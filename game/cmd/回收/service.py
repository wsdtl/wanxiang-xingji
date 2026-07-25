"""归航回收参数解析、不可变报价和确认展示。"""

from __future__ import annotations

import asyncio

from game.app import CharacterOverview, CharacterOverviewResult, CurrentCharacterResult, current_game_services
from game.content.catalog.foundation import PRIMARY_CURRENCY_ID, QUALITY_IDS
from game.content.presentation import COVENANT_RECYCLING_NAME
from game.core.gameplay import (
    STANDARD_LOADOUT_SLOT_ORDER,
    WEAPON_SLOT_ID,
    ItemInstance,
    equipment_state_from_instance,
    weapon_state_from_instance,
)
from game.rules.item import asset_reference, resolve_asset_reference
from message import Action, DocumentMessage, M

from ..command_helpers import command_time
from ..reply import send_command_failure, send_game_reply


async def recycle_one(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    token = str(message or "").strip()
    if not token:
        await send_game_reply(_failure("请选择一件武器或装备"))
        return
    try:
        asset = resolve_asset_reference(
            overview.inventory,
            token,
            current_game_services().content.catalog.items,
        )
        if not isinstance(asset, ItemInstance):
            raise ValueError("单件回收只接受武器或装备编号")
        quote_result = await asyncio.to_thread(
            current_game_services().economy.quote_recycle_assets,
            overview.character.id,
            (asset.id,),
        )
        await send_game_reply(
            _quote_message(
                quote_result,
                overview,
                f"single {asset_reference(overview.inventory, asset, current_game_services().content.catalog.items)}",
            )
        )
    except (KeyError, TypeError, ValueError) as exc:
        await send_game_reply(_failure(str(exc)))


async def recycle_batch(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    parts = str(message or "").strip().split()
    if not parts:
        await send_game_reply(_batch_slots(overview))
        return
    slot_id = _slot_id(parts[0], overview)
    if slot_id is None:
        await send_game_reply(_failure("没有找到这个武库部位"))
        return
    if len(parts) == 1:
        await send_game_reply(_batch_qualities(slot_id, overview))
        return
    try:
        maximum_weapon_level = None
        quality_values = parts[1:]
        if slot_id == WEAPON_SLOT_ID:
            if len(parts) == 2:
                await send_game_reply(
                    _batch_levels(
                        slot_id,
                        frozenset({_quality_id(parts[1], overview)}),
                        overview,
                    )
                )
                return
            try:
                maximum_weapon_level = int(parts[-1])
            except ValueError:
                quality_ids = frozenset(_quality_id(value, overview) for value in parts[1:])
                await send_game_reply(_batch_levels(slot_id, quality_ids, overview))
                return
            quality_values = parts[1:-1]
            if maximum_weapon_level < 1:
                raise ValueError("武器等级上限必须大于 0")
        elif any(value.isdigit() for value in parts[1:]):
            raise ValueError("装备没有等级，不能使用等级筛选")
        quality_ids = frozenset(_quality_id(value, overview) for value in quality_values)
        quote_result = await asyncio.to_thread(
            current_game_services().economy.quote_recycle_batch,
            overview.character.id,
            slot_id,
            quality_ids,
            maximum_weapon_level,
        )
        await send_game_reply(
            _quote_message(
                quote_result,
                overview,
                "batch "
                f"{slot_id} {','.join(sorted(quality_ids))}"
                + (f" {maximum_weapon_level}" if maximum_weapon_level is not None else ""),
            )
        )
    except (KeyError, TypeError, ValueError) as exc:
        await send_game_reply(_failure(str(exc)))


async def confirm_recycle(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    parts = str(message or "").strip().split()
    if len(parts) < 3:
        await send_game_reply(_failure("回收确认参数已经失效"))
        return
    mode = parts[0]
    expected_id = parts[-1]
    services = current_game_services()
    try:
        if mode == "single" and len(parts) == 3:
            asset = resolve_asset_reference(
                overview.inventory,
                parts[1],
                services.content.catalog.items,
            )
            quoted = await asyncio.to_thread(
                services.economy.quote_recycle_assets,
                overview.character.id,
                (asset.id,),
            )
        elif mode == "batch" and len(parts) in {4, 5}:
            maximum_weapon_level = None
            if len(parts) == 5:
                try:
                    maximum_weapon_level = int(parts[3])
                except ValueError as exc:
                    raise ValueError("回收确认参数已经失效") from exc
            quoted = await asyncio.to_thread(
                services.economy.quote_recycle_batch,
                overview.character.id,
                parts[1],
                frozenset(value for value in parts[2].split(",") if value),
                maximum_weapon_level,
            )
        else:
            raise ValueError("回收确认参数已经失效")
        if quoted.quote is None or quoted.quote.id != expected_id:
            await send_game_reply(_failure("回收报价已经变化，请重新选择"))
            return
        executed = await asyncio.to_thread(
            services.economy.execute_recycle,
            overview.character.id,
            quoted.quote,
            logical_time=command_time(),
        )
        await send_game_reply(_result_message(executed, overview))
    except (KeyError, TypeError, ValueError) as exc:
        await send_game_reply(_failure(str(exc)))
    except Exception as exc:
        await _failed("回收确认失败", overview.character.id, exc)


async def recycle_trophies(current: CurrentCharacterResult) -> None:
    character = current.character if current.status == "ok" else None
    if character is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    try:
        result = await asyncio.to_thread(
            current_game_services().economy.recycle_trophies,
            character.id,
            logical_time=command_time(),
        )
        view = current_game_services().world_view(current.character_world)
        builder = M.document().section(f"{COVENANT_RECYCLING_NAME}·战利品", icon="trade")
        if result.status == "empty":
            await send_game_reply(builder.line("背包中没有可回收的战利品").build())
            return
        for index, line in enumerate(result.quote.lines[:12], start=1):
            builder.item(
                index,
                f"{view.projector.name(line.definition_id)} x{line.quantity} | "
                f"{line.subtotal} {view.projector.name(line.output_id)}",
            )
        remaining = len(result.quote.lines) - 12
        if remaining > 0:
            builder.note(f"另有 {remaining} 类战利品已一并回收")
        if result.quote.total_amount and result.quote.currency_id is not None:
            builder.field(
                "货币",
                f"{result.quote.total_amount} {view.projector.name(result.quote.currency_id)}",
            )
        for definition_id, quantity in result.quote.stack_item_totals.items():
            builder.field("材料", f"{quantity} {view.projector.name(definition_id)}")
        await send_game_reply(
            builder.note("按名录类型化产出结算，不动用归航库，也不收交易税。").build()
        )
    except Exception as exc:
        await _failed("回收战利品失败", character.id, exc)


def _quote_message(result, overview: CharacterOverview, command_prefix: str) -> DocumentMessage:
    builder = M.document().section(f"{COVENANT_RECYCLING_NAME}·报价", icon="trade")
    quote = result.quote
    if result.status != "quoted" or quote is None:
        return builder.line(result.failure_message or "没有符合条件的可回收物品").build()
    for index, line in enumerate(quote.lines[:12], start=1):
        asset = overview.inventory.instances[line.asset_id]
        builder.item(
            index,
            f"{_gear_name(asset, overview)} | {_reference(asset, overview)} | {line.recycle_amount}",
        )
    remaining = len(quote.lines) - 12
    if remaining > 0:
        builder.note(f"另有 {remaining} 件物品包含在本次固定报价中")
    builder.row(
        ("数量", len(quote.lines)),
        ("参考总价", quote.total_reference_price),
        ("回收所得", quote.total_amount),
    )
    builder.note("确认后永久注销物品档案；本次结算不动用归航库，也不收交易税。")
    return builder.actions(
        (
            Action(
                "economy.recycle.confirm",
                "确认回收",
                f"economy_recycle_confirm {command_prefix} {quote.id}",
                style="secondary",
            ),
        )
    ).build()


def _result_message(result, overview: CharacterOverview) -> DocumentMessage:
    builder = M.document().section(f"{COVENANT_RECYCLING_NAME}·完成", icon="trade")
    if result.status != "recycled" or result.quote is None:
        return builder.line(result.failure_message or "本次回收没有完成").build()
    return builder.row(
        ("回收", f"{len(result.quote.lines)} 件"),
        (
            "收入",
            f"{result.quote.total_amount} {_view(overview).projector.name(PRIMARY_CURRENCY_ID)}",
        ),
    ).build()


def _batch_slots(overview: CharacterOverview) -> DocumentMessage:
    view = _view(overview)
    builder = M.document().section(COVENANT_RECYCLING_NAME, icon="trade")
    return builder.actions(
        tuple(
            Action(
                f"economy.recycle.slot.{slot_id}",
                view.projector.name(slot_id),
                f"批量回收 {slot_id}",
            )
            for slot_id in STANDARD_LOADOUT_SLOT_ORDER
        )
    ).build()


def _batch_qualities(slot_id: str, overview: CharacterOverview) -> DocumentMessage:
    view = _view(overview)
    builder = M.document().section(
        f"{COVENANT_RECYCLING_NAME}·{view.projector.name(slot_id)}",
        icon="trade",
    )
    return builder.actions(
        tuple(
                Action(
                f"economy.recycle.quality.{quality_id}",
                view.projector.name(quality_id),
                    f"批量回收 {slot_id} {quality_id}",
                )
            for quality_id in QUALITY_IDS
        )
    ).build()


def _batch_levels(
    slot_id: str,
    quality_ids: frozenset[str],
    overview: CharacterOverview,
) -> DocumentMessage:
    """武器先选品阶，再选等级上限；等级按钮只负责填写筛选条件。"""

    view = _view(overview)
    maximum_level = max(
        (
            profile.maximum_level
            for definition in current_game_services().content.catalog.weapons.definitions
            for profile in definition.quality_profiles.values()
        ),
        default=100,
    )
    limits = tuple(value for value in (1, 10, 20, 40, 60, 80, 100) if value <= maximum_level)
    if maximum_level not in limits:
        limits += (maximum_level,)
    quality_text = ",".join(sorted(view.projector.name(value) for value in quality_ids))
    builder = M.document().section(
        f"{COVENANT_RECYCLING_NAME}·武器·{quality_text}",
        icon="trade",
    ).note("选择等级上限，回收该等级及以下的武器")
    return builder.actions(
        tuple(
            Action(
                f"economy.recycle.level.{limit}",
                f"Lv{limit}及以下",
                f"批量回收 {slot_id} {','.join(sorted(quality_ids))} {limit}",
            )
            for limit in limits
        )
    ).build()


def _slot_id(value: str, overview: CharacterOverview) -> str | None:
    if value in STANDARD_LOADOUT_SLOT_ORDER:
        return value
    view = _view(overview)
    resolved = view.projector.resolve_alias(value)
    if resolved in STANDARD_LOADOUT_SLOT_ORDER:
        return resolved
    aliases = {
        "武器": STANDARD_LOADOUT_SLOT_ORDER[0],
        "头部": STANDARD_LOADOUT_SLOT_ORDER[1],
        "身体": STANDARD_LOADOUT_SLOT_ORDER[2],
        "手部": STANDARD_LOADOUT_SLOT_ORDER[3],
        "腰部": STANDARD_LOADOUT_SLOT_ORDER[4],
        "脚部": STANDARD_LOADOUT_SLOT_ORDER[5],
        "饰品": STANDARD_LOADOUT_SLOT_ORDER[6],
    }
    return aliases.get(value)


def _quality_id(value: str, overview: CharacterOverview) -> str:
    if value in QUALITY_IDS:
        return value
    resolved = _view(overview).projector.resolve_alias(value)
    if resolved not in QUALITY_IDS:
        raise ValueError(f"未知品阶: {value}")
    return resolved


def _gear_name(instance: ItemInstance, overview: CharacterOverview) -> str:
    view = _view(overview)
    definition = current_game_services().content.catalog.items.require(instance.definition_id)
    if definition.tags.has("item.weapon"):
        return view.gear_projector.weapon(
            weapon_state_from_instance(instance),
            instance,
            inscription_preference=overview.inscription_preference,
        ).name
    return view.gear_projector.equipment(
        equipment_state_from_instance(instance),
        instance,
        inscription_preference=overview.inscription_preference,
    ).name


def _reference(instance, overview) -> str:
    return asset_reference(
        overview.inventory,
        instance,
        current_game_services().content.catalog.items,
    )


def _view(overview: CharacterOverview):
    return current_game_services().world_view(overview.character_world)


def _overview(result: CharacterOverviewResult) -> CharacterOverview | None:
    return result.overview if result.status == "ok" else None


async def _failed(title: str, character_id: str, exc: Exception) -> None:
    await send_command_failure(
        title,
        character_id,
        exc,
        _failure("当前操作没有完成，请稍后重试"),
    )


def _failure(message: str) -> DocumentMessage:
    return M.document().section(COVENANT_RECYCLING_NAME, icon="notice").line(message).build()


__all__ = [
    "confirm_recycle",
    "recycle_batch",
    "recycle_one",
    "recycle_trophies",
]
