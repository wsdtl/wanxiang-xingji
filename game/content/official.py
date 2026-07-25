"""官方内容、真实世界运行目录与展示投影入口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from game.core.gameplay import (
    ContentAssembler,
    ContentRuntime,
    SkinPack,
    SkinProjector,
    StableId,
    WorldDefinition,
    WorldRuntimeCatalog,
)

from .catalog import CATALOG_PACKAGE
from .catalog.companion import CompanionCatalog
from .catalog.draw import DRAW_CATALOG_CONTENT
from .catalog.economy import audit_market_prices
from .catalog.economy import MarketItemPolicy
from .catalog.enemy import (
    PERSONAL_BOSS_ENEMIES,
    EnemyBehaviorProfileCatalog,
    PartyBossSourceCatalog,
)
from .catalog.exploration import EXPLORATION_REGION_CATALOG, ExplorationRegionCatalog
from .catalog.trial import BUILD_TRIAL_CATALOG, BuildTrialCatalog
from .extensions import OFFICIAL_EXTENSION_CATALOG
from .presentation import EnemyNameProjector, GearProjector
from .world_lore.models import WorldLoreCatalog


OFFICIAL_PACKAGES = OFFICIAL_EXTENSION_CATALOG.packages(CATALOG_PACKAGE)
PLAYABLE_WORLD_DEFINITIONS = tuple(
    value.bundle.world for value in OFFICIAL_EXTENSION_CATALOG.worlds
)
PLAYABLE_WORLD_IDS = OFFICIAL_EXTENSION_CATALOG.world_ids()
DEFAULT_WORLD_ID = PLAYABLE_WORLD_IDS[0]
DEFAULT_SKIN_ID = OFFICIAL_EXTENSION_CATALOG.require_world(DEFAULT_WORLD_ID).skin.id
COMPANION_CATALOG = OFFICIAL_EXTENSION_CATALOG.companions
WORLD_LORE_CATALOG: WorldLoreCatalog = OFFICIAL_EXTENSION_CATALOG.lore


@dataclass(frozen=True)
class OfficialContent:
    """已经冻结的官方规则运行期及当前展示皮肤。"""

    catalog: ContentRuntime
    skin: SkinPack
    projector: SkinProjector
    gear_projector: GearProjector
    enemy_projector: EnemyNameProjector
    enemy_behavior_profiles: EnemyBehaviorProfileCatalog
    exploration_regions: ExplorationRegionCatalog
    companions: CompanionCatalog
    party_bosses: PartyBossSourceCatalog
    party_boss_trophy_item_ids: Mapping[StableId, StableId]
    market_item_policies: Mapping[str, MarketItemPolicy]
    build_trials: BuildTrialCatalog
    world: WorldDefinition
    worlds: WorldRuntimeCatalog


class WorldViewCatalog:
    """按真实世界提供运行规则，并由世界定义派生展示皮肤。"""

    def __init__(
        self,
        catalog: ContentRuntime,
        playable_worlds: tuple[WorldDefinition, ...] | None = None,
    ) -> None:
        self.catalog = catalog
        self.extensions = OFFICIAL_EXTENSION_CATALOG
        values = tuple(playable_worlds or PLAYABLE_WORLD_DEFINITIONS)
        for value in values:
            catalog.skins.require(value.skin_id)
        if catalog.world_runtime is None:
            raise ValueError("正式内容没有装配真实世界目录")
        declared_ids = tuple(value.id for value in values)
        if set(declared_ids) != set(catalog.world_runtime.world_ids()):
            raise ValueError("应用声明的可进入世界与内容包装配结果不一致")
        self.worlds = catalog.world_runtime
        self._world_ids = self.extensions.world_ids()
        if set(self.worlds.world_ids()) != set(self._world_ids):
            raise ValueError("正式世界定义必须完整覆盖扩展目录")
        self._views: dict[tuple[StableId, int], OfficialContent] = {}

    def require(
        self,
        world_id: StableId,
        version: int | None = None,
    ) -> OfficialContent:
        world = self.worlds.require_world(world_id)
        skin = self.catalog.skins.require(world.skin_id, version)
        key = (world.id, skin.version)
        view = self._views.get(key)
        if view is None:
            view = select_world_skin(
                self.catalog,
                skin.id,
                version=skin.version,
                world=world,
                worlds=self.worlds,
            )
            self._views[key] = view
        return view

    def require_skin(
        self,
        skin_id: StableId,
        version: int | None = None,
    ) -> OfficialContent:
        """只供历史战报和内容来源按展示皮肤还原，不参与玩法定位。"""

        world = self.worlds.world_for_skin(skin_id)
        return self.require(world.id, version)

    def resolve(self, value: object) -> OfficialContent | None:
        """按 world_id、skin_id 或玩家可见世界名解析真实世界视图。"""

        token = " ".join(str(value or "").strip().casefold().split())
        if not token:
            return None
        for world_id in self.world_ids():
            view = self.require(world_id)
            if token in {
                view.world.id.casefold(),
                view.skin.id.casefold(),
                view.skin.name.casefold(),
            }:
                return view
        return None

    def world_ids(self) -> tuple[StableId, ...]:
        return self._world_ids

    def skin_ids(self) -> tuple[StableId, ...]:
        return self.worlds.skin_ids()

    def registered_skin_ids(self) -> tuple[StableId, ...]:
        return self.catalog.skins.skin_ids()

    def latest_views(self) -> tuple[OfficialContent, ...]:
        return tuple(self.require(world_id) for world_id in self.world_ids())


def assemble_official_catalog() -> ContentRuntime:
    """装配全部官方内容；应用组合根应在启动时只调用一次。"""

    runtime = ContentAssembler().assemble(OFFICIAL_PACKAGES)
    OFFICIAL_EXTENSION_CATALOG.validate_runtime(runtime)
    audit_market_prices(
        runtime.items,
        DRAW_CATALOG_CONTENT,
        runtime.equipment,
        market_item_policies=OFFICIAL_EXTENSION_CATALOG.market_item_policies,
        expected_party_trophy_ids=frozenset(
            OFFICIAL_EXTENSION_CATALOG.party_boss_trophy_item_ids.values()
        ),
    )
    return runtime


def select_world_skin(
    catalog: ContentRuntime,
    skin_id: StableId = DEFAULT_SKIN_ID,
    *,
    version: int | None = None,
    world: WorldDefinition | None = None,
    worlds: WorldRuntimeCatalog | None = None,
) -> OfficialContent:
    """在不改变规则和存档的前提下选择一套世界皮肤。"""

    skin = catalog.skins.require(skin_id, version)
    runtime = worlds or catalog.world_runtime
    if runtime is None:
        raise ValueError("正式内容没有装配真实世界目录")
    selected_world = world or runtime.world_for_skin(skin.id)
    projector = SkinProjector(skin)
    EXPLORATION_REGION_CATALOG.validate(catalog, runtime)
    OFFICIAL_EXTENSION_CATALOG.companions.validate(catalog, runtime)
    OFFICIAL_EXTENSION_CATALOG.party_bosses.validate(catalog, runtime.world_ids())
    OFFICIAL_EXTENSION_CATALOG.enemy_behavior_profiles.validate(
        runtime.world_ids(),
        catalog.enemies.behaviors.ids(),
    )
    OFFICIAL_EXTENSION_CATALOG.validate_runtime(catalog)
    validate_enemy_narrative_identities(projector, selected_world.id, skin.id)
    return OfficialContent(
        catalog,
        skin,
        projector,
        GearProjector(
            projector,
            OFFICIAL_EXTENSION_CATALOG.gear_presentation(skin.id, skin.version),
        ),
        EnemyNameProjector(
            projector,
            OFFICIAL_EXTENSION_CATALOG.enemy_presentation(skin.id, skin.version),
        ),
        OFFICIAL_EXTENSION_CATALOG.enemy_behavior_profiles,
        EXPLORATION_REGION_CATALOG,
        OFFICIAL_EXTENSION_CATALOG.companions,
        OFFICIAL_EXTENSION_CATALOG.party_bosses,
        OFFICIAL_EXTENSION_CATALOG.party_boss_trophy_item_ids,
        OFFICIAL_EXTENSION_CATALOG.market_item_policies,
        BUILD_TRIAL_CATALOG,
        selected_world,
        runtime,
    )


def build_official_content(
    skin_id: StableId = DEFAULT_SKIN_ID,
    *,
    version: int | None = None,
) -> OfficialContent:
    """用于启动装配和测试的便捷入口，正式组件不得自行调用。"""

    return select_world_skin(
        assemble_official_catalog(),
        skin_id,
        version=version,
    )


def validate_enemy_narrative_identities(
    projector: SkinProjector,
    world_id: StableId,
    skin_id: StableId,
) -> None:
    """防止同一世界来源的个人、组队和灾厄重复使用中文主身份。"""

    identities: dict[str, str] = {}
    enemy_ids = (
        *(value.id for value in PERSONAL_BOSS_ENEMIES),
        *sorted(OFFICIAL_EXTENSION_CATALOG.party_bosses.require(world_id).enemy_ids),
    )
    for enemy_id in enemy_ids:
        name = projector.name(enemy_id)
        token = _narrative_identity(name)
        previous = identities.get(token)
        if previous is not None:
            raise ValueError(
                f"世界皮肤的个人与组队首领中文身份重复：{previous} / {name}"
            )
        identities[token] = name
    disasters = OFFICIAL_EXTENSION_CATALOG.disasters.for_source(world_id)
    collisions = tuple(
        (identities[token], disaster.name)
        for disaster in disasters
        for token in (_narrative_identity(disaster.name),)
        if token in identities
    )
    if collisions:
        details = ", ".join(f"{left} / {right}" for left, right in collisions)
        raise ValueError(f"世界皮肤的首领与灾厄中文身份重复：{details}")


def _narrative_identity(name: str) -> str:
    return str(name or "").split("·", 1)[0].strip()


def build_world_view_catalog() -> WorldViewCatalog:
    """装配一次正式规则目录，并为角色级世界投影提供缓存入口。"""

    return WorldViewCatalog(
        assemble_official_catalog(),
        PLAYABLE_WORLD_DEFINITIONS,
    )


def build_dimensional_disaster_catalog():
    """返回扩展目录冻结的灾厄名录，不再维护第二份世界来源清单。"""

    return OFFICIAL_EXTENSION_CATALOG.disasters


__all__ = [
    "DEFAULT_SKIN_ID",
    "DEFAULT_WORLD_ID",
    "COMPANION_CATALOG",
    "OFFICIAL_PACKAGES",
    "OfficialContent",
    "PLAYABLE_WORLD_DEFINITIONS",
    "PLAYABLE_WORLD_IDS",
    "WORLD_LORE_CATALOG",
    "WorldViewCatalog",
    "assemble_official_catalog",
    "build_official_content",
    "build_dimensional_disaster_catalog",
    "build_world_view_catalog",
    "select_world_skin",
    "validate_enemy_narrative_identities",
]
