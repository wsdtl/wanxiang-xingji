"""核心、正式修仙产品与测试业务的物理归属和单向依赖测试。"""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import game  # noqa: E402
from game import core  # noqa: E402
from game import cmd  # noqa: E402
from game.content.presentation import GAME_NAME, GAME_TITLE  # noqa: E402
from game.core import account, gameplay, persistence  # noqa: E402


def main() -> None:
    _assert_physical_layout()
    _assert_test_support_boundaries()
    _assert_product_identity()
    _assert_ascii_python_identifiers()
    _assert_ascii_static_import_paths()
    _assert_public_root()
    _assert_layer_public_exports()
    _assert_import_boundaries()
    _assert_game_reply_boundaries()
    _assert_application_assembly_boundaries()
    _assert_command_helper_boundaries()
    _assert_extension_consumers_use_composed_catalogs()
    _assert_content_registration_boundaries()
    _assert_core_neutrality()
    _assert_world_identity_boundaries()
    print("core architecture tests passed")


def _assert_test_support_boundaries() -> None:
    """离线审计器只能依赖生产代码，生产代码不得反向携带或依赖审计器。"""

    forbidden_runtime_files = (
        ROOT / "game" / "core" / "gameplay" / "itemization" / "audit.py",
        ROOT / "game" / "content" / "catalog" / "equipment" / "balance.py",
        ROOT / "game" / "content" / "catalog" / "weapon" / "balance.py",
    )
    for path in forbidden_runtime_files:
        assert not path.exists(), f"测试审计器不得留在生产目录：{path.relative_to(ROOT)}"

    support = ROOT / ".test" / "support"
    for filename in (
        "itemization_balance_audit.py",
        "equipment_balance_audit.py",
        "weapon_balance_audit.py",
    ):
        assert (support / filename).is_file(), f"缺少测试审计支持：{filename}"

    valuation = ROOT / "game" / "content" / "catalog" / "weapon" / "valuation.py"
    assert valuation.is_file(), "正式武器价值估算必须独立于测试审计器"
    for path in (ROOT / "game").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "from support" not in source and "import support" not in source, (
            f"生产代码反向依赖了测试支持：{path.relative_to(ROOT)}"
        )


def _assert_product_identity() -> None:
    """玩家品牌与正式背景必须拥有单一、可审计的事实来源。"""

    assert GAME_NAME == "万象行纪"
    assert GAME_TITLE == "《万象行纪》"
    assert (ROOT / "README.md").read_text(encoding="utf-8").startswith("# 万象行纪\n")
    background = ROOT / "design" / "万象行纪世界设定.md"
    assert background.is_file()
    source = background.read_text(encoding="utf-8")
    for required in ("无穷界海", "唯一化身", "跨界灾厄", "铭刻之羽"):
        assert required in source, f"正式背景缺少主轴：{required}"


def _assert_ascii_python_identifiers() -> None:
    """二级组件目录可用中文，Python 文件名与代码标识符必须使用英文。"""

    failures: list[str] = []
    for path in (ROOT / "game").rglob("*.py"):
        relative = path.relative_to(ROOT)
        if not path.name.isascii():
            failures.append(f"{relative} 的 Python 文件名不是英文")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        identifiers: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                identifiers.append(node.name)
            elif isinstance(node, ast.Name):
                identifiers.append(node.id)
            elif isinstance(node, ast.arg):
                identifiers.append(node.arg)
            elif isinstance(node, ast.Attribute):
                identifiers.append(node.attr)
            elif isinstance(node, ast.alias) and node.asname:
                identifiers.append(node.asname)
        invalid = sorted({name for name in identifiers if not name.isascii()})
        if invalid:
            failures.append(f"{relative} 存在中文代码标识符：{', '.join(invalid)}")
    assert not failures, "\n".join(failures)


def _assert_ascii_static_import_paths() -> None:
    """中文二级组件必须动态加载，静态 import 路径统一使用英文。"""

    failures: list[str] = []
    for path in (ROOT / "game").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules = (node.module,) if node.module else ()
            else:
                continue
            for module in modules:
                if not module.isascii():
                    failures.append(f"{path.relative_to(ROOT)} 存在中文静态导包：{module}")
    assert not failures, "\n".join(failures)


