"""把一个世界自有内容装入统一世界扩展契约。"""

from __future__ import annotations

from game.core.gameplay import ContentVersion

from ...catalog.disaster.combat import build_disaster_enemy_definitions
from ...catalog.enemy.party import PartyBossSourceDefinition
from ..models import WorldExtension


def build_world_extension(
    *,
    version: ContentVersion,
    order: int,
    bundle,
    space,
    skin,
    gear_presentation,
    enemy_presentation,
    companion_species,
    companion_sanctuary,
    people,
    enemy_behavior_profile,
    party_bosses,
    disasters,
    lore,
    content_extensions=(),
) -> WorldExtension:
    world_id = bundle.world.id
    party_values = tuple(party_bosses)
    disaster_values = tuple(disasters)
    return WorldExtension(
        id=world_id,
        version=version,
        order=order,
        space=space,
        bundle=bundle,
        skin=skin,
        gear_presentation=gear_presentation,
        enemy_presentation=enemy_presentation,
        companion_species=tuple(companion_species),
        companion_sanctuary=companion_sanctuary,
        people=tuple(people),
        enemy_behavior_profile=enemy_behavior_profile,
        party_bosses=party_values,
        party_boss_source=PartyBossSourceDefinition(
            world_id,
            frozenset(value.id for value in party_values),
        ),
        party_boss_trophy_item_ids={
            value.id: f"item.trophy.party_boss.{value.id.removeprefix('enemy.boss.party.')}"
            for value in party_values
        },
        disasters=disaster_values,
        disaster_enemies=build_disaster_enemy_definitions(disaster_values),
        lore=lore,
        content_extensions=tuple(content_extensions),
    )


__all__ = ["build_world_extension"]
