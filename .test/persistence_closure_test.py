"""行动与装配持久化闭环测试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay.actions import (  # noqa: E402
    ActionCatalog,
    ActionDefinition,
    ActionEngine,
    ActionResult,
    ActionSlotKind,
    ActionState,
    ActionTransaction,
    ClaimAction,
    CompleteAction,
    StartAction,
)
from game.core.account import AccountEngine, AccountStatus, AccountStatusTransaction  # noqa: E402
from game.core.gameplay.loadout import (  # noqa: E402
    EquipAsset,
    LoadoutEngine,
    LoadoutState,
    WEAPON_SLOT_ID,
)
from game.core.persistence import (  # noqa: E402
    INVENTORY_AGGREGATE,
    PersistedActionService,
    PersistedAccountService,
    PersistedLoadoutService,
    SnapshotRepository,
    SqliteDatabase,
    TransactionMismatch,
)

from action_foundation_test import TIME as ACTION_TIME, _context as action_context, _snapshot  # noqa: E402
from account_foundation_test import (  # noqa: E402
    SequenceIds,
    _group_evidence,
    _private_evidence,
)
from loadout_weapon_equipment_test import (  # noqa: E402
    TIME as LOADOUT_TIME,
    _context as loadout_context,
    _environment as loadout_environment,
    _initial_inventory,
    _loadout_transaction,
)


def main() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        _assert_account_relations_and_hmac(root / "account.db")
        _assert_action_restart_and_replay(root / "action.db")
        _assert_loadout_inventory_atomicity(root / "loadout.db")
    print("persistence closure tests passed")


def _assert_account_relations_and_hmac(path: Path) -> None:
    database = SqliteDatabase(path)
    database.initialize()
    secret = "account-test-secret-32-bytes-long"
    service = PersistedAccountService(database, AccountEngine(SequenceIds()), secret)

    group = _group_evidence("event-group-1")
    first = service.resolve_identity(group)
    assert first.resolved and first.created and first.account
    assert first.account.id == "account-1"
    assert service.identity_count("account-1") == 3
    replay = service.resolve_identity(group)
    assert replay.replayed and replay.account == first.account
    delayed_replay = service.resolve_identity(
        replace(group, logical_time=group.logical_time + timedelta(minutes=5))
    )
    assert delayed_replay.replayed and delayed_replay.account == first.account
    try:
        service.resolve_identity(
            _group_evidence("event-group-1", member="M999")
        )
        raise AssertionError("同一事件 ID 不能更换身份集合")
    except TransactionMismatch:
        pass

    restarted = PersistedAccountService(database, AccountEngine(SequenceIds()), secret)
    private = restarted.resolve_identity(_private_evidence("event-private-1"))
    assert private.account and private.account.id == "account-1"
    assert restarted.identity_count("account-1") == 4

    second = restarted.resolve_identity(
        _private_evidence("event-private-2", user="U999")
    )
    assert second.account and second.account.id == "account-2"
    conflict = restarted.resolve_identity(
        _group_evidence(
            "event-conflict",
            user="U123",
            member="U999",
        )
    )
    assert not conflict.resolved and conflict.conflict
    assert conflict.conflict.account_ids == ("account-1", "account-2")

    account = restarted.load_account("account-1")
    assert account is not None
    suspend = AccountStatusTransaction(
        "account-status-suspend",
        account.id,
        account.revision,
        AccountStatus.SUSPENDED,
        "security.review",
        ACTION_TIME,
    )
    changed = restarted.change_status(suspend)
    assert changed.account.status is AccountStatus.SUSPENDED
    assert restarted.change_status(suspend).replayed

    raw_database = path.read_bytes()
    for raw_value in (
        b"bot-app-1",
        b"event-group-1",
        b"event-private-1",
        b"event-conflict",
        b"U123",
        b"U999",
        b"M456",
        b"G1",
    ):
        assert raw_value not in raw_database


def _action_engine() -> ActionEngine:
    catalog = ActionCatalog()
    catalog.register(
        ActionDefinition("action.explore", ActionSlotKind.MAIN, timedelta(minutes=10))
    )
    catalog.finalize()
    return ActionEngine(catalog)


def _assert_action_restart_and_replay(path: Path) -> None:
    database = SqliteDatabase(path)
    database.initialize()
    service = PersistedActionService(database, _action_engine())
    assert service.initialize("player-1", logical_time=ACTION_TIME) == ActionState("player-1")

    start = ActionTransaction(
        "persisted-action-start",
        "player-1",
        0,
        (StartAction("run-1", "action.explore", _snapshot(ACTION_TIME)),),
    )
    first = service.execute(start, context=action_context(ACTION_TIME, start.id)).unwrap()
    assert not first.replayed
    assert first.execution.state.revision == 1
    replay = service.execute(start, context=action_context(ACTION_TIME, start.id)).unwrap()
    assert replay.replayed and replay.execution == first.execution

    due = ACTION_TIME + timedelta(minutes=10)
    complete = ActionTransaction(
        "persisted-action-complete",
        "player-1",
        1,
        (CompleteAction("run-1", ActionResult("outcome.success", due)),),
    )
    service.execute(complete, context=action_context(due, complete.id)).unwrap()
    restarted = PersistedActionService(database, _action_engine())
    restored = restarted.load("player-1")
    assert restored and restored.revision == 2 and restored.completed()[0].id == "run-1"

    claim = ActionTransaction(
        "persisted-action-claim",
        "player-1",
        2,
        (ClaimAction("run-1"),),
    )
    claimed = restarted.execute(claim, context=action_context(due, claim.id)).unwrap()
    assert not claimed.execution.state.records


def _assert_loadout_inventory_atomicity(path: Path) -> None:
    environment = loadout_environment()
    inventory_engine = environment["inventory"]
    items = environment["items"]
    slots = environment["slots"]
    engine = LoadoutEngine(slots, items, inventory_engine)  # type: ignore[arg-type]
    database = SqliteDatabase(path)
    database.initialize()
    snapshots = SnapshotRepository()
    inventory = _initial_inventory(environment)
    with database.unit_of_work() as uow:
        snapshots.insert(
            uow,
            INVENTORY_AGGREGATE,
            "inventory-a",
            inventory,
            LOADOUT_TIME,
        )
        uow.commit()

    service = PersistedLoadoutService(database, engine)
    loadout = service.initialize(LoadoutState("character-a"), logical_time=LOADOUT_TIME)
    transaction = _loadout_transaction(
        loadout,
        "persisted-equip",
        EquipAsset(WEAPON_SLOT_ID, "weapon-new"),
    )
    first = service.execute(
        transaction,
        inventory_id="inventory-a",
        character_id="character-a",
        context=loadout_context(901),
    ).unwrap()
    assert not first.replayed
    assert first.execution.loadout.weapon_asset_id == "weapon-new"
    assert first.execution.inventory.instances["weapon-new"].container_id == "equipped"

    replay = service.execute(
        transaction,
        inventory_id="inventory-a",
        character_id="character-a",
        context=loadout_context(902),
    ).unwrap()
    assert replay.replayed and replay.execution == first.execution
    restarted = PersistedLoadoutService(database, engine)
    assert restarted.load("character-a") == first.execution.loadout


if __name__ == "__main__":
    main()
