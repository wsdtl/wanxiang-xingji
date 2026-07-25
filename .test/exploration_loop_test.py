"""首版持续探险从内容、持久化到命令注册的闭环巡检。"""

from __future__ import annotations

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

from game.app import build_game_services  # noqa: E402
from game.features.exploration import (  # noqa: E402
    MAX_EXPLORATION_BATCHES,
    exploration_battle_report_id,
)
from game.content import build_official_content  # noqa: E402
from game.content.catalog.enemy import (  # noqa: E402
    AWARD_BOSS_TROPHY_ID,
    AWARD_PARTY_BOSS_TROPHY_ID,
    AWARD_DRAW_TICKET_ID,
    AWARD_ENEMY_TROPHY_ID,
    AWARD_LARGE_HEALTH_MEDICINE_ID,
    AWARD_LARGE_SPIRIT_MEDICINE_ID,
    AWARD_MEDIUM_HEALTH_MEDICINE_ID,
    AWARD_MEDIUM_SPIRIT_MEDICINE_ID,
    AWARD_RANDOM_EQUIPMENT_ID,
    AWARD_RANDOM_WEAPON_ID,
    AWARD_REGION_TROPHY_ID,
    AWARD_SMALL_HEALTH_MEDICINE_ID,
    AWARD_SMALL_SPIRIT_MEDICINE_ID,
    AWARD_WORLD_CURIO_ID,
    ENEMY_LOOT_TABLES,
)
from game.content.catalog.exploration import (  # noqa: E402
    EXPLORATION_BATCH_SECONDS,
    EXPLORATION_REGION_CATALOG,
    REGULAR_EXPLORATION_REGIONS,
    SPECIAL_EXPLORATION_REGIONS,
)
from game.content.catalog.world import (  # noqa: E402
    GREEN_CLOUD_PLAIN_ID,
    STARTING_CITY_ID,
    SUNSET_RIDGE_ID,
    TAIXUAN_WORLD_SPACE_ID,
    MAGIC_WORLD_SPACE_ID,
)
from game.content.catalog.item import TROPHY_ITEMS  # noqa: E402
from game.core.account import ExternalIdentity, IdentityEvidence  # noqa: E402
from game.core.gameplay import SeededRandomSource  # noqa: E402
from game.rules.character import (  # noqa: E402
    CHARACTER_SETTINGS_AGGREGATE,
    CharacterSettingsState,
)
from game.rules.encounter import EnemyEncounterGenerator  # noqa: E402
from game.rules.exploration import (  # noqa: E402
    EXPLORATION_AGGREGATE,
    ExplorationBatchPlan,
    ExplorationBatchPlanner,
    ExplorationBatchResult,
    ExplorationEncounterKind,
    ExplorationState,
    ExplorationStatus,
    ExplorationStopReason,
    record_batch,
    start_exploration,
)


