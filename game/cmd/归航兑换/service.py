"""归航兑换目录、预览、确认与记录展示。"""

from __future__ import annotations

import asyncio
from math import ceil

from game.app import CurrentCharacterResult, current_game_services
from game.content.catalog.economy import EQUIPMENT_SET_BLUEPRINT_PRICE
from game.content.catalog.item import EXCHANGE_MATERIAL_ITEM_ID
from launch import C, logger
from launch.adapter import current_message_context
from message import Action, DocumentMessage, M

from ..command_helpers import command_time
from ..reply import send_game_reply


PAGE_SIZE = 6


async def covenant_exchange(message: str, current: CurrentCharacterResult) -> None:
    character = current.character if current.status == "ok" else None
    if character is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    services = current_game_services()
    view = services.world_view(current.character_world)
    token = str(message or "").strip()
    if not token:
        balance = await asyncio.to_thread(services.covenant_exchange.material_balance, character.id)
        await send_game_reply(
            M.document()
            .section("归航兑换", icon="trade")
            .field(view.projector.name(EXCHANGE_MATERIAL_ITEM_ID), balance)
            .actions((Action("exchange.sets", "套装图纸", "归航兑换 套装"),))
            .build()
        )
        return
    parts = token.split()
    if parts[0] == "套装":
        try:
            page = int(parts[1]) if len(parts) == 2 else 1
            if len(parts) > 2 or page < 1:
                raise ValueError
        except ValueError:
            await send_game_reply(_failure("套装图纸页码必须是正整数"))
            return
        await send_game_reply(await _set_page(character.id, page, view))
        return
    try:
        set_id = _resolve_set_id(token, view)
        await send_game_reply(await _set_detail(character.id, set_id, view))
    except (KeyError, ValueError) as exc:
        await send_game_reply(_failure(str(exc)))


async def confirm_covenant_exchange(message: str, current: CurrentCharacterResult) -> None:
    character = current.character if current.status == "ok" else None
    if character is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    parts = str(message or "").strip().split()
    if len(parts) != 2:
        await send_game_reply(_failure("兑换确认参数已经失效"))
        return
    try:
        price = int(parts[1])
        if price != EQUIPMENT_SET_BLUEPRINT_PRICE:
            raise ValueError("兑换价格已经变化，请重新预览")
        services = current_game_services()
        set_id = services.content.catalog.equipment.sets.require(parts[0]).id
        context = current_message_context()
        if context is None:
            raise RuntimeError("归航兑换缺少消息上下文")
        result = await asyncio.to_thread(
            services.covenant_exchange.redeem_blueprint,
            character.id,
            set_id,
            f"covenant-exchange:{context.identity.evidence_id}",
            logical_time=command_time(),
        )
        view = services.world_view(current.character_world)
        if result.receipt is None:
            await send_game_reply(_failure(result.failure_message or "兑换没有完成"))
            return
        await send_game_reply(
            M.document()
            .section("归航兑换·完成", icon="reward")
            .field("消耗", f"{price} {view.projector.name(EXCHANGE_MATERIAL_ITEM_ID)}")
            .field("获得", view.projector.name(result.receipt.blueprint_definition_id))
            .actions((Action("inventory.open", "查看纳戒", "纳戒"),))
            .build()
        )
    except (KeyError, TypeError, ValueError) as exc:
        await send_game_reply(_failure(str(exc)))
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(C.fail("归航兑换失败"), C.kv("character", character.id))
        )
        await send_game_reply(_failure("兑换没有完成，请稍后重试"))


async def covenant_exchange_history(current: CurrentCharacterResult) -> None:
    character = current.character if current.status == "ok" else None
    if character is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    services = current_game_services()
    history = await asyncio.to_thread(services.covenant_exchange.history, character.id)
    view = services.world_view(current.character_world)
    builder = M.document().section("归航兑换记录", icon="history")
    if not history.records:
        await send_game_reply(builder.line("暂无兑换记录").build())
        return
    for index, record in enumerate(reversed(history.records), start=1):
        builder.item(
            index,
            f"{view.projector.name(record.set_id)} | "
            f"{record.material_quantity} {view.projector.name(record.material_definition_id)}",
        )
    await send_game_reply(builder.build())


