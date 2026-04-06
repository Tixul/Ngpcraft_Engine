"""
core/rgb444.py - RGB444 quantization utilities for NGPC hardware.

The NGPC uses RGB444 color (4 bits per channel).
Encoding: word = r4 | (g4 << 4) | (b4 << 8)
Display value: each nibble × 17 gives 8-bit equivalent.
"""

from __future__ import annotations

from PIL import Image

OPAQUE_BLACK = 0x1000  # matches ngpc_sprite_export.py internal sentinel


def snap(r: int, g: int, b: int) -> tuple[int, int, int]:
    """Quantize an 8-bit RGB triplet to the nearest RGB444 representable value."""
    r4 = r >> 4
    g4 = g >> 4
    b4 = b >> 4
    return (r4 * 17, g4 * 17, b4 * 17)


def to_nibbles(r: int, g: int, b: int) -> tuple[int, int, int]:
    """Return (r4, g4, b4) nibbles (0..15) for an 8-bit RGB triplet."""
    return (r >> 4, g >> 4, b >> 4)


def to_word(r: int, g: int, b: int) -> int:
    """Convert 8-bit RGB to NGPC u16 palette word."""
    r4, g4, b4 = to_nibbles(r, g, b)
    return r4 | (g4 << 4) | (b4 << 8)

def to_word_sprite(r: int, g: int, b: int) -> int:
    """
    Convert 8-bit RGB to the palette word convention used by the template exporter.

    Index 0 is reserved for transparency (word 0x0000). Pure opaque black must be
    represented as OPAQUE_BLACK (0x1000) to avoid colliding with transparency.
    """
    w = to_word(r, g, b)
    return OPAQUE_BLACK if w == 0 else w


def from_word(word: int) -> tuple[int, int, int]:
    """Convert NGPC u16 palette word to 8-bit RGB."""
    r4 = word & 0xF
    g4 = (word >> 4) & 0xF
    b4 = (word >> 8) & 0xF
    return (r4 * 17, g4 * 17, b4 * 17)


def quantize_image(img: Image.Image) -> Image.Image:
    """
    Return a copy of img with all opaque pixels snapped to the nearest RGB444 color.
    Transparent pixels (alpha < 128) are left unchanged.
    """
    out = img.convert("RGBA").copy()
    px = out.load()
    w, h = out.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a >= 128:
                rs, gs, bs = snap(r, g, b)
                px[x, y] = (rs, gs, bs, a)
    return out


def palette_from_image(img: Image.Image) -> list[tuple[int, int, int]]:
    """
    Extract ordered unique opaque RGB444 colors from img.
    Returns list of (r8, g8, b8) tuples (already snapped).
    Transparent pixels are ignored.
    """
    seen: dict[tuple[int, int, int], int] = {}
    rgba = img.convert("RGBA")
    for r, g, b, a in rgba.getdata():
        if a < 128:
            continue
        key = snap(r, g, b)
        seen[key] = seen.get(key, 0) + 1
    # Sort by frequency descending, then by value for determinism.
    return [c for c, _ in sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))]


def colors_per_tile(img: Image.Image, tile_w: int = 8, tile_h: int = 8) -> list[list[int]]:
    """
    Return a 2D list [row][col] with the number of distinct opaque RGB444 colors per 8×8 tile.
    """
    rgba = img.convert("RGBA")
    w, h = rgba.size
    cols = w // tile_w
    rows = h // tile_h
    px = rgba.load()
    result: list[list[int]] = []
    for row in range(rows):
        row_counts: list[int] = []
        for col in range(cols):
            colors: set[tuple[int, int, int]] = set()
            for ty in range(tile_h):
                for tx in range(tile_w):
                    x = col * tile_w + tx
                    y = row * tile_h + ty
                    r, g, b, a = px[x, y]
                    if a >= 128:
                        colors.add(snap(r, g, b))
            row_counts.append(len(colors))
        result.append(row_counts)
    return result
