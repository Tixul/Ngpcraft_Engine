"""
ui/tabs/project_tab.py - Scene manager tab (Phase 2a).

Features:
- CRUD for scenes (create, rename, delete)
- Per-scene sprite list (file, frame size, frame count, tile estimate)
- Per-scene tilemap list
- Tile/palette budget per scene and globally
- Global export: All to PNG, All to .c, Palettes .c only
"""
from __future__ import annotations

import re
import subprocess
import sys as _sys
import tempfile
import uuid
import shutil
from pathlib import Path
from typing import Callable

from PIL import Image
from PyQt6.QtCore import Qt, QSettings, pyqtSignal, QProcess, QUrl
from PyQt6.QtGui import QColor, QTextDocument, QDesktopServices
from PyQt6.QtPrintSupport import QPrinter
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton,
    QSizePolicy, QSpinBox, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
    QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    QAbstractItemView,
)

from ui.tabs._project_path_mixin import ProjectPathMixin
from core.project_model import (
    TILE_MAX, PAL_MAX_SPR,
    sprite_tile_estimate, scene_tile_estimate, scene_pal_estimate,
    project_tile_estimate, project_pal_estimate,
    sprite_export_stats, analyze_scene_bg_palette_banks, analyze_scene_bg_palette_banks_exact,
)
from core.hitbox_export import make_hitbox_h, make_props_h, make_ctrl_h, make_anims_h
from core.collision_boxes import active_hurtboxes, box_enabled, first_bodybox, first_hurtbox, sprite_hurtboxes
from core.assets_autogen_mk import write_assets_autogen_mk
from core.audio_manifest import AudioManifest
from core.rgb444 import OPAQUE_BLACK, to_word
from core.report_html import build_report_html
from core.sprite_loader import load_sprite
from core.entity_roles import scene_role_map, sprite_gameplay_role, sprite_type_name
from core.scenes_autogen_gen import write_scenes_autogen
from core.scene_collision import scene_with_export_collision
from core.scene_level_gen import collect_scene_level_issues
from core.scene_presets import SCENE_PRESETS, apply_scene_preset
from core.export_validation import collect_export_pipeline_issues, validate_globals_consistency
from core.save_detection import project_has_save_triggers
from core.template_preflight import collect_template_2026_issues, format_template_2026_report
from core.template_integration import (
    _detect_features,
    compute_player_total_slots,
    detect_template_root,
    default_export_dir_rel,
    patch_makefile_for_autogen,
    resolve_project_audio_state,
    safe_ident,
    write_autorun_main_c,
)
from i18n.lang import tr 
from ui.asset_browser import AssetBrowserWidget
from ui.context_help import ContextHelpBox
from ui.export_options_dialog import ExportOptions, ExportOptionsDialog
from ui.build_dialog import BuildDialog
from ui.run_dialog import RunDialog
from ui.tool_finder import default_candidates, find_script, script_dialog_start_dir, remember_script_path 


# ---------------------------------------------------------------------------
# Collapsible panel for the right-splitter sections
# ---------------------------------------------------------------------------

_PANEL_HEADER_H = 26


