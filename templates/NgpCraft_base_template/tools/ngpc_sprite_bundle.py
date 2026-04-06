"""
ngpc_sprite_bundle.py - generic sprite batch-export helper for NGPC projects.

Provides the SpriteBundle class and utility functions to sequence multiple
ngpc_sprite_export.py calls while automatically tracking tile/palette VRAM
allocation and checking for overflow.

Typical usage in a game-specific export script:

    from pathlib import Path
    from ngpc_sprite_bundle import SpriteBundle, load_rgba, make_sheet, split_two_layers

    project_root = Path(__file__).resolve().parent.parent
    bundle = SpriteBundle(
        project_root=project_root,
        out_dir=project_root / "GraphX",
        gen_dir=project_root / "GraphX" / "_gen",
        tile_base=256,   # 0-31 reserved, 32-127 sysfont, 128+ user
        pal_base=0,
    )

    # Export a single static sprite
    sheet = bundle.gen_dir / "player_sheet.png"
    make_sheet([load_rgba(src / "player.png")], 16, 16, sheet)
    bundle.export("player", sheet, 16, 16, frame_count=1)

    # Export an animated sprite
    sheet = bundle.gen_dir / "explosion_sheet.png"
    make_sheet([load_rgba(src / f"exp_{i}.png") for i in range(3)], 8, 8, sheet)
    bundle.export("explosion", sheet, 8, 8, anim_duration=3)

    # Reuse an existing palette slot (saves palette slots)
    saved_pal = bundle.pal_base
    bundle.export("rock_a", rock_a_sheet, 16, 16)
    bundle.export_reuse_palette("rock_b", rock_b_sheet, 16, 16, shared_pal_base=saved_pal)

    # Force a known 4-word RGB444 palette read back from an earlier export
    pal4 = bundle.read_palette(project_root / "GraphX" / "player_mspr.c", "player")
    bundle.export_reuse_palette("hat", hat_sheet, 8, 8, shared_pal_base=0, fixed_palette=pal4)

    print(f"Done. next tile_base={bundle.tile_base}, pal_base={bundle.pal_base}")
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


# ---------------------------------------------------------------------------
# Image utilities
# ---------------------------------------------------------------------------

def load_rgba(path: Path) -> Image.Image:
    """Open an image and return it as RGBA."""
    return Image.open(path).convert("RGBA")


def pad_center(img: Image.Image, w: int, h: int) -> Image.Image:
    """Paste img centered in a transparent w×h canvas."""
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ox = (w - img.size[0]) // 2
    oy = (h - img.size[1]) // 2
    out.paste(img, (ox, oy), img)
    return out


def make_sheet(frames: list[Image.Image], frame_w: int, frame_h: int, out_path: Path) -> None:
    """Pack frames into a horizontal sprite sheet (PNG). Frames are centered in each cell."""
    padded = [pad_center(f, frame_w, frame_h) for f in frames]
    sheet = Image.new("RGBA", (frame_w * len(padded), frame_h), (0, 0, 0, 0))
    for i, f in enumerate(padded):
        sheet.paste(f, (i * frame_w, 0), f)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)


def make_sheet_from_files(paths: list[Path], frame_w: int, frame_h: int, out_path: Path) -> None:
    """Load PNGs from paths and write a horizontal sprite sheet."""
    make_sheet([load_rgba(p) for p in paths], frame_w, frame_h, out_path)


def split_two_layers(
    frames: list[Image.Image], frame_w: int, frame_h: int
) -> tuple[list[Image.Image], list[Image.Image]]:
    """
    Split frames that use up to 6 opaque colors into two layers (A + B) of ≤3 colors each.

    Layer A gets the 3 most-frequent colors; layer B gets the rest.
    Useful when NGPC sprite palettes only allow 3 opaque colors per palette entry
    and a character needs 6 colors total.

    Raises SystemExit if the sprite uses more than 6 opaque colors.
    """
    freq: dict[tuple[int, int, int], int] = {}
    padded: list[Image.Image] = []
    for f in frames:
        pf = pad_center(f, frame_w, frame_h)
        padded.append(pf)
        for r, g, b, a in pf.getdata():
            if a < 128:
                continue
            key = (r, g, b)
            freq[key] = freq.get(key, 0) + 1

    ordered = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    colors = [c for c, _ in ordered]
    if len(colors) > 6:
        raise SystemExit(
            f"Sprite uses {len(colors)} opaque colors (>6). Reduce colors or split manually."
        )

    keep_a = set(colors[:3])

    layer_a: list[Image.Image] = []
    layer_b: list[Image.Image] = []
    for pf in padded:
        aimg = Image.new("RGBA", (frame_w, frame_h), (0, 0, 0, 0))
        bimg = Image.new("RGBA", (frame_w, frame_h), (0, 0, 0, 0))
        src_px = pf.load()
        apx = aimg.load()
        bpx = bimg.load()
        for y in range(frame_h):
            for x in range(frame_w):
                r, g, b, aa = src_px[x, y]
                if aa < 128:
                    continue
                if (r, g, b) in keep_a:
                    apx[x, y] = (r, g, b, aa)
                else:
                    bpx[x, y] = (r, g, b, aa)
        layer_a.append(aimg)
        layer_b.append(bimg)

    return layer_a, layer_b


# ---------------------------------------------------------------------------
# Export result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExportResult:
    tiles_unique: int
    palettes: int


_RE_TILES = re.compile(r"^Tiles:\s+(\d+)\s+unique\b")
_RE_PALS = re.compile(r"^Palettes:\s+(\d+)\b")


def _call_exporter(
    project_root: Path,
    exporter: Path,
    sheet_path: Path,
    out_c: Path,
    name: str,
    frame_w: int,
    frame_h: int,
    frame_count: int,
    anim_duration: int,
    tile_base: int,
    pal_base: int,
    fixed_palette: list[int] | None = None,
) -> ExportResult:
    """Invoke ngpc_sprite_export.py as a subprocess and parse its output."""
    cmd = [
        sys.executable,
        str(exporter),
        str(sheet_path),
        "-o", str(out_c),
        "-n", name,
        "--frame-w", str(frame_w),
        "--frame-h", str(frame_h),
        "--tile-base", str(tile_base),
        "--pal-base", str(pal_base),
        "--anim-duration", str(anim_duration),
        "--header",
    ]
    if fixed_palette is not None:
        if len(fixed_palette) != 4:
            raise ValueError("fixed_palette must have exactly 4 RGB444 u16 entries.")
        cmd += ["--fixed-palette", ",".join(f"0x{c:04X}" for c in fixed_palette)]
    if frame_count > 0:
        cmd += ["--frame-count", str(frame_count)]

    r = subprocess.run(cmd, cwd=str(project_root), capture_output=True, text=True, check=False)
    if r.returncode != 0:
        sys.stderr.write(r.stdout)
        sys.stderr.write(r.stderr)
        raise SystemExit(r.returncode)

    tiles_unique = 0
    palettes = 0
    for line in (r.stdout or "").splitlines():
        m = _RE_TILES.match(line.strip())
        if m:
            tiles_unique = int(m.group(1))
        m = _RE_PALS.match(line.strip())
        if m:
            palettes = int(m.group(1))

    if tiles_unique <= 0:
        raise RuntimeError("Failed to parse tile count from exporter output.")
    if palettes <= 0:
        raise RuntimeError("Failed to parse palette count from exporter output.")

    print(r.stdout.rstrip())
    return ExportResult(tiles_unique=tiles_unique, palettes=palettes)


# ---------------------------------------------------------------------------
# Palette reader (reads back palette words from a generated _mspr.c file)
# ---------------------------------------------------------------------------

def read_palette(mspr_c_path: Path, symbol: str) -> list[int]:
    """
    Read back the first 4 RGB444 palette words from a generated *_mspr.c file.

    Useful when you need to pass --fixed-palette to a second sprite that must
    share exactly the same palette as an already-exported sprite.
    """
    txt = mspr_c_path.read_text(encoding="utf-8", errors="replace")
    marker = f"const u16 {symbol}_palettes[]"
    start = txt.find(marker)
    if start < 0:
        raise RuntimeError(f"Cannot find '{marker}' in {mspr_c_path}")
    brace = txt.find("{", start)
    if brace < 0:
        raise RuntimeError(f"Cannot find palette initializer '{{' in {mspr_c_path}")
    after = txt[brace:]
    words: list[int] = []
    i = 0
    while i < len(after) and len(words) < 4:
        j = after.find("0x", i)
        if j < 0:
            break
        w = after[j + 2: j + 6]
        if len(w) == 4 and all(ch in "0123456789abcdefABCDEF" for ch in w):
            words.append(int(w, 16))
        i = j + 2
    if len(words) < 4:
        raise RuntimeError(f"Cannot parse 4 palette words from {mspr_c_path}")
    return words[:4]


# ---------------------------------------------------------------------------
# SpriteBundle class
# ---------------------------------------------------------------------------

class SpriteBundle:
    """
    Tracks VRAM tile/palette allocation across a sequence of sprite exports.

    Call export() for each sprite; bases are incremented automatically.
    Call export_reuse_palette() when a sprite is authored to use the same
    colors as an already-exported sprite (saves palette slots).

    Attributes:
        tile_base (int): Next free tile slot (updated after each export).
        pal_base  (int): Next free palette slot (updated after each export).
    """

    MAX_TILES = 512
    MAX_PALETTES = 16

    def __init__(
        self,
        project_root: Path,
        out_dir: Path,
        gen_dir: Path,
        exporter: Path | None = None,
        tile_base: int = 256,
        pal_base: int = 0,
    ) -> None:
        self.project_root = Path(project_root)
        self.out_dir = Path(out_dir)
        self.gen_dir = Path(gen_dir)
        self.exporter = (
            Path(exporter) if exporter
            else self.project_root / "tools" / "ngpc_sprite_export.py"
        )
        self.tile_base = tile_base
        self.pal_base = pal_base

    def export(
        self,
        name: str,
        sheet_path: Path,
        frame_w: int,
        frame_h: int,
        frame_count: int = 0,
        anim_duration: int = 6,
    ) -> ExportResult:
        """
        Export a sprite sheet and advance both tile_base and pal_base.

        Parameters:
            name          : C symbol base name for generated files.
            sheet_path    : Path to the PNG sprite sheet.
            frame_w/h     : Frame dimensions in pixels (multiples of 8).
            frame_count   : Number of frames to export (0 = all).
            anim_duration : Frames per animation step.
        """
        out_c = self.out_dir / f"{name}_mspr.c"
        res = _call_exporter(
            project_root=self.project_root,
            exporter=self.exporter,
            sheet_path=sheet_path,
            out_c=out_c,
            name=name,
            frame_w=frame_w,
            frame_h=frame_h,
            frame_count=frame_count,
            anim_duration=anim_duration,
            tile_base=self.tile_base,
            pal_base=self.pal_base,
        )
        self.tile_base += res.tiles_unique
        self.pal_base += res.palettes
        self._check_overflow(name)
        return res

    def export_reuse_palette(
        self,
        name: str,
        sheet_path: Path,
        frame_w: int,
        frame_h: int,
        shared_pal_base: int,
        frame_count: int = 0,
        anim_duration: int = 6,
        fixed_palette: list[int] | None = None,
    ) -> ExportResult:
        """
        Export a sprite sheet that shares an already-allocated palette slot.

        Only tile_base is advanced; pal_base is not changed.

        Parameters:
            shared_pal_base : The palette slot index to reuse (e.g. saved before
                              the first export that allocated it).
            fixed_palette   : Optional list of 4 RGB444 words to force-assign.
                              Use read_palette() to obtain this from an existing
                              *_mspr.c file.
        """
        out_c = self.out_dir / f"{name}_mspr.c"
        res = _call_exporter(
            project_root=self.project_root,
            exporter=self.exporter,
            sheet_path=sheet_path,
            out_c=out_c,
            name=name,
            frame_w=frame_w,
            frame_h=frame_h,
            frame_count=frame_count,
            anim_duration=anim_duration,
            tile_base=self.tile_base,
            pal_base=shared_pal_base,
            fixed_palette=fixed_palette,
        )
        self.tile_base += res.tiles_unique
        # Deliberately do not advance self.pal_base.
        if self.tile_base > self.MAX_TILES:
            raise SystemExit(
                f"[{name}] Tile overflow: tile_base={self.tile_base} > {self.MAX_TILES}."
            )
        return res

    def read_palette(self, mspr_c_path: Path, symbol: str) -> list[int]:
        """Shortcut for the module-level read_palette()."""
        return read_palette(mspr_c_path, symbol)

    def _check_overflow(self, name: str) -> None:
        if self.tile_base > self.MAX_TILES:
            raise SystemExit(
                f"[{name}] Tile overflow: tile_base={self.tile_base} > {self.MAX_TILES}."
            )
        if self.pal_base > self.MAX_PALETTES:
            raise SystemExit(
                f"[{name}] Palette overflow: pal_base={self.pal_base} > {self.MAX_PALETTES}."
            )
