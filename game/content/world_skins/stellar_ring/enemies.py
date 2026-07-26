"""星环界的敌人身份、行为术语与精英前缀。"""

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
    "采掘重猿", "边轨猎犬", "拟态灵狐", "毒针织机", "管廊蛇人", "空壳卫兵", "冷却水妖", "仿生拟态体", "重装石卫", "血液采集者",
    "睡眠侵入体", "维修魔像", "晶翼狮鹫", "零温霜狼", "合金鬃兽", "高空女妖", "超载战猿", "吸附水蛭", "腐化疫兽", "废热火鸟",
    "脉冲雷兽", "管线巨蟒", "折光影豹", "撞角工兵", "黑甲骑士", "雾化操作员", "骨架射手", "镜海潜伏者", "熵火猎犬", "冰晶单元",
    "风压单元", "地壳单元", "暗物质单元", "生态树卫", "血能技师", "故障术士", "屏障卫士", "轨道狼王", "灵魂归档者", "钢铁构装体",
    "双足巡飞龙", "暗环织蛛", "镜像残影", "锁链监工", "遗构守卫", "星图观测者", "真空祭司", "低温女巫", "疫源萨满", "赤炉掠夺者",
    "风暴调度者", "深层猎手", "月面幽影", "日冕守卫", "失序聚合体", "时序监视者", "概率编织者", "终末书记官", "界面漫游者", "古代维护者",
)


_BOSS_NAMES = (
    ("许德拉·九首疫巢", "许德拉"), ("耶梦加得·毒环协议", "耶梦加得"),
    ("法厄同·赤昼失控", "法厄同"), ("奇美拉·复合灾兽", "奇美拉"),
    ("曼提柯尔·荒原猎杀号", "曼提柯尔"), ("贝希摩斯·地壳工程体", "贝希摩斯"),
    ("无面混沌·未定义体", "无面混沌"), ("诺克斯·黄昏巡航龙", "诺克斯"),
    ("无首刑官·永夜序列", "无首刑官"), ("莫拉格·镜海巨妖", "莫拉格"),
    ("猩红王·超载战猿", "猩红王"), ("斯廷法洛斯·铁羽群主", "斯廷法洛斯"),
    ("塞壬·高空女王", "塞壬"), ("巴西利斯克·凝固视线", "巴西利斯克"),
    ("索尔姆·雷暴巨构", "索尔姆"), ("斯库尔·逐日猎机", "斯库尔"),
    ("菲尼克斯·熵火再生体", "菲尼克斯"), ("凯尔派·洪潮引擎", "凯尔派"),
    ("斯库拉·深层猎兽", "斯库拉"), ("独眼者·荒原钻机", "荒原独眼"),
    ("亡语者·幽灵主机", "亡语者"), ("腐朽始祖·尸构母体", "腐朽始祖"),
    ("九尾拟态·魅惑协议", "九尾拟态"), ("墨菲斯·梦境侵入者", "墨菲斯"),
    ("金翼·狮鹫统领", "金翼"), ("特里同·镜海龙王", "特里同"),
    ("奥雷恩·风暴泰坦", "奥雷恩"), ("伊瑟琳·零温女王", "伊瑟琳"),
    ("阿格尼·赤炉统治者", "阿格尼"), ("诺萨·疫源领主", "诺萨"),
    ("德古拉·血能伯爵", "德古拉"), ("亡骸骨龙·空壳之翼", "亡骸骨龙"),
    ("阿撒兹勒·折翼观测者", "阿撒兹勒"), ("米诺陶洛斯·迷宫核心", "米诺陶洛斯"),
    ("阿尔格斯·独眼铸造机", "阿尔格斯"), ("梅杜莎·凝固女王", "梅杜莎"),
    ("克拉肯·深海采掘体", "克拉肯"), ("利维坦·吞海母舰", "利维坦"),
    ("阿特拉斯·擎天构造体", "阿特拉斯"), ("加姆·冥轨猎犬", "加姆"),
    ("尤克特·生态树王", "尤克特"), ("莫德雷德·幽魂骑士", "莫德雷德"),
    ("米诺斯·裁决终端", "米诺斯"), ("厄瑞玻斯·真空执政官", "厄瑞玻斯"),
    ("克洛诺斯·时序巨龙", "克洛诺斯"), ("莫伊莱·概率编织群", "莫伊莱"),
    ("纳西索斯·镜像领主", "纳西索斯"), ("塔罗斯·钢铁泰坦", "塔罗斯"),
    ("哈提·噬月机兽", "哈提"), ("苏尔特·坠日驱动者", "苏尔特"),
    ("欧罗巴·轨道巨兽", "欧罗巴"), ("缪斯·万卷档案官", "缪斯"),
    ("布里阿瑞俄斯·断环巨构", "布里阿瑞俄斯"), ("赫利俄斯·日冕镜阵", "赫利俄斯"),
    ("寂静指挥官·零号", "零号指挥官"), ("阿拉克涅·蜂群母体", "阿拉克涅"),
    ("安提凯希拉·时序机", "安提凯希拉"), ("卡律布狄斯·视界吞噬者", "卡律布狄斯"),
    ("忒弥斯·协议裁决者", "忒弥斯"), ("第十三核心·未署名母机", "第十三核心"),
)


