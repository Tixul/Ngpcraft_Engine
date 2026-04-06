"""core/project_model.py - Budget helpers for .ngpcraft project data."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import importlib.util
import math
from pathlib import Path
from typing import Any

from PIL import Image
from core.rgb444 import OPAQUE_BLACK

TILE_RESERVED = 32    # 0-31 reserved
TILE_SYSFONT  = 96    # 32-127 system font (BIOS SYSFONTSET)
TILE_MAX      = 512
TILE_USER_START = 128  # first free tile after sysfont
PAL_MAX_SPR   = 16
PAL_MAX_BG    = 16


@dataclass(frozen=True)
class SceneVramStats:
    """Summarized tile/palette allocation for one scene VRAM simulation."""

    tile_used: int
    tile_used_raw: int
    spr_tile_base: int
    spr_tile_end: int
    tm_tile_end: int
    spr_pal_base: int
    spr_pal_used: int
    bg_pal_scr1_used: int
    bg_pal_scr2_used: int
    tile_conflict: bool
    tile_overflow: bool
    is_estimated: bool


@dataclass(frozen=True)
class BgPaletteBankInfo:
    """Summarized palette bank signature for one scene BG on one plane."""

    name: str
    palette_count: int
    bank_signature: tuple[tuple[int, ...], ...]


@dataclass(frozen=True)
class BgPalettePlaneAnalysis:
    """Identical-bank analysis for one BG plane (SCR1 or SCR2)."""

    entries: tuple[BgPaletteBankInfo, ...]
    identical_groups: tuple[tuple[str, ...], ...]
    is_estimated: bool


def sprite_tile_estimate(spr: dict) -> int:
    """Estimate tile slots for one sprite entry."""
    fw = max(spr.get("frame_w", 8), 1)
    fh = max(spr.get("frame_h", 8), 1)
    fc = max(spr.get("frame_count", 1), 1)
    return math.ceil(fw / 8) * math.ceil(fh / 8) * fc


def scene_tile_estimate(scene: dict) -> int:
    """Estimate total sprite tile usage for one scene."""
    return sum(sprite_tile_estimate(s) for s in scene.get("sprites", []))


def scene_pal_estimate(scene: dict) -> int:
    """Estimate palette slots for a scene (1 per sprite, dedup by fixed_palette)."""
    seen: set[str] = set()
    count = 0
    for spr in scene.get("sprites", []):
        fp = spr.get("fixed_palette") or ""
        if fp and fp in seen:
            continue  # shared palette
        count += 1
        if fp:
            seen.add(fp)
    return count


def project_tile_estimate(data: dict) -> int:
    """Estimate total sprite tile usage across all scenes in a project."""
    return sum(scene_tile_estimate(s) for s in data.get("scenes", []))


def project_pal_estimate(data: dict) -> int:
    """Estimate total sprite palette usage across all scenes in a project."""
    return sum(scene_pal_estimate(s) for s in data.get("scenes", []))


def _resolve_project_file(base_dir: Path | None, rel_or_abs: str) -> Path | None:
    if not rel_or_abs:
        return None
    p = Path(rel_or_abs)
    if p.is_absolute():
        return p
    if base_dir is None:
        return None
    return base_dir / p


# Pipeline tool paths registered by the UI layer (via set_pipeline_tool_paths).
# These take priority over the project-local tools/ lookup.
_TILEMAP_TOOL_PATH: Path | None = None
_SPRITE_TOOL_PATH: Path | None = None


def set_pipeline_tool_paths(
    tilemap: "Path | None" = None,
    sprite: "Path | None" = None,
) -> None:
    """Register pipeline tool paths found by the UI (QSettings/find_script).
    Clears stats caches so next build_scene_vram_usage uses the new tools.
    """
    global _TILEMAP_TOOL_PATH, _SPRITE_TOOL_PATH
    if tilemap is not None:
        _TILEMAP_TOOL_PATH = tilemap
    if sprite is not None:
        _SPRITE_TOOL_PATH = sprite
    _TM_STATS_CACHE.clear()
    _SPR_STATS_CACHE.clear()


def _resolve_tool_path(override: "Path | None", base_dir: "Path | None", filename: str) -> Path:
    """Return the best path for a pipeline tool: registered override first, then project-local."""
    if override and override.exists():
        return override
    return (base_dir / "tools" / filename) if base_dir else Path("")


_TOOL_CACHE: dict[str, Any] = {}


def _import_tool(path: Path) -> Any | None:
    key = str(path)
    if key in _TOOL_CACHE:
        return _TOOL_CACHE[key]
    if not path.exists() or not path.is_file():
        _TOOL_CACHE[key] = None
        return None
    try:
        spec = importlib.util.spec_from_file_location(f"_tool_{path.stem}", str(path))
        if spec is None or spec.loader is None:
            _TOOL_CACHE[key] = None
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _TOOL_CACHE[key] = mod
        return mod
    except Exception:
        _TOOL_CACHE[key] = None
        return None


_SPR_STATS_CACHE: dict[tuple[str, int, int, int | None, str], tuple[int, int, bool]] = {}


def _sprite_export_stats(
    tool_mod: Any | None,
    img_path: Path,
    frame_w: int,
    frame_h: int,
    frame_count: int | None,
    fixed_palette: str,
) -> tuple[int, int, bool]:
    """
    Returns (unique_tiles, palette_count, estimated?).

    Uses ngpc_sprite_export.py when available to match the real exporter
    (palette assignment affects 2bpp words, and thus tile dedupe).
    """
    key = (str(img_path), int(frame_w), int(frame_h), frame_count if frame_count is None else int(frame_count), fixed_palette or "")
    if key in _SPR_STATS_CACHE:
        return _SPR_STATS_CACHE[key]

    if tool_mod is None:
        out = (sprite_tile_estimate({"frame_w": frame_w, "frame_h": frame_h, "frame_count": frame_count or 1}), 1, True)
        _SPR_STATS_CACHE[key] = out
        return out

    try:
        fw = max(int(frame_w), 8)
        fh = max(int(frame_h), 8)
        fc = None if frame_count is None else max(int(frame_count), 1)
        _fx, _fy, tile_colors, tile_sets, _tile_meta = tool_mod.read_frame_tiles(str(img_path), fw, fh, fc)

        if fixed_palette:
            pal_count = 1
            # fixed palette implies a single palette in exporter; still allow dedupe via indices.
            parts = [s.strip() for s in str(fixed_palette).split(",") if s.strip()]
            if len(parts) != 4:
                raise ValueError("fixed_palette must have 4 entries")
            fixed: list[int] = []
            for s in parts:
                ss = s.lower()
                if ss.startswith("0x"):
                    ss = ss[2:]
                fixed.append(int(ss, 16))
            palette_colors = [fixed]
            idx_map: dict[int, int] = {}
            for i, c in enumerate(fixed):
                if c not in idx_map:
                    idx_map[c] = i
            palette_idx_maps = [idx_map]
            tile_pal_ids = [0 for _ in tile_colors]
        else:
            palettes, tile_pal_ids = tool_mod.assign_palettes(tile_sets, PAL_MAX_SPR)
            palette_colors, palette_idx_maps = tool_mod.build_palette_index_maps(palettes, tile_colors, tile_pal_ids)
            pal_count = len(palette_colors)

        unique_tiles: list[tuple[int, ...]] = []
        tile_to_index: dict[tuple[int, ...], int] = {}
        for colors, pal_id in zip(tile_colors, tile_pal_ids):
            idx_map = palette_idx_maps[pal_id]
            indices = [idx_map[c] for c in colors]
            words = tool_mod.tile_words_from_indices(indices)
            tile_idx = tile_to_index.get(words, -1)
            if tile_idx < 0:
                tile_idx = len(unique_tiles)
                unique_tiles.append(words)
                tile_to_index[words] = tile_idx
        out = (len(unique_tiles), pal_count, False)
    except Exception:
        out = (sprite_tile_estimate({"frame_w": frame_w, "frame_h": frame_h, "frame_count": frame_count or 1}), 1, True)

    _SPR_STATS_CACHE[key] = out
    return out


def sprite_export_stats(
    base_dir: Path | None,
    img_path: Path,
    frame_w: int,
    frame_h: int,
    frame_count: int | None,
    fixed_palette: str = "",
) -> tuple[int, int, bool]:
    """
    Returns (unique_tiles, palette_count, estimated?).

    Uses the project's `tools/ngpc_sprite_export.py` when available (to match real
    exporter dedupe and palette behavior). Falls back to naive estimates when the
    tool cannot be imported.
    """
    tool_mod = _import_tool((base_dir / "tools" / "ngpc_sprite_export.py") if base_dir else Path(""))
    return _sprite_export_stats(tool_mod, img_path, frame_w, frame_h, frame_count, fixed_palette or "")


_TM_STATS_CACHE: dict[tuple[str, str], tuple[int, int, int, bool]] = {}
_TM_PAL_SIG_CACHE: dict[
    tuple[str, str],
    tuple[tuple[tuple[int, ...], ...], tuple[tuple[int, ...], ...], bool],
] = {}


def _rgba_to_rgb444(px: tuple[int, int, int, int], black_is_transparent: bool = False) -> int:
    r, g, b, a = px
    if a < 128:
        return 0
    rgb444 = ((r >> 4) & 0xF) | (((g >> 4) & 0xF) << 4) | (((b >> 4) & 0xF) << 8)
    if black_is_transparent and rgb444 == 0:
        return 0
    if rgb444 == 0:
        return OPAQUE_BLACK
    return rgb444


def _fallback_extract_tiles(
    path: Path,
    *,
    strict: bool,
    black_is_transparent: bool = False,
) -> tuple[int, int, list[tuple[int, ...]], list[frozenset[int]]]:
    img = Image.open(path).convert("RGBA")
    w, h = img.size
    if (w % 8) or (h % 8):
        pw = ((w + 7) // 8) * 8
        ph = ((h + 7) // 8) * 8
        padded = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        padded.paste(img, (0, 0))
        img = padded
        w, h = pw, ph

    px = img.load()
    tw = w // 8
    th = h // 8
    tiles: list[tuple[int, ...]] = []
    tile_sets: list[frozenset[int]] = []

    for ty in range(th):
        for tx in range(tw):
            colors: list[int] = []
            for y in range(8):
                sy = ty * 8 + y
                for x in range(8):
                    sx = tx * 8 + x
                    colors.append(_rgba_to_rgb444(px[sx, sy], black_is_transparent))
            cset = frozenset(colors)
            visible = set(cset)
            visible.discard(0)
            if strict and len(visible) > 3:
                raise ValueError("Tile exceeds 3 visible colors")
            tiles.append(tuple(colors))
            tile_sets.append(cset or frozenset([0]))

    return tw, th, tiles, tile_sets


def _fallback_needs_layer_split(tile_sets: list[frozenset[int]]) -> bool:
    for colors in tile_sets:
        visible = set(colors)
        visible.discard(0)
        if len(visible) > 3:
            return True
    return False


def _fallback_split_layers(
    tiles: list[tuple[int, ...]],
    tile_sets: list[frozenset[int]],
) -> tuple[
    list[tuple[int, ...]], list[frozenset[int]],
    list[tuple[int, ...]], list[frozenset[int]],
    int,
]:
    scr1_tiles: list[tuple[int, ...]] = []
    scr1_sets: list[frozenset[int]] = []
    scr2_tiles: list[tuple[int, ...]] = []
    scr2_sets: list[frozenset[int]] = []
    split_count = 0

    for colors, cset in zip(tiles, tile_sets):
        visible = set(cset)
        visible.discard(0)
        if len(visible) <= 3:
            scr1_tiles.append(colors)
            scr1_sets.append(cset)
            scr2_tiles.append(tuple([0] * 64))
            scr2_sets.append(frozenset([0]))
            continue

        split_count += 1
        freq: Counter[int] = Counter(c for c in colors if c != 0)
        ranked = [c for c, _n in freq.most_common()]
        scr1_colors = set(ranked[:3])
        scr2_colors = set(ranked[3:])

        scr1_px = tuple(c if c in scr1_colors else 0 for c in colors)
        scr2_px = tuple(c if c in scr2_colors else 0 for c in colors)
        scr1_tiles.append(scr1_px)
        scr1_sets.append(frozenset(scr1_px))
        scr2_tiles.append(scr2_px)
        scr2_sets.append(frozenset(scr2_px))

    return scr1_tiles, scr1_sets, scr2_tiles, scr2_sets, split_count


def _fallback_assign_palettes(
    tile_sets: list[frozenset[int]],
    max_palettes: int,
) -> tuple[list[set[int]], list[int]]:
    set_ids: dict[frozenset[int], int] = {}
    unique_sets: list[frozenset[int]] = []
    for colors in tile_sets:
        if colors not in set_ids:
            set_ids[colors] = len(unique_sets)
            unique_sets.append(colors)

    set_freq = Counter(set_ids[s] for s in tile_sets)
    order = sorted(
        range(len(unique_sets)),
        key=lambda sid: (-len(unique_sets[sid]), -set_freq[sid], sid),
    )

    palettes: list[set[int]] = []
    set_to_pal: dict[int, int] = {}

    for sid in order:
        colors = set(unique_sets[sid])

        exact_idx = -1
        best_subset_size = 99
        for i, pal in enumerate(palettes):
            if colors.issubset(pal) and len(pal) < best_subset_size:
                best_subset_size = len(pal)
                exact_idx = i
        if exact_idx >= 0:
            set_to_pal[sid] = exact_idx
            continue

        expand_idx = -1
        expand_cost = 99
        for i, pal in enumerate(palettes):
            union = pal | colors
            visible = len(union - {0})
            if visible <= 3:
                cost = len(union) - len(pal)
                if cost < expand_cost:
                    expand_cost = cost
                    expand_idx = i
        if expand_idx >= 0:
            palettes[expand_idx] |= colors
            set_to_pal[sid] = expand_idx
            continue

        if len(palettes) < max_palettes:
            palettes.append(set(colors))
            set_to_pal[sid] = len(palettes) - 1
            continue

        raise ValueError("Need more palettes")

    tile_pal_ids = [set_to_pal[set_ids[s]] for s in tile_sets]
    return palettes, tile_pal_ids


def _fallback_build_palette_index_maps(
    palettes: list[set[int]],
    tiles: list[tuple[int, ...]],
    tile_pal_ids: list[int],
) -> tuple[list[list[int]], list[dict[int, int]]]:
    pal_freq: dict[int, Counter[int]] = defaultdict(Counter)
    for tile_colors, pal_id in zip(tiles, tile_pal_ids):
        pal_freq[pal_id].update(tile_colors)

    palette_colors: list[list[int]] = []
    palette_idx_maps: list[dict[int, int]] = []

    for pal_id, pal_set in enumerate(palettes):
        colors = sorted(list(pal_set), key=lambda c: (-pal_freq[pal_id][c], c))
        if 0 in colors:
            colors.remove(0)
        colors = [0] + colors
        while len(colors) < 4:
            colors.append(0)
        colors = colors[:4]

        idx_map: dict[int, int] = {}
        for i, color in enumerate(colors):
            if color not in idx_map:
                idx_map[color] = i

        palette_colors.append(colors)
        palette_idx_maps.append(idx_map)

    return palette_colors, palette_idx_maps


def _tm_extract_tiles(
    tool_mod: Any | None,
    path: Path,
    *,
    strict: bool,
) -> tuple[int, int, list[tuple[int, ...]], list[frozenset[int]]]:
    if tool_mod is not None and hasattr(tool_mod, "extract_tiles"):
        return tool_mod.extract_tiles(str(path), strict=bool(strict))
    return _fallback_extract_tiles(path, strict=bool(strict))


def _tm_needs_layer_split(tool_mod: Any | None, tile_sets: list[frozenset[int]]) -> bool:
    if tool_mod is not None and hasattr(tool_mod, "needs_layer_split"):
        return bool(tool_mod.needs_layer_split(tile_sets))
    return _fallback_needs_layer_split(tile_sets)


def _tm_split_layers(
    tool_mod: Any | None,
    tiles: list[tuple[int, ...]],
    tile_sets: list[frozenset[int]],
) -> tuple[
    list[tuple[int, ...]], list[frozenset[int]],
    list[tuple[int, ...]], list[frozenset[int]],
    int,
]:
    if tool_mod is not None and hasattr(tool_mod, "split_layers"):
        return tool_mod.split_layers(tiles, tile_sets)
    return _fallback_split_layers(tiles, tile_sets)


def _tm_assign_palettes(
    tool_mod: Any | None,
    tile_sets: list[frozenset[int]],
    max_palettes: int,
) -> tuple[list[set[int]], list[int]]:
    if tool_mod is not None and hasattr(tool_mod, "assign_palettes"):
        return tool_mod.assign_palettes(tile_sets, int(max_palettes))
    return _fallback_assign_palettes(tile_sets, int(max_palettes))


def _tm_build_palette_index_maps(
    tool_mod: Any | None,
    palettes: list[set[int]],
    tiles: list[tuple[int, ...]],
    tile_pal_ids: list[int],
) -> tuple[list[list[int]], list[dict[int, int]]]:
    if tool_mod is not None and hasattr(tool_mod, "build_palette_index_maps"):
        return tool_mod.build_palette_index_maps(palettes, tiles, tile_pal_ids)
    return _fallback_build_palette_index_maps(palettes, tiles, tile_pal_ids)


def _normalize_palette_signature(colors: list[int]) -> tuple[int, ...]:
    return tuple(sorted({int(c) for c in colors if int(c) not in (0,)}))


def _normalize_palette_bank(palette_colors: list[list[int]]) -> tuple[tuple[int, ...], ...]:
    sigs = [_normalize_palette_signature(colors) for colors in palette_colors]
    sigs = [sig for sig in sigs if sig]
    return tuple(sorted(sigs))


def _ordered_palette_bank(palette_colors: list[list[int]]) -> tuple[tuple[int, ...], ...]:
    sigs = [_normalize_palette_signature(colors) for colors in palette_colors]
    return tuple(sig for sig in sigs if sig)


def _tilemap_palette_bank_signatures(
    tool_mod: Any | None,
    scr1_path: Path,
    scr2_path: Path | None,
    preserve_order: bool = False,
) -> tuple[tuple[tuple[int, ...], ...], tuple[tuple[int, ...], ...], bool]:
    key = (str(scr1_path), str(scr2_path) if scr2_path is not None else "", 1 if preserve_order else 0)
    if key in _TM_PAL_SIG_CACHE:
        return _TM_PAL_SIG_CACHE[key]

    estimated = tool_mod is None
    bank_norm = _ordered_palette_bank if preserve_order else _normalize_palette_bank
    try:
        if scr2_path is not None and scr2_path.exists():
            _tw1, _th1, tiles1, tsets1 = _tm_extract_tiles(tool_mod, scr1_path, strict=False)
            _tw2, _th2, tiles2, tsets2 = _tm_extract_tiles(tool_mod, scr2_path, strict=False)
            pals1, tpids1 = _tm_assign_palettes(tool_mod, tsets1, PAL_MAX_BG)
            pals2, tpids2 = _tm_assign_palettes(tool_mod, tsets2, PAL_MAX_BG)
            pcols1, _pimaps1 = _tm_build_palette_index_maps(tool_mod, pals1, tiles1, tpids1)
            pcols2, _pimaps2 = _tm_build_palette_index_maps(tool_mod, pals2, tiles2, tpids2)
            out = (bank_norm(pcols1), bank_norm(pcols2), estimated)
        else:
            _tw, _th, tiles, tile_sets = _tm_extract_tiles(tool_mod, scr1_path, strict=False)
            if _tm_needs_layer_split(tool_mod, tile_sets):
                s1t, s1s, s2t, s2s, _split_n = _tm_split_layers(tool_mod, tiles, tile_sets)
                pals1, tpids1 = _tm_assign_palettes(tool_mod, s1s, PAL_MAX_BG)
                pals2, tpids2 = _tm_assign_palettes(tool_mod, s2s, PAL_MAX_BG)
                pcols1, _pimaps1 = _tm_build_palette_index_maps(tool_mod, pals1, s1t, tpids1)
                pcols2, _pimaps2 = _tm_build_palette_index_maps(tool_mod, pals2, s2t, tpids2)
                out = (bank_norm(pcols1), bank_norm(pcols2), estimated)
            else:
                pals, tpids = _tm_assign_palettes(tool_mod, tile_sets, PAL_MAX_BG)
                pcols, _pimaps = _tm_build_palette_index_maps(tool_mod, pals, tiles, tpids)
                out = (bank_norm(pcols), tuple(), estimated)
    except Exception:
        out = (tuple(), tuple(), True)

    _TM_PAL_SIG_CACHE[key] = out
    return out


def _tilemap_export_stats(
    tool_mod: Any | None,
    scr1_path: Path,
    scr2_path: Path | None,
) -> tuple[int, int, int, bool]:
    """
    Returns (unique_tiles, pal_scr1, pal_scr2, estimated?).
    Uses ngpc_tilemap.py when available to match export behavior (auto-split + dedupe).
    """
    k2 = str(scr2_path) if scr2_path is not None else ""
    key = (str(scr1_path), k2)
    if key in _TM_STATS_CACHE:
        return _TM_STATS_CACHE[key]

    if tool_mod is None:
        # naive fallback: unique RGBA tiles, no palette info
        try:
            img = Image.open(scr1_path).convert("RGBA")
            w, h = img.size
            if (w % 8) or (h % 8):
                raise ValueError("size not multiple of 8")
            seen: set[bytes] = set()
            for ty in range(h // 8):
                for tx in range(w // 8):
                    tile = img.crop((tx * 8, ty * 8, tx * 8 + 8, ty * 8 + 8))
                    seen.add(tile.tobytes())
            out = (len(seen), 1, 0, True)
        except Exception:
            out = (0, 0, 0, True)
        _TM_STATS_CACHE[key] = out
        return out

    try:
        dedupe = True

        if scr2_path is not None and scr2_path.exists():
            tw1, th1, tiles1, tsets1 = tool_mod.extract_tiles(str(scr1_path))
            tw2, th2, tiles2, tsets2 = tool_mod.extract_tiles(str(scr2_path))
            if tw1 != tw2 or th1 != th2:
                raise ValueError("SCR1/SCR2 size mismatch")

            pals1, tpids1 = tool_mod.assign_palettes(tsets1, PAL_MAX_BG)
            pals2, tpids2 = tool_mod.assign_palettes(tsets2, PAL_MAX_BG)
            pcols1, pimaps1 = tool_mod.build_palette_index_maps(pals1, tiles1, tpids1)
            pcols2, pimaps2 = tool_mod.build_palette_index_maps(pals2, tiles2, tpids2)
            pool, pool_idx, _map_t1, _map_p1 = tool_mod.encode_tiles_and_map(tiles1, tpids1, pimaps1, dedupe)
            pool, _pool_idx, _map_t2, _map_p2 = tool_mod.encode_tiles_and_map(
                tiles2, tpids2, pimaps2, dedupe, tile_pool=pool, tile_pool_index=pool_idx
            )
            out = (len(pool), len(pcols1), len(pcols2), False)
        else:
            _tw, _th, tiles, tile_sets = tool_mod.extract_tiles(str(scr1_path), strict=False)
            if tool_mod.needs_layer_split(tile_sets):
                s1t, s1s, s2t, s2s, _split_n = tool_mod.split_layers(tiles, tile_sets)
                pals1, tpids1 = tool_mod.assign_palettes(s1s, PAL_MAX_BG)
                pals2, tpids2 = tool_mod.assign_palettes(s2s, PAL_MAX_BG)
                pcols1, pimaps1 = tool_mod.build_palette_index_maps(pals1, s1t, tpids1)
                pcols2, pimaps2 = tool_mod.build_palette_index_maps(pals2, s2t, tpids2)
                pool, pool_idx, _map_t1, _map_p1 = tool_mod.encode_tiles_and_map(s1t, tpids1, pimaps1, dedupe)
                pool, _pool_idx, _map_t2, _map_p2 = tool_mod.encode_tiles_and_map(
                    s2t, tpids2, pimaps2, dedupe, tile_pool=pool, tile_pool_index=pool_idx
                )
                out = (len(pool), len(pcols1), len(pcols2), False)
            else:
                pals, tpids = tool_mod.assign_palettes(tile_sets, PAL_MAX_BG)
                pcols, pimaps = tool_mod.build_palette_index_maps(pals, tiles, tpids)
                pool, _pool_idx, _map_t, _map_p = tool_mod.encode_tiles_and_map(tiles, tpids, pimaps, dedupe)
                out = (len(pool), len(pcols), 0, False)
    except Exception:
        out = (0, 0, 0, True)

    _TM_STATS_CACHE[key] = out
    return out


def analyze_scene_bg_palette_banks(
    scene: dict,
    base_dir: Path | None,
) -> dict[str, BgPalettePlaneAnalysis]:
    """Detect identical BG palette banks between tilemaps on SCR1 and SCR2."""
    return _analyze_scene_bg_palette_banks(scene, base_dir, preserve_order=False)


def analyze_scene_bg_palette_banks_exact(
    scene: dict,
    base_dir: Path | None,
) -> dict[str, BgPalettePlaneAnalysis]:
    """Detect exact-order identical BG palette banks between tilemaps on SCR1 and SCR2."""
    return _analyze_scene_bg_palette_banks(scene, base_dir, preserve_order=True)


def _analyze_scene_bg_palette_banks(
    scene: dict,
    base_dir: Path | None,
    *,
    preserve_order: bool,
) -> dict[str, BgPalettePlaneAnalysis]:
    """Internal shared BG palette bank analysis with optional palette-order sensitivity."""
    tilemap_tool = _import_tool(_resolve_tool_path(_TILEMAP_TOOL_PATH, base_dir, "ngpc_tilemap.py"))
    plane_entries: dict[str, list[BgPaletteBankInfo]] = {"scr1": [], "scr2": []}
    estimated = False

    for tm in scene.get("tilemaps", []) or []:
        if not isinstance(tm, dict):
            continue
        rel = str(tm.get("file") or "").strip()
        p = _resolve_project_file(base_dir, rel)
        if p is None or not p.exists():
            estimated = True
            continue

        scr2_guess = None
        if p.stem.lower().endswith("_scr1"):
            scr2_guess = p.with_name(p.stem[:-5] + "_scr2" + p.suffix)
            if not scr2_guess.exists():
                scr2_guess = None

        sig1, sig2, est = _tilemap_palette_bank_signatures(
            tilemap_tool,
            p,
            scr2_guess,
            preserve_order=preserve_order,
        )
        estimated = estimated or est

        label = str(tm.get("name") or "").strip()
        if not label:
            label = p.stem[:-5] if p.stem.lower().endswith("_scr1") else p.stem

        if sig2:
            if sig1:
                plane_entries["scr1"].append(BgPaletteBankInfo(label, len(sig1), sig1))
            if sig2:
                plane_entries["scr2"].append(BgPaletteBankInfo(label, len(sig2), sig2))
            continue

        plane = str(tm.get("plane", "auto") or "auto").strip().lower()
        target_plane = "scr2" if plane == "scr2" else "scr1"
        if sig1:
            plane_entries[target_plane].append(BgPaletteBankInfo(label, len(sig1), sig1))

    result: dict[str, BgPalettePlaneAnalysis] = {}
    for plane in ("scr1", "scr2"):
        entries = tuple(plane_entries[plane])
        by_signature: dict[tuple[tuple[int, ...], ...], list[str]] = {}
        for entry in entries:
            by_signature.setdefault(entry.bank_signature, []).append(entry.name)
        identical_groups = tuple(
            tuple(sorted(names))
            for signature, names in sorted(by_signature.items(), key=lambda item: item[1])
            if signature and len(names) >= 2
        )
        result[plane] = BgPalettePlaneAnalysis(
            entries=entries,
            identical_groups=identical_groups,
            is_estimated=estimated,
        )

    return result


def build_scene_vram_usage(
    project_data: dict,
    scene: dict,
    base_dir: Path | None,
) -> tuple[list[tuple[int, int, int] | None], list[str | None], SceneVramStats]:
    """
    Build tile slot usage + tooltips for a single scene.

    Note: sprites and tilemaps share the same 512-tile VRAM. Tilemaps default to base 128,
    sprites use `scene.spr_tile_base` when set, otherwise the project bundle tile_base (or 256).
    """
    usage: list[tuple[int, int, int] | None] = [None] * TILE_MAX
    names: list[str | None] = [None] * TILE_MAX

    bundle_cfg = ((project_data.get("bundle") or {}) or {}) if isinstance(project_data, dict) else {}
    try:
        sprite_base = int(scene.get("spr_tile_base", bundle_cfg.get("tile_base", 256)))
    except Exception:
        sprite_base = int(bundle_cfg.get("tile_base", 256) or 256)
    try:
        spr_pal_base = int(scene.get("spr_pal_base", bundle_cfg.get("pal_base", 0)))
    except Exception:
        spr_pal_base = int(bundle_cfg.get("pal_base", 0) or 0)
    tilemap_base_default = int(((project_data.get("tilemap") or {}) or {}).get("tile_base", TILE_USER_START))

    sprite_tool = _import_tool(_resolve_tool_path(_SPRITE_TOOL_PATH, base_dir, "ngpc_sprite_export.py"))
    tilemap_tool = _import_tool(_resolve_tool_path(_TILEMAP_TOOL_PATH, base_dir, "ngpc_tilemap.py"))

    tm_cursor = tilemap_base_default
    spr_cursor = sprite_base
    tm_max_end = tm_cursor
    tile_used_raw = 0
    tile_used = 0
    spr_pal_cursor = spr_pal_base
    bg_pal_1 = 0
    bg_pal_2 = 0
    estimated = False
    had_conflict = False
    had_overflow = False

    def _alloc(slot: int, color: tuple[int, int, int], label: str) -> None:
        nonlocal estimated, had_conflict, had_overflow
        if not (0 <= slot < TILE_MAX):
            had_overflow = True
            return
        if usage[slot] is not None and names[slot] is not None:
            usage[slot] = (244, 71, 71)  # conflict (red)
            names[slot] = f"CONFLICT: {names[slot]}  +  {label}"
            had_conflict = True
            return
        usage[slot] = color
        names[slot] = label

    # Tilemaps first (BG)
    # Avoid strong reds here: red is reserved for conflicts in the VRAM map.
    tm_colors = [
        (78, 201, 176),   # teal
        (181, 206, 168),  # desat green
        (156, 220, 254),  # light cyan
        (150, 150, 255),  # lavender
        (220, 220, 170),  # sand
        (197, 134, 192),  # purple
        (79, 193, 255),   # sky blue
        (120, 200, 80),   # green
    ]
    for idx, tm in enumerate(scene.get("tilemaps", []) or []):
        rel = (tm.get("file") or "").strip()
        p = _resolve_project_file(base_dir, rel)
        if p is None or not p.exists():
            estimated = True
            continue

        scr2_guess = None
        if p.stem.lower().endswith("_scr1"):
            scr2_guess = p.with_name(p.stem[:-5] + "_scr2" + p.suffix)
            if not scr2_guess.exists():
                scr2_guess = None

        uniq, pal1, pal2, est = _tilemap_export_stats(tilemap_tool, p, scr2_guess)
        estimated = estimated or est
        # Palette budgets: SCR1 and SCR2 are separate BG palette banks on NGPC.
        # If the export uses both planes (pal2>0), count into both. Otherwise, allow
        # a per-tilemap "plane" metadata to decide whether this single-layer BG is
        # intended for SCR1 or SCR2.
        if int(pal2) > 0:
            bg_pal_1 += int(pal1)
            bg_pal_2 += int(pal2)
        else:
            plane = tm.get("plane", "auto") if isinstance(tm, dict) else "auto"
            if plane == "scr2":
                bg_pal_2 += int(pal1)
            else:
                bg_pal_1 += int(pal1)

        tile_base = tm.get("tile_base")
        try:
            tile_base_i = int(tile_base) if tile_base is not None else tm_cursor
        except Exception:
            tile_base_i = tm_cursor
        tm_cursor = tile_base_i + int(uniq)
        tm_max_end = max(int(tm_max_end), int(tile_base_i) + int(uniq))

        label = tm.get("name") or p.name
        color = tm_colors[idx % len(tm_colors)]
        for i in range(int(uniq)):
            _alloc(tile_base_i + i, color, f"TM {label}  slots {tile_base_i}..{tile_base_i + int(uniq) - 1}")

        tile_used += int(uniq)
        # raw count: tilemap size in tiles (no dedupe)
        try:
            img = Image.open(p).convert("RGBA")
            tile_used_raw += (img.width // 8) * (img.height // 8)
        except Exception:
            estimated = True

    # Sprites
    # Avoid strong reds here: red is reserved for conflicts in the VRAM map.
    spr_colors = [
        (86, 156, 214),   # blue
        (78, 201, 176),   # teal
        (255, 215, 0),    # gold
        (197, 134, 192),  # purple
        (79, 193, 255),   # sky blue
        (220, 220, 170),  # sand
        (150, 150, 255),  # lavender
        (120, 200, 80),   # green
    ]
    fixed_to_pal_slot: dict[str, int] = {}  # fixed_palette string → first assigned cursor value
    for idx, spr in enumerate(scene.get("sprites", []) or []):
        rel = (spr.get("file") or "").strip()
        p = _resolve_project_file(base_dir, rel)
        fw = int(spr.get("frame_w", 8) or 8)
        fh = int(spr.get("frame_h", 8) or 8)
        fc = int(spr.get("frame_count", 1) or 1)
        fc_use = None if fc <= 0 else fc
        fixed = str(spr.get("fixed_palette") or "").strip()

        raw = sprite_tile_estimate({"frame_w": fw, "frame_h": fh, "frame_count": fc_use or 1})
        tile_used_raw += raw

        if p is None or not p.exists():
            uniq, pal_n, est = raw, 1, True
        else:
            uniq, pal_n, est = _sprite_export_stats(sprite_tool, p, fw, fh, fc_use, fixed)
        estimated = estimated or est

        color = spr_colors[idx % len(spr_colors)]
        name = spr.get("name") or p.name if p is not None else rel or "?"
        for i in range(int(uniq)):
            _alloc(spr_cursor + i, color, f"SPR {name}  slots {spr_cursor}..{spr_cursor + int(uniq) - 1}")
        spr_cursor += int(uniq)
        tile_used += int(uniq)

        if bool(fixed) and int(pal_n) == 1:
            if fixed in fixed_to_pal_slot:
                # Reuse existing slot for identical fixed_palette (even if non-consecutive).
                pass
            else:
                fixed_to_pal_slot[fixed] = spr_pal_cursor
                spr_pal_cursor += int(pal_n)
        else:
            spr_pal_cursor += int(pal_n)

    stats = SceneVramStats(
        tile_used=tile_used,
        tile_used_raw=tile_used_raw,
        spr_tile_base=int(sprite_base),
        spr_tile_end=int(spr_cursor),
        tm_tile_end=int(tm_max_end),
        spr_pal_base=spr_pal_base,
        spr_pal_used=max(0, int(spr_pal_cursor - spr_pal_base)),
        bg_pal_scr1_used=bg_pal_1,
        bg_pal_scr2_used=bg_pal_2,
        tile_conflict=had_conflict,
        tile_overflow=had_overflow,
        is_estimated=estimated,
    )
    return usage, names, stats


def build_vram_usage(data: dict) -> list[tuple[int, int, int] | None]:
    """
    Build a 512-entry color list representing tile slot usage.
    Reserved (0-31): dark grey. Sysfont (32-127): medium grey.
    Each sprite gets a distinct hue starting at TILE_USER_START.
    Returns list of (R,G,B) or None for empty slots.
    """
    usage: list[tuple[int, int, int] | None] = [None] * TILE_MAX

    # palette of distinct hues for sprites
    # Avoid strong reds here: red is reserved for conflicts in the VRAM map.
    hues = [
        (86, 156, 214),   # blue
        (78, 201, 176),   # teal
        (220, 220, 170),  # sand
        (156, 220, 254),  # light cyan
        (181, 206, 168),  # desat green
        (197, 134, 192),  # purple
        (79, 193, 255),   # sky blue
        (150, 150, 255),  # lavender
        (255, 215, 0),    # gold
        (120, 200, 80),   # green
        (120, 160, 220),  # steel blue
        (180, 180, 210),  # pale lilac
    ]
    hue_idx = 0
    cursor = TILE_USER_START

    for scene in data.get("scenes", []):
        for spr in scene.get("sprites", []):
            n = sprite_tile_estimate(spr)
            color = hues[hue_idx % len(hues)]
            hue_idx += 1
            for i in range(n):
                slot = cursor + i
                if slot < TILE_MAX:
                    usage[slot] = color
            cursor += n

    return usage


def build_vram_names(data: dict) -> list[str | None]:
    """
    Build a 512-entry name list for tile slot tooltips.
    Returns sprite name (with scene) for each occupied slot, None otherwise.
    """
    names: list[str | None] = [None] * TILE_MAX
    cursor = TILE_USER_START

    for scene in data.get("scenes", []):
        scene_label = scene.get("label", "?")
        for spr in scene.get("sprites", []):
            n = sprite_tile_estimate(spr)
            spr_name = spr.get("name") or spr.get("file", "?")
            label = f"{spr_name}  [{scene_label}]  slots {cursor}..{cursor + n - 1}"
            for i in range(n):
                slot = cursor + i
                if slot < TILE_MAX:
                    names[slot] = label
            cursor += n

    return names
