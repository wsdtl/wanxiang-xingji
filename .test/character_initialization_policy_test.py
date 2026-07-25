"""具体游戏的人物初始值与固定等级成长策略测试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay import RuleContext, Ruleset, SeededRandomSource  # noqa: E402
from game.core.gameplay.character import (  # noqa: E402
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    COMBAT_SPEED,
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    SPIRIT_MAXIMUM,
    CharacterCatalog,
    CharacterEngine,
    CharacterTemplateDefinition,
    CharacterTransaction,
    GrantExperience,
    ProgressionDefinition,
)
from game.content.catalog.character import (  # noqa: E402
    CHARACTER_LEVEL_EXPERIENCE_REQUIREMENTS,
    CHARACTER_MAXIMUM_LEVEL,
    INITIAL_CORE_ATTRIBUTES,
    LEVEL_CORE_ATTRIBUTE_DELTAS,
    character_level_milestones,
)


TIME = datetime(2026, 7, 14, 22, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
    assert CHARACTER_MAXIMUM_LEVEL == len(CHARACTER_LEVEL_EXPERIENCE_REQUIREMENTS) + 1
    assert CHARACTER_MAXIMUM_LEVEL == 100
    assert dict(INITIAL_CORE_ATTRIBUTES) == {
        HEALTH_MAXIMUM: 100.0,
        SPIRIT_MAXIMUM: 100.0,
        COMBAT_ATTACK: 10.0,
        COMBAT_DEFENSE: 0.0,
        COMBAT_SPEED: 100.0,
    }
    assert dict(LEVEL_CORE_ATTRIBUTE_DELTAS) == {
        HEALTH_MAXIMUM: 10.0,
        COMBAT_ATTACK: 1.0,
    }

    catalog = CharacterCatalog()
    catalog.progressions.register(
        ProgressionDefinition(
            "progression.character_level",
            experience_requirements=(10, 10),
            milestones=character_level_milestones(3),
        )
    )
    catalog.templates.register(
        CharacterTemplateDefinition(
            "character_template.standard",
            INITIAL_CORE_ATTRIBUTES,
            progression_ids=frozenset({"progression.character_level"}),
        )
    )
    catalog.finalize()
    state = catalog.create_character(
        character_id="character-a",
        account_id="account-a",
        name="测试角色",
        template_id="character_template.standard",
        created_at=TIME,
    )
    # 角色先损失 30 点血气，再连续升两级。
    state = replace(
        state,
        resources={HEALTH_CURRENT: 70.0, SPIRIT_CURRENT: 100.0},
    )
    outcome = CharacterEngine(catalog).execute(
        CharacterTransaction(
            "character-growth",
            "account-a",
            state.revision,
            "character.level_growth",
            (
                GrantExperience(
                    "progression.character_level",
                    20,
                    "source.test",
                    "growth-test",
                ),
            ),
        ),
        state=state,
        context=RuleContext(
            trace_id="character-growth",
            rule_version="rules.v1",
            ruleset=Ruleset("ruleset.standard"),
            logical_time=TIME,
            random=SeededRandomSource(14),
        ),
    )
    assert outcome.ok and outcome.value, outcome.failure
    grown = outcome.value.state
    assert grown.progressions["progression.character_level"].level == 3
    assert grown.core_attributes[HEALTH_MAXIMUM] == 120
    assert grown.core_attributes[COMBAT_ATTACK] == 12
    assert grown.core_attributes[SPIRIT_MAXIMUM] == 100
    assert grown.core_attributes[COMBAT_DEFENSE] == 0
    assert grown.core_attributes[COMBAT_SPEED] == 100
    assert grown.resources[HEALTH_CURRENT] == 90
    assert grown.resources[SPIRIT_CURRENT] == 100
    assert 120 - 90 == 30
    print("character initialization policy test: OK")


if __name__ == "__main__":
    main()
