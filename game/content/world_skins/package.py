"""汇总官方世界展示皮肤，不声明玩法世界。"""

from game.core.gameplay import (
    ContentPackage,
    ContentPackageManifest,
    ContentVersion,
    PackageRequirement,
)

from ..catalog import CATALOG_PACKAGE, CATALOG_PACKAGE_ID
from ..covenant import WORLD_INVARIANT_ITEM_IDS
from ..extensions import OFFICIAL_WORLD_EXTENSIONS
from .validation import validate_distinct_item_skin_names


WORLD_SKIN_PACKAGE_ID = "content.world_skins.official"
OFFICIAL_SKIN_PACKS = tuple(value.skin for value in OFFICIAL_WORLD_EXTENSIONS)
OFFICIAL_SKIN_IDS = tuple(value.id for value in OFFICIAL_SKIN_PACKS)


validate_distinct_item_skin_names(
    OFFICIAL_SKIN_PACKS,
    (definition.id for definition in CATALOG_PACKAGE.items),
    invariant_item_ids=WORLD_INVARIANT_ITEM_IDS,
)


WORLD_SKIN_PACKAGE = ContentPackage(
    manifest=ContentPackageManifest(
        id=WORLD_SKIN_PACKAGE_ID,
        version=ContentVersion(3, 24, 0),
        dependencies=(
            PackageRequirement(
                package_id=CATALOG_PACKAGE_ID,
                minimum_version=ContentVersion(3, 26, 0),
                maximum_exclusive=ContentVersion(4, 0, 0),
            ),
        ),
    ),
    skin_packs=OFFICIAL_SKIN_PACKS,
)


__all__ = [
    "OFFICIAL_SKIN_IDS",
    "WORLD_SKIN_PACKAGE",
    "WORLD_SKIN_PACKAGE_ID",
]
