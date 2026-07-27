"""魔法世界的敌人身份、行为术语与精英前缀。"""

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
    "山地巨猿", "狼人", "狐灵", "巨型毒蛛", "蛇人", "骷髅卫兵", "水妖", "幻形怪", "石像鬼", "吸血鬼",
    "梦魇", "魔像", "狮鹫", "霜狼", "金鬃野猪", "鹰身女妖", "狂暴猿", "水蛭怪", "瘟疫兽", "火鸟",
    "雷兽", "巨蟒", "暗影豹", "牛头人", "死亡骑士", "迷雾女巫", "骷髅弓手", "沼泽潜伏者", "地狱犬", "冰元素",
    "风元素", "土元素", "暗影元素", "树人", "血法师", "诅咒术士", "圣盾守卫", "狼王", "灵魂收割者", "钢铁魔像",
    "双足飞龙", "深渊蜘蛛", "镜像幽灵", "锁链看守", "遗迹守卫", "星界先知", "虚空祭司", "冰霜女巫", "瘟疫萨满", "火焰掠夺者",
    "风暴召唤者", "深渊猎手", "月影幽灵", "日耀守卫", "混沌魔兽", "时间守望者", "命运织女", "死亡书记官", "位面旅者", "远古守卫",
)


_BOSS_NAMES = (
    ("九头蛇·沼泽暴君", "九头蛇"),
    ("拉冬·百首园卫", "拉冬"),
    ("炎魔·赤地灾厄", "赤地炎魔"),
    ("奇美拉·三首凶兽", "奇美拉"),
    ("曼提柯尔·荒原暴君", "曼提柯尔"),
    ("贝希摩斯·大地巨兽", "贝希摩斯"),
    ("无面者·混沌魔神", "无面者"),
    ("黄昏巨龙·诺克斯", "诺克斯"),
    ("无头骑士·永夜行刑者", "无头骑士"),
    ("湖中巨妖·莫拉格", "莫拉格"),
    ("狂战巨猿·猩红王", "猩红王"),
    ("九首妖鸟·斯廷法洛斯", "斯廷法洛斯"),
    ("鹰身女王·塞壬", "塞壬"),
    ("蛇怪之王·巴西利斯克", "巴西利斯克"),
    ("雷霆巨人·索尔姆", "索尔姆"),
    ("斯库尔·逐日魔狼", "斯库尔"),
    ("凤凰·焚世余烬", "焚世凤凰"),
    ("凯尔派·洪水之兆", "凯尔派"),
    ("深渊猎兽·斯库拉", "斯库拉"),
    ("独眼巨人·荒原之主", "荒原独眼"),
    ("幽灵皇帝·亡语者", "亡语者"),
    ("尸王·腐朽始祖", "腐朽始祖"),
    ("九尾妖狐·魅惑女王", "魅惑女王"),
    ("梦魇领主·墨菲斯", "墨菲斯"),
    ("狮鹫王·金翼", "金翼"),
    ("海龙王·特里同", "特里同"),
    ("风暴泰坦·奥雷恩", "奥雷恩"),
    ("冰霜女王·伊瑟琳", "伊瑟琳"),
    ("焚焰王·阿格尼", "阿格尼"),
    ("瘟疫领主·诺萨", "诺萨"),
    ("吸血鬼伯爵·德古拉", "德古拉"),
    ("骨龙·亡骸之翼", "亡骸骨龙"),
    ("堕落天使·阿撒兹勒", "阿撒兹勒"),
    ("米诺陶洛斯·迷宫领主", "米诺陶洛斯"),
    ("独眼锻造神·阿尔格斯", "阿尔格斯"),
    ("梅杜莎·石化女王", "梅杜莎"),
    ("克拉肯·深渊巨妖", "克拉肯"),
    ("利维坦·吞海者", "利维坦"),
    ("泰坦·擎天者", "擎天泰坦"),
    ("加姆·冥界魔犬", "加姆"),
    ("古树之王·尤克特", "尤克特"),
    ("幽魂骑士·莫德雷德", "莫德雷德"),
    ("冥府判官·米诺斯", "米诺斯"),
    ("虚空执政官·厄瑞玻斯", "厄瑞玻斯"),
    ("时序巨龙·克洛诺斯", "克洛诺斯"),
    ("命运三女神·莫伊莱", "莫伊莱"),
    ("镜界领主·纳西索斯", "纳西索斯"),
    ("钢铁泰坦·塔罗斯", "塔罗斯"),
    ("噬月魔兽·哈提", "哈提"),
    ("法厄同·坠日御者", "法厄同"),
    ("欧罗巴·轨道巨兽", "欧罗巴"),
    ("缪斯·万卷档案官", "缪斯"),
    ("布里阿瑞俄斯·断环巨构", "布里阿瑞俄斯"),
    ("赫利俄斯·日冕镜阵", "赫利俄斯"),
    ("寂静指挥官·零号", "零号指挥官"),
    ("阿拉克涅·蜂群母体", "阿拉克涅"),
    ("安提凯希拉·时序机", "安提凯希拉"),
    ("卡律布狄斯·视界吞噬者", "卡律布狄斯"),
    ("忒弥斯·协议裁决者", "忒弥斯"),
    ("第十三核心·未署名母机", "第十三核心"),
)


