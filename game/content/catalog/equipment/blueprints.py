"""正式装备身份、随机词条入口和套装效果的单点蓝图。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.gameplay import (
    ACCESSORY_SLOT_ID,
    BODY_SLOT_ID,
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    COMBAT_SPEED,
    FEET_SLOT_ID,
    HANDS_SLOT_ID,
    HEAD_SLOT_ID,
    HEALTH_MAXIMUM,
    SPIRIT_MAXIMUM,
    WAIST_SLOT_ID,
    AttributeGrant,
    ContributionSpec,
    ModifierLayer,
)

from .ids import equipment_trigger_id
from .mechanisms import OFFICIAL_EQUIPMENT_MECHANICS

from ..combat.stats import (
    COMBAT_ACCURACY,
    COMBAT_BLOCK_CHANCE,
    COMBAT_BLOCK_REDUCTION,
    COMBAT_CONTROL_CHANCE,
    COMBAT_CONTROL_RESISTANCE,
    COMBAT_CRITICAL_CHANCE,
    COMBAT_CRITICAL_DAMAGE,
    COMBAT_EVASION,
    COMBAT_FLAT_PENETRATION,
    COMBAT_HEALING_RATE,
    COMBAT_HEALING_RECEIVED,
    COMBAT_OUTGOING_RATE,
    COMBAT_RATE_PENETRATION,
    COMBAT_TENACITY,
)


@dataclass(frozen=True)
class EquipmentFamilyBlueprint:
    key: str


@dataclass(frozen=True)
class EquipmentSlotBlueprint:
    key: str
    slot_id: str


@dataclass(frozen=True)
class EquipmentPropertyBlueprint:
    key: str
    category: str


@dataclass(frozen=True)
class EquipmentSetBlueprint:
    key: str
    bonuses: tuple[ContributionSpec, ContributionSpec, ContributionSpec]


def _attributes(*values: tuple[str, ModifierLayer, float]) -> ContributionSpec:
    return ContributionSpec(
        attributes=tuple(AttributeGrant(attribute, layer, amount) for attribute, layer, amount in values)
    )


def _trigger(key: str, tier: int) -> ContributionSpec:
    return ContributionSpec(triggers=frozenset({equipment_trigger_id(key, tier)}))


def _set(
    key: str,
    two: ContributionSpec,
    three: ContributionSpec,
    four: ContributionSpec,
) -> EquipmentSetBlueprint:
    return EquipmentSetBlueprint(key, (two, three, four))


EQUIPMENT_FAMILY_BLUEPRINTS = (
    EquipmentFamilyBlueprint("mystic_sky"),
    EquipmentFamilyBlueprint("crimson_cloud"),
    EquipmentFamilyBlueprint("azure_tide"),
    EquipmentFamilyBlueprint("verdant_void"),
    EquipmentFamilyBlueprint("mountain_guard"),
    EquipmentFamilyBlueprint("flowing_light"),
    EquipmentFamilyBlueprint("shadow_bamboo"),
    EquipmentFamilyBlueprint("star_array"),
    EquipmentFamilyBlueprint("great_void"),
    EquipmentFamilyBlueprint("startled_thunder"),
    EquipmentFamilyBlueprint("ashen_plume"),
    EquipmentFamilyBlueprint("returning_origin"),
)


EQUIPMENT_SLOT_BLUEPRINTS = (
    EquipmentSlotBlueprint("head", HEAD_SLOT_ID),
    EquipmentSlotBlueprint("body", BODY_SLOT_ID),
    EquipmentSlotBlueprint("hands", HANDS_SLOT_ID),
    EquipmentSlotBlueprint("waist", WAIST_SLOT_ID),
    EquipmentSlotBlueprint("feet", FEET_SLOT_ID),
    EquipmentSlotBlueprint("accessory", ACCESSORY_SLOT_ID),
)


NUMERIC_EQUIPMENT_PROPERTY_BLUEPRINTS = (
    EquipmentPropertyBlueprint("health", "core"),
    EquipmentPropertyBlueprint("spirit", "core"),
    EquipmentPropertyBlueprint("attack", "core"),
    EquipmentPropertyBlueprint("defense", "core"),
    EquipmentPropertyBlueprint("speed", "core"),
    EquipmentPropertyBlueprint("accuracy", "offense"),
    EquipmentPropertyBlueprint("evasion", "defense"),
    EquipmentPropertyBlueprint("critical_chance", "offense"),
    EquipmentPropertyBlueprint("critical_damage", "offense"),
    EquipmentPropertyBlueprint("block_chance", "defense"),
    EquipmentPropertyBlueprint("block_reduction", "defense"),
    EquipmentPropertyBlueprint("outgoing", "offense"),
    EquipmentPropertyBlueprint("incoming", "defense"),
    EquipmentPropertyBlueprint("flat_penetration", "offense"),
    EquipmentPropertyBlueprint("rate_penetration", "offense"),
    EquipmentPropertyBlueprint("healing", "sustain"),
    EquipmentPropertyBlueprint("healing_received", "sustain"),
    EquipmentPropertyBlueprint("control_chance", "control"),
    EquipmentPropertyBlueprint("control_resistance", "control"),
    EquipmentPropertyBlueprint("tenacity", "control"),
    EquipmentPropertyBlueprint("vital_guard", "hybrid"),
    EquipmentPropertyBlueprint("spirit_step", "hybrid"),
    EquipmentPropertyBlueprint("keen_edge", "hybrid"),
    EquipmentPropertyBlueprint("mystic_armor", "hybrid"),
)


MECHANIC_EQUIPMENT_PROPERTY_BLUEPRINTS = tuple(
    EquipmentPropertyBlueprint(definition.key, definition.category)
    for definition in OFFICIAL_EQUIPMENT_MECHANICS.definitions.values()
)


EQUIPMENT_PROPERTY_BLUEPRINTS = (
    *NUMERIC_EQUIPMENT_PROPERTY_BLUEPRINTS,
    *MECHANIC_EQUIPMENT_PROPERTY_BLUEPRINTS,
)


EQUIPMENT_SET_BLUEPRINTS = (
    _set(
        "army_breaker",
        _attributes((COMBAT_RATE_PENETRATION, ModifierLayer.GLOBAL_FLAT, 0.05)),
        _attributes((COMBAT_CRITICAL_CHANCE, ModifierLayer.GLOBAL_FLAT, 0.04)),
        _trigger("critical_echo", 2),
    ),
    _set(
        "everlife",
        _attributes((HEALTH_MAXIMUM, ModifierLayer.LOCAL_FLAT, 70)),
        _attributes((COMBAT_HEALING_RECEIVED, ModifierLayer.GLOBAL_FLAT, 0.07)),
        _trigger("healing_shield", 2),
    ),
    _set(
        "myriad_venom",
        _attributes((COMBAT_OUTGOING_RATE, ModifierLayer.GLOBAL_FLAT, 0.04)),
        _attributes((COMBAT_CONTROL_CHANCE, ModifierLayer.GLOBAL_FLAT, 0.04)),
        _trigger("venom_touch", 2),
    ),
    _set(
        "mirror_sea",
        _attributes((COMBAT_EVASION, ModifierLayer.GLOBAL_FLAT, 0.05)),
        _attributes((COMBAT_SPEED, ModifierLayer.LOCAL_FLAT, 7)),
        _trigger("evade_counter", 2),
    ),
    _set(
        "mystic_bastion",
        _attributes((COMBAT_DEFENSE, ModifierLayer.LOCAL_FLAT, 9)),
        _attributes((COMBAT_BLOCK_CHANCE, ModifierLayer.GLOBAL_FLAT, 0.05)),
        _trigger("damaged_shield", 2),
    ),
    _set(
        "wind_walk",
        _attributes((COMBAT_SPEED, ModifierLayer.LOCAL_FLAT, 8)),
        _attributes((COMBAT_EVASION, ModifierLayer.GLOBAL_FLAT, 0.04)),
        _trigger("kill_cooldown", 2),
    ),
    _set(
        "spirit_well",
        _attributes((SPIRIT_MAXIMUM, ModifierLayer.LOCAL_FLAT, 40)),
        _attributes((COMBAT_HEALING_RATE, ModifierLayer.GLOBAL_FLAT, 0.06)),
        _trigger("critical_spirit", 2),
    ),
    _set(
        "frost_prison",
        _attributes((COMBAT_CONTROL_CHANCE, ModifierLayer.GLOBAL_FLAT, 0.05)),
        _attributes((COMBAT_TENACITY, ModifierLayer.GLOBAL_FLAT, 0.05)),
        _trigger("frost_touch", 2),
    ),
    _set(
        "starfall",
        _attributes((COMBAT_ACCURACY, ModifierLayer.GLOBAL_FLAT, 0.05)),
        _attributes((COMBAT_CRITICAL_DAMAGE, ModifierLayer.GLOBAL_FLAT, 0.10)),
        _trigger("critical_echo", 1),
    ),
    _set(
        "sky_burn",
        _attributes((COMBAT_OUTGOING_RATE, ModifierLayer.GLOBAL_FLAT, 0.04)),
        _attributes((COMBAT_CRITICAL_CHANCE, ModifierLayer.GLOBAL_FLAT, 0.03)),
        _trigger("burning_touch", 2),
    ),
    _set(
        "void_realm",
        _attributes((COMBAT_FLAT_PENETRATION, ModifierLayer.GLOBAL_FLAT, 7)),
        _attributes((COMBAT_RATE_PENETRATION, ModifierLayer.GLOBAL_FLAT, 0.04)),
        _trigger("execute_echo", 2),
    ),
    _set(
        "samsara",
        _attributes((HEALTH_MAXIMUM, ModifierLayer.LOCAL_FLAT, 65)),
        _attributes((COMBAT_HEALING_RECEIVED, ModifierLayer.GLOBAL_FLAT, 0.06)),
        _trigger("low_health_guard", 2),
    ),
    _set(
        "blood_moon",
        _attributes((COMBAT_CRITICAL_DAMAGE, ModifierLayer.GLOBAL_FLAT, 0.12)),
        _attributes((COMBAT_HEALING_RATE, ModifierLayer.GLOBAL_FLAT, 0.06)),
        _trigger("lifesteal", 2),
    ),
    _set(
        "thunder_judgment",
        _attributes((COMBAT_ATTACK, ModifierLayer.LOCAL_FLAT, 7)),
        _attributes((COMBAT_SPEED, ModifierLayer.LOCAL_FLAT, 6)),
        _trigger("critical_stun", 2),
    ),
    _set(
        "thorn_crown",
        _attributes((COMBAT_DEFENSE, ModifierLayer.LOCAL_FLAT, 8)),
        _attributes((COMBAT_BLOCK_REDUCTION, ModifierLayer.GLOBAL_FLAT, 0.06)),
        _trigger("thorns", 2),
    ),
    _set(
        "spirit_tide",
        _attributes((SPIRIT_MAXIMUM, ModifierLayer.LOCAL_FLAT, 45)),
        _attributes((COMBAT_HEALING_RATE, ModifierLayer.GLOBAL_FLAT, 0.05)),
        _trigger("turn_spirit", 2),
    ),
    _set(
        "hunters_mark",
        _attributes((COMBAT_ACCURACY, ModifierLayer.GLOBAL_FLAT, 0.05)),
        _attributes((COMBAT_OUTGOING_RATE, ModifierLayer.GLOBAL_FLAT, 0.04)),
        _trigger("hit_slow", 2),
    ),
    _set(
        "immortal_guard",
        _attributes((HEALTH_MAXIMUM, ModifierLayer.LOCAL_FLAT, 74)),
        _attributes((COMBAT_CONTROL_RESISTANCE, ModifierLayer.GLOBAL_FLAT, 0.06)),
        _trigger("damaged_heal", 2),
    ),
)


def _validate_blueprints() -> None:
    if len(EQUIPMENT_SLOT_BLUEPRINTS) != 6:
        raise ValueError("正式装备必须覆盖六个标准槽位")
    for values, label in (
        (EQUIPMENT_FAMILY_BLUEPRINTS, "底座族"),
        (EQUIPMENT_SLOT_BLUEPRINTS, "槽位"),
        (EQUIPMENT_PROPERTY_BLUEPRINTS, "词条"),
        (EQUIPMENT_SET_BLUEPRINTS, "套装"),
    ):
        if not values:
            raise ValueError(f"正式装备{label}不能为空")
        keys = [value.key for value in values]
        if len(keys) != len(set(keys)):
            raise ValueError(f"正式装备{label}稳定键不能重复")
    if any(len(value.bonuses) != 3 for value in EQUIPMENT_SET_BLUEPRINTS):
        raise ValueError("正式套装蓝图必须同时声明二、三、四件效果")


_validate_blueprints()


__all__ = [
    "EQUIPMENT_FAMILY_BLUEPRINTS",
    "EQUIPMENT_PROPERTY_BLUEPRINTS",
    "EQUIPMENT_SET_BLUEPRINTS",
    "EQUIPMENT_SLOT_BLUEPRINTS",
    "MECHANIC_EQUIPMENT_PROPERTY_BLUEPRINTS",
    "NUMERIC_EQUIPMENT_PROPERTY_BLUEPRINTS",
    "EquipmentFamilyBlueprint",
    "EquipmentPropertyBlueprint",
    "EquipmentSetBlueprint",
    "EquipmentSlotBlueprint",
    "equipment_trigger_id",
]
