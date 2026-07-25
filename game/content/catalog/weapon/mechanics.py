"""把正式武器蓝图编译为可执行规则定义、随机属性和实例生成策略。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.gameplay import (
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    COMBAT_SPEED,
    HEALTH_CURRENT,
    HEALTH_MAXIMUM,
    LOADOUT_ITEM_COMPONENT_ID,
    SPIRIT_CURRENT,
    WEAPON_SLOT_ID,
    AbilityDefinition,
    BattleAbilityTargeting,
    AttributeMagnitude,
    ChangeResource,
    ChooseOne,
    Comparison,
    ConsumeEffectStacks,
    ContributionSpec,
    DealDamage,
    DispelEffects,
    EffectDefinition,
    EffectReference,
    EffectStacksMagnitude,
    EffectTarget,
    EventValueCondition,
    FixedMagnitude,
    GenerationProfileDefinition,
    GrantInterceptor,
    GrantShield,
    GrantTargetConstraint,
    GrantTrigger,
    Heal,
    InterceptorSide,
    ItemAssetKind,
    ItemDefinition,
    ItemizationKind,
    LoadoutItemComponent,
    ModifierLayer,
    MinimumMagnitude,
    ModifyAttribute,
    ModifyCooldown,
    ModifyCurrentCooldowns,
    ParameterMagnitude,
    ProductMagnitude,
    PropertyDefinition,
    PropertyParameterDefinition,
    PropertyTierDefinition,
    QualityValueBand,
    ReferenceValuationDefinition,
    ReferenceValueKind,
    RequestExtraTurn,
    RequestTurnDelay,
    ResourceCost,
    ResourceMagnitude,
    ResourceValueMode,
    StackingPolicy,
    SumMagnitude,
    TagSet,
    TargetConstraintDefinition,
    TargetConstraintKind,
    TransferResource,
    TriggerDefinition,
    TriggerOwner,
    TriggerSource,
    TriggerTarget,
    ValueVector,
    WeaponDefinition,
    WeaponLevelAttribute,
    WeaponMaximumLevelBand,
    WeaponMaximumLevelTable,
    WeaponQualityProfile,
    DamageInterceptorDefinition,
    DamageStage,
    ApplyControl,
)

from ..foundation import (
    COMMON_QUALITY_ID,
    EPIC_QUALITY_ID,
    FINE_QUALITY_ID,
    LEGENDARY_QUALITY_ID,
    QUALITY_IDS,
    RARE_QUALITY_ID,
)
from ..combat.stats import (
    COMBAT_ACCURACY,
    COMBAT_BLOCK_CHANCE,
    COMBAT_BLOCK_REDUCTION,
    COMBAT_CONTROL_CHANCE,
    COMBAT_CRITICAL_CHANCE,
    COMBAT_CRITICAL_DAMAGE,
    COMBAT_EVASION,
    COMBAT_FLAT_PENETRATION,
    COMBAT_HEALING_RATE,
    COMBAT_OUTGOING_RATE,
    COMBAT_RATE_PENETRATION,
    COMBAT_TENACITY,
    FIRE_DAMAGE_ID,
    FREEZE_CONTROL_ID,
    FROST_DAMAGE_ID,
    PHYSICAL_DAMAGE_ID,
    POISON_DAMAGE_ID,
    SLEEP_CONTROL_ID,
    STUN_CONTROL_ID,
    TRUE_DAMAGE_ID,
)
from .blueprints import WEAPON_BLUEPRINTS, WeaponBlueprint
from .balance import estimate_weapon_value
from .registry import OFFICIAL_WEAPON_MECHANICS


WEAPON_MARK_EFFECT_ID = "effect.weapon.shared_mark"
WEAPON_CHARGE_EFFECT_ID = "effect.weapon.shared_charge"
TAUNT_CONSTRAINT_ID = "target_constraint.weapon.taunt"
UNTARGETABLE_CONSTRAINT_ID = "target_constraint.weapon.untargetable"
DEATH_GUARD_INTERCEPTOR_ID = "interceptor.weapon.death_guard"
IMMUNITY_INTERCEPTOR_ID = "interceptor.weapon.immunity"
DAMAGE_CAP_INTERCEPTOR_ID = "interceptor.weapon.damage_cap"

QUALITY_BANDS = (
    QualityValueBand(COMMON_QUALITY_ID, 0, 62),
    QualityValueBand(FINE_QUALITY_ID, 62, 74),
    QualityValueBand(RARE_QUALITY_ID, 74, 84),
    QualityValueBand(EPIC_QUALITY_ID, 84, 100),
    QualityValueBand(LEGENDARY_QUALITY_ID, 100),
)

WEAPON_EXPERIENCE_REQUIREMENTS = tuple(
    60 + level * level * 4
    for level in range(1, 100)
)

WEAPON_MAXIMUM_LEVEL_TABLE = WeaponMaximumLevelTable(
    "weapon_maximum_level.standard",
    1,
    (
        WeaponMaximumLevelBand(20, 40, 450),
        WeaponMaximumLevelBand(41, 60, 280),
        WeaponMaximumLevelBand(61, 80, 180),
        WeaponMaximumLevelBand(81, 90, 60),
        WeaponMaximumLevelBand(91, 99, 25),
        WeaponMaximumLevelBand(100, 100, 5),
    ),
)


@dataclass(frozen=True)
class WeaponMechanicContent:
    items: tuple[ItemDefinition, ...]
    weapons: tuple[WeaponDefinition, ...]
    effects: tuple[EffectDefinition, ...]
    abilities: tuple[AbilityDefinition, ...]
    targeting: tuple[BattleAbilityTargeting, ...]
    triggers: tuple[TriggerDefinition, ...]
    interceptors: tuple[DamageInterceptorDefinition, ...]
    constraints: tuple[TargetConstraintDefinition, ...]
    properties: tuple[PropertyDefinition, ...]
    profiles: tuple[GenerationProfileDefinition, ...]
    reference_valuations: tuple[ReferenceValuationDefinition, ...]
    display_ids: frozenset[str]


def _attack(scale: float = 1.0, *, owner: str = "source") -> AttributeMagnitude:
    return AttributeMagnitude(COMBAT_ATTACK, owner=owner, scale=scale)


def _ability_targeting(
    blueprint: WeaponBlueprint,
    ability_id: str,
) -> BattleAbilityTargeting:
    targeting = OFFICIAL_WEAPON_MECHANICS.resolve(blueprint).targeting
    return BattleAbilityTargeting(
        ability_id,
        targeting.allowed_selectors,
        targeting.maximum_targets,
    )


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


def _base_damage_operations(blueprint: WeaponBlueprint) -> tuple[object, ...]:
    key = blueprint.key
    power = blueprint.power
    if blueprint.primary == "multi2":
        return tuple(_damage(f"operation.weapon.{key}.hit_{index}", _attack(power)) for index in range(1, 3))
    if blueprint.primary == "multi3":
        return tuple(_damage(f"operation.weapon.{key}.hit_{index}", _attack(power)) for index in range(1, 4))
    if blueprint.primary == "execute":
        magnitude = SumMagnitude(
            (
                _attack(power),
                ResourceMagnitude(
                    HEALTH_CURRENT,
                    mode=ResourceValueMode.MISSING,
                    maximum_attribute_id=HEALTH_MAXIMUM,
                    scale=0.22,
                ),
            )
        )
        return (_damage(f"operation.weapon.{key}.execute", magnitude),)
    if blueprint.primary == "missing_rage":
        magnitude = SumMagnitude(
            (
                _attack(power),
                ResourceMagnitude(
                    HEALTH_CURRENT,
                    owner="source",
                    mode=ResourceValueMode.MISSING,
                    maximum_attribute_id=HEALTH_MAXIMUM,
                    scale=0.16,
                ),
            )
        )
        return (_damage(f"operation.weapon.{key}.rage", magnitude),)
    if blueprint.primary == "max_health":
        magnitude = SumMagnitude((_attack(power), AttributeMagnitude(HEALTH_MAXIMUM, owner="target", scale=0.055)))
        return (
            DealDamage(
                f"operation.weapon.{key}.crush",
                PHYSICAL_DAMAGE_ID,
                magnitude,
                maximum_target_health_ratio=0.16,
            ),
        )
    if blueprint.primary == "true_strike":
        return (_damage(f"operation.weapon.{key}.true", _attack(power), damage_type=TRUE_DAMAGE_ID),)
    if blueprint.primary == "pierce":
        return (_damage(f"operation.weapon.{key}.pierce", _attack(power), bypass_shield=True),)
    if blueprint.primary in {"poison", "bleed", "burn", "frost"}:
        damage_type = {
            "poison": POISON_DAMAGE_ID,
            "bleed": PHYSICAL_DAMAGE_ID,
            "burn": FIRE_DAMAGE_ID,
            "frost": FROST_DAMAGE_ID,
        }[blueprint.primary]
        return (_damage(f"operation.weapon.{key}.{blueprint.primary}", _attack(power), damage_type=damage_type),)
    if blueprint.primary == "spirit_drain":
        return (
            _damage(f"operation.weapon.{key}.drain_hit", _attack(power)),
            TransferResource(
                f"operation.weapon.{key}.drain_spirit",
                SPIRIT_CURRENT,
                FixedMagnitude(12),
                efficiency=0.75,
            ),
        )
    if blueprint.primary == "spirit_burst":
        return (
            _damage(
                f"operation.weapon.{key}.spirit_burst",
                SumMagnitude(
                    (
                        _attack(power),
                        ResourceMagnitude(SPIRIT_CURRENT, owner="source", scale=0.22),
                    )
                ),
            ),
        )
    if blueprint.primary == "element_cycle":
        return (
            _damage(f"operation.weapon.{key}.fire", _attack(power * 0.45), damage_type=FIRE_DAMAGE_ID),
            _damage(f"operation.weapon.{key}.frost", _attack(power * 0.35), damage_type=FROST_DAMAGE_ID),
            _damage(
                f"operation.weapon.{key}.true",
                _attack(power * 0.20),
                damage_type=TRUE_DAMAGE_ID,
                can_critical=False,
            ),
        )
    if blueprint.primary == "detonate":
        magnitude = SumMagnitude(
            (
                _attack(power),
                ProductMagnitude((_attack(0.28), EffectStacksMagnitude(WEAPON_MARK_EFFECT_ID))),
            )
        )
        return (
            _damage(f"operation.weapon.{key}.detonate", magnitude, damage_type=FIRE_DAMAGE_ID),
            ConsumeEffectStacks(
                f"operation.weapon.{key}.consume_mark",
                WEAPON_MARK_EFFECT_ID,
                stacks=5,
            ),
        )
    if blueprint.primary == "self_cost":
        return (_damage(f"operation.weapon.{key}.sacrifice", _attack(power)),)
    if blueprint.primary == "volatile":
        return (
            ChooseOne(
                f"operation.weapon.{key}.volatile",
                (
                    (
                        _damage(
                            f"operation.weapon.{key}.low",
                            _attack(power * 0.45),
                            can_critical=False,
                        ),
                    ),
                    (
                        _damage(
                            f"operation.weapon.{key}.high",
                            _attack(power * 1.65),
                        ),
                    ),
                ),
            ),
        )
    if blueprint.primary == "borrowed_force":
        borrowed = MinimumMagnitude(
            (
                _attack(0.38, owner="target"),
                _attack(0.50),
            )
        )
        return (
            _damage(
                f"operation.weapon.{key}.borrowed_force",
                SumMagnitude((_attack(power), borrowed)),
            ),
        )
    if blueprint.primary == "deferred_echo":
        return (
            _damage(
                f"operation.weapon.{key}.echo_opening",
                _attack(power),
            ),
        )
    if blueprint.primary in {"heavy", "swift", "mark"}:
        return (_damage(f"operation.weapon.{key}.strike", _attack(power)),)
    raise ValueError(f"主机制已注册但缺少执行编译器：{blueprint.primary}")


def _status_content(
    blueprint: WeaponBlueprint,
) -> tuple[tuple[EffectDefinition, ...], tuple[TriggerDefinition, ...], tuple[EffectReference, ...]]:
    if blueprint.primary == "deferred_echo":
        key = blueprint.key
        status_id = f"effect.weapon.{key}.echo_status"
        release_id = f"effect.weapon.{key}.echo_release"
        trigger_id = f"trigger.weapon.{key}.echo_release"
        effects = (
            EffectDefinition(
                status_id,
                tags=TagSet.of("status.negative", "status.delayed_echo"),
                operations=(
                    GrantTrigger(
                        f"operation.weapon.{key}.grant_echo_release",
                        trigger_id,
                    ),
                ),
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
        triggers = (
            TriggerDefinition(
                trigger_id,
                "combat.turn.started",
                release_id,
                target=TriggerTarget.OWNER,
                owner=TriggerOwner.EVENT_SOURCE,
                source=TriggerSource.GRANT_SOURCE,
                max_activations_per_execution=1,
            ),
        )
        return effects, triggers, (EffectReference(status_id, EffectTarget.TARGET),)
    if blueprint.primary not in {"poison", "bleed", "burn"} and blueprint.support not in {"poison", "bleed", "burn"}:
        return (), (), ()
    ailment = blueprint.primary if blueprint.primary in {"poison", "bleed", "burn"} else blueprint.support
    key = blueprint.key
    status_id = f"effect.weapon.{key}.{ailment}_status"
    tick_id = f"effect.weapon.{key}.{ailment}_tick"
    trigger_id = f"trigger.weapon.{key}.{ailment}_tick"
    damage_type = {"poison": POISON_DAMAGE_ID, "bleed": PHYSICAL_DAMAGE_ID, "burn": FIRE_DAMAGE_ID}[ailment]
    effects = (
        EffectDefinition(
            status_id,
            tags=TagSet.of("status.negative", f"status.ailment.{ailment}"),
            operations=(GrantTrigger(f"operation.weapon.{key}.grant_{ailment}_tick", trigger_id),),
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
                    ProductMagnitude(
                        (
                            _attack(0.16),
                            ParameterMagnitude("effect.stacks"),
                        )
                    ),
                    damage_type=damage_type,
                    can_critical=False,
                    tags=TagSet.of("damage.periodic", f"damage.{ailment}"),
                ),
            ),
        ),
    )
    triggers = (
        TriggerDefinition(
            trigger_id,
            "combat.turn.started",
            tick_id,
            target=TriggerTarget.OWNER,
            owner=TriggerOwner.EVENT_SOURCE,
            source=TriggerSource.GRANT_SOURCE,
            max_activations_per_execution=1,
        ),
    )
    return effects, triggers, (EffectReference(status_id),)


def _support_effect(
    blueprint: WeaponBlueprint,
    ability_id: str,
) -> tuple[tuple[EffectDefinition, ...], tuple[EffectReference, ...]]:
    key = blueprint.key
    support = blueprint.support
    if support in {"none", "poison", "bleed", "burn", "lifesteal", "thorns", "on_crit", "on_kill", "cooldown", "evasion_counter", "on_crit_stun", "on_kill_heal", "shield_counter"}:
        return (), ()
    effect_id = f"effect.weapon.{key}.support"
    target = EffectTarget.SELF
    duration: int | None = 0
    tags = TagSet.of("status.positive")
    operations: tuple[object, ...]
    if support == "sunder":
        target, duration, tags = EffectTarget.TARGET, 2, TagSet.of("status.negative", "status.sunder")
        operations = (ModifyAttribute(f"operation.weapon.{key}.sunder", COMBAT_DEFENSE, ModifierLayer.GLOBAL_FLAT, FixedMagnitude(-12)),)
    elif support == "slow":
        target, duration, tags = EffectTarget.TARGET, 2, TagSet.of("status.negative", "status.slow")
        operations = (ModifyAttribute(f"operation.weapon.{key}.slow", COMBAT_SPEED, ModifierLayer.GLOBAL_FLAT, FixedMagnitude(-15)),)
    elif support == "weaken":
        target, duration, tags = EffectTarget.TARGET, 2, TagSet.of("status.negative", "status.weaken")
        operations = (ModifyAttribute(f"operation.weapon.{key}.weaken", COMBAT_ATTACK, ModifierLayer.GLOBAL_FLAT, FixedMagnitude(-10)),)
    elif support == "haste":
        duration = 2
        operations = (ModifyAttribute(f"operation.weapon.{key}.haste", COMBAT_SPEED, ModifierLayer.GLOBAL_FLAT, FixedMagnitude(16)),)
    elif support == "guard":
        duration = 2
        operations = (ModifyAttribute(f"operation.weapon.{key}.guard", COMBAT_DEFENSE, ModifierLayer.GLOBAL_FLAT, FixedMagnitude(16)),)
    elif support == "crit":
        duration = 2
        operations = (ModifyAttribute(f"operation.weapon.{key}.crit", COMBAT_CRITICAL_CHANCE, ModifierLayer.GLOBAL_FLAT, FixedMagnitude(0.14)),)
    elif support == "evasion":
        duration = 2
        operations = (ModifyAttribute(f"operation.weapon.{key}.evasion", COMBAT_EVASION, ModifierLayer.GLOBAL_FLAT, FixedMagnitude(0.14)),)
    elif support == "block":
        duration = 2
        operations = (
            ModifyAttribute(f"operation.weapon.{key}.block_chance", COMBAT_BLOCK_CHANCE, ModifierLayer.GLOBAL_FLAT, FixedMagnitude(0.16)),
            ModifyAttribute(f"operation.weapon.{key}.block_reduction", COMBAT_BLOCK_REDUCTION, ModifierLayer.GLOBAL_FLAT, FixedMagnitude(0.20)),
        )
    elif support == "heal":
        operations = (Heal(f"operation.weapon.{key}.heal", _attack(0.32)),)
    elif support == "shield":
        operations = (GrantShield(f"operation.weapon.{key}.shield", _attack(0.60), maximum_target_health_ratio=0.35),)
    elif support == "stun":
        target, tags = EffectTarget.TARGET, TagSet.of("status.negative", "status.control")
        operations = (ApplyControl(f"operation.weapon.{key}.stun", STUN_CONTROL_ID),)
    elif support == "freeze":
        target, tags = EffectTarget.TARGET, TagSet.of("status.negative", "status.control")
        operations = (ApplyControl(f"operation.weapon.{key}.freeze", FREEZE_CONTROL_ID),)
    elif support == "sleep":
        target, tags = EffectTarget.TARGET, TagSet.of("status.negative", "status.control")
        operations = (ApplyControl(f"operation.weapon.{key}.sleep", SLEEP_CONTROL_ID),)
    elif support == "extra_turn":
        operations = (RequestExtraTurn(f"operation.weapon.{key}.extra_turn"),)
    elif support == "delay":
        target = EffectTarget.TARGET
        operations = (RequestTurnDelay(f"operation.weapon.{key}.delay", positions=1),)
    elif support == "cooldown_delay":
        target = EffectTarget.TARGET
        operations = (
            ModifyCurrentCooldowns(
                f"operation.weapon.{key}.cooldown_delay",
                turns=1,
                selection="longest",
            ),
        )
    elif support == "spirit_drain":
        target = EffectTarget.TARGET
        operations = (TransferResource(f"operation.weapon.{key}.spirit_drain", SPIRIT_CURRENT, FixedMagnitude(10), 0.6),)
    elif support == "self_cost":
        operations = (ChangeResource(f"operation.weapon.{key}.blood_cost", HEALTH_CURRENT, _attack(-0.22)),)
    elif support == "resource_balance":
        operations = (
            Heal(
                f"operation.weapon.{key}.balance_health",
                ResourceMagnitude(HEALTH_CURRENT, owner="source", mode=ResourceValueMode.MISSING, maximum_attribute_id=HEALTH_MAXIMUM, scale=0.18),
            ),
            ChangeResource(f"operation.weapon.{key}.balance_spirit", SPIRIT_CURRENT, FixedMagnitude(10)),
        )
    elif support == "dispel":
        target = EffectTarget.TARGET
        operations = (DispelEffects(f"operation.weapon.{key}.dispel", required_tags=TagSet.of("status.positive"), maximum=1),)
    elif support == "mark":
        target, duration, tags = EffectTarget.TARGET, 4, TagSet.of("status.negative", "status.weapon_mark")
        effect_id = WEAPON_MARK_EFFECT_ID
        operations = ()
    elif support == "detonate":
        target = EffectTarget.TARGET
        operations = (
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
    elif support == "execute":
        target = EffectTarget.TARGET
        operations = (
            _damage(
                f"operation.weapon.{key}.support_execute",
                ResourceMagnitude(
                    HEALTH_CURRENT,
                    mode=ResourceValueMode.MISSING,
                    maximum_attribute_id=HEALTH_MAXIMUM,
                    scale=0.14,
                ),
                can_critical=False,
            ),
        )
    elif support == "mark_self":
        duration, tags = 5, TagSet.of("status.positive", "status.weapon_charge")
        effect_id = WEAPON_CHARGE_EFFECT_ID
        operations = (ModifyAttribute("operation.weapon.shared_charge", COMBAT_ATTACK, ModifierLayer.GLOBAL_FLAT, FixedMagnitude(3)),)
    elif support == "death_guard":
        duration = 1
        operations = (GrantInterceptor(f"operation.weapon.{key}.death_guard", DEATH_GUARD_INTERCEPTOR_ID),)
    elif support == "immunity":
        duration = 1
        operations = (GrantInterceptor(f"operation.weapon.{key}.immunity", IMMUNITY_INTERCEPTOR_ID),)
    elif support == "damage_cap":
        duration = 2
        operations = (GrantInterceptor(f"operation.weapon.{key}.damage_cap", DAMAGE_CAP_INTERCEPTOR_ID),)
    elif support == "taunt":
        target, duration, tags = EffectTarget.TARGET, 2, TagSet.of("status.negative", "status.taunted")
        operations = (GrantTargetConstraint(f"operation.weapon.{key}.taunt", TAUNT_CONSTRAINT_ID),)
    else:
        raise ValueError(f"辅助机制已注册但缺少执行编译器：{support}")
    stacking = StackingPolicy.STACK if effect_id in {WEAPON_MARK_EFFECT_ID, WEAPON_CHARGE_EFFECT_ID} else StackingPolicy.REFRESH
    maximum = 5 if stacking is StackingPolicy.STACK else 1
    definition = EffectDefinition(
        effect_id,
        tags=tags,
        operations=operations,
        duration_turns=duration,
        stacking=stacking,
        max_stacks=maximum,
        stack_by_source=effect_id == WEAPON_MARK_EFFECT_ID,
    )
    return (definition,), (EffectReference(effect_id, target),)


def _passive_content(
    blueprint: WeaponBlueprint,
    ability_id: str,
) -> tuple[tuple[EffectDefinition, ...], tuple[TriggerDefinition, ...], frozenset[str]]:
    support = blueprint.support
    if support not in {"lifesteal", "thorns", "on_crit", "on_kill", "cooldown", "evasion_counter", "on_crit_stun", "on_kill_heal", "shield_counter"}:
        return (), (), frozenset()
    key = blueprint.key
    effect_id = f"effect.weapon.{key}.passive"
    trigger_id = f"trigger.weapon.{key}.passive"
    conditions = ()
    if support == "lifesteal":
        event_kind, target, owner, source = "combat.damage.dealt", TriggerTarget.OWNER, TriggerOwner.EVENT_SOURCE, TriggerSource.OWNER
        operations = (Heal(f"operation.weapon.{key}.lifesteal", ParameterMagnitude("event.effective_damage", scale=0.22)),)
    elif support == "thorns":
        event_kind, target, owner, source = "combat.damage.dealt", TriggerTarget.EVENT_SOURCE, TriggerOwner.EVENT_TARGET, TriggerSource.OWNER
        conditions = (EventValueCondition(f"condition.weapon.{key}.not_proc", "damage_type", Comparison.NOT_EQUAL, TRUE_DAMAGE_ID),)
        operations = (_damage(f"operation.weapon.{key}.thorns", ParameterMagnitude("event.effective_damage", scale=0.28), damage_type=TRUE_DAMAGE_ID, can_critical=False),)
    elif support in {"on_crit", "on_crit_stun"}:
        event_kind, target, owner, source = "combat.attack.critical", TriggerTarget.EVENT_TARGET, TriggerOwner.EVENT_SOURCE, TriggerSource.OWNER
        operations = [_damage(f"operation.weapon.{key}.critical_echo", _attack(0.34), damage_type=TRUE_DAMAGE_ID, can_critical=False)]
        if support == "on_crit_stun":
            operations.append(ApplyControl(f"operation.weapon.{key}.critical_stun", STUN_CONTROL_ID))
        operations = tuple(operations)
    elif support in {"on_kill", "on_kill_heal"}:
        event_kind, target, owner, source = "combat.target.defeated", TriggerTarget.OWNER, TriggerOwner.EVENT_SOURCE, TriggerSource.OWNER
        operations = (RequestExtraTurn(f"operation.weapon.{key}.kill_turn"),) if support == "on_kill" else (Heal(f"operation.weapon.{key}.kill_heal", _attack(0.65)),)
    elif support == "cooldown":
        event_kind, target, owner, source = "combat.target.defeated", TriggerTarget.OWNER, TriggerOwner.EVENT_SOURCE, TriggerSource.OWNER
        operations = (ModifyCooldown(f"operation.weapon.{key}.reset", ability_id, set_to=0),)
    elif support == "evasion_counter":
        event_kind, target, owner, source = "combat.attack.missed", TriggerTarget.EVENT_SOURCE, TriggerOwner.EVENT_TARGET, TriggerSource.OWNER
        operations = (_damage(f"operation.weapon.{key}.evade_counter", _attack(0.55), damage_type=TRUE_DAMAGE_ID, can_critical=False),)
    else:
        event_kind, target, owner, source = "combat.shield.broken", TriggerTarget.EVENT_SOURCE, TriggerOwner.EVENT_TARGET, TriggerSource.OWNER
        operations = (_damage(f"operation.weapon.{key}.shield_counter", _attack(0.70), damage_type=TRUE_DAMAGE_ID, can_critical=False),)
    effect = EffectDefinition(effect_id, operations=operations)
    trigger = TriggerDefinition(
        trigger_id,
        event_kind,
        effect_id,
        target=target,
        owner=owner,
        source=source,
        conditions=conditions,
        max_activations_per_execution=1,
    )
    return (effect,), (trigger,), frozenset({trigger_id})


def _core_property(
    blueprint: WeaponBlueprint,
    ability_id: str,
    passive_triggers: frozenset[str],
) -> PropertyDefinition:
    contribution = ContributionSpec(
        tags=TagSet.of(
            "weapon.core",
            f"weapon.domain.{blueprint.domain}",
            f"weapon.primary.{blueprint.primary}",
            f"weapon.support.{blueprint.support}",
            f"weapon.targeting.{blueprint.targeting}",
        ),
        abilities=frozenset({ability_id}),
        triggers=passive_triggers,
    )
    return PropertyDefinition(
        f"property.weapon_core.{blueprint.key}",
        1,
        (PropertyTierDefinition(1, 1, contribution),),
        tags=contribution.tags,
    )


def _parameter_property(
    key: str,
    attribute_id: str,
    layer: ModifierLayer,
    ranges: tuple[tuple[float, float, float], ...],
    *,
    domains: tuple[str, ...] = (),
) -> PropertyDefinition:
    required = TagSet.of(*(f"weapon.domain.{value}" for value in domains)) if len(domains) == 1 else TagSet()
    tiers = tuple(
        PropertyTierDefinition(
            tier=index,
            weight=(60, 30, 10)[index - 1],
            parameters=(
                PropertyParameterDefinition(
                    f"parameter.weapon.{key}",
                    attribute_id,
                    layer,
                    minimum,
                    maximum,
                    step,
                ),
            ),
        )
        for index, (minimum, maximum, step) in enumerate(ranges, start=1)
    )
    return PropertyDefinition(
        f"property.weapon_affix.{key}",
        10,
        tiers,
        tags=TagSet.of(f"weapon.affix.{key}"),
        required_selected_tags=required,
    )


UNIVERSAL_WEAPON_PROPERTIES = (
    _parameter_property("attack", COMBAT_ATTACK, ModifierLayer.LOCAL_FLAT, ((4, 8, 1), (9, 14, 1), (15, 22, 1))),
    _parameter_property("defense", COMBAT_DEFENSE, ModifierLayer.LOCAL_FLAT, ((4, 8, 1), (9, 14, 1), (15, 22, 1))),
    _parameter_property("speed", COMBAT_SPEED, ModifierLayer.LOCAL_FLAT, ((3, 6, 1), (7, 11, 1), (12, 18, 1))),
    _parameter_property("accuracy", COMBAT_ACCURACY, ModifierLayer.GLOBAL_FLAT, ((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.13, 0.01))),
    _parameter_property("outgoing", COMBAT_OUTGOING_RATE, ModifierLayer.GLOBAL_FLAT, ((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.12, 0.01))),
    _parameter_property("tenacity", COMBAT_TENACITY, ModifierLayer.GLOBAL_FLAT, ((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.12, 0.01))),
)

DOMAIN_WEAPON_PROPERTIES = {
    "burst": (
        _parameter_property("burst_critical", COMBAT_CRITICAL_DAMAGE, ModifierLayer.GLOBAL_FLAT, ((0.05, 0.10, 0.01), (0.11, 0.18, 0.01), (0.19, 0.28, 0.01)), domains=("burst",)),
        _parameter_property("burst_penetration", COMBAT_FLAT_PENETRATION, ModifierLayer.GLOBAL_FLAT, ((3, 6, 1), (7, 11, 1), (12, 18, 1)), domains=("burst",)),
    ),
    "tempo": (
        _parameter_property("tempo_critical", COMBAT_CRITICAL_CHANCE, ModifierLayer.GLOBAL_FLAT, ((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.13, 0.01)), domains=("tempo",)),
        _parameter_property("tempo_evasion", COMBAT_EVASION, ModifierLayer.GLOBAL_FLAT, ((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.13, 0.01)), domains=("tempo",)),
    ),
    "ailment": (
        _parameter_property("ailment_rate", COMBAT_OUTGOING_RATE, ModifierLayer.GLOBAL_FLAT, ((0.03, 0.05, 0.01), (0.06, 0.09, 0.01), (0.10, 0.14, 0.01)), domains=("ailment",)),
        _parameter_property("ailment_control", COMBAT_CONTROL_CHANCE, ModifierLayer.GLOBAL_FLAT, ((0.02, 0.04, 0.01), (0.05, 0.08, 0.01), (0.09, 0.12, 0.01)), domains=("ailment",)),
    ),
    "resource": (
        _parameter_property("resource_healing", COMBAT_HEALING_RATE, ModifierLayer.GLOBAL_FLAT, ((0.03, 0.06, 0.01), (0.07, 0.11, 0.01), (0.12, 0.18, 0.01)), domains=("resource",)),
        _parameter_property("resource_attack", COMBAT_ATTACK, ModifierLayer.LOCAL_FLAT, ((5, 9, 1), (10, 16, 1), (17, 24, 1)), domains=("resource",)),
    ),
    "guard": (
        _parameter_property("guard_block", COMBAT_BLOCK_CHANCE, ModifierLayer.GLOBAL_FLAT, ((0.03, 0.05, 0.01), (0.06, 0.09, 0.01), (0.10, 0.14, 0.01)), domains=("guard",)),
        _parameter_property("guard_reduction", COMBAT_BLOCK_REDUCTION, ModifierLayer.GLOBAL_FLAT, ((0.04, 0.08, 0.01), (0.09, 0.14, 0.01), (0.15, 0.22, 0.01)), domains=("guard",)),
    ),
    "control": (
        _parameter_property("control_chance", COMBAT_CONTROL_CHANCE, ModifierLayer.GLOBAL_FLAT, ((0.03, 0.05, 0.01), (0.06, 0.10, 0.01), (0.11, 0.16, 0.01)), domains=("control",)),
        _parameter_property("control_speed", COMBAT_SPEED, ModifierLayer.LOCAL_FLAT, ((4, 7, 1), (8, 12, 1), (13, 19, 1)), domains=("control",)),
    ),
    "targeting": (
        _parameter_property("targeting_penetration", COMBAT_RATE_PENETRATION, ModifierLayer.GLOBAL_FLAT, ((0.03, 0.05, 0.01), (0.06, 0.09, 0.01), (0.10, 0.15, 0.01)), domains=("targeting",)),
        _parameter_property("targeting_accuracy", COMBAT_ACCURACY, ModifierLayer.GLOBAL_FLAT, ((0.03, 0.05, 0.01), (0.06, 0.10, 0.01), (0.11, 0.16, 0.01)), domains=("targeting",)),
    ),
    "reaction": (
        _parameter_property("reaction_evasion", COMBAT_EVASION, ModifierLayer.GLOBAL_FLAT, ((0.03, 0.05, 0.01), (0.06, 0.10, 0.01), (0.11, 0.16, 0.01)), domains=("reaction",)),
        _parameter_property("reaction_critical", COMBAT_CRITICAL_CHANCE, ModifierLayer.GLOBAL_FLAT, ((0.03, 0.05, 0.01), (0.06, 0.10, 0.01), (0.11, 0.16, 0.01)), domains=("reaction",)),
    ),
    "risk": (
        _parameter_property("risk_damage", COMBAT_OUTGOING_RATE, ModifierLayer.GLOBAL_FLAT, ((0.04, 0.07, 0.01), (0.08, 0.13, 0.01), (0.14, 0.20, 0.01)), domains=("risk",)),
        _parameter_property("risk_critical", COMBAT_CRITICAL_DAMAGE, ModifierLayer.GLOBAL_FLAT, ((0.06, 0.11, 0.01), (0.12, 0.20, 0.01), (0.21, 0.30, 0.01)), domains=("risk",)),
    ),
}


def _quality_profiles() -> dict[str, WeaponQualityProfile]:
    bases = (3.0, 4.0, 5.0, 6.0, 8.0)
    growth = (0.60, 0.80, 1.00, 1.25, 1.55)
    return {
        quality_id: WeaponQualityProfile(
            quality_id,
            WEAPON_EXPERIENCE_REQUIREMENTS,
            level_attributes=(
                WeaponLevelAttribute(
                    COMBAT_ATTACK,
                    ModifierLayer.LOCAL_FLAT,
                    tuple(round(bases[index] + (level - 1) * growth[index], 2) for level in range(1, 101)),
                ),
            ),
        )
        for index, quality_id in enumerate(QUALITY_IDS)
    }


def build_weapon_mechanic_content() -> WeaponMechanicContent:
    OFFICIAL_WEAPON_MECHANICS.validate_blueprints(WEAPON_BLUEPRINTS)
    effects: dict[str, EffectDefinition] = {
        WEAPON_MARK_EFFECT_ID: EffectDefinition(
            WEAPON_MARK_EFFECT_ID,
            tags=TagSet.of("status.negative", "status.weapon_mark"),
            duration_turns=4,
            stacking=StackingPolicy.STACK,
            max_stacks=5,
            stack_by_source=True,
        ),
        WEAPON_CHARGE_EFFECT_ID: EffectDefinition(
            WEAPON_CHARGE_EFFECT_ID,
            tags=TagSet.of("status.positive", "status.weapon_charge"),
            operations=(ModifyAttribute("operation.weapon.shared_charge", COMBAT_ATTACK, ModifierLayer.GLOBAL_FLAT, FixedMagnitude(3)),),
            duration_turns=5,
            stacking=StackingPolicy.STACK,
            max_stacks=5,
        ),
    }
    abilities = []
    targeting = []
    triggers = []
    items = []
    weapons = []
    core_properties = []
    profiles = []
    valuations = []
    display_ids: set[str] = set()
    qualities = _quality_profiles()
    for blueprint in WEAPON_BLUEPRINTS:
        key = blueprint.key
        ability_id = f"ability.weapon.{key}"
        strike_id = f"effect.weapon.{key}.strike"
        effects[strike_id] = EffectDefinition(strike_id, operations=_base_damage_operations(blueprint))
        status_effects, status_triggers, status_refs = _status_content(blueprint)
        support_effects, support_refs = _support_effect(blueprint, ability_id)
        passive_effects, passive_triggers, granted_triggers = _passive_content(blueprint, ability_id)
        for definition in (*status_effects, *support_effects, *passive_effects):
            previous = effects.get(definition.id)
            if previous is not None and previous != definition:
                raise ValueError(f"武器 Effect 定义冲突：{definition.id}")
            effects[definition.id] = definition
        triggers.extend((*status_triggers, *passive_triggers))
        costs = () if blueprint.spirit_cost == 0 else (ResourceCost(SPIRIT_CURRENT, FixedMagnitude(blueprint.spirit_cost)),)
        extra_refs: list[EffectReference] = []
        if blueprint.primary in {"mark", "detonate"}:
            extra_refs.append(EffectReference(WEAPON_MARK_EFFECT_ID))
        if blueprint.primary == "self_cost":
            blood_cost_id = f"effect.weapon.{key}.blood_cost"
            effects[blood_cost_id] = EffectDefinition(
                blood_cost_id,
                operations=(
                    ChangeResource(
                        f"operation.weapon.{key}.primary_blood_cost",
                        HEALTH_CURRENT,
                        _attack(-0.24),
                    ),
                ),
            )
            extra_refs.append(EffectReference(blood_cost_id, EffectTarget.SELF))
        ability = AbilityDefinition(
            ability_id,
            tags=TagSet.of(
                "ability.weapon",
                f"weapon.targeting.{blueprint.targeting}",
                f"weapon.domain.{blueprint.domain}",
            ),
            costs=costs,
            effects=(EffectReference(strike_id), *status_refs, *support_refs, *extra_refs),
            cooldown_turns=blueprint.cooldown,
        )
        abilities.append(ability)
        targeting.append(_ability_targeting(blueprint, ability_id))
        core = _core_property(blueprint, ability_id, granted_triggers)
        core_properties.append(core)
        domain_properties = DOMAIN_WEAPON_PROPERTIES[blueprint.domain]
        profile = GenerationProfileDefinition(
            f"generation.weapon.{key}",
            ItemizationKind.WEAPON,
            frozenset({core.id, *(value.id for value in UNIVERSAL_WEAPON_PROPERTIES), *(value.id for value in domain_properties)}),
            2,
            4,
            QUALITY_BANDS,
            core_property_ids=frozenset({core.id}),
            enforce_compatibility=True,
            maximum_attempts=8,
        )
        profiles.append(profile)
        item_id = f"item.weapon.{key}"
        weapon_id = f"weapon.{key}"
        items.append(
            ItemDefinition(
                item_id,
                ItemAssetKind.INSTANCE,
                TagSet.of("item.weapon", "item.armament"),
                components={
                    LOADOUT_ITEM_COMPONENT_ID: LoadoutItemComponent(frozenset({WEAPON_SLOT_ID}))
                },
            )
        )
        weapons.append(
            WeaponDefinition(
                weapon_id,
                item_id,
                ContributionSpec(tags=TagSet.of(f"weapon.identity.{key}")),
                qualities,
                generation_profile_id=profile.id,
            )
        )
        valuations.append(
            ReferenceValuationDefinition(
                ReferenceValueKind.ABILITY,
                ability_id,
                estimate_weapon_value(blueprint).estimated,
            )
        )
        for trigger_id in granted_triggers:
            valuations.append(
                ReferenceValuationDefinition(
                    ReferenceValueKind.TRIGGER,
                    trigger_id,
                    ValueVector(offense=4, sustain=2, tempo=2, volatility=2),
                )
            )
        display_ids.update((weapon_id, item_id, ability_id))
    all_secondary = (*UNIVERSAL_WEAPON_PROPERTIES, *(value for group in DOMAIN_WEAPON_PROPERTIES.values() for value in group))
    all_properties = (*all_secondary, *core_properties)
    display_ids.update(value.id for value in all_properties)
    return WeaponMechanicContent(
        tuple(items),
        tuple(weapons),
        tuple(effects.values()),
        tuple(abilities),
        tuple(targeting),
        tuple(triggers),
        (
            DamageInterceptorDefinition(
                DEATH_GUARD_INTERCEPTOR_ID,
                "interceptor.death_guard",
                DamageStage.BEFORE_SHIELD,
                InterceptorSide.TARGET,
                configuration={"minimum_health": 1},
            ),
            DamageInterceptorDefinition(
                IMMUNITY_INTERCEPTOR_ID,
                "interceptor.immunity",
                DamageStage.RAW,
                InterceptorSide.TARGET,
            ),
            DamageInterceptorDefinition(
                DAMAGE_CAP_INTERCEPTOR_ID,
                "interceptor.cap",
                DamageStage.AFTER_RATES,
                InterceptorSide.TARGET,
                configuration={"maximum": 80},
            ),
        ),
        (
            TargetConstraintDefinition(TAUNT_CONSTRAINT_ID, TargetConstraintKind.FORCE_GRANT_SOURCE),
            TargetConstraintDefinition(UNTARGETABLE_CONSTRAINT_ID, TargetConstraintKind.UNTARGETABLE),
        ),
        all_properties,
        tuple(profiles),
        tuple(valuations),
        frozenset(display_ids),
    )


WEAPON_MECHANIC_CONTENT = build_weapon_mechanic_content()


__all__ = [
    "DAMAGE_CAP_INTERCEPTOR_ID",
    "DEATH_GUARD_INTERCEPTOR_ID",
    "IMMUNITY_INTERCEPTOR_ID",
    "QUALITY_BANDS",
    "TAUNT_CONSTRAINT_ID",
    "UNTARGETABLE_CONSTRAINT_ID",
    "WEAPON_CHARGE_EFFECT_ID",
    "WEAPON_EXPERIENCE_REQUIREMENTS",
    "WEAPON_MARK_EFFECT_ID",
    "WEAPON_MAXIMUM_LEVEL_TABLE",
    "WEAPON_MECHANIC_CONTENT",
    "WeaponMechanicContent",
    "build_weapon_mechanic_content",
]
