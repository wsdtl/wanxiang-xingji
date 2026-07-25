"""掉落保底状态和审计凭据的 SQLite 持久化。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from ..gameplay.context import RuleContext
from ..gameplay.errors import RuleOutcome
from ..gameplay.loot import LootEngine, LootExecution, LootRollCommand, LootState

from .errors import TransactionMismatch
from .snapshots import LOOT_AGGREGATE, SnapshotRepository
from .sqlite import SqliteDatabase


@dataclass(frozen=True)
class PersistedLootExecution:
    execution: LootExecution
    replayed: bool = False


class PersistedLootService:
    def __init__(
        self,
        database: SqliteDatabase,
        engine: LootEngine,
        snapshots: SnapshotRepository | None = None,
    ) -> None:
        self.database = database
        self.engine = engine
        self.snapshots = snapshots or SnapshotRepository()

    def initialize(self, owner_id: str, *, logical_time: datetime) -> LootState:
        _aware(logical_time)
        initial = LootState(owner_id)
        with self.database.unit_of_work() as uow:
            current = self.snapshots.load(uow, LOOT_AGGREGATE, owner_id, LootState)
            if current is None:
                self.snapshots.insert(
                    uow,
                    LOOT_AGGREGATE,
                    owner_id,
                    initial,
                    logical_time,
                )
                current = initial
            uow.commit()
        return current

    def load(self, owner_id: str) -> LootState | None:
        with self.database.unit_of_work(write=False) as uow:
            return self.snapshots.load(uow, LOOT_AGGREGATE, owner_id, LootState)

    def roll(
        self,
        command: LootRollCommand,
        *,
        context: RuleContext,
    ) -> RuleOutcome[PersistedLootExecution]:
        checkpoint = context.random.checkpoint()
        try:
            with self.database.unit_of_work() as uow:
                fingerprint = self._fingerprint(command)
                previous_tx = uow.load_transaction(command.id)
                if previous_tx is not None:
                    if previous_tx.fingerprint != fingerprint or previous_tx.scope_id != command.actor_id:
                        raise TransactionMismatch(
                            f"同一掉落事务 ID 对应不同内容：{command.id}"
                        )
                    execution = self.snapshots.codec.loads(
                        previous_tx.receipt_payload,
                        LootExecution,
                    )
                    return RuleOutcome.success(PersistedLootExecution(execution, True))
                state = self.snapshots.require(
                    uow,
                    LOOT_AGGREGATE,
                    command.actor_id,
                    LootState,
                )
                outcome = self.engine.roll(command, state=state, context=context)
                if outcome.failure:
                    return RuleOutcome.failed(outcome.failure)
                assert outcome.value is not None
                self.snapshots.update(
                    uow,
                    LOOT_AGGREGATE,
                    command.actor_id,
                    state,
                    outcome.value.state,
                    context.logical_time,
                )
                timestamp = context.logical_time.isoformat()
                uow.insert_transaction(
                    command.id,
                    fingerprint,
                    command.actor_id,
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
                return RuleOutcome.success(PersistedLootExecution(outcome.value))
        except Exception:
            context.random.restore(checkpoint)
            raise

    def _fingerprint(self, command: LootRollCommand) -> str:
        payload = self.snapshots.codec.dumps(command)
        return sha256(("loot-roll.v1\0" + payload).encode("utf-8")).hexdigest()


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("掉落持久化逻辑时间必须包含时区")


__all__ = ["PersistedLootExecution", "PersistedLootService"]
