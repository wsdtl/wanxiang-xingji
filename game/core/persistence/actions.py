"""行动状态、生命周期与奖励领取的 SQLite 原子提交。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from ..gameplay.actions import (
    ActionEngine,
    ActionExecution,
    ActionState,
    ActionTransaction,
    ClaimAction,
)
from ..gameplay.context import RuleContext
from ..gameplay.errors import RuleFailure, RuleOutcome
from ..gameplay.rewards import RewardSettlement, RewardSettlementExecution

from .errors import CorruptPersistenceData, TransactionMismatch
from .rewards import PersistedRewardSettlementService, RewardSettlementStorageKeys
from .snapshots import ACTION_AGGREGATE, SnapshotRepository
from .sqlite import SqliteDatabase, SqliteUnitOfWork


@dataclass(frozen=True)
class PersistedActionExecution:
    execution: ActionExecution
    replayed: bool = False


@dataclass(frozen=True)
class PersistedActionClaimExecution:
    action: ActionExecution
    reward: RewardSettlementExecution
    replayed: bool = False


class PersistedActionService:
    """行动规则唯一数据库入口。"""

    def __init__(
        self,
        database: SqliteDatabase,
        engine: ActionEngine,
        snapshots: SnapshotRepository | None = None,
    ) -> None:
        self.database = database
        self.engine = engine
        self.snapshots = snapshots or SnapshotRepository()

    def initialize(self, owner_id: str, *, logical_time: datetime) -> ActionState:
        _aware(logical_time)
        initial = ActionState(owner_id)
        with self.database.unit_of_work() as uow:
            current = self.snapshots.load(uow, ACTION_AGGREGATE, owner_id, ActionState)
            if current is None:
                self.snapshots.insert(
                    uow,
                    ACTION_AGGREGATE,
                    owner_id,
                    initial,
                    logical_time,
                )
                current = initial
            uow.commit()
        return current

    def load(self, owner_id: str) -> ActionState | None:
        with self.database.unit_of_work(write=False) as uow:
            return self.snapshots.load(uow, ACTION_AGGREGATE, owner_id, ActionState)

    def execute(
        self,
        transaction: ActionTransaction,
        *,
        context: RuleContext,
    ) -> RuleOutcome[PersistedActionExecution]:
        checkpoint = context.random.checkpoint()
        try:
            with self.database.unit_of_work() as uow:
                outcome = self.execute_in_uow(uow, transaction, context=context)
                if outcome.failure:
                    return outcome
                uow.commit()
                return outcome
        except Exception:
            context.random.restore(checkpoint)
            raise

    def execute_in_uow(
        self,
        uow: SqliteUnitOfWork,
        transaction: ActionTransaction,
        *,
        context: RuleContext,
    ) -> RuleOutcome[PersistedActionExecution]:
        """在调用方工作单元内提交行动，供跨聚合玩法原子组合。"""

        replay = self._replay(uow, transaction)
        if replay is not None:
            return RuleOutcome.success(PersistedActionExecution(replay, True))
        state = self.snapshots.require(
            uow,
            ACTION_AGGREGATE,
            transaction.actor_id,
            ActionState,
        )
        failure = self._unsettled_claim_failure(transaction, state)
        if failure is not None:
            return RuleOutcome.failed(failure)
        outcome = self.engine.execute(transaction, state=state, context=context)
        if outcome.failure:
            return RuleOutcome.failed(outcome.failure)
        assert outcome.value is not None
        self._commit_execution(
            uow,
            transaction,
            state,
            outcome.value,
            context.logical_time,
        )
        return RuleOutcome.success(PersistedActionExecution(outcome.value))

    def claim_with_reward(
        self,
        transaction: ActionTransaction,
        settlement: RewardSettlement,
        keys: RewardSettlementStorageKeys,
        rewards: PersistedRewardSettlementService,
        *,
        context: RuleContext,
    ) -> RuleOutcome[PersistedActionClaimExecution]:
        if rewards.database.path != self.database.path:
            raise ValueError("行动和奖励服务必须使用同一个数据库")
        if len(transaction.operations) != 1 or not isinstance(
            transaction.operations[0], ClaimAction
        ):
            raise ValueError("带奖励领取必须且只能包含一个 ClaimAction")
        checkpoint = context.random.checkpoint()
        try:
            with self.database.unit_of_work() as uow:
                replay = self._replay(uow, transaction)
                if replay is not None:
                    reward = rewards.settle_in_uow(uow, settlement, keys, context=context)
                    if reward.failure or reward.value is None or not reward.value.replayed:
                        raise CorruptPersistenceData("行动领取记录与奖励事务不一致")
                    return RuleOutcome.success(
                        PersistedActionClaimExecution(replay, reward.value, True)
                    )
                state = self.snapshots.require(
                    uow,
                    ACTION_AGGREGATE,
                    transaction.actor_id,
                    ActionState,
                )
                action_id = transaction.operations[0].action_id
                record = state.records.get(action_id)
                if record is None or record.result is None:
                    return RuleOutcome.failed(
                        RuleFailure("action.not_completed", "只有已完成行动可以领取")
                    )
                if record.result.settlement_id != settlement.id:
                    return RuleOutcome.failed(
                        RuleFailure("action.settlement_mismatch", "行动奖励结算身份不匹配")
                    )
                reward = rewards.settle_in_uow(uow, settlement, keys, context=context)
                if reward.failure:
                    return RuleOutcome.failed(reward.failure)
                assert reward.value is not None
                if reward.value.replayed:
                    raise CorruptPersistenceData("奖励已提交但行动领取事务不存在")
                outcome = self.engine.execute(transaction, state=state, context=context)
                if outcome.failure:
                    return RuleOutcome.failed(outcome.failure)
                assert outcome.value is not None
                self._commit_execution(uow, transaction, state, outcome.value, context.logical_time)
                uow.commit()
                return RuleOutcome.success(
                    PersistedActionClaimExecution(outcome.value, reward.value)
                )
        except Exception:
            context.random.restore(checkpoint)
            raise

    def _replay(
        self,
        uow: SqliteUnitOfWork,
        transaction: ActionTransaction,
    ) -> ActionExecution | None:
        previous = uow.load_transaction(transaction.id)
        if previous is None:
            return None
        fingerprint = self._fingerprint(transaction)
        if previous.fingerprint != fingerprint or previous.scope_id != transaction.actor_id:
            raise TransactionMismatch(f"同一行动事务 ID 对应不同内容：{transaction.id}")
        return self.snapshots.codec.loads(previous.receipt_payload, ActionExecution)

    def _commit_execution(
        self,
        uow: SqliteUnitOfWork,
        transaction: ActionTransaction,
        previous: ActionState,
        execution: ActionExecution,
        logical_time: datetime,
    ) -> None:
        self.snapshots.update(
            uow,
            ACTION_AGGREGATE,
            transaction.actor_id,
            previous,
            execution.state,
            logical_time,
        )
        timestamp = logical_time.isoformat()
        uow.insert_transaction(
            transaction.id,
            self._fingerprint(transaction),
            transaction.actor_id,
            self.snapshots.codec.dumps(execution),
            timestamp,
        )
        for sequence, event in enumerate(execution.events):
            uow.append_fact(
                transaction.id,
                sequence,
                event.kind,
                self.snapshots.codec.dumps(event),
                timestamp,
            )

    def _fingerprint(self, transaction: ActionTransaction) -> str:
        payload = self.snapshots.codec.dumps(transaction)
        return sha256(("action-transaction.v1\0" + payload).encode("utf-8")).hexdigest()

    @staticmethod
    def _unsettled_claim_failure(
        transaction: ActionTransaction,
        state: ActionState,
    ) -> RuleFailure | None:
        for operation in transaction.operations:
            if not isinstance(operation, ClaimAction):
                continue
            record = state.records.get(operation.action_id)
            if record and record.result and record.result.settlement_id:
                return RuleFailure(
                    "action.reward_requires_atomic_claim",
                    "该行动必须通过奖励联合领取入口结算",
                )
        return None


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("行动持久化逻辑时间必须包含时区")


__all__ = [
    "PersistedActionClaimExecution",
    "PersistedActionExecution",
    "PersistedActionService",
]
