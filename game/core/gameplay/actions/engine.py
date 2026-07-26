"""异步行动槽位、生命周期与领域事件引擎。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Mapping, Protocol

from ..context import RuleContext
from ..errors import RuleOutcome, RuleViolation
from ..events import RuleEvent
from ..ids import StableId
from .models import (
    ActionCatalog,
    ActionRecord,
    ActionResult,
    ActionSlotKind,
    ActionSnapshot,
    ActionState,
    ActionStatus,
)


class ActionOperation(Protocol):
    """行动事务可接受的原子操作标记。"""


@dataclass(frozen=True)
class StartAction:
    action_id: str
    definition_id: StableId
    snapshot: ActionSnapshot
    duration_seconds: int | None = None

    def __post_init__(self) -> None:
        if not self.action_id.strip():
            raise ValueError("StartAction.action_id 不能为空")
        if self.duration_seconds is not None and self.duration_seconds < 0:
            raise ValueError("StartAction.duration_seconds 不能小于 0")


@dataclass(frozen=True)
class CompleteAction:
    action_id: str
    result: ActionResult

    def __post_init__(self) -> None:
        if not self.action_id.strip():
            raise ValueError("CompleteAction.action_id 不能为空")


@dataclass(frozen=True)
class ClaimAction:
    action_id: str

    def __post_init__(self) -> None:
        if not self.action_id.strip():
            raise ValueError("ClaimAction.action_id 不能为空")


@dataclass(frozen=True)
class CancelAction:
    action_id: str

    def __post_init__(self) -> None:
        if not self.action_id.strip():
            raise ValueError("CancelAction.action_id 不能为空")


@dataclass(frozen=True)
class InterruptAction:
    action_id: str
    reason_id: StableId

    def __post_init__(self) -> None:
        if not self.action_id.strip() or not str(self.reason_id).strip():
            raise ValueError("InterruptAction 缺少行动或原因 ID")


@dataclass(frozen=True)
class ActionTransaction:
    id: str
    actor_id: str
    expected_revision: int
    operations: tuple[ActionOperation, ...]

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.actor_id.strip():
            raise ValueError("ActionTransaction 缺少 id 或 actor_id")
        if self.expected_revision < 0:
            raise ValueError("ActionTransaction.expected_revision 不能小于 0")
        if not self.operations:
            raise ValueError("ActionTransaction.operations 不能为空")


@dataclass(frozen=True)
class ActionExecution:
    transaction_id: str
    state: ActionState
    transitions: tuple[ActionRecord, ...]
    events: tuple[RuleEvent, ...]


class ActionEngine:
    """统一处理行动占槽、到期、领取、取消和外部中断。"""

    def __init__(self, catalog: ActionCatalog, *, commission_slots: int = 1) -> None:
        if not catalog.finalized:
            catalog.finalize()
        if commission_slots < 0:
            raise ValueError("commission_slots 不能小于 0")
        self.catalog = catalog
        self.commission_slots = commission_slots

    def execute(
        self,
        transaction: ActionTransaction,
        *,
        state: ActionState,
        context: RuleContext,
    ) -> RuleOutcome[ActionExecution]:
        checkpoint = context.random.checkpoint()
        try:
            if state.owner_id != transaction.actor_id:
                self._fail("action.owner_mismatch", "行动状态不属于事务角色")
            if state.revision != transaction.expected_revision:
                self._fail(
                    "action.revision_conflict",
                    "行动状态版本与事务预期不一致",
                    {"expected": transaction.expected_revision, "actual": state.revision},
                )
            records = dict(state.records)
            next_sequence = state.next_sequence
            transitions: list[ActionRecord] = []
            event_specs: list[tuple[str, ActionRecord, Mapping[str, object]]] = []
            for operation in transaction.operations:
                if isinstance(operation, StartAction):
                    record, next_sequence = self._start(
                        operation,
                        records,
                        next_sequence,
                        context,
                    )
                    transitions.append(record)
                    event_specs.append(("action.started", record, {}))
                elif isinstance(operation, CompleteAction):
                    record = self._complete(operation, records, context)
                    transitions.append(record)
                    event_specs.append(
                        (
                            "action.completed",
                            record,
                            {"outcome_id": record.result.outcome_id},
                        )
                    )
                elif isinstance(operation, ClaimAction):
                    record = self._claim(operation, records)
                    transitions.append(record)
                    event_specs.append(("action.claimed", record, {}))
                elif isinstance(operation, CancelAction):
                    record = self._cancel(operation, records)
                    transitions.append(record)
                    event_specs.append(("action.cancelled", record, {}))
                elif isinstance(operation, InterruptAction):
                    record = self._interrupt(operation, records)
                    transitions.append(record)
                    event_specs.append(
                        ("action.interrupted", record, {"reason_id": operation.reason_id})
                    )
                else:
                    raise TypeError(f"未知行动操作：{type(operation).__name__}")
            current = ActionState(
                state.owner_id,
                records,
                next_sequence,
                state.revision + 1,
            )
            events = tuple(
                RuleEvent.from_context(
                    context,
                    kind=kind,
                    source_id=transaction.actor_id,
                    target_id=transaction.actor_id,
                    subject_id=record.definition_id,
                    values={
                        "transaction_id": transaction.id,
                        "action_id": record.id,
                        "sequence": record.sequence,
                        **values,
                    },
                )
                for kind, record, values in event_specs
            )
            return RuleOutcome.success(
                ActionExecution(transaction.id, current, tuple(transitions), events)
            )
        except RuleViolation as exc:
            context.random.restore(checkpoint)
            return RuleOutcome.failed(exc.failure)

    def _start(
        self,
        operation: StartAction,
        records: dict[str, ActionRecord],
        next_sequence: int,
        context: RuleContext,
    ) -> tuple[ActionRecord, int]:
        if operation.action_id in records:
            self._fail("action.id_conflict", "行动 ID 已经存在")
        definition = self.catalog.require(operation.definition_id)
        if operation.snapshot.captured_at != context.logical_time:
            self._fail("action.snapshot_time_mismatch", "行动快照时间必须等于开始时间")
        if definition.slot_kind is ActionSlotKind.MAIN and any(
            record.status is ActionStatus.RUNNING
            and record.slot_kind is ActionSlotKind.MAIN
            for record in records.values()
        ):
            self._fail("action.main_slot_occupied", "当前已有主行动正在进行")
        if definition.slot_kind is ActionSlotKind.COMMISSION:
            occupied = sum(
                record.status is ActionStatus.RUNNING
                and record.slot_kind is ActionSlotKind.COMMISSION
                for record in records.values()
            )
            if occupied >= self.commission_slots:
                self._fail("action.commission_slots_full", "委托行动槽已经占满")
        duration = (
            definition.duration
            if operation.duration_seconds is None
            else timedelta(seconds=operation.duration_seconds)
        )
        record = ActionRecord(
            operation.action_id,
            definition.id,
            next_sequence,
            definition.slot_kind,
            ActionStatus.RUNNING,
            context.logical_time,
            context.logical_time + duration,
            operation.snapshot,
        )
        records[record.id] = record
        return record, next_sequence + 1

    def _complete(
        self,
        operation: CompleteAction,
        records: dict[str, ActionRecord],
        context: RuleContext,
    ) -> ActionRecord:
        record = self._require(records, operation.action_id)
        if record.status is not ActionStatus.RUNNING:
            self._fail("action.not_running", "只有进行中的行动可以完成")
        if context.logical_time < record.completes_at:
            self._fail(
                "action.not_due",
                "行动尚未到达完成时间",
                {"completes_at": record.completes_at.isoformat()},
            )
        if operation.result.resolved_at != context.logical_time:
            self._fail("action.result_time_mismatch", "行动结果时间必须等于结算时间")
        completed = ActionRecord(
            record.id,
            record.definition_id,
            record.sequence,
            record.slot_kind,
            ActionStatus.COMPLETED,
            record.started_at,
            record.completes_at,
            record.snapshot,
            operation.result,
        )
        records[record.id] = completed
        return completed

    def _claim(
        self,
        operation: ClaimAction,
        records: dict[str, ActionRecord],
    ) -> ActionRecord:
        record = self._require(records, operation.action_id)
        if record.status is not ActionStatus.COMPLETED:
            self._fail("action.not_completed", "只有已完成行动可以领取")
        del records[record.id]
        return record

    def _cancel(
        self,
        operation: CancelAction,
        records: dict[str, ActionRecord],
    ) -> ActionRecord:
        record = self._require(records, operation.action_id)
        definition = self.catalog.require(record.definition_id)
        if record.status is not ActionStatus.RUNNING:
            self._fail("action.not_running", "只有进行中的行动可以取消")
        if not definition.cancellable:
            self._fail("action.not_cancellable", "该行动不允许主动取消")
        del records[record.id]
        return record

    def _interrupt(
        self,
        operation: InterruptAction,
        records: dict[str, ActionRecord],
    ) -> ActionRecord:
        record = self._require(records, operation.action_id)
        definition = self.catalog.require(record.definition_id)
        if record.status is not ActionStatus.RUNNING:
            self._fail("action.not_running", "只有进行中的行动可以中断")
        if not definition.interruptible:
            self._fail("action.not_interruptible", "该行动不能被外部中断")
        del records[record.id]
        return record

    @staticmethod
    def _require(records: Mapping[str, ActionRecord], action_id: str) -> ActionRecord:
        try:
            return records[action_id]
        except KeyError:
            ActionEngine._fail("action.unknown", "找不到指定行动", {"action_id": action_id})

    @staticmethod
    def _fail(
        code: StableId,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        raise RuleViolation(code, message, details or {})


__all__ = [
    "ActionEngine",
    "ActionExecution",
    "ActionOperation",
    "ActionTransaction",
    "CancelAction",
    "ClaimAction",
    "CompleteAction",
    "InterruptAction",
    "StartAction",
]
