"""战斗伤害底座回归测试，直接运行即可。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay import (  # noqa: E402
    AbilityDefinition,
    AbilityEngine,
    AbilityUse,
    ActiveEffect,
    AttributeDefinition,
    AttributeMagnitude,
    AttributeResolver,
    ChangeResource,
    CombatStats,
    DamageEngine,
    DamageRequest,
    DamageRules,
    DamageTypeDefinition,
    DealDamage,
    DefinitionRegistry,
    EffectDefinition,
    EffectEngine,
    EffectOperationHandlers,
    EffectReference,
    EffectSpec,
    FixedMagnitude,
    GameplayExecutor,
    GrantTrigger,
    GrantTag,
    ParameterMagnitude,
    ResourceDefinition,
    RuleContext,
    RuleEntity,
    Ruleset,
    Tag,
    TagCondition,
    TagSet,
    ConditionSubject,
    TriggerDefinition,
    TriggerEngine,
    TriggerOwner,
    TriggerTarget,
    register_damage_operation,
)


class SequenceRandom:
    """测试专用随机源，确保命中、暴击和格挡边界完全可控。"""

    def __init__(self, values: tuple[float, ...]) -> None:
        self.values = values
        self.cursor = 0

    def random(self) -> float:
        value = self.values[self.cursor]
        self.cursor += 1
        return value

    def randint(self, minimum: int, maximum: int) -> int:
        return minimum

    def choice(self, values):
        return values[0]

    def checkpoint(self) -> object:
        return self.cursor

    def restore(self, checkpoint: object) -> None:
        self.cursor = int(checkpoint)


def main() -> None:
    _assert_damage_layers()
    _assert_miss_true_damage_and_limits()
    _assert_effect_events_and_actual_damage()
    _assert_lifesteal_and_thorns()
    _assert_multihit_trigger_timing()
    _assert_invalid_references()
    print("combat kernel test: OK")


def _definitions():
    attributes = {
        "health.maximum": AttributeDefinition("health.maximum", default=100, minimum=1),
        "combat.attack": AttributeDefinition("combat.attack", default=0, minimum=0),
        "combat.defense.physical": AttributeDefinition("combat.defense.physical", default=0),
        "combat.penetration.physical.flat": AttributeDefinition(
            "combat.penetration.physical.flat",
            default=0,
            minimum=0,
        ),
        "combat.penetration.physical.rate": AttributeDefinition(
            "combat.penetration.physical.rate",
            default=0,
            minimum=0,
            maximum=1,
        ),
        "combat.accuracy": AttributeDefinition("combat.accuracy", default=0),
        "combat.evasion": AttributeDefinition("combat.evasion", default=0),
        "combat.critical.chance": AttributeDefinition(
            "combat.critical.chance",
            default=0,
            minimum=0,
        ),
        "combat.critical.damage": AttributeDefinition(
            "combat.critical.damage",
            default=0.5,
            minimum=0,
        ),
        "combat.block.chance": AttributeDefinition("combat.block.chance", default=0),
        "combat.block.reduction": AttributeDefinition(
            "combat.block.reduction",
            default=0,
            minimum=0,
        ),
        "combat.damage.outgoing": AttributeDefinition("combat.damage.outgoing", default=0),
        "combat.damage.incoming": AttributeDefinition("combat.damage.incoming", default=0),
    }
    resources = {
        "health.current": ResourceDefinition(
            "health.current",
            maximum_attribute="health.maximum",
        ),
        "shield.current": ResourceDefinition("shield.current", minimum=0),
    }
    damage_types = {
        "damage.physical": DamageTypeDefinition(
            "damage.physical",
            defense_attribute="combat.defense.physical",
            flat_penetration_attribute="combat.penetration.physical.flat",
            rate_penetration_attribute="combat.penetration.physical.rate",
        ),
        "damage.true": DamageTypeDefinition("damage.true", ignores_defense=True),
    }
    stats = CombatStats(
        health_resource="health.current",
        shield_resource="shield.current",
        accuracy_attribute="combat.accuracy",
        evasion_attribute="combat.evasion",
        critical_chance_attribute="combat.critical.chance",
        critical_damage_attribute="combat.critical.damage",
        block_chance_attribute="combat.block.chance",
        block_reduction_attribute="combat.block.reduction",
        outgoing_rate_attribute="combat.damage.outgoing",
        incoming_rate_attribute="combat.damage.incoming",
    )
    resolver = AttributeResolver(attributes)
    engine = DamageEngine(
        damage_types,
        resolver,
        resources,
        stats,
        DamageRules(maximum_critical_multiplier=3, maximum_rate_multiplier=4),
    )
    return resolver, resources, engine


def _context(*rolls: float) -> RuleContext:
    return RuleContext(
        trace_id="combat-test",
        rule_version="rules.v1",
        ruleset=Ruleset("ruleset.standard"),
        logical_time=datetime(2026, 7, 12, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        random=SequenceRandom(tuple(rolls)),
    )


def _entity(entity_id: str, *, health: float = 100, shield: float = 0, **attributes) -> RuleEntity:
    base_attributes = {"health.maximum": 100, **attributes}
    return RuleEntity(
        id=entity_id,
        base_attributes=base_attributes,
        resources={"health.current": health, "shield.current": shield},
        base_tags=TagSet.of("entity.combatant"),
    )


def _assert_damage_layers() -> None:
    _resolver, _resources, engine = _definitions()
    attacker = _entity(
        "attacker",
        **{
            "combat.critical.chance": 1,
            "combat.critical.damage": 1,
            "combat.damage.outgoing": 0.25,
        },
    )
    defender = _entity(
        "defender",
        health=100,
        shield=20,
        **{
            "combat.defense.physical": 100,
            "combat.block.chance": 1,
            "combat.block.reduction": 0.5,
            "combat.damage.incoming": 0.25,
        },
    )
    result = engine.resolve(
        DamageRequest("layered", "damage.physical", 100),
        source=attacker,
        target=defender,
        context=_context(0.0, 0.0, 0.0),
    )
    # 100 * 暴击2 * 正防0.5 * 增减伤1.5 * 格挡0.5 = 75。
    assert result.breakdown.limited == 75
    assert result.shield_damage == 20
    assert result.health_damage == 55
    assert result.critical and result.blocked and result.shield_broken

    negative_defense = _entity(
        "negative-defense",
        **{"combat.defense.physical": -100},
    )
    amplified = engine.resolve(
        DamageRequest(
            "negative-defense",
            "damage.physical",
            100,
            can_miss=False,
            can_critical=False,
            can_block=False,
        ),
        source=_entity("plain-attacker"),
        target=negative_defense,
        context=_context(),
    )
    assert amplified.breakdown.defense_multiplier == 1.5
    assert amplified.breakdown.limited == 150
    assert amplified.health_damage == 100
    assert amplified.overkill == 50


def _assert_miss_true_damage_and_limits() -> None:
    _resolver, _resources, engine = _definitions()
    evasive = _entity("evasive", **{"combat.evasion": 1, "combat.defense.physical": 9999})
    missed = engine.resolve(
        DamageRequest("miss", "damage.physical", 100),
        source=_entity("attacker"),
        target=evasive,
        context=_context(0.5),
    )
    assert not missed.hit and missed.health_damage == 0

    true_damage = engine.resolve(
        DamageRequest(
            "true",
            "damage.true",
            40,
            can_miss=False,
            can_critical=False,
            can_block=False,
            bypass_shield=True,
        ),
        source=_entity("attacker"),
        target=_entity("armored", shield=50, **{"combat.defense.physical": 9999}),
        context=_context(),
    )
    assert true_damage.breakdown.defense_multiplier == 1
    assert true_damage.shield_damage == 0
    assert true_damage.health_damage == 40

    limited = engine.resolve(
        DamageRequest(
            "limited",
            "damage.true",
            500,
            can_miss=False,
            can_critical=False,
            can_block=False,
            maximum_damage=30,
            maximum_target_health_ratio=0.2,
        ),
        source=_entity("attacker"),
        target=_entity("target"),
        context=_context(),
    )
    assert limited.breakdown.limited == 20


def _combat_effect_engine():
    resolver, resources, damage = _definitions()
    handlers = EffectOperationHandlers.with_defaults()
    register_damage_operation(handlers, damage)
    effects = DefinitionRegistry[EffectDefinition]("Effect")
    effects.register(
        EffectDefinition(
            "effect.attack",
            operations=(
                DealDamage(
                    "operation.attack",
                    "damage.physical",
                    AttributeMagnitude("combat.attack"),
                    can_miss=False,
                    can_critical=False,
                    can_block=False,
                ),
            ),
        )
    )
    effects.register(
        EffectDefinition(
            "effect.lifesteal",
            operations=(
                ChangeResource(
                    "operation.lifesteal",
                    "health.current",
                    ParameterMagnitude("event.health_damage", scale=0.5),
                ),
            ),
        )
    )
    effects.register(
        EffectDefinition(
            "effect.thorns.damage",
            operations=(
                DealDamage(
                    "operation.thorns.damage",
                    "damage.true",
                    ParameterMagnitude("event.health_damage", scale=0.25),
                    can_miss=False,
                    can_critical=False,
                    can_block=False,
                ),
            ),
        )
    )
    effects.register(
        EffectDefinition(
            "effect.lifesteal.state",
            operations=(GrantTrigger("operation.lifesteal.state", "trigger.lifesteal"),),
            duration_turns=None,
        )
    )
    effects.register(
        EffectDefinition(
            "effect.thorns.state",
            operations=(GrantTrigger("operation.thorns.state", "trigger.thorns"),),
            duration_turns=None,
        )
    )
    effects.register(
        EffectDefinition(
            "effect.reactive_shield",
            operations=(
                ChangeResource(
                    "operation.reactive_shield",
                    "shield.current",
                    FixedMagnitude(50),
                ),
                GrantTag("operation.reactive_shield.used", Tag("state.reactive_shield.used")),
            ),
            duration_turns=None,
        )
    )
    return EffectEngine(effects, resolver, resources, operations=handlers)


def _assert_effect_events_and_actual_damage() -> None:
    effects = _combat_effect_engine()
    effects.finalize(
        ability_ids=frozenset(),
        trigger_ids=frozenset({"trigger.lifesteal", "trigger.thorns"}),
    )
    attacker = _entity("attacker", **{"combat.attack": 100})
    target = _entity("target", health=10)
    result = effects.apply(
        EffectSpec("damage-effect", "effect.attack", attacker.id),
        source=attacker,
        target=target,
        context=_context(),
    )
    event = next(event for event in result.events if event.kind == "combat.damage.dealt")
    assert result.target.resources["health.current"] == 0
    assert event.values["requested_damage"] == 100
    assert event.values["health_damage"] == 10
    resource_event = next(event for event in result.events if event.kind == "resource.changed")
    assert resource_event.values["delta"] == -10
    assert resource_event.values["requested_delta"] == -10


def _assert_lifesteal_and_thorns() -> None:
    effects = _combat_effect_engine()
    triggers = DefinitionRegistry[TriggerDefinition]("Trigger")
    triggers.register(
        TriggerDefinition(
            "trigger.lifesteal",
            event_kind="combat.damage.dealt",
            effect_id="effect.lifesteal",
            owner=TriggerOwner.EVENT_SOURCE,
            target=TriggerTarget.OWNER,
        )
    )
    triggers.register(
        TriggerDefinition(
            "trigger.thorns",
            event_kind="combat.damage.dealt",
            effect_id="effect.thorns.damage",
            owner=TriggerOwner.EVENT_TARGET,
            target=TriggerTarget.EVENT_SOURCE,
            chance=0.5,
        )
    )
    abilities = DefinitionRegistry[AbilityDefinition]("Ability")
    abilities.register(
        AbilityDefinition("ability.attack", effects=(EffectReference("effect.attack"),))
    )
    ability_engine = AbilityEngine(
        abilities,
        effects,
        trigger_ids=frozenset(triggers.ids()),
    )
    executor = GameplayExecutor(ability_engine, TriggerEngine(triggers, effects))

    attacker = _entity("attacker", health=40, **{"combat.attack": 100})
    attacker = effects.apply(
        EffectSpec("lifesteal-state", "effect.lifesteal.state", attacker.id),
        source=attacker,
        target=attacker,
        context=_context(),
    ).target
    attacker = RuleEntity(
        id=attacker.id,
        base_attributes=attacker.base_attributes,
        resources=attacker.resources,
        base_tags=attacker.base_tags,
        base_abilities=frozenset({"ability.attack"}),
        active_effects=attacker.active_effects,
    )
    defender = _entity("defender", health=20)
    defender = effects.apply(
        EffectSpec("thorns-state", "effect.thorns.state", defender.id),
        source=defender,
        target=defender,
        context=_context(),
    ).target

    outcome = executor.execute_ability(
        AbilityUse("combat-ability", "ability.attack"),
        actor=attacker,
        target=defender,
        context=_context(0.25),
    )
    assert outcome.ok and outcome.value
    # 只造成 20 点实际伤害，因此吸血 10、反伤 5，最终 45 血。
    assert outcome.value.actor.resources["health.current"] == 45
    assert outcome.value.target.resources["health.current"] == 0
    kinds = [event.kind for event in outcome.value.events]
    assert kinds.count("combat.damage.dealt") == 2
    assert "combat.target.defeated" in kinds

    no_thorns = executor.execute_ability(
        AbilityUse("combat-ability-no-thorns", "ability.attack"),
        actor=attacker,
        target=defender,
        context=_context(0.75),
    )
    assert no_thorns.ok and no_thorns.value
    assert no_thorns.value.actor.resources["health.current"] == 50
    assert [event.kind for event in no_thorns.value.events].count("combat.damage.dealt") == 1


def _assert_multihit_trigger_timing() -> None:
    effects = _combat_effect_engine()
    triggers = DefinitionRegistry[TriggerDefinition]("Trigger")
    triggers.register(
        TriggerDefinition(
            "trigger.lifesteal",
            event_kind="combat.damage.dealt",
            effect_id="effect.lifesteal",
            owner=TriggerOwner.EVENT_SOURCE,
            target=TriggerTarget.OWNER,
        )
    )
    triggers.register(
        TriggerDefinition(
            "trigger.thorns",
            event_kind="combat.damage.dealt",
            effect_id="effect.thorns.damage",
            owner=TriggerOwner.EVENT_TARGET,
            target=TriggerTarget.EVENT_SOURCE,
        )
    )
    triggers.register(
        TriggerDefinition(
            "trigger.reactive_shield",
            event_kind="combat.damage.dealt",
            effect_id="effect.reactive_shield",
            owner=TriggerOwner.EVENT_TARGET,
            target=TriggerTarget.OWNER,
            conditions=(
                TagCondition(
                    "condition.reactive_shield.unused",
                    ConditionSubject.SOURCE,
                    blocked=TagSet.of("state.reactive_shield.used"),
                ),
            ),
        )
    )
    abilities = DefinitionRegistry[AbilityDefinition]("Ability")
    abilities.register(
        AbilityDefinition(
            "ability.double_attack",
            effects=(
                EffectReference("effect.attack"),
                EffectReference("effect.attack"),
            ),
        )
    )
    executor = GameplayExecutor(
        AbilityEngine(abilities, effects, trigger_ids=frozenset(triggers.ids())),
        TriggerEngine(triggers, effects),
    )
    attacker = _entity("multihit-attacker", **{"combat.attack": 30})
    attacker = RuleEntity(
        id=attacker.id,
        base_attributes=attacker.base_attributes,
        resources=attacker.resources,
        base_tags=attacker.base_tags,
        base_abilities=frozenset({"ability.double_attack"}),
    )
    defender = _entity("multihit-defender")
    defender = RuleEntity(
        id=defender.id,
        base_attributes=defender.base_attributes,
        resources=defender.resources,
        base_tags=defender.base_tags,
        active_effects=(
            ActiveEffect(
                "reactive-shield-trigger",
                "effect.reactive_shield",
                defender.id,
                granted_triggers=frozenset({"trigger.reactive_shield"}),
            ),
        ),
    )
    outcome = executor.execute_ability(
        AbilityUse("double-attack", "ability.double_attack"),
        actor=attacker,
        target=defender,
        context=_context(),
    )
    assert outcome.ok and outcome.value
    # 第一段扣 30 血并立即触发 50 护盾；第二段由护盾承受 30。
    assert outcome.value.target.resources["health.current"] == 70
    assert outcome.value.target.resources["shield.current"] == 20
    assert [event.kind for event in outcome.value.events].count("trigger.activated") == 1


def _assert_invalid_references() -> None:
    resolver, resources, engine = _definitions()
    try:
        DamageEngine(
            {
                "damage.invalid": DamageTypeDefinition(
                    "damage.invalid",
                    defense_attribute="missing.attribute",
                )
            },
            resolver,
            resources,
            engine.stats,
        )
        raise AssertionError("未知战斗属性必须在启动阶段被拒绝")
    except KeyError as exc:
        assert "missing.attribute" in str(exc)


if __name__ == "__main__":
    main()
