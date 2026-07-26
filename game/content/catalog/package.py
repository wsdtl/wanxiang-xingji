"""汇总稳定名录定义；具体分类定义不得直接写在本文件。"""

from game.core.gameplay import (
    ContentPackage,
    ContentPackageManifest,
    ContentVersion,
    WEAPON_EXPERIENCE_ITEM_COMPONENT_TYPE,
    WEAPON_MAXIMUM_LEVEL_ITEM_COMPONENT_TYPE,
    ITEM_CONTAINER_CAPACITY_COMPONENT_TYPE,
)

from .foundation import (
    BASE_ATTRIBUTES,
    BASE_COMBAT_PROFILES,
    BASE_CURRENCIES,
    BASE_DISPLAY_CONTENT_IDS,
    BASE_QUALITIES,
    BASE_RESOURCES,
    LOADOUT_SLOT_CONTENT_DEFINITIONS,
)
from .character.definitions import (
    CHARACTER_DISPLAY_CONTENT_IDS,
    CHARACTER_FEATURES,
    CHARACTER_LEVEL_PROGRESSION,
    DEFAULT_CHARACTER_TEMPLATE,
)
from .character.recovery import REST_ACTION_DEFINITION, REST_ACTION_ID
from .companion import COMPANION_DISPLAY_DEFINITIONS
from .combat.definitions import (
    BASE_ABILITIES,
    BASE_BATTLE_TARGETING,
    BASE_CONTROLS,
    BASE_DAMAGE_TYPES,
    BASE_EFFECTS,
    COMBAT_DISPLAY_CONTENT_IDS,
)
from .enemy import (
    ENCOUNTER_SCOPES,
    ENEMY_BEHAVIOR_CONTENT,
    ENEMY_DEFINITIONS,
    PERSONAL_ENEMY_ENCOUNTERS,
    SHARED_ENEMY_DISPLAY_CONTENT_IDS,
    ENEMY_LOOT_TABLES,
    ENEMY_RANKS,
    ENEMY_REWARD_PROFILES,
    PARTY_BOSS_LEVEL_PROFILE,
    PARTY_BOSS_REWARD_PROFILE,
    STANDARD_ENEMY_LEVEL_PROFILE,
)
from .item.definitions import ITEM_DISPLAY_CONTENT_IDS, MEDICINE_ITEMS
from .item.breakthrough import BREAKTHROUGH_TOKEN_ITEM, BREAKTHROUGH_TOKEN_ITEM_ID
from .item.draw import DRAW_TICKET_ITEM, DRAW_TICKET_ITEM_ID
from .item.exchange import (
    EQUIPMENT_SET_BLUEPRINT_COMPONENT_TYPE,
    EQUIPMENT_SET_BLUEPRINT_ITEMS,
    EXCHANGE_MATERIAL_ITEM,
)
from .item.special import (
    CHARACTER_EXPERIENCE_ITEM_COMPONENT_TYPE,
    COMPANION_EXPERIENCE_ITEM_COMPONENT_TYPE,
    COMPANION_SANCTUARY_ITEM_COMPONENT_TYPE,
    DIMENSION_SHIFT_ITEM_COMPONENT_TYPE,
    INSCRIPTION_FEATHER_ITEM,
    SPECIAL_ITEMS,
    validate_nacre_item_categories,
)
from .item.trade import ITEM_RECYCLE_COMPONENT_TYPE
from .item.trophies import TROPHY_DISPLAY_CONTENT_IDS, TROPHY_ITEMS
from .equipment.definitions import EQUIPMENT_CATALOG_CONTENT
from .equipment.properties import EQUIPMENT_PROPERTY_CONTENT
from .disaster import (
    DIMENSIONAL_DISASTER_ACTIVITY,
    DIMENSIONAL_DISASTER_CYCLES,
)
from .disaster.combat import (
    DISASTER_ENEMY_LEVEL_PROFILE,
    DISASTER_ENEMY_REWARD_PROFILE,
)
from .character.realms import (
    CHARACTER_REALM_CONTENT_DEFINITIONS,
    CHARACTER_REALM_DISPLAY_IDS,
)
from .weapon.definitions import (
    GENERATED_WEAPON_ITEMS,
    GENERATED_WEAPONS,
    STARTER_WEAPON,
    STARTER_WEAPON_ITEM,
    WEAPON_DISPLAY_CONTENT_IDS,
)
from .weapon.mechanics import WEAPON_MECHANIC_CONTENT
from .world.definitions import (
    LOCATION_DISPLAY_DEFINITIONS,
    SHARED_WORLD_DISPLAY_CONTENT_IDS,
)
from .social import (
    PARTY_INVITATION_REQUEST,
    PARTY_SPARRING_REQUEST,
    PARTY_TYPE_TRIO,
    SPARRING_REQUEST,
)
from .trial import (
    BUILD_TRIAL_LEVEL_PROFILES,
    BUILD_TRIAL_RANK,
    BUILD_TRIAL_REWARD_PROFILE,
    BUILD_TRIAL_TARGETS,
)
from .combat.valuation import BASE_ATTRIBUTE_VALUATIONS, BASE_REFERENCE_VALUATIONS
from .draw import DRAW_CATALOG_CONTENT


