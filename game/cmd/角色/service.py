"""角色组件的业务调用与协议中立回复。"""

from __future__ import annotations

import asyncio
from math import ceil

from game.content import (
    CHARACTER_LEVEL_PROGRESSION_ID,
    MORTAL_PHYSIQUE_FEATURE_ID,
    ORIGIN_HUMAN_FEATURE_ID,
    PRIMARY_CURRENCY_ID,
    SMALL_HEALTH_MEDICINE_ITEM_ID,
    SMALL_SPIRIT_MEDICINE_ITEM_ID,
    STARTING_CITY_ID,
)
from game.content.catalog.combat import (
    COMBAT_ACCURACY,
    COMBAT_BLOCK_CHANCE,
    COMBAT_BLOCK_REDUCTION,
    COMBAT_CONTROL_CHANCE,
    COMBAT_CONTROL_RESISTANCE,
    COMBAT_CRITICAL_CHANCE,
    COMBAT_CRITICAL_DAMAGE,
    COMBAT_EVASION,
    COMBAT_FLAT_PENETRATION,
    COMBAT_HEALING_RATE,
    COMBAT_HEALING_RECEIVED,
    COMBAT_INCOMING_RATE,
    COMBAT_OUTGOING_RATE,
    COMBAT_RATE_PENETRATION,
    COMBAT_TENACITY,
)
from game.content.catalog.character import REST_ACTION_ID
from game.content.presentation import COVENANT_NAME
from game.core.account import IdentityEvidence
from game.core.gameplay import (
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    COMBAT_SPEED,
    ACCESSORY_SLOT_ID,
    BODY_SLOT_ID,
    FEET_SLOT_ID,
    HANDS_SLOT_ID,
    HEAD_SLOT_ID,
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    SPIRIT_MAXIMUM,
    STANDARD_LOADOUT_SLOT_ORDER,
    WAIST_SLOT_ID,
    WEAPON_SLOT_ID,
    equipment_state_from_instance,
    weapon_state_from_instance,
)
from game.app import (
    CharacterCreationCommandResult,
    CharacterOverview,
    CharacterOverviewResult,
    CurrentCharacterResult,
    current_game_services,
    message_identity_evidence,
)
from game.rules.character import CharacterCreationReceipt, CharacterSettingsState
from game.rules.player_activity import PlayerActivityKind
from game.rules.item import asset_reference
from launch import C, logger
from launch.adapter import current_message_context
from message import Action, DocumentMessage, M
from message.schema import FieldSeparator

from ..command_helpers import command_time
from ..reply import send_game_reply
from ..presentation import (
    character_header_color,
    character_realm_name,
    player_activity_status_text,
)


_LOADOUT_SLOT_LABELS = {
    WEAPON_SLOT_ID: "武器",
    HEAD_SLOT_ID: "头部",
    BODY_SLOT_ID: "身体",
    HANDS_SLOT_ID: "手部",
    WAIST_SLOT_ID: "腰部",
    FEET_SLOT_ID: "足部",
    ACCESSORY_SLOT_ID: "饰品",
}


async def create_character(requested_name: str) -> None:
    """从公共消息上下文读取当前玩家并执行创建。"""

    context = current_message_context()
    if context is None:
        raise RuntimeError("创建角色缺少当前消息上下文")
    logical_time = command_time()
    evidence = message_identity_evidence(
        context.identity,
        logical_time=logical_time,
    )
    await _execute(
        evidence=evidence,
        requested_name=requested_name,
        sender_name=context.sender_name,
    )


async def view_character(result: CharacterOverviewResult) -> None:
    """展示依赖层已经读取的当前角色状态。"""

    await send_game_reply(_overview_message(result))


async def view_combat_panel(result: CharacterOverviewResult) -> None:
    """展示当前配装经过真实战斗投影后的最终数据。"""

    if result.status != "ok" or result.overview is None:
        await send_game_reply(_combat_panel_unavailable_message())
        return
    try:
        message = await asyncio.to_thread(_combat_panel_message, result.overview)
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(
                C.fail("战斗面板生成失败"),
                C.kv("character", result.overview.character.id),
            )
        )
        message = _combat_panel_unavailable_message()
    await send_game_reply(message)


