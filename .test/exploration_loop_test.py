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
from game.content.catalog.character import REST_FULL_RECOVERY_SECONDS  # noqa: E402
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
from game.core.gameplay import (  # noqa: E402
    HEALTH_CURRENT,
    SPIRIT_CURRENT,
    SeededRandomSource,
)
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
    ExplorationRestReason,
    ExplorationState,
    ExplorationStatus,
    ExplorationStopReason,
    record_batch,
    resume_exploration,
    start_exploration,
)


TIME = datetime(2026, 7, 18, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
    _assert_content()
    _assert_generation()
    _assert_batch_limit()
    _assert_rest_state_machine()
    _assert_persisted_loop()
    _assert_auto_rest_loop()
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


def _assert_rest_state_machine() -> None:
    state = start_exploration(
        "rest-state-character",
        "rest-state-session",
        "exploration.region.r1",
        "location.test",
        logical_time=TIME,
    )
    resolved_at = TIME + timedelta(seconds=EXPLORATION_BATCH_SECONDS)
    plan = ExplorationBatchPlan(
        state.session_id,
        1,
        state.region_id,
        state.location_id,
        ExplorationEncounterKind.NORMAL,
        1,
        "rest-state-seed",
        encounter=object(),
    )
    resting = record_batch(
        state,
        ExplorationBatchResult(plan, resolved_at, health_after=0, spirit_after=0),
        rest_reason=ExplorationRestReason.DEFEATED,
        rest_completes_at=resolved_at + timedelta(seconds=REST_FULL_RECOVERY_SECONDS),
    )
    assert resting.completed_batches == 1
    assert resting.defeats == 1
    assert resting.status is ExplorationStatus.RESTING
    assert resting.session_id == state.session_id
    resumed = resume_exploration(
        resting,
        logical_time=resting.rest_completes_at,
    )
    assert resumed.status is ExplorationStatus.RUNNING
    assert resumed.session_id == state.session_id
    assert resumed.completed_batches == 1
    assert resumed.rest_count == 1
    assert resumed.rest_seconds == REST_FULL_RECOVERY_SECONDS
    assert resumed.next_batch_at == TIME + timedelta(minutes=30)


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
        assert blocked.status == "exploring"

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
        current_fingerprint = services.content.catalog.report.content_fingerprint
        assert services.battle_reports.reference(
            exploration_battle_report_id(
                started.state.session_id,
                current_fingerprint,
            )
        ) is None

        old_fingerprint = "content-fingerprint.before-upgrade"
        prepared_before_upgrade = services.exploration.settlement._prepare_next(
            character_id,
            logical_time=TIME + timedelta(seconds=EXPLORATION_BATCH_SECONDS),
        )
        assert prepared_before_upgrade is not None
        assert prepared_before_upgrade.report is not None
        legacy_report_id = f"battle-report:{started.state.session_id}"
        old_reference = services.battle_reports.capture(
            replace(
                prepared_before_upgrade.report.draft,
                report_id=legacy_report_id,
                content_fingerprint=old_fingerprint,
            )
        )

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
            current_report_id = exploration_battle_report_id(
                settled.state.session_id,
                current_fingerprint,
            )
            reference = services.battle_reports.reference(
                current_report_id
            )
            assert reference is not None
            assert reference.report_id != old_reference.report_id
            assert reference.share_id != old_reference.share_id
            old_report = services.battle_reports.load_public(
                old_reference.share_id,
                logical_time=TIME + timedelta(seconds=EXPLORATION_BATCH_SECONDS),
            )
            assert old_report is not None
            assert old_report.content_fingerprint == old_fingerprint
            report = services.battle_reports.load_public(
                reference.share_id,
                logical_time=TIME + timedelta(seconds=EXPLORATION_BATCH_SECONDS),
            )
            assert report is not None and report.segments
            assert report.content_fingerprint == current_fingerprint
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


def _assert_auto_rest_loop() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "exploration-auto-rest.db"
        services = build_game_services(
            database_path=path,
            identity_secret="exploration-auto-rest-secret",
        )
        services.database.initialize()
        evidence = IdentityEvidence(
            "exploration-auto-rest-evidence",
            ExternalIdentity(
                "platform.local",
                "exploration-auto-rest",
                "identity.user",
                "private",
                "player-auto-rest",
            ),
            (),
            "message.local",
            TIME,
        )
        created = services.create_character(evidence, requested_name="守夜客")
        assert created.status == "created" and created.receipt is not None
        character_id = created.receipt.character.id
        world_id = created.receipt.character_world.world_id
        region = services.content.exploration_regions.definitions()[0]
        moved = services.world_travel.move(
            character_id,
            services.content.worlds.require_binding_for_display(
                world_id,
                region.location_id,
            ).anchor_id,
            logical_time=TIME,
        )
        assert moved.status == "moved"
        started = services.exploration.start(character_id, logical_time=TIME)
        assert started.state is not None
        session_id = started.state.session_id

        original_simulate = services.exploration.settlement._simulate_batch
        medicine_called = False

        def low_resources(*args, **kwargs):
            simulation = original_simulate(*args, **kwargs)
            return replace(simulation, health_after=0, spirit_after=0)

        def no_medicine_available(uow, character, *args, **kwargs):
            nonlocal medicine_called
            medicine_called = True
            return character, ()

        with patch.object(
            services.exploration.settlement,
            "_simulate_batch",
            side_effect=low_resources,
        ), patch.object(
            services.exploration.settlement.medicine,
            "apply",
            side_effect=no_medicine_available,
        ):
            settled = services.exploration.settle_due(
                character_id,
                logical_time=TIME + timedelta(minutes=10),
            )
        assert medicine_called
        assert len(settled.batches) == 1
        assert settled.state is not None
        assert settled.state.status is ExplorationStatus.RESTING
        assert settled.state.session_id == session_id
        assert settled.state.completed_batches == 1
        assert settled.state.rest_count == 1
        assert settled.state.rest_completes_at == TIME + timedelta(minutes=20)
        assert settled.state.next_batch_at == TIME + timedelta(minutes=30)
        action_state = services.actions.load(character_id)
        assert action_state is not None and len(action_state.running()) == 1
        action = action_state.running()[0]
        assert action.snapshot.values["exploration_session_id"] == session_id
        assert action.started_at == TIME + timedelta(minutes=10)
        assert action.completes_at == TIME + timedelta(minutes=20)

        restarted = build_game_services(
            database_path=path,
            identity_secret="exploration-auto-rest-secret",
        )
        restarted.database.initialize()
        waiting = restarted.exploration.load(
            character_id,
            logical_time=TIME + timedelta(minutes=19),
        )
        assert waiting.state is not None
        assert waiting.state.status is ExplorationStatus.RESTING
        completed = restarted.exploration.load(
            character_id,
            logical_time=TIME + timedelta(minutes=20),
        )
        assert completed.batches == ()
        assert completed.state is not None
        assert completed.state.status is ExplorationStatus.RUNNING
        assert completed.state.session_id == session_id
        assert completed.state.completed_batches == 1
        assert completed.state.rest_count == 1
        assert completed.state.rest_seconds == REST_FULL_RECOVERY_SECONDS
        assert completed.state.next_batch_at == TIME + timedelta(minutes=30)
        recovery = restarted.rest.view(
            character_id,
            logical_time=TIME + timedelta(minutes=20),
        )
        assert recovery.status == "idle" and recovery.character is not None
        assert recovery.character.resources[HEALTH_CURRENT] == recovery.health_maximum
        assert recovery.character.resources[SPIRIT_CURRENT] == recovery.spirit_maximum

        original_simulate = restarted.exploration.settlement._simulate_batch

        def low_resources_again(*args, **kwargs):
            simulation = original_simulate(*args, **kwargs)
            return replace(simulation, health_after=0, spirit_after=0)

        with patch.object(
            restarted.exploration.settlement,
            "_simulate_batch",
            side_effect=low_resources_again,
        ), patch.object(
            restarted.exploration.settlement.medicine,
            "apply",
            side_effect=lambda uow, character, *args, **kwargs: (character, ()),
        ):
            second_rest = restarted.exploration.settle_due(
                character_id,
                logical_time=TIME + timedelta(minutes=30),
            )
        assert second_rest.state is not None
        assert second_rest.state.status is ExplorationStatus.RESTING
        assert second_rest.state.session_id == session_id
        assert second_rest.state.completed_batches == 2
        assert second_rest.state.rest_count == 2

        stopped = restarted.exploration.stop(
            character_id,
            logical_time=TIME + timedelta(minutes=35),
        )
        assert stopped.status == "stopped" and stopped.state is not None
        assert stopped.state.status is ExplorationStatus.STOPPED
        assert stopped.state.session_id == session_id
        assert stopped.state.completed_batches == 2
        assert stopped.state.rest_count == 2
        assert stopped.state.rest_seconds == REST_FULL_RECOVERY_SECONDS + 5 * 60
        action_state = restarted.actions.load(character_id)
        assert action_state is not None and action_state.running() == ()
        returned = restarted.world_travel.move(
            character_id,
            restarted.content.worlds.require_binding_for_display(
                world_id,
                STARTING_CITY_ID,
            ).anchor_id,
            logical_time=TIME + timedelta(minutes=36),
        )
        assert returned.status == "moved"

        returned_to_region = restarted.world_travel.move(
            character_id,
            restarted.content.worlds.require_binding_for_display(
                world_id,
                region.location_id,
            ).anchor_id,
            logical_time=TIME + timedelta(minutes=37),
        )
        assert returned_to_region.status == "moved"
        restarted.set_auto_rest(
            character_id,
            False,
            logical_time=TIME + timedelta(minutes=37),
        )
        direct_stop = restarted.exploration.start(
            character_id,
            logical_time=TIME + timedelta(minutes=37),
        )
        assert direct_stop.status == "started"
        original_simulate = restarted.exploration.settlement._simulate_batch

        def force_defeat(*args, **kwargs):
            simulation = original_simulate(*args, **kwargs)
            if simulation.plan.encounter is None:
                return simulation
            return replace(
                simulation,
                victory=False,
                draw=False,
                health_after=0,
                spirit_after=0,
            )

        defeated = None
        with patch.object(
            restarted.exploration.settlement,
            "_simulate_batch",
            side_effect=force_defeat,
        ):
            for index in range(1, 21):
                defeated_at = TIME + timedelta(minutes=37 + index * 10)
                defeated = restarted.exploration.settle_due(
                    character_id,
                    logical_time=defeated_at,
                )
                if defeated.state is not None and defeated.state.status is ExplorationStatus.STOPPED:
                    break
        assert defeated is not None and defeated.state is not None
        assert defeated.state.status is ExplorationStatus.STOPPED
        assert defeated.state.stop_reason is ExplorationStopReason.DEFEATED
        assert defeated.state.defeats == 1

        manual_rest = restarted.rest.start(
            "exploration-test-recover-after-direct-stop",
            character_id,
            logical_time=defeated_at + timedelta(minutes=1),
        )
        assert manual_rest.status == "started"
        recovered = restarted.rest.stop(
            "exploration-test-recovered-after-direct-stop",
            character_id,
            logical_time=defeated_at + timedelta(minutes=11),
        )
        assert recovered.status == "completed"
        restarted.set_auto_rest(
            character_id,
            True,
            logical_time=defeated_at + timedelta(minutes=11),
        )
        invalid_session = restarted.exploration.start(
            character_id,
            logical_time=defeated_at + timedelta(minutes=12),
        )
        assert invalid_session.status == "started"
        with patch.object(
            restarted.exploration.settlement,
            "_location_valid",
            return_value=False,
        ):
            invalid = restarted.exploration.settle_due(
                character_id,
                logical_time=defeated_at + timedelta(minutes=22),
            )
        assert invalid.batches == ()
        assert invalid.state is not None
        assert invalid.state.status is ExplorationStatus.STOPPED
        assert invalid.state.stop_reason is ExplorationStopReason.INVALID_LOCATION
        assert invalid.state.completed_batches == 0


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
