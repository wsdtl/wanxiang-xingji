"""正式装备机制词条的单点定义与编译器。"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from game.core.gameplay import (
    COMBAT_ATTACK,
    COMBAT_SPEED,
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    ApplyControl,
    AttributeMagnitude,
    ChangeResource,
    Comparison,
    ConditionSubject,
    DealDamage,
    EffectDefinition,
    EventValueCondition,
    FixedMagnitude,
    GrantInterceptor,
    GrantShield,
    GrantTrigger,
    Heal,
    ModifierLayer,
    ModifyAttribute,
    ModifyCurrentCooldowns,
    ParameterMagnitude,
    ProductMagnitude,
    ResourceRatioCondition,
    StackingPolicy,
    TagSet,
    TriggerDefinition,
    TriggerOwner,
    TriggerSource,
    TriggerTarget,
    ValueVector,
)

from ..combat.stats import (
    DEATH_GUARD_INTERCEPTOR_ID,
    FIRE_DAMAGE_ID,
    FROST_DAMAGE_ID,
    POISON_DAMAGE_ID,
    STUN_CONTROL_ID,
    TRUE_DAMAGE_ID,
)
from .ids import equipment_trigger_id


_TIER_FACTORS = (0.65, 1.0, 1.45)


@dataclass(frozen=True)
class CompiledEquipmentMechanic:
    effects: tuple[EffectDefinition, ...]
    triggers: tuple[TriggerDefinition, ...]


EquipmentMechanicCompiler = Callable[[int], CompiledEquipmentMechanic]


@dataclass(frozen=True)
class EquipmentMechanicDefinition:
    key: str
    category: str
    base_value: ValueVector
    compiler: EquipmentMechanicCompiler
    blocked_property_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.key.strip() or not self.category.strip() or not callable(self.compiler):
            raise ValueError("装备机制定义缺少稳定键、类别或编译器")
        blocked = tuple(self.blocked_property_keys)
        if self.key in blocked or len(blocked) != len(set(blocked)):
            raise ValueError(f"装备机制互斥声明无效：{self.key}")
        object.__setattr__(self, "blocked_property_keys", blocked)

    def compile(self, tier: int) -> CompiledEquipmentMechanic:
        if tier not in (1, 2, 3):
            raise ValueError(f"装备机制档位无效：{self.key}/{tier}")
        return self.compiler(tier)


@dataclass(frozen=True)
class EquipmentMechanicRegistry:
    definitions: Mapping[str, EquipmentMechanicDefinition] = field(default_factory=dict)

    def __post_init__(self) -> None:
        source: Iterable[EquipmentMechanicDefinition]
        source = self.definitions.values() if isinstance(self.definitions, Mapping) else self.definitions
        indexed: dict[str, EquipmentMechanicDefinition] = {}
        for definition in source:
            if definition.key in indexed:
                raise ValueError(f"装备机制稳定键重复：{definition.key}")
            indexed[definition.key] = definition
        if not indexed:
            raise ValueError("装备机制注册不能为空")
        unknown_blocked = {
            blocked
            for definition in indexed.values()
            for blocked in definition.blocked_property_keys
            if blocked not in indexed
        }
        if unknown_blocked:
            raise ValueError(f"装备机制互斥项未注册：{sorted(unknown_blocked)}")
        object.__setattr__(self, "definitions", MappingProxyType(indexed))

    def require(self, key: str) -> EquipmentMechanicDefinition:
        try:
            return self.definitions[key]
        except KeyError as error:
            raise ValueError(f"装备机制未注册：{key}") from error


@dataclass(frozen=True)
class _MechanicContext:
    key: str
    tier: int
    factor: float
    effect_id: str
    trigger_id: str
    operation_id: str


OperationFactory = Callable[[_MechanicContext], tuple[object, ...]]
ConditionFactory = Callable[[_MechanicContext], tuple[object, ...]]


def _context(key: str, tier: int) -> _MechanicContext:
    return _MechanicContext(
        key,
        tier,
        _TIER_FACTORS[tier - 1],
        f"effect.equipment.{key}.tier_{tier}",
        equipment_trigger_id(key, tier),
        f"operation.equipment.{key}.tier_{tier}",
    )


def _damage(
    operation_id: str,
    damage_type: str,
    scale: float,
    *,
    event_scale: bool = False,
) -> DealDamage:
    magnitude = (
        ParameterMagnitude("event.effective_damage", scale=scale)
        if event_scale
        else AttributeMagnitude(COMBAT_ATTACK, scale=scale)
    )
    return DealDamage(
        operation_id,
        damage_type,
        magnitude,
        tags=TagSet.of("damage.proc", "damage.equipment"),
        can_critical=False,
    )


def _standard_compiler(
    key: str,
    event_kind: str,
    owner: TriggerOwner,
    target: TriggerTarget,
    source: TriggerSource,
    operations: OperationFactory,
    *,
    chances: tuple[float, float, float] = (1.0, 1.0, 1.0),
    conditions: ConditionFactory | None = None,
    effect_tags: TagSet = TagSet(),
    duration_turns: int | None = 0,
    non_proc_only: bool = False,
    living_target_only: bool = False,
) -> EquipmentMechanicCompiler:
    def compile_mechanic(tier: int) -> CompiledEquipmentMechanic:
        context = _context(key, tier)
        resolved_conditions = conditions(context) if conditions else ()
        if non_proc_only:
            resolved_conditions = (
                *resolved_conditions,
                EventValueCondition(
                    f"condition.equipment.{key}.non_proc.tier_{tier}",
                    "is_proc",
                    Comparison.EQUAL,
                    0.0,
                ),
            )
        if living_target_only:
            resolved_conditions = (
                *resolved_conditions,
                ResourceRatioCondition(
                    f"condition.equipment.{key}.alive.tier_{tier}",
                    ConditionSubject.TARGET,
                    HEALTH_CURRENT,
                    HEALTH_MAXIMUM,
                    Comparison.GREATER,
                    0.0,
                ),
            )
        effect = EffectDefinition(
            context.effect_id,
            tags=effect_tags,
            operations=operations(context),
            duration_turns=duration_turns,
        )
        trigger = TriggerDefinition(
            context.trigger_id,
            event_kind,
            context.effect_id,
            target=target,
            owner=owner,
            source=source,
            conditions=resolved_conditions,
            chance=chances[tier - 1],
            max_activations_per_execution=1,
        )
        return CompiledEquipmentMechanic((effect,), (trigger,))

    return compile_mechanic


def _venom_compiler(tier: int) -> CompiledEquipmentMechanic:
    context = _context("venom_touch", tier)
    tick_effect_id = f"effect.equipment.venom_touch.tick.tier_{tier}"
    tick_trigger_id = f"trigger.equipment.venom_touch.tick.tier_{tier}"
    status = EffectDefinition(
        context.effect_id,
        tags=TagSet.of("status.negative", "status.ailment.poison"),
        operations=(GrantTrigger(context.operation_id, tick_trigger_id),),
        duration_turns=3,
        stacking=StackingPolicy.STACK,
        max_stacks=3,
        stack_by_source=True,
    )
    tick = EffectDefinition(
        tick_effect_id,
        operations=(
            DealDamage(
                f"{context.operation_id}.tick",
                POISON_DAMAGE_ID,
                ProductMagnitude(
                    (
                        AttributeMagnitude(COMBAT_ATTACK, scale=0.07 * context.factor),
                        ParameterMagnitude("effect.stacks"),
                    )
                ),
                tags=TagSet.of(
                    "damage.proc",
                    "damage.equipment",
                    "damage.periodic",
                ),
                can_critical=False,
            ),
        ),
    )
    trigger = TriggerDefinition(
        context.trigger_id,
        "combat.attack.hit",
        context.effect_id,
        target=TriggerTarget.EVENT_TARGET,
        owner=TriggerOwner.EVENT_SOURCE,
        source=TriggerSource.OWNER,
        conditions=(
            EventValueCondition(
                f"condition.equipment.venom_touch.non_proc.tier_{tier}",
                "is_proc",
                Comparison.EQUAL,
                0.0,
            ),
        ),
        chance=(0.12, 0.20, 0.30)[tier - 1],
        max_activations_per_execution=1,
    )
    tick_trigger = TriggerDefinition(
        tick_trigger_id,
        "combat.turn.started",
        tick_effect_id,
        target=TriggerTarget.OWNER,
        owner=TriggerOwner.EVENT_SOURCE,
        source=TriggerSource.GRANT_SOURCE,
        max_activations_per_execution=1,
    )
    return CompiledEquipmentMechanic((status, tick), (trigger, tick_trigger))


def _definition(
    key: str,
    category: str,
    base_value: ValueVector,
    compiler: EquipmentMechanicCompiler,
    *,
    blocked: tuple[str, ...] = (),
) -> EquipmentMechanicDefinition:
    return EquipmentMechanicDefinition(key, category, base_value, compiler, blocked)


_EVENT_SOURCE = TriggerOwner.EVENT_SOURCE
_EVENT_TARGET = TriggerOwner.EVENT_TARGET
_OWNER = TriggerTarget.OWNER
_TARGET = TriggerTarget.EVENT_TARGET
_SOURCE = TriggerTarget.EVENT_SOURCE
_SELF_SOURCE = TriggerSource.OWNER

OFFICIAL_EQUIPMENT_MECHANICS = EquipmentMechanicRegistry(
    (
        _definition(
            "critical_echo",
            "reaction",
            ValueVector(offense=8, volatility=3),
            _standard_compiler(
                "critical_echo",
                "combat.attack.critical",
                _EVENT_SOURCE,
                _TARGET,
                _SELF_SOURCE,
                lambda c: (_damage(c.operation_id, TRUE_DAMAGE_ID, 0.18 * c.factor),),
            ),
        ),
        _definition(
            "burning_touch",
            "ailment",
            ValueVector(offense=7, volatility=3),
            _standard_compiler(
                "burning_touch",
                "combat.attack.hit",
                _EVENT_SOURCE,
                _TARGET,
                _SELF_SOURCE,
                lambda c: (_damage(c.operation_id, FIRE_DAMAGE_ID, 0.22 * c.factor),),
                chances=(0.12, 0.20, 0.30),
                non_proc_only=True,
            ),
            blocked=("venom_touch", "frost_touch"),
        ),
        _definition(
            "venom_touch",
            "ailment",
            ValueVector(offense=9, volatility=4),
            _venom_compiler,
            blocked=("burning_touch", "frost_touch"),
        ),
        _definition(
            "frost_touch",
            "ailment",
            ValueVector(offense=6, control=2, volatility=3),
            _standard_compiler(
                "frost_touch",
                "combat.attack.hit",
                _EVENT_SOURCE,
                _TARGET,
                _SELF_SOURCE,
                lambda c: (_damage(c.operation_id, FROST_DAMAGE_ID, 0.20 * c.factor),),
                chances=(0.12, 0.20, 0.30),
                non_proc_only=True,
            ),
            blocked=("burning_touch", "venom_touch"),
        ),
        _definition(
            "execute_echo",
            "offense",
            ValueVector(offense=9, volatility=5),
            _standard_compiler(
                "execute_echo",
                "combat.damage.dealt",
                _EVENT_SOURCE,
                _TARGET,
                _SELF_SOURCE,
                lambda c: (_damage(c.operation_id, TRUE_DAMAGE_ID, 0.16 * c.factor),),
                conditions=lambda c: (
                    ResourceRatioCondition(
                        f"condition.equipment.execute_echo.tier_{c.tier}",
                        ConditionSubject.TARGET,
                        HEALTH_CURRENT,
                        HEALTH_MAXIMUM,
                        Comparison.LESS_OR_EQUAL,
                        0.30,
                    ),
                ),
                non_proc_only=True,
                living_target_only=True,
            ),
        ),
        _definition(
            "kill_haste",
            "tempo",
            ValueVector(tempo=8, volatility=5),
            _standard_compiler(
                "kill_haste",
                "combat.target.defeated",
                _EVENT_SOURCE,
                _OWNER,
                _SELF_SOURCE,
                lambda c: (
                    ModifyAttribute(
                        c.operation_id, COMBAT_SPEED, ModifierLayer.GLOBAL_FLAT, FixedMagnitude((6, 10, 15)[c.tier - 1])
                    ),
                ),
                effect_tags=TagSet.of("status.positive"),
                duration_turns=2,
            ),
        ),
        _definition(
            "kill_heal",
            "sustain",
            ValueVector(sustain=8, volatility=5),
            _standard_compiler(
                "kill_heal",
                "combat.target.defeated",
                _EVENT_SOURCE,
                _OWNER,
                _SELF_SOURCE,
                lambda c: (Heal(c.operation_id, AttributeMagnitude(COMBAT_ATTACK, scale=0.35 * c.factor)),),
            ),
        ),
        _definition(
            "lifesteal",
            "sustain",
            ValueVector(sustain=9),
            _standard_compiler(
                "lifesteal",
                "combat.damage.dealt",
                _EVENT_SOURCE,
                _OWNER,
                _SELF_SOURCE,
                lambda c: (
                    Heal(
                        c.operation_id,
                        ParameterMagnitude("event.effective_damage", scale=(0.06, 0.10, 0.14)[c.tier - 1]),
                    ),
                ),
                non_proc_only=True,
            ),
        ),
        _definition(
            "thorns",
            "reaction",
            ValueVector(offense=4, survival=4, volatility=3),
            _standard_compiler(
                "thorns",
                "combat.damage.dealt",
                _EVENT_TARGET,
                _SOURCE,
                _SELF_SOURCE,
                lambda c: (_damage(c.operation_id, TRUE_DAMAGE_ID, (0.08, 0.13, 0.18)[c.tier - 1], event_scale=True),),
                conditions=lambda c: (
                    EventValueCondition(
                        f"condition.equipment.thorns.tier_{c.tier}", "damage_type", Comparison.NOT_EQUAL, TRUE_DAMAGE_ID
                    ),
                ),
                non_proc_only=True,
            ),
        ),
        _definition(
            "evade_counter",
            "reaction",
            ValueVector(offense=4, survival=4, volatility=4),
            _standard_compiler(
                "evade_counter",
                "combat.attack.missed",
                _EVENT_TARGET,
                _SOURCE,
                _SELF_SOURCE,
                lambda c: (_damage(c.operation_id, TRUE_DAMAGE_ID, 0.24 * c.factor),),
                chances=(0.35, 0.55, 0.75),
            ),
        ),
        _definition(
            "block_counter",
            "reaction",
            ValueVector(offense=4, survival=4, volatility=3),
            _standard_compiler(
                "block_counter",
                "combat.attack.blocked",
                _EVENT_TARGET,
                _SOURCE,
                _SELF_SOURCE,
                lambda c: (_damage(c.operation_id, TRUE_DAMAGE_ID, 0.20 * c.factor),),
                chances=(0.35, 0.55, 0.75),
            ),
        ),
        _definition(
            "shield_counter",
            "reaction",
            ValueVector(offense=5, survival=4, volatility=4),
            _standard_compiler(
                "shield_counter",
                "combat.shield.broken",
                _EVENT_TARGET,
                _SOURCE,
                _SELF_SOURCE,
                lambda c: (_damage(c.operation_id, TRUE_DAMAGE_ID, 0.30 * c.factor),),
            ),
        ),
        _definition(
            "damaged_heal",
            "sustain",
            ValueVector(sustain=7, volatility=2),
            _standard_compiler(
                "damaged_heal",
                "combat.damage.dealt",
                _EVENT_TARGET,
                _OWNER,
                _SELF_SOURCE,
                lambda c: (
                    Heal(
                        c.operation_id,
                        ParameterMagnitude("event.effective_damage", scale=(0.05, 0.08, 0.12)[c.tier - 1]),
                    ),
                ),
                non_proc_only=True,
                living_target_only=True,
            ),
        ),
        _definition(
            "damaged_shield",
            "defense",
            ValueVector(survival=7, volatility=2),
            _standard_compiler(
                "damaged_shield",
                "combat.damage.dealt",
                _EVENT_TARGET,
                _OWNER,
                _SELF_SOURCE,
                lambda c: (
                    GrantShield(
                        c.operation_id,
                        ParameterMagnitude("event.effective_damage", scale=(0.10, 0.16, 0.24)[c.tier - 1]),
                        maximum_target_health_ratio=0.12,
                    ),
                ),
                non_proc_only=True,
                living_target_only=True,
            ),
        ),
        _definition(
            "critical_spirit",
            "resource",
            ValueVector(sustain=3, tempo=5, volatility=3),
            _standard_compiler(
                "critical_spirit",
                "combat.attack.critical",
                _EVENT_SOURCE,
                _OWNER,
                _SELF_SOURCE,
                lambda c: (ChangeResource(c.operation_id, SPIRIT_CURRENT, FixedMagnitude((4, 7, 11)[c.tier - 1])),),
            ),
        ),
        _definition(
            "hit_spirit",
            "resource",
            ValueVector(sustain=3, tempo=4),
            _standard_compiler(
                "hit_spirit",
                "combat.attack.hit",
                _EVENT_SOURCE,
                _OWNER,
                _SELF_SOURCE,
                lambda c: (ChangeResource(c.operation_id, SPIRIT_CURRENT, FixedMagnitude((2, 3, 5)[c.tier - 1])),),
                non_proc_only=True,
            ),
        ),
        _definition(
            "kill_cooldown",
            "tempo",
            ValueVector(tempo=9, volatility=5),
            _standard_compiler(
                "kill_cooldown",
                "combat.target.defeated",
                _EVENT_SOURCE,
                _OWNER,
                _SELF_SOURCE,
                lambda c: (
                    ModifyCurrentCooldowns(
                        c.operation_id,
                        turns=((-1, "longest"), (-2, "longest"), (-1, "all"))[c.tier - 1][0],
                        selection=((-1, "longest"), (-2, "longest"), (-1, "all"))[c.tier - 1][1],
                    ),
                ),
            ),
        ),
        _definition(
            "turn_heal",
            "sustain",
            ValueVector(sustain=8),
            _standard_compiler(
                "turn_heal",
                "combat.turn.started",
                _EVENT_SOURCE,
                _OWNER,
                _SELF_SOURCE,
                lambda c: (Heal(c.operation_id, AttributeMagnitude(COMBAT_ATTACK, scale=0.12 * c.factor)),),
            ),
        ),
        _definition(
            "turn_spirit",
            "resource",
            ValueVector(sustain=4, tempo=4),
            _standard_compiler(
                "turn_spirit",
                "combat.turn.started",
                _EVENT_SOURCE,
                _OWNER,
                _SELF_SOURCE,
                lambda c: (ChangeResource(c.operation_id, SPIRIT_CURRENT, FixedMagnitude((2, 4, 6)[c.tier - 1])),),
            ),
        ),
        _definition(
            "turn_shield",
            "defense",
            ValueVector(survival=8),
            _standard_compiler(
                "turn_shield",
                "combat.turn.started",
                _EVENT_SOURCE,
                _OWNER,
                _SELF_SOURCE,
                lambda c: (
                    GrantShield(
                        c.operation_id,
                        AttributeMagnitude(COMBAT_ATTACK, scale=0.18 * c.factor),
                        maximum_target_health_ratio=0.15,
                    ),
                ),
            ),
        ),
        _definition(
            "critical_stun",
            "control",
            ValueVector(control=9, volatility=5),
            _standard_compiler(
                "critical_stun",
                "combat.attack.critical",
                _EVENT_SOURCE,
                _TARGET,
                _SELF_SOURCE,
                lambda c: (ApplyControl(c.operation_id, STUN_CONTROL_ID),),
                chances=(0.20, 0.32, 0.45),
            ),
        ),
        _definition(
            "hit_slow",
            "control",
            ValueVector(tempo=2, control=6),
            _standard_compiler(
                "hit_slow",
                "combat.attack.hit",
                _EVENT_SOURCE,
                _TARGET,
                _SELF_SOURCE,
                lambda c: (
                    ModifyAttribute(
                        c.operation_id,
                        COMBAT_SPEED,
                        ModifierLayer.GLOBAL_FLAT,
                        FixedMagnitude((-5, -8, -12)[c.tier - 1]),
                    ),
                ),
                chances=(0.18, 0.28, 0.40),
                effect_tags=TagSet.of("status.negative", "status.slow"),
                duration_turns=2,
                non_proc_only=True,
            ),
        ),
        _definition(
            "low_health_guard",
            "defense",
            ValueVector(survival=10, volatility=5),
            _standard_compiler(
                "low_health_guard",
                "combat.damage.dealt",
                _EVENT_TARGET,
                _OWNER,
                _SELF_SOURCE,
                lambda c: (GrantInterceptor(c.operation_id, DEATH_GUARD_INTERCEPTOR_ID),),
                conditions=lambda c: (
                    ResourceRatioCondition(
                        f"condition.equipment.low_health_guard.tier_{c.tier}",
                        ConditionSubject.TARGET,
                        HEALTH_CURRENT,
                        HEALTH_MAXIMUM,
                        Comparison.LESS_OR_EQUAL,
                        (0.15, 0.25, 0.35)[c.tier - 1],
                    ),
                ),
                effect_tags=TagSet.of("status.positive", "status.death_guard"),
                duration_turns=1,
                non_proc_only=True,
                living_target_only=True,
            ),
        ),
        _definition(
            "healing_shield",
            "sustain",
            ValueVector(survival=4, sustain=5, volatility=3),
            _standard_compiler(
                "healing_shield",
                "combat.healing.resolved",
                _EVENT_TARGET,
                _OWNER,
                _SELF_SOURCE,
                lambda c: (
                    GrantShield(
                        c.operation_id,
                        ParameterMagnitude("event.actual", scale=(0.20, 0.32, 0.48)[c.tier - 1]),
                        maximum_target_health_ratio=0.15,
                    ),
                ),
                conditions=lambda c: (
                    EventValueCondition(
                        f"condition.equipment.healing_shield.tier_{c.tier}", "actual", Comparison.GREATER, 0
                    ),
                ),
            ),
        ),
    )
)


__all__ = [
    "CompiledEquipmentMechanic",
    "EquipmentMechanicDefinition",
    "EquipmentMechanicRegistry",
    "OFFICIAL_EQUIPMENT_MECHANICS",
]
