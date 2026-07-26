"""正式游戏命令共享的紧凑展示规则。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from game.content import CHARACTER_LEVEL_PROGRESSION_ID, character_realm_for_level
from game.core.gameplay import CharacterState, SkinProjector
from game.features.player_activity import PlayerActivityBlock
from game.rules.character import CharacterSettingsState
from game.rules.exploration import ExplorationState
from game.rules.player_activity import (
    PlayerActivityKind,
    PlayerActivityProjection,
    resolve_player_activity,
)
from message import Action


MOOD_HEADER_COLORS = (
    "#FF8C00",
    "#9ACD32",
    "#1ABC9C",
    "#2980B9",
    "#8E44AD",
    "#9B59B6",
    "#FF69B4",
)


@dataclass(frozen=True)
class ActivityBlockFeedback:
    text: str
    recovery: Action | None


@dataclass(frozen=True)
class HealthDepletedFeedback:
    text: str
    recoveries: tuple[Action, ...]


def character_level(character: CharacterState) -> int:
    """读取人物主等级，不依赖成长轨道遍历顺序。"""

    return character.progressions[CHARACTER_LEVEL_PROGRESSION_ID].level


def character_header_parts(
    character: CharacterState,
    projector: SkinProjector,
) -> tuple[str, str, str]:
    """构造不主动换行的“境界短名 + 名字 + 等级”人物头。"""

    level = character_level(character)
    realm = character_realm_for_level(level)
    return (
        projector.compact_name(realm.id),
        f" {character.name}",
        f" Lv{level}",
    )


def character_realm_name(
    character: CharacterState,
    projector: SkinProjector,
) -> str:
    """读取角色详情使用的完整境界名。"""

    return projector.name(character_realm_for_level(character_level(character)).id)


def character_header_color(
    settings: CharacterSettingsState,
    logical_time: datetime,
) -> str:
    """按角色开关和星期返回已验证的人物头颜色。"""

    if not settings.mood_header_enabled:
        return ""
    return MOOD_HEADER_COLORS[logical_time.weekday()]


def active_exploration_status_text(state: ExplorationState | None) -> str | None:
    """把探险活动投影为所有命令共用的玩家状态。"""

    activity = resolve_player_activity(None, state)
    return (
        player_activity_status_text(activity)
        if activity.exploration_active
        else None
    )


def player_activity_status_text(activity: PlayerActivityProjection) -> str:
    """玩家活动名称只在这一处映射，避免各命令自行猜测。"""

    return {
        PlayerActivityKind.IDLE: "空闲",
        PlayerActivityKind.MAIN_ACTION: "主要行动中",
        PlayerActivityKind.EXPLORING: "探险中",
        PlayerActivityKind.EXPLORATION_RESTING: "自动休整中",
    }[activity.kind]


def activity_block_feedback(
    block: PlayerActivityBlock,
    operation: str,
    *,
    subject_name: str = "",
    allow_recovery: bool = True,
) -> ActivityBlockFeedback:
    """把精确活动阻塞事实统一翻译为原因与恢复入口。"""

    operation = str(operation or "").strip()
    if not operation:
        raise ValueError("玩家活动阻塞展示缺少目标操作")
    subject = str(subject_name or "").strip() or "当前"
    activity_text = {
        PlayerActivityKind.EXPLORING: "正在探险",
        PlayerActivityKind.EXPLORATION_RESTING: "正在自动休整",
        PlayerActivityKind.MAIN_ACTION: "正在进行主要行动",
    }[block.kind]
    resolution = "停止探险" if block.status == "exploring" else "结束当前行动"
    return ActivityBlockFeedback(
        f"{subject}{activity_text}，{resolution}后才能{operation}",
        blocking_activity_recovery_action(block) if allow_recovery else None,
    )


def blocking_activity_recovery_action(
    status: str | PlayerActivityBlock,
) -> Action:
    """为统一阻塞状态返回可恢复的完整命令按钮。"""

    status = status.status if isinstance(status, PlayerActivityBlock) else status
    if status == "exploring":
        return Action(
            "game.stop_exploration",
            "停止探险",
            "停止探险",
            behavior="callback",
        )
    if status == "main_action_occupied":
        return current_action_action()
    raise ValueError(f"未知玩家活动阻塞状态：{status}")


def health_depleted_feedback(
    operation: str,
    *,
    subject_name: str = "",
    allow_recovery: bool = True,
) -> HealthDepletedFeedback:
    """统一真实战斗入口的血气阻塞说明与恢复动作。"""

    operation = str(operation or "").strip()
    if not operation:
        raise ValueError("血气阻塞展示缺少目标操作")
    name = str(subject_name or "").strip()
    subject = f"{name}的" if name else "当前"
    recoveries = (
        (
            Action("game.rest", "休息", "休息"),
            Action(
                "game.inventory",
                "查看纳戒",
                "纳戒",
                style="secondary",
            ),
        )
        if allow_recovery
        else ()
    )
    return HealthDepletedFeedback(
        f"{subject}血气已经归零，恢复后才能{operation}",
        recoveries,
    )


def current_action_action() -> Action:
    """为主要行动冲突提供统一的可操作入口。"""

    return Action(
        "game.current_action",
        "查看行动",
        "我的角色",
        behavior="callback",
        style="secondary",
    )


__all__ = [
    "ActivityBlockFeedback",
    "HealthDepletedFeedback",
    "MOOD_HEADER_COLORS",
    "active_exploration_status_text",
    "activity_block_feedback",
    "blocking_activity_recovery_action",
    "character_header_color",
    "character_header_parts",
    "character_level",
    "character_realm_name",
    "current_action_action",
    "health_depleted_feedback",
    "player_activity_status_text",
]
