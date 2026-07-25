"""QQ 协议测试组件的离线结构测试。"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from 组件测试.QQ协议测试 import COMMAND, build_test_keyboard, build_test_menu, test_image_bytes
from launch.adapter.qq.diagnostics import safe_payload_summary
from launch.adapter.qq.handler import QqEventHandler
from launch.adapter.qq.keyboard import validate_keyboard
from launch.adapter.qq.render import render_qq_message
from message import DocumentMessage


def main() -> None:
    keyboard = build_test_keyboard()
    buttons = [button for row in keyboard["content"]["rows"] for button in row["buttons"]]
    actions = [button["action"] for button in buttons]

    assert len(buttons) == 7
    assert len({button["id"] for button in buttons}) == len(buttons)
    assert all(button["id"] for button in buttons)
    assert any(action["type"] == 1 for action in actions)
    assert any(action["type"] == 2 and action["enter"] is True for action in actions)
    assert any(action["type"] == 2 and action["enter"] is False for action in actions)
    assert any(action["type"] == 2 and action["reply"] is True for action in actions)
    assert all(str(action["data"]).startswith(COMMAND) for action in actions)

    menu = build_test_menu()
    assert isinstance(menu, DocumentMessage)
    rendered_menu = render_qq_message(menu)
    assert rendered_menu["kind"] == "markdown"
    assert rendered_menu["keyboard"] == keyboard
    assert validate_keyboard(keyboard) == keyboard
    invalid_keyboard = build_test_keyboard()
    invalid_keyboard["content"]["rows"][0]["buttons"][0].pop("id")
    try:
        validate_keyboard(invalid_keyboard)
        raise AssertionError("缺失按钮 id 必须被拒绝")
    except ValueError as exc:
        assert "稳定 id" in str(exc)
    assert test_image_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert COMMAND in QqEventHandler.exact_rules

    payload = {
        "t": "INTERACTION_CREATE",
        "d": {
            "group_openid": "sensitive-group",
            "data": {"nested": {"button_data": f"{COMMAND} 回调", "user_id": "sensitive-user"}},
        },
    }
    summary = safe_payload_summary(payload)
    assert "$.d.data.nested.button_data" in summary["schema"]
    assert summary["button_data"] == f"{COMMAND} 回调"
    assert "sensitive-user" not in str(summary)
    assert "sensitive-group" not in str(summary)

    print("QQ protocol component test passed")


if __name__ == "__main__":
    main()
