"""内容激活状态和显式切换工具。"""

from __future__ import annotations

import argparse
import ast
from datetime import datetime
import json
import keyword
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

# 直接执行隐藏目录脚本时，解释器默认只把 .ops 放入 sys.path。
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.content import assemble_official_catalog
from game.core.persistence import (
    ContentActivationMismatch,
    ContentActivationStore,
    SnapshotRepository,
    SqliteDatabase,
    gameplay_snapshot_codec,
)
from game.cmd.数据库备份.service import (
    DATABASE_FILENAME,
    backup_wanxiang_xingji_database,
)
from game.features.catalog import feature_snapshot_codec_registrations
from game.rules.companion import (
    COMPANION_SANCTUARY_AGGREGATE,
    CompanionSanctuaryState,
)
from game.rules.disaster import (
    DIMENSIONAL_DISASTER_AGGREGATE,
    DimensionalDisasterState,
    DimensionalDisasterStatus,
)
from launch.config import config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python .ops/__main__.py")
    subparsers = parser.add_subparsers(dest="command", required=True)
    status = subparsers.add_parser("content-status", help="显示数据库与当前内容的激活状态")
    status.add_argument(
        "--database",
        help="目标数据库路径；省略时使用项目 .env 的 DATABASE_PATH",
    )
    activate = subparsers.add_parser("content-activate", help="显式激活当前内容指纹")
    activate.add_argument(
        "--database",
        required=True,
        help=f"必须显式指定的目标数据库路径，文件名必须是 {DATABASE_FILENAME}",
    )
    activate.add_argument("--fingerprint", required=True, help="当前内容的完整 SHA-256 指纹")
    activate.add_argument(
        "--backup-directory",
        help="激活前备份目录；默认使用主数据库同级 backups 目录",
    )
    scaffold = subparsers.add_parser(
        "scaffold-extension",
        help="创建不会被正式发现器加载的扩展草稿",
    )
    scaffold.add_argument("--kind", required=True, choices=("world", "content"))
    scaffold.add_argument("--name", required=True, help="小写 ASCII Python 模块名")
    audit = subparsers.add_parser(
        "audit-extension",
        help="在扩展启用前检查结构，启用后验证完整内容装配",
    )
    audit_target = audit.add_mutually_exclusive_group(required=True)
    audit_target.add_argument("--path", help="扩展目录的仓库相对或绝对路径")
    audit_target.add_argument("--all", action="store_true", help="审计全部正式扩展")
    args = parser.parse_args(argv)

    if args.command == "scaffold-extension":
        path = scaffold_extension(args.kind, args.name)
        print(f"已创建扩展草稿：{path.relative_to(ROOT)}")
        print(f"完成实现和测试后，将目录 {path.name} 改名为 {args.name} 即可启用自动发现")
        return 0

    if args.command == "audit-extension":
        report = audit_all_extensions() if args.all else audit_extension(args.path)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["valid"] else 2

    database_path = _resolve_database_path(args.database)
    if args.command == "content-activate" and database_path.name != DATABASE_FILENAME:
        parser.error(f"content-activate 的 --database 必须指向 {DATABASE_FILENAME}")
    print(f"目标数据库：{database_path}", file=sys.stderr)
    database = SqliteDatabase(
        database_path,
        busy_timeout_ms=config.database.busy_timeout_ms,
    )
    database.initialize()
    report = assemble_official_catalog().report
    store = ContentActivationStore(database)

    if args.command == "content-status":
        return _status(database, store, report)
    return _activate(
        database,
        store,
        report,
        args.fingerprint,
        backup_directory=args.backup_directory,
    )


def _resolve_database_path(value: str | Path | None) -> Path:
    path = config.database.path if value is None else Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


