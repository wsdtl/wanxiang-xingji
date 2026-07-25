"""SQLite 结构版本、CAS 聚合仓储、事务防重和 Outbox。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from .errors import (
    AggregateNotFound,
    ConcurrencyConflict,
    SchemaVersionError,
    TransactionMismatch,
)


PERSISTENCE_SCHEMA_VERSION = 6
SNAPSHOT_CODEC_VERSION = 1

_REQUIRED_TABLES = frozenset(
    {
        "persistence_metadata",
        "aggregate_snapshot",
        "committed_transaction",
        "outbox_event",
        "content_activation",
        "cycle_cursor",
        "cycle_work_item",
        "account_record",
        "account_identity",
        "account_conflict",
        "account_evidence",
        "fact_journal",
        "projection_checkpoint",
        "projection_record",
        "notification_entry",
        "ranking_snapshot",
        "grant_campaign",
        "grant_credential",
        "grant_entitlement",
        "grant_redemption",
        "migration_manifest",
        "battle_report",
        "battle_report_segment",
    }
)

_EXPECTED_COLUMNS = {
    "persistence_metadata": (
        ("key", "TEXT", 1),
        ("value", "TEXT", 0),
    ),
    "aggregate_snapshot": (
        ("aggregate_kind", "TEXT", 1),
        ("aggregate_id", "TEXT", 2),
        ("revision", "INTEGER", 0),
        ("codec_version", "INTEGER", 0),
        ("payload", "TEXT", 0),
        ("updated_at", "TEXT", 0),
    ),
    "committed_transaction": (
        ("transaction_id", "TEXT", 1),
        ("fingerprint", "TEXT", 0),
        ("scope_id", "TEXT", 0),
        ("receipt_payload", "TEXT", 0),
        ("committed_at", "TEXT", 0),
    ),
    "outbox_event": (
        ("transaction_id", "TEXT", 1),
        ("sequence", "INTEGER", 2),
        ("event_kind", "TEXT", 0),
        ("payload", "TEXT", 0),
        ("created_at", "TEXT", 0),
        ("published_at", "TEXT", 0),
    ),
    "content_activation": (
        ("slot_id", "TEXT", 1),
        ("revision", "INTEGER", 0),
        ("fingerprint", "TEXT", 0),
        ("profile_id", "TEXT", 0),
        ("packages_payload", "TEXT", 0),
        ("activated_at", "TEXT", 0),
    ),
    "cycle_cursor": (
        ("scope_id", "TEXT", 1),
        ("cycle_id", "TEXT", 2),
        ("revision", "INTEGER", 0),
        ("scanned_through", "TEXT", 0),
        ("created_at", "TEXT", 0),
        ("updated_at", "TEXT", 0),
    ),
    "cycle_work_item": (
        ("scope_id", "TEXT", 1),
        ("cycle_id", "TEXT", 2),
        ("instance_id", "TEXT", 3),
        ("transaction_id", "TEXT", 0),
        ("window_start", "TEXT", 0),
        ("window_end", "TEXT", 0),
        ("available_at", "TEXT", 0),
        ("status", "TEXT", 0),
        ("attempt_count", "INTEGER", 0),
        ("lease_owner", "TEXT", 0),
        ("lease_until", "TEXT", 0),
        ("next_attempt_at", "TEXT", 0),
        ("completed_at", "TEXT", 0),
        ("last_error", "TEXT", 0),
        ("created_at", "TEXT", 0),
        ("updated_at", "TEXT", 0),
    ),
    "account_record": (
        ("account_id", "TEXT", 1),
        ("status", "TEXT", 0),
        ("revision", "INTEGER", 0),
        ("created_at", "TEXT", 0),
        ("updated_at", "TEXT", 0),
    ),
    "account_identity": (
        ("provider_id", "TEXT", 1),
        ("tenant_digest", "TEXT", 2),
        ("subject_kind", "TEXT", 3),
        ("scope_digest", "TEXT", 4),
        ("identity_digest", "TEXT", 5),
        ("account_id", "TEXT", 0),
        ("bound_at", "TEXT", 0),
        ("source_evidence_id", "TEXT", 0),
    ),
    "account_conflict": (
        ("conflict_id", "TEXT", 1),
        ("identity_keys_payload", "TEXT", 0),
        ("account_ids_payload", "TEXT", 0),
        ("source_kind", "TEXT", 0),
        ("detected_at", "TEXT", 0),
    ),
    "account_evidence": (
        ("evidence_id", "TEXT", 1),
        ("fingerprint", "TEXT", 0),
        ("account_id", "TEXT", 0),
        ("conflict_id", "TEXT", 0),
        ("transaction_id", "TEXT", 0),
        ("receipt_payload", "TEXT", 0),
        ("processed_at", "TEXT", 0),
    ),
    "fact_journal": (
        ("fact_offset", "INTEGER", 1),
        ("transaction_id", "TEXT", 0),
        ("sequence", "INTEGER", 0),
        ("event_kind", "TEXT", 0),
        ("payload", "TEXT", 0),
        ("occurred_at", "TEXT", 0),
    ),
    "projection_checkpoint": (
        ("projector_id", "TEXT", 1),
        ("partition_id", "TEXT", 2),
        ("fact_offset", "INTEGER", 0),
        ("revision", "INTEGER", 0),
        ("updated_at", "TEXT", 0),
    ),
    "projection_record": (
        ("projector_id", "TEXT", 1),
        ("partition_id", "TEXT", 2),
        ("record_key", "TEXT", 3),
        ("revision", "INTEGER", 0),
        ("payload", "TEXT", 0),
        ("fact_offset", "INTEGER", 0),
        ("updated_at", "TEXT", 0),
    ),
    "notification_entry": (
        ("notification_id", "TEXT", 1),
        ("recipient_id", "TEXT", 0),
        ("kind_id", "TEXT", 0),
        ("dedupe_key", "TEXT", 0),
        ("priority", "INTEGER", 0),
        ("source_fact_offset", "INTEGER", 0),
        ("status", "TEXT", 0),
        ("payload", "TEXT", 0),
        ("created_at", "TEXT", 0),
        ("expires_at", "TEXT", 0),
        ("read_at", "TEXT", 0),
        ("revision", "INTEGER", 0),
    ),
    "ranking_snapshot": (
        ("board_id", "TEXT", 1),
        ("scope_id", "TEXT", 2),
        ("period_id", "TEXT", 3),
        ("version", "INTEGER", 4),
        ("fingerprint", "TEXT", 0),
        ("payload", "TEXT", 0),
        ("frozen_at", "TEXT", 0),
        ("through_fact_offset", "INTEGER", 0),
    ),
    "grant_campaign": (
        ("campaign_id", "TEXT", 1),
        ("version", "INTEGER", 0),
        ("issuer_id", "TEXT", 0),
        ("source_kind", "TEXT", 0),
        ("offer_id", "TEXT", 0),
        ("offer_version", "INTEGER", 0),
        ("policy", "TEXT", 0),
        ("per_account_limit", "INTEGER", 0),
        ("total_limit", "INTEGER", 0),
        ("starts_at", "TEXT", 0),
        ("ends_at", "TEXT", 0),
        ("status", "TEXT", 0),
        ("metadata_payload", "TEXT", 0),
        ("created_at", "TEXT", 0),
        ("updated_at", "TEXT", 0),
    ),
    "grant_credential": (
        ("credential_id", "TEXT", 1),
        ("campaign_id", "TEXT", 0),
        ("kind", "TEXT", 0),
        ("digest", "TEXT", 0),
        ("usage_limit", "INTEGER", 0),
        ("usage_count", "INTEGER", 0),
        ("bound_account_id", "TEXT", 0),
        ("expires_at", "TEXT", 0),
        ("external_reference", "TEXT", 0),
        ("status", "TEXT", 0),
        ("metadata_payload", "TEXT", 0),
        ("issued_at", "TEXT", 0),
        ("updated_at", "TEXT", 0),
    ),
    "grant_entitlement": (
        ("entitlement_id", "TEXT", 1),
        ("campaign_id", "TEXT", 0),
        ("credential_id", "TEXT", 0),
        ("account_id", "TEXT", 0),
        ("offer_id", "TEXT", 0),
        ("offer_version", "INTEGER", 0),
        ("status", "TEXT", 0),
        ("issued_at", "TEXT", 0),
        ("expires_at", "TEXT", 0),
        ("redeemed_at", "TEXT", 0),
        ("settlement_id", "TEXT", 0),
        ("metadata_payload", "TEXT", 0),
        ("updated_at", "TEXT", 0),
    ),
    "grant_redemption": (
        ("redemption_id", "TEXT", 1),
        ("entitlement_id", "TEXT", 0),
        ("campaign_id", "TEXT", 0),
        ("credential_id", "TEXT", 0),
        ("account_id", "TEXT", 0),
        ("settlement_id", "TEXT", 0),
        ("request_fingerprint", "TEXT", 0),
        ("receipt_payload", "TEXT", 0),
        ("redeemed_at", "TEXT", 0),
    ),
    "migration_manifest": (
        ("batch_id", "TEXT", 1),
        ("legacy_subject_id", "TEXT", 2),
        ("legacy_asset_id", "TEXT", 3),
        ("mapping_version", "TEXT", 0),
        ("target_account_id", "TEXT", 0),
        ("entitlement_id", "TEXT", 0),
        ("source_digest", "TEXT", 0),
        ("source_payload", "TEXT", 0),
        ("imported_at", "TEXT", 0),
    ),
    "battle_report": (
        ("report_id", "TEXT", 1),
        ("share_id", "TEXT", 0),
        ("mode_id", "TEXT", 0),
        ("content_fingerprint", "TEXT", 0),
        ("summary_payload", "TEXT", 0),
        ("started_at", "TEXT", 0),
        ("finished_at", "TEXT", 0),
        ("detail_expires_at", "TEXT", 0),
        ("summary_expires_at", "TEXT", 0),
        ("uncompressed_bytes", "INTEGER", 0),
        ("compressed_bytes", "INTEGER", 0),
        ("created_at", "TEXT", 0),
    ),
    "battle_report_segment": (
        ("report_id", "TEXT", 1),
        ("sequence", "INTEGER", 2),
        ("segment_id", "TEXT", 0),
        ("detail_payload", "BLOB", 0),
        ("uncompressed_bytes", "INTEGER", 0),
        ("compressed_bytes", "INTEGER", 0),
    ),
}

_SCHEMA_SQL = """
CREATE TABLE persistence_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE aggregate_snapshot (
    aggregate_kind TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    codec_version INTEGER NOT NULL CHECK (codec_version > 0),
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (aggregate_kind, aggregate_id)
) WITHOUT ROWID;

