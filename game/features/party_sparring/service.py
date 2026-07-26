"""Lossless party sparring requests, snapshots, combat, and reports."""

from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256

from game.content.catalog.social import (
    PARTY_SPARRING_REQUEST_ID,
    PARTY_SPARRING_REQUEST_LIFETIME_SECONDS,
)
from game.core.gameplay import (
    CharacterState,
    InscriptionPreference,
    CreateSocialRequest,
    InventoryState,
    LoadoutState,
    PartyState,
    PartyStatus,
    ResolveSocialRequest,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    SocialCommand,
    SocialRequest,
    SocialRequestStatus,
    TagSet,
)
from game.rules.battle_report import (
    BattleReportDraft,
    BattleReportSummary,
)
from game.rules.character import CharacterWorldState
from game.rules.companion import CompanionRosterState
from game.rules.party_sparring import PartySparringBattleSimulator

from .models import (
    PartySignature,
    PartySparringRequestMetadata,
    PartySparringRequestResult,
    PartySparringResult,
    PartySparringStorageKinds,
)


PARTY_SPARRING_SOCIAL_SCOPE_ID = "social.party_sparring.global"
PARTY_SPARRING_RULE_VERSION = "rules.party_sparring.v1"


class PartySparringFeature:
    """Coordinate lossless party PvP without touching either party's state."""

    def __init__(
        self,
        database,
        content,
        world_views,
        snapshots,
        social,
        battle_reports,
        simulator: PartySparringBattleSimulator,
        storage: PartySparringStorageKinds,
    ) -> None:
        self.database = database
        self.content = content
        self.world_views = world_views
        self.snapshots = snapshots
        self.social = social
        self.battle_reports = battle_reports
        self.simulator = simulator
        self.storage = storage

    def create_request(
        self,
        operation_id: str,
        challenger_id: str,
        target_id: str,
        *,
        logical_time: datetime,
    ) -> PartySparringRequestResult:
        _aware(logical_time)
        with self.database.unit_of_work() as uow:
            challenger_party = self._party_for_member(uow, challenger_id)
            defender_party = self._party_for_member(uow, target_id)
            failure = self._request_failure(
                challenger_party,
                defender_party,
                challenger_id,
            )
            if failure:
                return PartySparringRequestResult(
                    "unavailable",
                    challenger_party=challenger_party,
                    defender_party=defender_party,
                    failure_message=failure,
                )
            assert challenger_party is not None and defender_party is not None
            social_state = self._social_state(uow)
            existing = self._pending_for_pair(
                social_state,
                challenger_party,
                defender_party,
                logical_time,
            )
            if existing is not None:
                return PartySparringRequestResult(
                    "already_pending",
                    existing,
                    challenger_party,
                    defender_party,
                )
            metadata = PartySparringRequestMetadata(
                PartySignature.from_party(challenger_party),
                PartySignature.from_party(defender_party),
            )
            request = SocialRequest(
                _request_id(operation_id, challenger_party.id, defender_party.id),
                PARTY_SPARRING_REQUEST_ID,
                challenger_party.leader_id,
                defender_party.leader_id,
                logical_time,
                logical_time
                + timedelta(seconds=PARTY_SPARRING_REQUEST_LIFETIME_SECONDS),
                metadata=metadata.to_mapping(),
            )
            command = SocialCommand(
                f"{operation_id}:social",
                challenger_id,
                social_state.revision if social_state is not None else 0,
                CreateSocialRequest(request),
            )
            execution = self._execute_social_in_uow(
                uow,
                social_state,
                command,
                _context(command.id, logical_time, "create"),
            )
            if execution is None:
                return PartySparringRequestResult(
                    "failed",
                    challenger_party=challenger_party,
                    defender_party=defender_party,
                    failure_message="组队切磋请求没有发出",
                )
            uow.commit()
            return PartySparringRequestResult(
                "created",
                execution.state.requests[request.id],
                challenger_party,
                defender_party,
            )

    def reject_request(
        self,
        operation_id: str,
        request_id: str,
        actor_id: str,
        *,
        logical_time: datetime,
    ) -> PartySparringRequestResult:
        _aware(logical_time)
        with self.database.unit_of_work() as uow:
            social_state = self._social_state(uow)
            request = (
                social_state.requests.get(str(request_id or "").strip())
                if social_state is not None
                else None
            )
            failure = self._basic_request_failure(request, actor_id, logical_time)
            if failure:
                return PartySparringRequestResult(
                    failure[0],
                    request,
                    failure_message=failure[1],
                )
            assert request is not None
            parties = self._current_request_parties(uow, request)
            if isinstance(parties, str):
                return PartySparringRequestResult(
                    "party_changed",
                    request,
                    failure_message=parties,
                )
            challenger_party, defender_party = parties
            command = SocialCommand(
                f"{operation_id}:social",
                actor_id,
                social_state.revision,
                ResolveSocialRequest(request.id, SocialRequestStatus.REJECTED),
            )
            execution = self._execute_social_in_uow(
                uow,
                social_state,
                command,
                _context(command.id, logical_time, "reject"),
            )
            if execution is None:
                return PartySparringRequestResult(
                    "failed",
                    request,
                    challenger_party,
                    defender_party,
                    failure_message="组队切磋请求没有处理",
                )
            uow.commit()
            return PartySparringRequestResult(
                "rejected",
                execution.state.requests[request.id],
                challenger_party,
                defender_party,
            )

    def accept_request(
        self,
        operation_id: str,
        request_id: str,
        actor_id: str,
        *,
        logical_time: datetime,
    ) -> PartySparringResult:
        _aware(logical_time)
        report_id = self._report_id(request_id)
        existing_report = self.battle_reports.reference(report_id)
        with self.database.unit_of_work() as uow:
            social_state = self._social_state(uow)
            request = (
                social_state.requests.get(str(request_id or "").strip())
                if social_state is not None
                else None
            )
            if (
                request is not None
                and request.kind_id == PARTY_SPARRING_REQUEST_ID
                and request.status is SocialRequestStatus.ACCEPTED
                and request.recipient_id == actor_id
                and existing_report is not None
            ):
                parties = self._current_request_parties(uow, request)
                challenger_party = parties[0] if not isinstance(parties, str) else None
                defender_party = parties[1] if not isinstance(parties, str) else None
                return PartySparringResult(
                    "replayed",
                    request,
                    existing_report,
                    challenger_party,
                    defender_party,
                )
            failure = self._basic_request_failure(request, actor_id, logical_time)
            if failure:
                return PartySparringResult(
                    failure[0],
                    request,
                    failure_message=failure[1],
                )
            assert request is not None
            parties = self._current_request_parties(uow, request)
            if isinstance(parties, str):
                return PartySparringResult(
                    "party_changed",
                    request,
                    failure_message=parties,
                )
            challenger_party, defender_party = parties
            challenger_members, challenger_bundles = self._party_bundles(
                uow,
                challenger_party,
            )
            defender_members, defender_bundles = self._party_bundles(
                uow,
                defender_party,
            )
            outcome = self.simulator.simulate(
                challenger_members,
                challenger_bundles,
                defender_members,
                defender_bundles,
                battle_id=f"battle:{request.id}",
                context=_context(f"{request.id}:battle", logical_time, "battle"),
            )
            draft = self._battle_report(
                uow,
                request,
                challenger_party,
                defender_party,
                challenger_bundles,
                defender_bundles,
                outcome,
                logical_time,
            )
            command = SocialCommand(
                f"{operation_id}:social",
                actor_id,
                social_state.revision,
                ResolveSocialRequest(request.id, SocialRequestStatus.ACCEPTED),
            )
            execution = self._execute_social_in_uow(
                uow,
                social_state,
                command,
                _context(command.id, logical_time, "accept"),
            )
            if execution is None:
                return PartySparringResult(
                    "failed",
                    request,
                    challenger_party=challenger_party,
                    defender_party=defender_party,
                    failure_message="组队切磋请求已被其他操作处理",
                )
            report = self.battle_reports.capture_in_uow(uow, draft)
            uow.commit()
            winner_party_id = None
            if not outcome.draw:
                winner_party_id = (
                    challenger_party.id
                    if outcome.challenger_victory
                    else defender_party.id
                )
            return PartySparringResult(
                "accepted",
                execution.state.requests[request.id],
                report,
                challenger_party,
                defender_party,
                winner_party_id,
                outcome.draw,
                outcome.turns,
            )

    def _battle_report(
        self,
        uow,
        request,
        challenger_party,
        defender_party,
        challenger_bundles,
        defender_bundles,
        outcome,
        logical_time,
    ):
        combatants = []
        for bundles, lineups, team_id, team_label in (
            (
                challenger_bundles,
                outcome.challenger_lineups,
                "team.challenger",
                "挑战方",
            ),
            (
                defender_bundles,
                outcome.defender_lineups,
                "team.defender",
                "应战方",
            ),
        ):
            for character, inventory, loadout, roster in bundles:
                character_world = self.snapshots.require(
                    uow,
                    self.storage.character_world,
                    character.id,
                    CharacterWorldState,
                )
                inscription_preference = self.snapshots.load(
                    uow,
                    self.storage.inscription_preference,
                    character.id,
                    InscriptionPreference,
                )
                combatants.append(
                    self.battle_reports.builder.character(
                        character,
                        character_world,
                        inventory,
                        loadout,
                        team_id=team_id,
                        team_label=team_label,
                        inscription_preference=inscription_preference,
                    )
                )
                lineup = lineups[character.id]
                if lineup.companion is None:
                    continue
                companion = roster.instances[lineup.companion.companion_id]
                combatants.append(
                    self.battle_reports.builder.companion(
                        companion,
                        team_id=team_id,
                        team_label=team_label,
                    )
                )
        challenger_leader = next(
            value[0] for value in challenger_bundles if value[0].id == challenger_party.leader_id
        )
        defender_leader = next(
            value[0] for value in defender_bundles if value[0].id == defender_party.leader_id
        )
        if outcome.draw:
            result_text = "组队切磋平局"
        else:
            result_text = (
                f"{challenger_leader.name}一方获胜"
                if outcome.challenger_victory
                else f"{defender_leader.name}一方获胜"
            )
        return BattleReportDraft(
            report_id=self._report_id(request.id),
            mode_id="battle.mode.party_sparring",
            content_fingerprint=self.content.catalog.report.content_fingerprint,
            summary=BattleReportSummary(
                f"组队切磋·{challenger_leader.name} vs {defender_leader.name}",
                result_text,
                (
                    f"阵容: {len(challenger_party.members)} vs {len(defender_party.members)}",
                    f"战斗行动: {outcome.turns}",
                ),
                "neutral" if outcome.draw else "victory",
            ),
            segment=self.battle_reports.builder.segment(
                segment_id=request.id,
                title=f"{challenger_leader.name}一方 vs {defender_leader.name}一方",
                trace=outcome.trace,
                combatants=combatants,
                outcome=result_text,
                started_at=logical_time,
                finished_at=logical_time,
            ),
        )

    def _party_bundles(self, uow, party):
        members = tuple(sorted(party.members.values(), key=lambda value: value.slot))
        bundles = []
        for member in members:
            character = self.snapshots.require(
                uow,
                self.storage.character,
                member.subject_id,
                CharacterState,
            )
            inventory = self.snapshots.require(
                uow,
                self.storage.inventory,
                member.subject_id,
                InventoryState,
            )
            loadout = self.snapshots.require(
                uow,
                self.storage.loadout,
                member.subject_id,
                LoadoutState,
            )
            roster = self.snapshots.load(
                uow,
                self.storage.companion_roster,
                member.subject_id,
                CompanionRosterState,
            ) or CompanionRosterState(member.subject_id)
            bundles.append((character, inventory, loadout, roster))
        return members, tuple(bundles)

    def _current_request_parties(self, uow, request):
        try:
            metadata = PartySparringRequestMetadata.from_request(request)
        except ValueError as exc:
            return str(exc)
        challenger = self._active_party(uow, metadata.challenger.party_id)
        defender = self._active_party(uow, metadata.defender.party_id)
        if challenger is None or defender is None:
            return "队伍已经解散，组队切磋请求失效"
        if not metadata.challenger.matches(challenger) or not metadata.defender.matches(defender):
            return "队伍成员、站位或队长已经变化，组队切磋请求失效"
        return challenger, defender

    def _party_for_member(self, uow, character_id: str):
        membership = uow.load_party_membership(character_id)
        if membership is None:
            return None
        party = self._active_party(uow, membership.party_scope_id)
        if party is None or party.id != membership.party_id or character_id not in party.members:
            raise RuntimeError("队伍成员索引与队伍快照不一致")
        return party

    def _active_party(self, uow, party_id: str):
        state = self.snapshots.load(
            uow,
            self.storage.party,
            party_id,
            PartyState,
        )
        return _active_party(state, party_id) if state is not None else None

    def _basic_request_failure(self, request, actor_id, logical_time):
        if request is None or request.kind_id != PARTY_SPARRING_REQUEST_ID:
            return "unknown", "找不到这份组队切磋请求"
        if request.recipient_id != actor_id:
            return "forbidden", "只有受邀队伍的队长可以处理组队切磋"
        if logical_time >= request.expires_at:
            return "expired", "组队切磋请求已经过期"
        if request.status is not SocialRequestStatus.PENDING:
            return "terminal", "组队切磋请求已经处理"
        return None

    @staticmethod
    def _request_failure(challenger_party, defender_party, actor_id):
        if challenger_party is None:
            return "请先创建或加入队伍"
        if challenger_party.leader_id != actor_id:
            return "只有队长可以发起组队切磋"
        if defender_party is None:
            return "对方当前没有队伍"
        if challenger_party.id == defender_party.id:
            return "不能向自己的队伍发起组队切磋"
        return ""

    @staticmethod
    def _pending_for_pair(state, first_party, second_party, logical_time):
        if state is None:
            return None
        current = {
            first_party.id: PartySignature.from_party(first_party),
            second_party.id: PartySignature.from_party(second_party),
        }
        target_pair = frozenset(current)
        for request in state.requests.values():
            if (
                request.kind_id != PARTY_SPARRING_REQUEST_ID
                or request.status is not SocialRequestStatus.PENDING
                or logical_time >= request.expires_at
            ):
                continue
            try:
                metadata = PartySparringRequestMetadata.from_request(request)
            except ValueError:
                continue
            if frozenset(
                (metadata.challenger.party_id, metadata.defender.party_id)
            ) == target_pair and (
                metadata.challenger == current[metadata.challenger.party_id]
                and metadata.defender == current[metadata.defender.party_id]
            ):
                return request
        return None

    def _social_state(self, uow):
        return self.social.load_in_uow(uow, PARTY_SPARRING_SOCIAL_SCOPE_ID)

    def _execute_social_in_uow(self, uow, previous, command, context):
        outcome = self.social.execute_in_uow(
            uow,
            PARTY_SPARRING_SOCIAL_SCOPE_ID,
            command,
            context=context,
            state=previous,
        )
        if outcome.failure or outcome.value is None:
            return None
        return outcome.value.execution

    @staticmethod
    def _report_id(request_id: str) -> str:
        return f"battle-report:party-sparring:{str(request_id or '').strip()}"


def _party_for_member(state: PartyState, character_id: str):
    return next(
        (
            party
            for party in state.parties.values()
            if party.status is PartyStatus.ACTIVE and character_id in party.members
        ),
        None,
    )


def _active_party(state: PartyState, party_id: str):
    party = state.parties.get(party_id)
    return party if party is not None and party.status is PartyStatus.ACTIVE else None


def _request_id(operation_id: str, challenger_party_id: str, defender_party_id: str) -> str:
    value = sha256(
        "\0".join((operation_id, challenger_party_id, defender_party_id)).encode("utf-8")
    ).hexdigest()[:24]
    return f"party-sparring:{value}"


def _context(trace_id: str, logical_time: datetime, phase: str) -> RuleContext:
    return RuleContext(
        trace_id,
        PARTY_SPARRING_RULE_VERSION,
        Ruleset(
            f"ruleset.party_sparring.{phase}",
            TagSet.of("scene.party_sparring"),
        ),
        logical_time,
        SeededRandomSource(trace_id),
    )


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("组队切磋逻辑时间必须包含时区")


__all__ = [
    "PARTY_SPARRING_RULE_VERSION",
    "PARTY_SPARRING_SOCIAL_SCOPE_ID",
    "PartySparringFeature",
]
