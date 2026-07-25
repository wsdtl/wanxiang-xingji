"""太玄界完整扩展描述。"""

from ....catalog.companion import CULTIVATION_COMPANIONS, CULTIVATION_PEOPLE
from ....catalog.disaster import CULTIVATION_DISASTERS
from ....catalog.enemy import CULTIVATION_PARTY_BOSS_ENEMIES
from ....world_lore.taixuan import TAIXUAN_LORE
from ....world_skins.cultivation import (
    CULTIVATION_ENEMY_PRESENTATION,
    CULTIVATION_GEAR_PRESENTATION,
    CULTIVATION_SKIN,
)
from ....worlds.taixuan import TAIXUAN_WORLD_BUNDLE
from .._factory import build_world_extension


WORLD_EXTENSION = build_world_extension(
    order=10,
    bundle=TAIXUAN_WORLD_BUNDLE,
    skin=CULTIVATION_SKIN,
    gear_presentation=CULTIVATION_GEAR_PRESENTATION,
    enemy_presentation=CULTIVATION_ENEMY_PRESENTATION,
    companion_species=CULTIVATION_COMPANIONS,
    people=CULTIVATION_PEOPLE,
    party_bosses=CULTIVATION_PARTY_BOSS_ENEMIES,
    disasters=CULTIVATION_DISASTERS,
    lore=TAIXUAN_LORE,
)


__all__ = ["WORLD_EXTENSION"]
