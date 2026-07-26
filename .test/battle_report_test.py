"""统一战报压缩、世界语义冻结、公开展示和保留期测试。"""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PREVIEW_ROOT = ROOT / "design" / "previews"
if str(PREVIEW_ROOT) not in sys.path:
    sys.path.insert(0, str(PREVIEW_ROOT))

from game.app import build_game_services, install_game_services, restore_game_services  # noqa: E402
from game.cmd import router as game_router  # noqa: E402
from game.content import (  # noqa: E402
    MAGIC_WORLD_ID,
    RARE_QUALITY_ID,
    STELLAR_RING_WORLD_ID,
    TAIXUAN_WORLD_ID,
)
from game.content.catalog.combat.stats import SHIELD_CURRENT  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    ExecutionPhase,
    EnemyInstance,
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    RuleEvent,
    SPIRIT_CURRENT,
    SPIRIT_MAXIMUM,
)
from game.core.persistence import SqliteDatabase  # noqa: E402
from game.features.battle_report import (  # noqa: E402
    BATTLE_EVENT_PRESENTATIONS,
    PUBLIC_BATTLE_REPORT_SCHEMA,
    PUBLIC_BATTLE_REPORT_VERSION,
    present_battle_event,
)
from game.rules.battle_report import (  # noqa: E402
    KNOWN_BATTLE_EVENT_KINDS,
    BattleReportCombatantDraft,
    BattleReportDraft,
    BattleReportEffectDraft,
    BattleReportFrameDraft,
    BattleReportGear,
    BattleReportParticipantDraft,
    BattleReportSegmentDraft,
    BattleReportSummary,
    BattleReportTerm,
    BattleReportTransitionDraft,
    StoredBattleCombatant,
    StoredBattleEvent,
)
from game.rules.companion import (  # noqa: E402
    COMPANION_APTITUDE_IDS,
    CompanionTrace,
)
from generate_battle_report_preview import build_preview_document  # noqa: E402


NOW = datetime.now(timezone.utc).replace(microsecond=0)


