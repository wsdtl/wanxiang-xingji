"""确定性扩展装配；所有运行目录都从同一份扩展事实派生。"""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

from game.core.gameplay import (
    ContentPackage,
    ContentPackageManifest,
    ContentVersion,
    PackageRequirement,
    StableId,
    stable_id,
)

from ..catalog.companion.models import CompanionCatalog
from ..catalog.disaster.catalog import DimensionalDisasterCatalog
from ..catalog.enemy.encounters import (
    PARTY_BOSS_ENCOUNTER_ID,
    build_party_boss_encounter,
)
from ..catalog.enemy.loadouts import EnemyBehaviorProfileCatalog
from ..catalog.enemy.loadouts import EnemyBehaviorProfileDefinition
from ..catalog.enemy.party import PartyBossSourceCatalog
from ..catalog.economy.market_items import MARKET_ITEM_POLICIES
from ..world_lore.models import WorldLoreCatalog
from .models import ContentExtension, WorldExtension


PARTY_ENCOUNTER_PACKAGE_ID = "content.extensions.party_encounter"
COMPOSITION_PACKAGE_ID = "content.extensions.composition"


class ExtensionCatalog:
    """冻结已启用扩展，并派生内容包和所有世界分区目录。"""

    def __init__(
        self,
        *,
        content: tuple[ContentExtension, ...] = (),
        worlds: tuple[WorldExtension, ...],
    ) -> None:
        content_values = tuple(sorted(content, key=lambda value: value.id))
        world_values = tuple(sorted(worlds, key=lambda value: (value.order, value.id)))
        if not world_values:
            raise ValueError("正式扩展目录至少需要一个可进入世界")
        self._validate_unique_ids(content_values, "内容扩展")
        self._validate_unique_ids(world_values, "世界扩展")
        skin_ids = tuple(value.skin.id for value in world_values)
        if len(skin_ids) != len(set(skin_ids)):
            raise ValueError("世界扩展不能共享同一个皮肤 ID")
        world_content = tuple(
            extension
            for world in world_values
            for extension in world.content_extensions
        )
        all_content = tuple(
            sorted((*content_values, *world_content), key=lambda value: value.id)
        )
        self._validate_unique_ids(all_content, "内容扩展")

        self.content_extensions = content_values
        self.all_content_extensions = all_content
        self.worlds = world_values
        self._by_world = MappingProxyType({value.id: value for value in world_values})
        self._skins = _merge_skin_overlays(world_values, all_content)
        self.market_item_policies = _merge_market_item_policies(all_content)
        self.party_boss_trophy_item_ids = _party_boss_trophy_items(world_values)
        self.companions = CompanionCatalog(
            tuple(value for world in world_values for value in world.companion_species),
            tuple(world.companion_sanctuary for world in world_values),
            _shared_companion_balance(world_values),
            _shared_companion_growth(world_values),
            tuple(value for world in world_values for value in world.people),
        )
        self.party_bosses = PartyBossSourceCatalog(
            tuple(world.party_boss_source for world in world_values)
        )
        self.enemy_behavior_profiles = _enemy_behavior_profiles(
            world_values,
            all_content,
        )
        self.disasters = DimensionalDisasterCatalog(
            tuple(value for world in world_values for value in world.disasters)
        )
        self.lore = WorldLoreCatalog(tuple(world.lore for world in world_values))
        self._gear_presentations = MappingProxyType(
            {
                (world.skin.id, world.skin.version): world.gear_presentation
                for world in world_values
            }
        )
        self._enemy_presentations = MappingProxyType(
            {
                (world.skin.id, world.skin.version): world.enemy_presentation
                for world in world_values
            }
        )

    @staticmethod
    def _validate_unique_ids(values, label: str) -> None:
        ids = tuple(value.id for value in values)
        if len(ids) != len(set(ids)):
            raise ValueError(f"{label} ID 重复")

    def world_ids(self) -> tuple[StableId, ...]:
        return tuple(value.id for value in self.worlds)

    def skin_ids(self) -> tuple[StableId, ...]:
        return tuple(value.skin.id for value in self.worlds)

    def skin(self, skin_id: StableId):
        key = stable_id(skin_id, field="skin id")
        try:
            return self._skins[key]
        except KeyError as exc:
            raise KeyError(f"未知扩展皮肤：{key}") from exc

    def validate_runtime(self, content) -> None:
        for enemy_id, item_id in self.party_boss_trophy_item_ids.items():
            enemy = content.enemies.require(enemy_id)
            item = content.items.require(item_id)
            if not enemy.tags.has("enemy.identity.party_boss"):
                raise ValueError(f"组队首领奖励绑定引用了非组队首领：{enemy_id}")
            if not item.tags.has("trophy.party_boss"):
                raise ValueError(f"组队首领奖励绑定引用了非首领战利品：{item_id}")

    def require_world(self, world_id: StableId) -> WorldExtension:
        key = stable_id(world_id, field="world id")
        try:
            return self._by_world[key]
        except KeyError as exc:
            raise KeyError(f"未知世界扩展：{key}") from exc

    def gear_presentation(self, skin_id: StableId, version: int):
        return self._require_presentation(
            self._gear_presentations,
            skin_id,
            version,
            "武器装备",
        )

    def enemy_presentation(self, skin_id: StableId, version: int):
        return self._require_presentation(
            self._enemy_presentations,
            skin_id,
            version,
            "敌人",
        )

    @staticmethod
    def _require_presentation(values, skin_id, version, label):
        key = (stable_id(skin_id, field="skin id"), int(version))
        try:
            return values[key]
        except KeyError as exc:
            raise KeyError(f"世界皮肤没有登记{label}展示样式：{key[0]}@{key[1]}") from exc

    def packages(self, base_package: ContentPackage) -> tuple[ContentPackage, ...]:
        standalone = tuple(
            package
            for extension in self.content_extensions
            for package in extension.packages
        )
        world_owned = tuple(
            package
            for world in self.worlds
            for extension in world.content_extensions
            for package in extension.packages
        )
        extension_packages = (*standalone, *world_owned)
        generated_worlds = tuple(
            self._world_package(world, base_package)
            for world in self.worlds
        )
        party_encounter = self._party_encounter_package(generated_worlds)
        values = (
            base_package,
            *extension_packages,
            *generated_worlds,
            party_encounter,
        )
        composition = self._composition_package(values)
        values = (*values, composition)
        package_ids = tuple(value.manifest.id for value in values)
        if len(package_ids) != len(set(package_ids)):
            raise ValueError("扩展装配生成了重复内容包 ID")
        return values

    def _composition_package(
        self,
        packages: tuple[ContentPackage, ...],
    ) -> ContentPackage:
        return ContentPackage(
            manifest=ContentPackageManifest(
                COMPOSITION_PACKAGE_ID,
                ContentVersion(1, 0, 0),
                tuple(_requirement(package) for package in packages),
            ),
            metadata={
                "extension_kind": "composition_manifest",
                "content_extensions": tuple(
                    (value.id, str(value.version))
                    for value in self.all_content_extensions
                ),
                "world_extensions": tuple(
                    (value.id, str(value.version), value.order)
                    for value in self.worlds
                ),
                "party_boss_trophies": tuple(
                    sorted(self.party_boss_trophy_item_ids.items())
                ),
                "enemy_behavior_profiles": tuple(
                    (
                        world_id,
                        tuple(
                            sorted(
                                self.enemy_behavior_profiles.require(
                                    world_id
                                ).behavior_weights.items()
                            )
                        ),
                    )
                    for world_id in self.world_ids()
                ),
                "market_item_policies": tuple(
                    (
                        item_id,
                        policy.category,
                        policy.unit_reference_price,
                        policy.minimum_price_bps,
                        policy.maximum_price_bps,
                        policy.minimum_quantity,
                        policy.maximum_quantity,
                    )
                    for item_id, policy in sorted(
                        self.market_item_policies.items()
                    )
                ),
            },
        )

    def _world_package(
        self,
        extension: WorldExtension,
        base_package: ContentPackage,
    ) -> ContentPackage:
        dependencies = [
            _requirement(base_package),
            *(
                _requirement(package)
                for content_extension in extension.content_extensions
                for package in content_extension.packages
            ),
        ]
        package_id = f"content.extension.{extension.id}"
        party_ids = frozenset(extension.party_boss_source.enemy_ids)
        return ContentPackage(
            manifest=ContentPackageManifest(
                package_id,
                extension.version,
                tuple(dependencies),
            ),
            enemies=(*extension.party_bosses, *extension.disaster_enemies),
            world_spaces=(extension.space,),
            world_definitions=(extension.bundle.world,),
            map_anchors=extension.bundle.anchors,
            world_location_bindings=extension.bundle.bindings,
            skin_packs=(self.skin(extension.skin.id),),
            skin_display_content_ids={
                extension.skin.id: frozenset({extension.space.id, *party_ids}),
            },
            metadata={
                "extension_kind": "world",
                "extension_id": extension.id,
                "extension_version": str(extension.version),
            },
        )

    def _party_encounter_package(
        self,
        world_packages: tuple[ContentPackage, ...],
    ) -> ContentPackage:
        enemy_ids = frozenset(
            enemy_id
            for world in self.worlds
            for enemy_id in world.party_boss_source.enemy_ids
        )
        return ContentPackage(
            manifest=ContentPackageManifest(
                PARTY_ENCOUNTER_PACKAGE_ID,
                ContentVersion(1, 0, 0),
                tuple(_requirement(package) for package in world_packages),
            ),
            enemy_encounters=(build_party_boss_encounter(enemy_ids),),
            display_content_ids=frozenset({PARTY_BOSS_ENCOUNTER_ID}),
            metadata={"extension_kind": "derived_party_encounter"},
        )


