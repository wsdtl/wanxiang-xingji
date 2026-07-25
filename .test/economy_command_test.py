"""回收、二手与税务命令通过本地驱动器的最终回复巡检。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "test") not in sys.path:
    sys.path.insert(0, str(ROOT / "test"))

from economy_system_test import _fund, _grant_equipment, _grant_weapon  # noqa: E402
from game.app import build_game_services, install_game_services, restore_game_services  # noqa: E402
from game.cmd import 二手 as market_component  # noqa: E402,F401
from game.cmd import 回收 as recycle_component  # noqa: E402,F401
from game.cmd import 角色 as character_component  # noqa: E402,F401
from game.content.catalog.item import SMALL_HEALTH_MEDICINE_ITEM_ID  # noqa: E402
from game.core.gameplay import InventoryState  # noqa: E402
from game.core.persistence import CHARACTER_AGGREGATE  # noqa: E402
from game.rules.item import asset_reference  # noqa: E402
from launch.adapter.local import LocalEventHandler, dispatch  # noqa: E402
from launch.adapter.qq import QqEventHandler  # noqa: E402


COMMANDS = (
    "回收",
    "批量回收",
    "回收战利品",
    "二手",
    "上架",
    "下架",
    "购买",
    "我的上架",
    "税务",
)


def main() -> None:
    asyncio.run(_main())
    print("economy command tests passed")


async def _main() -> None:
    for command in COMMANDS:
        assert len(LocalEventHandler.exact_rules[command]) == 1
        assert len(QqEventHandler.exact_rules[command]) == 1
    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "economy-command.db",
            identity_secret="economy-command-secret",
        )
        services.database.initialize()
        previous = install_game_services(services)
        try:
            await LocalEventHandler.run()
            services.economy.initialize(logical_time=_time())
            await _dispatch("seller", "创建角色 卖家", "economy-create-seller")
            await _dispatch("buyer", "创建角色 买家", "economy-create-buyer")
            characters = _characters(services)
            seller = characters["卖家"]
            buyer = characters["买家"]

            recycle_asset = _grant_equipment(services, seller.id, "cmd-recycle", seed=101)
            inventory = _inventory(services, seller.id)
            reference = asset_reference(inventory, recycle_asset, services.content.catalog.items)
            quoted = await _dispatch("seller", f"回收 {reference}", "economy-recycle-quote")
            assert "归航回收·报价" in quoted.replies[0].message.content
            assert "回收所得" in quoted.replies[0].message.content
            assert "永久注销物品档案" in quoted.replies[0].message.content
            assert "不动用归航库" in quoted.replies[0].message.content
            confirm = quoted.replies[0].message.actions[0].data
            recycled = await _dispatch("seller", confirm, "economy-recycle-confirm")
            assert "归航回收·完成" in recycled.replies[0].message.content

            batch = await _dispatch("seller", "批量回收", "economy-batch-home")
            assert len(batch.replies[0].message.actions) == 7
            quality = await _dispatch(
                "seller",
                batch.replies[0].message.actions[1].data,
                "economy-batch-quality",
            )
            assert len(quality.replies[0].message.actions) == 5

            weapon_slot = batch.replies[0].message.actions[0].data
            weapon_quality_page = await _dispatch(
                "seller",
                weapon_slot,
                "economy-batch-weapon-quality",
            )
            assert len(weapon_quality_page.replies[0].message.actions) == 5
            weapon = _grant_weapon(services, seller.id, "cmd-batch-weapon", seed=303, level=10)
            weapon_quality = services.economy.prices.quote(weapon).quality_id
            weapon_quality_action = next(
                action
                for action in weapon_quality_page.replies[0].message.actions
                if weapon_quality in action.data
            )
            weapon_levels = await _dispatch(
                "seller",
                weapon_quality_action.data,
                "economy-batch-levels",
            )
            assert "等级上限" in weapon_levels.replies[0].message.content
            level_action = next(
                action
                for action in weapon_levels.replies[0].message.actions
                if action.data.endswith(" 10")
            )
            weapon_quote = await _dispatch(
                "seller",
                level_action.data,
                "economy-batch-quote-level",
            )
            assert "回收所得" in weapon_quote.replies[0].message.content
            assert " 10 " in weapon_quote.replies[0].message.actions[0].data

            market_asset = _grant_equipment(services, seller.id, "cmd-market", seed=202)
            inventory = _inventory(services, seller.id)
            market_reference = asset_reference(
                inventory,
                market_asset,
                services.content.catalog.items,
            )
            listing_quote = await _dispatch(
                "seller",
                f"上架 {market_reference} 1",
                "economy-list-quote",
            )
            assert "预计到手" in listing_quote.replies[0].message.content
            listed = await _dispatch(
                "seller",
                listing_quote.replies[0].message.actions[0].data,
                "economy-list-confirm",
            )
            assert "M1 已进入归航市场" in listed.replies[0].message.content

            detail = await _dispatch("buyer", "二手 M1", "economy-market-detail")
            assert detail.replies[0].message.actions[0].data == "购买 M1"
            _fund(services, buyer.id, 100_000)
            purchase_quote = await _dispatch("buyer", "购买 M1", "economy-buy-quote")
            assert "低价纠偏" in purchase_quote.replies[0].message.content
            purchased = await _dispatch(
                "buyer",
                purchase_quote.replies[0].message.actions[0].data,
                "economy-buy-confirm",
            )
            assert "归航成交" in purchased.replies[0].message.content
            assert market_asset.id in _inventory(services, buyer.id).instances

            medicine = next(
                value
                for value in _inventory(services, seller.id).stacks.values()
                if value.definition_id == SMALL_HEALTH_MEDICINE_ITEM_ID
            )
            medicine_reference = asset_reference(
                _inventory(services, seller.id),
                medicine,
                services.content.catalog.items,
            )
            medicine_quote = await _dispatch(
                "seller",
                f"上架 {medicine_reference} 2 30",
                "economy-list-medicine-quote",
            )
            assert "数量" in medicine_quote.replies[0].message.content
            assert f" {medicine_reference} 2 30 " in medicine_quote.replies[0].message.actions[0].data
            medicine_listed = await _dispatch(
                "seller",
                medicine_quote.replies[0].message.actions[0].data,
                "economy-list-medicine-confirm",
            )
            assert "M2 已进入归航市场" in medicine_listed.replies[0].message.content
            medicine_page = await _dispatch("buyer", "二手 药品", "economy-market-medicine")
            assert "x2" in medicine_page.replies[0].message.content
            medicine_buy = await _dispatch("buyer", "购买 M2", "economy-buy-medicine")
            medicine_purchased = await _dispatch(
                "buyer",
                medicine_buy.replies[0].message.actions[0].data,
                "economy-buy-medicine-confirm",
            )
            assert "归航成交" in medicine_purchased.replies[0].message.content
            buyer_medicine_total = sum(
                value.quantity
                for value in _inventory(services, buyer.id).stacks.values()
                if value.definition_id == SMALL_HEALTH_MEDICINE_ITEM_ID
            )
            assert buyer_medicine_total == 4

            tax = await _dispatch("buyer", "税务", "economy-tax")
            assert "归航公约·税务" in tax.replies[0].message.content
            assert "归航库" in tax.replies[0].message.content
            assert "近七日税收" in tax.replies[0].message.content

            empty_trophies = await _dispatch(
                "buyer",
                "回收战利品",
                "economy-empty-trophies",
            )
            assert "归航回收·战利品" in empty_trophies.replies[0].message.content
            assert "没有可回收的战利品" in empty_trophies.replies[0].message.content
        finally:
            restore_game_services(previous)


async def _dispatch(client_id: str, raw_message: str, event_id: str):
    return await dispatch(
        client_id=client_id,
        raw_message=raw_message,
        sender_name=client_id,
        event_id=event_id,
    )


def _characters(services):
    with services.database.unit_of_work(write=False) as uow:
        rows = uow.connection.execute(
            "SELECT aggregate_id FROM aggregate_snapshot WHERE aggregate_kind = ?",
            (CHARACTER_AGGREGATE,),
        ).fetchall()
    values = [services.characters.load_character(str(row[0])) for row in rows]
    return {value.name: value for value in values if value is not None}


def _inventory(services, character_id):
    with services.database.unit_of_work(write=False) as uow:
        return services.economy.snapshots.require(
            uow,
            services.economy.storage.inventory,
            character_id,
            InventoryState,
        )


def _time():
    return datetime.now(ZoneInfo("Asia/Shanghai"))


if __name__ == "__main__":
    main()
