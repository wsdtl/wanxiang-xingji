"""账号身份自动归并、冲突保护、防重放和角色归属测试。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.account import (  # noqa: E402
    ACCOUNT_FOUNDATION_VERSION,
    CHARACTER_PRINCIPAL,
    AccountDirectoryState,
    AccountEngine,
    AccountStatus,
    AccountStatusTransaction,
    AccountViolation,
    IdentityEvidence,
    PrincipalRef,
    UnbindIdentityTransaction,
    account_owns,
    build_qq_identity_evidence,
    require_account_owner,
)
from game.core.gameplay.character import (  # noqa: E402
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    COMBAT_SPEED,
    HEALTH_MAXIMUM,
    SPIRIT_MAXIMUM,
    CharacterCatalog,
    CharacterTemplateDefinition,
)


TIME = datetime(2026, 7, 12, 23, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


class SequenceIds:
    def __init__(self) -> None:
        self.index = 0

    def __call__(self) -> str:
        self.index += 1
        return f"account-{self.index}"


def main() -> None:
    assert ACCOUNT_FOUNDATION_VERSION == "account.foundation.v1"
    _assert_group_and_private_resolve_same_account()
    _assert_actor_only_group_bridges_private()
    _assert_new_group_alias_is_added()
    _assert_identity_conflict_never_overwrites()
    _assert_evidence_and_transaction_replay()
    _assert_status_and_unbind_boundaries()
    _assert_scope_tenant_and_compat_boundaries()
    _assert_character_ownership_uses_account_id()
    print("account foundation tests passed")


def _engine() -> AccountEngine:
    return AccountEngine(SequenceIds())


def _group_evidence(
    event_id: str,
    *,
    user: str = "U123",
    member: str = "M456",
    group: str = "G1",
    bot: str = "bot-app-1",
):
    return build_qq_identity_evidence(
        bot_app_id=bot,
        event_id=event_id,
        logical_time=TIME,
        conversation_type="group",
        actor_openid=member,
        user_openid=user,
        member_openid=member,
        group_openid=group,
    )


def _private_evidence(
    event_id: str,
    *,
    user: str = "U123",
    bot: str = "bot-app-1",
):
    return build_qq_identity_evidence(
        bot_app_id=bot,
        event_id=event_id,
        logical_time=TIME,
        conversation_type="private",
        actor_openid=user,
        user_openid=user,
    )


def _assert_group_and_private_resolve_same_account() -> None:
    engine = _engine()
    first = engine.resolve_identity(
        _group_evidence("event-group-1"),
        state=AccountDirectoryState(),
    )
    assert first.resolved and first.created and first.account
    assert first.account.id == "account-1"
    assert len(first.directory.identities_for(first.account.id)) == 3
    assert [event.kind for event in first.events] == [
        "account.created",
        "account.identity.bound",
        "account.identity.bound",
        "account.identity.bound",
    ]
    assert "U123" not in repr(first.events)
    assert "M456" not in repr(first.events)

    private = engine.resolve_identity(
        _private_evidence("event-private-1"),
        state=first.directory,
    )
    assert private.account and private.account.id == first.account.id
    assert not private.created
    assert [event.kind for event in private.events] == ["account.identity.bound"]
    assert len(private.directory.accounts) == 1


def _assert_actor_only_group_bridges_private() -> None:
    engine = _engine()
    group = build_qq_identity_evidence(
        bot_app_id="bot-app-1",
        event_id="member-only-group",
        logical_time=TIME,
        conversation_type="group",
        actor_openid="SAME-OPENID",
        member_openid="SAME-OPENID",
        group_openid="G1",
    )
    first = engine.resolve_identity(group, state=AccountDirectoryState())
    assert first.account and len(first.directory.accounts) == 1
    private = engine.resolve_identity(
        _private_evidence("same-private", user="SAME-OPENID"),
        state=first.directory,
    )
    assert private.account and private.account.id == first.account.id
    assert len(private.directory.accounts) == 1


def _assert_new_group_alias_is_added() -> None:
    engine = _engine()
    first = engine.resolve_identity(
        _group_evidence("event-group-1"),
        state=AccountDirectoryState(),
    )
    second = engine.resolve_identity(
        _group_evidence("event-group-2", member="M789", group="G2"),
        state=first.directory,
    )
    assert second.account and second.account.id == "account-1"
    assert second.account.revision == 1
    identities = second.directory.identities_for("account-1")
    assert len(identities) == 5
    assert {identity.scope_id for identity in identities} == {"", "G1", "G2"}
    assert [event.kind for event in second.events] == [
        "account.identity.bound",
        "account.identity.bound",
    ]


def _assert_identity_conflict_never_overwrites() -> None:
    engine = _engine()
    first = engine.resolve_identity(
        _private_evidence("event-user-1", user="U1"),
        state=AccountDirectoryState(),
    )
    second = engine.resolve_identity(
        _private_evidence("event-user-2", user="U2"),
        state=first.directory,
    )
    user1 = _private_evidence("unused-1", user="U1").primary
    user2 = _private_evidence("unused-2", user="U2").primary
    conflict_evidence = IdentityEvidence(
        "event-conflict",
        user1,
        (user2,),
        "identity.qq_signed_event",
        TIME,
    )
    conflict = engine.resolve_identity(conflict_evidence, state=second.directory)
    assert not conflict.resolved and conflict.conflict
    assert conflict.conflict.account_ids == ("account-1", "account-2")
    assert conflict.directory.account_for(user1).id == "account-1"  # type: ignore[union-attr]
    assert conflict.directory.account_for(user2).id == "account-2"  # type: ignore[union-attr]
    assert conflict.events[0].kind == "account.identity.conflict"


def _assert_evidence_and_transaction_replay() -> None:
    engine = _engine()
    evidence = _group_evidence("event-replay")
    first = engine.resolve_identity(evidence, state=AccountDirectoryState())
    replay = engine.resolve_identity(evidence, state=first.directory)
    assert replay.replayed and replay.account
    assert replay.directory is first.directory
    assert not replay.events

    mismatched = _group_evidence("event-replay", member="M999")
    try:
        engine.resolve_identity(mismatched, state=first.directory)
        raise AssertionError("相同事件 id 不能换一组身份后重放")
    except AccountViolation as exc:
        assert exc.code == "account.evidence_mismatch"

    account = first.account
    assert account is not None
    suspended = engine.change_status(
        AccountStatusTransaction(
            "status-1",
            account.id,
            account.revision,
            AccountStatus.SUSPENDED,
            "test",
            TIME,
        ),
        state=first.directory,
    )
    status_replay = engine.change_status(
        AccountStatusTransaction(
            "status-1",
            account.id,
            account.revision,
            AccountStatus.SUSPENDED,
            "test",
            TIME,
        ),
        state=suspended.directory,
    )
    assert status_replay.replayed
    assert status_replay.directory is suspended.directory


def _assert_status_and_unbind_boundaries() -> None:
    engine = _engine()
    first = engine.resolve_identity(
        _group_evidence("event-group-1"),
        state=AccountDirectoryState(),
    )
    account = first.account
    assert account is not None
    suspended = engine.change_status(
        AccountStatusTransaction(
            "suspend-account",
            account.id,
            account.revision,
            AccountStatus.SUSPENDED,
            "risk-control",
            TIME,
        ),
        state=first.directory,
    )
    try:
        engine.require_active(suspended.account)
        raise AssertionError("暂停账号不能通过活跃守卫")
    except AccountViolation as exc:
        assert exc.code == "account.not_active"

    member_identity = _group_evidence("unused").primary
    unbound = engine.unbind_identity(
        UnbindIdentityTransaction(
            "unbind-member",
            account.id,
            suspended.account.revision,
            member_identity,
            "platform-identity-expired",
            TIME,
        ),
        state=suspended.directory,
    )
    assert len(unbound.directory.identities_for(account.id)) == 2
    removable_identity = unbound.directory.identities_for(account.id)[0]
    reduced = engine.unbind_identity(
        UnbindIdentityTransaction(
            "unbind-alias",
            account.id,
            unbound.account.revision,
            removable_identity,
            "identity-cleanup",
            TIME,
        ),
        state=unbound.directory,
    )
    last_identity = reduced.directory.identities_for(account.id)[0]
    try:
        engine.unbind_identity(
            UnbindIdentityTransaction(
                "unbind-last",
                account.id,
                reduced.account.revision,
                last_identity,
                "invalid-test",
                TIME,
            ),
            state=reduced.directory,
        )
        raise AssertionError("不能解绑账号最后一个登录身份")
    except AccountViolation as exc:
        assert exc.code == "account.last_identity"


def _assert_scope_tenant_and_compat_boundaries() -> None:
    engine = _engine()
    first = engine.resolve_identity(
        _private_evidence("event-bot-1", user="SAME", bot="bot-app-1"),
        state=AccountDirectoryState(),
    )
    second = engine.resolve_identity(
        _private_evidence("event-bot-2", user="SAME", bot="bot-app-2"),
        state=first.directory,
    )
    assert first.account and second.account
    assert first.account.id != second.account.id

    try:
        build_qq_identity_evidence(
            bot_app_id="bot-app-1",
            event_id="missing-group",
            logical_time=TIME,
            conversation_type="group",
            member_openid="M1",
        )
        raise AssertionError("群成员身份必须包含群作用域")
    except ValueError:
        pass

    actor_only = build_qq_identity_evidence(
        bot_app_id="bot-app-1",
        event_id="compat-only",
        logical_time=TIME,
        conversation_type="private",
        actor_openid="legacy-actor",
    )
    assert actor_only.primary.subject_kind == "identity.qq_actor"


def _assert_character_ownership_uses_account_id() -> None:
    catalog = CharacterCatalog()
    catalog.templates.register(
        CharacterTemplateDefinition(
            "character_template.standard",
            {
                HEALTH_MAXIMUM: 100,
                SPIRIT_MAXIMUM: 50,
                COMBAT_ATTACK: 10,
                COMBAT_DEFENSE: 10,
                COMBAT_SPEED: 5,
            },
        )
    )
    character = catalog.create_character(
        character_id="character-a",
        account_id="account-1",
        name="归属测试角色",
        template_id="character_template.standard",
        created_at=TIME,
    )
    assert character.account_id == "account-1"
    assert account_owns("account-1", character)
    require_account_owner("account-1", character)
    try:
        require_account_owner("account-2", character)
        raise AssertionError("其他账号不能操作该角色")
    except PermissionError:
        pass
    principal = PrincipalRef(CHARACTER_PRINCIPAL, character.id)
    assert principal.kind == "principal.character"


if __name__ == "__main__":
    main()
