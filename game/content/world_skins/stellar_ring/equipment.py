"""星环界的装备、词条与套装展示；规则蓝图不保存玩家可见文本。"""

from game.core.gameplay import SkinEntry

from ...catalog.equipment.blueprints import (
    EQUIPMENT_FAMILY_BLUEPRINTS,
    EQUIPMENT_PROPERTY_BLUEPRINTS,
    EQUIPMENT_SET_BLUEPRINTS,
    EQUIPMENT_SLOT_BLUEPRINTS,
)
from ...catalog.equipment.definitions import (
    equipment_definition_id,
    equipment_family_id,
    equipment_item_id,
    equipment_set_id,
)
from ...catalog.equipment.properties import equipment_property_id
from ...catalog.item.exchange import equipment_set_blueprint_item_id


_FAMILY_DISPLAY = {
    "mystic_sky": ("欧几里得", "天穹观测阵采用的几何轻装型制。"),
    "crimson_cloud": ("法拉第", "赤炉峡带使用的耐热隔离型制。"),
    "azure_tide": ("卡西尼", "镜海冷却区使用的密封兵装型制。"),
    "verdant_void": ("达尔文", "森环培育层制造的仿生兵装型制。"),
    "mountain_guard": ("阿特拉斯型", "断环修复工程使用的承重兵装型制。"),
    "flowing_light": ("开普勒", "晨昏轨道领航员使用的高速兵装型制。"),
    "shadow_bamboo": ("图灵", "静默裂廊发现的低可见兵装型制。"),
    "star_array": ("天环阵列", "依据天环轨道校准的阵列兵装型制。"),
    "great_void": ("奥尔特", "第十三暗环保存的深空兵装型制。"),
    "startled_thunder": ("特斯拉", "高压能源网维护队使用的兵装型制。"),
    "ashen_plume": ("凤凰座", "废热回收系统衍生的过载兵装型制。"),
    "returning_origin": ("安提凯希拉型", "造物母厂最早一批设计档案中的型制。"),
}
_SLOT_NAMES = {
    "head": "头冠",
    "body": "法袍",
    "hands": "护腕",
    "waist": "束带",
    "feet": "长靴",
    "accessory": "护符",
}
_PROPERTY_DISPLAY = {
    "health": ("生命", "提高气血上限"),
    "spirit": ("同步", "提高同步上限"),
    "attack": ("威能", "提高基础攻击"),
    "defense": ("护甲", "提高基础防御"),
    "speed": ("迅捷", "提高行动速度"),
    "accuracy": ("精准", "提高命中"),
    "evasion": ("幻影", "提高闪避"),
    "critical_chance": ("致命", "提高暴击率"),
    "critical_damage": ("暴烈", "提高暴击伤害"),
    "block_chance": ("格挡", "提高格挡率"),
    "block_reduction": ("坚壁", "提高格挡减伤"),
    "outgoing": ("强攻", "提高造成的伤害"),
    "incoming": ("减伤", "降低承受的伤害"),
    "flat_penetration": ("破甲", "提高固定穿透"),
    "rate_penetration": ("穿透", "提高比例穿透"),
    "healing": ("治愈", "提高造成的治疗"),
    "healing_received": ("复苏", "提高受到的治疗"),
    "control_chance": ("支配", "提高控制命中"),
    "control_resistance": ("抵抗", "提高控制抵抗"),
    "tenacity": ("坚韧", "缩短受到的控制"),
    "vital_guard": ("刚毅", "同时提高气血和防御"),
    "spirit_step": ("同步流转", "同时提高同步值和速度"),
    "keen_edge": ("锐锋", "同时提高攻击和命中"),
    "mystic_armor": ("秘法甲胄", "同时提高防御和韧性"),
    "critical_echo": ("致命回响", "暴击时追加回响伤害"),
    "burning_touch": ("灼热之触", "命中时追加火焰伤害"),
    "venom_touch": ("疫病之触", "命中时施加周期毒伤"),
    "frost_touch": ("寒冰之触", "命中时追加冰霜伤害"),
    "execute_echo": ("处决回响", "攻击残血目标时追加伤害"),
    "kill_haste": ("猎杀疾行", "击败目标后短暂加速"),
    "kill_heal": ("猎杀治愈", "击败目标后恢复气血"),
    "lifesteal": ("生命汲取", "按实际伤害恢复气血"),
    "thorns": ("荆棘反伤", "受到直接伤害时反震"),
    "evade_counter": ("幻影反击", "闪避后反击来袭者"),
    "block_counter": ("格挡反击", "格挡后反击来袭者"),
    "shield_counter": ("破盾反击", "护盾破碎时反击"),
    "damaged_heal": ("受创治愈", "受到伤害后恢复少量气血"),
    "damaged_shield": ("受创护盾", "受到伤害后获得护盾"),
    "critical_spirit": ("暴击回流", "暴击时恢复同步值"),
    "hit_spirit": ("命中回流", "命中时恢复同步值"),
    "kill_cooldown": ("猎杀回转", "击败目标后缩短最长冷却"),
    "turn_heal": ("生命涌动", "自身回合开始时恢复气血"),
    "turn_spirit": ("同步涌动", "自身回合开始时恢复同步值"),
    "turn_shield": ("护盾涌动", "自身回合开始时获得护盾"),
    "critical_stun": ("致命震荡", "暴击时尝试眩晕"),
    "hit_slow": ("迟缓诅咒", "命中时短暂降低目标速度"),
    "low_health_guard": ("濒死守护", "濒危受击时获得一次保命"),
    "healing_shield": ("治愈屏障", "获得有效治疗后生成护盾"),
}
_SET_DISPLAY = {
    "army_breaker": ("阿基米德破阵套装", "穿透与暴击回响协同"),
    "everlife": ("阿斯克勒庇俄斯常青套装", "恢复与受疗协同"),
    "myriad_venom": ("潘多拉疫源套装", "命中与周期毒伤协同"),
    "mirror_sea": ("纳西索斯镜像套装", "闪避与反击协同"),
    "mystic_bastion": ("埃癸斯堡垒套装", "格挡与护盾协同"),
    "wind_walk": ("洛伦兹矢量套装", "速度与行动节奏协同"),
    "spirit_well": ("麦克斯韦同步套装", "同步循环与回复协同"),
    "frost_prison": ("斯卡蒂零温套装", "控制与冰霜协同"),
    "starfall": ("开普勒轨道套装", "命中与暴击协同"),
    "sky_burn": ("普罗米修斯赤炉套装", "火焰与增伤协同"),
    "void_realm": ("厄瑞玻斯暗环套装", "穿盾与真实回响协同"),
    "samsara": ("菲尼克斯备份套装", "残血生存与击败恢复协同"),
    "blood_moon": ("哈维血月循环套装", "暴击、汲取与持续作战协同"),
    "thunder_judgment": ("伏打雷霆裁决套装", "攻速与暴击控制协同"),
    "thorn_crown": ("霍尔棘冠防护套装", "格挡减伤与反震协同"),
    "spirit_tide": ("狄拉克灵潮套装", "同步上限与回合恢复协同"),
    "hunters_mark": ("阿波罗猎标套装", "命中、增伤与迟缓协同"),
    "immortal_guard": ("诺依曼不灭冗余套装", "生命、抗性与受创恢复协同"),
}


