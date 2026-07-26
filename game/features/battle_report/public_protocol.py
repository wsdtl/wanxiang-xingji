"""公共战报协议 v3：紧凑首包、按需明细和稳定展示身份。"""

from __future__ import annotations

from colorsys import hls_to_rgb
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType

from game.content.catalog.combat.stats import SHIELD_CURRENT
from game.core.gameplay import (
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    COMBAT_SPEED,
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    SPIRIT_MAXIMUM,
)
from game.rules.battle_report import (
    BattleReportView,
    StoredBattleEffect,
    StoredBattleEvent,
    StoredBattleFrame,
    StoredBattleParticipant,
    StoredBattleSegment,
    StoredBattleTransition,
)

from .presentation import (
    BATTLE_EVENT_PRESENTATIONS,
    PUBLIC_BATTLE_REPORT_SCHEMA,
    PUBLIC_BATTLE_REPORT_VERSION,
    EventPresentationContext,
    _FILTER_OPTIONS,
    _MODE_OPTIONS,
    _SNAPSHOT_OPTIONS,
    _STATUS_NAMES,
    _UI,
)


_SYSTEM_VISUAL = MappingProxyType(
    {
        "key": "system",
        "number": 0,
        "color": "#6b7280",
        "foreground": "#ffffff",
    }
)
_BASE_ACTOR_COLORS = (
    "#e53935",
    "#1e88e5",
    "#43a047",
    "#fb8c00",
    "#8e24aa",
    "#00acc1",
    "#d81b60",
    "#7cb342",
    "#5e35b1",
    "#00897b",
    "#f4511e",
    "#3949ab",
)
_PERCENTAGE_ATTRIBUTE_IDS = frozenset(
    {
        "combat.accuracy",
        "combat.block.chance",
        "combat.block.reduction",
        "combat.control.chance",
        "combat.control.resistance",
        "combat.control.tenacity",
        "combat.critical.chance",
        "combat.critical.damage",
        "combat.damage.incoming_rate",
        "combat.damage.outgoing_rate",
        "combat.evasion",
        "combat.healing.outgoing_rate",
        "combat.healing.received_rate",
        "combat.penetration.rate",
    }
)
_PRIMARY_ATTRIBUTE_IDS = frozenset(
    {str(COMBAT_ATTACK), str(COMBAT_DEFENSE), str(COMBAT_SPEED)}
)
_GAUGE_ATTRIBUTE_IDS = frozenset({str(HEALTH_MAXIMUM), str(SPIRIT_MAXIMUM)})
_GAUGE_RESOURCE_IDS = frozenset(
    {str(HEALTH_CURRENT), str(SPIRIT_CURRENT), str(SHIELD_CURRENT)}
)
_INTERNAL_EFFECT_IDS = frozenset({"feature.basic_combat"})
_INTERNAL_EFFECT_PREFIXES = (
    "companion.contribution.",
    "loadout.",
)
_FORBIDDEN_PUBLIC_MARKERS = (
    "GROUP_MESSAGE_CREATE",
    "DIRECT_MESSAGE",
    "DIRECT_MESSAGE_CREATE",
    "C2C_MESSAGE_CREATE",
    "platform.qq",
    ":qq:",
)
_SUMMARY_EVENT_KINDS = frozenset(
    {
        "combat.turn.skipped",
        "resource.changed",
        "resource.transferred",
        "combat.attack.missed",
        "combat.attack.critical",
        "combat.attack.blocked",
        "combat.damage.prevented",
        "combat.damage.redirected",
        "combat.healing.resolved",
        "combat.target.revived",
        "combat.shield.granted",
        "combat.shield.broken",
        "combat.control.resolved",
        "combat.target.defeated",
        "combat.action.interrupted",
        "combat.timeline.extra_turn_requested",
        "combat.timeline.delay_requested",
        "effect.applied",
        "effect.application.rejected",
        "effect.expired",
        "effect.removed",
        "effect.stacks_changed",
        "effect.duration_changed",
        "trigger.activated",
        "combat.participant.joined",
        "combat.phase.activated",
        "combat.participant.left",
    }
)
_TRIGGER_OUTCOME_KINDS = frozenset(
    {
        "resource.transferred",
        "combat.attack.missed",
        "combat.damage.dealt",
        "combat.damage.prevented",
        "combat.damage.redirected",
        "combat.healing.resolved",
        "combat.target.revived",
        "combat.shield.granted",
        "combat.control.resolved",
        "combat.target.defeated",
        "combat.timeline.extra_turn_requested",
        "combat.timeline.delay_requested",
        "effect.applied",
        "effect.application.rejected",
    }
)


