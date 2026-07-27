"""太玄界的敌人身份、行为术语与精英前缀。"""

from game.core.gameplay import (
    ENCOUNTER_SCOPE_PARTY_ID,
    ENCOUNTER_SCOPE_PERSONAL_ID,
    ENEMY_RANK_BOSS_ID,
    ENEMY_RANK_ELITE_ID,
    ENEMY_RANK_NORMAL_ID,
    SkinEntry,
)

from ...catalog.enemy.blueprints import (
    BEHAVIOR_BLUEPRINTS,
    BOSS_BLUEPRINTS,
    CULTIVATION_PARTY_BOSS_BLUEPRINTS,
    MAGIC_PARTY_BOSS_BLUEPRINTS,
    STELLAR_RING_PARTY_BOSS_BLUEPRINTS,
    PERSONAL_BOSS_BLUEPRINTS,
    REGULAR_ENEMY_BLUEPRINTS,
)
from ...catalog.enemy.encounters import (
    PARTY_BOSS_ENCOUNTER_ID,
    PERSONAL_BOSS_ENCOUNTER_ID,
    PERSONAL_ELITE_ENCOUNTER_ID,
    PERSONAL_NORMAL_ENCOUNTER_ID,
)
from ...catalog.enemy.behaviors import ENEMY_BEHAVIOR_CONTENT
from ..combat_mechanisms import build_enemy_behavior_mechanism_entries


_REGULAR_NAMES = (
    "山魈", "狼妖", "狐妖", "蛛妖", "蛇妖", "尸傀", "水鬼", "画皮", "夜叉", "罗刹",
    "梦貘", "石傀", "狰", "孟极", "当康", "蛊雕", "朱厌", "长右", "蜚", "毕方",
    "夔牛", "巴蛇", "猫鬼", "诸怀", "飞僵", "雾魅", "骨妖", "水魅", "火鼠", "冰蚕",
    "雷兽", "土蝼", "魑魅", "木魅", "血尸", "咒灵", "金甲尸", "啸月狼", "勾魂使", "铜甲傀",
    "鹏妖", "蜃妖", "镜妖", "锁魂鬼", "镇墓兽", "星官残魂", "无常", "雪魅", "疫鬼", "火鸦",
    "雷公虫", "魍魉", "月魅", "日游神", "混沌兽", "烛阴", "织命蛛", "判官残影", "界游仙", "守山灵",
)


_BOSS_NAMES = (
    ("化蛇·洪涛妖君", "化蛇"),
    ("鸣蛇·旱泽毒君", "鸣蛇"),
    ("祸斗·吞火凶犬", "祸斗"),
    ("猲狙·兵乱妖兽", "猲狙"),
    ("梼杌·不化顽主", "梼杌"),
    ("饕餮·吞天巨口", "饕餮"),
    ("混沌·无相魔胎", "混沌"),
    ("虺龙·暮海玄君", "虺龙"),
    ("防风氏·断首巨人", "防风氏"),
    ("赤鱬·疫水妖王", "赤鱬"),
    ("朱厌·兵灾之兆", "朱厌王"),
    ("鬼车·九首夜啼", "鬼车"),
    ("蛊雕·食人凶禽", "蛊雕王"),
    ("巴蛇·洞庭巨蟒", "巴蛇王"),
    ("夔牛·雷泽独足", "夔牛王"),
    ("天狗·蚀日凶星", "天狗王"),
    ("金乌·焚世残阳", "金乌"),
    ("夫诸·大水之兆", "夫诸"),
    ("猰貐·弱水恶兽", "猰貐"),
    ("獓因·荒原巨凶", "獓因"),
    ("酆都鬼帝·罗酆", "罗酆"),
    ("飞僵始祖·不化骨", "不化骨"),
    ("青丘狐母·九尾", "九尾"),
    ("梦貘之主·食梦", "食梦"),
    ("山君·陆吾", "陆吾"),
    ("沧海龙君·敖渊", "敖渊"),
    ("九霄雷尊·应玄", "应玄"),
    ("玄冥冰后·幽寒", "幽寒"),
    ("离火魔君·赤霄", "赤霄"),
    ("五瘟使·疫主", "疫主"),
    ("血河老祖·冥河", "冥河"),
    ("白骨龙君·苍骸", "苍骸"),
    ("堕仙·折翼天人", "堕仙"),
    ("奇门阵主·无归", "无归"),
    ("独目器尊·熔岳", "熔岳"),
    ("石化妖后·青鳞", "青鳞"),
    ("北冥巨妖·吞舟", "吞舟"),
    ("海眼孽龙·覆溟", "覆溟"),
    ("撼地神兽·岳沉", "岳沉"),
    ("啸月天狼·食日", "食日"),
    ("建木妖祖·青帝", "青帝"),
    ("阴兵大将·夜巡", "夜巡"),
    ("幽冥判官·崔府君", "崔府君"),
    ("归墟魔尊·无极", "无极"),
    ("岁烛龙君·长明", "长明"),
    ("织命玄女·司罗", "司罗"),
    ("昆仑镜灵·照世", "照世"),
    ("铜头铁主·蚩尤", "蚩尤"),
    ("吞月蟾祖·望舒", "望舒"),
    ("射日遗魂·大羿", "大羿"),
    ("巡天巨兽·星甲", "星甲"),
    ("万卷天官·司册", "司册"),
    ("断环巨神·百臂", "百臂"),
    ("大日玄镜·曜灵", "曜灵"),
    ("无声天将·寂灭", "寂灭"),
    ("天蛛妖母·罗网", "罗网"),
    ("岁轮机君·刻辰", "刻辰"),
    ("吞界巨口·归墟", "归墟巨口"),
    ("天条判官·执衡", "执衡"),
    ("第十三天枢·无名", "无名天枢"),
)