async def mood(message: str, current: CurrentCharacterResult) -> None:
    """查看或修改当前角色的彩色人物头开关。"""

    if current.status != "ok" or current.character is None:
        await send_game_reply(_mood_unavailable_message())
        return
    services = current_game_services()
    try:
        settings = await asyncio.to_thread(
            services.load_character_settings,
            current.character.id,
        )
        requested = str(message or "").strip().casefold()
        if requested:
            on_words = {"开启", "打开", "启用", "开", "on", "1"}
            off_words = {"关闭", "关掉", "停用", "关", "off", "0"}
            if requested in on_words:
                enabled = True
            elif requested in off_words:
                enabled = False
            else:
                await send_game_reply(
                    _mood_message(settings, invalid=True)
                )
                return
            settings = await asyncio.to_thread(
                services.set_mood_header_enabled,
                current.character.id,
                enabled,
                logical_time=command_time(),
            )
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(
                C.fail("心情设置执行失败"),
                C.kv("character", current.character.id),
            )
        )
        await send_game_reply(_mood_unavailable_message())
        return
    await send_game_reply(_mood_message(settings))


async def auto_medicine(message: str, current: CurrentCharacterResult) -> None:
    """查看或修改当前角色的探险自动用药开关。"""

    if current.status != "ok" or current.character is None:
        await send_game_reply(_setting_unavailable_message("自动用药"))
        return
    services = current_game_services()
    try:
        settings = await asyncio.to_thread(
            services.load_character_settings,
            current.character.id,
        )
        requested = _parse_switch(message)
        if requested is None and str(message or "").strip():
            await send_game_reply(_auto_medicine_message(settings, invalid=True))
            return
        if requested is not None:
            settings = await asyncio.to_thread(
                services.set_auto_use_medicine,
                current.character.id,
                requested,
                logical_time=command_time(),
            )
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(
                C.fail("自动用药设置执行失败"),
                C.kv("character", current.character.id),
            )
        )
        await send_game_reply(_setting_unavailable_message("自动用药"))
        return
    await send_game_reply(_auto_medicine_message(settings))


async def auto_rest(message: str, current: CurrentCharacterResult) -> None:
    """查看或修改当前角色的探险自动休整开关。"""

    if current.status != "ok" or current.character is None:
        await send_game_reply(_setting_unavailable_message("自动休整"))
        return
    services = current_game_services()
    try:
        settings = await asyncio.to_thread(
            services.load_character_settings,
            current.character.id,
        )
        requested = _parse_switch(message)
        if requested is None and str(message or "").strip():
            await send_game_reply(_auto_rest_message(settings, invalid=True))
            return
        if requested is not None:
            settings = await asyncio.to_thread(
                services.set_auto_rest,
                current.character.id,
                requested,
                logical_time=command_time(),
            )
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(
                C.fail("自动休整设置执行失败"),
                C.kv("character", current.character.id),
            )
        )
        await send_game_reply(_setting_unavailable_message("自动休整"))
        return
    await send_game_reply(_auto_rest_message(settings))


async def _execute(
    *,
    evidence: IdentityEvidence,
    requested_name: str,
    sender_name: str,
) -> None:
    services = current_game_services()
    try:
        result = await asyncio.to_thread(
            services.create_character,
            evidence,
            requested_name=requested_name,
            platform_name=sender_name,
        )
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(C.fail("创建角色命令执行失败"), C.kv("evidence", evidence.id))
        )
        result = CharacterCreationCommandResult("failed")
    await send_game_reply(_result_message(result))


