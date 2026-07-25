"""魔法世界真实世界身份与地点功能绑定。"""

from game.core.gameplay import WorldDefinition, WorldLocationBinding

from ..catalog.companion import MAGIC_PEOPLE
from ..catalog.exploration import EXPLORATION_REGIONS
from ..catalog.world import (
    LOCATION_FUNCTION_CITY,
    LOCATION_FUNCTION_COMPANION_PERSON,
    LOCATION_FUNCTION_EXPLORATION,
    MAGIC_WORLD_ID,
    MAGIC_WORLD_SPACE_ID,
    STARTING_CITY_ID,
)
from ..world_skins import MAGIC_SKIN_ID
from .layouts import MAGIC_LAYOUT
from .models import OfficialWorldBundle


MAGIC_WORLD = WorldDefinition(
    MAGIC_WORLD_ID,
    MAGIC_WORLD_SPACE_ID,
    MAGIC_SKIN_ID,
    MAGIC_LAYOUT[STARTING_CITY_ID].id,
)
MAGIC_LOCATION_BINDINGS = (
    WorldLocationBinding(
        MAGIC_WORLD_ID,
        MAGIC_LAYOUT[STARTING_CITY_ID].id,
        LOCATION_FUNCTION_CITY,
        display_ref=STARTING_CITY_ID,
    ),
    *(
        WorldLocationBinding(
            MAGIC_WORLD_ID,
            MAGIC_LAYOUT[value.location_id].id,
            LOCATION_FUNCTION_EXPLORATION,
            value.id,
            display_ref=value.location_id,
        )
        for value in EXPLORATION_REGIONS
    ),
    *(
        WorldLocationBinding(
            MAGIC_WORLD_ID,
            MAGIC_LAYOUT[value.location_id].id,
            LOCATION_FUNCTION_COMPANION_PERSON,
            value.id,
            display_ref=value.location_id,
        )
        for value in MAGIC_PEOPLE
    ),
)
MAGIC_WORLD_BUNDLE = OfficialWorldBundle(
    MAGIC_WORLD,
    tuple(MAGIC_LAYOUT.values()),
    MAGIC_LOCATION_BINDINGS,
)


__all__ = [
    "MAGIC_LOCATION_BINDINGS",
    "MAGIC_WORLD",
    "MAGIC_WORLD_BUNDLE",
]
