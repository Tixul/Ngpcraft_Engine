"""
core/entity_roles.py - Shared gameplay-role helpers for sprite-backed entity types.
"""

from __future__ import annotations

from pathlib import Path


ROLE_VALUES: tuple[str, ...] = (
    "player",
    "enemy",
    "item",
    "npc",
    "trigger",
    "platform",
    "block",
    "prop",
)

ROLE_VALUES_WITH_NONE: tuple[str, ...] = ("none",) + ROLE_VALUES


def normalize_gameplay_role(value: object, default: str = "prop") -> str:
    role = str(value or "").strip().lower()
    return role if role in ROLE_VALUES else default


def sprite_type_name(sprite: dict) -> str:
    if not isinstance(sprite, dict):
        return ""
    raw = str(sprite.get("name") or "").strip()
    if raw:
        return raw
    raw = str(sprite.get("file") or "").strip()
    return Path(raw).stem if raw else ""


def sprite_gameplay_role(sprite: dict, legacy_role: object = None, default: str = "prop") -> str:
    if not isinstance(sprite, dict):
        return default
    role = normalize_gameplay_role(sprite.get("gameplay_role"), "")
    if role:
        return role
    role = normalize_gameplay_role(legacy_role, "")
    if role:
        return role
    ctrl = sprite.get("ctrl") or {}
    return normalize_gameplay_role(ctrl.get("role"), default)


def scene_role_map(scene: dict | None) -> dict[str, str]:
    if not isinstance(scene, dict):
        return {}
    legacy = dict(scene.get("entity_roles", {}) or {})
    roles: dict[str, str] = {}
    for sprite in scene.get("sprites", []) or []:
        type_name = sprite_type_name(sprite)
        if not type_name:
            continue
        roles[type_name] = sprite_gameplay_role(sprite, legacy.get(type_name))
    for type_name, legacy_role in legacy.items():
        name = str(type_name or "").strip()
        if name and name not in roles:
            roles[name] = normalize_gameplay_role(legacy_role)
    return roles


def scene_role(scene: dict | None, type_name: str, default: str = "prop") -> str:
    name = str(type_name or "").strip()
    if not name:
        return default
    return scene_role_map(scene).get(name, default)


def migrate_scene_sprite_roles(scene: dict | None) -> dict[str, str]:
    roles = scene_role_map(scene)
    if not isinstance(scene, dict):
        return roles
    for sprite in scene.get("sprites", []) or []:
        type_name = sprite_type_name(sprite)
        if not type_name:
            continue
        sprite["gameplay_role"] = roles.get(type_name, "prop")
    if "entity_roles" in scene:
        del scene["entity_roles"]
    return roles


def set_scene_sprite_role(scene: dict | None, type_name: str, role: object) -> str:
    name = str(type_name or "").strip()
    resolved = normalize_gameplay_role(role)
    if not isinstance(scene, dict) or not name:
        return resolved
    for sprite in scene.get("sprites", []) or []:
        if sprite_type_name(sprite) == name:
            sprite["gameplay_role"] = resolved
    if "entity_roles" in scene:
        del scene["entity_roles"]
    return resolved


def entity_override_role(entity: dict) -> str:
    """Return the per-instance role override stored on an entity, or '' if none.

    The override is stored in entity["role"]. Empty string / invalid values fall
    back to the sprite-type role at callsites that care about the effective role.
    """
    if not isinstance(entity, dict):
        return ""
    raw = str(entity.get("role") or "").strip().lower()
    return raw if raw in ROLE_VALUES else ""


def entity_effective_role(scene: dict | None, entity: dict, default: str = "prop") -> str:
    """Resolve the gameplay role that actually applies to a given entity instance.

    Priority: explicit entity-level override > sprite-type role > default.
    """
    ov = entity_override_role(entity)
    if ov:
        return ov
    type_name = str((entity or {}).get("type", "") or "").strip()
    return scene_role(scene, type_name, default=default)


def set_entity_role_override(entity: dict, role: object) -> str:
    """Store or clear a per-instance role override on an entity.

    Pass an empty/None/'none' role to clear the override. Returns the normalized
    value that was stored, or '' when the override was cleared.
    """
    if not isinstance(entity, dict):
        return ""
    raw = str(role or "").strip().lower()
    if raw in ("", "none"):
        entity.pop("role", None)
        return ""
    if raw not in ROLE_VALUES:
        entity.pop("role", None)
        return ""
    entity["role"] = raw
    return raw
