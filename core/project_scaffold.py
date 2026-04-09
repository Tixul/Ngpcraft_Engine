"""
core/project_scaffold.py - Scaffold a new NGPC C project from the bundled template.

Copies NgpCraft_base_template to a new destination and applies user-specified patches:
  - makefile:           NAME= and feature flags (SOUND, FLASH_SAVE, DEBUG, DMA)
  - build.bat:          romName=, compilerPath=, emuPath=
  - src/core/carthdr.h: CartTitle[12]
  - project.ngpcraft:      blank or pre-filled from a starter template
"""

from __future__ import annotations

import fnmatch
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from core.app_paths import user_template_root
from core.project_templates import DEFAULT_TEMPLATE_ID, write_project_file


# ---------------------------------------------------------------------------
# Template discovery
# ---------------------------------------------------------------------------

def find_template_root() -> Path | None:
    """Return the NGPC Template root directory, or None if not found.

    Search order (first hit with a makefile wins):
      1. PyInstaller _MEIPASS bundle  (standalone .exe distribution)
      2. Embedded copy inside PNG Manager  (templates/NgpCraft_base_template/)
         — no Toshiba binaries; users must set compilerPath in build.bat
      3. Dev-mode sibling  (NgpCraft_base_template next to NgpCraft_engine)
         — legacy fallback
    """
    candidates: list[Path] = []

    # 1. User-writable AppData copy (installer builds, after "Update Template").
    #    Takes priority so updated template is always used over the bundled one.
    user = user_template_root()
    if user is not None:
        candidates.append(user)

    # 2. Packaged binary bundle (PyInstaller --onefile: _MEIPASS extraction dir).
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "templates" / "NgpCraft_base_template")

    # 3. Embedded copy shipped with the tool (--onedir portable or source run).
    manager_root = Path(__file__).resolve().parent.parent
    candidates.append(manager_root / "templates" / "NgpCraft_base_template")

    # 4. Dev mode: NgpCraft_base_template sits next to NgpCraft_engine (legacy).
    candidates.append(manager_root.parent / "NgpCraft_base_template")

    for p in candidates:
        if (p / "makefile").exists():
            return p
    return None


# ---------------------------------------------------------------------------
# Sanitizers (mirrors ngpc_project_init.py logic)
# ---------------------------------------------------------------------------

def sanitize_rom_name(value: str) -> str:
    """Normalize a ROM basename to lowercase ASCII and underscores only."""
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9_]", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "main"


