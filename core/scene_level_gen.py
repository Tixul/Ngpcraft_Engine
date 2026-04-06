"""
core/scene_level_gen.py - Generate scene gameplay headers from .ngpcraft metadata.

Goal (CT-10 / L-21):
- When exporting a scene, also export the Level/room data (entities, waves,
  collision map, visual tile IDs, layout/scroll metadata) as a C header.

This module is UI-independent (no Qt) so it can be used by:
- ProjectTab "Export scene C"
- core/headless_export.py
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from core.collision_boxes import active_attack_hitboxes, box_enabled, first_attack_hitbox, first_bodybox, first_hurtbox
from core.entity_roles import scene_role_map


_RE_SAFE = re.compile(r"[^0-9a-zA-Z_]+")


def _tile_id_variants(value: object, default: int) -> list[int]:
    out: list[int] = []
    if isinstance(value, int):
        out = [int(value)]
    elif isinstance(value, str):
        parts = re.split(r"[^0-9]+", value)
        out = [int(p) for p in parts if p != ""]
    elif isinstance(value, (list, tuple)):
        for item in value:
            try:
                out.append(int(item))
            except Exception:
                pass
    if not out:
        out = [int(default)]
    seen: set[int] = set()
    norm: list[int] = []
    for v in out:
        v = max(0, min(255, int(v)))
        if v in seen:
            continue
        seen.add(v)
        norm.append(v)
    return norm or [int(default)]


def _tile_id_pick(value: object, *, default: int, x: int = 0, y: int = 0, salt: int = 0) -> int:
    ids = _tile_id_variants(value, default)
    if len(ids) == 1:
        return ids[0]
    idx = (int(x) * 131 + int(y) * 17 + int(salt) * 73 + len(ids) * 11) % len(ids)
    return ids[idx]

# Collision constants (kept in sync with Level tab)
_TCOL_PASS = 0
_TCOL_SOLID = 1
_TCOL_ONE_WAY = 2
_TCOL_DAMAGE = 3
_TCOL_LADDER = 4
_TCOL_WALL_N = 5
_TCOL_WALL_S = 6
_TCOL_WALL_E = 7
_TCOL_WALL_W = 8
_TCOL_WATER = 9
_TCOL_FIRE = 10
_TCOL_VOID = 11
_TCOL_DOOR = 12
_TCOL_STAIR_E = 13
_TCOL_STAIR_W = 14
_TCOL_SPRING      = 15
_TCOL_ICE         = 16
_TCOL_CONVEYOR_L  = 17
_TCOL_CONVEYOR_R  = 18

_SPRING_DIR_TO_C: dict[str, int] = {
    "up": 0,
    "down": 1,
    "left": 2,
    "right": 3,
    "opposite_touch": 4,
}

_MAP_MODE_ROLES: dict[str, list[tuple[str, int]]] = {
    "platformer": [
        ("empty", _TCOL_PASS),
        ("floor", _TCOL_SOLID),
        ("platform", _TCOL_ONE_WAY),
        ("damage", _TCOL_DAMAGE),
        ("ladder", _TCOL_LADDER),
        ("stair_e", _TCOL_STAIR_E),
        ("stair_w", _TCOL_STAIR_W),
        ("spring",      _TCOL_SPRING),
        ("ice",         _TCOL_ICE),
        ("conveyor_l",  _TCOL_CONVEYOR_L),
        ("conveyor_r",  _TCOL_CONVEYOR_R),
        ("water", _TCOL_WATER),
        ("fire", _TCOL_FIRE),
        ("void", _TCOL_VOID),
        ("door", _TCOL_DOOR),
    ],
    "topdown": [
        ("empty", _TCOL_PASS),
        ("solid", _TCOL_SOLID),
        ("wall_n", _TCOL_WALL_N),
        ("wall_s", _TCOL_WALL_S),
        ("wall_e", _TCOL_WALL_E),
        ("wall_w", _TCOL_WALL_W),
        ("damage", _TCOL_DAMAGE),
        ("water", _TCOL_WATER),
        ("fire", _TCOL_FIRE),
        ("void", _TCOL_VOID),
        ("door", _TCOL_DOOR),
    ],
    "shmup": [
        ("empty", _TCOL_PASS),
        ("solid", _TCOL_SOLID),
        ("damage", _TCOL_DAMAGE),
        ("fire", _TCOL_FIRE),
        ("void", _TCOL_VOID),
    ],
    "open": [
        ("empty", _TCOL_PASS),
        ("solid", _TCOL_SOLID),
        ("damage", _TCOL_DAMAGE),
        ("water", _TCOL_WATER),
        ("fire", _TCOL_FIRE),
        ("void", _TCOL_VOID),
        ("door", _TCOL_DOOR),
    ],
    # Puzzle: single-screen grid — floor/wall/pressure_plate/ice_floor/void_pit/door.
    # pressure_plate reuses DAMAGE tcol; ice_floor reuses ICE; void_pit reuses VOID.
    "puzzle": [
        ("floor",          _TCOL_PASS),
        ("wall",           _TCOL_SOLID),
        ("pressure_plate", _TCOL_DAMAGE),
        ("ice_floor",      _TCOL_ICE),
        ("void_pit",       _TCOL_VOID),
        ("door",           _TCOL_DOOR),
    ],
    # Race: topdown circuit — track/wall/boost/gravel/void.
    # Boost reuses CONVEYOR_R tcol; gravel reuses ICE tcol.
    "race": [
        ("track",  _TCOL_PASS),
        ("wall",   _TCOL_SOLID),
        ("boost",  _TCOL_CONVEYOR_R),
        ("gravel", _TCOL_ICE),
        ("void",   _TCOL_VOID),
    ],
}

_CAM_MODE_TO_C: dict[str, int] = {
    "single_screen": 0,
    "follow": 1,
    "forced_scroll": 2,
    "segments": 3,
    "loop": 4,
}
_MAP_MODE_TO_C: dict[str, int] = {
    "none": 0,
    "platformer": 1,
    "topdown": 2,
    "shmup": 3,
    "open": 4,
    "race": 5,
    "puzzle": 6,
}
_LEVEL_PROFILES: list[str] = [
    "none",
    "fighting",
    "platformer",
    "run_gun",
    "shmup",
    "brawler",
    "topdown_rpg",
    "tactical",
    "tcg",
    "puzzle",
    "visual_novel",
    "rhythm",
    "race",
]
_PROFILE_TO_C: dict[str, int] = {
    name: idx for idx, name in enumerate(_LEVEL_PROFILES)
}
_PROFILE_PRESETS: dict[str, dict[str, object]] = {
    "fighting":     {"map_mode": "none",       "scroll_x": True,  "scroll_y": False, "forced": False, "loop_x": False, "loop_y": False, "gw": 32, "gh": 19},
    "platformer":   {"map_mode": "platformer", "scroll_x": True,  "scroll_y": True,  "forced": False, "loop_x": False, "loop_y": False},
    "run_gun":      {"map_mode": "platformer", "scroll_x": True,  "scroll_y": False, "forced": False, "loop_x": False, "loop_y": False},
    "shmup":        {"map_mode": "shmup",      "scroll_x": False, "scroll_y": True,  "forced": True,  "loop_x": False, "loop_y": True, "speed_x": 0, "speed_y": 1},
    "brawler":      {"map_mode": "none",       "scroll_x": True,  "scroll_y": True,  "forced": False, "loop_x": False, "loop_y": False},
    "topdown_rpg":  {"map_mode": "topdown",    "scroll_x": True,  "scroll_y": True,  "forced": False, "loop_x": False, "loop_y": False},
    "tactical":     {"map_mode": "topdown",    "scroll_x": True,  "scroll_y": True,  "forced": False, "loop_x": False, "loop_y": False},
    "tcg":          {"map_mode": "none",       "scroll_x": False, "scroll_y": False, "forced": False, "loop_x": False, "loop_y": False, "gw": 20, "gh": 19},
    "puzzle":       {"map_mode": "none",       "scroll_x": False, "scroll_y": False, "forced": False, "loop_x": False, "loop_y": False, "gw": 20, "gh": 19},
    "visual_novel": {"map_mode": "none",       "scroll_x": False, "scroll_y": False, "forced": False, "loop_x": False, "loop_y": False, "gw": 20, "gh": 19},
    "rhythm":       {"map_mode": "none",       "scroll_x": False, "scroll_y": True,  "forced": True,  "loop_x": False, "loop_y": True, "speed_x": 0, "speed_y": 1, "gw": 20, "gh": 19},
    "race":         {"map_mode": "race",       "scroll_x": True,  "scroll_y": True,  "forced": False, "loop_x": True,  "loop_y": True},
}


def _safe_ident(s: str) -> str:
    s = (s or "").strip()
    s = _RE_SAFE.sub("_", s).strip("_")
    if not s:
        return "scene"
    if s[0].isdigit():
        s = "_" + s
    return s.lower()


def _type_to_c_const(name: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9]+", "_", (name or "")).strip("_").upper()
    return f"ENT_{clean}" if clean else "ENT_UNKNOWN"


def _safe_c_id(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", (name or "")).strip("_").lower() or "id"


def _sprite_meta_map(scene: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for spr in (scene.get("sprites") or []):
        if not isinstance(spr, dict):
            continue
        nm = str(spr.get("name") or "").strip()
        if not nm:
            rel = str(spr.get("file") or "").strip()
            nm = Path(rel).stem if rel else ""
        if not nm:
            continue
        out[nm] = spr
    return out


def _sprite_body_box(meta: dict, project_dir: Path | None) -> tuple[int, int, int, int]:
    del project_dir
    fw = int(meta.get("frame_w", 8) or 8)
    fh = int(meta.get("frame_h", 8) or 8)
    # Body/world collision now has its own canonical path, with a compatibility
    # fallback to hurtbox geometry when no explicit body box exists yet.
    hb = first_bodybox(meta, fw, fh)
    return (
        int(hb.get("x", 0) or 0),
        int(hb.get("y", 0) or 0),
        max(1, int(hb.get("w", fw) or fw)),
        max(1, int(hb.get("h", fh) or fh)),
    )


_ENEMY_SUPPORT_TILES = {
    _TCOL_SOLID,
    _TCOL_ONE_WAY,
    _TCOL_STAIR_E,
    _TCOL_STAIR_W,
    _TCOL_SPRING,
    _TCOL_ICE,
    _TCOL_CONVEYOR_L,
    _TCOL_CONVEYOR_R,
}


def _tile_supports_enemy(tile: object) -> bool:
    try:
        tile_id = int(tile)
    except Exception:
        return False
    return tile_id in _ENEMY_SUPPORT_TILES


def _derive_patrol_platform_bounds(ent: dict, meta: dict, col_map: object) -> tuple[int, int] | None:
    if not isinstance(meta, dict):
        return None
    if not isinstance(col_map, list) or not col_map:
        return None
    if not all(isinstance(row, list) and row for row in col_map):
        return None

    map_h = len(col_map)
    map_w = len(col_map[0])
    if map_w <= 0:
        return None

    render_off_x, render_off_y = _sprite_render_offset(meta)
    body_x, body_y, body_w, body_h = _sprite_body_box(meta, None)
    try:
        spawn_wx = int(ent.get("x", 0) or 0) * 8 - int(render_off_x)
        spawn_wy = int(ent.get("y", 0) or 0) * 8 - int(render_off_y)
    except Exception:
        return None

    support_y = int(spawn_wy + body_y + body_h + 1)
    support_ty = support_y // 8
    if support_ty < 0 or support_ty >= map_h:
        return None

    row = col_map[support_ty]
    probe_xs = (
        int(spawn_wx + body_x + (body_w // 2)),
        int(spawn_wx + body_x + 1),
        int(spawn_wx + body_x + max(0, body_w - 1)),
    )
    support_tx: int | None = None
    for probe_x in probe_xs:
        probe_tx = probe_x // 8
        if probe_tx < 0 or probe_tx >= map_w:
            continue
        if _tile_supports_enemy(row[probe_tx]):
            support_tx = probe_tx
            break
    if support_tx is None:
        return None

    left_tx = support_tx
    right_tx = support_tx
    while left_tx > 0 and _tile_supports_enemy(row[left_tx - 1]):
        left_tx -= 1
    while right_tx + 1 < map_w and _tile_supports_enemy(row[right_tx + 1]):
        right_tx += 1

    patrol_min = int(left_tx * 8 - body_x)
    patrol_max = int(((right_tx + 1) * 8 - 1) - body_x - body_w)
    if patrol_max < patrol_min:
        anchor = spawn_wx
        if anchor < patrol_min:
            anchor = patrol_min
        elif anchor > patrol_max:
            anchor = patrol_max
        patrol_min = anchor
        patrol_max = anchor
    return patrol_min, patrol_max


def _sprite_render_offset(meta: dict) -> tuple[int, int]:
    fw = max(1, int(meta.get("frame_w", 8) or 8))
    fh = max(1, int(meta.get("frame_h", 8) or 8))
    # Canonical rule for Level/runtime alignment:
    # - scene entity x/y is the visual top-left placement seen in Level
    # - runtime actor/world position is the internal sprite anchor used by
    #   hitboxes/hurtboxes (legacy data is centered around the frame)
    # So rendering must offset back by half the frame, independently from
    # body/world collision boxes.
    return -(fw // 2), -(fh // 2)


def _dir_frames_for_type(meta: dict, frame_count: int) -> tuple[list[int], list[int]]:
    """Return (frames[8], flips[8]) for directional sprite rendering.

    Direction indices match ngpc_vehicle convention:
      0=E  1=NE  2=N  3=NW  4=W  5=SW  6=S  7=SE

    The editor stores unique frames for N, NE, E, SE, S (plus N, E, S for 4dir).
    Missing directions are derived by mirroring:  NW=mirror(NE), W=mirror(E), SW=mirror(SE).
    When mode is "none", returns all-zero arrays (no directional rendering).
    """
    df = meta.get("dir_frames") or {}
    mode = str(df.get("mode", "none") or "none").strip().lower()
    if mode not in ("4dir", "8dir"):
        return [0] * 8, [0] * 8

    def _f(key: str) -> int:
        v = df.get(key, 0)
        return max(0, min(255, int(v) if v is not None else 0))

    if mode == "8dir":
        f_N  = _f("N");  f_NE = _f("NE"); f_E  = _f("E")
        f_SE = _f("SE"); f_S  = _f("S")
        # dir: 0=E  1=NE  2=N  3=NW(=NE+flip)  4=W(=E+flip)  5=SW(=SE+flip)  6=S  7=SE
        frames = [f_E, f_NE, f_N, f_NE, f_E, f_SE, f_S, f_SE]
        flips  = [0,   0,    0,   1,    1,   1,    0,   0  ]
    else:  # 4dir
        f_N = _f("N"); f_E = _f("E"); f_S = _f("S")
        # dir: 0=E  1=NE→E  2=N  3=NW→E+flip  4=W→E+flip  5=SW→E+flip  6=S  7=SE→E
        frames = [f_E, f_E, f_N, f_E, f_E, f_E, f_S, f_E]
        flips  = [0,   0,   0,   1,   1,   1,   0,   0  ]

    fc = max(1, frame_count)
    frames = [min(f, fc - 1) for f in frames]
    return frames, flips


def _anim_range(meta: dict, state: str, frame_count: int) -> tuple[int, int]:
    anims = meta.get("anims") or {}
    if isinstance(anims, dict):
        cfg = anims.get(state) or {}
        if isinstance(cfg, dict):
            start = max(0, int(cfg.get("start", 0) or 0))
            count = max(0, int(cfg.get("count", 0) or 0))
            if start >= frame_count:
                start = 0
                count = 0
            if count > 0:
                count = min(count, max(0, frame_count - start))
                return start, count
    # All unconfigured states (including idle) return (0, 0).
    # The runtime falls back: undefined state -> idle; idle count=0 -> frame 0 only.
    # This prevents unconfigured idle from auto-spanning all frames and
    # overlapping with explicitly configured states (e.g. death).
    return 0, 0


def _anim_speed(meta: dict) -> int:
    props = meta.get("props") or {}
    if isinstance(props, dict):
        try:
            spd = int(props.get("anim_spd", 0) or 0)
            if spd > 0:
                return spd
        except Exception:
            pass
    try:
        spd = int(meta.get("anim_duration", 0) or 0)
        if spd > 0:
            return spd
    except Exception:
        pass
    return 6


def _collect_entity_types(scene: dict) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for ent in (scene.get("entities") or []):
        if not isinstance(ent, dict):
            continue
        t = str(ent.get("type") or "").strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    for w in (scene.get("waves") or []):
        if not isinstance(w, dict):
            continue
        for ent in (w.get("entities") or []):
            if not isinstance(ent, dict):
                continue
            t = str(ent.get("type") or "").strip()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    for spr in (scene.get("sprites") or []):
        if not isinstance(spr, dict):
            continue
        t = str(spr.get("name") or "").strip()
        if not t:
            rel = str(spr.get("file") or "").strip()
            t = Path(rel).stem if rel else ""
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def collect_scene_level_issues(*, project_data: dict, scene: dict) -> list[str]:
    """Return blocking reference issues for scene-level export."""
    issues: list[str] = []
    entities = [dict(e) for e in (scene.get("entities") or []) if isinstance(e, dict)]
    regions = [dict(r) for r in (scene.get("regions") or []) if isinstance(r, dict)]
    triggers = [dict(t) for t in (scene.get("triggers") or []) if isinstance(t, dict)]

    entity_ids = {
        str(e.get("id") or "").strip()
        for e in entities
        if str(e.get("id") or "").strip()
    }
    region_ids = {
        str(r.get("id") or "").strip()
        for r in regions
        if str(r.get("id") or "").strip()
    }
    trigger_ids = {
        str(t.get("id") or "").strip()
        for t in triggers
        if str(t.get("id") or "").strip()
    }
    scene_ids = {
        str(s.get("id") or "").strip()
        for s in (project_data.get("scenes") or [])
        if isinstance(s, dict) and str(s.get("id") or "").strip()
    }

    def _name(i: int, trig: dict) -> str:
        return str(trig.get("name") or f"trigger_{i}").strip()

    for i, trig in enumerate(triggers):
        act = str(trig.get("action") or "").strip().lower() or "emit_event"
        nm = _name(i, trig)

        for j, extra in enumerate(trig.get("extra_conds", []) or []):
            if not isinstance(extra, dict):
                continue
            extra_rid = str(extra.get("region_id") or "").strip()
            if extra_rid and extra_rid not in region_ids:
                issues.append(f"{nm}: extra condition #{j + 1} references missing region '{extra_rid}'")
        for j, og in enumerate(trig.get("or_groups", []) or []):
            if not isinstance(og, list):
                continue
            for k, ec in enumerate(og):
                if not isinstance(ec, dict):
                    continue
                ec_rid = str(ec.get("region_id") or "").strip()
                if ec_rid and ec_rid not in region_ids:
                    issues.append(f"trigger '{_name(i, trig)}' or_group[{j}][{k}]: region_id '{ec_rid}' not found")

        if act in ("goto_scene", "warp_to"):
            sid = str(trig.get("scene_to") or "").strip()
            if sid and sid not in scene_ids:
                issues.append(f"{nm}: target scene '{sid}' not found")

        elif act in ("enable_trigger", "disable_trigger"):
            tid = str(trig.get("target_id") or "").strip()
            if tid:
                if tid not in trigger_ids:
                    issues.append(f"{nm}: target trigger '{tid}' not found")
            else:
                legacy_idx = int(trig.get("event", 0) or 0)
                if not (0 <= legacy_idx < len(triggers)):
                    issues.append(f"{nm}: target trigger index {legacy_idx} is out of range")

        elif act in ("show_entity", "hide_entity", "move_entity_to"):
            target_id = str(trig.get("entity_target_id") or "").strip()
            if target_id:
                if target_id not in entity_ids:
                    issues.append(f"{nm}: target entity '{target_id}' not found")
            else:
                legacy_idx = int(trig.get("entity_index", trig.get("event", 0)) or 0)
                if not (0 <= legacy_idx < len(entities)):
                    issues.append(f"{nm}: target entity index {legacy_idx} is out of range")

            if act == "move_entity_to":
                dest_region_id = str(trig.get("dest_region_id") or "").strip()
                if dest_region_id:
                    if dest_region_id not in region_ids:
                        issues.append(f"{nm}: destination region '{dest_region_id}' not found")
                else:
                    legacy_idx = int(trig.get("param", 0) or 0)
                    if not (0 <= legacy_idx < len(regions)):
                        issues.append(f"{nm}: destination region index {legacy_idx} is out of range")

    # Validate neighbor scene references (Track B).
    _nb_raw = scene.get("neighbors") or {}
    if isinstance(_nb_raw, dict):
        for _dir, _nb in _nb_raw.items():
            _target = str(_nb if isinstance(_nb, str) else (_nb.get("scene", "") or "")) if _nb else ""
            if _target and _target not in scene_ids:
                issues.append(f"neighbors.{_dir}: target scene '{_target}' not found")

    return issues


def make_scene_level_h(
    *,
    project_data: dict,
    scene: dict,
    sym: str | None = None,
    project_dir: Path | None = None,
) -> str:
    """Generate the full `scene_<name>_level.h` text for one scene.

    The header contains gameplay-facing metadata exported from the `.ngpcraft`
    scene: entity types, entity placements, waves, collision/tile role maps,
    camera/layout settings, regions, triggers, paths, parallax and audio
    defines. It is pure text generation and can be used from both the GUI and
    the headless export path.
    """
    issues = collect_scene_level_issues(project_data=project_data, scene=scene)
    if issues:
        raise ValueError("invalid scene level references:\n- " + "\n- ".join(issues))

    label = str(scene.get("label") or "")
    sid = str(scene.get("id") or "")
    safe = _safe_ident(label or sid or "scene")

    sym_use = (sym or safe).strip() or safe
    sym_use = _safe_ident(sym_use)
    guard = f"SCENE_{sym_use.upper()}_LEVEL_H"

    entities = [dict(e) for e in (scene.get("entities") or []) if isinstance(e, dict)]
    waves = [dict(w) for w in (scene.get("waves") or []) if isinstance(w, dict)]
    paths = [dict(p) for p in (scene.get("paths") or []) if isinstance(p, dict)]
    entity_roles = scene_role_map(scene)

    sprite_meta = _sprite_meta_map(scene)
    seen_types = _collect_entity_types(scene)
    damage_prop_types: set[str] = set()

    sep = "/* " + "-" * 66 + " */"
    lines: list[str] = [
        "/* Auto-generated by NgpCraft Engine -- do not edit */",
        f"/* Scene: {sym_use} */",
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        '#include "ngpc_types.h"   /* u8,u16,s16 */',
        "",
        "/* Standalone types (avoid conflicts with optional template modules). */",
        "#ifndef NGPNG_LEVEL_TYPES",
        "#define NGPNG_LEVEL_TYPES",
        "typedef struct { s16 x, y, w, h; } NgpngRect;",
        "typedef struct { u8 type; u8 x; u8 y; u8 data; } NgpngEnt;",
        "#endif",
        "",
    ]

    # ---- Entity type IDs ----
    lines += [sep, "/* Entity type IDs                                                    */", sep]
    for i, t in enumerate(seen_types):
        role = entity_roles.get(t, "prop")
        role_cmt = f"  /* [{role}] */" if role != "prop" else ""
        lines.append(f"#define {_type_to_c_const(t):30s} {i}{role_cmt}")
    lines.append("")

    role_to_id = {
        "prop": 0,
        "player": 1,
        "enemy": 2,
        "item": 3,
        "npc": 4,
        "trigger": 5,
        "platform": 6,
        "block": 7,
    }
    if seen_types:
        lines += [sep, "/* Entity roles by type ID                                             */", sep]
        lines += [
            "#ifndef NGPNG_ROLE_PROP",
            "#define NGPNG_ROLE_PROP    0",
            "#define NGPNG_ROLE_PLAYER  1",
            "#define NGPNG_ROLE_ENEMY   2",
            "#define NGPNG_ROLE_ITEM    3",
            "#define NGPNG_ROLE_NPC     4",
            "#define NGPNG_ROLE_TRIGGER 5",
            "#define NGPNG_ROLE_PLATFORM 6",
            "#define NGPNG_ROLE_BLOCK 7",
            "#endif",
            "",
        ]
        role_vals = []
        for t in seen_types:
            role_name = str(entity_roles.get(t, "prop") or "prop").strip().lower()
            role_vals.append(str(int(role_to_id.get(role_name, 0))))
        lines.append(f"static const u8 g_{sym_use}_type_roles[] = {{{', '.join(role_vals)}}};")
        lines.append(f"#define {sym_use.upper()}_TYPE_ROLE_COUNT {len(seen_types)}")
        lines.append("")

        hb_x_vals: list[str] = []
        hb_y_vals: list[str] = []
        hb_w_vals: list[str] = []
        hb_h_vals: list[str] = []
        body_x_vals: list[str] = []
        body_y_vals: list[str] = []
        body_w_vals: list[str] = []
        body_h_vals: list[str] = []
        render_off_x_vals: list[str] = []
        render_off_y_vals: list[str] = []
        frame_w_vals: list[str] = []
        frame_h_vals: list[str] = []
        atk_x_vals: list[str] = []
        atk_y_vals: list[str] = []
        atk_w_vals: list[str] = []
        atk_h_vals: list[str] = []
        atk_dmg_vals: list[str] = []
        atk_kbx_vals: list[str] = []
        atk_kby_vals: list[str] = []
        atk_prio_vals: list[str] = []
        atk_active_start_vals: list[str] = []
        atk_active_len_vals: list[str] = []
        atk_count_vals: list[str] = []
        atk_start_vals: list[str] = []
        atk_flat_x_vals: list[str] = []
        atk_flat_y_vals: list[str] = []
        atk_flat_w_vals: list[str] = []
        atk_flat_h_vals: list[str] = []
        atk_flat_dmg_vals: list[str] = []
        atk_flat_kbx_vals: list[str] = []
        atk_flat_kby_vals: list[str] = []
        atk_flat_prio_vals: list[str] = []
        atk_flat_active_start_vals: list[str] = []
        atk_flat_active_len_vals: list[str] = []
        atk_anim_state_vals: list[str] = []
        atk_flat_anim_state_vals: list[str] = []
        hp_vals: list[str] = []
        dmg_vals: list[str] = []
        score_vals: list[str] = []
        grav_vals: list[str] = []
        flip_x_dir_vals: list[str] = []
        anim_idle_start_vals: list[str] = []
        anim_idle_count_vals: list[str] = []
        anim_walk_start_vals: list[str] = []
        anim_walk_count_vals: list[str] = []
        anim_jump_start_vals: list[str] = []
        anim_jump_count_vals: list[str] = []
        anim_fall_start_vals: list[str] = []
        anim_fall_count_vals: list[str] = []
        anim_death_start_vals: list[str] = []
        anim_death_count_vals: list[str] = []
        anim_speed_vals: list[str] = []
        dir_frame_vals: list[str] = []  # 8 values per type, flattened
        dir_flip_vals:  list[str] = []  # 8 values per type, flattened
        has_dir_frames: bool = False
        can_shoot_vals: list[str] = []
        fire_rate_vals: list[str] = []
        fire_cond_vals: list[str] = []
        fire_range_vals: list[str] = []
        bullet_btype_vals: list[str] = []
        for t in seen_types:
            meta = sprite_meta.get(t) or {}
            role_name = str(entity_roles.get(t, "prop") or "prop").strip().lower()
            fw = int(meta.get("frame_w", 8) or 8)
            fh = int(meta.get("frame_h", 8) or 8)
            fc = max(1, int(meta.get("frame_count", 1) or 1))
            hb = first_hurtbox(meta, fw, fh)
            body_x, body_y, body_w, body_h = _sprite_body_box(meta, project_dir)
            render_off_x, render_off_y = _sprite_render_offset(meta)
            atk = first_attack_hitbox(meta, fw, fh)
            atk_boxes = active_attack_hitboxes(meta, fw, fh)
            hb_x = int(hb.get("x", 0) or 0)
            hb_y = int(hb.get("y", 0) or 0)
            hb_x_vals.append(str(hb_x))
            hb_y_vals.append(str(hb_y))
            hb_w_vals.append(str((int(hb.get("w", 8) or 8) if box_enabled(hb, True) else 0) & 0xFF))
            hb_h_vals.append(str((int(hb.get("h", 8) or 8) if box_enabled(hb, True) else 0) & 0xFF))
            body_x_vals.append(str(int(body_x)))
            body_y_vals.append(str(int(body_y)))
            body_w_vals.append(str(int(body_w) & 0xFF))
            body_h_vals.append(str(int(body_h) & 0xFF))
            render_off_x_vals.append(str(int(render_off_x)))
            render_off_y_vals.append(str(int(render_off_y)))
            frame_w_vals.append(str(fw & 0xFF))
            frame_h_vals.append(str(fh & 0xFF))
            atk_x_vals.append(str(int(atk.get("x", 0) or 0)))
            atk_y_vals.append(str(int(atk.get("y", 0) or 0)))
            atk_w_vals.append(str((int(atk.get("w", 8) or 8) if box_enabled(atk, True) else 0) & 0xFF))
            atk_h_vals.append(str((int(atk.get("h", 8) or 8) if box_enabled(atk, True) else 0) & 0xFF))
            atk_dmg_vals.append(str((int(atk.get("damage", 0) or 0) if box_enabled(atk, True) else 0) & 0xFF))
            atk_kbx_vals.append(str(int(atk.get("knockback_x", 0) or 0) if box_enabled(atk, True) else 0))
            atk_kby_vals.append(str(int(atk.get("knockback_y", 0) or 0) if box_enabled(atk, True) else 0))
            atk_prio_vals.append(str((int(atk.get("priority", 0) or 0) if box_enabled(atk, True) else 0) & 0xFF))
            atk_active_start_vals.append(str((int(atk.get("active_start", 0) or 0) if box_enabled(atk, True) else 0) & 0xFF))
            atk_active_len_vals.append(str((int(atk.get("active_len", 0) or 0) if box_enabled(atk, True) else 0) & 0xFF))
            atk_anim_state_vals.append(str((int(atk.get("active_anim_state", 0xFF) or 0xFF) if box_enabled(atk, True) else 0xFF) & 0xFF))
            atk_start_vals.append(str(len(atk_flat_x_vals)))
            atk_count_vals.append(str(len(atk_boxes)))
            for ab in atk_boxes:
                atk_flat_x_vals.append(str(int(ab.get("x", 0) or 0)))
                atk_flat_y_vals.append(str(int(ab.get("y", 0) or 0)))
                atk_flat_w_vals.append(str(int(ab.get("w", 8) or 8) & 0xFF))
                atk_flat_h_vals.append(str(int(ab.get("h", 8) or 8) & 0xFF))
                atk_flat_dmg_vals.append(str(int(ab.get("damage", 0) or 0) & 0xFF))
                atk_flat_kbx_vals.append(str(int(ab.get("knockback_x", 0) or 0)))
                atk_flat_kby_vals.append(str(int(ab.get("knockback_y", 0) or 0)))
                atk_flat_prio_vals.append(str(int(ab.get("priority", 0) or 0) & 0xFF))
                atk_flat_active_start_vals.append(str(int(ab.get("active_start", 0) or 0) & 0xFF))
                atk_flat_active_len_vals.append(str(int(ab.get("active_len", 0) or 0) & 0xFF))
                atk_flat_anim_state_vals.append(str(int(ab.get("active_anim_state", 0xFF) or 0xFF) & 0xFF))
            props = meta.get("props") or {}
            hp_vals.append(str(int(props.get("hp", 1) or 1) & 0xFF))
            dmg_vals.append(str(int(props.get("damage", 0) or 0) & 0xFF))
            score_vals.append(str(int(props.get("score", 0) or 0) & 0xFF))
            # OPT-2E: flat_patrol=true → gravity=0, skip floor probes + gravity for patrol enemies on flat terrain
            flat_patrol = bool(props.get("flat_patrol", False))
            grav_vals.append("0" if flat_patrol else str(int(props.get("gravity", 0) or 0) & 0xFF))
            flip_x_dir_vals.append(str(int(props.get("flip_x_dir", 0) or 0) & 0xFF))
            if role_name == "prop":
                type_damage = int(props.get("damage", 0) or 0)
                if type_damage > 0 or any(int(ab.get("damage", 0) or 0) > 0 for ab in atk_boxes):
                    damage_prop_types.add(t)
            idle_start, idle_count = _anim_range(meta, "idle", fc)
            walk_start, walk_count = _anim_range(meta, "walk", fc)
            jump_start, jump_count = _anim_range(meta, "jump", fc)
            fall_start, fall_count = _anim_range(meta, "fall", fc)
            death_start, death_count = _anim_range(meta, "death", fc)
            anim_idle_start_vals.append(str(idle_start & 0xFF))
            anim_idle_count_vals.append(str(idle_count & 0xFF))
            anim_walk_start_vals.append(str(walk_start & 0xFF))
            anim_walk_count_vals.append(str(walk_count & 0xFF))
            anim_jump_start_vals.append(str(jump_start & 0xFF))
            anim_jump_count_vals.append(str(jump_count & 0xFF))
            anim_fall_start_vals.append(str(fall_start & 0xFF))
            anim_fall_count_vals.append(str(fall_count & 0xFF))
            anim_death_start_vals.append(str(death_start & 0xFF))
            anim_death_count_vals.append(str(death_count & 0xFF))
            anim_speed_vals.append(str(_anim_speed(meta) & 0xFF))
            # Directional frames (generic — works for any entity with facing direction)
            _dframes, _dflips = _dir_frames_for_type(meta, fc)
            dir_frame_vals.extend(str(v & 0xFF) for v in _dframes)
            dir_flip_vals.extend(str(v & 0xFF) for v in _dflips)
            if any(v != 0 for v in _dframes) or any(v != 0 for v in _dflips):
                has_dir_frames = True
            # Shooting config (from spr["shooting"] top-level key)
            shoot = meta.get("shooting") or {}
            can_shoot_vals.append("1" if shoot.get("can_shoot", False) else "0")
            fire_rate_vals.append(str(int(shoot.get("fire_rate", 40) or 40) & 0xFF))
            fire_cond_vals.append(str(int(shoot.get("fire_condition", 0) or 0) & 0xFF))
            fire_range_vals.append(str(int(shoot.get("fire_range", 0) or 0) & 0xFF))
            # Resolve bullet sprite type index in this scene (0xFF = none)
            bullet_spr_name = shoot.get("bullet_sprite") or ""
            if bullet_spr_name and bullet_spr_name in seen_types:
                bullet_btype_vals.append(str(seen_types.index(bullet_spr_name)))
            else:
                bullet_btype_vals.append("0xFFu")
        lines += [sep, "/* Runtime type tables                                                 */", sep]
        if not atk_flat_x_vals:
            atk_flat_x_vals = ["0"]
            atk_flat_y_vals = ["0"]
            atk_flat_w_vals = ["0"]
            atk_flat_h_vals = ["0"]
            atk_flat_dmg_vals = ["0"]
            atk_flat_kbx_vals = ["0"]
            atk_flat_kby_vals = ["0"]
            atk_flat_prio_vals = ["0"]
            atk_flat_active_start_vals = ["0"]
            atk_flat_active_len_vals = ["0"]
            atk_anim_state_vals = ["0xFF"]
            atk_flat_anim_state_vals = ["0xFF"]
        lines.append(f"static const s8 g_{sym_use}_hitbox_x[] = {{{', '.join(hb_x_vals)}}};")
        lines.append(f"static const s8 g_{sym_use}_hitbox_y[] = {{{', '.join(hb_y_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_hitbox_w[] = {{{', '.join(hb_w_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_hitbox_h[] = {{{', '.join(hb_h_vals)}}};")
        lines.append(f"static const s8 g_{sym_use}_body_x[] = {{{', '.join(body_x_vals)}}};")
        lines.append(f"static const s8 g_{sym_use}_body_y[] = {{{', '.join(body_y_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_body_w[] = {{{', '.join(body_w_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_body_h[] = {{{', '.join(body_h_vals)}}};")
        lines.append(f"static const s8 g_{sym_use}_render_off_x[] = {{{', '.join(render_off_x_vals)}}};")
        lines.append(f"static const s8 g_{sym_use}_render_off_y[] = {{{', '.join(render_off_y_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_frame_w[] = {{{', '.join(frame_w_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_frame_h[] = {{{', '.join(frame_h_vals)}}};")
        lines.append(f"static const s8 g_{sym_use}_attack_hitbox_x[] = {{{', '.join(atk_x_vals)}}};")
        lines.append(f"static const s8 g_{sym_use}_attack_hitbox_y[] = {{{', '.join(atk_y_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_attack_hitbox_w[] = {{{', '.join(atk_w_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_attack_hitbox_h[] = {{{', '.join(atk_h_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_attack_hitbox_damage[] = {{{', '.join(atk_dmg_vals)}}};")
        lines.append(f"static const s8 g_{sym_use}_attack_hitbox_kb_x[] = {{{', '.join(atk_kbx_vals)}}};")
        lines.append(f"static const s8 g_{sym_use}_attack_hitbox_kb_y[] = {{{', '.join(atk_kby_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_attack_hitbox_priority[] = {{{', '.join(atk_prio_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_attack_hitbox_active_start[] = {{{', '.join(atk_active_start_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_attack_hitbox_active_len[] = {{{', '.join(atk_active_len_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_attack_hitbox_count[] = {{{', '.join(atk_count_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_attack_hitbox_start[] = {{{', '.join(atk_start_vals)}}};")
        lines.append(f"static const s8 g_{sym_use}_attack_hitboxes_x[] = {{{', '.join(atk_flat_x_vals)}}};")
        lines.append(f"static const s8 g_{sym_use}_attack_hitboxes_y[] = {{{', '.join(atk_flat_y_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_attack_hitboxes_w[] = {{{', '.join(atk_flat_w_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_attack_hitboxes_h[] = {{{', '.join(atk_flat_h_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_attack_hitboxes_damage[] = {{{', '.join(atk_flat_dmg_vals)}}};")
        lines.append(f"static const s8 g_{sym_use}_attack_hitboxes_kb_x[] = {{{', '.join(atk_flat_kbx_vals)}}};")
        lines.append(f"static const s8 g_{sym_use}_attack_hitboxes_kb_y[] = {{{', '.join(atk_flat_kby_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_attack_hitboxes_priority[] = {{{', '.join(atk_flat_prio_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_attack_hitboxes_active_start[] = {{{', '.join(atk_flat_active_start_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_attack_hitboxes_active_len[] = {{{', '.join(atk_flat_active_len_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_attack_hitbox_anim_state[] = {{{', '.join(atk_anim_state_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_attack_hitboxes_anim_state[] = {{{', '.join(atk_flat_anim_state_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_type_hp[] = {{{', '.join(hp_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_type_damage[] = {{{', '.join(dmg_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_type_score[] = {{{', '.join(score_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_type_gravity[] = {{{', '.join(grav_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_type_flip_x_dir[] = {{{', '.join(flip_x_dir_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_type_anim_idle_start[] = {{{', '.join(anim_idle_start_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_type_anim_idle_count[] = {{{', '.join(anim_idle_count_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_type_anim_walk_start[] = {{{', '.join(anim_walk_start_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_type_anim_walk_count[] = {{{', '.join(anim_walk_count_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_type_anim_jump_start[] = {{{', '.join(anim_jump_start_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_type_anim_jump_count[] = {{{', '.join(anim_jump_count_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_type_anim_fall_start[] = {{{', '.join(anim_fall_start_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_type_anim_fall_count[] = {{{', '.join(anim_fall_count_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_type_anim_death_start[] = {{{', '.join(anim_death_start_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_type_anim_death_count[] = {{{', '.join(anim_death_count_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_type_anim_speed[] = {{{', '.join(anim_speed_vals)}}};")
        # Directional sprite frames (generic — works for any entity with facing direction)
        # 8 entries per type, indexed as: g_SCENE_type_dir_frame[type * 8 + dir]
        # Direction convention (matches ngpc_vehicle): 0=E 1=NE 2=N 3=NW 4=W 5=SW 6=S 7=SE
        # dir_flip: 1 = apply SPR_HFLIP to the frame. All zeros = not configured.
        lines.append(f"static const u8 g_{sym_use}_type_dir_frame[] = {{{', '.join(dir_frame_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_type_dir_flip[]  = {{{', '.join(dir_flip_vals)}}};")
        if has_dir_frames:
            lines.append(f"#define {sym_use.upper()}_HAS_DIR_FRAMES 1")
        lines.append(f"static const u8 g_{sym_use}_type_can_shoot[] = {{{', '.join(can_shoot_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_type_fire_rate[] = {{{', '.join(fire_rate_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_type_fire_cond[] = {{{', '.join(fire_cond_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_type_fire_range[] = {{{', '.join(fire_range_vals)}}};")
        lines.append(f"static const u8 g_{sym_use}_type_bullet_btype[] = {{{', '.join(bullet_btype_vals)}}};")
        lines.append("")

    # ---- Hurtboxes ----
    lines += [sep, "/* Hurtboxes -- {x, y, w, h} relative to sprite top-left              */", sep]
    any_hb = False
    for t in seen_types:
        meta = sprite_meta.get(t)
        if meta is None:
            lines.append(f"/* {t}: sprite not found in scene */")
            continue
        fw = int(meta.get("frame_w", 8) or 8)
        fh = int(meta.get("frame_h", 8) or 8)
        hb = first_hurtbox(meta, fw, fh)
        x, y = hb.get("x", 0), hb.get("y", 0)
        w = hb.get("w", 0) if box_enabled(hb, True) else 0
        h = hb.get("h", 0) if box_enabled(hb, True) else 0
        cid = _safe_c_id(t)
        lines.append(f"static const NgpngRect g_{cid}_hitbox = {{{int(x)}, {int(y)}, {int(w)}, {int(h)}}};")
        any_hb = True
    if not any_hb:
        lines.append("/* (no hitboxes defined) */")
    lines.append("")

    # ---- Sprite props (optional) ----
    prop_block: list[str] = []
    for t in seen_types:
        meta = sprite_meta.get(t)
        if not meta:
            continue
        props = meta.get("props") or {}
        if not isinstance(props, dict) or not props:
            continue
        cid = _safe_c_id(t)
        prop_block.append(f"/* {t} */")
        for k, v in props.items():
            key = _safe_c_id(str(k))
            try:
                prop_block.append(f"static const u8 g_{cid}_{key} = {int(v)};")
            except Exception:
                continue
    if prop_block:
        lines += [sep, "/* Sprite props (u8)                                                  */", sep]
        lines.extend(prop_block)
        lines.append("")

    # ---- Static entity placement ----
    if entities:
        lines += [sep, f"/* Static entity placement -- g_{sym_use}_entities[]                        */", sep]
        lines.append(f"static const NgpngEnt g_{sym_use}_entities[] = {{")
        for ent in entities:
            c = _type_to_c_const(str(ent.get("type") or ""))
            x, y, d = ent.get("x", 0), ent.get("y", 0), ent.get("data", 0)
            lines.append(f"    {{{c}, {int(x):3d}, {int(y):3d}, {int(d):3d}}},")
        lines.append("    {0}  /* sentinel (type=0) */")
        lines.append("};")
        lines.append(f"#define {sym_use.upper()}_ENTITY_COUNT {len(entities)}")
        lines.append("")

        def _write_u8_table(tname: str, data: list[int], comment: str) -> None:
            lines.append(f"/* {comment} */")
            lines.append(f"static const u8 {tname}[] = {{")
            per = 16
            for i in range(0, len(data), per):
                chunk = ", ".join(f"{int(v) & 0xFF:3d}" for v in data[i:i + per])
                lines.append(f"    {chunk},")
            lines.append("};")
            lines.append("")

        def _write_s16_table(tname: str, data: list[int], comment: str) -> None:
            lines.append(f"/* {comment} */")
            lines.append(f"static const s16 {tname}[] = {{")
            per = 8
            for i in range(0, len(data), per):
                chunk = ", ".join(f"{int(v):6d}" for v in data[i:i + per])
                lines.append(f"    {chunk},")
            lines.append("};")
            lines.append("")

        behs = [int(ent.get("behavior", 0) or 0) & 0xFF for ent in entities]
        if any(b != 0 for b in behs):
            lines.append(f"#define {sym_use.upper()}_ENTITY_BEHAVIOR_TABLE 1")
            _write_u8_table(
                f"g_{sym_use}_ent_behaviors",
                behs,
                "Behavior per entity (0=patrol 1=chase 2=fixed 3=random)",
            )

        # ---- AI parameter tables (optional, only emitted if non-default) ----
        ai_speeds = [max(1, min(255, int(ent.get("ai_speed", 1) or 1))) for ent in entities]
        if any(s != 1 for s in ai_speeds):
            lines.append(f"#define {sym_use.upper()}_ENTITY_AI_SPEED_TABLE 1")
            _write_u8_table(
                f"g_{sym_use}_ent_ai_speed",
                ai_speeds,
                "AI move speed per entity in px/frame (1=default)",
            )

        has_chase = any(int(ent.get("behavior", 0) or 0) == 1 for ent in entities)
        if has_chase:
            ai_ranges = [max(0, min(255, int(ent.get("ai_range", 10) or 10))) for ent in entities]
            ai_loses  = [max(0, min(255, int(ent.get("ai_lose_range", 16) or 16))) for ent in entities]
            lines.append(f"#define {sym_use.upper()}_ENTITY_AI_RANGE_TABLE 1")
            _write_u8_table(
                f"g_{sym_use}_ent_ai_range",
                ai_ranges,
                "Chase aggro range per entity (x8 px, 10=80px default)",
            )
            _write_u8_table(
                f"g_{sym_use}_ent_ai_lose_range",
                ai_loses,
                "Chase lose-aggro range per entity (x8 px, 16=128px default)",
            )

        # OPT-2A-BOUNDS: pre-computed patrol world-X bounds per entity.
        # Only emitted when at least one entity is PATROL (behavior=0).
        # Non-patrol entities get (0,0) = sentinel "no bounds" for the runtime.
        has_patrol = any(int(ent.get("behavior", 0) or 0) == 0 for ent in entities)
        if has_patrol:
            patrol_mins: list[int] = []
            patrol_maxs: list[int] = []
            scene_col_map = scene.get("col_map", None)
            for ent in entities:
                behavior = int(ent.get("behavior", 0) or 0)
                if behavior == 0:
                    type_name = str(ent.get("type", "") or "").strip()
                    meta = sprite_meta.get(type_name) if type_name else None
                    render_off_x = _sprite_render_offset(meta)[0] if isinstance(meta, dict) else 0
                    spawn_wx = int(ent.get("x", 0) or 0) * 8 - int(render_off_x)
                    half_range = max(1, min(255, int(ent.get("ai_range", 10) or 10))) * 8
                    patrol_min = spawn_wx - half_range
                    patrol_max = spawn_wx + half_range
                    flags = int(ent.get("flags", 0) or 0)
                    allow_ledge_fall = bool(flags & 2)
                    gravity = 0
                    if isinstance(meta, dict):
                        props = meta.get("props") or {}
                        if isinstance(props, dict):
                            try:
                                gravity = int(props.get("gravity", 0) or 0)
                            except Exception:
                                gravity = 0
                    if allow_ledge_fall:
                        patrol_mins.append(0)
                        patrol_maxs.append(0)
                        continue
                    if gravity > 0:
                        support_bounds = _derive_patrol_platform_bounds(ent, meta or {}, scene_col_map)
                        if support_bounds is not None:
                            support_min, support_max = support_bounds
                            patrol_min = max(patrol_min, support_min)
                            patrol_max = min(patrol_max, support_max)
                            if patrol_max < patrol_min:
                                anchor = spawn_wx
                                if anchor < support_min:
                                    anchor = support_min
                                elif anchor > support_max:
                                    anchor = support_max
                                patrol_min = anchor
                                patrol_max = anchor
                    patrol_mins.append(patrol_min)
                    patrol_maxs.append(patrol_max)
                else:
                    patrol_mins.append(0)
                    patrol_maxs.append(0)
            lines.append(f"#define {sym_use.upper()}_ENTITY_PATROL_BOUNDS_TABLE 1")
            _write_s16_table(
                f"g_{sym_use}_ent_patrol_min",
                patrol_mins,
                "Patrol lower world-X bound per entity (clamped to support platform when detectable; 0=no bounds)",
            )
            _write_s16_table(
                f"g_{sym_use}_ent_patrol_max",
                patrol_maxs,
                "Patrol upper world-X bound per entity (clamped to support platform when detectable; 0=no bounds)",
            )

        has_random = any(int(ent.get("behavior", 0) or 0) == 3 for ent in entities)
        if has_random:
            ai_change = [max(1, min(255, int(ent.get("ai_change_every", 60) or 60))) for ent in entities]
            lines.append(f"#define {sym_use.upper()}_ENTITY_AI_CHANGE_TABLE 1")
            _write_u8_table(
                f"g_{sym_use}_ent_ai_change_every",
                ai_change,
                "Random behavior direction change period in frames (60=default)",
            )

        path_index_by_id = {
            str(p.get("id", "")): i
            for i, p in enumerate(paths or [])
            if isinstance(p, dict)
        }
        path_idxs: list[int] = []
        for ent in entities:
            pid = str(ent.get("path_id", "") or "")
            path_idxs.append(path_index_by_id[pid] if pid and pid in path_index_by_id else 255)
        _write_u8_table(
            f"g_{sym_use}_ent_paths",
            path_idxs,
            "Patrol path index per entity (255=none)",
        )
        lines.append(f"#define {sym_use.upper()}_ENTITY_PATH_TABLE 1")
        lines.append("")

        ent_flags = [int(ent.get("flags", 0) or 0) & 0xFF for ent in entities]
        if any(flag != 0 for flag in ent_flags):
            lines.append(f"#define {sym_use.upper()}_ENTITY_FLAG_TABLE 1")
            _write_u8_table(
                f"g_{sym_use}_ent_flags",
                ent_flags,
                "Instance flags per entity (bit0=clamp within map)",
            )
    else:
        lines.append(f"#define {sym_use.upper()}_ENTITY_COUNT 0")
        lines.append("")

    # ---- Enemy waves — flat NgpcWaveEntry table (ngpc_wave module) ----
    if waves:
        lines += [
            sep,
            "/* Enemy waves (flat NgpcWaveEntry table — sorted by delay ascending)  */",
            sep,
        ]
        # Build flat list: one NgpcWaveEntry per entity, sorted by delay.
        flat_entries: list[tuple[str, int, int, int, int]] = []  # (type_c, x, y, data, delay)
        for wave in waves:
            delay = int(wave.get("delay", 0) or 0)
            for ent in (wave.get("entities", []) or []):
                if not isinstance(ent, dict):
                    continue
                c = _type_to_c_const(str(ent.get("type") or ""))
                x, y = int(ent.get("x", 0)), int(ent.get("y", 0))
                d = int(ent.get("data", 0))
                flat_entries.append((c, x, y, d, delay))
        # Stable-sort by delay (already sorted if waves list is sorted ascending).
        flat_entries.sort(key=lambda e: e[4])

        U = sym_use.upper()
        lines.append(f"#define {U}_WAVE_TABLE_N {len(flat_entries)}")
        lines.append(f"static const NgpcWaveEntry g_{sym_use}_wave_table[] = {{")
        for wi, (c, x, y, d, delay) in enumerate(flat_entries):
            comment = f"delay={delay}"
            lines.append(f"    {{{c}, {x:3d}, {y:3d}, {d:3d}, {delay:5d}u}},  /* {comment} */")
        lines.append("    {0, 0, 0, 0, 0xFFFFu}  /* WAVE_SENTINEL */")
        lines.append("};")
        lines.append("")

    # Scene dimensions are needed by multiple export sections, including
    # neighbor auto-warp generation below.
    sz = scene.get("level_size", {}) or {}
    map_w = int(sz.get("w", 20)) if isinstance(sz, dict) else 20
    map_h = int(sz.get("h", 19)) if isinstance(sz, dict) else 19

    # ---- Neighbor auto-warp (Track B / MAP-1) ---------------------------
    # JSON: scene["neighbors"] = {"east": "scene_b_id", "west": {"scene": "scene_a_id"}, ...}
    #
    # For each direction that has a neighbor:
    #   - Auto-generates an EXIT trigger region (8 px strip at the map edge) + warp_to trigger.
    #   - Auto-generates an ENTRY spawn region at the corresponding edge (for incoming players).
    #
    # Entry spawn indices follow a FIXED SLOT convention so warp triggers can use predictable
    # spawn_idx values across scenes:
    #   slot 0 = west entry,  slot 1 = east entry,  slot 2 = north entry,  slot 3 = south entry
    # These auto-spawns are PREPENDED so manual user spawn points start at index 4.
    # The warp trigger from scene A exiting east uses spawn_idx = 0 (west entry of target).
    #
    # Pixel coordinates are used for regions (same as runtime NgpngRect).
    _NEIGHBOR_DIRS = ["west", "east", "north", "south"]  # fixed slot order
    _OPPOSITE: dict[str, str] = {"west": "east", "east": "west", "north": "south", "south": "north"}
    _DIR_IDX: dict[str, int] = {d: i for i, d in enumerate(_NEIGHBOR_DIRS)}
    _EDGE_PX = 8  # 1-tile-wide exit trigger strip
    _nb_raw: dict = scene.get("neighbors") or {}
    _auto_entry_spawns: list[dict] = []
    _auto_exit_regs: list[dict] = []
    _auto_trigs: list[dict] = []
    if isinstance(_nb_raw, dict):
        _map_w_px: int = int(map_w) * 8
        _map_h_px: int = int(map_h) * 8
        # Collect directions with valid neighbors (stable iteration via fixed order).
        for _dir in _NEIGHBOR_DIRS:
            _nb = _nb_raw.get(_dir)
            if not _nb:
                continue
            _target_scene = str(_nb if isinstance(_nb, str) else (_nb.get("scene", "") or ""))
            if not _target_scene:
                continue
            # spawn_idx in target = fixed slot of the OPPOSITE direction.
            _opp = _OPPOSITE[_dir]
            _spawn_idx_in_target = _DIR_IDX[_opp]
            # Exit trigger region (8px strip at the edge).
            if _dir == "west":
                _ex, _ey, _ew, _eh = 0, 0, _EDGE_PX, _map_h_px
                _sx, _sy = _EDGE_PX // 2, _map_h_px // 2  # entry spawn center
            elif _dir == "east":
                _ex, _ey, _ew, _eh = max(0, _map_w_px - _EDGE_PX), 0, _EDGE_PX, _map_h_px
                _sx, _sy = _map_w_px - _EDGE_PX // 2, _map_h_px // 2
            elif _dir == "north":
                _ex, _ey, _ew, _eh = 0, 0, _map_w_px, _EDGE_PX
                _sx, _sy = _map_w_px // 2, _EDGE_PX // 2
            else:  # south
                _ex, _ey, _ew, _eh = 0, max(0, _map_h_px - _EDGE_PX), _map_w_px, _EDGE_PX
                _sx, _sy = _map_w_px // 2, _map_h_px - _EDGE_PX // 2
            _auto_exit_regs.append({
                "id": f"_auto_exit_{_dir}",
                "name": f"[auto] exit {_dir}",
                "kind": "zone",
                "x": _ex, "y": _ey, "w": _ew, "h": _eh,
            })
            _auto_trigs.append({
                "cond": "enter_region", "region": f"_auto_exit_{_dir}",
                "action": "warp_to",
                "scene_to": _target_scene,
                "spawn_index": _spawn_idx_in_target,
            })
            # Entry spawn at the SAME edge (players arriving from _dir land here).
            _auto_entry_spawns.append({
                "id": f"_auto_entry_{_dir}",
                "name": f"[auto] entry {_dir}",
                "kind": "spawn",
                "x": _sx - 4, "y": _sy - 4, "w": 8, "h": 8,
                "_slot": _DIR_IDX[_dir],  # for sorting to fixed slot position
            })
        # Sort entry spawns to fixed slots 0-3, drop internal _slot key.
        _auto_entry_spawns.sort(key=lambda s: s.get("_slot", 99))
        for _sp in _auto_entry_spawns:
            _sp.pop("_slot", None)

    # ---- Regions (rectangles in tile coords) ----
    regs = scene.get("regions", []) or []
    regs = [r for r in regs if isinstance(r, dict)]
    # Synthetic 1×1 destination regions from triggers with dest_tile_x/y
    # (move_entity_to, teleport_player, spawn_at_region).
    # Created here so they appear in the exported region array and rid_to_idx.
    _TILE_DEST_ACTS = {"move_entity_to", "teleport_player", "spawn_at_region"}
    _syn_tp_seen: set = set()
    for _t in (scene.get("triggers") or []):
        if not isinstance(_t, dict):
            continue
        if str(_t.get("action", "")).strip().lower() not in _TILE_DEST_ACTS:
            continue
        if str(_t.get("dest_region_id", "") or "").strip():
            continue  # already has an explicit region
        _dtx = _t.get("dest_tile_x")
        _dty = _t.get("dest_tile_y")
        if _dtx is None or _dty is None:
            continue
        _dtx, _dty = int(_dtx), int(_dty)
        if _dtx < 0 or _dty < 0:
            continue
        _syn_id = f"__tp_{str(_t.get('id', ''))}"
        if _syn_id not in _syn_tp_seen:
            _syn_tp_seen.add(_syn_id)
            regs.append({"id": _syn_id, "x": _dtx, "y": _dty, "w": 1, "h": 1, "kind": "zone",
                         "name": f"tp_{_dtx}_{_dty}"})
    # Track B: prepend auto entry spawns (fixed slots 0-3), append auto exit regs.
    if _auto_entry_spawns or _auto_exit_regs:
        regs = _auto_entry_spawns + regs + _auto_exit_regs
    if regs:
        lines += [sep, "/* Regions (tile rectangles)                                           */", sep]
        lines += [
            "#ifndef REGION_KIND_ZONE",
            "#define REGION_KIND_ZONE        0",
            "#define REGION_KIND_NO_SPAWN    1",
            "#define REGION_KIND_DANGER_ZONE 2",
            "#define REGION_KIND_CHECKPOINT  3",
            "#define REGION_KIND_EXIT_GOAL   4",
            "#define REGION_KIND_CAMERA_LOCK 5",
            "#define REGION_KIND_SPAWN       6",
            "#define REGION_KIND_ATTRACTOR   7",
            "#define REGION_KIND_REPULSOR    8",
            "#define REGION_KIND_LAP_GATE    9",
            "#define REGION_KIND_CARD_SLOT   10",
            "#define REGION_KIND_RACE_WP     11",
            "#define REGION_KIND_PUSH_BLOCK  12",
            "#endif",
            "",
            f"#define {sym_use.upper()}_REGION_COUNT {len(regs)}",
            "",
        ]

        def _safe_reg_macro(name: str) -> str:
            clean = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").upper()
            return clean or "REGION"

        used_rmacros: set[str] = set()
        for i, r in enumerate(regs):
            nm = str(r.get("name", "") or f"region_{i}")
            macro = _safe_reg_macro(nm)
            if macro in used_rmacros:
                macro = f"{macro}_{i}"
            used_rmacros.add(macro)
            lines.append(f"#define {sym_use.upper()}_REGION_{macro} {i}")
        lines.append("")

        lines.append(f"static const NgpngRect g_{sym_use}_regions[] = {{")
        for r in regs:
            x = int(r.get("x", 0) or 0)
            y = int(r.get("y", 0) or 0)
            w = int(r.get("w", 1) or 1)
            h = int(r.get("h", 1) or 1)
            lines.append(f"    {{{x}, {y}, {w}, {h}}},")
        lines.append("};")
        lines.append("")

        lines.append(f"static const u8 g_{sym_use}_region_kind[] = {{")
        for r in regs:
            kind = str(r.get("kind", "zone") or "zone")
            kid = (1 if kind == "no_spawn"    else
                   2 if kind == "danger_zone"  else
                   3 if kind == "checkpoint"   else
                   4 if kind == "exit_goal"    else
                   5 if kind == "camera_lock"  else
                   6 if kind == "spawn"        else
                   7 if kind == "attractor"    else
                   8 if kind == "repulsor"     else
                   9 if kind == "lap_gate"     else
                   10 if kind == "card_slot"   else
                   11 if kind == "race_waypoint" else
                   12 if kind == "push_block"   else 0)
            lines.append(f"    {kid},")
        lines.append("};")
        lines.append("")

        # gate_index array — only emitted when at least one lap_gate region exists
        has_lap_gates = any(str(r.get("kind", "")) == "lap_gate" for r in regs)
        if has_lap_gates:
            gate_max = max((int(r.get("gate_index", 0)) for r in regs if str(r.get("kind", "")) == "lap_gate"), default=0)
            lines.append(f"#define {sym_use.upper()}_LAP_GATE_COUNT {gate_max + 1}")
            lines.append("/* gate_index: ordered sequence for lap_gate regions (0=start/finish, 1..N=checkpoints) */")
            lines.append(f"static const u8 g_{sym_use}_region_gate_index[] = {{")
            for r in regs:
                gate_idx = int(r.get("gate_index", 0)) if str(r.get("kind", "")) == "lap_gate" else 0
                lines.append(f"    {gate_idx},")
            lines.append("};")
            lines.append("")

        # AI waypoints — only emitted when at least one race_waypoint region exists
        # Sorted by wp_index; exported as NgpcWaypoint (pixel centers, tile*8+tile_size/2)
        wp_regs = [r for r in regs if isinstance(r, dict) and str(r.get("kind", "")) == "race_waypoint"]
        if wp_regs:
            wp_sorted = sorted(wp_regs, key=lambda r: int(r.get("wp_index", 0)))
            lines.append(f"#define {sym_use.upper()}_WAYPOINT_COUNT {len(wp_sorted)}")
            lines.append("/* NgpcWaypoint forward-declare (no-op if ngpc_vehicle.h already included) */")
            lines.append("#ifndef NGPC_WAYPOINT_T")
            lines.append("#define NGPC_WAYPOINT_T")
            lines.append("typedef struct { s16 x; s16 y; } NgpcWaypoint;")
            lines.append("#endif")
            lines.append("/* AI waypoints: pixel centres sorted by wp_index. Use with ngpc_vehicle_ai_steer(). */")
            lines.append(f"static const NgpcWaypoint g_{sym_use}_waypoints[] = {{")
            for r in wp_sorted:
                wx = int(r.get("x", 0)) * 8 + max(1, int(r.get("w", 2))) * 4
                wy = int(r.get("y", 0)) * 8 + max(1, int(r.get("h", 2))) * 4
                lines.append(f"    {{{wx}, {wy}}},  /* {str(r.get('name', '')) or 'wp'} */")
            lines.append("};")
            lines.append("")

        # slot_type array — only emitted when at least one card_slot region exists
        has_card_slots = any(str(r.get("kind", "")) == "card_slot" for r in regs)
        if has_card_slots:
            lines.append("/* slot_type: per-region card slot type (0=field, 1=hand, 2=discard, 3=deck, 4-15=user-defined) */")
            lines.append(f"static const u8 g_{sym_use}_region_slot_type[] = {{")
            for r in regs:
                if not isinstance(r, dict):
                    continue
                slot_t = int(r.get("slot_type", 0)) if str(r.get("kind", "")) == "card_slot" else 0
                lines.append(f"    {slot_t},")
            lines.append("};")
            lines.append("")

        # Push block initial positions — only emitted when at least one push_block region exists
        pb_regs = [r for r in regs if isinstance(r, dict) and str(r.get("kind", "")) == "push_block"]
        if pb_regs:
            lines.append(f"#define {sym_use.upper()}_PUSH_BLOCK_COUNT {len(pb_regs)}")
            lines.append("/* NgpcPbTile forward-declare (no-op if ngpc_pushblock.h already included) */")
            lines.append("#ifndef NGPC_PB_TILE_T")
            lines.append("#define NGPC_PB_TILE_T")
            lines.append("typedef struct { s16 tx; s16 ty; } NgpcPbTile;")
            lines.append("#endif")
            lines.append("/* Push block initial tile positions. Use ngpc_pushblock_init() to populate pool. */")
            lines.append(f"static const NgpcPbTile g_{sym_use}_push_block_tiles[] = {{")
            for r in pb_regs:
                tx = int(r.get("x", 0))
                ty = int(r.get("y", 0))
                lines.append(f"    {{{tx}, {ty}}},  /* {str(r.get('name', '')) or 'block'} */")
            lines.append("};")
            lines.append("")

        # Spawn points: regions with kind="spawn", exported as NgpngPoint (center pixel)
        spawn_regs = [r for r in regs if str(r.get("kind", "zone") or "zone") == "spawn"]
        if spawn_regs:
            lines.append(f"#define {sym_use.upper()}_SPAWN_COUNT {len(spawn_regs)}")
            lines.append(f"static const NgpngPoint g_{sym_use}_spawn_points[] = {{")
            for r in spawn_regs:
                sx = int(r.get("x", 0) or 0) + max(1, int(r.get("w", 8) or 8)) // 2
                sy = int(r.get("y", 0) or 0) + max(1, int(r.get("h", 8) or 8)) // 2
                lines.append(f"    {{{sx}, {sy}}},  /* {str(r.get('name','')) or 'spawn'} */")
            lines.append("};")
            lines.append("")

    # ---- Text labels (sysfont, ngpc_text_print) ----
    labels = [l for l in (scene.get("text_labels") or []) if isinstance(l, dict)]
    if labels:
        lines += [sep, "/* Text labels (sysfont, ngpc_text_print) */", sep]
        lines.append(f"#define {sym_use.upper()}_TEXT_LABEL_COUNT {len(labels)}")
        lines.append(f"static const u8 g_{sym_use}_text_label_x[]     = {{{', '.join(str(int(l.get('x', 0))) for l in labels)}}};")
        lines.append(f"static const u8 g_{sym_use}_text_label_y[]     = {{{', '.join(str(int(l.get('y', 0))) for l in labels)}}};")
        lines.append(f"static const u8 g_{sym_use}_text_label_pal[]   = {{{', '.join(str(int(l.get('pal', 0))) for l in labels)}}};")
        plane_vals = ['0' if str(l.get('plane', 'scr1')).lower() == 'scr1' else '1' for l in labels]
        lines.append(f"static const u8 g_{sym_use}_text_label_plane[] = {{{', '.join(plane_vals)}}};  /* 0=SCR1 1=SCR2 */")
        lines.append(f"static const char * const g_{sym_use}_text_labels[] = {{")
        for l in labels:
            txt = str(l.get('text') or '').replace('\\', '\\\\').replace('"', '\\"')[:20]
            lines.append(f'    "{txt}",')
        lines.append("};")
        lines.append("")

    # ---- Triggers (conditions -> actions) ----
    trigs = scene.get("triggers", []) or []
    trigs = [t for t in trigs if isinstance(t, dict)]
    # Track B: append auto-generated neighbor warp triggers.
    if _auto_trigs:
        trigs = trigs + _auto_trigs
    if trigs:
        # Region id -> index lookup
        rid_to_idx: dict[str, int] = {}
        for i, r in enumerate(regs):
            rid = str(r.get("id") or "").strip()
            if rid:
                rid_to_idx[rid] = int(i)

        cond_to_id = {
            "enter_region": 0,
            "leave_region": 1,
            "cam_x_ge": 2,
            "cam_y_ge": 3,
            "timer_ge": 4,
            "wave_ge": 5,
            "btn_a": 6,
            "btn_b": 7,
            "btn_a_b": 8,
            "btn_up": 9,
            "btn_down": 10,
            "btn_left": 11,
            "btn_right": 12,
            "btn_opt": 13,
            "on_jump": 14,
            "wave_cleared": 15,
            "health_le": 16,
            "health_ge": 17,
            "enemy_count_le": 18,
            "lives_le": 19,
            "lives_ge": 20,
            "collectible_count_ge": 21,
            "flag_set":      22,
            "flag_clear":    23,
            "variable_ge":   24,
            "variable_eq":   25,
            "timer_every":        26,
            "scene_first_enter":  27,
            "on_nth_jump":        28,
            "on_wall_left":       29,
            "on_wall_right":      30,
            "on_ladder":          31,
            "on_ice":             32,
            "on_conveyor":        33,
            "on_spring":          34,
            "player_has_item":    35,
            "npc_talked_to":      36,
            "count_eq":           37,
            "entity_alive":       38,
            "entity_dead":        39,
            "quest_stage_eq":     40,
            "ability_unlocked":   41,
            "resource_ge":        42,
            "combo_ge":           43,
            "lap_ge":             44,
            "btn_held_ge":        45,
            "chance":             46,
            "on_land":        47,
            "on_hurt":        48,
            "on_death":       49,
            "score_ge":       50,
            "timer_le":       51,
            "variable_le":    52,
            "on_crouch":      53,
            "cutscene_done":  54,
            "enemy_count_ge":  55,
            "variable_ne":     56,
            "health_eq":       57,
            "on_swim":         58,
            "on_dash":         59,
            "on_attack":       60,
            "on_pickup":       61,
            "entity_in_region":62,
            "all_switches_on": 63,
            "block_on_tile":   64,
            "dialogue_done":   65,
            "choice_result":   66,
            "menu_result":     67,
            "entity_contact":  68,
        }

        act_to_id = {
            "emit_event": 0,
            "play_sfx": 1,
            "start_bgm": 2,
            "stop_bgm": 3,
            "fade_bgm": 4,
            "goto_scene": 5,
            "add_score": 17,
            "spawn_wave": 6,
            "pause_scroll": 7,
            "resume_scroll": 8,
            "spawn_entity": 9,
            "set_scroll_speed": 10,
            "play_anim": 11,
            "force_jump": 12,
            "fire_player_shot": 23,
            "enable_trigger": 13,
            "disable_trigger": 14,
            "screen_shake": 15,
            "set_cam_target": 16,
            "show_entity": 18,
            "hide_entity": 19,
            "move_entity_to": 20,
            "pause_entity_path": 26,
            "resume_entity_path": 27,
            "cycle_player_form": 21,
            "set_player_form": 22,
            "set_checkpoint":  24,
            "respawn_player":  25,
            "set_flag":        28,
            "clear_flag":      29,
            "set_variable":    30,
            "inc_variable":    31,
            "warp_to":         32,
            "lock_player_input":   33,
            "unlock_player_input": 34,
            "enable_multijump":    35,
            "disable_multijump":   36,
            "reset_scene":         37,
            "show_dialogue":       38,
            "give_item":           39,
            "remove_item":         40,
            "unlock_door":         41,
            "enable_wall_grab":    42,
            "disable_wall_grab":   43,
            "set_gravity_dir":     44,
            "add_resource":        45,
            "remove_resource":     46,
            "unlock_ability":      47,
            "set_quest_stage":     48,
            "play_cutscene":       49,
            "end_game":            50,
            "dec_variable":   51,
            "add_health":     52,
            "set_health":     53,
            "add_lives":      54,
            "set_lives":      55,
            "destroy_entity": 56,
            "teleport_player":57,
            "toggle_flag":    58,
            "set_score":      59,
            "set_timer":      60,
            "pause_timer":    61,
            "resume_timer":   62,
            "fade_out":        63,
            "fade_in":         64,
            "camera_lock":     65,
            "camera_unlock":   66,
            "add_combo":       67,
            "reset_combo":     68,
            "flash_screen":    69,
            "spawn_at_region": 70,
            "save_game":       71,
            "set_bgm_volume":  72,
            "toggle_tile":     73,
            "set_npc_dialogue": 74,
            "open_menu":        75,
            "flip_sprite_h":   76,
            "flip_sprite_v":   77,
        }

        lines += [sep, "/* Triggers (conditions -> actions)                                    */", sep]
        lines += [
            "#ifndef TRIG_ENTER_REGION",
            "#define TRIG_ENTER_REGION 0",
            "#define TRIG_LEAVE_REGION 1",
            "#define TRIG_CAM_X_GE     2",
            "#define TRIG_CAM_Y_GE     3",
            "#define TRIG_TIMER_GE     4",
            "#define TRIG_WAVE_GE      5",
            "#define TRIG_BTN_A        6",
            "#define TRIG_BTN_B        7",
            "#define TRIG_BTN_A_B      8",
            "#define TRIG_BTN_UP       9",
            "#define TRIG_BTN_DOWN     10",
            "#define TRIG_BTN_LEFT     11",
            "#define TRIG_BTN_RIGHT    12",
            "#define TRIG_BTN_OPT      13",
            "#define TRIG_ON_JUMP      14",
            "#define TRIG_WAVE_CLEARED 15",
            "#define TRIG_HEALTH_LE    16",
            "#define TRIG_HEALTH_GE    17",
            "#define TRIG_ENEMY_COUNT_LE 18",
            "#define TRIG_LIVES_LE    19",
            "#define TRIG_LIVES_GE    20",
            "#define TRIG_COLLECTIBLE_COUNT_GE 21",
            "#define TRIG_FLAG_SET     22",
            "#define TRIG_FLAG_CLEAR   23",
            "#define TRIG_VARIABLE_GE  24",
            "#define TRIG_VARIABLE_EQ  25",
            "#define TRIG_TIMER_EVERY       26",
            "#define TRIG_SCENE_FIRST_ENTER 27",
            "#define TRIG_ON_NTH_JUMP       28",
            "#define TRIG_ON_WALL_LEFT      29",
            "#define TRIG_ON_WALL_RIGHT     30",
            "#define TRIG_ON_LADDER         31",
            "#define TRIG_ON_ICE            32",
            "#define TRIG_ON_CONVEYOR       33",
            "#define TRIG_ON_SPRING         34",
            "#define TRIG_PLAYER_HAS_ITEM   35",
            "#define TRIG_NPC_TALKED_TO     36",
            "#define TRIG_COUNT_EQ          37",
            "#define TRIG_ENTITY_ALIVE      38",
            "#define TRIG_ENTITY_DEAD       39",
            "#define TRIG_QUEST_STAGE_EQ    40",
            "#define TRIG_ABILITY_UNLOCKED  41",
            "#define TRIG_RESOURCE_GE       42",
            "#define TRIG_COMBO_GE          43",
            "#define TRIG_LAP_GE            44",
            "#define TRIG_BTN_HELD_GE       45",
            "#define TRIG_CHANCE            46",
            "#define TRIG_ON_LAND         47",
            "#define TRIG_ON_HURT         48",
            "#define TRIG_ON_DEATH        49",
            "#define TRIG_SCORE_GE        50",
            "#define TRIG_TIMER_LE        51",
            "#define TRIG_VARIABLE_LE     52",
            "#define TRIG_ON_CROUCH       53",
            "#define TRIG_CUTSCENE_DONE   54",
            "#define TRIG_ENEMY_COUNT_GE  55",
            "#define TRIG_VARIABLE_NE     56",
            "#define TRIG_HEALTH_EQ       57",
            "#define TRIG_ON_SWIM         58",
            "#define TRIG_ON_DASH         59",
            "#define TRIG_ON_ATTACK       60",
            "#define TRIG_ON_PICKUP       61",
            "#define TRIG_ENTITY_IN_REGION 62",
            "#define TRIG_ALL_SWITCHES_ON  63",
            "#define TRIG_BLOCK_ON_TILE    64",
            "#define TRIG_DIALOGUE_DONE    65",
            "#define TRIG_CHOICE_RESULT    66",
            "#define TRIG_MENU_RESULT      67",
            "#define TRIG_ENTITY_CONTACT   68",
            "#endif",
            "",
            "#ifndef TRIG_ACT_EMIT_EVENT",
            "#define TRIG_ACT_EMIT_EVENT 0",
            "#define TRIG_ACT_PLAY_SFX   1",
            "#define TRIG_ACT_START_BGM  2",
            "#define TRIG_ACT_STOP_BGM   3",
            "#define TRIG_ACT_FADE_BGM   4",
            "#define TRIG_ACT_GOTO_SCENE 5",
            "#define TRIG_ACT_ADD_SCORE  17",
            "#define TRIG_ACT_SPAWN_WAVE 6",
            "#define TRIG_ACT_PAUSE_SCROLL 7",
            "#define TRIG_ACT_RESUME_SCROLL 8",
            "#define TRIG_ACT_SPAWN_ENTITY 9",
            "#define TRIG_ACT_SET_SCROLL_SPEED 10",
            "#define TRIG_ACT_PLAY_ANIM 11",
            "#define TRIG_ACT_FORCE_JUMP 12",
            "#define TRIG_ACT_ENABLE_TRIGGER 13",
            "#define TRIG_ACT_DISABLE_TRIGGER 14",
            "#define TRIG_ACT_SCREEN_SHAKE 15",
            "#define TRIG_ACT_SET_CAM_TARGET 16",
            "#define TRIG_ACT_SHOW_ENTITY 18",
            "#define TRIG_ACT_HIDE_ENTITY 19",
            "#define TRIG_ACT_MOVE_ENTITY_TO 20",
            "#define TRIG_ACT_CYCLE_PLAYER_FORM 21",
            "#define TRIG_ACT_SET_PLAYER_FORM 22",
            "#define TRIG_ACT_FIRE_PLAYER_SHOT 23",
            "#define TRIG_ACT_SET_CHECKPOINT 24",
            "#define TRIG_ACT_RESPAWN_PLAYER 25",
            "#define TRIG_ACT_PAUSE_ENTITY_PATH 26",
            "#define TRIG_ACT_RESUME_ENTITY_PATH 27",
            "#define TRIG_ACT_SET_FLAG     28",
            "#define TRIG_ACT_CLEAR_FLAG   29",
            "#define TRIG_ACT_SET_VARIABLE 30",
            "#define TRIG_ACT_INC_VARIABLE 31",
            "#define TRIG_ACT_WARP_TO      32",
            "#define TRIG_ACT_LOCK_PLAYER_INPUT   33",
            "#define TRIG_ACT_UNLOCK_PLAYER_INPUT 34",
            "#define TRIG_ACT_ENABLE_MULTIJUMP    35",
            "#define TRIG_ACT_DISABLE_MULTIJUMP   36",
            "#define TRIG_ACT_RESET_SCENE         37",
            "#define TRIG_ACT_SHOW_DIALOGUE       38",
            "#define TRIG_ACT_GIVE_ITEM           39",
            "#define TRIG_ACT_REMOVE_ITEM         40",
            "#define TRIG_ACT_UNLOCK_DOOR         41",
            "#define TRIG_ACT_ENABLE_WALL_GRAB    42",
            "#define TRIG_ACT_DISABLE_WALL_GRAB   43",
            "#define TRIG_ACT_SET_GRAVITY_DIR     44",
            "#define TRIG_ACT_ADD_RESOURCE        45",
            "#define TRIG_ACT_REMOVE_RESOURCE     46",
            "#define TRIG_ACT_UNLOCK_ABILITY      47",
            "#define TRIG_ACT_SET_QUEST_STAGE     48",
            "#define TRIG_ACT_PLAY_CUTSCENE       49",
            "#define TRIG_ACT_END_GAME            50",
            "#define TRIG_ACT_DEC_VARIABLE    51",
            "#define TRIG_ACT_ADD_HEALTH      52",
            "#define TRIG_ACT_SET_HEALTH      53",
            "#define TRIG_ACT_ADD_LIVES       54",
            "#define TRIG_ACT_SET_LIVES       55",
            "#define TRIG_ACT_DESTROY_ENTITY  56",
            "#define TRIG_ACT_TELEPORT_PLAYER 57",
            "#define TRIG_ACT_TOGGLE_FLAG     58",
            "#define TRIG_ACT_SET_SCORE       59",
            "#define TRIG_ACT_SET_TIMER       60",
            "#define TRIG_ACT_PAUSE_TIMER     61",
            "#define TRIG_ACT_RESUME_TIMER    62",
            "#define TRIG_ACT_FADE_OUT        63",
            "#define TRIG_ACT_FADE_IN         64",
            "#define TRIG_ACT_CAMERA_LOCK     65",
            "#define TRIG_ACT_CAMERA_UNLOCK   66",
            "#define TRIG_ACT_ADD_COMBO       67",
            "#define TRIG_ACT_RESET_COMBO     68",
            "#define TRIG_ACT_FLASH_SCREEN    69",
            "#define TRIG_ACT_SPAWN_AT_REGION 70",
            "#define TRIG_ACT_SAVE_GAME       71",
            "#define TRIG_ACT_SET_BGM_VOLUME  72",
            "#define TRIG_ACT_TOGGLE_TILE     73",
            "#define TRIG_ACT_SET_NPC_DIALOGUE 74",
            "#define TRIG_ACT_OPEN_MENU        75",
            "#endif",
            "",
            "#ifndef NGPNG_TRIGGER_T",
            "#define NGPNG_TRIGGER_T",
            "typedef struct { u8 cond; u8 region; u16 value; u8 action; u8 a0; u8 a1; u8 once; } NgpngTrigger;",
            "#endif",
            "",
            f"#define {sym_use.upper()}_TRIGGER_COUNT {len(trigs)}",
            "",
        ]

        def _safe_trig_macro(name: str) -> str:
            clean = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").upper()
            return clean or "TRIG"

        used_tmacros: set[str] = set()
        for i, t in enumerate(trigs):
            nm = str(t.get("name", "") or f"trig_{i}")
            macro = _safe_trig_macro(nm)
            if macro in used_tmacros:
                macro = f"{macro}_{i}"
            used_tmacros.add(macro)
            lines.append(f"#define {sym_use.upper()}_TRIG_{macro} {i}")
        lines.append("")

        # Build project scene id -> index map (for goto_scene exports).
        scene_id_to_idx: dict[str, int] = {}
        scenes_pd = project_data.get("scenes", []) if isinstance(project_data, dict) else []
        if isinstance(scenes_pd, list):
            for i, s in enumerate(scenes_pd):
                if not isinstance(s, dict):
                    continue
                sid = str(s.get("id") or "").strip()
                if sid:
                    scene_id_to_idx[sid] = int(i)
        sfx_project_to_game: dict[int, int] = {}
        sfx_game_count = 0
        audio_pd = project_data.get("audio", {}) if isinstance(project_data, dict) else {}
        if isinstance(audio_pd, dict):
            sfx_map_rows = audio_pd.get("sfx_map", []) or []
            if isinstance(sfx_map_rows, list):
                sfx_game_count = len(sfx_map_rows)
                for game_idx, row in enumerate(sfx_map_rows):
                    if not isinstance(row, dict):
                        continue
                    try:
                        project_idx = int(row.get("project_id", game_idx))
                    except Exception:
                        continue
                    sfx_project_to_game[project_idx] = int(game_idx)

        lines.append(f"static const NgpngTrigger g_{sym_use}_triggers[] = {{")
        for t in trigs:
            cond = str(t.get("cond", "enter_region") or "enter_region")
            cid = int(cond_to_id.get(cond, 0))
            rid = str(t.get("region_id", "") or "").strip()
            # Flag/variable conditions use flag_var_index (0..7) packed into the
            # C `region` field instead of a region array index.
            # Must match _TRIGGER_FLAG_CONDS | _TRIGGER_VAR_CONDS in level_tab.py.
            if cond in ("flag_set", "flag_clear", "variable_ge", "variable_eq",
                        "count_eq", "quest_stage_eq", "resource_ge",
                        "variable_le", "variable_ne"):
                region_idx = int(t.get("flag_var_index", 0) or 0) & 0xFF
            else:
                region_idx = int(rid_to_idx.get(rid, 255))
            try:
                value = int(t.get("value", 0) or 0) & 0xFFFF
            except Exception:
                value = 0
            value_const = str(t.get("value_const", "") or "").strip()
            if value_const and re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', value_const):
                value_expr = f"(u16){value_const}"
            else:
                value_expr = f"(u16){value}"
            # dialogue_done: value = dlg_idx resolved from cond_dialogue_id
            if cond == "dialogue_done":
                cdid = str(t.get("cond_dialogue_id", "") or "").strip()
                if cdid:
                    dlgs = scene.get("dialogues") or []
                    cdidx = next((i for i, d in enumerate(dlgs)
                                  if str(d.get("id", "") or "").strip() == cdid), None)
                    if cdidx is not None:
                        value = int(cdidx) & 0xFFFF
                        value_expr = f"(u16){value}"
            # choice_result: region = dlg_idx, value = choice_idx
            elif cond == "choice_result":
                cdid = str(t.get("cond_dialogue_id", "") or "").strip()
                if cdid:
                    dlgs = scene.get("dialogues") or []
                    cdidx = next((i for i, d in enumerate(dlgs)
                                  if str(d.get("id", "") or "").strip() == cdid), None)
                    if cdidx is not None:
                        region_idx = int(cdidx) & 0xFF
                value = int(t.get("choice_idx", 0) or 0) & 0xFFFF
                value_expr = f"(u16){value}"
            # menu_result: region = menu_idx, value = item_idx
            elif cond == "menu_result":
                cmid = str(t.get("cond_menu_id", "") or "").strip()
                if cmid:
                    menus = scene.get("menus") or []
                    cmidx = next((i for i, m in enumerate(menus)
                                  if str(m.get("id", "") or "").strip() == cmid), None)
                    if cmidx is not None:
                        region_idx = int(cmidx) & 0xFF
                value = int(t.get("menu_item_idx", 0) or 0) & 0xFFFF
                value_expr = f"(u16){value}"
            act = str(t.get("action", "") or "").strip().lower()
            if not act:
                # Back-compat: old projects had only event/param (emit_event).
                act = "emit_event"
            aid = int(act_to_id.get(act, 0))
            # goto_scene / warp_to: prefer stable scene id mapping when present.
            try:
                if act in ("goto_scene", "warp_to"):
                    sid = str(t.get("scene_to", "") or "").strip()
                    if sid and sid in scene_id_to_idx:
                        a0 = int(scene_id_to_idx[sid]) & 0xFF
                    else:
                        a0 = int(t.get("a0", t.get("event", 0)) or 0) & 0xFF
                elif act in ("enable_trigger", "disable_trigger"):
                    tid = str(t.get("target_id", "") or "").strip()
                    if tid:
                        resolved = next(
                            (i for i, trig in enumerate(trigs) if str(trig.get("id", "") or "").strip() == tid),
                            None,
                        )
                        if resolved is not None:
                            a0 = int(resolved) & 0xFF
                        else:
                            a0 = int(t.get("a0", t.get("event", 0)) or 0) & 0xFF
                    else:
                        a0 = int(t.get("a0", t.get("event", 0)) or 0) & 0xFF
                elif act == "show_dialogue":
                    # a0 = dialogue index in scene["dialogues"]
                    dlg_id = str(t.get("dialogue_id", "") or "").strip()
                    dlgs = scene.get("dialogues") or []
                    if dlg_id:
                        resolved = next(
                            (i for i, d in enumerate(dlgs)
                             if str(d.get("id", "") or "").strip() == dlg_id),
                            None,
                        )
                        a0 = (0 if resolved is None else int(resolved)) & 0xFF
                    else:
                        a0 = int(t.get("a0", 0) or 0) & 0xFF
                elif act in ("set_flag", "clear_flag", "set_variable", "inc_variable",
                             "dec_variable", "toggle_flag"):
                    # a0 = flag/var index (0..7)
                    # Must match needs_fv_action in level_tab.py.
                    a0 = int(t.get("flag_var_index", 0) or 0) & 0xFF
                elif act in ("show_entity", "hide_entity", "move_entity_to",
                             "pause_entity_path", "resume_entity_path"):
                    ent_target_id = str(t.get("entity_target_id", "") or "").strip()
                    if ent_target_id:
                        resolved = next(
                            (i for i, ent in enumerate(entities) if str(ent.get("id", "") or "").strip() == ent_target_id),
                            None,
                        )
                        a0 = (255 if resolved is None else int(resolved)) & 0xFF
                    else:
                        a0 = int(t.get("entity_index", t.get("event", 0)) or 0) & 0xFF
                elif act == "play_sfx":
                    raw_sfx = int(t.get("a0", t.get("event", 0)) or 0)
                    if 0 <= raw_sfx < sfx_game_count:
                        a0 = raw_sfx & 0xFF
                    else:
                        a0 = int(sfx_project_to_game.get(raw_sfx, raw_sfx)) & 0xFF
                elif act == "toggle_tile":
                    # a0 = dest_region index (the region defining the tile area to toggle)
                    rid = str(t.get("dest_region_id", "") or "").strip()
                    if rid and rid in rid_to_idx:
                        a0 = int(rid_to_idx[rid]) & 0xFF
                    else:
                        a0 = int(t.get("a0", 0) or 0) & 0xFF
                elif act == "open_menu":
                    mid = str(t.get("menu_id", "") or "").strip()
                    if mid:
                        menus = scene.get("menus") or []
                        midx = next((i for i, m in enumerate(menus)
                                     if str(m.get("id", "") or "").strip() == mid), None)
                        a0 = (0 if midx is None else int(midx)) & 0xFF
                    else:
                        a0 = int(t.get("a0", 0) or 0) & 0xFF
                elif act == "set_npc_dialogue":
                    ent_target_id = str(t.get("entity_target_id", "") or "").strip()
                    if ent_target_id:
                        resolved = next(
                            (i for i, ent in enumerate(entities)
                             if str(ent.get("id", "") or "").strip() == ent_target_id),
                            None,
                        )
                        a0 = (255 if resolved is None else int(resolved)) & 0xFF
                    else:
                        a0 = int(t.get("a0", 0) or 0) & 0xFF
                else:
                    a0 = int(t.get("a0", t.get("event", 0)) or 0) & 0xFF
            except Exception:
                a0 = 0
            try:
                if act == "warp_to":
                    a1 = int(t.get("spawn_index", 0) or 0) & 0xFF
                else:
                    a1_raw = int(t.get("a1", t.get("param", 0)) or 0)
                    if act in ("move_entity_to", "teleport_player", "spawn_at_region"):
                        rid = str(t.get("dest_region_id", "") or "").strip()
                        if not rid:
                            # Fall back to synthetic region from dest_tile_x/y
                            _dtx2 = t.get("dest_tile_x")
                            _dty2 = t.get("dest_tile_y")
                            if _dtx2 is not None and _dty2 is not None and int(_dtx2) >= 0 and int(_dty2) >= 0:
                                rid = f"__tp_{str(t.get('id', ''))}"
                        if rid:
                            a1_raw = int(rid_to_idx.get(rid, a1_raw))
                    elif act == "toggle_tile":
                        # a1 = tile type to set (0=pass, 1=solid…); stored in param
                        a1_raw = int(t.get("param", 0) or 0)
                    elif act == "set_npc_dialogue":
                        npc_did = str(t.get("npc_dialogue_id", "") or "").strip()
                        if npc_did:
                            dlgs = scene.get("dialogues") or []
                            npc_didx = next((i for i, d in enumerate(dlgs)
                                             if str(d.get("id", "") or "").strip() == npc_did), None)
                            if npc_didx is not None:
                                a1_raw = int(npc_didx)
                    a1 = int(a1_raw) & 0xFF
            except Exception:
                a1 = 0
            once = 1 if bool(t.get("once", True)) else 0
            lines.append(f"    {{{cid}, {region_idx}, {value_expr}, {aid}, {a0}, {a1}, {once}}},")
        lines.append("};")
        lines.append("")

        all_extra: list[list[dict]] = [
            [ec for ec in (t.get("extra_conds", []) or []) if isinstance(ec, dict)]
            if isinstance(t, dict) else []
            for t in trigs
        ]
        if any(len(ecs) > 0 for ecs in all_extra):
            lines += [
                "#ifndef NGPNG_COND_T",
                "#define NGPNG_COND_T",
                "typedef struct { u8 cond; u8 region; u16 value; } NgpngCond;",
                "#endif",
                "",
                f"#define {sym_use.upper()}_TRIG_EXTRA_CONDS 1",
                "",
            ]
            flat_conds: list[tuple[int, int, int]] = []
            cond_starts: list[int] = []
            cond_counts: list[int] = []
            for ecs in all_extra:
                cond_starts.append(len(flat_conds))
                cond_counts.append(len(ecs))
                for ec in ecs:
                    ec_cond = str(ec.get("cond", "enter_region") or "enter_region")
                    ec_cid = int(cond_to_id.get(ec_cond, 0))
                    ec_rid = str(ec.get("region_id", "") or "").strip()
                    ec_ridx = int(rid_to_idx.get(ec_rid, 255))
                    ec_val = int(ec.get("value", 0) or 0) & 0xFFFF
                    flat_conds.append((ec_cid, ec_ridx, ec_val))

            lines.append(f"static const NgpngCond g_{sym_use}_trig_conds[] = {{")
            for (ec_cid, ec_ridx, ec_val) in flat_conds:
                lines.append(f"    {{{ec_cid}, {ec_ridx}, (u16){ec_val}}},")
            lines.append("};")
            lines.append("")
            lines.append(f"static const u8 g_{sym_use}_trig_cond_count[] = {{{', '.join(str(v) for v in cond_counts)}}};")
            lines.append(f"static const u8 g_{sym_use}_trig_cond_start[] = {{{', '.join(str(v) for v in cond_starts)}}};")
            lines.append("")

        # OR-groups: trigger fires if primary+extra_conds OR any or_group is all-true
        all_or_groups: list[list[list[dict]]] = [
            [
                [ec for ec in (og or []) if isinstance(ec, dict)]
                for og in (t.get("or_groups", []) or [])
                if isinstance(og, list)
            ]
            if isinstance(t, dict) else []
            for t in trigs
        ]
        if any(len(ogs) > 0 for ogs in all_or_groups):
            lines += [
                "#ifndef NGPNG_COND_T",
                "#define NGPNG_COND_T",
                "typedef struct { u8 cond; u8 region; u16 value; } NgpngCond;",
                "#endif",
                "",
                f"#define {sym_use.upper()}_TRIG_HAS_OR_GROUPS 1",
                "",
            ]
            flat_or_conds: list[tuple[int, int, int]] = []
            or_cond_starts: list[int] = []
            or_cond_counts: list[int] = []
            or_group_starts: list[int] = []
            or_group_counts: list[int] = []
            for ogs in all_or_groups:
                or_group_starts.append(len(or_cond_starts))
                or_group_counts.append(len(ogs))
                for og in ogs:
                    or_cond_starts.append(len(flat_or_conds))
                    or_cond_counts.append(len(og))
                    for ec in og:
                        ec_cond = str(ec.get("cond", "enter_region") or "enter_region")
                        ec_cid = int(cond_to_id.get(ec_cond, 0))
                        ec_rid = str(ec.get("region_id", "") or "").strip()
                        ec_ridx = int(rid_to_idx.get(ec_rid, 255))
                        ec_val = int(ec.get("value", 0) or 0) & 0xFFFF
                        flat_or_conds.append((ec_cid, ec_ridx, ec_val))
            lines.append(f"static const NgpngCond g_{sym_use}_trig_or_conds[] = {{")
            for (oc_cid, oc_ridx, oc_val) in flat_or_conds:
                lines.append(f"    {{{oc_cid}, {oc_ridx}, (u16){oc_val}}},")
            if not flat_or_conds:
                lines.append("    {0, 0, (u16)0}  /* sentinel — no OR-group conditions */")
            lines.append("};")
            lines.append("")
            lines.append(f"static const u8 g_{sym_use}_trig_or_cond_start[] = {{{', '.join(str(v) for v in or_cond_starts)}}};")
            lines.append(f"static const u8 g_{sym_use}_trig_or_cond_count[] = {{{', '.join(str(v) for v in or_cond_counts)}}};")
            lines.append(f"static const u8 g_{sym_use}_trig_or_group_start[] = {{{', '.join(str(v) for v in or_group_starts)}}};")
            lines.append(f"static const u8 g_{sym_use}_trig_or_group_count[] = {{{', '.join(str(v) for v in or_group_counts)}}};")
            lines.append("")

    # ---- Paths (routes; points in tile coords) ----
    pths = scene.get("paths", []) or []
    pths = [p for p in pths if isinstance(p, dict)]
    if pths:
        lines += [sep, "/* Paths (routes)                                                     */", sep]
        lines += [
            "#ifndef NGPNG_POINT_T",
            "#define NGPNG_POINT_T",
            "typedef struct { u8 x; u8 y; } NgpngPoint;",
            "#endif",
            "",
            f"#define {sym_use.upper()}_PATH_COUNT {len(pths)}",
            "",
        ]

        def _safe_path_macro(name: str) -> str:
            clean = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").upper()
            return clean or "PATH"

        used_pmacros: set[str] = set()
        for i, p in enumerate(pths):
            nm = str(p.get("name", "") or f"path_{i}")
            macro = _safe_path_macro(nm)
            if macro in used_pmacros:
                macro = f"{macro}_{i}"
            used_pmacros.add(macro)
            lines.append(f"#define {sym_use.upper()}_PATH_{macro} {i}")
        lines.append("")

        points_flat: list[tuple[int, int]] = []
        offsets: list[int] = []
        lengths: list[int] = []
        flags: list[int] = []
        speeds: list[int] = []

        for p in pths:
            offsets.append(len(points_flat))
            pts_in = p.get("points", []) or []
            pts: list[tuple[int, int]] = []
            if isinstance(pts_in, list):
                for pt in pts_in:
                    if isinstance(pt, dict):
                        pts.append((int(pt.get("x", 0)) & 0xFF, int(pt.get("y", 0)) & 0xFF))
                    elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        pts.append((int(pt[0]) & 0xFF, int(pt[1]) & 0xFF))
            points_flat.extend(pts)
            lengths.append(len(pts))
            flags.append(1 if bool(p.get("loop", False)) else 0)
            speeds.append(max(1, min(8, int(p.get("speed", 1)))))

        if not points_flat:
            points_flat = [(0, 0)]

        lines.append(f"static const u16 g_{sym_use}_path_offsets[] = {{ " + ", ".join(str(int(o)) for o in offsets) + " };")
        lines.append(f"static const u8  g_{sym_use}_path_lengths[] = {{ " + ", ".join(str(int(n) & 0xFF) for n in lengths) + " };")
        lines.append(f"static const u8  g_{sym_use}_path_flags[]   = {{ " + ", ".join(str(int(f) & 0xFF) for f in flags) + " };")
        lines.append(f"static const u8  g_{sym_use}_path_speeds[]  = {{ " + ", ".join(str(int(s) & 0xFF) for s in speeds) + " };")
        lines.append("")
        lines.append(f"static const NgpngPoint g_{sym_use}_path_points[] = {{")
        for x, y in points_flat:
            lines.append(f"    {{{int(x) & 0xFF}, {int(y) & 0xFF}}},")
        lines.append("};")
        lines.append("")

    # ---- Layout / scrolling metadata ----
    layers = scene.get("level_layers", {}) or {}
    layers = layers if isinstance(layers, dict) else {}

    bg_front = str(layers.get("bg_front") or scene.get("level_bg_front") or "scr1").strip().lower()
    if bg_front not in ("scr1", "scr2"):
        bg_front = "scr1"
    bg_scr1 = str(scene.get("level_bg_scr1") or "").strip()
    bg_scr2 = str(scene.get("level_bg_scr2") or "").strip()
    bg_scr1_c = bg_scr1.replace("\\", "/").replace("\"", "")
    bg_scr2_c = bg_scr2.replace("\\", "/").replace("\"", "")

    cam = scene.get("level_cam_tile", {}) or {}
    cam_x = int(cam.get("x", 0)) if isinstance(cam, dict) else 0
    cam_y = int(cam.get("y", 0)) if isinstance(cam, dict) else 0
    sc = scene.get("level_scroll", {}) or {}
    sc = sc if isinstance(sc, dict) else {}

    layout = scene.get("level_layout", {}) or {}
    layout = layout if isinstance(layout, dict) else {}
    cam_mode = str(layout.get("cam_mode", "") or "").strip()
    if cam_mode not in _CAM_MODE_TO_C:
        if bool(sc.get("forced", False)):
            cam_mode = "forced_scroll"
        elif bool(sc.get("loop_x", False)) or bool(sc.get("loop_y", False)):
            cam_mode = "loop"
        elif bool(sc.get("scroll_x", False)) or bool(sc.get("scroll_y", False)):
            cam_mode = "follow"
        else:
            cam_mode = "single_screen"
    clamp = 1 if bool(layout.get("clamp", True)) else 0
    bounds_auto = bool(layout.get("bounds_auto", True))
    if bounds_auto:
        min_x = 0
        min_y = 0
        max_x = max(0, (int(map_w) - 20) * 8)
        max_y = max(0, (int(map_h) - 19) * 8)
    else:
        min_x = int(layout.get("min_x", 0) or 0) * 8
        min_y = int(layout.get("min_y", 0) or 0) * 8
        max_x = int(layout.get("max_x", 0) or 0) * 8
        max_y = int(layout.get("max_y", 0) or 0) * 8
    follow_deadzone_x = max(0, min(79, int(layout.get("follow_deadzone_x", 16) or 16)))
    follow_deadzone_y = max(0, min(71, int(layout.get("follow_deadzone_y", 12) or 12)))
    follow_drop_margin_y = max(0, min(71, int(layout.get("follow_drop_margin_y", 20) or 20)))
    cam_lag = max(0, min(4, int(layout.get("cam_lag", 0) or 0)))

    def _clip_pct(v: int) -> int:
        try:
            v = int(v)
        except Exception:
            v = 100
        return max(0, min(200, v))

    scr1_px = _clip_pct(layers.get("scr1_parallax_x", 100))
    scr1_py = _clip_pct(layers.get("scr1_parallax_y", 100))
    scr2_px = _clip_pct(layers.get("scr2_parallax_x", 100))
    scr2_py = _clip_pct(layers.get("scr2_parallax_y", 100))
    # If the scene has dialogues and SCR2 has no background, force SCR2 to fixed (0% parallax)
    # so that dialog text written on SCR2 stays at the correct screen position.
    _has_dialogues = bool(scene.get("dialogues"))
    _scr2_bg_file = str((scene.get("level_layers") or {}).get("scr2_file") or "").strip()
    if _has_dialogues and not _scr2_bg_file and scr2_px == 100 and scr2_py == 100:
        scr2_px = 0
        scr2_py = 0

    profile = str(scene.get("level_profile", "none") or "none").strip()
    if profile not in _PROFILE_TO_C:
        profile = "none"

    map_mode_now = str(scene.get("map_mode", "none") or "none").strip().lower()
    if map_mode_now not in _MAP_MODE_TO_C:
        map_mode_now = "none"

    profile_preset = _PROFILE_PRESETS.get(profile, {}) if profile != "none" else {}
    hint_map_mode = str(profile_preset.get("map_mode", map_mode_now) or "none").strip().lower()
    if hint_map_mode not in _MAP_MODE_TO_C:
        hint_map_mode = "none"

    hint_scroll_x = 1 if bool(profile_preset.get("scroll_x", False)) else 0
    hint_scroll_y = 1 if bool(profile_preset.get("scroll_y", False)) else 0
    hint_forced = 1 if bool(profile_preset.get("forced", False)) else 0
    hint_loop_x = 1 if bool(profile_preset.get("loop_x", False)) else 0
    hint_loop_y = 1 if bool(profile_preset.get("loop_y", False)) else 0
    hint_lock_y = 1 if profile == "fighting" else 0
    hint_ground_band = 1 if profile == "brawler" else 0

    rules = scene.get("level_rules", {}) or {}
    rules = rules if isinstance(rules, dict) else {}
    lock_en = 1 if bool(rules.get("lock_y_en", False)) else 0
    lock_y = int(rules.get("lock_y", 0) or 0) & 0xFF
    band_en = 1 if bool(rules.get("ground_band_en", False)) else 0
    gmin = int(rules.get("ground_min_y", 0) or 0) & 0xFF
    gmax = int(rules.get("ground_max_y", 0) or 0) & 0xFF
    mir_en = 1 if bool(rules.get("mirror_en", False)) else 0
    axis = int(rules.get("mirror_axis_x", 0) or 0) & 0xFF
    apply_waves = 1 if bool(rules.get("apply_to_waves", True)) else 0
    hazard_damage = int(rules.get("hazard_damage", 1) or 1) & 0xFF
    fire_damage = int(rules.get("fire_damage", 1) or 1) & 0xFF
    void_damage = int(rules.get("void_damage", 255) or 255) & 0xFF
    void_instant = 1 if bool(rules.get("void_instant", True)) else 0
    hazard_invul = int(rules.get("hazard_invul", 30) or 30) & 0xFF
    spring_force = max(0, min(127, int(rules.get("spring_force", 8) or 8))) & 0xFF
    spring_dir = _SPRING_DIR_TO_C.get(str(rules.get("spring_dir", "up") or "up").strip().lower(), 0)
    conveyor_speed = max(1, min(8, int(rules.get("conveyor_speed", 2) or 2))) & 0xFF
    ice_friction   = max(0, min(255, int(rules.get("ice_friction", 0) or 0))) & 0xFF
    water_drag     = max(1, min(8, int(rules.get("water_drag", 2) or 2))) & 0xFF
    water_damage   = max(0, min(255, int(rules.get("water_damage", 0) or 0))) & 0xFF
    zone_force     = max(1, min(8, int(rules.get("zone_force", 2) or 2))) & 0xFF
    ladder_top_solid = 1 if bool(rules.get("ladder_top_solid", False)) else 0
    ladder_top_exit = 1 if bool(rules.get("ladder_top_exit", True)) else 0
    ladder_side_move = 1 if bool(rules.get("ladder_side_move", False)) else 0
    hud_color_to_c = {
        "white": 0,
        "green": 1,
        "amber": 2,
        "cyan": 3,
        "red": 4,
        "blue": 5,
        "black": 6,
    }
    hud_style_to_c = {
        "text": 0,
        "band": 1,
    }
    hud_flags = 0
    if bool(rules.get("hud_show_hp", False)):
        hud_flags |= 2
    if bool(rules.get("hud_show_score", True)):
        hud_flags |= 1
    if bool(rules.get("hud_show_collect", True)):
        hud_flags |= 4
    if bool(rules.get("hud_show_timer", False)):
        hud_flags |= 8
    if bool(rules.get("hud_show_lives", False)):
        hud_flags |= 16
    hud_pos = 1 if str(rules.get("hud_pos", "top") or "top").strip().lower() == "bottom" else 0
    hud_font_mode = 1 if str(rules.get("hud_font_mode", "system") or "system").strip().lower() == "custom" else 0
    hud_fixed_plane = 0
    hud_fixed_plane_name = str(rules.get("hud_fixed_plane", "none") or "none").strip().lower()
    if hud_fixed_plane_name == "scr1":
        hud_fixed_plane = 1
    elif hud_fixed_plane_name == "scr2":
        hud_fixed_plane = 2
    hud_text_color = int(hud_color_to_c.get(str(rules.get("hud_text_color", "white") or "white").strip().lower(), 0))
    hud_style = int(hud_style_to_c.get(str(rules.get("hud_style", "text") or "text").strip().lower(), 0))
    hud_band_color = int(hud_color_to_c.get(str(rules.get("hud_band_color", "blue") or "blue").strip().lower(), 5))
    hud_band_rows = max(1, min(3, int(rules.get("hud_band_rows", 2) or 2))) & 0xFF
    hud_digits_hp = max(1, min(6, int(rules.get("hud_digits_hp", 2) or 2))) & 0xFF
    hud_digits_score = max(1, min(6, int(rules.get("hud_digits_score", 5) or 5))) & 0xFF
    hud_digits_collect = max(1, min(6, int(rules.get("hud_digits_collect", 3) or 3))) & 0xFF
    hud_digits_timer = max(1, min(6, int(rules.get("hud_digits_timer", 3) or 3))) & 0xFF
    hud_digits_lives = max(1, min(6, int(rules.get("hud_digits_lives", 2) or 2))) & 0xFF
    hud_digits_continues = max(1, min(6, int(rules.get("hud_digits_continues", 2) or 2))) & 0xFF
    goal_collectibles = int(rules.get("goal_collectibles", 0) or 0) & 0xFFFF
    time_limit_sec = int(rules.get("time_limit_sec", 0) or 0) & 0xFFFF
    start_lives = int(rules.get("start_lives", 0) or 0) & 0xFF
    start_continues = int(rules.get("start_continues", 0) or 0) & 0xFF
    continue_restore_lives = int(rules.get("continue_restore_lives", 3) or 0) & 0xFF
    hud_metric_to_c = {
        "hp": 0,
        "score": 1,
        "collect": 2,
        "timer": 3,
        "lives": 4,
        "continues": 5,
        "lap_count": 6,
    }
    hud_kind_to_c = {
        "icon": 0,
        "value": 1,
    }
    hud_digit_names = list(rules.get("hud_custom_font_digits", [""] * 10) or [""] * 10)
    while len(hud_digit_names) < 10:
        hud_digit_names.append("")
    hud_digit_names = hud_digit_names[:10]
    hud_custom_items_raw = rules.get("hud_custom_items", []) or []
    hud_custom_items: list[tuple[int, int, int, int, int, int, int]] = []
    if isinstance(hud_custom_items_raw, list):
        type_idx_by_name = {str(name): i for i, name in enumerate(seen_types)}
        hud_digit_types = [int(type_idx_by_name.get(str(name).strip(), 255)) for name in hud_digit_names]
        for item in hud_custom_items_raw:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", "icon") or "icon").strip().lower()
            metric = str(item.get("metric", "score") or "score").strip().lower()
            type_name = str(item.get("type_name", "") or "").strip()
            kind_id = int(hud_kind_to_c.get(kind, 0))
            metric_id = int(hud_metric_to_c.get(metric, 1))
            type_id = int(type_idx_by_name.get(type_name, 255))
            x = max(0, min(19, int(item.get("x", 0) or 0)))
            y = max(0, min(18, int(item.get("y", 0) or 0)))
            digits = max(1, min(6, int(item.get("digits", 5) or 5)))
            flags = 1 if bool(item.get("zero_pad", True)) else 0
            if kind_id == 0 and type_id == 255:
                continue
            hud_custom_items.append((kind_id, metric_id, type_id, x, y, digits, flags))
    else:
        hud_digit_types = [255] * 10

    a = scene.get("audio", {}) or {}
    a = a if isinstance(a, dict) else {}
    try:
        bgm_index = int(a.get("bgm_index", -1))
    except Exception:
        bgm_index = -1
    bgm_tracks: list[int] = []
    raw_bgm_tracks = a.get("tracks", [])
    if isinstance(raw_bgm_tracks, list):
        for value in raw_bgm_tracks:
            try:
                idx = int(value)
            except Exception:
                continue
            if idx < 0 or idx in bgm_tracks:
                continue
            bgm_tracks.append(idx)
    if bgm_index >= 0 and bgm_index not in bgm_tracks:
        bgm_tracks.append(bgm_index)
    bgm_autostart_slot = bgm_tracks.index(bgm_index) if bgm_index in bgm_tracks else -1
    autostart = bool(a.get("autostart", True))
    try:
        fade_out = int(a.get("fade_out", 0))
    except Exception:
        fade_out = 0

    lines += [sep, "/* Layout / scroll metadata                                           */", sep]
    lines += [
        f"#define {sym_use.upper()}_BG_FRONT {1 if bg_front == 'scr1' else 2}  /* 1=SCR1, 2=SCR2 */",
        f"#define {sym_use.upper()}_BG_SCR1_FILE \"{bg_scr1_c}\"",
        f"#define {sym_use.upper()}_BG_SCR2_FILE \"{bg_scr2_c}\"",
        *(
            [
                f"/* Large background — requires optional/ngpc_mapstream + scene_{sym_use}_bg_map.c */",
                f"#define {sym_use.upper()}_HAS_MAPSTREAM 1",
                f"#define NGPNG_HAS_MAPSTREAM 1  /* project-level flag */",
                f"extern const u16 NGP_FAR g_{sym_use}_bg_map[];",
                f"",
            ] if (int(map_w) > 32 or int(map_h) > 32) else []
        ),
        f"#define {sym_use.upper()}_SCR1_PARALLAX_X_PCT {scr1_px}",
        f"#define {sym_use.upper()}_SCR1_PARALLAX_Y_PCT {scr1_py}",
        f"#define {sym_use.upper()}_SCR2_PARALLAX_X_PCT {scr2_px}",
        f"#define {sym_use.upper()}_SCR2_PARALLAX_Y_PCT {scr2_py}",
        *(
            [
                f"/* PERF-PAR-1: map_h={int(map_h)} tiles (>{int(map_h)*8} px). "
                f"At 100% parallax s16 overflow starts at cam_py>327 px (41 tiles). "
                f"ngpng_scale_pct() handles this safely — no action needed. */",
                f"#warning PERF-PAR-1 {sym_use}: map_h={int(map_h)} tiles with non-identity Y parallax."
                f" ngpng_scale_pct avoids overflow; verify template version >= 2026-03-18.",
            ] if (
                int(map_h) > 41
                and (scr1_py not in (0, 100) or scr2_py not in (0, 100))
            ) else []
        ),
        "#ifndef NGPNG_LEVEL_META_ENUMS",
        "#define NGPNG_LEVEL_META_ENUMS",
        "#define NGPNG_MAP_MODE_NONE 0",
        "#define NGPNG_MAP_MODE_PLATFORMER 1",
        "#define NGPNG_MAP_MODE_TOPDOWN 2",
        "#define NGPNG_MAP_MODE_SHMUP 3",
        "#define NGPNG_MAP_MODE_OPEN 4",
        "#define NGPNG_PROFILE_NONE 0",
        "#define NGPNG_PROFILE_FIGHTING 1",
        "#define NGPNG_PROFILE_PLATFORMER 2",
        "#define NGPNG_PROFILE_RUN_GUN 3",
        "#define NGPNG_PROFILE_SHMUP 4",
        "#define NGPNG_PROFILE_BRAWLER 5",
        "#define NGPNG_PROFILE_TOPDOWN_RPG 6",
        "#define NGPNG_PROFILE_TACTICAL 7",
        "#define NGPNG_PROFILE_PUZZLE 8",
        "#define NGPNG_PROFILE_VISUAL_NOVEL 9",
        "#define NGPNG_PROFILE_RHYTHM 10",
        "#define NGPNG_SPRING_DIR_UP 0",
        "#define NGPNG_SPRING_DIR_DOWN 1",
        "#define NGPNG_SPRING_DIR_LEFT 2",
        "#define NGPNG_SPRING_DIR_RIGHT 3",
        "#define NGPNG_SPRING_DIR_OPPOSITE_TOUCH 4",
        "#endif",
        "",
        f"#define {sym_use.upper()}_MAP_MODE {_MAP_MODE_TO_C.get(map_mode_now, 0)}",
        f"#define {sym_use.upper()}_PROFILE {_PROFILE_TO_C.get(profile, 0)}",
        f"#define {sym_use.upper()}_PROFILE_MAP_MODE_HINT {_MAP_MODE_TO_C.get(hint_map_mode, 0)}",
        f"#define {sym_use.upper()}_PROFILE_SCROLL_X_HINT {hint_scroll_x}",
        f"#define {sym_use.upper()}_PROFILE_SCROLL_Y_HINT {hint_scroll_y}",
        f"#define {sym_use.upper()}_PROFILE_FORCED_SCROLL_HINT {hint_forced}",
        f"#define {sym_use.upper()}_PROFILE_LOOP_X_HINT {hint_loop_x}",
        f"#define {sym_use.upper()}_PROFILE_LOOP_Y_HINT {hint_loop_y}",
        f"#define {sym_use.upper()}_PROFILE_RULE_LOCK_Y_HINT {hint_lock_y}",
        f"#define {sym_use.upper()}_PROFILE_RULE_GROUND_BAND_HINT {hint_ground_band}",
        f"#define {sym_use.upper()}_MAP_W {int(map_w)}",
        f"#define {sym_use.upper()}_MAP_H {int(map_h)}",
        f"#define {sym_use.upper()}_CAM_MODE {_CAM_MODE_TO_C.get(cam_mode, 0)}",
        f"#define {sym_use.upper()}_CAM_CLAMP {clamp}",
        f"#define {sym_use.upper()}_CAM_MIN_X {int(min_x)}",
        f"#define {sym_use.upper()}_CAM_MIN_Y {int(min_y)}",
        f"#define {sym_use.upper()}_CAM_MAX_X {int(max_x)}",
        f"#define {sym_use.upper()}_CAM_MAX_Y {int(max_y)}",
        f"#define {sym_use.upper()}_CAM_FOLLOW_DEADZONE_X {int(follow_deadzone_x)}",
        f"#define {sym_use.upper()}_CAM_FOLLOW_DEADZONE_Y {int(follow_deadzone_y)}",
        f"#define {sym_use.upper()}_CAM_FOLLOW_DROP_MARGIN_Y {int(follow_drop_margin_y)}",
        f"#define {sym_use.upper()}_CAM_LAG {int(cam_lag)}",
        f"#define {sym_use.upper()}_RULE_LOCK_Y_EN {lock_en}",
        f"#define {sym_use.upper()}_RULE_LOCK_Y {lock_y}",
        f"#define {sym_use.upper()}_RULE_GROUND_BAND_EN {band_en}",
        f"#define {sym_use.upper()}_RULE_GROUND_MIN_Y {gmin}",
        f"#define {sym_use.upper()}_RULE_GROUND_MAX_Y {gmax}",
        f"#define {sym_use.upper()}_RULE_MIRROR_EN {mir_en}",
        f"#define {sym_use.upper()}_RULE_MIRROR_AXIS_X {axis}",
        f"#define {sym_use.upper()}_RULE_APPLY_TO_WAVES {apply_waves}",
        f"#define {sym_use.upper()}_RULE_HAZARD_DAMAGE {hazard_damage}",
        f"#define {sym_use.upper()}_RULE_FIRE_DAMAGE {fire_damage}",
        f"#define {sym_use.upper()}_RULE_VOID_DAMAGE {void_damage}",
        f"#define {sym_use.upper()}_RULE_VOID_INSTANT {void_instant}",
        f"#define {sym_use.upper()}_RULE_HAZARD_INVUL {hazard_invul}",
        f"#define {sym_use.upper()}_RULE_SPRING_FORCE {spring_force}",
        f"#define {sym_use.upper()}_RULE_SPRING_DIR {spring_dir}",
        f"#define {sym_use.upper()}_RULE_CONVEYOR_SPEED {conveyor_speed}",
        f"#define {sym_use.upper()}_RULE_ICE_FRICTION {ice_friction}",
        f"#define {sym_use.upper()}_RULE_WATER_DRAG {water_drag}",
        f"#define {sym_use.upper()}_RULE_WATER_DAMAGE {water_damage}",
        f"#define {sym_use.upper()}_RULE_ZONE_FORCE {zone_force}",
        f"#define {sym_use.upper()}_RULE_LADDER_TOP_SOLID {ladder_top_solid}",
        f"#define {sym_use.upper()}_RULE_LADDER_TOP_EXIT {ladder_top_exit}",
        f"#define {sym_use.upper()}_RULE_LADDER_SIDE_MOVE {ladder_side_move}",
        f"#define {sym_use.upper()}_RULE_HUD_FLAGS {hud_flags}",
        f"#define {sym_use.upper()}_RULE_HUD_POS {hud_pos}",
        f"#define {sym_use.upper()}_RULE_HUD_FONT_MODE {hud_font_mode}",
        f"#define {sym_use.upper()}_RULE_HUD_FIXED_PLANE {hud_fixed_plane}",
        f"#define {sym_use.upper()}_RULE_HUD_TEXT_COLOR {hud_text_color}",
        f"#define {sym_use.upper()}_RULE_HUD_STYLE {hud_style}",
        f"#define {sym_use.upper()}_RULE_HUD_BAND_COLOR {hud_band_color}",
        f"#define {sym_use.upper()}_RULE_HUD_BAND_ROWS {hud_band_rows}",
        f"#define {sym_use.upper()}_RULE_HUD_DIGITS_HP {hud_digits_hp}",
        f"#define {sym_use.upper()}_RULE_HUD_DIGITS_SCORE {hud_digits_score}",
        f"#define {sym_use.upper()}_RULE_HUD_DIGITS_COLLECT {hud_digits_collect}",
        f"#define {sym_use.upper()}_RULE_HUD_DIGITS_TIMER {hud_digits_timer}",
        f"#define {sym_use.upper()}_RULE_HUD_DIGITS_LIVES {hud_digits_lives}",
        f"#define {sym_use.upper()}_RULE_HUD_DIGITS_CONTINUES {hud_digits_continues}",
        f"#define {sym_use.upper()}_RULE_GOAL_COLLECTIBLES {goal_collectibles}",
        f"#define {sym_use.upper()}_RULE_TIME_LIMIT_SEC {time_limit_sec}",
        f"#define {sym_use.upper()}_RULE_START_LIVES {start_lives}",
        f"#define {sym_use.upper()}_RULE_START_CONTINUES {start_continues}",
        f"#define {sym_use.upper()}_RULE_CONTINUE_RESTORE_LIVES {continue_restore_lives}",
        f"#define {sym_use.upper()}_CAM_TILE_X {cam_x}",
        f"#define {sym_use.upper()}_CAM_TILE_Y {cam_y}",
        f"#define {sym_use.upper()}_SCROLL_X {1 if bool(sc.get('scroll_x', False)) else 0}",
        f"#define {sym_use.upper()}_SCROLL_Y {1 if bool(sc.get('scroll_y', False)) else 0}",
        f"#define {sym_use.upper()}_FORCED_SCROLL {1 if bool(sc.get('forced', False)) else 0}",
        f"#define {sym_use.upper()}_SCROLL_SPEED_X {int(sc.get('speed_x', 0) or 0)}",
        f"#define {sym_use.upper()}_SCROLL_SPEED_Y {int(sc.get('speed_y', 0) or 0)}",
        f"#define {sym_use.upper()}_LOOP_X {1 if bool(sc.get('loop_x', False)) else 0}",
        f"#define {sym_use.upper()}_LOOP_Y {1 if bool(sc.get('loop_y', False)) else 0}",
        f"#define {sym_use.upper()}_BGM_COUNT {len(bgm_tracks)}",
        f"#define {sym_use.upper()}_BGM_LIST " + f"g_{sym_use}_bgm_list",
        f"#define {sym_use.upper()}_BGM_INDEX {bgm_index}",
        f"#define {sym_use.upper()}_BGM_AUTOSTART_SLOT {bgm_autostart_slot}",
        f"#define {sym_use.upper()}_BGM_AUTOSTART {1 if autostart else 0}",
        f"#define {sym_use.upper()}_BGM_FADE_OUT {max(0, fade_out)}",
        "",
    ]

    def _fmt_u8_array(name: str, data: list[int], per_line: int = 16) -> None:
        lines.append(f"static const u8 {name}[] = {{")
        for i in range(0, len(data), per_line):
            chunk = ", ".join(f"{int(v):3d}" for v in data[i:i + per_line])
            lines.append(f"    {chunk},")
        lines.append("};")
        lines.append("")

    if bgm_tracks:
        _fmt_u8_array(f"g_{sym_use}_bgm_list", bgm_tracks)
    else:
        lines.append(f"static const u8 g_{sym_use}_bgm_list[1] = {{0}};")
        lines.append("")

    if hud_custom_items:
        lines += [
            "#ifndef NGPNG_HUD_ITEM_T",
            "#define NGPNG_HUD_ITEM_T",
            "typedef struct { u8 kind; u8 metric; u8 type; u8 x; u8 y; u8 digits; u8 flags; } NgpngHudItem;",
            "#endif",
            "",
            f"#define {sym_use.upper()}_HUD_ITEM_COUNT {len(hud_custom_items)}",
            f"static const NgpngHudItem g_{sym_use}_hud_items[] = {{",
        ]
        for kind_id, metric_id, type_id, x, y, digits, flags in hud_custom_items:
            lines.append(f"    {{{kind_id}, {metric_id}, {type_id}, {x}, {y}, {digits}, {flags}}},")
        lines += [
            "};",
            "",
        ]
    if any(v != 255 for v in hud_digit_types):
        _fmt_u8_array(f"g_{sym_use}_hud_digit_types", hud_digit_types, per_line=10)
        lines.append(f"#define {sym_use.upper()}_HUD_DIGIT_TYPES 1")
        lines.append("")

    # ---- Collision map + visual tile IDs (procgen) ----
    col_map = scene.get("col_map", None)
    map_mode = map_mode_now
    tile_ids = scene.get("tile_ids", {}) or {}
    _sc_flags = 0

    for ent in entities:
        typ = str(ent.get("type") or "").strip()
        role_name = str(entity_roles.get(typ, "prop") or "prop").strip().lower()
        if role_name == "item":
            _sc_flags |= 0x20  # SCENE_FLAG_HAS_ITEMS
        elif role_name == "platform":
            _sc_flags |= 0x40  # SCENE_FLAG_HAS_PLATFORMS
        elif role_name == "block":
            _sc_flags |= 0x80  # SCENE_FLAG_HAS_BLOCKS
        elif role_name == "prop" and typ in damage_prop_types:
            _sc_flags |= 0x0100  # SCENE_FLAG_HAS_DAMAGE_PROPS

    if isinstance(col_map, list) and col_map:
        ok = (
            len(col_map) == int(map_h)
            and all(isinstance(r, list) and len(r) == int(map_w) for r in col_map)
        )
        if ok:
            lines += [sep, "/* Tile collision map (u8 per tile)                                  */", sep]
            lines += [
                "#ifndef TILE_PASS",
                "#define TILE_PASS       0",
                "#define TILE_SOLID      1",
                "#define TILE_ONE_WAY    2",
                "#define TILE_DAMAGE     3",
                "#define TILE_LADDER     4",
                "#endif",
                "#ifndef TILE_WALL_N",
                "#define TILE_WALL_N     5",
                "#define TILE_WALL_S     6",
                "#define TILE_WALL_E     7",
                "#define TILE_WALL_W     8",
                "#endif",
                "#ifndef TILE_WATER",
                "#define TILE_WATER      9",
                "#define TILE_FIRE       10",
                "#define TILE_VOID       11",
                "#define TILE_DOOR       12",
                "#endif",
                "#ifndef TILE_STAIR_E",
                "#define TILE_STAIR_E    13",
                "#define TILE_STAIR_W    14",
                "#endif",
                "#ifndef TILE_SPRING",
                "#define TILE_SPRING     15",
                "#endif",
                "#ifndef TILE_ICE",
                "#define TILE_ICE        16",
                "#define TILE_CONVEYOR_L 17",
                "#define TILE_CONVEYOR_R 18",
                "#endif",
                "",
                f"#define {sym_use.upper()}_MAP_W {int(map_w)}",
                f"#define {sym_use.upper()}_MAP_H {int(map_h)}",
                "",
            ]

            flat_col: list[int] = []
            for y in range(int(map_h)):
                for x in range(int(map_w)):
                    flat_col.append(int(col_map[y][x]))
            _fmt_u8_array(f"g_{sym_use}_tilecol", flat_col)
            lines.append(f"#define {sym_use.upper()}_TILECOL_EXISTS 1")
            # Compute per-scene capability flags from flat_col tile values.
            _sc_tile_set = set(flat_col)
            if _TCOL_SPRING in _sc_tile_set:                          _sc_flags |= 0x01  # SCENE_FLAG_HAS_SPRING
            if _TCOL_LADDER in _sc_tile_set:                          _sc_flags |= 0x02  # SCENE_FLAG_HAS_LADDER
            if (_TCOL_DAMAGE in _sc_tile_set                          # SCENE_FLAG_HAS_DEADLY
                    or _TCOL_FIRE in _sc_tile_set
                    or _TCOL_VOID in _sc_tile_set):                   _sc_flags |= 0x04
            if _TCOL_ICE in _sc_tile_set:                             _sc_flags |= 0x08  # SCENE_FLAG_HAS_ICE
            if (_TCOL_CONVEYOR_L in _sc_tile_set                      # SCENE_FLAG_HAS_CONVEYOR
                    or _TCOL_CONVEYOR_R in _sc_tile_set):             _sc_flags |= 0x10
            if _TCOL_WATER in _sc_tile_set:                           _sc_flags |= 0x0200  # SCENE_FLAG_HAS_WATER

            # Visual tile IDs (optional mapping)
            mode_map = tile_ids.get(map_mode, {}) if isinstance(tile_ids, dict) else {}
            if isinstance(mode_map, dict) and map_mode in _MAP_MODE_ROLES:
                tcol_to_role = {tcol: role_key for (role_key, tcol) in _MAP_MODE_ROLES[map_mode]}
                flat_vis: list[int] = []
                for i, t in enumerate(flat_col):
                    rk = tcol_to_role.get(int(t))
                    if rk is None:
                        flat_vis.append(0)
                    else:
                        x = i % int(map_w)
                        y = i // int(map_w)
                        flat_vis.append(_tile_id_pick(mode_map.get(rk, int(t)), default=int(t), x=x, y=y))
                lines += [sep, "/* Visual tile IDs (u8)                                               */", sep]
                _fmt_u8_array(f"g_{sym_use}_tilemap_ids", flat_vis)

    lines.append(f"#define {sym_use.upper()}_SCENE_FLAGS {_sc_flags:#06x}u")
    lines.append("")
    lines.append(f"#endif /* {guard} */")
    lines.append("")
    return "\n".join(lines)


def write_scene_level_h(
    *,
    project_data: dict,
    scene: dict,
    export_dir: Path,
    project_dir: Path | None = None,
) -> Path:
    """
    Write:
      export_dir/scene_<safe>_level.h
    and return its path.
    """
    label = str(scene.get("label") or "")
    sid = str(scene.get("id") or "")
    safe = _safe_ident(label or sid or "scene")
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    out_h = export_dir / f"scene_{safe}_level.h"
    out_h.write_text(make_scene_level_h(project_data=project_data, scene=scene, sym=safe, project_dir=project_dir), encoding="utf-8")
    return out_h


# ---------------------------------------------------------------------------
# CT-8 : standalone col_cells export for use with optional/ngpc_tilecol
# ---------------------------------------------------------------------------

def _extract_col_flat(scene: dict) -> tuple[list[int], int, int] | None:
    """Return (flat_col, map_w, map_h) or None if col_map is absent/invalid."""
    meta = scene.get("level_meta") or scene.get("meta") or {}
    map_w = int(meta.get("map_w") or scene.get("map_w") or 0)
    map_h = int(meta.get("map_h") or scene.get("map_h") or 0)
    col_map = scene.get("col_map", None)
    if not isinstance(col_map, list) or not col_map:
        return None
    if map_w <= 0 or map_h <= 0:
        map_h = len(col_map)
        map_w = len(col_map[0]) if isinstance(col_map[0], list) else 0
    if map_w <= 0 or map_h <= 0:
        return None
    if len(col_map) != map_h or not all(isinstance(r, list) and len(r) == map_w for r in col_map):
        return None
    flat: list[int] = []
    for row in col_map:
        for v in row:
            flat.append(max(0, min(255, int(v))))
    return flat, map_w, map_h


_TILECOL_DEFINES = """\
#ifndef TILE_PASS
#define TILE_PASS       0
#define TILE_SOLID      1
#define TILE_ONE_WAY    2
#define TILE_DAMAGE     3
#define TILE_LADDER     4
#endif
#ifndef TILE_WALL_N
#define TILE_WALL_N     5
#define TILE_WALL_S     6
#define TILE_WALL_E     7
#define TILE_WALL_W     8
#endif
#ifndef TILE_WATER
#define TILE_WATER      9
#define TILE_FIRE       10
#define TILE_VOID       11
#define TILE_DOOR       12
#endif
#ifndef TILE_STAIR_E
#define TILE_STAIR_E    13
#define TILE_STAIR_W    14
#endif
#ifndef TILE_SPRING
#define TILE_SPRING     15
#endif
#ifndef TILE_ICE
#define TILE_ICE        16
#define TILE_CONVEYOR_L 17
#define TILE_CONVEYOR_R 18
#endif"""


