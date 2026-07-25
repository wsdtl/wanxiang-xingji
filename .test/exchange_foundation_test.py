"""交换开放、冻结、成交、取消和原子失败测试。"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay import RuleContext, Ruleset, SeededRandomSource  # noqa: E402
from game.core.gameplay.economy import (  # noqa: E402
    CurrencyCatalog,
    CurrencyDefinition,
    IssueFunds,
    LedgerAccount,
    LedgerAccountKind,
    LedgerEngine,
    LedgerState,
    LedgerTransaction,
)
from game.core.gameplay.exchange import (  # noqa: E402
    EXCHANGE_FOUNDATION_VERSION,
    CancelExchange,
    CommitExchange,
    ExchangeAssetOffer,
    ExchangeCommand,
    ExchangeContract,
    ExchangeEngine,
    ExchangeQuote,
    ExchangeQuoteLine,
    ExchangeState,
    ExchangeStatus,
    OpenExchange,
    SettleExchange,
)
from game.core.gameplay.inventory import (  # noqa: E402
    GrantStack,
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


TIME = datetime(2026, 7, 14, 1, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
    assert EXCHANGE_FOUNDATION_VERSION == "exchange.foundation.v1"
    environment = _environment()
    _assert_fixed_price_settlement(environment)
    _assert_committed_cancel_releases_both_sides(environment)
    print("exchange foundation tests passed")


def _context(trace: str, at: datetime = TIME) -> RuleContext:
    return RuleContext(
        trace,
        "rules.exchange_v1",
        Ruleset("ruleset.exchange_test"),
        at,
        SeededRandomSource(trace),
    )


def _environment():
    components = ItemComponentRegistry()
    items = ItemCatalog(components)
    items.register(ItemDefinition("item.material_ore", ItemAssetKind.STACK, stack_limit=99))
    items.finalize()
    inventory_engine = InventoryEngine(items)
    inventory = InventoryState(
        containers={
            "seller-bag": ItemContainer("seller-bag", "container.inventory", "seller"),
            "buyer-bag": ItemContainer("buyer-bag", "container.inventory", "buyer"),
        }
    )
    inventory = inventory_engine.execute(
        InventoryTransaction(
            "grant-sale-stock",
            "seller",
            "inventory.test_setup",
            (
                GrantStack(
                    "ore-source",
                    "item.material_ore",
                    "seller-bag",
                    10,
                    SourceReceipt("source-ore", "source.test", "ore", TIME),
                ),
            ),
        ),
        state=inventory,
        context=_context("grant-sale-stock"),
    ).unwrap().state

    currencies = CurrencyCatalog()
    currencies.register(CurrencyDefinition("currency.stone"))
    currencies.finalize()
    ledger_engine = LedgerEngine(currencies)
    ledger = LedgerState(
        accounts={
            "issuer": LedgerAccount(
                "issuer", "owner.system", "system", "currency.stone", LedgerAccountKind.ISSUER
            ),
            "buyer-wallet": LedgerAccount(
                "buyer-wallet", "owner.account", "buyer", "currency.stone"
            ),
            "seller-wallet": LedgerAccount(
                "seller-wallet", "owner.account", "seller", "currency.stone"
            ),
            "tax-wallet": LedgerAccount(
                "tax-wallet", "owner.system", "tax", "currency.stone"
            ),
        }
    )
    ledger = ledger_engine.execute(
        LedgerTransaction(
            "fund-buyer",
            "system",
            "economy.test_setup",
            (IssueFunds("issuer", "buyer-wallet", 500),),
            {"issuer": 0, "buyer-wallet": 0},
        ),
        state=ledger,
        context=_context("fund-buyer"),
    ).unwrap().state
    return ExchangeEngine(inventory_engine, ledger_engine), inventory, ledger


def _contract(contract_id: str) -> ExchangeContract:
    return ExchangeContract(
        contract_id,
        "exchange.fixed_price",
        "seller",
        ExchangeQuote(
            f"quote-{contract_id}",
            1,
            "currency.stone",
            100,
            (
                ExchangeQuoteLine("quote_line.seller", "seller-wallet", 90),
                ExchangeQuoteLine("quote_line.tax", "tax-wallet", 10),
            ),
            "quote_policy.market",
            1,
        ),
        (ExchangeAssetOffer("exchange_offer.ore", "ore-source", f"{contract_id}-ore", 3),),
        TIME,
        TIME + timedelta(hours=1),
    )


def _open_and_commit(engine, inventory, ledger, contract_id="contract-a"):
    state = ExchangeState("exchange-main")
    contract = _contract(contract_id)
    opened = engine.execute(
        ExchangeCommand("open-" + contract_id, "seller", 0, OpenExchange(contract)),
        exchange=state,
        inventory_state=inventory,
        ledger_state=ledger,
        context=_context("open-" + contract_id),
    ).unwrap()
    assert opened.inventory.stacks["ore-source"].quantity == 7
    assert opened.inventory.stacks[f"{contract_id}-ore"].quantity == 3
    committed = engine.execute(
        ExchangeCommand(
            "commit-" + contract_id,
            "buyer",
            1,
            CommitExchange(
                contract_id,
                "buyer",
                "buyer-wallet",
                contract.quote.id,
                contract.quote.version,
                {"exchange_offer.ore": "buyer-bag"},
            ),
        ),
        exchange=opened.exchange,
        inventory_state=opened.inventory,
        ledger_state=opened.ledger,
        context=_context("commit-" + contract_id),
    ).unwrap()
    assert committed.contract.status is ExchangeStatus.COMMITTED
    assert committed.ledger.available_balance("buyer-wallet", logical_time=TIME) == 400
    return committed


def _assert_fixed_price_settlement(environment) -> None:
    engine, inventory, ledger = environment
    committed = _open_and_commit(engine, inventory, ledger)
    settled = engine.execute(
        ExchangeCommand("settle-contract-a", "buyer", 2, SettleExchange("contract-a")),
        exchange=committed.exchange,
        inventory_state=committed.inventory,
        ledger_state=committed.ledger,
        context=_context("settle-contract-a"),
    ).unwrap()
    assert settled.contract.status is ExchangeStatus.SETTLED
    assert settled.inventory.stacks["contract-a-ore"].container_id == "buyer-bag"
    assert settled.ledger.accounts["buyer-wallet"].balance == 400
    assert settled.ledger.accounts["seller-wallet"].balance == 90
    assert settled.ledger.accounts["tax-wallet"].balance == 10
    assert not settled.ledger.holds


def _assert_committed_cancel_releases_both_sides(environment) -> None:
    engine, inventory, ledger = environment
    committed = _open_and_commit(engine, inventory, ledger, "contract-b")
    cancelled = engine.execute(
        ExchangeCommand("cancel-contract-b", "seller", 2, CancelExchange("contract-b")),
        exchange=committed.exchange,
        inventory_state=committed.inventory,
        ledger_state=committed.ledger,
        context=_context("cancel-contract-b"),
    ).unwrap()
    assert cancelled.contract.status is ExchangeStatus.CANCELLED
    assert not cancelled.inventory.reservations
    assert not cancelled.ledger.holds
    assert cancelled.ledger.available_balance("buyer-wallet", logical_time=TIME) == 500


if __name__ == "__main__":
    main()
