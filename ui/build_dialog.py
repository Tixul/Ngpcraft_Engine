"""
ui/build_dialog.py - Make build dialog (Phase 5 integration).

Goals:
- Run `make` from the project root.
- Capture stdout/stderr live.
- Optional "Run emulator after build".

Note: this only wires the UI; it does not assume a specific toolchain.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QProcess, Qt, QSettings, QTimer
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.bug_report import build_issue_url, system_info_block
from i18n.lang import tr


@dataclass(frozen=True)
class _BuildPlan:
    """One predefined build scenario shown in the build dialog."""

    label: str
    steps: list[list[str]]  # [ [program, arg1, ...], ... ]


class BuildDialog(QDialog):
    """Run common `make` workflows and stream build logs inside the UI."""

    def __init__(
        self,
        project_dir: Path,
        on_run_requested: Callable[[], None] | None = None,
        parent: QWidget | None = None,
        auto_start: bool = False,
        run_after: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("build.title"))
        self.setModal(True)
        self.setMinimumSize(740, 420)

        self._project_dir = project_dir
        self._on_run_requested = on_run_requested
        self._auto_start = auto_start
        self._force_run_after = run_after

        self._proc = QProcess(self)
        self._proc.setWorkingDirectory(str(project_dir))
        self._proc.readyReadStandardOutput.connect(self._on_out)
        self._proc.readyReadStandardError.connect(self._on_err)
        self._proc.finished.connect(self._on_finished)

        self._queue: list[list[str]] = []
        self._last_exit: int | None = None
        self._current_cmd: list[str] | None = None

        self._build_ui()

        if self._force_run_after:
            self._chk_run.setChecked(True)
        if self._auto_start:
            QTimer.singleShot(100, self._start_selected)

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)

        info = QLabel(tr("build.hint", path=str(self._project_dir)))
        info.setStyleSheet("color: gray;")
        root.addWidget(info)

        settings = QSettings("NGPCraft", "Engine")

        top = QHBoxLayout()
        top.addWidget(QLabel(tr("build.target")))
        self._target = QComboBox()
        self._plans = [
            _BuildPlan(tr("build.plan_build"), [["make"]]),
            _BuildPlan(tr("build.plan_clean"), [["make", "clean"]]),
            _BuildPlan(tr("build.plan_rebuild"), [["make", "clean"], ["make"]]),
            _BuildPlan(tr("build.plan_custom"), [["make"]]),
        ]
        for p in self._plans:
            self._target.addItem(p.label)
        last_idx = settings.value("build/plan_idx", 0, int)
        try:
            last_idx = int(last_idx)
        except Exception:
            last_idx = 0
        self._target.setCurrentIndex(max(0, min(last_idx, len(self._plans) - 1)))
        self._target.currentIndexChanged.connect(
            lambda idx: settings.setValue("build/plan_idx", int(idx))
        )
        self._target.currentIndexChanged.connect(self._update_custom_visible)
        top.addWidget(self._target, 1)

        top.addSpacing(12)
        top.addWidget(QLabel(tr("build.jobs")))
        self._jobs = QSpinBox()
        self._jobs.setRange(1, 64)
        self._jobs.setValue(settings.value("build/jobs", 1, int))
        self._jobs.valueChanged.connect(lambda v: settings.setValue("build/jobs", int(v)))
        top.addWidget(self._jobs)

        self._chk_run = QCheckBox(tr("build.run_after"))
        self._chk_run.setChecked(settings.value("build/run_after", False, bool))
        self._chk_run.toggled.connect(lambda v: settings.setValue("build/run_after", bool(v)))
        top.addWidget(self._chk_run)

        self._btn_start = QPushButton(tr("build.start"))
        self._btn_start.clicked.connect(self._start_selected)
        top.addWidget(self._btn_start)

        self._btn_stop = QPushButton(tr("build.stop"))
        self._btn_stop.clicked.connect(self._stop)
        self._btn_stop.setEnabled(False)
        top.addWidget(self._btn_stop)

        root.addLayout(top)

        custom = QHBoxLayout()
        self._lbl_custom = QLabel(tr("build.custom_target"))
        custom.addWidget(self._lbl_custom)
        self._custom_target = QLineEdit()
        self._custom_target.setPlaceholderText(tr("build.custom_placeholder"))
        self._custom_target.setText(settings.value("build/custom_target", "", str))
        self._custom_target.textChanged.connect(
            lambda t: settings.setValue("build/custom_target", str(t))
        )
        custom.addWidget(self._custom_target, 1)
        root.addLayout(custom)

        extra = QHBoxLayout()
        extra.addWidget(QLabel(tr("build.extra_args")))
        self._extra_args = QLineEdit()
        self._extra_args.setPlaceholderText(tr("build.extra_placeholder"))
        self._extra_args.setText(settings.value("build/extra_args", "", str))
        self._extra_args.textChanged.connect(lambda t: settings.setValue("build/extra_args", str(t)))
        extra.addWidget(self._extra_args, 1)
        self._chk_scroll = QCheckBox(tr("build.auto_scroll"))
        self._chk_scroll.setChecked(settings.value("build/auto_scroll", True, bool))
        self._chk_scroll.toggled.connect(lambda v: settings.setValue("build/auto_scroll", bool(v)))
        extra.addWidget(self._chk_scroll)
        root.addLayout(extra)

        self._out = QTextEdit()
        self._out.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._out.setFont(mono)
        self._out.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        root.addWidget(self._out, 1)

        bot = QHBoxLayout()
        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet("color: gray;")
        bot.addWidget(self._lbl_status, 1)

        self._btn_report = QPushButton(tr("build.report_bug"))
        self._btn_report.setEnabled(False)
        self._btn_report.clicked.connect(self._report_failure)
        bot.addWidget(self._btn_report)

        btn_clear = QPushButton(tr("build.clear"))
        btn_clear.clicked.connect(self._out.clear)
        bot.addWidget(btn_clear)

        btn_copy = QPushButton(tr("build.copy"))
        btn_copy.clicked.connect(self._copy_log)
        bot.addWidget(btn_copy)

        btn_close = QPushButton(tr("build.close"))
        btn_close.clicked.connect(self.close)
        bot.addWidget(btn_close)

        root.addLayout(bot)

        self._update_custom_visible()

    # ------------------------------------------------------------------
    def _update_custom_visible(self) -> None:
        is_custom = int(self._target.currentIndex()) == (len(self._plans) - 1)
        self._lbl_custom.setVisible(is_custom)
        self._custom_target.setVisible(is_custom)

    def _copy_log(self) -> None:
        try:
            QApplication.clipboard().setText(self._out.toPlainText())
        except Exception:
            pass

    def _append(self, text: str) -> None:
        if not text:
            return
        saved = QTextCursor(self._out.textCursor())
        self._out.moveCursor(QTextCursor.MoveOperation.End)
        self._out.insertPlainText(text)
        if self._chk_scroll.isChecked():
            self._out.moveCursor(QTextCursor.MoveOperation.End)
        else:
            self._out.setTextCursor(saved)

    def _on_out(self) -> None:
        self._append(bytes(self._proc.readAllStandardOutput()).decode(errors="replace"))

    def _on_err(self) -> None:
        self._append(bytes(self._proc.readAllStandardError()).decode(errors="replace"))

    def _start_selected(self) -> None:
        if self._proc.state() != QProcess.ProcessState.NotRunning:
            return
        if not self._project_dir.exists():
            QMessageBox.warning(self, tr("build.title"), tr("build.no_dir"))
            return
        if not (self._project_dir / "Makefile").exists():
            # Not fatal; some templates use lowercase or include Makefile elsewhere.
            QMessageBox.information(self, tr("build.title"), tr("build.no_makefile"))

        idx = max(0, int(self._target.currentIndex()))
        plan = self._plans[idx] if idx < len(self._plans) else self._plans[0]

        extra = (self._extra_args.text() or "").strip()
        try:
            extra_args = shlex.split(extra) if extra else []
        except ValueError:
            QMessageBox.warning(self, tr("build.title"), tr("build.bad_args"))
            return

        jobs = int(self._jobs.value())
        job_args = ["-j", str(jobs)] if jobs > 1 else []

        steps: list[list[str]] = []
        if idx == (len(self._plans) - 1):
            target = (self._custom_target.text() or "").strip()
            try:
                target_args = shlex.split(target) if target else []
            except ValueError:
                QMessageBox.warning(self, tr("build.title"), tr("build.bad_target"))
                return
            steps = [["make", *job_args, *target_args, *extra_args]]
        else:
            for step in plan.steps:
                if not step:
                    continue
                if step[0] == "make":
                    steps.append([*step[:1], *job_args, *step[1:], *extra_args])
                else:
                    steps.append([*step, *extra_args])

        self._queue = [s[:] for s in steps]
        self._out.clear()
        self._last_exit = None
        self._current_cmd = None
        self._lbl_status.setText("")
        self._btn_report.setEnabled(False)
        self._run_next()

    def _run_next(self) -> None:
        if not self._queue:
            return
        cmd = self._queue.pop(0)
        if not cmd:
            self._run_next()
            return
        self._current_cmd = cmd
        program, *args = cmd
        self._append(f"\n$ {' '.join(cmd)}\n")
        self._lbl_status.setText(tr("build.running", cmd=" ".join(cmd)))
        self._lbl_status.setStyleSheet("color: gray;")
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._proc.start(program, args)

    def _stop(self) -> None:
        if self._proc.state() == QProcess.ProcessState.NotRunning:
            return
        self._proc.kill()
        self._proc.waitForFinished(3000)

    def _on_finished(self, exit_code: int, exit_status) -> None:  # type: ignore[override]
        self._last_exit = int(exit_code)
        self._btn_stop.setEnabled(False)

        if self._last_exit == 0 and self._queue:
            self._run_next()
            return

        self._btn_start.setEnabled(True)
        if self._last_exit == 0 and exit_status == QProcess.ExitStatus.NormalExit:
            self._lbl_status.setText(tr("build.ok"))
            self._lbl_status.setStyleSheet("color: #4ec94e;")
            if self._chk_run.isChecked() and self._on_run_requested is not None:
                self._on_run_requested()
        else:
            if exit_status == QProcess.ExitStatus.CrashExit:
                self._lbl_status.setText(tr("build.crash"))
            else:
                self._lbl_status.setText(tr("build.fail", code=self._last_exit))
            self._lbl_status.setStyleSheet("color: #e07030;")
            self._btn_report.setEnabled(True)

    def _report_failure(self) -> None:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        code = self._last_exit if self._last_exit is not None else "?"
        title = f"Build failed: make (exit {code})"
        log = self._out.toPlainText()
        body = f"## Build log\n```\n{log}\n```\n\n{system_info_block()}"
        url = build_issue_url(title, body, label="bug")
        QDesktopServices.openUrl(QUrl(url))