_BEHAVIOR_DISPLAY = {
    "heavy_strike": ("重击", "以低频强击压垮目标。", ("裂岳", "镇山", "破军", "崩天")),
    "rapid_attack": ("迅攻", "提高行动节奏连续施压。", ("追风", "掠影", "飞星", "疾电")),
    "combo": ("连击", "一次行动造成多段攻击。", ("乱刃", "千锋", "叠浪", "连环")),
    "follow_up": ("追击", "抓住破绽追加攻击。", ("逐命", "追魂", "衔尾", "赶月")),
    "execute": ("斩杀", "优先收割气血较低的目标。", ("断命", "绝生", "斩魂", "收魄")),
    "charged_burst": ("蓄势", "积累力量后集中爆发。", ("藏锋", "聚势", "凝元", "伏雷")),
    "piercing": ("破甲", "穿透防御制造稳定伤害。", ("破罡", "穿云", "裂甲", "透骨")),
    "true_damage": ("无相伤害", "以无相伤害绕开常规防御。", ("无相", "破妄", "直命", "洞虚")),
    "splash": ("溅射", "攻击同时波及邻近目标。", ("震岳", "荡波", "横扫", "裂阵")),
    "area_attack": ("群攻", "同时攻击多个敌人。", ("覆海", "横天", "席卷", "荡魔")),
    "poison": ("毒蚀", "施加能够持续生效的毒伤。", ("瘴毒", "腐骨", "蚀魂", "碧毒")),
    "burn": ("灼烧", "以真火伤害持续消耗目标。", ("劫火", "赤焰", "焚心", "流火")),
    "bleed": ("流血", "制造伤口并持续追压。", ("血刃", "裂脉", "断筋", "赤痕")),
    "mark_detonation": ("叠印", "积累印记后集中引爆。", ("咒印", "伏符", "叠煞", "爆箓")),
    "resource_drain": ("噬灵", "抽取目标灵力转为自身优势。", ("吞灵", "摄元", "噬法", "枯海")),
    "heavy_armor": ("玄甲", "以高气血和防御换取迟缓。", ("玄甲", "金刚", "镇岳", "磐石")),
    "shield": ("护体", "主动获得护盾吸收伤害。", ("金身", "灵罩", "护法", "罡壁")),
    "evasion": ("幻身", "依靠身法规避攻击。", ("流影", "幻身", "无踪", "踏虚")),
    "block": ("格挡", "通过格挡降低受到的伤害。", ("铁壁", "玄守", "拒岳", "横盾")),
    "counter": ("反锋", "主动挥击并以锋势压制目标。", ("返煞", "回锋", "逆震", "反戈")),
    "lifesteal": ("吸血", "将造成的伤害转为气血。", ("饮血", "血煞", "噬生", "摄命")),
    "regeneration": ("回生", "持续恢复自身气血。", ("回春", "长生", "复元", "青木")),
    "death_guard": ("不屈", "濒危时保留最后生机。", ("逆命", "不灭", "守魂", "续命")),
    "sunder": ("破防", "削弱目标的防御能力。", ("破阵", "碎甲", "裂罡", "摧山")),
    "stun": ("震魂", "尝试令目标短暂无法行动。", ("镇魂", "惊雷", "摄魄", "震神")),
    "freeze": ("冰封", "尝试对目标施加冰封。", ("玄冰", "霜狱", "冻魂", "寒劫")),
    "sleep": ("入梦", "尝试对目标施加昏睡。", ("梦魇", "眠云", "迷魂", "醉梦")),
    "slow": ("迟滞", "降低目标行动速度。", ("缚风", "沉岳", "迟光", "锁步")),
    "taunt": ("挑衅", "迫使敌人改变攻击目标。", ("镇阵", "守关", "拦江", "横岳")),
    "cooldown_lock": ("禁法", "延长目标能力的等待时间。", ("禁法", "封诀", "绝术", "断脉")),
    "volatile": ("赌命", "攻击在低谷与高峰间剧烈波动。", ("赌命", "狂骰", "无常", "天变")),
    "sacrifice": ("舍身", "消耗自身气血换取高额伤害。", ("燃命", "舍身", "献魂", "兵解")),
}


