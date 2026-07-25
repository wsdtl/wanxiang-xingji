"""正式世界的伙伴物种、秘境和公共显示词。"""

from game.core.gameplay import (
    COMBAT_ATTACK,
    COMBAT_DEFENSE,
    COMBAT_SPEED,
    HEALTH_MAXIMUM,
    SPIRIT_MAXIMUM,
    ContentDefinition,
)

from ..foundation import (
    COMMON_QUALITY_ID,
    EPIC_QUALITY_ID,
    FINE_QUALITY_ID,
    LEGENDARY_QUALITY_ID,
    RARE_QUALITY_ID,
)
from ..item.trophies import REGION_TROPHY_ITEM_IDS
from ..world import (
    BLACK_WIND_RAVINE_ID,
    BROKEN_PILLAR_RELIC_ID,
    GREEN_CLOUD_PLAIN_ID,
    MIRROR_LAKE_MARSH_ID,
    HEAVENLY_CRAFT_RELIC_ID,
    KUNLUN_SKY_RUINS_ID,
    PERSON_EAST_LOCATION_ID,
    PERSON_NORTH_LOCATION_ID,
    PERSON_WEST_LOCATION_ID,
    SCARLET_FLAME_VALLEY_ID,
    SUNSET_RIDGE_ID,
    THUNDER_MARSH_STEPPE_ID,
    TAIXUAN_WORLD_ID,
    MAGIC_WORLD_ID,
    STELLAR_RING_WORLD_ID,
    VERDANT_WILDERNESS_ID,
    RETURNING_RUIN_ABYSS_ID,
)
from .models import (
    CompanionBalance,
    CompanionCatalog,
    CompanionGrowthDefinition,
    CompanionSanctuaryDefinition,
    CompanionSpeciesDefinition,
    PersonCompanionDefinition,
)


COMPANION_TERM_ID = "term.companion"
COMPANION_SANCTUARY_TERM_ID = "term.companion_sanctuary"
COMPANION_BIND_ACTION_ID = "term.companion_bind"
COMPANION_FAREWELL_ACTION_ID = "term.companion_farewell"
COMPANION_DISPLAY_DEFINITIONS = tuple(
    ContentDefinition(value, "content.companion_term")
    for value in (
        COMPANION_TERM_ID,
        COMPANION_SANCTUARY_TERM_ID,
        COMPANION_BIND_ACTION_ID,
        COMPANION_FAREWELL_ACTION_ID,
    )
)

def _attributes(health: float, spirit: float, attack: float, defense: float, speed: float):
    return {
        HEALTH_MAXIMUM: health,
        SPIRIT_MAXIMUM: spirit,
        COMBAT_ATTACK: attack,
        COMBAT_DEFENSE: defense,
        COMBAT_SPEED: speed,
    }


def _species(
    key: str,
    world_id: str,
    name: str,
    description: str,
    role: str,
    multipliers,
    core: str,
    traits: tuple[str, ...],
    weight: int = 100,
) -> CompanionSpeciesDefinition:
    return CompanionSpeciesDefinition(
        f"companion.{world_id.removeprefix('world.')}.{key}",
        world_id,
        name,
        description,
        role,
        multipliers,
        f"enemy.behavior.{core}",
        tuple(f"enemy.behavior.{value}" for value in traits),
        weight,
    )


def _person(
    key: str,
    world_id: str,
    location_id: str,
    name: str,
    description: str,
    role: str,
    multipliers,
    core: str,
    trait: str,
    aptitudes: tuple[int, int, int, int],
    gifts: tuple[tuple[str, int], ...],
) -> PersonCompanionDefinition:
    aptitude_ids = (
        "companion.aptitude.vitality",
        "companion.aptitude.offense",
        "companion.aptitude.agility",
        "companion.aptitude.focus",
    )
    return PersonCompanionDefinition(
        f"companion.person.{world_id.removeprefix('world.')}.{key}",
        world_id,
        location_id,
        name,
        description,
        role,
        multipliers,
        f"enemy.behavior.{core}",
        f"enemy.behavior.{trait}",
        RARE_QUALITY_ID,
        dict(zip(aptitude_ids, aptitudes)),
        dict(gifts),
    )


