"""持续探险会话、批次计划与结算摘要。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from game.content.catalog.character import CHARACTER_MAXIMUM_LEVEL
from game.core.gameplay import EnemyEncounterInstance, StableId, stable_id


EXPLORATION_RULESET_VERSION = "rules.exploration.v4"
EXPLORATION_AGGREGATE = "snapshot.exploration"


class ExplorationStatus(str, Enum):
    RUNNING = "running"
    RESTING = "resting"
    STOPPED = "stopped"


class ExplorationStopReason(str, Enum):
    MANUAL = "manual"
    DEFEATED = "defeated"
    CAPACITY_FULL = "capacity_full"
    BATCH_LIMIT = "batch_limit"
    INVALID_LOCATION = "invalid_location"


class ExplorationRestReason(str, Enum):
    DEFEATED = "defeated"
    LOW_RESOURCES = "low_resources"


class ExplorationEncounterKind(str, Enum):
    EMPTY = "empty"
    NORMAL = "normal"
    ELITE = "elite"
    BOSS = "boss"


class ExplorationRewardKind(str, Enum):
    ITEM = "item"
    WEAPON = "weapon"
    EQUIPMENT = "equipment"


@dataclass(frozen=True)
class ExplorationRewardReference:
    """可在任意世界皮肤下重新投影的探险物品引用。"""

    kind: ExplorationRewardKind
    definition_id: StableId
    quantity: int = 1
    asset_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", ExplorationRewardKind(self.kind))
        object.__setattr__(
            self,
            "definition_id",
            stable_id(self.definition_id, field="reward definition id"),
        )
        if self.quantity < 1:
            raise ValueError("探险奖励引用数量必须大于 0")
        asset_id = str(self.asset_id or "").strip() or None
        object.__setattr__(self, "asset_id", asset_id)
        if self.kind is ExplorationRewardKind.ITEM and self.asset_id is not None:
            raise ValueError("可堆叠物品奖励不保存实例 ID")
        if self.kind is not ExplorationRewardKind.ITEM and self.asset_id is None:
            raise ValueError("武器和装备奖励必须保存实例 ID")
        if self.kind is not ExplorationRewardKind.ITEM and self.quantity != 1:
            raise ValueError("单件武器和装备奖励数量必须等于 1")


@dataclass(frozen=True)
class ExplorationBatchPlan:
    session_id: str
    batch_index: int
    region_id: StableId
    location_id: StableId
    encounter_kind: ExplorationEncounterKind
    enemy_level: int
    generation_seed: str
    encounter: EnemyEncounterInstance | None = None
    loot_modifiers: Mapping[StableId, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            not self.session_id.strip()
            or self.batch_index < 1
            or not self.generation_seed.strip()
        ):
            raise ValueError("探险批次计划缺少有效身份")
        object.__setattr__(self, "region_id", stable_id(self.region_id, field="region id"))
        object.__setattr__(self, "location_id", stable_id(self.location_id, field="location id"))
        object.__setattr__(self, "encounter_kind", ExplorationEncounterKind(self.encounter_kind))
        if not 1 <= self.enemy_level <= CHARACTER_MAXIMUM_LEVEL:
            raise ValueError(
                f"探险批次敌人等级必须位于 1 到 {CHARACTER_MAXIMUM_LEVEL}"
            )
        if (self.encounter_kind is ExplorationEncounterKind.EMPTY) != (
            self.encounter is None
        ):
            raise ValueError("空探险批次不能包含遭遇，战斗批次必须包含遭遇")
        object.__setattr__(self, "loot_modifiers", MappingProxyType(dict(self.loot_modifiers)))


@dataclass(frozen=True)
class ExplorationBatchResult:
    plan: ExplorationBatchPlan
    resolved_at: datetime
    victory: bool = False
    draw: bool = False
    health_after: float | None = None
    spirit_after: float | None = None
    character_experience: int = 0
    weapon_experience: int = 0
    companion_experience: int = 0
    weapon_drops: int = 0
    equipment_drops: int = 0
    trophy_drops: int = 0
    medicine_drops: int = 0
    draw_ticket_drops: int = 0
    trophy_value: int = 0
    rewards: tuple[ExplorationRewardReference, ...] = ()
    medicines_used: tuple[ExplorationRewardReference, ...] = ()

    def __post_init__(self) -> None:
        if self.resolved_at.tzinfo is None or self.resolved_at.utcoffset() is None:
            raise ValueError("探险批次结算时间必须包含时区")
        values = (
            self.character_experience,
            self.weapon_experience,
            self.companion_experience,
            self.weapon_drops,
            self.equipment_drops,
            self.trophy_drops,
            self.medicine_drops,
            self.draw_ticket_drops,
            self.trophy_value,
        )
        if any(value < 0 for value in values):
            raise ValueError("探险批次收益不能小于 0")
        rewards = tuple(self.rewards)
        medicines_used = tuple(self.medicines_used)
        if any(value.kind is not ExplorationRewardKind.ITEM for value in medicines_used):
            raise ValueError("探险自动用药记录只能引用可堆叠物品")
        object.__setattr__(self, "rewards", rewards)
        object.__setattr__(self, "medicines_used", medicines_used)


@dataclass(frozen=True)
class ExplorationState:
    character_id: str
    session_id: str
    region_id: StableId
    location_id: StableId
    status: ExplorationStatus
    started_at: datetime
    next_batch_at: datetime
    batch_index: int = 0
    completed_batches: int = 0
    victories: int = 0
    defeats: int = 0
    character_experience: int = 0
    weapon_experience: int = 0
    companion_experience: int = 0
    weapon_drops: int = 0
    equipment_drops: int = 0
    trophy_drops: int = 0
    medicine_drops: int = 0
    draw_ticket_drops: int = 0
    trophy_value: int = 0
    rest_count: int = 0
    rest_seconds: float = 0.0
    rest_reason: ExplorationRestReason | None = None
    rest_started_at: datetime | None = None
    rest_completes_at: datetime | None = None
    stopped_at: datetime | None = None
    stop_reason: ExplorationStopReason | None = None
    last_result: ExplorationBatchResult | None = None
    revision: int = 0

    def __post_init__(self) -> None:
        if not self.character_id.strip() or not self.session_id.strip():
            raise ValueError("探险状态缺少角色或会话身份")
        object.__setattr__(self, "region_id", stable_id(self.region_id, field="region id"))
        object.__setattr__(self, "location_id", stable_id(self.location_id, field="location id"))
        object.__setattr__(self, "status", ExplorationStatus(self.status))
        if self.rest_reason is not None:
            object.__setattr__(self, "rest_reason", ExplorationRestReason(self.rest_reason))
        if self.stop_reason is not None:
            object.__setattr__(self, "stop_reason", ExplorationStopReason(self.stop_reason))
        for field_name in (
            "started_at",
            "next_batch_at",
            "rest_started_at",
            "rest_completes_at",
            "stopped_at",
        ):
            value = getattr(self, field_name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"ExplorationState.{field_name} 必须包含时区")
        counters = (
            self.batch_index,
            self.completed_batches,
            self.victories,
            self.defeats,
            self.character_experience,
            self.weapon_experience,
            self.companion_experience,
            self.weapon_drops,
            self.equipment_drops,
            self.trophy_drops,
            self.medicine_drops,
            self.draw_ticket_drops,
            self.trophy_value,
            self.rest_count,
            self.rest_seconds,
            self.revision,
        )
        if any(value < 0 for value in counters):
            raise ValueError("探险状态计数不能小于 0")
        rest_fields = (
            self.rest_reason,
            self.rest_started_at,
            self.rest_completes_at,
        )
        if self.status is ExplorationStatus.RUNNING:
            if any(value is not None for value in (*rest_fields, self.stopped_at, self.stop_reason)):
                raise ValueError("运行中的探险不能已有休整或停止信息")
        elif self.status is ExplorationStatus.RESTING:
            if any(value is None for value in rest_fields):
                raise ValueError("休整中的探险必须记录原因和时间")
            if self.stopped_at is not None or self.stop_reason is not None:
                raise ValueError("休整中的探险不能已有停止信息")
            assert self.rest_started_at is not None
            assert self.rest_completes_at is not None
            if self.rest_completes_at <= self.rest_started_at:
                raise ValueError("探险休整完成时间必须晚于开始时间")
        else:
            if self.stopped_at is None or self.stop_reason is None:
                raise ValueError("已停止探险必须记录时间和原因")
            if any(value is not None for value in rest_fields):
                raise ValueError("已停止探险不能保留当前休整信息")

    @property
    def active(self) -> bool:
        return self.status is not ExplorationStatus.STOPPED


__all__ = [
    "EXPLORATION_AGGREGATE",
    "EXPLORATION_RULESET_VERSION",
    "ExplorationBatchPlan",
    "ExplorationBatchResult",
    "ExplorationEncounterKind",
    "ExplorationRewardKind",
    "ExplorationRewardReference",
    "ExplorationRestReason",
    "ExplorationState",
    "ExplorationStatus",
    "ExplorationStopReason",
]
