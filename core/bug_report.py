"""
core/bug_report.py — Build and open a pre-filled GitHub bug report URL.

Used by both the Help tab bug reporter and the Build dialog failure reporter.
No Qt dependency — pure stdlib.
"""

from __future__ import annotations

import platform
import sys
import urllib.parse

_GITHUB_NEW_ISSUE = "https://github.com/Tixul/Ngpcraft_Engine/issues/new"
_MAX_BODY_CHARS   = 1800   # stay well under browser URL limits (~2 000)


def _app_version() -> str:
    try:
        from core.version import APP_VERSION
        return APP_VERSION
    except Exception:
        return "unknown"


def system_info_block() -> str:
    return (
        "## Environment\n"
        f"- NgpCraft Engine: v{_app_version()}\n"
        f"- OS: {platform.system()} {platform.version()}\n"
        f"- Python: {sys.version.split()[0]}\n"
    )


def build_issue_url(
    title: str,
    body: str,
    label: str = "bug",
) -> str:
    """Return a GitHub new-issue URL with title/body/label pre-filled."""
    if len(body) > _MAX_BODY_CHARS:
        body = "…(truncated — paste full log manually)…\n\n" + body[-_MAX_BODY_CHARS:]
    params = urllib.parse.urlencode({"title": title, "body": body, "labels": label})
    return f"{_GITHUB_NEW_ISSUE}?{params}"


def open_issue_url(title: str, body: str, label: str = "bug") -> None:
    """Open the GitHub new-issue URL in the default browser."""
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl(build_issue_url(title, body, label)))
