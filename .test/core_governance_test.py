"""核心演进治理门禁：阻止业务绕层、状态吞并和无审计动态字段。"""

from __future__ import annotations

import ast
from importlib.util import resolve_name
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "game" / "core"


# 跨领域状态只能出现在经过审计的类型化组合结果中。键值精确到字段，禁止目录级放行。
APPROVED_CROSS_DOMAIN_STATE_FIELDS = {
    ("game/core/gameplay/draw/models.py", "DrawExecution", "loot_state", "LootState"),
    ("game/core/gameplay/draw/models.py", "DrawInventoryExecution", "inventory_state", "InventoryState"),
    ("game/core/gameplay/draw/models.py", "DrawInventoryExecution", "loot_state", "LootState"),
    ("game/core/gameplay/equipment/models.py", "EquipmentState", "roll", "ItemRollState"),
    ("game/core/gameplay/exchange/models.py", "ExchangeExecution", "inventory", "InventoryState"),
    ("game/core/gameplay/exchange/models.py", "ExchangeExecution", "ledger", "LedgerState"),
    ("game/core/gameplay/inscription/models.py", "InscriptionExecution", "inventory", "InventoryState"),
    ("game/core/gameplay/inventory/item_use.py", "CharacterItemUseExecution", "characters", "CharacterState"),
    ("game/core/gameplay/loadout/transactions.py", "LoadoutExecution", "inventory", "InventoryState"),
    ("game/core/gameplay/rewards/models.py", "GeneratedEquipmentReward", "state", "EquipmentState"),
    ("game/core/gameplay/rewards/models.py", "GeneratedWeaponReward", "state", "WeaponState"),
    ("game/core/gameplay/rewards/models.py", "RewardSettlementSnapshot", "inventory", "InventoryState"),
    ("game/core/gameplay/rewards/models.py", "RewardSettlementSnapshot", "ledger", "LedgerState"),
    ("game/core/gameplay/rewards/models.py", "RewardSettlementSnapshot", "characters", "CharacterState"),
    ("game/core/gameplay/rewards/models.py", "RewardSettlementSnapshot", "weapons", "WeaponState"),
    ("game/core/gameplay/rewards/planning.py", "RewardPlan", "generated_weapons", "WeaponState"),
    ("game/core/gameplay/rewards/planning.py", "RewardPlanBuilder", "generated_weapons", "WeaponState"),
    ("game/core/gameplay/weapon/models.py", "WeaponState", "roll", "ItemRollState"),
    (
        "game/core/persistence/characters.py",
        "PersistedCharacterRegistration",
        "character",
        "CharacterState",
    ),
    (
        "game/core/persistence/characters.py",
        "PersistedCharacterRegistration",
        "roster",
        "CharacterRosterState",
    ),
}


