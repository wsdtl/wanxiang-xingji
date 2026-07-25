"""宠物捕获、人物结交、通用名册与告别事务测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services  # noqa: E402
from game.content import COMPANION_SANCTUARY_ITEM_ID  # noqa: E402
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


NOW = datetime(2026, 7, 20, 13, 0, tzinfo=timezone.utc)


def main() -> None:
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "companion.db"
        services = build_game_services(
            database_path=database_path,
            identity_secret="companion-feature-secret",
        )
        services.database.initialize()
        character = _create_character(services)
        _grant_key(services, character.id, 2)
        overview = services.load_character_overview(character).overview
        assert overview is not None

        opened = services.companions.open_sanctuary(
            "companion-open-1",
            character,
            overview.character_world,
            "stack:companion-key",
            logical_time=NOW,
        )
        assert opened.status == "opened"
        assert opened.sanctuary is not None
        traces = opened.sanctuary.traces
        assert _key_quantity(services, character.id) == 1

        replayed = services.companions.open_sanctuary(
            "companion-open-1",
            character,
            overview.character_world,
            "stack:companion-key",
            logical_time=NOW,
        )
        assert replayed.status == "opened" and replayed.replayed
        assert replayed.sanctuary is not None
        assert replayed.sanctuary.traces == traces
        assert _key_quantity(services, character.id) == 1

        reloaded = build_game_services(
            database_path=database_path,
            identity_secret="companion-feature-secret",
        )
        reloaded.database.initialize()
        restored = reloaded.companions.view(character.id, logical_time=NOW)
        assert restored.sanctuary is not None
        assert restored.sanctuary.traces == traces

        hunted = reloaded.companions.hunt(
            "companion-hunt-1",
            character.id,
            1,
            logical_time=NOW,
        )
        assert hunted.status == "captured", hunted.failure_message
        assert hunted.companion is not None
        assert hunted.battle_report is not None
        assert hunted.roster is not None and len(hunted.roster.instances) == 1
        captured_reference = hunted.companion.reference

        hunt_replay = reloaded.companions.hunt(
            "companion-hunt-1",
            character.id,
            1,
            logical_time=NOW,
        )
        assert hunt_replay.status == "captured" and hunt_replay.replayed
        assert hunt_replay.companion is not None
        assert hunt_replay.companion.reference == captured_reference

        bound = reloaded.companions.bind(
            "companion-bind-1",
            character.id,
            captured_reference,
            allow_transfer=False,
            logical_time=NOW,
        )
        assert bound.status == "bound"
        assert bound.roster is not None
        assert bound.roster.bindings

        released = reloaded.companions.farewell(
            "companion-farewell-1",
            character.id,
            captured_reference,
            bound.roster.revision,
            logical_time=NOW,
        )
        assert released.status == "pet_departed"
        assert released.roster is not None
        assert not released.roster.instances
        assert not released.roster.bindings
        assert hunted.companion.definition_id in released.roster.captured_definition_ids

        person = reloaded.content.companions.people_for_world(overview.character_world.world_id)[0]
        gift_item_id = next(iter(person.gift_values))
        gift_asset_id = _grant_gift(reloaded, character.id, gift_item_id, 10)
        moved = reloaded.world_travel.move(
            character.id,
            reloaded.content.worlds.require_binding_for_display(
                overview.character_world.world_id,
                person.location_id,
            ).anchor_id,
            logical_time=NOW,
        )
        assert moved.status == "moved"
        gifted = reloaded.companions.gift_person(
            "companion-person-gift-1",
            character.id,
            gift_asset_id,
            10,
            logical_time=NOW,
        )
        assert gifted.status == "gifted", gifted.failure_message
        assert gifted.value_after == person.bond_required
        assert gifted.quantity < 10
        joined = reloaded.companions.join_person(
            "companion-person-join-1",
            character.id,
            logical_time=NOW,
        )
        assert joined.status == "joined" and joined.companion is not None
        assert joined.companion.definition_id == person.id
        departed = reloaded.companions.farewell(
            "companion-person-farewell-1",
            character.id,
            joined.companion.reference,
            joined.roster.revision,
            logical_time=NOW,
        )
        assert departed.status == "person_departed"
        assert departed.roster is not None
        assert person.id in departed.roster.departed_people
        rejoined = reloaded.companions.join_person(
            "companion-person-rejoin-1",
            character.id,
            logical_time=NOW,
        )
        assert rejoined.status == "rejoined"
        assert rejoined.companion == joined.companion
    print("companion feature tests passed")


def _create_character(services):
    evidence = IdentityEvidence(
        "evidence:companion-feature",
        ExternalIdentity(
            "platform.local",
            "companion-feature",
            "identity.user",
            "private",
            "companion-feature-user",
        ),
        (),
        "message.local",
        NOW,
    )
    result = services.create_character(evidence, requested_name="万灵客")
    assert result.status == "created" and result.receipt is not None
    return result.receipt.character


def _grant_key(services, character_id: str, quantity: int) -> None:
    snapshots = services.companions.snapshots
    with services.database.unit_of_work() as uow:
        inventory = snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            InventoryState,
        )
        container = next(
            value for value in inventory.containers.values() if value.kind == "container.special"
        )
        context = RuleContext(
            "grant-companion-key",
            "test.companion.v1",
            Ruleset("ruleset.test.companion"),
            NOW,
            SeededRandomSource("grant-companion-key"),
        )
        outcome = services.inventory_engine.execute(
            InventoryTransaction(
                "grant-companion-key",
                character_id,
                "test.grant",
                (
                    GrantStack(
                        "stack:companion-key",
                        COMPANION_SANCTUARY_ITEM_ID,
                        container.id,
                        quantity,
                        SourceReceipt(
                            "grant-companion-key",
                            "source.test",
                            "companion-key",
                            NOW,
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
            NOW,
        )
        uow.commit()


def _key_quantity(services, character_id: str) -> int:
    with services.database.unit_of_work(write=False) as uow:
        inventory = services.companions.snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            InventoryState,
        )
    return inventory.stacks["stack:companion-key"].quantity


def _grant_gift(services, character_id: str, definition_id: str, quantity: int) -> str:
    asset_id = "stack:companion-gift"
    snapshots = services.companions.snapshots
    with services.database.unit_of_work() as uow:
        inventory = snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            InventoryState,
        )
        container = next(
            value for value in inventory.containers.values()
            if value.kind == "container.backpack"
        )
        context = RuleContext(
            "grant-companion-gift",
            "test.companion.v2",
            Ruleset("ruleset.test.companion.gift"),
            NOW,
            SeededRandomSource("grant-companion-gift"),
        )
        outcome = services.inventory_engine.execute(
            InventoryTransaction(
                "grant-companion-gift",
                character_id,
                "test.grant",
                (
                    GrantStack(
                        asset_id,
                        definition_id,
                        container.id,
                        quantity,
                        SourceReceipt(
                            "grant-companion-gift",
                            "source.test",
                            "companion-gift",
                            NOW,
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
            NOW,
        )
        uow.commit()
    return asset_id


if __name__ == "__main__":
    main()