def _result_message(result: CharacterCreationCommandResult) -> DocumentMessage:
    if result.status == "created" and result.receipt is not None:
        return _created_message(result.receipt)
    if result.status == "existing" and result.existing_character is not None:
        return (
            M.document()
            .section("角色已存在", icon="notice")
            .field("状态", "已建立")
            .line("当前账号不能重复创建角色。")
            .action(
                Action(
                    "character.existing.view",
                    "查看角色",
                    "我的角色",
                    behavior="callback",
                )
            )
            .build()
        )
    if result.status == "name_required":
        return (
            M.document()
            .header("创建角色")
            .section("需要角色名", icon="notice")
            .line("发送: 创建角色 名称")
            .actions(
                (
                    Action(
                        "character.create.fill_name",
                        "填写名称",
                        "创建角色 ",
                        behavior="fill",
                        style="secondary",
                    ),
                )
            )
            .build()
        )
    if result.status == "name_invalid":
        return (
            M.document()
            .header("创建角色")
            .section("名称不可用", icon="notice")
            .line("角色名只能使用中文、英文字母或数字，显示宽度不能超过 12。")
            .line("发送: 创建角色 名称")
            .actions(
                (
                    Action(
                        "character.create.valid_name",
                        "填写名称",
                        "创建角色 ",
                        behavior="fill",
                        style="primary",
                    ),
                )
            )
            .build()
        )
    if result.status == "identity_conflict":
        return (
            M.document()
            .header("创建角色")
            .section("身份归属冲突", icon="notice")
            .line("当前平台身份对应多个账号，暂时不能创建角色。")
            .action(
                Action(
                    "character.identity.help",
                    "查看帮助",
                    "帮助",
                    behavior="callback",
                    style="secondary",
                )
            )
            .build()
        )
    return (
        M.document()
        .header("创建角色")
        .section("创建失败", icon="notice")
        .line("当前没有写入角色，请稍后重试。")
        .action(
            Action(
                "character.create.retry",
                "重新填写",
                "创建角色 ",
                behavior="fill",
                style="secondary",
            )
        )
        .build()
    )


def _created_message(receipt: CharacterCreationReceipt) -> DocumentMessage:
    services = current_game_services()
    view = services.world_view(receipt.character_world)
    projector = view.projector
    character = receipt.character
    quantities = {
        stack.definition_id: stack.quantity
        for stack in receipt.inventory.stacks.values()
    }
    wallet = next(
        account
        for account in receipt.ledger.accounts.values()
        if account.owner_id == character.id and account.currency_id == PRIMARY_CURRENCY_ID
    )
    starter_instance = receipt.inventory.instances[receipt.starter_weapon.asset_id]
    starter_name = view.gear_projector.weapon(
        receipt.starter_weapon,
        starter_instance,
    ).name
    starting_location = projector.name(STARTING_CITY_ID)
    return (
        M.document()
        .section("行纪开篇", icon="world")
        .line(f"源印建立完成，{COVENANT_NAME}已经收录了你的名字。")
        .field("首次降临", f"{view.skin.name}·{starting_location}")
        .row(
            ("种族", projector.name(ORIGIN_HUMAN_FEATURE_ID)),
            ("体质", projector.name(MORTAL_PHYSIQUE_FEATURE_ID)),
        )
        .row(
            (
                _resource_name(projector, HEALTH_CURRENT),
                f"{int(character.resources[HEALTH_CURRENT])}/{int(character.core_attributes[HEALTH_MAXIMUM])}",
            ),
            (
                _resource_name(projector, SPIRIT_CURRENT),
                f"{int(character.resources[SPIRIT_CURRENT])}/{int(character.core_attributes[SPIRIT_MAXIMUM])}",
            ),
        )
        .section("初始行囊", icon="inventory")
        .field("武器", starter_name)
        .row(
            (projector.name(PRIMARY_CURRENCY_ID), wallet.balance),
            (
                projector.name(SMALL_HEALTH_MEDICINE_ITEM_ID),
                f"x{quantities[SMALL_HEALTH_MEDICINE_ITEM_ID]}",
            ),
            (
                projector.name(SMALL_SPIRIT_MEDICINE_ITEM_ID),
                f"x{quantities[SMALL_SPIRIT_MEDICINE_ITEM_ID]}",
            ),
        )
        .note("这是你在《万象行纪》中的第一条记录。")
        .section("下一步", icon="world")
        .line(
            M.command("查看当前世界地图", "地图"),
            " | ",
            M.command("选择探险区域", "探险"),
        )
        .build()
    )


def _overview_message(result: CharacterOverviewResult) -> DocumentMessage:
    if result.status == "ok" and result.overview is not None:
        return _character_overview_message(result.overview)
    if result.status == "identity_conflict":
        return (
            M.document()
            .header("我的角色")
            .section("身份归属冲突", icon="notice")
            .line("当前平台身份对应多个账号，暂时不能查看角色。")
            .action(
                Action(
                    "character.overview.identity_help",
                    "查看帮助",
                    "帮助",
                    behavior="callback",
                    style="secondary",
                )
            )
            .build()
        )
    return (
        M.document()
        .header("我的角色")
        .section("读取失败", icon="notice")
        .line("当前没有读取到角色状态，请稍后重试。")
        .action(
            Action(
                "character.overview.retry",
                "重试",
                "我的角色",
                behavior="callback",
            )
        )
        .build()
    )