# 动态载荷只适合边界事实、可扩展定义和结算载荷。新增位置必须逐字段审核。
APPROVED_DYNAMIC_FIELDS = {
    ("game/core/account/models.py", "AccountEvent", "values"),
    ("game/core/gameplay/actions/models.py", "ActionDefinition", "metadata"),
    ("game/core/gameplay/actions/models.py", "ActionSnapshot", "values"),
    ("game/core/gameplay/actions/models.py", "ActionResult", "facts"),
    ("game/core/gameplay/activities/models.py", "ActivityParticipant", "metadata"),
    ("game/core/gameplay/activities/models.py", "ActivityInstance", "metadata"),
    ("game/core/gameplay/activities/models.py", "JoinActivity", "metadata"),
    ("game/core/gameplay/activities/models.py", "ActivityCommand", "operation"),
    ("game/core/gameplay/combat/interceptors.py", "DamageInterceptorDefinition", "configuration"),
    ("game/core/gameplay/content/models.py", "ContentPackage", "metadata"),
    ("game/core/gameplay/content/models.py", "ConditionRegistration", "handler"),
    ("game/core/gameplay/content/models.py", "ConditionRegistration", "validator"),
    ("game/core/gameplay/content/models.py", "ConditionRegistration", "value_type"),
    ("game/core/gameplay/content/models.py", "ContentPackage", "item_component_types"),
    ("game/core/gameplay/content/models.py", "EffectOperationRegistration", "handler"),
    ("game/core/gameplay/content/models.py", "EffectOperationRegistration", "validator"),
    ("game/core/gameplay/content/models.py", "EffectOperationRegistration", "value_type"),
    ("game/core/gameplay/content/models.py", "MagnitudeRegistration", "evaluator"),
    ("game/core/gameplay/content/models.py", "MagnitudeRegistration", "validator"),
    ("game/core/gameplay/content/models.py", "MagnitudeRegistration", "value_type"),
    ("game/core/gameplay/cycles/models.py", "CycleDefinition", "metadata"),
    ("game/core/gameplay/cycles/schedules.py", "ScheduleHandlerRegistration", "schedule_type"),
    ("game/core/gameplay/economy/models.py", "JournalEntry", "metadata"),
    ("game/core/gameplay/economy/transactions.py", "LedgerTransaction", "metadata"),
    ("game/core/gameplay/effects.py", "EffectFact", "values"),
    ("game/core/gameplay/errors.py", "RuleFailure", "details"),
    ("game/core/gameplay/events.py", "RuleEvent", "values"),
    ("game/core/gameplay/exchange/models.py", "ExchangeQuote", "metadata"),
    ("game/core/gameplay/exchange/models.py", "ExchangeCommand", "operation"),
    ("game/core/gameplay/grants/models.py", "GrantCampaign", "metadata"),
    ("game/core/gameplay/grants/models.py", "GrantCredential", "metadata"),
    ("game/core/gameplay/grants/models.py", "GrantEntitlement", "metadata"),
    ("game/core/gameplay/grants/models.py", "GrantRewardBundle", "metadata"),
    ("game/core/gameplay/grants/models.py", "MigrationManifestEntry", "source_data"),
    ("game/core/gameplay/inventory/definitions.py", "ItemDefinition", "components"),
    ("game/core/gameplay/inventory/models.py", "ItemInstance", "data"),
    ("game/core/gameplay/inventory/models.py", "SourceReceipt", "metadata"),
    ("game/core/gameplay/inventory/transactions.py", "GrantInstance", "data"),
    ("game/core/gameplay/projections/models.py", "NotificationAction", "payload"),
    ("game/core/gameplay/projections/models.py", "NotificationEntry", "data"),
    ("game/core/gameplay/projections/models.py", "ProjectionValue", "payload"),
    ("game/core/gameplay/party/models.py", "PartyCommand", "operation"),
    ("game/core/gameplay/rewards/models.py", "GeneratedEquipmentReward", "metadata"),
    ("game/core/gameplay/rewards/models.py", "GeneratedWeaponReward", "metadata"),
    ("game/core/gameplay/rewards/models.py", "InstanceItemReward", "data"),
    ("game/core/gameplay/rewards/models.py", "InstanceItemReward", "metadata"),
    ("game/core/gameplay/rewards/models.py", "RewardLine", "details"),
    ("game/core/gameplay/rewards/models.py", "RewardSettlement", "metadata"),
    ("game/core/gameplay/rewards/models.py", "StackItemReward", "metadata"),
    ("game/core/gameplay/rewards/planning.py", "RewardPlan", "character_operations"),
    ("game/core/gameplay/rewards/planning.py", "RewardPlanBuilder", "character_operations"),
    ("game/core/gameplay/social/models.py", "SocialRequest", "metadata"),
    ("game/core/gameplay/social/models.py", "SocialCommand", "operation"),
    ("game/core/gameplay/world/models.py", "WorldTransaction", "operations"),
}


