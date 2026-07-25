"""复合公式、状态操作、治疗、干预器与行动指令综合回归测试。"""

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
    ApplyControl,
    AttributeDefinition,
    AttributeMagnitude,
    AttributeResolver,
    BattleAbilityTargeting,
    BattleAction,
    BattleEngine,
    BattleParticipant,
    BattleRules,
    BattleStatus,
    ClampMagnitude,
    COMBAT_FOUNDATION_VERSION,
    CombatStats,
    ConsumeEffectStacks,
    ControlDefinition,
    ControlEngine,
    ControlStats,
    DamageEngine,
    DamageInterceptorDefinition,
    DamageInterceptorRegistry,
    DamageStage,
    DamageTypeDefinition,
    DealDamage,
    DefinitionRegistry,
    DispelEffects,
    EffectDefinition,
    EffectEngine,
    EffectOperationHandlers,
    EffectReference,
    EffectSpec,
    EffectTarget,
    FixedMagnitude,
    GameplayExecutor,
    GrantInterceptor,
    GrantShield,
    GrantTargetConstraint,
    GrantTrigger,
    Heal,
    InterceptorSide,
    MagnitudeContext,
    MaximumMagnitude,
    ModifyAttribute,
    ModifyCooldown,
    ModifyEffectDuration,
    ModifierLayer,
    ParameterMagnitude,
    ProductMagnitude,
    RecoveryEngine,
    RecoveryStats,
    RequestExtraTurn,
    RequestInterrupt,
    RequestTurnDelay,
    ResourceDefinition,
    ResourceMagnitude,
    ResourceValueMode,
    RuleContext,
    RuleEntity,
    Ruleset,
    SeededRandomSource,
    StackingPolicy,
    SumMagnitude,
    Tag,
    TagSet,
    TargetRequest,
    TargetConstraintDefinition,
    TargetConstraintKind,
    TargetConstraintRegistry,
    TargetSelectorRegistry,
    TransferResource,
    TriggerDefinition,
    TriggerEngine,
    TriggerOwner,
    TriggerSource,
    TriggerTarget,
    register_control_operation,
    register_damage_operation,
    register_recovery_operations,
    register_timeline_operations,
)


def main() -> None:
    assert COMBAT_FOUNDATION_VERSION == "combat.foundation.v6"
    engine, effects = _build()
    _assert_composite_magnitudes(effects)
    _assert_state_resource_and_cooldown_operations(effects)
    _assert_recovery_protocol(effects)
    _assert_effect_rejection_protocol(engine, effects)
    _assert_revival_protocol(engine, effects)
    _assert_damage_interceptors(engine, effects)
    _assert_control_protocol(effects)
    _assert_timeline_directives(engine)
    _assert_target_constraints(engine, effects)
    _assert_dynamic_participants(engine)
    print("advanced effects test: OK")


