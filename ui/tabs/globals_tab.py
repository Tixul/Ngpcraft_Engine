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
    QCompleter,
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
    QMenu,
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
from ui.no_scroll import NoScrollSpinBox as QSpinBox, NoScrollComboBox as QComboBox  # noqa: F811

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
    EVENTS_BY_ROLE,
    EVENT_IDS,
    ROLE_VALUES,
    get_entity_types,
    get_type_events,
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


def _make_searchable_combo(combo: "QComboBox") -> None:
    """Make a QComboBox searchable by typing — filters items that *contain* the query."""
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    c = combo.completer()
    if c:
        c.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        c.setFilterMode(Qt.MatchFlag.MatchContains)


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
        self._sub_tabs.addTab(self._build_items_tab(), "Items")
        self._sub_tabs.addTab(self._build_custom_events_tab(), "Événements")
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
        self._flag_table = QTableWidget(16, 1)
        self._flag_table.setHorizontalHeaderLabels([tr("proj.gamevars_name_col")])
        self._flag_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._flag_table.horizontalHeader().setToolTip(tr("proj.gamevars_flag_info"))
        self._flag_table.verticalHeader().setDefaultSectionSize(22)
        self._flag_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self._flag_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        for i in range(16):
            item = QTableWidgetItem("")
            item.setData(Qt.ItemDataRole.UserRole, i)
            self._flag_table.setVerticalHeaderItem(i, QTableWidgetItem(str(i)))
            self._flag_table.setItem(i, 0, item)
        self._flag_table.itemChanged.connect(lambda _: self._save_gamevars_to_project())
        gv_tabs.addTab(self._flag_table, tr("proj.gamevars_flags_tab"))

        # --- Variables sub-tab ---
        self._var_table = QTableWidget(16, 2)
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
        self._var_init_spins: list[QSpinBox] = []
        for i in range(16):
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
        self._load_items_from_project()
        self._load_save_config_from_project()
        self.load_custom_events()

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
        for i in range(16):
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
            for i in range(16)
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
            for i in range(16)
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

        # ── Combat stats (enemy only) ──
        self._et_hp_lbl = QLabel("HP max :")
        self._et_hp = QSpinBox()
        self._et_hp.setRange(1, 255)
        self._et_hp.setValue(10)
        self._et_hp.setToolTip("Points de vie maximum de ce type d'entité.")
        self._et_hp.valueChanged.connect(self._save_current_et)
        form.addRow(self._et_hp_lbl, self._et_hp)

        self._et_atk_lbl = QLabel("ATK :")
        self._et_atk = QSpinBox()
        self._et_atk.setRange(0, 255)
        self._et_atk.setValue(1)
        self._et_atk.setToolTip("Valeur d'attaque de base.")
        self._et_atk.valueChanged.connect(self._save_current_et)
        form.addRow(self._et_atk_lbl, self._et_atk)

        self._et_def_lbl = QLabel("DEF :")
        self._et_def = QSpinBox()
        self._et_def.setRange(0, 255)
        self._et_def.setValue(0)
        self._et_def.setToolTip("Valeur de défense (réduit les dégâts reçus).")
        self._et_def.valueChanged.connect(self._save_current_et)
        form.addRow(self._et_def_lbl, self._et_def)

        self._et_xp_lbl = QLabel("XP (récompense) :")
        self._et_xp = QSpinBox()
        self._et_xp.setRange(0, 255)
        self._et_xp.setValue(0)
        self._et_xp.setToolTip("Points d'expérience accordés au joueur quand ce type est tué.")
        self._et_xp.valueChanged.connect(self._save_current_et)
        form.addRow(self._et_xp_lbl, self._et_xp)

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

        # ── Events section ────────────────────────────────────────────────
        from PyQt6.QtWidgets import QFrame as _QFrame
        ev_sep = _QFrame()
        ev_sep.setFrameShape(_QFrame.Shape.HLine)
        ev_sep.setStyleSheet("color: #444;")
        form.addRow(ev_sep)

        ev_grp = QGroupBox("Events — actions déclenchées par ce type d'entité")
        ev_grp.setToolTip(
            "Ces actions s'exécutent pour N'IMPORTE QUELLE instance de ce type,\n"
            "dans toutes les scènes (statiques ET procgen).\n\n"
            "Exemples :\n"
            "  entity_death + inc_variable → compteur de kills global\n"
            "  entity_death + goto_scene  → fin de partie quand le boss meurt\n"
            "  entity_collect + set_flag  → flag clé ramassée")
        ev_v = QVBoxLayout(ev_grp)
        ev_v.setSpacing(4)
        ev_v.setContentsMargins(6, 6, 6, 6)

        ev_hint = QLabel(
            "Chaque ligne = une action. Double-clic pour éditer.")
        ev_hint.setStyleSheet("color:#888;font-size:10px;")
        ev_v.addWidget(ev_hint)

        self._et_event_list = QListWidget()
        self._et_event_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._et_event_list.setFixedHeight(90)
        self._et_event_list.itemDoubleClicked.connect(self._et_event_edit_selected)
        ev_v.addWidget(self._et_event_list)

        ev_btn_row = QHBoxLayout()
        self._btn_et_event_add = QPushButton("+ Ajouter action")
        self._btn_et_event_add.clicked.connect(self._et_event_add)
        ev_btn_row.addWidget(self._btn_et_event_add)
        self._btn_et_event_preset = QPushButton("Présets ▾")
        self._btn_et_event_preset.clicked.connect(self._et_event_preset)
        ev_btn_row.addWidget(self._btn_et_event_preset)
        self._btn_et_event_del = QPushButton("− Supprimer")
        self._btn_et_event_del.setEnabled(False)
        self._btn_et_event_del.clicked.connect(self._et_event_del)
        ev_btn_row.addWidget(self._btn_et_event_del)
        ev_btn_row.addStretch()
        ev_v.addLayout(ev_btn_row)

        self._et_event_list.currentRowChanged.connect(
            lambda r: self._btn_et_event_del.setEnabled(r >= 0))

        form.addRow(ev_grp)
        self._et_events_sep = ev_sep
        self._et_events_grp = ev_grp

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
        self._et_row_setvisible(self._et_hp_lbl, self._et_hp, is_enemy)
        self._et_row_setvisible(self._et_atk_lbl, self._et_atk, is_enemy)
        self._et_row_setvisible(self._et_def_lbl, self._et_def, is_enemy)
        self._et_row_setvisible(self._et_xp_lbl, self._et_xp, is_enemy)

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
                  self._et_change, self._et_hp, self._et_atk, self._et_def, self._et_xp,
                  self._et_dir, self._et_data, self._et_clamp):
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

        self._et_hp.setValue(int(t.get("hp", 10) or 10))
        self._et_atk.setValue(int(t.get("atk", 1) or 1))
        self._et_def.setValue(int(t.get("def", 0) or 0))
        self._et_xp.setValue(int(t.get("xp", 0) or 0))

        self._et_data.setValue(int(t.get("data") or 0))
        flags = int(t.get("flags") or 0)
        self._et_clamp.setChecked(bool(flags & 1))

        for w in (self._et_name, self._et_role, self._et_behavior,
                  self._et_speed, self._et_range, self._et_lose,
                  self._et_change, self._et_hp, self._et_atk, self._et_def, self._et_xp,
                  self._et_dir, self._et_data, self._et_clamp):
            w.blockSignals(False)

        self._et_update_form_visibility()
        self._et_update_sprite_info(t)
        self._et_load_events(t)

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
        t["hp"] = self._et_hp.value()
        t["atk"] = self._et_atk.value()
        t["def"] = self._et_def.value()
        t["xp"] = self._et_xp.value()
        t["direction"] = self._et_dir.currentData() or 0
        t["data"] = self._et_data.value()
        t["flags"] = 1 if self._et_clamp.isChecked() else 0

        # Save events
        t["events"] = self._et_collect_events()

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

    # -- entity type events ------------------------------------------------

    # Display label for event action items in the list
    _ACT_LABELS: dict[str, str] = {
        # Audio
        "play_sfx":            "Jouer SFX",
        "start_bgm":           "Démarrer BGM",
        "stop_bgm":            "Arrêter BGM",
        "fade_bgm":            "Fondu BGM",
        # Visuel / Effets
        "play_anim":           "Jouer animation",
        "screen_shake":        "Secousse écran",
        "fade_out":            "Fondu noir",
        "fade_in":             "Fondu entrant",
        # Score / Ressources
        "add_score":           "Ajouter score",
        "add_health":          "Ajouter HP",
        "set_health":          "Définir HP",
        "add_resource":        "Ajouter ressource",
        "remove_resource":     "Retirer ressource",
        # Flags / Variables
        "set_flag":            "Activer flag",
        "clear_flag":          "Désactiver flag",
        "inc_variable":        "Incrémenter variable",
        "dec_variable":        "Décrémenter variable",
        "set_variable":        "Définir variable",
        # Joueur
        "respawn_player":      "Respawn joueur",
        "lock_player_input":   "Bloquer contrôles",
        "unlock_player_input": "Débloquer contrôles",
        "force_jump":          "Forcer saut",
        "fire_player_shot":    "Tir joueur",
        "set_checkpoint":      "Checkpoint",
        "cycle_player_form":   "Forme suivante",
        "set_player_form":     "Définir forme",
        "enable_multijump":    "Activer multi-saut",
        "disable_multijump":   "Désactiver multi-saut",
        "enable_wall_grab":    "Activer wall grab",
        "disable_wall_grab":   "Désactiver wall grab",
        "set_gravity_dir":     "Définir gravité",
        # Entités
        "spawn_entity":        "Spawner entité",
        "show_entity":         "Afficher type entité",
        "hide_entity":         "Masquer type entité",
        "move_entity_to":      "Déplacer entité vers",
        "pause_entity_path":   "Pause chemin entité",
        "resume_entity_path":  "Reprendre chemin entité",
        "spawn_wave":          "Spawner wave",
        # Caméra / Scroll
        "set_scroll_speed":    "Vitesse scroll",
        "pause_scroll":        "Pause scroll",
        "resume_scroll":       "Reprendre scroll",
        "set_cam_target":      "Cible caméra",
        # Triggers
        "enable_trigger":      "Activer trigger",
        "disable_trigger":     "Désactiver trigger",
        # Scène / Navigation
        "goto_scene":          "Aller à scène",
        "warp_to":             "Téléporter → scène",
        "reset_scene":         "Réinitialiser scène",
        # RPG / Aventure
        "show_dialogue":       "Afficher dialogue",
        "give_item":           "Donner objet",
        "remove_item":         "Retirer objet",
        "unlock_door":         "Ouvrir porte",
        "unlock_ability":      "Débloquer capacité",
        "set_quest_stage":     "Étape de quête",
        "play_cutscene":       "Jouer cutscene",
        # Système
        "emit_event":          "Émettre événement",
        "save_game":           "Sauvegarder",
        "end_game":            "Fin de partie",
    }

    # Action groups for the combo (key = group label, values = ordered action keys)
    _ACT_GROUPS: list[tuple[str, list[str]]] = [
        ("Audio", ["play_sfx", "start_bgm", "stop_bgm", "fade_bgm"]),
        ("Visuel / Effets", ["play_anim", "screen_shake", "fade_out", "fade_in"]),
        ("Score / Ressources", ["add_score", "add_health", "set_health", "add_resource", "remove_resource"]),
        ("Flags / Variables", ["set_flag", "clear_flag", "inc_variable", "dec_variable", "set_variable"]),
        ("Joueur", [
            "respawn_player", "lock_player_input", "unlock_player_input",
            "force_jump", "fire_player_shot", "set_checkpoint",
            "cycle_player_form", "set_player_form",
            "enable_multijump", "disable_multijump",
            "enable_wall_grab", "disable_wall_grab", "set_gravity_dir",
        ]),
        ("Entités", [
            "spawn_entity", "show_entity", "hide_entity", "move_entity_to",
            "pause_entity_path", "resume_entity_path", "spawn_wave",
        ]),
        ("Caméra / Scroll", ["set_scroll_speed", "pause_scroll", "resume_scroll", "set_cam_target"]),
        ("Triggers", ["enable_trigger", "disable_trigger"]),
        ("Scène / Navigation", ["goto_scene", "warp_to", "reset_scene"]),
        ("RPG / Aventure", ["show_dialogue", "give_item", "remove_item", "unlock_door",
                            "unlock_ability", "set_quest_stage", "play_cutscene"]),
        ("Système", ["emit_event", "save_game", "end_game"]),
    ]

    _EV_LABELS: dict[str, str] = {
        "entity_death":         "Mort",
        "entity_collect":       "Collecte",
        "entity_activate":      "Activation",
        "entity_hit":           "Touché",
        "entity_spawn":         "Spawn",
        "entity_btn_a":         "Btn A pressé",
        "entity_btn_b":         "Btn B pressé",
        "entity_btn_opt":       "Option pressé",
        "entity_btn_up":        "Haut pressé",
        "entity_btn_down":      "Bas pressé",
        "entity_btn_left":      "Gauche pressé",
        "entity_btn_right":     "Droite pressé",
        "entity_player_enter":  "Joueur entre en zone",
        "entity_player_exit":   "Joueur quitte la zone",
        "entity_timer":         "Timer périodique",
        "entity_low_hp":        "HP bas (seuil)",
    }

    def _et_load_events(self, t: dict) -> None:
        """Populate _et_event_list from entity type events dict."""
        self._et_event_list.blockSignals(True)
        self._et_event_list.clear()
        events = get_type_events(t)
        for ev_name, actions in events.items():
            if not isinstance(actions, list):
                continue
            ev_lbl = self._EV_LABELS.get(ev_name, ev_name)
            for act in actions:
                if not isinstance(act, dict):
                    continue
                item = self._et_event_item(ev_name, act)
                self._et_event_list.addItem(item)
        self._et_event_list.blockSignals(False)
        self._btn_et_event_del.setEnabled(False)

    def _et_event_item(self, ev_name: str, act: dict) -> "QListWidgetItem":
        """Build a QListWidgetItem for one event action."""
        ev_lbl  = self._EV_LABELS.get(ev_name, ev_name)
        act_str = str(act.get("action") or "emit_event")
        act_lbl = self._ACT_LABELS.get(act_str, act_str)
        once    = act.get("once", False)

        # Build a short param summary
        params = ""
        if act_str in ("inc_variable", "dec_variable", "set_variable",
                       "set_flag", "clear_flag"):
            idx = int(act.get("flag_var_index") or 0)
            params = f" var[{idx}]"
            if act_str == "set_variable":
                params += f"={act.get('a1', 0)}"
        elif act_str == "goto_scene":
            params = f" → {act.get('scene_to') or '?'}"
        elif act_str in ("play_sfx", "start_bgm", "add_score",
                         "add_health", "set_health"):
            params = f" ({act.get('a0', 0)})"

        once_tag = " [×1]" if once else ""
        text = f"[{ev_lbl}]  {act_lbl}{params}{once_tag}"

        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, {"event": ev_name, **act})
        return item

    def _et_collect_events(self) -> dict:
        """Read _et_event_list and return events dict."""
        events: dict[str, list[dict]] = {}
        for i in range(self._et_event_list.count()):
            d = self._et_event_list.item(i).data(Qt.ItemDataRole.UserRole)
            if not isinstance(d, dict):
                continue
            ev_name = str(d.get("event") or "entity_death")
            act = {k: v for k, v in d.items() if k != "event"}
            events.setdefault(ev_name, []).append(act)
        return events

    # Preset event actions per role: (label, ev_name, action_dict)
    _PRESETS_BY_ROLE: dict[str, list[tuple[str, str, dict]]] = {
        "enemy": [
            ("Mort → Score +1",                  "entity_death",        {"action": "add_score",    "a0": 1}),
            ("Mort → Compteur kills (var[0])",   "entity_death",        {"action": "inc_variable", "flag_var_index": 0}),
            ("Mort → SFX (id 0)",                "entity_death",        {"action": "play_sfx",     "a0": 0}),
            ("Touché → SFX (id 1)",              "entity_hit",          {"action": "play_sfx",     "a0": 1}),
            ("HP bas → phase boss (emit 0)",     "entity_low_hp",       {"action": "emit_event",   "a0": 0}),
            ("Joueur entre zone → SFX alerte",   "entity_player_enter", {"action": "play_sfx",     "a0": 2}),
            ("Timer → event périodique",         "entity_timer",        {"action": "emit_event",   "a0": 0}),
        ],
        "item": [
            ("Collecte → Score +1",              "entity_collect",      {"action": "add_score",    "a0": 1}),
            ("Collecte → SFX pickup (id 0)",     "entity_collect",      {"action": "play_sfx",     "a0": 0}),
            ("Collecte → Flag ON (flag[0])",     "entity_collect",      {"action": "set_flag",     "flag_var_index": 0}),
            ("Collecte → Compteur (var[0])",     "entity_collect",      {"action": "inc_variable", "flag_var_index": 0}),
        ],
        "npc": [
            ("Btn A → SFX dialogue (id 0)",      "entity_btn_a",        {"action": "play_sfx",     "a0": 0}),
            ("Btn A → émettre event (id 0)",     "entity_btn_a",        {"action": "emit_event",   "a0": 0}),
            ("Joueur entre zone → SFX",          "entity_player_enter", {"action": "play_sfx",     "a0": 0}),
            ("Timer → event périodique",         "entity_timer",        {"action": "emit_event",   "a0": 0}),
        ],
        "trigger": [
            ("Btn A → activer flag (flag[0])",   "entity_btn_a",        {"action": "set_flag",     "flag_var_index": 0}),
            ("Btn A → émettre event (id 0)",     "entity_btn_a",        {"action": "emit_event",   "a0": 0}),
            ("Joueur entre → SFX",               "entity_player_enter", {"action": "play_sfx",     "a0": 0}),
            ("Joueur entre → émettre event",     "entity_player_enter", {"action": "emit_event",   "a0": 0}),
        ],
        "platform": [
            ("Btn A → SFX (id 0)",               "entity_btn_a",        {"action": "play_sfx",     "a0": 0}),
            ("Btn A → émettre event (id 0)",     "entity_btn_a",        {"action": "emit_event",   "a0": 0}),
            ("Joueur entre zone → SFX",          "entity_player_enter", {"action": "play_sfx",     "a0": 0}),
        ],
        "block": [
            ("Mort → SFX casse (id 0)",          "entity_death",        {"action": "play_sfx",     "a0": 0}),
            ("Mort → Score +1",                  "entity_death",        {"action": "add_score",    "a0": 1}),
            ("Touché → SFX (id 0)",              "entity_hit",          {"action": "play_sfx",     "a0": 0}),
            ("HP bas → émettre event",           "entity_low_hp",       {"action": "emit_event",   "a0": 0}),
        ],
        "prop": [
            ("Btn A → SFX (id 0)",               "entity_btn_a",        {"action": "play_sfx",     "a0": 0}),
            ("Btn A → émettre event (id 0)",     "entity_btn_a",        {"action": "emit_event",   "a0": 0}),
            ("Joueur entre zone → SFX",          "entity_player_enter", {"action": "play_sfx",     "a0": 0}),
            ("Timer → event périodique",         "entity_timer",        {"action": "emit_event",   "a0": 0}),
        ],
        "player": [
            ("Mort → SFX game over (id 0)",      "entity_death",        {"action": "play_sfx",     "a0": 0}),
            ("Mort → émettre event (id 0)",      "entity_death",        {"action": "emit_event",   "a0": 0}),
            ("Touché → SFX (id 1)",              "entity_hit",          {"action": "play_sfx",     "a0": 1}),
            ("Touché → Secousse écran",          "entity_hit",          {"action": "screen_shake", "a0": 3}),
            ("HP bas → SFX alerte (id 2)",       "entity_low_hp",       {"action": "play_sfx",     "a0": 2}),
            ("HP bas → changer BGM (id 1)",      "entity_low_hp",       {"action": "start_bgm",    "a0": 1}),
            ("Spawn → SFX respawn (id 0)",       "entity_spawn",        {"action": "play_sfx",     "a0": 0}),
            ("Btn A → SFX attaque (id 3)",       "entity_btn_a",        {"action": "play_sfx",     "a0": 3}),
            ("Btn B → SFX saut (id 4)",          "entity_btn_b",        {"action": "play_sfx",     "a0": 4}),
            ("Option → SFX menu (id 5)",         "entity_btn_opt",      {"action": "play_sfx",     "a0": 5}),
            ("Timer → HP regen (+1)",            "entity_timer",        {"action": "add_health",   "a0": 1}),
            ("Timer → event périodique",         "entity_timer",        {"action": "emit_event",   "a0": 0}),
        ],
    }

    def _et_event_preset(self) -> None:
        """Show a role-filtered preset menu and add the chosen action directly."""
        role = self._current_role()
        presets = self._PRESETS_BY_ROLE.get(role, [])
        if not presets:
            return
        menu = QMenu(self)
        for label, ev_name, act_template in presets:
            action = menu.addAction(label)
            action.setData((ev_name, dict(act_template)))
        btn = self._btn_et_event_preset
        chosen = menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
        if chosen is None:
            return
        ev_name, act = chosen.data()
        item = self._et_event_item(ev_name, act)
        self._et_event_list.addItem(item)
        self._save_current_et()

    def _current_role(self) -> str:
        return str(self._et_role.currentData() or "enemy")

    def _et_event_add(self) -> None:
        role = self._current_role()
        dlg = _TypeEventDialog(role, self._data, parent=self)
        if dlg.exec():
            ev_name, act = dlg.result_event, dlg.result_action
            item = self._et_event_item(ev_name, act)
            self._et_event_list.addItem(item)
            self._save_current_et()

    def _et_event_edit_selected(self, item: "QListWidgetItem") -> None:
        d = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(d, dict):
            return
        role = self._current_role()
        dlg = _TypeEventDialog(role, self._data,
                               ev_name=d.get("event", "entity_death"),
                               act=d, parent=self)
        if dlg.exec():
            new_item = self._et_event_item(dlg.result_event, dlg.result_action)
            row = self._et_event_list.row(item)
            self._et_event_list.takeItem(row)
            self._et_event_list.insertItem(row, new_item)
            self._save_current_et()

    def _et_event_del(self) -> None:
        row = self._et_event_list.currentRow()
        if row >= 0:
            self._et_event_list.takeItem(row)
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

    # ══════════════════════════════════════════════════════════════════════
    # Custom Events tab
    # ══════════════════════════════════════════════════════════════════════

    # Presets are lists of actions — one preset can insert several actions at once.
    # None = separator in the menu.
    _CEV_PRESETS: list[tuple[str, list[dict]] | None] = [
        # ── Actions simples ────────────────────────────────────────────────
        ("Jouer SFX (id 0)",         [{"action": "play_sfx",            "a0": 0}]),
        ("Démarrer BGM (id 0)",      [{"action": "start_bgm",           "a0": 0}]),
        ("Arrêter BGM",              [{"action": "stop_bgm"}]),
        ("Secousse écran",           [{"action": "screen_shake",        "a0": 3}]),
        ("Fondu noir",               [{"action": "fade_out"}]),
        ("Fondu entrant",            [{"action": "fade_in"}]),
        ("Activer flag [0]",         [{"action": "set_flag",            "flag_var_index": 0}]),
        ("Désactiver flag [0]",      [{"action": "clear_flag",          "flag_var_index": 0}]),
        ("Incrémenter variable [0]", [{"action": "inc_variable",        "flag_var_index": 0}]),
        ("Reset variable [0] → 0",  [{"action": "set_variable",        "flag_var_index": 0, "a1": 0}]),
        ("Émettre event (id 0)",     [{"action": "emit_event",          "a0": 0}]),
        ("Sauvegarder",              [{"action": "save_game"}]),
        ("Fin de partie",            [{"action": "end_game"}]),
        None,
        # ── Universels ─────────────────────────────────────────────────────
        ("Checkpoint : save + SFX + flag", [
            {"action": "set_flag",   "flag_var_index": 0},
            {"action": "save_game"},
            {"action": "play_sfx",   "a0": 0},
        ]),
        ("Game Over : fondu → scène", [
            {"action": "fade_out"},
            {"action": "goto_scene", "scene_to": ""},
        ]),
        ("Victoire : SFX + score + fade → scène", [
            {"action": "play_sfx",   "a0": 0},
            {"action": "add_score",  "a0": 100},
            {"action": "fade_out"},
            {"action": "goto_scene", "scene_to": ""},
        ]),
        ("Respawn joueur : respawn + secousse", [
            {"action": "respawn_player"},
            {"action": "screen_shake", "a0": 4},
        ]),
        None,
        # ── Platformer ─────────────────────────────────────────────────────
        ("Boss phase 2 : changer BGM + secousse + wave", [
            {"action": "stop_bgm"},
            {"action": "start_bgm",    "a0": 1},
            {"action": "screen_shake", "a0": 5},
            {"action": "spawn_wave",   "a0": 1},
        ]),
        ("Clé ramassée : +compteur + SFX + flag", [
            {"action": "inc_variable", "flag_var_index": 0},
            {"action": "play_sfx",     "a0": 0},
            {"action": "set_flag",     "flag_var_index": 1},
        ]),
        ("Porte débloquée : SFX + unlock + clear flag", [
            {"action": "play_sfx",     "a0": 0},
            {"action": "unlock_door",  "a0": 0},
            {"action": "clear_flag",   "flag_var_index": 1},
        ]),
        ("Invincibilité : multi-saut + lock HP", [
            {"action": "enable_multijump"},
            {"action": "set_variable", "flag_var_index": 0, "a1": 1},
        ]),
        None,
        # ── Shmup ──────────────────────────────────────────────────────────
        ("Alerte boss : SFX + secousse + next wave", [
            {"action": "play_sfx",    "a0": 0},
            {"action": "screen_shake","a0": 3},
            {"action": "spawn_wave",  "a0": 1},
        ]),
        ("Power-up : +power var + SFX", [
            {"action": "inc_variable", "flag_var_index": 0},
            {"action": "play_sfx",     "a0": 0},
        ]),
        ("Rang S — no-damage bonus : score + SFX", [
            {"action": "add_score",  "a0": 200},
            {"action": "play_sfx",   "a0": 0},
            {"action": "screen_shake","a0": 2},
        ]),
        None,
        # ── RPG / Adventure ────────────────────────────────────────────────
        ("Quête acceptée : étape 1 + dialogue + flag", [
            {"action": "set_quest_stage", "a0": 0, "a1": 1},
            {"action": "show_dialogue",   "a0": 0},
            {"action": "set_flag",        "flag_var_index": 0},
        ]),
        ("Item clé utilisé : retirer + débloquer + SFX", [
            {"action": "remove_item",  "a0": 0},
            {"action": "unlock_door",  "a0": 0},
            {"action": "play_sfx",     "a0": 0},
        ]),
        ("Récompense NPC : objet + dialogue + incrément", [
            {"action": "give_item",     "a0": 0},
            {"action": "show_dialogue", "a0": 0},
            {"action": "inc_variable",  "flag_var_index": 0},
        ]),
        ("Level up : reset XP + lvl + HP + SFX + secousse", [
            {"action": "set_variable",  "flag_var_index": 0, "a1": 0},   # reset XP
            {"action": "inc_variable",  "flag_var_index": 1},             # +level
            {"action": "add_health",    "a0": 20},
            {"action": "play_sfx",      "a0": 0},
            {"action": "screen_shake",  "a0": 2},
        ]),
        ("Cutscene narrative : lock input + cutscene + unlock", [
            {"action": "lock_player_input"},
            {"action": "play_cutscene", "a0": 0},
            {"action": "unlock_player_input"},
        ]),
        None,
        # ── Roguelite ──────────────────────────────────────────────────────
        ("Room cleared : SFX + spawn coffre + enable sortie", [
            {"action": "play_sfx",       "a0": 0},
            {"action": "spawn_entity",   "a0": 0},
            {"action": "enable_trigger", "a0": 0},
        ]),
        ("Mort permadeath : reset vars + save + game over", [
            {"action": "set_variable", "flag_var_index": 0, "a1": 0},
            {"action": "set_variable", "flag_var_index": 1, "a1": 0},
            {"action": "save_game"},
            {"action": "fade_out"},
            {"action": "goto_scene",   "scene_to": ""},
        ]),
        ("Drop rare (aléatoire) : objet + score + SFX", [
            {"action": "give_item",    "a0": 0},
            {"action": "add_score",    "a0": 50},
            {"action": "play_sfx",     "a0": 0},
        ]),
        ("Difficulté adaptive : +diff + wave suivante", [
            {"action": "inc_variable", "flag_var_index": 0},
            {"action": "spawn_wave",   "a0": 0},
            {"action": "play_sfx",     "a0": 0},
        ]),
        None,
        # ── Puzzle ─────────────────────────────────────────────────────────
        ("Puzzle résolu : SFX + unlock + flag done", [
            {"action": "play_sfx",     "a0": 0},
            {"action": "unlock_door",  "a0": 0},
            {"action": "set_flag",     "flag_var_index": 0},
        ]),
        ("Mauvaise combinaison : secousse + reset code", [
            {"action": "screen_shake", "a0": 3},
            {"action": "play_sfx",     "a0": 0},
            {"action": "set_variable", "flag_var_index": 0, "a1": 0},
        ]),
        None,
        # ── Racing / Arcade ────────────────────────────────────────────────
        ("Turbo boost : scroll max + SFX", [
            {"action": "set_scroll_speed", "a0": 8},
            {"action": "play_sfx",         "a0": 0},
        ]),
        ("Combo kill : score + secousse + SFX", [
            {"action": "add_score",    "a0": 50},
            {"action": "screen_shake", "a0": 2},
            {"action": "play_sfx",     "a0": 0},
        ]),
    ]

    # ------------------------------------------------------------------
    # Items tab (M4)
    # ------------------------------------------------------------------

    _ITEM_TYPES: list[tuple[str, str]] = [
        ("ITEM_HEAL",      "Heal HP"),
        ("ITEM_ATK_UP",    "ATK +"),
        ("ITEM_DEF_UP",    "DEF +"),
        ("ITEM_XP_UP",     "XP +"),
        ("ITEM_GOLD",      "Gold"),
        ("ITEM_DICE_PLUS", "Dice +"),
        ("ITEM_KEY",       "Key"),
        ("ITEM_CUSTOM",    "Custom"),
    ]
    _RARITY_LABELS: list[str] = ["Common", "Uncommon", "Rare"]

    def _build_items_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        hint = QLabel(
            "Définissez la table d'items du projet. Exportée en <b>item_table.h</b>."
            "<br>Chaque item a un type, une valeur, une rareté et un prix (boutique)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#aaa;font-size:11px;")
        lay.addWidget(hint)

        self._item_table = QTableWidget(0, 6)
        self._item_table.setHorizontalHeaderLabels(["Nom", "Type", "Valeur", "Rareté", "Prix", "Sprite"])
        self._item_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._item_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._item_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._item_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._item_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._item_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self._item_table.verticalHeader().setDefaultSectionSize(24)
        self._item_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self._item_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._item_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._item_table.itemChanged.connect(self._on_item_table_changed)
        lay.addWidget(self._item_table, 1)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("+ Ajouter")
        btn_add.clicked.connect(self._item_add)
        btn_row.addWidget(btn_add)
        self._btn_item_del = QPushButton("− Supprimer")
        self._btn_item_del.setEnabled(False)
        self._btn_item_del.clicked.connect(self._item_del)
        btn_row.addWidget(self._btn_item_del)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._item_table.itemSelectionChanged.connect(
            lambda: self._btn_item_del.setEnabled(self._item_table.currentRow() >= 0)
        )
        return w

    def _refresh_item_ids(self) -> None:
        """Update vertical header to show 0-based item indices (ITEM_IDX_*)."""
        n = self._item_table.rowCount()
        self._item_table.setVerticalHeaderLabels([str(i) for i in range(n)])

    def _item_add(self) -> None:
        self._item_insert_row({"name": "item", "type": "ITEM_HEAL", "value": 10, "rarity": 0, "price": 5})
        self._refresh_item_ids()
        self._save_items_to_project()

    def _item_del(self) -> None:
        row = self._item_table.currentRow()
        if row >= 0:
            self._item_table.removeRow(row)
            self._refresh_item_ids()
            self._save_items_to_project()

    def _item_insert_row(self, item: dict) -> None:
        self._item_table.blockSignals(True)
        row = self._item_table.rowCount()
        self._item_table.insertRow(row)

        # Col 0: name
        self._item_table.setItem(row, 0, QTableWidgetItem(str(item.get("name", "item"))))

        # Col 1: type combo
        type_combo = QComboBox()
        for key, label in self._ITEM_TYPES:
            type_combo.addItem(label, key)
        cur_type = str(item.get("type", "ITEM_HEAL"))
        idx = next((i for i, (k, _) in enumerate(self._ITEM_TYPES) if k == cur_type), 0)
        type_combo.setCurrentIndex(idx)
        type_combo.currentIndexChanged.connect(self._save_items_to_project)
        self._item_table.setCellWidget(row, 1, type_combo)

        # Col 2: value spin
        val_spin = QSpinBox()
        val_spin.setRange(0, 255)
        val_spin.setFrame(False)
        val_spin.setValue(max(0, min(255, int(item.get("value", 0) or 0))))
        val_spin.valueChanged.connect(self._save_items_to_project)
        self._item_table.setCellWidget(row, 2, val_spin)

        # Col 3: rarity combo
        rar_combo = QComboBox()
        for label in self._RARITY_LABELS:
            rar_combo.addItem(label)
        rar_combo.setCurrentIndex(max(0, min(len(self._RARITY_LABELS) - 1, int(item.get("rarity", 0) or 0))))
        rar_combo.currentIndexChanged.connect(self._save_items_to_project)
        self._item_table.setCellWidget(row, 3, rar_combo)

        # Col 4: price spin
        price_spin = QSpinBox()
        price_spin.setRange(0, 255)
        price_spin.setFrame(False)
        price_spin.setValue(max(0, min(255, int(item.get("price", 0) or 0))))
        price_spin.valueChanged.connect(self._save_items_to_project)
        self._item_table.setCellWidget(row, 4, price_spin)

        # Col 5: sprite_id spin (index metasprite dans le bundle PNG)
        sprite_spin = QSpinBox()
        sprite_spin.setRange(0, 255)
        sprite_spin.setFrame(False)
        sprite_spin.setValue(max(0, min(255, int(item.get("sprite_id", 0) or 0))))
        sprite_spin.setToolTip("Index du metasprite dans le bundle PNG (NGPNG_MSPR_*)")
        sprite_spin.valueChanged.connect(self._save_items_to_project)
        self._item_table.setCellWidget(row, 5, sprite_spin)

        self._item_table.blockSignals(False)
        self._refresh_item_ids()

    def _on_item_table_changed(self) -> None:
        self._save_items_to_project()

    def _load_items_from_project(self) -> None:
        raw = []
        if isinstance(self._data, dict):
            raw = self._data.get("item_table", []) or []
            if not isinstance(raw, list):
                raw = []
        self._item_table.blockSignals(True)
        self._item_table.setRowCount(0)
        for item in raw:
            if isinstance(item, dict):
                self._item_insert_row(item)
        self._item_table.blockSignals(False)
        self._refresh_item_ids()

    def _save_items_to_project(self) -> None:
        items = []
        for row in range(self._item_table.rowCount()):
            name_item = self._item_table.item(row, 0)
            name = name_item.text().strip() if name_item else "item"
            type_combo = self._item_table.cellWidget(row, 1)
            item_type = type_combo.currentData() if type_combo else "ITEM_HEAL"
            val_spin = self._item_table.cellWidget(row, 2)
            value = val_spin.value() if val_spin else 0
            rar_combo = self._item_table.cellWidget(row, 3)
            rarity = rar_combo.currentIndex() if rar_combo else 0
            price_spin = self._item_table.cellWidget(row, 4)
            price = price_spin.value() if price_spin else 0
            sprite_spin = self._item_table.cellWidget(row, 5)
            sprite_id = sprite_spin.value() if sprite_spin else 0
            items.append({"name": name, "type": item_type, "value": value, "rarity": rarity, "price": price, "sprite_id": sprite_id})
        if isinstance(self._data, dict):
            self._data["item_table"] = items
        self._on_save()

    def _build_custom_events_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        hint = QLabel(
            "Définissez des événements nommés déclenchés par <b>emit_event(id)</b>. "
            "Chaque événement peut exécuter une ou plusieurs actions "
            "depuis n'importe quelle scène ou type d'entité."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888;font-size:10px;")
        lay.addWidget(hint)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # ── Top panel : event list ─────────────────────────────────────
        top_w = QWidget()
        top_lay = QVBoxLayout(top_w)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.setSpacing(3)

        top_lbl = QLabel("Événements définis :")
        top_lbl.setStyleSheet("font-weight:bold;font-size:11px;")
        top_lay.addWidget(top_lbl)

        self._cev_list = QListWidget()
        self._cev_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._cev_list.setMinimumHeight(100)
        top_lay.addWidget(self._cev_list)

        btn_row1 = QHBoxLayout()
        btn_row1.setSpacing(3)
        self._btn_cev_add      = QPushButton("+ Ajouter")
        self._btn_cev_rename   = QPushButton("Renommer")
        self._btn_cev_category = QPushButton("Catégorie…")
        self._btn_cev_up       = QPushButton("↑")
        self._btn_cev_down     = QPushButton("↓")
        self._btn_cev_del      = QPushButton("− Supprimer")
        for b in (self._btn_cev_up, self._btn_cev_down):
            b.setFixedWidth(28)
        for b in (self._btn_cev_rename, self._btn_cev_category,
                  self._btn_cev_up, self._btn_cev_down, self._btn_cev_del):
            b.setEnabled(False)
        self._btn_cev_add.clicked.connect(self._cev_add)
        self._btn_cev_rename.clicked.connect(self._cev_rename)
        self._btn_cev_category.clicked.connect(self._cev_set_category)
        self._btn_cev_up.clicked.connect(self._cev_move_up)
        self._btn_cev_down.clicked.connect(self._cev_move_down)
        self._btn_cev_del.clicked.connect(self._cev_del)
        for b in (self._btn_cev_add, self._btn_cev_rename, self._btn_cev_category,
                  self._btn_cev_up, self._btn_cev_down, self._btn_cev_del):
            btn_row1.addWidget(b)
        btn_row1.addStretch()
        top_lay.addLayout(btn_row1)
        splitter.addWidget(top_w)

        # ── Bottom panel : QTabWidget (Conditions | Actions) ─────────────
        self._cev_bot_tabs = QTabWidget()
        self._cev_bot_tabs.setDocumentMode(True)
        self._cev_bot_tabs.setEnabled(False)

        # ── Tab 1: Conditions (guard ET + groupes OU) ─────────────────
        cond_w = QWidget()
        cond_lay = QVBoxLayout(cond_w)
        cond_lay.setContentsMargins(4, 4, 4, 4)
        cond_lay.setSpacing(4)

        cond_hint = QLabel(
            "Si aucune condition : l'événement s'exécute toujours. "
            "Conditions ET : toutes doivent être vraies. "
            "Groupes OU : une alternative suffit."
        )
        cond_hint.setWordWrap(True)
        cond_hint.setStyleSheet("color:#888;font-size:10px;")
        cond_lay.addWidget(cond_hint)

        # Primary AND conditions
        and_lbl = QLabel("Conditions (ET) :")
        and_lbl.setStyleSheet("font-weight:bold;font-size:11px;")
        cond_lay.addWidget(and_lbl)

        self._cev_and_list = QListWidget()
        self._cev_and_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._cev_and_list.setMaximumHeight(90)
        cond_lay.addWidget(self._cev_and_list)

        and_btns = QHBoxLayout()
        and_btns.setSpacing(3)
        self._btn_cev_and_add  = QPushButton("+ Ajouter")
        self._btn_cev_and_edit = QPushButton("Modifier")
        self._btn_cev_and_del  = QPushButton("− Supprimer")
        for b in (self._btn_cev_and_add, self._btn_cev_and_edit, self._btn_cev_and_del):
            b.setEnabled(False)
        self._btn_cev_and_add.clicked.connect(self._cev_and_add)
        self._btn_cev_and_edit.clicked.connect(self._cev_and_edit_selected)
        self._btn_cev_and_del.clicked.connect(self._cev_and_del)
        self._cev_and_list.itemDoubleClicked.connect(self._cev_and_edit)
        for b in (self._btn_cev_and_add, self._btn_cev_and_edit, self._btn_cev_and_del):
            and_btns.addWidget(b)
        and_btns.addStretch()
        cond_lay.addLayout(and_btns)

        # OR groups
        or_hdr = QHBoxLayout()
        or_lbl = QLabel("Groupes OU :")
        or_lbl.setStyleSheet("font-weight:bold;font-size:11px;")
        or_hdr.addWidget(or_lbl)
        self._cev_or_group_combo = QComboBox()
        self._cev_or_group_combo.setMinimumWidth(110)
        or_hdr.addWidget(self._cev_or_group_combo)
        self._btn_cev_or_grp_add = QPushButton("+ Groupe")
        self._btn_cev_or_grp_del = QPushButton("− Groupe")
        self._btn_cev_or_grp_add.setEnabled(False)
        self._btn_cev_or_grp_del.setEnabled(False)
        self._btn_cev_or_grp_add.clicked.connect(self._cev_or_group_add)
        self._btn_cev_or_grp_del.clicked.connect(self._cev_or_group_del)
        or_hdr.addWidget(self._btn_cev_or_grp_add)
        or_hdr.addWidget(self._btn_cev_or_grp_del)
        or_hdr.addStretch()
        cond_lay.addLayout(or_hdr)

        self._cev_or_list = QListWidget()
        self._cev_or_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._cev_or_list.setMaximumHeight(80)
        self._cev_or_list.setEnabled(False)
        cond_lay.addWidget(self._cev_or_list)

        or_btns = QHBoxLayout()
        or_btns.setSpacing(3)
        self._btn_cev_or_add  = QPushButton("+ Condition OU")
        self._btn_cev_or_edit = QPushButton("Modifier")
        self._btn_cev_or_del  = QPushButton("− Supprimer")
        for b in (self._btn_cev_or_add, self._btn_cev_or_edit, self._btn_cev_or_del):
            b.setEnabled(False)
        self._btn_cev_or_add.clicked.connect(self._cev_or_cond_add)
        self._btn_cev_or_edit.clicked.connect(self._cev_or_cond_edit_selected)
        self._btn_cev_or_del.clicked.connect(self._cev_or_cond_del)
        self._cev_or_list.itemDoubleClicked.connect(self._cev_or_cond_edit)
        for b in (self._btn_cev_or_add, self._btn_cev_or_edit, self._btn_cev_or_del):
            or_btns.addWidget(b)
        or_btns.addStretch()
        cond_lay.addLayout(or_btns)

        self._cev_bot_tabs.addTab(cond_w, "Conditions")

        # ── Tab 2: Actions ────────────────────────────────────────────
        act_w = QWidget()
        act_lay = QVBoxLayout(act_w)
        act_lay.setContentsMargins(4, 4, 4, 4)
        act_lay.setSpacing(3)

        self._cev_act_lbl = QLabel("Actions :")
        self._cev_act_lbl.setStyleSheet("font-weight:bold;font-size:11px;")
        act_lay.addWidget(self._cev_act_lbl)

        self._cev_act_hint = QLabel("← Sélectionnez un événement pour voir ses actions.")
        self._cev_act_hint.setStyleSheet("color:#888;font-size:10px;")
        self._cev_act_hint.setWordWrap(True)
        act_lay.addWidget(self._cev_act_hint)

        self._cev_act_list = QListWidget()
        self._cev_act_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._cev_act_list.setMinimumHeight(80)
        self._cev_act_list.itemDoubleClicked.connect(self._cev_action_edit)
        act_lay.addWidget(self._cev_act_list)

        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(3)
        self._btn_cev_act_add    = QPushButton("+ Ajouter action")
        self._btn_cev_act_preset = QPushButton("Présets ▾")
        self._btn_cev_act_del    = QPushButton("− Supprimer")
        for b in (self._btn_cev_act_add, self._btn_cev_act_preset, self._btn_cev_act_del):
            b.setEnabled(False)
        self._btn_cev_act_add.clicked.connect(self._cev_action_add)
        self._btn_cev_act_preset.clicked.connect(self._cev_action_preset)
        self._btn_cev_act_del.clicked.connect(self._cev_action_del)
        for b in (self._btn_cev_act_add, self._btn_cev_act_preset, self._btn_cev_act_del):
            btn_row2.addWidget(b)
        btn_row2.addStretch()
        act_lay.addLayout(btn_row2)

        self._cev_bot_tabs.addTab(act_w, "Actions")
        splitter.addWidget(self._cev_bot_tabs)

        splitter.setSizes([200, 260])
        lay.addWidget(splitter)

        # Wire signals
        self._cev_list.currentRowChanged.connect(self._cev_on_select_row)
        self._cev_act_list.currentRowChanged.connect(
            lambda r: self._btn_cev_act_del.setEnabled(r >= 0))
        self._cev_and_list.currentRowChanged.connect(self._cev_on_and_sel)
        self._cev_or_group_combo.currentIndexChanged.connect(self._cev_on_or_group_changed)
        self._cev_or_list.currentRowChanged.connect(self._cev_on_or_sel)

        return w

    # -- helpers -----------------------------------------------------------

    def _cev_events(self) -> list[dict]:
        """Return the live custom_events list from project data."""
        from core.custom_events import get_custom_events
        evs = get_custom_events(self._data)
        # Ensure list is stored in self._data for in-place mutation
        if "custom_events" not in self._data:
            self._data["custom_events"] = evs
        return evs

    def _cev_selected_event(self) -> dict | None:
        """Return the currently selected event dict, or None."""
        item = self._cev_list.currentItem()
        if item is None:
            return None
        eid = item.data(Qt.ItemDataRole.UserRole)
        if not eid:
            return None
        return next((e for e in self._cev_events() if e.get("id") == eid), None)

    def _cev_selected_flat_index(self) -> int:
        """Return the flat index of the selected event in custom_events, or -1."""
        item = self._cev_list.currentItem()
        if item is None:
            return -1
        eid = item.data(Qt.ItemDataRole.UserRole)
        if not eid:
            return -1
        for i, e in enumerate(self._cev_events()):
            if e.get("id") == eid:
                return i
        return -1

    _A0_A1_DISPLAY = frozenset({
        "move_entity_to", "add_resource", "remove_resource", "set_quest_stage",
    })
    _A0_DISPLAY = frozenset({
        "play_sfx", "start_bgm", "fade_bgm", "play_anim", "screen_shake",
        "add_score", "add_health", "set_health", "add_resource", "remove_resource",
        "spawn_entity", "show_entity", "hide_entity", "move_entity_to",
        "set_player_form", "set_checkpoint", "pause_entity_path", "resume_entity_path",
        "spawn_wave", "set_scroll_speed", "set_cam_target",
        "enable_trigger", "disable_trigger",
        "show_dialogue", "give_item", "remove_item", "unlock_door",
        "unlock_ability", "set_quest_stage", "play_cutscene", "set_gravity_dir",
        "emit_event",
    })

    def _cev_action_item(self, act: dict) -> "QListWidgetItem":
        """Build a display item for one action."""
        act_str = str(act.get("action") or "emit_event")
        act_lbl = self._ACT_LABELS.get(act_str, act_str)
        once    = act.get("once", False)
        params  = ""
        if act_str in ("inc_variable", "dec_variable", "set_variable",
                       "set_flag", "clear_flag"):
            idx = int(act.get("flag_var_index") or 0)
            params = f" [{idx}]"
            if act_str == "set_variable":
                params += f"={act.get('a1', 0)}"
        elif act_str in ("goto_scene", "warp_to"):
            params = f" → {act.get('scene_to') or '?'}"
        elif act_str in self._A0_A1_DISPLAY:
            params = f" ({act.get('a0', 0)}, {act.get('a1', 0)})"
        elif act_str in self._A0_DISPLAY:
            params = f" ({act.get('a0', 0)})"
        once_tag = " [×1]" if once else ""
        text = f"  {act_lbl}{params}{once_tag}"
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, dict(act))
        return item

    # -- load / save -------------------------------------------------------

    def _cev_load_all(self, restore_id: str = "") -> None:
        """Populate _cev_list from project data, grouped by category."""
        self._cev_list.blockSignals(True)
        self._cev_list.clear()
        evs = self._cev_events()

        # Group by category (preserve insertion order within each group)
        groups: dict[str, list[dict]] = {}
        for ev in evs:
            cat = str(ev.get("category") or "")
            groups.setdefault(cat, []).append(ev)

        # Uncategorized first, then alphabetical categories
        order = [""] + sorted(k for k in groups if k)
        restore_row = -1
        for cat in order:
            if cat not in groups:
                continue
            if cat:
                sep = QListWidgetItem(f"── {cat} ──")
                sep.setFlags(Qt.ItemFlag.NoItemFlags)
                sep.setForeground(self._cev_list.palette().mid())
                f = sep.font()
                f.setBold(True)
                sep.setFont(f)
                self._cev_list.addItem(sep)
            for ev in groups[cat]:
                eid  = str(ev.get("id") or "")
                name = str(ev.get("name") or eid)
                n_acts = len(ev.get("actions") or [])
                idx  = evs.index(ev)
                label = f"[{idx}] {name}  ({n_acts} action{'s' if n_acts != 1 else ''})"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, eid)
                self._cev_list.addItem(item)
                if eid == restore_id:
                    restore_row = self._cev_list.count() - 1

        self._cev_list.blockSignals(False)
        if restore_row >= 0:
            self._cev_list.setCurrentRow(restore_row)
        else:
            self._cev_on_select_row(-1)

    def _cev_load_actions(self, ev: dict) -> None:
        """Populate the action list for the given event."""
        from core.custom_events import get_custom_event_actions
        self._cev_act_list.blockSignals(True)
        self._cev_act_list.clear()
        for act in get_custom_event_actions(ev):
            if isinstance(act, dict):
                self._cev_act_list.addItem(self._cev_action_item(act))
        self._cev_act_list.blockSignals(False)
        self._btn_cev_act_del.setEnabled(False)

    def _cev_save_actions(self) -> None:
        """Write the action list widget back into the selected event's 'actions' key."""
        ev = self._cev_selected_event()
        if ev is None:
            return
        actions: list[dict] = []
        for i in range(self._cev_act_list.count()):
            d = self._cev_act_list.item(i).data(Qt.ItemDataRole.UserRole)
            if isinstance(d, dict):
                actions.append(d)
        ev["actions"] = actions
        self._on_save()

    # -- event list interactions -------------------------------------------

    def _cev_on_select_row(self, row: int) -> None:
        """Called when selection changes in the event list."""
        ev = self._cev_selected_event()
        has_sel = ev is not None
        for b in (self._btn_cev_rename, self._btn_cev_category,
                  self._btn_cev_up, self._btn_cev_down, self._btn_cev_del):
            b.setEnabled(has_sel)
        for b in (self._btn_cev_act_add, self._btn_cev_act_preset,
                  self._btn_cev_and_add, self._btn_cev_or_grp_add):
            b.setEnabled(has_sel)
        self._cev_act_list.setEnabled(has_sel)
        self._cev_bot_tabs.setEnabled(has_sel)
        if has_sel:
            name = str(ev.get("name") or "?")
            idx  = self._cev_selected_flat_index()
            self._cev_act_lbl.setText(
                f"Actions pour <b>[{idx}] {name}</b> :")
            self._cev_act_hint.setVisible(False)
            self._cev_load_actions(ev)
            self._cev_load_conditions(ev)
        else:
            self._cev_act_lbl.setText("Actions :")
            self._cev_act_hint.setVisible(True)
            self._cev_act_list.clear()
            self._btn_cev_act_del.setEnabled(False)
            self._cev_and_list.clear()
            self._cev_or_list.clear()
            self._cev_or_group_combo.clear()

    def _cev_add(self) -> None:
        from core.custom_events import new_custom_event
        name, ok = QInputDialog.getText(self, "Nouvel événement", "Nom de l'événement :")
        if not ok or not name.strip():
            return
        ev = new_custom_event(name.strip())
        # Avoid duplicate id
        evs = self._cev_events()
        existing_ids = {e.get("id") for e in evs}
        base = ev["id"]
        suffix = 2
        while ev["id"] in existing_ids:
            ev["id"] = f"{base}_{suffix}"
            suffix += 1
        evs.append(ev)
        self._on_save()
        self._cev_load_all(restore_id=ev["id"])

    def _cev_rename(self) -> None:
        import re
        ev = self._cev_selected_event()
        if ev is None:
            return
        new_name, ok = QInputDialog.getText(
            self, "Renommer l'événement", "Nouveau nom :",
            text=str(ev.get("name") or ""))
        if not ok or not new_name.strip():
            return
        safe = re.sub(r"[^A-Za-z0-9_]", "_", new_name.strip()).strip("_") or "event"
        ev["name"] = safe
        self._on_save()
        self._cev_load_all(restore_id=str(ev.get("id") or ""))

    def _cev_set_category(self) -> None:
        ev = self._cev_selected_event()
        if ev is None:
            return
        # Suggest existing categories
        existing = sorted({str(e.get("category") or "")
                           for e in self._cev_events() if e.get("category")})
        hint = f"Catégorie (laisser vide pour aucune).\nExistantes : {', '.join(existing)}" \
               if existing else "Catégorie (laisser vide pour aucune) :"
        cat, ok = QInputDialog.getText(
            self, "Catégorie de l'événement", hint,
            text=str(ev.get("category") or ""))
        if not ok:
            return
        ev["category"] = cat.strip()
        self._on_save()
        self._cev_load_all(restore_id=str(ev.get("id") or ""))

    def _cev_move_up(self) -> None:
        idx = self._cev_selected_flat_index()
        if idx <= 0:
            return
        evs = self._cev_events()
        evs[idx], evs[idx - 1] = evs[idx - 1], evs[idx]
        self._on_save()
        self._cev_load_all(restore_id=str(evs[idx - 1].get("id") or ""))

    def _cev_move_down(self) -> None:
        idx = self._cev_selected_flat_index()
        evs = self._cev_events()
        if idx < 0 or idx >= len(evs) - 1:
            return
        evs[idx], evs[idx + 1] = evs[idx + 1], evs[idx]
        self._on_save()
        self._cev_load_all(restore_id=str(evs[idx + 1].get("id") or ""))

    def _cev_del(self) -> None:
        ev = self._cev_selected_event()
        if ev is None:
            return
        evs = self._cev_events()
        evs.remove(ev)
        self._on_save()
        self._cev_load_all()

    # -- action list interactions ------------------------------------------

    def _cev_action_add(self) -> None:
        ev = self._cev_selected_event()
        if ev is None:
            return
        dlg = _CevActionDialog(self._data, parent=self)
        if dlg.exec():
            self._cev_act_list.addItem(self._cev_action_item(dlg.result_action))
            self._cev_save_actions()

    def _cev_action_edit(self, item: "QListWidgetItem") -> None:
        act = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(act, dict):
            return
        dlg = _CevActionDialog(self._data, act=act, parent=self)
        if dlg.exec():
            new_item = self._cev_action_item(dlg.result_action)
            row = self._cev_act_list.row(item)
            self._cev_act_list.takeItem(row)
            self._cev_act_list.insertItem(row, new_item)
            self._cev_save_actions()

    def _cev_action_preset(self) -> None:
        menu = QMenu(self)
        for item in self._CEV_PRESETS:
            if item is None:
                menu.addSeparator()
            else:
                label, acts = item
                action = menu.addAction(label)
                action.setData(list(acts))
        btn = self._btn_cev_act_preset
        chosen = menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
        if chosen is None:
            return
        for act in chosen.data():
            self._cev_act_list.addItem(self._cev_action_item(dict(act)))
        self._cev_save_actions()

    def _cev_action_del(self) -> None:
        row = self._cev_act_list.currentRow()
        if row >= 0:
            self._cev_act_list.takeItem(row)
            self._cev_save_actions()

    # -- condition display helpers ------------------------------------------

    def _cev_cond_item(self, cond: dict) -> "QListWidgetItem":
        """Build a display QListWidgetItem for one guard condition."""
        from ui.tabs.globals_tab import _CevCondDialog
        cond_str = str(cond.get("cond") or "?")
        label    = _CevCondDialog._COND_LABELS.get(cond_str, cond_str)
        index    = int(cond.get("index") or 0)
        value    = int(cond.get("value") or 0)
        negate   = bool(cond.get("negate"))
        prefix   = "NON " if negate else ""
        params   = ""
        if cond_str in _CevCondDialog._INDEX_CONDS and cond_str in _CevCondDialog._VALUE_CONDS:
            params = f" [{index}] ≥/=/≤ {value}"
        elif cond_str in _CevCondDialog._INDEX_CONDS:
            params = f" [{index}]"
        elif cond_str in _CevCondDialog._VALUE_CONDS:
            params = f" ({value})"
        item = QListWidgetItem(f"  {prefix}{label}{params}")
        item.setData(Qt.ItemDataRole.UserRole, dict(cond))
        return item

    # -- conditions load / save --------------------------------------------

    def _cev_load_conditions(self, ev: dict) -> None:
        """Populate condition widgets from the event's conditions/or_groups."""
        from core.custom_events import get_custom_event_conditions, get_custom_event_or_groups
        # Primary AND conditions
        self._cev_and_list.blockSignals(True)
        self._cev_and_list.clear()
        for c in get_custom_event_conditions(ev):
            if isinstance(c, dict):
                self._cev_and_list.addItem(self._cev_cond_item(c))
        self._cev_and_list.blockSignals(False)
        self._btn_cev_and_edit.setEnabled(False)
        self._btn_cev_and_del.setEnabled(False)
        # OR groups
        self._cev_or_group_combo.blockSignals(True)
        self._cev_or_group_combo.clear()
        groups = get_custom_event_or_groups(ev)
        for i in range(len(groups)):
            self._cev_or_group_combo.addItem(f"Groupe OU {i + 1}", i)
        self._cev_or_group_combo.blockSignals(False)
        has_groups = len(groups) > 0
        self._btn_cev_or_grp_del.setEnabled(has_groups)
        self._cev_or_list.setEnabled(has_groups)
        for b in (self._btn_cev_or_add, self._btn_cev_or_edit, self._btn_cev_or_del):
            b.setEnabled(False)
        self._cev_on_or_group_changed(0)

    def _cev_save_conditions(self) -> None:
        """Write condition widgets back to the selected event dict."""
        ev = self._cev_selected_event()
        if ev is None:
            return
        # Primary AND
        and_conds: list[dict] = []
        for i in range(self._cev_and_list.count()):
            d = self._cev_and_list.item(i).data(Qt.ItemDataRole.UserRole)
            if isinstance(d, dict):
                and_conds.append(d)
        ev["conditions"] = and_conds
        # OR groups
        n_groups = self._cev_or_group_combo.count()
        from core.custom_events import get_custom_event_or_groups
        groups = get_custom_event_or_groups(ev)
        # Rebuild from widget (current group may be dirty)
        grp_idx = self._cev_or_group_combo.currentData()
        if grp_idx is not None and 0 <= grp_idx < len(groups):
            oc: list[dict] = []
            for i in range(self._cev_or_list.count()):
                d = self._cev_or_list.item(i).data(Qt.ItemDataRole.UserRole)
                if isinstance(d, dict):
                    oc.append(d)
            groups[grp_idx] = oc
        ev["or_groups"] = groups
        self._on_save()

    # -- AND condition interactions -----------------------------------------

    def _cev_on_and_sel(self, row: int) -> None:
        self._btn_cev_and_edit.setEnabled(row >= 0)
        self._btn_cev_and_del.setEnabled(row >= 0)

    def _cev_and_add(self) -> None:
        ev = self._cev_selected_event()
        if ev is None:
            return
        dlg = _CevCondDialog(self._data, parent=self)
        if dlg.exec():
            self._cev_and_list.addItem(self._cev_cond_item(dlg.result_cond))
            self._cev_save_conditions()

    def _cev_and_edit(self, item: "QListWidgetItem") -> None:
        cond = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(cond, dict):
            return
        dlg = _CevCondDialog(self._data, cond=cond, parent=self)
        if dlg.exec():
            row = self._cev_and_list.row(item)
            self._cev_and_list.takeItem(row)
            self._cev_and_list.insertItem(row, self._cev_cond_item(dlg.result_cond))
            self._cev_save_conditions()

    def _cev_and_edit_selected(self) -> None:
        item = self._cev_and_list.currentItem()
        if item:
            self._cev_and_edit(item)

    def _cev_and_del(self) -> None:
        row = self._cev_and_list.currentRow()
        if row >= 0:
            self._cev_and_list.takeItem(row)
            self._cev_save_conditions()

    # -- OR group interactions ----------------------------------------------

    def _cev_on_or_group_changed(self, idx: int) -> None:
        """Populate OR condition list for the selected group."""
        from core.custom_events import get_custom_event_or_groups
        ev = self._cev_selected_event()
        self._cev_or_list.blockSignals(True)
        self._cev_or_list.clear()
        if ev is not None:
            grp_idx = self._cev_or_group_combo.currentData()
            groups  = get_custom_event_or_groups(ev)
            if grp_idx is not None and 0 <= grp_idx < len(groups):
                for c in groups[grp_idx]:
                    if isinstance(c, dict):
                        self._cev_or_list.addItem(self._cev_cond_item(c))
        has_groups = self._cev_or_group_combo.count() > 0
        self._cev_or_list.setEnabled(has_groups)
        self._btn_cev_or_add.setEnabled(has_groups)
        self._btn_cev_or_edit.setEnabled(False)
        self._btn_cev_or_del.setEnabled(False)
        self._cev_or_list.blockSignals(False)

    def _cev_on_or_sel(self, row: int) -> None:
        self._btn_cev_or_edit.setEnabled(row >= 0)
        self._btn_cev_or_del.setEnabled(row >= 0)

    def _cev_or_group_add(self) -> None:
        ev = self._cev_selected_event()
        if ev is None:
            return
        groups = ev.setdefault("or_groups", [])
        groups.append([])
        self._on_save()
        self._cev_load_conditions(ev)
        self._cev_or_group_combo.setCurrentIndex(self._cev_or_group_combo.count() - 1)

    def _cev_or_group_del(self) -> None:
        ev = self._cev_selected_event()
        if ev is None:
            return
        grp_idx = self._cev_or_group_combo.currentData()
        groups  = ev.get("or_groups") or []
        if grp_idx is not None and 0 <= grp_idx < len(groups):
            groups.pop(grp_idx)
            ev["or_groups"] = groups
            self._on_save()
            self._cev_load_conditions(ev)

    def _cev_or_cond_add(self) -> None:
        ev = self._cev_selected_event()
        if ev is None:
            return
        grp_idx = self._cev_or_group_combo.currentData()
        if grp_idx is None:
            return
        dlg = _CevCondDialog(self._data, parent=self)
        if dlg.exec():
            self._cev_or_list.addItem(self._cev_cond_item(dlg.result_cond))
            self._cev_save_or_group(ev, grp_idx)

    def _cev_or_cond_edit(self, item: "QListWidgetItem") -> None:
        ev = self._cev_selected_event()
        grp_idx = self._cev_or_group_combo.currentData()
        if ev is None or grp_idx is None:
            return
        cond = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(cond, dict):
            return
        dlg = _CevCondDialog(self._data, cond=cond, parent=self)
        if dlg.exec():
            row = self._cev_or_list.row(item)
            self._cev_or_list.takeItem(row)
            self._cev_or_list.insertItem(row, self._cev_cond_item(dlg.result_cond))
            self._cev_save_or_group(ev, grp_idx)

    def _cev_or_cond_edit_selected(self) -> None:
        item = self._cev_or_list.currentItem()
        if item:
            self._cev_or_cond_edit(item)

    def _cev_or_cond_del(self) -> None:
        ev = self._cev_selected_event()
        grp_idx = self._cev_or_group_combo.currentData()
        if ev is None or grp_idx is None:
            return
        row = self._cev_or_list.currentRow()
        if row >= 0:
            self._cev_or_list.takeItem(row)
            self._cev_save_or_group(ev, grp_idx)

    def _cev_save_or_group(self, ev: dict, grp_idx: int) -> None:
        """Write the OR list widget into ev['or_groups'][grp_idx] and save."""
        groups = ev.setdefault("or_groups", [])
        while len(groups) <= grp_idx:
            groups.append([])
        conds: list[dict] = []
        for i in range(self._cev_or_list.count()):
            d = self._cev_or_list.item(i).data(Qt.ItemDataRole.UserRole)
            if isinstance(d, dict):
                conds.append(d)
        groups[grp_idx] = conds
        ev["or_groups"] = groups
        self._on_save()

    # -- public: called from project_tab when loading project data ---------

    def load_custom_events(self) -> None:
        """Reload the custom events tab from current project data."""
        if hasattr(self, "_cev_list"):
            self._cev_load_all()

    # ══════════════════════════════════════════════════════════════════════

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


