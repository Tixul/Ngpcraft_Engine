"""
core/bg_size_check.py — Detect and resolve mismatches between a scene's
configured ``level_size`` (stored in project.ngpcraft) and the actual
dimensions of its background PNG.

Why
---
A scene's runtime scroll bounds are derived from ``level_size.w/h``
(e.g. ``CAM_MAX_X = level_w * 8 - 160``). The exported background tilemap
is a flat ``u16`` array of width ``png_w/8`` columns. When ``level_w >
png_tiles_w`` the runtime indexes ``bg_map[y * level_w + x]`` past the
true end of each row, reading the next row's tiles and producing the
"scrolling bg corruption" symptom users hit after swapping a wider PNG
for a narrower one (``level_size`` stays stale in the project JSON).

This module provides three resolution strategies, surfaced via the
``MismatchResolution`` enum, so the export pipeline can decide
interactively (UI dialog) or via a CLI flag.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable


__all__ = [
    "MismatchResolution",
    "SceneBgMismatch",
    "detect_scene_bg_mismatches",
    "apply_clamp_to_project",
    "rewrite_bg_map_to_size",
]


class MismatchResolution(str, Enum):
    """How to react when a scene's level_size disagrees with its BG PNG."""

    CANCEL = "cancel"       # Abort the whole export.
    CLAMP = "clamp"         # Mutate level_size to match the PNG and re-export.
    CROP_FILL = "crop_fill" # Keep level_size; reshape bg_map.c by cropping/padding.
    IGNORE = "ignore"       # No-op (legacy behavior — corruption may occur).


