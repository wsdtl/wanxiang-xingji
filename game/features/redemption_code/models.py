"""兑换码领取结果与玩家可见装备引用。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.gameplay import EquipmentState, StableId, WeaponState, stable_id


@dataclass(frozen=True)
class RedemptionCodeStackItem:
    definition_id: StableId
    quantity: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "definition_id",
            stable_id(self.definition_id, field="item definition id"),
        )
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise TypeError("兑换码堆叠物品数量必须是整数")
        if self.quantity < 1:
            raise ValueError("兑换码堆叠物品数量必须大于零")


@dataclass(frozen=True)
class RedemptionCodeItem:
    kind: str
    state: EquipmentState | WeaponState
    item_definition_id: StableId
    slot_id: StableId
    reference_number: int

    def __post_init__(self) -> None:
        if self.kind not in {"equipment", "weapon"}:
            raise ValueError("兑换码装备类型必须是 equipment 或 weapon")
        if self.reference_number < 1:
            raise ValueError("兑换码装备缺少永久编号")
        object.__setattr__(
            self,
            "item_definition_id",
            stable_id(self.item_definition_id, field="item definition id"),
        )
        object.__setattr__(self, "slot_id", stable_id(self.slot_id, field="loadout slot id"))


@dataclass(frozen=True)
class RedemptionCodeResult:
    status: str
    code: str = ""
    currency_amount: int = 0
    items: tuple[RedemptionCodeItem, ...] = ()
    stack_items: tuple[RedemptionCodeStackItem, ...] = ()
    replayed: bool = False
    failure_code: str = ""
    failure_message: str = ""

    def __post_init__(self) -> None:
        if self.status not in {
            "redeemed",
            "already_redeemed",
            "invalid",
            "unavailable",
            "rejected",
        }:
            raise ValueError(f"未知兑换码结果状态：{self.status}")
        if self.currency_amount < 0:
            raise ValueError("兑换码结果货币数量不能小于零")
        object.__setattr__(self, "items", tuple(self.items))
        object.__setattr__(self, "stack_items", tuple(self.stack_items))


__all__ = ["RedemptionCodeItem", "RedemptionCodeResult", "RedemptionCodeStackItem"]