_BEHAVIOR_DISPLAY = {
    "heavy_strike": ("重击", "使用低频而沉重的攻击。", ("粉碎", "巨力", "破城", "重锤")),
    "rapid_attack": ("迅击", "提高行动频率持续攻击。", ("疾行", "闪击", "风驰", "迅猛")),
    "combo": ("连击", "一次行动完成多次攻击。", ("剑舞", "连斩", "多重", "狂舞")),
    "follow_up": ("追击", "发现破绽后追加攻击。", ("猎杀", "追猎", "逐影", "穷追")),
    "execute": ("处决", "优先攻击生命较低的目标。", ("处刑", "终结", "断头", "死刑")),
    "charged_burst": ("蓄力", "蓄积能量后集中爆发。", ("蓄能", "超载", "聚能", "爆裂")),
    "piercing": ("穿透", "穿透护甲制造伤害。", ("穿甲", "贯穿", "破盾", "透骨")),
    "true_damage": ("真实伤害", "绕开常规护甲直接伤害。", ("虚空", "纯粹", "湮灭", "无视")),
    "splash": ("溅射", "攻击会波及邻近单位。", ("震荡", "横扫", "爆裂", "冲击")),
    "area_attack": ("范围攻击", "同时攻击多个敌人。", ("风暴", "横扫", "毁灭", "席卷")),
    "poison": ("中毒", "施加持续生效的毒素。", ("腐蚀", "剧毒", "瘟疫", "毒牙")),
    "burn": ("燃烧", "以火焰持续消耗目标。", ("烈焰", "焚烧", "熔火", "灰烬")),
    "bleed": ("流血", "制造伤口持续造成伤害。", ("血刃", "撕裂", "放血", "猩红")),
    "mark_detonation": ("标记引爆", "积累协议标记后引爆。", ("校准", "爆码", "过载", "烙印")),
    "resource_drain": ("同步汲取", "抽取目标同步值恢复自身。", ("截流", "枯竭", "吸能", "断联")),
    "heavy_armor": ("重甲", "以高生命和护甲换取迟缓。", ("铁壁", "堡垒", "钢甲", "磐甲")),
    "shield": ("护盾", "生成护盾吸收攻击。", ("光盾", "屏障", "偏转", "守护")),
    "evasion": ("闪避", "依靠速度回避攻击。", ("幻步", "暗影", "闪现", "虚影")),
    "block": ("格挡", "格挡并削减受到的伤害。", ("盾卫", "壁垒", "坚守", "铁卫")),
    "counter": ("镜返", "主动执行镜像斩击协议。", ("荆棘", "反刃", "复仇", "回击")),
    "lifesteal": ("吸血", "将伤害转化为自身生命。", ("血契", "猩红", "噬血", "生命汲取")),
    "regeneration": ("再生", "持续恢复自身生命。", ("复苏", "再生", "愈合", "常青")),
    "death_guard": ("不死守护", "濒危时保留最后生命。", ("不死", "拒亡", "守魂", "复命")),
    "sunder": ("削甲", "降低目标的护甲。", ("破甲", "碎盾", "侵蚀", "裂铠")),
    "stun": ("眩晕", "令目标短暂无法行动。", ("震荡", "雷击", "昏迷", "重震")),
    "freeze": ("冻结", "使用寒冰冻结目标。", ("霜缚", "冰封", "永冻", "寒潮")),
    "sleep": ("催眠", "令目标陷入沉睡。", ("梦雾", "沉眠", "迷梦", "梦魇")),
    "slow": ("减速", "降低目标行动速度。", ("迟缓", "重力", "霜足", "时滞")),
    "taunt": ("嘲讽", "迫使敌人改变攻击目标。", ("挑衅", "守卫", "拦截", "统御")),
    "cooldown_lock": ("冷却封锁", "延长目标能力冷却。", ("禁用", "锁定", "断绝", "静默")),
    "volatile": ("狂乱", "攻击强度在高低间剧烈波动。", ("狂乱", "混沌", "失序", "命运")),
    "sacrifice": ("过载", "消耗自身生命强化攻击。", ("过载", "燃血", "极限", "舍命")),
}