def make_scene_col_cells_h(*, scene: dict, sym: str) -> str | None:
    """Return the .h source for the standalone col_cells file, or None if no valid col_map."""
    result = _extract_col_flat(scene)
    if result is None:
        return None
    _flat, map_w, map_h = result
    SYM = sym.upper()
    guard = f"SCENE_{SYM}_COL_CELLS_H"
    lines = [
        f"/* Generated by NGPC PNG Manager — do not edit */",
        f"#ifndef {guard}",
        f"#define {guard}",
        f"",
        f'#include "ngpc_hw.h"',
        f"",
        _TILECOL_DEFINES,
        f"",
        f"#define {SYM}_MAP_W  {map_w}",
        f"#define {SYM}_MAP_H  {map_h}",
        f"",
        f"extern const u8 g_{sym}_tilecol[{SYM}_MAP_W * {SYM}_MAP_H];",
        f"",
        f"/* Convenience initializer — requires ngpc_tilecol.h */",
        f"#define {SYM}_COL_INIT  {{ g_{sym}_tilecol, {SYM}_MAP_W, {SYM}_MAP_H }}",
        f"",
        f"#endif /* {guard} */",
        f"",
    ]
    return "\n".join(lines)


def make_scene_col_cells_c(*, scene: dict, sym: str) -> str | None:
    """Return the .c source for the standalone col_cells file, or None if no valid col_map."""
    result = _extract_col_flat(scene)
    if result is None:
        return None
    flat, map_w, map_h = result
    SYM = sym.upper()
    # Format flat array 20 values per line
    per_line = map_w
    rows_c: list[str] = []
    for row_start in range(0, len(flat), per_line):
        chunk = flat[row_start: row_start + per_line]
        rows_c.append("  " + ", ".join(str(v) for v in chunk))
    body = ",\n".join(rows_c)
    lines = [
        f"/* Generated by NGPC PNG Manager — do not edit */",
        f'#include "scene_{sym}_col_cells.h"',
        f"",
        f"/* col_map: flat[ty * {SYM}_MAP_W + tx] = TILE_* type */",
        f"const u8 g_{sym}_tilecol[{SYM}_MAP_W * {SYM}_MAP_H] = {{",
        body,
        f"}};",
        f"",
    ]
    return "\n".join(lines)


