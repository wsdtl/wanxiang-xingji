"""把正式武器蓝图编译为可执行规则定义、随机属性和实例生成策略。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.gameplay import (
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    COMBAT_SPEED,
    LOADOUT_ITEM_COMPONENT_ID,
    SPIRIT_CURRENT,
    WEAPON_SLOT_ID,
    AbilityDefinition,
    BattleAbilityTargeting,
    ContributionSpec,
    EffectDefinition,
    EffectReference,
    FixedMagnitude,
    GenerationProfileDefinition,
    InterceptorSide,
    ItemAssetKind,
    ItemDefinition,
    ItemizationKind,
    LoadoutItemComponent,
    ModifierLayer,
    ModifyAttribute,
    PropertyDefinition,
    PropertyParameterDefinition,
    PropertyTierDefinition,
    QualityValueBand,
    ReferenceValuationDefinition,
    ReferenceValueKind,
    ResourceCost,
    StackingPolicy,
    TagSet,
    TargetConstraintDefinition,
    TargetConstraintKind,
    TriggerDefinition,
    ValueVector,
    WeaponDefinition,
    WeaponLevelAttribute,
    WeaponMaximumLevelBand,
    WeaponMaximumLevelTable,
    WeaponQualityProfile,
    DamageInterceptorDefinition,
    DamageStage,
)

from ..foundation import (
    COMMON_QUALITY_ID,
    EPIC_QUALITY_ID,
    FINE_QUALITY_ID,
    LEGENDARY_QUALITY_ID,
    QUALITY_IDS,
    RARE_QUALITY_ID,
)
from ..combat.stats import (
    COMBAT_ACCURACY,
    COMBAT_BLOCK_CHANCE,
    COMBAT_BLOCK_REDUCTION,
    COMBAT_CONTROL_CHANCE,
    COMBAT_CRITICAL_CHANCE,
    COMBAT_CRITICAL_DAMAGE,
    COMBAT_EVASION,
    COMBAT_FLAT_PENETRATION,
    COMBAT_HEALING_RATE,
    COMBAT_OUTGOING_RATE,
    COMBAT_RATE_PENETRATION,
    COMBAT_TENACITY,
)
from .blueprints import WEAPON_BLUEPRINTS, WeaponBlueprint
from .official_mechanics import (
    DAMAGE_CAP_INTERCEPTOR_ID,
    DEATH_GUARD_INTERCEPTOR_ID,
    IMMUNITY_INTERCEPTOR_ID,
    OFFICIAL_WEAPON_MECHANICS,
    TAUNT_CONSTRAINT_ID,
    UNTARGETABLE_CONSTRAINT_ID,
    WEAPON_CHARGE_EFFECT_ID,
    WEAPON_MARK_EFFECT_ID,
)
from .valuation import estimate_weapon_value

QUALITY_BANDS = (
    QualityValueBand(COMMON_QUALITY_ID, 0, 62),
    QualityValueBand(FINE_QUALITY_ID, 62, 74),
    QualityValueBand(RARE_QUALITY_ID, 74, 84),
    QualityValueBand(EPIC_QUALITY_ID, 84, 100),
    QualityValueBand(LEGENDARY_QUALITY_ID, 100),
)

WEAPON_EXPERIENCE_REQUIREMENTS = tuple(60 + level * level * 4 for level in range(1, 100))

WEAPON_MAXIMUM_LEVEL_TABLE = WeaponMaximumLevelTable(
    "weapon_maximum_level.standard",
    1,
    (
        WeaponMaximumLevelBand(20, 40, 450),
        WeaponMaximumLevelBand(41, 60, 280),
        WeaponMaximumLevelBand(61, 80, 180),
        WeaponMaximumLevelBand(81, 90, 60),
        WeaponMaximumLevelBand(91, 99, 25),
        WeaponMaximumLevelBand(100, 100, 5),
    ),
)


@dataclass(frozen=True)
class WeaponMechanicContent:
    items: tuple[ItemDefinition, ...]
    weapons: tuple[WeaponDefinition, ...]
    effects: tuple[EffectDefinition, ...]
    abilities: tuple[AbilityDefinition, ...]
    targeting: tuple[BattleAbilityTargeting, ...]
    triggers: tuple[TriggerDefinition, ...]
    interceptors: tuple[DamageInterceptorDefinition, ...]
    constraints: tuple[TargetConstraintDefinition, ...]
    properties: tuple[PropertyDefinition, ...]
    profiles: tuple[GenerationProfileDefinition, ...]
    reference_valuations: tuple[ReferenceValuationDefinition, ...]
    display_ids: frozenset[str]


def _ability_targeting(
    blueprint: WeaponBlueprint,
    ability_id: str,
) -> BattleAbilityTargeting:
    targeting = OFFICIAL_WEAPON_MECHANICS.resolve(blueprint).targeting
    return BattleAbilityTargeting(
        ability_id,
        targeting.allowed_selectors,
        targeting.maximum_targets,
    )


def _core_property(
    blueprint: WeaponBlueprint,
    ability_id: str,
    passive_triggers: frozenset[str],
) -> PropertyDefinition:
    contribution = ContributionSpec(
        tags=TagSet.of(
            "weapon.core",
            f"weapon.domain.{blueprint.domain}",
            f"weapon.primary.{blueprint.primary}",
            f"weapon.support.{blueprint.support}",
            f"weapon.targeting.{blueprint.targeting}",
        ),
        abilities=frozenset({ability_id}),
        triggers=passive_triggers,
    )
    return PropertyDefinition(
        f"property.weapon_core.{blueprint.key}",
        1,
        (PropertyTierDefinition(1, 1, contribution),),
        tags=contribution.tags,
    )


def _parameter_property(
    key: str,
    attribute_id: str,
    layer: ModifierLayer,
    ranges: tuple[tuple[float, float, float], ...],
    *,
    domains: tuple[str, ...] = (),
) -> PropertyDefinition:
    required = TagSet.of(*(f"weapon.domain.{value}" for value in domains)) if len(domains) == 1 else TagSet()
    tiers = tuple(
        PropertyTierDefinition(
            tier=index,
            weight=(60, 30, 10)[index - 1],
            parameters=(
                PropertyParameterDefinition(
                    f"parameter.weapon.{key}",
                    attribute_id,
                    layer,
                    minimum,
                    maximum,
                    step,
                ),
            ),
        )
        for index, (minimum, maximum, step) in enumerate(ranges, start=1)
    )
    return PropertyDefinition(
        f"property.weapon_affix.{key}",
        10,
        tiers,
        tags=TagSet.of(f"weapon.affix.{key}"),
        required_selected_tags=required,
    )


UNIVERSAL_WEAPON_PROPERTIES = (
    _parameter_property("attack", COMBAT_ATTACK, ModifierLayer.LOCAL_FLAT, ((4, 8, 1), (9, 14, 1), (15, 22, 1))),
    _parameter_property("defense", COMBAT_DEFENSE, ModifierLayer.LOCAL_FLAT, ((4, 8, 1), (9, 14, 1), (15, 22, 1))),
    _parameter_property("speed", COMBAT_SPEED, ModifierLayer.LOCAL_FLAT, ((3, 6, 1), (7, 11, 1), (12, 18, 1))),
    _parameter_property(
        "accuracy",
        COMBAT_ACCURACY,
        ModifierLayer.GLOBAL_FLAT,
        ((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.13, 0.01)),
    ),
    _parameter_property(
        "outgoing",
        COMBAT_OUTGOING_RATE,
        ModifierLayer.GLOBAL_FLAT,
        ((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.12, 0.01)),
    ),
    _parameter_property(
        "tenacity",
        COMBAT_TENACITY,
        ModifierLayer.GLOBAL_FLAT,
        ((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.12, 0.01)),
    ),
)

DOMAIN_WEAPON_PROPERTIES = {
    "burst": (
        _parameter_property(
            "burst_critical",
            COMBAT_CRITICAL_DAMAGE,
            ModifierLayer.GLOBAL_FLAT,
            ((0.05, 0.10, 0.01), (0.11, 0.18, 0.01), (0.19, 0.28, 0.01)),
            domains=("burst",),
        ),
        _parameter_property(
            "burst_penetration",
            COMBAT_FLAT_PENETRATION,
            ModifierLayer.GLOBAL_FLAT,
            ((3, 6, 1), (7, 11, 1), (12, 18, 1)),
            domains=("burst",),
        ),
    ),
    "tempo": (
        _parameter_property(
            "tempo_critical",
            COMBAT_CRITICAL_CHANCE,
            ModifierLayer.GLOBAL_FLAT,
            ((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.13, 0.01)),
            domains=("tempo",),
        ),
        _parameter_property(
            "tempo_evasion",
            COMBAT_EVASION,
            ModifierLayer.GLOBAL_FLAT,
            ((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.13, 0.01)),
            domains=("tempo",),
        ),
    ),
    "ailment": (
        _parameter_property(
            "ailment_rate",
            COMBAT_OUTGOING_RATE,
            ModifierLayer.GLOBAL_FLAT,
            ((0.03, 0.05, 0.01), (0.06, 0.09, 0.01), (0.10, 0.14, 0.01)),
            domains=("ailment",),
        ),
        _parameter_property(
            "ailment_control",
            COMBAT_CONTROL_CHANCE,
            ModifierLayer.GLOBAL_FLAT,
            ((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.12, 0.01)),
            domains=("ailment",),
        ),
    ),
    "resource": (
        _parameter_property(
            "resource_healing",
            COMBAT_HEALING_RATE,
            ModifierLayer.GLOBAL_FLAT,
            ((0.03, 0.06, 0.01), (0.07, 0.11, 0.01), (0.12, 0.18, 0.01)),
            domains=("resource",),
        ),
        _parameter_property(
            "resource_attack",
            COMBAT_ATTACK,
            ModifierLayer.LOCAL_FLAT,
            ((5, 9, 1), (10, 16, 1), (17, 24, 1)),
            domains=("resource",),
        ),
    ),
    "guard": (
        _parameter_property(
            "guard_block",
            COMBAT_BLOCK_CHANCE,
            ModifierLayer.GLOBAL_FLAT,
            ((0.03, 0.05, 0.01), (0.06, 0.09, 0.01), (0.10, 0.14, 0.01)),
            domains=("guard",),
        ),
        _parameter_property(
            "guard_reduction",
            COMBAT_BLOCK_REDUCTION,
            ModifierLayer.GLOBAL_FLAT,
            ((0.04, 0.08, 0.01), (0.09, 0.14, 0.01), (0.15, 0.22, 0.01)),
            domains=("guard",),
        ),
    ),
    "control": (
        _parameter_property(
            "control_chance",
            COMBAT_CONTROL_CHANCE,
            ModifierLayer.GLOBAL_FLAT,
            ((0.03, 0.05, 0.01), (0.06, 0.10, 0.01), (0.11, 0.16, 0.01)),
            domains=("control",),
        ),
        _parameter_property(
            "control_speed",
            COMBAT_SPEED,
            ModifierLayer.LOCAL_FLAT,
            ((4, 7, 1), (8, 12, 1), (13, 19, 1)),
            domains=("control",),
        ),
    ),
    "targeting": (
        _parameter_property(
            "targeting_penetration",
            COMBAT_RATE_PENETRATION,
            ModifierLayer.GLOBAL_FLAT,
            ((0.03, 0.05, 0.01), (0.06, 0.09, 0.01), (0.10, 0.15, 0.01)),
            domains=("targeting",),
        ),
        _parameter_property(
            "targeting_accuracy",
            COMBAT_ACCURACY,
            ModifierLayer.GLOBAL_FLAT,
            ((0.03, 0.05, 0.01), (0.06, 0.10, 0.01), (0.11, 0.16, 0.01)),
            domains=("targeting",),
        ),
    ),
    "reaction": (
        _parameter_property(
            "reaction_evasion",
            COMBAT_EVASION,
            ModifierLayer.GLOBAL_FLAT,
            ((0.03, 0.05, 0.01), (0.06, 0.10, 0.01), (0.11, 0.16, 0.01)),
            domains=("reaction",),
        ),
        _parameter_property(
            "reaction_critical",
            COMBAT_CRITICAL_CHANCE,
            ModifierLayer.GLOBAL_FLAT,
            ((0.03, 0.05, 0.01), (0.06, 0.10, 0.01), (0.11, 0.16, 0.01)),
            domains=("reaction",),
        ),
    ),
    "risk": (
        _parameter_property(
            "risk_damage",
            COMBAT_OUTGOING_RATE,
            ModifierLayer.GLOBAL_FLAT,
            ((0.04, 0.07, 0.01), (0.08, 0.13, 0.01), (0.14, 0.20, 0.01)),
            domains=("risk",),
        ),
        _parameter_property(
            "risk_critical",
            COMBAT_CRITICAL_DAMAGE,
            ModifierLayer.GLOBAL_FLAT,
            ((0.06, 0.11, 0.01), (0.12, 0.20, 0.01), (0.21, 0.30, 0.01)),
            domains=("risk",),
        ),
    ),
}


def _quality_profiles() -> dict[str, WeaponQualityProfile]:
    bases = (3.0, 4.0, 5.0, 6.0, 8.0)
    growth = (0.60, 0.80, 1.00, 1.25, 1.55)
    return {
        quality_id: WeaponQualityProfile(
            quality_id,
            WEAPON_EXPERIENCE_REQUIREMENTS,
            level_attributes=(
                WeaponLevelAttribute(
                    COMBAT_ATTACK,
                    ModifierLayer.LOCAL_FLAT,
                    tuple(round(bases[index] + (level - 1) * growth[index], 2) for level in range(1, 101)),
                ),
            ),
        )
        for index, quality_id in enumerate(QUALITY_IDS)
    }


def build_weapon_mechanic_content() -> WeaponMechanicContent:
    OFFICIAL_WEAPON_MECHANICS.validate_blueprints(WEAPON_BLUEPRINTS)
    effects: dict[str, EffectDefinition] = {
        WEAPON_MARK_EFFECT_ID: EffectDefinition(
            WEAPON_MARK_EFFECT_ID,
            tags=TagSet.of("status.negative", "status.weapon_mark"),
            duration_turns=4,
            stacking=StackingPolicy.STACK,
            max_stacks=5,
            stack_by_source=True,
        ),
        WEAPON_CHARGE_EFFECT_ID: EffectDefinition(
            WEAPON_CHARGE_EFFECT_ID,
            tags=TagSet.of("status.positive", "status.weapon_charge"),
            operations=(
                ModifyAttribute(
                    "operation.weapon.shared_charge", COMBAT_ATTACK, ModifierLayer.GLOBAL_FLAT, FixedMagnitude(3)
                ),
            ),
            duration_turns=5,
            stacking=StackingPolicy.STACK,
            max_stacks=5,
        ),
    }
    abilities = []
    targeting = []
    triggers = []
    items = []
    weapons = []
    core_properties = []
    profiles = []
    valuations = []
    display_ids: set[str] = set()
    qualities = _quality_profiles()
    for blueprint in WEAPON_BLUEPRINTS:
        key = blueprint.key
        ability_id = f"ability.weapon.{key}"
        strike_id = f"effect.weapon.{key}.strike"
        recipe = OFFICIAL_WEAPON_MECHANICS.resolve(blueprint)
        primary = recipe.primary.compile(blueprint)
        support = recipe.support.compile(blueprint, ability_id)
        effects[strike_id] = EffectDefinition(
            strike_id,
            operations=primary.operations,
        )
        for definition in (*primary.effects, *support.effects):
            previous = effects.get(definition.id)
            if previous is not None and previous != definition:
                raise ValueError(f"武器 Effect 定义冲突：{definition.id}")
            effects[definition.id] = definition
        triggers.extend((*primary.triggers, *support.triggers))
        costs = (
            () if blueprint.spirit_cost == 0 else (ResourceCost(SPIRIT_CURRENT, FixedMagnitude(blueprint.spirit_cost)),)
        )
        ability = AbilityDefinition(
            ability_id,
            tags=TagSet.of(
                "ability.weapon",
                f"weapon.targeting.{blueprint.targeting}",
                f"weapon.domain.{blueprint.domain}",
            ),
            costs=costs,
            effects=(
                EffectReference(strike_id),
                *primary.references,
                *support.references,
                *primary.final_references,
            ),
            cooldown_turns=blueprint.cooldown,
        )
        abilities.append(ability)
        targeting.append(_ability_targeting(blueprint, ability_id))
        core = _core_property(
            blueprint,
            ability_id,
            support.granted_triggers,
        )
        core_properties.append(core)
        domain_properties = DOMAIN_WEAPON_PROPERTIES[blueprint.domain]
        profile = GenerationProfileDefinition(
            f"generation.weapon.{key}",
            ItemizationKind.WEAPON,
            frozenset(
                {
                    core.id,
                    *(value.id for value in UNIVERSAL_WEAPON_PROPERTIES),
                    *(value.id for value in domain_properties),
                }
            ),
            2,
            4,
            QUALITY_BANDS,
            core_property_ids=frozenset({core.id}),
            enforce_compatibility=True,
            maximum_attempts=8,
        )
        profiles.append(profile)
        item_id = f"item.weapon.{key}"
        weapon_id = f"weapon.{key}"
        items.append(
            ItemDefinition(
                item_id,
                ItemAssetKind.INSTANCE,
                TagSet.of("item.weapon", "item.armament"),
                components={LOADOUT_ITEM_COMPONENT_ID: LoadoutItemComponent(frozenset({WEAPON_SLOT_ID}))},
            )
        )
        weapons.append(
            WeaponDefinition(
                weapon_id,
                item_id,
                ContributionSpec(tags=TagSet.of(f"weapon.identity.{key}")),
                qualities,
                generation_profile_id=profile.id,
            )
        )
        valuations.append(
            ReferenceValuationDefinition(
                ReferenceValueKind.ABILITY,
                ability_id,
                estimate_weapon_value(blueprint).estimated,
            )
        )
        for trigger_id in support.granted_triggers:
            valuations.append(
                ReferenceValuationDefinition(
                    ReferenceValueKind.TRIGGER,
                    trigger_id,
                    ValueVector(offense=4, sustain=2, tempo=2, volatility=2),
                )
            )
        display_ids.update((weapon_id, item_id, ability_id))
    all_secondary = (
        *UNIVERSAL_WEAPON_PROPERTIES,
        *(value for group in DOMAIN_WEAPON_PROPERTIES.values() for value in group),
    )
    all_properties = (*all_secondary, *core_properties)
    display_ids.update(value.id for value in all_properties)
    return WeaponMechanicContent(
        tuple(items),
        tuple(weapons),
        tuple(effects.values()),
        tuple(abilities),
        tuple(targeting),
        tuple(triggers),
        (
            DamageInterceptorDefinition(
                DEATH_GUARD_INTERCEPTOR_ID,
                "interceptor.death_guard",
                DamageStage.BEFORE_SHIELD,
                InterceptorSide.TARGET,
                configuration={"minimum_health": 1},
            ),
            DamageInterceptorDefinition(
                IMMUNITY_INTERCEPTOR_ID,
                "interceptor.immunity",
                DamageStage.RAW,
                InterceptorSide.TARGET,
            ),
            DamageInterceptorDefinition(
                DAMAGE_CAP_INTERCEPTOR_ID,
                "interceptor.cap",
                DamageStage.AFTER_RATES,
                InterceptorSide.TARGET,
                configuration={"maximum": 80},
            ),
        ),
        (
            TargetConstraintDefinition(TAUNT_CONSTRAINT_ID, TargetConstraintKind.FORCE_GRANT_SOURCE),
            TargetConstraintDefinition(UNTARGETABLE_CONSTRAINT_ID, TargetConstraintKind.UNTARGETABLE),
        ),
        all_properties,
        tuple(profiles),
        tuple(valuations),
        frozenset(display_ids),
    )


WEAPON_MECHANIC_CONTENT = build_weapon_mechanic_content()


__all__ = [
    "DAMAGE_CAP_INTERCEPTOR_ID",
    "DEATH_GUARD_INTERCEPTOR_ID",
    "IMMUNITY_INTERCEPTOR_ID",
    "QUALITY_BANDS",
    "TAUNT_CONSTRAINT_ID",
    "UNTARGETABLE_CONSTRAINT_ID",
    "WEAPON_CHARGE_EFFECT_ID",
    "WEAPON_EXPERIENCE_REQUIREMENTS",
    "WEAPON_MARK_EFFECT_ID",
    "WEAPON_MAXIMUM_LEVEL_TABLE",
    "WEAPON_MECHANIC_CONTENT",
    "WeaponMechanicContent",
    "build_weapon_mechanic_content",
]
