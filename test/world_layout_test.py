"""三个正式世界的独立地图布局与地点映射验收。"""

from collections import Counter
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.content import (  # noqa: E402
    MAGIC_WORLD_ID,
    STELLAR_RING_WORLD_ID,
    TAIXUAN_WORLD_ID,
    PLAYABLE_WORLD_IDS,
    build_world_view_catalog,
)
from game.content.catalog.world import (  # noqa: E402
    GREEN_CLOUD_PLAIN_ID,
    LOCATION_FUNCTION_CITY,
    LOCATION_FUNCTION_COMPANION_PERSON,
    LOCATION_FUNCTION_EXPLORATION,
    PERSON_EAST_LOCATION_ID,
    PERSON_NORTH_LOCATION_ID,
    PERSON_WEST_LOCATION_ID,
)
from game.content.worlds import (  # noqa: E402
    OFFICIAL_WORLD_BUNDLES,
    PLAYABLE_WORLD_DEFINITIONS,
    WORLD_LOCATION_BINDINGS,
    WORLD_MAP_ANCHORS,
)


def main() -> None:
    _assert_official_world_bundles()
    worlds = build_world_view_catalog().worlds
    layouts = {
        world_id: {
            binding.display_ref: (
                worlds.require_anchor(binding.anchor_id).x,
                worlds.require_anchor(binding.anchor_id).y,
            )
            for binding in worlds.bindings_for_world(world_id)
        }
        for world_id in (TAIXUAN_WORLD_ID, MAGIC_WORLD_ID, STELLAR_RING_WORLD_ID)
    }

    assert all(len(layout) == 17 for layout in layouts.values())
    assert len(
        {
            binding.anchor_id
            for world_id in layouts
            for binding in worlds.bindings_for_world(world_id)
        }
    ) == 51

    first_region_positions = {
        layout[GREEN_CLOUD_PLAIN_ID]
        for layout in layouts.values()
    }
    assert len(first_region_positions) == 3

    stellar = layouts[STELLAR_RING_WORLD_ID]
    inner_ring = {
        (0, 24),
        (17, 17),
        (24, 0),
        (17, -17),
        (0, -24),
        (-17, -17),
        (-24, 0),
        (-17, 17),
    }
    assert inner_ring <= set(stellar.values())
    assert {
        stellar[PERSON_WEST_LOCATION_ID],
        stellar[PERSON_EAST_LOCATION_ID],
        stellar[PERSON_NORTH_LOCATION_ID],
    } == {(-12, 36), (0, 36), (12, 36)}

    for display_id in layouts[TAIXUAN_WORLD_ID]:
        for world_id in layouts:
            binding = worlds.require_binding_for_display(world_id, display_id)
            resolved = worlds.resolve(world_id, binding.anchor_id)
            assert resolved.display_id == display_id
            assert (resolved.position.x, resolved.position.y) == layouts[world_id][display_id]

    print("world layout tests passed")


def _assert_official_world_bundles() -> None:
    assert tuple(bundle.world.id for bundle in OFFICIAL_WORLD_BUNDLES) == (
        PLAYABLE_WORLD_IDS
    )
    assert tuple(bundle.world for bundle in OFFICIAL_WORLD_BUNDLES) == (
        PLAYABLE_WORLD_DEFINITIONS
    )
    assert tuple(
        anchor
        for bundle in OFFICIAL_WORLD_BUNDLES
        for anchor in bundle.anchors
    ) == WORLD_MAP_ANCHORS
    assert tuple(
        binding
        for bundle in OFFICIAL_WORLD_BUNDLES
        for binding in bundle.bindings
    ) == WORLD_LOCATION_BINDINGS

    expected_function_counts = Counter(
        {
            LOCATION_FUNCTION_CITY: 1,
            LOCATION_FUNCTION_EXPLORATION: 13,
            LOCATION_FUNCTION_COMPANION_PERSON: 3,
        }
    )
    for bundle in OFFICIAL_WORLD_BUNDLES:
        assert len(bundle.anchors) == len(bundle.bindings) == 17
        assert {value.id for value in bundle.anchors} == {
            value.anchor_id for value in bundle.bindings
        }
        assert Counter(value.function_id for value in bundle.bindings) == (
            expected_function_counts
        )


if __name__ == "__main__":
    main()
