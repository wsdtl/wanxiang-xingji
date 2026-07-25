"""物品扣除、角色资源变化、防重回执与 Outbox 的 SQLite 联合提交。"""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

from ..gameplay.context import RuleContext
from ..gameplay.errors import RuleOutcome
from ..gameplay.inventory import (
    CharacterItemUse,
    CharacterItemUseEngine,
    ItemUseReceipt,
    item_use_fingerprint,
)
from ..gameplay.character import CharacterState
from ..gameplay.character import CharacterContribution
from ..gameplay.inventory import InventoryState
from .errors import CorruptPersistenceData, TransactionMismatch
from .snapshots import CHARACTER_AGGREGATE, INVENTORY_AGGREGATE, SnapshotRepository
from .sqlite import SqliteDatabase
from typing import Mapping


class PersistedItemUseService:
    """物品使用的唯一数据库写入口。"""

    def __init__(
        self,
        database: SqliteDatabase,
        engine: CharacterItemUseEngine,
        snapshots: SnapshotRepository | None = None,
    ) -> None:
        self.database = database
        self.engine = engine
        self.snapshots = snapshots or SnapshotRepository()

    def committed_receipt(
        self,
        transaction_id: str,
        *,
        actor_id: str,
    ) -> ItemUseReceipt | None:
        """在资产选择前读取已提交回执，供上层安全重放已消耗物品。"""

        if not transaction_id.strip() or not actor_id.strip():
            raise ValueError("transaction_id 和 actor_id 不能为空")
        with self.database.unit_of_work(write=False) as uow:
            committed = uow.load_transaction(transaction_id)
            if committed is None:
                return None
            if committed.scope_id != actor_id:
                raise TransactionMismatch(
                    f"物品使用事务作用域不匹配：{transaction_id}"
                )
            receipt = self.snapshots.codec.loads(
                committed.receipt_payload,
                ItemUseReceipt,
            )
            if receipt.transaction_id != transaction_id or receipt.actor_id != actor_id:
                raise CorruptPersistenceData("物品使用事务表与回执身份不一致")
            return replace(receipt, replayed=True)

    def use(
        self,
        command: CharacterItemUse,
        *,
        inventory_id: str,
        contributions: Mapping[str, tuple[CharacterContribution, ...]] | None = None,
        context: RuleContext,
    ) -> RuleOutcome[ItemUseReceipt]:
        if not inventory_id.strip():
            raise ValueError("inventory_id 不能为空")
        checkpoint = context.random.checkpoint()
        try:
            with self.database.unit_of_work() as uow:
                fingerprint = _persistence_fingerprint(command, inventory_id)
                committed = uow.load_transaction(command.id)
                if committed is not None:
                    if (
                        committed.fingerprint != fingerprint
                        or committed.scope_id != command.actor_id
                    ):
                        raise TransactionMismatch(
                            f"同一物品使用事务 ID 对应不同内容：{command.id}"
                        )
                    receipt = self.snapshots.codec.loads(
                        committed.receipt_payload,
                        ItemUseReceipt,
                    )
                    if (
                        receipt.transaction_id != command.id
                        or receipt.actor_id != command.actor_id
                        or receipt.target_id != command.target_id
                        or receipt.asset_id != command.asset_id
                        or receipt.ability_id != command.ability_use.ability_id
                    ):
                        raise CorruptPersistenceData(
                            "物品使用事务表、请求与回执身份不一致"
                        )
                    return RuleOutcome.success(replace(receipt, replayed=True))

                inventory = self.snapshots.require(
                    uow,
                    INVENTORY_AGGREGATE,
                    inventory_id,
                    InventoryState,
                )
                character_ids = tuple(dict.fromkeys((command.actor_id, command.target_id)))
                characters = {
                    character_id: self.snapshots.require(
                        uow,
                        CHARACTER_AGGREGATE,
                        character_id,
                        CharacterState,
                    )
                    for character_id in character_ids
                }
                outcome = self.engine.execute(
                    command,
                    inventory=inventory,
                    characters=characters,
                    contributions=contributions,
                    context=context,
                )
                if outcome.failure:
                    return RuleOutcome.failed(outcome.failure)
                assert outcome.value is not None

                if outcome.value.inventory != inventory:
                    self.snapshots.update(
                        uow,
                        INVENTORY_AGGREGATE,
                        inventory_id,
                        inventory,
                        outcome.value.inventory,
                        context.logical_time,
                    )
                for character_id, previous in characters.items():
                    current = outcome.value.characters[character_id]
                    if current != previous:
                        self.snapshots.update(
                            uow,
                            CHARACTER_AGGREGATE,
                            character_id,
                            previous,
                            current,
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


def _persistence_fingerprint(command: CharacterItemUse, inventory_id: str) -> str:
    payload = f"{item_use_fingerprint(command)}|{inventory_id}"
    return sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["PersistedItemUseService"]
