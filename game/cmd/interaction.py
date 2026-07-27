"""正式命令层共享的分页与动作编排规则。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import ceil
from typing import Generic, Sequence, TypeVar

from message import Action


DEFAULT_PAGE_SIZE = 50

T = TypeVar("T")


@dataclass(frozen=True)
class PageSlice(Generic[T]):
    """一个已校验的紧凑列表分页。"""

    values: tuple[T, ...]
    number: int
    pages: int
    total: int
    start: int

    @property
    def label(self) -> str:
        return f"{self.number}/{self.pages}"


def parse_page_number(value: object, *, default: int = 1) -> int:
    """将命令页码统一解析为正整数。"""

    text = "" if value is None else str(value).strip()
    try:
        page = int(text) if text else int(default)
    except (TypeError, ValueError) as exc:
        raise ValueError("页码必须是正整数") from exc
    if page < 1:
        raise ValueError("页码必须是正整数")
    return page


def paginate(
    values: Sequence[T],
    page: int,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> PageSlice[T]:
    """返回稳定页面切片，空列表仍保留第 1 页。"""

    if page_size < 1:
        raise ValueError("每页数量必须大于 0")
    number = parse_page_number(page)
    total = len(values)
    pages = max(1, ceil(total / page_size))
    if number > pages:
        raise ValueError(f"页码超出范围，当前共 {pages} 页")
    start = (number - 1) * page_size
    return PageSlice(
        tuple(values[start : start + page_size]),
        number,
        pages,
        total,
        start,
    )


def pagination_actions(
    command: str,
    page: PageSlice[object],
    *,
    back: Action | None = None,
) -> tuple[Action, ...]:
    """按“上一页、下一页、返回”生成辅助导航。"""

    base = str(command or "").strip()
    if not base:
        raise ValueError("分页命令不能为空")
    actions: list[Action] = []
    if page.number > 1:
        actions.append(
            Action(
                "page.previous",
                "上一页",
                f"{base} {page.number - 1}",
                style="secondary",
            )
        )
    if page.number < page.pages:
        actions.append(
            Action(
                "page.next",
                "下一页",
                f"{base} {page.number + 1}",
                style="secondary",
            )
        )
    if back is not None:
        actions.append(replace(back, style="secondary"))
    return tuple(actions)


def confirmation_actions(
    confirm: Action,
    *,
    back_command: str,
    back_label: str = "返回",
    back_id: str = "confirmation.back",
) -> tuple[Action, ...]:
    """确认页统一以主操作开头，返回入口收尾。"""

    return (
        replace(confirm, style="primary"),
        Action(
            back_id,
            back_label,
            str(back_command or "").strip(),
            style="secondary",
        ),
    )


def ordered_actions(actions: Sequence[Action]) -> tuple[Action, ...]:
    """主操作优先，辅助、返回与危险入口置后。"""

    values = tuple(actions)
    return tuple(action for action in values if action.style == "primary") + tuple(
        action for action in values if action.style == "secondary"
    )


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "PageSlice",
    "confirmation_actions",
    "ordered_actions",
    "paginate",
    "pagination_actions",
    "parse_page_number",
]
