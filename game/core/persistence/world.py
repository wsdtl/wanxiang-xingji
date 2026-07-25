"""世界状态事务和结构化事实的 SQLite 持久化。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from ..gameplay.context import RuleContext
from ..gameplay.errors import RuleOutcome
from ..gameplay.world import WorldEngine, WorldExecution, WorldState, WorldTransaction

from .errors import TransactionMismatch
from .snapshots import SnapshotRepository, WORLD_AGGREGATE
from .sqlite import SqliteDatabase


@dataclass(frozen=True)
class PersistedWorldExecution:
    execution: WorldExecution
    replayed: bool = False


class PersistedWorldService:
    def __init__(
        self,
        database: SqliteDatabase,
        engine: WorldEngine,
        snapshots: SnapshotRepository | None = None,
    ) -> None:
        self.database = database
        self.engine = engine
        self.snapshots = snapshots or SnapshotRepository()

    def initialize(self, world_id: str, *, logical_time: datetime) -> WorldState:
        _aware(logical_time)
        initial = WorldState(world_id)
        with self.database.unit_of_work() as uow:
            current = self.snapshots.load(uow, WORLD_AGGREGATE, world_id, WorldState)
            if current is None:
                self.snapshots.insert(uow, WORLD_AGGREGATE, world_id, initial, logical_time)
                current = initial
            uow.commit()
        return current

    def load(self, world_id: str) -> WorldState | None:
        with self.database.unit_of_work(write=False) as uow:
            return self.snapshots.load(uow, WORLD_AGGREGATE, world_id, WorldState)

    def execute(
        self,
        world_id: str,
        transaction: WorldTransaction,
        *,
        context: RuleContext,
    ) -> RuleOutcome[PersistedWorldExecution]:
        checkpoint = context.random.checkpoint()
        try:
            with self.database.unit_of_work() as uow:
                fingerprint = self._fingerprint(world_id, transaction)
                previous_tx = uow.load_transaction(transaction.id)
                if previous_tx is not None:
                    if previous_tx.fingerprint != fingerprint or previous_tx.scope_id != world_id:
                        raise TransactionMismatch(
                            f"同一世界事务 ID 对应不同内容：{transaction.id}"
                        )
                    execution = self.snapshots.codec.loads(
                        previous_tx.receipt_payload,
                        WorldExecution,
                    )
                    return RuleOutcome.success(PersistedWorldExecution(execution, True))
                state = self.snapshots.require(
                    uow,
                    WORLD_AGGREGATE,
                    world_id,
                    WorldState,
                )
                outcome = self.engine.execute(transaction, state=state, context=context)
                if outcome.failure:
                    return RuleOutcome.failed(outcome.failure)
                assert outcome.value is not None
                self.snapshots.update(
                    uow,
                    WORLD_AGGREGATE,
                    world_id,
                    state,
                    outcome.value.state,
                    context.logical_time,
                )
                timestamp = context.logical_time.isoformat()
                uow.insert_transaction(
                    transaction.id,
                    fingerprint,
                    world_id,
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
                return RuleOutcome.success(PersistedWorldExecution(outcome.value))
        except Exception:
            context.random.restore(checkpoint)
            raise

    def _fingerprint(self, world_id: str, transaction: WorldTransaction) -> str:
        payload = "\0".join(
            ("world-transaction.v1", world_id, self.snapshots.codec.dumps(transaction))
        )
        return sha256(payload.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("世界持久化逻辑时间必须包含时区")


__all__ = ["PersistedWorldExecution", "PersistedWorldService"]
