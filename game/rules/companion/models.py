"""伙伴名册、实例和一次性秘境状态。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from game.core.gameplay import StableId, stable_id


COMPANION_ROSTER_AGGREGATE = "game.companion.roster"
COMPANION_SANCTUARY_AGGREGATE = "game.companion.sanctuary"
COMPANION_RULESET_VERSION = "ruleset.companion.v3"

APTITUDE_VITALITY = "companion.aptitude.vitality"
APTITUDE_OFFENSE = "companion.aptitude.offense"
APTITUDE_AGILITY = "companion.aptitude.agility"
APTITUDE_FOCUS = "companion.aptitude.focus"
COMPANION_APTITUDE_IDS = (
    APTITUDE_VITALITY,
    APTITUDE_OFFENSE,
    APTITUDE_AGILITY,
    APTITUDE_FOCUS,
)


class CompanionSanctuaryStatus(str, Enum):
    OPEN = "open"
    TRACKING = "tracking"
    CAPTURED = "captured"
    ABANDONED = "abandoned"
    EXPIRED = "expired"


class CompanionKind(str, Enum):
    PET = "pet"
    PERSON = "person"


class CompanionAcquisitionKind(str, Enum):
    SANCTUARY_CAPTURE = "sanctuary_capture"
    PERSON_BOND = "person_bond"


@dataclass(frozen=True)
class CompanionInstance:
    """进入名册后由宠物和人物共同使用的伙伴实例。"""

    id: str
    reference: str
    owner_id: str
    definition_id: StableId
    origin_world_id: StableId
    quality_id: StableId
    level: int
    experience: int
    total_experience: int
    aptitudes: Mapping[StableId, int]
    trait_behavior_id: StableId
    kind: CompanionKind
    acquired_at: datetime
    acquisition_kind: CompanionAcquisitionKind
    acquisition_id: str

    def __post_init__(self) -> None:
        if not str(self.id or "").strip() or not str(self.owner_id or "").strip():
            raise ValueError("伙伴实例缺少 id 或 owner_id")
        reference = str(self.reference or "").strip().upper()
        if not reference.startswith("C") or not reference[1:].isdigit():
            raise ValueError("伙伴实例引用必须使用 C数字")
        if self.level < 1 or self.level > 100:
            raise ValueError("伙伴等级必须位于 1 至 100")
        if self.experience < 0 or self.total_experience < self.experience:
            raise ValueError("伙伴经验无效")
        aptitudes = {
            stable_id(key, field="companion aptitude id"): int(value)
            for key, value in self.aptitudes.items()
        }
        if set(aptitudes) != set(COMPANION_APTITUDE_IDS):
            raise ValueError("伙伴实例必须完整保存四项资质")
        if any(value < 60 or value > 140 for value in aptitudes.values()):
            raise ValueError("伙伴单项资质必须位于 60 至 140")
        if self.acquired_at.tzinfo is None or self.acquired_at.utcoffset() is None:
            raise ValueError("伙伴获得时间必须包含时区")
        kind = CompanionKind(self.kind)
        acquisition_kind = CompanionAcquisitionKind(self.acquisition_kind)
        expected = {
            CompanionKind.PET: CompanionAcquisitionKind.SANCTUARY_CAPTURE,
            CompanionKind.PERSON: CompanionAcquisitionKind.PERSON_BOND,
        }[kind]
        if acquisition_kind is not expected or not str(self.acquisition_id or "").strip():
            raise ValueError("伙伴类别与获得来源不一致")
        object.__setattr__(self, "reference", reference)
        object.__setattr__(self, "definition_id", stable_id(self.definition_id))
        object.__setattr__(self, "origin_world_id", stable_id(self.origin_world_id))
        object.__setattr__(self, "quality_id", stable_id(self.quality_id))
        object.__setattr__(
            self,
            "trait_behavior_id",
            stable_id(self.trait_behavior_id),
        )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "acquisition_kind", acquisition_kind)
        object.__setattr__(self, "acquisition_id", str(self.acquisition_id).strip())
        object.__setattr__(self, "aptitudes", MappingProxyType(aptitudes))


@dataclass(frozen=True)
class PersonBondState:
    """一名固定人物与角色之间可持续保留的关系。"""

    definition_id: StableId
    favor: int
    met_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "definition_id",
            stable_id(self.definition_id, field="person companion definition id"),
        )
        if self.favor < 0:
            raise ValueError("人物关系不能小于零")
        if self.met_at.tzinfo is None or self.met_at.utcoffset() is None:
            raise ValueError("人物相识时间必须包含时区")


@dataclass(frozen=True)
class CompanionTrace:
    """开启秘境时已经完全固定、展示时只揭露部分信息的踪迹。"""

    index: int
    definition_id: StableId
    quality_id: StableId
    level: int
    aptitudes: Mapping[StableId, int]
    trait_behavior_id: StableId
    battle_seed: str

    def __post_init__(self) -> None:
        if self.index < 1 or self.level < 1 or self.level > 100:
            raise ValueError("伙伴踪迹编号或等级无效")
        aptitudes = {
            stable_id(key, field="companion aptitude id"): int(value)
            for key, value in self.aptitudes.items()
        }
        if set(aptitudes) != set(COMPANION_APTITUDE_IDS):
            raise ValueError("伙伴踪迹必须完整保存四项资质")
        if any(value < 60 or value > 140 for value in aptitudes.values()):
            raise ValueError("伙伴踪迹资质必须位于 60 至 140")
        if not str(self.battle_seed or "").strip():
            raise ValueError("伙伴踪迹缺少固定战斗种子")
        object.__setattr__(self, "definition_id", stable_id(self.definition_id))
        object.__setattr__(self, "quality_id", stable_id(self.quality_id))
        object.__setattr__(self, "trait_behavior_id", stable_id(self.trait_behavior_id))
        object.__setattr__(self, "aptitudes", MappingProxyType(aptitudes))

    @property
    def battle_level(self) -> int:
        """秘境对手的战斗等级；与入册后的伙伴成长等级分开读取。"""

        return self.level


@dataclass(frozen=True)
class CompanionRosterState:
    """通用伙伴名册、宠物图鉴、人物关系与离队档案。"""

    character_id: str
    instances: Mapping[str, CompanionInstance] = field(default_factory=dict)
    bindings: Mapping[StableId, str] = field(default_factory=dict)
    captured_definition_ids: frozenset[StableId] = frozenset()
    person_bonds: Mapping[StableId, PersonBondState] = field(default_factory=dict)
    departed_people: Mapping[StableId, CompanionInstance] = field(default_factory=dict)
    next_sequence: int = 1
    revision: int = 0

    def __post_init__(self) -> None:
        character_id = str(self.character_id or "").strip()
        if not character_id:
            raise ValueError("伙伴名册缺少 character_id")
        if self.next_sequence < 1 or self.revision < 0:
            raise ValueError("伙伴名册序号或 revision 无效")
        instances = dict(self.instances)
        references = set()
        for key, instance in instances.items():
            if key != instance.id or instance.owner_id != character_id:
                raise ValueError("伙伴名册实例键或归属不一致")
            if instance.reference in references:
                raise ValueError("伙伴名册存在重复玩家引用")
            references.add(instance.reference)
        active_people = [
            value.definition_id for value in instances.values()
            if value.kind is CompanionKind.PERSON
        ]
        if len(active_people) != len(set(active_people)):
            raise ValueError("同一人物伙伴不能同时存在多个实例")
        bindings = {
            stable_id(key, field="companion loadout preset id"): str(value)
            for key, value in self.bindings.items()
        }
        if any(instance_id not in instances for instance_id in bindings.values()):
            raise ValueError("伙伴配装引用了不存在的实例")
        if len(bindings.values()) != len(set(bindings.values())):
            raise ValueError("同一只伙伴不能同时属于多套配装")
        captured = frozenset(
            stable_id(value, field="captured companion definition id")
            for value in self.captured_definition_ids
        )
        bonds = {
            stable_id(key, field="person companion definition id"): value
            for key, value in self.person_bonds.items()
        }
        if any(key != value.definition_id for key, value in bonds.items()):
            raise ValueError("人物关系映射键与 definition_id 不一致")
        departed = {
            stable_id(key, field="person companion definition id"): value
            for key, value in self.departed_people.items()
        }
        for key, instance in departed.items():
            if (
                instance.kind is not CompanionKind.PERSON
                or instance.definition_id != key
                or instance.owner_id != character_id
            ):
                raise ValueError("人物离队档案内容无效")
            if instance.reference in references or key in active_people:
                raise ValueError("人物伙伴不能同时在名册和离队档案中")
            references.add(instance.reference)
        object.__setattr__(self, "character_id", character_id)
        object.__setattr__(self, "instances", MappingProxyType(instances))
        object.__setattr__(self, "bindings", MappingProxyType(bindings))
        object.__setattr__(self, "captured_definition_ids", captured)
        object.__setattr__(self, "person_bonds", MappingProxyType(bonds))
        object.__setattr__(self, "departed_people", MappingProxyType(departed))

    def by_reference(self, reference: object) -> CompanionInstance | None:
        token = str(reference or "").strip().upper()
        return next(
            (value for value in self.instances.values() if value.reference == token),
            None,
        )

    def companion_for_preset(self, preset_id: StableId | None) -> CompanionInstance | None:
        if preset_id is None:
            return None
        instance_id = self.bindings.get(stable_id(preset_id))
        return self.instances.get(instance_id) if instance_id is not None else None

    def preset_for_companion(self, companion_id: str) -> StableId | None:
        return next(
            (preset_id for preset_id, value in self.bindings.items() if value == companion_id),
            None,
        )

    def active_by_definition(self, definition_id: StableId) -> CompanionInstance | None:
        key = stable_id(definition_id, field="companion definition id")
        return next(
            (value for value in self.instances.values() if value.definition_id == key),
            None,
        )


@dataclass(frozen=True)
class CompanionSanctuaryState:
    """一个角色当前或最近一次宠物秘境。"""

    character_id: str
    session_id: str
    sanctuary_id: StableId
    world_id: StableId
    opened_at: datetime
    expires_at: datetime
    traces: tuple[CompanionTrace, ...]
    content_version: str
    status: CompanionSanctuaryStatus = CompanionSanctuaryStatus.OPEN
    selected_trace_index: int | None = None
    attempt_count: int = 0
    captured_companion_id: str | None = None
    revision: int = 0

    def __post_init__(self) -> None:
        if not str(self.character_id or "").strip() or not str(self.session_id or "").strip():
            raise ValueError("宠物秘境缺少角色或会话 id")
        if self.opened_at.tzinfo is None or self.opened_at.utcoffset() is None:
            raise ValueError("宠物秘境时间必须包含时区")
        if self.expires_at <= self.opened_at:
            raise ValueError("宠物秘境结束时间必须晚于开启时间")
        content_version = str(self.content_version or "").strip()
        if not content_version:
            raise ValueError("宠物秘境缺少内容版本")
        object.__setattr__(self, "content_version", content_version)
        indices = tuple(value.index for value in self.traces)
        if not indices or len(indices) != len(set(indices)):
            raise ValueError("宠物秘境踪迹不能为空或重复")
        status = CompanionSanctuaryStatus(self.status)
        if status is CompanionSanctuaryStatus.OPEN and self.selected_trace_index is not None:
            raise ValueError("未追踪秘境不能保存选中踪迹")
        if status is CompanionSanctuaryStatus.TRACKING and self.selected_trace_index not in indices:
            raise ValueError("追踪中的秘境必须保存有效目标")
        if status is CompanionSanctuaryStatus.CAPTURED and not self.captured_companion_id:
            raise ValueError("已捕获秘境必须保存伙伴实例 id")
        if self.attempt_count < 0 or self.revision < 0:
            raise ValueError("宠物秘境尝试次数或 revision 无效")
        object.__setattr__(self, "sanctuary_id", stable_id(self.sanctuary_id))
        object.__setattr__(self, "world_id", stable_id(self.world_id))
        object.__setattr__(self, "status", status)

    @property
    def active(self) -> bool:
        return self.status in {
            CompanionSanctuaryStatus.OPEN,
            CompanionSanctuaryStatus.TRACKING,
        }

    @property
    def reserves_capacity(self) -> bool:
        return self.active

    def selected_trace(self) -> CompanionTrace | None:
        return next(
            (
                value
                for value in self.traces
                if value.index == self.selected_trace_index
            ),
            None,
        )


__all__ = [name for name in globals() if not name.startswith("_")]