def _mood_message(
    settings: CharacterSettingsState,
    *,
    invalid: bool = False,
) -> DocumentMessage:
    now_value = command_time()
    color = character_header_color(settings, now_value)
    builder = (
        M.document()
        .section("心情", icon="mood")
        .row(
            ("当前状态", "开启" if settings.mood_header_enabled else "关闭"),
            ("今日颜色", color or "默认"),
        )
    )
    if invalid:
        builder.line("心情只支持 开启 或 关闭。")
    else:
        builder.line("开启后，回复顶部的人物头会按星期轮换颜色。")
    enabled = settings.mood_header_enabled
    return builder.action(
        Action(
            "character.mood.disable" if enabled else "character.mood.enable",
            "关闭" if enabled else "开启",
            "心情 关闭" if enabled else "心情 开启",
            behavior="callback",
        )
    ).build()


def _mood_unavailable_message() -> DocumentMessage:
    return (
        M.document()
        .header("心情")
        .section("读取失败", icon="notice")
        .line("当前没有读取到角色设置，请稍后重试。")
        .action(
            Action(
                "character.mood.retry",
                "重试",
                "心情",
                behavior="callback",
            )
        )
        .build()
    )


def _auto_medicine_message(
    settings: CharacterSettingsState,
    *,
    invalid: bool = False,
) -> DocumentMessage:
    builder = (
        M.document()
        .section("自动用药", icon="recovery")
        .field("当前状态", "开启" if settings.auto_use_medicine else "关闭")
    )
    if invalid:
        builder.line("自动用药只支持 开启 或 关闭。")
    else:
        builder.line("开启后，探险会在批次之间按浪费最少原则使用恢复药。")
    enabled = settings.auto_use_medicine
    return builder.action(
        Action(
            "character.auto_medicine.disable" if enabled else "character.auto_medicine.enable",
            "关闭" if enabled else "开启",
            "自动用药 关闭" if enabled else "自动用药 开启",
            behavior="callback",
        )
    ).build()


def _auto_rest_message(
    settings: CharacterSettingsState,
    *,
    invalid: bool = False,
) -> DocumentMessage:
    builder = (
        M.document()
        .section("自动休整", icon="recovery")
        .field("当前状态", "开启" if settings.auto_rest else "关闭")
    )
    if invalid:
        builder.line("自动休整只支持 开启 或 关闭。")
    else:
        builder.line("开启后，探险会在战败或资源过低时休整，完全恢复后续行。")
    enabled = settings.auto_rest
    return builder.action(
        Action(
            "character.auto_rest.disable" if enabled else "character.auto_rest.enable",
            "关闭" if enabled else "开启",
            "自动休整 关闭" if enabled else "自动休整 开启",
            behavior="callback",
        )
    ).build()


def _setting_unavailable_message(title: str) -> DocumentMessage:
    action_id = {
        "自动用药": "character.auto_medicine.retry",
        "自动休整": "character.auto_rest.retry",
    }[title]
    return (
        M.document()
        .header(title)
        .section("读取失败", icon="notice")
        .line("当前没有读取到角色设置，请稍后重试。")
        .action(Action(action_id, "重试", title, behavior="callback"))
        .build()
    )


def _parse_switch(value: object) -> bool | None:
    requested = str(value or "").strip().casefold()
    if requested in {"开启", "打开", "启用", "开", "on", "1"}:
        return True
    if requested in {"关闭", "关掉", "停用", "关", "off", "0"}:
        return False
    return None


