"""世界行纪累计、阶段奖励和实时排名投影。"""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from game.content.catalog import PRIMARY_CURRENCY_ID
from game.content.catalog.world_progress import WORLD_PROGRESS_DEFINITION
from game.core.gameplay import (
    CurrencyReward,
    InventoryState,
    LedgerAccountKind,
    LedgerState,
    RankingCandidate,
    RankingDirection,
    RankingEngine,
    RewardClaimState,
    RewardExpectations,
    RewardSettlement,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    StackItemReward,
)
from game.rules.character import PRIMARY_ISSUER_ACCOUNT_ID, PRIMARY_LEDGER_ID
from game.rules.exploration import EXPLORATION_VICTORY_FACT_KIND, ExplorationVictoryFact
from game.rules.world_progress import (
    WORLD_PROGRESS_RULESET_VERSION,
    WorldProgressState,
    advance_world_progress,
    world_progress_state_id,
)

from .models import (
    WorldProgressAdvanceResult,
    WorldProgressRankEntry,
    WorldProgressRankingView,
    WorldProgressRegionView,
    WorldProgressStorageKinds,
    WorldProgressView,
)


WORLD_PROGRESS_FACT_KIND = EXPLORATION_VICTORY_FACT_KIND
WORLD_PROGRESS_PROJECTOR_ID = "projector.world_progress.ranking"
WORLD_PROGRESS_PARTITION_ID = "global"
WORLD_PROGRESS_SOURCE_KIND = "source.world_progress"


