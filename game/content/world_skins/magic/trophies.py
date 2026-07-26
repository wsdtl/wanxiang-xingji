"""魔法世界的探险与组队首领战利品展示。"""

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
    GREEN_CLOUD_PLAIN_ID: ("晨露草", "风语种", "白鹿绒", "青辉石", "云雀羽", "黎明晶髓"),
    SUNSET_RIDGE_ID: ("曦光花", "红枫叶", "晨霞砂", "狮鹫绒羽", "曙光棱晶", "晨曦宝石"),
    BLACK_WIND_RAVINE_ID: ("阴影苔", "乌木枝", "幽影砂", "暗羽翎", "暗影石", "风蚀魔核"),
    MIRROR_LAKE_MARSH_ID: ("镜湖珠", "沼泽兰根", "湖蚌珍珠", "龟甲片", "幻雾囊", "镜心水晶"),
    SCARLET_FLAME_VALLEY_ID: ("炎脉石", "烈焰草", "炎金砂", "火鸟羽", "地火晶", "熔岩之心"),
    VERDANT_WILDERNESS_ID: ("翡翠叶", "魔力藤", "翡翠树脂", "精灵羽", "翡翠木心", "世界树残芯"),
    THUNDER_MARSH_STEPPE_ID: ("风暴木", "雷纹砂", "雷兽皮", "风暴鹰羽", "风暴晶", "雷霆源质"),
    NORTHERN_ABYSS_SNOWFIELD_ID: ("寒霜花", "冻土玉屑", "雪兽绒", "永冬蛛丝", "永冬晶", "极寒源质"),
    BROKEN_PILLAR_RELIC_ID: ("泰坦石屑", "大地尘", "泰坦骨片", "泰坦铜", "地脉晶核", "神铸遗石"),
    KUNLUN_SKY_RUINS_ID: ("神域圣露", "天穹晶屑", "圣兽毫", "天门守卫甲", "神界晶", "金苹果核"),
    MYRIAD_SWORD_TOMB_ID: ("锈蚀剑片", "英灵披带", "断锋魔钢", "武魂尘", "英雄铭牌", "兵冢魂髓"),
    HEAVENLY_CRAFT_RELIC_ID: ("奥术齿轮", "秘银铜片", "魔像木心", "泰坦轴承", "奥械核心", "神炉火种"),
    RETURNING_RUIN_ABYSS_ID: ("深渊黑砂", "混沌潮晶", "邪魔骨", "灾兽血珀", "混沌魂核", "混沌魔髓"),
}

_REGULAR_TROPHY_NAMES = (
    "山地巨猿臂骨", "狼人獠牙", "狐灵尾毛", "毒蛛毒囊", "蛇人蜕鳞", "骷髅卫兵肋骨",
    "水妖凝珠", "幻形怪面膜", "石像鬼石角", "吸血鬼血晶", "梦魇鬃毛", "魔像核心",
    "狮鹫金羽", "霜狼皮", "金鬃野猪鬃", "鹰身女妖爪", "狂暴猿战血", "水蛭怪血囊",
    "瘟疫兽腐皮", "火鸟炎羽", "雷兽电角", "巨蟒鳞", "暗影豹幽瞳", "牛头人独角",
    "死亡骑士甲片", "迷雾女巫雾珠", "骷髅弓手指骨", "沼泽潜伏者背鳞", "地狱犬尾焰", "冰元素晶核",
    "风元素晶核", "土元素晶核", "暗影元素晶核", "树人心木", "血法师血石", "诅咒术士符骨",
    "圣盾守卫盾片", "狼王獠牙", "灵魂收割者镰片", "钢铁魔像机芯", "双足飞龙翼膜", "深渊蜘蛛丝囊",
    "镜像幽灵镜片", "锁链看守锁环", "遗迹守卫石睛", "星界先知星屑", "虚空祭司虚晶", "冰霜女巫寒魄",
    "瘟疫萨满疫珠", "火焰掠夺者炎章", "风暴召唤者雷瓶", "深渊猎手暗皮", "月影幽灵月纱", "日耀守卫曜片",
    "混沌魔兽浊核", "时间守望者时砂", "命运织女命丝", "死亡书记官墨骨", "位面旅者界尘", "远古守卫符石",
)

