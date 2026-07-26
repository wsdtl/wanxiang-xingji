"""休息命令调用与协议中立展示。"""

from __future__ import annotations

import asyncio

from game.app import CurrentCharacterResult, current_game_services
from game.content.catalog.character import (
    REST_ACTION_ID,
    REST_FULL_RECOVERY_SECONDS,
    REST_MINIMUM_SECONDS,
)
from game.core.gameplay import HEALTH_CURRENT, SPIRIT_CURRENT
from launch.adapter import current_message_context
from message import Action, DocumentMessage, M

from ..command_helpers import command_time, current_character_value
from ..reply import send_command_failure, send_game_reply
from ..presentation import current_action_action


async def start(current: CurrentCharacterResult) -> None:
    character = current_character_value(current)
    if character is None:
        await send_game_reply(_unavailable())
        return
    operation_id = f"rest:start:{_evidence_id()}"
    try:
        result = await asyncio.to_thread(
            current_game_services().rest.start,
            operation_id,
            character.id,
            logical_time=command_time(),
        )
    except Exception as exc:
        await _failed("开始休息失败", character.id, exc)
        return
    await send_game_reply(_start_message(result, _view(current)))


async def stop(current: CurrentCharacterResult) -> None:
    character = current_character_value(current)
    if character is None:
        await send_game_reply(_unavailable())
        return
    operation_id = f"rest:stop:{_evidence_id()}"
    try:
        result = await asyncio.to_thread(
            current_game_services().rest.stop,
            operation_id,
            character.id,
            logical_time=command_time(),
        )
    except Exception as exc:
        await _failed("结束休息失败", character.id, exc)
        return
    await send_game_reply(_stop_message(result, _view(current)))


def _start_message(result, view) -> DocumentMessage:
    builder = M.document().section(view.projector.name(REST_ACTION_ID), icon="notice")
    if result.status in {"started", "already_running"}:
        return (
            builder.line("已经开始休息")
            .field("最低结算", _duration(REST_MINIMUM_SECONDS))
            .field("完全恢复", _duration(REST_FULL_RECOVERY_SECONDS))
            .actions((Action("rest.stop", "结束休息", "结束休息", style="secondary"),))
            .build()
        )
    if result.status == "full":
        return builder.line("当前状态已经完全恢复").build()
    if result.status == "exploring":
        return (
            builder.line("探险进行中，停止探险后才能休息")
            .action(Action("rest.stop_exploration", "停止探险", "停止探险"))
            .build()
        )
    if result.status == "main_action_occupied":
        return (
            builder.line("当前正在进行其他主要行动")
            .action(current_action_action())
            .build()
        )
    if result.status == "exploration_managed":
        return (
            builder.line("当前由探险自动休整接管")
            .action(Action("rest.stop_exploration", "停止探险", "停止探险"))
            .build()
        )
    return builder.line(result.failure_message or "休息没有开始").build()


def _stop_message(result, view) -> DocumentMessage:
    action_name = view.projector.name(REST_ACTION_ID)
    builder = M.document().section(f"{action_name}结束", icon="notice")
    if result.status == "not_running":
        return builder.line("当前没有正在进行的休息").build()
    if result.status == "failed":
        return builder.line(result.failure_message or "休息没有结束").build()
    if result.status == "exploration_managed":
        return (
            builder.line("当前由探险自动休整接管")
            .action(Action("rest.stop_exploration", "停止探险", "停止探险"))
            .build()
        )
    builder.row(
        (f"恢复{_resource_name(view, HEALTH_CURRENT)}", _number(result.recovered_health)),
        (f"恢复{_resource_name(view, SPIRIT_CURRENT)}", _number(result.recovered_spirit)),
    )
    if result.character is not None:
        builder.row(
            (
                _resource_name(view, HEALTH_CURRENT),
                f"{_number(result.character.resources[HEALTH_CURRENT])}/{_number(result.health_maximum)}",
            ),
            (
                _resource_name(view, SPIRIT_CURRENT),
                f"{_number(result.character.resources[SPIRIT_CURRENT])}/{_number(result.spirit_maximum)}",
            ),
        )
    if result.progress_ratio <= 0:
        builder.note("累计休息尚未达到一分钟，本次没有恢复。")
    return builder.build()


async def _failed(title: str, character_id: str, exc: Exception) -> None:
    await send_command_failure(title, character_id, exc, _unavailable())


def _view(current: CurrentCharacterResult):
    if current.character_world is None:
        raise RuntimeError("休息命令缺少角色界相")
    return current_game_services().world_view(current.character_world)


def _resource_name(view, resource_id: str) -> str:
    return view.projector.name(resource_id).removeprefix("当前")


def _evidence_id() -> str:
    context = current_message_context()
    if context is None:
        raise RuntimeError("休息命令缺少消息上下文")
    return context.identity.evidence_id


def _duration(seconds: int) -> str:
    minutes, remainder = divmod(max(0, seconds), 60)
    return f"{minutes}分{remainder}秒" if remainder else f"{minutes}分钟"


def _number(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _unavailable() -> DocumentMessage:
    return M.document().section("休息", icon="notice").line(
        "当前没有读取到角色状态，请稍后重试"
    ).build()


__all__ = ["start", "stop"]
