"""交换契约、库存与账本的 SQLite 联合事务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from ..gameplay.context import RuleContext
from ..gameplay.economy import LedgerState
from ..gameplay.errors import RuleOutcome
from ..gameplay.exchange import ExchangeCommand, ExchangeEngine, ExchangeExecution, ExchangeState
from ..gameplay.inventory import InventoryState

from .errors import TransactionMismatch
from .snapshots import (
    EXCHANGE_AGGREGATE,
    INVENTORY_AGGREGATE,
    LEDGER_AGGREGATE,
    SnapshotRepository,
)
from .sqlite import SqliteDatabase


@dataclass(frozen=True)
class PersistedExchangeExecution:
    execution: ExchangeExecution
    replayed: bool = False


class PersistedExchangeService:
    def __init__(
        self,
        database: SqliteDatabase,
        engine: ExchangeEngine,
        snapshots: SnapshotRepository | None = None,
    ) -> None:
        self.database = database
        self.engine = engine
        self.snapshots = snapshots or SnapshotRepository()

    def initialize(
        self,
        state: ExchangeState,
        *,
        logical_time: datetime,
    ) -> ExchangeState:
        _aware(logical_time)
        with self.database.unit_of_work() as uow:
            current = self.snapshots.load(
                uow,
                EXCHANGE_AGGREGATE,
                state.scope_id,
                ExchangeState,
            )
            if current is None:
                self.snapshots.insert(
                    uow,
                    EXCHANGE_AGGREGATE,
                    state.scope_id,
                    state,
                    logical_time,
                )
                current = state
            uow.commit()
        return current

    def load(self, scope_id: str) -> ExchangeState | None:
        with self.database.unit_of_work(write=False) as uow:
            return self.snapshots.load(
                uow,
                EXCHANGE_AGGREGATE,
                scope_id,
                ExchangeState,
            )

    def execute(
        self,
        command: ExchangeCommand,
        *,
        exchange_id: str,
        inventory_id: str,
        ledger_id: str,
        context: RuleContext,
    ) -> RuleOutcome[PersistedExchangeExecution]:
        checkpoint = context.random.checkpoint()
        try:
            with self.database.unit_of_work() as uow:
                fingerprint = self._fingerprint(command, exchange_id, inventory_id, ledger_id)
                previous_tx = uow.load_transaction(command.id)
                if previous_tx is not None:
                    if previous_tx.fingerprint != fingerprint or previous_tx.scope_id != exchange_id:
                        raise TransactionMismatch(
                            f"同一交换事务 ID 对应不同内容：{command.id}"
                        )
                    execution = self.snapshots.codec.loads(
                        previous_tx.receipt_payload,
                        ExchangeExecution,
                    )
                    return RuleOutcome.success(PersistedExchangeExecution(execution, True))
                exchange = self.snapshots.require(
                    uow,
                    EXCHANGE_AGGREGATE,
                    exchange_id,
                    ExchangeState,
                )
                inventory = self.snapshots.require(
                    uow,
                    INVENTORY_AGGREGATE,
                    inventory_id,
                    InventoryState,
                )
                ledger = self.snapshots.require(
                    uow,
                    LEDGER_AGGREGATE,
                    ledger_id,
                    LedgerState,
                )
                outcome = self.engine.execute(
                    command,
                    exchange=exchange,
                    inventory_state=inventory,
                    ledger_state=ledger,
                    context=context,
                )
                if outcome.failure:
                    return RuleOutcome.failed(outcome.failure)
                assert outcome.value is not None
                self._update_if_changed(
                    uow,
                    EXCHANGE_AGGREGATE,
                    exchange_id,
                    exchange,
                    outcome.value.exchange,
                    context.logical_time,
                )
                self._update_if_changed(
                    uow,
                    INVENTORY_AGGREGATE,
                    inventory_id,
                    inventory,
                    outcome.value.inventory,
                    context.logical_time,
                )
                self._update_if_changed(
                    uow,
                    LEDGER_AGGREGATE,
                    ledger_id,
                    ledger,
                    outcome.value.ledger,
                    context.logical_time,
                )
                timestamp = context.logical_time.isoformat()
                uow.insert_transaction(
                    command.id,
                    fingerprint,
                    exchange_id,
                    self.snapshots.codec.dumps(outcome.value),
                    timestamp,
                )
                for sequence, event in enumerate(outcome.value.events):
                    uow.append_fact(
                        command.id,
                        sequence,
                        event.kind,
                        self.snapshots.codec.dumps(event),
                        timestamp,
                    )
                uow.commit()
                return RuleOutcome.success(PersistedExchangeExecution(outcome.value))
        except Exception:
            context.random.restore(checkpoint)
            raise

    def _update_if_changed(self, uow, kind, aggregate_id, previous, current, logical_time):
        if current != previous:
            self.snapshots.update(
                uow,
                kind,
                aggregate_id,
                previous,
                current,
                logical_time,
            )

    def _fingerprint(self, command, exchange_id, inventory_id, ledger_id) -> str:
        payload = "\0".join(
            (
                "exchange-command.v1",
                exchange_id,
                inventory_id,
                ledger_id,
                self.snapshots.codec.dumps(command),
            )
        )
        return sha256(payload.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("交换持久化逻辑时间必须包含时区")


__all__ = ["PersistedExchangeExecution", "PersistedExchangeService"]
