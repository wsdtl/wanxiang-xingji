"""数据库备份组件的框架调度入口。"""

from datetime import datetime
from zoneinfo import ZoneInfo

from launch import C, Scheduler, config, logger

from .service import BACKUP_RETENTION_COUNT, backup_wanxiang_xingji_database


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


__all__ = ["BACKUP_INTERVAL_HOURS", "backup_database_job"]
