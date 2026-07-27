"""构筑试炼参数解析和协议中立展示。"""

from __future__ import annotations

import asyncio

from game.app import CurrentCharacterResult, current_game_services
from launch.adapter import current_message_context
from launch.paths import public_url
from message import Action, M
from message.schema import FieldSeparator

from ..command_helpers import command_time
from ..reply import send_command_failure, send_game_reply


async def view_trials() -> None:
    services = current_game_services()
    modes = services.content.build_trials.definitions()
    builder = M.document().section("构筑试炼", icon="combat")
    for mode, link in zip(modes, _mode_links(modes), strict=True):
        builder.line(link, FieldSeparator(), mode.summary)
    builder.note("试炼使用当前配装与伙伴，不消耗资源，也不会产生任何收益。")
    await send_game_reply(builder.build())


async def start_trial(message: str, current: CurrentCharacterResult) -> None:
    character = current.character if current.status == "ok" else None
    if character is None:
        await send_game_reply(
            _failure(
                "当前没有可用角色",
                Action("build-trial.character", "查看角色", "我的角色"),
            )
        )
        return
    services = current_game_services()
    modes = services.content.build_trials.definitions()
    mode = services.content.build_trials.resolve(message)
    if mode is None:
        builder = M.document().section("构筑试炼", icon="combat").line(
            f"请选择{_mode_names(modes)}模式"
        )
        for link in _mode_links(modes):
            builder.line(link)
        await send_game_reply(
            builder.build()
        )
        return
    context = current_message_context()
    if context is None:
        raise RuntimeError("构筑试炼命令缺少消息上下文")
    try:
        result = await asyncio.to_thread(
            services.build_trials.run,
            context.identity.evidence_id,
            character.id,
            str(mode.id),
            logical_time=command_time(),
        )
    except Exception as exc:
        await send_command_failure(
            "构筑试炼执行失败",
            character.id,
            exc,
            _failure(
                "试炼执行失败，请稍后重试",
                Action("build-trial.retry", "查看试炼", "构筑试炼"),
            ),
        )
        return
    await send_game_reply(_result_message(result))


def _result_message(result):
    mode = result.mode
    builder = M.document().section(f"构筑试炼·{mode.name}", icon="combat")
    if result.status == "replayed":
        builder.line("已返回本次操作生成的既有战报")
    elif result.outcome is not None:
        outcome = result.outcome
        metrics = outcome.metrics
        builder.line(_outcome_text(mode.id, outcome))
        builder.field("阵容输出", f"{_number(metrics.total_damage)} / {metrics.player_actions}次行动")
        builder.field("生存承压", f"承伤{_number(metrics.damage_taken)} · 治疗{_number(metrics.healing)} · 护盾{_number(metrics.shield)}")
        builder.field("机制触发", f"暴击{metrics.critical_hits} · 特效{metrics.trigger_activations} · 击败{metrics.enemies_defeated}")
        builder.field("结束资源", f"血气{_number(metrics.health_after)}/{_number(metrics.health_maximum)} · 灵力{_number(metrics.spirit_after)}/{_number(metrics.spirit_maximum)}")
    if result.report is not None:
        builder.field(
            "战报",
            M.link("查看完整战报", public_url("battle", result.report.share_id)),
        )
    builder.note("本次试炼未修改血气、灵力、药品、行动、经验或资产。")
    return builder.actions(
        (
            Action(
                "build_trial.repeat",
                "再次试炼",
                f"开始试炼 {mode.name}",
            ),
            Action(
                "build_trial.modes",
                "更换模式",
                "构筑试炼",
                style="secondary",
            ),
        )
    ).build()


def _mode_links(modes):
    return tuple(
        M.command(
            mode.name,
            f"开始试炼 {mode.name}",
        )
        for mode in modes
    )


def _mode_names(modes) -> str:
    return "、".join(mode.name for mode in modes)


def _outcome_text(mode_id, outcome) -> str:
    if str(mode_id) == "trial.mode.endurance":
        return "持久验证完成" if outcome.completed else "阵容在时限前倒下"
    if outcome.victory:
        return "目标已经清除"
    if outcome.draw:
        return "达到试炼上限，目标仍未清除"
    return "阵容在目标清除前倒下"


def _failure(message: str, recovery: Action):
    return (
        M.document()
        .section("构筑试炼", icon="combat")
        .line(message)
        .action(recovery)
        .build()
    )


def _number(value: float) -> str:
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


__all__ = ["start_trial", "view_trials"]
