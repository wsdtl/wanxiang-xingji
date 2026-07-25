"""汇总官方世界展示皮肤，不声明玩法世界。"""

from game.core.gameplay import (
    ContentPackage,
    ContentPackageManifest,
    ContentVersion,
    PackageRequirement,
)

from ..catalog import CATALOG_PACKAGE_ID
from ..extensions import OFFICIAL_WORLD_EXTENSIONS


WORLD_SKIN_PACKAGE_ID = "content.world_skins.official"
OFFICIAL_SKIN_IDS = tuple(value.skin.id for value in OFFICIAL_WORLD_EXTENSIONS)


WORLD_SKIN_PACKAGE = ContentPackage(
    manifest=ContentPackageManifest(
        id=WORLD_SKIN_PACKAGE_ID,
        version=ContentVersion(3, 21, 0),
        dependencies=(
            PackageRequirement(
                package_id=CATALOG_PACKAGE_ID,
                minimum_version=ContentVersion(3, 26, 0),
                maximum_exclusive=ContentVersion(4, 0, 0),
            ),
        ),
    ),
    skin_packs=tuple(value.skin for value in OFFICIAL_WORLD_EXTENSIONS),
)


__all__ = [
    "OFFICIAL_SKIN_IDS",
    "WORLD_SKIN_PACKAGE",
    "WORLD_SKIN_PACKAGE_ID",
]
