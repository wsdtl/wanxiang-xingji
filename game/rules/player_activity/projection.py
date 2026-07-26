"""把通用行动与持续探险合并为唯一的玩家活动事实。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from game.core.gameplay import ActionRecord, ActionSlotKind, ActionState
from game.rules.exploration import ExplorationState, ExplorationStatus


PLAYER_ACTIVITY_RULE_VERSION = "rules.player_activity.v1"


class PlayerActivityKind(str, Enum):
    IDLE = "idle"
    MAIN_ACTION = "main_action"
    EXPLORING = "exploring"
    EXPLORATION_RESTING = "exploration_resting"


@dataclass(frozen=True)
class PlayerActivityProjection:
    """业务阻塞、角色页和恢复入口共同使用的活动投影。"""

    kind: PlayerActivityKind
    exploration: ExplorationState | None = None
    main_action: ActionRecord | None = None
    pending_actions: tuple[ActionRecord, ...] = ()
    consistency_issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", PlayerActivityKind(self.kind))
        object.__setattr__(self, "pending_actions", tuple(self.pending_actions))
        object.__setattr__(self, "consistency_issues", tuple(self.consistency_issues))
        if self.kind in {
            PlayerActivityKind.EXPLORING,
            PlayerActivityKind.EXPLORATION_RESTING,
        }:
            if self.exploration is None or not self.exploration.active:
                raise ValueError("探险活动投影必须引用有效的活动探险")
        elif self.exploration is not None and self.exploration.active:
            raise ValueError("非探险活动投影不能引用活动探险")
        if self.kind is PlayerActivityKind.MAIN_ACTION and self.main_action is None:
            raise ValueError("主要行动投影必须引用行动记录")

    @property
    def active(self) -> bool:
        return self.kind is not PlayerActivityKind.IDLE

    @property
    def exploration_active(self) -> bool:
        return self.kind in {
            PlayerActivityKind.EXPLORING,
            PlayerActivityKind.EXPLORATION_RESTING,
        }

    @property
    def blocking_status(self) -> str | None:
        if self.exploration_active:
            return "exploring"
        if self.kind is PlayerActivityKind.MAIN_ACTION:
            return "main_action_occupied"
        return None

    @property
    def consistent(self) -> bool:
        return not self.consistency_issues


def resolve_player_activity(
    action_state: ActionState | None,
    exploration_state: ExplorationState | None,
) -> PlayerActivityProjection:
    """探险是外层会话，自动休整行动只能作为它的内部实现出现。"""

    running = (
        action_state.running(ActionSlotKind.MAIN)
        if action_state is not None
        else ()
    )
    pending = action_state.completed() if action_state is not None else ()
    active_exploration = (
        exploration_state
        if exploration_state is not None and exploration_state.active
        else None
    )
    issues: list[str] = []
    if len(running) > 1:
        issues.append("multiple_main_actions")

    if active_exploration is not None:
        managed = tuple(
            action
            for action in running
            if _exploration_session_id(action) == active_exploration.session_id
        )
        unrelated = tuple(action for action in running if action not in managed)
        if unrelated:
            issues.append("exploration_with_unrelated_main_action")
        if active_exploration.status is ExplorationStatus.RUNNING:
            if managed:
                issues.append("running_exploration_with_rest_action")
            kind = PlayerActivityKind.EXPLORING
        else:
            if len(managed) != 1:
                issues.append("resting_exploration_action_mismatch")
            kind = PlayerActivityKind.EXPLORATION_RESTING
        return PlayerActivityProjection(
            kind,
            active_exploration,
            managed[0] if managed else None,
            pending,
            tuple(issues),
        )

    orphaned = tuple(
        action for action in running if _exploration_session_id(action) is not None
    )
    if orphaned:
        issues.append("orphaned_exploration_rest_action")
    if running:
        return PlayerActivityProjection(
            PlayerActivityKind.MAIN_ACTION,
            main_action=running[0],
            pending_actions=pending,
            consistency_issues=tuple(issues),
        )
    return PlayerActivityProjection(
        PlayerActivityKind.IDLE,
        pending_actions=pending,
        consistency_issues=tuple(issues),
    )


def _exploration_session_id(action: ActionRecord) -> str | None:
    value = action.snapshot.values.get("exploration_session_id")
    return str(value) if isinstance(value, str) and value else None


__all__ = [
    "PLAYER_ACTIVITY_RULE_VERSION",
    "PlayerActivityKind",
    "PlayerActivityProjection",
    "resolve_player_activity",
]
