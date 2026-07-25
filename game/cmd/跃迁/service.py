"""角色级世界投影查询与跃迁业务。"""

from __future__ import annotations

import asyncio

from game.app import CurrentCharacterResult, current_game_services
from game.content import DIMENSION_SHIFT_ITEM_ID
from game.rules.character import WorldShiftResult
from launch import C, logger
from message import Action, DocumentMessage, M

from ..command_helpers import command_time
from ..reply import send_game_reply
from ..presentation import current_action_action


async def dimension_shift(
    message: str,
    current: CurrentCharacterResult,
) -> None:
    character = current.character if current.status == "ok" else None
    dimension = current.character_world if current.status == "ok" else None
    if character is None or dimension is None:
        await send_game_reply(_unavailable())
        return
    services = current_game_services()
    requested = str(message or "").strip()
    if not requested:
        await send_game_reply(_worlds_message(dimension.world_id))
        return
    target = services.world_views.resolve(requested)
    if target is None:
        await send_game_reply(_worlds_message(dimension.world_id, invalid=True))
        return
    try:
        result = await asyncio.to_thread(
            services.shift_character_world,
            character.id,
            target.world.id,
            logical_time=command_time(),
        )
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.join(C.fail("角色跃迁失败"), C.kv("character", character.id))
        )
        await send_game_reply(_unavailable())
        return
    await send_game_reply(_result_message(result))


def _worlds_message(current_world_id: str, *, invalid: bool = False) -> DocumentMessage:
    services = current_game_services()
    current = services.world_views.require(current_world_id)
    builder = (
        M.document()
        .section("界门", icon="world")
        .field("当前登录", f"{current.skin.icon} {current.skin.name}")
    )
    if invalid:
        builder.line("没有找到这个世界")
    actions = []
    for index, view in enumerate(services.world_views.latest_views(), start=1):
        state = "已连接" if view.world.id == current.world.id else "可登录"
        builder.item(index, f"{view.skin.icon} {view.skin.name} | {state}")
        if view.world.id != current.world.id:
            actions.append(
                Action(
                    f"dimension.shift.{view.world.id}",
                    view.skin.name,
                    f"跃迁 {view.world.id}",
                    behavior="send",
                )
            )
    return builder.actions(tuple(actions)).build()


def _result_message(result: WorldShiftResult) -> DocumentMessage:
    services = current_game_services()
    if result.current is None:
        return _unavailable()
    current = services.world_view(result.current)
    if result.status == "main_action_occupied":
        return (
            M.document()
            .section("界标未稳", icon="notice")
            .line("当前正在进行主要行动，结束后才能跃迁")
            .action(current_action_action())
            .build()
        )
    if result.status == "already_there":
        return (
            M.document()
            .section("跃迁", icon="world")
            .field("当前世界", f"{current.skin.icon} {current.skin.name}")
            .line("界门已经连接这个世界")
            .build()
        )
    if result.status == "item_missing":
        return (
            M.document()
            .section("跃迁", icon="notice")
            .field("需要", f"{current.projector.name(DIMENSION_SHIFT_ITEM_ID)} x1")
            .line("纳戒中没有可用的跃迁凭证")
            .build()
        )
    if result.status == "shifted" and result.previous_world_id is not None:
        previous = services.world_views.require(result.previous_world_id)
        return (
            M.document()
            .section("跃迁", icon="world")
            .row(
                ("原世界", f"{previous.skin.icon} {previous.skin.name}"),
                ("当前世界", f"{current.skin.icon} {current.skin.name}"),
            )
            .field("消耗", f"{previous.projector.name(DIMENSION_SHIFT_ITEM_ID)} x1")
            .line("目标世界已完成化身重构")
            .note("角色档案、资产与构筑保持不变；地点按目标世界重新解析。")
            .build()
        )
    return _unavailable()


def _unavailable() -> DocumentMessage:
    return (
        M.document()
        .section("跃迁", icon="notice")
        .line("当前没有读取到世界连接状态，请稍后重试")
        .build()
    )


__all__ = ["dimension_shift"]
