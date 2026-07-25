"""组织、社会请求和关系状态的 SQLite 持久化。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from ..gameplay.context import RuleContext
from ..gameplay.errors import RuleOutcome
from ..gameplay.social import SocialCommand, SocialEngine, SocialExecution, SocialState

from .errors import TransactionMismatch
from .snapshots import SOCIAL_AGGREGATE, SnapshotRepository
from .sqlite import SqliteDatabase


@dataclass(frozen=True)
class PersistedSocialExecution:
    execution: SocialExecution
    replayed: bool = False


class PersistedSocialService:
    def __init__(
        self,
        database: SqliteDatabase,
        engine: SocialEngine,
        snapshots: SnapshotRepository | None = None,
    ) -> None:
        self.database = database
        self.engine = engine
        self.snapshots = snapshots or SnapshotRepository()

    def initialize(self, scope_id: str, *, logical_time: datetime) -> SocialState:
        _aware(logical_time)
        initial = SocialState(scope_id)
        with self.database.unit_of_work() as uow:
            current = self.snapshots.load(uow, SOCIAL_AGGREGATE, scope_id, SocialState)
            if current is None:
                self.snapshots.insert(
                    uow,
                    SOCIAL_AGGREGATE,
                    scope_id,
                    initial,
                    logical_time,
                )
                current = initial
            uow.commit()
        return current

    def load(self, scope_id: str) -> SocialState | None:
        with self.database.unit_of_work(write=False) as uow:
            return self.load_in_uow(uow, scope_id)

    def load_in_uow(self, uow, scope_id: str) -> SocialState | None:
        """在调用方已有工作单元内读取社会状态。"""

        return self.snapshots.load(uow, SOCIAL_AGGREGATE, scope_id, SocialState)

    def execute(
        self,
        scope_id: str,
        command: SocialCommand,
        *,
        context: RuleContext,
    ) -> RuleOutcome[PersistedSocialExecution]:
        checkpoint = context.random.checkpoint()
        try:
            with self.database.unit_of_work() as uow:
                outcome = self.execute_in_uow(
                    uow,
                    scope_id,
                    command,
                    context=context,
                )
                if outcome.failure:
                    return outcome
                uow.commit()
                return outcome
        except Exception:
            context.random.restore(checkpoint)
            raise

    def execute_in_uow(
        self,
        uow,
        scope_id: str,
        command: SocialCommand,
        *,
        context: RuleContext,
        state: SocialState | None = None,
    ) -> RuleOutcome[PersistedSocialExecution]:
        """在调用方工作单元中执行并持久化请求。

        需要和战斗、奖励或其他联合事务共用工作单元的 feature 使用此入口；
        社会状态、幂等记录和 outbox 会与调用方的其他写入一起提交。
        """

        fingerprint = self._fingerprint(scope_id, command)
        previous_tx = uow.load_transaction(command.id)
        if previous_tx is not None:
            if previous_tx.fingerprint != fingerprint or previous_tx.scope_id != scope_id:
                raise TransactionMismatch(
                    f"同一社会事务 ID 对应不同内容：{command.id}"
                )
            execution = self.snapshots.codec.loads(
                previous_tx.receipt_payload,
                SocialExecution,
            )
            return RuleOutcome.success(PersistedSocialExecution(execution, True))

        current = state or self.load_in_uow(uow, scope_id)
        is_new = current is None
        current = current or SocialState(scope_id)
        outcome = self.engine.execute(command, state=current, context=context)
        if outcome.failure:
            return RuleOutcome.failed(outcome.failure)
        assert outcome.value is not None
        if is_new:
            self.snapshots.insert(
                uow,
                SOCIAL_AGGREGATE,
                scope_id,
                outcome.value.state,
                context.logical_time,
            )
        else:
            self.snapshots.update(
                uow,
                SOCIAL_AGGREGATE,
                scope_id,
                current,
                outcome.value.state,
                context.logical_time,
            )
        timestamp = context.logical_time.isoformat()
        uow.insert_transaction(
            command.id,
            fingerprint,
            scope_id,
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
        return RuleOutcome.success(PersistedSocialExecution(outcome.value))

    def _fingerprint(self, scope_id: str, command: SocialCommand) -> str:
        payload = "\0".join(
            ("social-command.v1", scope_id, self.snapshots.codec.dumps(command))
        )
        return sha256(payload.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("社会持久化逻辑时间必须包含时区")


__all__ = ["PersistedSocialExecution", "PersistedSocialService"]