# ---------------------------------------------------------------------------
# _TypeEventDialog — choose event + action + params for an entity type event
# ---------------------------------------------------------------------------

class _TypeEventDialog(QDialog):
    """Dialog to add or edit one action attached to an entity type event.

    Parameters
    ----------
    role        : entity role string (used to filter available events)
    project_data: full project dict (needed to populate scene_to combo)
    ev_name     : pre-selected event (edit mode)
    act         : pre-filled action dict (edit mode)
    parent      : parent QWidget
    """

    _VAR_ACTIONS = frozenset({
        "inc_variable", "dec_variable", "set_variable", "set_flag", "clear_flag",
    })
    _A0_A1_ACTIONS = frozenset({
        "move_entity_to", "add_resource", "remove_resource", "set_quest_stage",
    })
    _A0_ACTIONS = frozenset({
        "play_sfx", "start_bgm", "fade_bgm", "play_anim", "screen_shake",
        "add_score", "add_health", "set_health",
        "add_resource", "remove_resource",
        "spawn_entity", "show_entity", "hide_entity", "move_entity_to",
        "set_player_form", "set_checkpoint", "pause_entity_path", "resume_entity_path",
        "spawn_wave", "set_scroll_speed", "set_cam_target",
        "enable_trigger", "disable_trigger",
        "show_dialogue", "give_item", "remove_item", "unlock_door",
        "unlock_ability", "set_quest_stage", "play_cutscene", "set_gravity_dir",
    })
    _SCENE_ACTIONS = frozenset({"goto_scene", "warp_to"})

    def __init__(
        self,
        role: str,
        project_data: dict,
        *,
        ev_name: str | None = None,
        act: dict | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Action sur événement d'entité")
        self.setMinimumWidth(380)

        self.result_event:  str  = ev_name or "entity_death"
        self.result_action: dict = {}

        self._project_data = project_data if isinstance(project_data, dict) else {}

        # Available events for this role
        from core.entity_types import EVENTS_BY_ROLE, EVENT_IDS
        ev_keys = EVENTS_BY_ROLE.get(role) or EVENT_IDS
        _EV_LABELS = {
            "entity_death":         "Mort",
            "entity_collect":       "Collecte",
            "entity_activate":      "Activation",
            "entity_hit":           "Touché",
            "entity_spawn":         "Spawn",
            "entity_btn_a":         "Btn A pressé",
            "entity_btn_b":         "Btn B pressé",
            "entity_btn_opt":       "Option pressé",
            "entity_btn_up":        "Haut pressé",
            "entity_btn_down":      "Bas pressé",
            "entity_btn_left":      "Gauche pressé",
            "entity_btn_right":     "Droite pressé",
            "entity_player_enter":  "Joueur entre en zone",
            "entity_player_exit":   "Joueur quitte la zone",
            "entity_timer":         "Timer périodique",
            "entity_low_hp":        "HP bas (seuil)",
        }
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Event combo
        self._ev_combo = QComboBox()
        for k in ev_keys:
            self._ev_combo.addItem(_EV_LABELS.get(k, k), k)
        if ev_name and ev_name in ev_keys:
            self._ev_combo.setCurrentIndex(list(ev_keys).index(ev_name))
        form.addRow("Événement :", self._ev_combo)

        # Action combo — grouped with separators
        self._act_combo = QComboBox()
        for i, (grp_name, grp_keys) in enumerate(GlobalsTab._ACT_GROUPS):
            if i > 0:
                self._act_combo.insertSeparator(self._act_combo.count())
            for k in grp_keys:
                lbl = GlobalsTab._ACT_LABELS.get(k, k)
                self._act_combo.addItem(lbl, k)
        _make_searchable_combo(self._act_combo)
        pre_act = str(act.get("action", "emit_event")) if isinstance(act, dict) else "emit_event"
        idx = self._act_combo.findData(pre_act)
        if idx >= 0:
            self._act_combo.setCurrentIndex(idx)
        form.addRow("Action :", self._act_combo)

        layout.addLayout(form)

        # Dynamic params area
        self._params_widget = QWidget()
        self._params_form = QFormLayout(self._params_widget)
        self._params_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # flag_var_index row (for variable/flag actions)
        self._lbl_var = QLabel("Index variable / flag :")
        self._spin_var = QSpinBox()
        self._spin_var.setRange(0, 127)
        pre_var = int(act.get("flag_var_index", 0)) if isinstance(act, dict) else 0
        self._spin_var.setValue(pre_var)
        self._params_form.addRow(self._lbl_var, self._spin_var)

        # a1 row (value for set_variable)
        self._lbl_a1 = QLabel("Valeur :")
        self._spin_a1 = QSpinBox()
        self._spin_a1.setRange(0, 255)
        pre_a1 = int(act.get("a1", 0)) if isinstance(act, dict) else 0
        self._spin_a1.setValue(pre_a1)
        self._params_form.addRow(self._lbl_a1, self._spin_a1)

        # a0 row (numeric param for sfx/bgm/score/etc.)
        self._lbl_a0 = QLabel("ID :")
        self._spin_a0 = QSpinBox()
        self._spin_a0.setRange(0, 255)
        pre_a0 = int(act.get("a0", 0)) if isinstance(act, dict) else 0
        self._spin_a0.setValue(pre_a0)
        self._params_form.addRow(self._lbl_a0, self._spin_a0)

        # emit_event row — named custom event selector (replaces raw spinner)
        self._lbl_cev = QLabel("Événement :")
        self._cev_ev_combo = QComboBox()
        from core.custom_events import get_custom_events as _get_cevs
        _cevs = _get_cevs(self._project_data)
        if _cevs:
            for _i, _cev in enumerate(_cevs):
                _cname = str(_cev.get("name") or f"event_{_i}")
                self._cev_ev_combo.addItem(f"[{_i}] {_cname}", _i)
        else:
            self._cev_ev_combo.addItem("(aucun événement défini — voir Globals > Événements)", 0)
        _pre_cev = int(act.get("a0", 0)) if isinstance(act, dict) else 0
        _ci = self._cev_ev_combo.findData(_pre_cev)
        if _ci >= 0:
            self._cev_ev_combo.setCurrentIndex(_ci)
        self._params_form.addRow(self._lbl_cev, self._cev_ev_combo)

        # scene_to row (for goto_scene)
        self._lbl_scene = QLabel("Scène cible :")
        self._scene_combo = QComboBox()
        scenes = self._project_data.get("scenes") or []
        for sc in scenes:
            if isinstance(sc, dict):
                sid  = str(sc.get("id") or "")
                name = str(sc.get("name") or sid)
                if sid:
                    self._scene_combo.addItem(name, sid)
        pre_scene = str(act.get("scene_to", "")) if isinstance(act, dict) else ""
        sidx = self._scene_combo.findData(pre_scene)
        if sidx >= 0:
            self._scene_combo.setCurrentIndex(sidx)
        self._params_form.addRow(self._lbl_scene, self._scene_combo)

        layout.addWidget(self._params_widget)

        # Once checkbox
        self._chk_once = QCheckBox("Déclencher une seule fois par chargement de scène")
        pre_once = bool(act.get("once", False)) if isinstance(act, dict) else False
        self._chk_once.setChecked(pre_once)
        layout.addWidget(self._chk_once)

        # OK / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Wire action combo → refresh params visibility
        self._act_combo.currentIndexChanged.connect(self._refresh_params)
        self._refresh_params()

    # ------------------------------------------------------------------

    _A0_LABELS: dict[str, str] = {
        "play_sfx":           "ID SFX :",
        "start_bgm":          "ID BGM :",
        "fade_bgm":           "Volume cible :",
        "play_anim":          "ID animation :",
        "screen_shake":       "Intensité :",
        "add_score":          "Montant :",
        "add_health":         "Montant HP :",
        "set_health":         "Valeur HP :",
        "add_resource":       "Index ressource :",
        "remove_resource":    "Index ressource :",
        "spawn_entity":       "Type entité :",
        "show_entity":        "ID entité :",
        "hide_entity":        "ID entité :",
        "move_entity_to":     "X cible :",
        "set_player_form":    "Forme (0..N) :",
        "set_checkpoint":     "Index checkpoint :",
        "pause_entity_path":  "ID entité :",
        "resume_entity_path": "ID entité :",
        "spawn_wave":         "Index vague :",
        "set_scroll_speed":   "Vitesse (0..255) :",
        "set_cam_target":     "ID cible caméra :",
        "enable_trigger":     "Index trigger :",
        "disable_trigger":    "Index trigger :",
        "show_dialogue":      "ID dialogue :",
        "give_item":          "ID objet :",
        "remove_item":        "ID objet :",
        "unlock_door":        "ID porte :",
        "unlock_ability":     "ID capacité :",
        "set_quest_stage":    "Index quête :",
        "play_cutscene":      "ID cinématique :",
        "set_gravity_dir":    "Dir (0=bas,1=haut,2=gauche,3=droite) :",
    }
    _A1_LABELS: dict[str, str] = {
        "move_entity_to":  "Y cible :",
        "add_resource":    "Quantité :",
        "remove_resource": "Quantité :",
        "set_quest_stage": "Étape :",
        "set_variable":    "Valeur :",
    }
    _VAR_LABELS: dict[str, str] = {
        "inc_variable": "Index variable :",
        "dec_variable": "Index variable :",
        "set_variable": "Index variable :",
        "set_flag":     "Index flag :",
        "clear_flag":   "Index flag :",
    }

    def _refresh_params(self) -> None:
        act_key   = self._act_combo.currentData() or ""
        is_var    = act_key in self._VAR_ACTIONS
        is_emit   = (act_key == "emit_event")
        is_a0     = act_key in self._A0_ACTIONS and not is_emit
        is_scene  = act_key in self._SCENE_ACTIONS
        is_set    = (act_key == "set_variable")
        is_a0_a1  = act_key in self._A0_A1_ACTIONS

        self._lbl_var.setText(self._VAR_LABELS.get(act_key, "Index :"))
        self._lbl_a0.setText(self._A0_LABELS.get(act_key, "Valeur :"))
        self._lbl_a1.setText(self._A1_LABELS.get(act_key, "Valeur :"))

        self._lbl_var.setVisible(is_var)
        self._spin_var.setVisible(is_var)
        self._lbl_a1.setVisible(is_set or is_a0_a1)
        self._spin_a1.setVisible(is_set or is_a0_a1)
        self._lbl_a0.setVisible(is_a0)
        self._spin_a0.setVisible(is_a0)
        self._lbl_cev.setVisible(is_emit)
        self._cev_ev_combo.setVisible(is_emit)
        self._lbl_scene.setVisible(is_scene)
        self._scene_combo.setVisible(is_scene)

    def _on_accept(self) -> None:
        self.result_event = str(self._ev_combo.currentData() or "entity_death")
        act_key = str(self._act_combo.currentData() or "emit_event")
        d: dict = {"action": act_key, "once": self._chk_once.isChecked()}

        if act_key in self._VAR_ACTIONS:
            d["flag_var_index"] = int(self._spin_var.value())
            if act_key == "set_variable":
                d["a1"] = int(self._spin_a1.value())
        elif act_key == "emit_event":
            d["a0"] = int(self._cev_ev_combo.currentData() or 0)
        elif act_key in self._SCENE_ACTIONS:
            d["scene_to"] = str(self._scene_combo.currentData() or "")
        elif act_key in self._A0_A1_ACTIONS:
            d["a0"] = int(self._spin_a0.value())
            d["a1"] = int(self._spin_a1.value())
        elif act_key in self._A0_ACTIONS:
            d["a0"] = int(self._spin_a0.value())

        self.result_action = d
        self.accept()


# ---------------------------------------------------------------------------
# _CevActionDialog — action-only dialog for custom events (no event selector)
# ---------------------------------------------------------------------------

class _CevActionDialog(QDialog):
    """Dialog to add or edit one action for a custom event.

    Identical action vocabulary to _TypeEventDialog but without the event
    selector row — the event is already determined by which event is selected
    in the custom events list.
    """

    _VAR_ACTIONS = frozenset({
        "inc_variable", "dec_variable", "set_variable", "set_flag", "clear_flag",
    })
    _A0_A1_ACTIONS = frozenset({
        "move_entity_to", "add_resource", "remove_resource", "set_quest_stage",
    })
    _A0_ACTIONS = frozenset({
        "play_sfx", "start_bgm", "fade_bgm", "play_anim", "screen_shake",
        "add_score", "add_health", "set_health",
        "add_resource", "remove_resource",
        "spawn_entity", "show_entity", "hide_entity", "move_entity_to",
        "set_player_form", "set_checkpoint", "pause_entity_path", "resume_entity_path",
        "spawn_wave", "set_scroll_speed", "set_cam_target",
        "enable_trigger", "disable_trigger",
        "show_dialogue", "give_item", "remove_item", "unlock_door",
        "unlock_ability", "set_quest_stage", "play_cutscene", "set_gravity_dir",
    })
    _SCENE_ACTIONS = frozenset({"goto_scene", "warp_to"})
    _A0_LABELS: dict[str, str] = {
        "play_sfx":           "ID SFX :",
        "start_bgm":          "ID BGM :",
        "fade_bgm":           "Volume cible :",
        "play_anim":          "ID animation :",
        "screen_shake":       "Intensité :",
        "add_score":          "Montant :",
        "add_health":         "Montant HP :",
        "set_health":         "Valeur HP :",
        "add_resource":       "Index ressource :",
        "remove_resource":    "Index ressource :",
        "spawn_entity":       "Type entité :",
        "show_entity":        "ID entité :",
        "hide_entity":        "ID entité :",
        "move_entity_to":     "X cible :",
        "set_player_form":    "Forme (0..N) :",
        "set_checkpoint":     "Index checkpoint :",
        "pause_entity_path":  "ID entité :",
        "resume_entity_path": "ID entité :",
        "spawn_wave":         "Index vague :",
        "set_scroll_speed":   "Vitesse (0..255) :",
        "set_cam_target":     "ID cible caméra :",
        "enable_trigger":     "Index trigger :",
        "disable_trigger":    "Index trigger :",
        "show_dialogue":      "ID dialogue :",
        "give_item":          "ID objet :",
        "remove_item":        "ID objet :",
        "unlock_door":        "ID porte :",
        "unlock_ability":     "ID capacité :",
        "set_quest_stage":    "Index quête :",
        "play_cutscene":      "ID cinématique :",
        "set_gravity_dir":    "Dir (0=bas,1=haut,2=gauche,3=droite) :",
    }
    _A1_LABELS: dict[str, str] = {
        "move_entity_to":  "Y cible :",
        "add_resource":    "Quantité :",
        "remove_resource": "Quantité :",
        "set_quest_stage": "Étape :",
        "set_variable":    "Valeur :",
    }
    _VAR_LABELS: dict[str, str] = {
        "inc_variable": "Index variable :",
        "dec_variable": "Index variable :",
        "set_variable": "Index variable :",
        "set_flag":     "Index flag :",
        "clear_flag":   "Index flag :",
    }

    def __init__(
        self,
        project_data: dict,
        *,
        act: dict | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Action d'événement personnalisé")
        self.setMinimumWidth(380)
        self.result_action: dict = {}
        self._project_data = project_data if isinstance(project_data, dict) else {}

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Action combo — grouped with separators
        self._act_combo = QComboBox()
        for i, (grp_name, grp_keys) in enumerate(GlobalsTab._ACT_GROUPS):
            if i > 0:
                self._act_combo.insertSeparator(self._act_combo.count())
            for k in grp_keys:
                lbl = GlobalsTab._ACT_LABELS.get(k, k)
                self._act_combo.addItem(lbl, k)
        _make_searchable_combo(self._act_combo)
        pre_act = str(act.get("action", "emit_event")) if isinstance(act, dict) else "emit_event"
        idx = self._act_combo.findData(pre_act)
        if idx >= 0:
            self._act_combo.setCurrentIndex(idx)
        form.addRow("Action :", self._act_combo)
        layout.addLayout(form)

        # Dynamic params
        self._params_widget = QWidget()
        self._params_form = QFormLayout(self._params_widget)
        self._params_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._lbl_var = QLabel("Index variable :")
        self._spin_var = QSpinBox()
        self._spin_var.setRange(0, 127)
        self._spin_var.setValue(int(act.get("flag_var_index", 0)) if isinstance(act, dict) else 0)
        self._params_form.addRow(self._lbl_var, self._spin_var)

        self._lbl_a1 = QLabel("Valeur :")
        self._spin_a1 = QSpinBox()
        self._spin_a1.setRange(0, 255)
        self._spin_a1.setValue(int(act.get("a1", 0)) if isinstance(act, dict) else 0)
        self._params_form.addRow(self._lbl_a1, self._spin_a1)

        self._lbl_a0 = QLabel("ID :")
        self._spin_a0 = QSpinBox()
        self._spin_a0.setRange(0, 255)
        self._spin_a0.setValue(int(act.get("a0", 0)) if isinstance(act, dict) else 0)
        self._params_form.addRow(self._lbl_a0, self._spin_a0)

        # emit_event row — named custom event selector
        self._lbl_cev = QLabel("Événement :")
        self._cev_ev_combo = QComboBox()
        from core.custom_events import get_custom_events as _get_cevs2
        _cevs2 = _get_cevs2(self._project_data)
        if _cevs2:
            for _i, _cev in enumerate(_cevs2):
                _cname = str(_cev.get("name") or f"event_{_i}")
                self._cev_ev_combo.addItem(f"[{_i}] {_cname}", _i)
        else:
            self._cev_ev_combo.addItem("(aucun événement défini — voir Globals > Événements)", 0)
        _pre_cev2 = int(act.get("a0", 0)) if isinstance(act, dict) else 0
        _ci2 = self._cev_ev_combo.findData(_pre_cev2)
        if _ci2 >= 0:
            self._cev_ev_combo.setCurrentIndex(_ci2)
        self._params_form.addRow(self._lbl_cev, self._cev_ev_combo)

        self._lbl_scene = QLabel("Scène cible :")
        self._scene_combo = QComboBox()
        for sc in (self._project_data.get("scenes") or []):
            if isinstance(sc, dict):
                sid  = str(sc.get("id") or "")
                name = str(sc.get("name") or sid)
                if sid:
                    self._scene_combo.addItem(name, sid)
        pre_scene = str(act.get("scene_to", "")) if isinstance(act, dict) else ""
        sidx = self._scene_combo.findData(pre_scene)
        if sidx >= 0:
            self._scene_combo.setCurrentIndex(sidx)
        self._params_form.addRow(self._lbl_scene, self._scene_combo)

        layout.addWidget(self._params_widget)

        self._chk_once = QCheckBox("Déclencher une seule fois par chargement de scène")
        self._chk_once.setChecked(bool(act.get("once", False)) if isinstance(act, dict) else False)
        layout.addWidget(self._chk_once)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._act_combo.currentIndexChanged.connect(self._refresh_params)
        self._refresh_params()

    def _refresh_params(self) -> None:
        act_key   = self._act_combo.currentData() or ""
        is_var    = act_key in self._VAR_ACTIONS
        is_emit   = (act_key == "emit_event")
        is_a0     = act_key in self._A0_ACTIONS and not is_emit
        is_scene  = act_key in self._SCENE_ACTIONS
        is_set    = (act_key == "set_variable")
        is_a0_a1  = act_key in self._A0_A1_ACTIONS

        self._lbl_var.setText(self._VAR_LABELS.get(act_key, "Index :"))
        self._lbl_a0.setText(self._A0_LABELS.get(act_key, "Valeur :"))
        self._lbl_a1.setText(self._A1_LABELS.get(act_key, "Valeur :"))

        self._lbl_var.setVisible(is_var)
        self._spin_var.setVisible(is_var)
        self._lbl_a1.setVisible(is_set or is_a0_a1)
        self._spin_a1.setVisible(is_set or is_a0_a1)
        self._lbl_a0.setVisible(is_a0)
        self._spin_a0.setVisible(is_a0)
        self._lbl_cev.setVisible(is_emit)
        self._cev_ev_combo.setVisible(is_emit)
        self._lbl_scene.setVisible(is_scene)
        self._scene_combo.setVisible(is_scene)

    def _on_accept(self) -> None:
        act_key = str(self._act_combo.currentData() or "emit_event")
        d: dict = {"action": act_key, "once": self._chk_once.isChecked()}
        if act_key in self._VAR_ACTIONS:
            d["flag_var_index"] = int(self._spin_var.value())
            if act_key == "set_variable":
                d["a1"] = int(self._spin_a1.value())
        elif act_key == "emit_event":
            d["a0"] = int(self._cev_ev_combo.currentData() or 0)
        elif act_key in self._SCENE_ACTIONS:
            d["scene_to"] = str(self._scene_combo.currentData() or "")
        elif act_key in self._A0_A1_ACTIONS:
            d["a0"] = int(self._spin_a0.value())
            d["a1"] = int(self._spin_a1.value())
        elif act_key in self._A0_ACTIONS:
            d["a0"] = int(self._spin_a0.value())
        self.result_action = d
        self.accept()


# ---------------------------------------------------------------------------
# _CevCondDialog — condition guard dialog for custom events
# ---------------------------------------------------------------------------

class _CevCondDialog(QDialog):
    """Dialog to add or edit one guard condition for a custom event.

    Condition vocabulary is the full TRIG_COND_* set (same as scene triggers).
    Supports negate, index (flag/var/entity-type), and value (threshold).
    """

    # Groups: (label, [(key, display_label), ...])
    _COND_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
        ("Joueur — boutons", [
            ("btn_a",       "Btn A pressé"),
            ("btn_b",       "Btn B pressé"),
            ("btn_a_b",     "Btn A+B"),
            ("btn_up",      "Btn Haut"),
            ("btn_down",    "Btn Bas"),
            ("btn_left",    "Btn Gauche"),
            ("btn_right",   "Btn Droite"),
            ("btn_opt",     "Btn Option"),
            ("btn_held_ge", "Btn maintenu ≥ N frames"),
        ]),
        ("Joueur — état", [
            ("health_le",         "HP ≤ valeur"),
            ("health_ge",         "HP ≥ valeur"),
            ("health_eq",         "HP = valeur"),
            ("lives_le",          "Vies ≤ valeur"),
            ("lives_ge",          "Vies ≥ valeur"),
            ("on_jump",           "Au saut"),
            ("on_nth_jump",       "Au N-ième saut"),
            ("on_land",           "À l'atterrissage"),
            ("on_hurt",           "Touché"),
            ("on_death",          "Mort du joueur"),
            ("on_crouch",         "Accroupi"),
            ("on_dash",           "Au dash"),
            ("on_attack",         "À l'attaque"),
            ("on_pickup",         "Ramassage objet"),
            ("on_swim",           "En nage"),
            ("on_wall_left",      "Mur gauche"),
            ("on_wall_right",     "Mur droit"),
            ("on_ladder",         "Sur échelle"),
            ("on_ice",            "Sur glace"),
            ("on_conveyor",       "Sur tapis"),
            ("on_spring",         "Sur ressort"),
            ("force_jump",        "Saut forcé"),
            ("score_ge",          "Score ≥ valeur"),
            ("combo_ge",          "Combo ≥ valeur"),
            ("collectible_count_ge", "Collectibles ≥ valeur"),
            ("player_has_item",   "Joueur possède objet (index)"),
            ("ability_unlocked",  "Capacité débloquée (index)"),
        ]),
        ("Caméra / Scroll", [
            ("cam_x_ge",     "Caméra X ≥ valeur"),
            ("cam_y_ge",     "Caméra Y ≥ valeur"),
            ("enter_region", "Entrer région"),
            ("leave_region", "Quitter région"),
        ]),
        ("Timer / Vague", [
            ("timer_ge",       "Timer ≥ valeur"),
            ("timer_le",       "Timer ≤ valeur"),
            ("timer_every",    "Timer toutes N frames"),
            ("wave_ge",        "Vague ≥ valeur"),
            ("wave_cleared",   "Vague terminée"),
            ("lap_ge",         "Tour ≥ valeur"),
            ("scene_first_enter", "Première entrée scène"),
        ]),
        ("Flags / Variables", [
            ("flag_set",      "Flag activé (index)"),
            ("flag_clear",    "Flag désactivé (index)"),
            ("variable_ge",   "Variable ≥ valeur (index)"),
            ("variable_le",   "Variable ≤ valeur (index)"),
            ("variable_eq",   "Variable = valeur (index)"),
            ("variable_ne",   "Variable ≠ valeur (index)"),
        ]),
        ("Entités — globales", [
            ("enemy_count_le",  "Nb ennemis ≤ valeur"),
            ("enemy_count_ge",  "Nb ennemis ≥ valeur"),
            ("count_eq",        "Compteur = valeur"),
            ("entity_alive",    "Entité vivante (index)"),
            ("entity_dead",     "Entité morte (index)"),
            ("entity_in_region","Entité en région (index)"),
            ("entity_contact",  "Contact entité (index)"),
            ("all_switches_on", "Tous switches ON"),
            ("block_on_tile",   "Bloc sur tuile"),
        ]),
        ("Entités — par type", [
            ("entity_type_all_dead",       "Type : tous morts (type)"),
            ("entity_type_count_ge",       "Type : compte ≥ valeur (type)"),
            ("entity_type_collected",      "Type : collecté (type)"),
            ("entity_type_alive_le",       "Type : vivants ≤ valeur (type)"),
            ("entity_type_collected_ge",   "Type : collectés ≥ valeur (type)"),
            ("entity_type_all_collected",  "Type : tous collectés (type)"),
            ("entity_type_activated",      "Type : activé (type)"),
            ("entity_type_all_activated",  "Type : tous activés (type)"),
            ("entity_type_any_alive",      "Type : au moins un vivant (type)"),
            ("entity_type_btn_a",          "Type : Btn A (type)"),
            ("entity_type_btn_b",          "Type : Btn B (type)"),
            ("entity_type_btn_opt",        "Type : Option (type)"),
            ("entity_type_contact",        "Type : contact (type)"),
            ("entity_type_near_player",    "Type : près joueur (type)"),
            ("entity_type_hit",            "Type : touché (type)"),
            ("entity_type_hit_ge",         "Type : hits ≥ valeur (type)"),
            ("entity_type_spawned",        "Type : spawné (type)"),
            ("entity_type_spawned_ge",     "Type : spawnés ≥ valeur (type)"),
        ]),
        ("Quête / Narration", [
            ("quest_stage_eq",  "Étape quête = valeur (index)"),
            ("dialogue_done",   "Dialogue terminé (index)"),
            ("choice_result",   "Résultat choix (index)"),
            ("menu_result",     "Résultat menu (index)"),
            ("cutscene_done",   "Cinématique terminée (index)"),
            ("npc_talked_to",   "NPC parlé (index)"),
        ]),
        ("Ressources / Aléatoire", [
            ("resource_ge",  "Ressource ≥ valeur (index)"),
            ("chance",       "Chance % (valeur 0-100)"),
        ]),
    ]

    # Conditions that need an index spinner (flag/var/entity-type index)
    _INDEX_CONDS = frozenset({
        "flag_set", "flag_clear",
        "variable_ge", "variable_le", "variable_eq", "variable_ne",
        "entity_alive", "entity_dead", "entity_in_region", "entity_contact",
        "entity_type_all_dead", "entity_type_count_ge", "entity_type_collected",
        "entity_type_alive_le", "entity_type_collected_ge", "entity_type_all_collected",
        "entity_type_activated", "entity_type_all_activated", "entity_type_any_alive",
        "entity_type_btn_a", "entity_type_btn_b", "entity_type_btn_opt",
        "entity_type_contact", "entity_type_near_player", "entity_type_hit",
        "entity_type_hit_ge", "entity_type_spawned", "entity_type_spawned_ge",
        "quest_stage_eq", "dialogue_done", "choice_result", "menu_result",
        "cutscene_done", "npc_talked_to",
        "player_has_item", "ability_unlocked", "resource_ge",
    })
    # Conditions that need a value spinner (threshold / comparison)
    _VALUE_CONDS = frozenset({
        "cam_x_ge", "cam_y_ge", "timer_ge", "timer_le", "timer_every",
        "wave_ge", "lap_ge", "health_le", "health_ge", "health_eq",
        "lives_le", "lives_ge", "score_ge", "combo_ge", "collectible_count_ge",
        "on_nth_jump", "btn_held_ge",
        "variable_ge", "variable_le", "variable_eq", "variable_ne",
        "enemy_count_le", "enemy_count_ge", "count_eq",
        "entity_type_count_ge", "entity_type_alive_le", "entity_type_collected_ge",
        "entity_type_hit_ge", "entity_type_spawned_ge",
        "quest_stage_eq", "choice_result", "menu_result",
        "resource_ge", "chance",
    })
    _INDEX_LABELS: dict[str, str] = {
        "flag_set":     "Index flag :",
        "flag_clear":   "Index flag :",
        "variable_ge":  "Index variable :",
        "variable_le":  "Index variable :",
        "variable_eq":  "Index variable :",
        "variable_ne":  "Index variable :",
        "resource_ge":  "Index ressource :",
        "quest_stage_eq": "Index quête :",
        "dialogue_done":  "Index dialogue :",
        "choice_result":  "Index choix :",
        "menu_result":    "Index menu :",
        "cutscene_done":  "Index cinématique :",
        "npc_talked_to":  "Index NPC :",
        "player_has_item": "ID objet :",
        "ability_unlocked": "ID capacité :",
    }
    _VALUE_LABELS: dict[str, str] = {
        "cam_x_ge":     "X ≥ :",
        "cam_y_ge":     "Y ≥ :",
        "timer_ge":     "Timer ≥ :",
        "timer_le":     "Timer ≤ :",
        "timer_every":  "Toutes N frames :",
        "wave_ge":      "Vague ≥ :",
        "lap_ge":       "Tour ≥ :",
        "health_le":    "HP ≤ :",
        "health_ge":    "HP ≥ :",
        "health_eq":    "HP = :",
        "lives_le":     "Vies ≤ :",
        "lives_ge":     "Vies ≥ :",
        "score_ge":     "Score ≥ :",
        "combo_ge":     "Combo ≥ :",
        "on_nth_jump":  "Numéro saut :",
        "btn_held_ge":  "Frames maintenu ≥ :",
        "variable_ge":  "Valeur ≥ :",
        "variable_le":  "Valeur ≤ :",
        "variable_eq":  "Valeur = :",
        "variable_ne":  "Valeur ≠ :",
        "enemy_count_le": "Nb ennemis ≤ :",
        "enemy_count_ge": "Nb ennemis ≥ :",
        "count_eq":     "Compteur = :",
        "entity_type_count_ge":   "Compte ≥ :",
        "entity_type_alive_le":   "Vivants ≤ :",
        "entity_type_collected_ge": "Collectés ≥ :",
        "entity_type_hit_ge":     "Hits ≥ :",
        "entity_type_spawned_ge": "Spawnés ≥ :",
        "quest_stage_eq": "Étape = :",
        "choice_result":  "Résultat = :",
        "menu_result":    "Résultat = :",
        "resource_ge":    "Valeur ≥ :",
        "collectible_count_ge": "Nb ≥ :",
        "chance":         "Chance % :",
    }

    # Flat label lookup derived from _COND_GROUPS (key → display label)
    _COND_LABELS: dict[str, str] = {
        k: lbl
        for _, entries in [
            ("Joueur — boutons", [
                ("btn_a","Btn A pressé"),("btn_b","Btn B pressé"),("btn_a_b","Btn A+B"),
                ("btn_up","Btn Haut"),("btn_down","Btn Bas"),("btn_left","Btn Gauche"),
                ("btn_right","Btn Droite"),("btn_opt","Btn Option"),("btn_held_ge","Btn maintenu ≥ N frames"),
            ]),
            ("Joueur — état", [
                ("health_le","HP ≤"),("health_ge","HP ≥"),("health_eq","HP ="),
                ("lives_le","Vies ≤"),("lives_ge","Vies ≥"),
                ("on_jump","Au saut"),("on_nth_jump","Au N-ième saut"),
                ("on_land","À l'atterrissage"),("on_hurt","Touché"),("on_death","Mort du joueur"),
                ("on_crouch","Accroupi"),("on_dash","Au dash"),("on_attack","À l'attaque"),
                ("on_pickup","Ramassage objet"),("on_swim","En nage"),
                ("on_wall_left","Mur gauche"),("on_wall_right","Mur droit"),
                ("on_ladder","Sur échelle"),("on_ice","Sur glace"),
                ("on_conveyor","Sur tapis"),("on_spring","Sur ressort"),
                ("force_jump","Saut forcé"),("score_ge","Score ≥"),("combo_ge","Combo ≥"),
                ("collectible_count_ge","Collectibles ≥"),
                ("player_has_item","Joueur possède objet"),("ability_unlocked","Capacité débloquée"),
            ]),
            ("Caméra / Scroll", [
                ("cam_x_ge","Caméra X ≥"),("cam_y_ge","Caméra Y ≥"),
                ("enter_region","Entrer région"),("leave_region","Quitter région"),
            ]),
            ("Timer / Vague", [
                ("timer_ge","Timer ≥"),("timer_le","Timer ≤"),("timer_every","Timer toutes N frames"),
                ("wave_ge","Vague ≥"),("wave_cleared","Vague terminée"),
                ("lap_ge","Tour ≥"),("scene_first_enter","Première entrée scène"),
            ]),
            ("Flags / Variables", [
                ("flag_set","Flag activé"),("flag_clear","Flag désactivé"),
                ("variable_ge","Variable ≥"),("variable_le","Variable ≤"),
                ("variable_eq","Variable ="),("variable_ne","Variable ≠"),
            ]),
            ("Entités — globales", [
                ("enemy_count_le","Nb ennemis ≤"),("enemy_count_ge","Nb ennemis ≥"),
                ("count_eq","Compteur ="),("entity_alive","Entité vivante"),
                ("entity_dead","Entité morte"),("entity_in_region","Entité en région"),
                ("entity_contact","Contact entité"),("all_switches_on","Tous switches ON"),
                ("block_on_tile","Bloc sur tuile"),
            ]),
            ("Entités — par type", [
                ("entity_type_all_dead","Type : tous morts"),
                ("entity_type_count_ge","Type : compte ≥"),
                ("entity_type_collected","Type : collecté"),
                ("entity_type_alive_le","Type : vivants ≤"),
                ("entity_type_collected_ge","Type : collectés ≥"),
                ("entity_type_all_collected","Type : tous collectés"),
                ("entity_type_activated","Type : activé"),
                ("entity_type_all_activated","Type : tous activés"),
                ("entity_type_any_alive","Type : au moins un vivant"),
                ("entity_type_btn_a","Type : Btn A"),("entity_type_btn_b","Type : Btn B"),
                ("entity_type_btn_opt","Type : Option"),
                ("entity_type_contact","Type : contact"),
                ("entity_type_near_player","Type : près joueur"),
                ("entity_type_hit","Type : touché"),
                ("entity_type_hit_ge","Type : hits ≥"),
                ("entity_type_spawned","Type : spawné"),
                ("entity_type_spawned_ge","Type : spawnés ≥"),
            ]),
            ("Quête / Narration", [
                ("quest_stage_eq","Étape quête ="),("dialogue_done","Dialogue terminé"),
                ("choice_result","Résultat choix"),("menu_result","Résultat menu"),
                ("cutscene_done","Cinématique terminée"),("npc_talked_to","NPC parlé"),
            ]),
            ("Ressources / Aléatoire", [
                ("resource_ge","Ressource ≥"),("chance","Chance %"),
            ]),
        ]
        for k, lbl in entries
    }

    def __init__(
        self,
        _project_data: object = None,  # accepted but unused (compat with call sites)
        *,
        cond: dict | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Condition de garde")
        self.setMinimumWidth(380)
        self.result_cond: dict = {}

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Condition combo — grouped with separators, searchable by typing
        self._cond_combo = QComboBox()
        pre_cond_key = str(cond.get("cond", "flag_set")) if isinstance(cond, dict) else "flag_set"
        for i, (grp_name, entries) in enumerate(self._COND_GROUPS):
            if i > 0:
                self._cond_combo.insertSeparator(self._cond_combo.count())
            for key, lbl in entries:
                self._cond_combo.addItem(lbl, key)
        _make_searchable_combo(self._cond_combo)
        idx = self._cond_combo.findData(pre_cond_key)
        if idx >= 0:
            self._cond_combo.setCurrentIndex(idx)
        form.addRow("Condition :", self._cond_combo)

        # Negate checkbox
        self._chk_negate = QCheckBox("Inverser (NOT)")
        self._chk_negate.setChecked(bool(cond.get("negate", False)) if isinstance(cond, dict) else False)
        form.addRow("", self._chk_negate)

        layout.addLayout(form)

        # Dynamic params
        self._params_widget = QWidget()
        self._params_form = QFormLayout(self._params_widget)
        self._params_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._lbl_index = QLabel("Index :")
        self._spin_index = QSpinBox()
        self._spin_index.setRange(0, 255)
        self._spin_index.setValue(int(cond.get("index", 0)) if isinstance(cond, dict) else 0)
        self._params_form.addRow(self._lbl_index, self._spin_index)

        self._lbl_value = QLabel("Valeur :")
        self._spin_value = QSpinBox()
        self._spin_value.setRange(0, 65535)
        self._spin_value.setValue(int(cond.get("value", 0)) if isinstance(cond, dict) else 0)
        self._params_form.addRow(self._lbl_value, self._spin_value)

        layout.addWidget(self._params_widget)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._cond_combo.currentIndexChanged.connect(self._refresh_fields)
        self._refresh_fields()

    def _refresh_fields(self) -> None:
        key = self._cond_combo.currentData() or ""
        need_idx = key in self._INDEX_CONDS
        need_val = key in self._VALUE_CONDS
        self._lbl_index.setText(self._INDEX_LABELS.get(key, "Index :"))
        self._lbl_value.setText(self._VALUE_LABELS.get(key, "Valeur :"))
        self._lbl_index.setVisible(need_idx)
        self._spin_index.setVisible(need_idx)
        self._lbl_value.setVisible(need_val)
        self._spin_value.setVisible(need_val)

    def _on_accept(self) -> None:
        key = str(self._cond_combo.currentData() or "flag_set")
        d: dict = {
            "cond":   key,
            "index":  int(self._spin_index.value()) if key in self._INDEX_CONDS else 0,
            "value":  int(self._spin_value.value()) if key in self._VALUE_CONDS else 0,
            "negate": self._chk_negate.isChecked(),
        }
        self.result_cond = d
        self.accept()
