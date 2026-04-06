#!/usr/bin/env python3
"""
ngpc_tilemap.py - PNG to NGPC tileset/tilemap converter

Converts one or two PNG images into:
- NGPC 2bpp tile words (u16, 8 words per tile)
- tilemap tile indices (per layer)
- tilemap palette indices (per layer)
- NGPC RGB444 palettes (up to 16 palettes x 4 colors per layer)

Output is a C source file compatible with the NgpCraft_base_template.

Template palette policy:
- Index 0 is reserved for transparency.
- Per 8x8 tile: max 3 visible colors (+ transparent index 0).

Single-layer mode (default):
    python tools/ngpc_tilemap.py input.png -o GraphX/level1_bg.c -n level1_bg --header

Dual-layer mode (SCR1 + SCR2):
    python tools/ngpc_tilemap.py scr1.png --scr2 scr2.png -o GraphX/level1.c -n level1 --header

    Tiles are globally deduplicated across both layers (shared 512-tile VRAM).
    Each layer gets independent palettes (16 per layer max).
    NGPC render order: BG color -> SCR2 (back) -> SCR1 (front) -> Sprites.

Requirements:
    Pillow (PIL)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter, defaultdict

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    print("Error: Pillow is required. Install with: pip install pillow", file=sys.stderr)
    raise SystemExit(2)

NGPC_MAX_TILES = 512
NGPC_MAP_W = 32
NGPC_MAP_H = 32
OPAQUE_BLACK = 0x1000  # internal sentinel to distinguish from transparent 0


def sanitize_c_identifier(name: str) -> str:
    name = re.sub(r"[^0-9A-Za-z_]", "_", name)
    if not name:
        name = "asset"
    if name[0].isdigit():
        name = "asset_" + name
    return name


def rgba_to_rgb444(px: tuple[int, int, int, int], black_is_transparent: bool = False) -> int:
    r, g, b, a = px
    if a < 128:
        return 0
    rgb444 = ((r >> 4) & 0xF) | (((g >> 4) & 0xF) << 4) | (((b >> 4) & 0xF) << 8)
    if black_is_transparent and rgb444 == 0:
        return 0
    if rgb444 == 0:
        return OPAQUE_BLACK
    return rgb444


def tile_words_from_indices(tile_indices: list[int]) -> tuple[int, ...]:
    words: list[int] = []
    for row in range(8):
        w = 0
        base = row * 8
        for col in range(8):
            idx = tile_indices[base + col] & 0x03
            w |= idx << (14 - col * 2)
        words.append(w)
    return tuple(words)


def extract_tiles(
    path: str,
    black_is_transparent: bool = False,
    strict: bool = True,
) -> tuple[int, int, list[tuple[int, ...]], list[frozenset[int]]]:
    img = Image.open(path).convert("RGBA")
    w, h = img.size
    if (w % 8) or (h % 8):
        pw = ((w + 7) // 8) * 8
        ph = ((h + 7) // 8) * 8
        print(
            f"Warning: {path} size {w}x{h} is not a multiple of 8 — "
            f"auto-padding to {pw}x{ph} with transparent pixels.",
            file=sys.stderr,
        )
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
                    colors.append(rgba_to_rgb444(px[sx, sy], black_is_transparent))
            cset = frozenset(colors)
            visible = set(cset)
            if 0 in visible:
                visible.remove(0)
            if strict and len(visible) > 3:
                raise ValueError(
                    "Tile (%d,%d) uses %d visible colors (>3). "
                    "Template pipeline reserves index 0 for transparency."
                    % (tx, ty, len(visible))
                )
            if len(cset) == 0:
                cset = frozenset([0])
            tiles.append(tuple(colors))
            tile_sets.append(cset)

    return tw, th, tiles, tile_sets


def needs_layer_split(tile_sets: list[frozenset[int]]) -> bool:
    """Return True if any tile has more than 3 visible colors."""
    for s in tile_sets:
        visible = set(s)
        visible.discard(0)
        if len(visible) > 3:
            return True
    return False


def split_layers(
    tiles: list[tuple[int, ...]],
    tile_sets: list[frozenset[int]],
) -> tuple[
    list[tuple[int, ...]], list[frozenset[int]],
    list[tuple[int, ...]], list[frozenset[int]],
    int,
]:
    """Split tiles into SCR1 (front) and SCR2 (back) layers.

    Tiles with <=3 visible colors go entirely to SCR1 (SCR2 = transparent).
    Tiles with >3 visible colors: top 3 most frequent -> SCR1, rest -> SCR2.
    At runtime SCR1 transparent pixels let SCR2 show through.

    Returns (scr1_tiles, scr1_sets, scr2_tiles, scr2_sets, split_count).
    """
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
        else:
            split_count += 1
            freq: Counter[int] = Counter(c for c in colors if c != 0)
            ranked = [c for c, _ in freq.most_common()]
            scr1_colors = set(ranked[:3])
            scr2_colors = set(ranked[3:])

            scr1_px = tuple(c if c in scr1_colors else 0 for c in colors)
            scr2_px = tuple(c if c in scr2_colors else 0 for c in colors)

            scr1_tiles.append(scr1_px)
            scr1_sets.append(frozenset(scr1_px))
            scr2_tiles.append(scr2_px)
            scr2_sets.append(frozenset(scr2_px))

    return scr1_tiles, scr1_sets, scr2_tiles, scr2_sets, split_count


def assign_palettes(
    tile_sets: list[frozenset[int]],
    max_palettes: int,
) -> tuple[list[set[int]], list[int]]:
    set_ids: dict[frozenset[int], int] = {}
    unique_sets: list[frozenset[int]] = []
    for s in tile_sets:
        if s not in set_ids:
            set_ids[s] = len(unique_sets)
            unique_sets.append(s)

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
            if colors.issubset(pal):
                if len(pal) < best_subset_size:
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

        raise ValueError(
            "Need more than %d palettes. Reduce color variety per tile/image."
            % max_palettes
        )

    tile_pal_ids = [set_to_pal[set_ids[s]] for s in tile_sets]
    return palettes, tile_pal_ids


def build_palette_index_maps(
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
        # Template convention: palette index 0 is reserved for transparency.
        colors = [0] + colors
        if len(colors) > 4:
            raise ValueError(
                "Palette %d needs %d entries (>4). Reduce colors."
                % (pal_id, len(colors))
            )
        while len(colors) < 4:
            colors.append(0)
        colors = colors[:4]

        idx_map: dict[int, int] = {}
        for i, c in enumerate(colors):
            if c not in idx_map:
                idx_map[c] = i

        palette_colors.append(colors)
        palette_idx_maps.append(idx_map)

    return palette_colors, palette_idx_maps


def encode_tiles_and_map(
    tiles: list[tuple[int, ...]],
    tile_pal_ids: list[int],
    palette_idx_maps: list[dict[int, int]],
    dedupe: bool,
    tile_pool: list[tuple[int, ...]] | None = None,
    tile_pool_index: dict[tuple[int, ...], int] | None = None,
) -> tuple[list[tuple[int, ...]], dict[tuple[int, ...], int], list[int], list[int]]:
    """Encode tile colors into 2bpp words and build tilemap indices.

    When tile_pool/tile_pool_index are provided, new tiles are appended to
    the existing pool (used for global deduplication across SCR1+SCR2).
    Returns (unique_tiles, tile_to_index, map_tile_ids, map_pal_ids).
    """
    if tile_pool is not None:
        unique_tiles = list(tile_pool)
        tile_to_index = dict(tile_pool_index) if tile_pool_index else {}
    else:
        unique_tiles = []
        tile_to_index = {}
    map_tile_ids: list[int] = []
    map_pal_ids: list[int] = []

    for tile_colors, pal_id in zip(tiles, tile_pal_ids):
        idx_map = palette_idx_maps[pal_id]
        tile_indices = [idx_map[c] for c in tile_colors]
        words = tile_words_from_indices(tile_indices)

        if dedupe:
            idx = tile_to_index.get(words, -1)
            if idx < 0:
                idx = len(unique_tiles)
                tile_to_index[words] = idx
                unique_tiles.append(words)
        else:
            idx = len(unique_tiles)
            unique_tiles.append(words)

        map_tile_ids.append(idx)
        map_pal_ids.append(pal_id)

    return unique_tiles, tile_to_index, map_tile_ids, map_pal_ids


def _fmt_u16_rows(values: list[int], per_line: int = 12) -> list[str]:
    out: list[str] = []
    for i in range(0, len(values), per_line):
        chunk = values[i : i + per_line]
        txt = ", ".join("0x%04X" % v for v in chunk)
        if i + per_line < len(values):
            txt += ","
        out.append("    " + txt)
    return out


def write_tiles_bin(path: str, unique_tiles: list[tuple[int, ...]]) -> None:
    data = bytearray()
    for tile in unique_tiles:
        for w in tile:
            data.append(w & 0xFF)
            data.append((w >> 8) & 0xFF)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _fmt_u8_rows(values: list[int], per_line: int = 24) -> list[str]:
    out: list[str] = []
    for i in range(0, len(values), per_line):
        chunk = values[i : i + per_line]
        txt = ", ".join("0x%02X" % v for v in chunk)
        if i + per_line < len(values):
            txt += ","
        out.append("    " + txt)
    return out


def format_c_source(
    name: str,
    tile_w: int,
    tile_h: int,
    palette_colors: list[list[int]],
    unique_tiles: list[tuple[int, ...]],
    map_tile_ids: list[int],
    map_pal_ids: list[int],
    emit_u8_tiles: bool,
) -> str:
    tile_words: list[int] = [w for t in unique_tiles for w in t]
    tile_bytes: list[int] = []
    for w in tile_words:
        tile_bytes.append(w & 0xFF)
        tile_bytes.append((w >> 8) & 0xFF)
    pal_words: list[int] = [
        (0 if c == OPAQUE_BLACK else c) for pal in palette_colors for c in pal
    ]

    lines: list[str] = []
    lines.append("/* Generated by ngpc_tilemap.py - do not edit */")
    lines.append("")
    lines.append('#include "ngpc_types.h"')
    lines.append("")
    lines.append("/* Image: %dx%d px (%dx%d tiles) */" % (tile_w * 8, tile_h * 8, tile_w, tile_h))
    lines.append("/* Tiles: %d unique (%d words) */" % (len(unique_tiles), len(tile_words)))
    lines.append("/* Palettes: %d */" % len(palette_colors))
    lines.append("")

    lines.append("const u16 %s_map_w = %du;" % (name, tile_w))
    lines.append("const u16 %s_map_h = %du;" % (name, tile_h))
    lines.append("const u16 %s_map_len = %du;" % (name, len(map_tile_ids)))
    lines.append("")

    lines.append("const u8 %s_palette_count = %du;" % (name, len(palette_colors)))
    lines.append("const u16 %s_palettes[] = {" % name)
    lines.extend(_fmt_u16_rows(pal_words))
    lines.append("};")
    lines.append("")

    if emit_u8_tiles:
        lines.append("const u16 %s_tile_count = %du;" % (name, len(unique_tiles)))
        lines.append("const u8 %s_tiles_u8[] = {" % name)
        lines.extend(_fmt_u8_rows(tile_bytes))
        lines.append("};")
        lines.append("")
    else:
        lines.append("const u16 %s_tiles_count = %du;" % (name, len(tile_words)))
        lines.append("const u16 %s_tiles[] = {" % name)
        lines.extend(_fmt_u16_rows(tile_words))
        lines.append("};")
        lines.append("")

    lines.append("const u16 %s_map_tiles[] = {" % name)
    lines.extend(_fmt_u16_rows(map_tile_ids))
    lines.append("};")
    lines.append("")

    lines.append("const u8 %s_map_pals[] = {" % name)
    lines.extend(_fmt_u8_rows(map_pal_ids))
    lines.append("};")
    lines.append("")

    return "\n".join(lines)


def format_c_header(name: str, emit_u8_tiles: bool) -> str:
    guard = (name + "_TILEMAP_H").upper()
    lines: list[str] = []
    lines.append("/* Generated by ngpc_tilemap.py - do not edit */")
    lines.append("")
    lines.append("#ifndef %s" % guard)
    lines.append("#define %s" % guard)
    lines.append("")
    lines.append('#include "ngpc_types.h"')
    lines.append("")
    lines.append("extern const u16 %s_map_w;" % name)
    lines.append("extern const u16 %s_map_h;" % name)
    lines.append("extern const u16 %s_map_len;" % name)
    lines.append("")
    lines.append("extern const u8 %s_palette_count;" % name)
    lines.append("extern const u16 NGP_FAR %s_palettes[];" % name)
    lines.append("")
    if emit_u8_tiles:
        lines.append("extern const u16 %s_tile_count;" % name)
        lines.append("extern const u8 NGP_FAR %s_tiles_u8[];" % name)
    else:
        lines.append("extern const u16 %s_tiles_count;" % name)
        lines.append("extern const u16 NGP_FAR %s_tiles[];" % name)
    lines.append("")
    lines.append("extern const u16 NGP_FAR %s_map_tiles[];" % name)
    lines.append("extern const u8 NGP_FAR %s_map_pals[];" % name)
    lines.append("")
    lines.append("#endif /* %s */" % guard)
    lines.append("")
    return "\n".join(lines)


def _format_layer_source(
    lines: list[str],
    prefix: str,
    label: str,
    tile_w: int,
    tile_h: int,
    palette_colors: list[list[int]],
    map_tile_ids: list[int],
    map_pal_ids: list[int],
) -> None:
    """Append C source lines for one scroll layer (used by dual-layer mode)."""
    pal_words: list[int] = [
        (0 if c == OPAQUE_BLACK else c) for pal in palette_colors for c in pal
    ]
    lines.append("/* --- %s --- */" % label)
    lines.append("const u16 %s_map_w = %du;" % (prefix, tile_w))
    lines.append("const u16 %s_map_h = %du;" % (prefix, tile_h))
    lines.append("const u16 %s_map_len = %du;" % (prefix, len(map_tile_ids)))
    lines.append("")
    lines.append("const u8 %s_palette_count = %du;" % (prefix, len(palette_colors)))
    lines.append("const u16 %s_palettes[] = {" % prefix)
    lines.extend(_fmt_u16_rows(pal_words))
    lines.append("};")
    lines.append("")
    lines.append("const u16 %s_map_tiles[] = {" % prefix)
    lines.extend(_fmt_u16_rows(map_tile_ids))
    lines.append("};")
    lines.append("")
    lines.append("const u8 %s_map_pals[] = {" % prefix)
    lines.extend(_fmt_u8_rows(map_pal_ids))
    lines.append("};")
    lines.append("")


def format_c_source_dual(
    name: str,
    scr1_tile_w: int, scr1_tile_h: int,
    scr1_palette_colors: list[list[int]],
    scr1_map_tile_ids: list[int], scr1_map_pal_ids: list[int],
    scr2_tile_w: int, scr2_tile_h: int,
    scr2_palette_colors: list[list[int]],
    scr2_map_tile_ids: list[int], scr2_map_pal_ids: list[int],
    unique_tiles: list[tuple[int, ...]],
    emit_u8_tiles: bool,
) -> str:
    """Format C source for dual-layer (SCR1+SCR2) tilemap data."""
    tile_words: list[int] = [w for t in unique_tiles for w in t]
    tile_bytes: list[int] = []
    for w in tile_words:
        tile_bytes.append(w & 0xFF)
        tile_bytes.append((w >> 8) & 0xFF)

    lines: list[str] = []
    lines.append("/* Generated by ngpc_tilemap.py (dual-layer) - do not edit */")
    lines.append("")
    lines.append('#include "ngpc_types.h"')
    lines.append("")
    lines.append("/* SCR1: %dx%d px (%dx%d tiles), SCR2: %dx%d px (%dx%d tiles) */" % (
        scr1_tile_w * 8, scr1_tile_h * 8, scr1_tile_w, scr1_tile_h,
        scr2_tile_w * 8, scr2_tile_h * 8, scr2_tile_w, scr2_tile_h,
    ))
    lines.append("/* Tiles: %d unique (shared VRAM, %d words) */" % (
        len(unique_tiles), len(tile_words),
    ))
    lines.append("/* SCR1 palettes: %d, SCR2 palettes: %d */" % (
        len(scr1_palette_colors), len(scr2_palette_colors),
    ))
    lines.append("")

    lines.append("/* --- Shared tile data --- */")
    if emit_u8_tiles:
        lines.append("const u16 %s_tile_count = %du;" % (name, len(unique_tiles)))
        lines.append("const u8 %s_tiles_u8[] = {" % name)
        lines.extend(_fmt_u8_rows(tile_bytes))
        lines.append("};")
        lines.append("")
    else:
        lines.append("const u16 %s_tiles_count = %du;" % (name, len(tile_words)))
        lines.append("const u16 %s_tiles[] = {" % name)
        lines.extend(_fmt_u16_rows(tile_words))
        lines.append("};")
        lines.append("")

    _format_layer_source(
        lines, name + "_scr1", "SCR1 (front layer)",
        scr1_tile_w, scr1_tile_h, scr1_palette_colors,
        scr1_map_tile_ids, scr1_map_pal_ids,
    )
    _format_layer_source(
        lines, name + "_scr2", "SCR2 (back layer)",
        scr2_tile_w, scr2_tile_h, scr2_palette_colors,
        scr2_map_tile_ids, scr2_map_pal_ids,
    )

    return "\n".join(lines)


def _format_layer_header(lines: list[str], prefix: str) -> None:
    """Append header extern declarations for one scroll layer."""
    lines.append("extern const u16 %s_map_w;" % prefix)
    lines.append("extern const u16 %s_map_h;" % prefix)
    lines.append("extern const u16 %s_map_len;" % prefix)
    lines.append("")
    lines.append("extern const u8 %s_palette_count;" % prefix)
    lines.append("extern const u16 NGP_FAR %s_palettes[];" % prefix)
    lines.append("")
    lines.append("extern const u16 NGP_FAR %s_map_tiles[];" % prefix)
    lines.append("extern const u8 NGP_FAR %s_map_pals[];" % prefix)
    lines.append("")


def format_c_header_dual(name: str, emit_u8_tiles: bool) -> str:
    """Format C header for dual-layer (SCR1+SCR2) tilemap data."""
    guard = (name + "_TILEMAP_H").upper()
    lines: list[str] = []
    lines.append("/* Generated by ngpc_tilemap.py (dual-layer) - do not edit */")
    lines.append("")
    lines.append("#ifndef %s" % guard)
    lines.append("#define %s" % guard)
    lines.append("")
    lines.append('#include "ngpc_types.h"')
    lines.append("")
    lines.append("/* Shared tile data */")
    if emit_u8_tiles:
        lines.append("extern const u16 %s_tile_count;" % name)
        lines.append("extern const u8 NGP_FAR %s_tiles_u8[];" % name)
    else:
        lines.append("extern const u16 %s_tiles_count;" % name)
        lines.append("extern const u16 NGP_FAR %s_tiles[];" % name)
    lines.append("")
    lines.append("/* SCR1 (front) */")
    _format_layer_header(lines, name + "_scr1")
    lines.append("/* SCR2 (back) */")
    _format_layer_header(lines, name + "_scr2")
    lines.append("#endif /* %s */" % guard)
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="Convert PNG to NGPC tilemap assets")
    p.add_argument("input", help="Input PNG path (SCR1 in dual-layer mode)")
    p.add_argument("-o", "--output", required=True, help="Output .c path")
    p.add_argument("-n", "--name", default=None, help="Base C symbol name (default: from input)")
    p.add_argument("--header", action="store_true", help="Also generate matching .h")
    p.add_argument(
        "--scr2",
        default=None,
        help="Second PNG for SCR2 (back layer). Enables dual-layer mode with "
             "global tile dedup and independent palettes per layer.",
    )
    p.add_argument(
        "--tiles-bin",
        default=None,
        help="Optional raw tile dump (.bin, little-endian u16 words) for compression pipeline",
    )
    p.add_argument(
        "--max-palettes",
        type=int,
        default=16,
        help="Max palette count per layer (default: 16, NGPC scroll limit)",
    )
    p.add_argument(
        "--emit-u8-tiles",
        action="store_true",
        help="Also emit raw 16-byte-per-tile array (<name>_tiles_u8) and tile count",
    )
    p.add_argument(
        "--black-is-transparent",
        action="store_true",
        help="Treat opaque RGB444 black as transparent index 0 (legacy-style conversion)",
    )
    p.add_argument("--no-dedupe", action="store_true", help="Disable tile deduplication")
    args = p.parse_args()

    if args.max_palettes < 1 or args.max_palettes > 16:
        print("Error: --max-palettes must be in range 1..16", file=sys.stderr)
        return 2

    if args.name:
        base_name = sanitize_c_identifier(args.name)
    else:
        base_name = sanitize_c_identifier(os.path.splitext(os.path.basename(args.input))[0])

    dedupe = not args.no_dedupe

    # ---- Dual-layer mode (SCR1 + SCR2) ----
    if args.scr2:
        try:
            tw1, th1, tiles1, tsets1 = extract_tiles(
                args.input, black_is_transparent=args.black_is_transparent,
            )
            if tw1 > NGPC_MAP_W or th1 > NGPC_MAP_H:
                print(
                    "Warning: SCR1 map %dx%d exceeds 32x32 — streaming required at runtime."
                    % (tw1, th1),
                    file=sys.stderr,
                )
            tw2, th2, tiles2, tsets2 = extract_tiles(
                args.scr2, black_is_transparent=args.black_is_transparent,
            )
            if tw2 > NGPC_MAP_W or th2 > NGPC_MAP_H:
                print(
                    "Warning: SCR2 map %dx%d exceeds 32x32 — streaming required at runtime."
                    % (tw2, th2),
                    file=sys.stderr,
                )

            # Independent palette assignment per layer.
            pals1, tpids1 = assign_palettes(tsets1, args.max_palettes)
            pals2, tpids2 = assign_palettes(tsets2, args.max_palettes)
            pcols1, pimaps1 = build_palette_index_maps(pals1, tiles1, tpids1)
            pcols2, pimaps2 = build_palette_index_maps(pals2, tiles2, tpids2)

            # Encode SCR1 first, then SCR2 extending the same tile pool.
            pool, pool_idx, map_t1, map_p1 = encode_tiles_and_map(
                tiles1, tpids1, pimaps1, dedupe,
            )
            pool, _, map_t2, map_p2 = encode_tiles_and_map(
                tiles2, tpids2, pimaps2, dedupe,
                tile_pool=pool, tile_pool_index=pool_idx,
            )

            if len(pool) > NGPC_MAX_TILES:
                raise ValueError(
                    "Combined unique tile count %d exceeds NGPC VRAM limit %d "
                    "(SCR1 + SCR2 share the same 512-tile character RAM)."
                    % (len(pool), NGPC_MAX_TILES)
                )
        except Exception as exc:
            print("Error: %s" % exc, file=sys.stderr)
            return 1

        c_src = format_c_source_dual(
            base_name,
            tw1, th1, pcols1, map_t1, map_p1,
            tw2, th2, pcols2, map_t2, map_p2,
            pool, emit_u8_tiles=args.emit_u8_tiles,
        )

        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(c_src)

        if args.tiles_bin:
            write_tiles_bin(args.tiles_bin, pool)

        if args.header:
            h_path = os.path.splitext(args.output)[0] + ".h"
            h_src = format_c_header_dual(base_name, emit_u8_tiles=args.emit_u8_tiles)
            with open(h_path, "w", encoding="utf-8") as f:
                f.write(h_src)
            print("Header:    %s" % h_path)
        if args.tiles_bin:
            print("Tiles bin: %s" % args.tiles_bin)

        dedupe_str = "off" if args.no_dedupe else "on"
        print("Mode:      dual-layer (SCR1 + SCR2)")
        print("SCR1:      %s (%dx%d tiles)" % (args.input, tw1, th1))
        print("SCR2:      %s (%dx%d tiles)" % (args.scr2, tw2, th2))
        print("Palettes:  SCR1=%d, SCR2=%d" % (len(pcols1), len(pcols2)))
        print("Tiles:     %d unique shared (dedupe=%s)" % (len(pool), dedupe_str))
        print("Output:    %s (symbols: %s_*)" % (args.output, base_name))
        return 0

    # ---- Single-image mode (auto-split if tiles exceed 3 colors) ----
    try:
        tile_w, tile_h, tiles, tile_sets = extract_tiles(
            args.input,
            black_is_transparent=args.black_is_transparent,
            strict=False,
        )
        if tile_w > NGPC_MAP_W or tile_h > NGPC_MAP_H:
            print(
                "Warning: map %dx%d exceeds 32x32 — streaming required at runtime."
                % (tile_w, tile_h),
                file=sys.stderr,
            )
    except Exception as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 1

    # Auto-split: if any tile has >3 visible colors, split across SCR1+SCR2.
    if needs_layer_split(tile_sets):
        try:
            s1t, s1s, s2t, s2s, split_n = split_layers(tiles, tile_sets)

            pals1, tpids1 = assign_palettes(s1s, args.max_palettes)
            pals2, tpids2 = assign_palettes(s2s, args.max_palettes)
            pcols1, pimaps1 = build_palette_index_maps(pals1, s1t, tpids1)
            pcols2, pimaps2 = build_palette_index_maps(pals2, s2t, tpids2)

            pool, pool_idx, map_t1, map_p1 = encode_tiles_and_map(
                s1t, tpids1, pimaps1, dedupe,
            )
            pool, _, map_t2, map_p2 = encode_tiles_and_map(
                s2t, tpids2, pimaps2, dedupe,
                tile_pool=pool, tile_pool_index=pool_idx,
            )

            if len(pool) > NGPC_MAX_TILES:
                raise ValueError(
                    "Combined unique tile count %d exceeds NGPC VRAM limit %d."
                    % (len(pool), NGPC_MAX_TILES)
                )
        except Exception as exc:
            print("Error: %s" % exc, file=sys.stderr)
            return 1

        c_src = format_c_source_dual(
            base_name,
            tile_w, tile_h, pcols1, map_t1, map_p1,
            tile_w, tile_h, pcols2, map_t2, map_p2,
            pool, emit_u8_tiles=args.emit_u8_tiles,
        )

        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(c_src)

        if args.tiles_bin:
            write_tiles_bin(args.tiles_bin, pool)

        if args.header:
            h_path = os.path.splitext(args.output)[0] + ".h"
            h_src = format_c_header_dual(base_name, emit_u8_tiles=args.emit_u8_tiles)
            with open(h_path, "w", encoding="utf-8") as f:
                f.write(h_src)
            print("Header:    %s" % h_path)
        if args.tiles_bin:
            print("Tiles bin: %s" % args.tiles_bin)

        dedupe_str = "off" if args.no_dedupe else "on"
        print("Mode:      auto-split (SCR1 + SCR2)")
        print("Input:     %s" % args.input)
        print("Split:     %d tiles had >3 colors -> split across layers" % split_n)
        print("Map:       %dx%d tiles" % (tile_w, tile_h))
        print("Palettes:  SCR1=%d, SCR2=%d" % (len(pcols1), len(pcols2)))
        print("Tiles:     %d unique shared (dedupe=%s)" % (len(pool), dedupe_str))
        print("Output:    %s (symbols: %s_*)" % (args.output, base_name))
        return 0

    # ---- All tiles fit in 3 colors: single-layer output ----
    try:
        palettes, tile_pal_ids = assign_palettes(tile_sets, args.max_palettes)
        palette_colors, palette_idx_maps = build_palette_index_maps(palettes, tiles, tile_pal_ids)
        unique_tiles, _, map_tile_ids, map_pal_ids = encode_tiles_and_map(
            tiles, tile_pal_ids, palette_idx_maps, dedupe,
        )
        if len(unique_tiles) > NGPC_MAX_TILES:
            raise ValueError(
                "Unique tile count %d exceeds NGPC tile VRAM limit %d."
                % (len(unique_tiles), NGPC_MAX_TILES)
            )
    except Exception as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 1

    c_src = format_c_source(
        base_name,
        tile_w,
        tile_h,
        palette_colors,
        unique_tiles,
        map_tile_ids,
        map_pal_ids,
        emit_u8_tiles=args.emit_u8_tiles,
    )

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(c_src)

    if args.tiles_bin:
        write_tiles_bin(args.tiles_bin, unique_tiles)

    if args.header:
        h_path = os.path.splitext(args.output)[0] + ".h"
        h_src = format_c_header(base_name, emit_u8_tiles=args.emit_u8_tiles)
        with open(h_path, "w", encoding="utf-8") as f:
            f.write(h_src)
        print("Header:    %s" % h_path)
    if args.tiles_bin:
        print("Tiles bin: %s" % args.tiles_bin)

    map_tiles = tile_w * tile_h
    print("Input:     %s" % args.input)
    print("Map:       %dx%d tiles (%d cells)" % (tile_w, tile_h, map_tiles))
    print("Palettes:  %d" % len(palette_colors))
    print("Tiles:     %d unique (dedupe=%s)" % (len(unique_tiles), "off" if args.no_dedupe else "on"))
    print("Output:    %s (symbols: %s_*)" % (args.output, base_name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
