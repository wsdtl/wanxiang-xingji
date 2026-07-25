"""人物经验物品的角色与库存联合事务。"""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

from ..gameplay.character import (
    CHARACTER_EXPERIENCE_ITEM_COMPONENT_ID,
    CharacterEngine,
    CharacterItemUseCommand,
    CharacterItemUseReceipt,
    CharacterState,
    CharacterTransaction,
    GrantExperience,
    character_item_use_fingerprint,
)
from ..gameplay.context import RuleContext
from ..gameplay.errors import RuleOutcome, RuleViolation
from ..gameplay.inventory import (
    ConsumeStack,
    InventoryEngine,
    InventoryState,
    InventoryTransaction,
    ItemCatalog,
    ItemStack,
)
from .errors import TransactionMismatch
from .snapshots import CHARACTER_AGGREGATE, INVENTORY_AGGREGATE, SnapshotRepository
from .sqlite import SqliteDatabase


class PersistedCharacterItemUseService:
    """人物成长物品的唯一数据库写入口。"""

    def __init__(
        self,
        database: SqliteDatabase,
        items: ItemCatalog,
        inventory_engine: InventoryEngine,
        character_engine: CharacterEngine,
        snapshots: SnapshotRepository | None = None,
    ) -> None:
        self.database = database
        self.items = items
        self.inventory_engine = inventory_engine
        self.character_engine = character_engine
        self.snapshots = snapshots or SnapshotRepository()

    def use(
        self,
        command: CharacterItemUseCommand,
        *,
        inventory_id: str,
        context: RuleContext,
    ) -> RuleOutcome[CharacterItemUseReceipt]:
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
                            f"同一人物经验事务 ID 对应不同内容：{command.id}"
                        )
                    receipt = self.snapshots.codec.loads(
                        committed.receipt_payload,
                        CharacterItemUseReceipt,
                    )
                    return RuleOutcome.success(replace(receipt, replayed=True))

                inventory = self.snapshots.require(
                    uow, INVENTORY_AGGREGATE, inventory_id, InventoryState
                )
                character = self.snapshots.require(
                    uow, CHARACTER_AGGREGATE, command.actor_id, CharacterState
                )
                try:
                    next_inventory, next_character, receipt, events = self._execute(
                        command,
                        inventory,
                        character,
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
                    CHARACTER_AGGREGATE,
                    character.id,
                    character,
                    next_character,
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

    def _execute(self, command, inventory, character, context):
        try:
            item_asset = inventory.asset(command.item_asset_id)
        except KeyError as exc:
            raise RuleViolation("character_item.item_unknown", "找不到人物经验物品") from exc
        if not isinstance(item_asset, ItemStack):
            self._fail("character_item.item_not_stack", "人物经验物品必须是可堆叠物品")
        if inventory.owner_of(item_asset.id) != command.actor_id:
            self._fail("character_item.item_owner_mismatch", "人物经验物品不属于当前角色")
        if inventory.available_quantity(item_asset.id) < 1:
            self._fail("character_item.item_unavailable", "人物经验物品当前不可使用")
        definition = self.items.require(item_asset.definition_id)
        component = definition.components.get(CHARACTER_EXPERIENCE_ITEM_COMPONENT_ID)
        if component is None:
            self._fail("character_item.component_missing", "物品不是人物经验物品")

        from ..gameplay.character import CharacterExperienceItemComponent

        if not isinstance(component, CharacterExperienceItemComponent):
            self._fail("character_item.component_invalid", "人物经验物品组件无效")
        progression_id = component.progression_id
        progression = character.progressions[progression_id]
        progression_definition = self.character_engine.catalog.progressions.require(progression_id)
        required = progression_definition.required_for_next_level(progression.level)
        if required is None or progression.level >= progression_definition.maximum_level:
            self._fail("character_item.level_capped", "角色已经达到当前成长上限，无法使用人物经验物品")
        missing = max(0, required - progression.experience)
        if missing == 0:
            self._fail("character_item.breakthrough_required", "当前经验已满，请先进行突破")
        amount = min(component.maximum_experience, missing)
        transaction = CharacterTransaction(
            f"{command.id}:character",
            command.actor_id,
            character.revision,
            "source.character_experience_item",
            (
                GrantExperience(
                    progression_id,
                    amount,
                    "source.character_experience_item",
                    item_asset.id,
                ),
            ),
        )
        character_outcome = self.character_engine.execute(
            transaction,
            state=character,
            context=context,
        )
        if character_outcome.failure or character_outcome.value is None:
            raise RuleViolation(
                character_outcome.failure.code if character_outcome.failure else "character_item.failed",
                character_outcome.failure.message if character_outcome.failure else "人物经验物品使用失败",
            )
        next_character = character_outcome.value.state
        next_progression = next_character.progressions[progression_id]
        inventory_outcome = self.inventory_engine.execute(
            InventoryTransaction(
                f"{command.id}:inventory",
                command.actor_id,
                "character.item_use",
                (ConsumeStack(item_asset.id, 1),),
            ),
            state=inventory,
            context=context,
        )
        if inventory_outcome.failure or inventory_outcome.value is None:
            failure = inventory_outcome.failure
            raise RuleViolation(
                failure.code if failure else "character_item.inventory_failed",
                failure.message if failure else "人物经验物品扣除失败",
            )
        receipt = CharacterItemUseReceipt(
            command.id,
            command.actor_id,
            item_asset.id,
            definition.id,
            progression_id,
            progression.level,
            next_progression.level,
            progression.experience,
            next_progression.experience,
            amount,
        )
        return (
            inventory_outcome.value.state,
            next_character,
            receipt,
            (*character_outcome.value.events, *inventory_outcome.value.events),
        )

    @staticmethod
    def _fail(code: str, message: str) -> None:
        raise RuleViolation(code, message)


def _persistence_fingerprint(command: CharacterItemUseCommand, inventory_id: str) -> str:
    return sha256(
        f"{character_item_use_fingerprint(command)}|{inventory_id}".encode("utf-8")
    ).hexdigest()


__all__ = ["PersistedCharacterItemUseService"]
