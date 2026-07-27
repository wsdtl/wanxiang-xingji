"""太玄界的战斗展示。"""

from game.core.gameplay import SkinEntry

from ...catalog import (
    BASIC_ATTACK_ABILITY_ID,
    BASIC_COMBAT_FEATURE_ID,
    BREAKING_STRIKE_ABILITY_ID,
    PHYSICAL_DAMAGE_ID,
)
from ...catalog.combat.definitions import BASE_CONTROLS, BASE_DAMAGE_TYPES, BASE_EFFECTS
from ...catalog.equipment.properties import EQUIPMENT_PROPERTY_CONTENT
from ...catalog.weapon.mechanics import (
    WEAPON_CHARGE_EFFECT_ID,
    WEAPON_MARK_EFFECT_ID,
    WEAPON_MECHANIC_CONTENT,
)
from ..combat_mechanisms import build_combat_mechanism_entries
from .equipment import CULTIVATION_EQUIPMENT_ENTRIES
from .weapons import CULTIVATION_WEAPON_ENTRIES


_MECHANISM_ENTRIES = build_combat_mechanism_entries(
    effects=(
        *BASE_EFFECTS,
        *WEAPON_MECHANIC_CONTENT.effects,
        *EQUIPMENT_PROPERTY_CONTENT.effects,
    ),
    triggers=(
        *WEAPON_MECHANIC_CONTENT.triggers,
        *EQUIPMENT_PROPERTY_CONTENT.triggers,
    ),
    interceptors=WEAPON_MECHANIC_CONTENT.interceptors,
    target_constraints=WEAPON_MECHANIC_CONTENT.constraints,
    damage_types=BASE_DAMAGE_TYPES,
    controls=BASE_CONTROLS,
    owner_entries={
        **CULTIVATION_WEAPON_ENTRIES,
        **CULTIVATION_EQUIPMENT_ENTRIES,
    },
    base_effect_names={
        "effect.basic_attack": "基础攻击·招式效果",
        "effect.breaking_strike": "破势·招式效果",
        "effect.recover_small_health": "小还丹·回气效果",
        "effect.recover_medium_health": "中还丹·回气效果",
        "effect.recover_large_health": "大还丹·回气效果",
        "effect.recover_small_spirit": "小聚灵丹·回灵效果",
        "effect.recover_medium_spirit": "中聚灵丹·回灵效果",
        "effect.recover_large_spirit": "大聚灵丹·回灵效果",
        WEAPON_MARK_EFFECT_ID: "同心印",
        WEAPON_CHARGE_EFFECT_ID: "蓄势",
    },
    damage_names={
        "damage.physical": "物理伤害",
        "damage.fire": "真火伤害",
        "damage.frost": "玄霜伤害",
        "damage.true": "无相伤害",
        "damage.poison": "毒煞伤害",
    },
    interceptor_names={
        "interceptor.weapon.death_guard": "护命截伤",
        "interceptor.weapon.immunity": "万法不侵",
        "interceptor.weapon.damage_cap": "承伤封顶",
    },
    constraint_names={
        "target_constraint.weapon.taunt": "强制应战",
        "target_constraint.weapon.untargetable": "遁形避战",
    },
    control_names={
        "control.stun": "眩晕",
        "control.freeze": "冰封",
        "control.sleep": "昏睡",
    },
)


CULTIVATION_COMBAT_ENTRIES = {
    BASIC_COMBAT_FEATURE_ID: SkinEntry(name="基础斗法"),
    PHYSICAL_DAMAGE_ID: SkinEntry(name="物理伤害"),
    BASIC_ATTACK_ABILITY_ID: SkinEntry(
        name="基础攻击",
        description="对单个敌人造成相当于自身攻击力的物理伤害。",
    ),
    BREAKING_STRIKE_ABILITY_ID: SkinEntry(
        name="破势",
        description=("对单个敌人造成相当于自身攻击力 × 150%的物理伤害，消耗 20 点灵力，冷却 2 次自身行动。"),
    ),
    **_MECHANISM_ENTRIES,
}


__all__ = ["CULTIVATION_COMBAT_ENTRIES"]
