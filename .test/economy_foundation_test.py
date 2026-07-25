"""经济账本底座的守恒、并发、防重、冻结和原子性测试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay import RuleContext, Ruleset, SeededRandomSource  # noqa: E402
from game.core.gameplay.economy import (  # noqa: E402
    CaptureFundHold,
    CurrencyCatalog,
    CurrencyDefinition,
    ECONOMY_FOUNDATION_VERSION,
    FundAllocation,
    IssueFunds,
    LedgerAccount,
    LedgerAccountKind,
    LedgerEngine,
    LedgerState,
    LedgerTransaction,
    OpenLedgerAccount,
    PlaceFundHold,
    ReleaseFundHold,
    RetireFunds,
    SplitFunds,
    TransferFunds,
)


TIME = datetime(2026, 7, 12, 23, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
    engine, state = _assert_catalog_and_account_opening()
    state = _assert_issuance_and_replay(engine, state)
    state = _assert_holds_and_atomic_capture(engine, state)
    state = _assert_transfer_split_and_retirement(engine, state)
    _assert_failures_are_atomic(engine, state)
    _assert_expired_hold_release(engine, state)
    print("economy foundation tests passed")


def _context(*, at: datetime = TIME, seed: int = 700) -> RuleContext:
    return RuleContext(
        trace_id=f"economy-test-{seed}-{at.timestamp()}",
        rule_version="rules.v1",
        ruleset=Ruleset("ruleset.standard"),
        logical_time=at,
        random=SeededRandomSource(seed),
    )


def _transaction(transaction_id, *operations, revisions=None, reason="economy.test"):
    return LedgerTransaction(
        transaction_id,
        "actor.test",
        reason,
        tuple(operations),
        expected_revisions=revisions or {},
    )


def _execute(engine, state, transaction, *, context=None):
    outcome = engine.execute(transaction, state=state, context=context or _context())
    assert outcome.ok and outcome.value, outcome.failure
    return outcome.value


def _account(account_id, owner_kind, owner_id, currency="currency.spirit_stone", *, kind=None):
    return LedgerAccount(
        account_id,
        owner_kind,
        owner_id,
        currency,
        kind or LedgerAccountKind.STANDARD,
    )


def _assert_catalog_and_account_opening():
    currencies = CurrencyCatalog()
    currencies.register(CurrencyDefinition("currency.spirit_stone"))
    currencies.register(CurrencyDefinition("currency.jade_credit", decimal_places=2))
    engine = LedgerEngine(currencies)
    assert currencies.finalized
    assert ECONOMY_FOUNDATION_VERSION == "economy.foundation.v1"
    try:
        currencies.register(CurrencyDefinition("currency.too_late"))
        raise AssertionError("运行期不能修改已冻结货币目录")
    except RuntimeError:
        pass

    accounts = (
        _account(
            "issuer-stone",
            "owner.system",
            "system-economy",
            kind=LedgerAccountKind.ISSUER,
        ),
        _account("player-a", "owner.account", "account-a"),
        _account("player-b", "owner.account", "account-b"),
        _account("city-tax", "owner.location", "city-a"),
        _account("market-escrow", "owner.business", "market", kind=LedgerAccountKind.ESCROW),
        _account("jade-player", "owner.account", "account-a", "currency.jade_credit"),
    )
    opened = _execute(
        engine,
        LedgerState(),
        _transaction("open-ledger-accounts", *(OpenLedgerAccount(value) for value in accounts)),
    )
    assert opened.state.revision == 1
    assert all(account.balance == 0 and account.revision == 0 for account in opened.state.accounts.values())
    assert [event.kind for event in opened.events] == ["economy.account.opened"] * len(accounts)
    return engine, opened.state


def _assert_issuance_and_replay(engine, state):
    transaction = _transaction(
        "issue-starter-funds",
        IssueFunds("issuer-stone", "player-a", 1_000),
        revisions={"issuer-stone": 0, "player-a": 0},
        reason="economy.reward_issue",
    )
    issued = _execute(engine, state, transaction)
    state = issued.state
    assert state.accounts["issuer-stone"].balance == -1_000
    assert state.accounts["player-a"].balance == 1_000
    assert state.accounts["issuer-stone"].revision == 1
    assert sum(posting.amount for posting in issued.entries[0].postings) == 0
    assert issued.events[0].kind == "economy.funds.issued"

    replayed = _execute(engine, state, transaction)
    assert replayed.replayed and replayed.state is state
    assert not replayed.events and not replayed.entries
    mismatch = engine.execute(
        replace(
            transaction,
            operations=(IssueFunds("issuer-stone", "player-a", 999),),
        ),
        state=state,
        context=_context(seed=701),
    )
    assert mismatch.failure and mismatch.failure.code == "economy.transaction_mismatch"
    return state


def _assert_holds_and_atomic_capture(engine, state):
    held = _execute(
        engine,
        state,
        _transaction(
            "hold-market-payment",
            PlaceFundHold(
                "hold-order-1",
                "player-a",
                600,
                "business.market_order",
                "order-1",
            ),
            revisions={"player-a": 1},
        ),
    )
    state = held.state
    assert state.accounts["player-a"].balance == 1_000
    assert state.available_balance("player-a", logical_time=TIME) == 400

    blocked = engine.execute(
        _transaction(
            "spend-held-funds",
            TransferFunds("player-a", "player-b", 401),
            revisions={"player-a": 2, "player-b": 0},
        ),
        state=state,
        context=_context(seed=702),
    )
    assert blocked.failure and blocked.failure.code == "economy.insufficient_funds"
    assert state.accounts["player-a"].balance == 1_000
    assert state.accounts["player-b"].balance == 0

    captured = _execute(
        engine,
        state,
        _transaction(
            "capture-market-payment",
            CaptureFundHold(
                "hold-order-1",
                (
                    FundAllocation("player-b", 400),
                    FundAllocation("city-tax", 100),
                ),
            ),
            revisions={"player-a": 2, "player-b": 0, "city-tax": 0},
            reason="economy.market_settlement",
        ),
    )
    state = captured.state
    assert state.accounts["player-a"].balance == 500
    assert state.accounts["player-b"].balance == 400
    assert state.accounts["city-tax"].balance == 100
    assert state.holds["hold-order-1"].amount == 100
    assert len(captured.entries[0].postings) == 3
    assert [value.amount for value in captured.entries[0].postings] == [-500, 400, 100]

    released = _execute(
        engine,
        state,
        _transaction(
            "release-market-remainder",
            ReleaseFundHold("hold-order-1"),
            revisions={"player-a": 3},
        ),
    )
    assert "hold-order-1" not in released.state.holds
    assert released.state.accounts["player-a"].balance == 500
    return released.state


def _assert_transfer_split_and_retirement(engine, state):
    split = _execute(
        engine,
        state,
        _transaction(
            "split-player-payment",
            SplitFunds(
                "player-a",
                (
                    FundAllocation("player-b", 100),
                    FundAllocation("city-tax", 20),
                    FundAllocation("market-escrow", 30),
                ),
            ),
            revisions={
                "player-a": 4,
                "player-b": 1,
                "city-tax": 1,
                "market-escrow": 0,
            },
        ),
    )
    state = split.state
    assert state.accounts["player-a"].balance == 350
    assert state.accounts["market-escrow"].balance == 30

    transferred = _execute(
        engine,
        state,
        _transaction(
            "release-escrow-payment",
            TransferFunds("market-escrow", "player-b", 30),
            revisions={"market-escrow": 1, "player-b": 2},
        ),
    )
    state = transferred.state
    retired = _execute(
        engine,
        state,
        _transaction(
            "retire-system-fee",
            RetireFunds("city-tax", "issuer-stone", 20),
            revisions={"city-tax": 2, "issuer-stone": 1},
            reason="economy.system_sink",
        ),
    )
    state = retired.state
    assert state.accounts["issuer-stone"].balance == -980
    assert state.accounts["city-tax"].balance == 100
    assert sum(account.balance for account in state.accounts.values()) == 0
    return state


def _assert_failures_are_atomic(engine, state):
    checkpoint_state = state
    context = _context(seed=703)
    random_checkpoint = context.random.checkpoint()
    failed = engine.execute(
        _transaction(
            "atomic-transfer-failure",
            TransferFunds("player-a", "player-b", 10),
            TransferFunds("player-a", "player-b", 100_000),
            revisions={
                "player-a": state.accounts["player-a"].revision,
                "player-b": state.accounts["player-b"].revision,
            },
        ),
        state=state,
        context=context,
    )
    assert failed.failure and failed.failure.code == "economy.insufficient_funds"
    assert state is checkpoint_state
    assert context.random.checkpoint() == random_checkpoint

    stale = engine.execute(
        _transaction(
            "stale-revision",
            TransferFunds("player-a", "player-b", 1),
            revisions={"player-a": 0, "player-b": state.accounts["player-b"].revision},
        ),
        state=state,
        context=_context(seed=704),
    )
    assert stale.failure and stale.failure.code == "economy.revision_conflict"

    cross_currency = engine.execute(
        _transaction(
            "cross-currency",
            TransferFunds("player-a", "jade-player", 1),
            revisions={
                "player-a": state.accounts["player-a"].revision,
                "jade-player": state.accounts["jade-player"].revision,
            },
        ),
        state=state,
        context=_context(seed=705),
    )
    assert cross_currency.failure and cross_currency.failure.code == "economy.currency_mismatch"

    issuer_transfer = engine.execute(
        _transaction(
            "issuer-normal-transfer",
            TransferFunds("issuer-stone", "player-a", 1),
            revisions={
                "issuer-stone": state.accounts["issuer-stone"].revision,
                "player-a": state.accounts["player-a"].revision,
            },
        ),
        state=state,
        context=_context(seed=706),
    )
    assert issuer_transfer.failure and issuer_transfer.failure.code == "economy.issuer_forbidden"

    duplicate_issuer = engine.execute(
        _transaction(
            "duplicate-issuer",
            OpenLedgerAccount(
                _account(
                    "issuer-stone-two",
                    "owner.system",
                    "system-economy-two",
                    kind=LedgerAccountKind.ISSUER,
                )
            ),
        ),
        state=state,
        context=_context(seed=708),
    )
    assert duplicate_issuer.failure and duplicate_issuer.failure.code == "economy.issuer_exists"


def _assert_expired_hold_release(engine, state):
    expires_at = TIME + timedelta(minutes=5)
    held = _execute(
        engine,
        state,
        _transaction(
            "hold-until-expiry",
            PlaceFundHold(
                "hold-expiring",
                "player-a",
                300,
                "business.reward_choice",
                "choice-1",
                expires_at,
            ),
            revisions={"player-a": state.accounts["player-a"].revision},
        ),
    ).state
    after = _execute(
        engine,
        held,
        _transaction(
            "spend-after-expiry",
            TransferFunds("player-a", "player-b", 300),
            revisions={
                "player-a": held.accounts["player-a"].revision,
                "player-b": held.accounts["player-b"].revision,
            },
        ),
        context=_context(at=expires_at + timedelta(seconds=1), seed=707),
    )
    assert "hold-expiring" not in after.state.holds
    assert [event.values.get("release_cause") for event in after.events] == ["expired", None]


if __name__ == "__main__":
    main()
