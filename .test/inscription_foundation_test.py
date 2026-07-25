"""铭刻三类目标、实例跟随、原名投影和持久化防重测试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay import (  # noqa: E402
    AssetInscriptionTarget,
    ContributionSpec,
    INSCRIPTION_DATA_KEY,
    INSCRIPTION_FOUNDATION_VERSION,
    INSCRIPTION_MEDIUM_DATA_KEY,
    InscriptionCommand,
    InscriptionEngine,
    InscriptionMediumData,
    InscriptionPreference,
    InscriptionProjector,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    TagSet,
    WeaponAbilityInscriptionTarget,
)
from game.core.gameplay.inventory import (  # noqa: E402
    InventoryState,
    ItemAssetKind,
    ItemCatalog,
    ItemComponentRegistry,
    ItemContainer,
    ItemDefinition,
    ItemInstance,
    SourceReceipt,
)
from game.core.gameplay.equipment import (  # noqa: E402
    EquipmentCatalog,
    EquipmentDefinition,
    EquipmentFamilyDefinition,
    EquipmentQualityProfile,
)
from game.core.gameplay.loadout import (  # noqa: E402
    HEAD_SLOT_ID,
    WEAPON_SLOT_ID,
    LoadoutItemComponent,
    QualityCatalog,
    QualityDefinition,
    register_loadout_item_component,
    standard_loadout_slot_catalog,
)
from game.core.gameplay.weapon import (  # noqa: E402
    WeaponCatalog,
    WeaponDefinition,
    WeaponQualityProfile,
    WeaponState,
)
from game.core.persistence import (  # noqa: E402
    INVENTORY_AGGREGATE,
    WEAPON_AGGREGATE,
    PersistedInscriptionService,
    SnapshotRepository,
    SqliteDatabase,
)


TIME = datetime(2026, 7, 13, 1, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
    assert INSCRIPTION_FOUNDATION_VERSION == "inscription.foundation.v1"
    engine, inventory, weapon_state = _fixture()
    inventory = _assert_weapon_name(engine, inventory, weapon_state)
    inventory = _assert_weapon_ability_name(engine, inventory, weapon_state)
    inventory = _assert_equipment_name(engine, inventory)
    _assert_failures_are_atomic(engine, inventory, weapon_state)
    _assert_persistence_replay()
    print("inscription foundation tests passed")


def _context(seed: int = 41) -> RuleContext:
    return RuleContext(
        f"inscription-test-{seed}",
        "rules.v1",
        Ruleset("ruleset.standard"),
        TIME,
        SeededRandomSource(seed),
    )


def _catalogs():
    components = ItemComponentRegistry()
    register_loadout_item_component(components)
    items = ItemCatalog(components)
    items.register(
        ItemDefinition(
            "item.weapon.training_blade",
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
            "item.equipment.training_head",
            ItemAssetKind.INSTANCE,
            tags=TagSet.of("item.equipment"),
            components={
                "item_component.loadout": LoadoutItemComponent(
                    frozenset({HEAD_SLOT_ID})
                )
            },
        )
    )
    items.register(
        ItemDefinition(
            "item.inscription.feather",
            ItemAssetKind.INSTANCE,
            tags=TagSet.of("item.inscription_medium"),
        )
    )
    qualities = QualityCatalog()
    quality = qualities.register(QualityDefinition("quality.common", 0))
    weapons = WeaponCatalog(qualities, items)
    weapons.register(
        WeaponDefinition(
            "weapon.training_blade",
            "item.weapon.training_blade",
            ContributionSpec(abilities=frozenset({"ability.weapon_slash"})),
            {
                quality.id: WeaponQualityProfile(
                    quality.id,
                    (),
                )
            },
        )
    )
    equipment = EquipmentCatalog(
        qualities,
        standard_loadout_slot_catalog(),
        items,
    )
    family = equipment.register_family(EquipmentFamilyDefinition("family.training"))
    equipment.register(
        EquipmentDefinition(
            "equipment.training_head",
            "item.equipment.training_head",
            HEAD_SLOT_ID,
            family.id,
            quality_profiles={
                quality.id: EquipmentQualityProfile(
                    quality.id,
                    ContributionSpec(),
                )
            },
        )
    )
    weapons.finalize()
    equipment.finalize()
    return items, weapons, equipment


def _fixture():
    items, weapons, equipment = _catalogs()
    receipt = SourceReceipt("source-1", "source.test", "test", TIME)
    containers = {
        "bag.player": ItemContainer("bag.player", "container.bag", "player.one"),
        "bag.other": ItemContainer("bag.other", "container.bag", "player.other"),
    }
    instances = {
        "weapon-1": ItemInstance(
            "weapon-1", "item.weapon.training_blade", "bag.player", receipt
        ),
        "equipment-1": ItemInstance(
            "equipment-1", "item.equipment.training_head", "bag.player", receipt
        ),
        "feather-1": _feather("feather-1", "旧桥挑灯客遗羽", containers, receipt),
        "feather-2": _feather("feather-2", "折柳渡青郎遗羽", containers, receipt),
        "feather-3": _feather("feather-3", "孤舟照月人遗羽", containers, receipt),
        "feather-4": _feather("feather-4", "无名旧愿遗羽", containers, receipt),
        "feather-other": ItemInstance(
            "feather-other",
            "item.inscription.feather",
            "bag.other",
            receipt,
            {
                INSCRIPTION_MEDIUM_DATA_KEY: InscriptionMediumData(
                    "他人遗羽", "这枚羽毛不属于当前玩家。"
                )
            },
        ),
    }
    inventory = InventoryState(
        containers,
        {},
        instances,
        {},
        0,
        protected_asset_ids=frozenset({"weapon-1", "equipment-1"}),
    )
    weapon_state = WeaponState(
        "weapon-1", "weapon.training_blade", "quality.common"
    )
    return InscriptionEngine(items, weapons, equipment), inventory, weapon_state


def _feather(asset_id, title, _containers, receipt):
    return ItemInstance(
        asset_id,
        "item.inscription.feather",
        "bag.player",
        receipt,
        {
            INSCRIPTION_MEDIUM_DATA_KEY: InscriptionMediumData(
                title,
                f"{title}散作微光前留下的一段旧愿。",
            )
        },
    )


def _apply(engine, inventory, command, weapon_state=None, seed=41):
    outcome = engine.apply(
        command,
        inventory=inventory,
        weapon_state=weapon_state,
        context=_context(seed),
    )
    assert outcome.ok and outcome.value, outcome.failure
    return outcome.value


def _assert_weapon_name(engine, inventory, weapon_state):
    result = _apply(
        engine,
        inventory,
        InscriptionCommand(
            "inscription-weapon",
            "player.one",
            AssetInscriptionTarget("weapon-1"),
            "feather-1",
            "青云剑",
            expected_inventory_revision=0,
            expected_asset_revision=0,
        ),
        weapon_state,
    )
    assert "feather-1" not in result.inventory.instances
    assert result.inventory.is_protected("weapon-1")
    weapon = result.inventory.instances["weapon-1"]
    assert weapon.revision == 1
    assert weapon.data[INSCRIPTION_DATA_KEY].asset_name == "青云剑"
    assert result.receipt.medium_title == "旧桥挑灯客遗羽"
    assert result.events[-1].kind == "inscription.applied"
    assert InscriptionProjector().asset_name("青岚短剑", weapon) == "青云剑（青岚短剑）"
    hidden = InscriptionProjector(InscriptionPreference("player.one", False))
    assert hidden.asset_name("青岚短剑", weapon) == "青云剑"

    moved = replace(weapon, container_id="bag.other", revision=weapon.revision + 1)
    assert InscriptionProjector().asset_name("青岚短剑", moved) == "青云剑（青岚短剑）"
    return result.inventory


def _assert_weapon_ability_name(engine, inventory, weapon_state):
    result = _apply(
        engine,
        inventory,
        InscriptionCommand(
            "inscription-ability",
            "player.one",
            WeaponAbilityInscriptionTarget("weapon-1", "ability.weapon_slash"),
            "feather-2",
            "青云斩",
        ),
        weapon_state,
        seed=42,
    )
    weapon = result.inventory.instances["weapon-1"]
    projector = InscriptionProjector()
    assert projector.weapon_ability_name(
        "风刃斩", weapon, "ability.weapon_slash"
    ) == "青云斩（风刃斩）"
    return result.inventory


def _assert_equipment_name(engine, inventory):
    result = _apply(
        engine,
        inventory,
        InscriptionCommand(
            "inscription-equipment",
            "player.one",
            AssetInscriptionTarget("equipment-1"),
            "feather-3",
            "青云冠",
        ),
        seed=43,
    )
    equipment = result.inventory.instances["equipment-1"]
    assert result.inventory.is_protected("equipment-1")
    assert InscriptionProjector().asset_name("云纹冠", equipment) == "青云冠（云纹冠）"
    return result.inventory


def _assert_failures_are_atomic(engine, inventory, weapon_state):
    before = inventory
    other_medium = InscriptionCommand(
        "inscription-other-medium",
        "player.one",
        AssetInscriptionTarget("weapon-1"),
        "feather-other",
        "照夜剑",
    )
    outcome = engine.apply(
        other_medium,
        inventory=inventory,
        weapon_state=weapon_state,
        context=_context(44),
    )
    assert outcome.failure and outcome.failure.code == "inscription.asset_not_owned"
    assert inventory == before and "feather-other" in inventory.instances

    invalid = InscriptionCommand(
        "inscription-invalid-ability",
        "player.one",
        WeaponAbilityInscriptionTarget("weapon-1", "ability.unknown"),
        "feather-4",
        "无名式",
    )
    outcome = engine.apply(
        invalid,
        inventory=inventory,
        weapon_state=weapon_state,
        context=_context(45),
    )
    assert outcome.failure and outcome.failure.code == "inscription.ability_not_owned"
    assert inventory == before and "feather-4" in inventory.instances


def _assert_persistence_replay():
    engine, inventory, weapon_state = _fixture()
    weapon_reference = inventory.reference_number("weapon-1")
    next_reference_number = inventory.next_reference_number
    with TemporaryDirectory() as directory:
        database = SqliteDatabase(Path(directory) / "inscription.db")
        database.initialize()
        snapshots = SnapshotRepository()
        with database.unit_of_work() as uow:
            snapshots.insert(uow, INVENTORY_AGGREGATE, "inventory.player", inventory, TIME)
            snapshots.insert(uow, WEAPON_AGGREGATE, "weapon-1", weapon_state, TIME)
            uow.commit()
        service = PersistedInscriptionService(database, engine, snapshots)
        command = InscriptionCommand(
            "persisted-inscription",
            "player.one",
            AssetInscriptionTarget("weapon-1"),
            "feather-1",
            "青云剑",
        )
        first = service.apply(
            command,
            inventory_id="inventory.player",
            context=_context(50),
        )
        assert first.ok and first.value and not first.value.replayed
        repeated = service.apply(
            command,
            inventory_id="inventory.player",
            context=_context(50),
        )
        assert repeated.ok and repeated.value and repeated.value.replayed
        with database.unit_of_work(write=False) as uow:
            stored = snapshots.require(
                uow,
                INVENTORY_AGGREGATE,
                "inventory.player",
                InventoryState,
            )
            assert stored.revision == 1
            assert "feather-1" not in stored.instances
            assert stored.reference_number("weapon-1") == weapon_reference
            assert stored.next_reference_number == next_reference_number
            assert stored.instances["weapon-1"].data[INSCRIPTION_DATA_KEY].asset_name == "青云剑"
            assert uow.pending_outbox(limit=10) == ()

        preference = service.initialize_preference("player.one", logical_time=TIME)
        assert preference.show_original_name
        hidden = service.set_show_original_name(
            "player.one", False, logical_time=TIME
        )
        assert not hidden.show_original_name and hidden.revision == 1
        restarted = PersistedInscriptionService(SqliteDatabase(database.path), engine)
        assert restarted.load_preference("player.one") == hidden


if __name__ == "__main__":
    main()
