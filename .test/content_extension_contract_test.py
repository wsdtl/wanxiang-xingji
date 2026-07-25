"""证明共享内容扩展可以完整贡献规则、展示倾向和经济政策。"""

from dataclasses import replace
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.content.catalog import CATALOG_PACKAGE  # noqa: E402
from game.content.catalog.draw import DRAW_CATALOG_CONTENT  # noqa: E402
from game.content.catalog.economy import (  # noqa: E402
    MarketItemPolicy,
    audit_market_prices,
)
from game.content.catalog.enemy import ENEMY_BEHAVIOR_CONTENT  # noqa: E402
from game.content.catalog.enemy.loadouts import EnemyBehaviorWeightPolicy  # noqa: E402
from game.content.catalog.item.exchange import EXCHANGE_MATERIAL_ITEM  # noqa: E402
from game.content.extensions import (  # noqa: E402
    ContentExtension,
    ExtensionCatalog,
    OFFICIAL_WORLD_EXTENSIONS,
)
from game.core.gameplay import (  # noqa: E402
    ContentAssembler,
    ContentPackage,
    ContentPackageManifest,
    ContentVersion,
    PackageRequirement,
    SkinEntry,
)


EXTENSION_ID = "content.contract_test.shared"
PACKAGE_ID = "content.contract_test.shared.package"
ITEM_ID = "item.exchange_material.contract_test"
BEHAVIOR_ID = "enemy.behavior.contract_test"


def main() -> None:
    extension = _extension()
    catalog = ExtensionCatalog(
        content=(extension,),
        worlds=OFFICIAL_WORLD_EXTENSIONS,
    )
    runtime = ContentAssembler().assemble(catalog.packages(CATALOG_PACKAGE))

    assert runtime.items.require(ITEM_ID)
    assert runtime.enemies.behaviors.require(BEHAVIOR_ID)
    for skin_id in catalog.skin_ids():
        skin = runtime.skins.require(skin_id)
        assert skin.entries[ITEM_ID].name.endswith("扩展材料")
        assert skin.entries[BEHAVIOR_ID].name.endswith("回响")

    behavior_ids = runtime.enemies.behaviors.ids()
    catalog.enemy_behavior_profiles.validate(catalog.world_ids(), behavior_ids)
    for world_id in catalog.world_ids():
        profile = catalog.enemy_behavior_profiles.require(world_id)
        expected = 18 if world_id == "world.magic" else 11
        assert profile.behavior_weights[BEHAVIOR_ID] == expected

    assert catalog.market_item_policies[ITEM_ID].unit_reference_price == 777
    audit_market_prices(
        runtime.items,
        DRAW_CATALOG_CONTENT,
        runtime.equipment,
        market_item_policies=catalog.market_item_policies,
        expected_party_trophy_ids=frozenset(
            catalog.party_boss_trophy_item_ids.values()
        ),
    )
    catalog.validate_runtime(runtime)
    print("content extension contract tests passed")


def _extension() -> ContentExtension:
    item = replace(EXCHANGE_MATERIAL_ITEM, id=ITEM_ID)
    behavior = replace(ENEMY_BEHAVIOR_CONTENT.behaviors[0], id=BEHAVIOR_ID)
    dependency = PackageRequirement(
        CATALOG_PACKAGE.manifest.id,
        CATALOG_PACKAGE.manifest.version,
        ContentVersion(CATALOG_PACKAGE.manifest.version.major + 1, 0, 0),
    )
    package = ContentPackage(
        manifest=ContentPackageManifest(
            PACKAGE_ID,
            ContentVersion(1, 0, 0),
            (dependency,),
        ),
        enemy_behaviors=(behavior,),
        items=(item,),
        display_content_ids=frozenset({ITEM_ID, BEHAVIOR_ID}),
    )
    overlays = {
        world.skin.id: {
            ITEM_ID: SkinEntry(name=f"{world.skin.name}扩展材料"),
            BEHAVIOR_ID: SkinEntry(name=f"{world.skin.name}回响"),
        }
        for world in OFFICIAL_WORLD_EXTENSIONS
    }
    return ContentExtension(
        id=EXTENSION_ID,
        version=ContentVersion(1, 0, 0),
        packages=(package,),
        skin_overlays=overlays,
        enemy_behavior_weights=(
            EnemyBehaviorWeightPolicy(
                BEHAVIOR_ID,
                11,
                {"world.magic": 18},
            ),
        ),
        market_item_policies=(
            MarketItemPolicy(
                ITEM_ID,
                "exchange_material",
                777,
                5_000,
                20_000,
                maximum_quantity=99,
            ),
        ),
    )


if __name__ == "__main__":
    main()
