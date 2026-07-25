"""突破关隘、凭证消费、资源恢复和幂等联合事务测试。"""

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
    BREAKTHROUGH_TOKEN_ITEM_ID,
    CHARACTER_LEVEL_EXPERIENCE_REQUIREMENTS,
    CHARACTER_LEVEL_PROGRESSION_ID,
)
from game.core.account import ExternalIdentity, IdentityEvidence  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    ChangeCharacterResource,
    CharacterEngine,
    CharacterState,
    CharacterTransaction,
    GrantExperience,
    GrantStack,
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    InventoryState,
    InventoryTransaction,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    SourceReceipt,
    SPIRIT_CURRENT,
    SPIRIT_MAXIMUM,
)
from game.core.persistence import CHARACTER_AGGREGATE, INVENTORY_AGGREGATE  # noqa: E402


TIME = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


def main() -> None:
    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "breakthrough.db",
            identity_secret="breakthrough-feature-secret",
        )
        services.database.initialize()
        character = _create_character(services, "ready-player")
        _prepare_boundary(services, character.id, grant_token=True)
        before = _states(services, character.id)
        progression = before[0].progressions[CHARACTER_LEVEL_PROGRESSION_ID]
        assert (progression.level, progression.level_cap) == (10, 10)
        assert progression.experience == CHARACTER_LEVEL_EXPERIENCE_REQUIREMENTS[9]

        result = services.breakthrough.breakthrough(
            character.id,
            "breakthrough-operation",
            logical_time=TIME,
        )
        assert result.status == "broken_through" and result.receipt is not None
        assert (result.receipt.level_before, result.receipt.level_after) == (10, 11)
        assert (result.receipt.cap_before, result.receipt.cap_after) == (10, 20)
        progression = result.character.progressions[CHARACTER_LEVEL_PROGRESSION_ID]
        assert (progression.level, progression.level_cap, progression.experience) == (11, 20, 0)
        assert result.character.resources[HEALTH_CURRENT] == result.character.core_attributes[HEALTH_MAXIMUM]
        assert result.character.resources[SPIRIT_CURRENT] == result.character.core_attributes[SPIRIT_MAXIMUM]
        assert _token_count(services, character.id) == 0

        replay = services.breakthrough.breakthrough(
            character.id,
            "breakthrough-operation",
            logical_time=TIME,
        )
        assert replay.status == "replayed" and replay.receipt is not None
        assert replay.receipt.replayed
        assert _token_count(services, character.id) == 0

        missing = _create_character(services, "missing-player")
        _prepare_boundary(services, missing.id, grant_token=False)
        rejected = services.breakthrough.breakthrough(
            missing.id,
            "breakthrough-missing",
            logical_time=TIME,
        )
        assert rejected.status == "item_missing"
        assert rejected.character.progressions[CHARACTER_LEVEL_PROGRESSION_ID].level == 10

    print("breakthrough feature tests passed")


def _create_character(services, user_id: str):
    evidence = IdentityEvidence(
        f"evidence:{user_id}",
        ExternalIdentity("platform.local", user_id, "identity.user", "private", user_id),
        (),
        "message.local",
        TIME,
    )
    created = services.create_character(
        evidence,
        requested_name="缺契客" if user_id.startswith("missing") else "破境客",
    )
    assert created.status == "created" and created.receipt is not None
    return created.receipt.character


def _prepare_boundary(services, character_id: str, *, grant_token: bool) -> None:
    snapshots = services.breakthrough.snapshots
    with services.database.unit_of_work() as uow:
        character = snapshots.require(uow, CHARACTER_AGGREGATE, character_id, CharacterState)
        engine = CharacterEngine(services.content.catalog.characters)
        advanced = engine.execute(
            CharacterTransaction(
                f"prepare:{character_id}:experience",
                character_id,
                character.revision,
                "source.test",
                (
                    GrantExperience(
                        CHARACTER_LEVEL_PROGRESSION_ID,
                        sum(CHARACTER_LEVEL_EXPERIENCE_REQUIREMENTS[:10]),
                        "source.test",
                        "prepare-boundary",
                    ),
                ),
            ),
            state=character,
            context=_context(f"prepare:{character_id}:experience"),
        ).unwrap().state
        depleted = engine.execute(
            CharacterTransaction(
                f"prepare:{character_id}:resources",
                character_id,
                advanced.revision,
                "source.test",
                (
                    ChangeCharacterResource(
                        HEALTH_CURRENT,
                        -advanced.resources[HEALTH_CURRENT],
                        "source.test",
                        "prepare-boundary",
                    ),
                    ChangeCharacterResource(
                        SPIRIT_CURRENT,
                        -advanced.resources[SPIRIT_CURRENT],
                        "source.test",
                        "prepare-boundary",
                    ),
                ),
            ),
            state=advanced,
            context=_context(f"prepare:{character_id}:resources"),
        ).unwrap().state
        snapshots.update(uow, CHARACTER_AGGREGATE, character_id, character, advanced, TIME)
        snapshots.update(uow, CHARACTER_AGGREGATE, character_id, advanced, depleted, TIME)
        if grant_token:
            inventory = snapshots.require(uow, INVENTORY_AGGREGATE, character_id, InventoryState)
            container = next(value for value in inventory.containers.values() if value.kind == "container.special")
            granted = services.inventory_engine.execute(
                InventoryTransaction(
                    f"prepare:{character_id}:token",
                    character_id,
                    "source.test",
                    (
                        GrantStack(
                            f"stack:{character_id}:{BREAKTHROUGH_TOKEN_ITEM_ID}",
                            BREAKTHROUGH_TOKEN_ITEM_ID,
                            container.id,
                            1,
                            SourceReceipt(
                                f"receipt:{character_id}:token",
                                "source.test",
                                character_id,
                                TIME,
                            ),
                        ),
                    ),
                ),
                state=inventory,
                context=_context(f"prepare:{character_id}:token"),
            ).unwrap().state
            snapshots.update(uow, INVENTORY_AGGREGATE, character_id, inventory, granted, TIME)
        uow.commit()


def _states(services, character_id: str):
    with services.database.unit_of_work(write=False) as uow:
        return (
            services.breakthrough.snapshots.require(uow, CHARACTER_AGGREGATE, character_id, CharacterState),
            services.breakthrough.snapshots.require(uow, INVENTORY_AGGREGATE, character_id, InventoryState),
        )


def _token_count(services, character_id: str) -> int:
    inventory = _states(services, character_id)[1]
    return sum(
        value.quantity
        for value in inventory.stacks.values()
        if value.definition_id == BREAKTHROUGH_TOKEN_ITEM_ID
    )


def _context(seed: str) -> RuleContext:
    return RuleContext(
        seed,
        "rules.breakthrough_test.v1",
        Ruleset("ruleset.breakthrough_test"),
        TIME,
        SeededRandomSource(seed),
    )


if __name__ == "__main__":
    main()