def _build_equipment_entries() -> dict[str, SkinEntry]:
    expected = (
        ({value.key for value in EQUIPMENT_FAMILY_BLUEPRINTS}, set(_FAMILY_DISPLAY), "装备族"),
        ({value.key for value in EQUIPMENT_SLOT_BLUEPRINTS}, set(_SLOT_NAMES), "装备槽位"),
        ({value.key for value in EQUIPMENT_PROPERTY_BLUEPRINTS}, set(_PROPERTY_DISPLAY), "装备词条"),
        ({value.key for value in EQUIPMENT_SET_BLUEPRINTS}, set(_SET_DISPLAY), "装备套装"),
    )
    for blueprint_keys, display_keys, label in expected:
        if blueprint_keys != display_keys:
            raise ValueError(f"星环界{label}展示键必须完整覆盖规则蓝图")
    entries: dict[str, SkinEntry] = {}
    for family in EQUIPMENT_FAMILY_BLUEPRINTS:
        family_name, family_description = _FAMILY_DISPLAY[family.key]
        entries[equipment_family_id(family.key)] = SkinEntry(name=family_name, description=family_description, icon="🛡")
    for value in EQUIPMENT_SET_BLUEPRINTS:
        name, description = _SET_DISPLAY[value.key]
        set_id = equipment_set_id(value.key)
        entries[set_id] = SkinEntry(name=name, description=description, icon="◆")
        entries[equipment_set_blueprint_item_id(value.key)] = SkinEntry(
            name=f"{name}图纸",
            description=f"归航公约定向封存的套装图纸；使用后只固定{name}身份，其余属性随机。",
            icon="▧",
        )
    for value in EQUIPMENT_PROPERTY_BLUEPRINTS:
        name, description = _PROPERTY_DISPLAY[value.key]
        entries[equipment_property_id(value.key)] = SkinEntry(name=name, description=description, icon="✦")
    for family in EQUIPMENT_FAMILY_BLUEPRINTS:
        family_name = _FAMILY_DISPLAY[family.key][0]
        for slot in EQUIPMENT_SLOT_BLUEPRINTS:
            name = f"{family_name}{_SLOT_NAMES[slot.key]}"
            entries[equipment_item_id(family.key, slot.key)] = SkinEntry(
                name=f"{name}原型",
                description="记录随机战斗属性、品质与套装协议的独立装备。",
                icon="🛡",
            )
            entries[equipment_definition_id(family.key, slot.key)] = SkinEntry(
                name=name,
                description="战斗属性与套装协议均由具体装备实例决定。",
                icon="🛡",
            )
    return entries


STELLAR_RING_EQUIPMENT_ENTRIES = _build_equipment_entries()


__all__ = ["STELLAR_RING_EQUIPMENT_ENTRIES"]
