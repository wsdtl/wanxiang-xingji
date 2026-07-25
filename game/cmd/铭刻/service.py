"""铭刻命令解析、直接执行与协议中立展示。"""

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
from ..interaction import (
    DEFAULT_PAGE_SIZE,
    paginate,
    pagination_actions,
    parse_page_number,
)
from ..reply import send_command_failure, send_game_reply


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
    if not requested or (len(requested.split()) == 1 and requested.isdigit()):
        try:
            page = parse_page_number(requested)
            await send_game_reply(
                _inscription_home(
                    overview.inventory,
                    overview.inscription_preference,
                    view,
                    page,
                )
            )
        except ValueError as exc:
            await send_game_reply(_invalid(str(exc)))
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
    try:
        await send_game_reply(
            await _apply_asset_inscription(
                character,
                overview,
                medium,
                target,
                custom_name,
            )
        )
    except Exception as exc:
        await _failed("资产铭刻执行失败", character.id, exc)


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
    if not requested or (len(requested.split()) == 1 and requested.isdigit()):
        try:
            page = parse_page_number(requested)
            await send_game_reply(
                _ability_home(
                    overview.inventory,
                    overview.inscription_preference,
                    view,
                    page,
                )
            )
        except ValueError as exc:
            await send_game_reply(_invalid(str(exc)))
        return
    parts = requested.split(maxsplit=3)
    if len(parts) != 4:
        await send_game_reply(_ability_usage())
        return
    medium_ref, weapon_ref, ability_token, custom_name = parts
    try:
        medium = _medium(overview.inventory, medium_ref)
        weapon = _weapon(overview.inventory, weapon_ref)
        ability_id, _ = _ability(weapon, ability_token)
        custom_name = clean_inscription_name(custom_name)
    except (KeyError, TypeError, ValueError) as exc:
        await send_game_reply(_invalid(str(exc)))
        return
    try:
        await send_game_reply(
            await _apply_ability_inscription(
                character,
                overview,
                medium,
                weapon,
                ability_id,
                custom_name,
            )
        )
    except Exception as exc:
        await _failed("能力铭刻执行失败", character.id, exc)


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
        await send_game_reply(
            _invalid(
                "铭刻确认参数不完整",
                Action("inscription.back", "返回铭刻", "铭刻", style="secondary"),
            )
        )
        return
    overview = await _load_overview(character)
    if overview is None:
        await send_game_reply(_unavailable("确认铭刻"))
        return
    try:
        medium = _medium(overview.inventory, parts[0])
        target = _asset_target(overview.inventory, parts[1])
        custom_name = clean_inscription_name(parts[2])
        reply = await _apply_asset_inscription(
            character,
            overview,
            medium,
            target,
            custom_name,
        )
    except Exception as exc:
        await _failed("资产铭刻执行失败", character.id, exc)
        return
    await send_game_reply(reply)


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
        await send_game_reply(
            _invalid(
                "铭刻确认参数不完整",
                Action(
                    "inscription.ability.back",
                    "返回能力铭刻",
                    "铭刻能力",
                    style="secondary",
                ),
            )
        )
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
        reply = await _apply_ability_inscription(
            character,
            overview,
            medium,
            weapon,
            ability_id,
            custom_name,
        )
    except Exception as exc:
        await _failed("能力铭刻执行失败", character.id, exc)
        return
    await send_game_reply(reply)


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


async def _apply_asset_inscription(
    character,
    overview,
    medium: ItemInstance,
    target: ItemInstance,
    custom_name: str,
) -> DocumentMessage:
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
    if outcome.failure:
        return _invalid(
            outcome.failure.message,
            Action("inscription.back", "重新选择", "铭刻", style="secondary"),
        )
    assert outcome.value is not None
    return _success(
        outcome.value,
        current_game_services().world_view(overview.character_world),
    )


async def _apply_ability_inscription(
    character,
    overview,
    medium: ItemInstance,
    weapon: ItemInstance,
    ability_id: str,
    custom_name: str,
) -> DocumentMessage:
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
    if outcome.failure:
        return _invalid(
            outcome.failure.message,
            Action(
                "inscription.ability.back",
                "重新选择",
                "铭刻能力",
                style="secondary",
            ),
        )
    assert outcome.value is not None
    return _success(
        outcome.value,
        current_game_services().world_view(overview.character_world),
    )


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


