"""正式业务 Manifest；登记已落地能力及其启动期扩展点。"""

from dataclasses import dataclass

from .breakthrough.codec import breakthrough_codec_registrations
from .companion.codec import companion_codec_registrations
from .dimensional_disaster.codec import dimensional_disaster_codec_registrations
from .draw.codec import draw_codec_registrations
from .economy.codec import economy_codec_registrations
from .equipment_blueprint.codec import equipment_blueprint_codec_registrations
from .exchange.codec import covenant_exchange_codec_registrations
from .exploration.codec import exploration_codec_registrations
from .lottery.codec import lottery_codec_registrations
from .party_battle.codec import party_battle_codec_registrations
from .rest.codec import rest_codec_registrations
from .special_items.codec import special_item_codec_registrations
from .world_lore.codec import world_lore_codec_registrations
from .world_progress.codec import world_progress_codec_registrations


SnapshotCodecRegistration = tuple[str, type[object]]


@dataclass(frozen=True)
class FeatureManifest:
    id: str
    package: str
    responsibility: str
    command_packages: tuple[str, ...] = ()
    scheduled_jobs: tuple[str, ...] = ()
    # Listed command packages are owned by this feature unless explicitly marked as integrated.
    integrated_command_packages: tuple[str, ...] = ()
    snapshot_codecs: tuple[SnapshotCodecRegistration, ...] = ()

    def __post_init__(self) -> None:
        if not self.id.isascii() or not self.id.strip():
            raise ValueError("业务 ID 必须是非空 ASCII 标识")
        if not self.package.isascii() or not self.package.strip():
            raise ValueError("业务包名必须是非空 ASCII 标识")
        if not self.responsibility.strip():
            raise ValueError("业务必须声明单一主要职责")
        if len(set(self.command_packages)) != len(self.command_packages):
            raise ValueError(f"业务 {self.id} 重复登记命令组件")
        if len(set(self.scheduled_jobs)) != len(self.scheduled_jobs):
            raise ValueError(f"业务 {self.id} 重复登记定时任务")
        if not set(self.integrated_command_packages).issubset(self.command_packages):
            raise ValueError(f"业务 {self.id} 登记了未参与的协作命令组件")
        codec_ids = tuple(value[0] for value in self.snapshot_codecs)
        if len(set(codec_ids)) != len(codec_ids):
            raise ValueError(f"业务 {self.id} 重复登记快照 codec")
        for type_id, value_type in self.snapshot_codecs:
            if not type_id.isascii() or not type_id.strip():
                raise ValueError(f"业务 {self.id} 的快照类型 ID 必须是非空 ASCII 标识")
            if not isinstance(value_type, type):
                raise TypeError(f"业务 {self.id} 的快照 codec 必须登记具体类型")


