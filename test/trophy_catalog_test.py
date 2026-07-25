"""正式战利品、价格曲线与多世界展示审计。"""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.content import (  # noqa: E402
    MAGIC_SKIN_ID,
    STELLAR_RING_SKIN_ID,
    assemble_official_catalog,
    select_world_skin,
)
from game.content.catalog import PRIMARY_CURRENCY_ID  # noqa: E402
from game.content.catalog.exploration import REGULAR_EXPLORATION_REGIONS  # noqa: E402
from game.content.catalog.item import (  # noqa: E402
    BOSS_TROPHY_ITEMS,
    PARTY_BOSS_TROPHY_ITEMS,
    PARTY_BOSS_EXCHANGE_YIELDS,
    ITEM_RECYCLE_COMPONENT_ID,
    REGION_TROPHY_ITEMS,
    REGION_TROPHY_WEIGHTS,
    REGULAR_ENEMY_TROPHY_ITEMS,
    TROPHY_ITEMS,
    WORLD_CURIO_ITEMS,
    CurrencyRecycleYield,
    EXCHANGE_MATERIAL_ITEM_ID,
    ItemRecycleYield,
    StackItemRecycleYield,
)
from game.core.gameplay import ITEM_STORAGE_COMPONENT_ID, ItemStorageComponent  # noqa: E402


def main() -> None:
    from game.content.catalog import item as item_catalog

    assert not hasattr(item_catalog, "ItemRecycleValue")
    catalog = assemble_official_catalog()
    cultivation = select_world_skin(catalog)
    magic = select_world_skin(catalog, MAGIC_SKIN_ID)
    stellar = select_world_skin(catalog, STELLAR_RING_SKIN_ID)
    assert len(TROPHY_ITEMS) == 210
    assert sum(len(items) for items in REGION_TROPHY_ITEMS.values()) == 78
    assert len(REGULAR_ENEMY_TROPHY_ITEMS) == 60
    assert len(BOSS_TROPHY_ITEMS) == 30
    assert len(PARTY_BOSS_TROPHY_ITEMS) == 30
    assert len(WORLD_CURIO_ITEMS) == 12
    assert sum(REGION_TROPHY_WEIGHTS) == 100

    cultivation_names = []
    magic_names = []
    stellar_names = []
    for item in TROPHY_ITEMS:
        assert item.tags.has("item.trophy")
        assert item.tags.has("loot.recyclable")
        assert item.tags.has("storage.backpack")
        storage = item.component(ITEM_STORAGE_COMPONENT_ID, ItemStorageComponent)
        sale = item.component(ITEM_RECYCLE_COMPONENT_ID, ItemRecycleYield)
        assert storage.unit_space == 1
        if item in PARTY_BOSS_TROPHY_ITEMS:
            assert isinstance(sale, StackItemRecycleYield)
            assert sale.definition_id == EXCHANGE_MATERIAL_ITEM_ID
            assert sale.unit_quantity > 0
        else:
            assert isinstance(sale, CurrencyRecycleYield)
            assert sale.currency_id == PRIMARY_CURRENCY_ID
            assert sale.unit_amount > 0
        cultivation_names.append(cultivation.projector.name(item.id))
        magic_names.append(magic.projector.name(item.id))
        stellar_names.append(stellar.projector.name(item.id))
    assert len(cultivation_names) == len(set(cultivation_names)) == 210
    assert len(magic_names) == len(set(magic_names)) == 210
    assert len(stellar_names) == len(set(stellar_names)) == 210
    assert cultivation_names != magic_names
    assert stellar_names != cultivation_names and stellar_names != magic_names
    assert tuple(
        item.component(ITEM_RECYCLE_COMPONENT_ID, StackItemRecycleYield).unit_quantity
        for item in PARTY_BOSS_TROPHY_ITEMS[:10]
    ) == PARTY_BOSS_EXCHANGE_YIELDS

    expected_values = []
    for region in REGULAR_EXPLORATION_REGIONS:
        prices = tuple(
            catalog.items.require(item_id)
            .component(ITEM_RECYCLE_COMPONENT_ID, CurrencyRecycleYield)
            .unit_amount
            for item_id in region.trophy_item_ids
        )
        expected_values.append(
            sum(price * weight for price, weight in zip(prices, region.trophy_weights))
            / sum(region.trophy_weights)
        )
    assert all(left < right for left, right in zip(expected_values, expected_values[1:]))
    print("trophy catalog tests passed")


if __name__ == "__main__":
    main()
