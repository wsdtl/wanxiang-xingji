"""新角色立即可用的基础战斗定义。"""

from game.core.gameplay import (
    AbilityDefinition,
    AttributeMagnitude,
    BattleAbilityTargeting,
    ChangeResource,
    DealDamage,
    EffectDefinition,
    EffectReference,
    EffectTarget,
    FixedMagnitude,
    ResourceCost,
)

from .stats import BASE_CONTROLS as BASE_CONTROLS
from .stats import BASE_DAMAGE_TYPES, PHYSICAL_DAMAGE_ID
from game.core.gameplay.character import (
    COMBAT_ATTACK,
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    SPIRIT_MAXIMUM,
)


BASIC_ATTACK_EFFECT_ID = "effect.basic_attack"
BREAKING_STRIKE_EFFECT_ID = "effect.breaking_strike"
SMALL_HEALTH_RECOVERY_EFFECT_ID = "effect.recover_small_health"
MEDIUM_HEALTH_RECOVERY_EFFECT_ID = "effect.recover_medium_health"
LARGE_HEALTH_RECOVERY_EFFECT_ID = "effect.recover_large_health"
SMALL_SPIRIT_RECOVERY_EFFECT_ID = "effect.recover_small_spirit"
MEDIUM_SPIRIT_RECOVERY_EFFECT_ID = "effect.recover_medium_spirit"
LARGE_SPIRIT_RECOVERY_EFFECT_ID = "effect.recover_large_spirit"
BASIC_ATTACK_ABILITY_ID = "ability.basic_attack"
BREAKING_STRIKE_ABILITY_ID = "ability.breaking_strike"
SMALL_HEALTH_MEDICINE_ABILITY_ID = "ability.use_small_health_medicine"
MEDIUM_HEALTH_MEDICINE_ABILITY_ID = "ability.use_medium_health_medicine"
LARGE_HEALTH_MEDICINE_ABILITY_ID = "ability.use_large_health_medicine"
SMALL_SPIRIT_MEDICINE_ABILITY_ID = "ability.use_small_spirit_medicine"
MEDIUM_SPIRIT_MEDICINE_ABILITY_ID = "ability.use_medium_spirit_medicine"
LARGE_SPIRIT_MEDICINE_ABILITY_ID = "ability.use_large_spirit_medicine"

SMALL_MEDICINE_RECOVERY_RATIO = 0.12
MEDIUM_MEDICINE_RECOVERY_RATIO = 0.25
LARGE_MEDICINE_RECOVERY_RATIO = 0.50


BASE_EFFECTS = (
    EffectDefinition(
        BASIC_ATTACK_EFFECT_ID,
        operations=(
            DealDamage(
                "operation.basic_attack_damage",
                PHYSICAL_DAMAGE_ID,
                AttributeMagnitude(COMBAT_ATTACK, owner="source"),
            ),
        ),
    ),
    EffectDefinition(
        BREAKING_STRIKE_EFFECT_ID,
        operations=(
            DealDamage(
                "operation.breaking_strike_damage",
                PHYSICAL_DAMAGE_ID,
                AttributeMagnitude(COMBAT_ATTACK, owner="source", scale=1.5),
            ),
        ),
    ),
    EffectDefinition(
        SMALL_HEALTH_RECOVERY_EFFECT_ID,
        operations=(
            ChangeResource(
                "operation.recover_small_health",
                HEALTH_CURRENT,
                AttributeMagnitude(
                    HEALTH_MAXIMUM,
                    owner="target",
                    scale=SMALL_MEDICINE_RECOVERY_RATIO,
                ),
            ),
        ),
    ),
    EffectDefinition(
        MEDIUM_HEALTH_RECOVERY_EFFECT_ID,
        operations=(
            ChangeResource(
                "operation.recover_medium_health",
                HEALTH_CURRENT,
                AttributeMagnitude(
                    HEALTH_MAXIMUM,
                    owner="target",
                    scale=MEDIUM_MEDICINE_RECOVERY_RATIO,
                ),
            ),
        ),
    ),
    EffectDefinition(
        LARGE_HEALTH_RECOVERY_EFFECT_ID,
        operations=(
            ChangeResource(
                "operation.recover_large_health",
                HEALTH_CURRENT,
                AttributeMagnitude(
                    HEALTH_MAXIMUM,
                    owner="target",
                    scale=LARGE_MEDICINE_RECOVERY_RATIO,
                ),
            ),
        ),
    ),
    EffectDefinition(
        SMALL_SPIRIT_RECOVERY_EFFECT_ID,
        operations=(
            ChangeResource(
                "operation.recover_small_spirit",
                SPIRIT_CURRENT,
                AttributeMagnitude(
                    SPIRIT_MAXIMUM,
                    owner="target",
                    scale=SMALL_MEDICINE_RECOVERY_RATIO,
                ),
            ),
        ),
    ),
    EffectDefinition(
        MEDIUM_SPIRIT_RECOVERY_EFFECT_ID,
        operations=(
            ChangeResource(
                "operation.recover_medium_spirit",
                SPIRIT_CURRENT,
                AttributeMagnitude(
                    SPIRIT_MAXIMUM,
                    owner="target",
                    scale=MEDIUM_MEDICINE_RECOVERY_RATIO,
                ),
            ),
        ),
    ),
    EffectDefinition(
        LARGE_SPIRIT_RECOVERY_EFFECT_ID,
        operations=(
            ChangeResource(
                "operation.recover_large_spirit",
                SPIRIT_CURRENT,
                AttributeMagnitude(
                    SPIRIT_MAXIMUM,
                    owner="target",
                    scale=LARGE_MEDICINE_RECOVERY_RATIO,
                ),
            ),
        ),
    ),
)

