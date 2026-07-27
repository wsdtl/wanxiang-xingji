"""当前世界地点名称在命令层的统一解析与链接格式。"""

from __future__ import annotations

from game.content.catalog.world import (
    LOCATION_FUNCTION_CITY,
    LOCATION_FUNCTION_COMPANION_PERSON,
    LOCATION_FUNCTION_EXPLORATION,
)
from message import Action


def current_world_location_name(view, binding) -> str:
    """读取绑定在角色当前世界中的玩家可见名称。"""

    display_id = binding.display_ref or binding.anchor_id
    return view.projector.name(display_id)


def current_world_location_command(view, binding) -> str:
    """构造不泄露内部世界、锚点或功能 ID 的前往命令。"""

    return f"前往 {current_world_location_name(view, binding)}"


def current_world_location_action(binding) -> Action:
    """按地点功能给出抵达后的下一步，而不是把所有地点当成探险区域。"""

    if binding.function_id == LOCATION_FUNCTION_EXPLORATION:
        return Action(
            "world-location.exploration",
            "开始探险",
            "开始探险",
            behavior="callback",
        )
    if binding.function_id == LOCATION_FUNCTION_COMPANION_PERSON:
        return Action(
            "world-location.person",
            "查看人物",
            "人物",
            behavior="callback",
        )
    if binding.function_id == LOCATION_FUNCTION_CITY:
        return Action(
            "world-location.city",
            "查看地图",
            "地图",
            behavior="callback",
        )
    return Action(
        "world-location.map",
        "查看地图",
        "地图",
        behavior="callback",
    )


def resolve_current_world_location(value: object, view, worlds):
    """按当前世界皮肤的名称或别名解析地点绑定。"""

    display_id = view.projector.resolve_alias(value)
    if display_id is None:
        return None
    return worlds.binding_for_display(view.world.id, display_id)


__all__ = [
    "current_world_location_action",
    "current_world_location_command",
    "current_world_location_name",
    "resolve_current_world_location",
]
