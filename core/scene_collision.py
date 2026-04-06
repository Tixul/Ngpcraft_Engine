"""Helpers for deriving a scene collision map from tilemap metadata."""

from __future__ import annotations

import copy
from pathlib import Path

from PIL import Image

_TILE_PX = 8
_TCOL_PASS = 0


def _scene_dims(scene: dict) -> tuple[int, int]:
    size = scene.get("level_size", {}) or {}
    map_w = int(size.get("w", scene.get("map_w", scene.get("grid_w", 20))) or 20)
    map_h = int(size.get("h", scene.get("map_h", scene.get("grid_h", 19))) or 19)
    return max(1, map_w), max(1, map_h)


def _norm_rel(path_value: str) -> str:
    return str(path_value or "").replace("\\", "/").strip()


def _scene_tilemap_entry_for_rel(scene: dict, rel: str) -> dict | None:
    rel_norm = _norm_rel(rel)
    rel_name = Path(rel_norm).name.lower()
    for tm in (scene.get("tilemaps") or []):
        if not isinstance(tm, dict):
            continue
        tm_rel = _norm_rel(str(tm.get("file") or ""))
        if not tm_rel:
            continue
        if tm_rel == rel_norm or Path(tm_rel).name.lower() == rel_name:
            return tm
    return None


def _resolve_scene_bg(scene: dict) -> tuple[str | None, str | None]:
    front = str(scene.get("level_bg_front", "scr1") or "scr1").strip().lower()
    ordered = [front, "scr2" if front == "scr1" else "scr1"]
    for plane in ordered:
        rel = str(scene.get(f"level_bg_{plane}", "") or "").strip()
        if rel:
            return plane, rel
    return None, None


def tilemap_collision_grid(tm: dict, path: Path) -> list[list[int]]:
    img = Image.open(path).convert("RGBA")
    tw = max(1, int(img.width // _TILE_PX))
    th = max(1, int(img.height // _TILE_PX))

    # Pre-resolved grid saved by the tilemap editor — always correct regardless
    # of tile pool ID ordering (tileset mode uses NGPC pipeline IDs).
    pre = tm.get("collision_grid")
    if isinstance(pre, list) and pre:
        grid = [[_TCOL_PASS for _x in range(tw)] for _y in range(th)]
        for y in range(min(th, len(pre))):
            row = pre[y]
            if not isinstance(row, list):
                continue
            for x in range(min(tw, len(row))):
                try:
                    grid[y][x] = int(row[x])
                except Exception:
                    grid[y][x] = _TCOL_PASS
        return grid

    mode = str(tm.get("collision_mode", "tileset") or "tileset").strip().lower()
    if mode == "paint":
        raw = tm.get("collision_paint", []) or []
        grid = [[_TCOL_PASS for _x in range(tw)] for _y in range(th)]
        if isinstance(raw, list):
            for y in range(min(th, len(raw))):
                row = raw[y]
                if not isinstance(row, list):
                    continue
                for x in range(min(tw, len(row))):
                    try:
                        grid[y][x] = int(row[x])
                    except Exception:
                        grid[y][x] = _TCOL_PASS
        return grid

    assign = [int(v) for v in (tm.get("collision_tileset", []) or [])]
    if not assign:
        return [[_TCOL_PASS for _x in range(tw)] for _y in range(th)]

    tile_ids: dict[bytes, int] = {}
    grid = [[_TCOL_PASS for _x in range(tw)] for _y in range(th)]
    next_id = 0
    for ty in range(th):
        for tx in range(tw):
            tile = img.crop((tx * _TILE_PX, ty * _TILE_PX, tx * _TILE_PX + _TILE_PX, ty * _TILE_PX + _TILE_PX))
            key = tile.tobytes()
            tid = tile_ids.get(key)
            if tid is None:
                tid = next_id
                tile_ids[key] = tid
                next_id += 1
            grid[ty][tx] = assign[tid] if 0 <= tid < len(assign) else _TCOL_PASS
    return grid


def fit_collision_grid(grid: list[list[int]], map_w: int, map_h: int) -> list[list[int]]:
    out = [[_TCOL_PASS for _x in range(map_w)] for _y in range(map_h)]
    for y in range(min(map_h, len(grid))):
        row = grid[y]
        if not isinstance(row, list):
            continue
        for x in range(min(map_w, len(row))):
            try:
                out[y][x] = int(row[x])
            except Exception:
                out[y][x] = _TCOL_PASS
    return out


def _tilemap_has_collision(tm: dict) -> bool:
    """Return True if the tilemap entry has user-defined collision data."""
    # Pre-resolved grid takes priority (saved by tilemap editor for both modes)
    grid = tm.get("collision_grid") or []
    if isinstance(grid, list) and grid:
        return any(
            any(v != _TCOL_PASS for v in row)
            for row in grid
            if isinstance(row, list)
        )
    mode = str(tm.get("collision_mode", "") or "").strip().lower()
    if mode == "paint":
        paint = tm.get("collision_paint") or []
        return isinstance(paint, list) and any(
            any(v != _TCOL_PASS for v in row)
            for row in paint
            if isinstance(row, list)
        )
    # tileset mode: at least one tile assigned a non-pass value
    assign = tm.get("collision_tileset") or []
    return isinstance(assign, list) and any(v != _TCOL_PASS for v in assign)


def scene_with_export_collision(scene: dict, base_dir: Path | None) -> dict:
    """Return a scene copy with col_map ready for export.

    col_map stored in the scene is the source of truth (populated by the
    level tab, either via auto-import from the BG tilemap on first load or
    via manual painting).  Auto-derivation from the tilemap is only used as
    a fallback when col_map is absent or empty.
    """
    scene_copy = copy.deepcopy(scene)
    col_map = scene_copy.get("col_map")
    if isinstance(col_map, list) and col_map:
        return scene_copy

    # Fallback: derive from BG tilemap (scene never opened in level tab yet).
    plane, rel = _resolve_scene_bg(scene_copy)
    if not rel:
        return scene_copy
    tm = _scene_tilemap_entry_for_rel(scene_copy, rel)
    if tm is None or not _tilemap_has_collision(tm):
        return scene_copy
    tm_path = Path(rel)
    if not tm_path.is_absolute() and base_dir is not None:
        tm_path = Path(base_dir) / tm_path
    if not tm_path.exists():
        return scene_copy
    try:
        grid = tilemap_collision_grid(tm, tm_path)
    except Exception:
        return scene_copy
    map_w, map_h = _scene_dims(scene_copy)
    scene_copy["col_map"] = fit_collision_grid(grid, map_w, map_h)
    scene_copy["col_map_meta"] = {
        "kind":  "tilemap_export_auto",
        "rel":   _norm_rel(rel),
        "plane": str(plane or "").lower(),
    }
    return scene_copy