TIME = datetime(2026, 7, 18, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
    _assert_content()
    _assert_generation()
    _assert_batch_limit()
    _assert_persisted_loop()
    print("exploration loop tests passed")


def _assert_batch_limit() -> None:
    state = start_exploration(
        "batch-limit-character",
        "batch-limit-session",
        "exploration.region.r1",
        "location.test",
        logical_time=TIME,
    )
    state = replace(
        state,
        batch_index=MAX_EXPLORATION_BATCHES - 1,
        completed_batches=MAX_EXPLORATION_BATCHES - 1,
    )
    plan = ExplorationBatchPlan(
        state.session_id,
        MAX_EXPLORATION_BATCHES,
        state.region_id,
        state.location_id,
        ExplorationEncounterKind.EMPTY,
        1,
        "batch-limit-seed",
    )
    next_state = record_batch(
        state,
        ExplorationBatchResult(plan, TIME + timedelta(minutes=10)),
        stop_reason=ExplorationStopReason.BATCH_LIMIT,
    )
    assert next_state.completed_batches == MAX_EXPLORATION_BATCHES
    assert next_state.status is ExplorationStatus.STOPPED
    assert next_state.stop_reason is ExplorationStopReason.BATCH_LIMIT


def _assert_content() -> None:
    content = build_official_content()
    for space_id in (TAIXUAN_WORLD_SPACE_ID, MAGIC_WORLD_SPACE_ID):
        space = content.catalog.world.spaces.require(space_id)
        assert (space.minimum_x, space.minimum_y) == (-100, -100)
        assert (space.maximum_x, space.maximum_y) == (100, 100)
    assert len(EXPLORATION_REGION_CATALOG.definitions()) == 13
    assert len(REGULAR_EXPLORATION_REGIONS) == 10
    assert len(SPECIAL_EXPLORATION_REGIONS) == 3
    assert len(TROPHY_ITEMS) == 210
    assert all(len(region.trophy_item_ids) == 6 for region in EXPLORATION_REGION_CATALOG.definitions())
    assert content.projector.name(SPECIAL_EXPLORATION_REGIONS[0].location_id) == "万剑冢"
    assert content.projector.name(SPECIAL_EXPLORATION_REGIONS[1].location_id) == "天工遗府"
    assert content.projector.name(SPECIAL_EXPLORATION_REGIONS[2].location_id) == "归墟魔渊"
    award_ids = {
        entry.award_id
        for table in ENEMY_LOOT_TABLES
        for group in table.groups
        for entry in group.entries
        if entry.award_id is not None
    }
    assert award_ids == {
        AWARD_BOSS_TROPHY_ID,
        AWARD_PARTY_BOSS_TROPHY_ID,
        AWARD_DRAW_TICKET_ID,
        AWARD_ENEMY_TROPHY_ID,
        AWARD_LARGE_HEALTH_MEDICINE_ID,
        AWARD_LARGE_SPIRIT_MEDICINE_ID,
        AWARD_MEDIUM_HEALTH_MEDICINE_ID,
        AWARD_MEDIUM_SPIRIT_MEDICINE_ID,
        AWARD_RANDOM_EQUIPMENT_ID,
        AWARD_RANDOM_WEAPON_ID,
        AWARD_REGION_TROPHY_ID,
        AWARD_SMALL_HEALTH_MEDICINE_ID,
        AWARD_SMALL_SPIRIT_MEDICINE_ID,
        AWARD_WORLD_CURIO_ID,
    }


def _assert_generation() -> None:
    content = build_official_content()
    planner = ExplorationBatchPlanner(
        content.exploration_regions,
        EnemyEncounterGenerator(
            content.catalog.enemies,
            content_version=content.catalog.report.content_fingerprint,
        ),
    )
    left = planner.plan(
        session_id="exploration-test",
        batch_index=1,
        region_id=REGULAR_EXPLORATION_REGIONS[0].id,
        character_level=1,
        random=SeededRandomSource("exploration-test"),
    )
    right = planner.plan(
        session_id="exploration-test",
        batch_index=1,
        region_id=REGULAR_EXPLORATION_REGIONS[0].id,
        character_level=1,
        random=SeededRandomSource("exploration-test"),
    )
    assert left == right
    assert left.enemy_level == 1
    if left.encounter_kind is ExplorationEncounterKind.EMPTY:
        assert left.encounter is None
    else:
        assert left.encounter is not None
        assert all(
            enemy.definition_id in REGULAR_EXPLORATION_REGIONS[0].regular_enemy_ids
            or enemy.definition_id in REGULAR_EXPLORATION_REGIONS[0].boss_enemy_ids
            for enemy in left.encounter.enemies
        )


def _assert_persisted_loop() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "exploration.db"
        services = build_game_services(
            database_path=path,
            identity_secret="exploration-loop-secret",
        )
        services.character_creation.workflow.id_factory = lambda kind: f"{kind}-fixed"
        services.database.initialize()
        evidence = IdentityEvidence(
            "exploration-evidence",
            ExternalIdentity(
                "platform.local",
                "exploration-test",
                "identity.user",
                "private",
                "player-a",
            ),
            (),
            "message.local",
            TIME,
        )
        created = services.create_character(evidence, requested_name="巡山客")
        assert created.status == "created" and created.receipt is not None
        character_id = created.receipt.character.id
        world_id = created.receipt.character_world.world_id

        def anchor(display_id: str) -> str:
            return services.content.worlds.require_binding_for_display(
                world_id,
                display_id,
            ).anchor_id

        moved = services.world_travel.move(
            character_id,
            anchor(GREEN_CLOUD_PLAIN_ID),
            logical_time=TIME,
        )
        assert moved.status == "moved"
        started = services.exploration.start(character_id, logical_time=TIME)
        assert started.status == "started" and started.state is not None
        assert started.state.next_batch_at == TIME + timedelta(seconds=EXPLORATION_BATCH_SECONDS)
        blocked = services.world_travel.move(
            character_id,
            anchor(SUNSET_RIDGE_ID),
            logical_time=TIME,
        )
        assert blocked.status == "main_action_occupied"

        before_failure = _persistent_state(services)
        simulation_started = Event()
        release_simulation = Event()
        original_simulate = services.exploration.settlement._simulate_batch

        def blocking_simulate(*args, **kwargs):
            simulation_started.set()
            if not release_simulation.wait(timeout=5):
                raise TimeoutError("测试未及时释放探险模拟")
            return original_simulate(*args, **kwargs)

        def unrelated_write() -> bool:
            with services.database.unit_of_work() as uow:
                uow.insert_transaction(
                    "test:exploration:unrelated-write",
                    "unrelated-fingerprint",
                    character_id,
                    "{}",
                    TIME.isoformat(),
                )
                uow.commit()
            return True

        with patch.object(
            services.battle_reports,
            "capture_prepared_in_uow",
            side_effect=RuntimeError("injected exploration report failure"),
        ), patch.object(
            services.exploration.settlement,
            "_simulate_batch",
            side_effect=blocking_simulate,
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                settlement = executor.submit(
                    services.exploration.settle_due,
                    character_id,
                    logical_time=TIME + timedelta(seconds=EXPLORATION_BATCH_SECONDS),
                )
                assert simulation_started.wait(timeout=5)
                writer = executor.submit(unrelated_write)
                try:
                    assert writer.result(timeout=2)
                    before_failure = _persistent_state(services)
                finally:
                    release_simulation.set()
                try:
                    settlement.result(timeout=10)
                except RuntimeError as exc:
                    assert str(exc) == "injected exploration report failure"
                else:
                    raise AssertionError("战报失败应中止整批探险结算")
        assert _persistent_state(services) == before_failure
        assert services.battle_reports.reference(
            exploration_battle_report_id(started.state.session_id)
        ) is None

        simulations = 0
        original_simulate = services.exploration.settlement._simulate_batch

        def make_first_result_stale(*args, **kwargs):
            nonlocal simulations
            simulations += 1
            result = original_simulate(*args, **kwargs)
            if simulations == 1:
                snapshots = services.character_creation.snapshots
                with services.database.unit_of_work() as uow:
                    settings = snapshots.require(
                        uow,
                        CHARACTER_SETTINGS_AGGREGATE,
                        character_id,
                        CharacterSettingsState,
                    )
                    snapshots.update(
                        uow,
                        CHARACTER_SETTINGS_AGGREGATE,
                        character_id,
                        settings,
                        replace(
                            settings,
                            mood_header_enabled=not settings.mood_header_enabled,
                            revision=settings.revision + 1,
                        ),
                        TIME,
                    )
                    uow.commit()
            return result

        with patch.object(
            services.exploration.settlement,
            "_simulate_batch",
            side_effect=make_first_result_stale,
        ):
            settled = services.exploration.settle_due(
                character_id,
                logical_time=TIME + timedelta(seconds=EXPLORATION_BATCH_SECONDS),
            )
        assert simulations == 2
        assert len(settled.batches) == 1
        assert settled.state is not None and settled.state.completed_batches == 1
        progress = services.world_progress.view(character_id, world_id).require_region(
            "exploration.region.r1"
        )
        batch = settled.batches[0]
        expected_progress = (
            {"normal": 1, "elite": 2, "boss": 5}[batch.plan.encounter_kind.value]
            if batch.victory
            else 0
        )
        assert progress.points == expected_progress
        if settled.batches[0].plan.encounter is not None:
            reference = services.battle_reports.reference(
                exploration_battle_report_id(settled.state.session_id)
            )
            assert reference is not None
            report = services.battle_reports.load_public(
                reference.share_id,
                logical_time=TIME + timedelta(seconds=EXPLORATION_BATCH_SECONDS),
            )
            assert report is not None and report.segments
            assert report.segments[0].transitions
            assert all(
                transition.after.participants
                for transition in report.segments[0].transitions
            )
            assert report.segments[0].final_participants
        repeated = services.exploration.settle_due(
            character_id,
            logical_time=TIME + timedelta(seconds=EXPLORATION_BATCH_SECONDS),
        )
        assert repeated.batches == ()
        assert repeated.state == settled.state

        restarted = build_game_services(
            database_path=path,
            identity_secret="exploration-loop-secret",
        )
        restarted.database.initialize()
        loaded = restarted.exploration.load(
            character_id,
            logical_time=TIME + timedelta(seconds=EXPLORATION_BATCH_SECONDS),
        )
        assert loaded.state == settled.state
        assert loaded.batches == ()
        with restarted.database.unit_of_work(write=False) as uow:
            encoded = restarted.character_creation.snapshots.require(
                uow,
                EXPLORATION_AGGREGATE,
                character_id,
                ExplorationState,
            )
        assert encoded == settled.state

        if loaded.state.status is ExplorationStatus.RUNNING:
            stopped = restarted.exploration.stop(character_id, logical_time=TIME + timedelta(minutes=11))
            assert stopped.status == "stopped"
            assert stopped.state is not None and stopped.state.status is ExplorationStatus.STOPPED

        returned = restarted.world_travel.move(
            character_id,
            restarted.content.worlds.require_binding_for_display(
                world_id,
                STARTING_CITY_ID,
            ).anchor_id,
            logical_time=TIME + timedelta(minutes=12),
        )
        assert returned.status in {"moved", "already_there"}


def _persistent_state(services):
    tables = (
        "aggregate_snapshot",
        "committed_transaction",
        "outbox_event",
        "fact_journal",
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
