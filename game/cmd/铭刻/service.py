"""铭刻命令解析、预览、确认与协议中立展示。"""

from __future__ import annotations

import asyncio

from game.app import CurrentCharacterResult, current_game_services
from game.content import INSCRIPTION_FEATHER_ITEM_ID
from game.core.gameplay import (
    INSCRIPTION_MEDIUM_DATA_KEY,
    AssetInscriptionTarget,
    InscriptionCommand,
    InscriptionMediumData,
    InscriptionProjector,
    InventoryState,
    ItemInstance,
    WeaponAbilityInscriptionTarget,
    WeaponContributionProvider,
    clean_inscription_name,
    equipment_state_from_instance,
    weapon_state_from_instance,
)
from game.rules import game_operation_context
from game.rules.item import asset_reference, resolve_asset_reference
from launch import C, logger
from launch.adapter import current_message_context
from message import Action, DocumentMessage, M
from message.schema import FieldSeparator

from ..command_helpers import command_time, current_character_value
from ..reply import send_command_failure, send_game_reply
from ..reply_intents import reply_intents


_LIST_LIMIT = 8


async def inscription(message: str, current: CurrentCharacterResult) -> None:
    character = current_character_value(current)
    if character is None:
        await send_game_reply(_unavailable("铭刻"))
        return
    overview = await _load_overview(character)
    if overview is None:
        await send_game_reply(_unavailable("铭刻"))
        return
    requested = str(message or "").strip()
    view = current_game_services().world_view(overview.character_world)
    if not requested:
        await send_game_reply(
            _inscription_home(overview.inventory, overview.inscription_preference, view)
        )
        return
    parts = requested.split(maxsplit=2)
    if len(parts) != 3:
        await send_game_reply(_asset_usage())
        return
    medium_ref, target_ref, custom_name = parts
    try:
        medium = _medium(overview.inventory, medium_ref)
        target = _asset_target(overview.inventory, target_ref)
        custom_name = clean_inscription_name(custom_name)
    except (KeyError, TypeError, ValueError) as exc:
        await send_game_reply(_invalid(str(exc)))
        return
    await send_game_reply(
        _asset_preview(
            overview.inventory,
            medium,
            target,
            custom_name,
            overview.inscription_preference,
            view,
        )
    )


async def inscription_ability(message: str, current: CurrentCharacterResult) -> None:
    character = current_character_value(current)
    if character is None:
        await send_game_reply(_unavailable("铭刻能力"))
        return
    overview = await _load_overview(character)
    if overview is None:
        await send_game_reply(_unavailable("铭刻能力"))
        return
    requested = str(message or "").strip()
    view = current_game_services().world_view(overview.character_world)
    if not requested:
        await send_game_reply(
            _ability_home(overview.inventory, overview.inscription_preference, view)
        )
        return
    parts = requested.split(maxsplit=3)
    if len(parts) != 4:
        await send_game_reply(_ability_usage())
        return
    medium_ref, weapon_ref, ability_token, custom_name = parts
    try:
        medium = _medium(overview.inventory, medium_ref)
        weapon = _weapon(overview.inventory, weapon_ref)
        ability_id, ability_index = _ability(weapon, ability_token)
        custom_name = clean_inscription_name(custom_name)
    except (KeyError, TypeError, ValueError) as exc:
        await send_game_reply(_invalid(str(exc)))
        return
    await send_game_reply(
        _ability_preview(
            overview.inventory,
            medium,
            weapon,
            ability_id,
            ability_index,
            custom_name,
            overview.inscription_preference,
            view,
        )
    )


async def confirm_asset_inscription(
    message: str,
    current: CurrentCharacterResult,
) -> None:
    character = current_character_value(current)
    if character is None:
        await send_game_reply(_unavailable("确认铭刻"))
        return
    parts = str(message or "").strip().split(maxsplit=2)
    if len(parts) != 3:
        await send_game_reply(_invalid("铭刻确认参数不完整"))
        return
    overview = await _load_overview(character)
    if overview is None:
        await send_game_reply(_unavailable("确认铭刻"))
        return
    try:
        medium = _medium(overview.inventory, parts[0])
        target = _asset_target(overview.inventory, parts[1])
        custom_name = clean_inscription_name(parts[2])
        command = InscriptionCommand(
            _transaction_id("inscription:asset"),
            character.id,
            AssetInscriptionTarget(target.id),
            medium.id,
            custom_name,
            overview.inventory.revision,
            target.revision,
        )
        outcome = await asyncio.to_thread(
            current_game_services().inscriptions.apply,
            command,
            inventory_id=character.id,
            context=game_operation_context(command.id, logical_time=command_time()),
        )
    except Exception as exc:
        await _failed("资产铭刻执行失败", character.id, exc)
        return
    if outcome.failure:
        await send_game_reply(_invalid(outcome.failure.message))
        return
    assert outcome.value is not None
    await send_game_reply(
        _success(outcome.value, current_game_services().world_view(overview.character_world))
    )


