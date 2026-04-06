"""
ui/tabs/bundle_tab.py - Scene sprite packer (Phase 3c).

This tab is the UI equivalent of a per-scene "bundle":
- It operates on the active scene sprite list (single source of truth).
- It computes cascading tile_base / pal_base for the scene.
- It batch-exports sprites in order using ngpc_sprite_export.py.
"""
from __future__ import annotations

import subprocess
import sys as _sys
import tempfile
from pathlib import Path
from typing import Callable

from PIL import Image
from PyQt6.QtCore import Qt, QSettings, QSize, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QSizePolicy, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.project_model import TILE_MAX, PAL_MAX_SPR, sprite_export_stats, sprite_tile_estimate
from i18n.lang import tr
from ui.context_help import ContextHelpBox
from ui.tool_finder import default_candidates, find_script, script_dialog_start_dir, remember_script_path
from ui.tabs._project_path_mixin import ProjectPathMixin


# ---------------------------------------------------------------------------
# Helper: sprite configuration dialog (same pattern as ProjectTab)
# ---------------------------------------------------------------------------

class _BundleSpriteDialog(QDialog):
    """Small dialog used to configure frame geometry for a bundled sprite sheet."""

    def __init__(self, png_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("bundle.sprite_title"))
        try:
            img = Image.open(png_path)
            pw, ph = img.size
        except Exception:
            pw, ph = 8, 8
        self._png_h = ph

        form = QFormLayout(self)

        self._fw = QSpinBox()
        self._fw.setRange(1, pw)
        self._fw.setValue(min(pw, 16) if pw <= 32 else 8)
        self._fw.setSingleStep(8)
        form.addRow(tr("proj.frame_w_label"), self._fw)

        self._fh = QSpinBox()
        self._fh.setRange(1, ph)
        self._fh.setValue(min(ph, 16) if ph <= 32 else 8)
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
# Helper: drag&drop reorder table
# ---------------------------------------------------------------------------