class _CollapsiblePanel(QWidget):
    """Titled panel whose body can be collapsed/expanded by clicking the header."""

    def __init__(self, title: str, settings_key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings_key = settings_key
        self._expanded = True
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header bar
        self._header = QWidget()
        self._header.setFixedHeight(_PANEL_HEADER_H)
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.setStyleSheet("background: #2e3440; border-radius: 2px;")
        h_lay = QHBoxLayout(self._header)
        h_lay.setContentsMargins(6, 0, 6, 0)
        h_lay.setSpacing(4)
        self._arrow = QLabel("▼")
        self._arrow.setFixedWidth(14)
        self._arrow.setStyleSheet("color: #8899aa;")
        h_lay.addWidget(self._arrow)
        lbl = QLabel(title)
        lbl.setStyleSheet("font-weight: bold; color: #cdd6e0;")
        h_lay.addWidget(lbl, 1)
        self._header.mousePressEvent = lambda _e: self.toggle()
        outer.addWidget(self._header)

        # Body — Expanding so the splitter can resize it freely
        self._body = QWidget()
        self._body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(4, 4, 4, 4)
        self._body_layout.setSpacing(4)
        outer.addWidget(self._body, 1)

        # Restore persisted collapse state
        settings = QSettings("NGPCraft", "Engine")
        saved = settings.value(self._settings_key, True)
        if isinstance(saved, str):
            saved = saved.lower() != "false"
        if not saved:
            self._expanded = True  # toggle() inverts it
            self.toggle()

    def body_layout(self) -> QVBoxLayout:
        return self._body_layout

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._arrow.setText("▼" if self._expanded else "▶")
        if self._expanded:
            self.setMinimumHeight(_PANEL_HEADER_H + 60)
            self.setMaximumHeight(16777215)
        else:
            self.setMinimumHeight(_PANEL_HEADER_H)
            self.setMaximumHeight(_PANEL_HEADER_H)
        QSettings("NGPCraft", "Engine").setValue(self._settings_key, self._expanded)


# ---------------------------------------------------------------------------
# Drag&drop target: sprite list
# ---------------------------------------------------------------------------

SPR_COL_FILE = 0
SPR_COL_SIZE = 1
SPR_COL_FRAMES = 2
SPR_COL_TILES = 3
SPR_COL_EXPORT = 4

class _SpriteDropTree(QTreeWidget):
    """Sprite tree widget that accepts dropped image paths and folders."""

    def __init__(self, on_drop_paths, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_drop_paths = on_drop_paths
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        if not event.mimeData().hasUrls():
            super().dropEvent(event)
            return

        paths: list[Path] = []
        for url in event.mimeData().urls():
            p = Path(url.toLocalFile())
            if not p.exists():
                continue
            if p.is_dir():
                paths.append(p)
            elif p.is_file() and p.suffix.lower() in (".png", ".bmp", ".gif"):
                paths.append(p)

        if paths:
            self._on_drop_paths(paths)
            event.acceptProposedAction()
            return

        super().dropEvent(event)


# ---------------------------------------------------------------------------
# Helper: sprite configuration dialog
# ---------------------------------------------------------------------------

class _AddSpriteDialog(QDialog):
    """Dialog used to configure frame size/count for a single imported sprite."""

    def __init__(
        self,
        png_path: Path,
        parent: QWidget | None = None,
        initial_fw: int | None = None,
        initial_fh: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("proj.sprite_title"))
        try:
            img = Image.open(png_path)
            pw, ph = img.size
        except Exception:
            pw, ph = 8, 8
        self._png_h = ph

        form = QFormLayout(self)

        self._fw = QSpinBox()
        self._fw.setRange(1, pw)
        self._fw.setValue(initial_fw if initial_fw is not None else pw)
        self._fw.setSingleStep(8)
        form.addRow(tr("proj.frame_w_label"), self._fw)

        self._fh = QSpinBox()
        self._fh.setRange(1, ph)
        self._fh.setValue(initial_fh if initial_fh is not None else ph)
        self._fh.setSingleStep(8)
        form.addRow(tr("proj.frame_h_label"), self._fh)

        self._fc_label = QLabel()
        form.addRow(tr("proj.frame_count_label"), self._fc_label)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

        self._fw.valueChanged.connect(self._update_fc)
        self._fh.valueChanged.connect(self._update_fc)
        self._update_fc()

    def _update_fc(self) -> None:
        self._fc_label.setText(str(max(1, self._png_h // max(1, self._fh.value()))))

    @property
    def frame_w(self) -> int:
        return self._fw.value()

    @property
    def frame_h(self) -> int:
        return self._fh.value()

    @property
    def frame_count(self) -> int:
        return max(1, self._png_h // self.frame_h)


# ---------------------------------------------------------------------------
# Helper: batch sprite import dialog (shared frame_w/h)
# ---------------------------------------------------------------------------

class _BatchSpriteDialog(QDialog):
    """Dialog used to configure shared import settings for multiple sprites."""

    def __init__(self, sample_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("proj.batch_title"))
        try:
            img = Image.open(sample_path)
            pw, ph = img.size
        except Exception:
            pw, ph = 8, 8
        max_w = max(1024, pw)
        max_h = max(1024, ph)

        form = QFormLayout(self)

        self._auto_guess = QCheckBox(tr("proj.batch_auto_guess"))
        self._auto_guess.setChecked(False)
        self._auto_guess.toggled.connect(self._on_auto_toggled)
        form.addRow("", self._auto_guess)

        self._fw = QSpinBox()
        self._fw.setRange(1, max_w)
        self._fw.setValue(pw)
        self._fw.setSingleStep(8)
        form.addRow(tr("proj.batch_fw_label"), self._fw)

        self._fh = QSpinBox()
        self._fh.setRange(1, max_h)
        self._fh.setValue(ph)
        self._fh.setSingleStep(8)
        form.addRow(tr("proj.batch_fh_label"), self._fh)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

        self._on_auto_toggled(self._auto_guess.isChecked())

    def _on_auto_toggled(self, checked: bool) -> None:
        self._fw.setEnabled(not checked)
        self._fh.setEnabled(not checked)

    @property
    def frame_w(self) -> int:
        return self._fw.value()

    @property
    def frame_h(self) -> int:
        return self._fh.value()

    @property
    def auto_guess(self) -> bool:
        return self._auto_guess.isChecked()


# ---------------------------------------------------------------------------
# Hitbox / props header helper (used by batch export)
# ---------------------------------------------------------------------------

def _write_hitbox_props(
    spr: dict,
    name: str,
    fw: int,
    fh: int,
    fc: int,
    out_dir: Path,
    errs: list,
) -> None:
    """Write _hitbox.h and/or _props.h next to the sprite file if data is present."""
    hitboxes = sprite_hurtboxes(spr, fw, fh)
    if hitboxes:
        try:
            text = make_hitbox_h(name, name, fw, fh, fc, hitboxes)
            (out_dir / f"{name}_hitbox.h").write_text(text, encoding="utf-8")
        except Exception as e:
            errs.append(f"{name}_hitbox.h: {e}")

    props = spr.get("props") or {}
    if props:
        try:
            text = make_props_h(name, name, fw, fh, fc, props)
            if text:
                (out_dir / f"{name}_props.h").write_text(text, encoding="utf-8")
        except Exception as e:
            errs.append(f"{name}_props.h: {e}")


def _write_ctrl_header(
    spr: dict,
    name: str,
    out_dir: Path,
    errs: list,
) -> None:
    """Write _ctrl.h if role is set (independent of PNG export)."""
    ctrl = spr.get("ctrl") or {}
    role = sprite_gameplay_role(spr)
    if role != "player":
        return
    props = spr.get("props") or {}
    try:
        text = make_ctrl_h(name, name, ctrl, props, role=role)
        if text:
            (out_dir / f"{name}_ctrl.h").write_text(text, encoding="utf-8")
    except Exception as e:
        errs.append(f"{name}_ctrl.h: {e}")


def _write_anims_header(
    spr: dict,
    name: str,
    out_dir: Path,
    errs: list,
) -> None:
    """Auto-generate _anims.h when the sprite has animation states defined."""
    anims = spr.get("anims") or {}
    if not anims:
        return
    try:
        text = make_anims_h(name, name, anims)
        if text:
            (out_dir / f"{name}_anims.h").write_text(text, encoding="utf-8")
    except Exception as e:
        errs.append(f"{name}_anims.h: {e}")

# ---------------------------------------------------------------------------
# ProjectTab
# ---------------------------------------------------------------------------

class ProjectTab(ProjectPathMixin, QWidget):
    """
    Scene-based project manager.
    Emits scene_activated(dict | None) when the selected scene changes.
    Path helpers (_project_dir, _rel, _abs) come from ProjectPathMixin.
    """

    scene_activated = pyqtSignal(object)
    open_asset_in_palette = pyqtSignal(object)  # Path
    open_asset_in_tilemap = pyqtSignal(object)  # Path
    open_asset_in_editor = pyqtSignal(object)  # Path
    open_sprite_in_palette = pyqtSignal(object)  # dict payload
    open_sprite_in_hitbox = pyqtSignal(object)   # dict payload (sprite meta)
    open_scene_tab = pyqtSignal(str)

    def __init__(
        self,
        project_data: dict,
        project_path: Path | None,
        on_save: Callable,
        is_free_mode: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._data = project_data
        self._project_path = project_path
        self._on_save = on_save
        self._is_free_mode = is_free_mode
        self._spr_populating = False
        self._tm_populating = False
        self._last_scene = None
        self._audio_manifest: AudioManifest | None = None
        self._globals_tab = None  # injected by MainWindow after construction
        if not is_free_mode:
            self._data.setdefault("scenes", [])
            self._data.setdefault("game", {})
        self._build_ui()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _export_dir_abs(self) -> Path | None:
        """Project setting: optional directory where generated .c/.h are written."""
        rel = str(self._data.get("export_dir") or "").strip()
        if not rel:
            return None
        if self._project_dir:
            return self._project_dir / rel
        return Path(rel)

    def _export_out_dir_for_asset(self, asset_path: Path) -> Path:
        """Return output directory for generated code (defaults to next to the PNG)."""
        d = self._export_dir_abs()
        return d if d else Path(asset_path).parent

    def set_globals_tab(self, globals_tab) -> None:
        """Inject GlobalsTab reference so export functions can delegate to it."""
        self._globals_tab = globals_tab

    def set_audio_manifest(self, manifest) -> None:
        """Receive updated AudioManifest from GlobalsTab and refresh per-scene BGM combo."""
        self._audio_manifest = manifest
        self._populate_bgm_combo()

    def _maybe_write_assets_autogen_mk(self, export_dir: Path | None, errs: list[str]) -> Path | None:
        if not export_dir or not self._project_dir:
            return None
        try:
            _d = self._data or {}
            _has_save = project_has_save_triggers(_d)
            return write_assets_autogen_mk(self._project_dir, export_dir, has_save=_has_save)
        except Exception as e:
            errs.append(f"assets_autogen.mk: {e}")
            return None

    def _maybe_write_audio_autogen_mk(self, export_dir: Path | None, errs: list[str]) -> Path | None:
        _gt = self._globals_tab
        return _gt.write_audio_autogen_mk(export_dir, errs) if _gt else None

    def _maybe_write_sfx_autogen(self, export_dir: Path | None, errs: list[str]) -> tuple[Path | None, Path | None]:
        _gt = self._globals_tab
        return _gt.write_sfx_autogen(export_dir, errs) if _gt else (None, None)

    def _maybe_write_constants_h(self, export_dir: Path | None, errs: list[str]) -> Path | None:
        _gt = self._globals_tab
        return _gt.write_constants_h(export_dir, errs) if _gt else None

    def _maybe_write_game_vars_h(self, export_dir: Path | None, errs: list[str]) -> Path | None:
        _gt = self._globals_tab
        return _gt.write_game_vars_h(export_dir, errs) if _gt else None

    def _maybe_write_entity_types_h(self, export_dir: Path | None, errs: list[str]) -> Path | None:
        _gt = self._globals_tab
        return _gt.write_entity_types_h(export_dir, errs) if _gt else None

    def _run_globals_validation(self, errs: list[str]) -> None:
        """Append globals consistency warnings (C1/C2) to errs."""
        if isinstance(self._data, dict):
            validate_globals_consistency(project_data=self._data, errs=errs)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        def _make_action_group(title: str, buttons: list[QWidget]) -> QWidget:
            wrap = QWidget(self)
            lay = QVBoxLayout(wrap)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(3)
            lbl = QLabel(title)
            lbl.setStyleSheet("font-weight: bold; color: #777;")
            lay.addWidget(lbl)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            for btn in buttons:
                row.addWidget(btn)
            row.addStretch()
            lay.addLayout(row)
            return wrap

        def _make_action_group_grid(title: str, buttons: list[QWidget], cols: int = 2) -> QWidget:
            wrap = QWidget(self)
            lay = QVBoxLayout(wrap)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(3)
            lbl = QLabel(title)
            lbl.setStyleSheet("font-weight: bold; color: #777;")
            lay.addWidget(lbl)
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(4)
            for i, btn in enumerate(buttons):
                grid.addWidget(btn, i // cols, i % cols)
            lay.addLayout(grid)
            return wrap

        root = QVBoxLayout(self)
        root.setSpacing(6)

        if self._is_free_mode:
            lbl = QLabel(tr("proj.no_project"))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: gray; font-style: italic;")
            root.addWidget(lbl)
            return

        # GraphX dir row
        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel(tr("proj.graphx_dir")))
        self._graphx_label = QLabel(self._data.get("graphx_dir", ""))
        self._graphx_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        dir_row.addWidget(self._graphx_label, 1)
        btn_dir = QPushButton(tr("proj.change_dir"))
        btn_dir.clicked.connect(self._change_graphx_dir)
        dir_row.addWidget(btn_dir)
        root.addLayout(dir_row)

        # Export dir row (generated .c/.h)
        exp_row = QHBoxLayout()
        exp_row.addWidget(QLabel(tr("proj.export_dir")))
        self._export_dir_label = QLabel("")
        self._export_dir_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        exp_row.addWidget(self._export_dir_label, 1)
        btn_exp = QPushButton(tr("proj.change_export_dir"))
        btn_exp.setToolTip(tr("proj.export_dir_tt"))
        btn_exp.clicked.connect(self._change_export_dir)
        exp_row.addWidget(btn_exp)
        btn_exp_clr = QPushButton("✕")
        btn_exp_clr.setFixedWidth(28)
        btn_exp_clr.setToolTip(tr("proj.export_dir_auto"))
        btn_exp_clr.clicked.connect(self._clear_export_dir)
        exp_row.addWidget(btn_exp_clr)
        root.addLayout(exp_row)
        self._refresh_export_dir_ui()

        # Main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Left: scenes list ---
        left_w = QWidget()
        left_w.setMinimumWidth(140)
        left_w.setMaximumWidth(210)
        ll = QVBoxLayout(left_w)
        ll.setContentsMargins(0, 0, 4, 0)
        ll.setSpacing(4)
        ll.addWidget(QLabel(tr("proj.scenes_title")))

        self._scenes_list = QListWidget()
        self._scenes_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        try:
            self._scenes_list.model().rowsMoved.connect(self._on_scenes_reordered)  # type: ignore[attr-defined]
        except Exception:
            pass
        self._scenes_list.currentRowChanged.connect(self._on_scene_row_changed)
        ll.addWidget(self._scenes_list, 1)

        sb = QHBoxLayout()
        self._btn_new = QPushButton(tr("proj.new_scene"))
        self._btn_new.clicked.connect(self._add_scene)
        sb.addWidget(self._btn_new)
        self._btn_ren = QPushButton("✎")
        self._btn_ren.setFixedWidth(28)
        self._btn_ren.setToolTip(tr("proj.rename_scene"))
        self._btn_ren.clicked.connect(self._rename_scene)
        self._btn_ren.setEnabled(False)
        sb.addWidget(self._btn_ren)
        self._btn_del = QPushButton("✕")
        self._btn_del.setFixedWidth(28)
        self._btn_del.setToolTip(tr("proj.delete_scene"))
        self._btn_del.clicked.connect(self._delete_scene)
        self._btn_del.setEnabled(False)
        sb.addWidget(self._btn_del)
        ll.addLayout(sb)

        start_row = QHBoxLayout()
        start_row.addWidget(QLabel(tr("proj.start_scene")))
        self._cmb_start_scene = QComboBox()
        self._cmb_start_scene.currentIndexChanged.connect(self._on_start_scene_changed)
        start_row.addWidget(self._cmb_start_scene, 1)
        ll.addLayout(start_row)
        splitter.addWidget(left_w)

        # --- Right: scene detail ---
        right_w = QWidget()
        rl = QVBoxLayout(right_w)
        rl.setContentsMargins(4, 0, 0, 0)
        rl.setSpacing(6)

        self._scene_title = QLabel(tr("proj.no_scene_selected")) 
        self._scene_title.setStyleSheet("font-weight: bold;") 
        rl.addWidget(self._scene_title) 
        self._scene_status = QLabel("")
        self._scene_status.setWordWrap(True)
        self._scene_status.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        rl.addWidget(self._scene_status)
        self._btn_quick_palette = QPushButton(tr("proj.quick_palette"))
        self._btn_quick_palette.clicked.connect(lambda: self.open_scene_tab.emit("palette"))
        self._btn_quick_palette.setToolTip(tr("proj.quick_palette_tt"))
        self._btn_quick_tilemap = QPushButton(tr("proj.quick_tilemap"))
        self._btn_quick_tilemap.clicked.connect(lambda: self.open_scene_tab.emit("tilemap"))
        self._btn_quick_tilemap.setToolTip(tr("proj.quick_tilemap_tt"))
        self._btn_quick_level = QPushButton(tr("proj.quick_level"))
        self._btn_quick_level.clicked.connect(lambda: self.open_scene_tab.emit("level"))
        self._btn_quick_level.setToolTip(tr("proj.quick_level_tt"))
        self._btn_quick_hitbox = QPushButton(tr("proj.quick_hitbox"))
        self._btn_quick_hitbox.clicked.connect(lambda: self.open_scene_tab.emit("hitbox"))
        self._btn_quick_hitbox.setToolTip(tr("proj.quick_hitbox_tt"))
        self._btn_quick_export_dir = QPushButton(tr("proj.quick_export_dir"))
        self._btn_quick_export_dir.clicked.connect(self._open_export_dir)
        self._btn_quick_export_dir.setToolTip(tr("proj.quick_export_dir_tt"))

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel(tr("proj.scene_preset_label")))
        self._combo_scene_preset = QComboBox()
        for key, label_key in SCENE_PRESETS:
            self._combo_scene_preset.addItem(tr(label_key), key)
        self._combo_scene_preset.setToolTip(tr("proj.scene_preset_tt"))
        preset_row.addWidget(self._combo_scene_preset, 1)
        self._btn_apply_scene_preset = QPushButton(tr("proj.scene_preset_apply"))
        self._btn_apply_scene_preset.setToolTip(tr("proj.scene_preset_apply_tt"))
        self._btn_apply_scene_preset.clicked.connect(self._apply_scene_preset_clicked)
        preset_row.addWidget(self._btn_apply_scene_preset)
        rl.addLayout(preset_row)

        self._scene_preset_hint = QLabel(tr("proj.scene_preset_hint"))
        self._scene_preset_hint.setWordWrap(True)
        self._scene_preset_hint.setStyleSheet("color: #8fa4b8; font-size: 10px;")
        rl.addWidget(self._scene_preset_hint)

        self._ctx_project = ContextHelpBox(
            tr("proj.ctx_workflow_title"),
            tr("proj.ctx_workflow_body"),
            self,
        )
        rl.addWidget(self._ctx_project)

        # Asset browser (GraphX)
        self._asset_browser = AssetBrowserWidget(self)
        self._asset_browser.open_palette_requested.connect(self.open_asset_in_palette.emit)
        self._asset_browser.open_tilemap_requested.connect(self.open_asset_in_tilemap.emit)
        self._asset_browser.open_editor_requested.connect(self.open_asset_in_editor.emit)
        self._asset_browser.add_sprites_requested.connect(self._add_sprites_from_paths)
        self._asset_browser.add_tilemaps_requested.connect(self._add_tilemaps_from_paths)
        graphx_rel = self._data.get("graphx_dir", "GraphX")
        base = self._project_dir
        graphx_abs = (base / graphx_rel) if base else None
        self._asset_browser.set_root(graphx_abs)
        self._asset_browser.set_can_add(False)
        asset_panel = _CollapsiblePanel(tr("proj.asset_browser_group"), "panel/asset_browser", self)
        asset_panel.body_layout().setContentsMargins(0, 0, 0, 0)
        asset_panel.body_layout().addWidget(self._asset_browser)

        # Sprites
        spr_panel = _CollapsiblePanel(tr("proj.sprites_group"), "panel/sprites", self)
        spr_l = spr_panel.body_layout()
        self._spr_tree = _SpriteDropTree(self._import_sprites_from_paths) 
        self._spr_tree.setColumnCount(5) 
        self._spr_tree.setHeaderLabels([
            tr("proj.col_file"), tr("proj.col_size"),
            tr("proj.col_frames"), tr("proj.col_tiles"),
            tr("proj.col_export"),
        ])
        self._spr_tree.setAlternatingRowColors(True) 
        self._spr_tree.setToolTip(tr("proj.sprites_tooltip")) 
        self._spr_tree.itemDoubleClicked.connect(self._on_sprite_double_clicked) 
        self._spr_tree.itemSelectionChanged.connect(self._on_sprite_selection_changed)
        self._spr_tree.itemChanged.connect(self._on_sprite_item_changed)
        spr_l.addWidget(self._spr_tree) 
        spr_btns = QHBoxLayout() 
        self._btn_add_spr = QPushButton(tr("proj.add_sprite")) 
        self._btn_add_spr.clicked.connect(self._add_sprite) 
        self._btn_add_spr.setEnabled(False) 
        spr_btns.addWidget(self._btn_add_spr) 
        self._btn_import_dir = QPushButton(tr("proj.import_folder"))
        self._btn_import_dir.clicked.connect(self._import_sprite_folder)
        self._btn_import_dir.setEnabled(False)
        spr_btns.addWidget(self._btn_import_dir)
        self._btn_auto_share = QPushButton(tr("proj.auto_share"))
        self._btn_auto_share.clicked.connect(self._auto_share_palettes)
        self._btn_auto_share.setEnabled(False) 
        spr_btns.addWidget(self._btn_auto_share) 
        self._btn_open_in = QToolButton(self)
        self._btn_open_in.setText(tr("proj.open_in"))
        self._btn_open_in.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._btn_open_in.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._btn_open_in.setEnabled(False)
        open_menu = QMenu(self._btn_open_in)
        open_menu.addAction(tr("proj.open_palette"), self._open_selected_sprite_in_palette)
        open_menu.addAction(tr("proj.open_editor"), self._open_selected_sprite_in_editor)
        open_menu.addAction(tr("proj.open_hitbox"), self._open_selected_sprite_in_hitbox)
        self._btn_open_in.setMenu(open_menu)
        spr_btns.addWidget(self._btn_open_in)
        self._btn_rm_spr = QPushButton(tr("proj.remove_item")) 
        self._btn_rm_spr.clicked.connect(self._remove_sprite) 
        self._btn_rm_spr.setEnabled(False) 
        spr_btns.addWidget(self._btn_rm_spr) 
        spr_btns.addStretch() 
        spr_l.addLayout(spr_btns)

        # Tilemaps
        tm_panel = _CollapsiblePanel(tr("proj.tilemaps_group"), "panel/tilemaps", self)
        tm_l = tm_panel.body_layout()
        self._tm_list = QListWidget()
        self._tm_list.currentRowChanged.connect(self._on_tm_selection_changed)
        self._tm_list.itemChanged.connect(self._on_tm_item_changed)
        tm_l.addWidget(self._tm_list)
        tm_plane_row = QHBoxLayout()
        tm_plane_row.addWidget(QLabel(tr("tilemap.plane")))
        self._tm_plane_pick = QComboBox()
        self._tm_plane_pick.addItem(tr("tilemap.plane_auto"), "auto")
        self._tm_plane_pick.addItem(tr("tilemap.plane_scr1"), "scr1")
        self._tm_plane_pick.addItem(tr("tilemap.plane_scr2"), "scr2")
        self._tm_plane_pick.setToolTip(tr("tilemap.plane_tt"))
        self._tm_plane_pick.setEnabled(False)
        self._tm_plane_pick.currentIndexChanged.connect(self._on_tm_plane_changed)
        tm_plane_row.addWidget(self._tm_plane_pick, 1)
        tm_l.addLayout(tm_plane_row)
        tm_btns = QHBoxLayout()
        self._btn_add_tm = QPushButton(tr("proj.add_tilemap"))
        self._btn_add_tm.clicked.connect(self._add_tilemap)
        self._btn_add_tm.setEnabled(False)
        tm_btns.addWidget(self._btn_add_tm)
        self._btn_rm_tm = QPushButton(tr("proj.remove_item"))
        self._btn_rm_tm.clicked.connect(self._remove_tilemap)
        self._btn_rm_tm.setEnabled(False)
        tm_btns.addWidget(self._btn_rm_tm)
        tm_btns.addStretch()
        tm_l.addLayout(tm_btns)
        self._lbl_tm_palette_info = QLabel("")
        self._lbl_tm_palette_info.setWordWrap(True)
        self._lbl_tm_palette_info.setStyleSheet("color: #8ea0b3; font-size: 10px;")
        tm_l.addWidget(self._lbl_tm_palette_info)

        # Scene Audio (BGM per scene — project-level audio moved to GlobalsTab)
        scene_bgm_panel = _CollapsiblePanel(tr("proj.scene_audio_group"), "panel/scene_bgm", self)
        audio_l = scene_bgm_panel.body_layout()
        audio_l.setSpacing(4)
        self._audio_group = scene_bgm_panel

        audio_l.addWidget(QLabel(tr("proj.scene_bgm_tracks")))
        self._scene_bgm_list = QListWidget()
        self._scene_bgm_list.setMinimumHeight(92)
        self._scene_bgm_list.setToolTip(tr("proj.scene_bgm_tracks_tt"))
        self._scene_bgm_list.itemChanged.connect(self._on_scene_bgm_list_changed)
        audio_l.addWidget(self._scene_bgm_list, 1)

        bgm_opt = QHBoxLayout()
        self._chk_bgm_autostart = QCheckBox(tr("proj.bgm_autostart"))
        self._chk_bgm_autostart.toggled.connect(self._on_scene_bgm_opt_changed)
        bgm_opt.addWidget(self._chk_bgm_autostart)
        bgm_opt.addWidget(QLabel(tr("proj.scene_bgm")))
        self._cmb_scene_bgm = QComboBox()
        self._cmb_scene_bgm.currentIndexChanged.connect(self._on_scene_bgm_changed)
        bgm_opt.addWidget(self._cmb_scene_bgm, 1)
        bgm_opt.addSpacing(8)
        bgm_opt.addWidget(QLabel(tr("proj.bgm_fade_out")))
        self._spin_bgm_fade = QSpinBox()
        self._spin_bgm_fade.setRange(0, 60)
        self._spin_bgm_fade.setValue(0)
        self._spin_bgm_fade.setSuffix(" fr")
        self._spin_bgm_fade.setToolTip(tr("proj.bgm_fade_out_tt"))
        self._spin_bgm_fade.valueChanged.connect(self._on_scene_bgm_opt_changed)
        bgm_opt.addWidget(self._spin_bgm_fade)
        bgm_opt.addStretch()
        audio_l.addLayout(bgm_opt)

        # Per-scene controls (BGM choice/options) are toggled in _refresh_detail().
        self._set_scene_audio_controls_enabled(False)

        # Resizable splitter for the 4 right-panel sections (collapsible)
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_splitter.addWidget(asset_panel)
        right_splitter.addWidget(spr_panel)
        right_splitter.addWidget(tm_panel)
        right_splitter.addWidget(scene_bgm_panel)
        right_splitter.setStretchFactor(0, 1)
        right_splitter.setStretchFactor(1, 2)
        right_splitter.setStretchFactor(2, 1)
        right_splitter.setStretchFactor(3, 0)

        _rsettings = QSettings("NGPCraft", "Engine")
        _saved_sizes = _rsettings.value("project_tab/right_splitter_sizes")
        if _saved_sizes:
            try:
                right_splitter.restoreState(_saved_sizes)
            except Exception:
                pass
        right_splitter.splitterMoved.connect(
            lambda _pos, _idx, _s=right_splitter: QSettings("NGPCraft", "Engine").setValue(
                "project_tab/right_splitter_sizes", _s.saveState()
            )
        )
        rl.addWidget(right_splitter, 1)

        self._scene_budget = QLabel("")
        self._scene_budget.setWordWrap(True)

        self._btn_export_scene_png = QPushButton(tr("proj.export_scene_png"))
        self._btn_export_scene_png.clicked.connect(self._export_scene_png)
        self._btn_export_scene_png.setEnabled(False)

        self._btn_export_scene_c = QPushButton(tr("proj.export_scene_c"))
        self._btn_export_scene_c.clicked.connect(self._export_scene_c_ui)
        self._btn_export_scene_c.setEnabled(False)

        self._btn_export_scene_tmc = QPushButton(tr("proj.export_scene_tilemaps_c"))
        self._btn_export_scene_tmc.clicked.connect(self._export_scene_tilemaps_c)
        self._btn_export_scene_tmc.setEnabled(False)

        self._btn_batch_replace = QPushButton(tr("proj.batch_replace"))
        self._btn_batch_replace.clicked.connect(self._batch_color_replace)
        self._btn_batch_replace.setEnabled(False)

        rl.addStretch()

        # --- Panneau droit : quick actions + workflows + scene + validation + exports + build ---
        action_w = QWidget()
        action_w.setMinimumWidth(220)
        action_w.setMaximumWidth(340)
        al = QVBoxLayout(action_w)
        al.setContentsMargins(6, 0, 0, 0)
        al.setSpacing(6)

        al.addWidget(_make_action_group_grid(
            tr("proj.quick_actions"),
            [
                self._btn_quick_palette,
                self._btn_quick_tilemap,
                self._btn_quick_level,
                self._btn_quick_hitbox,
                self._btn_quick_export_dir,
            ],
            cols=2,
        ))

        al.addWidget(self._scene_budget)

        al.addWidget(_make_action_group_grid(
            tr("proj.actions_scene"),
            [
                self._btn_export_scene_png,
                self._btn_export_scene_c,
                self._btn_export_scene_tmc,
                self._btn_batch_replace,
            ],
            cols=2,
        ))

        _sep_val = QFrame()
        _sep_val.setFrameShape(QFrame.Shape.HLine)
        _sep_val.setStyleSheet("color: #444;")
        al.addWidget(_sep_val)

        validation_row = QHBoxLayout()
        self._project_validation = QLabel("")
        self._project_validation.setWordWrap(True)
        self._project_validation.setStyleSheet("color: #b8c0ca; font-size: 10px;")
        validation_row.addWidget(self._project_validation, 1)
        self._btn_project_first_issue = QPushButton(tr("proj.validation_first_issue"))
        self._btn_project_first_issue.setToolTip(tr("proj.validation_first_issue_tt"))
        self._btn_project_first_issue.clicked.connect(self._goto_first_scene_issue)
        self._btn_project_first_issue.setEnabled(False)
        validation_row.addWidget(self._btn_project_first_issue)
        self._btn_project_validation_details = QPushButton(tr("proj.validation_details"))
        self._btn_project_validation_details.setToolTip(tr("proj.validation_details_tt"))
        self._btn_project_validation_details.clicked.connect(self._show_project_validation_details)
        self._btn_project_validation_details.setEnabled(True)
        validation_row.addWidget(self._btn_project_validation_details)
        al.addLayout(validation_row)

        checklist_row = QHBoxLayout()
        self._project_checklist = QLabel("")
        self._project_checklist.setWordWrap(True)
        self._project_checklist.setTextFormat(Qt.TextFormat.RichText)
        self._project_checklist.setStyleSheet("color: #aeb7c1; font-size: 10px;")
        checklist_row.addWidget(self._project_checklist, 1)
        self._btn_project_next_step = QPushButton(tr("proj.validation_next_step"))
        self._btn_project_next_step.setToolTip(tr("proj.validation_next_step_tt"))
        self._btn_project_next_step.clicked.connect(self._run_project_next_step)
        self._btn_project_next_step.setEnabled(False)
        checklist_row.addWidget(self._btn_project_next_step)
        al.addLayout(checklist_row)

        template_row = QHBoxLayout()
        self._template_contract = QLabel("")
        self._template_contract.setWordWrap(True)
        self._template_contract.setStyleSheet("color: #b8c0ca; font-size: 10px;")
        template_row.addWidget(self._template_contract, 1)
        self._btn_template_contract = QPushButton(tr("proj.template_contract_details"))
        self._btn_template_contract.setToolTip(tr("proj.template_contract_details_tt"))
        self._btn_template_contract.clicked.connect(self._show_template_contract_details)
        self._btn_template_contract.setEnabled(False)
        template_row.addWidget(self._btn_template_contract)
        al.addLayout(template_row)

        _sep_act = QFrame()
        _sep_act.setFrameShape(QFrame.Shape.HLine)
        _sep_act.setStyleSheet("color: #444;")
        al.addWidget(_sep_act)

        self._btn_export_all_png = QPushButton(tr("proj.export_all_png"))
        self._btn_export_all_png.clicked.connect(self._export_all_png)
        self._btn_export_all_c = QPushButton(tr("proj.export_all_c"))
        self._btn_export_all_c.clicked.connect(self._export_all_c)
        self._btn_export_all_scenes_c = QPushButton(tr("proj.export_all_scenes_c"))
        self._btn_export_all_scenes_c.clicked.connect(self._export_all_scenes_c_ui)
        self._btn_export_template_ready = QPushButton(tr("proj.export_template_ready"))
        self._btn_export_template_ready.clicked.connect(self._export_template_ready)
        self._btn_export_template_ready.setToolTip(tr("proj.export_template_ready_tt"))
        self._btn_export_all_palettes_c = QPushButton(tr("proj.export_pals_c"))
        self._btn_export_all_palettes_c.clicked.connect(self._export_all_palettes_c)
        self._btn_report_html = QPushButton(tr("proj.report_html"))
        self._btn_report_html.clicked.connect(self._export_report_html)
        self._btn_report_pdf = QPushButton(tr("proj.report_pdf"))
        self._btn_report_pdf.clicked.connect(self._export_report_pdf)
        self._btn_build = QPushButton(tr("proj.build"))
        self._btn_build.clicked.connect(self._open_build_dialog)
        self._btn_build.setToolTip(tr("proj.build_tt"))
        self._btn_run = QPushButton(tr("proj.run"))
        self._btn_run.clicked.connect(self._run_emulator)
        self._btn_run.setToolTip(tr("proj.run_tt"))
        self._btn_run_cfg = QPushButton(tr("proj.run_cfg"))
        self._btn_run_cfg.clicked.connect(self._open_run_dialog)
        self._btn_run_cfg.setToolTip(tr("proj.run_cfg_tt"))
        al.addWidget(_make_action_group_grid(
            tr("proj.actions_exports"),
            [
                self._btn_export_all_png,
                self._btn_export_all_c,
                self._btn_export_all_scenes_c,
                self._btn_export_template_ready,
                self._btn_export_all_palettes_c,
            ],
            cols=2,
        ))
        al.addWidget(_make_action_group_grid(
            tr("proj.actions_reports"),
            [self._btn_report_html, self._btn_report_pdf],
            cols=2,
        ))
        al.addWidget(_make_action_group_grid(
            tr("proj.actions_build_run"),
            [self._btn_build, self._btn_run, self._btn_run_cfg],
            cols=3,
        ))
        self._btn_copy_starter_kit = QPushButton(tr("proj.copy_starter_kit"))
        self._btn_copy_starter_kit.clicked.connect(self._copy_starter_kit)
        self._btn_copy_starter_kit.setToolTip(tr("proj.copy_starter_kit_tt"))
        al.addWidget(_make_action_group_grid(
            tr("proj.actions_starter"),
            [self._btn_copy_starter_kit],
            cols=1,
        ))
        al.addStretch()
        self._btn_export_build_run = QPushButton(tr("proj.export_build_run"))
        self._btn_export_build_run.setToolTip(tr("proj.export_build_run_tt"))
        self._btn_export_build_run.setStyleSheet(
            "QPushButton { background-color: #c85a00; color: white; font-weight: bold; padding: 6px 4px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #e06800; }"
            "QPushButton:pressed { background-color: #a04800; }"
        )
        self._btn_export_build_run.clicked.connect(self._export_build_run)
        al.addWidget(self._btn_export_build_run)

        splitter.addWidget(right_w)
        splitter.addWidget(action_w)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        root.addWidget(splitter, 1)

        # Bottom bar — budget global uniquement
        bot = QVBoxLayout()
        bot.setSpacing(2)
        self._global_budget = QLabel("")
        self._global_budget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        bot.addWidget(self._global_budget)
        root.addLayout(bot)

        self._populate_scenes()
        scene = self._current_scene()
        self._combo_scene_preset.setEnabled(scene is not None)
        self._btn_apply_scene_preset.setEnabled(scene is not None)
        self._update_global_budget()


    # ------------------------------------------------------------------
    # Scenes populate / refresh
    # ------------------------------------------------------------------

    def _scene_status_info(self, scene: dict) -> tuple[str, list[str]]:
        blockers: list[str] = []
        warns: list[str] = []

        sprites = scene.get("sprites", []) or []
        tilemaps = scene.get("tilemaps", []) or []
        entities = scene.get("entities", []) or []
        waves = scene.get("waves", []) or []
        regions = scene.get("regions", []) or []
        triggers = scene.get("triggers", []) or []
        paths = scene.get("paths", []) or []
        roles = scene_role_map(scene)
        level_profile = str(scene.get("level_profile") or "").strip().lower()

        if not sprites and not tilemaps:
            blockers.append(tr("proj.scene_status_need_assets"))
        elif not sprites:
            warns.append(tr("proj.scene_status_no_sprites"))
        elif not tilemaps:
            warns.append(tr("proj.scene_status_no_tilemaps"))

        missing_hitbox = sum(
            1
            for spr in sprites
            if isinstance(spr, dict)
            and not active_hurtboxes(spr, int(spr.get("frame_w", 8) or 8), int(spr.get("frame_h", 8) or 8))
        )
        if missing_hitbox:
            warns.append(tr("proj.scene_status_missing_hitboxes", n=missing_hitbox))
        for spr in sprites:
            if not isinstance(spr, dict):
                continue
            ctrl = spr.get("ctrl", {}) or {}
            props = spr.get("props", {}) or {}
            spr_name = str(sprite_type_name(spr) or spr.get("name") or "sprite")
            gameplay_role = sprite_gameplay_role(spr, roles.get(sprite_type_name(spr)))
            ctrl_role = str(ctrl.get("role", "none") or "none").strip().lower()
            if gameplay_role == "player" and ctrl_role != "player":
                warns.append(tr("proj.scene_status_player_ctrl_missing", name=spr_name))
            elif gameplay_role != "player" and ctrl_role == "player":
                warns.append(tr("proj.scene_status_ctrl_player_mismatch", name=spr_name, role=gameplay_role))
            if gameplay_role != "player":
                continue
            try:
                move_type = int(props.get("move_type", 0) or 0)
                can_jump = int(props.get("can_jump", 0) or 0)
                jump_force = int(props.get("jump_force", 0) or 0)
            except Exception:
                continue
            if level_profile == "platformer" and move_type != 2:
                warns.append(tr("proj.scene_status_platformer_move_type", name=spr_name, move_type=move_type))
            if move_type == 2 and ((can_jump != 0 and jump_force <= 0) or (can_jump == 0 and jump_force > 0)):
                gravity = int(props.get("gravity", 0) or 0)
                warns.append(
                    f"{spr_name}: "
                    f"{tr('hitbox.jump_summary_disabled', jump=jump_force, gravity=gravity)}"
                )

        player_types = {str(t) for t, role in roles.items() if str(role).strip().lower() == "player"}
        if player_types:
            has_player = any(str(e.get("type", "")) in player_types for e in entities if isinstance(e, dict))
            if not has_player:
                for wave in waves:
                    for ent in (wave.get("entities", []) or []):
                        if isinstance(ent, dict) and str(ent.get("type", "")) in player_types:
                            has_player = True
                            break
                    if has_player:
                        break
            if not has_player:
                blockers.append(tr("proj.scene_status_missing_player"))

        map_mode = str(scene.get("map_mode", "none") or "none")
        col_map = scene.get("col_map")
        _sz = scene.get("level_size", {}) or {}
        map_w = int(_sz.get("w", scene.get("map_w", scene.get("grid_w", 20))) or 20)
        map_h = int(_sz.get("h", scene.get("map_h", scene.get("grid_h", 19))) or 19)
        if map_mode != "none":
            if not isinstance(col_map, list):
                blockers.append(tr("proj.scene_status_missing_colmap"))
            elif len(col_map) != map_h or any(not isinstance(r, list) or len(r) != map_w for r in col_map):
                blockers.append(tr("proj.scene_status_bad_colmap", w=map_w, h=map_h))

        region_ids = {str(r.get("id", "") or "").strip() for r in regions if isinstance(r, dict)}
        path_ids = {str(p.get("id", "") or "").strip() for p in paths if isinstance(p, dict)}
        trigger_ids = {str(t.get("id", "") or "").strip() for t in triggers if isinstance(t, dict)}
        entity_ids = {str(e.get("id", "") or "").strip() for e in entities if isinstance(e, dict)}

        if any(
            int(reg.get("x", 0)) < 0
            or int(reg.get("y", 0)) < 0
            or int(reg.get("x", 0)) + max(1, int(reg.get("w", 1))) > map_w
            or int(reg.get("y", 0)) + max(1, int(reg.get("h", 1))) > map_h
            for reg in regions if isinstance(reg, dict)
        ):
            blockers.append(tr("proj.scene_status_bad_regions"))

        bad_paths = False
        for path in paths:
            if not isinstance(path, dict):
                continue
            pts = path.get("points", []) or []
            if len(pts) < 2:
                bad_paths = True
                break
            if any(
                int(pt.get("x", 0)) < 0
                or int(pt.get("y", 0)) < 0
                or int(pt.get("x", 0)) >= map_w
                or int(pt.get("y", 0)) >= map_h
                for pt in pts if isinstance(pt, dict)
            ):
                bad_paths = True
                break
        if bad_paths:
            blockers.append(tr("proj.scene_status_bad_paths"))

        if any(
            isinstance(ent, dict)
            and str(ent.get("path_id", "") or "").strip()
            and str(ent.get("path_id", "") or "").strip() not in path_ids
            for ent in entities
        ):
            blockers.append(tr("proj.scene_status_bad_entity_paths"))

        bad_triggers = False
        for trig in triggers:
            if not isinstance(trig, dict):
                continue
            cond = str(trig.get("cond", "") or "")
            action = str(trig.get("action", "") or "")
            rid = str(trig.get("region_id", "") or "").strip()
            if cond in ("enter_region", "leave_region") and rid and rid not in region_ids:
                bad_triggers = True
                break
            target_id = str(trig.get("target_id", "") or "").strip()
            if action in ("enable_trigger", "disable_trigger") and target_id and target_id not in trigger_ids:
                bad_triggers = True
                break
            ent_target = str(trig.get("entity_target_id", "") or "").strip()
            if action in ("show_entity", "hide_entity", "move_entity_to") and ent_target and ent_target not in entity_ids:
                bad_triggers = True
                break
        if bad_triggers:
            blockers.append(tr("proj.scene_status_bad_triggers"))

        if not str(self._data.get("export_dir") or "").strip():
            warns.append(tr("proj.scene_status_missing_export_dir"))

        if blockers:
            return "incomplete", blockers + warns
        if warns:
            return "warning", warns
        return "ready", [tr("proj.scene_status_ready_tip")]

    def _scene_status_visuals(self, status: str) -> tuple[str, QColor, str]:
        if status == "ready":
            return (
                str(tr("proj.scene_status_ready_short")),
                QColor(110, 200, 120),
                str(tr("proj.scene_status_ready")),
            )
        if status == "warning":
            return (
                str(tr("proj.scene_status_warning_short")),
                QColor(230, 180, 70),
                str(tr("proj.scene_status_warning")),
            )
        return (
            str(tr("proj.scene_status_incomplete_short")),
            QColor(225, 110, 110),
            str(tr("proj.scene_status_incomplete")),
        )

    def _apply_scene_status_item(self, item: QListWidgetItem, scene: dict, idx: int) -> None:
        label = str(scene.get("label", "?") or "?")
        status, reasons = self._scene_status_info(scene)
        tag, color, status_label = self._scene_status_visuals(status)
        item.setText(f"[{idx}] {tag} {label}")
        item.setForeground(color)
        tip = "<br>".join(f"• {r}" for r in reasons)
        item.setToolTip(f"<b>{status_label}</b><br>{tip}")
        item.setData(Qt.ItemDataRole.UserRole, scene)
        item.setData(Qt.ItemDataRole.UserRole + 1, status)

    def _populate_scenes(self) -> None:
        current = self._current_scene()
        current_id = str((current or {}).get("id") or "").strip() if isinstance(current, dict) else ""
        current_label = str((current or {}).get("label") or "").strip() if isinstance(current, dict) else ""
        restore_row = -1
        self._scenes_list.blockSignals(True)
        self._scenes_list.clear()
        for i, s in enumerate(self._data.get("scenes", [])):
            item = QListWidgetItem("")
            self._apply_scene_status_item(item, s, i)
            self._scenes_list.addItem(item)
            sid = str(s.get("id") or "").strip() if isinstance(s, dict) else ""
            label = str(s.get("label") or "").strip() if isinstance(s, dict) else ""
            if restore_row < 0 and ((current_id and sid == current_id) or (current_label and label == current_label)):
                restore_row = i
        self._scenes_list.blockSignals(False)
        self._populate_start_scene_combo()
        count = self._scenes_list.count()
        if count > 0:
            if restore_row < 0:
                restore_row = 0
            self._scenes_list.setCurrentRow(restore_row)
        else:
            self._last_scene = None
            self._refresh_detail(None)
            self._btn_ren.setEnabled(False)
            self._btn_del.setEnabled(False)
            self._btn_import_dir.setEnabled(False)
            self._btn_auto_share.setEnabled(False)
            self._btn_rm_spr.setEnabled(False)
            self._btn_rm_tm.setEnabled(False)
            self.scene_activated.emit(None)

    def _refresh_scene_statuses(self) -> None:
        if not hasattr(self, "_scenes_list"):
            return
        row = self._scenes_list.currentRow()
        self._scenes_list.blockSignals(True)
        try:
            for i in range(self._scenes_list.count()):
                item = self._scenes_list.item(i)
                if item is None:
                    continue
                scene = self._canonical_scene_ref(item.data(Qt.ItemDataRole.UserRole))
                if isinstance(scene, dict):
                    self._apply_scene_status_item(item, scene, i)
        finally:
            self._scenes_list.blockSignals(False)
        if row >= 0:
            self._scenes_list.setCurrentRow(row)

    def _goto_first_scene_issue(self) -> None:
        for wanted in ("incomplete", "warning"):
            for i in range(self._scenes_list.count()):
                item = self._scenes_list.item(i)
                if item is not None and str(item.data(Qt.ItemDataRole.UserRole + 1) or "") == wanted:
                    self._scenes_list.setCurrentRow(i)
                    return

    def _goto_scene_by_label(self, scene_label: str) -> bool:
        wanted = str(scene_label or "").strip()
        if not wanted:
            return False
        for i in range(self._scenes_list.count()):
            item = self._scenes_list.item(i)
            scene = self._canonical_scene_ref(item.data(Qt.ItemDataRole.UserRole) if item is not None else None)
            if isinstance(scene, dict) and str(scene.get("label") or "").strip() == wanted:
                self._scenes_list.setCurrentRow(i)
                return True
        return False

    def _collect_project_validation_details(self) -> list[dict[str, str]]:
        issues: list[dict[str, str]] = []

        def _add(
            severity: str,
            scope: str,
            message: str,
            scene_label: str = "",
            action: str = "",
        ) -> None:
            issues.append(
                {
                    "severity": str(severity or "warn"),
                    "scope": str(scope or tr("proj.validation_scope_project")),
                    "scene": str(scene_label or "").strip(),
                    "message": str(message or "").strip(),
                    "action": str(action or "").strip(),
                }
            )

        scenes = [s for s in (self._data.get("scenes", []) if isinstance(self._data, dict) else []) if isinstance(s, dict)]
        if not scenes:
            _add("bad", tr("proj.validation_scope_project"), tr("proj.validation_no_scenes"), action="add_scene")
            return issues

        game = self._data.get("game", {}) if isinstance(self._data, dict) else {}
        start_label = str(game.get("start_scene") or "").strip() if isinstance(game, dict) else ""
        labels = {str(s.get("label", "") or "").strip() for s in scenes}
        if not start_label or start_label not in labels:
            _add("bad", tr("proj.validation_scope_project"), tr("proj.validation_bad_start_scene"), action="set_start")
        if not str(self._data.get("export_dir") or "").strip():
            _add("warn", tr("proj.validation_scope_project"), tr("proj.validation_missing_export_dir"), action="set_export_dir_auto")

        tpl_status, tpl_summary, _tpl_details = self._template_contract_check()
        if tpl_status in ("warn", "bad"):
            _add(
                "bad" if tpl_status == "bad" else "warn",
                tr("proj.validation_scope_template"),
                tpl_summary,
                action="template_details",
            )
        if self._project_dir:
            tpl = detect_template_root(project_dir=self._project_dir, project_data=self._data)
            if tpl is not None:
                _tool_warns, _tool_details, tool_issues = self._toolchain_contract_check(tpl)
                for msg in tool_issues:
                    _add("warn", tr("proj.validation_scope_toolchain"), msg, action="build_dialog")

        for scene in scenes:
            scene_label = str(scene.get("label") or "").strip() or "?"
            status, reasons = self._scene_status_info(scene)
            if status in ("warning", "incomplete"):
                sev = "bad" if status == "incomplete" else "warn"
                for reason in reasons:
                    _add(sev, tr("proj.validation_scope_scene"), reason, scene_label, action="open_scene")

            for bucket_name, assets, asset_type in (
                ("sprites", scene.get("sprites", []) or [], tr("proj.validation_scope_sprite")),
                ("tilemaps", scene.get("tilemaps", []) or [], tr("proj.validation_scope_tilemap")),
            ):
                for asset in assets:
                    if not isinstance(asset, dict):
                        continue
                    rel = str(asset.get("file") or "").strip()
                    if not rel:
                        continue
                    abs_p = self._abs(rel)
                    if abs_p is None or not abs_p.exists():
                        _add("bad", asset_type, tr("proj.validation_missing_asset", path=rel), scene_label, action="open_scene")

            for msg in collect_scene_level_issues(project_data=self._data, scene=scene):
                _add("bad", tr("proj.validation_scope_level"), msg, scene_label, action="open_scene")

        if self._project_dir and isinstance(self._data, dict):
            try:
                pf_issues = collect_template_2026_issues(project_dir=self._project_dir, project_data=self._data)
            except Exception:
                pf_issues = []
            for issue in pf_issues:
                scene_label = str(getattr(issue, "scene_label", "") or "").strip()
                asset_label = str(getattr(issue, "asset_label", "") or "").strip()
                msg = str(getattr(issue, "message", "") or "").strip()
                body = f"{asset_label}: {msg}" if asset_label else msg
                _add("bad", tr("proj.validation_scope_export"), body, scene_label, action="export_ready")
            try:
                export_issues = collect_export_pipeline_issues(project_dir=self._project_dir, project_data=self._data)
            except Exception:
                export_issues = []
            for issue in export_issues:
                scene_label = str(getattr(issue, "scene_label", "") or "").strip()
                asset_label = str(getattr(issue, "asset_label", "") or "").strip()
                msg = str(getattr(issue, "message", "") or "").strip()
                sev = str(getattr(issue, "severity", "") or "warn")
                body = f"{asset_label}: {msg}" if asset_label else msg
                action = "open_scene" if scene_label else "export_ready"
                if "export_dir" in msg:
                    action = "set_export_dir_auto"
                elif "autogen" in msg.lower() or "generated" in msg.lower() or "re-run" in msg.lower():
                    action = "export_ready"
                _add("bad" if sev == "bad" else "warn", tr("proj.validation_scope_export"), body, scene_label, action=action)

        return issues

    def _show_project_validation_details(self) -> None:
        issues = self._collect_project_validation_details()
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("proj.validation_details_title"))
        dlg.resize(900, 420)
        lay = QVBoxLayout(dlg)

        bad_count = sum(1 for it in issues if str(it.get("severity") or "") == "bad")
        warn_count = sum(1 for it in issues if str(it.get("severity") or "") == "warn")
        head = QLabel(
            tr(
                "proj.validation_details_summary",
                total=len(issues),
                bad=bad_count,
                warn=warn_count,
            ) if issues else tr("proj.validation_details_none")
        )
        head.setWordWrap(True)
        lay.addWidget(head)

        tree = QTreeWidget()
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.setHeaderLabels(
            [
                tr("proj.validation_col_severity"),
                tr("proj.validation_col_scope"),
                tr("proj.validation_col_scene"),
                tr("proj.validation_col_message"),
            ]
        )
        for entry in issues:
            sev = str(entry.get("severity") or "warn")
            sev_label = tr("proj.validation_severity_bad") if sev == "bad" else tr("proj.validation_severity_warn")
            row = QTreeWidgetItem(
                [
                    sev_label,
                    str(entry.get("scope") or ""),
                    str(entry.get("scene") or ""),
                    str(entry.get("message") or ""),
                ]
            )
            row.setData(0, Qt.ItemDataRole.UserRole, str(entry.get("scene") or ""))
            row.setData(1, Qt.ItemDataRole.UserRole, str(entry.get("action") or ""))
            color = QColor(225, 110, 110) if sev == "bad" else QColor(230, 180, 70)
            row.setForeground(0, color)
            row.setForeground(1, color)
            tree.addTopLevelItem(row)
        tree.resizeColumnToContents(0)
        tree.resizeColumnToContents(1)
        tree.resizeColumnToContents(2)
        lay.addWidget(tree, 1)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=dlg)
        btn_open = btns.addButton(tr("proj.validation_open_scene"), QDialogButtonBox.ButtonRole.ActionRole)
        btn_open.setEnabled(False)
        btn_fix = btns.addButton(tr("proj.validation_apply_action"), QDialogButtonBox.ButtonRole.ActionRole)
        btn_fix.setEnabled(False)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        lay.addWidget(btns)

        def _open_current() -> None:
            item = tree.currentItem()
            if item is None:
                return
            scene_label = str(item.data(0, Qt.ItemDataRole.UserRole) or "").strip()
            if not scene_label:
                return
            if self._goto_scene_by_label(scene_label):
                dlg.accept()

        def _update_actions() -> None:
            item = tree.currentItem()
            scene_label = str(item.data(0, Qt.ItemDataRole.UserRole) or "").strip() if item else ""
            action = str(item.data(1, Qt.ItemDataRole.UserRole) or "").strip() if item else ""
            btn_open.setEnabled(bool(scene_label))
            label = self._validation_issue_action_label(action)
            btn_fix.setText(label or tr("proj.validation_apply_action"))
            btn_fix.setEnabled(bool(action))

        def _apply_current() -> None:
            item = tree.currentItem()
            if item is None:
                return
            scene_label = str(item.data(0, Qt.ItemDataRole.UserRole) or "").strip()
            action = str(item.data(1, Qt.ItemDataRole.UserRole) or "").strip()
            if not action:
                return
            self._run_validation_issue_action(action, scene_label)
            dlg.accept()

        tree.itemSelectionChanged.connect(_update_actions)
        tree.itemDoubleClicked.connect(lambda _item, _col: _open_current())
        btn_open.clicked.connect(_open_current)
        btn_fix.clicked.connect(_apply_current)
        _update_actions()

        dlg.exec()

    def _validation_issue_action_label(self, action: str) -> str:
        action = str(action or "").strip()
        if action == "add_scene":
            return tr("proj.validation_next_add_scene")
        if action == "set_start":
            return tr("proj.validation_next_set_start")
        if action == "set_export_dir_auto":
            return tr("proj.validation_apply_export_default")
        if action == "set_export_dir":
            return tr("proj.validation_next_set_export")
        if action == "open_scene":
            return tr("proj.validation_open_scene")
        if action == "build_dialog":
            return tr("build.title")
        if action == "template_details":
            return tr("proj.validation_next_template")
        if action == "export_ready":
            return tr("proj.validation_next_export")
        return ""

    def _run_validation_issue_action(self, action: str, scene_label: str = "") -> None:
        action = str(action or "").strip()
        if action == "add_scene":
            self._add_scene()
            return
        if action == "set_start":
            if hasattr(self, "_cmb_start_scene") and self._cmb_start_scene.count() > 0:
                self._cmb_start_scene.setCurrentIndex(0)
                self._cmb_start_scene.setFocus(Qt.FocusReason.OtherFocusReason)
                # Force-save: setCurrentIndex(0) does not fire currentIndexChanged
                # when the combo is already at 0 (e.g. populate fixed a stale
                # label but blockSignals prevented saving it).
                self._on_start_scene_changed(0)
            return
        if action == "set_export_dir_auto":
            self._apply_default_export_dir()
            return
        if action == "set_export_dir":
            self._change_export_dir()
            return
        if action == "open_scene":
            if scene_label:
                self._goto_scene_by_label(scene_label)
            return
        if action == "build_dialog":
            self._open_build_dialog()
            return
        if action == "template_details":
            self._show_template_contract_details()
            return
        if action == "export_ready":
            self.focus_template_ready_workflow()
            self._btn_export_template_ready.setFocus(Qt.FocusReason.OtherFocusReason)
            return

    def _apply_default_export_dir(self) -> None:
        if not isinstance(self._data, dict):
            return
        self._data["export_dir"] = default_export_dir_rel(self._data)
        self._refresh_export_dir_ui()
        self._on_save()

    def _update_project_validation(self) -> None:
        scenes = [s for s in (self._data.get("scenes", []) if isinstance(self._data, dict) else []) if isinstance(s, dict)]
        counts = {"ready": 0, "warning": 0, "incomplete": 0}
        first_issue = False
        for scene in scenes:
            status, _reasons = self._scene_status_info(scene)
            counts[status] = counts.get(status, 0) + 1
            if status in ("incomplete", "warning"):
                first_issue = True

        issues: list[str] = []
        if not scenes:
            issues.append(tr("proj.validation_no_scenes"))
        game = self._data.get("game", {}) if isinstance(self._data, dict) else {}
        start_label = str(game.get("start_scene") or "").strip() if isinstance(game, dict) else ""
        labels = {str(s.get("label", "") or "").strip() for s in scenes}
        if scenes and (not start_label or start_label not in labels):
            issues.append(tr("proj.validation_bad_start_scene"))
        if not str(self._data.get("export_dir") or "").strip():
            issues.append(tr("proj.validation_missing_export_dir"))

        summary = tr(
            "proj.validation_summary",
            ready=int(counts.get("ready", 0)),
            warning=int(counts.get("warning", 0)),
            incomplete=int(counts.get("incomplete", 0)),
        )
        if issues:
            summary = summary + "<br><span style='color:#f0b44c;'>" + " | ".join(issues) + "</span>"
        else:
            summary = summary + "<br><span style='color:#75d17f;'>" + tr("proj.validation_ok") + "</span>"
        bg_summary = self._project_bg_palette_reuse_summary()
        if bg_summary and bg_summary != tr("proj.budget_global_bg_none"):
            summary = summary + "<br><span style='color:#8ec8ff;'>" + tr("proj.validation_bg_reuse", detail=bg_summary) + "</span>"
        self._project_validation.setText(summary)
        self._btn_project_first_issue.setEnabled(bool(first_issue))
        self._update_project_checklist()

    def _template_contract_check(self) -> tuple[str, str, list[str]]:
        if not self._project_dir or not isinstance(self._data, dict):
            return "warn", tr("proj.template_contract_no_project"), []

        tpl = detect_template_root(project_dir=self._project_dir, project_data=self._data)
        if tpl is None:
            return "warn", tr("proj.template_contract_root_missing"), []

        details: list[str] = [tr("proj.template_contract_root", path=str(tpl))]
        warns = 0
        errors = 0

        mk = tpl / "makefile"
        if not mk.exists():
            mk = tpl / "Makefile"
        if mk.exists():
            details.append(tr("proj.template_contract_makefile_ok"))
            try:
                mk_txt = mk.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                mk_txt = ""
            if ("OBJS" not in mk_txt) and ("SRCS" not in mk_txt):
                warns += 1
                details.append(tr("proj.template_contract_patch_warn"))
            else:
                details.append(tr("proj.template_contract_patch_ok"))
        else:
            errors += 1
            details.append(tr("proj.template_contract_makefile_missing"))

        if (tpl / "src" / "main.c").exists():
            details.append(tr("proj.template_contract_main_ok"))
        else:
            errors += 1
            details.append(tr("proj.template_contract_main_missing"))

        tool_sprite = tpl / "tools" / "ngpc_sprite_export.py"
        tool_tilemap = tpl / "tools" / "ngpc_tilemap.py"
        missing_tools: list[str] = []
        if not tool_sprite.exists():
            missing_tools.append("ngpc_sprite_export.py")
        if not tool_tilemap.exists():
            missing_tools.append("ngpc_tilemap.py")
        if missing_tools:
            warns += 1
            details.append(tr("proj.template_contract_tools_missing", names=", ".join(missing_tools)))
        else:
            details.append(tr("proj.template_contract_tools_ok"))

        header_candidates = (
            tpl / "src" / "gfx" / "ngpc_metasprite.h",
            tpl / "src" / "ngpc_metasprite.h",
            tpl / "include" / "ngpc_metasprite.h",
            tpl / "headers" / "ngpc_metasprite.h",
        )
        metasprite_header = next((p for p in header_candidates if p.exists()), None)
        if metasprite_header is None:
            errors += 1
            details.append(tr("proj.template_contract_metasprite_missing"))
        else:
            details.append(tr("proj.template_contract_metasprite_ok", path=str(metasprite_header)))

        far_candidates = (
            tpl / "src" / "gfx" / "ngpc_gfx.h",
            tpl / "src" / "fx" / "ngpc_dma.h",
            tpl / "src" / "ngpc_gfx.h",
            tpl / "include" / "ngpc_gfx.h",
        )
        far_define_found = False
        for cand in far_candidates:
            if not cand.exists():
                continue
            try:
                txt = cand.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                txt = ""
            if "#define NGP_FAR" in txt:
                far_define_found = True
                details.append(tr("proj.template_contract_ngp_far_ok", path=str(cand)))
                break
        if not far_define_found:
            warns += 1
            details.append(tr("proj.template_contract_ngp_far_missing"))

        # Fine header: ngpc_types.h (u8/u16/s16)
        types_candidates = (
            tpl / "src" / "core" / "ngpc_types.h",
            tpl / "src" / "ngpc_types.h",
            tpl / "include" / "ngpc_types.h",
        )
        if any(p.exists() for p in types_candidates):
            details.append(tr("proj.template_contract_types_ok"))
        else:
            warns += 1
            details.append(tr("proj.template_contract_types_missing"))

        # Audio contract
        audio_data = self._data.get("audio") if isinstance(self._data, dict) else None
        man_rel = str((audio_data or {}).get("manifest") or "").strip()
        has_audio_manifest = False
        if man_rel:
            man_path = Path(man_rel)
            if not man_path.is_absolute() and self._project_dir:
                man_path = self._project_dir / man_path
            if man_path.exists():
                has_audio_manifest = True
                details.append(tr("proj.template_contract_audio_manifest_ok"))
            else:
                warns += 1
                details.append(tr("proj.template_contract_audio_manifest_missing", path=man_rel))
        sfx_count = int((self._data or {}).get("sfx_count") or 0) if isinstance(self._data, dict) else 0
        if sfx_count > 0 or has_audio_manifest:
            sounds_h = tpl / "src" / "audio" / "sounds.h"
            sounds_c = tpl / "src" / "audio" / "sounds.c"
            if sounds_h.exists() and sounds_c.exists():
                details.append(tr("proj.template_contract_audio_runtime_ok"))
            elif sounds_h.exists() or sounds_c.exists():
                details.append(tr("proj.template_contract_audio_runtime_partial"))
            else:
                warns += 1
                details.append(tr("proj.template_contract_audio_runtime_missing"))

        tool_warns, tool_details, _tool_issues = self._toolchain_contract_check(tpl)
        warns += tool_warns
        details.extend(tool_details)

        if errors > 0:
            summary = tr("proj.template_contract_summary_bad", n=errors, path=str(tpl))
            return "bad", summary, details
        if warns > 0:
            summary = tr("proj.template_contract_summary_warn", n=warns, path=str(tpl))
            return "warn", summary, details
        summary = tr("proj.template_contract_summary_ok", path=str(tpl))
        return "ok", summary, details

    def _toolchain_contract_check(self, tpl: Path) -> tuple[int, list[str], list[str]]:
        """Return warn-count, detailed lines, and warning-only lines for build toolchain checks."""
        warns = 0
        details: list[str] = []
        issues: list[str] = []

        build_bat = tpl / "build.bat"
        compiler_path = ""
        if build_bat.exists():
            try:
                build_bat_text = build_bat.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                build_bat_text = ""
            for raw_line in build_bat_text.splitlines():
                line = raw_line.strip()
                if not line.lower().startswith("set compilerpath="):
                    continue
                compiler_path = line.split("=", 1)[1].strip().strip('"')
                break
            if compiler_path:
                cp = Path(compiler_path)
                cand = (
                    cp / "BIN" / "cc900.exe",
                    cp / "bin" / "cc900.exe",
                    cp / "cc900.exe",
                )
                cc900_path = next((p for p in cand if p.exists()), None)
                if cc900_path is not None:
                    details.append(tr("proj.template_contract_compiler_path_ok", path=str(cc900_path)))
                else:
                    warns += 1
                    msg = tr("proj.template_contract_compiler_path_missing", path=compiler_path)
                    details.append(msg)
                    issues.append(msg)
            else:
                warns += 1
                msg = tr("proj.template_contract_compiler_path_empty")
                details.append(msg)
                issues.append(msg)
        else:
            warns += 1
            msg = tr("proj.template_contract_build_bat_missing")
            details.append(msg)
            issues.append(msg)

        local_helpers = ("asm900.exe", "thc1.exe", "thc2.exe")
        missing_helpers = [name for name in local_helpers if not (tpl / name).exists()]
        if missing_helpers:
            warns += 1
            msg = tr("proj.template_contract_local_helpers_missing", names=", ".join(missing_helpers))
            details.append(msg)
            issues.append(msg)
        else:
            details.append(tr("proj.template_contract_local_helpers_ok"))

        path_cmds = ("cc900", "tulink", "tuconv", "s242ngp")
        found_path_cmds = [name for name in path_cmds if shutil.which(name)]
        missing_path_cmds = [name for name in path_cmds if name not in found_path_cmds]
        if missing_path_cmds:
            warns += 1
            msg = tr("proj.template_contract_path_tools_missing", names=", ".join(missing_path_cmds))
            details.append(msg)
            issues.append(msg)
        else:
            details.append(tr("proj.template_contract_path_tools_ok"))

        return warns, details, issues

    def _update_template_contract(self) -> None:
        status, summary, details = self._template_contract_check()
        color = {"ok": "#75d17f", "warn": "#f0b44c", "bad": "#e26d6d"}.get(status, "#b8c0ca")
        self._template_contract.setText(
            f"<span style='color:{color}; font-weight:600;'>{tr('proj.template_contract_title')}</span> — {summary}"
        )
        self._template_contract.setToolTip("<br>".join(details))
        self._btn_template_contract.setEnabled(bool(details))
        self._btn_template_contract.setProperty("contract_details", details)
        self._update_project_checklist()

    def _show_template_contract_details(self) -> None:
        details = self._btn_template_contract.property("contract_details") or []
        if not details:
            return
        body = "\n".join(f"- {line}" for line in details)
        QMessageBox.information(
            self,
            tr("proj.template_contract_title"),
            tr("proj.template_contract_dialog", details=body),
        )

    def _project_check_item_html(self, status: str, title: str, detail: str) -> str:
        tag, color = {
            "ok": ("OK", "#75d17f"),
            "warn": ("!", "#f0b44c"),
            "bad": ("KO", "#e26d6d"),
            "skip": ("-", "#7f8a96"),
        }.get(status, ("?", "#b8c0ca"))
        body = f"<b>{title}</b>"
        if detail:
            body += f" : {detail}"
        return f"<span style='color:{color}; font-weight:600;'>[{tag}]</span> {body}"

    def _project_next_step_info(self) -> tuple[str, str]:
        scenes = [s for s in (self._data.get("scenes", []) if isinstance(self._data, dict) else []) if isinstance(s, dict)]
        if not scenes:
            return "add_scene", tr("proj.validation_next_add_scene")
        game = self._data.get("game", {}) if isinstance(self._data, dict) else {}
        start_label = str(game.get("start_scene") or "").strip() if isinstance(game, dict) else ""
        labels = [str(s.get("label", "") or "").strip() for s in scenes]
        if not start_label or start_label not in set(labels):
            return "set_start", tr("proj.validation_next_set_start")
        if not str(self._data.get("export_dir") or "").strip():
            return "set_export_dir_auto", tr("proj.validation_apply_export_default")
        for scene in scenes:
            status, _reasons = self._scene_status_info(scene)
            if status in ("incomplete", "warning"):
                return "open_scene_issue", tr("proj.validation_next_open_scene")
        tpl_status, _summary, details = self._template_contract_check()
        if tpl_status in ("warn", "bad") and details:
            return "template_details", tr("proj.validation_next_template")
        return "export_ready", tr("proj.validation_next_export")

    def _update_project_checklist(self) -> None:
        if not hasattr(self, "_project_checklist"):
            return
        scenes = [s for s in (self._data.get("scenes", []) if isinstance(self._data, dict) else []) if isinstance(s, dict)]
        counts = {"ready": 0, "warning": 0, "incomplete": 0}
        for scene in scenes:
            status, _reasons = self._scene_status_info(scene)
            counts[status] = counts.get(status, 0) + 1

        game = self._data.get("game", {}) if isinstance(self._data, dict) else {}
        start_label = str(game.get("start_scene") or "").strip() if isinstance(game, dict) else ""
        labels = {str(s.get("label", "") or "").strip() for s in scenes}
        tpl_status, _tpl_summary, tpl_details = self._template_contract_check()
        export_dir = str(self._data.get("export_dir") or "").strip()

        rows = [
            self._project_check_item_html(
                "ok" if scenes else "bad",
                tr("proj.validation_check_scenes"),
                tr("proj.validation_check_scenes_ok", n=len(scenes)) if scenes else tr("proj.validation_check_scenes_bad"),
            ),
            self._project_check_item_html(
                "ok" if (scenes and start_label and start_label in labels) else ("bad" if scenes else "skip"),
                tr("proj.validation_check_start"),
                start_label if (start_label and start_label in labels) else (
                    tr("proj.validation_check_not_set") if scenes else tr("proj.validation_check_not_applicable")
                ),
            ),
            self._project_check_item_html(
                "ok" if export_dir else "warn",
                tr("proj.validation_check_export"),
                export_dir or tr("proj.validation_check_auto_needed"),
            ),
            self._project_check_item_html(
                "ok" if counts.get("incomplete", 0) == 0 and counts.get("warning", 0) == 0 else (
                    "bad" if counts.get("incomplete", 0) > 0 else "warn"
                ),
                tr("proj.validation_check_scenes_state"),
                tr(
                    "proj.validation_check_scenes_state_detail",
                    ready=int(counts.get("ready", 0)),
                    warning=int(counts.get("warning", 0)),
                    incomplete=int(counts.get("incomplete", 0)),
                ) if scenes else tr("proj.validation_check_not_applicable"),
            ),
            self._project_check_item_html(
                tpl_status,
                tr("proj.validation_check_template"),
                tpl_details[0] if tpl_details else tr("proj.validation_check_not_detected"),
            ),
        ]
        self._project_checklist.setText("<br>".join(rows))

        action, label = self._project_next_step_info()
        self._btn_project_next_step.setText(label)
        self._btn_project_next_step.setEnabled(bool(action))
        self._btn_project_next_step.setProperty("next_action", action)

    def _run_project_next_step(self) -> None:
        action = str(self._btn_project_next_step.property("next_action") or "").strip()
        if action == "add_scene":
            self._add_scene()
            return
        if action == "set_start":
            if hasattr(self, "_cmb_start_scene") and self._cmb_start_scene.count() > 0:
                self._cmb_start_scene.setCurrentIndex(0)
                self._cmb_start_scene.setFocus(Qt.FocusReason.OtherFocusReason)
                self._on_start_scene_changed(0)
            return
        if action in ("set_export_dir_auto", "set_export_dir"):
            self._apply_default_export_dir()
            return
        if action == "open_scene_issue":
            self._goto_first_scene_issue()
            return
        if action == "template_details":
            self._show_template_contract_details()
            return
        if action == "export_ready":
            self._btn_export_template_ready.setFocus(Qt.FocusReason.OtherFocusReason)
            return

    def _apply_scene_preset_clicked(self) -> None:
        scene = self._current_scene()
        if not isinstance(scene, dict):
            return
        preset_key = str(self._combo_scene_preset.currentData() or "").strip()
        if not preset_key:
            return
        if not apply_scene_preset(scene, preset_key):
            return
        self._on_save()
        self._refresh_detail(scene)
        self._refresh_scene_statuses()
        self._update_global_budget()
        self.scene_activated.emit(scene)
        hint_key = f"proj.scene_preset_hint_{preset_key}"
        self._scene_preset_hint.setText(tr(hint_key))

    def _populate_start_scene_combo(self) -> None:
        game = self._data.setdefault("game", {}) if isinstance(self._data, dict) else {}
        start_label = str(game.get("start_scene") or "").strip() if isinstance(game, dict) else ""

        self._cmb_start_scene.blockSignals(True)
        self._cmb_start_scene.clear()

        scenes = self._data.get("scenes", []) if isinstance(self._data, dict) else []
        labels: list[str] = []
        for s in scenes:
            if not isinstance(s, dict):
                continue
            label = str(s.get("label", "?")).strip()
            labels.append(label)
            self._cmb_start_scene.addItem(label, label)

        changed = False
        if labels and start_label not in labels:
            current = self._current_scene()
            current_label = str((current or {}).get("label") or "").strip() if isinstance(current, dict) else ""
            start_label = current_label if current_label in labels else labels[0]
            if isinstance(game, dict):
                game["start_scene"] = start_label
                changed = True

        idx = self._cmb_start_scene.findData(start_label) if start_label else 0
        self._cmb_start_scene.setCurrentIndex(idx if idx >= 0 else 0)
        self._cmb_start_scene.blockSignals(False)
        if changed and self._on_save:
            self._on_save()

    def _on_start_scene_changed(self, _idx: int) -> None:
        if not isinstance(self._data, dict):
            return
        label = str(self._cmb_start_scene.currentData() or "").strip()
        self._data.setdefault("game", {})
        try:
            self._data["game"]["start_scene"] = label
        except Exception:
            pass
        self._on_save()

    def _refresh_detail(self, scene: dict | None) -> None: 
        if scene is None: 
            self._scene_title.setText(tr("proj.no_scene_selected")) 
            self._scene_status.setText("")
            self._spr_tree.clear() 
            self._tm_list.clear() 
            self._scene_budget.setText("")
            if hasattr(self, "_lbl_tm_palette_info"):
                self._lbl_tm_palette_info.setText("")
            self._set_scene_audio_controls_enabled(False)
            for b in (self._btn_add_spr, self._btn_import_dir, self._btn_auto_share, self._btn_rm_spr,
                      self._btn_add_tm, self._btn_rm_tm,
                      self._btn_export_scene_png, self._btn_export_scene_c, self._btn_export_scene_tmc,
                      self._btn_batch_replace):
                b.setEnabled(False)
            for b in (
                getattr(self, "_btn_quick_palette", None),
                getattr(self, "_btn_quick_tilemap", None),
                getattr(self, "_btn_quick_level", None),
                getattr(self, "_btn_quick_hitbox", None),
            ):
                if b is not None:
                    b.setEnabled(False)
            if hasattr(self, "_btn_quick_export_dir"):
                self._btn_quick_export_dir.setEnabled(self._export_dir_abs() is not None)
            self._combo_scene_preset.setEnabled(False)
            self._btn_apply_scene_preset.setEnabled(False)
            self._set_sprite_open_actions_enabled(False)
            if hasattr(self, "_asset_browser"):
                self._asset_browser.set_can_add(False)
            return

        self._scene_title.setText(tr("proj.scene_content", name=scene.get("label", "?"))) 
        status, reasons = self._scene_status_info(scene)
        _tag, color, status_label = self._scene_status_visuals(status)
        color_hex = color.name()
        body = " • ".join(reasons[:3])
        self._scene_status.setText(
            f"<span style='color:{color_hex}; font-weight:600;'>{status_label}</span>"
            + (f" — {body}" if body else "")
        )
        self._btn_add_spr.setEnabled(True) 
        self._btn_import_dir.setEnabled(True) 
        self._btn_auto_share.setEnabled(True) 
        self._btn_add_tm.setEnabled(True) 
        self._btn_export_scene_png.setEnabled(True)
        self._btn_export_scene_c.setEnabled(True)
        self._btn_export_scene_tmc.setEnabled(True)
        self._btn_batch_replace.setEnabled(True)
        self._btn_quick_palette.setEnabled(True)
        self._btn_quick_tilemap.setEnabled(True)
        self._btn_quick_level.setEnabled(True)
        self._btn_quick_hitbox.setEnabled(True)
        self._btn_quick_export_dir.setEnabled(self._export_dir_abs() is not None)
        self._combo_scene_preset.setEnabled(True)
        self._btn_apply_scene_preset.setEnabled(True)
        self._set_scene_audio_controls_enabled(True)
        self._refresh_scene_audio_ui(scene)
        if hasattr(self, "_asset_browser"):
            self._asset_browser.set_can_add(True)
        self._set_sprite_open_actions_enabled(self._spr_tree.currentItem() is not None)

        self._spr_populating = True
        self._spr_tree.blockSignals(True)
        self._spr_tree.clear()
        spr_map, tm_map = self._scene_export_maps(scene)
        for spr in scene.get("sprites", []):
            fw, fh, fc = spr.get("frame_w", 8), spr.get("frame_h", 8), spr.get("frame_count", 1)
            fname = Path(spr.get("file", "?")).name
            shared = bool(spr.get("fixed_palette"))
            display = fname + " ↔" if shared else fname
            item = QTreeWidgetItem([
                display, f"{fw}×{fh}", str(fc),
                str(sprite_tile_estimate(spr)), "",
            ])
            if shared:
                item.setForeground(0, QColor(100, 180, 255))
                item.setToolTip(0, tr("proj.pal_shared"))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            key = self._sprite_export_key(spr)
            exp = spr_map.get(key, spr.get("export", True))
            spr["export"] = bool(exp)
            item.setCheckState(
                SPR_COL_EXPORT,
                Qt.CheckState.Checked if bool(exp) else Qt.CheckState.Unchecked,
            )
            item.setToolTip(SPR_COL_EXPORT, tr("proj.col_export_tt"))
            item.setData(0, Qt.ItemDataRole.UserRole, spr)
            self._spr_tree.addTopLevelItem(item)
        self._spr_tree.resizeColumnToContents(0)
        self._spr_tree.blockSignals(False)
        self._spr_populating = False

        self._tm_populating = True
        self._tm_list.blockSignals(True)
        self._tm_list.clear()
        for tm in scene.get("tilemaps", []):
            plane = tm.get("plane", "auto")
            badge = {"scr1": "[SCR1]", "scr2": "[SCR2]"}.get(plane, "")
            name = Path(tm.get("file", "?")).name
            label = f"{badge} {name}" if badge else name
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            key = self._tilemap_export_key(tm)
            exp = tm_map.get(key, tm.get("export", True))
            tm["export"] = bool(exp)
            item.setCheckState(
                Qt.CheckState.Checked if bool(exp) else Qt.CheckState.Unchecked
            )
            item.setToolTip(tr("proj.col_export_tt"))
            item.setData(Qt.ItemDataRole.UserRole, tm)
            self._tm_list.addItem(item)
        self._tm_list.blockSignals(False)
        self._tm_populating = False

        bg_analysis = self._analyze_scene_bg_palettes(scene)
        bg_exact = self._analyze_scene_bg_palettes_exact(scene)
        self._apply_tilemap_bg_palette_highlights(bg_analysis, bg_exact)
        self._lbl_tm_palette_info.setText(self._format_tm_palette_info(bg_analysis, bg_exact))

        t = scene_tile_estimate(scene)
        p = scene_pal_estimate(scene)
        budget_text = tr("proj.budget_scene", tiles=t, pals=p)
        bg_budget = self._format_bg_palette_budget(bg_exact)
        if bg_budget:
            budget_text += "\n" + bg_budget
        self._scene_budget.setText(budget_text)

    def _tilemap_scene_label(self, tm: dict) -> str:
        label = str(tm.get("name") or "").strip()
        if label:
            return label
        rel = str(tm.get("file") or "").strip()
        if not rel:
            return "?"
        stem = Path(rel).stem
        return stem[:-5] if stem.lower().endswith("_scr1") else stem

    def _analyze_scene_bg_palettes(self, scene: dict) -> dict | None:
        try:
            return analyze_scene_bg_palette_banks(scene, self._project_dir)
        except Exception:
            return None

    def _analyze_scene_bg_palettes_exact(self, scene: dict) -> dict | None:
        try:
            return analyze_scene_bg_palette_banks_exact(scene, self._project_dir)
        except Exception:
            return None

    def _shared_bg_palette_names(self, analysis: dict | None) -> set[str]:
        shared: set[str] = set()
        if not isinstance(analysis, dict):
            return shared
        for plane in ("scr1", "scr2"):
            plane_info = analysis.get(plane)
            if plane_info is None:
                continue
            for group in getattr(plane_info, "identical_groups", ()) or ():
                for name in group:
                    shared.add(str(name))
        return shared

    def _apply_tilemap_bg_palette_highlights(self, analysis: dict | None, exact: dict | None) -> None:
        shared = self._shared_bg_palette_names(analysis)
        exact_shared = self._shared_bg_palette_names(exact)
        for row in range(self._tm_list.count()):
            item = self._tm_list.item(row)
            if item is None:
                continue
            tm = item.data(Qt.ItemDataRole.UserRole)
            name = self._tilemap_scene_label(tm if isinstance(tm, dict) else {})
            if name in exact_shared:
                item.setForeground(QColor(100, 180, 255))
                item.setToolTip(tr("proj.tm_bg_palette_shared_tt"))
            elif name in shared:
                item.setForeground(QColor(214, 176, 86))
                item.setToolTip(tr("proj.tm_bg_palette_match_tt"))

    def _format_tm_palette_info(self, analysis: dict | None, exact: dict | None) -> str:
        if not isinstance(analysis, dict):
            return ""
        reusable_parts: list[str] = []
        match_parts: list[str] = []
        estimated = False
        for plane in ("scr1", "scr2"):
            plane_info = analysis.get(plane)
            if plane_info is None:
                continue
            estimated = estimated or bool(getattr(plane_info, "is_estimated", False))
            groups = getattr(plane_info, "identical_groups", ()) or ()
            if groups:
                chunks = " / ".join(", ".join(str(name) for name in group) for group in groups)
                match_parts.append(
                    tr(
                        "proj.tm_palette_plane_group",
                        plane=tr(f"proj.tm_palette_plane_{plane}"),
                        names=chunks,
                    )
                )
        if isinstance(exact, dict):
            for plane in ("scr1", "scr2"):
                plane_info = exact.get(plane)
                if plane_info is None:
                    continue
                estimated = estimated or bool(getattr(plane_info, "is_estimated", False))
                groups = getattr(plane_info, "identical_groups", ()) or ()
                if groups:
                    chunks = " / ".join(", ".join(str(name) for name in group) for group in groups)
                    reusable_parts.append(
                        tr(
                            "proj.tm_palette_plane_group",
                            plane=tr(f"proj.tm_palette_plane_{plane}"),
                            names=chunks,
                        )
                    )
        if not match_parts and not reusable_parts:
            return tr("proj.tm_palette_info_none")
        lines: list[str] = []
        if reusable_parts:
            lines.append(tr("proj.tm_palette_info_exact", summary="  |  ".join(reusable_parts)))
        if match_parts:
            lines.append(tr("proj.tm_palette_info_shared", summary="  |  ".join(match_parts)))
        msg = "\n".join(lines)
        if estimated:
            msg += "\n" + tr("proj.tm_palette_info_estimated")
        return msg

    def _format_bg_palette_budget(self, analysis: dict | None) -> str:
        stats = self._bg_palette_reuse_stats(analysis)
        if stats is None:
            return ""
        if stats["total"] == 0:
            return ""
        line = tr(
            "proj.budget_scene_bg",
            scr1=stats["scr1"],
            scr2=stats["scr2"],
            saved=stats["saved"],
        )
        if stats["estimated"]:
            line += " " + tr("proj.budget_scene_bg_estimated")
        return line

    def _bg_palette_reuse_stats(self, analysis: dict | None) -> dict[str, int | bool] | None:
        if not isinstance(analysis, dict):
            return None
        totals: dict[str, int] = {"scr1": 0, "scr2": 0}
        uniques: dict[str, int] = {"scr1": 0, "scr2": 0}
        estimated = False
        for plane in ("scr1", "scr2"):
            plane_info = analysis.get(plane)
            if plane_info is None:
                continue
            estimated = estimated or bool(getattr(plane_info, "is_estimated", False))
            signature_counts: dict[object, int] = {}
            for entry in getattr(plane_info, "entries", ()) or ():
                pal_count = int(getattr(entry, "palette_count", 0) or 0)
                totals[plane] += pal_count
                signature = getattr(entry, "bank_signature", ())
                signature_counts.setdefault(signature, pal_count)
            uniques[plane] = sum(int(v) for v in signature_counts.values())
        saved = max(0, (totals["scr1"] + totals["scr2"]) - (uniques["scr1"] + uniques["scr2"]))
        return {
            "scr1": uniques["scr1"],
            "scr2": uniques["scr2"],
            "saved": saved,
            "total": totals["scr1"] + totals["scr2"],
            "estimated": estimated,
        }

    def _project_bg_palette_reuse_summary(self) -> str:
        if not isinstance(self._data, dict):
            return ""
        scenes = self._data.get("scenes", []) or []
        saved_total = 0
        scene_count = 0
        estimated = False
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            stats = self._bg_palette_reuse_stats(self._analyze_scene_bg_palettes_exact(scene))
            if not stats:
                continue
            estimated = estimated or bool(stats.get("estimated", False))
            saved = int(stats.get("saved", 0) or 0)
            if saved > 0:
                saved_total += saved
                scene_count += 1
        if saved_total <= 0:
            return tr("proj.budget_global_bg_none")
        line = tr("proj.budget_global_bg", scenes=scene_count, saved=saved_total)
        if estimated:
            line += " " + tr("proj.budget_scene_bg_estimated")
        return line

    def _update_global_budget(self) -> None:
        if self._is_free_mode:
            return
        t = project_tile_estimate(self._data)
        p = project_pal_estimate(self._data)
        ok = tr("proj.budget_ok") if t <= TILE_MAX and p <= PAL_MAX_SPR else tr("proj.budget_warn")
        budget_text = tr("proj.budget_global", tiles=t, pals=p, ok=ok)
        bg_text = self._project_bg_palette_reuse_summary()
        if bg_text:
            budget_text += "\n" + bg_text
        self._global_budget.setText(budget_text)
        self._update_project_validation()
        self._update_template_contract()

    # ------------------------------------------------------------------
    # Per-scene BGM metadata (AUD-1/AUD-2)
    # Project-level audio (manifest, SFX, SFX map) lives in GlobalsTab.
    # ------------------------------------------------------------------

    def _populate_bgm_combo(self) -> None:
        if not hasattr(self, "_scene_bgm_list"):
            return
        self._scene_bgm_list.blockSignals(True)
        self._scene_bgm_list.clear()
        manifest = getattr(self, "_audio_manifest", None)
        if manifest is not None:
            for s in manifest.songs:
                label = f"{s.idx:02d}  {s.name or s.song_id or '?'}"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, int(s.idx))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self._scene_bgm_list.addItem(item)
        self._scene_bgm_list.blockSignals(False)
        self._rebuild_scene_bgm_combo([], -1)
        scene = self._current_scene()
        if scene is not None:
            self._refresh_scene_audio_ui(scene)

    def _manifest_song_entries(self) -> list[tuple[int, str]]:
        rows: list[tuple[int, str]] = []
        manifest = getattr(self, "_audio_manifest", None)
        if manifest is None:
            return rows
        for s in manifest.songs:
            rows.append((int(s.idx), f"{s.idx:02d}  {s.name or s.song_id or '?'}"))
        return rows

    def _coerce_bgm_index(self, value: object, default: int = -1) -> int:
        try:
            if value is None:
                return int(default)
            return int(value)
        except Exception:
            return int(default)

    def _current_scene_bgm_index(self) -> int:
        data = self._cmb_scene_bgm.currentData()
        return self._coerce_bgm_index(data, -1)

    def _scene_audio_tracks(self, scene: dict) -> list[int]:
        a = self._scene_audio_dict(scene)
        rows: list[int] = []
        raw = a.get("tracks", [])
        if isinstance(raw, list):
            for value in raw:
                idx = self._coerce_bgm_index(value, -1)
                if idx < 0 or idx in rows:
                    continue
                rows.append(idx)
        bgm_index = self._coerce_bgm_index(a.get("bgm_index", -1), -1)
        if bgm_index >= 0 and bgm_index not in rows:
            rows.append(bgm_index)
        return rows

    def _checked_scene_bgm_ids(self) -> list[int]:
        rows: list[int] = []
        for i in range(self._scene_bgm_list.count()):
            item = self._scene_bgm_list.item(i)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            idx = self._coerce_bgm_index(item.data(Qt.ItemDataRole.UserRole), -1)
            if idx < 0 or idx in rows:
                continue
            rows.append(idx)
        return rows

    def _rebuild_scene_bgm_combo(self, track_ids: list[int], selected_id: int) -> None:
        labels = {idx: label for idx, label in self._manifest_song_entries()}
        self._cmb_scene_bgm.blockSignals(True)
        self._cmb_scene_bgm.clear()
        self._cmb_scene_bgm.addItem(tr("proj.bgm_none"), -1)
        for idx in track_ids:
            self._cmb_scene_bgm.addItem(labels.get(idx, f"{idx:02d}"), int(idx))
        if selected_id < 0:
            combo_id = -1
        elif selected_id in track_ids:
            combo_id = selected_id
        else:
            combo_id = track_ids[0] if track_ids else -1
        combo_row = self._cmb_scene_bgm.findData(combo_id)
        self._cmb_scene_bgm.setCurrentIndex(combo_row if combo_row >= 0 else 0)
        self._cmb_scene_bgm.blockSignals(False)

    def _save_scene_audio_from_controls(self, scene: dict) -> None:
        a = self._scene_audio_dict(scene)
        tracks = self._checked_scene_bgm_ids()
        bgm_index = self._current_scene_bgm_index()
        if bgm_index not in tracks and bgm_index >= 0:
            bgm_index = tracks[0] if tracks else -1
        a["tracks"] = tracks
        a["bgm_index"] = int(bgm_index)
        a["autostart"] = bool(self._chk_bgm_autostart.isChecked())
        a["fade_out"] = int(self._spin_bgm_fade.value())
        scene["audio"] = a
        self._on_save()

    def _scene_audio_dict(self, scene: dict) -> dict:
        a = scene.get("audio", {}) if isinstance(scene, dict) else {}
        if not isinstance(a, dict):
            a = {}
        return a

    def _set_scene_audio_controls_enabled(self, enabled: bool) -> None:
        self._scene_bgm_list.setEnabled(bool(enabled))
        self._cmb_scene_bgm.setEnabled(bool(enabled))
        self._chk_bgm_autostart.setEnabled(bool(enabled))
        self._spin_bgm_fade.setEnabled(bool(enabled))

    def _refresh_scene_audio_ui(self, scene: dict) -> None:
        a = self._scene_audio_dict(scene)
        track_ids = self._scene_audio_tracks(scene)
        bgm_index = self._coerce_bgm_index(a.get("bgm_index", -1), -1)
        autostart = bool(a.get("autostart", True))
        fade_out = self._coerce_bgm_index(a.get("fade_out", 0), 0)

        self._scene_bgm_list.blockSignals(True)
        selected = set(track_ids)
        for i in range(self._scene_bgm_list.count()):
            item = self._scene_bgm_list.item(i)
            item_id = self._coerce_bgm_index(item.data(Qt.ItemDataRole.UserRole), -1)
            item.setCheckState(Qt.CheckState.Checked if item_id in selected else Qt.CheckState.Unchecked)
        self._scene_bgm_list.blockSignals(False)

        self._rebuild_scene_bgm_combo(track_ids, bgm_index)

        self._chk_bgm_autostart.blockSignals(True)
        self._chk_bgm_autostart.setChecked(autostart)
        self._chk_bgm_autostart.blockSignals(False)

        self._spin_bgm_fade.blockSignals(True)
        self._spin_bgm_fade.setValue(max(0, fade_out))
        self._spin_bgm_fade.blockSignals(False)

    def _on_scene_bgm_list_changed(self, _item: QListWidgetItem) -> None:
        scene = self._current_scene()
        if not scene:
            return
        a = self._scene_audio_dict(scene)
        track_ids = self._checked_scene_bgm_ids()
        selected_id = self._coerce_bgm_index(a.get("bgm_index", -1), -1)
        self._rebuild_scene_bgm_combo(track_ids, selected_id)
        self._save_scene_audio_from_controls(scene)

    def _on_scene_bgm_changed(self, _idx: int) -> None:
        scene = self._current_scene()
        if not scene:
            return
        self._save_scene_audio_from_controls(scene)

    def _on_scene_bgm_opt_changed(self, _val=None) -> None:
        scene = self._current_scene()
        if not scene:
            return
        self._save_scene_audio_from_controls(scene)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _on_scene_row_changed(self, row: int) -> None: 
        _ = row
        self._commit_current_scene_export_flags(self._last_scene)
        it = self._scenes_list.currentItem()
        scene = it.data(Qt.ItemDataRole.UserRole) if it is not None else None
        scene = self._canonical_scene_ref(scene)
        self._refresh_detail(scene)
        can = scene is not None
        self._btn_ren.setEnabled(can)
        self._btn_del.setEnabled(can)
        self._btn_import_dir.setEnabled(can)
        self._btn_auto_share.setEnabled(can)
        self._btn_rm_spr.setEnabled(can) 
        self._btn_rm_tm.setEnabled(can) 
        self.scene_activated.emit(scene) 
        self._last_scene = scene

    def _on_sprite_selection_changed(self) -> None:
        scene = self._current_scene()
        if not scene:
            self._set_sprite_open_actions_enabled(False)
            return
        has_sel = self._spr_tree.currentItem() is not None
        self._set_sprite_open_actions_enabled(has_sel)

    def _set_sprite_open_actions_enabled(self, enabled: bool) -> None:
        self._btn_open_in.setEnabled(bool(enabled))

    def _sprite_export_enabled(self, spr: dict) -> bool:
        return bool(spr.get("export", True))

    def _tilemap_export_enabled(self, tm: dict) -> bool:
        return bool(tm.get("export", True))

    def _sprite_export_key(self, spr: dict) -> str:
        rel = str(spr.get("file") or "").strip()
        if rel:
            return rel
        return str(spr.get("name") or "").strip()

    def _tilemap_export_key(self, tm: dict) -> str:
        rel = str(tm.get("file") or "").strip()
        if rel:
            return rel
        return str(tm.get("name") or "").strip()

    def _scene_export_maps(self, scene: dict) -> tuple[dict, dict]:
        spr_map = scene.get("export_sprites", {})
        tm_map = scene.get("export_tilemaps", {})
        if not isinstance(spr_map, dict):
            spr_map = {}
        if not isinstance(tm_map, dict):
            tm_map = {}
        scene["export_sprites"] = spr_map
        scene["export_tilemaps"] = tm_map
        return spr_map, tm_map

    def _on_sprite_item_changed(self, item: QTreeWidgetItem, col: int) -> None:
        if self._spr_populating or col != SPR_COL_EXPORT:
            return
        spr = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(spr, dict):
            return
        val = item.checkState(SPR_COL_EXPORT) == Qt.CheckState.Checked
        spr["export"] = val
        scene = self._current_scene()
        if scene:
            spr_map, _tm_map = self._scene_export_maps(scene)
            key = self._sprite_export_key(spr)
            if key:
                spr_map[key] = bool(val)
        self._on_save()

    def _on_tm_item_changed(self, item: QListWidgetItem) -> None:
        if self._tm_populating:
            return
        tm = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(tm, dict):
            return
        val = item.checkState() == Qt.CheckState.Checked
        tm["export"] = val
        scene = self._current_scene()
        if scene:
            _spr_map, tm_map = self._scene_export_maps(scene)
            key = self._tilemap_export_key(tm)
            if key:
                tm_map[key] = bool(val)
        self._on_save()

    def _commit_current_scene_export_flags(self, scene: dict | None) -> None:
        if self._spr_populating or self._tm_populating:
            return
        if scene is None:
            return
        changed = False
        spr_map, tm_map = self._scene_export_maps(scene)
        for i in range(self._spr_tree.topLevelItemCount()):
            it = self._spr_tree.topLevelItem(i)
            spr = it.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(spr, dict):
                continue
            val = it.checkState(SPR_COL_EXPORT) == Qt.CheckState.Checked
            if spr.get("export", True) != val:
                spr["export"] = val
                changed = True
            if scene:
                key = self._sprite_export_key(spr)
                if key and spr_map.get(key, True) != val:
                    spr_map[key] = bool(val)
                    changed = True
        for i in range(self._tm_list.count()):
            it = self._tm_list.item(i)
            tm = it.data(Qt.ItemDataRole.UserRole)
            if not isinstance(tm, dict):
                continue
            val = it.checkState() == Qt.CheckState.Checked
            if tm.get("export", True) != val:
                tm["export"] = val
                changed = True
            if scene:
                key = self._tilemap_export_key(tm)
                if key and tm_map.get(key, True) != val:
                    tm_map[key] = bool(val)
                    changed = True
        if changed:
            self._on_save()

    def _on_sprite_double_clicked(self, item: QTreeWidgetItem, col: int) -> None:
        mods = QApplication.keyboardModifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            self._emit_open_sprite_in_palette(item)
            return
        self._edit_sprite(item, col)

    def _emit_open_sprite_in_palette(self, item: QTreeWidgetItem) -> None:
        spr = item.data(0, Qt.ItemDataRole.UserRole) or {}
        rel = spr.get("file", "")
        if not rel:
            return
        path = self._abs(rel)
        payload = {
            "path": path,
            "frame_w": int(spr.get("frame_w", 8)),
            "frame_h": int(spr.get("frame_h", 8)),
            "frame_count": int(spr.get("frame_count", 1)),
        }
        self.open_sprite_in_palette.emit(payload)

    def _open_selected_sprite_in_palette(self) -> None:
        it = self._spr_tree.currentItem()
        if it is None:
            return
        self._emit_open_sprite_in_palette(it)

    def _open_selected_sprite_in_editor(self) -> None:
        it = self._spr_tree.currentItem()
        if it is None:
            return
        spr = it.data(0, Qt.ItemDataRole.UserRole) or {}
        rel = spr.get("file", "")
        if not rel:
            return
        self.open_asset_in_editor.emit(self._abs(rel))

    def _open_selected_sprite_in_hitbox(self) -> None:
        it = self._spr_tree.currentItem()
        if it is None:
            return
        spr = it.data(0, Qt.ItemDataRole.UserRole) or {}
        rel = spr.get("file", "")
        if not rel:
            return
        # Pass the full sprite meta (including hitboxes if already stored)
        self.open_sprite_in_hitbox.emit(spr)

    def _current_scene(self) -> dict | None: 
        it = self._scenes_list.currentItem()
        scene = it.data(Qt.ItemDataRole.UserRole) if it is not None else None
        return self._canonical_scene_ref(scene)

    def _canonical_scene_ref(self, scene: dict | None) -> dict | None:
        if scene is None or not isinstance(scene, dict):
            return None
        scenes = self._data.get("scenes", []) if isinstance(self._data, dict) else []
        if not isinstance(scenes, list) or not scenes:
            return scene
        sid = str(scene.get("id") or "").strip()
        if sid:
            for s in scenes:
                if isinstance(s, dict) and str(s.get("id") or "").strip() == sid:
                    return s
        label = str(scene.get("label") or "").strip()
        if label:
            for s in scenes:
                if isinstance(s, dict) and str(s.get("label") or "").strip() == label:
                    return s
        return scene

    def _template_preflight_scenes(self, scope: str) -> list[dict]:
        """Return the scene subset targeted by a template-ready export."""
        if scope == "current":
            scene = self._current_scene()
            return [scene] if isinstance(scene, dict) else []
        scenes = self._data.get("scenes", []) if isinstance(self._data, dict) else []
        return [s for s in scenes if isinstance(s, dict)]

    def _on_scenes_reordered(self, *_args) -> None:
        # Rebuild the project scene list to match the UI order.
        scenes: list[dict] = []
        for i in range(self._scenes_list.count()):
            it = self._scenes_list.item(i)
            s = it.data(Qt.ItemDataRole.UserRole) if it is not None else None
            if isinstance(s, dict):
                scenes.append(self._canonical_scene_ref(s) or s)
        if isinstance(self._data, dict):
            self._data["scenes"] = scenes
            self._on_save()
        self._populate_start_scene_combo()

    def current_scene(self) -> dict | None:
        """Public: currently selected scene (or None)."""
        return self._current_scene()

    def select_scene(self, scene_ref: dict | str | None) -> bool:
        """Public: select a scene by dict, id, or label."""
        if scene_ref is None:
            return False
        wanted = ""
        wanted_label = ""
        if isinstance(scene_ref, dict):
            wanted = str(scene_ref.get("id") or "").strip()
            wanted_label = str(scene_ref.get("label") or "").strip()
        else:
            wanted = str(scene_ref).strip()
            wanted_label = wanted
        if not wanted and not wanted_label:
            return False

        for i in range(self._scenes_list.count()):
            item = self._scenes_list.item(i)
            scene = self._canonical_scene_ref(item.data(Qt.ItemDataRole.UserRole) if item is not None else None)
            if not isinstance(scene, dict):
                continue
            sid = str(scene.get("id") or "").strip()
            label = str(scene.get("label") or "").strip()
            if (wanted and sid == wanted) or (wanted_label and label == wanted_label):
                if self._scenes_list.currentRow() != i:
                    self._scenes_list.setCurrentRow(i)
                else:
                    self._refresh_detail(scene)
                    self.scene_activated.emit(scene)
                return True
        return False

    def refresh_current_scene(self) -> None:
        """Public: refresh right panel for the currently selected scene."""
        scene = self._current_scene()
        self._refresh_detail(scene)
        self._refresh_scene_statuses()
        self._update_global_budget()

    def focus_template_ready_workflow(self) -> None:
        if bool(self._btn_project_first_issue.isEnabled()):
            self._btn_project_first_issue.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        self._btn_export_template_ready.setFocus(Qt.FocusReason.OtherFocusReason)

    # ------------------------------------------------------------------
    # Phase 5 — Build / Run integration
    # ------------------------------------------------------------------

    def _open_build_dialog(self) -> None:
        if not self._project_dir:
            return

        dlg = BuildDialog(
            project_dir=self._project_dir,
            on_run_requested=self._run_emulator,
            parent=self,
        )
        dlg.exec()

    def _export_build_run(self) -> None:
        """Export (template-ready) → Build (auto-start) → Run emulator."""
        self._export_template_ready()
        if not self._project_dir:
            return
        dlg = BuildDialog(
            project_dir=self._project_dir,
            on_run_requested=self._run_emulator,
            parent=self,
            auto_start=True,
            run_after=True,
        )
        dlg.exec()

    def _open_run_dialog(self) -> None:
        if not self._project_dir:
            return
        dlg = RunDialog(project_dir=self._project_dir, parent=self)
        dlg.exec()

    def _detect_emulator(self) -> str | None:
        # Prefer explicit user setting
        settings = QSettings("NGPCraft", "Engine")
        p = (settings.value("run/emulator_path", "", str) or "").strip()
        if p:
            return p

        for cmd in ("mednafen", "race", "neopop"):
            found = shutil.which(cmd)
            if found:
                return found
        return None

    def _detect_rom(self) -> Path | None:
        if not self._project_dir:
            return None
        settings = QSettings("NGPCraft", "Engine")
        saved: Path | None = None
        p = (settings.value("run/rom_path", "", str) or "").strip()
        if p:
            rp = Path(p)
            if rp.exists():
                saved = rp

        # Heuristic: look in common output dirs first.
        roots = [self._project_dir]
        for sub in ("build", "out", "bin", "dist"):
            d = self._project_dir / sub
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

        if saved is None:
            return best

        # If a newer ROM exists inside the project, prefer it (avoid running an old pinned path).
        try:
            saved_m = saved.stat().st_mtime
        except OSError:
            saved_m = -1.0

        # Prefer project-local ROMs over external pinned ROMs.
        saved_in_project = False
        try:
            _ = saved.resolve().relative_to(self._project_dir.resolve())
            saved_in_project = True
        except Exception:
            saved_in_project = False

        if best is None:
            return saved

        if (not saved_in_project) or (best_m > saved_m + 1e-6):
            # Auto-update the setting so "Run" stays in sync with the last build output.
            try:
                settings.setValue("run/rom_path", str(best))
            except Exception:
                pass
            return best

        return saved

    def _run_emulator(self) -> None:
        if not self._project_dir:
            return

        settings = QSettings("NGPCraft", "Engine")
        emu = self._detect_emulator()
        if not emu:
            p, _ = QFileDialog.getOpenFileName(
                self,
                tr("proj.run_pick_emu"),
                str(self._project_dir),
                tr("proj.run_emu_filter"),
            )
            if not p:
                return
            emu = p
            settings.setValue("run/emulator_path", emu)

        rom = self._detect_rom()
        if rom is None or not rom.exists():
            p, _ = QFileDialog.getOpenFileName(
                self,
                tr("proj.run_pick_rom"),
                str(self._project_dir),
                tr("proj.run_rom_filter"),
            )
            if not p:
                return
            rom = Path(p)
            settings.setValue("run/rom_path", str(rom))

        ok = QProcess.startDetached(str(emu), [str(rom)], str(rom.parent))
        if not ok:
            QMessageBox.warning(self, tr("proj.run"), tr("proj.run_fail", emu=str(emu)))

    # ------------------------------------------------------------------
    # Scene CRUD
    # ------------------------------------------------------------------

    def _add_scene(self) -> None:
        name, ok = QInputDialog.getText(
            self, tr("proj.rename_title"), tr("proj.rename_label"),
            text=tr("proj.new_scene_name"),
        )
        if not ok or not name.strip():
            return
        self._data["scenes"].append({
            "id": str(uuid.uuid4())[:8],
            "label": name.strip(),
            "sprites": [], "tilemaps": [],
        })
        self._on_save()
        self._populate_scenes()
        self._scenes_list.setCurrentRow(len(self._data["scenes"]) - 1)
        self._update_global_budget()

    def _rename_scene(self) -> None:
        scene = self._current_scene()
        if not scene:
            return
        name, ok = QInputDialog.getText(
            self, tr("proj.rename_title"), tr("proj.rename_label"),
            text=scene.get("label", ""),
        )
        if not ok or not name.strip():
            return
        scene["label"] = name.strip()
        self._on_save()
        row = self._scenes_list.currentRow()
        self._populate_scenes()
        self._scenes_list.setCurrentRow(row)

    def _delete_scene(self) -> None:
        scene = self._current_scene()
        if not scene:
            return
        if QMessageBox.question(
            self, tr("proj.confirm_delete"),
            tr("proj.confirm_delete", name=scene.get("label", "?")),
        ) != QMessageBox.StandardButton.Yes:
            return
        row = self._scenes_list.currentRow()
        self._data["scenes"].pop(row)
        self._on_save()
        self._populate_scenes()
        self._scenes_list.setCurrentRow(min(row, len(self._data["scenes"]) - 1))
        self._update_global_budget()

    def _change_graphx_dir(self) -> None: 
        base = str(self._project_dir) if self._project_dir else ""
        d = QFileDialog.getExistingDirectory(self, tr("proj.graphx_dir"), base)
        if d: 
            rel = self._rel(Path(d)) 
            self._data["graphx_dir"] = rel 
            self._graphx_label.setText(rel) 
            self._on_save() 
            if hasattr(self, "_asset_browser"):
                self._asset_browser.set_root(Path(d))

    def _refresh_export_dir_ui(self) -> None:
        rel = str(self._data.get("export_dir") or "").strip()
        if rel:
            self._export_dir_label.setText(rel)
            self._export_dir_label.setStyleSheet("")
        else:
            self._export_dir_label.setText(tr("proj.export_dir_auto"))
            self._export_dir_label.setStyleSheet("color: gray; font-style: italic;")
        if hasattr(self, "_btn_quick_export_dir"):
            self._btn_quick_export_dir.setEnabled(self._export_dir_abs() is not None)
        if hasattr(self, "_scenes_list"):
            self._refresh_scene_statuses()

    def _open_export_dir(self) -> None:
        exp_dir = self._export_dir_abs()
        if exp_dir is None:
            QMessageBox.information(self, tr("proj.export_dir"), tr("proj.scene_status_missing_export_dir"))
            return
        exp_dir.mkdir(parents=True, exist_ok=True)
        ok = False
        if _sys.platform.startswith("win"):
            ok = QProcess.startDetached("explorer.exe", [str(exp_dir)])
        elif _sys.platform == "darwin":
            ok = QProcess.startDetached("open", [str(exp_dir)])
        else:
            ok = QProcess.startDetached("xdg-open", [str(exp_dir)])
        if not ok:
            QMessageBox.warning(self, tr("proj.export_dir"), str(exp_dir))

    def _change_export_dir(self) -> None:
        base = str(self._project_dir) if self._project_dir else ""
        d = QFileDialog.getExistingDirectory(self, tr("proj.export_dir"), base)
        if d:
            rel = self._rel(Path(d))
            self._data["export_dir"] = rel
            self._refresh_export_dir_ui()
            self._on_save()

    def _clear_export_dir(self) -> None:
        self._data.pop("export_dir", None)
        self._refresh_export_dir_ui()
        self._on_save()

    # ------------------------------------------------------------------
    # Sprite management
    # ------------------------------------------------------------------

    def _sprite_dialog_start_dir(self) -> str:
        s = QSettings("NGPCraft", "Engine")
        last = s.value("proj/last_sprite_dir", "", type=str)
        if last and Path(last).exists():
            return last
        return str(self._project_dir or "")

    def _set_last_sprite_dir(self, p: Path) -> None:
        d = p if p.is_dir() else p.parent
        QSettings("NGPCraft", "Engine").setValue("proj/last_sprite_dir", str(d))

    def _normalize_palette_words(self, words: list[int]) -> list[int]:
        # Backward compatibility: older project files may store opaque black as 0.
        return [OPAQUE_BLACK if int(w) == 0 else int(w) for w in words]

    def _palette_key(self, words: list[int]) -> frozenset[int]:
        return frozenset(self._normalize_palette_words(words))

    def _fixed_palette_arg_from_words(self, words: list[int]) -> str:
        # Template exporter constraint: exactly 4 entries, and entry 0 must be 0x0000 (transparency).
        uniq: list[int] = []
        seen: set[int] = set()
        for w in self._normalize_palette_words(words):
            if w not in seen:
                uniq.append(w)
                seen.add(w)
        uniq = uniq[:3]
        fixed = [0x0000] + uniq
        while len(fixed) < 4:
            fixed.append(0x0000)
        fixed = fixed[:4]
        return ",".join(f"0x{w:04X}" for w in fixed)

    def _normalize_fixed_palette_arg(self, fp: str | None, fallback_words: list[int]) -> str:
        """
        Ensure a valid --fixed-palette arg string:
          - exactly 4 entries
          - first entry must be 0x0000 (transparency index 0)
        """
        if not fp:
            return self._fixed_palette_arg_from_words(fallback_words)
        try:
            parts = [s.strip() for s in str(fp).split(",") if s.strip()]
            if len(parts) != 4:
                raise ValueError("bad_len")
            fixed: list[int] = []
            for s in parts:
                ss = s.lower()
                if ss.startswith("0x"):
                    ss = ss[2:]
                fixed.append(int(ss, 16))
            if fixed[0] != 0:
                raise ValueError("no_transparent_at_0")
            return ",".join(f"0x{w:04X}" for w in fixed)
        except Exception:
            return self._fixed_palette_arg_from_words(fallback_words)

    def _find_shared_fixed_palette(self, scene: dict, new_words: list[int]) -> str | None:
        """
        Return a fixed palette arg to share with an existing sprite in the scene,
        even if the palette order differs (set-based match).
        """
        new_key = self._palette_key(new_words)
        if not new_key or len(new_key) > 3:
            return None

        best_fp: str | None = None
        best_size: int | None = None

        for existing in scene.get("sprites", []):
            ew = existing.get("palette_words", []) or []
            ekey = self._palette_key(list(ew))
            if not ekey or len(ekey) > 3:
                continue

            if new_key != ekey and not new_key.issubset(ekey):
                continue

            fp = self._normalize_fixed_palette_arg(existing.get("fixed_palette"), list(ew))
            size = len(ekey)
            if new_key == ekey:
                return fp
            if best_size is None or size < best_size:
                best_size = size
                best_fp = fp

        return best_fp

    def _import_sprites_from_paths(self, paths: list[Path]) -> None:
        scene = self._current_scene()
        if not scene or not paths:
            return
        expanded = self._expand_import_paths(paths)
        if not expanded:
            return

        self._set_last_sprite_dir(expanded[0])

        if len(expanded) == 1:
            self._import_single_sprite(scene, expanded[0])
            return

        dlg = _BatchSpriteDialog(expanded[0], self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if dlg.auto_guess:
            self._import_sprite_entries_auto(scene, expanded)
        else:
            self._import_sprite_entries(scene, expanded, fw=dlg.frame_w, fh=dlg.frame_h)

    def _import_single_sprite(self, scene: dict, p: Path) -> None:
        if not p.exists():
            return
        dlg = _AddSpriteDialog(p, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        # Load palette for auto sharing detection
        palette_words: list[int] = []
        fixed_palette: str | None = None
        try:
            sdata = load_sprite(p)
            palette_words = sdata.palette_words
            fixed_palette = self._find_shared_fixed_palette(scene, palette_words)
        except Exception:
            pass

        scene.setdefault("sprites", []).append({
            "name": p.stem,
            "file": self._rel(p),
            "frame_w": dlg.frame_w,
            "frame_h": dlg.frame_h,
            "frame_count": dlg.frame_count,
            "anim_duration": 6,
            "fixed_palette": fixed_palette,
            "palette_words": palette_words,
            "export": True,
        })
        self._on_save()
        self._refresh_detail(scene)
        self._update_global_budget()
        self.scene_activated.emit(scene)  # refresh VRAM map

    def _expand_import_paths(self, paths: list[Path]) -> list[Path]:
        """
        Expand a list of dropped/selected paths into a de-duplicated list of image files.

        - Files: keep if extension is supported.
        - Folders: scan recursively for supported images.
        """
        allowed = (".png", ".bmp", ".gif")
        out: list[Path] = []
        seen: set[str] = set()

        def _add(p: Path) -> None:
            key = str(p)
            if key in seen:
                return
            seen.add(key)
            out.append(p)

        for p in paths:
            if not p.exists():
                continue
            if p.is_file():
                if p.suffix.lower() in allowed:
                    _add(p)
                continue

            if p.is_dir():
                try:
                    files = [f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in allowed]
                except Exception:
                    files = []
                for f in sorted(files, key=lambda x: str(x).lower()):
                    _add(f)

        if len(out) > 500:
            if QMessageBox.question(
                self,
                tr("proj.import_many_title"),
                tr("proj.import_many_msg", n=len(out)),
            ) != QMessageBox.StandardButton.Yes:
                return []
        return out

    def _guess_frame_for_file(self, p: Path) -> tuple[int, int]:
        """
        Heuristic for batch import:
        - frame_w defaults to image width
        - frame_h defaults to the largest common tile-aligned divisor of height (prefers square frames)
        """
        try:
            img = Image.open(p)
            w, h = img.size
        except Exception:
            return 8, 8

        fw = max(1, min(1024, w))
        candidates = [fw, 256, 128, 64, 32, 16, 8]
        fh = None
        for c in candidates:
            if c <= h and h % c == 0:
                fh = c
                break
        if fh is None:
            fh = 8 if h >= 8 else max(1, h)
        fh = max(1, min(1024, fh))
        return fw, fh

    def _import_sprite_entries_auto(self, scene: dict, paths: list[Path]) -> None:
        """Batch import where each file gets its own (guessed) frame_w/frame_h."""
        sprites = scene.setdefault("sprites", [])
        existing_files = {s.get("file", "") for s in sprites}

        for p in paths:
            if not p.exists() or not p.is_file():
                continue
            if p.suffix.lower() not in (".png", ".bmp", ".gif"):
                continue

            rel = self._rel(p)
            if rel in existing_files:
                continue

            fw, fh = self._guess_frame_for_file(p)
            try:
                img = Image.open(p)
                _, ph = img.size
                fc = max(1, ph // max(1, fh))
            except Exception:
                fc = 1

            palette_words: list[int] = []
            fixed_palette: str | None = None
            try:
                sdata = load_sprite(p)
                palette_words = sdata.palette_words
                fixed_palette = self._find_shared_fixed_palette(scene, palette_words)
            except Exception:
                pass

            sprites.append({
                "name": p.stem,
                "file": rel,
                "frame_w": fw,
                "frame_h": fh,
                "frame_count": fc,
                "anim_duration": 6,
                "fixed_palette": fixed_palette,
                "palette_words": palette_words,
                "export": True,
            })
            existing_files.add(rel)

        self._on_save()
        self._refresh_detail(scene)
        self._update_global_budget()
        self.scene_activated.emit(scene)  # refresh VRAM map

    def _import_sprite_entries(self, scene: dict, paths: list[Path], fw: int, fh: int) -> None:
        sprites = scene.setdefault("sprites", [])
        existing_files = {s.get("file", "") for s in sprites}

        for p in paths:
            if not p.exists() or not p.is_file():
                continue
            if p.suffix.lower() not in (".png", ".bmp", ".gif"):
                continue

            rel = self._rel(p)
            if rel in existing_files:
                continue

            # frame_count: auto from image height (stacked frames)
            try:
                img = Image.open(p)
                _, ph = img.size
                fc = max(1, ph // max(1, fh))
            except Exception:
                fc = 1

            # Load palette for auto sharing detection
            palette_words: list[int] = []
            fixed_palette: str | None = None
            try:
                sdata = load_sprite(p)
                palette_words = sdata.palette_words
                fixed_palette = self._find_shared_fixed_palette(scene, palette_words)
            except Exception:
                pass

            sprites.append({
                "name": p.stem,
                "file": rel,
                "frame_w": fw,
                "frame_h": fh,
                "frame_count": fc,
                "anim_duration": 6,
                "fixed_palette": fixed_palette,
                "palette_words": palette_words,
                "export": True,
            })
            existing_files.add(rel)

        self._on_save()
        self._refresh_detail(scene)
        self._update_global_budget()
        self.scene_activated.emit(scene)  # refresh VRAM map

    def _add_sprite(self) -> None:
        scene = self._current_scene()
        if not scene:
            return
        start = self._sprite_dialog_start_dir()
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("proj.add_sprite"), start,
            "PNG (*.png);;Toutes images (*.png *.bmp *.gif)",
        )
        if not paths:
            return
        self._import_sprites_from_paths([Path(p) for p in paths])

    def _import_sprite_folder(self) -> None:
        scene = self._current_scene()
        if not scene:
            return
        start = self._sprite_dialog_start_dir()
        folder = QFileDialog.getExistingDirectory(self, tr("proj.import_folder"), start)
        if not folder:
            return
        self._import_sprites_from_paths([Path(folder)])

    def _auto_share_palettes(self) -> None:
        """Assign --fixed-palette automatically for sprites that share the same colors (order-independent)."""
        scene = self._current_scene()
        if not scene:
            return
        sprites = scene.get("sprites", [])
        if not sprites:
            return

        # Count palette keys
        key_counts: dict[frozenset[int], int] = {}
        for spr in sprites:
            words = spr.get("palette_words", []) or []
            key = self._palette_key(list(words))
            if not key or len(key) > 3:
                continue
            key_counts[key] = key_counts.get(key, 0) + 1

        # Pick a canonical fixed palette per key (prefer an existing valid fixed_palette).
        key_to_fp: dict[frozenset[int], str] = {}
        for spr in sprites:
            words = list(spr.get("palette_words", []) or [])
            key = self._palette_key(words)
            if not key or len(key) > 3 or key_counts.get(key, 0) < 2:
                continue
            fp = spr.get("fixed_palette")
            if fp:
                key_to_fp.setdefault(key, self._normalize_fixed_palette_arg(fp, words))

        for key, n in key_counts.items():
            if n < 2 or len(key) > 3:
                continue
            if key not in key_to_fp:
                key_to_fp[key] = self._fixed_palette_arg_from_words(sorted(key))

        changed = 0
        for spr in sprites:
            words = list(spr.get("palette_words", []) or [])
            key = self._palette_key(words)
            if not key or len(key) > 3:
                continue
            if key_counts.get(key, 0) < 2:
                continue

            before = spr.get("fixed_palette")
            if before:
                spr["fixed_palette"] = self._normalize_fixed_palette_arg(before, words)
                continue
            spr["fixed_palette"] = key_to_fp.get(key)
            if spr.get("fixed_palette"):
                changed += 1

        # Set reuse_palette on consecutive same-fixed sprites so export + VRAM use one slot
        prev_fp = ""
        for spr in sprites:
            fp = str(spr.get("fixed_palette") or "").strip()
            if fp and fp == prev_fp:
                spr["reuse_palette"] = True
            prev_fp = fp

        if changed:
            self._on_save()
            self._refresh_detail(scene)
            self._update_global_budget()
            self.scene_activated.emit(scene)

    def _remove_sprite(self) -> None:
        scene = self._current_scene()
        if not scene:
            return
        item = self._spr_tree.currentItem()
        if not item:
            return
        idx = self._spr_tree.indexOfTopLevelItem(item)
        if 0 <= idx < len(scene.get("sprites", [])):
            scene["sprites"].pop(idx)
            self._on_save()
            self._refresh_detail(scene)
            self._update_global_budget()
            self.scene_activated.emit(scene)

    def _edit_sprite(self, item: QTreeWidgetItem, _col: int) -> None:
        """Double-click on a sprite row → edit frame_w/h/count."""
        scene = self._current_scene()
        if not scene:
            return
        idx = self._spr_tree.indexOfTopLevelItem(item)
        sprites = scene.get("sprites", [])
        if not (0 <= idx < len(sprites)):
            return
        spr = sprites[idx]
        rel_file = spr.get("file", "")
        p = (self._project_dir / rel_file) if self._project_dir else Path(rel_file)
        dlg = _AddSpriteDialog(
            p, self,
            initial_fw=spr.get("frame_w"),
            initial_fh=spr.get("frame_h"),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        spr["frame_w"] = dlg.frame_w
        spr["frame_h"] = dlg.frame_h
        spr["frame_count"] = dlg.frame_count
        self._on_save()
        self._refresh_detail(scene)
        self._update_global_budget()
        self.scene_activated.emit(scene)

    # ------------------------------------------------------------------
    # Tilemap management
    # ------------------------------------------------------------------

    def _add_tilemap(self) -> None: 
        scene = self._current_scene()
        if not scene:
            return
        start = self._sprite_dialog_start_dir()
        path, _ = QFileDialog.getOpenFileName(
            self, tr("proj.add_tilemap"), start,
            "PNG (*.png);;Toutes images (*.png *.bmp *.gif)",
        )
        if not path:
            return
        p = Path(path)
        self._set_last_sprite_dir(p) 
        scene["tilemaps"].append({"name": p.stem, "file": self._rel(p), "export": True}) 
        self._on_save() 
        self._refresh_detail(scene) 

    def _add_tilemaps_from_paths(self, paths: list[Path]) -> None:
        scene = self._current_scene()
        if not scene:
            return
        if not paths:
            return
        self._set_last_sprite_dir(paths[0])
        existing = {tm.get("file", "") for tm in (scene.get("tilemaps", []) or [])}
        for p in paths:
            rel = self._rel(p)
            if rel in existing:
                continue
            existing.add(rel)
            scene.setdefault("tilemaps", []).append({"name": p.stem, "file": rel, "export": True})
        self._on_save()
        self._refresh_detail(scene)
        self.scene_activated.emit(scene)

    def _add_sprites_from_paths(self, paths: list[Path]) -> None:
        scene = self._current_scene()
        if not scene:
            return
        if not paths:
            return
        self._set_last_sprite_dir(paths[0])
        self._import_sprites_from_paths(paths)

    def _remove_tilemap(self) -> None:
        scene = self._current_scene()
        if not scene:
            return
        row = self._tm_list.currentRow()
        if 0 <= row < len(scene.get("tilemaps", [])):
            scene["tilemaps"].pop(row)
            self._on_save()
            self._refresh_detail(scene)

    def _on_tm_selection_changed(self, row: int) -> None:
        scene = self._current_scene()
        if scene is None or row < 0:
            self._tm_plane_pick.setEnabled(False)
            return
        tilemaps = scene.get("tilemaps", [])
        if row >= len(tilemaps):
            self._tm_plane_pick.setEnabled(False)
            return
        plane = tilemaps[row].get("plane", "auto")
        idx = self._tm_plane_pick.findData(plane)
        self._tm_plane_pick.blockSignals(True)
        self._tm_plane_pick.setCurrentIndex(idx if idx >= 0 else 0)
        self._tm_plane_pick.blockSignals(False)
        self._tm_plane_pick.setEnabled(True)

    def _on_tm_plane_changed(self, _idx: int) -> None:
        scene = self._current_scene()
        if scene is None:
            return
        row = self._tm_list.currentRow()
        tilemaps = scene.get("tilemaps", [])
        if row < 0 or row >= len(tilemaps):
            return
        tm = tilemaps[row]
        v = self._tm_plane_pick.currentData()
        plane = str(v) if isinstance(v, str) else "auto"
        if plane not in ("auto", "scr1", "scr2"):
            plane = "auto"
        if tm.get("plane", "auto") == plane:
            return
        tm["plane"] = plane
        self._on_save()
        # Update list item text to reflect new badge
        badge = {"scr1": "[SCR1]", "scr2": "[SCR2]"}.get(plane, "")
        name = Path(tm.get("file", "?")).name
        label = f"{badge} {name}" if badge else name
        item = self._tm_list.item(row)
        if item:
            item.setText(label)

    # ------------------------------------------------------------------
    # Global exports
    # ------------------------------------------------------------------

    def _find_script(self) -> Path | None:
        repo_root = Path(__file__).resolve().parents[2]
        return find_script(
            "export_script_path",
            default_candidates(repo_root, "ngpc_sprite_export.py"),
        )

    def _all_sprites(self, include_disabled: bool = False): 
        for scene in self._data.get("scenes", []): 
            for spr in scene.get("sprites", []): 
                if not include_disabled and not self._sprite_export_enabled(spr):
                    continue
                yield spr, self._abs(spr.get("file", "")) 

    def _scene_sprites(self, scene: dict, include_disabled: bool = False): 
        for spr in scene.get("sprites", []): 
            if not include_disabled and not self._sprite_export_enabled(spr):
                continue
            yield spr, self._abs(spr.get("file", "")) 

    def _all_tilemaps(self, include_disabled: bool = False):
        for scene in self._data.get("scenes", []):
            for tm in scene.get("tilemaps", []):
                if not include_disabled and not self._tilemap_export_enabled(tm):
                    continue
                yield tm, self._abs(tm.get("file", ""))

    def _scene_tilemaps(self, scene: dict, include_disabled: bool = False):
        for tm in scene.get("tilemaps", []):
            if not include_disabled and not self._tilemap_export_enabled(tm):
                continue
            yield tm, self._abs(tm.get("file", ""))

    def _export_all_png(self) -> None: 
        n, errs = 0, [] 
        for spr, path in self._all_sprites(): 
            if not path.exists():
                errs.append(f"? {path.name}")
                continue
            try:
                data = load_sprite(path)
                data.hw.save(str(path.with_stem(path.stem + "_hw")))
                n += 1
            except Exception as e:
                errs.append(f"{path.name}: {e}")
        msg = tr("proj.export_done", n=n)
        if errs:
            msg += "\n" + "\n".join(errs[:6])
        QMessageBox.information(self, tr("proj.export_all_png"), msg) 

    def _export_scene_png(self) -> None: 
        scene = self._current_scene() 
        if not scene: 
            return 
        n, errs = 0, [] 
        for spr, path in self._scene_sprites(scene): 
            if not path.exists(): 
                errs.append(f"? {path.name}") 
                continue 
            try: 
                data = load_sprite(path) 
                data.hw.save(str(path.with_stem(path.stem + "_hw"))) 
                n += 1 
            except Exception as e: 
                errs.append(f"{path.name}: {e}") 
        msg = tr("proj.export_done", n=n) 
        if errs: 
            msg += "\n" + "\n".join(errs[:6]) 
        QMessageBox.information(self, tr("proj.export_scene_png"), msg) 

    def _export_all_c(self) -> None: 
        script = self._find_script() 
        if script is None:
            start = script_dialog_start_dir("export_script_path", fallback=self._project_dir)
            p, _ = QFileDialog.getOpenFileName(self, tr("export.find_script"), start, "Python (*.py)")
            if not p:
                return
            script = Path(p)
            remember_script_path("export_script_path", script)
        from core.sprite_export_pipeline import export_sprite_pipeline

        n, errs = 0, []
        for spr, path in self._all_sprites():
            out_dir = self._export_out_dir_for_asset(path)
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            spr_name = path.stem
            fw = int(spr.get("frame_w", 8) or 8)
            fh = int(spr.get("frame_h", 8) or 8)
            fc = int(spr.get("frame_count", 1) or 1)
            _write_ctrl_header(spr, spr_name, out_dir, errs)
            _write_anims_header(spr, spr_name, out_dir, errs)
            if not path.exists():
                errs.append(f"? {path.name}")
                continue
            try:
                fp = str(spr.get("fixed_palette") or "").strip() or None
                run = export_sprite_pipeline(
                    script=script,
                    source_path=path,
                    out_dir=out_dir,
                    name=spr_name,
                    frame_w=fw,
                    frame_h=fh,
                    frame_count=fc,
                    project_dir=self._project_dir,
                    fixed_palette=fp,
                    output_c=(out_dir / f"{re.sub(r'[^a-zA-Z0-9_]+', '_', spr_name).strip('_') or 'sprite'}_mspr.c"),
                    timeout_s=30,
                )
                if run.ok:
                    n += 1
                    _write_hitbox_props(spr, spr_name, fw, fh, fc, out_dir, errs)
                else:
                    errs.append(f"{path.name}: {run.detail}")
            except Exception as e:
                errs.append(f"{path.name}: {e}")

        # Export all tilemaps from all scenes (if tilemap script is available)
        n_tm = 0
        tm_script = self._find_tilemap_script()
        exp_dir = self._export_dir_abs()
        if tm_script:
            for _tm, path in self._all_tilemaps():
                if not path.exists():
                    errs.append(f"? {path.name}")
                    continue
                try:
                    if exp_dir:
                        try:
                            exp_dir.mkdir(parents=True, exist_ok=True)
                        except Exception:
                            pass
                    scr1, scr2, out_c = self._tilemap_export_paths(path, export_dir=exp_dir)
                    cmd = [_sys.executable, str(tm_script), str(scr1), "-o", str(out_c)]
                    out_name = out_c.stem
                    if out_name.lower().endswith("_map"):
                        out_name = out_name[:-4]
                    if out_name:
                        cmd += ["-n", out_name]
                    if scr2 is not None and scr2.exists():
                        cmd += ["--scr2", str(scr2)]
                    cmd += ["--header"]
                    res = subprocess.run(
                        cmd,
                        capture_output=True, text=True,
                        cwd=str(scr1.parent), timeout=60,
                    )
                    if res.returncode == 0:
                        n_tm += 1
                    else:
                        errs.append(f"{path.name}: code {res.returncode}")
                except Exception as e:
                    errs.append(f"{path.name}: {e}")

        sfx_map_h, sfx_play_c = self._maybe_write_sfx_autogen(exp_dir, errs)
        audio_mk = self._maybe_write_audio_autogen_mk(exp_dir, errs)
        scenes_h = None
        scenes_c = None
        skipped_scenes: list[str] = []
        if exp_dir:
            try:
                scenes_h, scenes_c, skipped_scenes = write_scenes_autogen(project_data=self._data, export_dir=exp_dir)
            except Exception as e:
                errs.append(f"scenes autogen: {e}")
        mk_path = self._maybe_write_assets_autogen_mk(exp_dir, errs)
        constants_h = self._maybe_write_constants_h(exp_dir, errs)
        game_vars_h = self._maybe_write_game_vars_h(exp_dir, errs)
        entity_types_h = self._maybe_write_entity_types_h(exp_dir, errs)
        self._run_globals_validation(errs)

        msg = tr("proj.export_done", n=n)
        if n_tm:
            msg += f"\n+ {n_tm} tilemap(s)"
        if mk_path:
            msg += "\n" + tr("proj.autogen_mk_written", path=self._rel(mk_path))
        if audio_mk:
            msg += "\n" + tr("proj.audio_autogen_mk_written", path=self._rel(audio_mk))
        if sfx_map_h:
            msg += "\n" + tr("proj.sfx_map_written", path=self._rel(sfx_map_h))
        if sfx_play_c:
            msg += "\n" + tr("proj.sfx_play_written", path=self._rel(sfx_play_c))
        if scenes_h and scenes_c:
            msg += "\n" + tr("proj.scenes_autogen_written", h=self._rel(scenes_h), c=self._rel(scenes_c))
            if skipped_scenes:
                msg += "\n" + tr("proj.scenes_autogen_skipped", names=", ".join(skipped_scenes[:8]))
        if constants_h:
            msg += "\n" + tr("proj.constants_written", path=self._rel(constants_h))
        if game_vars_h:
            msg += "\n" + tr("proj.gamevars_written", path=self._rel(game_vars_h))
        if errs:
            msg += "\n" + "\n".join(errs[:6])
        QMessageBox.information(self, tr("proj.export_all_c"), msg)

    def _export_all_scenes_c(self, options: ExportOptions | None = None) -> None:
        """
        Export every scene using the per-scene cascade (tile_base/pal_base), and generate:
        - scene_<name>.h / scene_<name>_level.h (when export_dir is set)
        - scenes_autogen.c/.h (manifest)
        """
        script = self._find_script()
        if script is None:
            start = script_dialog_start_dir("export_script_path", fallback=self._project_dir)
            p, _ = QFileDialog.getOpenFileName(self, tr("export.find_script"), start, "Python (*.py)")
            if not p:
                return
            script = Path(p)
            remember_script_path("export_script_path", script)

        tm_script = self._find_tilemap_script()
        exp_dir = self._export_dir_abs()

        scenes = self._data.get("scenes", []) if isinstance(self._data, dict) else []
        if not isinstance(scenes, list) or not scenes:
            return

        bundle_cfg = (self._data.get("bundle") or {}) if isinstance(self._data, dict) else {}

        total_spr = 0
        total_tm = 0
        errs: list[str] = []

        opts = options or ExportOptions()
        include_disabled = bool(opts.include_disabled_assets)
        do_sprites = bool(opts.export_sprites)
        do_tilemaps = bool(opts.export_tilemaps)
        do_hitbox = bool(opts.export_hitbox_props)
        do_level = bool(opts.export_level_data)
        do_scene_loader = bool(opts.export_scene_loader)
        do_scenes_autogen = bool(opts.export_scenes_autogen)
        do_autogen_mk = bool(opts.export_autogen_mk)
        from core.sprite_export_pipeline import export_sprite_pipeline

        # Purge stale *_mspr.* files before regenerating so renamed sprites
        # (e.g. "car_01-Sheet" → "car_01_Sheet") don't leave orphan files that
        # the Makefile would pick up and cause duplicate symbol linker errors.
        if do_sprites and exp_dir and exp_dir.is_dir():
            for _stale in list(exp_dir.glob("*_mspr.c")) + list(exp_dir.glob("*_mspr.h")):
                try:
                    _stale.unlink()
                except Exception:
                    pass

        for scene in scenes:
            if not isinstance(scene, dict):
                continue

            scene_export = scene_with_export_collision(scene, self._project_dir)

            try:
                t_cursor = int(scene.get("spr_tile_base", bundle_cfg.get("tile_base", 256)))
            except Exception:
                t_cursor = int(bundle_cfg.get("tile_base", 256) or 256)
            try:
                p_cursor = int(scene.get("spr_pal_base", bundle_cfg.get("pal_base", 0)))
            except Exception:
                p_cursor = int(bundle_cfg.get("pal_base", 0) or 0)
            fixed_to_slot: dict[str, int] = {}

            n = 0
            if do_sprites:
                for spr, path in self._scene_sprites(scene, include_disabled=include_disabled):
                    fw = int(spr.get("frame_w", 8) or 8)
                    fh = int(spr.get("frame_h", 8) or 8)
                    fc = int(spr.get("frame_count", 1) or 1)
                    fc_use = None if fc <= 0 else fc
                    fixed = str(spr.get("fixed_palette") or "").strip()
                    spr_name_exp = re.sub(r"[^a-zA-Z0-9_]+", "_", str(spr.get("name") or path.stem)).strip("_") or "sprite"
                    out_dir = self._export_out_dir_for_asset(path)
                    try:
                        out_dir.mkdir(parents=True, exist_ok=True)
                    except Exception:
                        pass
                    if do_hitbox:
                        _write_ctrl_header(spr, spr_name_exp, out_dir, errs)
                        _write_anims_header(spr, spr_name_exp, out_dir, errs)

                    if not path.exists():
                        tiles, pal_n = sprite_tile_estimate(spr), 1
                        auto_share = bool(fixed) and int(pal_n) == 1 and fixed in fixed_to_slot
                        pal_base = fixed_to_slot[fixed] if auto_share else p_cursor
                        errs.append(f"? {path.name}")
                        t_cursor += int(tiles)
                        if bool(fixed) and int(pal_n) == 1:
                            if not auto_share:
                                fixed_to_slot[fixed] = int(pal_base)
                                p_cursor += int(pal_n)
                        else:
                            p_cursor += int(pal_n)
                        continue
                    try:
                        est_tiles, est_pal_n, _est = sprite_export_stats(
                            self._project_dir,
                            path,
                            fw,
                            fh,
                            fc_use,
                            fixed,
                        ) if path.exists() else (sprite_tile_estimate(spr), 1, True)
                        auto_share = bool(fixed) and int(est_pal_n) == 1 and fixed in fixed_to_slot
                        pal_base = fixed_to_slot[fixed] if auto_share else p_cursor

                        run = export_sprite_pipeline(
                            script=script,
                            source_path=path,
                            out_dir=out_dir,
                            name=spr_name_exp,
                            frame_w=fw,
                            frame_h=fh,
                            frame_count=fc,
                            project_dir=self._project_dir,
                            tile_base=int(t_cursor),
                            pal_base=int(pal_base),
                            fixed_palette=fixed or None,
                            output_c=(out_dir / f"{spr_name_exp}_mspr.c"),
                            timeout_s=30,
                        )
                        if run.ok:
                            n += 1
                            if do_hitbox:
                                _write_hitbox_props(spr, spr_name_exp, fw, fh, fc, out_dir, errs)
                        else:
                            errs.append(f"{path.name}: {run.detail}")

                        t_cursor += int(run.tile_slots)
                        if bool(fixed) and int(run.palette_slots) == 1:
                            if not auto_share:
                                fixed_to_slot[fixed] = int(pal_base)
                                p_cursor += int(run.palette_slots)
                        else:
                            p_cursor += int(run.palette_slots)
                    except Exception as e:
                        errs.append(f"{path.name}: {e}")

            # Tilemaps
            n_tm = 0
            if do_tilemaps and tm_script:
                for _tm, path in self._scene_tilemaps(scene, include_disabled=include_disabled):
                    if not path.exists():
                        errs.append(f"? {path.name}")
                        continue
                    try:
                        if exp_dir:
                            try:
                                exp_dir.mkdir(parents=True, exist_ok=True)
                            except Exception:
                                pass
                        scr1, scr2, out_c = self._tilemap_export_paths(path, export_dir=exp_dir)
                        cmd = [_sys.executable, str(tm_script), str(scr1), "-o", str(out_c)]
                        out_name = out_c.stem
                        if out_name.lower().endswith("_map"):
                            out_name = out_name[:-4]
                        if out_name:
                            cmd += ["-n", out_name]
                        if scr2 is not None and scr2.exists():
                            cmd += ["--scr2", str(scr2)]
                        cmd += ["--header"]
                        res = subprocess.run(
                            cmd,
                            capture_output=True, text=True,
                            cwd=str(scr1.parent), timeout=60,
                        )
                        if res.returncode == 0:
                            n_tm += 1
                        else:
                            errs.append(f"{path.name}: code {res.returncode}")
                    except Exception as e:
                        errs.append(f"{path.name}: {e}")

            # Scene headers (export_dir only)
            if exp_dir and self._project_dir:
                level_ok = True
                if do_level:
                    try:
                        from core.scene_level_gen import write_scene_level_h
                        write_scene_level_h(project_data=self._data, scene=scene_export, export_dir=exp_dir, project_dir=self._project_dir)
                    except Exception as e:
                        level_ok = False
                        label = str(scene.get("label") or scene.get("id") or "scene")
                        errs.append(f"[{label}] scene level: {e}")
                    # Dialogue bank export (optional — no-op if no dialogues)
                    try:
                        from core.scene_level_gen import write_scene_dialogs_h
                        write_scene_dialogs_h(scene=scene_export, export_dir=exp_dir)
                    except Exception as e:
                        label = str(scene.get("label") or scene.get("id") or "scene")
                        errs.append(f"[{label}] scene dialogs: {e}")
                if do_scene_loader and (do_sprites or do_tilemaps):
                    if do_level and not level_ok:
                        label = str(scene.get("label") or scene.get("id") or "scene")
                        errs.append(f"[{label}] scene loader: skipped because scene level export failed")
                    else:
                        try:
                            from core.scene_loader_gen import write_scene_loader_h
                            loader_warns: list[str] = []
                            write_scene_loader_h(
                                project_data=self._data,
                                scene=scene_export,
                                project_dir=self._project_dir,
                                export_dir=exp_dir,
                                base_dir=self._project_dir,
                                include_level=do_level,
                                include_disabled=include_disabled,
                                warnings_out=loader_warns,
                            )
                            errs.extend(loader_warns)
                        except Exception as e:
                            label = str(scene.get("label") or scene.get("id") or "scene")
                            errs.append(f"[{label}] scene loader: {e}")

            total_spr += int(n)
            total_tm += int(n_tm)

        sfx_map_h, sfx_play_c = self._maybe_write_sfx_autogen(exp_dir, errs) if do_autogen_mk else (None, None)
        audio_mk = self._maybe_write_audio_autogen_mk(exp_dir, errs) if do_autogen_mk else None

        msg = tr("proj.export_done", n=total_spr)
        if total_tm:
            msg += f"\n+ {total_tm} tilemap(s)"
        if audio_mk:
            msg += "\n" + tr("proj.audio_autogen_mk_written", path=self._rel(audio_mk))
        if sfx_map_h:
            msg += "\n" + tr("proj.sfx_map_written", path=self._rel(sfx_map_h))
        if sfx_play_c:
            msg += "\n" + tr("proj.sfx_play_written", path=self._rel(sfx_play_c))
        if exp_dir and do_scenes_autogen:
            try:
                scenes_h, scenes_c, skipped_scenes = write_scenes_autogen(project_data=self._data, export_dir=exp_dir)
                if scenes_h and scenes_c:
                    msg += "\n" + tr("proj.scenes_autogen_written", h=self._rel(scenes_h), c=self._rel(scenes_c))
                    if skipped_scenes:
                        msg += "\n" + tr("proj.scenes_autogen_skipped", names=", ".join(skipped_scenes[:8]))
            except Exception as e:
                errs.append(f"scenes autogen: {e}")
        mk_path = self._maybe_write_assets_autogen_mk(exp_dir, errs) if do_autogen_mk else None
        if mk_path:
            msg += "\n" + tr("proj.autogen_mk_written", path=self._rel(mk_path))
        constants_h = self._maybe_write_constants_h(exp_dir, errs) if do_autogen_mk else None
        if constants_h:
            msg += "\n" + tr("proj.constants_written", path=self._rel(constants_h))
        game_vars_h = self._maybe_write_game_vars_h(exp_dir, errs) if do_autogen_mk else None
        if game_vars_h:
            msg += "\n" + tr("proj.gamevars_written", path=self._rel(game_vars_h))
        entity_types_h = self._maybe_write_entity_types_h(exp_dir, errs) if do_autogen_mk else None
        if entity_types_h:
            msg += "\n" + tr("proj.entity_types_written", path=self._rel(entity_types_h))
        self._run_globals_validation(errs)
        if errs:
            msg += "\n" + "\n".join(errs[:6])
        QMessageBox.information(self, tr("proj.export_all_scenes_c"), msg)

    def _export_all_scenes_c_ui(self) -> None:
        dlg = ExportOptionsDialog(self, title=tr("proj.export_all_scenes_c"), allow_scope=False)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        opts = dlg.options()
        self._export_all_scenes_c(options=opts)

    def _export_scene_c(self, options: ExportOptions | None = None, show_msg: bool = True) -> None:
        scene = self._current_scene() 
        if not scene: 
            return 
        script = self._find_script() 
        if script is None: 
            start = script_dialog_start_dir("export_script_path", fallback=self._project_dir)
            p, _ = QFileDialog.getOpenFileName(self, tr("export.find_script"), start, "Python (*.py)") 
            if not p: 
                return 
            script = Path(p) 
            remember_script_path("export_script_path", script)

        bundle_cfg = (self._data.get("bundle") or {}) if isinstance(self._data, dict) else {}
        try:
            t_cursor = int(scene.get("spr_tile_base", bundle_cfg.get("tile_base", 256)))
        except Exception:
            t_cursor = int(bundle_cfg.get("tile_base", 256) or 256)
        try:
            p_cursor = int(scene.get("spr_pal_base", bundle_cfg.get("pal_base", 0)))
        except Exception:
            p_cursor = int(bundle_cfg.get("pal_base", 0) or 0)
        fixed_to_slot: dict[str, int] = {}

        opts = options or ExportOptions()
        include_disabled = bool(opts.include_disabled_assets)
        do_sprites = bool(opts.export_sprites)
        do_tilemaps = bool(opts.export_tilemaps)
        do_hitbox = bool(opts.export_hitbox_props)
        do_level = bool(opts.export_level_data)
        do_scene_loader = bool(opts.export_scene_loader)
        do_scenes_autogen = bool(opts.export_scenes_autogen)
        do_autogen_mk = bool(opts.export_autogen_mk)
        from core.sprite_export_pipeline import export_sprite_pipeline

        n, errs = 0, [] 
        if do_sprites:
            for spr, path in self._scene_sprites(scene, include_disabled=include_disabled): 
                fw = int(spr.get("frame_w", 8) or 8)
                fh = int(spr.get("frame_h", 8) or 8)
                fc = int(spr.get("frame_count", 1) or 1)
                fc_use = None if fc <= 0 else fc
                fixed = str(spr.get("fixed_palette") or "").strip()
                spr_name_exp = re.sub(r"[^a-zA-Z0-9_]+", "_", str(spr.get("name") or path.stem)).strip("_") or "sprite"
                out_dir = self._export_out_dir_for_asset(path)
                try:
                    out_dir.mkdir(parents=True, exist_ok=True)
                except Exception:
                    pass
                if do_hitbox:
                    _write_ctrl_header(spr, spr_name_exp, out_dir, errs)
                    _write_anims_header(spr, spr_name_exp, out_dir, errs)

                if not path.exists():
                    tiles, pal_n = sprite_tile_estimate(spr), 1
                    auto_share = bool(fixed) and int(pal_n) == 1 and fixed in fixed_to_slot
                    pal_base = fixed_to_slot[fixed] if auto_share else p_cursor

                    errs.append(f"? {path.name}")
                    t_cursor += int(tiles)
                    if bool(fixed) and int(pal_n) == 1:
                        if auto_share:
                            pass
                        else:
                            fixed_to_slot[fixed] = int(pal_base)
                            p_cursor += int(pal_n)
                    else:
                        p_cursor += int(pal_n)
                    continue 
                try: 
                    est_tiles, est_pal_n, _est = sprite_export_stats(self._project_dir, path, fw, fh, fc_use, fixed) if path.exists() else (sprite_tile_estimate(spr), 1, True)
                    auto_share = bool(fixed) and int(est_pal_n) == 1 and fixed in fixed_to_slot
                    pal_base = fixed_to_slot[fixed] if auto_share else p_cursor

                    run = export_sprite_pipeline(
                        script=script,
                        source_path=path,
                        out_dir=out_dir,
                        name=spr_name_exp,
                        frame_w=fw,
                        frame_h=fh,
                        frame_count=fc,
                        project_dir=self._project_dir,
                        tile_base=int(t_cursor),
                        pal_base=int(pal_base),
                        fixed_palette=fixed or None,
                        output_c=(out_dir / f"{spr_name_exp}_mspr.c"),
                        timeout_s=30,
                    )
                    if run.ok:
                        n += 1
                        if do_hitbox:
                            _write_hitbox_props(spr, spr_name_exp, fw, fh, fc, out_dir, errs)
                    else:
                        errs.append(f"{path.name}: {run.detail}")

                    t_cursor += int(run.tile_slots)
                    if bool(fixed) and int(run.palette_slots) == 1:
                        if auto_share:
                            pass
                        else:
                            fixed_to_slot[fixed] = int(pal_base)
                            p_cursor += int(run.palette_slots)
                    else:
                        p_cursor += int(run.palette_slots)
                except Exception as e:
                    errs.append(f"{path.name}: {e}")

        # Export tilemaps for this scene (if tilemap script is available)
        n_tm = 0
        tm_script = self._find_tilemap_script()
        exp_dir = self._export_dir_abs()
        if do_tilemaps and tm_script:
            for _tm, path in self._scene_tilemaps(scene, include_disabled=include_disabled):
                if not path.exists():
                    errs.append(f"? {path.name}")
                    continue
                try:
                    if exp_dir:
                        try:
                            exp_dir.mkdir(parents=True, exist_ok=True)
                        except Exception:
                            pass
                    scr1, scr2, out_c = self._tilemap_export_paths(path, export_dir=exp_dir)
                    cmd = [_sys.executable, str(tm_script), str(scr1), "-o", str(out_c)]
                    out_name = out_c.stem
                    if out_name.lower().endswith("_map"):
                        out_name = out_name[:-4]
                    if out_name:
                        cmd += ["-n", out_name]
                    if scr2 is not None and scr2.exists():
                        cmd += ["--scr2", str(scr2)]
                    cmd += ["--header"]
                    res = subprocess.run(
                        cmd,
                        capture_output=True, text=True,
                        cwd=str(scr1.parent), timeout=60,
                    )
                    if res.returncode == 0:
                        n_tm += 1
                    else:
                        errs.append(f"{path.name}: code {res.returncode}")
                except Exception as e:
                    errs.append(f"{path.name}: {e}")

        sfx_map_h, sfx_play_c = self._maybe_write_sfx_autogen(exp_dir, errs) if do_autogen_mk else (None, None)
        audio_mk = self._maybe_write_audio_autogen_mk(exp_dir, errs) if do_autogen_mk else None

        scene_h = None
        level_h = None
        scene_export = scene_with_export_collision(scene, self._project_dir)

        if exp_dir and self._project_dir:
            level_ok = True
            if do_level:
                try:
                    from core.scene_level_gen import write_scene_level_h
                    level_h = write_scene_level_h(
                        project_data=self._data,
                        scene=scene_export,
                        export_dir=exp_dir,
                        project_dir=self._project_dir,
                    )
                except Exception as e:
                    level_ok = False
                    label = str(scene.get("label") or scene.get("id") or "scene")
                    errs.append(f"[{label}] scene level: {e}")
                # Dialogue bank export (optional — no-op if no dialogues)
                try:
                    from core.scene_level_gen import write_scene_dialogs_h
                    write_scene_dialogs_h(scene=scene_export, export_dir=exp_dir)
                except Exception as e:
                    label = str(scene.get("label") or scene.get("id") or "scene")
                    errs.append(f"[{label}] scene dialogs: {e}")

            if do_scene_loader and (do_sprites or do_tilemaps):
                if do_level and not level_ok:
                    label = str(scene.get("label") or scene.get("id") or "scene")
                    errs.append(f"[{label}] scene loader: skipped because scene level export failed")
                else:
                    try:
                        from core.scene_loader_gen import write_scene_loader_h
                        loader_warns: list[str] = []
                        scene_h = write_scene_loader_h(
                            project_data=self._data,
                            scene=scene_export,
                            project_dir=self._project_dir,
                            export_dir=exp_dir,
                            base_dir=self._project_dir,
                            include_level=do_level,
                            include_disabled=include_disabled,
                            warnings_out=loader_warns,
                        )
                        errs.extend(loader_warns)
                    except Exception as e:
                        label = str(scene.get("label") or scene.get("id") or "scene")
                        errs.append(f"[{label}] scene loader: {e}")

        msg = tr("proj.export_done", n=n)
        if n_tm:
            msg += f"\n+ {n_tm} tilemap(s)"
        if audio_mk:
            msg += "\n" + tr("proj.audio_autogen_mk_written", path=self._rel(audio_mk))
        if scene_h:
            msg += "\n" + tr("proj.scene_loader_written", path=self._rel(scene_h))
        if level_h:
            msg += "\n" + tr("proj.scene_level_written", path=self._rel(level_h))
        if sfx_map_h:
            msg += "\n" + tr("proj.sfx_map_written", path=self._rel(sfx_map_h))
        if sfx_play_c:
            msg += "\n" + tr("proj.sfx_play_written", path=self._rel(sfx_play_c))
        if exp_dir and do_scenes_autogen:
            try:
                scenes_h, scenes_c, skipped_scenes = write_scenes_autogen(project_data=self._data, export_dir=exp_dir)
                if scenes_h and scenes_c:
                    msg += "\n" + tr("proj.scenes_autogen_written", h=self._rel(scenes_h), c=self._rel(scenes_c))
                    if skipped_scenes:
                        msg += "\n" + tr("proj.scenes_autogen_skipped", names=", ".join(skipped_scenes[:8]))
            except Exception as e:
                errs.append(f"scenes autogen: {e}")
        mk_path = self._maybe_write_assets_autogen_mk(exp_dir, errs) if do_autogen_mk else None
        if mk_path:
            msg += "\n" + tr("proj.autogen_mk_written", path=self._rel(mk_path))
        constants_h = self._maybe_write_constants_h(exp_dir, errs) if do_autogen_mk else None
        if constants_h:
            msg += "\n" + tr("proj.constants_written", path=self._rel(constants_h))
        game_vars_h = self._maybe_write_game_vars_h(exp_dir, errs) if do_autogen_mk else None
        if game_vars_h:
            msg += "\n" + tr("proj.gamevars_written", path=self._rel(game_vars_h))
        entity_types_h = self._maybe_write_entity_types_h(exp_dir, errs) if do_autogen_mk else None
        if entity_types_h:
            msg += "\n" + tr("proj.entity_types_written", path=self._rel(entity_types_h))
        self._run_globals_validation(errs)
        if errs:
            msg += "\n" + "\n".join(errs[:6])
        if show_msg:
            QMessageBox.information(self, tr("proj.export_scene_c"), msg)

    def _export_scene_c_ui(self) -> None:
        if not self._current_scene():
            QMessageBox.information(self, tr("proj.export_scene_c"), tr("proj.export_need_scene"))
            return
        dlg = ExportOptionsDialog(self, title=tr("proj.export_scene_c"), allow_scope=False)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        opts = dlg.options()
        self._export_scene_c(options=opts, show_msg=True)

    def _export_template_ready(self) -> None:
        """
        Beginner-friendly one-click:
        - Ensure export_dir defaults to GraphX/gen
        - Export all scenes (.c) + autogen mk + scenes manifest
        - Patch template makefile to include assets_autogen.mk
        - Write an autorun main.c so the project is immediately buildable
        """
        if not self._project_dir or not isinstance(self._data, dict):
            return

        scenes = self._data.get("scenes", []) or []
        if not isinstance(scenes, list) or not scenes:
            QMessageBox.information(self, tr("proj.export_template_ready"), tr("proj.export_no_scenes"))
            return

        # Prefer a fixed default export dir for template builds (stable includes).
        if not str(self._data.get("export_dir") or "").strip():
            self._data["export_dir"] = default_export_dir_rel(self._data)
            self._refresh_export_dir_ui()

        dlg = ExportOptionsDialog(self, title=tr("proj.export_template_ready"), allow_scope=True)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        opts = dlg.options()
        self._commit_current_scene_export_flags(self._current_scene())

        pf_scenes = self._template_preflight_scenes(str(opts.scope or "all"))
        pf_issues = collect_template_2026_issues(
            project_data=self._data,
            project_dir=self._project_dir,
            scenes=pf_scenes,
        )
        if pf_issues:
            report = format_template_2026_report(pf_issues)
            answer = QMessageBox.warning(
                self,
                tr("proj.template_preflight_title"),
                tr("proj.template_preflight_found", n=len(pf_issues), details=report),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                QMessageBox.information(
                    self,
                    tr("proj.export_template_ready"),
                    tr("proj.template_preflight_cancelled"),
                )
                return

        if opts.scope == "current":
            if not self._current_scene():
                QMessageBox.information(self, tr("proj.export_template_ready"), tr("proj.export_need_scene"))
                return
            self._export_scene_c(options=opts, show_msg=True)
        else:
            self._export_all_scenes_c(options=opts)

        tpl = detect_template_root(project_dir=self._project_dir, project_data=self._data)
        if tpl is None:
            picked = QFileDialog.getExistingDirectory(self, tr("proj.template_dir_title"), str(self._project_dir))
            if not picked:
                QMessageBox.information(self, tr("proj.export_template_ready"), tr("proj.template_dir_missing"))
                return
            tpl = Path(picked)
            self._data["template_dir"] = str(tpl)

        export_dir_rel = str(self._data.get("export_dir") or "").replace("\\", "/").strip()

        # Choose start scene
        game = self._data.get("game", {}) if isinstance(self._data, dict) else {}
        start_label = str(game.get("start_scene") or "").strip() if isinstance(game, dict) else ""
        if not start_label:
            s0 = scenes[0] if scenes else {}
            if isinstance(s0, dict):
                start_label = str(s0.get("label") or s0.get("id") or "scene")
            else:
                start_label = "scene"
        start_safe = safe_ident(start_label)

        # Audio helper counts + default sound policy (loaded assets => sound on by default).
        _, song_count, sfx_count = resolve_project_audio_state(
            self._data,
            project_dir=self._project_dir,
            audio_manifest=self._audio_manifest,
        )

        # Collect all player sprites across all scenes (for actor integration)
        _re_safe_ident = __import__("re").compile(r"[^0-9a-zA-Z_]+")
        def _safe(s: str) -> str:
            s = (_re_safe_ident.sub("_", s or "")).strip("_")
            return ("_" + s) if s and s[0].isdigit() else (s or "sprite")
        player_sprites: list[dict] = []
        for _sc in (self._data.get("scenes") or []):
            for _spr in (_sc.get("sprites") or []):
                _ctrl = _spr.get("ctrl") or {}
                if sprite_gameplay_role(_spr) == "player":
                    _hb0 = first_hurtbox(_spr, int(_spr.get("frame_w", 8) or 8), int(_spr.get("frame_h", 8) or 8))
                    _hb_enabled = box_enabled(_hb0, True)
                    _body0 = first_bodybox(_spr, int(_spr.get("frame_w", 8) or 8), int(_spr.get("frame_h", 8) or 8))
                    _body_enabled = box_enabled(_body0, True)
                    _body_x = int(_body0.get("x", 0) or 0)
                    _body_y = int(_body0.get("y", 0) or 0)
                    _body_w = int((_body0.get("w", _spr.get("frame_w", 8)) if _body_enabled else 0) or 0)
                    _body_h = int((_body0.get("h", _spr.get("frame_h", 8)) if _body_enabled else 0) or 0)
                    _n = _safe(sprite_type_name(_spr))
                    if _n and not any(p["name"] == _n for p in player_sprites):
                        player_sprites.append({
                            "name": _n,
                            "ctrl": _ctrl,
                            "props": _spr.get("props") or {},
                            "anims": _spr.get("anims") or {},
                            "frame_count": int(_spr.get("frame_count", 1) or 1),
                            "anim_duration": int(_spr.get("anim_duration", 6) or 6),
                            "frame_w": int(_spr.get("frame_w", 8) or 8),
                            "frame_h": int(_spr.get("frame_h", 8) or 8),
                            "hb_x": int(_hb0.get("x", 0) or 0),
                            "hb_y": int(_hb0.get("y", 0) or 0),
                            "hb_w": int((_hb0.get("w", _spr.get("frame_w", 8)) if _hb_enabled else 0) or 0),
                            "hb_h": int((_hb0.get("h", _spr.get("frame_h", 8)) if _hb_enabled else 0) or 0),
                            "body_x": _body_x,
                            "body_y": _body_y,
                            "body_w": _body_w,
                            "body_h": _body_h,
                        })

        _export_dir_abs_mk = (Path(tpl) / export_dir_rel) if export_dir_rel else Path(tpl)
        _feat = _detect_features(self._data or {})
        changed_mk, mk_msg = patch_makefile_for_autogen(
            template_root=tpl,
            export_dir_rel=export_dir_rel,
            enable_autorun=True,
            has_player_actors=False,
            player_slot_count=compute_player_total_slots(player_sprites, _export_dir_abs_mk),
            has_sound=(song_count > 0 or sfx_count > 0),
            song_count=song_count,
            has_enemy=_feat.get("has_enemy", False),
            has_fx=_feat.get("has_fx", False),
            has_prop_actor=_feat.get("has_prop_actor", False),
            has_combat=_feat.get("has_combat", False),
            has_triggers=_feat.get("has_triggers", False),
            has_player=_feat.get("has_player", False),
            has_hud=_feat.get("has_hud", False),
            has_waves=_feat.get("has_waves", False),
            has_ladder=_feat.get("has_ladder", False),
            has_spring=_feat.get("has_spring", False),
            has_door=_feat.get("has_door", False),
            has_ice=_feat.get("has_ice", False),
            has_conveyor=_feat.get("has_conveyor", False),
            has_deadly_tile=_feat.get("has_deadly_tile", False),
            has_water=_feat.get("has_water", False),
            has_topdown_physics=_feat.get("has_topdown_physics", False),
            has_platform_physics=_feat.get("has_platform_physics", False),
            project_data=self._data,
        )

        try:
            main_path = write_autorun_main_c(
                template_root=tpl,
                export_dir_rel=export_dir_rel,
                start_scene_safe=start_safe,
                song_count=song_count,
                sfx_count=sfx_count,
                player_sprites=player_sprites if player_sprites else None,
                project_data=self._data,
            )
        except Exception as e:
            QMessageBox.warning(self, tr("proj.export_template_ready"), tr("proj.template_autorun_failed", err=str(e)))
            return

        if self._on_save:
            self._on_save()

        msg = tr("proj.template_ready_done", mk=mk_msg, main=str(main_path))
        if not changed_mk:
            msg += "\n" + tr("proj.template_ready_no_mk_change")
        QMessageBox.information(self, tr("proj.export_template_ready"), msg)

    # ------------------------------------------------------------------
    # Batch color replace (H)
    # ------------------------------------------------------------------

    def _batch_color_replace(self) -> None:
        scene = self._current_scene()
        if not scene:
            return
        sprites = scene.get("sprites") or []
        from ui.batch_color_replace_dialog import BatchColorReplaceDialog
        dlg = BatchColorReplaceDialog(sprites, self._project_dir, self)
        dlg.exec()
        # PNGs were saved in-place — if auto-reload is active in palette_tab it
        # will pick up the changes automatically via QFileSystemWatcher.

    def _find_tilemap_script(self) -> Path | None:
        repo_root = Path(__file__).resolve().parents[2]
        return find_script(
            "tilemap_script_path",
            default_candidates(repo_root, "ngpc_tilemap.py"),
        )

    def _tilemap_export_paths(self, path: Path, export_dir: Path | None = None) -> tuple[Path, Path | None, Path]:
        """
        Return (scr1_path, scr2_path_or_none, out_c_path) for a tilemap export.

        If a *_scr1.png + *_scr2.png pair exists, prefer exporting SCR1 explicitly
        and pass SCR2 via --scr2. Also normalizes the output base name by
        stripping a trailing _scr1/_scr2 suffix so we generate bg_map.c instead
        of bg_scr1_map.c.
        """
        from core.scene_loader_gen import _tilemap_symbol_base

        p = Path(path)
        stem_l = p.stem.lower()

        scr1 = p
        scr2: Path | None = None

        if stem_l.endswith("_scr1"):
            base = p.stem[:-5]
            cand = p.with_name(base + "_scr2" + p.suffix)
            if cand.exists():
                scr2 = cand
        elif stem_l.endswith("_scr2"):
            base = p.stem[:-5]
            cand1 = p.with_name(base + "_scr1" + p.suffix)
            if cand1.exists():
                scr1 = cand1
                scr2 = p
        else:
            cand1 = p.with_name(p.stem + "_scr1" + p.suffix)
            cand2 = p.with_name(p.stem + "_scr2" + p.suffix)
            if cand1.exists() and cand2.exists():
                scr1, scr2 = cand1, cand2
            else:
                cand = p.with_name(p.stem + "_scr2" + p.suffix)
                if cand.exists():
                    scr2 = cand

        out_base = _tilemap_symbol_base(scr1)
        out_c = (Path(export_dir) / (out_base + "_map.c")) if export_dir else scr1.with_name(out_base + "_map.c")
        return scr1, scr2, out_c

    def _export_scene_tilemaps_c(self) -> None: 
        scene = self._current_scene() 
        if not scene: 
            return 
        script = self._find_tilemap_script() 
        if script is None: 
            start = script_dialog_start_dir("tilemap_script_path", fallback=self._project_dir)
            p, _ = QFileDialog.getOpenFileName(self, tr("tilemap.find_script"), start, "Python (*.py)") 
            if not p: 
                return 
            script = Path(p) 
            remember_script_path("tilemap_script_path", script)

        n, errs = 0, [] 
        exp_dir = self._export_dir_abs()
        for tm, path in self._scene_tilemaps(scene): 
            if not path.exists(): 
                errs.append(f"? {path.name}") 
                continue 
            try: 
                if exp_dir:
                    try:
                        exp_dir.mkdir(parents=True, exist_ok=True)
                    except Exception:
                        pass
                scr1, scr2, out_c = self._tilemap_export_paths(path, export_dir=exp_dir)
                cmd = [_sys.executable, str(script), str(scr1), "-o", str(out_c)]
                out_name = out_c.stem
                if out_name.lower().endswith("_map"):
                    out_name = out_name[:-4]
                if out_name:
                    cmd += ["-n", out_name]
                if scr2 is not None and scr2.exists():
                    cmd += ["--scr2", str(scr2)]
                cmd += ["--header"]
                res = subprocess.run(
                    cmd,
                    capture_output=True, text=True, 
                    cwd=str(scr1.parent), timeout=60, 
                ) 
                if res.returncode == 0: 
                    n += 1 
                else: 
                    errs.append(f"{path.name}: code {res.returncode}") 
            except Exception as e: 
                errs.append(f"{path.name}: {e}") 

        mk_path = self._maybe_write_assets_autogen_mk(exp_dir, errs)
        constants_h = self._maybe_write_constants_h(exp_dir, errs)
        game_vars_h = self._maybe_write_game_vars_h(exp_dir, errs)
        entity_types_h = self._maybe_write_entity_types_h(exp_dir, errs)
        self._run_globals_validation(errs)
        msg = tr("proj.export_done", n=n)
        if mk_path:
            msg += "\n" + tr("proj.autogen_mk_written", path=self._rel(mk_path))
        if constants_h:
            msg += "\n" + tr("proj.constants_written", path=self._rel(constants_h))
        if game_vars_h:
            msg += "\n" + tr("proj.gamevars_written", path=self._rel(game_vars_h))
        if entity_types_h:
            msg += "\n" + tr("proj.entity_types_written", path=self._rel(entity_types_h))
        if errs:
            msg += "\n" + "\n".join(errs[:6])
        QMessageBox.information(self, tr("proj.export_scene_tilemaps_c"), msg)

    def _export_all_palettes_c(self) -> None:
        n, errs = 0, []
        for spr, path in self._all_sprites():
            if not path.exists():
                errs.append(f"? {path.name}")
                continue
            try:
                data = load_sprite(path)
                name = path.stem
                lines = [
                    f"/* {name} palette — RGB444 (NGPC) */\n",
                    f"const u16 {name}_pal[{len(data.palette)}] = {{\n",
                ]
                for i, color in enumerate(data.palette):
                    word = to_word(*color)
                    sep = "," if i < len(data.palette) - 1 else " "
                    cmt = "/* transparent */" if i == 0 else f"/* #{color[0]:02X}{color[1]:02X}{color[2]:02X} */"
                    lines.append(f"    0x{word:04X}u{sep}  {cmt}\n")
                lines.append("};\n")
                path.with_name(name + "_pal.c").write_text("".join(lines), encoding="utf-8")
                n += 1
            except Exception as e:
                errs.append(f"{path.name}: {e}")
        msg = tr("proj.export_pals_done", n=n)
        if errs:
            msg += "\n" + "\n".join(errs[:6])
        QMessageBox.information(self, tr("proj.export_pals_c"), msg)

    def _export_report_html(self) -> None: 
        if self._is_free_mode: 
            return 
        default = str((self._project_dir / "ngpcraft_engine_report.html") if self._project_dir else "ngpcraft_engine_report.html") 
        path, _ = QFileDialog.getSaveFileName( 
            self, 
            tr("proj.report_html"), 
            default, 
            "HTML (*.html)", 
        ) 
        if not path:
            return
        try:
            html = build_report_html(self._data, self._project_path)
            Path(path).write_text(html, encoding="utf-8")
            QMessageBox.information(self, tr("proj.report_html"), tr("proj.report_saved", path=path))
        except Exception as e:
            QMessageBox.warning(self, tr("proj.report_html"), tr("proj.report_fail", err=str(e)))

    def _copy_starter_kit(self) -> None:
        """Copy bundled starter-kit assets to a user-chosen directory."""
        kit_dir = Path(__file__).resolve().parents[2] / "assets" / "starter_kit"
        if not kit_dir.is_dir():
            QMessageBox.warning(self, tr("proj.copy_starter_kit"), tr("proj.starter_kit_missing"))
            return
        # Default destination: project GraphX dir if available, else home
        default_dest = str(self._export_dir_abs() or Path.home())
        dest = QFileDialog.getExistingDirectory(
            self, tr("proj.copy_starter_kit"), default_dest
        )
        if not dest:
            return
        dest_path = Path(dest)
        copied, skipped = 0, 0
        for src in kit_dir.iterdir():
            if not src.is_file():
                continue
            tgt = dest_path / src.name
            if tgt.exists():
                skipped += 1
                continue
            shutil.copy2(src, tgt)
            copied += 1
        QMessageBox.information(
            self,
            tr("proj.copy_starter_kit"),
            tr("proj.starter_kit_done", copied=copied, skipped=skipped, dest=dest),
        )

    def _export_report_pdf(self) -> None:
        if self._is_free_mode:
            return
        default = str((self._project_dir / "ngpcraft_engine_report.pdf") if self._project_dir else "ngpcraft_engine_report.pdf")
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("proj.report_pdf"),
            default,
            "PDF (*.pdf)",
        )
        if not path:
            return
        try:
            html = build_report_html(self._data, self._project_path)
            doc = QTextDocument()
            doc.setHtml(html)
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(path)
            doc.print(printer)
            QMessageBox.information(self, tr("proj.report_pdf"), tr("proj.report_saved", path=path))
        except Exception as e:
            QMessageBox.warning(self, tr("proj.report_pdf"), tr("proj.report_fail", err=str(e)))
