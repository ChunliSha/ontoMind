"""Business-logic topology: type registry, graph contract, index, mapping."""

from app.topology.index import OntologyIndex
from app.topology.node_types import (
    DEFAULT_NODE_TYPES,
    LAYOUT_X_STEP,
    LAYOUT_Y_STEP,
    UNGROUNDED_OBJECT_ID,
    UNGROUNDED_TYPE,
    NodeTypeRegistry,
    NodeTypeSpec,
    PropertyFieldSpec,
    color_for_class,
    get_default_registry,
)
from app.topology.type_mapping import suggest_type_mapping

__all__ = [
    "DEFAULT_NODE_TYPES",
    "LAYOUT_X_STEP",
    "LAYOUT_Y_STEP",
    "UNGROUNDED_OBJECT_ID",
    "UNGROUNDED_TYPE",
    "color_for_class",
    "NodeTypeRegistry",
    "NodeTypeSpec",
    "OntologyIndex",
    "PropertyFieldSpec",
    "get_default_registry",
    "suggest_type_mapping",
]