async def confirm_ability_inscription(
    message: str,
    current: CurrentCharacterResult,
) -> None:
    character = current_character_value(current)
    if character is None:
        await send_game_reply(_unavailable("确认铭刻"))
        return
    parts = str(message or "").strip().split(maxsplit=3)
    if len(parts) != 4:
        await send_game_reply(_invalid("铭刻确认参数不完整"))
        return
    overview = await _load_overview(character)
    if overview is None:
        await send_game_reply(_unavailable("确认铭刻"))
        return
    try:
        medium = _medium(overview.inventory, parts[0])
        weapon = _weapon(overview.inventory, parts[1])
        ability_id, _ = _ability(weapon, parts[2])
        custom_name = clean_inscription_name(parts[3])
        command = InscriptionCommand(
            _transaction_id("inscription:ability"),
            character.id,
            WeaponAbilityInscriptionTarget(weapon.id, ability_id),
            medium.id,
            custom_name,
            overview.inventory.revision,
            weapon.revision,
        )
        outcome = await asyncio.to_thread(
            current_game_services().inscriptions.apply,
            command,
            inventory_id=character.id,
            context=game_operation_context(command.id, logical_time=command_time()),
        )
    except Exception as exc:
        await _failed("能力铭刻执行失败", character.id, exc)
        return
    if outcome.failure:
        await send_game_reply(_invalid(outcome.failure.message))
        return
    assert outcome.value is not None
    await send_game_reply(
        _success(outcome.value, current_game_services().world_view(overview.character_world))
    )


async def inscription_original_name(
    message: str,
    current: CurrentCharacterResult,
) -> None:
    character = current_character_value(current)
    if character is None:
        await send_game_reply(_unavailable("铭刻原名"))
        return
    services = current_game_services()
    try:
        preference = await asyncio.to_thread(
            services.load_inscription_preference,
            character.id,
            logical_time=command_time(),
        )
        requested = _parse_switch(message)
        if requested is None and str(message or "").strip():
            await send_game_reply(_preference_message(preference, invalid=True))
            return
        if requested is not None:
            preference = await asyncio.to_thread(
                services.set_inscription_show_original_name,
                character.id,
                requested,
                logical_time=command_time(),
            )
    except Exception as exc:
        await _failed("铭刻原名设置失败", character.id, exc)
        return
    await send_game_reply(_preference_message(preference))


async def _load_overview(character):
    try:
        result = await asyncio.to_thread(
            current_game_services().load_character_overview,
            character,
        )
        return result.overview if result.status == "ok" else None
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(C.fail("铭刻状态读取失败"), C.kv("character", character.id))
        )
        return None


def _inscription_home(inventory: InventoryState, preference, view) -> DocumentMessage:
    mediums = [
        value
        for value in inventory.instances.values()
        if _definition(value).tags.has("item.inscription_medium")
    ]
    targets = [
        value
        for value in inventory.instances.values()
        if _definition(value).tags.has("item.weapon")
        or _definition(value).tags.has("item.equipment")
    ]
    builder = (
        M.document()
        .section("铭刻", icon="item")
        .field("世界", view.skin.name)
    )
    medium_name = view.projector.name(INSCRIPTION_FEATHER_ITEM_ID)
    if not mediums:
        builder.line(f"暂无{medium_name}")
    else:
        builder.field(medium_name, len(mediums))
        for medium in _sorted(inventory, mediums)[:_LIST_LIMIT]:
            data = medium.data.get(INSCRIPTION_MEDIUM_DATA_KEY)
            title = data.title if isinstance(data, InscriptionMediumData) else "数据异常"
            builder.line(f"{_reference(inventory, medium)} {title}")
    if targets:
        builder.field("可铭刻目标", len(targets))
        for target in _sorted(inventory, targets)[:_LIST_LIMIT]:
            builder.line(
                _reference(inventory, target),
                FieldSeparator(),
                _asset_name(target, preference, view),
            )
    return builder.note("发送: 铭刻 羽毛编号 目标编号 新名称").build()


