"""把组队首领掉落翻译成每名玩家的统一奖励规格。"""

from __future__ import annotations

from dataclasses import dataclass

from game.content.catalog import CHARACTER_LEVEL_PROGRESSION_ID, DRAW_TICKET_ITEM_ID
from game.content.catalog.enemy import (
    AWARD_DRAW_TICKET_ID,
    AWARD_LARGE_HEALTH_MEDICINE_ID,
    AWARD_LARGE_SPIRIT_MEDICINE_ID,
    AWARD_MEDIUM_HEALTH_MEDICINE_ID,
    AWARD_MEDIUM_SPIRIT_MEDICINE_ID,
    AWARD_PARTY_BOSS_TROPHY_ID,
    AWARD_RANDOM_EQUIPMENT_ID,
    AWARD_RANDOM_WEAPON_ID,
)
from game.content.catalog.item import (
    LARGE_HEALTH_MEDICINE_ITEM_ID,
    LARGE_SPIRIT_MEDICINE_ITEM_ID,
    MEDIUM_HEALTH_MEDICINE_ITEM_ID,
    MEDIUM_SPIRIT_MEDICINE_ITEM_ID,
)
from game.content.catalog.weapon.mechanics import WEAPON_MAXIMUM_LEVEL_TABLE
from game.core.gameplay import (
    CharacterExperienceReward,
    GeneratedEquipmentReward,
    GeneratedWeaponReward,
    StackItemReward,
    WeaponExperienceReward,
)
from game.rules.equipment import EquipmentGenerationRequest, EquipmentInstanceGenerator
from game.rules.weapon import WeaponGenerationRequest, WeaponInstanceGenerator


_MEDICINE_AWARDS = {
    AWARD_MEDIUM_HEALTH_MEDICINE_ID: MEDIUM_HEALTH_MEDICINE_ITEM_ID,
    AWARD_MEDIUM_SPIRIT_MEDICINE_ID: MEDIUM_SPIRIT_MEDICINE_ITEM_ID,
    AWARD_LARGE_HEALTH_MEDICINE_ID: LARGE_HEALTH_MEDICINE_ITEM_ID,
    AWARD_LARGE_SPIRIT_MEDICINE_ID: LARGE_SPIRIT_MEDICINE_ITEM_ID,
}


@dataclass(frozen=True)
class PartyBattleRewardReference:
    kind: str
    definition_id: str
    quantity: int = 1
    asset_id: str | None = None


@dataclass(frozen=True)
class PartyBattleRewardBuild:
    rewards: tuple[object, ...]
    references: tuple[PartyBattleRewardReference, ...]
    weapon_experience_asset_id: str | None = None


