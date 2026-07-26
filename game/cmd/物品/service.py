"""物品查询、实例详情与资产保护的协议中立实现。"""

from __future__ import annotations

import asyncio
from collections import Counter
from zoneinfo import ZoneInfo

from game.app import (
    CharacterOverview,
    CharacterOverviewResult,
    current_game_services,
)
from game.content.catalog.combat import (
    LARGE_MEDICINE_RECOVERY_RATIO,
    MEDIUM_MEDICINE_RECOVERY_RATIO,
    SMALL_MEDICINE_RECOVERY_RATIO,
)
from game.content.catalog.item import (
    ITEM_RECYCLE_COMPONENT_ID,
    LARGE_HEALTH_MEDICINE_ITEM_ID,
    LARGE_SPIRIT_MEDICINE_ITEM_ID,
    MEDIUM_HEALTH_MEDICINE_ITEM_ID,
    MEDIUM_SPIRIT_MEDICINE_ITEM_ID,
    SMALL_HEALTH_MEDICINE_ITEM_ID,
    SMALL_SPIRIT_MEDICINE_ITEM_ID,
    CurrencyRecycleYield,
    StackItemRecycleYield,
)
from game.core.gameplay import (
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    ITEM_STORAGE_COMPONENT_ID,
    LOADOUT_ITEM_COMPONENT_ID,
    SPIRIT_CURRENT,
    SPIRIT_MAXIMUM,
    STANDARD_LOADOUT_SLOT_ORDER,
    AssetAvailability,
    EquipmentState,
    InscriptionMediumData,
    InscriptionProjector,
    InventoryState,
    ItemInstance,
    ItemStack,
    ItemStorageComponent,
    LoadoutItemComponent,
    WeaponContributionProvider,
    WeaponState,
    equipment_state_from_instance,
    weapon_state_from_instance,
)
from game.core.gameplay.inscription import INSCRIPTION_MEDIUM_DATA_KEY
from game.rules import game_operation_context
from game.rules.character import equipped_character_contributions
from game.rules.item import asset_reference, resolve_asset_reference
from launch import C, config, logger
from launch.adapter import current_message_context
from message import Action, DocumentMessage, M
from message.schema import FieldSeparator

from ..command_helpers import command_time
from ..interaction import (
    DEFAULT_PAGE_SIZE,
    paginate,
    pagination_actions,
    parse_page_number,
)
from ..reply import send_game_reply


PAGE_SIZE = DEFAULT_PAGE_SIZE
_MEDICINE_RESOURCE = {
    SMALL_HEALTH_MEDICINE_ITEM_ID: (HEALTH_CURRENT, HEALTH_MAXIMUM, SMALL_MEDICINE_RECOVERY_RATIO),
    MEDIUM_HEALTH_MEDICINE_ITEM_ID: (HEALTH_CURRENT, HEALTH_MAXIMUM, MEDIUM_MEDICINE_RECOVERY_RATIO),
    LARGE_HEALTH_MEDICINE_ITEM_ID: (HEALTH_CURRENT, HEALTH_MAXIMUM, LARGE_MEDICINE_RECOVERY_RATIO),
    SMALL_SPIRIT_MEDICINE_ITEM_ID: (SPIRIT_CURRENT, SPIRIT_MAXIMUM, SMALL_MEDICINE_RECOVERY_RATIO),
    MEDIUM_SPIRIT_MEDICINE_ITEM_ID: (SPIRIT_CURRENT, SPIRIT_MAXIMUM, MEDIUM_MEDICINE_RECOVERY_RATIO),
    LARGE_SPIRIT_MEDICINE_ITEM_ID: (SPIRIT_CURRENT, SPIRIT_MAXIMUM, LARGE_MEDICINE_RECOVERY_RATIO),
}

_GEAR_SOURCE_NAMES = {
    "source.character_creation": "初始获得",
    "source.exploration": "探险",
    "reward.party_battle": "组队挑战",
    "source.draw": "抽奖",
    "source.dimensional_disaster": "跨界灾厄",
    "source.breakthrough": "境界突破",
}


async def nacre(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_unavailable("纳戒"))
        return
    try:
        page = _page_number(message)
    except ValueError as exc:
        await send_game_reply(_invalid("纳戒", str(exc)))
        return
    assets = _container_assets(overview.inventory, "container.special")
    try:
        reply = _asset_page("纳戒", "inventory", assets, page, overview)
    except ValueError as exc:
        reply = _invalid("纳戒", str(exc))
    await send_game_reply(reply)


