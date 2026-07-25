"""QQ 签名 HTTP 回调入口测试。"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from launch.adapter.qq.message import QQ_EVENT_MAX_BODY_BYTES
from launch.adapter.qq.signature import SIGNATURE_HEADER, TIMESTAMP_HEADER, make_event_signature
from launch.config import config
from launch.runtime_guard import runtime_guard
from main import create_app


def main() -> None:
    secret = "http-flow-secret"
    old_secret = config.custom.get("QQ_BOT_SECRET")
    old_required = config.custom.get("QQ_EVENT_SIGNATURE_REQUIRED")
    original_lock_file = runtime_guard.lock_file
    original_database = config.database
    config.custom["QQ_BOT_SECRET"] = secret
    config.custom["QQ_EVENT_SIGNATURE_REQUIRED"] = "true"

    with TemporaryDirectory() as tmpdir:
        runtime_guard.lock_file = Path(tmpdir) / "server.lock"
        object.__setattr__(
            config,
            "database",
            replace(config.database, path=Path(tmpdir) / "http-flow.db"),
        )
        try:
            with TestClient(create_app()) as http:
                body = json.dumps(
                    {
                        "id": "http-event",
                        "t": "C2C_MESSAGE_CREATE",
                        "d": {
                            "id": "http-message",
                            "content": "未注册命令",
                            "author": {"user_openid": "http-user"},
                        },
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                timestamp = str(int(time.time()))
                response = http.post(
                    "/qq/events",
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        TIMESTAMP_HEADER: timestamp,
                        SIGNATURE_HEADER: make_event_signature(secret, timestamp, body),
                    },
                )
                assert response.status_code == 200
                assert response.json() == {"op": 12}

                assert http.post("/qq/events", content=b"{}", headers={"Content-Type": "text/plain"}).status_code == 415
                oversized = b"{" + b" " * QQ_EVENT_MAX_BODY_BYTES + b"}"
                assert http.post(
                    "/qq/events",
                    content=oversized,
                    headers={"Content-Type": "application/json"},
                ).status_code == 413
        finally:
            runtime_guard.lock_file = original_lock_file
            object.__setattr__(config, "database", original_database)
            _restore_custom("QQ_BOT_SECRET", old_secret)
            _restore_custom("QQ_EVENT_SIGNATURE_REQUIRED", old_required)

    print("QQ signed HTTP flow test passed")


def _restore_custom(name: str, value: str | None) -> None:
    if value is None:
        config.custom.pop(name, None)
    else:
        config.custom[name] = value


if __name__ == "__main__":
    main()
