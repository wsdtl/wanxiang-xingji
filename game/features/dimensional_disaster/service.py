"""次元灾厄开放、挑战、封榜和唯一遗羽的联合持久化。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from hashlib import sha256
from math import ceil, sqrt
import random
from statistics import median
from zoneinfo import ZoneInfo

from game.content import (
    CHARACTER_LEVEL_PROGRESSION_ID,
    DIMENSIONAL_DISASTER_ACTIVITY_ID,
    DIMENSIONAL_DISASTER_BUSINESS_DAY_RESET_HOUR,
    DIMENSIONAL_DISASTER_CYCLE_IDS,
    DIMENSIONAL_DISASTER_DAILY_ATTEMPTS,
    DIMENSIONAL_DISASTER_DRAW_TICKET_CHANCE,
    DIMENSIONAL_DISASTER_MINIMUM_CONTRIBUTION_RATIO,
    DIMENSIONAL_DISASTER_RECENT_EXCLUSION,
    INSCRIPTION_FEATHER_ITEM_ID,
    DRAW_TICKET_ITEM_ID,
)
from game.core.gameplay import (
    ENEMY_RANK_BOSS_ID,
    HEALTH_CURRENT,
    SPIRIT_CURRENT,
    ActivityCommand,
    ActivityInstance,
    ActivityState,
    ActivityStatus,
    CharacterExperienceReward,
    CharacterState,
    CloseActivity,
    CreateActivity,
    FinalizeActivity,
    InscriptionMediumData,
    InscriptionPreference,
    InstanceItemReward,
    InventoryState,
    JoinActivity,
    LoadoutState,
    OpenActivity,
    RecordActivityContribution,
    RewardClaimState,
    RewardExpectations,
    RewardSettlement,
    StackItemReward,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    ActionSlotKind,
    ActionState,
    INSCRIPTION_MEDIUM_DATA_KEY,
)
from game.features.errors import StalePreparationError
from game.rules.activity import GLOBAL_ACTIVITY_SCOPE_ID
from game.rules.character import CharacterWorldState, PRIMARY_LEDGER_ID
from game.rules.companion import CompanionRosterState
from game.rules.disaster import (
    DIMENSIONAL_DISASTER_AGGREGATE,
    DIMENSIONAL_DISASTER_RULESET_VERSION,
    DimensionalDisasterOutcome,
    DimensionalDisasterState,
    DimensionalDisasterStatus,
    DisasterChallengeReceipt,
    DisasterCombatSnapshot,
    DisasterNarrativeSnapshot,
    begin_disaster_settlement,
    close_disaster,
    mark_disaster_rewarded,
    record_disaster_challenge,
    roll_draw_ticket_drop,
)
from game.rules.exploration import ExplorationState, ExplorationStatus
from game.rules.encounter import EnemyEncounterGenerator
from game.rules.battle_report import (
    BattleReportDraft,
    BattleReportSummary,
)

from .battle import DimensionalDisasterBattleSimulator
from .models import (
    DimensionalDisasterChallengeResult,
    DimensionalDisasterMaintenanceResult,
    DimensionalDisasterStorageKinds,
    DimensionalDisasterView,
)


SOURCE_KIND = "source.dimensional_disaster"
SYSTEM_ACTOR_ID = "system.dimensional_disaster"


@dataclass(frozen=True)
class _DisasterPlayerInputs:
    action: ActionState | None
    exploration: ExplorationState | None
    character: CharacterState
    character_world: CharacterWorldState
    inventory: InventoryState
    loadout: LoadoutState
    roster: CompanionRosterState
    inscription_preference: InscriptionPreference | None


@dataclass(frozen=True)
class _PreparedDisasterChallenge:
    event: DimensionalDisasterState
    inputs: _DisasterPlayerInputs
    battle: object
    context: RuleContext
    draw_ticket_drops: int
    report: object


_STALE_DISASTER_CHALLENGE = object()


class DimensionalDisasterFeature:
    """具体玩法协调器；不向公共核心增加灾厄专用字段。"""

    def __init__(
        self,
        database,
        content,
        world_views,
        disasters,
        playable_world_ids,
        snapshots,
        rewards,
        player_lineup,
        battle_reports,
        storage: DimensionalDisasterStorageKinds,
        reward_keys_factory,
        companion_growth,
        *,
        maximum_battle_rounds: int,
        timezone: str,
    ) -> None:
        self.database = database
        self.content = content
        self.world_views = world_views
        self.disasters = disasters
        self.playable_world_ids = tuple(playable_world_ids)
        self.snapshots = snapshots
        self.rewards = rewards
        self.battle_reports = battle_reports
        self.companion_growth = companion_growth
        self.storage = storage
        self.reward_keys_factory = reward_keys_factory
        self.timezone = ZoneInfo(timezone)
        self.battles = DimensionalDisasterBattleSimulator(
            content.catalog,
            player_lineup,
            maximum_rounds=maximum_battle_rounds,
        )
        self.enemy_loadouts = EnemyEncounterGenerator(
            content.catalog.enemies,
            content_version=content.catalog.report.content_fingerprint,
        )

    def maintain(self, *, logical_time: datetime) -> DimensionalDisasterMaintenanceResult:
        _aware(logical_time)
        settled = self._settle_due(logical_time)
        opened = 1 if self._open_current_window(logical_time) else 0
        return DimensionalDisasterMaintenanceResult(opened, settled)

    def view(self, *, logical_time: datetime) -> DimensionalDisasterView:
        self.maintain(logical_time=logical_time)
        current = self._current_state(logical_time)
        if current is not None:
            return self._view_for(current, active=True)
        latest = self._latest_state()
        if latest is None:
            return DimensionalDisasterView("empty")
        return self._view_for(latest, active=False)

    def attempts_today(
        self,
        event: DimensionalDisasterState,
        character_id: str,
        *,
        logical_time: datetime,
    ) -> int:
        return event.attempts_today(
            character_id,
            self._business_day(logical_time),
        )

    def challenge(
        self,
        character_id: str,
        operation_id: str,
        *,
        logical_time: datetime,
    ) -> DimensionalDisasterChallengeResult:
        _aware(logical_time)
        self.maintain(logical_time=logical_time)
        current = self._current_state(logical_time)
        if current is None:
            return DimensionalDisasterChallengeResult("no_active")
        normalized_character_id = str(character_id or "").strip()
        normalized_operation_id = str(operation_id or "").strip()
        if not normalized_character_id or not normalized_operation_id:
            raise ValueError("灾厄挑战缺少角色或操作身份")
        for _ in range(2):
            prepared = self._prepare_challenge(
                current.event_id,
                normalized_character_id,
                normalized_operation_id,
                logical_time,
            )
            if isinstance(prepared, DimensionalDisasterChallengeResult):
                return prepared
            result = self._commit_challenge(
                normalized_character_id,
                normalized_operation_id,
                logical_time,
                prepared,
            )
            if result is not _STALE_DISASTER_CHALLENGE:
                return result
        raise StalePreparationError("灾厄挑战准备结果连续过期，请重试")

    def _prepare_challenge(
        self,
        event_id: str,
        character_id: str,
        operation_id: str,
        logical_time: datetime,
    ) -> _PreparedDisasterChallenge | DimensionalDisasterChallengeResult:
        with self.database.unit_of_work(write=False) as uow:
            event = self.snapshots.require(
                uow,
                DIMENSIONAL_DISASTER_AGGREGATE,
                event_id,
                DimensionalDisasterState,
            )
            replay = event.challenge_receipts.get(operation_id)
            activity_state = self.snapshots.require(
                uow,
                self.storage.activity,
                GLOBAL_ACTIVITY_SCOPE_ID,
                ActivityState,
            )
            activity = activity_state.instances[event.event_id]
            if replay is not None:
                return DimensionalDisasterChallengeResult(
                    "replayed",
                    event,
                    activity,
                    replay.as_replay(),
                    self.battle_reports.reference_in_uow(
                        uow,
                        self._battle_report_id(operation_id)
                    ),
                )
            if (
                event.status is not DimensionalDisasterStatus.OPEN
                or event.outcome is not DimensionalDisasterOutcome.NONE
                or activity.status is not ActivityStatus.OPEN
                or not event.opens_at <= logical_time < event.closes_at
            ):
                return DimensionalDisasterChallengeResult("ended", event, activity)
            business_day = self._business_day(logical_time)
            attempts = event.attempts_today(character_id, business_day)
            if attempts >= DIMENSIONAL_DISASTER_DAILY_ATTEMPTS:
                return DimensionalDisasterChallengeResult(
                    "attempt_limit",
                    event,
                    activity,
                )
            inputs = self._load_player_inputs(uow, character_id)
            if inputs.action is not None and inputs.action.running(ActionSlotKind.MAIN):
                return DimensionalDisasterChallengeResult("main_action_occupied", event, activity)
            if (
                inputs.exploration is not None
                and inputs.exploration.status is ExplorationStatus.RUNNING
            ):
                return DimensionalDisasterChallengeResult("exploring", event, activity)
            if inputs.character.resources[HEALTH_CURRENT] <= 0:
                return DimensionalDisasterChallengeResult("health_depleted", event, activity)
        context = _context(operation_id, logical_time)
        battle = self.battles.simulate(
            event.combat,
            event.event_id,
            character=inputs.character,
            inventory=inputs.inventory,
            loadout=inputs.loadout,
            roster=inputs.roster,
            context=context,
        )
        damage = min(event.current_health, max(0, battle.damage))
        ticket_stack = self._ticket_stack(inputs.inventory)
        ticket_definition = self.content.catalog.items.require(DRAW_TICKET_ITEM_ID)
        ticket_capacity = (
            ticket_definition.stack_limit - (ticket_stack.quantity if ticket_stack else 0)
            if ticket_definition.stack_limit is not None
            else 1
        )
        draw_ticket_drops = roll_draw_ticket_drop(
            context.random,
            chance=DIMENSIONAL_DISASTER_DRAW_TICKET_CHANCE,
            effective_damage=damage,
            available_capacity=ticket_capacity,
        )
        companion_amount = self.companion_growth.engine.disaster_experience(
            event.combat.level,
            damage,
            event.maximum_health,
        )
        provisional_receipt = DisasterChallengeReceipt(
            operation_id,
            character_id,
            event.event_id,
            business_day,
            damage,
            event.current_health,
            event.current_health - damage,
            battle.player_health_after,
            battle.player_spirit_after,
            attempts + 1,
            battle.turns,
            battle.player_victory,
            logical_time,
            draw_ticket_drops,
            battle.player_companion_id,
            companion_amount,
        )
        report = self.battle_reports.prepare_capture(
            self._battle_report_draft(
                event,
                inputs.character,
                inputs.character_world,
                inputs.inventory,
                inputs.loadout,
                inputs.inscription_preference,
                inputs.roster,
                battle,
                provisional_receipt,
                operation_id,
                logical_time,
            )
        )
        return _PreparedDisasterChallenge(
            event,
            inputs,
            battle,
            context,
            draw_ticket_drops,
            report,
        )

    def _commit_challenge(
        self,
        character_id: str,
        operation_id: str,
        logical_time: datetime,
        prepared: _PreparedDisasterChallenge,
    ):
        battle = prepared.battle
        context = prepared.context
        with self.database.unit_of_work() as uow:
            event = self.snapshots.require(
                uow,
                DIMENSIONAL_DISASTER_AGGREGATE,
                prepared.event.event_id,
                DimensionalDisasterState,
            )
            activity_state = self.snapshots.require(
                uow,
                self.storage.activity,
                GLOBAL_ACTIVITY_SCOPE_ID,
                ActivityState,
            )
            activity = activity_state.instances[event.event_id]
            replay = event.challenge_receipts.get(operation_id)
            if replay is not None:
                return DimensionalDisasterChallengeResult(
                    "replayed",
                    event,
                    activity,
                    replay.as_replay(),
                    self.battle_reports.reference_in_uow(
                        uow,
                        self._battle_report_id(operation_id),
                    ),
                )
            if (
                event.status is not DimensionalDisasterStatus.OPEN
                or event.outcome is not DimensionalDisasterOutcome.NONE
                or activity.status is not ActivityStatus.OPEN
                or not event.opens_at <= logical_time < event.closes_at
            ):
                return DimensionalDisasterChallengeResult("ended", event, activity)
            business_day = self._business_day(logical_time)
            attempts = event.attempts_today(character_id, business_day)
            if attempts >= DIMENSIONAL_DISASTER_DAILY_ATTEMPTS:
                return DimensionalDisasterChallengeResult(
                    "attempt_limit",
                    event,
                    activity,
                )
            inputs = self._load_player_inputs(uow, character_id)
            if inputs != prepared.inputs:
                return _STALE_DISASTER_CHALLENGE
            damage = min(event.current_health, max(0, battle.damage))
            companion_amount = self.companion_growth.engine.disaster_experience(
                event.combat.level,
                damage,
                event.maximum_health,
            )
            companion_growth = self.companion_growth.grant_in_uow(
                uow,
                character_id,
                battle.player_companion_id,
                companion_amount,
                character_level=inputs.character.progressions[
                    CHARACTER_LEVEL_PROGRESSION_ID
                ].level,
                logical_time=logical_time,
            )
            companion_experience = (
                companion_growth.accepted if companion_growth is not None else 0
            )
            receipt = DisasterChallengeReceipt(
                operation_id,
                character_id,
                event.event_id,
                business_day,
                damage,
                event.current_health,
                event.current_health - damage,
                battle.player_health_after,
                battle.player_spirit_after,
                attempts + 1,
                battle.turns,
                battle.player_victory,
                logical_time,
                prepared.draw_ticket_drops,
                battle.player_companion_id,
                companion_experience,
            )
            next_event = record_disaster_challenge(event, receipt)
            next_activity_state = activity_state
            if character_id not in activity.participants:
                next_activity_state, activity = self._persist_activity_operation(
                    uow,
                    next_activity_state,
                    JoinActivity(event.event_id, character_id),
                    f"{operation_id}:join",
                    character_id,
                    logical_time,
                )
            next_activity_state, activity = self._persist_activity_operation(
                uow,
                next_activity_state,
                RecordActivityContribution(
                    event.event_id,
                    character_id,
                    damage,
                ),
                f"{operation_id}:contribution",
                character_id,
                logical_time,
            )
            self.snapshots.update(
                uow,
                DIMENSIONAL_DISASTER_AGGREGATE,
                event.event_id,
                event,
                next_event,
                logical_time,
            )
            resources = dict(inputs.character.resources)
            resources[HEALTH_CURRENT] = battle.player_health_after
            resources[SPIRIT_CURRENT] = battle.player_spirit_after
            if resources != dict(inputs.character.resources):
                next_character = replace(
                    inputs.character,
                    resources=resources,
                    revision=inputs.character.revision + 1,
                )
                self.snapshots.update(
                    uow,
                    self.storage.character,
                    character_id,
                    inputs.character,
                    next_character,
                    logical_time,
                )
            if prepared.draw_ticket_drops:
                inventory = inputs.inventory
                ticket_stack = self._ticket_stack(inventory)
                container_id = next(
                    value.id
                    for value in inventory.containers.values()
                    if value.kind == "container.special"
                )
                claim = self.snapshots.require(
                    uow,
                    self.storage.reward_claim,
                    character_id,
                    RewardClaimState,
                )
                settlement = RewardSettlement(
                    f"reward:{operation_id}:draw-ticket",
                    character_id,
                    character_id,
                    SOURCE_KIND,
                    f"{event.event_id}:{operation_id}:draw-ticket",
                    (
                        StackItemReward(
                            ticket_stack.id if ticket_stack else f"stack:{character_id}:{DRAW_TICKET_ITEM_ID}",
                            DRAW_TICKET_ITEM_ID,
                            container_id,
                            1,
                            {"disaster_event_id": event.event_id},
                        ),
                    ),
                    RewardExpectations(
                        claim.revision,
                        inventory_revision=inventory.revision,
                    ),
                )
                reward_outcome = self.rewards.settle_in_uow(
                    uow,
                    settlement,
                    self.reward_keys_factory(character_id, PRIMARY_LEDGER_ID),
                    context=context,
                )
                if reward_outcome.failure:
                    raise RuntimeError(reward_outcome.failure.message)
            report = self.battle_reports.capture_prepared_in_uow(
                uow,
                prepared.report.with_summary(
                    self._battle_report_summary(event, battle, receipt)
                ),
            )
            uow.commit()
            return DimensionalDisasterChallengeResult(
                "defeated" if next_event.outcome is DimensionalDisasterOutcome.DEFEATED else "resolved",
                next_event,
                activity,
                receipt,
                report,
            )

    def _load_player_inputs(
        self,
        uow,
        character_id: str,
    ) -> _DisasterPlayerInputs:
        return _DisasterPlayerInputs(
            self.snapshots.load(
                uow,
                self.storage.action,
                character_id,
                ActionState,
            ),
            self.snapshots.load(
                uow,
                self.storage.exploration,
                character_id,
                ExplorationState,
            ),
            self.snapshots.require(
                uow,
                self.storage.character,
                character_id,
                CharacterState,
            ),
            self.snapshots.require(
                uow,
                self.storage.character_world,
                character_id,
                CharacterWorldState,
            ),
            self.snapshots.require(
                uow,
                self.storage.inventory,
                character_id,
                InventoryState,
            ),
            self.snapshots.require(
                uow,
                self.storage.loadout,
                character_id,
                LoadoutState,
            ),
            self.snapshots.load(
                uow,
                self.storage.companion_roster,
                character_id,
                CompanionRosterState,
            ) or CompanionRosterState(character_id),
            self.snapshots.load(
                uow,
                self.storage.inscription_preference,
                character_id,
                InscriptionPreference,
            ),
        )

    @staticmethod
    def _ticket_stack(inventory: InventoryState):
        return next(
            (
                value
                for value in inventory.stacks.values()
                if value.definition_id == DRAW_TICKET_ITEM_ID
            ),
            None,
        )

    def _battle_report_draft(
        self,
        event,
        character,
        character_world,
        inventory,
        loadout,
        inscription_preference,
        roster,
        battle,
        receipt,
        operation_id: str,
        logical_time: datetime,
    ) -> BattleReportDraft:
        outcome = "讨伐胜利" if battle.player_victory else "战斗结束"
        enemy_id = f"enemy:{event.event_id}"
        combatants = [
            self.battle_reports.builder.character(
                character,
                character_world,
                inventory,
                loadout,
                team_id="player",
                team_label="归航行者",
                inscription_preference=inscription_preference,
            )
        ]
        if battle.player_companion_id is not None:
            companion = roster.instances[battle.player_companion_id]
            combatants.append(
                self.battle_reports.builder.companion(
                    companion,
                    team_id="player",
                    team_label="归航行者",
                )
            )
        combatants.append(
            self.battle_reports.builder.world_actor(
                enemy_id,
                event.narrative.name,
                event.source_world_id,
                team_id="enemy",
                team_label="次元灾厄",
                unit_kind="dimensional_disaster",
            )
        )
        return BattleReportDraft(
            report_id=self._battle_report_id(operation_id),
            mode_id="battle.mode.dimensional_disaster",
            content_fingerprint=self.content.catalog.report.content_fingerprint,
            summary=self._battle_report_summary(event, battle, receipt),
            segment=self.battle_reports.builder.segment(
                segment_id=operation_id,
                title=event.narrative.name,
                trace=battle.trace,
                combatants=combatants,
                outcome=outcome,
                started_at=logical_time,
                finished_at=logical_time,
            ),
        )

    @staticmethod
    def _battle_report_summary(
        event,
        battle,
        receipt,
    ) -> BattleReportSummary:
        return BattleReportSummary(
            f"讨伐灾厄·{event.narrative.name}",
            "讨伐胜利" if battle.player_victory else "战斗结束",
            (
                f"造成伤痕: {receipt.damage}",
                f"灾厄血量: {receipt.shared_health_after}/{event.maximum_health}",
                f"战斗行动: {receipt.turns}",
            ),
            "victory" if battle.player_victory else "neutral",
        )

    @staticmethod
    def _battle_report_id(operation_id: str) -> str:
        return f"battle-report:dimensional-disaster:{operation_id}"

    def _open_current_window(self, logical_time: datetime) -> bool:
        windows = self._current_windows(logical_time)
        if not windows:
            return False
        if len(windows) > 1:
            raise RuntimeError("次元灾厄周期窗口发生重叠")
        window = windows[0]
        event_id = self._event_id(window.instance_id)
        with self.database.unit_of_work() as uow:
            existing = self.snapshots.load(
                uow,
                DIMENSIONAL_DISASTER_AGGREGATE,
                event_id,
                DimensionalDisasterState,
            )
            if existing is not None:
                return False
            previous_events = self.snapshots.list(
                uow,
                DIMENSIONAL_DISASTER_AGGREGATE,
                DimensionalDisasterState,
                limit=1_000,
            )
            recent = tuple(
                value.definition_id
                for value in sorted(
                    previous_events,
                    key=lambda item: item.opens_at,
                    reverse=True,
                )[:DIMENSIONAL_DISASTER_RECENT_EXCLUSION]
            )
            definition = self.disasters.select(
                window.instance_id,
                source_world_ids=self.playable_world_ids,
                recent_definition_ids=recent,
            )
            characters = self.snapshots.list(
                uow,
                self.storage.character,
                CharacterState,
                limit=100_000,
            )
            levels = [
                value.progressions[CHARACTER_LEVEL_PROGRESSION_ID].level
                for value in characters
            ]
            level = max(1, round(median(levels))) if levels else 1
            generation_seed = f"{window.instance_id}:{definition.id}"
            behavior_ids, phase_loadouts = self.enemy_loadouts.generate_loadout(
                definition.enemy_definition_id,
                behavior_count=3,
                phase_health_ratios=(0.65, 0.30),
                behavior_weights=(
                    self.content.enemy_behavior_profiles.require(
                        definition.source_world_id
                    ).behavior_weights
                ),
                random=SeededRandomSource(generation_seed),
            )
            combat = DisasterCombatSnapshot(
                definition.enemy_definition_id,
                level,
                ENEMY_RANK_BOSS_ID,
                behavior_ids,
                generation_seed,
                self.content.catalog.report.content_fingerprint,
                phase_loadouts,
            )
            local_health = self.battles.enemy_maximum_health(combat, event_id)
            population_scale = max(
                4,
                min(30, ceil(sqrt(max(1, len(characters))) * 4)),
            )
            maximum_health = max(1, round(local_health * population_scale))
            event = DimensionalDisasterState(
                event_id,
                window.instance_id,
                definition.id,
                definition.source_world_id,
                DisasterNarrativeSnapshot(
                    definition.name,
                    definition.title,
                    definition.scene,
                    definition.story,
                    definition.farewell,
                    definition.feather_text,
                    definition.source_note,
                ),
                combat,
                window.starts_at,
                window.ends_at,
                maximum_health,
                maximum_health,
            )
            stored_activity = self.snapshots.load(
                uow,
                self.storage.activity,
                GLOBAL_ACTIVITY_SCOPE_ID,
                ActivityState,
            )
            activity_state = stored_activity or ActivityState(GLOBAL_ACTIVITY_SCOPE_ID)
            if stored_activity is None:
                self.snapshots.insert(
                    uow,
                    self.storage.activity,
                    GLOBAL_ACTIVITY_SCOPE_ID,
                    activity_state,
                    logical_time,
                )
            activity_instance = ActivityInstance(
                event.event_id,
                DIMENSIONAL_DISASTER_ACTIVITY_ID,
                1,
                event.opens_at,
                event.closes_at,
            )
            activity_state, _ = self._persist_activity_operation(
                uow,
                activity_state,
                CreateActivity(activity_instance),
                f"{event.event_id}:create",
                SYSTEM_ACTOR_ID,
                event.opens_at,
            )
            activity_state, _ = self._persist_activity_operation(
                uow,
                activity_state,
                OpenActivity(event.event_id),
                f"{event.event_id}:open",
                SYSTEM_ACTOR_ID,
                logical_time,
            )
            self.snapshots.insert(
                uow,
                DIMENSIONAL_DISASTER_AGGREGATE,
                event.event_id,
                event,
                logical_time,
            )
            uow.commit()
            return True

    def _settle_due(self, logical_time: datetime) -> int:
        with self.database.unit_of_work(write=False) as uow:
            events = self.snapshots.list(
                uow,
                DIMENSIONAL_DISASTER_AGGREGATE,
                DimensionalDisasterState,
                limit=1_000,
            )
        settled = 0
        for event in events:
            if event.status is DimensionalDisasterStatus.CLOSED or event.closes_at > logical_time:
                continue
            self._prepare_settlement(event.event_id, logical_time)
            self._settle_participant_rewards(event.event_id, logical_time)
            if self._finish_settlement(event.event_id, logical_time):
                settled += 1
        return settled

    def _prepare_settlement(self, event_id: str, logical_time: datetime) -> None:
        with self.database.unit_of_work() as uow:
            event = self.snapshots.require(
                uow,
                DIMENSIONAL_DISASTER_AGGREGATE,
                event_id,
                DimensionalDisasterState,
            )
            if event.status is not DimensionalDisasterStatus.OPEN:
                return
            activity_state = self.snapshots.require(
                uow,
                self.storage.activity,
                GLOBAL_ACTIVITY_SCOPE_ID,
                ActivityState,
            )
            activity_state, activity = self._activity_operation(
                activity_state,
                CloseActivity(event_id),
                f"{event_id}:close",
                SYSTEM_ACTOR_ID,
                logical_time,
            )
            winner = (
                self._select_feather_owner(event, activity)
                if event.outcome is DimensionalDisasterOutcome.DEFEATED
                else None
            )
            next_event = begin_disaster_settlement(
                event,
                logical_time=logical_time,
                feather_owner_id=winner,
            )
            self.snapshots.update(
                uow,
                DIMENSIONAL_DISASTER_AGGREGATE,
                event_id,
                event,
                next_event,
                logical_time,
            )
            previous_activity = self.snapshots.require(
                uow,
                self.storage.activity,
                GLOBAL_ACTIVITY_SCOPE_ID,
                ActivityState,
            )
            self.snapshots.update(
                uow,
                self.storage.activity,
                GLOBAL_ACTIVITY_SCOPE_ID,
                previous_activity,
                activity_state,
                logical_time,
            )
            uow.commit()

    def _settle_participant_rewards(self, event_id: str, logical_time: datetime) -> None:
        with self.database.unit_of_work(write=False) as uow:
            activity_state = self.snapshots.require(
                uow,
                self.storage.activity,
                GLOBAL_ACTIVITY_SCOPE_ID,
                ActivityState,
            )
            participant_ids = tuple(
                value.subject_id for value in activity_state.instances[event_id].ranking
            )
        for character_id in participant_ids:
            self._settle_one_reward(event_id, character_id, logical_time)

    def _settle_one_reward(
        self,
        event_id: str,
        character_id: str,
        logical_time: datetime,
    ) -> None:
        with self.database.unit_of_work() as uow:
            event = self.snapshots.require(
                uow,
                DIMENSIONAL_DISASTER_AGGREGATE,
                event_id,
                DimensionalDisasterState,
            )
            if character_id in event.rewarded_character_ids:
                return
            activity_state = self.snapshots.require(
                uow,
                self.storage.activity,
                GLOBAL_ACTIVITY_SCOPE_ID,
                ActivityState,
            )
            activity = activity_state.instances[event_id]
            entry = next(value for value in activity.ranking if value.subject_id == character_id)
            character = self.snapshots.require(
                uow,
                self.storage.character,
                character_id,
                CharacterState,
            )
            inventory = self.snapshots.require(
                uow,
                self.storage.inventory,
                character_id,
                InventoryState,
            )
            claim = self.snapshots.require(
                uow,
                self.storage.reward_claim,
                character_id,
                RewardClaimState,
            )
            ratio = entry.contribution / event.maximum_health
            victory_factor = 1.0 if event.outcome is DimensionalDisasterOutcome.DEFEATED else 0.5
            rank_bonus = 40 if entry.rank == 1 else 25 if entry.rank == 2 else 15 if entry.rank == 3 else 0
            experience = max(
                1,
                round((40 + 180 * sqrt(max(0.0, min(1.0, ratio))) + rank_bonus) * victory_factor),
            )
            reward_specs = [
                CharacterExperienceReward(
                    character_id,
                    CHARACTER_LEVEL_PROGRESSION_ID,
                    experience,
                )
            ]
            grants_feather = event.feather_owner_id == character_id
            if grants_feather:
                container_id = next(
                    value.id
                    for value in inventory.containers.values()
                    if value.kind == "container.inscription"
                )
                reward_specs.append(
                    InstanceItemReward(
                        event.feather_asset_id,
                        INSCRIPTION_FEATHER_ITEM_ID,
                        container_id,
                        {
                            INSCRIPTION_MEDIUM_DATA_KEY: InscriptionMediumData(
                                f"{event.narrative.name}遗羽",
                                self._feather_history(event, activity, entry),
                            )
                        },
                        {
                            "disaster_event_id": event.event_id,
                            "disaster_definition_id": event.definition_id,
                            "rank": entry.rank,
                            "contribution": entry.contribution,
                        },
                    )
                )
            settlement = RewardSettlement(
                f"reward:{event_id}:{character_id}",
                SYSTEM_ACTOR_ID,
                character_id,
                SOURCE_KIND,
                f"{event_id}:{character_id}",
                tuple(reward_specs),
                RewardExpectations(
                    claim.revision,
                    inventory.revision if grants_feather else None,
                    character_revisions={character_id: character.revision},
                ),
                {
                    "event_id": event_id,
                    "rank": entry.rank,
                    "contribution": entry.contribution,
                    "outcome": event.outcome.value,
                },
            )
            context = _context(settlement.id, logical_time)
            outcome = self.rewards.settle_in_uow(
                uow,
                settlement,
                self.reward_keys_factory(
                    character_id,
                    PRIMARY_LEDGER_ID,
                    (character_id,),
                ),
                context=context,
            )
            if outcome.failure:
                raise RuntimeError(outcome.failure.message)
            next_event = mark_disaster_rewarded(event, character_id)
            self.snapshots.update(
                uow,
                DIMENSIONAL_DISASTER_AGGREGATE,
                event_id,
                event,
                next_event,
                logical_time,
            )
            uow.commit()

    def _finish_settlement(self, event_id: str, logical_time: datetime) -> bool:
        with self.database.unit_of_work() as uow:
            event = self.snapshots.require(
                uow,
                DIMENSIONAL_DISASTER_AGGREGATE,
                event_id,
                DimensionalDisasterState,
            )
            if event.status is DimensionalDisasterStatus.CLOSED:
                return False
            activity_state = self.snapshots.require(
                uow,
                self.storage.activity,
                GLOBAL_ACTIVITY_SCOPE_ID,
                ActivityState,
            )
            activity = activity_state.instances[event_id]
            expected = {value.subject_id for value in activity.ranking}
            if not expected.issubset(event.rewarded_character_ids):
                return False
            next_activity_state, _ = self._activity_operation(
                activity_state,
                FinalizeActivity(event_id),
                f"{event_id}:finalize",
                SYSTEM_ACTOR_ID,
                logical_time,
            )
            next_event = close_disaster(event)
            self.snapshots.update(
                uow,
                DIMENSIONAL_DISASTER_AGGREGATE,
                event_id,
                event,
                next_event,
                logical_time,
            )
            self.snapshots.update(
                uow,
                self.storage.activity,
                GLOBAL_ACTIVITY_SCOPE_ID,
                activity_state,
                next_activity_state,
                logical_time,
            )
            uow.commit()
            return True

    def _view_for(self, event: DimensionalDisasterState, *, active: bool) -> DimensionalDisasterView:
        activity_state = self._activity_state()
        activity = activity_state.instances.get(event.event_id) if activity_state else None
        return DimensionalDisasterView("ok", event, activity, active)

    def _activity_state(self) -> ActivityState | None:
        with self.database.unit_of_work(write=False) as uow:
            return self.snapshots.load(
                uow,
                self.storage.activity,
                GLOBAL_ACTIVITY_SCOPE_ID,
                ActivityState,
            )

    def _current_state(self, logical_time: datetime) -> DimensionalDisasterState | None:
        windows = self._current_windows(logical_time)
        if not windows:
            return None
        event_id = self._event_id(windows[0].instance_id)
        with self.database.unit_of_work(write=False) as uow:
            return self.snapshots.load(
                uow,
                DIMENSIONAL_DISASTER_AGGREGATE,
                event_id,
                DimensionalDisasterState,
            )

    def _latest_state(self) -> DimensionalDisasterState | None:
        with self.database.unit_of_work(write=False) as uow:
            states = self.snapshots.list(
                uow,
                DIMENSIONAL_DISASTER_AGGREGATE,
                DimensionalDisasterState,
                limit=1_000,
            )
        return max(states, key=lambda value: value.opens_at) if states else None

    def _current_windows(self, logical_time: datetime):
        return tuple(
            window
            for cycle_id in DIMENSIONAL_DISASTER_CYCLE_IDS
            if (
                window := self.content.catalog.cycle_engine.current_window(
                    cycle_id,
                    logical_time=logical_time,
                )
            ) is not None
        )

    def _activity_operation(
        self,
        state: ActivityState,
        operation,
        trace_id: str,
        actor_id: str,
        logical_time: datetime,
    ) -> tuple[ActivityState, ActivityInstance]:
        outcome = self.content.catalog.activity_engine.execute(
            ActivityCommand(trace_id, actor_id, state.revision, operation),
            state=state,
            context=_context(trace_id, logical_time),
        )
        if outcome.failure or outcome.value is None:
            raise RuntimeError(
                outcome.failure.message if outcome.failure else "灾厄活动状态变换失败"
            )
        return outcome.value.state, outcome.value.instance

    def _persist_activity_operation(
        self,
        uow,
        state: ActivityState,
        operation,
        trace_id: str,
        actor_id: str,
        logical_time: datetime,
    ) -> tuple[ActivityState, ActivityInstance]:
        next_state, instance = self._activity_operation(
            state,
            operation,
            trace_id,
            actor_id,
            logical_time,
        )
        self.snapshots.update(
            uow,
            self.storage.activity,
            GLOBAL_ACTIVITY_SCOPE_ID,
            state,
            next_state,
            logical_time,
        )
        return next_state, instance

    def _select_feather_owner(
        self,
        event: DimensionalDisasterState,
        activity: ActivityInstance,
    ) -> str | None:
        minimum = max(
            1,
            ceil(event.maximum_health * DIMENSIONAL_DISASTER_MINIMUM_CONTRIBUTION_RATIO),
        )
        candidates = tuple(
            value for value in activity.ranking if value.contribution >= minimum
        )
        if not candidates:
            candidates = tuple(
                value for value in activity.ranking if value.contribution > 0
            )
        if not candidates:
            return None
        weights = tuple(
            max(
                1,
                round(
                    min(
                        0.35,
                        sqrt(value.contribution / event.maximum_health),
                    )
                    * 1_000_000
                ),
            )
            for value in candidates
        )
        seed = int.from_bytes(
            sha256(f"disaster-feather.v1\0{event.event_id}".encode("utf-8")).digest(),
            "big",
        )
        rng = random.Random(seed)
        roll = rng.randrange(sum(weights))
        for candidate, weight in zip(candidates, weights):
            roll -= weight
            if roll < 0:
                return candidate.subject_id
        return candidates[-1].subject_id

    def _feather_history(self, event, activity, entry) -> str:
        date_text = event.opens_at.astimezone(self.timezone).strftime("%Y-%m-%d")
        return (
            f"{event.narrative.feather_text}\n"
            f"万象行纪记载：{date_text}，"
            f"{len(activity.participants)} 位归航者共同迎战 {event.narrative.name}。"
            f"最初持有者贡献 {entry.contribution / event.maximum_health:.1%}，"
            f"位列第 {entry.rank}。"
        )

    def _business_day(self, logical_time: datetime) -> str:
        local = logical_time.astimezone(self.timezone) - timedelta(
            hours=DIMENSIONAL_DISASTER_BUSINESS_DAY_RESET_HOUR
        )
        return local.date().isoformat()

    @staticmethod
    def _event_id(window_id: str) -> str:
        return f"dimensional-disaster:{window_id}"


def _context(trace_id: str, logical_time: datetime) -> RuleContext:
    return RuleContext(
        trace_id,
        DIMENSIONAL_DISASTER_RULESET_VERSION,
        Ruleset("ruleset.standard"),
        logical_time,
        SeededRandomSource(trace_id),
    )


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("次元灾厄逻辑时间必须包含时区")


__all__ = ["DimensionalDisasterFeature"]
