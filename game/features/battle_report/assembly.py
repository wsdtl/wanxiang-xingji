"""把任意 BattleTrace 装配成自解释、冻结现场的战报片段。"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from game.core.gameplay import (
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    COMBAT_SPEED,
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    SPIRIT_MAXIMUM,
    STANDARD_LOADOUT_SLOT_ORDER,
    WEAPON_SLOT_ID,
    ContributionSpec,
    InscriptionPreference,
    InscriptionProjector,
    equipment_state_from_instance,
    weapon_state_from_instance,
    WeaponContributionProvider,
)
from game.content.catalog.combat.stats import SHIELD_CURRENT
from game.rules.companion.models import CompanionInstance, CompanionTrace
from game.rules.battle_report import (
    BattleReportCombatantDraft,
    BattleReportGear,
    BattleReportSegmentDraft,
    BattleReportTerm,
    BattleSnapshotProjector,
)


TermResolver = Callable[[str], BattleReportTerm]


@dataclass(frozen=True)
class BattleCombatantSpec:
    """玩法提供的参战者身份；数值状态始终来自 BattleTrace。"""

    entity_id: str
    label: str
    team_id: str
    team_label: str
    unit_kind: str
    projection_kind: str
    projection_id: str
    projection_version: int
    resolve_term: TermResolver = field(compare=False, repr=False)
    source_ids: tuple[str, ...] = ()
    gear: tuple[BattleReportGear, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "entity_id",
            "label",
            "team_id",
            "team_label",
            "unit_kind",
            "projection_kind",
            "projection_id",
        ):
            if not str(getattr(self, field_name) or "").strip():
                raise ValueError(f"战报参战者规格缺少 {field_name}")
        if self.projection_version < 1:
            raise ValueError("战报参战者规格版本必须大于 0")


class BattleReportBuilder:
    """所有战斗模式共用的唯一战报装配器和参战者工厂。"""

    def __init__(self, content, world_views) -> None:
        self.content = content
        self.world_views = world_views
        self.snapshot = BattleSnapshotProjector(
            content.catalog.enemy_projector.attributes,
            self._effect_polarity,
        )
        self._weapon_contributions = WeaponContributionProvider(
            content.catalog.weapons
        )

    def character(
        self,
        character,
        character_world,
        inventory,
        loadout,
        *,
        team_id: str,
        team_label: str,
        inscription_preference: InscriptionPreference | None = None,
    ) -> BattleCombatantSpec:
        """按角色开战时所在世界冻结术语、配装和铭刻最终名称。"""

        view = self.world_views.require(character_world.world_id)
        overrides: dict[str, BattleReportTerm] = {}
        source_ids = list(loadout.slots.values())
        gear = []
        equipment_states = []
        inscription = InscriptionProjector(inscription_preference)
        for slot_id in STANDARD_LOADOUT_SLOT_ORDER:
            asset_id = loadout.slots.get(slot_id)
            if asset_id is None:
                continue
            instance = inventory.instances[asset_id]
            if slot_id == WEAPON_SLOT_ID:
                state = weapon_state_from_instance(instance)
                display = view.gear_projector.weapon(
                    state,
                    instance,
                    inscription_preference=inscription_preference,
                )
                contribution = self._weapon_contributions.contribution(state)
                for ability_id in contribution.contribution.abilities:
                    base_name = view.projector.name(ability_id)
                    final_name = inscription.weapon_ability_name(
                        base_name,
                        instance,
                        ability_id,
                    )
                    overrides[str(ability_id)] = BattleReportTerm(final_name)
            else:
                state = equipment_state_from_instance(instance)
                equipment_states.append(state)
                display = view.gear_projector.equipment(
                    state,
                    instance,
                    inscription_preference=inscription_preference,
                )
            overrides[str(state.definition_id)] = BattleReportTerm(display.name)
            gear.append(
                BattleReportGear(
                    str(slot_id),
                    view.projector.name(slot_id),
                    display.name,
                )
            )
        source_ids.extend(
            str(state.set_id)
            for state in equipment_states
            if state.set_id is not None
        )
        return self._skin_spec(
            entity_id=character.id,
            label=character.name,
            team_id=team_id,
            team_label=team_label,
            unit_kind="character",
            projection_kind="character_world",
            world_id=character_world.world_id,
            overrides=overrides,
            source_ids=tuple(source_ids),
            gear=tuple(gear),
        )

    def enemy(
        self,
        enemy,
        source_world_id,
        label: str,
        *,
        team_id: str,
        team_label: str,
        unit_kind: str = "enemy",
    ) -> BattleCombatantSpec:
        """敌人只按自身来源世界解释，不读取任何玩家所在世界。"""

        view = self.world_views.require(source_world_id)
        definition = self.content.catalog.enemies.require(enemy.definition_id)
        rank = self.content.catalog.enemies.ranks.require(enemy.rank_id)
        empty = ContributionSpec()
        mechanisms = [
            (f"{label}·固有能力", definition.base_contribution),
            (
                view.projector.name(rank.id)
                if rank.contribution != empty
                else "",
                rank.contribution,
            ),
        ]
        for behavior_id in enemy.behavior_ids:
            behavior = self.content.catalog.enemies.behaviors.require(behavior_id)
            mechanisms.append(
                (
                    (
                        view.projector.name(behavior_id)
                        if behavior.contribution != empty
                        else ""
                    ),
                    behavior.contribution,
                )
            )
        overrides = {
            f"enemy.source_{index}": BattleReportTerm(name)
            for index, (name, contribution) in enumerate(mechanisms)
            if contribution != empty
        }
        for phase in enemy.phase_loadouts:
            overrides[str(phase.id)] = BattleReportTerm(f"{label}·阶段能力")
        return self._skin_spec(
            entity_id=enemy.id,
            label=label,
            team_id=team_id,
            team_label=team_label,
            unit_kind=unit_kind,
            projection_kind="enemy_world",
            world_id=source_world_id,
            overrides=overrides,
        )

    def world_actor(
        self,
        entity_id: str,
        label: str,
        world_id,
        *,
        team_id: str,
        team_label: str,
        unit_kind: str,
    ) -> BattleCombatantSpec:
        """用于没有正式 EnemyInstance 的合成世界来源单位。"""

        return self._skin_spec(
            entity_id=entity_id,
            label=label,
            team_id=team_id,
            team_label=team_label,
            unit_kind=unit_kind,
            projection_kind="enemy_world",
            world_id=world_id,
        )

    def companion(
        self,
        companion: CompanionInstance | CompanionTrace,
        *,
        team_id: str,
        team_label: str,
        unit_kind: str = "companion",
        entity_id: str | None = None,
        label_prefix: str = "",
    ) -> BattleCombatantSpec:
        """伙伴身份和全部战斗术语永久绑定自身来源世界。"""

        definition = self.content.companions.require_definition(
            companion.definition_id
        )
        if isinstance(companion, CompanionInstance):
            origin_world_id = companion.origin_world_id
            default_entity_id = companion.id
            if origin_world_id != definition.origin_world_id:
                raise ValueError("伙伴实例来源世界与内容定义不一致")
        elif isinstance(companion, CompanionTrace):
            origin_world_id = definition.origin_world_id
            if not str(entity_id or "").strip():
                raise ValueError("伙伴踪迹进入战报时必须提供战斗实体 ID")
            default_entity_id = str(entity_id).strip()
        else:
            raise TypeError("战报伙伴必须是正式实例或秘境踪迹")
        label = f"{str(label_prefix or '').strip()}{definition.name}"
        return self._skin_spec(
            entity_id=entity_id or default_entity_id,
            label=label,
            team_id=team_id,
            team_label=team_label,
            unit_kind=unit_kind,
            projection_kind="companion_origin_world",
            world_id=origin_world_id,
            overrides={
                "companion.contribution.base": BattleReportTerm(
                    f"{label}的基础能力",
                    "基础能力",
                ),
                "companion.contribution.core": BattleReportTerm(
                    f"{label}的核心特性",
                    "核心特性",
                ),
                "companion.contribution.trait": BattleReportTerm(
                    f"{label}的天赋特性",
                    "天赋特性",
                ),
            },
        )

    def segment(
        self,
        *,
        segment_id: str,
        title: str,
        trace,
        combatants: Iterable[BattleCombatantSpec],
        outcome: str,
        started_at,
        finished_at,
    ) -> BattleReportSegmentDraft:
        """从唯一核心轨迹一次性生成清单、状态、来源图和冻结词表。"""

        specs = tuple(combatants)
        by_id = {value.entity_id: value for value in specs}
        if len(by_id) != len(specs):
            raise ValueError("战报装配包含重复参战者")
        trace_ids = _trace_entity_ids(trace)
        if set(by_id) != set(trace_ids):
            missing = sorted(set(trace_ids) - set(by_id))
            extra = sorted(set(by_id) - set(trace_ids))
            raise ValueError(
                f"战报参战者规格与核心轨迹不一致: missing={missing}, extra={extra}"
            )
        source_owners = _source_graph(trace, specs)
        transitions = self.snapshot.transitions(trace, trace_ids)
        initial = tuple(
            self.snapshot.participant(trace.initial_frame.state.entities[entity_id])
            for entity_id in trace_ids
            if entity_id in trace.initial_frame.state.entities
        )
        final = tuple(
            self.snapshot.participant(trace.final_frame.state.entities[entity_id])
            for entity_id in trace_ids
            if entity_id in trace.final_frame.state.entities
        )
        required = _required_terms(
            trace_ids,
            initial,
            final,
            transitions,
            source_owners,
        )
        manifests = tuple(
            BattleReportCombatantDraft(
                entity_id=spec.entity_id,
                label=spec.label,
                team_id=spec.team_id,
                team_label=spec.team_label,
                unit_kind=spec.unit_kind,
                projection_kind=spec.projection_kind,
                projection_id=spec.projection_id,
                projection_version=spec.projection_version,
                terms={
                    content_id: spec.resolve_term(content_id)
                    for content_id in sorted(required[spec.entity_id])
                },
                gear=spec.gear,
                source_ids=tuple(
                    source_id
                    for source_id, owner_id in source_owners.items()
                    if owner_id == spec.entity_id and source_id != spec.entity_id
                ),
            )
            for spec in specs
        )
        return BattleReportSegmentDraft(
            segment_id=segment_id,
            title=title,
            combatants=manifests,
            initial_participants=initial,
            final_participants=final,
            transitions=transitions,
            source_owners=source_owners,
            outcome=outcome,
            started_at=started_at,
            finished_at=finished_at,
        )

    def _skin_spec(
        self,
        *,
        entity_id: str,
        label: str,
        team_id: str,
        team_label: str,
        unit_kind: str,
        projection_kind: str,
        world_id,
        overrides: Mapping[str, BattleReportTerm] | None = None,
        source_ids: tuple[str, ...] = (),
        gear: tuple[BattleReportGear, ...] = (),
    ) -> BattleCombatantSpec:
        view = self.world_views.require(world_id)
        fixed = MappingProxyType(dict(overrides or {}))

        def resolve(content_id: str) -> BattleReportTerm:
            identifier = str(content_id or "").strip()
            if identifier in fixed:
                return fixed[identifier]
            set_id, marker, pieces = identifier.rpartition(".bonus.pieces_")
            if marker and pieces.isdigit():
                try:
                    set_name = view.projector.name(set_id)
                except KeyError:
                    pass
                else:
                    return BattleReportTerm(
                        f"{set_name}·{pieces}件效果",
                        f"{pieces}件效果",
                    )
            try:
                entry = view.projector.entry(identifier)
            except (KeyError, ValueError):
                return _fallback_term(identifier)
            return BattleReportTerm(
                entry.name,
                entry.compact_name or _battle_compact_name(identifier, entry.name),
            )

        return BattleCombatantSpec(
            entity_id=entity_id,
            label=label,
            team_id=team_id,
            team_label=team_label,
            unit_kind=unit_kind,
            projection_kind=projection_kind,
            projection_id=str(world_id),
            projection_version=view.skin.version,
            resolve_term=resolve,
            source_ids=source_ids,
            gear=gear,
        )

    def _effect_polarity(self, effect_id: str) -> str:
        try:
            tags = self.content.catalog.effects.require(effect_id).tags
        except KeyError:
            return "neutral"
        if tags.has("status.negative"):
            return "negative"
        if tags.has("status.positive"):
            return "positive"
        return "neutral"


def _fallback_term(content_id: str) -> BattleReportTerm:
    identifier = str(content_id or "").strip()
    exact = {
        "battle.transition.start": "战斗建立",
        "battle.transition.turn": "行动结算",
        "target.enemy.first": "首个敌方目标",
        "target.enemy.all": "全部敌方目标",
        "target.ally.first": "首个友方目标",
        "target.self": "自身",
    }.get(identifier)
    if exact is not None:
        return BattleReportTerm(exact)
    prefixes = (
        ("ability.", "战斗能力"),
        ("effect.", "战斗效果"),
        ("trigger.", "触发机制"),
        ("interceptor.", "伤害拦截"),
        ("target_constraint.", "目标限制"),
        ("target.", "目标选择"),
        ("ai.", "自动决策"),
        ("damage.", "伤害类型"),
        ("enemy.source_", "固有机制"),
        ("phase.", "阶段机制"),
        ("operation.", "战斗操作"),
    )
    for prefix, name in prefixes:
        if identifier.startswith(prefix):
            return BattleReportTerm(name)
    return BattleReportTerm("战斗机制")


def _battle_compact_name(content_id: str, name: str) -> str:
    identifier = str(content_id)
    if identifier in {
        str(HEALTH_CURRENT),
        str(SPIRIT_CURRENT),
        str(SHIELD_CURRENT),
    }:
        return name.removeprefix("当前")
    if identifier == str(COMBAT_ATTACK):
        return name.removesuffix("力")
    if identifier == str(COMBAT_DEFENSE):
        return name.removeprefix("基础")
    if identifier == str(COMBAT_SPEED):
        return name.removeprefix("行动")
    return name


def _trace_entity_ids(trace) -> tuple[str, ...]:
    values: list[str] = []
    for frame in _trace_frames(trace):
        for entity_id in frame.state.participants:
            if entity_id not in values:
                values.append(entity_id)
    return tuple(values)


def _trace_frames(trace):
    for transition in trace.transitions:
        if transition.before is not None:
            yield transition.before
        yield transition.after


def _source_graph(
    trace,
    specs: tuple[BattleCombatantSpec, ...],
) -> dict[str, str]:
    entity_ids = {value.entity_id for value in specs}
    owners = {value.entity_id: value.entity_id for value in specs}
    ambiguous: set[str] = set()

    def register(source_id: str, owner_id: str) -> None:
        source = str(source_id or "").strip()
        if not source:
            return
        if source in ambiguous:
            return
        previous = owners.get(source)
        if previous is not None and previous != owner_id:
            if source in entity_ids:
                raise ValueError(f"战报实体来源 {source} 不能归属于其他参战者")
            owners.pop(source)
            ambiguous.add(source)
            return
        owners[source] = owner_id

    for spec in specs:
        for source_id in spec.source_ids:
            register(source_id, spec.entity_id)
    for frame in _trace_frames(trace):
        for entity_id, entity in frame.state.entities.items():
            for effect in entity.active_effects:
                if effect.source_id in entity_ids:
                    register(effect.source_id, effect.source_id)
                else:
                    register(effect.source_id, entity_id)
    return owners


def _required_terms(
    entity_ids,
    initial,
    final,
    transitions,
    source_owners,
) -> dict[str, set[str]]:
    result = {
        entity_id: {
            str(HEALTH_CURRENT),
            str(HEALTH_MAXIMUM),
            str(SPIRIT_CURRENT),
            str(SPIRIT_MAXIMUM),
            str(SHIELD_CURRENT),
        }
        for entity_id in entity_ids
    }

    def owner(source_id: str, fallback: str | None = None) -> str | None:
        return source_owners.get(str(source_id or ""), fallback)

    def add(owner_id: str | None, identifiers: Iterable[str]) -> None:
        if owner_id not in result:
            return
        result[owner_id].update(
            identifier
            for value in identifiers
            if (identifier := str(value or "").strip())
        )

    states = [*initial, *final]
    for transition in transitions:
        for frame in (transition.before, transition.after):
            if frame is not None:
                states.extend(frame.participants)
    for participant in states:
        identifiers = [
            *participant.attributes,
            *participant.resources,
            *participant.abilities,
            *participant.cooldowns,
            *participant.triggers,
            *participant.interceptors,
            *participant.target_constraints,
        ]
        add(participant.entity_id, identifiers)
        for effect in participant.effects:
            add(owner(effect.source_id, participant.entity_id), (effect.definition_id,))
    for transition in transitions:
        actor = owner(transition.actor_entity_id or "")
        add(
            actor,
            (
                transition.subject_id,
                transition.ability_id or "",
                transition.decision_rule_id or "",
                transition.requested_selector_id or "",
                *transition.action_context_tags,
            ),
        )
        add(actor, _content_identifiers(transition.action_parameters))
        for event in transition.events:
            source = owner(event.source_id)
            target = owner(event.target_id)
            add(source, (str(event.subject_id),))
            add(target, (str(event.subject_id),))
            identifiers = tuple(_content_identifiers(event.values))
            add(source, identifiers)
            add(target, identifiers)
    return result


def _content_identifiers(value: object):
    if isinstance(value, Mapping):
        for key in value:
            if isinstance(key, str) and "." in key and ":" not in key:
                yield key
        for item in value.values():
            yield from _content_identifiers(item)
        return
    if isinstance(value, (tuple, list, set, frozenset)):
        for item in value:
            yield from _content_identifiers(item)
        return
    if isinstance(value, str) and "." in value and ":" not in value:
        yield value


__all__ = ["BattleCombatantSpec", "BattleReportBuilder"]
