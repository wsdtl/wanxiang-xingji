"""组织角色、请求状态和有向关系测试。"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay import RuleContext, Ruleset, SeededRandomSource  # noqa: E402
from game.core.gameplay.social import (  # noqa: E402
    DISSOLVE_PERMISSION,
    MANAGE_MEMBERS_PERMISSION,
    MANAGE_ROLES_PERMISSION,
    SOCIAL_FOUNDATION_VERSION,
    AddOrganizationContribution,
    AdjustSocialRelation,
    ChangeOrganizationRole,
    CreateOrganization,
    CreateSocialRequest,
    JoinOrganization,
    LeaveOrganization,
    OrganizationRoleDefinition,
    OrganizationTypeDefinition,
    RelationOverflowPolicy,
    RelationTypeDefinition,
    ResolveSocialRequest,
    SocialCatalog,
    SocialCommand,
    SocialEngine,
    SocialRequest,
    SocialRequestDefinition,
    SocialRequestStatus,
    SocialState,
    TransferOrganizationLeadership,
)


TIME = datetime(2026, 7, 14, 3, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
    assert SOCIAL_FOUNDATION_VERSION == "social.foundation.v1"
    engine = _engine()
    state = SocialState("social-world")
    state = _run(
        engine,
        state,
        SocialCommand("org-create", "player-a", 0, CreateOrganization("org-a", "organization.guild")),
    ).state
    state = _run(
        engine,
        state,
        SocialCommand("org-join", "player-b", 1, JoinOrganization("org-a", "player-b")),
    ).state
    state = _run(
        engine,
        state,
        SocialCommand(
            "org-promote",
            "player-a",
            2,
            ChangeOrganizationRole("org-a", "player-b", "organization_role.officer"),
        ),
    ).state
    state = _run(
        engine,
        state,
        SocialCommand(
            "org-contribution",
            "system",
            3,
            AddOrganizationContribution("org-a", "player-b", "contribution.combat", 25),
        ),
    ).state
    assert state.organizations["org-a"].members["player-b"].contributions["contribution.combat"] == 25

    state = _run(
        engine,
        state,
        SocialCommand(
            "org-transfer-leadership",
            "player-a",
            4,
            TransferOrganizationLeadership("org-a", "player-a", "player-b"),
        ),
    ).state
    organization = state.organizations["org-a"]
    assert organization.members["player-a"].role_id == "organization_role.member"
    assert organization.members["player-b"].role_id == "organization_role.leader"
    state = _run(
        engine,
        state,
        SocialCommand(
            "founder-leaves",
            "player-a",
            5,
            LeaveOrganization("org-a", "player-a"),
        ),
    ).state
    assert "player-a" not in state.organizations["org-a"].members

    request = SocialRequest(
        "request-duel",
        "social_request.duel",
        "player-a",
        "player-b",
        TIME,
        TIME + timedelta(minutes=5),
    )
    state = _run(
        engine,
        state,
        SocialCommand("request-create", "player-a", 6, CreateSocialRequest(request)),
    ).state
    wrong_actor = engine.execute(
        SocialCommand(
            "request-wrong",
            "player-a",
            7,
            ResolveSocialRequest(request.id, SocialRequestStatus.ACCEPTED),
        ),
        state=state,
        context=_context("request-wrong"),
    )
    assert wrong_actor.failure and wrong_actor.failure.code == "social.request_recipient_required"
    state = _run(
        engine,
        state,
        SocialCommand(
            "request-accept",
            "player-b",
            7,
            ResolveSocialRequest(request.id, SocialRequestStatus.ACCEPTED),
        ),
    ).state
    assert state.requests[request.id].status is SocialRequestStatus.ACCEPTED

    state = _run(
        engine,
        state,
        SocialCommand(
            "relation-add",
            "system",
            8,
            AdjustSocialRelation("relation.hostility", "player-b", "player-a", 120),
        ),
    ).state
    relation = next(iter(state.relations.values()))
    assert relation.source_id == "player-b" and relation.target_id == "player-a"
    assert relation.value == 100
    print("social foundation tests passed")


def _engine() -> SocialEngine:
    catalog = SocialCatalog()
    catalog.roles.register(
        OrganizationRoleDefinition(
            "organization_role.leader",
            100,
            frozenset(
                {
                    MANAGE_MEMBERS_PERMISSION,
                    MANAGE_ROLES_PERMISSION,
                    DISSOLVE_PERMISSION,
                }
            ),
            maximum_members=1,
        )
    )
    catalog.roles.register(
        OrganizationRoleDefinition(
            "organization_role.officer",
            50,
            frozenset({MANAGE_MEMBERS_PERMISSION}),
        )
    )
    catalog.roles.register(OrganizationRoleDefinition("organization_role.member", 10))
    catalog.organizations.register(
        OrganizationTypeDefinition(
            "organization.guild",
            frozenset(
                {
                    "organization_role.leader",
                    "organization_role.officer",
                    "organization_role.member",
                }
            ),
            "organization_role.leader",
            "organization_role.member",
            capacity=20,
        )
    )
    catalog.requests.register(SocialRequestDefinition("social_request.duel", 600))
    catalog.relations.register(
        RelationTypeDefinition(
            "relation.hostility",
            0,
            100,
            overflow=RelationOverflowPolicy.CLAMP,
        )
    )
    catalog.finalize()
    return SocialEngine(catalog)


def _context(trace: str) -> RuleContext:
    return RuleContext(
        trace,
        "rules.social_v1",
        Ruleset("ruleset.social_test"),
        TIME,
        SeededRandomSource(trace),
    )


def _run(engine, state, command):
    outcome = engine.execute(command, state=state, context=_context(command.id))
    assert outcome.ok and outcome.value, outcome.failure
    return outcome.value


if __name__ == "__main__":
    main()
