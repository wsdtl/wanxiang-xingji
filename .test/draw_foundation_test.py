"""抽取池可信边界、批量抽取、保底与失败回滚测试。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay import (  # noqa: E402
    DRAW_FOUNDATION_VERSION,
    DrawCommand,
    DrawEngine,
    DrawGuaranteeEntry,
    DrawGuaranteeSlotDefinition,
    DrawInventoryCommand,
    DrawInventoryEngine,
    DrawPoolCatalog,
    DrawPoolDefinition,
    LootCatalog,
    LootEngine,
    LootEntry,
    LootGroup,
    LootGroupMode,
    LootPityDefinition,
    LootState,
    LootTableDefinition,
    InventoryEngine,
    InventoryState,
    ItemAssetKind,
    ItemCatalog,
    ItemContainer,
    ItemDefinition,
    ItemStack,
    ItemStorageComponent,
    ProvenanceLot,
    SourceReceipt,
    TagSet,
    register_item_storage_component,
    RuleContext,
    Ruleset,
    SeededRandomSource,
)
from game.core.persistence import gameplay_snapshot_codec  # noqa: E402


TIME = datetime(2026, 7, 19, 18, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
TABLE_ID = "loot_table.draw.special"
POOL_ID = "draw_pool.special"
TICKET_ID = "item.special.draw_ticket"
COMMON_ITEM_ID = "item.special.common"
RARE_ITEM_ID = "item.special.rare"
BREAKTHROUGH_ITEM_ID = "item.breakthrough.token"
GUARANTEE_SLOT_ID = "draw_guarantee.breakthrough"


def main() -> None:
    assert DRAW_FOUNDATION_VERSION == "draw.foundation.v2"
    pools, loot = _catalogs()
    engine = DrawEngine(pools, LootEngine(loot))
    _assert_batch_and_receipt(engine)
    _assert_pity_uses_shared_loot_state(engine)
    _assert_independent_guarantee_slot()
    _assert_failure_rolls_back_random(engine)
    _assert_catalog_rejects_untrusted_tables()
    _assert_inventory_execution(engine)
    _assert_codec_round_trip(engine)
    print("draw foundation tests passed")


def _catalogs() -> tuple[DrawPoolCatalog, LootCatalog]:
    loot = LootCatalog()
    loot.register(_table())
    loot.finalize()
    pools = DrawPoolCatalog()
    pools.register(
        DrawPoolDefinition(
            POOL_ID,
            3,
            TICKET_ID,
            TABLE_ID,
            frozenset({COMMON_ITEM_ID, RARE_ITEM_ID}),
        )
    )
    pools.finalize(loot_tables=loot)
    return pools, loot


def _table() -> LootTableDefinition:
    return LootTableDefinition(
        TABLE_ID,
        7,
        (
            LootGroup(
                "loot_group.draw.special",
                LootGroupMode.WEIGHTED_ONE,
                (
                    LootEntry("loot_entry.draw.common", COMMON_ITEM_ID, weight=9),
                    LootEntry("loot_entry.draw.rare", RARE_ITEM_ID, weight=1),
                ),
            ),
        ),
        LootPityDefinition(
            "loot_group.draw.special",
            5,
            frozenset({"loot_entry.draw.rare"}),
            frozenset({"loot_entry.draw.rare"}),
        ),
    )


def _context(seed: int | str) -> RuleContext:
    return RuleContext(
        f"draw:{seed}",
        DRAW_FOUNDATION_VERSION,
        Ruleset("ruleset.draw_test"),
        TIME,
        SeededRandomSource(seed),
    )


def _assert_batch_and_receipt(engine: DrawEngine) -> None:
    state = LootState("character-a")
    outcome = engine.draw(
        DrawCommand("draw:batch", "character-a", POOL_ID, 0, 10),
        state=state,
        context=_context("batch"),
    ).unwrap()
    assert outcome.loot_state.revision == 1
    assert outcome.receipt.pool_version == 3
    assert outcome.receipt.loot_receipt.table_version == 7
    assert outcome.receipt.ticket_item_id == TICKET_ID
    assert outcome.receipt.rolls == 10
    assert len(outcome.receipt.awards) == 10
    assert not outcome.receipt.loot_receipt.empty_count
    assert {award.award_id for award in outcome.receipt.awards} <= {
        COMMON_ITEM_ID,
        RARE_ITEM_ID,
    }


def _assert_pity_uses_shared_loot_state(engine: DrawEngine) -> None:
    state = LootState("character-a", {TABLE_ID: 4})
    outcome = engine.draw(
        DrawCommand("draw:pity", "character-a", POOL_ID, 0),
        state=state,
        context=_context("pity"),
    ).unwrap()
    assert outcome.receipt.awards[0].award_id == RARE_ITEM_ID
    assert outcome.receipt.loot_receipt.pity_before == 4
    assert outcome.receipt.loot_receipt.pity_after == 0
    assert outcome.receipt.loot_receipt.decisions[0].forced


def _assert_independent_guarantee_slot() -> None:
    table_id = "loot_table.draw.guarantee"
    pool_id = "draw_pool.guarantee"
    loot = LootCatalog()
    loot.register(
        LootTableDefinition(
            table_id,
            1,
            (
                LootGroup(
                    "loot_group.draw.guarantee",
                    LootGroupMode.WEIGHTED_ONE,
                    (LootEntry("loot_entry.draw.always_common", COMMON_ITEM_ID, weight=1),),
                ),
            ),
        )
    )
    loot.finalize()
    pools = DrawPoolCatalog()
    pools.register(
        DrawPoolDefinition(
            pool_id,
            1,
            TICKET_ID,
            table_id,
            frozenset({COMMON_ITEM_ID, BREAKTHROUGH_ITEM_ID}),
            (
                DrawGuaranteeSlotDefinition(
                    GUARANTEE_SLOT_ID,
                    3,
                    (
                        DrawGuaranteeEntry(
                            "draw_guarantee_entry.breakthrough",
                            BREAKTHROUGH_ITEM_ID,
                        ),
                    ),
                ),
            ),
        )
    )
    pools.finalize(loot_tables=loot)
    engine = DrawEngine(pools, LootEngine(loot))
    execution = engine.draw(
        DrawCommand("draw:guarantee", "character-a", pool_id, 0, 2),
        state=LootState("character-a", {GUARANTEE_SLOT_ID: 1}),
        context=_context("guarantee"),
    ).unwrap()
    assert [value.award_id for value in execution.receipt.awards] == [
        COMMON_ITEM_ID,
        COMMON_ITEM_ID,
        BREAKTHROUGH_ITEM_ID,
    ]
    assert execution.loot_state.pity_counters[GUARANTEE_SLOT_ID] == 0
    assert execution.receipt.guarantee_decisions[0].counter_after == 2
    assert execution.receipt.guarantee_decisions[1].forced
    assert execution.receipt.guarantee_decisions[1].counter_before == 2
    assert execution.events[-1].kind == "draw.guarantee_triggered"

    natural_table_id = "loot_table.draw.guarantee_natural"
    natural_pool_id = "draw_pool.guarantee_natural"
    natural_loot = LootCatalog()
    natural_loot.register(
        LootTableDefinition(
            natural_table_id,
            1,
            (
                LootGroup(
                    "loot_group.draw.guarantee_natural",
                    LootGroupMode.WEIGHTED_ONE,
                    (
                        LootEntry(
                            "loot_entry.draw.always_breakthrough",
                            BREAKTHROUGH_ITEM_ID,
                            weight=1,
                        ),
                    ),
                ),
            ),
        )
    )
    natural_loot.finalize()
    natural_pools = DrawPoolCatalog()
    natural_pools.register(
        DrawPoolDefinition(
            natural_pool_id,
            1,
            TICKET_ID,
            natural_table_id,
            frozenset({BREAKTHROUGH_ITEM_ID}),
            pools.require(pool_id).guarantee_slots,
        )
    )
    natural_pools.finalize(loot_tables=natural_loot)
    natural = DrawEngine(natural_pools, LootEngine(natural_loot)).draw(
        DrawCommand("draw:guarantee-natural", "character-a", natural_pool_id, 0),
        state=LootState("character-a", {GUARANTEE_SLOT_ID: 2}),
        context=_context("guarantee-natural"),
    ).unwrap()
    assert len(natural.receipt.awards) == 1
    assert natural.receipt.guarantee_decisions[0].naturally_satisfied
    assert not natural.receipt.guarantee_decisions[0].forced
    assert natural.loot_state.pity_counters[GUARANTEE_SLOT_ID] == 0


def _assert_failure_rolls_back_random(engine: DrawEngine) -> None:
    context = _context("stale")
    checkpoint = context.random.checkpoint()
    outcome = engine.draw(
        DrawCommand("draw:stale", "character-a", POOL_ID, 1),
        state=LootState("character-a"),
        context=context,
    )
    assert outcome.failure and outcome.failure.code == "draw.revision_conflict"
    assert context.random.checkpoint() == checkpoint


def _assert_catalog_rejects_untrusted_tables() -> None:
    try:
        DrawPoolDefinition(
            "draw_pool.self_loop",
            1,
            TICKET_ID,
            TABLE_ID,
            frozenset({TICKET_ID}),
        )
    except ValueError as exc:
        assert "不能把自己的抽取签作为奖励" in str(exc)
    else:
        raise AssertionError("抽取池不能形成抽取签自循环")
    for award_id, expected in (
        (None, "不能包含空奖项"),
        ("item.special.outside", "不在可信名录"),
    ):
        loot = LootCatalog()
        loot.register(
            LootTableDefinition(
                "loot_table.draw.invalid",
                1,
                (
                    LootGroup(
                        "loot_group.draw.invalid",
                        LootGroupMode.WEIGHTED_ONE,
                        (LootEntry("loot_entry.draw.invalid", award_id, weight=1),),
                    ),
                ),
            )
        )
        loot.finalize()
        pools = DrawPoolCatalog()
        pools.register(
            DrawPoolDefinition(
                "draw_pool.invalid",
                1,
                TICKET_ID,
                "loot_table.draw.invalid",
                frozenset({COMMON_ITEM_ID}),
            )
        )
        try:
            pools.finalize(loot_tables=loot)
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("不可信抽取表必须在启动期被拒绝")


def _assert_codec_round_trip(engine: DrawEngine) -> None:
    execution = engine.draw(
        DrawCommand("draw:codec", "character-a", POOL_ID, 0, 2),
        state=LootState("character-a"),
        context=_context("codec"),
    ).unwrap()
    codec = gameplay_snapshot_codec()
    payload = codec.dumps(execution)
    assert codec.loads(payload, type(execution)) == execution


def _assert_inventory_execution(engine: DrawEngine) -> None:
    catalog = ItemCatalog()
    register_item_storage_component(catalog.components)
    catalog.register(
        ItemDefinition(
            TICKET_ID,
            ItemAssetKind.STACK,
            TagSet.of("item.draw_ticket"),
            99,
            {"item_component.storage": ItemStorageComponent(1)},
        )
    )
    catalog.register(
        ItemDefinition(
            COMMON_ITEM_ID,
            ItemAssetKind.STACK,
            TagSet.of("item.special"),
            99,
            {"item_component.storage": ItemStorageComponent(1)},
        )
    )
    catalog.register(
        ItemDefinition(
            RARE_ITEM_ID,
            ItemAssetKind.STACK,
            TagSet.of("item.special"),
            99,
            {"item_component.storage": ItemStorageComponent(1)},
        )
    )
    catalog.finalize()
    container = ItemContainer("special", "container.special", "character-a")
    receipt = SourceReceipt("receipt:ticket", "source.test", "ticket", TIME)
    inventory = InventoryState(
        containers={container.id: container},
        stacks={
            "ticket-stack": ItemStack(
                "ticket-stack",
                TICKET_ID,
                container.id,
                (ProvenanceLot(receipt, 3),),
            )
        },
    )
    combined = DrawInventoryEngine(engine, InventoryEngine(catalog))
    result = combined.execute(
        DrawInventoryCommand(
            DrawCommand("draw:inventory", "character-a", POOL_ID, 0, 2),
            "ticket-stack",
            container.id,
            0,
        ),
        inventory_state=inventory,
        loot_state=LootState("character-a"),
        context=_context("inventory"),
    ).unwrap()
    assert result.inventory_state.revision == 1
    assert result.inventory_state.stacks["ticket-stack"].quantity == 1
    awards = [
        stack
        for stack in result.inventory_state.stacks.values()
        if stack.definition_id in {COMMON_ITEM_ID, RARE_ITEM_ID}
    ]
    assert sum(stack.quantity for stack in awards) == 2
    assert result.receipt.ticket_quantity == 2

    failing_context = _context("inventory-failure")
    checkpoint = failing_context.random.checkpoint()
    full_inventory = InventoryState(
        containers={container.id: container},
        stacks={
            "ticket-stack": inventory.stacks["ticket-stack"],
            "award-stack": ItemStack(
                "award-stack",
                COMMON_ITEM_ID,
                container.id,
                (ProvenanceLot(receipt, 99),),
            ),
            "rare-award-stack": ItemStack(
                "rare-award-stack",
                RARE_ITEM_ID,
                container.id,
                (ProvenanceLot(receipt, 99),),
            ),
        },
    )
    failing = combined.execute(
        DrawInventoryCommand(
            DrawCommand("draw:inventory-failure", "character-a", POOL_ID, 0, 2),
            "ticket-stack",
            container.id,
            0,
        ),
        inventory_state=full_inventory,
        loot_state=LootState("character-a"),
        context=failing_context,
    )
    assert failing.failure is not None
    assert failing_context.random.checkpoint() == checkpoint


if __name__ == "__main__":
    main()
