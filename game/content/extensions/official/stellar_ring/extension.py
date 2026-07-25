"""星环界完整扩展描述。"""

from .._factory import build_world_extension
from .companions import PEOPLE, SANCTUARY, SPECIES
from .disasters import DISASTERS
from .enemies import BEHAVIOR_PROFILE, PARTY_BOSSES
from .lore import LORE
from .skin import ENEMY_PRESENTATION, GEAR_PRESENTATION, SKIN
from .world import BUNDLE, SPACE


WORLD_EXTENSION = build_world_extension(
    order=30,
    bundle=BUNDLE,
    space=SPACE,
    skin=SKIN,
    gear_presentation=GEAR_PRESENTATION,
    enemy_presentation=ENEMY_PRESENTATION,
    companion_species=SPECIES,
    companion_sanctuary=SANCTUARY,
    people=PEOPLE,
    enemy_behavior_profile=BEHAVIOR_PROFILE,
    party_bosses=PARTY_BOSSES,
    disasters=DISASTERS,
    lore=LORE,
)


__all__ = ["WORLD_EXTENSION"]
