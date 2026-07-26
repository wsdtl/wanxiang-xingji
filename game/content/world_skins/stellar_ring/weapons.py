"""星环界的正式武器展示；规则蓝图不保存玩家可见文本。"""

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
    "judgement_bow": ("阿波罗神弓", "真实伤害击败后获得节奏收益"),
    "flash_blade": ("赫尔墨斯短剑", "三段攻击后提升速度"),
    "gearshade": ("达芬奇折叠盾伞", "攻守两段并获得短暂防御"),
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
    "heart_pyrelamp": ("普罗米修斯火种", "燃烧生命并抽取同步值"),
    "frost_marrow_needle": ("斯卡蒂冰针", "冰霜伤害累积并尝试冻结"),
    "blight_staff": ("赫卡忒毒杖", "群毒削弱目标攻击"),
    "ashen_crucible": ("赫菲斯托斯熔炉", "叠印后引爆并重新点燃"),
    "hidden_edge_coffer": ("潘多拉魔盒", "先藏锋叠印再一次释放"),
    "mana_devourer": ("达格达魔釜", "抽取同步值并转为恢复"),
    "blade_well": ("乌尔德之泉", "攻击积累刃势强化后续爆发"),
    "aether_orb": ("阿特拉斯天球", "消耗同步值爆发并获得护盾"),
    "fate_ledger": ("诺恩命运书", "以血换伤并短暂保命"),
    "soulburn_bell": ("加拉尔号角", "高同步消耗换取行动爆发"),
    "equilibrium_chalice": ("圣杯", "根据生命与同步缺口自适应恢复"),
    "formless_wheel": ("伊克西翁火轮", "真实伤害并清除目标增益"),
    "mountain_seal": ("所罗门王印", "重击后获得厚重护盾"),
    "verdant_staff": ("阿斯克勒庇俄斯蛇杖", "稳定攻击并持续自愈"),
    "mirror_blade": ("纳西索斯水镜", "攻击后以反击回应受伤"),
    "aegis_parasol": ("雅典娜神盾", "双段攻击后提高格挡"),
    "lifebond_chain": ("安德洛墨达锁链", "高额伤害按实际伤害恢复"),
    "phoenix_plume": ("凤凰羽", "自损追猎并以击败恢复"),
    "tortoise_bulwark": ("阿喀琉斯神盾", "低伤攻击换取单次伤害封顶"),
    "void_mirror": ("珀耳修斯铜镜", "真实伤害后获得短暂免疫"),
    "soul_bell": ("卡戎渡魂铃", "快速攻击并稳定尝试眩晕"),
    "binding_codex": ("所罗门之钥", "施加束缚印并强制目标回应"),
    "dream_flute": ("潘神牧笛", "群体低伤并尝试催眠"),
    "winter_rod": ("斯卡蒂权杖", "冰霜伤害邻位并延长控制节奏"),
    "dragon_bind": ("格莱普尼尔", "重击后将目标锁定于自身"),
    "gravity_tablet": ("阿特拉斯石碑", "压制群体高血目标行动进度"),
    "discord_harp": ("厄里斯竖琴", "乱击并削弱随机目标攻击"),
    "null_blade": ("提尔锋", "真实伤害并延长目标冷却"),
    "realm_fan": ("埃俄罗斯风袋", "群体攻击并统一削防"),
    "ninefold_bow": ("阿尔忒弥斯银弓", "三箭随机散射并积累暴击"),
    "cloud_piercer": ("冈格尼尔", "穿盾贯击并延迟邻位"),
    "tide_breaker": ("波塞冬三叉戟", "群体震击并低概率眩晕"),
    "rift_blade": ("卡拉德波加", "真实溅射并留下裂隙印记"),
    "prism_array": ("伊里斯虹盘", "一次攻击同时结算火、霜、真实三相伤害"),
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
    "samsara_wheel": ("伊西斯复生轮", "真实群伤并以击败延续生命"),
    "borrowed_edge": ("维纳反馈刃", "采样敌方输出形成反馈斩击，并启动防护协议"),
    "deferred_echo": ("惠更斯延迟棱镜", "写入延迟脉冲，在目标行动时释放二次冲击"),
}

