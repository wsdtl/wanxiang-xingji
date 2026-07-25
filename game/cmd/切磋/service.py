"""切磋命令参数、对手身份解析和协议中立展示。"""

from __future__ import annotations

import asyncio

from game.app import CurrentCharacterResult, current_game_services
from game.core.account import ExternalIdentity
from launch.adapter import current_message_context
from launch.paths import public_url
from message import Action, DocumentMessage, M

from ..command_helpers import command_time, current_character_value
from ..reply import send_command_failure, send_game_reply


async def challenge(message: str, current: CurrentCharacterResult) -> None:
    challenger = current_character_value(current)
    if challenger is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    requested = str(message or "").strip()
    if not requested:
        await send_game_reply(_failure("请指定切磋对象"))
        return
    target_external_id = requested.split(maxsplit=1)[0]
    defender = await asyncio.to_thread(_resolve_target, target_external_id)
    if defender is None:
        await send_game_reply(_failure("对方尚未创建角色，无法切磋"))
        return
    context = _message_context()
    try:
        result = await asyncio.to_thread(
            current_game_services().sparring.create_request,
            f"sparring:{context.identity.evidence_id}",
            challenger,
            defender,
            logical_time=command_time(),
        )
    except Exception as exc:
        await _failed("发起切磋失败", challenger.id, exc)
        return
    await send_game_reply(
        _request_message(
            result,
            challenger.name,
            defender.name,
            target_external_id,
        )
    )


async def accept(message: str, current: CurrentCharacterResult) -> None:
    defender = current_character_value(current)
    if defender is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    request_id = str(message or "").strip()
    if not request_id:
        await send_game_reply(_failure("切磋请求编号不能为空"))
        return
    context = _message_context()
    try:
        result = await asyncio.to_thread(
            current_game_services().sparring.accept_request,
            f"sparring:accept:{context.identity.evidence_id}",
            request_id,
            defender,
            logical_time=command_time(),
        )
    except Exception as exc:
        await _failed("接受切磋失败", defender.id, exc)
        return
    await send_game_reply(_result_message(result))


async def reject(message: str, current: CurrentCharacterResult) -> None:
    defender = current_character_value(current)
    if defender is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    request_id = str(message or "").strip()
    if not request_id:
        await send_game_reply(_failure("切磋请求编号不能为空"))
        return
    context = _message_context()
    try:
        result = await asyncio.to_thread(
            current_game_services().sparring.reject_request,
            f"sparring:reject:{context.identity.evidence_id}",
            request_id,
            defender,
            logical_time=command_time(),
        )
    except Exception as exc:
        await _failed("拒绝切磋失败", defender.id, exc)
        return
    builder = M.document().section("切磋", icon="combat")
    if result.status == "rejected":
        builder.line("已经拒绝这次切磋")
    else:
        builder.line(result.failure_message or "切磋请求没有处理")
    await send_game_reply(builder.build())


def _request_message(result, challenger_name, defender_name, target_external_id):
    builder = M.document().section("切磋邀请", icon="combat")
    if result.status in {"created", "already_pending"} and result.request is not None:
        request = result.request
        builder.line(f"{challenger_name} 向 {defender_name} 发起切磋")
        builder.field("有效期", "10分钟")
        if result.status == "already_pending":
            builder.note("双方已有一份待处理切磋请求。")
        return builder.actions(
            (
                Action(
                    "sparring.accept",
                    "接受",
                    f"接受切磋 {request.id}",
                    permission="specified",
                    specified_user_ids=(target_external_id,),
                ),
                Action(
                    "sparring.reject",
                    "拒绝",
                    f"拒绝切磋 {request.id}",
                    style="secondary",
                    permission="specified",
                    specified_user_ids=(target_external_id,),
                ),
            )
        ).build()
    return builder.line(result.failure_message or "切磋请求没有发出").build()


def _result_message(result) -> DocumentMessage:
    builder = M.document().section("切磋结果", icon="combat")
    if result.status in {"accepted", "replayed"} and result.request is not None:
        if result.draw:
            builder.line("双方战成平局")
        elif result.winner_id and result.challenger is not None and result.defender is not None:
            winner = (
                result.challenger.name
                if result.winner_id == result.challenger.id
                else result.defender.name
            )
            builder.line(f"{winner} 获胜")
        else:
            builder.line("切磋已经完成")
        if result.turns:
            builder.field("战斗行动", result.turns)
        if result.report is not None:
            builder.field(
                "战报",
                M.link("查看完整战报", public_url("battle", result.report.share_id)),
            )
        builder.note("切磋不会改变双方血气、灵力、装备或成长资源。")
        return builder.build()
    return builder.line(result.failure_message or "切磋没有完成").build()


def _resolve_target(target_external_id: str):
    context = _message_context()
    claim = context.identity.primary
    identity = ExternalIdentity(
        claim.provider_id,
        claim.tenant_id,
        claim.subject_kind,
        claim.scope_id,
        target_external_id,
    )
    services = current_game_services()
    account = services.accounts.find_existing_account(identity)
    if account is None:
        return None
    return services.characters.load_for_account(account.id)


def _message_context():
    context = current_message_context()
    if context is None:
        raise RuntimeError("切磋命令缺少消息上下文")
    return context


async def _failed(title: str, character_id: str, exc: Exception) -> None:
    await send_command_failure(
        title,
        character_id,
        exc,
        _failure("当前操作没有完成，请稍后重试"),
    )


def _failure(message: str) -> DocumentMessage:
    return M.document().section("切磋", icon="notice").line(message).build()


__all__ = ["accept", "challenge", "reject"]
