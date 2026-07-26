"""装配命令解析、持久化调用与协议中立展示。"""

from __future__ import annotations

import asyncio

from game.app import CurrentCharacterResult, current_game_services
from game.content import LOADOUT_PRESET_IDS
from game.core.gameplay import (
    LOADOUT_ITEM_COMPONENT_ID,
    STANDARD_LOADOUT_SLOT_ORDER,
    ActivateLoadoutPreset,
    EquipAsset,
    InventoryState,
    ItemInstance,
    LoadoutItemComponent,
    LoadoutState,
    LoadoutTransaction,
    UnequipSlot,
    equipment_state_from_instance,
    weapon_state_from_instance,
)
from game.rules import game_operation_context
from game.rules.item import asset_reference, resolve_asset_reference
from launch import C, logger
from launch.adapter import current_message_context
from message import DocumentMessage, M
from message.schema import FieldSeparator

from ..command_helpers import command_time
from ..interaction import DEFAULT_PAGE_SIZE
from ..reply import send_game_reply


_CANDIDATE_LIMIT = DEFAULT_PAGE_SIZE


async def view_loadout(current: CurrentCharacterResult) -> None:
    state = await _state(current)
    await send_game_reply(
        _loadout_message(state[1], state[2], state[3], state[4]) if state else _unavailable()
    )


async def equip(message: str, current: CurrentCharacterResult) -> None:
    state = await _state(current)
    if state is None:
        await send_game_reply(_unavailable())
        return
    character, loadout, inventory, preference, view = state
    token = str(message or "").strip()
    if not token:
        await send_game_reply(_usage("装备", "装备 物品编号"))
        return
    try:
        instance = _instance(inventory, token)
        definition = current_game_services().content.catalog.items.require(
            instance.definition_id
        )
        component = definition.component(
            LOADOUT_ITEM_COMPONENT_ID,
            LoadoutItemComponent,
        )
        if len(component.allowed_slot_ids) != 1:
            raise ValueError("物品没有唯一装配槽位")
        operation = EquipAsset(next(iter(component.allowed_slot_ids)), instance.id)
    except (KeyError, TypeError, ValueError) as exc:
        await send_game_reply(_rejected(str(exc)))
        return
    await _execute(character, loadout, inventory, preference, view, operation, "装备")


async def unequip(message: str, current: CurrentCharacterResult) -> None:
    state = await _state(current)
    if state is None:
        await send_game_reply(_unavailable())
        return
    character, loadout, inventory, preference, view = state
    requested = str(message or "").strip()
    slot_id = _slot_id(requested, view)
    if slot_id is None:
        await send_game_reply(_usage("卸下", "卸下 武器/冠首/法衣/护手/腰佩/履靴/饰品"))
        return
    await _execute(
        character,
        loadout,
        inventory,
        preference,
        view,
        UnequipSlot(slot_id),
        "卸下",
    )


async def presets(message: str, current: CurrentCharacterResult) -> None:
    state = await _state(current)
    if state is None:
        await send_game_reply(_unavailable())
        return
    character, loadout, inventory, preference, view = state
    requested = str(message or "").strip()
    if not requested:
        await send_game_reply(_preset_message(loadout, view))
        return
    try:
        index = int(requested)
        preset_id = LOADOUT_PRESET_IDS[index]
    except (ValueError, IndexError):
        await send_game_reply(_usage("配装", "配装只支持 0 至 5"))
        return
    await _execute(
        character,
        loadout,
        inventory,
        preference,
        view,
        ActivateLoadoutPreset(preset_id),
        f"切换配装 {index}",
    )


async def _execute(
    character,
    loadout,
    inventory,
    preference,
    view,
    operation,
    title: str,
) -> None:
    services = current_game_services()
    try:
        inventory_container = _container(inventory, "container.armory")
        equipped_container = _container(inventory, "container.equipped")
        transaction = LoadoutTransaction(
            _transaction_id("loadout"),
            character.id,
            loadout.revision,
            inventory_container,
            equipped_container,
            (operation,),
        )
        outcome = await asyncio.to_thread(
            services.loadouts.execute,
            transaction,
            inventory_id=character.id,
            character_id=character.id,
            context=game_operation_context(transaction.id, logical_time=command_time()),
        )
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(C.fail(f"{title}执行失败"), C.kv("character", character.id))
        )
        await send_game_reply(_unavailable())
        return
    if outcome.failure:
        await send_game_reply(_rejected(outcome.failure.message))
        return
    assert outcome.value is not None
    execution = outcome.value.execution
    await send_game_reply(
        _loadout_message(execution.loadout, execution.inventory, preference, view)
    )


