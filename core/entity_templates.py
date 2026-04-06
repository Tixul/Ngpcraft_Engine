"""
core/entity_templates.py — Project-global entity templates (prefabs).

An entity template is a full snapshot of an entity's characteristics:
  - Sprite reference (file, frame dimensions)
  - Hitbox data (hurtboxes, attack hitboxes)
  - Physics props (gravity, speed, jump_force, ...)
  - Control scheme (ctrl dict)
  - Animations (anims, named_anims, motion_patterns)
  - Gameplay role
  - Behavior / AI parameters

Templates live in project_data["entity_templates"]. They are the "master
version" of an entity. Instances in scenes are independent snapshots — they
are not auto-updated when the template changes. The user explicitly applies
a template to pull master values into a scene instance.

Backward-compat: project_data["entity_types"] (old behavior-only archetypes)
are still readable via get_entity_types() in entity_types.py. New code should
use entity_templates. Migration happens lazily: when a template is saved it
goes into entity_templates[]; entity_types[] is left intact for old data.

Public API:
    TEMPLATE_SPRITE_KEYS   — keys copied from/to a scene sprite dict
    TEMPLATE_BEHAVIOR_KEYS — keys copied from/to an entity instance dict

    new_entity_template(name, sprite_meta=None, behavior_params=None) -> dict
    snapshot_sprite_fields(sprite_meta) -> dict
    apply_template_to_scene_sprite(template, scene_sprite) -> None
    apply_template_to_entity(template, entity_instance) -> None
    find_template_for_file(project_data, file_rel) -> dict | None

    get_entity_templates(project_data) -> list[dict]
    get_entity_template_by_id(project_data, tpl_id) -> dict | None
"""

from __future__ import annotations

import copy
import uuid

from core.entity_roles import ROLE_VALUES
from core.entity_types import BEHAVIOR_LABELS, DIRECTION_LABELS, ET_DEFAULTS


# ---------------------------------------------------------------------------
# Field sets
# ---------------------------------------------------------------------------

# Keys that describe the visual / hitbox side of an entity (from scene sprite)
TEMPLATE_SPRITE_KEYS: tuple[str, ...] = (
    "file",
    "frame_w",
    "frame_h",
    "hurtboxes",
    "hitboxes",           # legacy sync copy — kept for compat
    "hitboxes_attack_multi",
    "hitboxes_attack",    # legacy sync copy — kept for compat
    "props",
    "ctrl",
    "anims",
    "named_anims",
    "motion_patterns",
    "dir_frames",
    "gameplay_role",
)

# Keys that describe the gameplay / AI side of an entity (from entity instance)
TEMPLATE_BEHAVIOR_KEYS: tuple[str, ...] = (
    "behavior",
    "ai_speed",
    "ai_range",
    "ai_lose_range",
    "ai_change_every",
    "direction",
    "data",
    "flags",
)

# Re-export so callers can import everything from one place
__all__ = [
    "TEMPLATE_SPRITE_KEYS",
    "TEMPLATE_BEHAVIOR_KEYS",
    "BEHAVIOR_LABELS",
    "DIRECTION_LABELS",
    "ROLE_VALUES",
    "ET_DEFAULTS",
    "new_entity_template",
    "snapshot_sprite_fields",
    "apply_template_to_scene_sprite",
    "apply_template_to_entity",
    "find_template_for_file",
    "get_entity_templates",
    "get_entity_template_by_id",
]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def new_entity_template(
    name: str,
    sprite_meta: dict | None = None,
    behavior_params: dict | None = None,
) -> dict:
    """Return a fresh entity template dict.

    Args:
        name:            Human-readable name (spaces → underscores).
        sprite_meta:     Scene sprite dict to snapshot visual data from.
        behavior_params: Dict with behavior/AI keys to override ET_DEFAULTS.
    """
    safe = str(name or "").strip().replace(" ", "_") or "template"
    tpl: dict = {
        "id":   f"etpl_{safe}_{uuid.uuid4().hex[:6]}",
        "name": safe,
        # Role — pulled from sprite_meta["gameplay_role"] if available
        "role": "enemy",
        **ET_DEFAULTS,
    }

    if sprite_meta:
        tpl.update(snapshot_sprite_fields(sprite_meta))
        role = sprite_meta.get("gameplay_role") or sprite_meta.get("ctrl", {}).get("role", "")
        if role:
            tpl["role"] = role

    if behavior_params:
        for k in TEMPLATE_BEHAVIOR_KEYS:
            if k in behavior_params:
                tpl[k] = behavior_params[k]
        if "role" in behavior_params:
            tpl["role"] = behavior_params["role"]

    return tpl


# ---------------------------------------------------------------------------
# Snapshot / apply helpers
# ---------------------------------------------------------------------------

def snapshot_sprite_fields(sprite_meta: dict) -> dict:
    """Return a deep copy of all TEMPLATE_SPRITE_KEYS present in sprite_meta."""
    return {
        k: copy.deepcopy(sprite_meta[k])
        for k in TEMPLATE_SPRITE_KEYS
        if k in sprite_meta
    }


def apply_template_to_scene_sprite(template: dict, scene_sprite: dict) -> None:
    """Copy TEMPLATE_SPRITE_KEYS from *template* into *scene_sprite* (in-place).

    Only keys present in the template are written — missing keys are not
    cleared from the target sprite.
    """
    for k in TEMPLATE_SPRITE_KEYS:
        if k in template:
            scene_sprite[k] = copy.deepcopy(template[k])


def apply_template_to_entity(template: dict, entity_instance: dict) -> None:
    """Copy TEMPLATE_BEHAVIOR_KEYS + role from *template* into *entity_instance*.

    gameplay_role is NOT written to entity instances (it lives on the sprite).
    Only behavior/AI keys are applied.
    """
    for k in TEMPLATE_BEHAVIOR_KEYS:
        if k in template:
            entity_instance[k] = template[k]


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def find_template_for_file(project_data: dict, file_rel: str) -> dict | None:
    """Return the first template whose 'file' field matches *file_rel*, or None."""
    if not file_rel:
        return None
    for tpl in get_entity_templates(project_data):
        if isinstance(tpl, dict) and tpl.get("file") == file_rel:
            return tpl
    return None


def get_entity_templates(project_data: dict) -> list[dict]:
    """Return the entity_templates list from project_data, or []."""
    if not isinstance(project_data, dict):
        return []
    tpls = project_data.get("entity_templates", [])
    return tpls if isinstance(tpls, list) else []


def get_entity_template_by_id(project_data: dict, tpl_id: str) -> dict | None:
    """Find an entity template by its id field."""
    for tpl in get_entity_templates(project_data):
        if isinstance(tpl, dict) and tpl.get("id") == tpl_id:
            return tpl
    return None
