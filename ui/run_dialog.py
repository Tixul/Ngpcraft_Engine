"""
ui/run_dialog.py - Emulator/ROM launcher configuration dialog (Phase 5).

Stores selections in QSettings:
  - run/emulator_path
  - run/rom_path
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PyQt6.QtCore import QProcess, QSettings
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from i18n.lang import tr


def _detect_emulator() -> str | None:
    for cmd in ("mednafen", "race", "neopop"):
        found = shutil.which(cmd)
        if found:
            return found
    return None


def _detect_rom(project_dir: Path) -> Path | None:
    roots = [project_dir]
    for sub in ("build", "out", "bin", "dist"):
        d = project_dir / sub
        if d.exists():
            roots.insert(0, d)

    best: Path | None = None
    best_m = -1.0
    for root in roots:
        for ext in (".ngp", ".ngc"):
            for cand in root.glob(f"*{ext}"):
                try:
                    m = cand.stat().st_mtime
                except OSError:
                    continue
                if m > best_m:
                    best_m = m
                    best = cand
    return best


class RunDialog(QDialog):
    """Collect emulator and ROM paths, then launch the built game binary."""

    def __init__(self, project_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("run.title"))
        self.setModal(True)
        self.setMinimumWidth(660)

        self._project_dir = project_dir
        self._settings = QSettings("NGPCraft", "Engine")

        self._build_ui()
        self._load_settings()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        root.addWidget(QLabel(tr("run.hint", path=str(self._project_dir))))

        # Emulator row
        emu_row = QHBoxLayout()
        emu_row.addWidget(QLabel(tr("run.emu")))
        self._emu = QLineEdit()
        self._emu.setPlaceholderText(tr("run.emu_ph"))
        emu_row.addWidget(self._emu, 1)
        btn_emu = QPushButton(tr("run.browse"))
        btn_emu.clicked.connect(self._browse_emu)
        emu_row.addWidget(btn_emu)
        root.addLayout(emu_row)

        # ROM row
        rom_row = QHBoxLayout()
        rom_row.addWidget(QLabel(tr("run.rom")))
        self._rom = QLineEdit()
        self._rom.setPlaceholderText(tr("run.rom_ph"))
        rom_row.addWidget(self._rom, 1)
        btn_rom = QPushButton(tr("run.browse"))
        btn_rom.clicked.connect(self._browse_rom)
        rom_row.addWidget(btn_rom)
        root.addLayout(rom_row)

        # Actions row
        act = QHBoxLayout()
        btn_auto = QPushButton(tr("run.auto_detect"))
        btn_auto.clicked.connect(self._auto_detect)
        act.addWidget(btn_auto)

        btn_clear = QPushButton(tr("run.clear"))
        btn_clear.clicked.connect(self._clear_saved)
        act.addWidget(btn_clear)

        act.addStretch()

        btn_run = QPushButton(tr("run.run_now"))
        btn_run.clicked.connect(self._run_now)
        act.addWidget(btn_run)

        btn_save = QPushButton(tr("run.save"))
        btn_save.clicked.connect(self._save)
        act.addWidget(btn_save)

        btn_cancel = QPushButton(tr("run.cancel"))
        btn_cancel.clicked.connect(self.reject)
        act.addWidget(btn_cancel)

        root.addLayout(act)

    # ------------------------------------------------------------------
    def _load_settings(self) -> None:
        self._emu.setText(self._settings.value("run/emulator_path", "", str))
        self._rom.setText(self._settings.value("run/rom_path", "", str))

    def _save(self) -> None:
        self._settings.setValue("run/emulator_path", self._emu.text().strip())
        self._settings.setValue("run/rom_path", self._rom.text().strip())
        self.accept()

    def _browse_emu(self) -> None:
        start = self._emu.text().strip() or str(self._project_dir)
        p, _ = QFileDialog.getOpenFileName(self, tr("run.pick_emu"), start, tr("run.emu_filter"))
        if p:
            self._emu.setText(p)

    def _browse_rom(self) -> None:
        start = self._rom.text().strip() or str(self._project_dir)
        p, _ = QFileDialog.getOpenFileName(self, tr("run.pick_rom"), start, tr("run.rom_filter"))
        if p:
            self._rom.setText(p)

    def _auto_detect(self) -> None:
        emu = _detect_emulator()
        if emu:
            self._emu.setText(emu)
        rom = _detect_rom(self._project_dir)
        if rom:
            self._rom.setText(str(rom))

    def _clear_saved(self) -> None:
        self._settings.remove("run/emulator_path")
        self._settings.remove("run/rom_path")
        self._emu.setText("")
        self._rom.setText("")

    def _run_now(self) -> None:
        emu = self._emu.text().strip()
        rom = self._rom.text().strip()
        if not emu:
            QMessageBox.warning(self, tr("run.title"), tr("run.no_emu"))
            return
        if not Path(emu).exists():
            QMessageBox.warning(self, tr("run.title"), tr("run.bad_emu", path=emu))
            return
        if not rom:
            QMessageBox.warning(self, tr("run.title"), tr("run.no_rom"))
            return
        rp = Path(rom)
        if not rp.exists():
            QMessageBox.warning(self, tr("run.title"), tr("run.bad_rom", path=rom))
            return

        ok = QProcess.startDetached(str(emu), [str(rp)], str(rp.parent))
        if not ok:
            QMessageBox.warning(self, tr("run.title"), tr("run.fail", emu=emu))
            return

        # Save on successful run so user doesn't have to reconfigure each time.
        self._settings.setValue("run/emulator_path", emu)
        self._settings.setValue("run/rom_path", str(rp))
