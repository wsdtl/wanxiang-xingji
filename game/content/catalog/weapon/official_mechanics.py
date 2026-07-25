"""正式武器机制的单点注册与可执行编译器。"""

from __future__ import annotations

from collections.abc import Callable

from game.core.gameplay import (
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    COMBAT_SPEED,
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    SPIRIT_CURRENT,
    ApplyControl,
    AttributeMagnitude,
    ChangeResource,
    ChooseOne,
    Comparison,
    ConsumeEffectStacks,
    DealDamage,
    DispelEffects,
    EffectDefinition,
    EffectReference,
    EffectStacksMagnitude,
    EffectTarget,
    EventValueCondition,
    FixedMagnitude,
    GrantInterceptor,
    GrantShield,
    GrantTargetConstraint,
    GrantTrigger,
    Heal,
    MinimumMagnitude,
    ModifierLayer,
    ModifyAttribute,
    ModifyCooldown,
    ModifyCurrentCooldowns,
    ParameterMagnitude,
    ProductMagnitude,
    RequestExtraTurn,
    RequestTurnDelay,
    ResourceMagnitude,
    ResourceValueMode,
    StackingPolicy,
    SumMagnitude,
    TagSet,
    TransferResource,
    TriggerDefinition,
    TriggerOwner,
    TriggerSource,
    TriggerTarget,
    ValueVector,
)

from ..combat.stats import (
    COMBAT_BLOCK_CHANCE,
    COMBAT_BLOCK_REDUCTION,
    COMBAT_CRITICAL_CHANCE,
    COMBAT_EVASION,
    DEATH_GUARD_INTERCEPTOR_ID,
    FIRE_DAMAGE_ID,
    FREEZE_CONTROL_ID,
    FROST_DAMAGE_ID,
    PHYSICAL_DAMAGE_ID,
    POISON_DAMAGE_ID,
    SLEEP_CONTROL_ID,
    STUN_CONTROL_ID,
    TRUE_DAMAGE_ID,
)
from .blueprints import WeaponBlueprint
from .registry import (
    CompiledPrimaryMechanic,
    CompiledSupportMechanic,
    PrimaryMechanicDefinition,
    SupportMechanicDefinition,
    TargetingMechanicDefinition,
    WeaponMechanicRegistry,
)


WEAPON_MARK_EFFECT_ID = "effect.weapon.shared_mark"
WEAPON_CHARGE_EFFECT_ID = "effect.weapon.shared_charge"
TAUNT_CONSTRAINT_ID = "target_constraint.weapon.taunt"
UNTARGETABLE_CONSTRAINT_ID = "target_constraint.weapon.untargetable"
IMMUNITY_INTERCEPTOR_ID = "interceptor.weapon.immunity"
DAMAGE_CAP_INTERCEPTOR_ID = "interceptor.weapon.damage_cap"


def _attack(scale: float = 1.0, *, owner: str = "source") -> AttributeMagnitude:
    return AttributeMagnitude(COMBAT_ATTACK, owner=owner, scale=scale)


def _damage(
    operation_id: str,
    magnitude,
    *,
    damage_type: str = PHYSICAL_DAMAGE_ID,
    bypass_shield: bool = False,
    can_critical: bool = True,
    minimum_damage: float | None = None,
    tags: TagSet = TagSet(),
) -> DealDamage:
    return DealDamage(
        operation_id,
        damage_type,
        magnitude,
        tags=tags,
        bypass_shield=bypass_shield,
        can_critical=can_critical,
        minimum_damage=minimum_damage,
    )


def _simple_primary(
    suffix: str,
    *,
    damage_type: str = PHYSICAL_DAMAGE_ID,
    bypass_shield: bool = False,
) -> Callable[[WeaponBlueprint], CompiledPrimaryMechanic]:
    def compile_primary(blueprint: WeaponBlueprint) -> CompiledPrimaryMechanic:
        return CompiledPrimaryMechanic(
            (
                _damage(
                    f"operation.weapon.{blueprint.key}.{suffix}",
                    _attack(blueprint.power),
                    damage_type=damage_type,
                    bypass_shield=bypass_shield,
                ),
            )
        )

    return compile_primary


def _multi_primary(hits: int) -> Callable[[WeaponBlueprint], CompiledPrimaryMechanic]:
    def compile_primary(blueprint: WeaponBlueprint) -> CompiledPrimaryMechanic:
        return CompiledPrimaryMechanic(
            tuple(
                _damage(
                    f"operation.weapon.{blueprint.key}.hit_{index}",
                    _attack(blueprint.power),
                )
                for index in range(1, hits + 1)
            )
        )

    return compile_primary


