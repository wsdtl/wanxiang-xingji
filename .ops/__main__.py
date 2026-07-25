"""内容激活状态和显式切换工具。"""

from __future__ import annotations

import argparse
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
from game.core.persistence import ContentActivationMismatch, ContentActivationStore, SqliteDatabase
from launch.config import config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python .ops/__main__.py")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("content-status", help="显示数据库与当前内容的激活状态")
    activate = subparsers.add_parser("content-activate", help="显式激活当前内容指纹")
    activate.add_argument("--fingerprint", required=True, help="当前内容的完整 SHA-256 指纹")
    scaffold = subparsers.add_parser(
        "scaffold-extension",
        help="创建不会被正式发现器加载的扩展草稿",
    )
    scaffold.add_argument("--kind", required=True, choices=("world", "content"))
    scaffold.add_argument("--name", required=True, help="小写 ASCII Python 模块名")
    args = parser.parse_args(argv)

    if args.command == "scaffold-extension":
        path = scaffold_extension(args.kind, args.name)
        print(f"已创建扩展草稿：{path.relative_to(ROOT)}")
        print(f"完成实现和测试后，将目录 {path.name} 改名为 {args.name} 即可启用自动发现")
        return 0

    database = SqliteDatabase(
        config.database.path,
        busy_timeout_ms=config.database.busy_timeout_ms,
    )
    database.initialize()
    report = assemble_official_catalog().report
    store = ContentActivationStore(database)

    if args.command == "content-status":
        return _status(store, report)
    return _activate(store, report, args.fingerprint)


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
    return draft


def _status(store: ContentActivationStore, report) -> int:
    try:
        activation = store.require()
    except ContentActivationMismatch:
        activation = None
    payload = {
        "database_fingerprint": activation.fingerprint if activation else None,
        "current_fingerprint": report.content_fingerprint,
        "revision": activation.revision if activation else None,
        "matches": activation is not None and activation.fingerprint == report.content_fingerprint,
        "packages": activation.packages if activation else (),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _activate(store: ContentActivationStore, report, fingerprint: str) -> int:
    if fingerprint.strip() != report.content_fingerprint:
        print("拒绝激活：传入指纹不是当前运行内容指纹", file=sys.stderr)
        return 2
    logical_time = datetime.now(ZoneInfo(config.project.timezone))
    try:
        activation = store.require()
    except ContentActivationMismatch:
        activation = store.verify_or_initialize(report, logical_time=logical_time)
        print(f"已初始化内容激活：revision={activation.revision}")
        return 0
    if activation.fingerprint == report.content_fingerprint:
        print(f"内容已经激活：revision={activation.revision}")
        return 0
    updated = store.replace(
        report,
        expected_revision=activation.revision,
        expected_fingerprint=activation.fingerprint,
        logical_time=logical_time,
    )
    print(f"已激活内容：revision={updated.revision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
