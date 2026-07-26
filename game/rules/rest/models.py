"""休息恢复窗口的持久状态与稳定结果。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.gameplay import ActionRecord, CharacterState


REST_RECOVERY_AGGREGATE = "snapshot.rest_recovery"
REST_RULESET_VERSION = "rules.rest.v2"


@dataclass(frozen=True)
class RestRecoveryState:
    """累计实际休息时间，防止重复领取首分钟恢复。"""

    character_id: str
    baseline_health: float
    baseline_spirit: float
    last_health: float
    last_spirit: float
    accumulated_seconds: float = 0.0
    revision: int = 0

    def __post_init__(self) -> None:
        if not self.character_id.strip():
            raise ValueError("休息恢复状态缺少角色 ID")
        values = (
            self.baseline_health,
            self.baseline_spirit,
            self.last_health,
            self.last_spirit,
            self.accumulated_seconds,
        )
        if any(value < 0 for value in values) or self.revision < 0:
            raise ValueError("休息恢复状态数值不能小于 0")


@dataclass(frozen=True)
class RestOperationResult:
    status: str
    character: CharacterState | None = None
    action: ActionRecord | None = None
    recovery: RestRecoveryState | None = None
    health_maximum: float = 0.0
    spirit_maximum: float = 0.0
    recovered_health: float = 0.0
    recovered_spirit: float = 0.0
    progress_ratio: float = 0.0
    failure_message: str = ""


__all__ = [
    "REST_RECOVERY_AGGREGATE",
    "REST_RULESET_VERSION",
    "RestOperationResult",
    "RestRecoveryState",
]
