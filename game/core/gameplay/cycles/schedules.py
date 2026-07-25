"""周期调度处理器与日历、固定间隔、显式窗口实现。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import floor
from typing import Callable
from zoneinfo import ZoneInfo

from .models import CalendarSchedule, CalendarUnit, ExplicitSchedule, FixedIntervalSchedule


@dataclass(frozen=True)
class ScheduledWindow:
    key: str
    starts_at: datetime
    ends_at: datetime


WindowRangeHandler = Callable[
    [object, datetime, datetime, int],
    tuple[ScheduledWindow, ...],
]
LatestWindowHandler = Callable[[object, datetime], ScheduledWindow | None]
ContainingWindowHandler = Callable[[object, datetime], ScheduledWindow | None]


@dataclass(frozen=True)
class ScheduleHandlerRegistration:
    schedule_type: type[object]
    ending_between: WindowRangeHandler
    latest_ending_at_or_before: LatestWindowHandler
    containing: ContainingWindowHandler
    implementation_version: int = 1

    def __post_init__(self) -> None:
        if (
            isinstance(self.implementation_version, bool)
            or not isinstance(self.implementation_version, int)
            or self.implementation_version < 1
        ):
            raise ValueError("周期调度实现版本必须是大于 0 的整数")


class CycleScheduleHandlers:
    """按调度声明类型分派，不把日历判断写进周期引擎。"""

    def __init__(self) -> None:
        self._range_handlers: dict[type[object], WindowRangeHandler] = {}
        self._latest_handlers: dict[type[object], LatestWindowHandler] = {}
        self._containing_handlers: dict[type[object], ContainingWindowHandler] = {}
        self._frozen = False

    @classmethod
    def with_defaults(cls) -> "CycleScheduleHandlers":
        handlers = cls()
        handlers.register(FixedIntervalSchedule, _fixed_between, _fixed_latest, _fixed_containing)
        handlers.register(CalendarSchedule, _calendar_between, _calendar_latest, _calendar_containing)
        handlers.register(ExplicitSchedule, _explicit_between, _explicit_latest, _explicit_containing)
        return handlers

    def register(
        self,
        schedule_type: type[object],
        ending_between: WindowRangeHandler,
        latest_ending_at_or_before: LatestWindowHandler,
        containing: ContainingWindowHandler,
    ) -> None:
        if self._frozen:
            raise RuntimeError("周期调度处理器已经冻结")
        if schedule_type in self._range_handlers:
            raise ValueError(f"周期调度处理器重复：{schedule_type.__name__}")
        self._range_handlers[schedule_type] = ending_between
        self._latest_handlers[schedule_type] = latest_ending_at_or_before
        self._containing_handlers[schedule_type] = containing

    def ending_between(
        self,
        schedule: object,
        after: datetime,
        through: datetime,
        limit: int,
    ) -> tuple[ScheduledWindow, ...]:
        if limit < 1:
            raise ValueError("周期窗口查询 limit 必须大于 0")
        try:
            handler = self._range_handlers[type(schedule)]
        except KeyError as exc:
            raise TypeError(f"未登记周期调度类型：{type(schedule).__name__}") from exc
        return handler(schedule, after, through, limit)

    def latest_ending_at_or_before(
        self,
        schedule: object,
        through: datetime,
    ) -> ScheduledWindow | None:
        try:
            handler = self._latest_handlers[type(schedule)]
        except KeyError as exc:
            raise TypeError(f"未登记周期调度类型：{type(schedule).__name__}") from exc
        return handler(schedule, through)

    def validate_schedule(self, schedule: object) -> None:
        if type(schedule) not in self._range_handlers:
            raise TypeError(f"未登记周期调度类型：{type(schedule).__name__}")

    def containing(self, schedule: object, at: datetime) -> ScheduledWindow | None:
        try:
            handler = self._containing_handlers[type(schedule)]
        except KeyError as exc:
            raise TypeError(f"未登记周期调度类型：{type(schedule).__name__}") from exc
        return handler(schedule, at)

    def freeze(self) -> None:
        if not self._range_handlers:
            raise ValueError("周期调度处理器不能为空")
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen


def _fixed_between(schedule, after, through, limit):
    duration = schedule.active_duration
    assert duration is not None
    interval_seconds = schedule.interval.total_seconds()
    offset = (after - schedule.anchor_at - duration).total_seconds()
    index = max(0, floor(offset / interval_seconds) + 1)
    result: list[ScheduledWindow] = []
    while len(result) < limit:
        starts_at = schedule.anchor_at + schedule.interval * index
        ends_at = starts_at + duration
        if ends_at > through:
            break
        if ends_at > after:
            result.append(ScheduledWindow(f"{index:012d}", starts_at, ends_at))
        index += 1
    return tuple(result)


def _fixed_latest(schedule, through):
    duration = schedule.active_duration
    assert duration is not None
    offset = (through - schedule.anchor_at - duration).total_seconds()
    index = floor(offset / schedule.interval.total_seconds())
    if index < 0:
        return None
    starts_at = schedule.anchor_at + schedule.interval * index
    return ScheduledWindow(f"{index:012d}", starts_at, starts_at + duration)


def _fixed_containing(schedule, at):
    if at < schedule.anchor_at:
        return None
    index = floor((at - schedule.anchor_at).total_seconds() / schedule.interval.total_seconds())
    starts_at = schedule.anchor_at + schedule.interval * index
    ends_at = starts_at + schedule.active_duration
    if not starts_at <= at < ends_at:
        return None
    return ScheduledWindow(f"{index:012d}", starts_at, ends_at)


def _calendar_between(schedule, after, through, limit):
    current = _calendar_window_at(schedule, after)
    result: list[ScheduledWindow] = []
    while len(result) < limit and current.ends_at <= through:
        if current.ends_at > after:
            result.append(current)
        current = _calendar_next(schedule, current)
    return tuple(result)


def _calendar_latest(schedule, through):
    current = _calendar_window_at(schedule, through)
    return _calendar_previous(schedule, current)


def _calendar_containing(schedule, at):
    return _calendar_window_at(schedule, at)


def _calendar_window_at(schedule: CalendarSchedule, moment: datetime) -> ScheduledWindow:
    zone = ZoneInfo(schedule.timezone)
    local = moment.astimezone(zone)
    boundary_delta = timedelta(
        hours=schedule.boundary.hour,
        minutes=schedule.boundary.minute,
        seconds=schedule.boundary.second,
        microseconds=schedule.boundary.microsecond,
    )
    business_date = (local - boundary_delta).date()
    if schedule.unit is CalendarUnit.DAY:
        start_date = business_date
    elif schedule.unit is CalendarUnit.WEEK:
        start_date = business_date - timedelta(
            days=(business_date.weekday() - schedule.week_start) % 7
        )
    else:
        start_date = date(business_date.year, business_date.month, 1)
    starts_at = datetime.combine(start_date, schedule.boundary, zone)
    ends_at = _next_boundary(schedule, start_date, zone)
    return ScheduledWindow(_calendar_key(schedule.unit, start_date), starts_at, ends_at)


def _calendar_next(schedule: CalendarSchedule, window: ScheduledWindow) -> ScheduledWindow:
    return _calendar_window_at(schedule, window.ends_at)


def _calendar_previous(schedule: CalendarSchedule, window: ScheduledWindow) -> ScheduledWindow:
    return _calendar_window_at(schedule, window.starts_at - timedelta(microseconds=1))


def _next_boundary(schedule: CalendarSchedule, start_date: date, zone: ZoneInfo) -> datetime:
    if schedule.unit is CalendarUnit.DAY:
        next_date = start_date + timedelta(days=1)
    elif schedule.unit is CalendarUnit.WEEK:
        next_date = start_date + timedelta(days=7)
    elif start_date.month == 12:
        next_date = date(start_date.year + 1, 1, 1)
    else:
        next_date = date(start_date.year, start_date.month + 1, 1)
    return datetime.combine(next_date, schedule.boundary, zone)


def _calendar_key(unit: CalendarUnit, start_date: date) -> str:
    if unit is CalendarUnit.MONTH:
        return start_date.strftime("%Y%m")
    return start_date.strftime("%Y%m%d")


def _explicit_between(schedule, after, through, limit):
    return tuple(
        ScheduledWindow(value.key, value.starts_at, value.ends_at)
        for value in schedule.windows
        if after < value.ends_at <= through
    )[:limit]


def _explicit_latest(schedule, through):
    values = [value for value in schedule.windows if value.ends_at <= through]
    if not values:
        return None
    value = values[-1]
    return ScheduledWindow(value.key, value.starts_at, value.ends_at)


def _explicit_containing(schedule, at):
    for value in schedule.windows:
        if value.starts_at <= at < value.ends_at:
            return ScheduledWindow(value.key, value.starts_at, value.ends_at)
    return None


__all__ = [
    "CycleScheduleHandlers",
    "ScheduleHandlerRegistration",
    "ScheduledWindow",
]
