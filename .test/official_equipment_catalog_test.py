"""正式装备名录、实例生成、套装贡献和真实触发巡检。"""

from __future__ import annotations

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

from game.content.catalog import BASIC_ATTACK_ABILITY_ID  # noqa: E402
from game.content.catalog.economy import EQUIPMENT_BLUEPRINT_EXPECTED_GEAR_VALUE  # noqa: E402
from game.content.catalog.equipment.blueprints import (  # noqa: E402
    EQUIPMENT_FAMILY_BLUEPRINTS,
    EQUIPMENT_PROPERTY_BLUEPRINTS,
    EQUIPMENT_SET_BLUEPRINTS,
    EQUIPMENT_SLOT_BLUEPRINTS,
)
from game.content.catalog.equipment.definitions import (  # noqa: E402
    EQUIPMENT_CATALOG_CONTENT,
    equipment_definition_id,
    equipment_item_id,
    equipment_set_id,
)
from game.content.catalog.item import equipment_set_blueprint_item_id  # noqa: E402
from game.content.catalog.equipment.properties import (  # noqa: E402
    EQUIPMENT_GENERATION_PROFILE_ID,
    EQUIPMENT_SET_MARK_CHANCE,
    EQUIPMENT_PROPERTY_CONTENT,
    equipment_property_id,
    equipment_trigger_id,
)
from game.content.official import (  # noqa: E402
    DEFAULT_SKIN_ID,
    assemble_official_catalog,
    select_world_skin,
)
from game.content.world_skins import MAGIC_SKIN_ID  # noqa: E402
from game.features.battle_report import resolve_battle_content_name  # noqa: E402
from support.equipment_balance_audit import EquipmentBalanceAuditor  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    ActiveEffect,
    AbilityUse,
    EquipmentContributionProvider,
    GameplayExecutor,
    RuleContext,
    RuleEntity,
    RuleEvent,
    Ruleset,
    SeededRandomSource,
)
from game.rules import (  # noqa: E402
    EquipmentGenerationRequest,
    EquipmentInstanceGenerator,
)
from game.rules.battle_report import KNOWN_BATTLE_EVENT_KINDS  # noqa: E402


def main() -> None:
    catalog = assemble_official_catalog()
    _assert_catalog_shape(catalog)
    _assert_world_skin_projection(catalog)
    _assert_instance_generation(catalog)
    _assert_six_piece_contribution(catalog)
    _assert_real_trigger_execution(catalog)
    _assert_reactive_trigger_caps(catalog)
    _assert_every_equipment_trigger_executes(catalog)
    _assert_balance(catalog)
    print("official equipment catalog test passed")


def _assert_catalog_shape(catalog) -> None:
    assert len(EQUIPMENT_FAMILY_BLUEPRINTS) == 12
    assert len(EQUIPMENT_SLOT_BLUEPRINTS) == 6
    assert len(EQUIPMENT_PROPERTY_BLUEPRINTS) == 48
    assert len(EQUIPMENT_SET_BLUEPRINTS) == 18
    assert len(EQUIPMENT_CATALOG_CONTENT.items) == 72
    assert len(EQUIPMENT_CATALOG_CONTENT.equipment) == 72
    assert len(EQUIPMENT_PROPERTY_CONTENT.properties) == 48
    assert len(catalog.equipment.families.ids()) == 12
    assert len(catalog.equipment.definitions.ids()) == 72
    assert len(catalog.equipment.sets.ids()) == 18
    assert {
        value.id for value in EQUIPMENT_PROPERTY_CONTENT.properties
    } == {
        equipment_property_id(value.key)
        for value in EQUIPMENT_PROPERTY_BLUEPRINTS
    }
    combinations = {
        (definition.family_id, definition.slot_id)
        for definition in catalog.equipment.definitions
    }
    assert len(combinations) == 72
    for definition in catalog.equipment.definitions:
        assert definition.generation_profile_id == EQUIPMENT_GENERATION_PROFILE_ID
        assert len(definition.quality_profiles) == 5


