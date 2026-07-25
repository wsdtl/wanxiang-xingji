"""官方内容扩展的唯一发现与冻结入口。"""

from .catalog import (
    COMPOSITION_PACKAGE_ID,
    ExtensionCatalog,
    PARTY_ENCOUNTER_PACKAGE_ID,
)
from .discovery import discover_extension_catalog
from .models import ContentExtension, WorldExtension


OFFICIAL_EXTENSION_CATALOG = discover_extension_catalog()
OFFICIAL_WORLD_EXTENSIONS = OFFICIAL_EXTENSION_CATALOG.worlds


__all__ = [
    "ContentExtension",
    "COMPOSITION_PACKAGE_ID",
    "ExtensionCatalog",
    "OFFICIAL_EXTENSION_CATALOG",
    "OFFICIAL_WORLD_EXTENSIONS",
    "PARTY_ENCOUNTER_PACKAGE_ID",
    "WorldExtension",
    "discover_extension_catalog",
]
