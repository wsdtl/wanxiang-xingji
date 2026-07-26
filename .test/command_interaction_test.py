"""命令分页、仅回收确认、恢复与按钮顺序的横向契约。"""

from __future__ import annotations

import ast
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.cmd import reply as reply_service  # noqa: E402
from game.cmd.interaction import (  # noqa: E402
    DEFAULT_PAGE_SIZE,
    confirmation_actions,
    ordered_actions,
    paginate,
    pagination_actions,
    parse_page_number,
)
from message import Action, M  # noqa: E402


def main() -> None:
    assert DEFAULT_PAGE_SIZE == 50
    assert parse_page_number("") == 1
    assert parse_page_number("2") == 2
    for invalid in ("x", 0, -1):
        try:
            parse_page_number(invalid)
        except ValueError as exc:
            assert str(exc) == "页码必须是正整数"
        else:
            raise AssertionError(f"非法页码未被拒绝: {invalid}")

    values = tuple(range(101))
    first = paginate(values, 1)
    middle = paginate(values, 2)
    last = paginate(values, 3)
    assert len(first.values) == 50
    assert len(middle.values) == 50
    assert last.values == (100,)
    assert last.label == "3/3"
    assert last.total == 101

    navigation = pagination_actions(
        "测试列表 筛选",
        middle,
        back=Action("page.back", "返回", "测试列表"),
    )
    assert tuple(action.label for action in navigation) == ("上一页", "下一页", "返回")
    assert tuple(action.data for action in navigation) == (
        "测试列表 筛选 1",
        "测试列表 筛选 3",
        "测试列表",
    )
    assert all(action.style == "secondary" for action in navigation)

    confirmation = confirmation_actions(
        Action("confirm", "确认执行", "confirm command", style="secondary"),
        back_command="返回预览",
    )
    assert tuple(action.label for action in confirmation) == ("确认执行", "返回")
    assert tuple(action.style for action in confirmation) == ("primary", "secondary")

    confirmation_callers = set()
    command_root = ROOT / "game" / "cmd"
    for source_path in command_root.rglob("*.py"):
        if source_path.name == "interaction.py":
            continue
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "confirmation_actions"
            for node in ast.walk(tree)
        ):
            confirmation_callers.add(source_path.relative_to(command_root).as_posix())
    assert confirmation_callers == {"回收/service.py"}
    _assert_action_command_semantics(command_root)

    mixed = (
        Action("secondary.first", "辅助一", "secondary 1", style="secondary"),
        Action("primary.first", "主操作一", "primary 1"),
        Action("secondary.second", "辅助二", "secondary 2", style="secondary"),
        Action("primary.second", "主操作二", "primary 2"),
    )
    assert tuple(action.id for action in ordered_actions(mixed)) == (
        "primary.first",
        "primary.second",
        "secondary.first",
        "secondary.second",
    )

    failure = M.document().section("读取失败", icon="notice").line("请稍后重试").build()
    recovered = reply_service._with_retry_action(failure, "地图")
    assert recovered.document.actions[0].id == "game.retry"
    assert recovered.document.actions[0].data == "地图"
    automatic = reply_service._with_temporary_failure_retry(failure, "地图")
    assert automatic.document.actions[0].data == "地图"
    validation = M.document().section("参数错误", icon="notice").line("页码必须是正整数").build()
    assert not reply_service._with_temporary_failure_retry(
        validation,
        "纳戒 x",
    ).document.actions

    normalized = reply_service._normalize_game_reply(
        M.document().section("顺序", icon="system").line("验证").actions(mixed).build()
    )
    assert tuple(action.id for action in normalized.document.actions) == (
        "primary.first",
        "primary.second",
        "secondary.first",
        "secondary.second",
    )
    print("command interaction tests passed")


def _assert_action_command_semantics(command_root: Path) -> None:
    violations: list[str] = []
    for source_path in command_root.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Action"
            ):
                continue
            behavior = _literal_keyword(node, "behavior") or "callback"
            if behavior not in {"callback", "send", "fill"}:
                continue
            data_node = node.args[2] if len(node.args) >= 3 else _keyword_node(node, "data")
            trailing_space = _literal_trailing_space(data_node)
            location = f"{source_path.relative_to(command_root)}:{node.lineno}"
            if behavior == "send":
                violations.append(f"{location} send 在群聊不会立即执行，请使用 callback")
            if behavior == "callback" and trailing_space:
                violations.append(f"{location} callback 保留了参数空位")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            action_behavior = _literal_keyword(node, "action_behavior")
            if action_behavior == "send":
                location = f"{source_path.relative_to(command_root)}:{node.lineno}"
                violations.append(f"{location} action_behavior 不能使用 send")
    assert not violations, "按钮命令语义不一致:\n" + "\n".join(violations)


def _literal_keyword(node: ast.Call, name: str) -> str | None:
    value = _keyword_node(node, name)
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


def _keyword_node(node: ast.Call, name: str) -> ast.expr | None:
    return next((keyword.value for keyword in node.keywords if keyword.arg == name), None)


def _literal_trailing_space(node: ast.expr | None) -> bool | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return bool(node.value) and node.value[-1].isspace()
    if isinstance(node, ast.JoinedStr):
        if not node.values:
            return False
        suffix = node.values[-1]
        if isinstance(suffix, ast.Constant) and isinstance(suffix.value, str):
            return bool(suffix.value) and suffix.value[-1].isspace()
        return False
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literal_trailing_space(node.right)
    return None


if __name__ == "__main__":
    main()