def main() -> None:
    _assert_all_current_events_are_rendered()
    _assert_production_preview()
    with TemporaryDirectory() as directory:
        database = SqliteDatabase(Path(directory) / "battle-report.db")
        database.initialize()
        services = build_game_services(
            database_path=database.path,
            identity_secret="battle-report-test-secret",
        )
        service = services.battle_reports
        first = _draft("segment-1", "第一战", NOW)
        prepared = service.prepare_capture(first)
        assert prepared.detail_payload
        assert prepared.uncompressed_bytes > len(prepared.detail_payload)
        with database.unit_of_work() as uow:
            reference = service.capture_prepared_in_uow(uow, prepared)
            uow.commit()
        with database.unit_of_work() as uow:
            assert service.capture_prepared_in_uow(uow, prepared) == reference
            uow.commit()
        assert service.capture(first) == reference

        rolled_back = replace(
            _draft("segment-rollback", "未提交战斗", NOW),
            report_id="battle-report:rollback",
        )
        with database.unit_of_work() as uow:
            service.capture_prepared_in_uow(uow, service.prepare_capture(rolled_back))
        assert service.reference(rolled_back.report_id) is None

        second = replace(
            _draft("segment-2", "第二战", NOW + timedelta(minutes=10)),
            summary=BattleReportSummary(
                "探险战报",
                "2胜 0负",
                ("完成批次: 2",),
                "victory",
            ),
        )
        assert service.capture(second) == reference

        full = service.load_public(
            reference.share_id,
            logical_time=NOW + timedelta(hours=1),
        )
        assert full is not None and full.detail_available
        assert [item.segment_id for item in full.segments] == ["segment-1", "segment-2"]
        assert full.summary.outcome == "2胜 0负"
        segment = full.segments[0]
        assert segment.combatants[0].key == "p0"
        assert segment.combatants[1].projection_kind == "companion_origin_world"
        assert segment.combatants[1].projection_id == MAGIC_WORLD_ID
        assert segment.combatants[2].projection_id == STELLAR_RING_WORLD_ID
        assert segment.initial_participants[0].abilities == ("ability.test",)
        assert [value.stacks for value in segment.initial_participants[0].effects] == [2, 1]
        assert segment.final_participants[0].resources[str(HEALTH_CURRENT)] == 750
        assert segment.combatants[0].gear[0].name == "铭刻·断潮"
        assert len(segment.transitions) == 2
        assert segment.transitions[0].before is None
        assert segment.transitions[0].after.status == "running"
        turn = segment.transitions[1]
        assert turn.actor_key == "p0"
        assert turn.ability_id == "ability.test"
        assert turn.decision_rule_id == "ai.test.rule"
        assert turn.requested_selector_id == "target.enemy"
        assert turn.requested_target_keys == ("p2",)
        assert turn.resolved_target_keys == ("p2",)
        assert turn.before is not None and turn.before.revision == 1
        assert turn.after.status == "finished"
        assert turn.after.inactive_keys == ("p2",)

        _assert_companion_origin_projection(services)
        _assert_enemy_term_projection(services)
        previous = install_game_services(services)
        try:
            real_load_public = services.battle_reports.load_public

            def load_public_at_test_time(share_id, *, logical_time):
                return real_load_public(
                    share_id,
                    logical_time=NOW + timedelta(hours=1),
                )

            services.battle_reports.load_public = load_public_at_test_time
            app = FastAPI()
            app.include_router(game_router)
            app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
            with TestClient(app) as client:
                _assert_web_assets(client, reference.share_id)
        finally:
            services.battle_reports.load_public = real_load_public
            restore_game_services(previous)

        connection = sqlite3.connect(database.path)
        row = connection.execute(
            "SELECT uncompressed_bytes, compressed_bytes FROM battle_report"
        ).fetchone()
        count = connection.execute(
            "SELECT COUNT(*) FROM battle_report_segment"
        ).fetchone()[0]
        connection.close()
        assert count == 2
        assert row[0] > 0 and row[1] > 0 and row[1] < row[0]

        summary = service.load_public(
            reference.share_id,
            logical_time=NOW + timedelta(hours=4),
        )
        assert summary is not None and not summary.detail_available
        assert summary.segments == ()
        removed_details, removed_reports = service.cleanup(
            logical_time=NOW + timedelta(hours=4)
        )
        assert removed_details == 2 and removed_reports == 0
        assert service.cleanup(logical_time=NOW + timedelta(hours=4)) == (0, 0)

        assert service.load_public(
            reference.share_id,
            logical_time=NOW + timedelta(hours=13),
        ) is None
        assert service.cleanup(logical_time=NOW + timedelta(hours=13)) == (0, 1)

    print("battle report tests passed")


def _assert_companion_origin_projection(services) -> None:
    species = next(
        value
        for value in services.content.companions.species
        if str(value.origin_world_id) == MAGIC_WORLD_ID
    )
    trace = CompanionTrace(
        index=1,
        definition_id=species.id,
        quality_id=RARE_QUALITY_ID,
        level=10,
        aptitudes={value: 100 for value in COMPANION_APTITUDE_IDS},
        trait_behavior_id=species.trait_behavior_ids[0],
        battle_seed="battle-report-companion-origin",
    )
    spec = services.battle_reports.builder.companion(
        trace,
        team_id="player",
        team_label="跨界队伍",
        entity_id="companion-origin-test",
    )
    magic = services.world_views.require(MAGIC_WORLD_ID).projector
    assert spec.label == species.name
    assert spec.projection_kind == "companion_origin_world"
    assert spec.projection_id == MAGIC_WORLD_ID
    assert spec.resolve_term(str(HEALTH_CURRENT)).compact_name == "生命"
    assert spec.resolve_term(str(SPIRIT_CURRENT)).compact_name == "魔力"
    assert spec.resolve_term(str(species.core_behavior_id)).name == magic.name(
        species.core_behavior_id
    )
    assert spec.resolve_term(str(species.trait_behavior_ids[0])).name == magic.name(
        species.trait_behavior_ids[0]
    )


