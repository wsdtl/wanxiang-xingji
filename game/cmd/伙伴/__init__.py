"""伙伴名册、秘境与配装绑定命令。"""

from __future__ import annotations

from launch.adapter import Depends

from ..command import GameCommand, HelpSpec
from ..dependencies import current_character_overview
from . import service


@GameCommand.handler(
    cmd="伙伴",
    help=HelpSpec(
        category="角色",
        summary="查看伙伴名册或一只伙伴的完整资料",
        usage=("伙伴", "伙伴 C1"),
        order=80,
    ),
)
async def companion(message: str = "", overview=Depends(current_character_overview)) -> None:
    await service.view_companions(message, overview)


@GameCommand.handler(
    cmd="伙伴出战",
    help=HelpSpec(
        category="角色",
        summary="让一只伙伴随当前配装出战",
        usage=("伙伴出战 C1",),
        side_effect="同一只伙伴只能属于一套配装，出战时会直接转移到当前配装",
        order=90,
    ),
)
async def bind_companion(message: str = "", overview=Depends(current_character_overview)) -> None:
    await service.bind_companion(message, overview)


@GameCommand.handler(
    cmd="伙伴休战",
    help=HelpSpec(
        category="角色",
        summary="解除当前配装的伙伴出战关系",
        usage=("伙伴休战",),
        order=100,
    ),
)
async def unbind_companion(overview=Depends(current_character_overview)) -> None:
    await service.unbind_companion(overview)


@GameCommand.handler(
    cmd="宠物秘境",
    help=HelpSpec(
        category="世界",
        summary="查看当前宠物秘境和已经固定的踪迹",
        usage=("宠物秘境",),
        order=80,
    ),
)
async def companion_sanctuary(overview=Depends(current_character_overview)) -> None:
    await service.view_sanctuary(overview)


@GameCommand.handler(
    cmd="秘境追踪",
    help=HelpSpec(
        category="世界",
        summary="锁定一条踪迹并立即进行捕获战斗",
        usage=("秘境追踪 1",),
        side_effect="首次选择后另外两条踪迹消失，战斗会真实结算角色资源",
        order=90,
    ),
)
async def hunt_companion(message: str = "", overview=Depends(current_character_overview)) -> None:
    await service.hunt_companion(message, overview)


@GameCommand.handler(
    cmd="放弃秘境",
    help=HelpSpec(
        category="世界",
        summary="永久结束当前宠物秘境",
        usage=("放弃秘境",),
        side_effect="当前全部踪迹会直接消失，万灵引不会返还",
        order=100,
    ),
)
async def abandon_sanctuary(overview=Depends(current_character_overview)) -> None:
    await service.abandon_sanctuary(overview)


@GameCommand.handler(
    cmd="告别",
    help=HelpSpec(
        category="角色",
        summary="让一名伙伴离开当前名册",
        usage=("告别 C1",),
        side_effect="宠物实例永久离开；人物保留成长并可再次结交",
        order=110,
    ),
)
async def farewell_companion(message: str = "", overview=Depends(current_character_overview)) -> None:
    await service.farewell_companion(message, overview)


@GameCommand.handler(
    cmd="人物",
    help=HelpSpec(
        category="世界",
        summary="查看当前世界的人物及专用地点",
        usage=("人物",),
        order=110,
    ),
)
async def people(overview=Depends(current_character_overview)) -> None:
    await service.view_people(overview)


@GameCommand.handler(
    cmd="赠礼",
    help=HelpSpec(
        category="世界",
        summary="向当前位置的人物赠送偏好战利品",
        usage=("赠礼 T编号", "赠礼 T编号 数量"),
        side_effect="会消耗实际赠送的战利品",
        order=120,
    ),
)
async def gift_person(message: str = "", overview=Depends(current_character_overview)) -> None:
    await service.gift_person(message, overview)


@GameCommand.handler(
    cmd="结交",
    help=HelpSpec(
        category="世界",
        summary="与当前位置关系达标的人物结为伙伴",
        usage=("结交",),
        order=130,
    ),
)
async def join_person(overview=Depends(current_character_overview)) -> None:
    await service.join_person(overview)


@GameCommand.handler(cmd="companion_bind_transfer_confirm", hidden=True)
async def confirm_bind_transfer(message: str = "", overview=Depends(current_character_overview)) -> None:
    await service.confirm_bind_transfer(message, overview)


@GameCommand.handler(cmd="companion_farewell_confirm", hidden=True)
async def confirm_farewell(message: str = "", overview=Depends(current_character_overview)) -> None:
    await service.confirm_farewell(message, overview)


@GameCommand.handler(cmd="companion_abandon_confirm", hidden=True)
async def confirm_abandon(message: str = "", overview=Depends(current_character_overview)) -> None:
    await service.confirm_abandon(message, overview)


__all__ = []
