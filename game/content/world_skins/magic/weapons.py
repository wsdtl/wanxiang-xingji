"""魔法世界的正式武器展示；规则蓝图不保存玩家可见文本。"""

from game.core.gameplay import SkinEntry

from ...catalog import STARTER_WEAPON_ID, STARTER_WEAPON_ITEM_ID
from ...catalog.weapon.blueprints import WEAPON_BLUEPRINTS
from ...catalog.weapon.mechanics import WEAPON_MECHANIC_CONTENT


_WEAPON_DISPLAY = {
    "mountain_cleaver": ("米诺斯双刃斧", "重击后削弱防御"),
    "dawn_bane": ("杜兰达尔", "目标越残血伤害越高"),
    "star_piercer": ("朗基努斯之枪", "穿盾攻击并提高暴击"),
    "war_breaker": ("盖伯尔加", "撼动高血量目标并延后行动"),
    "ember_brand": ("莱瓦汀", "重击点燃并波及邻位"),
    "storm_maul": ("妙尔尼尔", "双段雷击并尝试眩晕"),
    "blood_reaper": ("克洛诺斯之镰", "自身越残血越凶并吸取生命"),
    "judgement_bow": ("阿波罗神弓", "纯粹伤害击败后获得节奏收益"),
    "flash_blade": ("赫尔墨斯短剑", "三段攻击后提升速度"),
    "gearshade": ("达芬奇机巧伞", "攻守两段并获得短暂防御"),
    "moonstep_twins": ("双子星刃", "双击后请求一次受限额外行动"),
    "gale_ring": ("德罗普尼尔", "低消耗攻击并延迟随机目标"),
    "blink_fang": ("哈耳佩", "必中式突刺后提高闪避"),
    "continuum_rod": ("克洛诺斯权杖", "重击后以击败刷新冷却"),
    "soul_chaser": ("冥河锁链", "追击残血并削减速度"),
    "comet_shuttle": ("阿斯特赖俄斯飞刃", "多段攻击以暴击触发回响"),
    "plague_banner": ("潘多拉灾旗", "群体施毒并叠加疫病印记"),
    "cinder_lash": ("赫菲斯托斯火鞭", "灼烧邻位并降低速度"),
    "hemorrhage_nail": ("德古拉血钉", "流血会在残血目标上加速收割"),
    "wither_fan": ("喀耳刻毒扇", "毒蚀同时削弱防御"),
    "heart_pyrelamp": ("普罗米修斯火种", "燃烧生命并抽取魔力"),
    "frost_marrow_needle": ("斯卡蒂冰针", "寒霜伤害累积并尝试冻结"),
    "blight_staff": ("赫卡忒毒杖", "群毒削弱目标攻击"),
    "ashen_crucible": ("赫菲斯托斯熔炉", "叠印后引爆并重新点燃"),
    "hidden_edge_coffer": ("潘多拉魔盒", "先藏锋叠印再一次释放"),
    "mana_devourer": ("达格达魔釜", "抽取魔力并转为恢复"),
    "blade_well": ("乌尔德之泉", "攻击积累刃势强化后续爆发"),
    "aether_orb": ("阿特拉斯天球", "消耗魔力爆发并获得护盾"),
    "fate_ledger": ("诺恩命运书", "以血换伤并短暂保命"),
    "soulburn_bell": ("加拉尔号角", "高魔力消耗换取行动爆发"),
    "equilibrium_chalice": ("圣杯", "根据生命与魔力缺口自适应恢复"),
    "formless_wheel": ("伊克西翁火轮", "纯粹伤害并清除目标增益"),
    "mountain_seal": ("所罗门王印", "重击后获得厚重护盾"),
    "verdant_staff": ("阿斯克勒庇俄斯蛇杖", "稳定攻击并持续自愈"),
    "mirror_blade": ("纳西索斯水镜", "攻击后以反击回应受伤"),
    "aegis_parasol": ("雅典娜神盾", "双段攻击后提高格挡"),
    "lifebond_chain": ("安德洛墨达锁链", "高额伤害按实际伤害恢复"),
    "phoenix_plume": ("凤凰羽", "自损追猎并以击败恢复"),
    "tortoise_bulwark": ("阿喀琉斯神盾", "低伤攻击换取单次伤害封顶"),
    "void_mirror": ("珀耳修斯铜镜", "纯粹伤害后获得短暂免疫"),
    "soul_bell": ("卡戎渡魂铃", "快速攻击并稳定尝试眩晕"),
    "binding_codex": ("所罗门之钥", "施加束缚印并强制目标回应"),
    "dream_flute": ("潘神牧笛", "群体低伤并尝试施加睡眠"),
    "winter_rod": ("斯卡蒂权杖", "寒霜伤害波及邻位并延长控制节奏"),
    "dragon_bind": ("格莱普尼尔", "重击后将目标锁定于自身"),
    "gravity_tablet": ("阿特拉斯石碑", "压制群体高血目标行动进度"),
    "discord_harp": ("厄里斯竖琴", "乱击并削弱随机目标攻击"),
    "null_blade": ("提尔锋", "纯粹伤害并延长目标冷却"),
    "realm_fan": ("埃俄罗斯风袋", "群体攻击并统一削防"),
    "ninefold_bow": ("阿尔忒弥斯银弓", "三箭随机散射并积累暴击"),
    "cloud_piercer": ("冈格尼尔", "穿盾贯击并延迟邻位"),
    "tide_breaker": ("波塞冬三叉戟", "群体震击并低概率眩晕"),
    "rift_blade": ("卡拉德波加", "纯粹伤害溅射并留下裂隙印记"),
    "prism_array": ("伊里斯虹盘", "一次攻击同时结算火焰、寒霜、纯粹三类伤害"),
    "dragon_coil": ("拉奥孔蛇鞭", "邻位双击并降低速度"),
    "astral_board": ("黄道星盘", "全场布印并按层数引爆"),
    "blade_array": ("达摩克利斯剑阵", "群体剑阵以暴击追加回响"),
    "shadow_thread": ("阿里阿德涅线", "提高闪避并在闪避后反击"),
    "armament_talisman": ("瓦尔基里战符", "自损换取高伤与额外行动"),
    "thunder_warrant": ("宙斯雷霆", "暴击时追加雷击和眩晕"),
    "blood_pact": ("浮士德契约", "残血增伤并反击来袭者"),
    "phantom_banner": ("哈迪斯隐身盔", "双重幻击后进入闪避窗口"),
    "myriad_vault": ("尼伯龙根宝藏", "群体多段攻击积累自身刃势"),
    "sentinel_sigill": ("米迦勒守护徽记", "获得护盾并在破盾时反击"),
    "sevenfold_saber": ("七宗罪军刀", "三段杀招同时消耗自身生命"),
    "sacrifice_blade": ("戴因斯莱夫", "以固定生命代价换取极高倍率"),
    "bloomblight_staff": ("珀耳塞福涅双生杖", "施毒与自愈形成枯荣循环"),
    "twinphase_edge": ("双子座魔刃", "三相混合伤害并获得护盾"),
    "fate_die": ("诺恩命运骰", "每次攻击在低谷与高峰间波动"),
    "death_scribe": ("阿努比斯判魂笔", "标记残血并逐次提高斩杀压力"),
    "defiant_spear": ("阿斯卡隆圣枪", "濒危时爆发并保留最后生命"),
    "samsara_wheel": ("伊西斯复生轮", "纯粹群伤并以击败延续生命"),
    "borrowed_edge": ("雅努斯双面镜", "映照敌我威能完成反击，并形成短暂护甲"),
    "deferred_echo": ("俄耳甫斯回响琴", "将伤害谱成第二乐句，于目标行动前奏响"),
}