class PartyBattleRewardFactory:
    def __init__(self, content) -> None:
        self.content = content
        self.party_boss_trophy_item_ids = content.party_boss_trophy_item_ids
        catalog = content.catalog
        self.weapon_generator = WeaponInstanceGenerator(
            catalog.weapons,
            catalog.itemization_engine,
            WEAPON_MAXIMUM_LEVEL_TABLE,
        )
        self.equipment_generator = EquipmentInstanceGenerator(
            catalog.equipment,
            catalog.itemization_engine,
        )

    def build(
        self,
        awards,
        *,
        session_id: str,
        character,
        inventory,
        loadout,
        enemy_definition_id: str,
        character_experience: int,
        weapon_experience: int,
        first_clear: bool,
        context,
    ) -> PartyBattleRewardBuild:
        armory_id = _container_id(inventory, "container.armory")
        backpack_id = _container_id(inventory, "container.backpack")
        special_id = _container_id(inventory, "container.special")
        rewards: list[object] = [
            CharacterExperienceReward(
                character.id,
                CHARACTER_LEVEL_PROGRESSION_ID,
                character_experience,
            )
        ]
        weapon_asset_id = loadout.weapon_asset_id
        if weapon_asset_id is not None and weapon_experience > 0:
            rewards.append(WeaponExperienceReward(weapon_asset_id, weapon_experience))

        references: list[PartyBattleRewardReference] = []
        stack_quantities: dict[str, int] = {}
        weapon_ids = tuple(
            definition_id
            for definition_id in self.content.catalog.weapons.definitions.ids()
            if self.content.catalog.weapons.require(definition_id).generation_profile_id is not None
        )
        equipment_ids = self.content.catalog.equipment.definitions.ids()
        sequence = 0
        for award in awards:
            for _ in range(award.quantity):
                asset_id = f"asset:{session_id}:{character.id}:party-reward:{sequence}"
                if award.award_id == AWARD_RANDOM_WEAPON_ID:
                    definition_id = context.random.choice(weapon_ids)
                    generated = self.weapon_generator.generate(
                        WeaponGenerationRequest(
                            f"{session_id}:{character.id}:weapon:{sequence}",
                            asset_id,
                            definition_id,
                            self.content.catalog.report.content_fingerprint,
                        ),
                        context=context,
                    ).state
                    definition = self.content.catalog.weapons.require(definition_id)
                    rewards.append(
                        GeneratedWeaponReward(
                            generated,
                            definition.item_definition_id,
                            armory_id,
                        )
                    )
                    references.append(
                        PartyBattleRewardReference(
                            "weapon",
                            generated.definition_id,
                            asset_id=generated.asset_id,
                        )
                    )
                elif award.award_id == AWARD_RANDOM_EQUIPMENT_ID:
                    definition_id = context.random.choice(equipment_ids)
                    generated = self.equipment_generator.generate(
                        EquipmentGenerationRequest(
                            f"{session_id}:{character.id}:equipment:{sequence}",
                            asset_id,
                            definition_id,
                            self.content.catalog.report.content_fingerprint,
                        ),
                        context=context,
                    ).state
                    definition = self.content.catalog.equipment.require(definition_id)
                    rewards.append(
                        GeneratedEquipmentReward(
                            generated,
                            definition.item_definition_id,
                            armory_id,
                        )
                    )
                    references.append(
                        PartyBattleRewardReference(
                            "equipment",
                            generated.definition_id,
                            asset_id=generated.asset_id,
                        )
                    )
                else:
                    definition_id = self._stack_definition(
                        award.award_id,
                        enemy_definition_id,
                    )
                    stack_quantities[definition_id] = stack_quantities.get(definition_id, 0) + 1
                sequence += 1

        if first_clear:
            stack_quantities[DRAW_TICKET_ITEM_ID] = stack_quantities.get(DRAW_TICKET_ITEM_ID, 0) + 1

        for definition_id, quantity in sorted(stack_quantities.items()):
            definition = self.content.catalog.items.require(definition_id)
            container_id = backpack_id if definition.tags.has("storage.backpack") else special_id
            existing = next(
                (
                    value
                    for value in inventory.stacks.values()
                    if value.definition_id == definition_id and value.container_id == container_id
                ),
                None,
            )
            rewards.append(
                StackItemReward(
                    existing.id if existing is not None else f"stack:{character.id}:{definition_id}",
                    definition_id,
                    container_id,
                    quantity,
                )
            )
            references.append(
                PartyBattleRewardReference("item", definition_id, quantity)
            )
        return PartyBattleRewardBuild(
            tuple(rewards),
            tuple(references),
            weapon_asset_id if weapon_experience > 0 else None,
        )

    def _stack_definition(self, award_id: str, enemy_definition_id: str) -> str:
        if award_id == AWARD_PARTY_BOSS_TROPHY_ID:
            try:
                return self.party_boss_trophy_item_ids[enemy_definition_id]
            except KeyError as exc:
                raise KeyError(
                    f"组队首领没有登记战利品：{enemy_definition_id}"
                ) from exc
        if award_id == AWARD_DRAW_TICKET_ID:
            return DRAW_TICKET_ITEM_ID
        if award_id in _MEDICINE_AWARDS:
            return _MEDICINE_AWARDS[award_id]
        raise KeyError(f"组队首领奖励包含未知奖励声明：{award_id}")


def _container_id(inventory, kind: str) -> str:
    return next(value.id for value in inventory.containers.values() if value.kind == kind)


__all__ = [
    "PartyBattleRewardBuild",
    "PartyBattleRewardFactory",
    "PartyBattleRewardReference",
]
