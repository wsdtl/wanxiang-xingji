"""公开兑换码、随机开荒装备与统一权益结算的跨域协调。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from game.content.catalog import PRIMARY_CURRENCY_ID
from game.content.catalog.redemption_code import RedemptionCodeOfferDefinition
from game.content.catalog.weapon.mechanics import WEAPON_MAXIMUM_LEVEL_TABLE
from game.core.gameplay import (
    EquipmentState,
    InventoryState,
    LedgerAccountKind,
    LedgerState,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    WEAPON_SLOT_ID,
    WeaponState,
)
from game.core.gameplay.grants import (
    GrantCampaign,
    GrantRedemptionCommand,
    GrantRewardBundle,
    normalize_grant_code,
)
from game.core.gameplay.rewards import (
    CurrencyReward,
    GeneratedEquipmentReward,
    GeneratedWeaponReward,
    RewardClaimState,
    RewardExpectations,
)
from game.rules.character import PRIMARY_ISSUER_ACCOUNT_ID, PRIMARY_LEDGER_ID
from game.rules.equipment import EquipmentGenerationRequest, EquipmentInstanceGenerator
from game.rules.weapon import WeaponGenerationRequest, WeaponInstanceGenerator

from .models import RedemptionCodeItem, RedemptionCodeResult


REDEMPTION_CODE_RULE_VERSION = "rules.redemption_code.v1"


@dataclass(frozen=True)
class RedemptionCodeStorageKinds:
    inventory: str
    ledger: str
    reward_claim: str

    def __post_init__(self) -> None:
        if any(not str(value or "").strip() for value in (self.inventory, self.ledger, self.reward_claim)):
            raise ValueError("兑换码玩法缺少持久化聚合类型")


class RedemptionCodeFeature:
    """把可信代码配置解析为账号权益和角色资产奖励。"""

    def __init__(
        self,
        database,
        content,
        snapshots,
        grants,
        storage: RedemptionCodeStorageKinds,
        reward_keys_factory,
        offers: tuple[RedemptionCodeOfferDefinition, ...],
    ) -> None:
        if not offers:
            raise ValueError("兑换码玩法至少需要一份正式奖励定义")
        self.database = database
        self.content = content
        self.snapshots = snapshots
        self.grants = grants
        self.storage = storage
        self.reward_keys_factory = reward_keys_factory
        self.offers = tuple(offers)
        self._offers_by_code = {value.code: value for value in self.offers}
        if len(self._offers_by_code) != len(self.offers):
            raise ValueError("兑换码正式内容存在重复代码")
        if len({value.campaign_id for value in self.offers}) != len(self.offers):
            raise ValueError("兑换码正式内容存在重复活动 ID")
        catalog = content.catalog
        self.equipment_generator = EquipmentInstanceGenerator(
            catalog.equipment,
            catalog.itemization_engine,
        )
        self.weapon_generator = WeaponInstanceGenerator(
            catalog.weapons,
            catalog.itemization_engine,
            WEAPON_MAXIMUM_LEVEL_TABLE,
        )

    def initialize(self, *, logical_time: datetime) -> None:
        _require_aware(logical_time)
        for offer in self.offers:
            campaign = GrantCampaign(
                offer.campaign_id,
                1,
                "issuer.operations",
                offer.source_kind,
                offer.offer_id,
                offer.offer_version,
                offer.policy,
                offer.per_account_limit,
                offer.total_limit,
                offer.starts_at,
                offer.ends_at,
                metadata={"redemption.offer_definition_id": str(offer.id)},
            )
            self.grants.create_campaign(campaign, created_at=logical_time)
            self.grants.register_code(
                offer.credential_id,
                offer.campaign_id,
                offer.code,
                issued_at=offer.starts_at,
                expires_at=offer.ends_at,
                metadata={"redemption.offer_definition_id": str(offer.id)},
            )

    def redeem(
        self,
        character,
        code: object,
        operation_id: str,
        *,
        logical_time: datetime,
    ) -> RedemptionCodeResult:
        _require_aware(logical_time)
        operation_id = str(operation_id or "").strip()
        if not operation_id:
            return RedemptionCodeResult("rejected", failure_message="兑换请求缺少稳定身份")
        try:
            normalized_code = normalize_grant_code(code)
        except ValueError:
            return RedemptionCodeResult("invalid", failure_message="兑换码无效")
        offer = self._offers_by_code.get(normalized_code)
        if offer is None:
            return RedemptionCodeResult(
                "invalid",
                code=normalized_code,
                failure_message="兑换码无效",
            )
        if character.account_id.strip() == "" or character.id.strip() == "":
            return RedemptionCodeResult("rejected", failure_message="当前角色身份无效")
        if self.grants.find_account_redemption(offer.campaign_id, character.account_id) is not None:
            return RedemptionCodeResult(
                "already_redeemed",
                code=normalized_code,
                failure_message="当前账号已经领取过该兑换码",
            )

        inventory, ledger, claims = self._reward_state(character.id, character.account_id)
        armory_id = _container_id(inventory, "container.armory", character.id)
        wallet = _wallet(ledger, character.id)
        issuer = ledger.accounts[PRIMARY_ISSUER_ACCOUNT_ID]
        generation_context = _generation_context(offer, character.account_id)
        generated = self._generate_items(
            offer,
            character.account_id,
            armory_id,
            context=generation_context,
        )
        rewards: list[object] = []
        if offer.currency_amount:
            rewards.append(CurrencyReward(issuer.id, wallet.id, offer.currency_amount))
        rewards.extend(value[0] for value in generated)
        bundle = GrantRewardBundle(
            tuple(rewards),
            RewardExpectations(
                claim_revision=claims.revision,
                inventory_revision=inventory.revision,
                ledger_account_revisions={
                    issuer.id: issuer.revision,
                    wallet.id: wallet.revision,
                },
            ),
            {
                "redemption.offer_definition_id": str(offer.id),
                "redemption.recipient_character_id": character.id,
            },
        )
        command = GrantRedemptionCommand(
            f"redemption:{operation_id}",
            offer.campaign_id,
            character.account_id,
        )
        outcome = self.grants.redeem_code(
            command,
            normalized_code,
            bundle,
            self.reward_keys_factory(character.id, PRIMARY_LEDGER_ID),
            context=RuleContext(
                command.id,
                REDEMPTION_CODE_RULE_VERSION,
                Ruleset("ruleset.redemption_code"),
                logical_time,
                SeededRandomSource(command.id),
            ),
        )
        if outcome.failure:
            return _failed_result(normalized_code, outcome.failure)
        assert outcome.value is not None
        final_inventory = outcome.value.reward.snapshot.inventory
        items = tuple(
            RedemptionCodeItem(
                kind,
                state,
                item_definition_id,
                slot_id,
                final_inventory.reference_number(state.asset_id),
            )
            for _, kind, state, item_definition_id, slot_id in generated
        )
        return RedemptionCodeResult(
            "redeemed",
            normalized_code,
            offer.currency_amount,
            items,
            replayed=outcome.value.replayed,
        )

    def _reward_state(
        self,
        character_id: str,
        account_id: str,
    ) -> tuple[InventoryState, LedgerState, RewardClaimState]:
        with self.database.unit_of_work(write=False) as uow:
            inventory = self.snapshots.require(
                uow,
                self.storage.inventory,
                character_id,
                InventoryState,
            )
            ledger = self.snapshots.require(
                uow,
                self.storage.ledger,
                PRIMARY_LEDGER_ID,
                LedgerState,
            )
            claims = self.snapshots.load(
                uow,
                self.storage.reward_claim,
                account_id,
                RewardClaimState,
            ) or RewardClaimState(account_id)
        return inventory, ledger, claims

    def _generate_items(
        self,
        offer: RedemptionCodeOfferDefinition,
        account_id: str,
        armory_id: str,
        *,
        context: RuleContext,
    ) -> tuple[tuple[object, str, EquipmentState | WeaponState, str, str], ...]:
        values: list[tuple[object, str, EquipmentState | WeaponState, str, str]] = []
        weapon_ids = tuple(
            value
            for value in self.content.catalog.weapons.definitions.ids()
            if self.content.catalog.weapons.require(value).generation_profile_id is not None
        )
        for index in range(offer.weapon_count):
            definition_id, state = self._generate_common_weapon(
                offer,
                weapon_ids,
                _asset_id(offer.campaign_id, account_id, f"weapon:{index}"),
                index,
                context=context,
            )
            definition = self.content.catalog.weapons.require(definition_id)
            reward = GeneratedWeaponReward(
                state,
                definition.item_definition_id,
                armory_id,
                {"redemption.offer_definition_id": str(offer.id)},
            )
            values.append((reward, "weapon", state, str(definition.item_definition_id), WEAPON_SLOT_ID))

        definitions = tuple(self.content.catalog.equipment.definitions)
        for slot_id in offer.equipment_slot_ids:
            candidates = tuple(
                value for value in definitions if value.slot_id == slot_id
            )
            definition_id, state = self._generate_common_equipment(
                offer,
                tuple(str(value.id) for value in candidates),
                _asset_id(offer.campaign_id, account_id, str(slot_id)),
                str(slot_id),
                context=context,
            )
            definition = self.content.catalog.equipment.require(definition_id)
            reward = GeneratedEquipmentReward(
                state,
                definition.item_definition_id,
                armory_id,
                {"redemption.offer_definition_id": str(offer.id)},
            )
            values.append(
                (reward, "equipment", state, str(definition.item_definition_id), str(slot_id))
            )
        return tuple(values)

    def _generate_common_equipment(
        self,
        offer: RedemptionCodeOfferDefinition,
        definition_ids: tuple[str, ...],
        asset_id: str,
        slot_id: str,
        *,
        context: RuleContext,
    ) -> tuple[str, EquipmentState]:
        remaining = list(definition_ids)
        while remaining:
            definition_id = context.random.choice(tuple(remaining))
            remaining.remove(definition_id)
            for attempt in range(1, offer.generation_attempt_limit + 1):
                state = self.equipment_generator.generate(
                    EquipmentGenerationRequest(
                        f"redemption:{offer.id}:equipment:{slot_id}:{definition_id}:{attempt}",
                        asset_id,
                        definition_id,
                        self.content.catalog.report.content_fingerprint,
                    ),
                    context=context,
                ).state
                if state.quality_id == offer.equipment_quality_id:
                    return definition_id, state
        raise RuntimeError(f"兑换码装备在限定次数内未生成目标品质：{slot_id}")

    def _generate_common_weapon(
        self,
        offer: RedemptionCodeOfferDefinition,
        definition_ids: tuple[str, ...],
        asset_id: str,
        index: int,
        *,
        context: RuleContext,
    ) -> tuple[str, WeaponState]:
        remaining = list(definition_ids)
        while remaining:
            definition_id = context.random.choice(tuple(remaining))
            remaining.remove(definition_id)
            for attempt in range(1, offer.generation_attempt_limit + 1):
                state = self.weapon_generator.generate(
                    WeaponGenerationRequest(
                        f"redemption:{offer.id}:weapon:{index}:{definition_id}:{attempt}",
                        asset_id,
                        definition_id,
                        self.content.catalog.report.content_fingerprint,
                    ),
                    context=context,
                ).state
                if state.quality_id == offer.weapon_quality_id:
                    return definition_id, state
        raise RuntimeError(f"兑换码武器在限定次数内未生成目标品质：{index}")


def _generation_context(
    offer: RedemptionCodeOfferDefinition,
    account_id: str,
) -> RuleContext:
    seed = f"{offer.id}:{offer.offer_version}:{account_id}"
    return RuleContext(
        f"redemption-generation:{offer.id}:{account_id}",
        REDEMPTION_CODE_RULE_VERSION,
        Ruleset("ruleset.redemption_code_generation"),
        offer.starts_at,
        SeededRandomSource(seed),
    )


def _asset_id(campaign_id: str, account_id: str, slot_key: str) -> str:
    payload = "\0".join(("redemption-asset.v1", campaign_id, account_id, slot_key))
    return f"asset:redemption:{sha256(payload.encode('utf-8')).hexdigest()[:32]}"


def _container_id(inventory: InventoryState, kind: str, owner_id: str) -> str:
    try:
        return next(
            value.id
            for value in inventory.containers.values()
            if value.kind == kind and value.owner_id == owner_id
        )
    except StopIteration as exc:
        raise ValueError(f"当前角色缺少目标容器：{kind}") from exc


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


def _failed_result(code: str, failure) -> RedemptionCodeResult:
    if failure.code in {"grant.account_limit_reached", "grant.entitlement_redeemed"}:
        status = "already_redeemed"
    elif failure.code == "grant.code_invalid":
        status = "invalid"
    elif failure.code in {
        "grant.campaign_unavailable",
        "grant.campaign_not_started",
        "grant.campaign_expired",
        "grant.credential_revoked",
        "grant.credential_expired",
        "grant.credential_limit_reached",
    }:
        status = "unavailable"
    else:
        status = "rejected"
    return RedemptionCodeResult(
        status,
        code=code,
        failure_code=failure.code,
        failure_message=failure.message,
    )


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("兑换码逻辑时间必须包含时区")


__all__ = [
    "REDEMPTION_CODE_RULE_VERSION",
    "RedemptionCodeFeature",
    "RedemptionCodeStorageKinds",
]
