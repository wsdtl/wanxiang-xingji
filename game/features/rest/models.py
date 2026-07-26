"""休息业务对命令层公开的结果。"""

from dataclasses import dataclass

from game.core.gameplay import ActionRecord, CharacterState
from game.features.player_activity import (
    PlayerActivityBlock,
    validate_activity_block_contract,
)
from game.rules.rest import RestRecoveryState


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
    activity_block: PlayerActivityBlock | None = None

    def __post_init__(self) -> None:
        validate_activity_block_contract(
            self.status,
            self.activity_block,
            status_map={
                "exploring": "exploring",
                "main_action_occupied": "main_action_occupied",
                "exploration_managed": "exploring",
            },
            require=False,
        )


__all__ = ["RestOperationResult"]
