"""定相尘回收、套装图纸兑换与定向装备生成验收。"""

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
from game.content.catalog.economy import (  # noqa: E402
    EQUIPMENT_SET_BLUEPRINT_PRICE,
    MARKET_ITEM_POLICIES,
)
from game.content.catalog.item import (  # noqa: E402
    EQUIPMENT_SET_BLUEPRINT_COMPONENT_ID,
    EXCHANGE_MATERIAL_ITEM_ID,
    PARTY_BOSS_TROPHY_ITEMS,
    REGULAR_ENEMY_TROPHY_ITEMS,
    EquipmentSetBlueprintItemComponent,
)
from game.core.account import ExternalIdentity, IdentityEvidence  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    GrantStack,
    InventoryState,
    InventoryTransaction,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    SourceReceipt,
    equipment_state_from_instance,
)
from game.core.persistence import INVENTORY_AGGREGATE  # noqa: E402


TIME = datetime(2026, 7, 23, tzinfo=timezone.utc)


def main() -> None:
    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "exchange.db",
            identity_secret="covenant-exchange-test-secret",
        )
        services.database.initialize()
        character = _create_character(services)
        set_ids = services.content.catalog.equipment.sets.ids()
        missing = services.covenant_exchange.redeem_blueprint(
            character.id,
            set_ids[0],
            "exchange:test:missing",
            logical_time=TIME,
        )
        assert missing.status == "material_missing"
        assert services.covenant_exchange.material_balance(character.id) == 0
        assert not services.covenant_exchange.history(character.id).records

        trophy = PARTY_BOSS_TROPHY_ITEMS[9]
        _grant_stack(
            services,
            character.id,
            "stack:party-trophy",
            str(trophy.id),
            1,
            "container.backpack",
        )
        regular_trophy = REGULAR_ENEMY_TROPHY_ITEMS[0]
        _grant_stack(
            services,
            character.id,
            "stack:regular-trophy",
            str(regular_trophy.id),
            1,
            "container.backpack",
        )

        recycled = services.economy.recycle_trophies(character.id, logical_time=TIME)
        assert recycled.status == "recycled"
        assert recycled.quote.total_amount > 0
        assert recycled.quote.stack_item_totals == {EXCHANGE_MATERIAL_ITEM_ID: 100}
        assert services.covenant_exchange.material_balance(character.id) == 100

        set_id = set_ids[0]
        exchanged = services.covenant_exchange.redeem_blueprint(
            character.id,
            set_id,
            "exchange:test:first",
            logical_time=TIME,
        )
        assert exchanged.status == "redeemed" and exchanged.receipt is not None
        assert exchanged.receipt.material_quantity == EQUIPMENT_SET_BLUEPRINT_PRICE
        assert services.covenant_exchange.material_balance(character.id) == 37
        inventory = _inventory(services, character.id)
        blueprint = inventory.stacks[exchanged.receipt.blueprint_asset_id]
        component = services.content.catalog.items.require(blueprint.definition_id).component(
            EQUIPMENT_SET_BLUEPRINT_COMPONENT_ID,
            EquipmentSetBlueprintItemComponent,
        )
        assert component.target_set_id == set_id
        assert blueprint.definition_id in MARKET_ITEM_POLICIES
        exchange_replay = services.covenant_exchange.redeem_blueprint(
            character.id,
            set_id,
            "exchange:test:first",
            logical_time=TIME,
        )
        assert exchange_replay.status == "replayed"
        assert services.covenant_exchange.material_balance(character.id) == 37
        assert len(services.covenant_exchange.history(character.id).records) == 1

        generated = services.equipment_blueprints.use(
            character.id,
            blueprint.id,
            "blueprint:test:first",
            logical_time=TIME,
        )
        assert generated.status == "generated" and generated.receipt is not None
        inventory = _inventory(services, character.id)
        assert blueprint.id not in inventory.stacks
        equipment = inventory.instances[generated.receipt.equipment_asset_id]
        state = equipment_state_from_instance(equipment)
        assert state.set_id == set_id
        assert state.roll is not None and state.quality_id == generated.receipt.quality_id

        replayed = services.equipment_blueprints.use(
            character.id,
            blueprint.id,
            "blueprint:test:first",
            logical_time=TIME,
        )
        assert replayed.status == "replayed" and replayed.receipt is not None
        assert replayed.receipt.equipment_asset_id == equipment.id
        assert len(services.covenant_exchange.history(character.id).records) == 1

        _grant_stack(
            services,
            character.id,
            "stack:exchange-material:second",
            EXCHANGE_MATERIAL_ITEM_ID,
            EQUIPMENT_SET_BLUEPRINT_PRICE - 37,
            "container.special",
        )
        second_exchange = services.covenant_exchange.redeem_blueprint(
            character.id,
            set_ids[1],
            "exchange:test:second",
            logical_time=TIME,
        )
        assert second_exchange.status == "redeemed" and second_exchange.receipt is not None
        second_blueprint_id = second_exchange.receipt.blueprint_asset_id

        original_generator = services.equipment_blueprints.generator
        services.equipment_blueprints.generator = _FailingEquipmentGenerator()
        try:
            generation_failed = services.equipment_blueprints.use(
                character.id,
                second_blueprint_id,
                "blueprint:test:generation-failed",
                logical_time=TIME,
            )
        finally:
            services.equipment_blueprints.generator = original_generator
        assert generation_failed.status == "generation_failed"
        assert second_blueprint_id in _inventory(services, character.id).stacks

        _fill_armory(services, character.id)
        inventory_rejected = services.equipment_blueprints.use(
            character.id,
            second_blueprint_id,
            "blueprint:test:armory-full",
            logical_time=TIME,
        )
        assert inventory_rejected.status == "inventory_rejected"
        final_inventory = _inventory(services, character.id)
        assert second_blueprint_id in final_inventory.stacks
        assert "blueprint-equipment:blueprint:test:armory-full" not in final_inventory.instances

        blueprint_targets = {
            definition.component(
                EQUIPMENT_SET_BLUEPRINT_COMPONENT_ID,
                EquipmentSetBlueprintItemComponent,
            ).target_set_id
            for definition in services.content.catalog.items.definitions
            if EQUIPMENT_SET_BLUEPRINT_COMPONENT_ID in definition.components
        }
        assert blueprint_targets == set(services.content.catalog.equipment.sets.ids())
    print("covenant exchange tests passed")