def _execute_primary(blueprint: WeaponBlueprint) -> CompiledPrimaryMechanic:
    magnitude = SumMagnitude(
        (
            _attack(blueprint.power),
            ResourceMagnitude(
                HEALTH_CURRENT,
                mode=ResourceValueMode.MISSING,
                maximum_attribute_id=HEALTH_MAXIMUM,
                scale=0.22,
            ),
        )
    )
    return CompiledPrimaryMechanic((_damage(f"operation.weapon.{blueprint.key}.execute", magnitude),))


def _missing_rage_primary(blueprint: WeaponBlueprint) -> CompiledPrimaryMechanic:
    magnitude = SumMagnitude(
        (
            _attack(blueprint.power),
            ResourceMagnitude(
                HEALTH_CURRENT,
                owner="source",
                mode=ResourceValueMode.MISSING,
                maximum_attribute_id=HEALTH_MAXIMUM,
                scale=0.16,
            ),
        )
    )
    return CompiledPrimaryMechanic((_damage(f"operation.weapon.{blueprint.key}.rage", magnitude),))


def _max_health_primary(blueprint: WeaponBlueprint) -> CompiledPrimaryMechanic:
    magnitude = SumMagnitude(
        (
            _attack(blueprint.power),
            AttributeMagnitude(HEALTH_MAXIMUM, owner="target", scale=0.055),
        )
    )
    return CompiledPrimaryMechanic(
        (
            DealDamage(
                f"operation.weapon.{blueprint.key}.crush",
                PHYSICAL_DAMAGE_ID,
                magnitude,
                maximum_target_health_ratio=0.16,
            ),
        )
    )


def _ailment_content(
    blueprint: WeaponBlueprint,
    ailment: str,
) -> tuple[tuple[EffectDefinition, ...], tuple[TriggerDefinition, ...], tuple[EffectReference, ...]]:
    key = blueprint.key
    status_id = f"effect.weapon.{key}.{ailment}_status"
    tick_id = f"effect.weapon.{key}.{ailment}_tick"
    trigger_id = f"trigger.weapon.{key}.{ailment}_tick"
    damage_type = {
        "poison": POISON_DAMAGE_ID,
        "bleed": PHYSICAL_DAMAGE_ID,
        "burn": FIRE_DAMAGE_ID,
    }[ailment]
    effects = (
        EffectDefinition(
            status_id,
            tags=TagSet.of("status.negative", f"status.ailment.{ailment}"),
            operations=(
                GrantTrigger(
                    f"operation.weapon.{key}.grant_{ailment}_tick",
                    trigger_id,
                ),
            ),
            duration_turns=3,
            stacking=StackingPolicy.STACK,
            max_stacks=5,
            stack_by_source=True,
        ),
        EffectDefinition(
            tick_id,
            operations=(
                _damage(
                    f"operation.weapon.{key}.{ailment}_tick",
                    ProductMagnitude((_attack(0.16), ParameterMagnitude("effect.stacks"))),
                    damage_type=damage_type,
                    can_critical=False,
                    tags=TagSet.of("damage.periodic", f"damage.{ailment}"),
                ),
            ),
        ),
    )
    trigger = TriggerDefinition(
        trigger_id,
        "combat.turn.started",
        tick_id,
        target=TriggerTarget.OWNER,
        owner=TriggerOwner.EVENT_SOURCE,
        source=TriggerSource.GRANT_SOURCE,
        max_activations_per_execution=1,
    )
    return effects, (trigger,), (EffectReference(status_id),)


def _ailment_primary(
    ailment: str,
) -> Callable[[WeaponBlueprint], CompiledPrimaryMechanic]:
    damage_type = {
        "poison": POISON_DAMAGE_ID,
        "bleed": PHYSICAL_DAMAGE_ID,
        "burn": FIRE_DAMAGE_ID,
    }[ailment]

    def compile_primary(blueprint: WeaponBlueprint) -> CompiledPrimaryMechanic:
        effects, triggers, references = _ailment_content(blueprint, ailment)
        return CompiledPrimaryMechanic(
            (
                _damage(
                    f"operation.weapon.{blueprint.key}.{ailment}",
                    _attack(blueprint.power),
                    damage_type=damage_type,
                ),
            ),
            effects,
            triggers,
            references,
        )

    return compile_primary


