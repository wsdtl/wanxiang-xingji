"""构筑试炼的确定性、零收益、零状态污染和命令闭环测试。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services, install_game_services, restore_game_services  # noqa: E402
from game.cmd import 构筑试炼 as build_trial_component  # noqa: E402,F401
from game.cmd.构筑试炼 import service as build_trial_command_service  # noqa: E402
from game.cmd import 角色 as character_component  # noqa: E402,F401
from game.cmd import 休息 as rest_component  # noqa: E402,F401
from game.content import (  # noqa: E402
    BUILD_TRIAL_ENDURANCE_ID,
    BUILD_TRIAL_GROUP_ID,
    BUILD_TRIAL_SINGLE_ID,
)
from game.content.catalog.trial import BuildTrialModeDefinition  # noqa: E402
from game.core.persistence import CHARACTER_AGGREGATE  # noqa: E402
from launch.adapter.local import LocalEventHandler, dispatch  # noqa: E402
from launch.adapter.qq import QqEventHandler  # noqa: E402


def main() -> None:
    asyncio.run(_main())
    print("build trial tests passed")


async def _main() -> None:
    for command in ("构筑试炼", "开始试炼"):
        assert len(LocalEventHandler.exact_rules[command]) == 1
        assert len(QqEventHandler.exact_rules[command]) == 1

    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "build-trial.db",
            identity_secret="build-trial-test-secret",
        )
        services.database.initialize()
        previous = install_game_services(services)
        try:
            await LocalEventHandler.run()
            await _dispatch("创建角色 试剑者", "build-trial-create")
            character_id = _character_id(services)

            extension_mode = BuildTrialModeDefinition(
                "trial.mode.extension_check",
                "扩展校验",
                "确认新增模式不需要修改命令组件",
                "enemy.build_trial.single",
                "扩展校准体",
                1,
                10,
                20,
                "build-trial.extension-check",
            )
            extended_actions = build_trial_command_service._mode_actions(
                (*services.content.build_trials.definitions(), extension_mode)
            )
            assert extended_actions[-1].id == "build_trial.extension_check"
            assert extended_actions[-1].label == "扩展校验"
            assert extended_actions[-1].data == "开始试炼 扩展校验"

            menu = await _dispatch("构筑试炼", "build-trial-menu")
            menu_message = menu.replies[0].message
            assert all(value in menu_message.content for value in ("单体", "群体", "持久"))
            assert {value.label for value in menu_message.actions} == {"单体", "群体", "持久"}

            invalid = await _dispatch("开始试炼 未知模式", "build-trial-invalid")
            invalid_message = invalid.replies[0].message
            assert "请选择单体、群体、持久模式" in invalid_message.content
            assert {value.label for value in invalid_message.actions} == {"单体", "群体", "持久"}

            await _dispatch("休息", "build-trial-rest")
            snapshots_before = _snapshot_rows(services)
            result_messages = {}
            for index, name in enumerate(("单体", "群体", "持久"), start=1):
                dispatched = await _dispatch(
                    f"开始试炼 {name}",
                    f"build-trial-command-{index}",
                )
                message = dispatched.replies[0].message
                result_messages[name] = message
                assert f"构筑试炼·{name}" in message.content
                assert "查看完整战报" in message.content
                assert "未修改血气、灵力、药品、行动、经验或资产" in message.content
                assert {value.label for value in message.actions} == {"再次试炼", "更换模式"}
            assert _snapshot_rows(services) == snapshots_before

            now = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)
            first = services.build_trials.run(
                "deterministic-a",
                character_id,
                BUILD_TRIAL_SINGLE_ID,
                logical_time=now,
            )
            second = services.build_trials.run(
                "deterministic-b",
                character_id,
                BUILD_TRIAL_SINGLE_ID,
                logical_time=now,
            )
            assert first.outcome is not None and second.outcome is not None
            assert first.outcome.metrics == second.outcome.metrics
            assert first.outcome.victory
            assert first.outcome.metrics.enemies_defeated == 1
            assert tuple(value.kind for value in first.outcome.trace.events) == tuple(
                value.kind for value in second.outcome.trace.events
            )
            assert _snapshot_rows(services) == snapshots_before

            expected_participants = {
                BUILD_TRIAL_SINGLE_ID: 2,
                BUILD_TRIAL_GROUP_ID: 6,
                BUILD_TRIAL_ENDURANCE_ID: 2,
            }
            for index, mode_id in enumerate(expected_participants, start=1):
                result = services.build_trials.run(
                    f"report-{index}",
                    character_id,
                    mode_id,
                    logical_time=now,
                )
                assert result.report is not None and result.outcome is not None
                view = services.battle_reports.load_public(
                    result.report.share_id,
                    logical_time=now,
                )
                assert view is not None and view.detail_available
                assert view.mode_id.startswith("battle.mode.build_trial.")
                assert len(view.segments) == 1
                segment = view.segments[0]
                assert len(segment.combatants) == expected_participants[mode_id]
                assert len(segment.initial_participants) == expected_participants[mode_id]
                assert segment.events and segment.transitions
                assert any(value.kind == "turn" for value in segment.transitions)
                assert segment.final_participants
                defeated_ids = {
                    value.target_id
                    for value in result.outcome.trace.events
                    if value.kind == "combat.target.defeated"
                    and value.target_id in result.outcome.enemy_entity_ids
                }
                assert result.outcome.metrics.enemies_defeated == len(defeated_ids)
            assert _snapshot_rows(services) == snapshots_before
        finally:
            restore_game_services(previous)


async def _dispatch(command: str, event_id: str):
    return await dispatch(
        client_id="build-trial-player",
        raw_message=command,
        sender_name="试炼玩家",
        event_id=event_id,
    )


def _character_id(services) -> str:
    with services.database.unit_of_work(write=False) as uow:
        row = uow.connection.execute(
            "SELECT aggregate_id FROM aggregate_snapshot WHERE aggregate_kind = ?",
            (CHARACTER_AGGREGATE,),
        ).fetchone()
    assert row is not None
    return str(row[0])


def _snapshot_rows(services) -> tuple[tuple[object, ...], ...]:
    with services.database.unit_of_work(write=False) as uow:
        rows = uow.connection.execute(
            """
            SELECT aggregate_kind, aggregate_id, revision, payload
            FROM aggregate_snapshot
            ORDER BY aggregate_kind, aggregate_id
            """
        ).fetchall()
    return tuple(tuple(row) for row in rows)


if __name__ == "__main__":
    main()
