"""随机武器上限、成长约束和两件武器成长道具测试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.content import (  # noqa: E402
    COMMON_QUALITY_ID,
    STARTER_WEAPON_ID,
    WEAPON_EXPERIENCE_ITEM_ID,
    WEAPON_MAXIMUM_LEVEL_ITEM_ID,
    assemble_official_catalog,
)
from game.content.catalog.weapon.mechanics import WEAPON_MAXIMUM_LEVEL_TABLE  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    InventoryEngine,
    InventoryState,
    ItemContainer,
    ItemInstance,
    ItemStack,
    ProvenanceLot,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    SourceReceipt,
    WeaponEngine,
    WeaponItemUseCommand,
    WeaponState,
    weapon_state_data,
    weapon_state_from_instance,
)
from game.rules.weapon import WeaponGenerationRequest, WeaponInstanceGenerator  # noqa: E402
from game.core.persistence import (  # noqa: E402
    INVENTORY_AGGREGATE,
    WEAPON_AGGREGATE,
    PersistedWeaponItemUseService,
    SnapshotRepository,
    SqliteDatabase,
)


TIME = datetime(2026, 7, 19, 15, 0, tzinfo=timezone.utc)


def main() -> None:
    catalog = assemble_official_catalog()
    _assert_probability_table()

    definition_id = next(
        value
        for value in catalog.weapons.definitions.ids()
        if catalog.weapons.require(value).generation_profile_id is not None
    )
    generated = WeaponInstanceGenerator(
        catalog.weapons,
        catalog.itemization_engine,
        WEAPON_MAXIMUM_LEVEL_TABLE,
    ).generate(
        WeaponGenerationRequest(
            "weapon-growth-generate",
            "weapon-growth-target",
            definition_id,
            catalog.report.content_fingerprint,
        ),
        context=_context("weapon-growth-generate", 117),
    ).state
    assert generated.level == 1 and generated.experience == 0
    assert 20 <= generated.natural_maximum_level <= 100
    assert generated.maximum_level == generated.natural_maximum_level
    assert generated.maximum_level_roll is not None
    assert generated.maximum_level_roll.sampled_level == generated.natural_maximum_level
    assert generated.maximum_level < 100, "测试种子应产出可提升上限的武器"

    starter = catalog.weapons.create_state(
        asset_id="starter",
        definition_id=STARTER_WEAPON_ID,
        quality_id=COMMON_QUALITY_ID,
    )
    assert starter.level == starter.maximum_level == starter.natural_maximum_level == 1

    receipt = SourceReceipt("receipt:test", "source.test", "weapon-growth", TIME)
    special_container = ItemContainer("special", "container.special", "character-a")
    armory_container = ItemContainer("armory", "container.armory", "character-a")
    inventory = InventoryState(
        containers={
            special_container.id: special_container,
            armory_container.id: armory_container,
        },
        stacks={
            "stack:max": ItemStack(
                "stack:max",
                WEAPON_MAXIMUM_LEVEL_ITEM_ID,
                special_container.id,
                (ProvenanceLot(receipt, 2),),
            ),
            "stack:level": ItemStack(
                "stack:level",
                WEAPON_EXPERIENCE_ITEM_ID,
                special_container.id,
                (ProvenanceLot(receipt, 2),),
            ),
        },
        instances={
            generated.asset_id: ItemInstance(
                generated.asset_id,
                catalog.weapons.require(generated.definition_id).item_definition_id,
                armory_container.id,
                receipt,
                weapon_state_data(generated),
            )
        },
    )
    with TemporaryDirectory() as directory:
        database = SqliteDatabase(Path(directory) / "weapon-growth.db")
        database.initialize()
        snapshots = SnapshotRepository()
        with database.unit_of_work() as uow:
            snapshots.insert(uow, INVENTORY_AGGREGATE, "character-a", inventory, TIME)
            snapshots.insert(uow, WEAPON_AGGREGATE, generated.asset_id, generated, TIME)
            uow.commit()
        service = PersistedWeaponItemUseService(
            database,
            catalog.items,
            InventoryEngine(catalog.items),
            WeaponEngine(catalog.weapons),
            snapshots,
        )

        maximum_receipt = service.use(
            WeaponItemUseCommand(
                "weapon-item-max",
                "character-a",
                "stack:max",
                generated.asset_id,
            ),
            inventory_id="character-a",
            context=_context("weapon-item-max", 118),
        ).unwrap()
        maximum_inventory, maximum_weapon = _load_states(
            database, snapshots, generated.asset_id
        )
        assert maximum_receipt.maximum_level_after == generated.maximum_level + 1
        assert maximum_weapon.natural_maximum_level == generated.natural_maximum_level
        assert maximum_inventory.stacks["stack:max"].quantity == 1
        assert weapon_state_from_instance(
            maximum_inventory.instances[generated.asset_id]
        ) == maximum_weapon

        level_receipt = service.use(
            WeaponItemUseCommand(
                "weapon-item-level",
                "character-a",
                "stack:level",
                generated.asset_id,
            ),
            inventory_id="character-a",
            context=_context("weapon-item-level", 119),
        ).unwrap()
        level_inventory, level_weapon = _load_states(
            database, snapshots, generated.asset_id
        )
        assert level_receipt.level_after == maximum_weapon.level + 1
        assert level_weapon.experience == 0
        assert level_weapon.total_experience > maximum_weapon.total_experience
        assert level_inventory.stacks["stack:level"].quantity == 1

        capped = replace(
            level_weapon,
            level=level_weapon.maximum_level,
            experience=0,
            revision=level_weapon.revision + 1,
        )
        instance = level_inventory.instances[generated.asset_id]
        instances = dict(level_inventory.instances)
        instances[generated.asset_id] = replace(
            instance,
            data=weapon_state_data(capped),
            revision=instance.revision + 1,
        )
        capped_inventory = replace(
            level_inventory,
            instances=instances,
            revision=level_inventory.revision + 1,
        )
        with database.unit_of_work() as uow:
            snapshots.update(
                uow,
                INVENTORY_AGGREGATE,
                "character-a",
                level_inventory,
                capped_inventory,
                TIME,
            )
            snapshots.update(
                uow,
                WEAPON_AGGREGATE,
                generated.asset_id,
                level_weapon,
                capped,
                TIME,
            )
            uow.commit()
        failure = service.use(
            WeaponItemUseCommand(
                "weapon-item-level-at-cap",
                "character-a",
                "stack:level",
                generated.asset_id,
            ),
            inventory_id="character-a",
            context=_context("weapon-item-level-at-cap", 120),
        )
        assert failure.failure is not None
        assert failure.failure.code == "weapon.maximum_level_reached"
        final_inventory, _ = _load_states(database, snapshots, generated.asset_id)
        assert final_inventory.stacks["stack:level"].quantity == 1
    print("weapon growth item tests passed")


def _assert_probability_table() -> None:
    assert tuple(
        (value.minimum, value.maximum, value.weight)
        for value in WEAPON_MAXIMUM_LEVEL_TABLE.bands
    ) == (
        (20, 40, 450),
        (41, 60, 280),
        (61, 80, 180),
        (81, 90, 60),
        (91, 99, 25),
        (100, 100, 5),
    )
    assert WEAPON_MAXIMUM_LEVEL_TABLE.total_weight == 1000


def _load_states(database, snapshots, weapon_id):
    with database.unit_of_work(write=False) as uow:
        return (
            snapshots.require(uow, INVENTORY_AGGREGATE, "character-a", InventoryState),
            snapshots.require(uow, WEAPON_AGGREGATE, weapon_id, WeaponState),
        )


def _context(trace_id: str, seed: int) -> RuleContext:
    return RuleContext(
        trace_id,
        "rule.weapon_growth_test",
        Ruleset("ruleset.weapon_growth_test"),
        TIME,
        SeededRandomSource(seed),
    )


if __name__ == "__main__":
    main()
