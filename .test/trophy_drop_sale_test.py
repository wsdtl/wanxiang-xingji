"""探险战利品、容量停止与固定价原子回收闭环测试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services  # noqa: E402
from game.content.catalog.item import REGION_TROPHY_ITEM_IDS  # noqa: E402
from game.content.catalog.world import GREEN_CLOUD_PLAIN_ID  # noqa: E402
from game.core.account import ExternalIdentity, IdentityEvidence  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    CharacterState,
    GrantStack,
    InventoryState,
    InventoryTransaction,
    LedgerAccountKind,
    LedgerState,
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
from game.rules.character import PRIMARY_LEDGER_ID  # noqa: E402
from game.rules.exploration import ExplorationStatus, ExplorationStopReason  # noqa: E402


TIME = datetime(2026, 7, 18, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "trophy.db",
            identity_secret="trophy-drop-sale-secret",
        )
        services.character_creation.workflow.id_factory = lambda kind: f"{kind}-fixed"
        services.database.initialize()
        character_id, world_id = _create_character(services)
        _strengthen_character(services, character_id)

        services.world_travel.move(
            character_id,
            services.content.worlds.require_binding_for_display(
                world_id,
                GREEN_CLOUD_PLAIN_ID,
            ).anchor_id,
            logical_time=TIME,
        )
        started = services.exploration.start(character_id, logical_time=TIME)
        assert started.status == "started"
        settled = services.exploration.settle_due(
            character_id,
            logical_time=TIME + timedelta(minutes=10),
        )
        assert settled.state is not None
        assert settled.state.victories == 1
        assert settled.state.trophy_drops >= 1
        assert settled.state.trophy_value > 0

        before_balance = _wallet_balance(services, character_id)
        before_trophies = tuple(
            (stack.definition_id, stack.quantity)
            for stack in _trophy_stacks(services, character_id)
        )
        ledger_engine = services.economy.ledger_engine
        services.economy.ledger_engine = _FailingLedgerEngine()
        try:
            services.economy.recycle_trophies(
                character_id,
                logical_time=TIME + timedelta(minutes=10, seconds=30),
            )
            raise AssertionError("账本失败时回收必须整体失败")
        except RuntimeError as exc:
            assert "测试账本失败" in str(exc)
        finally:
            services.economy.ledger_engine = ledger_engine
        assert _wallet_balance(services, character_id) == before_balance
        assert tuple(
            (stack.definition_id, stack.quantity)
            for stack in _trophy_stacks(services, character_id)
        ) == before_trophies

        sale = services.economy.recycle_trophies(
            character_id,
            logical_time=TIME + timedelta(minutes=11),
        )
        assert sale.status == "recycled"
        assert sale.quote.total_amount == settled.state.trophy_value
        assert _wallet_balance(services, character_id) == (
            before_balance + sale.quote.total_amount
        )
        assert not _trophy_stacks(services, character_id)
        assert services.economy.recycle_trophies(
            character_id,
            logical_time=TIME + timedelta(minutes=11, seconds=1),
        ).status == "empty"

        services.exploration.stop(
            character_id,
            logical_time=TIME + timedelta(minutes=12),
        )
        _fill_backpack(services, character_id, quantity=40)
        restarted = services.exploration.start(
            character_id,
            logical_time=TIME + timedelta(minutes=13),
        )
        assert restarted.status == "started"
        for index in range(1, 6):
            full = services.exploration.settle_due(
                character_id,
                logical_time=TIME + timedelta(minutes=13 + index * 10),
            )
            if full.state is not None and full.state.status is ExplorationStatus.STOPPED:
                break
        assert full.state is not None
        assert full.state.stop_reason is ExplorationStopReason.CAPACITY_FULL
        assert sum(stack.quantity for stack in _trophy_stacks(services, character_id)) == 40

    print("trophy drop and sale tests passed")


class _FailingLedgerEngine:
    def execute(self, *_args, **_kwargs):
        failure = type("Failure", (), {"message": "测试账本失败"})()
        return type("Outcome", (), {"failure": failure, "value": None})()


def _create_character(services) -> tuple[str, str]:
    evidence = IdentityEvidence(
        "trophy-evidence",
        ExternalIdentity(
            "platform.local",
            "trophy-user",
            "identity.user",
            "private",
            "player-trophy",
        ),
        (),
        "message.local",
        TIME,
    )
    created = services.create_character(evidence, requested_name="TrophyPlayer")
    assert created.status == "created" and created.receipt is not None
    return created.receipt.character.id, created.receipt.character_world.world_id


def _strengthen_character(services, character_id: str) -> None:
    snapshots = services.character_creation.snapshots
    with services.database.unit_of_work() as uow:
        character = snapshots.require(
            uow,
            CHARACTER_AGGREGATE,
            character_id,
            CharacterState,
        )
        attributes = dict(character.core_attributes)
        attributes[HEALTH_MAXIMUM] = 10_000
        attributes[COMBAT_ATTACK] = 10_000
        attributes[COMBAT_DEFENSE] = 1_000
        resources = dict(character.resources)
        resources[HEALTH_CURRENT] = 10_000
        resources[SPIRIT_CURRENT] = 10_000
        strengthened = replace(
            character,
            core_attributes=attributes,
            resources=resources,
            revision=character.revision + 1,
        )
        snapshots.update(
            uow,
            CHARACTER_AGGREGATE,
            character_id,
            character,
            strengthened,
            TIME,
        )
        uow.commit()


def _fill_backpack(services, character_id: str, *, quantity: int) -> None:
    snapshots = services.character_creation.snapshots
    with services.database.unit_of_work() as uow:
        inventory = snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            InventoryState,
        )
        backpack_id = next(
            value.id
            for value in inventory.containers.values()
            if value.kind == "container.backpack"
        )
        definition_id = REGION_TROPHY_ITEM_IDS[GREEN_CLOUD_PLAIN_ID][0]
        context = RuleContext(
            "fill-trophy-backpack",
            "rules.test.v1",
            Ruleset("ruleset.standard"),
            TIME,
            SeededRandomSource("fill-trophy-backpack"),
        )
        outcome = services.economy.inventory_engine.execute(
            InventoryTransaction(
                "fill-trophy-backpack",
                character_id,
                "inventory.test_fill",
                (
                    GrantStack(
                        "stack-full-trophies",
                        definition_id,
                        backpack_id,
                        quantity,
                        SourceReceipt(
                            "receipt-fill-trophies",
                            "source.test",
                            "fill-trophy-backpack",
                            TIME,
                        ),
                    ),
                ),
            ),
            state=inventory,
            context=context,
        )
        assert outcome.ok and outcome.value is not None, outcome.failure
        snapshots.update(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            inventory,
            outcome.value.state,
            TIME,
        )
        uow.commit()


def _wallet_balance(services, character_id: str) -> int:
    with services.database.unit_of_work(write=False) as uow:
        ledger = services.character_creation.snapshots.require(
            uow,
            LEDGER_AGGREGATE,
            PRIMARY_LEDGER_ID,
            LedgerState,
        )
    return next(
        account.balance
        for account in ledger.accounts.values()
        if account.kind is LedgerAccountKind.STANDARD
        and account.owner_id == character_id
    )


def _trophy_stacks(services, character_id: str):
    with services.database.unit_of_work(write=False) as uow:
        inventory = services.character_creation.snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            InventoryState,
        )
    return tuple(
        stack
        for stack in inventory.stacks.values()
        if services.content.catalog.items.require(stack.definition_id).tags.has("item.trophy")
    )


if __name__ == "__main__":
    main()
