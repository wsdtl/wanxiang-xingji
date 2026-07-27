"""魔法世界的战斗展示。"""

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
from .equipment import MAGIC_EQUIPMENT_ENTRIES
from .weapons import MAGIC_WEAPON_ENTRIES


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
        **MAGIC_WEAPON_ENTRIES,
        **MAGIC_EQUIPMENT_ENTRIES,
    },
    base_effect_names={
        "effect.basic_attack": "基础攻击·战技效果",
        "effect.breaking_strike": "破势斩·战技效果",
        "effect.recover_small_health": "初级生命药剂·恢复效果",
        "effect.recover_medium_health": "中级生命药剂·恢复效果",
        "effect.recover_large_health": "高级生命药剂·恢复效果",
        "effect.recover_small_spirit": "初级魔力药剂·恢复效果",
        "effect.recover_medium_spirit": "中级魔力药剂·恢复效果",
        "effect.recover_large_spirit": "高级魔力药剂·恢复效果",
        WEAPON_MARK_EFFECT_ID: "协同刻印",
        WEAPON_CHARGE_EFFECT_ID: "奥能蓄势",
    },
    damage_names={
        "damage.physical": "物理伤害",
        "damage.fire": "火焰伤害",
        "damage.frost": "寒霜伤害",
        "damage.true": "纯粹伤害",
        "damage.poison": "剧毒伤害",
    },
    interceptor_names={
        "interceptor.weapon.death_guard": "濒死守护",
        "interceptor.weapon.immunity": "绝对免疫",
        "interceptor.weapon.damage_cap": "伤害限幅",
    },
    constraint_names={
        "target_constraint.weapon.taunt": "强制锁定",
        "target_constraint.weapon.untargetable": "不可选取",
    },
    control_names={
        "control.stun": "眩晕",
        "control.freeze": "冻结",
        "control.sleep": "睡眠",
    },
)


MAGIC_COMBAT_ENTRIES = {
    BASIC_COMBAT_FEATURE_ID: SkinEntry(name="基础战技"),
    PHYSICAL_DAMAGE_ID: SkinEntry(name="物理伤害"),
    BASIC_ATTACK_ABILITY_ID: SkinEntry(
        name="基础攻击",
        description="对单个敌人造成相当于自身攻击力的物理伤害。",
    ),
    BREAKING_STRIKE_ABILITY_ID: SkinEntry(
        name="破势斩",
        description=("对单个敌人造成相当于自身攻击力 × 150%的物理伤害，消耗 20 点魔力，冷却 2 次自身行动。"),
    ),
    **_MECHANISM_ENTRIES,
}


__all__ = ["MAGIC_COMBAT_ENTRIES"]
