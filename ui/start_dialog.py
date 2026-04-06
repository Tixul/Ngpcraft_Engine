"""
ui/start_dialog.py - Project start dialog (new / open / recents + language selector).
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from i18n.lang import available_languages, save_to_settings, set_language, tr
from ui.new_project_wizard import NewNgpcProjectWizard

_MAX_RECENTS = 8


def _is_recent_project_valid(path: str) -> bool:
    try:
        project_path = Path(path)
    except (TypeError, ValueError):
        return False
    return (
        project_path.suffix.lower() == ".ngpcraft"
        and project_path.is_file()
        and project_path.parent.is_dir()
    )


def _load_recents() -> list[str]:
    settings = QSettings("NGPCraft", "Engine")
    return settings.value("recents", [], type=list) or []


def _save_recents(paths: list[str]) -> None:
    settings = QSettings("NGPCraft", "Engine")
    settings.setValue("recents", paths[:_MAX_RECENTS])


def _valid_recents() -> list[str]:
    recents = _load_recents()
    valid: list[str] = []
    seen: set[str] = set()
    for raw_path in recents:
        key = str(raw_path).casefold()
        if key in seen:
            continue
        if _is_recent_project_valid(raw_path):
            valid.append(raw_path)
            seen.add(key)
    if valid != recents:
        _save_recents(valid)
    return valid


def add_recent(path: str) -> None:
    """Add a project path to the recents list (call after opening)."""
    recents = _load_recents()
    if path in recents:
        recents.remove(path)
    recents.insert(0, path)
    _save_recents(recents)


class StartDialog(QDialog):
    """
    Project selection dialog shown on application launch.

    Result attributes after accept():
      self.chosen_path  - Path to .ngpcraft file (existing or to be created), None in free mode
      self.is_new       - True if creating a new project
      self.is_free_mode - True if user chose free mode (no project)
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.chosen_path: Path | None = None
        self.is_new: bool = False
        self.is_free_mode: bool = False

        self.setWindowTitle(tr("start.title"))
        self.setMinimumSize(560, 360)
        self.resize(620, 420)
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # Title
        title = QLabel(tr("app.title"))
        font = title.font()
        font.setPointSize(14)
        font.setBold(True)
        title.setFont(font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        # Language selector row
        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel(tr("start.language")))
        self._lang_combo = QComboBox()
        lang_map = {"fr": "Français", "en": "English"}
        for code in available_languages():
            self._lang_combo.addItem(lang_map.get(code, code), code)
        settings = QSettings("NGPCraft", "Engine")
        cur = settings.value("language", "fr", type=str)
        idx = self._lang_combo.findData(cur)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)
        self._lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        lang_row.addWidget(self._lang_combo)
        lang_row.addStretch()
        root.addLayout(lang_row)

        # Radio: free mode / new / open
        self._radio_free = QRadioButton(tr("start.free_mode"))
        self._radio_free.setChecked(True)
        self._free_hint = QLabel(tr("start.free_mode_hint"))
        self._free_hint.setStyleSheet("color: gray; font-style: italic; margin-left: 18px;")
        root.addWidget(self._radio_free)
        root.addWidget(self._free_hint)

        sep = QLabel()
        sep.setFrameStyle(4)  # HLine
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #555;")
        root.addWidget(sep)

        self._radio_new = QRadioButton(tr("start.new_project"))
        self._radio_open = QRadioButton(tr("start.open_project"))
        root.addWidget(self._radio_new)
        self._new_hint = QLabel(tr("start.new_project_hint"))
        self._new_hint.setStyleSheet("color: gray; font-style: italic; margin-left: 18px;")
        root.addWidget(self._new_hint)
        root.addWidget(self._radio_open)

        self._radio_free.toggled.connect(self._update_panels)
        self._radio_new.toggled.connect(self._update_panels)

        # --- Open / recents panel ---
        self._open_panel = QWidget()
        op_layout = QVBoxLayout(self._open_panel)
        op_layout.setContentsMargins(0, 0, 0, 0)

        open_row = QHBoxLayout()
        open_btn = QPushButton(tr("start.open_project"))
        open_btn.clicked.connect(self._browse_ngpng)
        open_row.addWidget(open_btn)
        refresh_btn = QPushButton(tr("start.refresh"))
        refresh_btn.clicked.connect(self._populate_recents)
        open_row.addWidget(refresh_btn)
        open_row.addStretch()
        op_layout.addLayout(open_row)

        op_layout.addWidget(QLabel(tr("start.recents")))
        self._recents_list = QListWidget()
        self._recents_list.setMaximumHeight(120)
        self._recents_list.itemDoubleClicked.connect(self._accept_recent)
        self._populate_recents()
        op_layout.addWidget(self._recents_list)
        root.addWidget(self._open_panel)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("start.btn_open"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("start.btn_cancel"))
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._update_panels()

    # ------------------------------------------------------------------
    def _on_lang_changed(self) -> None:
        lang = self._lang_combo.currentData()
        set_language(lang)
        save_to_settings(lang)

    def _update_panels(self) -> None:
        is_free = self._radio_free.isChecked()
        is_new = self._radio_new.isChecked()
        self._free_hint.setVisible(is_free)
        self._new_hint.setVisible(is_new)
        self._open_panel.setVisible(not is_new and not is_free)

    def _browse_ngpng(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("start.open_project"), "", "NgpCraft Project (*.ngpcraft)"
        )
        if path:
            self.chosen_path = Path(path)
            self.is_new = False
            self.accept()

    def _populate_recents(self) -> None:
        self._recents_list.clear()
        recents = _valid_recents()
        if not recents:
            item = QListWidgetItem(tr("start.no_recents"))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._recents_list.addItem(item)
        else:
            for p in recents:
                self._recents_list.addItem(QListWidgetItem(p))

    def _accept_recent(self, item: QListWidgetItem) -> None:
        self._open_recent_item(item)

    def _open_recent_item(self, item: QListWidgetItem | None) -> None:
        if item is None or not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
            return
        path = Path(item.text())
        if not _is_recent_project_valid(str(path)):
            self._populate_recents()
            QMessageBox.warning(
                self,
                tr("start.missing_title"),
                tr("start.missing_body", path=str(path)),
            )
            return
        self.chosen_path = path
        self.is_new = False
        self.accept()

    def _on_accept(self) -> None:
        if self._radio_free.isChecked():
            self.is_free_mode = True
            self.chosen_path = None
            self.accept()
        elif self._radio_new.isChecked():
            wizard = NewNgpcProjectWizard(self)
            if wizard.exec() == QDialog.DialogCode.Accepted and wizard.chosen_path:
                self.chosen_path = wizard.chosen_path
                self.is_new = True
                add_recent(str(self.chosen_path))
                self.accept()
            # else: wizard cancelled — stay in start dialog
        else:
            self._open_recent_item(self._recents_list.currentItem())