CULTIVATION_COMPANIONS = (
    _species("qingluan", TAIXUAN_WORLD_ID, "青鸾", "栖于云海灵木的青羽神鸟。", "swift", _attributes(0.82, 1.05, 1.08, 0.78, 1.18), "rapid_attack", ("follow_up", "evasion", "burn"), 90),
    _species("xuangui", TAIXUAN_WORLD_ID, "玄龟", "背负玄纹、寿元悠长的水泽灵兽。", "guardian", _attributes(1.30, 1.00, 0.72, 1.35, 0.72), "block", ("shield", "taunt", "regeneration"), 110),
    _species("suanni", TAIXUAN_WORLD_ID, "狻猊", "喜烟好坐、声震山林的龙属异兽。", "assault", _attributes(1.05, 0.92, 1.22, 1.02, 0.96), "heavy_strike", ("burn", "sunder", "counter"), 75),
    _species("chenghuang", TAIXUAN_WORLD_ID, "乘黄", "背生双角、踏风越岭的古老瑞兽。", "swift", _attributes(0.88, 1.05, 0.98, 0.82, 1.30), "evasion", ("rapid_attack", "combo", "slow"), 105),
    _species("tianlu", TAIXUAN_WORLD_ID, "天禄", "辟邪纳福、守望灵脉的独角灵兽。", "guardian", _attributes(1.12, 1.08, 0.90, 1.18, 0.90), "shield", ("block", "counter", "death_guard"), 95),
    _species("jade_rabbit", TAIXUAN_WORLD_ID, "月宫玉兔", "饮月华而生、善辨灵药的白兔。", "sustain", _attributes(0.86, 1.28, 0.82, 0.80, 1.16), "regeneration", ("evasion", "slow", "sleep"), 125),
    _species("dangkang", TAIXUAN_WORLD_ID, "当康", "丰年将至时现身田野的有牙瑞兽。", "sustain", _attributes(1.18, 0.92, 0.94, 1.10, 0.88), "lifesteal", ("regeneration", "heavy_armor", "taunt"), 120),
    _species("mengji", TAIXUAN_WORLD_ID, "孟极", "身披白纹、善伏于山林阴影的异兽。", "control", _attributes(0.92, 1.02, 1.05, 0.84, 1.22), "freeze", ("evasion", "follow_up", "slow"), 100),
)

MAGIC_COMPANIONS = (
    _species("griffin", MAGIC_WORLD_ID, "星辉狮鹫", "翼羽映照星光的高山狮鹫。", "swift", _attributes(0.96, 0.92, 1.14, 0.88, 1.18), "follow_up", ("rapid_attack", "splash", "evasion"), 90),
    _species("unicorn", MAGIC_WORLD_ID, "银角独角兽", "能感知恶意并净化魔力乱流的圣洁生灵。", "sustain", _attributes(1.02, 1.25, 0.84, 0.96, 1.04), "regeneration", ("shield", "evasion", "counter"), 90),
    _species("phoenix_chick", MAGIC_WORLD_ID, "余烬雏凤", "从不灭余烬中孵化的幼年凤凰。", "assault", _attributes(0.88, 1.12, 1.18, 0.78, 1.12), "burn", ("death_guard", "area_attack", "charged_burst"), 65),
    _species("hellhound", MAGIC_WORLD_ID, "冥途猎犬", "巡游冥途边界、追逐灵魂气息的黑犬。", "assault", _attributes(1.02, 0.88, 1.16, 0.92, 1.08), "execute", ("bleed", "lifesteal", "follow_up"), 105),
    _species("wyvern", MAGIC_WORLD_ID, "翡翠翼蜥", "盘旋峡谷、吐出腐蚀毒雾的双足飞兽。", "control", _attributes(0.94, 1.06, 1.04, 0.88, 1.14), "poison", ("splash", "evasion", "slow"), 110),
    _species("flower_sprite", MAGIC_WORLD_ID, "晨露花精", "诞生于第一滴晨露中的微小自然精灵。", "sustain", _attributes(0.76, 1.35, 0.74, 0.72, 1.26), "sleep", ("regeneration", "evasion", "slow"), 130),
    _species("gargoyle", MAGIC_WORLD_ID, "符文石像鬼", "刻满守护符文、夜间苏醒的石翼造物。", "guardian", _attributes(1.22, 0.90, 0.84, 1.30, 0.78), "heavy_armor", ("block", "counter", "shield"), 115),
    _species("thunderbird", MAGIC_WORLD_ID, "苍穹雷鸟", "振翼时牵动雷云的远古巨鸟后裔。", "control", _attributes(0.90, 1.08, 1.12, 0.80, 1.22), "stun", ("area_attack", "rapid_attack", "volatile"), 85),
)

