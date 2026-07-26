"""短期数据生命周期维护触发器。"""

from datetime import datetime
from zoneinfo import ZoneInfo

from game.app import current_game_services
from launch import C, Scheduler, config, logger


@Scheduler._sync(
    "interval",
    minutes=30,
    id="game_data_lifecycle_cleanup",
    max_instances=1,
    coalesce=True,
)
def cleanup_short_lived_data() -> None:
    """运行各领域登记的短期清理器。"""

    logical_time = datetime.now(ZoneInfo(config.project.timezone))
    try:
        results = current_game_services().data_lifecycle.maintain(
            logical_time=logical_time,
        )
    except Exception as exc:
        logger.opt(colors=True, exception=exc).error(C.fail("短期数据清理失败"))
        return
    for result in results:
        if not result.ok:
            logger.opt(colors=True, exception=result.error).error(
                C.fail(f"数据清理任务失败：{result.task_id}")
            )


__all__ = ["cleanup_short_lived_data"]
