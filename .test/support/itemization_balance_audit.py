"""基于正式物品生成器执行确定性品质分布审计。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from types import MappingProxyType
from typing import Mapping

from game.core.gameplay.context import RuleContext, Ruleset, SeededRandomSource
from game.core.gameplay.ids import StableId
from game.core.gameplay.itemization.engine import ItemizationEngine
from game.core.gameplay.itemization.models import ItemGenerationCommand


@dataclass(frozen=True)
class ProfileBalanceSummary:
    profile_id: StableId
    samples: int
    quality_counts: Mapping[StableId, int]
    minimum_value: float
    maximum_value: float
    mean_value: float
    mean_attempts: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "quality_counts", MappingProxyType(dict(self.quality_counts)))

    def quality_ratio(self, quality_id: StableId) -> float:
        return self.quality_counts.get(quality_id, 0) / self.samples


@dataclass(frozen=True)
class ItemizationBalanceReport:
    summaries: Mapping[StableId, ProfileBalanceSummary] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "summaries", MappingProxyType(dict(self.summaries)))

    @property
    def total_samples(self) -> int:
        return sum(value.samples for value in self.summaries.values())

    @property
    def quality_counts(self) -> Mapping[StableId, int]:
        counts: dict[StableId, int] = {}
        for summary in self.summaries.values():
            for quality_id, amount in summary.quality_counts.items():
                counts[quality_id] = counts.get(quality_id, 0) + amount
        return MappingProxyType(counts)

    def profiles_above_attempts(self, maximum_mean_attempts: float) -> tuple[StableId, ...]:
        return tuple(
            sorted(
                profile_id
                for profile_id, summary in self.summaries.items()
                if summary.mean_attempts > maximum_mean_attempts
            )
        )


class ItemizationBalanceAuditor:
    """用物品生成器本身快速抽检全部策略，不复制估值公式。"""

    def __init__(self, engine: ItemizationEngine) -> None:
        self.engine = engine

    def audit(
        self,
        *,
        profile_ids: tuple[StableId, ...] | None = None,
        content_fingerprint: str,
        samples_per_profile: int = 128,
        seed: int = 0,
        logical_time: datetime = datetime(2000, 1, 1, tzinfo=timezone.utc),
    ) -> ItemizationBalanceReport:
        if not content_fingerprint.strip():
            raise ValueError("物品平衡审计缺少内容指纹")
        if samples_per_profile < 1:
            raise ValueError("samples_per_profile 必须大于 0")
        if logical_time.tzinfo is None or logical_time.utcoffset() is None:
            raise ValueError("物品平衡审计逻辑时间必须包含时区")
        selected = profile_ids or tuple(sorted(self.engine.catalog.profiles))
        summaries: dict[StableId, ProfileBalanceSummary] = {}
        for profile_id in selected:
            self.engine.catalog.require_profile(profile_id)
            quality_counts: dict[StableId, int] = {}
            values: list[float] = []
            attempts = 0
            for sample in range(samples_per_profile):
                sample_seed = _stable_seed(profile_id, seed, sample)
                trace_id = f"itemization-audit:{profile_id}:{seed}:{sample}"
                context = RuleContext(
                    trace_id,
                    "rules.itemization_balance_audit",
                    Ruleset("ruleset.itemization_balance_audit"),
                    logical_time,
                    SeededRandomSource(sample_seed),
                )
                execution = self.engine.generate(
                    ItemGenerationCommand(trace_id, profile_id, content_fingerprint),
                    context=context,
                )
                roll = execution.roll
                quality_counts[roll.quality_id] = quality_counts.get(roll.quality_id, 0) + 1
                values.append(roll.intrinsic_value.total)
                attempts += roll.receipt.attempts
            summaries[profile_id] = ProfileBalanceSummary(
                profile_id,
                samples_per_profile,
                quality_counts,
                min(values),
                max(values),
                sum(values) / samples_per_profile,
                attempts / samples_per_profile,
            )
        return ItemizationBalanceReport(summaries)


def _stable_seed(profile_id: StableId, seed: int, sample: int) -> int:
    payload = f"{profile_id}:{seed}:{sample}".encode("utf-8")
    return int.from_bytes(sha256(payload).digest()[:8], "big", signed=False)


__all__ = [
    "ItemizationBalanceAuditor",
    "ItemizationBalanceReport",
    "ProfileBalanceSummary",
]
