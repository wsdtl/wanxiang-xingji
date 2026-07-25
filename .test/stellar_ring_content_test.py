"""星环界真实世界、完整投影与专属内容验收。"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.content import (  # noqa: E402
    COMPANION_CATALOG,
    STELLAR_RING_SKIN_ID,
    STELLAR_RING_WORLD_ID,
    STELLAR_RING_WORLD_SPACE_ID,
    build_dimensional_disaster_catalog,
    build_world_view_catalog,
)
from game.content.catalog.enemy import PARTY_BOSS_SOURCE_CATALOG  # noqa: E402


def main() -> None:
    views = build_world_view_catalog()
    stellar = views.require(STELLAR_RING_WORLD_ID)
    assert stellar.skin.id == STELLAR_RING_SKIN_ID
    assert stellar.skin.name == "星环界"
    assert stellar.world.space_id == STELLAR_RING_WORLD_SPACE_ID
    stellar.skin.validate(stellar.catalog.report.display_content_ids)

    bindings = views.worlds.bindings_for_world(STELLAR_RING_WORLD_ID)
    assert len(bindings) == 17
    exploration_bindings = views.worlds.bindings_for_world(
        STELLAR_RING_WORLD_ID,
        function_id="location.function.exploration",
    )
    assert len(exploration_bindings) == 13
    assert all(
        stellar.exploration_regions.require(value.content_ref)
        for value in exploration_bindings
    )

    person_bindings = views.worlds.bindings_for_world(
        STELLAR_RING_WORLD_ID,
        function_id="location.function.companion_person",
    )
    people = COMPANION_CATALOG.people_for_world(STELLAR_RING_WORLD_ID)
    assert len(person_bindings) == len(people) == 3
    assert {value.content_ref for value in person_bindings} == {
        value.id for value in people
    }
    sanctuary = COMPANION_CATALOG.require_sanctuary(STELLAR_RING_WORLD_ID)
    assert len(sanctuary.species_ids) == 8
    assert all(
        COMPANION_CATALOG.species.require(value).origin_world_id
        == STELLAR_RING_WORLD_ID
        for value in sanctuary.species_ids
    )

    party_source = PARTY_BOSS_SOURCE_CATALOG.require(STELLAR_RING_WORLD_ID)
    assert len(party_source.enemy_ids) == 10
    assert all(
        stellar.catalog.enemies.require(value).tags.has("enemy.identity.party_boss")
        for value in party_source.enemy_ids
    )
    disasters = build_dimensional_disaster_catalog()
    source_disasters = disasters.for_source(STELLAR_RING_WORLD_ID)
    assert len(source_disasters) == 10
    source_audit = next(
        value for value in disasters.audit().sources
        if value.source_world_id == STELLAR_RING_WORLD_ID
    )
    assert source_audit.documented == 7 and source_audit.original == 3

    forbidden = ("魔法世界", "幻兽庭", "魔力", "魔能评分")
    for entry in stellar.skin.entries.values():
        visible = " ".join(
            value for value in (entry.name, entry.compact_name, entry.description)
            if value
        )
        assert not any(value in visible for value in forbidden)

    print("stellar ring content tests passed")


if __name__ == "__main__":
    main()
