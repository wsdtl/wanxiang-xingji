"""休息行动、累计恢复窗口与人物资源的原子协调。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from game.content.catalog.character import (
    REST_ACTION_ID,
    REST_FULL_RECOVERY_SECONDS,
    REST_MINIMUM_RECOVERY_RATIO,
    REST_MINIMUM_SECONDS,
)
from game.core.gameplay import (
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    SPIRIT_MAXIMUM,
    ActionResult,
    ActionSlotKind,
    ActionSnapshot,
    ActionState,
    ActionTransaction,
    CancelAction,
    ChangeCharacterResource,
    CharacterState,
    CharacterTransaction,
    ClaimAction,
    CompleteAction,
    InventoryState,
    LoadoutState,
    StartAction,
)
from game.rules.character import equipped_character_contributions
from game.rules.context import game_operation_context
from game.rules.exploration import ExplorationState, ExplorationStatus
from game.rules.rest import (
    REST_RECOVERY_AGGREGATE,
    REST_RULESET_VERSION,
    RestOperationResult,
    RestRecoveryState,
)


@dataclass(frozen=True)
class RestStorageKinds:
    action: str
    character: str
    inventory: str
    loadout: str
    exploration: str


class RestFeature:
    """休息玩法唯一写入口。"""

    def __init__(
        self,
        database,
        content,
        snapshots,
        actions,
        character_engine,
        character_projector,
        storage: RestStorageKinds,
    ) -> None:
        self.database = database
        self.content = content
        self.snapshots = snapshots
        self.actions = actions
        self.character_engine = character_engine
        self.character_projector = character_projector
        self.storage = storage

    def view(self, character_id: str, *, logical_time: datetime) -> RestOperationResult:
        with self.database.unit_of_work(write=False) as uow:
            character = self.snapshots.require(
                uow, self.storage.character, character_id, CharacterState
            )
            inventory = self.snapshots.require(
                uow, self.storage.inventory, character_id, InventoryState
            )
            loadout = self.snapshots.require(
                uow, self.storage.loadout, character_id, LoadoutState
            )
            action_state = self.snapshots.load(
                uow, self.storage.action, character_id, ActionState
            )
            recovery = self.snapshots.load(
                uow, REST_RECOVERY_AGGREGATE, character_id, RestRecoveryState
            )
        health_maximum, spirit_maximum = self._maximums(character, inventory, loadout)
        action = self._running_rest(action_state)
        accumulated = recovery.accumulated_seconds if recovery else 0.0
        if action is not None:
            accumulated += self._elapsed(action, logical_time)
        return RestOperationResult(
            "running" if action else "idle",
            character,
            action,
            recovery,
            health_maximum,
            spirit_maximum,
            progress_ratio=_recovery_ratio(accumulated),
        )

    def start(
        self,
        operation_id: str,
        character_id: str,
        *,
        logical_time: datetime,
    ) -> RestOperationResult:
        context = game_operation_context(operation_id, logical_time=logical_time)
        with self.database.unit_of_work() as uow:
            exploration = self.snapshots.load(
                uow, self.storage.exploration, character_id, ExplorationState
            )
            if exploration is not None and exploration.status is ExplorationStatus.RUNNING:
                return RestOperationResult("exploring")
            character = self.snapshots.require(
                uow, self.storage.character, character_id, CharacterState
            )
            inventory = self.snapshots.require(
                uow, self.storage.inventory, character_id, InventoryState
            )
            loadout = self.snapshots.require(
                uow, self.storage.loadout, character_id, LoadoutState
            )
            health_maximum, spirit_maximum = self._maximums(character, inventory, loadout)
            if (
                character.resources[HEALTH_CURRENT] >= health_maximum
                and character.resources[SPIRIT_CURRENT] >= spirit_maximum
            ):
                return RestOperationResult(
                    "full",
                    character,
                    health_maximum=health_maximum,
                    spirit_maximum=spirit_maximum,
                )
            action_state = self.snapshots.load(
                uow, self.storage.action, character_id, ActionState
            )
            if action_state is None:
                action_state = ActionState(character_id)
                self.snapshots.insert(
                    uow,
                    self.storage.action,
                    character_id,
                    action_state,
                    logical_time,
                )
            running_rest = self._running_rest(action_state)
            if running_rest is not None:
                return RestOperationResult("already_running", character, running_rest)
            if action_state.running(ActionSlotKind.MAIN):
                return RestOperationResult("main_action_occupied", character)

            previous_recovery = self.snapshots.load(
                uow, REST_RECOVERY_AGGREGATE, character_id, RestRecoveryState
            )
            recovery = self._prepare_window(character, previous_recovery)
            if previous_recovery is None:
                self.snapshots.insert(
                    uow,
                    REST_RECOVERY_AGGREGATE,
                    character_id,
                    recovery,
                    logical_time,
                )
            elif recovery != previous_recovery:
                self.snapshots.update(
                    uow,
                    REST_RECOVERY_AGGREGATE,
                    character_id,
                    previous_recovery,
                    recovery,
                    logical_time,
                )

            action_id = f"rest:{character_id}:{logical_time.isoformat()}"
            transaction = ActionTransaction(
                operation_id,
                character_id,
                action_state.revision,
                (
                    StartAction(
                        action_id,
                        REST_ACTION_ID,
                        ActionSnapshot(
                            logical_time,
                            REST_RULESET_VERSION,
                            self.content.report.content_fingerprint,
                            operation_id,
                            character.revision,
                            loadout.revision,
                            {"recovery_revision": recovery.revision},
                        ),
                    ),
                ),
            )
            outcome = self.actions.execute_in_uow(uow, transaction, context=context)
            if outcome.failure or outcome.value is None:
                return RestOperationResult(
                    "failed",
                    character,
                    recovery=recovery,
                    failure_message=(outcome.failure.message if outcome.failure else "休息没有开始"),
                )
            uow.commit()
            return RestOperationResult(
                "started",
                character,
                outcome.value.execution.transitions[-1],
                recovery,
                health_maximum,
                spirit_maximum,
                progress_ratio=_recovery_ratio(recovery.accumulated_seconds),
            )

    def stop(
        self,
        operation_id: str,
        character_id: str,
        *,
        logical_time: datetime,
    ) -> RestOperationResult:
        context = game_operation_context(operation_id, logical_time=logical_time)
        with self.database.unit_of_work() as uow:
            action_state = self.snapshots.load(
                uow, self.storage.action, character_id, ActionState
            )
            action = self._running_rest(action_state)
            if action is None or action_state is None:
                return RestOperationResult("not_running")
            character = self.snapshots.require(
                uow, self.storage.character, character_id, CharacterState
            )
            inventory = self.snapshots.require(
                uow, self.storage.inventory, character_id, InventoryState
            )
            loadout = self.snapshots.require(
                uow, self.storage.loadout, character_id, LoadoutState
            )
            recovery = self.snapshots.require(
                uow, REST_RECOVERY_AGGREGATE, character_id, RestRecoveryState
            )
            health_maximum, spirit_maximum = self._maximums(character, inventory, loadout)
            accumulated = recovery.accumulated_seconds + self._elapsed(action, logical_time)
            ratio = _recovery_ratio(accumulated)
            health_target = recovery.baseline_health + max(
                0.0, health_maximum - recovery.baseline_health
            ) * ratio
            spirit_target = recovery.baseline_spirit + max(
                0.0, spirit_maximum - recovery.baseline_spirit
            ) * ratio
            health_current = character.resources[HEALTH_CURRENT]
            spirit_current = character.resources[SPIRIT_CURRENT]
            health_gain = max(0.0, min(health_maximum, health_target) - health_current)
            spirit_gain = max(0.0, min(spirit_maximum, spirit_target) - spirit_current)
            updated_character = character
            character_events = ()
            operations = tuple(
                ChangeCharacterResource(resource_id, amount, "source.rest", action.id)
                for resource_id, amount in (
                    (HEALTH_CURRENT, health_gain),
                    (SPIRIT_CURRENT, spirit_gain),
                )
                if amount > 0
            )
            if operations:
                character_outcome = self.character_engine.execute(
                    CharacterTransaction(
                        f"{operation_id}:character",
                        character_id,
                        character.revision,
                        "character.rest",
                        operations,
                    ),
                    state=character,
                    context=context,
                )
                if character_outcome.failure or character_outcome.value is None:
                    return RestOperationResult(
                        "failed",
                        character,
                        action,
                        recovery,
                        health_maximum,
                        spirit_maximum,
                        failure_message=(
                            character_outcome.failure.message
                            if character_outcome.failure
                            else "休息恢复没有完成"
                        ),
                    )
                updated_character = character_outcome.value.state
                character_events = character_outcome.value.events
                self.snapshots.update(
                    uow,
                    self.storage.character,
                    character_id,
                    character,
                    updated_character,
                    logical_time,
                )

            due = logical_time >= action.completes_at
            action_operations = (
                (
                    CompleteAction(
                        action.id,
                        ActionResult("outcome.rest_completed", logical_time),
                    ),
                    ClaimAction(action.id),
                )
                if due
                else (CancelAction(action.id),)
            )
            action_outcome = self.actions.execute_in_uow(
                uow,
                ActionTransaction(
                    operation_id,
                    character_id,
                    action_state.revision,
                    action_operations,
                ),
                context=context,
            )
            if action_outcome.failure or action_outcome.value is None:
                return RestOperationResult(
                    "failed",
                    character,
                    action,
                    recovery,
                    health_maximum,
                    spirit_maximum,
                    failure_message=(
                        action_outcome.failure.message
                        if action_outcome.failure
                        else "休息行动没有结束"
                    ),
                )

            timestamp = logical_time.isoformat()
            sequence = len(action_outcome.value.execution.events)
            for offset, event in enumerate(character_events):
                uow.append_fact(
                    operation_id,
                    sequence + offset,
                    event.kind,
                    self.snapshots.codec.dumps(event),
                    timestamp,
                )

            fully_recovered = (
                updated_character.resources[HEALTH_CURRENT] >= health_maximum
                and updated_character.resources[SPIRIT_CURRENT] >= spirit_maximum
            )
            if fully_recovered or ratio >= 1.0:
                current_recovery = RestRecoveryState(
                    character_id,
                    updated_character.resources[HEALTH_CURRENT],
                    updated_character.resources[SPIRIT_CURRENT],
                    updated_character.resources[HEALTH_CURRENT],
                    updated_character.resources[SPIRIT_CURRENT],
                    revision=recovery.revision + 1,
                )
            else:
                current_recovery = replace(
                    recovery,
                    last_health=updated_character.resources[HEALTH_CURRENT],
                    last_spirit=updated_character.resources[SPIRIT_CURRENT],
                    accumulated_seconds=accumulated,
                    revision=recovery.revision + 1,
                )
            self.snapshots.update(
                uow,
                REST_RECOVERY_AGGREGATE,
                character_id,
                recovery,
                current_recovery,
                logical_time,
            )
            uow.commit()
            return RestOperationResult(
                "completed" if due or fully_recovered else "stopped",
                updated_character,
                action,
                current_recovery,
                health_maximum,
                spirit_maximum,
                health_gain,
                spirit_gain,
                ratio,
            )

    def settle_all_due(self, *, logical_time: datetime, limit: int = 1_000) -> int:
        with self.database.unit_of_work(write=False) as uow:
            states = self.snapshots.list(
                uow, self.storage.action, ActionState, limit=limit
            )
        settled = 0
        for state in states:
            action = self._running_rest(state)
            if action is None or action.completes_at > logical_time:
                continue
            result = self.stop(
                f"rest:auto_complete:{action.id}",
                state.owner_id,
                logical_time=logical_time,
            )
            if result.status == "completed":
                settled += 1
        return settled

    def _maximums(self, character, inventory, loadout) -> tuple[float, float]:
        contributions = equipped_character_contributions(
            self.content,
            inventory,
            loadout,
        )
        entity = self.character_projector.project(
            character,
            contributions=contributions,
        ).entity
        snapshot = entity.snapshot(self.character_projector.attributes)
        return float(snapshot.value(HEALTH_MAXIMUM)), float(snapshot.value(SPIRIT_MAXIMUM))

    @staticmethod
    def _prepare_window(
        character: CharacterState,
        previous: RestRecoveryState | None,
    ) -> RestRecoveryState:
        health = character.resources[HEALTH_CURRENT]
        spirit = character.resources[SPIRIT_CURRENT]
        if previous is None or health < previous.last_health or spirit < previous.last_spirit:
            return RestRecoveryState(
                character.id,
                health,
                spirit,
                health,
                spirit,
                revision=(previous.revision + 1 if previous else 0),
            )
        if health == previous.last_health and spirit == previous.last_spirit:
            return previous
        return replace(
            previous,
            last_health=health,
            last_spirit=spirit,
            revision=previous.revision + 1,
        )

    @staticmethod
    def _running_rest(state: ActionState | None):
        if state is None:
            return None
        return next(
            (
                action
                for action in state.running(ActionSlotKind.MAIN)
                if action.definition_id == REST_ACTION_ID
            ),
            None,
        )

    @staticmethod
    def _elapsed(action, logical_time: datetime) -> float:
        effective = min(logical_time, action.completes_at)
        return max(0.0, (effective - action.started_at).total_seconds())


def _recovery_ratio(seconds: float) -> float:
    if seconds < REST_MINIMUM_SECONDS:
        return 0.0
    if seconds >= REST_FULL_RECOVERY_SECONDS:
        return 1.0
    progress = (seconds - REST_MINIMUM_SECONDS) / (
        REST_FULL_RECOVERY_SECONDS - REST_MINIMUM_SECONDS
    )
    return REST_MINIMUM_RECOVERY_RATIO + (1.0 - REST_MINIMUM_RECOVERY_RATIO) * progress


__all__ = ["RestFeature", "RestStorageKinds"]
