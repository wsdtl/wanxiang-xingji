"""官方世界皮肤的武器装备展示样式注册表。"""

from game.core.gameplay import StableId

from ..presentation import GearPresentationStyle
from ..extensions import OFFICIAL_EXTENSION_CATALOG


def gear_presentation_style(
    skin_id: StableId,
    version: int,
) -> GearPresentationStyle:
    return OFFICIAL_EXTENSION_CATALOG.gear_presentation(skin_id, version)


def enemy_presentation_style(skin_id: StableId, version: int):
    return OFFICIAL_EXTENSION_CATALOG.enemy_presentation(skin_id, version)


__all__ = ["enemy_presentation_style", "gear_presentation_style"]
