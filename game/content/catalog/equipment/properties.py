"""正式装备的开放随机词条、真实触发机制和生成策略。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.gameplay import (
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    COMBAT_SPEED,
    HEALTH_MAXIMUM,
    SPIRIT_MAXIMUM,
    ContributionSpec,
    EffectDefinition,
    GenerationProfileDefinition,
    ItemizationKind,
    ModifierLayer,
    PropertyDefinition,
    PropertyParameterDefinition,
    PropertyTierDefinition,
    QualityValueBand,
    ReferenceValuationDefinition,
    ReferenceValueKind,
    TagSet,
    TriggerDefinition,
)

from ..foundation import (
    COMMON_QUALITY_ID,
    EPIC_QUALITY_ID,
    FINE_QUALITY_ID,
    LEGENDARY_QUALITY_ID,
    RARE_QUALITY_ID,
)
from ..combat.stats import (
    COMBAT_ACCURACY,
    COMBAT_BLOCK_CHANCE,
    COMBAT_BLOCK_REDUCTION,
    COMBAT_CONTROL_CHANCE,
    COMBAT_CONTROL_RESISTANCE,
    COMBAT_CRITICAL_CHANCE,
    COMBAT_CRITICAL_DAMAGE,
    COMBAT_EVASION,
    COMBAT_FLAT_PENETRATION,
    COMBAT_HEALING_RATE,
    COMBAT_HEALING_RECEIVED,
    COMBAT_INCOMING_RATE,
    COMBAT_OUTGOING_RATE,
    COMBAT_RATE_PENETRATION,
    COMBAT_TENACITY,
)
from .blueprints import (
    EQUIPMENT_PROPERTY_BLUEPRINTS,
)
from .ids import equipment_trigger_id
from .mechanisms import OFFICIAL_EQUIPMENT_MECHANICS


EQUIPMENT_GENERATION_PROFILE_ID = "generation.equipment.open"
EQUIPMENT_SET_MARK_CHANCE = 0.25
EQUIPMENT_QUALITY_BANDS = (
    QualityValueBand(COMMON_QUALITY_ID, 0, 23),
    QualityValueBand(FINE_QUALITY_ID, 23, 32),
    QualityValueBand(RARE_QUALITY_ID, 32, 40),
    QualityValueBand(EPIC_QUALITY_ID, 40, 50),
    QualityValueBand(LEGENDARY_QUALITY_ID, 50),
)


@dataclass(frozen=True)
class EquipmentPropertyContent:
    effects: tuple[EffectDefinition, ...]
    triggers: tuple[TriggerDefinition, ...]
    properties: tuple[PropertyDefinition, ...]
    profiles: tuple[GenerationProfileDefinition, ...]
    reference_valuations: tuple[ReferenceValuationDefinition, ...]
    display_ids: frozenset[str]


def equipment_property_id(key: str) -> str:
    return f"property.equipment.{key}"


def _ranges(*values: tuple[float, float, float]):
    if len(values) != 3:
        raise ValueError("装备数值词条必须提供三个档位")
    return values


NUMERIC_PROPERTY_SPECS = {
    "health": (
        ("health", HEALTH_MAXIMUM, ModifierLayer.LOCAL_FLAT, _ranges((20, 45, 5), (50, 90, 5), (100, 160, 10))),
    ),
    "spirit": (("spirit", SPIRIT_MAXIMUM, ModifierLayer.LOCAL_FLAT, _ranges((12, 24, 2), (26, 46, 2), (50, 80, 5))),),
    "attack": (("attack", COMBAT_ATTACK, ModifierLayer.LOCAL_FLAT, _ranges((2, 5, 1), (6, 10, 1), (11, 16, 1))),),
    "defense": (("defense", COMBAT_DEFENSE, ModifierLayer.LOCAL_FLAT, _ranges((3, 7, 1), (8, 13, 1), (14, 21, 1))),),
    "speed": (("speed", COMBAT_SPEED, ModifierLayer.LOCAL_FLAT, _ranges((2, 5, 1), (6, 10, 1), (11, 16, 1))),),
    "accuracy": (
        (
            "accuracy",
            COMBAT_ACCURACY,
            ModifierLayer.GLOBAL_FLAT,
            _ranges((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.13, 0.01)),
        ),
    ),
    "evasion": (
        (
            "evasion",
            COMBAT_EVASION,
            ModifierLayer.GLOBAL_FLAT,
            _ranges((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.13, 0.01)),
        ),
    ),
    "critical_chance": (
        (
            "critical_chance",
            COMBAT_CRITICAL_CHANCE,
            ModifierLayer.GLOBAL_FLAT,
            _ranges((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.13, 0.01)),
        ),
    ),
    "critical_damage": (
        (
            "critical_damage",
            COMBAT_CRITICAL_DAMAGE,
            ModifierLayer.GLOBAL_FLAT,
            _ranges((0.05, 0.10, 0.01), (0.11, 0.18, 0.01), (0.19, 0.28, 0.01)),
        ),
    ),
    "block_chance": (
        (
            "block_chance",
            COMBAT_BLOCK_CHANCE,
            ModifierLayer.GLOBAL_FLAT,
            _ranges((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.13, 0.01)),
        ),
    ),
    "block_reduction": (
        (
            "block_reduction",
            COMBAT_BLOCK_REDUCTION,
            ModifierLayer.GLOBAL_FLAT,
            _ranges((0.04, 0.08, 0.01), (0.09, 0.14, 0.01), (0.15, 0.22, 0.01)),
        ),
    ),
    "outgoing": (
        (
            "outgoing",
            COMBAT_OUTGOING_RATE,
            ModifierLayer.GLOBAL_FLAT,
            _ranges((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.12, 0.01)),
        ),
    ),
    "incoming": (
        (
            "incoming",
            COMBAT_INCOMING_RATE,
            ModifierLayer.GLOBAL_FLAT,
            _ranges((-0.04, -0.02, 0.01), (-0.08, -0.05, 0.01), (-0.13, -0.09, 0.01)),
        ),
    ),
    "flat_penetration": (
        (
            "flat_penetration",
            COMBAT_FLAT_PENETRATION,
            ModifierLayer.GLOBAL_FLAT,
            _ranges((2, 5, 1), (6, 10, 1), (11, 17, 1)),
        ),
    ),
    "rate_penetration": (
        (
            "rate_penetration",
            COMBAT_RATE_PENETRATION,
            ModifierLayer.GLOBAL_FLAT,
            _ranges((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.13, 0.01)),
        ),
    ),
    "healing": (
        (
            "healing",
            COMBAT_HEALING_RATE,
            ModifierLayer.GLOBAL_FLAT,
            _ranges((0.03, 0.06, 0.01), (0.07, 0.11, 0.01), (0.12, 0.18, 0.01)),
        ),
    ),
    "healing_received": (
        (
            "healing_received",
            COMBAT_HEALING_RECEIVED,
            ModifierLayer.GLOBAL_FLAT,
            _ranges((0.03, 0.06, 0.01), (0.07, 0.11, 0.01), (0.12, 0.18, 0.01)),
        ),
    ),
    "control_chance": (
        (
            "control_chance",
            COMBAT_CONTROL_CHANCE,
            ModifierLayer.GLOBAL_FLAT,
            _ranges((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.13, 0.01)),
        ),
    ),
    "control_resistance": (
        (
            "control_resistance",
            COMBAT_CONTROL_RESISTANCE,
            ModifierLayer.GLOBAL_FLAT,
            _ranges((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.13, 0.01)),
        ),
    ),
    "tenacity": (
        (
            "tenacity",
            COMBAT_TENACITY,
            ModifierLayer.GLOBAL_FLAT,
            _ranges((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.13, 0.01)),
        ),
    ),
    "vital_guard": (
        ("health", HEALTH_MAXIMUM, ModifierLayer.LOCAL_FLAT, _ranges((12, 24, 2), (28, 48, 2), (55, 85, 5))),
        ("defense", COMBAT_DEFENSE, ModifierLayer.LOCAL_FLAT, _ranges((2, 4, 1), (5, 8, 1), (9, 13, 1))),
    ),
    "spirit_step": (
        ("spirit", SPIRIT_MAXIMUM, ModifierLayer.LOCAL_FLAT, _ranges((8, 16, 2), (18, 30, 2), (35, 55, 5))),
        ("speed", COMBAT_SPEED, ModifierLayer.LOCAL_FLAT, _ranges((1, 3, 1), (4, 6, 1), (7, 10, 1))),
    ),
    "keen_edge": (
        ("attack", COMBAT_ATTACK, ModifierLayer.LOCAL_FLAT, _ranges((1, 3, 1), (4, 6, 1), (7, 10, 1))),
        (
            "accuracy",
            COMBAT_ACCURACY,
            ModifierLayer.GLOBAL_FLAT,
            _ranges((0.01, 0.03, 0.01), (0.04, 0.06, 0.01), (0.07, 0.10, 0.01)),
        ),
    ),
    "mystic_armor": (
        ("defense", COMBAT_DEFENSE, ModifierLayer.LOCAL_FLAT, _ranges((2, 4, 1), (5, 8, 1), (9, 13, 1))),
        (
            "tenacity",
            COMBAT_TENACITY,
            ModifierLayer.GLOBAL_FLAT,
            _ranges((0.01, 0.03, 0.01), (0.04, 0.06, 0.01), (0.07, 0.10, 0.01)),
        ),
    ),
}


def _numeric_property(key: str) -> PropertyDefinition:
    specs = NUMERIC_PROPERTY_SPECS[key]
    tiers = []
    for tier_index in range(3):
        parameters = tuple(
            PropertyParameterDefinition(
                f"parameter.equipment.{key}.{suffix}",
                attribute_id,
                layer,
                ranges[tier_index][0],
                ranges[tier_index][1],
                ranges[tier_index][2],
            )
            for suffix, attribute_id, layer, ranges in specs
        )
        tiers.append(
            PropertyTierDefinition(
                tier_index + 1,
                (60, 30, 10)[tier_index],
                parameters=parameters,
            )
        )
    blueprint = next(value for value in EQUIPMENT_PROPERTY_BLUEPRINTS if value.key == key)
    return PropertyDefinition(
        equipment_property_id(key),
        10,
        tuple(tiers),
        tags=TagSet.of(
            f"equipment.property.{key}",
            f"equipment.category.{blueprint.category}",
        ),
    )


def _mechanic_property(
    key: str,
) -> tuple[
    PropertyDefinition,
    tuple[EffectDefinition, ...],
    tuple[TriggerDefinition, ...],
    tuple[ReferenceValuationDefinition, ...],
]:
    mechanism = OFFICIAL_EQUIPMENT_MECHANICS.require(key)
    effects = []
    triggers = []
    valuations = []
    tiers = []
    for tier in range(1, 4):
        compiled = mechanism.compile(tier)
        effects.extend(compiled.effects)
        triggers.extend(compiled.triggers)
        trigger_id = equipment_trigger_id(key, tier)
        tiers.append(
            PropertyTierDefinition(
                tier,
                (60, 30, 10)[tier - 1],
                ContributionSpec(triggers=frozenset({trigger_id})),
            )
        )
        valuations.append(
            ReferenceValuationDefinition(
                ReferenceValueKind.TRIGGER,
                trigger_id,
                mechanism.base_value.scaled((0.65, 1.0, 1.45)[tier - 1]),
            )
        )
    blueprint = next(value for value in EQUIPMENT_PROPERTY_BLUEPRINTS if value.key == key)
    definition = PropertyDefinition(
        equipment_property_id(key),
        8,
        tuple(tiers),
        tags=TagSet.of(
            f"equipment.property.{key}",
            f"equipment.category.{blueprint.category}",
        ),
        blocked_selected_tags=TagSet.of(*(f"equipment.property.{value}" for value in mechanism.blocked_property_keys)),
    )
    return definition, tuple(effects), tuple(triggers), tuple(valuations)


def build_equipment_property_content() -> EquipmentPropertyContent:
    properties = []
    effects: dict[str, EffectDefinition] = {}
    triggers: dict[str, TriggerDefinition] = {}
    valuations = []
    for blueprint in EQUIPMENT_PROPERTY_BLUEPRINTS:
        if blueprint.key in OFFICIAL_EQUIPMENT_MECHANICS.definitions:
            definition, generated_effects, generated_triggers, generated_values = _mechanic_property(blueprint.key)
            for effect in generated_effects:
                if effect.id in effects and effects[effect.id] != effect:
                    raise ValueError(f"装备 Effect 定义冲突：{effect.id}")
                effects[effect.id] = effect
            for trigger in generated_triggers:
                if trigger.id in triggers and triggers[trigger.id] != trigger:
                    raise ValueError(f"装备 Trigger 定义冲突：{trigger.id}")
                triggers[trigger.id] = trigger
            valuations.extend(generated_values)
        else:
            definition = _numeric_property(blueprint.key)
        properties.append(definition)
    profile = GenerationProfileDefinition(
        EQUIPMENT_GENERATION_PROFILE_ID,
        ItemizationKind.EQUIPMENT,
        frozenset(value.id for value in properties),
        2,
        5,
        EQUIPMENT_QUALITY_BANDS,
        enforce_compatibility=True,
        maximum_attempts=16,
    )
    return EquipmentPropertyContent(
        tuple(effects.values()),
        tuple(triggers.values()),
        tuple(properties),
        (profile,),
        tuple(valuations),
        frozenset(value.id for value in properties),
    )


EQUIPMENT_PROPERTY_CONTENT = build_equipment_property_content()


__all__ = [
    "EQUIPMENT_GENERATION_PROFILE_ID",
    "EQUIPMENT_SET_MARK_CHANCE",
    "EQUIPMENT_PROPERTY_CONTENT",
    "EQUIPMENT_QUALITY_BANDS",
    "EquipmentPropertyContent",
    "build_equipment_property_content",
    "equipment_property_id",
    "equipment_trigger_id",
]
