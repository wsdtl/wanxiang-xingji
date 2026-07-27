"""把正式战斗定义投影为玩家可读的机制详情。"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping

from game.core.gameplay.abilities import EffectTarget
from game.core.gameplay.attributes import (
    AttributeMagnitude,
    ClampMagnitude,
    EffectStacksMagnitude,
    FixedMagnitude,
    MaximumMagnitude,
    MinimumMagnitude,
    ModifierLayer,
    ParameterMagnitude,
    PowerMagnitude,
    ProductMagnitude,
    RatioMagnitude,
    ResourceMagnitude,
    ResourceValueMode,
    SumMagnitude,
)
from game.core.gameplay.combat.control import ApplyControl
from game.core.gameplay.combat.integration import DealDamage
from game.core.gameplay.combat.recovery import GrantShield, Heal
from game.core.gameplay.combat.targeting import TargetConstraintKind
from game.core.gameplay.combat.timeline_operations import (
    RequestExtraTurn,
    RequestInterrupt,
    RequestTurnDelay,
)
from game.core.gameplay.conditions import (
    AttributeCondition,
    Comparison,
    ConditionSubject,
    EffectStacksCondition,
    EventValueCondition,
    ResourceRatioCondition,
    TagCondition,
)
from game.core.gameplay.content.assembler import ContentRuntime
from game.core.gameplay.content.skins import SkinProjector
from game.core.gameplay.effects import (
    ChangeResource,
    ChooseOne,
    ConsumeEffectStacks,
    DispelEffects,
    EffectDefinition,
    GrantAbility,
    GrantInterceptor,
    GrantTag,
    GrantTargetConstraint,
    GrantTrigger,
    ModifyAttribute,
    ModifyCooldown,
    ModifyCurrentCooldowns,
    ModifyEffectDuration,
    StackingPolicy,
    TransferResource,
)
from game.core.gameplay.itemization.models import (
    PropertyDefinition,
    PropertyParameterDefinition,
    PropertyTierDefinition,
)
from game.core.gameplay.triggers import (
    TriggerDefinition,
    TriggerOwner,
    TriggerSource,
    TriggerTarget,
)


_CATEGORY_ORDER = {
    "武器核心": 0,
    "武器词条": 1,
    "装备特效": 2,
    "装备词条": 3,
    "套装效果": 4,
    "能力": 5,
}

_EVENT_LABELS = {
    ("combat.attack.hit", TriggerOwner.EVENT_SOURCE): "自身攻击命中后",
    ("combat.attack.hit", TriggerOwner.EVENT_TARGET): "自身受到命中后",
    ("combat.attack.critical", TriggerOwner.EVENT_SOURCE): "自身攻击造成暴击后",
    ("combat.attack.critical", TriggerOwner.EVENT_TARGET): "自身受到暴击后",
    ("combat.attack.missed", TriggerOwner.EVENT_SOURCE): "自身攻击被闪避后",
    ("combat.attack.missed", TriggerOwner.EVENT_TARGET): "自身成功闪避攻击后",
    ("combat.attack.blocked", TriggerOwner.EVENT_SOURCE): "自身攻击被格挡后",
    ("combat.attack.blocked", TriggerOwner.EVENT_TARGET): "自身成功格挡攻击后",
    ("combat.damage.dealt", TriggerOwner.EVENT_SOURCE): "自身造成实际伤害后",
    ("combat.damage.dealt", TriggerOwner.EVENT_TARGET): "自身受到实际伤害后",
    ("combat.healing.resolved", TriggerOwner.EVENT_SOURCE): "自身造成有效治疗后",
    ("combat.healing.resolved", TriggerOwner.EVENT_TARGET): "自身获得有效治疗后",
    ("combat.shield.broken", TriggerOwner.EVENT_SOURCE): "自身击破护盾后",
    ("combat.shield.broken", TriggerOwner.EVENT_TARGET): "自身护盾被击破后",
    ("combat.target.defeated", TriggerOwner.EVENT_SOURCE): "自身击败目标后",
    ("combat.target.defeated", TriggerOwner.EVENT_TARGET): "自身被击败后",
    ("combat.turn.started", TriggerOwner.EVENT_SOURCE): "自身回合开始时",
    ("combat.turn.started", TriggerOwner.EVENT_TARGET): "自身回合开始时",
}

_COMPARISONS = {
    Comparison.EQUAL: "等于",
    Comparison.NOT_EQUAL: "不等于",
    Comparison.LESS: "低于",
    Comparison.LESS_OR_EQUAL: "不高于",
    Comparison.GREATER: "高于",
    Comparison.GREATER_OR_EQUAL: "不低于",
}

_TARGETING_LABELS = {
    frozenset({"target.enemy.explicit", "target.enemy.first"}): "单个敌人",
    frozenset({"target.enemy.lowest_health"}): "当前{health}最低的敌人",
    frozenset({"target.enemy.random"}): "随机一个敌人",
    frozenset({"target.enemy.adjacent"}): "选定敌人及其相邻目标，最多 3 个",
    frozenset({"target.enemy.all"}): "全体敌人",
}


class MechanicPresentationError(ValueError):
    """正式规则缺少玩家可读投影时立即失败。"""


@dataclass(frozen=True)
class MechanicCatalogEntry:
    id: str
    name: str
    category: str
    description: str


@dataclass(frozen=True)
class MechanicTierDetail:
    label: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class MechanicDetail:
    id: str
    name: str
    category: str
    description: str
    tiers: tuple[MechanicTierDetail, ...]


class MechanicProjector:
    """组合世界皮肤名称与冻结后的正式规则定义。"""

    def __init__(self, catalog: ContentRuntime, projector: SkinProjector) -> None:
        self.catalog = catalog
        self.projector = projector
        self.properties = catalog.itemization_engine.catalog.properties
        profile = catalog.combat_profiles.require(catalog.report.active_combat_profile_id)
        self.health_resource_id = profile.combat_stats.health_resource
        self.shield_resource_id = profile.combat_stats.shield_resource
        health = catalog.resources[self.health_resource_id]
        self.health_maximum_attribute_id = health.maximum_attribute
        if self.health_maximum_attribute_id is None:
            raise MechanicPresentationError("当前战斗配置缺少生命上限属性")

    def catalog_entries(self) -> tuple[MechanicCatalogEntry, ...]:
        entries = [
            MechanicCatalogEntry(
                str(definition.id),
                self._name(definition.id),
                self._property_category(definition),
                self._description(definition.id),
            )
            for definition in self.properties.values()
        ]
        entries.extend(
            MechanicCatalogEntry(
                str(definition.id),
                self._name(definition.id),
                "套装效果",
                self._description(definition.id),
            )
            for definition in self.catalog.equipment.sets
        )
        return tuple(
            sorted(
                entries,
                key=lambda value: (
                    _CATEGORY_ORDER[value.category],
                    value.name,
                    value.id,
                ),
            )
        )

    def resolve(self, value: object) -> str | None:
        token = self._query_token(value)
        if not token:
            return None
        resolved = self._supported_content_id(token)
        if resolved is not None:
            return resolved
        content_id = self.projector.resolve_alias(token)
        resolved = self._supported_content_id(content_id)
        if resolved is not None:
            return resolved
        normalized = self._normalize(token)
        for entry in self.catalog_entries():
            if self._normalize(entry.name) == normalized:
                return entry.id
        for ability_id in self.catalog.abilities.ids():
            if self._normalize(self._name(ability_id)) == normalized:
                return str(ability_id)
        return None

    def detail(self, content_id: object) -> MechanicDetail:
        key = str(content_id or "").strip()
        if key in self.properties:
            return self._property_detail(self.properties[key])
        if self.catalog.equipment.sets.contains(key):
            return self._set_detail(key)
        if self.catalog.abilities.contains(key):
            return self._ability_detail(key)
        if self.catalog.enemies.behaviors.contains(key):
            return self._behavior_detail(key)
        supported = self._supported_content_id(key)
        if supported is not None and supported != key:
            return self.detail(supported)
        raise KeyError("没有找到这个机制")

    def roll_lines(
        self,
        property_id: object,
        tier_number: int,
        values: Mapping[object, float],
    ) -> tuple[str, ...]:
        definition = self._property(property_id)
        tier = self._tier(definition, tier_number)
        normalized = {str(key): float(value) for key, value in values.items()}
        if not tier.parameters:
            return ()
        expected = {str(parameter.id) for parameter in tier.parameters}
        if set(normalized) != expected:
            raise MechanicPresentationError(f"{self._name(definition.id)} 的实际数值与正式档位不一致")
        return tuple(
            f"{self._name(parameter.attribute_id)} "
            f"{self._format_value(normalized[str(parameter.id)], parameter, signed=True)}"
            for parameter in tier.parameters
        )

    def roll_summary(
        self,
        property_id: object,
        tier_number: int,
        values: Mapping[object, float],
    ) -> str:
        return "、".join(self.roll_lines(property_id, tier_number, values))

    def _property_detail(self, definition: PropertyDefinition) -> MechanicDetail:
        category = self._property_category(definition)
        tiers = tuple(
            MechanicTierDetail(
                "固定机制" if category == "武器核心" and len(definition.tiers) == 1 else f"T{tier.tier}",
                self._property_tier_lines(tier),
            )
            for tier in sorted(definition.tiers, key=lambda value: value.tier)
        )
        description = self._description(definition.id)
        if category == "武器核心":
            ability_ids = tuple(definition.tiers[0].contribution.abilities)
            if ability_ids:
                description = self._description(ability_ids[0]) or description
        return MechanicDetail(
            str(definition.id),
            self._name(definition.id),
            category,
            description,
            tiers,
        )

    def _set_detail(self, set_id: str) -> MechanicDetail:
        definition = self.catalog.equipment.sets.require(set_id)
        tiers = tuple(
            MechanicTierDetail(
                f"{bonus.required_pieces} 件",
                self._contribution_lines(bonus.contribution),
            )
            for bonus in definition.bonuses
        )
        return MechanicDetail(
            set_id,
            self._name(set_id),
            "套装效果",
            self._description(set_id),
            tiers,
        )

    def _ability_detail(self, ability_id: str) -> MechanicDetail:
        return MechanicDetail(
            ability_id,
            self._name(ability_id),
            "能力",
            self._description(ability_id),
            (
                MechanicTierDetail(
                    "固定机制",
                    self._ability_lines(ability_id, include_name=False),
                ),
            ),
        )

    def _behavior_detail(self, behavior_id: str) -> MechanicDetail:
        definition = self.catalog.enemies.behaviors.require(behavior_id)
        lines = [
            f"{self._name(attribute_id)}倍率：{self._number(multiplier)} 倍"
            for attribute_id, multiplier in sorted(definition.attribute_multipliers.items())
        ]
        lines.extend(self._contribution_lines(definition.contribution))
        if not lines:
            raise MechanicPresentationError("战斗机制没有可展示的正式规则")
        return MechanicDetail(
            behavior_id,
            self._name(behavior_id),
            "战斗机制",
            self._description(behavior_id),
            (MechanicTierDetail("固定机制", tuple(lines)),),
        )

    def _property_tier_lines(self, tier: PropertyTierDefinition) -> tuple[str, ...]:
        lines = [self._parameter_range(parameter) for parameter in tier.parameters]
        lines.extend(self._contribution_lines(tier.contribution))
        if not lines:
            raise MechanicPresentationError("机制档位没有可展示的正式规则")
        return tuple(lines)

    def _contribution_lines(self, contribution) -> tuple[str, ...]:
        lines: list[str] = []
        for grant in contribution.attributes:
            lines.append(self._attribute_grant(grant))
        for ability_id in sorted(contribution.abilities):
            lines.extend(self._ability_lines(ability_id))
        for trigger_id in sorted(contribution.triggers):
            lines.extend(self._trigger_lines(self.catalog.triggers.require(trigger_id)))
        for interceptor_id in sorted(contribution.interceptors):
            lines.append(self._interceptor_text(interceptor_id))
        for constraint_id in sorted(contribution.target_constraints):
            lines.append(self._constraint_text(constraint_id))
        return tuple(lines)

    def _ability_lines(
        self,
        ability_id: object,
        *,
        include_name: bool = True,
    ) -> tuple[str, ...]:
        ability = self.catalog.abilities.require(str(ability_id))
        lines = [f"能力：{self._name(ability.id)}"] if include_name else []
        for cost in ability.costs:
            lines.append(
                "消耗："
                + self._amount_text(
                    cost.magnitude,
                    self._resource_name(cost.resource_id),
                )
            )
        lines.append("冷却：无" if ability.cooldown_turns == 0 else f"冷却：自身行动 {ability.cooldown_turns} 次")
        targeting = self.catalog.battle_ability_targeting.get(ability.id)
        if targeting is not None:
            try:
                target = _TARGETING_LABELS[frozenset(targeting.allowed_selectors)].format(
                    health=self._resource_name(self.health_resource_id)
                )
            except KeyError as exc:
                raise MechanicPresentationError(f"{self._name(ability.id)} 缺少目标规则说明") from exc
            lines.append(f"目标：{target}")
        lines.extend(self._condition_lines(ability.conditions))
        lines.extend(self._condition_lines(ability.target_conditions))
        for reference in ability.effects:
            target = "自身" if reference.target is EffectTarget.SELF else "目标"
            for line in self._effect_lines(
                self.catalog.effects.require(reference.effect_id),
                visited=frozenset(),
                source_label="自身",
                target_label=target,
            ):
                lines.append(f"{target}效果：{line}")
        return tuple(lines)

    def _trigger_lines(
        self,
        trigger: TriggerDefinition,
        *,
        visited: frozenset[str] = frozenset(),
    ) -> tuple[str, ...]:
        if trigger.id in visited:
            raise MechanicPresentationError(f"{self._name(trigger.id)} 的展示引用形成循环")
        key = (str(trigger.event_kind), trigger.owner)
        try:
            event_label = _EVENT_LABELS[key]
        except KeyError as exc:
            raise MechanicPresentationError(f"{self._name(trigger.id)} 缺少事件说明") from exc
        lines = [
            f"触发时机：{event_label}",
            f"作用对象：{self._trigger_target(trigger)}",
            f"触发概率：{self._percent(trigger.chance)}",
        ]
        lines.extend(self._condition_lines(trigger.conditions))
        if trigger.max_activations_per_execution == 1:
            lines.append("触发限制：单次机制结算最多触发 1 次")
        elif trigger.max_activations_per_execution < 64:
            lines.append(f"触发限制：单次机制结算最多触发 {trigger.max_activations_per_execution} 次")
        next_visited = visited | {str(trigger.id)}
        for line in self._effect_lines(
            self.catalog.effects.require(trigger.effect_id),
            visited=next_visited,
            source_label=self._trigger_source(trigger),
            target_label=self._trigger_target(trigger),
        ):
            lines.append(f"效果：{line}")
        return tuple(lines)

    def _effect_lines(
        self,
        effect: EffectDefinition,
        *,
        visited: frozenset[str],
        source_label: str,
        target_label: str,
    ) -> tuple[str, ...]:
        lines: list[str] = []
        persistent = effect.duration_turns is None or effect.duration_turns > 0
        if persistent:
            status = f"施加“{self._name(effect.id)}”"
            rule = self._effect_rule(effect)
            if rule:
                status += f"（{rule}）"
            lines.append(status)
        lines.extend(self._condition_lines(effect.conditions))
        lines.extend(
            self._collapsed_operation_lines(
                effect.operations,
                visited=visited,
                source_label=source_label,
                target_label=target_label,
            )
        )
        if not effect.operations and not persistent:
            lines.append(f"施加“{self._name(effect.id)}”")
        return tuple(lines)

    def _collapsed_operation_lines(
        self,
        operations,
        *,
        visited: frozenset[str],
        source_label: str,
        target_label: str,
    ) -> tuple[str, ...]:
        """合并连续且展示规则相同的操作，同时明确保留执行次数。"""

        groups = tuple(
            self._operation_lines(
                operation,
                visited=visited,
                source_label=source_label,
                target_label=target_label,
            )
            for operation in operations
        )
        lines: list[str] = []
        index = 0
        while index < len(groups):
            group = groups[index]
            count = 1
            while index + count < len(groups) and groups[index + count] == group:
                count += 1
            if count == 1:
                lines.extend(group)
            elif len(group) == 1 and group[0].startswith("造成"):
                lines.append(f"连续攻击 {count} 次，每次{group[0]}")
            else:
                lines.append(f"连续执行 {count} 次：{'；'.join(group)}")
            index += count
        return tuple(lines)

    def _operation_lines(
        self,
        operation: object,
        *,
        visited: frozenset[str],
        source_label: str,
        target_label: str,
    ) -> tuple[str, ...]:
        if isinstance(operation, DealDamage):
            text = self._action_amount_text(
                "造成",
                operation.magnitude,
                self._name(operation.damage_type),
                source_label=source_label,
                target_label=target_label,
            )
            limits = []
            if not operation.can_miss:
                limits.append("必定命中")
            if not operation.can_critical:
                limits.append("不可暴击")
            if not operation.can_block:
                limits.append("不可格挡")
            if operation.bypass_shield:
                limits.append("无视护盾")
            if operation.minimum_damage is not None:
                limits.append(f"最低 {self._number(operation.minimum_damage)} 点")
            if operation.maximum_damage is not None:
                limits.append(f"最高 {self._number(operation.maximum_damage)} 点")
            if operation.maximum_target_health_ratio is not None:
                limits.append(
                    f"单次伤害不超过{target_label}"
                    f"{self._name(self.health_maximum_attribute_id)}的 "
                    f"{self._percent(operation.maximum_target_health_ratio)}"
                )
            if limits:
                text += f"（{'，'.join(limits)}）"
            return (text,)
        if isinstance(operation, Heal):
            return (
                self._action_amount_text(
                    "恢复",
                    operation.magnitude,
                    self._resource_name(self.health_resource_id),
                    source_label=source_label,
                    target_label=target_label,
                ),
            )
        if isinstance(operation, GrantShield):
            if self.shield_resource_id is None:
                raise MechanicPresentationError("当前战斗配置缺少护盾资源")
            text = self._action_amount_text(
                "获得",
                operation.magnitude,
                self._resource_name(self.shield_resource_id),
                source_label=source_label,
                target_label=target_label,
            )
            if operation.maximum_target_health_ratio is not None:
                text += (
                    f"，最多不超过{target_label}"
                    f"{self._name(self.health_maximum_attribute_id)}的 "
                    f"{self._percent(operation.maximum_target_health_ratio)}"
                )
            return (text,)
        if isinstance(operation, ChangeResource):
            direction = self._magnitude_direction(operation.magnitude)
            verb = "消耗" if direction < 0 else "恢复" if direction > 0 else "改变"
            return (
                self._action_amount_text(
                    verb,
                    operation.magnitude,
                    self._resource_name(operation.resource_id),
                    absolute=direction < 0,
                    source_label=source_label,
                    target_label=target_label,
                ),
            )
        if isinstance(operation, TransferResource):
            text = self._action_amount_text(
                f"从{target_label}抽取",
                operation.magnitude,
                self._resource_name(operation.resource_id),
                source_label=source_label,
                target_label=target_label,
            )
            if operation.efficiency != 1:
                text += f"，{source_label}获得其中 {self._percent(operation.efficiency)}"
            return (text,)
        if isinstance(operation, ModifyAttribute):
            direction = self._magnitude_direction(operation.magnitude)
            verb = "降低" if direction < 0 else "提高" if direction > 0 else "调整"
            return (
                f"{verb}{self._name(operation.attribute_id)} "
                f"{self._magnitude(operation.magnitude, absolute=direction < 0, as_rate=self._is_rate_attribute(operation.attribute_id), source_label=source_label, target_label=target_label)}",
            )
        if isinstance(operation, ApplyControl):
            definition = self.catalog.controls.require(operation.control_id)
            return (
                f"尝试施加“{self._name(operation.control_id)}”"
                f"（基础成功率 {self._percent(definition.base_chance)}，"
                f"基础持续 {definition.base_duration_turns} 回合；"
                "控制命中、抵抗和韧性参与结算）",
            )
        if isinstance(operation, GrantTrigger):
            trigger = self.catalog.triggers.require(operation.trigger_id)
            lines = [f"获得触发效果“{self._name(trigger.id)}”"]
            lines.extend(f"联动{line}" for line in self._trigger_lines(trigger, visited=visited))
            return tuple(lines)
        if isinstance(operation, GrantInterceptor):
            return (self._interceptor_text(operation.interceptor_id),)
        if isinstance(operation, GrantTargetConstraint):
            return (self._constraint_text(operation.constraint_id),)
        if isinstance(operation, RequestExtraTurn):
            return ("获得 1 次额外行动",)
        if isinstance(operation, RequestTurnDelay):
            return (f"行动顺序向后推 {operation.positions} 位",)
        if isinstance(operation, RequestInterrupt):
            return ("中断当前行动",)
        if isinstance(operation, ModifyCurrentCooldowns):
            target = "全部现有冷却" if operation.selection == "all" else "当前最长冷却"
            verb = "缩短" if operation.turns < 0 else "延长"
            return (f"{verb}{target} {abs(operation.turns)} 回合",)
        if isinstance(operation, ModifyCooldown):
            ability = self._name(operation.ability_id)
            if operation.set_to is not None:
                return (f"将“{ability}”冷却设为 {operation.set_to} 回合",)
            verb = "缩短" if operation.turns < 0 else "延长"
            return (f"{verb}“{ability}”冷却 {abs(operation.turns)} 回合",)
        if isinstance(operation, DispelEffects):
            kind = "状态"
            if operation.required_tags.has("status.positive"):
                kind = "增益状态"
            elif operation.required_tags.has("status.negative"):
                kind = "负面状态"
            if operation.maximum:
                return (f"移除{target_label}最多 {operation.maximum} 个{kind}",)
            return (f"移除{target_label}的全部{kind}",)
        if isinstance(operation, ConsumeEffectStacks):
            return (f"消耗“{self._name(operation.effect_id)}” {operation.stacks} 层",)
        if isinstance(operation, ModifyEffectDuration):
            verb = "延长" if operation.turns > 0 else "缩短"
            return (f"{verb}“{self._name(operation.effect_id)}” {abs(operation.turns)} 回合",)
        if isinstance(operation, GrantAbility):
            return (f"获得能力“{self._name(operation.ability_id)}”",)
        if isinstance(operation, GrantTag):
            raise MechanicPresentationError("正式机制的战斗状态标签缺少玩家可读说明")
        if isinstance(operation, ChooseOne):
            total = sum(operation.weights)
            branches = []
            for index, branch in enumerate(operation.branches):
                branch_lines = [
                    line
                    for item in branch
                    for line in self._operation_lines(
                        item,
                        visited=visited,
                        source_label=source_label,
                        target_label=target_label,
                    )
                ]
                chance = operation.weights[index] / total
                branches.append(f"随机分支 {index + 1}（{self._percent(chance)}）：{'；'.join(branch_lines)}")
            return tuple(branches)
        raise MechanicPresentationError(f"正式机制包含尚未支持的展示操作：{type(operation).__name__}")

    def _condition_lines(self, conditions) -> tuple[str, ...]:
        return tuple(self._condition_text(condition) for condition in conditions)

    def _condition_text(self, condition: object) -> str:
        if isinstance(condition, EventValueCondition):
            if condition.key == "is_proc" and condition.comparison is Comparison.EQUAL and float(condition.value) == 0:
                return "条件：只响应直接攻击，追加伤害不会再次触发"
            if condition.key == "actual" and condition.comparison is Comparison.GREATER and float(condition.value) == 0:
                return "条件：本次实际恢复量必须大于 0"
            if (
                condition.key == "damage_type"
                and condition.comparison is Comparison.NOT_EQUAL
                and isinstance(condition.value, str)
            ):
                return f"条件：不响应{self._name(condition.value)}"
            raise MechanicPresentationError("正式机制包含尚未支持的事件条件")
        if isinstance(condition, ResourceRatioCondition):
            return (
                f"条件：{self._condition_subject(condition.subject)}的"
                f"{self._resource_name(condition.resource_id)}比例"
                f"{_COMPARISONS[condition.comparison]} {self._percent(float(condition.value))}"
            )
        if isinstance(condition, AttributeCondition):
            return (
                f"条件：{self._condition_subject(condition.subject)}的"
                f"{self._name(condition.attribute_id)}"
                f"{_COMPARISONS[condition.comparison]} {self._number(condition.value)}"
            )
        if isinstance(condition, EffectStacksCondition):
            return (
                f"条件：{self._condition_subject(condition.subject)}的"
                f"“{self._name(condition.effect_id)}”层数"
                f"{_COMPARISONS[condition.comparison]} {condition.value}"
            )
        if isinstance(condition, TagCondition):
            raise MechanicPresentationError("正式机制的战斗状态条件缺少玩家可读说明")
        raise MechanicPresentationError(f"正式机制包含尚未支持的展示条件：{type(condition).__name__}")

    def _interceptor_text(self, interceptor_id: object) -> str:
        definition = self.catalog.interceptors.require(str(interceptor_id))
        name = self._name(definition.id)
        config = definition.configuration
        if definition.handler_id == "interceptor.death_guard":
            minimum = self._number(float(config.get("minimum_health", 1)))
            return f"获得“{name}”：受到致命伤害后至少保留 {minimum} 点{self._resource_name(self.health_resource_id)}"
        if definition.handler_id == "interceptor.immunity":
            if not definition.required_damage_tags.values and not definition.blocked_damage_tags.values:
                return f"获得“{name}”：免疫受到的所有伤害"
            return f"获得“{name}”：免疫符合条件的伤害"
        if definition.handler_id == "interceptor.cap":
            maximum = self._number(float(config["maximum"]))
            if not definition.required_damage_tags.values and not definition.blocked_damage_tags.values:
                return f"获得“{name}”：单次受到的伤害最多结算 {maximum} 点"
            return f"获得“{name}”：单次符合条件的伤害最多结算 {maximum} 点"
        if definition.handler_id == "interceptor.bypass_shield":
            return f"获得“{name}”：符合条件的伤害无视护盾"
        if definition.handler_id == "interceptor.multiply":
            return f"获得“{name}”：符合条件的伤害按 {self._percent(float(config['multiplier']))} 结算"
        if definition.handler_id == "interceptor.flat":
            return f"获得“{name}”：符合条件的伤害调整 {self._number(float(config['amount']), signed=True)} 点"
        if definition.handler_id == "interceptor.convert":
            return f"获得“{name}”：将符合条件的伤害转换为{self._name(str(config['damage_type']))}"
        if definition.handler_id == "interceptor.redirect_to_grant_source":
            return f"获得“{name}”：将符合条件的伤害中的 {self._percent(float(config['ratio']))} 转移给效果来源"
        raise MechanicPresentationError(f"{name} 缺少伤害干预说明")

    def _constraint_text(self, constraint_id: object) -> str:
        definition = self.catalog.target_constraints.require(str(constraint_id))
        name = self._name(definition.id)
        if definition.kind is TargetConstraintKind.FORCE_GRANT_SOURCE:
            return f"获得“{name}”：敌方单体行动必须以效果施加者为目标"
        if definition.kind is TargetConstraintKind.UNTARGETABLE:
            return f"获得“{name}”：自身不会成为敌方单体行动的目标"
        raise MechanicPresentationError(f"{name} 缺少目标规则说明")

    def _effect_rule(self, effect: EffectDefinition) -> str:
        if effect.duration_turns == 0:
            return ""
        rules = ["永久生效" if effect.duration_turns is None else f"持续 {effect.duration_turns} 回合"]
        if effect.stacking is StackingPolicy.STACK:
            rules.append(f"最多叠加 {effect.max_stacks} 层")
        elif effect.stacking is StackingPolicy.REFRESH:
            rules.append("重复施加时刷新持续时间")
        elif effect.stacking is StackingPolicy.INDEPENDENT:
            rules.append("每次施加独立存在")
        elif effect.duration_turns not in (None, 0):
            rules.append("重复施加时覆盖原效果")
        if effect.stack_by_source:
            rules.append("不同来源分别计算")
        return "，".join(rules)

    def _trigger_target(self, trigger: TriggerDefinition) -> str:
        if trigger.target is TriggerTarget.OWNER:
            return "自身"
        if (trigger.target is TriggerTarget.EVENT_SOURCE and trigger.owner is TriggerOwner.EVENT_SOURCE) or (
            trigger.target is TriggerTarget.EVENT_TARGET and trigger.owner is TriggerOwner.EVENT_TARGET
        ):
            return "自身"
        if trigger.target is TriggerTarget.EVENT_SOURCE:
            return "本次事件来源"
        return "本次事件目标"

    @staticmethod
    def _trigger_source(trigger: TriggerDefinition) -> str:
        if trigger.source is TriggerSource.OWNER:
            return "自身"
        if trigger.source is TriggerSource.GRANT_SOURCE:
            return "效果施加者"
        if (trigger.source is TriggerSource.EVENT_SOURCE and trigger.owner is TriggerOwner.EVENT_SOURCE) or (
            trigger.source is TriggerSource.EVENT_TARGET and trigger.owner is TriggerOwner.EVENT_TARGET
        ):
            return "自身"
        if trigger.source is TriggerSource.EVENT_SOURCE:
            return "本次事件来源"
        return "本次事件目标"

    def _attribute_grant(self, grant) -> str:
        verb = "降低" if grant.value < 0 else "提高"
        value = abs(float(grant.value))
        return f"{verb}{self._name(grant.attribute_id)} {self._format_attribute_value(grant.attribute_id, value)}"

    def _parameter_range(self, parameter: PropertyParameterDefinition) -> str:
        minimum = self._format_value(parameter.minimum, parameter, signed=True)
        maximum = self._format_value(parameter.maximum, parameter, signed=True)
        step = self._format_value(parameter.step, parameter, signed=False)
        return f"{self._name(parameter.attribute_id)}：{minimum} 至 {maximum}，步长 {step}"

    def _format_value(
        self,
        value: float,
        parameter: PropertyParameterDefinition,
        *,
        signed: bool,
    ) -> str:
        if self._is_rate_parameter(parameter):
            return self._percent(value, signed=signed)
        return self._number(value, signed=signed)

    def _amount_text(
        self,
        magnitude: object,
        unit: str,
        *,
        absolute: bool = False,
        source_label: str = "自身",
        target_label: str = "目标",
    ) -> str:
        amount = self._magnitude(
            magnitude,
            absolute=absolute,
            source_label=source_label,
            target_label=target_label,
        )
        if isinstance(magnitude, FixedMagnitude):
            return f"{amount} 点{unit}"
        if isinstance(magnitude, SumMagnitude):
            amount = f"（{amount}）"
        return f"相当于{amount}的{unit}"

    def _action_amount_text(
        self,
        action: str,
        magnitude: object,
        unit: str,
        *,
        absolute: bool = False,
        source_label: str,
        target_label: str,
    ) -> str:
        amount = self._amount_text(
            magnitude,
            unit,
            absolute=absolute,
            source_label=source_label,
            target_label=target_label,
        )
        separator = " " if isinstance(magnitude, FixedMagnitude) else ""
        return f"{action}{separator}{amount}"

    def _magnitude(
        self,
        magnitude: object,
        *,
        absolute: bool = False,
        as_rate: bool = False,
        source_label: str = "自身",
        target_label: str = "目标",
    ) -> str:
        if isinstance(magnitude, FixedMagnitude):
            value = abs(magnitude.value) if absolute else magnitude.value
            return self._percent(value) if as_rate else self._number(value)
        if isinstance(magnitude, AttributeMagnitude):
            subject = source_label if magnitude.owner == "source" else target_label
            base = f"{subject}{self._name(magnitude.attribute_id)}"
            return self._scaled_magnitude_text(
                base,
                magnitude.scale,
                magnitude.offset,
                absolute=absolute,
            )
        if isinstance(magnitude, ParameterMagnitude):
            labels = {
                "event.effective_damage": "本次实际伤害",
                "event.actual": "本次实际恢复量",
                "effect.stacks": "当前效果层数",
            }
            try:
                base = labels[magnitude.key]
            except KeyError as exc:
                raise MechanicPresentationError("正式机制包含尚未支持的事件数值") from exc
            return self._scaled_magnitude_text(
                base,
                magnitude.scale,
                magnitude.offset,
                absolute=absolute,
            )
        if isinstance(magnitude, ResourceMagnitude):
            subject = source_label if magnitude.owner == "source" else target_label
            resource = self._resource_name(magnitude.resource_id)
            base = {
                ResourceValueMode.CURRENT: f"{subject}当前{resource}",
                ResourceValueMode.MISSING: f"{subject}已损失的{resource}",
                ResourceValueMode.RATIO: f"{subject}当前{resource}比例",
                ResourceValueMode.MISSING_RATIO: f"{subject}已损失的{resource}比例",
            }[magnitude.mode]
            return self._scaled_magnitude_text(
                base,
                magnitude.scale,
                magnitude.offset,
                absolute=absolute,
            )
        if isinstance(magnitude, EffectStacksMagnitude):
            subject = source_label if magnitude.owner == "source" else target_label
            base = f"{subject}“{self._name(magnitude.effect_id)}”的层数"
            return self._scaled_magnitude_text(
                base,
                magnitude.scale,
                magnitude.offset,
                absolute=absolute,
            )
        if isinstance(magnitude, SumMagnitude):
            return " + ".join(
                self._magnitude(
                    value,
                    source_label=source_label,
                    target_label=target_label,
                )
                for value in magnitude.terms
            )
        if isinstance(magnitude, ProductMagnitude):
            return " × ".join(
                self._magnitude(
                    value,
                    source_label=source_label,
                    target_label=target_label,
                )
                for value in magnitude.factors
            )
        if isinstance(magnitude, MinimumMagnitude):
            return (
                "以下数值中的较低值（"
                + "、".join(
                    self._magnitude(
                        value,
                        source_label=source_label,
                        target_label=target_label,
                    )
                    for value in magnitude.values
                )
                + "）"
            )
        if isinstance(magnitude, MaximumMagnitude):
            return (
                "以下数值中的较高值（"
                + "、".join(
                    self._magnitude(
                        value,
                        source_label=source_label,
                        target_label=target_label,
                    )
                    for value in magnitude.values
                )
                + "）"
            )
        if isinstance(magnitude, ClampMagnitude):
            text = self._magnitude(
                magnitude.value,
                source_label=source_label,
                target_label=target_label,
            )
            if magnitude.minimum is not None:
                text += "，最低 " + self._magnitude(
                    magnitude.minimum,
                    source_label=source_label,
                    target_label=target_label,
                )
            if magnitude.maximum is not None:
                text += "，最高 " + self._magnitude(
                    magnitude.maximum,
                    source_label=source_label,
                    target_label=target_label,
                )
            return text
        if isinstance(magnitude, RatioMagnitude):
            return (
                f"{self._magnitude(magnitude.numerator, source_label=source_label, target_label=target_label)} ÷ "
                f"{self._magnitude(magnitude.denominator, source_label=source_label, target_label=target_label)}"
            )
        if isinstance(magnitude, PowerMagnitude):
            return (
                f"{self._magnitude(magnitude.value, source_label=source_label, target_label=target_label)}"
                f" 的 {self._number(magnitude.exponent)} 次方"
            )
        raise MechanicPresentationError(f"正式机制包含尚未支持的数值表达式：{type(magnitude).__name__}")

    def _scaled_magnitude_text(
        self,
        base: str,
        scale: float,
        offset: float,
        *,
        absolute: bool,
    ) -> str:
        scale = abs(scale) if absolute else scale
        text = base if scale == 1 else f"{base} × {self._percent(scale)}"
        if offset > 0:
            text += f" + {self._number(offset)}"
        elif offset < 0:
            text += f" - {self._number(abs(offset))}"
        return text

    @staticmethod
    def _magnitude_direction(magnitude: object) -> int:
        value = None
        if isinstance(magnitude, FixedMagnitude):
            value = magnitude.value
        elif isinstance(magnitude, (AttributeMagnitude, ParameterMagnitude, ResourceMagnitude)):
            value = magnitude.scale
        if value is None or value == 0:
            return 0
        return -1 if value < 0 else 1

    def _format_attribute_value(self, attribute_id: object, value: float) -> str:
        if self._is_rate_attribute(attribute_id):
            return self._percent(value)
        return self._number(value)

    def _is_rate_attribute(self, attribute_id: object) -> bool:
        definition = self.catalog.attributes.get(str(attribute_id))
        if definition is None or definition.maximum is None:
            return False
        minimum = definition.minimum if definition.minimum is not None else 0.0
        return minimum >= -1.0 and definition.maximum <= 3.0

    def _is_rate_parameter(self, parameter: PropertyParameterDefinition) -> bool:
        if parameter.layer is ModifierLayer.LOCAL_FLAT:
            return False
        return max(abs(parameter.minimum), abs(parameter.maximum)) <= 1.0

    def _property_category(self, definition: PropertyDefinition) -> str:
        key = str(definition.id)
        if key.startswith("property.weapon_core."):
            return "武器核心"
        if key.startswith("property.weapon_affix."):
            return "武器词条"
        if key.startswith("property.equipment."):
            return "装备特效" if any(tier.contribution.triggers for tier in definition.tiers) else "装备词条"
        raise MechanicPresentationError("正式随机词条缺少展示分类")

    def _supported_content_id(self, content_id: object | None) -> str | None:
        if content_id is None:
            return None
        key = str(content_id)
        if (
            key in self.properties
            or self.catalog.equipment.sets.contains(key)
            or self.catalog.abilities.contains(key)
            or self.catalog.enemies.behaviors.contains(key)
        ):
            return key
        if key.startswith("weapon."):
            candidate = f"property.weapon_core.{key.removeprefix('weapon.')}"
            return candidate if candidate in self.properties else None
        if key.startswith("item.weapon."):
            candidate = f"property.weapon_core.{key.removeprefix('item.weapon.')}"
            return candidate if candidate in self.properties else None
        return None

    def _property(self, property_id: object) -> PropertyDefinition:
        try:
            return self.properties[str(property_id)]
        except KeyError as exc:
            raise KeyError("没有找到这个机制") from exc

    @staticmethod
    def _tier(definition: PropertyDefinition, tier_number: int) -> PropertyTierDefinition:
        try:
            return next(value for value in definition.tiers if value.tier == tier_number)
        except StopIteration as exc:
            raise KeyError("这个机制没有对应档位") from exc

    def _name(self, content_id: object) -> str:
        try:
            return self.projector.name(str(content_id))
        except KeyError as exc:
            raise MechanicPresentationError("正式机制缺少世界皮肤名称") from exc

    def _resource_name(self, content_id: object) -> str:
        """资源在数量语句中使用名词，避免出现“当前当前生命”。"""

        return self._name(content_id).removeprefix("当前").strip()

    def _description(self, content_id: object) -> str:
        try:
            return self.projector.entry(str(content_id)).description
        except KeyError as exc:
            raise MechanicPresentationError("正式机制缺少世界皮肤条目") from exc

    @staticmethod
    def _condition_subject(subject: ConditionSubject) -> str:
        return "效果来源" if subject is ConditionSubject.SOURCE else "作用目标"

    @staticmethod
    def _query_token(value: object) -> str:
        token = " ".join(str(value or "").strip().split())
        token = re.sub(r"\s+T\d+\s*$", "", token, flags=re.IGNORECASE)
        token = re.sub(r"\s+固定机制\s*$", "", token)
        return token.strip()

    @staticmethod
    def _normalize(value: object) -> str:
        return " ".join(str(value or "").strip().casefold().split())

    @staticmethod
    def _number(value: float, *, signed: bool = False) -> str:
        number = float(value)
        if abs(number) < 1e-12:
            number = 0.0
        text = f"{number:+.4f}" if signed else f"{number:.4f}"
        return text.rstrip("0").rstrip(".")

    @classmethod
    def _percent(cls, value: float, *, signed: bool = False) -> str:
        return f"{cls._number(float(value) * 100.0, signed=signed)}%"


__all__ = [
    "MechanicCatalogEntry",
    "MechanicDetail",
    "MechanicPresentationError",
    "MechanicProjector",
    "MechanicTierDetail",
]