# 每个领域版本必须由一个直接可运行的测试文件锁定。
FOUNDATION_TESTS = {
    "ACCOUNT_FOUNDATION_VERSION": ".test/account_foundation_test.py",
    "ACTION_FOUNDATION_VERSION": ".test/action_foundation_test.py",
    "BATTLE_AI_FOUNDATION_VERSION": ".test/official_enemy_catalog_test.py",
    "ACTIVITY_FOUNDATION_VERSION": ".test/activity_foundation_test.py",
    "CHARACTER_FOUNDATION_VERSION": ".test/character_foundation_test.py",
    "COMBAT_FOUNDATION_VERSION": ".test/advanced_effects_test.py",
    "CONTENT_FOUNDATION_VERSION": ".test/content_assembly_test.py",
    "CYCLE_FOUNDATION_VERSION": ".test/cycle_foundation_test.py",
    "DRAW_FOUNDATION_VERSION": ".test/draw_foundation_test.py",
    "ECONOMY_FOUNDATION_VERSION": ".test/economy_foundation_test.py",
    "ENEMY_FOUNDATION_VERSION": ".test/official_enemy_catalog_test.py",
    "EQUIPMENT_FOUNDATION_VERSION": ".test/loadout_weapon_equipment_test.py",
    "EXCHANGE_FOUNDATION_VERSION": ".test/exchange_foundation_test.py",
    "GRANT_FOUNDATION_VERSION": ".test/grant_foundation_test.py",
    "INSCRIPTION_FOUNDATION_VERSION": ".test/inscription_foundation_test.py",
    "INVENTORY_FOUNDATION_VERSION": ".test/inventory_foundation_test.py",
    "ITEMIZATION_FOUNDATION_VERSION": ".test/itemization_foundation_test.py",
    "LOADOUT_FOUNDATION_VERSION": ".test/loadout_weapon_equipment_test.py",
    "LOOT_FOUNDATION_VERSION": ".test/loot_foundation_test.py",
    "PARTY_FOUNDATION_VERSION": ".test/party_foundation_test.py",
    "PERSISTENCE_FOUNDATION_VERSION": ".test/persistence_foundation_test.py",
    "PROJECTION_FOUNDATION_VERSION": ".test/projection_foundation_test.py",
    "REWARD_FOUNDATION_VERSION": ".test/reward_settlement_test.py",
    "SOCIAL_FOUNDATION_VERSION": ".test/social_foundation_test.py",
    "VALUATION_FOUNDATION_VERSION": ".test/itemization_foundation_test.py",
    "WEAPON_FOUNDATION_VERSION": ".test/loadout_weapon_equipment_test.py",
    "WORLD_FOUNDATION_VERSION": ".test/world_foundation_test.py",
}


def main() -> None:
    _assert_database_write_boundary()
    _assert_feature_sql_boundary()
    _assert_feature_layer_boundary()
    _assert_business_feature_catalog()
    _assert_application_composition_boundary()
    _assert_retired_structure_is_absent()
    _assert_balance_values_live_in_content()
    _assert_item_use_components_are_wired()
    _assert_cross_domain_state_fields()
    _assert_dynamic_field_registry()
    _assert_foundation_coverage()
    _assert_battle_modes_use_core_session()
    _assert_changed_core_has_evidence()
    print("core governance tests passed")


