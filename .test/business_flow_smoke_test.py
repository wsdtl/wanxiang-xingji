"""正式业务组件通过本地驱动串行协作的冒烟测试。"""

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
from game.rules.activity import GLOBAL_ACTIVITY_SCOPE_ID  # noqa: E402
from game.cmd import 二手 as market_component  # noqa: E402,F401
from game.cmd import 休息 as rest_component  # noqa: E402,F401
from game.cmd import 切磋 as sparring_component  # noqa: E402,F401
from game.cmd import 回收 as recycle_component  # noqa: E402,F401
from game.cmd import 跨界灾厄 as disaster_component  # noqa: E402,F401
from game.cmd import 彩票 as lottery_component  # noqa: E402,F401
from game.cmd import 抽奖 as draw_component  # noqa: E402,F401
from game.cmd import 探险 as exploration_component  # noqa: E402,F401
from game.cmd import 提醒 as reminder_component  # noqa: E402,F401
from game.cmd import 活动 as activity_component  # noqa: E402,F401
from game.cmd import 物品 as item_component  # noqa: E402,F401
from game.cmd import 装配 as loadout_component  # noqa: E402,F401
from game.cmd import 角色 as character_component  # noqa: E402,F401
from game.cmd import 跃迁 as dimension_shift_component  # noqa: E402,F401
from game.cmd import 铭刻 as inscription_component  # noqa: E402,F401
from launch.adapter.local import LocalEventHandler, dispatch  # noqa: E402


NOW = datetime(2026, 7, 20, 1, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
    asyncio.run(_main())
    print("business flow smoke tests passed")


async def _main() -> None:
    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "business-flow.db",
            identity_secret="business-flow-secret",
        )
        services.database.initialize()
        services.activities.initialize(GLOBAL_ACTIVITY_SCOPE_ID, logical_time=NOW)
        services.economy.initialize(logical_time=NOW)
        services.lottery.initialize(logical_time=NOW)
        services.dimensional_disasters.maintain(logical_time=NOW)
        previous = install_game_services(services)
        try:
            await LocalEventHandler.run()
            created = await _dispatch("创建角色 云游客", "flow-create")
            assert "云游客" in _content(created)

            cases = (
                ("我的角色", "flow-character", "云游客"),
                ("纳戒", "flow-nacre", "纳戒"),
                ("武库", "flow-armory", "武库"),
                ("装配", "flow-loadout", "装配"),
                ("铭刻", "flow-inscription", "铭刻"),
                ("跃迁", "flow-shift", "界门"),
                ("探险", "flow-exploration", "探险"),
                ("抽奖", "flow-draw", "抽奖"),
                ("回收战利品", "flow-recycle", "战利品"),
                ("二手", "flow-market", "归航市场"),
                ("彩票", "flow-lottery", "彩票"),
                ("world_events", "flow-activities", "活动"),
                ("notifications", "flow-notifications", "通知"),
                ("pending_actions", "flow-pending", "待领取"),
                ("休息", "flow-rest", "休息"),
                ("切磋", "flow-sparring", "切磋"),
                ("跨界灾厄", "flow-disaster", "跨界灾厄"),
            )
            for command, event_id, expected in cases:
                result = await _dispatch(command, event_id)
                content = _content(result)
                assert expected in content, f"{command}: {content}"
        finally:
            restore_game_services(previous)


async def _dispatch(command: str, event_id: str):
    return await dispatch(
        client_id="business-flow-player",
        raw_message=command,
        sender_name="云游客",
        event_id=event_id,
    )


def _content(result) -> str:
    assert len(result.replies) == 1, result
    content = result.replies[0].message.content
    assert content.strip()
    return content


if __name__ == "__main__":
    main()