class _ReorderTableWidget(QTableWidget):
    """Table widget that forwards drag-reorder events to the bundle controller."""

    def __init__(self, on_move_row: Callable[[int, int], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_move_row = on_move_row

    def dropEvent(self, event) -> None:  # type: ignore[override]
        try:
            from_row = int(self.currentRow())
            if from_row < 0:
                event.ignore()
                return

            pos = event.position().toPoint()  # Qt6: QPointF -> QPoint
            to_row = int(self.rowAt(pos.y()))
            if to_row < 0:
                to_row = int(self.rowCount())  # drop below last -> end

            self._on_move_row(from_row, to_row)
            event.acceptProposedAction()
        except Exception:
            super().dropEvent(event)


# ---------------------------------------------------------------------------
# BundleTab
# ---------------------------------------------------------------------------

_COL_NUM       = 0
_COL_ICON      = 1
_COL_FILE      = 2
_COL_FW        = 3
_COL_FH        = 4
_COL_FRAMES    = 5
_COL_REUSE     = 6
_COL_TILES     = 7
_COL_TILE_BASE = 8
_COL_PAL_BASE  = 9
_N_COLS        = 10


class BundleTab(ProjectPathMixin, QWidget):
    """
    Scene sprite packer.

    Uses the active scene sprite list as the single source of truth.
    Path helpers (_project_dir, _rel, _abs) come from ProjectPathMixin.
    """
 
    open_sprite_in_palette = pyqtSignal(object)  # dict payload
    scene_changed = pyqtSignal(object)  # dict payload (scene) for cross-tab refresh
 
    def __init__( 
        self, 
        project_data: dict, 
        project_path: Path | None, 
        on_save: Callable,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._data = project_data
        self._project_path = project_path
        self._on_save_fn = on_save
        bundle = (self._data.get("bundle") or {}) if isinstance(self._data, dict) else {}
        try:
            self._default_tile_base = int(bundle.get("tile_base", 256))
        except Exception:
            self._default_tile_base = 256
        try:
            self._default_pal_base = int(bundle.get("pal_base", 0))
        except Exception:
            self._default_pal_base = 0
        self._populating = False
        self._scene: dict | None = None
        self._base_dir: Path | None = None
        self._build_ui()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_script(self) -> Path | None:
        repo_root = Path(__file__).resolve().parents[2]
        return find_script(
            "export_script_path",
            default_candidates(repo_root, "ngpc_sprite_export.py"),
        )

    def _scene_sprites(self) -> list[dict]:
        if not self._scene:
            return []
        sprites = self._scene.get("sprites")
        if not isinstance(sprites, list):
            sprites = []
            self._scene["sprites"] = sprites
        out: list[dict] = []
        for s in sprites:
            if isinstance(s, dict):
                out.append(s)
        if len(out) != len(sprites):
            self._scene["sprites"] = out
        return out

    def _scene_start_bases(self) -> tuple[int, int]:
        if not self._scene:
            return self._default_tile_base, self._default_pal_base

        tb = self._scene.get("spr_tile_base")
        pb = self._scene.get("spr_pal_base")
        try:
            tile_base = int(tb) if tb is not None else int(self._default_tile_base)
        except Exception:
            tile_base = int(self._default_tile_base)
        try:
            pal_base = int(pb) if pb is not None else int(self._default_pal_base)
        except Exception:
            pal_base = int(self._default_pal_base)
        return tile_base, pal_base

    def _emit_scene_changed(self) -> None:
        if self._scene:
            self.scene_changed.emit(self._scene)

    def _save_and_notify(self) -> None:
        """Persist project data and broadcast the scene change to other tabs."""
        self._save_and_notify()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(6)

        self._ctx_bundle = ContextHelpBox(
            tr("bundle.ctx_workflow_title"),
            tr("bundle.ctx_workflow_body"),
            self,
        )
        root.addWidget(self._ctx_bundle)

        # Top: scene + start values + Add button
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("bundle.scene_label")))
        self._scene_lbl = QLabel(tr("bundle.scene_none"))
        self._scene_lbl.setStyleSheet("color: gray; font-style: italic;")
        top.addWidget(self._scene_lbl, 1)
        top.addSpacing(10)

        top.addWidget(QLabel(tr("bundle.tile_base")))
        self._sb_tile_base = QSpinBox()
        self._sb_tile_base.setRange(128, 511)
        self._sb_tile_base.setValue(self._default_tile_base)
        self._sb_tile_base.setToolTip(tr("bundle.tile_base_tt"))
        self._sb_tile_base.valueChanged.connect(self._on_start_changed)
        self._sb_tile_base.setEnabled(False)
        top.addWidget(self._sb_tile_base)
        top.addSpacing(20)

        top.addWidget(QLabel(tr("bundle.pal_base")))
        self._sb_pal_base = QSpinBox()
        self._sb_pal_base.setRange(0, 15)
        self._sb_pal_base.setValue(self._default_pal_base)
        self._sb_pal_base.setToolTip(tr("bundle.pal_base_tt"))
        self._sb_pal_base.valueChanged.connect(self._on_start_changed)
        self._sb_pal_base.setEnabled(False)
        top.addWidget(self._sb_pal_base)
        top.addStretch()

        self._btn_add = QPushButton(tr("bundle.add"))
        self._btn_add.clicked.connect(self._add_entry)
        self._btn_add.setEnabled(False)
        top.addWidget(self._btn_add)
        root.addLayout(top)

        # Table
        self._table = _ReorderTableWidget(self._move_row_to)
        self._table.setColumnCount(_N_COLS)
        self._table.setHorizontalHeaderLabels([
            tr("bundle.col_num"),
            tr("bundle.col_icon"),
            tr("bundle.col_file"),
            tr("bundle.col_fw"),
            tr("bundle.col_fh"),
            tr("bundle.col_frames"),
            tr("bundle.col_reuse"),
            tr("bundle.col_tiles"),
            tr("bundle.col_tile_base"),
            tr("bundle.col_pal_base"),
        ])
        # Column header tooltips
        _col_tips = [
            "",
            tr("bundle.col_icon_tt"),
            tr("bundle.col_file_tt"),
            tr("bundle.col_fw_tt"),
            tr("bundle.col_fh_tt"),
            tr("bundle.col_frames_tt"),
            tr("bundle.col_reuse_tt"),
            tr("bundle.col_tiles_tt"),
            tr("bundle.col_tile_base_tt"),
            tr("bundle.col_pal_base_tt"),
        ]
        for col, tip in enumerate(_col_tips): 
            if tip: 
                self._table.horizontalHeaderItem(col).setToolTip(tip) 
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows) 
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers) 
        self._table.setAlternatingRowColors(True) 
        self._table.horizontalHeader().setStretchLastSection(False) 
        self._table.setDragEnabled(True)
        self._table.setAcceptDrops(True)
        self._table.setDropIndicatorShown(True)
        self._table.setDragDropOverwriteMode(False)
        self._table.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._table.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._table.setIconSize(QSize(32, 32))
        self._table.setToolTip(tr("bundle.table_tt"))
        self._table.setColumnWidth(_COL_ICON, 42)
        self._table.cellDoubleClicked.connect(self._open_row_in_palette)
        self._table.itemSelectionChanged.connect(self._update_open_palette_button)
        root.addWidget(self._table, 1) 
 
        # Row action buttons 
        btn_row = QHBoxLayout() 
        self._btn_up = QPushButton(tr("bundle.move_up")) 
        self._btn_up.clicked.connect(self._move_up) 
        self._btn_up.setEnabled(False)
        btn_row.addWidget(self._btn_up) 
        self._btn_down = QPushButton(tr("bundle.move_down")) 
        self._btn_down.clicked.connect(self._move_down) 
        self._btn_down.setEnabled(False)
        btn_row.addWidget(self._btn_down) 
        self._btn_open_pal = QPushButton(tr("bundle.open_palette"))
        self._btn_open_pal.clicked.connect(lambda: self._open_row_in_palette(self._table.currentRow(), _COL_FILE))
        self._btn_open_pal.setEnabled(False)
        btn_row.addWidget(self._btn_open_pal)
        self._btn_rm = QPushButton(tr("bundle.remove")) 
        self._btn_rm.clicked.connect(self._remove_entry) 
        self._btn_rm.setEnabled(False)
        btn_row.addWidget(self._btn_rm) 
        btn_row.addStretch() 
        root.addLayout(btn_row) 

        # Budget
        self._budget_lbl = QLabel("")
        self._budget_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        root.addWidget(self._budget_lbl)

        # Export + Save
        exp_row = QHBoxLayout()
        self._btn_export = QPushButton(tr("bundle.export"))
        self._btn_export.clicked.connect(self._export_all)
        self._btn_export.setEnabled(False)
        exp_row.addWidget(self._btn_export)
        btn_save_cfg = QPushButton(tr("bundle.save"))
        btn_save_cfg.clicked.connect(self._on_save_fn)
        exp_row.addWidget(btn_save_cfg)
        exp_row.addStretch()
        root.addLayout(exp_row)

        # Log
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(120)
        self._log.setPlaceholderText(tr("bundle.log_ph"))
        root.addWidget(self._log)

        self._populate()

    # ------------------------------------------------------------------
    # Scene
    # ------------------------------------------------------------------

    def set_scene(self, scene: dict | None, base_dir: Path | None) -> None:
        """Called by MainWindow when the active scene changes."""
        self._scene = scene
        self._base_dir = base_dir

        if not scene:
            self._scene_lbl.setText(tr("bundle.scene_none"))
            self._scene_lbl.setStyleSheet("color: gray; font-style: italic;")
            for w in (
                self._sb_tile_base, self._sb_pal_base,
                self._btn_add, self._btn_up, self._btn_down, self._btn_rm, self._btn_export,
            ):
                w.setEnabled(False)
            self._table.setRowCount(0)
            self._budget_lbl.setText("")
            self._update_open_palette_button()
            return

        self._scene_lbl.setText(scene.get("label", "?"))
        self._scene_lbl.setStyleSheet("")
        for w in (self._sb_tile_base, self._sb_pal_base, self._btn_add, self._btn_export):
            w.setEnabled(True)

        tile_base, pal_base = self._scene_start_bases()
        self._populating = True
        try:
            self._sb_tile_base.setValue(int(tile_base))
            self._sb_pal_base.setValue(int(pal_base))
        finally:
            self._populating = False

        self._populate()

    # ------------------------------------------------------------------
    # Table populate / refresh
    # ------------------------------------------------------------------

    def _populate(self) -> None: 
        self._populating = True 
        self._table.setRowCount(0) 
        if not self._scene:
            self._budget_lbl.setText("")
            self._update_open_palette_button()
            self._populating = False
            return

        sprites = self._scene_sprites()
        t_cursor = int(self._sb_tile_base.value())
        p_cursor = int(self._sb_pal_base.value())
        fixed_to_slot: dict[str, int] = {}

        for i, spr in enumerate(sprites):
            rel = (spr.get("file") or "").strip()
            p = self._abs(rel) if rel else None

            fw = int(spr.get("frame_w", 8) or 8)
            fh = int(spr.get("frame_h", 8) or 8)
            fc = int(spr.get("frame_count", 1) or 1)
            fc_use = None if fc <= 0 else fc
            fixed = str(spr.get("fixed_palette") or "").strip()

            if p is None or not p.exists():
                tiles, pal_n, est = sprite_tile_estimate(spr), 1, True
            else:
                tiles, pal_n, est = sprite_export_stats(self._base_dir, p, fw, fh, fc_use, fixed)

            auto_share = bool(fixed) and int(pal_n) == 1 and fixed in fixed_to_slot
            pal_base = fixed_to_slot[fixed] if auto_share else p_cursor
            self._insert_row(i, spr, t_cursor, pal_base, int(tiles), bool(est))

            t_cursor += int(tiles)
            if bool(fixed) and int(pal_n) == 1:
                if auto_share:
                    pass
                else:
                    fixed_to_slot[fixed] = int(pal_base)
                    p_cursor += int(pal_n)
            else:
                p_cursor += int(pal_n)

        self._table.resizeColumnToContents(_COL_FILE) 
        self._update_budget() 
        self._update_open_palette_button()
        has_any = len(sprites) > 0
        self._btn_rm.setEnabled(has_any)
        self._btn_up.setEnabled(has_any)
        self._btn_down.setEnabled(has_any)
        self._populating = False 

    def _update_open_palette_button(self) -> None:
        try:
            self._btn_open_pal.setEnabled(self._table.currentRow() >= 0)
        except Exception:
            pass

    def _open_row_in_palette(self, row: int, _col: int) -> None:
        sprites = self._scene_sprites()
        if not (0 <= row < len(sprites)):
            return
        spr = sprites[row] or {}
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

    def _insert_row(
        self, row: int, spr: dict, t_base: int, p_base: int, tiles: int, is_estimated: bool
    ) -> None:
        self._table.insertRow(row)
        try:
            self._table.setRowHeight(row, 36)
        except Exception:
            pass

        # Col 0: row number (read-only)
        self._set_ro(row, _COL_NUM, str(row + 1))

        # Col 1: icon preview
        icon_item = QTableWidgetItem("")
        icon_item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsDropEnabled
        )
        rel = (spr.get("file") or "").strip()
        if rel:
            p = self._abs(rel)
            if p.exists():
                pm = QPixmap(str(p))
                if not pm.isNull():
                    pm = pm.scaled(
                        32, 32,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    icon_item.setIcon(QIcon(pm))
        self._table.setItem(row, _COL_ICON, icon_item)

        # Col 2: file name (read-only)
        self._set_ro(row, _COL_FILE, Path(spr.get("file", "")).name)

        # Col 3: frame_w
        sb_fw = QSpinBox()
        sb_fw.setRange(1, 160)
        sb_fw.setValue(int(spr.get("frame_w", 8) or 8))
        sb_fw.setSingleStep(8)
        sb_fw.valueChanged.connect(lambda v, r=row: self._on_spinbox(r, "frame_w", v))
        self._table.setCellWidget(row, _COL_FW, sb_fw)

        # Col 4: frame_h
        sb_fh = QSpinBox()
        sb_fh.setRange(1, 160)
        sb_fh.setValue(int(spr.get("frame_h", 8) or 8))
        sb_fh.setSingleStep(8)
        sb_fh.valueChanged.connect(lambda v, r=row: self._on_spinbox(r, "frame_h", v))
        self._table.setCellWidget(row, _COL_FH, sb_fh)

        # Col 5: frame_count
        sb_fc = QSpinBox()
        sb_fc.setRange(1, 256)
        sb_fc.setValue(int(spr.get("frame_count", 1) or 1))
        sb_fc.valueChanged.connect(lambda v, r=row: self._on_spinbox(r, "frame_count", v))
        self._table.setCellWidget(row, _COL_FRAMES, sb_fc)

        # Col 6: reuse_palette (centered checkbox)
        container = QWidget()
        cl = QHBoxLayout(container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chk = QCheckBox()
        chk.setChecked(bool(spr.get("reuse_palette", False)))
        chk.setToolTip(tr("bundle.reuse_tt"))
        chk.stateChanged.connect(
            lambda state, r=row: self._on_reuse(r, state != 0)
        )
        cl.addWidget(chk)
        self._table.setCellWidget(row, _COL_REUSE, container)

        # Cols 7-9: calculated read-only
        self._set_ro(row, _COL_TILES, ("~" if is_estimated else "") + str(tiles))
        self._set_ro(row, _COL_TILE_BASE, str(t_base))
        self._set_ro(row, _COL_PAL_BASE, str(p_base))

    def _set_ro(self, row: int, col: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsDropEnabled
        )
        self._table.setItem(row, col, item)

    def _recalculate_cols(self) -> None:
        """Update read-only columns without recreating cell widgets."""
        if not self._scene:
            return

        sprites = self._scene_sprites()
        t_cursor = int(self._sb_tile_base.value())
        p_cursor = int(self._sb_pal_base.value())
        fixed_to_slot: dict[str, int] = {}

        for i, spr in enumerate(sprites):
            rel = (spr.get("file") or "").strip()
            p = self._abs(rel) if rel else None
            fw = int(spr.get("frame_w", 8) or 8)
            fh = int(spr.get("frame_h", 8) or 8)
            fc = int(spr.get("frame_count", 1) or 1)
            fc_use = None if fc <= 0 else fc
            fixed = str(spr.get("fixed_palette") or "").strip()

            if p is None or not p.exists():
                tiles, pal_n, est = sprite_tile_estimate(spr), 1, True
            else:
                tiles, pal_n, est = sprite_export_stats(self._base_dir, p, fw, fh, fc_use, fixed)

            auto_share = bool(fixed) and int(pal_n) == 1 and fixed in fixed_to_slot
            pal_base = fixed_to_slot[fixed] if auto_share else p_cursor
            tiles_txt = ("~" if est else "") + str(int(tiles))
            # Row number
            item0 = self._table.item(i, _COL_NUM)
            if item0:
                item0.setText(str(i + 1))
            # Calculated cols
            for col, val in [
                (_COL_TILES, tiles_txt),
                (_COL_TILE_BASE, str(t_cursor)),
                (_COL_PAL_BASE, str(pal_base)),
            ]:
                item = self._table.item(i, col)
                if item:
                    item.setText(val)
                else:
                    self._set_ro(i, col, val)

            t_cursor += int(tiles)
            if bool(fixed) and int(pal_n) == 1:
                if auto_share:
                    pass
                else:
                    fixed_to_slot[fixed] = int(pal_base)
                    p_cursor += int(pal_n)
            else:
                p_cursor += int(pal_n)
        self._update_budget()

    def _update_budget(self) -> None:
        if not self._scene:
            self._budget_lbl.setText("")
            return

        sprites = self._scene_sprites()
        t_cursor = int(self._sb_tile_base.value())
        p_cursor = int(self._sb_pal_base.value())
        fixed_to_slot: dict[str, int] = {}

        for spr in sprites:
            rel = (spr.get("file") or "").strip()
            p = self._abs(rel) if rel else None
            fw = int(spr.get("frame_w", 8) or 8)
            fh = int(spr.get("frame_h", 8) or 8)
            fc = int(spr.get("frame_count", 1) or 1)
            fc_use = None if fc <= 0 else fc
            fixed = str(spr.get("fixed_palette") or "").strip()

            if p is None or not p.exists():
                tiles, pal_n = sprite_tile_estimate(spr), 1
            else:
                tiles, pal_n, _est = sprite_export_stats(self._base_dir, p, fw, fh, fc_use, fixed)

            t_cursor += int(tiles)
            if bool(fixed) and int(pal_n) == 1:
                if fixed in fixed_to_slot:
                    pass
                else:
                    fixed_to_slot[fixed] = int(p_cursor)
                    p_cursor += int(pal_n)
            else:
                p_cursor += int(pal_n)

        t_used = t_cursor
        p_used = p_cursor
        ok = tr("proj.budget_ok") if t_used <= TILE_MAX and p_used <= PAL_MAX_SPR else tr("proj.budget_warn")
        self._budget_lbl.setText(tr("bundle.budget", tiles=t_used, pals=p_used, ok=ok))

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_start_changed(self) -> None:
        if self._populating:
            return
        if not self._scene:
            return
        self._scene["spr_tile_base"] = int(self._sb_tile_base.value())
        self._scene["spr_pal_base"] = int(self._sb_pal_base.value())
        self._recalculate_cols()
        self._save_and_notify()

    def _on_spinbox(self, row: int, field: str, value: int) -> None:
        if self._populating:
            return
        sprites = self._scene_sprites()
        if 0 <= row < len(sprites):
            sprites[row][field] = int(value)
            self._recalculate_cols()
            self._on_save_fn()
            self._emit_scene_changed()

    def _on_reuse(self, row: int, checked: bool) -> None:
        if self._populating:
            return
        sprites = self._scene_sprites()
        if 0 <= row < len(sprites):
            sprites[row]["reuse_palette"] = bool(checked)
            self._recalculate_cols()
            self._on_save_fn()
            self._emit_scene_changed()

    # ------------------------------------------------------------------
    # Entry CRUD
    # ------------------------------------------------------------------

    def _current_row(self) -> int:
        items = self._table.selectedItems()
        if items:
            return items[0].row()
        return self._table.currentRow()

    def _add_entry(self) -> None:
        if not self._scene:
            return
        settings = QSettings("NGPCraft", "Engine")
        start = (settings.value("bundle/last_dir", "", str) or "").strip()
        if not start:
            start = str(self._project_dir or "")
        path, _ = QFileDialog.getOpenFileName(
            self, tr("bundle.add"), start,
            "PNG (*.png);;All images (*.png *.bmp *.gif)",
        )
        if not path:
            return
        p = Path(path)
        try:
            settings.setValue("bundle/last_dir", str(p.parent))
        except Exception:
            pass
        dlg = _BundleSpriteDialog(p, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        sprites = self._scene_sprites()
        rel = self._rel(p)
        if any((s.get("file") or "") == rel for s in sprites):
            try:
                self._log.appendPlainText(tr("bundle.dup_skip", file=Path(rel).name))
            except Exception:
                pass
            return

        sprites.append({
            "name": p.stem,
            "file": rel,
            "frame_w": dlg.frame_w,
            "frame_h": dlg.frame_h,
            "frame_count": dlg.frame_count,
            "reuse_palette": False,
            "fixed_palette": None,
        })
        self._save_and_notify()
        self._populate()
        self._table.selectRow(len(sprites) - 1)

    def _remove_entry(self) -> None:
        if not self._scene:
            return
        row = self._current_row()
        sprites = self._scene_sprites()
        if 0 <= row < len(sprites):
            sprites.pop(row)
            self._on_save_fn()
            self._emit_scene_changed()
            self._populate()
            self._table.selectRow(min(row, len(sprites) - 1))

    def _move_up(self) -> None:
        if not self._scene:
            return
        row = self._current_row()
        entries = self._scene_sprites()
        if row > 0:
            entries[row], entries[row - 1] = entries[row - 1], entries[row]
            self._on_save_fn()
            self._emit_scene_changed()
            self._populate()
            self._table.selectRow(row - 1)

    def _move_down(self) -> None:
        if not self._scene:
            return
        row = self._current_row()
        entries = self._scene_sprites()
        if 0 <= row < len(entries) - 1:
            entries[row], entries[row + 1] = entries[row + 1], entries[row]
            self._on_save_fn()
            self._emit_scene_changed()
            self._populate()
            self._table.selectRow(row + 1)

    def _move_row_to(self, from_row: int, to_row: int) -> None:
        if not self._scene:
            return
        sprites = self._scene_sprites()
        if not (0 <= from_row < len(sprites)):
            return

        # drop at end is allowed
        to_row = max(0, min(int(to_row), len(sprites)))
        if to_row > from_row:
            to_row -= 1
        if to_row == from_row:
            return

        spr = sprites.pop(from_row)
        sprites.insert(int(to_row), spr)
        self._save_and_notify()
        self._populate()
        self._table.selectRow(int(to_row))

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _export_all(self) -> None:
        from core.sprite_loader import load_sprite

        if not self._scene:
            return

        sprites = self._scene_sprites()
        if not sprites:
            self._log.appendPlainText(tr("bundle.no_entries"))
            return

        script = self._find_script()
        if script is None:
            start = script_dialog_start_dir("export_script_path", fallback=self._project_dir)
            p, _ = QFileDialog.getOpenFileName(
                self, tr("export.find_script"), start, "Python (*.py)"
            )
            if not p:
                return
            script = Path(p)
            remember_script_path("export_script_path", script)

        self._log.clear()
        t_cursor = int(self._sb_tile_base.value())
        p_cursor = int(self._sb_pal_base.value())
        fixed_to_slot: dict[str, int] = {}
        n_ok = 0

        for spr in sprites:
            name = spr.get("name") or "?"
            path = self._abs(spr.get("file", ""))
            fw = int(spr.get("frame_w", 8) or 8)
            fh = int(spr.get("frame_h", 8) or 8)
            fc = int(spr.get("frame_count", 1) or 1)
            fc_use = None if fc <= 0 else fc
            fixed = str(spr.get("fixed_palette") or "").strip()

            if not path.exists():
                tiles, pal_n, est = sprite_tile_estimate(spr), 1, True
            else:
                tiles, pal_n, est = sprite_export_stats(self._base_dir, path, fw, fh, fc_use, fixed)

            auto_share = bool(fixed) and int(pal_n) == 1 and fixed in fixed_to_slot
            pal_base = fixed_to_slot[fixed] if auto_share else p_cursor

            if not path.exists():
                self._log.appendPlainText(tr("bundle.export_skip", name=name))
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
                data = load_sprite(path)
                out_dir = path.parent
                with tempfile.TemporaryDirectory(prefix="ngpc_pngmgr_") as tmp_dir:
                    tmp_png = Path(tmp_dir) / (path.stem + "__tmp.png")
                    data.hw.save(str(tmp_png))
                    from core.sprite_export_cli import run_sprite_export
                    res, _out_c = run_sprite_export(
                        script=script,
                        input_png=tmp_png,
                        out_dir=out_dir,
                        name=name,
                        frame_w=fw,
                        frame_h=fh,
                        frame_count=fc,
                        tile_base=int(t_cursor),
                        pal_base=int(pal_base),
                        fixed_palette=fixed or None,
                        output_c=(out_dir / f"{name}_mspr.c"),
                        header=True,
                        timeout_s=30,
                    )
                    if res.returncode == 0:
                        self._log.appendPlainText(
                            tr("bundle.export_ok", name=name, tiles=int(tiles), pal=int(pal_base))
                        )
                        n_ok += 1
                    else:
                        self._log.appendPlainText(
                            tr("bundle.export_fail", name=name, code=res.returncode)
                        )
            except Exception as e:
                self._log.appendPlainText(f"[ERR] {name}: {e}")

            t_cursor += int(tiles)
            if bool(fixed) and int(pal_n) == 1:
                if auto_share:
                    pass
                else:
                    fixed_to_slot[fixed] = int(pal_base)
                    p_cursor += int(pal_n)
            else:
                p_cursor += int(pal_n)

        self._log.appendPlainText(tr("bundle.done", n=n_ok))
