"""装备上线前的套装投影、真实触发与速度分布验收。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services  # noqa: E402
from game.content.catalog.equipment.blueprints import (  # noqa: E402
    EQUIPMENT_FAMILY_BLUEPRINTS,
    EQUIPMENT_SET_BLUEPRINTS,
    EQUIPMENT_SLOT_BLUEPRINTS,
)
from game.content.catalog.equipment.definitions import (  # noqa: E402
    equipment_definition_id,
    equipment_set_id,
)
from game.core.account import ExternalIdentity, IdentityEvidence  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    COMBAT_SPEED,
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    SPIRIT_MAXIMUM,
    EquipmentContributionProvider,
    ItemInstance,
    LoadoutPreset,
    RuleContext,
    RuleEntity,
    RuleEvent,
    Ruleset,
    SeededRandomSource,
    SourceReceipt,
    equipment_state_data,
)
from game.rules import EquipmentGenerationRequest, EquipmentInstanceGenerator  # noqa: E402


TIME = datetime(2026, 7, 23, 8, 0, tzinfo=timezone.utc)


def main() -> None:
    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "equipment-release.db",
            identity_secret="equipment-release-acceptance-secret",
        )
        services.database.initialize()
        character = _create_character(services)
        overview = services.load_character_overview(character).overview
        assert overview is not None
        _assert_every_set_projects_and_triggers(
            services,
            character,
            overview.inventory,
            overview.loadout,
        )
        _assert_equipment_speed_distribution(services.content.catalog)
    print("equipment release acceptance tests passed")


def _assert_every_set_projects_and_triggers(
    services,
    character,
    base_inventory,
    base_loadout,
) -> None:
    catalog = services.content.catalog
    generator = EquipmentInstanceGenerator(
        catalog.equipment,
        catalog.itemization_engine,
        set_mark_chance=0,
    )
    covered = set()
    for set_index, blueprint in enumerate(EQUIPMENT_SET_BLUEPRINTS):
        set_id = equipment_set_id(blueprint.key)
        inventory, loadout = _six_piece_loadout(
            catalog,
            generator,
            base_inventory,
            base_loadout,
            set_id,
            set_index,
        )
        lineup = services.player_lineup.project(
            character,
            inventory,
            loadout,
            None,
        )
        player = lineup.player.entity
        effect_ids = {str(value.definition_id) for value in player.active_effects}
        expected_bonus_ids = {
            f"{set_id}.bonus.pieces_{pieces}" for pieces in (2, 3, 4)
        }
        assert expected_bonus_ids <= effect_ids

        set_definition = catalog.equipment.sets.require(set_id)
        four_piece = next(
            value for value in set_definition.bonuses if value.required_pieces == 4
        )
        assert len(four_piece.contribution.triggers) == 1
        trigger_id = next(iter(four_piece.contribution.triggers))
        assert trigger_id in player.triggers
        _assert_trigger_activates(catalog, player, trigger_id, set_index)
        covered.add(set_id)
    assert covered == set(catalog.equipment.sets.ids())


def _six_piece_loadout(
    catalog,
    generator,
    base_inventory,
    base_loadout,
    set_id: str,
    set_index: int,
):
    equipped = next(
        value for value in base_inventory.containers.values()
        if value.kind == "container.equipped"
    )
    instances = dict(base_inventory.instances)
    slots = dict(base_loadout.slots)
    for slot_index, slot in enumerate(EQUIPMENT_SLOT_BLUEPRINTS):
        family = EQUIPMENT_FAMILY_BLUEPRINTS[
            (set_index + slot_index) % len(EQUIPMENT_FAMILY_BLUEPRINTS)
        ]
        asset_id = f"release:{set_id}:{slot.key}"
        generated = generator.generate(
            EquipmentGenerationRequest(
                f"release-generate:{set_id}:{slot.key}",
                asset_id,
                equipment_definition_id(family.key, slot.key),
                catalog.report.content_fingerprint,
            ),
            context=_context(
                f"release-generate:{set_id}:{slot.key}",
                20_000 + set_index * 10 + slot_index,
            ),
            forced_set_id=set_id,
        ).state
        definition = catalog.equipment.require(generated.definition_id)
        instances[asset_id] = ItemInstance(
            asset_id,
            definition.item_definition_id,
            equipped.id,
            SourceReceipt(
                f"release-source:{set_id}:{slot.key}",
                "source.test.equipment_release",
                set_id,
                TIME,
            ),
            equipment_state_data(generated),
        )
        slots[slot.slot_id] = asset_id
    inventory = replace(
        base_inventory,
        instances=instances,
        asset_references={
            **base_inventory.asset_references,
            **{
                asset_id: base_inventory.next_reference_number + offset
                for offset, asset_id in enumerate(
                    sorted(set(instances) - set(base_inventory.instances)),
                    start=0,
                )
            },
        },
        revision=base_inventory.revision + 1,
    )
    active_id = base_loadout.active_preset_id
    assert active_id is not None
    presets = dict(base_loadout.presets)
    presets[active_id] = LoadoutPreset(active_id, slots)
    loadout = replace(
        base_loadout,
        slots=slots,
        presets=presets,
        revision=base_loadout.revision + 1,
    )
    return inventory, loadout


def _assert_trigger_activates(catalog, player, trigger_id: str, seed_offset: int) -> None:
    definition = catalog.triggers.require(trigger_id)
    resources = dict(player.resources)
    resources[HEALTH_CURRENT] = min(1.0, resources.get(HEALTH_CURRENT, 1.0))
    player = replace(
        player,
        resources=resources,
        cooldowns={"ability.basic_attack": 3},
    )
    dummy = _combatant("release-target")
    player_is_target = definition.owner.value == "event_target"
    source = dummy if player_is_target else player
    target = player if player_is_target else dummy
    for seed in range(512):
        context = _context(
            f"release-trigger:{trigger_id}:{seed}",
            40_000 + seed_offset * 1_000 + seed,
        )
        event = RuleEvent.from_context(
            context,
            kind=definition.event_kind,
            source_id=source.id,
            target_id=target.id,
            subject_id="damage.physical",
            values={
                "is_proc": 0.0,
                "damage_type": "damage.physical",
                "raw": 100.0,
                "effective_damage": 100.0,
                "health_damage": 100.0,
                "shield_damage": 100.0,
                "actual": 100.0,
                "delta": -100.0,
                "current": 1.0,
            },
        )
        outcome = catalog.trigger_engine.process(
            (event,),
            entities={player.id: player, dummy.id: dummy},
            context=context,
        )
        if any(
            value.kind == "trigger.activated" and value.subject_id == trigger_id
            for value in outcome.events
        ):
            return
    raise AssertionError(f"套装触发器没有真实触发：{trigger_id}")


def _assert_equipment_speed_distribution(catalog) -> None:
    generator = EquipmentInstanceGenerator(
        catalog.equipment,
        catalog.itemization_engine,
    )
    provider = EquipmentContributionProvider(catalog.equipment)
    speeds = []
    samples = 1_024
    for sample in range(samples):
        states = []
        for slot_index, slot in enumerate(EQUIPMENT_SLOT_BLUEPRINTS):
            family = EQUIPMENT_FAMILY_BLUEPRINTS[
                (sample + slot_index) % len(EQUIPMENT_FAMILY_BLUEPRINTS)
            ]
            states.append(
                generator.generate(
                    EquipmentGenerationRequest(
                        f"release-speed:{sample}:{slot.key}",
                        f"release-speed-asset:{sample}:{slot.key}",
                        equipment_definition_id(family.key, slot.key),
                        catalog.report.content_fingerprint,
                    ),
                    context=_context(
                        f"release-speed:{sample}:{slot.key}",
                        80_000 + sample * 10 + slot_index,
                    ),
                ).state
            )
        speed = 100.0 + sum(
            grant.value
            for contribution in provider.contributions(tuple(states))
            for grant in contribution.contribution.attributes
            if grant.attribute_id == COMBAT_SPEED
        )
        speeds.append(speed)
    speeds.sort()
    median = speeds[len(speeds) // 2]
    percentile_95 = speeds[round((len(speeds) - 1) * 0.95)]
    assert speeds[0] >= 100
    assert median >= 100
    assert 105 <= percentile_95 <= 175
    assert percentile_95 <= speeds[-1] <= 225


def _create_character(services):
    evidence = IdentityEvidence(
        "evidence:equipment-release",
        ExternalIdentity(
            "platform.local",
            "equipment-release",
            "identity.user",
            "private",
            "equipment-release-user",
        ),
        (),
        "message.local",
        TIME,
    )
    result = services.create_character(evidence, requested_name="装备验收者")
    assert result.status == "created" and result.receipt is not None
    return result.receipt.character


def _combatant(entity_id: str) -> RuleEntity:
    return RuleEntity(
        entity_id,
        base_attributes={
            HEALTH_MAXIMUM: 10_000,
            SPIRIT_MAXIMUM: 1_000,
            "combat.attack": 100,
            "combat.defense.physical": 0,
            COMBAT_SPEED: 100,
            "combat.accuracy": 1,
        },
        resources={
            HEALTH_CURRENT: 1_000,
            SPIRIT_CURRENT: 1_000,
            "combat.shield.current": 0,
        },
    )


def _context(trace_id: str, seed: int) -> RuleContext:
    return RuleContext(
        trace_id,
        "rules.equipment_release_acceptance.v1",
        Ruleset("ruleset.equipment_release_acceptance"),
        TIME,
        SeededRandomSource(seed),
    )


if __name__ == "__main__":
    main()
