"""武器定义、品质等级表和实例成长状态。"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from ..attributes import ModifierLayer
from ..character import AttributeGrant, ContributionSpec
from ..ids import StableId, stable_id
from ..inventory import ItemAssetKind, ItemCatalog, ItemInstance
from ..itemization import ItemRollState, ItemizationEngine, ItemizationKind
from ..loadout import (
    LOADOUT_ITEM_COMPONENT_ID,
    WEAPON_SLOT_ID,
    LoadoutItemComponent,
    QualityCatalog,
)


WEAPON_STATE_DATA_KEY = "weapon.state"
WEAPON_ABSOLUTE_MAXIMUM_LEVEL = 100
from ..registry import DefinitionRegistry


@dataclass(frozen=True)
class WeaponMaximumLevelBand:
    """一段可抽取的武器天然等级上限。"""

    minimum: int
    maximum: int
    weight: int

    def __post_init__(self) -> None:
        for field_name in ("minimum", "maximum", "weight"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"WeaponMaximumLevelBand.{field_name} 必须是整数")
        if self.minimum < 1 or self.maximum < self.minimum:
            raise ValueError("武器等级上限区间无效")
        if self.maximum > WEAPON_ABSOLUTE_MAXIMUM_LEVEL:
            raise ValueError("武器等级上限区间超过系统绝对上限")
        if self.weight < 1:
            raise ValueError("武器等级上限区间权重必须大于 0")


@dataclass(frozen=True)
class WeaponMaximumLevelTable:
    """正式内容声明的武器天然等级上限概率表。"""

    id: StableId
    version: int
    bands: tuple[WeaponMaximumLevelBand, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", stable_id(self.id, field="weapon maximum level table id"))
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError("武器等级上限概率表版本必须是正整数")
        bands = tuple(self.bands)
        if not bands:
            raise ValueError("武器等级上限概率表不能为空")
        ordered = tuple(sorted(bands, key=lambda value: (value.minimum, value.maximum)))
        for previous, current in zip(ordered, ordered[1:]):
            if current.minimum <= previous.maximum:
                raise ValueError("武器等级上限概率区间不能重叠")
        object.__setattr__(self, "bands", bands)

    @property
    def total_weight(self) -> int:
        return sum(value.weight for value in self.bands)


@dataclass(frozen=True)
class WeaponMaximumLevelRoll:
    """保存一次武器天然等级上限抽取的审计结果。"""

    table_id: StableId
    table_version: int
    band_minimum: int
    band_maximum: int
    sampled_level: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "table_id", stable_id(self.table_id, field="weapon maximum level table id"))
        for field_name in (
            "table_version",
            "band_minimum",
            "band_maximum",
            "sampled_level",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"WeaponMaximumLevelRoll.{field_name} 必须是整数")
        if self.table_version < 1:
            raise ValueError("武器等级上限抽取版本必须大于 0")
        if not 1 <= self.band_minimum <= self.sampled_level <= self.band_maximum:
            raise ValueError("武器等级上限抽取结果不在命中区间内")
        if self.band_maximum > WEAPON_ABSOLUTE_MAXIMUM_LEVEL:
            raise ValueError("武器等级上限抽取超过系统绝对上限")


@dataclass(frozen=True)
class WeaponLevelAttribute:
    """一个属性在每个武器等级的完整贡献值，不使用隐藏成长公式。"""

    attribute_id: StableId
    layer: ModifierLayer
    values: tuple[float, ...]
    priority: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "attribute_id", stable_id(self.attribute_id, field="weapon attribute id"))
        object.__setattr__(self, "layer", ModifierLayer(self.layer))
        values = tuple(float(value) for value in self.values)
        if not values:
            raise ValueError("WeaponLevelAttribute.values 不能为空")
        object.__setattr__(self, "values", values)


@dataclass(frozen=True)
class WeaponQualityProfile:
    quality_id: StableId
    experience_requirements: tuple[int, ...]
    contribution: ContributionSpec = ContributionSpec()
    level_attributes: tuple[WeaponLevelAttribute, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "quality_id", stable_id(self.quality_id, field="quality id"))
        requirements = tuple(int(value) for value in self.experience_requirements)
        if any(value < 1 for value in requirements):
            raise ValueError("武器升级经验需求必须全部大于 0")
        object.__setattr__(self, "experience_requirements", requirements)
        for progression in self.level_attributes:
            if len(progression.values) != self.maximum_level:
                raise ValueError(
                    f"武器属性 {progression.attribute_id} 的等级值数量必须等于 {self.maximum_level}"
                )

    @property
    def maximum_level(self) -> int:
        return len(self.experience_requirements) + 1

    def required_for_next_level(self, level: int) -> int | None:
        if level < 1:
            raise ValueError("武器等级必须大于 0")
        if level >= self.maximum_level:
            return None
        return self.experience_requirements[level - 1]


@dataclass(frozen=True)
class WeaponDefinition:
    id: StableId
    item_definition_id: StableId
    base_contribution: ContributionSpec
    quality_profiles: Mapping[StableId, WeaponQualityProfile]
    generation_profile_id: StableId | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", stable_id(self.id, field="weapon id"))
        object.__setattr__(
            self,
            "item_definition_id",
            stable_id(self.item_definition_id, field="item id"),
        )
        profiles = dict(self.quality_profiles)
        if not profiles:
            raise ValueError("WeaponDefinition.quality_profiles 不能为空")
        for key, profile in profiles.items():
            if stable_id(key, field="quality id") != profile.quality_id:
                raise ValueError("武器品质档案映射键与 quality_id 不一致")
        object.__setattr__(self, "quality_profiles", MappingProxyType(profiles))
        if self.generation_profile_id is not None:
            object.__setattr__(
                self,
                "generation_profile_id",
                stable_id(self.generation_profile_id, field="generation profile id"),
            )


@dataclass(frozen=True)
class WeaponState:
    asset_id: str
    definition_id: StableId
    quality_id: StableId
    level: int = 1
    experience: int = 0
    total_experience: int = 0
    revision: int = 0
    roll: ItemRollState | None = None
    natural_maximum_level: int = WEAPON_ABSOLUTE_MAXIMUM_LEVEL
    maximum_level: int = WEAPON_ABSOLUTE_MAXIMUM_LEVEL
    maximum_level_roll: WeaponMaximumLevelRoll | None = None

    def __post_init__(self) -> None:
        if not self.asset_id.strip():
            raise ValueError("WeaponState 缺少 asset_id")
        object.__setattr__(self, "definition_id", stable_id(self.definition_id, field="weapon id"))
        object.__setattr__(self, "quality_id", stable_id(self.quality_id, field="quality id"))
        for field_name in (
            "level",
            "experience",
            "total_experience",
            "revision",
            "natural_maximum_level",
            "maximum_level",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"WeaponState.{field_name} 必须是整数")
        if self.level < 1 or self.experience < 0 or self.total_experience < 0:
            raise ValueError("武器等级和经验不能小于有效边界")
        if self.experience > self.total_experience:
            raise ValueError("武器当前经验不能大于累计经验")
        if self.revision < 0:
            raise ValueError("WeaponState.revision 不能小于 0")
        if not 1 <= self.natural_maximum_level <= self.maximum_level:
            raise ValueError("武器天然上限不能超过当前等级上限")
        if self.maximum_level > WEAPON_ABSOLUTE_MAXIMUM_LEVEL:
            raise ValueError("武器当前等级上限超过系统绝对上限")
        if self.level > self.maximum_level:
            raise ValueError("武器当前等级不能超过实例等级上限")
        if self.maximum_level_roll is not None:
            if self.maximum_level_roll.sampled_level != self.natural_maximum_level:
                raise ValueError("武器天然上限与抽取记录不一致")


class WeaponCatalog:
    def __init__(
        self,
        qualities: QualityCatalog,
        items: ItemCatalog,
        itemization: ItemizationEngine | None = None,
    ) -> None:
        self.qualities = qualities
        self.items = items
        self.itemization = itemization
        self.definitions = DefinitionRegistry[WeaponDefinition]("Weapon")
        self._finalized = False

    def register(self, definition: WeaponDefinition) -> WeaponDefinition:
        if self._finalized:
            raise RuntimeError("武器目录已经完成组装")
        return self.definitions.register(definition)

    def require(self, definition_id: StableId) -> WeaponDefinition:
        return self.definitions.require(definition_id)

    def finalize(self) -> None:
        if self._finalized:
            return
        if not self.qualities.finalized:
            self.qualities.finalize()
        if not self.items.finalized:
            self.items.finalize()
        quality_ids = set(self.qualities.definitions.ids())
        used_items: set[StableId] = set()
        core_owners: dict[StableId, StableId] = {}
        for definition in self.definitions:
            unknown = set(definition.quality_profiles) - quality_ids
            if unknown:
                raise KeyError(
                    f"武器 {definition.id} 引用了未知品质：{', '.join(sorted(unknown))}"
                )
            if definition.item_definition_id in used_items:
                raise ValueError(f"物品定义重复绑定武器：{definition.item_definition_id}")
            used_items.add(definition.item_definition_id)
            item = self.items.require(definition.item_definition_id)
            if item.asset_kind is not ItemAssetKind.INSTANCE or not item.tags.has("item.weapon"):
                raise ValueError(f"武器 {definition.id} 必须绑定带 item.weapon 标签的独立物品")
            component = item.component(LOADOUT_ITEM_COMPONENT_ID, LoadoutItemComponent)
            if component.allowed_slot_ids != frozenset({WEAPON_SLOT_ID}):
                raise ValueError(f"武器 {definition.id} 只能进入唯一武器槽")
            if definition.generation_profile_id is not None:
                if self.itemization is None:
                    raise ValueError(f"生成型武器 {definition.id} 缺少物品化引擎")
                generation = self.itemization.catalog.require_profile(
                    definition.generation_profile_id
                )
                if generation.kind is not ItemizationKind.WEAPON:
                    raise ValueError(f"武器 {definition.id} 引用了非武器生成策略")
                if len(generation.core_property_ids) != 1:
                    raise ValueError(f"武器 {definition.id} 必须绑定唯一核心特色")
                core_property_id = next(iter(generation.core_property_ids))
                previous = core_owners.get(core_property_id)
                if previous is not None:
                    raise ValueError(
                        f"武器核心特色不能复用：{core_property_id} 同时属于 "
                        f"{previous} 和 {definition.id}"
                    )
                core_owners[core_property_id] = definition.id
                unknown_qualities = {
                    band.quality_id for band in generation.quality_bands
                } - set(definition.quality_profiles)
                if unknown_qualities:
                    raise KeyError(
                        f"武器 {definition.id} 的生成策略产出未配置品质："
                        + ", ".join(sorted(unknown_qualities))
                    )
        self.definitions.freeze()
        self._finalized = True

    @property
    def finalized(self) -> bool:
        return self._finalized

    def create_state(
        self,
        *,
        asset_id: str,
        definition_id: StableId,
        quality_id: StableId,
        roll: ItemRollState | None = None,
        maximum_level_roll: WeaponMaximumLevelRoll | None = None,
    ) -> WeaponState:
        if not self._finalized:
            self.finalize()
        definition = self.require(definition_id)
        if quality_id not in definition.quality_profiles:
            raise KeyError(f"武器 {definition.id} 不支持品质：{quality_id}")
        if definition.generation_profile_id is None:
            if roll is not None:
                raise ValueError(f"固定武器 {definition.id} 不能携带随机属性")
            if maximum_level_roll is not None:
                raise ValueError(f"固定武器 {definition.id} 不能携带随机等级上限")
            maximum_level = definition.quality_profiles[quality_id].maximum_level
        else:
            if roll is None:
                raise ValueError(f"生成型武器 {definition.id} 必须携带随机属性")
            if roll.profile_id != definition.generation_profile_id:
                raise ValueError("武器随机属性策略与定义不一致")
            if roll.quality_id != quality_id:
                raise ValueError("武器随机属性品质与实例品质不一致")
            assert self.itemization is not None
            self.itemization.validate_roll(roll)
            if maximum_level_roll is None:
                raise ValueError(f"生成型武器 {definition.id} 必须携带随机等级上限")
            maximum_level = maximum_level_roll.sampled_level
            profile_maximum = definition.quality_profiles[quality_id].maximum_level
            if maximum_level > profile_maximum:
                raise ValueError("武器随机等级上限超过品质成长表范围")
        return WeaponState(
            asset_id,
            definition.id,
            quality_id,
            roll=roll,
            natural_maximum_level=maximum_level,
            maximum_level=maximum_level,
            maximum_level_roll=maximum_level_roll,
        )


def weapon_level_contribution(
    profile: WeaponQualityProfile,
    level: int,
) -> ContributionSpec:
    if level < 1 or level > profile.maximum_level:
        raise ValueError("武器等级超过品质档案范围")
    return ContributionSpec(
        attributes=tuple(
            AttributeGrant(
                progression.attribute_id,
                progression.layer,
                progression.values[level - 1],
                priority=progression.priority,
            )
            for progression in profile.level_attributes
        )
    )


def weapon_state_data(state: WeaponState) -> Mapping[str, object]:
    """生成库存实例时使用的稳定类型化武器数据。"""

    return MappingProxyType({WEAPON_STATE_DATA_KEY: state})


def weapon_state_from_data(data: Mapping[str, object]) -> WeaponState:
    try:
        state = data[WEAPON_STATE_DATA_KEY]
    except KeyError as exc:
        raise KeyError("物品实例缺少武器状态") from exc
    if not isinstance(state, WeaponState):
        raise TypeError("物品实例中的武器状态类型不正确")
    return state


def weapon_state_from_instance(instance: ItemInstance) -> WeaponState:
    state = weapon_state_from_data(instance.data)
    if state.asset_id != instance.id:
        raise ValueError("物品实例与武器状态资产 id 不一致")
    return state


__all__ = [
    "WeaponCatalog",
    "WEAPON_ABSOLUTE_MAXIMUM_LEVEL",
    "WeaponDefinition",
    "WeaponLevelAttribute",
    "WeaponMaximumLevelBand",
    "WeaponMaximumLevelRoll",
    "WeaponMaximumLevelTable",
    "WeaponQualityProfile",
    "WeaponState",
    "WEAPON_STATE_DATA_KEY",
    "weapon_state_data",
    "weapon_state_from_data",
    "weapon_state_from_instance",
    "weapon_level_contribution",
]