async def _state(current: CurrentCharacterResult):
    character = current.character if current.status == "ok" else None
    if character is None:
        return None
    try:
        result = await asyncio.to_thread(
            current_game_services().load_character_overview,
            character,
        )
        if result.status != "ok" or result.overview is None:
            return None
        return (
            character,
            result.overview.loadout,
            result.overview.inventory,
            result.overview.inscription_preference,
            current_game_services().world_view(result.overview.character_world),
        )
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(C.fail("装配状态读取失败"), C.kv("character", character.id))
        )
        return None


def _loadout_message(
    loadout: LoadoutState,
    inventory: InventoryState,
    preference,
    view,
) -> DocumentMessage:
    active = _preset_index(loadout.active_preset_id)
    builder = (
        M.document()
        .section("当前装配", icon="equipment")
        .field("世界", view.skin.name)
        .field("当前配装", active if active is not None else "未绑定")
    )
    for slot_id in STANDARD_LOADOUT_SLOT_ORDER:
        asset_id = loadout.slots.get(slot_id)
        if asset_id is None:
            value = "空"
        else:
            instance = inventory.instances.get(asset_id)
            if instance is None:
                value = "数据异常"
            else:
                reference = _reference(inventory, instance)
                value = M.command(
                    f"{reference} {_name(instance, preference, view)}",
                    f"查看 {reference}",
                )
        builder.field(view.projector.name(slot_id), value)

    candidates = _candidates(loadout, inventory)
    if candidates:
        builder.section("可装备", icon="inventory")
        for instance in candidates[:_CANDIDATE_LIMIT]:
            reference = _reference(inventory, instance)
            builder.line(
                M.command(
                    _name(instance, preference, view),
                    f"装备 {reference}",
                ),
                FieldSeparator(),
                reference,
            )
        if len(candidates) > _CANDIDATE_LIMIT:
            builder.line(
                f"另有 {len(candidates) - _CANDIDATE_LIMIT} 件，",
                M.command("查看完整武库", "武库"),
            )
    return builder.build()


def _preset_message(loadout: LoadoutState, view) -> DocumentMessage:
    builder = (
        M.document()
        .section("六套配装", icon="equipment")
        .field("世界", view.skin.name)
    )
    for index, preset_id in enumerate(LOADOUT_PRESET_IDS):
        preset = loadout.presets[preset_id]
        label = f"配装 {index}"
        if preset_id == loadout.active_preset_id:
            label += "（当前）"
        builder.line(
            M.command(label, f"配装 {index}"),
            FieldSeparator(),
            f"{len(preset.slots)}/7",
        )
    return builder.build()


def _candidates(loadout: LoadoutState, inventory: InventoryState) -> list[ItemInstance]:
    catalog = current_game_services().content.catalog.items
    active = loadout.active_preset_id
    bound_elsewhere = {
        asset_id
        for preset_id, preset in loadout.presets.items()
        if preset_id != active
        for asset_id in preset.slots.values()
    }
    values = []
    for instance in inventory.instances.values():
        definition = catalog.require(instance.definition_id)
        component = definition.components.get(LOADOUT_ITEM_COMPONENT_ID)
        if (
            not isinstance(component, LoadoutItemComponent)
            or len(component.allowed_slot_ids) != 1
            or instance.id in bound_elsewhere
            or inventory.containers[instance.container_id].kind != "container.armory"
        ):
            continue
        slot_id = next(iter(component.allowed_slot_ids))
        current_id = loadout.slots.get(slot_id)
        current = inventory.instances.get(current_id) if current_id is not None else None
        if current_id is not None and current is not None:
            candidate_score = _gear_score(instance, definition)
            current_definition = catalog.require(current.definition_id)
            current_score = _gear_score(current, current_definition)
            if candidate_score is None or (
                current_score is not None and candidate_score <= current_score
            ):
                continue
        values.append(instance)
    return sorted(
        values,
        key=lambda value: _candidate_sort_key(value, inventory, catalog),
    )


