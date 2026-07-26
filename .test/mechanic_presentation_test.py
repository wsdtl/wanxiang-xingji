"""正式机制目录、三界皮肤、分页与详情解释门禁。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.cmd.特效.service import PAGE_SIZE, _catalog_message  # noqa: E402
from game.content import WorldViewCatalog, assemble_official_catalog  # noqa: E402
from game.content.presentation import (  # noqa: E402
    MechanicPresentationError,
    MechanicProjector,
)
from launch.adapter.qq.render import render_qq_message  # noqa: E402


EXPECTED_CATEGORIES = {
    "武器核心": 74,
    "武器词条": 24,
    "装备特效": 24,
    "装备词条": 24,
    "套装效果": 18,
}


def main() -> None:
    catalog = assemble_official_catalog()
    views = WorldViewCatalog(catalog).latest_views()
    assert PAGE_SIZE == 50
    assert len(views) == 3

    for view in views:
        projector = MechanicProjector(catalog, view.projector)
        entries = projector.catalog_entries()
        assert len(entries) == 164
        assert Counter(value.category for value in entries) == EXPECTED_CATEGORIES
        assert len({value.name for value in entries}) == len(entries)

        for entry in entries:
            assert projector.resolve(entry.name) == entry.id
            detail = projector.detail(entry.id)
            assert detail.name == entry.name
            assert detail.category == entry.category
            assert detail.tiers
            assert all(tier.lines for tier in detail.tiers)
            visible = " ".join(
                (
                    detail.name,
                    detail.category,
                    detail.description,
                    *(line for tier in detail.tiers for line in tier.lines),
                )
            )
            for internal_prefix in (
                "property.",
                "ability.",
                "trigger.",
                "effect.",
                "attribute.",
            ):
                assert internal_prefix not in visible

        core = projector.detail("property.weapon_core.aegis_parasol")
        assert len(core.tiers) == 1
        assert core.tiers[0].label == "固定机制"
        assert any(line.startswith("能力：") for line in core.tiers[0].lines)

        ordinary = projector.detail("property.equipment.attack")
        assert tuple(value.label for value in ordinary.tiers) == ("T1", "T2", "T3")
        assert all("至" in value.lines[0] and "步长" in value.lines[0] for value in ordinary.tiers)

        triggered = projector.detail("property.equipment.thorns")
        assert tuple(value.label for value in triggered.tiers) == ("T1", "T2", "T3")
        assert all(any(line.startswith("触发：") for line in value.lines) for value in triggered.tiers)
        assert all(any("本次实际伤害" in line for line in value.lines) for value in triggered.tiers)

        healing_set = projector.detail("equipment_set.everlife")
        assert any(
            "本次实际恢复量" in line
            for tier in healing_set.tiers
            for line in tier.lines
        )

        basic_attack = projector.detail("ability.basic_attack")
        assert basic_attack.category == "能力"
        assert basic_attack.tiers[0].label == "固定机制"
        assert any(line.startswith("目标：") for line in basic_attack.tiers[0].lines)

        behavior_id = "enemy.behavior.heavy_strike"
        behavior_name = view.projector.name(behavior_id)
        assert projector.resolve(behavior_id) == behavior_id
        assert projector.resolve(behavior_name) == behavior_id
        behavior = projector.detail(behavior_id)
        assert behavior.name == behavior_name
        assert behavior.category == "战斗机制"
        assert behavior.tiers[0].label == "固定机制"
        assert any(line.startswith("能力：") for line in behavior.tiers[0].lines)

        definition = projector.properties["property.equipment.attack"]
        tier = definition.tiers[0]
        parameter = tier.parameters[0]
        actual = projector.roll_summary(
            definition.id,
            tier.tier,
            {parameter.id: parameter.minimum},
        )
        assert view.projector.name(parameter.attribute_id) in actual
        assert "+" in actual

        try:
            projector._magnitude(object())
            raise AssertionError("未知数值表达式必须被展示门禁拒绝")
        except MechanicPresentationError as exc:
            assert "尚未支持" in str(exc)

        first_page = _catalog_message(1, view.skin.name, projector)
        payload = render_qq_message(first_page)
        assert payload["content"].count("mqqapi://aio/inlinecmd") == 50
        assert payload["content"].count("enter=true") == 50
        assert tuple(value.data for value in first_page.document.actions) == (
            "特效 全部 2",
            "特效",
        )

        last_page = _catalog_message(4, view.skin.name, projector)
        last_payload = render_qq_message(last_page)
        assert last_payload["content"].count("mqqapi://aio/inlinecmd") == 14
        assert tuple(value.data for value in last_page.document.actions) == (
            "特效 全部 3",
            "特效",
        )

    expected_controls = {
        "太玄界": "眩晕",
        "魔法世界": "眩晕",
        "星环界": "震荡失能",
    }
    for view in views:
        detail = MechanicProjector(catalog, view.projector).detail(
            "property.equipment.critical_stun"
        )
        assert expected_controls[view.skin.name] in " ".join(
            line for tier in detail.tiers for line in tier.lines
        )

    print("mechanic presentation tests passed")


if __name__ == "__main__":
    main()
