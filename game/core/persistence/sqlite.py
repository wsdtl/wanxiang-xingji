"""SQLite 结构版本、CAS 聚合仓储、事务防重和 Outbox。"""

from __future__ import annotations

from contextlib import closing, suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import zlib

from .errors import (
    AggregateNotFound,
    ConcurrencyConflict,
    CorruptPersistenceData,
    SchemaVersionError,
    TransactionMismatch,
)


PERSISTENCE_SCHEMA_VERSION = 8
PREVIOUS_PERSISTENCE_SCHEMA_VERSION = 7
SNAPSHOT_CODEC_VERSION = 1
_RECEIPT_CODEC_HEADER = b"zlib.v1\0"


def _encode_receipt_payload(payload: str) -> bytes:
    if not isinstance(payload, str):
        raise TypeError("事务回执必须是字符串")
    return _RECEIPT_CODEC_HEADER + zlib.compress(payload.encode("utf-8"), level=9)


def _decode_receipt_payload(payload: object) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, memoryview):
        payload = payload.tobytes()
    if not isinstance(payload, bytes) or not payload.startswith(_RECEIPT_CODEC_HEADER):
        raise CorruptPersistenceData("事务回执压缩格式无效")
    try:
        return zlib.decompress(payload[len(_RECEIPT_CODEC_HEADER) :]).decode("utf-8")
    except (UnicodeDecodeError, zlib.error) as exc:
        raise CorruptPersistenceData("事务回执压缩数据损坏") from exc