async def armory(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_unavailable("武库"))
        return
    requested = str(message or "").strip()
    if not requested:
        await send_game_reply(_armory_home(overview))
        return
    parts = requested.split()
    view = _view(overview)
    slot_id = (
        parts[0]
        if parts[0] in STANDARD_LOADOUT_SLOT_ORDER
        else view.projector.resolve_alias(parts[0])
    )
    if slot_id not in STANDARD_LOADOUT_SLOT_ORDER:
        await send_game_reply(_invalid("武库", "请通过武库中的部位按钮查看"))
        return
    try:
        page = _page_number(parts[1] if len(parts) > 1 else "")
    except ValueError as exc:
        await send_game_reply(_invalid("武库", str(exc)))
        return
    assets = _armory_assets(overview, slot_id)
    title = f"武库·{view.projector.name(slot_id)}"
    try:
        reply = _asset_page(
            title,
            "equipment",
            assets,
            page,
            overview,
            page_command=f"武库 {slot_id}",
        )
    except ValueError as exc:
        reply = _invalid("武库", str(exc))
    await send_game_reply(reply)


async def backpack(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_unavailable("背包"))
        return
    try:
        page = _page_number(message)
    except ValueError as exc:
        await send_game_reply(_invalid("背包", str(exc)))
        return
    assets = _container_assets(overview.inventory, "container.backpack")
    try:
        reply = _backpack_page(assets, page, overview)
    except ValueError as exc:
        reply = _invalid("背包", str(exc))
    await send_game_reply(reply)


async def inspect(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_unavailable("查看"))
        return
    token = str(message or "").strip()
    if not token:
        await send_game_reply(_invalid("查看", "发送: 查看 物品编号"))
        return
    try:
        asset = resolve_asset_reference(
            overview.inventory,
            token,
            current_game_services().content.catalog.items,
        )
        message_value = _asset_detail(asset, overview)
    except (KeyError, TypeError, ValueError) as exc:
        await send_game_reply(_invalid("查看", str(exc)))
        return
    await send_game_reply(message_value)


async def protect_asset(message: str, result: CharacterOverviewResult) -> None:
    await _set_asset_protection(message, result, protected=True)


async def unprotect_asset(message: str, result: CharacterOverviewResult) -> None:
    await _set_asset_protection(message, result, protected=False)


async def _set_asset_protection(
    message: str,
    result: CharacterOverviewResult,
    *,
    protected: bool,
) -> None:
    title = "珍藏" if protected else "取消珍藏"
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_unavailable(title))
        return
    token = str(message or "").strip()
    if not token:
        await send_game_reply(_invalid(title, f"发送: {title} 物品编号"))
        return
    services = current_game_services()
    try:
        asset = resolve_asset_reference(
            overview.inventory,
            token,
            services.content.catalog.items,
        )
        if not isinstance(asset, ItemInstance):
            raise ValueError("只有武器和装备可以加入珍藏")
        definition = services.content.catalog.items.require(asset.definition_id)
        if not (
            definition.tags.has("item.weapon")
            or definition.tags.has("item.equipment")
        ):
            raise ValueError("只有武器和装备可以加入珍藏")
    except (KeyError, TypeError, ValueError) as exc:
        await send_game_reply(_invalid(title, str(exc)))
        return

    transaction_id = f"inventory-protection:{_evidence_id()}:{int(protected)}"
    try:
        outcome = await asyncio.to_thread(
            services.inventory_protection.set_protected,
            overview.character.id,
            asset.id,
            protected,
            context=game_operation_context(transaction_id, logical_time=command_time()),
        )
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(C.fail("珍藏状态更新失败"), C.kv("character", overview.character.id))
        )
        await send_game_reply(_invalid(title, "珍藏状态没有更新，请稍后重试"))
        return
    if outcome.failure:
        await send_game_reply(_invalid(title, outcome.failure.message))
        return
    assert outcome.value is not None
    state_text = "已加入珍藏" if protected else "已取消珍藏"
    if not outcome.value.changed:
        state_text = "已经处于珍藏状态" if protected else "当前没有珍藏"
    await send_game_reply(
        M.document()
        .section(title, icon="item")
        .field("物品", _asset_name(asset, overview))
        .field("状态", state_text)
        .build()
    )