def _assert_physical_layout() -> None:
    game = ROOT / "game"
    core = game / "core"
    assert (game / "__init__.py").is_file()
    assert core.is_dir()
    for name in ("gameplay", "account", "persistence"):
        assert (core / name / "__init__.py").is_file()
        assert not (ROOT / name).exists(), f"禁止保留旧顶层兼容包：{name}"
    assert (core / "gameplay" / "grants" / "__init__.py").is_file()

    commands = game / "cmd"
    assert (commands / "__init__.py").is_file()
    assert not (commands / "后台接口").exists(), "禁止保留空的后台接口占位组件"
    assert not (game / "修仙4").exists(), "禁止保留提前建立的旧产品目录"

    content = game / "content"
    assert (content / "__init__.py").is_file()
    assert (content / "official.py").is_file()
    assert (content / "presentation" / "__init__.py").is_file()
    assert (content / "presentation" / "gear.py").is_file()
    assert not (content / "runtime.py").exists(), "官方内容装配不得再使用 runtime 名称"
    catalog = content / "catalog"
    assert (catalog / "__init__.py").is_file()
    assert {path.name for path in catalog.glob("*.py")} == {
        "__init__.py",
        "foundation.py",
        "package.py",
    }, "名录根目录只能保留公共入口、跨领域基础和内容包装配"
    catalog_domains = {
        "activity": {"__init__.py", "policy.py"},
        "companion": {"__init__.py", "definitions.py", "models.py"},
        "character": {
            "__init__.py",
            "definitions.py",
            "identity.py",
            "realms.py",
            "recovery.py",
            "starting.py",
        },
        "combat": {"__init__.py", "definitions.py", "stats.py", "valuation.py"},
        "disaster": {
            "__init__.py",
            "catalog.py",
            "combat.py",
            "cultivation.py",
            "magic.py",
            "stellar_ring.py",
            "models.py",
            "policy.py",
        },
        "draw": {"__init__.py", "definitions.py"},
        "redemption_code": {"__init__.py", "definitions.py"},
        "enemy": {
            "__init__.py",
            "behaviors.py",
            "blueprints.py",
            "definitions.py",
            "encounters.py",
            "loadouts.py",
            "loot.py",
            "party.py",
        },
        "exploration": {"__init__.py", "definitions.py"},
        "item": {
            "__init__.py",
            "breakthrough.py",
            "classification.py",
            "definitions.py",
            "draw.py",
            "exchange.py",
            "special.py",
            "trade.py",
            "trophies.py",
        },
        "social": {"__init__.py"},
        "trial": {"__init__.py", "definitions.py", "models.py"},
        "weapon": {
            "__init__.py",
            "blueprints.py",
            "definitions.py",
            "mechanics.py",
            "official_mechanics.py",
            "registry.py",
            "valuation.py",
        },
        "equipment": {
            "__init__.py",
            "blueprints.py",
            "definitions.py",
            "ids.py",
            "mechanisms.py",
            "properties.py",
        },
        "economy": {
            "__init__.py",
            "audit.py",
            "exchange.py",
            "lottery.py",
            "market_items.py",
            "policy.py",
        },
        "world": {"__init__.py", "definitions.py"},
        "world_progress": {"__init__.py", "definitions.py"},
    }
    assert {path.name for path in catalog.iterdir() if path.is_dir() and path.name != "__pycache__"} == set(
        catalog_domains
    ), "名录领域目录必须同步登记到架构契约"
    for domain_name, expected_modules in catalog_domains.items():
        domain = catalog / domain_name
        assert domain.is_dir(), f"名录领域缺失：{domain_name}"
        assert {path.name for path in domain.glob("*.py")} == expected_modules
    display_tokens = (
        "cultivation_name",
        "magic_name",
        "cultivation_suffix",
        "magic_suffix",
        "promise",
        "description: str",
        "equipment_name",
    )
    for blueprint_path in (
        catalog / "weapon" / "blueprints.py",
        catalog / "equipment" / "blueprints.py",
    ):
        source = blueprint_path.read_text(encoding="utf-8")
        leaked = [token for token in display_tokens if token in source]
        assert not leaked, f"规则蓝图泄漏世界皮肤展示字段：{blueprint_path.name}/{leaked}"
    world_skins = content / "world_skins"
    assert (world_skins / "__init__.py").is_file()
    assert (world_skins / "validation.py").is_file()
    assert not (content / "skins").exists(), "具体世界皮肤必须归入 world_skins"
    from game.content.world_skins import WORLD_SKIN_PACKAGE

    registered_skin_names = {str(pack.id).rsplit(".", 1)[-1] for pack in WORLD_SKIN_PACKAGE.skin_packs}
    actual_skin_names = {path.name for path in world_skins.iterdir() if path.is_dir() and path.name != "__pycache__"}
    assert actual_skin_names == registered_skin_names, (
        f"世界皮肤目录必须与官方世界包登记同步：目录={sorted(actual_skin_names)} 登记={sorted(registered_skin_names)}"
    )
    worlds = content / "worlds"
    assert (worlds / "__init__.py").is_file()
    assert (worlds / "package.py").is_file()
    from game.content.worlds import WORLD_PACKAGE

    assert WORLD_PACKAGE.world_definitions
    assert WORLD_PACKAGE.world_location_bindings
    assert not WORLD_SKIN_PACKAGE.world_definitions
    assert not WORLD_SKIN_PACKAGE.world_location_bindings
    for skin_name in sorted(registered_skin_names):
        skin = world_skins / skin_name
        for module_name in (
            "base.py",
            "character.py",
            "combat.py",
            "equipment.py",
            "items.py",
            "trophies.py",
            "presentation.py",
            "skin.py",
            "weapons.py",
            "world.py",
        ):
            assert (skin / module_name).is_file()

    gameplay = core / "gameplay"
    assert (gameplay / "content" / "skins.py").is_file()
    assert not (gameplay / "skins.py").exists(), "皮肤契约必须归入核心内容子域"

    rules = game / "rules"
    assert (rules / "__init__.py").is_file()
    assert (rules / "activity" / "__init__.py").is_file()
    assert (rules / "character" / "__init__.py").is_file()
    assert not (game / "product").exists(), "禁止保留含义重复的 product 层"
    assert not (game / "service").exists(), "具体规则不得再使用 service 层名称"

    assert (game / "app.py").is_file()
    assert not (game / "runtime").exists(), "应用装配不得再使用 runtime 目录"
    assert not (ROOT / "auto" / "game").exists(), "游戏组合根不得放回 auto/"

    world_extensions = content / "extensions" / "official"
    required_world_modules = {
        "__init__.py",
        "extension.py",
        "world.py",
        "companions.py",
        "enemies.py",
        "disasters.py",
        "lore.py",
        "skin.py",
    }
    for name in ("taixuan", "magic", "stellar_ring"):
        extension = world_extensions / name
        assert {value.name for value in extension.glob("*.py")} == required_world_modules

    for component_name in ("活动", "提醒", "角色"):
        component = commands / component_name
        assert (component / "__init__.py").is_file()
        assert (component / "service.py").is_file()
        assert (component / "说明.md").is_file()

    assert (ROOT / "组件测试" / "QQ协议测试" / "__init__.py").is_file()
    for legacy in ("src", "components"):
        assert not (ROOT / legacy).exists(), f"禁止保留旧目录：{legacy}"