CATALOG_PACKAGE_ID = "content.catalog.base"


COMBAT_MECHANISM_DISPLAY_IDS = frozenset(
    str(definition.id)
    for definition in (
        *BASE_DAMAGE_TYPES,
        *BASE_CONTROLS,
        *BASE_EFFECTS,
        *WEAPON_MECHANIC_CONTENT.effects,
        *EQUIPMENT_PROPERTY_CONTENT.effects,
        *WEAPON_MECHANIC_CONTENT.triggers,
        *EQUIPMENT_PROPERTY_CONTENT.triggers,
        *WEAPON_MECHANIC_CONTENT.interceptors,
        *WEAPON_MECHANIC_CONTENT.constraints,
    )
)


OFFICIAL_ITEMS = (
    *MEDICINE_ITEMS,
    INSCRIPTION_FEATHER_ITEM,
    DRAW_TICKET_ITEM,
    BREAKTHROUGH_TOKEN_ITEM,
    *SPECIAL_ITEMS,
    EXCHANGE_MATERIAL_ITEM,
    *EQUIPMENT_SET_BLUEPRINT_ITEMS,
    *TROPHY_ITEMS,
    STARTER_WEAPON_ITEM,
    *GENERATED_WEAPON_ITEMS,
    *EQUIPMENT_CATALOG_CONTENT.items,
)
validate_nacre_item_categories(OFFICIAL_ITEMS)


