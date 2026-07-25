"""队伍二级组件命令。"""

from __future__ import annotations

from launch.adapter import Depends

from ..command import GameCommand, HelpSpec
from ..dependencies import current_character
from . import battle, party, sparring


@GameCommand.handler(
    cmd="组队",
    help=HelpSpec(
        category="战斗与社交",
        summary="查看当前队伍、成员准备状态和队伍邀请",
        usage=("组队",),
        order=40,
    ),
)
async def view(current=Depends(current_character)) -> None:
    await party.view(current)


@GameCommand.handler(
    cmd="创建队伍",
    help=HelpSpec(
        category="战斗与社交",
        summary="创建一支最多三人的轻量队伍",
        usage=("创建队伍",),
        side_effect="创建者成为队长；队伍可参与跨界协同挑战",
        order=50,
    ),
)
async def create(current=Depends(current_character)) -> None:
    await party.create(current)


@GameCommand.handler(
    cmd="邀请组队",
    help=HelpSpec(
        category="战斗与社交",
        summary="邀请指定玩家加入当前队伍",
        usage=("邀请组队 玩家",),
        side_effect="邀请十分钟内有效，只有队长可以邀请",
        order=60,
    ),
)
async def invite(message: str = "", current=Depends(current_character)) -> None:
    await party.invite(message, current)


@GameCommand.handler(
    cmd="接受组队",
    help=HelpSpec(
        category="战斗与社交",
        summary="接受属于当前角色的队伍邀请",
        usage=("接受组队 请求编号",),
        order=70,
    ),
)
async def accept(message: str = "", current=Depends(current_character)) -> None:
    await party.accept(message, current)


@GameCommand.handler(
    cmd="拒绝组队",
    help=HelpSpec(
        category="战斗与社交",
        summary="拒绝属于当前角色的队伍邀请",
        usage=("拒绝组队 请求编号",),
        order=80,
    ),
)
async def reject(message: str = "", current=Depends(current_character)) -> None:
    await party.reject(message, current)


@GameCommand.handler(
    cmd="退出队伍",
    help=HelpSpec(
        category="战斗与社交",
        summary="退出当前队伍",
        usage=("退出队伍",),
        side_effect="队长必须先转让队长或解散队伍",
        order=90,
    ),
)
async def leave(current=Depends(current_character)) -> None:
    await party.leave(current)


@GameCommand.handler(
    cmd="请离队伍",
    help=HelpSpec(
        category="战斗与社交",
        summary="由队长移除一名队伍成员",
        usage=("请离队伍 玩家",),
        order=100,
    ),
)
async def kick(message: str = "", current=Depends(current_character)) -> None:
    await party.kick(message, current)


@GameCommand.handler(
    cmd="转让队长",
    help=HelpSpec(
        category="战斗与社交",
        summary="把队长身份交给当前队伍成员",
        usage=("转让队长 玩家",),
        order=110,
    ),
)
async def transfer(message: str = "", current=Depends(current_character)) -> None:
    await party.transfer(message, current)


@GameCommand.handler(
    cmd="解散队伍",
    help=HelpSpec(
        category="战斗与社交",
        summary="解散当前队伍",
        usage=("解散队伍",),
        side_effect="只有队长可以解散，队伍成员关系会立即结束",
        order=120,
    ),
)
async def disband(current=Depends(current_character)) -> None:
    await party.disband(current)


@GameCommand.handler(cmd="party_disband_confirm", hidden=True)
async def confirm_disband(
    message: str = "",
    current=Depends(current_character),
) -> None:
    await party.confirm_disband(message, current)


@GameCommand.handler(
    cmd="准备",
    help=HelpSpec(
        category="战斗与社交",
        summary="将自己标记为已准备",
        usage=("准备",),
        order=130,
    ),
)
async def ready(current=Depends(current_character)) -> None:
    await battle.set_ready(current, True)


@GameCommand.handler(
    cmd="取消准备",
    help=HelpSpec(
        category="战斗与社交",
        summary="取消自己的队伍准备状态",
        usage=("取消准备",),
        order=140,
    ),
)
async def unready(current=Depends(current_character)) -> None:
    await battle.set_ready(current, False)


@GameCommand.handler(
    cmd="组队挑战",
    help=HelpSpec(
        category="战斗与社交",
        summary="查看当前队伍锁定的组队首领和准备状态",
        usage=("组队挑战",),
        order=150,
    ),
)
async def party_battle_view(current=Depends(current_character)) -> None:
    await battle.view(current)


@GameCommand.handler(
    cmd="选择组队挑战",
    help=HelpSpec(
        category="战斗与社交",
        summary="由队长锁定一个等级的跨界组队首领",
        usage=("选择组队挑战 等级",),
        order=160,
    ),
)
async def select_party_battle(message: str = "", current=Depends(current_character)) -> None:
    await battle.select(message, current)


@GameCommand.handler(
    cmd="开始组队挑战",
    help=HelpSpec(
        category="战斗与社交",
        summary="由队长发起已完成准备的组队首领战",
        usage=("开始组队挑战",),
        side_effect="胜负、资源变化和个人奖励在同一事务中结算",
        order=170,
    ),
)
async def start_party_battle(current=Depends(current_character)) -> None:
    await battle.start(current)


@GameCommand.handler(
    cmd="组队切磋",
    help=HelpSpec(
        category="战斗与社交",
        summary="由队长向另一支队伍发起无损切磋",
        usage=("组队切磋 玩家",),
        side_effect="双方各自以当前一至三名成员和已绑定伙伴参战，不产生奖励或持久消耗",
        order=180,
    ),
)
async def party_sparring(message: str = "", current=Depends(current_character)) -> None:
    await sparring.challenge(message, current)


@GameCommand.handler(
    cmd="接受组队切磋",
    help=HelpSpec(
        category="战斗与社交",
        summary="由受邀队伍的队长接受组队切磋",
        usage=("接受组队切磋 请求编号",),
        order=190,
    ),
)
async def accept_party_sparring(
    message: str = "",
    current=Depends(current_character),
) -> None:
    await sparring.accept(message, current)


@GameCommand.handler(
    cmd="拒绝组队切磋",
    help=HelpSpec(
        category="战斗与社交",
        summary="由受邀队伍的队长拒绝组队切磋",
        usage=("拒绝组队切磋 请求编号",),
        order=200,
    ),
)
async def reject_party_sparring(
    message: str = "",
    current=Depends(current_character),
) -> None:
    await sparring.reject(message, current)


__all__ = []
