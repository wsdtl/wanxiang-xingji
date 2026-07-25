"""归航市场列表、上架购买报价和税务展示。"""

from __future__ import annotations

import asyncio
from math import ceil

from game.app import CharacterOverview, CharacterOverviewResult, current_game_services
from game.content.catalog.foundation import PRIMARY_CURRENCY_ID
from game.content.presentation import (
    COVENANT_MARKET_NAME,
    COVENANT_NAME,
    COVENANT_TREASURY_NAME,
)
from game.core.gameplay import (
    STANDARD_LOADOUT_SLOT_ORDER,
    ItemInstance,
    equipment_state_from_instance,
    weapon_state_from_instance,
)
from game.rules.economy import quote_market_tax
from game.rules.item import resolve_asset_reference
from message import Action, DocumentMessage, M

from ..command_helpers import command_time
from ..reply import send_command_failure, send_game_reply


PAGE_SIZE = 20


async def market(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    parts = str(message or "").strip().split()
    if parts and _looks_like_listing(parts[0]):
        await _listing_detail(parts[0], overview)
        return
    slot_id = None
    category = None
    page = 1
    try:
        if parts:
            slot_id = _slot_id(parts[0], overview)
            if slot_id is None:
                category = _category_id(parts[0])
                if category is None:
                    page = _page(parts[0])
            elif len(parts) > 1:
                page = _page(parts[1])
            if category is not None and len(parts) > 1:
                page = _page(parts[1])
        listings = await asyncio.to_thread(
            current_game_services().economy.listings,
            logical_time=command_time(),
            slot_id=slot_id,
            category=category,
        )
        await send_game_reply(_listing_page(COVENANT_MARKET_NAME, listings, page, overview))
    except ValueError as exc:
        await send_game_reply(_failure(str(exc)))


async def my_listings(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    try:
        page = _page(message or "1")
        listings = await asyncio.to_thread(
            current_game_services().economy.listings,
            logical_time=command_time(),
            seller_id=overview.character.id,
        )
        await send_game_reply(_listing_page("我的上架", listings, page, overview))
    except ValueError as exc:
        await send_game_reply(_failure(str(exc)))


async def list_item(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    parts = str(message or "").strip().split()
    if len(parts) not in {2, 3}:
        await send_game_reply(_failure("上架格式：上架 物品编号 价格，堆叠物品可填写数量"))
        return
    try:
        asset = resolve_asset_reference(
            overview.inventory,
            parts[0],
            current_game_services().content.catalog.items,
        )
        quantity = 1 if len(parts) == 2 else int(parts[1])
        price = int(parts[1] if len(parts) == 2 else parts[2])
        if price < 1:
            raise ValueError("上架价格必须大于 0")
        quoted = await asyncio.to_thread(
            current_game_services().economy.quote_listing,
            overview.character.id,
            overview.character.name,
            asset.id,
            price,
            quantity,
        )
        await send_game_reply(_listing_quote_message(quoted, overview, parts[0]))
    except (KeyError, TypeError, ValueError) as exc:
        await send_game_reply(_failure(str(exc)))


async def confirm_listing(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    parts = str(message or "").strip().split()
    if len(parts) not in {3, 4}:
        await send_game_reply(_failure("上架确认已经失效"))
        return
    services = current_game_services()
    try:
        asset = resolve_asset_reference(
            overview.inventory,
            parts[0],
            services.content.catalog.items,
        )
        quoted = await asyncio.to_thread(
            services.economy.quote_listing,
            overview.character.id,
            overview.character.name,
            asset.id,
            int(parts[1] if len(parts) == 3 else parts[2]),
            1 if len(parts) == 3 else int(parts[1]),
        )
        if quoted.quote is None or quoted.quote.id != parts[-1]:
            await send_game_reply(_failure("上架报价已经变化，请重新上架"))
            return
        opened = await asyncio.to_thread(
            services.economy.open_listing,
            overview.character.id,
            quoted.quote,
            logical_time=command_time(),
        )
        builder = M.document().section("上架", icon="trade")
        if opened.status == "listed" and opened.listing is not None:
            builder.line(f"{opened.listing.id} 已进入{COVENANT_MARKET_NAME}")
            builder.row(
                ("物品", _market_asset_name(opened.listing.asset, overview)),
                ("价格", opened.listing.list_price),
                ("数量", _listing_quantity(opened.listing)),
            )
        else:
            builder.line(opened.failure_message or "本次上架没有完成")
        await send_game_reply(builder.build())
    except (KeyError, TypeError, ValueError) as exc:
        await send_game_reply(_failure(str(exc)))
    except Exception as exc:
        await _failed("二手上架失败", overview.character.id, exc)


async def cancel_listing(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    listing_id = str(message or "").strip()
    try:
        closed = await asyncio.to_thread(
            current_game_services().economy.cancel_listing,
            overview.character.id,
            listing_id,
            logical_time=command_time(),
        )
        builder = M.document().section("下架", icon="trade")
        if closed.status == "cancelled" and closed.listing is not None:
            builder.line(f"{closed.listing.id} 已下架")
        else:
            builder.line(closed.failure_message or "本次下架没有完成")
        await send_game_reply(builder.build())
    except ValueError as exc:
        await send_game_reply(_failure(str(exc)))
    except Exception as exc:
        await _failed("二手下架失败", overview.character.id, exc)


async def buy(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    listing_id = str(message or "").strip()
    try:
        quoted = await asyncio.to_thread(
            current_game_services().economy.quote_purchase,
            overview.character.id,
            listing_id,
            logical_time=command_time(),
        )
        await send_game_reply(_purchase_quote_message(quoted, overview))
    except ValueError as exc:
        await send_game_reply(_failure(str(exc)))


async def confirm_purchase(message: str, result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    parts = str(message or "").strip().split()
    if len(parts) != 2:
        await send_game_reply(_failure("购买确认已经失效"))
        return
    services = current_game_services()
    try:
        quoted = await asyncio.to_thread(
            services.economy.quote_purchase,
            overview.character.id,
            parts[0],
            logical_time=command_time(),
        )
        if quoted.quote is None or quoted.quote.id != parts[1]:
            await send_game_reply(_failure("购买报价已经变化，请重新确认"))
            return
        purchased = await asyncio.to_thread(
            services.economy.purchase,
            overview.character.id,
            quoted.quote,
            logical_time=command_time(),
        )
        builder = M.document().section("归航成交", icon="trade")
        if purchased.status == "purchased" and purchased.quote is not None:
            builder.line(_market_asset_name(purchased.quote.listing.asset, overview))
            builder.field("数量", _listing_quantity(purchased.quote.listing))
            builder.row(
                ("支付", purchased.quote.tax.buyer_total),
                ("税金", purchased.quote.tax.tax_amount),
            )
        else:
            builder.line(purchased.failure_message or "本次购买没有完成")
        await send_game_reply(builder.build())
    except ValueError as exc:
        await send_game_reply(_failure(str(exc)))
    except Exception as exc:
        await _failed("二手购买失败", overview.character.id, exc)


async def tax(result: CharacterOverviewResult) -> None:
    overview = _overview(result)
    if overview is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    summary = await asyncio.to_thread(
        current_game_services().economy.tax_summary,
        logical_time=command_time(),
    )
    currency = _view(overview).projector.name(PRIMARY_CURRENCY_ID)
    await send_game_reply(
        M.document()
        .section(f"{COVENANT_NAME}·税务", icon="trade")
        .field("税务主体", COVENANT_NAME)
        .field(COVENANT_TREASURY_NAME, f"{summary.balance} {currency}")
        .row(("近七日税收", summary.recent_tax), ("成交", summary.recent_trades))
        .build()
    )


async def _listing_detail(listing_id: str, overview: CharacterOverview) -> None:
    listings = await asyncio.to_thread(
        current_game_services().economy.listings,
        logical_time=command_time(),
    )
    listing = next((value for value in listings if value.id == listing_id.upper()), None)
    if listing is None:
        await send_game_reply(_failure("找不到这份归航挂单"))
        return
    builder = (
        M.document()
        .section(f"归航·{listing.id}", icon="trade")
        .line(_market_asset_name(listing.asset, overview))
        .field("数量", _listing_quantity(listing))
        .row(("售价", listing.list_price), ("参考价", listing.price.reference_price))
        .field("卖方", listing.seller_name)
    )
    if listing.seller_id == overview.character.id:
        builder.actions((Action("market.cancel", "下架", f"下架 {listing.id}", style="secondary"),))
    else:
        builder.actions((Action("market.buy", "购买", f"购买 {listing.id}"),))
    await send_game_reply(builder.build())


def _listing_quote_message(result, overview, reference) -> DocumentMessage:
    builder = M.document().section("上架报价", icon="trade")
    quote = result.quote
    if result.status != "quoted" or quote is None:
        return builder.line(result.failure_message or "本次上架报价没有生成").build()
    tax = quote_market_tax(
        quote.price.reference_price,
        quote.list_price,
        minimum_price_bps=quote.price.minimum_price_bps,
        maximum_price_bps=quote.price.maximum_price_bps,
    )
    builder.line(_market_asset_name(overview.inventory.asset(quote.asset_id), overview))
    builder.field("数量", quote.quantity)
    builder.row(("参考价", quote.price.reference_price), ("上架价", quote.list_price))
    builder.row(("预计到手", tax.seller_proceeds), ("基础税", tax.tax_amount))
    return builder.actions(
        (
            Action(
                "market.list.confirm",
                "确认上架",
                f"economy_market_list_confirm {reference} {quote.quantity} {quote.list_price} {quote.id}",
            ),
        )
    ).build()


def _purchase_quote_message(result, overview) -> DocumentMessage:
    builder = M.document().section("购买报价", icon="trade")
    quote = result.quote
    if result.status != "quoted" or quote is None:
        return builder.line(result.failure_message or "本次购买报价没有生成").build()
    builder.line(_market_asset_name(quote.listing.asset, overview))
    builder.field("数量", _listing_quantity(quote.listing))
    builder.row(("售价", quote.tax.list_price), ("参考价", quote.tax.reference_price))
    builder.row(("实际支付", quote.tax.buyer_total), ("税金", quote.tax.tax_amount))
    if quote.tax.low_price_surcharge:
        builder.field("低价纠偏", quote.tax.low_price_surcharge)
    if quote.tax.high_price_tax:
        builder.field("高价纠偏", quote.tax.high_price_tax)
    if quote.tax.risk_surcharge:
        builder.field("交易风险税", quote.tax.risk_surcharge)
    if quote.tax.repeated_pair_trades or quote.tax.repeated_asset_trades:
        builder.field("常规税率", f"{quote.tax.normal_tax_rate_bps / 100:.0f}%")
    return builder.actions(
        (
            Action(
                "market.buy.confirm",
                "确认购买",
                f"economy_market_buy_confirm {quote.listing.id} {quote.id}",
            ),
        )
    ).build()


def _listing_page(title, listings, page, overview) -> DocumentMessage:
    total_pages = max(1, ceil(len(listings) / PAGE_SIZE))
    if page > total_pages:
        raise ValueError(f"页码超出范围，当前共 {total_pages} 页")
    start = (page - 1) * PAGE_SIZE
    builder = M.document().section(title, icon="trade")
    current = listings[start : start + PAGE_SIZE]
    if not current:
        return builder.line("当前没有符合条件的归航挂单").build()
    for index, listing in enumerate(current, start=start + 1):
        builder.item(
            index,
            f"[{listing.id}] {_market_asset_name(listing.asset, overview)} x{_listing_quantity(listing)} | {listing.list_price}",
        )
    builder.field("页码", f"{page}/{total_pages}")
    return builder.build()


def _market_asset_name(asset, overview: CharacterOverview) -> str:
    view = _view(overview)
    definition = current_game_services().content.catalog.items.require(asset.definition_id)
    if isinstance(asset, ItemInstance) and definition.tags.has("item.weapon"):
        return view.gear_projector.weapon(
            weapon_state_from_instance(asset),
            asset,
            inscription_preference=overview.inscription_preference,
        ).name
    if isinstance(asset, ItemInstance) and definition.tags.has("item.equipment"):
        return view.gear_projector.equipment(
            equipment_state_from_instance(asset),
            asset,
            inscription_preference=overview.inscription_preference,
        ).name
    return view.projector.name(definition.id)


def _listing_quantity(listing) -> int:
    return int(getattr(listing.price, "quantity", 1))


def _category_id(value: str) -> str | None:
    return {
        "药品": "medicine",
        "特殊": "special_all",
        "成长": "growth",
        "永久": "permanent",
        "铭刻": "inscription",
        "抽奖签": "draw",
        "凭证": "breakthrough",
        "材料": "exchange_material",
        "图纸": "blueprint",
    }.get(str(value).strip())


def _slot_id(value: str, overview: CharacterOverview) -> str | None:
    if value in STANDARD_LOADOUT_SLOT_ORDER:
        return value
    resolved = _view(overview).projector.resolve_alias(value)
    return resolved if resolved in STANDARD_LOADOUT_SLOT_ORDER else None


def _page(value: str) -> int:
    try:
        page = int(str(value).strip() or "1")
    except ValueError as exc:
        raise ValueError("页码必须是正整数") from exc
    if page < 1:
        raise ValueError("页码必须是正整数")
    return page


def _looks_like_listing(value: str) -> bool:
    text = str(value or "").strip().upper()
    return text.startswith("M") and text[1:].isdigit()


def _view(overview: CharacterOverview):
    return current_game_services().world_view(overview.character_world)


def _overview(result: CharacterOverviewResult) -> CharacterOverview | None:
    return result.overview if result.status == "ok" else None


async def _failed(title: str, character_id: str, exc: Exception) -> None:
    await send_command_failure(
        title,
        character_id,
        exc,
        _failure("当前操作没有完成，请稍后重试"),
    )


def _failure(message: str) -> DocumentMessage:
    return M.document().section(COVENANT_MARKET_NAME, icon="notice").line(message).build()


__all__ = [
    "buy",
    "cancel_listing",
    "confirm_listing",
    "confirm_purchase",
    "list_item",
    "market",
    "my_listings",
    "tax",
]
