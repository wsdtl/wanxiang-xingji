"""QQ 消息归一化测试。

运行方式：

    python .test/qq_event_normalization_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from launch.adapter.qq.event import normalize_content


def main() -> None:
    """确认机器人 at 不进业务参数，其他用户 at 仍可用于指定目标。"""

    bot_mentions = [{"id": "bot", "user_openid": "bot-openid", "is_you": True}]
    assert normalize_content(
        "<@bot> 开启缘契 友枝町追卡",
        event_type="GROUP_AT_MESSAGE_CREATE",
        mentions=bot_mentions,
    ) == "开启缘契 友枝町追卡"
    assert normalize_content(
        "开启缘契 友枝町追卡 <@bot>",
        event_type="GROUP_AT_MESSAGE_CREATE",
        mentions=bot_mentions,
    ) == "开启缘契 友枝町追卡"

    player_mentions = [{"id": "target-token", "user_openid": "target-openid", "is_you": False}]
    assert normalize_content(
        "切磋 <@target-token>",
        event_type="GROUP_AT_MESSAGE_CREATE",
        mentions=player_mentions,
    ) == "切磋 target-openid"
    assert normalize_content(
        "查看ID <@target-token>",
        event_type="GROUP_AT_MESSAGE_CREATE",
        mentions=player_mentions,
    ) == "查看ID target-openid"

    mixed_mentions = [
        {"id": "bot", "user_openid": "bot-openid", "is_you": True},
        {"id": "target-token", "user_openid": "target-openid", "is_you": False},
    ]
    assert normalize_content(
        "<@bot> <@target-token> 切磋",
        event_type="GROUP_AT_MESSAGE_CREATE",
        mentions=mixed_mentions,
    ) == "target-openid 切磋"
    assert normalize_content(
        "<@bot><@target-token> 切磋",
        event_type="GROUP_AT_MESSAGE_CREATE",
        mentions=mixed_mentions,
    ) == "target-openid 切磋"

    ambiguous_bot_mentions = [{"id": "bot", "user_openid": "bot-openid"}]
    assert normalize_content(
        "<@bot> 购票 123456",
        event_type="GROUP_MESSAGE_CREATE",
        mentions=ambiguous_bot_mentions,
    ) == "购票 123456"

    explicit_player_mentions = [{"id": "target-token", "user_openid": "target-openid", "is_you": False}]
    assert normalize_content(
        "<@target-token> 购票 123456",
        event_type="GROUP_MESSAGE_CREATE",
        mentions=explicit_player_mentions,
    ) == "target-openid 购票 123456"

    print("QQ 消息归一化测试通过")


if __name__ == "__main__":
    main()
