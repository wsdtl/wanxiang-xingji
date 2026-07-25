"""Web 游戏台协议、认证、消息流水和本地执行验收。"""

from __future__ import annotations

import sys
import time
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from game.cmd.web.console import service
from game.cmd.web.models import ConsoleFlowRecord
from game.cmd.web.presentation import render_message_html
from game.core.persistence import MessageFlowStore
from launch.config import config
from launch.message_events import snapshot_from_message
from launch.runtime_guard import runtime_guard
from main import create_app
from message import Action, M


def test_message_snapshot_keeps_all_interactions() -> None:
    message = (
        M.document()
        .header("协议验收")
        .section("交互")
        .line(M.command("只预输入", "帮助 角色", submit=False))
        .actions(
            (
                Action("test.send", "直接发送", "我的角色"),
                Action(
                    "test.fill",
                    "无边框预输入",
                    "地图",
                    behavior="fill",
                    style="secondary",
                ),
                Action("test.link", "普通链接", "https://example.com", behavior="link"),
            )
        )
        .build()
    )
    snapshot = snapshot_from_message(message)
    assert snapshot.message_type == "markdown"
    assert "webcmd://command-link-4" in snapshot.content
    assert [item.behavior for item in snapshot.interactions] == ["send", "fill", "link", "fill"]
    assert snapshot.interactions[1].style == "secondary"
    assert snapshot.interactions[-1].kind == "command_link"
    assert snapshot.interactions[-1].submit is False

    malformed_native = snapshot_from_message(
        {
            "kind": "markdown",
            "content": "[执行](mqqapi://aio/inlinecmd?command=%E5%B8%AE%E5%8A%A9&enter=true&reply=false)",
            "keyboard": {
                "content": {
                    "rows": [
                        {
                            "buttons": [
                                {
                                    "id": "native",
                                    "render_data": {"label": "预输入", "style": "bad"},
                                    "action": {
                                        "type": "bad",
                                        "data": "地图",
                                        "permission": {"type": "bad"},
                                    },
                                }
                            ]
                        }
                    ]
                }
            },
        }
    )
    assert len(malformed_native.interactions) == 2
    assert malformed_native.interactions[-1].data == "帮助"


def test_web_projection_restores_escaped_markdown_punctuation() -> None:
    record = ConsoleFlowRecord(
        flow_id=1,
        direction="outgoing",
        adapter="local",
        request_id="request-1",
        client_id="local.message_console",
        sender_name="万象行纪",
        message_type="markdown",
        content="\\[1\\] 查看角色\n\\> 保留引用符号",
        image="",
        interactions=(),
        content_truncated=False,
        created_at="2026-07-22T00:00:00+08:00",
        created_at_timestamp=0.0,
    )
    rendered = render_message_html(record)
    assert "[1] 查看角色" in rendered
    assert "\\[1\\]" not in rendered
    assert "&gt; 保留引用符号" in rendered


