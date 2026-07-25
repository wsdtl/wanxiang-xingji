"""跨领域持久化原子提交、事务重放与重启恢复测试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay.actions import (  # noqa: E402
    ActionResult,
    ActionState,
    ActionTransaction,
    ClaimAction,
    CompleteAction,
    StartAction,
)
from game.core.gameplay.activities import (  # noqa: E402
    ActivityCommand,
    ActivityInstance,
    ActivityState,
    CreateActivity,
)
from game.core.gameplay.exchange import (  # noqa: E402
    CommitExchange,
    ExchangeCommand,
    ExchangeState,
    OpenExchange,
    SettleExchange,
)
from game.core.gameplay.loot import LootRollCommand, LootState  # noqa: E402
from game.core.gameplay.rewards import CharacterFeatureReward  # noqa: E402
from game.core.gameplay.social import (  # noqa: E402
    CreateOrganization,
    SocialCommand,
    SocialState,
)
from game.core.gameplay.world import (  # noqa: E402
    AddPresence,
    WorldPosition,
    WorldPresence,
    WorldState,
    WorldTransaction,
)
from game.core.persistence import (  # noqa: E402
    INVENTORY_AGGREGATE,
    LEDGER_AGGREGATE,
    PersistedActionService,
    PersistedActivityService,
    PersistedExchangeService,
    PersistedLootService,
    PersistedRewardSettlementService,
    PersistedSocialService,
    PersistedWorldService,
    RewardSettlementStorageKeys,
    SnapshotRepository,
    SqliteDatabase,
)

from action_foundation_test import (  # noqa: E402
    TIME as ACTION_TIME,
    _context as action_context,
    _snapshot as action_snapshot,
)
from activity_foundation_test import (  # noqa: E402
    TIME as ACTIVITY_TIME,
    _context as activity_context,
    _engine as activity_engine,
)
from exchange_foundation_test import (  # noqa: E402
    TIME as EXCHANGE_TIME,
    _context as exchange_context,
    _contract,
    _environment as exchange_environment,
)
from loot_foundation_test import (  # noqa: E402
    _context as loot_context,
    _engine as loot_engine,
)
from persistence_closure_test import _action_engine  # noqa: E402
from reward_settlement_test import (  # noqa: E402
    TIME as REWARD_TIME,
    _complete_settlement,
    _environment as reward_environment,
)
from social_foundation_test import (  # noqa: E402
    _context as social_context,
    _engine as social_engine,
)
from world_foundation_test import (  # noqa: E402
    _context as world_context,
    _engine as world_engine,
)


def main() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        _assert_action_reward_atomic_claim(root / "action-reward.db")
        _assert_action_reward_failure_rolls_back(root / "action-reward-failure.db")
        _assert_exchange_three_aggregate_restart(root / "exchange.db")
        _assert_rule_domain_restart_and_replay(root)
    print("persistence domain tests passed")


def _reward_storage():
    environment = reward_environment()
    keys = RewardSettlementStorageKeys(
        "inventory-account-a",
        "ledger-world-main",
        character_ids=("character-a",),
        weapon_ids=("weapon-a",),
    )
    return environment, keys


def _completed_action(
    database: SqliteDatabase,
    settlement_id: str,
) -> tuple[PersistedActionService, ActionTransaction]:
    service = PersistedActionService(database, _action_engine())
    assert service.initialize("account-a", logical_time=ACTION_TIME) == ActionState("account-a")
    start = ActionTransaction(
        settlement_id + "-start",
        "account-a",
        0,
        (StartAction("action-run", "action.explore", action_snapshot(ACTION_TIME)),),
    )
    service.execute(start, context=action_context(ACTION_TIME, start.id)).unwrap()
    due = ACTION_TIME + timedelta(minutes=10)
    complete = ActionTransaction(
        settlement_id + "-complete",
        "account-a",
        1,
        (CompleteAction("action-run", ActionResult("outcome.success", due, settlement_id)),),
    )
    service.execute(complete, context=action_context(due, complete.id)).unwrap()
    claim = ActionTransaction(
        settlement_id + "-claim",
        "account-a",
        2,
        (ClaimAction("action-run"),),
    )
    return service, claim


def _assert_action_reward_atomic_claim(path: Path) -> None:
    environment, keys = _reward_storage()
    initial = environment["snapshot"]
    database = SqliteDatabase(path)
    database.initialize()
    rewards = PersistedRewardSettlementService(database, environment["engine"])
    rewards.initialize_snapshot(keys, initial, logical_time=REWARD_TIME)
    actions, claim = _completed_action(database, "action-reward-success")
    settlement = replace(
        _complete_settlement(initial),
        id="action-reward-success",
        source_id="action-run",
    )
    due = ACTION_TIME + timedelta(minutes=10)
    first = actions.claim_with_reward(
        claim,
        settlement,
        keys,
        rewards,
        context=action_context(due, claim.id),
    ).unwrap()
    assert not first.replayed and not first.action.state.records
    assert first.reward.snapshot.ledger.accounts["wallet-a"].balance == 250

    restarted_actions = PersistedActionService(database, _action_engine())
    restarted_rewards = PersistedRewardSettlementService(database, environment["engine"])
    replay = restarted_actions.claim_with_reward(
        claim,
        settlement,
        keys,
        restarted_rewards,
        context=action_context(due, claim.id),
    ).unwrap()
    assert replay.replayed and replay.reward.replayed
    assert restarted_actions.load("account-a") == first.action.state


def _assert_action_reward_failure_rolls_back(path: Path) -> None:
    environment, keys = _reward_storage()
    initial = environment["snapshot"]
    database = SqliteDatabase(path)
    database.initialize()
    rewards = PersistedRewardSettlementService(database, environment["engine"])
    rewards.initialize_snapshot(keys, initial, logical_time=REWARD_TIME)
    actions, claim = _completed_action(database, "action-reward-failure")
    base_settlement = _complete_settlement(initial)
    settlement = replace(
        base_settlement,
        id="action-reward-failure",
        source_id="action-run",
        rewards=(
            *base_settlement.rewards,
            CharacterFeatureReward("character-a", "feature.unknown"),
        ),
    )
    before_action = actions.load("account-a")
    before_reward = rewards.load_snapshot(keys, claim_scope_id="account-a")
    failed = actions.claim_with_reward(
        claim,
        settlement,
        keys,
        rewards,
        context=action_context(ACTION_TIME + timedelta(minutes=10), claim.id),
    )
    assert failed.failure and failed.failure.code == "character.feature_unknown", failed.failure
    assert actions.load("account-a") == before_action
    assert rewards.load_snapshot(keys, claim_scope_id="account-a") == before_reward
    with database.unit_of_work(write=False) as uow:
        assert uow.load_transaction(claim.id) is None
        assert uow.load_transaction(settlement.id) is None


def _assert_exchange_three_aggregate_restart(path: Path) -> None:
    engine, inventory, ledger = exchange_environment()
    database = SqliteDatabase(path)
    database.initialize()
    snapshots = SnapshotRepository()
    with database.unit_of_work() as uow:
        snapshots.insert(uow, INVENTORY_AGGREGATE, "inventory-main", inventory, EXCHANGE_TIME)
        snapshots.insert(uow, LEDGER_AGGREGATE, "ledger-main", ledger, EXCHANGE_TIME)
        uow.commit()
    service = PersistedExchangeService(database, engine)
    service.initialize(ExchangeState("exchange-main"), logical_time=EXCHANGE_TIME)
    contract = _contract("contract-persisted")
    open_command = ExchangeCommand(
        "exchange-open-persisted",
        "seller",
        0,
        OpenExchange(contract),
    )
    opened = service.execute(
        open_command,
        exchange_id="exchange-main",
        inventory_id="inventory-main",
        ledger_id="ledger-main",
        context=exchange_context(open_command.id),
    ).unwrap()
    assert opened.execution.inventory.stacks["contract-persisted-ore"].quantity == 3
    commit_command = ExchangeCommand(
        "exchange-commit-persisted",
        "buyer",
        1,
        CommitExchange(
            contract.id,
            "buyer",
            "buyer-wallet",
            contract.quote.id,
            contract.quote.version,
            {"exchange_offer.ore": "buyer-bag"},
        ),
    )
    committed = service.execute(
        commit_command,
        exchange_id="exchange-main",
        inventory_id="inventory-main",
        ledger_id="ledger-main",
        context=exchange_context(commit_command.id),
    ).unwrap()
    settle_command = ExchangeCommand(
        "exchange-settle-persisted",
        "buyer",
        2,
        SettleExchange(contract.id),
    )
    settled = service.execute(
        settle_command,
        exchange_id="exchange-main",
        inventory_id="inventory-main",
        ledger_id="ledger-main",
        context=exchange_context(settle_command.id),
    ).unwrap()
    assert settled.execution.inventory.stacks["contract-persisted-ore"].container_id == "buyer-bag"
    assert settled.execution.ledger.accounts["seller-wallet"].balance == 90

    restarted = PersistedExchangeService(database, engine)
    assert restarted.load("exchange-main") == settled.execution.exchange
    replay = restarted.execute(
        settle_command,
        exchange_id="exchange-main",
        inventory_id="inventory-main",
        ledger_id="ledger-main",
        context=exchange_context(settle_command.id),
    ).unwrap()
    assert replay.replayed and replay.execution == settled.execution
    assert committed.execution.exchange.revision == 2


def _assert_rule_domain_restart_and_replay(root: Path) -> None:
    _assert_loot_restart(root / "loot.db")
    _assert_world_restart(root / "world.db")
    _assert_activity_restart(root / "activity.db")
    _assert_social_restart(root / "social.db")


def _assert_loot_restart(path: Path) -> None:
    database = SqliteDatabase(path)
    database.initialize()
    engine = loot_engine()
    service = PersistedLootService(database, engine)
    assert service.initialize("account-a", logical_time=REWARD_TIME) == LootState("account-a")
    command = LootRollCommand("loot-persisted", "account-a", "loot_table.exploration", 0)
    first = service.roll(command, context=loot_context("persisted-loot")).unwrap()
    restarted = PersistedLootService(database, engine)
    assert restarted.load("account-a") == first.execution.state
    assert restarted.roll(command, context=loot_context("persisted-loot")).unwrap().replayed


def _assert_world_restart(path: Path) -> None:
    database = SqliteDatabase(path)
    database.initialize()
    engine = world_engine()
    service = PersistedWorldService(database, engine)
    assert service.initialize("world-main", logical_time=REWARD_TIME) == WorldState("world-main")
    command = WorldTransaction(
        "world-persisted",
        "account-a",
        0,
        (
            AddPresence(
                WorldPresence(
                    "presence-persisted",
                    "account-a",
                    "presence.body",
                    WorldPosition("world_space.mortal", location_id="location.city"),
                )
            ),
        ),
    )
    first = service.execute(
        "world-main",
        command,
        context=world_context(command.id),
    ).unwrap()
    restarted = PersistedWorldService(database, engine)
    assert restarted.load("world-main") == first.execution.state
    assert restarted.execute(
        "world-main",
        command,
        context=world_context(command.id),
    ).unwrap().replayed


def _assert_activity_restart(path: Path) -> None:
    database = SqliteDatabase(path)
    database.initialize()
    engine = activity_engine()
    service = PersistedActivityService(database, engine)
    assert service.initialize("activity-world", logical_time=ACTIVITY_TIME) == ActivityState("activity-world")
    instance = ActivityInstance(
        "activity-persisted",
        "activity.world_event",
        1,
        ACTIVITY_TIME + timedelta(minutes=5),
        ACTIVITY_TIME + timedelta(hours=1),
    )
    command = ActivityCommand(
        "activity-create-persisted",
        "system",
        0,
        CreateActivity(instance),
    )
    first = service.execute(
        "activity-world",
        command,
        context=activity_context(command.id, ACTIVITY_TIME),
    ).unwrap()
    restarted = PersistedActivityService(database, engine)
    assert restarted.load("activity-world") == first.execution.state
    assert restarted.execute(
        "activity-world",
        command,
        context=activity_context(command.id, ACTIVITY_TIME),
    ).unwrap().replayed


def _assert_social_restart(path: Path) -> None:
    database = SqliteDatabase(path)
    database.initialize()
    engine = social_engine()
    service = PersistedSocialService(database, engine)
    assert service.initialize("social-world", logical_time=REWARD_TIME) == SocialState("social-world")
    command = SocialCommand(
        "organization-create-persisted",
        "account-a",
        0,
        CreateOrganization("organization-persisted", "organization.guild"),
    )
    first = service.execute(
        "social-world",
        command,
        context=social_context(command.id),
    ).unwrap()
    restarted = PersistedSocialService(database, engine)
    assert restarted.load("social-world") == first.execution.state
    assert restarted.execute(
        "social-world",
        command,
        context=social_context(command.id),
    ).unwrap().replayed


if __name__ == "__main__":
    main()