def _armory_home(overview: CharacterOverview) -> DocumentMessage:
    counts = Counter()
    catalog = current_game_services().content.catalog.items
    for instance in overview.inventory.instances.values():
        definition = catalog.require(instance.definition_id)
        component = definition.components.get(LOADOUT_ITEM_COMPONENT_ID)
        if not isinstance(component, LoadoutItemComponent) or len(component.allowed_slot_ids) != 1:
            continue
        counts[next(iter(component.allowed_slot_ids))] += 1
    builder = M.document().section("武库", icon="equipment")
    projector = _view(overview).projector
    for slot_id in STANDARD_LOADOUT_SLOT_ORDER:
        name = projector.name(slot_id)
        builder.line(
            M.command(name, f"武库 {slot_id}"),
            FieldSeparator(),
            f"{counts[slot_id]} 件",
        )
    return builder.field("合计", sum(counts.values())).build()


def _asset_page(
    title: str,
    icon: str,
    assets,
    page: int,
    overview: CharacterOverview,
    *,
    page_command: str | None = None,
) -> DocumentMessage:
    window = paginate(assets, page, page_size=PAGE_SIZE)
    builder = M.document().section(title, icon=icon)
    if not window.values:
        builder.line("当前没有物品")
    for asset in window.values:
        reference = _reference(overview.inventory, asset)
        builder.line(
            M.command(reference, f"查看 {reference}"),
            " ",
            _asset_name(asset, overview),
            FieldSeparator(),
            _compact_meta(asset, overview),
            " ",
            _protection_control(asset, overview),
        )
    command = page_command or title
    back = (
        Action("page.armory", "返回武库", "武库", style="secondary")
        if command.startswith("武库 ")
        else None
    )
    builder.row(("页码", window.label), ("总计", window.total))
    actions = pagination_actions(command, window, back=back)
    if actions:
        builder.actions(actions)
    return builder.build()


def _backpack_page(assets, page: int, overview: CharacterOverview) -> DocumentMessage:
    window = paginate(assets, page, page_size=PAGE_SIZE)
    inventory = overview.inventory
    container = _container(inventory, "container.backpack")
    used = _used_space(inventory, container.id)
    builder = (
        M.document()
        .section("背包", icon="inventory")
        .field("空间", f"{used}/{container.maximum_space}" if container.maximum_space else used)
    )
    if not window.values:
        builder.line("当前没有物品")
    total_value = 0
    for asset in window.values:
        reference = _reference(inventory, asset)
        definition = current_game_services().content.catalog.items.require(asset.definition_id)
        quantity = asset.quantity if isinstance(asset, ItemStack) else 1
        value = ""
        recycle = definition.components.get(ITEM_RECYCLE_COMPONENT_ID)
        if isinstance(recycle, CurrencyRecycleYield):
            subtotal = recycle.unit_amount * quantity
            total_value += subtotal
            value = f"估价 {subtotal}"
        elif isinstance(recycle, StackItemRecycleYield):
            value = (
                f"回收 {recycle.unit_quantity * quantity} "
                f"{_view(overview).projector.name(recycle.definition_id)}"
            )
        builder.line(
            M.command(reference, f"查看 {reference}"),
            " ",
            _asset_name(asset, overview),
            f" x{quantity}",
            FieldSeparator() if value else None,
            value or None,
        )
    if total_value:
        builder.field("本页估价", total_value)
    builder.row(("页码", window.label), ("总计", window.total)).actions(
        pagination_actions("背包", window)
    )
    return builder.build()


