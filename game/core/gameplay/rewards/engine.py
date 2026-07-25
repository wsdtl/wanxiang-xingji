"""跨领域奖励预检、原子结算和防重复领取。"""

from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from typing import Mapping

from ..character import CharacterEngine, CharacterTransaction
from ..context import RuleContext
from ..economy import LedgerEngine, LedgerTransaction
from ..errors import RuleFailure, RuleOutcome, RuleViolation
from ..events import RuleEvent
from ..inventory import InventoryEngine, InventoryTransaction, UpdateInstance
from ..weapon import (
    WeaponEngine,
    WeaponExperienceTransaction,
    weapon_state_data,
)
from .models import (
    RewardClaimRecord,
    RewardClaimState,
    RewardDisposition,
    RewardReceipt,
    RewardSettlement,
    RewardSettlementExecution,
    RewardSettlementPreview,
    RewardSettlementSnapshot,
)
from .planning import RewardPlannerRegistry


class RewardSettlementEngine:
    """组合既有领域引擎，但不接管它们的状态或业务规则。"""

    def __init__(
        self,
        *,
        inventory: InventoryEngine,
        ledger: LedgerEngine,
        character: CharacterEngine,
        weapon: WeaponEngine,
        planners: RewardPlannerRegistry | None = None,
    ) -> None:
        self.inventory = inventory
        self.ledger = ledger
        self.character = character
        self.weapon = weapon
        self.planners = planners or RewardPlannerRegistry.with_defaults()
        if not self.planners.finalized:
            self.planners.finalize()

    def preflight(
        self,
        settlement: RewardSettlement,
        *,
        snapshot: RewardSettlementSnapshot,
        context: RuleContext,
    ) -> RuleOutcome[RewardSettlementPreview]:
        """执行完整规则但不登记领取；返回值只能用于展示和确认。"""

        checkpoint = context.random.checkpoint()
        outcome = self._run(
            settlement,
            snapshot=snapshot,
            context=context,
            record_claim=False,
            preview=True,
        )
        context.random.restore(checkpoint)
        if outcome.failure:
            return RuleOutcome.failed(outcome.failure)
        assert outcome.value is not None
        return RuleOutcome.success(
            RewardSettlementPreview(
                outcome.value.settlement_id,
                outcome.value.receipt,
                outcome.value.events,
                outcome.value.replayed,
            )
        )

    def settle(
        self,
        settlement: RewardSettlement,
        *,
        snapshot: RewardSettlementSnapshot,
        context: RuleContext,
    ) -> RuleOutcome[RewardSettlementExecution]:
        return self._run(
            settlement,
            snapshot=snapshot,
            context=context,
            record_claim=True,
            preview=False,
        )

    def _run(
        self,
        settlement: RewardSettlement,
        *,
        snapshot: RewardSettlementSnapshot,
        context: RuleContext,
        record_claim: bool,
        preview: bool,
    ) -> RuleOutcome[RewardSettlementExecution]:
        fingerprint = reward_fingerprint(settlement)
        if snapshot.claims.scope_id != settlement.claim_scope_id:
            return RuleOutcome.failed(
                RuleFailure(
                    "reward.claim_scope_mismatch",
                    "奖励领取记录不属于本次结算作用域",
                    {
                        "expected": settlement.claim_scope_id,
                        "actual": snapshot.claims.scope_id,
                    },
                )
            )
        previous = snapshot.claims.records.get(settlement.id)
        if previous is not None:
            if previous.fingerprint != fingerprint:
                return RuleOutcome.failed(
                    RuleFailure(
                        "reward.settlement_mismatch",
                        "同一个奖励结算 id 携带了不同奖励内容",
                        {"settlement_id": settlement.id},
                    )
                )
            return RuleOutcome.success(
                RewardSettlementExecution(
                    settlement.id,
                    snapshot,
                    previous.receipt,
                    (),
                    replayed=True,
                    preview=preview,
                )
            )

        checkpoint = context.random.checkpoint()
        try:
            if snapshot.claims.revision != settlement.expectations.claim_revision:
                self._fail(
                    "reward.claim_revision_conflict",
                    "奖励领取记录 revision 已变化",
                    {
                        "expected": settlement.expectations.claim_revision,
                        "actual": snapshot.claims.revision,
                    },
                )
            plan = self.planners.plan(settlement, snapshot, context.logical_time)
            self._validate_expectations(settlement, snapshot, plan)
            result = self._execute_plan(settlement, snapshot, plan, context)
            if result.failure:
                context.random.restore(checkpoint)
                return RuleOutcome.failed(result.failure)
            assert result.value is not None
            inventory_state, ledger_state, characters, weapons, events, transaction_ids = result.value
            receipt = RewardReceipt(
                settlement.id,
                fingerprint,
                settlement.source_kind,
                settlement.source_id,
                context.logical_time,
                plan.lines,
                transaction_ids,
            )
            claims = snapshot.claims
            if record_claim:
                revision = claims.revision + 1
                records = dict(claims.records)
                records[settlement.id] = RewardClaimRecord(
                    settlement.id,
                    fingerprint,
                    receipt,
                    revision,
                )
                claims = RewardClaimState(claims.scope_id, records, revision)
            completion = RuleEvent.from_context(
                context,
                kind="reward.settlement.completed",
                source_id=settlement.source_id,
                target_id=settlement.claim_scope_id,
                subject_id=settlement.source_kind,
                values={
                    "settlement_id": settlement.id,
                    "reward_count": len(plan.lines),
                    "granted_count": sum(
                        line.disposition is RewardDisposition.GRANTED for line in plan.lines
                    ),
                    "skipped_count": sum(
                        line.disposition is RewardDisposition.SKIPPED for line in plan.lines
                    ),
                    "preview": preview,
                },
            )
            result_snapshot = RewardSettlementSnapshot(
                inventory_state,
                ledger_state,
                characters,
                weapons,
                claims,
            )
            return RuleOutcome.success(
                RewardSettlementExecution(
                    settlement.id,
                    result_snapshot,
                    receipt,
                    (*events, completion),
                    preview=preview,
                )
            )
        except RuleViolation as exc:
            context.random.restore(checkpoint)
            return RuleOutcome.failed(exc.failure)

    def _execute_plan(self, settlement, snapshot, plan, context):
        inventory_state = snapshot.inventory
        ledger_state = snapshot.ledger
        characters = dict(snapshot.characters)
        weapons = dict(snapshot.weapons)
        events: list[RuleEvent] = []
        transaction_ids: list[str] = []

        for asset_id, state in plan.generated_weapons.items():
            if asset_id in weapons:
                return RuleOutcome.failed(
                    RuleFailure(
                        "reward.weapon_exists",
                        "生成武器资产 id 已经存在",
                        {"asset_id": asset_id},
                    )
                )
            weapons[asset_id] = state

        if plan.ledger_operations:
            transaction_id = f"{settlement.id}:ledger"
            outcome = self.ledger.execute(
                LedgerTransaction(
                    transaction_id,
                    settlement.actor_id,
                    "reward.settlement",
                    plan.ledger_operations,
                    settlement.expectations.ledger_account_revisions,
                    {"reward_settlement_id": settlement.id},
                ),
                state=ledger_state,
                context=context,
            )
            if outcome.failure:
                return RuleOutcome.failed(outcome.failure)
            assert outcome.value is not None
            ledger_state = outcome.value.state
            events.extend(outcome.value.events)
            transaction_ids.append(transaction_id)

        for character_id in sorted(plan.character_operations):
            transaction_id = f"{settlement.id}:character:{character_id}"
            outcome = self.character.execute(
                CharacterTransaction(
                    transaction_id,
                    settlement.actor_id,
                    settlement.expectations.character_revisions[character_id],
                    "reward.settlement",
                    plan.character_operations[character_id],
                ),
                state=characters[character_id],
                context=context,
            )
            if outcome.failure:
                return RuleOutcome.failed(outcome.failure)
            assert outcome.value is not None
            characters[character_id] = outcome.value.state
            events.extend(outcome.value.events)
            transaction_ids.append(transaction_id)

        for asset_id in sorted(plan.weapon_experience):
            transaction_id = f"{settlement.id}:weapon:{asset_id}"
            outcome = self.weapon.grant_experience(
                WeaponExperienceTransaction(
                    transaction_id,
                    settlement.actor_id,
                    settlement.expectations.weapon_revisions[asset_id],
                    plan.weapon_experience[asset_id],
                    settlement.source_kind,
                    settlement.source_id,
                ),
                state=weapons[asset_id],
                context=context,
            )
            if outcome.failure:
                return RuleOutcome.failed(outcome.failure)
            assert outcome.value is not None
            weapons[asset_id] = outcome.value.state
            events.extend(outcome.value.events)
            transaction_ids.append(transaction_id)

        inventory_operations = list(plan.inventory_operations)
        for asset_id in sorted(plan.weapon_experience):
            try:
                instance = inventory_state.instances[asset_id]
            except KeyError:
                return RuleOutcome.failed(
                    RuleFailure(
                        "reward.weapon_instance_missing",
                        "武器成长目标不在角色武库中",
                        {"asset_id": asset_id},
                    )
                )
            embedded = instance.data.get("weapon.state")
            if embedded is not None and embedded != snapshot.weapons[asset_id]:
                return RuleOutcome.failed(
                    RuleFailure(
                        "reward.weapon_state_mismatch",
                        "武器聚合状态与武库实例状态不一致",
                        {"asset_id": asset_id},
                    )
                )
            inventory_operations.append(
                UpdateInstance(
                    replace(
                        instance,
                        data={**instance.data, **weapon_state_data(weapons[asset_id])},
                    ),
                    instance.revision,
                )
            )

        if inventory_operations:
            transaction_id = f"{settlement.id}:inventory"
            outcome = self.inventory.execute(
                InventoryTransaction(
                    transaction_id,
                    settlement.actor_id,
                    "reward.settlement",
                    tuple(inventory_operations),
                ),
                state=inventory_state,
                context=context,
            )
            if outcome.failure:
                return RuleOutcome.failed(outcome.failure)
            assert outcome.value is not None
            inventory_state = outcome.value.state
            events.extend(outcome.value.events)
            transaction_ids.append(transaction_id)

        return RuleOutcome.success(
            (
                inventory_state,
                ledger_state,
                characters,
                weapons,
                tuple(events),
                tuple(transaction_ids),
            )
        )

    @staticmethod
    def _validate_expectations(settlement, snapshot, plan) -> None:
        expectations = settlement.expectations
        if plan.inventory_operations:
            if expectations.inventory_revision is None:
                RewardSettlementEngine._fail(
                    "reward.inventory_revision_required",
                    "物品奖励必须提供库存 revision",
                )
            if expectations.inventory_revision != snapshot.inventory.revision:
                RewardSettlementEngine._fail(
                    "reward.inventory_revision_conflict",
                    "库存 revision 已变化",
                    {
                        "expected": expectations.inventory_revision,
                        "actual": snapshot.inventory.revision,
                    },
                )
        elif expectations.inventory_revision is not None:
            RewardSettlementEngine._fail(
                "reward.unused_inventory_revision",
                "结算没有物品奖励却提供了库存 revision",
            )

        RewardSettlementEngine._exact_revision_keys(
            "character",
            set(plan.character_operations),
            expectations.character_revisions,
        )
        RewardSettlementEngine._exact_revision_keys(
            "weapon",
            set(plan.weapon_experience),
            expectations.weapon_revisions,
        )
        if set(plan.generated_weapons) & set(snapshot.weapons):
            RewardSettlementEngine._fail(
                "reward.weapon_exists",
                "生成武器资产 id 已经存在",
            )
        for character_id in plan.character_operations:
            actual = snapshot.characters[character_id].revision
            expected = expectations.character_revisions[character_id]
            if actual != expected:
                RewardSettlementEngine._fail(
                    "reward.character_revision_conflict",
                    "角色 revision 已变化",
                    {"character_id": character_id, "expected": expected, "actual": actual},
                )
        for asset_id in plan.weapon_experience:
            actual = snapshot.weapons[asset_id].revision
            expected = expectations.weapon_revisions[asset_id]
            if actual != expected:
                RewardSettlementEngine._fail(
                    "reward.weapon_revision_conflict",
                    "武器 revision 已变化",
                    {"asset_id": asset_id, "expected": expected, "actual": actual},
                )
        if not plan.ledger_operations and expectations.ledger_account_revisions:
            RewardSettlementEngine._fail(
                "reward.unused_ledger_revision",
                "结算没有货币奖励却提供了账本账户 revision",
            )

    @staticmethod
    def _exact_revision_keys(domain, touched, revisions) -> None:
        actual = set(revisions)
        if actual != touched:
            RewardSettlementEngine._fail(
                f"reward.{domain}_revision_set_mismatch",
                f"{domain} revision 集合与本次奖励目标不一致",
                {
                    "missing": tuple(sorted(touched - actual)),
                    "unused": tuple(sorted(actual - touched)),
                },
            )

    @staticmethod
    def _fail(code, message, details=None) -> None:
        raise RuleViolation(code, message, details or {})


def reward_fingerprint(settlement: RewardSettlement) -> str:
    """只指纹化奖励语义，并发预期变化不改变领取身份。"""

    payload = {
        "id": settlement.id,
        "actor_id": settlement.actor_id,
        "claim_scope_id": settlement.claim_scope_id,
        "source_kind": settlement.source_kind,
        "source_id": settlement.source_id,
        "rewards": settlement.rewards,
        "metadata": settlement.metadata,
    }
    encoded = json.dumps(
        _canonical(payload),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def _canonical(value):
    if is_dataclass(value):
        return {item.name: _canonical(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_canonical(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"奖励指纹不支持元数据类型：{type(value).__name__}")


__all__ = ["RewardSettlementEngine", "reward_fingerprint"]
