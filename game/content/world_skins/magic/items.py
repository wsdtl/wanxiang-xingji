"""魔法世界的消耗品展示。"""

from game.core.gameplay import SkinEntry
from game.content.covenant import COVENANT_ITEM_ENTRIES

from ...catalog import (
    BREAKTHROUGH_TOKEN_ITEM_ID,
    DRAW_TICKET_ITEM_ID,
    BACKPACK_CAPACITY_ITEM_ID,
    COMPANION_SANCTUARY_ITEM_ID,
    DIMENSION_SHIFT_ITEM_ID,
    INSCRIPTION_FEATHER_ITEM_ID,
    LARGE_HEALTH_MEDICINE_ABILITY_ID,
    LARGE_HEALTH_MEDICINE_ITEM_ID,
    LARGE_SPIRIT_MEDICINE_ABILITY_ID,
    LARGE_SPIRIT_MEDICINE_ITEM_ID,
    MEDIUM_HEALTH_MEDICINE_ABILITY_ID,
    MEDIUM_HEALTH_MEDICINE_ITEM_ID,
    MEDIUM_SPIRIT_MEDICINE_ABILITY_ID,
    MEDIUM_SPIRIT_MEDICINE_ITEM_ID,
    SMALL_HEALTH_MEDICINE_ABILITY_ID,
    SMALL_HEALTH_MEDICINE_ITEM_ID,
    SMALL_SPIRIT_MEDICINE_ABILITY_ID,
    SMALL_SPIRIT_MEDICINE_ITEM_ID,
    CHARACTER_EXPERIENCE_ITEM_ID,
    COMPANION_EXPERIENCE_ITEM_ID,
    WEAPON_EXPERIENCE_ITEM_ID,
    WEAPON_MAXIMUM_LEVEL_ITEM_ID,
)


MAGIC_ITEM_ENTRIES = {
    **COVENANT_ITEM_ENTRIES,
    BREAKTHROUGH_TOKEN_ITEM_ID: SkinEntry(
        name="星界升格契印",
        description="封存一次生命升格所需的星界许可；抵达阶位关隘后自动消耗。",
        icon="✦",
    ),
    DRAW_TICKET_ITEM_ID: SkinEntry(
        name="星辉秘券",
        description="封存一束尚未坍缩的战斗可能；投入界门后会显化为一次确定收获。",
        icon="🎟️",
    ),
    INSCRIPTION_FEATHER_ITEM_ID: SkinEntry(
        name="铭刻之羽",
        description="承载一段不可复刻的旧愿，可为武器、装备或武器能力留下私名。",
        icon="📜",
    ),
    BACKPACK_CAPACITY_ITEM_ID: SkinEntry(
        name="折叠空间晶砂",
        description="融入背包后永久增加 5 格空间；背包最多扩展至 140 格。",
        icon="⌛",
    ),
    COMPANION_SANCTUARY_ITEM_ID: SkinEntry(
        name="幻兽庭钥印",
        description="在当前位面开启一次幻兽庭入口；名额不足时不会消耗。",
        icon="🧿",
    ),
    DIMENSION_SHIFT_ITEM_ID: SkinEntry(
        name="位面跃迁晶核",
        description="登录另一世界时自动消耗一枚；查看界门或跃迁失败不会消耗。",
        icon="🧿",
    ),
    WEAPON_MAXIMUM_LEVEL_ITEM_ID: SkinEntry(
        name="极限锻造催化剂",
        description="重塑一件武器的承载极限，使其等级上限提升 1 级，最高 100 级。",
        icon="⚗️",
    ),
    CHARACTER_EXPERIENCE_ITEM_ID: SkinEntry(
        name="贤者忆晶",
        description="为角色补充人物经验，单次最多增加 1,000,000 点。",
        icon="📖",
    ),
    WEAPON_EXPERIENCE_ITEM_ID: SkinEntry(
        name="时序晶髓",
        description="为指定武器补充成长经验，单次最多增加 40,000 点，无法超过武器等级上限。",
        icon="💠",
    ),
    COMPANION_EXPERIENCE_ITEM_ID: SkinEntry(
        name="契灵成长晶核",
        description="为指定伙伴补充成长经验，单次最多增加 30,000 点。",
        icon="🪶",
    ),
    SMALL_HEALTH_MEDICINE_ABILITY_ID: SkinEntry(name="饮用小型生命药剂"),
    MEDIUM_HEALTH_MEDICINE_ABILITY_ID: SkinEntry(name="饮用中型生命药剂"),
    LARGE_HEALTH_MEDICINE_ABILITY_ID: SkinEntry(name="饮用大型生命药剂"),
    SMALL_SPIRIT_MEDICINE_ABILITY_ID: SkinEntry(name="饮用小型魔力药剂"),
    MEDIUM_SPIRIT_MEDICINE_ABILITY_ID: SkinEntry(name="饮用中型魔力药剂"),
    LARGE_SPIRIT_MEDICINE_ABILITY_ID: SkinEntry(name="饮用大型魔力药剂"),
    SMALL_HEALTH_MEDICINE_ITEM_ID: SkinEntry(
        name="小型生命药剂",
        description="恢复最大生命的 12%。",
        icon="🧪",
    ),
    MEDIUM_HEALTH_MEDICINE_ITEM_ID: SkinEntry(
        name="中型生命药剂",
        description="恢复最大生命的 25%。",
        icon="🧪",
    ),
    LARGE_HEALTH_MEDICINE_ITEM_ID: SkinEntry(
        name="大型生命药剂",
        description="恢复最大生命的 50%。",
        icon="🧪",
    ),
    SMALL_SPIRIT_MEDICINE_ITEM_ID: SkinEntry(
        name="小型魔力药剂",
        description="恢复最大魔力的 12%。",
        icon="💧",
    ),
    MEDIUM_SPIRIT_MEDICINE_ITEM_ID: SkinEntry(
        name="中型魔力药剂",
        description="恢复最大魔力的 25%。",
        icon="💧",
    ),
    LARGE_SPIRIT_MEDICINE_ITEM_ID: SkinEntry(
        name="大型魔力药剂",
        description="恢复最大魔力的 50%。",
        icon="💧",
    ),
}


__all__ = ["MAGIC_ITEM_ENTRIES"]
