"""宠物秘境、人物关系、通用伙伴名册与配装绑定纯规则。"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from game.content.catalog.companion import CompanionCatalog
from game.core.gameplay import RandomSource, StableId, stable_id

from .models import (
    COMPANION_APTITUDE_IDS,
    CompanionAcquisitionKind,
    CompanionInstance,
    CompanionKind,
    CompanionRosterState,
    CompanionSanctuaryState,
    CompanionSanctuaryStatus,
    CompanionTrace,
    PersonBondState,
)


class CompanionRuleError(ValueError):
    """可稳定映射为玩家结果的伙伴纯规则拒绝。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CompanionEngine:
    def __init__(self, catalog: CompanionCatalog) -> None:
        self.catalog = catalog

    def open_sanctuary(
        self,
        roster: CompanionRosterState,
        previous: CompanionSanctuaryState | None,
        *,
        session_id: str,
        world_id: StableId,
        character_level: int,
        content_version: str,
        logical_time,
        random: RandomSource,
    ) -> CompanionSanctuaryState:
        if previous is not None and previous.active:
            self._fail("companion.sanctuary_active", "当前已有尚未结束的宠物秘境")
        if len(roster.instances) >= self.catalog.balance.roster_capacity:
            self._fail("companion.roster_full", "伙伴名册已经达到上限")
        sanctuary = self.catalog.require_sanctuary(world_id)
        selected = self._weighted_unique_species(
            sanctuary.species_ids,
            sanctuary.trace_count,
            random,
        )
        traces = tuple(
            self._trace(index, species_id, character_level, session_id, random)
            for index, species_id in enumerate(selected, start=1)
        )
        revision = 0 if previous is None else previous.revision + 1
        return CompanionSanctuaryState(
            roster.character_id,
            str(session_id),
            sanctuary.id,
            sanctuary.world_id,
            logical_time,
            logical_time + timedelta(seconds=sanctuary.duration_seconds),
            traces,
            content_version,
            revision=revision,
        )

    def select_trace(
        self,
        sanctuary: CompanionSanctuaryState,
        trace_index: int,
        *,
        logical_time,
    ) -> CompanionSanctuaryState:
        current = self.expire(sanctuary, logical_time=logical_time)
        if not current.active:
            self._fail("companion.sanctuary_inactive", "宠物秘境已经结束")
        trace = next((value for value in current.traces if value.index == trace_index), None)
        if trace is None:
            self._fail("companion.trace_unknown", "宠物秘境中没有这条踪迹")
        if current.selected_trace_index is not None:
            if current.selected_trace_index != trace_index:
                self._fail("companion.trace_locked", "宠物秘境已经锁定另一条踪迹")
            return current
        return replace(
            current,
            status=CompanionSanctuaryStatus.TRACKING,
            selected_trace_index=trace_index,
            revision=current.revision + 1,
        )

    def record_failed_attempt(
        self,
        sanctuary: CompanionSanctuaryState,
        *,
        logical_time,
    ) -> CompanionSanctuaryState:
        current = self.expire(sanctuary, logical_time=logical_time)
        if current.status is not CompanionSanctuaryStatus.TRACKING:
            self._fail("companion.trace_not_selected", "尚未选择要追踪的伙伴")
        return replace(
            current,
            attempt_count=current.attempt_count + 1,
            revision=current.revision + 1,
        )

    def capture(
        self,
        roster: CompanionRosterState,
        sanctuary: CompanionSanctuaryState,
        *,
        logical_time,
    ) -> tuple[CompanionRosterState, CompanionSanctuaryState, CompanionInstance]:
        current = self.expire(sanctuary, logical_time=logical_time)
        if current.status is not CompanionSanctuaryStatus.TRACKING:
            self._fail("companion.trace_not_selected", "尚未选择要捕获的伙伴")
        if len(roster.instances) >= self.catalog.balance.roster_capacity:
            self._fail("companion.roster_full", "伙伴名册预留位置已经失效")
        trace = current.selected_trace()
        if trace is None:
            raise RuntimeError("追踪中的宠物秘境缺少固定踪迹")
        species = self.catalog.species.require(trace.definition_id)
        sequence = roster.next_sequence
        instance = CompanionInstance(
            id=f"{roster.character_id}:companion:{sequence}",
            reference=f"C{sequence}",
            owner_id=roster.character_id,
            definition_id=species.id,
            origin_world_id=species.origin_world_id,
            quality_id=trace.quality_id,
            level=1,
            experience=0,
            total_experience=0,
            aptitudes=trace.aptitudes,
            trait_behavior_id=trace.trait_behavior_id,
            kind=CompanionKind.PET,
            acquired_at=logical_time,
            acquisition_kind=CompanionAcquisitionKind.SANCTUARY_CAPTURE,
            acquisition_id=current.session_id,
        )
        instances = dict(roster.instances)
        instances[instance.id] = instance
        next_roster = replace(
            roster,
            instances=instances,
            captured_definition_ids=roster.captured_definition_ids | {species.id},
            next_sequence=sequence + 1,
            revision=roster.revision + 1,
        )
        next_sanctuary = replace(
            current,
            status=CompanionSanctuaryStatus.CAPTURED,
            attempt_count=current.attempt_count + 1,
            captured_companion_id=instance.id,
            revision=current.revision + 1,
        )
        return next_roster, next_sanctuary, instance

    def bind(
        self,
        roster: CompanionRosterState,
        companion_id: str,
        preset_id: StableId,
        *,
        allow_transfer: bool = False,
    ) -> CompanionRosterState:
        if companion_id not in roster.instances:
            self._fail("companion.unknown", "找不到这名伙伴")
        preset_id = stable_id(preset_id, field="companion loadout preset id")
        previous_preset = roster.preset_for_companion(companion_id)
        if previous_preset == preset_id and roster.bindings.get(preset_id) == companion_id:
            return roster
        if previous_preset is not None and not allow_transfer:
            self._fail("companion.bound_elsewhere", "这名伙伴已经属于其他配装")
        bindings = {
            key: value
            for key, value in roster.bindings.items()
            if value != companion_id and key != preset_id
        }
        bindings[preset_id] = companion_id
        return replace(roster, bindings=bindings, revision=roster.revision + 1)

    def unbind(
        self,
        roster: CompanionRosterState,
        preset_id: StableId,
    ) -> CompanionRosterState:
        preset_id = stable_id(preset_id, field="companion loadout preset id")
        if preset_id not in roster.bindings:
            return roster
        bindings = dict(roster.bindings)
        del bindings[preset_id]
        return replace(roster, bindings=bindings, revision=roster.revision + 1)

    def give_gift(
        self,
        roster: CompanionRosterState,
        person_definition_id: StableId,
        favor: int,
        *,
        logical_time,
    ) -> tuple[CompanionRosterState, int, int]:
        person = self.catalog.people.require(person_definition_id)
        if favor < 1:
            self._fail("companion.gift_value_invalid", "赠礼关系值必须大于零")
        if roster.active_by_definition(person.id) is not None:
            self._fail("companion.person_joined", "这名人物已经是你的伙伴")
        if person.id in roster.departed_people:
            self._fail("companion.person_departed", "这名人物曾与你同行，可以直接再次结交")
        previous = roster.person_bonds.get(person.id)
        before = previous.favor if previous is not None else 0
        after = min(person.bond_required, before + favor)
        bonds = dict(roster.person_bonds)
        bonds[person.id] = PersonBondState(
            person.id,
            after,
            previous.met_at if previous is not None else logical_time,
        )
        return (
            replace(roster, person_bonds=bonds, revision=roster.revision + 1),
            before,
            after,
        )

    def join_person(
        self,
        roster: CompanionRosterState,
        person_definition_id: StableId,
        character_level: int,
        *,
        logical_time,
    ) -> tuple[CompanionRosterState, CompanionInstance, bool]:
        person = self.catalog.people.require(person_definition_id)
        active = roster.active_by_definition(person.id)
        if active is not None:
            self._fail("companion.person_joined", "这名人物已经是你的伙伴")
        if len(roster.instances) >= self.catalog.balance.roster_capacity:
            self._fail("companion.roster_full", "伙伴名册已经达到上限")
        bond = roster.person_bonds.get(person.id)
        if bond is None or bond.favor < person.bond_required:
            current = bond.favor if bond is not None else 0
            self._fail(
                "companion.bond_insufficient",
                f"关系尚未达到结交要求：{current}/{person.bond_required}",
            )
        archived = roster.departed_people.get(person.id)
        departed = dict(roster.departed_people)
        if archived is not None:
            instance = archived
            del departed[person.id]
            next_sequence = roster.next_sequence
            restored = True
        else:
            sequence = roster.next_sequence
            instance = CompanionInstance(
                id=f"{roster.character_id}:companion:{sequence}",
                reference=f"C{sequence}",
                owner_id=roster.character_id,
                definition_id=person.id,
                origin_world_id=person.origin_world_id,
                quality_id=person.quality_id,
                level=1,
                experience=0,
                total_experience=0,
                aptitudes=person.aptitudes,
                trait_behavior_id=person.trait_behavior_id,
                kind=CompanionKind.PERSON,
                acquired_at=logical_time,
                acquisition_kind=CompanionAcquisitionKind.PERSON_BOND,
                acquisition_id=str(person.id),
            )
            next_sequence = sequence + 1
            restored = False
        instances = dict(roster.instances)
        instances[instance.id] = instance
        return (
            replace(
                roster,
                instances=instances,
                departed_people=departed,
                next_sequence=next_sequence,
                revision=roster.revision + 1,
            ),
            instance,
            restored,
        )

    def farewell(
        self,
        roster: CompanionRosterState,
        companion_id: str,
    ) -> CompanionRosterState:
        if companion_id not in roster.instances:
            self._fail("companion.unknown", "找不到要告别的伙伴")
        companion = roster.instances[companion_id]
        instances = dict(roster.instances)
        del instances[companion_id]
        bindings = {
            key: value for key, value in roster.bindings.items() if value != companion_id
        }
        departed = dict(roster.departed_people)
        if companion.kind is CompanionKind.PERSON:
            departed[companion.definition_id] = companion
        return replace(
            roster,
            instances=instances,
            bindings=bindings,
            departed_people=departed,
            revision=roster.revision + 1,
        )

    def abandon(
        self,
        sanctuary: CompanionSanctuaryState,
        *,
        logical_time,
    ) -> CompanionSanctuaryState:
        current = self.expire(sanctuary, logical_time=logical_time)
        if not current.active:
            return current
        return replace(
            current,
            status=CompanionSanctuaryStatus.ABANDONED,
            revision=current.revision + 1,
        )

    @staticmethod
    def expire(
        sanctuary: CompanionSanctuaryState,
        *,
        logical_time,
    ) -> CompanionSanctuaryState:
        if sanctuary.active and logical_time >= sanctuary.expires_at:
            return replace(
                sanctuary,
                status=CompanionSanctuaryStatus.EXPIRED,
                revision=sanctuary.revision + 1,
            )
        return sanctuary

    def _trace(
        self,
        index: int,
        species_id: StableId,
        character_level: int,
        session_id: str,
        random: RandomSource,
    ) -> CompanionTrace:
        species = self.catalog.species.require(species_id)
        quality_id = self._weighted_choice(self.catalog.balance.quality_weights, random)
        budget = self.catalog.balance.aptitude_budgets[quality_id]
        aptitudes = self._aptitudes(budget, random)
        return CompanionTrace(
            index,
            species.id,
            quality_id,
            min(self.catalog.balance.maximum_level, max(1, int(character_level))),
            aptitudes,
            random.choice(species.trait_behavior_ids),
            f"{session_id}:trace:{index}",
        )

    def _weighted_unique_species(self, values, count, random):
        remaining = list(values)
        selected = []
        for _ in range(count):
            weights = {
                value: self.catalog.species.require(value).capture_weight
                for value in remaining
            }
            chosen = self._weighted_choice(weights, random)
            selected.append(chosen)
            remaining.remove(chosen)
        return tuple(selected)

    @staticmethod
    def _weighted_choice(weights, random):
        total = sum(int(value) for value in weights.values())
        roll = random.randint(1, total)
        for key, weight in weights.items():
            roll -= int(weight)
            if roll <= 0:
                return key
        raise RuntimeError("伙伴加权随机没有选出结果")

    @staticmethod
    def _aptitudes(budget: int, random: RandomSource):
        values = [random.randint(80, 120) for _ in COMPANION_APTITUDE_IDS]
        result = [60] * len(values)
        remaining = budget - sum(result)
        while remaining > 0:
            candidates = [index for index, value in enumerate(result) if value < 140]
            index = random.choice(candidates)
            weight = max(1, values[index] - 70)
            grant = min(remaining, max(1, weight // 10), 140 - result[index])
            result[index] += grant
            remaining -= grant
        return dict(zip(COMPANION_APTITUDE_IDS, result))

    @staticmethod
    def _fail(code: str, message: str) -> None:
        raise CompanionRuleError(code, message)


__all__ = ["CompanionEngine", "CompanionRuleError"]
