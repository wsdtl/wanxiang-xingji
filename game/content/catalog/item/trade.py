"""物品固定回收产出的类型化内容组件。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.gameplay import ItemComponentType, StableId, stable_id


ITEM_RECYCLE_COMPONENT_ID = "item_component.recycle_value"


class ItemRecycleYield:
    """系统回收产出的公共类型基类。"""


@dataclass(frozen=True)
class CurrencyRecycleYield(ItemRecycleYield):
    """系统回收物品时使用的币种与整数单价。"""

    currency_id: StableId
    unit_amount: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "currency_id",
            stable_id(self.currency_id, field="recycle currency id"),
        )
        if isinstance(self.unit_amount, bool) or not isinstance(self.unit_amount, int):
            raise TypeError("物品回收单价必须是整数")
        if self.unit_amount < 1:
            raise ValueError("物品回收单价必须大于 0")


@dataclass(frozen=True)
class StackItemRecycleYield(ItemRecycleYield):
    """系统回收一件来源物品时发放的可堆叠物品数量。"""

    definition_id: StableId
    unit_quantity: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "definition_id",
            stable_id(self.definition_id, field="recycle output item id"),
        )
        if isinstance(self.unit_quantity, bool) or not isinstance(self.unit_quantity, int):
            raise TypeError("物品回收产出数量必须是整数")
        if self.unit_quantity < 1:
            raise ValueError("物品回收产出数量必须大于 0")


ITEM_RECYCLE_COMPONENT_TYPE = ItemComponentType(
    ITEM_RECYCLE_COMPONENT_ID,
    ItemRecycleYield,
)


__all__ = [
    "ITEM_RECYCLE_COMPONENT_ID",
    "ITEM_RECYCLE_COMPONENT_TYPE",
    "CurrencyRecycleYield",
    "ItemRecycleYield",
    "StackItemRecycleYield",
]
