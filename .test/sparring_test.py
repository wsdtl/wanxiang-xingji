"""切磋请求、服务端权限、无损战斗和公开战报闭环测试。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services, install_game_services, restore_game_services  # noqa: E402
from game.cmd import 切磋 as sparring_component  # noqa: E402,F401
from game.cmd import 角色 as character_component  # noqa: E402,F401
from game.core.persistence import CHARACTER_AGGREGATE  # noqa: E402
from game.core.gameplay import SocialRequestStatus  # noqa: E402
from game.features.sparring import sparring_social_scope_id  # noqa: E402
from launch.adapter.local import LocalEventHandler, dispatch  # noqa: E402
from launch.adapter.qq import QqEventHandler  # noqa: E402


TIMEZONE = ZoneInfo("Asia/Shanghai")


def main() -> None:
    asyncio.run(_main())
    print("sparring tests passed")


async def _main() -> None:
    for command in ("切磋", "接受切磋", "拒绝切磋"):
        assert len(LocalEventHandler.exact_rules[command]) == 1
        assert len(QqEventHandler.exact_rules[command]) == 1

    with TemporaryDirectory() as directory:
        services = build_game_services(
            database_path=Path(directory) / "sparring.db",
            identity_secret="sparring-test-secret",
        )
        services.database.initialize()
        previous = install_game_services(services)
        try:
            await LocalEventHandler.run()
            await _dispatch("player-a", "创建角色 问剑", "sparring-create-a")
            await _dispatch("player-b", "创建角色 守岳", "sparring-create-b")
            characters = _characters(services)
            challenger = characters["问剑"]
            defender = characters["守岳"]
            challenger_before = challenger
            defender_before = defender

            invitation = await _dispatch(
                "player-a",
                "切磋 player-b",
                "sparring-request-a",
            )
            message = invitation.replies[0].message
            assert "问剑 向 守岳 发起切磋" in message.content
            assert {action.label for action in message.actions} == {"接受", "拒绝"}
            accept_command = next(
                action.data for action in message.actions if action.label == "接受"
            )
            request_id = accept_command.removeprefix("接受切磋 ")

            forbidden = await _dispatch(
                "player-a",
                accept_command,
                "sparring-forbidden-a",
            )
            assert "找不到这份切磋请求" in forbidden.replies[0].message.content

            with patch.object(
                services.battle_reports,
                "capture_in_uow",
                side_effect=RuntimeError("injected report failure"),
            ):
                try:
                    services.sparring.accept_request(
                        "sparring-atomic-failure",
                        request_id,
                        defender,
                        logical_time=datetime.now(TIMEZONE),
                    )
                except RuntimeError as exc:
                    assert str(exc) == "injected report failure"
                else:
                    raise AssertionError("战报写入失败应中止切磋事务")
            pending_state = services.sparring.social.load(
                sparring_social_scope_id(defender.id)
            )
            assert pending_state is not None
            assert pending_state.requests[request_id].status is SocialRequestStatus.PENDING
            assert services.battle_reports.reference(
                f"battle-report:sparring:{request_id}"
            ) is None

            accepted = await _dispatch(
                "player-b",
                accept_command,
                "sparring-accept-b",
            )
            accepted_text = accepted.replies[0].message.content
            assert "查看完整战报" in accepted_text
            assert "不会改变双方血气" in accepted_text

            challenger_after = services.characters.load_character(challenger.id)
            defender_after = services.characters.load_character(defender.id)
            assert challenger_after == challenger_before
            assert defender_after == defender_before

            report = services.battle_reports.reference(
                f"battle-report:sparring:{request_id}"
            )
            assert report is not None
            view = services.battle_reports.load_public(
                report.share_id,
                logical_time=datetime.now(TIMEZONE),
            )
            assert view is not None and view.detail_available
            assert view.mode_id == "battle.mode.sparring"
            assert view.segments[0].transitions
            assert all(
                transition.after.participants
                for transition in view.segments[0].transitions
            )
            assert any(
                transition.kind == "turn"
                for transition in view.segments[0].transitions
            )

            replayed = await _dispatch(
                "player-b",
                accept_command,
                "sparring-accept-replay-b",
            )
            assert "查看完整战报" in replayed.replies[0].message.content

            reverse = await _dispatch(
                "player-b",
                "切磋 player-a",
                "sparring-request-b",
            )
            reject_command = next(
                action.data
                for action in reverse.replies[0].message.actions
                if action.label == "拒绝"
            )
            rejected = await _dispatch(
                "player-a",
                reject_command,
                "sparring-reject-a",
            )
            assert "已经拒绝这次切磋" in rejected.replies[0].message.content
            incoming_a = services.sparring.social.load(
                sparring_social_scope_id(challenger.id)
            )
            incoming_b = services.sparring.social.load(
                sparring_social_scope_id(defender.id)
            )
            assert incoming_a is not None and len(incoming_a.requests) == 1
            assert incoming_b is not None and len(incoming_b.requests) == 1

            expired_request = services.sparring.create_request(
                "sparring-expired",
                challenger,
                defender,
                logical_time=datetime.now(TIMEZONE) - timedelta(minutes=11),
            )
            assert expired_request.status == "created"
            expired = await _dispatch(
                "player-b",
                "接受切磋 sparring-expired",
                "sparring-expired-b",
            )
            assert "切磋请求已经过期" in expired.replies[0].message.content
        finally:
            restore_game_services(previous)


async def _dispatch(client_id: str, command: str, event_id: str):
    return await dispatch(
        client_id=client_id,
        raw_message=command,
        sender_name=client_id,
        event_id=event_id,
    )


def _characters(services):
    with services.database.unit_of_work(write=False) as uow:
        rows = uow.connection.execute(
            "SELECT aggregate_id FROM aggregate_snapshot WHERE aggregate_kind = ?",
            (CHARACTER_AGGREGATE,),
        ).fetchall()
    values = [services.characters.load_character(str(row[0])) for row in rows]
    assert all(value is not None for value in values)
    return {value.name: value for value in values}


if __name__ == "__main__":
    main()
