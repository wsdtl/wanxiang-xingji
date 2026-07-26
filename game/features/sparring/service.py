"""切磋请求、双方快照读取和无损战斗结算。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from game.content.catalog.social import (
    SPARRING_REQUEST_ID,
    SPARRING_REQUEST_LIFETIME_SECONDS,
)
from game.core.gameplay import (
    CharacterState,
    InscriptionPreference,
    CreateSocialRequest,
    InventoryState,
    LoadoutState,
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
    BattleReportReference,
    BattleReportSummary,
)
from game.rules.character import CharacterWorldState
from game.rules.companion import CompanionRosterState
from game.rules.sparring import SparringBattleSimulator


SOCIAL_SCOPE_PREFIX = "social:sparring:"
SPARRING_RULE_VERSION = "rules.sparring.v1"


@dataclass(frozen=True)
class SparringRequestResult:
    status: str
    request: SocialRequest | None = None
    failure_message: str = ""


@dataclass(frozen=True)
class SparringStorageKinds:
    character: str
    character_world: str
    inventory: str
    loadout: str
    companion_roster: str
    inscription_preference: str


@dataclass(frozen=True)
class SparringResult:
    status: str
    request: SocialRequest | None = None
    report: BattleReportReference | None = None
    challenger: CharacterState | None = None
    defender: CharacterState | None = None
    winner_id: str | None = None
    draw: bool = False
    turns: int = 0
    failure_message: str = ""


class SparringFeature:
    """切磋只改变社会请求和战报，不改变任何玩家战斗资源。"""

    def __init__(
        self,
        database,
        content,
        world_views,
        snapshots,
        social,
        battle_reports,
        simulator: SparringBattleSimulator,
        storage: SparringStorageKinds,
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
        request_id: str,
        challenger: CharacterState,
        defender: CharacterState,
        *,
        logical_time: datetime,
    ) -> SparringRequestResult:
        if challenger.id == defender.id:
            return SparringRequestResult("self", failure_message="不能向自己发起切磋")
        scope_id = sparring_social_scope_id(defender.id)
        state = self.social.initialize(scope_id, logical_time=logical_time)
        existing = next(
            (
                request
                for request in state.requests.values()
                if request.kind_id == SPARRING_REQUEST_ID
                and request.sender_id == challenger.id
                and request.recipient_id == defender.id
                and request.status is SocialRequestStatus.PENDING
                and logical_time < request.expires_at
            ),
            None,
        )
        if existing is not None:
            return SparringRequestResult("already_pending", existing)
        request = SocialRequest(
            request_id,
            SPARRING_REQUEST_ID,
            challenger.id,
            defender.id,
            logical_time,
            logical_time + timedelta(seconds=SPARRING_REQUEST_LIFETIME_SECONDS),
            metadata={"mode": "sparring"},
        )
        outcome = self.social.execute(
            scope_id,
            SocialCommand(
                f"{request_id}:create",
                challenger.id,
                state.revision,
                CreateSocialRequest(request),
            ),
            context=_context(f"{request_id}:create", logical_time, "create"),
        )
        if outcome.failure:
            return SparringRequestResult("failed", failure_message=outcome.failure.message)
        return SparringRequestResult("created", request)

    def reject_request(
        self,
        operation_id: str,
        request_id: str,
        defender: CharacterState,
        *,
        logical_time: datetime,
    ) -> SparringRequestResult:
        state = self.social.load(sparring_social_scope_id(defender.id))
        request = state.requests.get(request_id) if state is not None else None
        if request is None or request.kind_id != SPARRING_REQUEST_ID:
            return SparringRequestResult("unknown", failure_message="找不到这份切磋请求")
        if request.recipient_id != defender.id:
            return SparringRequestResult("forbidden", failure_message="只有应战者可以拒绝切磋")
        if logical_time >= request.expires_at:
            return SparringRequestResult("expired", request, "切磋请求已经过期")
        result = self._resolve(
            operation_id,
            request,
            SocialRequestStatus.REJECTED,
            defender,
            logical_time=logical_time,
        )
        if result is None:
            return SparringRequestResult("failed", failure_message="切磋请求处理失败")
        return SparringRequestResult("rejected", result)

    def accept_request(
        self,
        operation_id: str,
        request_id: str,
        defender: CharacterState,
        *,
        logical_time: datetime,
    ) -> SparringResult:
        scope_id = sparring_social_scope_id(defender.id)
        with self.database.unit_of_work() as uow:
            state = self.social.load_in_uow(uow, scope_id)
            request = state.requests.get(request_id) if state is not None else None
            if request is None or request.kind_id != SPARRING_REQUEST_ID:
                return SparringResult("unknown", failure_message="找不到这份切磋请求")
            if request.recipient_id != defender.id:
                return SparringResult("forbidden", request=request, failure_message="只有应战者可以接受切磋")
            if logical_time >= request.expires_at:
                return SparringResult("expired", request=request, failure_message="切磋请求已经过期")
            challenger = self.snapshots.load(
                uow,
                self.storage.character,
                request.sender_id,
                CharacterState,
            )
            if challenger is None:
                return SparringResult("unavailable", request=request, failure_message="挑战者角色已不存在")
            defender = self.snapshots.require(
                uow,
                self.storage.character,
                defender.id,
                CharacterState,
            )
            report_id = self._report_id(request.id)
            existing = self.battle_reports.reference_in_uow(uow, report_id)
            if request.status is SocialRequestStatus.ACCEPTED and existing is not None:
                return SparringResult("replayed", request, existing, challenger, defender)
            if request.status is not SocialRequestStatus.PENDING:
                return SparringResult("terminal", request=request, failure_message="切磋请求已经处理")
            challenger_bundle = self._snapshot_bundle(uow, challenger.id)
            defender_bundle = self._snapshot_bundle(uow, defender.id)
            (
                challenger_inventory,
                challenger_loadout,
                _challenger_dimension,
                challenger_roster,
                _challenger_inscription,
            ) = challenger_bundle
            (
                defender_inventory,
                defender_loadout,
                _defender_dimension,
                defender_roster,
                _defender_inscription,
            ) = defender_bundle
            outcome = self.simulator.simulate(
                challenger,
                challenger_inventory,
                challenger_loadout,
                challenger_roster,
                defender,
                defender_inventory,
                defender_loadout,
                defender_roster,
                battle_id=f"battle:{request.id}",
                context=_context(f"{request.id}:battle", logical_time, "battle"),
            )
            draft = self._battle_report_draft(
                request,
                challenger,
                defender,
                challenger_bundle,
                defender_bundle,
                outcome,
                logical_time,
            )
            command = SocialCommand(
                f"{operation_id}:accept",
                defender.id,
                state.revision,
                ResolveSocialRequest(request.id, SocialRequestStatus.ACCEPTED),
            )
            resolved = self.social.execute_in_uow(
                uow,
                scope_id,
                command,
                context=_context(command.id, logical_time, "resolve"),
                state=state,
            )
            if resolved.failure or resolved.value is None:
                return SparringResult("failed", request=request, failure_message="切磋请求已被其他操作处理")
            accepted = resolved.value.execution.state.requests[request.id]
            report = self.battle_reports.capture_in_uow(uow, draft)
            uow.commit()
            return SparringResult(
                "accepted",
                accepted,
                report,
                challenger,
                defender,
                None if outcome.draw else (
                    challenger.id if outcome.challenger_victory else defender.id
                ),
                outcome.draw,
                outcome.turns,
            )

    def _resolve(self, operation_id, request, status, defender, *, logical_time):
        scope_id = sparring_social_scope_id(defender.id)
        state = self.social.load(scope_id)
        if state is None:
            return None
        outcome = self.social.execute(
            scope_id,
            SocialCommand(
                operation_id,
                defender.id,
                state.revision,
                ResolveSocialRequest(request.id, status),
            ),
            context=_context(operation_id, logical_time, "resolve"),
        )
        if outcome.failure or outcome.value is None:
            return None
        return outcome.value.execution.state.requests[request.id]

    def _snapshot_bundle(self, uow, character_id):
        inventory = self.snapshots.require(
            uow,
            self.storage.inventory,
            character_id,
            InventoryState,
        )
        loadout = self.snapshots.require(
            uow,
            self.storage.loadout,
            character_id,
            LoadoutState,
        )
        dimension = self.snapshots.require(
            uow,
            self.storage.character_world,
            character_id,
            CharacterWorldState,
        )
        roster = self.snapshots.load(
            uow,
            self.storage.companion_roster,
            character_id,
            CompanionRosterState,
        ) or CompanionRosterState(character_id)
        inscription_preference = self.snapshots.load(
            uow,
            self.storage.inscription_preference,
            character_id,
            InscriptionPreference,
        )
        return inventory, loadout, dimension, roster, inscription_preference

    def _battle_report_draft(
        self,
        request,
        challenger,
        defender,
        challenger_bundle,
        defender_bundle,
        outcome,
        logical_time,
    ):
        combatants = []
        for character, bundle, companion_id, team_id, team_label in (
            (
                challenger,
                challenger_bundle,
                outcome.challenger_companion_id,
                "challenger",
                "挑战方",
            ),
            (
                defender,
                defender_bundle,
                outcome.defender_companion_id,
                "defender",
                "应战方",
            ),
        ):
            inventory, loadout, dimension, roster, inscription_preference = bundle
            combatants.append(
                self.battle_reports.builder.character(
                    character,
                    dimension,
                    inventory,
                    loadout,
                    team_id=team_id,
                    team_label=team_label,
                    inscription_preference=inscription_preference,
                )
            )
            if companion_id is None:
                continue
            companion = roster.instances[companion_id]
            combatants.append(
                self.battle_reports.builder.companion(
                    companion,
                    team_id=team_id,
                    team_label=team_label,
                )
            )
        if outcome.draw:
            result_text = "切磋平局"
        else:
            winner = challenger.name if outcome.challenger_victory else defender.name
            result_text = f"{winner} 切磋获胜"
        return BattleReportDraft(
            report_id=self._report_id(request.id),
            mode_id="battle.mode.sparring",
            content_fingerprint=self.content.catalog.report.content_fingerprint,
            summary=BattleReportSummary(
                f"切磋·{challenger.name} vs {defender.name}",
                result_text,
                (
                    f"战斗行动: {outcome.turns}",
                    f"{challenger.name}余血: {outcome.challenger_health_after:.0f}",
                    f"{defender.name}余血: {outcome.defender_health_after:.0f}",
                ),
                "neutral" if outcome.draw else "victory",
            ),
            segment=self.battle_reports.builder.segment(
                segment_id=request.id,
                title=f"{challenger.name} vs {defender.name}",
                trace=outcome.trace,
                combatants=combatants,
                outcome=result_text,
                started_at=logical_time,
                finished_at=logical_time,
            ),
        )

    @staticmethod
    def _report_id(request_id: str) -> str:
        return f"battle-report:sparring:{request_id}"


def _context(trace_id: str, logical_time: datetime, phase: str) -> RuleContext:
    return RuleContext(
        trace_id=trace_id,
        rule_version=SPARRING_RULE_VERSION,
        ruleset=Ruleset(f"ruleset.sparring.{phase}", TagSet.of("scene.sparring")),
        logical_time=logical_time,
        random=SeededRandomSource(trace_id),
    )


def sparring_social_scope_id(recipient_id: str) -> str:
    normalized = str(recipient_id or "").strip()
    if not normalized:
        raise ValueError("切磋社会请求缺少接收角色")
    return f"{SOCIAL_SCOPE_PREFIX}{normalized}"


__all__ = [
    "SparringFeature",
    "SparringRequestResult",
    "SparringResult",
    "SparringStorageKinds",
    "sparring_social_scope_id",
]
