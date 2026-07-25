"""正式武器的机制矩阵；名称属于世界皮肤，稳定键属于规则内容。"""

from __future__ import annotations

from dataclasses import dataclass

from game.core.gameplay import ValueVector


@dataclass(frozen=True)
class WeaponBlueprint:
    key: str
    domain: str
    primary: str
    support: str
    targeting: str
    power: float
    spirit_cost: int
    cooldown: int
    value: ValueVector


def _w(
    key: str,
    domain: str,
    primary: str,
    support: str,
    targeting: str,
    power: float,
    spirit_cost: int,
    cooldown: int,
    value: ValueVector,
) -> WeaponBlueprint:
    return WeaponBlueprint(
        key,
        domain,
        primary,
        support,
        targeting,
        power,
        spirit_cost,
        cooldown,
        value,
    )


WEAPON_BLUEPRINTS = (
    # 爆发与斩杀：一次行动内解决伤害形态，不制造虚假额外回合。
    _w("mountain_cleaver", "burst", "heavy", "sunder", "single", 1.85, 18, 2, ValueVector(offense=48, volatility=5)),
    _w("dawn_bane", "burst", "execute", "none", "lowest", 1.05, 22, 2, ValueVector(offense=52, volatility=8)),
    _w("star_piercer", "burst", "pierce", "crit", "single", 1.20, 16, 2, ValueVector(offense=46, tempo=4)),
    _w("war_breaker", "burst", "max_health", "delay", "single", 0.82, 24, 3, ValueVector(offense=42, tempo=5, control=7)),
    _w("ember_brand", "burst", "heavy", "burn", "adjacent", 1.45, 25, 3, ValueVector(offense=50, volatility=4)),
    _w("storm_maul", "burst", "multi2", "stun", "single", 0.72, 26, 3, ValueVector(offense=38, control=14)),
    _w("blood_reaper", "burst", "missing_rage", "lifesteal", "single", 1.00, 12, 2, ValueVector(offense=40, sustain=12, volatility=8)),
    _w("judgement_bow", "burst", "true_strike", "on_kill", "lowest", 1.08, 28, 3, ValueVector(offense=48, tempo=8)),

    # 连击与行动节奏。
    _w("flash_blade", "tempo", "multi3", "haste", "single", 0.46, 16, 2, ValueVector(offense=34, tempo=18)),
    _w("gearshade", "tempo", "multi2", "guard", "single", 0.68, 14, 1, ValueVector(offense=30, survival=12, tempo=8)),
    _w("moonstep_twins", "tempo", "multi2", "extra_turn", "single", 0.60, 30, 4, ValueVector(offense=30, tempo=24, volatility=6)),
    _w("gale_ring", "tempo", "swift", "delay", "random", 0.92, 8, 1, ValueVector(offense=28, tempo=16, control=5)),
    _w("blink_fang", "tempo", "true_strike", "evasion", "single", 0.82, 15, 2, ValueVector(offense=32, survival=8, tempo=12)),
    _w("continuum_rod", "tempo", "heavy", "cooldown", "single", 1.42, 22, 3, ValueVector(offense=40, tempo=13)),
    _w("soul_chaser", "tempo", "execute", "slow", "lowest", 0.92, 18, 2, ValueVector(offense=38, tempo=7, control=7)),
    _w("comet_shuttle", "tempo", "multi3", "on_crit", "random", 0.40, 20, 2, ValueVector(offense=38, tempo=12, volatility=7)),

    # 持续伤害与引爆。
    _w("plague_banner", "ailment", "poison", "mark", "all", 0.58, 24, 3, ValueVector(offense=40, control=4, volatility=8)),
    _w("cinder_lash", "ailment", "burn", "slow", "adjacent", 0.70, 20, 2, ValueVector(offense=38, control=8, tempo=4)),
    _w("hemorrhage_nail", "ailment", "bleed", "execute", "single", 0.72, 16, 2, ValueVector(offense=46, volatility=6)),
    _w("wither_fan", "ailment", "poison", "sunder", "all", 0.52, 28, 3, ValueVector(offense=39, control=8)),
    _w("heart_pyrelamp", "ailment", "burn", "spirit_drain", "single", 0.66, 18, 2, ValueVector(offense=36, sustain=8, control=5)),
    _w("frost_marrow_needle", "ailment", "frost", "freeze", "single", 0.74, 24, 3, ValueVector(offense=32, control=17)),
    _w("blight_staff", "ailment", "poison", "weaken", "all", 0.50, 30, 3, ValueVector(offense=34, survival=6, control=8)),
    _w("ashen_crucible", "ailment", "detonate", "burn", "all", 0.68, 32, 4, ValueVector(offense=52, volatility=10)),

    # 资源积累与消耗。
    _w("hidden_edge_coffer", "resource", "mark", "detonate", "single", 0.78, 18, 2, ValueVector(offense=43, tempo=5, volatility=7)),
    _w("mana_devourer", "resource", "spirit_drain", "heal", "single", 0.72, 10, 2, ValueVector(offense=25, sustain=20, control=5)),
    _w("blade_well", "resource", "multi2", "mark_self", "single", 0.62, 12, 1, ValueVector(offense=34, tempo=12, volatility=5)),
    _w("aether_orb", "resource", "spirit_burst", "shield", "single", 1.16, 30, 3, ValueVector(offense=38, survival=12, sustain=4)),
    _w("fate_ledger", "resource", "self_cost", "death_guard", "single", 1.72, 8, 3, ValueVector(offense=48, survival=8, volatility=12)),
    _w("soulburn_bell", "resource", "spirit_burst", "extra_turn", "single", 1.02, 38, 4, ValueVector(offense=34, tempo=22, volatility=7)),
    _w("equilibrium_chalice", "resource", "heavy", "resource_balance", "single", 1.20, 20, 3, ValueVector(offense=34, sustain=16, volatility=4)),
    _w("formless_wheel", "resource", "true_strike", "dispel", "single", 0.92, 26, 3, ValueVector(offense=40, control=12)),

    # 护盾、恢复与反制。
    _w("mountain_seal", "guard", "heavy", "shield", "single", 1.22, 22, 3, ValueVector(offense=32, survival=20)),
    _w("verdant_staff", "guard", "swift", "heal", "single", 0.82, 14, 1, ValueVector(offense=24, sustain=24)),
    _w("mirror_blade", "guard", "swift", "thorns", "single", 0.82, 16, 2, ValueVector(offense=30, survival=10, volatility=8)),
    _w("aegis_parasol", "guard", "multi2", "block", "single", 0.56, 18, 2, ValueVector(offense=26, survival=20)),
    _w("lifebond_chain", "guard", "heavy", "lifesteal", "single", 1.28, 24, 3, ValueVector(offense=34, sustain=18)),
    _w("phoenix_plume", "guard", "self_cost", "on_kill_heal", "lowest", 1.48, 12, 2, ValueVector(offense=42, sustain=12, volatility=9)),
    _w("tortoise_bulwark", "guard", "swift", "damage_cap", "single", 0.74, 20, 3, ValueVector(offense=20, survival=30)),
    _w("void_mirror", "guard", "true_strike", "immunity", "single", 0.72, 36, 5, ValueVector(offense=30, survival=24, volatility=8)),

    # 控制与规则干扰。
    _w("soul_bell", "control", "swift", "stun", "single", 0.72, 22, 2, ValueVector(offense=22, control=25)),
    _w("binding_codex", "control", "mark", "taunt", "single", 0.62, 24, 3, ValueVector(offense=20, control=28)),
    _w("dream_flute", "control", "swift", "sleep", "all", 0.44, 32, 4, ValueVector(offense=18, control=30, volatility=5)),
    _w("winter_rod", "control", "frost", "freeze", "adjacent", 0.58, 30, 4, ValueVector(offense=24, control=26)),
    _w("dragon_bind", "control", "heavy", "taunt", "single", 1.08, 25, 3, ValueVector(offense=30, control=20)),
    _w("gravity_tablet", "control", "max_health", "delay", "all", 0.48, 36, 5, ValueVector(offense=26, tempo=8, control=20)),
    _w("discord_harp", "control", "multi3", "weaken", "random", 0.34, 22, 2, ValueVector(offense=25, survival=8, control=14)),
    _w("null_blade", "control", "true_strike", "cooldown_delay", "single", 0.82, 30, 4, ValueVector(offense=32, tempo=8, control=15)),

    # 群攻、溅射与目标策略。
    _w("realm_fan", "targeting", "swift", "sunder", "all", 0.50, 24, 3, ValueVector(offense=38, control=8)),
    _w("ninefold_bow", "targeting", "multi3", "crit", "random", 0.36, 18, 2, ValueVector(offense=42, volatility=7)),
    _w("cloud_piercer", "targeting", "pierce", "delay", "adjacent", 0.78, 22, 3, ValueVector(offense=36, tempo=5, control=7)),
    _w("tide_breaker", "targeting", "heavy", "stun", "all", 0.68, 38, 5, ValueVector(offense=38, control=14)),
    _w("rift_blade", "targeting", "true_strike", "mark", "adjacent", 0.70, 26, 3, ValueVector(offense=42, volatility=5)),
    _w("prism_array", "targeting", "element_cycle", "none", "random", 0.94, 20, 2, ValueVector(offense=40, volatility=9)),
    _w("dragon_coil", "targeting", "multi2", "slow", "adjacent", 0.54, 16, 2, ValueVector(offense=30, tempo=5, control=10)),
    _w("astral_board", "targeting", "mark", "detonate", "all", 0.48, 34, 4, ValueVector(offense=48, control=4, volatility=10)),

    # 回响、反应与自动触发。
    _w("blade_array", "reaction", "multi3", "on_crit", "all", 0.30, 28, 3, ValueVector(offense=45, tempo=6, volatility=8)),
    _w("shadow_thread", "reaction", "swift", "evasion_counter", "single", 0.72, 18, 2, ValueVector(offense=28, survival=10, tempo=8)),
    _w("armament_talisman", "reaction", "self_cost", "extra_turn", "single", 1.40, 20, 4, ValueVector(offense=42, tempo=18, volatility=12)),
    _w("thunder_warrant", "reaction", "multi2", "on_crit_stun", "random", 0.58, 24, 3, ValueVector(offense=36, control=12, volatility=8)),
    _w("blood_pact", "reaction", "missing_rage", "thorns", "single", 0.92, 14, 2, ValueVector(offense=36, survival=8, volatility=10)),
    _w("phantom_banner", "reaction", "multi2", "evasion", "random", 0.56, 18, 2, ValueVector(offense=30, survival=12, tempo=6)),
    _w("myriad_vault", "reaction", "multi3", "mark_self", "all", 0.29, 25, 3, ValueVector(offense=42, tempo=8, volatility=5)),
    _w("sentinel_sigill", "reaction", "swift", "shield_counter", "single", 0.70, 24, 3, ValueVector(offense=28, survival=18, volatility=5)),

    # 高风险、形态切换与规则改写。
    _w("sevenfold_saber", "risk", "multi3", "self_cost", "single", 0.52, 10, 2, ValueVector(offense=50, volatility=14)),
    _w("sacrifice_blade", "risk", "heavy", "self_cost", "single", 2.05, 8, 4, ValueVector(offense=56, volatility=16)),
    _w("bloomblight_staff", "risk", "poison", "heal", "single", 0.60, 20, 2, ValueVector(offense=32, sustain=18, volatility=5)),
    _w("twinphase_edge", "risk", "element_cycle", "shield", "single", 0.90, 22, 3, ValueVector(offense=38, survival=12, volatility=8)),
    _w("fate_die", "risk", "volatile", "none", "random", 1.00, 12, 1, ValueVector(offense=42, volatility=20)),
    _w("death_scribe", "risk", "execute", "mark", "lowest", 0.94, 20, 2, ValueVector(offense=48, volatility=8)),
    _w("defiant_spear", "risk", "missing_rage", "death_guard", "single", 1.10, 18, 3, ValueVector(offense=40, survival=10, volatility=12)),
    _w("samsara_wheel", "risk", "true_strike", "on_kill_heal", "all", 0.62, 36, 5, ValueVector(offense=45, sustain=10, volatility=9)),

    # 借势反锋：读取敌方攻击形成有上限的回击，不复制连击、异常或斩杀机制。
    _w("borrowed_edge", "reaction", "borrowed_force", "guard", "single", 0.76, 20, 2, ValueVector(offense=42, survival=10, volatility=5)),

    # 延迟回响：先留下独立标记，再于目标下一次行动开始时结算一次回响。
    _w("deferred_echo", "reaction", "deferred_echo", "none", "single", 0.72, 24, 3, ValueVector(offense=47, tempo=5, volatility=3)),
)


def _validate_blueprints() -> None:
    if not WEAPON_BLUEPRINTS:
        raise ValueError("正式武器矩阵不能为空")
    keys = [value.key for value in WEAPON_BLUEPRINTS]
    mechanics = [(value.primary, value.support, value.targeting) for value in WEAPON_BLUEPRINTS]
    if len(keys) != len(set(keys)):
        raise ValueError("正式武器稳定键不能重复")
    if len(mechanics) != len(set(mechanics)):
        raise ValueError("正式武器不能复用完全相同的机制组合")
    if any(value.power <= 0 or value.spirit_cost < 0 or value.cooldown < 0 for value in WEAPON_BLUEPRINTS):
        raise ValueError("正式武器倍率、消耗或冷却边界无效")


_validate_blueprints()


__all__ = ["WEAPON_BLUEPRINTS", "WeaponBlueprint"]
