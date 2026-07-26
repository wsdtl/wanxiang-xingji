"""星环界的探险与组队首领战利品展示。"""

from game.core.gameplay import SkinEntry

from ...catalog.enemy.blueprints import (
    CULTIVATION_PARTY_BOSS_BLUEPRINTS,
    MAGIC_PARTY_BOSS_BLUEPRINTS,
    STELLAR_RING_PARTY_BOSS_BLUEPRINTS,
    PERSONAL_BOSS_BLUEPRINTS,
    REGULAR_ENEMY_BLUEPRINTS,
)
from .enemies import STELLAR_RING_ENEMY_ENTRIES
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
    GREEN_CLOUD_PLAIN_ID: ("穹原孢子", "生态种荚", "仿生绒", "青氧晶", "巡隼羽片", "穹顶母种"),
    SUNSET_RIDGE_ID: ("曙光藻", "晨昏叶", "轨枕碎片", "光帆纤维", "暮线晶", "日照校准核"),
    BLACK_WIND_RAVINE_ID: ("静默苔", "断讯线", "吸光砂", "夜视镜片", "暗频晶", "失联信标"),
    MIRROR_LAKE_MARSH_ID: ("冷却珠", "导流根", "镜海珍珠", "耐压甲片", "雾化囊", "深冷泵芯"),
    SCARLET_FLAME_VALLEY_ID: ("赤炉石", "耐热芽", "赤炉金砂", "熵火羽", "等离子晶", "废热炉心"),
    VERDANT_WILDERNESS_ID: ("培育叶", "自律藤", "合成树脂", "授粉翼片", "生态木芯", "原生质种核"),
    THUNDER_MARSH_STEPPE_ID: ("脉冲木", "电容砂", "绝缘皮", "导电羽片", "高压晶", "雷网主栓"),
    NORTHERN_ABYSS_SNOWFIELD_ID: ("低温花", "冻存屑", "保温绒", "冷凝丝", "零温晶", "封存主钥"),
    BROKEN_PILLAR_RELIC_ID: ("断环石屑", "结构尘", "旧骨架片", "环城合金", "承重晶核", "天环铭板"),
    KUNLUN_SKY_RUINS_ID: ("真空露", "观测晶屑", "传感纤维", "阵列护甲", "深空晶", "界海坐标核"),
    MYRIAD_SWORD_TOMB_ID: ("锈蚀刃片", "军团织带", "断锋合金", "战术尘", "兵装铭牌", "作战母芯"),
    HEAVENLY_CRAFT_RELIC_ID: ("精密齿轮", "记忆合金片", "构装机芯", "母厂轴承", "造物核心", "原型火种"),
    RETURNING_RUIN_ABYSS_ID: ("暗环黑砂", "失序潮晶", "异常骨架", "红移琥珀", "暗环主核", "第十三残片"),
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
)

_CURIO_NAMES = (
    "零号设计图", "概率金线", "初启余烬", "生态母种", "永续冷却液", "原初合金",
    "界海罗盘片", "航路誓石", "日冕光片", "月面银尘", "失序原石", "造物源质",
)


def _build_entries() -> dict[str, SkinEntry]:
    entries: dict[str, SkinEntry] = {}
    for location_id, names in _REGION_NAMES.items():
        item_ids = REGION_TROPHY_ITEM_IDS[location_id]
        for item_id, name in zip(item_ids, names):
            entries[item_id] = SkinEntry(
                name=name,
                description=f"在此地探险取得的{name}，环心天城设有固定收购价。",
                icon="◆",
            )
    regular_enemy_ids = tuple(f"enemy.{value.key}" for value in REGULAR_ENEMY_BLUEPRINTS)
    for enemy_id in regular_enemy_ids:
        name = f"{STELLAR_RING_ENEMY_ENTRIES[enemy_id].compact_name}样本"
        entries[REGULAR_ENEMY_TROPHY_ITEM_IDS[enemy_id]] = SkinEntry(
            name=name,
            description=f"击败对应异常体后取得的{name}。",
            icon="◇",
        )
    boss_enemy_ids = tuple(
        f"enemy.boss.{value.key}" for value in PERSONAL_BOSS_BLUEPRINTS
    )
    for enemy_id in boss_enemy_ids:
        name = f"{STELLAR_RING_ENEMY_ENTRIES[enemy_id].compact_name}核心"
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
    for enemy_id in party_enemy_ids:
        name = f"{STELLAR_RING_ENEMY_ENTRIES[enemy_id].compact_name}残核"
        entries[PARTY_BOSS_TROPHY_ITEM_IDS[enemy_id]] = SkinEntry(
            name=name,
            description=f"组队击破对应强敌后取得的{name}。",
            icon="✦",
        )
    for item_id, name in zip(WORLD_CURIO_ITEM_IDS, _CURIO_NAMES):
        entries[item_id] = SkinEntry(
            name=name,
            description=f"星环界极难取得的遗存: {name}。",
            icon="✧",
        )
    if len({entry.name for entry in entries.values()}) != len(entries):
        raise ValueError("星环界战利品名称不能重复")
    return entries


STELLAR_RING_TROPHY_ENTRIES = _build_entries()


__all__ = ["STELLAR_RING_TROPHY_ENTRIES"]