CREATE TABLE committed_transaction (
    transaction_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    receipt_payload TEXT NOT NULL,
    committed_at TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE content_activation (
    slot_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    fingerprint TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    packages_payload TEXT NOT NULL,
    activated_at TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE cycle_cursor (
    scope_id TEXT NOT NULL,
    cycle_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    scanned_through TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scope_id, cycle_id)
) WITHOUT ROWID;

CREATE TABLE cycle_work_item (
    scope_id TEXT NOT NULL,
    cycle_id TEXT NOT NULL,
    instance_id TEXT NOT NULL,
    transaction_id TEXT NOT NULL UNIQUE,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    available_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    lease_owner TEXT,
    lease_until TEXT,
    next_attempt_at TEXT,
    completed_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scope_id, cycle_id, instance_id),
    FOREIGN KEY (scope_id, cycle_id)
        REFERENCES cycle_cursor(scope_id, cycle_id)
        ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE INDEX cycle_work_claim_idx
ON cycle_work_item(status, next_attempt_at, available_at, lease_until, cycle_id);

CREATE TABLE account_record (
    account_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('active', 'suspended', 'closed')),
    revision INTEGER NOT NULL CHECK (revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE account_identity (
    provider_id TEXT NOT NULL,
    tenant_digest TEXT NOT NULL,
    subject_kind TEXT NOT NULL,
    scope_digest TEXT NOT NULL,
    identity_digest TEXT NOT NULL,
    account_id TEXT NOT NULL,
    bound_at TEXT NOT NULL,
    source_evidence_id TEXT NOT NULL,
    PRIMARY KEY (
        provider_id, tenant_digest, subject_kind, scope_digest, identity_digest
    ),
    FOREIGN KEY (account_id) REFERENCES account_record(account_id) ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE INDEX account_identity_account_idx
ON account_identity(account_id, bound_at);

CREATE TABLE account_conflict (
    conflict_id TEXT PRIMARY KEY,
    identity_keys_payload TEXT NOT NULL,
    account_ids_payload TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    detected_at TEXT NOT NULL
) WITHOUT ROWID;

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
        REFERENCES committed_transaction(transaction_id)
        ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE INDEX account_evidence_account_idx
ON account_evidence(account_id, processed_at);

CREATE TABLE fact_journal (
    fact_offset INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    event_kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    UNIQUE(transaction_id, sequence),
    FOREIGN KEY (transaction_id)
        REFERENCES committed_transaction(transaction_id)
        ON DELETE RESTRICT
);

CREATE INDEX fact_journal_kind_idx
ON fact_journal(event_kind, fact_offset);

CREATE TABLE projection_checkpoint (
    projector_id TEXT NOT NULL,
    partition_id TEXT NOT NULL,
    fact_offset INTEGER NOT NULL DEFAULT 0 CHECK (fact_offset >= 0),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (projector_id, partition_id)
) WITHOUT ROWID;

CREATE TABLE projection_record (
    projector_id TEXT NOT NULL,
    partition_id TEXT NOT NULL,
    record_key TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    payload TEXT NOT NULL,
    fact_offset INTEGER NOT NULL CHECK (fact_offset >= 0),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (projector_id, partition_id, record_key),
    FOREIGN KEY (projector_id, partition_id)
        REFERENCES projection_checkpoint(projector_id, partition_id)
        ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE TABLE notification_entry (
    notification_id TEXT PRIMARY KEY,
    recipient_id TEXT NOT NULL,
    kind_id TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    priority INTEGER NOT NULL,
    source_fact_offset INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('unread', 'read', 'dismissed')),
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    read_at TEXT,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    UNIQUE(recipient_id, dedupe_key),
    FOREIGN KEY (source_fact_offset) REFERENCES fact_journal(fact_offset) ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE INDEX notification_inbox_idx
ON notification_entry(recipient_id, status, priority DESC, created_at);

CREATE TABLE ranking_snapshot (
    board_id TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    period_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    fingerprint TEXT NOT NULL,
    payload TEXT NOT NULL,
    frozen_at TEXT NOT NULL,
    through_fact_offset INTEGER NOT NULL CHECK (through_fact_offset >= 0),
    PRIMARY KEY (board_id, scope_id, period_id, version)
) WITHOUT ROWID;

CREATE TABLE grant_campaign (
    campaign_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL CHECK (version > 0),
    issuer_id TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    offer_id TEXT NOT NULL,
    offer_version INTEGER NOT NULL CHECK (offer_version > 0),
    policy TEXT NOT NULL CHECK (policy IN ('single_use', 'per_account', 'quota')),
    per_account_limit INTEGER NOT NULL CHECK (per_account_limit > 0),
    total_limit INTEGER CHECK (total_limit IS NULL OR total_limit > 0),
    starts_at TEXT NOT NULL,
    ends_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'revoked')),
    metadata_payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) WITHOUT ROWID;

CREATE INDEX grant_campaign_status_idx
ON grant_campaign(status, starts_at, ends_at);

CREATE TABLE grant_credential (
    credential_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('code', 'signed_receipt')),
    digest TEXT NOT NULL,
    usage_limit INTEGER CHECK (usage_limit IS NULL OR usage_limit > 0),
    usage_count INTEGER NOT NULL DEFAULT 0 CHECK (usage_count >= 0),
    bound_account_id TEXT,
    expires_at TEXT,
    external_reference TEXT,
    status TEXT NOT NULL CHECK (status IN ('active', 'revoked')),
    metadata_payload TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (campaign_id) REFERENCES grant_campaign(campaign_id) ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE UNIQUE INDEX grant_credential_digest_idx
ON grant_credential(campaign_id, digest);

CREATE UNIQUE INDEX grant_credential_external_idx
ON grant_credential(campaign_id, external_reference)
WHERE external_reference IS NOT NULL;

CREATE TABLE grant_entitlement (
    entitlement_id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL,
    credential_id TEXT,
    account_id TEXT NOT NULL,
    offer_id TEXT NOT NULL,
    offer_version INTEGER NOT NULL CHECK (offer_version > 0),
    status TEXT NOT NULL CHECK (status IN ('available', 'redeemed', 'revoked')),
    issued_at TEXT NOT NULL,
    expires_at TEXT,
    redeemed_at TEXT,
    settlement_id TEXT UNIQUE,
    metadata_payload TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (campaign_id) REFERENCES grant_campaign(campaign_id) ON DELETE RESTRICT,
    FOREIGN KEY (credential_id) REFERENCES grant_credential(credential_id) ON DELETE RESTRICT,
    FOREIGN KEY (settlement_id) REFERENCES committed_transaction(transaction_id) ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE INDEX grant_entitlement_account_idx
ON grant_entitlement(account_id, status, campaign_id, issued_at);

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
) WITHOUT ROWID;

CREATE INDEX grant_redemption_account_idx
ON grant_redemption(campaign_id, account_id, redeemed_at);

CREATE TABLE migration_manifest (
    batch_id TEXT NOT NULL,
    legacy_subject_id TEXT NOT NULL,
    legacy_asset_id TEXT NOT NULL,
    mapping_version TEXT NOT NULL,
    target_account_id TEXT NOT NULL,
    entitlement_id TEXT NOT NULL UNIQUE,
    source_digest TEXT NOT NULL,
    source_payload TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    PRIMARY KEY (batch_id, legacy_subject_id, legacy_asset_id),
    FOREIGN KEY (entitlement_id) REFERENCES grant_entitlement(entitlement_id) ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE TABLE battle_report (
    report_id TEXT PRIMARY KEY,
    share_id TEXT NOT NULL UNIQUE,
    mode_id TEXT NOT NULL,
    content_fingerprint TEXT NOT NULL,
    summary_payload TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    detail_expires_at TEXT NOT NULL,
    summary_expires_at TEXT NOT NULL,
    uncompressed_bytes INTEGER NOT NULL CHECK (uncompressed_bytes >= 0),
    compressed_bytes INTEGER NOT NULL CHECK (compressed_bytes >= 0),
    created_at TEXT NOT NULL
) WITHOUT ROWID;

CREATE INDEX battle_report_expiry_idx
ON battle_report(summary_expires_at, detail_expires_at);

CREATE TABLE battle_report_segment (
    report_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    segment_id TEXT NOT NULL,
    detail_payload BLOB NOT NULL,
    uncompressed_bytes INTEGER NOT NULL CHECK (uncompressed_bytes >= 0),
    compressed_bytes INTEGER NOT NULL CHECK (compressed_bytes >= 0),
    PRIMARY KEY (report_id, sequence),
    UNIQUE (report_id, segment_id),
    FOREIGN KEY (report_id) REFERENCES battle_report(report_id) ON DELETE CASCADE
) WITHOUT ROWID;

CREATE TABLE outbox_event (
    transaction_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    event_kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_at TEXT,
    PRIMARY KEY (transaction_id, sequence),
    FOREIGN KEY (transaction_id)
        REFERENCES committed_transaction(transaction_id)
        ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE INDEX outbox_event_pending_idx
ON outbox_event(published_at, created_at, transaction_id, sequence);
"""


@dataclass(frozen=True)
class AggregateSnapshotRow:
    aggregate_kind: str
    aggregate_id: str
    revision: int
    codec_version: int
    payload: str
    updated_at: str


@dataclass(frozen=True)
class CommittedTransactionRow:
    transaction_id: str
    fingerprint: str
    scope_id: str
    receipt_payload: str
    committed_at: str


@dataclass(frozen=True)
class OutboxEventRow:
    transaction_id: str
    sequence: int
    event_kind: str
    payload: str
    created_at: str
    published_at: str | None


@dataclass(frozen=True)
class ContentActivationRow:
    slot_id: str
    revision: int
    fingerprint: str
    profile_id: str
    packages_payload: str
    activated_at: str


@dataclass(frozen=True)
class CycleCursorRow:
    scope_id: str
    cycle_id: str
    revision: int
    scanned_through: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class CycleWorkItemRow:
    scope_id: str
    cycle_id: str
    instance_id: str
    transaction_id: str
    window_start: str
    window_end: str
    available_at: str
    status: str
    attempt_count: int
    lease_owner: str | None
    lease_until: str | None
    next_attempt_at: str | None
    completed_at: str | None
    last_error: str | None
    created_at: str
    updated_at: str


class SqliteDatabase:
    """每个工作单元独占一个连接，不在模块中保存全局游标。"""

    def __init__(self, path: Path | str, *, busy_timeout_ms: int = 5_000) -> None:
        self.path = Path(path)
        if busy_timeout_ms < 1:
            raise ValueError("busy_timeout_ms 必须大于 0")
        self.busy_timeout_ms = busy_timeout_ms

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self.connect()
        try:
            tables = _table_names(connection)
            if "persistence_metadata" not in tables:
                if tables:
                    raise SchemaVersionError(
                        "数据库包含未知结构，拒绝按万象行纪正式数据库初始化"
                    )
                try:
                    connection.executescript(
                        "BEGIN EXCLUSIVE;\n"
                        + _SCHEMA_SQL
                        + "\nINSERT INTO persistence_metadata(key, value) VALUES "
                        + f"('schema_version', '{PERSISTENCE_SCHEMA_VERSION}');\n"
                        + "COMMIT;"
                    )
                except Exception:
                    connection.rollback()
                    raise
                _validate_schema_shape(connection)
                return
            missing = _REQUIRED_TABLES - tables
            if missing:
                raise SchemaVersionError(
                    f"数据库结构不完整，缺少表：{', '.join(sorted(missing))}"
                )
            row = connection.execute(
                "SELECT value FROM persistence_metadata WHERE key = ?",
                ("schema_version",),
            ).fetchone()
            if row is None or row[0] != str(PERSISTENCE_SCHEMA_VERSION):
                actual = row[0] if row else "missing"
                raise SchemaVersionError(
                    f"数据库结构版本不匹配：需要 {PERSISTENCE_SCHEMA_VERSION}，当前 {actual}"
                )
            _validate_schema_shape(connection)
        finally:
            connection.close()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            isolation_level=None,
            timeout=self.busy_timeout_ms / 1000,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def unit_of_work(self, *, write: bool = True) -> "SqliteUnitOfWork":
        return SqliteUnitOfWork(self.connect(), write=write)


class SqliteUnitOfWork:
    """只有显式调用 commit() 才提交，离开上下文默认回滚。"""

    def __init__(self, connection: sqlite3.Connection, *, write: bool = True) -> None:
        self.connection = connection
        self.write = write
        self._committed = False
        self._entered = False

    def __enter__(self) -> "SqliteUnitOfWork":
        if self._entered:
            raise RuntimeError("SqliteUnitOfWork 不能重复进入")
        self.connection.execute("BEGIN IMMEDIATE" if self.write else "BEGIN DEFERRED")
        self._entered = True
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        try:
            if not self._committed:
                self.connection.rollback()
        finally:
            self.connection.close()

    def commit(self) -> None:
        if not self._entered or self._committed:
            raise RuntimeError("工作单元尚未开始或已经提交")
        self.connection.commit()
        self._committed = True

    def load_snapshot(
        self,
        aggregate_kind: str,
        aggregate_id: str,
    ) -> AggregateSnapshotRow | None:
        row = self.connection.execute(
            """
            SELECT aggregate_kind, aggregate_id, revision, codec_version, payload, updated_at
            FROM aggregate_snapshot
            WHERE aggregate_kind = ? AND aggregate_id = ?
            """,
            (aggregate_kind, aggregate_id),
        ).fetchone()
        return AggregateSnapshotRow(**dict(row)) if row else None

    def require_snapshot(self, aggregate_kind: str, aggregate_id: str) -> AggregateSnapshotRow:
        row = self.load_snapshot(aggregate_kind, aggregate_id)
        if row is None:
            raise AggregateNotFound(f"缺少聚合快照：{aggregate_kind}/{aggregate_id}")
        return row

    def list_snapshots(
        self,
        aggregate_kind: str,
        *,
        limit: int = 1_000,
    ) -> tuple[AggregateSnapshotRow, ...]:
        """按稳定聚合类型列出快照，供业务调度器发现待处理实例。"""

        if not aggregate_kind.strip() or limit < 1:
            raise ValueError("聚合类型不能为空且 limit 必须大于 0")
        rows = self.connection.execute(
            """
            SELECT aggregate_kind, aggregate_id, revision, codec_version, payload, updated_at
            FROM aggregate_snapshot
            WHERE aggregate_kind = ?
            ORDER BY aggregate_id
            LIMIT ?
            """,
            (aggregate_kind, limit),
        ).fetchall()
        return tuple(AggregateSnapshotRow(**dict(row)) for row in rows)

    def insert_snapshot(
        self,
        aggregate_kind: str,
        aggregate_id: str,
        revision: int,
        payload: str,
        updated_at: str,
    ) -> None:
        if revision < 0:
            raise ValueError("聚合初始 revision 不能小于 0")
        try:
            self.connection.execute(
                """
                INSERT INTO aggregate_snapshot(
                    aggregate_kind, aggregate_id, revision, codec_version, payload, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    aggregate_kind,
                    aggregate_id,
                    revision,
                    SNAPSHOT_CODEC_VERSION,
                    payload,
                    updated_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConcurrencyConflict(
                f"聚合快照已经存在：{aggregate_kind}/{aggregate_id}"
            ) from exc

    def compare_and_swap_snapshot(
        self,
        aggregate_kind: str,
        aggregate_id: str,
        expected_revision: int,
        new_revision: int,
        payload: str,
        updated_at: str,
    ) -> None:
        if new_revision != expected_revision + 1:
            raise ValueError("聚合条件更新必须恰好增加一个 revision")
        cursor = self.connection.execute(
            """
            UPDATE aggregate_snapshot
            SET revision = ?, codec_version = ?, payload = ?, updated_at = ?
            WHERE aggregate_kind = ? AND aggregate_id = ? AND revision = ?
            """,
            (
                new_revision,
                SNAPSHOT_CODEC_VERSION,
                payload,
                updated_at,
                aggregate_kind,
                aggregate_id,
                expected_revision,
            ),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(
                f"聚合 revision 冲突：{aggregate_kind}/{aggregate_id} expected={expected_revision}"
            )

    def load_transaction(self, transaction_id: str) -> CommittedTransactionRow | None:
        row = self.connection.execute(
            """
            SELECT transaction_id, fingerprint, scope_id, receipt_payload, committed_at
            FROM committed_transaction
            WHERE transaction_id = ?
            """,
            (transaction_id,),
        ).fetchone()
        return CommittedTransactionRow(**dict(row)) if row else None

    def load_content_activation(self, slot_id: str) -> ContentActivationRow | None:
        row = self.connection.execute(
            """
            SELECT slot_id, revision, fingerprint, profile_id, packages_payload, activated_at
            FROM content_activation
            WHERE slot_id = ?
            """,
            (slot_id,),
        ).fetchone()
        return ContentActivationRow(**dict(row)) if row else None

    def insert_content_activation(
        self,
        slot_id: str,
        fingerprint: str,
        profile_id: str,
        packages_payload: str,
        activated_at: str,
    ) -> None:
        try:
            self.connection.execute(
                """
                INSERT INTO content_activation(
                    slot_id, revision, fingerprint, profile_id, packages_payload, activated_at
                ) VALUES (?, 0, ?, ?, ?, ?)
                """,
                (slot_id, fingerprint, profile_id, packages_payload, activated_at),
            )
        except sqlite3.IntegrityError as exc:
            raise ConcurrencyConflict(f"内容激活槽已经存在：{slot_id}") from exc

    def compare_and_swap_content_activation(
        self,
        slot_id: str,
        expected_revision: int,
        expected_fingerprint: str,
        fingerprint: str,
        profile_id: str,
        packages_payload: str,
        activated_at: str,
    ) -> None:
        cursor = self.connection.execute(
            """
            UPDATE content_activation
            SET revision = revision + 1,
                fingerprint = ?,
                profile_id = ?,
                packages_payload = ?,
                activated_at = ?
            WHERE slot_id = ? AND revision = ? AND fingerprint = ?
            """,
            (
                fingerprint,
                profile_id,
                packages_payload,
                activated_at,
                slot_id,
                expected_revision,
                expected_fingerprint,
            ),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(
                f"内容激活槽 revision 或指纹冲突：{slot_id}"
            )

    def load_cycle_cursor(self, scope_id: str, cycle_id: str) -> CycleCursorRow | None:
        row = self.connection.execute(
            """
            SELECT scope_id, cycle_id, revision, scanned_through, created_at, updated_at
            FROM cycle_cursor
            WHERE scope_id = ? AND cycle_id = ?
            """,
            (scope_id, cycle_id),
        ).fetchone()
        return CycleCursorRow(**dict(row)) if row else None

    def insert_cycle_cursor(
        self,
        scope_id: str,
        cycle_id: str,
        scanned_through: str,
        created_at: str,
    ) -> None:
        try:
            self.connection.execute(
                """
                INSERT INTO cycle_cursor(
                    scope_id, cycle_id, revision, scanned_through, created_at, updated_at
                ) VALUES (?, ?, 0, ?, ?, ?)
                """,
                (scope_id, cycle_id, scanned_through, created_at, created_at),
            )
        except sqlite3.IntegrityError as exc:
            raise ConcurrencyConflict(
                f"周期游标已经存在：{scope_id}/{cycle_id}"
            ) from exc

    def advance_cycle_cursor(
        self,
        scope_id: str,
        cycle_id: str,
        expected_revision: int,
        scanned_through: str,
        updated_at: str,
    ) -> None:
        cursor = self.connection.execute(
            """
            UPDATE cycle_cursor
            SET revision = revision + 1,
                scanned_through = ?,
                updated_at = ?
            WHERE scope_id = ? AND cycle_id = ? AND revision = ?
            """,
            (scanned_through, updated_at, scope_id, cycle_id, expected_revision),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(
                f"周期游标 revision 冲突：{scope_id}/{cycle_id}"
            )

    def insert_cycle_work_item(self, row: CycleWorkItemRow) -> None:
        try:
            self.connection.execute(
                """
                INSERT INTO cycle_work_item(
                    scope_id, cycle_id, instance_id, transaction_id,
                    window_start, window_end, available_at, status,
                    attempt_count, lease_owner, lease_until, next_attempt_at,
                    completed_at, last_error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.scope_id,
                    row.cycle_id,
                    row.instance_id,
                    row.transaction_id,
                    row.window_start,
                    row.window_end,
                    row.available_at,
                    row.status,
                    row.attempt_count,
                    row.lease_owner,
                    row.lease_until,
                    row.next_attempt_at,
                    row.completed_at,
                    row.last_error,
                    row.created_at,
                    row.updated_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConcurrencyConflict(
                f"周期工作项重复：{row.scope_id}/{row.cycle_id}/{row.instance_id}"
            ) from exc

    def load_cycle_work_item(self, transaction_id: str) -> CycleWorkItemRow | None:
        row = self.connection.execute(
            """
            SELECT scope_id, cycle_id, instance_id, transaction_id,
                   window_start, window_end, available_at, status,
                   attempt_count, lease_owner, lease_until, next_attempt_at,
                   completed_at, last_error, created_at, updated_at
            FROM cycle_work_item
            WHERE transaction_id = ?
            """,
            (transaction_id,),
        ).fetchone()
        return CycleWorkItemRow(**dict(row)) if row else None

    def claim_cycle_work_item(
        self,
        worker_id: str,
        logical_time: str,
        lease_until: str,
        cycle_id: str | None = None,
    ) -> CycleWorkItemRow | None:
        parameters: list[object] = [logical_time, logical_time, logical_time]
        cycle_filter = ""
        if cycle_id is not None:
            cycle_filter = " AND cycle_id = ?"
            parameters.append(cycle_id)
        row = self.connection.execute(
            f"""
            SELECT scope_id, cycle_id, instance_id, transaction_id,
                   window_start, window_end, available_at, status,
                   attempt_count, lease_owner, lease_until, next_attempt_at,
                   completed_at, last_error, created_at, updated_at
            FROM cycle_work_item
            WHERE (
                (status = 'pending' AND COALESCE(next_attempt_at, available_at) <= ?)
                OR
                (status = 'running' AND lease_until <= ?)
            )
            AND updated_at <= ?
            {cycle_filter}
            ORDER BY COALESCE(next_attempt_at, available_at), cycle_id, instance_id
            LIMIT 1
            """,
            tuple(parameters),
        ).fetchone()
        if row is None:
            return None
        transaction_id = str(row["transaction_id"])
        cursor = self.connection.execute(
            """
            UPDATE cycle_work_item
            SET status = 'running',
                attempt_count = attempt_count + 1,
                lease_owner = ?,
                lease_until = ?,
                next_attempt_at = NULL,
                updated_at = ?
            WHERE transaction_id = ?
              AND (
                  (status = 'pending' AND COALESCE(next_attempt_at, available_at) <= ?)
                  OR
                  (status = 'running' AND lease_until <= ?)
              )
              AND updated_at <= ?
            """,
            (
                worker_id,
                lease_until,
                logical_time,
                transaction_id,
                logical_time,
                logical_time,
                logical_time,
            ),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(f"周期工作项抢占冲突：{transaction_id}")
        claimed = self.load_cycle_work_item(transaction_id)
        assert claimed is not None
        return claimed

    def heartbeat_cycle_work_item(
        self,
        transaction_id: str,
        worker_id: str,
        lease_until: str,
        updated_at: str,
    ) -> None:
        cursor = self.connection.execute(
            """
            UPDATE cycle_work_item
            SET lease_until = ?, updated_at = ?
            WHERE transaction_id = ? AND status = 'running' AND lease_owner = ?
              AND lease_until > ?
              AND lease_until < ?
              AND updated_at <= ?
            """,
            (
                lease_until,
                updated_at,
                transaction_id,
                worker_id,
                updated_at,
                lease_until,
                updated_at,
            ),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(f"周期工作项租约不属于当前执行器：{transaction_id}")

    def complete_cycle_work_item(
        self,
        transaction_id: str,
        worker_id: str,
        completed_at: str,
    ) -> None:
        cursor = self.connection.execute(
            """
            UPDATE cycle_work_item
            SET status = 'completed',
                lease_owner = NULL,
                lease_until = NULL,
                completed_at = ?,
                last_error = NULL,
                updated_at = ?
            WHERE transaction_id = ? AND status = 'running' AND lease_owner = ?
              AND lease_until > ?
              AND updated_at <= ?
            """,
            (
                completed_at,
                completed_at,
                transaction_id,
                worker_id,
                completed_at,
                completed_at,
            ),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(f"周期工作项无法由当前执行器完成：{transaction_id}")

    def retry_cycle_work_item(
        self,
        transaction_id: str,
        worker_id: str,
        retry_at: str,
        error: str,
        updated_at: str,
    ) -> None:
        cursor = self.connection.execute(
            """
            UPDATE cycle_work_item
            SET status = 'pending',
                lease_owner = NULL,
                lease_until = NULL,
                next_attempt_at = ?,
                last_error = ?,
                updated_at = ?
            WHERE transaction_id = ? AND status = 'running' AND lease_owner = ?
              AND lease_until > ?
              AND updated_at <= ?
            """,
            (
                retry_at,
                error,
                updated_at,
                transaction_id,
                worker_id,
                updated_at,
                updated_at,
            ),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(f"周期工作项无法由当前执行器重试：{transaction_id}")

    def fail_cycle_work_item(
        self,
        transaction_id: str,
        worker_id: str,
        error: str,
        updated_at: str,
    ) -> None:
        cursor = self.connection.execute(
            """
            UPDATE cycle_work_item
            SET status = 'failed',
                lease_owner = NULL,
                lease_until = NULL,
                next_attempt_at = NULL,
                last_error = ?,
                updated_at = ?
            WHERE transaction_id = ? AND status = 'running' AND lease_owner = ?
              AND lease_until > ?
              AND updated_at <= ?
            """,
            (
                error,
                updated_at,
                transaction_id,
                worker_id,
                updated_at,
                updated_at,
            ),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(f"周期工作项无法由当前执行器终止：{transaction_id}")

    def requeue_failed_cycle_work_item(
        self,
        transaction_id: str,
        retry_at: str,
        updated_at: str,
    ) -> None:
        cursor = self.connection.execute(
            """
            UPDATE cycle_work_item
            SET status = 'pending',
                next_attempt_at = ?,
                completed_at = NULL,
                updated_at = ?
            WHERE transaction_id = ? AND status = 'failed' AND updated_at <= ?
            """,
            (retry_at, updated_at, transaction_id, updated_at),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(f"周期失败工作项无法重新排队：{transaction_id}")

    def insert_transaction(
        self,
        transaction_id: str,
        fingerprint: str,
        scope_id: str,
        receipt_payload: str,
        committed_at: str,
    ) -> None:
        previous = self.load_transaction(transaction_id)
        if previous is not None:
            if previous.fingerprint != fingerprint or previous.scope_id != scope_id:
                raise TransactionMismatch(
                    f"同一持久化事务 ID 对应不同内容：{transaction_id}"
                )
            raise ConcurrencyConflict(f"持久化事务已经提交：{transaction_id}")
        self.connection.execute(
            """
            INSERT INTO committed_transaction(
                transaction_id, fingerprint, scope_id, receipt_payload, committed_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (transaction_id, fingerprint, scope_id, receipt_payload, committed_at),
        )

    def append_fact(
        self,
        transaction_id: str,
        sequence: int,
        event_kind: str,
        payload: str,
        occurred_at: str,
    ) -> None:
        """追加已经提交的领域事实，不隐式创建外部投递。"""

        try:
            self.connection.execute(
                """
                INSERT INTO fact_journal(
                    transaction_id, sequence, event_kind, payload, occurred_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (transaction_id, sequence, event_kind, payload, occurred_at),
            )
        except sqlite3.IntegrityError as exc:
            raise ConcurrencyConflict(
                f"领域事实已经存在：{transaction_id}/{sequence}"
            ) from exc

    def enqueue_outbox(
        self,
        transaction_id: str,
        sequence: int,
        event_kind: str,
        payload: str,
        created_at: str,
    ) -> None:
        """只为明确登记的外部消费者创建投递记录。"""

        try:
            self.connection.execute(
                """
                INSERT INTO outbox_event(
                    transaction_id, sequence, event_kind, payload, created_at, published_at
                ) VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (transaction_id, sequence, event_kind, payload, created_at),
            )
        except sqlite3.IntegrityError as exc:
            raise ConcurrencyConflict(
                f"外部投递已经存在：{transaction_id}/{sequence}"
            ) from exc

    def pending_outbox(self, *, limit: int = 100) -> tuple[OutboxEventRow, ...]:
        if limit < 1:
            raise ValueError("Outbox 查询 limit 必须大于 0")
        rows = self.connection.execute(
            """
            SELECT transaction_id, sequence, event_kind, payload, created_at, published_at
            FROM outbox_event
            WHERE published_at IS NULL
            ORDER BY created_at, transaction_id, sequence
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return tuple(OutboxEventRow(**dict(row)) for row in rows)

    def mark_outbox_published(
        self,
        transaction_id: str,
        sequence: int,
        published_at: str,
    ) -> None:
        cursor = self.connection.execute(
            """
            UPDATE outbox_event
            SET published_at = ?
            WHERE transaction_id = ? AND sequence = ? AND published_at IS NULL
            """,
            (published_at, transaction_id, sequence),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(
                f"Outbox 事件不存在或已经发布：{transaction_id}/{sequence}"
            )


def _table_names(connection: sqlite3.Connection) -> frozenset[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return frozenset(str(row[0]) for row in rows)


def _validate_schema_shape(connection: sqlite3.Connection) -> None:
    for table, expected in _EXPECTED_COLUMNS.items():
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
        actual = tuple((str(row[1]), str(row[2]).upper(), int(row[5])) for row in rows)
        if actual != expected:
            raise SchemaVersionError(f"数据库表结构与当前版本不一致：{table}")
    indexes = {
        str(row[1])
        for row in connection.execute("PRAGMA index_list(outbox_event)").fetchall()
    }
    if "outbox_event_pending_idx" not in indexes:
        raise SchemaVersionError("数据库缺少 Outbox 待发布索引")
    cycle_indexes = {
        str(row[1])
        for row in connection.execute("PRAGMA index_list(cycle_work_item)").fetchall()
    }
    if "cycle_work_claim_idx" not in cycle_indexes:
        raise SchemaVersionError("数据库缺少周期工作项领取索引")
    required_account_indexes = {
        "account_identity": {"account_identity_account_idx"},
        "account_evidence": {"account_evidence_account_idx"},
    }
    for table, expected_indexes in required_account_indexes.items():
        actual_indexes = {
            str(row[1])
            for row in connection.execute(f"PRAGMA index_list({table})").fetchall()
        }
        if not expected_indexes.issubset(actual_indexes):
            raise SchemaVersionError(f"数据库缺少账号索引：{table}")
    required_projection_indexes = {
        "fact_journal": {"fact_journal_kind_idx"},
        "notification_entry": {"notification_inbox_idx"},
    }
    for table, expected_indexes in required_projection_indexes.items():
        actual_indexes = {
            str(row[1])
            for row in connection.execute(f"PRAGMA index_list({table})").fetchall()
        }
        if not expected_indexes.issubset(actual_indexes):
            raise SchemaVersionError(f"数据库缺少事实投影索引：{table}")
    required_grant_indexes = {
        "grant_campaign": {"grant_campaign_status_idx"},
        "grant_credential": {
            "grant_credential_digest_idx",
            "grant_credential_external_idx",
        },
        "grant_entitlement": {"grant_entitlement_account_idx"},
        "grant_redemption": {"grant_redemption_account_idx"},
    }
    for table, expected_indexes in required_grant_indexes.items():
        actual_indexes = {
            str(row[1])
            for row in connection.execute(f"PRAGMA index_list({table})").fetchall()
        }
        missing_indexes = expected_indexes - actual_indexes
        if missing_indexes:
            raise SchemaVersionError(
                f"数据库缺少权益索引：{', '.join(sorted(missing_indexes))}"
            )
    report_indexes = {
        str(row[1])
        for row in connection.execute("PRAGMA index_list(battle_report)").fetchall()
    }
    if "battle_report_expiry_idx" not in report_indexes:
        raise SchemaVersionError("数据库缺少战报保留期索引")
    foreign_keys = connection.execute("PRAGMA foreign_key_list(outbox_event)").fetchall()
    if not any(
        str(row[2]) == "committed_transaction"
        and str(row[3]) == "transaction_id"
        and str(row[4]) == "transaction_id"
        for row in foreign_keys
    ):
        raise SchemaVersionError("Outbox 事务外键结构不正确")
    cycle_foreign_keys = connection.execute(
        "PRAGMA foreign_key_list(cycle_work_item)"
    ).fetchall()
    cycle_cursor_columns = {
        (str(row[3]), str(row[4]))
        for row in cycle_foreign_keys
        if str(row[2]) == "cycle_cursor"
    }
    if cycle_cursor_columns != {
        ("scope_id", "scope_id"),
        ("cycle_id", "cycle_id"),
    }:
        raise SchemaVersionError("周期工作项游标复合外键结构不正确")
    report_foreign_keys = connection.execute(
        "PRAGMA foreign_key_list(battle_report_segment)"
    ).fetchall()
    if not any(
        str(row[2]) == "battle_report"
        and str(row[3]) == "report_id"
        and str(row[4]) == "report_id"
        and str(row[6]).upper() == "CASCADE"
        for row in report_foreign_keys
    ):
        raise SchemaVersionError("战报片段外键结构不正确")
    expected_account_foreign_keys = {
        "account_identity": {
            ("account_id", "account_record", "account_id"),
        },
        "account_evidence": {
            ("account_id", "account_record", "account_id"),
            ("conflict_id", "account_conflict", "conflict_id"),
            ("transaction_id", "committed_transaction", "transaction_id"),
        },
    }
    for table, expected_keys in expected_account_foreign_keys.items():
        actual_keys = {
            (str(row[3]), str(row[2]), str(row[4]))
            for row in connection.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        }
        if actual_keys != expected_keys:
            raise SchemaVersionError(f"账号表外键结构不正确：{table}")
    expected_projection_foreign_keys = {
        "fact_journal": {
            ("transaction_id", "committed_transaction", "transaction_id"),
        },
        "projection_record": {
            ("projector_id", "projection_checkpoint", "projector_id"),
            ("partition_id", "projection_checkpoint", "partition_id"),
        },
        "notification_entry": {
            ("source_fact_offset", "fact_journal", "fact_offset"),
        },
    }
    for table, expected_keys in expected_projection_foreign_keys.items():
        actual_keys = {
            (str(row[3]), str(row[2]), str(row[4]))
            for row in connection.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        }
        if actual_keys != expected_keys:
            raise SchemaVersionError(f"事实投影表外键结构不正确：{table}")
    expected_grant_foreign_keys = {
        "grant_credential": {
            ("campaign_id", "grant_campaign", "campaign_id"),
        },
        "grant_entitlement": {
            ("campaign_id", "grant_campaign", "campaign_id"),
            ("credential_id", "grant_credential", "credential_id"),
            ("settlement_id", "committed_transaction", "transaction_id"),
        },
        "grant_redemption": {
            ("entitlement_id", "grant_entitlement", "entitlement_id"),
            ("campaign_id", "grant_campaign", "campaign_id"),
            ("credential_id", "grant_credential", "credential_id"),
            ("settlement_id", "committed_transaction", "transaction_id"),
        },
        "migration_manifest": {
            ("entitlement_id", "grant_entitlement", "entitlement_id"),
        },
    }
    for table, expected_keys in expected_grant_foreign_keys.items():
        actual_keys = {
            (str(row[3]), str(row[2]), str(row[4]))
            for row in connection.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        }
        if actual_keys != expected_keys:
            raise SchemaVersionError(f"权益表外键结构不正确：{table}")


__all__ = [
    "AggregateSnapshotRow",
    "CommittedTransactionRow",
    "ContentActivationRow",
    "CycleCursorRow",
    "CycleWorkItemRow",
    "OutboxEventRow",
    "PERSISTENCE_SCHEMA_VERSION",
    "SNAPSHOT_CODEC_VERSION",
    "SqliteDatabase",
    "SqliteUnitOfWork",
]
