"""
core/palette_remap.py - Checkerboard composite and helper utilities.
"""

from __future__ import annotations

from PIL import Image

from core.rgb444 import OPAQUE_BLACK, to_word_sprite


def make_checkerboard(w: int, h: int, size: int = 8) -> Image.Image:
    """Generate a gray checkerboard RGBA image of size w×h."""
    checker = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    px = checker.load()
    dark = (180, 180, 180, 255)
    light = (240, 240, 240, 255)
    for y in range(h):
        for x in range(w):
            if ((x // size) + (y // size)) % 2 == 0:
                px[x, y] = light
            else:
                px[x, y] = dark
    return checker


def composite_on_checker(img: Image.Image, checker_size: int = 8) -> Image.Image:
    """Composite an RGBA image over a checkerboard background."""
    checker = make_checkerboard(img.size[0], img.size[1], checker_size)
    checker.paste(img, (0, 0), img)
    return checker.convert("RGB")


def palette_to_fixed_arg(palette: list[tuple[int, int, int]]) -> str:
    """
    Format a palette as a --fixed-palette argument string for ngpc_sprite_export.py.

    Requires exactly 4 entries:
      - index 0: transparency (0x0000)
      - indices 1..3: visible colors (opaque black must be OPAQUE_BLACK=0x1000)
    """
    visible = [to_word_sprite(r, g, b) for r, g, b in palette]
    # De-dup while keeping order
    uniq: list[int] = []
    seen: set[int] = set()
    for w in visible:
        if w not in seen:
            uniq.append(w)
            seen.add(w)
    # Exactly 3 visible slots max for the template exporter
    uniq = uniq[:3]
    fixed = [0x0000] + uniq
    while len(fixed) < 4:
        fixed.append(0x0000)
    fixed = fixed[:4]

    # Safety: avoid accidental OPAQUE_BLACK in transparency slot
    if fixed[0] == OPAQUE_BLACK:
        fixed[0] = 0x0000
    return ",".join(f"0x{w:04X}" for w in fixed)
