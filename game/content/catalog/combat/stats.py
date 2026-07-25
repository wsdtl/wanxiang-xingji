"""正式武器与装备共用的派生战斗属性、资源和结算配置。"""

from game.core.gameplay import (
    AttributeDefinition,
    CombatProfileDefinition,
    CombatStats,
    ControlDefinition,
    ControlStats,
    DamageRules,
    DamageTypeDefinition,
    RecoveryStats,
    ResourceDefinition,
    Tag,
    TagSet,
)

STANDARD_COMBAT_PROFILE_ID = "combat_profile.standard"
COMBAT_ACCURACY = "combat.accuracy"
COMBAT_EVASION = "combat.evasion"
COMBAT_CRITICAL_CHANCE = "combat.critical.chance"
COMBAT_CRITICAL_DAMAGE = "combat.critical.damage"
COMBAT_BLOCK_CHANCE = "combat.block.chance"
COMBAT_BLOCK_REDUCTION = "combat.block.reduction"
COMBAT_OUTGOING_RATE = "combat.damage.outgoing_rate"
COMBAT_INCOMING_RATE = "combat.damage.incoming_rate"
COMBAT_FLAT_PENETRATION = "combat.penetration.flat"
COMBAT_RATE_PENETRATION = "combat.penetration.rate"
COMBAT_HEALING_RATE = "combat.healing.outgoing_rate"
COMBAT_HEALING_RECEIVED = "combat.healing.received_rate"
COMBAT_CONTROL_CHANCE = "combat.control.chance"
COMBAT_CONTROL_RESISTANCE = "combat.control.resistance"
COMBAT_TENACITY = "combat.control.tenacity"

SHIELD_CURRENT = "combat.shield.current"

PHYSICAL_DAMAGE_ID = "damage.physical"
TRUE_DAMAGE_ID = "damage.true"
FIRE_DAMAGE_ID = "damage.fire"
POISON_DAMAGE_ID = "damage.poison"
FROST_DAMAGE_ID = "damage.frost"

STUN_CONTROL_ID = "control.stun"
FREEZE_CONTROL_ID = "control.freeze"
SLEEP_CONTROL_ID = "control.sleep"

# 历史稳定 ID 保留 weapon 命名；所有会授予该拦截器的内容共用此处事实。
DEATH_GUARD_INTERCEPTOR_ID = "interceptor.weapon.death_guard"


DERIVED_COMBAT_ATTRIBUTES = (
    AttributeDefinition(COMBAT_ACCURACY, minimum=-1.0, maximum=1.0),
    AttributeDefinition(COMBAT_EVASION, minimum=-1.0, maximum=0.9),
    AttributeDefinition(COMBAT_CRITICAL_CHANCE, minimum=0.0, maximum=1.0),
    AttributeDefinition(COMBAT_CRITICAL_DAMAGE, minimum=0.0, maximum=3.0),
    AttributeDefinition(COMBAT_BLOCK_CHANCE, minimum=0.0, maximum=0.9),
    AttributeDefinition(COMBAT_BLOCK_REDUCTION, minimum=0.0, maximum=0.9),
    AttributeDefinition(COMBAT_OUTGOING_RATE, minimum=-0.9, maximum=3.0),
    AttributeDefinition(COMBAT_INCOMING_RATE, minimum=-0.9, maximum=3.0),
    AttributeDefinition(COMBAT_FLAT_PENETRATION, minimum=0.0),
    AttributeDefinition(COMBAT_RATE_PENETRATION, minimum=0.0, maximum=1.0),
    AttributeDefinition(COMBAT_HEALING_RATE, minimum=-1.0, maximum=3.0),
    AttributeDefinition(COMBAT_HEALING_RECEIVED, minimum=-1.0, maximum=3.0),
    AttributeDefinition(COMBAT_CONTROL_CHANCE, minimum=-1.0, maximum=1.0),
    AttributeDefinition(COMBAT_CONTROL_RESISTANCE, minimum=-1.0, maximum=1.0),
    AttributeDefinition(COMBAT_TENACITY, minimum=0.0, maximum=0.9),
)

BATTLE_RESOURCES = (ResourceDefinition(SHIELD_CURRENT),)

