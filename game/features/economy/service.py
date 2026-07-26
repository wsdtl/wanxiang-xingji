"""统一回收、归航市场和归航库的跨领域原子协调。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
import json

from game.content.catalog.economy import (
    ECONOMY_POLICY_ID,
    ECONOMY_POLICY_VERSION,
    MARKET_LISTING_LIFETIME_SECONDS,
    MARKET_MAX_SELLER_PRICE_BPS,
    MARKET_MIN_PRICE_BPS,
    MARKET_RISK_WINDOW_SECONDS,
)
from game.content.catalog.foundation import PRIMARY_CURRENCY_ID
from game.core.gameplay import (
    AssetAvailability,
    AppendStack,
    ConsumeInstance,
    ConsumeStack,
    DestroyAsset,
    FundAllocation,
    GrantInstance,
    GrantStack,
    InventoryState,
    InventoryTransaction,
    IssueFunds,
    LedgerAccount,
    LedgerAccountKind,
    LedgerState,
    LedgerTransaction,
    LoadoutState,
    ItemInstance,
    ItemStack,
    OpenLedgerAccount,
    ReleaseReservation,
    ReservationMode,
    ReserveAsset,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    SourceReceipt,
    SplitFunds,
    WEAPON_SLOT_ID,
    weapon_state_from_instance,
)
from game.rules.character import PRIMARY_ISSUER_ACCOUNT_ID, PRIMARY_LEDGER_ID
from game.rules.economy import (
    ECONOMY_RULESET_VERSION,
    MARKET_SCOPE_ID,
    PRIMARY_TAX_ACCOUNT_ID,
    PRIMARY_TAX_OWNER_ID,
    GearPriceService,
    MarketListing,
    MarketPriceQuote,
    MarketState,
    MarketTradeRecord,
    RecycleQuote,
    RecycleQuoteLine,
    quote_market_tax,
    recycle_amount,
)
from game.rules.item import quote_trophy_recycle

from .models import (
    EconomyStorageKinds,
    MarketListingQuote,
    MarketListingResult,
    MarketPurchaseQuote,
    MarketPurchaseResult,
    RecycleOperationResult,
    TaxSummary,
    TrophyRecycleResult,
)


class EconomyFeature:
    """价格由纯规则计算，玩法层只负责跨库存和账本的联合提交。"""

    def __init__(
        self,
        database,
        content,
        snapshots,
        inventory_engine,
        ledger_engine,
        storage: EconomyStorageKinds,
        *,
        market_item_policies,
    ) -> None:
        self.database = database
        self.content = content
        self.snapshots = snapshots
        self.inventory_engine = inventory_engine
        self.ledger_engine = ledger_engine
        self.storage = storage
        self.market_item_policies = market_item_policies
        self.prices = GearPriceService(content)

    def initialize(self, *, logical_time: datetime) -> MarketState:
        with self.database.unit_of_work() as uow:
            current = self.snapshots.load(
                uow,
                self.storage.market,
                MARKET_SCOPE_ID,
                MarketState,
            )
            if current is None:
                current = MarketState()
                self.snapshots.insert(
                    uow,
                    self.storage.market,
                    MARKET_SCOPE_ID,
                    current,
                    logical_time,
                )
            else:
                current = self._hydrate_market(uow, current)
            uow.commit()
        return current

    def quote_recycle_assets(
        self,
        owner_id: str,
        asset_ids: tuple[str, ...],
    ) -> RecycleOperationResult:
        try:
            with self.database.unit_of_work(write=False) as uow:
                inventory, loadout = self._inventory_loadout(uow, owner_id)
                quote = self._recycle_quote(inventory, loadout, owner_id, asset_ids)
            return RecycleOperationResult("quoted", quote)
        except (KeyError, TypeError, ValueError) as exc:
            return RecycleOperationResult("rejected", failure_message=str(exc))

    def quote_recycle_batch(
        self,
        owner_id: str,
        slot_id: str,
        quality_ids: frozenset[str],
        maximum_weapon_level: int | None = None,
    ) -> RecycleOperationResult:
        try:
            if not quality_ids:
                raise ValueError("批量回收至少需要一个品阶")
            if slot_id == WEAPON_SLOT_ID:
                if (
                    isinstance(maximum_weapon_level, bool)
                    or not isinstance(maximum_weapon_level, int)
                    or maximum_weapon_level < 1
                ):
                    raise ValueError("武器批量回收必须指定正整数等级上限")
            elif maximum_weapon_level is not None:
                raise ValueError("装备没有等级，不能使用等级筛选")
            with self.database.unit_of_work(write=False) as uow:
                inventory, loadout = self._inventory_loadout(uow, owner_id)
                asset_ids = tuple(
                    instance.id
                    for instance in inventory.instances.values()
                    if self._matches_batch(
                        instance,
                        slot_id,
                        quality_ids,
                        maximum_weapon_level,
                    )
                    and self._is_available_unassigned(inventory, loadout, instance.id)
                )
                selection_key = ":".join(
                    (
                        "batch",
                        slot_id,
                        ",".join(sorted(quality_ids)),
                        str(maximum_weapon_level or 0),
                    )
                )
                quote = self._recycle_quote(
                    inventory,
                    loadout,
                    owner_id,
                    asset_ids,
                    selection_key=selection_key,
                )
            return RecycleOperationResult("quoted", quote)
        except (KeyError, TypeError, ValueError) as exc:
            return RecycleOperationResult("rejected", failure_message=str(exc))

    def execute_recycle(
        self,
        owner_id: str,
        quote: RecycleQuote,
        *,
        logical_time: datetime,
    ) -> RecycleOperationResult:
        if quote.owner_id != owner_id:
            return RecycleOperationResult("forbidden", failure_message="回收报价不属于当前角色")
        with self.database.unit_of_work() as uow:
            inventory, loadout = self._inventory_loadout(uow, owner_id)
            try:
                current = self._recycle_quote(
                    inventory,
                    loadout,
                    owner_id,
                    tuple(line.asset_id for line in quote.lines),
                    selection_key=quote.selection_key,
                )
            except (KeyError, TypeError, ValueError) as exc:
                return RecycleOperationResult("stale", failure_message=str(exc))
            if current != quote:
                return RecycleOperationResult("stale", failure_message="回收报价已经过期，请重新确认")
            ledger = self.snapshots.require(
                uow,
                self.storage.ledger,
                PRIMARY_LEDGER_ID,
                LedgerState,
            )
            issuer = ledger.accounts[PRIMARY_ISSUER_ACCOUNT_ID]
            wallet = self._wallet(ledger, owner_id)
            context = _context(quote.id, logical_time, "recycle")
            inventory_outcome = self.inventory_engine.execute(
                InventoryTransaction(
                    f"{quote.id}:inventory",
                    owner_id,
                    "inventory.recycle_gear",
                    tuple(DestroyAsset(line.asset_id) for line in quote.lines),
                ),
                state=inventory,
                context=context,
            )
            if inventory_outcome.failure or inventory_outcome.value is None:
                return RecycleOperationResult(
                    "failed",
                    quote,
                    inventory_outcome.failure.message if inventory_outcome.failure else "回收物品失败",
                )
            ledger_outcome = self.ledger_engine.execute(
                LedgerTransaction(
                    f"{quote.id}:ledger",
                    owner_id,
                    "economy.recycle_gear",
                    (IssueFunds(issuer.id, wallet.id, quote.total_amount),),
                    expected_revisions={issuer.id: issuer.revision, wallet.id: wallet.revision},
                    metadata={"quote_id": quote.id, "asset_count": len(quote.lines)},
                ),
                state=ledger,
                context=context,
            )
            if ledger_outcome.failure or ledger_outcome.value is None:
                return RecycleOperationResult(
                    "failed",
                    quote,
                    ledger_outcome.failure.message if ledger_outcome.failure else "回收款入账失败",
                )
            self.snapshots.update(
                uow,
                self.storage.inventory,
                owner_id,
                inventory,
                inventory_outcome.value.state,
                logical_time,
            )
            self.snapshots.update(
                uow,
                self.storage.ledger,
                PRIMARY_LEDGER_ID,
                ledger,
                ledger_outcome.value.state,
                logical_time,
            )
            uow.commit()
            return RecycleOperationResult("recycled", quote)

    def quote_trophies(self, owner_id: str) -> TrophyRecycleResult:
        with self.database.unit_of_work(write=False) as uow:
            inventory = self.snapshots.require(
                uow,
                self.storage.inventory,
                owner_id,
                InventoryState,
            )
        quote = quote_trophy_recycle(inventory, self.content.items, owner_id)
        return TrophyRecycleResult("quoted" if quote.lines else "empty", quote)

    def recycle_trophies(
        self,
        owner_id: str,
        *,
        expected_quote_id: str | None = None,
        logical_time: datetime,
    ) -> TrophyRecycleResult:
        with self.database.unit_of_work() as uow:
            inventory = self.snapshots.require(
                uow,
                self.storage.inventory,
                owner_id,
                InventoryState,
            )
            quote = quote_trophy_recycle(inventory, self.content.items, owner_id)
            if not quote.lines:
                return TrophyRecycleResult("empty", quote)
            if expected_quote_id is not None and quote.id != expected_quote_id:
                return TrophyRecycleResult("stale", quote)
            context = _context(quote.id, logical_time, "trophy_recycle")
            inventory_operations = [
                ConsumeStack(line.asset_id, line.quantity) for line in quote.lines
            ]
            special_container = next(
                value
                for value in inventory.containers.values()
                if value.owner_id == owner_id and value.kind == "container.special"
            )
            for definition_id, quantity in sorted(quote.stack_item_totals.items()):
                existing = next(
                    (
                        stack
                        for stack in inventory.stacks.values()
                        if stack.definition_id == definition_id
                        and stack.container_id == special_container.id
                    ),
                    None,
                )
                receipt = SourceReceipt(
                    f"{quote.id}:receipt:{definition_id}",
                    "source.covenant_recycle",
                    quote.id,
                    logical_time,
                    {
                        "owner_id": owner_id,
                        "source_definition_ids": tuple(
                            sorted(
                                {
                                    str(line.definition_id)
                                    for line in quote.lines
                                    if line.output_kind == "stack_item"
                                    and line.output_id == definition_id
                                }
                            )
                        ),
                    },
                )
                if existing is None:
                    inventory_operations.append(
                        GrantStack(
                            f"{quote.id}:output:{definition_id}",
                            definition_id,
                            special_container.id,
                            quantity,
                            receipt,
                        )
                    )
                else:
                    inventory_operations.append(AppendStack(existing.id, quantity, receipt))
            inventory_outcome = self.inventory_engine.execute(
                InventoryTransaction(
                    f"{quote.id}:inventory",
                    owner_id,
                    "inventory.recycle_trophies",
                    tuple(inventory_operations),
                ),
                state=inventory,
                context=context,
            )
            if inventory_outcome.failure or inventory_outcome.value is None:
                raise RuntimeError(
                    inventory_outcome.failure.message if inventory_outcome.failure else "战利品回收失败"
                )
            ledger = None
            ledger_outcome = None
            if quote.total_amount:
                ledger = self.snapshots.require(
                    uow,
                    self.storage.ledger,
                    PRIMARY_LEDGER_ID,
                    LedgerState,
                )
                issuer = ledger.accounts[PRIMARY_ISSUER_ACCOUNT_ID]
                wallet = self._wallet(ledger, owner_id)
                ledger_outcome = self.ledger_engine.execute(
                    LedgerTransaction(
                        f"{quote.id}:ledger",
                        owner_id,
                        "economy.recycle_trophies",
                        (IssueFunds(issuer.id, wallet.id, quote.total_amount),),
                        expected_revisions={issuer.id: issuer.revision, wallet.id: wallet.revision},
                        metadata={"quote_id": quote.id},
                    ),
                    state=ledger,
                    context=context,
                )
                if ledger_outcome.failure or ledger_outcome.value is None:
                    raise RuntimeError(
                        ledger_outcome.failure.message
                        if ledger_outcome.failure
                        else "战利品回收款入账失败"
                    )
            self.snapshots.update(
                uow,
                self.storage.inventory,
                owner_id,
                inventory,
                inventory_outcome.value.state,
                logical_time,
            )
            if ledger is not None and ledger_outcome is not None and ledger_outcome.value is not None:
                self.snapshots.update(
                    uow,
                    self.storage.ledger,
                    PRIMARY_LEDGER_ID,
                    ledger,
                    ledger_outcome.value.state,
                    logical_time,
                )
            uow.commit()
            return TrophyRecycleResult("recycled", quote)

    def quote_listing(
        self,
        seller_id: str,
        seller_name: str,
        asset_id: str,
        list_price: int,
        quantity: int = 1,
    ) -> MarketListingResult:
        try:
            with self.database.unit_of_work(write=False) as uow:
                quote = self._listing_quote(
                    uow,
                    seller_id,
                    seller_name,
                    asset_id,
                    list_price,
                    quantity,
                )
            return MarketListingResult("quoted", quote=quote)
        except (KeyError, TypeError, ValueError) as exc:
            return MarketListingResult("rejected", failure_message=str(exc))

    def open_listing(
        self,
        seller_id: str,
        quote: MarketListingQuote,
        *,
        logical_time: datetime,
    ) -> MarketListingResult:
        if quote.seller_id != seller_id:
            return MarketListingResult("forbidden", failure_message="上架报价不属于当前角色")
        with self.database.unit_of_work() as uow:
            try:
                current = self._listing_quote(
                    uow,
                    seller_id,
                    quote.seller_name,
                    quote.asset_id,
                    quote.list_price,
                    quote.quantity,
                )
            except (KeyError, TypeError, ValueError) as exc:
                return MarketListingResult("stale", failure_message=str(exc))
            if current != quote:
                return MarketListingResult("stale", failure_message="上架报价已经过期，请重新查看物品")
            inventory, _loadout = self._inventory_loadout(uow, seller_id)
            market = self._market(uow)
            if any(value.asset.id == quote.asset_id for value in market.listings.values()):
                return MarketListingResult("duplicate", failure_message="该物品已有数量正在上架")
            number = market.next_listing_number
            listing_id = f"M{number}"
            reservation_id = f"market-reservation:{listing_id}:{quote.asset_id}"
            listing = MarketListing(
                listing_id,
                number,
                seller_id,
                quote.seller_name,
                quote.seller_wallet_account_id,
                inventory.asset(quote.asset_id),
                quote.price,
                quote.list_price,
                reservation_id,
                logical_time,
                logical_time + timedelta(seconds=MARKET_LISTING_LIFETIME_SECONDS),
            )
            context = _context(f"market:list:{listing_id}", logical_time, "market_list")
            inventory_outcome = self.inventory_engine.execute(
                InventoryTransaction(
                    f"market:list:{listing_id}:inventory",
                    seller_id,
                    "inventory.market_list",
                    (
                        ReserveAsset(
                            reservation_id,
                            quote.asset_id,
                            ReservationMode.ESCROWED,
                            "business.market_listing",
                            listing_id,
                            quote.quantity,
                        ),
                    ),
                ),
                state=inventory,
                context=context,
            )
            if inventory_outcome.failure or inventory_outcome.value is None:
                return MarketListingResult(
                    "failed",
                    quote,
                    failure_message=(
                        inventory_outcome.failure.message
                        if inventory_outcome.failure
                        else "物品上架预约失败"
                    ),
                )
            listings = dict(market.listings)
            listings[listing.id] = listing
            next_market = replace(
                market,
                listings=listings,
                next_listing_number=number + 1,
                revision=market.revision + 1,
            )
            self.snapshots.update(
                uow,
                self.storage.inventory,
                seller_id,
                inventory,
                inventory_outcome.value.state,
                logical_time,
            )
            self._write_market(uow, market, next_market, logical_time)
            uow.commit()
            return MarketListingResult("listed", quote, listing)

    def listings(
        self,
        *,
        logical_time: datetime,
        seller_id: str | None = None,
        slot_id: str | None = None,
        category: str | None = None,
    ) -> tuple[MarketListing, ...]:
        with self.database.unit_of_work(write=False) as uow:
            market = self._market(uow)
        return tuple(
            sorted(
                (
                    listing
                    for listing in market.listings.values()
                    if logical_time < listing.expires_at
                    and (seller_id is None or listing.seller_id == seller_id)
                    and (slot_id is None or listing.price.slot_id == slot_id)
                    and _matches_market_category(listing.price, category)
                ),
                key=lambda value: value.number,
                reverse=True,
            )
        )

    def quote_purchase(
        self,
        buyer_id: str,
        listing_id: str,
        *,
        logical_time: datetime,
    ) -> MarketPurchaseResult:
        try:
            with self.database.unit_of_work(write=False) as uow:
                quote = self._purchase_quote(uow, buyer_id, listing_id, logical_time)
            return MarketPurchaseResult("quoted", quote)
        except (KeyError, TypeError, ValueError) as exc:
            return MarketPurchaseResult("rejected", failure_message=str(exc))

    def purchase(
        self,
        buyer_id: str,
        quote: MarketPurchaseQuote,
        *,
        logical_time: datetime,
    ) -> MarketPurchaseResult:
        if quote.buyer_id != buyer_id:
            return MarketPurchaseResult("forbidden", failure_message="购买报价不属于当前角色")
        with self.database.unit_of_work() as uow:
            try:
                current = self._purchase_quote(uow, buyer_id, quote.listing.id, logical_time)
            except (KeyError, TypeError, ValueError) as exc:
                return MarketPurchaseResult("stale", failure_message=str(exc))
            if current != quote:
                return MarketPurchaseResult("stale", failure_message="购买报价已经变化，请重新查看挂单")
            listing = quote.listing
            market = self._market(uow)
            seller_inventory = self.snapshots.require(
                uow,
                self.storage.inventory,
                listing.seller_id,
                InventoryState,
            )
            buyer_inventory = self.snapshots.require(
                uow,
                self.storage.inventory,
                buyer_id,
                InventoryState,
            )
            try:
                current_asset = seller_inventory.asset(listing.asset.id)
            except KeyError:
                current_asset = None
            if current_asset != listing.asset:
                return MarketPurchaseResult("stale", failure_message="卖方物品状态已经变化")
            definition = self.content.items.require(listing.asset.definition_id)
            destination_kind = _market_destination_kind(definition)
            destination = next(
                (value for value in buyer_inventory.containers.values() if value.kind == destination_kind),
                None,
            )
            if destination is None:
                return MarketPurchaseResult("failed", failure_message="买方没有对应的物品存储空间")
            ledger = self.snapshots.require(
                uow,
                self.storage.ledger,
                PRIMARY_LEDGER_ID,
                LedgerState,
            )
            buyer_wallet = self._wallet(ledger, buyer_id)
            seller_wallet = ledger.accounts.get(listing.seller_wallet_account_id)
            if seller_wallet is None or seller_wallet.owner_id != listing.seller_id:
                return MarketPurchaseResult("failed", failure_message="卖方钱包状态无效")
            context = _context(quote.id, logical_time, "market_purchase")
            quantity = _market_quantity(listing.price)
            seller_operation = (
                ConsumeStack(listing.asset.id, quantity, listing.reservation_id)
                if isinstance(listing.asset, ItemStack)
                else ConsumeInstance(listing.asset.id, listing.reservation_id)
            )
            seller_outcome = self.inventory_engine.execute(
                InventoryTransaction(
                    f"{quote.id}:seller_inventory",
                    listing.seller_id,
                    "inventory.market_transfer_out",
                    (seller_operation,),
                ),
                state=seller_inventory,
                context=context,
            )
            if seller_outcome.failure or seller_outcome.value is None:
                return MarketPurchaseResult(
                    "failed",
                    quote,
                    seller_outcome.failure.message if seller_outcome.failure else "卖方物品转出失败",
                )
            buyer_operations = _market_grant_operations(
                listing,
                buyer_id,
                destination.id,
            )
            buyer_outcome = self.inventory_engine.execute(
                InventoryTransaction(
                    f"{quote.id}:buyer_inventory",
                    buyer_id,
                    "inventory.market_transfer_in",
                    buyer_operations,
                ),
                state=buyer_inventory,
                context=context,
            )
            if buyer_outcome.failure or buyer_outcome.value is None:
                return MarketPurchaseResult(
                    "failed",
                    quote,
                    buyer_outcome.failure.message if buyer_outcome.failure else "买方物品接收失败",
                )
            operations: list[object] = []
            expected = {
                buyer_wallet.id: buyer_wallet.revision,
                seller_wallet.id: seller_wallet.revision,
            }
            tax_account = ledger.accounts.get(PRIMARY_TAX_ACCOUNT_ID)
            if tax_account is None:
                tax_account = LedgerAccount(
                    PRIMARY_TAX_ACCOUNT_ID,
                    "owner.tax_authority",
                    PRIMARY_TAX_OWNER_ID,
                    PRIMARY_CURRENCY_ID,
                )
                operations.append(OpenLedgerAccount(tax_account))
            else:
                expected[tax_account.id] = tax_account.revision
            allocations = [
                FundAllocation(seller_wallet.id, quote.tax.seller_proceeds),
            ]
            if quote.tax.tax_amount:
                allocations.append(FundAllocation(tax_account.id, quote.tax.tax_amount))
            operations.append(SplitFunds(buyer_wallet.id, tuple(allocations)))
            ledger_outcome = self.ledger_engine.execute(
                LedgerTransaction(
                    f"{quote.id}:ledger",
                    buyer_id,
                    "economy.market_purchase",
                    tuple(operations),
                    expected_revisions=expected,
                    metadata={
                        "listing_id": listing.id,
                        "asset_id": listing.asset.id,
                        "definition_id": listing.asset.definition_id,
                        "quantity": quantity,
                        "reference_price": listing.price.reference_price,
                        "list_price": listing.list_price,
                        "tax_amount": quote.tax.tax_amount,
                    },
                ),
                state=ledger,
                context=context,
            )
            if ledger_outcome.failure or ledger_outcome.value is None:
                return MarketPurchaseResult(
                    "failed",
                    quote,
                    ledger_outcome.failure.message if ledger_outcome.failure else "二手款项结算失败",
                )
            listings = dict(market.listings)
            listings.pop(listing.id)
            cutoff = logical_time - timedelta(seconds=MARKET_RISK_WINDOW_SECONDS)
            recent = tuple(value for value in market.recent_trades if value.settled_at >= cutoff)
            record = MarketTradeRecord(
                f"trade:{quote.id}",
                listing.id,
                listing.asset.id,
                listing.seller_id,
                buyer_id,
                listing.price.reference_price,
                listing.list_price,
                quote.tax.buyer_total,
                quote.tax.seller_proceeds,
                quote.tax.tax_amount,
                logical_time,
                str(listing.asset.definition_id),
                "stack" if isinstance(listing.asset, ItemStack) else "instance",
                quantity,
            )
            next_market = replace(
                market,
                listings=listings,
                recent_trades=(*recent, record),
                revision=market.revision + 1,
            )
            self.snapshots.update(
                uow,
                self.storage.inventory,
                listing.seller_id,
                seller_inventory,
                seller_outcome.value.state,
                logical_time,
            )
            self.snapshots.update(
                uow,
                self.storage.inventory,
                buyer_id,
                buyer_inventory,
                buyer_outcome.value.state,
                logical_time,
            )
            self.snapshots.update(
                uow,
                self.storage.ledger,
                PRIMARY_LEDGER_ID,
                ledger,
                ledger_outcome.value.state,
                logical_time,
            )
            self._write_market(uow, market, next_market, logical_time)
            uow.commit()
            return MarketPurchaseResult("purchased", quote)

    def cancel_listing(
        self,
        seller_id: str,
        listing_id: str,
        *,
        logical_time: datetime,
        expired: bool = False,
    ) -> MarketListingResult:
        with self.database.unit_of_work() as uow:
            market = self._market(uow)
            listing = market.listings.get(_listing_id(listing_id))
            if listing is None:
                return MarketListingResult("unknown", failure_message="找不到这份二手挂单")
            if not expired and listing.seller_id != seller_id:
                return MarketListingResult("forbidden", failure_message="只能下架自己的物品")
            if expired and logical_time < listing.expires_at:
                return MarketListingResult("not_expired", listing=listing)
            inventory = self.snapshots.require(
                uow,
                self.storage.inventory,
                listing.seller_id,
                InventoryState,
            )
            context = _context(
                f"market:close:{listing.id}:{'expired' if expired else 'cancel'}",
                logical_time,
                "market_close",
            )
            outcome = self.inventory_engine.execute(
                InventoryTransaction(
                    context.trace_id,
                    seller_id or listing.seller_id,
                    "inventory.market_close",
                    (ReleaseReservation(listing.reservation_id),),
                ),
                state=inventory,
                context=context,
            )
            if outcome.failure or outcome.value is None:
                return MarketListingResult(
                    "failed",
                    listing=listing,
                    failure_message=outcome.failure.message if outcome.failure else "二手挂单释放失败",
                )
            listings = dict(market.listings)
            listings.pop(listing.id)
            next_market = replace(market, listings=listings, revision=market.revision + 1)
            self.snapshots.update(
                uow,
                self.storage.inventory,
                listing.seller_id,
                inventory,
                outcome.value.state,
                logical_time,
            )
            self._write_market(uow, market, next_market, logical_time)
            uow.commit()
            return MarketListingResult("expired" if expired else "cancelled", listing=listing)

    def expire_due(self, *, logical_time: datetime, limit: int = 100) -> int:
        with self.database.unit_of_work(write=False) as uow:
            market = self._market(uow)
            ids = tuple(
                value.id
                for value in sorted(market.listings.values(), key=lambda item: item.expires_at)
                if value.expires_at <= logical_time
            )[:limit]
        completed = 0
        for listing_id in ids:
            result = self.cancel_listing("", listing_id, logical_time=logical_time, expired=True)
            if result.status == "expired":
                completed += 1
        return completed

    def tax_summary(self, *, logical_time: datetime) -> TaxSummary:
        with self.database.unit_of_work(write=False) as uow:
            ledger = self.snapshots.load(
                uow,
                self.storage.ledger,
                PRIMARY_LEDGER_ID,
                LedgerState,
            )
            market = self._market(uow)
        account = ledger.accounts.get(PRIMARY_TAX_ACCOUNT_ID) if ledger is not None else None
        cutoff = logical_time - timedelta(seconds=MARKET_RISK_WINDOW_SECONDS)
        recent = tuple(value for value in market.recent_trades if value.settled_at >= cutoff)
        return TaxSummary(
            account.balance if account is not None else 0,
            sum(value.tax_amount for value in recent),
            len(recent),
        )

    def _listing_quote(self, uow, seller_id, seller_name, asset_id, list_price, quantity=1):
        if not seller_name.strip() or list_price < 1:
            raise ValueError("上架价格必须是大于 0 的整数")
        inventory, loadout = self._inventory_loadout(uow, seller_id)
        asset = inventory.asset(asset_id)
        self.content.items.require(asset.definition_id)
        if isinstance(asset, ItemInstance):
            self._require_available_unassigned(inventory, loadout, asset.id)
        policy = self.market_item_policies.get(str(asset.definition_id))
        if isinstance(asset, ItemStack):
            if policy is None:
                raise ValueError("该堆叠物品不能进入归航市场")
            if not policy.minimum_quantity <= quantity <= policy.maximum_quantity:
                raise ValueError("上架数量超出该物品的交易数量范围")
            if inventory.available_quantity(asset.id) < quantity:
                raise ValueError("该物品可交易数量不足")
            market_price = MarketPriceQuote(
                asset.id,
                asset.definition_id,
                "stack",
                policy.category,
                quantity,
                policy.unit_reference_price,
                policy.unit_reference_price * quantity,
                PRIMARY_CURRENCY_ID,
                policy.minimum_price_bps,
                policy.maximum_price_bps,
                ECONOMY_POLICY_ID,
                ECONOMY_POLICY_VERSION,
            )
        else:
            if quantity != 1:
                raise ValueError("独立物品不能填写堆叠数量")
            if policy is not None:
                market_price = MarketPriceQuote(
                    asset.id,
                    asset.definition_id,
                    "instance",
                    policy.category,
                    1,
                    policy.unit_reference_price,
                    policy.unit_reference_price,
                    PRIMARY_CURRENCY_ID,
                    policy.minimum_price_bps,
                    policy.maximum_price_bps,
                    ECONOMY_POLICY_ID,
                    ECONOMY_POLICY_VERSION,
                )
            else:
                try:
                    gear_price = self.prices.quote(asset)
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError("该物品不能进入归航市场") from exc
                market_price = MarketPriceQuote(
                    asset.id,
                    asset.definition_id,
                    "instance",
                    gear_price.kind,
                    1,
                    gear_price.reference_price,
                    gear_price.reference_price,
                    gear_price.currency_id,
                    MARKET_MIN_PRICE_BPS,
                    MARKET_MAX_SELLER_PRICE_BPS,
                    ECONOMY_POLICY_ID,
                    ECONOMY_POLICY_VERSION,
                    str(gear_price.slot_id),
                )
        ledger = self.snapshots.require(
            uow,
            self.storage.ledger,
            PRIMARY_LEDGER_ID,
            LedgerState,
        )
        wallet = self._wallet(ledger, seller_id)
        payload = (
            seller_id,
            seller_name,
            inventory.revision,
            asset.id,
            market_price.reference_price,
            list_price,
            quantity,
            ECONOMY_POLICY_ID,
            ECONOMY_POLICY_VERSION,
        )
        return MarketListingQuote(
            f"listing-quote:{_fingerprint(payload)}",
            seller_id,
            seller_name,
            wallet.id,
            inventory.revision,
            asset.id,
            market_price,
            list_price,
            quantity,
        )

    def _purchase_quote(self, uow, buyer_id, listing_id, logical_time):
        market = self._market(uow)
        listing = market.listings.get(_listing_id(listing_id))
        if listing is None:
            raise ValueError("找不到这份二手挂单")
        if logical_time >= listing.expires_at:
            raise ValueError("二手挂单已经到期")
        if listing.seller_id == buyer_id:
            raise ValueError("不能购买自己上架的物品")
        cutoff = logical_time - timedelta(seconds=MARKET_RISK_WINDOW_SECONDS)
        recent = tuple(value for value in market.recent_trades if value.settled_at >= cutoff)
        pair = frozenset((listing.seller_id, buyer_id))
        pair_count = sum(
            1
            for value in recent
            if frozenset((value.seller_id, value.buyer_id)) == pair
        )
        asset_count = (
            sum(1 for value in recent if value.asset_id == listing.asset.id)
            if isinstance(listing.asset, ItemInstance)
            else 0
        )
        minimum_price_bps = getattr(listing.price, "minimum_price_bps", MARKET_MIN_PRICE_BPS)
        maximum_price_bps = getattr(
            listing.price,
            "maximum_price_bps",
            MARKET_MAX_SELLER_PRICE_BPS,
        )
        tax = quote_market_tax(
            listing.price.reference_price,
            listing.list_price,
            repeated_pair_trades=pair_count,
            repeated_asset_trades=asset_count,
            minimum_price_bps=minimum_price_bps,
            maximum_price_bps=maximum_price_bps,
        )
        payload = (
            buyer_id,
            listing.id,
            listing.asset.id,
            listing.list_price,
            tax.buyer_total,
            tax.seller_proceeds,
            tax.tax_amount,
            pair_count,
            asset_count,
            minimum_price_bps,
            maximum_price_bps,
            ECONOMY_POLICY_VERSION,
        )
        return MarketPurchaseQuote(
            f"purchase-quote:{_fingerprint(payload)}",
            buyer_id,
            listing,
            tax,
        )

    def _recycle_quote(
        self,
        inventory,
        loadout,
        owner_id,
        asset_ids,
        *,
        selection_key="",
    ):
        normalized = tuple(dict.fromkeys(str(value).strip() for value in asset_ids if str(value).strip()))
        if not normalized:
            raise ValueError("没有符合条件的可回收物品")
        lines = []
        for asset_id in normalized:
            instance = inventory.instances.get(asset_id)
            if instance is None:
                raise ValueError("回收目标不是当前武库中的独立物品")
            self._require_available_unassigned(inventory, loadout, asset_id)
            price = self.prices.quote(instance)
            lines.append(
                RecycleQuoteLine(
                    asset_id,
                    inventory.reference_number(asset_id),
                    price.definition_id,
                    price.kind,
                    price.slot_id,
                    price.quality_id,
                    price.reference_price,
                    recycle_amount(price),
                )
            )
        lines.sort(key=lambda value: value.reference_number)
        payload = {
            "owner_id": owner_id,
            "inventory_revision": inventory.revision,
            "lines": [
                (line.asset_id, line.reference_price, line.recycle_amount)
                for line in lines
            ],
            "policy_version": ECONOMY_POLICY_VERSION,
            "selection_key": selection_key,
        }
        fingerprint = sha256(
            json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
        ).hexdigest()[:24]
        return RecycleQuote(
            f"recycle:{fingerprint}",
            owner_id,
            inventory.revision,
            PRIMARY_CURRENCY_ID,
            tuple(lines),
            sum(line.reference_price for line in lines),
            sum(line.recycle_amount for line in lines),
            ECONOMY_POLICY_ID,
            ECONOMY_POLICY_VERSION,
            selection_key,
        )

    def _matches_batch(
        self,
        instance,
        slot_id,
        quality_ids,
        maximum_weapon_level,
    ):
        try:
            price = self.prices.quote(instance)
        except (KeyError, TypeError, ValueError):
            return False
        if price.slot_id != slot_id or price.quality_id not in quality_ids:
            return False
        if price.kind == "weapon":
            return weapon_state_from_instance(instance).level <= maximum_weapon_level
        return maximum_weapon_level is None

    def _require_available_unassigned(self, inventory, loadout, asset_id):
        if not self._is_available_unassigned(inventory, loadout, asset_id):
            if inventory.is_protected(asset_id):
                raise ValueError("珍藏物品不能回收或上架")
            if inventory.availability(asset_id) is not AssetAvailability.AVAILABLE:
                raise ValueError("物品已经被其他业务占用")
            raise ValueError("物品仍被某套配装引用，不能回收或上架")

    @staticmethod
    def _is_available_unassigned(inventory, loadout, asset_id):
        if inventory.is_protected(asset_id):
            return False
        if inventory.availability(asset_id) is not AssetAvailability.AVAILABLE:
            return False
        assigned = set(loadout.slots.values())
        for preset in loadout.presets.values():
            assigned.update(preset.slots.values())
        return asset_id not in assigned

    def _inventory_loadout(self, uow, owner_id):
        return (
            self.snapshots.require(
                uow,
                self.storage.inventory,
                owner_id,
                InventoryState,
            ),
            self.snapshots.require(
                uow,
                self.storage.loadout,
                owner_id,
                LoadoutState,
            ),
        )

    def _market(self, uow):
        state = self.snapshots.load(
            uow,
            self.storage.market,
            MARKET_SCOPE_ID,
            MarketState,
        ) or MarketState()
        return self._hydrate_market(uow, state)

    def _write_market(self, uow, previous, current, logical_time):
        stored = self.snapshots.load(
            uow,
            self.storage.market,
            MARKET_SCOPE_ID,
            MarketState,
        )
        if stored is None:
            self._sync_market_listings(uow, MarketState(), current, logical_time)
            self.snapshots.insert(
                uow,
                self.storage.market,
                MARKET_SCOPE_ID,
                replace(current, listings={}),
                logical_time,
            )
        else:
            self._sync_market_listings(uow, previous, current, logical_time)
            self.snapshots.update(
                uow,
                self.storage.market,
                MARKET_SCOPE_ID,
                replace(previous, listings={}),
                replace(current, listings={}),
                logical_time,
            )

    def _hydrate_market(self, uow, state: MarketState) -> MarketState:
        listings = {}
        for row in uow.list_market_listings(state.scope_id):
            listing = self.snapshots.codec.loads(row.payload, MarketListing)
            if (
                listing.id != row.listing_id
                or listing.number != row.number
                or listing.seller_id != row.seller_id
            ):
                raise RuntimeError(f"二手挂单关系行与负载不一致：{row.listing_id}")
            listings[listing.id] = listing
        return replace(state, listings=listings)

    def _sync_market_listings(self, uow, previous, current, logical_time) -> None:
        for listing_id in previous.listings:
            if listing_id not in current.listings:
                uow.delete_market_listing(MARKET_SCOPE_ID, listing_id)
        for listing_id, listing in current.listings.items():
            prior = previous.listings.get(listing_id)
            payload = self.snapshots.codec.dumps(listing)
            if prior is None:
                uow.insert_market_listing(
                    MARKET_SCOPE_ID,
                    listing.id,
                    listing.number,
                    listing.seller_id,
                    listing.expires_at.isoformat(),
                    payload,
                    logical_time.isoformat(),
                )
            elif prior != listing:
                uow.update_market_listing(
                    MARKET_SCOPE_ID,
                    listing.id,
                    listing.number,
                    listing.seller_id,
                    listing.expires_at.isoformat(),
                    payload,
                    logical_time.isoformat(),
                )

    @staticmethod
    def _wallet(ledger, owner_id):
        try:
            return next(
                value
                for value in ledger.accounts.values()
                if value.kind is LedgerAccountKind.STANDARD
                and value.owner_kind == "owner.character"
                and value.owner_id == owner_id
                and value.currency_id == PRIMARY_CURRENCY_ID
            )
        except StopIteration as exc:
            raise ValueError("当前角色缺少主货币钱包") from exc


def _context(trace_id: str, logical_time: datetime, phase: str) -> RuleContext:
    return RuleContext(
        trace_id,
        ECONOMY_RULESET_VERSION,
        Ruleset(f"ruleset.economy.{phase}"),
        logical_time,
        SeededRandomSource(trace_id),
    )


def _listing_id(value: str) -> str:
    text = str(value or "").strip().upper()
    if text.startswith("M") and text[1:].isdigit() and int(text[1:]) > 0:
        return f"M{int(text[1:])}"
    raise ValueError("二手挂单编号格式应为 M数字")


def _market_quantity(price) -> int:
    return int(getattr(price, "quantity", 1))


def _matches_market_category(price, category: str | None) -> bool:
    if category is None:
        return True
    actual = getattr(price, "category", getattr(price, "kind", ""))
    if category == "special_all":
        return actual in {"special", "growth", "permanent"}
    return actual == category


def _market_destination_kind(definition) -> str:
    if definition.tags.has("storage.inscription"):
        return "container.inscription"
    if definition.tags.has("storage.special"):
        return "container.special"
    if definition.tags.has("item.weapon") or definition.tags.has("item.equipment"):
        return "container.armory"
    raise ValueError("该物品没有可用的市场存储空间")


def _market_grant_operations(listing: MarketListing, buyer_id: str, container_id: str):
    asset = listing.asset
    if isinstance(asset, ItemInstance):
        return (
            GrantInstance(
                asset.id,
                asset.definition_id,
                container_id,
                asset.receipt,
                asset.data,
                asset.revision,
            ),
        )
    quantity = _market_quantity(listing.price)
    lots = _take_provenance_lots(asset.lots, quantity)
    new_asset_id = f"market-stack:{listing.id}:{buyer_id}"
    first, *rest = lots
    operations = [GrantStack(new_asset_id, asset.definition_id, container_id, first.quantity, first.receipt)]
    operations.extend(AppendStack(new_asset_id, lot.quantity, lot.receipt) for lot in rest)
    return tuple(operations)


def _take_provenance_lots(lots, quantity: int):
    remaining = quantity
    selected = []
    for lot in lots:
        if remaining <= 0:
            break
        taken = min(remaining, lot.quantity)
        selected.append(type(lot)(lot.receipt, taken))
        remaining -= taken
    if remaining:
        raise ValueError("市场托管物品来源批次不足")
    return tuple(selected)


def _fingerprint(values) -> str:
    payload = json.dumps(values, ensure_ascii=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()[:24]


__all__ = ["EconomyFeature"]