def _character_overview_message(overview: CharacterOverview) -> DocumentMessage:
    services = current_game_services()
    view = services.world_view(overview.character_world)
    projector = view.projector
    character = overview.character
    progression = character.progressions[CHARACTER_LEVEL_PROGRESSION_ID]
    progression_definition = services.content.catalog.characters.progressions.require(
        progression.definition_id
    )
    required = progression_definition.required_for_next_level(progression.level)
    level_cap = progression.level_cap or next(
        (
            value
            for value in progression_definition.level_caps
            if value >= progression.level
        ),
        progression_definition.maximum_level,
    )
    experience = (
        "已满级"
        if required is None
        else "已满，可突破"
        if progression.level >= level_cap and progression.experience >= required
        else f"{progression.experience}/{required}"
    )
    wallet = next(
        (
            account
            for account in overview.ledger.accounts.values()
            if account.owner_id == character.id
            and account.currency_id == PRIMARY_CURRENCY_ID
        ),
        None,
    )
    presence = next(
        (
            value
            for value in overview.world.presences.values()
            if value.owner_id == character.id
        ),
        None,
    )
    location = "未知"
    location_command = ""
    if presence is not None:
        position = presence.position
        anchor_id = current_game_services().content.worlds.anchor_at(
            overview.character_world.world_id,
            position,
        )
        location = (
            _projected_name(
                current_game_services().content.worlds.resolve(
                    overview.character_world.world_id,
                    anchor_id,
                ).display_id,
                view,
            )
            if anchor_id
            else f"({position.x}, {position.y})"
        )
        if anchor_id:
            location_command = f"地图 {location}"
    builder = (
        M.document()
        .section("角色状态", icon="profile")
        .row(
            (
                projector.name(CHARACTER_LEVEL_PROGRESSION_ID),
                character_realm_name(character, projector),
            ),
            ("经验", experience),
        )
        .row(
            (
                _resource_name(projector, HEALTH_CURRENT),
                f"{_number(character.resources[HEALTH_CURRENT])}/{_number(character.core_attributes[HEALTH_MAXIMUM])}",
            ),
            (
                _resource_name(projector, SPIRIT_CURRENT),
                f"{_number(character.resources[SPIRIT_CURRENT])}/{_number(character.core_attributes[SPIRIT_MAXIMUM])}",
            ),
        )
        .section("当前装配", icon="inventory")
    )
    for slot_id in STANDARD_LOADOUT_SLOT_ORDER:
        builder.field(
            _LOADOUT_SLOT_LABELS[slot_id],
            _equipped_name(overview, slot_id, view),
        )
    return (
        builder.section("当前状态", icon="world")
        .row(("世界", view.skin.name), ("归属", COVENANT_NAME))
        .row(
            ("位置", M.command(location, location_command) if location_command else location),
            (projector.name(PRIMARY_CURRENCY_ID), wallet.balance if wallet else 0),
        )
        .field("行动", _action_value(overview, view))
        .row(
            ("自动用药", _switch_text(overview.settings.auto_use_medicine)),
            ("自动休整", _switch_text(overview.settings.auto_rest)),
        )
        .actions(
            (
                Action(
                    "character.combat_panel",
                    "战斗面板",
                    "战斗面板",
                    behavior="callback",
                ),
            )
        )
        .build()
    )


def _combat_panel_message(overview: CharacterOverview) -> DocumentMessage:
    services = current_game_services()
    view = services.world_view(overview.character_world)
    entity = services.player_combat.project(
        overview.character,
        overview.inventory,
        overview.loadout,
    ).entity
    snapshot = entity.snapshot(services.player_combat.attributes)
    projector = view.projector
    preset = "未命名"
    if overview.loadout.active_preset_id:
        token = overview.loadout.active_preset_id.rsplit(".", 1)[-1]
        preset = token[1:] if token.startswith("p") and token[1:].isdigit() else token
    builder = (
        M.document()
        .section("战斗面板", icon="combat")
        .field("当前配装", preset)
        .row(
            (projector.name(HEALTH_MAXIMUM), _number(snapshot.value(HEALTH_MAXIMUM))),
            (projector.name(SPIRIT_MAXIMUM), _number(snapshot.value(SPIRIT_MAXIMUM))),
        )
        .row(
            ("攻击", _number(snapshot.value(COMBAT_ATTACK))),
            ("防御", _number(snapshot.value(COMBAT_DEFENSE))),
        )
        .field("速度", _number(snapshot.value(COMBAT_SPEED)))
        .section("战斗修正", icon="status")
        .row(
            ("命中修正", _percent(snapshot.value(COMBAT_ACCURACY))),
            ("闪避", _percent(snapshot.value(COMBAT_EVASION))),
        )
        .row(
            ("暴击", _percent(snapshot.value(COMBAT_CRITICAL_CHANCE))),
            ("暴击增伤", _percent(snapshot.value(COMBAT_CRITICAL_DAMAGE))),
        )
        .row(
            ("格挡", _percent(snapshot.value(COMBAT_BLOCK_CHANCE))),
            ("格挡减伤", _percent(snapshot.value(COMBAT_BLOCK_REDUCTION))),
        )
        .row(
            ("伤害修正", _percent(snapshot.value(COMBAT_OUTGOING_RATE))),
            ("承伤修正", _percent(snapshot.value(COMBAT_INCOMING_RATE))),
        )
        .row(
            ("固定穿透", _number(snapshot.value(COMBAT_FLAT_PENETRATION))),
            ("比例穿透", _percent(snapshot.value(COMBAT_RATE_PENETRATION))),
        )
        .row(
            ("治疗修正", _percent(snapshot.value(COMBAT_HEALING_RATE))),
            ("受疗修正", _percent(snapshot.value(COMBAT_HEALING_RECEIVED))),
        )
        .row(
            ("控制修正", _percent(snapshot.value(COMBAT_CONTROL_CHANCE))),
            ("控制抵抗", _percent(snapshot.value(COMBAT_CONTROL_RESISTANCE))),
        )
        .field("韧性", _percent(snapshot.value(COMBAT_TENACITY)))
        .section("战斗机制", icon="item")
    )
    _append_value_group(builder, "能力", _ability_names(entity.abilities, view), 3)
    _append_value_group(builder, "特效", _mechanic_names(overview, entity, view), 4)
    _append_value_group(builder, "套装", _set_bonus_names(overview, view), 2)
    return builder.action(
        Action(
            "combat-panel.back",
            "返回角色",
            "我的角色",
            behavior="callback",
            style="secondary",
        )
    ).build()


