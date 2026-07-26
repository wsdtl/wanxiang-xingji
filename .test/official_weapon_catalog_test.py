"""正式武器目录、真实执行、战报承接和快速平衡巡检。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TEST_ROOT = ROOT / ".test"
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

from game.content.catalog.foundation import QUALITY_IDS  # noqa: E402
from game.content.catalog import STARTER_WEAPON_ID  # noqa: E402
from game.content.catalog.weapon.blueprints import WEAPON_BLUEPRINTS  # noqa: E402
from game.content.catalog.weapon.mechanics import (  # noqa: E402
    WEAPON_MARK_EFFECT_ID,
    WEAPON_MAXIMUM_LEVEL_TABLE,
    WEAPON_MECHANIC_CONTENT,
)
from game.content.official import assemble_official_catalog, select_world_skin  # noqa: E402
from game.content.world_skins import (  # noqa: E402
    CULTIVATION_SKIN_ID,
    MAGIC_SKIN_ID,
    STELLAR_RING_SKIN_ID,
)
from game.core.gameplay import (  # noqa: E402
    COMBAT_DEFENSE,
    HEALTH_CURRENT,
    AbilityUse,
    ActiveEffect,
    GameplayExecutor,
    RuleContext,
    RuleEntity,
    RuleEvent,
    Ruleset,
    SeededRandomSource,
)
from support.itemization_balance_audit import ItemizationBalanceAuditor  # noqa: E402
from support.weapon_balance_audit import WeaponBalanceAuditor  # noqa: E402
from game.content.catalog.combat.stats import SHIELD_CURRENT  # noqa: E402
from game.features.battle_report import present_battle_event  # noqa: E402
from game.rules import (  # noqa: E402
    WeaponGenerationRequest,
    WeaponInstanceGenerator,
)
from game.rules.battle_report import (  # noqa: E402
    KNOWN_BATTLE_EVENT_KINDS,
    BattleReportTerm,
    StoredBattleCombatant,
    StoredBattleEvent,
)


def main() -> None:
    catalog = assemble_official_catalog()
    executor = GameplayExecutor(catalog.ability_engine, catalog.trigger_engine)
    _assert_catalog_shape(catalog)
    _assert_instance_generation(catalog)
    _assert_all_active_abilities_execute(executor)
    _assert_all_weapon_triggers_execute(catalog)
    _assert_random_branch_is_real(executor)
    _assert_mark_and_detonation_cycle(executor)
    _assert_periodic_damage(executor, catalog)
    _assert_current_cooldown_delay(executor)
    _assert_borrowed_force_and_report_projection(executor, catalog)
    _assert_deferred_echo_and_report_projection(executor, catalog)
    _assert_fast_balance(catalog)
    print("official weapon catalog test passed")


def _assert_catalog_shape(catalog) -> None:
    assert len(WEAPON_BLUEPRINTS) == 74
    assert len(WEAPON_MECHANIC_CONTENT.items) == 74
    assert len(WEAPON_MECHANIC_CONTENT.weapons) == 74
    assert len(WEAPON_MECHANIC_CONTENT.abilities) == 74
    assert len(WEAPON_MECHANIC_CONTENT.targeting) == 74
    assert len(WEAPON_MECHANIC_CONTENT.profiles) == 74
    assert len({value.key for value in WEAPON_BLUEPRINTS}) == 74
    assert len(
        {
            (value.primary, value.support, value.targeting)
            for value in WEAPON_BLUEPRINTS
        }
    ) == 74
    expected_ability_ids = {
        f"ability.weapon.{value.key}" for value in WEAPON_BLUEPRINTS
    }
    assert expected_ability_ids.issubset(catalog.battle_ability_targeting)
    for blueprint in WEAPON_BLUEPRINTS:
        targeting = catalog.battle_ability_targeting[
            f"ability.weapon.{blueprint.key}"
        ]
        if blueprint.targeting in {"single", "lowest", "random"}:
            assert targeting.maximum_targets == 1
        elif blueprint.targeting == "adjacent":
            assert targeting.maximum_targets == 3
        else:
            assert blueprint.targeting == "all"
            assert targeting.maximum_targets is None


def _assert_instance_generation(catalog) -> None:
    generator = WeaponInstanceGenerator(
        catalog.weapons,
        catalog.itemization_engine,
        WEAPON_MAXIMUM_LEVEL_TABLE,
    )
    definition_ids = tuple(
        definition_id
        for definition_id in catalog.weapons.definitions.ids()
        if catalog.weapons.require(definition_id).generation_profile_id is not None
    )
    assert len(definition_ids) == 74
    replay_request = WeaponGenerationRequest(
        "weapon-replay",
        "asset-weapon-replay",
        definition_ids[0],
        catalog.report.content_fingerprint,
    )
    replay_left = generator.generate(
        replay_request,
        context=_context("weapon-replay", 7001),
    )
    replay_right = generator.generate(
        replay_request,
        context=_context("weapon-replay", 7001),
    )
    assert replay_left == replay_right
    for index, definition_id in enumerate(definition_ids):
        definition = catalog.weapons.require(definition_id)
        result = generator.generate(
            WeaponGenerationRequest(
                f"weapon-instance:{index}",
                f"asset-weapon-{index}",
                definition_id,
                catalog.report.content_fingerprint,
            ),
            context=_context(f"weapon-instance:{index}", index),
        )
        profile = catalog.itemization_engine.catalog.require_profile(
            definition.generation_profile_id
        )
        rolled_ids = {value.property_id for value in result.roll.properties}
        assert result.state.definition_id == definition_id
        assert result.state.quality_id == result.roll.quality_id
        assert result.state.roll == result.roll
        assert len(rolled_ids & profile.core_property_ids) == 1
        for skin_id in (
            CULTIVATION_SKIN_ID,
            MAGIC_SKIN_ID,
            STELLAR_RING_SKIN_ID,
        ):
            projector = catalog.skins.projector(skin_id)
            for property_id in rolled_ids:
                assert projector.name(property_id)
    try:
        generator.generate(
            WeaponGenerationRequest(
                "weapon-starter-rejected",
                "asset-starter-rejected",
                STARTER_WEAPON_ID,
                catalog.report.content_fingerprint,
            ),
            context=_context("weapon-starter-rejected", 9001),
        )
        raise AssertionError("固定新手武器不得进入随机生成器")
    except ValueError as exc:
        assert "固定武器" in str(exc)


def _assert_all_active_abilities_execute(executor: GameplayExecutor) -> None:
    for index, blueprint in enumerate(WEAPON_BLUEPRINTS):
        ability_id = f"ability.weapon.{blueprint.key}"
        actor = _entity("actor", ability_id=ability_id)
        target = _entity("target")
        outcome = executor.execute_ability(
            AbilityUse(f"weapon-all:{index}", ability_id),
            actor=actor,
            target=target,
            context=_context(f"weapon-all:{index}", index),
        )
        assert outcome.failure is None, (blueprint.key, outcome.failure)
        assert outcome.value is not None
        assert outcome.value.target.resources["health.current"] < 100_000
        unknown = {
            str(event.kind) for event in outcome.value.events
        } - KNOWN_BATTLE_EVENT_KINDS
        assert not unknown, (blueprint.key, unknown)


def _assert_random_branch_is_real(executor: GameplayExecutor) -> None:
    ability_id = "ability.weapon.fate_die"
    branches = set()
    damage_values = set()
    for seed in range(32):
        outcome = executor.execute_ability(
            AbilityUse(f"fate-die:{seed}", ability_id),
            actor=_entity("actor", ability_id=ability_id),
            target=_entity("target"),
            context=_context(f"fate-die:{seed}", seed),
        )
        assert outcome.failure is None and outcome.value is not None
        choice_events = tuple(
            event
            for event in outcome.value.events
            if event.kind == "effect.choice.selected"
        )
        assert len(choice_events) == 1
        branches.add(choice_events[0].values["branch"])
        damage_values.add(
            100_000 - outcome.value.target.resources["health.current"]
        )
    assert branches == {0, 1}
    assert len(damage_values) == 2


def _assert_all_weapon_triggers_execute(catalog) -> None:
    trigger_ids = tuple(
        trigger_id
        for trigger_id in catalog.triggers.ids()
        if trigger_id.startswith("trigger.weapon.")
    )
    assert trigger_ids
    for index, trigger_id in enumerate(trigger_ids):
        definition = catalog.triggers.require(trigger_id)
        owner_id = "target" if definition.owner.value == "event_target" else "actor"
        actor = _entity(
            "actor",
            trigger_id=trigger_id if owner_id == "actor" else None,
            cooldowns={"ability.basic_attack": 3},
        )
        target = _entity(
            "target",
            trigger_id=trigger_id if owner_id == "target" else None,
            cooldowns={"ability.basic_attack": 3},
        )
        context = _context(f"weapon-trigger:{trigger_id}", 20_000 + index)
        event = RuleEvent.from_context(
            context,
            kind=definition.event_kind,
            source_id="actor",
            target_id="target",
            subject_id="combat.test",
            values={
                "damage_type": "damage.physical",
                "is_proc": 0.0,
                "effective_damage": 100.0,
                "health_damage": 100.0,
                "shield_damage": 100.0,
                "actual": 100.0,
            },
        )
        result = catalog.trigger_engine.process(
            (event,),
            entities={"actor": actor, "target": target},
            context=context,
        )
        assert any(
            value.kind == "trigger.activated" and value.subject_id == trigger_id
            for value in result.events
        ), trigger_id
        unknown = {
            str(value.kind)
            for value in result.events
            if str(value.kind).startswith(
                ("ability.", "combat.", "effect.", "resource.", "trigger.")
            )
        } - KNOWN_BATTLE_EVENT_KINDS
        assert not unknown, (trigger_id, unknown)


def _assert_mark_and_detonation_cycle(executor: GameplayExecutor) -> None:
    ability_id = "ability.weapon.hidden_edge_coffer"
    first = executor.execute_ability(
        AbilityUse("mark-cycle:first", ability_id),
        actor=_entity("actor", ability_id=ability_id),
        target=_entity("target"),
        context=_context("mark-cycle:first", 11),
    )
    assert first.failure is None and first.value is not None
    assert _effect_stacks(first.value.target, WEAPON_MARK_EFFECT_ID) == 1
    first_damage = 100_000 - first.value.target.resources["health.current"]

    second_actor = replace(first.value.actor, cooldowns={})
    second = executor.execute_ability(
        AbilityUse("mark-cycle:second", ability_id),
        actor=second_actor,
        target=first.value.target,
        context=_context("mark-cycle:second", 12),
    )
    assert second.failure is None and second.value is not None
    second_damage = (
        first.value.target.resources["health.current"]
        - second.value.target.resources["health.current"]
    )
    assert second_damage > first_damage
    assert _effect_stacks(second.value.target, WEAPON_MARK_EFFECT_ID) == 1


def _assert_periodic_damage(executor: GameplayExecutor, catalog) -> None:
    ability_id = "ability.weapon.plague_banner"
    applied = executor.execute_ability(
        AbilityUse("periodic:apply", ability_id),
        actor=_entity("actor", ability_id=ability_id),
        target=_entity("target"),
        context=_context("periodic:apply", 21),
    )
    assert applied.failure is None and applied.value is not None
    health_before = applied.value.target.resources["health.current"]
    turn_context = _context("periodic:turn", 22)
    event = RuleEvent.from_context(
        turn_context,
        kind="combat.turn.started",
        source_id="target",
        target_id="target",
        subject_id="combat.turn",
    )
    result = catalog.trigger_engine.process(
        (event,),
        entities={"actor": applied.value.actor, "target": applied.value.target},
        context=turn_context,
    )
    assert result.entity("target").resources["health.current"] < health_before
    assert any(
        value.kind == "combat.damage.dealt"
        and value.values.get("damage_type") == "damage.poison"
        for value in result.events
    )


def _assert_current_cooldown_delay(executor: GameplayExecutor) -> None:
    ability_id = "ability.weapon.null_blade"
    target = _entity("target", cooldowns={"ability.basic_attack": 2})
    outcome = executor.execute_ability(
        AbilityUse("cooldown-delay", ability_id),
        actor=_entity("actor", ability_id=ability_id),
        target=target,
        context=_context("cooldown-delay", 31),
    )
    assert outcome.failure is None and outcome.value is not None
    assert outcome.value.target.cooldowns["ability.basic_attack"] == 3


def _assert_borrowed_force_and_report_projection(
    executor: GameplayExecutor,
    catalog,
) -> None:
    ability_id = "ability.weapon.borrowed_edge"

    def execute(target_attack: float, use_id: str):
        return executor.execute_ability(
            AbilityUse(use_id, ability_id),
            actor=_entity("actor", ability_id=ability_id, attack=100),
            target=_entity("target", attack=target_attack),
            context=_context(use_id, 41),
        )

    low = execute(50, "borrowed-force:low")
    high = execute(300, "borrowed-force:high")
    extreme = execute(10_000, "borrowed-force:extreme")
    assert low.failure is None and low.value is not None
    assert high.failure is None and high.value is not None
    assert extreme.failure is None and extreme.value is not None
    low_damage = 100_000 - low.value.target.resources["health.current"]
    high_damage = 100_000 - high.value.target.resources["health.current"]
    extreme_damage = 100_000 - extreme.value.target.resources["health.current"]
    assert low_damage == 95
    assert high_damage == extreme_damage == 126
    assert any(
        str(effect.definition_id) == "effect.weapon.borrowed_edge.support"
        and effect.remaining_turns == 2
        for effect in high.value.actor.active_effects
    )

    view = select_world_skin(catalog, CULTIVATION_SKIN_ID)
    combatants = _frozen_combatants(
        view,
        {"actor": "试剑者", "target": "镜前敌"},
        high.value.events,
    )
    presented = [
        present_battle_event(
            StoredBattleEvent(
                str(event.kind),
                event.source_id,
                event.target_id,
                str(event.subject_id),
                event.logical_time,
                dict(event.values),
                event.phase.value,
            ),
            combatants,
        )
        for event in high.value.events
    ]
    assert all(event["text"] for event in presented)
    assert any("移星换斗镜·主效" in event["text"] for event in presented)
    assert any("移星换斗镜·辅效" in event["text"] for event in presented)
    assert any(
        event["kind"] == "combat.damage.dealt"
        and "126 点" in event["text"]
        and any(
            fact["key"] == "effective_damage" and fact["value"] == 126
            for fact in event["facts"]
        )
        for event in presented
    )


def _assert_deferred_echo_and_report_projection(
    executor: GameplayExecutor,
    catalog,
) -> None:
    ability_id = "ability.weapon.deferred_echo"
    applied = executor.execute_ability(
        AbilityUse("deferred-echo:apply", ability_id),
        actor=_entity("actor", ability_id=ability_id, attack=100),
        target=_entity("target"),
        context=_context("deferred-echo:apply", 51),
    )
    assert applied.failure is None and applied.value is not None
    assert 100_000 - applied.value.target.resources["health.current"] == 72
    assert any(
        str(effect.definition_id) == "effect.weapon.deferred_echo.echo_status"
        and effect.remaining_turns == 1
        for effect in applied.value.target.active_effects
    )

    premature_context = _context("deferred-echo:premature", 52)
    premature_event = RuleEvent.from_context(
        premature_context,
        kind="combat.turn.started",
        source_id="actor",
        target_id="actor",
        subject_id="combat.turn",
    )
    premature = catalog.trigger_engine.process(
        (premature_event,),
        entities={"actor": applied.value.actor, "target": applied.value.target},
        context=premature_context,
    )
    health_before_echo = premature.entity("target").resources["health.current"]
    assert health_before_echo == applied.value.target.resources["health.current"]

    release_context = _context("deferred-echo:release", 53)
    release_event = RuleEvent.from_context(
        release_context,
        kind="combat.turn.started",
        source_id="target",
        target_id="target",
        subject_id="combat.turn",
    )
    released = catalog.trigger_engine.process(
        (release_event,),
        entities=premature.entities,
        context=release_context,
    )
    echo_damage = health_before_echo - released.entity("target").resources["health.current"]
    assert round(echo_damage, 1) == 61.2
    assert any(
        event.kind == "trigger.activated"
        and str(event.subject_id) == "trigger.weapon.deferred_echo.echo_release"
        for event in released.events
    )
    assert any(
        event.kind == "combat.damage.dealt"
        and event.values.get("damage_type") == "damage.true"
        and round(float(event.values.get("effective_damage", 0)), 1) == 61.2
        for event in released.events
    )

    view = select_world_skin(catalog, CULTIVATION_SKIN_ID)
    report_events = (*applied.value.events, *released.events)
    combatants = _frozen_combatants(
        view,
        {"actor": "奏璧者", "target": "闻声敌"},
        report_events,
    )
    presented = [
        present_battle_event(
            StoredBattleEvent(
                str(event.kind),
                event.source_id,
                event.target_id,
                str(event.subject_id),
                event.logical_time,
                dict(event.values),
                event.phase.value,
            ),
            combatants,
        )
        for event in report_events
    ]
    assert all(event["text"] for event in presented)
    assert any("空桑回音璧·回响标记" in event["text"] for event in presented)
    assert any("空桑回音璧·回响结算" in event["text"] for event in presented)
    assert any(
        event["kind"] == "combat.damage.dealt"
        and "61.2 点" in event["text"]
        and any(
            fact["key"] == "effective_damage"
            and round(float(fact["value"]), 1) == 61.2
            for fact in event["facts"]
        )
        for event in presented
    )


def _frozen_combatants(view, labels, events):
    identifiers = {
        str(HEALTH_CURRENT),
        str(SHIELD_CURRENT),
        str(COMBAT_DEFENSE),
    }
    for event in events:
        identifiers.add(str(event.subject_id))
        identifiers.update(_content_identifiers(event.values))
    terms = {}
    for identifier in identifiers:
        try:
            entry = view.projector.entry(identifier)
        except (KeyError, ValueError):
            terms[identifier] = BattleReportTerm(identifier)
        else:
            terms[identifier] = BattleReportTerm(
                entry.name,
                entry.compact_name or entry.name,
            )
    return {
        key: StoredBattleCombatant(
            key,
            label,
            key,
            label,
            "character",
            "character_world",
            str(view.world.id),
            view.skin.version,
            terms,
        )
        for key, label in labels.items()
    }


def _content_identifiers(value):
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _content_identifiers(item)
        return
    if isinstance(value, (tuple, list, set, frozenset)):
        for item in value:
            yield from _content_identifiers(item)
        return
    if isinstance(value, str) and "." in value and ":" not in value:
        yield value


def _assert_fast_balance(catalog) -> None:
    static_start = perf_counter()
    static_report = WeaponBalanceAuditor().audit()
    assert len(static_report.entries) == 74
    assert not static_report.outliers(22.0)
    assert perf_counter() - static_start < 1.0

    generation_start = perf_counter()
    generation_report = ItemizationBalanceAuditor(
        catalog.itemization_engine
    ).audit(
        profile_ids=tuple(
            value.id for value in WEAPON_MECHANIC_CONTENT.profiles
        ),
        content_fingerprint=catalog.report.content_fingerprint,
        samples_per_profile=128,
    )
    elapsed = perf_counter() - generation_start
    assert generation_report.total_samples == 74 * 128
    assert set(generation_report.quality_counts) == set(QUALITY_IDS)
    assert not generation_report.profiles_above_attempts(1.05)
    assert elapsed < 15.0, elapsed
    ratios = {
        quality_id: amount / generation_report.total_samples
        for quality_id, amount in generation_report.quality_counts.items()
    }
    assert 0.40 <= ratios["quality.common"] <= 0.52
    assert 0.24 <= ratios["quality.fine"] <= 0.36
    assert 0.10 <= ratios["quality.rare"] <= 0.20
    assert 0.04 <= ratios["quality.epic"] <= 0.11
    assert 0.005 <= ratios["quality.legendary"] <= 0.03


def _context(trace_id: str, seed: int) -> RuleContext:
    return RuleContext(
        trace_id,
        "rules.weapon_catalog_test",
        Ruleset("ruleset.weapon_catalog_test"),
        datetime(2026, 7, 16, tzinfo=timezone.utc),
        SeededRandomSource(seed),
    )


def _entity(
    entity_id: str,
    *,
    ability_id: str | None = None,
    cooldowns=None,
    trigger_id: str | None = None,
    attack: float = 100,
) -> RuleEntity:
    active_effects = ()
    if trigger_id:
        active_effects = (
            ActiveEffect(
                f"weapon-grant:{entity_id}:{trigger_id}",
                "effect.weapon.test_grant",
                entity_id,
                granted_triggers=frozenset({trigger_id}),
                remaining_turns=None,
            ),
        )
    return RuleEntity(
        entity_id,
        base_attributes={
            "health.maximum": 100_000,
            "spirit.maximum": 1_000,
            "combat.attack": attack,
            "combat.defense.physical": 0,
            "combat.speed": 100,
            "combat.accuracy": 1,
            "combat.critical.chance": 0,
        },
        resources={
            "health.current": 100_000,
            "spirit.current": 1_000,
            "combat.shield.current": 0,
        },
        base_abilities=frozenset({ability_id}) if ability_id else frozenset(),
        active_effects=active_effects,
        cooldowns=cooldowns or {},
    )


def _effect_stacks(entity: RuleEntity, effect_id: str) -> int:
    return sum(
        value.stacks
        for value in entity.active_effects
        if value.definition_id == effect_id
    )


if __name__ == "__main__":
    main()
