"""
core/headless_export.py — Headless (no-GUI) export engine for NgpCraft Engine.

Called by ngpcraft_engine.py when the --export flag is used.
No PyQt6 dependency — pure subprocess + Pillow + file I/O.

Usage (via entry point):
    python ngpcraft_engine.py --export project.ngpcraft
    python ngpcraft_engine.py --export project.ngpcraft --scene acte1
    python ngpcraft_engine.py --export project.ngpcraft --sprite-tool /path/to/ngpc_sprite_export.py
    python ngpcraft_engine.py --export project.ngpcraft --tilemap-tool /path/to/ngpc_tilemap.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field


def _python_cmd(script: "Path | str") -> list:
    """Return the subprocess argv prefix to run a Python script.
    In a frozen PyInstaller exe sys.executable is the .exe itself — use
    the '--run-script' mode so the exe acts as its own Python runner.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--run-script", str(script)]
    return [sys.executable, str(script)]
from pathlib import Path
from typing import Callable

from core.hitbox_export import make_anims_h, make_ctrl_h, make_hitbox_h, make_props_h
from core.collision_boxes import sprite_hurtboxes
from core.assets_autogen_mk import write_assets_autogen_mk
from core.audio_autogen_mk import (
    project_uses_template_managed_audio,
    write_audio_autogen_mk,
    write_disabled_audio_autogen_mk,
)
from core.audio_manifest import load_audio_manifest
from core.entity_roles import scene_role_map, sprite_gameplay_role
from core.sfx_map_gen import write_sfx_map_h
from core.sfx_play_autogen import write_sfx_play_autogen_c
from core.save_detection import project_has_save_triggers
from core.scenes_autogen_gen import write_scenes_autogen
from core.project_model import sprite_tile_estimate
from core.scene_collision import fit_collision_grid, scene_with_export_collision, tilemap_collision_grid
from core.sprite_export_pipeline import export_sprite_pipeline
from core.sprite_loader import load_sprite
from core.export_validation import collect_export_pipeline_issues
from core.template_integration import _sync_validated_sprite_runtime


# ---------------------------------------------------------------------------
# Tool auto-discovery (no Qt / no QSettings)
# ---------------------------------------------------------------------------

def _find_tool_near(tool_name: str, project_dir: Path | None) -> Path | None:
    """Scan common candidate locations for a pipeline tool script."""
    candidates: list[Path] = []
    here = Path(__file__).resolve().parent.parent
    candidates += [
        here / "templates" / "NgpCraft_base_template" / "tools" / tool_name,
        here.parent / "NgpCraft_base_template" / "tools" / tool_name,
        here.parent.parent / "NgpCraft_base_template" / "tools" / tool_name,
        here / "tools" / tool_name,
        here / tool_name,
    ]
    if project_dir:
        candidates += [
            project_dir / "tools" / tool_name,
            project_dir.parent / "tools" / tool_name,
            project_dir.parent / "NgpCraft_base_template" / "tools" / tool_name,
            project_dir.parent.parent / "NgpCraft_base_template" / "tools" / tool_name,
        ]
    for p in candidates:
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# Export result accumulator
# ---------------------------------------------------------------------------

