"""价值曲线、受约束武器与开放装备随机生成测试。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay import (  # noqa: E402
    AttributeGrant,
    ContributionSpec,
    ModifierLayer,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    TagSet,
)
from game.core.gameplay.itemization import (  # noqa: E402
    ITEMIZATION_FOUNDATION_VERSION,
    GenerationProfileDefinition,
    ItemGenerationCommand,
    ItemizationCatalog,
    ItemizationEngine,
    ItemizationKind,
    PropertyDefinition,
    PropertyParameterDefinition,
    PropertyTierDefinition,
    QualityValueBand,
)
from game.core.gameplay.valuation import (  # noqa: E402
    VALUATION_FOUNDATION_VERSION,
    AttributeValuationDefinition,
    ReferenceValuationDefinition,
    ReferenceValueKind,
    SynergyValuationDefinition,
    ValuationCatalog,
    ValuationEngine,
    ValueAxis,
    ValueCurvePoint,
    ValueVector,
)


TIME = datetime(2026, 7, 14, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
    assert ITEMIZATION_FOUNDATION_VERSION == "itemization.foundation.v2"
    assert VALUATION_FOUNDATION_VERSION == "valuation.foundation.v2"
    valuation = _valuation()
    engine = _itemization(valuation)
    _assert_curves_and_marginal(valuation)
    _assert_weapon_constraints_and_replay(engine)
    _assert_equipment_is_open(engine)
    _assert_unvalued_contribution_is_rejected(valuation)
    print("itemization foundation tests passed")


def _valuation() -> ValuationEngine:
    catalog = ValuationCatalog()
    catalog.register_attribute(
        AttributeValuationDefinition(
            "combat.attack",
            ModifierLayer.LOCAL_FLAT,
            ValueAxis.OFFENSE,
            (
                ValueCurvePoint(-20, -30),
                ValueCurvePoint(0, 0),
                ValueCurvePoint(20, 20),
                ValueCurvePoint(40, 32),
            ),
        )
    )
    catalog.register_attribute(
        AttributeValuationDefinition(
            "combat.defense",
            ModifierLayer.LOCAL_FLAT,
            ValueAxis.SURVIVAL,
            (
                ValueCurvePoint(-20, -25),
                ValueCurvePoint(0, 0),
                ValueCurvePoint(20, 18),
                ValueCurvePoint(40, 28),
            ),
        )
    )
    catalog.register_reference(
        ReferenceValuationDefinition(
            ReferenceValueKind.TRIGGER,
            "trigger.combo_core",
            ValueVector(offense=18, volatility=4),
        )
    )
    catalog.register_synergy(
        SynergyValuationDefinition(
            "valuation.combo_attack",
            TagSet.of("style.combo", "property.attack"),
            ValueVector(offense=5),
        )
    )
    catalog.finalize()
    return ValuationEngine(catalog)


def _itemization(valuation: ValuationEngine) -> ItemizationEngine:
    catalog = ItemizationCatalog()
    catalog.register_property(
        PropertyDefinition(
            "property.combo_core",
            1,
            (
                PropertyTierDefinition(
                    1,
                    1,
                    ContributionSpec(triggers=frozenset({"trigger.combo_core"})),
                ),
            ),
            tags=TagSet.of("style.combo"),
        )
    )
    catalog.register_property(
        PropertyDefinition(
            "property.attack_roll",
            1,
            (
                PropertyTierDefinition(
                    1,
                    1,
                    parameters=(
                        PropertyParameterDefinition(
                            "parameter.attack",
                            "combat.attack",
                            ModifierLayer.LOCAL_FLAT,
                            10,
                            20,
                            5,
                        ),
                    ),
                ),
            ),
            tags=TagSet.of("property.attack"),
            required_selected_tags=TagSet.of("style.combo"),
        )
    )
    catalog.register_property(
        PropertyDefinition(
            "property.guard_roll",
            1,
            (
                PropertyTierDefinition(
                    1,
                    1,
                    parameters=(
                        PropertyParameterDefinition(
                            "parameter.defense",
                            "combat.defense",
                            ModifierLayer.LOCAL_FLAT,
                            10,
                            20,
                            5,
                        ),
                    ),
                ),
            ),
            tags=TagSet.of("style.guard"),
            required_selected_tags=TagSet.of("style.guard"),
        )
    )
    bands = (
        QualityValueBand("quality.common", 0, 30),
        QualityValueBand("quality.rare", 30, None),
    )
    catalog.register_profile(
        GenerationProfileDefinition(
            "generation.weapon_combo",
            ItemizationKind.WEAPON,
            frozenset(
                {
                    "property.combo_core",
                    "property.attack_roll",
                    "property.guard_roll",
                }
            ),
            2,
            2,
            bands,
            core_property_ids=frozenset({"property.combo_core"}),
            enforce_compatibility=True,
        )
    )
    catalog.register_profile(
        GenerationProfileDefinition(
            "generation.equipment_open",
            ItemizationKind.EQUIPMENT,
            frozenset({"property.attack_roll", "property.guard_roll"}),
            2,
            2,
            bands,
            enforce_compatibility=False,
        )
    )
    catalog.finalize()
    return ItemizationEngine(catalog, valuation)


def _context(seed: str) -> RuleContext:
    return RuleContext(
        f"itemization-{seed}",
        "rules.itemization_v1",
        Ruleset("ruleset.itemization_test"),
        TIME,
        SeededRandomSource(seed),
    )


def _assert_curves_and_marginal(valuation: ValuationEngine) -> None:
    base = ContributionSpec(
        attributes=(
            AttributeGrant("combat.attack", ModifierLayer.LOCAL_FLAT, 20),
        ),
        tags=TagSet.of("style.combo"),
    )
    added = ContributionSpec(
        attributes=(
            AttributeGrant("combat.attack", ModifierLayer.LOCAL_FLAT, 20),
        ),
        tags=TagSet.of("property.attack"),
    )
    assert valuation.evaluate(base).total == 20
    marginal = valuation.marginal((base,), (added,))
    assert marginal.total == 17


def _assert_weapon_constraints_and_replay(engine: ItemizationEngine) -> None:
    command = ItemGenerationCommand(
        "generate-weapon-1",
        "generation.weapon_combo",
        "content-fingerprint-1",
    )
    first = engine.generate(command, context=_context("same"))
    second = engine.generate(command, context=_context("same"))
    assert first == second
    assert [value.property_id for value in first.roll.properties] == [
        "property.combo_core",
        "property.attack_roll",
    ]
    assert first.roll.quality_id == "quality.rare"
    assert engine.validate_roll(first.roll) == first.contribution


def _assert_equipment_is_open(engine: ItemizationEngine) -> None:
    execution = engine.generate(
        ItemGenerationCommand(
            "generate-equipment-1",
            "generation.equipment_open",
            "content-fingerprint-1",
        ),
        context=_context("equipment"),
    )
    assert {value.property_id for value in execution.roll.properties} == {
        "property.attack_roll",
        "property.guard_roll",
    }
    assert execution.roll.intrinsic_value.offense > 0
    assert execution.roll.intrinsic_value.survival > 0


def _assert_unvalued_contribution_is_rejected(valuation: ValuationEngine) -> None:
    try:
        valuation.evaluate(ContributionSpec(abilities=frozenset({"ability.unknown"})))
        raise AssertionError("未登记价值的机制不能进入随机池")
    except ValueError:
        pass


if __name__ == "__main__":
    main()
