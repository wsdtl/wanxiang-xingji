"""真实世界地点移动与绑定上下文校验的唯一业务入口。"""

from game.core.gameplay import (
    MovePresence,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    WorldState,
    WorldTransaction,
)
from game.rules.character import CharacterWorldState, MULTIVERSE_WORLD_STATE_ID
from .models import WorldLocationIntent, WorldTravelResult, WorldTravelStorageKinds


class WorldTravelFeature:
    """只负责位置移动；地点具体功能继续归各自业务所有。"""

    def __init__(
        self,
        database,
        content,
        snapshots,
        player_activity,
        storage: WorldTravelStorageKinds,
    ) -> None:
        self.database = database
        self.content = content
        self.snapshots = snapshots
        self.player_activity = player_activity
        self.storage = storage

    def move(
        self,
        character_id: str,
        anchor_id: str,
        *,
        logical_time,
        intent: WorldLocationIntent | None = None,
    ) -> WorldTravelResult:
        with self.database.unit_of_work() as uow:
            activity_block = self.player_activity.block_in_uow(uow, character_id)
            if activity_block is not None:
                return WorldTravelResult(
                    activity_block.status,
                    activity_block=activity_block,
                )

            character_world = self.snapshots.require(
                uow,
                self.storage.character_world,
                character_id,
                CharacterWorldState,
            )
            if intent is not None and character_world.world_id != intent.world_id:
                return WorldTravelResult("stale_world")
            try:
                resolved = self.content.worlds.resolve(
                    character_world.world_id,
                    anchor_id,
                )
            except KeyError:
                return WorldTravelResult("unavailable")
            binding = resolved.binding
            if intent is not None and (
                binding.anchor_id != intent.anchor_id
                or binding.function_id != intent.function_id
                or binding.version != intent.binding_version
            ):
                return WorldTravelResult("stale_binding")

            world = self.snapshots.require(
                uow,
                self.storage.world,
                MULTIVERSE_WORLD_STATE_ID,
                WorldState,
            )
            presence = next(
                (
                    value
                    for value in world.presences.values()
                    if value.owner_id == character_id
                ),
                None,
            )
            if presence is None:
                raise RuntimeError("世界移动时找不到角色存在体")
            destination = resolved.position
            if presence.position.key == destination.key:
                return WorldTravelResult("already_there", binding.anchor_id)

            trace_id = (
                f"world-travel:{character_id}:{binding.anchor_id}:{world.revision}"
            )
            context = RuleContext(
                trace_id,
                "feature.world_travel.v1",
                Ruleset("ruleset.world_travel"),
                logical_time,
                SeededRandomSource(trace_id),
            )
            outcome = self.content.catalog.world_engine.execute(
                WorldTransaction(
                    trace_id,
                    character_id,
                    world.revision,
                    (MovePresence(presence.id, destination),),
                ),
                state=world,
                context=context,
            )
            if outcome.failure or outcome.value is None:
                return WorldTravelResult("failed")
            self.snapshots.update(
                uow,
                self.storage.world,
                MULTIVERSE_WORLD_STATE_ID,
                world,
                outcome.value.state,
                logical_time,
            )
            uow.commit()
            return WorldTravelResult("moved", binding.anchor_id)


__all__ = ["WorldTravelFeature"]