def _create_character(services):
    evidence = IdentityEvidence(
        "evidence:exchange",
        ExternalIdentity(
            "platform.local",
            "exchange-test",
            "identity.user",
            "private",
            "exchange-user",
        ),
        (),
        "message.local",
        TIME,
    )
    result = services.create_character(evidence, requested_name="兑换测试")
    assert result.status == "created" and result.receipt is not None
    return result.receipt.character


def _grant_stack(services, owner_id, asset_id, definition_id, quantity, container_kind):
    with services.database.unit_of_work() as uow:
        inventory = services.economy.snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            owner_id,
            InventoryState,
        )
        container = next(
            value for value in inventory.containers.values() if value.kind == container_kind
        )
        outcome = services.inventory_engine.execute(
            InventoryTransaction(
                f"grant:{asset_id}",
                owner_id,
                "inventory.test_grant",
                (
                    GrantStack(
                        asset_id,
                        definition_id,
                        container.id,
                        quantity,
                        SourceReceipt(
                            f"receipt:{asset_id}",
                            "source.test",
                            asset_id,
                            TIME,
                        ),
                    ),
                ),
            ),
            state=inventory,
            context=_context(f"grant:{asset_id}"),
        )
        assert outcome.ok and outcome.value is not None, outcome.failure
        services.economy.snapshots.update(
            uow,
            INVENTORY_AGGREGATE,
            owner_id,
            inventory,
            outcome.value.state,
            TIME,
        )
        uow.commit()


def _inventory(services, owner_id):
    with services.database.unit_of_work(write=False) as uow:
        return services.economy.snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            owner_id,
            InventoryState,
        )


class _FailingEquipmentGenerator:
    def generate(self, *args, **kwargs):
        raise ValueError("test generation failure")


def _fill_armory(services, owner_id: str) -> None:
    with services.database.unit_of_work() as uow:
        inventory = services.economy.snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            owner_id,
            InventoryState,
        )
        armory = next(
            value for value in inventory.containers.values()
            if value.kind == "container.armory"
        )
        armory_asset_count = sum(
            value.container_id == armory.id
            for value in inventory.instances.values()
        ) + sum(
            value.container_id == armory.id
            for value in inventory.stacks.values()
        )
        containers = dict(inventory.containers)
        containers[armory.id] = replace(
            armory,
            maximum_assets=max(1, armory_asset_count),
        )
        filled = replace(
            inventory,
            containers=containers,
            revision=inventory.revision + 1,
        )
        services.economy.snapshots.update(
            uow,
            INVENTORY_AGGREGATE,
            owner_id,
            inventory,
            filled,
            TIME,
        )
        uow.commit()


def _context(trace_id: str):
    return RuleContext(
        trace_id,
        "rules.covenant_exchange_test.v1",
        Ruleset("ruleset.covenant_exchange_test"),
        TIME,
        SeededRandomSource(trace_id),
    )


if __name__ == "__main__":
    main()
