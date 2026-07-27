"""正式游戏命令的角色访问守卫。"""

from __future__ import annotations

import asyncio

from game.app import CurrentCharacterResult, current_game_services
from game.content.presentation import GAME_NAME
from launch import C, logger
from launch.adapter import (
    CommandGuardContext,
    CommandGuardDecision,
    register_command_guard,
)
from message import Action, DocumentMessage, M

from .command import GAME_ACCESS_PLAYER, GAME_ACCESS_PUBLIC, GAME_METADATA_KEY
from .dependencies import current_identity_evidence


CHARACTER_GUARD_NAME = "game.character_required"
CHARACTER_GUARD_PRIORITY = 200


def register_character_guard() -> None:
    """注册未建档角色守卫；同名注册会覆盖旧实现。"""

    register_command_guard(
        CHARACTER_GUARD_NAME,
        character_required_guard,
        priority=CHARACTER_GUARD_PRIORITY,
    )


async def character_required_guard(
    context: CommandGuardContext,
) -> CommandGuardDecision:
    """只允许已创建角色的玩家访问默认游戏命令。"""

    game_metadata = context.command_metadata.get(GAME_METADATA_KEY)
    if not isinstance(game_metadata, dict):
        return CommandGuardDecision.allow()

    access = str(game_metadata.get("access") or GAME_ACCESS_PLAYER).strip().lower()
    if access == GAME_ACCESS_PUBLIC:
        return CommandGuardDecision.allow()

    evidence = current_identity_evidence(context.message_context.identity)
    try:
        result = await asyncio.to_thread(
            current_game_services().load_current_character,
            evidence,
        )
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(C.fail("角色访问守卫执行失败"), C.kv("evidence", evidence.id))
        )
        result = CurrentCharacterResult("failed")

    if result.status == "ok" and result.character is not None:
        return CommandGuardDecision.allow()
    return CommandGuardDecision.block(
        _blocked_message(result.status),
        reason=f"game_character_{result.status}",
    )


def _blocked_message(status: str) -> DocumentMessage:
    if status == "not_created":
        return (
            M.document()
            .header(GAME_NAME)
            .section("界门登录", icon="world")
            .line("行纪中尚未发现你的化身记录。")
            .note("建立唯一化身，从第一个世界开始写下行纪。")
            .note("发送: 创建角色 名称")
            .actions(
                (
                    Action(
                        "character.create",
                        "创建角色",
                        "创建角色 ",
                        behavior="fill",
                    ),
                )
            )
            .build()
        )
    if status == "identity_conflict":
        return (
            M.document()
            .header(GAME_NAME)
            .section("身份归属冲突", icon="notice")
            .line("当前平台身份对应多个账号，暂时不能执行该命令。")
            .action(Action("guard.help", "查看帮助", "帮助", behavior="callback"))
            .build()
        )
    return (
        M.document()
        .header(GAME_NAME)
        .section("读取失败", icon="notice")
        .line("当前没有读取到角色状态，请稍后重试。")
        .action(Action("guard.retry", "重试", "我的角色", behavior="callback"))
        .build()
    )


register_character_guard()


__all__ = [
    "CHARACTER_GUARD_NAME",
    "CHARACTER_GUARD_PRIORITY",
    "character_required_guard",
    "register_character_guard",
]