def _assert_business_feature_catalog() -> None:
    """业务目录、中文组件和后台任务必须与正式能力台账一致。"""

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from game.features.catalog import (
        ACTIVE_FEATURE_MANIFESTS,
        feature_snapshot_codec_registrations,
    )

    ids = [value.id for value in ACTIVE_FEATURE_MANIFESTS]
    packages = [value.package for value in ACTIVE_FEATURE_MANIFESTS]
    assert len(ids) == len(set(ids)), "正式业务台账存在重复 ID"
    assert len(packages) == len(set(packages)), "正式业务台账存在重复包名"

    command_owners: dict[str, str] = {}
    for feature in ACTIVE_FEATURE_MANIFESTS:
        integrated = set(feature.integrated_command_packages)
        for command_package in set(feature.command_packages) - integrated:
            previous = command_owners.setdefault(command_package, feature.id)
            assert previous == feature.id, (
                f"命令组件 {command_package} 存在多个主业务：{previous} 与 {feature.id}"
            )
    for feature in ACTIVE_FEATURE_MANIFESTS:
        for command_package in feature.integrated_command_packages:
            assert command_package in command_owners, (
                f"业务 {feature.id} 的协作命令组件 {command_package} 没有主业务"
            )

    feature_root = ROOT / "game" / "features"
    actual_packages = {
        path.name
        for path in feature_root.iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    }
    assert actual_packages == set(packages), (
        f"业务目录与能力台账不一致：目录={sorted(actual_packages)}，"
        f"台账={sorted(packages)}"
    )

    command_root = ROOT / "game" / "cmd"
    job_sources = {
        path: path.read_text(encoding="utf-8")
        for path in command_root.rglob("jobs.py")
    }
    registered_job_files: set[Path] = set()
    for feature in ACTIVE_FEATURE_MANIFESTS:
        for command_package in feature.command_packages:
            package = command_root / command_package
            assert (package / "__init__.py").is_file(), (
                f"业务 {feature.id} 缺少命令组件 {command_package}"
            )
        for job_id in feature.scheduled_jobs:
            matches = [
                path
                for path, source in job_sources.items()
                if f'id="{job_id}"' in source
            ]
            assert len(matches) == 1, (
                f"业务 {feature.id} 的定时任务 {job_id} 必须且只能登记一次"
            )
            job_file = matches[0]
            assert job_file.parent.name in feature.command_packages, (
                f"业务 {feature.id} 的定时任务 {job_id} 不在所属二级组件中"
            )
            registered_job_files.add(job_file)
    assert registered_job_files == set(job_sources), "存在未登记到业务台账的 jobs.py"

    codec_packages = {
        path.parent.name for path in feature_root.glob("*/codec.py")
    }
    registered_codec_packages = {
        feature.package
        for feature in ACTIVE_FEATURE_MANIFESTS
        if feature.snapshot_codecs
    }
    assert registered_codec_packages == codec_packages, (
        "业务 codec.py 与 Feature Manifest 登记不一致："
        f"文件={sorted(codec_packages)}，登记={sorted(registered_codec_packages)}"
    )
    codec_registrations = feature_snapshot_codec_registrations()
    codec_ids = tuple(value[0] for value in codec_registrations)
    assert len(codec_ids) == len(set(codec_ids)), "业务快照 codec ID 重复"


def _assert_item_use_components_are_wired() -> None:
    """正式物品的类型化使用组件必须都有唯一的实际消费入口。"""

    from game.content import build_official_content
    from game.cmd.物品.use import ITEM_USE_ROUTES, ITEM_USE_ROUTE_REGISTRY

    content = build_official_content()
    used_components = {
        str(component_id)
        for definition in content.catalog.items.definitions
        for component_id in definition.components
        if str(component_id).startswith("item_component.use_")
    }
    registered_components = {str(value) for value in ITEM_USE_ROUTE_REGISTRY}
    assert len(ITEM_USE_ROUTES) == len(registered_components)
    assert used_components == registered_components, (
        "正式物品使用组件与消费入口不一致："
        f"定义={sorted(used_components)}，入口={sorted(registered_components)}"
    )
    for route in ITEM_USE_ROUTES:
        assert route.handler.__module__ == "game.cmd.物品.use"
        action = route.action("I1")
        assert action.data
        assert action.behavior in {"fill", "send"}

    delegated = ITEM_USE_ROUTE_REGISTRY["item_component.use_dimension_shift"]
    delegated_action = delegated.action("I1")
    assert (delegated_action.data, delegated_action.behavior) == ("跃迁", "send")
    for route in ITEM_USE_ROUTES:
        if route is delegated:
            continue
        action = route.action("I1")
        assert (action.data, action.behavior) == ("使用 I1", "fill")


