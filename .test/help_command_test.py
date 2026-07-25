"""帮助注册覆盖和本地驱动交互测试。"""

from __future__ import annotations

import asyncio
from importlib import import_module
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services, install_game_services, restore_game_services  # noqa: E402
from game.cmd.help_registry import HELP_CATEGORY_ORDER, help_registry  # noqa: E402
from launch.adapter.local import LocalEventHandler, dispatch  # noqa: E402
from launch.adapter.qq.render import render_qq_message  # noqa: E402
from main import create_app  # noqa: E402


def main() -> None:
    asyncio.run(_main())
    print("help command tests passed")


async def _main() -> None:
    # create_app 会导入 game.cmd 下全部二级组件；任何命令漏写 help 或 hidden 都会失败。
    create_app()
    assert help_registry.categories() == HELP_CATEGORY_ORDER
    assert help_registry.find("帮助") is not None
    assert help_registry.find("归航公约") is not None
    assert help_registry.find("探险") is not None
    assert help_registry.find("突破") is not None
    assert help_registry.find("world_events") is None
    assert help_registry.find("economy_recycle_confirm") is None

    help_service = import_module("game.cmd.帮助.service")
    home_payload = render_qq_message(help_service._home_message())
    assert home_payload["content"].count("mqqapi://aio/inlinecmd") == len(
        HELP_CATEGORY_ORDER
    )
    assert "keyboard" not in home_payload
    detail_payload = render_qq_message(
        help_service._detail_message(help_registry.find("开始探险"))
    )
    buttons = [
        button
        for row in detail_payload["keyboard"]["content"]["rows"]
        for button in row["buttons"]
    ]
    assert [button["action"]["data"] for button in buttons] == [
        "开始探险",
        "帮助 行动",
    ]
    assert all(button["action"]["enter"] for button in buttons)

    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "help.db",
            identity_secret="help-command-test-secret",
        )
        services.database.initialize()
        previous = install_game_services(services)
        try:
            await LocalEventHandler.run()

            home = await _dispatch("帮助", "help-home")
            home_content = _content(home)
            for category in HELP_CATEGORY_ORDER:
                assert category in home_content
            assert not home.replies[0].message.actions

            category = await _dispatch("帮助 行动", "help-category")
            category_content = _content(category)
            assert "开始探险" in category_content
            assert "结束休息" in category_content
            assert tuple(action.data for action in category.replies[0].message.actions) == (
                "帮助",
            )

            detail = await _dispatch("帮助 开始探险", "help-detail")
            detail_content = _content(detail)
            assert "每十分钟" in detail_content
            assert "占用当前主要行动" in detail_content
            assert tuple(action.data for action in detail.replies[0].message.actions) == (
                "开始探险",
                "帮助 行动",
            )

            missing = await _dispatch("帮助 不存在", "help-missing")
            assert "没有找到帮助" in _content(missing)
            assert missing.replies[0].message.actions[0].data == "帮助"

            covenant = await _dispatch("归航公约", "covenant")
            covenant_content = _content(covenant)
            assert "归航者" in covenant_content
            assert "归航回收" in covenant_content
            assert "归航市场" in covenant_content
            assert "归航库" in covenant_content
            assert "不增加第二套成长" in covenant_content
        finally:
            restore_game_services(previous)


async def _dispatch(command: str, event_id: str):
    return await dispatch(
        client_id="help-user",
        raw_message=command,
        sender_name="问路人",
        event_id=event_id,
    )


def _content(result) -> str:
    assert result.matched
    assert len(result.replies) == 1, result
    content = result.replies[0].message.content
    assert content.strip()
    return content


if __name__ == "__main__":
    main()
