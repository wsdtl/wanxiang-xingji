"""十二个装备底座族、六槽正式装备和十八套可混搭套装。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.gameplay import (
    LOADOUT_ITEM_COMPONENT_ID,
    ContributionSpec,
    EquipmentDefinition,
    EquipmentFamilyDefinition,
    EquipmentQualityProfile,
    EquipmentSetBonus,
    EquipmentSetDefinition,
    ItemAssetKind,
    ItemDefinition,
    LoadoutItemComponent,
    TagSet,
)

from ..foundation import QUALITY_IDS
from .blueprints import (
    EQUIPMENT_FAMILY_BLUEPRINTS,
    EQUIPMENT_SET_BLUEPRINTS,
    EQUIPMENT_SLOT_BLUEPRINTS,
)
from .properties import EQUIPMENT_GENERATION_PROFILE_ID


@dataclass(frozen=True)
class EquipmentCatalogContent:
    items: tuple[ItemDefinition, ...]
    families: tuple[EquipmentFamilyDefinition, ...]
    sets: tuple[EquipmentSetDefinition, ...]
    equipment: tuple[EquipmentDefinition, ...]
    display_ids: frozenset[str]


def equipment_family_id(key: str) -> str:
    return f"equipment_family.{key}"


def equipment_set_id(key: str) -> str:
    return f"equipment_set.{key}"


def equipment_definition_id(family_key: str, slot_key: str) -> str:
    return f"equipment.{family_key}.{slot_key}"


def equipment_item_id(family_key: str, slot_key: str) -> str:
    return f"item.equipment.{family_key}.{slot_key}"


def build_equipment_catalog_content() -> EquipmentCatalogContent:
    families = tuple(
        EquipmentFamilyDefinition(
            equipment_family_id(blueprint.key),
            TagSet.of(f"equipment.family.{blueprint.key}"),
        )
        for blueprint in EQUIPMENT_FAMILY_BLUEPRINTS
    )
    sets = tuple(
        EquipmentSetDefinition(
            equipment_set_id(blueprint.key),
            tuple(
                EquipmentSetBonus(required_pieces, contribution)
                for required_pieces, contribution in zip((2, 3, 4), blueprint.bonuses, strict=True)
            ),
        )
        for blueprint in EQUIPMENT_SET_BLUEPRINTS
    )
    quality_profiles = {
        quality_id: EquipmentQualityProfile(quality_id, ContributionSpec()) for quality_id in QUALITY_IDS
    }
    items = []
    definitions = []
    display_ids = {
        *(value.id for value in families),
        *(value.id for value in sets),
    }
    for family in EQUIPMENT_FAMILY_BLUEPRINTS:
        for slot in EQUIPMENT_SLOT_BLUEPRINTS:
            item_id = equipment_item_id(family.key, slot.key)
            definition_id = equipment_definition_id(family.key, slot.key)
            items.append(
                ItemDefinition(
                    item_id,
                    ItemAssetKind.INSTANCE,
                    TagSet.of("item.equipment", "item.armament"),
                    components={LOADOUT_ITEM_COMPONENT_ID: LoadoutItemComponent(frozenset({slot.slot_id}))},
                )
            )
            definitions.append(
                EquipmentDefinition(
                    definition_id,
                    item_id,
                    slot.slot_id,
                    equipment_family_id(family.key),
                    quality_profiles=quality_profiles,
                    generation_profile_id=EQUIPMENT_GENERATION_PROFILE_ID,
                )
            )
            display_ids.update((item_id, definition_id))
    return EquipmentCatalogContent(
        tuple(items),
        families,
        sets,
        tuple(definitions),
        frozenset(display_ids),
    )


EQUIPMENT_CATALOG_CONTENT = build_equipment_catalog_content()


__all__ = [
    "EQUIPMENT_CATALOG_CONTENT",
    "EquipmentCatalogContent",
    "build_equipment_catalog_content",
    "equipment_definition_id",
    "equipment_family_id",
    "equipment_item_id",
    "equipment_set_id",
]
