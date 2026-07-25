"""彩票命令通过本地驱动器的最终回复巡检。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services, install_game_services, restore_game_services  # noqa: E402
from game.cmd import 彩票 as lottery_component  # noqa: E402,F401
from game.cmd import 角色 as character_component  # noqa: E402,F401
from launch.adapter.local import LocalEventHandler, dispatch  # noqa: E402
from launch.adapter.qq import QqEventHandler  # noqa: E402


def main() -> None:
    asyncio.run(_main())
    print("lottery command tests passed")


async def _main() -> None:
    for command in ("彩票", "购票", "中奖记录"):
        assert len(LocalEventHandler.exact_rules[command]) == 1
        assert len(QqEventHandler.exact_rules[command]) == 1
    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "lottery-command.db",
            identity_secret="lottery-command-secret",
        )
        services.database.initialize()
        previous = install_game_services(services)
        try:
            await LocalEventHandler.run()
            now = datetime.now(ZoneInfo("Asia/Shanghai"))
            services.economy.initialize(logical_time=now)
            services.lottery.initialize(logical_time=now)
            await _dispatch("player", "创建角色 彩票客", "lottery-create")
            status = await _dispatch("player", "彩票", "lottery-status")
            assert "彩票系统" in status.replies[0].message.content, status.replies[0].message.content
            assert "尚未购票" in status.replies[0].message.content, status.replies[0].message.content
            assert "至少 2 人开奖" in status.replies[0].message.content
            assert [action.label for action in status.replies[0].message.actions] == [
                "购票",
                "中奖记录",
            ]
            assert status.replies[0].message.actions[0].behavior == "fill"
            chosen = await _dispatch(
                "player",
                "购票 123456",
                "lottery-purchase",
            )
            assert "123456" in chosen.replies[0].message.content
            second = await _dispatch("player", "购票 654321", "lottery-second")
            assert "123456" in second.replies[0].message.content
            assert "不能追加或更换" in second.replies[0].message.content
            multiple = await _dispatch(
                "player",
                "购票 111111 222222",
                "lottery-multiple",
            )
            assert "只能购买一张" in multiple.replies[0].message.content
            status = await _dispatch("player", "彩票", "lottery-status-after")
            assert "123456" in status.replies[0].message.content
            assert "654321" not in status.replies[0].message.content
            assert [action.label for action in status.replies[0].message.actions] == ["中奖记录"]
            invalid = await _dispatch("player", "购票 123", "lottery-invalid")
            assert "六位数字" in invalid.replies[0].message.content
            history = await _dispatch("player", "中奖记录", "lottery-history")
            assert "暂无中奖记录" in history.replies[0].message.content
        finally:
            restore_game_services(previous)


async def _dispatch(client_id: str, raw_message: str, event_id: str):
    return await dispatch(
        client_id=client_id,
        raw_message=raw_message,
        sender_name=client_id,
        event_id=event_id,
    )


if __name__ == "__main__":
    main()
