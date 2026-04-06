"""
core/entity_types.py — Project-global entity type archetypes.

An entity type defines default properties (role, behavior, AI params, etc.)
that scene instances can inherit. Instances stored in scenes keep their own
explicit values and are not automatically rewritten when a type changes —
the type is a creation-time preset, not a live binding.

Public API:
    ROLE_VALUES        — tuple of valid role strings
    BEHAVIOR_LABELS    — (internal_value, display_label) pairs
    DIRECTION_LABELS   — (internal_value, display_label) pairs
    ET_DEFAULTS        — default field values for a new type

    new_entity_type(name) -> dict
    get_entity_types(project_data) -> list[dict]
    get_entity_type_by_id(project_data, type_id) -> dict | None
"""

from __future__ import annotations

from core.entity_roles import ROLE_VALUES


# (stored_value, display label)
BEHAVIOR_LABELS: tuple[tuple[int, str], ...] = (
    (0, "Patrol"),
    (1, "Chase"),
    (2, "Fixed"),
    (3, "Random"),
)

DIRECTION_LABELS: tuple[tuple[int, str], ...] = (
    (0, "Droite (0)"),
    (1, "Haut (1)"),
    (2, "Gauche (2)"),
    (3, "Bas (3)"),
)

# Default values stored in every new archetype
ET_DEFAULTS: dict[str, object] = {
    "role":            "enemy",
    "behavior":        0,
    "ai_speed":        1,
    "ai_range":        10,
    "ai_lose_range":   16,
    "ai_change_every": 60,
    "direction":       0,
    "data":            0,
    "flags":           0,
}


def new_entity_type(name: str) -> dict:
    """Return a fresh entity type dict with all defaults."""
    safe = str(name or "").strip().replace(" ", "_") or "type"
    return {"id": f"etype_{safe}", "name": safe, **ET_DEFAULTS}


def get_entity_types(project_data: dict) -> list[dict]:
    """Return the entity_types list from project_data, or []."""
    if not isinstance(project_data, dict):
        return []
    types = project_data.get("entity_types", [])
    return types if isinstance(types, list) else []


def get_entity_type_by_id(project_data: dict, type_id: str) -> dict | None:
    """Find an entity type by its id field."""
    for t in get_entity_types(project_data):
        if isinstance(t, dict) and t.get("id") == type_id:
            return t
    return None