async def _set_page(actor_id: str, page: int, view) -> DocumentMessage:
    services = current_game_services()
    set_ids = services.content.catalog.equipment.sets.ids()
    pages = max(1, ceil(len(set_ids) / PAGE_SIZE))
    if page > pages:
        raise ValueError(f"页码不能超过 {pages}")
    balance = await asyncio.to_thread(services.covenant_exchange.material_balance, actor_id)
    start = (page - 1) * PAGE_SIZE
    values = set_ids[start : start + PAGE_SIZE]
    builder = (
        M.document()
        .section(f"归航兑换·套装 {page}/{pages}", icon="equipment")
        .field(view.projector.name(EXCHANGE_MATERIAL_ITEM_ID), balance)
    )
    for index, set_id in enumerate(values, start=start + 1):
        builder.item(index, f"{view.projector.name(set_id)} | {EQUIPMENT_SET_BLUEPRINT_PRICE} 定相尘")
    actions = [
        Action(f"exchange.set.{set_id}", view.projector.compact_name(set_id), f"归航兑换 {set_id}")
        for set_id in values
    ]
    if page > 1:
        actions.append(Action("exchange.previous", "上一页", f"归航兑换 套装 {page - 1}"))
    if page < pages:
        actions.append(Action("exchange.next", "下一页", f"归航兑换 套装 {page + 1}"))
    return builder.actions(tuple(actions)).build()


async def _set_detail(actor_id: str, set_id: str, view) -> DocumentMessage:
    services = current_game_services()
    definition = services.content.catalog.equipment.sets.require(set_id)
    balance = await asyncio.to_thread(services.covenant_exchange.material_balance, actor_id)
    builder = (
        M.document()
        .section(view.projector.name(set_id), icon="equipment")
        .line(view.projector.entry(set_id).description)
    )
    for bonus in definition.bonuses:
        builder.field(f"{bonus.required_pieces}件", _contribution_text(bonus.contribution, view))
    builder.row(
        ("价格", f"{EQUIPMENT_SET_BLUEPRINT_PRICE} 定相尘"),
        ("持有", balance),
    ).note("图纸只固定套装；部位、底座、品阶和随机词条均不固定。")
    if balance >= EQUIPMENT_SET_BLUEPRINT_PRICE:
        builder.actions(
            (
                Action(
                    "exchange.confirm",
                    "确认兑换",
                    f"covenant_exchange_confirm {set_id} {EQUIPMENT_SET_BLUEPRINT_PRICE}",
                    style="secondary",
                ),
            )
        )
    return builder.build()


def _contribution_text(contribution, view) -> str:
    values = []
    for grant in contribution.attributes:
        amount = grant.value
        rendered = f"{amount * 100:+g}%" if abs(amount) < 1 else f"{amount:+g}"
        values.append(f"{view.projector.name(grant.attribute_id)} {rendered}")
    values.extend(view.projector.name(trigger_id) for trigger_id in sorted(contribution.triggers))
    return "、".join(values) or "无"


def _resolve_set_id(value: str, view) -> str:
    catalog = current_game_services().content.catalog.equipment.sets
    if value.isdigit():
        index = int(value)
        if 1 <= index <= len(catalog.ids()):
            return catalog.ids()[index - 1]
    if value in catalog.ids():
        return catalog.require(value).id
    resolved = view.projector.resolve_alias(value)
    if resolved in catalog.ids():
        return catalog.require(resolved).id
    raise ValueError("没有找到这个套装")


def _failure(message: str) -> DocumentMessage:
    return M.document().section("归航兑换", icon="notice").line(message).build()


__all__ = [
    "PAGE_SIZE",
    "confirm_covenant_exchange",
    "covenant_exchange",
    "covenant_exchange_history",
]