def _assert_world_skin_projection(catalog) -> None:
    cultivation = select_world_skin(catalog, DEFAULT_SKIN_ID)
    magic = select_world_skin(catalog, MAGIC_SKIN_ID)
    stellar = select_world_skin(catalog, "skin.stellar_ring")
    definition_id = equipment_definition_id("mystic_sky", "head")
    item_id = equipment_item_id("mystic_sky", "head")
    assert cultivation.skin.version == 28
    assert magic.skin.version == 28
    assert stellar.skin.version == 6
    assert cultivation.projector.name(definition_id) == "昆仑冠"
    assert cultivation.projector.name(item_id) == "昆仑冠器胚"
    assert magic.projector.name(definition_id) == "奥林匹斯头冠"
    assert stellar.projector.name(definition_id) == "欧几里得头冠"
    assert cultivation.projector.name(equipment_set_id("army_breaker")) == "七杀破军套"
    assert cultivation.projector.name(equipment_property_id("critical_echo")) == "暴烈回响"
    for view in (cultivation, magic, stellar):
        set_names = []
        blueprint_names = []
        definition_names = []
        for blueprint in EQUIPMENT_SET_BLUEPRINTS:
            set_id = equipment_set_id(blueprint.key)
            set_name = view.projector.name(set_id)
            set_names.append(set_name)
            blueprint_name = view.projector.name(
                equipment_set_blueprint_item_id(blueprint.key)
            )
            blueprint_names.append(blueprint_name)
            assert set_name in blueprint_name
            for pieces in (2, 3, 4):
                bonus_name = resolve_battle_content_name(
                    view,
                    f"{set_id}.bonus.pieces_{pieces}",
                    "未命名效果",
                )
                assert set_name in bonus_name
                assert f"{pieces}件" in bonus_name
        for family in EQUIPMENT_FAMILY_BLUEPRINTS:
            for slot in EQUIPMENT_SLOT_BLUEPRINTS:
                definition_names.append(
                    view.projector.name(
                        equipment_definition_id(family.key, slot.key)
                    )
                )
        assert len(set_names) == len(set(set_names)) == 18
        assert len(blueprint_names) == len(set(blueprint_names)) == 18
        assert len(definition_names) == len(set(definition_names)) == 72


def _assert_instance_generation(catalog) -> None:
    generator = EquipmentInstanceGenerator(catalog.equipment, catalog.itemization_engine)
    definitions = catalog.equipment.definitions.ids()
    replay_request = EquipmentGenerationRequest(
        "equipment-replay",
        "asset-equipment-replay",
        definitions[0],
        catalog.report.content_fingerprint,
    )
    replay_left = generator.generate(
        replay_request,
        context=_context("equipment-replay", 7001),
    )
    replay_right = generator.generate(
        replay_request,
        context=_context("equipment-replay", 7001),
    )
    assert replay_left == replay_right
    set_ids = set()
    marked = 0
    samples = 1024
    for index in range(samples):
        definition_id = definitions[index % len(definitions)]
        result = generator.generate(
            EquipmentGenerationRequest(
                f"equipment-instance:{index}",
                f"asset-equipment-{index}",
                definition_id,
                catalog.report.content_fingerprint,
            ),
            context=_context(f"equipment-instance:{index}", index),
        )
        assert result.state.definition_id == definition_id
        assert result.state.roll == result.roll
        assert 2 <= len(result.roll.properties) <= 5
        if result.state.set_id is not None:
            marked += 1
            set_ids.add(result.state.set_id)
    ratio = marked / samples
    assert EQUIPMENT_SET_MARK_CHANCE == 0.25
    assert 0.20 <= ratio <= 0.30
    assert set_ids == set(catalog.equipment.sets.ids())


def _assert_six_piece_contribution(catalog) -> None:
    generator = EquipmentInstanceGenerator(
        catalog.equipment,
        catalog.itemization_engine,
        set_mark_chance=0,
    )
    base_states = []
    family = EQUIPMENT_FAMILY_BLUEPRINTS[0]
    for index, slot in enumerate(EQUIPMENT_SLOT_BLUEPRINTS):
        generated = generator.generate(
            EquipmentGenerationRequest(
                f"equipment-set:{index}",
                f"asset-set-{index}",
                equipment_definition_id(family.key, slot.key),
                catalog.report.content_fingerprint,
            ),
            context=_context(f"equipment-set:{index}", 2000 + index),
        )
        base_states.append(generated.state)
    provider = EquipmentContributionProvider(catalog.equipment)
    covered = set()
    for set_id in catalog.equipment.sets.ids():
        states = tuple(replace(state, set_id=set_id) for state in base_states)
        contributions = provider.contributions(states)
        assert len(contributions) == 9
        set_contributions = tuple(
            value
            for value in contributions
            if value.source_kind == "source.equipment_set"
        )
        assert tuple(value.id for value in set_contributions) == (
            f"{set_id}.bonus.pieces_2",
            f"{set_id}.bonus.pieces_3",
            f"{set_id}.bonus.pieces_4",
        )
        for contribution in set_contributions:
            spec = contribution.contribution
            assert all(catalog.abilities.contains(value) for value in spec.abilities)
            assert all(catalog.triggers.contains(value) for value in spec.triggers)
            assert all(catalog.interceptors.contains(value) for value in spec.interceptors)
            assert all(
                catalog.target_constraints.contains(value)
                for value in spec.target_constraints
            )
        covered.add(set_id)
    assert covered == set(catalog.equipment.sets.ids())


