"""正式队伍业务的邀请、成员、准备和持久化测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services  # noqa: E402
from game.core.account import ExternalIdentity, IdentityEvidence  # noqa: E402


NOW = datetime(2026, 7, 20, 16, 0, tzinfo=timezone.utc)


def main() -> None:
    with TemporaryDirectory() as directory:
        database_path = Path(directory) / "party-feature.db"
        services = build_game_services(
            database_path=database_path,
            identity_secret="party-feature-secret",
        )
        services.database.initialize()
        leader = _create_character(services, "party-leader", "领队")
        member = _create_character(services, "party-member", "前锋")
        third = _create_character(services, "party-third", "策应")
        outsider = _create_character(services, "party-outsider", "候补")

        assert services.party.view(leader.id, logical_time=NOW).party is None
        created = services.party.create("party-create", leader.id, logical_time=NOW)
        assert created.status == "created" and created.party is not None
        assert created.party.leader_id == leader.id

        invitation = services.party.invite(
            "party-invite-member",
            leader.id,
            member.id,
            logical_time=NOW,
        )
        assert invitation.status == "invited" and invitation.request is not None
        pending = services.party.view(member.id, logical_time=NOW)
        assert pending.incoming_requests == (invitation.request,)

        forbidden = services.party.accept(
            "party-accept-forbidden",
            outsider.id,
            invitation.request.id,
            logical_time=NOW,
        )
        assert forbidden.status == "failed"
        accepted = services.party.accept(
            "party-accept-member",
            member.id,
            invitation.request.id,
            logical_time=NOW,
        )
        assert accepted.status == "accepted" and accepted.party is not None
        assert set(accepted.party.members) == {leader.id, member.id}

        ready_leader = services.party.set_ready(
            "party-ready-leader",
            leader.id,
            True,
            logical_time=NOW,
        )
        ready_member = services.party.set_ready(
            "party-ready-member",
            member.id,
            True,
            logical_time=NOW,
        )
        assert ready_leader.status == "member.ready_changed"
        assert ready_member.status == "member.ready_changed"
        assert all(value.ready for value in ready_member.party.members.values())

        third_invite = services.party.invite(
            "party-invite-third",
            leader.id,
            third.id,
            logical_time=NOW,
        )
        joined_third = services.party.accept(
            "party-accept-third",
            third.id,
            third_invite.request.id,
            logical_time=NOW,
        )
        assert joined_third.status == "accepted" and joined_third.party is not None
        assert len(joined_third.party.members) == 3
        assert not any(value.ready for value in joined_third.party.members.values())

        full = services.party.invite(
            "party-invite-full",
            leader.id,
            outsider.id,
            logical_time=NOW,
        )
        assert full.status == "full"
        assert not services.party.view(outsider.id, logical_time=NOW).incoming_requests

        unauthorized = services.party.kick(
            "party-kick-unauthorized",
            member.id,
            third.id,
            logical_time=NOW,
        )
        assert unauthorized.status == "failed"
        transferred = services.party.transfer(
            "party-transfer",
            leader.id,
            member.id,
            logical_time=NOW,
        )
        assert transferred.status == "leadership.transferred"
        assert transferred.party.leader_id == member.id
        left = services.party.leave("party-leave", leader.id, logical_time=NOW)
        assert left.status == "member.left"
        assert leader.id not in left.party.members
        removed = services.party.kick(
            "party-kick-third",
            member.id,
            third.id,
            logical_time=NOW,
        )
        assert removed.status == "member.removed"

        reloaded = build_game_services(
            database_path=database_path,
            identity_secret="party-feature-secret",
        )
        reloaded.database.initialize()
        restored = reloaded.party.view(member.id, logical_time=NOW)
        assert restored.party is not None
        assert set(restored.party.members) == {member.id}
        disbanded = reloaded.party.disband(
            "party-disband",
            member.id,
            logical_time=NOW,
        )
        assert disbanded.status == "disbanded"
        assert reloaded.party.view(member.id, logical_time=NOW).party is None
    print("party feature tests passed")


def _create_character(services, subject: str, name: str):
    evidence = IdentityEvidence(
        f"evidence:{subject}",
        ExternalIdentity(
            "platform.local",
            "party-feature",
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


if __name__ == "__main__":
    main()
