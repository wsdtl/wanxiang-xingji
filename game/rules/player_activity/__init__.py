"""玩家当前主要活动的统一只读投影。"""

from .projection import (
    PLAYER_ACTIVITY_RULE_VERSION,
    PlayerActivityKind,
    PlayerActivityProjection,
    resolve_player_activity,
)


__all__ = [
    "PLAYER_ACTIVITY_RULE_VERSION",
    "PlayerActivityKind",
    "PlayerActivityProjection",
    "resolve_player_activity",
]
