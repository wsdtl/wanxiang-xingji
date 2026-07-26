"""为战报补齐世界皮肤的机制名称。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from game.core.gameplay import SkinEntry


_EFFECT_SUFFIXES = {
    "strike": "主效",
    "support": "辅效",
    "passive": "常驻",
    "burn_status": "灼烧状态",
    "burn_tick": "灼烧结算",
    "poison_status": "中毒状态",
    "poison_tick": "毒伤结算",
    "bleed_status": "流血状态",
    "bleed_tick": "流血结算",
    "blood_cost": "血契代价",
    "shared_mark": "印记",
    "echo_status": "回响标记",
    "echo_release": "回响结算",
    "tier_1": "一阶",
    "tier_2": "二阶",
    "tier_3": "三阶",
    "tick.tier_1": "一阶结算",
    "tick.tier_2": "二阶结算",
    "tick.tier_3": "三阶结算",
}

_TRIGGER_SUFFIXES = {
    **_EFFECT_SUFFIXES,
    "strike": "主效触发",
    "support": "辅效触发",
    "passive": "常驻触发",
    "burn_tick": "灼烧触发",
    "poison_tick": "毒伤触发",
    "bleed_tick": "流血触发",
    "echo_release": "回响",
    "tier_1": "一阶触发",
    "tier_2": "二阶触发",
    "tier_3": "三阶触发",
    "tick.tier_1": "一阶结算触发",
    "tick.tier_2": "二阶结算触发",
    "tick.tier_3": "三阶结算触发",
}


def build_combat_mechanism_entries(
    *,
    effects: Iterable,
    triggers: Iterable,
    interceptors: Iterable,
    target_constraints: Iterable,
    damage_types: Iterable,
    controls: Iterable,
    owner_entries: Mapping[str, SkinEntry],
    base_effect_names: Mapping[str, str],
    damage_names: Mapping[str, str],
    interceptor_names: Mapping[str, str],
    constraint_names: Mapping[str, str],
    control_names: Mapping[str, str],
) -> dict[str, SkinEntry]:
    """用武器/装备已经投影出的名称，生成每个运行期机制的唯一可见名称。"""

    entries: dict[str, SkinEntry] = {}
    used_names = {entry.name for entry in owner_entries.values()}
    for definition in effects:
        content_id = str(definition.id)
        name = base_effect_names.get(content_id) or _owned_name(
            content_id,
            owner_entries,
            _EFFECT_SUFFIXES,
            "效果",
        )
        name = _reserve_name(name, used_names)
        entries[content_id] = SkinEntry(name=name)
        used_names.add(name)
    for definition in triggers:
        content_id = str(definition.id)
        name = _reserve_name(
            _owned_name(content_id, owner_entries, _TRIGGER_SUFFIXES, "触发"),
            used_names,
        )
        entries[content_id] = SkinEntry(name=name)
        used_names.add(name)
    for definition in interceptors:
        content_id = str(definition.id)
        name = _reserve_name(interceptor_names.get(content_id, "伤害拦截"), used_names)
        entries[content_id] = SkinEntry(name=name)
        used_names.add(name)
    for definition in target_constraints:
        content_id = str(definition.id)
        name = _reserve_name(constraint_names.get(content_id, "目标限制"), used_names)
        entries[content_id] = SkinEntry(name=name)
        used_names.add(name)
    for definition in damage_types:
        content_id = str(definition.id)
        name = _reserve_name(damage_names.get(content_id, "特殊伤害"), used_names)
        entries[content_id] = SkinEntry(name=name)
        used_names.add(name)
    for definition in controls:
        content_id = str(definition.id)
        name = _reserve_name(control_names.get(content_id, "控制状态"), used_names)
        entries[content_id] = SkinEntry(name=name)
        used_names.add(name)
    return entries


def build_enemy_behavior_mechanism_entries(
    display_owners: Mapping[str, str],
    behavior_entries: Mapping[str, SkinEntry],
) -> dict[str, SkinEntry]:
    """为独立敌技 Effect/Trigger 建立世界内术语，不借用武器名称。"""

    entries: dict[str, SkinEntry] = {}
    used_names = {value.name for value in behavior_entries.values()}
    for content_id, behavior_key in display_owners.items():
        ability = behavior_entries[f"ability.enemy.{behavior_key}"]
        suffix = content_id.rsplit(".", 1)[-1]
        labels = _TRIGGER_SUFFIXES if content_id.startswith("trigger.") else _EFFECT_SUFFIXES
        visible_suffix = labels.get(suffix, "触发" if content_id.startswith("trigger.") else "效果")
        name = _reserve_name(f"{ability.name}·{visible_suffix}", used_names)
        entries[content_id] = SkinEntry(
            name=name,
            compact_name=f"{behavior_entries[f'enemy.behavior.{behavior_key}'].name}·{visible_suffix}",
        )
        used_names.add(name)
    return entries


def _owned_name(
    content_id: str,
    owner_entries: Mapping[str, SkinEntry],
    suffixes: Mapping[str, str],
    fallback: str,
) -> str:
    parts = content_id.split(".")
    if len(parts) >= 4 and parts[1] in {"weapon", "equipment"}:
        owner_kind = parts[1]
        owner_key = parts[2]
        owner_id = (
            f"weapon.{owner_key}"
            if owner_kind == "weapon"
            else f"property.equipment.{owner_key}"
        )
        owner = owner_entries.get(owner_id)
        owner_name = owner.name if owner is not None else owner_key
        suffix = ".".join(parts[3:])
        visible_suffix = suffixes.get(suffix)
        if visible_suffix is not None:
            return f"{owner_name}·{visible_suffix}"
        return f"{owner_name}·{suffix.replace('_', ' ')}{fallback}"
    return f"{content_id.rsplit('.', 1)[-1]}·{fallback}"


def _reserve_name(name: str, used_names: set[str]) -> str:
    if name not in used_names:
        return name
    candidate = f"{name}·战斗机制"
    if candidate not in used_names:
        return candidate
    index = 2
    while f"{name}·战斗机制{index}" in used_names:
        index += 1
    return f"{name}·战斗机制{index}"


__all__ = [
    "build_combat_mechanism_entries",
    "build_enemy_behavior_mechanism_entries",
]
