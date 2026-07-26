"""跨组件活动状态与可追加战报身份的防回归门禁。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.content.catalog.character import REST_ACTION_ID  # noqa: E402
from game.cmd.presentation import (  # noqa: E402
    activity_block_feedback,
    blocking_activity_recovery_action,
    health_depleted_feedback,
)
from game.app import build_game_services  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    ActionRecord,
    ActionSlotKind,
    ActionSnapshot,
    ActionState,
    ActionStatus,
)
from game.core.persistence import BattleReportStore, SqliteDatabase  # noqa: E402
from game.features.battle_report import (  # noqa: E402
    BattleReportService,
    PreparedBattleReport,
)
from game.features.player_activity import PlayerActivityBlock  # noqa: E402
from game.features.world_travel import WorldTravelResult  # noqa: E402
from game.rules.battle_report import (  # noqa: E402
    BattleReportDraft,
    BattleReportSummary,
    content_scoped_report_id,
)
from game.rules.exploration import (  # noqa: E402
    EXPLORATION_AGGREGATE,
    ExplorationRestReason,
    ExplorationStatus,
    ExplorationStopReason,
    start_exploration,
)
from game.rules.player_activity import (  # noqa: E402
    PlayerActivityKind,
    resolve_player_activity,
)


TIME = datetime(2026, 7, 26, 20, 0, tzinfo=timezone.utc)
CONTENT_FINGERPRINT = "content-fingerprint-v1"


def main() -> None:
    _assert_activity_projection()
    _assert_blocking_result_contract()
    _assert_missing_rest_action_auto_stops()
    _assert_all_blocking_features_use_projection()
    _assert_continued_report_identity_guard()
    print("state integrity contract tests passed")


def _assert_activity_projection() -> None:
    idle = resolve_player_activity(None, None)
    assert idle.kind is PlayerActivityKind.IDLE
    assert idle.blocking_status is None and idle.consistent

    rest_action = _action("rest:standalone")
    standalone = resolve_player_activity(_action_state(rest_action), None)
    assert standalone.kind is PlayerActivityKind.MAIN_ACTION
    assert standalone.main_action is rest_action
    assert standalone.blocking_status == "main_action_occupied"
    assert standalone.consistent

    exploration = start_exploration(
        "character-1",
        "exploration-session-1",
        "region.test",
        "location.test",
        logical_time=TIME,
    )
    running = resolve_player_activity(None, exploration)
    assert running.kind is PlayerActivityKind.EXPLORING
    assert running.blocking_status == "exploring" and running.consistent

    resting = replace(
        exploration,
        status=ExplorationStatus.RESTING,
        rest_reason=ExplorationRestReason.LOW_RESOURCES,
        rest_started_at=TIME,
        rest_completes_at=TIME + timedelta(minutes=10),
        revision=1,
    )
    managed_rest = _action(
        "rest:exploration",
        exploration_session_id=resting.session_id,
    )
    projected_rest = resolve_player_activity(
        _action_state(managed_rest),
        resting,
    )
    assert projected_rest.kind is PlayerActivityKind.EXPLORATION_RESTING
    assert projected_rest.main_action is managed_rest
    assert projected_rest.blocking_status == "exploring"
    assert projected_rest.consistent

    conflicting = resolve_player_activity(
        _action_state(managed_rest, _action("rest:unrelated", sequence=2)),
        resting,
    )
    assert conflicting.kind is PlayerActivityKind.EXPLORATION_RESTING
    assert conflicting.blocking_status == "exploring"
    assert "exploration_with_unrelated_main_action" in conflicting.consistency_issues

    orphaned = resolve_player_activity(_action_state(managed_rest), None)
    assert orphaned.kind is PlayerActivityKind.MAIN_ACTION
    assert "orphaned_exploration_rest_action" in orphaned.consistency_issues

    stop_action = blocking_activity_recovery_action("exploring")
    assert (stop_action.data, stop_action.behavior) == ("停止探险", "callback")
    view_action = blocking_activity_recovery_action("main_action_occupied")
    assert (view_action.data, view_action.behavior) == ("我的角色", "callback")

    running_feedback = activity_block_feedback(
        PlayerActivityBlock.from_projection("character-1", running),
        "跃迁",
    )
    resting_feedback = activity_block_feedback(
        PlayerActivityBlock.from_projection("character-1", projected_rest),
        "跃迁",
    )
    assert running_feedback.text == "当前正在探险，停止探险后才能跃迁"
    assert resting_feedback.text == "当前正在自动休整，停止探险后才能跃迁"
    assert running_feedback.recovery == resting_feedback.recovery

    health_feedback = health_depleted_feedback("开始探险")
    assert health_feedback.text == "当前血气已经归零，恢复后才能开始探险"
    assert tuple(action.data for action in health_feedback.recoveries) == (
        "休息",
        "纳戒",
    )
    teammate_health = health_depleted_feedback(
        "开始组队挑战",
        subject_name="队员甲",
        allow_recovery=False,
    )
    assert teammate_health.text == "队员甲的血气已经归零，恢复后才能开始组队挑战"
    assert not teammate_health.recoveries


def _assert_blocking_result_contract() -> None:
    try:
        WorldTravelResult("exploring")
    except ValueError as exc:
        assert "缺少精确玩家活动事实" in str(exc)
    else:
        raise AssertionError("活动阻塞结果不得只携带状态字符串")

    block = PlayerActivityBlock(
        "character-1",
        PlayerActivityKind.EXPLORATION_RESTING,
    )
    result = WorldTravelResult("exploring", activity_block=block)
    assert result.activity_block is block


def _assert_all_blocking_features_use_projection() -> None:
    gate_paths = (
        "game/features/companion/service.py",
        "game/features/dimension_shift/service.py",
        "game/features/dimensional_disaster/service.py",
        "game/features/exploration/service.py",
        "game/features/party_battle/service.py",
        "game/features/player/service.py",
        "game/features/rest/service.py",
        "game/features/world_travel/service.py",
    )
    for relative in gate_paths:
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "self.player_activity." in source, (
            f"{relative} 必须通过玩家活动业务端口判断状态"
        )

    resolver_users = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "game" / "features").rglob("*.py")
        if "resolve_player_activity(" in path.read_text(encoding="utf-8")
    }
    assert resolver_users == {"game/features/player_activity/service.py"}, (
        "玩法组件不得绕过玩家活动业务端口："
        f"{sorted(resolver_users)}"
    )

    activity_presenters = (
        "game/cmd/伙伴/service.py",
        "game/cmd/休息/service.py",
        "game/cmd/探险/service.py",
        "game/cmd/组队/battle.py",
        "game/cmd/跃迁/service.py",
        "game/cmd/跨界灾厄/service.py",
    )
    for relative in activity_presenters:
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "activity_block_feedback(" in source, (
            f"{relative} 必须通过统一活动阻塞展示契约生成文案和按钮"
        )

    health_presenters = (
        "game/cmd/伙伴/service.py",
        "game/cmd/探险/service.py",
        "game/cmd/组队/battle.py",
        "game/cmd/跨界灾厄/service.py",
    )
    for relative in health_presenters:
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "health_depleted_feedback(" in source, (
            f"{relative} 必须通过统一血气恢复契约生成文案和按钮"
        )

    raw_slot_users = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "game" / "features").rglob("*.py")
        if "ActionSlotKind" in path.read_text(encoding="utf-8")
    }
    assert raw_slot_users == {
        "game/features/data_lifecycle/snapshots.py",
        "game/features/rest/service.py",
    }, "新增主要行动判断必须进入统一玩家活动投影"
    raw_exploration_gates = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "game" / "features").rglob("*.py")
        if "exploration.active" in path.read_text(encoding="utf-8")
    }
    assert not raw_exploration_gates, (
        "探险占用判断必须进入统一玩家活动投影："
        f"{sorted(raw_exploration_gates)}"
    )


def _assert_missing_rest_action_auto_stops() -> None:
    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "missing-rest.db",
            identity_secret="state-integrity-secret",
        )
        services.database.initialize()
        exploration = start_exploration(
            "character-missing-rest",
            "session-missing-rest",
            "region.test",
            "location.test",
            logical_time=TIME,
        )
        resting = replace(
            exploration,
            status=ExplorationStatus.RESTING,
            rest_reason=ExplorationRestReason.LOW_RESOURCES,
            rest_started_at=TIME,
            rest_completes_at=TIME + timedelta(minutes=10),
            revision=1,
        )
        with services.database.unit_of_work() as uow:
            services.exploration.snapshots.insert(
                uow,
                EXPLORATION_AGGREGATE,
                resting.character_id,
                resting,
                TIME,
            )
            uow.commit()

        recovered = services.exploration.rest.resume_due(
            resting.character_id,
            logical_time=TIME + timedelta(minutes=1),
        )
        assert recovered is not None
        assert recovered.status is ExplorationStatus.STOPPED
        assert recovered.stop_reason is ExplorationStopReason.RECOVERY_INVALID


def _assert_continued_report_identity_guard() -> None:
    with TemporaryDirectory() as directory:
        database = SqliteDatabase(Path(directory) / "report-identity.db")
        database.initialize()
        service = BattleReportService(
            database,
            BattleReportStore(database),
            builder=None,
        )

        unsafe_id = "battle-report:continued-session"
        first = _prepared_report(unsafe_id, "segment-1")
        with database.unit_of_work() as uow:
            reference = service.capture_prepared_in_uow(uow, first)
            uow.commit()
        with database.unit_of_work() as uow:
            assert service.capture_prepared_in_uow(uow, first) == reference
            uow.commit()
        try:
            with database.unit_of_work() as uow:
                service.capture_prepared_in_uow(
                    uow,
                    _prepared_report(unsafe_id, "segment-2"),
                )
        except ValueError as exc:
            assert "内容指纹" in str(exc)
        else:
            raise AssertionError("未分代的战报身份不得追加第二个片段")

        safe_id = content_scoped_report_id(
            "battle-report:continued-session-safe",
            CONTENT_FINGERPRINT,
        )
        with database.unit_of_work() as uow:
            service.capture_prepared_in_uow(
                uow,
                _prepared_report(safe_id, "segment-1"),
            )
            service.capture_prepared_in_uow(
                uow,
                _prepared_report(safe_id, "segment-2"),
            )
            uow.commit()
        with database.unit_of_work(write=False) as uow:
            count = uow.connection.execute(
                "SELECT COUNT(*) FROM battle_report_segment WHERE report_id = ?",
                (safe_id,),
            ).fetchone()[0]
        assert count == 2


def _action(
    action_id: str,
    *,
    sequence: int = 1,
    exploration_session_id: str | None = None,
) -> ActionRecord:
    values = (
        {"exploration_session_id": exploration_session_id}
        if exploration_session_id is not None
        else {}
    )
    return ActionRecord(
        action_id,
        REST_ACTION_ID,
        sequence,
        ActionSlotKind.MAIN,
        ActionStatus.RUNNING,
        TIME,
        TIME + timedelta(minutes=10),
        ActionSnapshot(
            TIME,
            "rules.rest.test",
            CONTENT_FINGERPRINT,
            action_id,
            0,
            values=values,
        ),
    )


def _action_state(*actions: ActionRecord) -> ActionState:
    return ActionState(
        "character-1",
        {action.id: action for action in actions},
        max(action.sequence for action in actions) + 1,
    )


def _prepared_report(report_id: str, segment_id: str) -> PreparedBattleReport:
    segment = SimpleNamespace(
        segment_id=segment_id,
        started_at=TIME,
        finished_at=TIME,
    )
    return PreparedBattleReport(
        BattleReportDraft(
            report_id,
            "battle.mode.test",
            CONTENT_FINGERPRINT,
            BattleReportSummary("测试", "完成", (), "neutral"),
            segment,
        ),
        b"test-payload",
        12,
    )


if __name__ == "__main__":
    main()
