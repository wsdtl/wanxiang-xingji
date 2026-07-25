"""正式武器的静态价值估算与快速横向审计。"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Iterable, Mapping

from game.core.gameplay import ValueVector

from .blueprints import WEAPON_BLUEPRINTS, WeaponBlueprint
from .registry import OFFICIAL_WEAPON_MECHANICS


PRIMARY_HIT_FACTORS: Mapping[str, float] = MappingProxyType(
    {
        key: value.hit_factor
        for key, value in OFFICIAL_WEAPON_MECHANICS.primaries.items()
    }
)


PRIMARY_VALUES: Mapping[str, ValueVector] = MappingProxyType(
    {
        key: value.value
        for key, value in OFFICIAL_WEAPON_MECHANICS.primaries.items()
    }
)


SUPPORT_VALUES: Mapping[str, ValueVector] = MappingProxyType(
    {
        key: value.value
        for key, value in OFFICIAL_WEAPON_MECHANICS.supports.items()
    }
)


TARGET_FACTORS: Mapping[str, float] = MappingProxyType(
    {
        key: value.value_factor
        for key, value in OFFICIAL_WEAPON_MECHANICS.targeting.items()
    }
)


@dataclass(frozen=True)
class WeaponBalanceEntry:
    key: str
    declared: ValueVector
    estimated: ValueVector
    damage_points: float
    availability: float

    @property
    def total_delta(self) -> float:
        return self.declared.total - self.estimated.total


@dataclass(frozen=True)
class WeaponBalanceReport:
    entries: Mapping[str, WeaponBalanceEntry] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", MappingProxyType(dict(self.entries)))

    @property
    def minimum_estimated_total(self) -> float:
        return min(value.estimated.total for value in self.entries.values())

    @property
    def maximum_estimated_total(self) -> float:
        return max(value.estimated.total for value in self.entries.values())

    def outliers(self, maximum_delta: float = 18.0) -> tuple[WeaponBalanceEntry, ...]:
        if maximum_delta < 0:
            raise ValueError("maximum_delta 不能小于 0")
        return tuple(
            sorted(
                (
                    value
                    for value in self.entries.values()
                    if abs(value.total_delta) > maximum_delta
                ),
                key=lambda value: abs(value.total_delta),
                reverse=True,
            )
        )


class WeaponBalanceAuditor:
    """按统一机制表快速估算武器，不运行完整战斗时间线。"""

    def audit(
        self,
        blueprints: Iterable[WeaponBlueprint] = WEAPON_BLUEPRINTS,
    ) -> WeaponBalanceReport:
        entries: dict[str, WeaponBalanceEntry] = {}
        for blueprint in blueprints:
            if blueprint.key in entries:
                raise ValueError(f"武器平衡审计发现重复键：{blueprint.key}")
            entries[blueprint.key] = estimate_weapon_value(blueprint)
        if not entries:
            raise ValueError("武器平衡审计不能为空")
        return WeaponBalanceReport(entries)


def estimate_weapon_value(blueprint: WeaponBlueprint) -> WeaponBalanceEntry:
    recipe = OFFICIAL_WEAPON_MECHANICS.resolve(blueprint)
    hit_factor = recipe.primary.hit_factor
    primary = recipe.primary.value
    support = recipe.support.value
    target_factor = recipe.targeting.value_factor
    availability = 1.0 / (
        1.0
        + blueprint.cooldown * 0.08
        + blueprint.spirit_cost * 0.006
    )
    damage_points = (
        blueprint.power
        * hit_factor
        * target_factor
        * availability
        * 42.0
    )
    estimated = ValueVector(offense=damage_points) + primary + support
    return WeaponBalanceEntry(
        blueprint.key,
        blueprint.value,
        estimated,
        damage_points,
        availability,
    )


__all__ = [
    "PRIMARY_HIT_FACTORS",
    "PRIMARY_VALUES",
    "SUPPORT_VALUES",
    "TARGET_FACTORS",
    "WeaponBalanceAuditor",
    "WeaponBalanceEntry",
    "WeaponBalanceReport",
    "estimate_weapon_value",
]

