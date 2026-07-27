"""活动组件的只读查询与协议中立展示。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from game.app import (
    CurrentCharacterResult,
    GlobalActivityViewsResult,
    current_game_services,
)
from game.rules.activity import (
    GlobalActivityView,
    resolve_global_activity_presentation,
)
from launch import C, config, logger
from message import Action, DocumentMessage, M
from message.schema import FieldSeparator

from ..command_helpers import command_time
from ..reply import send_game_reply
from ..reply_intents import WORLD_EVENT_DETAIL_INTENT, reply_intents


async def view_world_events(
    instance_id: str,
    current: CurrentCharacterResult,
) -> None:
    """只读展示开放活动；传入实例 ID 时展示详情。"""

    result = await _load_activities(current)
    view = (
        current_game_services().world_view(current.character_world)
        if current.character_world is not None
        else None
    )
    await send_game_reply(_activity_message(result, instance_id.strip(), view))


async def _load_activities(
    current: CurrentCharacterResult,
) -> GlobalActivityViewsResult:
    if current.status != "ok" or current.character is None:
        return GlobalActivityViewsResult(current.status)
    try:
        return await asyncio.to_thread(
            current_game_services().load_global_activity_views,
            logical_time=command_time(),
        )
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(C.fail("公共活动查询失败"), C.kv("character", current.character.id))
        )
        return GlobalActivityViewsResult("failed")


def _activity_message(
    result: GlobalActivityViewsResult,
    instance_id: str,
    world_view,
) -> DocumentMessage:
    if result.status != "ok" or world_view is None:
        return _unavailable_message()
    if instance_id:
        view = next(
            (value for value in result.activities if value.instance.id == instance_id),
            None,
        )
        return _activity_detail_message(view, world_view)
    return _activity_list_message(result.activities, world_view)


def _activity_list_message(
    activities: tuple[GlobalActivityView, ...],
    world_view,
) -> DocumentMessage:
    builder = M.document().section("活动", icon="system")
    if not activities:
        return (
            builder.line("当前没有开放的活动")
            .action(Action("activity.character", "查看角色", "我的角色"))
            .build()
        )
    projector = world_view.projector
    builder.field("数量", len(activities))
    for index, view in enumerate(activities, start=1):
        builder.item(
            index,
            reply_intents.link(
                resolve_global_activity_presentation(
                    view.registration,
                    projector,
                ).name,
                WORLD_EVENT_DETAIL_INTENT,
                {"instance_id": view.instance.id},
            ),
            FieldSeparator(),
            M.em(f"至 {_time(view.instance.closes_at)}"),
        )
    return builder.build()


def _activity_detail_message(
    view: GlobalActivityView | None,
    world_view,
) -> DocumentMessage:
    if view is None:
        return (
            M.document()
            .section("活动详情", icon="system")
            .line("活动不存在、尚未开放或已经结束")
            .action(Action("activity.back", "返回活动", "活动"))
            .build()
        )
    projector = world_view.projector
    presentation = resolve_global_activity_presentation(
        view.registration,
        projector,
    )
    builder = M.document().section(
        presentation.name,
        icon="system",
    )
    if presentation.description:
        builder.line(presentation.description)
    builder.row(
        ("开放", _time(view.instance.opens_at)),
        ("结束", _time(view.instance.closes_at)),
    )
    builder.field("参与", f"{len(view.instance.participants)} 人")
    intent_id = view.registration.entry_intent_id
    if intent_id is not None and intent_id in reply_intents:
        builder.line(
            reply_intents.link(
                "进入活动",
                intent_id,
                {
                    "instance_id": view.instance.id,
                    "definition_id": view.instance.definition_id,
                },
            )
        )
    return builder.action(
        Action("activity.back", "返回活动", "活动", style="secondary")
    ).build()


def _unavailable_message() -> DocumentMessage:
    return (
        M.document()
        .section("活动", icon="system")
        .line("当前没有读取到活动状态，请稍后重试")
        .action(Action("activity.retry", "重试", "活动"))
        .build()
    )


def _time(value: datetime) -> str:
    return value.astimezone(ZoneInfo(config.project.timezone)).strftime("%m-%d %H:%M")


__all__ = ["view_world_events"]
