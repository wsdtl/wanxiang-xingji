"""全服活动注册、热点窗口和稳定排序测试。"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.content.catalog.activity import (  # noqa: E402
    GLOBAL_ACTIVITY_CLOSING_WINDOW,
    GLOBAL_ACTIVITY_OPENING_WINDOW,
    GLOBAL_ACTIVITY_SPOTLIGHT_LIMIT,
)
from game.core.gameplay import (  # noqa: E402
    ActivityCatalog,
    ActivityDefinition,
    ActivityInstance,
    ActivityState,
    ActivityStatus,
    SkinEntry,
    SkinPack,
    SkinProjector,
)
from game.rules.activity import (  # noqa: E402
    GLOBAL_ACTIVITY_SCOPE_ID,
    ActivitySpotlightPolicy,
    GlobalActivityCatalog,
    GlobalActivityRegistration,
)


TIME = datetime(2026, 7, 15, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
    _assert_content_defaults()
    _assert_spotlight_windows_and_filtering()
    _assert_sorting_and_limit()
    _assert_registration_validation()
    _assert_scope_and_time_boundaries()
    print("global activity registration tests passed")


def _assert_content_defaults() -> None:
    policy = ActivitySpotlightPolicy()
    assert policy.opening_window == GLOBAL_ACTIVITY_OPENING_WINDOW
    assert policy.closing_window == GLOBAL_ACTIVITY_CLOSING_WINDOW
    assert GLOBAL_ACTIVITY_SPOTLIGHT_LIMIT == 2


def _assert_spotlight_windows_and_filtering() -> None:
    catalog = GlobalActivityCatalog()
    catalog.register(GlobalActivityRegistration("activity.long", priority=1))
    catalog.register(GlobalActivityRegistration("activity.short", priority=2))
    catalog.register(GlobalActivityRegistration("activity.closing", priority=3))
    state = ActivityState(
        GLOBAL_ACTIVITY_SCOPE_ID,
        {
            "long": _open("long", "activity.long", TIME - timedelta(days=1), TIME + timedelta(days=1)),
            "short": _open("short", "activity.short", TIME - timedelta(hours=10), TIME + timedelta(hours=10)),
            "closing": _open("closing", "activity.closing", TIME - timedelta(days=2), TIME + timedelta(hours=6)),
            "hidden": _open("hidden", "activity.unregistered", TIME - timedelta(hours=1), TIME + timedelta(hours=1)),
        },
    )

    assert [view.instance.id for view in catalog.active(state, logical_time=TIME)] == [
        "closing",
        "short",
        "long",
    ]
    selection = catalog.spotlight(state, logical_time=TIME)
    assert [view.instance.id for view in selection.activities] == ["closing", "short"]
    assert selection.additional_count == 0

    long = state.instances["long"]
    policy = ActivitySpotlightPolicy()
    assert policy.visible(long, long.opens_at + timedelta(hours=1))
    assert not policy.visible(long, TIME)
    assert policy.visible(long, long.closes_at - timedelta(hours=1))
    assert policy.visible(state.instances["short"], TIME)


def _assert_sorting_and_limit() -> None:
    catalog = GlobalActivityCatalog()
    for definition_id, priority in (
        ("activity.a", 5),
        ("activity.b", 10),
        ("activity.c", 10),
        ("activity.d", 1),
    ):
        catalog.register(GlobalActivityRegistration(definition_id, priority=priority))
    state = ActivityState(
        GLOBAL_ACTIVITY_SCOPE_ID,
        {
            "a": _open("a", "activity.a", TIME - timedelta(hours=1), TIME + timedelta(hours=5)),
            "b": _open("b", "activity.b", TIME - timedelta(hours=1), TIME + timedelta(hours=4)),
            "c": _open("c", "activity.c", TIME - timedelta(hours=2), TIME + timedelta(hours=4)),
            "d": _open("d", "activity.d", TIME - timedelta(hours=1), TIME + timedelta(hours=6)),
        },
    )
    selection = catalog.spotlight(state, logical_time=TIME, limit=2)
    assert [view.instance.id for view in selection.activities] == ["c", "b"]
    assert selection.additional_count == 2


def _assert_registration_validation() -> None:
    definitions = ActivityCatalog()
    for definition_id in ("activity.valid", "activity.missing", "activity.wide"):
        definitions.register(ActivityDefinition(definition_id, 1))
    definitions.finalize()

    valid = GlobalActivityRegistration("activity.valid", entry_intent_id="activity.enter")
    catalog = GlobalActivityCatalog()
    assert catalog.register(valid) is valid
    assert catalog.register(valid) is valid
    try:
        catalog.register(GlobalActivityRegistration("activity.valid", priority=1))
        raise AssertionError("冲突注册必须失败")
    except ValueError:
        pass
    catalog.validate(definitions, _projector({"activity.valid": SkinEntry("完整活动", compact_name="短活动")}))

    for definition_id, entry in (
        ("activity.missing", SkinEntry("没有短名")),
        ("activity.wide", SkinEntry("完整活动", compact_name="五个汉字名")),
    ):
        invalid = GlobalActivityCatalog()
        invalid.register(GlobalActivityRegistration(definition_id))
        try:
            invalid.validate(definitions, _projector({definition_id: entry}))
            raise AssertionError("缺失或过长的活动短名必须失败")
        except ValueError:
            pass


def _assert_scope_and_time_boundaries() -> None:
    catalog = GlobalActivityCatalog()
    catalog.register(GlobalActivityRegistration("activity.valid"))
    wrong_scope = ActivityState(
        "activity.scope.player",
        {"valid": _open("valid", "activity.valid", TIME - timedelta(hours=1), TIME + timedelta(hours=1))},
    )
    try:
        catalog.active(wrong_scope, logical_time=TIME)
        raise AssertionError("非全服作用域必须失败")
    except ValueError:
        pass
    try:
        catalog.active(None, logical_time=TIME.replace(tzinfo=None))
        raise AssertionError("无时区逻辑时间必须失败")
    except ValueError:
        pass


def _open(
    instance_id: str,
    definition_id: str,
    opens_at: datetime,
    closes_at: datetime,
) -> ActivityInstance:
    return ActivityInstance(
        instance_id,
        definition_id,
        1,
        opens_at,
        closes_at,
        status=ActivityStatus.OPEN,
    )


def _projector(entries: dict[str, SkinEntry]) -> SkinProjector:
    return SkinProjector(SkinPack("skin.activity_test", 1, "测试皮肤", entries=entries))


if __name__ == "__main__":
    main()
