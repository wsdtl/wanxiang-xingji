"""次元灾厄专属战斗定义，不复用个人或组队首领身份。"""

from __future__ import annotations

from game.core.gameplay import (
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    COMBAT_SPEED,
    HEALTH_MAXIMUM,
    SPIRIT_MAXIMUM,
    BattleAiRule,
    ContributionSpec,
    ENEMY_RANK_BOSS_ID,
    EnemyDefinition,
    EnemyLevelProfileDefinition,
    EnemyRewardProfileDefinition,
    TagSet,
)

from ..combat.definitions import BASIC_ATTACK_ABILITY_ID
from ..combat.stats import COMBAT_CONTROL_RESISTANCE, COMBAT_TENACITY
DISASTER_ENEMY_LEVEL_PROFILE_ID = "enemy.level.dimensional_disaster"
DISASTER_ENEMY_REWARD_PROFILE_ID = "enemy.reward.dimensional_disaster"


def _levels(formula) -> tuple[float, ...]:
    return tuple(round(float(formula(level)), 2) for level in range(1, 101))


DISASTER_ENEMY_LEVEL_PROFILE = EnemyLevelProfileDefinition(
    DISASTER_ENEMY_LEVEL_PROFILE_ID,
    {
        HEALTH_MAXIMUM: _levels(
            lambda level: 110 + 14 * (level - 1) + 0.05 * (level - 1) ** 2
        ),
        SPIRIT_MAXIMUM: _levels(lambda level: 150 + 3 * (level - 1)),
        COMBAT_ATTACK: _levels(lambda level: 8 + 1.0 * (level - 1)),
        COMBAT_DEFENSE: _levels(lambda level: 0.55 * (level - 1)),
        COMBAT_SPEED: _levels(lambda _level: 100),
        COMBAT_CONTROL_RESISTANCE: _levels(lambda _level: 0),
        COMBAT_TENACITY: _levels(lambda _level: 0),
    },
)


# 灾厄奖励由活动贡献结算，敌人报价不能再次产生经验或掉落。
DISASTER_ENEMY_REWARD_PROFILE = EnemyRewardProfileDefinition(
    DISASTER_ENEMY_REWARD_PROFILE_ID,
    0.0,
    0.0,
    None,
    0,
)


_BASIC_AI = (
    BattleAiRule(
        "ai.enemy.dimensional_disaster.basic_attack",
        BASIC_ATTACK_ABILITY_ID,
        "target.enemy.first",
        priority=0,
        maximum_targets=1,
    ),
)


def _enemy(definition) -> EnemyDefinition:
    return EnemyDefinition(
        definition.enemy_definition_id,
        DISASTER_ENEMY_LEVEL_PROFILE_ID,
        DISASTER_ENEMY_REWARD_PROFILE_ID,
        frozenset({ENEMY_RANK_BOSS_ID}),
        base_contribution=ContributionSpec(
            tags=TagSet.of("enemy.identity.dimensional_disaster"),
            abilities=frozenset({BASIC_ATTACK_ABILITY_ID}),
        ),
        base_ai_rules=_BASIC_AI,
        tags=TagSet.of("enemy.identity.dimensional_disaster"),
    )


def build_disaster_enemy_definitions(disasters) -> tuple[EnemyDefinition, ...]:
    values = tuple(disasters)
    ids = tuple(value.enemy_definition_id for value in values)
    if len(ids) != len(set(ids)):
        raise ValueError("灾厄战斗敌人定义 ID 重复")
    return tuple(_enemy(value) for value in values)


from .cultivation import CULTIVATION_DISASTERS
from .magic import MAGIC_DISASTERS
from .stellar_ring import STELLAR_RING_DISASTERS


DISASTER_ENEMY_DEFINITIONS = build_disaster_enemy_definitions(
    (*CULTIVATION_DISASTERS, *MAGIC_DISASTERS, *STELLAR_RING_DISASTERS)
)


__all__ = [name for name in globals() if not name.startswith("_")]
