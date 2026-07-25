"""世界志公开入口；正式目录由世界扩展统一派生。"""

from importlib import import_module

from .models import WorldLoreCatalog, WorldLoreDefinition, WorldLoreRecord


def __getattr__(name: str):
    if name == "WORLD_LORE_CATALOG":
        return getattr(import_module(f"{__name__}.package"), name)
    raise AttributeError(name)


__all__ = [
    "WORLD_LORE_CATALOG",
    "WorldLoreCatalog",
    "WorldLoreDefinition",
    "WorldLoreRecord",
]