def _asset_detail(asset, overview: CharacterOverview) -> DocumentMessage:
    from .use import item_use_action

    services = current_game_services()
    view = _view(overview)
    inventory = overview.inventory
    definition = services.content.catalog.items.require(asset.definition_id)
    reference = _reference(inventory, asset)
    name = _asset_name(asset, overview)
    builder = M.document().section(name, icon="item").field("编号", reference)
    actions = []
    if isinstance(asset, ItemStack):
        builder.field("数量", asset.quantity)
        available = inventory.available_quantity(asset.id)
        if available != asset.quantity:
            builder.field("可用", available)
        entry = view.projector.entry(definition.id)
        if entry.description:
            builder.line(entry.description)
        recycle = definition.components.get(ITEM_RECYCLE_COMPONENT_ID)
        if isinstance(recycle, CurrencyRecycleYield):
            builder.row(
                ("回收单价", recycle.unit_amount),
                ("回收总价", recycle.unit_amount * asset.quantity),
            )
        elif isinstance(recycle, StackItemRecycleYield):
            builder.row(
                (
                    "回收单件",
                    f"{recycle.unit_quantity} {view.projector.name(recycle.definition_id)}",
                ),
                (
                    "回收合计",
                    f"{recycle.unit_quantity * asset.quantity} "
                    f"{view.projector.name(recycle.definition_id)}",
                ),
            )
        medicine = _MEDICINE_RESOURCE.get(definition.id)
        if medicine is not None:
            resource_id, maximum_id, ratio = medicine
            maximum = _resource_maximum(overview, maximum_id)
            builder.row(
                ("恢复", view.projector.name(resource_id)),
                ("单次", _number(maximum * ratio)),
            )
        use_action = item_use_action(definition, reference)
        if use_action is not None:
            actions.append(use_action)
    elif definition.tags.has("item.weapon"):
        state = weapon_state_from_instance(asset)
        display = view.gear_projector.weapon(
            state,
            asset,
            inscription_preference=overview.inscription_preference,
        )
        builder.row(
            ("品阶", display.quality_name),
            ("等级", f"Lv{state.level}/{state.maximum_level}"),
        )
        _append_gear_origin(builder, asset)
        if state.maximum_level != state.natural_maximum_level:
            builder.field("天然上限", state.natural_maximum_level)
        profile = services.content.catalog.weapons.require(state.definition_id).quality_profiles[state.quality_id]
        required = profile.required_for_next_level(state.level)
        builder.field("经验", "已满级" if required is None else f"{state.experience}/{required}")
        if display.score_text:
            builder.line(display.score_text)
        _append_roll(builder, state, overview)
        _append_gear_comparison(
            builder,
            asset,
            display,
            overview,
            STANDARD_LOADOUT_SLOT_ORDER[0],
        )
        abilities = WeaponContributionProvider(services.content.catalog.weapons).contribution(state).contribution.abilities
        if abilities:
            builder.section("能力", icon="skill")
            projector = InscriptionProjector(overview.inscription_preference)
            for ability_id in sorted(abilities):
                base = view.projector.name(ability_id)
                builder.line(projector.weapon_ability_name(base, asset, ability_id))
        _append_gear_status(builder, asset, overview)
        actions.extend(_gear_actions(asset, overview))
    elif definition.tags.has("item.equipment"):
        state = equipment_state_from_instance(asset)
        display = view.gear_projector.equipment(
            state,
            asset,
            inscription_preference=overview.inscription_preference,
        )
        equipment = services.content.catalog.equipment.require(state.definition_id)
        builder.row(
            ("品阶", display.quality_name),
            ("部位", view.projector.name(equipment.slot_id)),
        )
        if state.set_id is not None:
            builder.field("套装", view.projector.name(state.set_id))
        _append_gear_origin(builder, asset)
        if display.score_text:
            builder.line(display.score_text)
        _append_roll(builder, state, overview)
        _append_gear_comparison(
            builder,
            asset,
            display,
            overview,
            equipment.slot_id,
        )
        _append_gear_status(builder, asset, overview)
        actions.extend(_gear_actions(asset, overview))
    else:
        data = asset.data.get(INSCRIPTION_MEDIUM_DATA_KEY)
        if isinstance(data, InscriptionMediumData):
            builder.field("铭刻", data.title).line(data.flavor_text)
            actions.append(Action("item.inscription", "铭刻", "铭刻"))
        else:
            entry = view.projector.entry(definition.id)
            if entry.description:
                builder.line(entry.description)
    availability = inventory.availability(asset.id)
    if availability is not AssetAvailability.AVAILABLE:
        builder.field("状态", _availability_name(availability))
    return builder.actions(actions).build()


def _append_gear_origin(builder, asset: ItemInstance) -> None:
    """将资产凭证投影为玩家可读来源，不暴露内部来源编号。"""

    receipt = asset.receipt
    source = _GEAR_SOURCE_NAMES.get(str(receipt.source_kind), "其他途径")
    local_time = receipt.logical_time.astimezone(ZoneInfo(config.project.timezone))
    builder.row(
        ("来源", source),
        ("获得", local_time.strftime("%Y-%m-%d %H:%M")),
    )


