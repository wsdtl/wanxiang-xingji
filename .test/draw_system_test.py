"""抽奖扣签、混合奖励、保底状态和幂等事务测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services  # noqa: E402
from game.content import (  # noqa: E402
    BREAKTHROUGH_TOKEN_ITEM_ID,
    DRAW_CATALOG_CONTENT,
    DRAW_REWARD_LOW_CURRENCY_ID,
    DRAW_REWARD_MID_CURRENCY_ID,
    DRAW_TICKET_ITEM_ID,
    DIMENSION_SHIFT_ITEM_ID,
    COMPANION_SANCTUARY_ITEM_ID,
    CHARACTER_EXPERIENCE_ITEM_ID,
    COMPANION_EXPERIENCE_ITEM_ID,
    WEAPON_EXPERIENCE_ITEM_ID,
    WEAPON_MAXIMUM_LEVEL_ITEM_ID,
    BACKPACK_CAPACITY_ITEM_ID,
    DRAW_BREAKTHROUGH_GUARANTEE_SLOT_ID,
    DRAW_BREAKTHROUGH_PITY_THRESHOLD,
    DRAW_BREAKTHROUGH_WEIGHT,
)
from game.core.account import ExternalIdentity, IdentityEvidence  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    GrantStack,
    InventoryState,
    InventoryTransaction,
    LedgerState,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    SourceReceipt,
)
from game.core.persistence import INVENTORY_AGGREGATE, LEDGER_AGGREGATE  # noqa: E402
from game.rules.character import PRIMARY_LEDGER_ID  # noqa: E402


TIME = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
CURRENCY_AWARD_IDS = {
    DRAW_REWARD_LOW_CURRENCY_ID,
    DRAW_REWARD_MID_CURRENCY_ID,
}


def main() -> None:
    entries = DRAW_CATALOG_CONTENT.loot_table.groups[0].entries
    assert sum(value.weight for value in entries) == 100_000
    assert sum(
        value.weight for value in entries if value.award_id in CURRENCY_AWARD_IDS
    ) == 38_800
    breakthrough_entries = tuple(
        value for value in entries if value.award_id == BREAKTHROUGH_TOKEN_ITEM_ID
    )
    assert len(breakthrough_entries) == 1
    assert breakthrough_entries[0].weight == DRAW_BREAKTHROUGH_WEIGHT
    assert BREAKTHROUGH_TOKEN_ITEM_ID not in DRAW_CATALOG_CONTENT.special_item_ids
    assert DRAW_CATALOG_CONTENT.breakthrough_item_ids == frozenset(
        {BREAKTHROUGH_TOKEN_ITEM_ID}
    )
    slot = DRAW_CATALOG_CONTENT.pool.guarantee_slots[0]
    assert slot.id == DRAW_BREAKTHROUGH_GUARANTEE_SLOT_ID
    assert slot.threshold == DRAW_BREAKTHROUGH_PITY_THRESHOLD == 50
    assert DRAW_CATALOG_CONTENT.special_item_ids == frozenset(
        {
            WEAPON_MAXIMUM_LEVEL_ITEM_ID,
            WEAPON_EXPERIENCE_ITEM_ID,
            BACKPACK_CAPACITY_ITEM_ID,
            DIMENSION_SHIFT_ITEM_ID,
            COMPANION_SANCTUARY_ITEM_ID,
            CHARACTER_EXPERIENCE_ITEM_ID,
            COMPANION_EXPERIENCE_ITEM_ID,
        }
    )
    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "draw.db",
            identity_secret="draw-system-secret",
        )
        services.database.initialize()
        character = _create_character(services)
        _grant_tickets(services, character.id, 20)

        balance_before = _wallet_balance(services, character.id)
        first = services.draw.draw(
            character.id,
            "draw-operation-1",
            10,
            logical_time=TIME,
        )
        assert first.status == "drawn" and first.record is not None
        assert first.ticket_count == 10
        assert len(first.record.receipt.awards) == 10
        currency = sum(
            value.quantity
            for value in first.record.receipt.awards
            if value.award_id in CURRENCY_AWARD_IDS
        )
        assert _wallet_balance(services, character.id) == balance_before + currency
        _assert_item_awards(services, character.id, first.record.receipt.awards)

        inventory_revision = _inventory(services, character.id).revision
        balance_after = _wallet_balance(services, character.id)
        replay = services.draw.draw(
            character.id,
            "draw-operation-1",
            10,
            logical_time=TIME,
        )
        assert replay.status == "replayed" and replay.record == first.record
        assert _inventory(services, character.id).revision == inventory_revision
        assert _wallet_balance(services, character.id) == balance_after

        second = services.draw.draw(
            character.id,
            "draw-operation-2",
            10,
            logical_time=TIME,
        )
        assert second.status == "drawn" and second.ticket_count == 0
        insufficient = services.draw.draw(
            character.id,
            "draw-operation-3",
            1,
            logical_time=TIME,
        )
        assert insufficient.status == "insufficient" and insufficient.ticket_count == 0
        status = services.draw.status(character.id)
        assert len(status.records) == 2
        assert status.records[0].operation_id == "draw-operation-2"
        assert 0 <= status.pity_count < 10
        assert 0 <= status.guarantee_counts[DRAW_BREAKTHROUGH_GUARANTEE_SLOT_ID] < 50

    print("draw system tests passed")


def _create_character(services):
    evidence = IdentityEvidence(
        "evidence:draw-player",
        ExternalIdentity(
            "platform.local",
            "draw-test",
            "identity.user",
            "private",
            "draw-player",
        ),
        (),
        "message.local",
        TIME,
    )
    created = services.create_character(evidence, requested_name="抽签客")
    assert created.status == "created" and created.receipt is not None
    return created.receipt.character


def _grant_tickets(services, character_id: str, quantity: int) -> None:
    with services.database.unit_of_work() as uow:
        inventory = services.draw.snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            InventoryState,
        )
        container_id = next(
            value.id
            for value in inventory.containers.values()
            if value.kind == "container.special"
        )
        outcome = services.draw.inventory_engine.execute(
            InventoryTransaction(
                "grant:draw-tickets",
                character_id,
                "inventory.test_grant",
                (
                    GrantStack(
                        f"stack:{character_id}:{DRAW_TICKET_ITEM_ID}",
                        DRAW_TICKET_ITEM_ID,
                        container_id,
                        quantity,
                        SourceReceipt(
                            "receipt:draw-tickets",
                            "source.test",
                            character_id,
                            TIME,
                        ),
                    ),
                ),
            ),
            state=inventory,
            context=_context("grant:draw-tickets"),
        )
        assert outcome.ok and outcome.value is not None, outcome.failure
        services.draw.snapshots.update(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            inventory,
            outcome.value.state,
            TIME,
        )
        uow.commit()


def _assert_item_awards(services, character_id: str, awards) -> None:
    inventory = _inventory(services, character_id)
    totals: dict[str, int] = {}
    for award in awards:
        if award.award_id not in CURRENCY_AWARD_IDS:
            totals[str(award.award_id)] = totals.get(str(award.award_id), 0) + award.quantity
    for definition_id, quantity in totals.items():
        stack = next(
            value
            for value in inventory.stacks.values()
            if value.definition_id == definition_id
        )
        initial = 2 if "small_" in definition_id else 0
        assert stack.quantity >= initial + quantity


def _inventory(services, character_id: str) -> InventoryState:
    with services.database.unit_of_work(write=False) as uow:
        return services.draw.snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            InventoryState,
        )


def _wallet_balance(services, character_id: str) -> int:
    with services.database.unit_of_work(write=False) as uow:
        ledger = services.draw.snapshots.require(
            uow,
            LEDGER_AGGREGATE,
            PRIMARY_LEDGER_ID,
            LedgerState,
        )
    return next(
        value.balance
        for value in ledger.accounts.values()
        if value.owner_kind == "owner.character" and value.owner_id == character_id
    )


def _context(trace_id: str) -> RuleContext:
    return RuleContext(
        trace_id,
        "rules.draw_test.v1",
        Ruleset("ruleset.draw_test"),
        TIME,
        SeededRandomSource(trace_id),
    )


if __name__ == "__main__":
    main()
