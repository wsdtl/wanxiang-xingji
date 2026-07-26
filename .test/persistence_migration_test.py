"""Schema 7 -> 8 receipt compression, backup and rollback acceptance tests."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.persistence.errors import (  # noqa: E402
    CorruptPersistenceData,
    SchemaVersionError,
)
from game.core.persistence.sqlite import SqliteDatabase  # noqa: E402


TIME = datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc).isoformat()
ACCOUNT_RECEIPT = '{"account":"' + "a" * 24_000 + '"}'
REWARD_RECEIPT = '{"reward":"' + "r" * 18_000 + '"}'


def main() -> None:
    with TemporaryDirectory() as directory:
        _assert_complete_migration(Path(directory) / "complete.db")
    with TemporaryDirectory() as directory:
        _assert_failed_migration_rolls_back(Path(directory) / "rollback.db")
    with TemporaryDirectory() as directory:
        _assert_schema_six_is_rejected(Path(directory) / "unsupported.db")
    with TemporaryDirectory() as directory:
        _assert_corrupt_compressed_receipt_is_rejected(Path(directory) / "corrupt.db")
    print("persistence migration tests passed")


def _assert_complete_migration(path: Path) -> None:
    _prepare_v7(path)
    before_bytes = path.stat().st_size

    database = SqliteDatabase(path)
    database.initialize()
    database.initialize()

    backups = tuple((path.parent / "backups").glob("migration_complete_schema7_*.db"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as backup:
        assert _schema_version(backup) == "7"
        assert backup.execute(
            "SELECT typeof(receipt_payload) FROM committed_transaction LIMIT 1"
        ).fetchone()[0] == "text"
        assert backup.execute(
            "SELECT receipt_payload FROM account_evidence WHERE evidence_id = 'evidence-a'"
        ).fetchone()[0] == ACCOUNT_RECEIPT
        assert tuple(row[0] for row in backup.execute("PRAGMA quick_check")) == ("ok",)

    with database.unit_of_work(write=False) as uow:
        assert _schema_version(uow.connection) == "8"
        assert tuple(row[0] for row in uow.connection.execute("PRAGMA quick_check")) == (
            "ok",
        )
        assert not uow.connection.execute("PRAGMA foreign_key_check").fetchall()
        assert uow.load_transaction("account:evidence-a").receipt_payload == ACCOUNT_RECEIPT
        assert uow.load_transaction("reward-a").receipt_payload == REWARD_RECEIPT
        raw = uow.connection.execute(
            """
            SELECT typeof(receipt_payload), SUM(length(receipt_payload))
            FROM committed_transaction
            """
        ).fetchone()
        assert tuple(raw)[0] == "blob"
        assert int(raw[1]) < (len(ACCOUNT_RECEIPT) + len(REWARD_RECEIPT)) // 10
        assert "receipt_payload" not in _columns(uow.connection, "account_evidence")
        assert "receipt_payload" not in _columns(uow.connection, "reward_claim")
        assert "receipt_payload" not in _columns(uow.connection, "grant_redemption")
        assert dict(_column_types(uow.connection, "committed_transaction"))[
            "receipt_payload"
        ] == "BLOB"
        reward_foreign_keys = {
            (str(row[3]), str(row[2]), str(row[4]))
            for row in uow.connection.execute("PRAGMA foreign_key_list(reward_claim)")
        }
        assert reward_foreign_keys == {
            ("settlement_id", "committed_transaction", "transaction_id")
        }

    assert path.stat().st_size <= before_bytes * 2


def _assert_failed_migration_rolls_back(path: Path) -> None:
    _prepare_v7(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            UPDATE account_evidence
            SET receipt_payload = receipt_payload || 'broken'
            WHERE evidence_id = 'evidence-a'
            """
        )
        connection.commit()

    try:
        SqliteDatabase(path).initialize()
        raise AssertionError("不一致的 schema 7 重复回执不得被部分迁移")
    except SchemaVersionError:
        pass

    with closing(sqlite3.connect(path)) as connection:
        assert _schema_version(connection) == "7"
        assert connection.execute(
            "SELECT typeof(receipt_payload) FROM committed_transaction LIMIT 1"
        ).fetchone()[0] == "text"
        assert "receipt_payload" in _columns(connection, "account_evidence")
        assert "receipt_payload" in _columns(connection, "reward_claim")
        assert "receipt_payload" in _columns(connection, "grant_redemption")
        assert tuple(row[0] for row in connection.execute("PRAGMA quick_check")) == (
            "ok",
        )
    backups = tuple((path.parent / "backups").glob("migration_rollback_schema7_*.db"))
    assert len(backups) == 1


