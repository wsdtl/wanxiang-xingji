"""突破凭证、角色成长和资源恢复的原子联合事务。"""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

from game.content.catalog import (
    BREAKTHROUGH_TOKEN_ITEM_ID,
    CHARACTER_LEVEL_PROGRESSION_ID,
)
from game.core.gameplay import (
    ChangeCharacterResource,
    CharacterEngine,
    CharacterState,
    CharacterTransaction,
    ConsumeStack,
    InventoryEngine,
    InventoryState,
    InventoryTransaction,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    UnlockProgressionCap,
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    SPIRIT_MAXIMUM,
)

from .models import BreakthroughReceipt, BreakthroughResult, BreakthroughStorageKinds


BREAKTHROUGH_RULESET_VERSION = "rules.breakthrough.v1"
BREAKTHROUGH_SOURCE_KIND = "source.breakthrough"


class BreakthroughFeature:
    """只处理当前角色的破境，不定义世界皮肤名称和抽奖概率。"""

    def __init__(
        self,
        database,
        content,
        snapshots,
        inventory_engine: InventoryEngine,
        character_engine: CharacterEngine,
        storage: BreakthroughStorageKinds,
    ) -> None:
        self.database = database
        self.content = content
        self.snapshots = snapshots
        self.inventory_engine = inventory_engine
        self.character_engine = character_engine
        self.storage = storage

    def breakthrough(self, character_id: str, transaction_id: str, *, logical_time) -> BreakthroughResult:
        character_id = str(character_id or "").strip()
        transaction_id = str(transaction_id or "").strip()
        if not character_id or not transaction_id:
            raise ValueError("突破请求缺少角色或事务身份")
        fingerprint = _fingerprint(character_id)
        with self.database.unit_of_work() as uow:
            committed = uow.load_transaction(transaction_id)
            if committed is not None:
                if committed.fingerprint != fingerprint or committed.scope_id != character_id:
                    raise ValueError("同一突破事务 ID 对应不同内容")
                receipt = self.snapshots.codec.loads(
                    committed.receipt_payload,
                    BreakthroughReceipt,
                )
                character = self.snapshots.require(
                    uow, self.storage.character, character_id, CharacterState
                )
                return BreakthroughResult("replayed", character, replace(receipt, replayed=True))

            character = self.snapshots.require(
                uow, self.storage.character, character_id, CharacterState
            )
            inventory = self.snapshots.require(
                uow, self.storage.inventory, character_id, InventoryState
            )
            progression = character.progressions.get(CHARACTER_LEVEL_PROGRESSION_ID)
            if progression is None:
                return BreakthroughResult("progression_missing", character, failure_message="角色缺少人物成长轨道")
            definition = self.content.catalog.characters.progressions.require(
                CHARACTER_LEVEL_PROGRESSION_ID
            )
            current_cap = _level_cap(definition, progression)
            next_cap = definition.next_level_cap(current_cap)
            if next_cap is None:
                return BreakthroughResult("maximum", character, failure_message="已经达到最终境界")
            if progression.level != current_cap:
                return BreakthroughResult("not_at_cap", character, failure_message="尚未到达当前境界关隘")
            required = definition.required_for_next_level(progression.level)
            if required is not None and progression.experience < required:
                return BreakthroughResult("experience_incomplete", character, failure_message="当前境界经验尚未积满")
            item_asset = next(
                (
                    value
                    for value in sorted(inventory.stacks.values(), key=lambda item: item.id)
                    if value.definition_id == BREAKTHROUGH_TOKEN_ITEM_ID
                    and inventory.available_quantity(value.id) >= 1
                ),
                None,
            )
            if item_asset is None:
                return BreakthroughResult("item_missing", character, failure_message="缺少破境凭证")

            context = RuleContext(
                f"breakthrough:{transaction_id}",
                BREAKTHROUGH_RULESET_VERSION,
                Ruleset("ruleset.breakthrough"),
                logical_time,
                SeededRandomSource(transaction_id),
            )
            unlock = self.character_engine.execute(
                CharacterTransaction(
                    f"{transaction_id}:unlock",
                    character_id,
                    character.revision,
                    BREAKTHROUGH_SOURCE_KIND,
                    (
                        UnlockProgressionCap(
                            CHARACTER_LEVEL_PROGRESSION_ID,
                            BREAKTHROUGH_SOURCE_KIND,
                            transaction_id,
                        ),
                    ),
                ),
                state=character,
                context=context,
            )
            if unlock.failure or unlock.value is None:
                return BreakthroughResult(
                    "rejected",
                    character,
                    failure_message=unlock.failure.message if unlock.failure else "突破没有完成",
                )
            advanced = unlock.value.state
            restore_operations = []
            for current_id, maximum_id in (
                (HEALTH_CURRENT, HEALTH_MAXIMUM),
                (SPIRIT_CURRENT, SPIRIT_MAXIMUM),
            ):
                delta = advanced.core_attributes[maximum_id] - advanced.resources[current_id]
                if delta > 0:
                    restore_operations.append(
                        ChangeCharacterResource(
                            current_id,
                            delta,
                            BREAKTHROUGH_SOURCE_KIND,
                            transaction_id,
                        )
                    )
            restored = advanced
            restore_events = ()
            if restore_operations:
                restore = self.character_engine.execute(
                    CharacterTransaction(
                        f"{transaction_id}:restore",
                        character_id,
                        advanced.revision,
                        BREAKTHROUGH_SOURCE_KIND,
                        tuple(restore_operations),
                    ),
                    state=advanced,
                    context=context,
                )
                if restore.failure or restore.value is None:
                    return BreakthroughResult(
                        "rejected",
                        character,
                        failure_message=restore.failure.message if restore.failure else "突破恢复失败",
                    )
                restored = restore.value.state
                restore_events = restore.value.events
            inventory_outcome = self.inventory_engine.execute(
                InventoryTransaction(
                    f"{transaction_id}:inventory",
                    character_id,
                    BREAKTHROUGH_SOURCE_KIND,
                    (ConsumeStack(item_asset.id, 1),),
                ),
                state=inventory,
                context=context,
            )
            if inventory_outcome.failure or inventory_outcome.value is None:
                return BreakthroughResult(
                    "rejected",
                    character,
                    failure_message=inventory_outcome.failure.message if inventory_outcome.failure else "破境凭证扣除失败",
                )
            receipt = BreakthroughReceipt(
                transaction_id,
                character_id,
                item_asset.id,
                CHARACTER_LEVEL_PROGRESSION_ID,
                progression.level,
                restored.progressions[CHARACTER_LEVEL_PROGRESSION_ID].level,
                current_cap,
                next_cap,
            )
            self.snapshots.update(
                uow,
                self.storage.character,
                character_id,
                character,
                advanced,
                logical_time,
            )
            if restored is not advanced:
                self.snapshots.update(
                    uow,
                    self.storage.character,
                    character_id,
                    advanced,
                    restored,
                    logical_time,
                )
            self.snapshots.update(
                uow,
                self.storage.inventory,
                character_id,
                inventory,
                inventory_outcome.value.state,
                logical_time,
            )
            timestamp = logical_time.isoformat()
            uow.insert_transaction(
                transaction_id,
                fingerprint,
                character_id,
                self.snapshots.codec.dumps(receipt),
                timestamp,
            )
            for sequence, event in enumerate(
                (*unlock.value.events, *restore_events, *inventory_outcome.value.events)
            ):
                uow.append_fact(
                    transaction_id,
                    sequence,
                    event.kind,
                    self.snapshots.codec.dumps(event),
                    timestamp,
                )
            uow.commit()
            return BreakthroughResult("broken_through", restored, receipt)


def _level_cap(definition, progression) -> int:
    if progression.level_cap is not None:
        return progression.level_cap
    for value in definition.level_caps:
        if value >= progression.level:
            return value
    return definition.maximum_level


def _fingerprint(character_id: str) -> str:
    return sha256(f"{character_id}|{CHARACTER_LEVEL_PROGRESSION_ID}|{BREAKTHROUGH_TOKEN_ITEM_ID}".encode()).hexdigest()


__all__ = ["BREAKTHROUGH_RULESET_VERSION", "BreakthroughFeature"]
