"""基于正式武器价值估算执行横向平衡审计。"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Iterable, Mapping

from game.content.catalog.weapon.blueprints import WEAPON_BLUEPRINTS, WeaponBlueprint
from game.content.catalog.weapon.valuation import WeaponValueEstimate, estimate_weapon_value


@dataclass(frozen=True)
class WeaponBalanceReport:
    entries: Mapping[str, WeaponValueEstimate] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", MappingProxyType(dict(self.entries)))

    @property
    def minimum_estimated_total(self) -> float:
        return min(value.estimated.total for value in self.entries.values())

    @property
    def maximum_estimated_total(self) -> float:
        return max(value.estimated.total for value in self.entries.values())

    def outliers(self, maximum_delta: float = 18.0) -> tuple[WeaponValueEstimate, ...]:
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
    """按正式价值估算快速审计全部武器，不运行战斗时间线。"""

    def audit(
        self,
        blueprints: Iterable[WeaponBlueprint] = WEAPON_BLUEPRINTS,
    ) -> WeaponBalanceReport:
        entries: dict[str, WeaponValueEstimate] = {}
        for blueprint in blueprints:
            if blueprint.key in entries:
                raise ValueError(f"武器平衡审计发现重复键：{blueprint.key}")
            entries[blueprint.key] = estimate_weapon_value(blueprint)
        if not entries:
            raise ValueError("武器平衡审计不能为空")
        return WeaponBalanceReport(entries)


__all__ = ["WeaponBalanceAuditor", "WeaponBalanceReport"]