def _append_roll(
    builder,
    state: WeaponState | EquipmentState,
    overview: CharacterOverview,
) -> None:
    if state.roll is None:
        return
    projector = _view(overview).projector
    builder.section("词条", icon="item")
    for rolled in state.roll.properties:
        values = ", ".join(_number(value) for value in rolled.values.values())
        suffix = f" {values}" if values else ""
        builder.line(f"{projector.name(rolled.property_id)} T{rolled.tier}{suffix}")


def _append_gear_status(builder, asset: ItemInstance, overview: CharacterOverview) -> None:
    builder.field("归属", _compact_status(asset, overview))
    builder.field("珍藏", "是" if overview.inventory.is_protected(asset.id) else "否")


def _gear_actions(asset: ItemInstance, overview: CharacterOverview) -> list[Action]:
    reference = _reference(overview.inventory, asset)
    slot_id = next(
        (slot for slot, asset_id in overview.loadout.slots.items() if asset_id == asset.id),
        None,
    )
    if slot_id is not None:
        equip_action = Action("item.unequip", "卸下", f"卸下 {slot_id}")
    else:
        equip_action = Action("item.equip", "装备", f"装备 {reference}")
    protected = overview.inventory.is_protected(asset.id)
    actions = [
        equip_action,
        Action("item.inscribe", "铭刻", "铭刻"),
        Action(
            "item.unprotect" if protected else "item.protect",
            "取消珍藏" if protected else "珍藏",
            f"取消珍藏 {reference}" if protected else f"珍藏 {reference}",
            behavior="callback",
            style="secondary",
        ),
    ]
    assigned = any(
        asset.id in preset.slots.values()
        for preset in overview.loadout.presets.values()
    )
    if (
        not assigned
        and not protected
        and overview.inventory.availability(asset.id) is AssetAvailability.AVAILABLE
    ):
        actions.append(
            Action(
                "item.recycle",
                "回收",
                f"回收 {reference}",
                behavior="callback",
                style="secondary",
            )
        )
    return actions


def _append_gear_comparison(
    builder,
    candidate: ItemInstance,
    candidate_display,
    overview: CharacterOverview,
    slot_id: str,
) -> None:
    """展示同槽当前装备的客观差异，不替玩家判断构筑强弱。"""

    current_id = overview.loadout.slots.get(slot_id)
    if current_id is None or current_id == candidate.id:
        return
    current = overview.inventory.instances.get(current_id)
    if current is None:
        return
    catalog = current_game_services().content.catalog.items
    candidate_definition = catalog.require(candidate.definition_id)
    current_definition = catalog.require(current.definition_id)
    candidate_is_weapon = candidate_definition.tags.has("item.weapon")
    if candidate_is_weapon != current_definition.tags.has("item.weapon"):
        return
    candidate_state = (
        weapon_state_from_instance(candidate)
        if candidate_is_weapon
        else equipment_state_from_instance(candidate)
    )
    current_state = (
        weapon_state_from_instance(current)
        if candidate_is_weapon
        else equipment_state_from_instance(current)
    )
    view = _view(overview)
    current_display = (
        view.gear_projector.weapon(
            current_state,
            current,
            inscription_preference=overview.inscription_preference,
        )
        if candidate_is_weapon
        else view.gear_projector.equipment(
            current_state,
            current,
            inscription_preference=overview.inscription_preference,
        )
    )
    current_reference = _reference(overview.inventory, current)
    builder.section("同槽对比", icon="equipment")
    builder.line(
        "当前",
        FieldSeparator(),
        M.command(current_display.name, f"查看 {current_reference}"),
    )
    builder.row(
        ("候选评分", _score_text(candidate_display.score)),
        ("当前评分", _score_text(current_display.score)),
    )
    if candidate_display.score is not None and current_display.score is not None:
        builder.field(
            "评分差",
            _number(candidate_display.score - current_display.score, signed=True),
        )
    if candidate_is_weapon:
        builder.row(
            (
                "候选等级",
                f"Lv{candidate_state.level}/{candidate_state.maximum_level}",
            ),
            (
                "当前等级",
                f"Lv{current_state.level}/{current_state.maximum_level}",
            ),
        )
    else:
        builder.row(
            ("候选套装", _set_name(candidate_state.set_id, view)),
            ("当前套装", _set_name(current_state.set_id, view)),
        )
        _append_set_progress(builder, candidate_state, current_state, overview)


