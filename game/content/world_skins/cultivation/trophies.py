"""太玄界的探险与组队首领战利品展示。"""

from game.core.gameplay import SkinEntry

from ...catalog.enemy.blueprints import (
    CULTIVATION_PARTY_BOSS_BLUEPRINTS,
    MAGIC_PARTY_BOSS_BLUEPRINTS,
    STELLAR_RING_PARTY_BOSS_BLUEPRINTS,
    PERSONAL_BOSS_BLUEPRINTS,
    REGULAR_ENEMY_BLUEPRINTS,
)
from ...catalog.item.trophies import (
    BOSS_TROPHY_ITEM_IDS,
    PARTY_BOSS_TROPHY_ITEM_IDS,
    REGION_TROPHY_ITEM_IDS,
    REGULAR_ENEMY_TROPHY_ITEM_IDS,
    WORLD_CURIO_ITEM_IDS,
)
from ...catalog.world import (
    BLACK_WIND_RAVINE_ID,
    BROKEN_PILLAR_RELIC_ID,
    GREEN_CLOUD_PLAIN_ID,
    HEAVENLY_CRAFT_RELIC_ID,
    KUNLUN_SKY_RUINS_ID,
    MIRROR_LAKE_MARSH_ID,
    MYRIAD_SWORD_TOMB_ID,
    NORTHERN_ABYSS_SNOWFIELD_ID,
    RETURNING_RUIN_ABYSS_ID,
    SCARLET_FLAME_VALLEY_ID,
    SUNSET_RIDGE_ID,
    THUNDER_MARSH_STEPPE_ID,
    VERDANT_WILDERNESS_ID,
)


_REGION_NAMES = {
    GREEN_CLOUD_PLAIN_ID: ("青云露", "迎风草籽", "白鹿茸屑", "青纹石", "灵雀尾羽", "朝元玉髓"),
    SUNSET_RIDGE_ID: ("霞栖花", "丹枫叶", "赤岩砂", "云鹤翎", "暮光晶", "朱霞玉"),
    BLACK_WIND_RAVINE_ID: ("阴风苔", "乌骨木", "黑曜砂", "夜枭羽", "玄阴石", "风蚀妖核"),
    MIRROR_LAKE_MARSH_ID: ("镜水珠", "泽兰根", "青蚌珠", "玄龟甲片", "蜃雾囊", "镜心璃"),
    SCARLET_FLAME_VALLEY_ID: ("火纹石", "赤焰草", "熔金砂", "火鸦羽", "地肺晶", "赤炎髓"),
    VERDANT_WILDERNESS_ID: ("苍梧叶", "木灵藤", "古树脂", "青鸾羽", "灵木心", "建木残芯"),
    THUNDER_MARSH_STEPPE_ID: ("雷击木", "电纹砂", "夔皮碎片", "雷鸟翎", "霆光晶", "雷泽神髓"),
    NORTHERN_ABYSS_SNOWFIELD_ID: ("玄冰花", "寒玉屑", "雪魄绒", "冰蚕丝", "北冥晶", "玄霜髓"),
    BROKEN_PILLAR_RELIC_ID: ("天柱石屑", "息壤尘", "古神骨片", "裂天铜", "不周晶核", "补天遗玉"),
    KUNLUN_SKY_RUINS_ID: ("瑶池露", "昆仑玉屑", "陆吾毫", "开明兽甲", "天门晶", "蟠桃灵核"),
    MYRIAD_SWORD_TOMB_ID: ("锈剑残片", "古剑衣", "断锋寒铁", "剑魄尘", "古剑铭片", "万剑灵髓"),
    HEAVENLY_CRAFT_RELIC_ID: ("机关齿轮", "云纹铜片", "傀儡木心", "天工玉轴", "玄金机核", "造化炉芯"),
    RETURNING_RUIN_ABYSS_ID: ("魔渊黑砂", "归墟潮晶", "邪煞骨", "魔血琥珀", "深渊魂核", "归墟魔髓"),
}

_REGULAR_TROPHY_NAMES = (
    "山魈臂骨", "啸月狼牙", "狐妖尾毫", "蛛妖毒囊", "蛇妖蜕鳞", "尸傀阴骨",
    "水鬼发结", "画皮残面", "夜叉鬼角", "罗刹血玉", "梦貘香囊", "石傀心核",
    "狰尾刺", "孟极雪皮", "当康金鬃", "蛊雕喙骨", "朱厌战血", "长右水囊",
    "蜚疫皮", "毕方火羽", "夔牛雷皮", "巴蛇巨鳞", "猫鬼幽瞳", "诸怀独角",
    "飞僵尸甲", "雾魅凝珠", "骨妖肋刃", "水魅镜鳞", "火鼠赤尾", "冰蚕玄丝",
    "雷兽电角", "土蝼掘爪", "魑魅影尘", "木魅灵枝", "血尸心血", "咒灵符骨",
    "金甲尸甲片", "啸月狼王牙", "勾魂使锁片", "铜甲傀机芯", "鹏妖金羽", "蜃妖幻珠",
    "镜妖碎镜", "锁魂鬼锁环", "镇墓兽石睛", "星官残星屑", "无常哭丧签", "雪魅寒魄",
    "疫鬼瘟珠", "火鸦炎羽", "雷公虫雷囊", "魍魉影皮", "月魅月纱", "日游神曜片",
    "混沌兽浊核", "烛阴时鳞", "织命蛛命丝", "判官残墨", "界游仙界尘", "守山灵地契碎片",
)

