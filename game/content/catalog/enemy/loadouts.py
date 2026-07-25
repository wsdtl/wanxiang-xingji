"""World-weighted enemy behavior pools independent from enemy identities."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from game.core.gameplay import StableId, stable_id

from ..world import MAGIC_WORLD_ID, STELLAR_RING_WORLD_ID, TAIXUAN_WORLD_ID
from .behaviors import ENEMY_BEHAVIOR_CONTENT


@dataclass(frozen=True)
class EnemyBehaviorProfileDefinition:
    world_id: StableId
    behavior_weights: Mapping[StableId, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "world_id", stable_id(self.world_id, field="world id"))
        weights = {
            stable_id(key, field="enemy behavior id"): int(value)
            for key, value in self.behavior_weights.items()
        }
        if not weights or any(value < 1 for value in weights.values()):
            raise ValueError("世界敌人行为权重必须全部大于 0")
        object.__setattr__(self, "behavior_weights", MappingProxyType(weights))


@dataclass(frozen=True)
class EnemyBehaviorWeightPolicy:
    """共享行为扩展对全部世界提供默认权重，并可覆盖个别世界。"""

    behavior_id: StableId
    default_weight: int = 10
    world_weights: Mapping[StableId, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "behavior_id",
            stable_id(self.behavior_id, field="enemy behavior id"),
        )
        default_weight = int(self.default_weight)
        if default_weight < 1:
            raise ValueError("敌人行为默认权重必须大于 0")
        weights = {
            stable_id(key, field="world id"): int(value)
            for key, value in (self.world_weights or {}).items()
        }
        if any(value < 1 for value in weights.values()):
            raise ValueError("敌人行为世界权重必须全部大于 0")
        object.__setattr__(self, "default_weight", default_weight)
        object.__setattr__(self, "world_weights", MappingProxyType(weights))


class EnemyBehaviorProfileCatalog:
    def __init__(self, definitions: tuple[EnemyBehaviorProfileDefinition, ...]) -> None:
        values = {value.world_id: value for value in definitions}
        if len(values) != len(definitions):
            raise ValueError("世界敌人行为倾向不能重复")
        self._definitions = MappingProxyType(values)

    def require(self, world_id: StableId) -> EnemyBehaviorProfileDefinition:
        key = stable_id(world_id, field="world id")
        try:
            return self._definitions[key]
        except KeyError as exc:
            raise KeyError(f"世界没有登记敌人行为倾向：{key}") from exc

    def validate(
        self,
        playable_world_ids: tuple[StableId, ...],
        known_behavior_ids: tuple[StableId, ...] | None = None,
    ) -> None:
        worlds = frozenset(stable_id(value, field="world id") for value in playable_world_ids)
        if set(self._definitions) != set(worlds):
            raise ValueError("敌人行为倾向必须完整覆盖全部可进入世界")
        known = frozenset(
            stable_id(value, field="enemy behavior id")
            for value in (
                known_behavior_ids
                if known_behavior_ids is not None
                else tuple(value.id for value in ENEMY_BEHAVIOR_CONTENT.behaviors)
            )
        )
        for definition in self._definitions.values():
            if set(definition.behavior_weights) != set(known):
                raise ValueError(f"世界敌人行为倾向没有完整覆盖行为库：{definition.world_id}")


_ALL_BEHAVIOR_KEYS = tuple(
    value.id.removeprefix("enemy.behavior.")
    for value in ENEMY_BEHAVIOR_CONTENT.behaviors
)


def enemy_behavior_profile(
    world_id: str,
    preferred: frozenset[str],
) -> EnemyBehaviorProfileDefinition:
    unknown = preferred - set(_ALL_BEHAVIOR_KEYS)
    if unknown:
        raise KeyError("世界敌人行为倾向引用未知行为：" + ", ".join(sorted(unknown)))
    return EnemyBehaviorProfileDefinition(
        world_id,
        {
            f"enemy.behavior.{key}": 18 if key in preferred else 10
            for key in _ALL_BEHAVIOR_KEYS
        },
    )


TAIXUAN_ENEMY_BEHAVIOR_PROFILE = enemy_behavior_profile(
    TAIXUAN_WORLD_ID,
    frozenset({"poison", "bleed", "mark_detonation", "counter", "lifesteal", "sleep", "slow", "sunder", "sacrifice"}),
)
MAGIC_ENEMY_BEHAVIOR_PROFILE = enemy_behavior_profile(
    MAGIC_WORLD_ID,
    frozenset({"burn", "freeze", "area_attack", "resource_drain", "shield", "regeneration", "stun", "cooldown_lock", "charged_burst"}),
)
STELLAR_RING_ENEMY_BEHAVIOR_PROFILE = enemy_behavior_profile(
    STELLAR_RING_WORLD_ID,
    frozenset({"rapid_attack", "combo", "follow_up", "true_damage", "splash", "shield", "evasion", "mark_detonation", "cooldown_lock"}),
)

ENEMY_BEHAVIOR_PROFILE_CATALOG = EnemyBehaviorProfileCatalog(
    (
        TAIXUAN_ENEMY_BEHAVIOR_PROFILE,
        MAGIC_ENEMY_BEHAVIOR_PROFILE,
        STELLAR_RING_ENEMY_BEHAVIOR_PROFILE,
    )
)


__all__ = [
    "ENEMY_BEHAVIOR_PROFILE_CATALOG",
    "EnemyBehaviorProfileCatalog",
    "EnemyBehaviorProfileDefinition",
    "EnemyBehaviorWeightPolicy",
    "MAGIC_ENEMY_BEHAVIOR_PROFILE",
    "STELLAR_RING_ENEMY_BEHAVIOR_PROFILE",
    "TAIXUAN_ENEMY_BEHAVIOR_PROFILE",
    "enemy_behavior_profile",
]
