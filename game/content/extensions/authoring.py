"""把蓝图编译为可独立发现的共享内容扩展。"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from game.core.gameplay import (
    ContentPackage,
    ContentPackageManifest,
    ContentVersion,
    PackageRequirement,
    SkinEntry,
)

from ..catalog.economy.exchange import (
    EQUIPMENT_SET_BLUEPRINT_PRICE,
    EXCHANGE_MATERIAL_REFERENCE_VALUE,
)
from ..catalog.economy.market_items import MarketItemPolicy
from ..catalog.equipment.blueprints import (
    EQUIPMENT_SLOT_BLUEPRINTS,
    EquipmentFamilyBlueprint,
    EquipmentPropertyBlueprint,
    EquipmentSetBlueprint,
)
from ..catalog.equipment.definitions import build_equipment_catalog_content
from ..catalog.equipment.mechanisms import (
    EquipmentMechanicDefinition,
    EquipmentMechanicRegistry,
)
from ..catalog.equipment.properties import (
    EQUIPMENT_GENERATION_PROFILE_ID,
    EQUIPMENT_PROPERTY_CONTENT,
    build_equipment_property_content,
)
from ..catalog.item.exchange import (
    build_equipment_set_blueprint_items,
    equipment_set_blueprint_item_id,
)
from ..catalog.weapon.blueprints import WeaponBlueprint
from ..catalog.weapon.mechanics import (
    WEAPON_CHARGE_EFFECT_ID,
    WEAPON_MARK_EFFECT_ID,
    build_weapon_mechanic_content,
)
from ..catalog.weapon.official_mechanics import OFFICIAL_WEAPON_MECHANICS
from ..catalog.weapon.registry import WeaponMechanicRegistry
from ..world_skins.combat_mechanisms import build_combat_mechanism_entries
from .models import ContentExtension


@dataclass(frozen=True)
class ContentPresentation:
    name: str
    description: str = ""
    icon: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("内容展示名称不能为空")


@dataclass(frozen=True)
class EquipmentSkinPresentation:
    families: Mapping[str, ContentPresentation] = field(default_factory=dict)
    sets: Mapping[str, ContentPresentation] = field(default_factory=dict)
    slot_names: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "families", MappingProxyType(dict(self.families)))
        object.__setattr__(self, "sets", MappingProxyType(dict(self.sets)))
        slots = {str(key): str(value).strip() for key, value in self.slot_names.items()}
        if any(not value for value in slots.values()):
            raise ValueError("装备槽位展示名称不能为空")
        object.__setattr__(self, "slot_names", MappingProxyType(slots))


def build_weapon_content_extension(
    *,
    extension_id: str,
    package_id: str,
    version: ContentVersion,
    blueprints: tuple[WeaponBlueprint, ...],
    skin_presentations: Mapping[str, Mapping[str, ContentPresentation]],
    registry: WeaponMechanicRegistry = OFFICIAL_WEAPON_MECHANICS,
    base_package: ContentPackage | None = None,
) -> ContentExtension:
    """使用已注册机制编译一组独立武器内容。"""

    values = tuple(blueprints)
    content = build_weapon_mechanic_content(
        values,
        registry,
        require_all_registered_used=False,
    )
    shared_effect_ids = {WEAPON_MARK_EFFECT_ID, WEAPON_CHARGE_EFFECT_ID}
    effects = tuple(value for value in content.effects if value.id not in shared_effect_ids)
    properties = tuple(
        value
        for value in content.properties
        if str(value.id).startswith("property.weapon_core.")
    )
    display_ids = frozenset(
        {
            *(value.id for value in content.items),
            *(value.id for value in content.weapons),
            *(value.id for value in content.abilities),
            *(value.id for value in effects),
            *(value.id for value in content.triggers),
            *(value.id for value in properties),
        }
    )
    package = ContentPackage(
        manifest=ContentPackageManifest(
            package_id,
            version,
            (_base_requirement(base_package),),
        ),
        items=content.items,
        weapons=content.weapons,
        effects=effects,
        abilities=content.abilities,
        battle_ability_targeting=content.targeting,
        triggers=content.triggers,
        reference_valuations=content.reference_valuations,
        random_properties=properties,
        generation_profiles=content.profiles,
        display_content_ids=display_ids,
    )
    overlays = _weapon_overlays(
        values,
        effects,
        content.triggers,
        properties,
        skin_presentations,
    )
    _require_exact_overlay_coverage(display_ids, overlays)
    return ContentExtension(
        id=extension_id,
        version=version,
        packages=(package,),
        skin_overlays=overlays,
    )


def build_equipment_content_extension(
    *,
    extension_id: str,
    package_id: str,
    version: ContentVersion,
    families: tuple[EquipmentFamilyBlueprint, ...] = (),
    sets: tuple[EquipmentSetBlueprint, ...] = (),
    skin_presentations: Mapping[str, EquipmentSkinPresentation],
    base_package: ContentPackage | None = None,
    generation_profile_id: str | None = None,
) -> ContentExtension:
    """编译新装备底座族与套装，共用基础随机词条池。"""

    family_values = tuple(families)
    set_values = tuple(sets)
    content = build_equipment_catalog_content(
        family_values,
        set_values,
        EQUIPMENT_SLOT_BLUEPRINTS,
        generation_profile_id=(
            generation_profile_id
            if generation_profile_id is not None
            else EQUIPMENT_GENERATION_PROFILE_ID
        ),
    )
    blueprint_items = build_equipment_set_blueprint_items(set_values)
    display_ids = frozenset(
        {
            *content.display_ids,
            *(value.id for value in blueprint_items),
        }
    )
    package = ContentPackage(
        manifest=ContentPackageManifest(
            package_id,
            version,
            (_base_requirement(base_package),),
        ),
        items=(*content.items, *blueprint_items),
        equipment_families=content.families,
        equipment_sets=content.sets,
        equipment=content.equipment,
        display_content_ids=display_ids,
    )
    overlays = _equipment_overlays(
        family_values,
        set_values,
        skin_presentations,
    )
    _require_exact_overlay_coverage(display_ids, overlays)
    policies = tuple(
        MarketItemPolicy(
            equipment_set_blueprint_item_id(value.key),
            "blueprint",
            EQUIPMENT_SET_BLUEPRINT_PRICE * EXCHANGE_MATERIAL_REFERENCE_VALUE,
            3_000,
            30_000,
        )
        for value in set_values
    )
    return ContentExtension(
        id=extension_id,
        version=version,
        packages=(package,),
        skin_overlays=overlays,
        market_item_policies=policies,
    )


def build_equipment_mechanic_content_extension(
    *,
    extension_id: str,
    package_id: str,
    version: ContentVersion,
    profile_id: str,
    mechanisms: tuple[EquipmentMechanicDefinition, ...],
    skin_presentations: Mapping[str, Mapping[str, ContentPresentation]],
    base_package: ContentPackage | None = None,
    inherit_official_properties: bool = True,
) -> ContentExtension:
    """编译新装备机制、三档词条与可供新底座族选择的生成池。"""

    registry = EquipmentMechanicRegistry(tuple(mechanisms))
    blueprints = tuple(
        EquipmentPropertyBlueprint(value.key, value.category)
        for value in registry.definitions.values()
    )
    inherited = (
        frozenset(value.id for value in EQUIPMENT_PROPERTY_CONTENT.properties)
        if inherit_official_properties
        else frozenset()
    )
    content = build_equipment_property_content(
        blueprints,
        registry,
        profile_id=profile_id,
        inherited_property_ids=inherited,
    )
    display_ids = frozenset(
        {
            *(value.id for value in content.properties),
            *(value.id for value in content.effects),
            *(value.id for value in content.triggers),
        }
    )
    package = ContentPackage(
        manifest=ContentPackageManifest(
            package_id,
            version,
            (_base_requirement(base_package),),
        ),
        effects=content.effects,
        triggers=content.triggers,
        reference_valuations=content.reference_valuations,
        random_properties=content.properties,
        generation_profiles=content.profiles,
        display_content_ids=display_ids,
    )
    overlays = _equipment_mechanic_overlays(
        blueprints,
        content.effects,
        content.triggers,
        skin_presentations,
    )
    _require_exact_overlay_coverage(display_ids, overlays)
    return ContentExtension(
        id=extension_id,
        version=version,
        packages=(package,),
        skin_overlays=overlays,
    )


def _base_requirement(base_package: ContentPackage | None) -> PackageRequirement:
    if base_package is None:
        from ..catalog import CATALOG_PACKAGE

        base_package = CATALOG_PACKAGE
    version = base_package.manifest.version
    return PackageRequirement(
        base_package.manifest.id,
        version,
        ContentVersion(version.major + 1, 0, 0),
    )


def _weapon_overlays(
    blueprints,
    effects,
    triggers,
    properties,
    presentations,
):
    expected_keys = {value.key for value in blueprints}
    overlays = {}
    for skin_id, values in presentations.items():
        if set(values) != expected_keys:
            raise ValueError(f"武器扩展展示未完整覆盖蓝图：{skin_id}")
        entries = {}
        for blueprint in blueprints:
            visible = values[blueprint.key]
            entries.update(
                {
                    f"item.weapon.{blueprint.key}": SkinEntry(
                        name=f"{visible.name}器胚",
                        icon=visible.icon,
                    ),
                    f"weapon.{blueprint.key}": SkinEntry(
                        name=visible.name,
                        description=visible.description,
                        icon=visible.icon,
                    ),
                    f"ability.weapon.{blueprint.key}": SkinEntry(
                        name=f"{visible.name}战技",
                        description=visible.description,
                        icon=visible.icon,
                    ),
                    f"property.weapon_core.{blueprint.key}": SkinEntry(
                        name=f"{visible.name}核心",
                        description=f"承载{visible.name}核心战斗机制。",
                        icon=visible.icon,
                    ),
                }
            )
        entries.update(
            build_combat_mechanism_entries(
                effects=effects,
                triggers=triggers,
                interceptors=(),
                target_constraints=(),
                damage_types=(),
                controls=(),
                owner_entries=entries,
                base_effect_names={},
                damage_names={},
                interceptor_names={},
                constraint_names={},
                control_names={},
            )
        )
        overlays[skin_id] = entries
    return overlays


def _equipment_overlays(families, sets, presentations):
    family_keys = {value.key for value in families}
    set_keys = {value.key for value in sets}
    slot_keys = {value.key for value in EQUIPMENT_SLOT_BLUEPRINTS}
    overlays = {}
    for skin_id, visible in presentations.items():
        if set(visible.families) != family_keys:
            raise ValueError(f"装备扩展底座族展示未完整覆盖：{skin_id}")
        if set(visible.sets) != set_keys:
            raise ValueError(f"装备扩展套装展示未完整覆盖：{skin_id}")
        if family_keys and set(visible.slot_names) != slot_keys:
            raise ValueError(f"装备扩展槽位名称未完整覆盖：{skin_id}")
        entries = {}
        for family in families:
            family_visible = visible.families[family.key]
            family_id = f"equipment_family.{family.key}"
            entries[family_id] = SkinEntry(
                name=family_visible.name,
                description=family_visible.description,
                icon=family_visible.icon,
            )
            for slot in EQUIPMENT_SLOT_BLUEPRINTS:
                slot_name = visible.slot_names[slot.key]
                name = f"{family_visible.name}·{slot_name}"
                entries[f"item.equipment.{family.key}.{slot.key}"] = SkinEntry(
                    name=f"{name}器胚",
                    icon=family_visible.icon,
                )
                entries[f"equipment.{family.key}.{slot.key}"] = SkinEntry(
                    name=name,
                    description=family_visible.description,
                    icon=family_visible.icon,
                )
        for equipment_set in sets:
            set_visible = visible.sets[equipment_set.key]
            entries[f"equipment_set.{equipment_set.key}"] = SkinEntry(
                name=set_visible.name,
                description=set_visible.description,
                icon=set_visible.icon,
            )
            entries[equipment_set_blueprint_item_id(equipment_set.key)] = SkinEntry(
                name=f"{set_visible.name}图纸",
                description=f"使用后生成一件{set_visible.name}套装装备。",
                icon=set_visible.icon,
            )
        overlays[skin_id] = entries
    return overlays


def _equipment_mechanic_overlays(
    blueprints,
    effects,
    triggers,
    presentations,
):
    expected_keys = {value.key for value in blueprints}
    overlays = {}
    for skin_id, values in presentations.items():
        if set(values) != expected_keys:
            raise ValueError(f"装备机制展示未完整覆盖：{skin_id}")
        entries = {
            f"property.equipment.{blueprint.key}": SkinEntry(
                name=values[blueprint.key].name,
                description=values[blueprint.key].description,
                icon=values[blueprint.key].icon,
            )
            for blueprint in blueprints
        }
        entries.update(
            build_combat_mechanism_entries(
                effects=effects,
                triggers=triggers,
                interceptors=(),
                target_constraints=(),
                damage_types=(),
                controls=(),
                owner_entries=entries,
                base_effect_names={},
                damage_names={},
                interceptor_names={},
                constraint_names={},
                control_names={},
            )
        )
        overlays[skin_id] = entries
    return overlays


def _require_exact_overlay_coverage(display_ids, overlays) -> None:
    if not overlays:
        raise ValueError("内容扩展至少需要一份世界展示投影")
    expected = set(display_ids)
    for skin_id, entries in overlays.items():
        if set(entries) != expected:
            missing = sorted(expected - set(entries))
            extra = sorted(set(entries) - expected)
            raise ValueError(
                f"内容扩展展示覆盖不完整：{skin_id}/missing={missing}/extra={extra}"
            )


__all__ = [
    "ContentPresentation",
    "EquipmentSkinPresentation",
    "build_equipment_content_extension",
    "build_equipment_mechanic_content_extension",
    "build_weapon_content_extension",
]
