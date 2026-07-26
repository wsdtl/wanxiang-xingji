"""读取当前构筑、执行无损试炼并保存公开战报。"""

from __future__ import annotations

from game.content.catalog.character import CHARACTER_LEVEL_PROGRESSION_ID
from game.core.gameplay import (
    CharacterState,
    InscriptionPreference,
    InventoryState,
    LoadoutState,
    RuleContext,
    Ruleset,
    SeededRandomSource,
    TagSet,
)
from game.rules.battle_report import (
    BattleReportDraft,
    BattleReportSummary,
)
from game.rules.build_trial import BuildTrialBattleSimulator
from game.rules.character import CharacterWorldState
from game.rules.companion import CompanionRosterState

from .models import BuildTrialResult, BuildTrialStorageKinds


BUILD_TRIAL_RULE_VERSION = "rules.build_trial.v1"


class BuildTrialFeature:
    """只读玩家领域快照；唯一写入是公共战报。"""

    def __init__(
        self,
        database,
        content,
        world_views,
        snapshots,
        battle_reports,
        player_lineup,
        storage: BuildTrialStorageKinds,
    ) -> None:
        self.database = database
        self.content = content
        self.world_views = world_views
        self.snapshots = snapshots
        self.battle_reports = battle_reports
        self.storage = storage
        self.battles = BuildTrialBattleSimulator(content.catalog, player_lineup)

    def run(
        self,
        operation_id: str,
        character_id: str,
        mode_id: str,
        *,
        logical_time,
    ) -> BuildTrialResult:
        mode = self.content.build_trials.require(mode_id)
        report_id = self._report_id(operation_id)
        existing = self.battle_reports.reference(report_id)
        if existing is not None:
            return BuildTrialResult("replayed", mode, existing)
        (
            character,
            character_world,
            inventory,
            loadout,
            roster,
            inscription_preference,
        ) = self._snapshot_bundle(character_id)
        context = RuleContext(
            trace_id=f"build-trial:{operation_id}",
            rule_version=BUILD_TRIAL_RULE_VERSION,
            ruleset=Ruleset(
                f"ruleset.build_trial.{mode.id.removeprefix('trial.mode.')}",
                TagSet.of("scene.build_trial", str(mode.id)),
            ),
            logical_time=logical_time,
            random=SeededRandomSource(mode.random_seed),
        )
        outcome = self.battles.simulate(
            mode,
            character=character,
            inventory=inventory,
            loadout=loadout,
            roster=roster,
            battle_id=f"battle:build-trial:{operation_id}",
            context=context,
        )
        report = self.battle_reports.capture(
            self._battle_report(
                report_id,
                operation_id,
                mode,
                character,
                character_world,
                inventory,
                loadout,
                roster,
                inscription_preference,
                outcome,
                logical_time,
            )
        )
        return BuildTrialResult("completed", mode, report, outcome)

    def _snapshot_bundle(self, character_id: str):
        with self.database.unit_of_work(write=False) as uow:
            character = self.snapshots.require(
                uow,
                self.storage.character,
                character_id,
                CharacterState,
            )
            character_world = self.snapshots.require(
                uow,
                self.storage.character_world,
                character_id,
                CharacterWorldState,
            )
            inventory = self.snapshots.require(
                uow,
                self.storage.inventory,
                character_id,
                InventoryState,
            )
            loadout = self.snapshots.require(
                uow,
                self.storage.loadout,
                character_id,
                LoadoutState,
            )
            roster = self.snapshots.load(
                uow,
                self.storage.companion_roster,
                character_id,
                CompanionRosterState,
            ) or CompanionRosterState(character_id)
            inscription_preference = self.snapshots.load(
                uow,
                self.storage.inscription_preference,
                character_id,
                InscriptionPreference,
            )
        return (
            character,
            character_world,
            inventory,
            loadout,
            roster,
            inscription_preference,
        )

    def _battle_report(
        self,
        report_id,
        operation_id,
        mode,
        character,
        character_world,
        inventory,
        loadout,
        roster,
        inscription_preference,
        outcome,
        logical_time,
    ) -> BattleReportDraft:
        combatants = [
            self.battle_reports.builder.character(
                character,
                character_world,
                inventory,
                loadout,
                team_id="player",
                team_label="试炼者一方",
                inscription_preference=inscription_preference,
            )
        ]
        if outcome.companion_id is not None:
            companion = roster.instances[outcome.companion_id]
            combatants.append(
                self.battle_reports.builder.companion(
                    companion,
                    team_id="player",
                    team_label="试炼者一方",
                )
            )
        level = character.progressions[CHARACTER_LEVEL_PROGRESSION_ID].level
        enemies = self.battles.enemy_instances(mode, level)
        for index, enemy in enumerate(enemies, start=1):
            name = (
                mode.target_name
                if mode.target_count == 1
                else f"{mode.target_name}{index}号"
            )
            combatants.append(
                self.battle_reports.builder.enemy(
                    enemy,
                    character_world.world_id,
                    name,
                    team_id="trial_target",
                    team_label="试炼目标",
                    unit_kind="trial_target",
                )
            )
        result_text = _result_text(mode.id, outcome)
        metrics = outcome.metrics
        summary = BattleReportSummary(
            f"构筑试炼·{mode.name}",
            result_text,
            (
                f"阵容伤害: {_number(metrics.total_damage)}",
                f"承受伤害: {_number(metrics.damage_taken)}",
                f"阵容行动: {metrics.player_actions}",
                f"暴击/触发: {metrics.critical_hits}/{metrics.trigger_activations}",
            ),
            "victory" if outcome.completed else "defeat",
        )
        return BattleReportDraft(
            report_id=report_id,
            mode_id=f"battle.mode.build_trial.{mode.id.removeprefix('trial.mode.')}",
            content_fingerprint=self.content.catalog.report.content_fingerprint,
            summary=summary,
            segment=self.battle_reports.builder.segment(
                segment_id=operation_id,
                title=f"{character.name}·{mode.name}构筑试炼",
                trace=outcome.trace,
                combatants=combatants,
                outcome=result_text,
                started_at=logical_time,
                finished_at=logical_time,
            ),
        )

    @staticmethod
    def _report_id(operation_id: str) -> str:
        value = str(operation_id or "").strip()
        if not value:
            raise ValueError("构筑试炼缺少操作身份")
        return f"battle-report:build-trial:{value}"


def _result_text(mode_id, outcome) -> str:
    if str(mode_id) == "trial.mode.endurance":
        return "持久试炼完成" if outcome.completed else "阵容提前倒下"
    if outcome.victory:
        return "试炼完成"
    if outcome.draw:
        return "达到试炼上限"
    return "阵容提前倒下"


def _number(value: float) -> str:
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


__all__ = ["BUILD_TRIAL_RULE_VERSION", "BuildTrialFeature"]
