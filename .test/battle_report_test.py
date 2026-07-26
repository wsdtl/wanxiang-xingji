"""统一战报压缩、世界语义冻结、公开展示和保留期测试。"""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
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
    build_official_content,
)
from game.content.catalog.combat.stats import SHIELD_CURRENT  # noqa: E402
from game.content.catalog.weapon.blueprints import WEAPON_BLUEPRINTS  # noqa: E402
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
    validate_public_battle_report,
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
    content_scoped_report_id,
)
from game.rules.companion import (  # noqa: E402
    COMPANION_APTITUDE_IDS,
    CompanionTrace,
)
from generate_battle_report_preview import build_preview_artifacts  # noqa: E402
from launch import FastAPIAllowed  # noqa: E402


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
        assert segment.transitions[0].after.status == "active"
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
        selection = service.load_public_selection(
            reference.share_id,
            logical_time=NOW + timedelta(hours=1),
            segment_index=1,
        )
        assert selection is not None
        assert selection.segment_count == 2
        assert selection.segment_index == 1
        assert [value.segment_id for value in selection.report.segments] == ["segment-2"]
        assert service.load_public_selection(
            reference.share_id,
            logical_time=NOW + timedelta(hours=1),
            segment_index=2,
        ) is None
        assert service.public_exists(
            reference.share_id,
            logical_time=NOW + timedelta(hours=1),
        )

        _assert_companion_origin_projection(services)
        _assert_enemy_term_projection(services)
        previous = install_game_services(services)
        try:
            app = FastAPI()
            app.include_router(game_router)
            app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
            FastAPIAllowed(app)
            with TestClient(app) as client:
                _assert_web_assets(client, reference.share_id, services.battle_reports)
        finally:
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