class WorldProgressFeature:
    """消费探险胜利事实；不读取探险、战斗或库存业务快照。"""

    def __init__(
        self,
        database,
        content,
        world_views,
        snapshots,
        reward_settlement,
        projections,
        storage: WorldProgressStorageKinds,
        reward_keys_factory,
    ) -> None:
        self.database = database
        self.content = content
        self.world_views = world_views
        self.snapshots = snapshots
        self.reward_settlement = reward_settlement
        self.projections = projections
        self.storage = storage
        self.reward_keys_factory = reward_keys_factory
        self.ranking = RankingEngine()

    def observe_victory_in_uow(
        self,
        uow,
        fact: ExplorationVictoryFact,
    ) -> WorldProgressAdvanceResult:
        transaction_id = f"world-progress:{fact.event_id}"
        aggregate_id = world_progress_state_id(
            fact.character_id,
            fact.world_id,
            fact.region_id,
        )
        previous = self.snapshots.load(
            uow,
            self.storage.progress,
            aggregate_id,
            WorldProgressState,
        ) or WorldProgressState(
            fact.character_id,
            fact.character_name,
            fact.world_id,
            fact.region_id,
        )
        fingerprint = _fact_fingerprint(fact)
        committed = uow.load_transaction(transaction_id)
        if committed is not None:
            if committed.fingerprint != fingerprint or committed.scope_id != fact.character_id:
                raise ValueError("同一行纪事实身份对应不同内容")
            return WorldProgressAdvanceResult("replayed", previous)

        advance = advance_world_progress(
            previous,
            fact.encounter_kind,
            definition=WORLD_PROGRESS_DEFINITION,
            logical_time=fact.resolved_at,
        )
        if advance.added_points == 0:
            world_completed = self._world_completed_in_uow(uow, previous)
            world_reward_items: tuple[tuple[str, int], ...] = ()
            world_reward_granted = False
            if world_completed:
                _, items, replayed = self._settle_rewards(
                    uow,
                    fact,
                    (),
                    world_completed=True,
                    settlement_id=_world_completion_settlement_id(
                        fact.character_id,
                        fact.world_id,
                    ),
                    source_id=f"{fact.character_id}:{fact.world_id}",
                )
                if not replayed:
                    world_reward_items = items
                    world_reward_granted = True
            return WorldProgressAdvanceResult(
                "completed",
                previous,
                reward_items=world_reward_items,
                world_completed=world_reward_granted,
            )
        if previous.revision == 0 and previous.points == 0:
            self.snapshots.insert(
                uow,
                self.storage.progress,
                aggregate_id,
                advance.state,
                fact.resolved_at,
            )
        else:
            self.snapshots.update(
                uow,
                self.storage.progress,
                aggregate_id,
                previous,
                advance.state,
                fact.resolved_at,
            )

        world_completed = (
            previous.completed_at is None
            and advance.state.completed_at is not None
            and self._world_completed_in_uow(uow, advance.state)
        )
        reward_amount, milestone_items, _ = self._settle_rewards(
            uow,
            fact,
            advance.reached_milestones,
            world_completed=False,
        )
        world_reward_items: tuple[tuple[str, int], ...] = ()
        if world_completed:
            _, world_reward_items, replayed = self._settle_rewards(
                uow,
                fact,
                (),
                world_completed=True,
                settlement_id=_world_completion_settlement_id(
                    fact.character_id,
                    fact.world_id,
                ),
                source_id=f"{fact.character_id}:{fact.world_id}",
            )
            if replayed:
                world_reward_items = ()
        combined_items: dict[str, int] = {}
        for definition_id, quantity in (*milestone_items, *world_reward_items):
            combined_items[definition_id] = combined_items.get(definition_id, 0) + quantity
        reward_items = tuple(sorted(combined_items.items()))
        timestamp = fact.resolved_at.isoformat()
        uow.insert_transaction(
            transaction_id,
            fingerprint,
            fact.character_id,
            self.snapshots.codec.dumps(fact),
            timestamp,
        )
        self._update_ranking_projection(uow, fact, advance.state, advance.added_points)
        return WorldProgressAdvanceResult(
            "advanced",
            advance.state,
            advance.added_points,
            advance.reached_milestones,
            reward_amount,
            reward_items,
            world_completed,
        )

    def view(self, character_id: str, world_id: str) -> WorldProgressView:
        self.world_views.require(world_id)
        bound_region_ids = {
            binding.content_ref
            for binding in self.content.worlds.bindings_for_world(
                world_id,
                function_id="location.function.exploration",
            )
        }
        regions = tuple(
            region
            for region in self.content.exploration_regions.definitions()
            if region.id in bound_region_ids
        )
        with self.database.unit_of_work(write=False) as uow:
            values = tuple(
                self.snapshots.load(
                    uow,
                    self.storage.progress,
                    world_progress_state_id(character_id, world_id, region.id),
                    WorldProgressState,
                )
                for region in regions
            )
            claim = self.snapshots.require(
                uow,
                self.storage.reward_claim,
                character_id,
                RewardClaimState,
            )
        maximum = WORLD_PROGRESS_DEFINITION.maximum_points
        return WorldProgressView(
            character_id,
            world_id,
            tuple(
                WorldProgressRegionView(
                    region.id,
                    state.points if state else 0,
                    maximum,
                    state.victories if state else 0,
                    state.claimed_milestones if state else (),
                )
                for region, state in zip(regions, values)
            ),
            _world_completion_settlement_id(character_id, world_id) in claim.records,
        )

    def ranking_view(
        self,
        character_id: str,
        *,
        world_id: str | None,
        logical_time: datetime,
        limit: int = 10,
    ) -> WorldProgressRankingView:
        if limit < 1:
            raise ValueError("行纪排行显示数量必须大于 0")
        if world_id is not None:
            self.world_views.require(world_id)
        records = self.projections.records(
            WORLD_PROGRESS_PROJECTOR_ID,
            WORLD_PROGRESS_PARTITION_ID,
        )
        candidates = []
        payloads = {}
        for record in records:
            payload = dict(record.payload)
            if world_id is None:
                points = int(payload.get("points", 0))
                completed = int(payload.get("completed_regions", 0))
            else:
                world = dict(payload.get("worlds", {})).get(world_id, {})
                world = dict(world) if isinstance(world, dict) else {}
                points = int(world.get("points", 0))
                completed = int(world.get("completed_regions", 0))
            if points < 1:
                continue
            payloads[record.key] = (payload, points, completed)
            candidates.append(
                RankingCandidate(
                    record.key,
                    points * 1_000 + completed,
                    int(
                        payload.get("reached_at_us", 0)
                        if world_id is None
                        else world.get("reached_at_us", 0)
                    ),
                )
            )
        checkpoint = self.projections.checkpoint(
            WORLD_PROGRESS_PROJECTOR_ID,
            WORLD_PROGRESS_PARTITION_ID,
        )
        frozen = self.ranking.freeze(
            board_id="ranking.world_progress",
            scope_id=world_id or "all_worlds",
            period_id="permanent",
            version=1,
            direction=RankingDirection.DESCENDING,
            candidates=tuple(candidates),
            frozen_at=logical_time,
            through_fact_offset=checkpoint[0] if checkpoint else 0,
        )
        all_entries = tuple(
            _rank_entry(entry.rank, entry.subject_id, payloads[entry.subject_id])
            for entry in frozen.entries
        )
        own = next(
            (value for value in all_entries if value.character_id == character_id),
            None,
        )
        return WorldProgressRankingView(
            world_id,
            all_entries[:limit],
            own if own is not None and own.rank > limit else None,
        )

    def rebuild_ranking_projection(self, *, logical_time: datetime) -> int:
        """从行纪权威快照显式重建可丢弃的实时排名投影。"""

        with self.database.unit_of_work() as uow:
            states = self.snapshots.list(
                uow,
                self.storage.progress,
                WorldProgressState,
                limit=100_000,
            )
            grouped: dict[str, dict[str, object]] = {}
            for state in states:
                payload = grouped.setdefault(
                    state.character_id,
                    _empty_ranking_payload(state.character_name),
                )
                _add_state_to_ranking_payload(payload, state)
            self.projections.initialize_in_uow(
                uow,
                WORLD_PROGRESS_PROJECTOR_ID,
                WORLD_PROGRESS_PARTITION_ID,
                logical_time=logical_time,
            )
            checkpoint = self.projections.checkpoint_in_uow(
                uow,
                WORLD_PROGRESS_PROJECTOR_ID,
                WORLD_PROGRESS_PARTITION_ID,
            )
            assert checkpoint is not None
            existing = self.projections.records_in_uow(
                uow,
                WORLD_PROGRESS_PROJECTOR_ID,
                WORLD_PROGRESS_PARTITION_ID,
            )
            maximum = self.projections.maximum_fact_offset_in_uow(uow)
            self.projections.commit_in_uow(
                uow,
                WORLD_PROGRESS_PROJECTOR_ID,
                WORLD_PROGRESS_PARTITION_ID,
                expected_revision=checkpoint[1],
                through_fact_offset=maximum,
                updates=grouped,
                deletes=tuple(
                    record.key for record in existing if record.key not in grouped
                ),
                logical_time=logical_time,
            )
            uow.commit()
        return len(grouped)

    def _settle_rewards(
        self,
        uow,
        fact,
        milestones: tuple[int, ...],
        *,
        world_completed: bool,
        settlement_id: str | None = None,
        source_id: str | None = None,
    ) -> tuple[int, tuple[tuple[str, int], ...], bool]:
        amount = sum(
            milestone.currency_amount
            for milestone in WORLD_PROGRESS_DEFINITION.milestones
            if milestone.percent in milestones
        )
        item_quantities: dict[str, int] = {}
        for milestone in WORLD_PROGRESS_DEFINITION.milestones:
            if milestone.percent not in milestones:
                continue
            for reward in milestone.item_rewards:
                item_quantities[reward.definition_id] = (
                    item_quantities.get(reward.definition_id, 0) + reward.quantity
                )
        if world_completed:
            for reward in WORLD_PROGRESS_DEFINITION.world_completion_rewards:
                item_quantities[reward.definition_id] = (
                    item_quantities.get(reward.definition_id, 0) + reward.quantity
                )
        reward_items = tuple(sorted(item_quantities.items()))
        if amount == 0 and not reward_items:
            return 0, (), False

        ledger = self.snapshots.require(
            uow,
            self.storage.ledger,
            PRIMARY_LEDGER_ID,
            LedgerState,
        )
        claim = self.snapshots.require(
            uow,
            self.storage.reward_claim,
            fact.character_id,
            RewardClaimState,
        )
        rewards: list[object] = []
        ledger_revisions = {}
        if amount:
            wallet = _wallet(ledger, fact.character_id)
            issuer = ledger.accounts[PRIMARY_ISSUER_ACCOUNT_ID]
            rewards.append(CurrencyReward(issuer.id, wallet.id, amount))
            ledger_revisions = {
                issuer.id: issuer.revision,
                wallet.id: wallet.revision,
            }

        inventory_revision = None
        if reward_items:
            inventory = self.snapshots.require(
                uow,
                self.storage.inventory,
                fact.character_id,
                InventoryState,
            )
            special_container_id = next(
                value.id
                for value in inventory.containers.values()
                if value.kind == "container.special"
            )
            for definition_id, quantity in reward_items:
                self.content.catalog.items.require(definition_id)
                existing = next(
                    (
                        value
                        for value in inventory.stacks.values()
                        if value.definition_id == definition_id
                        and value.container_id == special_container_id
                    ),
                    None,
                )
                rewards.append(
                    StackItemReward(
                        existing.id
                        if existing is not None
                        else f"stack:{fact.character_id}:{definition_id}",
                        definition_id,
                        special_container_id,
                        quantity,
                        {
                            "world_id": fact.world_id,
                            "region_id": fact.region_id,
                        },
                    )
                )
            inventory_revision = inventory.revision

        settlement = RewardSettlement(
            settlement_id or f"world-progress-reward:{fact.event_id}",
            fact.character_id,
            fact.character_id,
            WORLD_PROGRESS_SOURCE_KIND,
            source_id or fact.event_id,
            tuple(rewards),
            RewardExpectations(
                claim_revision=claim.revision,
                inventory_revision=inventory_revision,
                ledger_account_revisions=ledger_revisions,
            ),
            {
                "world_id": fact.world_id,
                "region_id": fact.region_id,
                "milestones": milestones,
                "world_completed": world_completed,
            },
        )
        outcome = self.reward_settlement.settle_in_uow(
            uow,
            settlement,
            self.reward_keys_factory(fact.character_id, PRIMARY_LEDGER_ID),
            context=_context(fact.event_id, fact.resolved_at),
        )
        if outcome.failure or outcome.value is None:
            raise RuntimeError(
                outcome.failure.message if outcome.failure else "行纪阶段奖励入账失败"
            )
        return amount, reward_items, outcome.value.replayed

    def _world_completed_in_uow(self, uow, current: WorldProgressState) -> bool:
        region_ids = {
            binding.content_ref
            for binding in self.content.worlds.bindings_for_world(
                current.world_id,
                function_id="location.function.exploration",
            )
        }
        if not region_ids or current.region_id not in region_ids:
            return False
        maximum = WORLD_PROGRESS_DEFINITION.maximum_points
        for region_id in region_ids:
            if region_id == current.region_id:
                state = current
            else:
                state = self.snapshots.load(
                    uow,
                    self.storage.progress,
                    world_progress_state_id(
                        current.character_id,
                        current.world_id,
                        region_id,
                    ),
                    WorldProgressState,
                )
            if state is None or state.points < maximum:
                return False
        return True

    def _update_ranking_projection(self, uow, fact, state, added_points) -> None:
        self.projections.initialize_in_uow(
            uow,
            WORLD_PROGRESS_PROJECTOR_ID,
            WORLD_PROGRESS_PARTITION_ID,
            logical_time=fact.resolved_at,
        )
        checkpoint = self.projections.checkpoint_in_uow(
            uow,
            WORLD_PROGRESS_PROJECTOR_ID,
            WORLD_PROGRESS_PARTITION_ID,
        )
        assert checkpoint is not None
        current = self.projections.record_in_uow(
            uow,
            WORLD_PROGRESS_PROJECTOR_ID,
            WORLD_PROGRESS_PARTITION_ID,
            fact.character_id,
        )
        payload = (
            dict(current.payload)
            if current is not None
            else _empty_ranking_payload(fact.character_name)
        )
        worlds = {
            key: dict(value)
            for key, value in dict(payload.get("worlds", {})).items()
        }
        world = worlds.setdefault(
            fact.world_id,
            {"points": 0, "completed_regions": 0, "reached_at_us": 0},
        )
        world["points"] = int(world.get("points", 0)) + added_points
        completed_now = int(
            state.points == WORLD_PROGRESS_DEFINITION.maximum_points
            and state.points - added_points < WORLD_PROGRESS_DEFINITION.maximum_points
        )
        world["completed_regions"] = int(world.get("completed_regions", 0)) + completed_now
        world["reached_at_us"] = int(fact.resolved_at.timestamp() * 1_000_000)
        payload.update(
            {
                "character_name": fact.character_name,
                "points": int(payload.get("points", 0)) + added_points,
                "completed_regions": int(payload.get("completed_regions", 0)) + completed_now,
                "worlds": worlds,
                "reached_at_us": int(fact.resolved_at.timestamp() * 1_000_000),
            }
        )
        self.projections.commit_in_uow(
            uow,
            WORLD_PROGRESS_PROJECTOR_ID,
            WORLD_PROGRESS_PARTITION_ID,
            expected_revision=checkpoint[1],
            through_fact_offset=self.projections.maximum_fact_offset_in_uow(uow),
            updates={fact.character_id: payload},
            logical_time=fact.resolved_at,
        )


