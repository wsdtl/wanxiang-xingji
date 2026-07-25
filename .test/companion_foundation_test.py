"""伙伴内容、随机生成、名册、配装独占和战斗投影测试。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.content import (  # noqa: E402
    COMPANION_CATALOG,
    COMPANION_EXPERIENCE_REQUIREMENTS,
    CULTIVATION_SKIN_ID,
    MAGIC_WORLD_ID,
    TAIXUAN_WORLD_ID,
    LOADOUT_PRESET_IDS,
    build_official_content,
)
from game.rules.companion import (  # noqa: E402
    COMPANION_APTITUDE_IDS,
    CompanionCombatProjector,
    CompanionEngine,
    CompanionKind,
    CompanionGrowthEngine,
    CompanionRosterState,
    CompanionRuleError,
    CompanionSanctuaryStatus,
)
from game.core.gameplay import SeededRandomSource, TagSet  # noqa: E402


NOW = datetime(2026, 7, 20, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
    content = build_official_content(CULTIVATION_SKIN_ID)
    engine = CompanionEngine(COMPANION_CATALOG)
    exploration_location_ids = {
        value.location_id for value in content.exploration_regions.definitions()
    }
    for person in COMPANION_CATALOG.people:
        binding = content.worlds.require_binding_for_display(
            person.origin_world_id,
            person.location_id,
        )
        assert binding.function_id == "location.function.companion_person"
        assert person.location_id not in exploration_location_ids
    roster = CompanionRosterState("character-a")
    first = engine.open_sanctuary(
        roster,
        None,
        session_id="sanctuary-a",
        world_id=TAIXUAN_WORLD_ID,
        character_level=37,
        logical_time=NOW,
        random=SeededRandomSource("sanctuary-a"),
    )
    replay = engine.open_sanctuary(
        roster,
        None,
        session_id="sanctuary-a",
        world_id=TAIXUAN_WORLD_ID,
        character_level=37,
        logical_time=NOW,
        random=SeededRandomSource("sanctuary-a"),
    )
    assert first == replay
    assert len(first.traces) == 3
    assert len({value.definition_id for value in first.traces}) == 3
    assert all(value.battle_level == 37 for value in first.traces)
    for trace in first.traces:
        assert set(trace.aptitudes) == set(COMPANION_APTITUDE_IDS)
        assert sum(trace.aptitudes.values()) == COMPANION_CATALOG.balance.aptitude_budgets[
            trace.quality_id
        ]

    selected = engine.select_trace(first, 2, logical_time=NOW)
    assert selected.status is CompanionSanctuaryStatus.TRACKING
    assert engine.select_trace(selected, 2, logical_time=NOW) == selected
    _fails(
        "companion.trace_locked",
        lambda: engine.select_trace(selected, 1, logical_time=NOW),
    )

    trace = selected.selected_trace()
    assert trace is not None
    projection = CompanionCombatProjector(
        content.catalog,
        content.companions,
    ).project(
        trace,
        entity_id="trace-target",
        context_tags=TagSet.of("scene.companion_sanctuary"),
    )
    assert projection.entity.id == "trace-target"
    assert projection.entity.tags.has("entity.companion")
    assert "ability.basic_attack" in projection.entity.abilities
    assert len(projection.ai_rules) >= 3

    next_roster, captured, companion = engine.capture(
        roster,
        selected,
        logical_time=NOW,
    )
    assert companion.reference == "C1"
    assert captured.status is CompanionSanctuaryStatus.CAPTURED
    assert next_roster.by_reference("c1") == companion
    assert companion.definition_id in next_roster.captured_definition_ids
    assert companion.level == 1 and companion.experience == 0
    companion_projector = CompanionCombatProjector(
        content.catalog,
        content.companions,
    )
    companion_projection = companion_projector.project(companion)
    assert companion_projection.entity.tags.has(
        f"companion.origin.{companion.origin_world_id}"
    )
    try:
        companion_projector.project(
            replace(companion, origin_world_id=MAGIC_WORLD_ID)
        )
    except ValueError as exc:
        assert str(exc) == "伙伴实例来源世界与内容定义不一致"
    else:
        raise AssertionError("来源世界损坏的伙伴实例不应进入战斗投影")
    assert len(COMPANION_EXPERIENCE_REQUIREMENTS) == 99
    assert COMPANION_EXPERIENCE_REQUIREMENTS[0] == 83
    assert COMPANION_EXPERIENCE_REQUIREMENTS[9] == 380
    assert COMPANION_EXPERIENCE_REQUIREMENTS[49] == 7_580
    assert COMPANION_EXPERIENCE_REQUIREMENTS[98] == 29_483
    growth_engine = CompanionGrowthEngine(COMPANION_CATALOG)
    next_roster, growth = growth_engine.grant_experience(
        next_roster,
        companion.id,
        30_000,
        character_level=37,
    )
    companion = next_roster.instances[companion.id]
    assert growth.accepted == 30_000 and growth.level_after > 1
    assert companion.total_experience == 30_000

    bound = engine.bind(next_roster, companion.id, LOADOUT_PRESET_IDS[0])
    assert bound.companion_for_preset(LOADOUT_PRESET_IDS[0]) == companion
    _fails(
        "companion.bound_elsewhere",
        lambda: engine.bind(bound, companion.id, LOADOUT_PRESET_IDS[1]),
    )
    transferred = engine.bind(
        bound,
        companion.id,
        LOADOUT_PRESET_IDS[1],
        allow_transfer=True,
    )
    assert transferred.companion_for_preset(LOADOUT_PRESET_IDS[0]) is None
    assert transferred.companion_for_preset(LOADOUT_PRESET_IDS[1]) == companion
    released = engine.farewell(transferred, companion.id)
    assert not released.instances
    assert not released.bindings
    assert companion.definition_id in released.captured_definition_ids

    person = COMPANION_CATALOG.people_for_world(TAIXUAN_WORLD_ID)[0]
    bonded, before, after = engine.give_gift(
        released,
        person.id,
        person.bond_required,
        logical_time=NOW,
    )
    assert before == 0 and after == person.bond_required
    joined, person_instance, restored = engine.join_person(
        bonded,
        person.id,
        37,
        logical_time=NOW,
    )
    assert not restored
    assert person_instance.kind is CompanionKind.PERSON
    assert person_instance.level == 1
    assert person_instance.aptitudes == person.aptitudes
    person_projection = CompanionCombatProjector(
        content.catalog,
        content.companions,
    ).project(person_instance)
    assert person_projection.entity.tags.has("entity.companion.person")
    assert len(person_projection.ai_rules) >= 3
    _fails(
        "companion.person_joined",
        lambda: engine.join_person(joined, person.id, 37, logical_time=NOW),
    )
    departed = engine.farewell(joined, person_instance.id)
    assert person.id in departed.departed_people
    rejoined, restored_instance, restored = engine.join_person(
        departed,
        person.id,
        99,
        logical_time=NOW,
    )
    assert restored
    assert restored_instance == person_instance
    assert not rejoined.departed_people

    full_instances = {
        (clone := replace(
            companion,
            id=f"character-a:companion:{index}",
            reference=f"C{index}",
        )).id: clone
        for index in range(1, 31)
    }
    full = CompanionRosterState(
        "character-a",
        full_instances,
        next_sequence=31,
    )
    _fails(
        "companion.roster_full",
        lambda: engine.open_sanctuary(
            full,
            captured,
            session_id="sanctuary-full",
            world_id=TAIXUAN_WORLD_ID,
            character_level=37,
            logical_time=NOW,
            random=SeededRandomSource("sanctuary-full"),
        ),
    )

    expired = engine.expire(first, logical_time=NOW + timedelta(days=2))
    assert expired.status is CompanionSanctuaryStatus.EXPIRED
    print("companion foundation tests passed")


def _fails(code: str, operation) -> None:
    try:
        operation()
    except CompanionRuleError as exc:
        assert exc.code == code
    else:
        raise AssertionError(f"expected companion failure: {code}")


if __name__ == "__main__":
    main()
