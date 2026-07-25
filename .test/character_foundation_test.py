"""角色成长、五项核心值和任意来源贡献投影测试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay import (  # noqa: E402
    AttributeDefinition,
    AttributeResolver,
    ModifierLayer,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    TagSet,
)
from game.core.gameplay.character import (  # noqa: E402
    CHARACTER_FOUNDATION_VERSION,
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    COMBAT_SPEED,
    CORE_ATTRIBUTE_IDS,
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    SPIRIT_MAXIMUM,
    AttributeGrant,
    ChangeCharacterResource,
    CharacterCatalog,
    CharacterContribution,
    CharacterEngine,
    CharacterFeatureDefinition,
    CharacterProjector,
    CharacterStatus,
    CharacterTemplateDefinition,
    CharacterTransaction,
    ContributionSpec,
    GrantCoreAttribute,
    GrantExperience,
    ProgressionDefinition,
    ProgressionMilestone,
    RetireCharacter,
    UnlockFeature,
    UnlockProgression,
    UnlockProgressionCap,
    core_attribute_definitions,
    persistent_resource_definitions,
)


TIME = datetime(2026, 7, 12, 21, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
CRITICAL_CHANCE = "combat.critical.chance"


def main() -> None:
    _assert_template_and_catalog_boundaries()
    _assert_multilevel_progression()
    _assert_progression_level_caps()
    _assert_atomic_failure_and_revision_guard()
    _assert_core_and_resource_boundaries()
    _assert_open_contribution_projection()
    _assert_retirement()
    print("character foundation tests passed")


def _context(seed: int = 17) -> RuleContext:
    return RuleContext(
        trace_id=f"character-test-{seed}",
        rule_version="rules.v1",
        ruleset=Ruleset("ruleset.standard"),
        logical_time=TIME,
        random=SeededRandomSource(seed),
    )


def _catalog() -> CharacterCatalog:
    catalog = CharacterCatalog()
    catalog.features.register(
        CharacterFeatureDefinition(
            "feature.iron_body",
            ContributionSpec(
                attributes=(
                    AttributeGrant(
                        HEALTH_MAXIMUM,
                        ModifierLayer.LOCAL_FLAT,
                        20,
                    ),
                ),
                tags=TagSet.of("character.physique.iron_body"),
            ),
        )
    )
    catalog.features.register(
        CharacterFeatureDefinition(
            "feature.awakened_sight",
            ContributionSpec(
                attributes=(
                    AttributeGrant(
                        CRITICAL_CHANCE,
                        ModifierLayer.GLOBAL_FLAT,
                        0.1,
                    ),
                ),
            ),
        )
    )
    catalog.progressions.register(
        ProgressionDefinition(
            "progression.character_level",
            experience_requirements=(100, 200),
            milestones={
                2: ProgressionMilestone(
                    2,
                    {COMBAT_ATTACK: 5},
                ),
                3: ProgressionMilestone(
                    3,
                    {HEALTH_MAXIMUM: 20},
                    frozenset({"feature.awakened_sight"}),
                ),
            },
        )
    )
    catalog.progressions.register(
        ProgressionDefinition(
            "progression.weapon_mastery",
            experience_requirements=(50,),
        )
    )
    catalog.templates.register(
        CharacterTemplateDefinition(
            "character_template.standard",
            {
                HEALTH_MAXIMUM: 100,
                SPIRIT_MAXIMUM: 50,
                COMBAT_ATTACK: 10,
                COMBAT_DEFENSE: 20,
                COMBAT_SPEED: 5,
            },
            progression_ids=frozenset({"progression.character_level"}),
            feature_ids=frozenset({"feature.iron_body"}),
            tags=TagSet.of("character.origin.standard"),
        )
    )
    catalog.finalize()
    return catalog


def _character(catalog: CharacterCatalog):
    character = catalog.create_character(
        character_id="character-a",
        account_id="account-a",
        name="测试角色",
        template_id="character_template.standard",
        created_at=TIME,
    )
    assert character.name == "测试角色"
    return _projector(catalog).initialize_new_character(character)


def _transaction(state, transaction_id: str, *operations):
    return CharacterTransaction(
        transaction_id,
        "account-a",
        state.revision,
        "character.test_operation",
        tuple(operations),
    )


def _assert_template_and_catalog_boundaries() -> None:
    assert CHARACTER_FOUNDATION_VERSION == "character.foundation.v5"
    assert len(CORE_ATTRIBUTE_IDS) == 5
    try:
        CharacterTemplateDefinition(
            "character_template.invalid",
            {
                HEALTH_MAXIMUM: 100,
                SPIRIT_MAXIMUM: 50,
                COMBAT_ATTACK: 10,
                COMBAT_DEFENSE: 20,
            },
        )
        raise AssertionError("角色模板缺少速度时必须失败")
    except ValueError:
        pass

    catalog = _catalog()
    try:
        catalog.features.register(CharacterFeatureDefinition("feature.too_late"))
        raise AssertionError("角色目录冻结后不能增加内容")
    except RuntimeError:
        pass


def _assert_multilevel_progression() -> None:
    catalog = _catalog()
    state = _character(catalog)
    assert state.resources[HEALTH_CURRENT] == 120
    assert state.resources[SPIRIT_CURRENT] == 50
    engine = CharacterEngine(catalog)
    outcome = engine.execute(
        _transaction(
            state,
            "gain-350-exp",
            GrantExperience(
                "progression.character_level",
                350,
                "source.quest_reward",
                "quest-7",
            ),
        ),
        state=state,
        context=_context(),
    )
    assert outcome.ok and outcome.value, outcome.failure
    result = outcome.value
    progression = result.state.progressions["progression.character_level"]
    assert progression.level == 3
    assert progression.experience == 50
    assert progression.total_experience == 350
    assert result.state.core_attributes[COMBAT_ATTACK] == 15
    assert result.state.core_attributes[HEALTH_MAXIMUM] == 120
    assert result.state.resources[HEALTH_CURRENT] == 140
    assert "feature.awakened_sight" in result.state.features
    kinds = [event.kind for event in result.events]
    assert kinds.count("character.progression.advanced") == 2
    assert kinds.count("character.milestone.applied") == 2
    assert "character.feature.unlocked" in kinds
    assert all(event.trace_id == "character-test-17" for event in result.events)

    unlocked = engine.execute(
        _transaction(
            result.state,
            "unlock-weapon-mastery",
            UnlockProgression(
                "progression.weapon_mastery",
                "source.weapon_equipped",
                "weapon-9",
            ),
        ),
        state=result.state,
        context=_context(),
    ).unwrap()
    assert unlocked.state.progressions["progression.weapon_mastery"].level == 1
    assert unlocked.events[0].kind == "character.progression.unlocked"


def _assert_progression_level_caps() -> None:
    catalog = CharacterCatalog()
    catalog.progressions.register(
        ProgressionDefinition(
            "progression.gated",
            (100, 200),
            {
                2: ProgressionMilestone(2, {COMBAT_ATTACK: 1}),
                3: ProgressionMilestone(3, {HEALTH_MAXIMUM: 10}),
            },
            (2, 3),
        )
    )
    catalog.templates.register(
        CharacterTemplateDefinition(
            "character_template.gated",
            {
                HEALTH_MAXIMUM: 100,
                SPIRIT_MAXIMUM: 50,
                COMBAT_ATTACK: 10,
                COMBAT_DEFENSE: 0,
                COMBAT_SPEED: 100,
            },
            progression_ids=frozenset({"progression.gated"}),
        )
    )
    catalog.finalize()
    state = catalog.create_character(
        character_id="gated-character",
        account_id="account-a",
        name="关隘测试",
        template_id="character_template.gated",
        created_at=TIME,
    )
    assert state.progressions["progression.gated"].level_cap == 2
    engine = CharacterEngine(catalog)
    capped = engine.execute(
        _transaction(
            state,
            "gain-gated-exp",
            GrantExperience(
                "progression.gated",
                350,
                "source.test",
                "gated-exp",
            ),
        ),
        state=state,
        context=_context(),
    ).unwrap().state
    progression = capped.progressions["progression.gated"]
    assert (progression.level, progression.experience, progression.level_cap) == (2, 250, 2)
    unlocked = engine.execute(
        _transaction(
            capped,
            "unlock-gated-cap",
            UnlockProgressionCap(
                "progression.gated",
                "source.breakthrough",
                "token-1",
            ),
        ),
        state=capped,
        context=_context(),
    ).unwrap()
    progression = unlocked.state.progressions["progression.gated"]
    assert (progression.level, progression.experience, progression.level_cap) == (3, 50, 3)
    assert unlocked.state.core_attributes[HEALTH_MAXIMUM] == 110
    assert [value.kind for value in unlocked.events].count(
        "character.progression.cap_unlocked"
    ) == 1

    maximum = engine.execute(
        _transaction(
            unlocked.state,
            "unlock-gated-maximum",
            UnlockProgressionCap(
                "progression.gated",
                "source.breakthrough",
                "token-2",
            ),
        ),
        state=unlocked.state,
        context=_context(),
    )
    assert maximum.failure and maximum.failure.code == "character.progression_at_maximum_cap"


def _assert_atomic_failure_and_revision_guard() -> None:
    catalog = _catalog()
    state = _character(catalog)
    engine = CharacterEngine(catalog)
    context = _context(31)
    checkpoint = context.random.checkpoint()
    failed = engine.execute(
        _transaction(
            state,
            "partial-growth-must-rollback",
            GrantCoreAttribute(
                COMBAT_ATTACK,
                10,
                "source.admin_adjustment",
                "adjustment-1",
            ),
            UnlockFeature(
                "feature.unknown",
                "source.admin_adjustment",
                "adjustment-1",
            ),
        ),
        state=state,
        context=context,
    )
    assert failed.failure and failed.failure.code == "character.feature_unknown"
    assert state.core_attributes[COMBAT_ATTACK] == 10
    assert state.revision == 0
    assert context.random.checkpoint() == checkpoint

    stale = engine.execute(
        CharacterTransaction(
            "stale-growth",
            "account-a",
            expected_revision=9,
            reason="character.test_operation",
            operations=(
                GrantExperience(
                    "progression.character_level",
                    1,
                    "source.quest_reward",
                    "quest-stale",
                ),
            ),
        ),
        state=state,
        context=_context(),
    )
    assert stale.failure and stale.failure.code == "character.revision_conflict"


def _assert_core_and_resource_boundaries() -> None:
    catalog = _catalog()
    state = _character(catalog)
    engine = CharacterEngine(catalog)
    changed = engine.execute(
        _transaction(
            state,
            "negative-defense-is-valid",
            GrantCoreAttribute(
                COMBAT_DEFENSE,
                -50,
                "source.permanent_choice",
                "choice-risky",
            ),
            ChangeCharacterResource(
                SPIRIT_CURRENT,
                -20,
                "source.ability_cost",
                "ability-meditation",
            ),
        ),
        state=state,
        context=_context(),
    )
    assert changed.ok and changed.value
    assert changed.value.state.core_attributes[COMBAT_DEFENSE] == -30
    assert changed.value.state.resources[SPIRIT_CURRENT] == 30

    non_core = engine.execute(
        _transaction(
            state,
            "reject-non-core",
            GrantCoreAttribute(
                CRITICAL_CHANCE,
                0.2,
                "source.permanent_choice",
                "choice-invalid",
            ),
        ),
        state=state,
        context=_context(),
    )
    assert non_core.failure and non_core.failure.code == "character.not_core_attribute"

    insufficient = engine.execute(
        _transaction(
            state,
            "reject-negative-resource",
            ChangeCharacterResource(
                HEALTH_CURRENT,
                -121,
                "source.damage_settlement",
                "battle-1",
            ),
        ),
        state=state,
        context=_context(),
    )
    assert insufficient.failure
    assert insufficient.failure.code == "character.resource_insufficient"


def _projector(catalog: CharacterCatalog) -> CharacterProjector:
    attributes = core_attribute_definitions()
    attributes[CRITICAL_CHANCE] = AttributeDefinition(CRITICAL_CHANCE, default=0)
    return CharacterProjector(
        catalog,
        AttributeResolver(attributes),
        persistent_resource_definitions(),
    )


def _assert_open_contribution_projection() -> None:
    catalog = _catalog()
    state = _character(catalog)
    engine = CharacterEngine(catalog)
    advanced = engine.execute(
        _transaction(
            state,
            "advance-before-projection",
            GrantExperience(
                "progression.character_level",
                350,
                "source.quest_reward",
                "quest-8",
            ),
        ),
        state=state,
        context=_context(),
    ).unwrap().state
    # 持久资源可以来自上一场结算；投影时按全部贡献后的最终上限夹紧。
    advanced = replace(
        advanced,
        resources={HEALTH_CURRENT: 999, SPIRIT_CURRENT: 50},
    )
    weapon = CharacterContribution(
        "contribution.weapon_main_hand",
        "source.equipment_instance",
        "weapon-instance-9",
        ContributionSpec(
            attributes=(
                AttributeGrant(COMBAT_ATTACK, ModifierLayer.LOCAL_FLAT, 30),
                AttributeGrant(CRITICAL_CHANCE, ModifierLayer.GLOBAL_FLAT, 0.25),
            ),
            tags=TagSet.of("equipment.weapon.fast"),
        ),
    )
    projection = _projector(catalog).project(advanced, contributions=(weapon,))
    snapshot = projection.entity.snapshot(_projector(catalog).attributes)
    # 核心攻击 10 + 等级 5 + 武器 30。
    assert snapshot.value(COMBAT_ATTACK) == 45
    # 暴击不是角色固定字段，但永久特征和武器可按需贡献 0.1 + 0.25。
    assert CRITICAL_CHANCE not in advanced.core_attributes
    assert snapshot.value(CRITICAL_CHANCE) == 0.35
    # 核心血气 120 + 初始体质 20。
    assert snapshot.value(HEALTH_MAXIMUM) == 140
    assert projection.entity.resources[HEALTH_CURRENT] == 140
    assert projection.entity.tags.has("equipment.weapon")
    assert projection.entity.tags.has("character.physique")
    assert snapshot.breakdowns[COMBAT_ATTACK].local_flat == 30
    modifier = next(
        value
        for value in projection.entity.modifiers
        if value.attribute_id == COMBAT_ATTACK
    )
    assert modifier.source_id == "weapon-instance-9"

    unknown = CharacterContribution(
        "contribution.invalid",
        "source.test_invalid",
        "invalid-1",
        ContributionSpec(
            attributes=(
                AttributeGrant("combat.unregistered", ModifierLayer.LOCAL_FLAT, 1),
            ),
        ),
    )
    try:
        _projector(catalog).project(advanced, contributions=(unknown,))
        raise AssertionError("未登记属性不能偷偷进入角色投影")
    except KeyError:
        pass


def _assert_retirement() -> None:
    catalog = _catalog()
    state = _character(catalog)
    engine = CharacterEngine(catalog)
    retired = engine.execute(
        _transaction(
            state,
            "retire-character",
            RetireCharacter("source.owner_action", "retire-request-1"),
        ),
        state=state,
        context=_context(),
    ).unwrap().state
    assert retired.status is CharacterStatus.RETIRED
    blocked = engine.execute(
        _transaction(
            retired,
            "retired-cannot-grow",
            GrantExperience(
                "progression.character_level",
                10,
                "source.quest_reward",
                "quest-after-retire",
            ),
        ),
        state=retired,
        context=_context(),
    )
    assert blocked.failure and blocked.failure.code == "character.not_active"
    try:
        _projector(catalog).project(retired)
        raise AssertionError("退隐角色不能进入规则场景")
    except ValueError:
        pass


if __name__ == "__main__":
    main()