class PublicBattleReportProjector:
    """把一个冻结片段投影成协议 v3 的多个按需视图。"""

    def __init__(self, segment: StoredBattleSegment) -> None:
        self.segment = segment
        combatants = {value.key: value for value in segment.combatants}
        self.context = EventPresentationContext(MappingProxyType(combatants))
        self.visuals = _actor_visuals(segment)

    def compact_segment(
        self,
        *,
        segment_index: int,
        segment_count: int,
    ) -> dict[str, object]:
        return {
            "index": segment_index,
            "position_label": f"{segment_index + 1} / {segment_count}",
            "title": self.segment.title,
            "outcome": self.segment.outcome,
            "started_at": self.segment.started_at.isoformat(),
            "finished_at": self.segment.finished_at.isoformat(),
            "duration_label": _duration_label(
                self.segment.started_at,
                self.segment.finished_at,
            ),
            "system_visual": dict(_SYSTEM_VISUAL),
            "combatants": [self._combatant(value) for value in self.segment.combatants],
            "initial_participants": [
                self._participant(value, detail=False)
                for value in self.segment.initial_participants
            ],
            "final_participants": [
                self._participant(value, detail=False)
                for value in self.segment.final_participants
            ],
            "counts": {
                "actions": len(self.segment.transitions),
                "events": len(self.segment.events),
            },
            "timeline": [
                self._compact_transition(value)
                for value in self.segment.transitions
            ],
        }

    def events(self, *, segment_index: int) -> dict[str, object]:
        entries = [self._detailed_transition(value) for value in self.segment.transitions]
        counts = defaultdict(int)
        for entry in entries:
            for event in entry["events"]:
                counts["all"] += 1
                counts[str(event["category"])] += 1
        filters = [
            {**option, "count": counts[option["id"]]}
            for option in _FILTER_OPTIONS
        ]
        result = {
            "schema": PUBLIC_BATTLE_REPORT_SCHEMA,
            "version": PUBLIC_BATTLE_REPORT_VERSION,
            "segment_index": segment_index,
            "filters": filters,
            "timeline": entries,
        }
        validate_public_battle_report(result)
        return result

    def participants(self, *, segment_index: int, snapshot: str) -> dict[str, object]:
        if snapshot == "before":
            values = self.segment.initial_participants
        elif snapshot == "after":
            values = self.segment.final_participants or self.segment.initial_participants
        else:
            raise ValueError("战报参与者快照只能是 before 或 after")
        result = {
            "schema": PUBLIC_BATTLE_REPORT_SCHEMA,
            "version": PUBLIC_BATTLE_REPORT_VERSION,
            "segment_index": segment_index,
            "snapshot": snapshot,
            "participants": [self._participant(value, detail=True) for value in values],
        }
        validate_public_battle_report(result)
        return result

    def transition(self, *, segment_index: int, sequence: int) -> dict[str, object]:
        transition = next(
            (value for value in self.segment.transitions if value.sequence == sequence),
            None,
        )
        if transition is None:
            raise KeyError(sequence)
        before = (
            self._frame(transition.before, "动作前状态")
            if transition.before is not None
            else None
        )
        after_title = "战斗建立状态" if transition.kind == "start" else "动作后状态"
        result = {
            "schema": PUBLIC_BATTLE_REPORT_SCHEMA,
            "version": PUBLIC_BATTLE_REPORT_VERSION,
            "segment_index": segment_index,
            "sequence": sequence,
            "comparison": {
                "title": _UI["comparison_title"],
                "empty_text": _UI["comparison_empty"],
                "changes": self._state_changes(transition.before, transition.after),
                "before": before,
                "after": self._frame(transition.after, after_title),
            },
        }
        validate_public_battle_report(result)
        return result

    def raw(self, *, segment_index: int) -> dict[str, object]:
        result = {
            "schema": PUBLIC_BATTLE_REPORT_SCHEMA,
            "version": PUBLIC_BATTLE_REPORT_VERSION,
            "segment_index": segment_index,
            "title": self.segment.title,
            "outcome": self.segment.outcome,
            "combatants": [self._combatant(value) for value in self.segment.combatants],
            "initial_participants": [
                self._participant(value, detail=True)
                for value in self.segment.initial_participants
            ],
            "final_participants": [
                self._participant(value, detail=True)
                for value in self.segment.final_participants
            ],
            "transitions": [
                {
                    "sequence": transition.sequence,
                    "kind": transition.kind,
                    "title": self._transition_title(transition),
                    "round": _transition_round(transition),
                    "events": [
                        self._raw_event(event, event_index)
                        for event_index, event in enumerate(transition.events)
                    ],
                }
                for transition in self.segment.transitions
            ],
        }
        validate_public_battle_report(result)
        return result

    def _combatant(self, combatant) -> dict[str, object]:
        return {
            "key": combatant.key,
            "label": combatant.label,
            "team_id": combatant.team_id,
            "team_label": combatant.team_label,
            "unit_kind": combatant.unit_kind,
            "visual": dict(self.visuals[combatant.key]),
        }

    def _participant(
        self,
        participant: StoredBattleParticipant,
        *,
        detail: bool,
    ) -> dict[str, object]:
        combatant = self.context.combatants[participant.key]
        temporary = [
            self._effect(value, participant.key)
            for value in participant.effects
            if value.remaining_turns is not None
        ]
        result = {
            "key": participant.key,
            "label": combatant.label,
            "team_id": combatant.team_id,
            "team_label": combatant.team_label,
            "unit_kind": combatant.unit_kind,
            "visual": dict(self.visuals[participant.key]),
            "gauges": self._gauges(participant),
            "status_group": {
                "id": "temporary_effects",
                "label": "当前状态",
                "presentation": "chips",
                "empty_text": "当前无持续状态",
                "items": _dedupe_items(temporary),
            },
        }
        if detail:
            result["detail_label"] = "完整状态"
            result["detail_groups"] = self._detail_groups(participant)
        return result

    def _gauges(self, participant: StoredBattleParticipant) -> list[dict[str, object]]:
        gauges = []
        for current_id, maximum_id, tone in (
            (str(HEALTH_CURRENT), str(HEALTH_MAXIMUM), "primary"),
            (str(SPIRIT_CURRENT), str(SPIRIT_MAXIMUM), "secondary"),
        ):
            if current_id not in participant.resources or maximum_id not in participant.attributes:
                continue
            current = participant.resources[current_id]
            maximum = participant.attributes[maximum_id]
            gauges.append(
                {
                    "id": current_id,
                    "label": self.context.term(
                        participant.key,
                        current_id,
                        "当前资源",
                        compact=True,
                    ),
                    "current": current,
                    "maximum": maximum,
                    "display": f"{_number(current)} / {_number(maximum)}",
                    "tone": tone,
                    "presentation": "bar",
                }
            )
        shield_id = str(SHIELD_CURRENT)
        if shield_id in participant.resources:
            current = participant.resources[shield_id]
            gauges.append(
                {
                    "id": shield_id,
                    "label": self.context.term(
                        participant.key,
                        shield_id,
                        "护盾",
                        compact=True,
                    ),
                    "current": current,
                    "display": _number(current),
                    "tone": "shield",
                    "presentation": "value",
                }
            )
        return gauges

    def _detail_groups(
        self,
        participant: StoredBattleParticipant,
    ) -> list[dict[str, object]]:
        combatant = self.context.combatants[participant.key]
        gear_names = {value.name for value in combatant.gear}
        permanent = [
            self._effect(value, participant.key)
            for value in participant.effects
            if value.remaining_turns is None
            and self._public_permanent_effect(value, gear_names)
        ]
        attributes = []
        for content_id, value in sorted(participant.attributes.items()):
            if content_id in _GAUGE_ATTRIBUTE_IDS:
                continue
            if not value and content_id not in _PRIMARY_ATTRIBUTE_IDS:
                continue
            attributes.append(
                _item(
                    content_id,
                    self.context.term(participant.key, content_id, "战斗属性"),
                    _attribute_display(content_id, value),
                    value=value,
                )
            )
        resources = [
            _item(
                content_id,
                self.context.term(participant.key, content_id, "战斗资源"),
                _number(value),
                value=value,
            )
            for content_id, value in sorted(participant.resources.items())
            if content_id not in _GAUGE_RESOURCE_IDS
        ]
        abilities = [
            _item(
                content_id,
                self.context.term(participant.key, content_id, "未命名招式"),
                "",
            )
            for content_id in participant.abilities
        ]
        cooldowns = [
            _item(
                content_id,
                self.context.term(participant.key, content_id, "未命名招式"),
                f"{turns} 回合",
            )
            for content_id, turns in sorted(participant.cooldowns.items())
            if turns > 0
        ]
        groups = (
            _group(
                "gear",
                "参战配装",
                [
                    _item(value.slot_id, value.slot_name, value.name)
                    for value in combatant.gear
                ],
            ),
            _group("attributes", "属性", attributes),
            _group("resources", "其他资源", resources),
            _group("abilities", "招式", _dedupe_items(abilities)),
            _group("permanent_effects", "常驻效果", _dedupe_items(permanent)),
            _group("cooldowns", "冷却", cooldowns),
        )
        return [value for value in groups if value is not None]

    def _effect(
        self,
        effect: StoredBattleEffect,
        target_key: str,
    ) -> dict[str, object]:
        name = self.context.term(effect.source_key, effect.definition_id, "战斗效果")
        metadata = []
        if effect.stacks > 1:
            metadata.append(f"{effect.stacks} 层")
        if effect.remaining_turns is not None:
            metadata.append(f"剩余 {effect.remaining_turns} 回合")
        if effect.source_key != target_key:
            metadata.append(f"来源 {self.context.actor(effect.source_key, '战场')}")
        return {
            "label": name,
            "display": " · ".join(metadata),
            "stacks": effect.stacks,
            "remaining_turns": effect.remaining_turns,
            "tone": effect.polarity,
        }

    def _public_permanent_effect(
        self,
        effect: StoredBattleEffect,
        gear_names: set[str],
    ) -> bool:
        identifier = effect.definition_id
        if identifier in _INTERNAL_EFFECT_IDS:
            return False
        if identifier.startswith(_INTERNAL_EFFECT_PREFIXES):
            return False
        label = self.context.term(effect.source_key, identifier, "战斗效果")
        return label not in gear_names

    def _compact_transition(
        self,
        transition: StoredBattleTransition,
    ) -> dict[str, object]:
        events = self._summary_events(transition)
        categories = list(dict.fromkeys(str(value["category"]) for value in events))
        return {
            "sequence": transition.sequence,
            "title": self._transition_title(transition),
            "round_label": f"第 {_transition_round(transition)} 回合",
            "tone": _dominant_tone(events),
            "visual": dict(self._transition_visual(transition)),
            "categories": categories,
            "summary_events": events,
            "comparison_available": True,
        }

    def _detailed_transition(
        self,
        transition: StoredBattleTransition,
    ) -> dict[str, object]:
        events = [
            self._event(event, event_index)
            for event_index, event in enumerate(transition.events)
        ]
        round_number = _transition_round(transition)
        return {
            "sequence": transition.sequence,
            "title": self._transition_title(transition),
            "round_label": f"第 {round_number} 回合",
            "sequence_label": f"回合 {round_number} · 序列 {transition.sequence}",
            "tone": _dominant_tone(events),
            "visual": dict(self._transition_visual(transition)),
            "categories": list(
                dict.fromkeys(str(value["category"]) for value in events)
            ),
            "facts": self._transition_facts(transition),
            "events": events,
            "comparison": {
                "available": True,
                "sequence": transition.sequence,
                "title": _UI["comparison_title"],
            },
        }

    def _transition_visual(
        self,
        transition: StoredBattleTransition,
    ) -> Mapping[str, object]:
        if transition.kind != "turn":
            return _SYSTEM_VISUAL
        return self.visuals.get(transition.actor_key or "", _SYSTEM_VISUAL)

    def _transition_title(self, transition: StoredBattleTransition) -> str:
        actor = self.context.actor(transition.actor_key or "", "战场")
        if transition.kind == "start":
            return "战斗建立"
        if transition.kind == "turn":
            ability = self.context.term(
                transition.actor_key,
                transition.ability_id or "",
                "普通行动",
            )
            targets = "、".join(
                self.context.actor(value, "未知目标")
                for value in transition.resolved_target_keys
            ) or "无目标"
            return f"{actor} 对 {targets} 使用 {ability}"
        names = {
            "join": "参与者加入",
            "withdraw": "参与者退出",
            "external": "外部战斗阶段",
        }
        fallback = names.get(transition.kind, "状态转移")
        subject = self.context.term(
            transition.actor_key,
            transition.subject_id,
            fallback,
        )
        return fallback if subject == fallback else f"{fallback} · {subject}"

    def _transition_facts(
        self,
        transition: StoredBattleTransition,
    ) -> list[dict[str, object]]:
        facts = [
            _fact("序号", transition.sequence),
            _fact("回合", _transition_round(transition)),
        ]
        if transition.resolved_target_keys:
            facts.append(
                _fact(
                    "目标",
                    [
                        self.context.actor(value, "未知目标")
                        for value in transition.resolved_target_keys
                    ],
                )
            )
        return facts

    def _event(
        self,
        event: StoredBattleEvent,
        event_index: int,
    ) -> dict[str, object]:
        value = BATTLE_EVENT_PRESENTATIONS.present(event, self.context)
        value["event_index"] = event_index
        value["visual"] = dict(self.visuals.get(event.source, _SYSTEM_VISUAL))
        return value

    def _raw_event(
        self,
        event: StoredBattleEvent,
        event_index: int,
    ) -> dict[str, object]:
        presented = self._event(event, event_index)
        return {
            "event_index": event_index,
            "kind": presented["kind"],
            "source": presented["source"],
            "target": presented["target"],
            "subject": presented["subject"],
            "phase": presented["phase"],
            "logical_time": presented["logical_time"],
            "values": {
                fact["key"]: fact["value"]
                for fact in presented["facts"]
            },
        }

    def _summary_events(
        self,
        transition: StoredBattleTransition,
    ) -> list[dict[str, object]]:
        raw_events = transition.events
        consumed = _transient_effect_indexes(raw_events)
        summaries: list[tuple[int, dict[str, object]]] = []

        for index, event in enumerate(raw_events):
            if event.kind != "trigger.activated" or index in consumed:
                continue
            outcome_index = self._trigger_outcome_index(raw_events, index, consumed)
            trigger = self._event(event, index)
            subject = self.context.subject(event, "触发机制")
            trigger_text = subject if subject.endswith("触发") else f"{subject}触发"
            trigger["text"] = (
                f"{self.context.actor(event.source)} 的 "
                f"{trigger_text}"
            )
            if outcome_index is not None:
                outcome = self._event(raw_events[outcome_index], outcome_index)
                trigger["text"] = f"{trigger['text']}，{outcome['text']}"
                trigger["category"] = outcome["category"]
                trigger["tone"] = outcome["tone"]
                consumed.add(outcome_index)
            consumed.add(index)
            summaries.append((index, _compact_event(trigger)))

        damage_groups: dict[tuple[str, str], list[tuple[int, StoredBattleEvent]]] = defaultdict(list)
        for index, event in enumerate(raw_events):
            if index not in consumed and event.kind == "combat.damage.dealt":
                damage_groups[(event.source, event.target)].append((index, event))
        for (source, target), values in damage_groups.items():
            indexes = {index for index, _event in values}
            consumed.update(indexes)
            damage = self._damage_summary(source, target, values)
            related_broken = [
                index
                for index, event in enumerate(raw_events)
                if index not in consumed
                and event.kind == "combat.shield.broken"
                and event.source == source
                and event.target == target
            ]
            if related_broken:
                damage["text"] = f"{damage['text']}，护盾破碎"
                consumed.update(related_broken)
            summaries.append((min(indexes), damage))

        paired_resources = {
            (event.target, event.subject)
            for event in raw_events
            if event.kind
            in {
                "combat.healing.resolved",
                "combat.shield.granted",
                "resource.transferred",
            }
        }
        paired_resources.update(
            (event.target, resource_id)
            for event in raw_events
            if event.kind in {"combat.damage.dealt", "combat.damage.prevented"}
            for resource_id in (str(HEALTH_CURRENT), str(SHIELD_CURRENT))
        )
        for index, event in enumerate(raw_events):
            if index in consumed or event.kind not in _SUMMARY_EVENT_KINDS:
                continue
            if event.kind == "effect.applied" and _integer(event.values.get("stacks")) <= 0:
                continue
            if event.kind == "resource.changed" and (event.target, event.subject) in paired_resources:
                continue
            if event.kind == "combat.shield.damaged":
                continue
            value = self._event(event, index)
            summaries.append((index, _compact_event(value)))

        result = []
        seen = set()
        for _index, value in sorted(summaries, key=lambda item: item[0]):
            identity = (
                value["text"],
                value["source"]["key"],
                value["target"]["key"],
            )
            if identity in seen:
                continue
            seen.add(identity)
            result.append(value)
        return result

    @staticmethod
    def _trigger_outcome_index(raw_events, trigger_index, consumed):
        fallback = None
        for index in range(trigger_index + 1, len(raw_events)):
            event = raw_events[index]
            if event.kind in {"trigger.activated", "ability.completed", "combat.turn.ended"}:
                return fallback
            if index in consumed:
                continue
            if event.kind == "effect.applied" and _integer(event.values.get("stacks")) <= 0:
                continue
            if event.kind in _TRIGGER_OUTCOME_KINDS:
                return index
            if event.kind == "effect.applied" and _integer(event.values.get("stacks")) > 0:
                fallback = fallback if fallback is not None else index
            if event.kind == "resource.changed" and fallback is None:
                fallback = index
            if event.kind == "effect.applied":
                continue
        return fallback

    def _damage_summary(self, source, target, values):
        by_type = defaultdict(float)
        total = 0.0
        health = 0.0
        shield = 0.0
        for _index, event in values:
            amount = _float(event.values.get("effective_damage"))
            by_type[self.context.subject(event, "伤害", compact=True)] += amount
            total += amount
            health += _float(event.values.get("health_damage"))
            shield += _float(event.values.get("shield_damage"))
        source_label = self.context.actor(source)
        target_label = self.context.actor(target)
        if len(by_type) == 1:
            damage_type, amount = next(iter(by_type.items()))
            text = f"{source_label} 对 {target_label} 造成 {_number(amount)} 点{damage_type}"
        else:
            breakdown = "、".join(
                f"{name} {_number(amount)}"
                for name, amount in by_type.items()
            )
            text = f"{source_label} 对 {target_label} 共造成 {_number(total)} 点伤害：{breakdown}"
        if shield > 0:
            breakdown = []
            if health > 0:
                health_name = self.context.term(
                    target,
                    str(HEALTH_CURRENT),
                    "生命",
                    compact=True,
                )
                breakdown.append(f"{health_name} {_number(health)}")
            shield_name = self.context.term(
                target,
                str(SHIELD_CURRENT),
                "护盾",
                compact=True,
            )
            breakdown.append(f"{shield_name} {_number(shield)}")
            text += f"（{'，'.join(breakdown)}）"
        return {
            "kind": "combat.damage.summary",
            "label": "伤害结算",
            "tone": "damage",
            "category": "damage",
            "text": text,
            "source": {"key": source, "label": source_label},
            "target": {"key": target, "label": target_label},
            "visual": dict(self.visuals.get(source, _SYSTEM_VISUAL)),
        }

    def _frame(self, frame: StoredBattleFrame, title: str) -> dict[str, object]:
        facts = [_fact("状态", _STATUS_NAMES[frame.status])]
        if frame.current_actor_key:
            facts.append(_fact("当前行动者", self.context.actor(frame.current_actor_key)))
        if frame.turn_order_keys:
            facts.append(
                _fact(
                    "行动顺序",
                    [self.context.actor(value) for value in frame.turn_order_keys],
                )
            )
        if frame.inactive_keys:
            facts.append(
                _fact(
                    "失去行动能力",
                    [self.context.actor(value) for value in frame.inactive_keys],
                )
            )
        if frame.winning_team_ids:
            facts.append(
                _fact(
                    "胜方",
                    [self.context.team(value) for value in frame.winning_team_ids],
                )
            )
        return {
            "title": title,
            "round_turn_label": f"第 {frame.round_number} 回合 / 行动 {frame.turn_number}",
            "facts": facts,
            "participants": [
                self._participant(value, detail=True)
                for value in frame.participants
            ],
        }

    def _state_changes(
        self,
        before: StoredBattleFrame | None,
        after: StoredBattleFrame,
    ) -> list[dict[str, str]]:
        if before is None:
            return [
                {"text": f"{self.context.actor(value.key)} 加入战场", "tone": "system"}
                for value in after.participants
            ]
        old = {value.key: value for value in before.participants}
        new = {value.key: value for value in after.participants}
        rows = []
        for key, current in new.items():
            previous = old.get(key)
            if previous is None:
                rows.append({"text": f"{self.context.actor(key)} 加入战场", "tone": "system"})
                continue
            changes = self._participant_changes(previous, current)
            if changes:
                rows.append(
                    {
                        "text": f"{self.context.actor(key)}：{'；'.join(changes)}",
                        "tone": "change",
                    }
                )
        for key in old.keys() - new.keys():
            rows.append({"text": f"{self.context.actor(key)} 离开战场", "tone": "system"})
        return rows

    def _participant_changes(self, before, after):
        changes = []
        for values_before, values_after in (
            (before.resources, after.resources),
            (before.attributes, after.attributes),
        ):
            for content_id in sorted(set(values_before) | set(values_after)):
                old = values_before.get(content_id)
                new = values_after.get(content_id)
                if old == new:
                    continue
                label = self.context.term(after.key, content_id, "战斗数值", compact=True)
                changes.append(f"{label} {_number(old)} -> {_number(new)}")
        old_effects = {value.key: value for value in before.effects}
        new_effects = {value.key: value for value in after.effects}
        for key, effect in new_effects.items():
            previous = old_effects.get(key)
            name = self.context.term(effect.source_key, effect.definition_id, "战斗效果")
            if previous is None:
                changes.append(f"获得{name}")
            elif previous.stacks != effect.stacks:
                changes.append(f"{name}层数 {previous.stacks} -> {effect.stacks}")
            elif previous.remaining_turns != effect.remaining_turns:
                changes.append(
                    f"{name}持续 {_duration_value(previous.remaining_turns)} -> "
                    f"{_duration_value(effect.remaining_turns)}"
                )
        for key, effect in old_effects.items():
            if key not in new_effects:
                name = self.context.term(effect.source_key, effect.definition_id, "战斗效果")
                changes.append(f"失去{name}")
        for content_id in sorted(set(before.cooldowns) | set(after.cooldowns)):
            old = before.cooldowns.get(content_id, 0)
            new = after.cooldowns.get(content_id, 0)
            if old != new:
                name = self.context.term(after.key, content_id, "未命名招式")
                changes.append(f"{name}冷却 {old} -> {new}")
        return changes


