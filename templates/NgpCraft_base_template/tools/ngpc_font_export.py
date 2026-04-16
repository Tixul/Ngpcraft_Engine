#!/usr/bin/env python3
"""
ngpc_font_export.py - Custom 8x8 font PNG to NGPC tile data

Converts a 128x48 PNG tilesheet into NGPC 2bpp tile data compatible with
the ngpc_text_* API.  Loading the output replaces the BIOS system font
(VECT_SYSFONTSET) while keeping full API compatibility: no changes to
ngpc_text_print / ngpc_text_print_dec / ngpc_text_print_hex.

──────────────────────────────────────────────────────────────────────
PNG FORMAT (required)
  Dimensions : 128 x 48 pixels  (16 chars/row × 8 px, 6 rows × 8 px)
  Total      : 96 tiles  →  ASCII 32 (space) … 127 (DEL)
  Colors     : 4 max across the whole sheet (2bpp hardware limit)
    index 0  : background / transparent  (alpha < 128  OR  #000000)
    index 1  : primary text color
    index 2  : secondary color (shadow, outline…)  — optional
    index 3  : tertiary color                       — optional

Tile order (left→right, top→bottom):
  Row 0  ASCII  32– 47   space ! " # $ % & ' ( ) * + , - . /
  Row 1  ASCII  48– 63   0 1 2 3 4 5 6 7 8 9 : ; < = > ?
  Row 2  ASCII  64– 79   @ A B C D E F G H I J K L M N O
  Row 3  ASCII  80– 95   P Q R S T U V W X Y Z [ \\ ] ^ _
  Row 4  ASCII  96–111   ` a b c d e f g h i j k l m n o
  Row 5  ASCII 112–127   p q r s t u v w x y z { | } ~  [DEL]

The tile for ASCII 32 is placed at VRAM tile slot 32 (= NGPC_FONT_TILE_BASE).
Runtime mapping: tile_slot = ascii_code  (identical to BIOS system font).

──────────────────────────────────────────────────────────────────────
USAGE
  python tools/ngpc_font_export.py font.png -o GraphX/ngpc_custom_font
  python tools/ngpc_font_export.py font.png -o GraphX/ngpc_custom_font -n myfont

OPTIONS
  font.png          Input PNG (must be 128x48)
  -o / --output     Output base path (without .c / .h extension)
  -n / --name       C symbol prefix  (default: derived from output basename)
  --tile-base N     VRAM tile slot for first character (default: 32)
"""

from __future__ import annotations

import argparse
import os
import sys
import re

try:
    from PIL import Image
except ImportError:
    print("Error: Pillow is required.  pip install pillow", file=sys.stderr)
    raise SystemExit(2)

# ── constants ─────────────────────────────────────────────────────────────────

FONT_COLS       = 16          # characters per row in the PNG
FONT_ROWS       = 6           # rows in the PNG
FONT_TILE_COUNT = FONT_COLS * FONT_ROWS   # 96
TILE_W = TILE_H = 8
PNG_W = FONT_COLS * TILE_W    # 128
PNG_H = FONT_ROWS * TILE_H    # 48
WORDS_PER_TILE  = 8           # one u16 word per pixel row

DEFAULT_TILE_BASE = 32        # ASCII mapping: tile_slot == ascii_code

# ── helpers ───────────────────────────────────────────────────────────────────

def sanitize_c_identifier(name: str) -> str:
    name = re.sub(r"[^0-9A-Za-z_]", "_", name)
    if not name:
        name = "font"
    if name[0].isdigit():
        name = "font_" + name
    return name


def _is_transparent(r: int, g: int, b: int, a: int) -> bool:
    """True if the pixel should map to color index 0 (hardware clear)."""
    if a < 128:
        return True
    # Pure black with full alpha = also treated as transparent background,
    # matching the convention used by ngpc_sprite_export.py.
    if r == 0 and g == 0 and b == 0:
        return True
    return False


