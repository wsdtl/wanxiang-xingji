"""跨界灾厄命令调用、固定叙事展示和排行排版。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from game.app import CurrentCharacterResult, current_game_services
from game.content import (
    DIMENSIONAL_DISASTER_ACTIVITY_ID,
    DIMENSIONAL_DISASTER_DAILY_ATTEMPTS,
    DRAW_TICKET_ITEM_ID,
)
from game.features.dimensional_disaster import (
    DimensionalDisasterChallengeResult,
    DimensionalDisasterView,
)
from game.core.gameplay import HEALTH_CURRENT
from game.rules.disaster import (
    DimensionalDisasterOutcome,
    DimensionalDisasterStatus,
)
from game.rules.activity import GlobalActivityPresentation, register_global_activity
from launch import config
from launch.adapter import current_message_context
from launch.paths import public_url
from message import Action, DocumentMessage, M

from ..command_helpers import command_time, current_character_value
from ..reply import send_command_failure, send_game_reply
from ..presentation import current_action_action
from ..reply_intents import DIMENSIONAL_DISASTER_INTENT


register_global_activity(
    DIMENSIONAL_DISASTER_ACTIVITY_ID,
    priority=100,
    entry_intent_id=DIMENSIONAL_DISASTER_INTENT,
    presentation=GlobalActivityPresentation(
        "跨界灾厄",
        "灾厄",
        "能够突破世界边界并同时影响多个世界的公共灾难。",
    ),
)


async def view_disaster(current: CurrentCharacterResult) -> None:
    character = current_character_value(current)
    if character is None:
        await send_game_reply(_unavailable())
        return
    try:
        logical_time = command_time()
        result = await asyncio.to_thread(
            current_game_services().dimensional_disasters.view,
            logical_time=logical_time,
        )
        await send_game_reply(_status_message(result, character, logical_time))
    except Exception as exc:
        await _failed("跨界灾厄查询失败", character.id, exc)


async def challenge_disaster(current: CurrentCharacterResult) -> None:
    character = current_character_value(current)
    if character is None:
        await send_game_reply(_unavailable())
        return
    context = current_message_context()
    if context is None:
        raise RuntimeError("讨伐灾厄缺少消息上下文")
    operation_id = f"{context.identity.evidence_id}:dimensional-disaster.challenge"
    try:
        result = await asyncio.to_thread(
            current_game_services().dimensional_disasters.challenge,
            character.id,
            operation_id,
            logical_time=command_time(),
        )
        view = current_game_services().world_view(current.character_world)
        await send_game_reply(_challenge_message(result, view.projector))
    except Exception as exc:
        await _failed("讨伐灾厄失败", character.id, exc)


async def disaster_ranking(current: CurrentCharacterResult) -> None:
    character = current_character_value(current)
    if character is None:
        await send_game_reply(_unavailable())
        return
    try:
        result = await asyncio.to_thread(
            current_game_services().dimensional_disasters.view,
            logical_time=command_time(),
        )
        message = await asyncio.to_thread(
            _ranking_message,
            result,
            character.id,
        )
        await send_game_reply(message)
    except Exception as exc:
        await _failed("灾厄排行查询失败", character.id, exc)


def _status_message(
    result: DimensionalDisasterView,
    character,
    logical_time: datetime,
) -> DocumentMessage:
    if result.event is None:
        return (
            M.document()
            .section("跨界灾厄", icon="combat")
            .line("当前没有灾厄降临")
            .note("灾厄每周降临两次，每次持续 48 小时。")
            .build()
        )
    event = result.event
    activity = result.activity
    builder = M.document().section(
        f"跨界灾厄·{event.narrative.name}",
        icon="combat",
    )
    builder.line(event.narrative.title)
    builder.line(event.narrative.scene)
    builder.row(
        ("状态", _event_status(event)),
        ("血量", f"{event.current_health}/{event.maximum_health}"),
    )
    if result.active:
        builder.field("结束", _time(event.closes_at))
    else:
        builder.field("降临", _time(event.opens_at))
    attempts = 0
    if activity is not None:
        participant = activity.participants.get(character.id)
        attempts = current_game_services().dimensional_disasters.attempts_today(
            event,
            character.id,
            logical_time=logical_time,
        )
        builder.row(
            ("我的伤痕", participant.contribution if participant else 0),
            ("今日讨伐", f"{attempts}/{DIMENSIONAL_DISASTER_DAILY_ATTEMPTS}"),
        )
    builder.line(event.narrative.story)
    actions = [
        Action(
            "disaster.ranking",
            "排行",
            "灾厄排行",
            behavior="send",
            style="secondary",
        )
    ]
    if (
        result.active
        and event.status is DimensionalDisasterStatus.OPEN
        and event.outcome is DimensionalDisasterOutcome.NONE
        and attempts < DIMENSIONAL_DISASTER_DAILY_ATTEMPTS
        and character.resources.get(HEALTH_CURRENT, 0) > 0
    ):
        remaining = DIMENSIONAL_DISASTER_DAILY_ATTEMPTS - attempts
        actions.insert(
            0,
            Action(
                "disaster.challenge",
                f"讨伐（剩余{remaining}次）",
                "讨伐灾厄",
                behavior="send",
            ),
        )
    return builder.actions(tuple(actions)).build()


def _challenge_message(result: DimensionalDisasterChallengeResult, projector) -> DocumentMessage:
    builder = M.document().section("讨伐灾厄", icon="combat")
    if result.status in {"resolved", "defeated", "replayed"} and result.receipt is not None:
        receipt = result.receipt
        builder.row(
            ("伤痕", receipt.damage),
            ("灾厄血量", receipt.shared_health_after),
        )
        builder.row(
            ("血气", _number(receipt.player_health_after)),
            ("灵力", _number(receipt.player_spirit_after)),
        )
        builder.row(
            ("今日次数", f"{receipt.attempts_today}/{DIMENSIONAL_DISASTER_DAILY_ATTEMPTS}"),
            ("战斗行动", receipt.turns),
        )
        if receipt.draw_ticket_drops:
            builder.field("战斗掉落", f"{projector.name(DRAW_TICKET_ITEM_ID)} x1")
        if receipt.companion_id is not None:
            builder.field("伙伴经验", f"+{receipt.companion_experience}")
        if result.battle_report is not None:
            builder.field(
                "战报",
                M.link(
                    "查看完整战报",
                    public_url("battle", result.battle_report.share_id),
                ),
            )
        if result.status == "defeated":
            builder.line("跨界灾厄已经被击破，活动结束时将封榜并产生本期唯一遗羽。")
        elif result.status == "replayed":
            builder.note("本次为重复消息，已经返回原挑战结果。")
        actions = [
            Action(
                "disaster.ranking",
                "排行",
                "灾厄排行",
                behavior="send",
                style="secondary",
            )
        ]
        if (
            result.status == "resolved"
            and receipt.attempts_today < DIMENSIONAL_DISASTER_DAILY_ATTEMPTS
        ):
            remaining = DIMENSIONAL_DISASTER_DAILY_ATTEMPTS - receipt.attempts_today
            actions.insert(
                0,
                Action(
                    "disaster.challenge",
                    f"再次讨伐（剩余{remaining}次）",
                    "讨伐灾厄",
                    behavior="send",
                ),
            )
        return builder.actions(tuple(actions)).build()
    messages = {
        "no_active": "当前没有灾厄降临",
        "ended": "本期灾厄已经产生结局",
        "attempt_limit": "今日讨伐次数已经用完",
        "main_action_occupied": "当前正在进行其他主要行动",
        "exploring": "当前正在探险，停止后才能讨伐灾厄",
        "health_depleted": "血气已经归零，恢复后才能讨伐灾厄",
    }
    builder.line(messages.get(result.status, "本次讨伐没有完成"))
    if result.status == "main_action_occupied":
        builder.action(current_action_action())
    elif result.status == "exploring":
        builder.action(Action("disaster.stop_exploration", "停止探险", "停止探险"))
    elif result.status == "health_depleted":
        builder.actions(
            (
                Action("disaster.inventory", "查看纳戒", "纳戒", style="secondary"),
                Action("disaster.rest", "休息", "休息"),
            )
        )
    return builder.build()


def _ranking_message(
    result: DimensionalDisasterView,
    current_character_id: str,
) -> DocumentMessage:
    if result.event is None or result.activity is None:
        return M.document().section("灾厄排行", icon="combat").line("暂无灾厄记录").build()
    event = result.event
    activity = result.activity
    ranked = _ranked(activity)
    builder = M.document().section(
        f"灾厄排行·{event.narrative.name}",
        icon="combat",
    )
    if not ranked:
        return builder.line("当前还没有有效伤痕").build()
    services = current_game_services()
    for rank, character_id, contribution, attempts in ranked[:10]:
        character = services.characters.load_character(character_id)
        name = character.name if character is not None else "无名行者"
        builder.item(
            rank,
            f"{name} | 伤痕: {contribution} | "
            f"贡献: {contribution / event.maximum_health:.1%} | 讨伐: {attempts}",
        )
    mine = next((value for value in ranked if value[1] == current_character_id), None)
    if mine is not None and mine[0] > 10:
        builder.note(
            f"我的排名: {mine[0]} | 伤痕: {mine[2]} | "
            f"贡献: {mine[2] / event.maximum_health:.1%}"
        )
    return builder.build()


def _ranked(activity):
    if activity.ranking:
        return tuple(
            (value.rank, value.subject_id, value.contribution, value.attempts)
            for value in activity.ranking
        )
    participants = sorted(
        (value for value in activity.participants.values() if value.contribution > 0),
        key=lambda value: (-value.contribution, value.joined_at, value.subject_id),
    )
    return tuple(
        (index, value.subject_id, value.contribution, value.attempts)
        for index, value in enumerate(participants, 1)
    )


def _event_status(event) -> str:
    if event.status is DimensionalDisasterStatus.SETTLING:
        return "结算中"
    if event.status is DimensionalDisasterStatus.CLOSED:
        return "已封存"
    if event.outcome is DimensionalDisasterOutcome.DEFEATED:
        return "已击破"
    if event.outcome is DimensionalDisasterOutcome.ESCAPED:
        return "已退去"
    return "侵入中"


def _time(value: datetime) -> str:
    return value.astimezone(ZoneInfo(config.project.timezone)).strftime("%m-%d %H:%M")


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


async def _failed(message: str, character_id: str, exc: Exception) -> None:
    await send_command_failure(
        message,
        character_id,
        exc,
        M.document()
        .section("跨界灾厄", icon="combat")
        .line("当前操作没有完成，请稍后重试")
        .build()
    )


def _unavailable() -> DocumentMessage:
    return M.document().section("跨界灾厄", icon="combat").line("当前没有可用角色").build()


__all__ = ["challenge_disaster", "disaster_ranking", "view_disaster"]