def build_public_battle_report(
    report: BattleReportView,
    *,
    segment_index: int = 0,
    segment_count: int | None = None,
) -> dict[str, object]:
    """建立轻量首包；报告中携带的片段按给定公开序号投影。"""

    total = len(report.segments) if segment_count is None else segment_count
    segments = [
        PublicBattleReportProjector(segment).compact_segment(
            segment_index=segment_index + offset,
            segment_count=total,
        )
        for offset, segment in enumerate(report.segments)
    ]
    document = {
        "schema": PUBLIC_BATTLE_REPORT_SCHEMA,
        "version": PUBLIC_BATTLE_REPORT_VERSION,
        "ui": {
            "text": dict(_UI),
            "modes": [dict(value) for value in _MODE_OPTIONS],
            "filters": [dict(value) for value in _FILTER_OPTIONS],
            "snapshots": [dict(value) for value in _SNAPSHOT_OPTIONS],
        },
        "summary": {
            "title": report.summary.title,
            "outcome": report.summary.outcome,
            "tone": report.summary.tone,
            "lines": list(report.summary.lines),
        },
        "started_at": report.started_at.isoformat(),
        "finished_at": report.finished_at.isoformat(),
        "detail": {
            "available": report.detail_available,
            "retention_notice": (
                "完整行动保留 3 小时；当前仅保留本场结算摘要。"
                if not report.detail_available
                else ""
            ),
            "segment_count": total,
            "segments": segments,
        },
    }
    validate_public_battle_report(document)
    return document


