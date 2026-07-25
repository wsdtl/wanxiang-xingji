"""蓝图作者入口必须能不修改基础名录地装配新内容。"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.content.catalog import CATALOG_PACKAGE  # noqa: E402
from game.content.catalog.equipment.blueprints import (  # noqa: E402
    EQUIPMENT_SLOT_BLUEPRINTS,
    EquipmentFamilyBlueprint,
    EquipmentSetBlueprint,
)
from game.content.catalog.equipment.ids import equipment_trigger_id  # noqa: E402
from game.content.catalog.equipment.mechanisms import (  # noqa: E402
    CompiledEquipmentMechanic,
    EquipmentMechanicDefinition,
)
from game.content.catalog.weapon.blueprints import WeaponBlueprint  # noqa: E402
from game.content.extensions import (  # noqa: E402
    ContentPresentation,
    EquipmentSkinPresentation,
    ExtensionCatalog,
    OFFICIAL_WORLD_EXTENSIONS,
    build_equipment_content_extension,
    build_equipment_mechanic_content_extension,
    build_weapon_content_extension,
)
from game.core.gameplay import (  # noqa: E402
    COMBAT_ATTACK,
    AttributeGrant,
    ContentAssembler,
    ContentVersion,
    ContributionSpec,
    ModifierLayer,
    EffectDefinition,
    FixedMagnitude,
    ModifyAttribute,
    TriggerDefinition,
    TriggerOwner,
    TriggerSource,
    TriggerTarget,
    ValueVector,
)


def main() -> None:
    version = ContentVersion(1, 0, 0)
    weapon = WeaponBlueprint(
        "contract_lantern",
        "resource",
        "spirit_burst",
        "shield",
        "single",
        1.08,
        24,
        3,
        ValueVector(offense=36, survival=12),
    )
    weapon_extension = build_weapon_content_extension(
        extension_id="content.contract.weapon",
        package_id="content.contract.weapon.package",
        version=version,
        blueprints=(weapon,),
        skin_presentations={
            world.skin.id: {
                weapon.key: ContentPresentation(
                    f"{world.skin.name}契约灯",
                    "使用独立内容扩展编译的测试武器。",
                    "◇",
                )
            }
            for world in OFFICIAL_WORLD_EXTENSIONS
        },
        base_package=CATALOG_PACKAGE,
    )

    def compile_contract_mechanic(tier: int) -> CompiledEquipmentMechanic:
        effect_id = f"effect.equipment.contract_focus.tier_{tier}"
        trigger_id = equipment_trigger_id("contract_focus", tier)
        return CompiledEquipmentMechanic(
            (
                EffectDefinition(
                    effect_id,
                    operations=(
                        ModifyAttribute(
                            f"operation.equipment.contract_focus.tier_{tier}",
                            COMBAT_ATTACK,
                            ModifierLayer.GLOBAL_FLAT,
                            FixedMagnitude(tier),
                        ),
                    ),
                    duration_turns=1,
                ),
            ),
            (
                TriggerDefinition(
                    trigger_id,
                    "combat.turn.started",
                    effect_id,
                    target=TriggerTarget.OWNER,
                    owner=TriggerOwner.EVENT_SOURCE,
                    source=TriggerSource.OWNER,
                ),
            ),
        )

    mechanic = EquipmentMechanicDefinition(
        "contract_focus",
        "offense",
        ValueVector(offense=6),
        compile_contract_mechanic,
    )
    mechanic_extension = build_equipment_mechanic_content_extension(
        extension_id="content.contract.equipment_mechanic",
        package_id="content.contract.equipment_mechanic.package",
        version=version,
        profile_id="generation.equipment.contract",
        mechanisms=(mechanic,),
        skin_presentations={
            world.skin.id: {
                mechanic.key: ContentPresentation(
                    f"{world.skin.name}契约聚意",
                    "由独立装备机制扩展注册的随机词条。",
                    "◈",
                )
            }
            for world in OFFICIAL_WORLD_EXTENSIONS
        },
        base_package=CATALOG_PACKAGE,
    )

    family = EquipmentFamilyBlueprint("contract_weave")
    equipment_set = EquipmentSetBlueprint(
        "contract_oath",
        (
            ContributionSpec(
                attributes=(
                    AttributeGrant(COMBAT_ATTACK, ModifierLayer.LOCAL_FLAT, 2),
                )
            ),
            ContributionSpec(
                attributes=(
                    AttributeGrant(COMBAT_ATTACK, ModifierLayer.LOCAL_FLAT, 3),
                )
            ),
            ContributionSpec(
                attributes=(
                    AttributeGrant(COMBAT_ATTACK, ModifierLayer.LOCAL_FLAT, 5),
                )
            ),
        ),
    )
    equipment_extension = build_equipment_content_extension(
        extension_id="content.contract.equipment",
        package_id="content.contract.equipment.package",
        version=version,
        families=(family,),
        sets=(equipment_set,),
        skin_presentations={
            world.skin.id: EquipmentSkinPresentation(
                families={
                    family.key: ContentPresentation(
                        f"{world.skin.name}契织",
                        "由扩展蓝图生成的装备底座族。",
                        "◈",
                    )
                },
                sets={
                    equipment_set.key: ContentPresentation(
                        f"{world.skin.name}契誓",
                        "由扩展蓝图生成的套装。",
                        "◈",
                    )
                },
                slot_names={
                    slot.key: f"契约{index}"
                    for index, slot in enumerate(EQUIPMENT_SLOT_BLUEPRINTS, 1)
                },
            )
            for world in OFFICIAL_WORLD_EXTENSIONS
        },
        base_package=mechanic_extension.packages[0],
        generation_profile_id="generation.equipment.contract",
    )

    extensions = ExtensionCatalog(
        content=(weapon_extension, mechanic_extension, equipment_extension),
        worlds=OFFICIAL_WORLD_EXTENSIONS,
    )
    runtime = ContentAssembler().assemble(extensions.packages(CATALOG_PACKAGE))
    assert runtime.weapons.require("weapon.contract_lantern")
    assert runtime.equipment.families.require("equipment_family.contract_weave")
    assert runtime.equipment.sets.require("equipment_set.contract_oath")
    assert runtime.itemization_engine.catalog.require_property(
        "property.equipment.contract_focus"
    )
    assert runtime.items.require("item.blueprint.equipment_set.contract_oath")
    assert extensions.market_item_policies[
        "item.blueprint.equipment_set.contract_oath"
    ].category == "blueprint"
    for skin_id in extensions.skin_ids():
        skin = runtime.skins.require(skin_id)
        assert skin.entries["weapon.contract_lantern"].name.endswith("契约灯")
        assert skin.entries["equipment_set.contract_oath"].name.endswith("契誓")
    print("content authoring tests passed")


if __name__ == "__main__":
    main()
