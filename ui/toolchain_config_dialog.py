"""ui/toolchain_config_dialog.py — Configure the T900 toolchain + Python paths.

Persists user choices in QSettings ("toolchain/t900_path", "toolchain/python_path").
The values are picked up automatically by core.toolchain on the next build —
no engine restart needed.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import toolchain
from i18n.lang import tr


_OK_COLOR = "#75d17f"
_BAD_COLOR = "#e26d6d"


class ToolchainConfigDialog(QDialog):
    """Let the user pick the T900 root and (optionally) override python.exe.

    The dialog auto-detects on open and surfaces a live status line for
    every tool so the user can immediately see whether their pick is valid.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("toolchain.title"))
        self.setModal(True)
        self.setMinimumWidth(640)

        root = QVBoxLayout(self)
        root.setSpacing(8)

        intro = QLabel(tr("toolchain.intro"))
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #b8c0ca;")
        root.addWidget(intro)

        # --- T900 row -------------------------------------------------
        root.addWidget(self._section_label(tr("toolchain.t900_label")))
        t900_row = QHBoxLayout()
        self._t900_edit = QLineEdit()
        self._t900_edit.setPlaceholderText(tr("toolchain.t900_placeholder"))
        self._t900_edit.textChanged.connect(self._refresh_status)
        t900_row.addWidget(self._t900_edit, 1)
        btn_t900_browse = QPushButton(tr("toolchain.browse"))
        btn_t900_browse.clicked.connect(self._browse_t900)
        t900_row.addWidget(btn_t900_browse)
        btn_t900_detect = QPushButton(tr("toolchain.autodetect"))
        btn_t900_detect.clicked.connect(self._autodetect_t900)
        t900_row.addWidget(btn_t900_detect)
        root.addLayout(t900_row)

        # --- Python row -----------------------------------------------
        root.addWidget(self._section_label(tr("toolchain.python_label")))
        py_row = QHBoxLayout()
        self._py_edit = QLineEdit()
        self._py_edit.setPlaceholderText(tr("toolchain.python_placeholder"))
        self._py_edit.textChanged.connect(self._refresh_status)
        py_row.addWidget(self._py_edit, 1)
        btn_py_browse = QPushButton(tr("toolchain.browse"))
        btn_py_browse.clicked.connect(self._browse_python)
        py_row.addWidget(btn_py_browse)
        btn_py_detect = QPushButton(tr("toolchain.autodetect"))
        btn_py_detect.clicked.connect(self._autodetect_python)
        py_row.addWidget(btn_py_detect)
        root.addLayout(py_row)

        # --- Status panel ---------------------------------------------
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #444;")
        root.addWidget(sep)

        root.addWidget(self._section_label(tr("toolchain.status_label")))
        self._status = QLabel("")
        self._status.setTextFormat(Qt.TextFormat.RichText)
        self._status.setWordWrap(True)
        self._status.setStyleSheet(
            "QLabel { background:#1d2027; padding:8px; border-radius:4px; font-family:Consolas,monospace; }"
        )
        root.addWidget(self._status, 1)

        # --- Buttons --------------------------------------------------
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._save_and_close)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        # Prefill from QSettings if present, otherwise autodetect silently.
        s = toolchain._settings()
        t900_stored = (s.value(toolchain.KEY_T900_PATH, "", str) or "").strip()
        py_stored = (s.value(toolchain.KEY_PYTHON_PATH, "", str) or "").strip()
        if t900_stored:
            self._t900_edit.setText(t900_stored)
        else:
            found = toolchain.find_t900_root()
            if found is not None:
                self._t900_edit.setText(str(found))
        if py_stored:
            self._py_edit.setText(py_stored)
        else:
            found_py = toolchain.find_python()
            if found_py is not None:
                self._py_edit.setText(str(found_py))

        self._refresh_status()

    # ------------------------------------------------------------------
    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(f"<b>{text}</b>")
        return lbl

    def _browse_t900(self) -> None:
        start = self._t900_edit.text().strip() or "C:/"
        path = QFileDialog.getExistingDirectory(self, tr("toolchain.pick_t900"), start)
        if path:
            self._t900_edit.setText(path)

    def _browse_python(self) -> None:
        start = self._py_edit.text().strip() or "C:/"
        path, _ = QFileDialog.getOpenFileName(
            self, tr("toolchain.pick_python"), start, tr("toolchain.python_filter")
        )
        if path:
            self._py_edit.setText(path)

    def _autodetect_t900(self) -> None:
        # Bypass current edit value by clearing it before resolving.
        prev_text = self._t900_edit.text().strip()
        self._t900_edit.clear()
        # Temporarily clear the stored override so heuristics run.
        s = toolchain._settings()
        prev_setting = s.value(toolchain.KEY_T900_PATH, "", str) or ""
        s.remove(toolchain.KEY_T900_PATH)
        try:
            found = toolchain.find_t900_root()
        finally:
            if prev_setting:
                s.setValue(toolchain.KEY_T900_PATH, prev_setting)
        if found is not None:
            self._t900_edit.setText(str(found))
        else:
            self._t900_edit.setText(prev_text)
            self._status.setText(
                self._status.text() + f"<br><span style='color:{_BAD_COLOR};'>"
                + tr("toolchain.autodetect_failed") + "</span>"
            )

    def _autodetect_python(self) -> None:
        prev_text = self._py_edit.text().strip()
        self._py_edit.clear()
        s = toolchain._settings()
        prev_setting = s.value(toolchain.KEY_PYTHON_PATH, "", str) or ""
        s.remove(toolchain.KEY_PYTHON_PATH)
        try:
            found = toolchain.find_python()
        finally:
            if prev_setting:
                s.setValue(toolchain.KEY_PYTHON_PATH, prev_setting)
        if found is not None:
            self._py_edit.setText(str(found))
        else:
            self._py_edit.setText(prev_text)
            self._status.setText(
                self._status.text() + f"<br><span style='color:{_BAD_COLOR};'>"
                + tr("toolchain.autodetect_failed") + "</span>"
            )

    # ------------------------------------------------------------------
    def _refresh_status(self) -> None:
        t900_text = self._t900_edit.text().strip() or None
        py_text = self._py_edit.text().strip() or None
        status = toolchain.toolchain_status(
            explicit_t900=t900_text, explicit_python=py_text
        )

        lines: list[str] = []

        def line(ok: bool, label: str, detail: str = "") -> str:
            mark = "OK" if ok else "X"
            color = _OK_COLOR if ok else _BAD_COLOR
            extra = f" — <span style='color:#8a92a0;'>{detail}</span>" if detail else ""
            return f"<span style='color:{color};'>[{mark}]</span> {label}{extra}"

        t900 = status["t900_root"]
        lines.append(
            line(t900 is not None, "T900", str(t900) if t900 else tr("toolchain.not_found"))
        )

        for name in toolchain.T900_TOOL_NAMES + toolchain.T900_OPTIONAL_TOOL_NAMES:
            p = status["tools"].get(name)
            lines.append(line(p is not None, name, str(p) if p else tr("toolchain.not_found")))

        py = status["python"]
        lines.append(line(py is not None, "python", str(py) if py else tr("toolchain.not_found")))

        mk = status["make"]
        lines.append(line(mk is not None, "make", str(mk) if mk else tr("toolchain.not_found")))

        self._status.setText("<br>".join(lines))

    def _save_and_close(self) -> None:
        toolchain.save_t900_path(self._t900_edit.text().strip() or None)
        toolchain.save_python_path(self._py_edit.text().strip() or None)
        self.accept()
