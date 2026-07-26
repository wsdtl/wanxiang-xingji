"""权益凭证、迁移清单与奖励结算的 SQLite 原子兑付。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import sqlite3
from typing import Mapping

from ..gameplay.context import RuleContext
from ..gameplay.errors import RuleFailure, RuleOutcome
from ..gameplay.grants import (
    GrantCampaign,
    GrantCampaignStatus,
    GrantCredential,
    GrantCredentialKind,
    GrantCredentialStatus,
    GrantEngine,
    GrantEntitlement,
    GrantEntitlementStatus,
    GrantProof,
    GrantRedemptionCommand,
    GrantRedemptionExecution,
    GrantRedemptionPolicy,
    GrantRedemptionReceipt,
    GrantRewardBundle,
    GrantUsage,
    MigrationManifestEntry,
    code_entitlement_id,
    grant_code_digest,
    grant_proof_digest,
    verify_grant_proof,
)
from ..gameplay.rewards import RewardClaimState, RewardReceipt

from .errors import ConcurrencyConflict, CorruptPersistenceData, TransactionMismatch
from .rewards import PersistedRewardSettlementService, RewardSettlementStorageKeys
from .snapshots import REWARD_CLAIM_AGGREGATE, gameplay_snapshot_codec
from .sqlite import SqliteDatabase, SqliteUnitOfWork


class GrantRepository:
    """权益专用 SQL；事务边界由调用方持有。"""

    def __init__(self) -> None:
        self.codec = gameplay_snapshot_codec(
            (("grant.redemption_receipt", GrantRedemptionReceipt),)
        )

    def insert_campaign(
        self,
        uow: SqliteUnitOfWork,
        campaign: GrantCampaign,
        *,
        created_at: datetime,
    ) -> None:
        _require_aware(created_at)
        try:
            uow.connection.execute(
                """
                INSERT INTO grant_campaign(
                    campaign_id, version, issuer_id, source_kind, offer_id, offer_version,
                    policy, per_account_limit, total_limit, starts_at, ends_at, status,
                    metadata_payload, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    campaign.id,
                    campaign.version,
                    campaign.issuer_id,
                    str(campaign.source_kind),
                    str(campaign.offer_id),
                    campaign.offer_version,
                    campaign.policy.value,
                    campaign.per_account_limit,
                    campaign.total_limit,
                    campaign.starts_at.isoformat(),
                    _datetime_text(campaign.ends_at),
                    campaign.status.value,
                    self.codec.dumps(dict(campaign.metadata)),
                    created_at.isoformat(),
                    created_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConcurrencyConflict(f"权益活动已经存在：{campaign.id}") from exc

    def load_campaign(self, uow: SqliteUnitOfWork, campaign_id: str) -> GrantCampaign | None:
        row = uow.connection.execute(
            "SELECT * FROM grant_campaign WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        if row is None:
            return None
        return GrantCampaign(
            id=str(row["campaign_id"]),
            version=int(row["version"]),
            issuer_id=str(row["issuer_id"]),
            source_kind=str(row["source_kind"]),
            offer_id=str(row["offer_id"]),
            offer_version=int(row["offer_version"]),
            policy=GrantRedemptionPolicy(str(row["policy"])),
            per_account_limit=int(row["per_account_limit"]),
            total_limit=int(row["total_limit"]) if row["total_limit"] is not None else None,
            starts_at=datetime.fromisoformat(str(row["starts_at"])),
            ends_at=_parse_datetime(row["ends_at"]),
            status=GrantCampaignStatus(str(row["status"])),
            metadata=self.codec.loads(str(row["metadata_payload"]), dict),
        )

    def set_campaign_status(
        self,
        uow: SqliteUnitOfWork,
        campaign_id: str,
        status: GrantCampaignStatus,
        *,
        expected_version: int,
        updated_at: datetime,
    ) -> None:
        _require_aware(updated_at)
        cursor = uow.connection.execute(
            """
            UPDATE grant_campaign
            SET status = ?, version = version + 1, updated_at = ?
            WHERE campaign_id = ? AND version = ?
            """,
            (GrantCampaignStatus(status).value, updated_at.isoformat(), campaign_id, expected_version),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(f"权益活动版本冲突：{campaign_id}")

    def insert_credential(self, uow: SqliteUnitOfWork, credential: GrantCredential) -> None:
        try:
            uow.connection.execute(
                """
                INSERT INTO grant_credential(
                    credential_id, campaign_id, kind, digest, usage_limit, usage_count,
                    bound_account_id, expires_at, external_reference, status,
                    metadata_payload, issued_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    credential.id,
                    credential.campaign_id,
                    credential.kind.value,
                    credential.digest,
                    credential.usage_limit,
                    credential.bound_account_id,
                    _datetime_text(credential.expires_at),
                    credential.external_reference,
                    credential.status.value,
                    self.codec.dumps(dict(credential.metadata)),
                    credential.issued_at.isoformat(),
                    credential.issued_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConcurrencyConflict(f"权益凭证已经存在：{credential.id}") from exc

    def load_credential(
        self,
        uow: SqliteUnitOfWork,
        credential_id: str,
    ) -> tuple[GrantCredential, int] | None:
        row = uow.connection.execute(
            "SELECT * FROM grant_credential WHERE credential_id = ?",
            (credential_id,),
        ).fetchone()
        return self._credential(row) if row else None

    def find_credential_by_digest(
        self,
        uow: SqliteUnitOfWork,
        campaign_id: str,
        digest: str,
    ) -> tuple[GrantCredential, int] | None:
        row = uow.connection.execute(
            "SELECT * FROM grant_credential WHERE campaign_id = ? AND digest = ?",
            (campaign_id, digest),
        ).fetchone()
        return self._credential(row) if row else None

    def _credential(self, row) -> tuple[GrantCredential, int]:
        return (
            GrantCredential(
                id=str(row["credential_id"]),
                campaign_id=str(row["campaign_id"]),
                kind=GrantCredentialKind(str(row["kind"])),
                digest=str(row["digest"]),
                usage_limit=int(row["usage_limit"]) if row["usage_limit"] is not None else None,
                issued_at=datetime.fromisoformat(str(row["issued_at"])),
                bound_account_id=row["bound_account_id"],
                expires_at=_parse_datetime(row["expires_at"]),
                external_reference=row["external_reference"],
                status=GrantCredentialStatus(str(row["status"])),
                metadata=self.codec.loads(str(row["metadata_payload"]), dict),
            ),
            int(row["usage_count"]),
        )

    def increment_credential_usage(
        self,
        uow: SqliteUnitOfWork,
        credential_id: str,
        expected_usage: int,
        *,
        updated_at: datetime,
    ) -> None:
        cursor = uow.connection.execute(
            """
            UPDATE grant_credential
            SET usage_count = usage_count + 1, updated_at = ?
            WHERE credential_id = ? AND usage_count = ? AND status = 'active'
            """,
            (updated_at.isoformat(), credential_id, expected_usage),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(f"权益凭证使用次数冲突：{credential_id}")

    def revoke_credential(
        self,
        uow: SqliteUnitOfWork,
        credential_id: str,
        *,
        revoked_at: datetime,
    ) -> None:
        cursor = uow.connection.execute(
            """
            UPDATE grant_credential
            SET status = 'revoked', updated_at = ?
            WHERE credential_id = ? AND status = 'active'
            """,
            (revoked_at.isoformat(), credential_id),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(f"权益凭证不存在或已经撤销：{credential_id}")

    def insert_entitlement(self, uow: SqliteUnitOfWork, entitlement: GrantEntitlement) -> None:
        try:
            uow.connection.execute(
                """
                INSERT INTO grant_entitlement(
                    entitlement_id, campaign_id, credential_id, account_id, offer_id,
                    offer_version, status, issued_at, expires_at, redeemed_at,
                    settlement_id, metadata_payload, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entitlement.id,
                    entitlement.campaign_id,
                    entitlement.credential_id,
                    entitlement.account_id,
                    str(entitlement.offer_id),
                    entitlement.offer_version,
                    entitlement.status.value,
                    entitlement.issued_at.isoformat(),
                    _datetime_text(entitlement.expires_at),
                    _datetime_text(entitlement.redeemed_at),
                    entitlement.settlement_id,
                    self.codec.dumps(dict(entitlement.metadata)),
                    entitlement.issued_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConcurrencyConflict(f"领取权益已经存在：{entitlement.id}") from exc

    def load_entitlement(
        self,
        uow: SqliteUnitOfWork,
        entitlement_id: str,
    ) -> GrantEntitlement | None:
        row = uow.connection.execute(
            "SELECT * FROM grant_entitlement WHERE entitlement_id = ?",
            (entitlement_id,),
        ).fetchone()
        if row is None:
            return None
        return GrantEntitlement(
            id=str(row["entitlement_id"]),
            campaign_id=str(row["campaign_id"]),
            account_id=str(row["account_id"]),
            offer_id=str(row["offer_id"]),
            offer_version=int(row["offer_version"]),
            issued_at=datetime.fromisoformat(str(row["issued_at"])),
            credential_id=row["credential_id"],
            expires_at=_parse_datetime(row["expires_at"]),
            status=GrantEntitlementStatus(str(row["status"])),
            redeemed_at=_parse_datetime(row["redeemed_at"]),
            settlement_id=row["settlement_id"],
            metadata=self.codec.loads(str(row["metadata_payload"]), dict),
        )

    def mark_entitlement_redeemed(
        self,
        uow: SqliteUnitOfWork,
        entitlement_id: str,
        settlement_id: str,
        *,
        redeemed_at: datetime,
    ) -> None:
        cursor = uow.connection.execute(
            """
            UPDATE grant_entitlement
            SET status = 'redeemed', redeemed_at = ?, settlement_id = ?, updated_at = ?
            WHERE entitlement_id = ? AND status = 'available'
            """,
            (
                redeemed_at.isoformat(),
                settlement_id,
                redeemed_at.isoformat(),
                entitlement_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(f"领取权益状态冲突：{entitlement_id}")

    def revoke_entitlement(
        self,
        uow: SqliteUnitOfWork,
        entitlement_id: str,
        *,
        revoked_at: datetime,
    ) -> None:
        cursor = uow.connection.execute(
            """
            UPDATE grant_entitlement
            SET status = 'revoked', updated_at = ?
            WHERE entitlement_id = ? AND status = 'available'
            """,
            (revoked_at.isoformat(), entitlement_id),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(f"只有未领取权益可以撤销：{entitlement_id}")

    def usage(self, uow: SqliteUnitOfWork, campaign_id: str, account_id: str) -> GrantUsage:
        row = uow.connection.execute(
            """
            SELECT COUNT(*) AS campaign_count,
                   SUM(CASE WHEN account_id = ? THEN 1 ELSE 0 END) AS account_count
            FROM grant_redemption
            WHERE campaign_id = ?
            """,
            (account_id, campaign_id),
        ).fetchone()
        return GrantUsage(int(row["campaign_count"]), int(row["account_count"] or 0), 0)

    def insert_redemption(
        self,
        uow: SqliteUnitOfWork,
        receipt: GrantRedemptionReceipt,
    ) -> None:
        try:
            uow.connection.execute(
                """
                INSERT INTO grant_redemption(
                    redemption_id, entitlement_id, campaign_id, credential_id,
                    account_id, settlement_id, request_fingerprint,
                    redeemed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.redemption_id,
                    receipt.entitlement_id,
                    receipt.campaign_id,
                    receipt.credential_id,
                    receipt.account_id,
                    receipt.settlement_id,
                    receipt.request_fingerprint,
                    receipt.redeemed_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConcurrencyConflict(f"权益兑付记录已经存在：{receipt.redemption_id}") from exc

    def load_redemption(
        self,
        uow: SqliteUnitOfWork,
        *,
        redemption_id: str | None = None,
        entitlement_id: str | None = None,
    ) -> GrantRedemptionReceipt | None:
        if bool(redemption_id) == bool(entitlement_id):
            raise ValueError("必须且只能按 redemption_id 或 entitlement_id 查询")
        field = "redemption_id" if redemption_id else "entitlement_id"
        value = redemption_id or entitlement_id
        row = uow.connection.execute(
            f"""
            SELECT redemption_id, entitlement_id, campaign_id, credential_id,
                   account_id, settlement_id, request_fingerprint, redeemed_at
            FROM grant_redemption WHERE {field} = ?
            """,
            (value,),
        ).fetchone()
        return self._redemption_from_row(uow, row) if row else None

    def find_account_redemption(
        self,
        uow: SqliteUnitOfWork,
        campaign_id: str,
        account_id: str,
    ) -> GrantRedemptionReceipt | None:
        row = uow.connection.execute(
            """
            SELECT redemption_id, entitlement_id, campaign_id, credential_id,
                   account_id, settlement_id, request_fingerprint, redeemed_at
            FROM grant_redemption
            WHERE campaign_id = ? AND account_id = ?
            ORDER BY redeemed_at, redemption_id
            LIMIT 1
            """,
            (campaign_id, account_id),
        ).fetchone()
        return self._redemption_from_row(uow, row) if row else None

    def _redemption_from_row(
        self,
        uow: SqliteUnitOfWork,
        row: sqlite3.Row,
    ) -> GrantRedemptionReceipt:
        settlement_id = str(row["settlement_id"])
        account_id = str(row["account_id"])
        committed = uow.load_transaction(settlement_id)
        if committed is None:
            raise CorruptPersistenceData("权益兑付记录缺少奖励提交事务")
        reward_receipt = self.codec.loads(committed.receipt_payload, RewardReceipt)
        if (
            committed.scope_id != account_id
            or reward_receipt.settlement_id != settlement_id
            or reward_receipt.fingerprint != committed.fingerprint
        ):
            raise CorruptPersistenceData("权益兑付记录与奖励提交事务不一致")
        return GrantRedemptionReceipt(
            str(row["redemption_id"]),
            str(row["entitlement_id"]),
            str(row["campaign_id"]),
            account_id,
            settlement_id,
            str(row["request_fingerprint"]),
            datetime.fromisoformat(str(row["redeemed_at"])),
            reward_receipt,
            str(row["credential_id"]) if row["credential_id"] is not None else None,
        )

    def insert_migration_manifest(
        self,
        uow: SqliteUnitOfWork,
        entry: MigrationManifestEntry,
    ) -> None:
        try:
            uow.connection.execute(
                """
                INSERT INTO migration_manifest(
                    batch_id, legacy_subject_id, legacy_asset_id, mapping_version,
                    target_account_id, entitlement_id, source_digest,
                    source_payload, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.batch_id,
                    entry.legacy_subject_id,
                    entry.legacy_asset_id,
                    entry.mapping_version,
                    entry.target_account_id,
                    entry.entitlement_id,
                    entry.source_digest,
                    self.codec.dumps(dict(entry.source_data)),
                    entry.imported_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConcurrencyConflict(
                f"迁移资产已经登记：{entry.batch_id}/{entry.legacy_subject_id}/{entry.legacy_asset_id}"
            ) from exc

    def load_migration_manifest(
        self,
        uow: SqliteUnitOfWork,
        batch_id: str,
        legacy_subject_id: str,
        legacy_asset_id: str,
    ) -> MigrationManifestEntry | None:
        row = uow.connection.execute(
            """
            SELECT * FROM migration_manifest
            WHERE batch_id = ? AND legacy_subject_id = ? AND legacy_asset_id = ?
            """,
            (batch_id, legacy_subject_id, legacy_asset_id),
        ).fetchone()
        if row is None:
            return None
        return MigrationManifestEntry(
            batch_id=str(row["batch_id"]),
            legacy_subject_id=str(row["legacy_subject_id"]),
            legacy_asset_id=str(row["legacy_asset_id"]),
            mapping_version=str(row["mapping_version"]),
            target_account_id=str(row["target_account_id"]),
            entitlement_id=str(row["entitlement_id"]),
            source_digest=str(row["source_digest"]),
            imported_at=datetime.fromisoformat(str(row["imported_at"])),
            source_data=self.codec.loads(str(row["source_payload"]), dict),
        )


class PersistedGrantService:
    """所有兑换码、小游戏回执、活动权益和迁移资产的唯一兑付入口。"""

    def __init__(
        self,
        database: SqliteDatabase,
        rewards: PersistedRewardSettlementService,
        *,
        code_secret: bytes | str,
        proof_secrets: Mapping[str, bytes | str] | None = None,
        engine: GrantEngine | None = None,
        repository: GrantRepository | None = None,
    ) -> None:
        if rewards.database.path != database.path:
            raise ValueError("权益服务与奖励服务必须使用同一个数据库")
        self.database = database
        self.rewards = rewards
        self.code_secret = code_secret
        self.proof_secrets = dict(proof_secrets or {})
        self.engine = engine or GrantEngine()
        self.repository = repository or GrantRepository()

    def create_campaign(self, campaign: GrantCampaign, *, created_at: datetime) -> None:
        with self.database.unit_of_work() as uow:
            previous = self.repository.load_campaign(uow, campaign.id)
            if previous is not None:
                if previous != campaign:
                    raise TransactionMismatch(f"同一权益活动 ID 对应不同内容：{campaign.id}")
                return
            self.repository.insert_campaign(uow, campaign, created_at=created_at)
            uow.commit()

    def register_code(
        self,
        credential_id: str,
        campaign_id: str,
        code: object,
        *,
        issued_at: datetime,
        usage_limit: int | None = None,
        expires_at: datetime | None = None,
        bound_account_id: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> GrantCredential:
        credential = GrantCredential(
            credential_id,
            campaign_id,
            GrantCredentialKind.CODE,
            grant_code_digest(self.code_secret, campaign_id, code),
            usage_limit,
            issued_at,
            bound_account_id,
            expires_at,
            None,
            GrantCredentialStatus.ACTIVE,
            metadata or {},
        )
        with self.database.unit_of_work() as uow:
            if self.repository.load_campaign(uow, campaign_id) is None:
                raise ValueError(f"权益活动不存在：{campaign_id}")
            previous = self.repository.find_credential_by_digest(
                uow,
                campaign_id,
                credential.digest,
            )
            if previous is not None:
                previous_credential, _ = previous
                if previous_credential != credential:
                    raise TransactionMismatch("同一兑换码摘要对应不同凭证内容")
                return previous_credential
            self.repository.insert_credential(uow, credential)
            uow.commit()
        return credential

    def find_account_redemption(
        self,
        campaign_id: str,
        account_id: str,
    ) -> GrantRedemptionReceipt | None:
        campaign_id = str(campaign_id or "").strip()
        account_id = str(account_id or "").strip()
        if not campaign_id or not account_id:
            raise ValueError("查询权益兑付记录缺少活动或账号身份")
        with self.database.unit_of_work(write=False) as uow:
            return self.repository.find_account_redemption(
                uow,
                campaign_id,
                account_id,
            )

    def issue_entitlements(
        self,
        campaign_id: str,
        entitlements: tuple[GrantEntitlement, ...],
        *,
        logical_time: datetime,
    ) -> None:
        _require_aware(logical_time)
        if not entitlements:
            raise ValueError("批量发放权益不能为空")
        with self.database.unit_of_work() as uow:
            campaign = self._require_campaign(uow, campaign_id)
            self._require_campaign_window(campaign, logical_time)
            for entitlement in entitlements:
                self._validate_entitlement(campaign, entitlement)
                self._insert_entitlement_idempotent(uow, entitlement)
            uow.commit()

    def issue_signed_entitlement(
        self,
        proof: GrantProof,
        signature: object,
        entitlement: GrantEntitlement,
        *,
        logical_time: datetime,
    ) -> GrantCredential:
        secret = self.proof_secrets.get(proof.issuer_id)
        if secret is None or not verify_grant_proof(secret, proof, signature):
            raise ValueError("外部权益回执签名无效")
        if logical_time < proof.issued_at or logical_time >= proof.expires_at:
            raise ValueError("外部权益回执不在有效时间窗内")
        if (
            entitlement.campaign_id != proof.campaign_id
            or entitlement.account_id != proof.account_id
            or entitlement.expires_at != proof.expires_at
        ):
            raise ValueError("外部权益回执与待发权益不一致")
        digest = grant_proof_digest(proof)
        credential = GrantCredential(
            f"credential:{digest[:32]}",
            proof.campaign_id,
            GrantCredentialKind.SIGNED_RECEIPT,
            digest,
            1,
            proof.issued_at,
            proof.account_id,
            proof.expires_at,
            f"{proof.issuer_id}:{proof.receipt_id}",
            GrantCredentialStatus.ACTIVE,
            {"nonce": proof.nonce, "payload_digest": proof.payload_digest},
        )
        proof_metadata = {
            "grant.proof_issuer": proof.issuer_id,
            "grant.proof_receipt_id": proof.receipt_id,
            "grant.proof_payload_digest": proof.payload_digest,
        }
        conflicts = {
            key
            for key, value in proof_metadata.items()
            if key in entitlement.metadata and entitlement.metadata[key] != value
        }
        if conflicts:
            raise ValueError(
                f"外部回执覆盖权益保留元数据：{', '.join(sorted(conflicts))}"
            )
        entitlement = replace(
            entitlement,
            credential_id=credential.id,
            metadata={**dict(entitlement.metadata), **proof_metadata},
        )
        with self.database.unit_of_work() as uow:
            campaign = self._require_campaign(uow, proof.campaign_id)
            self._require_campaign_window(campaign, logical_time)
            self._validate_entitlement(campaign, entitlement)
            previous_credential = self.repository.find_credential_by_digest(
                uow,
                campaign.id,
                credential.digest,
            )
            if previous_credential is None:
                self.repository.insert_credential(uow, credential)
            else:
                previous_value, _ = previous_credential
                if previous_value != credential:
                    raise TransactionMismatch("同一外部回执对应不同凭证内容")
            self._insert_entitlement_idempotent(uow, entitlement)
            uow.commit()
        return credential

    def issue_migration_entitlement(
        self,
        entry: MigrationManifestEntry,
        entitlement: GrantEntitlement,
    ) -> None:
        if entry.target_account_id != entitlement.account_id or entry.entitlement_id != entitlement.id:
            raise ValueError("迁移清单与领取权益不一致")
        with self.database.unit_of_work() as uow:
            campaign = self._require_campaign(uow, entitlement.campaign_id)
            self._require_campaign_window(campaign, entry.imported_at)
            self._validate_entitlement(campaign, entitlement)
            previous = self.repository.load_migration_manifest(
                uow,
                entry.batch_id,
                entry.legacy_subject_id,
                entry.legacy_asset_id,
            )
            if previous is not None:
                if previous != entry:
                    raise TransactionMismatch("同一迁移资产身份对应不同内容")
                existing_entitlement = self.repository.load_entitlement(uow, entitlement.id)
                if not self._same_issued_entitlement(existing_entitlement, entitlement):
                    raise CorruptPersistenceData("迁移清单与已有权益不一致")
                return
            self._insert_entitlement_idempotent(uow, entitlement)
            self.repository.insert_migration_manifest(uow, entry)
            uow.commit()

    def redeem_code(
        self,
        command: GrantRedemptionCommand,
        code: object,
        bundle: GrantRewardBundle,
        keys: RewardSettlementStorageKeys,
        *,
        context: RuleContext,
    ) -> RuleOutcome[GrantRedemptionExecution]:
        checkpoint = context.random.checkpoint()
        try:
            with self.database.unit_of_work() as uow:
                campaign = self._require_campaign(uow, command.campaign_id)
                digest = grant_code_digest(self.code_secret, campaign.id, code)
                loaded = self.repository.find_credential_by_digest(uow, campaign.id, digest)
                if loaded is None:
                    return RuleOutcome.failed(RuleFailure("grant.code_invalid", "兑换码无效"))
                credential, credential_used = loaded
                entitlement_id = code_entitlement_id(campaign.id, command.id, command.account_id)
                entitlement = self.repository.load_entitlement(uow, entitlement_id)
                if entitlement is None:
                    expires_at = _earliest(campaign.ends_at, credential.expires_at)
                    entitlement = GrantEntitlement(
                        entitlement_id,
                        campaign.id,
                        command.account_id,
                        campaign.offer_id,
                        campaign.offer_version,
                        context.logical_time,
                        credential.id,
                        expires_at,
                        metadata={"grant.method": "code"},
                    )
                    self.repository.insert_entitlement(uow, entitlement)
                command = replace(command, entitlement_id=entitlement.id)
                outcome = self._redeem_in_uow(
                    uow,
                    campaign,
                    entitlement,
                    command,
                    bundle,
                    keys,
                    context=context,
                    credential=credential,
                    credential_used=credential_used,
                )
                if outcome.failure:
                    return outcome
                uow.commit()
                return outcome
        except Exception:
            context.random.restore(checkpoint)
            raise

    def redeem_entitlement(
        self,
        command: GrantRedemptionCommand,
        bundle: GrantRewardBundle,
        keys: RewardSettlementStorageKeys,
        *,
        context: RuleContext,
    ) -> RuleOutcome[GrantRedemptionExecution]:
        if not command.entitlement_id:
            raise ValueError("直接兑付必须指定 entitlement_id")
        checkpoint = context.random.checkpoint()
        try:
            with self.database.unit_of_work() as uow:
                campaign = self._require_campaign(uow, command.campaign_id)
                entitlement = self.repository.load_entitlement(uow, command.entitlement_id)
                if entitlement is None:
                    return RuleOutcome.failed(RuleFailure("grant.entitlement_missing", "领取权益不存在"))
                credential = None
                credential_used = 0
                if entitlement.credential_id:
                    loaded = self.repository.load_credential(uow, entitlement.credential_id)
                    if loaded is None:
                        raise CorruptPersistenceData("权益引用了不存在的凭证")
                    credential, credential_used = loaded
                outcome = self._redeem_in_uow(
                    uow,
                    campaign,
                    entitlement,
                    command,
                    bundle,
                    keys,
                    context=context,
                    credential=credential,
                    credential_used=credential_used,
                )
                if outcome.failure:
                    return outcome
                uow.commit()
                return outcome
        except Exception:
            context.random.restore(checkpoint)
            raise

    def revoke_entitlement(self, entitlement_id: str, *, revoked_at: datetime) -> None:
        _require_aware(revoked_at)
        with self.database.unit_of_work() as uow:
            self.repository.revoke_entitlement(uow, entitlement_id, revoked_at=revoked_at)
            uow.commit()

    def revoke_credential(self, credential_id: str, *, revoked_at: datetime) -> None:
        _require_aware(revoked_at)
        with self.database.unit_of_work() as uow:
            self.repository.revoke_credential(uow, credential_id, revoked_at=revoked_at)
            uow.commit()

    def set_campaign_status(
        self,
        campaign_id: str,
        status: GrantCampaignStatus,
        *,
        expected_version: int,
        updated_at: datetime,
    ) -> None:
        _require_aware(updated_at)
        with self.database.unit_of_work() as uow:
            campaign = self._require_campaign(uow, campaign_id)
            target_status = GrantCampaignStatus(status)
            if campaign.version != expected_version:
                raise ConcurrencyConflict(f"权益活动版本冲突：{campaign_id}")
            if campaign.status is GrantCampaignStatus.REVOKED and target_status is not GrantCampaignStatus.REVOKED:
                raise ValueError("已经撤销的权益活动不能重新启用")
            if campaign.status is target_status:
                return
            self.repository.set_campaign_status(
                uow,
                campaign_id,
                target_status,
                expected_version=expected_version,
                updated_at=updated_at,
            )
            uow.commit()

    def _redeem_in_uow(
        self,
        uow: SqliteUnitOfWork,
        campaign: GrantCampaign,
        entitlement: GrantEntitlement,
        command: GrantRedemptionCommand,
        bundle: GrantRewardBundle,
        keys: RewardSettlementStorageKeys,
        *,
        context: RuleContext,
        credential: GrantCredential | None,
        credential_used: int,
    ) -> RuleOutcome[GrantRedemptionExecution]:
        settlement = self.engine.build_settlement(campaign, entitlement, command, bundle)
        fingerprint = self.engine.request_fingerprint(command, settlement)
        previous = self.repository.load_redemption(uow, redemption_id=command.id)
        if previous is not None:
            if (
                previous.request_fingerprint != fingerprint
                or previous.account_id != command.account_id
                or previous.entitlement_id != entitlement.id
            ):
                raise TransactionMismatch(f"同一权益兑付 ID 对应不同内容：{command.id}")
            reward = self.rewards.settle_in_uow(uow, settlement, keys, context=context)
            if reward.failure or reward.value is None or not reward.value.replayed:
                raise CorruptPersistenceData("权益兑付记录与奖励事务不一致")
            if reward.value.receipt != previous.reward_receipt:
                raise CorruptPersistenceData("权益凭据与奖励凭据不一致")
            return RuleOutcome.success(GrantRedemptionExecution(previous, reward.value, True))
        previous_entitlement = self.repository.load_redemption(
            uow,
            entitlement_id=entitlement.id,
        )
        if previous_entitlement is not None:
            return RuleOutcome.failed(RuleFailure("grant.entitlement_redeemed", "权益已经兑付"))

        usage = self.repository.usage(uow, campaign.id, command.account_id)
        usage = replace(usage, credential_used=credential_used)
        authorization = self.engine.authorize(
            campaign,
            entitlement,
            usage,
            command,
            logical_time=context.logical_time,
            credential=credential,
        )
        if authorization.failure:
            return RuleOutcome.failed(authorization.failure)
        self._ensure_reward_claim_scope(
            uow,
            command.account_id,
            logical_time=context.logical_time,
        )
        reward = self.rewards.settle_in_uow(uow, settlement, keys, context=context)
        if reward.failure:
            return RuleOutcome.failed(reward.failure)
        assert reward.value is not None
        if reward.value.replayed:
            raise CorruptPersistenceData("奖励已提交但权益兑付记录不存在")

        self.repository.mark_entitlement_redeemed(
            uow,
            entitlement.id,
            settlement.id,
            redeemed_at=context.logical_time,
        )
        if credential is not None:
            self.repository.increment_credential_usage(
                uow,
                credential.id,
                credential_used,
                updated_at=context.logical_time,
            )
        receipt = GrantRedemptionReceipt(
            command.id,
            entitlement.id,
            campaign.id,
            command.account_id,
            settlement.id,
            fingerprint,
            context.logical_time,
            reward.value.receipt,
            credential.id if credential else None,
        )
        self.repository.insert_redemption(uow, receipt)
        return RuleOutcome.success(GrantRedemptionExecution(receipt, reward.value, False))

    def _ensure_reward_claim_scope(
        self,
        uow: SqliteUnitOfWork,
        account_id: str,
        *,
        logical_time: datetime,
    ) -> None:
        existing = self.rewards.snapshots.load(
            uow,
            REWARD_CLAIM_AGGREGATE,
            account_id,
            RewardClaimState,
        )
        if existing is None:
            self.rewards.snapshots.insert(
                uow,
                REWARD_CLAIM_AGGREGATE,
                account_id,
                RewardClaimState(account_id),
                logical_time,
            )

    def _require_campaign(self, uow: SqliteUnitOfWork, campaign_id: str) -> GrantCampaign:
        campaign = self.repository.load_campaign(uow, campaign_id)
        if campaign is None:
            raise ValueError(f"权益活动不存在：{campaign_id}")
        return campaign

    def _insert_entitlement_idempotent(
        self,
        uow: SqliteUnitOfWork,
        entitlement: GrantEntitlement,
    ) -> None:
        previous = self.repository.load_entitlement(uow, entitlement.id)
        if previous is None:
            self.repository.insert_entitlement(uow, entitlement)
            return
        if not self._same_issued_entitlement(previous, entitlement):
            raise TransactionMismatch(f"同一权益 ID 对应不同内容：{entitlement.id}")

    @staticmethod
    def _same_issued_entitlement(
        previous: GrantEntitlement | None,
        expected: GrantEntitlement,
    ) -> bool:
        if previous is None:
            return False
        return (
            previous.id == expected.id
            and previous.campaign_id == expected.campaign_id
            and previous.account_id == expected.account_id
            and previous.offer_id == expected.offer_id
            and previous.offer_version == expected.offer_version
            and previous.issued_at == expected.issued_at
            and previous.credential_id == expected.credential_id
            and previous.expires_at == expected.expires_at
            and previous.metadata == expected.metadata
        )

    @staticmethod
    def _validate_entitlement(campaign: GrantCampaign, entitlement: GrantEntitlement) -> None:
        if entitlement.campaign_id != campaign.id:
            raise ValueError("领取权益不属于指定活动")
        if entitlement.offer_id != campaign.offer_id or entitlement.offer_version != campaign.offer_version:
            raise ValueError("领取权益奖励方案与活动不一致")

    @staticmethod
    def _require_campaign_window(campaign: GrantCampaign, logical_time: datetime) -> None:
        if campaign.status is not GrantCampaignStatus.ACTIVE:
            raise ValueError("权益活动当前不可发放")
        if logical_time < campaign.starts_at or (
            campaign.ends_at is not None and logical_time >= campaign.ends_at
        ):
            raise ValueError("权益活动不在有效时间窗内")


def _parse_datetime(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value is not None else None


def _datetime_text(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _earliest(first: datetime | None, second: datetime | None) -> datetime | None:
    values = tuple(value for value in (first, second) if value is not None)
    return min(values) if values else None


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("权益持久化时间必须包含时区")
