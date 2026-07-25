"""创建角色命令的本地驱动端到端测试。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import inspect
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import (  # noqa: E402
    PlayerReplyState,
    build_game_services,
    install_game_services,
    restore_game_services,
)
from game.content import (  # noqa: E402
    CHARACTER_LEVEL_PROGRESSION_ID,
    STARTER_WEAPON_ID,
    STARTING_CITY_ID,
)
from game.core.persistence import CHARACTER_AGGREGATE  # noqa: E402
from game.core.gameplay import (  # noqa: E402
    ActivityInstance,
    ActivityStatus,
    NotificationEntry,
)
from game.rules.activity import (  # noqa: E402
    GlobalActivityRegistration,
    GlobalActivityView,
)
from game.cmd import 角色 as character_component  # noqa: E402
from game.cmd import 活动 as activity_component  # noqa: E402,F401
from game.cmd import 提醒 as reminder_component  # noqa: E402,F401
from game.cmd.command import GameCommand  # noqa: E402
from game.cmd.dependencies import current_character_overview  # noqa: E402
from game.cmd.reply import GameReplyComposer, send_game_reply  # noqa: E402
from game.cmd.reply_intents import (  # noqa: E402
    NOTIFICATION_READ_INTENT,
    ReplyIntentRegistry,
    reply_intents,
)
from game.cmd.角色.service import _number  # noqa: E402
from launch.adapter import Depends  # noqa: E402
from launch.adapter.local import LocalEventHandler, dispatch  # noqa: E402
from launch.adapter.qq import QqEventHandler  # noqa: E402
from message import M, RenderedMessage  # noqa: E402
from message.renderers.markdown import render_markdown  # noqa: E402
from launch.adapter.qq.render import render_qq_message  # noqa: E402


CREATE_COMMAND = "创建角色"
PROFILE_COMMAND = "我的角色"
COMBAT_PANEL_COMMAND = "战斗面板"
MOOD_COMMAND = "心情"
AUTO_MEDICINE_COMMAND = "自动用药"
PROTECTED_COMMAND = "角色守卫测试"
NOTIFICATION_COMMAND = "notifications"
PENDING_COMMAND = "pending_actions"
WORLD_EVENTS_COMMAND = "world_events"


@GameCommand.handler(cmd=PROTECTED_COMMAND, hidden=True)
async def protected_command() -> None:
    await send_game_reply(
        M.document().section("角色守卫", icon="status").line("已放行").build()
    )


def main() -> None:
    asyncio.run(_main())
    print("character command tests passed")


async def _main() -> None:
    assert _number(55.448) == "55.45"
    assert _number(40.0) == "40"
    assert tuple(inspect.signature(character_component.create_character).parameters) == (
        "message",
    )
    assert tuple(inspect.signature(character_component.view_character).parameters) == ("overview",)
    overview_parameter = inspect.signature(character_component.view_character).parameters[
        "overview"
    ]
    assert isinstance(overview_parameter.default, Depends)
    assert overview_parameter.default.dependency is current_character_overview
    assert tuple(inspect.signature(character_component.view_combat_panel).parameters) == (
        "overview",
    )
    assert len(LocalEventHandler.exact_rules[CREATE_COMMAND]) == 1
    assert len(QqEventHandler.exact_rules[CREATE_COMMAND]) == 1
    assert len(LocalEventHandler.exact_rules[PROFILE_COMMAND]) == 1
    assert len(QqEventHandler.exact_rules[PROFILE_COMMAND]) == 1
    assert len(LocalEventHandler.exact_rules[COMBAT_PANEL_COMMAND]) == 1
    assert len(QqEventHandler.exact_rules[COMBAT_PANEL_COMMAND]) == 1
    assert len(LocalEventHandler.exact_rules[MOOD_COMMAND]) == 1
    assert len(QqEventHandler.exact_rules[MOOD_COMMAND]) == 1
    assert len(LocalEventHandler.exact_rules[AUTO_MEDICINE_COMMAND]) == 1
    assert len(QqEventHandler.exact_rules[AUTO_MEDICINE_COMMAND]) == 1
    assert len(LocalEventHandler.exact_rules[PROTECTED_COMMAND]) == 1
    assert len(QqEventHandler.exact_rules[PROTECTED_COMMAND]) == 1
    assert len(LocalEventHandler.exact_rules[NOTIFICATION_COMMAND]) == 1
    assert len(QqEventHandler.exact_rules[NOTIFICATION_COMMAND]) == 1
    assert len(LocalEventHandler.exact_rules[PENDING_COMMAND]) == 1
    assert len(QqEventHandler.exact_rules[PENDING_COMMAND]) == 1
    assert len(LocalEventHandler.exact_rules[WORLD_EVENTS_COMMAND]) == 1
    assert len(QqEventHandler.exact_rules[WORLD_EVENTS_COMMAND]) == 1
    assert LocalEventHandler.exact_rules[CREATE_COMMAND][0].priority == 100
    assert LocalEventHandler.exact_rules[CREATE_COMMAND][0].block
    assert LocalEventHandler.exact_rules[CREATE_COMMAND][0].metadata == {
        "game": {"access": "public"}
    }
    assert LocalEventHandler.exact_rules[PROFILE_COMMAND][0].metadata == {
        "game": {"access": "player"}
    }
    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "character-command.db",
            identity_secret="character-command-test-secret",
        )
        services.database.initialize()
        assert services.exploration.settlement.battles.player_lineup is services.player_lineup
        assert services.dimensional_disasters.battles.player_lineup is services.player_lineup
        previous = install_game_services(services)
        try:
            await LocalEventHandler.run()

            blocked = await dispatch(
                client_id="local-user-guarded",
                raw_message=PROTECTED_COMMAND,
                sender_name="未建档用户",
                event_id="local-guard-blocked",
            )
            blocked_content = _content(blocked)
            assert blocked_content == (
                "**万象行纪**\n"
                "> 🌏 界门登录\n"
                "> > 行纪中尚未发现你的化身记录。\n"
                "> \n"
                "> 建立唯一化身，从第一个世界开始写下行纪。\n"
                "> \n"
                "> 发送: 创建角色 名称"
            )
            assert blocked.replies[0].message.actions[0].behavior == "fill"
            assert _character_count(services) == 0

            created = await dispatch(
                client_id="local-user-a",
                raw_message=f"{CREATE_COMMAND} 云舟客",
                sender_name="平台昵称甲",
                event_id="local-create-a",
            )
            content = _content(created)
            assert content.splitlines()[0] == "**未入道 云舟客 Lv1**"
            assert "未入道 云舟客 Lv1" in content
            assert "云舟客 Lv1" in content
            assert "人族" in content and "凡体" in content
            assert "黄品·仙京制式剑" in content
            assert "小还丹" in content and "小回灵丹" in content
            assert "太玄仙城" in content
            assert _character_count(services) == 1

            allowed = await dispatch(
                client_id="local-user-a",
                raw_message=PROTECTED_COMMAND,
                sender_name="平台昵称甲",
                event_id="local-guard-allowed",
            )
            assert "角色守卫" in _content(allowed)
            assert "已放行" in _content(allowed)

            mood_status = await dispatch(
                client_id="local-user-a",
                raw_message=MOOD_COMMAND,
                sender_name="平台昵称甲",
                event_id="local-mood-status",
            )
            assert mood_status.replies[0].message.content.splitlines()[0] == (
                "**未入道 云舟客 Lv1**"
            )
            assert "当前状态: _关闭_" in _content(mood_status)

            mood_enabled = await dispatch(
                client_id="local-user-a",
                raw_message=f"{MOOD_COMMAND} 开启",
                sender_name="平台昵称甲",
                event_id="local-mood-enable",
            )
            assert mood_enabled.replies[0].message.content.startswith(r"$\textcolor{#")
            assert "当前状态: _开启_" in _content(mood_enabled)
            character_id = _character_ids(services)[0]
            settings = services.load_character_settings(character_id)
            assert settings.mood_header_enabled and settings.revision == 1

            auto_medicine = await dispatch(
                client_id="local-user-a",
                raw_message=f"{AUTO_MEDICINE_COMMAND} 关闭",
                sender_name="平台昵称甲",
                event_id="local-auto-medicine-disable",
            )
            assert "当前状态: _关闭_" in _content(auto_medicine)
            settings = services.load_character_settings(character_id)
            assert not settings.auto_use_medicine and settings.revision == 2

            existing_with_mood = await dispatch(
                client_id="local-user-a",
                raw_message=f"{CREATE_COMMAND} 第二角色",
                sender_name="平台昵称甲",
                event_id="local-create-a-with-mood",
            )
            assert existing_with_mood.replies[0].message.content.startswith(
                r"$\textcolor{#"
            )
            assert "角色已存在" in _content(existing_with_mood)

            character = services.characters.load_character(character_id)
            assert character is not None
            overview_result = services.load_character_overview(character)
            assert overview_result.overview is not None
            dimension = overview_result.overview.character_world
            world_view = services.world_view(dimension)
            notification_time = datetime.now(ZoneInfo("Asia/Shanghai"))
            services.notifications.issue(
                NotificationEntry(
                    "notification-character-command",
                    character.account_id,
                    "notification.test",
                    "character-command:test",
                    100,
                    1,
                    notification_time,
                )
            )
            assert services.notifications.count_unread(
                character.account_id,
                logical_time=notification_time,
            ) == 1
            composer = GameReplyComposer(services.content.projector)
            activity_spotlights = (
                GlobalActivityView(
                    ActivityInstance(
                        "event-city",
                        STARTING_CITY_ID,
                        1,
                        notification_time - timedelta(hours=1),
                        notification_time + timedelta(hours=2),
                        status=ActivityStatus.OPEN,
                    ),
                    GlobalActivityRegistration(STARTING_CITY_ID),
                ),
                GlobalActivityView(
                    ActivityInstance(
                        "event-weapon",
                        STARTER_WEAPON_ID,
                        1,
                        notification_time - timedelta(hours=1),
                        notification_time + timedelta(hours=3),
                        status=ActivityStatus.OPEN,
                    ),
                    GlobalActivityRegistration(STARTER_WEAPON_ID),
                ),
            )
            composed = composer.compose(
                M.document()
                .header("组件标题")
                .section("正文", icon="status")
                .line("内容")
                .build(),
                PlayerReplyState(
                    character,
                    settings,
                    dimension,
                    activity_spotlights=activity_spotlights,
                    additional_activity_count=2,
                    unread_notification_count=2,
                    pending_action_count=3,
                ),
                logical_time=notification_time,
            )
            composed_lines = render_markdown(composed.document).splitlines()
            assert composed_lines[0].startswith(r"$\textcolor{#")
            assert composed_lines[1] == (
                "> ✨ 活动: 太玄仙城&nbsp;|&nbsp;仙京制式剑&nbsp;|&nbsp;+2"
            )
            assert composed_lines[2] == (
                "> 📌 提醒: 3 项待领取&nbsp;|&nbsp;2 条未读通知"
            )
            assert "组件标题" not in composed_lines[0]
            qq_content = render_qq_message(composed)["content"]
            assert qq_content.count("mqqapi://aio/inlinecmd") == 5
            assert "command=world_events%20event-city" in qq_content
            assert "command=world_events%20event-weapon" in qq_content
            assert "command=world_events&" in qq_content
            assert "command=pending_actions" in qq_content
            assert "command=notifications" in qq_content
            plain_intents = ReplyIntentRegistry()
            plain_composed = GameReplyComposer(
                services.content.projector,
                plain_intents,
            ).compose(
                M.document().section("正文", icon="status").line("内容").build(),
                    PlayerReplyState(
                        character,
                        settings,
                        dimension,
                        activity_spotlights=activity_spotlights,
                        additional_activity_count=2,
                        unread_notification_count=2,
                    pending_action_count=3,
                ),
                logical_time=notification_time,
            )
            assert "mqqapi://" not in render_qq_message(plain_composed)["content"]
            payload_intents = ReplyIntentRegistry()
            payload_intents.register(
                "notification.open_test",
                lambda payload: f"通知详情 {payload['notification_id']}",
            )
            payload_link = payload_intents.link(
                "处理",
                "notification.open_test",
                {"notification_id": "notice-1"},
            )
            assert payload_link.command == "通知详情 notice-1"
            for invalid_body in (
                M.document().inline_section("提醒", "组件手写通栏").build(),
                M.document().header("组件彩色头", color="#1ABC9C").build(),
            ):
                try:
                    composer.compose(
                        invalid_body,
                        PlayerReplyState(character, settings, dimension),
                        logical_time=notification_time,
                    )
                    raise AssertionError("组件不能手写全局通栏或彩色人物头")
                except ValueError:
                    pass

            profile = await dispatch(
                client_id="local-user-a",
                raw_message=PROFILE_COMMAND,
                sender_name="平台昵称甲",
                event_id="local-profile-a",
            )
            profile_content = _content(profile)
            assert profile_content.startswith(r"$\textcolor{#")
            assert profile_content.splitlines()[1] == "> 📌 提醒: 1 条未读通知"
            assert services.notifications.count_unread(
                character.account_id,
                logical_time=notification_time,
            ) == 1

            notification_list = await dispatch(
                client_id="local-user-a",
                raw_message=NOTIFICATION_COMMAND,
                sender_name="平台昵称甲",
                event_id="local-notification-list",
            )
            notification_content = _content(notification_list)
            assert "未读通知" in notification_content
            assert "系统通知" in notification_content
            assert services.notifications.count_unread(
                character.account_id,
                logical_time=notification_time,
            ) == 1
            read_intent = reply_intents.definition(NOTIFICATION_READ_INTENT)
            assert read_intent is not None
            read_command = read_intent.command(
                {
                    "notification_id": "notification-character-command",
                    "revision": 0,
                }
            )
            marked_read = await dispatch(
                client_id="local-user-a",
                raw_message=read_command,
                sender_name="平台昵称甲",
                event_id="local-notification-read",
            )
            assert "已标记为已读" in _content(marked_read)
            assert services.notifications.count_unread(
                character.account_id,
                logical_time=datetime.now(ZoneInfo("Asia/Shanghai")),
            ) == 0

            pending_list = await dispatch(
                client_id="local-user-a",
                raw_message=PENDING_COMMAND,
                sender_name="平台昵称甲",
                event_id="local-pending-list",
            )
            assert "暂无待领取行动" in _content(pending_list)

            activity_list = await dispatch(
                client_id="local-user-a",
                raw_message=WORLD_EVENTS_COMMAND,
                sender_name="平台昵称甲",
                event_id="local-world-events-list",
            )
            assert "当前没有开放的活动" in _content(activity_list)

            activity_detail = await dispatch(
                client_id="local-user-a",
                raw_message=f"{WORLD_EVENTS_COMMAND} missing-event",
                sender_name="平台昵称甲",
                event_id="local-world-events-detail",
            )
            assert "活动不存在、尚未开放或已经结束" in _content(activity_detail)
            profile_plain = _plain(profile_content)
            assert "云舟客 Lv1" in profile_plain
            assert (
                f"{world_view.projector.name(CHARACTER_LEVEL_PROGRESSION_ID)}: 未入道"
                in profile_plain
            )
            assert "经验: 0/" in profile_plain
            assert "气血: 100/100" in profile_plain
            assert "灵力: 100/100" in profile_plain
            assert "黄品·仙京制式剑 | Lv1" in profile_plain
            for slot_name in ("头部", "身体", "手部", "腰部", "足部", "饰品"):
                assert f"{slot_name}: 未装备" in profile_plain
            assert "基础属性" not in profile_plain
            assert "攻击:" not in profile_plain
            assert "防御:" not in profile_plain
            assert "速度:" not in profile_plain
            assert "太玄仙城" in profile_plain
            assert "灵石: 100" in profile_plain
            assert "行动: 空闲" in profile_plain
            assert profile.replies[0].message.actions[0].data == COMBAT_PANEL_COMMAND

            combat_panel = await dispatch(
                client_id="local-user-a",
                raw_message=COMBAT_PANEL_COMMAND,
                sender_name="平台昵称甲",
                event_id="local-combat-panel-a",
            )
            combat_plain = _plain(_content(combat_panel))
            assert "战斗面板" in combat_plain
            assert "当前配装: 0" in combat_plain
            assert "气血上限: 100" in combat_plain
            assert "灵力上限: 100" in combat_plain
            assert "攻击: 12" in combat_plain
            assert "防御: 0" in combat_plain
            assert "速度: 100" in combat_plain
            assert "命中修正: 0%" in combat_plain
            assert "暴击: 0%" in combat_plain
            assert "承伤修正: 0%" in combat_plain
            for label in (
                "闪避",
                "暴击增伤",
                "格挡",
                "格挡减伤",
                "伤害修正",
                "固定穿透",
                "比例穿透",
                "治疗修正",
                "受疗修正",
                "控制修正",
                "控制抵抗",
                "韧性",
            ):
                assert f"{label}:" in combat_plain
            assert "基础攻击" in combat_plain and "破势" in combat_plain
            assert "特效: 无" in combat_plain
            assert "套装: 无" in combat_plain

            mood_disabled = await dispatch(
                client_id="local-user-a",
                raw_message=f"{MOOD_COMMAND} 关闭",
                sender_name="平台昵称甲",
                event_id="local-mood-disable",
            )
            assert mood_disabled.replies[0].message.content.splitlines()[0] == (
                "**未入道 云舟客 Lv1**"
            )
            settings = services.load_character_settings(character_id)
            assert not settings.mood_header_enabled and settings.revision == 3

            replayed = await dispatch(
                client_id="local-user-a",
                raw_message=f"{CREATE_COMMAND} 云舟客",
                sender_name="平台昵称甲",
                event_id="local-create-a",
            )
            assert "云舟客 Lv1" in _content(replayed)
            assert _character_count(services) == 1

            existing = await dispatch(
                client_id="local-user-a",
                raw_message=f"{CREATE_COMMAND} 第二角色",
                sender_name="平台昵称甲",
                event_id="local-create-a-again",
            )
            assert "角色已存在" in _content(existing)
            assert _character_count(services) == 1

            nickname = await dispatch(
                client_id="local-user-b",
                raw_message=CREATE_COMMAND,
                sender_name="平台昵称乙",
                event_id="local-create-b",
            )
            assert "平台昵称乙 Lv1" in _content(nickname)
            assert _character_count(services) == 2

            missing = await dispatch(
                client_id="local-user-c",
                raw_message=CREATE_COMMAND,
                sender_name="",
                event_id="local-create-c",
            )
            missing_content = _content(missing)
            assert "需要角色名" in missing_content
            assert "创建角色 名称" in missing_content
            assert missing.replies[0].message.actions[0].behavior == "fill"
            assert _character_count(services) == 2

            invalid_name = await dispatch(
                client_id="local-user-d",
                raw_message=f"{CREATE_COMMAND} 七个汉字角色名",
                sender_name="平台昵称丁",
                event_id="local-create-d",
            )
            invalid_content = _content(invalid_name)
            assert "名称不可用" in invalid_content
            assert "显示宽度不能超过 12" in invalid_content
            assert invalid_name.replies[0].message.actions[0].behavior == "fill"
            assert _character_count(services) == 2

            not_created = await dispatch(
                client_id="local-user-c",
                raw_message=PROFILE_COMMAND,
                sender_name="",
                event_id="local-profile-c",
            )
            assert _content(not_created) == (
                "**万象行纪**\n"
                "> 🌏 界门登录\n"
                "> > 行纪中尚未发现你的化身记录。\n"
                "> \n"
                "> 建立唯一化身，从第一个世界开始写下行纪。\n"
                "> \n"
                "> 发送: 创建角色 名称"
            )
            assert _character_count(services) == 2
        finally:
            restore_game_services(previous)


def _content(result) -> str:
    assert result.matched and result.matched_count == 1
    assert len(result.replies) == 1
    message = result.replies[0].message
    assert isinstance(message, RenderedMessage)
    assert message.kind == "markdown"
    return message.content


def _character_count(services) -> int:
    return len(_character_ids(services))


def _character_ids(services) -> tuple[str, ...]:
    with services.database.unit_of_work(write=False) as uow:
        rows = uow.connection.execute(
            "SELECT aggregate_id FROM aggregate_snapshot WHERE aggregate_kind = ? "
            "ORDER BY aggregate_id",
            (CHARACTER_AGGREGATE,),
        ).fetchall()
        return tuple(str(row[0]) for row in rows)


def _plain(content: str) -> str:
    return content.replace("_", "").replace("&nbsp;", " ")


if __name__ == "__main__":
    main()
