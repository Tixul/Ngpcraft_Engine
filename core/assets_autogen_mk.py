"""
core/assets_autogen_mk.py - Generate a Makefile include listing generated assets.

Goal: avoid hand-editing OBJS after each export.

We write an include file (assets_autogen.mk) that appends .rel objects for every
.c file found under the configured export directory.
"""

from __future__ import annotations

import os
import re
from pathlib import Path


def _make_relpath(path: Path, base_dir: Path) -> str:
    """Return a Makefile-safe relative path using forward slashes."""
    try:
        rel = path.relative_to(base_dir)
    except ValueError:
        rel = Path(os.path.relpath(path, base_dir))
    return str(rel).replace("\\", "/")


_OBJ_REL_RE = re.compile(r"\$\(OBJ_DIR\)/([^\s]+?\.rel)")
_FLASH_SAVE_ASSIGN_RE = re.compile(r"(?m)^\s*NGP_ENABLE_FLASH_SAVE\s*(?:\?=|:=|=)\s*([0-9]+)\s*$")
_MAKEFILE_OBJ_ASSIGN_RE = re.compile(r"^\s*(OBJS|NGPNG_EXTRA_OBJS)\s*(?:\+?=|:=|=)")

_MSPR_TILE_BASE_RE = re.compile(r"const\s+u16\s+\w+_tile_base\s*=\s*(\d+)\s*u\s*;")
_MSPR_TILES_COUNT_RE = re.compile(r"const\s+u16\s+\w+_tiles_count\s*=\s*(\d+)\s*u\s*;")


def _compute_font_tile_base(export_dir: Path) -> int | None:
    """
    Scan *_mspr.c files in export_dir to find the highest tile end slot.
    Returns the first free tile slot after all sprite tiles, or None if no sprites found.
    Each tiles_count value is in u16 words (8 words per tile), so tile_count = tiles_count // 8.
    """
    max_end: int | None = None
    for mspr in export_dir.glob("*_mspr.c"):
        try:
            text = mspr.read_text(encoding="utf-8")
        except Exception:
            continue
        bases = [int(m.group(1)) for m in _MSPR_TILE_BASE_RE.finditer(text)]
        counts = [int(m.group(1)) for m in _MSPR_TILES_COUNT_RE.finditer(text)]
        if bases and counts:
            tile_end = bases[0] + counts[0] // 8
            if max_end is None or tile_end > max_end:
                max_end = tile_end
    return max_end


def _find_project_makefile(project_dir: Path) -> Path | None:
    for name in ("makefile", "Makefile"):
        candidate = project_dir / name
        if candidate.is_file():
            return candidate
    return None


def _read_explicit_makefile_objs(project_dir: Path) -> set[str]:
    """
    Return .rel paths already declared explicitly in the project makefile.
    These must not be re-added by assets_autogen.mk, or tulink will see the
    same object twice.
    """
    makefile_path = _find_project_makefile(project_dir)
    if makefile_path is None:
        return set()
    try:
        text = makefile_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = makefile_path.read_text(encoding="latin-1")
    # Only scan OBJS/NGPNG_EXTRA_OBJS assignment lines, not dependency rules like
    #   $(OBJ_DIR)/foo.rel: $(headers)
    # which look identical to the regex but are NOT OBJS additions.
    result: set[str] = set()
    for line in text.splitlines():
        if not _MAKEFILE_OBJ_ASSIGN_RE.match(line):
            continue
        for m in _OBJ_REL_RE.finditer(line):
            result.add(m.group(1).replace("\\", "/").lower())
    return result


def _makefile_sets_flash_save(project_dir: Path) -> bool:
    """Return True when the project makefile already enables flash save itself."""
    makefile_path = _find_project_makefile(project_dir)
    if makefile_path is None:
        return False
    try:
        text = makefile_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = makefile_path.read_text(encoding="latin-1")
    for match in _FLASH_SAVE_ASSIGN_RE.finditer(text):
        try:
            if int(match.group(1)) != 0:
                return True
        except ValueError:
            continue
    return False


def _is_duplicate_map_companion(c_path: Path, export_dir: Path) -> bool:
    """
    Skip generated *_map.c files when the matching base asset already exists and
    already bundles the same map symbols.

    This happens in two supported layouts:
    - GraphX/<name>.c + GraphX/<name>.h + GraphX/<name>_map.c
    - GraphX/<name>.c + GraphX/<name>.h + GraphX/gen/<name>_map.c
    """
    if not c_path.name.lower().endswith("_map.c"):
        return False
    stem = c_path.stem
    if not stem.lower().endswith("_map"):
        return False
    base = stem[:-4]
    if not base:
        return False

    candidates = [
        c_path.parent / f"{base}.c",
        c_path.parent / f"{base}.h",
        export_dir.parent / f"{base}.c",
        export_dir.parent / f"{base}.h",
    ]
    if c_path.parent != export_dir:
        candidates.extend(
            [
                export_dir / f"{base}.c",
                export_dir / f"{base}.h",
            ]
        )
    found_c = any(p.name.lower() == f"{base}.c".lower() and p.is_file() for p in candidates)
    found_h = any(p.name.lower() == f"{base}.h".lower() and p.is_file() for p in candidates)
    return found_c and found_h