def build_color_map(img_rgba: Image.Image) -> dict[tuple[int, int, int], int]:
    """
    Scan the entire image and assign color indices 1-3 to the (up to 3)
    distinct non-transparent colors, in order of first appearance
    (raster scan, top-left first).

    Returns a dict:  rgb_tuple -> color_index (1..3)
    Raises ValueError if more than 3 non-transparent colors are found.
    """
    color_map: dict[tuple[int, int, int], int] = {}
    pixels = img_rgba.load()
    assert pixels is not None

    for y in range(PNG_H):
        for x in range(PNG_W):
            r, g, b, a = pixels[x, y]
            if _is_transparent(r, g, b, a):
                continue
            key = (r, g, b)
            if key not in color_map:
                idx = len(color_map) + 1   # 1, 2, 3 …
                if idx > 3:
                    raise ValueError(
                        f"Font PNG has more than 3 non-transparent colors "
                        f"(hardware limit: 2bpp = 4 indices, index 0 reserved for "
                        f"transparency).  Found 4th color at pixel ({x},{y}): "
                        f"rgb({r},{g},{b}).\n"
                        f"Reduce to 3 visible colors (+ transparent background)."
                    )
                color_map[key] = idx

    return color_map


def pixel_to_index(r: int, g: int, b: int, a: int,
                   color_map: dict[tuple[int, int, int], int]) -> int:
    if _is_transparent(r, g, b, a):
        return 0
    return color_map.get((r, g, b), 0)


def tile_words_from_indices(tile_indices: list[int]) -> list[int]:
    """
    Convert a flat list of 64 color indices (8x8, row-major) to 8 u16 words.
    Each word encodes one row of 8 pixels: pixel 0 at bits [15:14], …,
    pixel 7 at bits [1:0].  Identical encoding to ngpc_sprite_export.py.
    """
    words: list[int] = []
    for row in range(8):
        w = 0
        base = row * 8
        for col in range(8):
            idx = tile_indices[base + col] & 0x03
            w |= idx << (14 - col * 2)
        words.append(w)
    return words


def extract_tiles(img_rgba: Image.Image,
                  color_map: dict[tuple[int, int, int], int]
                  ) -> list[list[int]]:
    """
    Extract FONT_TILE_COUNT tiles from the PNG in reading order.
    Returns a list of FONT_TILE_COUNT tile_words lists (each 8 u16 ints).
    """
    pixels = img_rgba.load()
    assert pixels is not None
    tiles: list[list[int]] = []

    for tile_row in range(FONT_ROWS):
        for tile_col in range(FONT_COLS):
            ox = tile_col * TILE_W
            oy = tile_row * TILE_H
            indices: list[int] = []
            for py in range(TILE_H):
                for px in range(TILE_W):
                    r, g, b, a = pixels[ox + px, oy + py]
                    indices.append(pixel_to_index(r, g, b, a, color_map))
            tiles.append(tile_words_from_indices(indices))

    return tiles


# ── output generation ─────────────────────────────────────────────────────────

_C_HEADER = """\
/* Auto-generated by ngpc_font_export.py — DO NOT EDIT
 * Source : {src_name}
 * Tiles  : {tile_count} (ASCII {ascii_first}–{ascii_last})
 * Base   : tile slot {tile_base} (NGPC_FONT_TILE_BASE)
 * Each tile : {wpt} u16 words (8x8, 2bpp)
 */
#include "ngpc_types.h"

const u16 NGP_FAR {sym}_tiles[{tile_count} * {wpt}] = {{
"""

_C_FOOTER = "};\n"

_H_TEMPLATE = """\
/* Auto-generated by ngpc_font_export.py — DO NOT EDIT
 * Source : {src_name}
 *
 * Usage:
 *   #include "GraphX/{hdr_basename}"
 *   // In init, instead of ngpc_load_sysfont():
 *   {sym}_load();
 *   // ngpc_text_print() then works with the custom font.
 */
#ifndef {guard}
#define {guard}

#include "ngpc_types.h"
#include "../gfx/ngpc_gfx.h"

/* VRAM tile slot for the first character (space, ASCII 32).
 * tile_slot = ascii_code  — identical mapping to the BIOS system font. */
#define NGPC_FONT_TILE_BASE   {tile_base}u
/* Total number of tiles in this font (ASCII {ascii_first}–{ascii_last}). */
#define NGPC_FONT_TILE_COUNT  {tile_count}u

extern const u16 NGP_FAR {sym}_tiles[NGPC_FONT_TILE_COUNT * {wpt}u];

/* Load the custom font into Character RAM.
 * Call once at startup, replaces ngpc_load_sysfont().
 * After this call ngpc_text_print() uses the custom font. */
static inline void {sym}_load(void)
{{
    ngpc_gfx_load_tiles_at({sym}_tiles,
                           NGPC_FONT_TILE_COUNT * {wpt}u,
                           NGPC_FONT_TILE_BASE);
}}

#endif /* {guard} */
"""

