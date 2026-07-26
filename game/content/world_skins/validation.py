"""具体世界皮肤共享的展示完整性校验。"""

from collections.abc import Iterable

from game.core.gameplay import (
    SkinEntry,
    SkinPack,
    StableId,
    character_name_display_width,
)

from ..catalog import CHARACTER_REALMS


def build_character_realm_entries(
    names: tuple[tuple[str, str], ...],
) -> dict[str, SkinEntry]:
    """把完整名和短名映射到稳定境界 ID。"""

    if len(names) != len(CHARACTER_REALMS):
        raise ValueError("世界皮肤必须完整提供 19 个人物境界名称")
    invalid = tuple(
        compact_name
        for _, compact_name in names
        if character_name_display_width(compact_name) > 8
    )
    if invalid:
        raise ValueError(f"人物境界短名显示宽度不能超过 8: {', '.join(invalid)}")
    return {
        realm.id: SkinEntry(name=full_name, compact_name=compact_name)
        for realm, (full_name, compact_name) in zip(CHARACTER_REALMS, names)
    }


def validate_distinct_item_skin_names(
    skins: tuple[SkinPack, ...],
    item_ids: Iterable[StableId],
    *,
    invariant_item_ids: frozenset[StableId],
) -> None:
    """除明确恒定物品外，每个世界必须提供独立物品名。"""

    conflicts: list[str] = []
    for item_id in sorted(set(item_ids) - set(invariant_item_ids)):
        names = tuple(skin.entries[item_id].name for skin in skins)
        if len(names) != len(set(names)):
            projected = ", ".join(
                f"{skin.id}={name}" for skin, name in zip(skins, names)
            )
            conflicts.append(f"{item_id}: {projected}")
    if conflicts:
        raise ValueError(
            "非恒定物品不能跨世界共用名称：" + "; ".join(conflicts)
        )


__all__ = [
    "build_character_realm_entries",
    "validate_distinct_item_skin_names",
]
