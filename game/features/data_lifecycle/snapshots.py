"""按领域规则压缩短期快照，不触碰角色与资产权威状态。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from game.content.catalog.character import REST_ACTION_ID
from game.core.gameplay import (
    ActionSlotKind,
    ActionState,
    ActivityState,
    ActivityStatus,
    SocialState,
)
from game.features.lottery.service import LOTTERY_AGGREGATE
from game.rules.disaster import (
    DIMENSIONAL_DISASTER_AGGREGATE,
    DimensionalDisasterState,
    DimensionalDisasterStatus,
)
from game.rules.lottery import LotteryState
from game.rules.rest import REST_RECOVERY_AGGREGATE, RestRecoveryState


TERMINAL_STATE_RETENTION = timedelta(hours=6)
HISTORY_LIMIT = 20


@dataclass(frozen=True)
class SnapshotLifecycleStorageKinds:
    action: str
    activity: str
    social: str

    def __post_init__(self) -> None:
        if not self.action.strip() or not self.activity.strip() or not self.social.strip():
            raise ValueError("快照生命周期存储键不能为空")


@dataclass(frozen=True)
class SnapshotLifecycleReceipt:
    expired_snapshots: int = 0
    social_requests: int = 0
    lottery_rounds: int = 0
    activity_instances: int = 0
    disaster_events: int = 0
    rest_windows: int = 0


class SnapshotLifecycleService:
    """维护可丢弃运行态；所有删除都有状态或期限依据。"""

    def __init__(
        self,
        database,
        snapshots,
        storage: SnapshotLifecycleStorageKinds,
        *,
        batch_size: int = 5_000,
    ) -> None:
        if batch_size < 1:
            raise ValueError("快照生命周期批量必须大于 0")
        self.database = database
        self.snapshots = snapshots
        self.storage = storage
        self.batch_size = batch_size

    def cleanup(self, *, logical_time: datetime) -> SnapshotLifecycleReceipt:
        _aware(logical_time)
        with self.database.unit_of_work() as uow:
            expired = uow.delete_expired_snapshots(
                logical_time.isoformat(),
                limit=self.batch_size,
            )
            social = self._prune_social(uow, logical_time)
            lottery = self._prune_lottery(uow, logical_time)
            activities = self._prune_activities(uow, logical_time)
            disasters = self._prune_disasters(uow)
            rest = self._prune_rest_windows(uow)
            uow.commit()
        return SnapshotLifecycleReceipt(
            expired,
            social,
            lottery,
            activities,
            disasters,
            rest,
        )

    def _prune_social(self, uow, logical_time: datetime) -> int:
        cutoff = logical_time - TERMINAL_STATE_RETENTION
        removed = 0
        states = tuple(
            self.snapshots.iter_all(uow, self.storage.social, SocialState)
        )
        for state in states:
            requests = {
                key: value
                for key, value in state.requests.items()
                if value.expires_at > cutoff
            }
            count = len(state.requests) - len(requests)
            if not count:
                continue
            current = replace(state, requests=requests, revision=state.revision + 1)
            self.snapshots.update(
                uow,
                self.storage.social,
                state.scope_id,
                state,
                current,
                logical_time,
            )
            removed += count
        return removed

    def _prune_lottery(self, uow, logical_time: datetime) -> int:
        removed = 0
        states = tuple(
            self.snapshots.iter_all(uow, LOTTERY_AGGREGATE, LotteryState)
        )
        for state in states:
            keep_ids = set(sorted(state.rounds, reverse=True)[:HISTORY_LIMIT])
            rounds = {key: value for key, value in state.rounds.items() if key in keep_ids}
            count = len(state.rounds) - len(rounds)
            if not count:
                continue
            current = replace(state, rounds=rounds, revision=state.revision + 1)
            self.snapshots.update(
                uow,
                LOTTERY_AGGREGATE,
                state.scope_id,
                state,
                current,
                logical_time,
            )
            removed += count
        return removed

    def _prune_activities(self, uow, logical_time: datetime) -> int:
        removed = 0
        states = tuple(
            self.snapshots.iter_all(uow, self.storage.activity, ActivityState)
        )
        terminal = {ActivityStatus.CLOSED, ActivityStatus.CANCELLED}
        for state in states:
            terminal_ids = {
                value.id
                for value in sorted(
                    (
                        value
                        for value in state.instances.values()
                        if value.status in terminal
                    ),
                    key=lambda value: (value.closes_at, value.id),
                    reverse=True,
                )[:HISTORY_LIMIT]
            }
            instances = {
                key: value
                for key, value in state.instances.items()
                if value.status not in terminal or key in terminal_ids
            }
            count = len(state.instances) - len(instances)
            if not count:
                continue
            current = replace(state, instances=instances, revision=state.revision + 1)
            self.snapshots.update(
                uow,
                self.storage.activity,
                state.scope_id,
                state,
                current,
                logical_time,
            )
            removed += count
        return removed

    def _prune_disasters(self, uow) -> int:
        states = tuple(
            self.snapshots.iter_all(
                uow,
                DIMENSIONAL_DISASTER_AGGREGATE,
                DimensionalDisasterState,
            )
        )
        terminal = sorted(
            (
                value
                for value in states
                if value.status is DimensionalDisasterStatus.CLOSED
            ),
            key=lambda value: (value.closes_at, value.event_id),
            reverse=True,
        )
        removed = 0
        for state in terminal[HISTORY_LIMIT:]:
            removed += int(
                self.snapshots.delete(
                    uow,
                    DIMENSIONAL_DISASTER_AGGREGATE,
                    state.event_id,
                    expected_revision=state.revision,
                )
            )
        return removed

    def _prune_rest_windows(self, uow) -> int:
        states = tuple(
            self.snapshots.iter_all(
                uow,
                REST_RECOVERY_AGGREGATE,
                RestRecoveryState,
            )
        )
        removed = 0
        for state in states:
            if state.accumulated_seconds != 0:
                continue
            action_state = self.snapshots.load(
                uow,
                self.storage.action,
                state.character_id,
                ActionState,
            )
            running_rest = bool(
                action_state
                and any(
                    action.definition_id == REST_ACTION_ID
                    for action in action_state.running(ActionSlotKind.MAIN)
                )
            )
            if running_rest:
                continue
            removed += int(
                self.snapshots.delete(
                    uow,
                    REST_RECOVERY_AGGREGATE,
                    state.character_id,
                    expected_revision=state.revision,
                )
            )
        return removed


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("快照生命周期时间必须包含时区")


__all__ = [
    "HISTORY_LIMIT",
    "SnapshotLifecycleReceipt",
    "SnapshotLifecycleService",
    "SnapshotLifecycleStorageKinds",
    "TERMINAL_STATE_RETENTION",
]
