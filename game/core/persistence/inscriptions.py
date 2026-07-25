"""铭刻之羽消耗、实例改名和防重凭据的 SQLite 联合提交。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from ..gameplay.context import RuleContext
from ..gameplay.errors import RuleOutcome
from ..gameplay.inscription import (
    InscriptionCommand,
    InscriptionEngine,
    InscriptionPreference,
    InscriptionReceipt,
    WeaponAbilityInscriptionTarget,
    inscription_fingerprint,
)
from ..gameplay.inventory import InventoryState
from ..gameplay.weapon import WeaponState

from .errors import TransactionMismatch
from .snapshots import (
    INSCRIPTION_PREFERENCE_AGGREGATE,
    INVENTORY_AGGREGATE,
    WEAPON_AGGREGATE,
    SnapshotRepository,
)
from .sqlite import SqliteDatabase


class PersistedInscriptionService:
    """铭刻规则唯一数据库写入口，不让业务分别提交羽毛和名称。"""

    def __init__(
        self,
        database: SqliteDatabase,
        engine: InscriptionEngine,
        snapshots: SnapshotRepository | None = None,
    ) -> None:
        self.database = database
        self.engine = engine
        self.snapshots = snapshots or SnapshotRepository()

    def apply(
        self,
        command: InscriptionCommand,
        *,
        inventory_id: str,
        context: RuleContext,
    ) -> RuleOutcome[InscriptionReceipt]:
        if not inventory_id.strip():
            raise ValueError("inventory_id 不能为空")
        checkpoint = context.random.checkpoint()
        try:
            with self.database.unit_of_work() as uow:
                fingerprint = inscription_fingerprint(command)
                committed = uow.load_transaction(command.id)
                if committed is not None:
                    if (
                        committed.fingerprint != fingerprint
                        or committed.scope_id != command.actor_id
                    ):
                        raise TransactionMismatch(
                            f"同一铭刻事务 ID 对应不同内容：{command.id}"
                        )
                    receipt = self.snapshots.codec.loads(
                        committed.receipt_payload,
                        InscriptionReceipt,
                    )
                    return RuleOutcome.success(replace(receipt, replayed=True))

                inventory = self.snapshots.require(
                    uow,
                    INVENTORY_AGGREGATE,
                    inventory_id,
                    InventoryState,
                )
                weapon_state = None
                if isinstance(command.target, WeaponAbilityInscriptionTarget):
                    weapon_state = self.snapshots.require(
                        uow,
                        WEAPON_AGGREGATE,
                        command.target.weapon_asset_id,
                        WeaponState,
                    )
                outcome = self.engine.apply(
                    command,
                    inventory=inventory,
                    weapon_state=weapon_state,
                    context=context,
                )
                if outcome.failure:
                    return RuleOutcome.failed(outcome.failure)
                assert outcome.value is not None
                self.snapshots.update(
                    uow,
                    INVENTORY_AGGREGATE,
                    inventory_id,
                    inventory,
                    outcome.value.inventory,
                    context.logical_time,
                )
                timestamp = context.logical_time.isoformat()
                uow.insert_transaction(
                    command.id,
                    fingerprint,
                    command.actor_id,
                    self.snapshots.codec.dumps(outcome.value.receipt),
                    timestamp,
                )
                for sequence, event in enumerate(outcome.value.events):
                    uow.append_fact(
                        command.id,
                        sequence,
                        event.kind,
                        self.snapshots.codec.dumps(event),
                        timestamp,
                    )
                uow.commit()
                return RuleOutcome.success(outcome.value.receipt)
        except Exception:
            context.random.restore(checkpoint)
            raise

    def initialize_preference(
        self,
        owner_id: str,
        *,
        logical_time: datetime,
    ) -> InscriptionPreference:
        _aware(logical_time)
        preference = InscriptionPreference(owner_id)
        with self.database.unit_of_work() as uow:
            existing = self.snapshots.load(
                uow,
                INSCRIPTION_PREFERENCE_AGGREGATE,
                owner_id,
                InscriptionPreference,
            )
            if existing is None:
                self.snapshots.insert(
                    uow,
                    INSCRIPTION_PREFERENCE_AGGREGATE,
                    owner_id,
                    preference,
                    logical_time,
                )
                existing = preference
            uow.commit()
        return existing

    def load_preference(self, owner_id: str) -> InscriptionPreference | None:
        with self.database.unit_of_work(write=False) as uow:
            return self.snapshots.load(
                uow,
                INSCRIPTION_PREFERENCE_AGGREGATE,
                owner_id,
                InscriptionPreference,
            )

    def set_show_original_name(
        self,
        owner_id: str,
        show_original_name: bool,
        *,
        logical_time: datetime,
    ) -> InscriptionPreference:
        _aware(logical_time)
        with self.database.unit_of_work() as uow:
            previous = self.snapshots.require(
                uow,
                INSCRIPTION_PREFERENCE_AGGREGATE,
                owner_id,
                InscriptionPreference,
            )
            current = previous.changed(show_original_name)
            if current != previous:
                self.snapshots.update(
                    uow,
                    INSCRIPTION_PREFERENCE_AGGREGATE,
                    owner_id,
                    previous,
                    current,
                    logical_time,
                )
            uow.commit()
        return current


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("铭刻持久化逻辑时间必须包含时区")


__all__ = ["PersistedInscriptionService"]
