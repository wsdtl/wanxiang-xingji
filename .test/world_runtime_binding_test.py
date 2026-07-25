"""同坐标跨世界功能绑定与空间隔离测试。"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay import (  # noqa: E402
    MapAnchorDefinition,
    WorldCatalog,
    WorldDefinition,
    WorldLocationBinding,
    WorldRuntimeCatalog,
    WorldSpaceDefinition,
    WorldTopologyKind,
)
from game.features.world_travel import WorldLocationIntent  # noqa: E402


def main() -> None:
    physical = WorldCatalog()
    for space_id in ("world_space.a", "world_space.b", "world_space.c"):
        physical.spaces.register(
            WorldSpaceDefinition(space_id, WorldTopologyKind.GRID, -10, 10, -10, 10)
        )
    physical.finalize()
    anchor = MapAnchorDefinition("location.shared_xp3_yn2", 3, -2)
    runtime = WorldRuntimeCatalog(
        (
            WorldDefinition("world.a", "world_space.a", "skin.a", anchor.id),
            WorldDefinition("world.b", "world_space.b", "skin.b", anchor.id),
            WorldDefinition("world.c", "world_space.c", "skin.c", anchor.id),
        ),
        (anchor,),
        (
            WorldLocationBinding(
                "world.a",
                anchor.id,
                "location.function.exploration",
                "exploration.region.a",
                version=2,
            ),
            WorldLocationBinding(
                "world.b",
                anchor.id,
                "location.function.companion_person",
                "companion.person.b",
                version=4,
            ),
            WorldLocationBinding(
                "world.c",
                anchor.id,
                "location.function.exploration",
                "exploration.region.c",
                version=1,
            ),
        ),
        world_catalog=physical,
    )
    first = runtime.require_binding("world.a", anchor.id)
    second = runtime.require_binding("world.b", anchor.id)
    third = runtime.require_binding("world.c", anchor.id)
    assert first.function_id != second.function_id
    assert first.version == 2 and second.version == 4
    assert first.content_ref == "exploration.region.a"
    assert second.content_ref == "companion.person.b"
    assert third.content_ref == "exploration.region.c"
    assert runtime.position("world.a", anchor.id).space_id == "world_space.a"
    assert runtime.position("world.b", anchor.id).space_id == "world_space.b"
    assert runtime.position("world.c", anchor.id).space_id == "world_space.c"
    assert runtime.anchor_at("world.a", runtime.position("world.b", anchor.id)) is None
    resolved = runtime.resolve_position(
        "world.c",
        runtime.position("world.c", anchor.id),
        function_id="location.function.exploration",
    )
    assert resolved is not None
    assert resolved.require_content_ref() == "exploration.region.c"
    intent = WorldLocationIntent(
        "world.a",
        anchor.id,
        "location.function.exploration",
        2,
    )
    command = intent.command()
    assert command.startswith("前往 @world_location ")
    assert WorldLocationIntent.parse(command.removeprefix("前往 ")) == intent

    try:
        WorldRuntimeCatalog(
            (WorldDefinition("world.a", "world_space.a", "skin.a", anchor.id),),
            (anchor,),
            (
                WorldLocationBinding("world.a", anchor.id, "location.function.city"),
                WorldLocationBinding("world.a", anchor.id, "location.function.exploration"),
            ),
            world_catalog=physical,
        )
    except ValueError as exc:
        assert "世界地点绑定不能重复" in str(exc)
    else:
        raise AssertionError("同一世界坐标登记两个主功能时必须失败")

    print("world runtime binding tests passed")


if __name__ == "__main__":
    main()
