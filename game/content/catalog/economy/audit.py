"""固定物品市场政策与抽奖期望值的快速审计。"""

from __future__ import annotations

from dataclasses import dataclass

from game.content.catalog.item.exchange import (
    EQUIPMENT_SET_BLUEPRINT_COMPONENT_ID,
    EXCHANGE_MATERIAL_ITEM_ID,
    EquipmentSetBlueprintItemComponent,
)
from game.content.catalog.item.trade import (
    ITEM_RECYCLE_COMPONENT_ID,
    ItemRecycleYield,
    StackItemRecycleYield,
)
from game.core.gameplay import ItemAssetKind

from .exchange import (
    EQUIPMENT_SET_BLUEPRINT_PRICE,
    EXCHANGE_MATERIAL_REFERENCE_VALUE,
)
from .market_items import MARKET_ITEM_POLICIES


@dataclass(frozen=True)
class MarketPriceAuditReport:
    policy_count: int
    draw_base_expected_value: float
    draw_ticket_reference_price: int
    blueprint_count: int = 0
    party_trophy_conversion_count: int = 0


def audit_market_prices(
    item_catalog,
    draw_content,
    equipment_catalog=None,
    *,
    market_item_policies=None,
    expected_party_trophy_ids: frozenset[str] | None = None,
) -> MarketPriceAuditReport:
    policies = market_item_policies or MARKET_ITEM_POLICIES
    required = {
        str(definition.id)
        for definition in (
            item_catalog.require(item_id) for item_id in item_catalog.definitions.ids()
        )
        if definition.tags.has("storage.special")
        or definition.tags.has("storage.inscription")
    }
    configured = set(policies)
    missing = sorted(required - configured)
    extra = sorted(configured - required)
    if missing:
        raise ValueError(f"可交易物品缺少市场参考价：{missing[0]}")
    if extra:
        raise ValueError(f"市场参考价引用了不可交易物品：{extra[0]}")

    for item_id, policy in policies.items():
        definition = item_catalog.require(item_id)
        maximum = (
            1 if definition.asset_kind is ItemAssetKind.INSTANCE else definition.stack_limit
        )
        if maximum is None or policy.maximum_quantity > maximum:
            raise ValueError(f"市场最大交易数量超过物品堆叠上限：{item_id}")

    _require_monotonic(
        "血气药",
        (
            "item.consumable.small_health_medicine",
            "item.consumable.medium_health_medicine",
            "item.consumable.large_health_medicine",
        ),
        policies,
    )
    _require_monotonic(
        "灵力药",
        (
            "item.consumable.small_spirit_medicine",
            "item.consumable.medium_spirit_medicine",
            "item.consumable.large_spirit_medicine",
        ),
        policies,
    )

    group = draw_content.loot_table.groups[0]
    total_weight = sum(entry.weight for entry in group.entries)
    weighted_value = 0
    for entry in group.entries:
        quantity = entry.minimum_quantity
        if entry.minimum_quantity != entry.maximum_quantity:
            raise ValueError(f"抽奖奖励数量不是固定值：{entry.id}")
        if entry.award_id in {"draw_reward.currency.low", "draw_reward.currency.mid"}:
            value = quantity
        else:
            policy = policies.get(str(entry.award_id))
            if policy is None:
                raise ValueError(f"抽奖奖励缺少市场参考价：{entry.award_id}")
            value = policy.unit_reference_price * quantity
        weighted_value += entry.weight * value
    expected = weighted_value / total_weight
    ticket_price = policies["item.draw.ticket"].unit_reference_price
    if not expected <= ticket_price <= expected * 2:
        raise ValueError("抽奖签参考价偏离基础奖池期望值")

    blueprint_targets: dict[str, int] = {}
    blueprint_ids = set()
    party_conversions = 0
    party_trophy_ids = set()
    for definition in item_catalog.definitions:
        blueprint = definition.components.get(EQUIPMENT_SET_BLUEPRINT_COMPONENT_ID)
        if isinstance(blueprint, EquipmentSetBlueprintItemComponent):
            blueprint_ids.add(str(definition.id))
            blueprint_targets[str(blueprint.target_set_id)] = (
                blueprint_targets.get(str(blueprint.target_set_id), 0) + 1
            )
            if ITEM_RECYCLE_COMPONENT_ID in definition.components:
                raise ValueError(f"套装图纸不能被系统回收：{definition.id}")
        recycle = definition.components.get(ITEM_RECYCLE_COMPONENT_ID)
        if isinstance(recycle, StackItemRecycleYield):
            if not definition.tags.has("trophy.party_boss"):
                raise ValueError(f"非组队首领战利品不能回收为物品：{definition.id}")
            if recycle.definition_id != EXCHANGE_MATERIAL_ITEM_ID:
                raise ValueError(f"组队首领战利品必须回收为定相尘：{definition.id}")
            party_conversions += 1
            party_trophy_ids.add(str(definition.id))
        elif definition.tags.has("trophy.party_boss"):
            raise ValueError(f"组队首领战利品缺少定相尘产出：{definition.id}")
        elif recycle is not None and not isinstance(recycle, ItemRecycleYield):
            raise TypeError(f"物品回收组件类型无效：{definition.id}")
    if expected_party_trophy_ids is not None and party_trophy_ids != set(
        expected_party_trophy_ids
    ):
        raise ValueError("组队首领奖励绑定与定相尘战利品目录不一致")
    if blueprint_ids & set(draw_content.special_item_ids):
        raise ValueError("套装图纸不能进入特殊物品抽奖池")
    if equipment_catalog is not None:
        expected_sets = set(equipment_catalog.sets.ids())
        if set(blueprint_targets) != expected_sets or any(
            amount != 1 for amount in blueprint_targets.values()
        ):
            raise ValueError("每个正式套装必须恰好对应一张图纸")
    material_policy = policies[EXCHANGE_MATERIAL_ITEM_ID]
    if material_policy.unit_reference_price != EXCHANGE_MATERIAL_REFERENCE_VALUE:
        raise ValueError("定相尘市场参考价与兑换价值锚不一致")
    for blueprint_id in blueprint_ids:
        if (
            policies[blueprint_id].unit_reference_price
            != EQUIPMENT_SET_BLUEPRINT_PRICE * EXCHANGE_MATERIAL_REFERENCE_VALUE
        ):
            raise ValueError(f"套装图纸参考价与兑换成本不一致：{blueprint_id}")
    return MarketPriceAuditReport(
        len(configured),
        expected,
        ticket_price,
        len(blueprint_ids),
        party_conversions,
    )


def _require_monotonic(label: str, item_ids: tuple[str, ...], policies) -> None:
    prices = tuple(policies[item_id].unit_reference_price for item_id in item_ids)
    if any(left >= right for left, right in zip(prices, prices[1:])):
        raise ValueError(f"{label}参考价必须随档位严格递增")


__all__ = ["MarketPriceAuditReport", "audit_market_prices"]
