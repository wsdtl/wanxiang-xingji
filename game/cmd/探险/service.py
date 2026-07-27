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
from game.features.exploration.rewards import available_backpack_space
from game.features.world_travel import WorldLocationIntent, WorldTravelResult
from game.core.gameplay import equipment_state_from_instance, weapon_state_from_instance
from game.rules.exploration import (
    ExplorationEncounterKind,
    ExplorationRestReason,
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
from ..presentation import (
    active_exploration_status_text,
    activity_block_feedback,
    health_depleted_feedback,
)
from ..world_location import (
    current_world_location_action,
    current_world_location_command,
    current_world_location_name,
    resolve_current_world_location,
)


async def view_exploration(current: CurrentCharacterResult) -> None:
    character = current_character_value(current)
    if character is None:
        await send_game_reply(
            _unavailable(Action("exploration.character", "查看角色", "我的角色"))
        )
        return
    try:
        services = current_game_services()
        logical_time = command_time()
        state = await asyncio.to_thread(
            services.exploration.load,
            character.id,
            logical_time=logical_time,
        )
        overview = await asyncio.to_thread(services.load_character_overview, character)
        view = services.world_view(current.character_world)
        await send_game_reply(_exploration_message(state, overview.overview, view))
    except Exception as exc:
        await _failed(
            "探险状态查询失败",
            character.id,
            exc,
            Action("exploration.retry", "重试", "探险"),
        )


async def move(message: str, current: CurrentCharacterResult) -> None:
    character = current_character_value(current)
    if character is None:
        await send_game_reply(
            _unavailable(Action("travel.character", "查看角色", "我的角色"))
        )
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
            .action(Action("travel.map", "查看地图", "地图", behavior="callback"))
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
        await _failed(
            "探险移动失败",
            character.id,
            exc,
            Action("travel.failure.map", "查看地图", "地图"),
        )


async def start(current: CurrentCharacterResult) -> None:
    await _operate(
        current,
        "start",
        _start_message,
        "开始探险失败",
        Action("exploration.start.failure", "查看探险", "探险"),
        include_settings=True,
    )


async def stop(current: CurrentCharacterResult) -> None:
    await _operate(
        current,
        "stop",
        _stop_message,
        "停止探险失败",
        Action("exploration.stop.failure", "查看探险", "探险"),
    )


async def summary(current: CurrentCharacterResult) -> None:
    character = current_character_value(current)
    if character is None:
        await send_game_reply(
            _unavailable(Action("exploration-summary.character", "查看角色", "我的角色"))
        )
        return
    try:
        services = current_game_services()
        logical_time = command_time()
        result = await asyncio.to_thread(
            services.exploration.load,
            character.id,
            logical_time=logical_time,
        )
        overview_result = await asyncio.to_thread(
            services.load_character_overview,
            character,
        )
        if overview_result.status != "ok" or overview_result.overview is None:
            await send_game_reply(
                _unavailable(
                    Action(
                        "exploration-summary.overview",
                        "查看角色",
                        "我的角色",
                    )
                )
            )
            return
        view = services.world_view(overview_result.overview.character_world)
        report = (
            services.battle_reports.reference(
                exploration_battle_report_id(
                    result.state.session_id,
                    services.content.catalog.report.content_fingerprint,
                )
            )
            if result.state is not None
            else None
        )
        await send_game_reply(
            _summary_message(result, overview_result.overview, view, report)
        )
    except Exception as exc:
        await _failed(
            "探险总结查询失败",
            character.id,
            exc,
            Action("exploration-summary.retry", "重试", "探险总结"),
        )


async def _operate(
    current,
    method_name,
    presenter,
    log_message,
    failure_recovery: Action,
    *,
    include_settings: bool = False,
) -> None:
    character = current_character_value(current)
    if character is None:
        await send_game_reply(
            _unavailable(Action("exploration-operation.character", "查看角色", "我的角色"))
        )
        return
    try:
        services = current_game_services()
        settings = (
            await asyncio.to_thread(
                services.load_character_settings,
                character.id,
            )
            if include_settings
            else None
        )
        method = getattr(services.exploration, method_name)
        result = await asyncio.to_thread(
            method,
            character.id,
            logical_time=command_time(),
        )
        view = services.world_view(current.character_world)
        if include_settings:
            await send_game_reply(presenter(result, view, settings))
        else:
            await send_game_reply(presenter(result, view))
    except Exception as exc:
        await _failed(log_message, character.id, exc, failure_recovery)


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
    if overview is not None:
        builder.row(
            ("自动用药", _switch_text(overview.settings.auto_use_medicine)),
            ("自动休整", _switch_text(overview.settings.auto_rest)),
        )
    if result.state is not None:
        _append_stopped_details(builder, result.state, overview)
    if result.state is not None and result.state.status is ExplorationStatus.RUNNING:
        builder.field("下次结算", _time(result.state.next_batch_at))
    elif result.state is not None and result.state.status is ExplorationStatus.RESTING:
        builder.field("休整原因", _rest_reason_text(result.state.rest_reason))
        if result.state.rest_completes_at is not None:
            builder.field("休整完成", _time(result.state.rest_completes_at))
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
        (
            services.content.exploration_regions.require(binding.content_ref),
            binding,
        )
        for binding in bindings
        if binding.content_ref is not None
    )
    regular = [
        value
        for value in regions
        if value[0].kind.value == "regular"
    ]
    for index, (region, binding) in enumerate(regular, start=1):
        builder.item(
            index,
            M.command(
                current_world_location_name(view, binding),
                current_world_location_command(view, binding),
            ),
            f" | {_levels(region.minimum_enemy_level, region.maximum_enemy_level)}",
        )
    builder.section("特殊区域", icon="notice")
    special = [
        value
        for value in regions
        if value[0].kind.value != "regular"
    ]
    for index, (region, binding) in enumerate(special, start=1):
        builder.item(
            index,
            M.command(
                current_world_location_name(view, binding),
                current_world_location_command(view, binding),
            ),
            f" | {_focus(region.kind.value)} | {_levels(region.minimum_enemy_level, region.maximum_enemy_level)}",
        )
    actions = []
    if result.state is not None and result.state.active:
        actions.append(Action("exploration.stop", "停止", "停止探险", behavior="callback"))
        actions.append(
            Action(
                "exploration.summary",
                "查看总结",
                "探险总结",
                behavior="callback",
                style="secondary",
            )
        )
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
            actions.append(Action("exploration.start", "开始", "开始探险", behavior="callback"))
    actions.append(Action("exploration.move", "前往", "前往 ", behavior="fill", style="secondary"))
    return builder.actions(tuple(actions)).build()