def _assert_enemy_term_projection(services) -> None:
    behavior_id = "enemy.behavior.heavy_strike"
    enemy = EnemyInstance(
        "battle-report-enemy-term-test",
        "enemy.mountain_ape",
        1,
        "enemy.rank.normal",
        (behavior_id,),
        "battle-report-enemy-term-test",
        services.content.catalog.report.content_fingerprint,
    )
    view = services.world_views.require(TAIXUAN_WORLD_ID)
    label = view.enemy_projector.enemy(enemy).name
    spec = services.battle_reports.builder.enemy(
        enemy,
        TAIXUAN_WORLD_ID,
        label,
        team_id="enemy",
        team_label="遭遇一方",
    )
    assert spec.resolve_term("enemy.source_0").name == f"{label}·固有能力"
    assert spec.resolve_term("enemy.source_2").name == view.projector.name(
        behavior_id
    )


def _assert_web_assets(client: TestClient, share_id: str) -> None:
    response = client.get(f"/battle/{share_id}")
    assert response.status_code == 200
    assert "/static/battle-report/style.css?v=18" in response.text
    assert "/static/battle-report/app.js?v=18" in response.text
    assert 'script type="module"' in response.text

    script = client.get("/static/battle-report/app.js").text
    timeline_script = client.get("/static/battle-report/timeline.js").text
    ui_script = client.get("/static/battle-report/ui.js").text
    combined_script = script + timeline_script + ui_script
    assert "state.report.ui.modes.map" in script
    assert "state.report.ui.snapshots.map" in script
    assert "ui.filters.map" in timeline_script
    assert 'action === "mode"' in script
    assert 'action === "segment"' in script
    assert 'action === "snapshot"' in script
    assert 'action === "participant-disclosure"' in script
    assert 'action === "filter"' in script
    assert "event.text" in timeline_script
    assert "event.category" in timeline_script
    assert "buildActorVisualMap(segment.combatants)" in timeline_script
    assert 'event.category === "system"' in timeline_script
    assert "event.source?.key" in timeline_script
    assert "actorVisuals.get(sourceKey)?.color" in timeline_script
    assert "combatant.team_id" not in timeline_script
    assert "buildActorVisualMap(segment.combatants)" in script
    assert "actorVisuals.get(participant.key)" in script
    assert "participant-index actor-${actorColor}" in script
    assert "event.kind" not in combined_script
    assert "const MODE_OPTIONS" not in combined_script
    assert ".at(" not in combined_script
    for forbidden in ("血气", "灵力", "生命", "魔力", "同步", "护盾", "伤害", "攻击", "防御"):
        assert forbidden not in combined_script
    assert 'export function renderRawDataAccess' in timeline_script
    assert 'details.addEventListener("toggle"' in timeline_script
    assert 'export function node' in ui_script
    assert "function updateSegmentView()" in script
    assert "function updateSnapshotView()" in script
    assert "function updateParticipantDisclosure()" in script
    assert "function updateFilterView()" in script
    assert "function selectSegment(index)" in script
    assert "const many = segments.length > 6" in script
    assert 'select.dataset.action = "segment-select"' in script
    assert "document.startViewTransition" not in combined_script
    assert script.count("renderReport();") == 1

    style = client.get("/static/battle-report/style.css").text
    assert "prefers-reduced-motion" in style
    assert "scrollbar-width: none" in style
    assert ".participant-stack {" in style
    assert ".timeline-panel {" in style
    assert "--actor-color" in style
    assert "--event-type-color" not in style
    assert ".actor-system" in style
    assert ".actor-0" in style
    assert ".actor-15" in style
    assert ".event-marker.actor-party-" not in style
    assert ".event-marker.actor-enemy-" not in style
    assert ".event-marker.tone-" not in style
    assert "border: 2px solid var(--event-type-color)" not in style
    assert "view-transition" not in style

    data_response = client.get(f"/battle/{share_id}/data")
    assert data_response.status_code == 200
    payload = data_response.json()
    assert payload["schema"] == PUBLIC_BATTLE_REPORT_SCHEMA
    assert payload["version"] == PUBLIC_BATTLE_REPORT_VERSION
    assert payload["summary"]["title"] == "探险战报"
    segment = payload["detail"]["segments"][0]
    assert segment["title"] == "第一战"
    participants = {
        value["label"]: value for value in segment["initial_participants"]
    }
    assert participants["问道客"]["gauges"][0]["label"] == "气血"
    assert participants["问道客"]["gauges"][1]["label"] == "灵力"
    assert participants["星辉狮鹫"]["gauges"][0]["label"] == "生命"
    assert participants["星辉狮鹫"]["gauges"][1]["label"] == "魔力"
    assert participants["边界守卫"]["gauges"][0]["label"] == "生命"
    assert participants["边界守卫"]["gauges"][1]["label"] == "同步"
    companion = next(
        value
        for value in segment["combatants"]
        if value["unit_kind"] == "companion"
    )
    assert companion["projection"] == {
        "kind": "companion_origin_world",
        "id": MAGIC_WORLD_ID,
        "version": companion["projection"]["version"],
    }
    turn = segment["timeline"][1]
    transfer = next(
        value for value in turn["events"] if value["kind"] == "resource.transferred"
    )
    assert "同步" in transfer["text"] and "灵力" in transfer["text"]
    health_change = next(
        value for value in turn["events"] if value["kind"] == "resource.changed"
    )
    assert "消耗 100 点生命" in health_change["text"]
    assert turn["comparison"]["before"]["title"] == "动作前完整状态"
    assert turn["comparison"]["after"]["title"] == "动作后完整状态"
    assert any(
        fact["label"] == "实际目标" and fact["value"] == ["边界守卫"]
        for fact in turn["facts"]
    )
    assert "character-private-id" not in data_response.text
    assert "companion-private-id" not in data_response.text
    assert "enemy-private-id" not in data_response.text
    assert client.get("/battle/not-found").status_code == 404
    assert client.get("/battle/not-found/data").status_code == 404


