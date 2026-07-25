"""归航兑换材料与套装图纸的正式物品定义。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.gameplay import (
    ITEM_STORAGE_COMPONENT_ID,
    ItemAssetKind,
    ItemComponentType,
    ItemDefinition,
    ItemStorageComponent,
    StableId,
    TagSet,
    stable_id,
)

from ..equipment.blueprints import EQUIPMENT_SET_BLUEPRINTS, EquipmentSetBlueprint
from ..equipment.definitions import equipment_set_id
from .classification import CONSUMABLE_ITEM_TAG, SPECIAL_STORAGE_TAG


EXCHANGE_MATERIAL_ITEM_ID = "item.exchange_material.set_blueprint_essence"
EXCHANGE_MATERIAL_ITEM_TAG = "item.exchange_material"
BLUEPRINT_ITEM_TAG = "item.blueprint"
EQUIPMENT_SET_BLUEPRINT_ITEM_TAG = "item.blueprint.equipment_set"
EQUIPMENT_SET_BLUEPRINT_COMPONENT_ID = "item_component.use_equipment_set_blueprint"
EXCHANGE_MATERIAL_STACK_LIMIT = 999_999
EQUIPMENT_SET_BLUEPRINT_STACK_LIMIT = 99


@dataclass(frozen=True)
class EquipmentSetBlueprintItemComponent:
    """声明图纸生成装备时必须使用的套装身份。"""

    target_set_id: StableId

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_set_id",
            stable_id(self.target_set_id, field="blueprint target equipment set id"),
        )


EQUIPMENT_SET_BLUEPRINT_COMPONENT_TYPE = ItemComponentType(
    EQUIPMENT_SET_BLUEPRINT_COMPONENT_ID,
    EquipmentSetBlueprintItemComponent,
)


def equipment_set_blueprint_item_id(set_key: str) -> str:
    key = str(set_key or "").strip()
    if not key:
        raise ValueError("套装图纸缺少稳定键")
    return f"item.blueprint.equipment_set.{key}"


EXCHANGE_MATERIAL_ITEM = ItemDefinition(
    EXCHANGE_MATERIAL_ITEM_ID,
    ItemAssetKind.STACK,
    TagSet.of(EXCHANGE_MATERIAL_ITEM_TAG, SPECIAL_STORAGE_TAG),
    EXCHANGE_MATERIAL_STACK_LIMIT,
    {ITEM_STORAGE_COMPONENT_ID: ItemStorageComponent(1)},
)

def build_equipment_set_blueprint_items(
    blueprints: tuple[EquipmentSetBlueprint, ...],
) -> tuple[ItemDefinition, ...]:
    values = tuple(blueprints)
    keys = tuple(value.key for value in values)
    if len(keys) != len(set(keys)):
        raise ValueError("套装图纸蓝图稳定键重复")
    return tuple(
        ItemDefinition(
            equipment_set_blueprint_item_id(blueprint.key),
            ItemAssetKind.STACK,
            TagSet.of(
                CONSUMABLE_ITEM_TAG,
                BLUEPRINT_ITEM_TAG,
                EQUIPMENT_SET_BLUEPRINT_ITEM_TAG,
                SPECIAL_STORAGE_TAG,
            ),
            EQUIPMENT_SET_BLUEPRINT_STACK_LIMIT,
            {
                ITEM_STORAGE_COMPONENT_ID: ItemStorageComponent(1),
                EQUIPMENT_SET_BLUEPRINT_COMPONENT_ID: EquipmentSetBlueprintItemComponent(
                    equipment_set_id(blueprint.key)
                ),
            },
        )
        for blueprint in values
    )


EQUIPMENT_SET_BLUEPRINT_ITEMS = build_equipment_set_blueprint_items(
    EQUIPMENT_SET_BLUEPRINTS
)

EQUIPMENT_SET_BLUEPRINT_ITEM_IDS = tuple(
    str(definition.id) for definition in EQUIPMENT_SET_BLUEPRINT_ITEMS
)


__all__ = [
    "BLUEPRINT_ITEM_TAG",
    "EQUIPMENT_SET_BLUEPRINT_COMPONENT_ID",
    "EQUIPMENT_SET_BLUEPRINT_COMPONENT_TYPE",
    "EQUIPMENT_SET_BLUEPRINT_ITEMS",
    "EQUIPMENT_SET_BLUEPRINT_ITEM_IDS",
    "EQUIPMENT_SET_BLUEPRINT_ITEM_TAG",
    "EQUIPMENT_SET_BLUEPRINT_STACK_LIMIT",
    "EXCHANGE_MATERIAL_ITEM",
    "EXCHANGE_MATERIAL_ITEM_ID",
    "EXCHANGE_MATERIAL_ITEM_TAG",
    "EXCHANGE_MATERIAL_STACK_LIMIT",
    "EquipmentSetBlueprintItemComponent",
    "build_equipment_set_blueprint_items",
    "equipment_set_blueprint_item_id",
]
