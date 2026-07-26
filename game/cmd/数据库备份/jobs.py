"""数据库备份组件的框架调度入口。"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from game.app import current_game_services
from launch import C, OnEvent, Scheduler, config, logger

from .service import (
    BACKUP_DIRECTORY_NAME,
    BACKUP_RETENTION_COUNT,
    DATABASE_FILENAME,
    backup_wanxiang_xingji_database,
    latest_database_backup_time,
)


BACKUP_INTERVAL_HOURS = 8


@Scheduler._sync(
    "interval",
    hours=BACKUP_INTERVAL_HOURS,
    id="wanxiang_xingji_database_backup",
    max_instances=1,
    coalesce=True,
)
def backup_database_job() -> None:
    """按调度周期备份正式主库；失败只记录，不中断其他后台任务。"""

    if current_game_services().database.path.name != DATABASE_FILENAME:
        return
    try:
        backup_path = backup_wanxiang_xingji_database(
            logical_time=datetime.now(ZoneInfo(config.project.timezone))
        )
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(
            C.fail("wanxiang_xingji 数据库备份失败")
        )
        return
    logger.opt(colors=True).success(
        C.join(
            C.ok("wanxiang_xingji 数据库备份完成"),
            C.kv("file", backup_path.name),
            C.kv("retention", BACKUP_RETENTION_COUNT),
        )
    )


@OnEvent.connect(priority=100)
def schedule_backup_from_last_success() -> None:
    """启动时按最后成功时间补跑，避免每次重启重新等待八小时。"""

    timezone = ZoneInfo(config.project.timezone)
    logical_time = datetime.now(timezone)
    source = current_game_services().database.path
    if source.name != DATABASE_FILENAME:
        return
    backup_directory = source.parent / BACKUP_DIRECTORY_NAME
    previous = latest_database_backup_time(
        backup_directory,
        timezone=timezone,
    )
    due_at = (
        previous + timedelta(hours=BACKUP_INTERVAL_HOURS)
        if previous is not None
        else logical_time
    )
    if due_at <= logical_time:
        backup_database_job()
        due_at = logical_time + timedelta(hours=BACKUP_INTERVAL_HOURS)
    Scheduler.syncinstance.reschedule_job(
        "wanxiang_xingji_database_backup",
        trigger="interval",
        hours=BACKUP_INTERVAL_HOURS,
        start_date=due_at,
        timezone=timezone,
    )


__all__ = [
    "BACKUP_INTERVAL_HOURS",
    "backup_database_job",
    "schedule_backup_from_last_success",
]