def _assert_real_trigger_execution(catalog) -> None:
    executor = GameplayExecutor(catalog.ability_engine, catalog.trigger_engine)
    critical_trigger = equipment_trigger_id("critical_echo", 2)
    actor = _combatant(
        "actor",
        ability_id=BASIC_ATTACK_ABILITY_ID,
        trigger_id=critical_trigger,
        critical_chance=1,
    )
    target = _combatant("target")
    outcome = executor.execute_ability(
        AbilityUse("equipment-critical", BASIC_ATTACK_ABILITY_ID),
        actor=actor,
        target=target,
        context=_context("equipment-critical", 4001),
    )
    assert outcome.failure is None and outcome.value is not None
    assert 10_000 - outcome.value.target.resources["health.current"] > 100
    assert any(
        event.kind == "trigger.activated" and event.subject_id == critical_trigger
        for event in outcome.value.events
    )

    burning_trigger = equipment_trigger_id("burning_touch", 3)
    burning_activated = False
    for seed in range(40):
        burning = executor.execute_ability(
            AbilityUse(f"equipment-burning:{seed}", BASIC_ATTACK_ABILITY_ID),
            actor=_combatant(
                "actor",
                ability_id=BASIC_ATTACK_ABILITY_ID,
                trigger_id=burning_trigger,
            ),
            target=_combatant("target"),
            context=_context(f"equipment-burning:{seed}", seed),
        )
        assert burning.failure is None and burning.value is not None
        if any(
            event.kind == "trigger.activated"
            and event.subject_id == burning_trigger
            for event in burning.value.events
        ):
            burning_activated = True
            assert 10_000 - burning.value.target.resources["health.current"] > 100
            break
    assert burning_activated

    venom_trigger = equipment_trigger_id("venom_touch", 2)
    applied = None
    for seed in range(100):
        candidate = executor.execute_ability(
            AbilityUse(f"equipment-venom:{seed}", BASIC_ATTACK_ABILITY_ID),
            actor=_combatant(
                "actor",
                ability_id=BASIC_ATTACK_ABILITY_ID,
                trigger_id=venom_trigger,
            ),
            target=_combatant("target"),
            context=_context(f"equipment-venom:{seed}", seed),
        )
        assert candidate.failure is None and candidate.value is not None
        if any(
            effect.definition_id == "effect.equipment.venom_touch.tier_2"
            for effect in candidate.value.target.active_effects
        ):
            applied = candidate.value
            break
    assert applied is not None
    health_before = applied.target.resources["health.current"]
    turn_context = _context("equipment-venom-turn", 5001)
    event = RuleEvent.from_context(
        turn_context,
        kind="combat.turn.started",
        source_id="target",
        target_id="target",
        subject_id="combat.turn",
    )
    ticked = catalog.trigger_engine.process(
        (event,),
        entities={"actor": applied.actor, "target": applied.target},
        context=turn_context,
    )
    assert ticked.entity("target").resources["health.current"] < health_before


