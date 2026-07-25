"""行纪查询、地点解析与永久排行榜消息展示。"""

from __future__ import annotations

import asyncio

from game.app import CharacterOverview, CharacterOverviewResult, current_game_services
from game.content.catalog import PRIMARY_CURRENCY_ID
from game.content.catalog.world import LOCATION_FUNCTION_EXPLORATION
from game.content.catalog.world_progress import WORLD_PROGRESS_DEFINITION
from message import Action, DocumentMessage, M
from message.schema import FieldSeparator

from ..command_helpers import command_time
from ..reply import send_command_failure, send_game_reply


async def view_world_progress(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_failure("当前没有读取到角色状态，请稍后重试"))
        return
    try:
        services = current_game_services()
        requested = str(message or "").strip()
        requested_world = services.world_views.resolve(requested) if requested else None
        view = requested_world or services.world_view(overview.character_world)
        progress = await asyncio.to_thread(
            services.world_progress.view,
            overview.character.id,
            view.world.id,
        )
        if requested and requested_world is None:
            reply = _region_detail(requested, progress, view)
        else:
            reply = _world_overview(progress, view)
    except (KeyError, TypeError, ValueError) as exc:
        reply = _failure(
            str(exc),
            Action("progress.back", "返回行纪", "行纪", style="secondary"),
        )
    except Exception as exc:
        await send_command_failure(
            "行纪查询失败",
            overview.character.id,
            exc,
            _failure("当前没有读取到行纪，请稍后重试"),
        )
        return
    await send_game_reply(reply)


async def view_world_progress_ranking(
    message: str,
    result: CharacterOverviewResult,
) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_failure("当前没有读取到角色状态，请稍后重试"))
        return
    try:
        services = current_game_services()
        requested = str(message or "").strip()
        view = services.world_views.resolve(requested) if requested else None
        if requested and view is None:
            raise ValueError("没有找到这个世界")
        ranking = await asyncio.to_thread(
            services.world_progress.ranking_view,
            overview.character.id,
            world_id=view.world.id if view else None,
            logical_time=command_time(),
            limit=10,
        )
        reply = _ranking(ranking, view)
    except (KeyError, TypeError, ValueError) as exc:
        reply = _failure(
            str(exc),
            Action("progress-ranking.back", "返回行纪", "行纪", style="secondary"),
        )
    except Exception as exc:
        await send_command_failure(
            "行纪排行查询失败",
            overview.character.id,
            exc,
            _failure("当前没有读取到行纪排行，请稍后重试"),
        )
        return
    await send_game_reply(reply)


def _world_overview(progress, view) -> DocumentMessage:
    services = current_game_services()
    builder = (
        M.document()
        .section(f"行纪·{view.skin.name}", icon="world")
        .row(
            ("世界", view.skin.name),
            ("总进度", f"{progress.percent}%"),
            ("完成", f"{progress.completed_regions}/{len(progress.regions)}"),
        )
        .section("区域记载", icon="combat")
    )
    for region in progress.regions:
        name = _region_name(services, view, region.region_id)
        builder.line(
            "[完成] " if region.completed else "",
            M.command(name, f"行纪 {name}"),
            FieldSeparator(),
            f"{region.percent}%",
        )
    world_complete = progress.completed_regions == len(progress.regions)
    if progress.world_completion_reward_claimed:
        world_reward_status = "已获得 " + _world_completion_reward_text(view)
    elif world_complete:
        world_reward_status = "待补发 " + _world_completion_reward_text(view)
    else:
        world_reward_status = "完成全部区域后获得 " + _world_completion_reward_text(view)
    builder.field(
        "世界圆满",
        world_reward_status,
    )
    return builder.note("发送：行纪 地点名称，可查看详细记载").build()


def _region_detail(requested: str, progress, view) -> DocumentMessage:
    services = current_game_services()
    display_id = view.projector.resolve_alias(requested)
    binding = (
        services.content.worlds.binding_for_display(view.world.id, display_id)
        if display_id is not None
        else None
    )
    if binding is None or binding.function_id != LOCATION_FUNCTION_EXPLORATION:
        return _failure("当前世界没有这处行纪区域")
    region = progress.require_region(binding.content_ref)
    next_stage = next(
        (value for value in (25, 50, 75, 100) if value > region.percent),
        None,
    )
    builder = (
        M.document()
        .section(view.projector.name(display_id), icon="combat")
        .field("世界", view.skin.name)
        .row(
            ("进度", f"{region.points}/{region.maximum_points} ({region.percent}%)"),
            ("胜利", str(region.victories)),
        )
    )
    builder.section("阶段奖励", icon="inventory")
    for milestone in WORLD_PROGRESS_DEFINITION.milestones:
        status = "已得" if milestone.percent in region.claimed_milestones else "未得"
        builder.line(
            f"{milestone.percent}% [{status}]",
            FieldSeparator(),
            _milestone_reward_text(milestone, view),
        )
    if next_stage is None:
        builder.note("这处区域的行纪已经写至圆满。")
    else:
        builder.note(f"距离下一阶段还差 {next_stage - region.percent}%")
    return (
        builder.action(
            Action("progress.back", "返回行纪", "行纪", style="secondary")
        ).build()
    )


def _ranking(ranking, view) -> DocumentMessage:
    title = f"{view.skin.name}行纪排行" if view is not None else "诸界行纪排行"
    builder = M.document().section(title, icon="world")
    if not ranking.entries:
        return builder.line("尚无人留下行纪。").build()
    for entry in ranking.entries:
        builder.line(
            f"{entry.rank}. ",
            entry.character_name,
            FieldSeparator(),
            f"{entry.points}点",
            FieldSeparator(),
            f"圆满{entry.completed_regions}",
        )
    if ranking.own_entry is not None:
        entry = ranking.own_entry
        builder.section("我的位次", icon="player").line(
            f"{entry.rank}. ",
            entry.character_name,
            FieldSeparator(),
            f"{entry.points}点",
            FieldSeparator(),
            f"圆满{entry.completed_regions}",
        )
    return builder.note("排行永久累计，只记录共同历史，不发放名次奖励").build()


def _region_name(services, view, region_id: str) -> str:
    binding = next(
        value
        for value in services.content.worlds.bindings_for_world(
            view.world.id,
            function_id=LOCATION_FUNCTION_EXPLORATION,
        )
        if value.content_ref == region_id
    )
    return view.projector.name(binding.display_ref)


def _milestone_reward_text(milestone, view) -> str:
    values = [
        f"{milestone.currency_amount} {view.projector.name(PRIMARY_CURRENCY_ID)}"
    ]
    values.extend(
        f"{view.projector.name(reward.definition_id)} x{reward.quantity}"
        for reward in milestone.item_rewards
    )
    return "、".join(values)


def _world_completion_reward_text(view) -> str:
    return "、".join(
        f"{view.projector.name(reward.definition_id)} x{reward.quantity}"
        for reward in WORLD_PROGRESS_DEFINITION.world_completion_rewards
    )


def _overview(result: CharacterOverviewResult) -> CharacterOverview | None:
    return result.overview if result.status == "ok" else None


def _failure(message: str, recovery: Action | None = None) -> DocumentMessage:
    builder = M.document().section("行纪", icon="notice").line(message)
    if recovery is not None:
        builder.action(recovery)
    return builder.build()


__all__ = ["view_world_progress", "view_world_progress_ranking"]
