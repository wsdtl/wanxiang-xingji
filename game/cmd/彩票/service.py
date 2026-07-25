"""彩票购买、轮次状态和个人中奖记录展示。"""

from __future__ import annotations

import asyncio

from game.app import CurrentCharacterResult, current_game_services
from game.content.catalog.economy import LOTTERY_TICKET_PRICE
from game.content.presentation import COVENANT_TREASURY_NAME
from game.rules.lottery import pool_breakdown
from message import Action, M

from ..command_helpers import command_time
from ..reply import send_command_failure, send_game_reply


async def lottery(current: CurrentCharacterResult) -> None:
    character = current.character if current.status == "ok" else None
    if character is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    services = current_game_services()
    logical_time = command_time()
    try:
        view = await asyncio.to_thread(
            services.lottery.status,
            character.id,
            logical_time=logical_time,
        )
        builder = M.document().section("彩票系统", icon="trade")
        if view.current_ticket is not None:
            builder.line("我的号码：" + view.current_ticket.number)
        else:
            builder.line(f"第 {view.signup_round_day} 期尚未购票")
        ticket_count = len(view.current_round.tickets) if view.current_round else 0
        base_pool, subsidy, estimated_pool = pool_breakdown(
            view.tax_balance,
            ticket_count,
        )
        builder.row(
            ("开奖", f"{view.signup_round_day} 21:00"),
            ("已售", f"{ticket_count} 张"),
        )
        builder.row(
            ("单价", LOTTERY_TICKET_PRICE),
            ("单人上限", "1 张"),
        )
        builder.row(
            (COVENANT_TREASURY_NAME, view.tax_balance),
            ("基础奖池", base_pool),
        )
        builder.row(
            ("补贴预计", subsidy),
            ("开奖池预计", estimated_pool),
        )
        builder.note("至少 2 人开奖；不足自动退票，按开奖号环形距离排名")
        _append_due_result(builder, view)
        if view.current_ticket is None:
            builder.action(
                Action(
                    "lottery.purchase",
                    "购票",
                    "购票 ",
                    behavior="fill",
                )
            )
        builder.action(
            Action(
                "lottery.history",
                "中奖记录",
                "中奖记录",
                style="secondary",
            )
        )
        await send_game_reply(builder.build())
    except (KeyError, TypeError, ValueError) as exc:
        await send_game_reply(
            _failure(str(exc))
        )
    except Exception as exc:
        await send_command_failure(
            "彩票命令失败",
            character.id,
            exc,
            _failure("当前操作没有完成，请稍后重试"),
        )


async def purchase(message: str, current: CurrentCharacterResult) -> None:
    character = current.character if current.status == "ok" else None
    if character is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    parts = str(message or "").strip().split()
    if not parts:
        await send_game_reply(
            _failure(
                "发送 购票 123456 选择六位号码",
                Action("lottery.number", "填写号码", "购票 ", behavior="fill"),
            )
        )
        return
    if len(parts) != 1:
        await send_game_reply(_failure("每人每期只能购买一张彩票，请只填写一个号码"))
        return
    try:
        result = await asyncio.to_thread(
            current_game_services().lottery.purchase,
            character.id,
            character.name,
            parts[0],
            logical_time=command_time(),
        )
        await send_game_reply(
            M.document().section("购票完成", icon="trade").line(result).build()
        )
    except (KeyError, TypeError, ValueError) as exc:
        await send_game_reply(_failure(str(exc)))
    except Exception as exc:
        await send_command_failure(
            "购票失败",
            character.id,
            exc,
            _failure("当前操作没有完成，请稍后重试"),
        )


async def winner_history(current: CurrentCharacterResult) -> None:
    character = current.character if current.status == "ok" else None
    if character is None:
        await send_game_reply(_failure("当前没有可用角色"))
        return
    try:
        values = await asyncio.to_thread(
            current_game_services().lottery.winner_history,
            character.id,
        )
        builder = M.document().section("中奖记录", icon="trade")
        if not values:
            builder.line("暂无中奖记录")
        for index, (round_day, winner) in enumerate(values, start=1):
            builder.item(
                index,
                f"{round_day} | {winner.tier} | {winner.number} | {winner.amount}",
            )
        await send_game_reply(builder.build())
    except Exception as exc:
        await send_command_failure(
            "中奖记录读取失败",
            character.id,
            exc,
            _failure("当前操作没有完成，请稍后重试"),
        )


def _append_due_result(builder, view) -> None:
    round_value = view.due_round
    if round_value is None:
        builder.section("最近开奖", icon="system").line("最近一期暂无购票记录")
        return
    builder.section("最近开奖", icon="system")
    if round_value.status == "pending":
        builder.line("本期已到开奖窗口，后台开奖任务正在整理")
        return
    if round_value.status == "skipped":
        builder.line(f"第 {round_value.round_day} 期未开奖：{round_value.reason or '条件不足'}")
        return
    builder.row(
        ("期号", round_value.round_day),
        ("开奖号", round_value.winning_number),
        ("支出", round_value.payout_amount),
    )
    if view.due_winner is not None:
        winner = view.due_winner
        builder.line(
            f"你中得 {winner.tier} | 号码 {winner.number} | 差距 {winner.distance} | 奖金 {winner.amount}"
        )
    elif view.due_ticket is not None:
        builder.line("本期未中 | 号码 " + view.due_ticket.number)
    else:
        builder.line("你未参与最近一期")
    for index, winner in enumerate(round_value.winners[:5], start=1):
        builder.item(
            index,
            f"{winner.tier} {winner.character_name} | 差 {winner.distance} | {winner.amount}",
        )


def _failure(message: str, recovery: Action | None = None):
    builder = M.document().section("彩票系统", icon="notice").line(message)
    if recovery is not None:
        builder.action(recovery)
    return builder.build()


__all__ = ["lottery", "purchase", "winner_history"]
