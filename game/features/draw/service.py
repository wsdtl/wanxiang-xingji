"""抽奖签、保底、库存和账本的跨领域原子协调。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import datetime

from game.content.catalog import (
    DRAW_CATALOG_CONTENT,
    DRAW_CURRENCY_COST_PER_ROLL,
    DRAW_POOL_ID,
    DRAW_REWARD_LOW_CURRENCY_ID,
    DRAW_REWARD_MID_CURRENCY_ID,
    DRAW_TICKET_ITEM_ID,
    PRIMARY_CURRENCY_ID,
)
from game.core.gameplay import (
    ConsumeStack,
    CurrencyReward,
    DrawCommand,
    InventoryState,
    InventoryTransaction,
    LedgerAccountKind,
    LedgerEngine,
    LedgerState,
    LedgerTransaction,
    LootState,
    RetireFunds,
    RewardClaimState,
    RewardExpectations,
    RewardSettlement,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    StackItemReward,
)
from game.rules.character import PRIMARY_ISSUER_ACCOUNT_ID, PRIMARY_LEDGER_ID

from .models import (
    DRAW_HISTORY_LIMIT,
    DrawHistoryRecord,
    DrawHistoryState,
    DrawOperationResult,
    DrawPoolView,
    DrawStorageKinds,
)


DRAW_HISTORY_AGGREGATE = "snapshot.draw_history"
DRAW_RULESET_VERSION = "rules.draw.v3"
DRAW_SOURCE_KIND = "source.draw"


class DrawFeature:
    """只协调领域快照；概率和奖项仍由正式内容与抽取内核决定。"""

    def __init__(
        self,
        database,
        content,
        snapshots,
        inventory_engine,
        ledger_engine: LedgerEngine,
        reward_settlement,
        storage: DrawStorageKinds,
        reward_keys_factory,
    ) -> None:
        self.database = database
        self.content = content
        self.snapshots = snapshots
        self.inventory_engine = inventory_engine
        self.ledger_engine = ledger_engine
        self.reward_settlement = reward_settlement
        self.storage = storage
        self.reward_keys_factory = reward_keys_factory

    def draw(
        self,
        character_id: str,
        operation_id: str,
        rolls: int,
        *,
        logical_time: datetime,
    ) -> DrawOperationResult:
        character_id = str(character_id or "").strip()
        operation_id = str(operation_id or "").strip()
        if not character_id or not operation_id or rolls not in (1, 10):
            return DrawOperationResult("rejected", failure_message="抽奖参数无效")

        with self.database.unit_of_work() as uow:
            stored_history = self.snapshots.load(
                uow,
                self.storage.history,
                character_id,
                DrawHistoryState,
            )
            history = stored_history or DrawHistoryState(character_id)
            existing = history.find(operation_id)
            if existing is not None:
                inventory = self._inventory(uow, character_id)
                loot = self._loot(uow, character_id)
                ledger = self._ledger(uow)
                wallet = _wallet(ledger, character_id)
                return DrawOperationResult(
                    "replayed",
                    existing,
                    self._ticket_count(inventory),
                    self._pity_count(loot),
                    guarantee_counts=self._guarantee_counts(loot),
                    currency_available=ledger.available_balance(
                        wallet.id,
                        logical_time=logical_time,
                    ),
                )

            inventory = self._inventory(uow, character_id)
            loot = self._loot(uow, character_id)
            ledger = self._ledger(uow)
            wallet = _wallet(ledger, character_id)
            issuer = ledger.accounts[PRIMARY_ISSUER_ACCOUNT_ID]
            ticket_operations = self._ticket_operations(
                inventory,
                rolls,
                logical_time,
            )
            tickets_spent = sum(value.quantity for value in ticket_operations)
            currency_spent = (rolls - tickets_spent) * DRAW_CURRENCY_COST_PER_ROLL
            currency_available = ledger.available_balance(
                wallet.id,
                logical_time=logical_time,
            )
            if currency_available < currency_spent:
                return DrawOperationResult(
                    "insufficient",
                    ticket_count=self._ticket_count(inventory),
                    pity_count=self._pity_count(loot),
                    failure_message="可用主货币不足，抽奖没有执行",
                    guarantee_counts=self._guarantee_counts(loot),
                    currency_available=currency_available,
                    currency_required=currency_spent,
                )

            context = _context(operation_id, logical_time)
            draw_outcome = self.content.catalog.draw_engine.draw(
                DrawCommand(
                    f"draw:{operation_id}",
                    character_id,
                    DRAW_POOL_ID,
                    loot.revision,
                    rolls,
                ),
                state=loot,
                context=context,
            )
            if draw_outcome.failure or draw_outcome.value is None:
                message = draw_outcome.failure.message if draw_outcome.failure else "抽奖失败"
                return DrawOperationResult("rejected", failure_message=message)
            execution = draw_outcome.value

            consumed_inventory = inventory
            if ticket_operations:
                inventory_outcome = self.inventory_engine.execute(
                    InventoryTransaction(
                        f"draw-ticket:{operation_id}",
                        character_id,
                        "inventory.consume_draw_ticket",
                        ticket_operations,
                    ),
                    state=inventory,
                    context=context,
                )
                if inventory_outcome.failure or inventory_outcome.value is None:
                    message = (
                        inventory_outcome.failure.message
                        if inventory_outcome.failure
                        else "抽奖签扣除失败"
                    )
                    return DrawOperationResult("rejected", failure_message=message)
                consumed_inventory = inventory_outcome.value.state
                self.snapshots.update(
                    uow,
                    self.storage.inventory,
                    character_id,
                    inventory,
                    consumed_inventory,
                    logical_time,
                )
            self.snapshots.update(
                uow,
                self.storage.loot,
                character_id,
                loot,
                execution.loot_state,
                logical_time,
            )

            paid_ledger = ledger
            if currency_spent:
                payment_outcome = self.ledger_engine.execute(
                    LedgerTransaction(
                        f"draw-payment:{operation_id}",
                        character_id,
                        "economy.draw_currency_payment",
                        (RetireFunds(wallet.id, issuer.id, currency_spent),),
                        expected_revisions={
                            wallet.id: wallet.revision,
                            issuer.id: issuer.revision,
                        },
                        metadata={
                            "pool_id": DRAW_POOL_ID,
                            "rolls": rolls,
                            "tickets_spent": tickets_spent,
                            "currency_spent": currency_spent,
                        },
                    ),
                    state=ledger,
                    context=context,
                )
                if payment_outcome.failure or payment_outcome.value is None:
                    message = (
                        payment_outcome.failure.message
                        if payment_outcome.failure
                        else "抽奖货币扣除失败"
                    )
                    return DrawOperationResult("rejected", failure_message=message)
                paid_ledger = payment_outcome.value.state
                self.snapshots.update(
                    uow,
                    self.storage.ledger,
                    PRIMARY_LEDGER_ID,
                    ledger,
                    paid_ledger,
                    logical_time,
                )

            claim = self.snapshots.require(
                uow,
                self.storage.reward_claim,
                character_id,
                RewardClaimState,
            )
            rewards, has_items, has_currency = self._rewards(
                character_id,
                consumed_inventory,
                paid_ledger,
                execution.receipt.awards,
            )
            wallet = _wallet(paid_ledger, character_id)
            issuer = paid_ledger.accounts[PRIMARY_ISSUER_ACCOUNT_ID]
            settlement = RewardSettlement(
                f"draw-reward:{operation_id}",
                character_id,
                character_id,
                DRAW_SOURCE_KIND,
                operation_id,
                rewards,
                RewardExpectations(
                    claim_revision=claim.revision,
                    inventory_revision=consumed_inventory.revision if has_items else None,
                    ledger_account_revisions=(
                        {issuer.id: issuer.revision, wallet.id: wallet.revision}
                        if has_currency
                        else {}
                    ),
                ),
                {
                    "pool_id": DRAW_POOL_ID,
                    "rolls": rolls,
                    "tickets_spent": tickets_spent,
                    "currency_spent": currency_spent,
                },
            )
            reward_outcome = self.reward_settlement.settle_in_uow(
                uow,
                settlement,
                self.reward_keys_factory(character_id, PRIMARY_LEDGER_ID),
                context=context,
            )
            if reward_outcome.failure or reward_outcome.value is None:
                message = reward_outcome.failure.message if reward_outcome.failure else "奖励入账失败"
                return DrawOperationResult("rejected", failure_message=message)

            record = DrawHistoryRecord(
                operation_id,
                execution.receipt,
                logical_time,
                tickets_spent,
                currency_spent,
            )
            updated_history = replace(
                history,
                records=(record, *history.records)[:DRAW_HISTORY_LIMIT],
                revision=history.revision + 1,
            )
            if stored_history is None:
                self.snapshots.insert(
                    uow,
                    self.storage.history,
                    character_id,
                    updated_history,
                    logical_time,
                )
            else:
                self.snapshots.update(
                    uow,
                    self.storage.history,
                    character_id,
                    history,
                    updated_history,
                    logical_time,
                )
            uow.commit()
            final_inventory = reward_outcome.value.snapshot.inventory
            final_ledger = reward_outcome.value.snapshot.ledger
            final_wallet = _wallet(final_ledger, character_id)
            return DrawOperationResult(
                "drawn",
                record,
                self._ticket_count(final_inventory),
                self._pity_count(execution.loot_state),
                guarantee_counts=self._guarantee_counts(execution.loot_state),
                currency_available=final_ledger.available_balance(
                    final_wallet.id,
                    logical_time=logical_time,
                ),
            )

    def status(self, character_id: str, *, history_limit: int = 10) -> DrawPoolView:
        with self.database.unit_of_work(write=False) as uow:
            inventory = self._inventory(uow, character_id)
            loot = self._loot(uow, character_id)
            ledger = self._ledger(uow)
            history = self._load_history(uow, character_id)
            return DrawPoolView(
                self._ticket_count(inventory),
                self._pity_count(loot),
                history.records[: max(0, history_limit)],
                self._guarantee_counts(loot),
                _wallet(ledger, character_id).balance,
            )

    def _rewards(self, character_id, inventory, ledger, awards):
        currency_amount = 0
        item_quantities: dict[str, int] = defaultdict(int)
        for award in awards:
            if award.award_id in {
                DRAW_REWARD_LOW_CURRENCY_ID,
                DRAW_REWARD_MID_CURRENCY_ID,
            }:
                currency_amount += award.quantity
            else:
                item_quantities[str(award.award_id)] += award.quantity

        rewards: list[object] = []
        wallet = _wallet(ledger, character_id)
        if currency_amount:
            rewards.append(
                CurrencyReward(
                    PRIMARY_ISSUER_ACCOUNT_ID,
                    wallet.id,
                    currency_amount,
                )
            )
        special_container_id = next(
            value.id
            for value in inventory.containers.values()
            if value.kind == "container.special"
        )
        for definition_id, quantity in sorted(item_quantities.items()):
            existing = next(
                (
                    value
                    for value in inventory.stacks.values()
                    if value.definition_id == definition_id
                    and value.container_id == special_container_id
                ),
                None,
            )
            rewards.append(
                StackItemReward(
                    existing.id if existing else f"stack:{character_id}:{definition_id}",
                    definition_id,
                    special_container_id,
                    quantity,
                    {"source": DRAW_SOURCE_KIND},
                )
            )
        return tuple(rewards), bool(item_quantities), bool(currency_amount)

    def _load_history(self, uow, character_id: str) -> DrawHistoryState:
        return self.snapshots.load(
            uow,
            self.storage.history,
            character_id,
            DrawHistoryState,
        ) or DrawHistoryState(character_id)

    def _inventory(self, uow, character_id: str) -> InventoryState:
        return self.snapshots.require(
            uow,
            self.storage.inventory,
            character_id,
            InventoryState,
        )

    def _loot(self, uow, character_id: str) -> LootState:
        return self.snapshots.require(
            uow,
            self.storage.loot,
            character_id,
            LootState,
        )

    def _ledger(self, uow) -> LedgerState:
        return self.snapshots.require(
            uow,
            self.storage.ledger,
            PRIMARY_LEDGER_ID,
            LedgerState,
        )

    @staticmethod
    def _ticket_operations(
        inventory: InventoryState,
        rolls: int,
        logical_time: datetime,
    ) -> tuple[ConsumeStack, ...]:
        remaining = rolls
        operations: list[ConsumeStack] = []
        stacks = sorted(
            (
                value
                for value in inventory.stacks.values()
                if value.definition_id == DRAW_TICKET_ITEM_ID
            ),
            key=lambda value: value.id,
        )
        for stack in stacks:
            reserved = sum(
                value.quantity
                for value in inventory.reservations_for(stack.id)
                if not value.expired_at(logical_time)
            )
            quantity = min(remaining, max(0, stack.quantity - reserved))
            if quantity:
                operations.append(ConsumeStack(stack.id, quantity))
                remaining -= quantity
            if remaining == 0:
                break
        return tuple(operations)

    @staticmethod
    def _ticket_count(inventory: InventoryState) -> int:
        return sum(
            value.quantity
            for value in inventory.stacks.values()
            if value.definition_id == DRAW_TICKET_ITEM_ID
        )

    @staticmethod
    def _pity_count(loot: LootState) -> int:
        return int(loot.pity_counters.get(DRAW_CATALOG_CONTENT.loot_table.id, 0))

    @staticmethod
    def _guarantee_counts(loot: LootState) -> dict[str, int]:
        return {
            str(slot.id): int(loot.pity_counters.get(slot.id, 0))
            for slot in DRAW_CATALOG_CONTENT.pool.guarantee_slots
        }


def _wallet(ledger: LedgerState, character_id: str):
    try:
        return next(
            account
            for account in ledger.accounts.values()
            if account.kind is LedgerAccountKind.STANDARD
            and account.owner_kind == "owner.character"
            and account.owner_id == character_id
            and account.currency_id == PRIMARY_CURRENCY_ID
        )
    except StopIteration as exc:
        raise ValueError("当前角色缺少主货币钱包") from exc


def _context(operation_id: str, logical_time: datetime) -> RuleContext:
    return RuleContext(
        f"draw:{operation_id}",
        DRAW_RULESET_VERSION,
        Ruleset("ruleset.draw"),
        logical_time,
        SeededRandomSource(operation_id),
    )


__all__ = [
    "DRAW_HISTORY_AGGREGATE",
    "DRAW_RULESET_VERSION",
    "DrawFeature",
]
