"""消费套装图纸并生成指定套装身份的随机装备。"""

from __future__ import annotations

from hashlib import sha256

from game.content.catalog.item import (
    EQUIPMENT_SET_BLUEPRINT_COMPONENT_ID,
    EquipmentSetBlueprintItemComponent,
)
from game.core.gameplay import (
    ConsumeStack,
    GrantInstance,
    InventoryState,
    InventoryTransaction,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    SourceReceipt,
    equipment_state_data,
)
from game.rules.equipment import EquipmentGenerationRequest, EquipmentInstanceGenerator

from .models import EquipmentBlueprintReceipt, EquipmentBlueprintResult


EQUIPMENT_BLUEPRINT_RULESET_VERSION = "features.equipment_blueprint.v1"


class EquipmentBlueprintFeature:
    """只拥有图纸消费与装备生成联合事务。"""

    def __init__(self, database, content, snapshots, inventory_engine, inventory_kind: str) -> None:
        self.database = database
        self.content = content
        self.snapshots = snapshots
        self.inventory_engine = inventory_engine
        self.inventory_kind = inventory_kind
        self.generator = EquipmentInstanceGenerator(
            content.equipment,
            content.itemization_engine,
        )

    def use(
        self,
        actor_id: str,
        blueprint_asset_id: str,
        transaction_id: str,
        *,
        logical_time,
    ) -> EquipmentBlueprintResult:
        actor_id = str(actor_id or "").strip()
        blueprint_asset_id = str(blueprint_asset_id or "").strip()
        transaction_id = str(transaction_id or "").strip()
        if not actor_id or not blueprint_asset_id or not transaction_id:
            raise ValueError("套装图纸请求缺少角色、物品或事务身份")
        fingerprint = _fingerprint(actor_id, blueprint_asset_id)
        with self.database.unit_of_work() as uow:
            committed = uow.load_transaction(transaction_id)
            if committed is not None:
                if committed.fingerprint != fingerprint or committed.scope_id != actor_id:
                    raise ValueError("同一图纸事务 ID 对应不同内容")
                receipt = self.snapshots.codec.loads(
                    committed.receipt_payload,
                    EquipmentBlueprintReceipt,
                )
                return EquipmentBlueprintResult("replayed", receipt.as_replayed())

            inventory = self.snapshots.require(
                uow,
                self.inventory_kind,
                actor_id,
                InventoryState,
            )
            try:
                blueprint = inventory.stacks[blueprint_asset_id]
            except KeyError:
                return EquipmentBlueprintResult("item_missing", failure_message="找不到这张套装图纸")
            if inventory.owner_of(blueprint.id) != actor_id or inventory.available_quantity(blueprint.id) < 1:
                return EquipmentBlueprintResult("item_unavailable", failure_message="套装图纸当前不可使用")
            definition = self.content.items.require(blueprint.definition_id)
            try:
                component = definition.component(
                    EQUIPMENT_SET_BLUEPRINT_COMPONENT_ID,
                    EquipmentSetBlueprintItemComponent,
                )
            except (KeyError, TypeError):
                return EquipmentBlueprintResult("invalid_item", failure_message="该物品不是套装图纸")

            armory = next(
                value
                for value in inventory.containers.values()
                if value.owner_id == actor_id and value.kind == "container.armory"
            )
            context = RuleContext(
                transaction_id,
                EQUIPMENT_BLUEPRINT_RULESET_VERSION,
                Ruleset("ruleset.equipment_blueprint"),
                logical_time,
                SeededRandomSource(transaction_id),
            )
            equipment_definition_id = context.random.choice(
                self.content.equipment.definitions.ids()
            )
            equipment_asset_id = f"blueprint-equipment:{transaction_id}"
            try:
                generated = self.generator.generate(
                    EquipmentGenerationRequest(
                        f"{transaction_id}:generate",
                        equipment_asset_id,
                        equipment_definition_id,
                        self.content.report.content_fingerprint,
                    ),
                    context=context,
                    forced_set_id=component.target_set_id,
                ).state
            except (KeyError, TypeError, ValueError) as exc:
                return EquipmentBlueprintResult("generation_failed", failure_message=str(exc))
            equipment_definition = self.content.equipment.require(equipment_definition_id)
            source = SourceReceipt(
                f"{transaction_id}:receipt",
                "source.equipment_blueprint",
                transaction_id,
                logical_time,
                {
                    "blueprint_definition_id": str(definition.id),
                    "set_id": str(component.target_set_id),
                },
            )
            outcome = self.inventory_engine.execute(
                InventoryTransaction(
                    f"{transaction_id}:inventory",
                    actor_id,
                    "inventory.use_equipment_blueprint",
                    (
                        ConsumeStack(blueprint.id, 1),
                        GrantInstance(
                            equipment_asset_id,
                            equipment_definition.item_definition_id,
                            armory.id,
                            source,
                            equipment_state_data(generated),
                        ),
                    ),
                ),
                state=inventory,
                context=context,
            )
            if outcome.failure or outcome.value is None:
                return EquipmentBlueprintResult(
                    "inventory_rejected",
                    failure_message=outcome.failure.message if outcome.failure else "装备没有生成",
                )
            receipt = EquipmentBlueprintReceipt(
                transaction_id,
                actor_id,
                blueprint.id,
                str(definition.id),
                equipment_asset_id,
                str(generated.definition_id),
                str(equipment_definition.item_definition_id),
                str(component.target_set_id),
                str(generated.quality_id),
            )
            self.snapshots.update(
                uow,
                self.inventory_kind,
                actor_id,
                inventory,
                outcome.value.state,
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
            return EquipmentBlueprintResult("generated", receipt)


def _fingerprint(actor_id: str, blueprint_asset_id: str) -> str:
    return sha256(f"{actor_id}|{blueprint_asset_id}".encode()).hexdigest()


__all__ = ["EQUIPMENT_BLUEPRINT_RULESET_VERSION", "EquipmentBlueprintFeature"]
