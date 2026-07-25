"""环形彩票、归航库支出和幂等开奖测试。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services  # noqa: E402
from game.content.catalog.foundation import PRIMARY_CURRENCY_ID  # noqa: E402
from game.core.account import ExternalIdentity, IdentityEvidence  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    IssueFunds,
    LedgerAccount,
    LedgerState,
    LedgerTransaction,
    OpenLedgerAccount,
    RuleContext,
    Ruleset,
    SeededRandomSource,
)
from game.core.persistence import LEDGER_AGGREGATE  # noqa: E402
from game.features.lottery import service as lottery_service  # noqa: E402
from game.rules.character import PRIMARY_ISSUER_ACCOUNT_ID, PRIMARY_LEDGER_ID  # noqa: E402
from game.rules.economy import PRIMARY_TAX_ACCOUNT_ID, PRIMARY_TAX_OWNER_ID  # noqa: E402
from game.rules.lottery import circular_distance, pool_breakdown, prize_tiers  # noqa: E402


ZONE = ZoneInfo("Asia/Shanghai")
SIGNUP_TIME = datetime(2026, 7, 19, 12, 0, tzinfo=ZONE)
DRAW_TIME = datetime(2026, 7, 19, 21, 0, tzinfo=ZONE)


def main() -> None:
    assert circular_distance("000000", "999999") == 1
    assert circular_distance("250000", "750000") == 500_000
    assert pool_breakdown(1_000, 0) == (0, 0, 0)
    assert pool_breakdown(40, 2) == (40, 0, 40)
    assert pool_breakdown(1_000, 2) == (40, 160, 200)
    assert pool_breakdown(1_000_000, 1_000) == (20_000, 0, 20_000)
    assert pool_breakdown(1_000_000, 1_001) == (20_020, 0, 20_000)
    assert prize_tiers(1) == ()
    assert prize_tiers(2) == (("一等奖", 1, 1.0),)
    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "lottery.db",
            identity_secret="lottery-system-secret",
        )
        services.database.initialize()
        services.economy.initialize(logical_time=SIGNUP_TIME)
        services.lottery.initialize(logical_time=SIGNUP_TIME)
        characters = tuple(
            _create_character(services, f"player-{index}", f"玩家{index}")
            for index in range(1, 5)
        )
        _fund_tax(services, 1_000_000)
        numbers = ("000000", "999999", "100000", "500000")
        wallet_before_purchase = {
            character.id: _wallet_balance(services, character.id)
            for character in characters
        }
        for character, number in zip(characters, numbers):
            message = services.lottery.purchase(
                character.id,
                character.name,
                number,
                logical_time=SIGNUP_TIME,
            )
            assert number in message
        assert all(
            _wallet_balance(services, character.id)
            == wallet_before_purchase[character.id] - 20
            for character in characters
        )
        assert _tax_balance(services) == 1_000_080
        assert "已经购买彩票" in services.lottery.purchase(
            characters[0].id,
            characters[0].name,
            "000000",
            logical_time=SIGNUP_TIME,
        )
        first_balance = _wallet_balance(services, characters[0].id)
        repeated = services.lottery.purchase(
            characters[0].id,
            characters[0].name,
            "000001",
            logical_time=SIGNUP_TIME,
        )
        assert "000000" in repeated and "不能追加或更换" in repeated
        assert _wallet_balance(services, characters[0].id) == first_balance
        second_balance = _wallet_balance(services, characters[1].id)
        repeated = services.lottery.purchase(
            characters[1].id,
            characters[1].name,
            "222222",
            logical_time=SIGNUP_TIME,
        )
        assert "999999" in repeated and "不能追加或更换" in repeated
        assert _wallet_balance(services, characters[1].id) == second_balance
        second_view = services.lottery.status(
            characters[1].id,
            logical_time=SIGNUP_TIME,
        )
        assert second_view.current_ticket is not None
        assert second_view.current_ticket.number == "999999"
        try:
            services.lottery.purchase(
                "another-character",
                "后来者",
                "000000",
                logical_time=SIGNUP_TIME,
            )
        except ValueError as exc:
            assert "已被购买" in str(exc)
        else:
            raise AssertionError("同轮次重复号码必须被拒绝")

        wallet_before = {
            character.id: _wallet_balance(services, character.id)
            for character in characters
        }
        original_randbelow = lottery_service.secrets.randbelow
        lottery_service.secrets.randbelow = lambda upper: 0
        try:
            summary = services.lottery.draw_due(logical_time=DRAW_TIME)
        finally:
            lottery_service.secrets.randbelow = original_randbelow
        assert summary == ("2026-07-19: 4 张，支出 400",)
        view = services.lottery.status(characters[0].id, logical_time=DRAW_TIME)
        assert view.due_round is not None
        assert view.due_round.winning_number == "000000"
        assert view.due_round.pool_amount == 400
        assert view.due_round.payout_amount == 400
        assert [winner.number for winner in view.due_round.winners] == [
            "000000",
            "999999",
            "100000",
            "500000",
        ]
        assert [winner.distance for winner in view.due_round.winners] == [
            0,
            1,
            100_000,
            500_000,
        ]
        assert [winner.amount for winner in view.due_round.winners] == [240, 54, 53, 53]
        assert _tax_balance(services) == 999_680
        assert _wallet_balance(services, characters[0].id) == wallet_before[characters[0].id] + 240
        assert _wallet_balance(services, characters[1].id) == wallet_before[characters[1].id] + 54
        assert _wallet_balance(services, characters[2].id) == wallet_before[characters[2].id] + 53
        assert _wallet_balance(services, characters[3].id) == wallet_before[characters[3].id] + 53
        assert services.lottery.draw_due(logical_time=DRAW_TIME) == ()
        assert _tax_balance(services) == 999_680
    _assert_underfilled_round_refunds()
    _assert_ticket_sales_fund_small_draw()
    print("lottery system tests passed")


def _assert_underfilled_round_refunds() -> None:
    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "lottery-waiting.db",
            identity_secret="lottery-waiting-secret",
        )
        services.database.initialize()
        services.economy.initialize(logical_time=SIGNUP_TIME)
        services.lottery.initialize(logical_time=SIGNUP_TIME)
        character = _create_character(services, "waiting-player", "等待者")
        wallet_before = _wallet_balance(services, character.id)
        services.lottery.purchase(
            character.id,
            character.name,
            "123456",
            logical_time=SIGNUP_TIME,
        )
        result = services.lottery.draw_due(logical_time=DRAW_TIME)
        assert result == ("2026-07-19: 参与不足，已退回 20",)
        view = services.lottery.status(character.id, logical_time=DRAW_TIME)
        assert view.due_round is not None and view.due_round.status == "skipped"
        assert view.due_round.reason == "参与不足，票款已退回"
        assert view.due_round.winning_number == ""
        assert _wallet_balance(services, character.id) == wallet_before
        assert _tax_balance(services) == 0


def _assert_ticket_sales_fund_small_draw() -> None:
    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "lottery-small.db",
            identity_secret="lottery-small-secret",
        )
        services.database.initialize()
        services.economy.initialize(logical_time=SIGNUP_TIME)
        services.lottery.initialize(logical_time=SIGNUP_TIME)
        first = _create_character(services, "small-first", "小服甲")
        second = _create_character(services, "small-second", "小服乙")
        services.lottery.purchase(first.id, first.name, "000000", logical_time=SIGNUP_TIME)
        services.lottery.purchase(second.id, second.name, "500000", logical_time=SIGNUP_TIME)
        original_randbelow = lottery_service.secrets.randbelow
        lottery_service.secrets.randbelow = lambda upper: 0
        try:
            summary = services.lottery.draw_due(logical_time=DRAW_TIME)
        finally:
            lottery_service.secrets.randbelow = original_randbelow
        assert summary == ("2026-07-19: 2 张，支出 40",)
        view = services.lottery.status(first.id, logical_time=DRAW_TIME)
        assert view.due_round is not None
        assert view.due_round.pool_amount == 40
        assert view.due_round.payout_amount == 40
        assert view.due_round.winners[0].character_id == first.id
        assert view.due_round.winners[0].amount == 40
        assert _tax_balance(services) == 0


def _create_character(services, external_id: str, name: str):
    evidence = IdentityEvidence(
        f"evidence:{external_id}",
        ExternalIdentity(
            "platform.local",
            "lottery-test",
            "identity.user",
            "private",
            external_id,
        ),
        (),
        "message.local",
        SIGNUP_TIME,
    )
    created = services.create_character(evidence, requested_name=name)
    assert created.status == "created" and created.receipt is not None
    return created.receipt.character


def _fund_tax(services, amount: int) -> None:
    with services.database.unit_of_work() as uow:
        ledger = services.lottery.snapshots.require(
            uow,
            LEDGER_AGGREGATE,
            PRIMARY_LEDGER_ID,
            LedgerState,
        )
        issuer = ledger.accounts[PRIMARY_ISSUER_ACCOUNT_ID]
        tax = LedgerAccount(
            PRIMARY_TAX_ACCOUNT_ID,
            "owner.tax_authority",
            PRIMARY_TAX_OWNER_ID,
            PRIMARY_CURRENCY_ID,
        )
        outcome = services.lottery.ledger_engine.execute(
            LedgerTransaction(
                "lottery-test:fund-tax",
                "system.test",
                "economy.test_tax_income",
                (
                    OpenLedgerAccount(tax),
                    IssueFunds(issuer.id, tax.id, amount),
                ),
                expected_revisions={issuer.id: issuer.revision},
            ),
            state=ledger,
            context=_context("lottery-test:fund-tax"),
        )
        assert outcome.ok and outcome.value is not None, outcome.failure
        services.lottery.snapshots.update(
            uow,
            LEDGER_AGGREGATE,
            PRIMARY_LEDGER_ID,
            ledger,
            outcome.value.state,
            SIGNUP_TIME,
        )
        uow.commit()


def _wallet_balance(services, character_id: str) -> int:
    ledger = _ledger(services)
    return next(
        account.balance
        for account in ledger.accounts.values()
        if account.owner_kind == "owner.character" and account.owner_id == character_id
    )


def _tax_balance(services) -> int:
    return _ledger(services).accounts[PRIMARY_TAX_ACCOUNT_ID].balance


def _ledger(services) -> LedgerState:
    with services.database.unit_of_work(write=False) as uow:
        return services.lottery.snapshots.require(
            uow,
            LEDGER_AGGREGATE,
            PRIMARY_LEDGER_ID,
            LedgerState,
        )


def _context(trace_id: str) -> RuleContext:
    return RuleContext(
        trace_id,
        "rules.lottery_test.v1",
        Ruleset("ruleset.lottery_test"),
        SIGNUP_TIME,
        SeededRandomSource(trace_id),
    )


if __name__ == "__main__":
    main()
