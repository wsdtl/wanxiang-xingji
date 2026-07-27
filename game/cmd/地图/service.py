"""地图命令的只读查询、地点解析与消息展示。"""

from __future__ import annotations

import asyncio

from game.app import CharacterOverview, CharacterOverviewResult, current_game_services
from game.content.catalog.exploration import ExplorationRegionKind
from game.content.catalog.world import (
    LOCATION_FUNCTION_CITY,
    LOCATION_FUNCTION_COMPANION_PERSON,
    LOCATION_FUNCTION_EXPLORATION,
)
from message import Action, DocumentMessage, M
from message.schema import FieldSeparator

from ..command_helpers import command_time
from ..reply import send_command_failure, send_game_reply
from ..world_location import (
    current_world_location_action,
    current_world_location_command,
    resolve_current_world_location,
)


_REGION_KIND_NAMES = {
    ExplorationRegionKind.REGULAR: "常规",
    ExplorationRegionKind.WEAPON_FOCUS: "武器偏向",
    ExplorationRegionKind.EQUIPMENT_FOCUS: "装备偏向",
    ExplorationRegionKind.BOSS_FOCUS: "首领偏向",
}


async def view_map(message: str, result: CharacterOverviewResult) -> None:
    """展示地图总览，或按当前世界的可见名称展示地点详情。"""

    overview = _overview(result)
    if overview is None:
        await send_game_reply(_unavailable())
        return
    try:
        services = current_game_services()
        companion_view = await asyncio.to_thread(
            services.companions.view,
            overview.character.id,
            logical_time=command_time(),
        )
        view = services.world_view(overview.character_world)
        progress = await asyncio.to_thread(
            services.world_progress.view,
            overview.character.id,
            view.world.id,
        )
        progress_by_region = {value.region_id: value for value in progress.regions}
        requested = str(message or "").strip()
        if requested:
            reply = _location_detail(
                requested,
                overview,
                companion_view.roster,
                view,
                progress_by_region,
            )
        else:
            reply = _map_overview(
                overview,
                companion_view.roster,
                view,
                progress_by_region,
            )
    except (KeyError, TypeError, ValueError) as exc:
        reply = _failure(str(exc))
    except Exception as exc:
        await send_command_failure(
            "地图查询失败",
            overview.character.id,
            exc,
            _failure("当前没有读取到地图，请稍后重试"),
        )
        return
    await send_game_reply(reply)


def _map_overview(overview: CharacterOverview, roster, view, progress_by_region) -> DocumentMessage:
    services = current_game_services()
    current = _current_location(overview)
    builder = (
        M.document()
        .section(f"地图·{view.skin.name}", icon="world")
        .row(
            ("世界", view.skin.name),
            ("当前位置", _location_name(current, view)),
        )
    )
    if current is not None:
        builder.field("坐标", _coordinates(current))

    city_bindings = services.content.worlds.bindings_for_world(
        view.world.id,
        function_id=LOCATION_FUNCTION_CITY,
    )
    builder.section("主城", icon="world")
    for binding in city_bindings:
        resolved = services.content.worlds.resolve(view.world.id, binding.anchor_id)
        builder.line(*_map_line(resolved, current, view, "安全区"))

    exploration_bindings = services.content.worlds.bindings_for_world(
        view.world.id,
        function_id=LOCATION_FUNCTION_EXPLORATION,
    )
    regions = sorted(
        (
            (
                services.content.exploration_regions.require(binding.content_ref),
                binding,
            )
            for binding in exploration_bindings
        ),
        key=lambda value: (
            value[0].kind is not ExplorationRegionKind.REGULAR,
            value[0].minimum_enemy_level,
            value[0].id,
        ),
    )
    builder.section("探险区域", icon="combat")
    for region, binding in regions:
        resolved = services.content.worlds.resolve(view.world.id, binding.anchor_id)
        detail = (
            f"{_REGION_KIND_NAMES[region.kind]} "
            f"{_levels(region.minimum_enemy_level, region.maximum_enemy_level)} "
            f"| 行纪 {progress_by_region[region.id].percent}%"
        )
        builder.line(*_map_line(resolved, current, view, detail))

    people_bindings = services.content.worlds.bindings_for_world(
        view.world.id,
        function_id=LOCATION_FUNCTION_COMPANION_PERSON,
    )
    builder.section("人物地点", icon="player")
    for binding in people_bindings:
        resolved = services.content.worlds.resolve(view.world.id, binding.anchor_id)
        person = services.content.companions.people.require(
            resolved.require_content_ref()
        )
        builder.line(
            *_map_line(
                resolved,
                current,
                view,
                f"{person.name} | {_person_status(person, roster)}",
            )
        )
    return builder.note("发送：地图 地点名称").build()