def write_scene_col_cells(
    *,
    scene: dict,
    export_dir: Path,
) -> tuple[Path, Path] | None:
    """
    Write scene_<safe>_col_cells.h and scene_<safe>_col_cells.c.
    Returns (path_h, path_c), or None if the scene has no valid col_map.
    """
    label = str(scene.get("label") or "")
    sid = str(scene.get("id") or "")
    sym = _safe_ident(label or sid or "scene")
    h_src = make_scene_col_cells_h(scene=scene, sym=sym)
    c_src = make_scene_col_cells_c(scene=scene, sym=sym)
    if h_src is None or c_src is None:
        return None
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    out_h = export_dir / f"scene_{sym}_col_cells.h"
    out_c = export_dir / f"scene_{sym}_col_cells.c"
    out_h.write_text(h_src, encoding="utf-8")
    out_c.write_text(c_src, encoding="utf-8")
    return out_h, out_c


# ---------------------------------------------------------------------------
# DLG-3 : Dialogue export  →  scene_<safe>_dialogs.h
# ---------------------------------------------------------------------------

def _escape_c_str(s: str) -> str:
    """Escape a Python string for use as a C string literal content."""
    return (
        s.replace("\\", "\\\\")
         .replace('"', '\\"')
         .replace("\n", "\\n")
         .replace("\r", "")
         .replace("\x01", "\\001")
         .replace("\x02", "\\002")
    )