def _spirit_drain_primary(blueprint: WeaponBlueprint) -> CompiledPrimaryMechanic:
    key = blueprint.key
    return CompiledPrimaryMechanic(
        (
            _damage(f"operation.weapon.{key}.drain_hit", _attack(blueprint.power)),
            TransferResource(
                f"operation.weapon.{key}.drain_spirit",
                SPIRIT_CURRENT,
                FixedMagnitude(12),
                efficiency=0.75,
            ),
        )
    )


def _spirit_burst_primary(blueprint: WeaponBlueprint) -> CompiledPrimaryMechanic:
    return CompiledPrimaryMechanic(
        (
            _damage(
                f"operation.weapon.{blueprint.key}.spirit_burst",
                SumMagnitude(
                    (
                        _attack(blueprint.power),
                        ResourceMagnitude(SPIRIT_CURRENT, owner="source", scale=0.22),
                    )
                ),
            ),
        )
    )


def _element_cycle_primary(blueprint: WeaponBlueprint) -> CompiledPrimaryMechanic:
    key, power = blueprint.key, blueprint.power
    return CompiledPrimaryMechanic(
        (
            _damage(f"operation.weapon.{key}.fire", _attack(power * 0.45), damage_type=FIRE_DAMAGE_ID),
            _damage(f"operation.weapon.{key}.frost", _attack(power * 0.35), damage_type=FROST_DAMAGE_ID),
            _damage(
                f"operation.weapon.{key}.true",
                _attack(power * 0.20),
                damage_type=TRUE_DAMAGE_ID,
                can_critical=False,
            ),
        )
    )


def _detonate_primary(blueprint: WeaponBlueprint) -> CompiledPrimaryMechanic:
    key = blueprint.key
    magnitude = SumMagnitude(
        (
            _attack(blueprint.power),
            ProductMagnitude((_attack(0.28), EffectStacksMagnitude(WEAPON_MARK_EFFECT_ID))),
        )
    )
    return CompiledPrimaryMechanic(
        (
            _damage(f"operation.weapon.{key}.detonate", magnitude, damage_type=FIRE_DAMAGE_ID),
            ConsumeEffectStacks(
                f"operation.weapon.{key}.consume_mark",
                WEAPON_MARK_EFFECT_ID,
                stacks=5,
            ),
        ),
        final_references=(EffectReference(WEAPON_MARK_EFFECT_ID),),
    )


def _mark_primary(blueprint: WeaponBlueprint) -> CompiledPrimaryMechanic:
    return CompiledPrimaryMechanic(
        (_damage(f"operation.weapon.{blueprint.key}.strike", _attack(blueprint.power)),),
        final_references=(EffectReference(WEAPON_MARK_EFFECT_ID),),
    )


def _self_cost_primary(blueprint: WeaponBlueprint) -> CompiledPrimaryMechanic:
    key = blueprint.key
    effect_id = f"effect.weapon.{key}.blood_cost"
    effect = EffectDefinition(
        effect_id,
        operations=(
            ChangeResource(
                f"operation.weapon.{key}.primary_blood_cost",
                HEALTH_CURRENT,
                _attack(-0.24),
            ),
        ),
    )
    return CompiledPrimaryMechanic(
        (_damage(f"operation.weapon.{key}.sacrifice", _attack(blueprint.power)),),
        effects=(effect,),
        final_references=(EffectReference(effect_id, EffectTarget.SELF),),
    )


def _volatile_primary(blueprint: WeaponBlueprint) -> CompiledPrimaryMechanic:
    key, power = blueprint.key, blueprint.power
    return CompiledPrimaryMechanic(
        (
            ChooseOne(
                f"operation.weapon.{key}.volatile",
                (
                    (_damage(f"operation.weapon.{key}.low", _attack(power * 0.45), can_critical=False),),
                    (_damage(f"operation.weapon.{key}.high", _attack(power * 1.65)),),
                ),
            ),
        )
    )


def _borrowed_force_primary(blueprint: WeaponBlueprint) -> CompiledPrimaryMechanic:
    borrowed = MinimumMagnitude((_attack(0.38, owner="target"), _attack(0.50)))
    return CompiledPrimaryMechanic(
        (
            _damage(
                f"operation.weapon.{blueprint.key}.borrowed_force",
                SumMagnitude((_attack(blueprint.power), borrowed)),
            ),
        )
    )


