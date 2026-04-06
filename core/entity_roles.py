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
