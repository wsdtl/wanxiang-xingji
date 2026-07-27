"""魔法世界的装备、词条与套装展示；规则蓝图不保存玩家可见文本。"""

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
    "mystic_sky": ("奥林匹斯", "奥林匹斯系列的魔法装备型制。"),
    "crimson_cloud": ("穆斯贝尔", "穆斯贝尔系列的魔法装备型制。"),
    "azure_tide": ("亚特兰蒂斯", "亚特兰蒂斯系列的魔法装备型制。"),
    "verdant_void": ("阿瓦隆", "阿瓦隆系列的魔法装备型制。"),
    "mountain_guard": ("阿斯加德", "阿斯加德系列的魔法装备型制。"),
    "flowing_light": ("伊甸", "伊甸系列的魔法装备型制。"),
    "shadow_bamboo": ("塔尔塔罗斯", "塔尔塔罗斯系列的魔法装备型制。"),
    "star_array": ("黄道", "黄道系列的魔法装备型制。"),
    "great_void": ("卡俄斯", "卡俄斯系列的魔法装备型制。"),
    "startled_thunder": ("瓦尔哈拉", "瓦尔哈拉系列的魔法装备型制。"),
    "ashen_plume": ("菲尼克斯", "菲尼克斯系列的魔法装备型制。"),
    "returning_origin": ("世界树", "世界树系列的魔法装备型制。"),
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
    "health": ("生命", "提高生命上限"),
    "spirit": ("魔力", "提高魔力上限"),
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
    "vital_guard": ("刚毅", "同时提高生命上限和防御"),
    "spirit_step": ("奥能流转", "同时提高魔力上限和速度"),
    "keen_edge": ("锐锋", "同时提高攻击和命中"),
    "mystic_armor": ("秘法甲胄", "同时提高防御和韧性"),
    "critical_echo": ("致命回响", "暴击时追加回响伤害"),
    "burning_touch": ("灼热之触", "命中时追加火焰伤害"),
    "venom_touch": ("疫病之触", "命中时施加周期毒伤"),
    "frost_touch": ("寒冰之触", "命中时追加寒霜伤害"),
    "execute_echo": ("处决回响", "攻击残血目标时追加伤害"),
    "kill_haste": ("猎杀疾行", "击败目标后短暂加速"),
    "kill_heal": ("猎杀治愈", "击败目标后恢复生命"),
    "lifesteal": ("生命汲取", "按实际伤害恢复生命"),
    "thorns": ("荆棘反伤", "受到直接伤害时反震"),
    "evade_counter": ("幻影反击", "闪避后反击来袭者"),
    "block_counter": ("格挡反击", "格挡后反击来袭者"),
    "shield_counter": ("破盾反击", "护盾破碎时反击"),
    "damaged_heal": ("受创治愈", "受到伤害后恢复少量生命"),
    "damaged_shield": ("受创护盾", "受到伤害后获得护盾"),
    "critical_spirit": ("致命回魔", "暴击时恢复魔力"),
    "hit_spirit": ("命中回魔", "命中时恢复魔力"),
    "kill_cooldown": ("猎杀回转", "击败目标后缩短最长冷却"),
    "turn_heal": ("生命涌动", "自身回合开始时恢复生命"),
    "turn_spirit": ("魔力涌动", "自身回合开始时恢复魔力"),
    "turn_shield": ("护盾涌动", "自身回合开始时获得护盾"),
    "critical_stun": ("致命震荡", "暴击时尝试眩晕"),
    "hit_slow": ("迟缓诅咒", "命中时短暂降低目标速度"),
    "low_health_guard": ("濒死守护", "濒危受击时获得一次保命"),
    "healing_shield": ("治愈屏障", "获得有效治疗后生成护盾"),
}
_SET_DISPLAY = {
    "army_breaker": ("阿瑞斯征服套装", "穿透与暴击回响协同"),
    "everlife": ("伊登青春套装", "恢复与受疗协同"),
    "myriad_venom": ("潘多拉疫灾套装", "命中与周期毒伤协同"),
    "mirror_sea": ("赫尔墨斯幻行套装", "闪避与反击协同"),
    "mystic_bastion": ("埃癸斯壁垒套装", "格挡与护盾协同"),
    "wind_walk": ("玻瑞阿斯北风套装", "速度与行动节奏协同"),
    "spirit_well": ("密米尔智慧泉套装", "魔力循环与回复协同"),
    "frost_prison": ("尼福尔寒狱套装", "控制与寒霜协同"),
    "starfall": ("阿斯特赖俄斯星陨套装", "命中与暴击协同"),
    "sky_burn": ("苏尔特炼狱套装", "火焰与增伤协同"),
    "void_realm": ("厄瑞玻斯虚界套装", "穿盾与纯粹伤害回响协同"),
    "samsara": ("菲尼克斯重生套装", "残血生存与击败恢复协同"),
    "blood_moon": ("德古拉血月套装", "暴击、汲取与持续作战协同"),
    "thunder_judgment": ("索尔雷霆裁决套装", "攻速与暴击控制协同"),
    "thorn_crown": ("涅墨亚棘冠套装", "格挡减伤与反震协同"),
    "spirit_tide": ("波塞冬灵潮套装", "魔力上限与回合恢复协同"),
    "hunters_mark": ("阿尔忒弥斯猎印套装", "命中、增伤与迟缓协同"),
    "immortal_guard": ("赫拉克勒斯不灭套装", "生命、抗性与受创恢复协同"),
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
            raise ValueError(f"魔法世界{label}展示键必须完整覆盖规则蓝图")
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
                description="记录随机魔法属性、品质与套装印记的独立装备。",
                icon="🛡",
            )
            entries[equipment_definition_id(family.key, slot.key)] = SkinEntry(
                name=name,
                description="魔法属性与套装印记均由具体装备实例决定。",
                icon="🛡",
            )
    return entries


MAGIC_EQUIPMENT_ENTRIES = _build_equipment_entries()


__all__ = ["MAGIC_EQUIPMENT_ENTRIES"]
