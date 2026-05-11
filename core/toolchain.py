"""core/toolchain.py — Toshiba T900 toolchain resolution and subprocess env setup.

Centralizes everything build-time tooling related:
- Finding the T900 root (cc900/asm900/tulink/tuconv/s242ngp/...)
- Finding a usable Python interpreter for the Makefile helper scripts
- Finding GNU make
- Producing a QProcessEnvironment with PATH/THOME augmented so `make`
  works even when the user has not touched the Windows system PATH.

Resolution order for both T900 and Python:
  1. Explicit argument (UI override)
  2. QSettings("NGPCraft", "Engine") keys "toolchain/t900_path" / "toolchain/python_path"
  3. Environment (THOME / shutil.which)
  4. Heuristic scan of common install locations
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from PyQt6.QtCore import QProcessEnvironment, QSettings


# Tools cc900 needs at link/build time. cc900 is the only mandatory one
# for compilation; the others are checked individually so the UI can
# report exactly what is missing.
T900_TOOL_NAMES: tuple[str, ...] = (
    "cc900.exe",
    "asm900.exe",
    "thc1.exe",
    "thc2.exe",
    "tulink.exe",
    "tuconv.exe",
)

# s242ngp is shipped separately (not part of the Toshiba SDK proper) but
# is usually dropped into T900\BIN alongside the rest. Treat it as optional
# for the install check but warn loudly if absent since the final ROM step
# needs it.
T900_OPTIONAL_TOOL_NAMES: tuple[str, ...] = ("s242ngp.exe",)


SETTINGS_ORG = "NGPCraft"
SETTINGS_APP = "Engine"
KEY_T900_PATH = "toolchain/t900_path"
KEY_PYTHON_PATH = "toolchain/python_path"


def _settings() -> QSettings:
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def _has_cc900(root: Path) -> bool:
    """Treat a folder as a T900 root if it contains BIN/cc900.exe (any case)."""
    if not root or not root.exists():
        return False
    for sub in ("BIN", "bin"):
        if (root / sub / "cc900.exe").exists():
            return True
    return (root / "cc900.exe").exists()


def _t900_bin_dir(root: Path) -> Path | None:
    """Return the BIN/ subfolder inside a resolved T900 root."""
    for sub in ("BIN", "bin"):
        if (root / sub).is_dir():
            return root / sub
    if (root / "cc900.exe").exists():
        return root
    return None


def _candidate_t900_roots() -> Iterable[Path]:
    """Yield heuristic locations where users typically drop the Toshiba SDK."""
    home = Path(os.path.expanduser("~"))
    return [
        Path(r"C:\t900"),
        Path(r"C:\T900"),
        Path(r"C:\ngpcbins\T900"),
        Path(r"C:\ngpcbins\t900"),
        home / "Desktop" / "T900",
        home / "Desktop" / "t900",
        home / "Documents" / "T900",
        home / "Documents" / "t900",
        Path(r"C:\Program Files\T900"),
        Path(r"C:\Program Files (x86)\T900"),
    ]


def find_t900_root(explicit: str | os.PathLike | None = None) -> Path | None:
    """Resolve the T900 root directory, or None if nothing usable was found.

    Resolution order: explicit arg → QSettings → THOME env var → heuristic scan.
    """
    # 1. Explicit
    if explicit:
        p = Path(str(explicit))
        if _has_cc900(p):
            return p

    # 2. QSettings
    stored = _settings().value(KEY_T900_PATH, "", str) or ""
    if stored:
        p = Path(stored)
        if _has_cc900(p):
            return p

    # 3. THOME env var
    thome = os.environ.get("THOME", "")
    if thome:
        p = Path(thome)
        if _has_cc900(p):
            return p

    # 4. Heuristic scan
    seen: set[Path] = set()
    for cand in _candidate_t900_roots():
        try:
            real = cand.resolve()
        except OSError:
            real = cand
        if real in seen:
            continue
        seen.add(real)
        if _has_cc900(cand):
            return cand
    return None


def _is_store_stub(p: Path) -> bool:
    """Detect the Microsoft Store python.exe execution alias.

    The Store ships a 0-byte (or tiny reparse-point) executable in
    %LOCALAPPDATA%\\Microsoft\\WindowsApps that, when run by a subprocess,
    pops up the Store instead of executing Python. shutil.which() happily
    returns it. We have to filter it out or the build silently dies.
    """
    s = str(p).replace("\\", "/").lower()
    if "windowsapps" not in s:
        return False
    try:
        return p.stat().st_size < 50_000  # real python.exe is ~95-110 KB
    except OSError:
        return True


def _python_works(p: Path) -> bool:
    """Validate a python.exe candidate by running it with --version (2s timeout)."""
    if _is_store_stub(p):
        return False
    try:
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        result = subprocess.run(
            [str(p), "--version"],
            capture_output=True,
            timeout=2.0,
            check=False,
            creationflags=flags,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False


def find_python(explicit: str | os.PathLike | None = None) -> Path | None:
    """Resolve a python interpreter usable by the Makefile (`$(PYTHON) ...`).

    The Makefile prefers `py -3` then `python3` then `python`; we mirror that
    but always return an absolute path so we can prepend its folder to PATH.
    Frozen PyInstaller exes don't expose a re-usable python.exe, so when the
    engine is running frozen we ignore sys.executable. The Microsoft Store
    python.exe stub is filtered out — `shutil.which("python")` happily
    returns it but it pops up the Store instead of running Python.
    """
    # 1. Explicit (trust the user — but still skip obvious stubs)
    if explicit:
        p = Path(str(explicit))
        if p.exists() and p.is_file() and not _is_store_stub(p):
            return p

    # 2. QSettings
    stored = _settings().value(KEY_PYTHON_PATH, "", str) or ""
    if stored:
        p = Path(stored)
        if p.exists() and p.is_file() and not _is_store_stub(p):
            return p

    # 3. sys.executable if not frozen (running from source — best match)
    if not getattr(sys, "frozen", False):
        try:
            p = Path(sys.executable)
            if (
                p.exists()
                and p.is_file()
                and p.name.lower() != "ngpcraftengine.exe"
                and not _is_store_stub(p)
            ):
                return p
        except Exception:
            pass

    # 4. PATH lookup — validate each candidate actually runs (catches stubs
    # and broken installs that shutil.which has no way to see through).
    for name in ("py.exe", "py", "python3.exe", "python3", "python.exe", "python"):
        found = shutil.which(name)
        if not found:
            continue
        p = Path(found)
        if _is_store_stub(p):
            continue
        if _python_works(p):
            return p
    return None


def find_make(t900_root: Path | None = None) -> Path | None:
    """Resolve GNU make. Prefers T900\\BIN\\make.exe (it ships with the SDK)."""
    if t900_root is not None:
        bin_dir = _t900_bin_dir(t900_root)
        if bin_dir is not None:
            for name in ("make.exe", "gmake.exe", "mingw32-make.exe"):
                p = bin_dir / name
                if p.exists():
                    return p
    for name in ("make", "gmake", "mingw32-make"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def toolchain_status(
    explicit_t900: str | os.PathLike | None = None,
    explicit_python: str | os.PathLike | None = None,
) -> dict:
    """Snapshot of toolchain availability used by the contract check + config dialog.

    Returns a dict with:
      - t900_root: Path | None
      - tools: dict[name, Path | None]  (each T900_TOOL_NAMES + optional)
      - python: Path | None
      - make: Path | None
      - ok: bool — True iff everything required to build is present
    """
    t900 = find_t900_root(explicit_t900)
    python = find_python(explicit_python)
    make = find_make(t900)

    tools: dict[str, Path | None] = {}
    bin_dir = _t900_bin_dir(t900) if t900 is not None else None
    for name in T900_TOOL_NAMES + T900_OPTIONAL_TOOL_NAMES:
        if bin_dir is None:
            tools[name] = None
            continue
        p = bin_dir / name
        tools[name] = p if p.exists() else None

    required_missing = [n for n in T900_TOOL_NAMES if tools.get(n) is None]
    ok = (
        t900 is not None
        and python is not None
        and make is not None
        and not required_missing
    )

    return {
        "t900_root": t900,
        "tools": tools,
        "python": python,
        "make": make,
        "ok": ok,
    }


def make_subprocess_env(
    explicit_t900: str | os.PathLike | None = None,
    explicit_python: str | os.PathLike | None = None,
) -> QProcessEnvironment:
    """Build a QProcessEnvironment with PATH and THOME ready for `make`.

    Starts from the system env, then PREPENDS to PATH (in order):
      - T900\\BIN (so make/cc900/asm900/tulink/tuconv/s242ngp resolve)
      - Python interpreter folder (so $(PYTHON) and bare `python` resolve)
    Sets THOME to the T900 root.

    Falls back gracefully when something is missing — callers should check
    toolchain_status() first if they need to abort.
    """
    env = QProcessEnvironment.systemEnvironment()

    extra_path: list[str] = []

    t900 = find_t900_root(explicit_t900)
    if t900 is not None:
        bin_dir = _t900_bin_dir(t900)
        if bin_dir is not None:
            extra_path.append(str(bin_dir))
        env.insert("THOME", str(t900))

    python = find_python(explicit_python)
    if python is not None:
        extra_path.append(str(python.parent))
        # Some tools look at PYTHON env var explicitly; harmless to set.
        env.insert("PYTHON", str(python))

    if extra_path:
        existing = env.value("PATH", "") or env.value("Path", "")
        new_path = os.pathsep.join(extra_path + ([existing] if existing else []))
        env.insert("PATH", new_path)

    return env


def sync_build_bat(
    build_bat_path: str | os.PathLike,
    t900_root: Path | None = None,
    python_path: Path | None = None,
) -> bool:
    """Rewrite the `SET compilerPath=...` line (and optionally inject a python
    PATH augmentation) in a project's build.bat so CLI builds match what the
    engine's Build & Run button uses.

    Heuristic: only patches build.bat files that look like the template
    default — i.e. their compilerPath line points to `C:\\t900` or to a
    path that does not actually contain cc900.exe. A user who has manually
    set a working compilerPath is respected and left untouched.

    Returns True if the file was modified, False otherwise.
    """
    bat = Path(build_bat_path)
    if not bat.exists() or not bat.is_file():
        return False
    if t900_root is None:
        t900_root = find_t900_root()
    if t900_root is None:
        return False

    try:
        text = bat.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    lines = text.splitlines(keepends=False)

    current = ""
    idx = -1
    for i, raw in enumerate(lines):
        if raw.strip().lower().startswith("set compilerpath="):
            current = raw.strip().split("=", 1)[1].strip().strip('"')
            idx = i
            break
    if idx < 0:
        return False  # not a template-style build.bat

    # Respect a user-customized, working compilerPath.
    if current and current.lower() != r"c:\t900":
        if _has_cc900(Path(current)):
            return False  # custom path that works — don't touch it

    new_compiler_line = f"SET compilerPath={t900_root}"
    if lines[idx] == new_compiler_line:
        already_synced_compiler = True
    else:
        lines[idx] = new_compiler_line
        already_synced_compiler = False

    # Optional python PATH augmentation. Insert (or refresh) a marked line
    # right after the compilerPath line so users can see it and we can
    # update it idempotently on the next sync.
    marker = "REM --- ngpcraft auto: python path ---"
    python_line = ""
    if python_path is not None:
        python_line = f'SET PATH=%PATH%;{python_path.parent}'

    # Find an existing auto block (marker + the next line) and either
    # update it, remove it, or leave it alone.
    auto_start = -1
    for i, raw in enumerate(lines):
        if raw.strip() == marker:
            auto_start = i
            break

    changed_python = False
    if auto_start >= 0:
        existing = lines[auto_start + 1] if auto_start + 1 < len(lines) else ""
        if python_path is None:
            # Remove the auto block.
            del lines[auto_start : auto_start + 2]
            changed_python = True
        elif existing != python_line:
            lines[auto_start + 1] = python_line
            changed_python = True
    elif python_path is not None:
        lines.insert(idx + 1, marker)
        lines.insert(idx + 2, python_line)
        changed_python = True

    if already_synced_compiler and not changed_python:
        return False

    try:
        bat.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True
    except OSError:
        return False


def save_t900_path(path: str | os.PathLike | None) -> None:
    """Persist the user-chosen T900 root (or clear it if path is None/empty)."""
    s = _settings()
    if path:
        s.setValue(KEY_T900_PATH, str(path))
    else:
        s.remove(KEY_T900_PATH)


def save_python_path(path: str | os.PathLike | None) -> None:
    """Persist the user-chosen python.exe (or clear it if path is None/empty)."""
    s = _settings()
    if path:
        s.setValue(KEY_PYTHON_PATH, str(path))
    else:
        s.remove(KEY_PYTHON_PATH)
