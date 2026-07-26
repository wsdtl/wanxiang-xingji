"""次元灾厄内容、共享血量、本地命令和唯一遗羽闭环测试。"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import (  # noqa: E402
    build_game_services,
    install_game_services,
    restore_game_services,
)
from game.core.account import ExternalIdentity, IdentityEvidence  # noqa: E402
from game.content import (  # noqa: E402
    DIMENSION_SHIFT_ITEM_ID,
    DRAW_TICKET_ITEM_ID,
    INSCRIPTION_FEATHER_ITEM_ID,
    PLAYABLE_WORLD_IDS,
    build_dimensional_disaster_catalog,
)
from game.content.extensions import OFFICIAL_EXTENSION_CATALOG  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    COMBAT_ATTACK,
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    SPIRIT_MAXIMUM,
    ActivityState,
    CharacterState,
    GrantStack,
    InscriptionMediumData,
    InventoryState,
    InventoryTransaction,
    INSCRIPTION_MEDIUM_DATA_KEY,
    SeededRandomSource,
    SourceReceipt,
)
from game.core.persistence import (  # noqa: E402
    ACTIVITY_AGGREGATE,
    CHARACTER_AGGREGATE,
    INVENTORY_AGGREGATE,
)
from game.rules.activity import GLOBAL_ACTIVITY_SCOPE_ID  # noqa: E402
from game.rules import game_operation_context  # noqa: E402
from game.rules.disaster import (  # noqa: E402
    DIMENSIONAL_DISASTER_AGGREGATE,
    DimensionalDisasterOutcome,
    DimensionalDisasterState,
    DimensionalDisasterStatus,
    roll_draw_ticket_drop,
)
from game.cmd import 跃迁 as dimension_component  # noqa: E402,F401
from game.cmd import 跨界灾厄 as disaster_component  # noqa: E402,F401
from game.cmd import 角色 as character_component  # noqa: E402,F401
from game.cmd import 铭刻 as inscription_component  # noqa: E402,F401
from game.cmd.跨界灾厄 import service as disaster_command_service  # noqa: E402
from game.features.dimensional_disaster import service as disaster_feature_service  # noqa: E402
from game.features.battle_report import build_public_battle_report  # noqa: E402
from launch.adapter.local import LocalEventHandler, dispatch  # noqa: E402
from launch.adapter.qq import QqEventHandler  # noqa: E402


ZONE = ZoneInfo("Asia/Shanghai")
TIME = datetime(2026, 7, 13, 8, 0, tzinfo=ZONE)


def main() -> None:
    _assert_ended_during_simulation()
    asyncio.run(_main())
    print("dimensional disaster tests passed")


async def _main() -> None:
    assert roll_draw_ticket_drop(
        SeededRandomSource("no-damage"),
        chance=1_000_000,
        effective_damage=0,
        available_capacity=1,
    ) == 0
    assert roll_draw_ticket_drop(
        SeededRandomSource("guaranteed"),
        chance=1_000_000,
        effective_damage=1,
        available_capacity=1,
    ) == 1
    catalog = build_dimensional_disaster_catalog()
    assert catalog.definitions()
    assert sum(
        len(catalog.for_source(world_id))
        for world_id in OFFICIAL_EXTENSION_CATALOG.world_ids()
    ) == len(catalog.definitions())
    assert all(
        catalog.for_source(world_id)
        for world_id in OFFICIAL_EXTENSION_CATALOG.world_ids()
    )
    audit = catalog.audit()
    assert not audit.warnings
    assert {value.source_world_id for value in audit.sources} == set(
        OFFICIAL_EXTENSION_CATALOG.world_ids()
    )
    assert all(value.documented == 7 and value.original == 3 for value in audit.sources)

    for command in ("跨界灾厄", "讨伐灾厄", "灾厄排行"):
        assert len(LocalEventHandler.exact_rules[command]) == 1
        assert len(QqEventHandler.exact_rules[command]) == 1

    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "dimensional-disaster.db",
            identity_secret="dimensional-disaster-test-secret",
        )
        services.database.initialize()
        services.activities.initialize(GLOBAL_ACTIVITY_SCOPE_ID, logical_time=TIME)
        previous = install_game_services(services)
        original_now = disaster_command_service.command_time
        original_ticket_chance = disaster_feature_service.DIMENSIONAL_DISASTER_DRAW_TICKET_CHANCE
        disaster_command_service.command_time = lambda: TIME
        disaster_feature_service.DIMENSIONAL_DISASTER_DRAW_TICKET_CHANCE = 1_000_000
        try:
            await LocalEventHandler.run()
            await _dispatch("player-a", "创建角色 观星客", "create-a")
            await _dispatch("player-b", "创建角色 守夜人", "create-b")
            first_character, second_character = _characters(services)
            _grant_dimension_shift_item(services, first_character.id)

            status = await _dispatch("player-a", "跨界灾厄", "status-a")
            content = status.replies[0].message.content
            event = _event(services)
            assert event.source_world_id in set(PLAYABLE_WORLD_IDS)
            assert event.narrative.name in content
            assert "跨界灾厄" in content and "今日讨伐: _0/2_" in content
            assert services.global_activities.active(
                services.activities.load(GLOBAL_ACTIVITY_SCOPE_ID),
                logical_time=TIME,
            )

            initial_dimension = services.load_character_overview(first_character).overview.character_world
            target_world = next(
                value for value in PLAYABLE_WORLD_IDS
                if value != initial_dimension.world_id
            )
            await _dispatch("player-a", f"跃迁 {target_world}", "shift-a")
            shifted = await _dispatch("player-a", "跨界灾厄", "status-shifted")
            assert event.narrative.name in shifted.replies[0].message.content

            simulation_started = Event()
            release_simulation = Event()
            original_simulate = services.dimensional_disasters.battles.simulate

            def blocking_simulate(*args, **kwargs):
                simulation_started.set()
                if not release_simulation.wait(timeout=5):
                    raise TimeoutError("测试未及时释放灾厄战斗模拟")
                return original_simulate(*args, **kwargs)

            def unrelated_write() -> bool:
                with services.database.unit_of_work() as uow:
                    uow.insert_transaction(
                        "test:disaster:unrelated-write",
                        "unrelated-fingerprint",
                        first_character.id,
                        "{}",
                        TIME.isoformat(),
                    )
                    uow.commit()
                return True

            with patch.object(
                services.battle_reports,
                "capture_prepared_in_uow",
                side_effect=RuntimeError("injected disaster report failure"),
            ), patch.object(
                services.dimensional_disasters.battles,
                "simulate",
                side_effect=blocking_simulate,
            ):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    challenge_future = executor.submit(
                        services.dimensional_disasters.challenge,
                        first_character.id,
                        "disaster-lock-failure",
                        logical_time=TIME,
                    )
                    assert simulation_started.wait(timeout=5)
                    writer = executor.submit(unrelated_write)
                    try:
                        assert writer.result(timeout=2)
                        before_failure = _persistent_state(services)
                    finally:
                        release_simulation.set()
                    try:
                        challenge_future.result(timeout=10)
                    except RuntimeError as exc:
                        assert str(exc) == "injected disaster report failure"
                    else:
                        raise AssertionError("战报失败应回滚整次灾厄挑战")
            assert _persistent_state(services) == before_failure

            first = await _dispatch("player-a", "讨伐灾厄", "challenge-a-1")
            assert "伤痕" in first.replies[0].message.content
            assert "查看完整战报" in first.replies[0].message.content
            assert "/battle/" in first.replies[0].message.content
            with services.database.unit_of_work(write=False) as uow:
                share_id = uow.connection.execute(
                    "SELECT share_id FROM battle_report ORDER BY created_at LIMIT 1"
                ).fetchone()[0]
            battle_report = services.battle_reports.load_public(
                share_id,
                logical_time=TIME,
            )
            assert battle_report is not None and battle_report.segments
            first_segment = battle_report.segments[0]
            character_manifest = next(
                value for value in first_segment.combatants
                if value.unit_kind == "character"
            )
            disaster_manifest = next(
                value for value in first_segment.combatants
                if value.unit_kind == "dimensional_disaster"
            )
            assert character_manifest.projection_id == str(target_world)
            assert disaster_manifest.projection_id == str(event.source_world_id)
            disaster_projector = services.world_views.require(
                event.source_world_id
            ).projector
            expected_permanent_terms = (
                f"{event.narrative.name}·固有能力",
                disaster_projector.name(event.combat.rank_id),
                *(
                    disaster_projector.name(behavior_id)
                    for behavior_id in event.combat.behavior_ids
                ),
            )
            assert tuple(
                disaster_manifest.terms[f"enemy.source_{index}"].name
                for index in range(len(expected_permanent_terms))
            ) == expected_permanent_terms
            public_segment = build_public_battle_report(battle_report)["detail"][
                "segments"
            ][0]
            public_disaster = next(
                value
                for value in public_segment["initial_participants"]
                if value["unit_kind"] == "dimensional_disaster"
            )
            permanent_group = next(
                value
                for value in public_disaster["detail_groups"]
                if value["id"] == "permanent_effects"
            )
            assert tuple(
                value["label"] for value in permanent_group["items"]
            ) == expected_permanent_terms
            assert first_segment.transitions
            assert first_segment.final_participants
            assert all(value.after.participants for value in first_segment.transitions)
            replay = await _dispatch("player-a", "讨伐灾厄", "challenge-a-1")
            assert "重复消息" in replay.replies[0].message.content
            assert "战斗掉落" in replay.replies[0].message.content
            assert _event(services).attempts_today(first_character.id, "2026-07-13") == 1

            _restore_combat_resources(services, first_character.id, attack=10_000)
            second = await _dispatch("player-a", "讨伐灾厄", "challenge-a-2")
            assert "今日次数: _2/2_" in second.replies[0].message.content
            blocked = await _dispatch("player-a", "讨伐灾厄", "challenge-a-3")
            assert "今日讨伐次数已经用完" in blocked.replies[0].message.content

            event = _event(services)
            _set_event_health(services, event.event_id, 1)
            _restore_combat_resources(services, second_character.id, attack=10_000)
            defeated = await _dispatch("player-b", "讨伐灾厄", "challenge-b-1")
            assert "跨界灾厄已经被击破" in defeated.replies[0].message.content
            assert _event(services).outcome is DimensionalDisasterOutcome.DEFEATED

            ranking = await _dispatch("player-a", "灾厄排行", "ranking-a")
            assert "灾厄排行" in ranking.replies[0].message.content
            assert "观星客" in ranking.replies[0].message.content
            assert "守夜人" in ranking.replies[0].message.content

            event = _event(services)
            services.dimensional_disasters.maintain(
                logical_time=event.closes_at + timedelta(minutes=1)
            )
            closed = _event(services)
            assert closed.status is DimensionalDisasterStatus.CLOSED
            assert closed.feather_owner_id in {first_character.id, second_character.id}
            assert closed.feather_asset_id is not None
            assert closed.rewarded_character_ids == {first_character.id, second_character.id}

            feathers = []
            for character in (first_character, second_character):
                inventory = _inventory(services, character.id)
                feathers.extend(
                    value
                    for value in inventory.instances.values()
                    if value.definition_id == INSCRIPTION_FEATHER_ITEM_ID
                )
            assert len(feathers) == 1
            feather = feathers[0]
            assert feather.id == closed.feather_asset_id
            medium = feather.data[INSCRIPTION_MEDIUM_DATA_KEY]
            assert isinstance(medium, InscriptionMediumData)
            assert medium.title == f"{closed.narrative.name}遗羽"
            assert "2026-07-13" in medium.flavor_text
            assert "2 位归航者" in medium.flavor_text

            services.dimensional_disasters.maintain(
                logical_time=event.closes_at + timedelta(minutes=2)
            )
            assert sum(
                1
                for character in (first_character, second_character)
                for value in _inventory(services, character.id).instances.values()
                if value.definition_id == INSCRIPTION_FEATHER_ITEM_ID
            ) == 1
            activity = _activity(services)
            assert activity.instances[event.event_id].status.value == "closed"
            assert sum(
                value.quantity
                for character in (first_character, second_character)
                for value in _inventory(services, character.id).stacks.values()
                if value.definition_id == DRAW_TICKET_ITEM_ID
            ) == 3
        finally:
            disaster_command_service.command_time = original_now
            disaster_feature_service.DIMENSIONAL_DISASTER_DRAW_TICKET_CHANCE = original_ticket_chance
            restore_game_services(previous)


def _assert_ended_during_simulation() -> None:
    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "disaster-ended.db",
            identity_secret="disaster-ended-secret",
        )
        services.database.initialize()
        services.activities.initialize(GLOBAL_ACTIVITY_SCOPE_ID, logical_time=TIME)
        created = services.create_character(
            IdentityEvidence(
                "disaster-ended-evidence",
                ExternalIdentity(
                    "platform.local",
                    "disaster-ended",
                    "identity.user",
                    "private",
                    "disaster-ended-player",
                ),
                (),
                "message.local",
                TIME,
            ),
            requested_name="迟归者",
        )
        assert created.status == "created" and created.receipt is not None
        character_id = created.receipt.character.id
        services.dimensional_disasters.maintain(logical_time=TIME)
        event = _event(services)
        character_before = created.receipt.character
        inventory_before = _inventory(services, character_id)
        simulation_started = Event()
        release_simulation = Event()
        original_simulate = services.dimensional_disasters.battles.simulate

        def blocking_simulate(*args, **kwargs):
            simulation_started.set()
            if not release_simulation.wait(timeout=5):
                raise TimeoutError("测试未及时释放灾厄结束边界")
            return original_simulate(*args, **kwargs)

        with patch.object(
            services.dimensional_disasters.battles,
            "simulate",
            side_effect=blocking_simulate,
        ):
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    services.dimensional_disasters.challenge,
                    character_id,
                    "disaster-ended-during-simulation",
                    logical_time=TIME,
                )
                assert simulation_started.wait(timeout=5)
                snapshots = services.character_creation.snapshots
                with services.database.unit_of_work() as uow:
                    current = snapshots.require(
                        uow,
                        DIMENSIONAL_DISASTER_AGGREGATE,
                        event.event_id,
                        DimensionalDisasterState,
                    )
                    snapshots.update(
                        uow,
                        DIMENSIONAL_DISASTER_AGGREGATE,
                        current.event_id,
                        current,
                        replace(
                            current,
                            current_health=0,
                            outcome=DimensionalDisasterOutcome.DEFEATED,
                            defeated_at=TIME,
                            revision=current.revision + 1,
                        ),
                        TIME,
                    )
                    uow.commit()
                release_simulation.set()
                result = future.result(timeout=10)
        assert result.status == "ended"
        ended = _event(services)
        assert "disaster-ended-during-simulation" not in ended.challenge_receipts
        assert ended.attempts_today(character_id, "2026-07-13") == 0
        assert _inventory(services, character_id) == inventory_before
        with services.database.unit_of_work(write=False) as uow:
            character_after = services.character_creation.snapshots.require(
                uow,
                CHARACTER_AGGREGATE,
                character_id,
                CharacterState,
            )
        assert character_after == character_before
        assert services.battle_reports.reference(
            "battle-report:dimensional-disaster:disaster-ended-during-simulation"
        ) is None


async def _dispatch(client_id: str, command: str, event_id: str):
    return await dispatch(
        client_id=client_id,
        raw_message=command,
        sender_name=client_id,
        event_id=event_id,
    )


def _characters(services) -> tuple[CharacterState, CharacterState]:
    with services.database.unit_of_work(write=False) as uow:
        values = services.character_creation.snapshots.list(
            uow,
            CHARACTER_AGGREGATE,
            CharacterState,
            limit=10,
        )
    by_name = {value.name: value for value in values}
    return by_name["观星客"], by_name["守夜人"]


def _event(services) -> DimensionalDisasterState:
    with services.database.unit_of_work(write=False) as uow:
        values = services.character_creation.snapshots.list(
            uow,
            DIMENSIONAL_DISASTER_AGGREGATE,
            DimensionalDisasterState,
            limit=10,
        )
    assert len(values) == 1
    return values[0]


def _activity(services) -> ActivityState:
    with services.database.unit_of_work(write=False) as uow:
        return services.character_creation.snapshots.require(
            uow,
            ACTIVITY_AGGREGATE,
            GLOBAL_ACTIVITY_SCOPE_ID,
            ActivityState,
        )


def _inventory(services, character_id: str) -> InventoryState:
    with services.database.unit_of_work(write=False) as uow:
        return services.character_creation.snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            InventoryState,
        )


def _grant_dimension_shift_item(services, character_id: str) -> None:
    snapshots = services.character_creation.snapshots
    with services.database.unit_of_work() as uow:
        inventory = snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            InventoryState,
        )
        special = next(
            value.id
            for value in inventory.containers.values()
            if value.kind == "container.special"
        )
        outcome = services.inventory_engine.execute(
            InventoryTransaction(
                "disaster-test-grant-dimension-shift-item",
                character_id,
                "inventory.test_setup",
                (
                    GrantStack(
                        "stack:disaster-dimension-shift",
                        DIMENSION_SHIFT_ITEM_ID,
                        special,
                        1,
                        SourceReceipt(
                            "receipt:disaster-dimension-shift",
                            "source.test",
                            character_id,
                            TIME,
                        ),
                    ),
                ),
            ),
            state=inventory,
            context=game_operation_context(
                "disaster-test-grant-dimension-shift-item",
                logical_time=TIME,
            ),
        ).unwrap()
        snapshots.update(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            inventory,
            outcome.state,
            TIME,
        )
        uow.commit()


def _restore_combat_resources(services, character_id: str, *, attack: float) -> None:
    snapshots = services.character_creation.snapshots
    with services.database.unit_of_work() as uow:
        character = snapshots.require(
            uow,
            CHARACTER_AGGREGATE,
            character_id,
            CharacterState,
        )
        attributes = dict(character.core_attributes)
        attributes[COMBAT_ATTACK] = attack
        attributes[HEALTH_MAXIMUM] = 10_000
        attributes[SPIRIT_MAXIMUM] = 10_000
        updated = replace(
            character,
            core_attributes=attributes,
            resources={HEALTH_CURRENT: 10_000, SPIRIT_CURRENT: 10_000},
            revision=character.revision + 1,
        )
        snapshots.update(
            uow,
            CHARACTER_AGGREGATE,
            character_id,
            character,
            updated,
            TIME,
        )
        uow.commit()


def _set_event_health(services, event_id: str, health: int) -> None:
    snapshots = services.character_creation.snapshots
    with services.database.unit_of_work() as uow:
        event = snapshots.require(
            uow,
            DIMENSIONAL_DISASTER_AGGREGATE,
            event_id,
            DimensionalDisasterState,
        )
        updated = replace(event, current_health=health, revision=event.revision + 1)
        snapshots.update(
            uow,
            DIMENSIONAL_DISASTER_AGGREGATE,
            event_id,
            event,
            updated,
            TIME,
        )
        uow.commit()


def _persistent_state(services):
    tables = (
        "aggregate_snapshot",
        "committed_transaction",
        "outbox_event",
        "battle_report",
        "battle_report_segment",
    )
    with services.database.unit_of_work(write=False) as uow:
        return tuple(
            (
                table,
                tuple(
                    tuple(row)
                    for row in uow.connection.execute(
                        f"SELECT * FROM {table} ORDER BY 1, 2"
                    ).fetchall()
                ),
            )
            for table in tables
        )


if __name__ == "__main__":
    main()
