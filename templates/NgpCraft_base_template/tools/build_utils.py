#!/usr/bin/env python3
"""
build_utils.py - Small cross-platform helpers for NGPC make targets.

Usage:
  python tools/build_utils.py clean
  python tools/build_utils.py move <name> <output_dir>
  python tools/build_utils.py s242ngp <file.s24>
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import tempfile

_IS_WINDOWS = sys.platform == "win32"


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _resolve_tool(name: str) -> list[str]:
    """Return the command list to invoke a Toshiba tool.

    On Windows: find name.exe via THOME or PATH.
    On Linux:   same lookup, but prepend 'wine'. Falls back to a plain
                shell wrapper named <name> if one exists in PATH (no wine needed).
    """
    exe_name = name + ".exe"
    thome = os.environ.get("THOME", "")
    thome_path = os.path.join(thome, "BIN", exe_name) if thome else ""

    if _IS_WINDOWS:
        path = thome_path if (thome_path and os.path.exists(thome_path)) else shutil.which(exe_name) or shutil.which(name)
        if not path:
            print(f"{exe_name} not found (set THOME or PATH).", file=sys.stderr)
            return []
        return [path]
    else:
        # Linux: prefer a plain wrapper script (no wine needed), then wine + .exe
        wrapper = shutil.which(name)
        if wrapper:
            return [wrapper]
        exe_path = thome_path if (thome_path and os.path.exists(thome_path)) else shutil.which(exe_name)
        if not exe_path:
            print(f"{exe_name} not found (set THOME or PATH).", file=sys.stderr)
            return []
        wine = shutil.which("wine")
        if not wine:
            print("wine not found. Install wine to run Toshiba tools on Linux.", file=sys.stderr)
            return []
        return [wine, exe_path]


def _ensure_crlf(src: str) -> tuple[str, bool]:
    """On Linux, copy src to a temp file with CRLF endings for ASM900.
    Returns (path_to_use, is_temp). Caller must delete temp if is_temp=True.
    """
    if _IS_WINDOWS:
        return src, False
    with open(src, "rb") as f:
        data = f.read()
    if b"\r\n" in data:
        return src, False
    crlf_data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    tmp = tempfile.NamedTemporaryFile(
        suffix=".asm", dir=os.path.dirname(os.path.abspath(src)), delete=False
    )
    tmp.write(crlf_data)
    tmp.close()
    return tmp.name, True


def cmd_clean() -> int:
    patterns = [
        "build/obj/**/*.rel",
        "build/tmp/*.abs",
        "build/tmp/*.s24",
        "build/tmp/*.map",
        "build/tmp/*.lst",
        "build/tmp/*.ngp",
        "build/tmp/*.ngc",
        "build/tmp/*.ngpc",
        # Legacy paths (pre-build/tmp migration).
        "*.abs",
        "*.s24",
        "*.map",
        "*.lst",
        "*.ngp",
        "*.ngc",
        "*.ngpc",
        # Legacy paths (pre-build/obj migration).
        "src/*.rel",
        "src/audio/*.rel",
        "sound/*.rel",
        "GraphX/*.rel",
        "bin/*.abs",
        "bin/*.s24",
        "bin/*.map",
        "bin/*.ngp",
        "bin/*.ngc",
        "bin/*.ngpc",
    ]
    for pattern in patterns:
        for path in glob.glob(pattern, recursive=True):
            _safe_remove(path)
    return 0


def cmd_copy(src: str, dst: str) -> int:
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    shutil.copy2(src, dst)
    return 0


def cmd_move(name: str, output_dir: str) -> int:
    base_name = os.path.basename(name)
    os.makedirs(output_dir, exist_ok=True)
    for ext in ("abs", "s24", "map", "ngc", "ngpc"):
        src = f"{name}.{ext}"
        if os.path.exists(src):
            dst = os.path.join(output_dir, f"{base_name}.{ext}")
            _safe_remove(dst)
            shutil.move(src, dst)

    # s242ngp always emits .ngp; archive it as .ngc to keep a single ROM format.
    ngp_src = f"{name}.ngp"
    if os.path.exists(ngp_src):
        ngc_dst = os.path.join(output_dir, f"{base_name}.ngc")
        _safe_remove(ngc_dst)
        shutil.move(ngp_src, ngc_dst)
    return 0


def cmd_asm(src: str, obj: str) -> int:
    src = os.path.normpath(src)
    obj = os.path.normpath(obj)

    os.makedirs(os.path.dirname(obj) or ".", exist_ok=True)

    asm900_cmd = _resolve_tool("asm900")
    if not asm900_cmd:
        return 2

    # ASM900 requires CRLF line endings; normalize on Linux.
    crlf_src, is_temp = _ensure_crlf(src)
    try:
        # asm900 always writes <source_basename>.rel next to the source file.
        # Run it from the source directory so the output lands predictably.
        src_dir = os.path.dirname(crlf_src) or "."
        src_name = os.path.basename(crlf_src)
        rel_name = os.path.splitext(os.path.basename(src))[0] + ".rel"
        rel_out = os.path.join(os.path.dirname(src) or ".", rel_name)

        result = subprocess.run(
            asm900_cmd + ["-g", src_name],
            cwd=src_dir,
            check=False,
        )
        if result.returncode != 0:
            return result.returncode
    finally:
        if is_temp:
            _safe_remove(crlf_src)

    # Move the .rel to the expected build/obj path.
    if os.path.normpath(rel_out) != os.path.normpath(obj):
        shutil.move(rel_out, obj)
    return 0


def cmd_compile(src: str, obj: str, extra_flags: list[str]) -> int:
    src = os.path.normpath(src)
    obj = os.path.normpath(obj)
    project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

    os.makedirs(os.path.dirname(obj) or ".", exist_ok=True)

    cc900_cmd = _resolve_tool("cc900")
    if not cc900_cmd:
        return 2

    # cc900 invokes thc1/thc2 as relative paths, so it must run from its own
    # directory. Use absolute paths for source, output, and includes.
    cc900_dir = os.path.dirname(os.path.abspath(cc900_cmd[-1]))
    src_abs = os.path.abspath(os.path.join(project_root, src))
    obj_abs = os.path.abspath(os.path.join(project_root, obj))
    include_flags = [
        "-I" + os.path.abspath(os.path.join(project_root, d))
        for d in ("src", "src/core", "src/gfx", "src/fx", "src/audio")
    ]
    abs_extra_flags = []
    for flag in extra_flags:
        if flag.startswith("-I") and not os.path.isabs(flag[2:]):
            abs_extra_flags.append("-I" + os.path.abspath(os.path.join(project_root, flag[2:])))
        else:
            abs_extra_flags.append(flag)
    cmd = cc900_cmd + ["-c", "-O3"] + include_flags + abs_extra_flags + [src_abs, "-o", obj_abs]
    result = subprocess.run(
        cmd,
        cwd=cc900_dir,
        check=False,
    )
    return result.returncode


def cmd_link(abs_path: str, lcf: str, link_args: list[str]) -> int:
    """Invoke tulink then tuconv using THOME for tool discovery."""
    tulink_cmd = _resolve_tool("tulink")
    if not tulink_cmd:
        return 2

    tuconv_cmd = _resolve_tool("tuconv")
    if not tuconv_cmd:
        return 2

    result = subprocess.run(
        tulink_cmd + ["-la", "-o", abs_path, lcf] + link_args,
        check=False,
    )
    if result.returncode != 0:
        return result.returncode

    result = subprocess.run(
        tuconv_cmd + ["-Fs24", abs_path],
        check=False,
    )
    return result.returncode


def cmd_s242ngp(s24_path: str) -> int:
    s24_path = os.path.normpath(s24_path)
    workdir = os.path.dirname(s24_path) or "."
    s24_name = os.path.basename(s24_path)

    s242ngp_cmd = _resolve_tool("s242ngp")
    if not s242ngp_cmd:
        return 2

    result = subprocess.run(
        s242ngp_cmd + [s24_name],
        cwd=workdir,
        check=False,
    )
    return result.returncode


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: build_utils.py <clean|move|compile|s242ngp> [args...]", file=sys.stderr)
        return 2

    cmd = argv[1]
    if cmd == "clean":
        return cmd_clean()
    if cmd == "move":
        if len(argv) != 4:
            print("Usage: build_utils.py move <name> <output_dir>", file=sys.stderr)
            return 2
        return cmd_move(argv[2], argv[3])
    if cmd == "asm":
        if len(argv) != 4:
            print("Usage: build_utils.py asm <src.asm> <obj.rel>", file=sys.stderr)
            return 2
        return cmd_asm(argv[2], argv[3])
    if cmd == "compile":
        if len(argv) < 4:
            print("Usage: build_utils.py compile <src.c> <obj.rel> [cc900_flags...]", file=sys.stderr)
            return 2
        return cmd_compile(argv[2], argv[3], argv[4:])
    if cmd == "link":
        if len(argv) < 4:
            print("Usage: build_utils.py link <abs> <lcf> [objs/libs...]", file=sys.stderr)
            return 2
        return cmd_link(argv[2], argv[3], argv[4:])
    if cmd == "s242ngp":
        if len(argv) != 3:
            print("Usage: build_utils.py s242ngp <file.s24>", file=sys.stderr)
            return 2
        return cmd_s242ngp(argv[2])
    if cmd == "copy":
        if len(argv) != 4:
            print("Usage: build_utils.py copy <src> <dst>", file=sys.stderr)
            return 2
        return cmd_copy(argv[2], argv[3])

    print(f"Unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
