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
from game.content import (  # noqa: E402
    DRAW_CURRENCY_COST_PER_ROLL,
    DRAW_TICKET_ITEM_ID,
)
from game.core.gameplay import (  # noqa: E402
    CharacterState,
    GrantStack,
    InventoryState,
    InventoryTransaction,
    IssueFunds,
    LedgerState,
    LedgerTransaction,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    SourceReceipt,
)
from game.core.persistence import (  # noqa: E402
    CHARACTER_AGGREGATE,
    INVENTORY_AGGREGATE,
    LEDGER_AGGREGATE,
)
from game.rules.character import (  # noqa: E402
    PRIMARY_ISSUER_ACCOUNT_ID,
    PRIMARY_LEDGER_ID,
)
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
            _grant_tickets(services, character.id, 4)

            pool = await dispatch(
                client_id="draw-player",
                raw_message="抽奖奖池",
                sender_name="逐光客",
                event_id="draw-pool",
            )
            assert "抽奖签: _4 张_" in pool.replies[0].message.content
            assert "每张抽奖签封存一次未定结果" in pool.replies[0].message.content
            assert f"每缺 1 张支付 {DRAW_CURRENCY_COST_PER_ROLL}" in pool.replies[0].message.content
            assert "十连最多支付 2500" in pool.replies[0].message.content
            assert "50 抽全货币为 12500" in pool.replies[0].message.content
            assert "不设十连折扣" in pool.replies[0].message.content
            assert "常规 77%" in pool.replies[0].message.content
            assert "珍稀 20%" in pool.replies[0].message.content
            assert "特殊 2%" in pool.replies[0].message.content
            assert "破境 1%" in pool.replies[0].message.content
            assert "问道玉契" in pool.replies[0].message.content
            assert "破境: _0/50_" in pool.replies[0].message.content

            insufficient = await dispatch(
                client_id="draw-player",
                raw_message="十连抽奖",
                sender_name="逐光客",
                event_id="draw-ten-insufficient",
            )
            insufficient_message = insufficient.replies[0].message.content
            assert "可用主货币不足" in insufficient_message
            assert "抽奖签: _4 张_" in insufficient_message
            assert "需要: _1500_" in insufficient_message
            assert "本次没有扣除抽奖签、货币，也没有推进保底" in insufficient_message

            result = await dispatch(
                client_id="draw-player",
                raw_message="抽奖",
                sender_name="逐光客",
                event_id="draw-once",
            )
            message = result.replies[0].message
            assert message.kind == "markdown"
            assert "![抽奖演出 #360px #203px]" in message.content
            assert "抽奖·显化结果" in message.content and "余签: _3 张_" in message.content
            assert "消耗: _" in message.content and "1 张" in message.content
            assert [value.data for value in message.actions] == ["抽奖", "十连抽奖", "抽奖奖池"]

            _grant_currency(services, character.id, 2_000)
            mixed = await dispatch(
                client_id="draw-player",
                raw_message="十连抽奖",
                sender_name="逐光客",
                event_id="draw-ten",
            )
            mixed_message = mixed.replies[0].message
            assert "抽奖·显化结果" in mixed_message.content
            assert "3 张 +" in mixed_message.content
            assert "1750" in mixed_message.content
            assert "余签: _0 张_" in mixed_message.content

            history = await dispatch(
                client_id="draw-player",
                raw_message="抽奖记录",
                sender_name="逐光客",
                event_id="draw-history",
            )
            assert "抽奖·显化记录" in history.replies[0].message.content
            assert "1 抽" in history.replies[0].message.content
            assert "10 抽" in history.replies[0].message.content

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


def _grant_currency(services, character_id: str, amount: int) -> None:
    with services.database.unit_of_work() as uow:
        ledger = services.draw.snapshots.require(
            uow,
            LEDGER_AGGREGATE,
            PRIMARY_LEDGER_ID,
            LedgerState,
        )
        issuer = ledger.accounts[PRIMARY_ISSUER_ACCOUNT_ID]
        wallet = next(
            value
            for value in ledger.accounts.values()
            if value.owner_kind == "owner.character" and value.owner_id == character_id
        )
        outcome = services.draw.ledger_engine.execute(
            LedgerTransaction(
                "draw-command:grant-currency",
                character_id,
                "economy.test_issue",
                (IssueFunds(issuer.id, wallet.id, amount),),
                expected_revisions={
                    issuer.id: issuer.revision,
                    wallet.id: wallet.revision,
                },
            ),
            state=ledger,
            context=RuleContext(
                "draw-command:grant-currency",
                "rules.draw_command_test.v1",
                Ruleset("ruleset.draw_command_test"),
                TIME,
                SeededRandomSource("draw-command:grant-currency"),
            ),
        )
        assert outcome.ok and outcome.value is not None
        services.draw.snapshots.update(
            uow,
            LEDGER_AGGREGATE,
            PRIMARY_LEDGER_ID,
            ledger,
            outcome.value.state,
            TIME,
        )
        uow.commit()


if __name__ == "__main__":
    main()
