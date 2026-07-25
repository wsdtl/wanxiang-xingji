"""统一奖励结算的跨领域原子性、预检、防重与扩展边界测试。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay import RuleContext, Ruleset, SeededRandomSource, TagSet  # noqa: E402
from game.core.gameplay.character import (  # noqa: E402
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    COMBAT_SPEED,
    HEALTH_MAXIMUM,
    SPIRIT_MAXIMUM,
    CharacterCatalog,
    CharacterEngine,
    CharacterFeatureDefinition,
    CharacterTemplateDefinition,
    ContributionSpec,
    ProgressionDefinition,
)
from game.core.gameplay.economy import (  # noqa: E402
    CurrencyCatalog,
    CurrencyDefinition,
    IssueFunds,
    LedgerAccount,
    LedgerAccountKind,
    LedgerEngine,
    LedgerState,
)
from game.core.gameplay.inventory import (  # noqa: E402
    InventoryEngine,
    InventoryState,
    ItemAssetKind,
    ItemCatalog,
    ItemComponentRegistry,
    ItemContainer,
    ItemDefinition,
    ItemInstance,
    SourceReceipt,
)
from game.core.gameplay.loadout import (  # noqa: E402
    WEAPON_SLOT_ID,
    LoadoutItemComponent,
    QualityCatalog,
    QualityDefinition,
    register_loadout_item_component,
)
from game.core.gameplay.rewards import (  # noqa: E402
    CharacterExperienceReward,
    CharacterFeatureReward,
    CharacterProgressionReward,
    CurrencyReward,
    DuplicateUnlockPolicy,
    GeneratedWeaponReward,
    InstanceItemReward,
    REWARD_FOUNDATION_VERSION,
    RewardDisposition,
    RewardExpectations,
    RewardLine,
    RewardPlannerRegistry,
    RewardSettlement,
    RewardSettlementEngine,
    RewardSettlementSnapshot,
    RewardClaimState,
    StackItemReward,
    WeaponExperienceReward,
)
from game.core.gameplay.weapon import (  # noqa: E402
    WeaponCatalog,
    WeaponDefinition,
    WeaponEngine,
    WeaponQualityProfile,
    WeaponState,
    weapon_state_data,
)
from game.core.persistence import (  # noqa: E402
    PersistedRewardSettlementService,
    RewardSettlementStorageKeys,
    SqliteDatabase,
)


TIME = datetime(2026, 7, 13, 0, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
    environment = _environment()
    execution = _assert_preflight_and_complete_settlement(environment)
    _assert_replay_and_content_mismatch(environment, execution)
    _assert_late_failure_rolls_back_every_domain(environment)
    _assert_revision_and_duplicate_policies(environment)
    _assert_custom_reward_planner(environment)
    _assert_generated_weapon_is_persisted_atomically(environment)
    print("reward settlement tests passed")


def _context(seed: int = 900) -> RuleContext:
    return RuleContext(
        trace_id=f"reward-test-{seed}",
        rule_version="rules.v1",
        ruleset=Ruleset("ruleset.standard"),
        logical_time=TIME,
        random=SeededRandomSource(seed),
    )


def _environment() -> dict[str, object]:
    components = ItemComponentRegistry()
    register_loadout_item_component(components)
    items = ItemCatalog(components)
    items.register(
        ItemDefinition(
            "item.material.spirit_ore",
            ItemAssetKind.STACK,
            tags=TagSet.of("item.material"),
            stack_limit=99,
        )
    )
    items.register(
        ItemDefinition(
            "item.relic.quest_token",
            ItemAssetKind.INSTANCE,
            tags=TagSet.of("item.relic"),
        )
    )
    items.register(
        ItemDefinition(
            "item.weapon.training_blade",
            ItemAssetKind.INSTANCE,
            tags=TagSet.of("item.weapon"),
            components={
                "item_component.loadout": LoadoutItemComponent(
                    frozenset({WEAPON_SLOT_ID})
                )
            },
        )
    )

    qualities = QualityCatalog()
    qualities.register(QualityDefinition("quality.common", 0))
    qualities.finalize()
    weapons = WeaponCatalog(qualities, items)
    weapons.register(
        WeaponDefinition(
            "weapon.training_blade",
            "item.weapon.training_blade",
            ContributionSpec(),
            {
                "quality.common": WeaponQualityProfile(
                    "quality.common",
                    experience_requirements=(100, 200),
                )
            },
        )
    )
    weapons.finalize()

    characters = CharacterCatalog()
    characters.features.register(CharacterFeatureDefinition("feature.starting_body"))
    characters.features.register(CharacterFeatureDefinition("feature.quest_sight"))
    characters.progressions.register(
        ProgressionDefinition("progression.character_level", (100, 200))
    )
    characters.progressions.register(
        ProgressionDefinition("progression.side_path", (50,))
    )
    characters.templates.register(
        CharacterTemplateDefinition(
            "character_template.standard",
            {
                HEALTH_MAXIMUM: 100,
                SPIRIT_MAXIMUM: 50,
                COMBAT_ATTACK: 10,
                COMBAT_DEFENSE: 10,
                COMBAT_SPEED: 5,
            },
            progression_ids=frozenset({"progression.character_level"}),
            feature_ids=frozenset({"feature.starting_body"}),
        )
    )
    characters.finalize()

    currencies = CurrencyCatalog()
    currencies.register(CurrencyDefinition("currency.spirit_stone"))
    ledger = LedgerEngine(currencies)
    inventory = InventoryEngine(items)
    character_engine = CharacterEngine(characters)
    weapon_engine = WeaponEngine(weapons)
    settlement_engine = RewardSettlementEngine(
        inventory=inventory,
        ledger=ledger,
        character=character_engine,
        weapon=weapon_engine,
    )

    character = characters.create_character(
        character_id="character-a",
        account_id="account-a",
        name="结算测试角色",
        template_id="character_template.standard",
        created_at=TIME,
    )
    weapon = weapons.create_state(
        asset_id="weapon-a",
        definition_id="weapon.training_blade",
        quality_id="quality.common",
    )
    ledger_state = LedgerState(
        accounts={
            "issuer-stone": LedgerAccount(
                "issuer-stone",
                "owner.system",
                "system-economy",
                "currency.spirit_stone",
                LedgerAccountKind.ISSUER,
            ),
            "wallet-a": LedgerAccount(
                "wallet-a",
                "owner.account",
                "account-a",
                "currency.spirit_stone",
            ),
        }
    )
    snapshot = RewardSettlementSnapshot(
        InventoryState(
            containers={
                "bag-a": ItemContainer("bag-a", "container.inventory", "account-a")
            },
            instances={
                weapon.asset_id: ItemInstance(
                    weapon.asset_id,
                    "item.weapon.training_blade",
                    "bag-a",
                    SourceReceipt("receipt:weapon-a", "source.test", "test", TIME),
                    weapon_state_data(weapon),
                )
            },
        ),
        ledger_state,
        {character.id: character},
        {weapon.asset_id: weapon},
        RewardClaimState("account-a"),
    )
    return {
        "engine": settlement_engine,
        "snapshot": snapshot,
    }


def _assert_generated_weapon_is_persisted_atomically(environment: dict[str, object]) -> None:
    engine = environment["engine"]
    snapshot = environment["snapshot"]
    assert isinstance(engine, RewardSettlementEngine)
    assert isinstance(snapshot, RewardSettlementSnapshot)
    generated = WeaponState(
        "weapon-generated",
        "weapon.training_blade",
        "quality.common",
    )
    settlement = RewardSettlement(
        "reward-generated-weapon",
        "account-a",
        "account-a",
        "source.test_reward",
        "generated-weapon-test",
        (
            GeneratedWeaponReward(
                generated,
                "item.weapon.training_blade",
                "bag-a",
            ),
        ),
        RewardExpectations(
            claim_revision=snapshot.claims.revision,
            inventory_revision=snapshot.inventory.revision,
        ),
    )
    with TemporaryDirectory() as directory:
        database = SqliteDatabase(Path(directory) / "generated-weapon.db")
        database.initialize()
        service = PersistedRewardSettlementService(database, engine)
        initial_keys = RewardSettlementStorageKeys(
            "inventory-a",
            "ledger-a",
            tuple(snapshot.characters),
            tuple(snapshot.weapons),
        )
        service.initialize_snapshot(initial_keys, snapshot, logical_time=TIME)
        completed = service.settle(
            settlement,
            initial_keys,
            context=_context(950),
        ).unwrap()
        assert "weapon-generated" in completed.snapshot.weapons
        assert "weapon-generated" in completed.snapshot.inventory.instances

        expanded_keys = RewardSettlementStorageKeys(
            "inventory-a",
            "ledger-a",
            tuple(snapshot.characters),
            (*tuple(snapshot.weapons), "weapon-generated"),
        )
        restarted = PersistedRewardSettlementService(database, engine)
        loaded = restarted.load_snapshot(expanded_keys, claim_scope_id="account-a")
        assert loaded.weapons["weapon-generated"] == generated
        replay = restarted.settle(
            settlement,
            expanded_keys,
            context=_context(951),
        ).unwrap()
        assert replay.replayed


def _complete_settlement(snapshot: RewardSettlementSnapshot) -> RewardSettlement:
    return RewardSettlement(
        "reward-quest-1",
        "account-a",
        "account-a",
        "source.quest_reward",
        "quest-1",
        (
            CurrencyReward("issuer-stone", "wallet-a", 250),
            StackItemReward("ore-reward", "item.material.spirit_ore", "bag-a", 5),
            InstanceItemReward(
                "token-reward",
                "item.relic.quest_token",
                "bag-a",
                {"chapter": 1},
            ),
            CharacterExperienceReward(
                "character-a",
                "progression.character_level",
                120,
            ),
            CharacterFeatureReward("character-a", "feature.quest_sight"),
            CharacterProgressionReward("character-a", "progression.side_path"),
            WeaponExperienceReward("weapon-a", 50),
            WeaponExperienceReward("weapon-a", 100),
            CharacterFeatureReward("character-a", "feature.starting_body"),
        ),
        RewardExpectations(
            snapshot.claims.revision,
            inventory_revision=snapshot.inventory.revision,
            ledger_account_revisions={
                "issuer-stone": snapshot.ledger.accounts["issuer-stone"].revision,
                "wallet-a": snapshot.ledger.accounts["wallet-a"].revision,
            },
            character_revisions={
                "character-a": snapshot.characters["character-a"].revision,
            },
            weapon_revisions={
                "weapon-a": snapshot.weapons["weapon-a"].revision,
            },
        ),
        {"chapter": 1},
    )


def _assert_preflight_and_complete_settlement(environment):
    engine = environment["engine"]
    snapshot = environment["snapshot"]
    settlement = _complete_settlement(snapshot)
    assert REWARD_FOUNDATION_VERSION == "reward.foundation.v1"

    context = _context()
    checkpoint = context.random.checkpoint()
    preview = engine.preflight(settlement, snapshot=snapshot, context=context)
    assert preview.ok and preview.value, preview.failure
    assert preview.value.receipt.settlement_id == settlement.id
    assert context.random.checkpoint() == checkpoint
    assert snapshot.claims.revision == 0
    assert snapshot.inventory.revision == 0
    assert snapshot.ledger.accounts["wallet-a"].balance == 0

    outcome = engine.settle(settlement, snapshot=snapshot, context=_context(seed=901))
    assert outcome.ok and outcome.value, outcome.failure
    execution = outcome.value
    result = execution.snapshot
    assert result.claims.revision == 1
    assert settlement.id in result.claims.records
    assert result.ledger.accounts["wallet-a"].balance == 250
    assert result.ledger.accounts["issuer-stone"].balance == -250
    assert result.inventory.stacks["ore-reward"].quantity == 5
    assert result.inventory.instances["token-reward"].data["chapter"] == 1
    assert result.inventory.stacks["ore-reward"].lots[0].receipt.source_id == "quest-1"
    character = result.characters["character-a"]
    progression = character.progressions["progression.character_level"]
    assert (progression.level, progression.experience, progression.total_experience) == (2, 20, 120)
    assert "feature.quest_sight" in character.features
    assert "progression.side_path" in character.progressions
    weapon = result.weapons["weapon-a"]
    assert (weapon.level, weapon.experience, weapon.total_experience) == (2, 50, 150)
    assert weapon.revision == 1
    assert len(execution.receipt.lines) == 9
    assert execution.receipt.lines[-1].disposition is RewardDisposition.SKIPPED
    assert len(execution.receipt.domain_transaction_ids) == 4
    assert execution.events[-1].kind == "reward.settlement.completed"
    assert execution.events[-1].values["granted_count"] == 8
    assert execution.events[-1].values["skipped_count"] == 1
    return execution


def _assert_replay_and_content_mismatch(environment, execution):
    engine = environment["engine"]
    settlement = _complete_settlement(environment["snapshot"])
    replay = engine.settle(
        settlement,
        snapshot=execution.snapshot,
        context=_context(seed=902),
    )
    assert replay.ok and replay.value and replay.value.replayed
    assert replay.value.snapshot is execution.snapshot
    assert not replay.value.events

    changed = replace(
        settlement,
        rewards=(CurrencyReward("issuer-stone", "wallet-a", 251), *settlement.rewards[1:]),
    )
    mismatch = engine.settle(
        changed,
        snapshot=execution.snapshot,
        context=_context(seed=903),
    )
    assert mismatch.failure and mismatch.failure.code == "reward.settlement_mismatch"


def _assert_late_failure_rolls_back_every_domain(environment):
    engine = environment["engine"]
    snapshot = environment["snapshot"]
    settlement = RewardSettlement(
        "reward-fails-late",
        "account-a",
        "account-a",
        "source.quest_reward",
        "quest-invalid",
        (
            StackItemReward("ore-before-failure", "item.material.spirit_ore", "bag-a", 3),
            CurrencyReward("issuer-stone", "wallet-a", 99),
            CharacterFeatureReward("character-a", "feature.unknown"),
        ),
        RewardExpectations(
            0,
            inventory_revision=0,
            ledger_account_revisions={"issuer-stone": 0, "wallet-a": 0},
            character_revisions={"character-a": 0},
        ),
    )
    context = _context(seed=904)
    checkpoint = context.random.checkpoint()
    failed = engine.settle(settlement, snapshot=snapshot, context=context)
    assert failed.failure and failed.failure.code == "character.feature_unknown"
    assert "ore-before-failure" not in snapshot.inventory.stacks
    assert snapshot.ledger.accounts["wallet-a"].balance == 0
    assert "feature.unknown" not in snapshot.characters["character-a"].features
    assert snapshot.claims.revision == 0
    assert context.random.checkpoint() == checkpoint


def _assert_revision_and_duplicate_policies(environment):
    engine = environment["engine"]
    snapshot = environment["snapshot"]
    stale = replace(
        _complete_settlement(snapshot),
        id="reward-stale",
        expectations=replace(
            _complete_settlement(snapshot).expectations,
            inventory_revision=7,
        ),
    )
    outcome = engine.settle(stale, snapshot=snapshot, context=_context(seed=905))
    assert outcome.failure and outcome.failure.code == "reward.inventory_revision_conflict"

    wrong_scope = replace(
        _complete_settlement(snapshot),
        id="reward-wrong-scope",
        claim_scope_id="account-b",
    )
    scoped = engine.settle(wrong_scope, snapshot=snapshot, context=_context(seed=908))
    assert scoped.failure and scoped.failure.code == "reward.claim_scope_mismatch"

    duplicate = RewardSettlement(
        "reward-duplicate-rejected",
        "account-a",
        "account-a",
        "source.quest_reward",
        "quest-duplicate",
        (
            CharacterFeatureReward(
                "character-a",
                "feature.starting_body",
                DuplicateUnlockPolicy.REJECT,
            ),
        ),
        RewardExpectations(0),
    )
    rejected = engine.preflight(duplicate, snapshot=snapshot, context=_context(seed=906))
    assert rejected.failure and rejected.failure.code == "reward.feature_already_owned"


@dataclass(frozen=True)
class _BonusCurrencyReward:
    amount: int


def _assert_custom_reward_planner(environment):
    base_engine = environment["engine"]
    snapshot = environment["snapshot"]
    planners = RewardPlannerRegistry.with_defaults()

    def plan_bonus(reward, index, builder):
        issuer = builder.require_ledger_account("issuer-stone")
        wallet = builder.require_ledger_account("wallet-a")
        builder.add_ledger(
            IssueFunds(issuer.id, wallet.id, reward.amount),
            RewardLine(
                index,
                "reward.test_bonus_currency",
                wallet.id,
                wallet.currency_id,
                reward.amount,
            ),
        )

    planners.register(_BonusCurrencyReward, plan_bonus)
    engine = RewardSettlementEngine(
        inventory=base_engine.inventory,
        ledger=base_engine.ledger,
        character=base_engine.character,
        weapon=base_engine.weapon,
        planners=planners,
    )
    settlement = RewardSettlement(
        "reward-custom-planner",
        "account-a",
        "account-a",
        "source.test_reward",
        "custom-1",
        (_BonusCurrencyReward(7),),
        RewardExpectations(
            0,
            ledger_account_revisions={"issuer-stone": 0, "wallet-a": 0},
        ),
    )
    outcome = engine.settle(settlement, snapshot=snapshot, context=_context(seed=907))
    assert outcome.ok and outcome.value, outcome.failure
    assert outcome.value.snapshot.ledger.accounts["wallet-a"].balance == 7
    try:
        planners.register(str, plan_bonus)
        raise AssertionError("运行期不能增加奖励规划器")
    except RuntimeError:
        pass


if __name__ == "__main__":
    main()