def _movement_message(result: WorldTravelResult, view) -> DocumentMessage:
    builder = M.document().section(f"前往·{view.skin.name}", icon="world")
    if result.activity_block is not None:
        feedback = activity_block_feedback(result.activity_block, "移动")
        return builder.line(feedback.text).action(feedback.recovery).build()
    if result.status == "moved":
        resolved = current_game_services().content.worlds.resolve(
            view.world.id,
            result.anchor_id,
        )
        return (
            builder.field("抵达", _anchor_name(result.anchor_id, view))
            .action(current_world_location_action(resolved.binding))
            .build()
        )
    if result.status == "already_there":
        resolved = current_game_services().content.worlds.resolve(
            view.world.id,
            result.anchor_id,
        )
        return (
            builder.field("位置", _anchor_name(result.anchor_id, view))
            .line("已经在这里")
            .action(current_world_location_action(resolved.binding))
            .build()
        )
    if result.status in {"stale_world", "stale_binding"}:
        return (
            builder.line("这条地点入口已经失效，请重新打开当前区域")
            .action(Action("exploration.regions", "重新选择", "探险"))
            .build()
        )
    if result.status == "unavailable":
        return (
            builder.line("当前世界没有这个地点")
            .action(Action("travel.map", "查看地图", "地图", behavior="callback"))
            .build()
        )
    return (
        builder.line("本次移动没有完成")
        .action(Action("travel.map", "查看地图", "地图", behavior="callback"))
        .build()
    )


