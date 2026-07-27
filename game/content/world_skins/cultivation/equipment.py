"""太玄界的装备、词条与套装展示；规则蓝图不保存玩家可见文本。"""

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
    "mystic_sky": ("昆仑", "昆仑一脉的装备器型。"),
    "crimson_cloud": ("扶桑", "扶桑一脉的装备器型。"),
    "azure_tide": ("归墟", "归墟一脉的装备器型。"),
    "verdant_void": ("青丘", "青丘一脉的装备器型。"),
    "mountain_guard": ("不周", "不周一脉的装备器型。"),
    "flowing_light": ("瑶池", "瑶池一脉的装备器型。"),
    "shadow_bamboo": ("幽都", "幽都一脉的装备器型。"),
    "star_array": ("紫微", "紫微一脉的装备器型。"),
    "great_void": ("太虚", "太虚一脉的装备器型。"),
    "startled_thunder": ("雷泽", "雷泽一脉的装备器型。"),
    "ashen_plume": ("丹穴", "丹穴一脉的装备器型。"),
    "returning_origin": ("蓬莱", "蓬莱一脉的装备器型。"),
}
_SLOT_NAMES = {
    "head": "冠",
    "body": "法袍",
    "hands": "护腕",
    "waist": "灵带",
    "feet": "云履",
    "accessory": "佩",
}
_PROPERTY_DISPLAY = {
    "health": ("气血", "提高气血上限"),
    "spirit": ("灵力", "提高灵力上限"),
    "attack": ("攻伐", "提高基础攻击"),
    "defense": ("护体", "提高基础防御"),
    "speed": ("身法", "提高行动速度"),
    "accuracy": ("洞察", "提高命中"),
    "evasion": ("幻步", "提高闪避"),
    "critical_chance": ("会心", "提高暴击率"),
    "critical_damage": ("会心威势", "提高暴击伤害"),
    "block_chance": ("格挡", "提高格挡率"),
    "block_reduction": ("坚壁", "提高格挡减伤"),
    "outgoing": ("增伤", "提高造成的伤害"),
    "incoming": ("减伤", "降低承受的伤害"),
    "flat_penetration": ("破甲", "提高固定穿透"),
    "rate_penetration": ("穿甲", "提高比例穿透"),
    "healing": ("疗愈", "提高造成的治疗"),
    "healing_received": ("纳生", "提高受到的治疗"),
    "control_chance": ("控灵", "提高控制命中"),
    "control_resistance": ("定神", "提高控制抵抗"),
    "tenacity": ("韧性", "缩短受到的控制"),
    "vital_guard": ("体魄", "同时提高气血上限和防御"),
    "spirit_step": ("灵动", "同时提高灵力上限和速度"),
    "keen_edge": ("锐眼", "同时提高攻击和命中"),
    "mystic_armor": ("玄甲", "同时提高防御和韧性"),
    "critical_echo": ("暴烈回响", "暴击时追加回响伤害"),
    "burning_touch": ("燃痕", "命中时追加真火伤害"),
    "venom_touch": ("毒蚀", "命中时施加周期毒伤"),
    "frost_touch": ("寒蚀", "命中时追加玄霜伤害"),
    "execute_echo": ("追命", "攻击残血目标时追加伤害"),
    "kill_haste": ("斩敌疾行", "击败目标后短暂加速"),
    "kill_heal": ("斩敌回春", "击败目标后恢复气血"),
    "lifesteal": ("饮血", "按实际伤害恢复气血"),
    "thorns": ("反震", "受到直接伤害时反震"),
    "evade_counter": ("踏影反击", "闪避后反击来袭者"),
    "block_counter": ("守御反击", "格挡后反击来袭者"),
    "shield_counter": ("碎盾反击", "护盾破碎时反击"),
    "damaged_heal": ("受创回春", "受到伤害后恢复少量气血"),
    "damaged_shield": ("受创生盾", "受到伤害后获得护盾"),
    "critical_spirit": ("会心回灵", "暴击时恢复灵力"),
    "hit_spirit": ("命中回灵", "命中时恢复灵力"),
    "kill_cooldown": ("斩敌回转", "击败目标后缩短最长冷却"),
    "turn_heal": ("周天回春", "自身回合开始时恢复气血"),
    "turn_spirit": ("周天回灵", "自身回合开始时恢复灵力"),
    "turn_shield": ("周天生盾", "自身回合开始时获得护盾"),
    "critical_stun": ("会心震魂", "暴击时尝试眩晕"),
    "hit_slow": ("迟滞", "命中时短暂降低目标速度"),
    "low_health_guard": ("危境护命", "濒危受击时获得一次保命"),
    "healing_shield": ("愈后生盾", "获得有效治疗后生成护盾"),
}
_SET_DISPLAY = {
    "army_breaker": ("七杀破军套", "穿透与暴击回响协同"),
    "everlife": ("彭祖长生套", "恢复与受疗协同"),
    "myriad_venom": ("神农百草套", "命中与周期毒伤协同"),
    "mirror_sea": ("庄周梦蝶套", "闪避与反击协同"),
    "mystic_bastion": ("玄武镇世套", "格挡与护盾协同"),
    "wind_walk": ("列子御风套", "速度与行动节奏协同"),
    "spirit_well": ("周天归元套", "灵力循环与回复协同"),
    "frost_prison": ("玄冥寒狱套", "控制与玄霜协同"),
    "starfall": ("北斗天罡套", "命中与会心协同"),
    "sky_burn": ("金乌焚天套", "真火与增伤协同"),
    "void_realm": ("太虚无相套", "穿盾与无相回响协同"),
    "samsara": ("凤凰涅槃套", "残血生存与击败恢复协同"),
    "blood_moon": ("刑天战血套", "暴击、汲取与持续作战协同"),
    "thunder_judgment": ("九天雷劫套", "攻速与暴击控制协同"),
    "thorn_crown": ("玄武荆甲套", "格挡减伤与反震协同"),
    "spirit_tide": ("沧海归墟套", "灵力上限与回合恢复协同"),
    "hunters_mark": ("后羿逐日套", "命中、增伤与迟缓协同"),
    "immortal_guard": ("不周天柱套", "气血、抗性与受创恢复协同"),
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
            raise ValueError(f"太玄界{label}展示键必须完整覆盖规则蓝图")
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
                name=f"{name}器胚",
                description="保存随机词条、品质和套装印记的独立装备资产。",
                icon="🛡",
            )
            entries[equipment_definition_id(family.key, slot.key)] = SkinEntry(
                name=name,
                description="随机词条与套装印记均由具体装备实例决定。",
                icon="🛡",
            )
    return entries


CULTIVATION_EQUIPMENT_ENTRIES = _build_equipment_entries()


__all__ = ["CULTIVATION_EQUIPMENT_ENTRIES"]