def _requirement(package: ContentPackage) -> PackageRequirement:
    version = package.manifest.version
    return PackageRequirement(
        package.manifest.id,
        version,
        ContentVersion(version.major + 1, 0, 0),
    )


def _shared_companion_balance(worlds: tuple[WorldExtension, ...]):
    from ..catalog.companion.definitions import COMPANION_BALANCE

    return COMPANION_BALANCE


def _shared_companion_growth(worlds: tuple[WorldExtension, ...]):
    from ..catalog.companion.definitions import COMPANION_GROWTH

    return COMPANION_GROWTH


def _merge_skin_overlays(
    worlds: tuple[WorldExtension, ...],
    content_extensions: tuple[ContentExtension, ...],
):
    skins = {world.skin.id: world.skin for world in worlds}
    known_skin_ids = set(skins)
    owners: dict[tuple[StableId, StableId], StableId] = {}
    for extension in content_extensions:
        unknown = set(extension.skin_overlays) - known_skin_ids
        if unknown:
            raise ValueError(
                f"内容扩展皮肤增量引用了未安装皮肤：{extension.id}/"
                + ", ".join(sorted(unknown))
            )
        for skin_id, overlay in extension.skin_overlays.items():
            entries = dict(skins[skin_id].entries)
            for content_id, entry in overlay.items():
                key = (skin_id, content_id)
                owner = owners.get(key)
                if content_id in entries or owner is not None:
                    raise ValueError(
                        f"内容扩展重复覆盖皮肤条目：{skin_id}/{content_id}"
                    )
                entries[content_id] = entry
                owners[key] = extension.id
            skins[skin_id] = replace(skins[skin_id], entries=entries)
    return MappingProxyType(skins)


