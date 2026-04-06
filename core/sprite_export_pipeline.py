"""
core/sprite_export_pipeline.py - Shared sprite export helpers with auto-split fallback.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core.layer_split import split_layers
from core.project_model import sprite_export_stats, sprite_tile_estimate
from core.sprite_export_cli import run_sprite_export
from core.sprite_loader import load_sprite


@dataclass
class SpriteExportPipelineResult:
    returncode: int
    tile_slots: int
    palette_slots: int
    output_c: Path
    auto_split_used: bool
    detail: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


_RE_TILES_COUNT = re.compile(r"const\s+u16\s+(?P<name>[A-Za-z0-9_]+)_tiles_count\s*=\s*(?P<count>\d+)u\s*;")
_RE_PAL_COUNT = re.compile(r"const\s+u8\s+(?P<name>[A-Za-z0-9_]+)_palette_count\s*=\s*(?P<count>\d+)u\s*;")
_RE_OVERCOLOR = re.compile(r"uses\s+\d+\s+visible\s+colors\s+\(>3\)", re.IGNORECASE)


def _safe_sprite_name(name: str, fallback: str) -> str:
    raw = (name or "").strip() or (fallback or "").strip()
    raw = re.sub(r"[^a-zA-Z0-9_]+", "_", raw).strip("_")
    return raw or "sprite"


def _parse_export_counts(out_c: Path, safe_name: str) -> tuple[int | None, int | None]:
    try:
        text = out_c.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None, None

    tile_slots = None
    palette_slots = None

    for match in _RE_TILES_COUNT.finditer(text):
        if match.group("name") == safe_name:
            try:
                tile_words = int(match.group("count"))
                tile_slots = max(0, (tile_words + 7) // 8)
            except Exception:
                tile_slots = None
            break

    for match in _RE_PAL_COUNT.finditer(text):
        if match.group("name") == safe_name:
            try:
                palette_slots = max(0, int(match.group("count")))
            except Exception:
                palette_slots = None
            break

    return tile_slots, palette_slots


def _result_detail(returncode: int, text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if lines:
        return lines[0]
    return f"code {returncode}"


def _looks_like_overcolor_failure(text: str) -> bool:
    return bool(_RE_OVERCOLOR.search(text or ""))


def _normalize_fixed_palette(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def export_sprite_pipeline(
    *,
    script: Path,
    source_path: Path,
    out_dir: Path,
    name: str,
    frame_w: int,
    frame_h: int,
    frame_count: int,
    project_dir: Path | None,
    tile_base: int | None = None,
    pal_base: int | None = None,
    fixed_palette: str | None = None,
    output_c: Path | None = None,
    timeout_s: int = 30,
) -> SpriteExportPipelineResult:
    safe_name = _safe_sprite_name(name, source_path.stem)
    fc_use = None if int(frame_count) <= 0 else int(frame_count)
    estimate_tiles, estimate_pals, _ = (
        sprite_export_stats(project_dir, source_path, int(frame_w), int(frame_h), fc_use, str(fixed_palette or ""))
        if source_path.exists()
        else (sprite_tile_estimate({"frame_w": frame_w, "frame_h": frame_h, "frame_count": frame_count}), 1, True)
    )

    data = load_sprite(source_path)
    out_c = Path(output_c) if output_c else (Path(out_dir) / f"{safe_name}_mspr.c")
    auto_split_used = False

    with tempfile.TemporaryDirectory(prefix="ngpc_pngmgr_") as tmp_dir:
        tmp_root = Path(tmp_dir)
        tmp_png = tmp_root / f"{safe_name}__tmp.png"
        data.hw.save(str(tmp_png))

        res, out_c = run_sprite_export(
            script=Path(script),
            input_png=tmp_png,
            out_dir=Path(out_dir),
            name=safe_name,
            frame_w=int(frame_w),
            frame_h=int(frame_h),
            frame_count=int(frame_count),
            tile_base=tile_base,
            pal_base=pal_base,
            fixed_palette=_normalize_fixed_palette(fixed_palette),
            output_c=out_c,
            header=True,
            timeout_s=int(timeout_s),
        )
        text = ((res.stderr or "") + "\n" + (res.stdout or "")).strip()

        if res.returncode != 0 and _looks_like_overcolor_failure(text):
            split = split_layers(data.hw)
            if split.n_layers_needed == 2 and len(split.layers) >= 2:
                tmp_base = tmp_root / f"{safe_name}__layer0.png"
                tmp_overlay = tmp_root / f"{safe_name}__layer1.png"
                split.layers[0].image.save(str(tmp_base))
                split.layers[1].image.save(str(tmp_overlay))
                res, out_c = run_sprite_export(
                    script=Path(script),
                    input_png=tmp_base,
                    layer2_png=tmp_overlay,
                    out_dir=Path(out_dir),
                    name=safe_name,
                    frame_w=int(frame_w),
                    frame_h=int(frame_h),
                    frame_count=int(frame_count),
                    tile_base=tile_base,
                    pal_base=pal_base,
                    fixed_palette=None,
                    output_c=out_c,
                    header=True,
                    timeout_s=int(timeout_s),
                )
                text = ((res.stderr or "") + "\n" + (res.stdout or "")).strip()
                auto_split_used = res.returncode == 0
            elif split.n_layers_needed > 2:
                text = (
                    f"Error: Sprite needs {split.n_layers_needed} layers after auto-split; "
                    "current exporter fallback supports up to 2 layers."
                )

    tile_slots = int(estimate_tiles)
    palette_slots = int(estimate_pals)
    if res.returncode == 0:
        parsed_tiles, parsed_pals = _parse_export_counts(out_c, safe_name)
        if parsed_tiles is not None:
            tile_slots = int(parsed_tiles)
        if parsed_pals is not None:
            palette_slots = int(parsed_pals)

    return SpriteExportPipelineResult(
        returncode=int(res.returncode),
        tile_slots=int(tile_slots),
        palette_slots=int(palette_slots),
        output_c=out_c,
        auto_split_used=bool(auto_split_used),
        detail=_result_detail(int(res.returncode), text),
    )
