"""正式武器机制的静态价值估算。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.gameplay import ValueVector

from .blueprints import WeaponBlueprint
from .official_mechanics import OFFICIAL_WEAPON_MECHANICS


@dataclass(frozen=True)
class WeaponValueEstimate:
    key: str
    declared: ValueVector
    estimated: ValueVector
    damage_points: float
    availability: float

    @property
    def total_delta(self) -> float:
        return self.declared.total - self.estimated.total


def estimate_weapon_value(blueprint: WeaponBlueprint) -> WeaponValueEstimate:
    recipe = OFFICIAL_WEAPON_MECHANICS.resolve(blueprint)
    availability = 1.0 / (1.0 + blueprint.cooldown * 0.08 + blueprint.spirit_cost * 0.006)
    damage_points = blueprint.power * recipe.primary.hit_factor * recipe.targeting.value_factor * availability * 42.0
    estimated = ValueVector(offense=damage_points) + recipe.primary.value + recipe.support.value
    return WeaponValueEstimate(
        blueprint.key,
        blueprint.value,
        estimated,
        damage_points,
        availability,
    )


__all__ = ["WeaponValueEstimate", "estimate_weapon_value"]
