"""不随世界同化的公共展示与恒定物品约束。"""

from game.core.gameplay import SkinEntry

from .catalog.item.exchange import EXCHANGE_MATERIAL_ITEM_ID
from .catalog.item.special import INSCRIPTION_FEATHER_ITEM_ID


WORLD_INVARIANT_ITEM_IDS = frozenset(
    {
        EXCHANGE_MATERIAL_ITEM_ID,
        INSCRIPTION_FEATHER_ITEM_ID,
    }
)


COVENANT_ITEM_ENTRIES = {
    EXCHANGE_MATERIAL_ITEM_ID: SkinEntry(
        name="定相尘",
        description="归航公约注销组队首领遗物后留下的稳定兑换材料。",
        icon="◆",
    ),
}


__all__ = ["COVENANT_ITEM_ENTRIES", "WORLD_INVARIANT_ITEM_IDS"]
