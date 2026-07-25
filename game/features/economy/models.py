"""经济玩法对命令层公开的稳定结果。"""

from __future__ import annotations

from dataclasses import dataclass

from game.rules.economy import (
    MarketListing,
    MarketPriceQuote,
    MarketTaxQuote,
    RecycleQuote,
)
from game.rules.item import TrophyRecycleQuote


@dataclass(frozen=True)
class EconomyStorageKinds:
    inventory: str
    loadout: str
    ledger: str
    market: str


@dataclass(frozen=True)
class RecycleOperationResult:
    status: str
    quote: RecycleQuote | None = None
    failure_message: str = ""


@dataclass(frozen=True)
class TrophyRecycleResult:
    status: str
    quote: TrophyRecycleQuote


@dataclass(frozen=True)
class MarketListingQuote:
    id: str
    seller_id: str
    seller_name: str
    seller_wallet_account_id: str
    inventory_revision: int
    asset_id: str
    price: MarketPriceQuote
    list_price: int
    quantity: int = 1


@dataclass(frozen=True)
class MarketListingResult:
    status: str
    quote: MarketListingQuote | None = None
    listing: MarketListing | None = None
    failure_message: str = ""


@dataclass(frozen=True)
class MarketPurchaseQuote:
    id: str
    buyer_id: str
    listing: MarketListing
    tax: MarketTaxQuote


@dataclass(frozen=True)
class MarketPurchaseResult:
    status: str
    quote: MarketPurchaseQuote | None = None
    failure_message: str = ""


@dataclass(frozen=True)
class TaxSummary:
    balance: int
    recent_tax: int
    recent_trades: int


__all__ = [
    "EconomyStorageKinds",
    "MarketListingQuote",
    "MarketListingResult",
    "MarketPurchaseQuote",
    "MarketPurchaseResult",
    "RecycleOperationResult",
    "TaxSummary",
    "TrophyRecycleResult",
]
