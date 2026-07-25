"""QQ 普通事件签名校验测试。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys
import time

from fastapi import HTTPException


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from launch.config import config
from launch.adapter.qq.message import _verify_event_signature
from launch.adapter.qq.signature import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    make_event_signature,
    verify_event_signature,
)


class FakeRequest:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


@contextmanager
def qq_signature_required(value: str):
    """临时固定 QQ 普通事件验签配置，避免测试受本机 .env 影响。"""

    old_value = config.custom.get("QQ_EVENT_SIGNATURE_REQUIRED")
    config.custom["QQ_EVENT_SIGNATURE_REQUIRED"] = value
    try:
        yield
    finally:
        if old_value is None:
            config.custom.pop("QQ_EVENT_SIGNATURE_REQUIRED", None)
        else:
            config.custom["QQ_EVENT_SIGNATURE_REQUIRED"] = old_value


def main() -> None:
    secret = "main-secret"
    now = int(time.time())
    timestamp = str(now)
    body = b'{"id":"event-1","t":"C2C_MESSAGE_CREATE","d":{"id":"msg-1"}}'
    signature = make_event_signature(secret, timestamp, body)

    verify_event_signature(secret, timestamp, body, signature, now=now)

    stale_timestamp = str(now - 301)
    stale_signature = make_event_signature(secret, stale_timestamp, body)
    try:
        verify_event_signature(secret, stale_timestamp, body, stale_signature, now=now)
        raise AssertionError("超过时间窗的合法签名必须被拒绝")
    except ValueError as exc:
        assert "时间戳已过期" in str(exc)

    request = FakeRequest(
        {
            TIMESTAMP_HEADER: timestamp,
            SIGNATURE_HEADER: signature,
        }
    )

    with qq_signature_required("true"):
        _verify_event_signature(request, secret, body)

        try:
            _verify_event_signature(
                FakeRequest({TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: "00" * 64}),
                secret,
                body,
            )
            raise AssertionError("错误签名必须被拒绝")
        except HTTPException as exc:
            assert exc.status_code == 401
            assert "签名校验失败" in str(exc.detail)

        try:
            _verify_event_signature(FakeRequest({}), secret, body)
            raise AssertionError("缺少签名头必须被拒绝")
        except HTTPException as exc:
            assert exc.status_code == 401
            assert SIGNATURE_HEADER in str(exc.detail) or TIMESTAMP_HEADER in str(exc.detail)

    with qq_signature_required("false"):
        _verify_event_signature(FakeRequest({}), secret, body)

    with qq_signature_required("maybe"):
        try:
            _verify_event_signature(request, secret, body)
            raise AssertionError("非法签名校验配置必须失败")
        except HTTPException as exc:
            assert exc.status_code == 500
            assert "QQ_EVENT_SIGNATURE_REQUIRED" in str(exc.detail)

    print("QQ 普通事件签名校验测试通过")


if __name__ == "__main__":
    main()
