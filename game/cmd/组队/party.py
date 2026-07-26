"""队伍创建、邀请、成员管理和队伍总览。"""

from __future__ import annotations

import asyncio

from game.app import CurrentCharacterResult, current_game_services
from game.core.gameplay import Party, SocialRequest
from message import Action, DocumentMessage, M
from message.schema import FieldSeparator

from ..reply import send_game_reply
from . import shared


async def view(current: CurrentCharacterResult) -> None:
    character = shared.character(current)
    if character is None:
        await send_game_reply(shared.failure("当前没有可用角色"))
        return
    try:
        result = await asyncio.to_thread(
            current_game_services().party.view,
            character.id,
            logical_time=shared.command_time(),
        )
        await send_game_reply(
            _view_message(result.party, result.incoming_requests, character.id)
        )
    except Exception as exc:
        await shared.failed("队伍读取失败", character.id, exc)


async def create(current: CurrentCharacterResult) -> None:
    character = shared.character(current)
    if character is None:
        await send_game_reply(shared.failure("当前没有可用角色"))
        return
    try:
        result = await asyncio.to_thread(
            current_game_services().party.create,
            shared.operation_id("party-create"),
            character.id,
            logical_time=shared.command_time(),
        )
        if result.status == "created" and result.party is not None:
            reply = (
                M.document()
                .section("队伍", icon="player")
                .line("队伍已经创建，你现在是队长")
                .actions(
                    (
                        Action("party.challenge", "组队挑战", "组队挑战"),
                        Action(
                            "party.invite",
                            "邀请",
                            "邀请组队 ",
                            behavior="fill",
                            style="secondary",
                        ),
                    )
                )
                .build()
            )
        elif result.status == "already_member":
            reply = shared.failure("你已经在一支队伍中")
        else:
            reply = shared.failure(result.failure_message or "队伍创建没有完成")
        await send_game_reply(reply)
    except Exception as exc:
        await shared.failed("创建队伍失败", character.id, exc)


async def invite(message: str, current: CurrentCharacterResult) -> None:
    character = shared.character(current)
    target_token = str(message or "").strip().split(maxsplit=1)
    if character is None:
        await send_game_reply(shared.failure("当前没有可用角色"))
        return
    if not target_token:
        await send_game_reply(shared.failure("发送：邀请组队 玩家"))
        return
    target = await asyncio.to_thread(shared.resolve_target, target_token[0])
    if target is None:
        await send_game_reply(shared.failure("对方尚未创建角色，无法邀请组队"))
        return
    try:
        result = await asyncio.to_thread(
            current_game_services().party.invite,
            shared.operation_id("party-invite"),
            character.id,
            target.id,
            logical_time=shared.command_time(),
        )
        if result.status in {"invited", "already_pending"}:
            text = (
                "已经向对方发出队伍邀请"
                if result.status == "invited"
                else "双方已有一份待处理队伍邀请"
            )
            reply = (
                M.document()
                .section("队伍邀请", icon="player")
                .line(text)
                .field("有效期", "10分钟")
                .build()
            )
        else:
            reply = shared.failure(result.failure_message or "队伍邀请没有发出")
        await send_game_reply(reply)
    except Exception as exc:
        await shared.failed("邀请组队失败", character.id, exc)


async def accept(message: str, current: CurrentCharacterResult) -> None:
    await _resolve_invitation(message, current, accepted=True)


async def reject(message: str, current: CurrentCharacterResult) -> None:
    await _resolve_invitation(message, current, accepted=False)


async def _resolve_invitation(message, current, *, accepted: bool) -> None:
    character = shared.character(current)
    request_id = str(message or "").strip()
    if character is None:
        await send_game_reply(shared.failure("当前没有可用角色"))
        return
    if not request_id:
        await send_game_reply(shared.failure("队伍请求编号不能为空"))
        return
    try:
        services = current_game_services()
        method = services.party.accept if accepted else services.party.reject
        result = await asyncio.to_thread(
            method,
            shared.operation_id("party-accept" if accepted else "party-reject"),
            character.id,
            request_id,
            logical_time=shared.command_time(),
        )
        if accepted and result.status == "accepted":
            reply = (
                M.document()
                .section("组队", icon="player")
                .line("已经加入队伍")
                .action(Action("party.challenge", "组队挑战", "组队挑战"))
                .build()
            )
        elif not accepted and result.status == "rejected":
            reply = shared.success("组队", "已经拒绝这份队伍邀请")
        else:
            reply = shared.failure(result.failure_message or "队伍邀请没有处理")
        await send_game_reply(reply)
    except Exception as exc:
        await shared.failed("处理队伍邀请失败", character.id, exc)


async def leave(current: CurrentCharacterResult) -> None:
    await _simple_action(current, "party-leave", "leave", "已经退出队伍")


async def kick(message: str, current: CurrentCharacterResult) -> None:
    await _target_action(current, message, "kick", "请离队伍", "已将成员请离队伍")


async def transfer(message: str, current: CurrentCharacterResult) -> None:
    await _target_action(current, message, "transfer", "转让队长", "已经转让队长")


