"""太玄界的消耗品展示。"""

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


CULTIVATION_ITEM_ENTRIES = {
    **COVENANT_ITEM_ENTRIES,
    BREAKTHROUGH_TOKEN_ITEM_ID: SkinEntry(
        name="问道玉契",
        description="承载破境所需的一缕道机；达到境界关隘后由突破流程自动消耗。",
        icon="📜",
    ),
    DRAW_TICKET_ITEM_ID: SkinEntry(
        name="流光签",
        description="封存一缕尚未定形的战斗余响；投入界门后会显化为一次确定收获。",
        icon="🎟️",
    ),
    INSCRIPTION_FEATHER_ITEM_ID: SkinEntry(
        name="铭刻之羽",
        description="承载一段不可复刻的旧愿，可为武器、装备或武器能力留下私名。",
        icon="📜",
    ),
    BACKPACK_CAPACITY_ITEM_ID: SkinEntry(
        name="芥子神砂",
        description=(
            f"炼入背包后永久增加 {BACKPACK_CAPACITY_INCREMENT} 格空间；"
            f"背包最多扩展至 {BACKPACK_CAPACITY_MAXIMUM} 格。"
        ),
        icon="⌛",
    ),
    COMPANION_SANCTUARY_ITEM_ID: SkinEntry(
        name="万灵引",
        description="在当前世界引动一次宠物秘境；名册空间不足时不会消耗。",
        icon="🧿",
    ),
    DIMENSION_SHIFT_ITEM_ID: SkinEntry(
        name="渡界玉符",
        description="登录另一世界时自动消耗一枚；查看界门或跃迁失败不会消耗。",
        icon="🧿",
    ),
    WEAPON_MAXIMUM_LEVEL_ITEM_ID: SkinEntry(
        name="淬锋丹",
        description="为一把未臻极限的武器淬炼根基，使其等级上限提升 1 级，最高 100 级。",
        icon="⚗️",
    ),
    CHARACTER_EXPERIENCE_ITEM_ID: SkinEntry(
        name="悟道玉简",
        description="为角色补充人物经验，单次最多增加 1,000,000 点。",
        icon="📖",
    ),
    WEAPON_EXPERIENCE_ITEM_ID: SkinEntry(
        name="岁华玉髓",
        description="为指定武器补充成长经验，单次最多增加 40,000 点，无法超过武器等级上限。",
        icon="💠",
    ),
    COMPANION_EXPERIENCE_ITEM_ID: SkinEntry(
        name="同契灵简",
        description="为指定伙伴补充成长经验，单次最多增加 30,000 点。",
        icon="💠",
    ),
    SMALL_HEALTH_MEDICINE_ABILITY_ID: SkinEntry(
        name="服用小还丹",
        description="恢复自身气血上限的 12%。",
    ),
    MEDIUM_HEALTH_MEDICINE_ABILITY_ID: SkinEntry(
        name="服用中还丹",
        description="恢复自身气血上限的 25%。",
    ),
    LARGE_HEALTH_MEDICINE_ABILITY_ID: SkinEntry(
        name="服用大还丹",
        description="恢复自身气血上限的 50%。",
    ),
    SMALL_SPIRIT_MEDICINE_ABILITY_ID: SkinEntry(
        name="服用小回灵丹",
        description="恢复自身灵力上限的 12%。",
    ),
    MEDIUM_SPIRIT_MEDICINE_ABILITY_ID: SkinEntry(
        name="服用中回灵丹",
        description="恢复自身灵力上限的 25%。",
    ),
    LARGE_SPIRIT_MEDICINE_ABILITY_ID: SkinEntry(
        name="服用大回灵丹",
        description="恢复自身灵力上限的 50%。",
    ),
    SMALL_HEALTH_MEDICINE_ITEM_ID: SkinEntry(
        name="小还丹",
        description="恢复气血上限的 12%。",
        icon="💊",
    ),
    MEDIUM_HEALTH_MEDICINE_ITEM_ID: SkinEntry(
        name="中还丹",
        description="恢复气血上限的 25%。",
        icon="💊",
    ),
    LARGE_HEALTH_MEDICINE_ITEM_ID: SkinEntry(
        name="大还丹",
        description="恢复气血上限的 50%。",
        icon="💊",
    ),
    SMALL_SPIRIT_MEDICINE_ITEM_ID: SkinEntry(
        name="小回灵丹",
        description="恢复灵力上限的 12%。",
        icon="💧",
    ),
    MEDIUM_SPIRIT_MEDICINE_ITEM_ID: SkinEntry(
        name="中回灵丹",
        description="恢复灵力上限的 25%。",
        icon="💧",
    ),
    LARGE_SPIRIT_MEDICINE_ITEM_ID: SkinEntry(
        name="大回灵丹",
        description="恢复灵力上限的 50%。",
        icon="💧",
    ),
}


__all__ = ["CULTIVATION_ITEM_ENTRIES"]
