"""武器与敌人共用的战斗机制注册表。"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from game.core.gameplay import ValueVector


@dataclass(frozen=True)
class PrimaryMechanicDefinition:
    key: str
    hit_factor: float
    value: ValueVector = ValueVector()

    def __post_init__(self) -> None:
        if not self.key.strip() or self.hit_factor <= 0:
            raise ValueError("主机制注册缺少稳定键或有效命中系数")


@dataclass(frozen=True)
class SupportMechanicDefinition:
    key: str
    value: ValueVector = ValueVector()

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("辅助机制注册缺少稳定键")


@dataclass(frozen=True)
class TargetingMechanicDefinition:
    key: str
    allowed_selectors: frozenset[str]
    maximum_targets: int | None
    value_factor: float

    def __post_init__(self) -> None:
        if not self.key.strip() or not self.allowed_selectors or self.value_factor <= 0:
            raise ValueError("目标机制注册不完整")
        if self.maximum_targets is not None and self.maximum_targets < 1:
            raise ValueError("目标机制最大目标数必须大于零")


@dataclass(frozen=True)
class WeaponMechanicRecipe:
    recipe_id: str
    primary: PrimaryMechanicDefinition
    support: SupportMechanicDefinition
    targeting: TargetingMechanicDefinition


@dataclass(frozen=True)
class WeaponMechanicRegistry:
    primaries: Mapping[str, PrimaryMechanicDefinition] = field(default_factory=dict)
    supports: Mapping[str, SupportMechanicDefinition] = field(default_factory=dict)
    targeting: Mapping[str, TargetingMechanicDefinition] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "primaries", _indexed(self.primaries, "主机制"))
        object.__setattr__(self, "supports", _indexed(self.supports, "辅助机制"))
        object.__setattr__(self, "targeting", _indexed(self.targeting, "目标机制"))

    @staticmethod
    def recipe_id(content_key: str) -> str:
        key = str(content_key or "").strip()
        if not key:
            raise ValueError("机制配方缺少内容键")
        return f"combat.recipe.{key}"

    def resolve(self, blueprint) -> WeaponMechanicRecipe:
        try:
            return WeaponMechanicRecipe(
                self.recipe_id(blueprint.key),
                self.primaries[blueprint.primary],
                self.supports[blueprint.support],
                self.targeting[blueprint.targeting],
            )
        except KeyError as error:
            raise ValueError(
                f"武器 {blueprint.key} 引用了未注册机制：{error.args[0]}"
            ) from error

    def validate_blueprints(self, blueprints) -> None:
        values = tuple(blueprints)
        recipes = tuple(self.resolve(value) for value in values)
        recipe_ids = tuple(value.recipe_id for value in recipes)
        if len(recipe_ids) != len(set(recipe_ids)):
            raise ValueError("武器机制配方 ID 不能重复")
        used_primary = {value.primary.key for value in recipes}
        used_support = {value.support.key for value in recipes}
        used_targeting = {value.targeting.key for value in recipes}
        unused = (
            set(self.primaries) - used_primary,
            set(self.supports) - used_support,
            set(self.targeting) - used_targeting,
        )
        if any(unused):
            raise ValueError(f"正式机制注册存在未使用项：{unused}")


def _indexed(values, label: str):
    result = {}
    source = values.values() if isinstance(values, Mapping) else values
    for value in source:
        if value.key in result:
            raise ValueError(f"{label}稳定键重复：{value.key}")
        result[value.key] = value
    if not result:
        raise ValueError(f"{label}注册不能为空")
    return MappingProxyType(result)


def _primary(key: str, hit_factor: float = 1.0, **value) -> PrimaryMechanicDefinition:
    return PrimaryMechanicDefinition(key, hit_factor, ValueVector(**value))


def _support(key: str, **value) -> SupportMechanicDefinition:
    return SupportMechanicDefinition(key, ValueVector(**value))


OFFICIAL_WEAPON_MECHANICS = WeaponMechanicRegistry(
    primaries=(
        _primary("heavy"),
        _primary("swift", tempo=3),
        _primary("multi2", 2.0, volatility=1),
        _primary("multi3", 3.0, volatility=2),
        _primary("execute", offense=8, volatility=4),
        _primary("missing_rage", offense=7, volatility=6),
        _primary("max_health", offense=8),
        _primary("true_strike", offense=8),
        _primary("pierce", offense=6),
        _primary("poison", offense=8, volatility=2),
        _primary("bleed", offense=8, volatility=2),
        _primary("burn", offense=8, volatility=2),
        _primary("frost", offense=5, control=3),
        _primary("spirit_drain", sustain=4, control=4),
        _primary("spirit_burst", offense=6, volatility=4),
        _primary("element_cycle", offense=7, volatility=3),
        _primary("detonate", offense=11, volatility=7),
        _primary("mark", offense=4, volatility=4),
        _primary("self_cost", offense=7, volatility=8),
        _primary("volatile", 1.05, offense=4, volatility=14),
        _primary("borrowed_force", 1.50, offense=7, volatility=5),
        _primary("deferred_echo", 1.85, offense=8, tempo=5, volatility=3),
    ),
    supports=(
        _support("none"),
        _support("sunder", offense=5, control=3),
        _support("crit", offense=7, tempo=2),
        _support("delay", tempo=3, control=5),
        _support("burn", offense=8, volatility=2),
        _support("stun", control=11, volatility=3),
        _support("lifesteal", sustain=11),
        _support("on_kill", tempo=10, volatility=5),
        _support("haste", tempo=8),
        _support("guard", survival=8),
        _support("extra_turn", tempo=14, volatility=5),
        _support("evasion", survival=7, tempo=2),
        _support("cooldown", tempo=8, volatility=4),
        _support("slow", tempo=2, control=6),
        _support("on_crit", offense=8, volatility=5),
        _support("mark", offense=5, volatility=4),
        _support("execute", offense=8, volatility=3),
        _support("spirit_drain", sustain=4, control=4),
        _support("freeze", control=12, volatility=4),
        _support("weaken", survival=4, control=5),
        _support("detonate", offense=10, volatility=7),
        _support("heal", sustain=10),
        _support("mark_self", offense=5, tempo=3, volatility=3),
        _support("shield", survival=10),
        _support("death_guard", survival=12, volatility=5),
        _support("resource_balance", sustain=10, volatility=3),
        _support("dispel", control=9),
        _support("thorns", survival=4, offense=5, volatility=5),
        _support("block", survival=10),
        _support("on_kill_heal", sustain=9, volatility=5),
        _support("damage_cap", survival=14),
        _support("immunity", survival=15, volatility=5),
        _support("taunt", survival=3, control=9),
        _support("sleep", control=13, volatility=4),
        _support("cooldown_delay", tempo=3, control=10),
        _support("evasion_counter", offense=5, survival=6, volatility=4),
        _support("on_crit_stun", offense=6, control=8, volatility=6),
        _support("shield_counter", offense=5, survival=8, volatility=4),
        _support("self_cost", offense=5, volatility=8),
    ),
    targeting=(
        TargetingMechanicDefinition(
            "single",
            frozenset({"target.enemy.explicit", "target.enemy.first"}),
            1,
            1.0,
        ),
        TargetingMechanicDefinition(
            "lowest",
            frozenset({"target.enemy.lowest_health"}),
            1,
            1.08,
        ),
        TargetingMechanicDefinition(
            "random",
            frozenset({"target.enemy.random"}),
            1,
            1.0,
        ),
        TargetingMechanicDefinition(
            "adjacent",
            frozenset({"target.enemy.adjacent"}),
            3,
            1.45,
        ),
        TargetingMechanicDefinition(
            "all",
            frozenset({"target.enemy.all"}),
            None,
            1.80,
        ),
    ),
)


__all__ = [
    "OFFICIAL_WEAPON_MECHANICS",
    "PrimaryMechanicDefinition",
    "SupportMechanicDefinition",
    "TargetingMechanicDefinition",
    "WeaponMechanicRecipe",
    "WeaponMechanicRegistry",
]
