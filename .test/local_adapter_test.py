"""本地驱动器测试。"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
import sys

from fastapi import FastAPI


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from launch.adapter import (
    CommandGuardDecision,
    Depends,
    MessageHandler,
    clear_command_guards,
    enabled_adapter_names,
    manager as adapter_manager,
    register_command_guard,
    registered_command_guards,
)
from launch.adapter.context import CONVERSATION_PRIVATE
from launch.adapter.local import LocalEventHandler, dispatch
from launch.adapter.local.manager import current_event
from launch.adapter.qq.depends import current_qq_event
from launch.adapter.qq.message import QQ_EVENT_ROUTE
from launch.mount import AdapterMount
from message import M, RenderedMessage


def main() -> None:
    asyncio.run(_main())
    print("local adapter test passed")


async def _main() -> None:
    assert enabled_adapter_names() == ["qq", "local"]
    await _assert_message_handler_registers_local()
    await _assert_priority_block()
    await _assert_regex_match()
    await _assert_command_guard_blocks_once_and_bypasses()
    await _assert_qq_depends_rejected()
    await _assert_mount_keeps_local_internal()


async def _assert_message_handler_registers_local() -> None:
    _reset_local_rules()
    captured: list[dict] = []

    @MessageHandler.handler(
        cmd="本地测试",
        priority=100,
        block=True,
        metadata={"test": {"access": "public"}},
    )
    async def local_handler(
        client_id: str,
        message: str,
        cmd: str,
        raw_message: str,
        sender_name: str,
        message_context,
        reply_target,
        adapter_capabilities,
        manager,
    ) -> None:
        captured.append(
            {
                "client_id": client_id,
                "message": message,
                "cmd": cmd,
                "raw_message": raw_message,
                "sender_name": sender_name,
                "adapter": message_context.adapter,
                "conversation_type": message_context.conversation_type,
                "identity": message_context.identity,
                "reply_target": reply_target,
                "can_markdown": adapter_capabilities.markdown,
                "uses_public_manager": manager is adapter_manager,
            }
        )
        await manager.send(
            M.document().section("本地回复", icon="message").line("收到: ", message).build(),
            client_id,
        )

    await LocalEventHandler.run()
    assert LocalEventHandler.exact_rules["本地测试"][0].metadata == {"test": {"access": "public"}}
    result = await dispatch(
        client_id="local-user",
        raw_message="本地测试 参数",
        sender_name="本地昵称",
    )

    assert result.matched is True
    assert result.matched_count == 1
    assert len(result.replies) == 1
    assert isinstance(result.replies[0].message, RenderedMessage)
    assert result.replies[0].message.kind == "markdown"
    assert "收到: 参数" in result.replies[0].message.content
    assert result.replies[0].client_id == "local-user"
    assert result.replies[0].request_id == result.event.event_id
    assert captured[0]["client_id"] == "local-user"
    assert captured[0]["message"] == "参数"
    assert captured[0]["cmd"] == "本地测试"
    assert captured[0]["raw_message"] == "本地测试 参数"
    assert captured[0]["sender_name"] == "本地昵称"
    assert captured[0]["adapter"] == "local"
    assert captured[0]["conversation_type"] == CONVERSATION_PRIVATE
    assert captured[0]["identity"].evidence_id.startswith("local:")
    assert captured[0]["identity"].primary.provider_id == "platform.local"
    assert captured[0]["identity"].primary.external_id == "local-user"
    assert captured[0]["reply_target"].adapter == "local"
    assert captured[0]["can_markdown"] is True
    assert captured[0]["uses_public_manager"] is True
    assert current_event.get() is None


async def _assert_priority_block() -> None:
    _reset_local_rules()
    calls: list[str] = []

    async def high() -> None:
        calls.append("high")

    async def same() -> None:
        calls.append("same")

    async def low() -> None:
        calls.append("low")

    LocalEventHandler.handler(cmd="顺序", priority=100, block=True)(high)
    LocalEventHandler.handler(cmd="顺序", priority=100, block=False)(same)
    LocalEventHandler.handler(cmd="顺序", priority=50, block=False)(low)

    await LocalEventHandler.run()
    result = await dispatch(client_id="local-user", raw_message="顺序")

    assert result.matched is True
    assert result.matched_count == 3
    assert calls == ["high", "same"]


async def _assert_regex_match() -> None:
    _reset_local_rules()
    captured: list[dict] = []

    async def regex_handler(message: str, match) -> None:
        captured.append({"message": message, "name": match.group("name")})

    LocalEventHandler.handler(
        cmd=re.compile(r"^查(?P<name>\S+)$"),
        priority=100,
        block=True,
    )(regex_handler)

    await LocalEventHandler.run()
    result = await dispatch(client_id="local-user", raw_message="查天气 明天")

    assert result.matched is True
    assert captured == [{"message": "明天", "name": "天气"}]


async def _assert_qq_depends_rejected() -> None:
    _reset_local_rules()

    async def qq_depends_handler(qq_event=Depends(current_qq_event)) -> None:
        raise AssertionError(f"Local 不应提供 QQ 私有事件：{qq_event!r}")

    LocalEventHandler.handler(cmd="QQ私有", priority=100, block=True)(qq_depends_handler)

    await LocalEventHandler.run()
    try:
        await dispatch(client_id="local-user", raw_message="QQ私有")
        raise AssertionError("Local 上下文读取 QQ 私有 Depends 必须失败")
    except RuntimeError as exc:
        assert "当前消息不是 QQ 上下文" in str(exc)


async def _assert_command_guard_blocks_once_and_bypasses() -> None:
    _reset_local_rules()
    clear_command_guards()
    calls: list[str] = []
    guard_contexts: list[dict] = []

    async def high() -> None:
        calls.append("high")

    async def same() -> None:
        calls.append("same")

    async def guard(context) -> CommandGuardDecision:
        guard_contexts.append(
            {
                "adapter": context.adapter,
                "client_id": context.client_id,
                "cmd": context.cmd,
                "message": context.message,
                "raw_message": context.raw_message,
                "metadata": context.command_metadata,
            }
        )
        return CommandGuardDecision.block(
            M.document().section("状态", icon="notice").line("托管中").build(),
            reason="locked",
        )

    LocalEventHandler.handler(
        cmd="守卫",
        priority=100,
        block=True,
        metadata={"test": {"access": "player"}},
    )(high)
    LocalEventHandler.handler(cmd="守卫", priority=100, block=False)(same)
    register_command_guard("test.local.guard", guard, priority=100)
    register_command_guard("test.local.guard", guard, priority=100)

    assert len(registered_command_guards()) == 1

    await LocalEventHandler.run()
    blocked = await dispatch(client_id="local-user", raw_message="守卫 参数")

    assert blocked.matched is True
    assert blocked.matched_count == 2
    assert calls == []
    assert guard_contexts == [
        {
            "adapter": "local",
            "client_id": "local-user",
            "cmd": "守卫",
            "message": "参数",
            "raw_message": "守卫 参数",
            "metadata": {"test": {"access": "player"}},
        }
    ]
    assert len(blocked.replies) == 1
    assert isinstance(blocked.replies[0].message, RenderedMessage)
    assert "托管中" in blocked.replies[0].message.content

    bypassed = await dispatch(client_id="local-user", raw_message="守卫 参数", bypass_guards=True)

    assert bypassed.matched is True
    assert bypassed.matched_count == 2
    assert calls == ["high", "same"]
    assert len(bypassed.replies) == 0
    assert len(guard_contexts) == 1
    clear_command_guards()


async def _assert_mount_keeps_local_internal() -> None:
    app = FastAPI()
    adapters = await AdapterMount(app)
    paths = {getattr(route, "path", "") for route in app.routes}

    assert LocalEventHandler in adapters
    assert QQ_EVENT_ROUTE in paths
    assert not any("local" in path.lower() for path in paths)


def _reset_local_rules() -> None:
    clear_command_guards()
    LocalEventHandler.exact_rules.clear()
    LocalEventHandler.regex_rules.clear()
    LocalEventHandler.regex_fallback.clear()
    LocalEventHandler.regex_prefix_lengths.clear()
    LocalEventHandler._register_order = 0


if __name__ == "__main__":
    main()
