"""wanxiang_xingji 数据库定时备份二级组件测试。"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from game.app import (  # noqa: E402
    build_game_services,
    install_game_services,
    restore_game_services,
)
from game.cmd.数据库备份.jobs import (  # noqa: E402
    BACKUP_INTERVAL_HOURS,
    backup_database_job,
    schedule_backup_from_last_success,
)
from game.cmd.数据库备份.service import (  # noqa: E402
    BACKUP_RETENTION_COUNT,
    backup_wanxiang_xingji_database,
    list_database_backups,
)
from launch import Scheduler  # noqa: E402


def main() -> None:
    _assert_scheduler_registration()
    _assert_online_backup_and_retention()
    print("database backup tests passed")


def _assert_scheduler_registration() -> None:
    jobs = [
        task
        for task in Scheduler.sync_list
        if task["kwargs"].get("id") == "wanxiang_xingji_database_backup"
    ]
    assert len(jobs) == 1
    assert jobs[0]["args"] == ("interval",)
    assert jobs[0]["kwargs"] == {
        "hours": BACKUP_INTERVAL_HOURS,
        "id": "wanxiang_xingji_database_backup",
        "max_instances": 1,
        "coalesce": True,
    }
    assert BACKUP_INTERVAL_HOURS == 8
    assert BACKUP_RETENTION_COUNT == 3


def _assert_online_backup_and_retention() -> None:
    timezone = ZoneInfo("Asia/Shanghai")
    first_time = datetime(2026, 7, 25, tzinfo=timezone)
    with TemporaryDirectory() as directory:
        root = Path(directory)
        source_path = root / "wanxiang_xingji.db"
        backup_directory = root / "backups"
        services = build_game_services(
            database_path=source_path,
            identity_secret="database-backup-test-secret",
        )
        previous_services = install_game_services(services)
        live_connection = sqlite3.connect(source_path)
        try:
            assert live_connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
            live_connection.execute("PRAGMA wal_autocheckpoint = 0")
            live_connection.execute(
                "CREATE TABLE player_state(player_id TEXT PRIMARY KEY, revision INTEGER NOT NULL)"
            )
            live_connection.execute(
                "INSERT INTO player_state(player_id, revision) VALUES ('player-1', 0)"
            )
            live_connection.commit()

            unrelated = backup_directory / "message_console_2026-07-25_00-00-00.db"
            backup_directory.mkdir(parents=True)
            unrelated.write_text("not managed by this plugin", encoding="utf-8")

            created_paths = []
            for revision in range(4):
                live_connection.execute(
                    "UPDATE player_state SET revision = ? WHERE player_id = 'player-1'",
                    (revision,),
                )
                live_connection.commit()
                backup_path = backup_wanxiang_xingji_database(
                    backup_directory=backup_directory,
                    logical_time=first_time + timedelta(hours=8 * revision),
                )
                created_paths.append(backup_path)
                with closing(sqlite3.connect(backup_path)) as restored:
                    assert restored.execute(
                        "SELECT revision FROM player_state WHERE player_id = 'player-1'"
                    ).fetchone()[0] == revision
                    assert restored.execute("PRAGMA quick_check").fetchone()[0] == "ok"

            retained = list_database_backups(backup_directory)
            assert retained == tuple(reversed(created_paths[1:]))
            assert not created_paths[0].exists()
            assert unrelated.exists()
            assert not tuple(backup_directory.glob("*.tmp"))
            assert not tuple(backup_directory.glob("*.db-wal"))
            assert not tuple(backup_directory.glob("*.db-shm"))

            wrong_database = root / "message_console.db"
            sqlite3.connect(wrong_database).close()
            original_database_path = services.database.path
            services.database.path = wrong_database
            try:
                backup_wanxiang_xingji_database(
                    backup_directory=backup_directory,
                    logical_time=first_time,
                )
                raise AssertionError("备份插件不得处理 message_console.db")
            except ValueError as exc:
                assert "只允许处理 wanxiang_xingji.db" in str(exc)
                with patch(
                    "game.cmd.数据库备份.jobs.backup_wanxiang_xingji_database"
                ) as scheduled_backup:
                    backup_database_job()
                    schedule_backup_from_last_success()
                scheduled_backup.assert_not_called()
            finally:
                services.database.path = original_database_path
        finally:
            live_connection.close()
            restore_game_services(previous_services)


if __name__ == "__main__":
    main()
