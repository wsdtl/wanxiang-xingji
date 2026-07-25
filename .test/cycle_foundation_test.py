"""时间周期规则、补偿游标、租约队列和重启恢复测试。"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay.cycles import (  # noqa: E402
    CYCLE_FOUNDATION_VERSION,
    CalendarSchedule,
    CalendarUnit,
    CatchUpPolicy,
    CycleDefinition,
    CycleEngine,
    ExplicitSchedule,
    ExplicitWindow,
    FixedIntervalSchedule,
)
from game.core.gameplay.registry import DefinitionRegistry  # noqa: E402
from game.core.persistence import (  # noqa: E402
    ConcurrencyConflict,
    CycleWorkStatus,
    PersistentCycleService,
    SqliteDatabase,
    cycle_transaction_id,
)


UTC = timezone.utc
SHANGHAI = ZoneInfo("Asia/Shanghai")
BASE = datetime(2026, 7, 1, tzinfo=UTC)


def main() -> None:
    assert CYCLE_FOUNDATION_VERSION == "cycle.foundation.v1"
    _assert_calendar_schedules()
    _assert_fixed_and_explicit_schedules()
    _assert_catch_up_policies()
    _assert_persistent_worker_lifecycle()
    print("cycle foundation tests passed")


def _engine(*definitions: CycleDefinition) -> CycleEngine:
    registry = DefinitionRegistry[CycleDefinition]("Cycle")
    for definition in definitions:
        registry.register(definition)
    return CycleEngine(registry)


def _assert_calendar_schedules() -> None:
    daily = _engine(
        CycleDefinition(
            "cycle.daily",
            CalendarSchedule("Asia/Shanghai", CalendarUnit.DAY, time(4)),
        )
    )
    before = daily.current_window(
        "cycle.daily",
        logical_time=datetime(2026, 7, 13, 3, 59, tzinfo=SHANGHAI),
    )
    after = daily.current_window(
        "cycle.daily",
        logical_time=datetime(2026, 7, 13, 4, 0, tzinfo=SHANGHAI),
    )
    assert before and after
    assert before.starts_at == datetime(2026, 7, 12, 4, tzinfo=SHANGHAI)
    assert after.starts_at == datetime(2026, 7, 13, 4, tzinfo=SHANGHAI)

    weekly = _engine(
        CycleDefinition(
            "cycle.weekly",
            CalendarSchedule("Asia/Shanghai", CalendarUnit.WEEK, time(4), 0),
        )
    ).current_window(
        "cycle.weekly",
        logical_time=datetime(2026, 7, 15, 12, tzinfo=SHANGHAI),
    )
    assert weekly and weekly.starts_at == datetime(2026, 7, 13, 4, tzinfo=SHANGHAI)

    monthly = _engine(
        CycleDefinition(
            "cycle.monthly",
            CalendarSchedule("Asia/Shanghai", CalendarUnit.MONTH, time(4)),
        )
    ).current_window(
        "cycle.monthly",
        logical_time=datetime(2026, 7, 31, 20, tzinfo=SHANGHAI),
    )
    assert monthly
    assert monthly.starts_at == datetime(2026, 7, 1, 4, tzinfo=SHANGHAI)
    assert monthly.ends_at == datetime(2026, 8, 1, 4, tzinfo=SHANGHAI)

    new_york = ZoneInfo("America/New_York")
    dst_window = _engine(
        CycleDefinition(
            "cycle.dst",
            CalendarSchedule("America/New_York", CalendarUnit.DAY),
        )
    ).current_window(
        "cycle.dst",
        logical_time=datetime(2026, 3, 8, 12, tzinfo=new_york),
    )
    assert dst_window
    assert (
        dst_window.ends_at.astimezone(UTC) - dst_window.starts_at.astimezone(UTC)
        == timedelta(hours=23)
    )


def _assert_fixed_and_explicit_schedules() -> None:
    fixed = _engine(
        CycleDefinition(
            "cycle.fixed",
            FixedIntervalSchedule(BASE, timedelta(hours=2), timedelta(hours=1)),
            settlement_delay=timedelta(minutes=30),
        )
    )
    active = fixed.current_window(
        "cycle.fixed", logical_time=BASE + timedelta(minutes=30)
    )
    gap = fixed.current_window(
        "cycle.fixed", logical_time=BASE + timedelta(hours=1, minutes=30)
    )
    assert active and active.settlement_available_at == BASE + timedelta(hours=1, minutes=30)
    assert gap is None
    delayed = fixed.discover(
        "cycle.fixed",
        scanned_from=BASE,
        through=BASE + timedelta(hours=1, minutes=29),
    )
    assert delayed.windows == ()

    season = ExplicitSchedule(
        (
            ExplicitWindow("spring", BASE, BASE + timedelta(days=10)),
            ExplicitWindow(
                "summer", BASE + timedelta(days=20), BASE + timedelta(days=30)
            ),
        )
    )
    explicit = _engine(CycleDefinition("cycle.season", season))
    assert explicit.current_window(
        "cycle.season", logical_time=BASE + timedelta(days=15)
    ) is None
    discovery = explicit.discover(
        "cycle.season",
        scanned_from=BASE,
        through=BASE + timedelta(days=31),
    )
    assert tuple(value.instance_id for value in discovery.windows) == (
        "cycle.season@spring",
        "cycle.season@summer",
    )


def _assert_catch_up_policies() -> None:
    schedule = FixedIntervalSchedule(BASE, timedelta(hours=1))
    all_engine = _engine(
        CycleDefinition(
            "cycle.all",
            schedule,
            maximum_backfill_per_scan=2,
        )
    )
    first = all_engine.discover(
        "cycle.all", scanned_from=BASE, through=BASE + timedelta(hours=5)
    )
    assert first.truncated and len(first.windows) == 2
    assert first.advanced_through == BASE + timedelta(hours=2)
    second = all_engine.discover(
        "cycle.all",
        scanned_from=first.advanced_through,
        through=BASE + timedelta(hours=5),
    )
    assert tuple(value.ends_at.hour for value in second.windows) == (3, 4)

    latest = _engine(
        CycleDefinition("cycle.latest", schedule, catch_up=CatchUpPolicy.LATEST)
    ).discover(
        "cycle.latest", scanned_from=BASE, through=BASE + timedelta(hours=5)
    )
    assert len(latest.windows) == 1 and latest.windows[0].ends_at.hour == 5
    assert latest.advanced_through == BASE + timedelta(hours=5)

    discarded = _engine(
        CycleDefinition("cycle.discard", schedule, catch_up=CatchUpPolicy.DISCARD)
    ).discover(
        "cycle.discard", scanned_from=BASE, through=BASE + timedelta(hours=5)
    )
    assert discarded.windows == ()
    assert discarded.advanced_through == BASE + timedelta(hours=5)


def _assert_persistent_worker_lifecycle() -> None:
    engine = _engine(
        CycleDefinition(
            "cycle.hourly",
            FixedIntervalSchedule(BASE, timedelta(hours=1)),
            maximum_backfill_per_scan=2,
        )
    )
    with TemporaryDirectory() as directory:
        path = Path(directory) / "cycle.db"
        database = SqliteDatabase(path)
        database.initialize()
        service = PersistentCycleService(database, engine)
        cursor = service.initialize_cursor(
            "world.main",
            "cycle.hourly",
            scanned_from=BASE.astimezone(SHANGHAI),
            logical_time=BASE.astimezone(SHANGHAI),
        )
        assert cursor.scanned_through == BASE and cursor.scanned_through.tzinfo is UTC

        first = service.discover(
            "world.main",
            "cycle.hourly",
            through=BASE + timedelta(hours=5),
        )
        assert first.truncated and len(first.windows) == 2
        restarted = PersistentCycleService(SqliteDatabase(path), engine)
        assert restarted.load_cursor("world.main", "cycle.hourly").scanned_through == (
            BASE + timedelta(hours=2)
        )
        restarted.discover(
            "world.main", "cycle.hourly", through=BASE + timedelta(hours=5)
        )
        restarted.discover(
            "world.main", "cycle.hourly", through=BASE + timedelta(hours=5)
        )
        assert restarted.load_cursor("world.main", "cycle.hourly").scanned_through == (
            BASE + timedelta(hours=5)
        )
        try:
            restarted.discover(
                "world.main",
                "cycle.hourly",
                through=BASE + timedelta(hours=4),
            )
            raise AssertionError("周期扫描逻辑时间不能倒退")
        except ValueError:
            pass

        claimed = restarted.claim(
            "worker.a",
            logical_time=BASE + timedelta(hours=5),
            lease_duration=timedelta(minutes=10),
        )
        assert claimed and claimed.status is CycleWorkStatus.RUNNING
        assert claimed.attempt_count == 1
        assert claimed.transaction_id == cycle_transaction_id(
            "world.main", "cycle.hourly", claimed.instance_id
        )
        assert restarted.claim(
            "worker.b",
            logical_time=BASE + timedelta(hours=5, minutes=5),
            lease_duration=timedelta(minutes=10),
            cycle_id="cycle.hourly",
        ).transaction_id != claimed.transaction_id

        taken_over = restarted.claim(
            "worker.b",
            logical_time=BASE + timedelta(hours=5, minutes=11),
            lease_duration=timedelta(minutes=10),
            cycle_id="cycle.hourly",
        )
        assert taken_over and taken_over.transaction_id == claimed.transaction_id
        assert taken_over.attempt_count == 2 and taken_over.lease_owner == "worker.b"
        try:
            restarted.complete(
                claimed.transaction_id,
                "worker.a",
                logical_time=BASE + timedelta(hours=5, minutes=12),
            )
            raise AssertionError("租约被接管后原 worker 不能完成工作")
        except ConcurrencyConflict:
            pass
        try:
            restarted.heartbeat(
                taken_over.transaction_id,
                "worker.b",
                logical_time=BASE + timedelta(hours=5, minutes=12),
                lease_duration=timedelta(minutes=1),
            )
            raise AssertionError("心跳不能缩短现有租约")
        except ConcurrencyConflict:
            pass
        heartbeat = restarted.heartbeat(
            taken_over.transaction_id,
            "worker.b",
            logical_time=BASE + timedelta(hours=5, minutes=12),
            lease_duration=timedelta(minutes=20),
        )
        assert heartbeat.lease_until == BASE + timedelta(hours=5, minutes=32)
        completed = restarted.complete(
            heartbeat.transaction_id,
            "worker.b",
            logical_time=BASE + timedelta(hours=5, minutes=13),
        )
        assert completed.status is CycleWorkStatus.COMPLETED
        try:
            restarted.complete(
                heartbeat.transaction_id,
                "worker.b",
                logical_time=BASE + timedelta(hours=5, minutes=14),
            )
            raise AssertionError("完成后的工作项不能再次完成")
        except ConcurrencyConflict:
            pass

        retry_item = restarted.claim(
            "worker.retry",
            logical_time=BASE + timedelta(hours=6),
            lease_duration=timedelta(minutes=10),
        )
        assert retry_item
        restarted.retry(
            retry_item.transaction_id,
            "worker.retry",
            retry_at=BASE + timedelta(hours=7),
            logical_time=BASE + timedelta(hours=6, minutes=1),
            error="暂时失败",
        )
        before_retry = restarted.claim(
            "worker.retry",
            logical_time=BASE + timedelta(hours=6, minutes=59),
            lease_duration=timedelta(minutes=10),
        )
        assert before_retry is None or before_retry.transaction_id != retry_item.transaction_id
        if before_retry is not None:
            restarted.complete(
                before_retry.transaction_id,
                "worker.retry",
                logical_time=BASE + timedelta(hours=6, minutes=59, seconds=1),
            )
        at_retry = _claim_until(
            restarted,
            retry_item.transaction_id,
            worker_id="worker.retry",
            logical_time=BASE + timedelta(hours=7),
        )
        failed = restarted.fail(
            at_retry.transaction_id,
            "worker.retry",
            logical_time=BASE + timedelta(hours=7, minutes=1),
            error="永久失败",
        )
        assert failed.status is CycleWorkStatus.FAILED
        restarted.requeue_failed(
            failed.transaction_id,
            retry_at=BASE + timedelta(hours=8),
            logical_time=BASE + timedelta(hours=7, minutes=2),
        )
        requeued = _claim_until(
            restarted,
            failed.transaction_id,
            worker_id="worker.final",
            logical_time=BASE + timedelta(hours=8),
        )
        assert requeued and requeued.transaction_id == failed.transaction_id

        raw = sqlite3.connect(path)
        try:
            stored = raw.execute(
                "SELECT scanned_through FROM cycle_cursor WHERE scope_id = ?",
                ("world.main",),
            ).fetchone()[0]
            assert stored.endswith("+00:00")
        finally:
            raw.close()


def _claim_until(
    service: PersistentCycleService,
    transaction_id: str,
    *,
    worker_id: str,
    logical_time: datetime,
):
    """按队列顺序完成更早工作，直到取得测试目标。"""

    for index in range(10):
        claimed = service.claim(
            worker_id,
            logical_time=logical_time + timedelta(seconds=index * 2),
            lease_duration=timedelta(minutes=10),
        )
        assert claimed is not None
        if claimed.transaction_id == transaction_id:
            return claimed
        service.complete(
            claimed.transaction_id,
            worker_id,
            logical_time=logical_time + timedelta(seconds=index * 2 + 1),
        )
    raise AssertionError(f"未能领取目标周期工作项：{transaction_id}")


if __name__ == "__main__":
    main()
