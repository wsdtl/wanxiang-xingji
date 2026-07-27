"""组队组件共享的身份、时间和基础回复工具。"""

from __future__ import annotations

from game.app import CurrentCharacterResult, current_game_services
from game.core.account import ExternalIdentity
from launch.adapter import current_message_context
from message import Action, DocumentMessage, M

from ..command_helpers import command_time
from ..reply import send_command_failure


def character(current: CurrentCharacterResult):
    return current.character if current.status == "ok" else None


def resolve_target(external_id: str):
    context = current_message_context()
    if context is None:
        raise RuntimeError("队伍命令缺少消息上下文")
    claim = context.identity.primary
    identity = ExternalIdentity(
        claim.provider_id,
        claim.tenant_id,
        claim.subject_kind,
        claim.scope_id,
        external_id,
    )
    services = current_game_services()
    account = services.accounts.find_existing_account(identity)
    return services.characters.load_for_account(account.id) if account is not None else None


def character_name(character_id: str) -> str:
    value = current_game_services().characters.load_character(character_id)
    return value.name if value is not None else "无名行者"


def world_name(world_id: str) -> str:
    return current_game_services().world_views.require(world_id).skin.name


def operation_id(prefix: str) -> str:
    context = current_message_context()
    if context is None:
        raise RuntimeError("队伍命令缺少消息上下文")
    return f"{prefix}:{context.identity.evidence_id}"


async def failed(title: str, character_id: str, exc: Exception) -> None:
    await send_command_failure(
        title,
        character_id,
        exc,
        failure("当前操作没有完成，请稍后重试", party_action("重试")),
    )


def success(title: str, text: str, recovery: Action) -> DocumentMessage:
    return (
        M.document()
        .section(title, icon="player")
        .line(text)
        .action(recovery)
        .build()
    )


def failure(text: str, recovery: Action) -> DocumentMessage:
    return (
        M.document()
        .section("组队", icon="notice")
        .line(text)
        .action(recovery)
        .build()
    )


def character_action() -> Action:
    return Action("party.character", "查看角色", "我的角色", style="secondary")


def party_action(label: str = "返回队伍") -> Action:
    return Action("party.back", label, "队伍", style="secondary")


def create_action() -> Action:
    return Action("party.create", "创建队伍", "创建队伍")


def invite_action(label: str = "邀请玩家") -> Action:
    return Action("party.invite", label, "邀请组队 ", behavior="fill")


def sparring_action(label: str = "选择对手") -> Action:
    return Action("party.sparring", label, "组队切磋 ", behavior="fill")


def challenge_action(label: str = "返回挑战") -> Action:
    return Action("party.challenge", label, "组队挑战", style="secondary")


__all__ = [
    "character",
    "character_action",
    "character_name",
    "challenge_action",
    "command_time",
    "create_action",
    "failed",
    "failure",
    "invite_action",
    "operation_id",
    "party_action",
    "resolve_target",
    "sparring_action",
    "success",
    "world_name",
]