ACTIVE_FEATURE_MANIFESTS = (
    FeatureManifest(
        "covenant_exchange",
        "exchange",
        "原子消费定相尘并按固定目录发放套装图纸",
        ("归航兑换",),
        snapshot_codecs=covenant_exchange_codec_registrations(),
    ),
    FeatureManifest(
        "equipment_blueprint",
        "equipment_blueprint",
        "原子消费套装图纸并生成仅固定套装身份的随机装备",
        ("物品",),
        integrated_command_packages=("物品",),
        snapshot_codecs=equipment_blueprint_codec_registrations(),
    ),
    FeatureManifest(
        "build_trial",
        "build_trial",
        "读取当前构筑执行固定种子无损战斗，并保存公开战报",
        ("构筑试炼",),
    ),
    FeatureManifest(
        "battle_report",
        "battle_report",
        "保存、公开读取和清理跨战斗模式共用的战报",
        ("战报",),
    ),
    FeatureManifest(
        "data_lifecycle",
        "data_lifecycle",
        "统一执行各领域登记的短期数据清理并维护正式数据库备份",
        ("数据维护", "数据库备份"),
        scheduled_jobs=(
            "game_data_lifecycle_cleanup",
            "wanxiang_xingji_database_backup",
        ),
    ),
    FeatureManifest(
        "companion",
        "companion",
        "协调宠物捕获、人物结交、通用名册、配装独占与告别",
        ("伙伴",),
        snapshot_codecs=companion_codec_registrations(),
    ),
    FeatureManifest(
        "dimension_shift",
        "dimension_shift",
        "原子扣除跃迁凭证、切换真实世界并迁移存在体空间",
        ("跃迁",),
    ),
    FeatureManifest(
        "world_travel",
        "world_travel",
        "统一校验世界地点意图、主要行动占用与角色位置移动",
        ("地图", "探险", "伙伴"),
        integrated_command_packages=("探险", "伙伴"),
    ),
    FeatureManifest(
        "breakthrough",
        "breakthrough",
        "原子消费破境凭证、解锁成长关隘、结算经验并恢复角色资源",
        ("突破",),
        snapshot_codecs=breakthrough_codec_registrations(),
    ),
    FeatureManifest(
        "dimensional_disaster",
        "dimensional_disaster",
        "协调全服灾厄战斗、贡献、周期和唯一遗羽结算",
        ("跨界灾厄",),
        ("game_dimensional_disaster_maintenance",),
        snapshot_codecs=dimensional_disaster_codec_registrations(),
    ),
    FeatureManifest(
        "draw",
        "draw",
        "扣除抽奖签、推进保底并原子发放奖项",
        ("抽奖",),
        snapshot_codecs=draw_codec_registrations(),
    ),
    FeatureManifest(
        "economy",
        "economy",
        "统一回收、二手交易、估价与中央税金结算",
        ("回收", "二手"),
        ("game_market_expiration",),
        snapshot_codecs=economy_codec_registrations(),
    ),
    FeatureManifest(
        "exploration",
        "exploration",
        "协调持续探险、战斗、掉落与奖励联合结算",
        ("探险",),
        ("game_exploration_settlement",),
        snapshot_codecs=exploration_codec_registrations(),
    ),
    FeatureManifest(
        "world_progress",
        "world_progress",
        "消费探险胜利事实，累计世界区域行纪、发放阶段奖励并维护永久排行",
        ("行纪",),
        snapshot_codecs=world_progress_codec_registrations(),
    ),
    FeatureManifest(
        "world_lore",
        "world_lore",
        "读取世界总行纪进度解锁世界记录，并保存成功阅读的记录",
        ("世界志",),
        snapshot_codecs=world_lore_codec_registrations(),
    ),
    FeatureManifest(
        "lottery",
        "lottery",
        "处理单期购票、环形开奖、退票与中奖入账",
        ("彩票",),
        ("game_lottery_draw",),
        snapshot_codecs=lottery_codec_registrations(),
    ),
    FeatureManifest(
        "party",
        "party",
        "协调三人队伍、社会邀请、成员关系、队长、站位与准备状态",
        ("组队",),
    ),
    FeatureManifest(
        "party_battle",
        "party_battle",
        "协调跨界组队首领、准备指纹、临时战斗投影、原子奖励与公开战报",
        ("组队",),
        integrated_command_packages=("组队",),
        snapshot_codecs=party_battle_codec_registrations(),
    ),
    FeatureManifest(
        "party_sparring",
        "party_sparring",
        "协调队长请求、双方当前阵容无损对战和公开战报",
        ("组队",),
        integrated_command_packages=("组队",),
    ),
    FeatureManifest(
        "player",
        "player",
        "提供账号到角色入口、角色总览、个人设置、提醒和活动读模型",
        ("角色", "提醒", "活动"),
    ),
    FeatureManifest(
        "rest",
        "rest",
        "协调主行动占用、离线恢复和主动结束休息",
        ("休息",),
        ("game_rest_settlement",),
        snapshot_codecs=rest_codec_registrations(),
    ),
    FeatureManifest(
        "sparring",
        "sparring",
        "协调切磋邀请、双方真实配装战斗和公开战报",
        ("切磋",),
    ),
    FeatureManifest(
        "special_items",
        "special_items",
        "原子提交需要长期状态的特殊物品效果",
        ("物品",),
        snapshot_codecs=special_item_codec_registrations(),
    ),
)


def feature_snapshot_codec_registrations() -> tuple[SnapshotCodecRegistration, ...]:
    registrations: list[SnapshotCodecRegistration] = []
    owners: dict[str, str] = {}
    for feature in ACTIVE_FEATURE_MANIFESTS:
        for registration in feature.snapshot_codecs:
            type_id = registration[0]
            previous = owners.setdefault(type_id, feature.id)
            if previous != feature.id:
                raise ValueError(
                    f"快照 codec {type_id} 同时属于业务 {previous} 与 {feature.id}"
                )
            registrations.append(registration)
    return tuple(registrations)


__all__ = [
    "ACTIVE_FEATURE_MANIFESTS",
    "FeatureManifest",
    "SnapshotCodecRegistration",
    "feature_snapshot_codec_registrations",
]
