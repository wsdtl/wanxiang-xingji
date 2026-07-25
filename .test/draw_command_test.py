"""抽奖命令通过本地驱动器的最终图文回复巡检。"""

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
from game.cmd import 抽奖 as draw_component  # noqa: E402,F401
from game.cmd import 角色 as character_component  # noqa: E402,F401
from game.content import DRAW_TICKET_ITEM_ID  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    CharacterState,
    GrantStack,
    InventoryState,
    InventoryTransaction,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    SourceReceipt,
)
from game.core.persistence import CHARACTER_AGGREGATE, INVENTORY_AGGREGATE  # noqa: E402
from game.cmd.抽奖 import service as draw_command_service  # noqa: E402
from launch.adapter.local import LocalEventHandler, dispatch  # noqa: E402
from launch.adapter.qq import QqEventHandler  # noqa: E402


TIME = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)


def main() -> None:
    asyncio.run(_main())
    print("draw command tests passed")


async def _main() -> None:
    for command in ("抽奖", "十连抽奖", "抽奖奖池", "抽奖记录"):
        assert len(LocalEventHandler.exact_rules[command]) == 1
        assert len(QqEventHandler.exact_rules[command]) == 1

    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "draw-command.db",
            identity_secret="draw-command-secret",
        )
        services.database.initialize()
        previous = install_game_services(services)
        original_now = draw_command_service.command_time
        draw_command_service.command_time = lambda: TIME
        try:
            await LocalEventHandler.run()
            await dispatch(
                client_id="draw-player",
                raw_message="创建角色 逐光客",
                sender_name="逐光客",
                event_id="draw-create",
            )
            with services.database.unit_of_work(write=False) as uow:
                characters = services.character_creation.snapshots.list(
                    uow,
                    CHARACTER_AGGREGATE,
                    CharacterState,
                    limit=10,
                )
            assert len(characters) == 1
            character = characters[0]
            _grant_tickets(services, character.id, 11)

            pool = await dispatch(
                client_id="draw-player",
                raw_message="抽奖奖池",
                sender_name="逐光客",
                event_id="draw-pool",
            )
            assert "持有: _11 张_" in pool.replies[0].message.content
            assert "每张抽奖签封存一次未定结果" in pool.replies[0].message.content
            assert "常规 77%" in pool.replies[0].message.content
            assert "珍稀 20%" in pool.replies[0].message.content
            assert "特殊 2%" in pool.replies[0].message.content
            assert "破境 1%" in pool.replies[0].message.content
            assert "问道玉契" in pool.replies[0].message.content
            assert "破境: _0/50_" in pool.replies[0].message.content

            result = await dispatch(
                client_id="draw-player",
                raw_message="抽奖",
                sender_name="逐光客",
                event_id="draw-once",
            )
            message = result.replies[0].message
            assert message.kind == "markdown"
            assert "![抽奖演出 #360px #203px]" in message.content
            assert "抽奖·显化结果" in message.content and "剩余: _10 张_" in message.content
            assert [value.data for value in message.actions] == ["抽奖", "十连抽奖", "抽奖奖池"]

            history = await dispatch(
                client_id="draw-player",
                raw_message="抽奖记录",
                sender_name="逐光客",
                event_id="draw-history",
            )
            assert "抽奖·显化记录" in history.replies[0].message.content
            assert "1 抽" in history.replies[0].message.content

            original_file = draw_command_service.DRAW_ANIMATION_FILES[(1, "low")]
            draw_command_service.DRAW_ANIMATION_FILES[(1, "low")] = "missing.gif"
            try:
                assert draw_command_service._animation_url(1, "low") == ""
            finally:
                draw_command_service.DRAW_ANIMATION_FILES[(1, "low")] = original_file
        finally:
            draw_command_service.command_time = original_now
            restore_game_services(previous)


def _grant_tickets(services, character_id: str, quantity: int) -> None:
    with services.database.unit_of_work() as uow:
        inventory = services.draw.snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            InventoryState,
        )
        container_id = next(
            value.id
            for value in inventory.containers.values()
            if value.kind == "container.special"
        )
        outcome = services.draw.inventory_engine.execute(
            InventoryTransaction(
                "draw-command:grant",
                character_id,
                "inventory.test_grant",
                (
                    GrantStack(
                        f"stack:{character_id}:{DRAW_TICKET_ITEM_ID}",
                        DRAW_TICKET_ITEM_ID,
                        container_id,
                        quantity,
                        SourceReceipt(
                            "receipt:draw-command",
                            "source.test",
                            character_id,
                            TIME,
                        ),
                    ),
                ),
            ),
            state=inventory,
            context=RuleContext(
                "draw-command:grant",
                "rules.draw_command_test.v1",
                Ruleset("ruleset.draw_command_test"),
                TIME,
                SeededRandomSource("draw-command:grant"),
            ),
        )
        assert outcome.ok and outcome.value is not None
        services.draw.snapshots.update(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            inventory,
            outcome.value.state,
            TIME,
        )
        uow.commit()


if __name__ == "__main__":
    main()