def _empty_ranking_payload(character_name: str) -> dict[str, object]:
    return {
        "character_name": character_name,
        "points": 0,
        "completed_regions": 0,
        "worlds": {},
        "reached_at_us": 0,
    }


def _add_state_to_ranking_payload(payload: dict[str, object], state: WorldProgressState) -> None:
    worlds = payload["worlds"]
    assert isinstance(worlds, dict)
    world = worlds.setdefault(
        state.world_id,
        {"points": 0, "completed_regions": 0, "reached_at_us": 0},
    )
    world["points"] += state.points
    completed = int(state.points >= WORLD_PROGRESS_DEFINITION.maximum_points)
    world["completed_regions"] += completed
    payload["points"] = int(payload["points"]) + state.points
    payload["completed_regions"] = int(payload["completed_regions"]) + completed
    if state.reached_at is not None:
        world["reached_at_us"] = max(
            int(world["reached_at_us"]),
            int(state.reached_at.timestamp() * 1_000_000),
        )
        payload["reached_at_us"] = max(
            int(payload["reached_at_us"]),
            int(state.reached_at.timestamp() * 1_000_000),
        )


def _rank_entry(rank: int, character_id: str, values) -> WorldProgressRankEntry:
    payload, points, completed = values
    return WorldProgressRankEntry(
        rank,
        character_id,
        str(payload.get("character_name", character_id)),
        points,
        completed,
    )