def _deferred_echo_primary(blueprint: WeaponBlueprint) -> CompiledPrimaryMechanic:
    key = blueprint.key
    status_id = f"effect.weapon.{key}.echo_status"
    release_id = f"effect.weapon.{key}.echo_release"
    trigger_id = f"trigger.weapon.{key}.echo_release"
    effects = (
        EffectDefinition(
            status_id,
            tags=TagSet.of("status.negative", "status.delayed_echo"),
            operations=(GrantTrigger(f"operation.weapon.{key}.grant_echo_release", trigger_id),),
            duration_turns=1,
            stacking=StackingPolicy.REFRESH,
            max_stacks=1,
            stack_by_source=True,
        ),
        EffectDefinition(
            release_id,
            operations=(
                _damage(
                    f"operation.weapon.{key}.echo_release",
                    _attack(blueprint.power * 0.85),
                    damage_type=TRUE_DAMAGE_ID,
                    can_critical=False,
                    tags=TagSet.of("damage.delayed", "damage.echo"),
                ),
            ),
        ),
    )
    trigger = TriggerDefinition(
        trigger_id,
        "combat.turn.started",
        release_id,
        target=TriggerTarget.OWNER,
        owner=TriggerOwner.EVENT_SOURCE,
        source=TriggerSource.GRANT_SOURCE,
        max_activations_per_execution=1,
    )
    return CompiledPrimaryMechanic(
        (_damage(f"operation.weapon.{key}.echo_opening", _attack(blueprint.power)),),
        effects,
        (trigger,),
        (EffectReference(status_id, EffectTarget.TARGET),),
    )


SupportOperationFactory = Callable[[WeaponBlueprint, str], tuple[object, ...]]


def _active_support(
    operation_factory: SupportOperationFactory,
    *,
    target: EffectTarget = EffectTarget.SELF,
    duration: int | None = 0,
    tags: TagSet = TagSet.of("status.positive"),
) -> Callable[[WeaponBlueprint, str], CompiledSupportMechanic]:
    def compile_support(
        blueprint: WeaponBlueprint,
        ability_id: str,
    ) -> CompiledSupportMechanic:
        effect_id = f"effect.weapon.{blueprint.key}.support"
        effect = EffectDefinition(
            effect_id,
            tags=tags,
            operations=operation_factory(blueprint, ability_id),
            duration_turns=duration,
            stacking=StackingPolicy.REFRESH,
            max_stacks=1,
        )
        return CompiledSupportMechanic(
            effects=(effect,),
            references=(EffectReference(effect_id, target),),
        )

    return compile_support


def _attribute_support(
    suffix: str,
    attribute_id: str,
    amount: float,
    *,
    target: EffectTarget = EffectTarget.SELF,
    duration: int = 2,
    tags: TagSet = TagSet.of("status.positive"),
) -> Callable[[WeaponBlueprint, str], CompiledSupportMechanic]:
    return _active_support(
        lambda blueprint, _: (
            ModifyAttribute(
                f"operation.weapon.{blueprint.key}.{suffix}",
                attribute_id,
                ModifierLayer.GLOBAL_FLAT,
                FixedMagnitude(amount),
            ),
        ),
        target=target,
        duration=duration,
        tags=tags,
    )


def _empty_support(
    blueprint: WeaponBlueprint,
    ability_id: str,
) -> CompiledSupportMechanic:
    return CompiledSupportMechanic()


def _ailment_support(
    ailment: str,
) -> Callable[[WeaponBlueprint, str], CompiledSupportMechanic]:
    def compile_support(
        blueprint: WeaponBlueprint,
        ability_id: str,
    ) -> CompiledSupportMechanic:
        effects, triggers, references = _ailment_content(blueprint, ailment)
        return CompiledSupportMechanic(effects, triggers, references)

    return compile_support


def _shared_effect_support(
    effect_id: str,
    target: EffectTarget,
) -> Callable[[WeaponBlueprint, str], CompiledSupportMechanic]:
    def compile_support(
        blueprint: WeaponBlueprint,
        ability_id: str,
    ) -> CompiledSupportMechanic:
        return CompiledSupportMechanic(references=(EffectReference(effect_id, target),))

    return compile_support


