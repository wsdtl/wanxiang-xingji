"""把现有世界内容分区装入统一世界扩展契约。"""

from __future__ import annotations

from game.core.gameplay import ContentVersion

from ...catalog.companion import COMPANION_CATALOG
from ...catalog.disaster.combat import DISASTER_ENEMY_DEFINITIONS
from ...catalog.enemy import (
    ENEMY_BEHAVIOR_PROFILE_CATALOG,
    PARTY_BOSS_SOURCE_CATALOG,
)
from ...catalog.item import PARTY_BOSS_TROPHY_ITEM_IDS
from ...catalog.world import WORLD_SPACES
from ..models import WorldExtension


def build_world_extension(
    *,
    order: int,
    bundle,
    skin,
    gear_presentation,
    enemy_presentation,
    companion_species,
    people,
    party_bosses,
    disasters,
    lore,
) -> WorldExtension:
    world_id = bundle.world.id
    disaster_ids = {value.enemy_definition_id for value in disasters}
    return WorldExtension(
        id=world_id,
        version=ContentVersion(1, 0, 0),
        order=order,
        space=next(
            value for value in WORLD_SPACES if value.id == bundle.world.space_id
        ),
        bundle=bundle,
        skin=skin,
        gear_presentation=gear_presentation,
        enemy_presentation=enemy_presentation,
        companion_species=tuple(companion_species),
        companion_sanctuary=COMPANION_CATALOG.require_sanctuary(world_id),
        people=tuple(people),
        enemy_behavior_profile=ENEMY_BEHAVIOR_PROFILE_CATALOG.require(world_id),
        party_bosses=tuple(party_bosses),
        party_boss_source=PARTY_BOSS_SOURCE_CATALOG.require(world_id),
        party_boss_trophy_item_ids={
            value.id: PARTY_BOSS_TROPHY_ITEM_IDS[value.id]
            for value in party_bosses
        },
        disasters=tuple(disasters),
        disaster_enemies=tuple(
            value
            for value in DISASTER_ENEMY_DEFINITIONS
            if value.id in disaster_ids
        ),
        lore=lore,
    )


__all__ = ["build_world_extension"]
