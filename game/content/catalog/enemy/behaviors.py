"""复用战斗配方构建身份独立的敌人 Ability、Effect 与 Trigger。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Mapping

from game.core.gameplay import (
    AbilityDefinition,
    BattleAbilityTargeting,
    BattleAiRule,
    ChooseOne,
    ContributionSpec,
    ConsumeEffectStacks,
    DispelEffects,
    EnemyBehaviorDefinition,
    EffectDefinition,
    GrantTrigger,
    ModifyEffectDuration,
    ReferenceValuationDefinition,
    ReferenceValueKind,
    TagSet,
    TriggerDefinition,
    ValueVector,
)

from ..weapon.mechanics import WEAPON_MECHANIC_CONTENT
from ..weapon.official_mechanics import OFFICIAL_WEAPON_MECHANICS
from .blueprints import BEHAVIOR_BLUEPRINTS


@dataclass(frozen=True)
class EnemyBehaviorContent:
    behaviors: tuple[EnemyBehaviorDefinition, ...]
    effects: tuple[EffectDefinition, ...]
    abilities: tuple[AbilityDefinition, ...]
    targeting: tuple[BattleAbilityTargeting, ...]
    triggers: tuple[TriggerDefinition, ...]
    reference_valuations: tuple[ReferenceValuationDefinition, ...]
    display_ids: frozenset[str]
    display_owners: Mapping[str, str]


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
        OFFICIAL_WEAPON_MECHANICS.recipe_id(str(value.id).removeprefix("ability.weapon.")): value
        for value in WEAPON_MECHANIC_CONTENT.abilities
    }
    source_targeting = {value.ability_id: value for value in WEAPON_MECHANIC_CONTENT.targeting}
    source_effects = {str(value.id): value for value in WEAPON_MECHANIC_CONTENT.effects}
    source_triggers = {str(value.id): value for value in WEAPON_MECHANIC_CONTENT.triggers}
    source_values = {
        value.reference_id: value.value
        for value in WEAPON_MECHANIC_CONTENT.reference_valuations
        if value.kind is ReferenceValueKind.ABILITY
    }
    behaviors = []
    effects = []
    abilities = []
    targeting = []
    triggers = []
    valuations = []
    display_ids = set()
    display_owners = {}
    for blueprint in BEHAVIOR_BLUEPRINTS:
        try:
            source = source_abilities[blueprint.mechanic_recipe_id]
        except KeyError as error:
            raise ValueError(f"敌人行为 {blueprint.key} 引用了未知机制配方：{blueprint.mechanic_recipe_id}") from error
        source_id = source.id
        ability_id = f"ability.enemy.{blueprint.key}"
        behavior_id = f"enemy.behavior.{blueprint.key}"
        source_rule = source_targeting[source_id]
        effect_ids, trigger_ids = _behavior_dependencies(
            blueprint.key,
            source,
            source_effects,
            source_triggers,
        )
        behavior_effects = tuple(
            _clone_effect(
                source_effects[source_effect_id],
                effect_ids,
                trigger_ids,
            )
            for source_effect_id in effect_ids
        )
        behavior_triggers = tuple(
            replace(
                source_triggers[source_trigger_id],
                id=trigger_ids[source_trigger_id],
                effect_id=effect_ids[
                    str(source_triggers[source_trigger_id].effect_id)
                ],
            )
            for source_trigger_id in trigger_ids
        )
        ability = replace(
            source,
            id=ability_id,
            tags=source.tags.merged(TagSet.of("ability.enemy", behavior_id)),
            effects=tuple(
                replace(reference, effect_id=effect_ids[str(reference.effect_id)])
                for reference in source.effects
            ),
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
        effects.extend(behavior_effects)
        abilities.append(ability)
        targeting.append(target_rule)
        triggers.extend(behavior_triggers)
        valuations.append(
            ReferenceValuationDefinition(
                ReferenceValueKind.ABILITY,
                ability_id,
                source_values.get(source_id, ValueVector(offense=10)),
            )
        )
        display_ids.update(
            {
                behavior_id,
                ability_id,
                *effect_ids.values(),
                *trigger_ids.values(),
            }
        )
        display_owners.update(
            {
                identifier: blueprint.key
                for identifier in (*effect_ids.values(), *trigger_ids.values())
            }
        )
    return EnemyBehaviorContent(
        tuple(behaviors),
        tuple(effects),
        tuple(abilities),
        tuple(targeting),
        tuple(triggers),
        tuple(valuations),
        frozenset(display_ids),
        MappingProxyType(display_owners),
    )


def _behavior_dependencies(
    behavior_key: str,
    ability: AbilityDefinition,
    source_effects: Mapping[str, EffectDefinition],
    source_triggers: Mapping[str, TriggerDefinition],
) -> tuple[dict[str, str], dict[str, str]]:
    effect_ids: dict[str, str] = {}
    trigger_ids: dict[str, str] = {}

    def include_effect(source_id: str) -> None:
        if source_id in effect_ids:
            return
        definition = source_effects[source_id]
        effect_ids[source_id] = _enemy_content_id("effect", behavior_key, source_id)
        for operation in _walk_operations(definition.operations):
            selected_effect = getattr(operation, "effect_id", None)
            if selected_effect and str(selected_effect) in source_effects:
                include_effect(str(selected_effect))
            if isinstance(operation, GrantTrigger):
                include_trigger(str(operation.trigger_id))

    def include_trigger(source_id: str) -> None:
        if source_id in trigger_ids:
            return
        definition = source_triggers[source_id]
        trigger_ids[source_id] = _enemy_content_id("trigger", behavior_key, source_id)
        include_effect(str(definition.effect_id))

    for reference in ability.effects:
        include_effect(str(reference.effect_id))
    return effect_ids, trigger_ids


def _clone_effect(
    definition: EffectDefinition,
    effect_ids: Mapping[str, str],
    trigger_ids: Mapping[str, str],
) -> EffectDefinition:
    return replace(
        definition,
        id=effect_ids[str(definition.id)],
        operations=tuple(
            _clone_operation(operation, effect_ids, trigger_ids)
            for operation in definition.operations
        ),
    )


def _clone_operation(operation, effect_ids, trigger_ids):
    if isinstance(operation, ChooseOne):
        return replace(
            operation,
            branches=tuple(
                tuple(
                    _clone_operation(nested, effect_ids, trigger_ids)
                    for nested in branch
                )
                for branch in operation.branches
            ),
        )
    if isinstance(operation, GrantTrigger):
        return replace(operation, trigger_id=trigger_ids[str(operation.trigger_id)])
    if isinstance(
        operation,
        (DispelEffects, ConsumeEffectStacks, ModifyEffectDuration),
    ):
        source_id = getattr(operation, "effect_id", None)
        if source_id and str(source_id) in effect_ids:
            return replace(operation, effect_id=effect_ids[str(source_id)])
    return operation


def _walk_operations(operations):
    for operation in operations:
        yield operation
        if isinstance(operation, ChooseOne):
            for branch in operation.branches:
                yield from _walk_operations(branch)


def _enemy_content_id(kind: str, behavior_key: str, source_id: str) -> str:
    prefix = f"{kind}.weapon."
    suffix = source_id.removeprefix(prefix)
    return f"{kind}.enemy.{behavior_key}.{suffix}"


ENEMY_BEHAVIOR_CONTENT = build_enemy_behavior_content()


__all__ = ["ENEMY_BEHAVIOR_CONTENT", "EnemyBehaviorContent", "build_enemy_behavior_content"]
