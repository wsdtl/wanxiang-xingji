"""伙伴等级、经验和战斗经验的独立规则。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from game.content.catalog.companion import CompanionCatalog

from .models import CompanionRosterState


@dataclass(frozen=True)
class CompanionExperienceResult:
    companion_id: str
    requested: int
    accepted: int
    discarded: int
    level_before: int
    level_after: int
    experience_before: int
    experience_after: int


class CompanionGrowthEngine:
    """只负责伙伴成长，不修改人物、武器或物品库存。"""

    def __init__(self, catalog: CompanionCatalog) -> None:
        self.catalog = catalog

    def grant_experience(
        self,
        roster: CompanionRosterState,
        companion_id: str,
        amount: int,
        *,
        character_level: int,
    ) -> tuple[CompanionRosterState, CompanionExperienceResult]:
        if isinstance(amount, bool) or amount < 0:
            raise ValueError("伙伴经验必须是非负整数")
        if character_level < 1:
            raise ValueError("人物等级必须大于零")
        companion = roster.instances.get(companion_id)
        if companion is None:
            raise ValueError("找不到目标伙伴")
        level_before = companion.level
        experience_before = companion.experience
        level = companion.level
        experience = companion.experience
        accepted = 0
        remaining = amount
        cap = min(100, character_level)
        while remaining > 0 and level < cap:
            required = self.catalog.growth.required_for_next_level(level)
            if required is None:
                break
            missing = max(0, required - experience)
            if missing == 0:
                level += 1
                experience = 0
                continue
            used = min(remaining, missing)
            accepted += used
            remaining -= used
            experience += used
            if experience == required:
                level += 1
                experience = 0
        discarded = amount - accepted
        result = CompanionExperienceResult(
            companion_id,
            amount,
            accepted,
            discarded,
            level_before,
            level,
            experience_before,
            experience,
        )
        if accepted == 0:
            return roster, result
        next_instance = replace(
            companion,
            level=level,
            experience=experience,
            total_experience=companion.total_experience + accepted,
        )
        instances = dict(roster.instances)
        instances[companion_id] = next_instance
        return replace(roster, instances=instances, revision=roster.revision + 1), result

    def exploration_experience(self, encounter_kind: str, enemy_levels: tuple[int, ...]) -> int:
        multiplier = self.catalog.growth.exploration_multipliers.get(encounter_kind)
        if multiplier is None:
            return 0
        return sum(max(1, round(level * multiplier)) for level in enemy_levels)

    def party_boss_experience(self, enemy_level: int) -> int:
        return max(1, round(enemy_level * self.catalog.growth.party_boss_multiplier))

    def disaster_experience(self, enemy_level: int, damage: int, maximum_health: int) -> int:
        if damage <= 0 or maximum_health <= 0:
            return 0
        ratio = damage / maximum_health
        multiplier = self.catalog.growth.disaster_damage_tiers[0][1]
        for threshold, candidate in self.catalog.growth.disaster_damage_tiers:
            if ratio >= threshold:
                multiplier = candidate
        return max(1, round(enemy_level * multiplier))


__all__ = ["CompanionExperienceResult", "CompanionGrowthEngine"]
