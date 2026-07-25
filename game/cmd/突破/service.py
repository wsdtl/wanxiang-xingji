"""境界突破命令的参数、展示和统一消息头衔接。"""

from __future__ import annotations

import asyncio

from game.app import CurrentCharacterResult, current_game_services
from game.content import (
    BREAKTHROUGH_TOKEN_ITEM_ID,
    CHARACTER_LEVEL_PROGRESSION_ID,
    character_realm_for_level,
)
from game.core.gameplay import CharacterState
from game.features.breakthrough import BreakthroughResult
from launch.adapter import MessageContext
from message import Action, DocumentMessage, M

from ..command_helpers import command_time
from ..reply import send_command_failure, send_game_reply


async def breakthrough(
    current: CurrentCharacterResult,
    context: MessageContext | None,
) -> None:
    character = current.character if current.status == "ok" else None
    dimension = current.character_world if current.status == "ok" else None
    if character is None or dimension is None or context is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    services = current_game_services()
    operation_id = f"{context.identity.evidence_id}:breakthrough"
    try:
        result = await asyncio.to_thread(
            services.breakthrough.breakthrough,
            character.id,
            operation_id,
            logical_time=command_time(),
        )
    except Exception as exc:
        await send_command_failure(
            "境界突破失败",
            character.id,
            exc,
            _failure("当前突破没有完成，请稍后重试"),
        )
        return
    view = services.world_view(dimension).projector
    await send_game_reply(_result_message(result, view))


def _result_message(result: BreakthroughResult, projector) -> DocumentMessage:
    character = result.character
    progression = character.progressions.get(CHARACTER_LEVEL_PROGRESSION_ID)
    if progression is None:
        return _failure("角色缺少人物成长轨道")
    realm = character_realm_for_level(progression.level)
    realm_name = projector.name(realm.id)
    if result.status == "broken_through" and result.receipt is not None:
        old_realm = projector.name(character_realm_for_level(result.receipt.level_before).id)
        new_realm = projector.name(character_realm_for_level(result.receipt.level_after).id)
        return (
            M.document()
            .section("境界突破", icon="reward")
            .row(("境界", f"{old_realm} → {new_realm}"), ("等级", f"Lv{result.receipt.level_after}"))
            .field("消耗", f"{projector.name(BREAKTHROUGH_TOKEN_ITEM_ID)} x1")
            .line("血气与灵力已恢复")
            .build()
        )
    if result.status == "replayed" and result.receipt is not None:
        return (
            M.document()
            .section("境界突破", icon="reward")
            .line(f"已完成：{realm_name} Lv{progression.level}")
            .build()
        )
    if result.status == "maximum":
        return M.document().section("境界", icon="notice").line("已经达到最终境界").build()
    if result.status == "item_missing":
        return (
            M.document()
            .section("境界突破", icon="notice")
            .field("当前境界", realm_name)
            .line(f"缺少 {projector.name(BREAKTHROUGH_TOKEN_ITEM_ID)}")
            .action(
                Action(
                    "breakthrough.draw_pool",
                    "查看奖池",
                    "抽奖奖池",
                    style="secondary",
                )
            )
            .build()
        )
    if result.status == "experience_incomplete":
        required = _required_experience(character)
        return (
            M.document()
            .section("境界突破", icon="notice")
            .field("当前境界", realm_name)
            .line(f"经验尚未积满：{progression.experience}/{required}")
            .action(Action("breakthrough.explore", "前往探险", "探险", style="secondary"))
            .build()
        )
    if result.status == "not_at_cap":
        return (
            M.document()
            .section("境界突破", icon="notice")
            .line(f"当前为 {realm_name} Lv{progression.level}，尚未到达关隘")
            .action(Action("breakthrough.explore", "前往探险", "探险", style="secondary"))
            .build()
        )
    return _failure(result.failure_message or "当前不能突破")


def _required_experience(character: CharacterState) -> int:
    progression = character.progressions[CHARACTER_LEVEL_PROGRESSION_ID]
    return current_game_services().content.catalog.characters.progressions.require(
        CHARACTER_LEVEL_PROGRESSION_ID
    ).required_for_next_level(progression.level) or 0


def _failure(message: str) -> DocumentMessage:
    return M.document().section("境界突破", icon="notice").line(message).build()


__all__ = ["breakthrough"]