_AFFIX_DISPLAY = {
    "property.weapon_affix.attack": ("威能", "提高武器基础攻击。"),
    "property.weapon_affix.defense": ("护甲", "提高自身防御。"),
    "property.weapon_affix.speed": ("迅捷", "提高行动速度。"),
    "property.weapon_affix.accuracy": ("精准", "提高攻击命中。"),
    "property.weapon_affix.outgoing": ("强攻", "提高造成的伤害。"),
    "property.weapon_affix.tenacity": ("坚韧", "缩短受到的控制。"),
    "property.weapon_affix.burst_critical": ("毁灭暴击", "提高爆发武器的暴击伤害。"),
    "property.weapon_affix.burst_penetration": ("重甲击穿", "提高爆发武器的固定穿透。"),
    "property.weapon_affix.tempo_critical": ("迅击暴击", "提高节奏武器的暴击概率。"),
    "property.weapon_affix.tempo_evasion": ("幻步", "提高节奏武器的闪避。"),
    "property.weapon_affix.ailment_rate": ("诅咒增幅", "提高异常武器的持续伤害。"),
    "property.weapon_affix.ailment_control": ("异常支配", "提高异常武器的控制命中。"),
    "property.weapon_affix.resource_healing": ("奥能复苏", "提高资源武器的治疗效果。"),
    "property.weapon_affix.resource_attack": ("奥能威能", "提高资源武器的基础攻击。"),
    "property.weapon_affix.guard_block": ("盾卫", "提高守御武器的格挡概率。"),
    "property.weapon_affix.guard_reduction": ("堡垒", "提高守御武器的格挡减伤。"),
    "property.weapon_affix.control_chance": ("法术支配", "提高控制武器的控制命中。"),
    "property.weapon_affix.control_speed": ("时序加速", "提高控制武器的行动速度。"),
    "property.weapon_affix.targeting_penetration": ("法术穿透", "提高群攻武器的比例穿透。"),
    "property.weapon_affix.targeting_accuracy": ("鹰眼", "提高群攻武器的攻击命中。"),
    "property.weapon_affix.reaction_evasion": ("暗影闪避", "提高反应武器的闪避。"),
    "property.weapon_affix.reaction_critical": ("反应暴击", "提高反应武器的暴击概率。"),
    "property.weapon_affix.risk_damage": ("狂怒增幅", "提高风险武器造成的伤害。"),
    "property.weapon_affix.risk_critical": ("献祭暴击", "提高风险武器的暴击伤害。"),
}


