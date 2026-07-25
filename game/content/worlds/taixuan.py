"""太玄界真实世界身份与地点功能绑定。"""

from game.core.gameplay import WorldDefinition, WorldLocationBinding

from ..catalog.companion import CULTIVATION_PEOPLE
from ..catalog.exploration import EXPLORATION_REGIONS
from ..catalog.world import (
    LOCATION_FUNCTION_CITY,
    LOCATION_FUNCTION_COMPANION_PERSON,
    LOCATION_FUNCTION_EXPLORATION,
    STARTING_CITY_ID,
    TAIXUAN_WORLD_ID,
    TAIXUAN_WORLD_SPACE_ID,
)
from ..world_skins import CULTIVATION_SKIN_ID
from .layouts import TAIXUAN_LAYOUT
from .models import OfficialWorldBundle


TAIXUAN_WORLD = WorldDefinition(
    TAIXUAN_WORLD_ID,
    TAIXUAN_WORLD_SPACE_ID,
    CULTIVATION_SKIN_ID,
    TAIXUAN_LAYOUT[STARTING_CITY_ID].id,
)
TAIXUAN_LOCATION_BINDINGS = (
    WorldLocationBinding(
        TAIXUAN_WORLD_ID,
        TAIXUAN_LAYOUT[STARTING_CITY_ID].id,
        LOCATION_FUNCTION_CITY,
        display_ref=STARTING_CITY_ID,
    ),
    *(
        WorldLocationBinding(
            TAIXUAN_WORLD_ID,
            TAIXUAN_LAYOUT[value.location_id].id,
            LOCATION_FUNCTION_EXPLORATION,
            value.id,
            display_ref=value.location_id,
        )
        for value in EXPLORATION_REGIONS
    ),
    *(
        WorldLocationBinding(
            TAIXUAN_WORLD_ID,
            TAIXUAN_LAYOUT[value.location_id].id,
            LOCATION_FUNCTION_COMPANION_PERSON,
            value.id,
            display_ref=value.location_id,
        )
        for value in CULTIVATION_PEOPLE
    ),
)
TAIXUAN_WORLD_BUNDLE = OfficialWorldBundle(
    TAIXUAN_WORLD,
    tuple(TAIXUAN_LAYOUT.values()),
    TAIXUAN_LOCATION_BINDINGS,
)


__all__ = [
    "TAIXUAN_LOCATION_BINDINGS",
    "TAIXUAN_WORLD",
    "TAIXUAN_WORLD_BUNDLE",
]
