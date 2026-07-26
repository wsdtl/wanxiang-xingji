"""把统一奖励规则结果原子提交到 SQLite。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from ..gameplay.context import RuleContext
from ..gameplay.economy import LedgerState
from ..gameplay.errors import RuleOutcome
from ..gameplay.events import RuleEvent
from ..gameplay.inventory import InventoryState
from ..gameplay.character import CharacterState
from ..gameplay.rewards import (
    RewardClaimState,
    RewardReceipt,
    RewardSettlement,
    RewardSettlementEngine,
    RewardSettlementExecution,
    RewardSettlementSnapshot,
    reward_fingerprint,
)
from ..gameplay.weapon import WeaponState

from .errors import CorruptPersistenceData, TransactionMismatch
from .snapshots import (
    CHARACTER_AGGREGATE,
    INVENTORY_AGGREGATE,
    LEDGER_AGGREGATE,
    REWARD_CLAIM_AGGREGATE,
    WEAPON_AGGREGATE,
    SnapshotRepository,
)
from .sqlite import OutboxEventRow, SqliteDatabase, SqliteUnitOfWork


@dataclass(frozen=True)
class RewardSettlementStorageKeys:
    """一次结算从哪些持久化聚合组装规则快照。"""

    inventory_id: str
    ledger_id: str
    character_ids: tuple[str, ...] = ()
    weapon_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.inventory_id.strip() or not self.ledger_id.strip():
            raise ValueError("RewardSettlementStorageKeys 缺少库存或账本聚合 id")
        if len(self.character_ids) != len(set(self.character_ids)):
            raise ValueError("RewardSettlementStorageKeys 包含重复角色聚合 id")
        if len(self.weapon_ids) != len(set(self.weapon_ids)):
            raise ValueError("RewardSettlementStorageKeys 包含重复武器聚合 id")
        characters = tuple(sorted(self.character_ids))
        weapons = tuple(sorted(self.weapon_ids))
        if any(not value.strip() for value in (*characters, *weapons)):
            raise ValueError("RewardSettlementStorageKeys 包含空聚合 id")
        object.__setattr__(self, "character_ids", characters)
        object.__setattr__(self, "weapon_ids", weapons)


@dataclass(frozen=True)
class PendingRuleEvent:
    transaction_id: str
    sequence: int
    event: RuleEvent
    created_at: datetime


class PersistedRewardSettlementService:
    """规则计算与数据库提交之间唯一允许的奖励写入口。"""

    def __init__(
        self,
        database: SqliteDatabase,
        engine: RewardSettlementEngine,
        snapshots: SnapshotRepository | None = None,
    ) -> None:
        self.database = database
        self.engine = engine
        self.snapshots = snapshots or SnapshotRepository()

    def initialize_snapshot(
        self,
        keys: RewardSettlementStorageKeys,
        snapshot: RewardSettlementSnapshot,
        *,
        logical_time: datetime,
    ) -> None:
        """只用于创建新聚合；任何已存在行都会让整批初始化回滚。"""

        if snapshot.claims.scope_id == "":
            raise ValueError("奖励领取作用域不能为空")
        with self.database.unit_of_work() as uow:
            self.snapshots.insert(
                uow,
                INVENTORY_AGGREGATE,
                keys.inventory_id,
                snapshot.inventory,
                logical_time,
            )
            self.snapshots.insert(
                uow,
                LEDGER_AGGREGATE,
                keys.ledger_id,
                snapshot.ledger,
                logical_time,
            )
            if set(keys.character_ids) != set(snapshot.characters):
                raise ValueError("初始化角色聚合 ID 与快照不一致")
            if set(keys.weapon_ids) != set(snapshot.weapons):
                raise ValueError("初始化武器聚合 ID 与快照不一致")
            for character_id in keys.character_ids:
                self.snapshots.insert(
                    uow,
                    CHARACTER_AGGREGATE,
                    character_id,
                    snapshot.characters[character_id],
                    logical_time,
                )
            for asset_id in keys.weapon_ids:
                self.snapshots.insert(
                    uow,
                    WEAPON_AGGREGATE,
                    asset_id,
                    snapshot.weapons[asset_id],
                    logical_time,
                )
            self.snapshots.insert(
                uow,
                REWARD_CLAIM_AGGREGATE,
                snapshot.claims.scope_id,
                snapshot.claims,
                logical_time,
            )
            uow.commit()

    def load_snapshot(
        self,
        keys: RewardSettlementStorageKeys,
        *,
        claim_scope_id: str,
    ) -> RewardSettlementSnapshot:
        with self.database.unit_of_work(write=False) as uow:
            return self._load_snapshot(uow, keys, claim_scope_id)

    def is_settled_in_uow(
        self,
        uow: SqliteUnitOfWork,
        claim_scope_id: str,
        settlement_id: str,
    ) -> bool:
        """从永久关系记录判断奖励是否已经提交，并校验双写事实一致。"""

        if not claim_scope_id.strip() or not settlement_id.strip():
            raise ValueError("奖励领取作用域和结算 ID 不能为空")
        committed = uow.load_transaction(settlement_id)
        claim = uow.load_reward_claim(claim_scope_id, settlement_id)
        if committed is None and claim is None:
            return False
        if committed is None or claim is None:
            raise CorruptPersistenceData("奖励提交事务与关系化领取记录不完整")
        if (
            committed.scope_id != claim_scope_id
            or committed.fingerprint != claim.fingerprint
        ):
            raise CorruptPersistenceData("奖励提交事务与关系化领取记录不一致")
        return True

    def settle(
        self,
        settlement: RewardSettlement,
        keys: RewardSettlementStorageKeys,
        *,
        context: RuleContext,
    ) -> RuleOutcome[RewardSettlementExecution]:
        checkpoint = context.random.checkpoint()
        try:
            with self.database.unit_of_work() as uow:
                outcome = self.settle_in_uow(
                    uow,
                    settlement,
                    keys,
                    context=context,
                )
                if outcome.failure:
                    return outcome
                uow.commit()
                return outcome
        except Exception:
            context.random.restore(checkpoint)
            raise

    def settle_in_uow(
        self,
        uow: SqliteUnitOfWork,
        settlement: RewardSettlement,
        keys: RewardSettlementStorageKeys,
        *,
        context: RuleContext,
    ) -> RuleOutcome[RewardSettlementExecution]:
        """在调用方持有的事务中结算；本方法绝不自行提交。"""

        checkpoint = context.random.checkpoint()
        try:
            snapshot = self._load_snapshot(uow, keys, settlement.claim_scope_id)
            fingerprint = reward_fingerprint(settlement)
            committed = uow.load_transaction(settlement.id)
            if committed is not None:
                if (
                    committed.fingerprint != fingerprint
                    or committed.scope_id != settlement.claim_scope_id
                ):
                    raise TransactionMismatch(
                        f"同一奖励事务 ID 对应不同内容：{settlement.id}"
                    )
                claim = uow.load_reward_claim(
                    settlement.claim_scope_id,
                    settlement.id,
                )
                if claim is None:
                    raise CorruptPersistenceData(
                        "数据库已有奖励提交事务，但缺少关系化领取记录"
                    )
                receipt = self.snapshots.codec.loads(
                    committed.receipt_payload,
                    RewardReceipt,
                )
                if (
                    claim.fingerprint != fingerprint
                    or claim.resulting_revision > snapshot.claims.revision
                ):
                    raise CorruptPersistenceData("事务表与奖励领取记录不一致")
                return RuleOutcome.success(
                    RewardSettlementExecution(
                        settlement.id,
                        snapshot,
                        receipt,
                        (),
                        replayed=True,
                    )
                )

            outcome = self.engine.settle(
                settlement,
                snapshot=snapshot,
                context=context,
            )
            if outcome.failure:
                return outcome
            assert outcome.value is not None
            if outcome.value.replayed:
                raise CorruptPersistenceData(
                    "领取快照声明奖励已完成，但缺少数据库提交事务"
                )
            timestamp = context.logical_time.isoformat()
            uow.insert_transaction(
                settlement.id,
                fingerprint,
                settlement.claim_scope_id,
                self.snapshots.codec.dumps(outcome.value.receipt),
                timestamp,
            )
            self._save_changed(
                uow,
                keys,
                snapshot,
                outcome.value.snapshot,
                context.logical_time,
            )
            for sequence, event in enumerate(outcome.value.events):
                uow.append_fact(
                    settlement.id,
                    sequence,
                    event.kind,
                    self.snapshots.codec.dumps(event),
                    timestamp,
                )
            compacted = RewardSettlementSnapshot(
                outcome.value.snapshot.inventory,
                self.snapshots.compact(outcome.value.snapshot.ledger),
                outcome.value.snapshot.characters,
                outcome.value.snapshot.weapons,
                self.snapshots.compact(outcome.value.snapshot.claims),
            )
            return RuleOutcome.success(replace(outcome.value, snapshot=compacted))
        except Exception:
            context.random.restore(checkpoint)
            raise

    def pending_events(self, *, limit: int = 100) -> tuple[PendingRuleEvent, ...]:
        with self.database.unit_of_work(write=False) as uow:
            rows = uow.pending_outbox(limit=limit)
            return tuple(self._pending_event(row) for row in rows)

    def mark_event_published(
        self,
        transaction_id: str,
        sequence: int,
        *,
        published_at: datetime,
    ) -> None:
        _require_aware(published_at)
        with self.database.unit_of_work() as uow:
            uow.mark_outbox_published(
                transaction_id,
                sequence,
                published_at.isoformat(),
            )
            uow.commit()

    def _load_snapshot(self, uow, keys, claim_scope_id) -> RewardSettlementSnapshot:
        inventory = self.snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            keys.inventory_id,
            InventoryState,
        )
        ledger = self.snapshots.require(
            uow,
            LEDGER_AGGREGATE,
            keys.ledger_id,
            LedgerState,
        )
        characters = {
            character_id: self.snapshots.require(
                uow,
                CHARACTER_AGGREGATE,
                character_id,
                CharacterState,
            )
            for character_id in keys.character_ids
        }
        weapons = {
            asset_id: self.snapshots.require(
                uow,
                WEAPON_AGGREGATE,
                asset_id,
                WeaponState,
            )
            for asset_id in keys.weapon_ids
        }
        claims = self.snapshots.require(
            uow,
            REWARD_CLAIM_AGGREGATE,
            claim_scope_id,
            RewardClaimState,
        )
        return RewardSettlementSnapshot(inventory, ledger, characters, weapons, claims)

    def _save_changed(self, uow, keys, previous, current, logical_time) -> None:
        self._update_if_changed(
            uow,
            INVENTORY_AGGREGATE,
            keys.inventory_id,
            previous.inventory,
            current.inventory,
            logical_time,
        )
        self._update_if_changed(
            uow,
            LEDGER_AGGREGATE,
            keys.ledger_id,
            previous.ledger,
            current.ledger,
            logical_time,
        )
        for character_id in keys.character_ids:
            self._update_if_changed(
                uow,
                CHARACTER_AGGREGATE,
                character_id,
                previous.characters[character_id],
                current.characters[character_id],
                logical_time,
            )
        for asset_id in keys.weapon_ids:
            self._update_if_changed(
                uow,
                WEAPON_AGGREGATE,
                asset_id,
                previous.weapons[asset_id],
                current.weapons[asset_id],
                logical_time,
            )
        for asset_id in sorted(set(current.weapons) - set(previous.weapons)):
            self.snapshots.insert(
                uow,
                WEAPON_AGGREGATE,
                asset_id,
                current.weapons[asset_id],
                logical_time,
            )
        self._update_if_changed(
            uow,
            REWARD_CLAIM_AGGREGATE,
            previous.claims.scope_id,
            previous.claims,
            current.claims,
            logical_time,
        )

    def _update_if_changed(
        self,
        uow,
        aggregate_kind,
        aggregate_id,
        previous,
        current,
        logical_time,
    ) -> None:
        if previous == current:
            return
        self.snapshots.update(
            uow,
            aggregate_kind,
            aggregate_id,
            previous,
            current,
            logical_time,
        )

    def _pending_event(self, row: OutboxEventRow) -> PendingRuleEvent:
        created_at = datetime.fromisoformat(row.created_at)
        _require_aware(created_at)
        return PendingRuleEvent(
            row.transaction_id,
            row.sequence,
            self.snapshots.codec.loads(row.payload, RuleEvent),
            created_at,
        )


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("持久化审计时间必须包含时区")


__all__ = [
    "PendingRuleEvent",
    "PersistedRewardSettlementService",
    "RewardSettlementStorageKeys",
]