def _build_entries() -> tuple[dict[str, SkinEntry], dict[str, tuple[str, ...]], dict[str, str]]:
    regular_keys = tuple(value.key for value in REGULAR_ENEMY_BLUEPRINTS)
    boss_blueprints = BOSS_BLUEPRINTS
    behavior_keys = {value.key for value in BEHAVIOR_BLUEPRINTS}
    if len(_REGULAR_NAMES) != len(regular_keys) or len(_BOSS_NAMES) != len(boss_blueprints):
        raise ValueError("太玄界敌人名称必须完整覆盖正式敌人身份")
    boss_names = dict(zip((value.key for value in boss_blueprints), _BOSS_NAMES, strict=True))
    if set(_BEHAVIOR_DISPLAY) != behavior_keys:
        raise ValueError("太玄界行为名称必须完整覆盖正式行为模板")
    all_names = [
        *_REGULAR_NAMES,
        *(boss_names[value.key][0] for value in boss_blueprints),
    ]
    if len(all_names) != len(set(all_names)):
        raise ValueError("太玄界敌人完整名称不能重复")
    entries = {
        ENEMY_RANK_NORMAL_ID: SkinEntry(name="寻常敌人"),
        ENEMY_RANK_ELITE_ID: SkinEntry(name="精英敌人"),
        ENEMY_RANK_BOSS_ID: SkinEntry(name="首领敌人"),
        ENCOUNTER_SCOPE_PERSONAL_ID: SkinEntry(name="个人遭遇"),
        ENCOUNTER_SCOPE_PARTY_ID: SkinEntry(name="结伴讨伐"),
        PERSONAL_NORMAL_ENCOUNTER_ID: SkinEntry(name="寻常遭遇"),
        PERSONAL_ELITE_ENCOUNTER_ID: SkinEntry(name="精英遭遇"),
        PERSONAL_BOSS_ENCOUNTER_ID: SkinEntry(name="首领挑战"),
        PARTY_BOSS_ENCOUNTER_ID: SkinEntry(name="结伴诛魔"),
    }
    for key, name in zip(regular_keys, _REGULAR_NAMES):
        entries[f"enemy.{key}"] = SkinEntry(name=name, compact_name=name, icon="♟")
    for blueprint in PERSONAL_BOSS_BLUEPRINTS:
        name, compact_name = boss_names[blueprint.key]
        entries[f"enemy.boss.{blueprint.key}"] = SkinEntry(name=name, compact_name=compact_name, icon="♛")
    for source, blueprints in (
        ("cultivation", CULTIVATION_PARTY_BOSS_BLUEPRINTS),
        ("magic", MAGIC_PARTY_BOSS_BLUEPRINTS),
        ("stellar_ring", STELLAR_RING_PARTY_BOSS_BLUEPRINTS),
    ):
        for blueprint in blueprints:
            name, compact_name = boss_names[blueprint.key]
            entries[f"enemy.boss.party.{source}.{blueprint.key}"] = SkinEntry(name=name, compact_name=compact_name, icon="♛")
    prefixes = {}
    behavior_names = {}
    for key, (name, description, values) in _BEHAVIOR_DISPLAY.items():
        behavior_id = f"enemy.behavior.{key}"
        entries[behavior_id] = SkinEntry(name=f"妖性·{name}", description=description, icon="✦")
        entries[f"ability.enemy.{key}"] = SkinEntry(name=f"敌术·{name}", description=description, icon="✦")
        prefixes[behavior_id] = values
        behavior_names[behavior_id] = name
    entries.update(
        build_enemy_behavior_mechanism_entries(
            ENEMY_BEHAVIOR_CONTENT.display_owners,
            entries,
        )
    )
    return entries, prefixes, behavior_names


CULTIVATION_ENEMY_ENTRIES, CULTIVATION_ENEMY_PREFIXES, CULTIVATION_ENEMY_BEHAVIOR_NAMES = _build_entries()


__all__ = [
    "CULTIVATION_ENEMY_BEHAVIOR_NAMES",
    "CULTIVATION_ENEMY_ENTRIES",
    "CULTIVATION_ENEMY_PREFIXES",
]
