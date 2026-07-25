"""魔法世界完整扩展描述。"""

from ....catalog.companion import MAGIC_COMPANIONS, MAGIC_PEOPLE
from ....catalog.disaster import MAGIC_DISASTERS
from ....catalog.enemy import MAGIC_PARTY_BOSS_ENEMIES
from ....world_lore.magic import MAGIC_LORE
from ....world_skins.magic import (
    MAGIC_ENEMY_PRESENTATION,
    MAGIC_GEAR_PRESENTATION,
    MAGIC_SKIN,
)
from ....worlds.magic import MAGIC_WORLD_BUNDLE
from .._factory import build_world_extension


WORLD_EXTENSION = build_world_extension(
    order=20,
    bundle=MAGIC_WORLD_BUNDLE,
    skin=MAGIC_SKIN,
    gear_presentation=MAGIC_GEAR_PRESENTATION,
    enemy_presentation=MAGIC_ENEMY_PRESENTATION,
    companion_species=MAGIC_COMPANIONS,
    people=MAGIC_PEOPLE,
    party_bosses=MAGIC_PARTY_BOSS_ENEMIES,
    disasters=MAGIC_DISASTERS,
    lore=MAGIC_LORE,
)


__all__ = ["WORLD_EXTENSION"]
