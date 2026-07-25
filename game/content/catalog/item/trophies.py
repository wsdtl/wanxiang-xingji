"""探险产出的区域战利品、敌人凭证、首领遗物与世界奇珍。"""

from __future__ import annotations

from types import MappingProxyType

from game.core.gameplay import (
    ITEM_STORAGE_COMPONENT_ID,
    ItemAssetKind,
    ItemDefinition,
    ItemStorageComponent,
    StableId,
    TagSet,
)

from ..enemy.definitions import PERSONAL_BOSS_ENEMIES, REGULAR_ENEMIES
from ..enemy.party import PARTY_BOSS_ENEMIES
from ..foundation import PRIMARY_CURRENCY_ID
from ..world import (
    BLACK_WIND_RAVINE_ID,
    BROKEN_PILLAR_RELIC_ID,
    GREEN_CLOUD_PLAIN_ID,
    HEAVENLY_CRAFT_RELIC_ID,
    KUNLUN_SKY_RUINS_ID,
    MIRROR_LAKE_MARSH_ID,
    MYRIAD_SWORD_TOMB_ID,
    NORTHERN_ABYSS_SNOWFIELD_ID,
    RETURNING_RUIN_ABYSS_ID,
    SCARLET_FLAME_VALLEY_ID,
    SUNSET_RIDGE_ID,
    THUNDER_MARSH_STEPPE_ID,
    VERDANT_WILDERNESS_ID,
)
from .exchange import EXCHANGE_MATERIAL_ITEM_ID
from .trade import (
    ITEM_RECYCLE_COMPONENT_ID,
    CurrencyRecycleYield,
    ItemRecycleYield,
    StackItemRecycleYield,
)


TROPHY_STACK_LIMIT = 999
TROPHY_UNIT_SPACE = 1
REGION_TROPHY_WEIGHTS = (35, 25, 18, 12, 7, 3)

_REGION_PRICE_ROWS = (
    (4, 5, 7, 9, 13, 20),
    (7, 9, 12, 16, 23, 34),
    (12, 15, 20, 27, 39, 58),
    (20, 25, 33, 45, 64, 96),
    (32, 40, 54, 72, 104, 156),
    (50, 63, 84, 113, 163, 245),
    (78, 98, 131, 176, 254, 380),
    (120, 150, 200, 270, 390, 585),
    (180, 225, 300, 405, 585, 875),
    (260, 325, 435, 585, 845, 1265),
    (100, 140, 190, 270, 390, 600),
    (160, 220, 300, 420, 610, 940),
    (260, 360, 500, 700, 1020, 1580),
)
_REGION_CODES = (
    (GREEN_CLOUD_PLAIN_ID, "r01"),
    (SUNSET_RIDGE_ID, "r02"),
    (BLACK_WIND_RAVINE_ID, "r03"),
    (MIRROR_LAKE_MARSH_ID, "r04"),
    (SCARLET_FLAME_VALLEY_ID, "r05"),
    (VERDANT_WILDERNESS_ID, "r06"),
    (THUNDER_MARSH_STEPPE_ID, "r07"),
    (NORTHERN_ABYSS_SNOWFIELD_ID, "r08"),
    (BROKEN_PILLAR_RELIC_ID, "r09"),
    (KUNLUN_SKY_RUINS_ID, "r10"),
    (MYRIAD_SWORD_TOMB_ID, "weapon_focus"),
    (HEAVENLY_CRAFT_RELIC_ID, "equipment_focus"),
    (RETURNING_RUIN_ABYSS_ID, "boss_focus"),
)

_REGULAR_ENEMY_PRICE_BANDS = (24, 40, 68, 112, 180, 280, 430, 660, 980, 1450)
_BOSS_PRICE_BANDS = (90, 150, 250, 420, 680, 1050, 1600, 2400, 3500, 5000)
PARTY_BOSS_EXCHANGE_YIELDS = (2, 3, 5, 8, 14, 21, 32, 48, 70, 100)
_WORLD_CURIO_KEYS = (
    "world_scripture",
    "fate_fragment",
    "creation_ember",
    "world_tree_seed",
    "eternal_dew",
    "divine_metal",
    "star_compass",
    "underworld_stone",
    "solar_essence",
    "lunar_essence",
    "chaos_seed",
    "primordial_breath",
)
_WORLD_CURIO_PRICES = (
    600,
    900,
    1300,
    1800,
    2500,
    3400,
    4600,
    6200,
    8300,
    11000,
    14500,
    19000,
)


def _item(
    definition_id: str,
    recycle_yield: ItemRecycleYield | int,
    *category_tags: str,
) -> ItemDefinition:
    if isinstance(recycle_yield, int):
        recycle_yield = CurrencyRecycleYield(PRIMARY_CURRENCY_ID, recycle_yield)
    return ItemDefinition(
        definition_id,
        ItemAssetKind.STACK,
        TagSet.of(
            "item.trophy",
            "loot.recyclable",
            "storage.backpack",
            *category_tags,
        ),
        TROPHY_STACK_LIMIT,
        {
            ITEM_STORAGE_COMPONENT_ID: ItemStorageComponent(TROPHY_UNIT_SPACE),
            ITEM_RECYCLE_COMPONENT_ID: recycle_yield,
        },
    )


_region_items: dict[StableId, tuple[ItemDefinition, ...]] = {}
for (location_id, code), prices in zip(_REGION_CODES, _REGION_PRICE_ROWS):
    _region_items[location_id] = tuple(
        _item(
            f"item.trophy.region.{code}.t{index:02d}",
            price,
            "trophy.region",
            f"trophy.region.{code}",
        )
        for index, price in enumerate(prices, start=1)
    )

