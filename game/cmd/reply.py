"""正式游戏回复的玩家外框装饰与统一发送出口。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from game.app import (
    PlayerReplyState,
    current_game_services,
    message_identity_evidence,
)
from game.core.gameplay import SkinProjector
from game.rules.activity import resolve_global_activity_presentation
from launch import C, logger
from launch.adapter import MessageIdentity, current_message_context, manager
from message import DocumentMessage, Message, rich
from message.schema import (
    Document,
    FieldSeparator,
    HeaderBlock,
    InlineBlock,
    RichText,
)

from .presentation import character_header_color, character_header_parts
from .command_helpers import command_time
from .reply_intents import (
    NOTIFICATIONS_INTENT,
    PENDING_ACTIONS_INTENT,
    ReplyIntentRegistry,
    WORLD_EVENT_DETAIL_INTENT,
    WORLD_EVENTS_INTENT,
    reply_intents,
)


@dataclass(frozen=True)
class GameReplyComposer:
    """为已建档玩家统一添加人物头、活动和个人提醒通栏。"""

    projector: SkinProjector
    intent_registry: ReplyIntentRegistry = reply_intents

    def compose(
        self,
        message: DocumentMessage,
        state: PlayerReplyState,
        *,
        logical_time: datetime,
    ) -> DocumentMessage:
        body = message.document
        headers = tuple(block for block in body.blocks if isinstance(block, HeaderBlock))
        if len(headers) > 1:
            raise ValueError("游戏业务正文不能包含多个 Header")
        if headers and headers[0].color:
            raise ValueError("游戏业务不能手写彩色 Header")
        if any(isinstance(block, InlineBlock) for block in body.blocks):
            raise ValueError("游戏业务不能占用全局通知通栏")

        blocks = [
            HeaderBlock(
                rich(*character_header_parts(state.character, self.projector)),
                character_header_color(state.settings, logical_time),
            )
        ]
        activities = _activity_content(state, self.projector, self.intent_registry)
        if activities:
            blocks.append(InlineBlock(rich("活动"), activities, "system"))
        reminder = _reminder_content(state, self.intent_registry)
        if reminder:
            blocks.append(InlineBlock(rich("提醒"), reminder, "notice"))
        blocks.extend(
            block for block in body.blocks if not isinstance(block, HeaderBlock)
        )
        return DocumentMessage(Document(tuple(blocks), body.actions))


async def send_game_reply(message: Message) -> bool:
    """自动装饰已建档玩家回复，再发送到当前命令的默认目标。"""

    context = current_message_context()
    if context is None:
        raise RuntimeError("游戏回复缺少当前消息上下文")
    decorated = await _decorate_current_player_reply(
        message,
        context.identity,
        logical_time=command_time(),
    )
    return await manager.send(decorated, context.client_id)


async def send_command_failure(
    title: str,
    character_id: str,
    exc: Exception,
    fallback: Message,
) -> None:
    """统一记录命令异常并发送由组件决定的降级回复。"""

    logger.opt(colors=True, exception=exc).error(
        C.join(C.fail(title), C.kv("character", character_id))
    )
    await send_game_reply(fallback)


async def _decorate_current_player_reply(
    message: Message,
    identity: MessageIdentity,
    *,
    logical_time: datetime,
) -> Message:
    if not isinstance(message, DocumentMessage):
        return message
    services = current_game_services()
    evidence = message_identity_evidence(identity, logical_time=logical_time)
    try:
        result = await asyncio.to_thread(
            services.load_player_reply_state,
            evidence,
        )
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(
                C.fail("玩家回复外框读取失败"),
                C.kv("evidence", evidence.id),
            )
        )
        return message
    if result.status != "ok" or result.state is None:
        return message
    return GameReplyComposer(services.world_view(result.state.character_world).projector).compose(
        message,
        result.state,
        logical_time=logical_time,
    )


def _reminder_content(
    state: PlayerReplyState,
    intent_registry: ReplyIntentRegistry,
) -> RichText:
    parts = []
    if state.pending_action_count:
        parts.append(
            intent_registry.link(
                f"{state.pending_action_count} 项待领取",
                PENDING_ACTIONS_INTENT,
            )
        )
    if state.unread_notification_count:
        if parts:
            parts.append(FieldSeparator())
        parts.append(
            intent_registry.link(
                f"{state.unread_notification_count} 条未读通知",
                NOTIFICATIONS_INTENT,
            )
        )
    return tuple(parts)


def _activity_content(
    state: PlayerReplyState,
    projector: SkinProjector,
    intent_registry: ReplyIntentRegistry,
) -> RichText:
    parts = []
    for view in state.activity_spotlights:
        if parts:
            parts.append(FieldSeparator())
        parts.append(
            intent_registry.link(
                resolve_global_activity_presentation(
                    view.registration,
                    projector,
                ).compact_name,
                WORLD_EVENT_DETAIL_INTENT,
                {"instance_id": view.instance.id},
            )
        )
    if state.additional_activity_count:
        if parts:
            parts.append(FieldSeparator())
        parts.append(
            intent_registry.link(
                f"+{state.additional_activity_count}",
                WORLD_EVENTS_INTENT,
            )
        )
    return tuple(parts)


__all__ = ["GameReplyComposer", "send_command_failure", "send_game_reply"]
