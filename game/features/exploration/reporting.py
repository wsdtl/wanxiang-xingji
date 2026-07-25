"""把探险战斗轨迹交给统一战报装配器。"""

from __future__ import annotations

from game.rules.battle_report import (
    BattleReportDraft,
    BattleReportSummary,
)

from .models import exploration_battle_report_id


def build_exploration_battle_report(
    content,
    builder,
    state,
    next_state,
    character,
    character_world,
    inventory,
    loadout,
    inscription_preference,
    roster,
    battle,
    segment_id: str,
    view,
) -> BattleReportDraft:
    plan = next_state.last_result.plan
    assert plan.encounter is not None
    enemies = tuple(plan.encounter.enemies)
    combatants = [
        builder.character(
            character,
            character_world,
            inventory,
            loadout,
            team_id="player",
            team_label="行者一方",
            inscription_preference=inscription_preference,
        )
    ]
    if battle.player_companion_id is not None:
        companion = roster.instances[battle.player_companion_id]
        combatants.append(
            builder.companion(
                companion,
                team_id="player",
                team_label="行者一方",
            )
        )
    enemy_names = []
    for enemy in enemies:
        name = view.enemy_projector.enemy(enemy).name
        enemy_names.append(name)
        combatants.append(
            builder.enemy(
                enemy,
                character_world.world_id,
                name,
                team_id="enemy",
                team_label="遭遇一方",
            )
        )
    outcome = (
        "探险胜利"
        if battle.victory
        else "战斗平局"
        if battle.draw
        else "探险战败"
    )
    return BattleReportDraft(
        report_id=exploration_battle_report_id(state.session_id),
        mode_id="battle.mode.exploration",
        content_fingerprint=content.catalog.report.content_fingerprint,
        summary=build_exploration_battle_report_summary(next_state, view),
        segment=builder.segment(
            segment_id=segment_id,
            title=f"第 {plan.batch_index} 批·{', '.join(enemy_names)}",
            trace=battle.trace,
            combatants=combatants,
            outcome=outcome,
            started_at=next_state.last_result.resolved_at,
            finished_at=next_state.last_result.resolved_at,
        ),
    )


def build_exploration_battle_report_summary(state, view) -> BattleReportSummary:
    """生成可在最终短事务中替换的轻量结算摘要。"""

    result = state.last_result
    if result is None or result.plan.encounter is None:
        raise ValueError("探险战报摘要缺少战斗批次")
    return BattleReportSummary(
        f"探险战报·{view.projector.name(state.location_id)}",
        f"{state.victories}胜 {state.defeats}负",
        (
            f"完成批次: {state.completed_batches}",
            f"累计经验: +{state.character_experience}",
            f"伙伴经验: +{state.companion_experience}",
            f"累计掉落: 武器 {state.weapon_drops}, 装备 {state.equipment_drops}",
        ),
        "victory" if result.victory else "neutral" if result.draw else "defeat",
    )


__all__ = [
    "build_exploration_battle_report",
    "build_exploration_battle_report_summary",
]
