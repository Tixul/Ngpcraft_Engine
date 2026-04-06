"""
ui/tool_finder.py - Shared helpers for locating external pipeline scripts.

Tabs use QSettings to remember the last chosen path, and fall back to a few
common locations relative to the NgpCraft_engine repo.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings


def script_dialog_start_dir(settings_key: str, fallback: Path | None = None) -> str:
    """
    Return a reasonable start directory for a file dialog when asking the user to pick a tool script.

    Order:
      1) Parent dir of configured path for this settings_key (if any)
      2) scripts/last_dir (shared)
      3) fallback
    """
    settings = QSettings("NGPCraft", "Engine")
    configured = (settings.value(settings_key, "", type=str) or "").strip()
    if configured:
        p = Path(configured)
        if p.exists():
            return str(p.parent)
        if p.parent.exists():
            return str(p.parent)

    last = (settings.value("scripts/last_dir", "", type=str) or "").strip()
    if last and Path(last).exists():
        return last

    return str(fallback) if fallback else ""


def remember_script_path(settings_key: str, script_path: Path) -> None:
    """Persist a user-selected tool path and update the shared last-dir hint."""
    settings = QSettings("NGPCraft", "Engine")
    settings.setValue(settings_key, str(script_path))
    try:
        settings.setValue("scripts/last_dir", str(script_path.parent))
    except Exception:
        pass


def find_script(settings_key: str, candidates: list[Path]) -> Path | None:
    """
    Return a valid script path.

    1) If QSettings(settings_key) points to an existing file, use it.
    2) Else, pick the first existing file from candidates and persist it.
    3) Else, return None (caller should prompt the user).
    """
    settings = QSettings("NGPCraft", "Engine")
    configured = settings.value(settings_key, "", type=str)
    if configured and Path(configured).exists():
        return Path(configured)

    for p in candidates:
        if p.exists():
            settings.setValue(settings_key, str(p))
            return p
    return None


def default_candidates(repo_root: Path, tool_filename: str) -> list[Path]:
    """
    Return common candidate paths for a pipeline tool filename.

    repo_root is expected to be the NgpCraft_engine directory (contains core/, ui/).
    """
    return [
        repo_root / "templates" / "NgpCraft_base_template" / "tools" / tool_filename,
        repo_root.parent.parent / "NgpCraft_base_template" / "tools" / tool_filename,
        repo_root.parent / "NgpCraft_base_template" / "tools" / tool_filename,
        repo_root.parent / "tools" / tool_filename,
        repo_root / "tools" / tool_filename,
        repo_root / tool_filename,
    ]