@dataclass
class SceneBgMismatch:
    """One concrete mismatch between a scene's level_size and its BG PNG."""

    scene_label: str
    scene_index: int
    bg_rel: str                # project-relative PNG path
    png_tiles_w: int           # PNG width in 8x8 tiles
    png_tiles_h: int           # PNG height in 8x8 tiles
    level_w: int               # scene["level_size"]["w"]
    level_h: int               # scene["level_size"]["h"]

    @property
    def is_runtime_unsafe(self) -> bool:
        """True when the configured size exceeds the PNG.

        This is the failure mode that produces visible corruption: the
        runtime walks past the real end of each row into the next row's
        bytes. The opposite case (PNG larger than level) is benign — the
        extra columns are simply unused.
        """
        return self.level_w > self.png_tiles_w or self.level_h > self.png_tiles_h

    def describe(self) -> str:
        return (
            f"[{self.scene_label}] level_size={self.level_w}x{self.level_h} "
            f"PNG={self.png_tiles_w}x{self.png_tiles_h} tiles "
            f"(BG: {self.bg_rel})"
        )


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _png_tile_dims(path: Path) -> "tuple[int, int] | None":
    """Return (tiles_w, tiles_h) for the PNG, rounding up to whole tiles.

    Returns None when the file is missing or unreadable. ``ngpc_tilemap.py``
    auto-pads non-multiple-of-8 PNGs, so we round up here for parity.
    """
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        with Image.open(path) as im:
            w, h = int(im.width), int(im.height)
    except Exception:
        return None
    if w <= 0 or h <= 0:
        return None
    return ((w + 7) // 8, (h + 7) // 8)


def _resolve_png(base_dir: "Path | None", rel: str) -> "Path | None":
    if not rel:
        return None
    p = Path(rel)
    if not p.is_absolute() and base_dir is not None:
        p = base_dir / p
    return p if p.exists() else None


def _scene_bg_rel(scene: dict) -> str:
    """Return the BG PNG path the runtime actually scrolls.

    The renderer prefers ``level_bg_scr1`` (large scrollable bg); fall
    back to ``level_bg`` for legacy projects.
    """
    val = str(scene.get("level_bg_scr1") or "").strip()
    if val:
        return val
    return str(scene.get("level_bg") or "").strip()


def detect_scene_bg_mismatches(
    project_data: dict,
    base_dir: "Path | None",
) -> "list[SceneBgMismatch]":
    """Inspect every scene with a BG PNG; return mismatches in scene order.

    Only runtime-unsafe mismatches (``level_size`` strictly larger than
    the PNG) are returned — the inverse case is benign. Callers that
    want every divergence can filter on ``is_runtime_unsafe`` themselves.
    """
    out: list[SceneBgMismatch] = []
    scenes = project_data.get("scenes") or []
    for idx, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        bg_rel = _scene_bg_rel(scene)
        if not bg_rel:
            continue
        png_path = _resolve_png(base_dir, bg_rel)
        if png_path is None:
            continue
        dims = _png_tile_dims(png_path)
        if dims is None:
            continue
        size = scene.get("level_size") or {}
        try:
            level_w = int(size.get("w") or 0)
            level_h = int(size.get("h") or 0)
        except Exception:
            continue
        if level_w <= 0 or level_h <= 0:
            continue
        png_tw, png_th = dims
        m = SceneBgMismatch(
            scene_label=str(scene.get("label") or scene.get("id") or f"scene{idx}"),
            scene_index=idx,
            bg_rel=bg_rel,
            png_tiles_w=png_tw,
            png_tiles_h=png_th,
            level_w=level_w,
            level_h=level_h,
        )
        if m.is_runtime_unsafe:
            out.append(m)
    return out


# ---------------------------------------------------------------------------
# Resolution: CLAMP — mutate project data to match the PNG
# ---------------------------------------------------------------------------

def apply_clamp_to_project(
    project_data: dict,
    mismatches: Iterable[SceneBgMismatch],
) -> "list[SceneBgMismatch]":
    """In-place: shrink each scene's ``level_size`` so it never exceeds
    the PNG. Returns the list of mismatches actually applied.

    The caller is responsible for persisting the project file after this
    call (e.g. ``json.dump(project_data, ...)``) — keeping persistence
    here would couple this module to the project file format and prevent
    callers from layering atomic-save / undo / diff logic on top.
    """
    applied: list[SceneBgMismatch] = []
    scenes = project_data.get("scenes") or []
    for m in mismatches:
        if m.scene_index < 0 or m.scene_index >= len(scenes):
            continue
        scene = scenes[m.scene_index]
        if not isinstance(scene, dict):
            continue
        size = scene.setdefault("level_size", {})
        if not isinstance(size, dict):
            size = {}
            scene["level_size"] = size
        new_w = min(m.level_w, m.png_tiles_w)
        new_h = min(m.level_h, m.png_tiles_h)
        size["w"] = int(new_w)
        size["h"] = int(new_h)
        applied.append(m)
    return applied


# ---------------------------------------------------------------------------
# Resolution: CROP_FILL — reshape the generated bg_map.c to level_size
# ---------------------------------------------------------------------------

_ARRAY_OPEN_RE = re.compile(
    r"const\s+u16\s+NGP_FAR\s+(?P<sym>g_[A-Za-z0-9_]+)\s*\[\s*\]\s*=\s*\{",
)
_DIM_COMMENT_RE = re.compile(
    r"^/\*\s*FAR tileword array for ngpc_mapstream.*\(\s*(\d+)\s*x\s*(\d+)\s*tiles\s*\)\.\s*\*/",
    re.MULTILINE,
)
_HEX_TOKEN_RE = re.compile(r"0[xX][0-9a-fA-F]+")


def _parse_bg_map_c(text: str) -> "tuple[str, int, int, list[int]] | None":
    """Parse the generator's ``<sym>_bg_map.c`` output.

    Returns ``(symbol, current_w, current_h, flat_tiles)`` or ``None`` if
    the file does not match the expected shape (no array opening, missing
    dim comment, or wrong element count).
    """
    open_m = _ARRAY_OPEN_RE.search(text)
    if open_m is None:
        return None
    sym = open_m.group("sym")
    dim_m = _DIM_COMMENT_RE.search(text)
    if dim_m is None:
        return None
    cur_w = int(dim_m.group(1))
    cur_h = int(dim_m.group(2))
    body_start = open_m.end()
    body_end = text.find("};", body_start)
    if body_end < 0:
        return None
    body = text[body_start:body_end]
    flat = [int(tok, 16) for tok in _HEX_TOKEN_RE.findall(body)]
    if len(flat) != cur_w * cur_h:
        # The file shape disagrees with its own comment — refuse to
        # silently re-emit, the user needs to know.
        return None
    return sym, cur_w, cur_h, flat


def _emit_bg_map_c(
    sym: str,
    target_w: int,
    target_h: int,
    flat: "list[int]",
    fill_tile: int = 0,
) -> str:
    """Render a fresh bg_map.c with the given dimensions and data."""
    lines: list[str] = []
    lines.append("/* Auto-generated by NgpCraft Engine -- do not edit */")
    lines.append(
        f"/* FAR tileword array for ngpc_mapstream SCR1 ({target_w}x{target_h} tiles). */"
    )
    lines.append("/* assets_autogen.mk picks this up automatically — no manual OBJS edit needed. */")
    lines.append("")
    lines.append('#include "ngpc_types.h"')
    lines.append("")
    lines.append(f"const u16 NGP_FAR {sym}[] = {{")
    per_line = 16
    n = target_w * target_h
    for start in range(0, n, per_line):
        chunk = flat[start:start + per_line]
        lines.append("    " + ", ".join(f"0x{v:04X}" for v in chunk) + ",")
    lines.append("};")
    lines.append("")
    return "\n".join(lines)


def rewrite_bg_map_to_size(
    out_c: Path,
    target_w: int,
    target_h: int,
    fill_tile: int = 0,
) -> bool:
    """Reshape the existing ``out_c`` so its array matches ``target_w x
    target_h``. Crops excess rows/cols, pads missing cells with
    ``fill_tile``.

    Returns True on success, False when the file cannot be safely
    rewritten (parse failure). On failure the file is left untouched —
    callers must surface the issue to the user.
    """
    try:
        text = out_c.read_text(encoding="utf-8")
    except Exception:
        return False
    parsed = _parse_bg_map_c(text)
    if parsed is None:
        return False
    sym, cur_w, cur_h, flat = parsed
    if cur_w == target_w and cur_h == target_h:
        return True  # nothing to do
    if target_w <= 0 or target_h <= 0:
        return False

    new_flat: list[int] = [fill_tile] * (target_w * target_h)
    copy_w = min(cur_w, target_w)
    copy_h = min(cur_h, target_h)
    for y in range(copy_h):
        src_off = y * cur_w
        dst_off = y * target_w
        new_flat[dst_off:dst_off + copy_w] = flat[src_off:src_off + copy_w]

    try:
        out_c.write_text(
            _emit_bg_map_c(sym, target_w, target_h, new_flat, fill_tile=fill_tile),
            encoding="utf-8",
        )
    except Exception:
        return False
    return True
