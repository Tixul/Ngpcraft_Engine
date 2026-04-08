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


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


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

    thome = os.environ.get("THOME", "")
    asm900_from_thome = os.path.join(thome, "BIN", "asm900.exe") if thome else ""
    asm900 = asm900_from_thome if (asm900_from_thome and os.path.exists(asm900_from_thome)) else shutil.which("asm900")
    if not asm900:
        print("asm900 not found (set THOME or PATH).", file=sys.stderr)
        return 2

    # asm900 always writes <source_basename>.rel next to the source file.
    # Run it from the source directory so the output lands predictably.
    src_dir = os.path.dirname(src) or "."
    src_name = os.path.basename(src)
    rel_name = os.path.splitext(src_name)[0] + ".rel"
    rel_out = os.path.join(src_dir, rel_name)

    result = subprocess.run(
        [asm900, "-g", src_name],
        cwd=src_dir,
        check=False,
    )
    if result.returncode != 0:
        return result.returncode

    # Move the .rel to the expected build/obj path.
    if os.path.normpath(rel_out) != os.path.normpath(obj):
        shutil.move(rel_out, obj)
    return 0


def cmd_compile(src: str, obj: str, extra_flags: list[str]) -> int:
    src = os.path.normpath(src)
    obj = os.path.normpath(obj)
    project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

    os.makedirs(os.path.dirname(obj) or ".", exist_ok=True)

    thome = os.environ.get("THOME", "")
    cc900_from_thome = os.path.join(thome, "BIN", "cc900.exe") if thome else ""
    cc900 = cc900_from_thome if (cc900_from_thome and os.path.exists(cc900_from_thome)) else shutil.which("cc900")
    if not cc900:
        print("cc900 not found (set THOME or PATH).", file=sys.stderr)
        return 2

    # cc900 invokes thc1/thc2 as relative paths, so it must run from its own
    # directory. Use absolute paths for source, output, and includes.
    cc900_dir = os.path.dirname(os.path.abspath(cc900))
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
    cmd = [cc900, "-c", "-O3"] + include_flags + abs_extra_flags + [src_abs, "-o", obj_abs]
    result = subprocess.run(
        cmd,
        cwd=cc900_dir,
        check=False,
    )
    return result.returncode


def cmd_link(abs_path: str, lcf: str, link_args: list[str]) -> int:
    """Invoke tulink then tuconv using THOME for tool discovery."""
    thome = os.environ.get("THOME", "")
    tulink_from_thome = os.path.join(thome, "BIN", "tulink.exe") if thome else ""
    tulink = tulink_from_thome if (tulink_from_thome and os.path.exists(tulink_from_thome)) else shutil.which("tulink")
    if not tulink:
        print("tulink not found (set THOME or PATH).", file=sys.stderr)
        return 2

    tuconv_from_thome = os.path.join(thome, "BIN", "tuconv.exe") if thome else ""
    tuconv = tuconv_from_thome if (tuconv_from_thome and os.path.exists(tuconv_from_thome)) else shutil.which("tuconv")
    if not tuconv:
        print("tuconv not found (set THOME or PATH).", file=sys.stderr)
        return 2

    result = subprocess.run(
        [tulink, "-la", "-o", abs_path, lcf] + link_args,
        check=False,
    )
    if result.returncode != 0:
        return result.returncode

    result = subprocess.run(
        [tuconv, "-Fs24", abs_path],
        check=False,
    )
    return result.returncode


def cmd_s242ngp(s24_path: str) -> int:
    s24_path = os.path.normpath(s24_path)
    workdir = os.path.dirname(s24_path) or "."
    s24_name = os.path.basename(s24_path)

    thome = os.environ.get("THOME", "")
    s242ngp_from_thome = os.path.join(thome, "BIN", "s242ngp.exe") if thome else ""
    s242ngp = s242ngp_from_thome if (s242ngp_from_thome and os.path.exists(s242ngp_from_thome)) else shutil.which("s242ngp")
    if not s242ngp:
        print("s242ngp not found (set THOME or PATH).", file=sys.stderr)
        return 2

    result = subprocess.run(
        [s242ngp, s24_name],
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

    print(f"Unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