_WEAPON_NAMES = (
    "阿基米德重力斧", "晨星裁决刃", "赫利俄斯贯星枪", "帕斯卡破城锤", "法拉第赤炉剑", "特斯拉脉冲锤",
    "克洛诺斯收割镰", "阿波罗日冕弓", "洛伦兹闪频刃", "达芬奇折叠盾伞", "双子座相位刃", "开普勒风轨环",
    "赫尔墨斯瞬移枪", "安提凯希拉时序杖", "阿里阿德涅追索链", "哈雷彗星梭", "潘多拉疫源旗", "普罗米修斯熵火鞭",
    "德古拉血流钉", "喀耳刻凋零扇", "赫菲斯托斯心炉灯", "斯卡蒂零温针", "赫卡忒腐化杖", "灰烬反应炉",
    "潘多拉藏锋匣", "麦克斯韦吞噬器", "达摩克利斯刃井", "阿特拉斯轨道球", "拉普拉斯演算簿", "加拉尔警报钟",
    "帕拉塞尔苏斯均衡杯", "伊克西翁清除轮", "所罗门重力印", "阿斯克勒庇俄斯再生杖", "纳西索斯镜像刃", "埃癸斯偏转伞",
    "安德洛墨达生命链", "菲尼克斯熵火羽", "阿喀琉斯阈值盾", "珀耳修斯真空镜", "卡戎震荡钟", "所罗门锁定典",
    "潘神睡眠笛", "斯卡蒂冻结杖", "格莱普尼尔拘束索", "阿特拉斯压制碑", "厄里斯干扰琴", "提尔封锁刃",
    "埃俄罗斯扩散扇", "阿尔忒弥斯散射弓", "冈格尼尔云轨枪", "波塞冬潮汐戟", "卡拉德波加裂界刃", "伊里斯棱镜阵",
    "拉奥孔螺旋鞭", "黄道标记盘", "达摩克利斯群刃阵", "阿里阿德涅反应丝", "瓦尔基里过载符", "宙斯雷霆令",
    "浮士德血契刃", "哈迪斯偏移旗", "尼伯龙根武库匣", "米迦勒屏障徽", "七宗罪自损刃", "戴因斯莱夫献祭剑",
    "珀耳塞福涅共生杖", "双子座护盾刃", "诺恩波动骰", "阿努比斯归档笔", "阿斯卡隆保命枪", "伊西斯续航轮",
    "维纳反馈刃", "惠更斯延迟棱镜",
)

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
    "property.weapon_affix.control_chance": ("协议支配", "提高控制武器的控制命中。"),
    "property.weapon_affix.control_speed": ("时序加速", "提高控制武器的行动速度。"),
    "property.weapon_affix.targeting_penetration": ("阵列穿透", "提高群攻武器的比例穿透。"),
    "property.weapon_affix.targeting_accuracy": ("鹰眼", "提高群攻武器的攻击命中。"),
    "property.weapon_affix.reaction_evasion": ("暗影闪避", "提高反应武器的闪避。"),
    "property.weapon_affix.reaction_critical": ("反应暴击", "提高反应武器的暴击概率。"),
    "property.weapon_affix.risk_damage": ("狂怒增幅", "提高风险武器造成的伤害。"),
    "property.weapon_affix.risk_critical": ("献祭暴击", "提高风险武器的暴击伤害。"),
}


def _build_weapon_entries() -> dict[str, SkinEntry]:
    blueprint_keys = {value.key for value in WEAPON_BLUEPRINTS}
    if set(_WEAPON_DISPLAY) != blueprint_keys:
        raise ValueError("星环界武器展示键必须完整覆盖正式武器蓝图")
    names = list(_WEAPON_NAMES)
    if len(names) != len(set(names)):
        raise ValueError("星环界正式武器名称不能重复")
    if len(_WEAPON_NAMES) != len(WEAPON_BLUEPRINTS):
        raise ValueError("星环界武器名称必须完整覆盖正式武器蓝图")
    stellar_names = dict(zip((value.key for value in WEAPON_BLUEPRINTS), _WEAPON_NAMES))
    affix_ids = {
        value.id
        for value in WEAPON_MECHANIC_CONTENT.properties
        if value.id.startswith("property.weapon_affix.")
    }
    if set(_AFFIX_DISPLAY) != affix_ids:
        raise ValueError("星环界武器随机词条必须完整覆盖规则定义")
    entries = {
        STARTER_WEAPON_ITEM_ID: SkinEntry(name="环卫制式剑原型", icon="⚔"),
        STARTER_WEAPON_ID: SkinEntry(
            name="环卫制式剑",
            description="环心天城配发给新晋行者的制式长剑。",
            icon="⚔",
        ),
    }
    for blueprint in WEAPON_BLUEPRINTS:
        _, description = _WEAPON_DISPLAY[blueprint.key]
        name = stellar_names[blueprint.key]
        entries.update(
            {
                f"item.weapon.{blueprint.key}": SkinEntry(name=f"{name}原型", icon="⚔"),
                f"weapon.{blueprint.key}": SkinEntry(name=name, description=description, icon="⚔"),
                f"ability.weapon.{blueprint.key}": SkinEntry(name=f"{name}战技", description=description, icon="⚔"),
                f"property.weapon_core.{blueprint.key}": SkinEntry(
                    name=f"{name}核心",
                    description=f"承载{name}核心战斗机制的兵装核心。",
                    icon="✦",
                ),
            }
        )
    for property_id, (name, description) in _AFFIX_DISPLAY.items():
        entries[property_id] = SkinEntry(
            name=f"兵装协议·{name}",
            description=description,
            icon="✦",
        )
    return entries


STELLAR_RING_WEAPON_ENTRIES = _build_weapon_entries()


__all__ = ["STELLAR_RING_WEAPON_ENTRIES"]