def build_public_battle_events(
    segment: StoredBattleSegment,
    *,
    segment_index: int,
) -> dict[str, object]:
    return PublicBattleReportProjector(segment).events(segment_index=segment_index)


def build_public_battle_participants(
    segment: StoredBattleSegment,
    *,
    segment_index: int,
    snapshot: str,
) -> dict[str, object]:
    return PublicBattleReportProjector(segment).participants(
        segment_index=segment_index,
        snapshot=snapshot,
    )


def build_public_battle_transition(
    segment: StoredBattleSegment,
    *,
    segment_index: int,
    sequence: int,
) -> dict[str, object]:
    return PublicBattleReportProjector(segment).transition(
        segment_index=segment_index,
        sequence=sequence,
    )


def build_public_battle_raw(
    segment: StoredBattleSegment,
    *,
    segment_index: int,
) -> dict[str, object]:
    return PublicBattleReportProjector(segment).raw(segment_index=segment_index)


def validate_public_battle_report(value: object) -> None:
    """在发送前阻断平台请求身份和内部投影字段回流。"""

    forbidden_keys = {
        "content_fingerprint",
        "mode_id",
        "projection",
        "segment_id",
        "share_id",
    }

    def visit(item: object, path: str) -> None:
        if isinstance(item, Mapping):
            leaked = forbidden_keys.intersection(str(key) for key in item)
            if leaked:
                raise RuntimeError(
                    f"公共战报包含内部字段 {sorted(leaked)} at {path}"
                )
            for key, nested in item.items():
                visit(nested, f"{path}.{key}")
            return
        if isinstance(item, (tuple, list, set, frozenset)):
            for index, nested in enumerate(item):
                visit(nested, f"{path}[{index}]")
            return
        if isinstance(item, str) and any(
            marker.casefold() in item.casefold()
            for marker in _FORBIDDEN_PUBLIC_MARKERS
        ):
            raise RuntimeError(f"公共战报包含平台请求身份 at {path}")

    visit(value, "$.")


