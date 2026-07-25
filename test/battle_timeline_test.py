"""多实体目标与战斗时间线回归测试。"""

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
    AttributeDefinition,
    AttributeMagnitude,
    AttributeResolver,
    BattleAction,
    BattleAbilityTargeting,
    BattleEngine,
    BattleParticipant,
    BattleRules,
    BattleStatus,
    CombatStats,
    DamageEngine,
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
    GrantTag,
    GrantTrigger,
    ParameterMagnitude,
    ResourceCost,
    ResourceDefinition,
    RuleContext,
    RuleEntity,
    Ruleset,
    SeededRandomSource,
    StackingPolicy,
    Tag,
    TagSet,
    TargetRequest,
    TriggerDefinition,
    TriggerEngine,
    TriggerOwner,
    TriggerSource,
    TriggerTarget,
    register_damage_operation,
)


def main() -> None:
    _assert_target_registry_and_multi_target_cost()
    _assert_adjacent_targeting()
    _assert_periodic_damage_source_and_expiry()
    _assert_control_skip_and_expiry()
    _assert_victory_and_invalid_actor()
    _assert_turn_start_victory_before_targeting()
    _assert_random_rollback_and_max_round_draw()
    _assert_speed_action_frequency()
    print("battle timeline test: OK")


def _context(trace_id: str, seed: int = 20260712) -> RuleContext:
    return RuleContext(
        trace_id=trace_id,
        rule_version="rules.v1",
        ruleset=Ruleset("ruleset.standard"),
        logical_time=datetime(2026, 7, 12, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        random=SeededRandomSource(seed),
    )


def _build_engine() -> tuple[BattleEngine, EffectEngine]:
    attributes = {
        "health.maximum": AttributeDefinition("health.maximum", default=100, minimum=1),
        "spirit.maximum": AttributeDefinition("spirit.maximum", default=30, minimum=0),
        "combat.attack": AttributeDefinition("combat.attack", default=10, minimum=0),
        "combat.speed": AttributeDefinition("combat.speed", default=0),
        "combat.defense.physical": AttributeDefinition("combat.defense.physical", default=0),
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
    damage = DamageEngine(
        {
            "damage.physical": DamageTypeDefinition(
                "damage.physical",
                defense_attribute="combat.defense.physical",
            ),
            "damage.poison": DamageTypeDefinition("damage.poison", ignores_defense=True),
        },
        resolver,
        resources,
        CombatStats(
            health_resource="health.current",
            shield_resource="shield.current",
        ),
    )
    handlers = EffectOperationHandlers.with_defaults()
    register_damage_operation(handlers, damage)

    effects = DefinitionRegistry[EffectDefinition]("Effect")
    effects.register(
        EffectDefinition(
            "effect.strike",
            operations=(
                DealDamage(
                    "operation.strike",
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
            "effect.poison.tick",
            operations=(
                DealDamage(
                    "operation.poison.tick",
                    "damage.poison",
                    ParameterMagnitude("dot.amount"),
                    can_miss=False,
                    can_critical=False,
                    can_block=False,
                ),
            ),
        )
    )
    effects.register(
        EffectDefinition(
            "effect.poison.state",
            tags=TagSet.of("effect.damage.periodic.poison"),
            operations=(GrantTrigger("operation.poison.state", "trigger.poison.tick"),),
            duration_turns=2,
            stacking=StackingPolicy.REFRESH,
            stack_by_source=True,
        )
    )
    effects.register(
        EffectDefinition(
            "effect.stunned",
            operations=(GrantTag("operation.stunned", Tag("state.control.stunned")),),
            duration_turns=1,
        )
    )
    effects.register(
        EffectDefinition(
            "effect.turn_start.self_destruct",
            operations=(
                DealDamage(
                    "operation.turn_start.self_destruct",
                    "damage.physical",
                    FixedMagnitude(100),
                    can_miss=False,
                    can_critical=False,
                    can_block=False,
                ),
            ),
        )
    )
    effects.register(
        EffectDefinition(
            "effect.turn_start.self_destruct_state",
            operations=(
                GrantTrigger(
                    "operation.turn_start.self_destruct_state",
                    "trigger.turn_start.self_destruct",
                ),
            ),
            duration_turns=None,
        )
    )
    effect_engine = EffectEngine(effects, resolver, resources, operations=handlers)

    triggers = DefinitionRegistry[TriggerDefinition]("Trigger")
    triggers.register(
        TriggerDefinition(
            "trigger.poison.tick",
            event_kind="combat.turn.started",
            effect_id="effect.poison.tick",
            owner=TriggerOwner.EVENT_TARGET,
            target=TriggerTarget.OWNER,
            source=TriggerSource.GRANT_SOURCE,
        )
    )
    triggers.register(
        TriggerDefinition(
            "trigger.turn_start.self_destruct",
            event_kind="combat.turn.started",
            effect_id="effect.turn_start.self_destruct",
            owner=TriggerOwner.ANY,
            target=TriggerTarget.OWNER,
            source=TriggerSource.OWNER,
            max_activations_per_execution=1,
        )
    )
    abilities = DefinitionRegistry[AbilityDefinition]("Ability")
    abilities.register(
        AbilityDefinition(
            "ability.strike",
            costs=(ResourceCost("spirit.current", FixedMagnitude(10)),),
            effects=(EffectReference("effect.strike"),),
        )
    )
    abilities.register(
        AbilityDefinition(
            "ability.whirlwind",
            costs=(ResourceCost("spirit.current", FixedMagnitude(10)),),
            effects=(EffectReference("effect.strike"),),
        )
    )
    abilities.register(
        AbilityDefinition(
            "ability.apply_poison",
            effects=(EffectReference("effect.poison.state"),),
        )
    )
    ability_engine = AbilityEngine(
        abilities,
        effect_engine,
        trigger_ids=frozenset(triggers.ids()),
    )
    executor = GameplayExecutor(ability_engine, TriggerEngine(triggers, effect_engine))
    return (
        BattleEngine(
            executor,
            BattleRules(
                health_resource="health.current",
                speed_attribute="combat.speed",
                maximum_rounds=10,
            ),
            {
                "ability.strike": BattleAbilityTargeting(
                    "ability.strike",
                    frozenset(
                        {
                            "target.enemy.explicit",
                            "target.enemy.first",
                            "target.enemy.random",
                        }
                    ),
                    maximum_targets=1,
                ),
                "ability.whirlwind": BattleAbilityTargeting(
                    "ability.whirlwind",
                    frozenset({"target.enemy.all", "target.enemy.adjacent"}),
                    maximum_targets=3,
                ),
                "ability.apply_poison": BattleAbilityTargeting(
                    "ability.apply_poison",
                    frozenset({"target.enemy.explicit"}),
                    maximum_targets=1,
                ),
            },
        ),
        effect_engine,
    )


def _entity(
    entity_id: str,
    *,
    health: float = 100,
    spirit: float = 30,
    attack: float = 10,
    speed: float = 0,
    abilities: tuple[str, ...] = (),
) -> RuleEntity:
    return RuleEntity(
        id=entity_id,
        base_attributes={
            "health.maximum": 100,
            "spirit.maximum": 30,
            "combat.attack": attack,
            "combat.speed": speed,
        },
        resources={
            "health.current": health,
            "spirit.current": spirit,
            "shield.current": 0,
        },
        base_tags=TagSet.of("entity.combatant"),
        base_abilities=frozenset(abilities),
    )


def _start(
    engine: BattleEngine,
    entities: dict[str, RuleEntity],
    teams: dict[str, str],
    slots: dict[str, int],
    trace_id: str,
):
    participants = tuple(
        BattleParticipant(entity_id, teams[entity_id], slots[entity_id])
        for entity_id in entities
    )
    outcome = engine.start(
        trace_id,
        participants=participants,
        entities=entities,
        context=_context(f"{trace_id}.start"),
    )
    assert outcome.ok and outcome.value
    return outcome.value.state


def _assert_target_registry_and_multi_target_cost() -> None:
    engine, _effects = _build_engine()
    entities = {
        "hero": _entity(
            "hero",
            attack=30,
            speed=20,
            abilities=("ability.whirlwind",),
        ),
        "enemy-a": _entity("enemy-a", speed=10),
        "enemy-b": _entity("enemy-b", speed=5),
    }
    state = _start(
        engine,
        entities,
        {"hero": "team.hero", "enemy-a": "team.enemy", "enemy-b": "team.enemy"},
        {"hero": 0, "enemy-a": 0, "enemy-b": 1},
        "battle.multi",
    )
    assert state.turn_order == ("hero", "enemy-a", "enemy-b")
    forbidden = engine.execute_turn(
        state,
        BattleAction(
            "action.forbidden",
            "hero",
            "ability.whirlwind",
            TargetRequest("target.enemy.explicit", ("enemy-a",)),
        ),
        context=_context("battle.multi.forbidden"),
    )
    assert forbidden.failure and forbidden.failure.code == "battle.target_selector_forbidden"
    assert state.entity("hero").resources["spirit.current"] == 30
    outcome = engine.execute_turn(
        state,
        BattleAction(
            "action.whirlwind",
            "hero",
            "ability.whirlwind",
            TargetRequest("target.enemy.all"),
        ),
        context=_context("battle.multi.turn1"),
    )
    assert outcome.ok and outcome.value
    state = outcome.value.state
    assert state.entity("hero").resources["spirit.current"] == 20
    assert state.entity("enemy-a").resources["health.current"] == 70
    assert state.entity("enemy-b").resources["health.current"] == 70
    damage_events = [
        event for event in outcome.value.events if event.kind == "combat.damage.dealt"
    ]
    assert [event.target_id for event in damage_events] == ["enemy-a", "enemy-b"]
    cost_events = [
        event
        for event in outcome.value.events
        if event.kind == "resource.changed" and event.subject_id == "spirit.current"
    ]
    assert len(cost_events) == 1


def _assert_periodic_damage_source_and_expiry() -> None:
    engine, _effects = _build_engine()
    entities = {
        "poisoner": _entity(
            "poisoner",
            speed=20,
            abilities=("ability.apply_poison",),
        ),
        "victim": _entity("victim", speed=10),
        "ally": _entity("ally", speed=5),
    }
    state = _start(
        engine,
        entities,
        {
            "poisoner": "team.hero",
            "ally": "team.hero",
            "victim": "team.enemy",
        },
        {"poisoner": 0, "ally": 1, "victim": 0},
        "battle.poison",
    )
    applied = engine.execute_turn(
        state,
        BattleAction(
            "action.poison",
            "poisoner",
            "ability.apply_poison",
            TargetRequest("target.enemy.explicit", ("victim",)),
            parameters={"dot.amount": 15},
        ),
        context=_context("battle.poison.apply"),
    )
    assert applied.ok and applied.value
    state = applied.value.state
    withdrawn = engine.withdraw(
        state,
        "poisoner",
        context=_context("battle.poison.source_left"),
        reason="fled",
    )
    assert withdrawn.ok and withdrawn.value
    state = withdrawn.value.state
    assert "poisoner" in state.entities
    assert "poisoner" in state.inactive_ids
    first_tick = engine.execute_turn(
        state,
        None,
        context=_context("battle.poison.tick1"),
    )
    assert first_tick.ok and first_tick.value
    state = first_tick.value.state
    assert state.entity("victim").resources["health.current"] == 85
    damage = next(
        event for event in first_tick.value.events if event.kind == "combat.damage.dealt"
    )
    assert damage.source_id == "poisoner"
    assert damage.target_id == "victim"

    poisoner_pass = engine.execute_turn(
        state,
        None,
        context=_context("battle.poison.round2.poisoner"),
    )
    assert poisoner_pass.ok and poisoner_pass.value
    second_tick = engine.execute_turn(
        poisoner_pass.value.state,
        None,
        context=_context("battle.poison.tick2"),
    )
    assert second_tick.ok and second_tick.value
    victim = second_tick.value.state.entity("victim")
    assert victim.resources["health.current"] == 70
    assert not victim.active_effects
    assert "effect.expired" in [event.kind for event in second_tick.value.events]


def _assert_adjacent_targeting() -> None:
    engine, _effects = _build_engine()
    entities = {
        "hero": _entity(
            "hero",
            attack=20,
            speed=20,
            abilities=("ability.whirlwind",),
        ),
        "enemy-a": _entity("enemy-a", speed=10),
        "enemy-b": _entity("enemy-b", speed=5),
        "enemy-c": _entity("enemy-c", speed=1),
    }
    state = _start(
        engine,
        entities,
        {
            "hero": "team.hero",
            "enemy-a": "team.enemy",
            "enemy-b": "team.enemy",
            "enemy-c": "team.enemy",
        },
        {"hero": 0, "enemy-a": 0, "enemy-b": 1, "enemy-c": 2},
        "battle.adjacent",
    )
    outcome = engine.execute_turn(
        state,
        BattleAction(
            "action.adjacent",
            "hero",
            "ability.whirlwind",
            TargetRequest("target.enemy.adjacent", ("enemy-a",)),
        ),
        context=_context("battle.adjacent.turn"),
    )
    assert outcome.ok and outcome.value
    state = outcome.value.state
    assert state.entity("enemy-a").resources["health.current"] == 80
    assert state.entity("enemy-b").resources["health.current"] == 80
    assert state.entity("enemy-c").resources["health.current"] == 100


def _assert_control_skip_and_expiry() -> None:
    engine, effects = _build_engine()
    hero = _entity("hero", speed=20)
    enemy = _entity("enemy", attack=50, speed=10, abilities=("ability.strike",))
    enemy = effects.apply(
        EffectSpec("stun-state", "effect.stunned", hero.id),
        source=hero,
        target=enemy,
        context=_context("battle.stun.apply"),
    ).target
    state = _start(
        engine,
        {"hero": hero, "enemy": enemy},
        {"hero": "team.hero", "enemy": "team.enemy"},
        {"hero": 0, "enemy": 0},
        "battle.stun",
    )
    hero_pass = engine.execute_turn(
        state,
        None,
        context=_context("battle.stun.hero"),
    )
    assert hero_pass.ok and hero_pass.value
    skipped = engine.execute_turn(
        hero_pass.value.state,
        BattleAction(
            "action.blocked",
            "enemy",
            "ability.strike",
            TargetRequest("target.enemy.explicit", ("hero",)),
        ),
        context=_context("battle.stun.enemy"),
    )
    assert skipped.ok and skipped.value
    assert skipped.value.state.entity("hero").resources["health.current"] == 100
    assert not skipped.value.state.entity("enemy").active_effects
    skipped_event = next(
        event for event in skipped.value.events if event.kind == "combat.turn.skipped"
    )
    assert skipped_event.values["reason"] == "incapacitated"


def _assert_victory_and_invalid_actor() -> None:
    engine, _effects = _build_engine()
    entities = {
        "hero": _entity(
            "hero",
            attack=50,
            speed=20,
            abilities=("ability.whirlwind",),
        ),
        "enemy-a": _entity("enemy-a", health=20, speed=10),
        "enemy-b": _entity("enemy-b", health=20, speed=5),
    }
    state = _start(
        engine,
        entities,
        {"hero": "team.hero", "enemy-a": "team.enemy", "enemy-b": "team.enemy"},
        {"hero": 0, "enemy-a": 0, "enemy-b": 1},
        "battle.victory",
    )
    invalid = engine.execute_turn(
        state,
        BattleAction(
            "action.invalid",
            "enemy-a",
            "ability.whirlwind",
            TargetRequest("target.enemy.all"),
        ),
        context=_context("battle.victory.invalid"),
    )
    assert invalid.failure and invalid.failure.code == "battle.not_current_actor"
    assert state.entity("enemy-a").resources["health.current"] == 20

    victory = engine.execute_turn(
        state,
        BattleAction(
            "action.finish",
            "hero",
            "ability.whirlwind",
            TargetRequest("target.enemy.all"),
        ),
        context=_context("battle.victory.finish"),
    )
    assert victory.ok and victory.value
    assert victory.value.state.status is BattleStatus.FINISHED
    assert victory.value.state.winning_teams == ("team.hero",)
    finished = next(
        event for event in victory.value.events if event.kind == "combat.battle.finished"
    )
    assert finished.values["winning_teams"] == ("team.hero",)


def _assert_turn_start_victory_before_targeting() -> None:
    engine, effects = _build_engine()
    hero = _entity(
        "hero",
        speed=20,
        abilities=("ability.strike",),
    )
    enemy = _entity("enemy", health=20, speed=10)
    enemy = effects.apply(
        EffectSpec(
            "turn-start-self-destruct",
            "effect.turn_start.self_destruct_state",
            enemy.id,
        ),
        source=enemy,
        target=enemy,
        context=_context("battle.turn_start_finish.apply"),
    ).target
    state = _start(
        engine,
        {"hero": hero, "enemy": enemy},
        {"hero": "team.hero", "enemy": "team.enemy"},
        {"hero": 0, "enemy": 0},
        "battle.turn_start_finish",
    )
    outcome = engine.execute_turn(
        state,
        BattleAction(
            "action.never_executed",
            "hero",
            "ability.strike",
            TargetRequest("target.enemy.first"),
        ),
        context=_context("battle.turn_start_finish.turn"),
    )
    assert outcome.ok and outcome.value
    assert outcome.value.state.status is BattleStatus.FINISHED
    assert outcome.value.state.winning_teams == ("team.hero",)
    assert outcome.value.resolved_target_ids == ()
    assert not any(event.kind == "ability.started" for event in outcome.value.events)
    finished = next(
        event for event in outcome.value.events if event.kind == "combat.battle.finished"
    )
    assert finished.values["reason"] == "turn_start_effect"


def _assert_random_rollback_and_max_round_draw() -> None:
    engine, _effects = _build_engine()
    entities = {
        "hero": _entity("hero", speed=20),
        "enemy": _entity("enemy", speed=10),
    }
    teams = {"hero": "team.hero", "enemy": "team.enemy"}
    slots = {"hero": 0, "enemy": 0}
    state = _start(engine, entities, teams, slots, "battle.rollback")
    context = _context("battle.rollback.failure", seed=99)
    checkpoint = context.random.checkpoint()
    failed = engine.execute_turn(
        state,
        BattleAction(
            "action.random.failure",
            "hero",
            "ability.strike",
            TargetRequest("target.enemy.random"),
        ),
        context=context,
    )
    assert failed.failure and failed.failure.code == "ability.not_owned"
    assert context.random.checkpoint() == checkpoint

    draw_engine = BattleEngine(
        engine.executor,
        BattleRules(
            health_resource="health.current",
            speed_attribute="combat.speed",
            maximum_rounds=1,
        ),
        engine.ability_targeting,
    )
    draw_state = _start(draw_engine, entities, teams, slots, "battle.draw")
    first = draw_engine.execute_turn(
        draw_state,
        None,
        context=_context("battle.draw.hero"),
    )
    assert first.ok and first.value
    second = draw_engine.execute_turn(
        first.value.state,
        None,
        context=_context("battle.draw.enemy"),
    )
    assert second.ok and second.value
    assert second.value.state.status is BattleStatus.DRAW
    finished = next(
        event for event in second.value.events if event.kind == "combat.battle.finished"
    )
    assert finished.values["reason"] == "maximum_rounds"


def _assert_speed_action_frequency() -> None:
    engine, _effects = _build_engine()
    assert abs(engine.rules.action_efficiency(50) - 2 / 3) < 1e-9
    assert abs(engine.rules.action_efficiency(100) - 1) < 1e-9
    assert abs(engine.rules.action_efficiency(200) - 4 / 3) < 1e-9

    entities = {
        "fast": _entity("fast", speed=200),
        "normal": _entity("normal", speed=100),
        "slow": _entity("slow", speed=50),
    }
    state = _start(
        engine,
        entities,
        {"fast": "team.fast", "normal": "team.normal", "slow": "team.slow"},
        {"fast": 0, "normal": 0, "slow": 0},
        "battle.speed_frequency",
    )
    # 开场每人保留一次行动，避免慢速角色出生时长时间空等。
    assert state.turn_order == ("fast", "normal", "slow")
    for index in range(3):
        outcome = engine.execute_turn(
            state,
            None,
            context=_context(f"battle.speed_frequency.initial.{index}"),
        )
        assert outcome.ok and outcome.value
        state = outcome.value.state

    actors: list[str] = []
    for index in range(9):
        actor_id = state.current_actor_id
        assert actor_id is not None
        actors.append(actor_id)
        outcome = engine.execute_turn(
            state,
            None,
            context=_context(f"battle.speed_frequency.timeline.{index}"),
        )
        assert outcome.ok and outcome.value
        state = outcome.value.state

    assert actors.count("fast") == 4
    assert actors.count("normal") == 3
    assert actors.count("slow") == 2


if __name__ == "__main__":
    main()