def _location_detail(
    requested: str,
    overview: CharacterOverview,
    roster,
    view,
    progress_by_region,
) -> DocumentMessage:
    services = current_game_services()
    binding = resolve_current_world_location(
        requested,
        view,
        services.content.worlds,
    )
    if binding is None:
        return _failure("当前世界没有这个地点")
    resolved = services.content.worlds.resolve(view.world.id, binding.anchor_id)
    entry = view.projector.entry(resolved.display_id)
    builder = (
        M.document()
        .section(entry.name, icon="world")
        .field("世界", view.skin.name)
        .line(entry.description or "这里尚无更多记载。")
        .row(("坐标", _coordinates(resolved)), ("类型", _location_type(binding.function_id)))
    )
    if binding.function_id == LOCATION_FUNCTION_EXPLORATION:
        region = services.content.exploration_regions.require(resolved.require_content_ref())
        builder.row(
            ("等级", _levels(region.minimum_enemy_level, region.maximum_enemy_level)),
            ("倾向", _REGION_KIND_NAMES[region.kind]),
            ("行纪", f"{progress_by_region[region.id].percent}%"),
        )
    elif binding.function_id == LOCATION_FUNCTION_COMPANION_PERSON:
        person = services.content.companions.people.require(resolved.require_content_ref())
        builder.field("驻留人物", f"{person.name} | {_person_status(person, roster)}")
        builder.line(person.description)

    current = _current_location(overview)
    if current is not None and current.anchor.id == resolved.anchor.id:
        builder.note("你当前就在这里。").action(
            current_world_location_action(binding)
        )
    else:
        builder.actions(
            (
                Action(
                    f"map.travel.{binding.anchor_id}",
                    "前往",
                    current_world_location_command(view, binding),
                    behavior="callback",
                ),
            )
        )
    return builder.build()


def _map_line(resolved, current, view, detail: str):
    marker = "[当前] " if current is not None and current.anchor.id == resolved.anchor.id else ""
    location_name = view.projector.name(resolved.display_id)
    return (
        marker,
        M.command(location_name, f"地图 {location_name}"),
        FieldSeparator(),
        _coordinates(resolved),
        FieldSeparator(),
        detail,
    )


def _current_location(overview: CharacterOverview):
    presence = next(
        (
            value
            for value in overview.world.presences.values()
            if value.owner_id == overview.character.id
        ),
        None,
    )
    if presence is None:
        return None
    return current_game_services().content.worlds.resolve_position(
        overview.character_world.world_id,
        presence.position,
    )


def _person_status(person, roster) -> str:
    if roster.active_by_definition(person.id) is not None:
        return "已结交"
    if person.id in roster.departed_people:
        return "可以重逢"
    bond = roster.person_bonds.get(person.id)
    if bond is not None and bond.favor >= person.bond_required:
        return "可以结交"
    return f"关系 {bond.favor if bond else 0}/{person.bond_required}"


def _location_name(resolved, view) -> str:
    return view.projector.name(resolved.display_id) if resolved is not None else "未知"


def _coordinates(resolved) -> str:
    return f"({resolved.position.x}, {resolved.position.y})"


def _levels(low: int, high: int) -> str:
    return f"Lv{low}" if low == high else f"Lv{low}-{high}"


def _location_type(function_id: str) -> str:
    return {
        LOCATION_FUNCTION_CITY: "主城",
        LOCATION_FUNCTION_EXPLORATION: "探险区域",
        LOCATION_FUNCTION_COMPANION_PERSON: "人物地点",
    }[function_id]


def _overview(result: CharacterOverviewResult) -> CharacterOverview | None:
    return result.overview if result.status == "ok" else None


def _failure(message: str) -> DocumentMessage:
    return (
        M.document()
        .section("地图", icon="notice")
        .line(message)
        .action(Action("map.back", "查看地图", "地图", behavior="callback"))
        .build()
    )


def _unavailable() -> DocumentMessage:
    return _failure("当前没有读取到角色状态，请稍后重试")


__all__ = ["view_map"]
