"""协议、存储和具体玩法无关的随机物品化底座。"""

ITEMIZATION_FOUNDATION_VERSION = "itemization.foundation.v2"

from .engine import GENERATOR_VERSION, ItemizationCatalog, ItemizationEngine
from .models import (
    GenerationDecision,
    GenerationProfileDefinition,
    GenerationReceipt,
    ItemGenerationCommand,
    ItemGenerationExecution,
    ItemRollState,
    ItemizationKind,
    PropertyDefinition,
    PropertyParameterDefinition,
    PropertyTierDefinition,
    QualityValueBand,
    RolledProperty,
)

__all__ = [
    "GENERATOR_VERSION",
    "ITEMIZATION_FOUNDATION_VERSION",
    "GenerationDecision",
    "GenerationProfileDefinition",
    "GenerationReceipt",
    "ItemGenerationCommand",
    "ItemGenerationExecution",
    "ItemRollState",
    "ItemizationCatalog",
    "ItemizationEngine",
    "ItemizationKind",
    "PropertyDefinition",
    "PropertyParameterDefinition",
    "PropertyTierDefinition",
    "QualityValueBand",
    "RolledProperty",
]
