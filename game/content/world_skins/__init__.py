"""世界皮肤公开入口；避免包导入过程维护第二份世界清单。"""

from importlib import import_module


_EXPORT_MODULES = {
    "CULTIVATION_ENEMY_PRESENTATION": "cultivation",
    "CULTIVATION_GEAR_PRESENTATION": "cultivation",
    "CULTIVATION_SKIN": "cultivation",
    "CULTIVATION_SKIN_ID": "cultivation",
    "MAGIC_ENEMY_PRESENTATION": "magic",
    "MAGIC_GEAR_PRESENTATION": "magic",
    "MAGIC_SKIN": "magic",
    "MAGIC_SKIN_ID": "magic",
    "STELLAR_RING_ENEMY_PRESENTATION": "stellar_ring",
    "STELLAR_RING_GEAR_PRESENTATION": "stellar_ring",
    "STELLAR_RING_SKIN": "stellar_ring",
    "STELLAR_RING_SKIN_ID": "stellar_ring",
    "OFFICIAL_SKIN_IDS": "package",
    "WORLD_SKIN_PACKAGE": "package",
    "WORLD_SKIN_PACKAGE_ID": "package",
    "enemy_presentation_style": "presentation",
    "gear_presentation_style": "presentation",
}


def __getattr__(name: str):
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    return getattr(import_module(f"{__name__}.{module_name}"), name)


__all__ = list(_EXPORT_MODULES)
