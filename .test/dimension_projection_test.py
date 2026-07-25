"""真实世界身份、独立空间、独立布局与展示投影测试。"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.content import (  # noqa: E402
    CULTIVATION_SKIN_ID,
    MAGIC_SKIN_ID,
    MAGIC_WORLD_ID,
    STELLAR_RING_SKIN_ID,
    STELLAR_RING_WORLD_ID,
    PLAYABLE_WORLD_IDS,
    PRIMARY_CURRENCY_ID,
    STARTING_CITY_ID,
    TAIXUAN_WORLD_ID,
    build_world_view_catalog,
)
from game.core.gameplay import SeededRandomSource  # noqa: E402
from game.rules.character import assign_initial_world, shift_world  # noqa: E402


NOW = datetime(2026, 7, 18, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
    views = build_world_view_catalog()
    cultivation = views.require(TAIXUAN_WORLD_ID)
    magic = views.require(MAGIC_WORLD_ID)
    stellar = views.require(STELLAR_RING_WORLD_ID)

    assert cultivation is views.require(TAIXUAN_WORLD_ID)
    assert magic is views.require(MAGIC_WORLD_ID)
    assert cultivation.catalog is magic.catalog is stellar.catalog is views.catalog
    assert cultivation.skin.id == CULTIVATION_SKIN_ID
    assert magic.skin.id == MAGIC_SKIN_ID
    assert stellar.skin.id == STELLAR_RING_SKIN_ID
    assert cultivation.projector.name(PRIMARY_CURRENCY_ID) != magic.projector.name(
        PRIMARY_CURRENCY_ID
    )
    assert cultivation.projector.name(STARTING_CITY_ID) != magic.projector.name(
        STARTING_CITY_ID
    )
    assert cultivation.catalog.items.definitions.ids() == magic.catalog.items.definitions.ids()
    assert cultivation.catalog.weapons.definitions.ids() == magic.catalog.weapons.definitions.ids()
    assert cultivation.catalog.equipment.definitions.ids() == magic.catalog.equipment.definitions.ids()
    assert views.world_ids() == PLAYABLE_WORLD_IDS
    assert views.require_skin(CULTIVATION_SKIN_ID) is cultivation

    cultivation_position = views.worlds.spawn_position(TAIXUAN_WORLD_ID)
    magic_position = views.worlds.spawn_position(MAGIC_WORLD_ID)
    stellar_position = views.worlds.spawn_position(STELLAR_RING_WORLD_ID)
    assert (cultivation_position.x, cultivation_position.y) == (0, 0)
    assert (magic_position.x, magic_position.y) == (0, 0)
    assert (stellar_position.x, stellar_position.y) == (0, 0)
    assert len(
        {
            cultivation_position.space_id,
            magic_position.space_id,
            stellar_position.space_id,
        }
    ) == 3
    assert views.worlds.anchor_at(TAIXUAN_WORLD_ID, magic_position) is None

    assignments = {
        assign_initial_world(
            f"character-{seed}",
            views.world_ids(),
            random=SeededRandomSource(seed),
            logical_time=NOW,
        ).world_id
        for seed in range(128)
    }
    assert assignments == {TAIXUAN_WORLD_ID, MAGIC_WORLD_ID, STELLAR_RING_WORLD_ID}

    initial = assign_initial_world(
        "character-repeatable",
        views.world_ids(),
        random=SeededRandomSource("same-seed"),
        logical_time=NOW,
    )
    repeated = assign_initial_world(
        "character-repeatable",
        views.world_ids(),
        random=SeededRandomSource("same-seed"),
        logical_time=NOW,
    )
    assert repeated == initial

    target = next(value for value in PLAYABLE_WORLD_IDS if value != initial.world_id)
    shifted = shift_world(initial, target, logical_time=NOW + timedelta(minutes=1))
    assert shifted.status == "shifted"
    assert shifted.previous_world_id == initial.world_id
    assert shifted.current is not None
    assert shifted.current.world_id == target
    assert shifted.current.revision == initial.revision + 1

    unchanged = shift_world(
        shifted.current,
        target,
        logical_time=NOW + timedelta(minutes=2),
    )
    assert unchanged.status == "already_there"
    assert unchanged.current == shifted.current

    forbidden = (
        "services.content.projector",
        "services.content.gear_projector",
        "services.content.enemy_projector",
        "current_game_services().content.projector",
    )
    for root in (ROOT / "game" / "cmd", ROOT / "game" / "features"):
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert not any(value in source for value in forbidden), (
                f"玩家展示不能回退到服务器默认皮肤: {path}"
            )

    print("dimension projection tests passed")


if __name__ == "__main__":
    main()
