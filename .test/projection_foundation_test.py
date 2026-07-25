"""永久事实、投影检查点、通知和不可变排名测试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay.projections import (  # noqa: E402
    PROJECTION_FOUNDATION_VERSION,
    NotificationAction,
    NotificationEntry,
    NotificationStatus,
    RankingCandidate,
    RankingDirection,
    RankingEngine,
)
from game.core.persistence import (  # noqa: E402
    ConcurrencyConflict,
    FactJournalService,
    NotificationInboxService,
    ProjectionStore,
    RankingSnapshotStore,
    SqliteDatabase,
    TransactionMismatch,
)


TIME = datetime(2026, 7, 14, 4, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
    assert PROJECTION_FOUNDATION_VERSION == "projection.foundation.v1"
    with TemporaryDirectory() as directory:
        database = SqliteDatabase(Path(directory) / "projection.db")
        database.initialize()
        _append_fact(database)
        _assert_fact_survives_outbox_publish(database)
        _assert_projection_checkpoint(database)
        _assert_notification_is_read_only_until_marked(database)
        _assert_ranking_snapshot(database)
    print("projection foundation tests passed")


def _append_fact(database: SqliteDatabase) -> None:
    with database.unit_of_work() as uow:
        uow.insert_transaction("fact-tx-1", "fingerprint-1", "account-a", "{}", TIME.isoformat())
        uow.append_fact(
            "fact-tx-1",
            0,
            "activity.contribution.recorded",
            '{"subject_id":"account-a","amount":25}',
            TIME.isoformat(),
        )
        uow.commit()


def _assert_fact_survives_outbox_publish(database: SqliteDatabase) -> None:
    facts = FactJournalService(database)
    first = facts.list()
    assert len(first) == 1 and first[0].offset == 1
    assert facts.list() == first
    assert facts.list(kinds=("activity.contribution.recorded",)) == first


def _assert_projection_checkpoint(database: SqliteDatabase) -> None:
    store = ProjectionStore(database)
    with database.unit_of_work() as uow:
        store.initialize_in_uow(
            uow,
            "projector.atomic_probe",
            "world",
            logical_time=TIME,
        )
        store.commit_in_uow(
            uow,
            "projector.atomic_probe",
            "world",
            expected_revision=0,
            through_fact_offset=1,
            updates={"account-a": {"value": 1}},
            logical_time=TIME,
        )
        assert store.record_in_uow(
            uow,
            "projector.atomic_probe",
            "world",
            "account-a",
        ) is not None
    assert store.checkpoint("projector.atomic_probe", "world") is None

    store.initialize("projector.player_stats", "world", logical_time=TIME)
    written = store.commit(
        "projector.player_stats",
        "world",
        expected_revision=0,
        through_fact_offset=1,
        updates={"account-a": {"contribution": 25}},
        logical_time=TIME,
    )
    assert written[0].payload["contribution"] == 25
    before_read = store.checkpoint("projector.player_stats", "world")
    assert store.records("projector.player_stats", "world") == written
    assert store.checkpoint("projector.player_stats", "world") == before_read == (1, 1)
    try:
        store.commit(
            "projector.player_stats",
            "world",
            expected_revision=0,
            through_fact_offset=1,
            updates={},
            logical_time=TIME,
        )
        raise AssertionError("旧投影 revision 必须冲突")
    except ConcurrencyConflict:
        pass
    reset_revision = store.reset(
        "projector.player_stats",
        "world",
        expected_revision=1,
        logical_time=TIME + timedelta(minutes=1),
    )
    assert reset_revision == 2
    assert store.checkpoint("projector.player_stats", "world") == (0, 2)
    assert not store.records("projector.player_stats", "world")
    rebuilt = store.commit(
        "projector.player_stats",
        "world",
        expected_revision=2,
        through_fact_offset=1,
        updates={"account-a": {"contribution": 25}},
        logical_time=TIME + timedelta(minutes=2),
    )
    assert rebuilt[0].payload["contribution"] == 25
    try:
        store.reset(
            "projector.player_stats",
            "world",
            expected_revision=1,
            logical_time=TIME + timedelta(minutes=3),
        )
        raise AssertionError("旧 revision 不能清空投影记录")
    except ConcurrencyConflict:
        pass
    assert store.records("projector.player_stats", "world") == rebuilt


def _assert_notification_is_read_only_until_marked(database: SqliteDatabase) -> None:
    inbox = NotificationInboxService(database)
    entry = NotificationEntry(
        "notice-1",
        "account-a",
        "notification.activity_reward",
        "activity-1:reward",
        100,
        1,
        TIME,
        TIME + timedelta(days=1),
        NotificationAction("notification_action.open_activity", {"activity_id": "activity-1"}),
        {"activity_id": "activity-1"},
    )
    assert inbox.issue(entry) == entry
    assert inbox.issue(entry) == entry
    try:
        inbox.issue(replace(entry, id="notice-conflict"))
        raise AssertionError("同一通知防重键不能对应不同内容")
    except TransactionMismatch:
        pass
    assert inbox.list_unread("account-a", logical_time=TIME) == (entry,)
    assert inbox.list_unread("account-a", logical_time=TIME) == (entry,)
    assert inbox.count_unread("account-a", logical_time=TIME) == 1
    assert inbox.count_unread("account-a", logical_time=TIME) == 1
    marked = inbox.mark(
        entry.id,
        NotificationStatus.READ,
        expected_revision=0,
        logical_time=TIME + timedelta(minutes=1),
    )
    assert marked.status is NotificationStatus.READ and marked.revision == 1
    assert not inbox.list_unread("account-a", logical_time=TIME + timedelta(minutes=1))
    assert inbox.count_unread("account-a", logical_time=TIME + timedelta(minutes=1)) == 0
    try:
        inbox.mark(
            entry.id,
            NotificationStatus.DISMISSED,
            expected_revision=0,
            logical_time=TIME + timedelta(minutes=2),
        )
        raise AssertionError("已处理通知不能再次写入")
    except ConcurrencyConflict:
        pass


def _assert_ranking_snapshot(database: SqliteDatabase) -> None:
    snapshot = RankingEngine().freeze(
        board_id="ranking.weekly_contribution",
        scope_id="world",
        period_id="2026-W29",
        version=1,
        direction=RankingDirection.DESCENDING,
        candidates=(
            RankingCandidate("account-b", 25, 2),
            RankingCandidate("account-a", 25, 1),
            RankingCandidate("account-c", 10, 1),
        ),
        frozen_at=TIME,
        through_fact_offset=1,
    )
    assert [entry.subject_id for entry in snapshot.entries] == [
        "account-a",
        "account-b",
        "account-c",
    ]
    store = RankingSnapshotStore(database)
    assert store.save(snapshot) == snapshot
    assert store.save(snapshot) == snapshot
    assert store.load(snapshot.board_id, "world", "2026-W29", 1) == snapshot
    conflicting = RankingEngine().freeze(
        board_id="ranking.weekly_contribution",
        scope_id="world",
        period_id="2026-W29",
        version=1,
        direction=RankingDirection.DESCENDING,
        candidates=(RankingCandidate("account-a", 999),),
        frozen_at=TIME,
        through_fact_offset=1,
    )
    try:
        store.save(conflicting)
        raise AssertionError("同一排名快照身份不能覆盖历史内容")
    except TransactionMismatch:
        pass
    try:
        store.save(
            RankingEngine().freeze(
                board_id="ranking.weekly_contribution",
                scope_id="world",
                period_id="2026-W30",
                version=1,
                direction=RankingDirection.DESCENDING,
                candidates=(RankingCandidate("account-a", 1),),
                frozen_at=TIME,
                through_fact_offset=2,
            )
        )
        raise AssertionError("排名快照不能引用不存在的事实")
    except ValueError:
        pass


if __name__ == "__main__":
    main()
