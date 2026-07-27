"""星环界的消耗品展示。"""

from game.core.gameplay import SkinEntry
from game.content.covenant import COVENANT_ITEM_ENTRIES

from ...catalog import (
    BACKPACK_CAPACITY_INCREMENT,
    BREAKTHROUGH_TOKEN_ITEM_ID,
    DRAW_TICKET_ITEM_ID,
    BACKPACK_CAPACITY_ITEM_ID,
    BACKPACK_CAPACITY_MAXIMUM,
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


STELLAR_RING_ITEM_ENTRIES = {
    **COVENANT_ITEM_ENTRIES,
    BREAKTHROUGH_TOKEN_ITEM_ID: SkinEntry(
        name="序列升格许可",
        description="封存一次生命升格所需的中枢许可；抵达阶位关隘后自动消耗。",
        icon="✦",
    ),
    DRAW_TICKET_ITEM_ID: SkinEntry(
        name="未定序列券",
        description="封存一段等待执行的战斗可能；接入界门后会解析为一次确定收获。",
        icon="🎟️",
    ),
    INSCRIPTION_FEATHER_ITEM_ID: SkinEntry(
        name="铭刻之羽",
        description="承载一段不可复刻的旧愿，可为武器、装备或武器能力留下私名。",
        icon="📜",
    ),
    BACKPACK_CAPACITY_ITEM_ID: SkinEntry(
        name="折叠仓扩容片",
        description=(
            f"融入背包后永久增加 {BACKPACK_CAPACITY_INCREMENT} 格空间；"
            f"背包最多扩展至 {BACKPACK_CAPACITY_MAXIMUM} 格。"
        ),
        icon="⌛",
    ),
    COMPANION_SANCTUARY_ITEM_ID: SkinEntry(
        name="生态舱密钥",
        description="在当前世界开启一次回声育成舱；名额不足时不会消耗。",
        icon="🧿",
    ),
    DIMENSION_SHIFT_ITEM_ID: SkinEntry(
        name="界门相位核",
        description="登录另一世界时自动消耗一枚；查看界门或跃迁失败不会消耗。",
        icon="🧿",
    ),
    WEAPON_MAXIMUM_LEVEL_ITEM_ID: SkinEntry(
        name="极限承载芯片",
        description="重塑一件武器的承载极限，使其等级上限提升 1 级，最高 100 级。",
        icon="⚗️",
    ),
    CHARACTER_EXPERIENCE_ITEM_ID: SkinEntry(
        name="认知跃迁模组",
        description="为角色补充人物经验，单次最多增加 1,000,000 点。",
        icon="📖",
    ),
    WEAPON_EXPERIENCE_ITEM_ID: SkinEntry(
        name="时序经验模组",
        description="为指定武器补充成长经验，单次最多增加 40,000 点，无法超过武器等级上限。",
        icon="💠",
    ),
    COMPANION_EXPERIENCE_ITEM_ID: SkinEntry(
        name="伴生迭代模组",
        description="为指定伙伴补充成长经验，单次最多增加 30,000 点。",
        icon="🪶",
    ),
    SMALL_HEALTH_MEDICINE_ABILITY_ID: SkinEntry(
        name="注入小型生命修复剂",
        description="恢复自身生命上限的 12%。",
    ),
    MEDIUM_HEALTH_MEDICINE_ABILITY_ID: SkinEntry(
        name="注入中型生命修复剂",
        description="恢复自身生命上限的 25%。",
    ),
    LARGE_HEALTH_MEDICINE_ABILITY_ID: SkinEntry(
        name="注入大型生命修复剂",
        description="恢复自身生命上限的 50%。",
    ),
    SMALL_SPIRIT_MEDICINE_ABILITY_ID: SkinEntry(
        name="使用小型同步剂",
        description="恢复自身同步上限的 12%。",
    ),
    MEDIUM_SPIRIT_MEDICINE_ABILITY_ID: SkinEntry(
        name="使用中型同步剂",
        description="恢复自身同步上限的 25%。",
    ),
    LARGE_SPIRIT_MEDICINE_ABILITY_ID: SkinEntry(
        name="使用大型同步剂",
        description="恢复自身同步上限的 50%。",
    ),
    SMALL_HEALTH_MEDICINE_ITEM_ID: SkinEntry(
        name="小型生命修复剂",
        description="恢复生命上限的 12%。",
        icon="🧪",
    ),
    MEDIUM_HEALTH_MEDICINE_ITEM_ID: SkinEntry(
        name="中型生命修复剂",
        description="恢复生命上限的 25%。",
        icon="🧪",
    ),
    LARGE_HEALTH_MEDICINE_ITEM_ID: SkinEntry(
        name="大型生命修复剂",
        description="恢复生命上限的 50%。",
        icon="🧪",
    ),
    SMALL_SPIRIT_MEDICINE_ITEM_ID: SkinEntry(
        name="小型同步剂",
        description="恢复同步上限的 12%。",
        icon="💧",
    ),
    MEDIUM_SPIRIT_MEDICINE_ITEM_ID: SkinEntry(
        name="中型同步剂",
        description="恢复同步上限的 25%。",
        icon="💧",
    ),
    LARGE_SPIRIT_MEDICINE_ITEM_ID: SkinEntry(
        name="大型同步剂",
        description="恢复同步上限的 50%。",
        icon="💧",
    ),
}


__all__ = ["STELLAR_RING_ITEM_ENTRIES"]
