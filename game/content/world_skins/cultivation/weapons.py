"""太玄界的正式武器展示；规则蓝图不保存玩家可见文本。"""

from game.core.gameplay import SkinEntry

from ...catalog import STARTER_WEAPON_ID, STARTER_WEAPON_ITEM_ID
from ...catalog.weapon.blueprints import WEAPON_BLUEPRINTS
from ...catalog.weapon.mechanics import WEAPON_MECHANIC_CONTENT


_WEAPON_DISPLAY = {
    "mountain_cleaver": ("盘古斧", "重击后削弱防御"),
    "dawn_bane": ("斩仙飞刀", "目标越残血伤害越高"),
    "star_piercer": ("火尖枪", "穿盾攻击并提高暴击"),
    "war_breaker": ("方天画戟", "撼动高血量目标并延后行动"),
    "ember_brand": ("三昧火扇", "重击点燃并波及邻位"),
    "storm_maul": ("雷公凿", "双段雷击并尝试眩晕"),
    "blood_reaper": ("化血神刀", "自身越残血越凶并吸取气血"),
    "judgement_bow": ("震天弓", "无相伤害击败后获得节奏收益"),
    "flash_blade": ("七星龙渊", "三段攻击后提升速度"),
    "gearshade": ("混元伞", "攻守两段并获得短暂防御"),
    "moonstep_twins": ("雌雄双股剑", "双击后请求一次受限额外行动"),
    "gale_ring": ("乾坤圈", "低消耗攻击并延迟随机目标"),
    "blink_fang": ("鱼肠剑", "必中式突刺后提高闪避"),
    "continuum_rod": ("如意金箍棒", "重击后以击败刷新冷却"),
    "soul_chaser": ("捆仙绳", "追击残血并削减速度"),
    "comet_shuttle": ("攒心钉", "多段攻击以暴击触发回响"),
    "plague_banner": ("六魂幡", "群体施毒并叠加毒印"),
    "cinder_lash": ("混天绫", "灼烧邻位并降低速度"),
    "hemorrhage_nail": ("七箭钉魂书", "流血会在残血目标上加速收割"),
    "wither_fan": ("蛊神瘴扇", "毒蚀同时削弱防御"),
    "heart_pyrelamp": ("灵柩灯", "燃烧气血并抽取灵力"),
    "frost_marrow_needle": ("太阴玄针", "玄霜伤害累积并尝试冰封"),
    "blight_staff": ("瘟癀伞", "群毒削弱目标攻击"),
    "ashen_crucible": ("神农鼎", "叠印后引爆并重新点燃"),
    "hidden_edge_coffer": ("诛仙剑匣", "先藏锋叠印再一次释放"),
    "mana_devourer": ("紫金葫芦", "抽取灵力并转为恢复"),
    "blade_well": ("洗剑池", "攻击积累剑势强化后续爆发"),
    "aether_orb": ("定海珠", "消耗灵力爆发并获得护盾"),
    "fate_ledger": ("生死簿", "以血换伤并短暂保命"),
    "soulburn_bell": ("落魂钟", "高灵力消耗换取行动爆发"),
    "equilibrium_chalice": ("玉净瓶", "根据气血与灵力缺口自适应恢复"),
    "formless_wheel": ("金刚琢", "无相伤害并清除目标增益"),
    "mountain_seal": ("番天印", "重击后获得厚重护盾"),
    "verdant_staff": ("神农鞭", "稳定攻击并持续自愈"),
    "mirror_blade": ("莫邪剑", "攻击后以反击回应受伤"),
    "aegis_parasol": ("七宝伞", "双段攻击后提高格挡"),
    "lifebond_chain": ("同心锁", "高额伤害按实际伤害恢复"),
    "phoenix_plume": ("凤凰翎", "自损追猎并以击败恢复"),
    "tortoise_bulwark": ("玄武甲", "低伤攻击换取单次伤害封顶"),
    "void_mirror": ("阴阳镜", "无相伤害后获得短暂免疫"),
    "soul_bell": ("摄魂铃", "快速攻击并稳定尝试眩晕"),
    "binding_codex": ("封神榜", "施加束缚印并强制目标回应"),
    "dream_flute": ("韩湘子玉笛", "群体低伤并尝试施加昏睡"),
    "winter_rod": ("玄冥杖", "玄霜伤害波及邻位并延长控制节奏"),
    "dragon_bind": ("缚龙索", "重击后将目标锁定于自身"),
    "gravity_tablet": ("石敢当碑", "压制群体高血目标行动进度"),
    "discord_harp": ("伏羲琴", "乱击并削弱随机目标攻击"),
    "null_blade": ("绝仙剑", "无相伤害并延长目标冷却"),
    "realm_fan": ("山河社稷图", "群体攻击并统一削防"),
    "ninefold_bow": ("射日神弓", "三箭随机散射并积累暴击"),
    "cloud_piercer": ("三尖两刃刀", "穿盾贯击并延迟邻位"),
    "tide_breaker": ("定海神针", "群体震击并低概率眩晕"),
    "rift_blade": ("诛仙剑", "无相伤害溅射并留下裂隙印记"),
    "prism_array": ("河图洛书", "一次攻击同时结算真火、玄霜、无相三类伤害"),
    "dragon_coil": ("打神鞭", "邻位双击并降低速度"),
    "astral_board": ("周天星斗图", "全场布印并按层数引爆"),
    "blade_array": ("诛仙阵图", "群体剑阵以暴击追加回响"),
    "shadow_thread": ("傀儡牵机线", "提高闪避并在闪避后反击"),
    "armament_talisman": ("兵解符", "自损换取高伤与额外行动"),
    "thunder_warrant": ("五雷天师令", "暴击时追加雷击和眩晕"),
    "blood_pact": ("血誓盟书", "残血增伤并反击来袭者"),
    "phantom_banner": ("青莲宝色旗", "双重幻击后进入闪避窗口"),
    "myriad_vault": ("万剑归宗匣", "群体多段攻击积累自身剑势"),
    "sentinel_sigill": ("玲珑宝塔", "获得护盾并在破盾时反击"),
    "sevenfold_saber": ("七杀刀", "三段杀招同时消耗自身气血"),
    "sacrifice_blade": ("干将剑", "以固定气血代价换取极高倍率"),
    "bloomblight_staff": ("枯荣禅杖", "施毒与自愈形成枯荣循环"),
    "twinphase_edge": ("太极剑", "三相混合伤害并获得护盾"),
    "fate_die": ("六博骰", "每次攻击在低谷与高峰间波动"),
    "death_scribe": ("判官笔", "标记残血并逐次提高斩杀压力"),
    "defiant_spear": ("逆鳞枪", "濒危时爆发并保留最后气血"),
    "samsara_wheel": ("六道轮", "无相群伤并以击败延续生命"),
    "borrowed_edge": ("移星换斗镜", "借敌方攻势反锋，并凝成短暂护体罡气"),
    "deferred_echo": ("空桑回音璧", "一击留声，于目标下一次行动前引发回响"),
}

