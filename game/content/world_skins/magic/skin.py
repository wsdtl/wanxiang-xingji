"""魔法世界世界皮肤的唯一组装入口。"""

from game.core.gameplay import SkinPack

from .base import MAGIC_BASE_ENTRIES
from .character import MAGIC_CHARACTER_ENTRIES
from .combat import MAGIC_COMBAT_ENTRIES
from .companions import MAGIC_COMPANION_ENTRIES
from .equipment import MAGIC_EQUIPMENT_ENTRIES
from .enemies import MAGIC_ENEMY_ENTRIES
from .items import MAGIC_ITEM_ENTRIES
from .trophies import MAGIC_TROPHY_ENTRIES
from .weapons import MAGIC_WEAPON_ENTRIES
from .world import MAGIC_WORLD_ENTRIES


MAGIC_SKIN_ID = "skin.magic"
MAGIC_SKIN_VERSION = 28


MAGIC_SKIN = SkinPack(
    id=MAGIC_SKIN_ID,
    version=MAGIC_SKIN_VERSION,
    name="魔法世界",
    icon="✦",
    entries={
        **MAGIC_BASE_ENTRIES,
        **MAGIC_CHARACTER_ENTRIES,
        **MAGIC_COMBAT_ENTRIES,
        **MAGIC_COMPANION_ENTRIES,
        **MAGIC_EQUIPMENT_ENTRIES,
        **MAGIC_ENEMY_ENTRIES,
        **MAGIC_ITEM_ENTRIES,
        **MAGIC_TROPHY_ENTRIES,
        **MAGIC_WEAPON_ENTRIES,
        **MAGIC_WORLD_ENTRIES,
    },
)


__all__ = ["MAGIC_SKIN", "MAGIC_SKIN_ID", "MAGIC_SKIN_VERSION"]