def _gear_score(instance: ItemInstance, definition) -> float | None:
    if definition.tags.has("item.weapon"):
        roll = weapon_state_from_instance(instance).roll
    elif definition.tags.has("item.equipment"):
        roll = equipment_state_from_instance(instance).roll
    else:
        return None
    return None if roll is None else roll.intrinsic_value.total


def _candidate_sort_key(instance: ItemInstance, inventory: InventoryState, catalog):
    definition = catalog.require(instance.definition_id)
    score = _gear_score(instance, definition)
    return (
        score is None,
        -(score if score is not None else 0.0),
        inventory.reference_number(instance.id),
    )


def _instance(inventory: InventoryState, token: str) -> ItemInstance:
    asset = resolve_asset_reference(
        inventory,
        token,
        current_game_services().content.catalog.items,
    )
    if not isinstance(asset, ItemInstance):
        raise ValueError("指定编号不是武器或装备")
    return asset


def _reference(inventory: InventoryState, instance: ItemInstance) -> str:
    return asset_reference(
        inventory,
        instance,
        current_game_services().content.catalog.items,
    )


def _name(instance: ItemInstance, preference, view) -> str:
    services = current_game_services()
    definition = services.content.catalog.items.require(instance.definition_id)
    if definition.tags.has("item.weapon"):
        return view.gear_projector.weapon(
            weapon_state_from_instance(instance),
            instance,
            inscription_preference=preference,
        ).name
    if definition.tags.has("item.equipment"):
        return view.gear_projector.equipment(
            equipment_state_from_instance(instance),
            instance,
            inscription_preference=preference,
        ).name
    return view.projector.name(instance.definition_id)


def _slot_id(value: str, view) -> str | None:
    requested = value.strip().casefold()
    if requested in STANDARD_LOADOUT_SLOT_ORDER:
        return requested
    aliases = {
        view.projector.name(slot_id).casefold(): slot_id
        for slot_id in STANDARD_LOADOUT_SLOT_ORDER
    }
    aliases.update(
        {
            "武器": STANDARD_LOADOUT_SLOT_ORDER[0],
            "头部": STANDARD_LOADOUT_SLOT_ORDER[1],
            "冠首": STANDARD_LOADOUT_SLOT_ORDER[1],
            "身体": STANDARD_LOADOUT_SLOT_ORDER[2],
            "法衣": STANDARD_LOADOUT_SLOT_ORDER[2],
            "护甲": STANDARD_LOADOUT_SLOT_ORDER[2],
            "手部": STANDARD_LOADOUT_SLOT_ORDER[3],
            "护手": STANDARD_LOADOUT_SLOT_ORDER[3],
            "腰部": STANDARD_LOADOUT_SLOT_ORDER[4],
            "腰佩": STANDARD_LOADOUT_SLOT_ORDER[4],
            "足部": STANDARD_LOADOUT_SLOT_ORDER[5],
            "履靴": STANDARD_LOADOUT_SLOT_ORDER[5],
            "饰品": STANDARD_LOADOUT_SLOT_ORDER[6],
        }
    )
    return aliases.get(requested)


def _container(inventory: InventoryState, kind: str) -> str:
    for container in inventory.containers.values():
        if container.kind == kind:
            return container.id
    raise ValueError(f"库存缺少容器：{kind}")


def _preset_index(preset_id: str | None) -> int | None:
    if preset_id is None:
        return None
    try:
        return LOADOUT_PRESET_IDS.index(preset_id)
    except ValueError:
        return None


def _transaction_id(prefix: str) -> str:
    context = current_message_context()
    if context is None:
        raise RuntimeError("装配命令缺少消息上下文")
    return f"{prefix}:{context.identity.evidence_id}"


def _usage(title: str, text: str) -> DocumentMessage:
    return M.document().section(title, icon="equipment").line(text).build()


def _rejected(message: str) -> DocumentMessage:
    return M.document().section("装配未完成", icon="notice").line(message).build()


def _unavailable() -> DocumentMessage:
    return M.document().section("装配", icon="notice").line(
        "当前没有读取到装配状态，请稍后重试"
    ).build()


__all__ = ["equip", "presets", "unequip", "view_loadout"]
