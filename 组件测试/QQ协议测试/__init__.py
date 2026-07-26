"""测试业务中的 QQ 协议探针。

该组件直接依赖 QQ 驱动器，用于真实客户端联调，不进入未来修仙业务公共层。
组件使用根级 message 语义协议，同时读取 QQ 私有事件验证协议翻译结果。
"""

from __future__ import annotations

import struct
import zlib
from launch import C, logger
from launch.adapter import Depends
from launch.adapter.qq.depends import current_qq_event
from launch.adapter.qq.diagnostics import identity_fingerprint, safe_payload_summary
from launch.adapter.qq.event import QqMessageEvent
from launch.adapter.qq.handler import QqEventHandler
from launch.adapter.qq.manager import manager
from launch.adapter.qq.render import render_qq_message
from message import Action, DocumentMessage, M


COMMAND = "QQ协议测试"
TEST_ACTIONS = {"回调", "即发", "回填", "引用", "Markdown", "图片", "身份"}


def build_test_actions() -> tuple[Action, ...]:
    """覆盖回调、即发、回填和引用的公共动作语义。"""

    return (
        Action("callback", "回调", f"{COMMAND} 回调", behavior="callback", visited_label="已点 回调"),
        Action("send", "即发", f"{COMMAND} 即发", behavior="send", visited_label="已点 即发"),
        Action("fill", "回填", f"{COMMAND} 回填 ", behavior="fill", style="secondary"),
        Action("reply", "引用", f"{COMMAND} 引用", behavior="send", style="secondary", reply=True),
        Action("markdown", "Markdown", f"{COMMAND} Markdown", behavior="send"),
        Action("image", "图片", f"{COMMAND} 图片", behavior="send"),
        Action("identity", "身份", f"{COMMAND} 身份", behavior="send", style="secondary"),
    )


def build_test_menu() -> DocumentMessage:
    """生成跨协议测试面板，由当前驱动器负责最终渲染。"""

    return (
        M.document()
        .header("QQ 驱动器协议测试")
        .section("测试状态", icon="test")
        .field("状态", "等待操作")
        .row(("动作", "回调 / 即发 / 回填 / 引用"), ("输出", "Markdown / 图片 / 身份"))
        .actions(build_test_actions())
        .build()
    )


def build_test_keyboard() -> dict:
    """读取公共动作经 QQ 翻译后的按钮键盘，供协议测试断言。"""

    rendered = render_qq_message(build_test_menu())
    if not isinstance(rendered, dict) or not isinstance(rendered.get("keyboard"), dict):
        raise RuntimeError("QQ 测试菜单未生成 keyboard")
    return rendered["keyboard"]


def _event_report(event: QqMessageEvent, action: str) -> DocumentMessage:
    """把一次真实事件整理成可见的脱敏结果。"""

    summary = safe_payload_summary(event.raw)
    conversation = "群聊" if event.is_group else "私聊"
    return (
        M.document()
        .header("QQ 协议事件已接收")
        .section("事件", icon="test")
        .field("动作", action)
        .row(("事件", event.event_type), ("会话", conversation))
        .field("actor", identity_fingerprint(event.actor_openid))
        .row(
            ("user", identity_fingerprint(event.user_openid)),
            ("member", identity_fingerprint(event.member_openid)),
        )
        .field("button_data", summary["button_data"])
        .build()
    )


def _log_event(event: QqMessageEvent, action: str) -> None:
    """记录字段结构，原始 OpenID 和完整 payload 不进入日志。"""

    summary = safe_payload_summary(event.raw)
    logger.opt(colors=True).info(
        C.join(
            C.ok("QQ 协议测试事件"),
            C.kv("action", action),
            C.kv("type", event.event_type),
            C.kv("schema", summary["schema"]),
            C.kv("identities", summary["identities"]),
            C.kv("button_data", summary["button_data"]),
        )
    )


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def test_image_bytes() -> bytes:
    """生成无需外部文件的红绿蓝测试图，验证 QQ 图片上传与发送链路。"""

    width, height = 96, 48
    rows: list[bytes] = []
    colors = ((220, 66, 77), (39, 174, 96), (41, 128, 185))
    for _y in range(height):
        row = bytearray([0])
        for x in range(width):
            row.extend(colors[min(2, x // (width // 3))])
        rows.append(bytes(row))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    compressed = zlib.compress(b"".join(rows), level=9)
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", header),
            _png_chunk(b"IDAT", compressed),
            _png_chunk(b"IEND", b""),
        ]
    )


@QqEventHandler.handler(cmd=COMMAND, priority=1000, block=True)
async def qq_protocol_test(
    client_id: str,
    message: str = "",
    qq_event: QqMessageEvent = Depends(current_qq_event),
) -> None:
    """发送测试面板，并接收各类按钮产生的真实事件。"""

    action = str(message or "").strip() or "菜单"
    _log_event(qq_event, action)

    if action == "菜单":
        await manager.send(build_test_menu(), client_id)
        return
    if action == "图片":
        await manager.send(M.image(test_image_bytes(), "QQ 图片协议测试"), client_id)
        return
    if action == "Markdown":
        await manager.send(
            M.document()
            .header("QQ Markdown 协议正常")
            .section("来源", icon="test")
            .line("真实客户端联调")
            .build(),
            client_id,
        )
        return
    if action in TEST_ACTIONS or action.startswith("回填 "):
        await manager.send(_event_report(qq_event, action), client_id)
        return

    await manager.send(
        M.document()
        .header("QQ 协议测试")
        .section("错误", icon="notice")
        .field("未知动作", action)
        .build(),
        client_id,
    )
