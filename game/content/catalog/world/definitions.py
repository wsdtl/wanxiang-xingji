"""真实世界空间、共享地点身份与坐标编码规则。"""

import re

from game.core.gameplay import (
    ContentDefinition,
    MapAnchorDefinition,
    WorldSpaceDefinition,
    WorldTopologyKind,
)


TAIXUAN_WORLD_ID = "world.taixuan"
MAGIC_WORLD_ID = "world.magic"
STELLAR_RING_WORLD_ID = "world.stellar_ring"

TAIXUAN_WORLD_SPACE_ID = "world_space.taixuan"
MAGIC_WORLD_SPACE_ID = "world_space.magic"
STELLAR_RING_WORLD_SPACE_ID = "world_space.stellar_ring"
CHARACTER_PRESENCE_KIND_ID = "presence.character"

LOCATION_FUNCTION_CITY = "location.function.city"
LOCATION_FUNCTION_EXPLORATION = "location.function.exploration"
LOCATION_FUNCTION_COMPANION_PERSON = "location.function.companion_person"

STARTING_CITY_ID = "location.main_city"
PERSON_WEST_LOCATION_ID = "location.person_01"
PERSON_EAST_LOCATION_ID = "location.person_02"
PERSON_NORTH_LOCATION_ID = "location.person_03"

GREEN_CLOUD_PLAIN_ID = "location.exploration_r01"
SUNSET_RIDGE_ID = "location.exploration_r02"
BLACK_WIND_RAVINE_ID = "location.exploration_r03"
MIRROR_LAKE_MARSH_ID = "location.exploration_r04"
SCARLET_FLAME_VALLEY_ID = "location.exploration_r05"
VERDANT_WILDERNESS_ID = "location.exploration_r06"
THUNDER_MARSH_STEPPE_ID = "location.exploration_r07"
NORTHERN_ABYSS_SNOWFIELD_ID = "location.exploration_r08"
BROKEN_PILLAR_RELIC_ID = "location.exploration_r09"
KUNLUN_SKY_RUINS_ID = "location.exploration_r10"
MYRIAD_SWORD_TOMB_ID = "location.exploration_weapon_focus"
HEAVENLY_CRAFT_RELIC_ID = "location.exploration_equipment_focus"
RETURNING_RUIN_ABYSS_ID = "location.exploration_boss_focus"


def world_space_definition(space_id: str) -> WorldSpaceDefinition:
    return WorldSpaceDefinition(
        space_id,
        WorldTopologyKind.GRID,
        minimum_x=-100,
        maximum_x=100,
        minimum_y=-100,
        maximum_y=100,
    )


WORLD_SPACES = (
    world_space_definition(TAIXUAN_WORLD_SPACE_ID),
    world_space_definition(MAGIC_WORLD_SPACE_ID),
    world_space_definition(STELLAR_RING_WORLD_SPACE_ID),
)

TAIXUAN_WORLD_SPACE, MAGIC_WORLD_SPACE, STELLAR_RING_WORLD_SPACE = WORLD_SPACES


EXPLORATION_LOCATION_IDS = (
    GREEN_CLOUD_PLAIN_ID,
    SUNSET_RIDGE_ID,
    BLACK_WIND_RAVINE_ID,
    MIRROR_LAKE_MARSH_ID,
    SCARLET_FLAME_VALLEY_ID,
    VERDANT_WILDERNESS_ID,
    THUNDER_MARSH_STEPPE_ID,
    NORTHERN_ABYSS_SNOWFIELD_ID,
    BROKEN_PILLAR_RELIC_ID,
    KUNLUN_SKY_RUINS_ID,
    MYRIAD_SWORD_TOMB_ID,
    HEAVENLY_CRAFT_RELIC_ID,
    RETURNING_RUIN_ABYSS_ID,
)
PERSON_LOCATION_IDS = (
    PERSON_WEST_LOCATION_ID,
    PERSON_EAST_LOCATION_ID,
    PERSON_NORTH_LOCATION_ID,
)
LOCATION_DISPLAY_IDS = (
    STARTING_CITY_ID,
    *EXPLORATION_LOCATION_IDS,
    *PERSON_LOCATION_IDS,
)
LOCATION_DISPLAY_DEFINITIONS = tuple(
    ContentDefinition(value, "content_kind.location_display")
    for value in LOCATION_DISPLAY_IDS
)


WORLD_DISPLAY_CONTENT_IDS = frozenset(
    {
        TAIXUAN_WORLD_SPACE_ID,
        MAGIC_WORLD_SPACE_ID,
        STELLAR_RING_WORLD_SPACE_ID,
        *LOCATION_DISPLAY_IDS,
    }
)
WORLD_SPACE_DISPLAY_IDS = frozenset(
    {TAIXUAN_WORLD_SPACE_ID, MAGIC_WORLD_SPACE_ID, STELLAR_RING_WORLD_SPACE_ID}
)
SHARED_WORLD_DISPLAY_CONTENT_IDS = frozenset(LOCATION_DISPLAY_IDS)
_COORDINATE_SUFFIX = re.compile(
    r"_x(0|p[1-9][0-9]*|n[1-9][0-9]*)_y(0|p[1-9][0-9]*|n[1-9][0-9]*)$"
)


def coordinate_token(value: int) -> str:
    """把整数坐标编码为稳定 ID 后缀，不参与运行期坐标计算。"""

    if value == 0:
        return "0"
    return f"p{value}" if value > 0 else f"n{abs(value)}"


def validate_anchor_coordinate_id(definition: MapAnchorDefinition) -> None:
    """正式锚点装配时校验 ID 后缀与真实坐标一致。"""

    match = _COORDINATE_SUFFIX.search(definition.id)
    expected = f"_x{coordinate_token(definition.x)}_y{coordinate_token(definition.y)}"
    if match is None or match.group(0) != expected:
        raise ValueError(f"锚点 ID 坐标后缀与实际坐标不一致：{definition.id} != {expected}")


__all__ = [name for name in globals() if not name.startswith("_")]