BASE_ABILITIES = (
    AbilityDefinition(
        BASIC_ATTACK_ABILITY_ID,
        effects=(EffectReference(BASIC_ATTACK_EFFECT_ID),),
    ),
    AbilityDefinition(
        BREAKING_STRIKE_ABILITY_ID,
        costs=(ResourceCost(SPIRIT_CURRENT, FixedMagnitude(20)),),
        effects=(EffectReference(BREAKING_STRIKE_EFFECT_ID),),
        cooldown_turns=2,
    ),
    AbilityDefinition(
        SMALL_HEALTH_MEDICINE_ABILITY_ID,
        effects=(EffectReference(SMALL_HEALTH_RECOVERY_EFFECT_ID, EffectTarget.SELF),),
    ),
    AbilityDefinition(
        MEDIUM_HEALTH_MEDICINE_ABILITY_ID,
        effects=(EffectReference(MEDIUM_HEALTH_RECOVERY_EFFECT_ID, EffectTarget.SELF),),
    ),
    AbilityDefinition(
        LARGE_HEALTH_MEDICINE_ABILITY_ID,
        effects=(EffectReference(LARGE_HEALTH_RECOVERY_EFFECT_ID, EffectTarget.SELF),),
    ),
    AbilityDefinition(
        SMALL_SPIRIT_MEDICINE_ABILITY_ID,
        effects=(EffectReference(SMALL_SPIRIT_RECOVERY_EFFECT_ID, EffectTarget.SELF),),
    ),
    AbilityDefinition(
        MEDIUM_SPIRIT_MEDICINE_ABILITY_ID,
        effects=(EffectReference(MEDIUM_SPIRIT_RECOVERY_EFFECT_ID, EffectTarget.SELF),),
    ),
    AbilityDefinition(
        LARGE_SPIRIT_MEDICINE_ABILITY_ID,
        effects=(EffectReference(LARGE_SPIRIT_RECOVERY_EFFECT_ID, EffectTarget.SELF),),
    ),
)

BASE_BATTLE_TARGETING = (
    BattleAbilityTargeting(
        BASIC_ATTACK_ABILITY_ID,
        frozenset({"target.enemy.explicit", "target.enemy.first"}),
        1,
    ),
    BattleAbilityTargeting(
        BREAKING_STRIKE_ABILITY_ID,
        frozenset({"target.enemy.explicit", "target.enemy.first"}),
        1,
    ),
)

COMBAT_DISPLAY_CONTENT_IDS = frozenset(
    {
        PHYSICAL_DAMAGE_ID,
        BASIC_ATTACK_ABILITY_ID,
        BREAKING_STRIKE_ABILITY_ID,
        SMALL_HEALTH_MEDICINE_ABILITY_ID,
        MEDIUM_HEALTH_MEDICINE_ABILITY_ID,
        LARGE_HEALTH_MEDICINE_ABILITY_ID,
        SMALL_SPIRIT_MEDICINE_ABILITY_ID,
        MEDIUM_SPIRIT_MEDICINE_ABILITY_ID,
        LARGE_SPIRIT_MEDICINE_ABILITY_ID,
    }
)


__all__ = [
    "BASE_ABILITIES",
    "BASE_BATTLE_TARGETING",
    "BASE_DAMAGE_TYPES",
    "BASE_EFFECTS",
    "BASIC_ATTACK_ABILITY_ID",
    "BREAKING_STRIKE_ABILITY_ID",
    "COMBAT_DISPLAY_CONTENT_IDS",
    "LARGE_HEALTH_MEDICINE_ABILITY_ID",
    "LARGE_MEDICINE_RECOVERY_RATIO",
    "LARGE_SPIRIT_MEDICINE_ABILITY_ID",
    "MEDIUM_HEALTH_MEDICINE_ABILITY_ID",
    "MEDIUM_MEDICINE_RECOVERY_RATIO",
    "MEDIUM_SPIRIT_MEDICINE_ABILITY_ID",
    "PHYSICAL_DAMAGE_ID",
    "SMALL_HEALTH_MEDICINE_ABILITY_ID",
    "SMALL_MEDICINE_RECOVERY_RATIO",
    "SMALL_SPIRIT_MEDICINE_ABILITY_ID",
]
