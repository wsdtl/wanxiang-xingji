"""三世界世界志内容、统一回复、已读状态和重启持久化验收。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from importlib import import_module
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services, install_game_services, restore_game_services  # noqa: E402
from game.content import PLAYABLE_WORLD_IDS, WORLD_LORE_CATALOG  # noqa: E402
from game.core.persistence import CHARACTER_AGGREGATE  # noqa: E402
from game.rules.character import CHARACTER_WORLD_AGGREGATE, CharacterWorldState  # noqa: E402
from game.rules.world_progress import (  # noqa: E402
    WORLD_PROGRESS_AGGREGATE,
    WorldProgressState,
    world_progress_state_id,
)
from launch.adapter.local import LocalEventHandler, dispatch  # noqa: E402


TIME = datetime(2026, 7, 23, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
CLIENT_ID = "world-lore-player"
SECRET = "world-lore-test-secret"
FORBIDDEN_PLAYER_DECISIONS = (
    "你决定",
    "你选择",
    "你成为",
    "你的使命",
    "你的名字被",
    "你拯救",
    "替所有人作出",
)


def main() -> None:
    _assert_lore_content()
    asyncio.run(_main())
    print("world lore tests passed")


def _assert_lore_content() -> None:
    assert WORLD_LORE_CATALOG.world_ids() == PLAYABLE_WORLD_IDS
    all_record_ids = []
    for lore in WORLD_LORE_CATALOG.definitions():
        assert tuple(value.threshold for value in lore.records) == (0, 25, 50, 75, 100)
        assert len(lore.overview) >= 20
        texts = [lore.overview]
        for record in lore.records:
            assert len(record.title) >= 4
            assert len(record.paragraphs) == 3
            assert all(len(value) >= 25 for value in record.paragraphs)
            texts.extend(record.paragraphs)
            all_record_ids.append(record.id)
        combined = "\n".join(texts)
        assert not any(value in combined for value in FORBIDDEN_PLAYER_DECISIONS)
    assert len(all_record_ids) == len(set(all_record_ids)) == 15


async def _main() -> None:
    import_module("game.cmd.角色")
    import_module("game.cmd.行纪")
    import_module("game.cmd.世界志")
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "world-lore.db"
        services = build_game_services(
            database_path=database_path,
            identity_secret=SECRET,
        )
        services.database.initialize()
        previous = install_game_services(services)
        try:
            await LocalEventHandler.run()
            created = await _dispatch("创建角色 见证者", "lore-create")
            assert len(created.replies) == 1
            character = _created_character(services)
            character_world = _character_world(services, character.id)
            world_view = services.world_views.require(character_world.world_id)
            lore_definition = WORLD_LORE_CATALOG.require(character_world.world_id)

            progress = await _dispatch("行纪", "lore-progress-first")
            progress_contents = _contents(progress)
            assert len(progress_contents) == 1
            assert f"行纪·{world_view.skin.name}" in progress_contents[0]

            overview = await _dispatch("世界志", "lore-overview")
            overview_content = _single_content(overview)
            assert f"世界志·{world_view.skin.name}" in overview_content
            assert lore_definition.overview in overview_content
            assert lore_definition.records[0].title in overview_content
            assert "新录" in overview_content and "25%解锁" in overview_content

            first_record = await _dispatch("世界志 1", "lore-read-first")
            first_content = _single_content(first_record)
            assert lore_definition.records[0].title in first_content
            assert lore_definition.records[0].paragraphs[0] in first_content
            assert "见证者" in first_content

            other_world_id = next(
                value for value in PLAYABLE_WORLD_IDS if value != character_world.world_id
            )
            other_name = services.world_views.require(other_world_id).skin.name
            locked = await _dispatch(f"世界志 {other_name}", "lore-locked-world")
            assert "尚未在这个世界留下" in _single_content(locked)

            _set_world_progress(services, character, character_world.world_id, 50)
            advanced = await _dispatch("世界志", "lore-progress-advanced")
            advanced_content = _single_content(advanced)
            assert lore_definition.records[2].title in advanced_content
            assert advanced_content.count("新录") == 2

            after_advanced = services.world_lore.view(
                character.id,
                character_world.world_id,
                current_world_id=character_world.world_id,
            )
            assert after_advanced.percent == 50
            assert len(after_advanced.unlocked_records) == 3
            assert len(after_advanced.unseen_records) == 2

            replacement = build_game_services(
                database_path=database_path,
                identity_secret=SECRET,
            )
            replacement.database.initialize()
            install_game_services(replacement)
            persisted = await _dispatch("世界志", "lore-after-restart")
            persisted_content = _single_content(persisted)
            assert "已阅" in persisted_content
            assert persisted_content.count("新录") == 2
        finally:
            await LocalEventHandler.shutdown()
            restore_game_services(previous)


def _set_world_progress(services, character, world_id: str, points: int) -> None:
    bindings = services.content.worlds.bindings_for_world(
        world_id,
        function_id="location.function.exploration",
    )
    with services.database.unit_of_work() as uow:
        for binding in bindings:
            state = WorldProgressState(
                character.id,
                character.name,
                world_id,
                binding.content_ref,
                points=points,
                victories=points,
                claimed_milestones=tuple(
                    value for value in (25, 50, 75, 100) if value <= points
                ),
                started_at=TIME,
                reached_at=TIME,
                completed_at=TIME if points == 100 else None,
                revision=1,
            )
            services.world_progress.snapshots.insert(
                uow,
                WORLD_PROGRESS_AGGREGATE,
                world_progress_state_id(character.id, world_id, binding.content_ref),
                state,
                TIME,
            )
        uow.commit()


def _created_character(services):
    with services.database.unit_of_work(write=False) as uow:
        row = uow.connection.execute(
            "SELECT aggregate_id FROM aggregate_snapshot WHERE aggregate_kind = ?",
            (CHARACTER_AGGREGATE,),
        ).fetchone()
    character = services.characters.load_character(str(row[0]))
    assert character is not None
    return character


def _character_world(services, character_id: str) -> CharacterWorldState:
    with services.database.unit_of_work(write=False) as uow:
        return services.character_creation.snapshots.require(
            uow,
            CHARACTER_WORLD_AGGREGATE,
            character_id,
            CharacterWorldState,
        )


async def _dispatch(command: str, event_id: str):
    return await dispatch(
        client_id=CLIENT_ID,
        raw_message=command,
        sender_name="见证者",
        event_id=event_id,
    )


def _contents(result) -> tuple[str, ...]:
    assert result.matched and result.matched_count == 1, result
    return tuple(value.message.content for value in result.replies)


def _single_content(result) -> str:
    values = _contents(result)
    assert len(values) == 1, result
    return values[0]


if __name__ == "__main__":
    main()