ASCII_CHARS = [chr(i) if 32 <= i < 127 else "[DEL]" for i in range(32, 128)]


def write_c(path: str, sym: str, src_name: str,
            tiles: list[list[int]], tile_base: int) -> None:
    tile_count = len(tiles)
    with open(path, "w", encoding="utf-8") as f:
        f.write(_C_HEADER.format(
            src_name=src_name,
            tile_count=tile_count,
            ascii_first=tile_base,
            ascii_last=tile_base + tile_count - 1,
            tile_base=tile_base,
            wpt=WORDS_PER_TILE,
            sym=sym,
        ))
        for ti, words in enumerate(tiles):
            ascii_code = tile_base + ti
            label = ASCII_CHARS[ti] if ti < len(ASCII_CHARS) else "?"
            f.write(f"    /* [{ti:2d}] '{label}' (ASCII {ascii_code}) */\n")
            hex_words = ", ".join(f"0x{w:04X}" for w in words)
            f.write(f"    {hex_words},\n")
        f.write(_C_FOOTER)


def write_h(path: str, sym: str, src_name: str,
            hdr_basename: str, tile_base: int, tile_count: int) -> None:
    guard = f"NGPC_{sym.upper()}_H"
    with open(path, "w", encoding="utf-8") as f:
        f.write(_H_TEMPLATE.format(
            src_name=src_name,
            guard=guard,
            tile_base=tile_base,
            tile_count=tile_count,
            ascii_first=tile_base,
            ascii_last=tile_base + tile_count - 1,
            wpt=WORDS_PER_TILE,
            sym=sym,
            hdr_basename=hdr_basename,
        ))


# ── main ──────────────────────────────────────────────────────────────────────

def export_font(png_path: str, output_base: str, name: str | None = None,
                tile_base: int = DEFAULT_TILE_BASE) -> tuple[str, str]:
    """
    Export a font PNG to NGPC .c/.h files.

    Returns (c_path, h_path).
    Raises ValueError / IOError on bad input.
    """
    # ── open & validate PNG ───────────────────────────────────────────────
    try:
        img = Image.open(png_path)
    except Exception as exc:
        raise IOError(f"Cannot open '{png_path}': {exc}") from exc

    img = img.convert("RGBA")
    if img.width != PNG_W or img.height != PNG_H:
        raise ValueError(
            f"Font PNG must be exactly {PNG_W}×{PNG_H} pixels "
            f"(16 chars × {TILE_W}px wide, {FONT_ROWS} rows × {TILE_H}px tall = "
            f"{FONT_TILE_COUNT} tiles).\n"
            f"Got: {img.width}×{img.height}."
        )

    # ── build global color map ────────────────────────────────────────────
    color_map = build_color_map(img)
    n_colors = len(color_map)
    if n_colors == 0:
        print("Warning: font image appears to be fully transparent.", file=sys.stderr)

    # ── extract tiles ─────────────────────────────────────────────────────
    tiles = extract_tiles(img, color_map)

    # ── resolve output paths & symbol ────────────────────────────────────
    c_path = output_base + ".c"
    h_path = output_base + ".h"
    hdr_basename = os.path.basename(h_path)

    if name is None:
        name = sanitize_c_identifier(os.path.splitext(os.path.basename(output_base))[0])
    else:
        name = sanitize_c_identifier(name)

    src_name = os.path.basename(png_path)

    # ── write files ───────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(os.path.abspath(c_path)), exist_ok=True)
    write_c(c_path, name, src_name, tiles, tile_base)
    write_h(h_path, name, src_name, hdr_basename, tile_base, FONT_TILE_COUNT)

    print(f"Font export: {FONT_TILE_COUNT} tiles, {n_colors} visible color(s)")
    print(f"  → {c_path}")
    print(f"  → {h_path}")
    return c_path, h_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export a 128×48 font PNG to NGPC 2bpp tile data (.c/.h).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("png", help="Input PNG (128×48)")
    parser.add_argument("-o", "--output", required=True,
                        help="Output base path (without .c/.h extension)")
    parser.add_argument("-n", "--name", default=None,
                        help="C symbol prefix (default: derived from output basename)")
    parser.add_argument("--tile-base", type=int, default=DEFAULT_TILE_BASE,
                        help=f"VRAM tile slot for ASCII 32 / space (default: {DEFAULT_TILE_BASE})")
    args = parser.parse_args()

    try:
        export_font(args.png, args.output, args.name, args.tile_base)
    except (ValueError, IOError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
