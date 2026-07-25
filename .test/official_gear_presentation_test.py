"""武器装备品质全名、评分术语与铭刻覆盖测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.content import (  # noqa: E402
    COMMON_QUALITY_ID,
    STARTER_WEAPON_ID,
    assemble_official_catalog,
    select_world_skin,
)
from game.content.catalog.equipment.definitions import (  # noqa: E402
    equipment_definition_id,
    equipment_set_id,
)
from game.content.catalog.weapon.mechanics import WEAPON_MAXIMUM_LEVEL_TABLE  # noqa: E402
from game.content.world_skins import (  # noqa: E402
    CULTIVATION_SKIN_ID,
    MAGIC_SKIN_ID,
    STELLAR_RING_SKIN_ID,
)
from game.features.battle_report import resolve_battle_content_name  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    INSCRIPTION_DATA_KEY,
    InscriptionData,
    InscriptionPreference,
    ItemInstance,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    SourceReceipt,
)
from game.rules import (  # noqa: E402
    EquipmentGenerationRequest,
    EquipmentInstanceGenerator,
    WeaponGenerationRequest,
    WeaponInstanceGenerator,
)


TIME = datetime(2026, 7, 17, tzinfo=timezone.utc)


def main() -> None:
    catalog = assemble_official_catalog()
    cultivation = select_world_skin(catalog, CULTIVATION_SKIN_ID)
    magic = select_world_skin(catalog, MAGIC_SKIN_ID)
    stellar = select_world_skin(catalog, STELLAR_RING_SKIN_ID)

    starter = catalog.weapons.create_state(
        asset_id="starter-display",
        definition_id=STARTER_WEAPON_ID,
        quality_id=COMMON_QUALITY_ID,
    )
    starter_display = cultivation.gear_projector.weapon(starter)
    assert starter_display.name == "黄品·仙京制式剑"
    assert starter_display.score is None and starter_display.score_text == ""

    weapon_id = next(
        value
        for value in catalog.weapons.definitions.ids()
        if catalog.weapons.require(value).generation_profile_id is not None
    )
    weapon = WeaponInstanceGenerator(
        catalog.weapons,
        catalog.itemization_engine,
        WEAPON_MAXIMUM_LEVEL_TABLE,
    ).generate(
        WeaponGenerationRequest(
            "gear-display-weapon",
            "gear-display-weapon-asset",
            weapon_id,
            catalog.report.content_fingerprint,
        ),
        context=_context("gear-display-weapon", 701),
    ).state
    cultivation_weapon = cultivation.gear_projector.weapon(weapon)
    magic_weapon = magic.gear_projector.weapon(weapon)
    stellar_weapon = stellar.gear_projector.weapon(weapon)
    assert cultivation_weapon.name == (
        f"{cultivation.projector.name(weapon.quality_id)}品·"
        f"{cultivation.projector.name(weapon.definition_id)}"
    )
    assert magic_weapon.name == (
        f"{magic.projector.name(weapon.quality_id)}·"
        f"{magic.projector.name(weapon.definition_id)}"
    )
    assert stellar_weapon.name == (
        f"{stellar.projector.name(weapon.quality_id)}·"
        f"{stellar.projector.name(weapon.definition_id)}"
    )
    assert stellar_weapon.score_text.startswith("结构评分:")
    assert cultivation_weapon.score_label == "器蕴评分"
    assert magic_weapon.score_label == "魔能评分"
    assert cultivation_weapon.score == weapon.roll.intrinsic_value.total
    assert cultivation_weapon.score_text.startswith("器蕴评分: ")

    equipment = EquipmentInstanceGenerator(
        catalog.equipment,
        catalog.itemization_engine,
        set_mark_chance=0,
    ).generate(
        EquipmentGenerationRequest(
            "gear-display-equipment",
            "gear-display-equipment-asset",
            equipment_definition_id("mystic_sky", "head"),
            catalog.report.content_fingerprint,
        ),
        context=_context("gear-display-equipment", 702),
    ).state
    equipment_definition = catalog.equipment.require(equipment.definition_id)
    instance = ItemInstance(
        equipment.asset_id,
        equipment_definition.item_definition_id,
        "container.armament",
        SourceReceipt("gear-display-source", "source.test", "gear-display", TIME),
        data={INSCRIPTION_DATA_KEY: InscriptionData(asset_name="照夜")},
    )
    engraved = cultivation.gear_projector.equipment(equipment, instance)
    assert engraved.base_name.startswith(
        f"{cultivation.projector.name(equipment.quality_id)}品·"
    )
    assert engraved.name == f"照夜（{engraved.base_name}）"
    hidden = cultivation.gear_projector.equipment(
        equipment,
        instance,
        inscription_preference=InscriptionPreference("player", False),
    )
    assert hidden.name == "照夜"

    for view in (cultivation, magic, stellar):
        set_id = equipment_set_id("army_breaker")
        set_name = view.projector.name(set_id)
        for pieces in (2, 3, 4):
            bonus_name = resolve_battle_content_name(
                view,
                f"{set_id}.bonus.pieces_{pieces}",
                "未命名效果",
            )
            assert set_name in bonus_name
            assert f"{pieces}件" in bonus_name

    print("official gear presentation test passed")


def _context(trace_id: str, seed: int) -> RuleContext:
    return RuleContext(
        trace_id,
        "rules.gear_presentation_test",
        Ruleset("ruleset.gear_presentation_test"),
        TIME,
        SeededRandomSource(seed),
    )


if __name__ == "__main__":
    main()
