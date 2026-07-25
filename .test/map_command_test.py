"""地图命令与三世界地点意图的本地驱动器巡检。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services, install_game_services, restore_game_services  # noqa: E402
from game.content import (  # noqa: E402
    DIMENSION_SHIFT_ITEM_ID,
    MAGIC_WORLD_ID,
    STELLAR_RING_WORLD_ID,
    TAIXUAN_WORLD_ID,
)
from game.content.catalog.world import (  # noqa: E402
    LOCATION_FUNCTION_COMPANION_PERSON,
    LOCATION_FUNCTION_EXPLORATION,
)
from game.core.gameplay import (  # noqa: E402
    GrantStack,
    InventoryState,
    InventoryTransaction,
    SourceReceipt,
)
from game.core.persistence import CHARACTER_AGGREGATE, INVENTORY_AGGREGATE  # noqa: E402
from game.features.world_travel import WorldLocationIntent  # noqa: E402
from game.rules import game_operation_context  # noqa: E402
from game.cmd import 地图 as map_component  # noqa: E402,F401
from game.cmd import 角色 as character_component  # noqa: E402,F401
from game.cmd import 跃迁 as shift_component  # noqa: E402,F401
from game.cmd import 探险 as exploration_component  # noqa: E402,F401
from launch.adapter.local import LocalEventHandler, dispatch  # noqa: E402
from launch.adapter.qq import QqEventHandler  # noqa: E402


TIMEZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 21, 10, 0, tzinfo=TIMEZONE)
CLIENT_ID = "map-command-player"


def main() -> None:
    asyncio.run(_main())
    print("map command tests passed")


async def _main() -> None:
    assert len(LocalEventHandler.exact_rules["地图"]) == 1
    assert len(QqEventHandler.exact_rules["地图"]) == 1

    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "map-command.db",
            identity_secret="map-command-secret",
        )
        services.database.initialize()
        previous = install_game_services(services)
        try:
            await LocalEventHandler.run()
            await _dispatch("创建角色 观图客", "map-create")
            character = _created_character(services)
            _grant_shift_items(services, character.id, 2)

            old_action = None
            for index, world_id in enumerate(
                (TAIXUAN_WORLD_ID, MAGIC_WORLD_ID, STELLAR_RING_WORLD_ID)
            ):
                if index:
                    shifted = await _dispatch(f"跃迁 {world_id}", f"map-shift-{index}")
                    assert "目标世界已完成化身重构" in _content(shifted)
                    if old_action is not None:
                        stale = await _dispatch(old_action.data, f"map-stale-{index}")
                        assert "地点按钮已经失效" in _content(stale)

                overview = services.load_character_overview(character).overview
                assert overview is not None
                assert overview.character_world.world_id == world_id
                view = services.world_views.require(world_id)
                listing = await _dispatch("地图", f"map-list-{index}")
                text = _content(listing)
                assert view.skin.name in text
                assert all(title in text for title in ("主城", "探险区域", "人物地点"))
                assert text.count("\\[当前\\]") == 1

                bindings = services.content.worlds.bindings_for_world(world_id)
                assert len(bindings) == 17
                for binding in bindings:
                    resolved = services.content.worlds.resolve(world_id, binding.anchor_id)
                    assert view.projector.name(resolved.display_id) in text
                    assert f"({resolved.position.x}, {resolved.position.y})" in text
                    assert binding.anchor_id not in text

                presence = next(
                    value
                    for value in overview.world.presences.values()
                    if value.owner_id == character.id
                )
                current_anchor = services.content.worlds.anchor_at(
                    world_id,
                    presence.position,
                )
                exploration_binding = next(
                    value
                    for value in services.content.worlds.bindings_for_world(
                        world_id,
                        function_id=LOCATION_FUNCTION_EXPLORATION,
                    )
                    if value.anchor_id != current_anchor
                )
                exploration = services.content.worlds.resolve(
                    world_id,
                    exploration_binding.anchor_id,
                )
                location_name = view.projector.name(exploration.display_id)
                detail = await _dispatch(
                    f"地图 {location_name}",
                    f"map-detail-{index}",
                )
                detail_message = detail.replies[0].message
                detail_text = detail_message.content
                assert view.projector.entry(exploration.display_id).description in detail_text
                assert "探险区域" in detail_text and "等级" in detail_text
                action = next(
                    value for value in detail_message.actions
                    if value.label == "前往"
                )
                intent = WorldLocationIntent.parse(action.data.removeprefix("前往 "))
                assert intent is not None
                assert intent.world_id == world_id
                assert intent.anchor_id == exploration_binding.anchor_id
                assert intent.function_id == LOCATION_FUNCTION_EXPLORATION
                old_action = action

                moved = await _dispatch(action.data, f"map-move-{index}")
                assert "抵达" in _content(moved) or "已经在这里" in _content(moved)

                person_binding = services.content.worlds.bindings_for_world(
                    world_id,
                    function_id=LOCATION_FUNCTION_COMPANION_PERSON,
                )[0]
                person_location = services.content.worlds.resolve(
                    world_id,
                    person_binding.anchor_id,
                )
                person = services.content.companions.people.require(
                    person_location.require_content_ref()
                )
                person_detail = await _dispatch(
                    f"地图 {view.projector.name(person_location.display_id)}",
                    f"map-person-{index}",
                )
                assert person.name in _content(person_detail)
                assert "关系 0/" in _content(person_detail)

            missing = await _dispatch("地图 不存在的地点", "map-missing")
            assert "当前世界没有这个地点" in _content(missing)
        finally:
            restore_game_services(previous)


def _created_character(services):
    with services.database.unit_of_work(write=False) as uow:
        row = uow.connection.execute(
            "SELECT aggregate_id FROM aggregate_snapshot WHERE aggregate_kind = ?",
            (CHARACTER_AGGREGATE,),
        ).fetchone()
    character = services.characters.load_character(str(row[0]))
    assert character is not None
    return character


def _grant_shift_items(services, character_id: str, quantity: int) -> None:
    snapshots = services.character_creation.snapshots
    with services.database.unit_of_work() as uow:
        inventory = snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            InventoryState,
        )
        container = next(
            value for value in inventory.containers.values()
            if value.kind == "container.special"
        )
        outcome = services.inventory_engine.execute(
            InventoryTransaction(
                "map-test-grant-shift-items",
                character_id,
                "inventory.test_setup",
                (
                    GrantStack(
                        "map-test-shift-stack",
                        DIMENSION_SHIFT_ITEM_ID,
                        container.id,
                        quantity,
                        SourceReceipt(
                            "map-test-shift-receipt",
                            "source.test",
                            character_id,
                            NOW,
                        ),
                    ),
                ),
            ),
            state=inventory,
            context=game_operation_context(
                "map-test-grant-shift-items",
                logical_time=NOW,
            ),
        ).unwrap()
        snapshots.update(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            inventory,
            outcome.state,
            NOW,
        )
        uow.commit()


async def _dispatch(command: str, event_id: str):
    return await dispatch(
        client_id=CLIENT_ID,
        raw_message=command,
        sender_name="观图客",
        event_id=event_id,
    )


def _content(result) -> str:
    assert result.matched and result.matched_count == 1, result
    assert len(result.replies) == 1, result
    message = result.replies[0].message
    assert message.kind == "markdown"
    assert message.content.strip()
    return message.content


if __name__ == "__main__":
    main()
