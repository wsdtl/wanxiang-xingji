"""基于正式装备生成器执行词条、品质与套装价值审计。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from types import MappingProxyType
from typing import Mapping

from game.content.catalog.equipment.properties import EQUIPMENT_GENERATION_PROFILE_ID
from game.core.gameplay.context import RuleContext, Ruleset, SeededRandomSource
from game.core.gameplay.equipment.models import EquipmentCatalog
from game.core.gameplay.itemization.engine import ItemizationEngine
from game.core.gameplay.itemization.models import ItemGenerationCommand
from game.core.gameplay.valuation.engine import ValuationEngine


@dataclass(frozen=True)
class EquipmentBalanceReport:
    samples: int
    quality_counts: Mapping[str, int]
    property_counts: Mapping[str, int]
    tier_counts: Mapping[tuple[str, int], int]
    value_quantiles: Mapping[float, float]
    minimum_value: float
    maximum_value: float
    mean_value: float
    mean_attempts: float
    set_cumulative_values: Mapping[str, Mapping[int, float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "quality_counts", MappingProxyType(dict(self.quality_counts)))
        object.__setattr__(self, "property_counts", MappingProxyType(dict(self.property_counts)))
        object.__setattr__(self, "tier_counts", MappingProxyType(dict(self.tier_counts)))
        object.__setattr__(self, "value_quantiles", MappingProxyType(dict(self.value_quantiles)))
        object.__setattr__(
            self,
            "set_cumulative_values",
            MappingProxyType(
                {
                    key: MappingProxyType(dict(values))
                    for key, values in self.set_cumulative_values.items()
                }
            ),
        )

    def quality_ratio(self, quality_id: str) -> float:
        return self.quality_counts.get(quality_id, 0) / self.samples

    @property
    def missing_property_ids(self) -> tuple[str, ...]:
        return tuple(sorted(key for key, amount in self.property_counts.items() if amount == 0))


class EquipmentBalanceAuditor:
    """复用正式生成器和价值引擎，不运行完整战斗。"""

    def __init__(
        self,
        itemization: ItemizationEngine,
        valuation: ValuationEngine,
        equipment: EquipmentCatalog,
    ) -> None:
        self.itemization = itemization
        self.valuation = valuation
        self.equipment = equipment

    def audit(
        self,
        *,
        content_fingerprint: str,
        samples: int = 9216,
        seed: int = 0,
        logical_time: datetime = datetime(2000, 1, 1, tzinfo=timezone.utc),
    ) -> EquipmentBalanceReport:
        if samples < 1:
            raise ValueError("装备平衡审计样本数必须大于 0")
        if not content_fingerprint.strip():
            raise ValueError("装备平衡审计缺少内容指纹")
        profile = self.itemization.catalog.require_profile(EQUIPMENT_GENERATION_PROFILE_ID)
        quality_counts: dict[str, int] = {}
        property_counts = {property_id: 0 for property_id in profile.property_ids}
        tier_counts: dict[tuple[str, int], int] = {}
        values = []
        attempts = 0
        for sample in range(samples):
            sample_seed = _stable_seed(seed, sample)
            trace_id = f"equipment-balance:{seed}:{sample}"
            context = RuleContext(
                trace_id,
                "rules.equipment_balance_audit",
                Ruleset("ruleset.equipment_balance_audit"),
                logical_time,
                SeededRandomSource(sample_seed),
            )
            execution = self.itemization.generate(
                ItemGenerationCommand(
                    trace_id,
                    EQUIPMENT_GENERATION_PROFILE_ID,
                    content_fingerprint,
                ),
                context=context,
            )
            roll = execution.roll
            quality_counts[roll.quality_id] = quality_counts.get(roll.quality_id, 0) + 1
            values.append(roll.intrinsic_value.total)
            attempts += roll.receipt.attempts
            for rolled in roll.properties:
                property_counts[rolled.property_id] += 1
                key = (rolled.property_id, rolled.tier)
                tier_counts[key] = tier_counts.get(key, 0) + 1
        ordered = sorted(values)
        quantiles = {value: _quantile(ordered, value) for value in (0.45, 0.76, 0.91, 0.985)}
        return EquipmentBalanceReport(
            samples,
            quality_counts,
            property_counts,
            tier_counts,
            quantiles,
            ordered[0],
            ordered[-1],
            sum(ordered) / samples,
            attempts / samples,
            self._set_values(),
        )

    def _set_values(self) -> Mapping[str, Mapping[int, float]]:
        result: dict[str, Mapping[int, float]] = {}
        for definition in self.equipment.sets:
            cumulative = 0.0
            values: dict[int, float] = {}
            for bonus in definition.bonuses:
                cumulative += self.valuation.evaluate(bonus.contribution, strict=True).value.total
                values[bonus.required_pieces] = cumulative
            result[definition.id] = values
        return result


def _stable_seed(seed: int, sample: int) -> int:
    payload = f"equipment:{seed}:{sample}".encode("utf-8")
    return int.from_bytes(sha256(payload).digest()[:8], "big", signed=False)


def _quantile(values: list[float], ratio: float) -> float:
    if not 0 <= ratio <= 1 or not values:
        raise ValueError("装备价值分位参数无效")
    position = (len(values) - 1) * ratio
    left = int(position)
    right = min(left + 1, len(values) - 1)
    fraction = position - left
    return values[left] + (values[right] - values[left]) * fraction


__all__ = ["EquipmentBalanceAuditor", "EquipmentBalanceReport"]
