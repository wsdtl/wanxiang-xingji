"""全局提醒组件的只读查询与消息正文。"""

from __future__ import annotations

import asyncio
from base64 import urlsafe_b64decode
from datetime import datetime
from zoneinfo import ZoneInfo

from game.app import (
    CurrentCharacterResult,
    PlayerReminderDetailsResult,
    current_game_services,
)
from game.core.gameplay import ActionRecord, NotificationEntry
from launch import C, config, logger
from message import Action, DocumentMessage, M
from message.schema import FieldSeparator

from ..command_helpers import command_time
from ..reply import send_game_reply
from ..reply_intents import NOTIFICATION_READ_INTENT, reply_intents


async def view_notifications(current: CurrentCharacterResult) -> None:
    """读取并展示未读通知，不自动标记已读。"""

    result = await _load_details(current)
    await send_game_reply(_notifications_message(result, world_view=_world_view(current)))


async def view_pending_actions(current: CurrentCharacterResult) -> None:
    """读取并展示已经完成但尚未领取的行动。"""

    result = await _load_details(current)
    await send_game_reply(_pending_actions_message(result, _world_view(current)))


async def mark_notification_read(
    message: str,
    current: CurrentCharacterResult,
) -> None:
    """校验当前账号后把一条通知标记为已读。"""

    if current.status != "ok" or current.character is None:
        await send_game_reply(
            _unavailable_message(
                "未读通知",
                Action("notifications.retry", "重试", "未读通知"),
            )
        )
        return
    parts = str(message or "").strip().split()
    if len(parts) != 2:
        await send_game_reply(
            _unavailable_message(
                "未读通知",
                Action("notifications.back", "返回通知", "未读通知"),
            )
        )
        return
    try:
        notification_id = urlsafe_b64decode(parts[0].encode("ascii")).decode("utf-8")
        revision = int(parts[1])
        marked = await asyncio.to_thread(
            current_game_services().mark_notification_read,
            current.character,
            notification_id,
            revision,
            logical_time=command_time(),
        )
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(
                C.fail("通知已读执行失败"),
                C.kv("character", current.character.id),
            )
        )
        await send_game_reply(
            _unavailable_message(
                "未读通知",
                Action("notifications.retry", "重试", "未读通知"),
            )
        )
        return
    result = await _load_details(current)
    note = "已标记为已读" if marked.status == "read" else "通知已经处理或状态发生变化"
    await send_game_reply(
        _notifications_message(result, world_view=_world_view(current), note=note)
    )


async def _load_details(
    current: CurrentCharacterResult,
) -> PlayerReminderDetailsResult:
    if current.status != "ok" or current.character is None:
        return PlayerReminderDetailsResult(current.status)
    try:
        return await asyncio.to_thread(
            current_game_services().load_player_reminder_details,
            current.character,
            logical_time=command_time(),
        )
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(
                C.fail("玩家提醒明细执行失败"),
                C.kv("character", current.character.id),
            )
        )
        return PlayerReminderDetailsResult("failed")


def _notifications_message(
    result: PlayerReminderDetailsResult,
    *,
    world_view,
    note: str = "",
) -> DocumentMessage:
    if result.status != "ok" or result.details is None or world_view is None:
        return _unavailable_message(
            "未读通知",
            Action("notifications.retry", "重试", "未读通知"),
        )
    details = result.details
    builder = M.document().section("未读通知", icon="notice")
    if not details.notifications:
        builder.line("暂无未读通知")
        if note:
            builder.note(note)
        return builder.action(
            Action("notifications.pending", "查看待领取", "待领取")
        ).build()
    builder.field("数量", len(details.notifications))
    for index, entry in enumerate(details.notifications, start=1):
        parts = [f"[{index}] {_notification_title(entry, world_view)}", FieldSeparator(), M.em(_time(entry.created_at))]
        if entry.action is not None and entry.action.kind_id in reply_intents:
            parts.extend(
                (
                    FieldSeparator(),
                    reply_intents.link(
                        "处理",
                        entry.action.kind_id,
                        entry.action.payload,
                    ),
                )
            )
        parts.extend(
            (
                FieldSeparator(),
                reply_intents.link(
                    "已读",
                    NOTIFICATION_READ_INTENT,
                    {
                        "notification_id": entry.id,
                        "revision": entry.revision,
                    },
                ),
            )
        )
        builder.line(*parts)
    if note:
        builder.note(note)
    return builder.build()


def _pending_actions_message(
    result: PlayerReminderDetailsResult,
    world_view,
) -> DocumentMessage:
    if result.status != "ok" or result.details is None or world_view is None:
        return _unavailable_message(
            "待领取",
            Action("pending-actions.retry", "重试", "待领取"),
        )
    details = result.details
    builder = M.document().section("待领取", icon="reward")
    if not details.pending_actions:
        return (
            builder.line("暂无待领取行动")
            .action(Action("pending-actions.notifications", "查看通知", "未读通知"))
            .build()
        )
    builder.field("数量", len(details.pending_actions))
    for index, record in enumerate(details.pending_actions, start=1):
        builder.line(
            f"[{index}] {_action_title(record, world_view)}",
            FieldSeparator(),
            M.em(_time(record.completes_at)),
        )
    return builder.action(
        Action("pending-actions.notifications", "查看通知", "未读通知")
    ).build()


def _notification_title(entry: NotificationEntry, world_view) -> str:
    return _projected_name(entry.kind_id, "系统通知", world_view)


def _action_title(record: ActionRecord, world_view) -> str:
    return _projected_name(record.definition_id, "待领取行动", world_view)


def _projected_name(definition_id: str, fallback: str, world_view) -> str:
    try:
        return world_view.projector.name(definition_id)
    except KeyError:
        return fallback


def _world_view(current: CurrentCharacterResult):
    if current.character_world is None:
        return None
    return current_game_services().world_view(current.character_world)


def _unavailable_message(title: str, recovery: Action) -> DocumentMessage:
    return (
        M.document()
        .section(title, icon="notice")
        .line("当前没有读取到提醒状态，请稍后重试")
        .action(recovery)
        .build()
    )


def _time(value: datetime) -> str:
    return value.astimezone(ZoneInfo(config.project.timezone)).strftime("%m-%d %H:%M")


__all__ = ["mark_notification_read", "view_notifications", "view_pending_actions"]
