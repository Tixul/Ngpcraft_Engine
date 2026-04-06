"""
ui/tabs/globals_tab.py — Project-wide globals: Variables, Constants, Audio, Entity Types.

Extracted from project_tab.py. Houses everything that is project-level (not per-scene):
  • Game flags and variables  (game_flags / game_vars)
  • Project constants         (constants)
  • Audio manifest + SFX bank + SFX mapping
  • Entity types              (archetypes / presets)

Emits ``manifest_reloaded(object)`` whenever the AudioManifest is reloaded so
ProjectTab can keep its per-scene BGM combo up to date via ``set_audio_manifest()``.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QFileSystemWatcher, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.tabs._project_path_mixin import ProjectPathMixin
from core.audio_autogen_mk import (
    project_uses_template_managed_audio,
    write_audio_autogen_mk,
    write_disabled_audio_autogen_mk,
)
from core.audio_manifest import (
    AudioManifest,
    load_audio_manifest,
    load_sfx_count,
    load_sfx_names,
    resolve_manifest_asset_path,
)
from core.sfx_map_gen import write_sfx_map_h
from core.sfx_play_autogen import write_sfx_play_autogen_c
from core.entity_types import (
    BEHAVIOR_LABELS,
    DIRECTION_LABELS,
    ET_DEFAULTS,
    ROLE_VALUES,
    get_entity_types,
    new_entity_type,
)
from core.entity_templates import (
    get_entity_templates,
    new_entity_template,
    find_template_for_file,
)
from core.game_constants_gen import write_constants_h
from core.game_vars_gen import write_game_vars_h
from core.entity_types_gen import write_entity_types_h as _write_entity_types_h
from i18n.lang import tr


class GlobalsTab(QWidget, ProjectPathMixin):
    """Top-level tab for project-wide globals (Variables, Constants, Audio, Entity Types)."""

    manifest_reloaded = pyqtSignal(object)  # emits AudioManifest | None

    def __init__(
        self,
        project_data: dict,
        project_path: Path | None,
        on_save,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._data = project_data
        self._project_path = project_path
        self._on_save = on_save
        self._audio_manifest: AudioManifest | None = None
        # AUD-8: init watcher before _build_ui so _reload_audio_manifest can arm it
        self._audio_manifest_watcher = QFileSystemWatcher(self)
        self._audio_manifest_watcher.fileChanged.connect(self._on_audio_manifest_file_changed)
        self._build_ui()
        self._load_all_from_project()

    @property
    def audio_manifest(self) -> AudioManifest | None:
        """Current loaded AudioManifest (or None). Used by ProjectTab for initial sync."""
        return self._audio_manifest

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(0)

        self._sub_tabs = QTabWidget()
        self._sub_tabs.setDocumentMode(True)
        root.addWidget(self._sub_tabs)

        self._sub_tabs.addTab(self._build_variables_tab(), tr("proj.gamevars_group"))
        self._sub_tabs.addTab(self._build_constants_tab(), tr("proj.constants_group"))
        self._sub_tabs.addTab(self._build_audio_tab(), tr("proj.audio_group"))
        self._sub_tabs.addTab(self._build_entity_types_tab(), tr("glob.entity_types_tab"))
        self._sub_tabs.addTab(self._build_save_tab(), tr("glob.save_tab"))

    def _build_variables_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        lbl_hint = QLabel(tr("glob.vars_hint"))
        lbl_hint.setStyleSheet("color: #888; font-size: 10px;")
        lbl_hint.setWordWrap(True)
        lay.addWidget(lbl_hint)

        gv_tabs = QTabWidget()
        gv_tabs.setDocumentMode(True)

        # --- Flags sub-tab ---
        self._flag_table = QTableWidget(8, 1)
        self._flag_table.setHorizontalHeaderLabels([tr("proj.gamevars_name_col")])
        self._flag_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._flag_table.horizontalHeader().setToolTip(tr("proj.gamevars_flag_info"))
        self._flag_table.verticalHeader().setDefaultSectionSize(22)
        self._flag_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self._flag_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._flag_table.setMaximumHeight(
            22 * 8 + self._flag_table.horizontalHeader().height() + 4
        )
        for i in range(8):
            item = QTableWidgetItem("")
            item.setData(Qt.ItemDataRole.UserRole, i)
            self._flag_table.setVerticalHeaderItem(i, QTableWidgetItem(str(i)))
            self._flag_table.setItem(i, 0, item)
        self._flag_table.itemChanged.connect(lambda _: self._save_gamevars_to_project())
        gv_tabs.addTab(self._flag_table, tr("proj.gamevars_flags_tab"))

        # --- Variables sub-tab ---
        self._var_table = QTableWidget(8, 2)
        self._var_table.setHorizontalHeaderLabels([
            tr("proj.gamevars_name_col"), tr("proj.gamevars_init_col")
        ])
        self._var_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self._var_table.horizontalHeader().resizeSection(0, 130)
        self._var_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._var_table.horizontalHeader().setToolTip(tr("proj.gamevars_var_info"))
        self._var_table.verticalHeader().setDefaultSectionSize(22)
        self._var_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self._var_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._var_table.setMaximumHeight(
            22 * 8 + self._var_table.horizontalHeader().height() + 4
        )
        self._var_init_spins: list[QSpinBox] = []
        for i in range(8):
            self._var_table.setVerticalHeaderItem(i, QTableWidgetItem(str(i)))
            self._var_table.setItem(i, 0, QTableWidgetItem(""))
            spin = QSpinBox()
            spin.setRange(0, 255)
            spin.setFrame(False)
            spin.valueChanged.connect(self._save_gamevars_to_project)
            self._var_table.setCellWidget(i, 1, spin)
            self._var_init_spins.append(spin)
        self._var_table.itemChanged.connect(lambda _: self._save_gamevars_to_project())
        gv_tabs.addTab(self._var_table, tr("proj.gamevars_vars_tab"))

        lay.addWidget(gv_tabs)
        lay.addStretch()
        return w

    def _build_constants_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        lbl_hint = QLabel(tr("glob.constants_hint"))
        lbl_hint.setStyleSheet("color: #888; font-size: 10px;")
        lbl_hint.setWordWrap(True)
        lay.addWidget(lbl_hint)

        self._constants_table = QTableWidget(0, 3)
        self._constants_table.setHorizontalHeaderLabels([
            tr("proj.constants_name_col"),
            tr("proj.constants_value_col"),
            tr("proj.constants_comment_col"),
        ])
        self._constants_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._constants_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._constants_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self._constants_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._constants_table.setMinimumHeight(80)
        self._constants_table.itemChanged.connect(self._on_constant_changed)
        lay.addWidget(self._constants_table, 1)

        const_btns = QHBoxLayout()
        self._btn_const_add = QPushButton(tr("proj.constants_add"))
        self._btn_const_add.clicked.connect(self._add_constant)
        const_btns.addWidget(self._btn_const_add)
        self._btn_const_del = QPushButton(tr("proj.constants_del"))
        self._btn_const_del.clicked.connect(self._del_constant)
        self._btn_const_del.setEnabled(False)
        const_btns.addWidget(self._btn_const_del)
        const_btns.addStretch()
        lay.addLayout(const_btns)

        self._constants_table.itemSelectionChanged.connect(
            lambda: self._btn_const_del.setEnabled(
                bool(self._constants_table.selectedItems())
            )
        )
        return w

    def _build_audio_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        # Manifest picker row
        man_row = QHBoxLayout()
        man_row.addWidget(QLabel(tr("proj.audio_manifest")), 0)
        self._edit_audio_manifest = QLineEdit()
        self._edit_audio_manifest.setReadOnly(True)
        self._edit_audio_manifest.setPlaceholderText(tr("proj.audio_manifest_ph"))
        man_row.addWidget(self._edit_audio_manifest, 1)
        self._btn_audio_pick = QPushButton(tr("proj.audio_pick"))
        self._btn_audio_pick.clicked.connect(self._pick_audio_manifest)
        man_row.addWidget(self._btn_audio_pick)
        self._btn_audio_reload = QPushButton(tr("proj.audio_reload"))
        self._btn_audio_reload.clicked.connect(self._reload_audio_manifest)
        man_row.addWidget(self._btn_audio_reload)
        self._btn_audio_reveal = QToolButton()
        self._btn_audio_reveal.setText("📂")
        self._btn_audio_reveal.setToolTip(tr("proj.audio_reveal_tt"))
        self._btn_audio_reveal.setEnabled(False)
        self._btn_audio_reveal.clicked.connect(self._reveal_audio_folder)
        man_row.addWidget(self._btn_audio_reveal)
        lay.addLayout(man_row)

        self._lbl_audio_status = QLabel("")
        self._lbl_audio_status.setStyleSheet("color: #aaa; font-size: 10px;")
        self._lbl_audio_status.setWordWrap(True)
        lay.addWidget(self._lbl_audio_status)

        # SFX bank
        self._lbl_sfx_status = QLabel("")
        self._lbl_sfx_status.setStyleSheet("color: #aaa; font-size: 10px;")
        self._lbl_sfx_status.setWordWrap(True)
        lay.addWidget(self._lbl_sfx_status)

        self._lbl_sfx_bank = QLabel(tr("proj.sfx_bank_group"))
        self._lbl_sfx_bank.setStyleSheet(
            "font-weight: bold; font-size: 10px; color: #888; padding: 0;"
        )
        lay.addWidget(self._lbl_sfx_bank)

        self._sfx_list = QListWidget()
        self._sfx_list.setMinimumHeight(70)
        self._sfx_list.setToolTip(tr("proj.sfx_list_tt"))
        lay.addWidget(self._sfx_list, 1)

        # SFX mapping
        sfx_map_g = QGroupBox(tr("proj.sfx_map_group"))
        sfx_map_v = QVBoxLayout(sfx_map_g)
        sfx_map_v.setSpacing(4)

        self._sfx_map_tree = QTreeWidget()
        self._sfx_map_tree.setHeaderLabels([
            tr("proj.sfx_map_col_name"), tr("proj.sfx_map_col_id")
        ])
        self._sfx_map_tree.setRootIsDecorated(False)
        self._sfx_map_tree.setToolTip(tr("proj.sfx_map_tt"))
        self._sfx_map_tree.itemDoubleClicked.connect(self._on_sfx_map_edit)
        self._sfx_map_tree.itemSelectionChanged.connect(self._on_sfx_map_sel_changed)
        sfx_map_v.addWidget(self._sfx_map_tree, 1)

        sfx_btns = QHBoxLayout()
        self._btn_sfx_map_add = QPushButton(tr("proj.sfx_map_add"))
        self._btn_sfx_map_add.clicked.connect(self._sfx_map_add)
        sfx_btns.addWidget(self._btn_sfx_map_add)
        self._btn_sfx_map_del = QPushButton(tr("proj.sfx_map_del"))
        self._btn_sfx_map_del.clicked.connect(self._sfx_map_del)
        self._btn_sfx_map_del.setEnabled(False)
        sfx_btns.addWidget(self._btn_sfx_map_del)
        sfx_btns.addStretch()
        sfx_map_v.addLayout(sfx_btns)

        lay.addWidget(sfx_map_g)
        return w

    # ------------------------------------------------------------------
    # Init load
    # ------------------------------------------------------------------

    def _load_all_from_project(self) -> None:
        self._load_gamevars_from_project()
        self._load_constants_from_project()
        self._load_audio_manifest_from_project()
        self._load_sfx_map_from_project()
        self._load_entity_types_from_project()
        self._load_save_config_from_project()

    # ------------------------------------------------------------------
    # Game flags / variables
    # ------------------------------------------------------------------

    def _load_gamevars_from_project(self) -> None:
        data = self._data if isinstance(self._data, dict) else {}
        flags = data.get("game_flags", [])
        if not isinstance(flags, list):
            flags = []
        vars_ = data.get("game_vars", [])
        if not isinstance(vars_, list):
            vars_ = []
        self._flag_table.blockSignals(True)
        for i in range(8):
            name = str(flags[i]) if i < len(flags) else ""
            item = self._flag_table.item(i, 0)
            if item is None:
                item = QTableWidgetItem("")
                self._flag_table.setItem(i, 0, item)
            item.setText(name)
        self._flag_table.blockSignals(False)
        self._var_table.blockSignals(True)
        for i, spin in enumerate(self._var_init_spins):
            entry = vars_[i] if i < len(vars_) and isinstance(vars_[i], dict) else {}
            name = str(entry.get("name", "") or "")
            init = int(entry.get("init", 0) or 0)
            item = self._var_table.item(i, 0)
            if item is None:
                item = QTableWidgetItem("")
                self._var_table.setItem(i, 0, item)
            item.setText(name)
            spin.blockSignals(True)
            spin.setValue(init)
            spin.blockSignals(False)
        self._var_table.blockSignals(False)

    def _save_gamevars_to_project(self) -> None:
        flags = [
            (self._flag_table.item(i, 0).text().strip() if self._flag_table.item(i, 0) else "")
            for i in range(8)
        ]
        vars_ = [
            {
                "name": (
                    self._var_table.item(i, 0).text().strip()
                    if self._var_table.item(i, 0)
                    else ""
                ),
                "init": self._var_init_spins[i].value(),
            }
            for i in range(8)
        ]
        if isinstance(self._data, dict):
            self._data["game_flags"] = flags
            self._data["game_vars"] = vars_
        self._on_save()

    # ------------------------------------------------------------------
    # Game constants
    # ------------------------------------------------------------------

    def _load_constants_from_project(self) -> None:
        rows = self._data.get("constants", []) if isinstance(self._data, dict) else []
        if not isinstance(rows, list):
            rows = []
        self._populate_constants_table(rows)

    def _populate_constants_table(self, rows: list[dict]) -> None:
        self._constants_table.blockSignals(True)
        self._constants_table.setRowCount(0)
        for r in rows:
            if not isinstance(r, dict):
                continue
            row_idx = self._constants_table.rowCount()
            self._constants_table.insertRow(row_idx)
            self._constants_table.setItem(row_idx, 0, QTableWidgetItem(str(r.get("name") or "")))
            self._constants_table.setItem(row_idx, 1, QTableWidgetItem(str(r.get("value", 0))))
            self._constants_table.setItem(row_idx, 2, QTableWidgetItem(str(r.get("comment") or "")))
        self._constants_table.blockSignals(False)

    def _save_constants_to_project(self) -> None:
        rows: list[dict] = []
        for i in range(self._constants_table.rowCount()):
            name = (self._constants_table.item(i, 0) or QTableWidgetItem("")).text().strip()
            val_txt = (self._constants_table.item(i, 1) or QTableWidgetItem("0")).text().strip()
            comment = (self._constants_table.item(i, 2) or QTableWidgetItem("")).text().strip()
            if not name:
                continue
            try:
                value = int(val_txt) if val_txt.lstrip("-").isdigit() else 0
            except Exception:
                value = 0
            rows.append({"name": name, "value": value, "comment": comment})
        if isinstance(self._data, dict):
            self._data["constants"] = rows
        self._on_save()

    def _add_constant(self) -> None:
        row_idx = self._constants_table.rowCount()
        self._constants_table.blockSignals(True)
        self._constants_table.insertRow(row_idx)
        self._constants_table.setItem(row_idx, 0, QTableWidgetItem("NEW_CONST"))
        self._constants_table.setItem(row_idx, 1, QTableWidgetItem("0"))
        self._constants_table.setItem(row_idx, 2, QTableWidgetItem(""))
        self._constants_table.blockSignals(False)
        self._save_constants_to_project()
        self._constants_table.editItem(self._constants_table.item(row_idx, 0))

    def _del_constant(self) -> None:
        rows_to_remove = sorted(
            {idx.row() for idx in self._constants_table.selectedIndexes()}, reverse=True
        )
        for r in rows_to_remove:
            self._constants_table.removeRow(r)
        self._save_constants_to_project()

    def _on_constant_changed(self, _item: QTableWidgetItem) -> None:
        self._save_constants_to_project()

    # ------------------------------------------------------------------
    # Audio manifest
    # ------------------------------------------------------------------

    def _audio_manifest_path_abs(self) -> Path | None:
        audio = self._data.get("audio", {}) if isinstance(self._data, dict) else {}
        if not isinstance(audio, dict):
            return None
        rel = str(audio.get("manifest") or "").strip()
        if not rel:
            return None
        return self._abs(rel)

    def _load_audio_manifest_from_project(self) -> None:
        p = self._audio_manifest_path_abs()
        if p and p.exists():
            self._edit_audio_manifest.setText(self._rel(p))
            self._reload_audio_manifest()
        else:
            self._edit_audio_manifest.setText("")
            self._audio_manifest = None
            self.manifest_reloaded.emit(self._audio_manifest)
            self._lbl_audio_status.setText(tr("proj.audio_status_none"))
            self._refresh_sfx_bank_ui()

    def _pick_audio_manifest(self) -> None:
        start = str(self._project_dir) if self._project_dir else ""
        p, _ = QFileDialog.getOpenFileName(
            self,
            tr("proj.audio_pick_title"),
            start,
            tr("proj.audio_pick_filter"),
        )
        if not p:
            return
        abs_p = Path(p)
        self._data.setdefault("audio", {})
        try:
            self._data["audio"]["manifest"] = self._rel(abs_p)
        except Exception:
            self._data["audio"]["manifest"] = str(abs_p)
        self._on_save()
        self._load_audio_manifest_from_project()

    def _reload_audio_manifest(self) -> None:
        p = self._audio_manifest_path_abs()
        if not p or not p.exists():
            self._audio_manifest = None
            self.manifest_reloaded.emit(self._audio_manifest)
            self._lbl_audio_status.setText(tr("proj.audio_status_missing"))
            self._refresh_sfx_bank_ui()
            self._btn_audio_reveal.setEnabled(False)
            return
        try:
            self._audio_manifest = load_audio_manifest(p)
            self.manifest_reloaded.emit(self._audio_manifest)
            status = tr("proj.audio_status_ok", n=len(self._audio_manifest.songs))
            if not self._audio_manifest.instruments:
                status += "\n" + tr("proj.audio_status_no_instruments")
                self._lbl_audio_status.setStyleSheet("color: #e8a020; font-size: 10px;")
            else:
                self._lbl_audio_status.setStyleSheet("color: #aaa; font-size: 10px;")
            self._lbl_audio_status.setText(status)
            self._refresh_sfx_bank_ui()
        except Exception as exc:
            self._audio_manifest = None
            self.manifest_reloaded.emit(self._audio_manifest)
            self._lbl_audio_status.setText(tr("proj.audio_status_err", err=str(exc)))
            self._refresh_sfx_bank_ui()
        self._btn_audio_reveal.setEnabled(p.parent.exists())
        self._audio_manifest_watcher_set_path(p)

    def _audio_manifest_watcher_set_path(self, new_path: Path | None) -> None:
        for old in self._audio_manifest_watcher.files():
            self._audio_manifest_watcher.removePath(old)
        if new_path and new_path.exists():
            self._audio_manifest_watcher.addPath(str(new_path))

    def _on_audio_manifest_file_changed(self, _path: str) -> None:
        # Re-arm immediately: some editors write-by-replace (delete + create).
        p = self._audio_manifest_path_abs()
        if p and p.exists():
            self._audio_manifest_watcher.addPath(str(p))
        self._reload_audio_manifest()

    def _reveal_audio_folder(self) -> None:
        p = self._audio_manifest_path_abs()
        folder = p.parent if (p and p.parent.exists()) else None
        if folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _refresh_sfx_bank_ui(self) -> None:
        self._sfx_list.clear()
        manifest = self._audio_manifest
        if manifest is None:
            self._lbl_sfx_status.setText(tr("proj.sfx_status_none"))
            return

        sfx_rel = str(manifest.sfx or "").strip()
        if not sfx_rel:
            self._lbl_sfx_status.setText(tr("proj.sfx_status_missing"))
            return

        man = self._audio_manifest_path_abs()
        if not man:
            self._lbl_sfx_status.setText(tr("proj.sfx_status_missing"))
            return

        sfx_abs = resolve_manifest_asset_path(man.parent, sfx_rel)
        if sfx_abs is None or not sfx_abs.exists():
            missing = resolve_manifest_asset_path(man.parent, Path(sfx_rel).name)
            missing_path = missing if missing is not None else (man.parent / sfx_rel)
            self._lbl_sfx_status.setText(
                tr("proj.sfx_status_not_found", path=self._rel(missing_path))
            )
            return

        count = load_sfx_count(manifest, man.parent)
        sfx_rows = load_sfx_names(manifest, man.parent)
        if count is None and sfx_rows:
            count = max(idx for idx, _name in sfx_rows) + 1

        if count is None:
            self._lbl_sfx_status.setText(
                tr("proj.sfx_status_ok_unknown", path=self._rel(sfx_abs))
            )
        else:
            self._lbl_sfx_status.setText(
                tr("proj.sfx_status_ok", n=count, path=self._rel(sfx_abs))
            )
        sfx_names = {idx: name for idx, name in sfx_rows}
        limit = max(0, int(count if count is not None else len(sfx_rows)))
        for i in range(limit):
            label = f"{i:02d}: {sfx_names[i]}" if i in sfx_names else f"{i:02d}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, int(i))
            self._sfx_list.addItem(item)

    # ------------------------------------------------------------------
    # SFX mapping
    # ------------------------------------------------------------------

    def _load_sfx_map_from_project(self) -> None:
        self._sfx_map_tree.clear()
        audio = self._data.get("audio", {}) if isinstance(self._data, dict) else {}
        if not isinstance(audio, dict):
            return
        rows = audio.get("sfx_map", []) if isinstance(audio.get("sfx_map", []), list) else []
        for r in rows:
            if not isinstance(r, dict):
                continue
            name = str(r.get("name") or "").strip()
            pid = r.get("project_id", r.get("id", 0))
            try:
                pid_i = int(pid)
            except Exception:
                pid_i = 0
            item = QTreeWidgetItem([name, str(max(0, pid_i))])
            self._sfx_map_tree.addTopLevelItem(item)
        self._sfx_map_tree.resizeColumnToContents(0)
        self._on_sfx_map_sel_changed()

    def _save_sfx_map_to_project(self) -> None:
        audio = self._data.get("audio", {}) if isinstance(self._data, dict) else {}
        if not isinstance(audio, dict):
            audio = {}
        rows: list[dict] = []
        for i in range(self._sfx_map_tree.topLevelItemCount()):
            it = self._sfx_map_tree.topLevelItem(i)
            name = str(it.text(0)).strip()
            try:
                pid_i = int(str(it.text(1)).strip())
            except Exception:
                pid_i = 0
            if not name:
                continue
            rows.append({"name": name, "project_id": max(0, pid_i)})
        audio["sfx_map"] = rows
        self._data.setdefault("audio", {})
        self._data["audio"].update(audio)
        self._on_save()

    def _get_sfx_name_list(self) -> list[tuple[int, str]]:
        man = self._audio_manifest_path_abs()
        if man and man.exists() and self._audio_manifest is not None:
            return load_sfx_names(self._audio_manifest, man.parent)
        return []

    def _pick_sfx_id(self, title: str, current: int = 0) -> tuple[int, bool]:
        names = self._get_sfx_name_list()
        if names:
            items = [f"{idx}: {name}" for idx, name in names]
            cur_row = 0
            for i, (idx, _) in enumerate(names):
                if idx == current:
                    cur_row = i
                    break
            dlg = QDialog(self)
            dlg.setWindowTitle(title)
            layout = QVBoxLayout(dlg)
            combo = QComboBox()
            combo.addItems(items)
            combo.setCurrentIndex(cur_row)
            layout.addWidget(combo)
            btns = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
            btns.accepted.connect(dlg.accept)
            btns.rejected.connect(dlg.reject)
            layout.addWidget(btns)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                return names[combo.currentIndex()][0], True
            return 0, False
        else:
            pid, ok = QInputDialog.getInt(
                self, title, tr("proj.sfx_map_id_prompt"), current, 0, 255, 1
            )
            return pid, ok

    def _on_sfx_map_sel_changed(self) -> None:
        sel = self._sfx_map_tree.selectedItems()
        self._btn_sfx_map_del.setEnabled(bool(sel))

    def _sfx_map_add(self) -> None:
        name, ok = QInputDialog.getText(
            self, tr("proj.sfx_map_add_title"), tr("proj.sfx_map_name_prompt")
        )
        if not ok:
            return
        name = str(name or "").strip()
        if not name:
            return
        pid, ok = self._pick_sfx_id(tr("proj.sfx_map_add_title"))
        if not ok:
            return
        self._sfx_map_tree.addTopLevelItem(QTreeWidgetItem([name, str(int(pid))]))
        self._sfx_map_tree.resizeColumnToContents(0)
        self._save_sfx_map_to_project()

    def _sfx_map_del(self) -> None:
        sel = self._sfx_map_tree.selectedItems()
        if not sel:
            return
        it = sel[0]
        idx = self._sfx_map_tree.indexOfTopLevelItem(it)
        if idx >= 0:
            self._sfx_map_tree.takeTopLevelItem(idx)
            self._save_sfx_map_to_project()

    def _on_sfx_map_edit(self, item: QTreeWidgetItem, col: int) -> None:
        if not item:
            return
        if col == 0:
            name, ok = QInputDialog.getText(
                self,
                tr("proj.sfx_map_add_title"),
                tr("proj.sfx_map_name_prompt"),
                text=item.text(0),
            )
            if not ok:
                return
            name = str(name or "").strip()
            if not name:
                return
            item.setText(0, name)
            self._save_sfx_map_to_project()
        elif col == 1:
            try:
                cur = int(item.text(1))
            except Exception:
                cur = 0
            pid, ok = self._pick_sfx_id(tr("proj.sfx_map_add_title"), current=cur)
            if not ok:
                return
            item.setText(1, str(int(pid)))
            self._save_sfx_map_to_project()

    # ------------------------------------------------------------------
    # Entity types tab
    # ------------------------------------------------------------------

    def _build_entity_types_tab(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left : list + buttons ──────────────────────────────────────
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(6, 6, 4, 6)
        ll.setSpacing(4)

        hint = QLabel(tr("glob.et_hint"))
        hint.setStyleSheet("color: #888; font-size: 10px;")
        hint.setWordWrap(True)
        ll.addWidget(hint)

        self._et_list = QListWidget()
        self._et_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._et_list.currentRowChanged.connect(self._on_et_selected)
        ll.addWidget(self._et_list, 1)

        et_btns = QHBoxLayout()
        self._btn_et_add = QPushButton(tr("glob.et_add"))
        self._btn_et_add.clicked.connect(self._et_add)
        et_btns.addWidget(self._btn_et_add)
        self._btn_et_del = QPushButton(tr("glob.et_del"))
        self._btn_et_del.clicked.connect(self._et_del)
        self._btn_et_del.setEnabled(False)
        et_btns.addWidget(self._btn_et_del)
        et_btns.addStretch()
        ll.addLayout(et_btns)

        left.setMinimumWidth(130)
        left.setMaximumWidth(200)
        splitter.addWidget(left)

        # ── Right : form ───────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)

        self._et_form_w = QWidget()
        self._et_form_w.setEnabled(False)
        form = QFormLayout(self._et_form_w)
        form.setContentsMargins(8, 8, 8, 8)
        form.setSpacing(6)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Name
        self._et_name = QLineEdit()
        self._et_name.setMaxLength(32)
        self._et_name.setPlaceholderText("slime_patrol")
        self._et_name.editingFinished.connect(self._on_et_name_changed)
        form.addRow(tr("glob.et_name"), self._et_name)

        # Role
        self._et_role = QComboBox()
        for r in ROLE_VALUES:
            self._et_role.addItem(r, r)
        self._et_role.currentIndexChanged.connect(self._on_et_role_changed)
        form.addRow(tr("glob.et_role"), self._et_role)

        # ── Enemy fields ──
        self._et_behavior_lbl = QLabel(tr("glob.et_behavior"))
        self._et_behavior = QComboBox()
        for val, label in BEHAVIOR_LABELS:
            self._et_behavior.addItem(label, val)
        self._et_behavior.currentIndexChanged.connect(self._on_et_behavior_changed)
        form.addRow(self._et_behavior_lbl, self._et_behavior)

        self._et_speed_lbl = QLabel(tr("glob.et_ai_speed"))
        self._et_speed = QSpinBox()
        self._et_speed.setRange(1, 255)
        self._et_speed.valueChanged.connect(self._save_current_et)
        form.addRow(self._et_speed_lbl, self._et_speed)

        self._et_range_lbl = QLabel(tr("glob.et_ai_range"))
        self._et_range = QSpinBox()
        self._et_range.setRange(0, 255)
        self._et_range.setSuffix(" ×8px")
        self._et_range.valueChanged.connect(self._save_current_et)
        form.addRow(self._et_range_lbl, self._et_range)

        self._et_lose_lbl = QLabel(tr("glob.et_ai_lose_range"))
        self._et_lose = QSpinBox()
        self._et_lose.setRange(0, 255)
        self._et_lose.setSuffix(" ×8px")
        self._et_lose.valueChanged.connect(self._save_current_et)
        form.addRow(self._et_lose_lbl, self._et_lose)

        self._et_change_lbl = QLabel(tr("glob.et_ai_change_every"))
        self._et_change = QSpinBox()
        self._et_change.setRange(1, 255)
        self._et_change.setSuffix(" fr")
        self._et_change.valueChanged.connect(self._save_current_et)
        form.addRow(self._et_change_lbl, self._et_change)

        # ── Common fields ──
        self._et_dir = QComboBox()
        for val, label in DIRECTION_LABELS:
            self._et_dir.addItem(label, val)
        self._et_dir.currentIndexChanged.connect(self._save_current_et)
        form.addRow(tr("glob.et_direction"), self._et_dir)

        self._et_data = QSpinBox()
        self._et_data.setRange(0, 255)
        self._et_data.valueChanged.connect(self._save_current_et)
        form.addRow(tr("glob.et_data"), self._et_data)

        self._et_clamp = QCheckBox(tr("glob.et_clamp_map"))
        self._et_clamp.toggled.connect(self._save_current_et)
        form.addRow("", self._et_clamp)

        # ── Sprite snapshot info (read-only, only shown for full templates) ──
        from PyQt6.QtWidgets import QFrame
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #444;")
        form.addRow(sep)

        self._et_sprite_lbl = QLabel(tr("glob.et_sprite_file"))
        self._et_sprite_val = QLabel("—")
        self._et_sprite_val.setStyleSheet("color: #aaa; font-size: 11px;")
        self._et_sprite_val.setWordWrap(True)
        form.addRow(self._et_sprite_lbl, self._et_sprite_val)

        self._et_frames_lbl = QLabel(tr("glob.et_frames"))
        self._et_frames_val = QLabel("—")
        self._et_frames_val.setStyleSheet("color: #aaa; font-size: 11px;")
        form.addRow(self._et_frames_lbl, self._et_frames_val)

        self._et_hitbox_lbl = QLabel(tr("glob.et_hitbox_info"))
        self._et_hitbox_val = QLabel("—")
        self._et_hitbox_val.setStyleSheet("color: #aaa; font-size: 11px;")
        self._et_hitbox_val.setWordWrap(True)
        form.addRow(self._et_hitbox_lbl, self._et_hitbox_val)

        self._et_props_lbl = QLabel(tr("glob.et_props_info"))
        self._et_props_val = QLabel("—")
        self._et_props_val.setStyleSheet("color: #aaa; font-size: 11px;")
        self._et_props_val.setWordWrap(True)
        form.addRow(self._et_props_lbl, self._et_props_val)

        # Initially hide sprite info section
        for w in (sep, self._et_sprite_lbl, self._et_sprite_val,
                  self._et_frames_lbl, self._et_frames_val,
                  self._et_hitbox_lbl, self._et_hitbox_val,
                  self._et_props_lbl, self._et_props_val):
            w.setVisible(False)
        self._et_sprite_sep = sep

        scroll.setWidget(self._et_form_w)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        outer = QWidget()
        _lay = QVBoxLayout(outer)
        _lay.setContentsMargins(0, 0, 0, 0)
        _lay.addWidget(splitter)
        return outer

    # -- helpers -----------------------------------------------------------

    def _et_row_setvisible(self, label: QWidget, field: QWidget, visible: bool) -> None:
        label.setVisible(visible)
        field.setVisible(visible)

    def _et_update_form_visibility(self) -> None:
        role = self._et_role.currentData() or "enemy"
        behavior = self._et_behavior.currentData() or 0
        is_enemy = role == "enemy"
        is_chase = is_enemy and behavior == 1
        is_random = is_enemy and behavior == 3
        is_moving = is_enemy and behavior != 2  # not Fixed

        self._et_row_setvisible(self._et_behavior_lbl, self._et_behavior, is_enemy)
        self._et_row_setvisible(self._et_speed_lbl, self._et_speed, is_moving)
        self._et_row_setvisible(self._et_range_lbl, self._et_range, is_chase)
        self._et_row_setvisible(self._et_lose_lbl, self._et_lose, is_chase)
        self._et_row_setvisible(self._et_change_lbl, self._et_change, is_random)

    # -- load / save -------------------------------------------------------

    def _et_all_entries(self) -> list[dict]:
        """Return merged list: entity_templates[] first, then legacy entity_types[]."""
        tpls = [t for t in get_entity_templates(self._data) if isinstance(t, dict)]
        types = [t for t in get_entity_types(self._data) if isinstance(t, dict)]
        return tpls + types

    def _et_is_template(self, entry: dict) -> bool:
        """True if this entry comes from entity_templates[] (has sprite data)."""
        return bool(entry.get("file") or entry.get("hurtboxes") is not None)

    def _load_entity_types_from_project(self) -> None:
        self._et_list.blockSignals(True)
        self._et_list.clear()
        for t in self._et_all_entries():
            name = str(t.get("name") or t.get("id") or "?")
            role = str(t.get("role") or "enemy")
            prefix = "📌 " if self._et_is_template(t) else ""
            item = QListWidgetItem(f"{prefix}{name}  [{role}]")
            item.setData(Qt.ItemDataRole.UserRole, str(t.get("id") or name))
            self._et_list.addItem(item)
        self._et_list.blockSignals(False)
        self._et_form_w.setEnabled(False)
        self._btn_et_del.setEnabled(False)

    def _on_et_selected(self, row: int) -> None:
        types = self._et_all_entries()
        if row < 0 or row >= len(types):
            self._et_form_w.setEnabled(False)
            self._btn_et_del.setEnabled(False)
            return
        t = types[row]
        self._et_form_w.setEnabled(True)
        self._btn_et_del.setEnabled(True)

        # Block all signals while populating
        for w in (self._et_name, self._et_role, self._et_behavior,
                  self._et_speed, self._et_range, self._et_lose,
                  self._et_change, self._et_dir, self._et_data, self._et_clamp):
            w.blockSignals(True)

        self._et_name.setText(str(t.get("name") or ""))

        role = str(t.get("role") or "enemy")
        idx = next((i for i, r in enumerate(ROLE_VALUES) if r == role), 0)
        self._et_role.setCurrentIndex(idx)

        behavior = int(t.get("behavior") or 0)
        beh_idx = next((i for i, (v, _) in enumerate(BEHAVIOR_LABELS) if v == behavior), 0)
        self._et_behavior.setCurrentIndex(beh_idx)

        self._et_speed.setValue(int(t.get("ai_speed") or ET_DEFAULTS["ai_speed"]))
        self._et_range.setValue(int(t.get("ai_range") or ET_DEFAULTS["ai_range"]))
        self._et_lose.setValue(int(t.get("ai_lose_range") or ET_DEFAULTS["ai_lose_range"]))
        self._et_change.setValue(int(t.get("ai_change_every") or ET_DEFAULTS["ai_change_every"]))

        direction = int(t.get("direction") or 0)
        dir_idx = next((i for i, (v, _) in enumerate(DIRECTION_LABELS) if v == direction), 0)
        self._et_dir.setCurrentIndex(dir_idx)

        self._et_data.setValue(int(t.get("data") or 0))
        flags = int(t.get("flags") or 0)
        self._et_clamp.setChecked(bool(flags & 1))

        for w in (self._et_name, self._et_role, self._et_behavior,
                  self._et_speed, self._et_range, self._et_lose,
                  self._et_change, self._et_dir, self._et_data, self._et_clamp):
            w.blockSignals(False)

        self._et_update_form_visibility()
        self._et_update_sprite_info(t)

    def _et_update_sprite_info(self, t: dict) -> None:
        """Populate (or hide) the sprite snapshot section in the form."""
        is_tpl = self._et_is_template(t)
        for w in (self._et_sprite_sep, self._et_sprite_lbl, self._et_sprite_val,
                  self._et_frames_lbl, self._et_frames_val,
                  self._et_hitbox_lbl, self._et_hitbox_val,
                  self._et_props_lbl, self._et_props_val):
            w.setVisible(is_tpl)
        if not is_tpl:
            return
        from pathlib import Path as _Path
        file_rel = t.get("file") or ""
        self._et_sprite_val.setText(_Path(file_rel).name if file_rel else "—")
        fw = t.get("frame_w", "?")
        fh = t.get("frame_h", "?")
        self._et_frames_val.setText(f"{fw}×{fh} px")
        hurt_count = len(t.get("hurtboxes") or [])
        atk_count = len(t.get("hitboxes_attack_multi") or [])
        self._et_hitbox_val.setText(
            f"{hurt_count} hurtbox{'es' if hurt_count != 1 else ''}  •  "
            f"{atk_count} attack box{'es' if atk_count != 1 else ''}"
        )
        props = t.get("props") or {}
        if props:
            self._et_props_val.setText("  ".join(f"{k}={v}" for k, v in props.items()))
        else:
            self._et_props_val.setText("—")

    def _save_current_et(self) -> None:
        row = self._et_list.currentRow()
        types = self._et_all_entries()
        if row < 0 or row >= len(types):
            return
        t = types[row]

        name = self._et_name.text().strip().replace(" ", "_") or "type"
        t["name"] = name
        t["role"] = self._et_role.currentData() or "enemy"
        t["behavior"] = self._et_behavior.currentData() or 0
        t["ai_speed"] = self._et_speed.value()
        t["ai_range"] = self._et_range.value()
        t["ai_lose_range"] = self._et_lose.value()
        t["ai_change_every"] = self._et_change.value()
        t["direction"] = self._et_dir.currentData() or 0
        t["data"] = self._et_data.value()
        t["flags"] = 1 if self._et_clamp.isChecked() else 0

        # Refresh list label (preserve 📌 prefix for templates)
        role = t["role"]
        item = self._et_list.item(row)
        if item:
            prefix = "📌 " if self._et_is_template(t) else ""
            item.setText(f"{prefix}{name}  [{role}]")
            item.setData(Qt.ItemDataRole.UserRole, str(t.get("id") or name))

        self._on_save()

    def _on_et_name_changed(self) -> None:
        self._save_current_et()

    def _on_et_role_changed(self) -> None:
        self._et_update_form_visibility()
        self._save_current_et()

    def _on_et_behavior_changed(self) -> None:
        self._et_update_form_visibility()
        self._save_current_et()

    # -- add / delete ------------------------------------------------------

    def _et_add(self) -> None:
        name, ok = QInputDialog.getText(
            self, tr("glob.et_add_title"), tr("glob.et_name_prompt")
        )
        if not ok:
            return
        name = str(name or "").strip().replace(" ", "_")
        if not name:
            return
        # New entries go into entity_templates[] (full prefab format)
        t = new_entity_template(name)
        self._data.setdefault("entity_templates", [])
        self._data["entity_templates"].append(t)
        self._on_save()
        total = self._et_list.count()
        item = QListWidgetItem(f"{t['name']}  [{t['role']}]")
        item.setData(Qt.ItemDataRole.UserRole, str(t["id"]))
        self._et_list.addItem(item)
        self._et_list.setCurrentRow(total)

    def _et_del(self) -> None:
        row = self._et_list.currentRow()
        all_entries = self._et_all_entries()
        if row < 0 or row >= len(all_entries):
            return
        t = all_entries[row]
        # Remove from whichever list owns this entry
        tpl_id = t.get("id", "")
        tpls = get_entity_templates(self._data)
        for i, e in enumerate(tpls):
            if e.get("id") == tpl_id:
                tpls.pop(i)
                self._data["entity_templates"] = tpls
                break
        else:
            types = get_entity_types(self._data)
            for i, e in enumerate(types):
                if e.get("id") == tpl_id:
                    types.pop(i)
                    self._data["entity_types"] = types
                    break
        self._on_save()
        self._et_list.takeItem(row)
        new_row = min(row, self._et_list.count() - 1)
        if new_row >= 0:
            self._et_list.setCurrentRow(new_row)
        else:
            self._et_form_w.setEnabled(False)
            self._btn_et_del.setEnabled(False)

    # ------------------------------------------------------------------
    # Public export API (called by ProjectTab via delegation)
    # ------------------------------------------------------------------

    def write_audio_autogen_mk(self, export_dir: Path | None, errs: list[str]) -> Path | None:
        if not self._project_dir:
            return None
        man = self._audio_manifest_path_abs()
        if not man or not man.exists():
            return None
        try:
            out_dir = export_dir if export_dir else man.parent
            if export_dir and project_uses_template_managed_audio(self._project_dir):
                return write_disabled_audio_autogen_mk(
                    out_dir,
                    reason="template-managed hybrid audio is aggregated by sound/sound_data.c",
                )
            return write_audio_autogen_mk(
                self._project_dir,
                man.parent,
                out_dir=out_dir,
                manifest=self._audio_manifest,
            )
        except Exception as e:
            errs.append(f"audio_autogen.mk: {e}")
            return None

    def write_sfx_autogen(
        self, export_dir: Path | None, errs: list[str]
    ) -> tuple[Path | None, Path | None]:
        if not export_dir:
            return (None, None)
        if not self._project_dir:
            return (None, None)
        audio = self._data.get("audio", {}) if isinstance(self._data, dict) else {}
        if not isinstance(audio, dict):
            return (None, None)
        rows = audio.get("sfx_map", None)
        if not isinstance(rows, list) or not rows:
            return (None, None)
        man = self._audio_manifest_path_abs()
        if not man or not man.exists():
            return (None, None)
        exports_dir = man.parent
        if self._audio_manifest is not None and str(self._audio_manifest.mode or "").upper() == "ASM":
            return (None, None)
        try:
            sfx_map_h = write_sfx_map_h(
                project_data=self._data, export_dir=export_dir, extra_dirs=[exports_dir]
            )
        except Exception as e:
            errs.append(f"sfx map: {e}")
            sfx_map_h = None
        try:
            sfx_play_c = write_sfx_play_autogen_c(exports_dir=exports_dir)
        except Exception as e:
            errs.append(f"sfx play: {e}")
            sfx_play_c = None
        return (sfx_map_h, sfx_play_c)

    def write_constants_h(self, export_dir: Path | None, errs: list[str]) -> Path | None:
        if not export_dir:
            return None
        try:
            rows = self._data.get("constants", []) if isinstance(self._data, dict) else []
            if not isinstance(rows, list) or not rows:
                return None
            return write_constants_h(project_data=self._data, export_dir=export_dir)
        except Exception as e:
            errs.append(f"project_constants.h: {e}")
            return None

    def write_game_vars_h(self, export_dir: Path | None, errs: list[str]) -> Path | None:
        if not export_dir:
            return None
        try:
            return write_game_vars_h(
                project_data=self._data if isinstance(self._data, dict) else {},
                export_dir=export_dir,
            )
        except Exception as e:
            errs.append(f"ngpc_game_vars.h: {e}")
            return None

    def write_entity_types_h(self, export_dir: Path | None, errs: list[str]) -> Path | None:
        if not export_dir:
            return None
        try:
            types = self._data.get("entity_types", []) if isinstance(self._data, dict) else []
            if not isinstance(types, list) or not types:
                return None
            return _write_entity_types_h(
                project_data=self._data if isinstance(self._data, dict) else {},
                export_dir=export_dir,
            )
        except Exception as e:
            errs.append(f"ngpc_entity_types.h: {e}")
            return None

    # ------------------------------------------------------------------
    # Save config tab
    # ------------------------------------------------------------------

    _SAVE_FIELD_TYPES = ("u8", "u16", "s8")
    _SAVE_CORE_BYTES  = 8  # magic[4] + version + resume_scene + checkpoint_scene + checkpoint_region

    def _build_save_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        hint = QLabel(tr("glob.save_hint"))
        hint.setStyleSheet("color: #888; font-size: 10px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        # Group 1 — Player state
        grp_player = QGroupBox(tr("glob.save_group_player"))
        grp_player_lay = QVBoxLayout(grp_player)
        grp_player_lay.setSpacing(2)
        self._save_cb_score     = QCheckBox(tr("glob.save_score"))
        self._save_cb_lives     = QCheckBox(tr("glob.save_lives"))
        self._save_cb_hp        = QCheckBox(tr("glob.save_hp"))
        self._save_cb_continues = QCheckBox(tr("glob.save_continues"))
        self._save_cb_form      = QCheckBox(tr("glob.save_player_form"))
        for cb in (self._save_cb_score, self._save_cb_lives,
                   self._save_cb_hp, self._save_cb_continues, self._save_cb_form):
            grp_player_lay.addWidget(cb)
            cb.toggled.connect(self._on_save_config_changed)
        lay.addWidget(grp_player)

        # Group 2 — Progression
        grp_progress = QGroupBox(tr("glob.save_group_progress"))
        grp_progress_lay = QVBoxLayout(grp_progress)
        grp_progress_lay.setSpacing(2)
        self._save_cb_keys      = QCheckBox(tr("glob.save_keys"))
        self._save_cb_bosses    = QCheckBox(tr("glob.save_bosses"))
        self._save_cb_stages    = QCheckBox(tr("glob.save_stages"))
        self._save_cb_abilities = QCheckBox(tr("glob.save_abilities"))
        self._save_cb_level     = QCheckBox(tr("glob.save_player_level"))
        self._save_cb_xp        = QCheckBox(tr("glob.save_experience"))
        for cb in (self._save_cb_keys, self._save_cb_bosses, self._save_cb_stages,
                   self._save_cb_abilities, self._save_cb_level, self._save_cb_xp):
            grp_progress_lay.addWidget(cb)
            cb.toggled.connect(self._on_save_config_changed)
        lay.addWidget(grp_progress)

        # Group 3 — Resources & records
        grp_res = QGroupBox(tr("glob.save_group_resources"))
        grp_res_lay = QVBoxLayout(grp_res)
        grp_res_lay.setSpacing(2)
        self._save_cb_collect   = QCheckBox(tr("glob.save_collectibles"))
        self._save_cb_money     = QCheckBox(tr("glob.save_money"))
        self._save_cb_ammo      = QCheckBox(tr("glob.save_ammo"))
        self._save_cb_best_time = QCheckBox(tr("glob.save_best_time"))
        for cb in (self._save_cb_collect, self._save_cb_money,
                   self._save_cb_ammo, self._save_cb_best_time):
            grp_res_lay.addWidget(cb)
            cb.toggled.connect(self._on_save_config_changed)
        lay.addWidget(grp_res)

        # Custom fields
        grp_custom = QGroupBox(tr("glob.save_custom_group"))
        grp_c_lay = QVBoxLayout(grp_custom)

        custom_hint = QLabel(tr("glob.save_custom_hint"))
        custom_hint.setStyleSheet("color: #888; font-size: 10px;")
        custom_hint.setWordWrap(True)
        grp_c_lay.addWidget(custom_hint)

        self._save_custom_table = QTableWidget(0, 2)
        self._save_custom_table.setHorizontalHeaderLabels([
            tr("glob.save_custom_name_col"),
            tr("glob.save_custom_type_col"),
        ])
        self._save_custom_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._save_custom_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._save_custom_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._save_custom_table.setMinimumHeight(80)
        self._save_custom_table.itemChanged.connect(self._on_save_custom_changed)
        grp_c_lay.addWidget(self._save_custom_table, 1)

        btn_row = QHBoxLayout()
        self._btn_save_add = QPushButton(tr("glob.save_custom_add"))
        self._btn_save_add.clicked.connect(self._add_save_custom_field)
        btn_row.addWidget(self._btn_save_add)
        self._btn_save_del = QPushButton(tr("glob.save_custom_del"))
        self._btn_save_del.clicked.connect(self._del_save_custom_field)
        self._btn_save_del.setEnabled(False)
        btn_row.addWidget(self._btn_save_del)
        btn_row.addStretch()
        grp_c_lay.addLayout(btn_row)

        self._save_custom_table.itemSelectionChanged.connect(
            lambda: self._btn_save_del.setEnabled(
                bool(self._save_custom_table.selectedItems())
            )
        )
        lay.addWidget(grp_custom, 1)

        # Budget label
        self._save_budget_label = QLabel()
        self._save_budget_label.setStyleSheet("color: #aaa; font-size: 10px;")
        lay.addWidget(self._save_budget_label)

        self._update_save_budget()
        return w

    def _save_config_dict(self) -> dict:
        """Return (and initialise if absent) project_data['save_config']."""
        if not isinstance(self._data, dict):
            return {}
        cfg = self._data.setdefault("save_config", {})
        if not isinstance(cfg, dict):
            cfg = {}
            self._data["save_config"] = cfg
        cfg.setdefault("save_score",        False)
        cfg.setdefault("save_lives",         False)
        cfg.setdefault("save_collectibles",  False)
        cfg.setdefault("save_player_form",   False)
        cfg.setdefault("save_hp",            False)
        cfg.setdefault("save_continues",     False)
        cfg.setdefault("save_keys",          False)
        cfg.setdefault("save_bosses",        False)
        cfg.setdefault("save_stages",        False)
        cfg.setdefault("save_abilities",     False)
        cfg.setdefault("save_money",         False)
        cfg.setdefault("save_ammo",          False)
        cfg.setdefault("save_player_level",  False)
        cfg.setdefault("save_experience",    False)
        cfg.setdefault("save_best_time",     False)
        cfg.setdefault("custom_fields",      [])
        return cfg

    def _update_save_budget(self) -> None:
        cfg   = self._save_config_dict()
        used  = self._SAVE_CORE_BYTES
        if cfg.get("save_score"):        used += 2
        if cfg.get("save_lives"):        used += 1
        if cfg.get("save_collectibles"): used += 1
        if cfg.get("save_player_form"):  used += 1
        if cfg.get("save_hp"):           used += 1
        if cfg.get("save_continues"):    used += 1
        if cfg.get("save_keys"):         used += 1
        if cfg.get("save_bosses"):       used += 1
        if cfg.get("save_stages"):       used += 1
        if cfg.get("save_abilities"):    used += 1
        if cfg.get("save_money"):        used += 2
        if cfg.get("save_ammo"):         used += 1
        if cfg.get("save_player_level"): used += 1
        if cfg.get("save_experience"):   used += 2
        if cfg.get("save_best_time"):    used += 2
        for f in (cfg.get("custom_fields") or []):
            if isinstance(f, dict):
                used += 2 if f.get("type") == "u16" else 1
        total = 256  # SAVE_SIZE from ngpc_flash.h
        free  = total - used
        self._save_budget_label.setText(
            tr("glob.save_budget").format(used=used, total=total, free=free)
        )

    def _load_save_config_from_project(self) -> None:
        cfg = self._save_config_dict()
        for cb, key in (
            (self._save_cb_score,     "save_score"),
            (self._save_cb_lives,     "save_lives"),
            (self._save_cb_collect,   "save_collectibles"),
            (self._save_cb_form,      "save_player_form"),
            (self._save_cb_hp,        "save_hp"),
            (self._save_cb_continues, "save_continues"),
            (self._save_cb_keys,      "save_keys"),
            (self._save_cb_bosses,    "save_bosses"),
            (self._save_cb_stages,    "save_stages"),
            (self._save_cb_abilities, "save_abilities"),
            (self._save_cb_money,     "save_money"),
            (self._save_cb_ammo,      "save_ammo"),
            (self._save_cb_level,     "save_player_level"),
            (self._save_cb_xp,        "save_experience"),
            (self._save_cb_best_time, "save_best_time"),
        ):
            cb.blockSignals(True)
            cb.setChecked(bool(cfg.get(key, False)))
            cb.blockSignals(False)

        self._save_custom_table.blockSignals(True)
        self._save_custom_table.setRowCount(0)
        for f in (cfg.get("custom_fields") or []):
            if not isinstance(f, dict):
                continue
            row = self._save_custom_table.rowCount()
            self._save_custom_table.insertRow(row)
            self._save_custom_table.setItem(row, 0, QTableWidgetItem(str(f.get("name", ""))))
            combo = QComboBox()
            combo.addItems(self._SAVE_FIELD_TYPES)
            ftype = str(f.get("type", "u8"))
            idx   = combo.findText(ftype)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.currentTextChanged.connect(self._on_save_custom_changed)
            self._save_custom_table.setCellWidget(row, 1, combo)
        self._save_custom_table.blockSignals(False)
        self._update_save_budget()

    def _write_save_config_to_project(self) -> None:
        cfg = self._save_config_dict()
        cfg["save_score"]        = self._save_cb_score.isChecked()
        cfg["save_lives"]        = self._save_cb_lives.isChecked()
        cfg["save_collectibles"] = self._save_cb_collect.isChecked()
        cfg["save_player_form"]  = self._save_cb_form.isChecked()
        cfg["save_hp"]           = self._save_cb_hp.isChecked()
        cfg["save_continues"]    = self._save_cb_continues.isChecked()
        cfg["save_keys"]         = self._save_cb_keys.isChecked()
        cfg["save_bosses"]       = self._save_cb_bosses.isChecked()
        cfg["save_stages"]       = self._save_cb_stages.isChecked()
        cfg["save_abilities"]    = self._save_cb_abilities.isChecked()
        cfg["save_money"]        = self._save_cb_money.isChecked()
        cfg["save_ammo"]         = self._save_cb_ammo.isChecked()
        cfg["save_player_level"] = self._save_cb_level.isChecked()
        cfg["save_experience"]   = self._save_cb_xp.isChecked()
        cfg["save_best_time"]    = self._save_cb_best_time.isChecked()
        fields = []
        for row in range(self._save_custom_table.rowCount()):
            name_item = self._save_custom_table.item(row, 0)
            name = name_item.text().strip() if name_item else ""
            combo = self._save_custom_table.cellWidget(row, 1)
            ftype = combo.currentText() if combo else "u8"
            if name:
                fields.append({"name": name, "type": ftype})
        cfg["custom_fields"] = fields
        self._update_save_budget()
        self._on_save()

    def _on_save_config_changed(self) -> None:
        self._write_save_config_to_project()

    def _on_save_custom_changed(self) -> None:
        self._write_save_config_to_project()

    def _add_save_custom_field(self) -> None:
        name, ok = QInputDialog.getText(
            self, tr("glob.save_custom_add"), tr("glob.save_custom_name_col") + ":"
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        row = self._save_custom_table.rowCount()
        self._save_custom_table.insertRow(row)
        self._save_custom_table.setItem(row, 0, QTableWidgetItem(name))
        combo = QComboBox()
        combo.addItems(self._SAVE_FIELD_TYPES)
        combo.currentTextChanged.connect(self._on_save_custom_changed)
        self._save_custom_table.setCellWidget(row, 1, combo)
        self._write_save_config_to_project()

    def _del_save_custom_field(self) -> None:
        rows = sorted(
            {idx.row() for idx in self._save_custom_table.selectedIndexes()},
            reverse=True,
        )
        for r in rows:
            self._save_custom_table.removeRow(r)
        self._write_save_config_to_project()
