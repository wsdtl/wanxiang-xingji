"""世界移动结果、存储键和版本化地点意图。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.gameplay import StableId, stable_id
from game.features.player_activity import (
    PlayerActivityBlock,
    validate_activity_block_contract,
)


WORLD_LOCATION_INTENT_MARKER = "@world_location"


@dataclass(frozen=True)
class WorldTravelStorageKinds:
    world: str
    character_world: str


@dataclass(frozen=True)
class WorldTravelResult:
    status: str
    anchor_id: StableId | None = None
    activity_block: PlayerActivityBlock | None = None

    def __post_init__(self) -> None:
        validate_activity_block_contract(self.status, self.activity_block)


@dataclass(frozen=True)
class WorldLocationIntent:
    """旧消息防串世界所需的完整地点绑定上下文。"""

    world_id: StableId
    anchor_id: StableId
    function_id: StableId
    binding_version: int

    def __post_init__(self) -> None:
        for field_name, label in (
            ("world_id", "world id"),
            ("anchor_id", "map anchor id"),
            ("function_id", "location function id"),
        ):
            object.__setattr__(
                self,
                field_name,
                stable_id(getattr(self, field_name), field=label),
            )
        if self.binding_version < 1:
            raise ValueError("地点意图绑定版本必须大于 0")

    def command(self, command_name: str = "前往") -> str:
        return (
            f"{command_name} {WORLD_LOCATION_INTENT_MARKER} {self.world_id} "
            f"{self.anchor_id} {self.function_id} {self.binding_version}"
        )

    @classmethod
    def parse(cls, value: object) -> "WorldLocationIntent | None":
        parts = str(value or "").strip().split()
        if len(parts) != 5 or parts[0] != WORLD_LOCATION_INTENT_MARKER:
            return None
        try:
            return cls(parts[1], parts[2], parts[3], int(parts[4]))
        except (TypeError, ValueError):
            return None


__all__ = [
    "WORLD_LOCATION_INTENT_MARKER",
    "WorldLocationIntent",
    "WorldTravelResult",
    "WorldTravelStorageKinds",
]