def _append_set_progress(
    builder,
    candidate_state: EquipmentState,
    current_state: EquipmentState,
    overview: CharacterOverview,
) -> None:
    """展示候选替换当前槽位后，受影响套装的件数变化。"""

    if candidate_state.set_id == current_state.set_id:
        affected_ids = {candidate_state.set_id} if candidate_state.set_id is not None else set()
    else:
        affected_ids = {
            value
            for value in (candidate_state.set_id, current_state.set_id)
            if value is not None
        }
    if not affected_ids:
        return

    catalog = current_game_services().content.catalog
    before: Counter[str] = Counter()
    for asset_id in overview.loadout.slots.values():
        asset = overview.inventory.instances.get(asset_id)
        if asset is None:
            continue
        definition = catalog.items.require(asset.definition_id)
        if not definition.tags.has("item.equipment"):
            continue
        state = equipment_state_from_instance(asset)
        if state.set_id is not None:
            before[state.set_id] += 1
    after = before.copy()
    if current_state.set_id is not None:
        after[current_state.set_id] -= 1
    if candidate_state.set_id is not None:
        after[candidate_state.set_id] += 1

    rows = []
    for set_id in sorted(affected_ids):
        definition = catalog.equipment.sets.require(set_id)
        before_count = before.get(set_id, 0)
        after_count = after.get(set_id, 0)
        if before_count == after_count:
            continue
        maximum = definition.bonuses[-1].required_pieces
        rows.append(
            f"{_set_name(set_id, _view(overview))}："
            f"{before_count}/{maximum} -> {after_count}/{maximum}"
        )
    if rows:
        builder.section("套装进度", icon="equipment")
        for row in rows:
            builder.line(row)


def _set_name(set_id: str | None, view) -> str:
    return view.projector.name(set_id) if set_id is not None else "无套装"


def _score_text(value: float | None) -> str:
    return "暂无" if value is None else _number(value)


def _armory_assets(overview: CharacterOverview, slot_id: str):
    catalog = current_game_services().content.catalog.items
    values = []
    for instance in overview.inventory.instances.values():
        definition = catalog.require(instance.definition_id)
        component = definition.components.get(LOADOUT_ITEM_COMPONENT_ID)
        if isinstance(component, LoadoutItemComponent) and component.allowed_slot_ids == frozenset({slot_id}):
            values.append(instance)
    return _sorted_assets(overview.inventory, values)


def _container_assets(inventory: InventoryState, kind: str):
    container = _container(inventory, kind)
    values = [
        asset
        for asset in (*inventory.stacks.values(), *inventory.instances.values())
        if asset.container_id == container.id
    ]
    return _sorted_assets(inventory, values)


def _sorted_assets(inventory: InventoryState, values):
    return sorted(values, key=lambda value: inventory.reference_number(value.id), reverse=True)


def _page_number(value: object) -> int:
    return parse_page_number(value)


def _asset_name(asset, overview: CharacterOverview) -> str:
    services = current_game_services()
    view = _view(overview)
    definition = services.content.catalog.items.require(asset.definition_id)
    if isinstance(asset, ItemInstance) and definition.tags.has("item.weapon"):
        return view.gear_projector.weapon(
            weapon_state_from_instance(asset),
            asset,
            inscription_preference=overview.inscription_preference,
        ).name
    if isinstance(asset, ItemInstance) and definition.tags.has("item.equipment"):
        return view.gear_projector.equipment(
            equipment_state_from_instance(asset),
            asset,
            inscription_preference=overview.inscription_preference,
        ).name
    data = getattr(asset, "data", {}).get(INSCRIPTION_MEDIUM_DATA_KEY)
    if isinstance(data, InscriptionMediumData):
        return data.title
    return view.projector.name(definition.id)


def _view(overview: CharacterOverview):
    return current_game_services().world_view(overview.character_world)


def _compact_status(asset, overview: CharacterOverview) -> str:
    quantity = f"x{asset.quantity}" if isinstance(asset, ItemStack) else ""
    if isinstance(asset, ItemInstance):
        active = next(
            (slot for slot, asset_id in overview.loadout.slots.items() if asset_id == asset.id),
            None,
        )
        if active is not None:
            return "当前"
        for index, preset in enumerate(overview.loadout.presets.values()):
            if asset.id in preset.slots.values():
                return f"配装{index}"
    availability = overview.inventory.availability(asset.id)
    return _availability_name(availability) if availability is not AssetAvailability.AVAILABLE else quantity or "空闲"


