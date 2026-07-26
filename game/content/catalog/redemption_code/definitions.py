"""公开兑换码的活动限制与可信奖励内容。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from game.core.gameplay import (
    ACCESSORY_SLOT_ID,
    BODY_SLOT_ID,
    EQUIPMENT_SLOT_IDS,
    FEET_SLOT_ID,
    HANDS_SLOT_ID,
    HEAD_SLOT_ID,
    StableId,
    WAIST_SLOT_ID,
    stable_id,
)
from game.core.gameplay.grants import GrantRedemptionPolicy, normalize_grant_code

from ..foundation import COMMON_QUALITY_ID


@dataclass(frozen=True)
class RedemptionCodeOfferDefinition:
    """一个公开代码对应的不可变活动版本和奖励约束。"""

    id: StableId
    code: str
    campaign_id: str
    credential_id: str
    source_kind: StableId
    offer_id: StableId
    offer_version: int
    policy: GrantRedemptionPolicy
    per_account_limit: int
    total_limit: int | None
    starts_at: datetime
    ends_at: datetime | None
    currency_amount: int
    equipment_quality_id: StableId
    equipment_slot_ids: tuple[StableId, ...]
    weapon_count: int
    weapon_quality_id: StableId
    generation_attempt_limit: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", stable_id(self.id, field="redemption offer id"))
        object.__setattr__(self, "code", normalize_grant_code(self.code))
        for field_name in ("campaign_id", "credential_id"):
            value = str(getattr(self, field_name) or "").strip()
            if not value:
                raise ValueError(f"兑换码活动缺少 {field_name}")
            object.__setattr__(self, field_name, value)
        object.__setattr__(self, "source_kind", stable_id(self.source_kind, field="source kind"))
        object.__setattr__(self, "offer_id", stable_id(self.offer_id, field="grant offer id"))
        object.__setattr__(self, "policy", GrantRedemptionPolicy(self.policy))
        if self.offer_version < 1 or self.per_account_limit < 1:
            raise ValueError("兑换码奖励版本和账号额度必须大于零")
        if self.total_limit is not None and self.total_limit < 1:
            raise ValueError("兑换码全服额度必须大于零")
        for field_name in ("starts_at", "ends_at"):
            value = getattr(self, field_name)
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"兑换码活动 {field_name} 必须包含时区")
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("兑换码活动结束时间必须晚于开始时间")
        if self.currency_amount < 0 or self.weapon_count < 0:
            raise ValueError("兑换码货币和武器数量不能小于零")
        slots = tuple(stable_id(value, field="equipment slot id") for value in self.equipment_slot_ids)
        if not slots or len(slots) != len(set(slots)):
            raise ValueError("兑换码装备槽必须非空且不能重复")
        if not set(slots).issubset(EQUIPMENT_SLOT_IDS):
            raise ValueError("兑换码装备槽不能包含武器或未知槽位")
        object.__setattr__(self, "equipment_slot_ids", slots)
        object.__setattr__(
            self,
            "equipment_quality_id",
            stable_id(self.equipment_quality_id, field="equipment quality id"),
        )
        object.__setattr__(
            self,
            "weapon_quality_id",
            stable_id(self.weapon_quality_id, field="weapon quality id"),
        )
        if self.generation_attempt_limit < 1:
            raise ValueError("兑换码装备生成尝试次数必须大于零")
        if self.currency_amount == 0 and not slots and self.weapon_count == 0:
            raise ValueError("兑换码奖励不能为空")


VIP666_REDEMPTION_OFFER = RedemptionCodeOfferDefinition(
    id="redemption_offer.vip666.v1",
    code="VIP666",
    campaign_id="campaign.vip666.launch.v1",
    credential_id="credential.vip666.launch.v1",
    source_kind="source.grant_code",
    offer_id="offer.vip666.launch",
    offer_version=1,
    policy=GrantRedemptionPolicy.PER_ACCOUNT,
    per_account_limit=1,
    total_limit=None,
    starts_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    ends_at=None,
    currency_amount=5_000,
    equipment_quality_id=COMMON_QUALITY_ID,
    equipment_slot_ids=(
        HEAD_SLOT_ID,
        BODY_SLOT_ID,
        HANDS_SLOT_ID,
        WAIST_SLOT_ID,
        FEET_SLOT_ID,
        ACCESSORY_SLOT_ID,
    ),
    weapon_count=1,
    weapon_quality_id=COMMON_QUALITY_ID,
    generation_attempt_limit=64,
)


REDEMPTION_CODE_OFFERS = (VIP666_REDEMPTION_OFFER,)


__all__ = [
    "REDEMPTION_CODE_OFFERS",
    "VIP666_REDEMPTION_OFFER",
    "RedemptionCodeOfferDefinition",
]