def _asset_preview(
    inventory: InventoryState,
    medium: ItemInstance,
    target: ItemInstance,
    custom_name: str,
    preference,
    view,
) -> DocumentMessage:
    data = _medium_data(medium)
    medium_name = view.projector.name(INSCRIPTION_FEATHER_ITEM_ID)
    intent = reply_intents.definition("inscription.confirm_asset")
    assert intent is not None
    command = intent.command(
        {
            "medium": _reference(inventory, medium),
            "target": _reference(inventory, target),
            "name": custom_name,
        }
    )
    return (
        M.document()
        .section("铭刻预览", icon="item")
        .field("世界", view.skin.name)
        .field(medium_name, data.title)
        .field("原名", _asset_name(target, preference, view))
        .field("铭刻名", custom_name)
        .note(f"铭刻成功后将永久消耗这枚{medium_name}。")
        .actions((Action("inscription.confirm_asset", "确认铭刻", command),))
        .build()
    )


def _ability_preview(
    inventory: InventoryState,
    medium: ItemInstance,
    weapon: ItemInstance,
    ability_id: str,
    ability_index: int,
    custom_name: str,
    preference,
    view,
) -> DocumentMessage:
    data = _medium_data(medium)
    medium_name = view.projector.name(INSCRIPTION_FEATHER_ITEM_ID)
    intent = reply_intents.definition("inscription.confirm_ability")
    assert intent is not None
    command = intent.command(
        {
            "medium": _reference(inventory, medium),
            "weapon": _reference(inventory, weapon),
            "ability": ability_index,
            "name": custom_name,
        }
    )
    return (
        M.document()
        .section("能力铭刻预览", icon="skill")
        .field("世界", view.skin.name)
        .field(medium_name, data.title)
        .field("武器", _asset_name(weapon, preference, view))
        .field("原能力名", _ability_name(weapon, ability_id, preference, view))
        .field("铭刻名", custom_name)
        .note("铭刻只改变展示名称，不改变能力机制与数值。")
        .actions((Action("inscription.confirm_ability", "确认铭刻", command),))
        .build()
    )


def _ability_home(inventory: InventoryState, preference, view) -> DocumentMessage:
    weapons = [
        value
        for value in inventory.instances.values()
        if _definition(value).tags.has("item.weapon")
    ]
    builder = (
        M.document()
        .section("铭刻能力", icon="skill")
        .field("世界", view.skin.name)
    )
    if not weapons:
        return builder.line("当前没有可以铭刻能力的武器").build()
    for weapon in _sorted(inventory, weapons)[:_LIST_LIMIT]:
        builder.line(
            f"{_reference(inventory, weapon)} {_asset_name(weapon, preference, view)}"
        )
        for index, ability_id in enumerate(_weapon_abilities(weapon), start=1):
            builder.line(f"[{index}] {_ability_name(weapon, ability_id, preference, view)}")
    return builder.note("发送: 铭刻能力 羽毛编号 武器编号 能力序号 新名称").build()


def _success(receipt, view) -> DocumentMessage:
    return (
        M.document()
        .section("铭刻完成", icon="item")
        .field("世界", view.skin.name)
        .field("铭刻名", receipt.custom_name)
        .line(receipt.medium_flavor_text)
        .build()
    )


def _preference_message(preference, *, invalid: bool = False) -> DocumentMessage:
    builder = (
        M.document()
        .section("铭刻原名", icon="item")
        .field("当前状态", "开启" if preference.show_original_name else "关闭")
        .row(
            ("开启展示", "铭刻名（世界完整原名）"),
            ("关闭展示", "铭刻名"),
        )
    )
    if invalid:
        builder.line("铭刻原名只支持 开启 或 关闭。")
    return (
        builder.actions(
            (
                Action("inscription.original.enable", "开启", "铭刻原名 开启"),
                Action(
                    "inscription.original.disable",
                    "关闭",
                    "铭刻原名 关闭",
                    style="secondary",
                ),
            )
        )
        .build()
    )


def _asset_usage() -> DocumentMessage:
    return M.document().section("铭刻", icon="item").line(
        "发送: 铭刻 羽毛编号 目标编号 新名称"
    ).build()


def _ability_usage() -> DocumentMessage:
    return M.document().section("铭刻能力", icon="skill").line(
        "发送: 铭刻能力 羽毛编号 武器编号 能力序号 新名称"
    ).build()