def _passive_support(
    event_kind: str,
    target: TriggerTarget,
    owner: TriggerOwner,
    source: TriggerSource,
    operation_factory: SupportOperationFactory,
    *,
    condition_factory: Callable[[WeaponBlueprint], tuple[object, ...]] | None = None,
) -> Callable[[WeaponBlueprint, str], CompiledSupportMechanic]:
    def compile_support(
        blueprint: WeaponBlueprint,
        ability_id: str,
    ) -> CompiledSupportMechanic:
        key = blueprint.key
        effect_id = f"effect.weapon.{key}.passive"
        trigger_id = f"trigger.weapon.{key}.passive"
        effect = EffectDefinition(
            effect_id,
            operations=operation_factory(blueprint, ability_id),
        )
        trigger = TriggerDefinition(
            trigger_id,
            event_kind,
            effect_id,
            target=target,
            owner=owner,
            source=source,
            conditions=condition_factory(blueprint) if condition_factory else (),
            max_activations_per_execution=1,
        )
        return CompiledSupportMechanic(
            effects=(effect,),
            triggers=(trigger,),
            granted_triggers=frozenset({trigger_id}),
        )

    return compile_support


def _block_operations(blueprint: WeaponBlueprint, ability_id: str) -> tuple[object, ...]:
    key = blueprint.key
    return (
        ModifyAttribute(
            f"operation.weapon.{key}.block_chance", COMBAT_BLOCK_CHANCE, ModifierLayer.GLOBAL_FLAT, FixedMagnitude(0.16)
        ),
        ModifyAttribute(
            f"operation.weapon.{key}.block_reduction",
            COMBAT_BLOCK_REDUCTION,
            ModifierLayer.GLOBAL_FLAT,
            FixedMagnitude(0.20),
        ),
    )


def _resource_balance_operations(blueprint: WeaponBlueprint, ability_id: str) -> tuple[object, ...]:
    key = blueprint.key
    return (
        Heal(
            f"operation.weapon.{key}.balance_health",
            ResourceMagnitude(
                HEALTH_CURRENT,
                owner="source",
                mode=ResourceValueMode.MISSING,
                maximum_attribute_id=HEALTH_MAXIMUM,
                scale=0.18,
            ),
        ),
        ChangeResource(f"operation.weapon.{key}.balance_spirit", SPIRIT_CURRENT, FixedMagnitude(10)),
    )


def _detonate_support_operations(blueprint: WeaponBlueprint, ability_id: str) -> tuple[object, ...]:
    key = blueprint.key
    return (
        _damage(
            f"operation.weapon.{key}.support_detonate",
            ProductMagnitude((_attack(0.30), EffectStacksMagnitude(WEAPON_MARK_EFFECT_ID))),
            damage_type=TRUE_DAMAGE_ID,
            can_critical=False,
            minimum_damage=0,
        ),
        ConsumeEffectStacks(
            f"operation.weapon.{key}.support_consume_mark",
            WEAPON_MARK_EFFECT_ID,
            stacks=5,
        ),
    )


def _on_crit_operations(blueprint: WeaponBlueprint, ability_id: str) -> tuple[object, ...]:
    return (
        _damage(
            f"operation.weapon.{blueprint.key}.critical_echo",
            _attack(0.34),
            damage_type=TRUE_DAMAGE_ID,
            can_critical=False,
        ),
    )


def _on_crit_stun_operations(blueprint: WeaponBlueprint, ability_id: str) -> tuple[object, ...]:
    return (
        *_on_crit_operations(blueprint, ability_id),
        ApplyControl(f"operation.weapon.{blueprint.key}.critical_stun", STUN_CONTROL_ID),
    )


def _primary(
    key: str,
    compiler,
    hit_factor: float = 1.0,
    **value,
) -> PrimaryMechanicDefinition:
    return PrimaryMechanicDefinition(
        key=key,
        hit_factor=hit_factor,
        compiler=compiler,
        value=ValueVector(**value),
    )


def _support(key: str, compiler, **value) -> SupportMechanicDefinition:
    return SupportMechanicDefinition(
        key=key,
        compiler=compiler,
        value=ValueVector(**value),
    )


_NEGATIVE = TagSet.of("status.negative")
_CONTROL = TagSet.of("status.negative", "status.control")

