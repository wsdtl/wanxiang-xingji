"""正式内容的跨世界展示组合工具。"""

from .branding import (
    COVENANT_MARKET_NAME,
    COVENANT_MEMBER_NAME,
    COVENANT_NAME,
    COVENANT_RECYCLING_NAME,
    COVENANT_TREASURY_NAME,
    GAME_NAME,
    GAME_TAGLINE,
    GAME_TITLE,
)
from .gear import GearDisplay, GearPresentationStyle, GearProjector
from .enemy import EnemyDisplay, EnemyNameProjector, EnemyPresentationStyle
from .mechanics import (
    MechanicCatalogEntry,
    MechanicDetail,
    MechanicPresentationError,
    MechanicProjector,
    MechanicTierDetail,
)


__all__ = [
    "EnemyDisplay",
    "EnemyNameProjector",
    "EnemyPresentationStyle",
    "GearDisplay",
    "GearPresentationStyle",
    "GearProjector",
    "MechanicCatalogEntry",
    "MechanicDetail",
    "MechanicPresentationError",
    "MechanicProjector",
    "MechanicTierDetail",
    "COVENANT_MARKET_NAME",
    "COVENANT_MEMBER_NAME",
    "COVENANT_NAME",
    "COVENANT_RECYCLING_NAME",
    "COVENANT_TREASURY_NAME",
    "GAME_NAME",
    "GAME_TAGLINE",
    "GAME_TITLE",
]
