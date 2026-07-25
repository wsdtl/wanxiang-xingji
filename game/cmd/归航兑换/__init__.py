"""归航兑换二级组件。"""

from __future__ import annotations

from launch.adapter import Depends

from ..command import GameCommand, HelpSpec
from ..dependencies import current_character
from . import service


@GameCommand.handler(
    cmd="归航兑换",
    help=HelpSpec(
        category="资产",
        summary="使用定相尘兑换套装图纸",
        usage=("归航兑换", "归航兑换 套装", "归航兑换 套装编号"),
        side_effect="选择套装后直接扣除定相尘并发放图纸",
        order=170,
    ),
)
async def covenant_exchange(message: str = "", current=Depends(current_character)) -> None:
    await service.covenant_exchange(message, current)


@GameCommand.handler(
    cmd="归航兑换记录",
    help=HelpSpec(
        category="资产",
        summary="查看最近二十次归航兑换",
        usage=("归航兑换记录",),
        order=171,
    ),
)
async def covenant_exchange_history(current=Depends(current_character)) -> None:
    await service.covenant_exchange_history(current)


@GameCommand.handler(cmd="covenant_exchange_confirm", hidden=True)
async def confirm_covenant_exchange(
    message: str = "",
    current=Depends(current_character),
) -> None:
    await service.confirm_covenant_exchange(message, current)


__all__ = []
