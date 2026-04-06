"""
core/app_updater.py — Check for new NgpCraft Engine releases on GitHub.

Uses only the stdlib (urllib + json); no pip dependencies.
Returns None on any network/parse failure so callers can treat it as
"no update info available" rather than crashing.

Public API:
    check_latest_release(repo, timeout) -> str | None
        Returns the latest version tag (e.g. "1.2.0") or None.

    is_newer(current, latest) -> bool
        True when latest > current (numeric tuple comparison).
"""

from __future__ import annotations

import json
import urllib.request


def check_latest_release(
    repo: str = "Tixul/Ngpcraft_Engine",
    timeout: int = 5,
) -> str | None:
    """Query the GitHub Releases API for *repo* and return the latest version tag.

    The tag is stripped of a leading ``v`` so ``"v1.2.0"`` becomes ``"1.2.0"``.
    Returns ``None`` on any network or parse error (no exception is raised).
    """
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "NgpCraft-Engine",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data: dict = json.loads(resp.read())
        tag: str = data.get("tag_name") or ""
        return tag.lstrip("v") if tag else None
    except Exception:
        return None


def is_newer(current: str, latest: str) -> bool:
    """Return ``True`` if *latest* is strictly greater than *current*.

    Comparison is done component-by-component on integer parts so
    ``"1.10.0" > "1.9.0"`` works correctly.
    Non-numeric components are treated as 0.
    """

    def _parse(v: str) -> tuple[int, ...]:
        parts = []
        for p in v.split("."):
            try:
                parts.append(int(p))
            except ValueError:
                parts.append(0)
        return tuple(parts)

    return _parse(latest) > _parse(current)
