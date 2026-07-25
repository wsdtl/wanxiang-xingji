"""正式装备的稳定身份蓝图，不保存玩家可见文本和战斗数值。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.gameplay import (
    ACCESSORY_SLOT_ID,
    BODY_SLOT_ID,
    FEET_SLOT_ID,
    HANDS_SLOT_ID,
    HEAD_SLOT_ID,
    WAIST_SLOT_ID,
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


MECHANIC_EQUIPMENT_PROPERTY_BLUEPRINTS = (
    EquipmentPropertyBlueprint("critical_echo", "reaction"),
    EquipmentPropertyBlueprint("burning_touch", "ailment"),
    EquipmentPropertyBlueprint("venom_touch", "ailment"),
    EquipmentPropertyBlueprint("frost_touch", "ailment"),
    EquipmentPropertyBlueprint("execute_echo", "offense"),
    EquipmentPropertyBlueprint("kill_haste", "tempo"),
    EquipmentPropertyBlueprint("kill_heal", "sustain"),
    EquipmentPropertyBlueprint("lifesteal", "sustain"),
    EquipmentPropertyBlueprint("thorns", "reaction"),
    EquipmentPropertyBlueprint("evade_counter", "reaction"),
    EquipmentPropertyBlueprint("block_counter", "reaction"),
    EquipmentPropertyBlueprint("shield_counter", "reaction"),
    EquipmentPropertyBlueprint("damaged_heal", "sustain"),
    EquipmentPropertyBlueprint("damaged_shield", "defense"),
    EquipmentPropertyBlueprint("critical_spirit", "resource"),
    EquipmentPropertyBlueprint("hit_spirit", "resource"),
    EquipmentPropertyBlueprint("kill_cooldown", "tempo"),
    EquipmentPropertyBlueprint("turn_heal", "sustain"),
    EquipmentPropertyBlueprint("turn_spirit", "resource"),
    EquipmentPropertyBlueprint("turn_shield", "defense"),
    EquipmentPropertyBlueprint("critical_stun", "control"),
    EquipmentPropertyBlueprint("hit_slow", "control"),
    EquipmentPropertyBlueprint("low_health_guard", "defense"),
    EquipmentPropertyBlueprint("healing_shield", "sustain"),
)


EQUIPMENT_PROPERTY_BLUEPRINTS = (
    *NUMERIC_EQUIPMENT_PROPERTY_BLUEPRINTS,
    *MECHANIC_EQUIPMENT_PROPERTY_BLUEPRINTS,
)


EQUIPMENT_SET_BLUEPRINTS = (
    EquipmentSetBlueprint("army_breaker"),
    EquipmentSetBlueprint("everlife"),
    EquipmentSetBlueprint("myriad_venom"),
    EquipmentSetBlueprint("mirror_sea"),
    EquipmentSetBlueprint("mystic_bastion"),
    EquipmentSetBlueprint("wind_walk"),
    EquipmentSetBlueprint("spirit_well"),
    EquipmentSetBlueprint("frost_prison"),
    EquipmentSetBlueprint("starfall"),
    EquipmentSetBlueprint("sky_burn"),
    EquipmentSetBlueprint("void_realm"),
    EquipmentSetBlueprint("samsara"),
    EquipmentSetBlueprint("blood_moon"),
    EquipmentSetBlueprint("thunder_judgment"),
    EquipmentSetBlueprint("thorn_crown"),
    EquipmentSetBlueprint("spirit_tide"),
    EquipmentSetBlueprint("hunters_mark"),
    EquipmentSetBlueprint("immortal_guard"),
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
]
