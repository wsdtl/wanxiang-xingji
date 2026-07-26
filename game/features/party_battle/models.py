"""组队挑战的持久化状态和命令层结果。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Mapping

from game.content.catalog import CHARACTER_MAXIMUM_LEVEL
from game.content.catalog.social import PARTY_BATTLE_DAILY_REWARD_WINS
from game.core.gameplay import EnemyEncounterInstance, StableId, stable_id
from game.features.player_activity import (
    PlayerActivityBlock,
    validate_activity_block_contract,
)


PARTY_BATTLE_CHALLENGE_AGGREGATE = "game.party_battle.challenge"
PARTY_BATTLE_DAILY_AGGREGATE = "game.party_battle.daily"
PARTY_BATTLE_RULE_VERSION = "rules.party_battle.v1"
PARTY_BATTLE_SOURCE_KIND = "reward.party_battle"
PARTY_BATTLE_DAILY_WINS = PARTY_BATTLE_DAILY_REWARD_WINS


@dataclass(frozen=True)
class PartyBattleChallengeState:
    party_id: str
    session_id: str
    selected_by: str
    source_world_id: StableId
    level: int
    encounter: EnemyEncounterInstance
    member_slots: Mapping[str, int]
    ready_fingerprints: Mapping[str, str] = field(default_factory=dict)
    status: str = "selected"
    attempt_count: int = 0
    report_id: str | None = None
    selected_at: datetime | None = None
    revision: int = 0

    def __post_init__(self) -> None:
        if not self.party_id.strip() or not self.session_id.strip() or not self.selected_by.strip():
            raise ValueError("组队挑战缺少队伍、会话或发起人")
        object.__setattr__(self, "source_world_id", stable_id(self.source_world_id))
        if not 1 <= self.level <= CHARACTER_MAXIMUM_LEVEL:
            raise ValueError(
                f"组队挑战等级必须位于 1 到 {CHARACTER_MAXIMUM_LEVEL}"
            )
        if self.status not in {"selected", "completed"}:
            raise ValueError("未知组队挑战状态")
        if self.attempt_count < 0:
            raise ValueError("组队挑战尝试次数不能小于 0")
        if self.selected_at is not None and (
            self.selected_at.tzinfo is None or self.selected_at.utcoffset() is None
        ):
            raise ValueError("组队挑战选择时间必须包含时区")
        members = {str(key): int(value) for key, value in self.member_slots.items()}
        if not members or len(set(members.values())) != len(members):
            raise ValueError("组队挑战必须保存不重复的成员站位")
        if any(not key.strip() or value < 0 for key, value in members.items()):
            raise ValueError("组队挑战成员站位无效")
        fingerprints = {str(key): str(value) for key, value in self.ready_fingerprints.items()}
        if not set(fingerprints).issubset(members):
            raise ValueError("组队挑战准备状态引用了队伍外成员")
        if any(not key.strip() or not value.strip() for key, value in fingerprints.items()):
            raise ValueError("组队挑战准备指纹不能为空")
        if self.report_id is not None and not self.report_id.strip():
            raise ValueError("组队挑战战报 ID 不能为空")
        if self.revision < 0:
            raise ValueError("组队挑战 revision 不能小于 0")
        object.__setattr__(self, "member_slots", MappingProxyType(members))
        object.__setattr__(self, "ready_fingerprints", MappingProxyType(fingerprints))


@dataclass(frozen=True)
class PartyBattleDailyState:
    character_id: str
    business_day: str
    reward_wins: int = 0
    first_clear_ids: frozenset[StableId] = frozenset()
    revision: int = 0

    def __post_init__(self) -> None:
        if not self.character_id.strip() or not self.business_day.strip():
            raise ValueError("组队挑战每日状态缺少角色或业务日")
        if self.reward_wins < 0 or self.reward_wins > PARTY_BATTLE_DAILY_WINS:
            raise ValueError("组队挑战每日胜利次数无效")
        if self.revision < 0:
            raise ValueError("组队挑战每日状态 revision 无效")
        object.__setattr__(
            self,
            "first_clear_ids",
            frozenset(stable_id(value) for value in self.first_clear_ids),
        )


@dataclass(frozen=True)
class PartyBattleSelectionResult:
    status: str
    challenge: PartyBattleChallengeState | None = None
    failure_message: str = ""
    activity_block: PlayerActivityBlock | None = None

    def __post_init__(self) -> None:
        validate_activity_block_contract(self.status, self.activity_block)


@dataclass(frozen=True)
class PartyBattleResult:
    status: str
    challenge: PartyBattleChallengeState | None = None
    report_id: str | None = None
    share_id: str | None = None
    victory: bool = False
    draw: bool = False
    turns: int = 0
    enemy_name: str = ""
    reward_summaries: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    failure_message: str = ""
    activity_block: PlayerActivityBlock | None = None
    blocked_character_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reward_summaries",
            MappingProxyType({str(key): tuple(value) for key, value in self.reward_summaries.items()}),
        )
        validate_activity_block_contract(
            self.status,
            self.activity_block,
            status_map={
                "member_exploring": "exploring",
                "member_main_action_occupied": "main_action_occupied",
            },
        )
        blocked_character_id = str(self.blocked_character_id or "").strip()
        if self.status in {"health_depleted", "loadout_changed"}:
            if not blocked_character_id:
                raise ValueError("组队挑战阻塞结果缺少对应成员")
        elif blocked_character_id:
            raise ValueError("非成员状态阻塞结果不能携带对应成员")
        object.__setattr__(self, "blocked_character_id", blocked_character_id)


@dataclass(frozen=True)
class PartyBattleOperationReceipt:
    """命令幂等凭据；战斗奖励和战报引用必须绑定同一个操作。"""

    operation_id: str
    actor_id: str
    action: str
    status: str
    report_id: str | None = None
    share_id: str | None = None
    victory: bool = False
    draw: bool = False
    turns: int = 0
    enemy_name: str = ""
    reward_summaries: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.operation_id.strip() or not self.actor_id.strip() or not self.action.strip():
            raise ValueError("组队挑战操作凭据缺少身份")
        if self.report_id is not None and not self.report_id.strip():
            raise ValueError("组队挑战操作凭据的战报 ID 不能为空")
        object.__setattr__(
            self,
            "reward_summaries",
            MappingProxyType({str(key): tuple(value) for key, value in self.reward_summaries.items()}),
        )


__all__ = [name for name in globals() if not name.startswith("_")]
