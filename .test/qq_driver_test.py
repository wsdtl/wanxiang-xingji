"""QQ 单机器人驱动与发送协议测试。"""

from __future__ import annotations

import asyncio
import sys
from io import BytesIO
from pathlib import Path
from types import MethodType


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from launch.adapter import Depends
from launch.adapter.context import MENTION_SENDER, SendOptions
from launch.adapter.qq.client import client
from launch.adapter.qq.depends import (
    current_qq_actor_openid,
    current_qq_event,
    current_qq_group_openid,
    current_qq_send_target,
)
from launch.adapter.qq.event import parse_message_event
from launch.adapter.qq.handler import QqCommandMatch, QqEventHandler
from launch.adapter.qq.manager import QqReplyManager
from launch.adapter.qq.message import QQ_EVENT_ROUTE
from launch.adapter.qq.payload import ark, embed, image, markdown, media, raw, text
from launch.adapter.qq.signature import make_validation_signature
from launch.adapter.qq.target import qq_group_target, qq_private_target
from launch.config import config


def _group_payload(content: str = "状态") -> dict:
    return {
        "id": "event-group",
        "t": "GROUP_AT_MESSAGE_CREATE",
        "d": {
            "id": "message-group",
            "content": f"<@bot-token> {content}",
            "group_openid": "group-openid",
            "author": {
                "user_openid": "global-user-openid",
                "member_openid": "member-openid",
                "username": "群聊昵称",
            },
            "mentions": [
                {"id": "bot-token", "user_openid": "bot-openid", "is_you": True}
            ],
        },
    }


def _private_payload(content: str = "状态") -> dict:
    return {
        "id": "event-private",
        "t": "C2C_MESSAGE_CREATE",
        "d": {
            "id": "message-private",
            "content": content,
            "author": {"user_openid": "private-openid", "username": "私聊昵称"},
        },
    }


def _interaction_payload(interaction_id: str) -> dict:
    """使用 2026-07-12 真实群聊 callback 的字段结构。"""

    return {
        "id": f"event-{interaction_id}",
        "t": "INTERACTION_CREATE",
        "d": {
            "id": interaction_id,
            "application_id": "application-id",
            "type": 11,
            "group_openid": "group-openid",
            "group_member_openid": "member-openid",
            "chat_type": 1,
            "scene": "group",
            "data": {
                "type": 11,
                "resolved": {
                    "button_data": "状态",
                    "button_id": "status",
                }
            },
        },
    }


def main() -> None:
    old_secret = config.custom.get("QQ_BOT_SECRET")
    config.custom["QQ_BOT_SECRET"] = "single-secret"
    try:
        _assert_single_callback()
        asyncio.run(_assert_context_and_deduplication())
        _assert_explicit_targets_and_payloads()
    finally:
        if old_secret is None:
            config.custom.pop("QQ_BOT_SECRET", None)
        else:
            config.custom["QQ_BOT_SECRET"] = old_secret

    print("QQ single bot driver test passed")


def _assert_single_callback() -> None:
    assert QQ_EVENT_ROUTE == "/qq/events"
    validation = {"op": 13, "d": {"plain_token": "plain", "event_ts": "123"}}
    response = asyncio.run(QqEventHandler.validation(validation))
    assert response == {
        "plain_token": "plain",
        "signature": make_validation_signature("single-secret", "plain", "123"),
    }

    group_event = parse_message_event(_group_payload())
    private_event = parse_message_event(_private_payload())
    private_without_name_payload = _private_payload()
    private_without_name_payload["d"]["author"].pop("username")
    private_without_name = parse_message_event(private_without_name_payload)
    assert group_event is not None and group_event.is_group
    assert private_event is not None and not private_event.is_group
    assert private_without_name is not None
    assert group_event.actor_openid == "member-openid"
    assert group_event.user_openid == "global-user-openid"
    assert private_event.actor_openid == "private-openid"
    assert group_event.sender_name == "群聊昵称"
    assert private_event.sender_name == "私聊昵称"
    assert private_without_name.sender_name == ""
    assert not hasattr(group_event, "bot_key")
    assert QqEventHandler._actor_identity_source(group_event) == "member"
    assert QqEventHandler._actor_identity_source(private_event) == "user"
    assert QqEventHandler._identity_fingerprint(group_event.user_openid) == QqEventHandler._identity_fingerprint(
        "global-user-openid"
    )
    assert QqEventHandler._identity_fingerprint("") == "-"


