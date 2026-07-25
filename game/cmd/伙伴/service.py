"""伙伴命令解析、确认和协议中立展示。"""

from __future__ import annotations

import asyncio

from game.app import CharacterOverview, CharacterOverviewResult, current_game_services
from game.content import CHARACTER_LEVEL_PROGRESSION_ID, LOADOUT_PRESET_IDS
from game.core.gameplay import (
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    COMBAT_SPEED,
    HEALTH_MAXIMUM,
    SPIRIT_MAXIMUM,
)
from game.features.world_travel import WorldLocationIntent
from game.rules.companion import CompanionKind, CompanionSanctuaryStatus
from game.rules.item import resolve_asset_reference
from launch import C, logger
from launch.adapter import current_message_context
from launch.paths import public_url
from message import Action, DocumentMessage, M
from message.schema import FieldSeparator

from ..command_helpers import command_time
from ..reply import send_game_reply


_APTITUDE_NAMES = {
    "companion.aptitude.vitality": "体魄",
    "companion.aptitude.offense": "威势",
    "companion.aptitude.agility": "灵动",
    "companion.aptitude.focus": "灵性",
}
_ROLE_NAMES = {
    "assault": "强攻",
    "swift": "迅捷",
    "guardian": "守护",
    "control": "控制",
    "sustain": "续航",
}


async def view_companions(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_unavailable())
        return
    try:
        view = await asyncio.to_thread(
            current_game_services().companions.view,
            overview.character.id,
            logical_time=command_time(),
        )
        reference = str(message or "").strip()
        reply = (
            _companion_detail(view.roster, reference, overview)
            if reference
            else _companion_list(view.roster, overview)
        )
    except (KeyError, TypeError, ValueError) as exc:
        reply = _failure(str(exc))
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(C.fail("伙伴名册读取失败"), C.kv("character", overview.character.id))
        )
        reply = _failure("当前没有读取到伙伴名册")
    await send_game_reply(reply)