def _assert_public_root() -> None:
    assert game.PUBLIC_FOUNDATION_VERSION == "public-foundation.v11"
    assert set(game.__all__) == {"PUBLIC_FOUNDATION_VERSION"}
    assert cmd.router is not None
    assert core.GAME_CORE_VERSION == "game-core.v12"
    assert core.CORE_LAYERS == (
        "game.core.gameplay",
        "game.core.account",
        "game.core.persistence",
    )
    assert set(core.__all__) == {"CORE_LAYERS", "GAME_CORE_VERSION"}


def _assert_application_assembly_boundaries() -> None:
    """组合根分阶段但保持唯一公开构建入口。"""

    path = ROOT / "game" / "app.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "build_game_services" in functions
    assert {
        "_assemble_content",
        "_assemble_foundation",
        "_assemble_world_features",
        "_assemble_economy_features",
        "_assemble_player_features",
        "_assemble_social_features",
    }.issubset(functions)
    assert not (ROOT / "game" / "runtime").exists()
    exploration_reporting = ROOT / "game" / "features" / "exploration" / "reporting.py"
    reporting_source = exploration_reporting.read_text(encoding="utf-8")
    assert "unit_of_work" not in reporting_source
    assert "game.core.persistence" not in reporting_source


def _assert_command_helper_boundaries() -> None:
    """命令组件复用统一时间和角色取值，不再各自复制实现。"""

    helper = ROOT / "game" / "cmd" / "command_helpers.py"
    assert helper.is_file()
    failures = []
    for path in (ROOT / "game" / "cmd").glob("*/service.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        local_helpers = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {"_now", "_character"}
        }
        if local_helpers:
            failures.append(f"{path.relative_to(ROOT)} 重复定义命令工具：{', '.join(sorted(local_helpers))}")
        source = path.read_text(encoding="utf-8")
        if "datetime.now(" in source:
            failures.append(f"{path.relative_to(ROOT)} 绕过统一命令时钟")
    assert not failures, "\n".join(failures)


