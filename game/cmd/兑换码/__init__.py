"""公开兑换码二级组件。"""

from __future__ import annotations

from launch.adapter import Depends

from ..command import GameCommand, HelpSpec
from ..dependencies import current_character
from . import service


@GameCommand.handler(
    cmd="兑换码",
    help=HelpSpec(
        category="活动",
        summary="领取公开兑换码对应的账号限定奖励",
        usage=("兑换码 代码",),
        side_effect="有效代码会立即发放奖励，每个账号受活动领取次数限制",
        order=5,
    ),
)
async def redeem_code(
    message: str = "",
    current=Depends(current_character),
) -> None:
    await service.redeem_code(message, current)


__all__ = []
