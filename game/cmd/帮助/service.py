"""从命令帮助注册表生成协议中立的玩家消息。"""

from __future__ import annotations

from game.content.presentation import (
    COVENANT_MARKET_NAME,
    COVENANT_MEMBER_NAME,
    COVENANT_NAME,
    COVENANT_RECYCLING_NAME,
    COVENANT_TREASURY_NAME,
    GAME_NAME,
)
from launch.paths import public_url, static_url
from message import Action, DocumentMessage, M

from ..help_registry import CommandHelpEntry, help_registry
from ..reply import send_game_reply


async def show_help(query: str = "") -> None:
    """按空查询、分类或命令三级展示帮助。"""

    normalized = " ".join(str(query or "").split())
    if not normalized:
        message = _home_message()
    elif normalized in help_registry.categories():
        message = _category_message(normalized)
    elif entry := help_registry.find(normalized):
        message = _detail_message(entry)
    else:
        message = _not_found_message(normalized)
    await send_game_reply(message)


async def show_covenant() -> None:
    """展示不依赖角色状态的归航公约背景摘要。"""

    await send_game_reply(
        M.document()
        .header(GAME_NAME)
        .section(COVENANT_NAME, icon="world")
        .line("它不统治诸界，只保证你跨越世界后仍被承认为同一个人。")
        .row(("成员", COVENANT_MEMBER_NAME), ("公共资金", COVENANT_TREASURY_NAME))
        .section("公约职责")
        .line(f"身份互认 · 资产确权 · {COVENANT_MARKET_NAME}清算")
        .line(f"{COVENANT_RECYCLING_NAME} · 灾厄征召 · 公共行纪")
        .note("建立唯一化身时自动登记；不增加第二套成长，也不占用玩家共同体归属。")
        .build()
    )


def _home_message() -> DocumentMessage:
    builder = (
        M.document()
        .header(GAME_NAME)
        .section("帮助", icon="system")
        .line("按分类查看当前已经开放的命令。")
    )
    categories = help_registry.categories()
    for start in range(0, len(categories), 3):
        row = categories[start : start + 3]
        parts: list[object] = []
        for index, category in enumerate(row):
            if index:
                parts.append("　")
            parts.append(M.command(category, f"帮助 {category}"))
        builder.line(*parts)
    builder.section("游戏主页").line(
        M.link(
            "世界设定 · 诸界档案 · 游玩手册",
            public_url(static_url("main", "index.html")),
        )
    )
    return builder.build()


def _category_message(category: str) -> DocumentMessage:
    builder = M.document().header(GAME_NAME).section(category, icon="system")
    for entry in help_registry.in_category(category):
        builder.line(
            M.command(entry.command, f"帮助 {entry.command}"),
            " - ",
            entry.spec.summary,
        )
    return builder.actions((_home_action(),)).build()


def _detail_message(entry: CommandHelpEntry) -> DocumentMessage:
    builder = (
        M.document()
        .header(GAME_NAME)
        .section(entry.command, icon="system")
        .line(entry.spec.summary)
        .section("写法")
    )
    for usage in entry.spec.usage:
        builder.line(usage)
    if entry.spec.side_effect:
        builder.section("影响").line(entry.spec.side_effect)
    return builder.actions(
        (
            Action(
                "help.execute",
                "发送命令",
                entry.command,
                behavior="callback",
            ),
            Action(
                "help.category",
                "返回分类",
                f"帮助 {entry.spec.category}",
                behavior="callback",
                style="secondary",
            ),
        )
    ).build()


def _not_found_message(query: str) -> DocumentMessage:
    builder = (
        M.document()
        .header(GAME_NAME)
        .section("没有找到帮助", icon="notice")
        .line(f"未登记分类或命令: {query}")
        .section("可用分类")
    )
    for category in help_registry.categories():
        builder.line(M.command(category, f"帮助 {category}"))
    return builder.actions((_home_action(),)).build()


def _home_action() -> Action:
    return Action(
        "help.home",
        "帮助首页",
        "帮助",
        behavior="callback",
        style="secondary",
    )


__all__ = ["show_covenant", "show_help"]