def _assert_web_assets(client: TestClient, share_id: str, service) -> None:
    exists_calls = []
    real_exists = service.public_exists
    real_selection = service.load_public_selection

    def tracked_exists(value, *, logical_time):
        exists_calls.append(value)
        return real_exists(value, logical_time=logical_time)

    def selection_must_not_run(*args, **kwargs):
        raise AssertionError("HTML 入口不应读取或解压战报片段")

    service.public_exists = tracked_exists
    service.load_public_selection = selection_must_not_run
    try:
        response = client.get(f"/battle/{share_id}")
    finally:
        service.public_exists = real_exists
        service.load_public_selection = real_selection
    assert response.status_code == 200
    assert exists_calls == [share_id]
    assert "/static/battle-report/style.css?v=19" in response.text
    assert "/static/battle-report/app.js?v=19" in response.text
    assert 'script type="module"' in response.text

    script = client.get("/static/battle-report/app.js").text
    timeline_script = client.get("/static/battle-report/timeline.js").text
    ui_script = client.get("/static/battle-report/ui.js").text
    combined_script = script + timeline_script + ui_script
    assert "state.report.ui.modes.map" in script
    assert "state.report.ui.snapshots.map" in script
    assert "detail.filters.map" in timeline_script
    assert 'action === "mode"' in script
    assert 'action === "segment"' in script
    assert 'action === "snapshot"' in script
    assert 'action === "participant-disclosure"' in script
    assert 'action === "filter"' in script
    assert "ensureEvents(state.segmentIndex)" in script
    assert "/segments/${index}/events" in script
    assert "/segments/${index}/participants/" in script
    assert "/segments/${index}/transitions/${values.sequence}" in script
    assert "/segments/${index}/raw" in script
    assert 'export function renderRawDataAccess' in timeline_script
    assert 'details.addEventListener("toggle"' in timeline_script
    assert "status.replaceWith(rawBlock(value))" in timeline_script
    assert 'export function node' in ui_script
    assert "function selectSegment(index)" in script
    assert 'select.dataset.action = "segment-select"' in script
    assert "event.text" in timeline_script
    assert "event.category" in timeline_script
    assert "buildActorVisualMap" not in combined_script
    assert "ACTOR_PALETTE" not in combined_script
    assert "visual?.color ||" not in timeline_script
    assert 'setProperty("--actor-color", visual.color)' in timeline_script
    assert "applyVisual(article, entry.visual)" in timeline_script
    assert not re.search(r"#[0-9a-fA-F]{6}", combined_script)
    assert "event.kind" not in combined_script
    assert "const MODE_OPTIONS" not in combined_script
    assert ".at(" not in combined_script
    assert "slice(0, 50)" not in combined_script
    assert "page_size" not in combined_script
    assert "pageSize" not in combined_script
    assert "cursor" not in combined_script
    for forbidden in ("血气", "灵力", "生命", "魔力", "同步", "护盾", "伤害", "攻击", "防御"):
        assert forbidden not in combined_script

    style = client.get("/static/battle-report/style.css").text
    assert "prefers-reduced-motion" in style
    assert ".participant-stack {" in style
    assert ".timeline-panel {" in style
    assert "--actor-color" in style
    assert "--event-type-color" not in style
    assert ".actor-system" not in style
    assert ".actor-0" not in style
    assert ".actor-15" not in style
    assert ".event-marker.actor-party-" not in style
    assert ".event-marker.actor-enemy-" not in style
    assert ".event-marker.tone-" not in style
    assert "view-transition" not in style
    assert "min-height: 44px" in style

    data_response = client.get(
        f"/battle/{share_id}/data",
        headers={"Accept-Encoding": "gzip"},
    )
    assert data_response.status_code == 200
    assert data_response.headers.get("content-encoding") == "gzip"
    assert len(data_response.content) < 100_000
    payload = data_response.json()
    _assert_public_payload(payload)
    assert payload["schema"] == PUBLIC_BATTLE_REPORT_SCHEMA
    assert payload["version"] == PUBLIC_BATTLE_REPORT_VERSION
    assert payload["summary"]["title"] == "探险战报"
    assert payload["detail"]["segment_count"] == 2
    assert len(payload["detail"]["segments"]) == 1
    segment = payload["detail"]["segments"][0]
    assert segment["index"] == 0
    assert segment["title"] == "第一战"
    assert segment["counts"]["events"] > 50
    assert len(segment["timeline"]) == segment["counts"]["actions"]
    assert all("events" not in entry and "facts" not in entry for entry in segment["timeline"])
    assert all("detail_groups" not in value for value in segment["initial_participants"])

    visuals = [value["visual"] for value in segment["combatants"]]
    assert [value["number"] for value in visuals] == [1, 2, 3]
    assert len({value["color"] for value in visuals}) == len(visuals)
    assert all(re.fullmatch(r"#[0-9a-f]{6}", value["color"]) for value in visuals)
    assert segment["system_visual"] == {
        "key": "system",
        "number": 0,
        "color": "#6b7280",
        "foreground": "#ffffff",
    }
    visual_by_key = {value["key"]: value["visual"] for value in segment["combatants"]}
    assert all(
        value["visual"] == visual_by_key[value["key"]]
        for value in segment["initial_participants"]
    )

    participants = {value["label"]: value for value in segment["initial_participants"]}
    assert [value["label"] for value in participants["问道客"]["gauges"]] == ["气血", "灵力"]
    assert [value["label"] for value in participants["星辉狮鹫"]["gauges"]] == ["生命", "魔力"]
    assert [value["label"] for value in participants["边界守卫"]["gauges"]] == ["生命", "同步"]
    companion = next(value for value in segment["combatants"] if value["unit_kind"] == "companion")
    assert "projection" not in companion
    turn = segment["timeline"][1]
    assert segment["timeline"][0]["visual"] == segment["system_visual"]
    assert turn["visual"] == visual_by_key["p0"]
    assert turn["round_label"] == "第 1 回合"
    assert len(turn["summary_events"]) > 50
    assert any(value["kind"] == "resource.transferred" for value in turn["summary_events"])

    events_response = client.get(f"/battle/{share_id}/segments/0/events")
    assert events_response.status_code == 200
    event_payload = events_response.json()
    _assert_public_payload(event_payload)
    assert len(event_payload["timeline"]) == segment["counts"]["actions"]
    assert event_payload["timeline"][0]["visual"] == segment["system_visual"]
    assert event_payload["timeline"][1]["visual"] == visual_by_key["p0"]
    event_count = sum(len(value["events"]) for value in event_payload["timeline"])
    assert event_count == segment["counts"]["events"]
    assert event_count > 50
    assert event_payload["filters"][0]["count"] == event_count
    transfer = next(
        value
        for entry in event_payload["timeline"]
        for value in entry["events"]
        if value["kind"] == "resource.transferred"
    )
    assert "同步" in transfer["text"] and "灵力" in transfer["text"]
    health_change = next(
        value
        for entry in event_payload["timeline"]
        for value in entry["events"]
        if value["kind"] == "resource.changed"
    )
    assert "边界守卫 的生命减少 100 点" in health_change["text"]

    participant_response = client.get(f"/battle/{share_id}/segments/0/participants/before")
    assert participant_response.status_code == 200
    participant_payload = participant_response.json()
    _assert_public_payload(participant_payload)
    detailed = {value["label"]: value for value in participant_payload["participants"]}
    character = detailed["问道客"]
    group_items = [
        item
        for group in character["detail_groups"]
        for item in group["items"]
    ]
    assert not {str(HEALTH_MAXIMUM), str(SPIRIT_MAXIMUM), str(HEALTH_CURRENT), str(SPIRIT_CURRENT)} & {
        item.get("id") for item in group_items
    }
    permanent = next(value for value in character["detail_groups"] if value["id"] == "permanent_effects")
    assert all("永久" not in value["display"] for value in permanent["items"])

    transition_response = client.get(f"/battle/{share_id}/segments/0/transitions/1")
    assert transition_response.status_code == 200
    transition_payload = transition_response.json()
    _assert_public_payload(transition_payload)
    comparison = transition_payload["comparison"]
    assert comparison["before"]["title"] == "动作前状态"
    assert comparison["after"]["title"] == "动作后状态"
    assert comparison["before"]["round_turn_label"].startswith("第 1 回合")
    assert comparison["after"]["round_turn_label"].startswith("第 2 回合")

    raw_response = client.get(f"/battle/{share_id}/segments/0/raw")
    assert raw_response.status_code == 200
    raw_payload = raw_response.json()
    _assert_public_payload(raw_payload)
    assert len(raw_payload["transitions"]) == segment["counts"]["actions"]
    assert sum(len(value["events"]) for value in raw_payload["transitions"]) == event_count

    second_response = client.get(f"/battle/{share_id}/segments/1")
    assert second_response.status_code == 200
    second = second_response.json()
    _assert_public_payload(second)
    assert second["segment"]["index"] == 1
    assert second["segment"]["title"] == "第二战"
    assert len(second["segment"]["timeline"]) == second["segment"]["counts"]["actions"]

    assert client.get(f"/battle/{share_id}/segments/2").status_code == 404
    assert client.get(f"/battle/{share_id}/segments/0/participants/middle").status_code == 404
    assert client.get(f"/battle/{share_id}/segments/0/transitions/999").status_code == 404
    assert client.get("/battle/not-found").status_code == 404
    assert client.get("/battle/not-found/data").status_code == 404

    try:
        validate_public_battle_report({"message": "DIRECT_MESSAGE:private-request"})
    except RuntimeError as exc:
        assert "平台请求身份" in str(exc)
    else:
        raise AssertionError("公共战报校验必须阻断 DIRECT_MESSAGE 请求身份")