def _assert_layer_public_exports() -> None:
    for module in (account, gameplay, persistence):
        exports = tuple(module.__all__)
        assert len(exports) == len(set(exports)), f"{module.__name__} 存在重复公开符号"
        missing = tuple(name for name in exports if not hasattr(module, name))
        assert not missing, f"{module.__name__} 缺少公开符号：{', '.join(missing)}"


def _assert_world_identity_boundaries() -> None:
    """玩法必须使用 world_id；skin_id 只能服务展示与历史还原。"""

    forbidden = {
        "CharacterDimensionState": "旧角色界相类型",
        "CHARACTER_DIMENSION_AGGREGATE": "旧角色界相聚合",
        "snapshot.character_dimension": "旧角色界相快照",
        "world_space.primary": "共享世界空间",
        ".character_world.skin_id": "角色世界状态读取皮肤",
        "source_skin_id": "把玩法内容来源绑定到展示皮肤",
        "PLAYABLE_WORLD_SKIN_IDS": "让展示皮肤声明世界可进入性",
        "shift_character_dimension": "旧跃迁应用接口",
    }
    failures = []
    for path in (ROOT / "game").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for token, label in forbidden.items():
            if token in source:
                failures.append(f"{path.relative_to(ROOT)} 仍包含{label}: {token}")
    assert not failures, "\n".join(failures)


def _assert_import_boundaries() -> None:
    forbidden_by_layer = {
        "gameplay": {"launch", "message", "组件测试", "account", "persistence"},
        "account": {
            "launch",
            "message",
            "组件测试",
            "gameplay",
            "persistence",
        },
        "persistence": {"launch", "message", "组件测试"},
    }
    failures: list[str] = []
    for layer, forbidden in forbidden_by_layer.items():
        folder = ROOT / "game" / "core" / layer
        for path in folder.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for imported in _imports(tree, path):
                root_name = imported.split(".", 1)[0]
                core_layer = imported.split(".", 3)[2] if imported.startswith("game.core.") else root_name
                if core_layer in forbidden or _is_game_integration(imported) or _is_game_product(imported):
                    failures.append(f"{path.relative_to(ROOT)} 导入了禁止层 {imported}")
    for folder_name in ("launch", "message"):
        for path in (ROOT / folder_name).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if any(
                imported == "game"
                or imported.startswith("game.")
                or (folder_name == "message" and (imported == "launch" or imported.startswith("launch.")))
                for imported in _imports(tree, path)
            ):
                failures.append(f"{path.relative_to(ROOT)} 违反公共框架与游戏代码依赖边界")
    for path in (ROOT / "组件测试").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in _imports(tree, path):
            if imported == "game" or imported.startswith("game."):
                failures.append(f"{path.relative_to(ROOT)} 协议测试不得依赖游戏代码 {imported}")
    for path in (ROOT / "game" / "content").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in _imports(tree, path):
            if (
                imported == "launch"
                or imported.startswith("launch.")
                or imported == "message"
                or imported.startswith("message.")
                or imported == "auto"
                or imported.startswith("auto.")
                or imported == "组件测试"
                or imported.startswith("组件测试.")
                or _is_game_integration(imported)
                or _is_game_policy(imported)
                or imported == "game.core.account"
                or imported.startswith("game.core.account.")
                or imported == "game.core.persistence"
                or imported.startswith("game.core.persistence.")
            ):
                failures.append(f"{path.relative_to(ROOT)} 正式内容层导入了禁止模块 {imported}")
    for path in (ROOT / "game" / "rules" / "character").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in _imports(tree, path):
            if (
                imported == "launch"
                or imported.startswith("launch.")
                or imported == "message"
                or imported.startswith("message.")
                or imported == "auto"
                or imported.startswith("auto.")
                or imported == "组件测试"
                or imported.startswith("组件测试.")
                or _is_game_integration(imported)
                or imported == "game.core.persistence"
                or imported.startswith("game.core.persistence.")
            ):
                failures.append(f"{path.relative_to(ROOT)} 角色内部策略导入了禁止模块 {imported}")
    for path in (ROOT / "game" / "cmd").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in _imports(tree, path):
            private_driver = imported.startswith("launch.adapter.qq") or imported.startswith("launch.adapter.local")
            registration_bypass = path.name == "__init__.py" and (
                imported == "game.core"
                or imported.startswith("game.core.")
                or imported == "game.content"
                or imported.startswith("game.content.")
                or imported == "game.app"
                or imported.startswith("game.app.")
            )
            if private_driver or registration_bypass:
                failures.append(f"{path.relative_to(ROOT)} 命令注册入口导入了禁止模块 {imported}")
    assert not failures, "\n".join(failures)