def _start_message(
    result: ExplorationOperationResult,
    view,
    settings=None,
) -> DocumentMessage:
    builder = M.document().section("开始探险", icon="combat")
    if result.activity_block is not None:
        feedback = activity_block_feedback(result.activity_block, "开始探险")
        return builder.line(feedback.text).action(feedback.recovery).build()
    if result.status == "started" and result.state is not None:
        builder.field("区域", _name(result.state.location_id, view)).field(
            "首次结算",
            _time(result.state.next_batch_at),
        )
        if settings is not None:
            builder.row(
                ("自动用药", _switch_text(settings.auto_use_medicine)),
                ("自动休整", _switch_text(settings.auto_rest)),
            )
        return (
            builder.line(
                f"之后每 10 分钟自动结算，最多 {MAX_EXPLORATION_BATCHES} 批；"
                "自动休整开启时，战败或资源过低会在完全恢复后续行。"
            )
            .actions(
                (
                    Action("exploration.stop", "停止", "停止探险", behavior="callback"),
                    Action(
                        "exploration.summary",
                        "查看总结",
                        "探险总结",
                        behavior="callback",
                        style="secondary",
                    ),
                )
            )
            .build()
        )
    if result.status == "already_running":
        if settings is not None:
            builder.row(
                ("自动用药", _switch_text(settings.auto_use_medicine)),
                ("自动休整", _switch_text(settings.auto_rest)),
            )
        return (
            builder.line("当前已经在探险")
            .actions(
                (
                    Action("exploration.stop", "停止", "停止探险"),
                    Action(
                        "exploration.summary",
                        "查看总结",
                        "探险总结",
                        style="secondary",
                    ),
                )
            )
            .build()
        )
    if result.status == "health_depleted":
        feedback = health_depleted_feedback("开始探险")
        return builder.line(feedback.text).actions(feedback.recoveries).build()
    if result.status == "not_in_region":
        return (
            builder.line("当前位置不是探险区域")
            .action(Action("exploration.regions", "查看区域", "探险", style="secondary"))
            .build()
        )
    return (
        builder.line("本次探险没有开始")
        .action(Action("exploration.start.back", "查看探险", "探险"))
        .build()
    )


def _stop_message(result: ExplorationOperationResult, view) -> DocumentMessage:
    builder = M.document().section("停止探险", icon="combat")
    if result.status == "stopped" and result.state is not None:
        return (
            builder.field("已结算", f"{result.state.completed_batches} 批")
            .line("已经停止")
            .actions(
                (
                    Action("exploration.summary", "探险总结", "探险总结"),
                    Action(
                        "exploration.dimension_shift",
                        "界门",
                        "跃迁",
                        style="secondary",
                    ),
                )
            )
            .build()
        )
    if result.status == "already_stopped":
        return (
            builder.line("当前探险已经停止")
            .actions(
                (
                    Action("exploration.summary", "探险总结", "探险总结"),
                    Action(
                        "exploration.dimension_shift",
                        "界门",
                        "跃迁",
                        style="secondary",
                    ),
                )
            )
            .build()
        )
    if result.status == "not_started":
        return (
            builder.line("当前没有探险记录")
            .action(Action("exploration.regions", "查看区域", "探险"))
            .build()
        )
    return (
        builder.line("本次停止没有完成")
        .action(Action("exploration.stop.back", "查看探险", "探险"))
        .build()
    )


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
            .action(Action("exploration.regions", "查看区域", "探险"))
            .build()
        )
    state = result.state
    builder = (
        M.document()
        .section("探险总结", icon="combat")
        .field("世界", view.skin.name)
        .row(("区域", _name(state.location_id, view)), ("状态", _status_text(result)))
    )
    if overview is not None:
        builder.row(
            ("自动用药", _switch_text(overview.settings.auto_use_medicine)),
            ("自动休整", _switch_text(overview.settings.auto_rest)),
        )
    _append_stopped_details(builder, state, overview)
    builder.row(
        ("批次", state.completed_batches),
        ("胜负", f"{state.victories}胜 {state.defeats}负"),
    ).row(
        ("经验", f"+{state.character_experience}"),
        ("武器经验", f"+{state.weapon_experience}"),
    ).field(
        "伙伴经验", f"+{state.companion_experience}"
    ).row(
        ("武器", state.weapon_drops), ("装备", state.equipment_drops)
    ).row(
        ("战利品", state.trophy_drops), ("药物掉落", state.medicine_drops)
    ).row(
        ("休整次数", state.rest_count), ("累计休整", _duration(_rest_seconds(state)))
    ).field(
        "抽奖签", state.draw_ticket_drops
    ).field(
        "战利品估价", f"{state.trophy_value} {_name(PRIMARY_CURRENCY_ID, view)}"
    )
    if state.status is ExplorationStatus.RESTING:
        builder.field("休整原因", _rest_reason_text(state.rest_reason))
        if state.rest_completes_at is not None:
            builder.field("休整完成", _time(state.rest_completes_at))
        builder.field("下次结算", _time(state.next_batch_at))
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
    actions = []
    if state.active:
        actions.append(Action("exploration.stop", "停止探险", "停止探险"))
    else:
        actions.extend(
            (
                Action(
                    "exploration.recycle_trophies",
                    "回收",
                    "回收战利品",
                    behavior="callback",
                ),
                Action(
                    "exploration.regions",
                    "查看区域",
                    "探险",
                    style="secondary",
                ),
            )
        )
    return builder.actions(actions).build()


