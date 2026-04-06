from __future__ import annotations

from typing import Iterable

HURTBOX_KEY = "hurtboxes"
BODYBOX_KEY = "bodyboxes"
LEGACY_HITBOX_KEY = "hitboxes"
ATTACK_HITBOX_KEY = "hitboxes_attack"
ATTACK_HITBOX_ALT_KEY = "attack_hitboxes"
ATTACK_HITBOX_MULTI_KEY = "hitboxes_attack_multi"


def default_box(frame_w: int, frame_h: int) -> dict:
    fw = max(1, int(frame_w or 1))
    fh = max(1, int(frame_h or 1))
    return {
        "x": -(fw // 2),
        "y": -(fh // 2),
        "w": fw,
        "h": fh,
        "enabled": True,
    }


def _axis_bounds(frame_size: int) -> tuple[int, int]:
    lo = -(max(1, int(frame_size or 1)) // 2)
    return lo, lo + max(1, int(frame_size or 1))


def _recenter_axis(size: int) -> int:
    return -(max(1, int(size or 1)) // 2)


def _box_entirely_outside_frame(box: dict, frame_w: int, frame_h: int) -> tuple[bool, bool]:
    x = int(box.get("x", 0) or 0)
    y = int(box.get("y", 0) or 0)
    w = max(1, int(box.get("w", 1) or 1))
    h = max(1, int(box.get("h", 1) or 1))
    x_lo, x_hi = _axis_bounds(frame_w)
    y_lo, y_hi = _axis_bounds(frame_h)
    outside_x = (x + w) <= x_lo or x >= x_hi
    outside_y = (y + h) <= y_lo or y >= y_hi
    return outside_x, outside_y


def normalize_box(box: object, fallback: dict, *, frame_w: int | None = None, frame_h: int | None = None, coerce_into_frame: bool = False) -> dict:
    src = box if isinstance(box, dict) else {}
    def _pick_num(key: str, default: int) -> int:
        val = src.get(key, default)
        return default if val is None else int(val)
    out = {
        "x": _pick_num("x", int(fallback["x"])),
        "y": _pick_num("y", int(fallback["y"])),
        "w": max(1, _pick_num("w", int(fallback["w"]))),
        "h": max(1, _pick_num("h", int(fallback["h"]))),
        "enabled": bool(src.get("enabled", fallback.get("enabled", True))),
    }
    if coerce_into_frame and frame_w is not None and frame_h is not None:
        # Compatibility path: older projects could store hurtboxes relative to
        # the whole sprite sheet instead of a single frame. When the box ends
        # up completely outside the current frame, re-center it within the frame
        # while preserving its size instead of exporting a wildly offset sprite.
        outside_x, outside_y = _box_entirely_outside_frame(out, frame_w, frame_h)
        if outside_x:
            out["x"] = _recenter_axis(out["w"])
        if outside_y:
            out["y"] = _recenter_axis(out["h"])
    return out


def _normalize_box_list(raw: object, fallback: dict, *, frame_w: int | None = None, frame_h: int | None = None, coerce_into_frame: bool = False) -> list[dict]:
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes, dict)):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(normalize_box(item, fallback, frame_w=frame_w, frame_h=frame_h, coerce_into_frame=coerce_into_frame))
    return out


def sprite_hurtboxes(sprite: dict, frame_w: int, frame_h: int) -> list[dict]:
    fallback = default_box(frame_w, frame_h)
    raw = sprite.get(HURTBOX_KEY)
    if not raw:
        raw = sprite.get(LEGACY_HITBOX_KEY)
    return _normalize_box_list(raw, fallback, frame_w=frame_w, frame_h=frame_h, coerce_into_frame=True)


def sprite_bodyboxes(sprite: dict, frame_w: int, frame_h: int) -> list[dict]:
    fallback = default_box(frame_w, frame_h)
    raw = sprite.get(BODYBOX_KEY)
    if raw:
        return _normalize_box_list(raw, fallback, frame_w=frame_w, frame_h=frame_h, coerce_into_frame=True)
    # Compatibility path: before body/world collision had its own storage key,
    # the runtime reused hurtbox geometry. Keep that shape as the physics body,
    # but force it enabled so disabling hurtbox damage does not also remove
    # body/world collision.
    out = sprite_hurtboxes(sprite, frame_w, frame_h)
    for box in out:
        box["enabled"] = True
    return out


def sprite_attack_hitboxes(sprite: dict, frame_w: int, frame_h: int) -> list[dict]:
    fallback = {
        "x": 0,
        "y": 0,
        "w": max(1, int(frame_w or 1) // 2),
        "h": max(1, int(frame_h or 1) // 2),
        "damage": 0,
        "knockback_x": 0,
        "knockback_y": 0,
        "active_start": 0,
        "active_len": 0,
        "priority": 0,
        "enabled": True,
    }
    raw = sprite.get(ATTACK_HITBOX_MULTI_KEY)
    if not raw:
        raw = sprite.get(ATTACK_HITBOX_KEY)
    if not raw:
        raw = sprite.get(ATTACK_HITBOX_ALT_KEY)
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes, dict)):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        box = normalize_box(item, fallback, frame_w=frame_w, frame_h=frame_h, coerce_into_frame=True)
        box["damage"] = max(0, int(item.get("damage", fallback["damage"]) or fallback["damage"]))
        box["knockback_x"] = int(item.get("knockback_x", fallback["knockback_x"]) or fallback["knockback_x"])
        box["knockback_y"] = int(item.get("knockback_y", fallback["knockback_y"]) or fallback["knockback_y"])
        box["active_start"] = max(0, min(255, int(item.get("active_start", fallback["active_start"]) or fallback["active_start"])))
        box["active_len"] = max(0, min(255, int(item.get("active_len", fallback["active_len"]) or fallback["active_len"])))
        box["priority"] = max(0, min(255, int(item.get("priority", fallback["priority"]) or fallback["priority"])))
        out.append(box)
    if sprite.get(ATTACK_HITBOX_MULTI_KEY):
        return out
    # Legacy `hitboxes_attack` was previously interpreted as a single attack box.
    # Keep old projects stable by only reading the first entry unless they opt in
    # to the new multi-box storage key.
    return out[:1]


def box_enabled(box: dict | None, default: bool = True) -> bool:
    if not isinstance(box, dict):
        return bool(default)
    return bool(box.get("enabled", default))


def active_hurtboxes(sprite: dict, frame_w: int, frame_h: int) -> list[dict]:
    return [dict(b) for b in sprite_hurtboxes(sprite, frame_w, frame_h) if box_enabled(b, True)]


def active_bodyboxes(sprite: dict, frame_w: int, frame_h: int) -> list[dict]:
    return [dict(b) for b in sprite_bodyboxes(sprite, frame_w, frame_h) if box_enabled(b, True)]


def active_attack_hitboxes(sprite: dict, frame_w: int, frame_h: int) -> list[dict]:
    return [dict(b) for b in sprite_attack_hitboxes(sprite, frame_w, frame_h) if box_enabled(b, True)]


def first_hurtbox(sprite: dict, frame_w: int, frame_h: int) -> dict:
    boxes = sprite_hurtboxes(sprite, frame_w, frame_h)
    if boxes:
        return boxes[0]
    return default_box(frame_w, frame_h)


def first_bodybox(sprite: dict, frame_w: int, frame_h: int) -> dict:
    boxes = sprite_bodyboxes(sprite, frame_w, frame_h)
    if boxes:
        return boxes[0]
    return default_box(frame_w, frame_h)


def first_attack_hitbox(sprite: dict, frame_w: int, frame_h: int) -> dict:
    boxes = sprite_attack_hitboxes(sprite, frame_w, frame_h)
    if boxes:
        return boxes[0]
    return first_hurtbox(sprite, frame_w, frame_h)


def store_sprite_boxes(sprite: dict, hurtboxes: list[dict], attack_hitboxes: list[dict]) -> None:
    sprite[HURTBOX_KEY] = [dict(h) for h in hurtboxes]
    # Keep legacy key in sync during the migration window.
    sprite[LEGACY_HITBOX_KEY] = [dict(h) for h in hurtboxes]
    canon_attack = [dict(h) for h in attack_hitboxes]
    sprite[ATTACK_HITBOX_MULTI_KEY] = canon_attack
    sprite[ATTACK_HITBOX_KEY] = [dict(canon_attack[0])] if canon_attack else []
