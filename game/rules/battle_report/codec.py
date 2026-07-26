"""自解释战报片段的紧凑 JSON 与 zlib 编解码。"""

from __future__ import annotations

from datetime import datetime
import json
import zlib

from .models import (
    BattleReportGear,
    BattleReportParticipantDraft,
    BattleReportSegmentDraft,
    BattleReportTerm,
    StoredBattleCombatant,
    StoredBattleEffect,
    StoredBattleEvent,
    StoredBattleFrame,
    StoredBattleParticipant,
    StoredBattleSegment,
    StoredBattleTransition,
)


BATTLE_REPORT_CODEC_VERSION = 4
COMPRESSION_LEVEL = 6


def encode_segment(draft: BattleReportSegmentDraft) -> tuple[bytes, int]:
    """移除实体、资产和效果实例身份后压缩一个战斗片段。"""

    aliases = {
        combatant.entity_id: f"p{index}"
        for index, combatant in enumerate(draft.combatants)
    }
    public_aliases = dict(aliases)
    for source_id, entity_id in draft.source_owners.items():
        public_aliases[source_id] = aliases[entity_id]
    effect_aliases = {
        instance_id: f"e{index}"
        for index, instance_id in enumerate(_effect_instance_ids(draft))
    }
    payload = {
        "v": BATTLE_REPORT_CODEC_VERSION,
        "id": draft.segment_id,
        "title": draft.title,
        "combatants": [
            {
                "key": aliases[value.entity_id],
                "label": value.label,
                "team": value.team_id,
                "team_label": value.team_label,
                "unit": value.unit_kind,
                "projection": [
                    value.projection_kind,
                    value.projection_id,
                    value.projection_version,
                ],
                "terms": {
                    content_id: [term.name, term.compact_name]
                    for content_id, term in sorted(value.terms.items())
                },
                "gear": [
                    [gear.slot_id, gear.slot_name, gear.name]
                    for gear in value.gear
                ],
            }
            for value in draft.combatants
        ],
        "initial": [
            _participant_payload(value, aliases, public_aliases, effect_aliases)
            for value in draft.initial_participants
        ],
        "final": [
            _participant_payload(value, aliases, public_aliases, effect_aliases)
            for value in draft.final_participants
        ],
        "transitions": [
            _transition_payload(value, aliases, public_aliases, effect_aliases)
            for value in draft.transitions
        ],
        "outcome": draft.outcome,
        "started_at": draft.started_at.isoformat(),
        "finished_at": draft.finished_at.isoformat(),
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return zlib.compress(raw, level=COMPRESSION_LEVEL), len(raw)


def decode_segment(payload: bytes) -> StoredBattleSegment:
    value = json.loads(zlib.decompress(payload).decode("utf-8"))
    if value.get("v") != BATTLE_REPORT_CODEC_VERSION:
        raise ValueError("战报片段编码版本不受支持")
    return StoredBattleSegment(
        segment_id=str(value["id"]),
        title=str(value["title"]),
        combatants=tuple(_decode_combatant(item) for item in value["combatants"]),
        initial_participants=tuple(
            _decode_participant(item) for item in value["initial"]
        ),
        final_participants=tuple(
            _decode_participant(item) for item in value["final"]
        ),
        transitions=tuple(
            _decode_transition(item) for item in value["transitions"]
        ),
        outcome=str(value["outcome"]),
        started_at=datetime.fromisoformat(value["started_at"]),
        finished_at=datetime.fromisoformat(value["finished_at"]),
    )


def _transition_payload(transition, aliases, public_aliases, effect_aliases):
    return {
        "sequence": transition.sequence,
        "kind": transition.kind,
        "subject": public_aliases.get(transition.subject_id, transition.subject_id),
        "before": (
            _frame_payload(transition.before, aliases, public_aliases, effect_aliases)
            if transition.before is not None
            else None
        ),
        "after": _frame_payload(
            transition.after,
            aliases,
            public_aliases,
            effect_aliases,
        ),
        "events": [
            _event_payload(event, public_aliases) for event in transition.events
        ],
        "actor": public_aliases.get(transition.actor_entity_id, "system"),
        "action": transition.action_id,
        "ability": transition.ability_id,
        "decision": transition.decision_rule_id,
        "selector": transition.requested_selector_id,
        "requested": [public_aliases.get(value, "system") for value in transition.requested_target_ids],
        "resolved": [public_aliases.get(value, "system") for value in transition.resolved_target_ids],
        "parameters": dict(transition.action_parameters),
        "tags": list(transition.action_context_tags),
    }


def _frame_payload(frame, aliases, public_aliases, effect_aliases):
    return {
        "at": frame.logical_time.isoformat(),
        "round": frame.round_number,
        "turn": frame.turn_number,
        "status": frame.status,
        "revision": frame.revision,
        "current_actor": public_aliases.get(frame.current_actor_entity_id, "system"),
        "turn_order": [public_aliases.get(value, "system") for value in frame.turn_order_entity_ids],
        "inactive": [public_aliases.get(value, "system") for value in frame.inactive_entity_ids],
        "winners": list(frame.winning_team_ids),
        "progress": {
            public_aliases.get(key, "system"): value
            for key, value in frame.action_progress.items()
        },
        "participants": [
            _participant_payload(value, aliases, public_aliases, effect_aliases)
            for value in frame.participants
        ],
    }


def _participant_payload(
    participant: BattleReportParticipantDraft,
    aliases: dict[str, str],
    public_aliases: dict[str, str],
    effect_aliases: dict[str, str],
) -> dict[str, object]:
    return {
        "key": aliases[participant.entity_id],
        "attributes": dict(participant.attributes),
        "resources": dict(participant.resources),
        "abilities": list(participant.abilities),
        "effects": [
            {
                "key": effect_aliases[value.instance_id],
                "definition": value.definition_id,
                "source": public_aliases.get(
                    value.source_id,
                    aliases[participant.entity_id],
                ),
                "stacks": value.stacks,
                "remaining": value.remaining_turns,
                "polarity": value.polarity,
            }
            for value in participant.effects
        ],
        "cooldowns": dict(participant.cooldowns),
        "triggers": list(participant.triggers),
        "interceptors": list(participant.interceptors),
        "constraints": list(participant.target_constraints),
    }


def _event_payload(event, public_aliases: dict[str, str]) -> dict[str, object]:
    return {
        "k": str(event.kind),
        "s": public_aliases.get(event.source_id, "system"),
        "t": public_aliases.get(event.target_id, "system"),
        "u": public_aliases.get(str(event.subject_id), str(event.subject_id)),
        "at": event.logical_time.isoformat(),
        "v": _json_value(dict(event.values), public_aliases),
        "p": event.phase.value,
    }


def _decode_combatant(item: dict[str, object]) -> StoredBattleCombatant:
    projection = item["projection"]
    return StoredBattleCombatant(
        key=str(item["key"]),
        label=str(item["label"]),
        team_id=str(item["team"]),
        team_label=str(item["team_label"]),
        unit_kind=str(item["unit"]),
        projection_kind=str(projection[0]),
        projection_id=str(projection[1]),
        projection_version=int(projection[2]),
        terms={
            str(content_id): BattleReportTerm(str(term[0]), str(term[1]))
            for content_id, term in item.get("terms", {}).items()
        },
        gear=tuple(
            BattleReportGear(str(value[0]), str(value[1]), str(value[2]))
            for value in item.get("gear", ())
        ),
    )


def _decode_transition(item: dict[str, object]) -> StoredBattleTransition:
    before = item.get("before")
    return StoredBattleTransition(
        sequence=int(item["sequence"]),
        kind=str(item["kind"]),
        subject_id=str(item["subject"]),
        before=_decode_frame(before) if before is not None else None,
        after=_decode_frame(item["after"]),
        events=tuple(_decode_event(value) for value in item.get("events", ())),
        actor_key=(str(item["actor"]) if item.get("actor") not in {None, "system"} else None),
        action_id=str(item["action"]) if item.get("action") is not None else None,
        ability_id=str(item["ability"]) if item.get("ability") is not None else None,
        decision_rule_id=str(item["decision"]) if item.get("decision") is not None else None,
        requested_selector_id=str(item["selector"]) if item.get("selector") is not None else None,
        requested_target_keys=tuple(str(value) for value in item.get("requested", ())),
        resolved_target_keys=tuple(str(value) for value in item.get("resolved", ())),
        action_parameters={str(key): float(number) for key, number in item.get("parameters", {}).items()},
        action_context_tags=tuple(str(value) for value in item.get("tags", ())),
    )


def _decode_frame(item: dict[str, object]) -> StoredBattleFrame:
    return StoredBattleFrame(
        logical_time=datetime.fromisoformat(str(item["at"])),
        round_number=int(item["round"]),
        turn_number=int(item["turn"]),
        status=str(item["status"]),
        revision=int(item["revision"]),
        current_actor_key=(
            str(item["current_actor"])
            if item.get("current_actor") not in {None, "system"}
            else None
        ),
        turn_order_keys=tuple(str(value) for value in item.get("turn_order", ())),
        inactive_keys=tuple(str(value) for value in item.get("inactive", ())),
        winning_team_ids=tuple(str(value) for value in item.get("winners", ())),
        action_progress={str(key): float(number) for key, number in item.get("progress", {}).items()},
        participants=tuple(_decode_participant(value) for value in item.get("participants", ())),
    )


def _decode_event(item: dict[str, object]) -> StoredBattleEvent:
    return StoredBattleEvent(
        kind=str(item["k"]),
        source=str(item["s"]),
        target=str(item["t"]),
        subject=str(item["u"]),
        logical_time=datetime.fromisoformat(str(item["at"])),
        values=dict(item.get("v", {})),
        phase=str(item.get("p", "resolve")),
    )


def _decode_participant(item: dict[str, object]) -> StoredBattleParticipant:
    return StoredBattleParticipant(
        key=str(item["key"]),
        attributes={str(key): float(number) for key, number in item.get("attributes", {}).items()},
        resources={str(key): float(number) for key, number in item.get("resources", {}).items()},
        abilities=tuple(str(value) for value in item.get("abilities", ())),
        effects=tuple(
            StoredBattleEffect(
                key=str(value["key"]),
                definition_id=str(value["definition"]),
                source_key=str(value["source"]),
                stacks=int(value["stacks"]),
                remaining_turns=(
                    None if value.get("remaining") is None else int(value["remaining"])
                ),
                polarity=str(value["polarity"]),
            )
            for value in item.get("effects", ())
        ),
        cooldowns={str(key): int(number) for key, number in item.get("cooldowns", {}).items()},
        triggers=tuple(str(value) for value in item.get("triggers", ())),
        interceptors=tuple(str(value) for value in item.get("interceptors", ())),
        target_constraints=tuple(str(value) for value in item.get("constraints", ())),
    )


def _effect_instance_ids(draft: BattleReportSegmentDraft) -> tuple[str, ...]:
    values: list[str] = []
    for participant in _all_participant_states(draft):
        for effect in participant.effects:
            if effect.instance_id not in values:
                values.append(effect.instance_id)
    return tuple(values)


def _all_participant_states(draft: BattleReportSegmentDraft):
    yield from draft.initial_participants
    yield from draft.final_participants
    for transition in draft.transitions:
        for frame in (transition.before, transition.after):
            if frame is not None:
                yield from frame.participants


def _json_value(value: object, aliases: dict[str, str]) -> object:
    if isinstance(value, dict):
        return {str(key): _json_value(item, aliases) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_value(item, aliases) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return aliases.get(value, value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


__all__ = [
    "BATTLE_REPORT_CODEC_VERSION",
    "COMPRESSION_LEVEL",
    "decode_segment",
    "encode_segment",
]
