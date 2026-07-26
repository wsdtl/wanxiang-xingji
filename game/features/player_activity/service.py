"""所有玩法读取玩家当前活动的唯一业务端口。"""

from game.core.gameplay import ActionState
from game.rules.exploration import ExplorationState
from game.rules.player_activity import PlayerActivityProjection, resolve_player_activity

from .models import PlayerActivityBlock, PlayerActivityStorageKinds


class PlayerActivityFeature:
    """在调用方事务内合并行动与探险快照，不拥有写模型。"""

    def __init__(self, database, snapshots, storage: PlayerActivityStorageKinds) -> None:
        self.database = database
        self.snapshots = snapshots
        self.storage = storage

    def load(self, character_id: str) -> PlayerActivityProjection:
        with self.database.unit_of_work(write=False) as uow:
            return self.load_in_uow(uow, character_id)

    def load_in_uow(self, uow, character_id: str) -> PlayerActivityProjection:
        normalized_id = str(character_id or "").strip()
        if not normalized_id:
            raise ValueError("玩家活动读取缺少角色")
        action = self.snapshots.load(
            uow,
            self.storage.action,
            normalized_id,
            ActionState,
        )
        exploration = self.snapshots.load(
            uow,
            self.storage.exploration,
            normalized_id,
            ExplorationState,
        )
        return resolve_player_activity(action, exploration)

    def block_in_uow(self, uow, character_id: str) -> PlayerActivityBlock | None:
        return PlayerActivityBlock.from_projection(
            character_id,
            self.load_in_uow(uow, character_id),
        )


__all__ = ["PlayerActivityFeature"]