def _merge_market_item_policies(
    content_extensions: tuple[ContentExtension, ...],
):
    policies = dict(MARKET_ITEM_POLICIES)
    for extension in content_extensions:
        for policy in extension.market_item_policies:
            if policy.definition_id in policies:
                raise ValueError(
                    f"内容扩展重复登记市场政策：{policy.definition_id}"
                )
            policies[policy.definition_id] = policy
    return MappingProxyType(policies)


def _party_boss_trophy_items(worlds: tuple[WorldExtension, ...]):
    values: dict[StableId, StableId] = {}
    item_owners: dict[StableId, StableId] = {}
    for world in worlds:
        for enemy_id, item_id in world.party_boss_trophy_item_ids.items():
            if enemy_id in values:
                raise ValueError(f"组队首领奖励重复登记：{enemy_id}")
            owner = item_owners.get(item_id)
            if owner is not None:
                raise ValueError(
                    f"组队首领 {enemy_id} 与 {owner} 共享战利品：{item_id}"
                )
            values[enemy_id] = item_id
            item_owners[item_id] = enemy_id
    return MappingProxyType(values)


def _enemy_behavior_profiles(
    worlds: tuple[WorldExtension, ...],
    content_extensions: tuple[ContentExtension, ...],
) -> EnemyBehaviorProfileCatalog:
    policy_values = tuple(
        policy
        for extension in content_extensions
        for policy in extension.enemy_behavior_weights
    )
    policy_ids = tuple(value.behavior_id for value in policy_values)
    if len(policy_ids) != len(set(policy_ids)):
        raise ValueError("多个内容扩展重复登记敌人行为权重")
    policies = {policy.behavior_id: policy for policy in policy_values}
    extension_behavior_ids = {
        behavior.id
        for extension in content_extensions
        for package in extension.packages
        for behavior in package.enemy_behaviors
    }
    values = []
    world_ids = {world.id for world in worlds}
    for policy in policies.values():
        unknown_worlds = set(policy.world_weights) - world_ids
        if unknown_worlds:
            raise ValueError(
                f"敌人行为权重引用了未安装世界：{policy.behavior_id}/"
                + ", ".join(sorted(unknown_worlds))
            )
    for world in worlds:
        weights = dict(world.enemy_behavior_profile.behavior_weights)
        for behavior_id in extension_behavior_ids:
            policy = policies.get(behavior_id)
            weights[behavior_id] = (
                policy.world_weights.get(world.id, policy.default_weight)
                if policy is not None
                else 10
            )
        values.append(EnemyBehaviorProfileDefinition(world.id, weights))
    return EnemyBehaviorProfileCatalog(tuple(values))


__all__ = [
    "COMPOSITION_PACKAGE_ID",
    "ExtensionCatalog",
    "PARTY_ENCOUNTER_PACKAGE_ID",
]
