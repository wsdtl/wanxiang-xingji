"""武器成长道具、武库实例和武器聚合的 SQLite 联合提交。"""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

from ..gameplay.context import RuleContext
from ..gameplay.errors import RuleOutcome, RuleViolation
from ..gameplay.inventory import (
    AssetAvailability,
    ConsumeStack,
    InventoryEngine,
    InventoryState,
    InventoryTransaction,
    ItemCatalog,
    ItemStack,
    UpdateInstance,
)
from ..gameplay.weapon import (
    WEAPON_EXPERIENCE_ITEM_COMPONENT_ID,
    WEAPON_MAXIMUM_LEVEL_ITEM_COMPONENT_ID,
    WEAPON_STATE_DATA_KEY,
    WeaponEngine,
    WeaponExperienceTransaction,
    WeaponItemUseCommand,
    WeaponItemUseReceipt,
    WeaponExperienceItemComponent,
    WeaponMaximumLevelItemComponent,
    WeaponMaximumLevelTransaction,
    WeaponState,
    weapon_item_use_fingerprint,
    weapon_state_data,
)
from .errors import CorruptPersistenceData, TransactionMismatch
from .snapshots import (
    INVENTORY_AGGREGATE,
    WEAPON_AGGREGATE,
    SnapshotRepository,
)
from .sqlite import SqliteDatabase