_MODULE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def scaffold_extension(kind: str, name: str, *, root: Path = ROOT) -> Path:
    normalized = str(name or "").strip()
    if not _MODULE_NAME_PATTERN.fullmatch(normalized) or keyword.iskeyword(normalized):
        raise ValueError("扩展名必须是非关键字、以小写字母开头的 ASCII Python 模块名")
    roots = {
        "world": root / "game" / "content" / "extensions" / "official",
        "content": root / "game" / "content" / "extensions" / "official_content",
    }
    try:
        extension_root = roots[kind]
    except KeyError as error:
        raise ValueError(f"未知扩展类型：{kind}") from error
    draft = extension_root / f"_{normalized}"
    active = extension_root / normalized
    if draft.exists() or active.exists():
        raise FileExistsError(f"扩展目录已经存在：{draft if draft.exists() else active}")
    draft.mkdir(parents=False)
    (draft / "__init__.py").write_text(
        '"""尚未启用的扩展草稿。"""\n',
        encoding="utf-8",
    )
    export_name = "WORLD_EXTENSION" if kind == "world" else "CONTENT_EXTENSION"
    type_name = "WorldExtension" if kind == "world" else "ContentExtension"
    extension_source = f'''"""{normalized} 扩展草稿；完成后移除目录名前导下划线以启用。"""

from game.content.extensions.models import {type_name}


def _build_extension() -> {type_name}:
    raise NotImplementedError("请完成 {normalized} 的 {type_name} 定义后再启用扩展")


{export_name} = _build_extension()


__all__ = ["{export_name}"]
'''
    (draft / "extension.py").write_text(extension_source, encoding="utf-8")
    templates = _scaffold_templates(kind, normalized)
    for filename, source in templates.items():
        (draft / filename).write_text(source, encoding="utf-8")
    return draft


_WORLD_EXTENSION_FILES = (
    "extension.py",
    "world.py",
    "companions.py",
    "enemies.py",
    "disasters.py",
    "lore.py",
    "skin.py",
)
_CONTENT_EXTENSION_FILES = (
    "extension.py",
    "content.py",
    "presentation.py",
)


def _scaffold_templates(kind: str, name: str) -> dict[str, str]:
    if kind == "world":
        modules = {
            "world.py": "世界、空间、布局、坐标与地点绑定",
            "companions.py": "宠物、人物伙伴与世界秘境",
            "enemies.py": "世界行为倾向与专属组队首领",
            "disasters.py": "该世界可贡献的跨界灾厄身份",
            "lore.py": "世界设定、行纪阶段与可见文本",
            "skin.py": "世界皮肤与完整展示投影",
        }
    else:
        modules = {
            "content.py": "内容蓝图、机制定义与内容包",
            "presentation.py": "各已安装世界的名称、描述与图标投影",
        }
    return {
        filename: (
            f'"""{name} 扩展：{description}。"""\n\n'
            '# 草稿目录不会被正式发现器加载。\n'
        )
        for filename, description in modules.items()
    }