def _encode_dialog_text(*, speaker: str, text: str) -> str:
    """
    Encode a dialogue page string for C.

    Use octal escapes for speaker markers so the compiled C string cannot
    accidentally swallow following hex characters from the speaker/text.
    Example: "\\001car\\002bof" stays 0x01,'c','a','r',0x02,'b','o','f'.
    """
    if speaker:
        return f"\\001{_escape_c_str(speaker)}\\002{_escape_c_str(text)}"
    return _escape_c_str(text)


def _resolve_goto(dlgs: list, goto_id: str) -> str:
    """Resolve a dialogue string ID to its integer index, or '0xFF' if not found."""
    if not goto_id:
        return "0xFF"
    idx = next((j for j, d in enumerate(dlgs)
                if str(d.get("id", "") or "").strip() == goto_id), None)
    return str(idx) if idx is not None else "0xFF"


def _get_sprite_fill_color(export_dir, sprite_name: str) -> str:
    """Read the dominant fill color (palette index 1) from a generated *_mspr.c file.
    Returns a 4-hex-digit string like '089A', or '' if not found."""
    import re
    try:
        mspr_path = Path(export_dir) / f"{sprite_name}_mspr.c"
        if not mspr_path.exists():
            return ""
        content = mspr_path.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"_palettes\[\]\s*=\s*\{([^}]+)\}", content)
        if not m:
            return ""
        parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
        if len(parts) < 2:
            return ""
        raw = parts[1].strip()
        val = int(raw, 16) & 0x0FFF
        return f"{val:04X}"
    except Exception:
        return ""