def test_web_console_full_flow() -> None:
    original_lock_file = runtime_guard.lock_file
    original_database = config.database
    original_storage = service.storage
    original_media_dir = service.media_dir
    original_custom = dict(config.custom)

    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        runtime_guard.lock_file = root / "server.lock"
        object.__setattr__(
            config,
            "database",
            replace(
                config.database,
                path=root / "game.db",
                message_console_path=root / "message_console.db",
            ),
        )
        config.custom["ACCOUNT_IDENTITY_SECRET"] = "web-console-test-secret-32-bytes"
        config.custom["WEB_CONSOLE_USERNAME"] = "maintainer"
        config.custom["WEB_CONSOLE_PASSWORD"] = "test-password"
        service.storage = MessageFlowStore(root / "message_console.db")
        service.media_dir = root / "media"
        service._records.clear()
        service._character_ready = False
        service.auth._sessions.clear()
        service.auth._failures.clear()

        try:
            with TestClient(create_app()) as client:
                assert client.get("/game-console").status_code == 200
                assert client.get("/game-console/api/messages").status_code == 401
                assert client.post(
                    "/game-console/login",
                    json={"username": "maintainer", "password": "wrong"},
                ).status_code == 401

                login = client.post(
                    "/game-console/login",
                    json={"username": "maintainer", "password": "test-password"},
                )
                assert login.status_code == 200, login.text
                session = login.json()
                assert session["character_name"] == "归航维护员"
                assert session["operator_name"] == "归航公约维护员"
                csrf = session["csrf_token"]

                creation_records = _wait_for_records(client, "行纪开篇")
                assert any(
                    "归航维护员" in item["content"]
                    for item in creation_records
                    if item["direction"] == "outgoing"
                )

                without_csrf = client.post(
                    "/game-console/api/command",
                    json={"command": "我的角色"},
                )
                assert without_csrf.status_code == 403

                command = client.post(
                    "/game-console/api/command",
                    headers={"X-CSRF-Token": csrf},
                    json={"command": "帮助 角色"},
                )
                assert command.status_code == 200, command.text
                assert command.json()["matched"] is True

                unmatched = client.post(
                    "/game-console/api/command",
                    headers={"X-CSRF-Token": csrf},
                    json={"command": "开始冒险"},
                )
                assert unmatched.status_code == 200, unmatched.text
                assert unmatched.json()["matched"] is False
                unmatched_records = _wait_for_records(client, "命令未识别")
                unmatched_reply = next(
                    item
                    for item in reversed(unmatched_records)
                    if item["direction"] == "outgoing"
                    and "命令未识别" in item["content"]
                )
                assert unmatched_reply["request_id"] == unmatched.json()["event_id"]
                assert len(unmatched_reply["interactions"]) == 1
                assert unmatched_reply["interactions"][0]["data"] == "帮助"

                records = _wait_for_records(client, "帮助 角色")
                assert any(item["adapter"] == "local" and item["direction"] == "incoming" for item in records)
                response_record = next(
                    item
                    for item in reversed(records)
                    if item["direction"] == "outgoing"
                    and any(action["kind"] == "command_link" for action in item["interactions"])
                )
                interaction = next(
                    action for action in response_record["interactions"] if action["kind"] == "command_link"
                )
                executed = client.post(
                    "/game-console/api/interaction",
                    headers={"X-CSRF-Token": csrf},
                    json={
                        "flow_id": response_record["flow_id"],
                        "interaction_id": interaction["id"],
                    },
                )
                assert executed.status_code == 200, executed.text
                assert executed.json()["kind"] == "dispatch"

                forged = client.post(
                    "/game-console/api/interaction",
                    headers={"X-CSRF-Token": csrf},
                    json={"flow_id": response_record["flow_id"], "interaction_id": "forged"},
                )
                assert forged.status_code == 404

                web_command = client.post(
                    "/game-console/api/command",
                    headers={"X-CSRF-Token": csrf},
                    json={"command": "web"},
                )
                assert web_command.status_code == 200
                web_records = _wait_for_records(client, "Web 游戏台")
                assert any(
                    action["behavior"] == "link"
                    for item in web_records
                    for action in item["interactions"]
                )
        finally:
            runtime_guard.lock_file = original_lock_file
            object.__setattr__(config, "database", original_database)
            config.custom.clear()
            config.custom.update(original_custom)
            service.storage = original_storage
            service.media_dir = original_media_dir
            service._records.clear()
            service._character_ready = False
            service.auth._sessions.clear()
            service.auth._failures.clear()


def _wait_for_records(client: TestClient, expected: str) -> list[dict]:
    deadline = time.time() + 5
    records: list[dict] = []
    while time.time() < deadline:
        response = client.get("/game-console/api/messages?limit=200")
        assert response.status_code == 200, response.text
        records = response.json()["records"]
        if any(expected in str(item.get("content") or "") for item in records):
            return records
        time.sleep(0.05)
    raise AssertionError(f"等待消息超时: {expected}; 当前消息数={len(records)}")


def main() -> None:
    test_message_snapshot_keeps_all_interactions()
    test_web_projection_restores_escaped_markdown_punctuation()
    test_web_console_full_flow()
    print("web console test passed")


if __name__ == "__main__":
    main()