def _assert_application_composition_boundary() -> None:
    """组合根只能装配和转发，不能重新成为业务事务集中地。"""

    from game.features.catalog import ACTIVE_FEATURE_MANIFESTS

    source = (ROOT / "game" / "app.py").read_text(encoding="utf-8")
    assert ".unit_of_work(" not in source, "game/app.py 禁止直接开启业务工作单元"
    assert "InventoryTransaction(" not in source, "game/app.py 禁止直接构造库存事务"
    assert "@Scheduler" not in source, "game/app.py 禁止直接注册业务定时任务"
    assert "*feature_snapshot_codec_registrations()," in source
    for feature in ACTIVE_FEATURE_MANIFESTS:
        assert f"{feature.id}_codec_registrations" not in source, (
            f"业务 {feature.id} 的快照 codec 必须通过 Feature Manifest 装配"
        )


def _assert_retired_structure_is_absent() -> None:
    """已经移除的伪模板和兼容别名不能重新进入正式源码。"""

    forbidden = {
        "BOSS_TEMPLATE_KEYS": "首领显示必须直接覆盖真实个人/组队身份蓝图",
        "DISASTER_TEMPLATE_KEYS": "跨界灾厄必须由 disaster 内容包独立定义",
        "ItemRecycleValue": "回收产出必须使用明确的 CurrencyRecycleYield 类型",
        "BusinessFeaturePlan": "正式业务必须统一使用 FeatureManifest",
        "ACTIVE_BUSINESS_FEATURES": "正式业务必须统一使用 ACTIVE_FEATURE_MANIFESTS",
    }
    failures: list[str] = []
    for root in (ROOT / "game", ROOT / "launch", ROOT / "message"):
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for symbol, reason in forbidden.items():
                if symbol in source:
                    failures.append(
                        f"{path.relative_to(ROOT).as_posix()} 仍包含退役符号 "
                        f"{symbol}：{reason}"
                    )
    assert not failures, "\n".join(failures)


def _assert_battle_modes_use_core_session() -> None:
    """连续战斗模式不能绕过核心会话自行维护状态轨迹。"""

    battle_modes = (
        ROOT / "game" / "rules" / "exploration" / "battle.py",
        ROOT / "game" / "features" / "dimensional_disaster" / "battle.py",
    )
    forbidden = (
        "self.engine.execute_turn(",
        "replace(state",
        "initial_entities",
        "round_entities",
        "turn_entities",
    )
    for path in battle_modes:
        source = path.read_text(encoding="utf-8")
        assert "BattleSession.start(" in source, path
        assert "session.execute_turn(" in source, path
        assert "session.apply_external(" in source, path
        assert not any(value in source for value in forbidden), path


def _assert_database_write_boundary() -> None:
    """SQLite 和快照实现只能由持久化层、游戏组合根和测试持有。"""

    failures: list[str] = []
    for path in (ROOT / "game").rglob("*.py"):
        relative = path.relative_to(ROOT)
        if (
            _is_below(relative, Path("game/core/persistence"))
            or relative == Path("game/app.py")
        ):
            continue
        tree = _parse(path)
        for imported in _imports(tree, path):
            if imported == "sqlite3" or imported.startswith("sqlite3."):
                failures.append(f"{relative.as_posix()} 直接导入 sqlite3")
            if imported == "game.core.persistence" or imported.startswith(
                "game.core.persistence."
            ):
                failures.append(
                    f"{relative.as_posix()} 绕过持久化协调服务导入 {imported}"
                )
    assert not failures, "\n".join(failures)


