"""
core/scene_loader_gen.py - Generate template-ready C header snippets for a scene.

Goal (CT-7):
- After exporting a scene (sprites + tilemaps), generate a small header that
  contains ready-to-call functions to load palettes/tiles and blit tilemaps.

This is intentionally conservative:
- It only emits code based on the project's scene metadata and exported asset
  outputs that should already exist in export_dir (project setting).
- If an exported tilemap .c is missing (or unparseable), the generator keeps
  the tile_base cascade and estimates tile usage from the PNG size when possible
  (to avoid overlap with later assets).
"""

from __future__ import annotations

import re
import os
from pathlib import Path

from core.project_model import analyze_scene_bg_palette_banks_exact

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional fallback
    Image = None


_RE_SCENE_SAFE = re.compile(r"[^0-9a-zA-Z_]+")
_RE_TYPE_SAFE = re.compile(r"[^a-zA-Z0-9]+")


def _is_pow2(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


def _log2(n: int) -> int:
    r = 0
    while (1 << r) < n:
        r += 1
    return r


def _safe_ident(s: str) -> str:
    s = (s or "").strip()
    s = _RE_SCENE_SAFE.sub("_", s)
    s = s.strip("_")
    if not s:
        return "scene"
    if s[0].isdigit():
        s = "_" + s
    return s.lower()


def _type_to_c_const(name: str) -> str:
    clean = _RE_TYPE_SAFE.sub("_", (name or "")).strip("_").upper()
    return f"ENT_{clean}" if clean else "ENT_UNKNOWN"


def _type_to_c_const_scoped(scene_sym: str, name: str) -> str:
    """Return a scene-prefixed entity type macro: ENT_{SCENE}_{TYPE}.
    Matches the scene-prefixed macros emitted by scene_level_gen.py.
    """
    clean = _RE_TYPE_SAFE.sub("_", (name or "")).strip("_").upper()
    prefix = _RE_TYPE_SAFE.sub("_", (scene_sym or "")).strip("_").upper()
    return f"ENT_{prefix}_{clean}" if clean else f"ENT_{prefix}_UNKNOWN"


def _name_to_c_id(name: str) -> str:
    """Return a C-safe identifier from a sprite/entity name (e.g. hyphens → underscores)."""
    return _RE_TYPE_SAFE.sub("_", (name or "")).strip("_")


def _scene_sprite_name(spr: dict) -> str:
    nm = str(spr.get("name") or "").strip()
    if nm:
        return nm
    rel = str(spr.get("file") or "").strip()
    return Path(rel).stem if rel else ""


def _scene_sprite_export_header_exists(spr: dict, export_dir: Path, base_dir: Path | None) -> bool:
    nm = _scene_sprite_name(spr)
    safe_nm = re.sub(r"[^a-zA-Z0-9_]+", "_", nm).strip("_")
    if not safe_nm:
        return False

    candidates: list[Path] = [Path(export_dir) / f"{safe_nm}_mspr.h"]
    rel = str(spr.get("file") or "").strip()
    if rel:
        src = Path(rel)
        if not src.is_absolute() and base_dir is not None:
            src = Path(base_dir) / src
        candidates.append(src.parent / f"{safe_nm}_mspr.h")
    return any(p.is_file() for p in candidates)


def _scene_sprite_has_layer1(spr: dict, export_dir: Path, base_dir: Path | None) -> bool:
    """Return True if the exported header contains a HAS_LAYER1 macro (dual-layer auto-split)."""
    nm = _scene_sprite_name(spr)
    safe_nm = re.sub(r"[^a-zA-Z0-9_]+", "_", nm).strip("_")
    if not safe_nm:
        return False

    candidates: list[Path] = [Path(export_dir) / f"{safe_nm}_mspr.h"]
    rel = str(spr.get("file") or "").strip()
    if rel:
        src = Path(rel)
        if not src.is_absolute() and base_dir is not None:
            src = Path(base_dir) / src
        candidates.append(src.parent / f"{safe_nm}_mspr.h")

    for p in candidates:
        if p.is_file():
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                if "_HAS_LAYER1" in content:
                    return True
            except Exception:
                pass
    return False


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


def _tilemap_symbol_base(tilemap_path: Path) -> str:
    stem = tilemap_path.stem
    if stem.lower().endswith("_scr1") or stem.lower().endswith("_scr2"):
        stem = stem[:-5]
    stem = _RE_SCENE_SAFE.sub("_", stem).strip("_").lower()
    if not stem:
        stem = "asset"
    if stem[0].isdigit():
        stem = "asset_" + stem
    return stem


def _read_text(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _parse_tilemap_tile_slots_from_c(text: str, sym_base: str) -> int | None:
    # Standard u16 words path: tiles_count = number of u16 words (8 words per tile).
    m = re.search(rf"\bconst\s+u16\s+{re.escape(sym_base)}_tiles_count\s*=\s*(\d+)u\s*;", text)
    if m:
        try:
            words = int(m.group(1))
            return max(0, words // 8)
        except Exception:
            return None

    # Optional u8 tiles path: tile_count = number of tiles.
    m = re.search(rf"\bconst\s+u16\s+{re.escape(sym_base)}_tile_count\s*=\s*(\d+)u\s*;", text)
    if m:
        try:
            return max(0, int(m.group(1)))
        except Exception:
            return None

    return None


def _parse_map_dims_from_c(text: str, sym_base: str) -> tuple[int | None, int | None]:
    """Return (map_w, map_h) from an exported tilemap .c for the given symbol base."""
    # Accept both u8 and u16 declarations (ngpc_tilemap.py exports u16 since large-map support).
    mw = re.search(rf"\bconst\s+(?:u8|u16)\s+{re.escape(sym_base)}_map_w\s*=\s*(\d+)u?\s*;", text)
    mh = re.search(rf"\bconst\s+(?:u8|u16)\s+{re.escape(sym_base)}_map_h\s*=\s*(\d+)u?\s*;", text)
    w = int(mw.group(1)) if mw else None
    h = int(mh.group(1)) if mh else None
    return w, h


def _parse_c_array_ints(text: str, sym_name: str) -> list[int] | None:
    """Extract all integer values from a C array declaration: const u8/u16 sym_name[] = {...}"""
    m = re.search(
        rf"\bconst\s+(?:u8|u16)\s+{re.escape(sym_name)}\s*\[\s*[^\]]*\]\s*=\s*\{{([^}}]*)\}}",
        text,
        re.DOTALL,
    )
    if not m:
        return None
    body = m.group(1)
    vals: list[int] = []
    for tok in re.findall(r"0[xX][0-9a-fA-F]+|\d+", body):
        try:
            vals.append(int(tok, 16) if tok.lower().startswith("0x") else int(tok))
        except ValueError:
            pass
    return vals if vals else None


def _write_scene_bg_map_c(
    safe: str,
    scr1_sym: str,
    tile_base: int,
    c_text: str,
    export_dir: Path,
    map_w: int,
    map_h: int,
    plane_label: str = "SCR1",
) -> Path | None:
    """
    Phase 2 of ngpc_mapstream: generate scene_{safe}_bg_map.c containing
    g_{safe}_bg_map[] — a FAR ROM array of precomputed tilewords for ngpc_mapstream.

    Tileword format (same as ngpc_mapstream ms_put target):
        tileword = (tile_base + relative_tile_idx) | (palette_idx << 9)

    The file is placed in export_dir so that assets_autogen_mk.py picks it up
    automatically on the next export and adds it to assets_autogen.mk OBJS.

    plane_label is cosmetic only (appears in the header comment) — the tileword
    format is identical for SCR1 and SCR2.
    """
    tiles = _parse_c_array_ints(c_text, f"{scr1_sym}_map_tiles")
    pals = _parse_c_array_ints(c_text, f"{scr1_sym}_map_pals")
    if not tiles or not pals:
        return None
    n = map_w * map_h
    if len(tiles) < n or len(pals) < n:
        n = min(len(tiles), len(pals))
    tilewords = [
        ((tile_base + tiles[i]) & 0x1FF) | ((pals[i] & 0x0F) << 9)
        for i in range(n)
    ]
    out_c = export_dir / f"scene_{safe}_bg_map.c"
    lines: list[str] = [
        "/* Auto-generated by NgpCraft Engine -- do not edit */\n",
        f"/* FAR tileword array for ngpc_mapstream {plane_label} ({map_w}x{map_h} tiles). */\n",
        "/* assets_autogen.mk picks this up automatically — no manual OBJS edit needed. */\n",
        "\n",
        "#include \"ngpc_types.h\"\n",
        "\n",
        f"const u16 NGP_FAR g_{safe}_bg_map[] = {{\n",
    ]
    for i in range(0, len(tilewords), 16):
        chunk = tilewords[i : i + 16]
        lines.append("    " + ", ".join(f"0x{v:04X}" for v in chunk) + ",\n")
    lines.append("};\n")
    out_c.write_text("".join(lines), encoding="utf-8")
    return out_c


def _assemble_chunk_bg_map_c(
    safe: str,
    chunk_grid: list[list[dict]],
    export_dir: Path,
) -> tuple["Path | None", int, int]:
    """
    Track A (MAP-1): assemble a grid of chunk maps into a single g_{safe}_bg_map[].

    chunk_grid[row][col] each dict: sym_base, tile_base, c_text, map_w, map_h
    (same keys used by _write_scene_bg_map_c).

    Constraints: all chunks in the same chunk-row must share the same height;
    all chunks in the same chunk-col must share the same width.

    Returns (out_path | None, total_w_tiles, total_h_tiles).
    """
    if not chunk_grid or not chunk_grid[0]:
        return None, 0, 0

    n_rows = len(chunk_grid)
    n_cols = len(chunk_grid[0])

    # Parse raw tile arrays for every chunk.
    parsed: list[list[dict | None]] = []
    for chunk_row in chunk_grid:
        parsed_row: list[dict | None] = []
        for ci in chunk_row:
            ct = ci.get("c_text") or ""
            sym = str(ci.get("sym_base", ""))
            tb = int(ci.get("tile_base", 128))
            mw = int(ci.get("map_w") or 0)
            mh = int(ci.get("map_h") or 0)
            tiles = _parse_c_array_ints(ct, f"{sym}_map_tiles")
            pals = _parse_c_array_ints(ct, f"{sym}_map_pals")
            if not tiles or not pals or mw == 0 or mh == 0:
                parsed_row.append(None)
            else:
                n = mw * mh
                parsed_row.append({
                    "tile_base": tb, "map_w": mw, "map_h": mh,
                    "tiles": tiles[:n], "pals": pals[:n],
                })
        parsed.append(parsed_row)

    # All chunks must be parseable.
    if any(ci is None for row in parsed for ci in row):
        return None, 0, 0

    # Validate row-height consistency.
    for row in parsed:
        row_h = row[0]["map_h"]  # type: ignore[index]
        if any(ci["map_h"] != row_h for ci in row):  # type: ignore[index]
            return None, 0, 0

    total_w: int = sum(parsed[0][c]["map_w"] for c in range(n_cols))  # type: ignore[index]
    total_h: int = sum(parsed[r][0]["map_h"] for r in range(n_rows))  # type: ignore[index]

    # Assemble tilewords in row-major world order.
    tilewords: list[int] = []
    for parsed_row in parsed:
        row_h = parsed_row[0]["map_h"]  # type: ignore[index]
        for local_row in range(row_h):
            for chunk in parsed_row:
                mw = chunk["map_w"]  # type: ignore[index]
                tb = chunk["tile_base"]  # type: ignore[index]
                tls = chunk["tiles"]  # type: ignore[index]
                pls = chunk["pals"]  # type: ignore[index]
                for col in range(mw):
                    i = local_row * mw + col
                    tilewords.append(((tb + tls[i]) & 0x1FF) | ((pls[i] & 0x0F) << 9))

    out_c = export_dir / f"scene_{safe}_bg_map.c"
    lines: list[str] = [
        "/* Auto-generated by NgpCraft Engine -- do not edit */\n",
        f"/* FAR tileword array for ngpc_mapstream SCR1"
        f" ({total_w}x{total_h} tiles, {n_rows}x{n_cols} chunk grid). */\n",
        "/* assets_autogen.mk picks this up automatically — no manual OBJS edit needed. */\n",
        "\n",
        '#include "ngpc_types.h"\n',
        "\n",
        f"const u16 NGP_FAR g_{safe}_bg_map[] = {{\n",
    ]
    for i in range(0, len(tilewords), 16):
        sl = tilewords[i:i + 16]
        lines.append("    " + ", ".join(f"0x{v:04X}" for v in sl) + ",\n")
    lines.append("};\n")
    out_c.write_text("".join(lines), encoding="utf-8")
    return out_c, total_w, total_h


def write_scene_loader_h(
    *,
    project_data: dict,
    scene: dict,
    project_dir: Path,
    export_dir: Path,
    base_dir: Path | None,
    include_level: bool = True,
    include_disabled: bool = False,
    warnings_out: list[str] | None = None,
) -> Path:
    """
    Write:
      export_dir/scene_<safe>.h
    and return its path.
    """
    project_dir = Path(project_dir)
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    label = str(scene.get("label") or "")
    sid = str(scene.get("id") or "")
    safe = _safe_ident(label or sid or "scene")

    scene_out_h = export_dir / f"scene_{safe}.h"
    guard = f"SCENE_{safe.upper()}_H"

    # ---- Sprite includes + calls ------------------------------------
    sprite_names: list[str] = []   # raw filename stem (used for #include)
    sprite_cids:  list[str] = []   # C-safe identifier (used in function calls)
    layer1_sprite_set: set[str] = set()  # sprite names that have dual-layer auto-split
    seen_sprite: set[str] = set()
    missing_sprite_exports: list[str] = []
    for spr in (scene.get("sprites") or []):
        if not isinstance(spr, dict):
            continue
        if not include_disabled and spr.get("export", True) is False:
            continue
        nm = _scene_sprite_name(spr)
        if not nm or nm in seen_sprite:
            continue
        if not _scene_sprite_export_header_exists(spr, export_dir, base_dir):
            missing_sprite_exports.append(nm)
            continue
        seen_sprite.add(nm)
        sprite_names.append(nm)
        # Sanitize for C identifiers and #include filenames (spaces, hyphens → _)
        sprite_cids.append(re.sub(r"[^a-zA-Z0-9_]+", "_", nm).strip("_"))
        if _scene_sprite_has_layer1(spr, export_dir, base_dir):
            layer1_sprite_set.add(nm)

    if warnings_out is not None and missing_sprite_exports:
        scene_label = str(scene.get("label") or scene.get("id") or safe or "scene")
        for nm in missing_sprite_exports:
            warnings_out.append(
                f"[{scene_label}] scene loader: missing sprite export for '{nm}' - loader include skipped"
            )

    ent_types = _collect_entity_types(scene)
    sprite_set = set(sprite_names)
    ent_draw_types = [t for t in ent_types if t in sprite_set]
    layer1_draw_types: set[str] = {t for t in ent_draw_types if t in layer1_sprite_set}

    # ---- Tilemap includes + bases -----------------------------------
    tilemap_cfg = (project_data.get("tilemap") or {}) if isinstance(project_data, dict) else {}
    try:
        cursor = int(tilemap_cfg.get("tile_base", 128))
    except Exception:
        cursor = 128

    # ---- Track A: multi-chunk map grid (MAP-1) -------------------------
    # JSON: scene["bg_chunk_map"] = {"grid": [["r0c0.png", "r0c1.png"], ...]}
    # Each PNG in the grid must also appear in scene["tilemaps"] so that
    # ngpc_tilemap.py exports its tiles.  The assembler suppresses individual
    # PUT_MAP calls for chunk tilemaps and replaces them with one combined
    # g_{safe}_bg_map[] (same format as single-map ngpc_mapstream path).
    _bg_chunk_raw: dict = scene.get("bg_chunk_map") or {}
    _bg_chunk_grid_paths: list[list[str]] = []
    if isinstance(_bg_chunk_raw, dict):
        for _row in (_bg_chunk_raw.get("grid") or []):
            if isinstance(_row, list):
                _bg_chunk_grid_paths.append([str(f).strip() for f in _row if f])
    # Normalised path set for O(1) membership test.
    _chunk_file_set: set[str] = {
        fp.replace("/", "\\")
        for row in _bg_chunk_grid_paths
        for fp in row
    }

    tilemap_infos: list[dict] = []
    bg_scr1_rel = str(scene.get("level_bg_scr1") or "").strip().replace("/", "\\")
    bg_scr2_rel = str(scene.get("level_bg_scr2") or "").strip().replace("/", "\\")
    layout_bound_bgs = {p for p in (bg_scr1_rel, bg_scr2_rel) if p}
    for tm in (scene.get("tilemaps") or []):
        if not isinstance(tm, dict):
            continue
        if not include_disabled and tm.get("export", True) is False:
            continue
        rel = str(tm.get("file") or "").strip()
        if not rel:
            continue
        tm_path = Path(rel)
        if not tm_path.is_absolute() and base_dir is not None:
            tm_path = Path(base_dir) / tm_path

        sym_base = _tilemap_symbol_base(tm_path)
        # Usual export: <export_dir>/<sym>_map.c/.h (written by ngpc_tilemap.py --header).
        out_c = export_dir / f"{sym_base}_map.c"
        out_h_inc = f"{sym_base}_map.h"
        tm_out_h = export_dir / out_h_inc

        # Reuse existing exports next to the PNG when present (template assets like intro_ngpc_craft_png).
        # This avoids duplicate symbols when the template already compiles GraphX/<sym>.c.
        existing_c = tm_path.with_suffix(".c")
        existing_h = tm_path.with_suffix(".h")
        use_existing = bool(existing_c.is_file() and existing_h.is_file())
        if use_existing:
            try:
                out_h_inc = os.path.relpath(existing_h, export_dir).replace("\\", "/")
            except Exception:
                out_h_inc = str(existing_h).replace("\\", "/")

        # Determine tile_base for this tilemap (stored or cascaded)
        base_val = tm.get("tile_base", None)
        try:
            tile_base = int(base_val) if base_val is not None else int(cursor)
        except Exception:
            tile_base = int(cursor)

        # Determine whether exported output is dual-layer and how many tiles it uses.
        c_src = existing_c if use_existing else out_c
        c_text = _read_text(c_src) if c_src.is_file() else None
        is_dual = bool(c_text and (f"{sym_base}_scr2_map_w" in c_text))
        slots_used = _parse_tilemap_tile_slots_from_c(c_text or "", sym_base) if c_text else None
        if slots_used is None:
            # Fallback: estimate from PNG size to keep tile_base cascade stable.
            if Image is not None and tm_path.is_file():
                try:
                    img = Image.open(tm_path)
                    w, h = img.size
                    if (w % 8) == 0 and (h % 8) == 0:
                        slots_used = (w // 8) * (h // 8)
                except Exception:
                    slots_used = None
        if slots_used is None:
            slots_used = 0

        cursor = int(tile_base) + int(slots_used)

        plane = str(tm.get("plane") or "auto").lower()
        if plane not in ("auto", "scr1", "scr2"):
            plane = "auto"
        rel_norm = str(rel).strip().replace("/", "\\")
        if plane == "auto" and layout_bound_bgs and rel_norm not in layout_bound_bgs:
            # When the scene layout explicitly binds background maps to SCR1/SCR2,
            # do not also blit unrelated auto-plane tilemaps. They would default to
            # SCR1 and visually overwrite the actual level background.
            continue
        if plane == "auto":
            if bg_scr2_rel and rel_norm == bg_scr2_rel:
                plane = "scr2"
            elif bg_scr1_rel and rel_norm == bg_scr1_rel:
                plane = "scr1"

        # Parse map dimensions to decide whether hardware wrapping is enough.
        if c_text:
            if is_dual:
                scr1_w, scr1_h = _parse_map_dims_from_c(c_text, sym_base + "_scr1")
                scr2_w, scr2_h = _parse_map_dims_from_c(c_text, sym_base + "_scr2")
                map_w, map_h = scr1_w, scr1_h
            else:
                map_w, map_h = _parse_map_dims_from_c(c_text, sym_base)
                scr1_w = scr1_h = scr2_w = scr2_h = None
        else:
            map_w = map_h = scr1_w = scr1_h = scr2_w = scr2_h = None

        tilemap_infos.append(
            {
                "sym_base": sym_base,
                "include": out_h_inc,
                "include_ok": bool(existing_h.is_file()) if use_existing else bool(tm_out_h.is_file()),
                "tile_base": int(tile_base),
                "is_dual": bool(is_dual),
                "plane": plane,
                "label": str(tm.get("name") or tm_path.name),
                "name_key": str(tm.get("name") or (tm_path.stem[:-5] if tm_path.stem.lower().endswith("_scr1") else tm_path.stem)),
                "slots_used": int(slots_used),
                "missing_c": (c_text is None),
                "map_w": map_w,
                "map_h": map_h,
                "scr1_map_w": scr1_w,
                "scr1_map_h": scr1_h,
                "scr2_map_w": scr2_w,
                "scr2_map_h": scr2_h,
                "c_text": c_text,  # kept for mapstream bg_map generation (Phase 2)
                # Track A: True when this tilemap is part of a bg_chunk_map grid.
                # Tiles are still loaded into VRAM; PUT_MAP is suppressed (assembled instead).
                "is_bg_chunk": bool(_chunk_file_set and rel_norm in _chunk_file_set),
            }
        )

    # Phase 4 budget: snapshot cursor (= next free tile slot after all tilemaps).
    # Tiles 0-127 reserved (system/font), 128-383 = 256 user slots, 384-511 = tight/overflow.
    # The cursor represents the hardware tile index of the first unused slot.
    _tile_cursor_final = int(cursor)

    exact_bg_analysis = None
    try:
        exact_bg_analysis = analyze_scene_bg_palette_banks_exact(scene, base_dir)
    except Exception:
        exact_bg_analysis = None

    exact_sig_by_plane_name: dict[tuple[str, str], tuple[tuple[int, ...], ...]] = {}
    if isinstance(exact_bg_analysis, dict):
        for _plane in ("scr1", "scr2"):
            _plane_info = exact_bg_analysis.get(_plane)
            if _plane_info is None:
                continue
            for _entry in getattr(_plane_info, "entries", ()) or ():
                _name = str(getattr(_entry, "name", "") or "").strip()
                _sig = getattr(_entry, "bank_signature", tuple())
                if _name and _sig:
                    exact_sig_by_plane_name[(_plane, _name)] = _sig

    # ---- DungeonGen flag for this scene ---------------------------------
    _rt_dg = (scene.get("rt_dungeongen_params") or {}) if isinstance(scene, dict) else {}
    has_dungeongen = bool(_rt_dg.get("enabled"))

    # ---- Emit header -------------------------------------------------
    lines: list[str] = []
    lines.append("/* Auto-generated by NgpCraft Engine -- do not edit */\n\n")
    lines.append(f"#ifndef {guard}\n#define {guard}\n\n")
    lines.append('#include "ngpc_gfx.h"\n')
    if ent_draw_types:
        lines.append('#include "ngpc_metasprite.h"\n')
    lines.append('#include "ngpc_tilemap_blit.h"\n\n')
    lines.append('#include "ngpc_types.h"  /* u8 */\n')
    lines.append('#include "ngpc_vramq.h"\n\n')

    for nm in sprite_names:
        safe_nm = re.sub(r"[^a-zA-Z0-9_]+", "_", nm).strip("_")
        lines.append(f'#include "{safe_nm}_mspr.h"\n')
    for info in tilemap_infos:
        if bool(info.get("missing_c")) or (not bool(info.get("include_ok"))):
            continue
        lines.append(f'#include "{info["include"]}"\n')
    # Scene gameplay metadata (entities, collision, layout...) generated alongside exports.
    if include_level:
        lines.append(f'#include "scene_{safe}_level.h"\n')
    if has_dungeongen:
        lines.append('#if defined(NGPNG_HAS_DUNGEONGEN) && (NGPNG_HAS_DUNGEONGEN)\n')
        lines.append('#include "ngpc_dungeongen/ngpc_dungeongen.h"\n')
        lines.append('#endif\n')
    if sprite_names or tilemap_infos or has_dungeongen:
        lines.append("\n")

    # NOTE: THC (TLCS-900) compiler is closer to C89 and does not accept C99 'inline'
    # nor mixed declarations/statements. Keep this helper C89-compatible and define
    # it once per translation unit (scenes_autogen.c includes multiple scene_*.h).
    lines.append("#ifndef NGPNG_HAVE_LOAD_SPRITE_PALETTES\n")
    lines.append("#define NGPNG_HAVE_LOAD_SPRITE_PALETTES\n")
    lines.append("static void ngpng_load_sprite_palettes(const u16 *pals, u8 palette_count, u8 pal_base)\n{\n")
    lines.append("    u8 p;\n")
    lines.append("    u16 off;\n")
    lines.append("    for (p = 0; p < palette_count; ++p) {\n")
    lines.append("        off = (u16)p * 4u;\n")
    lines.append("        ngpc_gfx_set_palette(\n")
    lines.append("            GFX_SPR,\n")
    lines.append("            (u8)(pal_base + p),\n")
    lines.append("            pals[off + 0u], pals[off + 1u], pals[off + 2u], pals[off + 3u]\n")
    lines.append("        );\n")
    lines.append("    }\n")
    lines.append("}\n")
    lines.append("#endif\n\n")

    lines.append(f"static void scene_{safe}_load_sprites(void)\n{{\n")
    if not sprite_names:
        lines.append("    /* (no sprites) */\n")
    else:
        for cid in sprite_cids:  # C-safe identifiers (hyphens replaced by underscores)
            lines.append(f"    ngpng_load_sprite_palettes({cid}_palettes, {cid}_palette_count, {cid}_pal_base);\n")
            lines.append(f"    ngpc_gfx_load_tiles_at({cid}_tiles, {cid}_tiles_count, {cid}_tile_base);\n")
    lines.append("}\n\n")

    lines.append(f"static void scene_{safe}_blit_tilemaps(void)\n{{\n")
    if not tilemap_infos:
        lines.append("    /* (no tilemaps) */\n")
    else:
        seen_bg_sig: dict[str, set[tuple[tuple[int, ...], ...]]] = {"scr1": set(), "scr2": set()}
        for info in tilemap_infos:
            sym = str(info["sym_base"])
            tb = int(info["tile_base"])
            label_c = str(info["label"]).replace("*/", "* /")
            name_key = str(info.get("name_key") or info.get("label") or "").strip()
            if bool(info["missing_c"]):
                lines.append(f"    /* WARN: missing export for {label_c} ({sym}_map.c) -- tile_base={tb} */\n")
                lines.append("\n")
                continue
            if not bool(info.get("include_ok")):
                lines.append(f"    /* WARN: missing header for {label_c} ({sym}_map.h) -- tile_base={tb} */\n")
                lines.append("\n")
                continue
            elif int(info["slots_used"]) <= 0:
                lines.append(f"    /* NOTE: cannot detect tile usage for {label_c} -- tile_base={tb} */\n")
            else:
                lines.append(f"    /* {label_c} -- tile_base={tb} tiles={int(info['slots_used'])} */\n")

            # Helper: return True when a plane's tilemap exceeds the 32×32 HW window
            # and therefore needs streaming.  In that case PUT_MAP is skipped here —
            # stream_planes() handles the initial fill via need_full on the first frame.
            def _plane_needs_stream(inf: dict, sfx: str) -> bool:
                # Chunk tilemaps: tiles go to VRAM but PUT_MAP is handled by assembler.
                if inf.get("is_bg_chunk"):
                    return True
                w = inf.get(f"{sfx}_map_w" if sfx else "map_w")
                h = inf.get(f"{sfx}_map_h" if sfx else "map_h")
                if w is None or h is None:
                    return True   # unknown dims → assume streaming needed
                return int(w) > 32 or int(h) > 32

            if bool(info["is_dual"]):
                sig_scr1 = exact_sig_by_plane_name.get(("scr1", name_key), tuple())
                sig_scr2 = exact_sig_by_plane_name.get(("scr2", name_key), tuple())
                lines.append(f"    NGP_TILEMAP_LOAD_TILES_VRAM({sym}, {tb});\n")
                if sig_scr1 and sig_scr1 in seen_bg_sig["scr1"]:
                    lines.append(f"    /* Reuse exact SCR1 palette bank already loaded for {label_c}. */\n")
                else:
                    lines.append(f"    NGP_TILEMAP_LOAD_PALETTES_SCR1({sym}_scr1);\n")
                    if sig_scr1:
                        seen_bg_sig["scr1"].add(sig_scr1)
                if _plane_needs_stream(info, "scr1"):
                    lines.append(f"    /* Large map: SCR1 tilemap filled by stream_planes() on first frame. */\n")
                else:
                    lines.append(f"    NGP_TILEMAP_PUT_MAP_SCR1({sym}_scr1, {tb});\n")
                if sig_scr2 and sig_scr2 in seen_bg_sig["scr2"]:
                    lines.append(f"    /* Reuse exact SCR2 palette bank already loaded for {label_c}. */\n")
                else:
                    lines.append(f"    NGP_TILEMAP_LOAD_PALETTES_SCR2({sym}_scr2);\n")
                    if sig_scr2:
                        seen_bg_sig["scr2"].add(sig_scr2)
                if _plane_needs_stream(info, "scr2"):
                    lines.append(f"    /* Large map: SCR2 tilemap filled by stream_planes() on first frame. */\n")
                else:
                    lines.append(f"    NGP_TILEMAP_PUT_MAP_SCR2({sym}_scr2, {tb});\n")
            else:
                plane = str(info["plane"])
                target_plane = "scr2" if plane == "scr2" else "scr1"
                sig_single = exact_sig_by_plane_name.get((target_plane, name_key), tuple())
                lines.append(f"    NGP_TILEMAP_LOAD_TILES_VRAM({sym}, {tb});\n")
                if target_plane == "scr2":
                    if sig_single and sig_single in seen_bg_sig["scr2"]:
                        lines.append(f"    /* Reuse exact SCR2 palette bank already loaded for {label_c}. */\n")
                    else:
                        lines.append(f"    NGP_TILEMAP_LOAD_PALETTES_SCR2({sym});\n")
                        if sig_single:
                            seen_bg_sig["scr2"].add(sig_single)
                    if _plane_needs_stream(info, ""):
                        lines.append(f"    /* Large map: SCR2 tilemap filled by stream_planes() on first frame. */\n")
                    else:
                        lines.append(f"    NGP_TILEMAP_PUT_MAP_SCR2({sym}, {tb});\n")
                else:
                    if sig_single and sig_single in seen_bg_sig["scr1"]:
                        lines.append(f"    /* Reuse exact SCR1 palette bank already loaded for {label_c}. */\n")
                    else:
                        lines.append(f"    NGP_TILEMAP_LOAD_PALETTES_SCR1({sym});\n")
                        if sig_single:
                            seen_bg_sig["scr1"].add(sig_single)
                    if _plane_needs_stream(info, ""):
                        lines.append(f"    /* Large map: SCR1 managed by ngpc_mapstream — see ngpng_mapstream_load_scene(). */\n")
                    else:
                        lines.append(f"    NGP_TILEMAP_PUT_MAP_SCR1({sym}, {tb});\n")
            lines.append("\n")
    lines.append("}\n\n")

    # Determine which scroll planes need software streaming.
    # A plane needs streaming only when its tilemap is larger than the 32×32 VRAM window.
    # For 32-wide-or-less maps, the hardware scroll register wraps for free — no VRAM
    # rewrites are needed at all (same pattern as Shmup_StarGunner reference).
    def _dims_for_plane(info: dict, suffix: str) -> tuple[int | None, int | None]:
        if suffix:
            return info.get(f"{suffix}_map_w"), info.get(f"{suffix}_map_h")
        return info.get("map_w"), info.get("map_h")

    needs_stream: dict[str, bool] = {}
    needs_stream_unknown_dims: dict[str, bool] = {}  # True if streaming was inferred (no C file)
    for _pn in ("scr1", "scr2"):
        _pinfos = []
        for _inf in tilemap_infos:
            if bool(_inf["is_dual"]):
                _pinfos.append((_inf, _pn))
            elif str(_inf["plane"]) == _pn:
                _pinfos.append((_inf, ""))
        _plane_needs = False
        _dims_unknown = False
        for _inf, _sfx in _pinfos:
            _w, _h = _dims_for_plane(_inf, _sfx)
            if _w is None or _h is None:
                # Dims unknown (tilemap C file not yet exported).
                # Do NOT enable streaming speculatively — the map may well be ≤32×32.
                # A warning will be emitted in the generated header.
                _dims_unknown = True
            elif int(_w) > 32 or int(_h) > 32:
                _plane_needs = True
                break
        needs_stream[_pn] = _plane_needs and bool(_pinfos)
        needs_stream_unknown_dims[_pn] = _dims_unknown and not _plane_needs and bool(_pinfos)

    # Pick the mapstream plane for this scene. Priority: SCR1 → SCR2.
    #   "scr1" : SCR1 has a large tilemap → mapstream on SCR1 (legacy path).
    #   "scr2" : SCR1 has no large tilemap but SCR2 does → mapstream on SCR2.
    #   ""     : neither plane needs mapstream.
    # Track A (bg_chunk_map grid) always produces a bg_map.c targeted at SCR1.
    ms_plane = ""
    if needs_stream.get("scr1", False):
        ms_plane = "scr1"
    elif needs_stream.get("scr2", False):
        ms_plane = "scr2"
    if _bg_chunk_grid_paths:
        ms_plane = "scr1"
    # Legacy alias: downstream code still calls this `scr1_by_mapstream`.
    scr1_by_mapstream = (ms_plane == "scr1")

    # stream_planes (direct per-frame VRAM writer) is only needed for SCR2 when SCR2
    # is large AND not already owned by mapstream. Small maps (≤32×32) wrap for free
    # via the hardware scroll register — no VRAM rewrites at all.
    any_streaming = needs_stream.get("scr2", False) and ms_plane != "scr2"

    # Safety: prevent dual-plane streaming (SCR1 via mapstream + SCR2 via stream_planes).
    # Both share the VBlank VRAM bandwidth. If both planes exceed 32×32, prioritise SCR1
    # (via ngpc_mapstream) and disable SCR2 streaming to protect the VBlank budget.
    # The user must redesign the scene so that at most one scroll plane is large.
    dual_stream_blocked = scr1_by_mapstream and any_streaming
    if dual_stream_blocked:
        any_streaming = False

    # Read scene loop and parallax settings for SCR2 streaming optimisation.
    # For non-looping axes with parallax ≤ 100 %, cam constraints guarantee
    # scr2x < map_w*8 (always non-negative), so view_tx = scr2x >> 3 is exact —
    # no software division needed.  Saves 4 software divs/frame on T900.
    _level_scroll = scene.get("level_scroll") or {}
    _loop_x = bool(_level_scroll.get("loop_x", False))
    _loop_y = bool(_level_scroll.get("loop_y", False))
    _level_layers = scene.get("level_layers") or {}
    try:
        _scr2_par_x = max(0, min(200, int(_level_layers.get("scr2_parallax_x", 100) or 100)))
    except Exception:
        _scr2_par_x = 100
    try:
        _scr2_par_y = max(0, min(200, int(_level_layers.get("scr2_parallax_y", 100) or 100)))
    except Exception:
        _scr2_par_y = 100
    _fast_tx = not _loop_x and _scr2_par_x <= 100
    _fast_ty = not _loop_y and _scr2_par_y <= 100
    _need_tile_origin = not (_fast_tx and _fast_ty)

    # Phase 2 mapstream: generate scene_{safe}_bg_map.c with FAR tileword array.
    # This file defines g_{safe}_bg_map[] used by ngpc_mapstream_init().
    # assets_autogen_mk.py picks it up automatically at next export run.
    _scr1_cam_map_w: int = 0
    _scr1_cam_map_h: int = 0
    if ms_plane == "scr1":
        if _bg_chunk_grid_paths:
            # Track A: assemble multi-chunk grid into one flat tileword array.
            # Build chunk_infos_grid by matching each grid path to tilemap_infos.
            _info_by_sym: dict[str, dict] = {
                str(inf["sym_base"]): inf for inf in tilemap_infos
            }
            _chunk_infos_grid: list[list[dict]] = []
            _grid_ok = True
            for _row_paths in _bg_chunk_grid_paths:
                _row_infos: list[dict] = []
                for _fp in _row_paths:
                    _sym = _tilemap_symbol_base(Path(_fp))
                    _ci = _info_by_sym.get(_sym)
                    if _ci is None:
                        # Try reading the .c directly from export_dir.
                        _direct_c = export_dir / f"{_sym}_map.c"
                        _ct2 = _direct_c.read_text(encoding="utf-8") if _direct_c.is_file() else None
                        _mw2, _mh2 = _parse_map_dims_from_c(_ct2 or "", _sym) if _ct2 else (None, None)
                        _ci = {
                            "sym_base": _sym, "tile_base": 128,
                            "c_text": _ct2, "map_w": _mw2, "map_h": _mh2,
                        }
                    _row_infos.append({
                        "sym_base": str(_ci["sym_base"]),
                        "tile_base": int(_ci.get("tile_base") or 128),
                        "c_text": _ci.get("c_text") or "",
                        "map_w": int(_ci.get("map_w") or 0),
                        "map_h": int(_ci.get("map_h") or 0),
                    })
                _chunk_infos_grid.append(_row_infos)
            if _grid_ok and _chunk_infos_grid:
                _out, _scr1_cam_map_w, _scr1_cam_map_h = _assemble_chunk_bg_map_c(
                    safe, _chunk_infos_grid, export_dir
                )
        else:
            # Single large map (existing path).
            for _inf in tilemap_infos:
                _is_dual = bool(_inf.get("is_dual", False))
                _plane = str(_inf.get("plane", ""))
                if _is_dual or _plane == "scr1":
                    _scr1_sym = str(_inf["sym_base"]) + ("_scr1" if _is_dual else "")
                    _tb = int(_inf["tile_base"])
                    _ct = _inf.get("c_text") or ""
                    _mw = int(_inf.get("scr1_map_w") or _inf.get("map_w") or 0)
                    _mh = int(_inf.get("scr1_map_h") or _inf.get("map_h") or 0)
                    _scr1_cam_map_w = _mw
                    _scr1_cam_map_h = _mh
                    if _ct and _mw > 0 and _mh > 0:
                        _write_scene_bg_map_c(safe, _scr1_sym, _tb, _ct, export_dir, _mw, _mh)
                    break
    elif ms_plane == "scr2":
        # Large tilemap lives on SCR2 → write bg_map.c from the SCR2 layer.
        # Same symbol name scheme as SCR1 (g_{safe}_bg_map); only the plane
        # passed to ngpc_mapstream_init() differs (handled by autorun generator).
        for _inf in tilemap_infos:
            _is_dual = bool(_inf.get("is_dual", False))
            _plane = str(_inf.get("plane", ""))
            if _is_dual or _plane == "scr2":
                _scr2_sym = str(_inf["sym_base"]) + ("_scr2" if _is_dual else "")
                _tb = int(_inf["tile_base"])
                _ct = _inf.get("c_text") or ""
                _mw = int(_inf.get("scr2_map_w") or _inf.get("map_w") or 0)
                _mh = int(_inf.get("scr2_map_h") or _inf.get("map_h") or 0)
                _scr1_cam_map_w = _mw  # variable names kept for downstream use
                _scr1_cam_map_h = _mh
                if _ct and _mw > 0 and _mh > 0:
                    _write_scene_bg_map_c(safe, _scr2_sym, _tb, _ct, export_dir, _mw, _mh, plane_label="SCR2")
                break

    # Publish the mapstream plane (0=none, 1=SCR1, 2=SCR2) so the autorun
    # generator can pass the matching GFX_SCRx constant to ngpc_mapstream_init().
    _ms_plane_num = 1 if ms_plane == "scr1" else (2 if ms_plane == "scr2" else 0)
    lines.append(f"#define SCENE_{safe.upper()}_MAPSTREAM_PLANE {_ms_plane_num}\n")

    # Publish whether this scene needs per-frame VRAM streaming.
    # scenes_autogen_gen.py reads this to set stream_planes = NULL when not needed,
    # so ngpng_apply_plane_scroll falls through to the full-scroll hardware path.
    lines.append(f"#define SCENE_{safe.upper()}_STREAM_PLANES_NEEDED {1 if any_streaming else 0}\n\n")

    # Camera scroll bounds for ngpc_mapstream clamping (Sonic disassembly §9.6).
    # CAM_MAX_X = (map_w - SCREEN_TW) * 8 px  (last valid left-edge pixel before right border)
    # CAM_MAX_Y = (map_h - SCREEN_TH) * 8 px  (last valid top-edge pixel before bottom border)
    # Use NGPC_MS_CLAMP_X/Y macros from ngpc_mapstream.h, or compare directly.
    if bool(ms_plane) and _scr1_cam_map_w > 20 and _scr1_cam_map_h > 19:
        _cx = (_scr1_cam_map_w - 20) * 8
        _cy = (_scr1_cam_map_h - 19) * 8
        if _bg_chunk_grid_paths:
            n_cg_r = len(_bg_chunk_grid_paths)
            n_cg_c = len(_bg_chunk_grid_paths[0]) if _bg_chunk_grid_paths else 0
            lines.append(f"/* MAP-1 chunk grid: {n_cg_r}x{n_cg_c} chunks assembled to {_scr1_cam_map_w}x{_scr1_cam_map_h} tiles. */\n")
            lines.append(f"/* Set scene level_size to w={_scr1_cam_map_w} h={_scr1_cam_map_h} for correct col_map + entity bounds. */\n")
            lines.append(f"#define SCENE_{safe.upper()}_CHUNK_MAP_W {_scr1_cam_map_w}\n")
            lines.append(f"#define SCENE_{safe.upper()}_CHUNK_MAP_H {_scr1_cam_map_h}\n")
        lines.append(f"/* Camera pixel bounds for ngpc_mapstream (NGPC_MS_CLAMP_X/Y) */\n")
        lines.append(f"#define SCENE_{safe.upper()}_CAM_MAX_X  {_cx}  /* px, map {_scr1_cam_map_w} tiles wide  */\n")
        lines.append(f"#define SCENE_{safe.upper()}_CAM_MAX_Y  {_cy}  /* px, map {_scr1_cam_map_h} tiles tall */\n\n")
    elif _bg_chunk_grid_paths and _scr1_cam_map_w == 0:
        lines.append(f"/* WARNING: bg_chunk_map grid assembly failed for scene '{safe}'.\n")
        lines.append(f" * Ensure all chunk PNGs are listed in scene tilemaps and exported first. */\n\n")

    # Emit build-time warnings for problematic configurations.
    if dual_stream_blocked:
        lines.append(
            f"/* !!! DUAL LARGE-MAP BLOCKED — scene '{safe}' !!!\n"
            f" * SCR1 and SCR2 are both large (>32x32 tiles).\n"
            f" * Streaming both planes simultaneously exceeds the VBlank VRAM budget on real hardware.\n"
            f" * SCR1 is streamed via ngpc_mapstream (kept). SCR2 streaming has been DISABLED.\n"
            f" * SCR2 falls back to hardware scroll wrap — it will glitch visually if the map > 32x32.\n"
            f" * FIX: keep at most ONE scroll plane larger than 32x32 per scene. */\n\n"
        )
    if needs_stream_unknown_dims.get("scr1") or needs_stream_unknown_dims.get("scr2"):
        _unk_planes = ", ".join(p.upper() for p in ("scr1", "scr2") if needs_stream_unknown_dims.get(p))
        lines.append(
            f"/* NOTE: {_unk_planes} tilemap dimensions unknown (C file not yet exported).\n"
            f" * Streaming disabled for this plane — re-export after running ngpc_tilemap.py. */\n\n"
        )

    # Phase 4 — VRAM tile budget warning (build-time diagnostic).
    # NGPC tile VRAM: 512 slots total (0-511). Slots 0-127 reserved.
    # User tiles: 128-511 = 384 slots. Sprites share this range above the tilemap cursor.
    # Thresholds: ≤256 safe, 257-320 warning, 321-384 caution, >384 overflow (sprites will corrupt).
    _U = safe.upper()
    lines.append(f"/* VRAM tile budget: next free slot = {_tile_cursor_final} "
                 f"(used {_tile_cursor_final - 128} / 384 user slots) */\n")
    lines.append(f"#define SCENE_{_U}_TILE_CURSOR {_tile_cursor_final}\n")
    if _tile_cursor_final > 384:
        lines.append(
            f"#error \"VRAM OVERFLOW scene '{safe}': tile cursor {_tile_cursor_final} > 384"
            f" -- sprite tiles will corrupt BG! Reduce tilemap tile count.\"\n\n"
        )
    elif _tile_cursor_final > 320:
        lines.append(
            f"#warning \"VRAM tight scene '{safe}': tile cursor {_tile_cursor_final} (321-384)"
            f" -- little room for sprites. Consider reducing tile count.\"\n\n"
        )
    elif _tile_cursor_final > 256:
        lines.append(
            f"#warning \"VRAM budget notice scene '{safe}': tile cursor {_tile_cursor_final} (257-320)"
            f" -- monitor sprite tile usage.\"\n\n"
        )
    else:
        lines.append("\n")

    if tilemap_infos and any_streaming:
        # Only SCR2 uses stream_planes; SCR1 large maps are delegated to ngpc_mapstream.
        # No RAM buffers — direct VRAM writes only (same approach as ngpc_mapstream.c ms_put).
        lines.append(f"static u16 scene_{safe}_stream_last_scr2_tx = 0xFFFFu;\n")
        lines.append(f"static u16 scene_{safe}_stream_last_scr2_ty = 0xFFFFu;\n\n")
        # Only emit the modulo-based helper when at least one axis requires it
        # (looping map or parallax > 100 %).  Non-looping axes with parallax ≤ 100
        # guarantee scr2x < map_w*8, so a plain >> 3 is sufficient and avoids
        # two software divisions per call on the T900.
        if _need_tile_origin:
            lines.append(f"static u16 scene_{safe}_stream_tile_origin(s16 scroll_px, u16 map_tiles)\n{{\n")
            lines.append("    s16 size_px = (s16)(map_tiles * 8u);\n")
            lines.append("    s16 v;\n")
            lines.append("    if (map_tiles == 0u || size_px <= 0) return 0u;\n")
            lines.append("    v = (s16)(scroll_px % size_px);\n")
            lines.append("    if (v < 0) v = (s16)(v + size_px);\n")
            lines.append("    return (u16)((u16)v >> 3);\n")
            lines.append("}\n\n")
        lines.append(f"static void scene_{safe}_stream_planes(s16 scr1x, s16 scr1y, s16 scr2x, s16 scr2y)\n{{\n")
        lines.append("    u8 x;\n")
        lines.append("    u8 y;\n")
        # SCR1: always suppress — delegated to ngpc_mapstream (large) or hardware scroll (small).
        # stream_planes must never write SCR1 tiles to avoid the dual-stream conflict.
        if scr1_by_mapstream:
            lines.append("    /* SCR1 managed by ngpc_mapstream — tile writes handled there. */\n")
        lines.append("    (void)scr1x; (void)scr1y;\n")
        # SCR2 streaming with direct VRAM writes (mirrors ngpc_mapstream ms_put approach).
        scr2_plane_infos = []
        for _i in tilemap_infos:
            if bool(_i["is_dual"]):
                scr2_plane_infos.append((_i, "scr2"))
            elif str(_i["plane"]) == "scr2":
                scr2_plane_infos.append((_i, ""))
        if not scr2_plane_infos:
            lines.append("    (void)scr2x; (void)scr2y;\n")
        else:
            cache_tx = f"scene_{safe}_stream_last_scr2_tx"
            cache_ty = f"scene_{safe}_stream_last_scr2_ty"
            first_info, first_suffix = scr2_plane_infos[0]
            first_sym = str(first_info["sym_base"]) + (f"_{first_suffix}" if first_suffix else "")
            lines.append("    {\n")
            lines.append("        volatile u16 *vb = (volatile u16 *)HW_SCR2_MAP;\n")
            lines.append("        u16 view_tx = 0u;\n")
            lines.append("        u16 view_ty = 0u;\n")
            lines.append("        u16 prev_tx = 0u;\n")
            lines.append("        u16 prev_ty = 0u;\n")
            lines.append("        u16 dst_col = 0u;\n")
            lines.append("        u16 src_col = 0u;\n")
            lines.append("        u16 dst_row = 0u;\n")
            lines.append("        u16 src_row = 0u;\n")
            lines.append("        u16 src_y = 0u;\n")
            lines.append("        u16 dst_y = 0u;\n")
            lines.append("        u16 src_x = 0u;\n")
            lines.append("        u16 dst_x = 0u;\n")
            lines.append("        u16 src_i = 0u;\n")
            lines.append("        u16 tile = 0u;\n")
            lines.append("        u16 pal = 0u;\n")
            lines.append("        u16 tw = 0u;\n")
            lines.append("        u16 voff = 0u;\n")
            lines.append("        u8 need_full = 0u;\n")
            lines.append("        u8 patch_right = 0u;\n")
            lines.append("        u8 patch_left = 0u;\n")
            lines.append("        u8 patch_down = 0u;\n")
            lines.append("        u8 patch_up = 0u;\n")
            # Non-looping axis with parallax ≤ 100 %: cam constraints ensure scroll_px
            # is always in [0, map_w*8), so view_tx = scroll_px >> 3 (no division).
            if _fast_tx:
                lines.append(f"        view_tx = (u16)((u16)scr2x >> 3u);\n")
            else:
                lines.append(f"        view_tx = scene_{safe}_stream_tile_origin(scr2x, (u16){first_sym}_map_w);\n")
            if _fast_ty:
                lines.append(f"        view_ty = (u16)((u16)scr2y >> 3u);\n")
            else:
                lines.append(f"        view_ty = scene_{safe}_stream_tile_origin(scr2y, (u16){first_sym}_map_h);\n")
            lines.append(f"        prev_tx = {cache_tx};\n")
            lines.append(f"        prev_ty = {cache_ty};\n")
            lines.append(f"        if (prev_tx == 0xFFFFu || prev_ty == 0xFFFFu) need_full = 1u;\n")
            lines.append("        else {\n")
            lines.append(f"            if (view_tx == prev_tx) {{\n")
            # Non-looping x with parallax ≤ 100 %: camera clamping guarantees
            # prev_tx+1 < map_w, so the modulo is always a no-op — omit it.
            if _fast_tx:
                lines.append("            } else if (view_tx == (u16)(prev_tx + 1u)) {\n")
                lines.append("                patch_right = 1u;\n")
                lines.append("                dst_col = (u16)((view_tx + 31u) & 31u);\n")
                lines.append("                src_col = (u16)((view_tx + 31u) % (u16)" + first_sym + "_map_w);\n")
                lines.append("            } else if (prev_tx == (u16)(view_tx + 1u)) {\n")
                lines.append("                patch_left = 1u;\n")
                lines.append("                dst_col = (u16)(view_tx & 31u);\n")
                lines.append("                src_col = view_tx;\n")
            else:
                lines.append("            } else if (view_tx == (u16)((prev_tx + 1u) % (u16)" + first_sym + "_map_w)) {\n")
                lines.append("                patch_right = 1u;\n")
                lines.append("                dst_col = (u16)((view_tx + 31u) & 31u);\n")
                lines.append("                src_col = (u16)((view_tx + 31u) % (u16)" + first_sym + "_map_w);\n")
                lines.append("            } else if (prev_tx == (u16)((view_tx + 1u) % (u16)" + first_sym + "_map_w)) {\n")
                lines.append("                patch_left = 1u;\n")
                lines.append("                dst_col = (u16)(view_tx & 31u);\n")
                lines.append("                src_col = (u16)(view_tx % (u16)" + first_sym + "_map_w);\n")
            lines.append("            } else {\n")
            lines.append("                need_full = 1u;\n")
            lines.append("            }\n")
            lines.append("            if (!need_full) {\n")
            lines.append(f"                if (view_ty == prev_ty) {{\n")
            # Non-looping y with parallax ≤ 100 %: same simplification.
            if _fast_ty:
                lines.append("                } else if (view_ty == (u16)(prev_ty + 1u)) {\n")
                lines.append("                    patch_down = 1u;\n")
                lines.append("                    dst_row = (u16)((view_ty + 19u) & 31u);\n")
                lines.append("                    src_row = (u16)((view_ty + 19u) % (u16)" + first_sym + "_map_h);\n")
                lines.append("                } else if (prev_ty == (u16)(view_ty + 1u)) {\n")
                lines.append("                    patch_up = 1u;\n")
                lines.append("                    dst_row = (u16)(view_ty & 31u);\n")
                lines.append("                    src_row = view_ty;\n")
            else:
                lines.append("                } else if (view_ty == (u16)((prev_ty + 1u) % (u16)" + first_sym + "_map_h)) {\n")
                lines.append("                    patch_down = 1u;\n")
                lines.append("                    dst_row = (u16)((view_ty + 19u) & 31u);\n")
                lines.append("                    src_row = (u16)((view_ty + 19u) % (u16)" + first_sym + "_map_h);\n")
                lines.append("                } else if (prev_ty == (u16)((view_ty + 1u) % (u16)" + first_sym + "_map_h)) {\n")
                lines.append("                    patch_up = 1u;\n")
                lines.append("                    dst_row = (u16)(view_ty & 31u);\n")
                lines.append("                    src_row = (u16)(view_ty % (u16)" + first_sym + "_map_h);\n")
            lines.append("                } else {\n")
            lines.append("                    need_full = 1u;\n")
            lines.append("                }\n")
            lines.append("            }\n")
            lines.append("        }\n")
            lines.append("        if (need_full || patch_right || patch_left || patch_down || patch_up) {\n")
            for _info, _suffix in scr2_plane_infos:
                _sym = str(_info["sym_base"]) + (f"_{_suffix}" if _suffix else "")
                _tb = int(_info["tile_base"])
                # Retrieve map dims known at export time — used to emit shifts/masks
                # instead of runtime multiplications and modulos (PERF-GEN-A/B/C).
                _raw_mw, _raw_mh = _dims_for_plane(_info, _suffix)
                _mw = int(_raw_mw) if _raw_mw is not None else 0
                _mh = int(_raw_mh) if _raw_mh is not None else 0
                _pow2_w = _is_pow2(_mw)
                _pow2_h = _is_pow2(_mh)
                # Pre-compute masks/shifts as literal C constants where possible.
                # PERF-GEN-C: % map_w → & (map_w-1) literal, avoids runtime division.
                _modw = f"& {_mw - 1}u" if _pow2_w else f"% (u16){_sym}_map_w"
                _modh = f"& {_mh - 1}u" if _pow2_h else f"% (u16){_sym}_map_h"
                # PERF-GEN-B: src_y * map_w → src_y << log2(map_w) literal shift.
                if _pow2_w:
                    _shift_w = _log2(_mw)
                    _mul_mw = f"(u16)(src_y << {_shift_w}u)"
                    _mul_row_mw = f"(u16)(src_row_clamped << {_shift_w}u)"
                else:
                    _mul_mw = f"(u16)(src_y * (u16){_sym}_map_w)"
                    _mul_row_mw = f"(u16)(src_row_clamped * (u16){_sym}_map_w)"
                # Each tilemap lives in its own C block so that src_row_clamped
                # stays scoped even when multiple SCR2 tilemaps are generated.
                lines.append("            {\n")
                # need_full: write 20 visible rows × 32 cols directly to VRAM (no buffer).
                lines.append("            if (need_full) {\n")
                lines.append("                for (y = 0u; y < 20u; ++y) {\n")
                lines.append(f"                    src_y = (u16)((view_ty + y) {_modh});\n")
                lines.append("                    dst_y = (u16)((view_ty + y) & 31u);\n")
                lines.append("                    for (x = 0u; x < 32u; ++x) {\n")
                lines.append(f"                        src_x = (u16)((view_tx + x) {_modw});\n")
                lines.append("                        dst_x = (u16)((view_tx + x) & 31u);\n")
                lines.append(f"                        src_i = (u16)({_mul_mw} + src_x);\n")
                lines.append(f"                        tile = (u16)({_tb}u + {_sym}_map_tiles[src_i]);\n")
                lines.append(f"                        pal = (u16)({_sym}_map_pals[src_i] & 0x0Fu);\n")
                lines.append("                        tw = (u16)(tile + (pal << 9));\n")
                lines.append("                        voff = (u16)((dst_y << 5u) + dst_x);\n")
                lines.append("                        vb[voff] = tw;\n")
                lines.append("                    }\n")
                lines.append("                }\n")
                lines.append("            } else {\n")
                # Column patch: 20 writes (one per visible row) — same cost as ngpc_mapstream ms_stream_col.
                # src_col is already in [0, map_w) from the patch detection above, so the % is
                # redundant for non-looping maps; for looping maps apply the same mask/modulo.
                if _pow2_w:
                    _src_col_clamped = f"(u16)(src_col & {_mw - 1}u)"
                else:
                    _src_col_clamped = f"(u16)(src_col % (u16){_sym}_map_w)"
                lines.append("                if (patch_right || patch_left) {\n")
                lines.append("                    for (y = 0u; y < 20u; ++y) {\n")
                lines.append(f"                        src_y = (u16)((view_ty + y) {_modh});\n")
                lines.append("                        dst_y = (u16)((view_ty + y) & 31u);\n")
                lines.append(f"                        src_i = (u16)({_mul_mw} + {_src_col_clamped});\n")
                lines.append(f"                        tile = (u16)({_tb}u + {_sym}_map_tiles[src_i]);\n")
                lines.append(f"                        pal = (u16)({_sym}_map_pals[src_i] & 0x0Fu);\n")
                lines.append("                        tw = (u16)(tile + (pal << 9));\n")
                lines.append("                        voff = (u16)((dst_y << 5u) + dst_col);\n")
                lines.append("                        vb[voff] = tw;\n")
                lines.append("                    }\n")
                lines.append("                }\n")
                # Row patch: 32 writes (one per column) — same cost as ngpc_mapstream ms_stream_row.
                # Clamp src_row once before the inner loop to avoid repeating the modulo.
                lines.append("                if (patch_down || patch_up) {\n")
                if _pow2_h:
                    lines.append(f"                    u16 src_row_clamped = (u16)(src_row & {_mh - 1}u);\n")
                else:
                    lines.append(f"                    u16 src_row_clamped = (u16)(src_row % (u16){_sym}_map_h);\n")
                lines.append("                    for (x = 0u; x < 32u; ++x) {\n")
                lines.append(f"                        src_x = (u16)((view_tx + x) {_modw});\n")
                lines.append("                        dst_x = (u16)((view_tx + x) & 31u);\n")
                lines.append(f"                        src_i = (u16)({_mul_row_mw} + src_x);\n")
                lines.append(f"                        tile = (u16)({_tb}u + {_sym}_map_tiles[src_i]);\n")
                lines.append(f"                        pal = (u16)({_sym}_map_pals[src_i] & 0x0Fu);\n")
                lines.append("                        tw = (u16)(tile + (pal << 9));\n")
                lines.append("                        voff = (u16)((dst_row << 5u) + dst_x);\n")
                lines.append("                        vb[voff] = tw;\n")
                lines.append("                    }\n")
                lines.append("                }\n")
                lines.append("            }\n")
                lines.append("            }\n")  # close per-tilemap scope
            lines.append(f"            {cache_tx} = view_tx;\n")
            lines.append(f"            {cache_ty} = view_ty;\n")
            lines.append("        }\n")
            lines.append("    }\n")
        lines.append("}\n\n")
    else:
        # All tilemaps fit in the 32×32 hardware VRAM window.
        # blit_tilemaps() loads everything at init; hardware scroll register handles
        # wrapping per-frame with zero VRAM rewrites (same as Shmup_StarGunner).
        lines.append(f"static void scene_{safe}_stream_planes(s16 scr1x, s16 scr1y, s16 scr2x, s16 scr2y)\n{{\n")
        lines.append("    (void)scr1x; (void)scr1y; (void)scr2x; (void)scr2y;\n")
        lines.append("}\n\n")

    lines.append(f"static void scene_{safe}_load_all(void)\n{{\n")
    lines.append("    /* Clear both planes to avoid leftovers from previous scenes. */\n")
    lines.append("    ngpc_gfx_clear(GFX_SCR1);\n")
    lines.append("    ngpc_gfx_clear(GFX_SCR2);\n")
    if tilemap_infos and any_streaming:
        # Reset SCR2 streaming state (SCR1 is managed by ngpc_mapstream — no state here).
        lines.append(f"    scene_{safe}_stream_last_scr2_tx = 0xFFFFu;\n")
        lines.append(f"    scene_{safe}_stream_last_scr2_ty = 0xFFFFu;\n")
    if has_dungeongen:
        # DungeonGen scene: skip pre-built tilemap blit; dungeongen owns the SCR1 content.
        lines.append("#if defined(NGPNG_HAS_DUNGEONGEN) && (NGPNG_HAS_DUNGEONGEN)\n")
        lines.append("    /* DungeonGen: autorun owns room generation; scene enter only loads procgen assets. */\n")
        lines.append("    ngpc_dungeongen_init();\n")
        lines.append("#else\n")
        lines.append(f"    scene_{safe}_blit_tilemaps();\n")
        lines.append("#endif\n")
    else:
        lines.append(f"    scene_{safe}_blit_tilemaps();\n")
    lines.append(f"    scene_{safe}_load_sprites();\n")
    _lbl_count = len([l for l in (scene.get("text_labels") or []) if isinstance(l, dict)])
    if _lbl_count > 0:
        U = safe.upper()
        lines.append(f"#if defined({U}_TEXT_LABEL_COUNT) && ({U}_TEXT_LABEL_COUNT > 0)\n")
        lines.append("    { u8 _i; for (_i = 0; _i < (u8)" + U + "_TEXT_LABEL_COUNT; _i++)\n")
        lines.append(f"        ngpc_text_print(g_{safe}_text_label_plane[_i], g_{safe}_text_label_pal[_i],\n")
        lines.append(f"                        g_{safe}_text_label_x[_i], g_{safe}_text_label_y[_i],\n")
        lines.append(f"                        g_{safe}_text_labels[_i]); }}\n")
        lines.append("#endif\n")
    lines.append("}\n\n")

    # ---- Entity preview draw helpers --------------------------------
    # SPR_MIDDLE = between planes. Use it only when SCR2 is the front plane so
    # sprites sit between SCR1 (back, game map) and SCR2 (front).
    # When SCR1 is the front plane (the common topdown/platformer case), sprites
    # must use SPR_FRONT or they end up hidden behind the map.
    # Dialog priority switching is handled separately by g_ngpng_entity_prio in
    # the template integration — not here.
    _bg_front_raw = (
        str(scene.get("level_bg_front") or "")
        or str((scene.get("level_layers") or {}).get("bg_front") or "")
        or "scr1"
    ).strip().lower()
    _spr_draw_prio = "SPR_MIDDLE" if _bg_front_raw == "scr2" else "SPR_FRONT"

    lines.append(f"static u8 scene_{safe}_draw_entity_anim(u8 spr_start, u8 type, u8 anim_frame, s16 sx, s16 sy)\n{{\n")
    if not ent_draw_types:
        lines.append("    (void)spr_start; (void)type; (void)anim_frame; (void)sx; (void)sy;\n")
        lines.append("    return 0;\n")
    else:
        lines.append("    const MsprAnimFrame *anim = 0;\n")
        lines.append("    const MsprAnimFrame *anim_l1 = 0;\n")
        lines.append("    u8 count = 0;\n")
        lines.append("    u8 frame_idx = 0;\n")
        lines.append("    u8 used = 0;\n")
        for i, t in enumerate(ent_draw_types):
            cid = _name_to_c_id(t)
            prefix = "if" if i == 0 else "else if"
            lines.append(f"    {prefix} (type == (u8){_type_to_c_const_scoped(safe, t)}) {{\n")
            lines.append(f"        anim = {cid}_anim;\n")
            lines.append(f"        count = {cid}_anim_count;\n")
            if t in layer1_draw_types:
                lines.append(f"        anim_l1 = {cid}_layer1_anim;\n")
            lines.append("    }\n")
        lines.append("    if (!anim || count == 0u) return 0;\n")
        lines.append("    frame_idx = (u8)(anim_frame % count);\n")
        lines.append(f"    used = ngpc_mspr_draw(spr_start, sx, sy, anim[frame_idx].frame, (u8){_spr_draw_prio});\n")
        lines.append("    if (anim_l1) {\n")
        lines.append(f"        used = (u8)(used + ngpc_mspr_draw((u8)(spr_start + used), sx, sy, anim_l1[frame_idx].frame, (u8){_spr_draw_prio}));\n")
        lines.append("    }\n")
        lines.append("    return (u8)(spr_start + used);\n")
    lines.append("}\n\n")

    lines.append(f"static const NgpcMetasprite *scene_{safe}_resolve_entity_frame(u8 type, u8 anim_frame)\n{{\n")
    if not ent_draw_types:
        lines.append("    (void)type; (void)anim_frame;\n")
        lines.append("    return 0;\n")
    else:
        lines.append("    const MsprAnimFrame *anim = 0;\n")
        lines.append("    u8 count = 0;\n")
        lines.append("    u8 frame_idx = 0;\n")
        for i, t in enumerate(ent_draw_types):
            cid = _name_to_c_id(t)
            prefix = "if" if i == 0 else "else if"
            lines.append(f"    {prefix} (type == (u8){_type_to_c_const_scoped(safe, t)}) {{\n")
            lines.append(f"        anim = {cid}_anim;\n")
            lines.append(f"        count = {cid}_anim_count;\n")
            lines.append("    }\n")
        lines.append("    if (!anim || count == 0u) return 0;\n")
        lines.append("    frame_idx = (u8)(anim_frame % count);\n")
        lines.append("    return anim[frame_idx].frame;\n")
    lines.append("}\n\n")

    lines.append(f"static u8 scene_{safe}_draw_entity_screen(u8 spr_start, u8 type, s16 sx, s16 sy)\n{{\n")
    lines.append(f"    return scene_{safe}_draw_entity_anim(spr_start, type, 0u, sx, sy);\n")
    lines.append("}\n\n")

    lines.append(f"static u8 scene_{safe}_draw_entities_cam(u8 spr_start, s16 cam_px, s16 cam_py)\n{{\n")
    if not ent_draw_types:
        lines.append("    (void)spr_start; (void)cam_px; (void)cam_py;\n")
        lines.append("    return 0;\n")
    else:
        U = safe.upper()
        lines.append(f"#if defined({U}_ENTITY_COUNT) && ({U}_ENTITY_COUNT > 0)\n")
        lines.append("    u8 spr = spr_start;\n")
        lines.append("    u8 used = 0;\n")
        lines.append("    u8 i;\n")
        lines.append("    const NgpngEnt *e;\n")
        lines.append(f"    for (i = 0; i < (u8){U}_ENTITY_COUNT; ++i) {{\n")
        lines.append(f"        e = &g_{safe}_entities[i];\n")
        lines.append("        if (spr >= 64u) break;\n")
        lines.append("        used = scene_" + safe + "_draw_entity_screen(spr, e->type, (s16)((s16)e->x * 8 - cam_px), (s16)((s16)e->y * 8 - cam_py));\n")
        lines.append("        spr = (u8)(spr + used);\n")
        lines.append("    }\n")
        lines.append("    return (u8)(spr - spr_start);\n")
        lines.append("#else\n")
        lines.append("    (void)spr_start; (void)cam_px; (void)cam_py;\n")
        lines.append("    return 0;\n")
        lines.append("#endif\n")
    lines.append("}\n\n")

    lines.append(f"static u8 scene_{safe}_draw_entities(u8 spr_start)\n{{\n")
    lines.append(f"    return scene_{safe}_draw_entities_cam(spr_start, (s16)({safe.upper()}_CAM_TILE_X * 8), (s16)({safe.upper()}_CAM_TILE_Y * 8));\n")
    lines.append("}\n\n")

    # ---- Optional audio helpers (Sound Creator project export) -------
    lines.append("/* Optional audio helpers\n")
    lines.append("   - Requires the template sound driver (Sounds_Init/Sounds_Update/Bgm_FadeOut)\n")
    lines.append("   - If you use Sound Creator Project Export All, also compile/link project_audio_api.c\n")
    lines.append("*/\n")
    lines.append("#if defined(NGP_ENABLE_SOUND) && (NGP_ENABLE_SOUND)\n")
    lines.append("void Sounds_Init(void);\n")
    lines.append("void Sounds_Update(void);\n")
    lines.append("void Bgm_FadeOut(u8 speed);\n")
    lines.append("void NgpcProject_BgmStartLoop4ByIndex(u8 idx);\n")
    lines.append("#endif\n\n")

    lines.append(f"static void scene_{safe}_audio_enter(void)\n{{\n")
    lines.append("#if defined(NGP_ENABLE_SOUND) && (NGP_ENABLE_SOUND)\n")
    lines.append(f"    if ({safe.upper()}_BGM_AUTOSTART) {{\n")
    lines.append(f"        s16 bgm_idx = (s16){safe.upper()}_BGM_INDEX;\n")
    lines.append(f"        if ({safe.upper()}_BGM_COUNT > 0 && {safe.upper()}_BGM_AUTOSTART_SLOT >= 0) {{\n")
    lines.append(f"            bgm_idx = (s16){safe.upper()}_BGM_LIST[{safe.upper()}_BGM_AUTOSTART_SLOT];\n")
    lines.append("        }\n")
    lines.append("        if (bgm_idx >= 0) {\n")
    lines.append("            NgpcProject_BgmStartLoop4ByIndex((u8)bgm_idx);\n")
    lines.append("        }\n")
    lines.append("    }\n")
    lines.append("#endif\n")
    lines.append("}\n\n")

    lines.append(f"static void scene_{safe}_audio_exit(void)\n{{\n")
    lines.append("#if defined(NGP_ENABLE_SOUND) && (NGP_ENABLE_SOUND)\n")
    lines.append(f"    if ({safe.upper()}_BGM_FADE_OUT > 0) {{\n")
    lines.append(f"        Bgm_FadeOut((u8){safe.upper()}_BGM_FADE_OUT);\n")
    lines.append("    }\n")
    lines.append("#endif\n")
    lines.append("}\n\n")

    lines.append(f"static void scene_{safe}_audio_update(void)\n{{\n")
    lines.append("#if defined(NGP_ENABLE_SOUND) && (NGP_ENABLE_SOUND)\n")
    lines.append("    Sounds_Update();\n")
    lines.append("#endif\n")
    lines.append("}\n\n")

    lines.append(f"static void scene_{safe}_enter(void)\n{{\n")
    lines.append(f"    scene_{safe}_load_all();\n")
    lines.append(f"    scene_{safe}_audio_enter();\n")
    lines.append("}\n\n")

    lines.append(f"static void scene_{safe}_exit(void)\n{{\n")
    lines.append(f"    scene_{safe}_audio_exit();\n")
    lines.append("}\n\n")

    lines.append(f"static void scene_{safe}_update(void)\n{{\n")
    lines.append(f"    scene_{safe}_audio_update();\n")
    lines.append("}\n\n")

    lines.append(f"#endif /* {guard} */\n")

    scene_out_h.write_text("".join(lines), encoding="utf-8")
    return scene_out_h
