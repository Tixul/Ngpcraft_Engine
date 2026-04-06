"""
core/app_paths.py — Platform-agnostic user-data directory for NgpCraft Engine.

Single source of truth used by:
  - template_updater  (writes updated template here)
  - project_scaffold  (reads template from here first when frozen)
  - template_integration (reads optional modules from template)

When running from source: user_data_dir() returns None — callers fall back to
paths relative to the source tree.

When packaged (PyInstaller, sys.frozen == True):
  Windows  -> %LOCALAPPDATA%/NgpCraft Engine/
  macOS    -> ~/Library/Application Support/NgpCraft Engine/
  Linux    -> ~/.local/share/NgpCraft Engine/
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_APP_NAME = "NgpCraft Engine"
_TEMPLATE_SUBPATH = ("templates", "NgpCraft_base_template")


def user_data_dir() -> Path | None:
    """Return the writable user-data root for NgpCraft Engine, or None when
    running from source (no isolation needed in dev mode)."""
    if not getattr(sys, "frozen", False):
        return None

    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")

    return base / _APP_NAME


def user_template_root() -> Path | None:
    """Return the user-writable template path, or None when running from source."""
    d = user_data_dir()
    if d is None:
        return None
    return d.joinpath(*_TEMPLATE_SUBPATH)
