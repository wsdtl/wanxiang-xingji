"""把冻结战斗事实投影成 Web 只需逐节点渲染的公共文档。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from game.content.catalog.combat.stats import SHIELD_CURRENT
from game.core.gameplay import (
    BattleStatus,
    COMBAT_DEFENSE,
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    SPIRIT_MAXIMUM,
)
from game.rules.battle_report import (
    KNOWN_BATTLE_EVENT_KINDS,
    BattleReportView,
    StoredBattleCombatant,
    StoredBattleEffect,
    StoredBattleEvent,
    StoredBattleFrame,
    StoredBattleParticipant,
    StoredBattleSegment,
    StoredBattleTransition,
)


PUBLIC_BATTLE_REPORT_SCHEMA = "game.battle_report.presentation"
PUBLIC_BATTLE_REPORT_VERSION = 3

# 公共事实采用逐事件允许列表。核心以后新增任何审计字段时，默认不会外发。
_EVENT_VALUE_KEYS = {
    "ability.completed": frozenset({"interrupted"}),
    "ability.cooldown_changed": frozenset({"before", "after", "delta"}),
    "ability.cooldown_started": frozenset({"turns"}),
    "ability.ready": frozenset(),
    "ability.started": frozenset(),
    "combat.action.interrupted": frozenset(),
    "combat.attack.blocked": frozenset({"block_reduction"}),
    "combat.attack.critical": frozenset({"critical_multiplier"}),
    "combat.attack.hit": frozenset(),
    "combat.attack.missed": frozenset({"hit_chance"}),
    "combat.battle.finished": frozenset({"reason"}),
    "combat.battle.started": frozenset(),
    "combat.control.resolved": frozenset(
        {"applied", "chance", "duration_turns"}
    ),
    "combat.damage.dealt": frozenset(
        {
            "effective_damage",
            "health_damage",
            "shield_damage",
            "overkill",
        }
    ),
    "combat.damage.intercepted": frozenset(
        {"before_amount", "after_amount"}
    ),
    "combat.damage.prevented": frozenset({"requested_damage"}),
    "combat.damage.redirected": frozenset({"amount"}),
    "combat.healing.resolved": frozenset({"actual", "overheal"}),
    "combat.participant.joined": frozenset(),
    "combat.participant.left": frozenset(),
    "combat.phase.activated": frozenset({"behavior_ids"}),
    "combat.round.started": frozenset({"round"}),
    "combat.shield.broken": frozenset({"shield_damage"}),
    "combat.shield.damaged": frozenset(
        {"shield_damage", "shield_before", "shield_after"}
    ),
    "combat.shield.granted": frozenset({"actual", "before", "after"}),
    "combat.target.defeated": frozenset({"overkill"}),
    "combat.target.revived": frozenset({"current"}),
    "combat.timeline.delay_requested": frozenset({"positions"}),
    "combat.timeline.extra_turn_requested": frozenset(),
    "combat.turn.ended": frozenset({"round", "turn", "skipped"}),
    "combat.turn.skipped": frozenset({"reason"}),
    "combat.turn.started": frozenset({"round", "turn"}),
    "effect.applied": frozenset({"stacks"}),
    "effect.application.rejected": frozenset({"reason"}),
    "effect.choice.selected": frozenset({"branch"}),
    "effect.duration_changed": frozenset({"remaining_turns", "delta"}),
    "effect.expired": frozenset(),
    "effect.removed": frozenset({"reason"}),
    "effect.stacks_changed": frozenset({"stacks", "delta"}),
    "resource.changed": frozenset({"delta", "current"}),
    "resource.transferred": frozenset(
        {"drained", "received", "overflow", "efficiency"}
    ),
    "trigger.activated": frozenset({"chance"}),
}

_FACT_LABELS = {
    "raw": "原始值",
    "requested_damage": "请求伤害",
    "effective_damage": "有效伤害",
    "overkill": "溢出伤害",
    "defense_multiplier": "防御倍率",
    "rate_multiplier": "伤害倍率",
    "hit_chance": "命中率",
    "hit_roll": "命中判定",
    "critical_chance": "暴击率",
    "critical_roll": "暴击判定",
    "critical_multiplier": "暴击倍率",
    "block_chance": "格挡率",
    "block_roll": "格挡判定",
    "block_reduction": "格挡减免",
    "delta": "变化量",
    "current": "当前值",
    "requested": "请求值",
    "actual": "实际值",
    "overheal": "溢出恢复",
    "chance": "成功率",
    "roll": "判定值",
    "duration_turns": "持续回合",
    "remaining_turns": "剩余回合",
    "turns": "回合",
    "stacks": "层数",
    "removed_stacks": "移除层数",
    "before": "变化前",
    "after": "变化后",
    "before_amount": "拦截前",
    "after_amount": "拦截后",
    "amount": "数值",
    "positions": "后移位数",
    "threshold": "阶段阈值",
    "health_ratio": "当前生命资源比例",
    "behavior_count": "新增能力数",
    "behavior_ids": "新增能力",
    "drained": "转移数值",
    "received": "获得数值",
    "overflow": "溢出数值",
    "efficiency": "转化效率",
    "applied": "是否生效",
    "branch": "分支",
    "reason": "原因",
    "failure_code": "失败码",
    "conditions": "未满足条件",
    "round": "回合",
    "turn": "行动",
    "modified": "修正后数值",
    "multiplier": "倍率",
}

_STATUS_NAMES = {
    BattleStatus.ACTIVE.value: "进行中",
    BattleStatus.FINISHED.value: "已经结束",
    BattleStatus.DRAW.value: "平局结束",
}

_UI = {
    "brand_suffix": "公开战报",
    "settlement_label": "结算",
    "archive_kicker": "公开档案",
    "archive_title": "完整战报已归档",
    "more_summary": "更多结算",
    "segment_label": "战斗片段",
    "segment_select_label": "选择战斗片段",
    "previous_segment_label": "上一片段",
    "next_segment_label": "下一片段",
    "participant_panel_title": "参与者状态",
    "comparison_title": "行动前后状态",
    "comparison_empty": "本次行动没有可见状态变化。",
    "process_group_label": "过程记录",
    "raw_data_label": "原始数据",
    "event_facts_label": "事件事实",
    "empty_timeline": "本片段没有可展示的行动事实。",
    "empty_filter": "当前筛选下没有事件。",
    "empty_participants": "本片段没有参与者快照。",
    "empty_value": "无",
    "undecided_value": "未决",
    "none_actor": "无",
    "other_team_label": "其他阵营",
    "additional_team_template": "另有 {count} 方",
}

_MODE_OPTIONS = (
    {"id": "compact", "label": "战斗记录"},
    {"id": "detail", "label": "全部事件"},
)

_FILTER_OPTIONS = (
    {"id": "all", "label": "全部"},
    {"id": "damage", "label": "伤害"},
    {"id": "status", "label": "状态与控制"},
    {"id": "resource", "label": "资源与恢复"},
    {"id": "system", "label": "过程"},
)

_SNAPSHOT_OPTIONS = (
    {"id": "before", "label": "战前"},
    {"id": "after", "label": "战后"},
)


@dataclass(frozen=True)
class EventPresentationContext:
    combatants: Mapping[str, StoredBattleCombatant]

    def actor(self, key: str, fallback: str = "战场") -> str:
        combatant = self.combatants.get(str(key or ""))
        return combatant.label if combatant is not None else fallback

    def team(self, team_id: str) -> str:
        for combatant in self.combatants.values():
            if combatant.team_id == team_id:
                return combatant.team_label
        return str(team_id or "") or "未知阵营"

    def term(
        self,
        owner_key: str | None,
        content_id: str,
        fallback: str,
        *,
        compact: bool = False,
    ) -> str:
        identifier = str(content_id or "").strip()
        if not identifier:
            return fallback
        if identifier in self.combatants:
            return self.actor(identifier, fallback)
        combatant = self.combatants.get(str(owner_key or ""))
        if combatant is None:
            return fallback
        value = combatant.terms.get(identifier)
        if value is None:
            raise RuntimeError(
                f"战报参战者 {combatant.key} 缺少冻结术语: {identifier}"
            )
        return value.compact_name if compact else value.name

    def subject(
        self,
        event: StoredBattleEvent,
        fallback: str = "战斗机制",
        *,
        owner: str = "source",
        compact: bool = False,
    ) -> str:
        owner_key = event.target if owner == "target" else event.source
        return self.term(owner_key, event.subject, fallback, compact=compact)


EventTextRenderer = Callable[[StoredBattleEvent, EventPresentationContext], str]


@dataclass(frozen=True)
class EventPresentationDescriptor:
    kind: str
    label: str
    tone: str
    category: str
    compact_visible: bool
    subject_owner: str
    render: EventTextRenderer


class BattleEventPresentationRegistry:
    """事件事实到完整玩家可见语义的唯一注册表。"""

    def __init__(self) -> None:
        self._entries: dict[str, EventPresentationDescriptor] = {}

    def register(
        self,
        kind: str,
        *,
        label: str,
        tone: str,
        category: str,
        compact_visible: bool,
        render: EventTextRenderer,
        subject_owner: str = "source",
    ) -> None:
        event_kind = str(kind or "").strip()
        if not all((event_kind, label.strip(), tone.strip(), category.strip())):
            raise ValueError("战报事件展示注册缺少类型、名称、语气或类别")
        if subject_owner not in {"source", "target"}:
            raise ValueError("战报事件主题归属必须是 source 或 target")
        if event_kind in self._entries:
            raise ValueError(f"战报事件展示重复注册: {event_kind}")
        self._entries[event_kind] = EventPresentationDescriptor(
            event_kind,
            label.strip(),
            tone.strip(),
            category.strip(),
            bool(compact_visible),
            subject_owner,
            render,
        )

    @property
    def registered_kinds(self) -> frozenset[str]:
        return frozenset(self._entries)

    def present(
        self,
        event: StoredBattleEvent,
        context: EventPresentationContext,
    ) -> dict[str, object]:
        try:
            descriptor = self._entries[event.kind]
        except KeyError as exc:
            raise RuntimeError(f"战报事件没有展示注册: {event.kind}") from exc
        public_values = _public_values(event.kind, event.values)
        subject = context.subject(
            event,
            owner=descriptor.subject_owner,
        )
        return {
            "kind": event.kind,
            "label": descriptor.label,
            "tone": descriptor.tone,
            "category": descriptor.category,
            "text": descriptor.render(event, context),
            "source": {"key": event.source, "label": context.actor(event.source)},
            "target": {"key": event.target, "label": context.actor(event.target)},
            "subject": {"id": event.subject, "label": subject},
            "phase": event.phase,
            "logical_time": event.logical_time.isoformat(),
            "facts": _fact_entries(event, public_values, context),
        }


class BattleReportPresenter:
    """后端完成全部战斗解释，公共文档不要求浏览器理解战斗。"""

    def __init__(self, event_registry: BattleEventPresentationRegistry) -> None:
        self.event_registry = event_registry

    def build(self, report: BattleReportView) -> dict[str, object]:
        return {
            "schema": PUBLIC_BATTLE_REPORT_SCHEMA,
            "version": PUBLIC_BATTLE_REPORT_VERSION,
            "share_id": report.share_id,
            "mode_id": report.mode_id,
            "content_fingerprint": report.content_fingerprint,
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
                "segments": [self._segment(value) for value in report.segments],
            },
        }

    def _segment(self, segment: StoredBattleSegment) -> dict[str, object]:
        combatants = {value.key: value for value in segment.combatants}
        context = EventPresentationContext(MappingProxyType(combatants))
        initial = [
            self._participant(value, context)
            for value in segment.initial_participants
        ]
        final = [
            self._participant(value, context)
            for value in segment.final_participants
        ]
        return {
            "id": segment.segment_id,
            "title": segment.title,
            "outcome": segment.outcome,
            "started_at": segment.started_at.isoformat(),
            "finished_at": segment.finished_at.isoformat(),
            "duration_label": _duration_label(
                segment.started_at,
                segment.finished_at,
            ),
            "combatants": [self._combatant(value) for value in segment.combatants],
            "initial_participants": initial,
            "final_participants": final,
            "timeline": [
                self._transition(value, context)
                for value in segment.transitions
            ],
        }

    @staticmethod
    def _combatant(combatant: StoredBattleCombatant) -> dict[str, object]:
        return {
            "key": combatant.key,
            "label": combatant.label,
            "team_id": combatant.team_id,
            "team_label": combatant.team_label,
            "unit_kind": combatant.unit_kind,
            "projection": {
                "kind": combatant.projection_kind,
                "id": combatant.projection_id,
                "version": combatant.projection_version,
            },
            "gear": [
                {
                    "slot_id": value.slot_id,
                    "slot_label": value.slot_name,
                    "label": value.name,
                }
                for value in combatant.gear
            ],
        }

    def _transition(
        self,
        transition: StoredBattleTransition,
        context: EventPresentationContext,
    ) -> dict[str, object]:
        events = [
            self.event_registry.present(event, context)
            for event in transition.events
        ]
        categories = tuple(dict.fromkeys(event["category"] for event in events))
        before = (
            self._frame(transition.before, context, "动作前完整状态")
            if transition.before is not None
            else None
        )
        after_title = "战斗建立状态" if transition.kind == "start" else "动作后完整状态"
        after = self._frame(transition.after, context, after_title)
        return {
            "type": "entry",
            "sequence": transition.sequence,
            "title": self._transition_title(transition, context),
            "round_label": f"第 {transition.after.round_number} 回合",
            "sequence_label": (
                f"回合 {transition.after.round_number} · 序列 {transition.sequence}"
            ),
            "tone": _dominant_tone(events),
            "categories": list(categories),
            "facts": self._transition_facts(transition, context),
            "events": events,
            "comparison": {
                "title": _UI["comparison_title"],
                "empty_text": _UI["comparison_empty"],
                "changes": self._state_changes(
                    transition.before,
                    transition.after,
                    context,
                ),
                "before": before,
                "after": after,
            },
        }

    @staticmethod
    def _transition_title(
        transition: StoredBattleTransition,
        context: EventPresentationContext,
    ) -> str:
        actor = context.actor(transition.actor_key or "", "战场")
        if transition.kind == "start":
            return "战斗建立"
        if transition.kind == "turn":
            ability = context.term(
                transition.actor_key,
                transition.ability_id or "",
                "普通行动",
            )
            targets = "、".join(
                context.actor(value, "未知目标")
                for value in transition.resolved_target_keys
            ) or "无目标"
            return f"{actor} 对 {targets} 使用 {ability}"
        names = {
            "join": "参与者加入",
            "withdraw": "参与者退出",
            "external": "外部战斗阶段",
        }
        fallback = names.get(transition.kind, "状态转移")
        subject = context.term(
            transition.actor_key,
            transition.subject_id,
            fallback,
        )
        return f"{fallback} · {subject}"

    @staticmethod
    def _transition_facts(
        transition: StoredBattleTransition,
        context: EventPresentationContext,
    ) -> list[dict[str, object]]:
        facts = [
            _fact("序号", transition.sequence),
            _fact("回合", transition.after.round_number),
            _fact("行动", transition.after.turn_number),
        ]
        owner = transition.actor_key
        if transition.decision_rule_id:
            facts.append(
                _fact(
                    "决策",
                    context.term(owner, transition.decision_rule_id, "自动决策"),
                )
            )
        if transition.requested_selector_id:
            facts.append(
                _fact(
                    "选取",
                    context.term(owner, transition.requested_selector_id, "目标选择"),
                )
            )
        if transition.requested_target_keys:
            facts.append(
                _fact(
                    "请求目标",
                    [context.actor(value, "未知目标") for value in transition.requested_target_keys],
                )
            )
        if transition.resolved_target_keys:
            facts.append(
                _fact(
                    "实际目标",
                    [context.actor(value, "未知目标") for value in transition.resolved_target_keys],
                )
            )
        if transition.action_parameters:
            facts.append(_fact("参数", dict(sorted(transition.action_parameters.items()))))
        if transition.action_context_tags:
            facts.append(
                _fact(
                    "上下文",
                    [
                        context.term(owner, value, "战斗上下文")
                        for value in transition.action_context_tags
                    ],
                )
            )
        return facts

    def _frame(
        self,
        frame: StoredBattleFrame,
        context: EventPresentationContext,
        title: str,
    ) -> dict[str, object]:
        winners = [context.team(value) for value in frame.winning_team_ids]
        facts = [
            _fact("状态", _STATUS_NAMES.get(frame.status, frame.status)),
            _fact("当前行动者", context.actor(frame.current_actor_key or "", "无")),
            _fact("行动顺序", [context.actor(value, "未知参与者") for value in frame.turn_order_keys]),
            _fact("失去行动能力", [context.actor(value, "未知参与者") for value in frame.inactive_keys]),
            _fact("胜方", winners or "未决"),
            _fact("状态修订", frame.revision),
        ]
        if frame.action_progress:
            facts.append(
                _fact(
                    "行动进度",
                    [
                        f"{context.actor(key, '未知参与者')} {_number(value)}"
                        for key, value in sorted(frame.action_progress.items())
                    ],
                )
            )
        return {
            "title": title,
            "logical_time": frame.logical_time.isoformat(),
            "round": frame.round_number,
            "turn": frame.turn_number,
            "round_turn_label": (
                f"第 {frame.round_number} 回合 / 行动 {frame.turn_number}"
            ),
            "facts": facts,
            "participants": [
                self._participant(value, context)
                for value in frame.participants
            ],
        }

    def _participant(
        self,
        participant: StoredBattleParticipant,
        context: EventPresentationContext,
    ) -> dict[str, object]:
        combatant = context.combatants[participant.key]
        effects = [
            self._effect(value, participant.key, context)
            for value in participant.effects
        ]
        temporary_effects = [
            value for effect, value in zip(participant.effects, effects)
            if effect.remaining_turns is not None
        ]
        permanent_effects = [
            value for effect, value in zip(participant.effects, effects)
            if effect.remaining_turns is None
        ]
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
                    "label": context.term(participant.key, current_id, "当前资源", compact=True),
                    "current": current,
                    "maximum": maximum,
                    "display": f"{_number(current)} / {_number(maximum)}",
                    "tone": tone,
                }
            )
        detail_groups = [
            _group(
                "gear",
                "参战配装",
                [
                    _item(value.slot_id, value.slot_name, value.name)
                    for value in combatant.gear
                ],
            ),
            _group(
                "attributes",
                "属性",
                self._named_values(participant.key, participant.attributes, context),
            ),
            _group(
                "resources",
                "资源",
                self._named_values(participant.key, participant.resources, context),
            ),
            _group(
                "abilities",
                "招式",
                self._named_identifiers(participant.key, participant.abilities, context),
            ),
            _group("permanent_effects", "常驻效果", permanent_effects),
            _group(
                "cooldowns",
                "冷却",
                [
                    _item(
                        ability_id,
                        context.term(participant.key, ability_id, "未命名招式"),
                        f"{turns} 回合",
                    )
                    for ability_id, turns in sorted(participant.cooldowns.items())
                ],
            ),
            _group(
                "triggers",
                "触发机制",
                self._named_identifiers(participant.key, participant.triggers, context),
            ),
            _group(
                "interceptors",
                "拦截机制",
                self._named_identifiers(participant.key, participant.interceptors, context),
            ),
            _group(
                "target_constraints",
                "目标限制",
                self._named_identifiers(
                    participant.key,
                    participant.target_constraints,
                    context,
                ),
            ),
        ]
        return {
            "key": participant.key,
            "label": combatant.label,
            "team_id": combatant.team_id,
            "team_label": combatant.team_label,
            "unit_kind": combatant.unit_kind,
            "projection": {
                "kind": combatant.projection_kind,
                "id": combatant.projection_id,
                "version": combatant.projection_version,
            },
            "gauges": gauges,
            "status_group": {
                "id": "temporary_effects",
                "label": "当前状态",
                "presentation": "chips",
                "empty_text": "当前无持续状态",
                "items": temporary_effects,
            },
            "detail_label": "完整状态",
            "detail_groups": detail_groups,
        }

    @staticmethod
    def _named_values(owner_key, values, context):
        return [
            _item(
                content_id,
                context.term(owner_key, content_id, "未命名数值"),
                _number(value),
                value=value,
            )
            for content_id, value in sorted(values.items())
        ]

    @staticmethod
    def _named_identifiers(owner_key, identifiers, context):
        return [
            _item(
                content_id,
                context.term(owner_key, content_id, "未命名机制"),
                "",
            )
            for content_id in identifiers
        ]

    @staticmethod
    def _effect(
        effect: StoredBattleEffect,
        target_key: str,
        context: EventPresentationContext,
    ) -> dict[str, object]:
        name = context.term(effect.source_key, effect.definition_id, "战斗效果")
        duration = _effect_duration(effect)
        source = context.actor(effect.source_key, "战场")
        metadata = [duration]
        if effect.source_key != target_key:
            metadata.insert(0, f"来源 {source}")
        if effect.stacks > 1:
            metadata.insert(0, f"{effect.stacks} 层")
        return {
            "id": effect.definition_id,
            "key": effect.key,
            "label": name,
            "display": " · ".join(metadata),
            "stacks": effect.stacks,
            "duration": duration,
            "source": source,
            "tone": effect.polarity,
        }

    def _state_changes(
        self,
        before: StoredBattleFrame | None,
        after: StoredBattleFrame,
        context: EventPresentationContext,
    ) -> list[dict[str, str]]:
        if before is None:
            return [
                {
                    "text": f"{context.actor(value.key)} 加入战场",
                    "tone": "system",
                }
                for value in after.participants
            ]
        before_map = {value.key: value for value in before.participants}
        after_map = {value.key: value for value in after.participants}
        rows = []
        for key, current in after_map.items():
            previous = before_map.get(key)
            if previous is None:
                rows.append({"text": f"{context.actor(key)} 加入战场", "tone": "system"})
                continue
            changes = self._participant_changes(previous, current, context)
            if changes:
                rows.append(
                    {
                        "text": f"{context.actor(key)}：{'；'.join(changes)}",
                        "tone": "change",
                    }
                )
        for key in before_map.keys() - after_map.keys():
            rows.append({"text": f"{context.actor(key)} 离开战场", "tone": "system"})
        return rows

    def _participant_changes(self, before, after, context) -> list[str]:
        changes = []
        changes.extend(
            _mapping_changes(before.resources, after.resources, after.key, context)
        )
        changes.extend(
            _mapping_changes(before.attributes, after.attributes, after.key, context)
        )
        changes.extend(self._effect_changes(before.effects, after.effects, after.key, context))
        changes.extend(
            _cooldown_changes(before.cooldowns, after.cooldowns, after.key, context)
        )
        for label, old_values, new_values in (
            ("招式", before.abilities, after.abilities),
            ("触发机制", before.triggers, after.triggers),
            ("拦截机制", before.interceptors, after.interceptors),
            ("目标限制", before.target_constraints, after.target_constraints),
        ):
            changes.extend(
                _identifier_changes(
                    label,
                    old_values,
                    new_values,
                    after.key,
                    context,
                )
            )
        return changes

    @staticmethod
    def _effect_changes(before, after, target_key, context):
        old = {value.key: value for value in before}
        new = {value.key: value for value in after}
        changes = []
        for key, value in new.items():
            previous = old.get(key)
            name = context.term(value.source_key, value.definition_id, "战斗效果")
            if previous is None:
                changes.append(f"获得{name}（{_effect_duration(value)}）")
                continue
            details = []
            if previous.stacks != value.stacks:
                details.append(f"层数 {previous.stacks} -> {value.stacks}")
            if previous.remaining_turns != value.remaining_turns:
                details.append(
                    f"持续 {_duration_value(previous.remaining_turns)} -> "
                    f"{_duration_value(value.remaining_turns)}"
                )
            if details:
                changes.append(f"{name}{'，'.join(details)}")
        for key, value in old.items():
            if key not in new:
                name = context.term(value.source_key, value.definition_id, "战斗效果")
                changes.append(f"失去{name}")
        return changes


def build_public_battle_report(
    report: BattleReportView,
    *,
    event_registry: BattleEventPresentationRegistry | None = None,
) -> dict[str, object]:
    """建立公共战报 v3；默认走轻量、按需加载协议。"""

    if event_registry is not None:
        return BattleReportPresenter(event_registry).build(report)
    from .public_protocol import build_public_battle_report as build_v3

    return build_v3(report)


def present_battle_event(
    event: StoredBattleEvent,
    combatants: Mapping[str, StoredBattleCombatant],
    *,
    event_registry: BattleEventPresentationRegistry | None = None,
) -> dict[str, object]:
    context = EventPresentationContext(MappingProxyType(dict(combatants)))
    return (event_registry or BATTLE_EVENT_PRESENTATIONS).present(event, context)


def resolve_battle_content_name(view, content_id: str, fallback: str) -> str:
    """内容编辑和目录测试使用的单世界名称解析工具。"""

    identifier = str(content_id or "").strip()
    if not identifier:
        return fallback
    set_id, marker, pieces = identifier.rpartition(".bonus.pieces_")
    if marker and pieces.isdigit():
        try:
            return f"{view.projector.name(set_id)}·{pieces}件效果"
        except KeyError:
            pass
    try:
        return view.projector.name(identifier)
    except KeyError:
        return fallback


def _build_event_registry() -> BattleEventPresentationRegistry:
    registry = BattleEventPresentationRegistry()

    def add(
        kind: str,
        label: str,
        tone: str,
        category: str,
        compact_visible: bool,
        render: EventTextRenderer,
        *,
        subject_owner: str = "source",
    ) -> None:
        registry.register(
            kind,
            label=label,
            tone=tone,
            category=category,
            compact_visible=compact_visible,
            subject_owner=subject_owner,
            render=render,
        )

    add("combat.battle.started", "战斗开始", "phase", "system", False, lambda _e, _c: "战斗开始")
    add("combat.round.started", "回合开始", "phase", "system", False, lambda e, _c: f"第 {_number(e.values.get('round'))} 回合")
    add("combat.turn.started", "行动开始", "action", "system", False, lambda e, c: f"第 {_number(e.values.get('turn'))} 次行动，由 {c.actor(e.source)} 出手")
    add("combat.turn.ended", "行动结束", "action", "system", False, lambda e, c: f"{c.actor(e.source)} 结束行动")
    add("combat.turn.skipped", "跳过行动", "control", "status", True, _turn_skipped_text)
    add("ability.started", "发动招式", "action", "system", False, _ability_started_text)
    add("ability.completed", "完成招式", "action", "system", False, _ability_completed_text)
    add("ability.cooldown_started", "进入冷却", "resource", "resource", True, _ability_cooldown_started_text)
    add("ability.cooldown_changed", "冷却变化", "resource", "resource", True, _ability_cooldown_changed_text)
    add("ability.ready", "招式就绪", "resource", "resource", True, lambda e, c: f"{c.subject(e, '招式')} 已可再次使用")
    add("resource.changed", "资源变化", "resource", "resource", True, _resource_changed_text, subject_owner="target")
    add("resource.transferred", "资源转移", "resource", "resource", True, _resource_transferred_text, subject_owner="target")
    add("combat.attack.hit", "攻击命中", "damage", "damage", False, lambda e, c: f"{c.actor(e.source)} 命中 {c.actor(e.target)}")
    add("combat.attack.missed", "攻击落空", "control", "status", True, lambda e, c: f"{c.actor(e.target)} 避开了 {c.actor(e.source)} 的攻击")
    add("combat.attack.critical", "暴击", "damage", "damage", True, _critical_text)
    add("combat.attack.blocked", "格挡", "control", "status", True, lambda e, c: f"{c.actor(e.target)} 格挡了 {c.actor(e.source)} 的攻击")
    add("combat.damage.dealt", "伤害结算", "damage", "damage", True, _damage_dealt_text)
    add("combat.damage.prevented", "伤害化解", "control", "status", True, lambda e, c: f"{c.actor(e.target)} 完全化解了 {c.actor(e.source)} 的伤害")
    add("combat.damage.intercepted", "伤害拦截", "control", "status", True, _damage_intercepted_text)
    add("combat.damage.redirected", "伤害转移", "control", "status", True, _damage_redirected_text)
    add("combat.healing.resolved", "治疗结算", "healing", "resource", True, _healing_text, subject_owner="target")
    add("combat.target.revived", "目标复起", "healing", "resource", True, _target_revived_text, subject_owner="target")
    add("combat.shield.granted", "获得护盾", "healing", "resource", True, _shield_granted_text, subject_owner="target")
    add("combat.shield.damaged", "护盾受击", "damage", "damage", True, _shield_damaged_text, subject_owner="target")
    add("combat.shield.broken", "护盾破碎", "damage", "damage", True, lambda e, c: f"{c.actor(e.target)} 的 {c.term(e.target, str(SHIELD_CURRENT), '护盾', compact=True)}破碎", subject_owner="target")
    add("combat.control.resolved", "控制结算", "control", "status", True, _control_text)
    add("combat.target.defeated", "目标击败", "damage", "damage", True, lambda e, c: f"{c.actor(e.target)} 被击败")
    add("combat.action.interrupted", "行动打断", "control", "status", True, lambda e, c: f"{c.actor(e.target)} 的行动被打断")
    add("combat.timeline.extra_turn_requested", "额外行动", "action", "system", True, lambda e, c: f"{c.actor(e.source)} 获得一次额外行动")
    add("combat.timeline.delay_requested", "行动延后", "control", "status", True, _timeline_delay_text)
    add("effect.applied", "施加效果", "status", "status", True, _effect_applied_text)
    add("effect.application.rejected", "效果未生效", "status", "status", True, _effect_rejected_text)
    add("effect.expired", "效果结束", "status", "status", True, lambda e, c: f"{c.actor(e.target)} 身上的 {c.subject(e)} 结束")
    add("effect.removed", "移除效果", "status", "status", True, lambda e, c: f"{c.actor(e.target)} 身上的 {c.subject(e)} 被移除")
    add("effect.stacks_changed", "层数变化", "status", "status", True, _effect_stacks_text)
    add("effect.duration_changed", "持续变化", "status", "status", True, _effect_duration_text)
    add("effect.choice.selected", "效果分支", "status", "status", True, _effect_choice_text)
    add("trigger.activated", "机制触发", "status", "status", True, lambda e, c: f"{c.actor(e.source)} 的 {c.subject(e, '触发机制')}触发")
    add("combat.participant.joined", "加入战斗", "system", "system", True, lambda e, c: f"{c.actor(e.source)} 加入战斗")
    add("combat.phase.activated", "阶段变化", "phase", "system", True, _phase_activated_text)
    add("combat.participant.left", "退出战斗", "system", "system", True, lambda e, c: f"{c.actor(e.source)} 退出战斗")
    add("combat.battle.finished", "战斗结束", "phase", "system", False, lambda _e, _c: "战斗结束")
    return registry


def _phase_activated_text(event, context):
    behavior_ids = event.values.get("behavior_ids", ())
    if not isinstance(behavior_ids, (tuple, list)) or not behavior_ids:
        return f"{context.actor(event.source)} 进入新的战斗阶段"
    names = [
        context.term(event.source, str(value), "未知能力")
        for value in behavior_ids
    ]
    return f"{context.actor(event.source)} 进入新的战斗阶段，获得{'、'.join(names)}"


def _turn_skipped_text(event, context):
    reason = {
        "defeated": "已经倒下",
        "incapacitated": "无法行动",
        "passed": "放弃行动",
    }.get(str(event.values.get("reason")), "跳过行动")
    return f"{context.actor(event.source)}{reason}"


def _ability_started_text(event, context):
    return f"{context.actor(event.source)} 对 {context.actor(event.target)} 发动 {context.subject(event, '招式')}"


def _ability_completed_text(event, context):
    return f"{context.actor(event.source)} 完成 {context.subject(event, '招式')}"


def _ability_cooldown_started_text(event, context):
    return f"{context.subject(event, '招式')} 进入 {_number(event.values.get('turns'))} 回合冷却"


def _ability_cooldown_changed_text(event, context):
    after = event.values.get("after", event.values.get("turns"))
    return f"{context.subject(event, '招式')} 的冷却调整为 {_number(after)} 回合"


def _resource_changed_text(event, context):
    delta = _float(event.values.get("delta"))
    resource = context.subject(event, "战斗资源", owner="target", compact=True)
    target = context.actor(event.target)
    if delta > 0:
        return f"{target} 恢复 {_number(delta)} 点{resource}"
    if delta < 0:
        return f"{target} 的{resource}减少 {_number(abs(delta))} 点"
    return f"{target} 的{resource}没有变化"


def _resource_transferred_text(event, context):
    target_term = context.term(event.target, event.subject, "资源", compact=True)
    source_term = context.term(event.source, event.subject, "资源", compact=True)
    return (
        f"{context.actor(event.target)} 被转移 {_number(event.values.get('drained'))} 点{target_term}，"
        f"{context.actor(event.source)} 获得 {_number(event.values.get('received'))} 点{source_term}"
    )


def _critical_text(event, context):
    multiplier = event.values.get("critical_multiplier")
    suffix = f"，倍率 {_number(multiplier)}" if multiplier is not None else ""
    return f"{context.actor(event.source)} 触发暴击{suffix}"


def _damage_dealt_text(event, context):
    health = context.term(event.target, str(HEALTH_CURRENT), "生命", compact=True)
    shield = context.term(event.target, str(SHIELD_CURRENT), "护盾", compact=True)
    damage_type = context.subject(event, "伤害", compact=True)
    breakdown = []
    health_damage = _float(event.values.get("health_damage"))
    shield_damage = _float(event.values.get("shield_damage"))
    if health_damage > 0:
        breakdown.append(f"{health} {_number(health_damage)}")
    if shield_damage > 0:
        breakdown.append(f"{shield} {_number(shield_damage)}")
    suffix = f"（{'，'.join(breakdown)}）" if breakdown else ""
    return (
        f"{context.actor(event.source)} 对 {context.actor(event.target)} 造成 "
        f"{_number(event.values.get('effective_damage'))} 点{damage_type}"
        f"{suffix}"
    )


def _damage_intercepted_text(event, context):
    return (
        f"{context.actor(event.target)} 的伤害被拦截："
        f"{_number(event.values.get('before_amount'))} -> "
        f"{_number(event.values.get('after_amount'))}"
    )


def _damage_redirected_text(event, context):
    return f"{context.actor(event.source)} 的 {_number(event.values.get('amount'))} 点伤害转移至 {context.actor(event.target)}"


def _healing_text(event, context):
    resource = context.term(event.target, str(HEALTH_CURRENT), "生命", compact=True)
    return f"{context.actor(event.source)} 为 {context.actor(event.target)} 恢复 {_number(event.values.get('actual'))} 点{resource}"


def _target_revived_text(event, context):
    source = context.actor(event.source)
    target = context.actor(event.target)
    return f"{target}重新投入战斗" if event.source == event.target else f"{source}使{target}重新投入战斗"


def _shield_granted_text(event, context):
    shield = context.term(event.target, str(SHIELD_CURRENT), "护盾", compact=True)
    return f"{context.actor(event.target)} 获得 {_number(event.values.get('actual'))} 点{shield}"


def _shield_damaged_text(event, context):
    shield = context.term(event.target, str(SHIELD_CURRENT), "护盾", compact=True)
    return f"{context.actor(event.target)} 的{shield}承受 {_number(event.values.get('shield_damage'))} 点伤害"


def _control_text(event, context):
    result = "生效" if bool(event.values.get("applied")) else "被抵抗"
    return f"{context.actor(event.source)} 对 {context.actor(event.target)} 施加的 {context.subject(event)}{result}"


def _timeline_delay_text(event, context):
    return f"{context.actor(event.target)} 的行动顺序后移 {_number(event.values.get('positions', 1))} 位"


def _effect_applied_text(event, context):
    stacks = _integer(event.values.get("stacks", 1))
    if stacks <= 0:
        return f"{context.actor(event.target)} 受到 {context.subject(event)} 影响"
    return f"{context.actor(event.target)} 获得 {context.subject(event)}，当前 {stacks} 层"


def _effect_rejected_text(event, context):
    source = context.actor(event.source)
    target = context.actor(event.target)
    subject = context.subject(event)
    reason = str(event.values.get("reason") or "")
    if reason == "control_resisted":
        return f"{target}抵抗了{source}施加的{subject}"
    if reason == "condition_failed":
        return f"{subject}的触发条件未满足，未影响{target}"
    return f"{target}未能获得{subject}" if event.source == event.target else f"{target}未受{source}施加的{subject}影响"


def _effect_stacks_text(event, context):
    return f"{context.actor(event.target)} 的 {context.subject(event)} 调整为 {_number(event.values.get('stacks'))} 层"


def _effect_duration_text(event, context):
    return f"{context.actor(event.target)} 的 {context.subject(event)} 剩余 {_number(event.values.get('remaining_turns'))} 回合"


def _effect_choice_text(event, context):
    return f"{context.actor(event.source)} 的 {context.subject(event)} 选择了第 {_integer(event.values.get('branch')) + 1} 种效果"


def _fact_entries(event, values, context):
    return [
        {
            "key": key,
            "label": _fact_label(event, key, context),
            "value": value,
            "display": _fact_display(event, key, value, context),
        }
        for key, value in values.items()
    ]


def _fact_label(event, key, context):
    def target_term(identifier, fallback):
        return context.term(
            event.target,
            str(identifier),
            fallback,
            compact=True,
        )

    if key == "health_damage":
        return f"{target_term(HEALTH_CURRENT, '生命')}伤害"
    if key == "health_before":
        return f"伤前{target_term(HEALTH_CURRENT, '生命')}"
    if key == "health_after":
        return f"伤后{target_term(HEALTH_CURRENT, '生命')}"
    if key == "shield_damage":
        return f"{target_term(SHIELD_CURRENT, '护盾')}伤害"
    if key == "shield_before":
        return f"伤前{target_term(SHIELD_CURRENT, '护盾')}"
    if key == "shield_after":
        return f"伤后{target_term(SHIELD_CURRENT, '护盾')}"
    if key == "defense":
        return target_term(COMBAT_DEFENSE, "防御")
    if key == "effective_defense":
        return f"有效{target_term(COMBAT_DEFENSE, '防御')}"
    return _FACT_LABELS.get(key, key)


def _fact_display(event, key, value, context):
    if key in {
        "block_reduction",
        "chance",
        "critical_chance",
        "hit_chance",
        "rate_multiplier",
    }:
        return _percentage(value)
    owner = event.target if key in {"conditions"} else event.source
    return _display_value(value, owner, context)


def _display_value(value, owner, context):
    if isinstance(value, Mapping):
        return "、".join(
            f"{key}={_display_value(item, owner, context)}"
            for key, item in value.items()
        ) or "无"
    if isinstance(value, (tuple, list, set, frozenset)):
        return "、".join(_display_value(item, owner, context) for item in value) or "无"
    if isinstance(value, str):
        if value in context.combatants:
            return context.actor(value)
        if "." in value and ":" not in value:
            return context.term(owner, value, value)
        return value or "无"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return "无" if value is None else str(value)


def _mapping_changes(before, after, owner, context):
    changes = []
    for identifier in sorted(set(before) | set(after)):
        old = before.get(identifier)
        new = after.get(identifier)
        if old == new:
            continue
        name = context.term(owner, identifier, "战斗数值", compact=True)
        if old is None:
            changes.append(f"新增{name} {_number(new)}")
        elif new is None:
            changes.append(f"移除{name}（原 {_number(old)}）")
        else:
            changes.append(f"{name} {_number(old)} -> {_number(new)}")
    return changes


def _cooldown_changes(before, after, owner, context):
    changes = []
    for identifier in sorted(set(before) | set(after)):
        old = before.get(identifier, 0)
        new = after.get(identifier, 0)
        if old == new:
            continue
        name = context.term(owner, identifier, "未命名招式")
        changes.append(f"{name}冷却 {old} -> {new}")
    return changes


def _identifier_changes(label, before, after, owner, context):
    old = set(before)
    new = set(after)
    added = [context.term(owner, value, "未命名机制") for value in sorted(new - old)]
    removed = [context.term(owner, value, "未命名机制") for value in sorted(old - new)]
    changes = []
    if added:
        changes.append(f"新增{label} {'、'.join(added)}")
    if removed:
        changes.append(f"失去{label} {'、'.join(removed)}")
    return changes


def _effect_duration(effect):
    return _duration_value(effect.remaining_turns)


def _duration_value(value):
    return "永久" if value is None else f"剩余{value}回合"


def _group(group_id, label, items):
    return {
        "id": group_id,
        "label": label,
        "presentation": "list",
        "empty_text": "无",
        "items": items,
    }


def _item(identifier, label, display, *, value=None):
    result = {"id": str(identifier), "label": str(label), "display": str(display)}
    if value is not None:
        result["value"] = value
    return result


def _fact(label, value):
    return {"label": label, "value": value, "display": _plain_display(value)}


def _plain_display(value):
    if isinstance(value, (tuple, list)):
        return "、".join(_plain_display(item) for item in value) or "无"
    if isinstance(value, Mapping):
        return "、".join(f"{key}={_plain_display(item)}" for key, item in value.items()) or "无"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return _number(value)
    return "无" if value is None or value == "" else str(value)


def _dominant_tone(events):
    priorities = ("damage", "status", "resource", "system")
    categories = {str(value["category"]) for value in events}
    return next((value for value in priorities if value in categories), "system")


def _duration_label(started_at, finished_at):
    seconds = (finished_at - started_at).total_seconds()
    if seconds <= 0:
        return ""
    if seconds < 60:
        return f"用时 {_number(seconds)} 秒"
    return f"用时 {_number(seconds / 60)} 分钟"


def _public_values(kind, values):
    allowed = _EVENT_VALUE_KEYS[kind]
    return {
        str(key): _json_value(value)
        for key, value in values.items()
        if key in allowed
    }


def _json_value(value):
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_value(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


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


def _percentage(value):
    return f"{_number(_float(value) * 100)}%"


BATTLE_EVENT_PRESENTATIONS = _build_event_registry()

if BATTLE_EVENT_PRESENTATIONS.registered_kinds != KNOWN_BATTLE_EVENT_KINDS:
    missing = sorted(KNOWN_BATTLE_EVENT_KINDS - BATTLE_EVENT_PRESENTATIONS.registered_kinds)
    extra = sorted(BATTLE_EVENT_PRESENTATIONS.registered_kinds - KNOWN_BATTLE_EVENT_KINDS)
    raise RuntimeError(f"战报事件展示注册不完整: missing={missing}, extra={extra}")

if frozenset(_EVENT_VALUE_KEYS) != KNOWN_BATTLE_EVENT_KINDS:
    missing = sorted(KNOWN_BATTLE_EVENT_KINDS - frozenset(_EVENT_VALUE_KEYS))
    extra = sorted(frozenset(_EVENT_VALUE_KEYS) - KNOWN_BATTLE_EVENT_KINDS)
    raise RuntimeError(f"战报公共事实白名单不完整: missing={missing}, extra={extra}")

if frozenset(_STATUS_NAMES) != frozenset(value.value for value in BattleStatus):
    raise RuntimeError("战报状态名称没有完整覆盖 BattleStatus")


__all__ = [
    "BATTLE_EVENT_PRESENTATIONS",
    "BattleEventPresentationRegistry",
    "BattleReportPresenter",
    "EventPresentationContext",
    "EventPresentationDescriptor",
    "PUBLIC_BATTLE_REPORT_SCHEMA",
    "PUBLIC_BATTLE_REPORT_VERSION",
    "build_public_battle_report",
    "present_battle_event",
    "resolve_battle_content_name",
]
