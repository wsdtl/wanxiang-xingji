"""一武器槽、六装备槽、武器成长和装备随机品质联合测试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay import (  # noqa: E402
    AttributeDefinition,
    AttributeResolver,
    ModifierLayer,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    TagSet,
)
from game.core.gameplay.character import (  # noqa: E402
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    COMBAT_SPEED,
    HEALTH_MAXIMUM,
    SPIRIT_MAXIMUM,
    AttributeGrant,
    CharacterCatalog,
    CharacterProjector,
    CharacterTemplateDefinition,
    ContributionSpec,
    core_attribute_definitions,
    persistent_resource_definitions,
)
from game.core.gameplay.equipment import (  # noqa: E402
    EQUIPMENT_FOUNDATION_VERSION,
    EquipmentCatalog,
    EquipmentContributionProvider,
    EquipmentDefinition,
    EquipmentFamilyDefinition,
    EquipmentQualityProfile,
    EquipmentSetBonus,
    EquipmentSetDefinition,
    EquipmentState,
)
from game.core.gameplay.inventory import (  # noqa: E402
    GrantInstance,
    InventoryEngine,
    InventoryState,
    InventoryTransaction,
    ItemAssetKind,
    ItemCatalog,
    ItemComponentRegistry,
    ItemContainer,
    ItemDefinition,
    SourceReceipt,
)
from game.core.gameplay.loadout import (  # noqa: E402
    BODY_SLOT_ID,
    HEAD_SLOT_ID,
    LOADOUT_FOUNDATION_VERSION,
    WEAPON_SLOT_ID,
    ActivateLoadoutPreset,
    EquipAsset,
    LoadoutContributionAssembler,
    LoadoutEngine,
    LoadoutItemComponent,
    LoadoutPreset,
    LoadoutState,
    LoadoutTransaction,
    QualityCatalog,
    QualityDefinition,
    UnequipSlot,
    register_loadout_item_component,
    standard_loadout_slot_catalog,
)
from game.core.gameplay.weapon import (  # noqa: E402
    WEAPON_FOUNDATION_VERSION,
    WeaponCatalog,
    WeaponContributionProvider,
    WeaponDefinition,
    WeaponEngine,
    WeaponExperienceTransaction,
    WeaponLevelAttribute,
    WeaponQualityProfile,
)


TIME = datetime(2026, 7, 12, 22, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
CRITICAL_CHANCE = "combat.critical.chance"


def main() -> None:
    env = _environment()
    _assert_foundation_shapes(env)
    _assert_atomic_equip_and_full_container_replace(env)
    _assert_weapon_growth_and_contributions(env)
    _assert_equipment_has_no_growth_axis(env)
    _assert_only_equipped_assets_are_projected(env)
    _assert_multi_loadout_switch_is_atomic(env)
    _assert_set_bonuses_are_separate(env)
    print("loadout weapon equipment tests passed")


def _context(seed: int = 11) -> RuleContext:
    return RuleContext(
        trace_id=f"gear-test-{seed}",
        rule_version="rules.v1",
        ruleset=Ruleset("ruleset.standard"),
        logical_time=TIME,
        random=SeededRandomSource(seed),
    )


def _receipt(receipt_id: str) -> SourceReceipt:
    return SourceReceipt(receipt_id, "source.test_reward", receipt_id, TIME)


def _environment() -> dict[str, object]:
    component_types = ItemComponentRegistry()
    register_loadout_item_component(component_types)
    items = ItemCatalog(component_types)
    items.register(
        ItemDefinition(
            "item.weapon.wind_blade",
            ItemAssetKind.INSTANCE,
            tags=TagSet.of("item.weapon"),
            components={
                "item_component.loadout": LoadoutItemComponent(
                    frozenset({WEAPON_SLOT_ID})
                )
            },
        )
    )
    items.register(
        ItemDefinition(
            "item.equipment.combo_head",
            ItemAssetKind.INSTANCE,
            tags=TagSet.of("item.equipment", "item.equipment.head"),
            components={
                "item_component.loadout": LoadoutItemComponent(
                    frozenset({HEAD_SLOT_ID})
                )
            },
        )
    )
    items.register(
        ItemDefinition(
            "item.equipment.sustain_head",
            ItemAssetKind.INSTANCE,
            tags=TagSet.of("item.equipment", "item.equipment.head"),
            components={
                "item_component.loadout": LoadoutItemComponent(
                    frozenset({HEAD_SLOT_ID})
                )
            },
        )
    )
    items.register(
        ItemDefinition(
            "item.equipment.combo_body",
            ItemAssetKind.INSTANCE,
            tags=TagSet.of("item.equipment", "item.equipment.body"),
            components={
                "item_component.loadout": LoadoutItemComponent(
                    frozenset({BODY_SLOT_ID})
                )
            },
        )
    )
    inventory = InventoryEngine(items)
    slots = standard_loadout_slot_catalog()
    qualities = QualityCatalog()
    qualities.register(QualityDefinition("quality.common", 0))
    qualities.register(QualityDefinition("quality.rare", 1))
    qualities.finalize()

    weapons = WeaponCatalog(qualities, items)
    weapons.register(
        WeaponDefinition(
            "weapon.wind_blade",
            "item.weapon.wind_blade",
            ContributionSpec(tags=TagSet.of("weapon.tempo.fast")),
            {
                "quality.common": WeaponQualityProfile(
                    "quality.common",
                    experience_requirements=(100,),
                    level_attributes=(
                        WeaponLevelAttribute(
                            COMBAT_ATTACK,
                            ModifierLayer.LOCAL_FLAT,
                            (10, 20),
                        ),
                    ),
                ),
                "quality.rare": WeaponQualityProfile(
                    "quality.rare",
                    experience_requirements=(100, 200),
                    contribution=ContributionSpec(
                        attributes=(
                            AttributeGrant(
                                CRITICAL_CHANCE,
                                ModifierLayer.GLOBAL_FLAT,
                                0.05,
                            ),
                        ),
                    ),
                    level_attributes=(
                        WeaponLevelAttribute(
                            COMBAT_ATTACK,
                            ModifierLayer.LOCAL_FLAT,
                            (20, 35, 50),
                        ),
                    ),
                ),
            },
        )
    )
    weapons.finalize()

    equipment = EquipmentCatalog(qualities, slots, items)
    equipment.register_family(
        EquipmentFamilyDefinition("family.combo", TagSet.of("equipment.family.combo"))
    )
    equipment.register_family(
        EquipmentFamilyDefinition("family.sustain", TagSet.of("equipment.family.sustain"))
    )
    equipment.register_set(
        EquipmentSetDefinition(
            "equipment_set.combo",
            (
                EquipmentSetBonus(
                    2,
                    ContributionSpec(tags=TagSet.of("equipment.set.combo.active")),
                ),
            ),
        )
    )
    equipment.register(
        EquipmentDefinition(
            "equipment.combo_head",
            "item.equipment.combo_head",
            HEAD_SLOT_ID,
            "family.combo",
            quality_profiles={
                "quality.common": EquipmentQualityProfile(
                    "quality.common",
                    ContributionSpec(
                        attributes=(
                            AttributeGrant(
                                CRITICAL_CHANCE,
                                ModifierLayer.GLOBAL_FLAT,
                                0.10,
                            ),
                        ),
                    ),
                ),
                "quality.rare": EquipmentQualityProfile(
                    "quality.rare",
                    ContributionSpec(
                        attributes=(
                            AttributeGrant(
                                CRITICAL_CHANCE,
                                ModifierLayer.GLOBAL_FLAT,
                                0.25,
                            ),
                        ),
                    ),
                ),
            },
        )
    )
    equipment.register(
        EquipmentDefinition(
            "equipment.combo_body",
            "item.equipment.combo_body",
            BODY_SLOT_ID,
            "family.combo",
            quality_profiles={
                "quality.common": EquipmentQualityProfile(
                    "quality.common",
                    ContributionSpec(),
                ),
                "quality.rare": EquipmentQualityProfile(
                    "quality.rare",
                    ContributionSpec(),
                ),
            },
        )
    )
    equipment.register(
        EquipmentDefinition(
            "equipment.sustain_head",
            "item.equipment.sustain_head",
            HEAD_SLOT_ID,
            "family.sustain",
            quality_profiles={
                "quality.common": EquipmentQualityProfile(
                    "quality.common",
                    ContributionSpec(
                        attributes=(
                            AttributeGrant(
                                HEALTH_MAXIMUM,
                                ModifierLayer.LOCAL_FLAT,
                                20,
                            ),
                        ),
                    ),
                ),
                "quality.rare": EquipmentQualityProfile(
                    "quality.rare",
                    ContributionSpec(
                        attributes=(
                            AttributeGrant(
                                HEALTH_MAXIMUM,
                                ModifierLayer.LOCAL_FLAT,
                                40,
                            ),
                        ),
                    ),
                ),
            },
        )
    )
    equipment.finalize()
    return {
        "items": items,
        "inventory": inventory,
        "slots": slots,
        "qualities": qualities,
        "weapons": weapons,
        "equipment": equipment,
    }


def _initial_inventory(env: dict[str, object]) -> InventoryState:
    inventory = env["inventory"]
    assert isinstance(inventory, InventoryEngine)
    state = InventoryState(
        containers={
            "bag": ItemContainer(
                "bag",
                "container.inventory",
                "character-a",
                maximum_assets=2,
            ),
            "equipped": ItemContainer(
                "equipped",
                "container.loadout",
                "character-a",
                maximum_assets=7,
            ),
        }
    )
    return _grant(
        inventory,
        state,
        "grant-weapons",
        GrantInstance(
            "weapon-old",
            "item.weapon.wind_blade",
            "bag",
            _receipt("receipt-weapon-old"),
        ),
        GrantInstance(
            "weapon-new",
            "item.weapon.wind_blade",
            "bag",
            _receipt("receipt-weapon-new"),
        ),
    )


def _grant(
    engine: InventoryEngine,
    state: InventoryState,
    transaction_id: str,
    *operations,
) -> InventoryState:
    outcome = engine.execute(
        InventoryTransaction(
            transaction_id,
            "character-a",
            "inventory.test_reward",
            tuple(operations),
        ),
        state=state,
        context=_context(),
    )
    assert outcome.ok and outcome.value, outcome.failure
    return outcome.value.state


def _loadout_transaction(loadout: LoadoutState, transaction_id: str, *operations):
    return LoadoutTransaction(
        transaction_id,
        "account-a",
        loadout.revision,
        "bag",
        "equipped",
        tuple(operations),
    )


def _prepared_loadout(env: dict[str, object]):
    inventory_engine = env["inventory"]
    items = env["items"]
    slots = env["slots"]
    assert isinstance(inventory_engine, InventoryEngine)
    assert isinstance(items, ItemCatalog)
    loadout_engine = LoadoutEngine(slots, items, inventory_engine)  # type: ignore[arg-type]
    inventory = _initial_inventory(env)
    loadout = LoadoutState("character-a")
    equipped_weapon = loadout_engine.execute(
        _loadout_transaction(
            loadout,
            "equip-old-weapon",
            EquipAsset(WEAPON_SLOT_ID, "weapon-old"),
        ),
        loadout=loadout,
        inventory_state=inventory,
        context=_context(),
    ).unwrap()
    inventory = _grant(
        inventory_engine,
        equipped_weapon.inventory,
        "grant-old-head",
        GrantInstance(
            "head-old",
            "item.equipment.combo_head",
            "bag",
            _receipt("receipt-head-old"),
        ),
    )
    equipped_head = loadout_engine.execute(
        _loadout_transaction(
            equipped_weapon.loadout,
            "equip-old-head",
            EquipAsset(HEAD_SLOT_ID, "head-old"),
        ),
        loadout=equipped_weapon.loadout,
        inventory_state=inventory,
        context=_context(),
    ).unwrap()
    inventory = _grant(
        inventory_engine,
        equipped_head.inventory,
        "grant-new-head",
        GrantInstance(
            "head-new",
            "item.equipment.sustain_head",
            "bag",
            _receipt("receipt-head-new"),
        ),
    )
    return loadout_engine, equipped_head.loadout, inventory


def _assert_foundation_shapes(env: dict[str, object]) -> None:
    assert LOADOUT_FOUNDATION_VERSION == "loadout.foundation.v2"
    assert WEAPON_FOUNDATION_VERSION == "weapon.foundation.v5"
    assert EQUIPMENT_FOUNDATION_VERSION == "equipment.foundation.v4"
    slots = env["slots"]
    assert len(slots.definitions.ids()) == 7  # type: ignore[union-attr]


def _assert_multi_loadout_switch_is_atomic(env: dict[str, object]) -> None:
    engine, loadout, inventory = _prepared_loadout(env)
    presets = {
        "loadout_preset.a": LoadoutPreset("loadout_preset.a", loadout.slots),
        "loadout_preset.b": LoadoutPreset(
            "loadout_preset.b",
            {WEAPON_SLOT_ID: "weapon-new", HEAD_SLOT_ID: "head-new"},
        ),
    }
    loadout = LoadoutState(
        loadout.character_id,
        loadout.slots,
        loadout.revision,
        presets,
        "loadout_preset.a",
    )
    changed = engine.execute(
        _loadout_transaction(
            loadout,
            "activate-preset-b",
            ActivateLoadoutPreset("loadout_preset.b"),
        ),
        loadout=loadout,
        inventory_state=inventory,
        context=_context(72),
    ).unwrap()
    assert changed.loadout.active_preset_id == "loadout_preset.b"
    assert changed.loadout.weapon_asset_id == "weapon-new"
    assert changed.inventory.instances["weapon-old"].container_id == "bag"
    containers = dict(changed.inventory.containers)
    containers["bag"] = replace(containers["bag"], maximum_assets=3)
    editable_inventory = replace(changed.inventory, containers=containers)

    unequipped = engine.execute(
        _loadout_transaction(
            changed.loadout,
            "edit-active-preset-b",
            UnequipSlot(HEAD_SLOT_ID),
        ),
        loadout=changed.loadout,
        inventory_state=editable_inventory,
        context=_context(71),
    ).unwrap()
    assert unequipped.loadout.active_preset_id == "loadout_preset.b"
    assert HEAD_SLOT_ID not in unequipped.loadout.presets["loadout_preset.b"].slots

    restored_head = engine.execute(
        _loadout_transaction(
            unequipped.loadout,
            "restore-active-preset-b-head",
            EquipAsset(HEAD_SLOT_ID, "head-new"),
        ),
        loadout=unequipped.loadout,
        inventory_state=unequipped.inventory,
        context=_context(75),
    ).unwrap()
    assert restored_head.loadout.presets["loadout_preset.b"].slots[HEAD_SLOT_ID] == "head-new"

    restored = engine.execute(
        _loadout_transaction(
            restored_head.loadout,
            "activate-preset-a",
            ActivateLoadoutPreset("loadout_preset.a"),
        ),
        loadout=restored_head.loadout,
        inventory_state=restored_head.inventory,
        context=_context(73),
    ).unwrap()
    assert restored.loadout.weapon_asset_id == "weapon-old"
    assert restored.loadout.slots[HEAD_SLOT_ID] == "head-old"
    assert restored.inventory.instances["weapon-old"].container_id == "equipped"
    assert restored.inventory.instances["weapon-new"].container_id == "bag"

    try:
        LoadoutState(
            restored.loadout.character_id,
            restored.loadout.slots,
            presets={
                "loadout_preset.a": restored.loadout.presets["loadout_preset.a"],
                "loadout_preset.duplicate": LoadoutPreset(
                    "loadout_preset.duplicate",
                    {WEAPON_SLOT_ID: "weapon-old"},
                ),
            },
            active_preset_id="loadout_preset.a",
        )
        raise AssertionError("同一个资产不能跨配装复用")
    except ValueError as exc:
        assert "多套配装" in str(exc)

    bad_presets = dict(restored.loadout.presets)
    bad_presets["loadout_preset.bad"] = LoadoutPreset(
        "loadout_preset.bad",
        {HEAD_SLOT_ID: "missing-head"},
    )
    corrupted_target = LoadoutState(
        restored.loadout.character_id,
        restored.loadout.slots,
        restored.loadout.revision,
        bad_presets,
        restored.loadout.active_preset_id,
    )
    rejected = engine.execute(
        _loadout_transaction(
            corrupted_target,
            "activate-missing-preset-asset",
            ActivateLoadoutPreset("loadout_preset.bad"),
        ),
        loadout=corrupted_target,
        inventory_state=restored.inventory,
        context=_context(74),
    )
    assert rejected.failure and rejected.failure.code == "loadout.instance_unknown"
    assert corrupted_target.slots == restored.loadout.slots
    assert restored.inventory.instances["weapon-old"].container_id == "equipped"


def _assert_set_bonuses_are_separate(env: dict[str, object]) -> None:
    equipment = env["equipment"]
    assert isinstance(equipment, EquipmentCatalog)
    provider = EquipmentContributionProvider(equipment)
    head = EquipmentState(
        "set-head",
        "equipment.combo_head",
        "quality.common",
        set_id="equipment_set.combo",
    )
    body = EquipmentState(
        "set-body",
        "equipment.combo_body",
        "quality.common",
        set_id="equipment_set.combo",
    )
    assert provider.set_contributions((head,)) == ()
    bonuses = provider.set_contributions((head, body))
    assert len(bonuses) == 1
    assert bonuses[0].contribution.tags.has("equipment.set.combo.active")
    assert not provider.contribution(head).contribution.tags.has("equipment.set.combo.active")


def _assert_atomic_equip_and_full_container_replace(env: dict[str, object]) -> None:
    engine, loadout, inventory = _prepared_loadout(env)
    assert len([asset for asset in inventory.instances.values() if asset.container_id == "bag"]) == 2
    rejected = engine.execute(
        _loadout_transaction(
            loadout,
            "head-cannot-enter-body",
            EquipAsset(BODY_SLOT_ID, "head-new"),
        ),
        loadout=loadout,
        inventory_state=inventory,
        context=_context(),
    )
    assert rejected.failure and rejected.failure.code == "loadout.slot_rejected"
    assert loadout.slots[HEAD_SLOT_ID] == "head-old"
    assert inventory.instances["head-new"].container_id == "bag"

    replaced = engine.execute(
        _loadout_transaction(
            loadout,
            "replace-head-in-full-bag",
            EquipAsset(HEAD_SLOT_ID, "head-new"),
        ),
        loadout=loadout,
        inventory_state=inventory,
        context=_context(),
    ).unwrap()
    assert replaced.loadout.slots[HEAD_SLOT_ID] == "head-new"
    assert replaced.inventory.instances["head-new"].container_id == "equipped"
    assert replaced.inventory.instances["head-old"].container_id == "bag"
    assert len([asset for asset in replaced.inventory.instances.values() if asset.container_id == "bag"]) == 2
    kinds = [event.kind for event in replaced.events]
    assert kinds.count("inventory.item.swapped") == 2
    assert kinds[-1] == "loadout.asset.replaced"


def _assert_weapon_growth_and_contributions(env: dict[str, object]) -> None:
    weapons = env["weapons"]
    assert isinstance(weapons, WeaponCatalog)
    state = weapons.create_state(
        asset_id="weapon-old",
        definition_id="weapon.wind_blade",
        quality_id="quality.common",
    )
    context = _context(71)
    engine = WeaponEngine(weapons)
    grown = engine.grant_experience(
        WeaponExperienceTransaction(
            "weapon-exp-1",
            "character-a",
            state.revision,
            150,
            "source.battle_reward",
            "battle-9",
        ),
        state=state,
        context=context,
    ).unwrap()
    assert grown.state.level == 2
    assert grown.state.experience == 0
    assert grown.state.total_experience == 100
    assert grown.events[-1].kind == "weapon.experience.discarded"
    contribution = WeaponContributionProvider(weapons).contribution(grown.state)
    attack = next(
        value
        for value in contribution.contribution.attributes
        if value.attribute_id == COMBAT_ATTACK
    )
    assert attack.value == 20

    stale = engine.grant_experience(
        WeaponExperienceTransaction(
            "weapon-exp-stale",
            "character-a",
            0,
            1,
            "source.battle_reward",
            "battle-stale",
        ),
        state=grown.state,
        context=_context(),
    )
    assert stale.failure and stale.failure.code == "weapon.revision_conflict"


def _assert_equipment_has_no_growth_axis(env: dict[str, object]) -> None:
    equipment = env["equipment"]
    assert isinstance(equipment, EquipmentCatalog)
    state = equipment.create_state(
        asset_id="head-new",
        definition_id="equipment.sustain_head",
        quality_id="quality.rare",
    )
    assert not hasattr(state, "level")
    assert not hasattr(state, "experience")
    contribution = EquipmentContributionProvider(equipment).contribution(state)
    health = next(
        value
        for value in contribution.contribution.attributes
        if value.attribute_id == HEALTH_MAXIMUM
    )
    assert health.value == 40
    assert contribution.contribution.tags.has("equipment.family.sustain")


def _assert_only_equipped_assets_are_projected(env: dict[str, object]) -> None:
    engine, loadout, inventory = _prepared_loadout(env)
    replaced = engine.execute(
        _loadout_transaction(
            loadout,
            "replace-for-projection",
            EquipAsset(HEAD_SLOT_ID, "head-new"),
        ),
        loadout=loadout,
        inventory_state=inventory,
        context=_context(),
    ).unwrap()
    weapons = env["weapons"]
    equipment = env["equipment"]
    assert isinstance(weapons, WeaponCatalog)
    assert isinstance(equipment, EquipmentCatalog)
    weapon_states = {
        "weapon-old": WeaponEngine(weapons).grant_experience(
            WeaponExperienceTransaction(
                "weapon-exp-projection",
                "character-a",
                0,
                150,
                "source.battle_reward",
                "battle-10",
            ),
            state=weapons.create_state(
                asset_id="weapon-old",
                definition_id="weapon.wind_blade",
                quality_id="quality.common",
            ),
            context=_context(),
        ).unwrap().state,
        "weapon-new": weapons.create_state(
            asset_id="weapon-new",
            definition_id="weapon.wind_blade",
            quality_id="quality.rare",
        ),
    }
    equipment_states = {
        "head-old": equipment.create_state(
            asset_id="head-old",
            definition_id="equipment.combo_head",
            quality_id="quality.common",
        ),
        "head-new": equipment.create_state(
            asset_id="head-new",
            definition_id="equipment.sustain_head",
            quality_id="quality.rare",
        ),
    }
    weapon_provider = WeaponContributionProvider(weapons)
    equipment_provider = EquipmentContributionProvider(equipment)

    def resolve(asset_id: str):
        if asset_id in weapon_states:
            return weapon_provider.contribution(weapon_states[asset_id])
        return equipment_provider.contribution(equipment_states[asset_id])

    contributions = LoadoutContributionAssembler().assemble(replaced.loadout, resolve)
    assert [value.source_id for value in contributions] == ["weapon-old", "head-new"]

    characters = CharacterCatalog()
    characters.templates.register(
        CharacterTemplateDefinition(
            "character_template.standard",
            {
                HEALTH_MAXIMUM: 100,
                SPIRIT_MAXIMUM: 50,
                COMBAT_ATTACK: 5,
                COMBAT_DEFENSE: 10,
                COMBAT_SPEED: 5,
            },
        )
    )
    characters.finalize()
    character = characters.create_character(
        character_id="character-a",
        account_id="account-a",
        name="装配测试角色",
        template_id="character_template.standard",
        created_at=TIME,
    )
    attributes = core_attribute_definitions()
    attributes[CRITICAL_CHANCE] = AttributeDefinition(CRITICAL_CHANCE, default=0)
    projector = CharacterProjector(
        characters,
        AttributeResolver(attributes),
        persistent_resource_definitions(),
    )
    projection = projector.project(character, contributions=contributions)
    snapshot = projection.entity.snapshot(projector.attributes)
    assert snapshot.value(COMBAT_ATTACK) == 25
    assert snapshot.value(HEALTH_MAXIMUM) == 140
    assert snapshot.value(CRITICAL_CHANCE) == 0
    assert projection.entity.tags.has("weapon.tempo.fast")
    assert projection.entity.tags.has("equipment.family.sustain")


if __name__ == "__main__":
    main()
