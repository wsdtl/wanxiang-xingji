"""突破命令、关隘提示和统一消息头的本地驱动器巡检。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import (  # noqa: E402
    build_game_services,
    install_game_services,
    restore_game_services,
)
from game.cmd import 突破 as breakthrough_component  # noqa: E402,F401
from game.cmd import 角色 as character_component  # noqa: E402,F401
from game.cmd.突破 import service as command_service  # noqa: E402
from game.content import (  # noqa: E402
    BREAKTHROUGH_TOKEN_ITEM_ID,
    CHARACTER_LEVEL_EXPERIENCE_REQUIREMENTS,
    CHARACTER_LEVEL_PROGRESSION_ID,
)
from game.core.gameplay import (  # noqa: E402
    CharacterEngine,
    CharacterState,
    CharacterTransaction,
    GrantExperience,
    GrantStack,
    InventoryState,
    InventoryTransaction,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    SourceReceipt,
)
from game.core.persistence import CHARACTER_AGGREGATE, INVENTORY_AGGREGATE  # noqa: E402
from game.rules.character import CHARACTER_WORLD_AGGREGATE, CharacterWorldState  # noqa: E402
from launch.adapter.local import LocalEventHandler, dispatch  # noqa: E402
from launch.adapter.qq import QqEventHandler  # noqa: E402


TIME = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


def main() -> None:
    asyncio.run(_main())
    print("breakthrough command tests passed")


async def _main() -> None:
    assert len(LocalEventHandler.exact_rules["突破"]) == 1
    assert len(QqEventHandler.exact_rules["突破"]) == 1
    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "breakthrough-command.db",
            identity_secret="breakthrough-command-secret",
        )
        services.database.initialize()
        previous = install_game_services(services)
        original_now = command_service.command_time
        command_service.command_time = lambda: TIME
        try:
            await LocalEventHandler.run()
            await dispatch(
                client_id="breakthrough-player",
                raw_message="创建角色 破关客",
                sender_name="破关客",
                event_id="breakthrough-create",
            )
            character = _character(services)
            _prepare(services, character.id)

            profile = await dispatch(
                client_id="breakthrough-player",
                raw_message="我的角色",
                sender_name="破关客",
                event_id="breakthrough-profile",
            )
            assert "经验: _已满，可突破_" in profile.replies[0].message.content

            dimension = _dimension(services, character.id)
            token_name = services.world_view(dimension).projector.name(
                BREAKTHROUGH_TOKEN_ITEM_ID
            )
            result = await dispatch(
                client_id="breakthrough-player",
                raw_message="突破",
                sender_name="破关客",
                event_id="breakthrough-run",
            )
            content = result.replies[0].message.content
            assert content.splitlines()[0].endswith("破关客 Lv11**")
            assert "境界突破" in content
            assert f"消耗: _{token_name} x1_" in content
            assert "血气与灵力已恢复" in content
        finally:
            command_service.command_time = original_now
            restore_game_services(previous)


def _character(services) -> CharacterState:
    with services.database.unit_of_work(write=False) as uow:
        values = services.breakthrough.snapshots.list(
            uow,
            CHARACTER_AGGREGATE,
            CharacterState,
            limit=10,
        )
    assert len(values) == 1
    return values[0]


def _dimension(services, character_id: str) -> CharacterWorldState:
    with services.database.unit_of_work(write=False) as uow:
        return services.breakthrough.snapshots.require(
            uow,
            CHARACTER_WORLD_AGGREGATE,
            character_id,
            CharacterWorldState,
        )


def _prepare(services, character_id: str) -> None:
    snapshots = services.breakthrough.snapshots
    with services.database.unit_of_work() as uow:
        character = snapshots.require(uow, CHARACTER_AGGREGATE, character_id, CharacterState)
        advanced = CharacterEngine(services.content.catalog.characters).execute(
            CharacterTransaction(
                "breakthrough-command:experience",
                character_id,
                character.revision,
                "source.test",
                (
                    GrantExperience(
                        CHARACTER_LEVEL_PROGRESSION_ID,
                        sum(CHARACTER_LEVEL_EXPERIENCE_REQUIREMENTS[:10]),
                        "source.test",
                        "breakthrough-command",
                    ),
                ),
            ),
            state=character,
            context=_context("breakthrough-command:experience"),
        ).unwrap().state
        snapshots.update(uow, CHARACTER_AGGREGATE, character_id, character, advanced, TIME)

        inventory = snapshots.require(uow, INVENTORY_AGGREGATE, character_id, InventoryState)
        container = next(value for value in inventory.containers.values() if value.kind == "container.special")
        granted = services.inventory_engine.execute(
            InventoryTransaction(
                "breakthrough-command:token",
                character_id,
                "source.test",
                (
                    GrantStack(
                        f"stack:{character_id}:{BREAKTHROUGH_TOKEN_ITEM_ID}",
                        BREAKTHROUGH_TOKEN_ITEM_ID,
                        container.id,
                        1,
                        SourceReceipt(
                            "receipt:breakthrough-command:token",
                            "source.test",
                            character_id,
                            TIME,
                        ),
                    ),
                ),
            ),
            state=inventory,
            context=_context("breakthrough-command:token"),
        ).unwrap().state
        snapshots.update(uow, INVENTORY_AGGREGATE, character_id, inventory, granted, TIME)
        uow.commit()


def _context(seed: str) -> RuleContext:
    return RuleContext(
        seed,
        "rules.breakthrough_command_test.v1",
        Ruleset("ruleset.breakthrough_command_test"),
        TIME,
        SeededRandomSource(seed),
    )


if __name__ == "__main__":
    main()
