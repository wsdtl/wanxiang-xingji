"""队伍关系、社会邀请和原子入队业务。"""

from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256

from game.content import (
    PARTY_INVITATION_REQUEST_ID,
    PARTY_INVITATION_REQUEST_LIFETIME_SECONDS,
    PARTY_TYPE_TRIO_ID,
)
from game.core.gameplay import (
    CreateParty,
    CreateSocialRequest,
    DisbandParty,
    LeaveParty,
    PartyAdmissionCommand,
    PartyCommand,
    PartyState,
    PartyStatus,
    RemovePartyMember,
    ResolveSocialRequest,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    SetPartyMemberReady,
    SetPartyMemberSlot,
    SocialCommand,
    SocialRequest,
    SocialRequestStatus,
    TransferPartyLeadership,
    party_invitation_metadata,
)
from .models import PartyOperationResult, PartyView


# 仅供 v6 数据识别；v7 起每支队伍使用自己的 party_id 作为聚合分片。
PARTY_SCOPE_ID = "party.global"
PARTY_SOCIAL_SCOPE_ID = "social.party.global"


class PartyFeature:
    """正式队伍业务的唯一写入口。"""

    def __init__(self, parties, admissions, social, catalog) -> None:
        self.parties = parties
        self.admissions = admissions
        self.social = social
        self.catalog = catalog

    def view(self, character_id: str, *, logical_time: datetime) -> PartyView:
        party_state = self.parties.find_by_member(character_id)
        party = self._member_party(party_state, character_id) if party_state else None
        social_state = self._social_state(logical_time)
        requests = tuple(
            value
            for value in social_state.requests.values()
            if value.recipient_id == character_id
            and value.kind_id == PARTY_INVITATION_REQUEST_ID
            and value.status is SocialRequestStatus.PENDING
            and logical_time < value.expires_at
        )
        return PartyView(party, requests, party_state.revision if party_state else 0)

    def create(
        self,
        operation_id: str,
        character_id: str,
        *,
        logical_time: datetime,
    ) -> PartyOperationResult:
        state = self.parties.find_by_member(character_id)
        if state is not None:
            return PartyOperationResult("already_member", self._member_party(state, character_id))
        party_id = _party_id(operation_id, character_id)
        outcome = self.parties.execute(
            party_id,
            PartyCommand(
                operation_id,
                character_id,
                0,
                CreateParty(party_id, PARTY_TYPE_TRIO_ID),
            ),
            context=_context(operation_id, logical_time, "create"),
        )
        if outcome.failure and outcome.failure.code == "party.exclusive_membership":
            current = self.parties.find_by_member(character_id)
            return PartyOperationResult(
                "already_member",
                self._member_party(current, character_id) if current else None,
            )
        if outcome.failure or outcome.value is None:
            return _failure_result(outcome.failure)
        return PartyOperationResult("created", outcome.value.execution.party)

    def invite(
        self,
        operation_id: str,
        leader_id: str,
        target_id: str,
        *,
        logical_time: datetime,
    ) -> PartyOperationResult:
        state = self.parties.find_by_member(leader_id)
        party = self._member_party(state, leader_id) if state else None
        if party is None:
            return PartyOperationResult("not_member", failure_message="请先创建或加入队伍")
        if party.leader_id != leader_id:
            return PartyOperationResult("not_leader", party, failure_message="只有队长可以邀请成员")
        if target_id in party.members:
            return PartyOperationResult("already_member", party, failure_message="对方已经在当前队伍")
        capacity = self.catalog.require(party.definition_id).capacity
        if len(party.members) >= capacity:
            return PartyOperationResult("full", party, failure_message="队伍人数已经达到上限")
        if self.parties.find_by_member(target_id) is not None:
            return PartyOperationResult("target_busy", party, failure_message="对方已经加入其他队伍")
        social_state = self._social_state(logical_time)
        existing = next(
            (
                value
                for value in social_state.requests.values()
                if value.kind_id == PARTY_INVITATION_REQUEST_ID
                and value.sender_id == leader_id
                and value.recipient_id == target_id
                and value.metadata.get("party_id") == party.id
                and value.status is SocialRequestStatus.PENDING
                and logical_time < value.expires_at
            ),
            None,
        )
        if existing is not None:
            return PartyOperationResult("already_pending", party, existing)
        request = SocialRequest(
            f"party-invite:{operation_id}",
            PARTY_INVITATION_REQUEST_ID,
            leader_id,
            target_id,
            logical_time,
            logical_time + timedelta(seconds=PARTY_INVITATION_REQUEST_LIFETIME_SECONDS),
            metadata=party_invitation_metadata(party.id),
        )
        outcome = self.social.execute(
            PARTY_SOCIAL_SCOPE_ID,
            SocialCommand(
                f"{operation_id}:social",
                leader_id,
                social_state.revision,
                CreateSocialRequest(request),
            ),
            context=_context(operation_id, logical_time, "invite"),
        )
        if outcome.failure or outcome.value is None:
            return _failure_result(outcome.failure, party=party)
        return PartyOperationResult("invited", party, request)

    def accept(
        self,
        operation_id: str,
        member_id: str,
        request_id: str,
        *,
        logical_time: datetime,
    ) -> PartyOperationResult:
        social_state = self._social_state(logical_time)
        request = social_state.requests.get(request_id)
        if request is None:
            return PartyOperationResult("unknown", failure_message="找不到队伍邀请")
        party_id = request.metadata.get("party_id", "")
        if not party_id:
            return PartyOperationResult("invalid", failure_message="队伍邀请缺少目标队伍")
        party_state = self.parties.load(party_id)
        if party_state is None:
            return PartyOperationResult("invalid", failure_message="队伍已经不存在")
        if self.parties.find_by_member(member_id) is not None:
            return PartyOperationResult("target_busy", failure_message="当前已经加入其他队伍")
        outcome = self.admissions.execute(
            PartyAdmissionCommand(
                operation_id,
                member_id,
                PARTY_SOCIAL_SCOPE_ID,
                party_id,
                request_id,
                PARTY_INVITATION_REQUEST_ID,
                party_id,
                social_state.revision,
                party_state.revision,
            ),
            context=_context(operation_id, logical_time, "accept"),
        )
        if outcome.failure or outcome.value is None:
            return _failure_result(outcome.failure)
        return PartyOperationResult(
            "accepted",
            outcome.value.execution.party.party,
            request,
            replayed=outcome.value.replayed,
        )

    def reject(
        self,
        operation_id: str,
        character_id: str,
        request_id: str,
        *,
        logical_time: datetime,
    ) -> PartyOperationResult:
        social_state = self._social_state(logical_time)
        request = social_state.requests.get(request_id)
        if request is None:
            return PartyOperationResult("unknown", failure_message="找不到队伍邀请")
        if request.recipient_id != character_id:
            return PartyOperationResult("forbidden", failure_message="只有邀请对象可以拒绝队伍邀请")
        outcome = self.social.execute(
            PARTY_SOCIAL_SCOPE_ID,
            SocialCommand(
                operation_id,
                character_id,
                social_state.revision,
                ResolveSocialRequest(request_id, SocialRequestStatus.REJECTED),
            ),
            context=_context(operation_id, logical_time, "reject"),
        )
        if outcome.failure:
            return _failure_result(outcome.failure)
        return PartyOperationResult("rejected", request=request)

    def leave(self, operation_id: str, character_id: str, *, logical_time: datetime) -> PartyOperationResult:
        party = self._party_for(character_id, logical_time)
        if party is None:
            return PartyOperationResult("not_member", failure_message="当前没有队伍")
        return self._party_operation(
            operation_id,
            character_id,
            LeaveParty(party.id),
            logical_time,
        )

    def kick(
        self,
        operation_id: str,
        leader_id: str,
        target_id: str,
        *,
        logical_time: datetime,
    ) -> PartyOperationResult:
        party = self._party_for(leader_id, logical_time)
        if party is None:
            return PartyOperationResult("not_member", failure_message="当前没有队伍")
        return self._party_operation(
            operation_id,
            leader_id,
            RemovePartyMember(party.id, target_id),
            logical_time,
        )

    def transfer(
        self,
        operation_id: str,
        leader_id: str,
        target_id: str,
        *,
        logical_time: datetime,
    ) -> PartyOperationResult:
        party = self._party_for(leader_id, logical_time)
        if party is None:
            return PartyOperationResult("not_member", failure_message="当前没有队伍")
        return self._party_operation(
            operation_id,
            leader_id,
            TransferPartyLeadership(party.id, target_id),
            logical_time,
        )

    def disband(
        self,
        operation_id: str,
        leader_id: str,
        *,
        expected_revision: int | None = None,
        logical_time: datetime,
    ) -> PartyOperationResult:
        state = self.parties.find_by_member(leader_id)
        party = self._member_party(state, leader_id) if state else None
        if party is None:
            return PartyOperationResult("not_member", failure_message="当前没有队伍")
        if expected_revision is not None and state.revision != expected_revision:
            return PartyOperationResult(
                "stale",
                party,
                failure_message="队伍状态已经变化，请重新打开队伍",
            )
        return self._party_operation(
            operation_id,
            leader_id,
            DisbandParty(party.id),
            logical_time,
        )

    def set_ready(
        self,
        operation_id: str,
        character_id: str,
        ready: bool,
        *,
        logical_time: datetime,
    ) -> PartyOperationResult:
        party = self._party_for(character_id, logical_time)
        if party is None:
            return PartyOperationResult("not_member", failure_message="当前没有队伍")
        return self._party_operation(
            operation_id,
            character_id,
            SetPartyMemberReady(party.id, ready),
            logical_time,
        )

    def set_slot(
        self,
        operation_id: str,
        leader_id: str,
        target_id: str,
        slot: int,
        *,
        logical_time: datetime,
    ) -> PartyOperationResult:
        party = self._party_for(leader_id, logical_time)
        if party is None:
            return PartyOperationResult("not_member", failure_message="当前没有队伍")
        return self._party_operation(
            operation_id,
            leader_id,
            SetPartyMemberSlot(party.id, target_id, slot),
            logical_time,
        )

    def _party_operation(self, operation_id, actor_id, operation, logical_time):
        state = self.parties.find_by_member(actor_id)
        party = self._member_party(state, actor_id) if state else None
        if party is None:
            return PartyOperationResult("not_member", failure_message="当前没有队伍")
        outcome = self.parties.execute(
            party.id,
            PartyCommand(operation_id, actor_id, state.revision, operation),
            context=_context(operation_id, logical_time, "party"),
        )
        if outcome.failure or outcome.value is None:
            return _failure_result(outcome.failure, party=party)
        return PartyOperationResult(outcome.value.execution.events[0].kind.removeprefix("party."), outcome.value.execution.party)

    def _social_state(self, logical_time):
        value = self.social.load(PARTY_SOCIAL_SCOPE_ID)
        return value or self.social.initialize(PARTY_SOCIAL_SCOPE_ID, logical_time=logical_time)

    def _party_for(self, character_id, logical_time):
        state = self.parties.find_by_member(character_id)
        return self._member_party(state, character_id) if state else None

    @staticmethod
    def _member_party(state: PartyState, character_id: str):
        return next(
            (
                value
                for value in state.parties.values()
                if value.status is PartyStatus.ACTIVE and character_id in value.members
            ),
            None,
        )

def _party_id(operation_id: str, character_id: str) -> str:
    digest = sha256(f"{operation_id}\0{character_id}".encode("utf-8")).hexdigest()[:20]
    return f"party:{digest}"


def _context(operation_id: str, logical_time: datetime, phase: str) -> RuleContext:
    return RuleContext(
        operation_id,
        "rules.party.v1",
        Ruleset(f"ruleset.party.{phase}"),
        logical_time,
        SeededRandomSource(operation_id),
    )


def _failure_result(failure, *, party=None) -> PartyOperationResult:
    return PartyOperationResult(
        "failed",
        party,
        failure_message=failure.message if failure is not None else "队伍操作没有完成",
    )


__all__ = ["PARTY_SCOPE_ID", "PARTY_SOCIAL_SCOPE_ID", "PartyFeature"]
