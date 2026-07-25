"""队伍命令通过本地驱动器完成邀请与成员管理闭环。"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services, install_game_services, restore_game_services  # noqa: E402
from game.cmd import 组队 as party_component  # noqa: E402,F401
from game.cmd import 角色 as character_component  # noqa: E402,F401
from launch.adapter.local import LocalEventHandler, dispatch  # noqa: E402
from launch.adapter.qq import QqEventHandler  # noqa: E402


def main() -> None:
    asyncio.run(_main())
    print("party command tests passed")


async def _main() -> None:
    commands = (
        "组队",
        "创建队伍",
        "邀请组队",
        "接受组队",
        "拒绝组队",
        "退出队伍",
        "请离队伍",
        "转让队长",
        "解散队伍",
        "准备",
        "取消准备",
        "组队挑战",
        "选择组队挑战",
        "开始组队挑战",
        "组队切磋",
        "接受组队切磋",
        "拒绝组队切磋",
    )
    for command in commands:
        assert len(LocalEventHandler.exact_rules[command]) == 1
        assert len(QqEventHandler.exact_rules[command]) == 1

    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "party-command.db",
            identity_secret="party-command-secret",
        )
        services.database.initialize()
        previous = install_game_services(services)
        try:
            await LocalEventHandler.run()
            for client, name in (
                ("party-a", "领队"),
                ("party-b", "前锋"),
                ("party-c", "策应"),
                ("party-d", "候补"),
            ):
                await _dispatch(client, f"创建角色 {name}", f"create-{client}")

            empty = await _dispatch("party-a", "组队", "party-empty")
            assert "当前没有加入队伍" in empty.replies[0].message.content
            assert empty.replies[0].message.actions[0].data == "创建队伍"
            created = await _dispatch("party-a", "创建队伍", "party-create")
            assert "你现在是队长" in created.replies[0].message.content

            invited = await _dispatch("party-a", "邀请组队 party-b", "party-invite-b")
            assert "已经向对方发出队伍邀请" in invited.replies[0].message.content
            incoming = await _dispatch("party-b", "组队", "party-view-b")
            accept_action = next(
                value for value in incoming.replies[0].message.actions if value.label == "接受"
            )
            forbidden = await _dispatch("party-c", accept_action.data, "party-forbidden-c")
            assert "队伍邀请不属于当前主体" in forbidden.replies[0].message.content
            accepted = await _dispatch("party-b", accept_action.data, "party-accept-b")
            assert "已经加入队伍" in accepted.replies[0].message.content

            nonleader = await _dispatch("party-b", "邀请组队 party-c", "party-nonleader")
            assert "只有队长可以邀请成员" in nonleader.replies[0].message.content
            await _dispatch("party-a", "邀请组队 party-c", "party-invite-c")
            incoming_c = await _dispatch("party-c", "组队", "party-view-c")
            accept_c = next(
                value.data for value in incoming_c.replies[0].message.actions if value.label == "接受"
            )
            await _dispatch("party-c", accept_c, "party-accept-c")
            full = await _dispatch("party-a", "邀请组队 party-d", "party-full")
            assert "队伍人数已经达到上限" in full.replies[0].message.content

            await _dispatch("party-d", "创建队伍", "party-d-create")
            sparring = await _dispatch(
                "party-a",
                "组队切磋 party-d",
                "party-sparring-create",
            )
            assert "3 vs 1" in sparring.replies[0].message.content
            accept_sparring = next(
                value.data
                for value in sparring.replies[0].message.actions
                if value.label == "接受"
            )
            denied_sparring = await _dispatch(
                "party-b",
                accept_sparring,
                "party-sparring-denied",
            )
            assert "只有受邀队伍的队长" in denied_sparring.replies[0].message.content
            completed_sparring = await _dispatch(
                "party-d",
                accept_sparring,
                "party-sparring-accept",
            )
            assert "组队切磋结果" in completed_sparring.replies[0].message.content
            assert "查看完整战报" in completed_sparring.replies[0].message.content

            selected = await _dispatch(
                "party-a",
                "选择组队挑战 1",
                "party-battle-select",
            )
            assert "已锁定组队首领" in selected.replies[0].message.content
            assert "来源世界" in selected.replies[0].message.content

            for client in ("party-a", "party-b", "party-c"):
                ready = await _dispatch(client, "准备", f"party-ready-{client}")
                assert "已标记为准备" in ready.replies[0].message.content
            roster = await _dispatch("party-a", "组队", "party-roster")
            content = roster.replies[0].message.content
            assert "人数: _3/3_" in content
            assert content.count("已准备") == 3
            challenge = await _dispatch("party-a", "组队挑战", "party-battle-view")
            assert "来源世界" in challenge.replies[0].message.content
            assert challenge.replies[0].message.content.count("已准备") == 3
            started = await _dispatch(
                "party-a",
                "开始组队挑战",
                "party-battle-start",
            )
            assert "组队战报" in started.replies[0].message.content
            assert "来源世界" in started.replies[0].message.content
            assert "查看完整战报" in started.replies[0].message.content
            after_battle = await _dispatch("party-a", "组队", "party-after-battle")
            assert after_battle.replies[0].message.content.count("未准备") == 3

            transferred = await _dispatch("party-a", "转让队长 party-b", "party-transfer")
            assert "已经转让队长" in transferred.replies[0].message.content
            left = await _dispatch("party-a", "退出队伍", "party-leave-a")
            assert "已经退出队伍" in left.replies[0].message.content
            kicked = await _dispatch("party-b", "请离队伍 party-c", "party-kick-c")
            assert "已将成员请离队伍" in kicked.replies[0].message.content
            disband_preview = await _dispatch("party-b", "解散队伍", "party-disband-preview")
            disband_confirm = next(
                value.data
                for value in disband_preview.replies[0].message.actions
                if value.label == "确认解散"
            )
            disbanded = await _dispatch("party-b", disband_confirm, "party-disband-confirm")
            assert "队伍已经解散" in disbanded.replies[0].message.content
            final = await _dispatch("party-b", "组队", "party-final")
            assert "当前没有加入队伍" in final.replies[0].message.content
        finally:
            restore_game_services(previous)


async def _dispatch(client_id: str, command: str, event_id: str):
    return await dispatch(
        client_id=client_id,
        raw_message=command,
        sender_name=client_id,
        event_id=event_id,
    )


if __name__ == "__main__":
    main()