async def _assert_context_and_deduplication() -> None:
    event = parse_message_event(_group_payload())
    assert event is not None
    captured: list[dict] = []

    async def command(
        client_id: str,
        sender_name: str,
        message_context,
        qq_event=Depends(current_qq_event),
        actor_openid=Depends(current_qq_actor_openid),
        group_openid=Depends(current_qq_group_openid),
        send_target=Depends(current_qq_send_target),
    ) -> None:
        captured.append(
            {
                "client_id": client_id,
                "sender_name": sender_name,
                "identity": message_context.identity,
                "event": qq_event,
                "actor_openid": actor_openid,
                "group_openid": group_openid,
                "target": send_target,
            }
        )

    rule = QqEventHandler._make_rule(command, priority=10, block=True)
    await QqEventHandler._call_rule(
        QqCommandMatch(rule=rule, command="状态", message=""),
        event,
    )
    assert captured[0]["client_id"] == "member-openid"
    assert captured[0]["sender_name"] == "群聊昵称"
    identity = captured[0]["identity"]
    assert identity.primary.subject_kind == "identity.qq_group_member"
    assert identity.primary.external_id == "member-openid"
    assert {claim.subject_kind for claim in identity.aliases} == {
        "identity.qq_user",
        "identity.qq_actor",
    }
    assert captured[0]["event"] is event
    assert captured[0]["actor_openid"] == "member-openid"
    assert captured[0]["group_openid"] == "group-openid"
    assert captured[0]["target"].group_openid == "group-openid"
    assert not hasattr(captured[0]["target"], "route_id")

    async with QqEventHandler._seen_event_guard:
        QqEventHandler._seen_event_ids.clear()
        QqEventHandler._seen_event_order.clear()
    assert await QqEventHandler._remember_event_once(event) is True
    assert await QqEventHandler._remember_event_once(parse_message_event(_group_payload())) is False
    await QqEventHandler._forget_event(event)
    assert await QqEventHandler._remember_event_once(event) is True
    await QqEventHandler._forget_event(event)

    original_queue = QqEventHandler._event_queue
    QqEventHandler._event_queue = None
    try:
        await QqEventHandler._enqueue_event(event)
    finally:
        QqEventHandler._event_queue = original_queue
    assert await QqEventHandler._remember_event_once(event) is True
    await QqEventHandler._forget_event(event)

    first_click = parse_message_event(_interaction_payload("interaction-1"))
    second_click = parse_message_event(_interaction_payload("interaction-2"))
    assert first_click is not None and second_click is not None
    assert first_click.message_id == ""
    assert first_click.member_openid == "member-openid"
    assert first_click.content == "状态"
    assert QqEventHandler._event_dedupe_key(first_click) != QqEventHandler._event_dedupe_key(second_click)


def _assert_explicit_targets_and_payloads() -> None:
    calls: list[dict] = []
    originals = {
        "send_group_payload": client.send_group_payload,
        "send_c2c_payload": client.send_c2c_payload,
        "upload_group_image": client.upload_group_image,
        "upload_c2c_image": client.upload_c2c_image,
    }

    def send_group(self, group_openid, payload, message_id="", event_id=""):
        calls.append({"api": "group", "target": group_openid, "payload": payload})
        return {"id": "group-result"}

    def send_c2c(self, openid, payload, message_id="", event_id="", is_wakeup=False):
        calls.append({"api": "private", "target": openid, "payload": payload})
        return {"id": "private-result"}

    def upload_group(self, group_openid, image_bytes):
        return f"group-image:{group_openid}:{len(image_bytes)}"

    def upload_private(self, openid, image_bytes):
        return f"private-image:{openid}:{len(image_bytes)}"

    client.send_group_payload = MethodType(send_group, client)
    client.send_c2c_payload = MethodType(send_c2c, client)
    client.upload_group_image = MethodType(upload_group, client)
    client.upload_c2c_image = MethodType(upload_private, client)
    try:
        group_target = qq_group_target("group-openid", member_openid="member-openid")
        private_target = qq_private_target("private-openid", is_wakeup=True)
        assert not hasattr(group_target.driver_target, "bot_key")

        QqReplyManager._send_sync(text("文本"), group_target.driver_target)
        QqReplyManager._send_sync(
            markdown("富文本"),
            group_target.driver_target,
            SendOptions(mention=MENTION_SENDER),
        )
        QqReplyManager._send_sync(image(BytesIO(b"image")), private_target.driver_target)
        QqReplyManager._send_sync(ark({"template_id": 1}), group_target.driver_target)
        QqReplyManager._send_sync(embed({"title": "公告"}), group_target.driver_target)
        QqReplyManager._send_sync(media("file-info"), group_target.driver_target)
        QqReplyManager._send_sync(raw({"content": "raw", "msg_type": 0}), group_target.driver_target)
    finally:
        for name, value in originals.items():
            setattr(client, name, value)

    assert calls[0]["payload"]["content"] == "文本"
    assert calls[1]["payload"]["markdown"]["content"] == "<@member-openid> 富文本"
    assert calls[2]["payload"]["media"]["file_info"] == "private-image:private-openid:5"
    assert calls[3]["payload"]["msg_type"] == 3
    assert calls[4]["payload"]["msg_type"] == 4
    assert calls[5]["payload"]["msg_type"] == 7
    assert calls[6]["payload"] == {"content": "raw", "msg_type": 0}


if __name__ == "__main__":
    main()
