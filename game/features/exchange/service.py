"""定相尘兑换套装图纸的原子业务。"""

from __future__ import annotations

from hashlib import sha256

from game.content.catalog.economy import EQUIPMENT_SET_BLUEPRINT_PRICE
from game.content.catalog.item import (
    EQUIPMENT_SET_BLUEPRINT_COMPONENT_ID,
    EXCHANGE_MATERIAL_ITEM_ID,
    EquipmentSetBlueprintItemComponent,
)
from game.core.gameplay import (
    AppendStack,
    ConsumeStack,
    GrantStack,
    InventoryState,
    InventoryTransaction,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    SourceReceipt,
)

from .models import CovenantExchangeHistory, CovenantExchangeReceipt, CovenantExchangeResult


COVENANT_EXCHANGE_RULESET_VERSION = "features.covenant_exchange.v1"
COVENANT_EXCHANGE_HISTORY_AGGREGATE = "game.exchange.history"


class CovenantExchangeFeature:
    """只拥有归航材料余额与固定目录兑换事务。"""

    def __init__(
        self,
        database,
        content,
        snapshots,
        inventory_engine,
        inventory_kind: str,
        history_kind: str = COVENANT_EXCHANGE_HISTORY_AGGREGATE,
    ) -> None:
        self.database = database
        self.content = content
        self.snapshots = snapshots
        self.inventory_engine = inventory_engine
        self.inventory_kind = inventory_kind
        self.history_kind = history_kind

    def history(self, actor_id: str) -> CovenantExchangeHistory:
        with self.database.unit_of_work(write=False) as uow:
            return self.snapshots.load(
                uow,
                self.history_kind,
                actor_id,
                CovenantExchangeHistory,
            ) or CovenantExchangeHistory(actor_id)

    def material_balance(self, actor_id: str) -> int:
        with self.database.unit_of_work(write=False) as uow:
            inventory = self.snapshots.require(
                uow,
                self.inventory_kind,
                actor_id,
                InventoryState,
            )
        return sum(
            inventory.available_quantity(stack.id)
            for stack in inventory.stacks.values()
            if stack.definition_id == EXCHANGE_MATERIAL_ITEM_ID
        )

    def redeem_blueprint(
        self,
        actor_id: str,
        set_id: str,
        transaction_id: str,
        *,
        logical_time,
    ) -> CovenantExchangeResult:
        actor_id = str(actor_id or "").strip()
        set_id = str(set_id or "").strip()
        transaction_id = str(transaction_id or "").strip()
        if not actor_id or not set_id or not transaction_id:
            raise ValueError("归航兑换请求缺少角色、套装或事务身份")
        fingerprint = _fingerprint(actor_id, set_id)
        with self.database.unit_of_work() as uow:
            committed = uow.load_transaction(transaction_id)
            if committed is not None:
                if committed.fingerprint != fingerprint or committed.scope_id != actor_id:
                    raise ValueError("同一兑换事务 ID 对应不同内容")
                receipt = self.snapshots.codec.loads(
                    committed.receipt_payload,
                    CovenantExchangeReceipt,
                )
                return CovenantExchangeResult("replayed", receipt.as_replayed())

            self.content.equipment.sets.require(set_id)
            blueprint_definition = self._blueprint_for_set(set_id)

            inventory = self.snapshots.require(
                uow,
                self.inventory_kind,
                actor_id,
                InventoryState,
            )
            material_stacks = tuple(
                sorted(
                    (
                        stack
                        for stack in inventory.stacks.values()
                        if stack.definition_id == EXCHANGE_MATERIAL_ITEM_ID
                        and inventory.owner_of(stack.id) == actor_id
                    ),
                    key=lambda value: value.id,
                )
            )
            consume_operations = _consume_operations(
                inventory,
                material_stacks,
                EQUIPMENT_SET_BLUEPRINT_PRICE,
            )
            if consume_operations is None:
                return CovenantExchangeResult(
                    "material_missing",
                    failure_message=f"定相尘不足，需要 {EQUIPMENT_SET_BLUEPRINT_PRICE}",
                )
            special = next(
                value
                for value in inventory.containers.values()
                if value.owner_id == actor_id and value.kind == "container.special"
            )
            existing = next(
                (
                    stack
                    for stack in inventory.stacks.values()
                    if stack.definition_id == blueprint_definition.id
                    and stack.container_id == special.id
                    and stack.quantity < (blueprint_definition.stack_limit or stack.quantity + 1)
                ),
                None,
            )
            blueprint_asset_id = (
                existing.id
                if existing is not None
                else f"covenant-blueprint:{transaction_id}"
            )
            source = SourceReceipt(
                f"{transaction_id}:receipt",
                "source.covenant_exchange",
                transaction_id,
                logical_time,
                {"set_id": set_id, "material_quantity": EQUIPMENT_SET_BLUEPRINT_PRICE},
            )
            grant = (
                AppendStack(existing.id, 1, source)
                if existing is not None
                else GrantStack(
                    blueprint_asset_id,
                    blueprint_definition.id,
                    special.id,
                    1,
                    source,
                )
            )
            context = RuleContext(
                transaction_id,
                COVENANT_EXCHANGE_RULESET_VERSION,
                Ruleset("ruleset.covenant_exchange"),
                logical_time,
                SeededRandomSource(transaction_id),
            )
            outcome = self.inventory_engine.execute(
                InventoryTransaction(
                    f"{transaction_id}:inventory",
                    actor_id,
                    "inventory.covenant_exchange",
                    (*consume_operations, grant),
                ),
                state=inventory,
                context=context,
            )
            if outcome.failure or outcome.value is None:
                return CovenantExchangeResult(
                    "inventory_rejected",
                    failure_message=outcome.failure.message if outcome.failure else "兑换没有完成",
                )
            receipt = CovenantExchangeReceipt(
                transaction_id,
                actor_id,
                set_id,
                EXCHANGE_MATERIAL_ITEM_ID,
                EQUIPMENT_SET_BLUEPRINT_PRICE,
                str(blueprint_definition.id),
                blueprint_asset_id,
            )
            history = self.snapshots.load(
                uow,
                self.history_kind,
                actor_id,
                CovenantExchangeHistory,
            )
            next_history = CovenantExchangeHistory(
                actor_id,
                ((history.records if history is not None else ()) + (receipt,))[-20:],
                (history.revision if history is not None else 0) + 1,
            )
            self.snapshots.update(
                uow,
                self.inventory_kind,
                actor_id,
                inventory,
                outcome.value.state,
                logical_time,
            )
            if history is None:
                self.snapshots.insert(
                    uow,
                    self.history_kind,
                    actor_id,
                    next_history,
                    logical_time,
                )
            else:
                self.snapshots.update(
                    uow,
                    self.history_kind,
                    actor_id,
                    history,
                    next_history,
                    logical_time,
                )
            timestamp = logical_time.isoformat()
            uow.insert_transaction(
                transaction_id,
                fingerprint,
                actor_id,
                self.snapshots.codec.dumps(receipt),
                timestamp,
            )
            for sequence, event in enumerate(outcome.value.events):
                uow.append_fact(
                    transaction_id,
                    sequence,
                    event.kind,
                    self.snapshots.codec.dumps(event),
                    timestamp,
                )
            uow.commit()
            return CovenantExchangeResult("redeemed", receipt)

    def _blueprint_for_set(self, set_id: str):
        matches = []
        for definition in self.content.items.definitions:
            component = definition.components.get(EQUIPMENT_SET_BLUEPRINT_COMPONENT_ID)
            if (
                isinstance(component, EquipmentSetBlueprintItemComponent)
                and component.target_set_id == set_id
            ):
                matches.append(definition)
        if len(matches) != 1:
            raise ValueError(f"套装 {set_id} 必须恰好对应一张图纸")
        return matches[0]


def _consume_operations(inventory, stacks, quantity: int):
    remaining = quantity
    operations = []
    for stack in stacks:
        amount = min(remaining, inventory.available_quantity(stack.id))
        if amount > 0:
            operations.append(ConsumeStack(stack.id, amount))
            remaining -= amount
        if remaining == 0:
            return tuple(operations)
    return None


def _fingerprint(actor_id: str, set_id: str) -> str:
    return sha256(f"{actor_id}|{set_id}".encode()).hexdigest()


__all__ = [
    "COVENANT_EXCHANGE_HISTORY_AGGREGATE",
    "COVENANT_EXCHANGE_RULESET_VERSION",
    "CovenantExchangeFeature",
]
