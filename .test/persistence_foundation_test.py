"""持久化结构版本、联合提交、CAS、事实日志与可选 Outbox 测试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay.rewards import (  # noqa: E402
    CharacterFeatureReward,
    CurrencyReward,
    RewardExpectations,
    RewardSettlement,
    StackItemReward,
)
from game.core.persistence import (  # noqa: E402
    ConcurrencyConflict,
    CorruptPersistenceData,
    FactJournalService,
    INVENTORY_AGGREGATE,
    PERSISTENCE_FOUNDATION_VERSION,
    PERSISTENCE_SCHEMA_VERSION,
    PersistedRewardSettlementService,
    RewardSettlementStorageKeys,
    SchemaVersionError,
    SnapshotRepository,
    SqliteDatabase,
    TransactionMismatch,
)

from reward_settlement_test import (  # noqa: E402
    TIME,
    _complete_settlement,
    _context,
    _environment,
)


def main() -> None:
    _assert_database_schema_rejection()
    with TemporaryDirectory() as directory:
        _assert_atomic_persisted_settlement(Path(directory))
    print("persistence foundation tests passed")


def _assert_database_schema_rejection() -> None:
    with TemporaryDirectory() as directory:
        unknown_path = Path(directory) / "unknown.db"
        connection = sqlite3.connect(unknown_path)
        connection.execute("CREATE TABLE old_game_data(id INTEGER PRIMARY KEY)")
        connection.commit()
        connection.close()
        try:
            SqliteDatabase(unknown_path).initialize()
            raise AssertionError("未知旧数据库不能被静默盖章为新结构")
        except SchemaVersionError:
            pass

        mismatch_path = Path(directory) / "mismatch.db"
        database = SqliteDatabase(mismatch_path)
        database.initialize()
        connection = sqlite3.connect(mismatch_path)
        connection.execute(
            "UPDATE persistence_metadata SET value = ? WHERE key = ?",
            ("999", "schema_version"),
        )
        connection.commit()
        connection.close()
        try:
            database.initialize()
            raise AssertionError("结构版本不匹配时必须拒绝启动")
        except SchemaVersionError:
            pass

        shape_path = Path(directory) / "shape.db"
        shape_database = SqliteDatabase(shape_path)
        shape_database.initialize()
        connection = sqlite3.connect(shape_path)
        connection.execute("DROP INDEX outbox_event_pending_idx")
        connection.commit()
        connection.close()
        try:
            shape_database.initialize()
            raise AssertionError("核心索引损坏时不能只凭版本号启动")
        except SchemaVersionError:
            pass


def _assert_atomic_persisted_settlement(directory: Path) -> None:
    environment = _environment()
    engine = environment["engine"]
    initial = environment["snapshot"]
    keys = RewardSettlementStorageKeys(
        "inventory-account-a",
        "ledger-world-main",
        character_ids=("character-a",),
        weapon_ids=("weapon-a",),
    )
    database = SqliteDatabase(directory / "wanxiang-xingji-test.db")
    database.initialize()
    database.initialize()
    service = PersistedRewardSettlementService(database, engine)
    service.initialize_snapshot(keys, initial, logical_time=TIME)
    assert PERSISTENCE_FOUNDATION_VERSION == "persistence.foundation.v10"
    assert PERSISTENCE_SCHEMA_VERSION == 8
    assert service.load_snapshot(keys, claim_scope_id="account-a") == initial

    settlement = _complete_settlement(initial)
    outcome = service.settle(settlement, keys, context=_context(seed=1_001))
    assert outcome.ok and outcome.value, outcome.failure
    persisted = service.load_snapshot(keys, claim_scope_id="account-a")
    assert persisted == outcome.value.snapshot
    assert persisted.inventory.stacks["ore-reward"].quantity == 5
    assert persisted.ledger.accounts["wallet-a"].balance == 250
    assert persisted.characters["character-a"].revision == 1
    assert persisted.weapons["weapon-a"].revision == 1
    assert persisted.claims.revision == 1

    facts = FactJournalService(database).list(limit=100)
    assert len(facts) == len(outcome.value.events)
    assert facts[-1].kind == "reward.settlement.completed"
    assert service.pending_events(limit=100) == ()
    with database.unit_of_work(write=False) as uow:
        committed = uow.load_transaction(settlement.id)
        assert committed and committed.scope_id == "account-a"
        assert uow.pending_outbox(limit=100) == ()

    replay = service.settle(settlement, keys, context=_context(seed=1_002))
    assert replay.ok and replay.value and replay.value.replayed
    assert service.load_snapshot(keys, claim_scope_id="account-a") == persisted
    assert len(FactJournalService(database).list(limit=100)) == len(facts)

    changed = replace(
        settlement,
        rewards=(CurrencyReward("issuer-stone", "wallet-a", 251), *settlement.rewards[1:]),
    )
    try:
        service.settle(changed, keys, context=_context(seed=1_003))
        raise AssertionError("数据库事务 ID 相同但内容不同时必须拒绝")
    except TransactionMismatch:
        pass

    _assert_late_rule_failure_does_not_persist(service, keys, persisted)
    _assert_uncommitted_and_stale_cas_rollback(database, persisted)

    first = outcome.value.events[0]
    with database.unit_of_work() as uow:
        uow.enqueue_outbox(
            settlement.id,
            0,
            first.kind,
            service.snapshots.codec.dumps(first),
            TIME.isoformat(),
        )
        uow.commit()
    pending = service.pending_events(limit=100)
    assert len(pending) == 1 and pending[0].event == first
    first_delivery = pending[0]
    service.mark_event_published(
        first_delivery.transaction_id,
        first_delivery.sequence,
        published_at=TIME + timedelta(minutes=1),
    )
    assert service.pending_events(limit=100) == ()
    try:
        service.mark_event_published(
            first_delivery.transaction_id,
            first_delivery.sequence,
            published_at=TIME + timedelta(minutes=2),
        )
        raise AssertionError("同一 Outbox 事件不能重复标记发布")
    except ConcurrencyConflict:
        pass

    _assert_append_only_history_is_externalized(service, keys, persisted)


def _assert_append_only_history_is_externalized(service, keys, current) -> None:
    with service.database.unit_of_work(write=False) as uow:
        before_ledger_size = uow.connection.execute(
            """
            SELECT length(payload) FROM aggregate_snapshot
            WHERE aggregate_kind = 'snapshot.ledger' AND aggregate_id = ?
            """,
            (keys.ledger_id,),
        ).fetchone()[0]
        before_claim_size = uow.connection.execute(
            """
            SELECT length(payload) FROM aggregate_snapshot
            WHERE aggregate_kind = 'snapshot.reward_claim' AND aggregate_id = ?
            """,
            (current.claims.scope_id,),
        ).fetchone()[0]

    replay_candidate = None
    for index in range(60):
        settlement = RewardSettlement(
            f"reward-growth-{index:03d}",
            current.claims.scope_id,
            current.claims.scope_id,
            "source.persistence_growth_test",
            f"growth-{index:03d}",
            (CurrencyReward("issuer-stone", "wallet-a", 1),),
            RewardExpectations(
                current.claims.revision,
                ledger_account_revisions={
                    "issuer-stone": current.ledger.accounts["issuer-stone"].revision,
                    "wallet-a": current.ledger.accounts["wallet-a"].revision,
                },
            ),
        )
        outcome = service.settle(
            settlement,
            keys,
            context=_context(seed=2_000 + index),
        ).unwrap()
        current = outcome.snapshot
        if index == 10:
            replay_candidate = settlement

    assert replay_candidate is not None
    with service.database.unit_of_work(write=False) as uow:
        after_ledger_size = uow.connection.execute(
            """
            SELECT length(payload) FROM aggregate_snapshot
            WHERE aggregate_kind = 'snapshot.ledger' AND aggregate_id = ?
            """,
            (keys.ledger_id,),
        ).fetchone()[0]
        after_claim_size = uow.connection.execute(
            """
            SELECT length(payload) FROM aggregate_snapshot
            WHERE aggregate_kind = 'snapshot.reward_claim' AND aggregate_id = ?
            """,
            (current.claims.scope_id,),
        ).fetchone()[0]
        ledger_transactions = uow.connection.execute(
            "SELECT COUNT(*) FROM ledger_transaction WHERE ledger_id = ?",
            (keys.ledger_id,),
        ).fetchone()[0]
        reward_claims = uow.connection.execute(
            "SELECT COUNT(*) FROM reward_claim WHERE scope_id = ?",
            (current.claims.scope_id,),
        ).fetchone()[0]
    assert after_ledger_size <= before_ledger_size + 256
    assert after_claim_size <= before_claim_size + 64
    assert ledger_transactions == 61
    assert reward_claims == 61

    replayed = service.settle(
        replay_candidate,
        keys,
        context=_context(seed=3_000),
    ).unwrap()
    assert replayed.replayed
    assert replayed.receipt.settlement_id == replay_candidate.id
    assert replayed.snapshot == current


def _assert_late_rule_failure_does_not_persist(service, keys, before) -> None:
    settlement = RewardSettlement(
        "persisted-reward-fails-late",
        "account-a",
        "account-a",
        "source.quest_reward",
        "quest-persist-invalid",
        (
            StackItemReward(
                "ore-persist-before-failure",
                "item.material.spirit_ore",
                "bag-a",
                3,
            ),
            CurrencyReward("issuer-stone", "wallet-a", 99),
            CharacterFeatureReward("character-a", "feature.unknown"),
        ),
        RewardExpectations(
            before.claims.revision,
            inventory_revision=before.inventory.revision,
            ledger_account_revisions={
                "issuer-stone": before.ledger.accounts["issuer-stone"].revision,
                "wallet-a": before.ledger.accounts["wallet-a"].revision,
            },
            character_revisions={
                "character-a": before.characters["character-a"].revision,
            },
        ),
    )
    pending_before = service.pending_events(limit=100)
    context = _context(seed=1_004)
    checkpoint = context.random.checkpoint()
    failed = service.settle(settlement, keys, context=context)
    assert failed.failure and failed.failure.code == "character.feature_unknown"
    assert service.load_snapshot(keys, claim_scope_id="account-a") == before
    assert service.pending_events(limit=100) == pending_before
    assert context.random.checkpoint() == checkpoint
    with service.database.unit_of_work(write=False) as uow:
        assert uow.load_transaction(settlement.id) is None


def _assert_uncommitted_and_stale_cas_rollback(database, persisted) -> None:
    repository = SnapshotRepository()
    candidate = replace(persisted.inventory, revision=persisted.inventory.revision + 1)
    with database.unit_of_work() as uow:
        repository.update(
            uow,
            INVENTORY_AGGREGATE,
            "inventory-account-a",
            persisted.inventory,
            candidate,
            TIME,
        )
        # 不调用 commit，退出上下文必须回滚。
    with database.unit_of_work(write=False) as uow:
        current = repository.require(
            uow,
            INVENTORY_AGGREGATE,
            "inventory-account-a",
            type(persisted.inventory),
        )
        assert current == persisted.inventory

    stale = replace(persisted.inventory, revision=persisted.inventory.revision + 1)
    try:
        with database.unit_of_work() as uow:
            uow.compare_and_swap_snapshot(
                INVENTORY_AGGREGATE,
                "inventory-account-a",
                999,
                1_000,
                repository.codec.dumps(stale),
                TIME.isoformat(),
            )
        raise AssertionError("旧 revision 条件更新必须失败")
    except ConcurrencyConflict:
        pass

    with database.unit_of_work() as uow:
        row = uow.require_snapshot(INVENTORY_AGGREGATE, "inventory-account-a")
        uow.connection.execute(
            "UPDATE aggregate_snapshot SET payload = ? WHERE aggregate_kind = ? AND aggregate_id = ?",
            ('{"format":"structured-json.v1","value":{"$type":"unknown.type"}}', INVENTORY_AGGREGATE, "inventory-account-a"),
        )
        try:
            repository.require(
                uow,
                INVENTORY_AGGREGATE,
                "inventory-account-a",
                type(persisted.inventory),
            )
            raise AssertionError("未知持久化类型不能被动态导入")
        except CorruptPersistenceData:
            pass
        # 未提交，损坏注入也必须回滚；row 只用于确认原记录存在。
        assert row.revision == persisted.inventory.revision


if __name__ == "__main__":
    main()
