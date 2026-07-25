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

from game.core.persistence import PersistenceRetentionService, SqliteDatabase  # noqa: E402
from game.features.data_lifecycle import DataLifecycleFeature, DataLifecycleTask  # noqa: E402


TIME = datetime(2026, 7, 25, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
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


if __name__ == "__main__":
    main()
