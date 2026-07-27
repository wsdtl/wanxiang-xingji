"""抽奖命令调用、共用演出与结果展示。"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from game.app import CurrentCharacterResult, current_game_services
from game.content import (
    BREAKTHROUGH_TOKEN_ITEM_ID,
    DRAW_CATALOG_CONTENT,
    DRAW_BREAKTHROUGH_GUARANTEE_SLOT_ID,
    DRAW_BREAKTHROUGH_PITY_THRESHOLD,
    DRAW_BREAKTHROUGH_WEIGHT,
    DRAW_CURRENCY_COST_PER_ROLL,
    DRAW_HIGH_WEIGHT,
    DRAW_LOW_WEIGHT,
    DRAW_MID_PITY_THRESHOLD,
    DRAW_MID_WEIGHT,
    DRAW_REWARD_LOW_CURRENCY_ID,
    DRAW_REWARD_MID_CURRENCY_ID,
    DRAW_TIER_HIGH,
    DRAW_TIER_BREAKTHROUGH,
    DRAW_TIER_LOW,
    DRAW_TIER_MID,
    DRAW_TICKET_ITEM_ID,
    PRIMARY_CURRENCY_ID,
)
from game.features.draw import DrawHistoryRecord, DrawOperationResult
from launch.adapter import current_message_context
from launch.paths import public_url, static_path
from message import Action, DocumentMessage, M

from ..command_helpers import command_time
from ..reply import send_command_failure, send_game_reply


DRAW_ANIMATION_VERSION = "20260720"
DRAW_ANIMATION_FILES = {
    (1, DRAW_TIER_LOW): "single-low.gif",
    (1, DRAW_TIER_MID): "single-mid.gif",
    (1, DRAW_TIER_HIGH): "single-high.gif",
    (1, DRAW_TIER_BREAKTHROUGH): "single-high.gif",
    (10, DRAW_TIER_LOW): "batch-mid.gif",
    (10, DRAW_TIER_MID): "batch-mid.gif",
    (10, DRAW_TIER_HIGH): "batch-high.gif",
    (10, DRAW_TIER_BREAKTHROUGH): "batch-high.gif",
}
TIER_LABELS = {
    DRAW_TIER_LOW: "常规",
    DRAW_TIER_MID: "珍稀",
    DRAW_TIER_HIGH: "特殊",
    DRAW_TIER_BREAKTHROUGH: "破境",
}


async def draw(current: CurrentCharacterResult, rolls: int) -> None:
    character = current.character if current.status == "ok" else None
    if character is None:
        await send_game_reply(
            _failure(
                "当前没有可用角色",
                Action("draw.character", "查看角色", "我的角色"),
            )
        )
        return
    context = current_message_context()
    if context is None:
        raise RuntimeError("抽奖命令缺少消息上下文")
    operation_id = f"{context.identity.evidence_id}:draw:{rolls}"
    try:
        services = current_game_services()
        result = await asyncio.to_thread(
            services.draw.draw,
            character.id,
            operation_id,
            rolls,
            logical_time=command_time(),
        )
        view = services.world_view(current.character_world)
        await send_game_reply(_result_message(result, view.projector, rolls))
    except Exception as exc:
        await send_command_failure(
            "抽奖命令失败",
            character.id,
            exc,
            _failure(
                "当前操作没有完成，请稍后重试",
                Action(
                    "draw.retry",
                    "再次抽取",
                    "抽奖" if rolls == 1 else "十连抽奖",
                ),
            ),
        )


async def pool(current: CurrentCharacterResult) -> None:
    character = current.character if current.status == "ok" else None
    if character is None:
        await send_game_reply(
            _failure(
                "当前没有可用角色",
                Action("draw.character", "查看角色", "我的角色"),
            )
        )
        return
    try:
        services = current_game_services()
        status = await asyncio.to_thread(services.draw.status, character.id, history_limit=0)
        projector = services.world_view(current.character_world).projector
        currency_name = projector.name(PRIMARY_CURRENCY_ID)
        high_open = bool(DRAW_CATALOG_CONTENT.special_item_ids)
        low_weight = DRAW_LOW_WEIGHT if high_open else DRAW_LOW_WEIGHT + DRAW_HIGH_WEIGHT
        builder = (
            M.document()
            .section("抽奖奖池", icon="reward")
            .line("每张抽奖签封存一次未定结果，使用后由界门正式显化。")
            .row(
                ("抽奖签", f"{status.ticket_count} 张"),
                (currency_name, status.currency_balance),
            )
            .row(
                ("珍稀", f"{status.pity_count}/{DRAW_MID_PITY_THRESHOLD}"),
                ("破境", f"{_breakthrough_pity(status)}/{DRAW_BREAKTHROUGH_PITY_THRESHOLD}"),
            )
            .line(f"常规 {low_weight / 1000:.0f}% | {currency_name}或基础恢复药")
            .line(f"珍稀 {DRAW_MID_WEIGHT / 1000:.0f}% | {currency_name}或进阶恢复药")
        )
        if high_open:
            names = "、".join(
                projector.name(value)
                for value in sorted(DRAW_CATALOG_CONTENT.special_item_ids)
            )
            builder.line(f"特殊 {DRAW_HIGH_WEIGHT / 1000:.0f}% | {names}")
        else:
            builder.line("特殊物品尚未开放，对应权重暂时回流常规档")
        builder.line(
            f"破境 {DRAW_BREAKTHROUGH_WEIGHT / 1000:.0f}% | "
            f"{projector.name(BREAKTHROUGH_TOKEN_ITEM_ID)}"
        )
        builder.note(
            f"每 {DRAW_MID_PITY_THRESHOLD} 抽至少出现一次珍稀或更高档",
            f"连续 {DRAW_BREAKTHROUGH_PITY_THRESHOLD} 抽未获得破境凭证时额外保底 1 枚",
            f"单抽和十连优先消耗{projector.name(DRAW_TICKET_ITEM_ID)}，每缺 1 张支付 "
            f"{DRAW_CURRENCY_COST_PER_ROLL} {currency_name}",
            f"十连最多支付 {10 * DRAW_CURRENCY_COST_PER_ROLL} {currency_name}；"
            f"50 抽全货币为 {50 * DRAW_CURRENCY_COST_PER_ROLL} {currency_name}，不设十连折扣",
        ).actions(_actions())
        await send_game_reply(builder.build())
    except Exception as exc:
        await send_command_failure(
            "抽奖奖池查询失败",
            character.id,
            exc,
            _failure(
                "当前没有读取到奖池状态，请稍后重试",
                Action("draw.pool.retry", "重试", "抽奖奖池"),
            ),
        )


async def history(current: CurrentCharacterResult) -> None:
    character = current.character if current.status == "ok" else None
    if character is None:
        await send_game_reply(
            _failure(
                "当前没有可用角色",
                Action("draw.character", "查看角色", "我的角色"),
            )
        )
        return
    try:
        services = current_game_services()
        status = await asyncio.to_thread(services.draw.status, character.id, history_limit=10)
        projector = services.world_view(current.character_world).projector
        builder = M.document().section("抽奖·显化记录", icon="history")
        if not status.records:
            builder.line("暂无抽奖记录")
        for index, record in enumerate(status.records, start=1):
            tier = _highest_tier(record)
            builder.item(
                index,
                f"{record.receipt.rolls} 抽 | {TIER_LABELS[tier]} | {_summary(record, projector)}",
            )
        builder.actions(_actions())
        await send_game_reply(builder.build())
    except Exception as exc:
        await send_command_failure(
            "抽奖记录查询失败",
            character.id,
            exc,
            _failure(
                "当前没有读取到抽奖记录，请稍后重试",
                Action("draw.history.retry", "重试", "抽奖记录"),
            ),
        )


def _result_message(result: DrawOperationResult, projector, rolls: int) -> DocumentMessage:
    if result.status == "insufficient":
        currency_name = projector.name(PRIMARY_CURRENCY_ID)
        return (
            M.document()
            .section("抽奖", icon="notice")
            .line(result.failure_message)
            .row(
                ("抽奖签", f"{result.ticket_count} 张"),
                (f"可用{currency_name}", result.currency_available),
                ("需要", result.currency_required),
            )
            .note("本次没有扣除抽奖签、货币，也没有推进保底")
            .action(Action("draw.explore", "前往探险", "探险", style="secondary"))
            .build()
        )
    if result.status not in {"drawn", "replayed"} or result.record is None:
        return _failure(
            result.failure_message or "抽奖没有完成",
            Action("draw.pool", "查看奖池", "抽奖奖池"),
        )

    record = result.record
    tier = _highest_tier(record)
    builder = M.document()
    animation = _animation_url(rolls, tier)
    if animation:
        builder.image(animation, alt="抽奖演出", width=360, height=203)
    builder.section("抽奖·显化结果", icon="reward").row(
        ("消耗", _payment_text(record, projector)),
        ("最高", TIER_LABELS[tier]),
    )
    for name, quantity in _reward_lines(record, projector):
        builder.line(f"获得 {name} x{quantity}")
    builder.row(
        ("余签", f"{result.ticket_count} 张"),
        (projector.name(PRIMARY_CURRENCY_ID), result.currency_available),
    ).row(
        ("珍稀", f"{result.pity_count}/{DRAW_MID_PITY_THRESHOLD}"),
        ("破境", f"{_breakthrough_pity(result)}/{DRAW_BREAKTHROUGH_PITY_THRESHOLD}"),
    ).actions(_actions())
    return builder.build()


def _reward_lines(record: DrawHistoryRecord, projector) -> tuple[tuple[str, int], ...]:
    totals: dict[str, int] = defaultdict(int)
    for award in record.receipt.awards:
        key = (
            PRIMARY_CURRENCY_ID
            if award.award_id in {
                DRAW_REWARD_LOW_CURRENCY_ID,
                DRAW_REWARD_MID_CURRENCY_ID,
            }
            else str(award.award_id)
        )
        totals[key] += award.quantity
    return tuple((projector.name(key), quantity) for key, quantity in totals.items())


def _summary(record: DrawHistoryRecord, projector) -> str:
    lines = _reward_lines(record, projector)
    return "、".join(f"{name} x{quantity}" for name, quantity in lines[:3])


def _payment_text(record: DrawHistoryRecord, projector) -> str:
    if record.tickets_spent is None or record.currency_spent is None:
        return f"{projector.name(DRAW_TICKET_ITEM_ID)} {record.receipt.rolls} 张"
    values = []
    if record.tickets_spent:
        values.append(f"{projector.name(DRAW_TICKET_ITEM_ID)} {record.tickets_spent} 张")
    if record.currency_spent:
        values.append(f"{projector.name(PRIMARY_CURRENCY_ID)} {record.currency_spent}")
    return " + ".join(values)


def _highest_tier(record: DrawHistoryRecord) -> str:
    ranks = {
        DRAW_TIER_LOW: 0,
        DRAW_TIER_MID: 1,
        DRAW_TIER_HIGH: 2,
        DRAW_TIER_BREAKTHROUGH: 3,
    }
    return max(
        (
            DRAW_CATALOG_CONTENT.entry_tiers.get(str(value.entry_id), DRAW_TIER_LOW)
            for value in record.receipt.awards
        ),
        key=ranks.__getitem__,
        default=DRAW_TIER_LOW,
    )


def _breakthrough_pity(result) -> int:
    return int(result.guarantee_counts.get(DRAW_BREAKTHROUGH_GUARANTEE_SLOT_ID, 0))


def _animation_url(rolls: int, tier: str) -> str:
    filename = DRAW_ANIMATION_FILES.get((rolls, tier))
    if not filename or not static_path("draw", filename).is_file():
        return ""
    return f"{public_url('static', 'draw', filename)}?v={DRAW_ANIMATION_VERSION}"


def _actions() -> tuple[Action, ...]:
    return (
        Action("draw-once", "单抽", "抽奖", behavior="callback"),
        Action("draw-ten", "十连", "十连抽奖", behavior="callback"),
        Action("draw-pool", "奖池", "抽奖奖池", behavior="callback", style="secondary"),
    )


def _failure(message: str, recovery: Action) -> DocumentMessage:
    return (
        M.document()
        .section("抽奖", icon="notice")
        .line(message)
        .action(recovery)
        .build()
    )


__all__ = ["draw", "history", "pool"]
