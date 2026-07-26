"""抽奖二级组件命令。"""

from __future__ import annotations

from launch.adapter import Depends

from ..command import GameCommand, HelpSpec
from ..dependencies import current_character
from . import service


@GameCommand.handler(
    cmd="抽奖",
    help=HelpSpec(
        category="活动",
        summary="优先消耗一张抽奖签，不足时支付 250 主货币",
        usage=("抽奖",),
        side_effect="成功后优先消耗一张抽奖签，不足时扣除 250 主货币",
        order=10,
    ),
)
async def draw_once(current=Depends(current_character)) -> None:
    await service.draw(current, 1)


@GameCommand.handler(
    cmd="十连抽奖",
    help=HelpSpec(
        category="活动",
        summary="优先消耗现有抽奖签，缺口按每抽 250 主货币补足",
        usage=("十连抽奖",),
        side_effect="成功后优先消耗最多十张抽奖签，缺口按每张 250 主货币扣除",
        order=20,
    ),
)
async def draw_ten(current=Depends(current_character)) -> None:
    await service.draw(current, 10)


@GameCommand.handler(
    cmd="抽奖奖池",
    help=HelpSpec(
        category="活动",
        summary="查看显化档位、稳定度和可能获得的奖励",
        usage=("抽奖奖池",),
        order=30,
    ),
)
async def draw_pool(current=Depends(current_character)) -> None:
    await service.pool(current)


@GameCommand.handler(
    cmd="抽奖记录",
    help=HelpSpec(
        category="活动",
        summary="查看自己的近期显化结果",
        usage=("抽奖记录",),
        order=40,
    ),
)
async def draw_history(current=Depends(current_character)) -> None:
    await service.history(current)


__all__ = []