def _assert_production_preview() -> None:
    preview_path = PREVIEW_ROOT / "battle-report-production.html"
    assert preview_path.is_file()
    assert not (PREVIEW_ROOT / "battle-report-humanized.html").exists()
    preview = preview_path.read_text(encoding="utf-8")
    assert "<style" not in preview
    assert "maximum-scale" not in preview
    assert "user-scalable" not in preview
    assert "../../static/battle-report/style.css?v=19" in preview
    assert "../../static/battle-report/app.js?v=19" in preview
    assert 'script type="module"' in preview
    assert 'meta name="battle-report-preview-data"' in preview
    opening = '<script id="battleReportPreviewData" type="application/json">'
    payload = preview.split(opening, 1)[1].split("</script>", 1)[0]
    embedded = json.loads(payload)
    generated, generated_bundle = build_preview_artifacts()
    assert embedded == generated
    bundle_path = PREVIEW_ROOT / "battle-report-production.data.json"
    assert bundle_path.is_file()
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert bundle == generated_bundle
    _assert_public_payload(embedded)
    _assert_public_payload(bundle)
    assert embedded["schema"] == PUBLIC_BATTLE_REPORT_SCHEMA
    assert embedded["version"] == PUBLIC_BATTLE_REPORT_VERSION
    assert embedded["detail"]["available"] is True
    assert embedded["detail"]["segments"]
    assert len(payload.encode("utf-8")) < 100_000
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
    segment = embedded["detail"]["segments"][0]
    assert len(segment["timeline"]) == segment["counts"]["actions"]
    assert all("events" not in transition for transition in segment["timeline"])
    detail = bundle["events"]["0"]
    detailed_event_count = sum(len(value["events"]) for value in detail["timeline"])
    assert detailed_event_count == segment["counts"]["events"]
    initial_participants = bundle["participants"]["0:before"]["participants"]
    for participant in initial_participants:
        if participant["unit_kind"] != "character":
            continue
        permanent_group = next((
            value
            for value in participant["detail_groups"]
            if value["id"] == "permanent_effects"
        ), None)
        if permanent_group is None:
            continue
        assert all(
            "永久" not in effect["display"]
            for effect in permanent_group["items"]
        )
    serialized = json.dumps(bundle, ensure_ascii=False)
    assert "ability.test" not in payload
    assert "combat.damage.dealt" in serialized
    events = [
        event
        for transition in detail["timeline"]
        for event in transition["events"]
    ]
    phase_events = [
        event for event in events if event["kind"] == "combat.phase.activated"
    ]
    assert phase_events
    assert all(
        "进入新的战斗阶段" in event["text"]
        and "获得" in event["text"]
        and any(fact["key"] == "behavior_ids" and fact["value"] for fact in event["facts"])
        and event["subject"]["id"].startswith("enemy.phase.")
        and event["subject"]["label"].endswith("阶段能力")
        for event in phase_events
    )
    visual_by_key = {value["key"]: value["visual"] for value in segment["combatants"]}
    system_visual = segment["system_visual"]
    assert all(
        event["visual"] == visual_by_key.get(event["source"]["key"], system_visual)
        for event in events
    )
    for transition in segment["timeline"]:
        identities = [
            (event["text"], event["source"]["key"], event["target"]["key"])
            for event in transition["summary_events"]
        ]
        assert len(identities) == len(set(identities))
    summary_events = [
        event
        for transition in segment["timeline"]
        for event in transition["summary_events"]
    ]
    summary_text = "\n".join(event["text"] for event in summary_events)
    assert all(
        not re.search(r"（[^）]*(?:生命|气血|护盾) 0(?:，|）)", event["text"])
        for event in summary_events
    )
    assert "获得 敌技·不死守护·辅效" not in summary_text
    assert "敌技·不死守护·辅效 结束" not in summary_text

    stellar = build_official_content("skin.stellar_ring")
    weapon_names = {
        stellar.projector.name(f"weapon.{blueprint.key}")
        for blueprint in WEAPON_BLUEPRINTS
    }
    enemy_keys = {
        value["key"]
        for value in segment["combatants"]
        if value["unit_kind"] == "enemy"
    }
    for event in events:
        if event["source"]["key"] not in enemy_keys:
            continue
        event_text = json.dumps(event, ensure_ascii=False)
        assert not any(name in event_text for name in weapon_names)
        assert "effect.weapon." not in event_text
        assert "trigger.weapon." not in event_text
        assert "ability.weapon." not in event_text


