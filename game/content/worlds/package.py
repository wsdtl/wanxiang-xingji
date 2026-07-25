"""官方真实世界身份与地点绑定内容包。"""

from game.core.gameplay import (
    ContentPackage,
    ContentPackageManifest,
    ContentVersion,
    PackageRequirement,
)

from ..catalog import CATALOG_PACKAGE_ID
from ..catalog.enemy import PARTY_BOSS_ENCOUNTER_ID, build_party_boss_encounter
from ..extensions import OFFICIAL_WORLD_EXTENSIONS
from ..world_skins import WORLD_SKIN_PACKAGE_ID


WORLD_PACKAGE_ID = "content.worlds.official"
OFFICIAL_WORLD_BUNDLES = (
    *(value.bundle for value in OFFICIAL_WORLD_EXTENSIONS),
)
PLAYABLE_WORLD_DEFINITIONS = tuple(
    value.world for value in OFFICIAL_WORLD_BUNDLES
)
WORLD_MAP_ANCHORS = tuple(
    anchor
    for bundle in OFFICIAL_WORLD_BUNDLES
    for anchor in bundle.anchors
)
WORLD_LOCATION_BINDINGS = tuple(
    binding
    for bundle in OFFICIAL_WORLD_BUNDLES
    for binding in bundle.bindings
)
WORLD_SPACES = tuple(value.space for value in OFFICIAL_WORLD_EXTENSIONS)
WORLD_PARTY_BOSSES = tuple(
    enemy for value in OFFICIAL_WORLD_EXTENSIONS for enemy in value.party_bosses
)
WORLD_DISASTER_ENEMIES = tuple(
    enemy for value in OFFICIAL_WORLD_EXTENSIONS for enemy in value.disaster_enemies
)
WORLD_PARTY_BOSS_IDS = frozenset(value.id for value in WORLD_PARTY_BOSSES)
WORLD_PACKAGE = ContentPackage(
    manifest=ContentPackageManifest(
        id=WORLD_PACKAGE_ID,
        version=ContentVersion(2, 0, 0),
        dependencies=(
            PackageRequirement(
                package_id=CATALOG_PACKAGE_ID,
                minimum_version=ContentVersion(3, 22, 0),
                maximum_exclusive=ContentVersion(4, 0, 0),
            ),
            PackageRequirement(
                package_id=WORLD_SKIN_PACKAGE_ID,
                minimum_version=ContentVersion(3, 19, 0),
                maximum_exclusive=ContentVersion(4, 0, 0),
            ),
        ),
    ),
    enemies=(*WORLD_PARTY_BOSSES, *WORLD_DISASTER_ENEMIES),
    enemy_encounters=(build_party_boss_encounter(WORLD_PARTY_BOSS_IDS),),
    world_spaces=WORLD_SPACES,
    world_definitions=PLAYABLE_WORLD_DEFINITIONS,
    map_anchors=WORLD_MAP_ANCHORS,
    world_location_bindings=WORLD_LOCATION_BINDINGS,
    display_content_ids=frozenset({PARTY_BOSS_ENCOUNTER_ID}),
    skin_display_content_ids={
        value.skin.id: frozenset(
            {value.space.id, *value.party_boss_source.enemy_ids}
        )
        for value in OFFICIAL_WORLD_EXTENSIONS
    },
)


__all__ = [
    "OFFICIAL_WORLD_BUNDLES",
    "PLAYABLE_WORLD_DEFINITIONS",
    "WORLD_LOCATION_BINDINGS",
    "WORLD_MAP_ANCHORS",
    "WORLD_PACKAGE",
    "WORLD_PACKAGE_ID",
    "WORLD_SPACES",
]
