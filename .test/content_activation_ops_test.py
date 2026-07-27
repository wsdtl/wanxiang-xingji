"""内容发布工具必须校验版本、先备份再切换，并保持重复执行幂等。"""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
import json
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
from game.core.gameplay import EnemyEncounterInstance, EnemyInstance
from game.core.gameplay.content import ContentVersion
from game.core.persistence import (
    ContentActivationStore,
    SnapshotRepository,
    SqliteDatabase,
    gameplay_snapshot_codec,
)
from game.features.catalog import feature_snapshot_codec_registrations
from game.features.party_battle import (
    PARTY_BATTLE_CHALLENGE_AGGREGATE,
    PartyBattleChallengeState,
)
from game.rules.companion import (
    APTITUDE_AGILITY,
    APTITUDE_FOCUS,
    APTITUDE_OFFENSE,
    APTITUDE_VITALITY,
    COMPANION_SANCTUARY_AGGREGATE,
    CompanionSanctuaryState,
    CompanionTrace,
)
from game.rules.disaster import (
    DIMENSIONAL_DISASTER_AGGREGATE,
    DimensionalDisasterState,
    DisasterCombatSnapshot,
    DisasterNarrativeSnapshot,
)


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
        database_path = Path(directory) / "explicit-target.db"
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status_result = OPS_MODULE.main(
                ["content-status", "--database", str(database_path)]
            )
        status_payload = json.loads(stdout.getvalue())
        assert status_result == 0
        assert Path(status_payload["database_path"]) == database_path.resolve()
        assert str(database_path.resolve()) in stderr.getvalue()
        assert database_path.is_file()

    with redirect_stderr(StringIO()):
        try:
            OPS_MODULE.main(
                ["content-activate", "--fingerprint", report.content_fingerprint]
            )
        except SystemExit as error:
            assert error.code == 2
        else:
            raise AssertionError("内容激活必须显式指定目标数据库")

    with TemporaryDirectory() as directory:
        invalid_database_path = Path(directory) / "wrong-name.db"
        stderr = StringIO()
        with redirect_stderr(stderr):
            try:
                OPS_MODULE.main(
                    [
                        "content-activate",
                        "--database",
                        str(invalid_database_path),
                        "--fingerprint",
                        report.content_fingerprint,
                    ]
                )
            except SystemExit as error:
                assert error.code == 2
            else:
                raise AssertionError("内容激活必须拒绝非规范数据库文件名")
        assert "wanxiang_xingji.db" in stderr.getvalue()
        assert not invalid_database_path.exists()

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
        assert activation.packages[0] == ("content.catalog.base", "3.32.2")

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

    with TemporaryDirectory() as directory:
        root = Path(directory)
        database = SqliteDatabase(root / "wanxiang_xingji.db")
        database.initialize()
        store = ContentActivationStore(database)
        store.verify_or_initialize(old_report, logical_time=TIME)
        _seed_transition_blockers(database, old_report.content_fingerprint)

        blockers = OPS_MODULE._content_transition_blockers(
            database,
            logical_time=TIME,
        )
        assert {value["kind"] for value in blockers} == {
            "companion_sanctuary",
            "dimensional_disaster",
        }
        stderr = StringIO()
        with redirect_stderr(stderr):
            refused = OPS_MODULE._activate(
                database,
                store,
                report,
                report.content_fingerprint,
                backup_directory=root / "backups",
                logical_time=TIME,
            )
        assert refused == 2
        assert "仍有依赖当前内容的活动会话" in stderr.getvalue()
        assert store.require().fingerprint == old_report.content_fingerprint
        assert not (root / "backups").exists()

    print("content activation ops tests passed")


def _seed_transition_blockers(database: SqliteDatabase, content_version: str) -> None:
    snapshots = SnapshotRepository(
        gameplay_snapshot_codec(feature_snapshot_codec_registrations())
    )
    trace = CompanionTrace(
        1,
        "companion.audit",
        "companion.quality.audit",
        1,
        {
            APTITUDE_VITALITY: 100,
            APTITUDE_OFFENSE: 100,
            APTITUDE_AGILITY: 100,
            APTITUDE_FOCUS: 100,
        },
        "enemy.behavior.audit",
        "companion-audit-seed",
    )
    sanctuary = CompanionSanctuaryState(
        "character-audit",
        "sanctuary-audit",
        "sanctuary.audit",
        "world.audit",
        TIME,
        TIME + timedelta(hours=1),
        (trace,),
        content_version,
    )
    enemy = EnemyInstance(
        "enemy-audit",
        "enemy.audit",
        1,
        "enemy.rank.audit",
        (),
        "enemy-audit-seed",
        content_version,
    )
    encounter = EnemyEncounterInstance(
        "encounter-audit",
        "encounter.audit",
        "encounter.scope.audit",
        1,
        (enemy,),
        "encounter-audit-seed",
        content_version,
    )
    challenge = PartyBattleChallengeState(
        "party-audit",
        "party-session-audit",
        "character-audit",
        "world.audit",
        1,
        encounter,
        {"character-audit": 0},
        selected_at=TIME,
    )
    narrative = DisasterNarrativeSnapshot(
        "审计灾厄",
        "审计标题",
        "审计场景",
        "审计故事",
        "审计告别",
        "审计遗羽",
        "审计来源",
    )
    disaster = DimensionalDisasterState(
        "disaster-audit",
        "window-audit",
        "disaster.definition.audit",
        "world.audit",
        narrative,
        DisasterCombatSnapshot(
            "enemy.audit",
            1,
            "enemy.rank.audit",
            (),
            "disaster-audit-seed",
            content_version,
        ),
        TIME,
        TIME + timedelta(days=1),
        100,
        100,
    )
    with database.unit_of_work() as uow:
        snapshots.insert(
            uow,
            COMPANION_SANCTUARY_AGGREGATE,
            sanctuary.character_id,
            sanctuary,
            TIME,
        )
        snapshots.insert(
            uow,
            PARTY_BATTLE_CHALLENGE_AGGREGATE,
            challenge.party_id,
            challenge,
            TIME,
        )
        snapshots.insert(
            uow,
            DIMENSIONAL_DISASTER_AGGREGATE,
            disaster.event_id,
            disaster,
            TIME,
        )
        uow.commit()


if __name__ == "__main__":
    main()