def _context(trace_id: str, seed: int = 7) -> RuleContext:
    return RuleContext(
        trace_id=trace_id,
        rule_version="rules.v1",
        ruleset=Ruleset("ruleset.standard"),
        logical_time=datetime(2026, 7, 12, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        random=SeededRandomSource(seed),
    )


def _entity(
    entity_id: str,
    *,
    health: float = 100,
    spirit: float = 30,
    attack: float = 20,
    defense: float = 0,
    speed: float = 0,
    healing: float = 0,
    received: float = 0,
    resistance: float = 0,
    tenacity: float = 0,
    abilities: tuple[str, ...] = (),
    cooldowns=None,
) -> RuleEntity:
    return RuleEntity(
        id=entity_id,
        base_attributes={
            "health.maximum": 100,
            "spirit.maximum": 30,
            "combat.attack": attack,
            "combat.defense.physical": defense,
            "combat.speed": speed,
            "healing.outgoing": healing,
            "healing.incoming": received,
            "control.chance": 0,
            "control.resistance": resistance,
            "control.tenacity": tenacity,
        },
        resources={
            "health.current": health,
            "spirit.current": spirit,
            "shield.current": 0,
        },
        base_tags=TagSet.of("entity.combatant"),
        base_abilities=frozenset(abilities),
        cooldowns=cooldowns or {},
    )


def _build() -> tuple[BattleEngine, EffectEngine]:
    attributes = {
        "health.maximum": AttributeDefinition("health.maximum", default=100, minimum=1),
        "spirit.maximum": AttributeDefinition("spirit.maximum", default=30, minimum=0),
        "combat.attack": AttributeDefinition("combat.attack", default=10, minimum=0),
        "combat.defense.physical": AttributeDefinition("combat.defense.physical", default=0),
        "combat.speed": AttributeDefinition("combat.speed", default=0),
        "healing.outgoing": AttributeDefinition("healing.outgoing", default=0),
        "healing.incoming": AttributeDefinition("healing.incoming", default=0),
        "control.chance": AttributeDefinition("control.chance", default=0),
        "control.resistance": AttributeDefinition("control.resistance", default=0),
        "control.tenacity": AttributeDefinition("control.tenacity", default=0),
    }
    resources = {
        "health.current": ResourceDefinition(
            "health.current",
            maximum_attribute="health.maximum",
        ),
        "spirit.current": ResourceDefinition(
            "spirit.current",
            maximum_attribute="spirit.maximum",
        ),
        "shield.current": ResourceDefinition("shield.current", minimum=0),
    }
    resolver = AttributeResolver(attributes)

    interceptor_definitions = DefinitionRegistry[DamageInterceptorDefinition]("Interceptor")
    interceptor_definitions.register(
        DamageInterceptorDefinition(
            "interceptor.guard.death",
            "interceptor.death_guard",
            DamageStage.BEFORE_SHIELD,
            InterceptorSide.TARGET,
            configuration={"minimum_health": 1},
        )
    )
    interceptor_definitions.register(
        DamageInterceptorDefinition(
            "interceptor.guard.immunity",
            "interceptor.immunity",
            DamageStage.BEFORE_SHIELD,
            InterceptorSide.TARGET,
        )
    )
    interceptor_definitions.register(
        DamageInterceptorDefinition(
            "interceptor.attack.convert_true",
            "interceptor.convert",
            DamageStage.RAW,
            InterceptorSide.SOURCE,
            configuration={"damage_type": "damage.true"},
        )
    )
    interceptor_definitions.register(
        DamageInterceptorDefinition(
            "interceptor.guard.share_half",
            "interceptor.redirect_to_grant_source",
            DamageStage.BEFORE_SHIELD,
            InterceptorSide.TARGET,
            configuration={"ratio": 0.5, "damage_type": "damage.true"},
        )
    )
    interceptors = DamageInterceptorRegistry(interceptor_definitions)
    interceptors.register_default_handlers()
    damage = DamageEngine(
        {
            "damage.physical": DamageTypeDefinition(
                "damage.physical",
                defense_attribute="combat.defense.physical",
            ),
            "damage.true": DamageTypeDefinition("damage.true", ignores_defense=True),
        },
        resolver,
        resources,
        CombatStats("health.current", "shield.current"),
        interceptors=interceptors,
    )
    recovery = RecoveryEngine(
        resolver,
        resources,
        RecoveryStats(
            "health.current",
            "shield.current",
            "healing.outgoing",
            "healing.incoming",
        ),
    )
    control_definitions = DefinitionRegistry[ControlDefinition]("Control")
    control_definitions.register(
        ControlDefinition("control.stun", Tag("state.control.stunned"), 1.0, 4)
    )
    control = ControlEngine(
        control_definitions,
        resolver,
        ControlStats(
            "control.chance",
            "control.resistance",
            "control.tenacity",
        ),
    )
    target_constraint_definitions = DefinitionRegistry[TargetConstraintDefinition](
        "TargetConstraint"
    )
    target_constraint_definitions.register(
        TargetConstraintDefinition(
            "constraint.taunt",
            TargetConstraintKind.FORCE_GRANT_SOURCE,
        )
    )
    target_constraint_definitions.register(
        TargetConstraintDefinition(
            "constraint.hidden",
            TargetConstraintKind.UNTARGETABLE,
        )
    )
    target_constraints = TargetConstraintRegistry(target_constraint_definitions)

    handlers = EffectOperationHandlers.with_defaults()
    register_damage_operation(handlers, damage)
    register_recovery_operations(handlers, recovery)
    register_control_operation(handlers, control)
    register_timeline_operations(handlers)

    definitions = DefinitionRegistry[EffectDefinition]("Effect")
    definitions.register(
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
    definitions.register(
        EffectDefinition(
            "effect.heal",
            operations=(Heal("operation.heal", FixedMagnitude(30)),),
        )
    )
    definitions.register(
        EffectDefinition(
            "effect.rejectable",
            required_target_tags=TagSet.of("state.accepts_effect"),
            duration_turns=1,
        )
    )
    definitions.register(
        EffectDefinition(
            "effect.shield",
            operations=(
                GrantShield(
                    "operation.shield",
                    FixedMagnitude(100),
                    maximum_target_health_ratio=0.5,
                ),
            ),
        )
    )
    definitions.register(
        EffectDefinition(
            "effect.mark",
            tags=TagSet.of("effect.debuff.mark"),
            operations=(
                ModifyAttribute(
                    "operation.mark.attack",
                    "combat.attack",
                    ModifierLayer.LOCAL_FLAT,
                    FixedMagnitude(10),
                ),
            ),
            duration_turns=3,
            stacking=StackingPolicy.STACK,
            max_stacks=3,
        )
    )
    definitions.register(
        EffectDefinition(
            "effect.consume_mark",
            operations=(ConsumeEffectStacks("operation.consume_mark", "effect.mark", 1),),
        )
    )
    definitions.register(
        EffectDefinition(
            "effect.shorten_mark",
            operations=(ModifyEffectDuration("operation.shorten_mark", "effect.mark", -1),),
        )
    )
    definitions.register(
        EffectDefinition(
            "effect.cleanse",
            operations=(
                DispelEffects(
                    "operation.cleanse",
                    required_tags=TagSet.of("effect.debuff"),
                ),
            ),
        )
    )
    definitions.register(
        EffectDefinition(
            "effect.drain",
            operations=(
                TransferResource(
                    "operation.drain",
                    "spirit.current",
                    FixedMagnitude(20),
                ),
            ),
        )
    )
    definitions.register(
        EffectDefinition(
            "effect.cooldown_reduce",
            operations=(ModifyCooldown("operation.cooldown_reduce", "ability.attack", turns=-2),),
        )
    )
    definitions.register(
        EffectDefinition(
            "effect.death_guard",
            operations=(
                GrantInterceptor("operation.death_guard", "interceptor.guard.death"),
            ),
            duration_turns=None,
        )
    )
    definitions.register(
        EffectDefinition(
            "effect.immunity",
            operations=(
                GrantInterceptor("operation.immunity", "interceptor.guard.immunity"),
            ),
            duration_turns=None,
        )
    )
    definitions.register(
        EffectDefinition(
            "effect.convert_true",
            operations=(
                GrantInterceptor(
                    "operation.convert_true",
                    "interceptor.attack.convert_true",
                ),
            ),
            duration_turns=None,
        )
    )
    definitions.register(
        EffectDefinition(
            "effect.share_guard",
            operations=(
                GrantInterceptor(
                    "operation.share_guard",
                    "interceptor.guard.share_half",
                ),
            ),
            duration_turns=None,
        )
    )
    definitions.register(
        EffectDefinition(
            "effect.redirect_receiver",
            operations=(
                GrantTrigger(
                    "operation.redirect_receiver",
                    "trigger.redirect_damage",
                ),
            ),
            duration_turns=None,
        )
    )
    definitions.register(
        EffectDefinition(
            "effect.revive_state",
            operations=(
                GrantTrigger("operation.revive_state", "trigger.revive_on_defeat"),
            ),
            duration_turns=None,
        )
    )
    definitions.register(
        EffectDefinition(
            "effect.redirect_damage",
            operations=(
                DealDamage(
                    "operation.redirect_damage",
                    "damage.true",
                    ParameterMagnitude("event.amount"),
                    can_miss=False,
                    can_critical=False,
                    can_block=False,
                ),
            ),
        )
    )
    definitions.register(
        EffectDefinition(
            "effect.stun",
            operations=(ApplyControl("operation.stun", "control.stun"),),
        )
    )
    definitions.register(
        EffectDefinition(
            "effect.taunted",
            operations=(
                GrantTargetConstraint("operation.taunted", "constraint.taunt"),
            ),
            duration_turns=2,
        )
    )
    definitions.register(
        EffectDefinition(
            "effect.hidden",
            operations=(
                GrantTargetConstraint("operation.hidden", "constraint.hidden"),
            ),
            duration_turns=2,
        )
    )
    definitions.register(
        EffectDefinition(
            "effect.extra_turn",
            operations=(RequestExtraTurn("operation.extra_turn"),),
        )
    )
    definitions.register(
        EffectDefinition(
            "effect.delay",
            operations=(RequestTurnDelay("operation.delay", positions=1),),
        )
    )
    definitions.register(
        EffectDefinition(
            "effect.interrupt",
            operations=(RequestInterrupt("operation.interrupt"),),
        )
    )
    effects = EffectEngine(definitions, resolver, resources, operations=handlers)

    abilities = DefinitionRegistry[AbilityDefinition]("Ability")
    abilities.register(
        AbilityDefinition("ability.attack", effects=(EffectReference("effect.attack"),))
    )
    abilities.register(
        AbilityDefinition(
            "ability.rejectable",
            effects=(EffectReference("effect.rejectable"),),
        )
    )
    abilities.register(
        AbilityDefinition(
            "ability.interrupted_combo",
            effects=(
                EffectReference("effect.interrupt", EffectTarget.SELF),
                EffectReference("effect.attack"),
            ),
        )
    )
    abilities.register(
        AbilityDefinition(
            "ability.extra_turn",
            effects=(EffectReference("effect.extra_turn", EffectTarget.SELF),),
        )
    )
    abilities.register(
        AbilityDefinition("ability.delay", effects=(EffectReference("effect.delay"),))
    )
    abilities.register(
        AbilityDefinition("ability.true_sight", effects=(EffectReference("effect.attack"),))
    )
    triggers = DefinitionRegistry[TriggerDefinition]("Trigger")
    triggers.register(
        TriggerDefinition(
            "trigger.redirect_damage",
            event_kind="combat.damage.redirected",
            effect_id="effect.redirect_damage",
            owner=TriggerOwner.EVENT_TARGET,
            target=TriggerTarget.OWNER,
            source=TriggerSource.EVENT_SOURCE,
        )
    )
    triggers.register(
        TriggerDefinition(
            "trigger.revive_on_defeat",
            event_kind="combat.target.defeated",
            effect_id="effect.heal",
            owner=TriggerOwner.EVENT_TARGET,
            target=TriggerTarget.OWNER,
            source=TriggerSource.OWNER,
        )
    )
    ability_engine = AbilityEngine(
        abilities,
        effects,
        trigger_ids=frozenset(triggers.ids()),
        interceptor_ids=interceptors.ids(),
        target_constraint_ids=target_constraints.ids(),
    )
    executor = GameplayExecutor(ability_engine, TriggerEngine(triggers, effects))
    targeting = {
        "ability.attack": BattleAbilityTargeting(
            "ability.attack",
            frozenset({"target.enemy.explicit"}),
            1,
        ),
        "ability.rejectable": BattleAbilityTargeting(
            "ability.rejectable",
            frozenset({"target.enemy.explicit"}),
            1,
        ),
        "ability.interrupted_combo": BattleAbilityTargeting(
            "ability.interrupted_combo",
            frozenset({"target.enemy.explicit"}),
            1,
        ),
        "ability.extra_turn": BattleAbilityTargeting(
            "ability.extra_turn",
            frozenset({"target.self"}),
            1,
        ),
        "ability.delay": BattleAbilityTargeting(
            "ability.delay",
            frozenset({"target.enemy.explicit"}),
            1,
        ),
        "ability.true_sight": BattleAbilityTargeting(
            "ability.true_sight",
            frozenset({"target.enemy.explicit"}),
            1,
            bypass_target_constraints=True,
        ),
    }
    return (
        BattleEngine(
            executor,
            BattleRules("health.current", "combat.speed", maximum_rounds=10),
            targeting,
            selectors=TargetSelectorRegistry.with_defaults(target_constraints),
        ),
        effects,
    )


def _apply(effects, effect_id, source, target, trace):
    return effects.apply(
        EffectSpec(trace, effect_id, source.id),
        source=source,
        target=target,
        context=_context(trace),
    )


def _assert_composite_magnitudes(effects: EffectEngine) -> None:
    source = _entity("formula-source", attack=20)
    target = _entity("formula-target", health=40)
    context = MagnitudeContext(
        source.snapshot(effects.attributes),
        target.snapshot(effects.attributes),
        {},
        source.resources,
        target.resources,
    )
    formula = ClampMagnitude(
        SumMagnitude(
            (
                AttributeMagnitude("combat.attack"),
                ProductMagnitude(
                    (
                        ResourceMagnitude(
                            "health.current",
                            mode=ResourceValueMode.MISSING_RATIO,
                            maximum_attribute_id="health.maximum",
                        ),
                        FixedMagnitude(100),
                    )
                ),
            )
        ),
        maximum=MaximumMagnitude((FixedMagnitude(50), FixedMagnitude(40))),
    )
    assert effects.magnitudes.evaluate(formula, context) == 50
    effects.magnitudes.validate(
        formula,
        frozenset(effects.attributes.definitions),
        frozenset(effects.resources),
    )


def _assert_state_resource_and_cooldown_operations(effects: EffectEngine) -> None:
    source = _entity("state-source", spirit=25)
    target = _entity("state-target", spirit=15, attack=10, cooldowns={"ability.attack": 3})
    for index in range(3):
        target = _apply(effects, "effect.mark", source, target, f"mark-{index}").target
    assert target.snapshot(effects.attributes).value("combat.attack") == 40
    assert target.active_effects[0].stacks == 3

    consumed = _apply(effects, "effect.consume_mark", source, target, "consume-mark")
    target = consumed.target
    assert target.active_effects[0].stacks == 2
    assert target.snapshot(effects.attributes).value("combat.attack") == 30
    target = _apply(effects, "effect.shorten_mark", source, target, "shorten-mark").target
    assert target.active_effects[0].remaining_turns == 2
    target = _apply(effects, "effect.cleanse", source, target, "cleanse-mark").target
    assert not target.active_effects

    target = _apply(effects, "effect.cooldown_reduce", source, target, "cooldown").target
    assert target.cooldowns["ability.attack"] == 1

    drained = _apply(effects, "effect.drain", source, target, "drain")
    assert drained.target.resources["spirit.current"] == 0
    assert drained.source and drained.source.resources["spirit.current"] == 30
    source_event = next(
        event
        for event in drained.events
        if event.kind == "resource.changed" and event.target_id == source.id
    )
    assert source_event.values["delta"] == 5


def _assert_recovery_protocol(effects: EffectEngine) -> None:
    healer = _entity("healer", healing=0.5)
    target = _entity("patient", health=80, received=-0.2)
    healed = _apply(effects, "effect.heal", healer, target, "heal")
    assert healed.target.resources["health.current"] == 100
    event = next(event for event in healed.events if event.kind == "combat.healing.resolved")
    assert event.values["modified"] == 39
    assert event.values["actual"] == 20
    assert event.values["overheal"] == 19

    shielded = _entity("shielded")
    shielded = shielded.replace_resources(
        {**shielded.resources, "shield.current": 20}
    )
    result = _apply(effects, "effect.shield", healer, shielded, "shield")
    assert result.target.resources["shield.current"] == 50


def _assert_effect_rejection_protocol(
    engine: BattleEngine,
    effects: EffectEngine,
) -> None:
    source = _entity(
        "rejection-source",
        abilities=("ability.rejectable",),
    )
    target = _entity("rejection-target")
    rejected = engine.executor.execute_ability_many(
        AbilityUse("rejected-use", "ability.rejectable"),
        actor_id=source.id,
        target_ids=(target.id,),
        entities={source.id: source, target.id: target},
        context=_context("rejected-use"),
    )
    assert rejected.ok and rejected.value
    event = next(
        event
        for event in rejected.value.events
        if event.kind == "effect.application.rejected"
    )
    assert event.subject_id == "effect.rejectable"
    assert event.values["reason"] == "target_blocked"
    assert not any(
        event.kind == "effect.applied" and event.subject_id == "effect.rejectable"
        for event in rejected.value.events
    )

    resistant = _entity("rejection-resistant", resistance=1)
    control = _apply(effects, "effect.stun", source, resistant, "control-rejected")
    control_rejection = next(
        event
        for event in control.events
        if event.kind == "effect.application.rejected"
    )
    assert control_rejection.subject_id == "effect.stun"
    assert control_rejection.values["reason"] == "control_resisted"


def _assert_revival_protocol(
    engine: BattleEngine,
    effects: EffectEngine,
) -> None:
    attacker = _entity(
        "revival-attacker",
        attack=100,
        speed=20,
        abilities=("ability.attack",),
    )
    revived = _entity("revival-target", speed=10)
    revived = _apply(
        effects,
        "effect.revive_state",
        revived,
        revived,
        "revival-state",
    ).target
    state = _start(
        engine,
        {attacker.id: attacker, revived.id: revived},
        {attacker.id: "team.attacker", revived.id: "team.revived"},
        {attacker.id: 0, revived.id: 0},
        "battle.revival",
    )
    result = engine.execute_turn(
        state,
        BattleAction(
            "action.revival",
            attacker.id,
            "ability.attack",
            TargetRequest("target.enemy.explicit", explicit_ids=(revived.id,)),
        ),
        context=_context("battle.revival.turn"),
    )
    assert result.ok and result.value
    assert result.value.state.status is BattleStatus.ACTIVE
    assert result.value.state.current_actor_id == revived.id
    assert result.value.state.entities[revived.id].resources["health.current"] == 30
    event_kinds = [event.kind for event in result.value.events]
    assert event_kinds.index("combat.target.defeated") < event_kinds.index(
        "combat.target.revived"
    )
    assert "combat.battle.finished" not in event_kinds
    revival = next(
        event
        for event in result.value.events
        if event.kind == "combat.target.revived"
    )
    assert revival.source_id == revived.id
    assert revival.target_id == revived.id
    assert revival.values == {"before": 0.0, "after": 30.0, "actual": 30.0}


def _assert_damage_interceptors(engine: BattleEngine, effects: EffectEngine) -> None:
    attacker = _entity("interceptor-attacker", attack=100)
    guarded = _entity("guarded")
    guarded = _apply(effects, "effect.death_guard", guarded, guarded, "guard-state").target
    result = _apply(effects, "effect.attack", attacker, guarded, "guard-hit")
    assert result.target.resources["health.current"] == 1
    assert "combat.damage.intercepted" in [event.kind for event in result.events]

    immune = _entity("immune")
    immune = _apply(effects, "effect.immunity", immune, immune, "immune-state").target
    result = _apply(effects, "effect.attack", attacker, immune, "immune-hit")
    assert result.target.resources["health.current"] == 100
    assert "combat.damage.prevented" in [event.kind for event in result.events]

    converted = _apply(
        effects,
        "effect.convert_true",
        attacker,
        attacker,
        "convert-state",
    ).target
    armored = _entity("armored", defense=100)
    result = _apply(effects, "effect.attack", converted, armored, "convert-hit")
    assert result.target.resources["health.current"] == 0
    dealt = next(event for event in result.events if event.kind == "combat.damage.dealt")
    assert dealt.values["damage_type"] == "damage.true"

    protector = _entity("protector")
    protected = _entity("protected")
    protected = _apply(
        effects,
        "effect.share_guard",
        protector,
        protected,
        "share-guard",
    ).target
    protector = _apply(
        effects,
        "effect.redirect_receiver",
        protector,
        protector,
        "share-receiver",
    ).target
    attacker = _entity("share-attacker", attack=100, abilities=("ability.attack",))
    shared = engine.executor.execute_ability_many(
        AbilityUse("share-attack", "ability.attack"),
        actor_id=attacker.id,
        target_ids=(protected.id,),
        entities={
            attacker.id: attacker,
            protected.id: protected,
            protector.id: protector,
        },
        context=_context("share-attack"),
    )
    assert shared.ok and shared.value
    assert shared.value.entity(protected.id).resources["health.current"] == 50
    assert shared.value.entity(protector.id).resources["health.current"] == 50
    assert "combat.damage.redirected" in [event.kind for event in shared.value.events]


def _assert_control_protocol(effects: EffectEngine) -> None:
    source = _entity("controller")
    target = _entity("controlled", tenacity=0.5)
    result = _apply(effects, "effect.stun", source, target, "stun-success")
    assert result.target.tags.has("state.control.stunned")
    assert result.target.active_effects[0].remaining_turns == 2

    resistant = _entity("resistant", resistance=1)
    result = _apply(effects, "effect.stun", source, resistant, "stun-resisted")
    assert not result.target.tags.has("state.control.stunned")
    event = next(event for event in result.events if event.kind == "combat.control.resolved")
    assert event.values["applied"] is False
    rejection = next(
        event
        for event in result.events
        if event.kind == "effect.application.rejected"
    )
    assert rejection.values["reason"] == "control_resisted"


def _start(engine: BattleEngine, entities, teams, slots, battle_id):
    outcome = engine.start(
        battle_id,
        participants=tuple(
            BattleParticipant(entity_id, teams[entity_id], slots[entity_id])
            for entity_id in entities
        ),
        entities=entities,
        context=_context(f"{battle_id}.start"),
    )
    assert outcome.ok and outcome.value
    return outcome.value.state


def _assert_timeline_directives(engine: BattleEngine) -> None:
    hero = _entity(
        "timeline-hero",
        speed=20,
        abilities=("ability.extra_turn", "ability.interrupted_combo", "ability.delay"),
    )
    enemy = _entity("timeline-enemy", speed=10)
    state = _start(
        engine,
        {hero.id: hero, enemy.id: enemy},
        {hero.id: "team.hero", enemy.id: "team.enemy"},
        {hero.id: 0, enemy.id: 0},
        "battle.extra",
    )
    extra = engine.execute_turn(
        state,
        BattleAction(
            "action.extra",
            hero.id,
            "ability.extra_turn",
            TargetRequest("target.self"),
        ),
        context=_context("battle.extra.turn"),
    )
    assert extra.ok and extra.value
    assert extra.value.state.current_actor_id == hero.id

    interrupted = engine.execute_turn(
        extra.value.state,
        BattleAction(
            "action.interrupted",
            hero.id,
            "ability.interrupted_combo",
            TargetRequest("target.enemy.explicit", (enemy.id,)),
        ),
        context=_context("battle.extra.interrupted"),
    )
    assert interrupted.ok and interrupted.value
    assert interrupted.value.state.entity(enemy.id).resources["health.current"] == 100

    hero2 = _entity("delay-hero", speed=20, abilities=("ability.delay",))
    enemy_a = _entity("delay-a", speed=10)
    enemy_b = _entity("delay-b", speed=5)
    delay_state = _start(
        engine,
        {hero2.id: hero2, enemy_a.id: enemy_a, enemy_b.id: enemy_b},
        {
            hero2.id: "team.hero",
            enemy_a.id: "team.enemy",
            enemy_b.id: "team.enemy",
        },
        {hero2.id: 0, enemy_a.id: 0, enemy_b.id: 1},
        "battle.delay",
    )
    delayed = engine.execute_turn(
        delay_state,
        BattleAction(
            "action.delay",
            hero2.id,
            "ability.delay",
            TargetRequest("target.enemy.explicit", (enemy_a.id,)),
        ),
        context=_context("battle.delay.turn"),
    )
    assert delayed.ok and delayed.value
    assert delayed.value.state.current_actor_id == enemy_b.id


def _assert_dynamic_participants(engine: BattleEngine) -> None:
    hero = _entity("join-hero", speed=20)
    enemy = _entity("join-enemy", speed=10)
    state = _start(
        engine,
        {hero.id: hero, enemy.id: enemy},
        {hero.id: "team.hero", enemy.id: "team.enemy"},
        {hero.id: 0, enemy.id: 0},
        "battle.join",
    )
    summon = _entity("join-summon", speed=15)
    joined = engine.join(
        state,
        BattleParticipant(summon.id, "team.hero", 1),
        summon,
        context=_context("battle.join.summon"),
    )
    assert joined.ok and joined.value
    assert summon.id in joined.value.state.entities
    assert summon.id not in joined.value.state.turn_order

    left = engine.withdraw(
        joined.value.state,
        enemy.id,
        context=_context("battle.join.enemy_left"),
        reason="fled",
    )
    assert left.ok and left.value
    assert left.value.state.status is BattleStatus.FINISHED
    assert left.value.state.winning_teams == ("team.hero",)


def _assert_target_constraints(engine: BattleEngine, effects: EffectEngine) -> None:
    actor = _entity(
        "constraint-actor",
        speed=20,
        abilities=("ability.attack", "ability.true_sight"),
    )
    taunter = _entity("constraint-taunter", speed=10)
    other = _entity("constraint-other", speed=5)
    actor = _apply(effects, "effect.taunted", taunter, actor, "apply-taunt").target
    state = _start(
        engine,
        {actor.id: actor, taunter.id: taunter, other.id: other},
        {
            actor.id: "team.hero",
            taunter.id: "team.enemy",
            other.id: "team.enemy",
        },
        {actor.id: 0, taunter.id: 0, other.id: 1},
        "battle.constraint.taunt",
    )
    wrong_target = engine.execute_turn(
        state,
        BattleAction(
            "action.ignore_taunt",
            actor.id,
            "ability.attack",
            TargetRequest("target.enemy.explicit", (other.id,)),
        ),
        context=_context("battle.constraint.taunt.wrong"),
    )
    assert wrong_target.failure and wrong_target.failure.code == "target.no_valid_target"
    correct_target = engine.execute_turn(
        state,
        BattleAction(
            "action.follow_taunt",
            actor.id,
            "ability.attack",
            TargetRequest("target.enemy.explicit", (taunter.id,)),
        ),
        context=_context("battle.constraint.taunt.correct"),
    )
    assert correct_target.ok and correct_target.value

    hidden = _entity("constraint-hidden", speed=10)
    hidden = _apply(effects, "effect.hidden", hidden, hidden, "apply-hidden").target
    viewer = _entity(
        "constraint-viewer",
        speed=20,
        abilities=("ability.attack", "ability.true_sight"),
    )
    hidden_state = _start(
        engine,
        {viewer.id: viewer, hidden.id: hidden},
        {viewer.id: "team.hero", hidden.id: "team.enemy"},
        {viewer.id: 0, hidden.id: 0},
        "battle.constraint.hidden",
    )
    blocked = engine.execute_turn(
        hidden_state,
        BattleAction(
            "action.hidden.blocked",
            viewer.id,
            "ability.attack",
            TargetRequest("target.enemy.explicit", (hidden.id,)),
        ),
        context=_context("battle.constraint.hidden.blocked"),
    )
    assert blocked.failure and blocked.failure.code == "target.no_valid_target"
    revealed = engine.execute_turn(
        hidden_state,
        BattleAction(
            "action.hidden.revealed",
            viewer.id,
            "ability.true_sight",
            TargetRequest("target.enemy.explicit", (hidden.id,)),
        ),
        context=_context("battle.constraint.hidden.revealed"),
    )
    assert revealed.ok and revealed.value


if __name__ == "__main__":
    main()
