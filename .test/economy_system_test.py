"""统一估价、系统回收、二手市场和税务闭环测试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services  # noqa: E402
from game.content.catalog.item import SMALL_HEALTH_MEDICINE_ITEM_ID  # noqa: E402
from game.content.catalog.weapon.mechanics import WEAPON_MAXIMUM_LEVEL_TABLE  # noqa: E402
from game.core.account import ExternalIdentity, IdentityEvidence  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    GrantInstance,
    InventoryState,
    InventoryTransaction,
    IssueFunds,
    LedgerState,
    LedgerTransaction,
    LoadoutState,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    SourceReceipt,
    equipment_state_data,
    weapon_state_data,
)
from game.core.persistence import (  # noqa: E402
    INVENTORY_AGGREGATE,
    LEDGER_AGGREGATE,
    LOADOUT_AGGREGATE,
)
from game.rules import (  # noqa: E402
    EquipmentGenerationRequest,
    EquipmentInstanceGenerator,
    WeaponGenerationRequest,
    WeaponInstanceGenerator,
)
from game.rules.character import (  # noqa: E402
    PRIMARY_ISSUER_ACCOUNT_ID,
    PRIMARY_LEDGER_ID,
)
from game.rules.economy import quote_market_tax  # noqa: E402


TIME = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)


def main() -> None:
    _assert_tax_policy()
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "economy.db"
        services = build_game_services(
            database_path=database_path,
            identity_secret="economy-system-secret",
        )
        services.database.initialize()
        services.economy.initialize(logical_time=TIME)
        seller = _create_character(services, "seller", "Seller")
        buyer = _create_character(services, "buyer", "Buyer")
        first = _grant_equipment(services, seller.id, "gear-recycle", seed=11)
        second = _grant_equipment(services, seller.id, "gear-market", seed=23)
        third = _grant_equipment(services, seller.id, "gear-cancel", seed=37)
        protected = _grant_equipment(services, seller.id, "gear-protected", seed=51)
        cherished = _grant_equipment(services, seller.id, "gear-cherished", seed=51)
        batch_candidate = _grant_equipment(services, seller.id, "gear-batch", seed=51)
        old_recycle_quote = services.economy.quote_recycle_assets(
            seller.id,
            (cherished.id,),
        )
        old_listing_quote = services.economy.quote_listing(
            seller.id,
            seller.name,
            cherished.id,
            2_000,
        )
        assert old_recycle_quote.quote is not None
        assert old_listing_quote.quote is not None
        revision_before = _inventory(services, seller.id).revision
        protected_result = services.inventory_protection.set_protected(
            seller.id,
            cherished.id,
            True,
            context=_context("protect:gear-cherished", 52),
        )
        assert protected_result.ok and protected_result.value is not None
        assert protected_result.value.changed
        protected_revision = _inventory(services, seller.id).revision
        assert protected_revision == revision_before + 1
        repeated = services.inventory_protection.set_protected(
            seller.id,
            cherished.id,
            True,
            context=_context("protect:gear-cherished-again", 53),
        )
        assert repeated.ok and repeated.value is not None
        assert not repeated.value.changed
        assert _inventory(services, seller.id).revision == protected_revision

        reloaded = build_game_services(
            database_path=database_path,
            identity_secret="economy-system-secret",
        )
        reloaded.database.initialize()
        assert _inventory(reloaded, seller.id).is_protected(cherished.id)
        assert services.economy.quote_recycle_assets(
            seller.id,
            (cherished.id,),
        ).status == "rejected"
        assert services.economy.quote_listing(
            seller.id,
            seller.name,
            cherished.id,
            2_000,
        ).status == "rejected"
        assert services.economy.execute_recycle(
            seller.id,
            old_recycle_quote.quote,
            logical_time=TIME,
        ).status == "stale"
        assert services.economy.open_listing(
            seller.id,
            old_listing_quote.quote,
            logical_time=TIME,
        ).status == "stale"
        protected_price = services.economy.prices.quote(protected)
        _protect_in_inactive_preset(
            services,
            seller.id,
            protected_price.slot_id,
            protected.id,
        )
        batch_quote = services.economy.quote_recycle_batch(
            seller.id,
            protected_price.slot_id,
            frozenset({protected_price.quality_id}),
        )
        assert batch_quote.status == "quoted" and batch_quote.quote is not None
        batch_ids = {line.asset_id for line in batch_quote.quote.lines}
        assert batch_candidate.id in batch_ids
        assert protected.id not in batch_ids
        assert cherished.id not in batch_ids

        unprotected_result = services.inventory_protection.set_protected(
            seller.id,
            cherished.id,
            False,
            context=_context("unprotect:gear-cherished", 54),
        )
        assert unprotected_result.ok and unprotected_result.value is not None
        assert unprotected_result.value.changed
        assert services.economy.quote_recycle_assets(
            seller.id,
            (cherished.id,),
        ).status == "quoted"
        assert services.economy.quote_listing(
            seller.id,
            seller.name,
            cherished.id,
            2_000,
        ).status == "quoted"
        weapon = _grant_weapon(services, seller.id, "weapon-batch", seed=61, level=10)
        weapon_price = services.economy.prices.quote(weapon)
        weapon_state = weapon.data["weapon.state"]
        low_cap = replace(
            weapon_state,
            natural_maximum_level=20,
            maximum_level=20,
            maximum_level_roll=None,
        )
        high_cap = replace(low_cap, maximum_level=100)
        assert services.economy.prices.quote(
            replace(weapon, data=weapon_state_data(high_cap))
        ).reference_price > services.economy.prices.quote(
            replace(weapon, data=weapon_state_data(low_cap))
        ).reference_price
        level_quote = services.economy.quote_recycle_batch(
            seller.id,
            weapon_price.slot_id,
            frozenset({weapon_price.quality_id}),
            10,
        )
        assert level_quote.status == "quoted" and level_quote.quote is not None
        assert weapon.id in {line.asset_id for line in level_quote.quote.lines}
        excluded_quote = services.economy.quote_recycle_batch(
            seller.id,
            weapon_price.slot_id,
            frozenset({weapon_price.quality_id}),
            9,
        )
        assert excluded_quote.status == "rejected"
        equipment_level_rejected = services.economy.quote_recycle_batch(
            seller.id,
            protected_price.slot_id,
            frozenset({protected_price.quality_id}),
            10,
        )
        assert equipment_level_rejected.status == "rejected"

        recycle_quote = services.economy.quote_recycle_assets(seller.id, (first.id,))
        assert recycle_quote.status == "quoted" and recycle_quote.quote is not None
        assert recycle_quote.quote.total_amount * 4 <= recycle_quote.quote.total_reference_price
        seller_before = _wallet_balance(services, seller.id)
        recycled = services.economy.execute_recycle(
            seller.id,
            recycle_quote.quote,
            logical_time=TIME,
        )
        assert recycled.status == "recycled"
        assert _wallet_balance(services, seller.id) == seller_before + recycle_quote.quote.total_amount
        assert first.id not in _inventory(services, seller.id).instances

        listing_quote = services.economy.quote_listing(
            seller.id,
            seller.name,
            second.id,
            1,
        )
        assert listing_quote.status == "quoted" and listing_quote.quote is not None
        listed = services.economy.open_listing(
            seller.id,
            listing_quote.quote,
            logical_time=TIME,
        )
        assert listed.status == "listed" and listed.listing is not None
        assert _inventory(services, seller.id).reservations_for(second.id)

        _fund(services, buyer.id, 100_000)
        purchase_quote = services.economy.quote_purchase(
            buyer.id,
            listed.listing.id,
            logical_time=TIME,
        )
        assert purchase_quote.status == "quoted" and purchase_quote.quote is not None
        assert purchase_quote.quote.tax.low_price_surcharge > 0
        buyer_before = _wallet_balance(services, buyer.id)
        seller_before = _wallet_balance(services, seller.id)
        purchased = services.economy.purchase(
            buyer.id,
            purchase_quote.quote,
            logical_time=TIME,
        )
        assert purchased.status == "purchased"
        assert second.id not in _inventory(services, seller.id).instances
        transferred = _inventory(services, buyer.id).instances[second.id]
        assert transferred.data == second.data
        assert transferred.receipt == second.receipt
        assert transferred.revision == second.revision
        assert _wallet_balance(services, buyer.id) == buyer_before - purchase_quote.quote.tax.buyer_total
        assert _wallet_balance(services, seller.id) == seller_before + purchase_quote.quote.tax.seller_proceeds
        summary = services.economy.tax_summary(logical_time=TIME)
        assert summary.balance == purchase_quote.quote.tax.tax_amount
        assert summary.recent_tax == summary.balance and summary.recent_trades == 1

        seller_inventory = _inventory(services, seller.id)
        medicine = next(
            value
            for value in seller_inventory.stacks.values()
            if value.definition_id == SMALL_HEALTH_MEDICINE_ITEM_ID
        )
        medicine_quote = services.economy.quote_listing(
            seller.id,
            seller.name,
            medicine.id,
            30,
            2,
        )
        assert medicine_quote.status == "quoted" and medicine_quote.quote is not None
        assert medicine_quote.quote.price.reference_price == 24
        medicine_listing = services.economy.open_listing(
            seller.id,
            medicine_quote.quote,
            logical_time=TIME,
        )
        assert medicine_listing.status == "listed" and medicine_listing.listing is not None
        reservation = _inventory(services, seller.id).reservations_for(medicine.id)
        assert len(reservation) == 1 and reservation[0].quantity == 2
        medicine_purchase = services.economy.quote_purchase(
            buyer.id,
            medicine_listing.listing.id,
            logical_time=TIME,
        )
        assert medicine_purchase.quote is not None
        medicine_result = services.economy.purchase(
            buyer.id,
            medicine_purchase.quote,
            logical_time=TIME,
        )
        assert medicine_result.status == "purchased"
        assert medicine.id not in _inventory(services, seller.id).stacks
        transferred_stack = next(
            value
            for value in _inventory(services, buyer.id).stacks.values()
            if value.id == f"market-stack:{medicine_listing.listing.id}:{buyer.id}"
        )
        assert transferred_stack.quantity == 2
        assert transferred_stack.lots == medicine.lots
        assert _inventory(services, buyer.id).containers[transferred_stack.container_id].kind == "container.special"

        cancel_quote = services.economy.quote_listing(
            seller.id,
            seller.name,
            third.id,
            5_000,
        )
        assert cancel_quote.quote is not None
        cancel_listing = services.economy.open_listing(
            seller.id,
            cancel_quote.quote,
            logical_time=TIME,
        )
        assert cancel_listing.listing is not None
        cancelled = services.economy.cancel_listing(
            seller.id,
            cancel_listing.listing.id,
            logical_time=TIME,
        )
        assert cancelled.status == "cancelled"
        assert not _inventory(services, seller.id).reservations_for(third.id)

        expiring_asset = _grant_equipment(services, seller.id, "gear-expiring", seed=41)
        expiring_quote = services.economy.quote_listing(
            seller.id,
            seller.name,
            expiring_asset.id,
            2_000,
        )
        assert expiring_quote.quote is not None
        expiring = services.economy.open_listing(
            seller.id,
            expiring_quote.quote,
            logical_time=TIME,
        )
        assert expiring.listing is not None
        assert services.economy.expire_due(
            logical_time=TIME + timedelta(days=8),
        ) == 1
        assert not _inventory(services, seller.id).reservations_for(expiring_asset.id)
        assert not services.economy.listings(logical_time=TIME + timedelta(days=8))

    print("economy system tests passed")


def _assert_tax_policy() -> None:
    normal = quote_market_tax(1_000, 1_000)
    assert normal.normal_tax_rate_bps == 800
    assert normal.buyer_total == 1_000
    assert normal.seller_proceeds == 920
    assert normal.tax_amount == 80
    low = quote_market_tax(1_000, 100)
    assert low.buyer_total == 700 and low.low_price_surcharge == 600
    high = quote_market_tax(1_000, 10_000)
    assert high.high_price_tax == 8_500
    assert high.seller_proceeds == 1_380
    risky = quote_market_tax(
        1_000,
        1_000,
        repeated_pair_trades=10,
        repeated_asset_trades=10,
    )
    assert risky.normal_tax_rate_bps == 3_000
    assert risky.seller_proceeds == normal.seller_proceeds
    assert risky.risk_surcharge == 220
    assert risky.buyer_total == 1_220


def _create_character(services, external_id: str, name: str):
    evidence = IdentityEvidence(
        f"evidence:{external_id}",
        ExternalIdentity(
            "platform.local",
            "economy-test",
            "identity.user",
            "private",
            external_id,
        ),
        (),
        "message.local",
        TIME,
    )
    created = services.create_character(evidence, requested_name=name)
    assert created.status == "created" and created.receipt is not None
    return created.receipt.character


def _grant_equipment(services, owner_id: str, asset_id: str, *, seed: int):
    catalog = services.content.catalog
    definition_id = catalog.equipment.definitions.ids()[seed % len(catalog.equipment.definitions.ids())]
    generated = EquipmentInstanceGenerator(
        catalog.equipment,
        catalog.itemization_engine,
    ).generate(
        EquipmentGenerationRequest(
            f"generate:{asset_id}",
            asset_id,
            definition_id,
            catalog.report.content_fingerprint,
        ),
        context=_context(f"generate:{asset_id}", seed),
    )
    receipt = SourceReceipt(
        f"receipt:{asset_id}",
        "source.test",
        asset_id,
        TIME,
    )
    with services.database.unit_of_work() as uow:
        inventory = services.economy.snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            owner_id,
            InventoryState,
        )
        armory = next(
            value for value in inventory.containers.values() if value.kind == "container.armory"
        )
        outcome = services.economy.inventory_engine.execute(
            InventoryTransaction(
                f"grant:{asset_id}",
                owner_id,
                "inventory.test_grant",
                (
                    GrantInstance(
                        asset_id,
                        catalog.equipment.require(definition_id).item_definition_id,
                        armory.id,
                        receipt,
                        equipment_state_data(generated.state),
                    ),
                ),
            ),
            state=inventory,
            context=_context(f"grant:{asset_id}", seed),
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
    return _inventory(services, owner_id).instances[asset_id]


def _grant_weapon(services, owner_id: str, asset_id: str, *, seed: int, level: int):
    catalog = services.content.catalog
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
            f"generate:{asset_id}",
            asset_id,
            definition_id,
            catalog.report.content_fingerprint,
        ),
        context=_context(f"generate:{asset_id}", seed),
    )
    state = replace(generated.state, level=level)
    receipt = SourceReceipt(
        f"receipt:{asset_id}",
        "source.test",
        asset_id,
        TIME,
    )
    with services.database.unit_of_work() as uow:
        inventory = services.economy.snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            owner_id,
            InventoryState,
        )
        armory = next(
            value for value in inventory.containers.values() if value.kind == "container.armory"
        )
        outcome = services.economy.inventory_engine.execute(
            InventoryTransaction(
                f"grant:{asset_id}",
                owner_id,
                "inventory.test_grant",
                (
                    GrantInstance(
                        asset_id,
                        catalog.weapons.require(definition_id).item_definition_id,
                        armory.id,
                        receipt,
                        weapon_state_data(state),
                    ),
                ),
            ),
            state=inventory,
            context=_context(f"grant:{asset_id}", seed),
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
    return _inventory(services, owner_id).instances[asset_id]


def _fund(services, owner_id: str, amount: int) -> None:
    with services.database.unit_of_work() as uow:
        ledger = services.economy.snapshots.require(
            uow,
            LEDGER_AGGREGATE,
            PRIMARY_LEDGER_ID,
            LedgerState,
        )
        issuer = ledger.accounts[PRIMARY_ISSUER_ACCOUNT_ID]
        wallet = services.economy._wallet(ledger, owner_id)
        outcome = services.economy.ledger_engine.execute(
            LedgerTransaction(
                f"fund:{owner_id}",
                owner_id,
                "economy.test_fund",
                (IssueFunds(issuer.id, wallet.id, amount),),
                {issuer.id: issuer.revision, wallet.id: wallet.revision},
            ),
            state=ledger,
            context=_context(f"fund:{owner_id}", amount),
        )
        assert outcome.ok and outcome.value is not None, outcome.failure
        services.economy.snapshots.update(
            uow,
            LEDGER_AGGREGATE,
            PRIMARY_LEDGER_ID,
            ledger,
            outcome.value.state,
            TIME,
        )
        uow.commit()


def _inventory(services, owner_id: str) -> InventoryState:
    with services.database.unit_of_work(write=False) as uow:
        return services.economy.snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            owner_id,
            InventoryState,
        )


def _protect_in_inactive_preset(services, owner_id, slot_id, asset_id) -> None:
    with services.database.unit_of_work() as uow:
        loadout = services.economy.snapshots.require(
            uow,
            LOADOUT_AGGREGATE,
            owner_id,
            LoadoutState,
        )
        preset_id = next(
            value for value in loadout.presets if value != loadout.active_preset_id
        )
        presets = dict(loadout.presets)
        presets[preset_id] = replace(presets[preset_id], slots={slot_id: asset_id})
        updated = replace(loadout, presets=presets, revision=loadout.revision + 1)
        services.economy.snapshots.update(
            uow,
            LOADOUT_AGGREGATE,
            owner_id,
            loadout,
            updated,
            TIME,
        )
        uow.commit()


def _wallet_balance(services, owner_id: str) -> int:
    with services.database.unit_of_work(write=False) as uow:
        ledger = services.economy.snapshots.require(
            uow,
            LEDGER_AGGREGATE,
            PRIMARY_LEDGER_ID,
            LedgerState,
        )
    return services.economy._wallet(ledger, owner_id).balance


def _context(trace_id: str, seed: int) -> RuleContext:
    return RuleContext(
        trace_id,
        "rules.economy_test.v1",
        Ruleset("ruleset.economy_test"),
        TIME,
        SeededRandomSource(seed),
    )


if __name__ == "__main__":
    main()