def audit_extension(path: str | Path, *, root: Path = ROOT) -> dict[str, object]:
    candidate = Path(path)
    resolved = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    roots = {
        "world": (root / "game" / "content" / "extensions" / "official").resolve(),
        "content": (root / "game" / "content" / "extensions" / "official_content").resolve(),
    }
    kind = next((key for key, value in roots.items() if resolved.parent == value), None)
    if kind is None:
        raise ValueError("扩展目录必须直接位于 official 或 official_content 下")
    if not resolved.is_dir():
        raise FileNotFoundError(f"扩展目录不存在：{resolved}")
    expected = _WORLD_EXTENSION_FILES if kind == "world" else _CONTENT_EXTENSION_FILES
    missing = [filename for filename in expected if not (resolved / filename).is_file()]
    syntax_errors = []
    for source_path in sorted(resolved.glob("*.py")):
        try:
            ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        except (SyntaxError, UnicodeError) as error:
            syntax_errors.append(f"{source_path.name}: {error}")
    export_name = "WORLD_EXTENSION" if kind == "world" else "CONTENT_EXTENSION"
    extension_path = resolved / "extension.py"
    export_declared = False
    if extension_path.is_file() and not syntax_errors:
        tree = ast.parse(extension_path.read_text(encoding="utf-8"), filename=str(extension_path))
        export_declared = any(
            isinstance(node, (ast.Assign, ast.AnnAssign))
            and any(
                isinstance(target, ast.Name) and target.id == export_name
                for target in (
                    node.targets if isinstance(node, ast.Assign) else (node.target,)
                )
            )
            for node in tree.body
        )
    draft = resolved.name.startswith("_")
    assembly_fingerprint = None
    runtime_error = None
    if not draft and not missing and not syntax_errors and export_declared:
        try:
            assembly_fingerprint = assemble_official_catalog().report.content_fingerprint
        except Exception as error:  # noqa: BLE001 - 审计需要返回完整启用失败原因。
            runtime_error = f"{type(error).__name__}: {error}"
    valid = not missing and not syntax_errors and export_declared and runtime_error is None
    return {
        "path": resolved.relative_to(root.resolve()).as_posix(),
        "kind": kind,
        "draft": draft,
        "valid": valid,
        "required_files": expected,
        "missing_files": missing,
        "syntax_errors": syntax_errors,
        "required_export": export_name,
        "export_declared": export_declared,
        "assembly_fingerprint": assembly_fingerprint,
        "runtime_error": runtime_error,
    }


def audit_all_extensions(*, root: Path = ROOT) -> dict[str, object]:
    """审计全部世界与通用内容扩展，返回可供 CI 判定的汇总。"""

    extension_roots = (
        root / "game" / "content" / "extensions" / "official",
        root / "game" / "content" / "extensions" / "official_content",
    )
    candidates = [
        path
        for extension_root in extension_roots
        if extension_root.is_dir()
        for path in sorted(extension_root.iterdir(), key=lambda value: value.name)
        if path.is_dir() and path.name != "__pycache__"
    ]
    reports = [audit_extension(path, root=root) for path in candidates]
    return {
        "valid": bool(reports) and all(bool(report["valid"]) for report in reports),
        "count": len(reports),
        "extensions": reports,
    }


