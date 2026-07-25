"""Gameplay 规则内核完整链路测试。"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from game.core.gameplay import (
    AbilityDefinition,
    AbilityEngine,
    AbilityUse,
    AttributeDefinition,
    AttributeMagnitude,
    AttributeResolver,
    ChangeResource,
    Comparison,
    ContentDefinition,
    DefinitionRegistry,
    EffectContribution,
    EffectDefinition,
    EffectEngine,
    EffectOperationContext,
    EffectOperationHandlers,
    EffectReference,
    EffectSpec,
    EffectTarget,
    EventValueCondition,
    ExecutionPhase,
    FixedMagnitude,
    GrantTag,
    GrantTrigger,
    GameplayExecutor,
    ModifierLayer,
    ModifyAttribute,
    ParameterMagnitude,
    ResourceCost,
    ResourceDefinition,
    ResourceRatioCondition,
    RuleContext,
    RuleEntity,
    RuleEvent,
    Ruleset,
    RuleViolation,
    SeededRandomSource,
    SkinCatalog,
    SkinEntry,
    SkinPack,
    StackingPolicy,
    Tag,
    TagSet,
    TriggerDefinition,
    TriggerEngine,
    TriggerOwner,
    TriggerTarget,
    ConditionSubject,
    stable_id,
)


def main() -> None:
    _assert_stable_ids_and_tags()
    content_ids = _assert_content_registry()
    _assert_world_skins(content_ids)
    _assert_rule_context_replay()
    _assert_ability_and_effect_flow()
    _assert_phase_order_and_conditions()
    _assert_trigger_chain_and_failure_codes()
    _assert_operation_extension()
    _assert_invalid_reference_rejected()
    print("gameplay kernel test passed")


def _assert_stable_ids_and_tags() -> None:
    assert stable_id("effect.recover_health") == "effect.recover_health"
    try:
        stable_id("生骨丹")
        raise AssertionError("玩家可见名称不能成为稳定业务 id")
    except ValueError:
        pass

    tags = TagSet.of("item.equipment.main_hand", "weapon.tempo.fast")
    assert tags.has("item.equipment")
    assert tags.has("weapon.tempo.fast")
    assert not tags.has("weapon.tempo.slow")


def _assert_content_registry() -> set[str]:
    definitions = DefinitionRegistry[ContentDefinition]("内容")
    definitions.register(
        ContentDefinition(
            id="item.main_hand.fast_001",
            kind="content.item",
            tags=TagSet.of("item.equipment.main_hand", "weapon.tempo.fast"),
        )
    )
    definitions.register(
        ContentDefinition(
            id="item.consumable.recover_001",
            kind="content.item",
            tags=TagSet.of("item.consumable", "effect.recovery"),
        )
    )
    definitions.freeze()
    try:
        definitions.register(ContentDefinition("item.other.test", "content.item"))
        raise AssertionError("运行期不能继续增加内容定义")
    except RuntimeError:
        pass
    return set(definitions.ids())


def _assert_world_skins(content_ids: set[str]) -> None:
    cultivation_v1 = SkinPack(
        id="skin.cultivation",
        version=1,
        name="太玄界",
        entries={
            "item.main_hand.fast_001": SkinEntry(
                "青锋剑",
                "剑走轻灵",
                aliases=("青锋",),
                compact_name="青锋",
            ),
            "item.consumable.recover_001": SkinEntry("生骨丹", "恢复血气"),
        },
    )
    cultivation_v2 = SkinPack(
        id="skin.cultivation",
        version=2,
        name="太玄界",
        entries={
            "item.main_hand.fast_001": SkinEntry("流云剑", "剑势轻灵", aliases=("流云",)),
            "item.consumable.recover_001": SkinEntry("生骨丹", "恢复血气"),
        },
    )
    magic = SkinPack(
        id="skin.magic",
        version=1,
        name="魔法世界",
        entries={
            "item.main_hand.fast_001": SkinEntry("秘银短杖", "快速引导法术"),
            "item.consumable.recover_001": SkinEntry("生命药剂", "恢复生命"),
        },
    )
    martial = SkinPack(
        id="skin.martial",
        version=1,
        name="武侠世界",
        entries={
            "item.main_hand.fast_001": SkinEntry("雁翎刀", "出手迅疾"),
            "item.consumable.recover_001": SkinEntry("金疮药", "恢复气血"),
        },
    )
    science_fiction = SkinPack(
        id="skin.science_fiction",
        version=1,
        name="科幻世界",
        entries={
            "item.main_hand.fast_001": SkinEntry("粒子刃", "高频近战武装"),
            "item.consumable.recover_001": SkinEntry("修复针剂", "修复生命损伤"),
        },
    )

    catalog = SkinCatalog(content_ids)
    for pack in (cultivation_v1, cultivation_v2, magic, martial, science_fiction):
        catalog.register(pack)
    catalog.freeze()

    assert catalog.skin_ids() == (
        "skin.cultivation",
        "skin.magic",
        "skin.martial",
        "skin.science_fiction",
    )
    assert catalog.versions("skin.cultivation") == (1, 2)
    assert len(catalog) == 5
    assert catalog.require("skin.cultivation").name == "太玄界"
    cultivation_view = catalog.projector("skin.cultivation", version=1)
    latest_cultivation_view = catalog.projector("skin.cultivation")
    magic_view = catalog.projector("skin.magic")
    assert cultivation_view.name("item.main_hand.fast_001") == "青锋剑"
    assert cultivation_view.compact_name("item.main_hand.fast_001") == "青锋"
    assert cultivation_view.compact_name("item.consumable.recover_001") == "生骨丹"
    assert latest_cultivation_view.name("item.main_hand.fast_001") == "流云剑"
    assert magic_view.name("item.main_hand.fast_001") == "秘银短杖"
    try:
        catalog = SkinCatalog(content_ids)
        catalog.register(cultivation_v1)
        catalog.register(
            SkinPack(
                id="skin.duplicate_name",
                version=1,
                name="太玄界",
                entries=cultivation_v1.entries,
            )
        )
        raise AssertionError("不同世界皮肤不能使用相同名称")
    except ValueError as exc:
        assert "名称冲突" in str(exc)
    assert cultivation_view.resolve_alias("青锋") == "item.main_hand.fast_001"


def _rule_context(seed: int = 20260712, *, max_trigger_depth: int = 16) -> RuleContext:
    return RuleContext(
        trace_id=f"trace-{seed}",
        rule_version="rules.v1",
        ruleset=Ruleset(
            "ruleset.standard",
            tags=TagSet.of("context.test"),
            max_trigger_depth=max_trigger_depth,
        ),
        logical_time=datetime(2026, 7, 12, 18, 0, tzinfo=timezone.utc),
        random=SeededRandomSource(seed),
    )


def _assert_rule_context_replay() -> None:
    first = _rule_context(42)
    second = _rule_context(42)
    assert [first.random.randint(1, 100) for _ in range(5)] == [
        second.random.randint(1, 100) for _ in range(5)
    ]
    checkpoint = first.random.checkpoint()
    rolled = first.random.randint(1, 10_000)
    first.random.restore(checkpoint)
    assert first.random.randint(1, 10_000) == rolled


def _rule_engines(*, operations: EffectOperationHandlers | None = None):
    attributes = {
        "combat.attack": AttributeDefinition("combat.attack", default=1, minimum=0),
        "health.maximum": AttributeDefinition("health.maximum", default=1, minimum=1),
        "spirit.maximum": AttributeDefinition("spirit.maximum", default=0, minimum=0),
    }
    resources = {
        "health.current": ResourceDefinition("health.current", maximum_attribute="health.maximum"),
        "spirit.current": ResourceDefinition("spirit.current", maximum_attribute="spirit.maximum"),
    }
    effect_definitions = DefinitionRegistry[EffectDefinition]("Effect")
    effect_definitions.register(
        EffectDefinition(
            id="effect.focus_attack",
            tags=TagSet.of("effect.buff.attack"),
            operations=(
                ModifyAttribute(
                    id="operation.focus_attack",
                    attribute_id="combat.attack",
                    layer=ModifierLayer.GLOBAL_RATE,
                    magnitude=FixedMagnitude(0.5),
                ),
                GrantTag("operation.focus_tag", Tag("state.focused")),
            ),
            duration_turns=2,
            stacking=StackingPolicy.REFRESH,
        )
    )
    effect_definitions.register(
        EffectDefinition(
            id="effect.expand_and_heal",
            operations=(
                ModifyAttribute(
                    id="operation.expand_health",
                    attribute_id="health.maximum",
                    layer=ModifierLayer.LOCAL_FLAT,
                    magnitude=FixedMagnitude(50),
                ),
                ChangeResource(
                    id="operation.fill_expanded_health",
                    resource_id="health.current",
                    magnitude=FixedMagnitude(100),
                ),
            ),
            duration_turns=2,
        )
    )
    effect_definitions.register(
        EffectDefinition(
            id="effect.basic_damage",
            tags=TagSet.of("effect.damage.physical"),
            required_target_tags=TagSet.of("entity.combatant"),
            operations=(
                ChangeResource(
                    id="operation.basic_damage",
                    resource_id="health.current",
                    magnitude=AttributeMagnitude("combat.attack", owner="source", scale=-1.0),
                ),
            ),
        )
    )
    effect_definitions.register(
        EffectDefinition(
            id="effect.recover_health",
            tags=TagSet.of("effect.recovery"),
            operations=(
                ChangeResource(
                    id="operation.recover_health",
                    resource_id="health.current",
                    magnitude=FixedMagnitude(30),
                ),
            ),
        )
    )
    effect_engine = EffectEngine(
        effect_definitions,
        AttributeResolver(attributes),
        resources,
        operations=operations,
    )

    ability_definitions = DefinitionRegistry[AbilityDefinition]("Ability")
    ability_definitions.register(
        AbilityDefinition(
            id="ability.focus",
            effects=(EffectReference("effect.focus_attack", EffectTarget.SELF),),
            cooldown_turns=3,
        )
    )
    ability_definitions.register(
        AbilityDefinition(
            id="ability.expand_and_heal",
            effects=(
                EffectReference(
                    "effect.expand_and_heal",
                    EffectTarget.SELF,
                    ExecutionPhase.BEFORE_APPLY,
                ),
            ),
        )
    )
    ability_definitions.register(
        AbilityDefinition(
            id="ability.emergency_heal",
            conditions=(
                ResourceRatioCondition(
                    id="condition.low_health",
                    subject=ConditionSubject.SOURCE,
                    resource_id="health.current",
                    maximum_attribute_id="health.maximum",
                    comparison=Comparison.LESS_OR_EQUAL,
                    value=0.5,
                ),
            ),
            effects=(EffectReference("effect.recover_health", EffectTarget.SELF),),
        )
    )
    ability_definitions.register(
        AbilityDefinition(
            id="ability.basic_attack",
            required_owner_tags=TagSet.of("entity.combatant"),
            required_target_tags=TagSet.of("entity.combatant"),
            costs=(ResourceCost("spirit.current", FixedMagnitude(5)),),
            effects=(EffectReference("effect.basic_damage"),),
        )
    )
    ability_definitions.register(
        AbilityDefinition(
            id="ability.use_recovery_item",
            effects=(EffectReference("effect.recover_health", EffectTarget.SELF),),
        )
    )
    return effect_engine, AbilityEngine(ability_definitions, effect_engine)


def _assert_ability_and_effect_flow() -> None:
    effect_engine, abilities = _rule_engines()
    actor = RuleEntity(
        id="player-1",
        base_attributes={"combat.attack": 20, "health.maximum": 100, "spirit.maximum": 30},
        resources={"health.current": 75, "spirit.current": 20},
        base_tags=TagSet.of("entity.player", "entity.combatant"),
        base_abilities=frozenset(
            {
                "ability.focus",
                "ability.basic_attack",
                "ability.use_recovery_item",
                "ability.expand_and_heal",
                "ability.emergency_heal",
            }
        ),
    )
    enemy = RuleEntity(
        id="enemy-1",
        base_attributes={"combat.attack": 10, "health.maximum": 80, "spirit.maximum": 0},
        resources={"health.current": 80},
        base_tags=TagSet.of("entity.enemy", "entity.combatant"),
    )

    context = _rule_context()
    focused = abilities.execute(
        AbilityUse("use-focus-1", "ability.focus"),
        actor=actor,
        target=actor,
        context=context,
    )
    actor = focused.actor
    assert actor.tags.has("state.focused")
    assert actor.snapshot(effect_engine.attributes).value("combat.attack") == 30
    assert actor.cooldowns["ability.focus"] == 3

    attacked = abilities.execute(
        AbilityUse("use-attack-1", "ability.basic_attack"),
        actor=actor,
        target=enemy,
        context=context,
    )
    assert attacked.actor.resources["spirit.current"] == 15
    assert attacked.target.resources["health.current"] == 50
    assert [event.kind for event in attacked.events] == [
        "ability.started",
        "resource.changed",
        "effect.applied",
        "resource.changed",
        "ability.completed",
    ]

    healed = abilities.execute(
        AbilityUse("use-item-1", "ability.use_recovery_item"),
        actor=attacked.actor,
        target=attacked.actor,
        context=context,
    )
    assert healed.actor.resources["health.current"] == 100

    first_turn = effect_engine.advance_turn(actor, context)
    second_turn = effect_engine.advance_turn(first_turn.target, context)
    actor_after_two_turns = second_turn.target
    assert [event.kind for event in second_turn.events] == ["effect.expired"]
    assert not actor_after_two_turns.tags.has("state.focused")
    assert actor_after_two_turns.snapshot(effect_engine.attributes).value("combat.attack") == 20


def _assert_phase_order_and_conditions() -> None:
    effect_engine, abilities = _rule_engines()
    context = _rule_context(101)
    actor = RuleEntity(
        id="phase-player",
        base_attributes={"combat.attack": 10, "health.maximum": 100, "spirit.maximum": 20},
        resources={"health.current": 90, "spirit.current": 20},
        base_tags=TagSet.of("entity.player", "entity.combatant"),
        base_abilities=frozenset(
            {"ability.expand_and_heal", "ability.emergency_heal", "ability.basic_attack"}
        ),
    )
    expanded = abilities.execute(
        AbilityUse("phase-expand-1", "ability.expand_and_heal"),
        actor=actor,
        target=actor,
        context=context,
    )
    assert expanded.actor.snapshot(effect_engine.attributes).value("health.maximum") == 150
    assert expanded.actor.resources["health.current"] == 150
    assert {
        event.phase
        for event in expanded.events
        if event.kind in {"effect.applied", "resource.changed"}
    } == {ExecutionPhase.BEFORE_APPLY}

    blocked = abilities.try_execute(
        AbilityUse("phase-heal-blocked", "ability.emergency_heal"),
        actor=actor,
        target=actor,
        context=context,
    )
    assert not blocked.ok
    assert blocked.failure and blocked.failure.code == "ability.owner_condition_failed"

    low_health = actor.replace_resources({"health.current": 40, "spirit.current": 20})
    allowed = abilities.try_execute(
        AbilityUse("phase-heal-allowed", "ability.emergency_heal"),
        actor=low_health,
        target=low_health,
        context=context,
    )
    assert allowed.ok
    assert allowed.value and allowed.value.actor.resources["health.current"] == 70

    no_spirit = actor.replace_resources({"health.current": 90, "spirit.current": 0})
    insufficient = abilities.try_execute(
        AbilityUse("phase-cost-failed", "ability.basic_attack"),
        actor=no_spirit,
        target=low_health,
        context=context,
    )
    assert insufficient.failure and insufficient.failure.code == "resource.insufficient"


def _assert_trigger_chain_and_failure_codes() -> None:
    context = _rule_context(303)
    attributes = {
        "combat.attack": AttributeDefinition("combat.attack", default=20, minimum=0),
        "health.maximum": AttributeDefinition("health.maximum", default=100, minimum=1),
    }
    resources = {
        "health.current": ResourceDefinition("health.current", maximum_attribute="health.maximum"),
    }
    effects = DefinitionRegistry[EffectDefinition]("Effect")
    effects.register(
        EffectDefinition(
            id="effect.trigger_attack_damage",
            operations=(
                ChangeResource(
                    "operation.trigger_attack_damage",
                    "health.current",
                    AttributeMagnitude("combat.attack", scale=-1),
                ),
            ),
        )
    )
    effects.register(
        EffectDefinition(
            id="effect.reflect_damage",
            operations=(
                ChangeResource(
                    "operation.reflect_damage",
                    "health.current",
                    ParameterMagnitude("event.delta", scale=0.5),
                ),
            ),
        )
    )
    effects.register(
        EffectDefinition(
            id="effect.thorns_state",
            operations=(GrantTrigger("operation.grant_thorns", "trigger.reflect_damage"),),
            duration_turns=None,
        )
    )
    effects.register(
        EffectDefinition(
            id="effect.capped_thorns_state",
            operations=(
                GrantTrigger(
                    "operation.grant_capped_thorns",
                    "trigger.reflect_damage.capped",
                ),
            ),
            duration_turns=None,
        )
    )
    trigger_definitions = DefinitionRegistry[TriggerDefinition]("Trigger")
    trigger_definitions.register(
        TriggerDefinition(
            id="trigger.reflect_damage",
            event_kind="resource.changed",
            effect_id="effect.reflect_damage",
            target=TriggerTarget.EVENT_SOURCE,
            owner=TriggerOwner.EVENT_TARGET,
            conditions=(
                EventValueCondition(
                    "condition.damage_only",
                    "delta",
                    Comparison.LESS,
                    0,
                ),
            ),
        )
    )
    trigger_definitions.register(
        TriggerDefinition(
            id="trigger.reflect_damage.capped",
            event_kind="resource.changed",
            effect_id="effect.reflect_damage",
            target=TriggerTarget.EVENT_SOURCE,
            owner=TriggerOwner.EVENT_TARGET,
            conditions=(
                EventValueCondition(
                    "condition.capped_damage_only",
                    "delta",
                    Comparison.LESS,
                    0,
                ),
            ),
            max_activations_per_execution=1,
        )
    )
    effect_engine = EffectEngine(
        effects,
        AttributeResolver(attributes),
        resources,
    )
    abilities = DefinitionRegistry[AbilityDefinition]("Ability")
    abilities.register(
        AbilityDefinition(
            id="ability.trigger_attack",
            effects=(EffectReference("effect.trigger_attack_damage"),),
        )
    )
    ability_engine = AbilityEngine(
        abilities,
        effect_engine,
        trigger_ids=frozenset(trigger_definitions.ids()),
    )
    trigger_engine = TriggerEngine(trigger_definitions, effect_engine)
    executor = GameplayExecutor(ability_engine, trigger_engine)

    attacker = RuleEntity(
        id="trigger-attacker",
        base_attributes={"combat.attack": 20, "health.maximum": 100},
        resources={"health.current": 100},
        base_abilities=frozenset({"ability.trigger_attack"}),
    )
    defender = RuleEntity(
        id="trigger-defender",
        base_attributes={"combat.attack": 10, "health.maximum": 100},
        resources={"health.current": 100},
    )
    thorns = effect_engine.apply(
        EffectSpec("thorns-1", "effect.thorns_state", defender.id),
        source=defender,
        target=defender,
        context=context,
    )
    result = executor.execute_ability(
        AbilityUse("trigger-attack-1", "ability.trigger_attack"),
        actor=attacker,
        target=thorns.target,
        context=context,
    )
    assert result.ok and result.value
    assert result.value.target.resources["health.current"] == 80
    assert result.value.actor.resources["health.current"] == 90
    assert "trigger.activated" in [event.kind for event in result.value.events]
    assert all(event.trace_id == context.trace_id for event in result.value.events)
    assert all(event.rule_version == "rules.v1" for event in result.value.events)
    assert all(event.ruleset_id == "ruleset.standard" for event in result.value.events)

    capped = effect_engine.apply(
        EffectSpec("capped-thorns-1", "effect.capped_thorns_state", defender.id),
        source=defender,
        target=defender,
        context=context,
    ).target
    capped_context = _rule_context(304)
    damage_event = RuleEvent.from_context(
        capped_context,
        kind="resource.changed",
        source_id=attacker.id,
        target_id=capped.id,
        subject_id="health.current",
        values={"delta": -20.0},
    )
    capped_session = trigger_engine.session(capped_context)
    first_batch = capped_session.process(
        (damage_event,),
        {attacker.id: attacker, capped.id: capped},
    )
    second_batch = capped_session.process((damage_event,), first_batch.entities)
    activated = tuple(
        event
        for event in (*first_batch.events, *second_batch.events)
        if event.kind == "trigger.activated"
        and event.subject_id == "trigger.reflect_damage.capped"
    )
    assert len(activated) == 1
    assert second_batch.entity(attacker.id).resources["health.current"] == 90

    self_context = _rule_context(306, max_trigger_depth=1)
    self_event = RuleEvent.from_context(
        self_context,
        kind="resource.changed",
        source_id=capped.id,
        target_id=capped.id,
        subject_id="health.current",
        values={"delta": -20.0},
    )
    self_result = trigger_engine.process(
        (self_event,),
        entities={capped.id: capped},
        context=self_context,
    )
    assert sum(
        event.kind == "trigger.activated"
        and event.subject_id == "trigger.reflect_damage.capped"
        for event in self_result.events
    ) == 1

    recursive_attacker = effect_engine.apply(
        EffectSpec("recursive-thorns-attacker", "effect.thorns_state", attacker.id),
        source=attacker,
        target=attacker,
        context=context,
    ).target
    recursive_defender = effect_engine.apply(
        EffectSpec("recursive-thorns-defender", "effect.thorns_state", defender.id),
        source=defender,
        target=defender,
        context=context,
    ).target
    recursive_context = _rule_context(305, max_trigger_depth=2)
    recursive_event = RuleEvent.from_context(
        recursive_context,
        kind="resource.changed",
        source_id=recursive_attacker.id,
        target_id=recursive_defender.id,
        subject_id="health.current",
        values={"delta": -20.0},
    )
    try:
        trigger_engine.process(
            (recursive_event,),
            entities={
                recursive_attacker.id: recursive_attacker,
                recursive_defender.id: recursive_defender,
            },
            context=recursive_context,
        )
        raise AssertionError("递归触发链必须被深度保护拒绝")
    except RuleViolation as exc:
        assert exc.failure.code == "rule.recursion_limit"

    try:
        _rule_context(404, max_trigger_depth=1).at_trigger_depth(1).next_trigger()
        raise AssertionError("触发深度越界必须被拒绝")
    except RuleViolation as exc:
        assert exc.failure.code == "rule.recursion_limit"


@dataclass(frozen=True)
class ParameterResourceChange:
    """只存在于测试里的新 Effect 原子操作。"""

    id: str
    resource_id: str
    parameter: str


def _assert_operation_extension() -> None:
    handlers = EffectOperationHandlers.with_defaults()

    def apply_parameter_change(
        operation: ParameterResourceChange,
        context: EffectOperationContext,
    ) -> EffectContribution:
        value = context.spec.parameters.get(operation.parameter, 0.0)
        return EffectContribution(resource_deltas={operation.resource_id: value})

    handlers.register(ParameterResourceChange, apply_parameter_change)
    attributes = {
        "health.maximum": AttributeDefinition("health.maximum", default=100, minimum=1),
    }
    resources = {
        "health.current": ResourceDefinition("health.current", maximum_attribute="health.maximum"),
    }
    definitions = DefinitionRegistry[EffectDefinition]("Effect")
    definitions.register(
        EffectDefinition(
            id="effect.extension_demo",
            operations=(
                ParameterResourceChange(
                    "operation.parameter_resource_change",
                    "health.current",
                    "healing",
                ),
            ),
        )
    )
    engine = EffectEngine(
        definitions,
        AttributeResolver(attributes),
        resources,
        operations=handlers,
    )
    engine.finalize()
    entity = RuleEntity(
        id="player-extension",
        base_attributes={"health.maximum": 100},
        resources={"health.current": 10},
    )
    result = engine.apply(
        spec=EffectSpec(
            "extension-1",
            "effect.extension_demo",
            entity.id,
            {"healing": 25},
        ),
        source=entity,
        target=entity,
        context=_rule_context(505),
    )
    assert result.target.resources["health.current"] == 35


def _assert_invalid_reference_rejected() -> None:
    """未知规则引用必须在引擎组装时失败，不能拖到玩家执行时。"""

    effects = DefinitionRegistry[EffectDefinition]("Effect")
    effects.register(
        EffectDefinition(
            id="effect.invalid_reference",
            operations=(
                ChangeResource(
                    "operation.invalid_reference",
                    "resource.unknown",
                    FixedMagnitude(1),
                ),
            ),
        )
    )
    effect_engine = EffectEngine(
        effects,
        AttributeResolver(
            {"health.maximum": AttributeDefinition("health.maximum", default=100)}
        ),
        {},
    )
    abilities = DefinitionRegistry[AbilityDefinition]("Ability")
    abilities.register(
        AbilityDefinition(
            id="ability.invalid_reference",
            effects=(EffectReference("effect.invalid_reference"),),
        )
    )
    try:
        AbilityEngine(abilities, effect_engine)
        raise AssertionError("未知资源引用必须在规则引擎组装时被拒绝")
    except KeyError as exc:
        assert "resource.unknown" in str(exc)


if __name__ == "__main__":
    main()