def write_assets_autogen_mk(
    project_dir: Path,
    export_dir: Path,
    has_save: bool = False,
    no_sysfont: bool = False,
) -> Path:
    """
    Scan export_dir recursively for *.c and generate:
      export_dir/assets_autogen.mk

    Each entry becomes:
      OBJS += $(OBJ_DIR)/<relpath>.rel
    where relpath is relative to project_dir.

    has_save: when True, emit NGP_ENABLE_FLASH_SAVE=1 so the standalone
    flash stubs (ngpc_flash_asm.rel) are compiled in by the template makefile.
    """
    project_dir = Path(project_dir)
    export_dir = Path(export_dir)
    mk_path = export_dir / "assets_autogen.mk"
    explicit_objs = _read_explicit_makefile_objs(project_dir)

    c_files: list[Path] = []
    if export_dir.exists():
        for p in export_dir.rglob("*.c"):
            if p.name.lower() == "assets_autogen.c":
                continue
            if _is_duplicate_map_companion(p, export_dir):
                continue
            c_files.append(p)

    def _link_order_key(p: Path) -> tuple[int, str]:
        """Sprites before maps before everything else (within each group: alphabetical)."""
        name = p.name.lower()
        if name.endswith("_mspr.c"):
            return (0, str(p))
        if "_map.c" in name or name.endswith("_map.c"):
            return (2, str(p))
        return (1, str(p))

    rel_objs: list[str] = []
    has_mapstream = False
    has_dungeongen = (export_dir / "dungeongen_config.h").exists()
    for c in sorted(c_files, key=_link_order_key):
        rel_rel = _make_relpath(c, project_dir)
        if rel_rel.lower().endswith(".c"):
            rel_rel = rel_rel[:-2] + ".rel"
        rel_rel = rel_rel.replace("\\", "/")
        if rel_rel.lower() in explicit_objs:
            continue
        rel_objs.append(f"$(OBJ_DIR)/{rel_rel}")
        if c.name.lower().endswith("_bg_map.c"):
            has_mapstream = True

    lines: list[str] = []
    lines.append("# Auto-generated by NgpCraft Engine -- do not edit\n")
    lines.append("# Generated objects from exported assets (.c -> .rel)\n\n")
    lines.append("# Optional: include audio exports list if present (AUD-4)\n")
    lines.append("-include $(dir $(lastword $(MAKEFILE_LIST)))audio_autogen.mk\n\n")
    if rel_objs:
        for obj in rel_objs:
            lines.append(f"OBJS += {obj}\n")
    else:
        lines.append("# (no .c assets found)\n")
    font_tile_base = _compute_font_tile_base(export_dir)
    if font_tile_base is not None:
        lines.append(f"# Font tile base: placed after all sprite tiles (first free = {font_tile_base})\n")
        lines.append(f"CDEFS += -DFONT_TILE_BASE={font_tile_base}\n")
    if has_mapstream:
        ms_rel = "optional/ngpc_mapstream/ngpc_mapstream.rel"
        if ms_rel.lower() not in explicit_objs:
            lines.append("# ngpc_mapstream: required when any scene uses large-map streaming\n")
            lines.append("CDEFS += -DNGPNG_HAS_MAPSTREAM=1\n")
            lines.append(f"OBJS += $(OBJ_DIR)/{ms_rel}\n")
    if has_dungeongen:
        dgen_rel = "optional/ngpc_dungeongen/ngpc_dungeongen.rel"
        clus_rel = "optional/ngpc_dungeongen/ngpc_cluster.rel"
        rtc_rel  = "src/core/ngpc_rtc.rel"
        lines.append("# ngpc_dungeongen: required when any scene uses dungeon generation\n")
        lines.append("CDEFS += -DNGPNG_HAS_DUNGEONGEN=1\n")
        if dgen_rel.lower() not in explicit_objs:
            lines.append(f"OBJS += $(OBJ_DIR)/{dgen_rel}\n")
        if clus_rel.lower() not in explicit_objs:
            lines.append(f"OBJS += $(OBJ_DIR)/{clus_rel}\n")
        # ngpc_dungeongen uses ngpc_rtc_get() — re-add ngpc_rtc via NGPNG_EXTRA_OBJS
        # (OBJS += here would be filtered out by NGPNG_TRIM_UNUSED; EXTRA_OBJS is
        #  appended by the template makefile AFTER the trim block)
        lines.append(f"NGPNG_EXTRA_OBJS += $(OBJ_DIR)/{rtc_rel}\n")
    if no_sysfont:
        lines.append("# Custom font: disable BIOS system font, add generated font to include path\n")
        lines.append("CDEFS += -DNO_SYSFONT=1\n")
        lines.append("CDEFS += -IGraphX/gen\n")
    if has_save:
        lines.append("# Flash save: standalone AMD stubs (no system.lib required)\n")
        lines.append("NGP_ENABLE_FLASH_SAVE = 1\n")
        if not _makefile_sets_flash_save(project_dir):
            # ngpc_flash_asm.rel is guarded by ifneq(NGP_ENABLE_FLASH_SAVE) in the template
            # makefile, which is evaluated at parse time before assets_autogen.mk is included.
            # Add it here explicitly only when the main makefile does not already enable flash save.
            lines.append("OBJS += $(OBJ_DIR)/src/core/ngpc_flash_asm.rel\n")

    export_dir.mkdir(parents=True, exist_ok=True)
    mk_path.write_text("".join(lines), encoding="utf-8")
    return mk_path
