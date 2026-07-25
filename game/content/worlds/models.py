"""正式玩法世界的显式聚合边界。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.gameplay import (
    MapAnchorDefinition,
    WorldDefinition,
    WorldLocationBinding,
)


@dataclass(frozen=True)
class OfficialWorldBundle:
    """组合一个真实世界的身份、物理锚点和功能绑定。"""

    world: WorldDefinition
    anchors: tuple[MapAnchorDefinition, ...]
    bindings: tuple[WorldLocationBinding, ...]

    def __post_init__(self) -> None:
        anchors = tuple(self.anchors)
        bindings = tuple(self.bindings)
        anchor_ids = {value.id for value in anchors}
        if not anchors or len(anchor_ids) != len(anchors):
            raise ValueError(f"世界锚点不能为空或重复：{self.world.id}")
        if self.world.spawn_anchor_id not in anchor_ids:
            raise ValueError(f"世界出生点不属于自身锚点：{self.world.id}")
        if not bindings:
            raise ValueError(f"世界地点绑定不能为空：{self.world.id}")
        if any(value.world_id != self.world.id for value in bindings):
            raise ValueError(f"世界 bundle 混入其他世界绑定：{self.world.id}")
        if any(value.anchor_id not in anchor_ids for value in bindings):
            raise ValueError(f"世界地点绑定引用了 bundle 外锚点：{self.world.id}")
        binding_keys = {(value.anchor_id, value.function_id) for value in bindings}
        if len(binding_keys) != len(bindings):
            raise ValueError(f"世界地点绑定重复：{self.world.id}")
        object.__setattr__(self, "anchors", anchors)
        object.__setattr__(self, "bindings", bindings)


__all__ = ["OfficialWorldBundle"]
