"""
ngpcraft_engine.py - Entry point for NgpCraft Engine.

Usage:
    python ngpcraft_engine.py
    python ngpcraft_engine.py path/to/project.ngpcraft        # open directly

    # Headless export (no GUI — safe on build servers):
    python ngpcraft_engine.py --export project.ngpcraft
    python ngpcraft_engine.py --export project.ngpcraft --scene acte1
    python ngpcraft_engine.py --export project.ngpcraft --sprite-tool /path/to/ngpc_sprite_export.py
    python ngpcraft_engine.py --export project.ngpcraft --tilemap-tool /path/to/ngpc_tilemap.py

    # Generate the validation suite (4 mini projects):
    python ngpcraft_engine.py --validation-suite path/to/output_folder
    python ngpcraft_engine.py --validation-run path/to/output_folder
    python ngpcraft_engine.py --validation-run path/to/output_folder --build
    python ngpcraft_engine.py --validation-run path/to/output_folder --build --smoke-run

Requires: PyQt6, Pillow
    pip install PyQt6 Pillow
"""

from __future__ import annotations

import sys
from pathlib import Path


def _run_headless(args: list[str]) -> int:
    """Parse --export sub-arguments and run headless export (no QApplication)."""
    from core.headless_export import export_project

    project_path:   Path | None = None
    scene_filter:   str  | None = None
    sprite_script:  Path | None = None
    tilemap_script: Path | None = None

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--scene" and i + 1 < len(args):
            scene_filter = args[i + 1]
            i += 2
        elif a == "--sprite-tool" and i + 1 < len(args):
            sprite_script = Path(args[i + 1])
            i += 2
        elif a == "--tilemap-tool" and i + 1 < len(args):
            tilemap_script = Path(args[i + 1])
            i += 2
        elif not a.startswith("--"):
            project_path = Path(a)
            i += 1
        else:
            i += 1

    if project_path is None:
        print(
            "Usage: ngpcraft_engine.py --export project.ngpcraft"
            " [--scene NAME]"
            " [--sprite-tool PATH]"
            " [--tilemap-tool PATH]",
            file=sys.stderr,
        )
        return 1

    return export_project(project_path, scene_filter, sprite_script, tilemap_script)


def _run_validation_suite(args: list[str]) -> int:
    """Generate the bundled validation suite projects from the real template."""
    from core.project_scaffold import find_template_root
    from core.validation_suite import build_validation_suite

    if not args:
        print(
            "Usage: ngpcraft_engine.py --validation-suite output_folder",
            file=sys.stderr,
        )
        return 1

    destination = Path(args[0])
    template_root = find_template_root()
    if template_root is None:
        print("ERROR: NGPC template root not found.", file=sys.stderr)
        return 1

    try:
        build_validation_suite(destination_root=destination, template_root=template_root)
    except Exception as exc:
        print(f"ERROR: cannot generate validation suite: {exc}", file=sys.stderr)
        return 1
    return 0


def _run_validation_run(args: list[str]) -> int:
    """Generate the validation suite and run exports on each project."""
    from core.project_scaffold import find_template_root
    from core.validation_runner import run_validation_suite

    if not args:
        print(
            "Usage: ngpcraft_engine.py --validation-run output_folder [--build] [--smoke-run]",
            file=sys.stderr,
        )
        return 1

    destination: Path | None = None
    build_projects = False
    smoke_run = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--build":
            build_projects = True
        elif arg == "--smoke-run":
            smoke_run = True
        elif not arg.startswith("--") and destination is None:
            destination = Path(arg)
        i += 1
    if destination is None:
        print(
            "Usage: ngpcraft_engine.py --validation-run output_folder [--build] [--smoke-run]",
            file=sys.stderr,
        )
        return 1
    if smoke_run:
        build_projects = True

    template_root = find_template_root()
    if template_root is None:
        print("ERROR: NGPC template root not found.", file=sys.stderr)
        return 1

    try:
        results = run_validation_suite(
            destination_root=destination,
            template_root=template_root,
            build_projects=build_projects,
            smoke_run=smoke_run,
        )
    except Exception as exc:
        print(f"ERROR: cannot run validation suite: {exc}", file=sys.stderr)
        return 1
    return 0 if all(
        r.export_exit_code == 0
        and r.generated_checks_ok
        and (not r.build_attempted or r.build_ok)
        and (not r.runtime_smoke_attempted or r.runtime_smoke_ok)
        for r in results
    ) else 1


def main() -> int:
    """Start NgpCraft Engine in GUI mode or run headless export.

    GUI mode is the default and opens either the requested project file or the
    start dialog. When `--export` is present, the function skips Qt entirely and
    delegates to `core.headless_export.export_project`, which makes it safe to
    use from CI/build scripts without a display server.
    """
    # ------------------------------------------------------------------
    # Headless mode — no QApplication, no display required
    # ------------------------------------------------------------------
    if "--export" in sys.argv:
        idx = sys.argv.index("--export")
        return _run_headless(sys.argv[idx + 1:])
    if "--validation-suite" in sys.argv:
        idx = sys.argv.index("--validation-suite")
        return _run_validation_suite(sys.argv[idx + 1:])
    if "--validation-run" in sys.argv:
        idx = sys.argv.index("--validation-run")
        return _run_validation_run(sys.argv[idx + 1:])

    # ------------------------------------------------------------------
    # GUI mode
    # ------------------------------------------------------------------
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication

    from i18n.lang import load_from_settings
    from ui.main_window import MainWindow
    from ui.start_dialog import StartDialog

    app = QApplication(sys.argv)
    app.setApplicationName("NgpCraft Engine")
    app.setOrganizationName("NGPC")

    # Application icon (works both in dev and PyInstaller bundle)
    _ico = Path(__file__).parent / "assets" / "ngpcraft.ico"
    if not _ico.exists():
        # PyInstaller: look next to the frozen exe
        _ico = Path(sys.executable).parent / "assets" / "ngpcraft.ico"
    if _ico.exists():
        app.setWindowIcon(QIcon(str(_ico)))

    load_from_settings()

    # Allow direct open via command-line argument
    if len(sys.argv) >= 2:
        project_path = Path(sys.argv[1])
        is_new = not project_path.exists()
        win = MainWindow(project_path, is_new=is_new)
        win.show()
        return app.exec()

    # Show start dialog
    dlg = StartDialog()
    if dlg.exec() != StartDialog.DialogCode.Accepted:
        return 0

    if dlg.is_free_mode:
        win = MainWindow(None, is_free_mode=True)
    elif dlg.chosen_path is not None:
        win = MainWindow(dlg.chosen_path, is_new=dlg.is_new)
    else:
        return 0
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
