"""
core/sprite_export_cli.py - Helpers to call ngpc_sprite_export.py robustly.

The NgpCraft_base_template version of ngpc_sprite_export.py requires:
  -o / --output  (output .c file)
and supports:
  --header       (generate matching .h next to the .c)

Some older variants may not support -o/--output. To keep backward compatibility,
we try the modern CLI first, and if it fails with an "unrecognized arguments"
error mentioning -o/--output, we retry without -o/--header.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def _safe_base_name(name: str, fallback: str) -> str:
    """
    Make a safe base name for output files and --name.

    Keep letters/digits/underscore, collapse everything else to underscore.
    """
    raw = (name or "").strip()
    if not raw:
        raw = (fallback or "").strip()
    raw = re.sub(r"[^a-zA-Z0-9_]+", "_", raw).strip("_")
    return raw or "sprite"


def _looks_like_unrecognized_args(err_text: str) -> bool:
    t = (err_text or "").lower()
    return ("unrecognized arguments" in t) or ("unknown option" in t)


def _mentions_output_flag(err_text: str) -> bool:
    t = (err_text or "").lower()
    return ("-o" in t) or ("--output" in t)


def run_sprite_export(
    *,
    script: Path,
    input_png: Path,
    layer2_png: Path | None = None,
    out_dir: Path,
    name: str,
    frame_w: int,
    frame_h: int,
    frame_count: int,
    tile_base: int | None = None,
    pal_base: int | None = None,
    fixed_palette: str | None = None,
    output_c: Path | None = None,
    header: bool = True,
    timeout_s: int = 30,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """
    Run ngpc_sprite_export.py and return (CompletedProcess, expected_output_c_path).

    Note: the function returns an "expected" output path. In GUI mode we do not
    strictly verify file creation here (the exporter prints errors to stdout/stderr).
    """
    script = Path(script)
    input_png = Path(input_png)
    out_dir = Path(out_dir)

    safe_name = _safe_base_name(name, input_png.stem)
    out_c = Path(output_c) if output_c else (out_dir / f"{safe_name}_mspr.c")

    base_cmd = [
        sys.executable,
        str(script),
        str(input_png),
        "--name",
        safe_name,
        "--frame-w",
        str(int(frame_w)),
        "--frame-h",
        str(int(frame_h)),
        "--frame-count",
        str(int(frame_count)),
    ]
    if layer2_png is not None:
        base_cmd += ["--layer2", str(Path(layer2_png))]
    if tile_base is not None:
        base_cmd += ["--tile-base", str(int(tile_base))]
    if pal_base is not None:
        base_cmd += ["--pal-base", str(int(pal_base))]
    if fixed_palette:
        base_cmd += ["--fixed-palette", str(fixed_palette)]

    cmd = base_cmd + ["-o", str(out_c)]
    if header:
        cmd.append("--header")

    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(out_dir),
        timeout=int(timeout_s),
    )

    # Backward compat: retry without -o/--header if this script doesn't support them.
    if res.returncode != 0 and _looks_like_unrecognized_args((res.stderr or "") + "\n" + (res.stdout or "")):
        if _mentions_output_flag((res.stderr or "") + "\n" + (res.stdout or "")):
            res = subprocess.run(
                base_cmd,
                capture_output=True,
                text=True,
                cwd=str(out_dir),
                timeout=int(timeout_s),
            )

    return res, out_c
