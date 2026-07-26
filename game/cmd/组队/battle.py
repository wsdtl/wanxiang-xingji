"""组队首领选择、准备状态和挑战结果展示。"""

from __future__ import annotations

import asyncio

from game.app import CurrentCharacterResult, current_game_services
from game.core.gameplay import Party
from launch.paths import public_url
from message import Action, DocumentMessage, M
from message.schema import FieldSeparator

from ..reply import send_game_reply
from ..presentation import activity_block_feedback, health_depleted_feedback
from . import shared


async def set_ready(current: CurrentCharacterResult, ready: bool) -> None:
    character = shared.character(current)
    if character is None:
        await send_game_reply(shared.failure("当前没有可用角色"))
        return
    try:
        services = current_game_services()
        party_view = await asyncio.to_thread(
            services.party.view,
            character.id,
            logical_time=shared.command_time(),
        )
        if party_view.party is None:
            await send_game_reply(shared.failure("当前没有队伍"))
            return
        result = await asyncio.to_thread(
            services.party_battles.set_ready,
            shared.operation_id("party-battle-ready"),
            party_view.party.id,
            character.id,
            ready,
            logical_time=shared.command_time(),
        )
        if result.activity_block is not None:
            feedback = activity_block_feedback(
                result.activity_block,
                "准备组队挑战",
            )
            reply = shared.failure(feedback.text, feedback.recovery)
        elif result.status == "health_depleted":
            feedback = health_depleted_feedback("准备组队挑战")
            reply = (
                M.document()
                .section("组队", icon="notice")
                .line(feedback.text)
                .actions(feedback.recoveries)
                .build()
            )
        elif result.status in {"ready", "unready", "replayed"}:
            reply = _challenge_message(
                party_view.party,
                result.challenge,
                character.id,
            )
        else:
            reply = shared.failure(
                result.failure_message or "准备状态没有更新",
                Action("party-battle.back", "返回挑战", "组队挑战", style="secondary"),
            )
        await send_game_reply(reply)
    except Exception as exc:
        await shared.failed("更新准备状态失败", character.id, exc)


async def view(current: CurrentCharacterResult) -> None:
    character = shared.character(current)
    if character is None:
        await send_game_reply(shared.failure("当前没有可用角色"))
        return
    try:
        services = current_game_services()
        party_view = await asyncio.to_thread(
            services.party.view,
            character.id,
            logical_time=shared.command_time(),
        )
        if party_view.party is None:
            await send_game_reply(shared.failure("请先加入队伍"))
            return
        challenge = await asyncio.to_thread(
            services.party_battles.view,
            party_view.party.id,
        )
        if challenge.status == "content_changed":
            action = (
                Action(
                    "party-battle.select",
                    "重新选择首领",
                    "选择组队挑战 ",
                    behavior="fill",
                )
                if party_view.party.leader_id == character.id
                else Action(
                    "party-battle.party",
                    "返回队伍",
                    "队伍",
                    behavior="callback",
                    style="secondary",
                )
            )
            await send_game_reply(
                shared.failure(challenge.failure_message, action)
            )
            return
        await send_game_reply(
            _challenge_message(
                party_view.party,
                challenge.challenge,
                character.id,
            )
        )
    except Exception as exc:
        await shared.failed("组队挑战读取失败", character.id, exc)


async def select(message: str, current: CurrentCharacterResult) -> None:
    character = shared.character(current)
    if character is None:
        await send_game_reply(shared.failure("当前没有可用角色"))
        return
    try:
        level = int(str(message or "").strip())
    except ValueError:
        await send_game_reply(shared.failure("发送：选择组队挑战 等级"))
        return
    try:
        services = current_game_services()
        party_view = await asyncio.to_thread(
            services.party.view,
            character.id,
            logical_time=shared.command_time(),
        )
        if party_view.party is None:
            await send_game_reply(shared.failure("请先加入队伍"))
            return
        result = await asyncio.to_thread(
            services.party_battles.select,
            shared.operation_id("party-battle-select"),
            party_view.party.id,
            character.id,
            level,
            logical_time=shared.command_time(),
        )
        reply = (
            _challenge_message(
                party_view.party,
                result.challenge,
                character.id,
            )
            if result.status in {"selected", "replayed"}
            else shared.failure(
                result.failure_message or "组队首领选择没有完成",
                Action(
                    "party-battle.select.retry",
                    "重新选择",
                    "选择组队挑战 ",
                    behavior="fill",
                ),
            )
        )
        await send_game_reply(reply)
    except Exception as exc:
        await shared.failed("选择组队首领失败", character.id, exc)