STELLAR_RING_COMPANIONS = (
    _species("rail_hound", STELLAR_RING_WORLD_ID, "磁轨猎犬", "沿维护轨道巡游、能锁定异常热源的合金猎犬。", "assault", _attributes(1.02, 0.86, 1.16, 0.94, 1.10), "follow_up", ("bleed", "execute", "rapid_attack"), 105),
    _species("crystal_falcon", STELLAR_RING_WORLD_ID, "晶翼巡隼", "以透明光翼穿越环城气流的高速侦察体。", "swift", _attributes(0.82, 1.04, 1.08, 0.76, 1.32), "rapid_attack", ("evasion", "piercing", "follow_up"), 90),
    _species("repair_wisp", STELLAR_RING_WORLD_ID, "维修浮灵", "古老维护协议孕育的浮游机械，会主动修补受损结构。", "sustain", _attributes(0.80, 1.34, 0.74, 0.86, 1.18), "regeneration", ("shield", "lifesteal", "counter"), 125),
    _species("pulse_beetle", STELLAR_RING_WORLD_ID, "脉冲甲虫", "背甲储存高压电荷，受惊时释放定向脉冲。", "control", _attributes(1.08, 1.06, 0.96, 1.18, 0.90), "stun", ("shield", "splash", "volatile"), 115),
    _species("quantum_fox", STELLAR_RING_WORLD_ID, "量子灵狐", "能在数个概率位置间短暂叠加的银灰灵兽。", "swift", _attributes(0.88, 1.12, 1.02, 0.78, 1.28), "evasion", ("combo", "counter", "cooldown_lock"), 80),
    _species("prism_jelly", STELLAR_RING_WORLD_ID, "折光水母", "漂浮于冷却海上空、以光谱变化交流的透明生物。", "control", _attributes(0.92, 1.28, 0.82, 0.90, 1.08), "slow", ("freeze", "area_attack", "shield"), 120),
    _species("rebuild_tortoise", STELLAR_RING_WORLD_ID, "重构玄龟", "甲壳内保存着失落的自修复工艺，行动缓慢而极难摧毁。", "guardian", _attributes(1.34, 0.94, 0.72, 1.36, 0.68), "heavy_armor", ("block", "regeneration", "death_guard"), 110),
    _species("entropy_drake", STELLAR_RING_WORLD_ID, "熵火幼龙", "从废热炉心孵化的幼体，以吞噬失控能量成长。", "assault", _attributes(0.94, 1.08, 1.24, 0.82, 1.06), "burn", ("charged_burst", "resource_drain", "sacrifice"), 65),
)

