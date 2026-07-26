"""临时队伍定义、成员、状态和原子命令。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from ..events import RuleEvent
from ..ids import StableId, stable_id
from ..registry import DefinitionRegistry


class PartyStatus(str, Enum):
    ACTIVE = "active"
    DISBANDED = "disbanded"


@dataclass(frozen=True)
class PartyDefinition:
    """内容包声明的队伍容量；名称和玩法规则由上层提供。"""

    id: StableId
    capacity: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", stable_id(self.id, field="party definition id"))
        if self.capacity < 2:
            raise ValueError("队伍容量至少为 2")


class PartyCatalog:
    def __init__(self) -> None:
        self.definitions = DefinitionRegistry[PartyDefinition]("Party")
        self._finalized = False

    def register(self, definition: PartyDefinition) -> PartyDefinition:
        if self._finalized:
            raise RuntimeError("队伍目录已经完成组装")
        return self.definitions.register(definition)

    def require(self, definition_id: StableId) -> PartyDefinition:
        return self.definitions.require(definition_id)

    def finalize(self) -> None:
        if self._finalized:
            return
        self.definitions.freeze()
        self._finalized = True

    @property
    def finalized(self) -> bool:
        return self._finalized


@dataclass(frozen=True)
class PartyMember:
    subject_id: str
    slot: int
    joined_at: datetime
    ready: bool = False

    def __post_init__(self) -> None:
        if not self.subject_id.strip() or self.slot < 0:
            raise ValueError("队伍成员身份或站位无效")
        _aware(self.joined_at, "PartyMember.joined_at")


@dataclass(frozen=True)
class Party:
    id: str
    definition_id: StableId
    leader_id: str
    members: Mapping[str, PartyMember]
    created_at: datetime
    status: PartyStatus = PartyStatus.ACTIVE

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.leader_id.strip():
            raise ValueError("队伍身份或队长身份无效")
        object.__setattr__(
            self,
            "definition_id",
            stable_id(self.definition_id, field="party definition id"),
        )
        _aware(self.created_at, "Party.created_at")
        members = dict(self.members)
        if not members or any(key != value.subject_id for key, value in members.items()):
            raise ValueError("队伍成员映射为空或身份不一致")
        if len({value.slot for value in members.values()}) != len(members):
            raise ValueError("队伍成员站位不能重复")
        status = PartyStatus(self.status)
        if self.leader_id not in members:
            raise ValueError("队长必须属于队伍")
        object.__setattr__(self, "members", MappingProxyType(members))
        object.__setattr__(self, "status", status)


@dataclass(frozen=True)
class PartyState:
    """一个队伍分片的不可变状态；跨分片成员排他由持久化唯一索引保证。"""

    scope_id: str
    parties: Mapping[str, Party] = field(default_factory=dict)
    revision: int = 0

    def __post_init__(self) -> None:
        if not self.scope_id.strip() or self.revision < 0:
            raise ValueError("队伍状态分片或 revision 无效")
        parties = dict(self.parties)
        if any(key != value.id for key, value in parties.items()):
            raise ValueError("队伍映射键与队伍 ID 不一致")
        active_members: set[str] = set()
        for party in parties.values():
            if party.status is not PartyStatus.ACTIVE:
                continue
            overlap = active_members & set(party.members)
            if overlap:
                raise ValueError("同一主体不能同时属于多支活跃队伍")
            active_members.update(party.members)
        object.__setattr__(self, "parties", MappingProxyType(parties))


@dataclass(frozen=True)
class CreateParty:
    party_id: str
    definition_id: StableId

    def __post_init__(self) -> None:
        if not self.party_id.strip():
            raise ValueError("CreateParty 缺少 party_id")
        object.__setattr__(
            self,
            "definition_id",
            stable_id(self.definition_id, field="party definition id"),
        )


@dataclass(frozen=True)
class AddPartyMember:
    party_id: str
    subject_id: str

    def __post_init__(self) -> None:
        _identities("AddPartyMember", self.party_id, self.subject_id)


@dataclass(frozen=True)
class RemovePartyMember:
    party_id: str
    subject_id: str

    def __post_init__(self) -> None:
        _identities("RemovePartyMember", self.party_id, self.subject_id)


@dataclass(frozen=True)
class LeaveParty:
    party_id: str

    def __post_init__(self) -> None:
        _identities("LeaveParty", self.party_id)


@dataclass(frozen=True)
class TransferPartyLeadership:
    party_id: str
    next_leader_id: str

    def __post_init__(self) -> None:
        _identities("TransferPartyLeadership", self.party_id, self.next_leader_id)


@dataclass(frozen=True)
class SetPartyMemberReady:
    party_id: str
    ready: bool

    def __post_init__(self) -> None:
        _identities("SetPartyMemberReady", self.party_id)
        if not isinstance(self.ready, bool):
            raise ValueError("SetPartyMemberReady.ready 必须是布尔值")


@dataclass(frozen=True)
class SetPartyMemberSlot:
    party_id: str
    subject_id: str
    slot: int

    def __post_init__(self) -> None:
        _identities("SetPartyMemberSlot", self.party_id, self.subject_id)
        if self.slot < 0:
            raise ValueError("队伍站位不能小于 0")


@dataclass(frozen=True)
class DisbandParty:
    party_id: str

    def __post_init__(self) -> None:
        _identities("DisbandParty", self.party_id)


@dataclass(frozen=True)
class PartyCommand:
    id: str
    actor_id: str
    expected_revision: int
    operation: object

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.actor_id.strip() or self.expected_revision < 0:
            raise ValueError("PartyCommand 身份或 revision 无效")


@dataclass(frozen=True)
class PartyExecution:
    command_id: str
    state: PartyState
    party: Party
    events: tuple[RuleEvent, ...]


def _aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} 必须包含时区")


def _identities(label: str, *values: str) -> None:
    if not all(value.strip() for value in values):
        raise ValueError(f"{label} 缺少必要身份")


__all__ = [
    "AddPartyMember",
    "CreateParty",
    "DisbandParty",
    "LeaveParty",
    "Party",
    "PartyCatalog",
    "PartyCommand",
    "PartyDefinition",
    "PartyExecution",
    "PartyMember",
    "PartyState",
    "PartyStatus",
    "RemovePartyMember",
    "SetPartyMemberReady",
    "SetPartyMemberSlot",
    "TransferPartyLeadership",
]
