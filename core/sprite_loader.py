"""
core/sprite_loader.py - Load a PNG and produce original + HW-quantized views.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from core.rgb444 import palette_from_image, quantize_image, to_word_sprite


@dataclass
class SpriteData:
    """Loaded sprite asset with both source pixels and RGB444-ready pixels."""

    path: Path
    original: Image.Image       # RGBA, untouched
    hw: Image.Image             # RGBA, every opaque pixel snapped to RGB444
    palette: list[tuple[int, int, int]]  # ordered [(r8,g8,b8), ...] — opaque colors only
    palette_words: list[int] = field(default_factory=list)  # NGPC u16 words

    def __post_init__(self) -> None:
        self.palette_words = [to_word_sprite(r, g, b) for (r, g, b) in self.palette]


def load_sprite(path: Path) -> SpriteData:
    """Open a PNG and return a SpriteData with original and RGB444-quantized views."""
    img = Image.open(path).convert("RGBA")
    hw = quantize_image(img)
    palette = palette_from_image(hw)
    return SpriteData(
        path=path,
        original=img,
        hw=hw,
        palette=palette,
    )


def remap_palette(data: SpriteData, new_palette: list[tuple[int, int, int]]) -> SpriteData:
    """
    Return a new SpriteData where each pixel is remapped from old palette to new_palette.

    new_palette must have the same length as data.palette.
    Transparent pixels are preserved.
    """
    if len(new_palette) != len(data.palette):
        raise ValueError("new_palette must be same length as data.palette")

    old_map: dict[tuple[int, int, int], tuple[int, int, int]] = {
        old: new for old, new in zip(data.palette, new_palette)
    }

    out = data.hw.copy()
    px = out.load()
    w, h = out.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 128:
                continue
            key = (r, g, b)
            if key in old_map:
                nr, ng, nb = old_map[key]
                px[x, y] = (nr, ng, nb, a)

    new_pal = list(new_palette)
    return SpriteData(path=data.path, original=data.original, hw=out, palette=new_pal)
