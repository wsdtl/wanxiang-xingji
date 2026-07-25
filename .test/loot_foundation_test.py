"""版本化掉落、空结果、批量抽取、修正和保底测试。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay import RuleContext, Ruleset, SeededRandomSource  # noqa: E402
from game.core.gameplay.loot import (  # noqa: E402
    LOOT_CHANCE_SCALE,
    LOOT_FOUNDATION_VERSION,
    LootCatalog,
    LootEngine,
    LootEntry,
    LootGroup,
    LootGroupMode,
    LootPityDefinition,
    LootRollCommand,
    LootState,
    LootTableDefinition,
)
from game.core.gameplay.tags import TagSet  # noqa: E402


TIME = datetime(2026, 7, 13, 23, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
    assert LOOT_FOUNDATION_VERSION == "loot.foundation.v1"
    engine = _engine()
    _assert_forced_pity(engine)
    _assert_empty_independent_and_guaranteed_groups(engine)
    _assert_modifiers_and_failure_rollback(engine)
    _assert_deterministic_batch(engine)
    _assert_multi_draw_audit_coordinates()
    print("loot foundation tests passed")


def _engine() -> LootEngine:
    catalog = LootCatalog()
    catalog.register(
        LootTableDefinition(
            "loot_table.exploration",
            3,
            (
                LootGroup(
                    "loot_group.primary",
                    LootGroupMode.WEIGHTED_ONE,
                    (
                        LootEntry("loot_entry.empty", None, weight=8),
                        LootEntry(
                            "loot_entry.herb",
                            "award.material_herb",
                            weight=4,
                            minimum_quantity=1,
                            maximum_quantity=3,
                        ),
                        LootEntry(
                            "loot_entry.rare",
                            "award.rare_relic",
                            weight=1,
                        ),
                    ),
                ),
                LootGroup(
                    "loot_group.independent",
                    LootGroupMode.INDEPENDENT,
                    (
                        LootEntry(
                            "loot_entry.certain",
                            "award.fixed_token",
                            chance=LOOT_CHANCE_SCALE,
                        ),
                        LootEntry("loot_entry.never", "award.never", chance=0),
                    ),
                ),
                LootGroup(
                    "loot_group.all",
                    LootGroupMode.ALL,
                    (
                        LootEntry(
                            "loot_entry.tagged",
                            "award.tag_bonus",
                            required_tags=TagSet.of("scene.blessed"),
                        ),
                    ),
                ),
            ),
            LootPityDefinition(
                "loot_group.primary",
                3,
                frozenset({"loot_entry.rare"}),
                frozenset({"loot_entry.rare"}),
            ),
        )
    )
    catalog.finalize()
    return LootEngine(catalog)


def _context(seed: int | str, *, blessed: bool = True) -> RuleContext:
    return RuleContext(
        f"loot-{seed}",
        "rules.loot_v1",
        Ruleset("ruleset.loot_test"),
        TIME,
        SeededRandomSource(seed),
        TagSet.of("scene.blessed") if blessed else TagSet(),
    )


def _assert_forced_pity(engine: LootEngine) -> None:
    state = LootState("account-a", {"loot_table.exploration": 2})
    command = LootRollCommand("loot-forced", "account-a", "loot_table.exploration", 0)
    execution = engine.roll(command, state=state, context=_context(10)).unwrap()
    assert execution.receipt.table_version == 3
    assert execution.receipt.pity_before == 2
    assert execution.receipt.pity_after == 0
    assert any(award.entry_id == "loot_entry.rare" for award in execution.receipt.awards)
    assert any(decision.forced for decision in execution.receipt.decisions)
    assert execution.state.revision == 1


def _assert_empty_independent_and_guaranteed_groups(engine: LootEngine) -> None:
    state = LootState("account-a")
    command = LootRollCommand("loot-groups", "account-a", "loot_table.exploration", 0)
    execution = engine.roll(command, state=state, context=_context(20)).unwrap()
    award_ids = {award.award_id for award in execution.receipt.awards}
    assert "award.fixed_token" in award_ids
    assert "award.never" not in award_ids
    assert "award.tag_bonus" in award_ids

    without_tag = engine.roll(
        LootRollCommand("loot-no-tag", "account-a", "loot_table.exploration", 0),
        state=state,
        context=_context(21, blessed=False),
    )
    assert without_tag.failure and without_tag.failure.code == "loot.no_eligible_entries"


def _assert_modifiers_and_failure_rollback(engine: LootEngine) -> None:
    state = LootState("account-a", {"loot_table.exploration": 2})
    command = LootRollCommand(
        "loot-disabled-pity",
        "account-a",
        "loot_table.exploration",
        0,
        modifier_basis_points={"loot_entry.rare": 0},
    )
    context = _context(30)
    checkpoint = context.random.checkpoint()
    outcome = engine.roll(command, state=state, context=context)
    assert outcome.failure and outcome.failure.code == "loot.no_positive_weight"
    assert context.random.checkpoint() == checkpoint

    stale = engine.roll(
        LootRollCommand("loot-stale", "account-a", "loot_table.exploration", 1),
        state=state,
        context=_context(31),
    )
    assert stale.failure and stale.failure.code == "loot.revision_conflict"


def _assert_deterministic_batch(engine: LootEngine) -> None:
    state = LootState("account-a")
    command = LootRollCommand(
        "loot-batch",
        "account-a",
        "loot_table.exploration",
        0,
        rolls=8,
    )
    first = engine.roll(command, state=state, context=_context("same-seed")).unwrap()
    second = engine.roll(command, state=state, context=_context("same-seed")).unwrap()
    assert first.receipt == second.receipt
    assert first.state == second.state
    assert all(1 <= award.quantity <= 3 for award in first.receipt.awards)


def _assert_multi_draw_audit_coordinates() -> None:
    catalog = LootCatalog()
    catalog.register(
        LootTableDefinition(
            "loot_table.audit",
            1,
            (
                LootGroup(
                    "loot_group.empty_all",
                    LootGroupMode.ALL,
                    (LootEntry("loot_entry.empty_all", None),),
                    draws=3,
                ),
                LootGroup(
                    "loot_group.miss",
                    LootGroupMode.INDEPENDENT,
                    (LootEntry("loot_entry.miss", "award.never", chance=0),),
                    draws=2,
                ),
            ),
        )
    )
    catalog.finalize()
    execution = LootEngine(catalog).roll(
        LootRollCommand("loot-audit", "account-a", "loot_table.audit", 0),
        state=LootState("account-a"),
        context=_context("audit"),
    ).unwrap()
    assert execution.receipt.empty_count == 5
    assert [decision.draw_index for decision in execution.receipt.decisions] == [0, 1, 2, 0, 1]
    misses = execution.receipt.decisions[-2:]
    assert all(decision.entry_id == "loot_entry.miss" and not decision.hit for decision in misses)


if __name__ == "__main__":
    main()
