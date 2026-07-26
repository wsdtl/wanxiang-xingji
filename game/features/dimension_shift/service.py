"""跃迁条件、凭证扣除、真实世界更新和空间迁移的唯一联合事务。"""

from game.content.catalog.item import (
    DIMENSION_SHIFT_ITEM_COMPONENT_ID,
    DIMENSION_SHIFT_ITEM_ID,
    DimensionShiftItemComponent,
)
from game.core.gameplay import (
    AddPresence,
    ActionSlotKind,
    ActionState,
    ConsumeStack,
    InventoryEngine,
    InventoryState,
    InventoryTransaction,
    RemovePresence,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    WorldPresence,
    WorldState,
    WorldTransaction,
)
from game.rules.character import (
    MULTIVERSE_WORLD_STATE_ID,
    CharacterWorldState,
    WorldShiftResult,
    shift_world,
)
from game.rules.exploration import ExplorationState

from .models import DimensionShiftStorageKinds


class DimensionShiftFeature:
    """原子扣除凭证、切换真实世界并迁移角色空间位置。"""

    def __init__(
        self,
        database,
        content,
        world_views,
        snapshots,
        inventory_engine: InventoryEngine,
        storage: DimensionShiftStorageKinds,
    ) -> None:
        self.database = database
        self.content = content
        self.world_views = world_views
        self.snapshots = snapshots
        self.inventory_engine = inventory_engine
        self.storage = storage

    def shift(
        self,
        character_id: str,
        target_world_id: str,
        *,
        logical_time,
    ) -> WorldShiftResult:
        target = self.world_views.require(target_world_id).world.id
        normalized_id = str(character_id or "").strip()
        with self.database.unit_of_work() as uow:
            current = self.snapshots.require(
                uow,
                self.storage.character_world,
                normalized_id,
                CharacterWorldState,
            )
            if current.world_id == target:
                return shift_world(current, target, logical_time=logical_time)
            action = self.snapshots.load(
                uow, self.storage.action, normalized_id, ActionState
            )
            exploration = self.snapshots.load(
                uow, self.storage.exploration, normalized_id, ExplorationState
            )
            if (
                action is not None
                and action.running(ActionSlotKind.MAIN)
            ) or (
                exploration is not None
                and exploration.active
            ):
                return WorldShiftResult("main_action_occupied", current)
            inventory = self.snapshots.require(
                uow,
                self.storage.inventory,
                normalized_id,
                InventoryState,
            )
            definition = self.content.catalog.items.require(DIMENSION_SHIFT_ITEM_ID)
            component = definition.component(
                DIMENSION_SHIFT_ITEM_COMPONENT_ID,
                DimensionShiftItemComponent,
            )
            item_asset = next(
                (
                    value
                    for value in sorted(
                        inventory.stacks.values(), key=lambda item: item.id
                    )
                    if value.definition_id == definition.id
                    and inventory.available_quantity(value.id) >= component.quantity
                ),
                None,
            )
            if item_asset is None:
                return WorldShiftResult("item_missing", current)
            result = shift_world(current, target, logical_time=logical_time)
            if result.status != "shifted" or result.current is None:
                return result
            trace_id = f"dimension-shift:{normalized_id}:{current.revision}:{target}"
            world = self.snapshots.require(
                uow,
                self.storage.world,
                MULTIVERSE_WORLD_STATE_ID,
                WorldState,
            )
            presence = next(
                (
                    value
                    for value in world.presences.values()
                    if value.owner_id == normalized_id
                ),
                None,
            )
            if presence is None:
                raise RuntimeError("跃迁时找不到角色世界存在体")
            current_anchor = self.world_views.worlds.anchor_at(
                current.world_id,
                presence.position,
            )
            current_location = (
                self.world_views.worlds.resolve(current.world_id, current_anchor)
                if current_anchor is not None
                else None
            )
            equivalent = (
                self.world_views.worlds.binding_for_display(
                    target,
                    current_location.display_id,
                )
                if current_location is not None
                else None
            )
            target_anchor = (
                equivalent.anchor_id
                if equivalent is not None
                else self.world_views.worlds.require_world(target).spawn_anchor_id
            )
            destination = self.world_views.worlds.position(target, target_anchor)
            world_outcome = self.content.catalog.world_engine.execute(
                WorldTransaction(
                    f"{trace_id}:world",
                    normalized_id,
                    world.revision,
                    (
                        RemovePresence(presence.id),
                        AddPresence(
                            WorldPresence(
                                presence.id,
                                presence.owner_id,
                                presence.kind_id,
                                destination,
                                presence.revision + 1,
                            )
                        ),
                    ),
                ),
                state=world,
                context=RuleContext(
                    f"{trace_id}:world",
                    "feature.dimension_shift.v2",
                    Ruleset("ruleset.dimension_shift"),
                    logical_time,
                    SeededRandomSource(f"{trace_id}:world"),
                ),
            )
            if world_outcome.failure or world_outcome.value is None:
                raise RuntimeError(
                    world_outcome.failure.message
                    if world_outcome.failure
                    else "跃迁空间迁移失败"
                )
            inventory_outcome = self.inventory_engine.execute(
                InventoryTransaction(
                    f"{trace_id}:inventory",
                    normalized_id,
                    "dimension.shift",
                    (ConsumeStack(item_asset.id, component.quantity),),
                ),
                state=inventory,
                context=RuleContext(
                    trace_id,
                    "feature.dimension_shift.v2",
                    Ruleset("ruleset.dimension_shift"),
                    logical_time,
                    SeededRandomSource(trace_id),
                ),
            )
            if inventory_outcome.failure or inventory_outcome.value is None:
                raise RuntimeError(
                    inventory_outcome.failure.message
                    if inventory_outcome.failure
                    else "跃迁凭证扣除失败"
                )
            self.snapshots.update(
                uow,
                self.storage.inventory,
                normalized_id,
                inventory,
                inventory_outcome.value.state,
                logical_time,
            )
            self.snapshots.update(
                uow,
                self.storage.character_world,
                normalized_id,
                current,
                result.current,
                logical_time,
            )
            self.snapshots.update(
                uow,
                self.storage.world,
                MULTIVERSE_WORLD_STATE_ID,
                world,
                world_outcome.value.state,
                logical_time,
            )
            uow.commit()
            return result


__all__ = ["DimensionShiftFeature"]
