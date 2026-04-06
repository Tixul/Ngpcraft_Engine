"""
ui/tabs/_project_path_mixin.py - Shared path helpers for tabs that own a project file.

Any tab that stores ``self._project_path: Path | None`` can inherit this mixin
to get the ``_project_dir`` property and the ``_rel()`` / ``_abs()`` converters
without duplicating the implementation.

Tabs using this mixin: ProjectTab, BundleTab, TilemapTab.
"""
from __future__ import annotations

from pathlib import Path


class ProjectPathMixin:
    """Mixin that provides project-relative path helpers.

    Requirements for the host class:
    - Must set ``self._project_path: Path | None`` before calling any method.
    """

    # Type annotation for type-checkers; the value is set by the host class.
    _project_path: "Path | None"

    @property
    def _project_dir(self) -> Path | None:
        """Parent directory of the project file, or None in free mode."""
        return self._project_path.parent if self._project_path else None

    def _rel(self, abs_path: Path) -> str:
        """Return *abs_path* relative to the project directory, or as-is if not possible."""
        if self._project_dir:
            try:
                return str(abs_path.relative_to(self._project_dir))
            except ValueError:
                pass
        return str(abs_path)

    def _abs(self, rel: str) -> Path:
        """Resolve a project-relative path string to an absolute Path."""
        p = Path(rel)
        if not p.is_absolute() and self._project_dir:
            return self._project_dir / p
        return p
