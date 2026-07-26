"""跨玩法共用的玩家活动存储契约与阻塞事实。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from game.rules.player_activity import PlayerActivityKind, PlayerActivityProjection


ACTIVITY_BLOCK_STATUS_MAP = {
    "exploring": "exploring",
    "main_action_occupied": "main_action_occupied",
}


@dataclass(frozen=True)
class PlayerActivityStorageKinds:
    action: str
    exploration: str

    def __post_init__(self) -> None:
        if not self.action.strip() or not self.exploration.strip():
            raise ValueError("玩家活动存储类型不能为空")


@dataclass(frozen=True)
class PlayerActivityBlock:
    """跨玩法结果共用的精确活动阻塞事实。"""

    character_id: str
    kind: PlayerActivityKind

    def __post_init__(self) -> None:
        character_id = str(self.character_id or "").strip()
        kind = PlayerActivityKind(self.kind)
        if not character_id:
            raise ValueError("玩家活动阻塞缺少角色")
        if kind is PlayerActivityKind.IDLE:
            raise ValueError("空闲状态不能构成业务阻塞")
        object.__setattr__(self, "character_id", character_id)
        object.__setattr__(self, "kind", kind)

    @property
    def status(self) -> str:
        if self.kind in {
            PlayerActivityKind.EXPLORING,
            PlayerActivityKind.EXPLORATION_RESTING,
        }:
            return "exploring"
        return "main_action_occupied"

    @classmethod
    def from_projection(
        cls,
        character_id: str,
        activity: PlayerActivityProjection,
    ) -> "PlayerActivityBlock | None":
        return cls(character_id, activity.kind) if activity.active else None


def validate_activity_block_contract(
    status: str,
    block: PlayerActivityBlock | None,
    *,
    status_map: Mapping[str, str] = ACTIVITY_BLOCK_STATUS_MAP,
    require: bool = True,
) -> None:
    """防止结果状态与精确活动事实再次分裂。"""

    expected = status_map.get(str(status))
    if expected is None:
        if block is not None:
            raise ValueError("非活动阻塞结果不能携带玩家活动阻塞")
        return
    if block is None:
        if require:
            raise ValueError("活动阻塞结果缺少精确玩家活动事实")
        return
    if block.status != expected:
        raise ValueError("结果状态与玩家活动阻塞事实不一致")


__all__ = [
    "ACTIVITY_BLOCK_STATUS_MAP",
    "PlayerActivityBlock",
    "PlayerActivityStorageKinds",
    "validate_activity_block_contract",
]
