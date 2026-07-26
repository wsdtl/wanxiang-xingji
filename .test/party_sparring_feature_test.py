"""Party sparring sizes, authority, invalidation, reports, and lossless state."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
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
    CharacterState,
    GrantStack,
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    InventoryState,
    InventoryTransaction,
    LoadoutState,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    SourceReceipt,
    SPIRIT_CURRENT,
    SPIRIT_MAXIMUM,
    TagSet,
)
from game.rules.character import CharacterWorldState  # noqa: E402
from game.rules.companion import CompanionRosterState  # noqa: E402


def main() -> None:
    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "party-sparring.db",
            identity_secret="party-sparring-feature-secret",
        )
        services.database.initialize()
        now = datetime(2026, 7, 23, 8, 0, tzinfo=timezone.utc)
        sequence = 0

        for challenger_size, defender_size in ((1, 1), (1, 3), (2, 3), (3, 3)):
            sequence += 1
            challenger_members = tuple(
                _create_character(
                    services,
                    f"spar-{sequence}-a-{index}",
                    f"甲{sequence}{index}",
                    now,
                )
                for index in range(challenger_size)
            )
            defender_members = tuple(
                _create_character(
                    services,
                    f"spar-{sequence}-b-{index}",
                    f"乙{sequence}{index}",
                    now,
                )
                for index in range(defender_size)
            )
            _create_party(
                services,
                f"spar-{sequence}-a",
                challenger_members,
                now,
            )
            _create_party(
                services,
                f"spar-{sequence}-b",
                defender_members,
                now,
            )
            leader = challenger_members[0]
            defender_leader = defender_members[0]
            target = defender_members[-1]

            nonleader = challenger_members[-1]
            if nonleader.id != leader.id:
                denied = services.party_sparring.create_request(
                    f"spar-{sequence}-nonleader",
                    nonleader.id,
                    target.id,
                    logical_time=now,
                )
                assert denied.status == "unavailable"
                assert "只有队长" in denied.failure_message
            same_party_target = challenger_members[-1]
            same_party = services.party_sparring.create_request(
                f"spar-{sequence}-same",
                leader.id,
                same_party_target.id,
                logical_time=now,
            )
            assert same_party.status == "unavailable"
            assert "自己的队伍" in same_party.failure_message

            requested = services.party_sparring.create_request(
                f"spar-{sequence}-request",
                leader.id,
                target.id,
                logical_time=now,
            )
            assert requested.status == "created" and requested.request is not None
            assert requested.request.recipient_id == defender_leader.id
            duplicate = services.party_sparring.create_request(
                f"spar-{sequence}-duplicate",
                leader.id,
                defender_leader.id,
                logical_time=now,
            )
            assert duplicate.status == "already_pending"
            assert duplicate.request is not None
            assert duplicate.request.id == requested.request.id

            if len(defender_members) > 1:
                forbidden = services.party_sparring.accept_request(
                    f"spar-{sequence}-forbidden",
                    requested.request.id,
                    defender_members[-1].id,
                    logical_time=now,
                )
                assert forbidden.status == "forbidden"

            all_characters = (*challenger_members, *defender_members)
            companion_id = None
            if (challenger_size, defender_size) == (2, 3):
                companion_id = _bind_companion(services, challenger_members[0], now)
                _activate_empty_preset(services, challenger_members[-1].id, now)
                _move_to_other_world(services, defender_members[-1].id, now)
            for character in all_characters:
                _set_resources(services, character, health=0, spirit=0, now=now)
            before = _lossless_snapshots(services, all_characters)
            party_before = _party_state_payload(services)
            accepted = services.party_sparring.accept_request(
                f"spar-{sequence}-accept",
                requested.request.id,
                defender_leader.id,
                logical_time=now,
            )
            assert accepted.status == "accepted"
            assert accepted.report is not None
            assert accepted.challenger_party is not None
            assert accepted.defender_party is not None
            assert len(accepted.challenger_party.members) == challenger_size
            assert len(accepted.defender_party.members) == defender_size
            assert accepted.turns > 0
            assert _lossless_snapshots(services, all_characters) == before
            assert _party_state_payload(services) == party_before

            report = services.battle_reports.load_public(
                accepted.report.share_id,
                logical_time=now,
            )
            assert report is not None and report.detail_available
            assert report.mode_id == "battle.mode.party_sparring"
            assert len(report.segments) == 1
            segment = report.segments[0]
            assert len(segment.combatants) == (
                challenger_size + defender_size + (1 if companion_id else 0)
            )
            assert segment.events
            assert segment.transitions
            assert segment.initial_participants
            for participant in segment.initial_participants:
                assert (
                    participant.resources[HEALTH_CURRENT]
                    == participant.attributes[HEALTH_MAXIMUM]
                )
                assert (
                    participant.resources[SPIRIT_CURRENT]
                    == participant.attributes[SPIRIT_MAXIMUM]
                )
            assert all(value.after.participants for value in segment.transitions)
            character_projections = {
                value.label: value.projection_id
                for value in segment.combatants
                if value.unit_kind == "character"
            }
            assert character_projections == {
                character.name: str(before[character.id]["world"].world_id)
                for character in all_characters
            }

            replayed = services.party_sparring.accept_request(
                f"spar-{sequence}-replay",
                requested.request.id,
                defender_leader.id,
                logical_time=now,
            )
            assert replayed.status == "replayed"
            assert replayed.report == accepted.report
            assert _lossless_snapshots(services, all_characters) == before

        _assert_expiry_and_party_change(services, now)
        _assert_rejection(services, now)
    print("party sparring feature tests passed")


def _assert_expiry_and_party_change(services, now):
    members = tuple(
        _create_character(services, f"edge-{index}", f"边界{index}", now)
        for index in range(3)
    )
    first = _create_party(services, "edge-a", (members[0],), now)
    second = _create_party(services, "edge-b", (members[1],), now)
    request = services.party_sparring.create_request(
        "edge-expiry",
        first.leader_id,
        second.leader_id,
        logical_time=now,
    )
    assert request.request is not None
    expired = services.party_sparring.accept_request(
        "edge-expiry-accept",
        request.request.id,
        second.leader_id,
        logical_time=now + timedelta(minutes=10),
    )
    assert expired.status == "expired"

    fresh = services.party_sparring.create_request(
        "edge-party-change",
        first.leader_id,
        second.leader_id,
        logical_time=now + timedelta(minutes=10),
    )
    assert fresh.status == "created" and fresh.request is not None
    invited = services.party.invite(
        "edge-add-invite",
        second.leader_id,
        members[2].id,
        logical_time=now + timedelta(minutes=10),
    )
    assert invited.request is not None
    joined = services.party.accept(
        "edge-add-accept",
        members[2].id,
        invited.request.id,
        logical_time=now + timedelta(minutes=10),
    )
    assert joined.status == "accepted"
    changed = services.party_sparring.accept_request(
        "edge-party-change-accept",
        fresh.request.id,
        second.leader_id,
        logical_time=now + timedelta(minutes=10),
    )
    assert changed.status == "party_changed"


def _assert_rejection(services, now):
    left = _create_character(services, "reject-a", "拒绝甲", now)
    right = _create_character(services, "reject-b", "拒绝乙", now)
    left_party = _create_party(services, "reject-a", (left,), now)
    right_party = _create_party(services, "reject-b", (right,), now)
    requested = services.party_sparring.create_request(
        "reject-request",
        left_party.leader_id,
        right_party.leader_id,
        logical_time=now,
    )
    assert requested.request is not None
    rejected = services.party_sparring.reject_request(
        "reject-resolve",
        requested.request.id,
        right_party.leader_id,
        logical_time=now,
    )
    assert rejected.status == "rejected"
    terminal = services.party_sparring.accept_request(
        "reject-after",
        requested.request.id,
        right_party.leader_id,
        logical_time=now,
    )
    assert terminal.status == "terminal"


def _create_character(services, subject: str, name: str, now: datetime):
    evidence = IdentityEvidence(
        f"evidence:{subject}",
        ExternalIdentity(
            "platform.local",
            "party-sparring",
            "identity.user",
            "private",
            subject,
        ),
        (),
        "message.local",
        now,
    )
    result = services.create_character(evidence, requested_name=name)
    assert result.status == "created" and result.receipt is not None
    return result.receipt.character


def _create_party(services, prefix: str, members, now: datetime):
    created = services.party.create(f"{prefix}:create", members[0].id, logical_time=now)
    assert created.status == "created" and created.party is not None
    party = created.party
    for index, member in enumerate(members[1:], start=1):
        invited = services.party.invite(
            f"{prefix}:invite:{index}",
            members[0].id,
            member.id,
            logical_time=now,
        )
        assert invited.request is not None
        accepted = services.party.accept(
            f"{prefix}:accept:{index}",
            member.id,
            invited.request.id,
            logical_time=now,
        )
        assert accepted.status == "accepted" and accepted.party is not None
        party = accepted.party
    return party


def _activate_empty_preset(services, character_id: str, now: datetime) -> None:
    storage = services.party_sparring.storage
    with services.database.unit_of_work() as uow:
        loadout = services.party_sparring.snapshots.require(
            uow,
            storage.loadout,
            character_id,
            LoadoutState,
        )
        target_id = next(
            key
            for key, preset in loadout.presets.items()
            if key != loadout.active_preset_id and not preset.slots
        )
        updated = replace(
            loadout,
            slots=loadout.presets[target_id].slots,
            active_preset_id=target_id,
            revision=loadout.revision + 1,
        )
        services.party_sparring.snapshots.update(
            uow,
            storage.loadout,
            character_id,
            loadout,
            updated,
            now,
        )
        uow.commit()


def _bind_companion(services, character, now: datetime) -> str:
    storage = services.party_sparring.storage
    stack_id = f"stack:party-sparring-key:{character.id}"
    with services.database.unit_of_work() as uow:
        inventory = services.party_sparring.snapshots.require(
            uow,
            storage.inventory,
            character.id,
            InventoryState,
        )
        container = next(
            value
            for value in inventory.containers.values()
            if value.kind == "container.special"
        )
        context = RuleContext(
            f"grant-party-sparring-key:{character.id}",
            "test.party_sparring.v1",
            Ruleset("ruleset.test.party_sparring", TagSet.of("test.party_sparring")),
            now,
            SeededRandomSource(f"grant-party-sparring-key:{character.id}"),
        )
        outcome = services.inventory_engine.execute(
            InventoryTransaction(
                f"grant-party-sparring-key:{character.id}",
                character.id,
                "test.grant",
                (
                    GrantStack(
                        stack_id,
                        COMPANION_SANCTUARY_ITEM_ID,
                        container.id,
                        1,
                        SourceReceipt(
                            f"grant-party-sparring-key:{character.id}",
                            "source.test",
                            "party-sparring-key",
                            now,
                        ),
                    ),
                ),
            ),
            state=inventory,
            context=context,
        )
        assert outcome.ok and outcome.value is not None
        services.party_sparring.snapshots.update(
            uow,
            storage.inventory,
            character.id,
            inventory,
            outcome.value.state,
            now,
        )
        uow.commit()
    overview = services.load_character_overview(character).overview
    assert overview is not None
    opened = services.companions.open_sanctuary(
        f"party-sparring-open:{character.id}",
        character,
        overview.character_world,
        stack_id,
        logical_time=now,
    )
    assert opened.status == "opened"
    hunted = services.companions.hunt(
        f"party-sparring-hunt:{character.id}",
        character.id,
        1,
        logical_time=now,
    )
    assert hunted.status == "captured" and hunted.companion is not None
    bound = services.companions.bind(
        f"party-sparring-bind:{character.id}",
        character.id,
        hunted.companion.reference,
        allow_transfer=False,
        logical_time=now,
    )
    assert bound.status == "bound"
    return hunted.companion.id


def _move_to_other_world(services, character_id: str, now: datetime) -> None:
    storage = services.party_sparring.storage
    with services.database.unit_of_work() as uow:
        current = services.party_sparring.snapshots.require(
            uow,
            storage.character_world,
            character_id,
            CharacterWorldState,
        )
        target = next(
            value
            for value in services.content.worlds.world_ids()
            if value != current.world_id
        )
        updated = replace(
            current,
            world_id=target,
            arrived_at=now,
            revision=current.revision + 1,
        )
        services.party_sparring.snapshots.update(
            uow,
            storage.character_world,
            character_id,
            current,
            updated,
            now,
        )
        uow.commit()


def _set_resources(
    services,
    character,
    *,
    health: float,
    spirit: float,
    now: datetime,
) -> None:
    storage = services.party_sparring.storage
    with services.database.unit_of_work() as uow:
        current = services.party_sparring.snapshots.require(
            uow,
            storage.character,
            character.id,
            CharacterState,
        )
        resources = dict(current.resources)
        resources[HEALTH_CURRENT] = health
        resources[SPIRIT_CURRENT] = spirit
        updated = replace(
            current,
            resources=resources,
            revision=current.revision + 1,
        )
        services.party_sparring.snapshots.update(
            uow,
            storage.character,
            character.id,
            current,
            updated,
            now,
        )
        uow.commit()


def _lossless_snapshots(services, characters):
    storage = services.party_sparring.storage
    kinds = (
        ("character", storage.character, CharacterState),
        ("inventory", storage.inventory, InventoryState),
        ("loadout", storage.loadout, LoadoutState),
        ("roster", storage.companion_roster, CompanionRosterState),
        ("world", storage.character_world, CharacterWorldState),
    )
    result = {}
    with services.database.unit_of_work(write=False) as uow:
        for character in characters:
            values = {}
            for label, aggregate, expected in kinds:
                values[label] = services.party_sparring.snapshots.load(
                    uow,
                    aggregate,
                    character.id,
                    expected,
                )
            result[character.id] = values
    return result


def _party_state_payload(services):
    storage = services.party_sparring.storage
    with services.database.unit_of_work(write=False) as uow:
        rows = uow.connection.execute(
            """
            SELECT aggregate_id, revision, payload, expires_at
            FROM aggregate_snapshot
            WHERE aggregate_kind = ?
            ORDER BY aggregate_id
            """,
            (storage.party,),
        ).fetchall()
    return tuple(tuple(row) for row in rows)


if __name__ == "__main__":
    main()
