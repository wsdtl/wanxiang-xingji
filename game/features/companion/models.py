"""伙伴业务公开结果、存储键和幂等回执。"""

from __future__ import annotations

from dataclasses import dataclass

from game.features.player_activity import (
    PlayerActivityBlock,
    validate_activity_block_contract,
)
from game.rules.battle_report import BattleReportReference
from game.rules.companion import (
    CompanionInstance,
    CompanionRosterState,
    CompanionSanctuaryState,
)


@dataclass(frozen=True)
class CompanionStorageKinds:
    character: str
    character_world: str
    inventory: str
    loadout: str
    roster: str
    sanctuary: str
    world: str
    inscription_preference: str


@dataclass(frozen=True)
class CompanionView:
    roster: CompanionRosterState
    sanctuary: CompanionSanctuaryState | None = None


@dataclass(frozen=True)
class CompanionOperationReceipt:
    transaction_id: str
    actor_id: str
    operation: str
    sanctuary_session_id: str = ""
    companion_id: str = ""
    battle_report_id: str = ""
    definition_id: str = ""
    value_before: int = 0
    value_after: int = 0
    quantity: int = 0

    def __post_init__(self) -> None:
        if not self.transaction_id.strip() or not self.actor_id.strip():
            raise ValueError("伙伴业务回执缺少事务或角色 id")
        if not self.operation.strip():
            raise ValueError("伙伴业务回执缺少操作类型")


@dataclass(frozen=True)
class CompanionOperationResult:
    status: str
    roster: CompanionRosterState | None = None
    sanctuary: CompanionSanctuaryState | None = None
    companion: CompanionInstance | None = None
    battle_report: BattleReportReference | None = None
    battle: object | None = None
    previous_preset_id: str | None = None
    definition_id: str = ""
    value_before: int = 0
    value_after: int = 0
    quantity: int = 0
    failure_message: str = ""
    replayed: bool = False
    activity_block: PlayerActivityBlock | None = None

    def __post_init__(self) -> None:
        validate_activity_block_contract(self.status, self.activity_block)


@dataclass(frozen=True)
class CompanionExperienceItemReceipt:
    transaction_id: str
    actor_id: str
    item_asset_id: str
    item_definition_id: str
    companion_id: str
    level_before: int
    level_after: int
    experience_before: int
    experience_after: int
    experience_granted: int


@dataclass(frozen=True)
class CompanionExperienceItemResult:
    status: str
    receipt: CompanionExperienceItemReceipt | None = None
    companion: CompanionInstance | None = None
    failure_message: str = ""
    replayed: bool = False


__all__ = [
    "CompanionOperationReceipt",
    "CompanionOperationResult",
    "CompanionStorageKinds",
    "CompanionView",
    "CompanionExperienceItemReceipt",
    "CompanionExperienceItemResult",
]
