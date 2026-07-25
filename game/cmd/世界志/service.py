"""世界志参数解析、记录展示与成功阅读确认。"""

from __future__ import annotations

import asyncio

from game.app import CharacterOverviewResult, current_game_services
from message import Action

from ..lore_presentation import (
    world_lore_failure_message,
    world_lore_overview_message,
    world_lore_record_message,
)
from ..command_helpers import command_time
from ..reply import send_command_failure, send_game_reply


async def view_world_lore(message: str, result: CharacterOverviewResult) -> None:
    overview = result.overview if result.status == "ok" else None
    if overview is None:
        await send_game_reply(world_lore_failure_message("当前没有读取到角色状态，请稍后重试"))
        return
    services = current_game_services()
    world_view = None
    try:
        world_token, record_number = _parse_request(message)
        world_view = (
            services.world_views.resolve(world_token)
            if world_token
            else services.world_view(overview.character_world)
        )
        if world_view is None:
            raise ValueError("没有找到这个世界")
        lore = await asyncio.to_thread(
            services.world_lore.view,
            overview.character.id,
            world_view.world.id,
            current_world_id=overview.character_world.world_id,
        )
        if record_number is None:
            await send_game_reply(world_lore_overview_message(lore, world_view.skin.name))
            return
        if not lore.available:
            raise ValueError("尚未在这个世界留下可阅读的行纪")
        if not 1 <= record_number <= len(lore.definition.records):
            raise ValueError("没有这条世界志记录")
        record = lore.definition.records[record_number - 1]
        if record not in lore.unlocked_records:
            raise ValueError(f"这条记录需要世界行纪达到 {record.threshold}%")
        sent = await send_game_reply(
            world_lore_record_message(lore.definition, record, world_view.skin.name)
        )
        if sent:
            await asyncio.to_thread(
                services.world_lore.acknowledge,
                overview.character.id,
                world_view.world.id,
                tuple(
                    value.id
                    for value in lore.unlocked_records
                    if value.threshold <= record.threshold
                ),
                current_world_id=overview.character_world.world_id,
                logical_time=command_time(),
            )
    except (KeyError, TypeError, ValueError) as exc:
        command = f"世界志 {world_view.skin.name}" if world_view is not None else "世界志"
        await send_game_reply(
            world_lore_failure_message(
                str(exc),
                Action(
                    "world-lore.recover",
                    "返回世界志",
                    command,
                    style="secondary",
                ),
            )
        )
    except Exception as exc:
        await send_command_failure(
            "世界志查询失败",
            overview.character.id,
            exc,
            world_lore_failure_message("当前没有读取到世界志，请稍后重试"),
        )


def _parse_request(message: str) -> tuple[str, int | None]:
    tokens = str(message or "").strip().split()
    if not tokens:
        return "", None
    if tokens[-1].isdigit():
        return " ".join(tokens[:-1]), int(tokens[-1])
    return " ".join(tokens), None


__all__ = ["view_world_lore"]
