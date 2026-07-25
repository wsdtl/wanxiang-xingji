"""wanxiang_xingji 主数据库的在线备份与历史轮换。"""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from game.app import current_game_services


DATABASE_ID = "wanxiang_xingji"
DATABASE_FILENAME = f"{DATABASE_ID}.db"
BACKUP_DIRECTORY_NAME = "backups"
BACKUP_FILE_GLOB = f"{DATABASE_ID}_*.db"
BACKUP_RETENTION_COUNT = 3


def backup_wanxiang_xingji_database(
    *,
    backup_directory: Path | str | None = None,
    logical_time: datetime,
) -> Path:
    """生成一份可独立恢复的 SQLite 备份，并只保留最新三份。"""

    services = current_game_services()
    source = Path(services.database.path)
    if source.name != DATABASE_FILENAME:
        raise ValueError(
            f"备份组件只允许处理 {DATABASE_FILENAME}，当前路径是：{source}"
        )
    if not source.is_file():
        raise FileNotFoundError(f"待备份数据库不存在：{source}")

    if logical_time.tzinfo is None or logical_time.utcoffset() is None:
        raise ValueError("数据库备份时间必须包含时区")

    destination = Path(backup_directory or source.parent / BACKUP_DIRECTORY_NAME)
    destination.mkdir(parents=True, exist_ok=True)
    filename = f"{DATABASE_ID}_{logical_time:%Y-%m-%d_%H-%M-%S}.db"
    backup_path = destination / filename
    temporary_path = destination / f".{filename}.{uuid4().hex}.tmp"

    try:
        services.backup_database(temporary_path)
        temporary_path.replace(backup_path)
        _prune_old_backups(destination)
    finally:
        with suppress(OSError):
            temporary_path.unlink(missing_ok=True)
    return backup_path


def list_database_backups(directory: Path | str) -> tuple[Path, ...]:
    """按时间从新到旧列出本组件生成的备份文件。"""

    return tuple(
        sorted(
            (
                path
                for path in Path(directory).glob(BACKUP_FILE_GLOB)
                if path.is_file()
            ),
            key=lambda path: path.name,
            reverse=True,
        )
    )


def _prune_old_backups(directory: Path) -> None:
    for stale_path in list_database_backups(directory)[BACKUP_RETENTION_COUNT:]:
        stale_path.unlink()


__all__ = [
    "BACKUP_RETENTION_COUNT",
    "DATABASE_ID",
    "backup_wanxiang_xingji_database",
    "list_database_backups",
]