async def start(current: CurrentCharacterResult) -> None:
    character = shared.character(current)
    if character is None:
        await send_game_reply(shared.failure("当前没有可用角色"))
        return
    try:
        services = current_game_services()
        party_view = await asyncio.to_thread(
            services.party.view,
            character.id,
            logical_time=shared.command_time(),
        )
        if party_view.party is None:
            await send_game_reply(shared.failure("请先加入队伍"))
            return
        result = await asyncio.to_thread(
            services.party_battles.challenge,
            shared.operation_id("party-battle-start"),
            party_view.party.id,
            character.id,
            logical_time=shared.command_time(),
        )
        if result.status in {"victory", "draw", "defeated", "replayed"}:
            builder = M.document().section("组队战报", icon="combat")
            if result.challenge is not None:
                builder.field(
                    "来源世界",
                    shared.world_name(result.challenge.source_world_id),
                )
            builder.row(
                ("首领", result.enemy_name),
                ("结果", "胜利" if result.victory else "平局" if result.draw else "战败"),
            )
            builder.field("战斗行动", result.turns)
            for character_id, lines in result.reward_summaries.items():
                builder.line(
                    shared.character_name(character_id),
                    "：",
                    "；".join(lines),
                )
            if result.share_id:
                builder.field(
                    "战报",
                    M.link("查看完整战报", public_url("battle", result.share_id)),
                )
            builder.actions(
                (
                    Action(
                        "party-battle.select.next",
                        "选择下一场",
                        "选择组队挑战 ",
                        behavior="fill",
                    ),
                    Action(
                        "party-battle.party",
                        "返回队伍",
                        "队伍",
                        style="secondary",
                    ),
                )
            )
            reply = builder.build()
        else:
            if result.activity_block is not None:
                is_current = result.activity_block.character_id == character.id
                feedback = activity_block_feedback(
                    result.activity_block,
                    "开始组队挑战",
                    subject_name=(
                        ""
                        if is_current
                        else shared.character_name(result.activity_block.character_id)
                    ),
                    allow_recovery=is_current,
                )
                reply = shared.failure(feedback.text, feedback.recovery)
            elif result.status == "health_depleted" and result.blocked_character_id:
                is_current = result.blocked_character_id == character.id
                feedback = health_depleted_feedback(
                    "开始组队挑战",
                    subject_name=(
                        ""
                        if is_current
                        else shared.character_name(result.blocked_character_id)
                    ),
                    allow_recovery=is_current,
                )
                reply = (
                    M.document()
                    .section("组队", icon="notice")
                    .line(feedback.text)
                    .actions(feedback.recoveries)
                    .build()
                )
            elif result.status == "loadout_changed" and result.blocked_character_id:
                is_current = result.blocked_character_id == character.id
                name = (
                    "当前"
                    if is_current
                    else shared.character_name(result.blocked_character_id)
                )
                builder = (
                    M.document()
                    .section("组队", icon="notice")
                    .line(f"{name}准备后的状态或配装已经变化，需要重新准备")
                )
                if is_current:
                    builder.action(
                        Action(
                            "party-battle.ready-again",
                            "重新准备",
                            "准备",
                        )
                    )
                reply = builder.build()
            else:
                reply = shared.failure(
                    result.failure_message or "组队挑战没有开始"
                )
        await send_game_reply(reply)
    except Exception as exc:
        await shared.failed("组队挑战执行失败", character.id, exc)


def _challenge_message(
    party: Party,
    challenge,
    character_id: str,
) -> DocumentMessage:
    builder = M.document().section("组队挑战", icon="combat")
    if challenge is None:
        builder.line("当前没有锁定的组队首领")
        if party.leader_id == character_id:
            builder.action(
                Action(
                    "party-battle.select",
                    "选择首领",
                    "选择组队挑战 ",
                    behavior="fill",
                )
            )
        else:
            builder.action(
                Action("party-battle.party", "返回队伍", "队伍", style="secondary")
            )
        return builder.build()
    services = current_game_services()
    view = services.world_views.require(challenge.source_world_id)
    enemy = view.enemy_projector.enemy(challenge.encounter.enemies[0])
    builder.field("来源世界", view.skin.name)
    builder.row(("首领", enemy.name), ("等级", str(challenge.level)))
    builder.line(
        "状态",
        FieldSeparator(),
        "待挑战" if challenge.status == "selected" else "已完成",
    )
    builder.line("挑战次数", FieldSeparator(), str(challenge.attempt_count))
    for member in sorted(party.members.values(), key=lambda value: value.slot):
        ready = (
            "已准备"
            if member.subject_id in challenge.ready_fingerprints
            else "未准备"
        )
        builder.line(
            f"{member.slot + 1}. {shared.character_name(member.subject_id)}",
            FieldSeparator(),
            ready,
        )
    if challenge.status == "selected":
        ready = character_id in challenge.ready_fingerprints
        all_ready = set(party.members) <= set(challenge.ready_fingerprints)
        actions = []
        if party.leader_id == character_id and all_ready:
            actions.append(
                Action(
                    "party-battle.start",
                    "发起挑战",
                    "开始组队挑战",
                    behavior="callback",
                )
            )
        actions.append(
            Action(
                "party-battle.unready" if ready else "party-battle.ready",
                "取消准备" if ready else "准备",
                "取消准备" if ready else "准备",
                behavior="callback",
                style="secondary" if ready else "primary",
            )
        )
        actions.append(
            Action("party-battle.party", "返回队伍", "队伍", style="secondary")
        )
        return builder.actions(actions).build()
    if challenge.report_id:
        report = services.battle_reports.reference(challenge.report_id)
        if report is not None:
            builder.field(
                "战报",
                M.link("查看完整战报", public_url("battle", report.share_id)),
            )
    return builder.actions(
        (
            Action(
                "party-battle.select.next",
                "选择下一场",
                "选择组队挑战 ",
                behavior="fill",
            ),
            Action(
                "party-battle.party",
                "返回队伍",
                "队伍",
                behavior="callback",
                style="secondary",
            ),
        )
    ).build()


__all__ = ["select", "set_ready", "start", "view"]