def _combat_panel_unavailable_message() -> DocumentMessage:
    return (
        M.document()
        .section("战斗面板", icon="combat")
        .line("当前没有读取到角色战斗数据，请稍后重试。")
        .action(
            Action(
                "combat-panel.retry",
                "重试",
                "战斗面板",
                behavior="callback",
            )
        )
        .build()
    )


def _equipped_name(
    overview: CharacterOverview,
    slot_id: str,
    view,
):
    asset_id = overview.loadout.slots.get(slot_id)
    if asset_id is None:
        return "未装备"
    instance = overview.inventory.instances.get(asset_id)
    if instance is None:
        return "状态异常"
    if slot_id == WEAPON_SLOT_ID:
        weapon = weapon_state_from_instance(instance)
        name = view.gear_projector.weapon(
            weapon,
            instance,
            inscription_preference=overview.inscription_preference,
        ).name
        display = f"{name} | Lv{weapon.level}"
    else:
        equipment = equipment_state_from_instance(instance)
        display = view.gear_projector.equipment(
            equipment,
            instance,
            inscription_preference=overview.inscription_preference,
        ).name
    reference = asset_reference(
        overview.inventory,
        instance,
        current_game_services().content.catalog.items,
    )
    return M.command(display, f"查看 {reference}")


def _ability_names(ability_ids, view) -> tuple[object, ...]:
    return tuple(
        _mechanic_link(value, view)
        for value in sorted(ability_ids)
    )


def _mechanic_names(overview: CharacterOverview, entity, view) -> tuple[object, ...]:
    names: list[object] = []
    seen: set[str] = set()
    rolled_property_ids: set[str] = set()
    for asset_id in overview.loadout.slots.values():
        instance = overview.inventory.instances.get(asset_id)
        if instance is None:
            continue
        state = (
            weapon_state_from_instance(instance)
            if asset_id == overview.loadout.weapon_asset_id
            else equipment_state_from_instance(instance)
        )
        if state.roll is None:
            continue
        for rolled in state.roll.properties:
            property_id = str(rolled.property_id)
            rolled_property_ids.add(property_id)
            name = _projected_name(property_id, view)
            label = (
                name
                if property_id.startswith("property.weapon_core.")
                else f"{name} T{rolled.tier}"
            )
            key = f"{property_id}:tier:{rolled.tier}"
            if key not in seen:
                seen.add(key)
                names.append(M.command(label, f"特效 {name}"))
    for trigger_id in sorted(entity.triggers):
        property_id = _trigger_property_id(trigger_id)
        if property_id is None:
            continue
        if property_id in rolled_property_ids:
            continue
        name = _projected_name(property_id, view)
        key = f"{property_id}:runtime"
        if key not in seen:
            seen.add(key)
            names.append(M.command(name, f"特效 {name}"))
    return tuple(names)