CULTIVATION_PEOPLE = (
    _person(
        "xie_tingyun", TAIXUAN_WORLD_ID, PERSON_WEST_LOCATION_ID,
        "谢停云", "曾为剑宗巡守，如今独居听雨庐，以剑意辨人心。", "swift",
        _attributes(0.92, 1.04, 1.10, 0.88, 1.18), "follow_up", "combo",
        (92, 112, 116, 80),
        ((REGION_TROPHY_ITEM_IDS[GREEN_CLOUD_PLAIN_ID][3], 20), (REGION_TROPHY_ITEM_IDS[SUNSET_RIDGE_ID][5], 35)),
    ),
    _person(
        "ning_suwen", TAIXUAN_WORLD_ID, PERSON_EAST_LOCATION_ID,
        "宁素问", "提灯行医的游方丹师，愿为守诺之人留下一盏灯。", "sustain",
        _attributes(1.02, 1.20, 0.82, 0.96, 1.02), "regeneration", "shield",
        (104, 82, 88, 126),
        ((REGION_TROPHY_ITEM_IDS[MIRROR_LAKE_MARSH_ID][1], 20), (REGION_TROPHY_ITEM_IDS[VERDANT_WILDERNESS_ID][4], 35)),
    ),
    _person(
        "pei_zhaoye", TAIXUAN_WORLD_ID, PERSON_NORTH_LOCATION_ID,
        "裴照夜", "守望星轨的阵师，试图从天象中寻找诸界裂隙的规律。", "control",
        _attributes(0.94, 1.16, 0.96, 0.90, 1.10), "slow", "charged_burst",
        (94, 104, 98, 104),
        ((REGION_TROPHY_ITEM_IDS[BLACK_WIND_RAVINE_ID][4], 20), (REGION_TROPHY_ITEM_IDS[SCARLET_FLAME_VALLEY_ID][5], 35)),
    ),
)

MAGIC_PEOPLE = (
    _person(
        "elin_veis", MAGIC_WORLD_ID, PERSON_WEST_LOCATION_ID,
        "伊琳·维斯", "守着雾灯研究灵魂回响的年轻术士，不轻易接受同行者。", "sustain",
        _attributes(0.94, 1.18, 0.86, 0.98, 1.04), "shield", "regeneration",
        (96, 84, 92, 128),
        ((REGION_TROPHY_ITEM_IDS[GREEN_CLOUD_PLAIN_ID][2], 20), (REGION_TROPHY_ITEM_IDS[MIRROR_LAKE_MARSH_ID][5], 35)),
    ),
    _person(
        "roland_hess", MAGIC_WORLD_ID, PERSON_EAST_LOCATION_ID,
        "罗兰·赫斯", "卸甲后仍看守旧驿道的骑士，坚持记录每一位过客的去向。", "guardian",
        _attributes(1.18, 0.90, 0.92, 1.22, 0.86), "block", "counter",
        (124, 92, 84, 100),
        ((REGION_TROPHY_ITEM_IDS[SUNSET_RIDGE_ID][2], 20), (REGION_TROPHY_ITEM_IDS[SCARLET_FLAME_VALLEY_ID][4], 35)),
    ),
    _person(
        "seraphina", MAGIC_WORLD_ID, PERSON_NORTH_LOCATION_ID,
        "塞拉菲娜", "追踪界海星潮的占星师，能以星辉扰乱敌人的行动。", "control",
        _attributes(0.90, 1.22, 1.00, 0.86, 1.12), "stun", "area_attack",
        (88, 108, 104, 100),
        ((REGION_TROPHY_ITEM_IDS[BLACK_WIND_RAVINE_ID][3], 20), (REGION_TROPHY_ITEM_IDS[VERDANT_WILDERNESS_ID][5], 35)),
    ),
)

