"""从共享战斗效果构建敌人行为 Ability 和行为模板。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from game.core.gameplay import (
    AbilityDefinition,
    BattleAbilityTargeting,
    BattleAiRule,
    ContributionSpec,
    EnemyBehaviorDefinition,
    ReferenceValuationDefinition,
    ReferenceValueKind,
    TagSet,
    ValueVector,
)

from ..weapon.mechanics import WEAPON_MECHANIC_CONTENT
from ..weapon.registry import OFFICIAL_WEAPON_MECHANICS
from .blueprints import BEHAVIOR_BLUEPRINTS


@dataclass(frozen=True)
class EnemyBehaviorContent:
    behaviors: tuple[EnemyBehaviorDefinition, ...]
    abilities: tuple[AbilityDefinition, ...]
    targeting: tuple[BattleAbilityTargeting, ...]
    reference_valuations: tuple[ReferenceValuationDefinition, ...]
    display_ids: frozenset[str]


def _selector(targeting: BattleAbilityTargeting) -> str:
    preference = (
        "target.enemy.lowest_health",
        "target.enemy.first",
        "target.enemy.all",
        "target.enemy.adjacent",
        "target.enemy.random",
    )
    for selector_id in preference:
        if selector_id in targeting.allowed_selectors:
            return selector_id
    raise ValueError(f"敌人行为没有可自动选择的目标模式：{targeting.ability_id}")


def build_enemy_behavior_content() -> EnemyBehaviorContent:
    source_abilities = {
        OFFICIAL_WEAPON_MECHANICS.recipe_id(
            str(value.id).removeprefix("ability.weapon.")
        ): value
        for value in WEAPON_MECHANIC_CONTENT.abilities
    }
    source_targeting = {value.ability_id: value for value in WEAPON_MECHANIC_CONTENT.targeting}
    source_values = {
        value.reference_id: value.value
        for value in WEAPON_MECHANIC_CONTENT.reference_valuations
        if value.kind is ReferenceValueKind.ABILITY
    }
    behaviors = []
    abilities = []
    targeting = []
    valuations = []
    display_ids = set()
    for blueprint in BEHAVIOR_BLUEPRINTS:
        try:
            source = source_abilities[blueprint.mechanic_recipe_id]
        except KeyError as error:
            raise ValueError(
                f"敌人行为 {blueprint.key} 引用了未知机制配方："
                f"{blueprint.mechanic_recipe_id}"
            ) from error
        source_id = source.id
        ability_id = f"ability.enemy.{blueprint.key}"
        behavior_id = f"enemy.behavior.{blueprint.key}"
        source_rule = source_targeting[source_id]
        ability = replace(
            source,
            id=ability_id,
            tags=source.tags.merged(TagSet.of("ability.enemy", behavior_id)),
        )
        target_rule = replace(source_rule, ability_id=ability_id)
        ai_rule = BattleAiRule(
            f"ai.enemy.{blueprint.key}",
            ability_id,
            _selector(target_rule),
            priority=100,
            maximum_targets=target_rule.maximum_targets,
        )
        behavior = EnemyBehaviorDefinition(
            behavior_id,
            blueprint.attribute_multipliers,
            ContributionSpec(
                tags=TagSet.of(behavior_id),
                abilities=frozenset({ability_id}),
            ),
            (ai_rule,),
            frozenset(f"enemy.behavior.{value}" for value in blueprint.incompatible_keys),
            blueprint.threat_bonus,
        )
        behaviors.append(behavior)
        abilities.append(ability)
        targeting.append(target_rule)
        valuations.append(
            ReferenceValuationDefinition(
                ReferenceValueKind.ABILITY,
                ability_id,
                source_values.get(source_id, ValueVector(offense=10)),
            )
        )
        display_ids.update({behavior_id, ability_id})
    return EnemyBehaviorContent(
        tuple(behaviors),
        tuple(abilities),
        tuple(targeting),
        tuple(valuations),
        frozenset(display_ids),
    )


ENEMY_BEHAVIOR_CONTENT = build_enemy_behavior_content()


__all__ = ["ENEMY_BEHAVIOR_CONTENT", "EnemyBehaviorContent", "build_enemy_behavior_content"]