BASE_DAMAGE_TYPES = (
    DamageTypeDefinition(
        PHYSICAL_DAMAGE_ID,
        defense_attribute="combat.defense.physical",
        flat_penetration_attribute=COMBAT_FLAT_PENETRATION,
        rate_penetration_attribute=COMBAT_RATE_PENETRATION,
    ),
    DamageTypeDefinition(
        FIRE_DAMAGE_ID,
        defense_attribute="combat.defense.physical",
        flat_penetration_attribute=COMBAT_FLAT_PENETRATION,
        rate_penetration_attribute=COMBAT_RATE_PENETRATION,
        tags=TagSet.of("damage.element.fire"),
    ),
    DamageTypeDefinition(
        FROST_DAMAGE_ID,
        defense_attribute="combat.defense.physical",
        flat_penetration_attribute=COMBAT_FLAT_PENETRATION,
        rate_penetration_attribute=COMBAT_RATE_PENETRATION,
        tags=TagSet.of("damage.element.frost"),
    ),
    DamageTypeDefinition(TRUE_DAMAGE_ID, ignores_defense=True, tags=TagSet.of("damage.true")),
    DamageTypeDefinition(
        POISON_DAMAGE_ID,
        ignores_defense=True,
        tags=TagSet.of("damage.dot.poison"),
    ),
)

BASE_CONTROLS = (
    ControlDefinition(STUN_CONTROL_ID, Tag("state.control.stunned"), 0.72, 1),
    ControlDefinition(FREEZE_CONTROL_ID, Tag("state.control.frozen"), 0.58, 2),
    ControlDefinition(SLEEP_CONTROL_ID, Tag("state.control.sleeping"), 0.82, 1),
)

BASE_COMBAT_PROFILES = (
    CombatProfileDefinition(
        id=STANDARD_COMBAT_PROFILE_ID,
        combat_stats=CombatStats(
            "health.current",
            shield_resource=SHIELD_CURRENT,
            accuracy_attribute=COMBAT_ACCURACY,
            evasion_attribute=COMBAT_EVASION,
            critical_chance_attribute=COMBAT_CRITICAL_CHANCE,
            critical_damage_attribute=COMBAT_CRITICAL_DAMAGE,
            block_chance_attribute=COMBAT_BLOCK_CHANCE,
            block_reduction_attribute=COMBAT_BLOCK_REDUCTION,
            outgoing_rate_attribute=COMBAT_OUTGOING_RATE,
            incoming_rate_attribute=COMBAT_INCOMING_RATE,
        ),
        recovery_stats=RecoveryStats(
            "health.current",
            shield_resource=SHIELD_CURRENT,
            source_healing_rate_attribute=COMBAT_HEALING_RATE,
            target_healing_received_attribute=COMBAT_HEALING_RECEIVED,
            maximum_healing_multiplier=4.0,
        ),
        control_stats=ControlStats(
            source_control_chance_attribute=COMBAT_CONTROL_CHANCE,
            target_control_resistance_attribute=COMBAT_CONTROL_RESISTANCE,
            target_tenacity_attribute=COMBAT_TENACITY,
            maximum_chance=0.95,
        ),
        damage_rules=DamageRules(
            base_hit_chance=0.95,
            minimum_hit_chance=0.20,
            maximum_hit_chance=1.0,
            maximum_critical_multiplier=4.0,
            maximum_rate_multiplier=4.0,
            defense_constant=100.0,
            minimum_damage=1.0,
        ),
    ),
)


__all__ = [
    "BASE_COMBAT_PROFILES",
    "BASE_CONTROLS",
    "BASE_DAMAGE_TYPES",
    "BATTLE_RESOURCES",
    "COMBAT_ACCURACY",
    "COMBAT_BLOCK_CHANCE",
    "COMBAT_BLOCK_REDUCTION",
    "COMBAT_CONTROL_CHANCE",
    "COMBAT_CONTROL_RESISTANCE",
    "COMBAT_CRITICAL_CHANCE",
    "COMBAT_CRITICAL_DAMAGE",
    "COMBAT_EVASION",
    "COMBAT_FLAT_PENETRATION",
    "COMBAT_HEALING_RATE",
    "COMBAT_HEALING_RECEIVED",
    "COMBAT_INCOMING_RATE",
    "COMBAT_OUTGOING_RATE",
    "COMBAT_RATE_PENETRATION",
    "COMBAT_TENACITY",
    "DERIVED_COMBAT_ATTRIBUTES",
    "FIRE_DAMAGE_ID",
    "FREEZE_CONTROL_ID",
    "FROST_DAMAGE_ID",
    "PHYSICAL_DAMAGE_ID",
    "POISON_DAMAGE_ID",
    "SHIELD_CURRENT",
    "SLEEP_CONTROL_ID",
    "STUN_CONTROL_ID",
    "STANDARD_COMBAT_PROFILE_ID",
    "TRUE_DAMAGE_ID",
]
