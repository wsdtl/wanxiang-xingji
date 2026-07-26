"""统一战报应用服务与公共展示协议入口。"""

from .assembly import BattleCombatantSpec, BattleReportBuilder
from .presentation import (
    BATTLE_EVENT_PRESENTATIONS,
    PUBLIC_BATTLE_REPORT_SCHEMA,
    PUBLIC_BATTLE_REPORT_VERSION,
    BattleEventPresentationRegistry,
    present_battle_event,
    resolve_battle_content_name,
)
from .public_protocol import (
    PublicBattleReportProjector,
    build_public_battle_events,
    build_public_battle_participants,
    build_public_battle_raw,
    build_public_battle_report,
    build_public_battle_transition,
    validate_public_battle_report,
)
from .service import (
    BattleReportService,
    DETAIL_RETENTION,
    PreparedBattleReport,
    PublicBattleReportSelection,
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
    "PublicBattleReportProjector",
    "PublicBattleReportSelection",
    "PUBLIC_BATTLE_REPORT_SCHEMA",
    "PUBLIC_BATTLE_REPORT_VERSION",
    "SUMMARY_RETENTION",
    "build_public_battle_events",
    "build_public_battle_participants",
    "build_public_battle_raw",
    "build_public_battle_report",
    "build_public_battle_transition",
    "present_battle_event",
    "resolve_battle_content_name",
    "validate_public_battle_report",
]