_BOSS_TROPHY_NAMES = (
    "九头蛇毒腺", "耶梦加得鳞", "炎魔心核", "奇美拉鬃", "曼提柯尔尾刺", "贝希摩斯甲片",
    "无面者胎膜", "诺克斯龙瞳", "无头骑士盔片", "莫拉格水晶", "猩红王战血", "斯廷法洛斯铁羽",
    "塞壬王冠羽", "巴西利斯克石化眼", "索尔姆雷核", "芬里尔蚀日牙", "焚世凤凰余烬", "凯尔派洪水鬃",
    "斯库拉深渊爪", "荒原独眼晶", "亡语者幽冥玺", "腐朽始祖尸骨", "魅惑女王尾毫", "墨菲斯梦晶",
    "金翼狮鹫羽", "特里同龙鳞", "奥雷恩风暴核", "伊瑟琳冰冠碎片", "阿格尼焚焰珠", "诺萨瘟疫令",
)

_PARTY_BOSS_TROPHY_NAMES = (
    "德古拉血晶", "亡骸骨翼", "阿撒兹勒残羽", "迷宫王角", "阿尔格斯炉眼",
    "梅杜莎石瞳", "克拉肯巨触", "利维坦逆鳞", "泰坦地核", "加姆冥牙",
    "尤克特年轮心", "莫德雷德断剑", "米诺斯裁决印", "厄瑞玻斯虚空核", "克洛诺斯时鳞",
    "莫伊莱命线", "纳西索斯镜片", "塔罗斯铁心", "哈提月蚀牙", "苏尔特焰核",
    "欧罗巴星甲", "缪斯档案晶", "百臂巨构芯", "赫利俄斯镜片", "零号静默令",
    "阿拉克涅母丝", "安提凯希拉齿轮", "卡律布狄斯视界核", "忒弥斯裁决印", "第十三母机片",
)

_CURIO_NAMES = (
    "贤者石残片", "命运金线", "创世余烬", "世界树种", "永恒圣露", "诸神秘银",
    "星界罗盘碎片", "冥河誓石", "太阳神辉", "月神银华", "混沌原石", "创世以太",
)


def _build_entries() -> dict[str, SkinEntry]:
    entries: dict[str, SkinEntry] = {}
    for location_id, names in _REGION_NAMES.items():
        item_ids = REGION_TROPHY_ITEM_IDS[location_id]
        for item_id, name in zip(item_ids, names):
            entries[item_id] = SkinEntry(
                name=name,
                description=f"在此地探险取得的{name}，王城设有固定收购价。",
                icon="◆",
            )
    regular_enemy_ids = tuple(f"enemy.{value.key}" for value in REGULAR_ENEMY_BLUEPRINTS)
    for enemy_id, name in zip(regular_enemy_ids, _REGULAR_TROPHY_NAMES):
        entries[REGULAR_ENEMY_TROPHY_ITEM_IDS[enemy_id]] = SkinEntry(
            name=name,
            description=f"击败对应魔物后取得的{name}。",
            icon="◇",
        )
    boss_enemy_ids = tuple(
        f"enemy.boss.{value.key}" for value in PERSONAL_BOSS_BLUEPRINTS
    )
    for enemy_id, name in zip(boss_enemy_ids, _BOSS_TROPHY_NAMES):
        entries[BOSS_TROPHY_ITEM_IDS[enemy_id]] = SkinEntry(
            name=name,
            description=f"仅有对应首领会留下的{name}。",
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
            description=f"组队击破对应强敌后取得的{name}。",
            icon="✦",
        )
    for item_id, name in zip(WORLD_CURIO_ITEM_IDS, _CURIO_NAMES):
        entries[item_id] = SkinEntry(
            name=name,
            description=f"魔法世界极难得见的奇珍: {name}。",
            icon="✧",
        )
    if len({entry.name for entry in entries.values()}) != len(entries):
        raise ValueError("魔法世界战利品名称不能重复")
    return entries


MAGIC_TROPHY_ENTRIES = _build_entries()


__all__ = ["MAGIC_TROPHY_ENTRIES"]