def _assert_feature_layer_boundary() -> None:
    """正式玩法只能向下依赖内容、规则和公共核心，不能反向吞掉外层。"""

    failures: list[str] = []
    features = ROOT / "game" / "features"
    forbidden = ("launch", "message", "game.cmd", "game.app", "组件测试")
    for path in features.rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        for imported in _imports(_parse(path), path):
            if any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in forbidden):
                failures.append(f"{relative} 反向导入外层模块 {imported}")

    allowed_root_files = {"__init__.py", "app.py"}
    unexpected = sorted(
        path.name
        for path in (ROOT / "game").glob("*.py")
        if path.name not in allowed_root_files
    )
    failures.extend(f"game 根目录出现业务模块 {name}，请归入 features" for name in unexpected)
    assert not failures, "\n".join(failures)


def _assert_feature_sql_boundary() -> None:
    """玩法可以控制工作单元，但 SQL 只能由持久化仓储拥有。"""

    failures = []
    for path in (ROOT / "game" / "features").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if ".connection.execute(" in source:
            failures.append(
                f"{path.relative_to(ROOT).as_posix()} 直接执行 SQL，请下沉到持久化仓储"
            )
    assert not failures, "\n".join(failures)


def _assert_balance_values_live_in_content() -> None:
    """可调概率、阈值和初始资产不能重新定义在规则或玩法层。"""

    balance_name = re.compile(
        r"(?:CHANCE|RATIO|WEIGHT|AMOUNT|CAPACITY|QUANTITY|RECOVERY_SECONDS|PRESET_IDS|WINDOW)$"
        r"|^INITIAL_|^LEVEL_CORE_ATTRIBUTE_|^CHARACTER_MAXIMUM_LEVEL$"
        r"|^GLOBAL_ACTIVITY_SPOTLIGHT_LIMIT$"
    )
    failures: list[str] = []
    for root in (ROOT / "game" / "rules", ROOT / "game" / "features"):
        for path in root.rglob("*.py"):
            tree = _parse(path)
            for node in tree.body:
                names: list[str] = []
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    names = [target.id for target in targets if isinstance(target, ast.Name)]
                for name in names:
                    if balance_name.search(name):
                        failures.append(
                            f"{path.relative_to(ROOT).as_posix()} 在外层声明平衡参数 {name}"
                        )
    assert not failures, "\n".join(failures)


def _assert_cross_domain_state_fields() -> None:
    actual: set[tuple[str, str, str, str]] = set()
    aggregate_failures: list[str] = []
    for path in CORE.rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        tree = _parse(path)
        imports = _imported_names(tree, path)
        owner_domain = _domain_for_module(_module_name(path))
        for class_node in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            for field in _class_fields(class_node):
                for state_name, source in _state_references(field.annotation, imports):
                    source_domain = _domain_for_module(source)
                    if not source_domain or source_domain == owner_domain:
                        continue
                    key = (relative, class_node.name, field.target.id, state_name)
                    actual.add(key)
                    if class_node.name.endswith("State") and key not in {
                        (
                            "game/core/gameplay/equipment/models.py",
                            "EquipmentState",
                            "roll",
                            "ItemRollState",
                        ),
                        (
                            "game/core/gameplay/weapon/models.py",
                            "WeaponState",
                            "roll",
                            "ItemRollState",
                        ),
                    }:
                        aggregate_failures.append(
                            f"{relative}:{field.lineno} 聚合 {class_node.name} "
                            f"不得拥有外域状态 {state_name}"
                        )

    unknown = actual - APPROVED_CROSS_DOMAIN_STATE_FIELDS
    stale = APPROVED_CROSS_DOMAIN_STATE_FIELDS - actual
    failures = aggregate_failures
    failures.extend(
        f"{path}:{owner}.{field} 新增跨域状态字段 {state}；"
        "请移到显式组合结果或持久化协调服务并接受审计"
        for path, owner, field, state in sorted(unknown)
    )
    failures.extend(
        f"跨域状态白名单已经失效，请删除：{path}:{owner}.{field} -> {state}"
        for path, owner, field, state in sorted(stale)
    )
    assert not failures, "\n".join(failures)


