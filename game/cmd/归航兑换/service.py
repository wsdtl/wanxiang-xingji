"""归航兑换目录、直接兑换与记录展示。"""

from __future__ import annotations

import asyncio

from game.app import CurrentCharacterResult, current_game_services
from game.content.catalog.economy import EQUIPMENT_SET_BLUEPRINT_PRICE
from game.content.catalog.item import EXCHANGE_MATERIAL_ITEM_ID
from launch.adapter import current_message_context
from message import Action, DocumentMessage, M

from ..command_helpers import command_time
from ..interaction import (
    DEFAULT_PAGE_SIZE,
    paginate,
    pagination_actions,
    parse_page_number,
)
from ..reply import send_command_failure, send_game_reply


PAGE_SIZE = DEFAULT_PAGE_SIZE


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
            .line(M.command("套装图纸", "归航兑换 套装"))
            .build()
        )
        return
    parts = token.split()
    if parts[0] == "套装":
        try:
            if len(parts) > 2:
                raise ValueError("套装图纸页码必须是正整数")
            page = parse_page_number(parts[1] if len(parts) == 2 else "")
        except ValueError:
            await send_game_reply(_failure("套装图纸页码必须是正整数"))
            return
        try:
            await send_game_reply(await _set_page(character.id, page, view))
        except ValueError as exc:
            await send_game_reply(
                _failure(
                    str(exc),
                    Action("exchange.back", "返回兑换", "归航兑换", style="secondary"),
                )
            )
        return
    try:
        set_id = _resolve_set_id(token, view)
        await _redeem_blueprint(character.id, set_id, view)
    except (KeyError, ValueError) as exc:
        await send_game_reply(
            _failure(
                str(exc),
                Action("exchange.back", "返回套装", "归航兑换 套装", style="secondary"),
            )
        )
    except Exception as exc:
        await send_command_failure(
            "归航兑换失败",
            character.id,
            exc,
            _failure("兑换没有完成，请稍后重试"),
        )


async def confirm_covenant_exchange(message: str, current: CurrentCharacterResult) -> None:
    character = current.character if current.status == "ok" else None
    if character is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    parts = str(message or "").strip().split()
    if len(parts) != 2:
        await send_game_reply(
            _failure(
                "兑换确认参数已经失效",
                Action("exchange.back", "返回套装", "归航兑换 套装", style="secondary"),
            )
        )
        return
    try:
        price = int(parts[1])
        if price != EQUIPMENT_SET_BLUEPRINT_PRICE:
            raise ValueError("兑换价格已经变化，请重新预览")
        services = current_game_services()
        set_id = services.content.catalog.equipment.sets.require(parts[0]).id
        await _redeem_blueprint(
            character.id,
            set_id,
            services.world_view(current.character_world),
        )
    except (KeyError, TypeError, ValueError) as exc:
        set_token = parts[0] if parts else ""
        await send_game_reply(
            _failure(
                str(exc),
                Action(
                    "exchange.retry_preview",
                    "重新预览" if set_token else "返回套装",
                    f"归航兑换 {set_token}" if set_token else "归航兑换 套装",
                ),
            )
        )
    except Exception as exc:
        await send_command_failure(
            "归航兑换失败",
            character.id,
            exc,
            _failure("兑换没有完成，请稍后重试"),
        )


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
    window = paginate(set_ids, page, page_size=PAGE_SIZE)
    balance = await asyncio.to_thread(services.covenant_exchange.material_balance, actor_id)
    builder = (
        M.document()
        .section("归航兑换·套装", icon="equipment")
        .field(view.projector.name(EXCHANGE_MATERIAL_ITEM_ID), balance)
    )
    for index, set_id in enumerate(window.values, start=window.start + 1):
        builder.item(
            index,
            M.command(view.projector.name(set_id), f"归航兑换 {set_id}"),
            f" | {EQUIPMENT_SET_BLUEPRINT_PRICE} 定相尘",
        )
    builder.row(("页码", window.label), ("总计", window.total)).actions(
        pagination_actions("归航兑换 套装", window)
    )
    return builder.build()


async def _redeem_blueprint(actor_id: str, set_id: str, view) -> None:
    services = current_game_services()
    services.content.catalog.equipment.sets.require(set_id)
    context = current_message_context()
    if context is None:
        raise RuntimeError("归航兑换缺少消息上下文")
    result = await asyncio.to_thread(
        services.covenant_exchange.redeem_blueprint,
        actor_id,
        set_id,
        f"covenant-exchange:{context.identity.evidence_id}",
        logical_time=command_time(),
    )
    if result.receipt is None:
        await send_game_reply(
            _failure(
                result.failure_message or "兑换没有完成",
                Action("exchange.back", "返回套装", "归航兑换 套装", style="secondary"),
            )
        )
        return
    await send_game_reply(
        M.document()
        .section("归航兑换·完成", icon="reward")
        .field(
            "消耗",
            f"{EQUIPMENT_SET_BLUEPRINT_PRICE} {view.projector.name(EXCHANGE_MATERIAL_ITEM_ID)}",
        )
        .field("获得", view.projector.name(result.receipt.blueprint_definition_id))
        .actions(
            (
                Action("inventory.open", "查看纳戒", "纳戒"),
                Action(
                    "exchange.back",
                    "继续兑换",
                    "归航兑换 套装",
                    style="secondary",
                ),
            )
        )
        .build()
    )


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


def _failure(message: str, recovery: Action | None = None) -> DocumentMessage:
    builder = M.document().section("归航兑换", icon="notice").line(message)
    if recovery is not None:
        builder.action(recovery)
    return builder.build()


__all__ = [
    "PAGE_SIZE",
    "confirm_covenant_exchange",
    "covenant_exchange",
    "covenant_exchange_history",
]
