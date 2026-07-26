"""次元灾厄应用服务对命令层公开的稳定结果。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.gameplay import ActivityInstance
from game.features.player_activity import (
    PlayerActivityBlock,
    validate_activity_block_contract,
)
from game.rules.disaster import DimensionalDisasterState, DisasterChallengeReceipt
from game.rules.battle_report import BattleReportReference


@dataclass(frozen=True)
class DimensionalDisasterStorageKinds:
    activity: str
    character: str
    character_world: str
    inventory: str
    loadout: str
    companion_roster: str
    reward_claim: str
    inscription_preference: str


@dataclass(frozen=True)
class DimensionalDisasterView:
    status: str
    event: DimensionalDisasterState | None = None
    activity: ActivityInstance | None = None
    active: bool = False


@dataclass(frozen=True)
class DimensionalDisasterChallengeResult:
    status: str
    event: DimensionalDisasterState | None = None
    activity: ActivityInstance | None = None
    receipt: DisasterChallengeReceipt | None = None
    battle_report: BattleReportReference | None = None
    activity_block: PlayerActivityBlock | None = None

    def __post_init__(self) -> None:
        validate_activity_block_contract(self.status, self.activity_block)


@dataclass(frozen=True)
class DimensionalDisasterMaintenanceResult:
    opened: int = 0
    settled: int = 0


__all__ = [
    "DimensionalDisasterChallengeResult",
    "DimensionalDisasterMaintenanceResult",
    "DimensionalDisasterStorageKinds",
    "DimensionalDisasterView",
]