def make_scene_dialogs_h(*, scene: dict, sym: str, export_dir=None) -> str | None:
    """
    Generate scene_<sym>_dialogs.h content.

    Exports:
      - String arrays per dialogue (ROM)
      - Per-line choice label + goto tables (ROM)
      - NgpcDlgSeq sequence table with on_done action
      - Choice-goto lookup table for the runner
      - NgpcDlgRunner struct + scene_<sym>_dlg_open() / scene_<sym>_dlg_update()
        as static inline functions — zero RAM, no external .c needed

    Returns None if the scene has no dialogues.
    """
    dlgs = scene.get("dialogues") or []
    if not dlgs:
        return None

    guard = f"SCENE_{sym.upper()}_DIALOGS_H"
    sym_upper_scene = sym.upper()
    lines: list[str] = []
    lines.append(f"#ifndef {guard}")
    lines.append(f"#define {guard}")
    lines.append("")
    lines.append("/* Auto-generated by NgpCraft — DO NOT EDIT */")
    lines.append('#include "ngpc_dialog/ngpc_dialog.h"')
    lines.append("")

    portrait_ids: dict[str, int] = {}
    for dlg in dlgs:
        for ln in (dlg.get("lines") or []):
            portrait = str(ln.get("portrait") or "").strip()
            if portrait and portrait not in portrait_ids:
                portrait_ids[portrait] = len(portrait_ids)

    lines.append("#ifndef NGPCRAFT_DLG_PAGE_TYPE")
    lines.append("#define NGPCRAFT_DLG_PAGE_TYPE 1")
    lines.append("typedef struct {")
    lines.append("    const char *text;    /* encoded text, may start with speaker markers */")
    lines.append("    u8  portrait_id;     /* 0xFF = no portrait for this page             */")
    lines.append("} NgpcDlgPage;")
    lines.append("#endif")
    lines.append("")

    # ── 1. Page string arrays ─────────────────────────────────────────────
    lines.append("/* ================================================================ */")
    lines.append("/* PAGE DATA (text strings in ROM)                                   */")
    lines.append("/* ================================================================ */")
    lines.append("")

    defines:    list[str] = []
    choice_syms: list[tuple[int, int, str]] = []  # (seq_idx, page_idx, goto_sym)

    for i, dlg in enumerate(dlgs):
        did       = str(dlg.get("id") or f"dlg_{i:02d}")
        dlg_lines = dlg.get("lines") or []
        did_upper = did.upper()

        lines.append(f"static const NgpcDlgPage g_{sym}_dlg_{did}[] = {{")
        for ln in dlg_lines:
            speaker = str(ln.get("speaker") or "")
            text    = str(ln.get("text") or "")
            portrait = str(ln.get("portrait") or "").strip()
            portrait_c = f"{portrait_ids[portrait]}u" if portrait else "0xFFu"
            encoded = _encode_dialog_text(speaker=speaker, text=text)
            lines.append(f'    {{ "{encoded}", {portrait_c} }},')
        lines.append("    { 0, 0xFFu }")
        lines.append("};")
        lines.append("")
        defines.append(f"#define {sym_upper_scene}_DLG_{did_upper} {i}")

        # Per-line choice arrays
        for li, ln in enumerate(dlg_lines):
            choices = ln.get("choices") or []
            if not choices:
                continue
            ch_sym = f"g_{sym}_dlg_{did}_l{li}_choices"
            gt_sym = f"g_{sym}_dlg_{did}_l{li}_goto"
            labels = ", ".join(
                f'"{_escape_c_str(str(c.get("label") or ""))}"' for c in choices
            )
            gotos = [_resolve_goto(dlgs, str(c.get("goto") or "").strip()) for c in choices]
            gotos_str = ", ".join(gotos)
            lines.append(f"static const char *{ch_sym}[] = {{ {labels}, 0 }};")
            lines.append(f"static const u8    {gt_sym}[] = {{ {gotos_str}, 0xFF }};")
            lines.append("")
            choice_syms.append((i, li, gt_sym))

    # ── 2. Sequence table ─────────────────────────────────────────────────
    lines.append("/* ================================================================ */")
    lines.append("/* SEQUENCE TABLE                                                    */")
    lines.append("/* ================================================================ */")
    lines.append("")
    lines.append("#ifndef NGPCRAFT_DLG_DONE_CONSTANTS")
    lines.append("#define NGPCRAFT_DLG_DONE_CONSTANTS 1")
    lines.append("#define DLG_DONE_CLOSE       0  /* close box, resume game           */")
    lines.append("#define DLG_DONE_NEXT_DLG    1  /* auto-open on_done_arg dialogue   */")
    lines.append("#define DLG_DONE_SET_FLAG    2  /* caller: set flag on_done_arg     */")
    lines.append("#define DLG_DONE_EMIT_EVENT  3  /* caller: emit event on_done_arg   */")
    lines.append("#endif")
    lines.append("")
    lines.append("#ifndef NGPCRAFT_DLG_SHARED_TYPES")
    lines.append("#define NGPCRAFT_DLG_SHARED_TYPES 1")
    lines.append("typedef struct {")
    lines.append("    const NgpcDlgPage *pages;  /* null-terminated page array (ROM) */")
    lines.append("    u8  on_done;              /* DLG_DONE_* action                */")
    lines.append("    u8  on_done_arg;          /* next seq index / flag n / event n */")
    lines.append("} NgpcDlgSeq;")
    lines.append("typedef struct { u8 seq; u8 page; const u8 *tbl; } NgpcDlgChoiceGoto;")
    lines.append("typedef struct {")
    lines.append("    NgpcDialog  box;      /* runtime dialog state                 */")
    lines.append("    u8          page;     /* current page in seq.pages[]          */")
    lines.append("    u8          seq_idx;  /* current sequence (dialog index)      */")
    lines.append("    u8          portrait_id; /* current portrait for the active page */")
    lines.append("} NgpcDlgRunner;")
    lines.append("#define ngpc_dlg_is_active(r)  ngpc_dialog_is_open(&(r)->box)")
    lines.append("#endif")
    lines.append("")
    lines.append(f"static const NgpcDlgSeq g_{sym}_dlg_seq[{len(dlgs)}] = {{")

    _ON_DONE_MAP = {
        "close":       "DLG_DONE_CLOSE",
        "next_dlg":    "DLG_DONE_NEXT_DLG",
        "set_flag":    "DLG_DONE_SET_FLAG",
        "emit_event":  "DLG_DONE_EMIT_EVENT",
    }
    for i, dlg in enumerate(dlgs):
        did       = str(dlg.get("id") or f"dlg_{i:02d}")
        on_done   = dlg.get("on_done") or {}
        action    = str(on_done.get("action") or "close")
        action_c  = _ON_DONE_MAP.get(action, "DLG_DONE_CLOSE")
        if action == "next_dlg":
            arg = _resolve_goto(dlgs, str(on_done.get("id") or "").strip())
            if arg == "0xFF":
                arg = "0"   # fallback: close (index 0 if nothing resolved)
        elif action in ("set_flag", "emit_event"):
            arg = str(int(on_done.get("n") or 0) & 0xFF)
        else:
            arg = "0"
        lines.append(f"    {{ g_{sym}_dlg_{did}, {action_c}, {arg} }},   /* {i}: {did} */")
    lines.append("};")
    lines.append("")

    # Choice-goto lookup table used by the runner
    lines.append("/* choice-goto lookup: {seq_idx, page_idx, goto_table}, sentinel={0xFF,0xFF,NULL} */")
    lines.append(f"static const NgpcDlgChoiceGoto g_{sym}_choice_gotos[] = {{")
    for seq_i, page_i, gt_sym in choice_syms:
        lines.append(f"    {{ {seq_i}, {page_i}, {gt_sym} }},")
    lines.append("    { 0xFF, 0xFF, 0 }")
    lines.append("};")
    lines.append("")

    # Index defines
    lines += defines
    lines.append(f"#define {sym_upper_scene}_DLG_COUNT {len(dlgs)}")
    lines.append("")

    # ── 3. Runner struct + inline functions ───────────────────────────────
    lines.append("/* ================================================================ */")
    lines.append("/* RUNNER — call once per frame while ngpc_dlg_is_active(r)         */")
    lines.append("/* ================================================================ */")
    lines.append("")
    lines.append(f"static u8 {sym}_dlg_on_done_action(const NgpcDlgRunner *r)")
    lines.append("{")
    lines.append(f"    return g_{sym}_dlg_seq[r->seq_idx].on_done;")
    lines.append("}")
    lines.append("")
    lines.append(f"static u8 {sym}_dlg_on_done_arg(const NgpcDlgRunner *r)")
    lines.append("{")
    lines.append(f"    return g_{sym}_dlg_seq[r->seq_idx].on_done_arg;")
    lines.append("}")
    lines.append("")
    lines.append(f"static void {sym}_dlg_apply_page(NgpcDlgRunner *r, const NgpcDlgPage *page)")
    lines.append("{")
    lines.append("    r->portrait_id = 0xFFu;")
    lines.append("    if (!page || !page->text) return;")
    lines.append("    if (page->portrait_id != 0xFFu)")
    lines.append("        r->portrait_id = page->portrait_id;")
    lines.append("    ngpc_dialog_set_text(&r->box, page->text);")
    lines.append("}")
    lines.append("")

    # open function
    lines.append(f"static void {sym}_dlg_open(")
    lines.append( "        NgpcDlgRunner *r, u8 seq_idx,")
    lines.append( "        u8 bx, u8 by, u8 bw, u8 bh, u8 pal,")
    lines.append( "        u16 frame_tile_base, u8 frame_pal)")
    lines.append( "{")
    lines.append( "    r->seq_idx = seq_idx;")
    lines.append( "    r->page    = 0;")
    lines.append( "    r->portrait_id = 0xFFu;")
    lines.append( "    ngpc_dialog_open(&r->box, bx, by, bw, bh, pal, 0u, frame_tile_base, frame_pal);")
    lines.append(f"    if (g_{sym}_dlg_seq[seq_idx].pages[0].text)")
    lines.append(f"        {sym}_dlg_apply_page(r, &g_{sym}_dlg_seq[seq_idx].pages[0]);")
    lines.append( "}")
    lines.append("")

    # update function
    lines.append(f"/* Returns DIALOG_RUNNING while active.")
    lines.append( " * Returns DIALOG_DONE when fully closed:")
    lines.append( " *   check the scene-specific on_done helpers for post-close actions.")
    lines.append( " * DIALOG_CHOICE_0/1 is returned only if no auto-goto resolved.")
    lines.append( " * Handles automatically: pagination, choice branching, on_done=next_dlg. */")
    lines.append(f"static u8 {sym}_dlg_update(NgpcDlgRunner *r)")
    lines.append( "{")
    lines.append( "    const NgpcDlgSeq    *seq;")
    lines.append( "    const NgpcDlgChoiceGoto *cg;")
    lines.append( "    u8 result, choice, next;")
    lines.append( "")
    lines.append( "    if (!ngpc_dialog_is_open(&r->box)) return DIALOG_DONE;")
    lines.append( "")
    lines.append( "    result = ngpc_dialog_update(&r->box);")
    lines.append( "    if (result == DIALOG_RUNNING) return DIALOG_RUNNING;")
    lines.append( "")
    lines.append( "    /* ── Choice made ──────────────────────────────────────── */")
    lines.append( "    if (result == DIALOG_CHOICE_0 || result == DIALOG_CHOICE_1) {")
    lines.append( "        choice = result - DIALOG_CHOICE_0;")
    lines.append(f"        cg = g_{sym}_choice_gotos;")
    lines.append( "        while (cg->tbl) {")
    lines.append( "            if (cg->seq == r->seq_idx && cg->page == r->page) {")
    lines.append( "                next = cg->tbl[choice];")
    lines.append( "                if (next != 0xFF) {")
    lines.append( "                    /* auto-jump to target sequence */")
    lines.append( "                    r->seq_idx = next;")
    lines.append( "                    r->page    = 0;")
    lines.append( "                    ngpc_dialog_open(&r->box, r->box.bx, r->box.by,")
    lines.append( "                                     r->box.bw, r->box.bh, r->box.pal, 0u,")
    lines.append( "                                     r->box.frame_tile_base, r->box.frame_pal);")
    lines.append(f"                    if (g_{sym}_dlg_seq[next].pages[0].text)")
    lines.append(f"                        {sym}_dlg_apply_page(r, &g_{sym}_dlg_seq[next].pages[0]);")
    lines.append( "                    return DIALOG_RUNNING;")
    lines.append( "                }")
    lines.append( "                return DIALOG_DONE; /* goto 0xFF = close */")
    lines.append( "            }")
    lines.append( "            cg++;")
    lines.append( "        }")
    lines.append( "        return DIALOG_DONE;")
    lines.append( "    }")
    lines.append( "")
    lines.append( "    /* ── Page done — advance or on_done ──────────────────── */")
    lines.append(f"    seq = &g_{sym}_dlg_seq[r->seq_idx];")
    lines.append( "    r->page++;")
    lines.append( "    if (seq->pages[r->page].text) {")
    lines.append( "        /* more pages — reopen box, set next page text */")
    lines.append( "        ngpc_dialog_open(&r->box, r->box.bx, r->box.by,")
    lines.append( "                         r->box.bw, r->box.bh, r->box.pal, 0u,")
    lines.append( "                         r->box.frame_tile_base, r->box.frame_pal);")
    lines.append(f"        {sym}_dlg_apply_page(r, &seq->pages[r->page]);")
    lines.append( "        return DIALOG_RUNNING;")
    lines.append( "    }")
    lines.append( "")
    lines.append( "    /* ── Last page: on_done ───────────────────────────────── */")
    lines.append( "    /* For DLG_DONE_NEXT_DLG: return DIALOG_DONE so the caller can close cleanly")
    lines.append( "       and reopen the next sequence via ngpng_dialog_open_for_scene (full reinit).")
    lines.append( "       r->seq_idx is left pointing at the current sequence so on_done_arg is")
    lines.append(f"       still readable via {sym}_dlg_on_done_arg(). */")
    lines.append( "    /* DLG_DONE_CLOSE / SET_FLAG / EMIT_EVENT / NEXT_DLG:")
    lines.append( "       box already closed by ngpc_dialog_update().")
    lines.append( "       Caller reads on_done_action + on_done_arg to decide next step. */")
    lines.append( "    return DIALOG_DONE;")
    lines.append( "}")
    lines.append("")

    # ── 4. Menus (unchanged) ──────────────────────────────────────────────
    menus = scene.get("menus") or []
    if menus:
        lines.append("/* ================================================================ */")
        lines.append("/* MENUS (ngpc_menu — max 8 items, D-pad navigation)                */")
        lines.append("/* ================================================================ */")
        lines.append("")
        menu_defines: list[str] = []
        for mi, menu in enumerate(menus):
            mid       = str(menu.get("id") or f"menu_{mi:02d}")
            items     = menu.get("items") or []
            mid_upper = mid.upper()
            if items:
                labels    = ", ".join(f'"{_escape_c_str(str(it.get("label") or ""))}"' for it in items)
                gotos     = [_resolve_goto(dlgs, str(it.get("goto") or "").strip()) for it in items]
                gotos_str = ", ".join(gotos)
                lines.append(f"static const char *g_{sym}_menu_{mid}_items[] = {{ {labels}, 0 }};")
                lines.append(f"static const u8    g_{sym}_menu_{mid}_goto[]  = {{ {gotos_str}, 0xFF }};")
            else:
                lines.append(f"static const char *g_{sym}_menu_{mid}_items[] = {{ 0 }};")
                lines.append(f"static const u8    g_{sym}_menu_{mid}_goto[]  = {{ 0xFF }};")
            lines.append("")
            menu_defines.append(f"#define {sym_upper_scene}_MENU_{mid_upper}       {mi}")
            menu_defines.append(f"#define {sym_upper_scene}_MENU_{mid_upper}_COUNT {len(items)}")
        lines += menu_defines
        lines.append(f"#define {sym_upper_scene}_MENU_COUNT {len(menus)}")

    # ── Background tile set (optional) ───────────────────────────────────
    # Layout in sprite sheet (4 consecutive tiles from tile_base):
    #   +0 corner  (use H/V flip for all 4 corners)
    #   +1 H-border (top; V-flip for bottom)
    #   +2 V-border (left; H-flip for right)
    #   +3 fill     (center, repeated)
    cfg = scene.get("dialogue_config") or {}
    bg_sprite = str(cfg.get("bg_sprite") or "").strip()
    if bg_sprite:
        bg_sym = re.sub(r"[^A-Za-z0-9_]+", "_", bg_sprite).upper()
        lines.append("")
        lines.append(f"/* Dialog background sprite: {bg_sprite} */")
        lines.append(f"/* Use DLG_BG_TILE_BASE (resolved at runtime from sprite VRAM slot) */")
        lines.append(f"#define {sym_upper_scene}_DLG_BG_SPRITE_NAME  \"{_escape_c_str(bg_sprite)}\"")
        lines.append(f"/* Sprite layout (16x16 px = 4 tiles 8x8):                           */")
        lines.append(f"/*   [tile+0] top-left  = corner TL  |  [tile+1] top-right  = H-bord */")
        lines.append(f"/*   [tile+2] bot-left  = fill       |  [tile+3] bot-right  = V-bord */")
        lines.append(f"#define {sym_upper_scene}_DLG_BG_CORNER_OFS   0  /* TL; H-flip=TR, V-flip=BL, HV=BR   */")
        lines.append(f"#define {sym_upper_scene}_DLG_BG_HBORDER_OFS  1  /* top edge; V-flip = bottom edge     */")
        lines.append(f"#define {sym_upper_scene}_DLG_BG_FILL_OFS     2  /* center fill, repeat                */")
        lines.append(f"#define {sym_upper_scene}_DLG_BG_VBORDER_OFS  3  /* right edge; H-flip = left edge     */")
    else:
        lines.append("")
        lines.append("/* No dialog background sprite configured — use default drawn box */")
        lines.append(f"#define {sym_upper_scene}_DLG_BG_SPRITE_NAME  \"\"")

    # ── Text palette (3 editable slots; slot 0 = hardware transparent) ───
    _PAL_DEFAULTS = ["0000", "0888", "0FFF"]
    pal = list(cfg.get("palette") or [])
    while len(pal) < 3:
        pal.append(_PAL_DEFAULTS[len(pal)])
    # If a bg_sprite is configured, always derive slot-2 fill color from its
    # palette (index 1 = first non-transparent color = box background).
    # This overrides any stored value so the font background always matches the box.
    if bg_sprite and export_dir is not None:
        fill_hex = _get_sprite_fill_color(export_dir, bg_sprite)
        if fill_hex:
            pal[1] = fill_hex
    lines.append("")
    lines.append("/* Dialog text palette (NGPC RGB444: 0xBGR  slot 0 = transparent) */")
    for idx in range(3):
        try:
            word = int(pal[idx], 16) & 0x0FFF
        except (ValueError, IndexError):
            word = int(_PAL_DEFAULTS[idx], 16)
        lines.append(f"#define {sym_upper_scene}_DLG_PAL_{idx + 1}  0x{word:04X}  /* slot {idx + 1} */")

    lines.append("")
    lines.append(f"#endif /* {guard} */")
    return "\n".join(lines) + "\n"


def write_scene_dialogs_h(
    *,
    scene: dict,
    export_dir,
) -> "Path | None":
    """Write scene_<safe>_dialogs.h; returns path or None if no dialogues."""
    label = str(scene.get("label") or "")
    sid   = str(scene.get("id") or "")
    safe  = _safe_ident(label or sid or "scene")
    src   = make_scene_dialogs_h(scene=scene, sym=safe, export_dir=export_dir)
    if src is None:
        return None
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    out_h = export_dir / f"scene_{safe}_dialogs.h"
    out_h.write_text(src, encoding="utf-8")
    return out_h
