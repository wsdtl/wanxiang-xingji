"""公共抽奖签奖池、档位和正式平衡参数。"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from game.core.gameplay import (
    DrawGuaranteeEntry,
    DrawGuaranteeSlotDefinition,
    DrawPoolDefinition,
    LootEntry,
    LootGroup,
    LootGroupMode,
    LootPityDefinition,
    LootTableDefinition,
)

from ..item import (
    BREAKTHROUGH_TOKEN_ITEM_ID,
    DRAW_TICKET_ITEM_ID,
    LARGE_HEALTH_MEDICINE_ITEM_ID,
    LARGE_SPIRIT_MEDICINE_ITEM_ID,
    MEDIUM_HEALTH_MEDICINE_ITEM_ID,
    MEDIUM_SPIRIT_MEDICINE_ITEM_ID,
    SMALL_HEALTH_MEDICINE_ITEM_ID,
    SMALL_SPIRIT_MEDICINE_ITEM_ID,
    SPECIAL_ITEMS,
)


DRAW_POOL_ID = "draw_pool.special"
DRAW_LOOT_TABLE_ID = "loot.draw.special"
DRAW_REWARD_LOW_CURRENCY_ID = "draw_reward.currency.low"
DRAW_REWARD_MID_CURRENCY_ID = "draw_reward.currency.mid"
DRAW_BREAKTHROUGH_GUARANTEE_SLOT_ID = "draw_guarantee.breakthrough"
DRAW_BREAKTHROUGH_GUARANTEE_ENTRY_ID = "draw_guarantee_entry.breakthrough_token"
DRAW_CURRENCY_COST_PER_ROLL = 250

DRAW_TIER_LOW = "low"
DRAW_TIER_MID = "mid"
DRAW_TIER_HIGH = "high"
DRAW_TIER_BREAKTHROUGH = "breakthrough"

DRAW_LOW_CURRENCY_AMOUNT = 20
DRAW_MID_CURRENCY_AMOUNT = 100
DRAW_MID_PITY_THRESHOLD = 10
DRAW_BREAKTHROUGH_PITY_THRESHOLD = 50
DRAW_LOW_WEIGHT = 77_000
DRAW_MID_WEIGHT = 20_000
DRAW_HIGH_WEIGHT = 2_000
DRAW_BREAKTHROUGH_WEIGHT = 1_000


@dataclass(frozen=True)
class DrawCatalogContent:
    loot_table: LootTableDefinition
    pool: DrawPoolDefinition
    entry_tiers: Mapping[str, str]
    special_item_ids: frozenset[str]
    breakthrough_item_ids: frozenset[str]


def _entries(
    tier: str,
    total_weight: int,
    values: tuple[tuple[str, str, int, int], ...],
) -> tuple[LootEntry, ...]:
    ratio_total = sum(value[3] for value in values)
    weights = [total_weight * value[3] // ratio_total for value in values]
    weights[0] += total_weight - sum(weights)
    return tuple(
        LootEntry(
            f"draw_entry.{tier}.{key}",
            award_id,
            weight=weight,
            minimum_quantity=quantity,
            maximum_quantity=quantity,
        )
        for (key, award_id, quantity, _), weight in zip(values, weights)
    )


def build_draw_catalog_content() -> DrawCatalogContent:
    special_ids = tuple(sorted(str(value.id) for value in SPECIAL_ITEMS))
    low_weight = DRAW_LOW_WEIGHT if special_ids else DRAW_LOW_WEIGHT + DRAW_HIGH_WEIGHT
    low_entries = _entries(
        DRAW_TIER_LOW,
        low_weight,
        (
            ("currency", DRAW_REWARD_LOW_CURRENCY_ID, DRAW_LOW_CURRENCY_AMOUNT, 8),
            ("small_health", SMALL_HEALTH_MEDICINE_ITEM_ID, 2, 3),
            ("small_spirit", SMALL_SPIRIT_MEDICINE_ITEM_ID, 2, 3),
            ("medium_health", MEDIUM_HEALTH_MEDICINE_ITEM_ID, 1, 3),
            ("medium_spirit", MEDIUM_SPIRIT_MEDICINE_ITEM_ID, 1, 3),
        ),
    )
    mid_entries = _entries(
        DRAW_TIER_MID,
        DRAW_MID_WEIGHT,
        (
            ("currency", DRAW_REWARD_MID_CURRENCY_ID, DRAW_MID_CURRENCY_AMOUNT, 8),
            ("medium_health", MEDIUM_HEALTH_MEDICINE_ITEM_ID, 2, 3),
            ("medium_spirit", MEDIUM_SPIRIT_MEDICINE_ITEM_ID, 2, 3),
            ("large_health", LARGE_HEALTH_MEDICINE_ITEM_ID, 1, 3),
            ("large_spirit", LARGE_SPIRIT_MEDICINE_ITEM_ID, 1, 3),
        ),
    )
    high_entries: tuple[LootEntry, ...] = ()
    if special_ids:
        base_weight, remainder = divmod(DRAW_HIGH_WEIGHT, len(special_ids))
        high_entries = tuple(
            LootEntry(
                f"draw_entry.{DRAW_TIER_HIGH}.{item_id}",
                item_id,
                weight=base_weight + (1 if index < remainder else 0),
            )
            for index, item_id in enumerate(special_ids)
        )
    breakthrough_entries = (
        LootEntry(
            "draw_entry.breakthrough.token",
            BREAKTHROUGH_TOKEN_ITEM_ID,
            weight=DRAW_BREAKTHROUGH_WEIGHT,
        ),
    )
    entries = (*low_entries, *mid_entries, *high_entries, *breakthrough_entries)
    mid_or_high_ids = frozenset(
        value.id
        for value in (*mid_entries, *high_entries, *breakthrough_entries)
    )
    table = LootTableDefinition(
        DRAW_LOOT_TABLE_ID,
        2,
        (
            LootGroup(
                "loot_group.draw.special",
                LootGroupMode.WEIGHTED_ONE,
                entries,
            ),
        ),
        LootPityDefinition(
            "loot_group.draw.special",
            DRAW_MID_PITY_THRESHOLD,
            mid_or_high_ids,
            mid_or_high_ids,
        ),
    )
    pool = DrawPoolDefinition(
        DRAW_POOL_ID,
        2,
        DRAW_TICKET_ITEM_ID,
        table.id,
        frozenset(value.award_id for value in entries if value.award_id is not None),
        (
            DrawGuaranteeSlotDefinition(
                DRAW_BREAKTHROUGH_GUARANTEE_SLOT_ID,
                DRAW_BREAKTHROUGH_PITY_THRESHOLD,
                (
                    DrawGuaranteeEntry(
                        DRAW_BREAKTHROUGH_GUARANTEE_ENTRY_ID,
                        BREAKTHROUGH_TOKEN_ITEM_ID,
                    ),
                ),
            ),
        ),
    )
    tiers = {
        entry.id: tier
        for tier, tier_entries in (
            (DRAW_TIER_LOW, low_entries),
            (DRAW_TIER_MID, mid_entries),
            (DRAW_TIER_HIGH, high_entries),
            (DRAW_TIER_BREAKTHROUGH, breakthrough_entries),
        )
        for entry in tier_entries
    }
    tiers[DRAW_BREAKTHROUGH_GUARANTEE_ENTRY_ID] = DRAW_TIER_BREAKTHROUGH
    return DrawCatalogContent(
        table,
        pool,
        MappingProxyType(tiers),
        frozenset(special_ids),
        frozenset({BREAKTHROUGH_TOKEN_ITEM_ID}),
    )


DRAW_CATALOG_CONTENT = build_draw_catalog_content()


__all__ = [name for name in globals() if not name.startswith("_")]