def _invalid(message: str) -> DocumentMessage:
    return M.document().section("铭刻未完成", icon="notice").line(message).build()


def _unavailable(title: str) -> DocumentMessage:
    return M.document().section(title, icon="notice").line(
        "当前没有读取到角色或物品状态，请稍后重试"
    ).build()


async def _failed(title: str, character_id: str, exc: Exception) -> None:
    await send_command_failure(title, character_id, exc, _unavailable(title))


def _medium(inventory: InventoryState, token: str) -> ItemInstance:
    instance = _instance(inventory, token)
    if not _definition(instance).tags.has("item.inscription_medium"):
        raise ValueError("指定编号不是铭刻媒介")
    _medium_data(instance)
    return instance


def _asset_target(inventory: InventoryState, token: str) -> ItemInstance:
    instance = _instance(inventory, token)
    definition = _definition(instance)
    if not (definition.tags.has("item.weapon") or definition.tags.has("item.equipment")):
        raise ValueError("铭刻目标只能是武器或装备")
    return instance


def _weapon(inventory: InventoryState, token: str) -> ItemInstance:
    instance = _instance(inventory, token)
    if not _definition(instance).tags.has("item.weapon"):
        raise ValueError("指定编号不是武器")
    return instance


def _instance(inventory: InventoryState, token: str) -> ItemInstance:
    asset = resolve_asset_reference(
        inventory,
        token,
        current_game_services().content.catalog.items,
    )
    if not isinstance(asset, ItemInstance):
        raise ValueError("指定编号不是独立物品")
    return asset


def _ability(weapon: ItemInstance, token: str) -> tuple[str, int]:
    try:
        index = int(str(token or "").strip())
    except ValueError as exc:
        raise ValueError("能力序号必须是数字") from exc
    abilities = _weapon_abilities(weapon)
    if index < 1 or index > len(abilities):
        raise ValueError("武器没有这个能力序号")
    return abilities[index - 1], index


def _weapon_abilities(weapon: ItemInstance) -> tuple[str, ...]:
    services = current_game_services()
    state = weapon_state_from_instance(weapon)
    provider = WeaponContributionProvider(services.content.catalog.weapons)
    return tuple(sorted(provider.contribution(state).contribution.abilities))


def _asset_name(instance: ItemInstance, preference, view) -> str:
    if _definition(instance).tags.has("item.weapon"):
        return view.gear_projector.weapon(
            weapon_state_from_instance(instance),
            instance,
            inscription_preference=preference,
        ).name
    return view.gear_projector.equipment(
        equipment_state_from_instance(instance),
        instance,
        inscription_preference=preference,
    ).name


def _definition(instance: ItemInstance):
    return current_game_services().content.catalog.items.require(instance.definition_id)


def _medium_data(instance: ItemInstance) -> InscriptionMediumData:
    data = instance.data.get(INSCRIPTION_MEDIUM_DATA_KEY)
    if not isinstance(data, InscriptionMediumData):
        raise ValueError("铭刻媒介缺少标题或故事")
    return data


def _reference(inventory: InventoryState, instance: ItemInstance) -> str:
    return asset_reference(
        inventory,
        instance,
        current_game_services().content.catalog.items,
    )


def _sorted(inventory: InventoryState, values: list[ItemInstance]):
    return sorted(values, key=lambda value: inventory.reference_number(value.id))


def _projected_name(definition_id: str, view) -> str:
    try:
        return view.projector.name(definition_id)
    except KeyError:
        return definition_id


def _ability_name(weapon: ItemInstance, ability_id: str, preference, view) -> str:
    return InscriptionProjector(preference).weapon_ability_name(
        _projected_name(ability_id, view),
        weapon,
        ability_id,
    )


def _parse_switch(value: object) -> bool | None:
    requested = str(value or "").strip().casefold()
    if requested in {"开启", "打开", "启用", "开", "on", "1"}:
        return True
    if requested in {"关闭", "关掉", "停用", "关", "off", "0"}:
        return False
    return None


def _transaction_id(prefix: str) -> str:
    context = current_message_context()
    if context is None:
        raise RuntimeError("铭刻命令缺少消息上下文")
    return f"{prefix}:{context.identity.evidence_id}"


__all__ = [
    "confirm_ability_inscription",
    "confirm_asset_inscription",
    "inscription",
    "inscription_ability",
    "inscription_original_name",
]