_AFFIX_DISPLAY = {
    "property.weapon_affix.attack": ("攻伐", "提高武器基础攻击。"),
    "property.weapon_affix.defense": ("护体", "提高自身防御。"),
    "property.weapon_affix.speed": ("身法", "提高行动速度。"),
    "property.weapon_affix.accuracy": ("洞察", "提高攻击命中。"),
    "property.weapon_affix.outgoing": ("威势", "提高造成的伤害。"),
    "property.weapon_affix.tenacity": ("定神", "缩短受到的控制。"),
    "property.weapon_affix.burst_critical": ("破军会心", "提高爆发武器的会心伤害。"),
    "property.weapon_affix.burst_penetration": ("破罡", "提高爆发武器的固定穿透。"),
    "property.weapon_affix.tempo_critical": ("迅刃会心", "提高节奏武器的会心概率。"),
    "property.weapon_affix.tempo_evasion": ("流影", "提高节奏武器的闪避。"),
    "property.weapon_affix.ailment_rate": ("毒焰增幅", "提高持续伤害武器的伤害。"),
    "property.weapon_affix.ailment_control": ("蚀魂", "提高持续伤害武器的控制命中。"),
    "property.weapon_affix.resource_healing": ("回元", "提高资源武器的治疗效果。"),
    "property.weapon_affix.resource_attack": ("聚元攻伐", "提高资源武器的基础攻击。"),
    "property.weapon_affix.guard_block": ("玄守", "提高守御武器的格挡概率。"),
    "property.weapon_affix.guard_reduction": ("金刚", "提高守御武器的格挡减伤。"),
    "property.weapon_affix.control_chance": ("摄魂", "提高控制武器的控制命中。"),
    "property.weapon_affix.control_speed": ("御风", "提高控制武器的行动速度。"),
    "property.weapon_affix.targeting_penetration": ("穿云", "提高群攻武器的比例穿透。"),
    "property.weapon_affix.targeting_accuracy": ("天眼", "提高群攻武器的攻击命中。"),
    "property.weapon_affix.reaction_evasion": ("幻身", "提高反应武器的闪避。"),
    "property.weapon_affix.reaction_critical": ("应机", "提高反应武器的会心概率。"),
    "property.weapon_affix.risk_damage": ("逆命", "提高风险武器造成的伤害。"),
    "property.weapon_affix.risk_critical": ("血劫", "提高风险武器的会心伤害。"),
}