def derive_cart_title(name: str) -> str:
    """Produce a strict 12-char ASCII cart title (padded with spaces)."""
    text = name.upper()
    text = "".join(
        ch if ("A" <= ch <= "Z" or "0" <= ch <= "9" or ch == " ") else " "
        for ch in text
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text[:12].ljust(12)


# ---------------------------------------------------------------------------
# Scaffold parameters
# ---------------------------------------------------------------------------

@dataclass
class ScaffoldParams:
    """User-selected options required to scaffold a fresh NGPC project."""

    destination: Path       # full path to the new project folder
    project_name: str       # human-readable name
    rom_name: str           # sanitized: lowercase, underscores only
    cart_title: str         # exactly 12 ASCII chars (padded)
    project_template: str = DEFAULT_TEMPLATE_ID
    enable_sound: bool = True
    enable_flash_save: bool = False
    enable_debug: bool = False
    enable_dma: bool = False
    compiler_path: str = ""
    system_lib_path: str = ""
    emulator_path: str = ""


# ---------------------------------------------------------------------------
# Artifact filter (excludes files/folders listed in the template's .gitignore)
# ---------------------------------------------------------------------------

def _load_gitignore_patterns(template_root: Path) -> tuple[list[str], list[str]]:
    """Parse template_root/.gitignore and return (dir_patterns, file_patterns).

    Only handles simple patterns (exact names, glob wildcards, trailing-slash
    directory markers). Anchored patterns (/foo) and negation (!foo) are not
    needed for our .gitignore and are silently skipped.
    """
    dir_pats: list[str] = []
    file_pats: list[str] = []
    gitignore = template_root / ".gitignore"
    if not gitignore.exists():
        return dir_pats, file_pats
    for raw in gitignore.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("!") or line.startswith("/"):
            continue
        if line.endswith("/"):
            dir_pats.append(line.rstrip("/"))
        else:
            file_pats.append(line)
    return dir_pats, file_pats


def _make_gitignore_filter(template_root: Path):
    """Return a shutil.copytree-compatible ignore callable built from .gitignore.

    Always also excludes .git/ and .vs/ (never useful in a new project).
    """
    dir_pats, file_pats = _load_gitignore_patterns(template_root)
    # Hard-coded extra dirs that should never be copied regardless of .gitignore
    extra_dirs = {".git", ".vs", ".vscode"}

    def _ignore(dir_path: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        for n in names:
            if n in extra_dirs:
                ignored.add(n)
                continue
            low = n.lower()
            # Directory patterns (match by name, case-insensitive on Windows)
            for pat in dir_pats:
                if fnmatch.fnmatch(low, pat.lower()):
                    ignored.add(n)
                    break
            else:
                # File patterns
                for pat in file_pats:
                    if fnmatch.fnmatch(low, pat.lower()):
                        ignored.add(n)
                        break
        return ignored

    return _ignore


# ---------------------------------------------------------------------------
# File patchers
# ---------------------------------------------------------------------------

def _patch_makefile(path: Path, p: ScaffoldParams) -> None:
    content = path.read_text(encoding="utf-8")
    content = re.sub(r"(?m)^NAME\s*=\s*.+$", f"NAME = {p.rom_name}", content)
    content = re.sub(
        r"(?m)^NGP_ENABLE_SOUND\s*\?=\s*\d+",
        f"NGP_ENABLE_SOUND ?= {1 if p.enable_sound else 0}",
        content,
    )
    content = re.sub(
        r"(?m)^NGP_ENABLE_FLASH_SAVE\s*\?=\s*\d+",
        f"NGP_ENABLE_FLASH_SAVE ?= {1 if p.enable_flash_save else 0}",
        content,
    )
    content = re.sub(
        r"(?m)^NGP_ENABLE_DEBUG\s*\?=\s*\d+",
        f"NGP_ENABLE_DEBUG ?= {1 if p.enable_debug else 0}",
        content,
    )
    content = re.sub(
        r"(?m)^NGP_ENABLE_DMA\s*\?=\s*\d+",
        f"NGP_ENABLE_DMA ?= {1 if p.enable_dma else 0}",
        content,
    )
    system_lib = p.system_lib_path.strip().strip('"').replace("\\", "/")
    content = re.sub(
        r"(?m)^SYSTEM_LIB\s*\?=\s*.*$",
        lambda _: f"SYSTEM_LIB ?= {system_lib}",
        content,
    )
    if p.compiler_path:
        thome = p.compiler_path.strip().strip('"').replace("\\", "/")
        content = re.sub(
            r"(?m)^THOME\s*\?=\s*.*$",
            lambda _: f"THOME ?= {thome}",
            content,
        )
    path.write_text(content, encoding="utf-8")


def _patch_build_bat(path: Path, p: ScaffoldParams) -> None:
    content = path.read_text(encoding="utf-8")
    # Use lambdas as repl so re.sub never interprets backslashes in Windows paths.
    rom = p.rom_name
    content = re.sub(r"(?m)^SET romName=.*$", lambda _: f"SET romName={rom}", content)
    if p.enable_flash_save:
        content = re.sub(r"(?m)^SET FlashSave=.*$", lambda _: "SET FlashSave=1", content)
    if p.compiler_path:
        cc = p.compiler_path
        content = re.sub(
            r"(?m)^SET compilerPath=.*$",
            lambda _: f"SET compilerPath={cc}",
            content,
        )
    system_lib = p.system_lib_path.strip().strip('"')
    content = re.sub(
        r"(?m)^SET systemLibPath=.*$",
        lambda _: f"SET systemLibPath={system_lib}",
        content,
    )
    if p.emulator_path:
        emu = p.emulator_path.strip('"')
        content = re.sub(
            r'(?m)^SET emuPath=.*$',
            lambda _: f'SET emuPath="{emu}"',
            content,
        )
    path.write_text(content, encoding="utf-8")


def _patch_carthdr(path: Path, cart_title_12: str) -> None:
    content = path.read_text(encoding="utf-8")
    content = re.sub(
        r'const char CartTitle\[12\]\s*=\s*"[^"]*";',
        f'const char CartTitle[12] = "{cart_title_12}";',
        content,
    )
    path.write_text(content, encoding="utf-8")


def _patch_main_c(path: Path, p: ScaffoldParams) -> None:
    """Replace the template demo main.c with a starter hello world."""
    content = (
        "/*\n"
        f" * main.c - {p.project_name}\n"
        " *\n"
        " * Starter template — demonstrates the basic API:\n"
        " * - hardware init + BIOS system font\n"
        " * - text printing and hex/dec display\n"
        " * - pad input (held / pressed / released)\n"
        " * - movable tile cursor\n"
        " */\n"
        "\n"
        '#include "ngpc_hw.h"\n'
        '#include "carthdr.h"\n'
        '#include "ngpc_sys.h"\n'
        '#include "ngpc_gfx.h"\n'
        '#include "ngpc_text.h"\n'
        '#include "ngpc_timing.h"\n'
        '#include "ngpc_input.h"\n'
        "\n"
        "static void hello_init(void)\n"
        "{\n"
        "    ngpc_gfx_scroll(GFX_SCR1, 0, 0);\n"
        "    ngpc_gfx_scroll(GFX_SCR2, 0, 0);\n"
        "    ngpc_gfx_clear(GFX_SCR1);\n"
        "    ngpc_gfx_clear(GFX_SCR2);\n"
        "\n"
        "    ngpc_gfx_set_bg_color(RGB(0, 0, 0));\n"
        "\n"
        "    /* Palette 0 for text plane (SCR1). */\n"
        "    ngpc_gfx_set_palette(GFX_SCR1, 0,\n"
        "        RGB(0, 0, 0),\n"
        "        RGB(15, 15, 15),\n"
        "        RGB(10, 10, 10),\n"
        "        RGB(6, 6, 6)\n"
        "    );\n"
        "\n"
        "    /* Clear any leftover glyphs on the line tails. */\n"
        "    ngpc_gfx_fill(GFX_SCR1, ' ', 0);\n"
        "\n"
        '    ngpc_text_print(GFX_SCR1, 0, 4, 2, "Hello, world!");\n'
        '    ngpc_text_print(GFX_SCR1, 0, 2, 4, "FRAME:");\n'
        '    ngpc_text_print(GFX_SCR1, 0, 2, 5, "HELD:");\n'
        '    ngpc_text_print(GFX_SCR1, 0, 2, 6, "PRESSED:");\n'
        '    ngpc_text_print(GFX_SCR1, 0, 2, 7, "RELEASED:");\n'
        "}\n"
        "\n"
        "void main(void)\n"
        "{\n"
        "    u8 cursor_x = 1;\n"
        "    u8 cursor_y = 10;\n"
        "    u16 frame = 0;\n"
        "    u8 old_x = cursor_x;\n"
        "    u8 old_y = cursor_y;\n"
        "\n"
        "    ngpc_init();\n"
        "    ngpc_load_sysfont();\n"
        "\n"
        "    hello_init();\n"
        "    ngpc_gfx_put_tile(GFX_SCR1, cursor_x, cursor_y, '@', 0);\n"
        "\n"
        "    while (1) {\n"
        "        ngpc_vsync();\n"
        "        ngpc_input_update();\n"
        "\n"
        "        old_x = cursor_x;\n"
        "        old_y = cursor_y;\n"
        "\n"
        "        /* 1 press = 1 tile (use PRESSED, not HELD). */\n"
        "        if (ngpc_pad_pressed & PAD_LEFT)  { if (cursor_x > 0)              cursor_x--; }\n"
        "        if (ngpc_pad_pressed & PAD_RIGHT) { if (cursor_x < (SCREEN_TW-1)) cursor_x++; }\n"
        "        if (ngpc_pad_pressed & PAD_UP)    { if (cursor_y > 0)              cursor_y--; }\n"
        "        if (ngpc_pad_pressed & PAD_DOWN)  { if (cursor_y < (SCREEN_TH-1)) cursor_y++; }\n"
        "\n"
        "        /* Erase old position and draw new one. */\n"
        "        if (cursor_x != old_x || cursor_y != old_y) {\n"
        "            ngpc_gfx_put_tile(GFX_SCR1, old_x, old_y, ' ', 0);\n"
        "            ngpc_gfx_put_tile(GFX_SCR1, cursor_x, cursor_y, '@', 0);\n"
        "        }\n"
        "\n"
        "        ngpc_text_print_dec(GFX_SCR1, 0,  9, 4, frame,                 5);\n"
        "        ngpc_text_print_hex(GFX_SCR1, 0, 11, 5, (u16)ngpc_pad_held,     2);\n"
        "        ngpc_text_print_hex(GFX_SCR1, 0, 11, 6, (u16)ngpc_pad_pressed,  2);\n"
        "        ngpc_text_print_hex(GFX_SCR1, 0, 11, 7, (u16)ngpc_pad_released, 2);\n"
        "\n"
        "        frame++;\n"
        "    }\n"
        "}\n"
    )
    path.write_text(content, encoding="utf-8")


def scaffold_project(params: ScaffoldParams, template_root: Path) -> Path:
    """
    Copy the template to params.destination and apply all patches.

    Returns the path to the created project.ngpcraft file.
    Raises RuntimeError (or OSError) on failure.
    If an error occurs after copytree, the partially created folder is removed.
    The destination folder must NOT exist before calling this function.
    """
    dest = params.destination
    if dest.exists():
        raise RuntimeError(f"Destination already exists: {dest}")

    shutil.copytree(str(template_root), str(dest), ignore=_make_gitignore_filter(template_root))

    try:
        _patch_makefile(dest / "makefile", params)
        _patch_build_bat(dest / "build.bat", params)
        _patch_carthdr(dest / "src" / "core" / "carthdr.h", params.cart_title)
        _patch_main_c(dest / "src" / "main.c", params)

        ngpng_path = write_project_file(
            destination=dest,
            project_name=params.project_name,
            rom_name=params.rom_name,
            template_id=params.project_template,
        )
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise

    return ngpng_path