async def disband(current: CurrentCharacterResult) -> None:
    character = shared.character(current)
    if character is None:
        await send_game_reply(shared.failure("当前没有可用角色"))
        return
    try:
        result = await asyncio.to_thread(
            current_game_services().party.view,
            character.id,
            logical_time=shared.command_time(),
        )
        party = result.party
        if party is None:
            await send_game_reply(shared.failure("当前没有队伍"))
            return
        if party.leader_id != character.id:
            await send_game_reply(shared.failure("只有队长可以解散队伍"))
            return
        disbanded = await asyncio.to_thread(
            current_game_services().party.disband,
            shared.operation_id("party-disband"),
            character.id,
            expected_revision=result.state_revision,
            logical_time=shared.command_time(),
        )
        await send_game_reply(
            shared.success("组队", "队伍已经解散")
            if disbanded.status == "disbanded"
            else shared.failure(disbanded.failure_message or "队伍解散没有完成")
        )
    except Exception as exc:
        await shared.failed("解散队伍失败", character.id, exc)


async def confirm_disband(message: str, current: CurrentCharacterResult) -> None:
    character = shared.character(current)
    if character is None:
        await send_game_reply(shared.failure("当前没有可用角色"))
        return
    try:
        revision = int(str(message or "").strip())
        result = await asyncio.to_thread(
            current_game_services().party.disband,
            shared.operation_id("party-disband"),
            character.id,
            expected_revision=revision,
            logical_time=shared.command_time(),
        )
        await send_game_reply(
            shared.success("组队", "队伍已经解散")
            if result.status == "disbanded"
            else shared.failure(result.failure_message or "队伍解散没有完成")
        )
    except ValueError:
        await send_game_reply(
            shared.failure(
                "解散确认已经失效",
                Action("party.disband.back", "返回队伍", "队伍", style="secondary"),
            )
        )
    except Exception as exc:
        await shared.failed("解散队伍失败", character.id, exc)


async def _simple_action(current, prefix, method_name, success_text) -> None:
    character = shared.character(current)
    if character is None:
        await send_game_reply(shared.failure("当前没有可用角色"))
        return
    try:
        method = getattr(current_game_services().party, method_name)
        result = await asyncio.to_thread(
            method,
            shared.operation_id(prefix),
            character.id,
            logical_time=shared.command_time(),
        )
        reply = (
            shared.success("组队", success_text)
            if result.status in {"member.left", "disbanded"}
            else shared.failure(result.failure_message or "队伍操作没有完成")
        )
        await send_game_reply(reply)
    except Exception as exc:
        await shared.failed("队伍操作失败", character.id, exc)


async def _target_action(current, message, method_name, title, success_text) -> None:
    character = shared.character(current)
    token = str(message or "").strip().split(maxsplit=1)
    if character is None:
        await send_game_reply(shared.failure("当前没有可用角色"))
        return
    if not token:
        await send_game_reply(shared.failure(f"发送：{title} 玩家"))
        return
    target = await asyncio.to_thread(shared.resolve_target, token[0])
    if target is None:
        await send_game_reply(shared.failure("对方尚未创建角色"))
        return
    try:
        method = getattr(current_game_services().party, method_name)
        result = await asyncio.to_thread(
            method,
            shared.operation_id(f"party-{method_name}"),
            character.id,
            target.id,
            logical_time=shared.command_time(),
        )
        success_status = (
            "leadership.transferred" if method_name == "transfer" else "member.removed"
        )
        reply = (
            shared.success("组队", success_text)
            if result.status == success_status
            else shared.failure(result.failure_message or "队伍操作没有完成")
        )
        await send_game_reply(reply)
    except Exception as exc:
        await shared.failed(f"{title}失败", character.id, exc)


def _view_message(
    party: Party | None,
    requests: tuple[SocialRequest, ...],
    character_id: str,
) -> DocumentMessage:
    builder = M.document().section("组队", icon="player")
    actions = []
    if party is None:
        builder.line("当前没有加入队伍")
        actions.append(Action("party.create", "创建队伍", "创建队伍", behavior="callback"))
    else:
        leader = shared.character_name(party.leader_id)
        capacity = current_game_services().content.catalog.parties.require(
            party.definition_id
        ).capacity
        builder.row(("队长", leader), ("人数", f"{len(party.members)}/{capacity}"))
        for member in sorted(party.members.values(), key=lambda value: value.slot):
            name = shared.character_name(member.subject_id)
            marker = "队长" if member.subject_id == party.leader_id else "成员"
            ready = "已准备" if member.ready else "未准备"
            builder.line(
                f"{member.slot + 1}. {name}",
                FieldSeparator(),
                marker,
                FieldSeparator(),
                ready,
            )
        actions.append(Action("party.challenge", "组队挑战", "组队挑战", behavior="callback"))
        if party.leader_id == character_id:
            actions.extend(
                (
                    Action(
                        "party.invite",
                        "邀请",
                        "邀请组队 ",
                        behavior="fill",
                        style="secondary",
                    ),
                    Action(
                        "party.sparring",
                        "组队切磋",
                        "组队切磋 ",
                        behavior="fill",
                        style="secondary",
                    ),
                    Action(
                        "party.disband",
                        "解散",
                        "解散队伍",
                        behavior="callback",
                        style="secondary",
                    ),
                )
            )
        if party.leader_id != character_id:
            actions.append(
                Action(
                    "party.leave",
                    "退出",
                    "退出队伍",
                    behavior="callback",
                    style="secondary",
                )
            )
    if requests:
        builder.section("队伍邀请", icon="message")
        for request in requests:
            builder.line(
                shared.character_name(request.sender_id),
                " 邀请你加入队伍",
                FieldSeparator(),
                M.command("接受", f"接受组队 {request.id}"),
                FieldSeparator(),
                M.command("拒绝", f"拒绝组队 {request.id}"),
            )
    return builder.actions(actions).build()


__all__ = [
    "accept",
    "confirm_disband",
    "create",
    "invite",
    "kick",
    "leave",
    "disband",
    "reject",
    "transfer",
    "view",
]