def _assert_public_payload(value) -> None:
    forbidden_keys = {
        "content_fingerprint",
        "mode_id",
        "projection",
        "segment_id",
        "share_id",
        "page",
        "page_size",
        "cursor",
    }
    forbidden_markers = (
        "GROUP_MESSAGE_CREATE",
        "DIRECT_MESSAGE",
        "C2C_MESSAGE_CREATE",
        "platform.qq",
        ":qq:",
        "character-private-id",
        "companion-private-id",
        "enemy-private-id",
    )

    def visit(item):
        if isinstance(item, dict):
            assert not forbidden_keys.intersection(item)
            for nested in item.values():
                visit(nested)
        elif isinstance(item, (tuple, list)):
            for nested in item:
                visit(nested)
        elif isinstance(item, str):
            assert not any(marker.casefold() in item.casefold() for marker in forbidden_markers)

    visit(value)


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
            for index in range(60)
        ),
    )
    before = _frame(logical_time, 0, 1, "active", initial, round_number=1)
    after = _frame(logical_time, 1, 2, "finished", final, round_number=2)
    return BattleReportDraft(
        report_id=content_scoped_report_id(
            "battle-report:exploration:session-private-id",
            "content-fingerprint",
        ),
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
                    after=_frame(logical_time, 0, 0, "active", initial),
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


def _frame(logical_time, turn, revision, status, participants, *, round_number=1):
    return BattleReportFrameDraft(
        logical_time=logical_time,
        round_number=round_number,
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
