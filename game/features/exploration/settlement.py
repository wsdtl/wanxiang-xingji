"""持续探险批次的跨领域原子结算。"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from hashlib import sha256

from game.content.catalog import CHARACTER_LEVEL_PROGRESSION_ID
from game.content.catalog.character import (
    AUTO_HEALTH_TRIGGER_RATIO,
    AUTO_SPIRIT_TRIGGER_RATIO,
    REST_FULL_RECOVERY_SECONDS,
)
from game.features.errors import StalePreparationError
from game.core.gameplay import (
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    SPIRIT_MAXIMUM,
    CharacterState,
    InventoryState,
    InscriptionPreference,
    LoadoutState,
    LootRollCommand,
    LootState,
    RewardClaimState,
    RewardExpectations,
    RewardSettlement,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    WeaponState,
    WorldState,
)
from game.rules.character import (
    CHARACTER_SETTINGS_AGGREGATE,
    CharacterSettingsState,
    CharacterWorldState,
    MULTIVERSE_WORLD_STATE_ID,
    PRIMARY_LEDGER_ID,
)
from game.rules.companion import CompanionRosterState
from game.rules.encounter import EnemyEncounterGenerator
from game.rules.exploration import (
    EXPLORATION_AGGREGATE,
    EXPLORATION_RULESET_VERSION,
    EXPLORATION_VICTORY_FACT_KIND,
    ExplorationBatchPlan,
    ExplorationBatchPlanner,
    ExplorationBatchResult,
    ExplorationRewardKind,
    ExplorationRewardReference,
    ExplorationRestReason,
    ExplorationBattleSimulator,
    ExplorationState,
    ExplorationStatus,
    ExplorationStopReason,
    record_batch,
    stop_exploration,
)
from .medicine import ExplorationMedicineService
from .models import (
    MAX_CATCH_UP_BATCHES,
    MAX_DISCOVERABLE_EXPLORATIONS,
    MAX_EXPLORATION_BATCHES,
    ExplorationOperationResult,
    ExplorationVictoryFact,
    ExplorationStorageKinds,
)
from .reporting import (
    build_exploration_battle_report,
    build_exploration_battle_report_summary,
)
from .rewards import ExplorationRewardFactory, available_backpack_space


@dataclass(frozen=True)
class _BatchInputs:
    state: ExplorationState
    character: CharacterState
    character_world: CharacterWorldState
    view: object
    inventory: InventoryState
    loadout: LoadoutState
    roster: CompanionRosterState
    settings: CharacterSettingsState
    inscription_preference: InscriptionPreference | None
    character_level: int


@dataclass(frozen=True)
class _BatchSimulation:
    plan: ExplorationBatchPlan
    battle: object | None
    victory: bool
    draw: bool
    health_after: float
    spirit_after: float
    health_maximum: float
    spirit_maximum: float


@dataclass(frozen=True)
class _BatchRewards:
    character_experience: int = 0
    weapon_experience: int = 0
    companion_experience: int = 0
    weapon_drops: int = 0
    equipment_drops: int = 0
    trophy_drops: int = 0
    medicine_drops: int = 0
    draw_ticket_drops: int = 0
    trophy_value: int = 0
    references: tuple[ExplorationRewardReference, ...] = ()
    capacity_full: bool = False


@dataclass(frozen=True)
class _PreparedBatch:
    inputs: _BatchInputs
    simulation: _BatchSimulation
    context: RuleContext
    report: object | None


@dataclass(frozen=True)
class _PreparedBatchLimit:
    state: ExplorationState


@dataclass(frozen=True)
class _PreparedStop:
    state: ExplorationState
    reason: ExplorationStopReason


_STALE_BATCH = object()


class ExplorationSettlementService:
    """每个到期批次在一个工作单元内全部成功或回滚。"""

    def __init__(
        self,
        database,
        content,
        world_views,
        snapshots,
        rewards,
        inventory_engine,
        player_lineup,
        battle_reports,
        storage: ExplorationStorageKinds,
        reward_keys_factory,
        companion_growth,
        rest,
        settlement_observer=None,
    ) -> None:
        self.database = database
        self.content = content
        self.world_views = world_views
        self.snapshots = snapshots
        self.rewards = rewards
        self.battle_reports = battle_reports
        self.storage = storage
        self.reward_keys_factory = reward_keys_factory
        self.companion_growth = companion_growth
        self.rest = rest
        self.settlement_observer = settlement_observer
        catalog = content.catalog
        encounters = EnemyEncounterGenerator(
            catalog.enemies,
            content_version=catalog.report.content_fingerprint,
        )
        self.planner = ExplorationBatchPlanner(
            content.exploration_regions,
            encounters,
            content.enemy_behavior_profiles,
        )
        self.battles = ExplorationBattleSimulator(catalog, player_lineup)
        self.reward_factory = ExplorationRewardFactory(content)
        self.medicine = ExplorationMedicineService(
            content,
            snapshots,
            inventory_engine,
            storage,
        )

    def settle_due(
        self,
        character_id: str,
        *,
        logical_time: datetime,
        limit: int = MAX_CATCH_UP_BATCHES,
    ) -> ExplorationOperationResult:
        completed: list[ExplorationBatchResult] = []
        for _ in range(limit):
            result = self._settle_next(character_id, logical_time=logical_time)
            if result is None:
                break
            completed.append(result)
        return ExplorationOperationResult(
            "settled",
            self.load_state(character_id),
            tuple(completed),
        )

    def settle_all_due(
        self,
        *,
        logical_time: datetime,
        limit: int = MAX_DISCOVERABLE_EXPLORATIONS,
    ) -> int:
        settled = 0
        after_id: str | None = None
        while True:
            with self.database.unit_of_work(write=False) as uow:
                states = self.snapshots.list(
                    uow,
                    EXPLORATION_AGGREGATE,
                    ExplorationState,
                    limit=limit,
                    after_id=after_id,
                )
            if not states:
                break
            for state in states:
                if (
                    state.status is not ExplorationStatus.RUNNING
                    or state.next_batch_at > logical_time
                ):
                    continue
                result = self.settle_due(
                    state.character_id,
                    logical_time=logical_time,
                    limit=MAX_CATCH_UP_BATCHES,
                )
                settled += len(result.batches)
            after_id = states[-1].character_id
            if len(states) < limit:
                break
        return settled

    def load_state(self, character_id: str) -> ExplorationState | None:
        with self.database.unit_of_work(write=False) as uow:
            return self.snapshots.load(
                uow,
                EXPLORATION_AGGREGATE,
                character_id,
                ExplorationState,
            )

    def _settle_next(
        self,
        character_id: str,
        *,
        logical_time: datetime,
    ) -> ExplorationBatchResult | None:
        for _ in range(2):
            prepared = self._prepare_next(character_id, logical_time=logical_time)
            if prepared is None:
                return None
            if isinstance(prepared, (_PreparedBatchLimit, _PreparedStop)):
                reason = (
                    ExplorationStopReason.BATCH_LIMIT
                    if isinstance(prepared, _PreparedBatchLimit)
                    else prepared.reason
                )
                result = self._commit_stop(
                    character_id,
                    prepared.state,
                    logical_time,
                    reason,
                )
            else:
                result = self._commit_prepared_batch(character_id, prepared)
            if result is not _STALE_BATCH:
                return result
        raise StalePreparationError("探险批次准备结果连续过期，请重试")

    def _prepare_next(
        self,
        character_id: str,
        *,
        logical_time: datetime,
    ) -> _PreparedBatch | _PreparedBatchLimit | _PreparedStop | None:
        with self.database.unit_of_work(write=False) as uow:
            state = self.snapshots.load(
                uow, EXPLORATION_AGGREGATE, character_id, ExplorationState
            )
            if (
                state is None
                or state.status is not ExplorationStatus.RUNNING
                or state.next_batch_at > logical_time
            ):
                return None
            if state.batch_index >= MAX_EXPLORATION_BATCHES:
                return _PreparedBatchLimit(state)
            inputs = self._load_batch_inputs(uow, state, character_id)
            if not self._location_valid(uow, state, inputs.character_world):
                return _PreparedStop(state, ExplorationStopReason.INVALID_LOCATION)
        batch_index = state.batch_index + 1
        context = _context(
            f"{state.session_id}:batch:{batch_index}",
            state.next_batch_at,
        )
        simulation = self._simulate_batch(inputs, batch_index, context)
        report = None
        if simulation.battle is not None:
            provisional_result = self._batch_result(
                simulation,
                _BatchRewards(),
                resolved_at=context.logical_time,
                health_after=simulation.health_after,
                spirit_after=simulation.spirit_after,
                medicines_used=(),
            )
            provisional_state = record_batch(
                state,
                provisional_result,
                stop_reason=self._stop_reason(
                    simulation,
                    batch_index,
                    inputs.settings,
                ),
            )
            report = self.battle_reports.prepare_capture(
                build_exploration_battle_report(
                    self.content,
                    self.battle_reports.builder,
                    state,
                    provisional_state,
                    inputs.character,
                    inputs.character_world,
                    inputs.inventory,
                    inputs.loadout,
                    inputs.inscription_preference,
                    inputs.roster,
                    simulation.battle,
                    context.trace_id,
                    inputs.view,
                )
            )
        return _PreparedBatch(inputs, simulation, context, report)

    def _commit_stop(
        self,
        character_id: str,
        expected: ExplorationState,
        logical_time: datetime,
        reason: ExplorationStopReason,
    ):
        with self.database.unit_of_work() as uow:
            current = self.snapshots.load(
                uow,
                EXPLORATION_AGGREGATE,
                character_id,
                ExplorationState,
            )
            if current != expected:
                return _STALE_BATCH
            stopped = stop_exploration(
                current,
                reason,
                logical_time=logical_time,
            )
            self.snapshots.update(
                uow,
                EXPLORATION_AGGREGATE,
                character_id,
                current,
                stopped,
                logical_time,
            )
            uow.commit()
            return None

    def _commit_prepared_batch(
        self,
        character_id: str,
        prepared: _PreparedBatch,
    ):
        inputs = prepared.inputs
        simulation = prepared.simulation
        context = prepared.context
        resolved_at = inputs.state.next_batch_at
        batch_index = inputs.state.batch_index + 1
        with self.database.unit_of_work() as uow:
            state = self.snapshots.load(
                uow,
                EXPLORATION_AGGREGATE,
                character_id,
                ExplorationState,
            )
            if state != inputs.state:
                return _STALE_BATCH
            current_inputs = self._load_batch_inputs(uow, state, character_id)
            if not self._same_batch_inputs(inputs, current_inputs):
                return _STALE_BATCH
            if not self._location_valid(uow, state, current_inputs.character_world):
                self._stop_for_reason(
                    uow,
                    state,
                    character_id,
                    resolved_at,
                    ExplorationStopReason.INVALID_LOCATION,
                )
                uow.commit()
                return None
            rewards = self._settle_rewards_in_uow(
                uow,
                current_inputs,
                simulation,
                context,
            )
            if rewards.capacity_full:
                self._stop_for_capacity(uow, state, character_id, resolved_at)
                uow.commit()
                return None
            after_battle, medicines_used = self._apply_battle_resources_in_uow(
                uow,
                current_inputs,
                simulation,
                context,
            )
            result = self._batch_result(
                simulation,
                rewards,
                resolved_at=resolved_at,
                health_after=after_battle.resources[HEALTH_CURRENT],
                spirit_after=after_battle.resources[SPIRIT_CURRENT],
                medicines_used=medicines_used,
            )
            result = self._observe_victory_in_uow(
                uow,
                current_inputs,
                simulation,
                result,
            )
            stop_reason = self._stop_reason(
                simulation,
                batch_index,
                current_inputs.settings,
            )
            rest_reason = self._rest_reason(
                simulation,
                after_battle,
                current_inputs.settings,
            )
            if stop_reason is not None:
                rest_reason = None
            next_state = record_batch(
                state,
                result,
                stop_reason=stop_reason,
                rest_reason=rest_reason,
                rest_completes_at=(
                    resolved_at + timedelta(seconds=REST_FULL_RECOVERY_SECONDS)
                    if rest_reason is not None
                    else None
                ),
            )
            self.snapshots.update(
                uow,
                EXPLORATION_AGGREGATE,
                character_id,
                state,
                next_state,
                resolved_at,
            )
            if next_state.status is ExplorationStatus.RESTING:
                next_state = self.rest.start_in_uow(uow, next_state)
            if prepared.report is not None:
                self.battle_reports.capture_prepared_in_uow(
                    uow,
                    prepared.report.with_summary(
                        build_exploration_battle_report_summary(
                            next_state,
                            current_inputs.view,
                        )
                    ),
                )
            uow.commit()
            return result

    @staticmethod
    def _same_batch_inputs(left: _BatchInputs, right: _BatchInputs) -> bool:
        return (
            left.state,
            left.character,
            left.character_world,
            left.inventory,
            left.loadout,
            left.roster,
            left.settings,
            left.inscription_preference,
            left.character_level,
        ) == (
            right.state,
            right.character,
            right.character_world,
            right.inventory,
            right.loadout,
            right.roster,
            right.settings,
            right.inscription_preference,
            right.character_level,
        )

    @staticmethod
    def _stop_reason(
        simulation: _BatchSimulation,
        batch_index: int,
        settings: CharacterSettingsState,
    ) -> ExplorationStopReason | None:
        if batch_index >= MAX_EXPLORATION_BATCHES:
            return ExplorationStopReason.BATCH_LIMIT
        defeated = (
            simulation.plan.encounter is not None
            and not simulation.victory
            and not simulation.draw
        )
        if defeated and not settings.auto_rest:
            return ExplorationStopReason.DEFEATED
        return None

    @staticmethod
    def _rest_reason(
        simulation: _BatchSimulation,
        character: CharacterState,
        settings: CharacterSettingsState,
    ) -> ExplorationRestReason | None:
        if not settings.auto_rest:
            return None
        if (
            simulation.plan.encounter is not None
            and not simulation.victory
            and not simulation.draw
        ):
            return ExplorationRestReason.DEFEATED
        health_low = (
            simulation.health_maximum > 0
            and character.resources[HEALTH_CURRENT] / simulation.health_maximum
            < AUTO_HEALTH_TRIGGER_RATIO
        )
        spirit_low = (
            simulation.spirit_maximum > 0
            and character.resources[SPIRIT_CURRENT] / simulation.spirit_maximum
            < AUTO_SPIRIT_TRIGGER_RATIO
        )
        return ExplorationRestReason.LOW_RESOURCES if health_low or spirit_low else None

    @staticmethod
    def _batch_result(
        simulation: _BatchSimulation,
        rewards: _BatchRewards,
        *,
        resolved_at: datetime,
        health_after: float,
        spirit_after: float,
        medicines_used,
    ) -> ExplorationBatchResult:
        return ExplorationBatchResult(
            plan=simulation.plan,
            resolved_at=resolved_at,
            victory=simulation.victory,
            draw=simulation.draw,
            health_after=health_after,
            spirit_after=spirit_after,
            character_experience=rewards.character_experience,
            weapon_experience=rewards.weapon_experience,
            companion_experience=rewards.companion_experience,
            weapon_drops=rewards.weapon_drops,
            equipment_drops=rewards.equipment_drops,
            trophy_drops=rewards.trophy_drops,
            medicine_drops=rewards.medicine_drops,
            draw_ticket_drops=rewards.draw_ticket_drops,
            trophy_value=rewards.trophy_value,
            rewards=rewards.references,
            medicines_used=tuple(medicines_used),
        )

    def _load_batch_inputs(
        self,
        uow,
        state: ExplorationState,
        character_id: str,
    ) -> _BatchInputs:
        character = self.snapshots.require(
            uow, self.storage.character, character_id, CharacterState
        )
        character_world = self.snapshots.require(
            uow,
            self.storage.character_world,
            character_id,
            CharacterWorldState,
        )
        inventory = self.snapshots.require(
            uow, self.storage.inventory, character_id, InventoryState
        )
        loadout = self.snapshots.require(
            uow, self.storage.loadout, character_id, LoadoutState
        )
        roster = self.snapshots.load(
            uow,
            self.storage.companion_roster,
            character_id,
            CompanionRosterState,
        ) or CompanionRosterState(character_id)
        settings = self.snapshots.require(
            uow,
            CHARACTER_SETTINGS_AGGREGATE,
            character_id,
            CharacterSettingsState,
        )
        inscription_preference = self.snapshots.load(
            uow,
            self.storage.inscription_preference,
            character_id,
            InscriptionPreference,
        )
        level = character.progressions[CHARACTER_LEVEL_PROGRESSION_ID].level
        return _BatchInputs(
            state,
            character,
            character_world,
            self.world_views.require(character_world.world_id),
            inventory,
            loadout,
            roster,
            settings,
            inscription_preference,
            level,
        )

    def _simulate_batch(
        self,
        inputs: _BatchInputs,
        batch_index: int,
        context: RuleContext,
    ) -> _BatchSimulation:
        plan = self.planner.plan(
            session_id=inputs.state.session_id,
            batch_index=batch_index,
            region_id=inputs.state.region_id,
            world_id=inputs.character_world.world_id,
            character_level=inputs.character_level,
            random=context.random,
        )
        if plan.encounter is None:
            return _BatchSimulation(
                plan,
                None,
                False,
                False,
                inputs.character.resources[HEALTH_CURRENT],
                inputs.character.resources[SPIRIT_CURRENT],
                float(inputs.character.core_attributes[HEALTH_MAXIMUM]),
                float(inputs.character.core_attributes[SPIRIT_MAXIMUM]),
            )
        battle = self.battles.simulate(
            plan,
            character=inputs.character,
            inventory=inputs.inventory,
            loadout=inputs.loadout,
            roster=inputs.roster,
            context=context,
        )
        return _BatchSimulation(
            plan,
            battle,
            battle.victory,
            battle.draw,
            battle.health_after,
            battle.spirit_after,
            battle.health_maximum,
            battle.spirit_maximum,
        )

    def _settle_rewards_in_uow(
        self,
        uow,
        inputs: _BatchInputs,
        simulation: _BatchSimulation,
        context: RuleContext,
    ) -> _BatchRewards:
        plan = simulation.plan
        if not simulation.victory or plan.encounter is None:
            return _BatchRewards()
        quotes = tuple(
            self.content.catalog.enemy_threat.reward_quote(enemy)
            for enemy in plan.encounter.enemies
        )
        character_experience = sum(value.character_experience for value in quotes)
        weapon_experience = sum(value.weapon_experience for value in quotes)
        companion_experience = 0
        battle = simulation.battle
        if battle is not None and battle.player_companion_id is not None:
            companion_experience = self.companion_growth.engine.exploration_experience(
                plan.encounter_kind.value,
                tuple(enemy.level for enemy in plan.encounter.enemies),
            )
        loot_state = self.snapshots.require(
            uow,
            self.storage.loot,
            inputs.character.id,
            LootState,
        )
        region = self.content.exploration_regions.require(inputs.state.region_id)
        loot_outcome = self.content.catalog.loot_engine.roll(
            LootRollCommand(
                f"{context.trace_id}:loot",
                inputs.character.id,
                region.loot_table_id(plan.encounter_kind.value),
                loot_state.revision,
                sum(value.loot_rolls for value in quotes),
                plan.loot_modifiers,
            ),
            state=loot_state,
            context=context,
        )
        if loot_outcome.failure or loot_outcome.value is None:
            raise RuntimeError(
                loot_outcome.failure.message
                if loot_outcome.failure
                else "探险掉落失败"
            )
        reward_build = self.reward_factory.build(
            loot_outcome.value.receipt.awards,
            plan=plan,
            character=inputs.character,
            inventory=inputs.inventory,
            loadout=inputs.loadout,
            character_experience=character_experience,
            weapon_experience=weapon_experience,
            context=context,
        )
        remaining_space = available_backpack_space(
            inputs.inventory,
            self.content.catalog.items,
        )
        if (
            remaining_space is not None
            and reward_build.backpack_space > remaining_space
        ):
            return _BatchRewards(capacity_full=True)

        self.snapshots.update(
            uow,
            self.storage.loot,
            inputs.character.id,
            loot_state,
            loot_outcome.value.state,
            inputs.state.next_batch_at,
        )
        weapon_revisions = (
            self._weapon_revisions(uow, inputs.loadout)
            if weapon_experience > 0
            else {}
        )
        has_inventory_drops = any((
            reward_build.weapon_drops,
            reward_build.equipment_drops,
            reward_build.trophy_drops,
            reward_build.medicine_drops,
            reward_build.draw_ticket_drops,
        ))
        settlement = RewardSettlement(
            f"{context.trace_id}:reward",
            inputs.character.id,
            inputs.character.id,
            "source.exploration",
            f"{inputs.state.session_id}:{plan.batch_index}",
            reward_build.rewards,
            RewardExpectations(
                claim_revision=self._claim_revision(uow, inputs.character.id),
                inventory_revision=(
                    inputs.inventory.revision if has_inventory_drops else None
                ),
                character_revisions={
                    inputs.character.id: inputs.character.revision
                },
                weapon_revisions=weapon_revisions,
            ),
        )
        keys = self.reward_keys_factory(
            inputs.character.id,
            PRIMARY_LEDGER_ID,
            (inputs.character.id,),
            tuple(weapon_revisions),
        )
        reward_outcome = self.rewards.settle_in_uow(
            uow,
            settlement,
            keys,
            context=context,
        )
        if reward_outcome.failure:
            raise RuntimeError(reward_outcome.failure.message)
        companion_growth = self.companion_growth.grant_in_uow(
            uow,
            inputs.character.id,
            battle.player_companion_id if battle is not None else None,
            companion_experience,
            character_level=inputs.character_level,
            logical_time=inputs.state.next_batch_at,
        )
        return _BatchRewards(
            character_experience=character_experience,
            weapon_experience=weapon_experience,
            companion_experience=(
                companion_growth.accepted if companion_growth is not None else 0
            ),
            weapon_drops=reward_build.weapon_drops,
            equipment_drops=reward_build.equipment_drops,
            trophy_drops=reward_build.trophy_drops,
            medicine_drops=reward_build.medicine_drops,
            draw_ticket_drops=reward_build.draw_ticket_drops,
            trophy_value=reward_build.trophy_value,
            references=tuple(reward_build.references),
        )

    def _apply_battle_resources_in_uow(
        self,
        uow,
        inputs: _BatchInputs,
        simulation: _BatchSimulation,
        context: RuleContext,
    ):
        current = self.snapshots.require(
            uow,
            self.storage.character,
            inputs.character.id,
            CharacterState,
        )
        resources = dict(current.resources)
        resources[HEALTH_CURRENT] = simulation.health_after
        resources[SPIRIT_CURRENT] = simulation.spirit_after
        after_battle = current
        if resources != dict(current.resources):
            after_battle = replace(
                current,
                resources=resources,
                revision=current.revision + 1,
            )
            self.snapshots.update(
                uow,
                self.storage.character,
                current.id,
                current,
                after_battle,
                inputs.state.next_batch_at,
            )
        medicines_used = ()
        defeated_without_rest = (
            simulation.plan.encounter is not None
            and not simulation.victory
            and not simulation.draw
            and not inputs.settings.auto_rest
        )
        if inputs.settings.auto_use_medicine and not defeated_without_rest:
            after_battle, medicines_used = self.medicine.apply(
                uow,
                after_battle,
                simulation.health_maximum,
                simulation.spirit_maximum,
                context,
            )
        return after_battle, medicines_used

    def _observe_victory_in_uow(
        self,
        uow,
        inputs: _BatchInputs,
        simulation: _BatchSimulation,
        result: ExplorationBatchResult,
    ) -> ExplorationBatchResult:
        if not simulation.victory or simulation.plan.encounter is None:
            return result
        fact = ExplorationVictoryFact(
            event_id=f"{inputs.state.session_id}:batch:{simulation.plan.batch_index}",
            character_id=inputs.character.id,
            character_name=inputs.character.name,
            world_id=inputs.character_world.world_id,
            region_id=inputs.state.region_id,
            encounter_kind=simulation.plan.encounter_kind.value,
            resolved_at=inputs.state.next_batch_at,
        )
        self._append_victory_fact(uow, fact)
        if self.settlement_observer is None:
            return result
        observation = self.settlement_observer.observe_victory_in_uow(uow, fact)
        if not observation.reward_items:
            return result
        return replace(
            result,
            rewards=(
                *result.rewards,
                *(
                    ExplorationRewardReference(
                        ExplorationRewardKind.ITEM,
                        definition_id,
                        quantity,
                    )
                    for definition_id, quantity in observation.reward_items
                ),
            ),
        )

    def _stop_for_capacity(
        self,
        uow,
        state: ExplorationState,
        character_id: str,
        resolved_at: datetime,
    ) -> None:
        self._stop_for_reason(
            uow,
            state,
            character_id,
            resolved_at,
            ExplorationStopReason.CAPACITY_FULL,
        )

    def _stop_for_reason(
        self,
        uow,
        state: ExplorationState,
        character_id: str,
        resolved_at: datetime,
        reason: ExplorationStopReason,
    ) -> None:
        stopped = stop_exploration(
            state,
            reason,
            logical_time=resolved_at,
        )
        self.snapshots.update(
            uow,
            EXPLORATION_AGGREGATE,
            character_id,
            state,
            stopped,
            resolved_at,
        )

    def _location_valid(
        self,
        uow,
        state: ExplorationState,
        character_world: CharacterWorldState,
    ) -> bool:
        world = self.snapshots.require(
            uow,
            self.storage.world,
            MULTIVERSE_WORLD_STATE_ID,
            WorldState,
        )
        presence = next(
            (
                value
                for value in world.presences.values()
                if value.owner_id == state.character_id
            ),
            None,
        )
        if presence is None:
            return False
        resolved = self.content.worlds.resolve_position(
            character_world.world_id,
            presence.position,
            function_id="location.function.exploration",
        )
        return (
            resolved is not None
            and resolved.binding.content_ref == state.region_id
        )

    def _weapon_revisions(self, uow, loadout: LoadoutState) -> dict[str, int]:
        if loadout.weapon_asset_id is None:
            return {}
        weapon = self.snapshots.require(
            uow,
            self.storage.weapon,
            loadout.weapon_asset_id,
            WeaponState,
        )
        return {weapon.asset_id: weapon.revision}

    def _claim_revision(self, uow, character_id: str) -> int:
        return self.snapshots.require(
            uow,
            self.storage.reward_claim,
            character_id,
            RewardClaimState,
        ).revision

    def _append_victory_fact(self, uow, fact: ExplorationVictoryFact) -> None:
        transaction_id = f"exploration-victory:{fact.event_id}"
        payload = self.snapshots.codec.dumps(fact)
        timestamp = fact.resolved_at.isoformat()
        uow.insert_transaction(
            transaction_id,
            sha256(payload.encode("utf-8")).hexdigest(),
            fact.character_id,
            payload,
            timestamp,
        )
        uow.append_fact(
            transaction_id,
            0,
            EXPLORATION_VICTORY_FACT_KIND,
            payload,
            timestamp,
        )


def _context(trace_id: str, logical_time: datetime) -> RuleContext:
    return RuleContext(
        trace_id,
        EXPLORATION_RULESET_VERSION,
        Ruleset("ruleset.standard"),
        logical_time,
        SeededRandomSource(trace_id),
    )


__all__ = ["ExplorationSettlementService"]