def _build_weapon_entries() -> dict[str, SkinEntry]:
    blueprint_keys = {value.key for value in WEAPON_BLUEPRINTS}
    if set(_WEAPON_DISPLAY) != blueprint_keys:
        raise ValueError("太玄界武器展示键必须完整覆盖正式武器蓝图")
    names = [value[0] for value in _WEAPON_DISPLAY.values()]
    if len(names) != len(set(names)):
        raise ValueError("太玄界正式武器名称不能重复")
    affix_ids = {
        value.id
        for value in WEAPON_MECHANIC_CONTENT.properties
        if value.id.startswith("property.weapon_affix.")
    }
    if set(_AFFIX_DISPLAY) != affix_ids:
        raise ValueError("太玄界武器随机词条必须完整覆盖规则定义")
    entries = {
        STARTER_WEAPON_ITEM_ID: SkinEntry(name="仙京制式剑器", icon="⚔"),
        STARTER_WEAPON_ID: SkinEntry(
            name="仙京制式剑",
            description="仙京赐予初入道途者的制式灵剑。",
            icon="⚔",
        ),
    }
    for blueprint in WEAPON_BLUEPRINTS:
        name, description = _WEAPON_DISPLAY[blueprint.key]
        entries.update(
            {
                f"item.weapon.{blueprint.key}": SkinEntry(name=f"{name}器胚", icon="⚔"),
                f"weapon.{blueprint.key}": SkinEntry(name=name, description=description, icon="⚔"),
                f"ability.weapon.{blueprint.key}": SkinEntry(name=f"{name}器诀", description=description, icon="⚔"),
                f"property.weapon_core.{blueprint.key}": SkinEntry(
                    name=f"{name}器魂",
                    description=f"承载{name}核心战斗机制的本命器魂。",
                    icon="✦",
                ),
            }
        )
    for property_id, (name, description) in _AFFIX_DISPLAY.items():
        entries[property_id] = SkinEntry(
            name=f"器纹·{name}",
            description=description,
            icon="✦",
        )
    return entries


CULTIVATION_WEAPON_ENTRIES = _build_weapon_entries()


__all__ = ["CULTIVATION_WEAPON_ENTRIES"]
