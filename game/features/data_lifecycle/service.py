"""以登记表方式运行各领域自己的短期数据清理器。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from game.core.gameplay import StableId, stable_id


CleanupHandler = Callable[[datetime], object]


@dataclass(frozen=True)
class DataLifecycleTask:
    id: StableId
    handler: CleanupHandler

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", stable_id(self.id, field="数据清理任务 ID"))
        if not callable(self.handler):
            raise TypeError("数据清理任务必须提供可调用处理器")


@dataclass(frozen=True)
class DataLifecycleResult:
    task_id: StableId
    value: object | None = None
    error: Exception | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class DataLifecycleFeature:
    """冻结清理任务目录，逐项执行并隔离单项失败。"""

    def __init__(self, tasks: tuple[DataLifecycleTask, ...] = ()) -> None:
        values = tuple(tasks)
        ids = tuple(value.id for value in values)
        if len(ids) != len(set(ids)):
            raise ValueError("数据清理任务 ID 不能重复")
        self.tasks = tuple(sorted(values, key=lambda value: value.id))

    def maintain(self, *, logical_time: datetime) -> tuple[DataLifecycleResult, ...]:
        if logical_time.tzinfo is None or logical_time.utcoffset() is None:
            raise ValueError("数据清理时间必须包含时区")
        return tuple(
            self._run(task, logical_time)
            for task in self.tasks
        )

    @staticmethod
    def _run(task: DataLifecycleTask, logical_time: datetime) -> DataLifecycleResult:
        try:
            return DataLifecycleResult(task.id, task.handler(logical_time))
        except Exception as exc:  # isolate one optional cleanup from the rest
            return DataLifecycleResult(task.id, error=exc)


__all__ = ["DataLifecycleFeature", "DataLifecycleResult", "DataLifecycleTask"]
