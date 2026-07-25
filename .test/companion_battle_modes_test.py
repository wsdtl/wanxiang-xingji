"""伙伴统一阵容投影接入探险、切磋和跨界灾厄的测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services  # noqa: E402
from game.content import CHARACTER_LEVEL_PROGRESSION_ID, COMPANION_SANCTUARY_ITEM_ID  # noqa: E402
from game.core.account import ExternalIdentity, IdentityEvidence  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    ENEMY_RANK_BOSS_ID,
    GrantStack,
    InventoryState,
    InventoryTransaction,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    SourceReceipt,
    TagSet,
)
from game.core.persistence import INVENTORY_AGGREGATE  # noqa: E402
from game.rules.companion import CompanionRosterState  # noqa: E402
from game.rules.disaster import DisasterCombatSnapshot  # noqa: E402


NOW = datetime(2026, 7, 20, 13, 0, tzinfo=timezone.utc)


def main() -> None:
    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "companion-battle-modes.db",
            identity_secret="companion-battle-modes-secret",
        )
        services.database.initialize()
        challenger = _create_character(services, "companion-battle-a", "驭灵者")
        defender = _create_character(services, "companion-battle-b", "守界人")
        _grant_key(services, challenger.id)
        overview = services.load_character_overview(challenger).overview
        defender_overview = services.load_character_overview(defender).overview
        assert overview is not None and defender_overview is not None

        opened = services.companions.open_sanctuary(
            "companion-battle-open",
            challenger,
            overview.character_world,
            "stack:companion-battle-key",
            logical_time=NOW,
        )
        assert opened.status == "opened"
        hunted = services.companions.hunt(
            "companion-battle-hunt",
            challenger.id,
            1,
            logical_time=NOW,
        )
        assert hunted.status == "captured" and hunted.companion is not None
        bound = services.companions.bind(
            "companion-battle-bind",
            challenger.id,
            hunted.companion.reference,
            allow_transfer=False,
            logical_time=NOW,
        )
        assert bound.status == "bound" and bound.roster is not None
        companion_id = hunted.companion.id

        _assert_exploration(services, challenger, overview, bound.roster, companion_id)
        _assert_sparring(
            services,
            challenger,
            overview,
            bound.roster,
            defender,
            defender_overview,
            companion_id,
        )
        _assert_disaster(services, challenger, overview, bound.roster, companion_id)
        person = services.content.companions.people_for_world(
            overview.character_world.world_id
        )[0]
        without_pet = services.companions.engine.farewell(bound.roster, companion_id)
        bonded, _, _ = services.companions.engine.give_gift(
            without_pet,
            person.id,
            person.bond_required,
            logical_time=NOW,
        )
        person_roster, person_instance, _ = services.companions.engine.join_person(
            bonded,
            person.id,
            1,
            logical_time=NOW,
        )
        person_roster = services.companions.engine.bind(
            person_roster,
            person_instance.id,
            overview.loadout.active_preset_id,
        )
        _assert_exploration(
            services,
            challenger,
            overview,
            person_roster,
            person_instance.id,
        )
    print("companion battle modes tests passed")


def _assert_exploration(services, character, overview, roster, companion_id) -> None:
    region = services.content.exploration_regions.definitions()[0]
    level = character.progressions[CHARACTER_LEVEL_PROGRESSION_ID].level
    plan = None
    for index in range(1, 100):
        candidate = services.exploration.settlement.planner.plan(
            session_id="companion-exploration",
            batch_index=index,
            region_id=region.id,
            world_id=overview.character_world.world_id,
            character_level=level,
            random=SeededRandomSource(f"companion-exploration:{index}"),
        )
        if candidate.encounter is not None:
            plan = candidate
            break
    assert plan is not None
    outcome = services.exploration.settlement.battles.simulate(
        plan,
        character=character,
        inventory=overview.inventory,
        loadout=overview.loadout,
        roster=roster,
        context=_context("companion-exploration-battle", "scene.exploration"),
    )
    assert outcome.player_companion_id == companion_id
    assert outcome.trace.initial_frame.state.participants[companion_id].team_id == "team.player"


def _assert_sparring(
    services,
    challenger,
    challenger_overview,
    challenger_roster,
    defender,
    defender_overview,
    companion_id,
) -> None:
    outcome = services.sparring.simulator.simulate(
        challenger,
        challenger_overview.inventory,
        challenger_overview.loadout,
        challenger_roster,
        defender,
        defender_overview.inventory,
        defender_overview.loadout,
        CompanionRosterState(defender.id),
        battle_id="battle:companion-sparring",
        context=_context("companion-sparring", "scene.sparring"),
    )
    assert outcome.challenger_companion_id == companion_id
    assert outcome.defender_companion_id is None
    assert outcome.trace.initial_frame.state.participants[companion_id].team_id == "team.challenger"


def _assert_disaster(services, character, overview, roster, companion_id) -> None:
    disaster = services.dimensional_disasters.disasters.definitions()[0]
    behavior_ids, phase_loadouts = (
        services.dimensional_disasters.enemy_loadouts.generate_loadout(
            disaster.enemy_definition_id,
            behavior_count=3,
            phase_health_ratios=(0.65, 0.30),
            behavior_weights=services.content.enemy_behavior_profiles.require(
                disaster.source_world_id
            ).behavior_weights,
            random=SeededRandomSource("companion-disaster-seed"),
        )
    )
    combat = DisasterCombatSnapshot(
        disaster.enemy_definition_id,
        1,
        ENEMY_RANK_BOSS_ID,
        behavior_ids,
        "companion-disaster-seed",
        services.content.catalog.report.content_fingerprint,
        phase_loadouts,
    )
    outcome = services.dimensional_disasters.battles.simulate(
        combat,
        "companion-disaster-event",
        character=character,
        inventory=overview.inventory,
        loadout=overview.loadout,
        roster=roster,
        context=_context("companion-disaster", "scene.dimensional_disaster"),
    )
    assert outcome.player_companion_id == companion_id
    assert outcome.trace.initial_frame.state.participants[companion_id].team_id == "team.player"


def _create_character(services, subject: str, name: str):
    evidence = IdentityEvidence(
        f"evidence:{subject}",
        ExternalIdentity(
            "platform.local",
            "companion-battle-modes",
            "identity.user",
            "private",
            subject,
        ),
        (),
        "message.local",
        NOW,
    )
    result = services.create_character(evidence, requested_name=name)
    assert result.status == "created" and result.receipt is not None
    return result.receipt.character


def _grant_key(services, character_id: str) -> None:
    with services.database.unit_of_work() as uow:
        inventory = services.companions.snapshots.require(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            InventoryState,
        )
        container = next(
            value for value in inventory.containers.values() if value.kind == "container.special"
        )
        context = _context("grant-companion-battle-key", "test.companion")
        outcome = services.inventory_engine.execute(
            InventoryTransaction(
                "grant-companion-battle-key",
                character_id,
                "test.grant",
                (
                    GrantStack(
                        "stack:companion-battle-key",
                        COMPANION_SANCTUARY_ITEM_ID,
                        container.id,
                        1,
                        SourceReceipt(
                            "grant-companion-battle-key",
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
        services.companions.snapshots.update(
            uow,
            INVENTORY_AGGREGATE,
            character_id,
            inventory,
            outcome.value.state,
            NOW,
        )
        uow.commit()


def _context(trace_id: str, scene: str) -> RuleContext:
    return RuleContext(
        trace_id,
        "test.companion.battle_modes.v1",
        Ruleset(f"ruleset.{scene}", TagSet.of(scene)),
        NOW,
        SeededRandomSource(trace_id),
    )


if __name__ == "__main__":
    main()