STELLAR_RING_PEOPLE = (
    _person(
        "heya", STELLAR_RING_WORLD_ID, PERSON_WEST_LOCATION_ID,
        "赫娅", "守在第七码头的遗迹领航员，能从失效航标中读出旧时代的归途。", "swift",
        _attributes(0.90, 1.10, 1.06, 0.84, 1.24), "follow_up", "evasion",
        (88, 106, 122, 84),
        ((REGION_TROPHY_ITEM_IDS[GREEN_CLOUD_PLAIN_ID][4], 20), (REGION_TROPHY_ITEM_IDS[THUNDER_MARSH_STEPPE_ID][5], 35)),
    ),
    _person(
        "ino_karl", STELLAR_RING_WORLD_ID, PERSON_EAST_LOCATION_ID,
        "伊诺·卡尔", "离开中枢议会的结构工程师，仍在独自修复无人承认存在的第十三环。", "guardian",
        _attributes(1.16, 1.02, 0.88, 1.24, 0.84), "shield", "block",
        (120, 86, 82, 112),
        ((REGION_TROPHY_ITEM_IDS[BROKEN_PILLAR_RELIC_ID][3], 20), (REGION_TROPHY_ITEM_IDS[HEAVENLY_CRAFT_RELIC_ID][5], 35)),
    ),
    _person(
        "zero_string", STELLAR_RING_WORLD_ID, PERSON_NORTH_LOCATION_ID,
        "零弦", "失去大半记忆的观测员，以一串从未重复的脉冲记录人造恒星的梦。", "control",
        _attributes(0.88, 1.26, 0.96, 0.82, 1.16), "cooldown_lock", "mark_detonation",
        (84, 102, 108, 106),
        ((REGION_TROPHY_ITEM_IDS[KUNLUN_SKY_RUINS_ID][2], 20), (REGION_TROPHY_ITEM_IDS[RETURNING_RUIN_ABYSS_ID][4], 35)),
    ),
)

COMPANION_BALANCE = CompanionBalance(
    roster_capacity=30,
    quality_weights={
        COMMON_QUALITY_ID: 550,
        FINE_QUALITY_ID: 280,
        RARE_QUALITY_ID: 120,
        EPIC_QUALITY_ID: 40,
        LEGENDARY_QUALITY_ID: 10,
    },
    aptitude_budgets={
        COMMON_QUALITY_ID: 360,
        FINE_QUALITY_ID: 380,
        RARE_QUALITY_ID: 400,
        EPIC_QUALITY_ID: 420,
        LEGENDARY_QUALITY_ID: 440,
    },
)

COMPANION_EXPERIENCE_REQUIREMENTS = tuple(
    80 + 3 * level * level
    for level in range(1, 100)
)

COMPANION_GROWTH = CompanionGrowthDefinition(
    experience_requirements=COMPANION_EXPERIENCE_REQUIREMENTS,
    base_attributes=_attributes(60, 80, 4, 0, 100),
    per_level_attributes=_attributes(6, 1, 0.55, 0.2, 0),
    exploration_multipliers={"normal": 2.5, "elite": 8, "boss": 40},
    party_boss_multiplier=60,
    disaster_damage_tiers=((0.0, 10), (0.001, 20), (0.005, 40)),
)

CULTIVATION_COMPANION_SANCTUARY = CompanionSanctuaryDefinition(
    "companion_sanctuary.cultivation",
    TAIXUAN_WORLD_ID,
    "万灵秘境",
    "隐于太玄界灵脉夹层中的古老生灵栖地。",
    tuple(value.id for value in CULTIVATION_COMPANIONS),
)
MAGIC_COMPANION_SANCTUARY = CompanionSanctuaryDefinition(
    "companion_sanctuary.magic",
    MAGIC_WORLD_ID,
    "幻兽庭",
    "漂流在魔力潮汐间、收容异界生灵的隐秘庭域。",
    tuple(value.id for value in MAGIC_COMPANIONS),
)
STELLAR_RING_COMPANION_SANCTUARY = CompanionSanctuaryDefinition(
    "companion_sanctuary.stellar_ring",
    STELLAR_RING_WORLD_ID,
    "回声育成舱",
    "被遗忘的生态舱层，古代造物与适应环城环境的生灵在此繁衍。",
    tuple(value.id for value in STELLAR_RING_COMPANIONS),
)

COMPANION_CATALOG = CompanionCatalog(
    (*CULTIVATION_COMPANIONS, *MAGIC_COMPANIONS, *STELLAR_RING_COMPANIONS),
    (
        CULTIVATION_COMPANION_SANCTUARY,
        MAGIC_COMPANION_SANCTUARY,
        STELLAR_RING_COMPANION_SANCTUARY,
    ),
    COMPANION_BALANCE,
    COMPANION_GROWTH,
    (*CULTIVATION_PEOPLE, *MAGIC_PEOPLE, *STELLAR_RING_PEOPLE),
)


__all__ = [name for name in globals() if not name.startswith("_")]
