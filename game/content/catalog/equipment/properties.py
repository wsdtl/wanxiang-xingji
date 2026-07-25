"""正式装备的开放随机词条、真实触发机制和生成策略。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.gameplay import (
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    COMBAT_SPEED,
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    SPIRIT_MAXIMUM,
    ApplyControl,
    AttributeMagnitude,
    ChangeResource,
    Comparison,
    ConditionSubject,
    ContributionSpec,
    DealDamage,
    EffectDefinition,
    EventValueCondition,
    FixedMagnitude,
    GenerationProfileDefinition,
    GrantInterceptor,
    GrantShield,
    GrantTrigger,
    Heal,
    ItemizationKind,
    ModifierLayer,
    ModifyAttribute,
    ModifyCurrentCooldowns,
    ParameterMagnitude,
    ProductMagnitude,
    PropertyDefinition,
    PropertyParameterDefinition,
    PropertyTierDefinition,
    QualityValueBand,
    ReferenceValuationDefinition,
    ReferenceValueKind,
    ResourceRatioCondition,
    StackingPolicy,
    TagSet,
    TriggerDefinition,
    TriggerOwner,
    TriggerSource,
    TriggerTarget,
    ValueVector,
)

from ..foundation import (
    COMMON_QUALITY_ID,
    EPIC_QUALITY_ID,
    FINE_QUALITY_ID,
    LEGENDARY_QUALITY_ID,
    RARE_QUALITY_ID,
)
from ..combat.stats import (
    COMBAT_ACCURACY,
    COMBAT_BLOCK_CHANCE,
    COMBAT_BLOCK_REDUCTION,
    COMBAT_CONTROL_CHANCE,
    COMBAT_CONTROL_RESISTANCE,
    COMBAT_CRITICAL_CHANCE,
    COMBAT_CRITICAL_DAMAGE,
    COMBAT_EVASION,
    COMBAT_FLAT_PENETRATION,
    COMBAT_HEALING_RATE,
    COMBAT_HEALING_RECEIVED,
    COMBAT_INCOMING_RATE,
    COMBAT_OUTGOING_RATE,
    COMBAT_RATE_PENETRATION,
    COMBAT_TENACITY,
    FIRE_DAMAGE_ID,
    FROST_DAMAGE_ID,
    POISON_DAMAGE_ID,
    STUN_CONTROL_ID,
    TRUE_DAMAGE_ID,
)
from .blueprints import (
    EQUIPMENT_PROPERTY_BLUEPRINTS,
    MECHANIC_EQUIPMENT_PROPERTY_BLUEPRINTS,
)
from ..weapon.mechanics import DEATH_GUARD_INTERCEPTOR_ID


EQUIPMENT_GENERATION_PROFILE_ID = "generation.equipment.open"
EQUIPMENT_SET_MARK_CHANCE = 0.25
EQUIPMENT_QUALITY_BANDS = (
    QualityValueBand(COMMON_QUALITY_ID, 0, 23),
    QualityValueBand(FINE_QUALITY_ID, 23, 32),
    QualityValueBand(RARE_QUALITY_ID, 32, 40),
    QualityValueBand(EPIC_QUALITY_ID, 40, 50),
    QualityValueBand(LEGENDARY_QUALITY_ID, 50),
)


@dataclass(frozen=True)
class EquipmentPropertyContent:
    effects: tuple[EffectDefinition, ...]
    triggers: tuple[TriggerDefinition, ...]
    properties: tuple[PropertyDefinition, ...]
    profiles: tuple[GenerationProfileDefinition, ...]
    reference_valuations: tuple[ReferenceValuationDefinition, ...]
    display_ids: frozenset[str]


def equipment_property_id(key: str) -> str:
    return f"property.equipment.{key}"


def equipment_trigger_id(key: str, tier: int) -> str:
    return f"trigger.equipment.{key}.tier_{tier}"


def _ranges(*values: tuple[float, float, float]):
    if len(values) != 3:
        raise ValueError("装备数值词条必须提供三个档位")
    return values


NUMERIC_PROPERTY_SPECS = {
    "health": (("health", HEALTH_MAXIMUM, ModifierLayer.LOCAL_FLAT, _ranges((20, 45, 5), (50, 90, 5), (100, 160, 10))),),
    "spirit": (("spirit", SPIRIT_MAXIMUM, ModifierLayer.LOCAL_FLAT, _ranges((12, 24, 2), (26, 46, 2), (50, 80, 5))),),
    "attack": (("attack", COMBAT_ATTACK, ModifierLayer.LOCAL_FLAT, _ranges((2, 5, 1), (6, 10, 1), (11, 16, 1))),),
    "defense": (("defense", COMBAT_DEFENSE, ModifierLayer.LOCAL_FLAT, _ranges((3, 7, 1), (8, 13, 1), (14, 21, 1))),),
    "speed": (("speed", COMBAT_SPEED, ModifierLayer.LOCAL_FLAT, _ranges((2, 5, 1), (6, 10, 1), (11, 16, 1))),),
    "accuracy": (("accuracy", COMBAT_ACCURACY, ModifierLayer.GLOBAL_FLAT, _ranges((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.13, 0.01))),),
    "evasion": (("evasion", COMBAT_EVASION, ModifierLayer.GLOBAL_FLAT, _ranges((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.13, 0.01))),),
    "critical_chance": (("critical_chance", COMBAT_CRITICAL_CHANCE, ModifierLayer.GLOBAL_FLAT, _ranges((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.13, 0.01))),),
    "critical_damage": (("critical_damage", COMBAT_CRITICAL_DAMAGE, ModifierLayer.GLOBAL_FLAT, _ranges((0.05, 0.10, 0.01), (0.11, 0.18, 0.01), (0.19, 0.28, 0.01))),),
    "block_chance": (("block_chance", COMBAT_BLOCK_CHANCE, ModifierLayer.GLOBAL_FLAT, _ranges((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.13, 0.01))),),
    "block_reduction": (("block_reduction", COMBAT_BLOCK_REDUCTION, ModifierLayer.GLOBAL_FLAT, _ranges((0.04, 0.08, 0.01), (0.09, 0.14, 0.01), (0.15, 0.22, 0.01))),),
    "outgoing": (("outgoing", COMBAT_OUTGOING_RATE, ModifierLayer.GLOBAL_FLAT, _ranges((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.12, 0.01))),),
    "incoming": (("incoming", COMBAT_INCOMING_RATE, ModifierLayer.GLOBAL_FLAT, _ranges((-0.04, -0.02, 0.01), (-0.08, -0.05, 0.01), (-0.13, -0.09, 0.01))),),
    "flat_penetration": (("flat_penetration", COMBAT_FLAT_PENETRATION, ModifierLayer.GLOBAL_FLAT, _ranges((2, 5, 1), (6, 10, 1), (11, 17, 1))),),
    "rate_penetration": (("rate_penetration", COMBAT_RATE_PENETRATION, ModifierLayer.GLOBAL_FLAT, _ranges((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.13, 0.01))),),
    "healing": (("healing", COMBAT_HEALING_RATE, ModifierLayer.GLOBAL_FLAT, _ranges((0.03, 0.06, 0.01), (0.07, 0.11, 0.01), (0.12, 0.18, 0.01))),),
    "healing_received": (("healing_received", COMBAT_HEALING_RECEIVED, ModifierLayer.GLOBAL_FLAT, _ranges((0.03, 0.06, 0.01), (0.07, 0.11, 0.01), (0.12, 0.18, 0.01))),),
    "control_chance": (("control_chance", COMBAT_CONTROL_CHANCE, ModifierLayer.GLOBAL_FLAT, _ranges((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.13, 0.01))),),
    "control_resistance": (("control_resistance", COMBAT_CONTROL_RESISTANCE, ModifierLayer.GLOBAL_FLAT, _ranges((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.13, 0.01))),),
    "tenacity": (("tenacity", COMBAT_TENACITY, ModifierLayer.GLOBAL_FLAT, _ranges((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.13, 0.01))),),
    "vital_guard": (
        ("health", HEALTH_MAXIMUM, ModifierLayer.LOCAL_FLAT, _ranges((12, 24, 2), (28, 48, 2), (55, 85, 5))),
        ("defense", COMBAT_DEFENSE, ModifierLayer.LOCAL_FLAT, _ranges((2, 4, 1), (5, 8, 1), (9, 13, 1))),
    ),
    "spirit_step": (
        ("spirit", SPIRIT_MAXIMUM, ModifierLayer.LOCAL_FLAT, _ranges((8, 16, 2), (18, 30, 2), (35, 55, 5))),
        ("speed", COMBAT_SPEED, ModifierLayer.LOCAL_FLAT, _ranges((1, 3, 1), (4, 6, 1), (7, 10, 1))),
    ),
    "keen_edge": (
        ("attack", COMBAT_ATTACK, ModifierLayer.LOCAL_FLAT, _ranges((1, 3, 1), (4, 6, 1), (7, 10, 1))),
        ("accuracy", COMBAT_ACCURACY, ModifierLayer.GLOBAL_FLAT, _ranges((0.01, 0.03, 0.01), (0.04, 0.06, 0.01), (0.07, 0.10, 0.01))),
    ),
    "mystic_armor": (
        ("defense", COMBAT_DEFENSE, ModifierLayer.LOCAL_FLAT, _ranges((2, 4, 1), (5, 8, 1), (9, 13, 1))),
        ("tenacity", COMBAT_TENACITY, ModifierLayer.GLOBAL_FLAT, _ranges((0.01, 0.03, 0.01), (0.04, 0.06, 0.01), (0.07, 0.10, 0.01))),
    ),
}


MECHANIC_BASE_VALUES = {
    "critical_echo": ValueVector(offense=8, volatility=3),
    "burning_touch": ValueVector(offense=7, volatility=3),
    "venom_touch": ValueVector(offense=9, volatility=4),
    "frost_touch": ValueVector(offense=6, control=2, volatility=3),
    "execute_echo": ValueVector(offense=9, volatility=5),
    "kill_haste": ValueVector(tempo=8, volatility=5),
    "kill_heal": ValueVector(sustain=8, volatility=5),
    "lifesteal": ValueVector(sustain=9),
    "thorns": ValueVector(offense=4, survival=4, volatility=3),
    "evade_counter": ValueVector(offense=4, survival=4, volatility=4),
    "block_counter": ValueVector(offense=4, survival=4, volatility=3),
    "shield_counter": ValueVector(offense=5, survival=4, volatility=4),
    "damaged_heal": ValueVector(sustain=7, volatility=2),
    "damaged_shield": ValueVector(survival=7, volatility=2),
    "critical_spirit": ValueVector(sustain=3, tempo=5, volatility=3),
    "hit_spirit": ValueVector(sustain=3, tempo=4),
    "kill_cooldown": ValueVector(tempo=9, volatility=5),
    "turn_heal": ValueVector(sustain=8),
    "turn_spirit": ValueVector(sustain=4, tempo=4),
    "turn_shield": ValueVector(survival=8),
    "critical_stun": ValueVector(control=9, volatility=5),
    "hit_slow": ValueVector(tempo=2, control=6),
    "low_health_guard": ValueVector(survival=10, volatility=5),
    "healing_shield": ValueVector(survival=4, sustain=5, volatility=3),
}


def _numeric_property(key: str) -> PropertyDefinition:
    specs = NUMERIC_PROPERTY_SPECS[key]
    tiers = []
    for tier_index in range(3):
        parameters = tuple(
            PropertyParameterDefinition(
                f"parameter.equipment.{key}.{suffix}",
                attribute_id,
                layer,
                ranges[tier_index][0],
                ranges[tier_index][1],
                ranges[tier_index][2],
            )
            for suffix, attribute_id, layer, ranges in specs
        )
        tiers.append(
            PropertyTierDefinition(
                tier_index + 1,
                (60, 30, 10)[tier_index],
                parameters=parameters,
            )
        )
    blueprint = next(value for value in EQUIPMENT_PROPERTY_BLUEPRINTS if value.key == key)
    return PropertyDefinition(
        equipment_property_id(key),
        10,
        tuple(tiers),
        tags=TagSet.of(
            f"equipment.property.{key}",
            f"equipment.category.{blueprint.category}",
        ),
    )


def _damage(operation_id: str, damage_type: str, scale: float, *, event_scale: bool = False):
    magnitude = (
        ParameterMagnitude("event.effective_damage", scale=scale)
        if event_scale
        else AttributeMagnitude(COMBAT_ATTACK, scale=scale)
    )
    return DealDamage(
        operation_id,
        damage_type,
        magnitude,
        tags=TagSet.of("damage.proc", "damage.equipment"),
        can_critical=False,
    )


def _mechanic_content(key: str, tier: int):
    factor = (0.65, 1.0, 1.45)[tier - 1]
    effect_id = f"effect.equipment.{key}.tier_{tier}"
    trigger_id = equipment_trigger_id(key, tier)
    operation_id = f"operation.equipment.{key}.tier_{tier}"
    effects: list[EffectDefinition] = []
    triggers: list[TriggerDefinition] = []
    conditions = ()
    chance = 1.0

    if key == "critical_echo":
        event_kind, owner, target, source = "combat.attack.critical", TriggerOwner.EVENT_SOURCE, TriggerTarget.EVENT_TARGET, TriggerSource.OWNER
        operations = (_damage(operation_id, TRUE_DAMAGE_ID, 0.18 * factor),)
    elif key == "burning_touch":
        event_kind, owner, target, source = "combat.attack.hit", TriggerOwner.EVENT_SOURCE, TriggerTarget.EVENT_TARGET, TriggerSource.OWNER
        chance = (0.12, 0.20, 0.30)[tier - 1]
        operations = (_damage(operation_id, FIRE_DAMAGE_ID, 0.22 * factor),)
    elif key == "venom_touch":
        event_kind, owner, target, source = "combat.attack.hit", TriggerOwner.EVENT_SOURCE, TriggerTarget.EVENT_TARGET, TriggerSource.OWNER
        chance = (0.12, 0.20, 0.30)[tier - 1]
        tick_effect_id = f"effect.equipment.{key}.tick.tier_{tier}"
        tick_trigger_id = f"trigger.equipment.{key}.tick.tier_{tier}"
        effects.extend(
            (
                EffectDefinition(
                    effect_id,
                    tags=TagSet.of("status.negative", "status.ailment.poison"),
                    operations=(GrantTrigger(operation_id, tick_trigger_id),),
                    duration_turns=3,
                    stacking=StackingPolicy.STACK,
                    max_stacks=3,
                    stack_by_source=True,
                ),
                EffectDefinition(
                    tick_effect_id,
                    operations=(
                        DealDamage(
                            f"{operation_id}.tick",
                            POISON_DAMAGE_ID,
                            ProductMagnitude(
                                (
                                    AttributeMagnitude(COMBAT_ATTACK, scale=0.07 * factor),
                                    ParameterMagnitude("effect.stacks"),
                                )
                            ),
                            tags=TagSet.of("damage.proc", "damage.equipment", "damage.periodic"),
                            can_critical=False,
                        ),
                    ),
                ),
            )
        )
        triggers.append(
            TriggerDefinition(
                tick_trigger_id,
                "combat.turn.started",
                tick_effect_id,
                target=TriggerTarget.OWNER,
                owner=TriggerOwner.EVENT_SOURCE,
                source=TriggerSource.GRANT_SOURCE,
                max_activations_per_execution=1,
            )
        )
        operations = None
    elif key == "frost_touch":
        event_kind, owner, target, source = "combat.attack.hit", TriggerOwner.EVENT_SOURCE, TriggerTarget.EVENT_TARGET, TriggerSource.OWNER
        chance = (0.12, 0.20, 0.30)[tier - 1]
        operations = (_damage(operation_id, FROST_DAMAGE_ID, 0.20 * factor),)
    elif key == "execute_echo":
        event_kind, owner, target, source = "combat.damage.dealt", TriggerOwner.EVENT_SOURCE, TriggerTarget.EVENT_TARGET, TriggerSource.OWNER
        conditions = (
            ResourceRatioCondition(
                f"condition.equipment.{key}.tier_{tier}",
                ConditionSubject.TARGET,
                HEALTH_CURRENT,
                HEALTH_MAXIMUM,
                Comparison.LESS_OR_EQUAL,
                0.30,
            ),
        )
        operations = (_damage(operation_id, TRUE_DAMAGE_ID, 0.16 * factor),)
    elif key == "kill_haste":
        event_kind, owner, target, source = "combat.target.defeated", TriggerOwner.EVENT_SOURCE, TriggerTarget.OWNER, TriggerSource.OWNER
        operations = (ModifyAttribute(operation_id, COMBAT_SPEED, ModifierLayer.GLOBAL_FLAT, FixedMagnitude((6, 10, 15)[tier - 1])),)
        effects.append(EffectDefinition(effect_id, tags=TagSet.of("status.positive"), operations=operations, duration_turns=2))
        operations = None
    elif key == "kill_heal":
        event_kind, owner, target, source = "combat.target.defeated", TriggerOwner.EVENT_SOURCE, TriggerTarget.OWNER, TriggerSource.OWNER
        operations = (Heal(operation_id, AttributeMagnitude(COMBAT_ATTACK, scale=0.35 * factor)),)
    elif key == "lifesteal":
        event_kind, owner, target, source = "combat.damage.dealt", TriggerOwner.EVENT_SOURCE, TriggerTarget.OWNER, TriggerSource.OWNER
        operations = (Heal(operation_id, ParameterMagnitude("event.effective_damage", scale=(0.06, 0.10, 0.14)[tier - 1])),)
    elif key == "thorns":
        event_kind, owner, target, source = "combat.damage.dealt", TriggerOwner.EVENT_TARGET, TriggerTarget.EVENT_SOURCE, TriggerSource.OWNER
        conditions = (EventValueCondition(f"condition.equipment.{key}.tier_{tier}", "damage_type", Comparison.NOT_EQUAL, TRUE_DAMAGE_ID),)
        operations = (_damage(operation_id, TRUE_DAMAGE_ID, (0.08, 0.13, 0.18)[tier - 1], event_scale=True),)
    elif key == "evade_counter":
        event_kind, owner, target, source = "combat.attack.missed", TriggerOwner.EVENT_TARGET, TriggerTarget.EVENT_SOURCE, TriggerSource.OWNER
        chance = (0.35, 0.55, 0.75)[tier - 1]
        operations = (_damage(operation_id, TRUE_DAMAGE_ID, 0.24 * factor),)
    elif key == "block_counter":
        event_kind, owner, target, source = "combat.attack.blocked", TriggerOwner.EVENT_TARGET, TriggerTarget.EVENT_SOURCE, TriggerSource.OWNER
        chance = (0.35, 0.55, 0.75)[tier - 1]
        operations = (_damage(operation_id, TRUE_DAMAGE_ID, 0.20 * factor),)
    elif key == "shield_counter":
        event_kind, owner, target, source = "combat.shield.broken", TriggerOwner.EVENT_TARGET, TriggerTarget.EVENT_SOURCE, TriggerSource.OWNER
        operations = (_damage(operation_id, TRUE_DAMAGE_ID, 0.30 * factor),)
    elif key == "damaged_heal":
        event_kind, owner, target, source = "combat.damage.dealt", TriggerOwner.EVENT_TARGET, TriggerTarget.OWNER, TriggerSource.OWNER
        operations = (Heal(operation_id, ParameterMagnitude("event.effective_damage", scale=(0.05, 0.08, 0.12)[tier - 1])),)
    elif key == "damaged_shield":
        event_kind, owner, target, source = "combat.damage.dealt", TriggerOwner.EVENT_TARGET, TriggerTarget.OWNER, TriggerSource.OWNER
        operations = (GrantShield(operation_id, ParameterMagnitude("event.effective_damage", scale=(0.10, 0.16, 0.24)[tier - 1]), maximum_target_health_ratio=0.12),)
    elif key == "critical_spirit":
        event_kind, owner, target, source = "combat.attack.critical", TriggerOwner.EVENT_SOURCE, TriggerTarget.OWNER, TriggerSource.OWNER
        operations = (ChangeResource(operation_id, SPIRIT_CURRENT, FixedMagnitude((4, 7, 11)[tier - 1])),)
    elif key == "hit_spirit":
        event_kind, owner, target, source = "combat.attack.hit", TriggerOwner.EVENT_SOURCE, TriggerTarget.OWNER, TriggerSource.OWNER
        operations = (ChangeResource(operation_id, SPIRIT_CURRENT, FixedMagnitude((2, 3, 5)[tier - 1])),)
    elif key == "kill_cooldown":
        event_kind, owner, target, source = "combat.target.defeated", TriggerOwner.EVENT_SOURCE, TriggerTarget.OWNER, TriggerSource.OWNER
        turns, selection = ((-1, "longest"), (-2, "longest"), (-1, "all"))[tier - 1]
        operations = (ModifyCurrentCooldowns(operation_id, turns=turns, selection=selection),)
    elif key == "turn_heal":
        event_kind, owner, target, source = "combat.turn.started", TriggerOwner.EVENT_SOURCE, TriggerTarget.OWNER, TriggerSource.OWNER
        operations = (Heal(operation_id, AttributeMagnitude(COMBAT_ATTACK, scale=0.12 * factor)),)
    elif key == "turn_spirit":
        event_kind, owner, target, source = "combat.turn.started", TriggerOwner.EVENT_SOURCE, TriggerTarget.OWNER, TriggerSource.OWNER
        operations = (ChangeResource(operation_id, SPIRIT_CURRENT, FixedMagnitude((2, 4, 6)[tier - 1])),)
    elif key == "turn_shield":
        event_kind, owner, target, source = "combat.turn.started", TriggerOwner.EVENT_SOURCE, TriggerTarget.OWNER, TriggerSource.OWNER
        operations = (GrantShield(operation_id, AttributeMagnitude(COMBAT_ATTACK, scale=0.18 * factor), maximum_target_health_ratio=0.15),)
    elif key == "critical_stun":
        event_kind, owner, target, source = "combat.attack.critical", TriggerOwner.EVENT_SOURCE, TriggerTarget.EVENT_TARGET, TriggerSource.OWNER
        chance = (0.20, 0.32, 0.45)[tier - 1]
        operations = (ApplyControl(operation_id, STUN_CONTROL_ID),)
    elif key == "hit_slow":
        event_kind, owner, target, source = "combat.attack.hit", TriggerOwner.EVENT_SOURCE, TriggerTarget.EVENT_TARGET, TriggerSource.OWNER
        chance = (0.18, 0.28, 0.40)[tier - 1]
        operations = (ModifyAttribute(operation_id, COMBAT_SPEED, ModifierLayer.GLOBAL_FLAT, FixedMagnitude((-5, -8, -12)[tier - 1])),)
        effects.append(EffectDefinition(effect_id, tags=TagSet.of("status.negative", "status.slow"), operations=operations, duration_turns=2))
        operations = None
    elif key == "low_health_guard":
        event_kind, owner, target, source = "combat.damage.dealt", TriggerOwner.EVENT_TARGET, TriggerTarget.OWNER, TriggerSource.OWNER
        conditions = (
            ResourceRatioCondition(
                f"condition.equipment.{key}.tier_{tier}",
                ConditionSubject.TARGET,
                HEALTH_CURRENT,
                HEALTH_MAXIMUM,
                Comparison.LESS_OR_EQUAL,
                (0.15, 0.25, 0.35)[tier - 1],
            ),
        )
        operations = (GrantInterceptor(operation_id, DEATH_GUARD_INTERCEPTOR_ID),)
        effects.append(EffectDefinition(effect_id, tags=TagSet.of("status.positive", "status.death_guard"), operations=operations, duration_turns=1))
        operations = None
    elif key == "healing_shield":
        event_kind, owner, target, source = "combat.healing.resolved", TriggerOwner.EVENT_TARGET, TriggerTarget.OWNER, TriggerSource.OWNER
        conditions = (EventValueCondition(f"condition.equipment.{key}.tier_{tier}", "actual", Comparison.GREATER, 0),)
        operations = (GrantShield(operation_id, ParameterMagnitude("event.actual", scale=(0.20, 0.32, 0.48)[tier - 1]), maximum_target_health_ratio=0.15),)
    else:
        raise ValueError(f"未知装备机制词条：{key}")

    if key in {
        "burning_touch",
        "venom_touch",
        "frost_touch",
        "execute_echo",
        "lifesteal",
        "thorns",
        "damaged_heal",
        "damaged_shield",
        "hit_spirit",
        "hit_slow",
        "low_health_guard",
    }:
        conditions = (
            *conditions,
            EventValueCondition(
                f"condition.equipment.{key}.non_proc.tier_{tier}",
                "is_proc",
                Comparison.EQUAL,
                0.0,
            ),
        )
    if key in {
        "execute_echo",
        "damaged_heal",
        "damaged_shield",
        "low_health_guard",
    }:
        conditions = (
            *conditions,
            ResourceRatioCondition(
                f"condition.equipment.{key}.alive.tier_{tier}",
                ConditionSubject.TARGET,
                HEALTH_CURRENT,
                HEALTH_MAXIMUM,
                Comparison.GREATER,
                0.0,
            ),
        )

    if operations is not None:
        effects.append(EffectDefinition(effect_id, operations=operations))
    triggers.insert(
        0,
        TriggerDefinition(
            trigger_id,
            event_kind,
            effect_id,
            target=target,
            owner=owner,
            source=source,
            conditions=conditions,
            chance=chance,
            max_activations_per_execution=1,
        ),
    )
    return tuple(effects), tuple(triggers)


def _mechanic_property(key: str) -> tuple[PropertyDefinition, tuple[EffectDefinition, ...], tuple[TriggerDefinition, ...], tuple[ReferenceValuationDefinition, ...]]:
    effects = []
    triggers = []
    valuations = []
    tiers = []
    for tier in range(1, 4):
        tier_effects, tier_triggers = _mechanic_content(key, tier)
        effects.extend(tier_effects)
        triggers.extend(tier_triggers)
        trigger_id = equipment_trigger_id(key, tier)
        tiers.append(
            PropertyTierDefinition(
                tier,
                (60, 30, 10)[tier - 1],
                ContributionSpec(triggers=frozenset({trigger_id})),
            )
        )
        valuations.append(
            ReferenceValuationDefinition(
                ReferenceValueKind.TRIGGER,
                trigger_id,
                MECHANIC_BASE_VALUES[key].scaled((0.65, 1.0, 1.45)[tier - 1]),
            )
        )
    blueprint = next(value for value in EQUIPMENT_PROPERTY_BLUEPRINTS if value.key == key)
    blocked = {
        "burning_touch": ("venom_touch", "frost_touch"),
        "venom_touch": ("burning_touch", "frost_touch"),
        "frost_touch": ("burning_touch", "venom_touch"),
    }.get(key, ())
    definition = PropertyDefinition(
        equipment_property_id(key),
        8,
        tuple(tiers),
        tags=TagSet.of(
            f"equipment.property.{key}",
            f"equipment.category.{blueprint.category}",
        ),
        blocked_selected_tags=TagSet.of(
            *(f"equipment.property.{value}" for value in blocked)
        ),
    )
    return definition, tuple(effects), tuple(triggers), tuple(valuations)


def build_equipment_property_content() -> EquipmentPropertyContent:
    properties = []
    effects: dict[str, EffectDefinition] = {}
    triggers: dict[str, TriggerDefinition] = {}
    valuations = []
    mechanic_keys = {value.key for value in MECHANIC_EQUIPMENT_PROPERTY_BLUEPRINTS}
    for blueprint in EQUIPMENT_PROPERTY_BLUEPRINTS:
        if blueprint.key in mechanic_keys:
            definition, generated_effects, generated_triggers, generated_values = _mechanic_property(blueprint.key)
            for effect in generated_effects:
                if effect.id in effects and effects[effect.id] != effect:
                    raise ValueError(f"装备 Effect 定义冲突：{effect.id}")
                effects[effect.id] = effect
            for trigger in generated_triggers:
                if trigger.id in triggers and triggers[trigger.id] != trigger:
                    raise ValueError(f"装备 Trigger 定义冲突：{trigger.id}")
                triggers[trigger.id] = trigger
            valuations.extend(generated_values)
        else:
            definition = _numeric_property(blueprint.key)
        properties.append(definition)
    profile = GenerationProfileDefinition(
        EQUIPMENT_GENERATION_PROFILE_ID,
        ItemizationKind.EQUIPMENT,
        frozenset(value.id for value in properties),
        2,
        5,
        EQUIPMENT_QUALITY_BANDS,
        enforce_compatibility=True,
        maximum_attempts=16,
    )
    return EquipmentPropertyContent(
        tuple(effects.values()),
        tuple(triggers.values()),
        tuple(properties),
        (profile,),
        tuple(valuations),
        frozenset(value.id for value in properties),
    )


EQUIPMENT_PROPERTY_CONTENT = build_equipment_property_content()


__all__ = [
    "EQUIPMENT_GENERATION_PROFILE_ID",
    "EQUIPMENT_SET_MARK_CHANCE",
    "EQUIPMENT_PROPERTY_CONTENT",
    "EQUIPMENT_QUALITY_BANDS",
    "EquipmentPropertyContent",
    "build_equipment_property_content",
    "equipment_property_id",
    "equipment_trigger_id",
]
