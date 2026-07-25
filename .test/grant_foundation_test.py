"""兑换码、小游戏回执、活动权益、迁移清单与奖励原子兑付测试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay.grants import (  # noqa: E402
    GRANT_FOUNDATION_VERSION,
    GrantCampaign,
    GrantCampaignStatus,
    GrantCredentialKind,
    GrantEntitlement,
    GrantEntitlementStatus,
    GrantProof,
    GrantRedemptionCommand,
    GrantRedemptionPolicy,
    GrantRewardBundle,
    MigrationManifestEntry,
    code_entitlement_id,
    grant_code_digest,
    sign_grant_proof,
)
from game.core.gameplay.rewards import (  # noqa: E402
    CurrencyReward,
    RewardExpectations,
    StackItemReward,
)
from game.core.persistence import (  # noqa: E402
    ConcurrencyConflict,
    PERSISTENCE_SCHEMA_VERSION,
    PersistedGrantService,
    PersistedRewardSettlementService,
    RewardSettlementStorageKeys,
    SqliteDatabase,
    TransactionMismatch,
)
from game.core.persistence.grants import GrantRepository  # noqa: E402

from reward_settlement_test import TIME, _context, _environment  # noqa: E402


CODE_SECRET = b"grant-code-secret-for-tests"
PROOF_SECRET = b"mini-game-proof-secret-tests"
KEYS = RewardSettlementStorageKeys(
    "inventory-account-a",
    "ledger-world-main",
    character_ids=("character-a",),
    weapon_ids=("weapon-a",),
)


def main() -> None:
    assert GRANT_FOUNDATION_VERSION == "grant.foundation.v1"
    assert PERSISTENCE_SCHEMA_VERSION == 6
    with TemporaryDirectory() as directory:
        _assert_complete_grant_flow(Path(directory))
    print("grant foundation tests passed")


def _assert_complete_grant_flow(directory: Path) -> None:
    environment = _environment()
    database = SqliteDatabase(directory / "grant.db")
    database.initialize()
    rewards = PersistedRewardSettlementService(database, environment["engine"])
    rewards.initialize_snapshot(KEYS, environment["snapshot"], logical_time=TIME)
    service = PersistedGrantService(
        database,
        rewards,
        code_secret=CODE_SECRET,
        proof_secrets={"mini-game.main": PROOF_SECRET},
    )

    _assert_schema(database)
    _assert_code_redemption(service, database, rewards)
    _assert_activity_and_atomic_failure(service, database, rewards)
    _assert_signed_receipt(service, database)
    _assert_migration_manifest(service, database)
    _assert_revocation(service, database, rewards)


def _assert_schema(database: SqliteDatabase) -> None:
    with database.unit_of_work(write=False) as uow:
        tables = {
            str(row[0])
            for row in uow.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {
        "grant_campaign",
        "grant_credential",
        "grant_entitlement",
        "grant_redemption",
        "migration_manifest",
    } <= tables


def _assert_code_redemption(service, database, rewards) -> None:
    campaign = GrantCampaign(
        "campaign.public-code",
        1,
        "issuer.operations",
        "source.grant_code",
        "offer.public_code",
        1,
        GrantRedemptionPolicy.QUOTA,
        2,
        1,
        TIME - timedelta(minutes=1),
        TIME + timedelta(days=1),
    )
    service.create_campaign(campaign, created_at=TIME)
    service.create_campaign(campaign, created_at=TIME)
    raw_code = "PUBLIC-TEST-1234"
    credential = service.register_code(
        "credential.public-code",
        campaign.id,
        raw_code,
        issued_at=TIME,
    )
    assert credential.kind is GrantCredentialKind.CODE
    assert credential.digest == grant_code_digest(CODE_SECRET, campaign.id, raw_code)
    service.register_code(
        "credential.public-code",
        campaign.id,
        raw_code,
        issued_at=TIME,
    )
    with database.unit_of_work(write=False) as uow:
        row = uow.connection.execute(
            "SELECT digest FROM grant_credential WHERE credential_id = ?",
            (credential.id,),
        ).fetchone()
        assert row and str(row[0]) != raw_code
        assert "PUBLIC" not in str(row[0])

    initial = rewards.load_snapshot(KEYS, claim_scope_id="account-a")
    command = GrantRedemptionCommand("redeem-code-1", campaign.id, "account-a")
    bundle = _currency_bundle(initial, 50)
    outcome = service.redeem_code(command, raw_code.lower(), bundle, KEYS, context=_context(2_001))
    assert outcome.ok and outcome.value, outcome.failure
    assert not outcome.value.replayed
    assert outcome.value.receipt.credential_id == credential.id
    assert rewards.load_snapshot(KEYS, claim_scope_id="account-a").ledger.accounts["wallet-a"].balance == 50

    replay = service.redeem_code(command, raw_code, bundle, KEYS, context=_context(2_002))
    assert replay.ok and replay.value and replay.value.replayed
    assert replay.value.receipt == outcome.value.receipt

    invalid = service.redeem_code(
        GrantRedemptionCommand("redeem-code-invalid", campaign.id, "account-a"),
        "WRONG-CODE-9999",
        bundle,
        KEYS,
        context=_context(2_003),
    )
    assert invalid.failure and invalid.failure.code == "grant.code_invalid"

    exhausted_command = GrantRedemptionCommand("redeem-code-2", campaign.id, "account-a")
    exhausted = service.redeem_code(
        exhausted_command,
        raw_code,
        bundle,
        KEYS,
        context=_context(2_004),
    )
    assert exhausted.failure and exhausted.failure.code == "grant.campaign_limit_reached"
    rolled_back_id = code_entitlement_id(campaign.id, exhausted_command.id, "account-a")
    with database.unit_of_work(write=False) as uow:
        assert GrantRepository().load_entitlement(uow, rolled_back_id) is None


def _assert_activity_and_atomic_failure(service, database, rewards) -> None:
    campaign = _activity_campaign()
    service.create_campaign(campaign, created_at=TIME)
    direct = GrantEntitlement(
        "entitlement.activity-1",
        campaign.id,
        "account-a",
        campaign.offer_id,
        campaign.offer_version,
        TIME,
        metadata={"grant.method": "activity"},
    )
    service.issue_entitlements(campaign.id, (direct,), logical_time=TIME)
    service.issue_entitlements(campaign.id, (direct,), logical_time=TIME)
    before = rewards.load_snapshot(KEYS, claim_scope_id="account-a")
    result = service.redeem_entitlement(
        GrantRedemptionCommand("redeem-activity-1", campaign.id, "account-a", direct.id),
        _currency_bundle(before, 25),
        KEYS,
        context=_context(2_010),
    )
    assert result.ok and result.value, result.failure
    after = rewards.load_snapshot(KEYS, claim_scope_id="account-a")
    assert after.ledger.accounts["wallet-a"].balance == 75

    failing = GrantEntitlement(
        "entitlement.reward-failure",
        campaign.id,
        "account-a",
        campaign.offer_id,
        campaign.offer_version,
        TIME,
    )
    service.issue_entitlements(campaign.id, (failing,), logical_time=TIME)
    failure_bundle = GrantRewardBundle(
        (StackItemReward("invalid-item", "item.missing.definition", "bag-a", 1),),
        RewardExpectations(
            after.claims.revision,
            inventory_revision=after.inventory.revision,
        ),
    )
    failed = service.redeem_entitlement(
        GrantRedemptionCommand("redeem-fails", campaign.id, "account-a", failing.id),
        failure_bundle,
        KEYS,
        context=_context(2_011),
    )
    assert failed.failure
    assert rewards.load_snapshot(KEYS, claim_scope_id="account-a") == after
    with database.unit_of_work(write=False) as uow:
        entitlement = GrantRepository().load_entitlement(uow, failing.id)
        assert entitlement and entitlement.status is GrantEntitlementStatus.AVAILABLE
        assert uow.load_transaction("grant:should-not-exist") is None


def _assert_signed_receipt(service, database) -> None:
    campaign = _activity_campaign()
    proof = GrantProof(
        "mini-game.main",
        "run-9001",
        campaign.id,
        "account-a",
        "nonce-9001",
        TIME,
        TIME + timedelta(minutes=10),
        sha256(b"score-tier-3").hexdigest(),
    )
    entitlement = GrantEntitlement(
        "entitlement.mini-game-9001",
        campaign.id,
        "account-a",
        campaign.offer_id,
        campaign.offer_version,
        TIME,
        expires_at=proof.expires_at,
        metadata={"reward_tier": 3},
    )
    signature = sign_grant_proof(PROOF_SECRET, proof)
    credential = service.issue_signed_entitlement(
        proof,
        signature,
        entitlement,
        logical_time=TIME,
    )
    service.issue_signed_entitlement(proof, signature, entitlement, logical_time=TIME)
    assert credential.bound_account_id == "account-a"
    with database.unit_of_work(write=False) as uow:
        stored = GrantRepository().load_entitlement(uow, entitlement.id)
        assert stored and stored.credential_id == credential.id
        assert stored.metadata["grant.proof_payload_digest"] == proof.payload_digest
    try:
        service.issue_signed_entitlement(
            proof,
            "0" * 64,
            replace(entitlement, id="entitlement.invalid-proof"),
            logical_time=TIME,
        )
        raise AssertionError("无效小游戏签名必须被拒绝")
    except ValueError as exc:
        assert "签名无效" in str(exc)


def _assert_migration_manifest(service, database) -> None:
    campaign = _activity_campaign()
    entitlement = GrantEntitlement(
        "entitlement.migration-1",
        campaign.id,
        "account-a",
        campaign.offer_id,
        campaign.offer_version,
        TIME,
        metadata={"grant.method": "migration"},
    )
    entry = MigrationManifestEntry(
        "migration.batch-1",
        "legacy-user-7",
        "legacy-asset-99",
        "mapping.v1",
        "account-a",
        entitlement.id,
        sha256(b"legacy-asset-source").hexdigest(),
        TIME,
        {"legacy_quantity": 12, "equivalent_offer": "offer.activity"},
    )
    service.issue_migration_entitlement(entry, entitlement)
    service.issue_migration_entitlement(entry, entitlement)
    with database.unit_of_work(write=False) as uow:
        stored = GrantRepository().load_migration_manifest(
            uow,
            entry.batch_id,
            entry.legacy_subject_id,
            entry.legacy_asset_id,
        )
        assert stored == entry
    try:
        service.issue_migration_entitlement(
            replace(entry, source_digest=sha256(b"changed").hexdigest()),
            entitlement,
        )
        raise AssertionError("同一旧资产不能映射为不同迁移内容")
    except TransactionMismatch:
        pass


def _assert_revocation(service, database, rewards) -> None:
    campaign = _activity_campaign()
    entitlement = GrantEntitlement(
        "entitlement.revoked",
        campaign.id,
        "account-a",
        campaign.offer_id,
        campaign.offer_version,
        TIME,
    )
    service.issue_entitlements(campaign.id, (entitlement,), logical_time=TIME)
    service.revoke_entitlement(entitlement.id, revoked_at=TIME + timedelta(seconds=1))
    snapshot = rewards.load_snapshot(KEYS, claim_scope_id="account-a")
    outcome = service.redeem_entitlement(
        GrantRedemptionCommand("redeem-revoked", campaign.id, "account-a", entitlement.id),
        _currency_bundle(snapshot, 1),
        KEYS,
        context=_context(2_020),
    )
    assert outcome.failure and outcome.failure.code == "grant.entitlement_revoked"
    try:
        service.revoke_entitlement(entitlement.id, revoked_at=TIME + timedelta(seconds=2))
        raise AssertionError("已经撤销的权益不能重复改变状态")
    except ConcurrencyConflict:
        pass

    credential = service.register_code(
        "credential.revoked",
        campaign.id,
        "REVOKED-CODE-1234",
        issued_at=TIME,
    )
    service.revoke_credential(credential.id, revoked_at=TIME + timedelta(seconds=3))
    credential_result = service.redeem_code(
        GrantRedemptionCommand("redeem-revoked-code", campaign.id, "account-a"),
        "REVOKED-CODE-1234",
        _currency_bundle(snapshot, 1),
        KEYS,
        context=_context(2_021),
    )
    assert credential_result.failure and credential_result.failure.code == "grant.credential_revoked"

    paused = GrantEntitlement(
        "entitlement.paused-campaign",
        campaign.id,
        "account-a",
        campaign.offer_id,
        campaign.offer_version,
        TIME,
    )
    service.issue_entitlements(campaign.id, (paused,), logical_time=TIME)
    service.set_campaign_status(
        campaign.id,
        GrantCampaignStatus.PAUSED,
        expected_version=1,
        updated_at=TIME + timedelta(seconds=4),
    )
    paused_result = service.redeem_entitlement(
        GrantRedemptionCommand("redeem-paused", campaign.id, "account-a", paused.id),
        _currency_bundle(snapshot, 1),
        KEYS,
        context=_context(2_022),
    )
    assert paused_result.failure and paused_result.failure.code == "grant.campaign_unavailable"

    replay_after_pause = service.redeem_entitlement(
        GrantRedemptionCommand(
            "redeem-activity-1",
            campaign.id,
            "account-a",
            "entitlement.activity-1",
        ),
        _currency_bundle(snapshot, 25),
        KEYS,
        context=_context(2_023),
    )
    assert replay_after_pause.ok and replay_after_pause.value and replay_after_pause.value.replayed


def _activity_campaign() -> GrantCampaign:
    return GrantCampaign(
        "campaign.activity",
        1,
        "issuer.operations",
        "source.activity_grant",
        "offer.activity",
        1,
        GrantRedemptionPolicy.PER_ACCOUNT,
        10,
        None,
        TIME - timedelta(minutes=1),
        TIME + timedelta(days=1),
    )


def _currency_bundle(snapshot, amount: int) -> GrantRewardBundle:
    return GrantRewardBundle(
        (CurrencyReward("issuer-stone", "wallet-a", amount),),
        RewardExpectations(
            snapshot.claims.revision,
            ledger_account_revisions={
                "issuer-stone": snapshot.ledger.accounts["issuer-stone"].revision,
                "wallet-a": snapshot.ledger.accounts["wallet-a"].revision,
            },
        ),
    )


if __name__ == "__main__":
    main()
