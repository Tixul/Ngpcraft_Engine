#!/usr/bin/env python3
"""
ngpc_sprite_export.py - Spritesheet to NGPC metasprite exporter

Converts one or two PNG spritesheets (grid frames) into:
- NGPC 2bpp sprite tiles (u16 words)
- sprite palettes (RGB444, up to 16 x 4 colors shared)
- NgpcMetasprite frame definitions (per layer)
- MsprAnimFrame table (per layer)

Template palette policy:
- Index 0 is reserved for transparency.
- Per 8x8 tile: max 3 visible colors (+ transparent index 0).

Single-layer mode (default):
    python tools/ngpc_sprite_export.py sprites.png -o GraphX/player_mspr.c -n player \
        --frame-w 16 --frame-h 16 --header

Dual-layer mode (base + overlay):
    python tools/ngpc_sprite_export.py base.png --layer2 overlay.png \
        -o GraphX/player_mspr.c -n player --frame-w 16 --frame-h 16 --header

    Both images must have the same frame dimensions and frame count.
    Tiles are globally deduplicated across both layers (shared VRAM).
    Palettes are combined (base first, overlay after) since sprites
    share a single 16-palette bank on NGPC hardware.
    At runtime, draw both layers at the same position for overlay effect.
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

MSPR_MAX_PARTS = 16
MSPR_MAX_OFFSET_DIM = 128  # ox/oy are s8 in MsprPart (0..127 used by exporter)
OPAQUE_BLACK = 0x1000  # internal sentinel to distinguish from transparent 0


def sanitize_c_identifier(name: str) -> str:
    name = re.sub(r"[^0-9A-Za-z_]", "_", name)
    if not name:
        name = "asset"
    if name[0].isdigit():
        name = "asset_" + name
    return name


def rgba_to_rgb444(px: tuple[int, int, int, int]) -> int:
    r, g, b, a = px
    if a < 128:
        return 0
    rgb444 = ((r >> 4) & 0xF) | (((g >> 4) & 0xF) << 4) | (((b >> 4) & 0xF) << 8)
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


def assign_palettes(tile_sets: list[frozenset[int]], max_palettes: int) -> tuple[list[set[int]], list[int]]:
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
            if len(union) <= 4:
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

        raise ValueError("Need more than %d palettes. Reduce sprite color variety." % max_palettes)

    tile_pal_ids = [set_to_pal[set_ids[s]] for s in tile_sets]
    return palettes, tile_pal_ids


def build_palette_index_maps(
    palettes: list[set[int]],
    tile_colors: list[tuple[int, ...]],
    tile_pal_ids: list[int],
) -> tuple[list[list[int]], list[dict[int, int]]]:
    pal_freq: dict[int, Counter[int]] = defaultdict(Counter)
    for colors, pal_id in zip(tile_colors, tile_pal_ids):
        pal_freq[pal_id].update(colors)

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


def read_frame_tiles(
    img_path: str,
    frame_w: int,
    frame_h: int,
    frame_count: int | None,
) -> tuple[int, int, list[tuple[int, ...]], list[frozenset[int]], list[dict[str, int]]]:
    img = Image.open(img_path).convert("RGBA")
    w, h = img.size
    if (frame_w % 8) or (frame_h % 8):
        raise ValueError("Frame size must be multiple of 8.")
    if frame_w <= 0 or frame_h <= 0:
        raise ValueError("Frame size must be > 0.")
    if frame_w > MSPR_MAX_OFFSET_DIM or frame_h > MSPR_MAX_OFFSET_DIM:
        raise ValueError(
            "Frame size must be <= %d px (MsprPart offsets are s8)." % MSPR_MAX_OFFSET_DIM
        )
    if (w % frame_w) or (h % frame_h):
        raise ValueError("Image size %dx%d must be multiple of frame size %dx%d." % (w, h, frame_w, frame_h))

    px = img.load()
    frames_x = w // frame_w
    frames_y = h // frame_h
    total_frames = frames_x * frames_y
    if frame_count is None:
        use_frames = total_frames
    else:
        if frame_count < 1 or frame_count > total_frames:
            raise ValueError("frame-count must be in range 1..%d" % total_frames)
        use_frames = frame_count

    tile_colors: list[tuple[int, ...]] = []
    tile_sets: list[frozenset[int]] = []
    tile_meta: list[dict[str, int]] = []

    frame_index = 0
    for fy in range(frames_y):
        for fx in range(frames_x):
            if frame_index >= use_frames:
                break
            origin_x = fx * frame_w
            origin_y = fy * frame_h
            tiles_x = frame_w // 8
            tiles_y = frame_h // 8

            for ty in range(tiles_y):
                for tx in range(tiles_x):
                    colors: list[int] = []
                    for py in range(8):
                        sy = origin_y + ty * 8 + py
                        for px0 in range(8):
                            sx = origin_x + tx * 8 + px0
                            colors.append(rgba_to_rgb444(px[sx, sy]))

                    # Skip fully transparent tiles.
                    if all(c == 0 for c in colors):
                        continue

                    cset = frozenset(colors)
                    visible = set(cset)
                    if 0 in visible:
                        visible.remove(0)
                    if len(visible) > 3:
                        raise ValueError(
                            "Frame %d tile (%d,%d) uses %d visible colors (>3). "
                            "Template pipeline reserves index 0 for transparency." % (
                                frame_index, tx, ty, len(visible)
                            )
                        )
                    tile_colors.append(tuple(colors))
                    tile_sets.append(cset)
                    tile_meta.append(
                        {
                            "frame": frame_index,
                            "ox": tx * 8,
                            "oy": ty * 8,
                        }
                    )
            frame_index += 1
        if frame_index >= use_frames:
            break

    return use_frames, frame_w, tile_colors, tile_sets, tile_meta


def format_c_source(
    name: str,
    frame_count: int,
    frame_w: int,
    frame_h: int,
    tile_base: int,
    pal_base: int,
    anim_duration: int,
    palette_colors: list[list[int]],
    unique_tiles: list[tuple[int, ...]],
    frame_parts: list[list[tuple[int, int, int, int]]],
    layer1_frame_parts: "list[list[tuple[int, int, int, int]]] | None" = None,
) -> str:
    lines: list[str] = []
    tile_words = [w for t in unique_tiles for w in t]
    pal_words = [(0 if c == OPAQUE_BLACK else c) for p in palette_colors for c in p]

    lines.append("/* Generated by ngpc_sprite_export.py - do not edit */")
    lines.append("")
    lines.append('#include "ngpc_types.h"')
    lines.append('#include "ngpc_metasprite.h"')
    lines.append("")
    lines.append("/* Runtime note: call ngpc_mspr_draw(..., SPR_FRONT|optional flips). */")
    lines.append("")
    lines.append("const u16 %s_tiles_count = %du;" % (name, len(tile_words)))
    lines.append("const u16 %s_tiles[] = {" % name)
    lines.extend(_fmt_u16_rows(tile_words))
    lines.append("};")
    lines.append("")
    lines.append("const u8 %s_palette_count = %du;" % (name, len(palette_colors)))
    lines.append("const u16 %s_palettes[] = {" % name)
    lines.extend(_fmt_u16_rows(pal_words))
    lines.append("};")
    lines.append("")
    lines.append("const u8 %s_pal_base = %du;" % (name, pal_base))
    lines.append("")
    lines.append("const u16 %s_tile_base = %du;" % (name, tile_base))
    lines.append("")

    for fi in range(frame_count):
        parts = frame_parts[fi]
        lines.append("const NgpcMetasprite %s_frame_%d = {" % (name, fi))
        lines.append("    %du, %du, %du," % (len(parts), frame_w, frame_h))
        lines.append("    {")
        if not parts:
            lines.append("        { 0, 0, 0, 0, 0 }")
        for i, (ox, oy, tile_id, pal_id) in enumerate(parts):
            tail = "," if (i + 1) < len(parts) else ""
            lines.append(
                "        { %d, %d, %d, %d, 0 }%s" % (ox, oy, tile_id, pal_id, tail)
            )
        lines.append("    }")
        lines.append("};")
        lines.append("")

    lines.append("const MsprAnimFrame %s_anim[] = {" % name)
    for fi in range(frame_count):
        tail = "," if (fi + 1) < frame_count else ""
        lines.append("    { &%s_frame_%d, %d }%s" % (name, fi, anim_duration, tail))
    lines.append("};")
    lines.append("")
    lines.append("const u8 %s_anim_count = %du;" % (name, frame_count))
    lines.append("")

    # Layer1 (overlay) — only emitted when --layer2 produces a second palette
    if layer1_frame_parts is not None:
        for fi in range(frame_count):
            parts = layer1_frame_parts[fi]
            lines.append("const NgpcMetasprite %s_layer1_frame_%d = {" % (name, fi))
            lines.append("    %du, %du, %du," % (len(parts), frame_w, frame_h))
            lines.append("    {")
            if not parts:
                lines.append("        { 0, 0, 0, 0, 0 }")
            for i, (ox, oy, tile_id, pal_id) in enumerate(parts):
                tail = "," if (i + 1) < len(parts) else ""
                lines.append(
                    "        { %d, %d, %d, %d, 0 }%s" % (ox, oy, tile_id, pal_id, tail)
                )
            lines.append("    }")
            lines.append("};")
            lines.append("")
        lines.append("const MsprAnimFrame %s_layer1_anim[] = {" % name)
        for fi in range(frame_count):
            tail = "," if (fi + 1) < frame_count else ""
            lines.append("    { &%s_layer1_frame_%d, %d }%s" % (name, fi, anim_duration, tail))
        lines.append("};")
        lines.append("")
        lines.append("const u8 %s_layer1_anim_count = %du;" % (name, frame_count))
        lines.append("")

    return "\n".join(lines)


def format_c_header(name: str, frame_count: int, has_layer1: bool = False) -> str:
    guard = (name + "_MSPR_H").upper()
    lines: list[str] = []
    lines.append("/* Generated by ngpc_sprite_export.py - do not edit */")
    lines.append("")
    lines.append("#ifndef %s" % guard)
    lines.append("#define %s" % guard)
    lines.append("")
    lines.append('#include "ngpc_types.h"')
    lines.append('#include "ngpc_metasprite.h"')
    lines.append("")
    lines.append("extern const u16 %s_tiles_count;" % name)
    lines.append("extern const u16 NGP_FAR %s_tiles[];" % name)
    lines.append("")
    lines.append("extern const u8 %s_palette_count;" % name)
    lines.append("extern const u16 NGP_FAR %s_palettes[];" % name)
    lines.append("extern const u8 %s_pal_base;" % name)
    lines.append("extern const u16 %s_tile_base;" % name)
    lines.append("")
    for fi in range(frame_count):
        lines.append("extern const NgpcMetasprite %s_frame_%d;" % (name, fi))
    lines.append("")
    lines.append("extern const MsprAnimFrame %s_anim[];" % name)
    lines.append("extern const u8 %s_anim_count;" % name)
    if has_layer1:
        lines.append("")
        lines.append("/* Dual-layer auto-split: draw %s_layer1_anim at the same position after %s_anim */" % (name, name))
        lines.append("#define %s_HAS_LAYER1 1" % name.upper())
        lines.append("")
        for fi in range(frame_count):
            lines.append("extern const NgpcMetasprite %s_layer1_frame_%d;" % (name, fi))
        lines.append("")
        lines.append("extern const MsprAnimFrame %s_layer1_anim[];" % name)
        lines.append("extern const u8 %s_layer1_anim_count;" % name)
    lines.append("")
    lines.append("#endif /* %s */" % guard)
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="Export spritesheet PNG to NGPC metasprite C data")
    p.add_argument("input", help="Input spritesheet PNG")
    p.add_argument("--layer2", default=None, help="Optional overlay spritesheet PNG (same frame layout as input)")
    p.add_argument("-o", "--output", required=True, help="Output .c file")
    p.add_argument("-n", "--name", default=None, help="Base C symbol name (default: from input)")
    p.add_argument("--frame-w", type=int, required=True, help="Frame width in pixels (multiple of 8)")
    p.add_argument("--frame-h", type=int, required=True, help="Frame height in pixels (multiple of 8)")
    p.add_argument("--frame-count", type=int, default=None, help="Number of frames to export (row-major)")
    p.add_argument("--tile-base", type=int, default=0, help="Tile base index used in generated metasprites")
    p.add_argument("--pal-base", type=int, default=0, help="Palette base index used in generated metasprites (0-15)")
    p.add_argument("--anim-duration", type=int, default=6, help="Default frame duration in output animation table")
    p.add_argument("--max-palettes", type=int, default=16, help="Maximum palette count (1..16)")
    p.add_argument(
        "--fixed-palette",
        default=None,
        help="Force a single palette. Provide 4 comma-separated RGB444 hex words (e.g. 0000,0657,044F,0112).",
    )
    p.add_argument("--no-dedupe", action="store_true", help="Disable tile deduplication")
    p.add_argument(
        "--tiles-bin",
        default=None,
        help="Optional raw tile dump (.bin, little-endian u16 words) for compression pipeline",
    )
    p.add_argument("--header", action="store_true", help="Generate matching .h file")
    args = p.parse_args()

    if args.tile_base < 0 or args.tile_base > 511:
        print("Error: --tile-base must be in range 0..511", file=sys.stderr)
        return 2
    if args.pal_base < 0 or args.pal_base > 15:
        print("Error: --pal-base must be in range 0..15", file=sys.stderr)
        return 2
    if args.anim_duration < 1 or args.anim_duration > 255:
        print("Error: --anim-duration must be in range 1..255", file=sys.stderr)
        return 2
    if args.max_palettes < 1 or args.max_palettes > 16:
        print("Error: --max-palettes must be in range 1..16", file=sys.stderr)
        return 2

    try:
        frame_count, frame_w, tile_colors, tile_sets, tile_meta = read_frame_tiles(
            args.input, args.frame_w, args.frame_h, args.frame_count
        )
        if args.layer2:
            layer2_count, layer2_frame_w, layer2_colors, layer2_sets, layer2_meta = read_frame_tiles(
                args.layer2, args.frame_w, args.frame_h, args.frame_count
            )
            if layer2_count != frame_count:
                raise ValueError(
                    "Layer2 frame count (%d) must match base frame count (%d)." % (
                        layer2_count, frame_count
                    )
                )
            if layer2_frame_w != frame_w:
                raise ValueError(
                    "Layer2 frame width (%d) must match base frame width (%d)." % (
                        layer2_frame_w, frame_w
                    )
                )
            tile_colors.extend(layer2_colors)
            tile_sets.extend(layer2_sets)
            tile_meta.extend(layer2_meta)
        if not tile_colors:
            raise ValueError("No visible sprite tiles found (all transparent?).")

        if args.fixed_palette:
            parts = [s.strip() for s in str(args.fixed_palette).split(",") if s.strip()]
            if len(parts) != 4:
                raise ValueError("--fixed-palette must have exactly 4 entries.")
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
            if args.pal_base + 1 > 16:
                raise ValueError("Palette overflow: pal-base(%d) + palettes(1) > 16." % args.pal_base)
        else:
            palettes, tile_pal_ids = assign_palettes(tile_sets, args.max_palettes)
            palette_colors, palette_idx_maps = build_palette_index_maps(palettes, tile_colors, tile_pal_ids)
            if args.pal_base + len(palette_colors) > 16:
                raise ValueError(
                    "Palette overflow: pal-base(%d) + palettes(%d) > 16. Reduce palettes or change pal-base."
                    % (args.pal_base, len(palette_colors))
                )

        frame_parts: list[list[tuple[int, int, int, int]]] = [[] for _ in range(frame_count)]
        unique_tiles: list[tuple[int, ...]] = []
        tile_to_index: dict[tuple[int, ...], int] = {}

        for colors, meta, pal_id in zip(tile_colors, tile_meta, tile_pal_ids):
            idx_map = palette_idx_maps[pal_id]
            if args.fixed_palette:
                missing = [c for c in set(colors) if c not in idx_map]
                if missing:
                    raise ValueError(
                        "Tile uses colors not in --fixed-palette: %s"
                        % ", ".join("0x%04X" % c for c in sorted(missing))
                    )
            indices = [idx_map[c] for c in colors]
            words = tile_words_from_indices(indices)

            if args.no_dedupe:
                tile_idx = len(unique_tiles)
                unique_tiles.append(words)
            else:
                tile_idx = tile_to_index.get(words, -1)
                if tile_idx < 0:
                    tile_idx = len(unique_tiles)
                    unique_tiles.append(words)
                    tile_to_index[words] = tile_idx

            final_tile_id = args.tile_base + tile_idx
            if final_tile_id > 511:
                raise ValueError("Tile index overflow (>511). Reduce tiles or tile-base.")

            frame_parts[meta["frame"]].append(
                (meta["ox"], meta["oy"], final_tile_id, args.pal_base + pal_id)
            )

        for fi, parts in enumerate(frame_parts):
            if len(parts) > MSPR_MAX_PARTS:
                raise ValueError(
                    "Frame %d has %d visible tiles (> %d). Reduce frame size/content." % (
                        fi, len(parts), MSPR_MAX_PARTS
                    )
                )

    except Exception as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 1

    if args.name:
        base_name = sanitize_c_identifier(args.name)
    else:
        base_name = sanitize_c_identifier(os.path.splitext(os.path.basename(args.input))[0])

    # When --layer2 produced a second palette, split frame_parts into base (pal 0)
    # and overlay (pal 1+) so the engine autorun can render each layer separately.
    layer1_frame_parts = None
    base_frame_parts = frame_parts
    if args.layer2 and len(palette_colors) > 1:
        base_frame_parts = [
            [(ox, oy, tid, pid) for (ox, oy, tid, pid) in parts if pid == args.pal_base]
            for parts in frame_parts
        ]
        layer1_parts = [
            [(ox, oy, tid, pid) for (ox, oy, tid, pid) in parts if pid != args.pal_base]
            for parts in frame_parts
        ]
        # Only emit layer1 if at least one frame has overlay tiles
        if any(layer1_parts):
            layer1_frame_parts = layer1_parts

    c_src = format_c_source(
        base_name,
        frame_count,
        frame_w,
        args.frame_h,
        args.tile_base,
        args.pal_base,
        args.anim_duration,
        palette_colors,
        unique_tiles,
        base_frame_parts,
        layer1_frame_parts=layer1_frame_parts,
    )
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(c_src)

    if args.tiles_bin:
        write_tiles_bin(args.tiles_bin, unique_tiles)

    if args.header:
        h_path = os.path.splitext(args.output)[0] + ".h"
        with open(h_path, "w", encoding="utf-8") as f:
            f.write(format_c_header(base_name, frame_count, has_layer1=(layer1_frame_parts is not None)))
        print("Header:    %s" % h_path)
    if args.tiles_bin:
        print("Tiles bin: %s" % args.tiles_bin)

    print("Input:     %s" % args.input)
    print("Frames:    %d (%dx%d px each)" % (frame_count, args.frame_w, args.frame_h))
    print("Palettes:  %d" % len(palette_colors))
    print("Tiles:     %d unique (dedupe=%s)" % (len(unique_tiles), "off" if args.no_dedupe else "on"))
    print("Output:    %s (symbols: %s_*)" % (args.output, base_name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
