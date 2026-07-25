"""各世界专属的组队首领定义与显式来源目录。"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from game.core.gameplay import (
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    COMBAT_SPEED,
    HEALTH_MAXIMUM,
    SPIRIT_MAXIMUM,
    BattleAiRule,
    ContributionSpec,
    ENEMY_RANK_BOSS_ID,
    EnemyDefinition,
    EnemyLevelProfileDefinition,
    EnemyRewardProfileDefinition,
    StableId,
    TagSet,
    stable_id,
)

from ..combat.definitions import BASIC_ATTACK_ABILITY_ID
from ..combat.stats import COMBAT_CONTROL_RESISTANCE, COMBAT_TENACITY
from .blueprints import (
    CULTIVATION_PARTY_BOSS_BLUEPRINTS,
    MAGIC_PARTY_BOSS_BLUEPRINTS,
    STELLAR_RING_PARTY_BOSS_BLUEPRINTS,
)
from .loot import PARTY_BOSS_LOOT_TABLE_ID


PARTY_BOSS_LEVEL_PROFILE_ID = "enemy.level.party_boss"
PARTY_BOSS_REWARD_PROFILE_ID = "enemy.reward.party_boss"


def _levels(formula) -> tuple[float, ...]:
    return tuple(round(float(formula(level)), 2) for level in range(1, 101))


PARTY_BOSS_LEVEL_PROFILE = EnemyLevelProfileDefinition(
    PARTY_BOSS_LEVEL_PROFILE_ID,
    {
        HEALTH_MAXIMUM: _levels(
            lambda level: 180 + 24 * (level - 1) + 0.08 * (level - 1) ** 2
        ),
        SPIRIT_MAXIMUM: _levels(lambda level: 180 + 4 * (level - 1)),
        COMBAT_ATTACK: _levels(lambda level: 8 + 1.05 * (level - 1)),
        COMBAT_DEFENSE: _levels(lambda level: 0.6 * (level - 1)),
        COMBAT_SPEED: _levels(lambda _level: 100),
        COMBAT_CONTROL_RESISTANCE: _levels(lambda _level: 0),
        COMBAT_TENACITY: _levels(lambda _level: 0),
    },
)


PARTY_BOSS_REWARD_PROFILE = EnemyRewardProfileDefinition(
    PARTY_BOSS_REWARD_PROFILE_ID,
    28.0,
    9.0,
    PARTY_BOSS_LOOT_TABLE_ID,
    1,
)


_BASIC_AI = (
    BattleAiRule(
        "ai.enemy.party_boss.basic_attack",
        BASIC_ATTACK_ABILITY_ID,
        "target.enemy.first",
        priority=0,
        maximum_targets=1,
    ),
)


def _party_boss(blueprint, source_key: str) -> EnemyDefinition:
    enemy_id = f"enemy.boss.party.{source_key}.{blueprint.key}"
    return EnemyDefinition(
        enemy_id,
        PARTY_BOSS_LEVEL_PROFILE_ID,
        PARTY_BOSS_REWARD_PROFILE_ID,
        frozenset({ENEMY_RANK_BOSS_ID}),
        base_contribution=ContributionSpec(
            tags=TagSet.of(
                "enemy.identity.party_boss",
                f"enemy.source.{source_key}",
            ),
            abilities=frozenset({BASIC_ATTACK_ABILITY_ID}),
        ),
        base_ai_rules=_BASIC_AI,
        tags=TagSet.of(
            "enemy.identity.party_boss",
            f"enemy.source.{source_key}",
        ),
    )


CULTIVATION_PARTY_BOSS_ENEMIES = tuple(
    _party_boss(value, "cultivation")
    for value in CULTIVATION_PARTY_BOSS_BLUEPRINTS
)
MAGIC_PARTY_BOSS_ENEMIES = tuple(
    _party_boss(value, "magic")
    for value in MAGIC_PARTY_BOSS_BLUEPRINTS
)
STELLAR_RING_PARTY_BOSS_ENEMIES = tuple(
    _party_boss(value, "stellar_ring")
    for value in STELLAR_RING_PARTY_BOSS_BLUEPRINTS
)
PARTY_BOSS_ENEMIES = (
    *CULTIVATION_PARTY_BOSS_ENEMIES,
    *MAGIC_PARTY_BOSS_ENEMIES,
    *STELLAR_RING_PARTY_BOSS_ENEMIES,
)
PARTY_BOSS_DISPLAY_IDS = frozenset(value.id for value in PARTY_BOSS_ENEMIES)


@dataclass(frozen=True)
class PartyBossSourceDefinition:
    source_world_id: StableId
    enemy_ids: frozenset[StableId]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_world_id",
            stable_id(self.source_world_id, field="party boss source world id"),
        )
        enemy_ids = frozenset(
            stable_id(value, field="party boss enemy id")
            for value in self.enemy_ids
        )
        if not enemy_ids:
            raise ValueError("组队首领来源必须至少登记一只首领")
        object.__setattr__(self, "enemy_ids", enemy_ids)


class PartyBossSourceCatalog:
    """只保存来源与候选关系；随机抽取属于组队挑战规则。"""

    def __init__(self, definitions: tuple[PartyBossSourceDefinition, ...]) -> None:
        values: dict[StableId, PartyBossSourceDefinition] = {}
        enemy_owners: dict[StableId, StableId] = {}
        for definition in definitions:
            if definition.source_world_id in values:
                raise ValueError(
                    f"组队首领来源重复：{definition.source_world_id}"
                )
            values[definition.source_world_id] = definition
            for enemy_id in definition.enemy_ids:
                owner = enemy_owners.get(enemy_id)
                if owner is not None:
                    raise ValueError(
                        f"组队首领 {enemy_id} 同时属于 {owner} "
                        f"和 {definition.source_world_id}"
                    )
                enemy_owners[enemy_id] = definition.source_world_id
        if not values:
            raise ValueError("组队首领来源目录不能为空")
        self._definitions = MappingProxyType(values)
        self._enemy_owners = MappingProxyType(enemy_owners)

    def source_ids(self) -> tuple[StableId, ...]:
        return tuple(sorted(self._definitions))

    def require(self, source_world_id: StableId) -> PartyBossSourceDefinition:
        key = stable_id(source_world_id, field="party boss source world id")
        try:
            return self._definitions[key]
        except KeyError as exc:
            raise KeyError(f"未知组队首领来源：{key}") from exc

    def owner_of(self, enemy_id: StableId) -> StableId:
        key = stable_id(enemy_id, field="party boss enemy id")
        try:
            return self._enemy_owners[key]
        except KeyError as exc:
            raise KeyError(f"敌人不是组队首领：{key}") from exc

    def validate(self, content, playable_world_ids: tuple[StableId, ...]) -> None:
        playable = frozenset(
            stable_id(value, field="playable world id")
            for value in playable_world_ids
        )
        if set(self.source_ids()) != set(playable):
            raise ValueError("每个可进入世界必须且只能登记一组组队首领")
        known = set(content.enemies.definitions.ids())
        registered = set(self._enemy_owners)
        official_party_bosses = {
            enemy_id
            for enemy_id in known
            if content.enemies.require(enemy_id).tags.has("enemy.identity.party_boss")
        }
        if registered != official_party_bosses:
            raise ValueError("组队首领来源目录没有完整覆盖正式组队首领")
        if not registered.issubset(known):
            raise KeyError("组队首领来源目录引用了未知敌人")
        for enemy_id in registered:
            enemy = content.enemies.require(enemy_id)
            if not enemy.tags.has("enemy.identity.party_boss"):
                raise ValueError(f"组队首领缺少专属身份标签：{enemy_id}")


PARTY_BOSS_SOURCE_CATALOG = PartyBossSourceCatalog(
    (
        PartyBossSourceDefinition(
            "world.taixuan",
            frozenset(value.id for value in CULTIVATION_PARTY_BOSS_ENEMIES),
        ),
        PartyBossSourceDefinition(
            "world.magic",
            frozenset(value.id for value in MAGIC_PARTY_BOSS_ENEMIES),
        ),
        PartyBossSourceDefinition(
            "world.stellar_ring",
            frozenset(value.id for value in STELLAR_RING_PARTY_BOSS_ENEMIES),
        ),
    )
)


__all__ = [name for name in globals() if not name.startswith("_")]