def _assert_production_preview() -> None:
    preview_path = PREVIEW_ROOT / "battle-report-production.html"
    assert preview_path.is_file()
    assert not (PREVIEW_ROOT / "battle-report-humanized.html").exists()
    preview = preview_path.read_text(encoding="utf-8")
    assert "<style" not in preview
    assert "maximum-scale=1, user-scalable=no" in preview
    assert "../../static/battle-report/style.css?v=18" in preview
    assert "../../static/battle-report/app.js?v=18" in preview
    assert 'script type="module"' in preview
    opening = '<script id="battleReportPreviewData" type="application/json">'
    payload = preview.split(opening, 1)[1].split("</script>", 1)[0]
    embedded = json.loads(payload)
    generated = build_preview_document()
    generated["share_id"] = embedded["share_id"]
    assert embedded == generated
    assert embedded["schema"] == PUBLIC_BATTLE_REPORT_SCHEMA
    assert embedded["version"] == PUBLIC_BATTLE_REPORT_VERSION
    assert embedded["mode_id"] == "battle.mode.party_battle"
    assert embedded["detail"]["available"] is True
    assert embedded["detail"]["segments"]
    assert all(
        segment["timeline"] for segment in embedded["detail"]["segments"]
    )
    assert {"观潮客", "砺锋客", "司星者"}.issubset(
        {
            participant["label"]
            for participant in embedded["detail"]["segments"][0][
                "initial_participants"
            ]
        }
    )
    initial_participants = embedded["detail"]["segments"][0][
        "initial_participants"
    ]
    for participant in initial_participants:
        if participant["unit_kind"] != "character":
            continue
        permanent_group = next(
            value
            for value in participant["detail_groups"]
            if value["id"] == "permanent_effects"
        )
        assert all(
            effect["source"] == participant["label"]
            for effect in permanent_group["items"]
            if effect["id"].startswith("feature.")
        )
    assert "ability.test" not in payload
    assert "combat.damage.dealt" in payload
    events = [
        event
        for segment in embedded["detail"]["segments"]
        for transition in segment["timeline"]
        for event in transition["events"]
    ]
    phase_events = [
        event for event in events if event["kind"] == "combat.phase.activated"
    ]
    assert phase_events
    assert all(
        "进入新的战斗阶段" in event["text"]
        and "获得" in event["text"]
        and event["raw"]["values"]["behavior_ids"]
        and event["subject"]["id"].startswith("enemy.phase.")
        and event["subject"]["label"].endswith("阶段能力")
        for event in phase_events
    )