REGION_TROPHY_ITEMS = MappingProxyType(_region_items)
REGION_TROPHY_ITEM_IDS = MappingProxyType(
    {
        location_id: tuple(item.id for item in items)
        for location_id, items in REGION_TROPHY_ITEMS.items()
    }
)

REGULAR_ENEMY_TROPHY_ITEMS = tuple(
    _item(
        f"item.trophy.enemy.{enemy.id.removeprefix('enemy.')}",
        _REGULAR_ENEMY_PRICE_BANDS[index // 6],
        "trophy.enemy",
    )
    for index, enemy in enumerate(REGULAR_ENEMIES)
)
REGULAR_ENEMY_TROPHY_ITEM_IDS = MappingProxyType(
    {
        enemy.id: item.id
        for enemy, item in zip(REGULAR_ENEMIES, REGULAR_ENEMY_TROPHY_ITEMS)
    }
)

BOSS_TROPHY_ITEMS = tuple(
    _item(
        f"item.trophy.boss.{enemy.id.removeprefix('enemy.boss.')}",
        _BOSS_PRICE_BANDS[index // 3],
        "trophy.boss",
    )
    for index, enemy in enumerate(PERSONAL_BOSS_ENEMIES)
)
BOSS_TROPHY_ITEM_IDS = MappingProxyType(
    {
        enemy.id: item.id
        for enemy, item in zip(PERSONAL_BOSS_ENEMIES, BOSS_TROPHY_ITEMS)
    }
)

PARTY_BOSS_TROPHY_ITEMS = tuple(
    _item(
        f"item.trophy.party_boss.{enemy.id.removeprefix('enemy.boss.party.')}",
        StackItemRecycleYield(
            EXCHANGE_MATERIAL_ITEM_ID,
            PARTY_BOSS_EXCHANGE_YIELDS[index % len(PARTY_BOSS_EXCHANGE_YIELDS)],
        ),
        "trophy.party_boss",
    )
    for index, enemy in enumerate(PARTY_BOSS_ENEMIES)
)
PARTY_BOSS_TROPHY_ITEM_IDS = MappingProxyType(
    {
        enemy.id: item.id
        for enemy, item in zip(PARTY_BOSS_ENEMIES, PARTY_BOSS_TROPHY_ITEMS)
    }
)

WORLD_CURIO_ITEMS = tuple(
    _item(
        f"item.trophy.curio.{key}",
        price,
        "trophy.curio",
    )
    for key, price in zip(_WORLD_CURIO_KEYS, _WORLD_CURIO_PRICES)
)
WORLD_CURIO_ITEM_IDS = tuple(item.id for item in WORLD_CURIO_ITEMS)
WORLD_CURIO_WEIGHTS = (30, 24, 18, 12, 8, 5, 4, 3, 2, 1, 1, 1)

TROPHY_ITEMS = (
    *(item for items in REGION_TROPHY_ITEMS.values() for item in items),
    *REGULAR_ENEMY_TROPHY_ITEMS,
    *BOSS_TROPHY_ITEMS,
    *PARTY_BOSS_TROPHY_ITEMS,
    *WORLD_CURIO_ITEMS,
)
TROPHY_DISPLAY_CONTENT_IDS = frozenset(item.id for item in TROPHY_ITEMS)


def _validate() -> None:
    if not TROPHY_ITEMS:
        raise ValueError("正式战利品名录不能为空")
    ids = tuple(item.id for item in TROPHY_ITEMS)
    if len(ids) != len(set(ids)):
        raise ValueError("战利品稳定 ID 不能重复")
    if set(REGION_TROPHY_ITEM_IDS) != {value[0] for value in _REGION_CODES}:
        raise ValueError("区域战利品必须完整覆盖全部探险地点")
    party_ids = {item.id for item in PARTY_BOSS_TROPHY_ITEMS}
    for item in TROPHY_ITEMS:
        output = item.component(ITEM_RECYCLE_COMPONENT_ID, ItemRecycleYield)
        is_material = isinstance(output, StackItemRecycleYield)
        if is_material != (item.id in party_ids):
            raise ValueError("只有组队首领战利品可以回收为定相尘")
        if is_material and output.definition_id != EXCHANGE_MATERIAL_ITEM_ID:
            raise ValueError("组队首领战利品必须统一回收为定相尘")


_validate()


__all__ = [
    "BOSS_TROPHY_ITEM_IDS",
    "BOSS_TROPHY_ITEMS",
    "PARTY_BOSS_TROPHY_ITEM_IDS",
    "PARTY_BOSS_TROPHY_ITEMS",
    "PARTY_BOSS_EXCHANGE_YIELDS",
    "REGION_TROPHY_ITEM_IDS",
    "REGION_TROPHY_ITEMS",
    "REGION_TROPHY_WEIGHTS",
    "REGULAR_ENEMY_TROPHY_ITEM_IDS",
    "REGULAR_ENEMY_TROPHY_ITEMS",
    "TROPHY_DISPLAY_CONTENT_IDS",
    "TROPHY_ITEMS",
    "TROPHY_STACK_LIMIT",
    "TROPHY_UNIT_SPACE",
    "WORLD_CURIO_ITEM_IDS",
    "WORLD_CURIO_ITEMS",
    "WORLD_CURIO_WEIGHTS",
]