def _status_text(result: ExplorationOperationResult) -> str:
    state = result.state
    if state is None:
        return "未开始"
    active_text = active_exploration_status_text(state)
    if active_text is not None:
        return active_text
    return "已停止"


def _append_stopped_details(builder, state, overview) -> None:
    if state.status is not ExplorationStatus.STOPPED:
        return
    builder.field("停止原因", _stop_reason_text(state.stop_reason))
    if state.stop_reason is ExplorationStopReason.CAPACITY_FULL and overview is not None:
        builder.field("背包空间", _backpack_space_text(overview))


def _stop_reason_text(reason: ExplorationStopReason | None) -> str:
    return {
        ExplorationStopReason.MANUAL: "主动停止",
        ExplorationStopReason.DEFEATED: "战败",
        ExplorationStopReason.CAPACITY_FULL: "背包空间不足",
        ExplorationStopReason.BATCH_LIMIT: f"达到 {MAX_EXPLORATION_BATCHES} 批上限",
        ExplorationStopReason.INVALID_LOCATION: "位置失效",
        ExplorationStopReason.RECOVERY_INVALID: "休整异常",
    }.get(reason, "未知原因")


def _backpack_space_text(overview) -> str:
    remaining = available_backpack_space(
        overview.inventory,
        current_game_services().content.catalog.items,
    )
    if remaining is None:
        return "无限"
    maximum = next(
        value.maximum_space
        for value in overview.inventory.containers.values()
        if value.kind == "container.backpack"
    )
    if maximum is None:
        return "无限"
    return f"{maximum - remaining}/{maximum}"


def _rest_reason_text(reason: ExplorationRestReason | None) -> str:
    return {
        ExplorationRestReason.DEFEATED: "本批战败",
        ExplorationRestReason.LOW_RESOURCES: "资源过低",
    }.get(reason, "等待恢复")


def _rest_seconds(state) -> float:
    seconds = state.rest_seconds
    if (
        state.status is ExplorationStatus.RESTING
        and state.rest_started_at is not None
        and state.rest_completes_at is not None
    ):
        current = command_time()
        effective = min(max(current, state.rest_started_at), state.rest_completes_at)
        seconds += (effective - state.rest_started_at).total_seconds()
    return seconds


def _duration(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, remainder = divmod(total, 60)
    if minutes and remainder:
        return f"{minutes}分{remainder}秒"
    if minutes:
        return f"{minutes}分钟"
    return f"{remainder}秒"


def _switch_text(enabled: bool) -> str:
    return "开启" if enabled else "关闭"


def _resolve_location(value: str, view) -> tuple[str | None, WorldLocationIntent | None]:
    services = current_game_services()
    intent = WorldLocationIntent.parse(value)
    if intent is not None:
        return intent.anchor_id, intent
    binding = resolve_current_world_location(value, view, services.content.worlds)
    if binding is not None:
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


async def _failed(
    message: str,
    character_id: str,
    exc: Exception,
    recovery: Action,
) -> None:
    await send_command_failure(
        message,
        character_id,
        exc,
        M.document()
        .section("探险", icon="world")
        .line("当前操作没有完成，请稍后重试")
        .action(recovery)
        .build(),
    )


def _unavailable(recovery: Action) -> DocumentMessage:
    return (
        M.document()
        .section("探险", icon="world")
        .line("当前没有可用角色")
        .action(recovery)
        .build()
    )


__all__ = [
    "move",
    "start",
    "stop",
    "summary",
    "view_exploration",
]
