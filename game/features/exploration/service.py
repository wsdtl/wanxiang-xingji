"""持续探险玩法的唯一公开入口。"""

from dataclasses import replace
from datetime import datetime

from game.core.gameplay import (
    ActionSlotKind,
    ActionState,
    HEALTH_CURRENT,
    CharacterState,
    WorldState,
)
from game.rules.character import MULTIVERSE_WORLD_STATE_ID
from game.rules.exploration import (
    EXPLORATION_AGGREGATE,
    ExplorationBatchResult,
    ExplorationState,
    ExplorationStatus,
    ExplorationStopReason,
    start_exploration,
    stop_exploration,
)
from game.rules.character import CharacterWorldState

from .models import (
    MAX_CATCH_UP_BATCHES,
    MAX_DISCOVERABLE_EXPLORATIONS,
    ExplorationOperationResult,
    ExplorationStorageKinds,
)
from .recovery import ExplorationRestCoordinator
from .settlement import ExplorationSettlementService


class ExplorationFeature:
    """组织探险启停和批次结算，不承担通用世界移动。"""

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
        self.snapshots = snapshots
        self.storage = storage
        self.rest = ExplorationRestCoordinator(database, snapshots, rest)
        self.settlement = ExplorationSettlementService(
            database,
            content,
            world_views,
            snapshots,
            rewards,
            inventory_engine,
            player_lineup,
            battle_reports,
            storage,
            reward_keys_factory,
            companion_growth,
            self.rest,
            settlement_observer,
        )

    def start(self, character_id: str, *, logical_time: datetime) -> ExplorationOperationResult:
        with self.database.unit_of_work() as uow:
            action_state = self.snapshots.load(
                uow, self.storage.action, character_id, ActionState
            )
            if action_state is not None and action_state.running(ActionSlotKind.MAIN):
                return ExplorationOperationResult("main_action_occupied")
            previous = self.snapshots.load(
                uow, EXPLORATION_AGGREGATE, character_id, ExplorationState
            )
            if previous is not None and previous.active:
                return ExplorationOperationResult("already_running", previous)
            character = self.snapshots.require(
                uow, self.storage.character, character_id, CharacterState
            )
            if character.resources[HEALTH_CURRENT] <= 0:
                return ExplorationOperationResult("health_depleted", previous)
            world = self.snapshots.require(
                uow, self.storage.world, MULTIVERSE_WORLD_STATE_ID, WorldState
            )
            presence = _presence(world, character_id)
            character_world = self.snapshots.require(
                uow,
                self.storage.character_world,
                character_id,
                CharacterWorldState,
            )
            resolved = self.content.worlds.resolve_position(
                character_world.world_id,
                presence.position,
                function_id="location.function.exploration",
            )
            if resolved is None:
                return ExplorationOperationResult("not_in_region", previous)
            try:
                region = self.content.exploration_regions.require(
                    resolved.require_content_ref()
                )
            except KeyError:
                return ExplorationOperationResult("not_in_region", previous)
            session_id = f"exploration:{character_id}:{logical_time.isoformat()}"
            current = start_exploration(
                character_id,
                session_id,
                region.id,
                region.location_id,
                logical_time=logical_time,
            )
            if previous is None:
                self.snapshots.insert(
                    uow, EXPLORATION_AGGREGATE, character_id, current, logical_time
                )
            else:
                current = replace(current, revision=previous.revision + 1)
                self.snapshots.update(
                    uow,
                    EXPLORATION_AGGREGATE,
                    character_id,
                    previous,
                    current,
                    logical_time,
                )
            uow.commit()
            return ExplorationOperationResult("started", current)

    def stop(self, character_id: str, *, logical_time: datetime) -> ExplorationOperationResult:
        settled = self.settle_due(character_id, logical_time=logical_time)
        with self.database.unit_of_work() as uow:
            current = self.snapshots.load(
                uow, EXPLORATION_AGGREGATE, character_id, ExplorationState
            )
            if current is None:
                return ExplorationOperationResult("not_started", batches=settled.batches)
            if current.status is ExplorationStatus.STOPPED:
                return ExplorationOperationResult("already_stopped", current, settled.batches)
            self.rest.stop_in_uow(uow, current, logical_time=logical_time)
            stopped = stop_exploration(
                current,
                ExplorationStopReason.MANUAL,
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
            return ExplorationOperationResult("stopped", stopped, settled.batches)

    def load(
        self,
        character_id: str,
        *,
        logical_time: datetime,
        settle_due: bool = True,
    ) -> ExplorationOperationResult:
        batches: tuple[ExplorationBatchResult, ...] = ()
        if settle_due:
            batches = self.settle_due(character_id, logical_time=logical_time).batches
        state = self.settlement.load_state(character_id)
        return ExplorationOperationResult("ok" if state else "not_started", state, batches)

    def settle_due(
        self,
        character_id: str,
        *,
        logical_time: datetime,
        limit: int = MAX_CATCH_UP_BATCHES,
    ) -> ExplorationOperationResult:
        completed: list[ExplorationBatchResult] = []
        for _ in range(limit):
            self.rest.resume_due(character_id, logical_time=logical_time)
            result = self.settlement.settle_due(
                character_id,
                logical_time=logical_time,
                limit=1,
            )
            if not result.batches:
                break
            completed.extend(result.batches)
        return ExplorationOperationResult(
            "settled",
            self.settlement.load_state(character_id),
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
                if state.status is ExplorationStatus.STOPPED:
                    continue
                if (
                    state.status is ExplorationStatus.RUNNING
                    and state.next_batch_at > logical_time
                ):
                    continue
                if (
                    state.status is ExplorationStatus.RESTING
                    and state.rest_completes_at is not None
                    and state.rest_completes_at > logical_time
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


def _presence(world: WorldState, character_id: str):
    return next(value for value in world.presences.values() if value.owner_id == character_id)


__all__ = ["ExplorationFeature"]