def _compact_meta(asset, overview: CharacterOverview) -> str:
    definition = current_game_services().content.catalog.items.require(asset.definition_id)
    status = _compact_status(asset, overview)
    if isinstance(asset, ItemInstance) and definition.tags.has("item.weapon"):
        state = weapon_state_from_instance(asset)
        suffix = " | 珍藏" if overview.inventory.is_protected(asset.id) else ""
        return f"Lv{state.level}/{state.maximum_level} | {status}{suffix}"
    if isinstance(asset, ItemInstance) and overview.inventory.is_protected(asset.id):
        return f"{status} | 珍藏"
    return status


def _protection_control(asset, overview: CharacterOverview):
    if not isinstance(asset, ItemInstance):
        return None
    definition = current_game_services().content.catalog.items.require(asset.definition_id)
    if not (definition.tags.has("item.weapon") or definition.tags.has("item.equipment")):
        return None
    reference = _reference(overview.inventory, asset)
    protected = overview.inventory.is_protected(asset.id)
    return M.command(
        "取消珍藏" if protected else "加入珍藏",
        f"取消珍藏 {reference}" if protected else f"珍藏 {reference}",
    )


def _availability_name(value: AssetAvailability) -> str:
    return {
        AssetAvailability.AVAILABLE: "可用",
        AssetAvailability.RESERVED: "预约中",
        AssetAvailability.LOCKED: "锁定中",
        AssetAvailability.ESCROWED: "托管中",
    }[value]


def _reference(inventory: InventoryState, asset) -> str:
    return asset_reference(
        inventory,
        asset,
        current_game_services().content.catalog.items,
    )


def _resource_maximum(overview: CharacterOverview, maximum_id: str) -> float:
    services = current_game_services()
    contributions = equipped_character_contributions(
        services.content.catalog,
        overview.inventory,
        overview.loadout,
    )
    entity = services.character_projector.project(
        overview.character,
        contributions=contributions,
    ).entity
    return float(entity.snapshot(services.character_projector.attributes).value(maximum_id))


def _used_space(inventory: InventoryState, container_id: str) -> int:
    catalog = current_game_services().content.catalog.items
    used = 0
    for asset in (*inventory.stacks.values(), *inventory.instances.values()):
        if asset.container_id != container_id:
            continue
        definition = catalog.require(asset.definition_id)
        storage = definition.component(ITEM_STORAGE_COMPONENT_ID, ItemStorageComponent)
        used += storage.unit_space * (asset.quantity if isinstance(asset, ItemStack) else 1)
    return used


def _container(inventory: InventoryState, kind: str):
    try:
        return next(value for value in inventory.containers.values() if value.kind == kind)
    except StopIteration as exc:
        raise ValueError(f"库存缺少容器: {kind}") from exc


async def _load_overview(character) -> CharacterOverview | None:
    try:
        result = await asyncio.to_thread(
            current_game_services().load_character_overview,
            character,
        )
        return result.overview if result.status == "ok" else None
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(C.fail("物品状态读取失败"), C.kv("character", character.id))
        )
        return None


def _overview(result: CharacterOverviewResult) -> CharacterOverview | None:
    return result.overview if result.status == "ok" else None


def _evidence_id() -> str:
    context = current_message_context()
    if context is None:
        raise RuntimeError("物品命令缺少消息上下文")
    return context.identity.evidence_id


def _number(value: float, *, signed: bool = False) -> str:
    if abs(value) < 0.005:
        return "0"
    text = f"{value:+.2f}" if signed else f"{value:.2f}"
    return text.rstrip("0").rstrip(".")


def _invalid(title: str, message: str) -> DocumentMessage:
    return M.document().section(title, icon="notice").line(message).build()


def _unavailable(title: str) -> DocumentMessage:
    return M.document().section(title, icon="notice").line(
        "当前没有读取到角色或物品状态，请稍后重试"
    ).build()


__all__ = [
    "PAGE_SIZE",
    "armory",
    "backpack",
    "inspect",
    "nacre",
    "protect_asset",
    "unprotect_asset",
]
