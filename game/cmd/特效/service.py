"""当前配装机制、正式机制图鉴与详情展示。"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass

from game.app import CharacterOverview, CharacterOverviewResult, current_game_services
from game.content.presentation import MechanicDetail, MechanicProjector
from game.core.gameplay import (
    STANDARD_LOADOUT_SLOT_ORDER,
    WEAPON_SLOT_ID,
    EquipmentState,
    WeaponState,
    equipment_state_from_instance,
    weapon_state_from_instance,
)
from game.rules.item import asset_reference
from message import Action, DocumentMessage, M
from message.schema import FieldSeparator

from ..interaction import (
    DEFAULT_PAGE_SIZE,
    paginate,
    pagination_actions,
    parse_page_number,
)
from ..reply import send_command_failure, send_game_reply


PAGE_SIZE = DEFAULT_PAGE_SIZE


class _MechanicRequestError(ValueError):
    """玩家输入无法解析为正式机制请求。"""


@dataclass(frozen=True)
class _EquippedMechanic:
    content_id: str
    name: str
    category: str
    summary: str
    active_tiers: frozenset[str]
    source_name: str
    source_command: str = ""


@dataclass(frozen=True)
class _EquippedGear:
    state: WeaponState | EquipmentState
    name: str
    reference: str


async def view_mechanics(message: str, result: CharacterOverviewResult) -> None:
    """按请求展示当前机制、图鉴页或单项详情。"""

    overview = result.overview if result.status == "ok" else None
    if overview is None:
        await send_game_reply(_failure_message("当前没有读取到角色配装，请稍后重试"))
        return
    try:
        request = _parse_request(message)
        reply = await asyncio.to_thread(_request_message, request, overview)
    except _MechanicRequestError as exc:
        await send_game_reply(_failure_message(str(exc)))
        return
    except Exception as exc:
        await send_command_failure(
            "特效详情生成失败",
            overview.character.id,
            exc,
            _failure_message("当前没有读取到特效详情，请稍后重试"),
        )
        return
    await send_game_reply(reply)


def _parse_request(message: str) -> tuple[str, object]:
    tokens = str(message or "").strip().split()
    if not tokens:
        return "current", None
    if tokens[0] == "全部":
        if len(tokens) > 2:
            raise _MechanicRequestError("全部特效只接受一个页码")
        try:
            page = parse_page_number(tokens[1] if len(tokens) == 2 else "")
        except ValueError as exc:
            raise _MechanicRequestError(str(exc)) from exc
        return "catalog", page
    return "detail", " ".join(tokens)


def _request_message(
    request: tuple[str, object],
    overview: CharacterOverview,
) -> DocumentMessage:
    services = current_game_services()
    current_view = services.world_view(overview.character_world)
    current_projector = MechanicProjector(current_view.catalog, current_view.projector)
    mode, value = request
    if mode == "current":
        return _current_message(overview, current_view, current_projector)
    if mode == "catalog":
        return _catalog_message(int(value), current_view.skin.name, current_projector)
    view, query = _detail_view(value, current_view, services.world_views)
    projector = MechanicProjector(view.catalog, view.projector)
    content_id = projector.resolve(query)
    if content_id is None:
        raise _MechanicRequestError(f"没有找到名为“{query}”的正式机制")
    return _detail_message(
        projector.detail(content_id),
        _equipped_mechanics(overview, current_view, current_projector),
        view.skin.name,
    )


def _detail_view(value: object, current_view, world_views):
    query = " ".join(str(value or "").strip().split())
    if not query.startswith("@"):
        return current_view, query
    scope, separator, query = query.partition(" ")
    if not separator or not query:
        raise _MechanicRequestError("特效来源后缺少机制名称")
    view = world_views.resolve(scope.removeprefix("@"))
    if view is None:
        raise _MechanicRequestError("没有找到这个特效来源世界")
    return view, query


def _current_message(overview, view, projector: MechanicProjector) -> DocumentMessage:
    equipped = _equipped_mechanics(overview, view, projector)
    builder = (
        M.document()
        .section("当前特效", icon="skill")
        .row(("世界", view.skin.name), ("生效项", len(equipped)))
    )
    if not equipped:
        builder.line("当前配装没有生效机制")
    current_category = ""
    for value in equipped:
        if value.category != current_category:
            current_category = value.category
            builder.section(current_category, icon=_category_icon(current_category))
        parts: list[object] = [
            M.command(value.name, f"特效 {value.name}"),
            FieldSeparator(),
            value.summary,
        ]
        if value.source_name:
            parts.append(FieldSeparator())
            parts.append(
                M.command(value.source_name, value.source_command)
                if value.source_command
                else value.source_name
            )
        builder.line(*parts)
    builder.section("机制图鉴", icon="item").line(
        M.command("查看全部特效", "特效 全部")
    )
    return builder.build()


def _catalog_message(
    page_number: int,
    world_name: str,
    projector: MechanicProjector,
) -> DocumentMessage:
    try:
        page = paginate(
            projector.catalog_entries(),
            page_number,
            page_size=PAGE_SIZE,
        )
    except ValueError as exc:
        raise _MechanicRequestError(str(exc)) from exc
    builder = (
        M.document()
        .section("全部特效", icon="item")
        .row(("世界", world_name), ("页码", page.label), ("总数", page.total))
    )
    current_category = ""
    for entry in page.values:
        if entry.category != current_category:
            current_category = entry.category
            builder.section(current_category, icon=_category_icon(current_category))
        parts: list[object] = [M.command(entry.name, f"特效 {entry.name}")]
        if entry.description:
            parts.extend((" - ", entry.description))
        builder.line(*parts)
    return builder.actions(
        pagination_actions(
            "特效 全部",
            page,
            back=Action(
                "mechanic.current",
                "当前特效",
                "特效",
                style="secondary",
            ),
        )
    ).build()


def _detail_message(
    detail: MechanicDetail,
    equipped: tuple[_EquippedMechanic, ...],
    world_name: str,
) -> DocumentMessage:
    current = tuple(value for value in equipped if value.content_id == detail.id)
    active_tiers = frozenset(
        tier
        for value in current
        for tier in value.active_tiers
    )
    builder = (
        M.document()
        .section(detail.name, icon=_category_icon(detail.category))
        .row(("类别", detail.category), ("世界", world_name))
    )
    if detail.description:
        builder.line(detail.description)
    if current:
        builder.section("当前配装", icon="equipment")
        for value in current:
            source = (
                M.command(value.source_name, value.source_command)
                if value.source_command
                else value.source_name
            )
            builder.line(source, FieldSeparator(), value.summary)
    for tier in detail.tiers:
        title = f"{tier.label}（当前生效）" if tier.label in active_tiers else tier.label
        builder.section(title, icon="status")
        for line in tier.lines:
            builder.line(line)
    return builder.actions(
        (
            Action(
                "mechanic.current",
                "当前特效",
                "特效",
                style="secondary",
            ),
            Action(
                "mechanic.catalog",
                "全部特效",
                "特效 全部",
                style="secondary",
            ),
        )
    ).build()


def _equipped_mechanics(
    overview: CharacterOverview,
    view,
    projector: MechanicProjector,
) -> tuple[_EquippedMechanic, ...]:
    services = current_game_services()
    entity = services.player_combat.project(
        overview.character,
        overview.inventory,
        overview.loadout,
    ).entity
    values: list[_EquippedMechanic] = []
    for ability_id in sorted(entity.abilities):
        detail = projector.detail(ability_id)
        values.append(
            _EquippedMechanic(
                detail.id,
                detail.name,
                detail.category,
                "当前已生效",
                frozenset({detail.tiers[0].label}),
                "角色与当前配装",
            )
        )

    equipment_sets: Counter[str] = Counter()
    for gear in _equipped_gear(overview, view):
        state = gear.state
        if state.roll is not None:
            for rolled in state.roll.properties:
                detail = projector.detail(rolled.property_id)
                tier_label = (
                    detail.tiers[0].label
                    if detail.category == "武器核心" and len(detail.tiers) == 1
                    else f"T{rolled.tier}"
                )
                actual = projector.roll_summary(
                    rolled.property_id,
                    rolled.tier,
                    rolled.values,
                )
                summary = tier_label if not actual else f"{tier_label} · {actual}"
                values.append(
                    _EquippedMechanic(
                        detail.id,
                        detail.name,
                        detail.category,
                        summary,
                        frozenset({tier_label}),
                        f"{gear.name} {gear.reference}",
                        f"查看 {gear.reference}",
                    )
                )
        if isinstance(state, EquipmentState) and state.set_id is not None:
            equipment_sets[str(state.set_id)] += 1

    for set_id, count in sorted(equipment_sets.items()):
        definition = view.catalog.equipment.sets.require(set_id)
        active = tuple(
            bonus.required_pieces
            for bonus in definition.bonuses
            if count >= bonus.required_pieces
        )
        if not active:
            continue
        detail = projector.detail(set_id)
        values.append(
            _EquippedMechanic(
                detail.id,
                detail.name,
                detail.category,
                f"已装备 {count} 件 · {'/'.join(str(value) for value in active)} 件生效",
                frozenset(f"{value} 件" for value in active),
                "当前装备",
            )
        )

    category_order = {
        category: index
        for index, category in enumerate(
            (
                "能力",
                *dict.fromkeys(entry.category for entry in projector.catalog_entries()),
            )
        )
    }
    return tuple(
        sorted(
            values,
            key=lambda value: (
                category_order[value.category],
                value.name,
                value.source_name,
            ),
        )
    )


def _equipped_gear(overview: CharacterOverview, view) -> tuple[_EquippedGear, ...]:
    services = current_game_services()
    values: list[_EquippedGear] = []
    for slot_id in STANDARD_LOADOUT_SLOT_ORDER:
        asset_id = overview.loadout.slots.get(slot_id)
        if asset_id is None:
            continue
        asset = overview.inventory.instances.get(asset_id)
        if asset is None:
            continue
        if slot_id == WEAPON_SLOT_ID:
            state = weapon_state_from_instance(asset)
            name = view.gear_projector.weapon(
                state,
                asset,
                inscription_preference=overview.inscription_preference,
            ).name
        else:
            state = equipment_state_from_instance(asset)
            name = view.gear_projector.equipment(
                state,
                asset,
                inscription_preference=overview.inscription_preference,
            ).name
        reference = asset_reference(
            overview.inventory,
            asset,
            services.content.catalog.items,
        )
        values.append(_EquippedGear(state, name, reference))
    return tuple(values)


def _category_icon(category: str) -> str:
    if category in {"能力", "战斗机制"}:
        return "skill"
    if category == "套装效果":
        return "equipment"
    return "item"


def _failure_message(reason: str) -> DocumentMessage:
    return (
        M.document()
        .section("特效", icon="notice")
        .line(reason)
        .actions(
            (
                Action(
                    "mechanic.current",
                    "当前特效",
                    "特效",
                    style="secondary",
                ),
                Action(
                    "mechanic.catalog",
                    "全部特效",
                    "特效 全部",
                    style="secondary",
                ),
            )
        )
        .build()
    )


__all__ = ["PAGE_SIZE", "view_mechanics"]