def _assert_extension_consumers_use_composed_catalogs() -> None:
    """业务不得绕过扩展装配重新读取基础包静态映射。"""

    forbidden = {
        "MARKET_ITEM_POLICIES",
        "PARTY_BOSS_TROPHY_ITEM_IDS",
    }
    failures: list[str] = []
    for root in (ROOT / "game" / "features", ROOT / "game" / "cmd"):
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                imported = forbidden & {alias.name for alias in node.names}
                if imported:
                    failures.append(
                        f"{path.relative_to(ROOT)} 绕过扩展目录导入静态映射：" + ", ".join(sorted(imported))
                    )
    assert not failures, "\n".join(failures)


def _assert_content_registration_boundaries() -> None:
    """正式机制必须由单点声明驱动，扩展必须保持无中央清单发现。"""

    from game.content.catalog.equipment.blueprints import (
        EQUIPMENT_SET_BLUEPRINTS,
        MECHANIC_EQUIPMENT_PROPERTY_BLUEPRINTS,
    )
    from game.content.catalog.equipment.mechanisms import (
        OFFICIAL_EQUIPMENT_MECHANICS,
    )
    from game.content.catalog.weapon.blueprints import WEAPON_BLUEPRINTS
    from game.content.catalog.weapon.official_mechanics import (
        OFFICIAL_WEAPON_MECHANICS,
    )

    equipment_root = ROOT / "game" / "content" / "catalog" / "equipment"
    weapon_root = ROOT / "game" / "content" / "catalog" / "weapon"
    definitions_source = (equipment_root / "definitions.py").read_text(encoding="utf-8")
    properties_source = (equipment_root / "properties.py").read_text(encoding="utf-8")
    weapon_assembly_source = (weapon_root / "mechanics.py").read_text(encoding="utf-8")
    assert "_set_bonuses" not in definitions_source
    assert all(len(blueprint.bonuses) == 3 for blueprint in EQUIPMENT_SET_BLUEPRINTS)
    assert "_mechanic_content" not in properties_source
    assert "_base_damage_operations" not in weapon_assembly_source
    assert "if blueprint.primary" not in weapon_assembly_source
    assert "if support" not in weapon_assembly_source

    equipment_blueprints = {(value.key, value.category) for value in MECHANIC_EQUIPMENT_PROPERTY_BLUEPRINTS}
    equipment_definitions = {(value.key, value.category) for value in OFFICIAL_EQUIPMENT_MECHANICS.definitions.values()}
    assert equipment_blueprints == equipment_definitions
    for mechanism in OFFICIAL_EQUIPMENT_MECHANICS.definitions.values():
        for tier in (1, 2, 3):
            compiled = mechanism.compile(tier)
            assert compiled.effects and compiled.triggers

    OFFICIAL_WEAPON_MECHANICS.validate_blueprints(WEAPON_BLUEPRINTS)
    for blueprint in WEAPON_BLUEPRINTS:
        recipe = OFFICIAL_WEAPON_MECHANICS.resolve(blueprint)
        assert recipe.primary.compile(blueprint).operations
        recipe.support.compile(blueprint, f"ability.weapon.{blueprint.key}")

    discovery = (ROOT / "game" / "content" / "extensions" / "discovery.py").read_text(encoding="utf-8")
    for required in (
        "pkgutil.iter_modules",
        "sorted(",
        'module.name.startswith("_")',
        '"CONTENT_EXTENSION"',
        '"WORLD_EXTENSION"',
    ):
        assert required in discovery, f"扩展发现契约缺少：{required}"

    authoring = (ROOT / "game" / "content" / "extensions" / "authoring.py").read_text(encoding="utf-8")
    for required in (
        "build_weapon_content_extension",
        "build_equipment_content_extension",
        "build_equipment_mechanic_content_extension",
        "build_weapon_mechanic_content",
        "build_equipment_catalog_content",
    ):
        assert required in authoring, f"扩展作者入口缺少：{required}"
    world_factory = (
        ROOT / "game" / "content" / "extensions" / "official" / "_factory.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "COMPANION_CATALOG",
        "ENEMY_BEHAVIOR_PROFILE_CATALOG",
        "PARTY_BOSS_SOURCE_CATALOG",
        "PARTY_BOSS_TROPHY_ITEM_IDS",
        "WORLD_SPACES",
    ):
        assert forbidden not in world_factory, f"世界扩展工厂仍隐式查询中央目录：{forbidden}"

    forbidden_imports: list[str] = []
    for path in (ROOT / "game").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in _imports(tree, path):
            if imported in {"test", "ops"} or imported.startswith(("test.", "ops.")):
                forbidden_imports.append(f"{path.relative_to(ROOT)} 导入了离线目录 {imported}")
    assert not forbidden_imports, "\n".join(forbidden_imports)


