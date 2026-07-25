"""把物品使用与 Ability 结算组合为同一个原子结果。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..abilities import AbilityUse
from ..context import RuleContext
from ..entity import RuleEntity
from ..errors import RuleOutcome, RuleViolation
from ..events import RuleEvent
from ..ids import StableId, stable_id
from ..runtime import GameplayExecutor
from .components import ItemComponentRegistry, ItemComponentType
from .definitions import ItemCatalog
from .models import InventoryState, ItemStack
from .transactions import (
    ConsumeInstance,
    ConsumeStack,
    InventoryEngine,
    InventoryTransaction,
)


ITEM_ABILITY_COMPONENT_ID = "item_component.use_ability"


@dataclass(frozen=True)
class ItemAbilityComponent:
    """声明一个物品可授权哪个 Ability，以及是否消耗物品。"""

    ability_id: StableId
    consume_quantity: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "ability_id", stable_id(self.ability_id, field="ability id"))
        if self.consume_quantity < 0:
            raise ValueError("ItemAbilityComponent.consume_quantity 不能小于 0")


def register_item_ability_component(registry: ItemComponentRegistry) -> None:
    """向物品目录登记标准 Ability 组件类型。"""

    registry.register(ItemComponentType(ITEM_ABILITY_COMPONENT_ID, ItemAbilityComponent))


@dataclass(frozen=True)
class ItemAbilityUse:
    """玩家使用某一份具体物品资产发动 Ability。"""

    transaction_id: str
    asset_id: str
    ability_use: AbilityUse
    reservation_id: str | None = None

    def __post_init__(self) -> None:
        if not self.transaction_id.strip():
            raise ValueError("ItemAbilityUse 缺少 transaction_id")
        if not self.asset_id.strip():
            raise ValueError("ItemAbilityUse 缺少 asset_id")


@dataclass(frozen=True)
class InventoryAbilityExecution:
    inventory: InventoryState
    actor: RuleEntity
    target: RuleEntity
    events: tuple[RuleEvent, ...]


class InventoryAbilityExecutor:
    """同时验证物品资产、支付物品成本并执行 Ability。"""

    def __init__(
        self,
        catalog: ItemCatalog,
        inventory: InventoryEngine,
        gameplay: GameplayExecutor,
    ) -> None:
        self.catalog = catalog
        self.inventory = inventory
        self.gameplay = gameplay
        self._validate_ability_references()

    def execute(
        self,
        use: ItemAbilityUse,
        *,
        inventory_state: InventoryState,
        actor: RuleEntity,
        target: RuleEntity,
        context: RuleContext,
    ) -> RuleOutcome[InventoryAbilityExecution]:
        checkpoint = context.random.checkpoint()
        try:
            try:
                asset = inventory_state.asset(use.asset_id)
            except KeyError as exc:
                raise RuleViolation(
                    "inventory.asset_unknown",
                    "找不到要使用的物品资产",
                    {"asset_id": use.asset_id},
                ) from exc
            owner_id = inventory_state.owner_of(asset.id)
            if owner_id != actor.id:
                raise RuleViolation(
                    "inventory.owner_mismatch",
                    "使用者不是物品当前所有者",
                    {"asset_id": asset.id, "owner_id": owner_id, "actor_id": actor.id},
                )
            definition = self.catalog.require(asset.definition_id)
            try:
                component = definition.component(
                    ITEM_ABILITY_COMPONENT_ID,
                    ItemAbilityComponent,
                )
            except KeyError as exc:
                raise RuleViolation(
                    "inventory.item_not_usable",
                    "物品没有 Ability 使用组件",
                    {"item_id": definition.id},
                ) from exc
            if component.ability_id != use.ability_use.ability_id:
                raise RuleViolation(
                    "inventory.ability_mismatch",
                    "请求的 Ability 与物品定义不一致",
                    {
                        "item_id": definition.id,
                        "requested": use.ability_use.ability_id,
                        "expected": component.ability_id,
                    },
                )
            inventory_events: tuple[RuleEvent, ...] = ()
            next_inventory = inventory_state
            if component.consume_quantity:
                if isinstance(asset, ItemStack):
                    operation = ConsumeStack(
                        asset.id,
                        component.consume_quantity,
                        use.reservation_id,
                    )
                elif component.consume_quantity == 1:
                    operation = ConsumeInstance(asset.id, use.reservation_id)
                else:
                    raise RuleViolation(
                        "inventory.invalid_quantity",
                        "独立实例物品每次最多消耗一个",
                        {"asset_id": asset.id, "quantity": component.consume_quantity},
                    )
                inventory_outcome = self.inventory.execute(
                    InventoryTransaction(
                        use.transaction_id,
                        actor.id,
                        "inventory.use_item",
                        (operation,),
                    ),
                    state=inventory_state,
                    context=context,
                )
                if inventory_outcome.failure:
                    raise RuleViolation(
                        inventory_outcome.failure.code,
                        inventory_outcome.failure.message,
                        inventory_outcome.failure.details,
                    )
                assert inventory_outcome.value is not None
                next_inventory = inventory_outcome.value.state
                inventory_events = inventory_outcome.value.events
            else:
                self._authorize_non_consuming_use(
                    asset.id,
                    use.reservation_id,
                    inventory_state,
                    context,
                )

            originally_owned = component.ability_id in actor.base_abilities
            authorized_actor = actor
            if not originally_owned:
                authorized_actor = replace(
                    actor,
                    base_abilities=actor.base_abilities | {component.ability_id},
                )
            gameplay_outcome = self.gameplay.execute_ability(
                use.ability_use,
                actor=authorized_actor,
                target=authorized_actor if target.id == actor.id else target,
                context=context,
            )
            if gameplay_outcome.failure:
                raise RuleViolation(
                    gameplay_outcome.failure.code,
                    gameplay_outcome.failure.message,
                    gameplay_outcome.failure.details,
                )
            assert gameplay_outcome.value is not None
            actor_result = gameplay_outcome.value.actor
            target_result = gameplay_outcome.value.target
            if not originally_owned:
                actor_result = replace(actor_result, base_abilities=actor.base_abilities)
                if target.id == actor.id:
                    target_result = actor_result
            used_event = RuleEvent.from_context(
                context,
                kind="inventory.item.used",
                source_id=actor.id,
                target_id=target.id,
                subject_id=definition.id,
                values={
                    "transaction_id": use.transaction_id,
                    "asset_id": asset.id,
                    "ability_id": component.ability_id,
                    "consumed_quantity": component.consume_quantity,
                },
            )
            return RuleOutcome.success(
                InventoryAbilityExecution(
                    next_inventory,
                    actor_result,
                    target_result,
                    (*inventory_events, *gameplay_outcome.value.events, used_event),
                )
            )
        except RuleViolation as exc:
            context.random.restore(checkpoint)
            return RuleOutcome.failed(exc.failure)

    def _validate_ability_references(self) -> None:
        ability_ids = self.gameplay.abilities.definitions
        for definition in self.catalog.definitions:
            component = definition.components.get(ITEM_ABILITY_COMPONENT_ID)
            if component is None:
                continue
            assert isinstance(component, ItemAbilityComponent)
            if not ability_ids.contains(component.ability_id):
                raise KeyError(
                    f"物品 {definition.id} 引用了未知 Ability：{component.ability_id}"
                )

    @staticmethod
    def _authorize_non_consuming_use(
        asset_id: str,
        reservation_id: str | None,
        inventory: InventoryState,
        context: RuleContext,
    ) -> None:
        reservations = tuple(
            value
            for value in inventory.reservations_for(asset_id)
            if not value.expired_at(context.logical_time)
        )
        if reservation_id is None:
            if reservations:
                raise RuleViolation(
                    "inventory.asset_reserved",
                    "物品已被其他业务占用",
                    {"asset_id": asset_id},
                )
            return
        reservation = inventory.reservations.get(reservation_id)
        if reservation is None or reservation.expired_at(context.logical_time):
            raise RuleViolation("inventory.reservation_unknown", "找不到有效的指定预约")
        if reservation.asset_id != asset_id:
            raise RuleViolation("inventory.reservation_mismatch", "预约不属于指定资产")
        if any(value.id != reservation_id for value in reservations):
            raise RuleViolation("inventory.reservation_conflict", "物品还被其他业务占用")


__all__ = [
    "ITEM_ABILITY_COMPONENT_ID",
    "InventoryAbilityExecution",
    "InventoryAbilityExecutor",
    "ItemAbilityComponent",
    "ItemAbilityUse",
    "register_item_ability_component",
]
