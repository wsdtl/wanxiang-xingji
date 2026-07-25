"""探险命令通过本地驱动器的最终回复巡检。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import (  # noqa: E402
    build_game_services,
    install_game_services,
    restore_game_services,
)
from game.cmd.探险.service import _start_message, _summary_message  # noqa: E402
from game.core.account import ExternalIdentity, IdentityEvidence  # noqa: E402
from game.features.exploration import ExplorationOperationResult  # noqa: E402
from game.rules.battle_report import BattleReportReference  # noqa: E402
from launch import config  # noqa: E402
from game.cmd import 探险 as exploration_component  # noqa: E402,F401
from game.cmd import 回收 as recycle_component  # noqa: E402,F401
from game.cmd import 角色 as character_component  # noqa: E402,F401
from launch.adapter.local import LocalEventHandler, dispatch  # noqa: E402
from launch.adapter.qq import QqEventHandler  # noqa: E402
from message import render_local_message  # noqa: E402


def main() -> None:
    asyncio.run(_main())
    print("exploration command tests passed")


async def _main() -> None:
    for command in (
        "探险",
        "前往",
        "开始探险",
        "停止探险",
        "探险总结",
        "回收战利品",
    ):
        assert len(LocalEventHandler.exact_rules[command]) == 1
        assert len(QqEventHandler.exact_rules[command]) == 1

    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "exploration-command.db",
            identity_secret="exploration-command-secret",
        )
        services.database.initialize()
        previous = install_game_services(services)
        try:
            await LocalEventHandler.run()
            await dispatch(
                client_id="exploration-player",
                raw_message="创建角色 巡山客",
                sender_name="巡山客",
                event_id="exploration-create",
            )
            listing = await dispatch(
                client_id="exploration-player",
                raw_message="探险",
                sender_name="巡山客",
                event_id="exploration-list",
            )
            content = listing.replies[0].message.content
            assert listing.replies[0].message.kind == "markdown"
            assert "常规区域" in content and "特殊区域" in content
            destination = next(
                name
                for name in ("青云原", "翠风平原", "生态穹原")
                if name in content
            )
            assert any(
                name in content for name in ("万剑冢", "英灵兵冢", "兵装墓库")
            )

            moved = await dispatch(
                client_id="exploration-player",
                raw_message=f"前往 {destination}",
                sender_name="巡山客",
                event_id="exploration-move",
            )
            assert "抵达:" in moved.replies[0].message.content

            started = await dispatch(
                client_id="exploration-player",
                raw_message="开始探险",
                sender_name="巡山客",
                event_id="exploration-start",
            )
            assert "首次结算" in started.replies[0].message.content
            assert started.replies[0].message.actions[0].data == "停止探险"

            summary = await dispatch(
                client_id="exploration-player",
                raw_message="探险总结",
                sender_name="巡山客",
                event_id="exploration-summary",
            )
            assert "药物掉落" in summary.replies[0].message.content
            assert "状态: _进行中_" in summary.replies[0].message.content
            assert summary.replies[0].message.actions[0].data == "回收战利品"

            logical_time = datetime.now(ZoneInfo(config.project.timezone))
            current = services.load_current_character(
                IdentityEvidence(
                    "exploration-summary-regression",
                    ExternalIdentity(
                        "platform.local",
                        config.project.name,
                        "identity.local_user",
                        "",
                        "exploration-player",
                    ),
                    (),
                    "identity.local_event",
                    logical_time,
                )
            )
            assert current.character is not None
            overview = services.load_character_overview(current.character).overview
            assert overview is not None
            blocked_message = _start_message(
                ExplorationOperationResult("main_action_occupied"),
                services.world_view(overview.character_world),
            )
            assert blocked_message.document.actions[0].data == "我的角色"
            state = services.exploration.load(
                current.character.id,
                logical_time=logical_time,
                settle_due=False,
            ).state
            assert state is not None
            regression_message = _summary_message(
                ExplorationOperationResult(
                    "ok",
                    replace(state, medicine_drops=1),
                ),
                overview,
                services.world_view(overview.character_world),
                BattleReportReference("report-regression", "share-regression"),
            )
            rendered_regression = render_local_message(regression_message)
            assert "药物数量为累计掉落" in rendered_regression.content
            assert "查看完整战报" in rendered_regression.content
            assert rendered_regression.actions[0].data == "回收战利品"

            empty_sale = await dispatch(
                client_id="exploration-player",
                raw_message="回收战利品",
                sender_name="巡山客",
                event_id="exploration-empty-sale",
            )
            assert "没有可回收的战利品" in empty_sale.replies[0].message.content
        finally:
            restore_game_services(previous)


if __name__ == "__main__":
    main()
