"""星环界完整扩展描述。"""

from ....catalog.companion import STELLAR_RING_COMPANIONS, STELLAR_RING_PEOPLE
from ....catalog.disaster import STELLAR_RING_DISASTERS
from ....catalog.enemy import STELLAR_RING_PARTY_BOSS_ENEMIES
from ....world_lore.stellar_ring import STELLAR_RING_LORE
from ....world_skins.stellar_ring import (
    STELLAR_RING_ENEMY_PRESENTATION,
    STELLAR_RING_GEAR_PRESENTATION,
    STELLAR_RING_SKIN,
)
from ....worlds.stellar_ring import STELLAR_RING_WORLD_BUNDLE
from .._factory import build_world_extension


WORLD_EXTENSION = build_world_extension(
    order=30,
    bundle=STELLAR_RING_WORLD_BUNDLE,
    skin=STELLAR_RING_SKIN,
    gear_presentation=STELLAR_RING_GEAR_PRESENTATION,
    enemy_presentation=STELLAR_RING_ENEMY_PRESENTATION,
    companion_species=STELLAR_RING_COMPANIONS,
    people=STELLAR_RING_PEOPLE,
    party_bosses=STELLAR_RING_PARTY_BOSS_ENEMIES,
    disasters=STELLAR_RING_DISASTERS,
    lore=STELLAR_RING_LORE,
)


__all__ = ["WORLD_EXTENSION"]