_BEHAVIOR_DISPLAY = {
    "heavy_strike": ("重击", "使用低频而沉重的攻击。", ("粉碎", "巨力", "破城", "重锤")),
    "rapid_attack": ("迅击", "提高行动频率持续攻击。", ("疾行", "闪击", "风驰", "迅猛")),
    "combo": ("连击", "一次行动完成多次攻击。", ("剑舞", "连斩", "多重", "狂舞")),
    "follow_up": ("追击", "发现破绽后追加攻击。", ("猎杀", "追猎", "逐影", "穷追")),
    "execute": ("处决", "优先攻击生命较低的目标。", ("处刑", "终结", "断头", "死刑")),
    "charged_burst": ("蓄力", "蓄积能量后集中爆发。", ("蓄能", "超载", "聚能", "爆裂")),
    "piercing": ("穿透", "穿透护甲制造伤害。", ("穿甲", "贯穿", "破盾", "透骨")),
    "true_damage": ("纯粹伤害", "以纯粹伤害绕开常规护甲。", ("虚空", "纯粹", "湮灭", "无视")),
    "splash": ("溅射", "攻击会波及邻近单位。", ("震荡", "横扫", "爆裂", "冲击")),
    "area_attack": ("范围攻击", "同时攻击多个敌人。", ("风暴", "横扫", "毁灭", "席卷")),
    "poison": ("中毒", "施加持续生效的毒素。", ("腐蚀", "剧毒", "瘟疫", "毒牙")),
    "burn": ("燃烧", "以火焰持续消耗目标。", ("烈焰", "焚烧", "熔火", "灰烬")),
    "bleed": ("流血", "制造伤口持续造成伤害。", ("血刃", "撕裂", "放血", "猩红")),
    "mark_detonation": ("印记引爆", "积累魔法印记后引爆。", ("秘印", "爆印", "符爆", "烙印")),
    "resource_drain": ("魔力汲取", "抽取目标魔力恢复自身。", ("噬魔", "枯竭", "吸能", "魔蚀")),
    "heavy_armor": ("重甲", "以高生命和护甲换取迟缓。", ("铁壁", "堡垒", "钢甲", "磐甲")),
    "shield": ("护盾", "生成护盾吸收攻击。", ("圣盾", "屏障", "魔障", "守护")),
    "evasion": ("闪避", "依靠速度回避攻击。", ("幻步", "暗影", "闪现", "虚影")),
    "block": ("格挡", "格挡并削减受到的伤害。", ("盾卫", "壁垒", "坚守", "铁卫")),
    "counter": ("反刃", "主动挥刃攻击并压制目标。", ("荆棘", "反刃", "复仇", "回击")),
    "lifesteal": ("吸血", "将伤害转化为自身生命。", ("血契", "猩红", "噬血", "生命汲取")),
    "regeneration": ("再生", "持续恢复自身生命。", ("复苏", "再生", "愈合", "常青")),
    "death_guard": ("不死守护", "濒危时保留最后生命。", ("不死", "拒亡", "守魂", "复命")),
    "sunder": ("削甲", "降低目标的护甲。", ("破甲", "碎盾", "侵蚀", "裂铠")),
    "stun": ("眩晕", "令目标短暂无法行动。", ("震荡", "雷击", "昏迷", "重震")),
    "freeze": ("冻结", "尝试对目标施加冻结。", ("霜缚", "冰封", "永冻", "寒潮")),
    "sleep": ("催眠", "尝试对目标施加睡眠。", ("梦雾", "沉眠", "迷梦", "梦魇")),
    "slow": ("减速", "降低目标行动速度。", ("迟缓", "重力", "霜足", "时滞")),
    "taunt": ("嘲讽", "迫使敌人改变攻击目标。", ("挑衅", "守卫", "拦截", "统御")),
    "cooldown_lock": ("冷却封锁", "延长目标能力冷却。", ("禁魔", "封法", "断绝", "沉默")),
    "volatile": ("狂乱", "攻击强度在高低间剧烈波动。", ("狂乱", "混沌", "失序", "命运")),
    "sacrifice": ("献祭", "消耗自身生命强化攻击。", ("献祭", "燃血", "血誓", "舍命")),
}


def _build_entries() -> tuple[dict[str, SkinEntry], dict[str, tuple[str, ...]], dict[str, str]]:
    regular_keys = tuple(value.key for value in REGULAR_ENEMY_BLUEPRINTS)
    boss_blueprints = BOSS_BLUEPRINTS
    behavior_keys = {value.key for value in BEHAVIOR_BLUEPRINTS}
    if len(_REGULAR_NAMES) != len(regular_keys) or len(_BOSS_NAMES) != len(boss_blueprints):
        raise ValueError("魔法世界敌人名称必须完整覆盖正式敌人身份")
    boss_names = dict(zip((value.key for value in boss_blueprints), _BOSS_NAMES, strict=True))
    if set(_BEHAVIOR_DISPLAY) != behavior_keys:
        raise ValueError("魔法世界行为名称必须完整覆盖正式行为模板")
    all_names = [
        *_REGULAR_NAMES,
        *(boss_names[value.key][0] for value in boss_blueprints),
    ]
    if len(all_names) != len(set(all_names)):
        raise ValueError("魔法世界敌人完整名称不能重复")
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


MAGIC_ENEMY_ENTRIES, MAGIC_ENEMY_PREFIXES, MAGIC_ENEMY_BEHAVIOR_NAMES = _build_entries()


__all__ = ["MAGIC_ENEMY_BEHAVIOR_NAMES", "MAGIC_ENEMY_ENTRIES", "MAGIC_ENEMY_PREFIXES"]
