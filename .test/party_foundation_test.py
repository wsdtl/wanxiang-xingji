"""队伍规则、战斗阵营投影、持久化与邀请联合事务测试。"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay import (  # noqa: E402
    PARTY_FOUNDATION_VERSION,
    AddPartyMember,
    CreateParty,
    CreateSocialRequest,
    DisbandParty,
    LeaveParty,
    PartyAdmissionCommand,
    PartyBattleProjector,
    PartyCatalog,
    PartyCommand,
    PartyDefinition,
    PartyEngine,
    PartyState,
    PartyStatus,
    party_invitation_metadata,
    RemovePartyMember,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    SetPartyMemberReady,
    SetPartyMemberSlot,
    SocialCatalog,
    SocialCommand,
    SocialEngine,
    SocialRequest,
    SocialRequestDefinition,
    SocialRequestStatus,
    TransferPartyLeadership,
)
from game.core.persistence import (  # noqa: E402
    PersistedPartyAdmissionService,
    PersistedPartyService,
    PersistedSocialService,
    SqliteDatabase,
)


TIME = datetime(2026, 7, 14, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
INVITATION_KIND = "social_request.party_invitation"


def main() -> None:
    _assert_party_rules_and_battle_projection()
    _assert_persistence_and_atomic_invitation()
    _assert_independent_party_shards_and_membership_guard()
    print("party foundation tests passed")


def _context(seed: int, *, seconds: int = 0) -> RuleContext:
    return RuleContext(
        f"party-test-{seed}",
        "rules.party_v1",
        Ruleset("ruleset.party_test"),
        TIME + timedelta(seconds=seconds),
        SeededRandomSource(seed),
    )


def _catalog(*definitions: PartyDefinition) -> PartyCatalog:
    catalog = PartyCatalog()
    for definition in definitions:
        catalog.register(definition)
    catalog.finalize()
    return catalog


def _execute(engine, state, operation, actor, command_id, seed):
    return engine.execute(
        PartyCommand(command_id, actor, state.revision, operation),
        state=state,
        context=_context(seed, seconds=seed),
    )


def _assert_party_rules_and_battle_projection() -> None:
    assert PARTY_FOUNDATION_VERSION == "party.foundation.v1"
    engine = PartyEngine(_catalog(PartyDefinition("party_type.trio", 3)))
    state = PartyState("party-scope")

    created = _execute(
        engine,
        state,
        CreateParty("party-a", "party_type.trio"),
        "player-a",
        "party-create-a",
        1,
    ).unwrap()
    state = created.state
    assert created.party.leader_id == "player-a"
    assert created.party.members["player-a"].slot == 0

    joined = _execute(
        engine,
        state,
        AddPartyMember("party-a", "player-b"),
        "player-a",
        "party-add-b",
        2,
    ).unwrap()
    state = joined.state
    for actor, seed in (("player-a", 3), ("player-b", 4)):
        ready = _execute(
            engine,
            state,
            SetPartyMemberReady("party-a", True),
            actor,
            f"party-ready-{actor}",
            seed,
        ).unwrap()
        state = ready.state

    participants = PartyBattleProjector().participants(
        state.parties["party-a"],
        require_all_ready=True,
    )
    assert len(participants) == 2
    assert len({value.team_id for value in participants}) == 1
    assert [value.slot for value in participants] == [0, 1]

    joined_c = _execute(
        engine,
        state,
        AddPartyMember("party-a", "player-c"),
        "player-a",
        "party-add-c",
        5,
    ).unwrap()
    state = joined_c.state
    assert not any(value.ready for value in joined_c.party.members.values())
    full = _execute(
        engine,
        state,
        AddPartyMember("party-a", "player-d"),
        "player-a",
        "party-add-d",
        6,
    )
    assert full.failure and full.failure.code == "party.capacity_reached"
    assert state.revision == joined_c.state.revision

    created_d = _execute(
        engine,
        state,
        CreateParty("party-d", "party_type.trio"),
        "player-d",
        "party-create-d",
        7,
    ).unwrap()
    state = created_d.state
    duplicate = _execute(
        engine,
        state,
        AddPartyMember("party-d", "player-b"),
        "player-d",
        "party-duplicate-b",
        8,
    )
    assert duplicate.failure and duplicate.failure.code == "party.exclusive_membership"
    unauthorized = _execute(
        engine,
        state,
        RemovePartyMember("party-a", "player-c"),
        "player-b",
        "party-unauthorized-remove",
        9,
    )
    assert unauthorized.failure and unauthorized.failure.code == "party.permission_denied"

    swapped = _execute(
        engine,
        state,
        SetPartyMemberSlot("party-a", "player-c", 0),
        "player-a",
        "party-swap-slot",
        10,
    ).unwrap()
    state = swapped.state
    assert swapped.party.members["player-c"].slot == 0
    assert swapped.party.members["player-a"].slot == 2
    leader_leave = _execute(
        engine,
        state,
        LeaveParty("party-a"),
        "player-a",
        "party-leader-leave",
        11,
    )
    assert leader_leave.failure and leader_leave.failure.code == "party.leader_must_transfer"

    transferred = _execute(
        engine,
        state,
        TransferPartyLeadership("party-a", "player-b"),
        "player-a",
        "party-transfer",
        12,
    ).unwrap()
    state = transferred.state
    left = _execute(
        engine,
        state,
        LeaveParty("party-a"),
        "player-a",
        "party-leave-a",
        13,
    ).unwrap()
    state = left.state
    assert set(left.party.members) == {"player-b", "player-c"}
    disbanded = _execute(
        engine,
        state,
        DisbandParty("party-a"),
        "player-b",
        "party-disband-a",
        14,
    ).unwrap()
    assert disbanded.party.status is PartyStatus.DISBANDED
    try:
        PartyBattleProjector().participants(disbanded.party)
        raise AssertionError("已解散队伍不能投影到战斗")
    except ValueError:
        pass


def _assert_persistence_and_atomic_invitation() -> None:
    party_catalog = _catalog(PartyDefinition("party_type.pair", 2))
    party_engine = PartyEngine(party_catalog)
    social_catalog = SocialCatalog()
    social_catalog.requests.register(SocialRequestDefinition(INVITATION_KIND, 300))
    social_catalog.finalize()
    social_engine = SocialEngine(social_catalog)

    with TemporaryDirectory() as directory:
        database = SqliteDatabase(Path(directory) / "party.db")
        database.initialize()
        parties = PersistedPartyService(database, party_engine)
        social = PersistedSocialService(database, social_engine)
        admissions = PersistedPartyAdmissionService(
            database,
            social_engine,
            party_engine,
        )
        party_state = parties.initialize("party-scope", logical_time=TIME)
        social_state = social.initialize("social-scope", logical_time=TIME)
        created = parties.execute(
            "party-scope",
            PartyCommand(
                "persist-party-create",
                "leader",
                party_state.revision,
                CreateParty("party-pair", "party_type.pair"),
            ),
            context=_context(20, seconds=20),
        ).unwrap()
        party_state = created.execution.state

        invitation = SocialRequest(
            "party-invite-1",
            INVITATION_KIND,
            "leader",
            "member-a",
            TIME + timedelta(seconds=30),
            TIME + timedelta(seconds=300),
            metadata=party_invitation_metadata("party-pair"),
        )
        invited = social.execute(
            "social-scope",
            SocialCommand(
                "persist-party-invite",
                "leader",
                social_state.revision,
                CreateSocialRequest(invitation),
            ),
            context=_context(30, seconds=30),
        ).unwrap()
        social_state = invited.execution.state

        admission = PartyAdmissionCommand(
            "persist-party-admission",
            "member-a",
            "social-scope",
            "party-scope",
            invitation.id,
            INVITATION_KIND,
            "party-pair",
            social_state.revision,
            party_state.revision,
        )
        accepted = admissions.execute(
            admission,
            context=_context(40, seconds=40),
        ).unwrap()
        assert accepted.execution.social.state.requests[invitation.id].status is SocialRequestStatus.ACCEPTED
        assert "member-a" in accepted.execution.party.party.members
        replay = admissions.execute(
            admission,
            context=_context(41, seconds=41),
        ).unwrap()
        assert replay.replayed and replay.execution == accepted.execution

        social_state = social.load("social-scope")
        party_state = parties.load("party-scope")
        assert social_state is not None and party_state is not None
        second = SocialRequest(
            "party-invite-2",
            INVITATION_KIND,
            "leader",
            "member-b",
            TIME + timedelta(seconds=50),
            TIME + timedelta(seconds=300),
            metadata=party_invitation_metadata("party-pair"),
        )
        invited_second = social.execute(
            "social-scope",
            SocialCommand(
                "persist-party-invite-2",
                "leader",
                social_state.revision,
                CreateSocialRequest(second),
            ),
            context=_context(50, seconds=50),
        ).unwrap()
        social_before = invited_second.execution.state
        party_before = party_state
        rejected = admissions.execute(
            PartyAdmissionCommand(
                "persist-party-admission-full",
                "member-b",
                "social-scope",
                "party-scope",
                second.id,
                INVITATION_KIND,
                "party-pair",
                social_before.revision,
                party_before.revision,
            ),
            context=_context(60, seconds=60),
        )
        assert rejected.failure and rejected.failure.code == "party.capacity_reached"
        social_after = social.load("social-scope")
        party_after = parties.load("party-scope")
        assert social_after == social_before
        assert party_after == party_before
        assert social_after.requests[second.id].status is SocialRequestStatus.PENDING


def _assert_independent_party_shards_and_membership_guard() -> None:
    engine = PartyEngine(_catalog(PartyDefinition("party_type.pair", 2)))
    with TemporaryDirectory() as directory:
        database = SqliteDatabase(Path(directory) / "party-shards.db")
        database.initialize()
        parties = PersistedPartyService(database, engine)
        created_a = parties.execute(
            "party-a",
            PartyCommand(
                "create-party-a",
                "leader-a",
                0,
                CreateParty("party-a", "party_type.pair"),
            ),
            context=_context(101, seconds=101),
        ).unwrap()
        created_b = parties.execute(
            "party-b",
            PartyCommand(
                "create-party-b",
                "leader-b",
                0,
                CreateParty("party-b", "party_type.pair"),
            ),
            context=_context(102, seconds=102),
        ).unwrap()
        before_b = parties.load("party-b")
        ready_a = parties.execute(
            "party-a",
            PartyCommand(
                "ready-party-a",
                "leader-a",
                created_a.execution.state.revision,
                SetPartyMemberReady("party-a", True),
            ),
            context=_context(103, seconds=103),
        ).unwrap()
        assert ready_a.execution.state.revision == 2
        assert parties.load("party-b") == before_b
        ready_b = parties.execute(
            "party-b",
            PartyCommand(
                "ready-party-b",
                "leader-b",
                created_b.execution.state.revision,
                SetPartyMemberReady("party-b", True),
            ),
            context=_context(104, seconds=104),
        ).unwrap()
        assert ready_b.execution.state.revision == 2

        duplicate = parties.execute(
            "party-c",
            PartyCommand(
                "duplicate-party-membership",
                "leader-a",
                0,
                CreateParty("party-c", "party_type.pair"),
            ),
            context=_context(105, seconds=105),
        )
        assert duplicate.failure
        assert duplicate.failure.code == "party.exclusive_membership"
        assert parties.load("party-c") is None

        disband_time = TIME + timedelta(seconds=106)
        disbanded = parties.execute(
            "party-a",
            PartyCommand(
                "disband-party-a",
                "leader-a",
                ready_a.execution.state.revision,
                DisbandParty("party-a"),
            ),
            context=_context(106, seconds=106),
        ).unwrap()
        assert disbanded.execution.party.status is PartyStatus.DISBANDED
        with database.unit_of_work(write=False) as uow:
            row = uow.require_snapshot("snapshot.party", "party-a")
            assert row.expires_at == (disband_time + timedelta(hours=6)).isoformat()
            assert uow.load_party_membership("leader-a") is None
            membership_b = uow.load_party_membership("leader-b")
            assert membership_b is not None and membership_b.party_id == "party-b"


if __name__ == "__main__":
    main()