def _status(
    database: SqliteDatabase,
    store: ContentActivationStore,
    report,
    *,
    logical_time: datetime | None = None,
) -> int:
    try:
        activation = store.require()
    except ContentActivationMismatch:
        activation = None
    current_packages = _package_pairs(report)
    matches = activation is not None and _activation_matches(
        activation,
        report,
        current_packages=current_packages,
    )
    blockers: tuple[dict[str, str], ...] = ()
    audit_error = None
    if activation is not None and not matches:
        try:
            blockers = _content_transition_blockers(
                database,
                logical_time=(
                    logical_time
                    or datetime.now(ZoneInfo(config.project.timezone))
                ),
            )
        except Exception as exc:  # noqa: BLE001 - 状态命令必须报告预检失败原因。
            audit_error = f"{type(exc).__name__}: {exc}"
    payload = {
        "database_path": str(database.path),
        "database_fingerprint": activation.fingerprint if activation else None,
        "current_fingerprint": report.content_fingerprint,
        "revision": activation.revision if activation else None,
        "matches": matches,
        "database_profile": activation.profile_id if activation else None,
        "current_profile": report.active_combat_profile_id,
        "database_packages": activation.packages if activation else (),
        "current_packages": current_packages,
        "package_versions_changed": (
            activation is None or activation.packages != current_packages
        ),
        "transition_blockers": blockers,
        "transition_audit_error": audit_error,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _activate(
    database: SqliteDatabase,
    store: ContentActivationStore,
    report,
    fingerprint: str,
    *,
    backup_directory: Path | str | None = None,
    logical_time: datetime | None = None,
) -> int:
    if fingerprint.strip() != report.content_fingerprint:
        print("拒绝激活：传入指纹不是当前运行内容指纹", file=sys.stderr)
        return 2
    activation_time = logical_time or datetime.now(ZoneInfo(config.project.timezone))
    try:
        activation = store.require()
    except ContentActivationMismatch:
        backup_path = _backup_before_activation(
            database,
            backup_directory=backup_directory,
            logical_time=activation_time,
        )
        activation = store.verify_or_initialize(report, logical_time=activation_time)
        print(f"激活前备份：{backup_path}")
        print(f"已初始化内容激活：revision={activation.revision}")
        return 0
    current_packages = _package_pairs(report)
    if _activation_matches(
        activation,
        report,
        current_packages=current_packages,
    ):
        print(f"内容已经激活：revision={activation.revision}")
        return 0
    if activation.packages == current_packages:
        print(
            "拒绝激活：内容或战斗配置已经变化，但内容包版本没有提升",
            file=sys.stderr,
        )
        return 2
    try:
        blockers = _content_transition_blockers(
            database,
            logical_time=activation_time,
        )
    except Exception as exc:  # noqa: BLE001 - 无法证明安全时必须拒绝内容切换。
        print(
            f"拒绝激活：内容切换预检失败：{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2
    if blockers:
        print("拒绝激活：仍有依赖当前内容的活动会话", file=sys.stderr)
        for blocker in blockers:
            print(json.dumps(blocker, ensure_ascii=False), file=sys.stderr)
        return 2
    backup_path = _backup_before_activation(
        database,
        backup_directory=backup_directory,
        logical_time=activation_time,
    )
    updated = store.replace(
        report,
        expected_revision=activation.revision,
        expected_fingerprint=activation.fingerprint,
        logical_time=activation_time,
    )
    print(f"激活前备份：{backup_path}")
    print(f"已激活内容：revision={updated.revision}")
    return 0


def _package_pairs(report) -> tuple[tuple[str, str], ...]:
    return tuple((package.id, str(package.version)) for package in report.packages)


def _activation_matches(
    activation,
    report,
    *,
    current_packages: tuple[tuple[str, str], ...],
) -> bool:
    return (
        activation.fingerprint == report.content_fingerprint
        and activation.profile_id == report.active_combat_profile_id
        and activation.packages == current_packages
    )


def _content_transition_blockers(
    database: SqliteDatabase,
    *,
    logical_time: datetime,
) -> tuple[dict[str, str], ...]:
    if logical_time.tzinfo is None or logical_time.utcoffset() is None:
        raise ValueError("内容切换预检时间必须包含时区")
    snapshots = SnapshotRepository(
        gameplay_snapshot_codec(feature_snapshot_codec_registrations())
    )
    blockers: list[dict[str, str]] = []
    with database.unit_of_work(write=False) as uow:
        sanctuaries = tuple(
            snapshots.iter_all(
                uow,
                COMPANION_SANCTUARY_AGGREGATE,
                CompanionSanctuaryState,
            )
        )
        disasters = tuple(
            snapshots.iter_all(
                uow,
                DIMENSIONAL_DISASTER_AGGREGATE,
                DimensionalDisasterState,
            )
        )
    for sanctuary in sanctuaries:
        if sanctuary.active and sanctuary.expires_at > logical_time:
            blockers.append(
                {
                    "kind": "companion_sanctuary",
                    "id": sanctuary.character_id,
                    "detail": sanctuary.session_id,
                }
            )
    for disaster in disasters:
        if disaster.status is not DimensionalDisasterStatus.CLOSED:
            blockers.append(
                {
                    "kind": "dimensional_disaster",
                    "id": disaster.event_id,
                    "detail": disaster.status.value,
                }
            )
    return tuple(
        sorted(
            blockers,
            key=lambda value: (value["kind"], value["id"], value["detail"]),
        )
    )


def _backup_before_activation(
    database: SqliteDatabase,
    *,
    backup_directory: Path | str | None,
    logical_time: datetime,
) -> Path:
    return backup_wanxiang_xingji_database(
        backup_directory=backup_directory,
        logical_time=logical_time,
        database=database,
    )


if __name__ == "__main__":
    raise SystemExit(main())
