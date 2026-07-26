"""当前配装特效与正式机制图鉴命令。"""

from __future__ import annotations

from launch.adapter import Depends

from ..command import GameCommand, HelpSpec
from ..dependencies import current_character_overview
from . import service


@GameCommand.handler(
    cmd="特效",
    help=HelpSpec(
        category="角色",
        summary="查看当前配装生效机制，或查询全部正式档位与数值",
        usage=("特效", "特效 名称", "特效 全部", "特效 全部 页码"),
        order=35,
    ),
)
async def mechanics(
    message: str = "",
    overview=Depends(current_character_overview),
) -> None:
    await service.view_mechanics(message, overview)


__all__ = []
