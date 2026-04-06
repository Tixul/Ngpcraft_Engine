"""
core/layer_split.py - Generalized N-layer sprite split for NGPC hardware.

NGPC hardware constraint: max 3 opaque colors per sprite palette slot.
A sprite with N opaque colors needs ceil(N/3) layers to be rendered.

Split strategy (matches ngpc_sprite_bundle.split_two_layers):
- Collect all opaque RGB444 colors globally (across all pixels)
- Sort by frequency descending (most-used colors in layer 0)
- Assign: layer 0 = colors [0..2], layer 1 = colors [3..5], layer 2 = colors [6..8] ...
- Route each pixel to the layer owning its color

In-game rendering: layers are drawn at the same (x,y) position;
transparency in upper layers reveals lower layers beneath.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image

from core.rgb444 import snap, to_word_sprite


@dataclass
class LayerInfo:
    """One generated hardware layer produced from an over-colored sprite."""

    index: int                           # 0-based layer index
    image: Image.Image                   # RGBA image (same size as source)
    colors: list[tuple[int, int, int]]   # Ordered opaque RGB444 colors (max 3)
    palette_words: list[int]             # 4 NGPC u16 words (index 0 = transparent = 0x0000)

    @property
    def fixed_palette_arg(self) -> str:
        """Return --fixed-palette argument string for ngpc_sprite_export.py."""
        return ",".join(f"0x{w:04X}" for w in self.palette_words)


@dataclass
class SplitResult:
    """High-level result of a layer split analysis/export preparation."""

    layers: list[LayerInfo]
    total_colors: int
    n_layers_needed: int

    @property
    def is_ok(self) -> bool:
        """Return True when the source image already fits in one NGPC layer."""
        return self.total_colors <= 3

    @property
    def suggestion(self) -> str:
        """Return a coarse UI hint describing the split situation."""
        n = self.total_colors
        layers = self.n_layers_needed
        if n == 0:
            return "no_pixels"
        if n <= 3:
            return "ok"
        if layers == 2:
            return "split_2"
        if layers == 3:
            return "split_3"
        return "too_many"


def layers_needed(n_colors: int) -> int:
    """Return the number of NGPC sprite layers needed for n_colors opaque colors."""
    if n_colors <= 0:
        return 1
    return math.ceil(n_colors / 3)


def split_layers(img: Image.Image) -> SplitResult:
    """
    Split an RGBA image into N layers of ≤3 opaque RGB444 colors each.

    Returns a SplitResult with one LayerInfo per required layer.
    If the image has ≤3 colors, returns a single layer equal to the quantized image.
    """
    rgba = img.convert("RGBA")
    w, h = rgba.size
    src_px = rgba.load()

    # 1. Collect opaque color frequencies (after RGB444 snap)
    freq: dict[tuple[int, int, int], int] = {}
    for y in range(h):
        for x in range(w):
            r, g, b, a = src_px[x, y]
            if a >= 128:
                key = snap(r, g, b)
                freq[key] = freq.get(key, 0) + 1

    # 2. Sort: most frequent first, then by RGB for determinism
    ordered = [c for c, _ in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))]
    n_colors = len(ordered)
    n_layers = layers_needed(n_colors)

    # 3. Assign colors to layers (3 per layer)
    color_to_layer: dict[tuple[int, int, int], int] = {}
    layer_color_sets: list[list[tuple[int, int, int]]] = []
    for i in range(n_layers):
        group = ordered[i * 3: i * 3 + 3]
        layer_color_sets.append(group)
        for c in group:
            color_to_layer[c] = i

    # 4. Build layer images
    layer_images = [Image.new("RGBA", (w, h), (0, 0, 0, 0)) for _ in range(n_layers)]
    layer_pxs = [limg.load() for limg in layer_images]

    for y in range(h):
        for x in range(w):
            r, g, b, a = src_px[x, y]
            if a < 128:
                continue
            key = snap(r, g, b)
            layer_idx = color_to_layer.get(key, 0)
            layer_pxs[layer_idx][x, y] = (snap(r, g, b)[0], snap(r, g, b)[1], snap(r, g, b)[2], a)

    # 5. Build LayerInfo list
    layer_infos: list[LayerInfo] = []
    for i, (limg, colors) in enumerate(zip(layer_images, layer_color_sets)):
        # Palette: word 0 = transparent (0x0000), words 1..3 = colors
        words = [0x0000]
        for r, g, b in colors:
            words.append(to_word_sprite(r, g, b))
        while len(words) < 4:
            words.append(0x0000)
        layer_infos.append(LayerInfo(
            index=i,
            image=limg,
            colors=colors,
            palette_words=words[:4],
        ))

    return SplitResult(
        layers=layer_infos,
        total_colors=n_colors,
        n_layers_needed=n_layers,
    )