def _assert_dynamic_field_registry() -> None:
    actual: set[tuple[str, str, str]] = set()
    for path in CORE.rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        tree = _parse(path)
        for class_node in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            for field in _class_fields(class_node):
                if _is_dynamic_annotation(field.annotation):
                    actual.add((relative, class_node.name, field.target.id))

    unknown = actual - APPROVED_DYNAMIC_FIELDS
    stale = APPROVED_DYNAMIC_FIELDS - actual
    failures = [
        f"{path}:{owner}.{field} 新增万能动态字段；请改为类型化契约或登记审核理由"
        for path, owner, field in sorted(unknown)
    ]
    failures.extend(
        f"动态字段白名单已经失效，请删除：{path}:{owner}.{field}"
        for path, owner, field in sorted(stale)
    )
    assert not failures, "\n".join(failures)


def _assert_foundation_coverage() -> None:
    versions: dict[str, tuple[str, Path]] = {}
    failures: list[str] = []
    pattern = re.compile(r"^[a-z][a-z0-9-]*\.foundation\.v[1-9][0-9]*$")
    for path in CORE.rglob("*.py"):
        tree = _parse(path)
        for node in tree.body:
            assignment = _constant_assignment(node)
            if assignment is None:
                continue
            name, value = assignment
            if not name.endswith("FOUNDATION_VERSION"):
                continue
            if name in versions:
                failures.append(f"{name} 被重复定义")
                continue
            versions[name] = (value, path)
            if not pattern.fullmatch(value):
                failures.append(f"{name} 版本格式非法：{value}")
            if not any(
                candidate.is_file() and re.search(r"[\u4e00-\u9fff]", candidate.name)
                for candidate in path.parent.glob("*.md")
            ):
                failures.append(f"{path.parent.relative_to(ROOT)} 缺少中文底座说明文档")

    unknown = set(versions) - set(FOUNDATION_TESTS)
    stale = set(FOUNDATION_TESTS) - set(versions)
    failures.extend(f"新增底座 {name} 尚未登记测试文件" for name in sorted(unknown))
    failures.extend(f"测试登记对应的底座已不存在：{name}" for name in sorted(stale))
    for name, test_name in FOUNDATION_TESTS.items():
        test_path = ROOT / test_name
        if not test_path.is_file():
            failures.append(f"{name} 缺少测试文件 {test_name}")
        elif not _asserts_name(_parse(test_path), name):
            failures.append(f"{test_name} 没有使用 assert 锁定 {name}")
    assert not failures, "\n".join(failures)


def _assert_changed_core_has_evidence() -> None:
    """CI 可设置基线引用，要求核心改动同时提交测试、文档和公共版本。"""

    base_ref = os.getenv("CORE_GUARD_BASE_REF", "").strip()
    if not base_ref:
        return
    # 直接比较基线和工作树，本地提交前与 CI 提交后都能使用同一规则。
    changed = set(_git_lines("diff", "--name-only", base_ref))
    changed.update(_git_lines("ls-files", "--others", "--exclude-standard"))
    core_changes = {name for name in changed if name.startswith("game/core/")}
    if not core_changes:
        return
    failures: list[str] = []
    if not any(name.startswith(".test/") and name.endswith("_test.py") for name in changed):
        failures.append("核心有变更，但没有同步提交 .test/*_test.py")
    if not any(
        name.endswith(".md")
        and (name.startswith("game/core/") or name.startswith("design/"))
        for name in changed
    ):
        failures.append("核心有变更，但没有同步提交中文说明文档")
    public_changes = {
        name
        for name in core_changes
        if name.endswith("/__init__.py") or name == "game/core/__init__.py"
    }
    if public_changes:
        old_core = _git_file(base_ref, "game/core/__init__.py")
        old_public = _git_file(base_ref, "game/__init__.py")
        current_core = (ROOT / "game/core/__init__.py").read_text(encoding="utf-8")
        current_public = (ROOT / "game/__init__.py").read_text(encoding="utf-8")
        if _assigned_string(old_core, "GAME_CORE_VERSION") == _assigned_string(
            current_core, "GAME_CORE_VERSION"
        ):
            failures.append("核心公开入口有变更，但 GAME_CORE_VERSION 没有升级")
        if _assigned_string(old_public, "PUBLIC_FOUNDATION_VERSION") == _assigned_string(
            current_public, "PUBLIC_FOUNDATION_VERSION"
        ):
            failures.append("核心公开入口有变更，但 PUBLIC_FOUNDATION_VERSION 没有升级")
    assert not failures, "\n".join(failures)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _class_fields(class_node: ast.ClassDef) -> tuple[ast.AnnAssign, ...]:
    return tuple(
        node
        for node in class_node.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    )


