"""多世界拓扑、存在体、移动、占用和共享计量测试。"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay import RuleContext, Ruleset, SeededRandomSource  # noqa: E402
from game.core.gameplay.world import (  # noqa: E402
    WORLD_FOUNDATION_VERSION,
    AddPresence,
    AdjustWorldMeter,
    MeterOverflowPolicy,
    MovePresence,
    ReserveWorldPosition,
    WorldCatalog,
    WorldConnectionDefinition,
    WorldEngine,
    WorldLocationDefinition,
    WorldMeterDefinition,
    WorldPosition,
    WorldPresence,
    WorldReservation,
    WorldScopeKind,
    WorldScopeRef,
    WorldSpaceDefinition,
    WorldState,
    WorldTopologyKind,
    WorldTransaction,
    meter_key,
)


TIME = datetime(2026, 7, 14, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
    assert WORLD_FOUNDATION_VERSION == "world.foundation.v4"
    engine = _engine()
    _assert_grid_and_multiple_presences(engine)
    _assert_graph_path(engine)
    _assert_reservations_and_expiry(engine)
    _assert_scoped_meter(engine)
    print("world foundation tests passed")


def _engine() -> WorldEngine:
    catalog = WorldCatalog()
    catalog.spaces.register(
        WorldSpaceDefinition("world_space.mortal", WorldTopologyKind.GRID, -10, 10, -10, 10)
    )
    catalog.spaces.register(
        WorldSpaceDefinition("world_space.realm", WorldTopologyKind.GRAPH)
    )
    catalog.locations.register(
        WorldLocationDefinition("location.city", "world_space.mortal", 0, 0, capacity=2)
    )
    catalog.locations.register(
        WorldLocationDefinition("location.port", "world_space.mortal", 4, 3)
    )
    for location_id in ("location.realm_a", "location.realm_b", "location.realm_c"):
        catalog.locations.register(WorldLocationDefinition(location_id, "world_space.realm"))
    catalog.connections.register(
        WorldConnectionDefinition(
            "connection.realm_ab",
            "world_space.realm",
            "location.realm_a",
            "location.realm_b",
            3,
        )
    )
    catalog.connections.register(
        WorldConnectionDefinition(
            "connection.realm_bc",
            "world_space.realm",
            "location.realm_b",
            "location.realm_c",
            4,
        )
    )
    catalog.meters.register(
        WorldMeterDefinition(
            "world_meter.construction",
            frozenset({WorldScopeKind.LOCATION}),
            0,
            100,
            0,
            (25, 50, 100),
            MeterOverflowPolicy.CLAMP,
        )
    )
    catalog.finalize()
    return WorldEngine(catalog)


def _context(trace: str, at: datetime = TIME) -> RuleContext:
    return RuleContext(
        trace,
        "rules.world_v1",
        Ruleset("ruleset.world_test"),
        at,
        SeededRandomSource(trace),
    )


def _assert_grid_and_multiple_presences(engine: WorldEngine) -> None:
    state = WorldState("world-main")
    transaction = WorldTransaction(
        "world-add-presences",
        "account-a",
        0,
        (
            AddPresence(
                WorldPresence(
                    "presence-body",
                    "account-a",
                    "presence.body",
                    WorldPosition("world_space.mortal", location_id="location.city"),
                )
            ),
            AddPresence(
                WorldPresence(
                    "presence-merchant",
                    "account-a",
                    "presence.merchant",
                    WorldPosition("world_space.mortal", x=1, y=1),
                )
            ),
        ),
    )
    added = engine.execute(transaction, state=state, context=_context(transaction.id)).unwrap()
    assert len(added.state.presences) == 2
    move = WorldTransaction(
        "world-move-merchant",
        "account-a",
        1,
        (
            MovePresence(
                "presence-merchant",
                WorldPosition("world_space.mortal", location_id="location.port"),
                maximum_cost=5,
            ),
        ),
    )
    moved = engine.execute(move, state=added.state, context=_context(move.id)).unwrap()
    assert moved.state.presences["presence-body"].position.location_id == "location.city"
    assert moved.state.presences["presence-merchant"].position.location_id == "location.port"
    assert moved.events[0].values["cost"] == 5
    city = WorldPosition("world_space.mortal", location_id="location.city")
    assert [value.id for value in engine.presences_at(moved.state, city)] == [
        "presence-body"
    ]
    assert [value.id for value, _ in engine.presences_within(moved.state, city, 6)] == [
        "presence-body"
    ]
    assert [
        (value.id, cost) for value, cost in engine.presences_within(moved.state, city, 7)
    ] == [("presence-body", 0), ("presence-merchant", 7)]


def _assert_graph_path(engine: WorldEngine) -> None:
    origin = WorldPosition("world_space.realm", location_id="location.realm_a")
    destination = WorldPosition("world_space.realm", location_id="location.realm_c")
    assert engine.movement_cost(origin, destination) == 7


def _assert_reservations_and_expiry(engine: WorldEngine) -> None:
    position = WorldPosition("world_space.mortal", location_id="location.city")
    state = WorldState("world-main")
    reserve = WorldTransaction(
        "world-reserve",
        "account-a",
        0,
        (
            ReserveWorldPosition(
                WorldReservation(
                    "reservation-a",
                    "account-a",
                    position,
                    2,
                    False,
                    TIME,
                    TIME + timedelta(minutes=5),
                )
            ),
        ),
    )
    reserved = engine.execute(reserve, state=state, context=_context(reserve.id)).unwrap()
    assert engine.active_reservations_at(
        reserved.state,
        position,
        logical_time=TIME,
    ) == (reserved.state.reservations["reservation-a"],)
    full = engine.execute(
        WorldTransaction(
            "world-reserve-full",
            "account-b",
            1,
            (
                ReserveWorldPosition(
                    WorldReservation(
                        "reservation-b",
                        "account-b",
                        position,
                        1,
                        False,
                        TIME,
                    )
                ),
            ),
        ),
        state=reserved.state,
        context=_context("world-reserve-full"),
    )
    assert full.failure and full.failure.code == "world.position_capacity_exceeded"

    after_expiry_time = TIME + timedelta(minutes=6)
    after_expiry = engine.execute(
        WorldTransaction(
            "world-reserve-after-expiry",
            "account-b",
            1,
            (
                ReserveWorldPosition(
                    WorldReservation(
                        "reservation-b",
                        "account-b",
                        position,
                        1,
                        True,
                        after_expiry_time,
                    )
                ),
            ),
        ),
        state=reserved.state,
        context=_context("world-reserve-after-expiry", after_expiry_time),
    ).unwrap()
    assert set(after_expiry.state.reservations) == {"reservation-b"}
    assert not engine.active_reservations_at(
        reserved.state,
        position,
        logical_time=after_expiry_time,
    )


def _assert_scoped_meter(engine: WorldEngine) -> None:
    scope = WorldScopeRef(WorldScopeKind.LOCATION, "location.city")
    state = WorldState("world-main")
    execution = engine.execute(
        WorldTransaction(
            "world-meter",
            "system-world",
            0,
            (AdjustWorldMeter(scope, "world_meter.construction", 120),),
        ),
        state=state,
        context=_context("world-meter"),
    ).unwrap()
    assert execution.state.meters[meter_key(scope, "world_meter.construction")] == 100
    assert execution.events[0].values["crossed_thresholds"] == (25, 50, 100)


if __name__ == "__main__":
    main()