def _inscription_home(
    inventory: InventoryState,
    preference,
    view,
    page: int,
) -> DocumentMessage:
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
    entries = tuple(("medium", value) for value in _sorted(inventory, mediums)) + tuple(
        ("target", value) for value in _sorted(inventory, targets)
    )
    window = paginate(entries, page, page_size=DEFAULT_PAGE_SIZE)
    builder = (
        M.document()
        .section("铭刻", icon="item")
        .field("世界", view.skin.name)
        .row(("铭刻媒介", len(mediums)), ("可铭刻目标", len(targets)))
    )
    medium_name = view.projector.name(INSCRIPTION_FEATHER_ITEM_ID)
    if not mediums:
        builder.line(f"暂无{medium_name}")
    if not targets:
        builder.line("当前没有可铭刻目标")
    current_kind = ""
    for kind, value in window.values:
        if kind != current_kind:
            builder.section(
                medium_name if kind == "medium" else "可铭刻目标",
                icon="item" if kind == "medium" else "equipment",
            )
            current_kind = kind
        reference = _reference(inventory, value)
        if kind == "medium":
            medium = value
            data = medium.data.get(INSCRIPTION_MEDIUM_DATA_KEY)
            title = data.title if isinstance(data, InscriptionMediumData) else "数据异常"
            builder.line(
                M.command(
                    f"{reference} {title}",
                    f"铭刻 {reference} ",
                    submit=False,
                )
            )
        else:
            target = value
            builder.line(
                M.command(reference, f"查看 {reference}"),
                FieldSeparator(),
                M.command(_asset_name(target, preference, view), f"查看 {reference}"),
            )
    builder.row(("页码", window.label), ("总计", window.total)).actions(
        pagination_actions("铭刻", window)
    )
    return builder.note("发送: 铭刻 羽毛编号 目标编号 新名称").build()


def _ability_home(
    inventory: InventoryState,
    preference,
    view,
    page: int,
) -> DocumentMessage:
    weapons = [
        value
        for value in inventory.instances.values()
        if _definition(value).tags.has("item.weapon")
    ]
    mediums = [
        value
        for value in inventory.instances.values()
        if _definition(value).tags.has("item.inscription_medium")
    ]
    medium = _sorted(inventory, mediums)[0] if mediums else None
    entries = tuple(
        (weapon, index, ability_id)
        for weapon in _sorted(inventory, weapons)
        for index, ability_id in enumerate(_weapon_abilities(weapon), start=1)
    )
    window = paginate(entries, page, page_size=DEFAULT_PAGE_SIZE)
    builder = (
        M.document()
        .section("铭刻能力", icon="skill")
        .field("世界", view.skin.name)
        .row(("武器", len(weapons)), ("能力", len(entries)))
    )
    if medium is None:
        builder.line(f"暂无{view.projector.name(INSCRIPTION_FEATHER_ITEM_ID)}")
    for weapon, index, ability_id in window.values:
        weapon_reference = _reference(inventory, weapon)
        ability_name = _ability_name(weapon, ability_id, preference, view)
        ability_command = (
            f"铭刻能力 {_reference(inventory, medium)} {weapon_reference} {index} "
            if medium is not None
            else f"查看 {weapon_reference}"
        )
        builder.line(
            M.command(
                f"{weapon_reference} {_asset_name(weapon, preference, view)}",
                f"查看 {weapon_reference}",
            ),
            FieldSeparator(),
            M.command(
                f"[{index}] {ability_name}",
                ability_command,
                submit=medium is None,
            ),
        )
    if not entries:
        builder.line("当前没有可以铭刻能力的武器")
    builder.row(("页码", window.label), ("总计", window.total)).actions(
        pagination_actions("铭刻能力", window)
    )
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
    enabled = preference.show_original_name
    return builder.action(
        Action(
            "inscription.original.disable" if enabled else "inscription.original.enable",
            "关闭" if enabled else "开启",
            "铭刻原名 关闭" if enabled else "铭刻原名 开启",
        )
    ).build()


def _asset_usage() -> DocumentMessage:
    return M.document().section("铭刻", icon="item").line(
        "发送: 铭刻 羽毛编号 目标编号 新名称"
    ).build()


def _ability_usage() -> DocumentMessage:
    return M.document().section("铭刻能力", icon="skill").line(
        "发送: 铭刻能力 羽毛编号 武器编号 能力序号 新名称"
    ).build()


def _invalid(message: str, recovery: Action | None = None) -> DocumentMessage:
    builder = M.document().section("铭刻未完成", icon="notice").line(message)
    if recovery is not None:
        builder.action(recovery)
    return builder.build()


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
