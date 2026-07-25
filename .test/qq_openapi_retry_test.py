"""QQ OpenAPI 有界重试测试。"""

from __future__ import annotations

import sys
from pathlib import Path
from types import MethodType


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from launch.adapter.qq.client import QqOpenApiClient, QqOpenApiError, QqOpenApiTransportError


def main() -> None:
    _assert_retry_after_and_success()
    _assert_unsafe_push_does_not_retry()
    _assert_401_refreshes_once()
    _assert_connect_failure_retries()
    print("QQ OpenAPI retry test passed")


def _client_with_outcomes(outcomes: list[object]) -> tuple[QqOpenApiClient, list[float], list[int]]:
    api = QqOpenApiClient(app_id="app", client_secret="secret")
    sleeps: list[float] = []
    calls: list[int] = []

    def request_once(self, method, path, payload, log_title):
        calls.append(1)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    api._request_openapi_once = MethodType(request_once, api)
    api._sleep = sleeps.append
    return api, sleeps, calls


def _assert_retry_after_and_success() -> None:
    api, sleeps, calls = _client_with_outcomes(
        [
            QqOpenApiError(429, "limited", headers={"Retry-After": "1.5"}),
            {"id": "ok"},
        ]
    )
    result = api._request_openapi("POST", "/v2/groups/g/messages", {"event_id": "event"}, "test")
    assert result == {"id": "ok"}
    assert sleeps == [1.5]
    assert len(calls) == 2


def _assert_unsafe_push_does_not_retry() -> None:
    api, sleeps, calls = _client_with_outcomes([QqOpenApiError(503, "down")])
    try:
        api._request_openapi("POST", "/v2/groups/g/messages", {"msg_type": 0}, "test")
        raise AssertionError("无事件关联的主动推送不能自动重试")
    except QqOpenApiError as exc:
        assert exc.status_code == 503
    assert sleeps == []
    assert len(calls) == 1


def _assert_401_refreshes_once() -> None:
    api, sleeps, calls = _client_with_outcomes([QqOpenApiError(401, "expired"), {"id": "ok"}])
    cleared: list[int] = []
    api.clear_access_token = lambda: cleared.append(1)
    assert api._request_openapi("POST", "/v2/groups/g/messages", {"event_id": "event"}, "test") == {"id": "ok"}
    assert cleared == [1]
    assert sleeps == []
    assert len(calls) == 2


def _assert_connect_failure_retries() -> None:
    api, sleeps, calls = _client_with_outcomes(
        [QqOpenApiTransportError("connect", retryable=True), {"id": "ok"}]
    )
    assert api._request_openapi("PUT", "/interactions/i", {"code": 0}, "test") == {"id": "ok"}
    assert sleeps == [0.25]
    assert len(calls) == 2


if __name__ == "__main__":
    main()
