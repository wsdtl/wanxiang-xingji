"""账号、外部身份和已验证凭据的关系型 SQLite 持久化。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from hashlib import sha256
import hmac
import sqlite3

from ..account import (
    AccountDirectoryState,
    AccountEngine,
    AccountEvent,
    AccountMutation,
    AccountResolution,
    AccountState,
    AccountStatus,
    AccountStatusTransaction,
    ExternalIdentity,
    IdentityBinding,
    IdentityEvidence,
    UnbindIdentityTransaction,
)

from .errors import ConcurrencyConflict, CorruptPersistenceData, TransactionMismatch
from .snapshots import SnapshotRepository
from .sqlite import SqliteDatabase, SqliteUnitOfWork


class PersistedAccountService:
    """账号规则唯一数据库入口，数据库中不保存原始平台身份。"""

    def __init__(
        self,
        database: SqliteDatabase,
        engine: AccountEngine,
        identity_secret: bytes | str,
        snapshots: SnapshotRepository | None = None,
    ) -> None:
        secret = identity_secret.encode("utf-8") if isinstance(identity_secret, str) else bytes(identity_secret)
        if len(secret) < 16:
            raise ValueError("账号身份 HMAC 密钥至少需要 16 字节")
        self.database = database
        self.engine = engine
        self.identity_secret = secret
        self.codec = (snapshots or SnapshotRepository()).codec

    def resolve_identity(self, evidence: IdentityEvidence) -> AccountResolution:
        protected = self._protect_evidence(evidence)
        # 同一平台事件可能在不同进程时间被重投；处理时间不属于身份集合。
        fingerprint = self._fingerprint(
            "account-evidence.v2",
            (
                protected.id,
                protected.primary,
                protected.aliases,
                protected.source_kind,
            ),
        )
        transaction_id = f"account:evidence:{protected.id}"
        with self.database.unit_of_work() as uow:
            previous = uow.connection.execute(
                "SELECT fingerprint, transaction_id FROM account_evidence WHERE evidence_id = ?",
                (protected.id,),
            ).fetchone()
            if previous is not None:
                if str(previous["fingerprint"]) != fingerprint:
                    raise TransactionMismatch("同一账号身份凭据对应不同身份集合")
                committed = uow.load_transaction(str(previous["transaction_id"]))
                if committed is None or committed.fingerprint != fingerprint:
                    raise CorruptPersistenceData("账号身份凭据缺少匹配的提交事务")
                receipt = self.codec.loads(committed.receipt_payload, AccountResolution)
                return replace(receipt, replayed=True)

            state = self._state_for_identities(uow, protected.identities)
            resolution = self._resolve_without_id_collision(uow, protected, state)
            self._persist_resolution(uow, state, resolution, protected.logical_time)
            timestamp = protected.logical_time.isoformat()
            receipt_payload = self.codec.dumps(resolution)
            uow.insert_transaction(
                transaction_id,
                fingerprint,
                resolution.account.id if resolution.account else resolution.conflict.id,
                receipt_payload,
                timestamp,
            )
            for sequence, event in enumerate(resolution.events):
                self._append_event(uow, transaction_id, sequence, event, timestamp)
            uow.connection.execute(
                """
                INSERT INTO account_evidence(
                    evidence_id, fingerprint, account_id, conflict_id,
                    transaction_id, processed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    protected.id,
                    fingerprint,
                    resolution.account.id if resolution.account else None,
                    resolution.conflict.id if resolution.conflict else None,
                    transaction_id,
                    timestamp,
                ),
            )
            uow.commit()
            return resolution

    def _resolve_without_id_collision(
        self,
        uow: SqliteUnitOfWork,
        evidence: IdentityEvidence,
        state: AccountDirectoryState,
    ) -> AccountResolution:
        current = state
        for _ in range(32):
            try:
                resolution = self.engine.resolve_identity(evidence, state=current)
            except RuntimeError as exc:
                if "产生重复账号 id" not in str(exc):
                    raise
                continue
            if not resolution.created or resolution.account is None:
                return resolution
            occupied = self._load_account(uow, resolution.account.id)
            if occupied is None:
                return resolution
            current = AccountDirectoryState(
                accounts={**dict(current.accounts), occupied.id: occupied},
                bindings=current.bindings,
            )
        raise RuntimeError("账号 ID 生成器连续产生重复身份")

    def load_account(self, account_id: str) -> AccountState | None:
        with self.database.unit_of_work(write=False) as uow:
            return self._load_account(uow, account_id)

    def find_existing_account(self, identity: ExternalIdentity) -> AccountState | None:
        """按已知外部身份只读查找账号，不为陌生对手创建账号。"""

        protected = self._protect_identity(identity)
        with self.database.unit_of_work(write=False) as uow:
            state = self._state_for_identities(uow, (protected,))
            account_ids = {
                binding.account_id for binding in state.bindings.values()
            }
            if len(account_ids) != 1:
                return None
            return self._load_account(uow, next(iter(account_ids)))

    def change_status(self, transaction: AccountStatusTransaction) -> AccountMutation:
        return self._mutate(
            transaction.id,
            transaction.account_id,
            transaction.logical_time,
            transaction,
            operation="status",
        )

    def unbind_identity(self, transaction: UnbindIdentityTransaction) -> AccountMutation:
        protected = replace(transaction, identity=self._protect_identity(transaction.identity))
        return self._mutate(
            protected.id,
            protected.account_id,
            protected.logical_time,
            protected,
            operation="unbind",
        )

    def identity_count(self, account_id: str) -> int:
        with self.database.unit_of_work(write=False) as uow:
            row = uow.connection.execute(
                "SELECT COUNT(*) AS count FROM account_identity WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            return int(row["count"])

    def _mutate(
        self,
        transaction_id: str,
        account_id: str,
        logical_time: datetime,
        transaction: AccountStatusTransaction | UnbindIdentityTransaction,
        *,
        operation: str,
    ) -> AccountMutation:
        fingerprint = self._fingerprint(f"account-{operation}.v1", transaction)
        with self.database.unit_of_work() as uow:
            previous = uow.load_transaction(transaction_id)
            if previous is not None:
                if previous.fingerprint != fingerprint or previous.scope_id != account_id:
                    raise TransactionMismatch(f"同一账号事务 ID 对应不同内容：{transaction_id}")
                receipt = self.codec.loads(previous.receipt_payload, AccountMutation)
                return replace(receipt, replayed=True)
            state = self._state_for_account(uow, account_id)
            if operation == "status":
                assert isinstance(transaction, AccountStatusTransaction)
                mutation = self.engine.change_status(transaction, state=state)
            else:
                assert isinstance(transaction, UnbindIdentityTransaction)
                mutation = self.engine.unbind_identity(transaction, state=state)
            previous_account = state.accounts[account_id]
            self._update_account(uow, previous_account, mutation.account, logical_time)
            if operation == "unbind":
                assert isinstance(transaction, UnbindIdentityTransaction)
                self._delete_binding(uow, transaction.identity, account_id)
            timestamp = logical_time.isoformat()
            payload = self.codec.dumps(mutation)
            uow.insert_transaction(
                transaction_id,
                fingerprint,
                account_id,
                payload,
                timestamp,
            )
            for sequence, event in enumerate(mutation.events):
                self._append_event(uow, transaction_id, sequence, event, timestamp)
            uow.commit()
            return mutation

    def _state_for_identities(
        self,
        uow: SqliteUnitOfWork,
        identities: tuple[ExternalIdentity, ...],
    ) -> AccountDirectoryState:
        bindings: dict[tuple[str, str, str, str, str], IdentityBinding] = {}
        account_ids: set[str] = set()
        for identity in identities:
            row = uow.connection.execute(
                """
                SELECT account_id, bound_at, source_evidence_id
                FROM account_identity
                WHERE provider_id = ? AND tenant_digest = ? AND subject_kind = ?
                  AND scope_digest = ? AND identity_digest = ?
                """,
                identity.key,
            ).fetchone()
            if row is None:
                continue
            binding = IdentityBinding(
                identity,
                str(row["account_id"]),
                datetime.fromisoformat(str(row["bound_at"])),
                str(row["source_evidence_id"]),
            )
            bindings[identity.key] = binding
            account_ids.add(binding.account_id)
        accounts = {
            account_id: self._require_account(uow, account_id)
            for account_id in account_ids
        }
        return AccountDirectoryState(accounts=accounts, bindings=bindings)

    def _state_for_account(
        self,
        uow: SqliteUnitOfWork,
        account_id: str,
    ) -> AccountDirectoryState:
        account = self._require_account(uow, account_id)
        rows = uow.connection.execute(
            """
            SELECT provider_id, tenant_digest, subject_kind, scope_digest,
                   identity_digest, bound_at, source_evidence_id
            FROM account_identity WHERE account_id = ?
            """,
            (account_id,),
        ).fetchall()
        bindings = {}
        for row in rows:
            identity = ExternalIdentity(
                str(row["provider_id"]),
                str(row["tenant_digest"]),
                str(row["subject_kind"]),
                str(row["scope_digest"]),
                str(row["identity_digest"]),
            )
            bindings[identity.key] = IdentityBinding(
                identity,
                account_id,
                datetime.fromisoformat(str(row["bound_at"])),
                str(row["source_evidence_id"]),
            )
        return AccountDirectoryState(accounts={account_id: account}, bindings=bindings)

    def _persist_resolution(
        self,
        uow: SqliteUnitOfWork,
        previous: AccountDirectoryState,
        resolution: AccountResolution,
        logical_time: datetime,
    ) -> None:
        for account_id, account in resolution.directory.accounts.items():
            old = previous.accounts.get(account_id)
            if old is None:
                old = self._load_account(uow, account_id)
            if old is None:
                try:
                    uow.connection.execute(
                        """
                        INSERT INTO account_record(
                            account_id, status, revision, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            account.id,
                            account.status.value,
                            account.revision,
                            account.created_at.isoformat(),
                            account.created_at.isoformat(),
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ConcurrencyConflict(f"账号已经存在：{account.id}") from exc
            elif account != old:
                self._update_account(uow, old, account, logical_time)
        for key, binding in resolution.directory.bindings.items():
            if key in previous.bindings:
                continue
            identity = binding.identity
            try:
                uow.connection.execute(
                    """
                    INSERT INTO account_identity(
                        provider_id, tenant_digest, subject_kind, scope_digest,
                        identity_digest, account_id, bound_at, source_evidence_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        *identity.key,
                        binding.account_id,
                        binding.bound_at.isoformat(),
                        binding.source_evidence_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ConcurrencyConflict("外部身份已经绑定到其他账号") from exc
        if resolution.conflict is not None:
            conflict = resolution.conflict
            uow.connection.execute(
                """
                INSERT INTO account_conflict(
                    conflict_id, identity_keys_payload, account_ids_payload,
                    source_kind, detected_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    conflict.id,
                    self.codec.dumps(conflict.identity_keys),
                    self.codec.dumps(conflict.account_ids),
                    conflict.source_kind,
                    conflict.detected_at.isoformat(),
                ),
            )

    def _load_account(self, uow: SqliteUnitOfWork, account_id: str) -> AccountState | None:
        row = uow.connection.execute(
            "SELECT account_id, status, revision, created_at FROM account_record WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        if row is None:
            return None
        return AccountState(
            str(row["account_id"]),
            AccountStatus(str(row["status"])),
            datetime.fromisoformat(str(row["created_at"])),
            int(row["revision"]),
        )

    def _require_account(self, uow: SqliteUnitOfWork, account_id: str) -> AccountState:
        account = self._load_account(uow, account_id)
        if account is None:
            raise ValueError(f"账号不存在：{account_id}")
        return account

    @staticmethod
    def _update_account(
        uow: SqliteUnitOfWork,
        previous: AccountState,
        current: AccountState,
        logical_time: datetime,
    ) -> None:
        if current.revision != previous.revision + 1:
            raise CorruptPersistenceData("账号更新必须恰好增加一个 revision")
        cursor = uow.connection.execute(
            """
            UPDATE account_record
            SET status = ?, revision = ?, updated_at = ?
            WHERE account_id = ? AND revision = ?
            """,
            (
                current.status.value,
                current.revision,
                logical_time.isoformat(),
                current.id,
                previous.revision,
            ),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict(f"账号 revision 冲突：{current.id}")

    @staticmethod
    def _delete_binding(
        uow: SqliteUnitOfWork,
        identity: ExternalIdentity,
        account_id: str,
    ) -> None:
        cursor = uow.connection.execute(
            """
            DELETE FROM account_identity
            WHERE provider_id = ? AND tenant_digest = ? AND subject_kind = ?
              AND scope_digest = ? AND identity_digest = ? AND account_id = ?
            """,
            (*identity.key, account_id),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyConflict("待解绑身份已经变化")

    def _append_event(
        self,
        uow: SqliteUnitOfWork,
        transaction_id: str,
        sequence: int,
        event: AccountEvent,
        timestamp: str,
    ) -> None:
        uow.append_fact(
            transaction_id,
            sequence,
            event.kind,
            self.codec.dumps(event),
            timestamp,
        )

    def _protect_evidence(self, evidence: IdentityEvidence) -> IdentityEvidence:
        evidence_id = self._digest("evidence", evidence.id)
        identities = tuple(self._protect_identity(identity) for identity in evidence.identities)
        return IdentityEvidence(
            evidence_id,
            identities[0],
            identities[1:],
            evidence.source_kind,
            evidence.logical_time,
        )

    def _protect_identity(self, identity: ExternalIdentity) -> ExternalIdentity:
        return ExternalIdentity(
            identity.provider_id,
            self._digest("tenant", identity.tenant_id),
            identity.subject_kind,
            self._digest("scope", identity.scope_id) if identity.scope_id else "",
            self._digest("identity", identity.external_id),
        )

    def _digest(self, domain: str, value: str) -> str:
        payload = f"account-identity.v1\0{domain}\0{value}".encode("utf-8")
        return hmac.new(self.identity_secret, payload, sha256).hexdigest()

    def _fingerprint(self, domain: str, value: object) -> str:
        payload = f"{domain}\0{self.codec.dumps(value)}".encode("utf-8")
        return sha256(payload).hexdigest()


__all__ = ["PersistedAccountService"]