def _wallet(ledger: LedgerState, character_id: str):
    try:
        return next(
            account
            for account in ledger.accounts.values()
            if account.kind is LedgerAccountKind.STANDARD
            and account.owner_kind == "owner.character"
            and account.owner_id == character_id
            and account.currency_id == PRIMARY_CURRENCY_ID
        )
    except StopIteration as exc:
        raise ValueError("当前角色缺少主货币钱包") from exc


def _context(event_id: str, logical_time: datetime) -> RuleContext:
    return RuleContext(
        f"world-progress:{event_id}",
        WORLD_PROGRESS_RULESET_VERSION,
        Ruleset("ruleset.world_progress"),
        logical_time,
        SeededRandomSource(event_id),
    )


def _fact_fingerprint(fact: ExplorationVictoryFact) -> str:
    payload = "|".join(
        (
            fact.character_id,
            fact.character_name,
            fact.world_id,
            fact.region_id,
            fact.encounter_kind,
            fact.resolved_at.isoformat(),
        )
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _world_completion_settlement_id(character_id: str, world_id: str) -> str:
    return f"world-progress-world-completion:v1:{character_id}:{world_id}"


__all__ = [
    "WORLD_PROGRESS_FACT_KIND",
    "WORLD_PROGRESS_PARTITION_ID",
    "WORLD_PROGRESS_PROJECTOR_ID",
    "WorldProgressFeature",
]