def _assert_schema_six_is_rejected(path: Path) -> None:
    _prepare_v7(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "UPDATE persistence_metadata SET value = '6' WHERE key = 'schema_version'"
        )
        connection.commit()
    try:
        SqliteDatabase(path).initialize()
        raise AssertionError("schema 6 不应继续自动兼容")
    except SchemaVersionError:
        pass
    assert not (path.parent / "backups").exists()


def _assert_corrupt_compressed_receipt_is_rejected(path: Path) -> None:
    database = SqliteDatabase(path)
    database.initialize()
    with database.unit_of_work() as uow:
        uow.insert_transaction("broken", "fp", "scope", "{}", TIME)
        uow.commit()
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "UPDATE committed_transaction SET receipt_payload = X'010203' WHERE transaction_id = 'broken'"
        )
        connection.commit()
    with database.unit_of_work(write=False) as uow:
        try:
            uow.load_transaction("broken")
            raise AssertionError("损坏的压缩回执不得静默返回")
        except CorruptPersistenceData:
            pass


def _prepare_v7(path: Path) -> None:
    database = SqliteDatabase(path)
    database.initialize()
    with database.unit_of_work() as uow:
        uow.insert_transaction(
            "account:evidence-a",
            "fingerprint-account",
            "account-a",
            ACCOUNT_RECEIPT,
            TIME,
        )
        uow.connection.execute(
            """
            INSERT INTO account_record(account_id, status, revision, created_at, updated_at)
            VALUES ('account-a', 'active', 1, ?, ?)
            """,
            (TIME, TIME),
        )
        uow.connection.execute(
            """
            INSERT INTO account_evidence(
                evidence_id, fingerprint, account_id, conflict_id,
                transaction_id, processed_at
            ) VALUES ('evidence-a', 'fingerprint-account', 'account-a', NULL,
                      'account:evidence-a', ?)
            """,
            (TIME,),
        )
        uow.insert_transaction(
            "reward-a",
            "fingerprint-reward",
            "account-a",
            REWARD_RECEIPT,
            TIME,
        )
        uow.insert_reward_claim(
            "account-a",
            "reward-a",
            "fingerprint-reward",
            1,
            TIME,
        )
        uow.commit()

    with database.unit_of_work(write=False) as uow:
        transactions = tuple(
            uow.load_transaction(str(row[0]))
            for row in uow.connection.execute(
                "SELECT transaction_id FROM committed_transaction ORDER BY transaction_id"
            )
        )
        account_rows = tuple(
            tuple(row)
            for row in uow.connection.execute(
                """
                SELECT evidence_id, fingerprint, account_id, conflict_id,
                       transaction_id, processed_at
                FROM account_evidence
                """
            )
        )
        reward_rows = tuple(
            tuple(row)
            for row in uow.connection.execute(
                """
                SELECT scope_id, settlement_id, fingerprint,
                       resulting_revision, claimed_at
                FROM reward_claim
                """
            )
        )
    receipts = {
        transaction.transaction_id: transaction.receipt_payload
        for transaction in transactions
        if transaction is not None
    }

    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("PRAGMA legacy_alter_table = ON")
        connection.execute("BEGIN EXCLUSIVE")
        try:
            for table in (
                "committed_transaction",
                "reward_claim",
                "account_evidence",
                "grant_redemption",
            ):
                connection.execute(f"ALTER TABLE {table} RENAME TO _schema8_{table}")
            for statement in _V7_TABLES:
                connection.execute(statement)
            connection.executemany(
                """
                INSERT INTO committed_transaction(
                    transaction_id, fingerprint, scope_id, receipt_payload, committed_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    (
                        value.transaction_id,
                        value.fingerprint,
                        value.scope_id,
                        value.receipt_payload,
                        value.committed_at,
                    )
                    for value in transactions
                    if value is not None
                ),
            )
            connection.executemany(
                """
                INSERT INTO account_evidence(
                    evidence_id, fingerprint, account_id, conflict_id,
                    transaction_id, receipt_payload, processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (*row[:5], receipts[str(row[4])], row[5])
                    for row in account_rows
                ),
            )
            connection.executemany(
                """
                INSERT INTO reward_claim(
                    scope_id, settlement_id, fingerprint, receipt_payload,
                    resulting_revision, claimed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    (*row[:3], receipts[str(row[1])], *row[3:])
                    for row in reward_rows
                ),
            )
            for table in (
                "_schema8_grant_redemption",
                "_schema8_account_evidence",
                "_schema8_reward_claim",
                "_schema8_committed_transaction",
            ):
                connection.execute(f"DROP TABLE {table}")
            for statement in _V7_INDEXES:
                connection.execute(statement)
            connection.execute(
                "UPDATE persistence_metadata SET value = '7' WHERE key = 'schema_version'"
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.execute("PRAGMA legacy_alter_table = OFF")
            connection.execute("PRAGMA foreign_keys = ON")
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


_V7_TABLES = (
    """
    CREATE TABLE committed_transaction (
        transaction_id TEXT PRIMARY KEY,
        fingerprint TEXT NOT NULL,
        scope_id TEXT NOT NULL,
        receipt_payload TEXT NOT NULL,
        committed_at TEXT NOT NULL
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE reward_claim (
        scope_id TEXT NOT NULL,
        settlement_id TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        receipt_payload TEXT NOT NULL,
        resulting_revision INTEGER NOT NULL CHECK (resulting_revision > 0),
        claimed_at TEXT NOT NULL,
        PRIMARY KEY (scope_id, settlement_id),
        UNIQUE (settlement_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE account_evidence (
        evidence_id TEXT PRIMARY KEY,
        fingerprint TEXT NOT NULL,
        account_id TEXT,
        conflict_id TEXT,
        transaction_id TEXT NOT NULL UNIQUE,
        receipt_payload TEXT NOT NULL,
        processed_at TEXT NOT NULL,
        CHECK ((account_id IS NULL) <> (conflict_id IS NULL)),
        FOREIGN KEY (account_id) REFERENCES account_record(account_id) ON DELETE RESTRICT,
        FOREIGN KEY (conflict_id) REFERENCES account_conflict(conflict_id) ON DELETE RESTRICT,
        FOREIGN KEY (transaction_id)
            REFERENCES committed_transaction(transaction_id) ON DELETE RESTRICT
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE grant_redemption (
        redemption_id TEXT PRIMARY KEY,
        entitlement_id TEXT NOT NULL UNIQUE,
        campaign_id TEXT NOT NULL,
        credential_id TEXT,
        account_id TEXT NOT NULL,
        settlement_id TEXT NOT NULL UNIQUE,
        request_fingerprint TEXT NOT NULL,
        receipt_payload TEXT NOT NULL,
        redeemed_at TEXT NOT NULL,
        FOREIGN KEY (entitlement_id) REFERENCES grant_entitlement(entitlement_id) ON DELETE RESTRICT,
        FOREIGN KEY (campaign_id) REFERENCES grant_campaign(campaign_id) ON DELETE RESTRICT,
        FOREIGN KEY (credential_id) REFERENCES grant_credential(credential_id) ON DELETE RESTRICT,
        FOREIGN KEY (settlement_id) REFERENCES committed_transaction(transaction_id) ON DELETE RESTRICT
    ) WITHOUT ROWID
    """,
)

_V7_INDEXES = (
    "CREATE INDEX reward_claim_time_idx ON reward_claim(scope_id, claimed_at, settlement_id)",
    "CREATE INDEX account_evidence_account_idx ON account_evidence(account_id, processed_at)",
    "CREATE INDEX grant_redemption_account_idx ON grant_redemption(campaign_id, account_id, redeemed_at)",
)


def _schema_version(connection: sqlite3.Connection) -> str:
    return str(
        connection.execute(
            "SELECT value FROM persistence_metadata WHERE key = 'schema_version'"
        ).fetchone()[0]
    )


def _columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})"))


def _column_types(connection: sqlite3.Connection, table: str) -> tuple[tuple[str, str], ...]:
    return tuple(
        (str(row[1]), str(row[2]).upper())
        for row in connection.execute(f"PRAGMA table_info({table})")
    )


if __name__ == "__main__":
    main()
