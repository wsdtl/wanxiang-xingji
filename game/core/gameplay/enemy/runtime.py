"""敌人实例的战斗投影、阶段判定、威胁估值与奖励报价。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..attributes import AttributeModifier, AttributeResolver, ResourceDefinition
from ..character import ContributionSpec
from ..combat.ai import BattleAiRule
from ..entity import ActiveEffect, RuleEntity
from ..ids import StableId
from ..tags import TagSet
from ..valuation import ValuationEngine
from .catalog import EnemyCatalog
from .models import EnemyInstance, EnemyPhaseLoadout


@dataclass(frozen=True)
class EnemyCombatProjection:
    instance: EnemyInstance
    entity: RuleEntity
    ai_rules: tuple[BattleAiRule, ...]


@dataclass(frozen=True)
class EnemyThreatReport:
    base_score: float
    mechanic_score: float
    behavior_bonus: float
    rank_multiplier: float
    total: float


@dataclass(frozen=True)
class EnemyRewardQuote:
    reward_profile_id: StableId
    loot_table_id: StableId | None
    character_experience: int
    weapon_experience: int
    loot_rolls: int
    threat_score: float


class EnemyCombatProjector:
    def __init__(
        self,
        catalog: EnemyCatalog,
        attributes: AttributeResolver,
        resources: dict[StableId, ResourceDefinition],
    ) -> None:
        if not catalog.finalized:
            raise RuntimeError("敌人目录必须先完成装配")
        self.catalog = catalog
        self.attributes = attributes
        self.resources = dict(resources)

    def project(self, instance: EnemyInstance) -> EnemyCombatProjection:
        definition = self.catalog.require(instance.definition_id)
        rank = self.catalog.ranks.require(instance.rank_id)
        behaviors = tuple(self.catalog.behaviors.require(value) for value in instance.behavior_ids)
        self._validate_instance(instance, definition, rank, behaviors)
        profile = self.catalog.level_profiles.require(definition.level_profile_id)
        base_attributes = dict(profile.attributes_at(instance.level))
        for multipliers in (rank.attribute_multipliers, *(value.attribute_multipliers for value in behaviors)):
            for attribute_id, factor in multipliers.items():
                base_attributes[attribute_id] = base_attributes.get(attribute_id, 0.0) * factor
        specs = (definition.base_contribution, rank.contribution, *(value.contribution for value in behaviors))
        effects = tuple(
            self._effect(instance.id, f"enemy.source_{index}", spec, index)
            for index, spec in enumerate(specs)
            if spec != ContributionSpec()
        )
        entity = RuleEntity(
            id=instance.id,
            base_attributes=base_attributes,
            base_tags=definition.tags.merged(
                TagSet.of("entity.enemy", instance.rank_id, f"enemy.definition.{definition.id}")
            ),
            active_effects=effects,
        )
        snapshot = entity.snapshot(self.attributes)
        resource_values = {}
        for resource_id, resource in self.resources.items():
            if resource.maximum_attribute is not None:
                resource_values[resource_id] = snapshot.value(resource.maximum_attribute)
            elif resource.fixed_maximum is not None:
                resource_values[resource_id] = resource.fixed_maximum
            else:
                resource_values[resource_id] = resource.minimum
        entity = replace(entity, resources=resource_values)
        rules = (*definition.base_ai_rules, *(rule for behavior in behaviors for rule in behavior.ai_rules))
        return EnemyCombatProjection(instance, entity, tuple(rules))

    def apply_phase(
        self,
        entity: RuleEntity,
        instance: EnemyInstance,
        phase: EnemyPhaseLoadout,
    ) -> tuple[RuleEntity, tuple[BattleAiRule, ...]]:
        behaviors = tuple(self.catalog.behaviors.require(value) for value in sorted(phase.behavior_ids))
        base_attributes = dict(entity.base_attributes)
        for behavior in behaviors:
            for attribute_id, factor in behavior.attribute_multipliers.items():
                base_attributes[attribute_id] = base_attributes.get(attribute_id, 0.0) * factor
        new_effects = list(entity.active_effects)
        for index, behavior in enumerate(behaviors):
            new_effects.append(
                self._effect(
                    instance.id,
                    phase.id,
                    behavior.contribution,
                    len(new_effects) + index,
                )
            )
        return replace(entity, base_attributes=base_attributes, active_effects=tuple(new_effects)), tuple(
            rule for behavior in behaviors for rule in behavior.ai_rules
        )

    @staticmethod
    def pending_phases(
        instance: EnemyInstance,
        health_ratio: float,
        active_phase_ids: frozenset[StableId],
    ) -> tuple[EnemyPhaseLoadout, ...]:
        return tuple(
            phase
            for phase in instance.phase_loadouts
            if phase.id not in active_phase_ids and health_ratio <= phase.health_ratio
        )

    def _effect(self, enemy_id: str, source_id: str, spec: ContributionSpec, index: int) -> ActiveEffect:
        modifiers = tuple(
            AttributeModifier(
                id=f"enemy:{enemy_id}:{index}:attribute:{grant_index}",
                attribute_id=grant.attribute_id,
                layer=grant.layer,
                value=grant.value,
                source_id=source_id,
                required_tags=grant.required_tags,
                blocked_tags=grant.blocked_tags,
                priority=grant.priority,
            )
            for grant_index, grant in enumerate(spec.attributes)
        )
        return ActiveEffect(
            instance_id=f"enemy:{enemy_id}:contribution:{index}",
            definition_id=source_id,
            source_id=source_id,
            modifiers=modifiers,
            granted_tags=spec.tags,
            granted_abilities=spec.abilities,
            granted_triggers=spec.triggers,
            granted_interceptors=spec.interceptors,
            granted_target_constraints=spec.target_constraints,
        )

    def _validate_instance(self, instance, definition, rank, behaviors) -> None:
        if instance.rank_id not in definition.allowed_rank_ids:
            raise ValueError(f"敌人 {definition.id} 不允许阶位 {instance.rank_id}")
        phase_behavior_ids = {
            behavior_id
            for phase in instance.phase_loadouts
            for behavior_id in phase.behavior_ids
        }
        all_behavior_ids = set(instance.behavior_ids) | phase_behavior_ids
        if not rank.minimum_behaviors <= len(behaviors) <= rank.maximum_behaviors:
            raise ValueError(f"敌人阶位 {rank.id} 的行为数量无效")
        all_behaviors = tuple(
            self.catalog.behaviors.require(value)
            for value in sorted(all_behavior_ids)
        )
        for behavior in all_behaviors:
            if behavior.incompatible_behavior_ids & all_behavior_ids:
                raise ValueError(f"敌人实例包含互斥行为：{behavior.id}")


class EnemyThreatEvaluator:
    def __init__(self, catalog: EnemyCatalog, valuation: ValuationEngine) -> None:
        self.catalog = catalog
        self.valuation = valuation

    def evaluate(self, instance: EnemyInstance) -> EnemyThreatReport:
        definition = self.catalog.require(instance.definition_id)
        rank = self.catalog.ranks.require(instance.rank_id)
        profile = self.catalog.level_profiles.require(definition.level_profile_id)
        attributes = dict(profile.attributes_at(instance.level))
        behaviors = tuple(self.catalog.behaviors.require(value) for value in instance.behavior_ids)
        for multipliers in (rank.attribute_multipliers, *(value.attribute_multipliers for value in behaviors)):
            for attribute_id, factor in multipliers.items():
                attributes[attribute_id] = attributes.get(attribute_id, 0.0) * factor
        base_score = sum(max(0.0, value) for value in attributes.values()) / max(1, len(attributes))
        specs = (definition.base_contribution, rank.contribution, *(value.contribution for value in behaviors))
        mechanic_score = self.valuation.evaluate(*specs, strict=True).total
        behavior_bonus = sum(value.threat_bonus for value in behaviors)
        total = (base_score + mechanic_score + behavior_bonus) * rank.threat_multiplier
        return EnemyThreatReport(base_score, mechanic_score, behavior_bonus, rank.threat_multiplier, total)

    def reward_quote(self, instance: EnemyInstance) -> EnemyRewardQuote:
        definition = self.catalog.require(instance.definition_id)
        rank = self.catalog.ranks.require(instance.rank_id)
        reward = self.catalog.reward_profiles.require(
            rank.reward_profile_id or definition.reward_profile_id
        )
        threat = self.evaluate(instance)
        return EnemyRewardQuote(
            reward.id,
            reward.loot_table_id,
            max(1, round(instance.level * reward.character_experience_per_level * rank.threat_multiplier)),
            max(0, round(instance.level * reward.weapon_experience_per_level * rank.threat_multiplier)),
            reward.base_loot_rolls + max(0, rank.maximum_behaviors - 1),
            threat.total,
        )


__all__ = [
    "EnemyCombatProjection",
    "EnemyCombatProjector",
    "EnemyRewardQuote",
    "EnemyThreatEvaluator",
    "EnemyThreatReport",
]