def _assert_all_current_events_are_rendered() -> None:
    discovered: set[str] = {"combat.damage.dealt", "combat.damage.prevented"}
    for path in (ROOT / "game").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if (
                isinstance(node.func, ast.Name)
                and node.func.id == "EffectFact"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                _add_battle_event(discovered, node.args[0].value)
            if isinstance(node.func, ast.Attribute) and node.func.attr == "from_context":
                for keyword in node.keywords:
                    if (
                        keyword.arg == "kind"
                        and isinstance(keyword.value, ast.Constant)
                        and isinstance(keyword.value.value, str)
                    ):
                        _add_battle_event(discovered, keyword.value.value)
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "_effect_mutation_event"
                and len(node.args) > 4
                and isinstance(node.args[4], ast.Constant)
                and isinstance(node.args[4].value, str)
            ):
                _add_battle_event(discovered, node.args[4].value)
    assert discovered == KNOWN_BATTLE_EVENT_KINDS
    assert BATTLE_EVENT_PRESENTATIONS.registered_kinds == KNOWN_BATTLE_EVENT_KINDS

    combatants = _event_test_combatants()
    for kind in sorted(KNOWN_BATTLE_EVENT_KINDS):
        event = present_battle_event(
            StoredBattleEvent(
                kind,
                "p0",
                "p1",
                "effect.test",
                NOW,
                {},
            ),
            combatants,
        )
        assert event["text"] and event["tone"], kind

    try:
        present_battle_event(
            StoredBattleEvent(
                "combat.future.time_rewind",
                "p0",
                "p1",
                "effect.future.time_rewind",
                NOW,
                {"restored_health": 300},
            ),
            combatants,
        )
    except RuntimeError as exc:
        assert "没有展示注册" in str(exc)
    else:
        raise AssertionError("未知战斗事件不得由 Web 或通用兜底猜测显示")

    rejected = present_battle_event(
        StoredBattleEvent(
            "effect.application.rejected",
            "p0",
            "p1",
            "effect.test",
            NOW,
            {"reason": "control_resisted", "chance": 0.5, "roll": 0.8},
        ),
        combatants,
    )
    assert rejected["text"] == "乙抵抗了甲施加的测试效果"

    revived = present_battle_event(
        StoredBattleEvent(
            "combat.target.revived",
            "p0",
            "p1",
            str(HEALTH_CURRENT),
            NOW,
            {"before": 0, "after": 30, "actual": 30},
        ),
        combatants,
    )
    assert revived["text"] == "甲使乙重新投入战斗"


def _event_test_combatants() -> dict[str, StoredBattleCombatant]:
    terms = {
        "effect.test": BattleReportTerm("测试效果"),
        str(HEALTH_CURRENT): BattleReportTerm("当前生命", "生命"),
        str(HEALTH_MAXIMUM): BattleReportTerm("生命上限"),
        str(SPIRIT_CURRENT): BattleReportTerm("当前能量", "能量"),
        str(SPIRIT_MAXIMUM): BattleReportTerm("能量上限"),
        str(SHIELD_CURRENT): BattleReportTerm("当前护盾", "护盾"),
        str(COMBAT_DEFENSE): BattleReportTerm("防御"),
    }
    return {
        key: StoredBattleCombatant(
            key,
            label,
            team,
            team_label,
            "character",
            "character_world",
            world,
            1,
            terms,
        )
        for key, label, team, team_label, world in (
            ("p0", "甲", "a", "甲方", TAIXUAN_WORLD_ID),
            ("p1", "乙", "b", "乙方", MAGIC_WORLD_ID),
        )
    }


def _add_battle_event(discovered: set[str], value: str) -> None:
    if value.startswith(("ability.", "combat.", "effect.", "resource.", "trigger.")):
        discovered.add(value)


