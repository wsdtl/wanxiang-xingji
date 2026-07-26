"""角色二级组件命令。"""

from __future__ import annotations

from launch.adapter import Depends

from ..command import GameCommand, HelpSpec
from ..dependencies import current_character, current_character_overview
from . import service


@GameCommand.handler(
    cmd="创建角色",
    access="public",
    help=HelpSpec(
        category="角色",
        summary="建立当前账号的唯一化身",
        usage=("创建角色", "创建角色 名称"),
        side_effect="每个账号只能创建一个角色",
        order=10,
    ),
)
async def create_character(message: str = "") -> None:
    """创建当前消息发送者的角色。"""

    await service.create_character(message)


@GameCommand.handler(
    cmd="我的角色",
    help=HelpSpec(
        category="角色",
        summary="查看人物、装配、位置、资产和当前行动",
        usage=("我的角色",),
        order=20,
    ),
)
async def view_character(
    overview=Depends(current_character_overview),
) -> None:
    """查看当前消息发送者的角色状态。"""

    await service.view_character(overview)


@GameCommand.handler(
    cmd="战斗面板",
    help=HelpSpec(
        category="角色",
        summary="查看当前配装实际生效的全部战斗数值",
        usage=("战斗面板",),
        order=30,
    ),
)
async def view_combat_panel(
    overview=Depends(current_character_overview),
) -> None:
    """查看当前配装真正生效的全部战斗数据。"""

    await service.view_combat_panel(overview)


@GameCommand.handler(
    cmd="心情",
    help=HelpSpec(
        category="角色",
        summary="查看或切换人物头的心情颜色",
        usage=("心情", "心情 开启", "心情 关闭"),
        order=40,
    ),
)
async def mood(
    message: str = "",
    current=Depends(current_character),
) -> None:
    """查看或修改彩色人物头开关。"""

    await service.mood(message, current)


@GameCommand.handler(
    cmd="自动用药",
    help=HelpSpec(
        category="角色",
        summary="查看或切换探险中的自动恢复药使用",
        usage=("自动用药", "自动用药 开启", "自动用药 关闭"),
        side_effect="开启后会在符合条件时消耗纳戒中的恢复药",
        order=50,
    ),
)
async def auto_medicine(
    message: str = "",
    current=Depends(current_character),
) -> None:
    """查看或修改探险自动用药开关。"""

    await service.auto_medicine(message, current)


@GameCommand.handler(
    cmd="自动休整",
    help=HelpSpec(
        category="角色",
        summary="查看或切换探险战败及低资源时的自动休整",
        usage=("自动休整", "自动休整 开启", "自动休整 关闭"),
        side_effect="关闭后，探险战败会直接结束当前会话",
        order=60,
    ),
)
async def auto_rest(
    message: str = "",
    current=Depends(current_character),
) -> None:
    """查看或修改探险自动休整开关。"""

    await service.auto_rest(message, current)


__all__ = []
