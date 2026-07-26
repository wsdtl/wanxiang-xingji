"""兑换码命令调用与玩家可见结果展示。"""

from __future__ import annotations

import asyncio

from game.app import CurrentCharacterResult, current_game_services
from game.content import PRIMARY_CURRENCY_ID
from game.features.redemption_code import RedemptionCodeItem, RedemptionCodeResult
from launch.adapter import current_message_context
from message import DocumentMessage, M
from message.schema import FieldSeparator

from ..command_helpers import command_time
from ..reply import send_command_failure, send_game_reply


async def redeem_code(message: str, current: CurrentCharacterResult) -> None:
    character = current.character if current.status == "ok" else None
    if character is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    code = str(message or "").strip()
    if not code:
        await send_game_reply(
            M.document()
            .section("兑换码", icon="notice")
            .line("请输入要领取的兑换码")
            .line(M.command("兑换码 VIP666", "兑换码 VIP666"))
            .build()
        )
        return
    context = current_message_context()
    if context is None:
        raise RuntimeError("兑换码命令缺少消息上下文")
    services = current_game_services()
    try:
        result = await asyncio.to_thread(
            services.redemption_codes.redeem,
            character,
            code,
            context.identity.evidence_id,
            logical_time=command_time(),
        )
        view = services.world_view(current.character_world)
        await send_game_reply(_result_message(result, view))
    except Exception as exc:
        await send_command_failure(
            "兑换码领取失败",
            character.id,
            exc,
            _failure("奖励没有发放，请稍后重试"),
        )


def _result_message(result: RedemptionCodeResult, view) -> DocumentMessage:
    if result.status == "already_redeemed":
        return (
            M.document()
            .section("兑换码", icon="notice")
            .line(result.failure_message or "当前账号已经领取过该兑换码")
            .line(M.command("查看武库", "武库"))
            .build()
        )
    if result.status == "invalid":
        return _failure(result.failure_message or "兑换码无效，请检查后重试")
    if result.status == "unavailable":
        return _failure("该兑换码当前不可领取")
    if result.status != "redeemed":
        return _failure(result.failure_message or "兑换没有完成，请稍后重试")

    currency_name = view.projector.name(PRIMARY_CURRENCY_ID)
    builder = (
        M.document()
        .section("兑换码·领取成功", icon="reward")
        .field("获得", f"{result.currency_amount} {currency_name}")
        .section("开荒装备", icon="equipment")
    )
    for item in result.items:
        reference = _item_reference(item)
        builder.line(
            M.command(reference, f"查看 {reference}"),
            " ",
            _item_name(item, view),
            FieldSeparator(),
            view.projector.name(item.slot_id),
        )
    builder.line(
        M.command("装配", "装配"),
        FieldSeparator(),
        M.command("武库", "武库"),
    )
    return builder.build()


def _item_reference(item: RedemptionCodeItem) -> str:
    prefix = "W" if item.kind == "weapon" else "E"
    return f"{prefix}{item.reference_number}"


def _item_name(item: RedemptionCodeItem, view) -> str:
    if item.kind == "weapon":
        return view.gear_projector.weapon(item.state).name
    return view.gear_projector.equipment(item.state).name


def _failure(message: str) -> DocumentMessage:
    return M.document().section("兑换码", icon="notice").line(message).build()


__all__ = ["redeem_code"]
