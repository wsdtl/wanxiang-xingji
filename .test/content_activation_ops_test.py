"""内容发布工具必须校验版本、先备份再切换，并保持重复执行幂等。"""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import datetime
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OPS_SPEC = spec_from_file_location(
    "wanxiang_xingji_content_ops",
    ROOT / ".ops" / "__main__.py",
)
assert OPS_SPEC is not None and OPS_SPEC.loader is not None
OPS_MODULE = module_from_spec(OPS_SPEC)
OPS_SPEC.loader.exec_module(OPS_MODULE)

from game.content import assemble_official_catalog
from game.core.gameplay.content import ContentVersion
from game.core.persistence import ContentActivationStore, SqliteDatabase


TIME = datetime(2026, 7, 26, 16, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


def main() -> None:
    report = assemble_official_catalog().report
    first_package = report.packages[0]
    old_report = replace(
        report,
        content_fingerprint="a" * 64,
        packages=(
            replace(first_package, version=ContentVersion(3, 28, 0)),
            *report.packages[1:],
        ),
    )
    unchanged_version_report = replace(report, content_fingerprint="b" * 64)

    with TemporaryDirectory() as directory:
        root = Path(directory)
        database = SqliteDatabase(root / "wanxiang_xingji.db")
        database.initialize()
        store = ContentActivationStore(database)
        store.verify_or_initialize(old_report, logical_time=TIME)
        backup_directory = root / "backups"

        stdout = StringIO()
        with redirect_stdout(stdout):
            result = OPS_MODULE._activate(
                database,
                store,
                report,
                report.content_fingerprint,
                backup_directory=backup_directory,
                logical_time=TIME,
            )
        assert result == 0
        assert "激活前备份" in stdout.getvalue()
        assert "revision=1" in stdout.getvalue()
        backups = tuple(backup_directory.glob("wanxiang_xingji_*.db"))
        assert len(backups) == 1

        backup_store = ContentActivationStore(SqliteDatabase(backups[0]))
        backup_activation = backup_store.require()
        assert backup_activation.revision == 0
        assert backup_activation.fingerprint == old_report.content_fingerprint
        activation = store.require()
        assert activation.revision == 1
        assert activation.fingerprint == report.content_fingerprint
        assert activation.packages[0] == ("content.catalog.base", "3.30.0")

        with redirect_stdout(StringIO()):
            repeated = OPS_MODULE._activate(
                database,
                store,
                report,
                report.content_fingerprint,
                backup_directory=backup_directory,
                logical_time=TIME,
            )
        assert repeated == 0
        assert store.require().revision == 1
        assert tuple(backup_directory.glob("wanxiang_xingji_*.db")) == backups

    with TemporaryDirectory() as directory:
        root = Path(directory)
        database = SqliteDatabase(root / "wanxiang_xingji.db")
        database.initialize()
        store = ContentActivationStore(database)
        store.verify_or_initialize(report, logical_time=TIME)
        stderr = StringIO()
        with redirect_stderr(stderr):
            refused = OPS_MODULE._activate(
                database,
                store,
                unchanged_version_report,
                unchanged_version_report.content_fingerprint,
                backup_directory=root / "backups",
                logical_time=TIME,
            )
        assert refused == 2
        assert "包版本没有提升" in stderr.getvalue()
        assert store.require().revision == 0
        assert not (root / "backups").exists()

    print("content activation ops tests passed")


if __name__ == "__main__":
    main()
