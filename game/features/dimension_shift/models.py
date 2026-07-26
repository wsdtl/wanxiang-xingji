"""跃迁业务结果与存储键。"""

from dataclasses import dataclass

from game.core.gameplay import StableId
from game.features.player_activity import (
    PlayerActivityBlock,
    validate_activity_block_contract,
)
from game.rules.character import CharacterWorldState, WorldShiftResult


@dataclass(frozen=True)
class DimensionShiftResult:
    status: str
    current: CharacterWorldState | None = None
    previous_world_id: StableId | None = None
    activity_block: PlayerActivityBlock | None = None

    def __post_init__(self) -> None:
        validate_activity_block_contract(self.status, self.activity_block)

    @classmethod
    def from_rule(cls, result: WorldShiftResult) -> "DimensionShiftResult":
        return cls(result.status, result.current, result.previous_world_id)


@dataclass(frozen=True)
class DimensionShiftStorageKinds:
    character_world: str
    world: str
    inventory: str


__all__ = ["DimensionShiftResult", "DimensionShiftStorageKinds"]
