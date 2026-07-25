"""人物、武器和伙伴成长物品的独立规则与事务测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services  # noqa: E402
from game.content import (  # noqa: E402
    CHARACTER_EXPERIENCE_ITEM_ID,
    COMPANION_EXPERIENCE_ITEM_ID,
    COMPANION_SANCTUARY_ITEM_ID,
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


NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)


def main() -> None:
    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "growth.db",
            identity_secret="growth-items-secret",
        )
        services.database.initialize()
        character = _create_character(services)
        _grant_stack(services, character.id, "stack:character-exp", CHARACTER_EXPERIENCE_ITEM_ID, 2, "container.special")

        result = services.character_item_use.use(
            _character_command("character-exp-1", character.id, "stack:character-exp"),
            inventory_id=character.id,
            context=_context("character-exp-1"),
        ).unwrap()
        assert result.experience_granted == 1_000_000 or result.experience_granted > 0
        assert result.level_after >= result.level_before
        assert _quantity(services, character.id, "stack:character-exp") == 1

        _grant_stack(services, character.id, "stack:companion-key", COMPANION_SANCTUARY_ITEM_ID, 1, "container.special")
        _grant_stack(services, character.id, "stack:companion-exp", COMPANION_EXPERIENCE_ITEM_ID, 2, "container.special")
        overview = services.load_character_overview(character).overview
        assert overview is not None
        opened = services.companions.open_sanctuary(
            "growth-open",
            character,
            overview.character_world,
            "stack:companion-key",
            logical_time=NOW,
        )
        assert opened.status == "opened"
        hunted = services.companions.hunt("growth-hunt", character.id, 1, logical_time=NOW)
        assert hunted.status == "captured" and hunted.companion is not None
        assert hunted.companion.level == 1
        used = services.companions.use_experience_item(
            "companion-exp-1",
            character.id,
            "stack:companion-exp",
            hunted.companion.reference,
            logical_time=NOW,
        )
        assert used.status == "used" and used.receipt is not None
        assert 0 < used.receipt.experience_granted <= 30_000
        assert used.receipt.level_after > 1
        assert _quantity(services, character.id, "stack:companion-exp") == 1
        replay = services.companions.use_experience_item(
            "companion-exp-1",
            character.id,
            "stack:companion-exp",
            hunted.companion.reference,
            logical_time=NOW,
        )
        assert replay.replayed
        assert _quantity(services, character.id, "stack:companion-exp") == 1
    print("growth item tests passed")


def _create_character(services):
    evidence = IdentityEvidence(
        "growth-evidence",
        ExternalIdentity("platform.local", "growth", "identity.user", "private", "growth-user"),
        (),
        "message.local",
        NOW,
    )
    result = services.create_character(evidence, requested_name="成长测试")
    assert result.status == "created" and result.receipt is not None
    return result.receipt.character


def _grant_stack(services, character_id, asset_id, definition_id, quantity, kind):
    with services.database.unit_of_work() as uow:
        inventory = services.companions.snapshots.require(uow, INVENTORY_AGGREGATE, character_id, InventoryState)
        container = next(value for value in inventory.containers.values() if value.kind == kind)
        outcome = services.inventory_engine.execute(
            InventoryTransaction(
                "grant:" + asset_id,
                character_id,
                "test.growth",
                (GrantStack(asset_id, definition_id, container.id, quantity, SourceReceipt("receipt:" + asset_id, "source.test", asset_id, NOW)),),
            ),
            state=inventory,
            context=_context("grant:" + asset_id),
        )
        assert outcome.ok and outcome.value is not None
        services.companions.snapshots.update(uow, INVENTORY_AGGREGATE, character_id, inventory, outcome.value.state, NOW)
        uow.commit()


def _quantity(services, character_id, asset_id):
    with services.database.unit_of_work(write=False) as uow:
        inventory = services.companions.snapshots.require(uow, INVENTORY_AGGREGATE, character_id, InventoryState)
    return inventory.stacks[asset_id].quantity


def _character_command(transaction_id, character_id, item_asset_id):
    from game.core.gameplay import CharacterItemUseCommand

    return CharacterItemUseCommand(transaction_id, character_id, item_asset_id)


def _context(trace_id):
    return RuleContext(trace_id, "test.growth_items", Ruleset("ruleset.growth_items"), NOW, SeededRandomSource(trace_id))


if __name__ == "__main__":
    main()
