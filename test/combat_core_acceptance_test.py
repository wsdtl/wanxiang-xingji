"""正式战斗内容、自动决策与核心轨迹的封板验收。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.content import assemble_official_catalog  # noqa: E402
from game.content.catalog.combat import BASIC_ATTACK_ABILITY_ID  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    ActiveEffect,
    AbilityUse,
    BattleAction,
    BattleAiRule,
    BattleEngine,
    BattleParticipant,
    BattleRules,
    BattleSession,
    BattleStatus,
    BattleTransitionKind,
    COMBAT_SPEED,
    DamageRequest,
    GameplayExecutor,
    HEALTH_CURRENT,
    RuleContext,
    RuleEntity,
    RuleEvent,
    Ruleset,
    SeededRandomSource,
    TargetRequest,
)


TIME = datetime(2026, 7, 19, tzinfo=timezone.utc)


def main() -> None:
    catalog = assemble_official_catalog()
    _assert_all_abilities_and_effects(catalog)
    _assert_all_triggers(catalog)
    _assert_formal_interceptors(catalog)
    _assert_formal_target_constraints(catalog)
    _assert_trace_is_core_owned(catalog)
    _assert_session_join_and_withdraw(catalog)
    _assert_all_weapon_auto_battles(catalog)
    _assert_weapon_equipment_combinations(catalog)
    _assert_all_enemy_ai_rules(catalog)
    print("combat core acceptance tests passed")


def _assert_all_abilities_and_effects(catalog) -> None:
    executor = GameplayExecutor(catalog.ability_engine, catalog.trigger_engine)
    referenced_effects = {
        str(reference.effect_id)
        for ability in catalog.abilities
        for reference in ability.effects
    }
    referenced_effects.update(str(trigger.effect_id) for trigger in catalog.triggers)
    assert referenced_effects == set(map(str, catalog.effects.ids()))
    assert referenced_effects
    for index, ability_id in enumerate(catalog.abilities.ids()):
        actor = _entity("actor", abilities=(ability_id,), health=1_000)
        target = _entity("target", health=1_000)
        outcome = executor.execute_ability(
            AbilityUse(f"ability-acceptance-{index}", ability_id),
            actor=actor,
            target=target,
            context=_context(f"ability:{ability_id}", 1_000 + index),
        )
        assert outcome.ok and outcome.value is not None, (ability_id, outcome.failure)
        _assert_entity_resource_events(
            {actor.id: actor, target.id: target},
            {
                outcome.value.actor.id: outcome.value.actor,
                outcome.value.target.id: outcome.value.target,
            },
            outcome.value.events,
        )
        started = tuple(
            event
            for event in outcome.value.events
            if event.kind == "ability.started" and event.subject_id == ability_id
        )
        completed = tuple(
            event
            for event in outcome.value.events
            if event.kind == "ability.completed" and event.subject_id == ability_id
        )
        assert len(started) == len(completed) == 1


def _assert_all_triggers(catalog) -> None:
    assert catalog.triggers.ids()
    for index, trigger_id in enumerate(catalog.triggers.ids()):
        definition = catalog.triggers.require(trigger_id)
        owner_id = "target" if definition.owner.value == "event_target" else "actor"
        activated = None
        for seed in range(512):
            actor = _trigger_entity(
                "actor",
                trigger_id if owner_id == "actor" else None,
            )
            target = _trigger_entity(
                "target",
                trigger_id if owner_id == "target" else None,
            )
            context = _context(f"trigger:{trigger_id}:{seed}", 30_000 + seed)
            event = RuleEvent.from_context(
                context,
                kind=definition.event_kind,
                source_id="actor",
                target_id="target",
                subject_id="combat.acceptance",
                values={
                    "damage_type": "damage.physical",
                    "is_proc": 0.0,
                    "effective_damage": 100.0,
                    "health_damage": 100.0,
                    "shield_damage": 100.0,
                    "actual": 100.0,
                    "raw": 100.0,
                    "delta": -100.0,
                    "current": 500.0,
                },
            )
            result = catalog.trigger_engine.process(
                (event,),
                entities={"actor": actor, "target": target},
                context=context,
            )
            if any(
                value.kind == "trigger.activated" and value.subject_id == trigger_id
                for value in result.events
            ):
                activated = (actor, target, result)
                break
        assert activated is not None, trigger_id
        actor, target, result = activated
        _assert_entity_resource_events(
            {"actor": actor, "target": target},
            result.entities,
            result.events,
        )


def _assert_formal_interceptors(catalog) -> None:
    assert set(map(str, catalog.interceptors.ids())) == {
        "interceptor.weapon.damage_cap",
        "interceptor.weapon.death_guard",
        "interceptor.weapon.immunity",
    }
    results = {}
    for index, interceptor_id in enumerate(catalog.interceptors.ids()):
        target = _entity(
            "target",
            health=100,
            active_effects=(
                ActiveEffect(
                    f"effect-instance-{index}",
                    "effect.test.interceptor",
                    "target",
                    granted_interceptors=frozenset({interceptor_id}),
                ),
            ),
        )
        results[str(interceptor_id)] = catalog.damage_engine.resolve(
            DamageRequest(
                f"damage-interceptor-{index}",
                "damage.physical",
                500,
                can_miss=False,
                can_critical=False,
                can_block=False,
            ),
            source=_entity("source"),
            target=target,
            context=_context(f"interceptor:{interceptor_id}", 40_000 + index),
        )
    assert results["interceptor.weapon.damage_cap"].breakdown.limited == 80
    assert results["interceptor.weapon.death_guard"].health_after == 1
    immunity = results["interceptor.weapon.immunity"]
    assert immunity.health_damage == 0
    assert immunity.health_after == 100
    assert immunity.breakdown.limited == 0
    assert immunity.interceptions[0].after.prevented


def _assert_formal_target_constraints(catalog) -> None:
    assert set(map(str, catalog.target_constraints.ids())) == {
        "target_constraint.weapon.taunt",
        "target_constraint.weapon.untargetable",
    }
    engine = _engine(catalog)
    taunted = _entity(
        "actor",
        abilities=(BASIC_ATTACK_ABILITY_ID,),
        speed=200,
        active_effects=(
            ActiveEffect(
                "effect-instance-taunt",
                "effect.test.taunt",
                "enemy-a",
                granted_target_constraints=frozenset({"target_constraint.weapon.taunt"}),
                remaining_turns=2,
            ),
        ),
    )
    opened = BattleSession.start(
        engine,
        "battle-constraint-taunt",
        participants=(
            BattleParticipant("actor", "team.player", 0),
            BattleParticipant("enemy-a", "team.enemy", 0),
            BattleParticipant("enemy-b", "team.enemy", 1),
        ),
        entities={
            "actor": taunted,
            "enemy-a": _entity("enemy-a", speed=100),
            "enemy-b": _entity("enemy-b", speed=90),
        },
        context=_context("constraint-taunt-start", 50_000),
    )
    assert opened.ok and opened.value is not None
    session = opened.value
    wrong = session.execute_turn(
        BattleAction(
            "action-ignore-taunt",
            "actor",
            BASIC_ATTACK_ABILITY_ID,
            TargetRequest("target.enemy.explicit", ("enemy-b",)),
        ),
        context=_context("constraint-taunt-wrong", 50_001),
    )
    assert wrong.failure and wrong.failure.code == "target.no_valid_target"
    correct = session.execute_turn(
        BattleAction(
            "action-follow-taunt",
            "actor",
            BASIC_ATTACK_ABILITY_ID,
            TargetRequest("target.enemy.explicit", ("enemy-a",)),
        ),
        context=_context("constraint-taunt-correct", 50_002),
    )
    assert correct.ok

    hidden = _entity(
        "hidden",
        active_effects=(
            ActiveEffect(
                "effect-instance-hidden",
                "effect.test.hidden",
                "hidden",
                granted_target_constraints=frozenset(
                    {"target_constraint.weapon.untargetable"}
                ),
                remaining_turns=2,
            ),
        ),
    )
    hidden_opened = BattleSession.start(
        engine,
        "battle-constraint-hidden",
        participants=(
            BattleParticipant("viewer", "team.player", 0),
            BattleParticipant("hidden", "team.enemy", 0),
        ),
        entities={
            "viewer": _entity(
                "viewer",
                abilities=(BASIC_ATTACK_ABILITY_ID,),
                speed=200,
            ),
            "hidden": hidden,
        },
        context=_context("constraint-hidden-start", 50_003),
    )
    assert hidden_opened.ok and hidden_opened.value is not None
    blocked = hidden_opened.value.execute_turn(
        BattleAction(
            "action-target-hidden",
            "viewer",
            BASIC_ATTACK_ABILITY_ID,
            TargetRequest("target.enemy.explicit", ("hidden",)),
        ),
        context=_context("constraint-hidden-blocked", 50_004),
    )
    assert blocked.failure and blocked.failure.code == "target.no_valid_target"


def _assert_trace_is_core_owned(catalog) -> None:
    engine = _engine(catalog)
    ability_id = "ability.weapon.cinder_lash"
    entities = {
        "player": _entity("player", abilities=(ability_id,), speed=200),
        "enemy-a": _entity("enemy-a", speed=100),
        "enemy-b": _entity("enemy-b", speed=90),
    }
    opened = BattleSession.start(
        engine,
        "battle-trace-acceptance",
        participants=(
            BattleParticipant("player", "team.player", 0),
            BattleParticipant("enemy-a", "team.enemy", 0),
            BattleParticipant("enemy-b", "team.enemy", 1),
        ),
        entities=entities,
        context=_context("battle-trace-start", 2),
    )
    assert opened.ok and opened.value is not None
    session = opened.value
    initial_trace = session.trace
    assert len(initial_trace.transitions) == 1
    assert initial_trace.transitions[0].kind is BattleTransitionKind.START

    targeting = catalog.battle_ability_targeting[ability_id]
    rule = BattleAiRule(
        "ai.acceptance.cinder_lash",
        ability_id,
        "target.enemy.adjacent",
        priority=10,
        maximum_targets=targeting.maximum_targets,
    )
    action = catalog.battle_ai_engine.decide(
        (rule,),
        session.state,
        "player",
        context=_context("battle-trace-decision", 3),
    )
    assert action is not None
    assert action.decision_rule_id == rule.id
    assert action.targets.explicit_ids == ("enemy-a",)
    turn = session.execute_turn(
        action,
        context=_context("battle-trace-turn", 4),
    )
    assert turn.ok and turn.value is not None
    assert turn.value.kind is BattleTransitionKind.TURN
    assert turn.value.before is not None
    assert turn.value.before.state == initial_trace.final_frame.state
    assert turn.value.after.state == session.state
    assert turn.value.resolved_target_ids == ("enemy-a", "enemy-b")
    _assert_resource_events(turn.value.before.state, turn.value.after.state, turn.value.events)

    actor_id = session.state.current_actor_id
    assert actor_id is not None
    updated = replace(
        session.state.entities[actor_id],
        cooldowns={"ability.basic_attack": 2},
    )
    phase_event = RuleEvent.from_context(
        _context("battle-trace-phase", 5),
        kind="combat.phase.activated",
        source_id=actor_id,
        target_id=actor_id,
        subject_id="combat.phase.acceptance",
        values={"threshold": 0.5},
    )
    external = session.apply_external(
        {actor_id: updated},
        (phase_event,),
        subject_id="battle.transition.acceptance_phase",
        context=_context("battle-trace-phase", 5),
    )
    assert external.ok and external.value is not None
    assert external.value.kind is BattleTransitionKind.EXTERNAL
    assert session.state.entities[actor_id].cooldowns["ability.basic_attack"] == 2

    transitions_before_failure = session.trace.transitions
    wrong_actor = next(value for value in session.state.entities if value != actor_id)
    failed = session.execute_turn(
        BattleAction(
            "action-wrong-actor",
            wrong_actor,
            BASIC_ATTACK_ABILITY_ID,
            catalog.target_selectors.automatic_request(
                "target.enemy.first",
                _targeting_context(catalog, session.state, wrong_actor, 6),
            ),
        ),
        context=_context("battle-trace-failed", 6),
    )
    assert failed.failure and failed.failure.code == "battle.not_current_actor"
    assert session.trace.transitions == transitions_before_failure
    assert session.trace.final_frame.state == session.state
    assert len(session.trace.turn_frames) == 1
    assert session.trace.events


def _assert_session_join_and_withdraw(catalog) -> None:
    opened = BattleSession.start(
        _engine(catalog),
        "battle-session-participants",
        participants=(
            BattleParticipant("hero", "team.hero", 0),
            BattleParticipant("enemy", "team.enemy", 0),
        ),
        entities={
            "hero": _entity("hero", abilities=(BASIC_ATTACK_ABILITY_ID,), speed=200),
            "enemy": _entity("enemy", abilities=(BASIC_ATTACK_ABILITY_ID,), speed=100),
        },
        context=_context("session-participants-start", 7),
    )
    assert opened.ok and opened.value is not None
    session = opened.value
    joined = session.join(
        BattleParticipant("summon", "team.hero", 1),
        _entity("summon", abilities=(BASIC_ATTACK_ABILITY_ID,), speed=90),
        context=_context("session-participants-join", 8),
    )
    assert joined.ok and joined.value is not None
    assert joined.value.kind is BattleTransitionKind.JOIN
    assert "summon" in session.state.entities
    left = session.withdraw(
        "summon",
        context=_context("session-participants-summon-left", 9),
    )
    assert left.ok and left.value is not None
    assert left.value.kind is BattleTransitionKind.WITHDRAW
    assert "summon" in session.state.inactive_ids
    finished = session.withdraw(
        "enemy",
        context=_context("session-participants-enemy-left", 10),
    )
    assert finished.ok and finished.value is not None
    assert session.state.status is BattleStatus.FINISHED
    assert session.state.winning_teams == ("team.hero",)
    assert tuple(value.kind for value in session.trace.transitions) == (
        BattleTransitionKind.START,
        BattleTransitionKind.JOIN,
        BattleTransitionKind.WITHDRAW,
        BattleTransitionKind.WITHDRAW,
    )


def _assert_all_weapon_auto_battles(catalog) -> None:
    weapon_ids = tuple(
        str(value)
        for value in catalog.abilities.ids()
        if str(value).startswith("ability.weapon.")
    )
    assert weapon_ids
    engine = _engine(catalog, maximum_rounds=60, maximum_turns=600)
    for index, ability_id in enumerate(weapon_ids):
        context = _context(f"weapon-auto:{ability_id}", 10_000 + index)
        opened = BattleSession.start(
            engine,
            f"battle-weapon-auto-{index}",
            participants=(
                BattleParticipant("player", "team.player", 0),
                BattleParticipant("enemy", "team.enemy", 0),
            ),
            entities={
                "player": _entity(
                    "player",
                    abilities=(ability_id, BASIC_ATTACK_ABILITY_ID),
                    speed=110,
                ),
                "enemy": _entity(
                    "enemy",
                    abilities=(BASIC_ATTACK_ABILITY_ID,),
                    speed=100,
                ),
            },
            context=context,
        )
        assert opened.ok and opened.value is not None, ability_id
        session = opened.value
        rules = {
            "player": (
                _ai_rule(catalog, "player.weapon", ability_id, 10),
                _ai_rule(catalog, "player.basic", BASIC_ATTACK_ABILITY_ID, 0),
            ),
            "enemy": (_ai_rule(catalog, "enemy.basic", BASIC_ATTACK_ABILITY_ID, 0),),
        }
        used: set[str] = set()
        while session.state.status is BattleStatus.ACTIVE:
            actor_id = session.state.current_actor_id
            assert actor_id is not None
            action = catalog.battle_ai_engine.decide(
                rules[actor_id],
                session.state,
                actor_id,
                context=context,
            )
            assert action is not None, (ability_id, actor_id)
            outcome = session.execute_turn(action, context=context)
            assert outcome.ok and outcome.value is not None, (
                ability_id,
                outcome.failure,
            )
            assert outcome.value.before is not None
            _assert_resource_events(
                outcome.value.before.state,
                outcome.value.after.state,
                outcome.value.events,
            )
            used.add(str(action.ability_id))
        assert ability_id in used
        assert session.trace.final_frame.state.status is not BattleStatus.ACTIVE
        assert len(session.trace.turn_transitions) == session.state.turn_number
        event_rounds = {
            int(event.values["round"])
            for event in session.trace.events
            if event.kind == "combat.round.started"
        }
        frame_rounds = {
            frame.state.round_number for frame in session.trace.round_frames
        }
        assert frame_rounds == event_rounds


def _assert_all_enemy_ai_rules(catalog) -> None:
    engine = _engine(catalog)
    covered = set()
    for index, behavior in enumerate(catalog.enemies.behaviors):
        ability_id = next(iter(behavior.contribution.abilities))
        opened = BattleSession.start(
            engine,
            f"battle-enemy-ai-{index}",
            participants=(
                BattleParticipant("enemy", "team.enemy", 0),
                BattleParticipant("player", "team.player", 0),
            ),
            entities={
                "enemy": _entity("enemy", abilities=(ability_id,), speed=200),
                "player": _entity(
                    "player",
                    abilities=(BASIC_ATTACK_ABILITY_ID,),
                    speed=100,
                ),
            },
            context=_context(f"enemy-ai:{behavior.id}", 20_000 + index),
        )
        assert opened.ok and opened.value is not None
        session = opened.value
        action = catalog.battle_ai_engine.decide(
            behavior.ai_rules,
            session.state,
            "enemy",
            context=_context(f"enemy-ai:{behavior.id}", 20_000 + index),
        )
        assert action is not None, behavior.id
        outcome = session.execute_turn(
            action,
            context=_context(f"enemy-ai:{behavior.id}", 20_000 + index),
        )
        assert outcome.ok and outcome.value is not None, (
            behavior.id,
            outcome.failure,
        )
        covered.add(behavior.id)
    assert covered == set(catalog.enemies.behaviors.ids())


def _assert_weapon_equipment_combinations(catalog) -> None:
    weapon_ids = tuple(
        str(value)
        for value in catalog.abilities.ids()
        if str(value).startswith("ability.weapon.")
    )
    trigger_ids = tuple(
        str(value)
        for value in catalog.triggers.ids()
        if str(value).startswith("trigger.equipment.")
    )
    behaviors = tuple(catalog.enemies.behaviors)
    assert weapon_ids
    assert trigger_ids
    assert behaviors
    covered_triggers: set[str] = set()
    engine = _engine(catalog, maximum_rounds=60, maximum_turns=600)

    for weapon_index, ability_id in enumerate(weapon_ids):
        for loadout_index in range(3):
            scenario = weapon_index * 3 + loadout_index
            selected_triggers = tuple(
                trigger_ids[(scenario * 7 + offset * 13) % len(trigger_ids)]
                for offset in range(6)
            )
            covered_triggers.update(selected_triggers)
            effects = tuple(
                ActiveEffect(
                    f"combination:{scenario}:{index}",
                    "effect.test.equipment_combination",
                    "player",
                    granted_triggers=frozenset({trigger_id}),
                )
                for index, trigger_id in enumerate(selected_triggers)
            )
            behavior = behaviors[scenario % len(behaviors)]
            enemy_ability = str(next(iter(behavior.contribution.abilities)))
            context = _context(f"combination:{scenario}", 40_000 + scenario)
            opened = BattleSession.start(
                engine,
                f"battle-combination-{scenario}",
                participants=(
                    BattleParticipant("player", "team.player", 0),
                    BattleParticipant("enemy", "team.enemy", 0),
                ),
                entities={
                    "player": _entity(
                        "player",
                        abilities=(ability_id, BASIC_ATTACK_ABILITY_ID),
                        speed=110,
                        active_effects=effects,
                    ),
                    "enemy": _entity(
                        "enemy",
                        abilities=(enemy_ability, BASIC_ATTACK_ABILITY_ID),
                        speed=100,
                    ),
                },
                context=context,
            )
            assert opened.ok and opened.value is not None, (
                ability_id,
                selected_triggers,
                opened.failure,
            )
            session = opened.value
            rules = {
                "player": (
                    _ai_rule(catalog, "combination.player", ability_id, 10),
                    _ai_rule(catalog, "combination.player.basic", BASIC_ATTACK_ABILITY_ID, 0),
                ),
                "enemy": (
                    _ai_rule(catalog, "combination.enemy", enemy_ability, 10),
                    _ai_rule(catalog, "combination.enemy.basic", BASIC_ATTACK_ABILITY_ID, 0),
                ),
            }
            while session.state.status is BattleStatus.ACTIVE:
                actor_id = session.state.current_actor_id
                assert actor_id is not None
                action = catalog.battle_ai_engine.decide(
                    rules[actor_id],
                    session.state,
                    actor_id,
                    context=context,
                )
                assert action is not None, (
                    ability_id,
                    selected_triggers,
                    actor_id,
                )
                outcome = session.execute_turn(action, context=context)
                assert outcome.ok and outcome.value is not None, (
                    ability_id,
                    selected_triggers,
                    enemy_ability,
                    outcome.failure,
                )
                assert outcome.value.before is not None
                _assert_resource_events(
                    outcome.value.before.state,
                    outcome.value.after.state,
                    outcome.value.events,
                )
            assert session.trace.final_frame.state.status is not BattleStatus.ACTIVE

    assert covered_triggers == set(trigger_ids)


def _engine(catalog, *, maximum_rounds: int = 20, maximum_turns: int = 200):
    return BattleEngine(
        GameplayExecutor(catalog.ability_engine, catalog.trigger_engine),
        BattleRules(
            HEALTH_CURRENT,
            COMBAT_SPEED,
            maximum_rounds=maximum_rounds,
            maximum_turns=maximum_turns,
        ),
        catalog.battle_ability_targeting,
        catalog.target_selectors,
    )


def _entity(
    entity_id: str,
    *,
    abilities: tuple[str, ...] = (),
    speed: float = 100,
    health: float = 5_000,
    active_effects=(),
) -> RuleEntity:
    return RuleEntity(
        entity_id,
        base_attributes={
            "health.maximum": 5_000,
            "spirit.maximum": 2_000,
            "combat.attack": 500,
            "combat.defense.physical": 100,
            "combat.speed": speed,
            "combat.accuracy": 0.95,
            "combat.evasion": 0.05,
            "combat.critical.chance": 0.2,
            "combat.critical.damage": 0.5,
            "combat.block.chance": 0.1,
            "combat.block.reduction": 0.3,
        },
        resources={
            "health.current": health,
            "spirit.current": 2_000,
            "combat.shield.current": 0,
        },
        base_abilities=frozenset(abilities),
        active_effects=tuple(active_effects),
    )


def _trigger_entity(entity_id: str, trigger_id: str | None) -> RuleEntity:
    active_effects = ()
    if trigger_id is not None:
        active_effects = (
            ActiveEffect(
                f"effect-trigger-grant-{entity_id}",
                "effect.test.trigger_grant",
                entity_id,
                granted_triggers=frozenset({trigger_id}),
            ),
        )
    return replace(
        _entity(entity_id, health=500, active_effects=active_effects),
        cooldowns={BASIC_ATTACK_ABILITY_ID: 3},
    )


def _ai_rule(catalog, prefix: str, ability_id: str, priority: int) -> BattleAiRule:
    targeting = catalog.battle_ability_targeting[ability_id]
    selectors = tuple(sorted(targeting.allowed_selectors))
    selector = "target.enemy.first" if "target.enemy.first" in selectors else selectors[0]
    suffix = ability_id.removeprefix("ability.").replace("_", ".")
    return BattleAiRule(
        f"ai.{prefix}.{suffix}",
        ability_id,
        selector,
        priority=priority,
        maximum_targets=targeting.maximum_targets,
    )


def _assert_resource_events(before, after, events) -> None:
    _assert_entity_resource_events(before.entities, after.entities, events)


def _assert_entity_resource_events(before_entities, after_entities, events) -> None:
    emitted: dict[tuple[str, str], float] = {}
    for event in events:
        if event.kind != "resource.changed":
            continue
        key = (event.target_id, str(event.subject_id))
        emitted[key] = emitted.get(key, 0.0) + float(event.values.get("delta", 0))
    for entity_id, old in before_entities.items():
        new = after_entities[entity_id]
        for resource_id in set(old.resources) | set(new.resources):
            delta = float(new.resources.get(resource_id, 0)) - float(
                old.resources.get(resource_id, 0)
            )
            assert abs(delta - emitted.get((entity_id, str(resource_id)), 0.0)) < 1e-6


def _targeting_context(catalog, state, actor_id: str, seed: int):
    from game.core.gameplay import TargetingContext

    return TargetingContext(
        actor_id,
        state.entities,
        {key: value.team_id for key, value in state.participants.items()},
        {key: value.slot for key, value in state.participants.items()},
        catalog.enemy_projector.attributes,
        catalog.resources[HEALTH_CURRENT],
        SeededRandomSource(seed),
        state.inactive_ids,
    )


def _context(trace_id: str, seed: int) -> RuleContext:
    return RuleContext(
        trace_id,
        "rules.combat_acceptance.v1",
        Ruleset("ruleset.combat_acceptance"),
        TIME,
        SeededRandomSource(seed),
    )


if __name__ == "__main__":
    main()