def _build_entries() -> tuple[dict[str, SkinEntry], dict[str, tuple[str, ...]], dict[str, str]]:
    regular_keys = tuple(value.key for value in REGULAR_ENEMY_BLUEPRINTS)
    boss_blueprints = BOSS_BLUEPRINTS
    behavior_keys = {value.key for value in BEHAVIOR_BLUEPRINTS}
    if len(_REGULAR_NAMES) != len(regular_keys) or len(_BOSS_NAMES) != len(boss_blueprints):
        raise ValueError("星环界敌人名称必须完整覆盖正式敌人身份")
    boss_names = dict(zip((value.key for value in boss_blueprints), _BOSS_NAMES, strict=True))
    if set(_BEHAVIOR_DISPLAY) != behavior_keys:
        raise ValueError("星环界行为名称必须完整覆盖正式行为模板")
    all_names = [
        *_REGULAR_NAMES,
        *(boss_names[value.key][0] for value in boss_blueprints),
    ]
    if len(all_names) != len(set(all_names)):
        raise ValueError("星环界敌人完整名称不能重复")
    entries = {
        ENEMY_RANK_NORMAL_ID: SkinEntry(name="普通敌人"),
        ENEMY_RANK_ELITE_ID: SkinEntry(name="精英敌人"),
        ENEMY_RANK_BOSS_ID: SkinEntry(name="首领敌人"),
        ENCOUNTER_SCOPE_PERSONAL_ID: SkinEntry(name="个人遭遇"),
        ENCOUNTER_SCOPE_PARTY_ID: SkinEntry(name="队伍挑战"),
        PERSONAL_NORMAL_ENCOUNTER_ID: SkinEntry(name="普通遭遇"),
        PERSONAL_ELITE_ENCOUNTER_ID: SkinEntry(name="精英遭遇"),
        PERSONAL_BOSS_ENCOUNTER_ID: SkinEntry(name="首领挑战"),
        PARTY_BOSS_ENCOUNTER_ID: SkinEntry(name="队伍首领"),
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
        entries[behavior_id] = SkinEntry(name=f"敌性·{name}", description=description, icon="✦")
        entries[f"ability.enemy.{key}"] = SkinEntry(name=f"敌技·{name}", description=description, icon="✦")
        prefixes[behavior_id] = values
        behavior_names[behavior_id] = name
    entries.update(
        build_enemy_behavior_mechanism_entries(
            ENEMY_BEHAVIOR_CONTENT.display_owners,
            entries,
        )
    )
    return entries, prefixes, behavior_names


STELLAR_RING_ENEMY_ENTRIES, STELLAR_RING_ENEMY_PREFIXES, STELLAR_RING_ENEMY_BEHAVIOR_NAMES = _build_entries()


__all__ = ["STELLAR_RING_ENEMY_BEHAVIOR_NAMES", "STELLAR_RING_ENEMY_ENTRIES", "STELLAR_RING_ENEMY_PREFIXES"]