async def bind_companion(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    reference = str(message or "").strip().upper()
    if overview is None:
        await send_game_reply(_unavailable())
        return
    if not reference:
        await send_game_reply(_failure("发送：伙伴出战 C1"))
        return
    operation_id = _operation_id("companion-bind")
    try:
        outcome = await asyncio.to_thread(
            current_game_services().companions.bind,
            operation_id,
            overview.character.id,
            reference,
            allow_transfer=False,
            logical_time=command_time(),
        )
        if outcome.status == "transfer_required" and outcome.roster is not None:
            await send_game_reply(_transfer_confirmation(outcome, overview))
            return
        await send_game_reply(_bind_result(outcome))
    except Exception as exc:
        await _logged_failure("伙伴出战失败", overview.character.id, exc)


async def confirm_bind_transfer(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_unavailable())
        return
    parts = str(message or "").split()
    if len(parts) != 2:
        await send_game_reply(_failure("出战确认已经失效"))
        return
    try:
        revision = int(parts[1])
        outcome = await asyncio.to_thread(
            current_game_services().companions.bind,
            _operation_id("companion-bind-transfer"),
            overview.character.id,
            parts[0],
            allow_transfer=True,
            expected_revision=revision,
            logical_time=command_time(),
        )
        await send_game_reply(_bind_result(outcome))
    except (TypeError, ValueError):
        await send_game_reply(_failure("出战确认已经失效"))
    except Exception as exc:
        await _logged_failure("伙伴转移失败", overview.character.id, exc)


async def unbind_companion(result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_unavailable())
        return
    try:
        outcome = await asyncio.to_thread(
            current_game_services().companions.unbind_current,
            _operation_id("companion-unbind"),
            overview.character.id,
            logical_time=command_time(),
        )
        if outcome.status == "unbound":
            name = _companion_name(outcome.companion) if outcome.companion else "伙伴"
            reply = M.document().section("伙伴休战", icon="player").line(f"{name} 已离开当前配装").build()
        elif outcome.status == "already_unbound":
            reply = _failure("当前配装没有出战伙伴")
        else:
            reply = _failure(outcome.failure_message or "伙伴休战没有完成")
        await send_game_reply(reply)
    except Exception as exc:
        await _logged_failure("伙伴休战失败", overview.character.id, exc)


async def view_sanctuary(result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_unavailable())
        return
    try:
        view = await asyncio.to_thread(
            current_game_services().companions.view,
            overview.character.id,
            logical_time=command_time(),
        )
        await send_game_reply(_sanctuary_message(view.sanctuary, overview))
    except Exception as exc:
        await _logged_failure("宠物秘境读取失败", overview.character.id, exc)


async def hunt_companion(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_unavailable())
        return
    try:
        trace_index = int(str(message or "").strip())
        outcome = await asyncio.to_thread(
            current_game_services().companions.hunt,
            _operation_id("companion-hunt"),
            overview.character.id,
            trace_index,
            logical_time=command_time(),
        )
        await send_game_reply(_hunt_result(outcome))
    except ValueError:
        await send_game_reply(_failure("发送：秘境追踪 1"))
    except Exception as exc:
        await _logged_failure("伙伴追踪失败", overview.character.id, exc)


async def view_people(result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_unavailable())
        return
    try:
        view = await asyncio.to_thread(
            current_game_services().companions.view,
            overview.character.id,
            logical_time=command_time(),
        )
        await send_game_reply(_people_message(view.roster, overview))
    except Exception as exc:
        await _logged_failure("人物地点读取失败", overview.character.id, exc)


async def gift_person(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_unavailable())
        return
    parts = str(message or "").split()
    if len(parts) not in {1, 2}:
        await send_game_reply(_failure("发送：赠礼 T编号 [数量]"))
        return
    try:
        quantity = int(parts[1]) if len(parts) == 2 else 1
        asset = resolve_asset_reference(
            overview.inventory,
            parts[0],
            current_game_services().content.catalog.items,
        )
        outcome = await asyncio.to_thread(
            current_game_services().companions.gift_person,
            _operation_id("companion-person-gift"),
            overview.character.id,
            asset.id,
            quantity,
            logical_time=command_time(),
        )
        await send_game_reply(_gift_result(outcome, overview))
    except ValueError as exc:
        await send_game_reply(_failure(str(exc)))
    except Exception as exc:
        await _logged_failure("人物赠礼失败", overview.character.id, exc)


async def join_person(result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_unavailable())
        return
    try:
        outcome = await asyncio.to_thread(
            current_game_services().companions.join_person,
            _operation_id("companion-person-join"),
            overview.character.id,
            logical_time=command_time(),
        )
        await send_game_reply(_join_result(outcome, overview))
    except Exception as exc:
        await _logged_failure("人物结交失败", overview.character.id, exc)


async def preview_farewell(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    reference = str(message or "").strip().upper()
    if overview is None:
        await send_game_reply(_unavailable())
        return
    try:
        view = await asyncio.to_thread(
            current_game_services().companions.view,
            overview.character.id,
            logical_time=command_time(),
        )
        companion = view.roster.by_reference(reference)
        if companion is None:
            raise ValueError("找不到要告别的伙伴")
        is_person = companion.kind is CompanionKind.PERSON
        reply = (
            M.document()
            .section("确认告别", icon="notice")
            .line(f"{companion.reference} {_companion_name(companion)} 将离开当前名册。")
            .note(
                "人物的成长记录会保留，回到原地点后可以再次结交。"
                if is_person
                else "宠物实例会永久离开，以后捕获的是新的随机实例。"
            )
            .actions((
                Action(
                    "companion.farewell.confirm",
                    "确认告别",
                    f"companion_farewell_confirm {companion.reference} {view.roster.revision}",
                    behavior="send",
                    style="secondary",
                ),
            ))
            .build()
        )
    except (KeyError, ValueError) as exc:
        reply = _failure(str(exc))
    except Exception as exc:
        await _logged_failure("伙伴告别预览失败", overview.character.id, exc)
        return
    await send_game_reply(reply)


async def confirm_farewell(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_unavailable())
        return
    parts = str(message or "").split()
    if len(parts) != 2:
        await send_game_reply(_failure("告别确认已经失效"))
        return
    try:
        outcome = await asyncio.to_thread(
            current_game_services().companions.farewell,
            _operation_id("companion-farewell"),
            overview.character.id,
            parts[0],
            int(parts[1]),
            logical_time=command_time(),
        )
        reply = (
            M.document()
            .section("告别", icon="player")
            .line(f"{_outcome_companion_name(outcome)} 已离开名册")
            .note(
                "回到原地点后可以再次结交。"
                if outcome.status == "person_departed"
                else "以后可以在宠物秘境捕获新的实例。"
            )
            .build()
            if outcome.status in {"person_departed", "pet_departed"}
            else _failure(outcome.failure_message or "告别没有完成")
        )
        await send_game_reply(reply)
    except (TypeError, ValueError):
        await send_game_reply(_failure("告别确认已经失效"))
    except Exception as exc:
        await _logged_failure("伙伴告别失败", overview.character.id, exc)


async def preview_abandon(result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_unavailable())
        return
    try:
        view = await asyncio.to_thread(
            current_game_services().companions.view,
            overview.character.id,
            logical_time=command_time(),
        )
        sanctuary = view.sanctuary
        if sanctuary is None or not sanctuary.active:
            raise ValueError("当前没有可以放弃的宠物秘境")
        reply = (
            M.document()
            .section("确认放弃秘境", icon="notice")
            .line("当前踪迹和已锁定目标都会永久消失。")
            .note("开启秘境消耗的万灵引不会返还。")
            .actions((
                Action(
                    "companion.abandon.confirm",
                    "确认放弃",
                    f"companion_abandon_confirm {sanctuary.revision}",
                    behavior="send",
                    style="secondary",
                ),
            ))
            .build()
        )
    except ValueError as exc:
        reply = _failure(str(exc))
    except Exception as exc:
        await _logged_failure("宠物秘境放弃预览失败", overview.character.id, exc)
        return
    await send_game_reply(reply)


async def confirm_abandon(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_unavailable())
        return
    try:
        outcome = await asyncio.to_thread(
            current_game_services().companions.abandon,
            _operation_id("companion-abandon"),
            overview.character.id,
            int(str(message or "").strip()),
            logical_time=command_time(),
        )
        reply = (
            M.document().section("宠物秘境", icon="explore").line("秘境已经关闭").build()
            if outcome.status == "abandoned"
            else _failure(outcome.failure_message or "放弃秘境没有完成")
        )
        await send_game_reply(reply)
    except (TypeError, ValueError):
        await send_game_reply(_failure("放弃确认已经失效"))
    except Exception as exc:
        await _logged_failure("宠物秘境放弃失败", overview.character.id, exc)


def _people_message(roster, overview: CharacterOverview) -> DocumentMessage:
    services = current_game_services()
    catalog = services.content.companions
    projector = _projector(overview)
    bindings = services.content.worlds.bindings_for_world(
        overview.character_world.world_id,
        function_id="location.function.companion_person",
    )
    people = tuple(
        catalog.people.require(binding.content_ref)
        for binding in bindings
        if binding.content_ref is not None
    )
    binding_by_content = {
        binding.content_ref: binding
        for binding in bindings
        if binding.content_ref is not None
    }
    anchor_id = _current_location(overview)
    current_location = (
        services.content.worlds.resolve(
            overview.character_world.world_id,
            anchor_id,
        )
        if anchor_id is not None
        else None
    )
    builder = (
        M.document()
        .section("人物", icon="world")
        .field("世界", _world_name(overview))
        .field(
            "当前位置",
            projector.name(current_location.display_id) if current_location is not None else "未知",
        )
    )
    actions = []
    for person in people:
        binding = binding_by_content[person.id]
        display_id = binding.display_ref or binding.anchor_id
        active = roster.active_by_definition(person.id)
        bond = roster.person_bonds.get(person.id)
        if active is not None:
            status = "已结交"
        elif person.id in roster.departed_people:
            status = "可以重逢"
        elif bond is not None and bond.favor >= person.bond_required:
            status = "可以结交"
        else:
            status = f"关系 {bond.favor if bond else 0}/{person.bond_required}"
        builder.line(
            person.name,
            FieldSeparator(),
            projector.name(display_id),
            FieldSeparator(),
            status,
        )
        actions.append(
            Action(
                f"person.location.{person.id}",
                projector.name(display_id),
                _location_command(
                    overview.character_world.world_id,
                    binding.anchor_id,
                    "location.function.companion_person",
                ),
                behavior="send",
                style="secondary",
            )
        )
    local = None
    if anchor_id is not None:
        try:
            resolved = services.content.worlds.resolve(
                overview.character_world.world_id,
                anchor_id,
                function_id="location.function.companion_person",
            )
            local = catalog.people.require(resolved.require_content_ref())
        except KeyError:
            pass
    if local is not None:
        bond = roster.person_bonds.get(local.id)
        active = roster.active_by_definition(local.id)
        departed = roster.departed_people.get(local.id)
        builder.section(f"当前相遇·{local.name}", icon="player")
        builder.row(
            ("定位", _ROLE_NAMES[local.role]),
            ("关系", f"{bond.favor if bond else 0}/{local.bond_required}"),
        )
        builder.line(local.description)
        builder.field(
            "偏好",
            "、".join(
                f"{projector.name(item_id)}(+{value})"
                for item_id, value in local.gift_values.items()
            ),
        )
        if active is None and departed is None:
            actions.append(Action("person.gift", "赠礼", "赠礼 ", behavior="fill"))
        if active is None and (
            departed is not None
            or (bond is not None and bond.favor >= local.bond_required)
        ):
            actions.append(Action("person.join", "结交", "结交", behavior="send"))
    return builder.actions(actions).build()


def _gift_result(outcome, overview: CharacterOverview) -> DocumentMessage:
    if outcome.status != "gifted":
        return _failure(outcome.failure_message or "赠礼没有完成")
    person = current_game_services().content.companions.people.require(
        outcome.definition_id
    )
    builder = (
        M.document()
        .section("赠礼", icon="reward")
        .field("人物", person.name)
        .field("消耗", outcome.quantity)
        .field("关系", f"{outcome.value_before} -> {outcome.value_after}/{person.bond_required}")
    )
    if outcome.value_after >= person.bond_required:
        builder.note("关系已经满足结交要求。").actions(
            (Action("person.join", "结交", "结交", behavior="send"),)
        )
    return builder.build()


def _join_result(outcome, overview: CharacterOverview) -> DocumentMessage:
    if outcome.status not in {"joined", "rejoined"} or outcome.companion is None:
        return _failure(outcome.failure_message or "结交没有完成")
    text = "重新回到了你的名册" if outcome.status == "rejoined" else "成为了你的伙伴"
    return (
        M.document()
        .section("结交", icon="player")
        .line(f"{outcome.companion.reference} {_companion_name(outcome.companion)} {text}")
        .actions((
            Action(
                "companion.bind",
                "出战",
                f"伙伴出战 {outcome.companion.reference}",
                behavior="send",
            ),
        ))
        .build()
    )


def _companion_list(roster, overview: CharacterOverview) -> DocumentMessage:
    term = _projector(overview).name("term.companion")
    builder = (
        M.document()
        .section(f"{term}名册", icon="player")
        .field("世界", _world_name(overview))
        .field(
            "数量",
            f"{len(roster.instances)}/{current_game_services().content.companions.balance.roster_capacity}",
        )
    )
    if not roster.instances:
        builder.line("当前还没有伙伴")
    for companion in sorted(roster.instances.values(), key=lambda value: int(value.reference[1:])):
        preset = roster.preset_for_companion(companion.id)
        status = f"配装 {_preset_index(preset)}" if preset is not None else "休战"
        companion_projector = _companion_projector(companion)
        builder.line(
            M.command(companion.reference, f"伙伴 {companion.reference}"),
            " ",
            _companion_name(companion),
            FieldSeparator(),
            "人物" if companion.kind is CompanionKind.PERSON else "宠物",
            FieldSeparator(),
            companion_projector.name(companion.quality_id),
            FieldSeparator(),
            f"Lv{companion.level}",
            FieldSeparator(),
            status,
        )
    builder.actions((
        Action("companion.people", "人物", "人物", behavior="send"),
        Action("companion.sanctuary", "宠物秘境", "宠物秘境", behavior="send"),
    ))
    return builder.build()


def _companion_detail(roster, reference: str, overview: CharacterOverview) -> DocumentMessage:
    companion = roster.by_reference(reference)
    if companion is None:
        raise ValueError("找不到这名伙伴")
    definition = _companion_definition(companion)
    origin_view = current_game_services().world_views.require(companion.origin_world_id)
    projector = _companion_projector(companion)
    origin = origin_view.skin.name
    preset = roster.preset_for_companion(companion.id)
    character_level = overview.character.progressions[CHARACTER_LEVEL_PROGRESSION_ID].level
    required = current_game_services().content.companions.growth.required_for_next_level(
        companion.level
    )
    if companion.level >= 100:
        experience_text = "已满级"
    elif companion.level >= character_level:
        experience_text = f"{companion.experience}/{required}（人物等级限制）"
    else:
        experience_text = f"{companion.experience}/{required}"
    combat = current_game_services().player_lineup.companion_combat.project(companion)
    attributes = combat.entity.snapshot(
        current_game_services().player_lineup.companion_combat.attributes
    )
    builder = (
        M.document()
        .section(f"{companion.reference} {definition.name}", icon="player")
        .row(("品阶", projector.name(companion.quality_id)), ("等级", f"Lv{companion.level}"))
        .row(("类型", "人物" if companion.kind is CompanionKind.PERSON else "宠物"), ("定位", _ROLE_NAMES[definition.role]))
        .field("来源", origin)
        .field("状态", f"配装 {_preset_index(preset)}" if preset is not None else "休战")
        .field("经验", experience_text)
        .line(definition.description)
        .section("资质", icon="status")
    )
    builder.row(*((_APTITUDE_NAMES[str(key)], value) for key, value in companion.aptitudes.items()))
    builder.section("战斗属性", icon="combat")
    builder.row(
        (projector.name(HEALTH_MAXIMUM), _number(attributes.value(HEALTH_MAXIMUM))),
        (projector.name(SPIRIT_MAXIMUM), _number(attributes.value(SPIRIT_MAXIMUM))),
    )
    builder.row(
        (projector.name(COMBAT_ATTACK), _number(attributes.value(COMBAT_ATTACK))),
        (projector.name(COMBAT_DEFENSE), _number(attributes.value(COMBAT_DEFENSE))),
        (projector.name(COMBAT_SPEED), _number(attributes.value(COMBAT_SPEED))),
    )
    builder.section("战斗机制", icon="combat")
    builder.field("主动行动", projector.name(definition.core_behavior_id))
    builder.field("特色效果", projector.name(companion.trait_behavior_id))
    actions = []
    if preset == overview.loadout.active_preset_id:
        actions.append(Action("companion.unbind", "休战", "伙伴休战", behavior="send"))
    else:
        actions.append(Action("companion.bind", projector.name("term.companion_bind"), f"伙伴出战 {companion.reference}", behavior="send"))
    actions.append(Action("companion.farewell", "告别", f"告别 {companion.reference}", behavior="send", style="secondary"))
    return builder.actions(actions).build()


def _sanctuary_message(sanctuary, overview: CharacterOverview) -> DocumentMessage:
    title = _projector(overview).name("term.companion_sanctuary")
    if sanctuary is None:
        return (
            M.document()
            .section(title, icon="explore")
            .field("世界", _world_name(overview))
            .line("当前没有已开启的宠物秘境")
            .note("使用万灵引可在当前世界开启一次秘境。")
            .build()
        )
    status_names = {
        CompanionSanctuaryStatus.OPEN: "等待选择",
        CompanionSanctuaryStatus.TRACKING: "追踪中",
        CompanionSanctuaryStatus.CAPTURED: "已捕获",
        CompanionSanctuaryStatus.ABANDONED: "已放弃",
        CompanionSanctuaryStatus.EXPIRED: "已过期",
    }
    builder = (
        M.document()
        .section(title, icon="explore")
        .field("来源世界", _world_name_by_id(sanctuary.world_id))
        .row(
            ("状态", status_names[sanctuary.status]),
            ("有效期", sanctuary.expires_at.strftime("%m-%d %H:%M")),
        )
    )
    actions = []
    if sanctuary.active:
        traces = sanctuary.traces
        if sanctuary.selected_trace_index is not None:
            traces = tuple(value for value in traces if value.index == sanctuary.selected_trace_index)
        for trace in traces:
            species = current_game_services().content.companions.species.require(trace.definition_id)
            builder.item(
                trace.index,
                species.name,
                FieldSeparator(),
                _ROLE_NAMES[species.role],
                FieldSeparator(),
                "危险相当",
            )
            actions.append(Action(f"companion.trace.{trace.index}", f"追踪 {trace.index}", f"秘境追踪 {trace.index}", behavior="send"))
        actions.append(Action("companion.abandon", "放弃", "放弃秘境", behavior="send", style="secondary"))
    return builder.actions(actions).build()


def _hunt_result(outcome) -> DocumentMessage:
    if outcome.status == "captured" and outcome.companion is not None:
        companion = outcome.companion
        builder = (
            M.document()
            .section("捕获成功", icon="reward")
            .field("来源世界", _world_name_by_id(companion.origin_world_id))
            .field("宠物", f"{companion.reference} {_companion_name(companion)}")
            .row(("品阶", _companion_projector(companion).name(companion.quality_id)), ("等级", f"Lv{companion.level}"))
        )
        if outcome.battle_report is not None:
            builder.field("战报", M.link("查看完整战报", public_url("battle", outcome.battle_report.share_id)))
        return builder.actions((Action("companion.bind", _companion_projector(companion).name("term.companion_bind"), f"伙伴出战 {companion.reference}", behavior="send"),)).build()
    if outcome.status == "defeated":
        builder = M.document().section("追踪失败", icon="combat").line("目标仍停留在原踪迹，恢复后可以再次挑战。")
        if outcome.battle_report is not None:
            builder.field("战报", M.link("查看完整战报", public_url("battle", outcome.battle_report.share_id)))
        return builder.build()
    return _failure(outcome.failure_message or "伙伴追踪没有完成")


def _transfer_confirmation(outcome, overview: CharacterOverview) -> DocumentMessage:
    companion = outcome.companion
    assert companion is not None and outcome.roster is not None
    previous = _preset_index(outcome.previous_preset_id)
    current = _preset_index(overview.loadout.active_preset_id)
    return (
        M.document()
        .section("确认转移伙伴", icon="notice")
        .line(f"{_companion_name(companion)} 当前属于配装 {previous}，将转移到配装 {current}。")
        .actions((Action("companion.bind.transfer", "确认转移", f"companion_bind_transfer_confirm {companion.reference} {outcome.roster.revision}", behavior="send"),))
        .build()
    )


def _bind_result(outcome) -> DocumentMessage:
    if outcome.status in {"bound", "transferred", "already_bound"} and outcome.companion is not None:
        action = _companion_projector(outcome.companion).name("term.companion_bind")
        text = "已经随当前配装出战" if outcome.status != "already_bound" else "本就属于当前配装"
        return M.document().section(f"伙伴{action}", icon="player").line(f"{_companion_name(outcome.companion)} {text}").build()
    return _failure(outcome.failure_message or "伙伴出战没有完成")


def _companion_definition(companion):
    return current_game_services().content.companions.require_definition(
        companion.definition_id
    )


def _companion_name(companion) -> str:
    return _companion_definition(companion).name


def _companion_projector(companion):
    definition = _companion_definition(companion)
    if companion.origin_world_id != definition.origin_world_id:
        raise ValueError("伙伴实例来源世界与内容定义不一致")
    return current_game_services().world_views.require(
        companion.origin_world_id
    ).projector


def _world_name(overview: CharacterOverview) -> str:
    return current_game_services().world_view(overview.character_world).skin.name


def _world_name_by_id(world_id: str) -> str:
    return current_game_services().world_views.require(world_id).skin.name


def _outcome_companion_name(outcome) -> str:
    if outcome.companion is not None:
        return _companion_name(outcome.companion)
    if outcome.definition_id:
        return current_game_services().content.companions.require_definition(
            outcome.definition_id
        ).name
    return "伙伴"


def _current_location(overview: CharacterOverview) -> str | None:
    presence = next(
        (
            value for value in overview.world.presences.values()
            if value.owner_id == overview.character.id
        ),
        None,
    )
    if presence is None:
        return None
    return current_game_services().content.worlds.anchor_at(
        overview.character_world.world_id,
        presence.position,
    )


def _location_command(world_id: str, anchor_id: str, function_id: str) -> str:
    binding = current_game_services().content.worlds.require_binding(
        world_id,
        anchor_id,
    )
    if binding.function_id != function_id:
        raise ValueError(f"地点按钮功能与世界绑定不一致：{world_id}/{anchor_id}")
    return WorldLocationIntent(
        world_id,
        anchor_id,
        function_id,
        binding.version,
    ).command()


def _projector(overview: CharacterOverview):
    return current_game_services().world_view(overview.character_world).projector


def _preset_index(preset_id) -> int | None:
    if preset_id is None:
        return None
    try:
        return LOADOUT_PRESET_IDS.index(preset_id)
    except ValueError:
        return None


def _overview(result: CharacterOverviewResult) -> CharacterOverview | None:
    return result.overview if result.status == "ok" else None


def _operation_id(prefix: str) -> str:
    context = current_message_context()
    if context is None:
        raise RuntimeError("伙伴命令缺少消息上下文")
    return f"{prefix}:{context.identity.evidence_id}"


async def _logged_failure(title: str, character_id: str, exc: Exception) -> None:
    logger.opt(colors=True, exception=exc).error(
        C.join(C.fail(title), C.kv("character", character_id))
    )
    await send_game_reply(_failure("当前操作没有完成，请稍后重试"))


def _failure(message: str) -> DocumentMessage:
    return M.document().section("伙伴", icon="notice").line(message).build()


def _unavailable() -> DocumentMessage:
    return _failure("当前没有读取到角色状态，请稍后重试")


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


__all__ = [
    "bind_companion",
    "confirm_abandon",
    "confirm_bind_transfer",
    "confirm_farewell",
    "gift_person",
    "hunt_companion",
    "join_person",
    "preview_abandon",
    "preview_farewell",
    "unbind_companion",
    "view_companions",
    "view_people",
    "view_sanctuary",
]
