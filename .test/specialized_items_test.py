"""芥子神砂的持久化与容量边界测试。"""

from datetime import datetime, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services  # noqa: E402
from game.content import (  # noqa: E402
    BACKPACK_CAPACITY_ITEM_ID,
    BACKPACK_CAPACITY_MAXIMUM,
)
from game.core.account import ExternalIdentity, IdentityEvidence  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    GrantStack,
    InventoryState,
    InventoryTransaction,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    SourceReceipt,
)
from game.core.persistence import INVENTORY_AGGREGATE  # noqa: E402
from game.features.special_items import SpecialItemUseCommand  # noqa: E402


TIME = datetime(2026, 7, 19, 16, 0, tzinfo=timezone.utc)


def main() -> None:
    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "specialized-items.db",
            identity_secret="specialized-items-secret",
        )
        services.database.initialize()
        character = _create_character(services)
        _grant_special_items(services, character.id)

        for index in range(20):
            outcome = services.special_item_use.use(
                SpecialItemUseCommand(
                    f"capacity-use:{index}",
                    character.id,
                    "stack:backpack-capacity",
                ),
                inventory_id=character.id,
                context=_context(f"capacity-use:{index}", index),
            )
            assert outcome.ok and outcome.value is not None, outcome.failure
        inventory = _inventory(services, character.id)
        backpack = next(
            value for value in inventory.containers.values() if value.kind == "container.backpack"
        )
        assert backpack.maximum_space == BACKPACK_CAPACITY_MAXIMUM == 140
        assert inventory.stacks["stack:backpack-capacity"].quantity == 1

        rejected = services.special_item_use.use(
            SpecialItemUseCommand(
                "capacity-use:rejected",
                character.id,
                "stack:backpack-capacity",
            ),
            inventory_id=character.id,
            context=_context("capacity-use:rejected", 100),
        )
        assert rejected.failure is not None
        assert rejected.failure.code == "inventory.container_space_maximum_reached"
        assert _inventory(services, character.id).stacks[
            "stack:backpack-capacity"
        ].quantity == 1

    print("specialized item tests passed")


def _create_character(services):
    evidence = IdentityEvidence(
        "evidence:specialized-items",
        ExternalIdentity(
            "platform.local",
            "specialized-items",
            "identity.user",
            "private",
            "specialized-items-user",
        ),
        (),
        "message.local",
        TIME,
    )
    created = services.create_character(evidence, requested_name="试砂人")
    assert created.status == "created" and created.receipt is not None
    return created.receipt.character


def _grant_special_items(services, character_id: str) -> None:
    snapshots = services.special_item_use.snapshots
    with services.database.unit_of_work() as uow:
        inventory = snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            InventoryState,
        )
        special = next(
            value for value in inventory.containers.values() if value.kind == "container.special"
        )
        outcome = services.special_item_use.inventory_engine.execute(
            InventoryTransaction(
                "grant:specialized-items",
                character_id,
                "inventory.test_grant",
                (
                    GrantStack(
                        "stack:backpack-capacity",
                        BACKPACK_CAPACITY_ITEM_ID,
                        special.id,
                        21,
                        SourceReceipt(
                            "receipt:backpack-capacity",
                            "source.test",
                            "specialized-items",
                            TIME,
                        ),
                    ),
                ),
            ),
            state=inventory,
            context=_context("grant:specialized-items", 0),
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


def _inventory(services, character_id: str) -> InventoryState:
    with services.database.unit_of_work(write=False) as uow:
        return services.special_item_use.snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            InventoryState,
        )


def _context(trace_id: str, seed: int) -> RuleContext:
    return RuleContext(
        trace_id,
        "rules.specialized_items_test.v1",
        Ruleset("ruleset.specialized_items_test"),
        TIME,
        SeededRandomSource(seed),
    )


if __name__ == "__main__":
    main()