def _assert_every_equipment_trigger_executes(catalog) -> None:
    trigger_ids = tuple(
        trigger_id
        for trigger_id in catalog.triggers.ids()
        if trigger_id.startswith("trigger.equipment.")
    )
    assert trigger_ids
    for trigger_id in trigger_ids:
        definition = catalog.triggers.require(trigger_id)
        owner_id = "target" if definition.owner.value == "event_target" else "actor"
        actor = _combatant(
            "actor",
            trigger_id=trigger_id if owner_id == "actor" else None,
            cooldowns={BASIC_ATTACK_ABILITY_ID: 3},
            health=1_000,
        )
        target = _combatant(
            "target",
            trigger_id=trigger_id if owner_id == "target" else None,
            cooldowns={BASIC_ATTACK_ABILITY_ID: 3},
            health=1_000,
        )
        activated = None
        for seed in range(512):
            context = _context(f"equipment-trigger:{trigger_id}:{seed}", 10_000 + seed)
            event = RuleEvent.from_context(
                context,
                kind=definition.event_kind,
                source_id="actor",
                target_id="target",
                subject_id="combat.test",
                values={
                    "is_proc": 0.0,
                    "damage_type": "damage.physical",
                    "raw": 100.0,
                    "effective_damage": 100.0,
                    "health_damage": 100.0,
                    "shield_damage": 100.0,
                    "actual": 100.0,
                    "delta": -100.0,
                    "current": 1_000.0,
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
                activated = result
                break
        assert activated is not None, trigger_id
        unknown = {
            str(value.kind)
            for value in activated.events
            if str(value.kind).startswith(
                ("ability.", "combat.", "effect.", "resource.", "trigger.")
            )
        } - KNOWN_BATTLE_EVENT_KINDS
        assert not unknown, (trigger_id, unknown)


def _assert_reactive_trigger_caps(catalog) -> None:
    for property_key in ("thorns", "damaged_shield"):
        trigger_id = equipment_trigger_id(property_key, 2)
        actor = _combatant("actor")
        target = _combatant("target", trigger_id=trigger_id)
        context = _context(f"equipment-cap:{property_key}", 9_000)
        direct_damage = RuleEvent.from_context(
            context,
            kind="combat.damage.dealt",
            source_id=actor.id,
            target_id=target.id,
            subject_id="damage.physical",
            values={
                "is_proc": 0.0,
                "damage_type": "damage.physical",
                "effective_damage": 100.0,
                "health_damage": 100.0,
                "shield_damage": 0.0,
            },
        )
        periodic_damage = RuleEvent.from_context(
            context,
            kind="combat.damage.dealt",
            source_id=actor.id,
            target_id=target.id,
            subject_id="damage.bleed",
            values={
                "is_proc": 0.0,
                "damage_type": "damage.physical",
                "effective_damage": 100.0,
                "health_damage": 100.0,
                "shield_damage": 0.0,
            },
        )
        session = catalog.trigger_engine.session(context)
        first_batch = session.process(
            (direct_damage,),
            {actor.id: actor, target.id: target},
        )
        second_batch = session.process((periodic_damage,), first_batch.entities)
        all_events = (*first_batch.events, *second_batch.events)
        assert sum(
            event.kind == "trigger.activated" and event.subject_id == trigger_id
            for event in all_events
        ) == 1
        assert not any(
            event.kind == "trigger.activated" and event.subject_id == trigger_id
            for event in second_batch.events
        )
        unknown = {
            str(event.kind)
            for event in all_events
            if str(event.kind).startswith(
                ("ability.", "combat.", "effect.", "resource.", "trigger.")
            )
        } - KNOWN_BATTLE_EVENT_KINDS
        assert not unknown, (trigger_id, unknown)


def _assert_balance(catalog) -> None:
    started = perf_counter()
    report = EquipmentBalanceAuditor(
        catalog.itemization_engine,
        catalog.valuation_engine,
        catalog.equipment,
    ).audit(content_fingerprint=catalog.report.content_fingerprint)
    elapsed = perf_counter() - started
    assert report.samples == 9216
    assert not report.missing_property_ids
    assert report.mean_attempts == 1
    assert abs(report.mean_value * 100 - EQUIPMENT_BLUEPRINT_EXPECTED_GEAR_VALUE) < 100
    assert elapsed < 20
    assert 0.40 <= report.quality_ratio("quality.common") <= 0.52
    assert 0.24 <= report.quality_ratio("quality.fine") <= 0.36
    assert 0.11 <= report.quality_ratio("quality.rare") <= 0.21
    assert 0.04 <= report.quality_ratio("quality.epic") <= 0.11
    assert 0.005 <= report.quality_ratio("quality.legendary") <= 0.03
    for values in report.set_cumulative_values.values():
        assert tuple(values) == (2, 3, 4)
        assert values[2] < values[3] < values[4]
        assert 18 <= values[4] <= 27


def _context(trace_id: str, seed: int) -> RuleContext:
    return RuleContext(
        trace_id,
        "rules.official_equipment_test",
        Ruleset("ruleset.official_equipment_test"),
        datetime(2026, 7, 16, tzinfo=timezone.utc),
        SeededRandomSource(seed),
    )


def _combatant(
    entity_id: str,
    *,
    ability_id: str | None = None,
    trigger_id: str | None = None,
    critical_chance: float = 0,
    cooldowns=None,
    health: float = 10_000,
) -> RuleEntity:
    active_effects = ()
    if trigger_id:
        active_effects = (
            ActiveEffect(
                f"equipment-grant:{entity_id}:{trigger_id}",
                "effect.equipment.test_grant",
                entity_id,
                granted_triggers=frozenset({trigger_id}),
                remaining_turns=None,
            ),
        )
    return RuleEntity(
        entity_id,
        base_attributes={
            "health.maximum": 10_000,
            "spirit.maximum": 1_000,
            "combat.attack": 100,
            "combat.defense.physical": 0,
            "combat.speed": 100,
            "combat.accuracy": 1,
            "combat.critical.chance": critical_chance,
            "combat.critical.damage": 0,
        },
        resources={
            "health.current": health,
            "spirit.current": 1_000,
            "combat.shield.current": 0,
        },
        base_abilities=frozenset({ability_id}) if ability_id else frozenset(),
        active_effects=active_effects,
        cooldowns=cooldowns or {},
    )


if __name__ == "__main__":
    main()
