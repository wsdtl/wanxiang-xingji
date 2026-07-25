"""活动生命周期、参与限制、贡献和冻结排名测试。"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay import RuleContext, Ruleset, SeededRandomSource  # noqa: E402
from game.core.gameplay.activities import (  # noqa: E402
    ACTIVITY_FOUNDATION_VERSION,
    ActivityCatalog,
    ActivityCommand,
    ActivityDefinition,
    ActivityEngine,
    ActivityInstance,
    ActivityState,
    ActivityStatus,
    CloseActivity,
    CreateActivity,
    FinalizeActivity,
    JoinActivity,
    OpenActivity,
    RecordActivityContribution,
)


TIME = datetime(2026, 7, 14, 2, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
    assert ACTIVITY_FOUNDATION_VERSION == "activity.foundation.v1"
    engine = _engine()
    state = ActivityState("activity-world")
    instance = ActivityInstance(
        "activity-1",
        "activity.world_event",
        1,
        TIME + timedelta(minutes=5),
        TIME + timedelta(hours=1),
    )
    state = _run(
        engine,
        state,
        ActivityCommand("activity-create", "system", 0, CreateActivity(instance)),
        TIME,
    ).state
    too_early = engine.execute(
        ActivityCommand("activity-open-early", "system", 1, OpenActivity(instance.id)),
        state=state,
        context=_context("activity-open-early", TIME),
    )
    assert too_early.failure and too_early.failure.code == "activity.outside_open_window"

    opened_at = TIME + timedelta(minutes=5)
    state = _run(
        engine,
        state,
        ActivityCommand("activity-open", "system", 1, OpenActivity(instance.id)),
        opened_at,
    ).state
    state = _run(
        engine,
        state,
        ActivityCommand("join-b", "player-b", 2, JoinActivity(instance.id, "player-b")),
        opened_at,
    ).state
    state = _run(
        engine,
        state,
        ActivityCommand("join-a", "player-a", 3, JoinActivity(instance.id, "player-a")),
        opened_at + timedelta(seconds=1),
    ).state
    for index, (subject, amount) in enumerate(
        (("player-a", 20), ("player-b", 20), ("player-a", 5)),
        4,
    ):
        state = _run(
            engine,
            state,
            ActivityCommand(
                f"contribution-{index}",
                subject,
                index,
                RecordActivityContribution(instance.id, subject, amount),
            ),
            opened_at + timedelta(minutes=index),
        ).state
    limit = engine.execute(
        ActivityCommand(
            "contribution-limit",
            "player-a",
            7,
            RecordActivityContribution(instance.id, "player-a", 1),
        ),
        state=state,
        context=_context("contribution-limit", opened_at + timedelta(minutes=8)),
    )
    assert limit.failure and limit.failure.code == "activity.attempt_limit"

    closed = _run(
        engine,
        state,
        ActivityCommand("activity-close", "system", 7, CloseActivity(instance.id)),
        instance.closes_at,
    )
    assert closed.instance.status is ActivityStatus.SETTLING
    assert [entry.subject_id for entry in closed.instance.ranking] == ["player-a", "player-b"]
    assert [entry.contribution for entry in closed.instance.ranking] == [25, 20]
    finalized = _run(
        engine,
        closed.state,
        ActivityCommand("activity-finalize", "system", 8, FinalizeActivity(instance.id)),
        instance.closes_at,
    )
    assert finalized.instance.status is ActivityStatus.CLOSED
    print("activity foundation tests passed")


def _engine() -> ActivityEngine:
    catalog = ActivityCatalog()
    catalog.register(
        ActivityDefinition(
            "activity.world_event",
            1,
            capacity=10,
            maximum_attempts_per_participant=2,
            minimum_rank_contribution=1,
        )
    )
    catalog.finalize()
    return ActivityEngine(catalog)


def _context(trace: str, at: datetime) -> RuleContext:
    return RuleContext(
        trace,
        "rules.activity_v1",
        Ruleset("ruleset.activity_test"),
        at,
        SeededRandomSource(trace),
    )


def _run(engine, state, command, at):
    outcome = engine.execute(command, state=state, context=_context(command.id, at))
    assert outcome.ok and outcome.value, outcome.failure
    return outcome.value


if __name__ == "__main__":
    main()
