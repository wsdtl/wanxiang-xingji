"""把角色当前配装统一投影为实际战斗实体。"""

from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from game.core.gameplay import (
    AttributeResolver,
    CharacterContribution,
    CharacterProjection,
    CharacterProjector,
    CharacterState,
    EquipmentContributionProvider,
    InventoryState,
    LoadoutState,
    ResourceDefinition,
    RuleEntity,
    TagSet,
    WeaponContributionProvider,
    equipment_state_from_instance,
    weapon_state_from_instance,
)


class PlayerCombatProjector:
    """探险、活动和面板共用的玩家战斗构筑入口。"""

    def __init__(self, content, character_projector: CharacterProjector) -> None:
        self.content = content
        self.character_projector = character_projector
        self.attributes = character_projector.attributes
        self.weapon_contributions = WeaponContributionProvider(content.weapons)
        self.equipment_contributions = EquipmentContributionProvider(content.equipment)

    def project(
        self,
        character: CharacterState,
        inventory: InventoryState,
        loadout: LoadoutState,
        *,
        context_tags: TagSet = TagSet(),
        extra_contributions: tuple[CharacterContribution, ...] = (),
    ) -> CharacterProjection:
        """汇总当前七槽、随机词条与套装后生成唯一最终投影。"""

        if character.id != loadout.character_id:
            raise ValueError("角色与配装归属不一致")
        for asset_id in loadout.slots.values():
            if inventory.owner_of(asset_id) != character.id:
                raise ValueError("当前配装引用了不属于角色的资产")
        contributions: list[CharacterContribution] = []
        if loadout.weapon_asset_id is not None:
            contributions.append(
                self.weapon_contributions.contribution(
                    weapon_state_from_instance(
                        inventory.instances[loadout.weapon_asset_id]
                    )
                )
            )
        equipment = tuple(
            equipment_state_from_instance(inventory.instances[asset_id])
            for asset_id in loadout.equipment_asset_ids
        )
        contributions.extend(self.equipment_contributions.contributions(equipment))
        contributions.extend(extra_contributions)
        return self.character_projector.project(
            character,
            contributions=tuple(contributions),
            context_tags=context_tags,
        )


def fully_restored_entity(
    entity: RuleEntity,
    resources: Mapping[str, ResourceDefinition],
    attributes: AttributeResolver,
) -> RuleEntity:
    """返回战斗资源按当前投影上限填满的实体副本。"""

    snapshot = entity.snapshot(attributes)
    restored = {}
    for resource_id, definition in resources.items():
        if definition.maximum_attribute is not None:
            restored[resource_id] = snapshot.value(definition.maximum_attribute)
        elif definition.fixed_maximum is not None:
            restored[resource_id] = definition.fixed_maximum
        else:
            restored[resource_id] = definition.minimum
    return replace(entity, resources=restored)


__all__ = ["PlayerCombatProjector", "fully_restored_entity"]