def _draft(segment_id: str, title: str, logical_time: datetime) -> BattleReportDraft:
    combatants = (
        BattleReportCombatantDraft(
            "character-private-id",
            "问道客",
            "player",
            "行者一方",
            "character",
            "character_world",
            TAIXUAN_WORLD_ID,
            1,
            _taixuan_terms(),
            (BattleReportGear("slot.weapon", "兵器", "铭刻·断潮"),),
        ),
        BattleReportCombatantDraft(
            "companion-private-id",
            "星辉狮鹫",
            "player",
            "行者一方",
            "companion",
            "companion_origin_world",
            MAGIC_WORLD_ID,
            1,
            _magic_terms(),
        ),
        BattleReportCombatantDraft(
            "enemy-private-id",
            "边界守卫",
            "enemy",
            "敌方",
            "enemy",
            "enemy_world",
            STELLAR_RING_WORLD_ID,
            1,
            _stellar_terms(),
        ),
    )
    initial = (
        BattleReportParticipantDraft(
            "character-private-id",
            attributes={
                str(HEALTH_MAXIMUM): 1000,
                str(SPIRIT_MAXIMUM): 100,
                str(COMBAT_ATTACK): 100,
                str(COMBAT_DEFENSE): 50,
            },
            resources={str(HEALTH_CURRENT): 1000, str(SPIRIT_CURRENT): 100},
            abilities=("ability.test",),
            effects=(
                BattleReportEffectDraft(
                    "effect-instance-charge",
                    "effect.weapon.shared_charge",
                    "character-private-id",
                    2,
                    3,
                    "positive",
                ),
                BattleReportEffectDraft(
                    "effect-instance-mark",
                    "effect.weapon.shared_mark",
                    "character-private-id",
                    1,
                    None,
                    "neutral",
                ),
            ),
            cooldowns={"ability.test": 2},
            triggers=("trigger.test",),
        ),
        BattleReportParticipantDraft(
            "companion-private-id",
            attributes={str(HEALTH_MAXIMUM): 700, str(SPIRIT_MAXIMUM): 140},
            resources={str(HEALTH_CURRENT): 700, str(SPIRIT_CURRENT): 140},
            abilities=("ability.basic_attack",),
        ),
        BattleReportParticipantDraft(
            "enemy-private-id",
            attributes={str(HEALTH_MAXIMUM): 1000, str(SPIRIT_MAXIMUM): 200},
            resources={str(HEALTH_CURRENT): 1000, str(SPIRIT_CURRENT): 200},
            abilities=("ability.basic_attack",),
        ),
    )
    final = (
        replace(
            initial[0],
            resources={str(HEALTH_CURRENT): 750, str(SPIRIT_CURRENT): 120},
            effects=(),
            cooldowns={},
        ),
        initial[1],
        replace(
            initial[2],
            resources={str(HEALTH_CURRENT): 0, str(SPIRIT_CURRENT): 160},
        ),
    )
    start_events = (
        _event(
            "combat.battle.started",
            "battle-private-id",
            "character-private-id",
            "battle.start",
            logical_time,
            {"round": 1},
        ),
        _event(
            "combat.round.started",
            "battle-private-id",
            "character-private-id",
            "combat.round",
            logical_time,
            {"round": 1},
        ),
    )
    turn_events = (
        _event(
            "combat.turn.started",
            "character-private-id",
            "character-private-id",
            "combat.turn",
            logical_time,
            {"round": 1, "turn": 1},
        ),
        _event(
            "resource.transferred",
            "character-private-id",
            "enemy-private-id",
            str(SPIRIT_CURRENT),
            logical_time,
            {"drained": 20, "received": 20, "overflow": 0, "efficiency": 1},
        ),
        *(
            _event(
                "resource.changed",
                "character-private-id",
                "enemy-private-id",
                str(HEALTH_CURRENT),
                logical_time,
                {"delta": -100 - index, "current": 900 - index},
            )
            for index in range(40)
        ),
    )
    before = _frame(logical_time, 0, 1, "running", initial)
    after = _frame(logical_time, 1, 2, "finished", final)
    return BattleReportDraft(
        report_id="battle-report:exploration:session-private-id",
        mode_id="battle.mode.exploration",
        content_fingerprint="content-fingerprint",
        summary=BattleReportSummary(
            "探险战报",
            "1胜 0负",
            ("完成批次: 1",),
            "victory",
        ),
        segment=BattleReportSegmentDraft(
            segment_id=segment_id,
            title=title,
            combatants=combatants,
            initial_participants=initial,
            final_participants=final,
            transitions=(
                BattleReportTransitionDraft(
                    sequence=0,
                    kind="start",
                    subject_id="battle.transition.start",
                    before=None,
                    after=_frame(logical_time, 0, 0, "running", initial),
                    events=start_events,
                ),
                BattleReportTransitionDraft(
                    sequence=1,
                    kind="turn",
                    subject_id="battle.transition.turn",
                    before=before,
                    after=after,
                    events=turn_events,
                    actor_entity_id="character-private-id",
                    action_id="action:test:1",
                    ability_id="ability.test",
                    decision_rule_id="ai.test.rule",
                    requested_selector_id="target.enemy",
                    requested_target_ids=("enemy-private-id",),
                    resolved_target_ids=("enemy-private-id",),
                    action_parameters={"power": 1.5},
                    action_context_tags=("scene.test",),
                ),
            ),
            source_owners={
                "character-private-id": "character-private-id",
                "companion-private-id": "companion-private-id",
                "enemy-private-id": "enemy-private-id",
            },
            outcome="胜利",
            started_at=logical_time,
            finished_at=logical_time,
        ),
    )


