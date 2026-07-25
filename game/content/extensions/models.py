"""具体游戏内容与世界扩展的冻结契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from game.core.gameplay import (
    ContentPackage,
    ContentVersion,
    EnemyDefinition,
    SkinEntry,
    SkinPack,
    StableId,
    WorldSpaceDefinition,
    stable_id,
)

from ..catalog.companion.models import (
    CompanionSanctuaryDefinition,
    CompanionSpeciesDefinition,
    PersonCompanionDefinition,
)
from ..catalog.disaster.models import DimensionalDisasterDefinition
from ..catalog.enemy.loadouts import EnemyBehaviorProfileDefinition
from ..catalog.enemy.loadouts import EnemyBehaviorWeightPolicy
from ..catalog.enemy.party import PartyBossSourceDefinition
from ..catalog.economy.market_items import MarketItemPolicy
from ..presentation import EnemyPresentationStyle, GearPresentationStyle
from ..world_lore.models import WorldLoreDefinition
from ..worlds.models import OfficialWorldBundle


@dataclass(frozen=True)
class ContentExtension:
    """一组可独立加入正式装配的共享内容包。"""

    id: StableId
    version: ContentVersion
    packages: tuple[ContentPackage, ...]
    skin_overlays: Mapping[StableId, Mapping[StableId, SkinEntry]] = field(
        default_factory=dict
    )
    enemy_behavior_weights: tuple[EnemyBehaviorWeightPolicy, ...] = ()
    market_item_policies: tuple[MarketItemPolicy, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", stable_id(self.id, field="content extension id"))
        if not isinstance(self.version, ContentVersion):
            raise TypeError("内容扩展 version 必须是 ContentVersion")
        packages = tuple(self.packages)
        package_ids = tuple(value.manifest.id for value in packages)
        if not packages or len(package_ids) != len(set(package_ids)):
            raise ValueError(f"内容扩展包不能为空或重复：{self.id}")
        overlays = {
            stable_id(skin_id, field="skin id"): MappingProxyType(
                {
                    stable_id(content_id, field="skin content id"): entry
                    for content_id, entry in entries.items()
                }
            )
            for skin_id, entries in self.skin_overlays.items()
        }
        if any(not entries for entries in overlays.values()):
            raise ValueError(f"内容扩展皮肤增量不能为空：{self.id}")
        owned_display_ids = {
            content_id
            for package in packages
            for content_id in (
                *package.display_content_ids,
                *(
                    value
                    for values in package.skin_display_content_ids.values()
                    for value in values
                ),
            )
        }
        overlay_ids = {
            content_id
            for entries in overlays.values()
            for content_id in entries
        }
        if not overlay_ids.issubset(owned_display_ids):
            raise ValueError(f"内容扩展皮肤增量引用了非本扩展示内容：{self.id}")
        behavior_policies = tuple(self.enemy_behavior_weights)
        behavior_ids = tuple(value.behavior_id for value in behavior_policies)
        if len(behavior_ids) != len(set(behavior_ids)):
            raise ValueError(f"内容扩展重复登记敌人行为权重：{self.id}")
        owned_behavior_ids = {
            value.id
            for package in packages
            for value in package.enemy_behaviors
        }
        if not set(behavior_ids).issubset(owned_behavior_ids):
            raise ValueError(f"内容扩展行为权重引用了非本扩展行为：{self.id}")
        market_policies = tuple(self.market_item_policies)
        market_ids = tuple(value.definition_id for value in market_policies)
        if len(market_ids) != len(set(market_ids)):
            raise ValueError(f"内容扩展重复登记市场政策：{self.id}")
        owned_item_ids = {
            str(value.id)
            for package in packages
            for value in package.items
        }
        if not set(market_ids).issubset(owned_item_ids):
            raise ValueError(f"内容扩展市场政策引用了非本扩展物品：{self.id}")
        object.__setattr__(self, "packages", packages)
        object.__setattr__(self, "skin_overlays", MappingProxyType(overlays))
        object.__setattr__(self, "enemy_behavior_weights", behavior_policies)
        object.__setattr__(self, "market_item_policies", market_policies)


@dataclass(frozen=True)
class WorldExtension:
    """一个玩法世界完整拥有的内容槽，不依赖中央世界编号表。"""

    id: StableId
    version: ContentVersion
    order: int
    space: WorldSpaceDefinition
    bundle: OfficialWorldBundle
    skin: SkinPack
    gear_presentation: GearPresentationStyle
    enemy_presentation: EnemyPresentationStyle
    companion_species: tuple[CompanionSpeciesDefinition, ...]
    companion_sanctuary: CompanionSanctuaryDefinition
    people: tuple[PersonCompanionDefinition, ...]
    enemy_behavior_profile: EnemyBehaviorProfileDefinition
    party_bosses: tuple[EnemyDefinition, ...]
    party_boss_source: PartyBossSourceDefinition
    party_boss_trophy_item_ids: Mapping[StableId, StableId]
    disasters: tuple[DimensionalDisasterDefinition, ...]
    disaster_enemies: tuple[EnemyDefinition, ...]
    lore: WorldLoreDefinition
    content_extensions: tuple[ContentExtension, ...] = ()

    def __post_init__(self) -> None:
        world_id = stable_id(self.id, field="world extension id")
        object.__setattr__(self, "id", world_id)
        if not isinstance(self.version, ContentVersion):
            raise TypeError("世界扩展 version 必须是 ContentVersion")
        if int(self.order) < 0:
            raise ValueError("世界扩展顺序不能小于 0")
        object.__setattr__(self, "order", int(self.order))

        species = tuple(self.companion_species)
        people = tuple(self.people)
        party_bosses = tuple(self.party_bosses)
        disasters = tuple(self.disasters)
        disaster_enemies = tuple(self.disaster_enemies)
        content_extensions = tuple(
            sorted(self.content_extensions, key=lambda value: value.id)
        )
        for field_name, values in (
            ("companion_species", species),
            ("people", people),
            ("party_bosses", party_bosses),
            ("disasters", disasters),
            ("disaster_enemies", disaster_enemies),
        ):
            if not values:
                raise ValueError(f"世界扩展缺少 {field_name}：{world_id}")

        world = self.bundle.world
        if world.id != world_id:
            raise ValueError(f"世界扩展 ID 与世界定义不一致：{world_id}")
        if world.space_id != self.space.id:
            raise ValueError(f"世界扩展空间与世界定义不一致：{world_id}")
        if world.skin_id != self.skin.id:
            raise ValueError(f"世界扩展皮肤与世界定义不一致：{world_id}")
        for style in (self.gear_presentation, self.enemy_presentation):
            if style.skin_id != self.skin.id or style.skin_version != self.skin.version:
                raise ValueError(f"世界展示样式与皮肤版本不一致：{world_id}")

        if any(value.origin_world_id != world_id for value in species):
            raise ValueError(f"世界扩展混入其他世界宠物：{world_id}")
        if self.companion_sanctuary.world_id != world_id:
            raise ValueError(f"世界扩展宠物秘境来源错误：{world_id}")
        if set(self.companion_sanctuary.species_ids) != {value.id for value in species}:
            raise ValueError(f"世界扩展宠物秘境未完整覆盖宠物：{world_id}")
        if any(value.origin_world_id != world_id for value in people):
            raise ValueError(f"世界扩展混入其他世界人物伙伴：{world_id}")
        if self.enemy_behavior_profile.world_id != world_id:
            raise ValueError(f"世界敌人行为倾向来源错误：{world_id}")

        party_ids = {value.id for value in party_bosses}
        if self.party_boss_source.source_world_id != world_id:
            raise ValueError(f"组队首领来源世界错误：{world_id}")
        if set(self.party_boss_source.enemy_ids) != party_ids:
            raise ValueError(f"组队首领来源未完整覆盖首领：{world_id}")
        trophy_item_ids = {
            stable_id(enemy_id, field="party boss enemy id"): stable_id(
                item_id,
                field="party boss trophy item id",
            )
            for enemy_id, item_id in self.party_boss_trophy_item_ids.items()
        }
        if set(trophy_item_ids) != party_ids:
            raise ValueError(f"组队首领奖励绑定未完整覆盖首领：{world_id}")
        if len(set(trophy_item_ids.values())) != len(trophy_item_ids):
            raise ValueError(f"组队首领不能共享同一战利品：{world_id}")
        if any(value.source_world_id != world_id for value in disasters):
            raise ValueError(f"世界扩展混入其他世界灾厄：{world_id}")
        if {value.enemy_definition_id for value in disasters} != {
            value.id for value in disaster_enemies
        }:
            raise ValueError(f"世界灾厄与战斗敌人未一一对应：{world_id}")
        if self.lore.world_id != world_id:
            raise ValueError(f"世界志来源世界错误：{world_id}")

        required_skin_ids = {self.space.id, *party_ids}
        missing_skin_ids = required_skin_ids - set(self.skin.entries)
        if missing_skin_ids:
            raise ValueError(
                f"世界皮肤缺少自身专属展示：{world_id}/"
                + ", ".join(sorted(missing_skin_ids))
            )
        extension_ids = tuple(value.id for value in content_extensions)
        if len(extension_ids) != len(set(extension_ids)):
            raise ValueError(f"世界扩展重复登记内容扩展：{world_id}")

        object.__setattr__(self, "companion_species", species)
        object.__setattr__(self, "people", people)
        object.__setattr__(self, "party_bosses", party_bosses)
        object.__setattr__(
            self,
            "party_boss_trophy_item_ids",
            MappingProxyType(trophy_item_ids),
        )
        object.__setattr__(self, "disasters", disasters)
        object.__setattr__(self, "disaster_enemies", disaster_enemies)
        object.__setattr__(self, "content_extensions", content_extensions)


__all__ = ["ContentExtension", "WorldExtension"]