def _actor_visuals(segment: StoredBattleSegment):
    result = {}
    used = set()
    for index, combatant in enumerate(segment.combatants):
        color = _actor_color(index)
        if color in used:
            raise RuntimeError("战报角色颜色发生重复")
        used.add(color)
        result[combatant.key] = MappingProxyType(
            {
                "key": combatant.key,
                "number": index + 1,
                "color": color,
                "foreground": _foreground(color),
            }
        )
    return MappingProxyType(result)


def _actor_color(index: int) -> str:
    if index < len(_BASE_ACTOR_COLORS):
        return _BASE_ACTOR_COLORS[index]
    hue = ((index - len(_BASE_ACTOR_COLORS)) * 137.507764 + 18) % 360
    lightness = 0.43 + ((index // 24) % 3) * 0.05
    red, green, blue = hls_to_rgb(hue / 360, lightness, 0.74)
    return f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"


def _foreground(color: str) -> str:
    red, green, blue = (int(color[index:index + 2], 16) for index in (1, 3, 5))
    luminance = (red * 299 + green * 587 + blue * 114) / 1000
    return "#17231d" if luminance >= 155 else "#ffffff"


def _compact_event(value: Mapping[str, object]) -> dict[str, object]:
    return {
        key: value[key]
        for key in (
            "kind",
            "label",
            "tone",
            "category",
            "text",
            "source",
            "target",
            "visual",
        )
        if key in value
    }


def _transient_effect_indexes(
    events: tuple[StoredBattleEvent, ...],
) -> set[int]:
    """隐藏同一行动内施加后立即结束的载体 Effect；完整事件仍按原样保留。"""

    applied: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    terminal: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, event in enumerate(events):
        identity = (event.source, event.target, event.subject)
        if event.kind == "effect.applied":
            applied[identity].append(index)
        elif event.kind in {"effect.expired", "effect.removed"}:
            terminal[identity].append(index)
    consumed = set()
    for identity in applied.keys() & terminal.keys():
        endings = terminal[identity]
        ending_offset = 0
        for start in applied[identity]:
            while ending_offset < len(endings) and endings[ending_offset] < start:
                ending_offset += 1
            if ending_offset >= len(endings):
                break
            consumed.update({start, endings[ending_offset]})
            ending_offset += 1
    return consumed


def _transition_round(transition: StoredBattleTransition) -> int:
    if transition.kind == "turn" and transition.before is not None:
        return transition.before.round_number
    return transition.after.round_number


def _dominant_tone(events):
    priorities = ("damage", "status", "resource", "system")
    categories = {str(value["category"]) for value in events}
    return next((value for value in priorities if value in categories), "system")


def _group(group_id, label, items):
    if not items:
        return None
    return {
        "id": group_id,
        "label": label,
        "presentation": "list",
        "items": items,
    }


def _item(identifier, label, display, *, value=None):
    result = {"id": str(identifier), "label": str(label), "display": str(display)}
    if value is not None:
        result["value"] = value
    return result


def _dedupe_items(items):
    result = []
    seen = set()
    for item in items:
        identity = (item.get("label"), item.get("display"), item.get("tone"))
        if identity in seen:
            continue
        seen.add(identity)
        result.append(item)
    return result


def _fact(label, value):
    return {"label": label, "value": value, "display": _plain_display(value)}


def _plain_display(value):
    if isinstance(value, (tuple, list)):
        return "、".join(_plain_display(item) for item in value)
    if isinstance(value, Mapping):
        return "、".join(
            f"{key}={_plain_display(item)}" for key, item in value.items()
        )
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return _number(value)
    return "" if value is None else str(value)


def _attribute_display(content_id: str, value: float) -> str:
    if content_id in _PERCENTAGE_ATTRIBUTE_IDS:
        return f"{_number(value * 100)}%"
    return _number(value)


def _duration_value(value):
    return "永久" if value is None else f"{value} 回合"


def _duration_label(started_at: datetime, finished_at: datetime) -> str:
    seconds = (finished_at - started_at).total_seconds()
    if seconds <= 0:
        return ""
    if seconds < 60:
        return f"用时 {_number(seconds)} 秒"
    return f"用时 {_number(seconds / 60)} 分钟"


def _float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _integer(value):
    return int(_float(value))


def _number(value):
    number = _float(value)
    return str(round(number)) if number.is_integer() else f"{number:.2f}".rstrip("0").rstrip(".")


__all__ = [
    "PublicBattleReportProjector",
    "build_public_battle_events",
    "build_public_battle_participants",
    "build_public_battle_raw",
    "build_public_battle_report",
    "build_public_battle_transition",
    "validate_public_battle_report",
]
