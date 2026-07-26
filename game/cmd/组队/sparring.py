"""组队切磋邀请、处理和无损战报展示。"""

from __future__ import annotations

import asyncio

from game.app import CurrentCharacterResult, current_game_services
from launch.paths import public_url
from message import Action, DocumentMessage, M

from ..reply import send_game_reply
from . import shared


async def challenge(message: str, current: CurrentCharacterResult) -> None:
    character = shared.character(current)
    token = str(message or "").strip().split(maxsplit=1)
    if character is None:
        await send_game_reply(shared.failure("当前没有可用角色"))
        return
    if not token:
        await send_game_reply(shared.failure("发送：组队切磋 玩家"))
        return
    target = await asyncio.to_thread(shared.resolve_target, token[0])
    if target is None:
        await send_game_reply(shared.failure("对方尚未创建角色，无法组队切磋"))
        return
    try:
        result = await asyncio.to_thread(
            current_game_services().party_sparring.create_request,
            shared.operation_id("party-sparring-create"),
            character.id,
            target.id,
            logical_time=shared.command_time(),
        )
        await send_game_reply(_request_message(result))
    except Exception as exc:
        await shared.failed("发起组队切磋失败", character.id, exc)


async def accept(message: str, current: CurrentCharacterResult) -> None:
    character = shared.character(current)
    request_id = str(message or "").strip()
    if character is None:
        await send_game_reply(shared.failure("当前没有可用角色"))
        return
    if not request_id:
        await send_game_reply(shared.failure("组队切磋请求编号不能为空"))
        return
    try:
        result = await asyncio.to_thread(
            current_game_services().party_sparring.accept_request,
            shared.operation_id("party-sparring-accept"),
            request_id,
            character.id,
            logical_time=shared.command_time(),
        )
        await send_game_reply(_result_message(result))
    except Exception as exc:
        await shared.failed("接受组队切磋失败", character.id, exc)


async def reject(message: str, current: CurrentCharacterResult) -> None:
    character = shared.character(current)
    request_id = str(message or "").strip()
    if character is None:
        await send_game_reply(shared.failure("当前没有可用角色"))
        return
    if not request_id:
        await send_game_reply(shared.failure("组队切磋请求编号不能为空"))
        return
    try:
        result = await asyncio.to_thread(
            current_game_services().party_sparring.reject_request,
            shared.operation_id("party-sparring-reject"),
            request_id,
            character.id,
            logical_time=shared.command_time(),
        )
        reply = (
            shared.success("组队切磋", "已经拒绝这次组队切磋")
            if result.status == "rejected"
            else shared.failure(result.failure_message or "组队切磋请求没有处理")
        )
        await send_game_reply(reply)
    except Exception as exc:
        await shared.failed("拒绝组队切磋失败", character.id, exc)


def _request_message(result) -> DocumentMessage:
    builder = M.document().section("组队切磋邀请", icon="combat")
    if result.status not in {"created", "already_pending"} or result.request is None:
        return builder.line(result.failure_message or "组队切磋请求没有发出").build()
    challenger = result.challenger_party
    defender = result.defender_party
    challenger_name = (
        shared.character_name(challenger.leader_id)
        if challenger is not None
        else "挑战方"
    )
    defender_name = (
        shared.character_name(defender.leader_id)
        if defender is not None
        else "受邀方"
    )
    builder.line(f"{challenger_name}一方向{defender_name}一方发起组队切磋")
    builder.row(
        ("阵容", f"{len(challenger.members) if challenger else 0} vs {len(defender.members) if defender else 0}"),
        ("有效期", "10分钟"),
    )
    if result.status == "already_pending":
        builder.note("两支队伍已有一份待处理请求。")
    builder.note("只有受邀队伍的队长可以处理；队伍成员、站位或队长变化后请求失效。")
    return builder.actions((
        Action(
            "party-sparring.accept",
            "接受",
            f"接受组队切磋 {result.request.id}",
            behavior="callback",
        ),
        Action(
            "party-sparring.reject",
            "拒绝",
            f"拒绝组队切磋 {result.request.id}",
            behavior="callback",
            style="secondary",
        ),
    )).build()


def _result_message(result) -> DocumentMessage:
    builder = M.document().section("组队切磋结果", icon="combat")
    if result.status not in {"accepted", "replayed"}:
        return builder.line(result.failure_message or "组队切磋没有完成").build()
    if result.draw:
        builder.line("双方战成平局")
    elif result.winner_party_id and result.challenger_party and result.defender_party:
        winner = (
            result.challenger_party
            if result.winner_party_id == result.challenger_party.id
            else result.defender_party
        )
        builder.line(f"{shared.character_name(winner.leader_id)}一方获胜")
    else:
        builder.line("组队切磋已经完成")
    if result.challenger_party is not None and result.defender_party is not None:
        builder.field(
            "阵容",
            f"{len(result.challenger_party.members)} vs {len(result.defender_party.members)}",
        )
    if result.turns:
        builder.field("战斗行动", result.turns)
    if result.report is not None:
        builder.field(
            "战报",
            M.link("查看完整战报", public_url("battle", result.report.share_id)),
        )
    builder.note("组队切磋不改变资源、装备、成长、位置、世界或队伍状态，也不产生奖励。")
    return builder.build()


__all__ = ["accept", "challenge", "reject"]
