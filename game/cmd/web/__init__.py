"""Web 游戏台命令与 HTTP 组件。"""

from __future__ import annotations

from ..command import GameCommand
from . import entry, runtime
from .site import router


@GameCommand.handler(cmd="web", access="public", hidden=True)
async def web_console() -> None:
    await entry.show_entry()


__all__ = ["router"]
