"""探险玩法对命令层和装配层公开的稳定模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from game.rules.exploration import (
    ExplorationBatchResult,
    ExplorationState,
    ExplorationVictoryFact,
)
from game.rules.battle_report import content_scoped_report_id
from game.features.player_activity import (
    PlayerActivityBlock,
    validate_activity_block_contract,
)


MAX_EXPLORATION_BATCHES = 144
MAX_CATCH_UP_BATCHES = 144
MAX_DISCOVERABLE_EXPLORATIONS = 1_000


def exploration_battle_report_id(session_id: str, content_fingerprint: str) -> str:
    session = str(session_id or "").strip()
    if not session:
        raise ValueError("探险战报身份缺少会话")
    return content_scoped_report_id(
        f"battle-report:{session}",
        content_fingerprint,
    )


class ExplorationSettlementObserver(Protocol):
    """旁路系统可实现的探险胜利观察端口。"""

    def observe_victory_in_uow(
        self,
        uow,
        fact: ExplorationVictoryFact,
    ) -> "ExplorationSettlementObservation":
        ...


class ExplorationSettlementObservation(Protocol):
    """旁路结算可以追加到本批次展示的通用可堆叠物品。"""

    reward_items: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class ExplorationOperationResult:
    status: str
    state: ExplorationState | None = None
    batches: tuple[ExplorationBatchResult, ...] = ()
    activity_block: PlayerActivityBlock | None = None

    def __post_init__(self) -> None:
        validate_activity_block_contract(self.status, self.activity_block)


@dataclass(frozen=True)
class ExplorationStorageKinds:
    """由组合根注入的持久化聚合类型，不让玩法层导入 SQLite 包。"""

    character: str
    inventory: str
    loadout: str
    companion_roster: str
    loot: str
    reward_claim: str
    weapon: str
    world: str
    character_world: str
    inscription_preference: str


__all__ = [
    "ExplorationOperationResult",
    "ExplorationSettlementObservation",
    "ExplorationSettlementObserver",
    "ExplorationStorageKinds",
    "ExplorationVictoryFact",
    "MAX_EXPLORATION_BATCHES",
    "MAX_CATCH_UP_BATCHES",
    "MAX_DISCOVERABLE_EXPLORATIONS",
    "exploration_battle_report_id",
]
