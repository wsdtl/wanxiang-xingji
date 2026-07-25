"""内容包版本、依赖、类型化定义清单和受控扩展注册。"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Mapping

from ..actions import ActionDefinition
from ..activities import ActivityDefinition
from ..abilities import AbilityDefinition
from ..attributes import (
    AttributeDefinition,
    MagnitudeContext,
    ResourceDefinition,
)
from ..character import (
    CharacterFeatureDefinition,
    CharacterTemplateDefinition,
    ProgressionDefinition,
)
from ..combat import (
    AutomaticTargetRequest,
    BattleAbilityTargeting,
    CombatStats,
    ControlDefinition,
    ControlStats,
    DamageInterceptorDefinition,
    DamageRules,
    DamageTypeDefinition,
    InterceptorHandler,
    RecoveryStats,
    TargetConstraintDefinition,
    TargetSelector,
)
from ..conditions import ConditionContext, ConditionReferences
from ..cycles import CycleDefinition, ScheduleHandlerRegistration
from ..economy import CurrencyDefinition
from ..effects import (
    EffectContribution,
    EffectDefinition,
    EffectOperationContext,
    RuleReferences,
)
from ..equipment import (
    EquipmentDefinition,
    EquipmentSetDefinition,
    EquipmentFamilyDefinition,
)
from ..enemy import (
    EncounterScopeDefinition,
    EnemyBehaviorDefinition,
    EnemyDefinition,
    EnemyEncounterDefinition,
    EnemyLevelProfileDefinition,
    EnemyRankDefinition,
    EnemyRewardProfileDefinition,
)
from ..ids import StableId, stable_id
from ..registry import ContentDefinition
from ..inventory import ItemComponentType, ItemDefinition
from ..itemization import GenerationProfileDefinition, PropertyDefinition
from ..loadout import QualityDefinition
from ..loot import LootTableDefinition
from ..draw import DrawPoolDefinition
from ..party import PartyDefinition
from ..social import (
    OrganizationRoleDefinition,
    OrganizationTypeDefinition,
    RelationTypeDefinition,
    SocialRequestDefinition,
)
from ..world import (
    WorldConnectionDefinition,
    WorldLocationDefinition,
    MapAnchorDefinition,
    WorldDefinition,
    WorldLocationBinding,
    WorldMeterDefinition,
    WorldSpaceDefinition,
)
from .skins import SkinPack
from ..triggers import TriggerDefinition
from ..valuation import (
    AttributeValuationDefinition,
    ReferenceValuationDefinition,
    SynergyValuationDefinition,
)
from ..weapon import WeaponDefinition


@dataclass(frozen=True, order=True)
class ContentVersion:
    major: int
    minor: int = 0
    patch: int = 0

    def __post_init__(self) -> None:
        if min(self.major, self.minor, self.patch) < 0:
            raise ValueError("内容版本数字不能小于 0")

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class PackageRequirement:
    package_id: StableId
    minimum_version: ContentVersion = ContentVersion(0)
    maximum_exclusive: ContentVersion | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.minimum_version, ContentVersion):
            raise TypeError("minimum_version 必须是 ContentVersion")
        if self.maximum_exclusive is not None and not isinstance(
            self.maximum_exclusive,
            ContentVersion,
        ):
            raise TypeError("maximum_exclusive 必须是 ContentVersion")
        object.__setattr__(self, "package_id", stable_id(self.package_id, field="package id"))
        if self.maximum_exclusive is not None and self.maximum_exclusive <= self.minimum_version:
            raise ValueError("内容包依赖的最高版本必须大于最低版本")

    def accepts(self, version: ContentVersion) -> bool:
        return version >= self.minimum_version and (
            self.maximum_exclusive is None or version < self.maximum_exclusive
        )


@dataclass(frozen=True)
class ContentPackageManifest:
    id: StableId
    version: ContentVersion
    dependencies: tuple[PackageRequirement, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.version, ContentVersion):
            raise TypeError("内容包 version 必须是 ContentVersion")
        object.__setattr__(self, "id", stable_id(self.id, field="content package id"))
        dependencies = tuple(self.dependencies)
        ids = [value.package_id for value in dependencies]
        if self.id in ids:
            raise ValueError("内容包不能依赖自己")
        if len(ids) != len(set(ids)):
            raise ValueError("内容包依赖不能重复")
        object.__setattr__(self, "dependencies", dependencies)


@dataclass(frozen=True)
class CombatProfileDefinition:
    """一套可选择的战斗公共字段映射和数值边界。"""

    id: StableId
    combat_stats: CombatStats
    recovery_stats: RecoveryStats
    control_stats: ControlStats = ControlStats()
    damage_rules: DamageRules = DamageRules()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", stable_id(self.id, field="combat profile id"))


@dataclass(frozen=True)
class MagnitudeRegistration:
    value_type: type[object]
    evaluator: Callable[[object, MagnitudeContext], float]
    validator: Callable[[object, frozenset[str], frozenset[str]], None] | None = None


@dataclass(frozen=True)
class ConditionRegistration:
    value_type: type[object]
    handler: Callable[[object, ConditionContext], bool]
    validator: Callable[[object, ConditionReferences], None] | None = None


@dataclass(frozen=True)
class EffectOperationRegistration:
    value_type: type[object]
    handler: Callable[[object, EffectOperationContext], EffectContribution]
    validator: Callable[[object, RuleReferences], None] | None = None


@dataclass(frozen=True)
class InterceptorHandlerRegistration:
    id: StableId
    handler: InterceptorHandler

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", stable_id(self.id, field="interceptor handler id"))


@dataclass(frozen=True)
class TargetSelectorRegistration:
    id: StableId
    selector: TargetSelector
    automatic_request: AutomaticTargetRequest | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", stable_id(self.id, field="target selector id"))


@dataclass(frozen=True)
class ContentPackage:
    """一个包只声明内容，不自行决定装配顺序或冻结时机。"""

    manifest: ContentPackageManifest
    display_definitions: tuple[ContentDefinition, ...] = ()
    item_component_types: tuple[ItemComponentType[object], ...] = ()
    currencies: tuple[CurrencyDefinition, ...] = ()
    qualities: tuple[QualityDefinition, ...] = ()
    attributes: tuple[AttributeDefinition, ...] = ()
    resources: tuple[ResourceDefinition, ...] = ()
    character_features: tuple[CharacterFeatureDefinition, ...] = ()
    progressions: tuple[ProgressionDefinition, ...] = ()
    character_templates: tuple[CharacterTemplateDefinition, ...] = ()
    enemy_level_profiles: tuple[EnemyLevelProfileDefinition, ...] = ()
    enemy_ranks: tuple[EnemyRankDefinition, ...] = ()
    enemy_behaviors: tuple[EnemyBehaviorDefinition, ...] = ()
    enemy_reward_profiles: tuple[EnemyRewardProfileDefinition, ...] = ()
    enemies: tuple[EnemyDefinition, ...] = ()
    encounter_scopes: tuple[EncounterScopeDefinition, ...] = ()
    enemy_encounters: tuple[EnemyEncounterDefinition, ...] = ()
    items: tuple[ItemDefinition, ...] = ()
    equipment_families: tuple[EquipmentFamilyDefinition, ...] = ()
    equipment_sets: tuple[EquipmentSetDefinition, ...] = ()
    weapons: tuple[WeaponDefinition, ...] = ()
    equipment: tuple[EquipmentDefinition, ...] = ()
    attribute_valuations: tuple[AttributeValuationDefinition, ...] = ()
    reference_valuations: tuple[ReferenceValuationDefinition, ...] = ()
    synergy_valuations: tuple[SynergyValuationDefinition, ...] = ()
    random_properties: tuple[PropertyDefinition, ...] = ()
    generation_profiles: tuple[GenerationProfileDefinition, ...] = ()
    combat_profiles: tuple[CombatProfileDefinition, ...] = ()
    damage_types: tuple[DamageTypeDefinition, ...] = ()
    controls: tuple[ControlDefinition, ...] = ()
    interceptors: tuple[DamageInterceptorDefinition, ...] = ()
    target_constraints: tuple[TargetConstraintDefinition, ...] = ()
    effects: tuple[EffectDefinition, ...] = ()
    abilities: tuple[AbilityDefinition, ...] = ()
    triggers: tuple[TriggerDefinition, ...] = ()
    battle_ability_targeting: tuple[BattleAbilityTargeting, ...] = ()
    cycles: tuple[CycleDefinition, ...] = ()
    actions: tuple[ActionDefinition, ...] = ()
    activities: tuple[ActivityDefinition, ...] = ()
    loot_tables: tuple[LootTableDefinition, ...] = ()
    draw_pools: tuple[DrawPoolDefinition, ...] = ()
    world_spaces: tuple[WorldSpaceDefinition, ...] = ()
    world_definitions: tuple[WorldDefinition, ...] = ()
    map_anchors: tuple[MapAnchorDefinition, ...] = ()
    world_location_bindings: tuple[WorldLocationBinding, ...] = ()
    world_locations: tuple[WorldLocationDefinition, ...] = ()
    world_connections: tuple[WorldConnectionDefinition, ...] = ()
    world_meters: tuple[WorldMeterDefinition, ...] = ()
    organization_roles: tuple[OrganizationRoleDefinition, ...] = ()
    organization_types: tuple[OrganizationTypeDefinition, ...] = ()
    social_request_types: tuple[SocialRequestDefinition, ...] = ()
    relation_types: tuple[RelationTypeDefinition, ...] = ()
    party_types: tuple[PartyDefinition, ...] = ()
    skin_packs: tuple[SkinPack, ...] = ()
    display_content_ids: frozenset[StableId] = frozenset()
    skin_display_content_ids: Mapping[StableId, frozenset[StableId]] = field(
        default_factory=dict
    )
    magnitude_registrations: tuple[MagnitudeRegistration, ...] = ()
    condition_registrations: tuple[ConditionRegistration, ...] = ()
    effect_operation_registrations: tuple[EffectOperationRegistration, ...] = ()
    interceptor_handler_registrations: tuple[InterceptorHandlerRegistration, ...] = ()
    target_selector_registrations: tuple[TargetSelectorRegistration, ...] = ()
    cycle_schedule_registrations: tuple[ScheduleHandlerRegistration, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, ContentPackageManifest):
            raise TypeError("ContentPackage.manifest 类型不正确")
        tuple_fields = (
            "display_definitions",
            "item_component_types",
            "currencies",
            "qualities",
            "attributes",
            "resources",
            "character_features",
            "progressions",
            "character_templates",
            "enemy_level_profiles",
            "enemy_ranks",
            "enemy_behaviors",
            "enemy_reward_profiles",
            "enemies",
            "encounter_scopes",
            "enemy_encounters",
            "items",
            "equipment_families",
            "equipment_sets",
            "weapons",
            "equipment",
            "attribute_valuations",
            "reference_valuations",
            "synergy_valuations",
            "random_properties",
            "generation_profiles",
            "combat_profiles",
            "damage_types",
            "controls",
            "interceptors",
            "target_constraints",
            "effects",
            "abilities",
            "triggers",
            "battle_ability_targeting",
            "cycles",
            "actions",
            "activities",
            "loot_tables",
            "draw_pools",
            "world_spaces",
            "world_definitions",
            "map_anchors",
            "world_location_bindings",
            "world_locations",
            "world_connections",
            "world_meters",
            "organization_roles",
            "organization_types",
            "social_request_types",
            "relation_types",
            "party_types",
            "skin_packs",
            "magnitude_registrations",
            "condition_registrations",
            "effect_operation_registrations",
            "interceptor_handler_registrations",
            "target_selector_registrations",
            "cycle_schedule_registrations",
        )
        for field_name in tuple_fields:
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        object.__setattr__(
            self,
            "display_content_ids",
            frozenset(
                stable_id(value, field="display content id")
                for value in self.display_content_ids
            ),
        )
        scoped_display_ids = {
            stable_id(skin_id, field="skin id"): frozenset(
                stable_id(value, field="skin scoped display content id")
                for value in content_ids
            )
            for skin_id, content_ids in self.skin_display_content_ids.items()
        }
        if any(not content_ids for content_ids in scoped_display_ids.values()):
            raise ValueError("皮肤作用域展示集合不能为空")
        object.__setattr__(
            self,
            "skin_display_content_ids",
            MappingProxyType(scoped_display_ids),
        )
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


__all__ = [
    "CombatProfileDefinition",
    "ConditionRegistration",
    "ContentPackage",
    "ContentPackageManifest",
    "ContentVersion",
    "EffectOperationRegistration",
    "InterceptorHandlerRegistration",
    "MagnitudeRegistration",
    "PackageRequirement",
    "TargetSelectorRegistration",
]
