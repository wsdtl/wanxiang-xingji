"""官方基础名录、多世界皮肤和统一装配边界测试。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.content import (  # noqa: E402
    BREAKTHROUGH_TOKEN_ITEM_ID,
    BREAKTHROUGH_TOKEN_ITEM_TAG,
    BASIC_ATTACK_ABILITY_ID,
    BASIC_COMBAT_FEATURE_ID,
    CATALOG_PACKAGE,
    CHARACTER_LEVEL_EXPERIENCE_REQUIREMENTS,
    CHARACTER_REALMS,
    DEFAULT_CHARACTER_TEMPLATE_ID,
    COMMON_QUALITY_ID,
    CULTIVATION_SKIN,
    CULTIVATION_SKIN_ID,
    DEFAULT_SKIN_ID,
    DRAW_TICKET_ITEM_ID,
    DIMENSION_SHIFT_ITEM_ID,
    EPIC_QUALITY_ID,
    FINE_QUALITY_ID,
    INSCRIPTION_FEATHER_ITEM_ID,
    LARGE_HEALTH_MEDICINE_ABILITY_ID,
    LARGE_HEALTH_MEDICINE_ITEM_ID,
    LARGE_MEDICINE_RECOVERY_RATIO,
    LARGE_SPIRIT_MEDICINE_ABILITY_ID,
    LARGE_SPIRIT_MEDICINE_ITEM_ID,
    LEGENDARY_QUALITY_ID,
    MAGIC_SKIN,
    MAGIC_SKIN_ID,
    STELLAR_RING_SKIN,
    STELLAR_RING_SKIN_ID,
    MEDIUM_HEALTH_MEDICINE_ABILITY_ID,
    MEDIUM_HEALTH_MEDICINE_ITEM_ID,
    MEDIUM_MEDICINE_RECOVERY_RATIO,
    MEDIUM_SPIRIT_MEDICINE_ABILITY_ID,
    MEDIUM_SPIRIT_MEDICINE_ITEM_ID,
    PRIMARY_CURRENCY_ID,
    QUALITY_IDS,
    RARE_QUALITY_ID,
    SMALL_HEALTH_MEDICINE_ABILITY_ID,
    SMALL_HEALTH_MEDICINE_ITEM_ID,
    SMALL_MEDICINE_RECOVERY_RATIO,
    SMALL_SPIRIT_MEDICINE_ABILITY_ID,
    SMALL_SPIRIT_MEDICINE_ITEM_ID,
    SPECIAL_ITEM_STACK_LIMIT,
    SPECIAL_ITEM_TAG,
    SPECIAL_STORAGE_TAG,
    STARTING_CITY_ID,
    STARTER_WEAPON_ITEM_ID,
    TAIXUAN_WORLD_ID,
    coordinate_token,
    validate_anchor_coordinate_id,
    WORLD_SKIN_PACKAGE,
    WORLD_PACKAGE,
    OFFICIAL_PACKAGES,
    assemble_official_catalog,
    character_realm_for_level,
    select_world_skin,
    special_item_definition,
)
from game.core.gameplay import (  # noqa: E402
    AttributeMagnitude,
    ContentAssembler,
    CurrencyDefinition,
    ITEM_ABILITY_COMPONENT_ID,
    ITEM_STORAGE_COMPONENT_ID,
    ItemAssetKind,
    ItemAbilityComponent,
    ItemStorageComponent,
    LoadoutState,
    MapAnchorDefinition,
    character_name_display_width,
    resolve_package_order,
)
from game.content.catalog.world_progress import WORLD_PROGRESS_DEFINITION  # noqa: E402


def main() -> None:
    catalog = assemble_official_catalog()
    progress_reward_ids = {
        reward.definition_id
        for milestone in WORLD_PROGRESS_DEFINITION.milestones
        for reward in milestone.item_rewards
    } | {
        reward.definition_id
        for reward in WORLD_PROGRESS_DEFINITION.world_completion_rewards
    }
    assert progress_reward_ids == {
        DRAW_TICKET_ITEM_ID,
        DIMENSION_SHIFT_ITEM_ID,
    }
    assert progress_reward_ids <= set(catalog.items.definitions.ids())

    assert tuple(value.id for value in catalog.report.packages) == tuple(
        value.manifest.id for value in resolve_package_order(OFFICIAL_PACKAGES)
    )
    assert str(CATALOG_PACKAGE.manifest.version) == "3.28.0"
    assert str(WORLD_SKIN_PACKAGE.manifest.version) == "3.21.0"
    assert str(WORLD_PACKAGE.manifest.version) == "2.0.0"
    assert len(catalog.report.content_fingerprint) == 64
    assert catalog.report.display_content_ids == frozenset(
        content_id
        for package in OFFICIAL_PACKAGES
        for content_id in (
            *package.display_content_ids,
            *(
                scoped_id
                for scoped_ids in package.skin_display_content_ids.values()
                for scoped_id in scoped_ids
            ),
        )
    )
    progression = catalog.characters.progressions.require("progression.character_level")
    assert progression.maximum_level == 100
    assert len(CHARACTER_REALMS) == 19
    assert (character_realm_for_level(1).minimum_level, character_realm_for_level(10).maximum_level) == (1, 10)
    assert (character_realm_for_level(81).minimum_level, character_realm_for_level(90).maximum_level) == (81, 90)
    assert character_realm_for_level(91).minimum_level == 91
    assert character_realm_for_level(100).maximum_level == 100
    assert character_realm_for_level(91).id != character_realm_for_level(92).id
    assert progression.experience_requirements == CHARACTER_LEVEL_EXPERIENCE_REQUIREMENTS
    assert progression.required_for_next_level(80) == 6_359_356
    assert progression.required_for_next_level(90) == 10_356_800
    assert progression.required_for_next_level(99) == 13_380_764
    assert sum(progression.experience_requirements) == 270_305_413
    assert catalog.characters.templates.require(DEFAULT_CHARACTER_TEMPLATE_ID)
    assert QUALITY_IDS == (
        COMMON_QUALITY_ID,
        FINE_QUALITY_ID,
        RARE_QUALITY_ID,
        EPIC_QUALITY_ID,
        LEGENDARY_QUALITY_ID,
    )
    assert tuple(catalog.qualities.require(value).rank for value in QUALITY_IDS) == tuple(
        range(5)
    )
    _assert_medicine_catalog(catalog)
    _assert_nacre_item_categories(catalog)
    breakthrough = catalog.items.require(BREAKTHROUGH_TOKEN_ITEM_ID)
    assert breakthrough.tags.has(BREAKTHROUGH_TOKEN_ITEM_TAG)
    assert not breakthrough.tags.has(SPECIAL_ITEM_TAG)
    assert breakthrough.tags.has(SPECIAL_STORAGE_TAG)
    assert catalog.items.require(STARTER_WEAPON_ITEM_ID).tags.has("item.armament")
    basic_combat = catalog.characters.features.require(BASIC_COMBAT_FEATURE_ID)
    assert BASIC_ATTACK_ABILITY_ID in basic_combat.contribution.abilities
    city = catalog.world_runtime.require_anchor(
        catalog.world_runtime.require_world(TAIXUAN_WORLD_ID).spawn_anchor_id
    )
    assert (city.x, city.y) == (0, 0)
    assert coordinate_token(12) == "p12"
    assert coordinate_token(-12) == "n12"
    validate_anchor_coordinate_id(city)
    try:
        validate_anchor_coordinate_id(
            MapAnchorDefinition("location.main_city_xp1_y0", x=2, y=0)
        )
        raise AssertionError("地点 ID 后缀必须与真实坐标一致")
    except ValueError as exc:
        assert "坐标后缀" in str(exc)
    assert not LoadoutState("empty-loadout-character").slots
    assert catalog.skins.frozen
    assert catalog.skins.skin_ids() == (
        CULTIVATION_SKIN_ID,
        MAGIC_SKIN_ID,
        STELLAR_RING_SKIN_ID,
    )

    cultivation = select_world_skin(catalog, DEFAULT_SKIN_ID)
    magic = select_world_skin(catalog, MAGIC_SKIN_ID)
    stellar = select_world_skin(catalog, STELLAR_RING_SKIN_ID)
    assert cultivation.catalog is magic.catalog is stellar.catalog
    assert cultivation.skin.name == "太玄界"
    assert cultivation.skin.version == 27
    assert cultivation.skin.icon == "☯"
    assert cultivation.projector.name(PRIMARY_CURRENCY_ID) == "灵石"
    assert tuple(cultivation.projector.name(value) for value in QUALITY_IDS) == (
        "黄",
        "玄",
        "地",
        "天",
        "圣",
    )
    assert magic.skin.name == "魔法世界"
    assert magic.skin.version == 26
    assert magic.skin.icon == "✦"
    assert magic.projector.name(PRIMARY_CURRENCY_ID) == "魔晶"
    assert magic.projector.name(COMMON_QUALITY_ID) == "普通"
    assert stellar.skin.name == "星环界"
    assert stellar.skin.version == 4
    assert stellar.skin.icon == "◎"
    assert stellar.projector.name(PRIMARY_CURRENCY_ID) == "星铢"
    assert cultivation.projector.name(INSCRIPTION_FEATHER_ITEM_ID) == "铭刻之羽"
    assert magic.projector.name(INSCRIPTION_FEATHER_ITEM_ID) == "铭刻之羽"
    assert cultivation.projector.name(DRAW_TICKET_ITEM_ID) == "流光签"
    assert magic.projector.name(DRAW_TICKET_ITEM_ID) == "星辉秘券"
    assert stellar.projector.name(DRAW_TICKET_ITEM_ID) == "未定序列券"
    assert cultivation.projector.name(BREAKTHROUGH_TOKEN_ITEM_ID) == "问道玉契"
    assert magic.projector.name(BREAKTHROUGH_TOKEN_ITEM_ID) == "星界升格契印"
    assert cultivation.projector.name(DIMENSION_SHIFT_ITEM_ID) == "渡界玉符"
    assert magic.projector.name(DIMENSION_SHIFT_ITEM_ID) == "位面跃迁晶核"
    assert tuple(magic.projector.name(value) for value in QUALITY_IDS) == (
        "普通",
        "精良",
        "稀有",
        "史诗",
        "传说",
    )
    assert tuple(
        cultivation.projector.name(value)
        for value in (
            SMALL_HEALTH_MEDICINE_ITEM_ID,
            MEDIUM_HEALTH_MEDICINE_ITEM_ID,
            LARGE_HEALTH_MEDICINE_ITEM_ID,
            SMALL_SPIRIT_MEDICINE_ITEM_ID,
            MEDIUM_SPIRIT_MEDICINE_ITEM_ID,
            LARGE_SPIRIT_MEDICINE_ITEM_ID,
        )
    ) == ("小还丹", "中还丹", "大还丹", "小回灵丹", "中回灵丹", "大回灵丹")
    assert cultivation.projector.name(STARTING_CITY_ID) == "太玄仙城"
    assert magic.projector.name(STARTING_CITY_ID) == "星辉王城"
    assert stellar.projector.name(STARTING_CITY_ID) == "环心天城"
    first_realm = character_realm_for_level(1).id
    late_realm = character_realm_for_level(98).id
    assert cultivation.projector.name(first_realm) == "未入道"
    assert cultivation.projector.compact_name(first_realm) == "未入道"
    assert cultivation.projector.name(late_realm) == "太乙金仙"
    assert magic.projector.name(first_realm) == "见习者"
    assert magic.projector.compact_name(first_realm) == "见习"
    assert magic.projector.name(late_realm) == "主神"
    assert stellar.projector.name(first_realm) == "新晋登记者"
    assert stellar.projector.name(late_realm) == "星环执掌者"
    for realm in CHARACTER_REALMS:
        assert character_name_display_width(
            cultivation.projector.compact_name(realm.id)
        ) <= 8
        assert character_name_display_width(
            magic.projector.compact_name(realm.id)
        ) <= 8
        assert character_name_display_width(
            stellar.projector.compact_name(realm.id)
        ) <= 8

    _assert_new_display_content_requires_all_skins()
    print("official content tests passed")


def _assert_medicine_catalog(catalog) -> None:
    medicines = (
        (
            SMALL_HEALTH_MEDICINE_ITEM_ID,
            SMALL_HEALTH_MEDICINE_ABILITY_ID,
            SMALL_MEDICINE_RECOVERY_RATIO,
        ),
        (
            MEDIUM_HEALTH_MEDICINE_ITEM_ID,
            MEDIUM_HEALTH_MEDICINE_ABILITY_ID,
            MEDIUM_MEDICINE_RECOVERY_RATIO,
        ),
        (
            LARGE_HEALTH_MEDICINE_ITEM_ID,
            LARGE_HEALTH_MEDICINE_ABILITY_ID,
            LARGE_MEDICINE_RECOVERY_RATIO,
        ),
        (
            SMALL_SPIRIT_MEDICINE_ITEM_ID,
            SMALL_SPIRIT_MEDICINE_ABILITY_ID,
            SMALL_MEDICINE_RECOVERY_RATIO,
        ),
        (
            MEDIUM_SPIRIT_MEDICINE_ITEM_ID,
            MEDIUM_SPIRIT_MEDICINE_ABILITY_ID,
            MEDIUM_MEDICINE_RECOVERY_RATIO,
        ),
        (
            LARGE_SPIRIT_MEDICINE_ITEM_ID,
            LARGE_SPIRIT_MEDICINE_ABILITY_ID,
            LARGE_MEDICINE_RECOVERY_RATIO,
        ),
    )
    for item_id, ability_id, recovery_ratio in medicines:
        item = catalog.items.require(item_id)
        assert item.tags.has("storage.special")
        component = item.component(ITEM_ABILITY_COMPONENT_ID, ItemAbilityComponent)
        storage = item.component(ITEM_STORAGE_COMPONENT_ID, ItemStorageComponent)
        assert storage.unit_space == 1
        assert component.ability_id == ability_id and component.consume_quantity == 1
        ability = catalog.abilities.require(ability_id)
        assert len(ability.effects) == 1
        effect = catalog.effects.require(ability.effects[0].effect_id)
        assert len(effect.operations) == 1
        magnitude = effect.operations[0].magnitude
        assert isinstance(magnitude, AttributeMagnitude)
        assert magnitude.scale == recovery_ratio


def _assert_nacre_item_categories(catalog) -> None:
    feather = catalog.items.require(INSCRIPTION_FEATHER_ITEM_ID)
    assert feather.asset_kind is ItemAssetKind.INSTANCE
    assert feather.tags.has("item.inscription_medium")
    assert feather.tags.has("storage.inscription")
    assert not feather.tags.has(SPECIAL_STORAGE_TAG)
    assert not feather.tags.has("item.consumable")
    assert not feather.tags.has(SPECIAL_ITEM_TAG)

    special = special_item_definition(
        "item.special.test_talisman",
        use_components={
            ITEM_ABILITY_COMPONENT_ID: ItemAbilityComponent("ability.test_talisman")
        },
    )
    assert special.asset_kind is ItemAssetKind.STACK
    assert special.stack_limit == SPECIAL_ITEM_STACK_LIMIT
    assert special.tags.has("item.consumable")
    assert special.tags.has(SPECIAL_ITEM_TAG)
    assert special.tags.has(SPECIAL_STORAGE_TAG)
    assert not special.tags.has("item.medicine")
    try:
        special_item_definition("item.special.invalid", use_components={})
        raise AssertionError("特殊物品不能缺少类型化使用组件")
    except ValueError as exc:
        assert "使用组件" in str(exc)


def _assert_new_display_content_requires_all_skins() -> None:
    required = frozenset(
        {PRIMARY_CURRENCY_ID, COMMON_QUALITY_ID, "item.example"}
    )
    for skin in (CULTIVATION_SKIN, MAGIC_SKIN, STELLAR_RING_SKIN):
        try:
            skin.validate(required)
            raise AssertionError("新增展示内容必须同步补齐全部世界皮肤")
        except ValueError as exc:
            assert "缺少条目" in str(exc)

    changed_catalog = replace(
        CATALOG_PACKAGE,
        currencies=(
            *CATALOG_PACKAGE.currencies,
            CurrencyDefinition("currency.new_for_test"),
        ),
        display_content_ids=(
            CATALOG_PACKAGE.display_content_ids | {"currency.new_for_test"}
        ),
    )
    try:
        ContentAssembler().assemble(
            (changed_catalog, WORLD_SKIN_PACKAGE, WORLD_PACKAGE)
        )
        raise AssertionError("完整装配不能接受缺少世界皮肤名称的新内容")
    except ValueError as exc:
        assert "缺少条目" in str(exc)


if __name__ == "__main__":
    main()
