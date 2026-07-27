"""物品使用命令、显式路由与所属业务工作流。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Awaitable, Callable, Mapping

from game.app import CharacterOverview, CurrentCharacterResult, current_game_services
from game.content.catalog.item import (
    COMPANION_SANCTUARY_ITEM_COMPONENT_ID,
    DIMENSION_SHIFT_ITEM_COMPONENT_ID,
    EQUIPMENT_SET_BLUEPRINT_COMPONENT_ID,
)
from game.core.gameplay import (
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    ITEM_ABILITY_COMPONENT_ID,
    ITEM_CONTAINER_CAPACITY_COMPONENT_ID,
    SPIRIT_CURRENT,
    SPIRIT_MAXIMUM,
    AbilityUse,
    CharacterItemUse,
    CharacterItemUseCommand,
    CHARACTER_EXPERIENCE_ITEM_COMPONENT_ID,
    COMPANION_EXPERIENCE_ITEM_COMPONENT_ID,
    ItemAbilityComponent,
    ItemDefinition,
    ItemInstance,
    ItemStack,
    StableId,
    WeaponItemUseCommand,
    WEAPON_EXPERIENCE_ITEM_COMPONENT_ID,
    WEAPON_MAXIMUM_LEVEL_ITEM_COMPONENT_ID,
    equipment_state_from_instance,
    stable_id,
)
from game.features.special_items import (
    BACKPACK_CAPACITY_EFFECT_KIND,
    SpecialItemUseCommand,
)
from game.rules import game_operation_context
from game.rules.character import equipped_character_contributions
from game.rules.item import resolve_asset_reference
from launch import C, logger
from message import Action, DocumentMessage, M
from message.schema import FieldSeparator

from ..command_helpers import command_time
from ..reply import send_game_reply
from .service import (
    _MEDICINE_RESOURCE,
    _armory_action,
    _asset_name,
    _backpack_action,
    _evidence_id,
    _inspect_action,
    _invalid,
    _load_overview,
    _nacre_action,
    _number,
    _reference,
    _resource_maximum,
    _unavailable,
    _view,
)


class ItemUseArgumentPolicy(str, Enum):
    """`使用` 命令第二参数的稳定语义。"""

    QUANTITY = "quantity"
    NONE = "none"
    OPTIONAL_WEAPON = "optional_weapon"
    OPTIONAL_COMPANION = "optional_companion"
    DELEGATED_COMMAND = "delegated_command"


@dataclass(frozen=True)
class ItemUseRequest:
    parts: tuple[str, ...]
    current: CurrentCharacterResult
    overview: CharacterOverview
    asset: ItemStack | ItemInstance
    definition: ItemDefinition
    available_quantity: int


ItemUseHandler = Callable[[ItemUseRequest], Awaitable[None]]


@dataclass(frozen=True)
class ItemUseRoute:
    """一个类型化使用组件在命令层的完整交互路由。"""

    component_id: StableId
    handler: ItemUseHandler
    argument_policy: ItemUseArgumentPolicy
    argument_error: str = ""
    action_id: str = "item.use"
    action_label: str = "使用"
    action_command: str = "使用 {reference}"
    action_behavior: str = "fill"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "component_id",
            stable_id(self.component_id, field="item use component id"),
        )
        if not callable(self.handler):
            raise TypeError("物品使用路由 handler 必须可调用")
        if self.argument_policy is ItemUseArgumentPolicy.NONE and not self.argument_error:
            raise ValueError(f"无参数物品使用路由必须声明错误文案：{self.component_id}")

    def validate_arguments(
        self,
        parts: tuple[str, ...],
        *,
        item_name: str,
    ) -> None:
        if self.argument_policy is ItemUseArgumentPolicy.NONE and len(parts) != 1:
            raise ValueError(self.argument_error.format(item=item_name))

    def action(self, reference: str) -> Action:
        return Action(
            self.action_id,
            self.action_label,
            self.action_command.format(reference=reference),
            behavior=self.action_behavior,
        )


async def use_item(message: str, current: CurrentCharacterResult) -> None:
    character = current.character if current.status == "ok" else None
    if character is None:
        await send_game_reply(_unavailable("使用", _nacre_action()))
        return
    parts = tuple(str(message or "").strip().split())
    if not parts or len(parts) > 2:
        await send_game_reply(
            _invalid(
                "使用",
                "发送: 使用 物品编号 [数量或武器编号]",
                _use_action(),
            )
        )
        return

    services = current_game_services()
    initial = await _load_overview(character)
    if initial is None:
        await send_game_reply(_unavailable("使用", _nacre_action()))
        return
    try:
        asset = resolve_asset_reference(
            initial.inventory,
            parts[0],
            services.content.catalog.items,
        )
        definition = services.content.catalog.items.require(asset.definition_id)
        if definition.tags.has("item.inscription_medium"):
            raise ValueError("铭刻之羽只能通过铭刻命令使用")
        route = item_use_route(definition)
        if route is None:
            definition.component(ITEM_ABILITY_COMPONENT_ID, ItemAbilityComponent)
            raise AssertionError("能力物品缺少使用路由")
        if route.argument_policy is ItemUseArgumentPolicy.DELEGATED_COMMAND:
            await route.handler(
                ItemUseRequest(parts, current, initial, asset, definition, 0)
            )
            return
        available = initial.inventory.available_quantity(asset.id)
        if available < 1:
            raise ValueError("物品当前不可使用")
        route.validate_arguments(
            parts,
            item_name=_view(initial).projector.name(definition.id),
        )
    except (KeyError, TypeError, ValueError) as exc:
        await send_game_reply(_invalid("使用", str(exc), _use_action()))
        return

    await route.handler(
        ItemUseRequest(parts, current, initial, asset, definition, available)
    )


async def _use_ability(request: ItemUseRequest) -> None:
    character = request.current.character
    assert character is not None
    services = current_game_services()
    try:
        component = request.definition.component(
            ITEM_ABILITY_COMPONENT_ID,
            ItemAbilityComponent,
        )
        requested_quantity = int(request.parts[1]) if len(request.parts) == 2 else 1
        if requested_quantity < 1:
            raise ValueError("使用数量必须大于 0")
    except (KeyError, TypeError, ValueError) as exc:
        await send_game_reply(
            _invalid("使用", str(exc), _use_action(request.parts[0]))
        )
        return

    limit = min(requested_quantity, request.available_quantity)
    initial_resources = dict(request.overview.character.resources)
    consumed = 0
    executed = 0
    stopped_full = False
    failure_message = ""
    for index in range(limit):
        overview = await _load_overview(character)
        if overview is None:
            failure_message = "物品状态读取失败"
            break
        try:
            current_asset = resolve_asset_reference(
                overview.inventory,
                request.parts[0],
                services.content.catalog.items,
            )
        except ValueError:
            break
        medicine = _MEDICINE_RESOURCE.get(current_asset.definition_id)
        if medicine is not None:
            resource_id, maximum_id, _ = medicine
            maximum = _resource_maximum(overview, maximum_id)
            if overview.character.resources[resource_id] >= maximum:
                stopped_full = True
                break
        transaction_id = f"item-use:{_evidence_id()}:{index}"
        command = CharacterItemUse(
            transaction_id,
            character.id,
            character.id,
            current_asset.id,
            AbilityUse(f"{transaction_id}:ability", component.ability_id),
        )
        contributions = equipped_character_contributions(
            services.content.catalog,
            overview.inventory,
            overview.loadout,
        )
        try:
            outcome = await asyncio.to_thread(
                services.item_use.use,
                command,
                inventory_id=character.id,
                contributions={character.id: contributions},
                context=game_operation_context(
                    transaction_id,
                    logical_time=command_time(),
                ),
            )
        except Exception as exc:
            logger.opt(colors=True, exception=exc).error(
                C.join(C.fail("物品使用失败"), C.kv("character", character.id))
            )
            failure_message = "物品使用没有完成"
            break
        if outcome.failure:
            failure_message = outcome.failure.message
            break
        assert outcome.value is not None
        executed += 1
        consumed += outcome.value.consumed_quantity

    final = await _load_overview(character)
    if executed < 1 or final is None:
        message_text = (
            "资源已经恢复至上限"
            if stopped_full
            else failure_message or "没有使用任何物品"
        )
        await send_game_reply(
            _invalid("使用", message_text, _use_action(request.parts[0]))
        )
        return
    await send_game_reply(
        _use_result(
            request.definition.id,
            executed,
            consumed,
            initial_resources,
            final,
            requested_quantity > limit,
            stopped_full,
            failure_message,
        )
    )


async def _use_equipment_blueprint(request: ItemUseRequest) -> None:
    services = current_game_services()
    overview = request.overview
    transaction_id = f"equipment-blueprint:{_evidence_id()}"
    try:
        result = await asyncio.to_thread(
            services.equipment_blueprints.use,
            overview.character.id,
            request.asset.id,
            transaction_id,
            logical_time=command_time(),
        )
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(C.fail("套装图纸使用失败"), C.kv("character", overview.character.id))
        )
        await send_game_reply(
            _invalid(
                "套装图纸",
                "装备没有生成，请稍后重试",
                _use_action(request.parts[0]),
            )
        )
        return
    if result.receipt is None:
        await send_game_reply(
            _invalid(
                "套装图纸",
                result.failure_message or "装备没有生成",
                _use_action(request.parts[0]),
            )
        )
        return
    final = await _load_overview(overview.character)
    if final is None:
        await send_game_reply(
            _invalid("套装图纸", "装备已经生成，请稍后查看武库", _armory_action())
        )
        return
    asset = final.inventory.instances.get(result.receipt.equipment_asset_id)
    if asset is None:
        await send_game_reply(
            _invalid("套装图纸", "装备已经生成，请稍后查看武库", _armory_action())
        )
        return
    view = _view(final)
    state = equipment_state_from_instance(asset)
    display = view.gear_projector.equipment(
        state,
        asset,
        inscription_preference=final.inscription_preference,
    )
    reference = _reference(final.inventory, asset)
    set_name = view.projector.name(result.receipt.set_id)
    await send_game_reply(
        M.document()
        .section("套装图纸", icon="reward")
        .field("套装", M.command(set_name, f"特效 {set_name}"))
        .field("获得", M.command(display.name, f"查看 {reference}"))
        .row(("品阶", view.projector.name(state.quality_id)), ("编号", reference))
        .note("部位、底座、品阶、词条与词条数值均由本次生成独立决定。")
        .build()
    )


async def _use_weapon_growth(request: ItemUseRequest) -> None:
    services = current_game_services()
    overview = request.overview
    try:
        if len(request.parts) == 2:
            target = resolve_asset_reference(
                overview.inventory,
                request.parts[1],
                services.content.catalog.items,
            )
            if not isinstance(target, ItemInstance):
                raise ValueError("目标编号不是武器")
        else:
            asset_id = overview.loadout.weapon_asset_id
            if asset_id is None:
                raise ValueError("当前没有装备武器，请补充武器编号")
            target = overview.inventory.instances[asset_id]
        target_definition = services.content.catalog.items.require(target.definition_id)
        if not target_definition.tags.has("item.weapon"):
            raise ValueError("目标编号不是武器")
    except (KeyError, TypeError, ValueError) as exc:
        await send_game_reply(
            _invalid("使用", str(exc), _use_target_action(request.parts[0]))
        )
        return

    transaction_id = f"weapon-item-use:{_evidence_id()}"
    try:
        outcome = await asyncio.to_thread(
            services.weapon_item_use.use,
            WeaponItemUseCommand(
                transaction_id,
                overview.character.id,
                request.asset.id,
                target.id,
            ),
            inventory_id=overview.character.id,
            context=game_operation_context(transaction_id, logical_time=command_time()),
        )
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(C.fail("武器成长道具使用失败"), C.kv("character", overview.character.id))
        )
        await send_game_reply(
            _invalid("使用", "物品使用没有完成", _use_action(request.parts[0]))
        )
        return
    if outcome.failure:
        await send_game_reply(
            _invalid("使用", outcome.failure.message, _use_action(request.parts[0]))
        )
        return
    assert outcome.value is not None
    receipt = outcome.value
    view = _view(overview)
    builder = (
        M.document()
        .section("使用完成", icon="item")
        .field("物品", view.projector.name(receipt.item_definition_id))
        .field("武器", _asset_name(target, overview))
    )
    if receipt.maximum_level_after != receipt.maximum_level_before:
        builder.field(
            "等级上限",
            f"{receipt.maximum_level_before} -> {receipt.maximum_level_after}",
        )
    if receipt.level_after != receipt.level_before:
        builder.field("等级", f"Lv{receipt.level_before} -> Lv{receipt.level_after}")
    if receipt.experience_granted:
        builder.field("武器经验", f"+{receipt.experience_granted}")
        builder.field(
            "当前经验",
            f"{receipt.experience_before} -> {receipt.experience_after}",
        )
    await send_game_reply(
        builder.action(
            _inspect_action(_reference(overview.inventory, target))
        ).build()
    )


async def _use_character_experience(request: ItemUseRequest) -> None:
    services = current_game_services()
    overview = request.overview
    transaction_id = f"character-item-use:{_evidence_id()}"
    try:
        outcome = await asyncio.to_thread(
            services.character_item_use.use,
            CharacterItemUseCommand(
                transaction_id,
                overview.character.id,
                request.asset.id,
            ),
            inventory_id=overview.character.id,
            context=game_operation_context(transaction_id, logical_time=command_time()),
        )
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(C.fail("人物经验物品使用失败"), C.kv("character", overview.character.id))
        )
        await send_game_reply(
            _invalid("使用", "物品使用没有完成", _use_action(request.parts[0]))
        )
        return
    if outcome.failure:
        await send_game_reply(
            _invalid("使用", outcome.failure.message, _use_action(request.parts[0]))
        )
        return
    receipt = outcome.unwrap()
    await send_game_reply(
        M.document()
        .section("使用完成", icon="item")
        .field("物品", _view(overview).projector.name(receipt.item_definition_id))
        .field("人物经验", f"+{receipt.experience_granted}")
        .field("等级", f"Lv{receipt.level_before} -> Lv{receipt.level_after}")
        .field("当前经验", f"{receipt.experience_before} -> {receipt.experience_after}")
        .action(Action("item.character", "查看角色", "我的角色"))
        .build()
    )


async def _use_companion_experience(request: ItemUseRequest) -> None:
    services = current_game_services()
    overview = request.overview
    reference = request.parts[1].upper() if len(request.parts) == 2 else None
    if reference is not None and (
        not reference.startswith("C") or not reference[1:].isdigit()
    ):
        await send_game_reply(
            _invalid(
                "使用",
                "伙伴编号必须使用 C数字",
                _use_target_action(request.parts[0]),
            )
        )
        return
    transaction_id = f"companion-item-use:{_evidence_id()}"
    try:
        result = await asyncio.to_thread(
            services.companions.use_experience_item,
            transaction_id,
            overview.character.id,
            request.asset.id,
            reference,
            logical_time=command_time(),
        )
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(C.fail("伙伴经验物品使用失败"), C.kv("character", overview.character.id))
        )
        await send_game_reply(
            _invalid("使用", "物品使用没有完成", _use_action(request.parts[0]))
        )
        return
    if result.status != "used" or result.receipt is None or result.companion is None:
        await send_game_reply(
            _invalid(
                "使用",
                result.failure_message or "伙伴经验物品没有生效",
                _use_target_action(request.parts[0]),
            )
        )
        return
    receipt = result.receipt
    definition = services.content.companions.require_definition(
        result.companion.definition_id
    )
    await send_game_reply(
        M.document()
        .section("使用完成", icon="item")
        .field("物品", _view(overview).projector.name(receipt.item_definition_id))
        .field("伙伴", f"{result.companion.reference} {definition.name}")
        .field("伙伴经验", f"+{receipt.experience_granted}")
        .field("等级", f"Lv{receipt.level_before} -> Lv{receipt.level_after}")
        .field("当前经验", f"{receipt.experience_before} -> {receipt.experience_after}")
        .action(
            Action(
                "item.companion",
                "查看伙伴",
                f"伙伴 {result.companion.reference}",
            )
        )
        .build()
    )


async def _use_specialized(request: ItemUseRequest) -> None:
    services = current_game_services()
    overview = request.overview
    transaction_id = f"special-item-use:{_evidence_id()}"
    try:
        outcome = await asyncio.to_thread(
            services.special_item_use.use,
            SpecialItemUseCommand(
                transaction_id,
                overview.character.id,
                request.asset.id,
            ),
            inventory_id=overview.character.id,
            context=game_operation_context(transaction_id, logical_time=command_time()),
        )
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(C.fail("特殊物品使用失败"), C.kv("character", overview.character.id))
        )
        await send_game_reply(
            _invalid("使用", "物品使用没有完成", _use_action(request.parts[0]))
        )
        return
    if outcome.failure:
        await send_game_reply(
            _invalid("使用", outcome.failure.message, _use_action(request.parts[0]))
        )
        return
    assert outcome.value is not None
    receipt = outcome.value
    builder = (
        M.document()
        .section("使用完成", icon="item")
        .field("物品", _view(overview).projector.name(receipt.item_definition_id))
    )
    if receipt.effect_kind == BACKPACK_CAPACITY_EFFECT_KIND:
        builder.field("背包空间", f"{receipt.value_before} -> {receipt.value_after}")
    await send_game_reply(builder.action(_backpack_action()).build())


async def _use_companion_sanctuary(request: ItemUseRequest) -> None:
    character = request.current.character
    dimension = request.current.character_world
    if character is None or dimension is None:
        await send_game_reply(_unavailable("使用", _nacre_action()))
        return
    item_name = _view(request.overview).projector.name(request.definition.id)
    services = current_game_services()
    operation_id = f"companion-sanctuary-open:{_evidence_id()}"
    try:
        result = await asyncio.to_thread(
            services.companions.open_sanctuary,
            operation_id,
            character,
            dimension,
            request.asset.id,
            logical_time=command_time(),
        )
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(C.fail("宠物秘境开启失败"), C.kv("character", character.id))
        )
        await send_game_reply(
            _invalid(
                "使用",
                f"{item_name}没有成功生效",
                _use_action(request.parts[0]),
            )
        )
        return
    if result.status != "opened" or result.sanctuary is None:
        failure_message = {
            "item_unknown": f"找不到要使用的{item_name}",
            "item_forbidden": f"{item_name}不属于当前角色",
            "item_unavailable": f"{item_name}当前被其他流程占用",
            "item_consume_failed": f"{item_name}扣除失败",
        }.get(result.status, result.failure_message or "当前不能开启宠物秘境")
        await send_game_reply(
            _invalid("使用", failure_message, _use_action(request.parts[0]))
        )
        return
    await send_game_reply(_opened_sanctuary_message(result.sanctuary, dimension))


async def _use_delegated_dimension_shift(request: ItemUseRequest) -> None:
    del request
    await send_game_reply(
        _invalid(
            "使用",
            "跃迁凭证会在成功跃迁时自动消耗，请发送：跃迁",
            Action("item.dimension-shift", "前往跃迁", "跃迁"),
        )
    )


def _opened_sanctuary_message(sanctuary, dimension) -> DocumentMessage:
    services = current_game_services()
    view = services.world_view(dimension)
    title = view.projector.name("term.companion_sanctuary")
    builder = (
        M.document()
        .section(f"{title}已开启", icon="explore")
        .field("有效期", sanctuary.expires_at.strftime("%m-%d %H:%M"))
    )
    actions = []
    for trace in sanctuary.traces:
        species = services.content.companions.species.require(trace.definition_id)
        builder.item(
            trace.index,
            species.name,
            FieldSeparator(),
            _companion_role(species.role),
            FieldSeparator(),
            "危险相当",
        )
        actions.append(
            Action(
                f"companion.trace.{trace.index}",
                f"追踪 {trace.index}",
                f"秘境追踪 {trace.index}",
                behavior="callback",
            )
        )
    return (
        builder.note("选择一条踪迹后，另外两条会立即消失。跃迁不会刷新踪迹。")
        .actions(actions)
        .build()
    )


def _companion_role(role: str) -> str:
    return {
        "assault": "强攻",
        "swift": "迅捷",
        "guardian": "守护",
        "control": "控制",
        "sustain": "续航",
    }[role]


def _use_result(
    definition_id: str,
    executed: int,
    consumed: int,
    before,
    final: CharacterOverview,
    exhausted: bool,
    stopped_full: bool,
    failure: str,
) -> DocumentMessage:
    view = _view(final)
    builder = (
        M.document()
        .section("使用完成", icon="item")
        .field("物品", view.projector.name(definition_id))
        .field("次数", executed)
    )
    if consumed:
        builder.field("消耗", consumed)
    for resource_id in (HEALTH_CURRENT, SPIRIT_CURRENT):
        previous = before[resource_id]
        current = final.character.resources[resource_id]
        if current != previous:
            maximum_id = (
                HEALTH_MAXIMUM if resource_id == HEALTH_CURRENT else SPIRIT_MAXIMUM
            )
            builder.field(
                view.projector.name(resource_id),
                f"{_number(previous)} -> {_number(current)}/"
                f"{_number(_resource_maximum(final, maximum_id))}",
            )
    if stopped_full:
        builder.note("资源达到上限后已停止继续消耗。")
    elif exhausted:
        builder.note("持有数量不足，已使用全部可用物品。")
    elif failure:
        builder.note(f"后续使用已停止: {failure}")
    return builder.action(_nacre_action()).build()


def _use_action(reference: str = "") -> Action:
    if reference:
        return Action("item.use.retry", "再次使用", f"使用 {reference}")
    return Action("item.use.fill", "填写物品", "使用 ", behavior="fill")


def _use_target_action(reference: str) -> Action:
    return Action(
        "item.use.target",
        "填写目标",
        f"使用 {reference} ",
        behavior="fill",
    )


ITEM_USE_ROUTES = (
    ItemUseRoute(
        ITEM_ABILITY_COMPONENT_ID,
        _use_ability,
        ItemUseArgumentPolicy.QUANTITY,
    ),
    ItemUseRoute(
        CHARACTER_EXPERIENCE_ITEM_COMPONENT_ID,
        _use_character_experience,
        ItemUseArgumentPolicy.NONE,
        "人物经验物品不需要指定目标",
    ),
    ItemUseRoute(
        COMPANION_EXPERIENCE_ITEM_COMPONENT_ID,
        _use_companion_experience,
        ItemUseArgumentPolicy.OPTIONAL_COMPANION,
    ),
    ItemUseRoute(
        WEAPON_MAXIMUM_LEVEL_ITEM_COMPONENT_ID,
        _use_weapon_growth,
        ItemUseArgumentPolicy.OPTIONAL_WEAPON,
    ),
    ItemUseRoute(
        WEAPON_EXPERIENCE_ITEM_COMPONENT_ID,
        _use_weapon_growth,
        ItemUseArgumentPolicy.OPTIONAL_WEAPON,
    ),
    ItemUseRoute(
        ITEM_CONTAINER_CAPACITY_COMPONENT_ID,
        _use_specialized,
        ItemUseArgumentPolicy.NONE,
        "该特殊物品每次只能使用一件",
    ),
    ItemUseRoute(
        COMPANION_SANCTUARY_ITEM_COMPONENT_ID,
        _use_companion_sanctuary,
        ItemUseArgumentPolicy.NONE,
        "{item}每次只能使用一枚",
    ),
    ItemUseRoute(
        EQUIPMENT_SET_BLUEPRINT_COMPONENT_ID,
        _use_equipment_blueprint,
        ItemUseArgumentPolicy.NONE,
        "套装图纸每次只能使用一张",
    ),
    ItemUseRoute(
        DIMENSION_SHIFT_ITEM_COMPONENT_ID,
        _use_delegated_dimension_shift,
        ItemUseArgumentPolicy.DELEGATED_COMMAND,
        action_id="dimension.shift",
        action_label="跃迁",
        action_command="跃迁",
        action_behavior="callback",
    ),
)


def _build_route_registry(
    routes: tuple[ItemUseRoute, ...],
) -> Mapping[StableId, ItemUseRoute]:
    values: dict[StableId, ItemUseRoute] = {}
    for route in routes:
        if route.component_id in values:
            raise ValueError(f"物品使用路由重复：{route.component_id}")
        values[route.component_id] = route
    return MappingProxyType(values)


ITEM_USE_ROUTE_REGISTRY = _build_route_registry(ITEM_USE_ROUTES)


def item_use_route(definition: ItemDefinition) -> ItemUseRoute | None:
    matches = tuple(
        ITEM_USE_ROUTE_REGISTRY[component_id]
        for component_id in definition.components
        if component_id in ITEM_USE_ROUTE_REGISTRY
    )
    if len(matches) > 1:
        raise ValueError(f"物品 {definition.id} 声明了多个使用路由")
    return matches[0] if matches else None


def item_use_action(definition: ItemDefinition, reference: str) -> Action | None:
    route = item_use_route(definition)
    return route.action(reference) if route is not None else None


__all__ = [
    "ITEM_USE_ROUTES",
    "ITEM_USE_ROUTE_REGISTRY",
    "ItemUseArgumentPolicy",
    "ItemUseRequest",
    "ItemUseRoute",
    "item_use_action",
    "item_use_route",
    "use_item",
]