_BOSS_TROPHY_NAMES = (
    "九婴毒血囊", "相柳毒牙", "旱魃火骨", "穷奇凶翎", "梼杌顽骨", "饕餮胃石",
    "混沌无相胎膜", "烛龙瞳鳞", "刑天战纹甲", "无支祁水鬃", "朱厌兵灾骨", "鬼车九首羽",
    "蛊雕王喙", "巴蛇王蜕", "夔牛王雷皮", "天狗蚀日牙", "金乌残羽", "夫诸水角",
    "猰貐弱水爪", "獓因荒角", "罗酆鬼玺碎片", "不化骨残片", "九尾狐尾毫", "食梦囊",
    "陆吾金纹爪", "敖渊龙鳞", "应玄雷印", "幽寒冰冠碎片", "赤霄离火珠", "疫主瘟令",
)

_PARTY_BOSS_TROPHY_NAMES = (
    "冥河血玉", "苍骸龙骨", "堕仙残翼", "无归阵枢", "熔岳炉眼",
    "青鳞石瞳", "吞舟巨触", "覆溟逆鳞", "岳沉地核", "食日狼牙",
    "青帝祖心", "夜巡阴兵令", "崔府君笔锋", "无极魔印", "长明时鳞",
    "司罗命丝", "照世镜屑", "蚩尤战角", "望舒寒珠", "大羿弓屑",
    "巡天巨兽骨", "万卷天机芯", "断环巨神核", "金乌日镜片", "无声天将令",
    "织机母巢丝", "岁轮机心", "饕餮界核", "天条法印", "十三天枢片",
)

_CURIO_NAMES = (
    "河图残页", "洛书玉简", "女娲石屑", "盘古斧痕", "昆仑神木种", "扶桑金叶",
    "息壤", "三生石片", "烛照残辉", "幽荧月华", "混沌青莲子", "鸿蒙紫气",
)


def _build_entries() -> dict[str, SkinEntry]:
    entries: dict[str, SkinEntry] = {}
    for location_id, names in _REGION_NAMES.items():
        item_ids = REGION_TROPHY_ITEM_IDS[location_id]
        for item_id, name in zip(item_ids, names):
            entries[item_id] = SkinEntry(
                name=name,
                description=f"在此地探险取得的{name}，仙城设有固定收购价。",
                icon="◆",
            )
    regular_enemy_ids = tuple(f"enemy.{value.key}" for value in REGULAR_ENEMY_BLUEPRINTS)
    for enemy_id, name in zip(regular_enemy_ids, _REGULAR_TROPHY_NAMES):
        entries[REGULAR_ENEMY_TROPHY_ITEM_IDS[enemy_id]] = SkinEntry(
            name=name,
            description=f"击败对应妖物后取得的{name}。",
            icon="◇",
        )
    boss_enemy_ids = tuple(
        f"enemy.boss.{value.key}" for value in PERSONAL_BOSS_BLUEPRINTS
    )
    for enemy_id, name in zip(boss_enemy_ids, _BOSS_TROPHY_NAMES):
        entries[BOSS_TROPHY_ITEM_IDS[enemy_id]] = SkinEntry(
            name=name,
            description=f"仅有对应灾主会留下的{name}。",
            icon="✦",
        )
    party_blueprints = (
        ("cultivation", CULTIVATION_PARTY_BOSS_BLUEPRINTS),
        ("magic", MAGIC_PARTY_BOSS_BLUEPRINTS),
        ("stellar_ring", STELLAR_RING_PARTY_BOSS_BLUEPRINTS),
    )
    party_enemy_ids = tuple(
        f"enemy.boss.party.{source}.{value.key}"
        for source, values in party_blueprints
        for value in values
    )
    for enemy_id, name in zip(party_enemy_ids, _PARTY_BOSS_TROPHY_NAMES):
        entries[PARTY_BOSS_TROPHY_ITEM_IDS[enemy_id]] = SkinEntry(
            name=name,
            description=f"结伴击破对应强敌后取得的{name}。",
            icon="✦",
        )
    for item_id, name in zip(WORLD_CURIO_ITEM_IDS, _CURIO_NAMES):
        entries[item_id] = SkinEntry(
            name=name,
            description=f"太玄界极难得见的奇珍: {name}。",
            icon="✧",
        )
    if len({entry.name for entry in entries.values()}) != len(entries):
        raise ValueError("太玄界战利品名称不能重复")
    return entries


CULTIVATION_TROPHY_ENTRIES = _build_entries()


__all__ = ["CULTIVATION_TROPHY_ENTRIES"]