class PersistedWeaponItemUseService:
    """武器成长道具的唯一数据库写入口。"""

    def __init__(
        self,
        database: SqliteDatabase,
        items: ItemCatalog,
        inventory_engine: InventoryEngine,
        weapon_engine: WeaponEngine,
        snapshots: SnapshotRepository | None = None,
    ) -> None:
        self.database = database
        self.items = items
        self.inventory_engine = inventory_engine
        self.weapon_engine = weapon_engine
        self.snapshots = snapshots or SnapshotRepository()

    def use(
        self,
        command: WeaponItemUseCommand,
        *,
        inventory_id: str,
        context: RuleContext,
    ) -> RuleOutcome[WeaponItemUseReceipt]:
        if not inventory_id.strip():
            raise ValueError("inventory_id 不能为空")
        checkpoint = context.random.checkpoint()
        try:
            with self.database.unit_of_work() as uow:
                fingerprint = _persistence_fingerprint(command, inventory_id)
                committed = uow.load_transaction(command.id)
                if committed is not None:
                    if committed.fingerprint != fingerprint or committed.scope_id != command.actor_id:
                        raise TransactionMismatch(
                            f"同一武器道具事务 ID 对应不同内容：{command.id}"
                        )
                    receipt = self.snapshots.codec.loads(
                        committed.receipt_payload,
                        WeaponItemUseReceipt,
                    )
                    if (
                        receipt.transaction_id != command.id
                        or receipt.actor_id != command.actor_id
                        or receipt.item_asset_id != command.item_asset_id
                        or receipt.weapon_asset_id != command.weapon_asset_id
                    ):
                        raise CorruptPersistenceData("武器道具事务表、请求与回执身份不一致")
                    return RuleOutcome.success(replace(receipt, replayed=True))

                inventory = self.snapshots.require(
                    uow,
                    INVENTORY_AGGREGATE,
                    inventory_id,
                    InventoryState,
                )
                weapon = self.snapshots.require(
                    uow,
                    WEAPON_AGGREGATE,
                    command.weapon_asset_id,
                    WeaponState,
                )
                try:
                    next_inventory, next_weapon, receipt, events = self._execute(
                        command,
                        inventory,
                        weapon,
                        context,
                    )
                except RuleViolation as exc:
                    context.random.restore(checkpoint)
                    return RuleOutcome.failed(exc.failure)
                self.snapshots.update(
                    uow,
                    INVENTORY_AGGREGATE,
                    inventory_id,
                    inventory,
                    next_inventory,
                    context.logical_time,
                )
                self.snapshots.update(
                    uow,
                    WEAPON_AGGREGATE,
                    weapon.asset_id,
                    weapon,
                    next_weapon,
                    context.logical_time,
                )
                timestamp = context.logical_time.isoformat()
                uow.insert_transaction(
                    command.id,
                    fingerprint,
                    command.actor_id,
                    self.snapshots.codec.dumps(receipt),
                    timestamp,
                )
                for sequence, event in enumerate(events):
                    uow.append_fact(
                        command.id,
                        sequence,
                        event.kind,
                        self.snapshots.codec.dumps(event),
                        timestamp,
                    )
                uow.commit()
                return RuleOutcome.success(receipt)
        except Exception:
            context.random.restore(checkpoint)
            raise

    def _execute(self, command, inventory, weapon, context):
        try:
            item_asset = inventory.asset(command.item_asset_id)
        except KeyError as exc:
            raise RuleViolation("weapon_item.item_unknown", "找不到武器成长道具") from exc
        if not isinstance(item_asset, ItemStack):
            self._fail("weapon_item.item_not_stack", "武器成长道具必须是可堆叠物品")
        if inventory.owner_of(item_asset.id) != command.actor_id:
            self._fail("weapon_item.item_owner_mismatch", "武器成长道具不属于当前角色")
        if inventory.available_quantity(item_asset.id) < 1:
            self._fail("weapon_item.item_unavailable", "武器成长道具当前不可使用")
        try:
            weapon_asset = inventory.instances[command.weapon_asset_id]
        except KeyError as exc:
            raise RuleViolation("weapon_item.weapon_unknown", "找不到目标武器") from exc
        if inventory.owner_of(weapon_asset.id) != command.actor_id:
            self._fail("weapon_item.weapon_owner_mismatch", "目标武器不属于当前角色")
        if inventory.availability(weapon_asset.id) is not AssetAvailability.AVAILABLE:
            self._fail("weapon_item.weapon_unavailable", "目标武器当前被其他流程占用")
        weapon_definition = self.items.require(weapon_asset.definition_id)
        if not weapon_definition.tags.has("item.weapon"):
            self._fail("weapon_item.target_not_weapon", "目标物品不是武器")
        if weapon.asset_id != weapon_asset.id:
            self._fail("weapon_item.weapon_identity_mismatch", "武器聚合与目标物品身份不一致")
        embedded = weapon_asset.data.get(WEAPON_STATE_DATA_KEY)
        if embedded is not None and embedded != weapon:
            self._fail("weapon_item.weapon_state_mismatch", "武器聚合与武库实例状态不一致")

        item_definition = self.items.require(item_asset.definition_id)
        maximum_component = item_definition.components.get(
            WEAPON_MAXIMUM_LEVEL_ITEM_COMPONENT_ID
        )
        experience_component = item_definition.components.get(
            WEAPON_EXPERIENCE_ITEM_COMPONENT_ID
        )
        if isinstance(maximum_component, WeaponMaximumLevelItemComponent):
            weapon_outcome = self.weapon_engine.increase_maximum_level(
                WeaponMaximumLevelTransaction(
                    f"{command.id}:weapon",
                    command.actor_id,
                    weapon.revision,
                    maximum_component.delta,
                    maximum_component.cap,
                    "source.weapon_growth_item",
                    item_asset.id,
                ),
                state=weapon,
                context=context,
            )
        elif isinstance(experience_component, WeaponExperienceItemComponent):
            amount = min(
                experience_component.maximum_experience,
                self.weapon_engine.experience_to_next_level(weapon),
            )
            weapon_outcome = self.weapon_engine.grant_experience(
                WeaponExperienceTransaction(
                    f"{command.id}:weapon",
                    command.actor_id,
                    weapon.revision,
                    amount,
                    "source.weapon_growth_item",
                    item_asset.id,
                ),
                state=weapon,
                context=context,
            )
        else:
            self._fail("weapon_item.component_missing", "物品不是武器成长道具")
        if weapon_outcome.failure:
            raise RuleViolation(
                weapon_outcome.failure.code,
                weapon_outcome.failure.message,
                weapon_outcome.failure.details,
            )
        assert weapon_outcome.value is not None
        next_weapon = weapon_outcome.value.state
        inventory_outcome = self.inventory_engine.execute(
            InventoryTransaction(
                f"{command.id}:inventory",
                command.actor_id,
                "weapon.item_use",
                (
                    ConsumeStack(item_asset.id, 1),
                    UpdateInstance(
                        replace(
                            weapon_asset,
                            data={
                                **weapon_asset.data,
                                **weapon_state_data(next_weapon),
                            },
                        ),
                        weapon_asset.revision,
                    ),
                ),
            ),
            state=inventory,
            context=context,
        )
        if inventory_outcome.failure:
            raise RuleViolation(
                inventory_outcome.failure.code,
                inventory_outcome.failure.message,
                inventory_outcome.failure.details,
            )
        assert inventory_outcome.value is not None
        receipt = WeaponItemUseReceipt(
            command.id,
            command.actor_id,
            item_asset.id,
            item_asset.definition_id,
            weapon.asset_id,
            weapon.definition_id,
            weapon.level,
            next_weapon.level,
            weapon.maximum_level,
            next_weapon.maximum_level,
            weapon.experience,
            next_weapon.experience,
            next_weapon.total_experience - weapon.total_experience,
        )
        return (
            inventory_outcome.value.state,
            next_weapon,
            receipt,
            (*inventory_outcome.value.events, *weapon_outcome.value.events),
        )

    @staticmethod
    def _fail(code: str, message: str) -> None:
        raise RuleViolation(code, message)


def _persistence_fingerprint(command: WeaponItemUseCommand, inventory_id: str) -> str:
    payload = f"{weapon_item_use_fingerprint(command)}|{inventory_id}"
    return sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["PersistedWeaponItemUseService"]
