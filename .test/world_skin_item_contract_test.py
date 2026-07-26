"""世界物品命名与业务层展示边界巡检。"""

from __future__ import annotations

import ast
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.content import (  # noqa: E402
    COMPANION_SANCTUARY_ITEM_ID,
    CULTIVATION_SKIN_ID,
    MAGIC_SKIN_ID,
    STELLAR_RING_SKIN_ID,
    assemble_official_catalog,
    select_world_skin,
)
from game.content.covenant import WORLD_INVARIANT_ITEM_IDS  # noqa: E402


BUSINESS_SOURCE_ROOTS = (
    ROOT / "game" / "cmd",
    ROOT / "game" / "features",
    ROOT / "game" / "rules",
)


def main() -> None:
    catalog = assemble_official_catalog()
    views = tuple(
        select_world_skin(catalog, skin_id)
        for skin_id in (
            CULTIVATION_SKIN_ID,
            MAGIC_SKIN_ID,
            STELLAR_RING_SKIN_ID,
        )
    )
    item_ids = tuple(catalog.items.definitions.ids())

    for item_id in item_ids:
        names = tuple(view.projector.name(item_id) for view in views)
        if item_id in WORLD_INVARIANT_ITEM_IDS:
            assert len(set(names)) == 1, (item_id, names)
        else:
            assert len(set(names)) == len(names), (item_id, names)

    assert tuple(
        view.projector.name(COMPANION_SANCTUARY_ITEM_ID) for view in views
    ) == ("万灵引", "幻兽庭钥印", "生态舱密钥")
    _assert_business_code_has_no_mutable_item_names(views, item_ids)
    print("world skin item contract tests passed")


def _assert_business_code_has_no_mutable_item_names(views, item_ids) -> None:
    mutable_names = {
        view.projector.name(item_id)
        for item_id in item_ids
        if item_id not in WORLD_INVARIANT_ITEM_IDS
        for view in views
        if len(view.projector.name(item_id)) >= 3
    }
    violations: list[str] = []
    for source_root in BUSINESS_SOURCE_ROOTS:
        for path in sorted(source_root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                matches = sorted(name for name in mutable_names if name in node.value)
                if matches:
                    relative = path.relative_to(ROOT)
                    violations.append(
                        f"{relative}:{node.lineno}: {', '.join(matches)}"
                    )
    assert not violations, "业务代码写死了世界可变物品名:\n" + "\n".join(violations)


if __name__ == "__main__":
    main()