def _frame(logical_time, turn, revision, status, participants):
    return BattleReportFrameDraft(
        logical_time=logical_time,
        round_number=1,
        turn_number=turn,
        status=status,
        revision=revision,
        current_actor_entity_id=(
            None if status == "finished" else "character-private-id"
        ),
        turn_order_entity_ids=(
            "character-private-id",
            "companion-private-id",
            "enemy-private-id",
        ),
        inactive_entity_ids=("enemy-private-id",) if status == "finished" else (),
        winning_team_ids=("player",) if status == "finished" else (),
        action_progress={"character-private-id": 1.0 if status == "finished" else 0.2},
        participants=participants,
    )


def _event(kind, source, target, subject, logical_time, values):
    return RuleEvent(
        kind=kind,
        source_id=source,
        target_id=target,
        subject_id=subject,
        trace_id="private-trace-id",
        rule_version="rule.test.v1",
        ruleset_id="ruleset.standard",
        logical_time=logical_time,
        values=values,
        phase=ExecutionPhase.RESOLVE,
    )


def _taixuan_terms():
    return _terms("当前气血", "气血", "气血上限", "当前灵力", "灵力", "灵力上限", "基础防御")


def _magic_terms():
    return _terms("当前生命", "生命", "生命上限", "当前魔力", "魔力", "魔力上限", "基础护甲")


def _stellar_terms():
    return _terms("当前生命", "生命", "生命上限", "当前同步", "同步", "同步上限", "基础护甲")


def _terms(health_name, health_short, health_max, spirit_name, spirit_short, spirit_max, defense):
    return {
        str(HEALTH_CURRENT): BattleReportTerm(health_name, health_short),
        str(HEALTH_MAXIMUM): BattleReportTerm(health_max),
        str(SPIRIT_CURRENT): BattleReportTerm(spirit_name, spirit_short),
        str(SPIRIT_MAXIMUM): BattleReportTerm(spirit_max),
        str(SHIELD_CURRENT): BattleReportTerm("当前护盾", "护盾"),
        str(COMBAT_ATTACK): BattleReportTerm("攻击力", "攻击"),
        str(COMBAT_DEFENSE): BattleReportTerm(defense, "防御"),
        "ability.test": BattleReportTerm("潮生一式"),
        "ability.basic_attack": BattleReportTerm("普通攻击"),
        "effect.weapon.shared_charge": BattleReportTerm("潮势蓄积"),
        "effect.weapon.shared_mark": BattleReportTerm("潮痕"),
        "trigger.test": BattleReportTerm("回潮"),
        "ai.test.rule": BattleReportTerm("优先攻敌"),
        "target.enemy": BattleReportTerm("敌方目标"),
        "scene.test": BattleReportTerm("边界战场"),
        "combat.turn": BattleReportTerm("行动"),
    }


if __name__ == "__main__":
    main()
