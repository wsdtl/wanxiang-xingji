"""正式世界公开入口；聚合结果延迟到扩展发现完成后读取。"""

from importlib import import_module

from .models import OfficialWorldBundle


_PACKAGE_EXPORTS = {
    "OFFICIAL_WORLD_BUNDLES",
    "PLAYABLE_WORLD_DEFINITIONS",
    "WORLD_LOCATION_BINDINGS",
    "WORLD_MAP_ANCHORS",
    "WORLD_PACKAGE",
    "WORLD_PACKAGE_ID",
}


def __getattr__(name: str):
    if name in _PACKAGE_EXPORTS:
        return getattr(import_module(f"{__name__}.package"), name)
    raise AttributeError(name)


__all__ = ["OfficialWorldBundle", *_PACKAGE_EXPORTS]
