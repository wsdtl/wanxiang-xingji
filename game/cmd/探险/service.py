"""探险命令的参数解析、应用服务调用与富文本展示。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from game.app import CurrentCharacterResult, current_game_services
from game.content.catalog import PRIMARY_CURRENCY_ID
from game.features.exploration import (
    MAX_EXPLORATION_BATCHES,
    ExplorationOperationResult,
    exploration_battle_report_id,
)
from game.features.world_travel import WorldLocationIntent, WorldTravelResult
from game.core.gameplay import equipment_state_from_instance, weapon_state_from_instance
from game.rules.exploration import (
    ExplorationEncounterKind,
    ExplorationRewardKind,
    ExplorationStatus,
    ExplorationStopReason,
)
from game.rules.item import asset_reference
from launch import config
from launch.paths import public_url
from message import Action, DocumentMessage, M

from ..command_helpers import command_time, current_character_value
from ..reply import send_command_failure, send_game_reply
from ..presentation import current_action_action


async def view_exploration(current: CurrentCharacterResult) -> None:
    character = current_character_value(current)
    if character is None:
        await send_game_reply(_unavailable())
        return
    try:
        services = current_game_services()
        state, overview = await asyncio.gather(
            asyncio.to_thread(
                services.exploration.load,
                character.id,
                logical_time=command_time(),
            ),
            asyncio.to_thread(services.load_character_overview, character),
        )
        view = services.world_view(current.character_world)
        await send_game_reply(_exploration_message(state, overview.overview, view))
    except Exception as exc:
        await _failed("探险状态查询失败", character.id, exc)


async def move(message: str, current: CurrentCharacterResult) -> None:
    character = current_character_value(current)
    if character is None:
        await send_game_reply(_unavailable())
        return
    services = current_game_services()
    view = services.world_view(current.character_world)
    requested = str(message or "").strip()
    if not requested:
        await view_exploration(current)
        return
    location_id, intent = _resolve_location(requested, view)
    if location_id is None:
        await send_game_reply(
            M.document()
            .section("前往", icon="world")
            .line("没有找到这个地点")
            .note("发送：地图 地点名称")
            .build()
        )
        return
    try:
        result = await asyncio.to_thread(
            services.world_travel.move,
            character.id,
            location_id,
            logical_time=command_time(),
            intent=intent,
        )
        await send_game_reply(_movement_message(result, view))
    except Exception as exc:
        await _failed("探险移动失败", character.id, exc)


async def start(current: CurrentCharacterResult) -> None:
    await _operate(current, "start", _start_message, "开始探险失败")


async def stop(current: CurrentCharacterResult) -> None:
    await _operate(current, "stop", _stop_message, "停止探险失败")


async def summary(current: CurrentCharacterResult) -> None:
    character = current_character_value(current)
    if character is None:
        await send_game_reply(_unavailable())
        return
    try:
        services = current_game_services()
        result, overview_result = await asyncio.gather(
            asyncio.to_thread(
                services.exploration.load,
                character.id,
                logical_time=command_time(),
            ),
            asyncio.to_thread(services.load_character_overview, character),
        )
        if overview_result.status != "ok" or overview_result.overview is None:
            await send_game_reply(_unavailable())
            return
        view = services.world_view(overview_result.overview.character_world)
        report = (
            services.battle_reports.reference(
                exploration_battle_report_id(result.state.session_id)
            )
            if result.state is not None
            else None
        )
        await send_game_reply(
            _summary_message(result, overview_result.overview, view, report)
        )
    except Exception as exc:
        await _failed("探险总结查询失败", character.id, exc)


async def _operate(current, method_name, presenter, log_message) -> None:
    character = current_character_value(current)
    if character is None:
        await send_game_reply(_unavailable())
        return
    try:
        method = getattr(current_game_services().exploration, method_name)
        result = await asyncio.to_thread(
            method,
            character.id,
            logical_time=command_time(),
        )
        view = current_game_services().world_view(current.character_world)
        await send_game_reply(presenter(result, view))
    except Exception as exc:
        await _failed(log_message, character.id, exc)


def _exploration_message(result, overview, view) -> DocumentMessage:
    services = current_game_services()
    projector = view.projector
    anchor_id = None
    location_id = None
    if overview is not None:
        presence = next(
            (
                value
                for value in overview.world.presences.values()
                if value.owner_id == overview.character.id
            ),
            None,
        )
        anchor_id = (
            services.content.worlds.anchor_at(
                overview.character_world.world_id,
                presence.position,
            )
            if presence
            else None
        )
        location_id = (
            services.content.worlds.resolve(
                overview.character_world.world_id,
                anchor_id,
            ).display_id
            if anchor_id is not None
            else None
        )
    builder = M.document().section(f"探险·{view.skin.name}", icon="world")
    builder.row(
        ("世界", view.skin.name),
        ("位置", projector.name(location_id) if location_id else "未知"),
        ("状态", _status_text(result)),
    )
    if result.state is not None and result.state.status is ExplorationStatus.RUNNING:
        builder.field("下次结算", _time(result.state.next_batch_at))
    builder.section("常规区域", icon="combat")
    bindings = (
        services.content.worlds.bindings_for_world(
            overview.character_world.world_id,
            function_id="location.function.exploration",
        )
        if overview is not None
        else ()
    )
    regions = tuple(
        services.content.exploration_regions.require(binding.content_ref)
        for binding in bindings
        if binding.content_ref is not None
    )
    regular = [
        value
        for value in regions
        if value.kind.value == "regular"
    ]
    for index, region in enumerate(regular, start=1):
        builder.item(
            index,
            f"{projector.name(region.location_id)} | {_levels(region.minimum_enemy_level, region.maximum_enemy_level)}",
        )
    builder.section("特殊区域", icon="notice")
    special = [
        value
        for value in regions
        if value.kind.value != "regular"
    ]
    for index, region in enumerate(special, start=1):
        builder.item(
            index,
            f"{projector.name(region.location_id)} | {_focus(region.kind.value)} | {_levels(region.minimum_enemy_level, region.maximum_enemy_level)}",
        )
    actions = []
    if result.state is not None and result.state.status is ExplorationStatus.RUNNING:
        actions.append(Action("exploration.stop", "停止", "停止探险", behavior="send"))
    elif anchor_id is not None:
        try:
            resolved = services.content.worlds.resolve(
                overview.character_world.world_id,
                anchor_id,
                function_id="location.function.exploration",
            ) if overview is not None else None
        except KeyError:
            resolved = None
        if resolved is not None and resolved.binding.content_ref is not None:
            actions.append(Action("exploration.start", "开始", "开始探险", behavior="send"))
    actions.append(Action("exploration.move", "前往", "前往 ", behavior="fill", style="secondary"))
    return builder.actions(tuple(actions)).build()


def _movement_message(result: WorldTravelResult, view) -> DocumentMessage:
    builder = M.document().section(f"前往·{view.skin.name}", icon="world")
    if result.status == "moved":
        return builder.field("抵达", _anchor_name(result.anchor_id, view)).build()
    if result.status == "already_there":
        return builder.field("位置", _anchor_name(result.anchor_id, view)).line("已经在这里").build()
    if result.status == "main_action_occupied":
        return (
            builder.line("当前主要行动进行中，结束后才能移动")
            .action(current_action_action())
            .build()
        )
    if result.status in {"stale_world", "stale_binding"}:
        return builder.line("这条地点按钮已经失效，请重新打开当前世界页面").build()
    if result.status == "unavailable":
        return builder.line("当前世界没有这个地点").build()
    return builder.line("本次移动没有完成").build()


def _start_message(result: ExplorationOperationResult, view) -> DocumentMessage:
    builder = M.document().section("开始探险", icon="combat")
    if result.status == "started" and result.state is not None:
        return (
            builder.field("区域", _name(result.state.location_id, view))
            .field("首次结算", _time(result.state.next_batch_at))
            .line(f"之后每 10 分钟自动结算，最多 {MAX_EXPLORATION_BATCHES} 批，或直到停止、战败、容量已满。")
            .actions((Action("exploration.stop", "停止", "停止探险", behavior="send"),))
            .build()
        )
    if result.status == "already_running":
        return builder.line("当前已经在探险").build()
    if result.status == "health_depleted":
        return (
            builder.line("血气已经归零，恢复后才能开始探险")
            .actions(
                (
                    Action("exploration.inventory", "查看纳戒", "纳戒", style="secondary"),
                    Action("exploration.rest", "休息", "休息"),
                )
            )
            .build()
        )
    if result.status == "main_action_occupied":
        return (
            builder.line("当前正在进行其他主要行动")
            .action(current_action_action())
            .build()
        )
    if result.status == "not_in_region":
        return (
            builder.line("当前位置不是探险区域")
            .action(Action("exploration.regions", "查看区域", "探险", style="secondary"))
            .build()
        )
    return builder.line("本次探险没有开始").build()


def _stop_message(result: ExplorationOperationResult, view) -> DocumentMessage:
    builder = M.document().section("停止探险", icon="combat")
    if result.status == "stopped" and result.state is not None:
        return (
            builder.field("已结算", f"{result.state.completed_batches} 批")
            .line("已经停止")
            .build()
        )
    if result.status == "already_stopped":
        return builder.line("当前探险已经停止").build()
    if result.status == "not_started":
        return builder.line("当前没有探险记录").build()
    return builder.line("本次停止没有完成").build()


def _summary_message(
    result: ExplorationOperationResult,
    overview,
    view,
    battle_report=None,
) -> DocumentMessage:
    if result.state is None:
        return (
            M.document()
            .section("探险总结", icon="combat")
            .line("还没有探险记录")
            .build()
        )
    state = result.state
    builder = (
        M.document()
        .section("探险总结", icon="combat")
        .field("世界", view.skin.name)
        .row(("区域", _name(state.location_id, view)), ("状态", _status_text(result)))
        .row(("批次", state.completed_batches), ("胜负", f"{state.victories}胜 {state.defeats}负"))
        .row(("经验", f"+{state.character_experience}"), ("武器经验", f"+{state.weapon_experience}"))
        .field("伙伴经验", f"+{state.companion_experience}")
        .row(("武器", state.weapon_drops), ("装备", state.equipment_drops))
        .row(("战利品", state.trophy_drops), ("药物掉落", state.medicine_drops))
        .field("抽奖签", state.draw_ticket_drops)
        .field("战利品估价", f"{state.trophy_value} {_name(PRIMARY_CURRENCY_ID, view)}")
    )
    if battle_report is not None:
        builder.field(
            "战报",
            M.link(
                "查看完整战报",
                public_url("battle", battle_report.share_id),
            ),
        )
    last = state.last_result
    if last is not None:
        builder.section("最近一批", icon="inventory")
        if last.plan.encounter_kind is ExplorationEncounterKind.EMPTY:
            builder.line("没有遭遇")
        else:
            enemies = (
                tuple(last.plan.encounter.enemies)
                if last.plan.encounter is not None
                else ()
            )
            builder.field(
                "遭遇",
                ", ".join(view.enemy_projector.enemy(enemy).name for enemy in enemies)
                or "未知敌人",
            )
            builder.field("结果", "胜利" if last.victory else "平局" if last.draw else "战败")
            if last.rewards:
                builder.section("最近获得", icon="inventory")
                for reference in last.rewards:
                    builder.line(_reward_line(reference, overview, view))
            if last.medicines_used:
                builder.field(
                    "自动用药",
                    ", ".join(
                        _reward_name(reference, overview, view)
                        for reference in last.medicines_used
                    ),
                )
    if state.medicine_drops:
        builder.note("药物数量为累计掉落；开启自动用药时，批次间消耗后可能不再留存在纳戒。")
    return builder.actions(
        (Action("exploration.recycle_trophies", "回收", "回收战利品", behavior="send"),)
    ).build()


def _status_text(result: ExplorationOperationResult) -> str:
    state = result.state
    if state is None:
        return "未开始"
    if state.status is ExplorationStatus.RUNNING:
        return "进行中"
    return {
        ExplorationStopReason.MANUAL: "已停止",
        ExplorationStopReason.DEFEATED: "战败停止",
        ExplorationStopReason.CAPACITY_FULL: "容量已满",
        ExplorationStopReason.BATCH_LIMIT: f"达到 {MAX_EXPLORATION_BATCHES} 批上限",
        ExplorationStopReason.INVALID_LOCATION: "位置失效",
    }.get(state.stop_reason, "已停止")


def _resolve_location(value: str, view) -> tuple[str | None, WorldLocationIntent | None]:
    services = current_game_services()
    intent = WorldLocationIntent.parse(value)
    if intent is not None:
        return intent.anchor_id, intent
    normalized = value.casefold()
    for binding in services.content.worlds.bindings_for_world(view.world.id):
        display_id = binding.display_ref or binding.anchor_id
        if value == binding.anchor_id or view.projector.name(display_id).casefold() == normalized:
            return binding.anchor_id, None
    return None, None


def _focus(kind: str) -> str:
    return {
        "weapon_focus": "武器偏向",
        "equipment_focus": "装备偏向",
        "boss_focus": "强敌偏向",
    }[kind]


def _levels(low: int, high: int) -> str:
    return f"Lv{low}" if low == high else f"Lv{low}-{high}"


def _name(definition_id: str, view) -> str:
    return view.projector.name(definition_id)


def _anchor_name(anchor_id: str, view) -> str:
    resolved = current_game_services().content.worlds.resolve(view.world.id, anchor_id)
    return view.projector.name(resolved.display_id)


def _reward_name(reference, overview, view) -> str:
    if reference.kind is ExplorationRewardKind.ITEM:
        return f"{view.projector.name(reference.definition_id)} x{reference.quantity}"
    instance = overview.inventory.instances.get(reference.asset_id)
    if instance is None:
        return view.projector.name(reference.definition_id)
    if reference.kind is ExplorationRewardKind.WEAPON:
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


def _reward_line(reference, overview, view):
    if reference.kind is ExplorationRewardKind.ITEM:
        return f"{view.projector.name(reference.definition_id)} x{reference.quantity}"
    instance = overview.inventory.instances.get(reference.asset_id)
    if instance is None:
        return view.projector.name(reference.definition_id)
    token = asset_reference(
        overview.inventory,
        instance,
        current_game_services().content.catalog.items,
    )
    return M.command(
        _reward_name(reference, overview, view),
        f"查看 {token}",
    )


def _time(value: datetime) -> str:
    return value.astimezone(ZoneInfo(config.project.timezone)).strftime("%m-%d %H:%M")


async def _failed(message: str, character_id: str, exc: Exception) -> None:
    await send_command_failure(
        message,
        character_id,
        exc,
        M.document().section("探险", icon="world").line("当前操作没有完成，请稍后重试").build()
    )


def _unavailable() -> DocumentMessage:
    return M.document().section("探险", icon="world").line("当前没有可用角色").build()


__all__ = [
    "move",
    "start",
    "stop",
    "summary",
    "view_exploration",
]