def _is_dynamic_annotation(annotation: ast.expr) -> bool:
    return any(
        isinstance(node, ast.Name) and node.id in {"Any", "object"}
        for node in ast.walk(annotation)
    )


def _state_references(
    annotation: ast.expr,
    imports: dict[str, str],
) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for node in ast.walk(annotation):
        if isinstance(node, ast.Name) and node.id.endswith("State"):
            source = imports.get(node.id)
            if source:
                result.add((node.id, source))
        elif (
            isinstance(node, ast.Attribute)
            and node.attr.endswith("State")
            and isinstance(node.value, ast.Name)
        ):
            source = imports.get(node.value.id)
            if source:
                result.add((node.attr, source))
    return result


def _imported_names(tree: ast.Module, path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    package = _package_name(path)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = resolve_name("." * node.level + module, package)
            for alias in node.names:
                result[alias.asname or alias.name] = module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                result[alias.asname or alias.name.split(".", 1)[0]] = alias.name
    return result


def _imports(tree: ast.Module, path: Path) -> tuple[str, ...]:
    package = _package_name(path)
    result: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = resolve_name("." * node.level + module, package)
            result.append(module)
            result.extend(
                f"{module}.{alias.name}" if module else alias.name
                for alias in node.names
                if alias.name != "*"
            )
    return tuple(result)


def _module_name(path: Path) -> str:
    relative = path.relative_to(ROOT).with_suffix("")
    parts = relative.parts[:-1] if path.name == "__init__.py" else relative.parts
    return ".".join(parts)


def _package_name(path: Path) -> str:
    module = _module_name(path)
    return module if path.name == "__init__.py" else module.rsplit(".", 1)[0]


def _domain_for_module(module: str) -> str:
    parts = module.split(".")
    if parts[:3] == ["game", "core", "gameplay"] and len(parts) >= 4:
        return parts[3]
    if parts[:2] == ["game", "core"] and len(parts) >= 3:
        return parts[2]
    return ""


def _constant_assignment(node: ast.stmt) -> tuple[str, str] | None:
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target, value = node.targets[0], node.value
    elif isinstance(node, ast.AnnAssign):
        target, value = node.target, node.value
    else:
        return None
    if (
        isinstance(target, ast.Name)
        and isinstance(value, ast.Constant)
        and isinstance(value.value, str)
    ):
        return target.id, value.value
    return None


def _asserts_name(tree: ast.Module, name: str) -> bool:
    return any(
        isinstance(node, ast.Assert)
        and any(
            isinstance(candidate, ast.Name) and candidate.id == name
            for candidate in ast.walk(node.test)
        )
        for node in ast.walk(tree)
    )


def _assigned_string(source: str, name: str) -> str | None:
    for node in ast.parse(source).body:
        assignment = _constant_assignment(node)
        if assignment and assignment[0] == name:
            return assignment[1]
    return None


def _git_lines(*arguments: str) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "-c", "core.quotePath=false", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    return tuple(
        line.strip().replace("\\", "/")
        for line in result.stdout.splitlines()
        if line.strip()
    )


def _git_file(ref: str, path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    return result.stdout


def _is_below(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


if __name__ == "__main__":
    main()
