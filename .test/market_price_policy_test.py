"""可交易物品参考价覆盖、分类区间和抽奖期望值审计。"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.content import build_official_content  # noqa: E402
from game.content.catalog.draw import DRAW_CATALOG_CONTENT  # noqa: E402
from game.content.catalog.economy import (  # noqa: E402
    MARKET_ITEM_POLICIES,
    audit_market_prices,
)
from game.rules.economy import quote_market_tax  # noqa: E402


def main() -> None:
    content = build_official_content()
    report = audit_market_prices(
        content.catalog.items,
        DRAW_CATALOG_CONTENT,
        content.catalog.equipment,
    )
    assert report.policy_count == 35
    assert report.blueprint_count == 18
    assert report.party_trophy_conversion_count == 30
    assert 149 < report.draw_base_expected_value < 150
    assert report.draw_ticket_reference_price == 200
    assert "item.special.equipment_set_guarantee" not in content.catalog.items.definitions.ids()
    assert not any(item_id.startswith("item.trophy.") for item_id in MARKET_ITEM_POLICIES)

    medicine = MARKET_ITEM_POLICIES["item.consumable.small_health_medicine"]
    low = quote_market_tax(
        1_000,
        500,
        minimum_price_bps=medicine.minimum_price_bps,
        maximum_price_bps=medicine.maximum_price_bps,
    )
    assert low.buyer_total == 600 and low.low_price_surcharge == 100
    high = quote_market_tax(
        1_000,
        2_000,
        minimum_price_bps=medicine.minimum_price_bps,
        maximum_price_bps=medicine.maximum_price_bps,
    )
    assert high.high_price_tax == 200
    assert high.seller_proceeds == 1_656
    print("market price policy tests passed")


if __name__ == "__main__":
    main()
