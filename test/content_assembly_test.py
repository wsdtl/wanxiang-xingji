"""内容包依赖、统一组装、跨目录校验、冻结和指纹测试。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, time
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.gameplay import (  # noqa: E402
    AbilityDefinition,
    AbilityUse,
    DealDamage,
    DrawCommand,
    DrawPoolDefinition,
    EffectDefinition,
    EffectReference,
    LootEntry,
    LootGroup,
    LootGroupMode,
    LootState,
    LootTableDefinition,
    ModifierLayer,
    RuleContext,
    RuleEntity,
    Ruleset,
    SeededRandomSource,
    SkinEntry,
    SkinPack,
    TagSet,
)
from game.core.gameplay.character import (  # noqa: E402
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    COMBAT_SPEED,
    HEALTH_MAXIMUM,
    SPIRIT_MAXIMUM,
    CharacterFeatureDefinition,
    CharacterTemplateDefinition,
    ContributionSpec,
    ProgressionDefinition,
    core_attribute_definitions,
    persistent_resource_definitions,
)
from game.core.gameplay.combat import CombatStats, DamageTypeDefinition, RecoveryStats  # noqa: E402
from game.core.gameplay.content import (  # noqa: E402
    CONTENT_FOUNDATION_VERSION,
    CombatProfileDefinition,
    ContentAssembler,
    ContentPackage,
    ContentPackageManifest,
    ContentVersion,
    MagnitudeRegistration,
    PackageRequirement,
    resolve_package_order,
)
from game.core.gameplay.cycles import CalendarSchedule, CalendarUnit, CycleDefinition  # noqa: E402
from game.core.gameplay.economy import CurrencyDefinition  # noqa: E402
from game.core.gameplay.equipment import (  # noqa: E402
    EquipmentDefinition,
    EquipmentFamilyDefinition,
    EquipmentQualityProfile,
)
from game.core.gameplay.inventory import ItemAssetKind, ItemDefinition  # noqa: E402
from game.core.gameplay.itemization import (  # noqa: E402
    GenerationProfileDefinition,
    ItemGenerationCommand,
    ItemizationKind,
    PropertyDefinition,
    PropertyParameterDefinition,
    PropertyTierDefinition,
    QualityValueBand,
)
from game.core.gameplay.loadout import (  # noqa: E402
    HEAD_SLOT_ID,
    LOADOUT_ITEM_COMPONENT_ID,
    WEAPON_SLOT_ID,
    LoadoutItemComponent,
    QualityDefinition,
)
from game.core.gameplay.party import PartyDefinition  # noqa: E402
from game.core.gameplay.weapon import (  # noqa: E402
    WeaponDefinition,
    WeaponMaximumLevelRoll,
    WeaponQualityProfile,
)
from game.core.gameplay.valuation import (  # noqa: E402
    AttributeValuationDefinition,
    ValueAxis,
    ValueCurvePoint,
)
from game.core.persistence import (  # noqa: E402
    ConcurrencyConflict,
    ContentActivationMismatch,
    ContentActivationStore,
    SqliteDatabase,
    gameplay_snapshot_codec,
)


TIME = datetime(2026, 7, 13, 0, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


@dataclass(frozen=True)
class _PackageMagnitude:
    value: float


def _evaluate_package_magnitude(value: _PackageMagnitude, _context) -> float:
    return value.value


def _context(seed: int) -> RuleContext:
    return RuleContext(
        f"content-test-{seed}",
        "rules.content_test",
        Ruleset("ruleset.content_test"),
        TIME,
        SeededRandomSource(seed),
    )


def main() -> None:
    packages = _packages()
    _assert_dependency_resolution(packages)
    runtime = _assert_complete_runtime(packages)
    _assert_runtime_is_frozen(runtime)
    _assert_dependency_and_reference_failures(packages)
    _assert_scoped_skin_coverage(packages)
    _assert_weapon_core_contract(packages)
    _assert_fingerprint_is_deterministic(packages, runtime.report.content_fingerprint)
    _assert_persisted_activation(runtime)
    print("content assembly tests passed")


def _assert_weapon_core_contract(packages) -> None:
    core, *others = packages
    weapon = core.weapons[0]
    profile = next(
        value
        for value in core.generation_profiles
        if value.kind is ItemizationKind.WEAPON
    )
    duplicate_item = ItemDefinition(
        "item.weapon.training_blade_second",
        ItemAssetKind.INSTANCE,
        TagSet.of("item.weapon"),
        components={
            LOADOUT_ITEM_COMPONENT_ID: LoadoutItemComponent(
                frozenset({WEAPON_SLOT_ID})
            )
        },
    )
    duplicate_profile = replace(profile, id="generation.training_weapon_second")
    duplicate_weapon = replace(
        weapon,
        id="weapon.training_blade_second",
        item_definition_id=duplicate_item.id,
        generation_profile_id=duplicate_profile.id,
    )
    duplicated_core = replace(
        core,
        items=(*core.items, duplicate_item),
        generation_profiles=(*core.generation_profiles, duplicate_profile),
        weapons=(*core.weapons, duplicate_weapon),
    )
    try:
        ContentAssembler().assemble((duplicated_core, *others))
        raise AssertionError("两把武器不能复用同一个核心特色")
    except ValueError as exc:
        assert "武器核心特色不能复用" in str(exc)

    second_property = replace(
        core.random_properties[0],
        id="property.training_attack_second",
    )
    multi_core_profile = replace(
        profile,
        property_ids=profile.property_ids | {second_property.id},
        core_property_ids=profile.core_property_ids | {second_property.id},
    )
    multi_core = replace(
        core,
        random_properties=(*core.random_properties, second_property),
        generation_profiles=tuple(
            multi_core_profile if value.id == profile.id else value
            for value in core.generation_profiles
        ),
    )
    try:
        ContentAssembler().assemble((multi_core, *others))
        raise AssertionError("一把武器不能声明多个核心特色")
    except ValueError as exc:
        assert "必须绑定唯一核心特色" in str(exc)


def _manifest(package_id: str, *dependencies: str, version=(1, 0, 0)):
    return ContentPackageManifest(
        package_id,
        ContentVersion(*version),
        tuple(PackageRequirement(value, ContentVersion(1)) for value in dependencies),
    )


def _core_package() -> ContentPackage:
    attributes = tuple(core_attribute_definitions().values())
    resources = tuple(persistent_resource_definitions().values())
    feature = CharacterFeatureDefinition("feature.starting_body")
    progression = ProgressionDefinition("progression.character_level", (100, 200))
    template = CharacterTemplateDefinition(
        "character_template.standard",
        {
            HEALTH_MAXIMUM: 100,
            SPIRIT_MAXIMUM: 50,
            COMBAT_ATTACK: 10,
            COMBAT_DEFENSE: 0,
            COMBAT_SPEED: 5,
        },
        progression_ids=frozenset({progression.id}),
        feature_ids=frozenset({feature.id}),
    )
    weapon_item = ItemDefinition(
        "item.weapon.training_blade",
        ItemAssetKind.INSTANCE,
        tags=TagSet.of("item.weapon"),
        components={
            "item_component.loadout": LoadoutItemComponent(frozenset({WEAPON_SLOT_ID}))
        },
    )
    equipment_item = ItemDefinition(
        "item.equipment.training_head",
        ItemAssetKind.INSTANCE,
        tags=TagSet.of("item.equipment", "item.equipment.head"),
        components={
            "item_component.loadout": LoadoutItemComponent(frozenset({HEAD_SLOT_ID}))
        },
    )
    quality = QualityDefinition("quality.common", 0)
    attack_value = AttributeValuationDefinition(
        COMBAT_ATTACK,
        ModifierLayer.LOCAL_FLAT,
        ValueAxis.OFFENSE,
        (ValueCurvePoint(0, 0), ValueCurvePoint(20, 20)),
    )
    attack_property = PropertyDefinition(
        "property.attack_roll",
        1,
        (
            PropertyTierDefinition(
                1,
                1,
                parameters=(
                    PropertyParameterDefinition(
                        "parameter.attack",
                        COMBAT_ATTACK,
                        ModifierLayer.LOCAL_FLAT,
                        5,
                        10,
                    ),
                ),
            ),
        ),
    )
    quality_bands = (QualityValueBand(quality.id, 0, None),)
    weapon_generation = GenerationProfileDefinition(
        "generation.training_weapon",
        ItemizationKind.WEAPON,
        frozenset({attack_property.id}),
        1,
        1,
        quality_bands,
        core_property_ids=frozenset({attack_property.id}),
        enforce_compatibility=True,
    )
    equipment_generation = GenerationProfileDefinition(
        "generation.training_equipment",
        ItemizationKind.EQUIPMENT,
        frozenset({attack_property.id}),
        1,
        1,
        quality_bands,
    )
    family = EquipmentFamilyDefinition("family.training")
    weapon = WeaponDefinition(
        "weapon.training_blade",
        weapon_item.id,
        ContributionSpec(),
        {
            quality.id: WeaponQualityProfile(
                quality.id,
                experience_requirements=(100,),
            )
        },
        generation_profile_id=weapon_generation.id,
    )
    equipment = EquipmentDefinition(
        "equipment.training_head",
        equipment_item.id,
        HEAD_SLOT_ID,
        family.id,
        quality_profiles={
            quality.id: EquipmentQualityProfile(quality.id, ContributionSpec())
        },
        generation_profile_id=equipment_generation.id,
    )
    damage_type = DamageTypeDefinition(
        "damage.physical",
        defense_attribute="combat.defense.physical",
    )
    return ContentPackage(
        _manifest("content.core"),
        currencies=(CurrencyDefinition("currency.spirit_stone"),),
        qualities=(quality,),
        attributes=attributes,
        resources=resources,
        character_features=(feature,),
        progressions=(progression,),
        character_templates=(template,),
        items=(weapon_item, equipment_item),
        equipment_families=(family,),
        party_types=(PartyDefinition("party_type.standard", 3),),
        attribute_valuations=(attack_value,),
        random_properties=(attack_property,),
        generation_profiles=(weapon_generation, equipment_generation),
        weapons=(weapon,),
        equipment=(equipment,),
        combat_profiles=(
            CombatProfileDefinition(
                "combat_profile.standard",
                CombatStats("health.current"),
                RecoveryStats("health.current"),
            ),
        ),
        damage_types=(damage_type,),
        cycles=(
            CycleDefinition(
                "cycle.daily_reset",
                CalendarSchedule("Asia/Shanghai", CalendarUnit.DAY, time(4)),
            ),
        ),
        display_content_ids=frozenset(
            {
                "currency.spirit_stone",
                quality.id,
                feature.id,
                progression.id,
                template.id,
                weapon_item.id,
                equipment_item.id,
                family.id,
                weapon.id,
                equipment.id,
                damage_type.id,
            }
        ),
    )


def _mechanics_package() -> ContentPackage:
    return ContentPackage(
        _manifest("content.mechanics"),
        magnitude_registrations=(
            MagnitudeRegistration(_PackageMagnitude, _evaluate_package_magnitude),
        ),
    )


def _adventure_package() -> ContentPackage:
    material = ItemDefinition(
        "item.material.spirit_ore",
        ItemAssetKind.STACK,
        tags=TagSet.of("item.material"),
        stack_limit=99,
    )
    draw_ticket = ItemDefinition(
        "item.draw.ticket",
        ItemAssetKind.STACK,
        tags=TagSet.of("item.draw_ticket"),
        stack_limit=99,
    )
    draw_award = ItemDefinition(
        "item.draw.award",
        ItemAssetKind.STACK,
        tags=TagSet.of("item.special"),
        stack_limit=99,
    )
    draw_table = LootTableDefinition(
        "loot_table.draw.content_test",
        1,
        (
            LootGroup(
                "loot_group.draw.content_test",
                LootGroupMode.WEIGHTED_ONE,
                (LootEntry("loot_entry.draw.content_test", draw_award.id, weight=1),),
            ),
        ),
    )
    draw_pool = DrawPoolDefinition(
        "draw_pool.content_test",
        1,
        draw_ticket.id,
        draw_table.id,
        frozenset({draw_award.id}),
    )
    effect = EffectDefinition(
        "effect.adventure_strike",
        operations=(
            DealDamage(
                "operation.adventure_strike",
                "damage.physical",
                _PackageMagnitude(15),
                can_miss=False,
                can_critical=False,
                can_block=False,
            ),
        ),
    )
    ability = AbilityDefinition(
        "ability.adventure_strike",
        effects=(EffectReference(effect.id),),
    )
    return ContentPackage(
        _manifest("content.adventure", "content.core", "content.mechanics"),
        items=(material, draw_ticket, draw_award),
        loot_tables=(draw_table,),
        draw_pools=(draw_pool,),
        effects=(effect,),
        abilities=(ability,),
        display_content_ids=frozenset({material.id, ability.id}),
    )


def _skin_package(display_ids: frozenset[str]) -> ContentPackage:
    entries = {
        content_id: SkinEntry(content_id.replace(".", " ").title())
        for content_id in display_ids
    }
    return ContentPackage(
        _manifest("content.world_skins", "content.core", "content.adventure"),
        skin_packs=(
            SkinPack("skin.cultivation", 1, "太玄界", entries=entries),
            SkinPack("skin.magic", 1, "魔法世界", entries=entries),
        ),
    )


def _packages() -> tuple[ContentPackage, ...]:
    core = _core_package()
    mechanics = _mechanics_package()
    adventure = _adventure_package()
    display_ids = core.display_content_ids | adventure.display_content_ids
    skins = _skin_package(display_ids)
    return core, mechanics, adventure, skins


def _assert_dependency_resolution(packages) -> None:
    core, mechanics, adventure, skins = packages
    order = resolve_package_order((skins, adventure, mechanics, core))
    assert tuple(value.manifest.id for value in order) == (
        "content.core",
        "content.mechanics",
        "content.adventure",
        "content.world_skins",
    )
    missing = replace(
        adventure,
        manifest=_manifest("content.adventure", "content.missing"),
    )
    try:
        resolve_package_order((core, missing))
        raise AssertionError("缺少依赖时必须失败")
    except KeyError:
        pass
    incompatible = replace(
        adventure,
        manifest=ContentPackageManifest(
            "content.adventure",
            ContentVersion(1),
            (PackageRequirement("content.core", ContentVersion(2)),),
        ),
    )
    try:
        resolve_package_order((core, incompatible))
        raise AssertionError("依赖版本不满足时必须失败")
    except ValueError:
        pass
    first = ContentPackage(_manifest("content.cycle_a", "content.cycle_b"))
    second = ContentPackage(_manifest("content.cycle_b", "content.cycle_a"))
    try:
        resolve_package_order((first, second))
        raise AssertionError("依赖环必须失败")
    except ValueError:
        pass


def _assert_complete_runtime(packages):
    runtime = ContentAssembler().assemble(tuple(reversed(packages)))
    assert CONTENT_FOUNDATION_VERSION == "content.foundation.v9"
    assert runtime.report.active_combat_profile_id == "combat_profile.standard"
    assert runtime.report.packages[-1].id == "content.world_skins"
    assert len(runtime.report.content_fingerprint) == 64
    assert runtime.currencies.ids() == ("currency.spirit_stone",)
    assert runtime.items.require("item.material.spirit_ore").stack_limit == 99
    assert runtime.draw_pools.require("draw_pool.content_test").ticket_item_id == "item.draw.ticket"
    draw = runtime.draw_engine.draw(
        DrawCommand("content-draw", "actor", "draw_pool.content_test", 0),
        state=LootState("actor"),
        context=_context(87),
    ).unwrap()
    assert draw.receipt.awards[0].award_id == "item.draw.award"
    assert runtime.weapons.require("weapon.training_blade")
    assert runtime.equipment.require("equipment.training_head")
    assert runtime.parties.require("party_type.standard").capacity == 3
    weapon_roll = runtime.itemization_engine.generate(
        ItemGenerationCommand(
            "generate-training-weapon",
            "generation.training_weapon",
            runtime.report.content_fingerprint,
        ),
        context=_context(88),
    ).roll
    weapon_state = runtime.weapons.create_state(
        asset_id="generated-training-weapon",
        definition_id="weapon.training_blade",
        quality_id=weapon_roll.quality_id,
        roll=weapon_roll,
        maximum_level_roll=WeaponMaximumLevelRoll(
            "weapon_maximum_level.test",
            1,
            1,
            3,
            2,
        ),
    )
    assert weapon_state.roll == weapon_roll
    equipment_roll = runtime.itemization_engine.generate(
        ItemGenerationCommand(
            "generate-training-equipment",
            "generation.training_equipment",
            runtime.report.content_fingerprint,
        ),
        context=_context(89),
    ).roll
    equipment_state = runtime.equipment.create_state(
        asset_id="generated-training-head",
        definition_id="equipment.training_head",
        quality_id=equipment_roll.quality_id,
        roll=equipment_roll,
    )
    assert equipment_state.roll == equipment_roll
    codec = gameplay_snapshot_codec()
    assert codec.loads(codec.dumps(weapon_state), type(weapon_state)) == weapon_state
    assert codec.loads(codec.dumps(equipment_state), type(equipment_state)) == equipment_state
    assert runtime.skins.skin_ids() == ("skin.cultivation", "skin.magic")
    assert runtime.skins.require("skin.cultivation").name == "太玄界"
    assert runtime.skins.require("skin.magic").name == "魔法世界"
    assert runtime.skins.projector("skin.cultivation").name("ability.adventure_strike")
    cycle = runtime.cycle_engine.current_window(
        "cycle.daily_reset",
        logical_time=datetime(2026, 7, 13, 3, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    assert cycle and cycle.starts_at.day == 12 and cycle.starts_at.hour == 4

    actor = RuleEntity(
        "actor",
        base_attributes={
            HEALTH_MAXIMUM: 100,
            SPIRIT_MAXIMUM: 50,
            COMBAT_ATTACK: 10,
            COMBAT_DEFENSE: 0,
            COMBAT_SPEED: 5,
        },
        resources={"health.current": 100, "spirit.current": 50},
        base_abilities=frozenset({"ability.adventure_strike"}),
    )
    target = RuleEntity(
        "target",
        base_attributes={
            HEALTH_MAXIMUM: 100,
            SPIRIT_MAXIMUM: 50,
            COMBAT_ATTACK: 10,
            COMBAT_DEFENSE: 0,
            COMBAT_SPEED: 5,
        },
        resources={"health.current": 100, "spirit.current": 50},
    )
    result = runtime.ability_engine.execute(
        AbilityUse("content-ability-use", "ability.adventure_strike"),
        actor=actor,
        target=target,
        context=RuleContext(
            "content-test",
            "rules.v1",
            Ruleset("ruleset.standard"),
            TIME,
            SeededRandomSource(17),
        ),
    )
    assert result.target.resources["health.current"] == 85
    return runtime


def _assert_runtime_is_frozen(runtime) -> None:
    assert runtime.items.finalized
    assert runtime.characters.finalized
    assert runtime.weapons.finalized
    assert runtime.equipment.finalized
    assert runtime.skins.frozen
    assert runtime.effects.frozen
    assert runtime.abilities.frozen
    assert runtime.triggers.frozen
    assert runtime.target_selectors.frozen
    assert runtime.draw_pools.finalized
    assert runtime.cycles.frozen
    assert runtime.cycle_engine.handlers.frozen
    try:
        runtime.currencies.register(CurrencyDefinition("currency.too_late"))
        raise AssertionError("运行期不能增加货币")
    except RuntimeError:
        pass
    try:
        runtime.draw_pools.register(
            DrawPoolDefinition(
                "draw_pool.too_late",
                1,
                "item.draw.ticket",
                "loot_table.draw.content_test",
                frozenset({"item.draw.award"}),
            )
        )
        raise AssertionError("运行期不能增加抽取池")
    except RuntimeError:
        pass


def _assert_scoped_skin_coverage(packages) -> None:
    core, mechanics, adventure, skins = packages
    local_id = "currency.skin_local"
    local = ContentPackage(
        _manifest("content.skin_local", "content.core"),
        currencies=(CurrencyDefinition(local_id),),
        skin_display_content_ids={"skin.cultivation": frozenset({local_id})},
    )
    cultivation, magic = skins.skin_packs
    scoped_skins = replace(
        skins,
        skin_packs=(
            replace(
                cultivation,
                entries={
                    **cultivation.entries,
                    local_id: SkinEntry("太玄专属货币"),
                },
            ),
            magic,
        ),
    )
    runtime = ContentAssembler().assemble(
        (core, mechanics, adventure, local, scoped_skins)
    )
    assert runtime.skins.require("skin.cultivation").entries[local_id]
    assert local_id not in runtime.skins.require("skin.magic").entries

    try:
        ContentAssembler().assemble((core, mechanics, adventure, local, skins))
        raise AssertionError("皮肤必须覆盖分配给自己的作用域展示内容")
    except ValueError as exc:
        assert "缺少条目" in str(exc)

    unknown_skin_scope = replace(
        local,
        skin_display_content_ids={"skin.not_installed": frozenset({local_id})},
    )
    try:
        ContentAssembler().assemble(
            (core, mechanics, adventure, unknown_skin_scope, scoped_skins)
        )
        raise AssertionError("作用域展示内容不能引用未启用皮肤")
    except KeyError as exc:
        assert "未启用皮肤" in str(exc)


def _assert_dependency_and_reference_failures(packages) -> None:
    core, mechanics, adventure, skins = packages
    undeclared = replace(
        adventure,
        manifest=_manifest("content.adventure", "content.core"),
    )
    try:
        ContentAssembler().assemble((core, mechanics, undeclared, skins))
        raise AssertionError("使用其他包扩展类型却未声明依赖时必须失败")
    except ValueError as exc:
        assert "_PackageMagnitude" in str(exc)

    skin_without_dependencies = replace(
        skins,
        manifest=_manifest("content.world_skins"),
    )
    projected = ContentAssembler().assemble(
        (core, mechanics, adventure, skin_without_dependencies)
    )
    assert projected.skins.require("skin.cultivation")

    duplicate = ContentPackage(
        _manifest("content.duplicate"),
        currencies=(CurrencyDefinition("currency.spirit_stone"),),
    )
    try:
        ContentAssembler().assemble((core, mechanics, adventure, skins, duplicate))
        raise AssertionError("跨包稳定 ID 冲突必须失败")
    except ValueError as exc:
        assert "稳定内容 ID 冲突" in str(exc)

    bad_effect = EffectDefinition(
        "effect.bad_reference",
        operations=(
            DealDamage(
                "operation.bad_reference",
                "damage.unknown",
                _PackageMagnitude(1),
            ),
        ),
    )
    bad_adventure = replace(adventure, effects=(bad_effect,))
    try:
        ContentAssembler().assemble((core, mechanics, bad_adventure, skins))
        raise AssertionError("跨目录未知引用必须在启动组装时失败")
    except KeyError:
        pass


def _assert_fingerprint_is_deterministic(packages, expected) -> None:
    repeated = ContentAssembler().assemble((packages[3], packages[1], packages[0], packages[2]))
    assert repeated.report.content_fingerprint == expected
    upgraded_core = replace(
        packages[0],
        manifest=replace(packages[0].manifest, version=ContentVersion(1, 0, 1)),
    )
    upgraded_adventure = replace(
        packages[2],
        manifest=ContentPackageManifest(
            packages[2].manifest.id,
            packages[2].manifest.version,
            tuple(
                PackageRequirement(
                    item.package_id,
                    ContentVersion(1),
                )
                for item in packages[2].manifest.dependencies
            ),
        ),
    )
    changed = ContentAssembler().assemble(
        (upgraded_core, packages[1], upgraded_adventure, packages[3])
    )
    assert changed.report.content_fingerprint != expected


def _assert_persisted_activation(runtime) -> None:
    with TemporaryDirectory() as directory:
        database = SqliteDatabase(Path(directory) / "content.db")
        database.initialize()
        store = ContentActivationStore(database)
        activation = store.verify_or_initialize(runtime.report, logical_time=TIME)
        assert activation.revision == 0
        assert activation.fingerprint == runtime.report.content_fingerprint
        repeated = store.verify_or_initialize(runtime.report, logical_time=TIME)
        assert repeated == activation

        changed_report = replace(runtime.report, content_fingerprint="f" * 64)
        try:
            store.verify_or_initialize(changed_report, logical_time=TIME)
            raise AssertionError("内容指纹变化不能在普通启动中静默覆盖")
        except ContentActivationMismatch:
            pass
        replaced = store.replace(
            changed_report,
            expected_revision=activation.revision,
            expected_fingerprint=activation.fingerprint,
            logical_time=TIME,
        )
        assert replaced.revision == 1
        assert store.require() == replaced
        try:
            store.replace(
                runtime.report,
                expected_revision=0,
                expected_fingerprint=activation.fingerprint,
                logical_time=TIME,
            )
            raise AssertionError("旧内容激活 revision 不能覆盖新激活记录")
        except ConcurrencyConflict:
            pass


if __name__ == "__main__":
    main()