def _assert_core_neutrality() -> None:
    """真正核心不能倒灌产品词、模块随机源或机器当前时间。"""

    product_terms = ("宗门", "仙城", "纳戒", "探险", "首领", "洞天", "修仙")
    failures: list[str] = []
    core = ROOT / "game" / "core"
    for path in core.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT)
        for term in product_terms:
            if term in source:
                failures.append(f"{relative} 出现具体产品词 {term}")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "random" and path.name != "context.py":
                        failures.append(f"{relative} 直接导入模块随机源")
            elif isinstance(node, ast.ImportFrom) and node.module == "random":
                failures.append(f"{relative} 直接导入模块随机源")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                owner = node.func.value
                if isinstance(owner, ast.Name) and owner.id == "datetime" and node.func.attr in {"now", "utcnow"}:
                    failures.append(f"{relative} 直接读取机器当前时间")
                if isinstance(owner, ast.Name) and owner.id == "time" and node.func.attr == "time":
                    failures.append(f"{relative} 直接读取机器当前时间")
    assert not failures, "\n".join(failures)


def _assert_game_reply_boundaries() -> None:
    """全局通知通栏和彩色人物头只能由统一回复装饰器生成。"""

    failures: list[str] = []
    reply_path = ROOT / "game" / "cmd" / "reply.py"
    for path in (ROOT / "game" / "cmd").rglob("*.py"):
        if path == reply_path:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            relative = path.relative_to(ROOT)
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr == "inline_section":
                failures.append(f"{relative} 手写了全局通知通栏")
            if node.func.attr == "header" and any(keyword.arg == "color" for keyword in node.keywords):
                failures.append(f"{relative} 手写了彩色人物头")
    assert not failures, "\n".join(failures)


def _is_game_core(imported: str) -> bool:
    return imported == "game.core" or imported.startswith("game.core.")


def _is_game_integration(imported: str) -> bool:
    return imported == "game.cmd" or imported.startswith("game.cmd.")


def _is_game_product(imported: str) -> bool:
    return imported == "game.content" or imported.startswith("game.content.") or _is_game_policy(imported)


def _is_game_policy(imported: str) -> bool:
    return imported == "game.rules" or imported.startswith("game.rules.")


def _imports(tree: ast.AST, path: Path) -> tuple[str, ...]:
    result: list[str] = []
    relative = path.relative_to(ROOT).with_suffix("")
    package_parts = relative.parts[:-1]
    if path.name == "__init__.py":
        package_parts = relative.parts[:-1]
    package = ".".join(package_parts)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                result.append(node.module)
            elif node.level > 0:
                relative_name = "." * node.level + (node.module or "")
                result.append(resolve_name(relative_name, package))
    return tuple(result)


if __name__ == "__main__":
    main()
