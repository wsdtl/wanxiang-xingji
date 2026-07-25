"""统一战报应用服务与公共展示协议入口。"""

from .assembly import BattleCombatantSpec, BattleReportBuilder
from .presentation import (
    BATTLE_EVENT_PRESENTATIONS,
    PUBLIC_BATTLE_REPORT_SCHEMA,
    PUBLIC_BATTLE_REPORT_VERSION,
    BattleEventPresentationRegistry,
    build_public_battle_report,
    present_battle_event,
    resolve_battle_content_name,
)
from .service import (
    BattleReportService,
    DETAIL_RETENTION,
    PreparedBattleReport,
    SUMMARY_RETENTION,
)

__all__ = [
    "BATTLE_EVENT_PRESENTATIONS",
    "BattleCombatantSpec",
    "BattleEventPresentationRegistry",
    "BattleReportBuilder",
    "BattleReportService",
    "DETAIL_RETENTION",
    "PreparedBattleReport",
    "PUBLIC_BATTLE_REPORT_SCHEMA",
    "PUBLIC_BATTLE_REPORT_VERSION",
    "SUMMARY_RETENTION",
    "build_public_battle_report",
    "present_battle_event",
    "resolve_battle_content_name",
]
