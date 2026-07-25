"""装配状态与库存位置的 SQLite 原子提交。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from ..gameplay.context import RuleContext
from ..gameplay.errors import RuleOutcome
from ..gameplay.inventory import InventoryState
from ..gameplay.loadout import LoadoutEngine, LoadoutExecution, LoadoutState, LoadoutTransaction

from .errors import TransactionMismatch
from .snapshots import INVENTORY_AGGREGATE, LOADOUT_AGGREGATE, SnapshotRepository
from .sqlite import SqliteDatabase


@dataclass(frozen=True)
class PersistedLoadoutExecution:
    execution: LoadoutExecution
    replayed: bool = False


class PersistedLoadoutService:
    """装配规则唯一数据库写入口。"""

    def __init__(
        self,
        database: SqliteDatabase,
        engine: LoadoutEngine,
        snapshots: SnapshotRepository | None = None,
    ) -> None:
        self.database = database
        self.engine = engine
        self.snapshots = snapshots or SnapshotRepository()

    def initialize(
        self,
        loadout: LoadoutState,
        *,
        logical_time: datetime,
    ) -> LoadoutState:
        _aware(logical_time)
        with self.database.unit_of_work() as uow:
            current = self.snapshots.load(
                uow,
                LOADOUT_AGGREGATE,
                loadout.character_id,
                LoadoutState,
            )
            if current is None:
                self.snapshots.insert(
                    uow,
                    LOADOUT_AGGREGATE,
                    loadout.character_id,
                    loadout,
                    logical_time,
                )
                current = loadout
            uow.commit()
        return current

    def load(self, character_id: str) -> LoadoutState | None:
        with self.database.unit_of_work(write=False) as uow:
            return self.snapshots.load(
                uow,
                LOADOUT_AGGREGATE,
                character_id,
                LoadoutState,
            )

    def execute(
        self,
        transaction: LoadoutTransaction,
        *,
        inventory_id: str,
        character_id: str,
        context: RuleContext,
    ) -> RuleOutcome[PersistedLoadoutExecution]:
        checkpoint = context.random.checkpoint()
        try:
            with self.database.unit_of_work() as uow:
                fingerprint = self._fingerprint(transaction, inventory_id, character_id)
                previous_tx = uow.load_transaction(transaction.id)
                if previous_tx is not None:
                    if previous_tx.fingerprint != fingerprint or previous_tx.scope_id != character_id:
                        raise TransactionMismatch(
                            f"同一装配事务 ID 对应不同内容：{transaction.id}"
                        )
                    execution = self.snapshots.codec.loads(
                        previous_tx.receipt_payload,
                        LoadoutExecution,
                    )
                    return RuleOutcome.success(PersistedLoadoutExecution(execution, True))
                loadout = self.snapshots.require(
                    uow,
                    LOADOUT_AGGREGATE,
                    character_id,
                    LoadoutState,
                )
                inventory = self.snapshots.require(
                    uow,
                    INVENTORY_AGGREGATE,
                    inventory_id,
                    InventoryState,
                )
                outcome = self.engine.execute(
                    transaction,
                    loadout=loadout,
                    inventory_state=inventory,
                    context=context,
                )
                if outcome.failure:
                    return RuleOutcome.failed(outcome.failure)
                assert outcome.value is not None
                self.snapshots.update(
                    uow,
                    LOADOUT_AGGREGATE,
                    character_id,
                    loadout,
                    outcome.value.loadout,
                    context.logical_time,
                )
                if outcome.value.inventory != inventory:
                    self.snapshots.update(
                        uow,
                        INVENTORY_AGGREGATE,
                        inventory_id,
                        inventory,
                        outcome.value.inventory,
                        context.logical_time,
                    )
                timestamp = context.logical_time.isoformat()
                uow.insert_transaction(
                    transaction.id,
                    fingerprint,
                    character_id,
                    self.snapshots.codec.dumps(outcome.value),
                    timestamp,
                )
                for sequence, event in enumerate(outcome.value.events):
                    uow.append_fact(
                        transaction.id,
                        sequence,
                        event.kind,
                        self.snapshots.codec.dumps(event),
                        timestamp,
                    )
                uow.commit()
                return RuleOutcome.success(PersistedLoadoutExecution(outcome.value))
        except Exception:
            context.random.restore(checkpoint)
            raise

    def _fingerprint(
        self,
        transaction: LoadoutTransaction,
        inventory_id: str,
        character_id: str,
    ) -> str:
        payload = "\0".join(
            (
                "loadout-transaction.v1",
                inventory_id,
                character_id,
                self.snapshots.codec.dumps(transaction),
            )
        )
        return sha256(payload.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("装配持久化逻辑时间必须包含时区")


__all__ = ["PersistedLoadoutExecution", "PersistedLoadoutService"]
