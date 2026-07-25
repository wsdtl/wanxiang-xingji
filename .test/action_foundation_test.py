"""异步行动定义、槽位、生命周期和快照持久化测试。"""

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
    ACTION_FOUNDATION_VERSION,
    ActionCatalog,
    ActionDefinition,
    ActionEngine,
    ActionResult,
    ActionSlotKind,
    ActionSnapshot,
    ActionState,
    ActionTransaction,
    CancelAction,
    ClaimAction,
    CompleteAction,
    InterruptAction,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    StartAction,
)
from game.core.persistence import (  # noqa: E402
    ACTION_AGGREGATE,
    SnapshotRepository,
    SqliteDatabase,
)


TIME = datetime(2026, 7, 13, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
    assert ACTION_FOUNDATION_VERSION == "action.foundation.v1"
    catalog = ActionCatalog()
    catalog.register(ActionDefinition("action.explore", ActionSlotKind.MAIN, timedelta(minutes=10)))
    catalog.register(ActionDefinition("action.rest", ActionSlotKind.MAIN, timedelta(minutes=5)))
    catalog.register(ActionDefinition("action.trade", ActionSlotKind.COMMISSION, timedelta(minutes=20)))
    catalog.register(ActionDefinition("action.inspect", ActionSlotKind.INSTANT, timedelta(0)))
    catalog.finalize()
    engine = ActionEngine(catalog, commission_slots=1)

    state = ActionState("player-1")
    started = _success(
        engine,
        state,
        ActionTransaction(
            "tx-start",
            state.owner_id,
            state.revision,
            (StartAction("run-1", "action.explore", _snapshot(TIME)),),
        ),
        TIME,
    )
    assert started.state.next_sequence == 2
    assert started.state.running(ActionSlotKind.MAIN)[0].id == "run-1"
    assert started.events[0].kind == "action.started"

    conflict = engine.execute(
        ActionTransaction(
            "tx-conflict",
            state.owner_id,
            started.state.revision,
            (StartAction("run-2", "action.rest", _snapshot(TIME)),),
        ),
        state=started.state,
        context=_context(TIME, "tx-conflict"),
    )
    assert conflict.failure and conflict.failure.code == "action.main_slot_occupied"

    too_early = engine.execute(
        ActionTransaction(
            "tx-early",
            state.owner_id,
            started.state.revision,
            (
                CompleteAction(
                    "run-1",
                    ActionResult("outcome.success", TIME + timedelta(minutes=9)),
                ),
            ),
        ),
        state=started.state,
        context=_context(TIME + timedelta(minutes=9), "tx-early"),
    )
    assert too_early.failure and too_early.failure.code == "action.not_due"

    due = TIME + timedelta(minutes=10)
    completed = _success(
        engine,
        started.state,
        ActionTransaction(
            "tx-complete",
            state.owner_id,
            started.state.revision,
            (
                CompleteAction(
                    "run-1",
                    ActionResult(
                        "outcome.success",
                        due,
                        "reward:run-1",
                        {"damage": 18},
                    ),
                ),
            ),
        ),
        due,
    )
    assert not completed.state.running(ActionSlotKind.MAIN)
    assert completed.state.completed("action.explore")[0].result.facts["damage"] == 18

    next_main = _success(
        engine,
        completed.state,
        ActionTransaction(
            "tx-next-main",
            state.owner_id,
            completed.state.revision,
            (StartAction("run-2", "action.rest", _snapshot(due)),),
        ),
        due,
    )
    commissioned = _success(
        engine,
        next_main.state,
        ActionTransaction(
            "tx-commission",
            state.owner_id,
            next_main.state.revision,
            (StartAction("commission-1", "action.trade", _snapshot(due)),),
        ),
        due,
    )
    commission_full = engine.execute(
        ActionTransaction(
            "tx-commission-full",
            state.owner_id,
            commissioned.state.revision,
            (StartAction("commission-2", "action.trade", _snapshot(due)),),
        ),
        state=commissioned.state,
        context=_context(due, "tx-commission-full"),
    )
    assert commission_full.failure and commission_full.failure.code == "action.commission_slots_full"

    cancelled = _success(
        engine,
        commissioned.state,
        ActionTransaction(
            "tx-cancel",
            state.owner_id,
            commissioned.state.revision,
            (CancelAction("run-2"),),
        ),
        due,
    )
    interrupted = _success(
        engine,
        cancelled.state,
        ActionTransaction(
            "tx-interrupt",
            state.owner_id,
            cancelled.state.revision,
            (InterruptAction("commission-1", "reason.world_event"),),
        ),
        due,
    )
    claimed = _success(
        engine,
        interrupted.state,
        ActionTransaction(
            "tx-claim",
            state.owner_id,
            interrupted.state.revision,
            (ClaimAction("run-1"),),
        ),
        due,
    )
    assert not claimed.state.records
    _assert_snapshot_round_trip(claimed.state, due)
    print("action foundation tests passed")


def _snapshot(at: datetime) -> ActionSnapshot:
    return ActionSnapshot(
        at,
        "rules.action.v1",
        "content-fingerprint",
        "fixed-seed",
        actor_revision=3,
        loadout_revision=2,
        values={"location_id": "location.mountain_gate"},
    )


def _context(at: datetime, trace_id: str) -> RuleContext:
    return RuleContext(
        trace_id,
        "rules.action.v1",
        Ruleset("ruleset.action_test"),
        at,
        SeededRandomSource(trace_id),
    )


def _success(engine, state, transaction, at):
    outcome = engine.execute(
        transaction,
        state=state,
        context=_context(at, transaction.id),
    )
    assert not outcome.failure, outcome.failure
    assert outcome.value is not None
    return outcome.value


def _assert_snapshot_round_trip(state: ActionState, logical_time: datetime) -> None:
    with TemporaryDirectory() as directory:
        database = SqliteDatabase(Path(directory) / "action.db")
        database.initialize()
        repository = SnapshotRepository()
        with database.unit_of_work() as uow:
            repository.insert(uow, ACTION_AGGREGATE, state.owner_id, state, logical_time)
            uow.commit()
        with database.unit_of_work(write=False) as uow:
            restored = repository.require(
                uow,
                ACTION_AGGREGATE,
                state.owner_id,
                ActionState,
            )
        assert restored == state


if __name__ == "__main__":
    main()
