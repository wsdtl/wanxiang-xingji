"""证明新增完整世界只需提供一个 WorldExtension，不修改旧世界或中央清单。"""

from dataclasses import replace
from pathlib import Path
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.content.catalog import CATALOG_PACKAGE  # noqa: E402
from game.content.catalog.draw import DRAW_CATALOG_CONTENT  # noqa: E402
from game.content.catalog.economy import audit_market_prices  # noqa: E402
from game.content.catalog.enemy import AWARD_PARTY_BOSS_TROPHY_ID  # noqa: E402
from game.content.catalog.item import PARTY_BOSS_TROPHY_ITEMS  # noqa: E402
from game.content.catalog.world import (  # noqa: E402
    LOCATION_FUNCTION_COMPANION_PERSON,
    coordinate_token,
)
from game.content.extensions import (  # noqa: E402
    ExtensionCatalog,
    ContentExtension,
    OFFICIAL_WORLD_EXTENSIONS,
    WorldExtension,
)
from game.content.presentation import EnemyPresentationStyle, GearPresentationStyle  # noqa: E402
from game.content.worlds.models import OfficialWorldBundle  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    ContentAssembler,
    ContentPackage,
    ContentPackageManifest,
    ContentVersion,
    PackageRequirement,
    SkinEntry,
    StableId,
)
from game.features.party_battle.rewards import PartyBattleRewardFactory  # noqa: E402


WORLD_ID = "world.contract_test"
SPACE_ID = "world_space.contract_test"
SKIN_ID = "skin.contract_test"


def main() -> None:
    dummy = _dummy_world_extension()
    catalog = ExtensionCatalog(worlds=(*OFFICIAL_WORLD_EXTENSIONS, dummy))
    assert catalog.world_ids() == (
        "world.taixuan",
        "world.magic",
        "world.stellar_ring",
        WORLD_ID,
    )

    runtime = ContentAssembler().assemble(catalog.packages(CATALOG_PACKAGE))
    assert runtime.world_runtime is not None
    assert set(runtime.world_runtime.world_ids()) == set(catalog.world_ids())
    assert runtime.skins.require(SKIN_ID).name == "契约测试界"
    assert runtime.enemies.require(next(iter(dummy.party_boss_source.enemy_ids)))

    catalog.companions.validate(runtime, runtime.world_runtime)
    catalog.party_bosses.validate(runtime, catalog.world_ids())
    catalog.enemy_behavior_profiles.validate(
        catalog.world_ids(),
        runtime.enemies.behaviors.ids(),
    )
    catalog.disasters.validate(runtime, catalog.world_ids())
    assert catalog.lore.world_ids() == catalog.world_ids()
    catalog.validate_runtime(runtime)
    audit_market_prices(
        runtime.items,
        DRAW_CATALOG_CONTENT,
        runtime.equipment,
        market_item_policies=catalog.market_item_policies,
        expected_party_trophy_ids=frozenset(
            catalog.party_boss_trophy_item_ids.values()
        ),
    )
    reward_factory = PartyBattleRewardFactory(
        SimpleNamespace(
            catalog=runtime,
            party_boss_trophy_item_ids=catalog.party_boss_trophy_item_ids,
        )
    )
    first_party_boss = dummy.party_bosses[0].id
    assert reward_factory._stack_definition(
        AWARD_PARTY_BOSS_TROPHY_ID,
        first_party_boss,
    ) == dummy.party_boss_trophy_item_ids[first_party_boss]

    reversed_catalog = ExtensionCatalog(
        worlds=tuple(reversed((*OFFICIAL_WORLD_EXTENSIONS, dummy)))
    )
    assert reversed_catalog.world_ids() == catalog.world_ids()
    repeated = ContentAssembler().assemble(reversed_catalog.packages(CATALOG_PACKAGE))
    assert repeated.report.content_fingerprint == runtime.report.content_fingerprint
    print("world extension contract tests passed")


