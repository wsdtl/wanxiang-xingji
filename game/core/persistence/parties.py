"""队伍状态及社会邀请接力的 SQLite 原子提交。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256

from ..gameplay.context import RuleContext
from ..gameplay.errors import RuleFailure, RuleOutcome
from ..gameplay.party import (
    AddPartyMember,
    CreateParty,
    PARTY_INVITATION_PARTY_ID_KEY,
    PartyAdmissionCommand,
    PartyAdmissionExecution,
    PartyCommand,
    PartyEngine,
    PartyExecution,
    PartyState,
    PartyStatus,
)
from ..gameplay.social import (
    ResolveSocialRequest,
    SocialCommand,
    SocialEngine,
    SocialRequestStatus,
    SocialState,
)
from .errors import ConcurrencyConflict, TransactionMismatch
from .snapshots import PARTY_AGGREGATE, SOCIAL_AGGREGATE, SnapshotRepository
from .sqlite import SqliteDatabase


@dataclass(frozen=True)
class PersistedPartyExecution:
    execution: PartyExecution
    replayed: bool = False


@dataclass(frozen=True)
class PersistedPartyAdmissionExecution:
    execution: PartyAdmissionExecution
    replayed: bool = False


class PersistedPartyService:
    def __init__(
        self,
        database: SqliteDatabase,
        engine: PartyEngine,
        snapshots: SnapshotRepository | None = None,
    ) -> None:
        self.database = database
        self.engine = engine
        self.snapshots = snapshots or SnapshotRepository()

    def initialize(self, scope_id: str, *, logical_time: datetime) -> PartyState:
        _aware(logical_time)
        initial = PartyState(scope_id)
        with self.database.unit_of_work() as uow:
            current = self.snapshots.load(uow, PARTY_AGGREGATE, scope_id, PartyState)
            if current is None:
                self.snapshots.insert(
                    uow,
                    PARTY_AGGREGATE,
                    scope_id,
                    initial,
                    logical_time,
                )
                current = initial
            uow.commit()
        return current

    def load(self, scope_id: str) -> PartyState | None:
        with self.database.unit_of_work(write=False) as uow:
            return self.snapshots.load(uow, PARTY_AGGREGATE, scope_id, PartyState)

    def find_by_member(self, subject_id: str) -> PartyState | None:
        with self.database.unit_of_work(write=False) as uow:
            membership = uow.load_party_membership(subject_id)
            if membership is None:
                return None
            return self.snapshots.require(
                uow,
                PARTY_AGGREGATE,
                membership.party_scope_id,
                PartyState,
            )

    def execute(
        self,
        scope_id: str,
        command: PartyCommand,
        *,
        context: RuleContext,
    ) -> RuleOutcome[PersistedPartyExecution]:
        checkpoint = context.random.checkpoint()
        try:
            with self.database.unit_of_work() as uow:
                fingerprint = _fingerprint(
                    "party-command.v1",
                    scope_id,
                    self.snapshots.codec.dumps(command),
                )
                previous_tx = uow.load_transaction(command.id)
                if previous_tx is not None:
                    if previous_tx.fingerprint != fingerprint or previous_tx.scope_id != scope_id:
                        raise TransactionMismatch(
                            f"同一队伍事务 ID 对应不同内容：{command.id}"
                        )
                    execution = self.snapshots.codec.loads(
                        previous_tx.receipt_payload,
                        PartyExecution,
                    )
                    return RuleOutcome.success(PersistedPartyExecution(execution, True))
                state = self.snapshots.load(
                    uow,
                    PARTY_AGGREGATE,
                    scope_id,
                    PartyState,
                )
                created = state is None
                if state is None:
                    if not isinstance(command.operation, CreateParty):
                        return RuleOutcome.failed(
                            RuleFailure("party.unknown", "找不到指定队伍")
                        )
                    state = PartyState(scope_id)
                outcome = self.engine.execute(command, state=state, context=context)
                if outcome.failure:
                    return RuleOutcome.failed(outcome.failure)
                assert outcome.value is not None
                expires_at = (
                    context.logical_time + timedelta(hours=6)
                    if outcome.value.party.status is PartyStatus.DISBANDED
                    else None
                )
                if created:
                    self.snapshots.insert(
                        uow,
                        PARTY_AGGREGATE,
                        scope_id,
                        outcome.value.state,
                        context.logical_time,
                        expires_at=expires_at,
                    )
                else:
                    self.snapshots.update(
                        uow,
                        PARTY_AGGREGATE,
                        scope_id,
                        state,
                        outcome.value.state,
                        context.logical_time,
                        expires_at=expires_at,
                    )
                _record_execution(
                    uow,
                    command.id,
                    fingerprint,
                    scope_id,
                    outcome.value,
                    outcome.value.events,
                    self.snapshots,
                    context.logical_time,
                )
                uow.commit()
                return RuleOutcome.success(PersistedPartyExecution(outcome.value))
        except ConcurrencyConflict:
            context.random.restore(checkpoint)
            if isinstance(command.operation, CreateParty):
                return RuleOutcome.failed(
                    RuleFailure(
                        "party.exclusive_membership",
                        "主体已经加入其他活跃队伍",
                    )
                )
            raise
        except Exception:
            context.random.restore(checkpoint)
            raise


class PersistedPartyAdmissionService:
    """在一个数据库事务中接受社会请求并加入队伍。"""

    def __init__(
        self,
        database: SqliteDatabase,
        social: SocialEngine,
        parties: PartyEngine,
        snapshots: SnapshotRepository | None = None,
    ) -> None:
        self.database = database
        self.social = social
        self.parties = parties
        self.snapshots = snapshots or SnapshotRepository()

    def execute(
        self,
        command: PartyAdmissionCommand,
        *,
        context: RuleContext,
    ) -> RuleOutcome[PersistedPartyAdmissionExecution]:
        checkpoint = context.random.checkpoint()
        try:
            with self.database.unit_of_work() as uow:
                fingerprint = _fingerprint(
                    "party-admission.v1",
                    command.party_scope_id,
                    self.snapshots.codec.dumps(command),
                )
                previous_tx = uow.load_transaction(command.id)
                if previous_tx is not None:
                    if (
                        previous_tx.fingerprint != fingerprint
                        or previous_tx.scope_id != command.party_scope_id
                    ):
                        raise TransactionMismatch(
                            f"同一队伍邀请事务 ID 对应不同内容：{command.id}"
                        )
                    execution = self.snapshots.codec.loads(
                        previous_tx.receipt_payload,
                        PartyAdmissionExecution,
                    )
                    return RuleOutcome.success(
                        PersistedPartyAdmissionExecution(execution, True)
                    )

                social_state = self.snapshots.require(
                    uow,
                    SOCIAL_AGGREGATE,
                    command.social_scope_id,
                    SocialState,
                )
                party_state = self.snapshots.require(
                    uow,
                    PARTY_AGGREGATE,
                    command.party_scope_id,
                    PartyState,
                )
                membership = uow.load_party_membership(command.actor_id)
                if membership is not None:
                    context.random.restore(checkpoint)
                    return RuleOutcome.failed(
                        RuleFailure(
                            "party.exclusive_membership",
                            "主体已经加入其他活跃队伍",
                            {"party_id": membership.party_id},
                        )
                    )
                request = social_state.requests.get(command.request_id)
                failure = self._validate_request(command, request)
                if failure is not None:
                    context.random.restore(checkpoint)
                    return RuleOutcome.failed(failure)

                social_outcome = self.social.execute(
                    SocialCommand(
                        f"{command.id}:social",
                        command.actor_id,
                        command.expected_social_revision,
                        ResolveSocialRequest(
                            command.request_id,
                            SocialRequestStatus.ACCEPTED,
                        ),
                    ),
                    state=social_state,
                    context=context,
                )
                if social_outcome.failure:
                    context.random.restore(checkpoint)
                    return RuleOutcome.failed(social_outcome.failure)
                assert social_outcome.value is not None
                assert request is not None
                party_outcome = self.parties.execute(
                    PartyCommand(
                        f"{command.id}:party",
                        request.sender_id,
                        command.expected_party_revision,
                        AddPartyMember(command.party_id, command.actor_id),
                    ),
                    state=party_state,
                    context=context,
                )
                if party_outcome.failure:
                    context.random.restore(checkpoint)
                    return RuleOutcome.failed(party_outcome.failure)
                assert party_outcome.value is not None

                execution = PartyAdmissionExecution(
                    command.id,
                    social_outcome.value,
                    party_outcome.value,
                )
                self.snapshots.update(
                    uow,
                    SOCIAL_AGGREGATE,
                    command.social_scope_id,
                    social_state,
                    social_outcome.value.state,
                    context.logical_time,
                )
                self.snapshots.update(
                    uow,
                    PARTY_AGGREGATE,
                    command.party_scope_id,
                    party_state,
                    party_outcome.value.state,
                    context.logical_time,
                )
                events = (*social_outcome.value.events, *party_outcome.value.events)
                _record_execution(
                    uow,
                    command.id,
                    fingerprint,
                    command.party_scope_id,
                    execution,
                    events,
                    self.snapshots,
                    context.logical_time,
                )
                uow.commit()
                return RuleOutcome.success(PersistedPartyAdmissionExecution(execution))
        except Exception:
            context.random.restore(checkpoint)
            raise

    @staticmethod
    def _validate_request(command, request) -> RuleFailure | None:
        if request is None:
            return RuleFailure("party.invitation_unknown", "找不到队伍邀请")
        if request.kind_id != command.request_kind_id:
            return RuleFailure("party.invitation_kind_mismatch", "社会请求不是指定队伍邀请类型")
        if request.recipient_id != command.actor_id:
            return RuleFailure("party.invitation_recipient_mismatch", "队伍邀请不属于当前主体")
        if request.metadata.get(PARTY_INVITATION_PARTY_ID_KEY) != command.party_id:
            return RuleFailure("party.invitation_party_mismatch", "队伍邀请绑定的队伍不一致")
        return None


def _record_execution(
    uow,
    transaction_id,
    fingerprint,
    scope_id,
    execution,
    events,
    snapshots,
    logical_time,
) -> None:
    timestamp = logical_time.isoformat()
    uow.insert_transaction(
        transaction_id,
        fingerprint,
        scope_id,
        snapshots.codec.dumps(execution),
        timestamp,
    )
    for sequence, event in enumerate(events):
        uow.append_fact(
            transaction_id,
            sequence,
            event.kind,
            snapshots.codec.dumps(event),
            timestamp,
        )


def _fingerprint(kind: str, scope_id: str, payload: str) -> str:
    return sha256("\0".join((kind, scope_id, payload)).encode("utf-8")).hexdigest()


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("队伍持久化逻辑时间必须包含时区")


__all__ = [
    "PersistedPartyAdmissionExecution",
    "PersistedPartyAdmissionService",
    "PersistedPartyExecution",
    "PersistedPartyService",
]
