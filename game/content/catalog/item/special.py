"""纳戒物品分类、铭刻之羽定义与特殊物品构造约束。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from game.core.gameplay import (
    ITEM_STORAGE_COMPONENT_ID,
    ITEM_CONTAINER_CAPACITY_COMPONENT_ID,
    ContainerCapacityItemComponent,
    CHARACTER_EXPERIENCE_ITEM_COMPONENT_ID,
    CharacterExperienceItemComponent,
    COMPANION_EXPERIENCE_ITEM_COMPONENT_ID,
    CompanionExperienceItemComponent,
    ItemAssetKind,
    ItemDefinition,
    ItemComponentType,
    ItemStorageComponent,
    StableId,
    TagSet,
    WEAPON_EXPERIENCE_ITEM_COMPONENT_ID,
    WEAPON_MAXIMUM_LEVEL_ITEM_COMPONENT_ID,
    WeaponExperienceItemComponent,
    WeaponMaximumLevelItemComponent,
    stable_id,
)
from .classification import (
    CONSUMABLE_ITEM_TAG,
    INSCRIPTION_MEDIUM_ITEM_TAG,
    INSCRIPTION_STORAGE_TAG,
    MEDICINE_ITEM_TAG,
    SPECIAL_ITEM_TAG,
    SPECIAL_STORAGE_TAG,
    validate_nacre_item_categories,
)

INSCRIPTION_FEATHER_ITEM_ID = "item.inscription.feather"
WEAPON_MAXIMUM_LEVEL_ITEM_ID = "item.special.weapon_maximum_level"
CHARACTER_EXPERIENCE_ITEM_ID = "item.special.character_experience"
WEAPON_EXPERIENCE_ITEM_ID = "item.special.weapon_experience"
COMPANION_EXPERIENCE_ITEM_ID = "item.special.companion_experience"
BACKPACK_CAPACITY_ITEM_ID = "item.special.backpack_capacity"
DIMENSION_SHIFT_ITEM_ID = "item.special.dimension_shift"
DIMENSION_SHIFT_ITEM_COMPONENT_ID = "item_component.use_dimension_shift"
COMPANION_SANCTUARY_ITEM_ID = "item.special.companion_sanctuary"
COMPANION_SANCTUARY_ITEM_COMPONENT_ID = "item_component.use_companion_sanctuary"
BACKPACK_CAPACITY_INCREMENT = 5
BACKPACK_CAPACITY_MAXIMUM = 140
SPECIAL_ITEM_STACK_LIMIT = 99

CHARACTER_EXPERIENCE_ITEM_COMPONENT_TYPE = ItemComponentType(
    CHARACTER_EXPERIENCE_ITEM_COMPONENT_ID,
    CharacterExperienceItemComponent,
)
COMPANION_EXPERIENCE_ITEM_COMPONENT_TYPE = ItemComponentType(
    COMPANION_EXPERIENCE_ITEM_COMPONENT_ID,
    CompanionExperienceItemComponent,
)


@dataclass(frozen=True)
class DimensionShiftItemComponent:
    """标记该特殊物品由跃迁业务自动消耗。"""

    quantity: int = 1

    def __post_init__(self) -> None:
        if self.quantity != 1:
            raise ValueError("每次跃迁必须且只能消耗一枚跃迁凭证")


DIMENSION_SHIFT_ITEM_COMPONENT_TYPE = ItemComponentType(
    DIMENSION_SHIFT_ITEM_COMPONENT_ID,
    DimensionShiftItemComponent,
)


@dataclass(frozen=True)
class CompanionSanctuaryItemComponent:
    """标记该特殊物品用于开启角色当前世界的宠物秘境。"""

    quantity: int = 1

    def __post_init__(self) -> None:
        if self.quantity != 1:
            raise ValueError("每次开启宠物秘境必须且只能消耗一枚秘境凭证")


COMPANION_SANCTUARY_ITEM_COMPONENT_TYPE = ItemComponentType(
    COMPANION_SANCTUARY_ITEM_COMPONENT_ID,
    CompanionSanctuaryItemComponent,
)


INSCRIPTION_FEATHER_ITEM = ItemDefinition(
    INSCRIPTION_FEATHER_ITEM_ID,
    ItemAssetKind.INSTANCE,
    TagSet.of(INSCRIPTION_MEDIUM_ITEM_TAG, INSCRIPTION_STORAGE_TAG),
    components={ITEM_STORAGE_COMPONENT_ID: ItemStorageComponent(1)},
)


def special_item_definition(
    item_id: StableId,
    *,
    use_components: Mapping[StableId, object],
    stack_limit: int = SPECIAL_ITEM_STACK_LIMIT,
) -> ItemDefinition:
    """构造一个可堆叠特殊物品；实际用途必须由类型化使用组件声明。"""

    components = {
        stable_id(component_id, field="item component id"): value
        for component_id, value in use_components.items()
    }
    if not components:
        raise ValueError("特殊物品必须声明至少一个类型化使用组件")
    invalid = sorted(
        component_id
        for component_id in components
        if not component_id.startswith("item_component.use_")
    )
    if invalid:
        raise ValueError(f"特殊物品包含非使用组件：{invalid[0]}")
    components[ITEM_STORAGE_COMPONENT_ID] = ItemStorageComponent(1)
    definition = ItemDefinition(
        item_id,
        ItemAssetKind.STACK,
        TagSet.of(CONSUMABLE_ITEM_TAG, SPECIAL_ITEM_TAG, SPECIAL_STORAGE_TAG),
        stack_limit,
        components,
    )
    validate_nacre_item_categories((definition,))
    return definition


WEAPON_MAXIMUM_LEVEL_ITEM = special_item_definition(
    WEAPON_MAXIMUM_LEVEL_ITEM_ID,
    use_components={
        WEAPON_MAXIMUM_LEVEL_ITEM_COMPONENT_ID: WeaponMaximumLevelItemComponent(),
    },
)
CHARACTER_EXPERIENCE_ITEM = special_item_definition(
    CHARACTER_EXPERIENCE_ITEM_ID,
    use_components={
        CHARACTER_EXPERIENCE_ITEM_COMPONENT_ID: CharacterExperienceItemComponent(),
    },
)
WEAPON_EXPERIENCE_ITEM = special_item_definition(
    WEAPON_EXPERIENCE_ITEM_ID,
    use_components={
        WEAPON_EXPERIENCE_ITEM_COMPONENT_ID: WeaponExperienceItemComponent(),
    },
)
COMPANION_EXPERIENCE_ITEM = special_item_definition(
    COMPANION_EXPERIENCE_ITEM_ID,
    use_components={
        COMPANION_EXPERIENCE_ITEM_COMPONENT_ID: CompanionExperienceItemComponent(),
    },
)
BACKPACK_CAPACITY_ITEM = special_item_definition(
    BACKPACK_CAPACITY_ITEM_ID,
    use_components={
        ITEM_CONTAINER_CAPACITY_COMPONENT_ID: ContainerCapacityItemComponent(
            "container.backpack",
            BACKPACK_CAPACITY_INCREMENT,
            BACKPACK_CAPACITY_MAXIMUM,
        ),
    },
)
DIMENSION_SHIFT_ITEM = special_item_definition(
    DIMENSION_SHIFT_ITEM_ID,
    use_components={
        DIMENSION_SHIFT_ITEM_COMPONENT_ID: DimensionShiftItemComponent(),
    },
)
COMPANION_SANCTUARY_ITEM = special_item_definition(
    COMPANION_SANCTUARY_ITEM_ID,
    use_components={
        COMPANION_SANCTUARY_ITEM_COMPONENT_ID: CompanionSanctuaryItemComponent(),
    },
)
SPECIAL_ITEMS: tuple[ItemDefinition, ...] = (
    WEAPON_MAXIMUM_LEVEL_ITEM,
    CHARACTER_EXPERIENCE_ITEM,
    WEAPON_EXPERIENCE_ITEM,
    COMPANION_EXPERIENCE_ITEM,
    BACKPACK_CAPACITY_ITEM,
    DIMENSION_SHIFT_ITEM,
    COMPANION_SANCTUARY_ITEM,
)


__all__ = [
    "CONSUMABLE_ITEM_TAG",
    "COMPANION_SANCTUARY_ITEM",
    "COMPANION_SANCTUARY_ITEM_COMPONENT_ID",
    "COMPANION_SANCTUARY_ITEM_COMPONENT_TYPE",
    "COMPANION_SANCTUARY_ITEM_ID",
    "CompanionSanctuaryItemComponent",
    "BACKPACK_CAPACITY_INCREMENT",
    "BACKPACK_CAPACITY_ITEM",
    "BACKPACK_CAPACITY_ITEM_ID",
    "BACKPACK_CAPACITY_MAXIMUM",
    "DIMENSION_SHIFT_ITEM",
    "DIMENSION_SHIFT_ITEM_COMPONENT_ID",
    "DIMENSION_SHIFT_ITEM_COMPONENT_TYPE",
    "DIMENSION_SHIFT_ITEM_ID",
    "DimensionShiftItemComponent",
    "INSCRIPTION_FEATHER_ITEM",
    "INSCRIPTION_FEATHER_ITEM_ID",
    "INSCRIPTION_MEDIUM_ITEM_TAG",
    "INSCRIPTION_STORAGE_TAG",
    "MEDICINE_ITEM_TAG",
    "SPECIAL_ITEM_STACK_LIMIT",
    "SPECIAL_ITEMS",
    "SPECIAL_ITEM_TAG",
    "SPECIAL_STORAGE_TAG",
    "CHARACTER_EXPERIENCE_ITEM_ID",
    "CHARACTER_EXPERIENCE_ITEM_COMPONENT_TYPE",
    "CHARACTER_EXPERIENCE_ITEM",
    "COMPANION_EXPERIENCE_ITEM_ID",
    "COMPANION_EXPERIENCE_ITEM_COMPONENT_TYPE",
    "COMPANION_EXPERIENCE_ITEM",
    "WEAPON_EXPERIENCE_ITEM",
    "WEAPON_EXPERIENCE_ITEM_ID",
    "WEAPON_MAXIMUM_LEVEL_ITEM",
    "WEAPON_MAXIMUM_LEVEL_ITEM_ID",
    "special_item_definition",
    "validate_nacre_item_categories",
]
