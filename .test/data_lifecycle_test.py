"""短期数据清理和任务隔离测试。"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay import (  # noqa: E402
    ActivityInstance,
    ActivityState,
    ActivityStatus,
    SocialRequest,
    SocialRequestStatus,
    SocialState,
)
from game.core.persistence import (  # noqa: E402
    ACTION_AGGREGATE,
    ACTIVITY_AGGREGATE,
    SOCIAL_AGGREGATE,
    PersistenceRetentionService,
    SnapshotRepository,
    SqliteDatabase,
    gameplay_snapshot_codec,
)
from game.features.data_lifecycle import (  # noqa: E402
    DataLifecycleFeature,
    DataLifecycleTask,
    SnapshotLifecycleService,
    SnapshotLifecycleStorageKinds,
)
from game.features.lottery.service import LOTTERY_AGGREGATE  # noqa: E402
from game.features.catalog import feature_snapshot_codec_registrations  # noqa: E402
from game.rules.disaster import (  # noqa: E402
    DIMENSIONAL_DISASTER_AGGREGATE,
    DimensionalDisasterOutcome,
    DimensionalDisasterState,
    DimensionalDisasterStatus,
    DisasterCombatSnapshot,
    DisasterNarrativeSnapshot,
)
from game.rules.lottery import LotteryRound, LotteryState  # noqa: E402
from game.rules.rest import REST_RECOVERY_AGGREGATE, RestRecoveryState  # noqa: E402


TIME = datetime(2026, 7, 25, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
    _assert_snapshot_lifecycle()
    with TemporaryDirectory() as directory:
        database = SqliteDatabase(Path(directory) / "lifecycle.db")
        database.initialize()
        with database.unit_of_work() as uow:
            uow.insert_transaction(
                "lifecycle-fact",
                "lifecycle-fingerprint",
                "scope",
                "{}",
                TIME.isoformat(),
            )
            uow.append_fact(
                "lifecycle-fact",
                0,
                "test.lifecycle.fact",
                "{}",
                TIME.isoformat(),
            )
            uow.enqueue_outbox(
                "lifecycle-fact",
                0,
                "test.lifecycle.delivery",
                "{}",
                TIME.isoformat(),
            )
            uow.commit()
        with database.unit_of_work() as uow:
            uow.mark_outbox_published(
                "lifecycle-fact",
                0,
                (TIME + timedelta(minutes=1)).isoformat(),
            )
            uow.commit()

        persistence = PersistenceRetentionService(
            database,
            fact_retention=timedelta(hours=1),
            published_delivery_retention=timedelta(hours=1),
        )
        receipt = persistence.cleanup(logical_time=TIME + timedelta(hours=2))
        assert receipt.facts == 1 and receipt.published_deliveries == 1

    calls: list[str] = []

    def good(logical_time: datetime) -> str:
        calls.append(logical_time.isoformat())
        return "ok"

    def bad(_logical_time: datetime) -> None:
        raise RuntimeError("isolated")

    feature = DataLifecycleFeature(
        (
            DataLifecycleTask("task.good", good),
            DataLifecycleTask("task.bad", bad),
        )
    )
    results = feature.maintain(logical_time=TIME)
    assert [value.task_id for value in results] == ["task.bad", "task.good"]
    assert results[0].error is not None and not results[0].ok
    assert results[1].value == "ok" and results[1].ok
    assert calls == [TIME.isoformat()]
    print("data lifecycle tests passed")


def _assert_snapshot_lifecycle() -> None:
    with TemporaryDirectory() as directory:
        database = SqliteDatabase(Path(directory) / "snapshot-lifecycle.db")
        database.initialize()
        snapshots = SnapshotRepository(
            gameplay_snapshot_codec(feature_snapshot_codec_registrations())
        )
        old_request = SocialRequest(
            "request-old",
            "social_request.test",
            "sender-old",
            "recipient-old",
            TIME - timedelta(hours=26),
            TIME - timedelta(hours=25),
            SocialRequestStatus.REJECTED,
        )
        recent_request = SocialRequest(
            "request-recent",
            "social_request.test",
            "sender-recent",
            "recipient-recent",
            TIME - timedelta(hours=2),
            TIME - timedelta(hours=1),
            SocialRequestStatus.REJECTED,
        )
        social = SocialState(
            "social.lifecycle",
            requests={old_request.id: old_request, recent_request.id: recent_request},
            revision=1,
        )
        lottery_rounds = {
            f"round-{index:03d}": LotteryRound(f"round-{index:03d}", status="opened")
            for index in range(52)
        }
        lottery = LotteryState("lottery.lifecycle", lottery_rounds)
        activity_instances = {}
        for index in range(52):
            opens_at = TIME - timedelta(days=53 - index)
            instance = ActivityInstance(
                f"activity-{index:03d}",
                "activity.lifecycle",
                1,
                opens_at,
                opens_at + timedelta(hours=1),
                ActivityStatus.CLOSED,
            )
            activity_instances[instance.id] = instance
        activities = ActivityState("activity.lifecycle", activity_instances)
        narrative = DisasterNarrativeSnapshot(
            "测试灾厄",
            "测试标题",
            "测试场景",
            "测试故事",
            "测试告别",
            "测试遗羽",
            "测试来源",
        )

        with database.unit_of_work() as uow:
            snapshots.insert(
                uow,
                "snapshot.lifecycle.expired",
                "expired-row",
                RestRecoveryState("expired-row", 1, 1, 1, 1),
                TIME - timedelta(days=1),
                expires_at=TIME - timedelta(seconds=1),
            )
            snapshots.insert(uow, SOCIAL_AGGREGATE, social.scope_id, social, TIME)
            snapshots.insert(uow, LOTTERY_AGGREGATE, lottery.scope_id, lottery, TIME)
            snapshots.insert(
                uow,
                ACTIVITY_AGGREGATE,
                activities.scope_id,
                activities,
                TIME,
            )
            for index in range(52):
                opens_at = TIME - timedelta(days=53 - index)
                event = DimensionalDisasterState(
                    f"disaster-{index:03d}",
                    f"window-{index:03d}",
                    "disaster.lifecycle",
                    "world.lifecycle",
                    narrative,
                    DisasterCombatSnapshot(
                        "enemy.lifecycle",
                        1,
                        "enemy_rank.lifecycle",
                        (),
                        f"seed-{index:03d}",
                        "content.lifecycle.v1",
                    ),
                    opens_at,
                    opens_at + timedelta(hours=1),
                    1,
                    1,
                    outcome=DimensionalDisasterOutcome.ESCAPED,
                    status=DimensionalDisasterStatus.CLOSED,
                )
                snapshots.insert(
                    uow,
                    DIMENSIONAL_DISASTER_AGGREGATE,
                    event.event_id,
                    event,
                    TIME,
                )
            for index in range(1_001):
                character_id = f"rest-{index:04d}"
                snapshots.insert(
                    uow,
                    REST_RECOVERY_AGGREGATE,
                    character_id,
                    RestRecoveryState(character_id, 1, 1, 1, 1),
                    TIME,
                )
            uow.commit()

        lifecycle = SnapshotLifecycleService(
            database,
            snapshots,
            SnapshotLifecycleStorageKinds(
                ACTION_AGGREGATE,
                ACTIVITY_AGGREGATE,
                SOCIAL_AGGREGATE,
            ),
        )
        receipt = lifecycle.cleanup(logical_time=TIME)
        assert receipt.expired_snapshots == 1
        assert receipt.social_requests == 1
        assert receipt.lottery_rounds == 32
        assert receipt.activity_instances == 32
        assert receipt.disaster_events == 32
        assert receipt.rest_windows == 1_001

        with database.unit_of_work(write=False) as uow:
            assert snapshots.load(
                uow,
                "snapshot.lifecycle.expired",
                "expired-row",
                RestRecoveryState,
            ) is None
            current_social = snapshots.require(
                uow,
                SOCIAL_AGGREGATE,
                social.scope_id,
                SocialState,
            )
            current_lottery = snapshots.require(
                uow,
                LOTTERY_AGGREGATE,
                lottery.scope_id,
                LotteryState,
            )
            current_activities = snapshots.require(
                uow,
                ACTIVITY_AGGREGATE,
                activities.scope_id,
                ActivityState,
            )
            disasters = tuple(
                snapshots.iter_all(
                    uow,
                    DIMENSIONAL_DISASTER_AGGREGATE,
                    DimensionalDisasterState,
                )
            )
            rests = tuple(
                snapshots.iter_all(
                    uow,
                    REST_RECOVERY_AGGREGATE,
                    RestRecoveryState,
                )
            )
        assert set(current_social.requests) == {recent_request.id}
        assert len(current_lottery.rounds) == 20
        assert len(current_activities.instances) == 20
        assert len(disasters) == 20
        assert not rests

        repeated = lifecycle.cleanup(logical_time=TIME)
        assert repeated == type(repeated)()


if __name__ == "__main__":
    main()