_REQUIRED_TABLES = frozenset(
    {
        "persistence_metadata",
        "aggregate_snapshot",
        "ledger_transaction",
        "ledger_journal_entry",
        "reward_claim",
        "party_membership",
        "world_presence",
        "world_reservation",
        "market_listing",
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
        ("expires_at", "TEXT", 0),
    ),
    "ledger_transaction": (
        ("ledger_id", "TEXT", 1),
        ("transaction_id", "TEXT", 2),
        ("fingerprint", "TEXT", 0),
        ("resulting_revision", "INTEGER", 0),
        ("applied_at", "TEXT", 0),
    ),
    "ledger_journal_entry": (
        ("ledger_id", "TEXT", 1),
        ("entry_id", "TEXT", 2),
        ("transaction_id", "TEXT", 0),
        ("currency_id", "TEXT", 0),
        ("reason", "TEXT", 0),
        ("actor_id", "TEXT", 0),
        ("logical_time", "TEXT", 0),
        ("payload", "TEXT", 0),
    ),
    "reward_claim": (
        ("scope_id", "TEXT", 1),
        ("settlement_id", "TEXT", 2),
        ("fingerprint", "TEXT", 0),
        ("resulting_revision", "INTEGER", 0),
        ("claimed_at", "TEXT", 0),
    ),
    "party_membership": (
        ("subject_id", "TEXT", 1),
        ("party_id", "TEXT", 0),
        ("party_scope_id", "TEXT", 0),
        ("joined_at", "TEXT", 0),
    ),
    "world_presence": (
        ("world_id", "TEXT", 1),
        ("presence_id", "TEXT", 2),
        ("owner_id", "TEXT", 0),
        ("revision", "INTEGER", 0),
        ("payload", "TEXT", 0),
        ("updated_at", "TEXT", 0),
    ),
    "world_reservation": (
        ("world_id", "TEXT", 1),
        ("reservation_id", "TEXT", 2),
        ("owner_id", "TEXT", 0),
        ("expires_at", "TEXT", 0),
        ("payload", "TEXT", 0),
        ("updated_at", "TEXT", 0),
    ),
    "market_listing": (
        ("scope_id", "TEXT", 1),
        ("listing_id", "TEXT", 2),
        ("number", "INTEGER", 0),
        ("seller_id", "TEXT", 0),
        ("expires_at", "TEXT", 0),
        ("payload", "TEXT", 0),
        ("updated_at", "TEXT", 0),
    ),
    "committed_transaction": (
        ("transaction_id", "TEXT", 1),
        ("fingerprint", "TEXT", 0),
        ("scope_id", "TEXT", 0),
        ("receipt_payload", "BLOB", 0),
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

_V7_EXPECTED_COLUMNS = dict(_EXPECTED_COLUMNS)
_V7_EXPECTED_COLUMNS.update(
    {
        "committed_transaction": (
            ("transaction_id", "TEXT", 1),
            ("fingerprint", "TEXT", 0),
            ("scope_id", "TEXT", 0),
            ("receipt_payload", "TEXT", 0),
            ("committed_at", "TEXT", 0),
        ),
        "reward_claim": (
            ("scope_id", "TEXT", 1),
            ("settlement_id", "TEXT", 2),
            ("fingerprint", "TEXT", 0),
            ("receipt_payload", "TEXT", 0),
            ("resulting_revision", "INTEGER", 0),
            ("claimed_at", "TEXT", 0),
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
    }
)

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
    expires_at TEXT,
    PRIMARY KEY (aggregate_kind, aggregate_id)
) WITHOUT ROWID;

CREATE INDEX aggregate_snapshot_expiry_idx
ON aggregate_snapshot(expires_at, aggregate_kind, aggregate_id)
WHERE expires_at IS NOT NULL;

CREATE TABLE ledger_transaction (
    ledger_id TEXT NOT NULL,
    transaction_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    resulting_revision INTEGER NOT NULL CHECK (resulting_revision > 0),
    applied_at TEXT NOT NULL,
    PRIMARY KEY (ledger_id, transaction_id)
) WITHOUT ROWID;

CREATE INDEX ledger_transaction_time_idx
ON ledger_transaction(ledger_id, applied_at, transaction_id);

CREATE TABLE ledger_journal_entry (
    ledger_id TEXT NOT NULL,
    entry_id TEXT NOT NULL,
    transaction_id TEXT NOT NULL,
    currency_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    logical_time TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (ledger_id, entry_id),
    FOREIGN KEY (ledger_id, transaction_id)
        REFERENCES ledger_transaction(ledger_id, transaction_id)
        ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE INDEX ledger_journal_time_idx
ON ledger_journal_entry(ledger_id, logical_time, entry_id);

CREATE TABLE reward_claim (
    scope_id TEXT NOT NULL,
    settlement_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    resulting_revision INTEGER NOT NULL CHECK (resulting_revision > 0),
    claimed_at TEXT NOT NULL,
    PRIMARY KEY (scope_id, settlement_id),
    UNIQUE (settlement_id),
    FOREIGN KEY (settlement_id)
        REFERENCES committed_transaction(transaction_id)
        ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE INDEX reward_claim_time_idx
ON reward_claim(scope_id, claimed_at, settlement_id);

CREATE TABLE party_membership (
    subject_id TEXT PRIMARY KEY,
    party_id TEXT NOT NULL,
    party_scope_id TEXT NOT NULL,
    joined_at TEXT NOT NULL
) WITHOUT ROWID;

CREATE INDEX party_membership_party_idx
ON party_membership(party_id, subject_id);

CREATE TABLE world_presence (
    world_id TEXT NOT NULL,
    presence_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (world_id, presence_id)
) WITHOUT ROWID;

CREATE INDEX world_presence_owner_idx
ON world_presence(world_id, owner_id, presence_id);

CREATE TABLE world_reservation (
    world_id TEXT NOT NULL,
    reservation_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    expires_at TEXT,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (world_id, reservation_id)
) WITHOUT ROWID;

CREATE INDEX world_reservation_expiry_idx
ON world_reservation(expires_at, world_id, reservation_id);

CREATE TABLE market_listing (
    scope_id TEXT NOT NULL,
    listing_id TEXT NOT NULL,
    number INTEGER NOT NULL CHECK (number > 0),
    seller_id TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scope_id, listing_id),
    UNIQUE (scope_id, number)
) WITHOUT ROWID;

CREATE INDEX market_listing_expiry_idx
ON market_listing(scope_id, expires_at, listing_id);

CREATE TABLE committed_transaction (
    transaction_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    receipt_payload BLOB NOT NULL,
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
    expires_at: str | None


@dataclass(frozen=True)
class LedgerTransactionRow:
    ledger_id: str
    transaction_id: str
    fingerprint: str
    resulting_revision: int
    applied_at: str


@dataclass(frozen=True)
class RewardClaimRow:
    scope_id: str
    settlement_id: str
    fingerprint: str
    resulting_revision: int
    claimed_at: str


@dataclass(frozen=True)
class PartyMembershipRow:
    subject_id: str
    party_id: str
    party_scope_id: str
    joined_at: str


@dataclass(frozen=True)
class WorldPresenceRow:
    world_id: str
    presence_id: str
    owner_id: str
    revision: int
    payload: str
    updated_at: str


@dataclass(frozen=True)
class WorldReservationRow:
    world_id: str
    reservation_id: str
    owner_id: str
    expires_at: str | None
    payload: str
    updated_at: str


@dataclass(frozen=True)
class MarketListingRow:
    scope_id: str
    listing_id: str
    number: int
    seller_id: str
    expires_at: str
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
                connection.execute("PRAGMA auto_vacuum = INCREMENTAL")
                connection.execute("VACUUM")
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
            row = connection.execute(
                "SELECT value FROM persistence_metadata WHERE key = ?",
                ("schema_version",),
            ).fetchone()
            actual = str(row[0]) if row else "missing"
            if actual == str(PREVIOUS_PERSISTENCE_SCHEMA_VERSION):
                _validate_v7_migration_source(connection)
                backup_path = _backup_before_schema_migration(
                    connection,
                    self.path,
                    busy_timeout_ms=self.busy_timeout_ms,
                )
                try:
                    _migrate_v7_to_v8(connection)
                except Exception as exc:
                    raise SchemaVersionError(
                        f"数据库 v7 -> v8 升级失败；原库事务已回滚，迁移前备份位于 {backup_path}"
                    ) from exc
                actual = str(PERSISTENCE_SCHEMA_VERSION)
                tables = _table_names(connection)
                missing = _REQUIRED_TABLES - tables
                if missing:
                    raise SchemaVersionError(
                        f"数据库升级后结构不完整，缺少表：{', '.join(sorted(missing))}"
                    )
            if actual != str(PERSISTENCE_SCHEMA_VERSION):
                raise SchemaVersionError(
                    f"数据库结构版本不匹配：需要 {PERSISTENCE_SCHEMA_VERSION}，当前 {actual}"
                )
            missing = _REQUIRED_TABLES - tables
            if missing:
                raise SchemaVersionError(
                    f"数据库结构不完整，缺少表：{', '.join(sorted(missing))}"
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

    def backup_to(self, destination: Path | str) -> Path:
        """在线生成一份独立 SQLite 备份，并在交付前完成完整性校验。"""

        target = Path(destination)
        if not self.path.is_file():
            raise FileNotFoundError(f"待备份数据库不存在：{self.path}")
        if target.resolve() == self.path.resolve():
            raise ValueError("数据库备份目标不能覆盖源数据库")
        if target.exists():
            raise FileExistsError(f"数据库备份目标已经存在：{target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with closing(self.connect()) as source_connection, closing(
                sqlite3.connect(
                    target,
                    timeout=self.busy_timeout_ms / 1000,
                )
            ) as target_connection:
                source_connection.backup(target_connection)
                target_connection.execute("PRAGMA journal_mode = DELETE")
                check_rows = target_connection.execute("PRAGMA quick_check").fetchall()
                check_result = tuple(str(row[0]) for row in check_rows)
                if check_result != ("ok",):
                    raise sqlite3.DatabaseError(
                        f"数据库备份完整性校验失败：{', '.join(check_result)}"
                    )
        except Exception:
            with suppress(OSError):
                target.unlink(missing_ok=True)
            raise
        return target

    def reclaim_free_pages(self, *, max_pages: int = 256) -> tuple[int, int]:
        """低频回收尾部空闲页；不执行会长时间独占数据库的全量 VACUUM。"""

        if max_pages < 1:
            raise ValueError("数据库增量回收页数必须大于 0")
        with closing(self.connect()) as connection:
            before = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
            connection.execute("PRAGMA optimize")
            auto_vacuum = int(connection.execute("PRAGMA auto_vacuum").fetchone()[0])
            if before and auto_vacuum == 2:
                connection.execute(f"PRAGMA incremental_vacuum({int(max_pages)})")
            after = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
        return before, after


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
            SELECT aggregate_kind, aggregate_id, revision, codec_version, payload,
                   updated_at, expires_at
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
        after_id: str | None = None,
    ) -> tuple[AggregateSnapshotRow, ...]:
        """按稳定游标列出一页快照，避免固定 LIMIT 永久漏扫尾部。"""

        if not aggregate_kind.strip() or limit < 1:
            raise ValueError("聚合类型不能为空且 limit 必须大于 0")
        rows = self.connection.execute(
            """
            SELECT aggregate_kind, aggregate_id, revision, codec_version, payload,
                   updated_at, expires_at
            FROM aggregate_snapshot
            WHERE aggregate_kind = ? AND (? IS NULL OR aggregate_id > ?)
            ORDER BY aggregate_id
            LIMIT ?
            """,
            (aggregate_kind, after_id, after_id, limit),
        ).fetchall()
        return tuple(AggregateSnapshotRow(**dict(row)) for row in rows)

    def insert_snapshot(
        self,
        aggregate_kind: str,
        aggregate_id: str,
        revision: int,
        payload: str,
        updated_at: str,
        expires_at: str | None = None,
    ) -> None:
        if revision < 0:
            raise ValueError("聚合初始 revision 不能小于 0")
        try:
            self.connection.execute(
                """
                INSERT INTO aggregate_snapshot(
                    aggregate_kind, aggregate_id, revision, codec_version, payload,
                    updated_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    aggregate_kind,
                    aggregate_id,
                    revision,
                    SNAPSHOT_CODEC_VERSION,
                    payload,
                    updated_at,
                    expires_at,
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
        expires_at: str | None = None,
    ) -> None:
        if new_revision != expected_revision + 1:
            raise ValueError("聚合条件更新必须恰好增加一个 revision")
        cursor = self.connection.execute(
            """
            UPDATE aggregate_snapshot
            SET revision = ?, codec_version = ?, payload = ?, updated_at = ?, expires_at = ?
            WHERE aggregate_kind = ? AND aggregate_id = ? AND revision = ?
            """,
            (
                new_revision,
                SNAPSHOT_CODEC_VERSION,
                payload,
                updated_at,
                expires_at,
                aggregate_kind,
                aggregate_id,
                expected_revision,
            ),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(
                f"聚合 revision 冲突：{aggregate_kind}/{aggregate_id} expected={expected_revision}"
            )

    def set_snapshot_expiry(
        self,
        aggregate_kind: str,
        aggregate_id: str,
        expected_revision: int,
        expires_at: str | None,
    ) -> None:
        cursor = self.connection.execute(
            """
            UPDATE aggregate_snapshot
            SET expires_at = ?
            WHERE aggregate_kind = ? AND aggregate_id = ? AND revision = ?
            """,
            (expires_at, aggregate_kind, aggregate_id, expected_revision),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(
                f"快照过期时间更新冲突：{aggregate_kind}/{aggregate_id}"
            )

    def delete_snapshot(
        self,
        aggregate_kind: str,
        aggregate_id: str,
        *,
        expected_revision: int | None = None,
    ) -> bool:
        if expected_revision is None:
            cursor = self.connection.execute(
                "DELETE FROM aggregate_snapshot WHERE aggregate_kind = ? AND aggregate_id = ?",
                (aggregate_kind, aggregate_id),
            )
        else:
            cursor = self.connection.execute(
                """
                DELETE FROM aggregate_snapshot
                WHERE aggregate_kind = ? AND aggregate_id = ? AND revision = ?
                """,
                (aggregate_kind, aggregate_id, expected_revision),
            )
        return cursor.rowcount == 1

    def delete_expired_snapshots(self, logical_time: str, *, limit: int = 5_000) -> int:
        if limit < 1:
            raise ValueError("快照清理 limit 必须大于 0")
        cursor = self.connection.execute(
            """
            DELETE FROM aggregate_snapshot
            WHERE (aggregate_kind, aggregate_id) IN (
                SELECT aggregate_kind, aggregate_id
                FROM aggregate_snapshot
                WHERE expires_at IS NOT NULL
                  AND julianday(expires_at) <= julianday(?)
                ORDER BY expires_at, aggregate_kind, aggregate_id
                LIMIT ?
            )
            """,
            (logical_time, limit),
        )
        return cursor.rowcount

    def load_ledger_transaction(
        self,
        ledger_id: str,
        transaction_id: str,
    ) -> LedgerTransactionRow | None:
        row = self.connection.execute(
            """
            SELECT ledger_id, transaction_id, fingerprint, resulting_revision, applied_at
            FROM ledger_transaction
            WHERE ledger_id = ? AND transaction_id = ?
            """,
            (ledger_id, transaction_id),
        ).fetchone()
        return LedgerTransactionRow(**dict(row)) if row else None

    def insert_ledger_transaction(
        self,
        ledger_id: str,
        transaction_id: str,
        fingerprint: str,
        resulting_revision: int,
        applied_at: str,
    ) -> None:
        try:
            self.connection.execute(
                """
                INSERT INTO ledger_transaction(
                    ledger_id, transaction_id, fingerprint, resulting_revision, applied_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (ledger_id, transaction_id, fingerprint, resulting_revision, applied_at),
            )
        except sqlite3.IntegrityError as exc:
            raise ConcurrencyConflict(
                f"账本事务已经提交：{ledger_id}/{transaction_id}"
            ) from exc

    def insert_ledger_journal_entry(
        self,
        ledger_id: str,
        entry_id: str,
        transaction_id: str,
        currency_id: str,
        reason: str,
        actor_id: str,
        logical_time: str,
        payload: str,
    ) -> None:
        try:
            self.connection.execute(
                """
                INSERT INTO ledger_journal_entry(
                    ledger_id, entry_id, transaction_id, currency_id, reason,
                    actor_id, logical_time, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ledger_id,
                    entry_id,
                    transaction_id,
                    currency_id,
                    reason,
                    actor_id,
                    logical_time,
                    payload,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConcurrencyConflict(
                f"账本流水已经存在：{ledger_id}/{entry_id}"
            ) from exc

    def load_reward_claim(self, scope_id: str, settlement_id: str) -> RewardClaimRow | None:
        row = self.connection.execute(
            """
            SELECT scope_id, settlement_id, fingerprint, resulting_revision, claimed_at
            FROM reward_claim
            WHERE scope_id = ? AND settlement_id = ?
            """,
            (scope_id, settlement_id),
        ).fetchone()
        return RewardClaimRow(**dict(row)) if row else None

    def insert_reward_claim(
        self,
        scope_id: str,
        settlement_id: str,
        fingerprint: str,
        resulting_revision: int,
        claimed_at: str,
    ) -> None:
        try:
            self.connection.execute(
                """
                INSERT INTO reward_claim(
                    scope_id, settlement_id, fingerprint, resulting_revision, claimed_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    scope_id,
                    settlement_id,
                    fingerprint,
                    resulting_revision,
                    claimed_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConcurrencyConflict(
                f"奖励领取已经提交：{scope_id}/{settlement_id}"
            ) from exc

    def load_party_membership(self, subject_id: str) -> PartyMembershipRow | None:
        row = self.connection.execute(
            """
            SELECT subject_id, party_id, party_scope_id, joined_at
            FROM party_membership
            WHERE subject_id = ?
            """,
            (subject_id,),
        ).fetchone()
        return PartyMembershipRow(**dict(row)) if row else None

    def insert_party_membership(
        self,
        subject_id: str,
        party_id: str,
        party_scope_id: str,
        joined_at: str,
    ) -> None:
        try:
            self.connection.execute(
                """
                INSERT INTO party_membership(subject_id, party_id, party_scope_id, joined_at)
                VALUES (?, ?, ?, ?)
                """,
                (subject_id, party_id, party_scope_id, joined_at),
            )
        except sqlite3.IntegrityError as exc:
            raise ConcurrencyConflict(f"角色已经属于其他队伍：{subject_id}") from exc

    def delete_party_membership(self, subject_id: str, party_id: str) -> None:
        cursor = self.connection.execute(
            "DELETE FROM party_membership WHERE subject_id = ? AND party_id = ?",
            (subject_id, party_id),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(f"队伍成员占用记录已经变化：{subject_id}")

    def list_world_presences(self, world_id: str) -> tuple[WorldPresenceRow, ...]:
        rows = self.connection.execute(
            """
            SELECT world_id, presence_id, owner_id, revision, payload, updated_at
            FROM world_presence
            WHERE world_id = ?
            ORDER BY presence_id
            """,
            (world_id,),
        ).fetchall()
        return tuple(WorldPresenceRow(**dict(row)) for row in rows)

    def insert_world_presence(
        self,
        world_id: str,
        presence_id: str,
        owner_id: str,
        revision: int,
        payload: str,
        updated_at: str,
    ) -> None:
        try:
            self.connection.execute(
                """
                INSERT INTO world_presence(
                    world_id, presence_id, owner_id, revision, payload, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (world_id, presence_id, owner_id, revision, payload, updated_at),
            )
        except sqlite3.IntegrityError as exc:
            raise ConcurrencyConflict(
                f"世界存在体已经存在：{world_id}/{presence_id}"
            ) from exc

    def update_world_presence(
        self,
        world_id: str,
        presence_id: str,
        expected_revision: int,
        revision: int,
        owner_id: str,
        payload: str,
        updated_at: str,
    ) -> None:
        cursor = self.connection.execute(
            """
            UPDATE world_presence
            SET owner_id = ?, revision = ?, payload = ?, updated_at = ?
            WHERE world_id = ? AND presence_id = ? AND revision = ?
            """,
            (
                owner_id,
                revision,
                payload,
                updated_at,
                world_id,
                presence_id,
                expected_revision,
            ),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(
                f"世界存在体 revision 冲突：{world_id}/{presence_id}"
            )

    def delete_world_presence(
        self,
        world_id: str,
        presence_id: str,
        expected_revision: int,
    ) -> None:
        cursor = self.connection.execute(
            """
            DELETE FROM world_presence
            WHERE world_id = ? AND presence_id = ? AND revision = ?
            """,
            (world_id, presence_id, expected_revision),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(
                f"世界存在体删除冲突：{world_id}/{presence_id}"
            )

    def list_world_reservations(self, world_id: str) -> tuple[WorldReservationRow, ...]:
        rows = self.connection.execute(
            """
            SELECT world_id, reservation_id, owner_id, expires_at, payload, updated_at
            FROM world_reservation
            WHERE world_id = ?
            ORDER BY reservation_id
            """,
            (world_id,),
        ).fetchall()
        return tuple(WorldReservationRow(**dict(row)) for row in rows)

    def upsert_world_reservation(
        self,
        world_id: str,
        reservation_id: str,
        owner_id: str,
        expires_at: str | None,
        payload: str,
        updated_at: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO world_reservation(
                world_id, reservation_id, owner_id, expires_at, payload, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(world_id, reservation_id) DO UPDATE SET
                owner_id = excluded.owner_id,
                expires_at = excluded.expires_at,
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (world_id, reservation_id, owner_id, expires_at, payload, updated_at),
        )

    def delete_world_reservation(self, world_id: str, reservation_id: str) -> None:
        cursor = self.connection.execute(
            "DELETE FROM world_reservation WHERE world_id = ? AND reservation_id = ?",
            (world_id, reservation_id),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(
                f"世界预约删除冲突：{world_id}/{reservation_id}"
            )

    def list_market_listings(self, scope_id: str) -> tuple[MarketListingRow, ...]:
        rows = self.connection.execute(
            """
            SELECT scope_id, listing_id, number, seller_id, expires_at, payload, updated_at
            FROM market_listing
            WHERE scope_id = ?
            ORDER BY number, listing_id
            """,
            (scope_id,),
        ).fetchall()
        return tuple(MarketListingRow(**dict(row)) for row in rows)

    def insert_market_listing(
        self,
        scope_id: str,
        listing_id: str,
        number: int,
        seller_id: str,
        expires_at: str,
        payload: str,
        updated_at: str,
    ) -> None:
        try:
            self.connection.execute(
                """
                INSERT INTO market_listing(
                    scope_id, listing_id, number, seller_id, expires_at, payload, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scope_id,
                    listing_id,
                    number,
                    seller_id,
                    expires_at,
                    payload,
                    updated_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConcurrencyConflict(f"二手挂单已经存在：{listing_id}") from exc

    def update_market_listing(
        self,
        scope_id: str,
        listing_id: str,
        number: int,
        seller_id: str,
        expires_at: str,
        payload: str,
        updated_at: str,
    ) -> None:
        cursor = self.connection.execute(
            """
            UPDATE market_listing
            SET number = ?, seller_id = ?, expires_at = ?, payload = ?, updated_at = ?
            WHERE scope_id = ? AND listing_id = ?
            """,
            (
                number,
                seller_id,
                expires_at,
                payload,
                updated_at,
                scope_id,
                listing_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(f"二手挂单已经变化：{listing_id}")

    def delete_market_listing(self, scope_id: str, listing_id: str) -> None:
        cursor = self.connection.execute(
            "DELETE FROM market_listing WHERE scope_id = ? AND listing_id = ?",
            (scope_id, listing_id),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(f"二手挂单已经变化：{listing_id}")

    def load_transaction(self, transaction_id: str) -> CommittedTransactionRow | None:
        row = self.connection.execute(
            """
            SELECT transaction_id, fingerprint, scope_id, receipt_payload, committed_at
            FROM committed_transaction
            WHERE transaction_id = ?
            """,
            (transaction_id,),
        ).fetchone()
        if row is None:
            return None
        values = dict(row)
        values["receipt_payload"] = _decode_receipt_payload(values["receipt_payload"])
        return CommittedTransactionRow(**values)

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
            (
                transaction_id,
                fingerprint,
                scope_id,
                _encode_receipt_payload(receipt_payload),
                committed_at,
            ),
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


def _validate_v7_migration_source(connection: sqlite3.Connection) -> None:
    """只接收完整 schema 7；更早版本和残缺数据库都拒绝启动。"""

    missing = _REQUIRED_TABLES - _table_names(connection)
    if missing:
        raise SchemaVersionError(
            f"数据库 v7 结构不完整，缺少表：{', '.join(sorted(missing))}"
        )
    _validate_schema_shape(
        connection,
        expected_columns=_V7_EXPECTED_COLUMNS,
        require_reward_claim_transaction=False,
    )
    _validate_database_integrity(connection, phase="迁移前")


def _backup_before_schema_migration(
    connection: sqlite3.Connection,
    source_path: Path,
    *,
    busy_timeout_ms: int,
) -> Path:
    backup_directory = source_path.parent / "backups"
    backup_directory.mkdir(parents=True, exist_ok=True)
    stamp = _migration_backup_stamp(connection, source_path)
    target = _next_available_backup_path(
        backup_directory,
        f"migration_{source_path.stem}_schema{PREVIOUS_PERSISTENCE_SCHEMA_VERSION}_{stamp}",
    )
    try:
        with closing(
            sqlite3.connect(target, timeout=busy_timeout_ms / 1000)
        ) as target_connection:
            connection.backup(target_connection)
            rows = target_connection.execute("PRAGMA quick_check").fetchall()
            result = tuple(str(row[0]) for row in rows)
            if result != ("ok",):
                raise sqlite3.DatabaseError(
                    f"迁移前备份完整性校验失败：{', '.join(result)}"
                )
    except Exception:
        with suppress(OSError):
            target.unlink(missing_ok=True)
        raise
    return target


def _migration_backup_stamp(
    connection: sqlite3.Connection,
    source_path: Path,
) -> str:
    row = connection.execute(
        "SELECT MAX(updated_at) FROM aggregate_snapshot"
    ).fetchone()
    value = str(row[0] or "") if row else ""
    if value:
        latest = datetime.fromisoformat(value)
        if latest.tzinfo is not None and latest.utcoffset() is not None:
            return latest.astimezone(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S_%fZ")
    modified = datetime.fromtimestamp(source_path.stat().st_mtime, timezone.utc)
    return modified.strftime("%Y-%m-%d_%H-%M-%S_%fZ")


def _next_available_backup_path(
    directory: Path,
    stem: str,
) -> Path:
    candidate = directory / f"{stem}.db"
    suffix = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{suffix}.db"
        suffix += 1
    return candidate


def _migrate_v7_to_v8(connection: sqlite3.Connection) -> None:
    temporary_tables = (
        "_schema7_committed_transaction",
        "_schema7_reward_claim",
        "_schema7_account_evidence",
        "_schema7_grant_redemption",
    )
    occupied = set(temporary_tables) & _table_names(connection)
    if occupied:
        raise SchemaVersionError(
            f"数据库包含迁移保留表：{', '.join(sorted(occupied))}"
        )

    foreign_keys = int(connection.execute("PRAGMA foreign_keys").fetchone()[0])
    legacy_alter = int(connection.execute("PRAGMA legacy_alter_table").fetchone()[0])
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("PRAGMA legacy_alter_table = ON")
    connection.execute("BEGIN EXCLUSIVE")
    try:
        _validate_v7_duplicate_receipts(connection)
        connection.execute(
            "ALTER TABLE committed_transaction RENAME TO _schema7_committed_transaction"
        )
        connection.execute("ALTER TABLE reward_claim RENAME TO _schema7_reward_claim")
        connection.execute(
            "ALTER TABLE account_evidence RENAME TO _schema7_account_evidence"
        )
        connection.execute(
            "ALTER TABLE grant_redemption RENAME TO _schema7_grant_redemption"
        )
        for statement in (
            """
            CREATE TABLE committed_transaction (
                transaction_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                receipt_payload BLOB NOT NULL,
                committed_at TEXT NOT NULL
            ) WITHOUT ROWID
            """,
            """
            CREATE TABLE reward_claim (
                scope_id TEXT NOT NULL,
                settlement_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                resulting_revision INTEGER NOT NULL CHECK (resulting_revision > 0),
                claimed_at TEXT NOT NULL,
                PRIMARY KEY (scope_id, settlement_id),
                UNIQUE (settlement_id),
                FOREIGN KEY (settlement_id)
                    REFERENCES committed_transaction(transaction_id)
                    ON DELETE RESTRICT
            ) WITHOUT ROWID
            """,
            """
            CREATE TABLE account_evidence (
                evidence_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                account_id TEXT,
                conflict_id TEXT,
                transaction_id TEXT NOT NULL UNIQUE,
                processed_at TEXT NOT NULL,
                CHECK ((account_id IS NULL) <> (conflict_id IS NULL)),
                FOREIGN KEY (account_id)
                    REFERENCES account_record(account_id) ON DELETE RESTRICT,
                FOREIGN KEY (conflict_id)
                    REFERENCES account_conflict(conflict_id) ON DELETE RESTRICT,
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
                redeemed_at TEXT NOT NULL,
                FOREIGN KEY (entitlement_id)
                    REFERENCES grant_entitlement(entitlement_id) ON DELETE RESTRICT,
                FOREIGN KEY (campaign_id)
                    REFERENCES grant_campaign(campaign_id) ON DELETE RESTRICT,
                FOREIGN KEY (credential_id)
                    REFERENCES grant_credential(credential_id) ON DELETE RESTRICT,
                FOREIGN KEY (settlement_id)
                    REFERENCES committed_transaction(transaction_id) ON DELETE RESTRICT
            ) WITHOUT ROWID
            """,
        ):
            connection.execute(statement)
        rows = connection.execute(
            """
            SELECT transaction_id, fingerprint, scope_id, receipt_payload, committed_at
            FROM _schema7_committed_transaction
            ORDER BY transaction_id
            """
        ).fetchall()
        encoded_rows = []
        for row in rows:
            payload = row["receipt_payload"]
            if not isinstance(payload, str):
                raise SchemaVersionError("数据库 v7 事务回执不是文本")
            encoded_rows.append(
                (
                    str(row["transaction_id"]),
                    str(row["fingerprint"]),
                    str(row["scope_id"]),
                    _encode_receipt_payload(payload),
                    str(row["committed_at"]),
                )
            )
        connection.executemany(
            """
            INSERT INTO committed_transaction(
                transaction_id, fingerprint, scope_id, receipt_payload, committed_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            encoded_rows,
        )
        connection.execute(
            """
            INSERT INTO reward_claim(
                scope_id, settlement_id, fingerprint, resulting_revision, claimed_at
            )
            SELECT scope_id, settlement_id, fingerprint, resulting_revision, claimed_at
            FROM _schema7_reward_claim
            """
        )
        connection.execute(
            """
            INSERT INTO account_evidence(
                evidence_id, fingerprint, account_id, conflict_id,
                transaction_id, processed_at
            )
            SELECT evidence_id, fingerprint, account_id, conflict_id,
                   transaction_id, processed_at
            FROM _schema7_account_evidence
            """
        )
        connection.execute(
            """
            INSERT INTO grant_redemption(
                redemption_id, entitlement_id, campaign_id, credential_id,
                account_id, settlement_id, request_fingerprint, redeemed_at
            )
            SELECT redemption_id, entitlement_id, campaign_id, credential_id,
                   account_id, settlement_id, request_fingerprint, redeemed_at
            FROM _schema7_grant_redemption
            """
        )
        for table in reversed(temporary_tables[1:]):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("DROP TABLE _schema7_committed_transaction")
        for statement in (
            """
            CREATE INDEX reward_claim_time_idx
            ON reward_claim(scope_id, claimed_at, settlement_id)
            """,
            """
            CREATE INDEX account_evidence_account_idx
            ON account_evidence(account_id, processed_at)
            """,
            """
            CREATE INDEX grant_redemption_account_idx
            ON grant_redemption(campaign_id, account_id, redeemed_at)
            """,
        ):
            connection.execute(statement)
        connection.execute(
            "UPDATE persistence_metadata SET value = ? WHERE key = 'schema_version'",
            (str(PERSISTENCE_SCHEMA_VERSION),),
        )
        _validate_schema_shape(connection)
        _validate_database_integrity(connection, phase="迁移后")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute(f"PRAGMA legacy_alter_table = {legacy_alter}")
        connection.execute(f"PRAGMA foreign_keys = {foreign_keys}")


def _validate_v7_duplicate_receipts(connection: sqlite3.Connection) -> None:
    relations = (
        ("account_evidence", "evidence_id", "transaction_id"),
        ("reward_claim", "settlement_id", "settlement_id"),
    )
    for table, identity_column, transaction_column in relations:
        rows = connection.execute(
            f"""
            SELECT relation.{identity_column} AS relation_id,
                   relation.receipt_payload AS relation_payload,
                   committed.receipt_payload AS committed_payload
            FROM {table} AS relation
            LEFT JOIN committed_transaction AS committed
              ON committed.transaction_id = relation.{transaction_column}
            """
        ).fetchall()
        for row in rows:
            if row["committed_payload"] is None:
                raise SchemaVersionError(
                    f"数据库 v7 关系记录缺少提交事务：{table}/{row['relation_id']}"
                )
            if row["relation_payload"] != row["committed_payload"]:
                raise SchemaVersionError(
                    f"数据库 v7 重复回执不一致：{table}/{row['relation_id']}"
                )


def _migrate_v6_to_v7(connection: sqlite3.Connection) -> None:
    statements = (
        "ALTER TABLE aggregate_snapshot ADD COLUMN expires_at TEXT",
        """
        CREATE INDEX aggregate_snapshot_expiry_idx
        ON aggregate_snapshot(expires_at, aggregate_kind, aggregate_id)
        WHERE expires_at IS NOT NULL
        """,
        """
        CREATE TABLE ledger_transaction (
            ledger_id TEXT NOT NULL,
            transaction_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            resulting_revision INTEGER NOT NULL CHECK (resulting_revision > 0),
            applied_at TEXT NOT NULL,
            PRIMARY KEY (ledger_id, transaction_id)
        ) WITHOUT ROWID
        """,
        """
        CREATE INDEX ledger_transaction_time_idx
        ON ledger_transaction(ledger_id, applied_at, transaction_id)
        """,
        """
        CREATE TABLE ledger_journal_entry (
            ledger_id TEXT NOT NULL,
            entry_id TEXT NOT NULL,
            transaction_id TEXT NOT NULL,
            currency_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            logical_time TEXT NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY (ledger_id, entry_id),
            FOREIGN KEY (ledger_id, transaction_id)
                REFERENCES ledger_transaction(ledger_id, transaction_id)
                ON DELETE RESTRICT
        ) WITHOUT ROWID
        """,
        """
        CREATE INDEX ledger_journal_time_idx
        ON ledger_journal_entry(ledger_id, logical_time, entry_id)
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
        CREATE INDEX reward_claim_time_idx
        ON reward_claim(scope_id, claimed_at, settlement_id)
        """,
        """
        CREATE TABLE party_membership (
            subject_id TEXT PRIMARY KEY,
            party_id TEXT NOT NULL,
            party_scope_id TEXT NOT NULL,
            joined_at TEXT NOT NULL
        ) WITHOUT ROWID
        """,
        """
        CREATE INDEX party_membership_party_idx
        ON party_membership(party_id, subject_id)
        """,
        """
        CREATE TABLE world_presence (
            world_id TEXT NOT NULL,
            presence_id TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            revision INTEGER NOT NULL CHECK (revision >= 0),
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (world_id, presence_id)
        ) WITHOUT ROWID
        """,
        """
        CREATE INDEX world_presence_owner_idx
        ON world_presence(world_id, owner_id, presence_id)
        """,
        """
        CREATE TABLE world_reservation (
            world_id TEXT NOT NULL,
            reservation_id TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            expires_at TEXT,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (world_id, reservation_id)
        ) WITHOUT ROWID
        """,
        """
        CREATE INDEX world_reservation_expiry_idx
        ON world_reservation(expires_at, world_id, reservation_id)
        """,
        """
        CREATE TABLE market_listing (
            scope_id TEXT NOT NULL,
            listing_id TEXT NOT NULL,
            number INTEGER NOT NULL CHECK (number > 0),
            seller_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (scope_id, listing_id),
            UNIQUE (scope_id, number)
        ) WITHOUT ROWID
        """,
        """
        CREATE INDEX market_listing_expiry_idx
        ON market_listing(scope_id, expires_at, listing_id)
        """,
    )
    connection.execute("BEGIN EXCLUSIVE")
    try:
        for statement in statements:
            connection.execute(statement)
        _migrate_ledger_snapshots(connection)
        _migrate_reward_claim_snapshots(connection)
        _migrate_party_snapshots(connection)
        _migrate_world_snapshots(connection)
        _migrate_market_snapshots(connection)
        connection.execute(
            "UPDATE persistence_metadata SET value = ? WHERE key = 'schema_version'",
            (str(PERSISTENCE_SCHEMA_VERSION),),
        )
        _validate_schema_shape(connection)
        _validate_database_integrity(connection, phase="迁移后")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _migrate_ledger_snapshots(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT aggregate_id, payload, updated_at
        FROM aggregate_snapshot
        WHERE aggregate_kind = 'snapshot.ledger'
        """
    ).fetchall()
    for row in rows:
        ledger_id = str(row["aggregate_id"])
        document, fields = _snapshot_document(row["payload"], "economy.state")
        journal = _collection_items(fields, "journal", "tuple")
        entries_by_transaction: dict[str, list[dict[str, object]]] = {}
        for entry in journal:
            entry_fields = _typed_fields(entry, "economy.journal_entry")
            transaction_id = str(entry_fields["transaction_id"])
            entries_by_transaction.setdefault(transaction_id, []).append(entry_fields)
        applied = _mapping_items(fields, "applied_transactions")
        for key, value in applied:
            record = _typed_fields(value, "economy.applied_transaction")
            transaction_id = str(record["transaction_id"])
            if str(key) != transaction_id:
                raise SchemaVersionError("账本防重映射键与事务 ID 不一致")
            related = entries_by_transaction.get(transaction_id, ())
            applied_at = (
                _datetime_value(related[0]["logical_time"])
                if related
                else str(row["updated_at"])
            )
            connection.execute(
                """
                INSERT INTO ledger_transaction(
                    ledger_id, transaction_id, fingerprint, resulting_revision, applied_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    ledger_id,
                    transaction_id,
                    str(record["fingerprint"]),
                    int(record["resulting_revision"]),
                    applied_at,
                ),
            )
        for entry in journal:
            entry_fields = _typed_fields(entry, "economy.journal_entry")
            connection.execute(
                """
                INSERT INTO ledger_journal_entry(
                    ledger_id, entry_id, transaction_id, currency_id, reason,
                    actor_id, logical_time, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ledger_id,
                    str(entry_fields["id"]),
                    str(entry_fields["transaction_id"]),
                    str(entry_fields["currency_id"]),
                    str(entry_fields["reason"]),
                    str(entry_fields["actor_id"]),
                    _datetime_value(entry_fields["logical_time"]),
                    _node_payload(entry),
                ),
            )
        fields["journal"] = {"$type": "tuple", "items": []}
        fields["applied_transactions"] = {"$type": "mapping", "items": []}
        connection.execute(
            """
            UPDATE aggregate_snapshot SET payload = ?
            WHERE aggregate_kind = 'snapshot.ledger' AND aggregate_id = ?
            """,
            (_dump_document(document), ledger_id),
        )


def _migrate_reward_claim_snapshots(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT aggregate_id, payload
        FROM aggregate_snapshot
        WHERE aggregate_kind = 'snapshot.reward_claim'
        """
    ).fetchall()
    for row in rows:
        document, fields = _snapshot_document(row["payload"], "reward.claim_state")
        scope_id = str(fields["scope_id"])
        if scope_id != str(row["aggregate_id"]):
            raise SchemaVersionError("奖励领取快照作用域与聚合 ID 不一致")
        for key, value in _mapping_items(fields, "records"):
            record = _typed_fields(value, "reward.claim_record")
            settlement_id = str(record["settlement_id"])
            receipt = record["receipt"]
            receipt_fields = _typed_fields(receipt, "reward.receipt")
            if str(key) != settlement_id:
                raise SchemaVersionError("奖励领取映射键与结算 ID 不一致")
            connection.execute(
                """
                INSERT INTO reward_claim(
                    scope_id, settlement_id, fingerprint, receipt_payload,
                    resulting_revision, claimed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    scope_id,
                    settlement_id,
                    str(record["fingerprint"]),
                    _node_payload(receipt),
                    int(record["resulting_revision"]),
                    _datetime_value(receipt_fields["logical_time"]),
                ),
            )
        fields["records"] = {"$type": "mapping", "items": []}
        connection.execute(
            """
            UPDATE aggregate_snapshot SET payload = ?
            WHERE aggregate_kind = 'snapshot.reward_claim' AND aggregate_id = ?
            """,
            (_dump_document(document), scope_id),
        )


def _migrate_party_snapshots(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT aggregate_id, revision, codec_version, payload, updated_at
        FROM aggregate_snapshot
        WHERE aggregate_kind = 'snapshot.party'
        ORDER BY aggregate_id
        """
    ).fetchall()
    for row in rows:
        document, fields = _snapshot_document(row["payload"], "party.state")
        parties = _mapping_items(fields, "parties")
        if len(parties) <= 1 and all(str(key) == str(row["aggregate_id"]) for key, _ in parties):
            _populate_party_memberships(connection, parties, str(row["aggregate_id"]))
            continue
        for key, party_node in parties:
            party_id = str(key)
            party_fields = _typed_fields(party_node, "party.value")
            if str(party_fields["id"]) != party_id:
                raise SchemaVersionError("队伍映射键与队伍 ID 不一致")
            next_document = json.loads(json.dumps(document, ensure_ascii=False))
            next_fields = _typed_fields(next_document["value"], "party.state")
            next_fields["scope_id"] = party_id
            next_fields["parties"] = {
                "$type": "mapping",
                "items": [[party_id, party_node]],
            }
            status = party_fields["status"]
            active = isinstance(status, dict) and status.get("$enum") == "active"
            expires_at = None
            if not active:
                expires_at = (
                    datetime.fromisoformat(str(row["updated_at"])) + timedelta(hours=24)
                ).isoformat()
            connection.execute(
                """
                INSERT INTO aggregate_snapshot(
                    aggregate_kind, aggregate_id, revision, codec_version, payload,
                    updated_at, expires_at
                ) VALUES ('snapshot.party', ?, ?, ?, ?, ?, ?)
                """,
                (
                    party_id,
                    int(row["revision"]),
                    int(row["codec_version"]),
                    _dump_document(next_document),
                    str(row["updated_at"]),
                    expires_at,
                ),
            )
            _populate_party_memberships(connection, ((party_id, party_node),), party_id)
        connection.execute(
            """
            DELETE FROM aggregate_snapshot
            WHERE aggregate_kind = 'snapshot.party' AND aggregate_id = ?
            """,
            (str(row["aggregate_id"]),),
        )


def _populate_party_memberships(connection, parties, scope_id: str) -> None:
    for party_id, party_node in parties:
        party_fields = _typed_fields(party_node, "party.value")
        status = party_fields["status"]
        if not isinstance(status, dict) or status.get("$enum") != "active":
            continue
        for subject_id, member_node in _mapping_node_items(party_fields["members"]):
            member_fields = _typed_fields(member_node, "party.member")
            connection.execute(
                """
                INSERT INTO party_membership(subject_id, party_id, party_scope_id, joined_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(subject_id),
                    str(party_id),
                    scope_id,
                    _datetime_value(member_fields["joined_at"]),
                ),
            )


def _migrate_world_snapshots(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT aggregate_id, payload, updated_at
        FROM aggregate_snapshot
        WHERE aggregate_kind = 'snapshot.world'
        """
    ).fetchall()
    for row in rows:
        document, fields = _snapshot_document(row["payload"], "world.state")
        world_id = str(fields["world_id"])
        if world_id != str(row["aggregate_id"]):
            raise SchemaVersionError("世界快照 ID 与聚合 ID 不一致")
        for key, node in _mapping_items(fields, "presences"):
            presence = _typed_fields(node, "world.presence")
            presence_id = str(presence["id"])
            if str(key) != presence_id:
                raise SchemaVersionError("世界存在体映射键与 ID 不一致")
            connection.execute(
                """
                INSERT INTO world_presence(
                    world_id, presence_id, owner_id, revision, payload, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    world_id,
                    presence_id,
                    str(presence["owner_id"]),
                    int(presence["revision"]),
                    _node_payload(node),
                    str(row["updated_at"]),
                ),
            )
        for key, node in _mapping_items(fields, "reservations"):
            reservation = _typed_fields(node, "world.reservation")
            reservation_id = str(reservation["id"])
            if str(key) != reservation_id:
                raise SchemaVersionError("世界预约映射键与 ID 不一致")
            expires_node = reservation.get("expires_at")
            expires_at = _datetime_value(expires_node) if expires_node is not None else None
            connection.execute(
                """
                INSERT INTO world_reservation(
                    world_id, reservation_id, owner_id, expires_at, payload, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    world_id,
                    reservation_id,
                    str(reservation["owner_id"]),
                    expires_at,
                    _node_payload(node),
                    str(row["updated_at"]),
                ),
            )
        fields["presences"] = {"$type": "mapping", "items": []}
        fields["reservations"] = {"$type": "mapping", "items": []}
        connection.execute(
            """
            UPDATE aggregate_snapshot SET payload = ?
            WHERE aggregate_kind = 'snapshot.world' AND aggregate_id = ?
            """,
            (_dump_document(document), world_id),
        )


def _migrate_market_snapshots(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT aggregate_id, payload, updated_at
        FROM aggregate_snapshot
        WHERE aggregate_kind = 'snapshot.market'
        """
    ).fetchall()
    for row in rows:
        document, fields = _snapshot_document(
            row["payload"],
            "game.economy.market_state.v1",
        )
        scope_id = str(fields["scope_id"])
        if scope_id != str(row["aggregate_id"]):
            raise SchemaVersionError("二手市场作用域与聚合 ID 不一致")
        for key, node in _mapping_items(fields, "listings"):
            listing = _typed_fields(node, "game.economy.market_listing.v1")
            listing_id = str(listing["id"])
            if str(key) != listing_id:
                raise SchemaVersionError("二手挂单映射键与 ID 不一致")
            connection.execute(
                """
                INSERT INTO market_listing(
                    scope_id, listing_id, number, seller_id, expires_at,
                    payload, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scope_id,
                    listing_id,
                    int(listing["number"]),
                    str(listing["seller_id"]),
                    _datetime_value(listing["expires_at"]),
                    _node_payload(node),
                    str(row["updated_at"]),
                ),
            )
        fields["listings"] = {"$type": "mapping", "items": []}
        connection.execute(
            """
            UPDATE aggregate_snapshot SET payload = ?
            WHERE aggregate_kind = 'snapshot.market' AND aggregate_id = ?
            """,
            (_dump_document(document), scope_id),
        )


def _snapshot_document(payload: str, expected_type: str) -> tuple[dict, dict]:
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SchemaVersionError("迁移快照不是有效 JSON") from exc
    if document.get("format") != "structured-json.v1":
        raise SchemaVersionError("迁移快照格式未知")
    return document, _typed_fields(document.get("value"), expected_type)


def _typed_fields(node: object, expected_type: str) -> dict:
    if not isinstance(node, dict) or node.get("$type") != expected_type:
        raise SchemaVersionError(f"迁移快照类型错误：需要 {expected_type}")
    fields = node.get("$fields")
    if not isinstance(fields, dict):
        raise SchemaVersionError(f"迁移快照缺少字段：{expected_type}")
    return fields


def _mapping_node_items(node: object) -> list:
    if not isinstance(node, dict) or node.get("$type") != "mapping":
        raise SchemaVersionError("迁移快照映射结构无效")
    items = node.get("items")
    if not isinstance(items, list):
        raise SchemaVersionError("迁移快照映射条目无效")
    return items


def _mapping_items(fields: dict, name: str) -> list:
    return _mapping_node_items(fields.get(name))


def _collection_items(fields: dict, name: str, collection_type: str) -> list:
    node = fields.get(name)
    if not isinstance(node, dict) or node.get("$type") != collection_type:
        raise SchemaVersionError(f"迁移快照集合结构无效：{name}")
    items = node.get("items")
    if not isinstance(items, list):
        raise SchemaVersionError(f"迁移快照集合条目无效：{name}")
    return items


def _datetime_value(node: object) -> str:
    if not isinstance(node, dict) or node.get("$type") != "datetime":
        raise SchemaVersionError("迁移快照时间结构无效")
    value = str(node.get("value") or "")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SchemaVersionError("迁移快照时间缺少时区")
    return value


def _node_payload(node: object) -> str:
    return json.dumps(
        {"format": "structured-json.v1", "value": node},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _dump_document(document: object) -> str:
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _validate_schema_shape(
    connection: sqlite3.Connection,
    *,
    expected_columns: dict[str, tuple[tuple[str, str, int], ...]] = _EXPECTED_COLUMNS,
    require_reward_claim_transaction: bool = True,
) -> None:
    for table, expected in expected_columns.items():
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
    required_lifecycle_indexes = {
        "aggregate_snapshot": {"aggregate_snapshot_expiry_idx"},
        "ledger_transaction": {"ledger_transaction_time_idx"},
        "ledger_journal_entry": {"ledger_journal_time_idx"},
        "reward_claim": {"reward_claim_time_idx"},
        "party_membership": {"party_membership_party_idx"},
        "world_presence": {"world_presence_owner_idx"},
        "world_reservation": {"world_reservation_expiry_idx"},
        "market_listing": {"market_listing_expiry_idx"},
    }
    for table, expected_indexes in required_lifecycle_indexes.items():
        actual_indexes = {
            str(row[1])
            for row in connection.execute(f"PRAGMA index_list({table})").fetchall()
        }
        if not expected_indexes.issubset(actual_indexes):
            raise SchemaVersionError(f"数据库缺少生命周期索引：{table}")
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
    ledger_journal_keys = {
        (str(row[3]), str(row[2]), str(row[4]))
        for row in connection.execute(
            "PRAGMA foreign_key_list(ledger_journal_entry)"
        ).fetchall()
    }
    if ledger_journal_keys != {
        ("ledger_id", "ledger_transaction", "ledger_id"),
        ("transaction_id", "ledger_transaction", "transaction_id"),
    }:
        raise SchemaVersionError("账本流水事务外键结构不正确")
    reward_claim_keys = {
        (str(row[3]), str(row[2]), str(row[4]))
        for row in connection.execute("PRAGMA foreign_key_list(reward_claim)").fetchall()
    }
    expected_reward_claim_keys = (
        {("settlement_id", "committed_transaction", "transaction_id")}
        if require_reward_claim_transaction
        else set()
    )
    if reward_claim_keys != expected_reward_claim_keys:
        raise SchemaVersionError("奖励领取事务外键结构不正确")
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


def _validate_database_integrity(
    connection: sqlite3.Connection,
    *,
    phase: str,
) -> None:
    quick_check = tuple(
        str(row[0]) for row in connection.execute("PRAGMA quick_check")
    )
    if quick_check != ("ok",):
        raise SchemaVersionError(
            f"数据库{phase}完整性校验失败：{', '.join(quick_check)}"
        )
    foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_rows:
        first = foreign_key_rows[0]
        raise SchemaVersionError(
            "数据库"
            f"{phase}外键校验失败：{first[0]}/{first[1]}/{first[2]}/{first[3]}"
        )


__all__ = [
    "AggregateSnapshotRow",
    "CommittedTransactionRow",
    "ContentActivationRow",
    "CycleCursorRow",
    "CycleWorkItemRow",
    "LedgerTransactionRow",
    "MarketListingRow",
    "OutboxEventRow",
    "PartyMembershipRow",
    "PERSISTENCE_SCHEMA_VERSION",
    "SNAPSHOT_CODEC_VERSION",
    "RewardClaimRow",
    "SqliteDatabase",
    "SqliteUnitOfWork",
    "WorldPresenceRow",
    "WorldReservationRow",
]