@dataclass
class ExportResult:
    """Accumulate export counts and human-readable errors for one run."""

    ok: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Return True when the export completed without recorded errors."""
        return not self.errors

    def print_summary(self) -> None:
        """Print a compact terminal summary of the export result."""
        status = "OK" if self.success else "FAIL"
        print(
            f"[{status}]  {self.ok} exported"
            f"  {self.skipped} skipped"
            f"  {len(self.errors)} error(s)"
        )
        for e in self.errors:
            print(f"  ERR: {e}")


_TCOL_PASS = 0
_TCOL_SOLID = 1
_TCOL_ONE_WAY = 2
_TCOL_DAMAGE = 3
_TCOL_LADDER = 4
_TCOL_WALL_N = 5
_TCOL_WALL_S = 6
_TCOL_WALL_E = 7
_TCOL_WALL_W = 8
_TCOL_WATER = 9
_TCOL_FIRE = 10
_TCOL_VOID = 11
_TCOL_DOOR = 12
_TCOL_STAIR_E = 13
_TCOL_STAIR_W = 14
_TCOL_SPRING = 15
_TCOL_ICE = 16
_TCOL_CONVEYOR_L = 17
_TCOL_CONVEYOR_R = 18

_TILECOL_LABELS: dict[int, str] = {
    _TCOL_PASS: "pass",
    _TCOL_SOLID: "solid",
    _TCOL_ONE_WAY: "one_way",
    _TCOL_DAMAGE: "damage",
    _TCOL_LADDER: "ladder",
    _TCOL_WALL_N: "wall_n",
    _TCOL_WALL_S: "wall_s",
    _TCOL_WALL_E: "wall_e",
    _TCOL_WALL_W: "wall_w",
    _TCOL_WATER: "water",
    _TCOL_FIRE: "fire",
    _TCOL_VOID: "void",
    _TCOL_DOOR: "door",
    _TCOL_STAIR_E: "stair_e",
    _TCOL_STAIR_W: "stair_w",
    _TCOL_SPRING: "spring",
    _TCOL_ICE: "ice",
    _TCOL_CONVEYOR_L: "conveyor_l",
    _TCOL_CONVEYOR_R: "conveyor_r",
}

_PERF_TILECOL_FRAME_BUDGET = 102400
_PERF_TILECOL_CYCLE_COST = 200


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _abs_path(base_dir: Path | None, rel: str) -> Path:
    p = Path(rel)
    if p.is_absolute():
        return p
    return (base_dir / p) if base_dir else p


def _scene_dims(scene: dict) -> tuple[int, int]:
    size = scene.get("level_size", {}) or {}
    map_w = int(size.get("w", scene.get("map_w", scene.get("grid_w", 20))) or 20)
    map_h = int(size.get("h", scene.get("map_h", scene.get("grid_h", 19))) or 19)
    return max(1, map_w), max(1, map_h)


def _norm_rel(path_value: str) -> str:
    return str(path_value or "").replace("\\", "/").strip()


def _scene_tilemap_entry_for_rel(scene: dict, rel: str) -> dict | None:
    rel_norm = _norm_rel(rel)
    rel_name = Path(rel_norm).name.lower()
    for tm in (scene.get("tilemaps") or []):
        if not isinstance(tm, dict):
            continue
        tm_rel = _norm_rel(str(tm.get("file") or ""))
        if not tm_rel:
            continue
        if tm_rel == rel_norm or Path(tm_rel).name.lower() == rel_name:
            return tm
    return None


def _resolve_scene_bg(scene: dict) -> tuple[str | None, str | None]:
    front = str(scene.get("level_bg_front", "scr1") or "scr1").strip().lower()
    ordered = [front, "scr2" if front == "scr1" else "scr1"]
    for plane in ordered:
        rel = str(scene.get(f"level_bg_{plane}", "") or "").strip()
        if rel:
            return plane, rel
    return None, None


def _extract_flat_col(scene: dict) -> tuple[list[int], int, int] | None:
    map_w, map_h = _scene_dims(scene)
    col_map = scene.get("col_map", None)
    if not isinstance(col_map, list) or not col_map:
        return None
    if len(col_map) != map_h or not all(isinstance(row, list) and len(row) == map_w for row in col_map):
        return None
    flat: list[int] = []
    for row in col_map:
        for value in row:
            try:
                flat.append(max(0, min(255, int(value))))
            except Exception:
                flat.append(_TCOL_PASS)
    return flat, map_w, map_h


def _extract_bg_tileset_flat(scene: dict, base_dir: Path | None) -> tuple[list[int], int, int] | None:
    _plane, rel = _resolve_scene_bg(scene)
    if not rel:
        return None
    tm = _scene_tilemap_entry_for_rel(scene, rel)
    if tm is None:
        return None
    mode = str(tm.get("collision_mode", "tileset") or "tileset").strip().lower()
    if mode == "paint":
        if not isinstance(tm.get("collision_paint"), list) or not (tm.get("collision_paint") or []):
            return None
    else:
        if not isinstance(tm.get("collision_tileset"), list) or not (tm.get("collision_tileset") or []):
            return None
    tm_path = Path(rel)
    if not tm_path.is_absolute() and base_dir is not None:
        tm_path = Path(base_dir) / tm_path
    if not tm_path.exists():
        return None
    map_w, map_h = _scene_dims(scene)
    try:
        grid = tilemap_collision_grid(tm, tm_path)
    except Exception:
        return None
    fitted = fit_collision_grid(grid, map_w, map_h)
    flat: list[int] = []
    for row in fitted:
        for value in row:
            flat.append(max(0, min(255, int(value))))
    return flat, map_w, map_h


def _fmt_tile_types(values: set[int]) -> str:
    parts: list[str] = []
    for value in sorted(values):
        parts.append(f"{_TILECOL_LABELS.get(int(value), 'tile')}({int(value)})")
    return ", ".join(parts)


def _log_collision_sync_warnings(scene: dict, base_dir: Path | None, log: Callable[[str], None]) -> None:
    actual = _extract_flat_col(scene)
    expected = _extract_bg_tileset_flat(scene, base_dir)
    if actual is None or expected is None:
        return

    actual_flat, _map_w, _map_h = actual
    expected_flat, _exp_w, _exp_h = expected
    if len(actual_flat) != len(expected_flat):
        return

    actual_types = {value for value in actual_flat if int(value) != _TCOL_PASS}
    expected_types = {value for value in expected_flat if int(value) != _TCOL_PASS}
    if actual_types == expected_types:
        return

    label = str(scene.get("label") or scene.get("id") or "scene")
    missing_from_colmap = expected_types - actual_types
    missing_from_tileset = actual_types - expected_types
    if missing_from_colmap:
        log(
            "  WARN  COLMAP sync "
            f"{label}: active BG collision metadata contains tile types absent from scene col_map: "
            f"{_fmt_tile_types(missing_from_colmap)}"
        )
    if missing_from_tileset:
        log(
            "  WARN  COLMAP sync "
            f"{label}: scene col_map contains tile types absent from active BG collision metadata: "
            f"{_fmt_tile_types(missing_from_tileset)}"
        )


def _sprite_meta_map(scene: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for spr in (scene.get("sprites") or []):
        if not isinstance(spr, dict):
            continue
        name = str(spr.get("name") or "").strip()
        if not name:
            rel = str(spr.get("file") or "").strip()
            name = Path(rel).stem if rel else ""
        if name:
            out[name] = spr
    return out


def _entity_has_gravity_enemy(ent: dict, *, roles: dict[str, str], sprite_meta: dict[str, dict]) -> bool:
    type_name = str(ent.get("type") or "").strip()
    if not type_name or str(roles.get(type_name, "prop") or "prop").strip().lower() != "enemy":
        return False
    meta = sprite_meta.get(type_name) or {}
    props = meta.get("props") if isinstance(meta.get("props"), dict) else {}
    try:
        return int(props.get("gravity", 0) or 0) > 0
    except Exception:
        return False


def _estimate_gravity_enemies(scene: dict) -> int:
    roles = scene_role_map(scene)
    sprite_meta = _sprite_meta_map(scene)

    static_count = sum(
        1
        for ent in (scene.get("entities") or [])
        if isinstance(ent, dict) and _entity_has_gravity_enemy(ent, roles=roles, sprite_meta=sprite_meta)
    )

    max_wave = 0
    for wave in (scene.get("waves") or []):
        if not isinstance(wave, dict):
            continue
        wave_count = sum(
            1
            for ent in (wave.get("entities") or [])
            if isinstance(ent, dict) and _entity_has_gravity_enemy(ent, roles=roles, sprite_meta=sprite_meta)
        )
        if wave_count > max_wave:
            max_wave = wave_count

    if static_count > 0 and max_wave > 0:
        return static_count + max_wave
    return max(static_count, max_wave)


def _log_tilecol_perf_estimate(scene: dict, log: Callable[[str], None]) -> None:
    extracted = _extract_flat_col(scene)
    if extracted is None:
        return

    flat_col, _map_w, _map_h = extracted
    gravity_enemies = _estimate_gravity_enemies(scene)
    n_damage = (
        flat_col.count(_TCOL_DAMAGE)
        + flat_col.count(_TCOL_FIRE)
        + flat_col.count(_TCOL_VOID)
    )
    n_spring = flat_col.count(_TCOL_SPRING)
    tilecol_est = gravity_enemies * 12 + (12 if n_spring > 0 else 0) + 20
    cycles_est = tilecol_est * _PERF_TILECOL_CYCLE_COST
    label = str(scene.get("label") or scene.get("id") or "scene")
    log(
        f"  [PERF] Scene '{label}': ~{tilecol_est} tilecol/frame estimated "
        f"(~{cycles_est} cycles, budget={_PERF_TILECOL_FRAME_BUDGET}, "
        f"gravity_enemies={gravity_enemies}, spring_tiles={n_spring}, deadly_tiles={n_damage})"
    )


def _write_hitbox_props(
    spr: dict,
    name: str,
    fw: int,
    fh: int,
    fc: int,
    out_dir: Path,
    errs: list[str],
) -> None:
    hitboxes = sprite_hurtboxes(spr, fw, fh)
    if hitboxes:
        try:
            text = make_hitbox_h(name, name, fw, fh, fc, hitboxes)
            (out_dir / f"{name}_hitbox.h").write_text(text, encoding="utf-8")
        except Exception as e:
            errs.append(f"{name}_hitbox.h: {e}")
    props = spr.get("props") or {}
    if props:
        try:
            text = make_props_h(name, name, fw, fh, fc, props)
            if text:
                (out_dir / f"{name}_props.h").write_text(text, encoding="utf-8")
        except Exception as e:
            errs.append(f"{name}_props.h: {e}")
    anims = spr.get("anims") or {}
    if anims:
        try:
            text = make_anims_h(name, name, anims)
            if text:
                (out_dir / f"{name}_anims.h").write_text(text, encoding="utf-8")
        except Exception as e:
            errs.append(f"{name}_anims.h: {e}")


def _write_ctrl_header(
    spr: dict,
    name: str,
    out_dir: Path,
    errs: list[str],
) -> None:
    ctrl = spr.get("ctrl") or {}
    role = sprite_gameplay_role(spr)
    if role != "player":
        return
    props = spr.get("props") or {}
    try:
        text = make_ctrl_h(name, name, ctrl, props, role=role)
        if text:
            (out_dir / f"{name}_ctrl.h").write_text(text, encoding="utf-8")
    except Exception as e:
        errs.append(f"{name}_ctrl.h: {e}")


def _export_sprite(
    spr: dict,
    base_dir: Path | None,
    script: Path,
    out_dir: Path | None,
    t_cursor: int,
    pal_base: int,
    result: ExportResult,
    log: Callable[[str], None],
) -> tuple[int, int]:
    """
    Export one sprite asset.
    Returns (tile_slots_used, pal_slots_used).
    """
    name = str(spr.get("name") or "")
    rel  = str(spr.get("file") or "").strip()
    path = _abs_path(base_dir, rel)
    fw   = int(spr.get("frame_w",    8) or 8)
    fh   = int(spr.get("frame_h",    8) or 8)
    fc   = int(spr.get("frame_count", 1) or 1)
    fc_use = None if fc <= 0 else fc
    fixed  = str(spr.get("fixed_palette") or "").strip()
    if not name:
        name = path.stem
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", name).strip("_") or "sprite"

    out_dir = Path(out_dir) if out_dir else path.parent
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    _write_ctrl_header(spr, name, out_dir, result.errors)

    if not path.exists():
        tiles = sprite_tile_estimate(spr)
        result.skipped += 1
        log(f"  SKIP  {name}  (missing: {rel})")
        return int(tiles), 1

    try:
        run = export_sprite_pipeline(
            script=Path(script),
            source_path=path,
            out_dir=out_dir,
            name=name,
            frame_w=fw,
            frame_h=fh,
            frame_count=fc,
            project_dir=base_dir,
            tile_base=int(t_cursor),
            pal_base=int(pal_base),
            fixed_palette=fixed or None,
            output_c=(out_dir / f"{name}_mspr.c"),
            timeout_s=30,
        )
        if run.ok:
            split_note = "  auto-split=2" if run.auto_split_used else ""
            log(
                f"  OK    {name}{split_note}"
                f"  tiles={t_cursor}..{t_cursor + int(run.tile_slots) - 1}"
                f"  pal={pal_base}"
            )
            result.ok += 1
            _write_hitbox_props(spr, name, fw, fh, fc, out_dir, result.errors)
        else:
            result.errors.append(f"{name}: {run.detail}")
            log(f"  ERR   {name}: {run.detail}")

        return int(run.tile_slots), int(run.palette_slots)

    except Exception as e:
        result.errors.append(f"{name}: {e}")
        log(f"  ERR   {name}: {e}")
        return int(sprite_tile_estimate(spr)), 1


def _export_tilemap(
    tm: dict,
    base_dir: Path | None,
    script: Path,
    out_dir: Path | None,
    result: ExportResult,
    log: Callable[[str], None],
) -> None:
    """Export one tilemap asset."""
    rel   = str(tm.get("file") or "").strip()
    if not rel:
        return
    path  = _abs_path(base_dir, rel)
    label = tm.get("name") or path.name

    if not path.exists():
        result.skipped += 1
        log(f"  SKIP  {label}  (missing: {rel})")
        return

    def _tilemap_export_paths(p: Path) -> tuple[Path, Path | None, Path]:
        from core.scene_loader_gen import _tilemap_symbol_base  # type: ignore

        stem_l = p.stem.lower()
        scr1 = p
        scr2: Path | None = None

        if stem_l.endswith("_scr1"):
            base = p.stem[:-5]
            cand = p.with_name(base + "_scr2" + p.suffix)
            if cand.exists():
                scr2 = cand
        elif stem_l.endswith("_scr2"):
            base = p.stem[:-5]
            cand1 = p.with_name(base + "_scr1" + p.suffix)
            if cand1.exists():
                scr1 = cand1
                scr2 = p
        else:
            cand1 = p.with_name(p.stem + "_scr1" + p.suffix)
            cand2 = p.with_name(p.stem + "_scr2" + p.suffix)
            if cand1.exists() and cand2.exists():
                scr1, scr2 = cand1, cand2
            else:
                cand = p.with_name(p.stem + "_scr2" + p.suffix)
                if cand.exists():
                    scr2 = cand

        out_base = _tilemap_symbol_base(scr1)
        _out_dir = Path(out_dir) if out_dir else scr1.parent
        try:
            _out_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        out_c = _out_dir / (out_base + "_map.c")
        return scr1, scr2, out_c

    try:
        scr1, scr2, out_c = _tilemap_export_paths(path)

        # Quick validation: tilemap PNGs must be multiples of 8 pixels.
        # (ngpc_tilemap.py will error too, but this gives a clear message here.)
        try:
            from PIL import Image
            w, h = Image.open(scr1).size
            if (w % 8) or (h % 8):
                pw = ((w + 7) // 8) * 8
                ph = ((h + 7) // 8) * 8
                log(f"  WARN  {label}: size {w}x{h} not a multiple of 8 — auto-padding to {pw}x{ph}")
            if scr2 is not None and scr2.exists():
                w2, h2 = Image.open(scr2).size
                if (w2 % 8) or (h2 % 8):
                    pw2 = ((w2 + 7) // 8) * 8
                    ph2 = ((h2 + 7) // 8) * 8
                    log(f"  WARN  {label}: SCR2 size {w2}x{h2} not a multiple of 8 — auto-padding to {pw2}x{ph2}")
        except Exception:
            # If PIL is unavailable or image load fails, defer to ngpc_tilemap.py.
            pass

        # If the PNG already has a matching C export next to it (same stem),
        # prefer reusing it instead of generating a duplicate <name>_map.c in export_dir.
        # This avoids linker "multiply defined" errors (e.g. template intro assets).
        existing_c = path.with_suffix(".c")
        existing_h = path.with_suffix(".h")
        try:
            if existing_c.is_file() and existing_h.is_file():
                if out_c.resolve() != existing_c.resolve():
                    log(f"  OK    {label}  (reuse existing: {existing_c.name})")
                    result.ok += 1
                    return
        except Exception:
            # If resolve fails for any reason, fall back to normal export.
            pass

        cmd = _python_cmd(script) + [str(scr1), "-o", str(out_c)]
        out_name = out_c.stem
        if out_name.lower().endswith("_map"):
            out_name = out_name[:-4]
        if out_name:
            cmd += ["-n", out_name]
        if scr2 is not None and scr2.exists():
            cmd += ["--scr2", str(scr2)]
        cmd += ["--header"]
        res = subprocess.run(
            cmd,
            capture_output=True, text=True,
            cwd=str(scr1.parent), timeout=60,
        )
        if res.returncode == 0:
            log(f"  OK    {label}")
            result.ok += 1
        else:
            lines = (res.stderr or res.stdout or "").strip().splitlines()
            detail = lines[0] if lines else f"code {res.returncode}"
            result.errors.append(f"{label}: {detail}")
            log(f"  ERR   {label}: {detail}")
    except Exception as e:
        result.errors.append(f"{label}: {e}")
        log(f"  ERR   {label}: {e}")


def _export_enabled(obj: dict) -> bool:
    return not (isinstance(obj, dict) and obj.get("export", True) is False)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def export_scene(
    scene: dict,
    project_data: dict,
    base_dir: Path | None,
    sprite_script: Path | None,
    tilemap_script: Path | None,
    log: Callable[[str], None] = print,
) -> ExportResult:
    """Export sprites + tilemaps for a single scene."""
    result = ExportResult()
    scene_export = scene_with_export_collision(scene, base_dir)

    bundle_cfg = (project_data.get("bundle") or {}) if isinstance(project_data, dict) else {}
    try:
        t_cursor = int(scene_export.get("spr_tile_base", bundle_cfg.get("tile_base", 256)))
    except Exception:
        t_cursor = int(bundle_cfg.get("tile_base", 256) or 256)
    try:
        p_cursor = int(scene_export.get("spr_pal_base", bundle_cfg.get("pal_base", 0)))
    except Exception:
        p_cursor = int(bundle_cfg.get("pal_base", 0) or 0)

    # Linux: normalise backslashes in export_dir paths stored on Windows
    export_dir_rel = str(project_data.get("export_dir") or "").replace("\\", "/").strip()
    export_dir_abs = (base_dir / export_dir_rel) if (base_dir and export_dir_rel) else None

    # --- Tilemaps ------------------------------------------------------
    tilemaps = [tm for tm in (scene_export.get("tilemaps") or []) if _export_enabled(tm)]
    if tilemap_script:
        for tm in tilemaps:
            _export_tilemap(tm, base_dir, tilemap_script, export_dir_abs, result, log)
    elif tilemaps:
        log("  WARN  ngpc_tilemap.py not found - tilemaps skipped")
        result.skipped += len(tilemaps)

    # --- Sprite base auto-bump (avoid tilemap overlap) ----------------
    tm_end = None
    try:
        from core.scene_loader_gen import _tilemap_symbol_base, _parse_tilemap_tile_slots_from_c  # type: ignore
        tilemap_cfg = (project_data.get("tilemap") or {}) if isinstance(project_data, dict) else {}
        try:
            tm_cursor = int(tilemap_cfg.get("tile_base", 128))
        except Exception:
            tm_cursor = 128

        if export_dir_abs and base_dir:
            for tm in tilemaps:
                if not isinstance(tm, dict):
                    continue
                rel = str(tm.get("file") or "").strip()
                if not rel:
                    continue
                tm_path = Path(rel)
                if not tm_path.is_absolute() and base_dir is not None:
                    tm_path = Path(base_dir) / tm_path

                sym_base = _tilemap_symbol_base(tm_path)
                out_c = export_dir_abs / f"{sym_base}_map.c"

                # Reuse existing exports next to the PNG when present.
                existing_c = tm_path.with_suffix('.c')
                existing_h = tm_path.with_suffix('.h')
                use_existing = bool(existing_c.is_file() and existing_h.is_file())
                c_src = existing_c if use_existing else out_c

                base_val = tm.get("tile_base", None)
                try:
                    tile_base = int(base_val) if base_val is not None else int(tm_cursor)
                except Exception:
                    tile_base = int(tm_cursor)

                if c_src.is_file():
                    c_text = c_src.read_text(encoding='utf-8', errors='replace')
                    slots_used = _parse_tilemap_tile_slots_from_c(c_text, sym_base)
                else:
                    slots_used = 0
                if slots_used is None:
                    slots_used = 0

                tm_cursor = int(tile_base) + int(slots_used)
                tm_end = tm_cursor if tm_end is None else max(int(tm_end), int(tm_cursor))
    except Exception:
        tm_end = None

    if tm_end is not None and int(t_cursor) < int(tm_end):
        log(f"  WARN  sprite tile_base bumped {t_cursor} -> {tm_end} (avoid tilemap overlap)")
        t_cursor = int(tm_end)

    # NOTE: stale *_mspr.* purge is done once in export_project() before the
    # scene loop so that multi-scene projects don't erase each other's sprites.

    sprites = [spr for spr in (scene_export.get("sprites") or []) if _export_enabled(spr)]
    if sprite_script:
        fixed_to_slot: dict[str, int] = {}
        for spr in sprites:
            fixed     = str(spr.get("fixed_palette") or "").strip()
            auto_share = bool(fixed) and fixed in fixed_to_slot
            pal_base  = fixed_to_slot[fixed] if auto_share else p_cursor

            tiles, pal_n = _export_sprite(
                spr, base_dir, sprite_script, export_dir_abs, t_cursor, pal_base, result, log
            )
            t_cursor += tiles

            if bool(fixed) and int(pal_n) == 1:
                if auto_share:
                    # Reuse existing palette slot for identical fixed_palette.
                    pass
                else:
                    fixed_to_slot[fixed] = int(pal_base)
                    p_cursor += int(pal_n)
            else:
                p_cursor += int(pal_n)
    elif sprites:
        log("  WARN  ngpc_sprite_export.py not found - sprites skipped")
        result.skipped += len(sprites)

    # --- Scene loader snippet (CT-7) ----------------------------------
    if export_dir_abs and base_dir:
        level_ok = True
        try:
            from core.scene_level_gen import write_scene_dialogs_h, write_scene_level_h
            lvl_h = write_scene_level_h(
                project_data=project_data,
                scene=scene_export,
                export_dir=export_dir_abs,
                project_dir=base_dir,
            )
            log(f"  OUT   {lvl_h.name}")
            dlg_h = write_scene_dialogs_h(
                scene=scene_export,
                export_dir=export_dir_abs,
            )
            if dlg_h is not None:
                log(f"  OUT   {dlg_h.name}")
        except Exception as e:
            level_ok = False
            label = str(scene.get("label") or scene.get("id") or "scene")
            msg = f"{label}: scene level: {e}"
            result.errors.append(msg)
            log(f"  ERR   {msg}")

        _log_collision_sync_warnings(scene_export, base_dir, log)
        _log_tilecol_perf_estimate(scene_export, log)

        # CT-8: standalone col_cells (.c/.h) for optional/ngpc_tilecol
        try:
            from core.scene_level_gen import write_scene_col_cells
            col_paths = write_scene_col_cells(scene=scene_export, export_dir=export_dir_abs)
            if col_paths is not None:
                log(f"  OUT   {col_paths[0].name}")
                log(f"  OUT   {col_paths[1].name}")
        except Exception as e:
            label = str(scene.get("label") or scene.get("id") or "scene")
            msg = f"{label}: col_cells: {e}"
            result.errors.append(msg)
            log(f"  ERR   {msg}")

        # Phase 3A: export large background map via ngpc_tilemap when map > 32×32
        try:
            _sz = (scene_export.get("level_size") or {})
            _map_w = int(_sz.get("w", 20) or 20)
            _map_h = int(_sz.get("h", 19) or 19)
            if (_map_w > 32 or _map_h > 32) and tilemap_script and export_dir_abs:
                _bg_rel = str(scene_export.get("level_bg_scr1") or "").strip()
                if _bg_rel:
                    from core.scene_level_gen import _safe_ident as _sl_safe
                    _sc_label = str(scene_export.get("label") or scene_export.get("id") or "scene")
                    _sc_sym = _sl_safe(_sc_label)
                    _bg_tm = {"file": _bg_rel, "name": f"scene_{_sc_sym}_bg_map"}
                    _export_tilemap(_bg_tm, base_dir, tilemap_script, export_dir_abs, result, log)
        except Exception as e:
            label = str(scene.get("label") or scene.get("id") or "scene")
            msg = f"{label}: large bg map: {e}"
            result.errors.append(msg)
            log(f"  ERR   {msg}")

        if level_ok:
            try:
                from core.scene_loader_gen import write_scene_loader_h
                loader_warns: list[str] = []
                out_h = write_scene_loader_h(
                    project_data=project_data,
                    scene=scene_export,
                    project_dir=base_dir,
                    export_dir=export_dir_abs,
                    base_dir=base_dir,
                    warnings_out=loader_warns,
                )
                log(f"  OUT   {out_h.name}")
                for msg in loader_warns:
                    result.errors.append(msg)
                    log(f"  WARN  {msg}")
            except Exception as e:
                label = str(scene.get("label") or scene.get("id") or "scene")
                msg = f"{label}: scene loader: {e}"
                result.errors.append(msg)
                log(f"  ERR   {msg}")
        else:
            label = str(scene.get("label") or scene.get("id") or "scene")
            msg = f"{label}: scene loader skipped because scene level export failed"
            result.errors.append(msg)
            log(f"  ERR   {msg}")

    # --- Tile budget report --------------------------------------------
    _TILE_USER_START = 128
    tiles_used = max(0, t_cursor - _TILE_USER_START)
    if tiles_used > 384:
        log(f"  WARN  BUDGET 🔴 {tiles_used}/384 tiles — VRAM dépassé, réduisez le tileset")
    elif tiles_used > 320:
        log(f"  WARN  BUDGET 🔶 {tiles_used}/384 tiles — limite critique")
    elif tiles_used > 256:
        log(f"  INFO  BUDGET ⚠  {tiles_used}/384 tiles — peu de marge pour les sprites")

    return result

def export_project(
    project_path: Path,
    scene_filter: str | None = None,
    sprite_script: Path | None = None,
    tilemap_script: Path | None = None,
    log: Callable[[str], None] = print,
) -> int:
    """
    Full headless export.
    Returns 0 on success, 1 if any error occurred (suitable for sys.exit).
    """
    project_path = Path(project_path).resolve()
    if not project_path.exists():
        print(f"ERROR: project file not found: {project_path}", file=sys.stderr)
        return 1

    try:
        data = json.loads(project_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: cannot read project: {e}", file=sys.stderr)
        return 1

    base_dir = project_path.parent
    # Linux: normalise backslashes in export_dir paths stored on Windows
    export_dir_rel = str(data.get("export_dir") or "").replace("\\", "/").strip()
    export_dir_abs = (base_dir / export_dir_rel) if export_dir_rel else None

    try:
        _sync_validated_sprite_runtime(base_dir)
        log(f"Runtime  : synced {base_dir / 'src/ngpng/ngpng_player_runtime.c'}")
    except Exception as e:
        log(f"WARN  cannot sync validated runtime files: {e}")

    # Auto-discover tools when not explicitly provided
    if sprite_script is None:
        sprite_script  = _find_tool_near("ngpc_sprite_export.py", base_dir)
    if tilemap_script is None:
        tilemap_script = _find_tool_near("ngpc_tilemap.py", base_dir)
    if sprite_script is not None:
        sprite_script = Path(sprite_script).resolve()
    if tilemap_script is not None:
        tilemap_script = Path(tilemap_script).resolve()

    log(f"Project  : {project_path}")
    log(f"Sprites  : {sprite_script  or '(not found)'}")
    log(f"Tilemaps : {tilemap_script or '(not found)'}")
    log("")

    try:
        preflight_issues = collect_export_pipeline_issues(base_dir, data)
    except Exception:
        preflight_issues = []
    if preflight_issues:
        log("[Export validation]")
        for issue in preflight_issues:
            sev = "ERR" if str(getattr(issue, "severity", "") or "") == "bad" else "WARN"
            scene_label = str(getattr(issue, "scene_label", "") or "").strip()
            asset_label = str(getattr(issue, "asset_label", "") or "").strip()
            msg = str(getattr(issue, "message", "") or "").strip()
            prefix = f"[{scene_label}] " if scene_label else ""
            body = f"{asset_label}: {msg}" if asset_label else msg
            log(f"  {sev}  {prefix}{body}")
        log("")

    scenes = data.get("scenes") or []
    if scene_filter:
        scenes = [
            s for s in scenes
            if (s.get("label") or "").lower() == scene_filter.lower()
        ]
        if not scenes:
            print(f"ERROR: no scene named '{scene_filter}'", file=sys.stderr)
            return 1

    if not scenes:
        log("(no scenes to export)")
        return 0

    # Purge stale *_mspr.* files once before exporting any scene so that
    # renamed sprites don't leave orphan files, and so that scene_2's export
    # doesn't erase scene_1's freshly generated sprites.
    if export_dir_abs and export_dir_abs.is_dir():
        for _stale in list(export_dir_abs.glob("*_mspr.c")) + list(export_dir_abs.glob("*_mspr.h")):
            try:
                _stale.unlink()
            except Exception:
                pass

    total = ExportResult()
    for scene in scenes:
        label = scene.get("label") or "?"
        log(f"[Scene: {label}]")
        r = export_scene(scene, data, base_dir, sprite_script, tilemap_script, log)
        total.ok      += r.ok
        total.skipped += r.skipped
        total.errors  += r.errors
        log("")

    log("=" * 50)
    total.print_summary()

    # Custom font export (no_sysfont=true + custom_font_png set)
    _no_sysfont = bool(data.get("no_sysfont"))
    if export_dir_abs and _no_sysfont:
        _custom_font_png = str(data.get("custom_font_png") or "").strip()
        if _custom_font_png:
            _font_script = _find_tool_near("ngpc_font_export.py", base_dir)
            if _font_script:
                _font_out = str(export_dir_abs / "ngpc_custom_font")
                import subprocess as _sp
                _fr = _sp.run(
                    [sys.executable, str(_font_script), _custom_font_png, "-o", _font_out, "-n", "ngpc_custom_font"],
                    capture_output=True, text=True,
                )
                if _fr.returncode == 0:
                    log(f"CustomFont: {_font_out}.c + .h")
                else:
                    log(f"WARN  custom font export failed: {_fr.stderr.strip()}")
            else:
                log("WARN  ngpc_font_export.py not found — custom font not exported")
        else:
            log("WARN  no_sysfont=true but custom_font_png is empty")

    if export_dir_abs:
        try:
            sh, sc, skipped = write_scenes_autogen(project_data=data, export_dir=export_dir_abs)
            if sh and sc:
                log(f"Scenes   : {sh} + {sc}")
                if skipped:
                    log(f"Scenes   : skipped {len(skipped)} (not exported yet)")
        except Exception as e:
            log(f"WARN  cannot write scenes_autogen.c/h: {e}")
        try:
            _has_save = project_has_save_triggers(data)
            mk_path = write_assets_autogen_mk(base_dir, export_dir_abs, has_save=_has_save, no_sysfont=_no_sysfont)
            log(f"Makefile : {mk_path}")
        except Exception as e:
            log(f"WARN  cannot write assets_autogen.mk: {e}")
        try:
            sfx_h = write_sfx_map_h(project_data=data, export_dir=export_dir_abs)
            if sfx_h:
                log(f"SFX map  : {sfx_h}")
        except Exception as e:
            log(f"WARN  cannot write ngpc_project_sfx_map.h: {e}")
        try:
            from core.entity_type_events_gen import write_entity_type_events_h
            ev_h = write_entity_type_events_h(project_data=data, export_dir=export_dir_abs)
            log(f"TypeEvts : {ev_h}")
        except Exception as e:
            log(f"WARN  cannot write ngpc_entity_type_events.h: {e}")
        try:
            from core.custom_events_gen import write_custom_events_h
            cev_h = write_custom_events_h(project_data=data, export_dir=export_dir_abs)
            log(f"CustEvts : {cev_h}")
        except Exception as e:
            log(f"WARN  cannot write ngpc_custom_events.h: {e}")
        try:
            from core.item_table_gen import write_item_table_h
            it_h = write_item_table_h(project_data=data, export_dir=export_dir_abs)
            log(f"ItemTable: {it_h}")
        except Exception as e:
            log(f"WARN  cannot write item_table.h: {e}")
        try:
            from core.procgen_config_gen import (
                write_procgen_config_h,
                write_cavegen_config_h,
                write_dungeongen_config_h,
            )
            for sc in (data.get("scenes") or []):
                if sc.get("rt_dfs_params"):
                    dfs_h = write_procgen_config_h(scene=sc, export_dir=export_dir_abs)
                    log(f"ProcgenDFS: {dfs_h}")
                if sc.get("rt_cave_params"):
                    cave_h = write_cavegen_config_h(scene=sc, export_dir=export_dir_abs, project_data=data)
                    log(f"ProcgenCave: {cave_h}")
                if sc.get("rt_dungeongen_params"):
                    dgen_h = write_dungeongen_config_h(
                        scene=sc,
                        export_dir=export_dir_abs,
                        project_data=data,
                    )
                    log(f"ProcgenDungeonGen: {dgen_h}")
        except Exception as e:
            log(f"WARN  cannot write procgen_config.h: {e}")
    # Optional: DungeonGen procgen assets (tiles + sprites)
    try:
        pa = (data.get("procgen_assets") or {}) if isinstance(data, dict) else {}
        dgen_pa = pa.get("dungeongen", {}) or {}
        if dgen_pa and export_dir_abs:
            gen_dir = export_dir_abs
            png_rel = str(dgen_pa.get("tileset_png", "") or "").strip()
            tile_roles = dgen_pa.get("tile_roles", {}) or {}
            if png_rel and tile_roles:
                from core.dungeongen_tiles_export import export_tiles_procgen
                from core.dungeongen_cells import (
                    normalize_dungeongen_runtime_cells,
                    parse_dungeongen_cell_size,
                )
                cell_cfg = str(dgen_pa.get("cell_size", "16x16") or "16x16")
                cw, ch = parse_dungeongen_cell_size(cell_cfg)
                # cell_size is a project-level setting — source and runtime are identical.
                # Scene-level cell_w/h_tiles are read-only mirrors of this value.
                rt_cw, rt_ch = cw, ch
                # Warn on stale per-scene values that diverge from the project setting.
                for _sc in (data.get("scenes") or []):
                    _rtdg = (_sc.get("rt_dungeongen_params") or {}) if isinstance(_sc, dict) else {}
                    if not _rtdg.get("enabled"):
                        continue
                    _sc_cw = int(_rtdg.get("cell_w_tiles", cw) or cw)
                    _sc_ch = int(_rtdg.get("cell_h_tiles", ch) or ch)
                    if _sc_cw != cw or _sc_ch != ch:
                        _sc_name = _sc.get("name", "?") if isinstance(_sc, dict) else "?"
                        log(
                            f"WARN  DungeonGen: scène '{_sc_name}' a cell_w_tiles={_sc_cw}/"
                            f"cell_h_tiles={_sc_ch} mais le projet est configuré en {cell_cfg} "
                            f"({cw}×{ch}). La valeur projet est utilisée — re-sauvegarder la scène."
                        )
                if base_dir and png_rel:
                    png_path = Path(png_rel) if Path(png_rel).is_absolute() else base_dir / png_rel
                    if png_path.exists():
                        role_dict: dict[str, list[int]] = {}
                        for k, v in tile_roles.items():
                            if isinstance(v, list):
                                role_dict[k] = [int(x) for x in v]
                            elif isinstance(v, int):
                                role_dict[k] = [v]
                        rt_cw, rt_ch, _cell_reason = normalize_dungeongen_runtime_cells(
                            source_cell_w_tiles=cw,
                            source_cell_h_tiles=ch,
                            requested_cell_w_tiles=rt_cw,
                            requested_cell_h_tiles=rt_ch,
                            tile_roles=role_dict,
                        )
                        _tileset_mode = str(dgen_pa.get("tileset_mode", "full") or "full")
                        tc, th = export_tiles_procgen(
                            png_path=png_path,
                            cell_w_tiles=cw,
                            cell_h_tiles=ch,
                            tile_roles=role_dict,
                            out_dir=gen_dir,
                            rt_cell_w_tiles=rt_cw,
                            rt_cell_h_tiles=rt_ch,
                            compact_mode=(_tileset_mode == "compact"),
                        )
                        log(f"DungeonTiles: {tc}, {th}")
            enemy_pool = dgen_pa.get("enemy_pool", []) or []
            item_pool  = dgen_pa.get("item_pool",  []) or []
            if not enemy_pool and not item_pool:
                for _sc in (data.get("scenes") or []):
                    _rtdg = (_sc.get("rt_dungeongen_params") or {}) if isinstance(_sc, dict) else {}
                    if not _rtdg.get("enabled"):
                        continue
                    _enemy_pool = _rtdg.get("enemy_pool", []) or []
                    _item_pool  = _rtdg.get("item_pool",  []) or []
                    if _enemy_pool or _item_pool:
                        enemy_pool = _enemy_pool
                        item_pool  = _item_pool
                        _sc_name = _sc.get("name", "?") if isinstance(_sc, dict) else "?"
                        log(
                            f"WARN  DungeonSprites: procgen_assets pool vide — "
                            f"utilisation du pool runtime de la scène '{_sc_name}'."
                        )
                        break
            from core.dungeongen_sprites_export import export_sprites_lab
            et = (data.get("entity_templates", []) or []) + (data.get("entity_types", []) or [])
            _sc2, _sh2 = export_sprites_lab(
                enemy_pool=enemy_pool,
                item_pool=item_pool,
                entity_types=[e for e in et if isinstance(e, dict)],
                base_dir=base_dir,
                out_dir=gen_dir,
            )
            log(f"DungeonSprites: {_sc2}, {_sh2}")
    except Exception as e:
        log(f"WARN  cannot write dungeongen procgen assets: {e}")
    # Optional: write Sound Creator exports Makefile include (AUD-4)
    try:
        audio = data.get("audio", {}) if isinstance(data, dict) else {}
        man_rel = str(audio.get("manifest") or "").strip() if isinstance(audio, dict) else ""
        if man_rel:
            man_abs = (base_dir / man_rel) if not Path(man_rel).is_absolute() else Path(man_rel)
            if man_abs.exists():
                # Optional SFX autogen (AUD-5): header + external Sfx_Play next to exports.
                try:
                    rows = audio.get("sfx_map", None) if isinstance(audio, dict) else None
                    if isinstance(rows, list) and rows and export_dir_abs:
                        write_sfx_map_h(project_data=data, export_dir=export_dir_abs, extra_dirs=[man_abs.parent])
                        write_sfx_play_autogen_c(exports_dir=man_abs.parent)
                except Exception:
                    pass
                out_dir = export_dir_abs if export_dir_abs else man_abs.parent
                # Skip audio_autogen.mk when template-managed audio is in place
                # (sound/new/*.c are #included by sound_data.c — adding them to OBJS again
                # would cause duplicate symbol errors at link time).
                _template_audio_managed = project_uses_template_managed_audio(base_dir)
                if _template_audio_managed and export_dir_abs:
                    amk = write_disabled_audio_autogen_mk(
                        out_dir,
                        reason="template-managed hybrid audio is aggregated by sound/sound_data.c",
                    )
                    log(f"Audio MK : {amk} (standalone audio objects disabled)")
                elif not _template_audio_managed:
                    amk = write_audio_autogen_mk(
                        base_dir,
                        man_abs.parent,
                        out_dir=out_dir,
                        manifest=load_audio_manifest(man_abs),
                    )
                    log(f"Audio MK : {amk}")
                else:
                    log("Audio MK : skipped (template-managed audio in sound/new/)")
    except Exception as e:
        log(f"WARN  cannot write audio_autogen.mk: {e}")
    try:
        regen_script = Path(__file__).resolve().parent.parent / "regen_autorun.py"
        if regen_script.exists():
            regen = subprocess.run(
                _python_cmd(regen_script) + [str(project_path)],
                cwd=str(regen_script.parent),
                capture_output=True,
                text=True,
                check=False,
            )
            if regen.returncode == 0:
                for _line in (regen.stdout or "").splitlines():
                    _line = _line.strip()
                    if _line:
                        log(f"Autorun : {_line}")
            else:
                _msg = (regen.stderr or regen.stdout or "").strip()
                log(f"WARN  cannot regenerate autorun_main: {_msg or f'code {regen.returncode}'}")
    except Exception as e:
        log(f"WARN  cannot regenerate autorun_main: {e}")
    return 0 if total.success else 1