def _trigger_property_id(trigger_id: str) -> str | None:
    if trigger_id.startswith("trigger.equipment."):
        key = trigger_id.removeprefix("trigger.equipment.").split(".", 1)[0]
        return f"property.equipment.{key}"
    if trigger_id.startswith("trigger.weapon."):
        key = trigger_id.removeprefix("trigger.weapon.").split(".", 1)[0]
        return f"property.weapon_core.{key}"
    return None


def _set_bonus_names(overview: CharacterOverview, view) -> tuple[object, ...]:
    catalog = current_game_services().content.catalog.equipment
    counts: dict[str, int] = {}
    for asset_id in overview.loadout.equipment_asset_ids:
        instance = overview.inventory.instances.get(asset_id)
        if instance is None:
            continue
        set_id = equipment_state_from_instance(instance).set_id
        if set_id is not None:
            counts[set_id] = counts.get(set_id, 0) + 1
    names = []
    for set_id, count in sorted(counts.items()):
        active = tuple(
            bonus.required_pieces
            for bonus in catalog.sets.require(set_id).bonuses
            if count >= bonus.required_pieces
        )
        if active:
            thresholds = "/".join(str(value) for value in active)
            name = _projected_name(set_id, view)
            names.append(
                M.command(
                    f"{name} x{count} | {thresholds}件生效",
                    f"特效 {name}",
                )
            )
    return tuple(names)


def _append_value_group(builder, label: str, values: tuple[object, ...], size: int) -> None:
    if not values:
        builder.line(f"{label}: 无")
        return
    groups = tuple(values[index : index + size] for index in range(0, len(values), size))
    for group_index, group in enumerate(groups):
        parts: list[object] = [f"{label}: "] if group_index == 0 else []
        for index, value in enumerate(group):
            if index:
                parts.append(FieldSeparator())
            parts.append(value)
        builder.line(*parts)


def _percent(value: float) -> str:
    percentage = float(value) * 100.0
    if abs(percentage) < 0.005:
        return "0%"
    text = f"{percentage:+.2f}".rstrip("0").rstrip(".")
    return f"{text}%"


def _projected_name(definition_id: str, view) -> str:
    return view.projector.name(definition_id)


def _mechanic_link(definition_id: str, view):
    name = _projected_name(definition_id, view)
    return M.command(name, f"特效 {name}")


def _action_text(overview: CharacterOverview, view) -> str:
    activity = overview.activity
    if activity.exploration_active:
        exploration_text = player_activity_status_text(activity)
        if (
            activity.kind is PlayerActivityKind.EXPLORATION_RESTING
            and activity.exploration is not None
            and activity.exploration.rest_completes_at is not None
        ):
            remaining_seconds = max(
                0,
                int(
                    (
                        activity.exploration.rest_completes_at - command_time()
                    ).total_seconds()
                ),
            )
            remaining_minutes = ceil(remaining_seconds / 60)
            return f"{exploration_text} | 剩余 {remaining_minutes} 分钟"
        return exploration_text
    if activity.kind is PlayerActivityKind.MAIN_ACTION:
        record = activity.main_action
        if record is None:
            raise RuntimeError("主要行动投影缺少行动记录")
        remaining_seconds = max(0, int((record.completes_at - command_time()).total_seconds()))
        remaining_minutes = ceil(remaining_seconds / 60)
        return f"{_projected_name(record.definition_id, view)} | 剩余 {remaining_minutes} 分钟"
    if activity.pending_actions:
        return f"{len(activity.pending_actions)} 项待领取"
    return player_activity_status_text(activity)


def _action_value(overview: CharacterOverview, view):
    text = _action_text(overview, view)
    activity = overview.activity
    if activity.exploration_active:
        return M.command(text, "停止探险")
    if (
        activity.main_action is not None
        and activity.main_action.definition_id == REST_ACTION_ID
    ) or activity.pending_actions:
        return M.command(text, "结束休息")
    return text


def _switch_text(enabled: bool) -> str:
    return "开启" if enabled else "关闭"


def _number(value: float) -> str:
    number = float(value)
    if abs(number) < 0.005:
        return "0"
    return str(int(number)) if number.is_integer() else f"{number:.2f}".rstrip("0").rstrip(".")


def _resource_name(projector, resource_id: str) -> str:
    return projector.name(resource_id).removeprefix("当前")


__all__ = [
    "create_character",
    "auto_medicine",
    "auto_rest",
    "mood",
    "view_character",
]
