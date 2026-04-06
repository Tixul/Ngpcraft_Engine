#!/usr/bin/env python3
"""
ngpc_project_init.py - Create a new NGPC project from this template.

Features:
- Copies the template directory to a new destination
- Skips generated artifacts (bin/build/__pycache__, etc.)
- Renames project identifiers:
  - makefile: NAME=<rom_name>
  - build.bat: SET romName=<rom_name>
  - src/core/carthdr.h: CartTitle[12] (strict 12-char ASCII)

Usage:
    python tools/ngpc_project_init.py C:/dev/MyNgpcGame --name "My NGPC Game"
    python tools/ngpc_project_init.py C:/dev/MyNgpcGame --name "My NGPC Game" --rom-name mygame
    python tools/ngpc_project_init.py C:/dev/MyNgpcGame --dry-run
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path


def sanitize_rom_name(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9_]", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    if not value:
        value = "main"
    return value


def derive_cart_title(name: str) -> str:
    # Strict ASCII, 12 chars max, padded with spaces.
    text = name.upper()
    text = "".join(ch if ("A" <= ch <= "Z" or "0" <= ch <= "9" or ch == " ") else " " for ch in text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text[:12]
    return text.ljust(12)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, data: str) -> None:
    path.write_text(data, encoding="utf-8")


def patch_makefile(path: Path, rom_name: str) -> None:
    content = read_text(path)
    patched = re.sub(r"(?m)^NAME\s*=\s*.+$", f"NAME = {rom_name}", content)
    if patched == content:
        raise RuntimeError(f"Could not patch NAME in {path}")
    write_text(path, patched)


def patch_build_bat(path: Path, rom_name: str) -> None:
    content = read_text(path)
    patched = re.sub(r"(?m)^SET romName=.*$", f"SET romName={rom_name}", content)
    if patched == content:
        raise RuntimeError(f"Could not patch romName in {path}")
    write_text(path, patched)


def patch_carthdr(path: Path, cart_title_12: str) -> None:
    content = read_text(path)
    patched = re.sub(
        r'const char CartTitle\[12\]\s*=\s*"[^"]*";',
        f'const char CartTitle[12] = "{cart_title_12}";',
        content,
    )
    if patched == content:
        raise RuntimeError(f"Could not patch CartTitle in {path}")
    write_text(path, patched)


def ignore_template_artifacts(dir_path: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for n in names:
        low = n.lower()
        if low in {"bin", "build", "__pycache__", ".git", ".vs", ".vscode"}:
            ignored.add(n)
            continue
        if low.endswith(".pyc"):
            ignored.add(n)
            continue
        if low in {"main.abs", "main.s24", "main.ngp", "main.ngc", "main.map", "main.lst"}:
            ignored.add(n)
            continue
        # Skip old object artifacts if any remain.
        if low.endswith(".rel"):
            ignored.add(n)
            continue
    return ignored


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Create a new project from NgpCraft_base_template")
    parser.add_argument("destination", help="Destination project directory (must not exist unless --force)")
    parser.add_argument("--name", default=None, help="Human project name (default: destination folder name)")
    parser.add_argument("--rom-name", default=None, help="ROM filename/base (default: derived from --name)")
    parser.add_argument("--cart-title", default=None, help="Cart title (12 chars max; default: derived from --name)")
    parser.add_argument("--force", action="store_true", help="Overwrite destination if it exists")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing files")
    args = parser.parse_args(argv)

    template_root = Path(__file__).resolve().parent.parent
    destination = Path(args.destination).resolve()

    proj_name = args.name if args.name else destination.name
    rom_name = sanitize_rom_name(args.rom_name if args.rom_name else proj_name)
    cart_title = args.cart_title if args.cart_title is not None else derive_cart_title(proj_name)
    cart_title = derive_cart_title(cart_title)

    if args.dry_run:
        print("[dry-run] template:   %s" % template_root)
        print("[dry-run] destination:%s" % destination)
        print("[dry-run] name:       %s" % proj_name)
        print("[dry-run] rom_name:   %s" % rom_name)
        print("[dry-run] cart_title: '%s'" % cart_title)
        print("[dry-run] would copy template and patch makefile/build.bat/carthdr.h")
        return 0

    if destination.exists():
        if not args.force:
            print("Error: destination exists. Use --force to overwrite.", file=sys.stderr)
            return 1
        shutil.rmtree(destination)

    shutil.copytree(template_root, destination, ignore=ignore_template_artifacts)

    patch_makefile(destination / "makefile", rom_name)
    patch_build_bat(destination / "build.bat", rom_name)
    patch_carthdr(destination / "src" / "core" / "carthdr.h", cart_title)

    print("Created:    %s" % destination)
    print("ROM name:   %s" % rom_name)
    print("Cart title: '%s'" % cart_title)
    print("")
    print("Next steps:")
    print("1. Open the new folder.")
    print("2. Adjust build.bat compilerPath if needed.")
    print("3. Run: make clean && make && make move_files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
