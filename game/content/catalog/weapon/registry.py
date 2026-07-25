"""武器与敌人共用的战斗机制注册表。"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Mapping

from game.core.gameplay import EffectDefinition, EffectReference, TriggerDefinition, ValueVector

from .blueprints import WeaponBlueprint


@dataclass(frozen=True)
class CompiledPrimaryMechanic:
    operations: tuple[object, ...]
    effects: tuple[EffectDefinition, ...] = ()
    triggers: tuple[TriggerDefinition, ...] = ()
    references: tuple[EffectReference, ...] = ()
    final_references: tuple[EffectReference, ...] = ()


@dataclass(frozen=True)
class CompiledSupportMechanic:
    effects: tuple[EffectDefinition, ...] = ()
    triggers: tuple[TriggerDefinition, ...] = ()
    references: tuple[EffectReference, ...] = ()
    granted_triggers: frozenset[str] = frozenset()


PrimaryCompiler = Callable[[WeaponBlueprint], CompiledPrimaryMechanic]
SupportCompiler = Callable[[WeaponBlueprint, str], CompiledSupportMechanic]


@dataclass(frozen=True)
class PrimaryMechanicDefinition:
    key: str
    hit_factor: float
    compiler: PrimaryCompiler
    value: ValueVector = ValueVector()

    def __post_init__(self) -> None:
        if not self.key.strip() or self.hit_factor <= 0 or not callable(self.compiler):
            raise ValueError("主机制注册缺少稳定键或有效命中系数")

    def compile(self, blueprint: WeaponBlueprint) -> CompiledPrimaryMechanic:
        return self.compiler(blueprint)


@dataclass(frozen=True)
class SupportMechanicDefinition:
    key: str
    compiler: SupportCompiler
    value: ValueVector = ValueVector()

    def __post_init__(self) -> None:
        if not self.key.strip() or not callable(self.compiler):
            raise ValueError("辅助机制注册缺少稳定键")

    def compile(
        self,
        blueprint: WeaponBlueprint,
        ability_id: str,
    ) -> CompiledSupportMechanic:
        return self.compiler(blueprint, ability_id)


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
            raise ValueError(f"武器 {blueprint.key} 引用了未注册机制：{error.args[0]}") from error

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


__all__ = [
    "CompiledPrimaryMechanic",
    "CompiledSupportMechanic",
    "PrimaryMechanicDefinition",
    "SupportMechanicDefinition",
    "TargetingMechanicDefinition",
    "WeaponMechanicRecipe",
    "WeaponMechanicRegistry",
]