OFFICIAL_WEAPON_MECHANICS = WeaponMechanicRegistry(
    primaries=(
        _primary("heavy", _simple_primary("strike")),
        _primary("swift", _simple_primary("strike"), tempo=3),
        _primary("multi2", _multi_primary(2), 2.0, volatility=1),
        _primary("multi3", _multi_primary(3), 3.0, volatility=2),
        _primary("execute", _execute_primary, offense=8, volatility=4),
        _primary("missing_rage", _missing_rage_primary, offense=7, volatility=6),
        _primary("max_health", _max_health_primary, offense=8),
        _primary("true_strike", _simple_primary("true", damage_type=TRUE_DAMAGE_ID), offense=8),
        _primary("pierce", _simple_primary("pierce", bypass_shield=True), offense=6),
        _primary("poison", _ailment_primary("poison"), offense=8, volatility=2),
        _primary("bleed", _ailment_primary("bleed"), offense=8, volatility=2),
        _primary("burn", _ailment_primary("burn"), offense=8, volatility=2),
        _primary("frost", _simple_primary("frost", damage_type=FROST_DAMAGE_ID), offense=5, control=3),
        _primary("spirit_drain", _spirit_drain_primary, sustain=4, control=4),
        _primary("spirit_burst", _spirit_burst_primary, offense=6, volatility=4),
        _primary("element_cycle", _element_cycle_primary, offense=7, volatility=3),
        _primary("detonate", _detonate_primary, offense=11, volatility=7),
        _primary("mark", _mark_primary, offense=4, volatility=4),
        _primary("self_cost", _self_cost_primary, offense=7, volatility=8),
        _primary("volatile", _volatile_primary, 1.05, offense=4, volatility=14),
        _primary("borrowed_force", _borrowed_force_primary, 1.50, offense=7, volatility=5),
        _primary("deferred_echo", _deferred_echo_primary, 1.85, offense=8, tempo=5, volatility=3),
    ),
    supports=(
        _support("none", _empty_support),
        _support(
            "sunder",
            _attribute_support(
                "sunder",
                COMBAT_DEFENSE,
                -12,
                target=EffectTarget.TARGET,
                tags=TagSet.of("status.negative", "status.sunder"),
            ),
            offense=5,
            control=3,
        ),
        _support("crit", _attribute_support("crit", COMBAT_CRITICAL_CHANCE, 0.14), offense=7, tempo=2),
        _support(
            "delay",
            _active_support(
                lambda b, _: (RequestTurnDelay(f"operation.weapon.{b.key}.delay", positions=1),),
                target=EffectTarget.TARGET,
            ),
            tempo=3,
            control=5,
        ),
        _support("burn", _ailment_support("burn"), offense=8, volatility=2),
        _support(
            "stun",
            _active_support(
                lambda b, _: (ApplyControl(f"operation.weapon.{b.key}.stun", STUN_CONTROL_ID),),
                target=EffectTarget.TARGET,
                tags=_CONTROL,
            ),
            control=11,
            volatility=3,
        ),
        _support(
            "lifesteal",
            _passive_support(
                "combat.damage.dealt",
                TriggerTarget.OWNER,
                TriggerOwner.EVENT_SOURCE,
                TriggerSource.OWNER,
                lambda b, _: (
                    Heal(
                        f"operation.weapon.{b.key}.lifesteal", ParameterMagnitude("event.effective_damage", scale=0.22)
                    ),
                ),
            ),
            sustain=11,
        ),
        _support(
            "on_kill",
            _passive_support(
                "combat.target.defeated",
                TriggerTarget.OWNER,
                TriggerOwner.EVENT_SOURCE,
                TriggerSource.OWNER,
                lambda b, _: (RequestExtraTurn(f"operation.weapon.{b.key}.kill_turn"),),
            ),
            tempo=10,
            volatility=5,
        ),
        _support("haste", _attribute_support("haste", COMBAT_SPEED, 16), tempo=8),
        _support("guard", _attribute_support("guard", COMBAT_DEFENSE, 16), survival=8),
        _support(
            "extra_turn",
            _active_support(lambda b, _: (RequestExtraTurn(f"operation.weapon.{b.key}.extra_turn"),)),
            tempo=14,
            volatility=5,
        ),
        _support("evasion", _attribute_support("evasion", COMBAT_EVASION, 0.14), survival=7, tempo=2),
        _support(
            "cooldown",
            _passive_support(
                "combat.target.defeated",
                TriggerTarget.OWNER,
                TriggerOwner.EVENT_SOURCE,
                TriggerSource.OWNER,
                lambda b, ability_id: (ModifyCooldown(f"operation.weapon.{b.key}.reset", ability_id, set_to=0),),
            ),
            tempo=8,
            volatility=4,
        ),
        _support(
            "slow",
            _attribute_support(
                "slow", COMBAT_SPEED, -15, target=EffectTarget.TARGET, tags=TagSet.of("status.negative", "status.slow")
            ),
            tempo=2,
            control=6,
        ),
        _support(
            "on_crit",
            _passive_support(
                "combat.attack.critical",
                TriggerTarget.EVENT_TARGET,
                TriggerOwner.EVENT_SOURCE,
                TriggerSource.OWNER,
                _on_crit_operations,
            ),
            offense=8,
            volatility=5,
        ),
        _support("mark", _shared_effect_support(WEAPON_MARK_EFFECT_ID, EffectTarget.TARGET), offense=5, volatility=4),
        _support(
            "execute",
            _active_support(
                lambda b, _: (
                    _damage(
                        f"operation.weapon.{b.key}.support_execute",
                        ResourceMagnitude(
                            HEALTH_CURRENT,
                            mode=ResourceValueMode.MISSING,
                            maximum_attribute_id=HEALTH_MAXIMUM,
                            scale=0.14,
                        ),
                        can_critical=False,
                    ),
                ),
                target=EffectTarget.TARGET,
            ),
            offense=8,
            volatility=3,
        ),
        _support(
            "spirit_drain",
            _active_support(
                lambda b, _: (
                    TransferResource(f"operation.weapon.{b.key}.spirit_drain", SPIRIT_CURRENT, FixedMagnitude(10), 0.6),
                ),
                target=EffectTarget.TARGET,
            ),
            sustain=4,
            control=4,
        ),
        _support(
            "freeze",
            _active_support(
                lambda b, _: (ApplyControl(f"operation.weapon.{b.key}.freeze", FREEZE_CONTROL_ID),),
                target=EffectTarget.TARGET,
                tags=_CONTROL,
            ),
            control=12,
            volatility=4,
        ),
        _support(
            "weaken",
            _attribute_support(
                "weaken",
                COMBAT_ATTACK,
                -10,
                target=EffectTarget.TARGET,
                tags=TagSet.of("status.negative", "status.weaken"),
            ),
            survival=4,
            control=5,
        ),
        _support(
            "detonate",
            _active_support(_detonate_support_operations, target=EffectTarget.TARGET),
            offense=10,
            volatility=7,
        ),
        _support(
            "heal", _active_support(lambda b, _: (Heal(f"operation.weapon.{b.key}.heal", _attack(0.32)),)), sustain=10
        ),
        _support(
            "mark_self",
            _shared_effect_support(WEAPON_CHARGE_EFFECT_ID, EffectTarget.SELF),
            offense=5,
            tempo=3,
            volatility=3,
        ),
        _support(
            "shield",
            _active_support(
                lambda b, _: (
                    GrantShield(f"operation.weapon.{b.key}.shield", _attack(0.60), maximum_target_health_ratio=0.35),
                )
            ),
            survival=10,
        ),
        _support(
            "death_guard",
            _active_support(
                lambda b, _: (GrantInterceptor(f"operation.weapon.{b.key}.death_guard", DEATH_GUARD_INTERCEPTOR_ID),),
                duration=1,
            ),
            survival=12,
            volatility=5,
        ),
        _support("resource_balance", _active_support(_resource_balance_operations), sustain=10, volatility=3),
        _support(
            "dispel",
            _active_support(
                lambda b, _: (
                    DispelEffects(
                        f"operation.weapon.{b.key}.dispel", required_tags=TagSet.of("status.positive"), maximum=1
                    ),
                ),
                target=EffectTarget.TARGET,
            ),
            control=9,
        ),
        _support(
            "thorns",
            _passive_support(
                "combat.damage.dealt",
                TriggerTarget.EVENT_SOURCE,
                TriggerOwner.EVENT_TARGET,
                TriggerSource.OWNER,
                lambda b, _: (
                    _damage(
                        f"operation.weapon.{b.key}.thorns",
                        ParameterMagnitude("event.effective_damage", scale=0.28),
                        damage_type=TRUE_DAMAGE_ID,
                        can_critical=False,
                    ),
                ),
                condition_factory=lambda b: (
                    EventValueCondition(
                        f"condition.weapon.{b.key}.not_proc", "damage_type", Comparison.NOT_EQUAL, TRUE_DAMAGE_ID
                    ),
                ),
            ),
            survival=4,
            offense=5,
            volatility=5,
        ),
        _support("block", _active_support(_block_operations, duration=2), survival=10),
        _support(
            "on_kill_heal",
            _passive_support(
                "combat.target.defeated",
                TriggerTarget.OWNER,
                TriggerOwner.EVENT_SOURCE,
                TriggerSource.OWNER,
                lambda b, _: (Heal(f"operation.weapon.{b.key}.kill_heal", _attack(0.65)),),
            ),
            sustain=9,
            volatility=5,
        ),
        _support(
            "damage_cap",
            _active_support(
                lambda b, _: (GrantInterceptor(f"operation.weapon.{b.key}.damage_cap", DAMAGE_CAP_INTERCEPTOR_ID),),
                duration=2,
            ),
            survival=14,
        ),
        _support(
            "immunity",
            _active_support(
                lambda b, _: (GrantInterceptor(f"operation.weapon.{b.key}.immunity", IMMUNITY_INTERCEPTOR_ID),),
                duration=1,
            ),
            survival=15,
            volatility=5,
        ),
        _support(
            "taunt",
            _active_support(
                lambda b, _: (GrantTargetConstraint(f"operation.weapon.{b.key}.taunt", TAUNT_CONSTRAINT_ID),),
                target=EffectTarget.TARGET,
                duration=2,
                tags=TagSet.of("status.negative", "status.taunted"),
            ),
            survival=3,
            control=9,
        ),
        _support(
            "sleep",
            _active_support(
                lambda b, _: (ApplyControl(f"operation.weapon.{b.key}.sleep", SLEEP_CONTROL_ID),),
                target=EffectTarget.TARGET,
                tags=_CONTROL,
            ),
            control=13,
            volatility=4,
        ),
        _support(
            "cooldown_delay",
            _active_support(
                lambda b, _: (
                    ModifyCurrentCooldowns(f"operation.weapon.{b.key}.cooldown_delay", turns=1, selection="longest"),
                ),
                target=EffectTarget.TARGET,
            ),
            tempo=3,
            control=10,
        ),
        _support(
            "evasion_counter",
            _passive_support(
                "combat.attack.missed",
                TriggerTarget.EVENT_SOURCE,
                TriggerOwner.EVENT_TARGET,
                TriggerSource.OWNER,
                lambda b, _: (
                    _damage(
                        f"operation.weapon.{b.key}.evade_counter",
                        _attack(0.55),
                        damage_type=TRUE_DAMAGE_ID,
                        can_critical=False,
                    ),
                ),
            ),
            offense=5,
            survival=6,
            volatility=4,
        ),
        _support(
            "on_crit_stun",
            _passive_support(
                "combat.attack.critical",
                TriggerTarget.EVENT_TARGET,
                TriggerOwner.EVENT_SOURCE,
                TriggerSource.OWNER,
                _on_crit_stun_operations,
            ),
            offense=6,
            control=8,
            volatility=6,
        ),
        _support(
            "shield_counter",
            _passive_support(
                "combat.shield.broken",
                TriggerTarget.EVENT_SOURCE,
                TriggerOwner.EVENT_TARGET,
                TriggerSource.OWNER,
                lambda b, _: (
                    _damage(
                        f"operation.weapon.{b.key}.shield_counter",
                        _attack(0.70),
                        damage_type=TRUE_DAMAGE_ID,
                        can_critical=False,
                    ),
                ),
            ),
            offense=5,
            survival=8,
            volatility=4,
        ),
        _support(
            "self_cost",
            _active_support(
                lambda b, _: (ChangeResource(f"operation.weapon.{b.key}.blood_cost", HEALTH_CURRENT, _attack(-0.22)),)
            ),
            offense=5,
            volatility=8,
        ),
    ),
    targeting=(
        TargetingMechanicDefinition("single", frozenset({"target.enemy.explicit", "target.enemy.first"}), 1, 1.0),
        TargetingMechanicDefinition("lowest", frozenset({"target.enemy.lowest_health"}), 1, 1.08),
        TargetingMechanicDefinition("random", frozenset({"target.enemy.random"}), 1, 1.0),
        TargetingMechanicDefinition("adjacent", frozenset({"target.enemy.adjacent"}), 3, 1.45),
        TargetingMechanicDefinition("all", frozenset({"target.enemy.all"}), None, 1.80),
    ),
)


__all__ = [
    "DAMAGE_CAP_INTERCEPTOR_ID",
    "DEATH_GUARD_INTERCEPTOR_ID",
    "IMMUNITY_INTERCEPTOR_ID",
    "OFFICIAL_WEAPON_MECHANICS",
    "TAUNT_CONSTRAINT_ID",
    "UNTARGETABLE_CONSTRAINT_ID",
    "WEAPON_CHARGE_EFFECT_ID",
    "WEAPON_MARK_EFFECT_ID",
]