def _dummy_world_extension() -> WorldExtension:
    base = OFFICIAL_WORLD_EXTENSIONS[0]
    space = replace(base.space, id=SPACE_ID)

    anchor_ids: dict[StableId, StableId] = {}
    anchors = []
    for anchor in base.bundle.anchors:
        anchor_id = (
            "map_anchor.contract_test"
            f"_x{coordinate_token(anchor.x)}_y{coordinate_token(anchor.y)}"
        )
        anchor_ids[anchor.id] = anchor_id
        anchors.append(replace(anchor, id=anchor_id))

    species = tuple(
        replace(
            value,
            id=f"companion.contract_test.c{index}",
            origin_world_id=WORLD_ID,
            name=f"契约生灵{index}",
        )
        for index, value in enumerate(base.companion_species, start=1)
    )
    people = tuple(
        replace(
            value,
            id=f"companion.person.contract_test.p{index}",
            origin_world_id=WORLD_ID,
            name=f"契约旅人{index}",
        )
        for index, value in enumerate(base.people, start=1)
    )
    people_by_location = {value.location_id: value.id for value in people}
    bindings = tuple(
        replace(
            value,
            world_id=WORLD_ID,
            anchor_id=anchor_ids[value.anchor_id],
            content_ref=(
                people_by_location[value.display_ref]
                if value.function_id == LOCATION_FUNCTION_COMPANION_PERSON
                and value.display_ref is not None
                else value.content_ref
            ),
        )
        for value in base.bundle.bindings
    )
    world = replace(
        base.bundle.world,
        id=WORLD_ID,
        space_id=SPACE_ID,
        skin_id=SKIN_ID,
        spawn_anchor_id=anchor_ids[base.bundle.world.spawn_anchor_id],
    )
    bundle = OfficialWorldBundle(world, tuple(anchors), bindings)

    party_id_map = {
        value.id: f"enemy.boss.party.contract_test.b{index}"
        for index, value in enumerate(base.party_bosses, start=1)
    }
    party_bosses = tuple(
        replace(value, id=party_id_map[value.id])
        for value in base.party_bosses
    )
    party_source = replace(
        base.party_boss_source,
        source_world_id=WORLD_ID,
        enemy_ids=frozenset(party_id_map.values()),
    )
    trophy_id_map = {
        enemy.id: f"item.trophy.party_boss.contract_test.b{index}"
        for index, enemy in enumerate(party_bosses, start=1)
    }
    trophy_items = tuple(
        replace(
            PARTY_BOSS_TROPHY_ITEMS[(index - 1) % len(PARTY_BOSS_TROPHY_ITEMS)],
            id=trophy_id_map[enemy.id],
        )
        for index, enemy in enumerate(party_bosses, start=1)
    )
    trophy_ids = frozenset(value.id for value in trophy_items)
    trophy_content = ContentExtension(
        id="content.contract_test.trophies",
        version=ContentVersion(1, 0, 0),
        packages=(
            ContentPackage(
                manifest=ContentPackageManifest(
                    "content.contract_test.trophies.package",
                    ContentVersion(1, 0, 0),
                    (
                        PackageRequirement(
                            CATALOG_PACKAGE.manifest.id,
                            CATALOG_PACKAGE.manifest.version,
                            ContentVersion(
                                CATALOG_PACKAGE.manifest.version.major + 1,
                                0,
                                0,
                            ),
                        ),
                    ),
                ),
                items=trophy_items,
                skin_display_content_ids={SKIN_ID: trophy_ids},
            ),
        ),
        skin_overlays={
            SKIN_ID: {
                item_id: SkinEntry(name=f"契约战利品{index}")
                for index, item_id in enumerate(sorted(trophy_ids), start=1)
            }
        },
    )

    disaster_id_map = {
        value.enemy_definition_id: f"enemy.boss.disaster.contract_test.d{index}"
        for index, value in enumerate(base.disasters, start=1)
    }
    disasters = tuple(
        replace(
            value,
            id=f"disaster.contract_test.d{index}",
            source_world_id=WORLD_ID,
            enemy_definition_id=disaster_id_map[value.enemy_definition_id],
            name=f"契约灾厄{index}",
        )
        for index, value in enumerate(base.disasters, start=1)
    )
    disaster_enemies = tuple(
        replace(value, id=disaster_id_map[value.id])
        for value in base.disaster_enemies
    )

    entries = dict(base.skin.entries)
    entries[SPACE_ID] = SkinEntry(name="契约测试界域")
    entries.update(
        {
            enemy_id: SkinEntry(name=f"契约首领{index}")
            for index, enemy_id in enumerate(sorted(party_id_map.values()), start=1)
        }
    )
    skin = replace(
        base.skin,
        id=SKIN_ID,
        version=1,
        name="契约测试界",
        entries=entries,
    )
    gear_presentation = replace(
        base.gear_presentation,
        skin_id=SKIN_ID,
        skin_version=1,
    )
    enemy_presentation = replace(
        base.enemy_presentation,
        skin_id=SKIN_ID,
        skin_version=1,
    )
    assert isinstance(gear_presentation, GearPresentationStyle)
    assert isinstance(enemy_presentation, EnemyPresentationStyle)

    lore = replace(
        base.lore,
        world_id=WORLD_ID,
        overview="用于验证世界插槽契约的完整测试世界。",
        records=tuple(
            replace(value, id=f"lore.contract_test.t{value.threshold}")
            for value in base.lore.records
        ),
    )
    return WorldExtension(
        id=WORLD_ID,
        version=ContentVersion(1, 0, 0),
        order=40,
        space=space,
        bundle=bundle,
        skin=skin,
        gear_presentation=gear_presentation,
        enemy_presentation=enemy_presentation,
        companion_species=species,
        companion_sanctuary=replace(
            base.companion_sanctuary,
            id="companion_sanctuary.contract_test",
            world_id=WORLD_ID,
            species_ids=tuple(value.id for value in species),
        ),
        people=people,
        enemy_behavior_profile=replace(
            base.enemy_behavior_profile,
            world_id=WORLD_ID,
        ),
        party_bosses=party_bosses,
        party_boss_source=party_source,
        party_boss_trophy_item_ids=trophy_id_map,
        disasters=disasters,
        disaster_enemies=disaster_enemies,
        lore=lore,
        content_extensions=(trophy_content,),
    )


if __name__ == "__main__":
    main()