CATALOG_PACKAGE = ContentPackage(
    manifest=ContentPackageManifest(
        id=CATALOG_PACKAGE_ID,
        version=ContentVersion(3, 32, 0),
    ),
    item_component_types=(
        ITEM_RECYCLE_COMPONENT_TYPE,
        CHARACTER_EXPERIENCE_ITEM_COMPONENT_TYPE,
        COMPANION_EXPERIENCE_ITEM_COMPONENT_TYPE,
        WEAPON_MAXIMUM_LEVEL_ITEM_COMPONENT_TYPE,
        WEAPON_EXPERIENCE_ITEM_COMPONENT_TYPE,
        ITEM_CONTAINER_CAPACITY_COMPONENT_TYPE,
        DIMENSION_SHIFT_ITEM_COMPONENT_TYPE,
        COMPANION_SANCTUARY_ITEM_COMPONENT_TYPE,
        EQUIPMENT_SET_BLUEPRINT_COMPONENT_TYPE,
    ),
    display_definitions=(
        *CHARACTER_REALM_CONTENT_DEFINITIONS,
        *LOADOUT_SLOT_CONTENT_DEFINITIONS,
        *COMPANION_DISPLAY_DEFINITIONS,
        *LOCATION_DISPLAY_DEFINITIONS,
    ),
    currencies=BASE_CURRENCIES,
    qualities=BASE_QUALITIES,
    attributes=BASE_ATTRIBUTES,
    resources=BASE_RESOURCES,
    character_features=CHARACTER_FEATURES,
    progressions=(CHARACTER_LEVEL_PROGRESSION,),
    actions=(REST_ACTION_DEFINITION,),
    activities=(DIMENSIONAL_DISASTER_ACTIVITY,),
    cycles=DIMENSIONAL_DISASTER_CYCLES,
    character_templates=(DEFAULT_CHARACTER_TEMPLATE,),
    enemy_level_profiles=(
        STANDARD_ENEMY_LEVEL_PROFILE,
        PARTY_BOSS_LEVEL_PROFILE,
        DISASTER_ENEMY_LEVEL_PROFILE,
        *BUILD_TRIAL_LEVEL_PROFILES,
    ),
    enemy_ranks=(*ENEMY_RANKS, BUILD_TRIAL_RANK),
    enemy_behaviors=ENEMY_BEHAVIOR_CONTENT.behaviors,
    enemy_reward_profiles=(
        *ENEMY_REWARD_PROFILES,
        PARTY_BOSS_REWARD_PROFILE,
        DISASTER_ENEMY_REWARD_PROFILE,
        BUILD_TRIAL_REWARD_PROFILE,
    ),
    enemies=(
        *ENEMY_DEFINITIONS,
        *BUILD_TRIAL_TARGETS,
    ),
    encounter_scopes=ENCOUNTER_SCOPES,
    enemy_encounters=PERSONAL_ENEMY_ENCOUNTERS,
    items=OFFICIAL_ITEMS,
    weapons=(STARTER_WEAPON, *GENERATED_WEAPONS),
    equipment_families=EQUIPMENT_CATALOG_CONTENT.families,
    equipment_sets=EQUIPMENT_CATALOG_CONTENT.sets,
    equipment=EQUIPMENT_CATALOG_CONTENT.equipment,
    attribute_valuations=BASE_ATTRIBUTE_VALUATIONS,
    reference_valuations=(
        *BASE_REFERENCE_VALUATIONS,
        *WEAPON_MECHANIC_CONTENT.reference_valuations,
        *EQUIPMENT_PROPERTY_CONTENT.reference_valuations,
        *ENEMY_BEHAVIOR_CONTENT.reference_valuations,
    ),
    random_properties=(
        *WEAPON_MECHANIC_CONTENT.properties,
        *EQUIPMENT_PROPERTY_CONTENT.properties,
    ),
    generation_profiles=(
        *WEAPON_MECHANIC_CONTENT.profiles,
        *EQUIPMENT_PROPERTY_CONTENT.profiles,
    ),
    combat_profiles=BASE_COMBAT_PROFILES,
    damage_types=BASE_DAMAGE_TYPES,
    controls=BASE_CONTROLS,
    effects=(
        *BASE_EFFECTS,
        *WEAPON_MECHANIC_CONTENT.effects,
        *EQUIPMENT_PROPERTY_CONTENT.effects,
        *ENEMY_BEHAVIOR_CONTENT.effects,
    ),
    abilities=(
        *BASE_ABILITIES,
        *WEAPON_MECHANIC_CONTENT.abilities,
        *ENEMY_BEHAVIOR_CONTENT.abilities,
    ),
    battle_ability_targeting=(
        *BASE_BATTLE_TARGETING,
        *WEAPON_MECHANIC_CONTENT.targeting,
        *ENEMY_BEHAVIOR_CONTENT.targeting,
    ),
    triggers=(
        *WEAPON_MECHANIC_CONTENT.triggers,
        *EQUIPMENT_PROPERTY_CONTENT.triggers,
        *ENEMY_BEHAVIOR_CONTENT.triggers,
    ),
    interceptors=WEAPON_MECHANIC_CONTENT.interceptors,
    target_constraints=WEAPON_MECHANIC_CONTENT.constraints,
    loot_tables=(*ENEMY_LOOT_TABLES, DRAW_CATALOG_CONTENT.loot_table),
    draw_pools=(DRAW_CATALOG_CONTENT.pool,),
    social_request_types=(
        SPARRING_REQUEST,
        PARTY_INVITATION_REQUEST,
        PARTY_SPARRING_REQUEST,
    ),
    party_types=(PARTY_TYPE_TRIO,),
    display_content_ids=(
        BASE_DISPLAY_CONTENT_IDS
        | CHARACTER_DISPLAY_CONTENT_IDS
        | CHARACTER_REALM_DISPLAY_IDS
        | COMBAT_DISPLAY_CONTENT_IDS
        | COMBAT_MECHANISM_DISPLAY_IDS
        | ITEM_DISPLAY_CONTENT_IDS
        | TROPHY_DISPLAY_CONTENT_IDS
        | WEAPON_DISPLAY_CONTENT_IDS
        | EQUIPMENT_CATALOG_CONTENT.display_ids
        | EQUIPMENT_PROPERTY_CONTENT.display_ids
        | SHARED_ENEMY_DISPLAY_CONTENT_IDS
        | {DRAW_TICKET_ITEM_ID}
        | {BREAKTHROUGH_TOKEN_ITEM_ID}
        | {str(value.id) for value in SPECIAL_ITEMS}
        | {str(EXCHANGE_MATERIAL_ITEM.id)}
        | {str(value.id) for value in EQUIPMENT_SET_BLUEPRINT_ITEMS}
        | {REST_ACTION_ID}
        | {str(value.id) for value in COMPANION_DISPLAY_DEFINITIONS}
        | SHARED_WORLD_DISPLAY_CONTENT_IDS
    ),
)


__all__ = [
    "CATALOG_PACKAGE",
    "CATALOG_PACKAGE_ID",
    "COMBAT_MECHANISM_DISPLAY_IDS",
]