def _build_weapon_entries() -> dict[str, SkinEntry]:
    blueprint_keys = {value.key for value in WEAPON_BLUEPRINTS}
    if set(_WEAPON_DISPLAY) != blueprint_keys:
        raise ValueError("魔法世界武器展示键必须完整覆盖正式武器蓝图")
    names = [value[0] for value in _WEAPON_DISPLAY.values()]
    if len(names) != len(set(names)):
        raise ValueError("魔法世界正式武器名称不能重复")
    affix_ids = {
        value.id
        for value in WEAPON_MECHANIC_CONTENT.properties
        if value.id.startswith("property.weapon_affix.")
    }
    if set(_AFFIX_DISPLAY) != affix_ids:
        raise ValueError("魔法世界武器随机词条必须完整覆盖规则定义")
    entries = {
        STARTER_WEAPON_ITEM_ID: SkinEntry(name="王都守备剑原型", icon="⚔"),
        STARTER_WEAPON_ID: SkinEntry(
            name="王都守备剑",
            description="王都兵工坊配发给新晋冒险者的制式长剑。",
            icon="⚔",
        ),
    }
    for blueprint in WEAPON_BLUEPRINTS:
        name, description = _WEAPON_DISPLAY[blueprint.key]
        entries.update(
            {
                f"item.weapon.{blueprint.key}": SkinEntry(name=f"{name}原型", icon="⚔"),
                f"weapon.{blueprint.key}": SkinEntry(name=name, description=description, icon="⚔"),
                f"ability.weapon.{blueprint.key}": SkinEntry(name=f"{name}战技", description=description, icon="⚔"),
                f"property.weapon_core.{blueprint.key}": SkinEntry(
                    name=f"{name}核心",
                    description=f"承载{name}核心战斗机制的魔法核心。",
                    icon="✦",
                ),
            }
        )
    for property_id, (name, description) in _AFFIX_DISPLAY.items():
        entries[property_id] = SkinEntry(
            name=f"武装符文·{name}",
            description=description,
            icon="✦",
        )
    return entries


MAGIC_WEAPON_ENTRIES = _build_weapon_entries()


__all__ = ["MAGIC_WEAPON_ENTRIES"]
