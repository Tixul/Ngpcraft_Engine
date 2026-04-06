"""
ui/tabs/tilemap_tab.py - Tilemap preview tab (Phase 4).

Opens a PNG and shows each 8×8 tile colored by color count:
  green  = ≤ 3 opaque colors → single-layer OK
  orange = 4 colors → borderline
  red    = 5+ colors → dual-layer required

Can launch ngpc_tilemap.py for the actual export.
"""
from __future__ import annotations

import base64
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
import importlib.util
from io import BytesIO
import json
import random
import subprocess 
import sys as _sys 
from pathlib import Path 
 
from PIL import Image 
from PyQt6.QtCore import Qt, QRect, QSize, QSettings, QFileSystemWatcher, QTimer 
from PyQt6.QtGui import QBrush, QColor, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut 
from PyQt6.QtWidgets import ( 
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFileDialog, QGroupBox, QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem, 
    QMessageBox,
    QInputDialog,
    QKeySequenceEdit,
    QPushButton, QScrollArea, QToolButton, QVBoxLayout, QWidget, QCheckBox, 
    QSpinBox,
    QSplitter,
    QTabWidget,
) 

from core.rgb444 import colors_per_tile, quantize_image
from i18n.lang import tr

_SHAPE_MODES: tuple[tuple[str, str], ...] = (
    ("free", "tilemap.shape_free"),
    ("rect", "tilemap.shape_rect"),
    ("ellipse", "tilemap.shape_ellipse"),
)
_SHORTCUT_DEFAULTS: tuple[tuple[str, str, str], ...] = (
    ("paint", "tilemap.tool_paint", "B"),
    ("pick", "tilemap.tool_pick", "P"),
    ("erase", "tilemap.tool_erase", "E"),
    ("fill", "tilemap.tool_fill", "F"),
    ("replace", "tilemap.tool_replace", "R"),
    ("select", "tilemap.tool_select", "S"),
    ("stamp", "tilemap.tool_stamp", "M"),
    ("stamp_flip_h", "tilemap.stamp_flip_h", "X"),
    ("stamp_flip_v", "tilemap.stamp_flip_v", "Y"),
    ("stamp_rot_r", "tilemap.stamp_rot_r", "Z"),
)
from ui.context_help import ContextHelpBox
from ui.tool_finder import default_candidates, find_script, script_dialog_start_dir, remember_script_path
from ui.tabs._project_path_mixin import ProjectPathMixin

# Overlay colors (RGBA)
_COL_OK   = QColor(0,   200,  80, 60)
_COL_WARN = QColor(255, 160,   0, 120)
_COL_ERR  = QColor(255,  30,  30, 150)

_COLLISION_PRESETS: dict[str, list[dict[str, int | str]]] = {
    "basic": [
        {"name": "PASS", "value": 0},
        {"name": "SOLID", "value": 1},
        {"name": "ONE_WAY", "value": 2},
        {"name": "DAMAGE", "value": 3},
        {"name": "LADDER", "value": 4},
    ],
    "platformer": [
        {"name": "PASS", "value": 0},
        {"name": "SOLID", "value": 1},
        {"name": "ONE_WAY", "value": 2},
        {"name": "DAMAGE", "value": 3},
        {"name": "LADDER", "value": 4},
        {"name": "STAIR_E", "value": 13},
        {"name": "STAIR_W", "value": 14},
        {"name": "WATER", "value": 9},
        {"name": "FIRE", "value": 10},
        {"name": "VOID", "value": 11},
        {"name": "DOOR", "value": 12},
    ],
    "topdown": [
        {"name": "PASS", "value": 0},
        {"name": "SOLID", "value": 1},
        {"name": "WALL_N", "value": 5},
        {"name": "WALL_S", "value": 6},
        {"name": "WALL_E", "value": 7},
        {"name": "WALL_W", "value": 8},
        {"name": "DAMAGE", "value": 3},
        {"name": "WATER", "value": 9},
        {"name": "FIRE", "value": 10},
        {"name": "VOID", "value": 11},
        {"name": "DOOR", "value": 12},
    ],
    "shmup": [
        {"name": "PASS", "value": 0},
        {"name": "SOLID", "value": 1},
        {"name": "DAMAGE", "value": 3},
        {"name": "FIRE", "value": 10},
        {"name": "VOID", "value": 11},
    ],
    "open": [
        {"name": "PASS", "value": 0},
        {"name": "SOLID", "value": 1},
        {"name": "DAMAGE", "value": 3},
        {"name": "WATER", "value": 9},
        {"name": "FIRE", "value": 10},
        {"name": "VOID", "value": 11},
        {"name": "DOOR", "value": 12},
    ],
    "full": [
        {"name": "PASS", "value": 0},
        {"name": "SOLID", "value": 1},
        {"name": "ONE_WAY", "value": 2},
        {"name": "DAMAGE", "value": 3},
        {"name": "LADDER", "value": 4},
        {"name": "WALL_N", "value": 5},
        {"name": "WALL_S", "value": 6},
        {"name": "WALL_E", "value": 7},
        {"name": "WALL_W", "value": 8},
        {"name": "WATER", "value": 9},
        {"name": "FIRE", "value": 10},
        {"name": "VOID", "value": 11},
        {"name": "DOOR", "value": 12},
        {"name": "STAIR_E", "value": 13},
        {"name": "STAIR_W", "value": 14},
    ],
}


@dataclass
class _UndoState:
    """Serialized tilemap image snapshot stored by the tilemap undo stack."""

    w: int
    h: int
    rgba: bytes


@dataclass
class _ColUndoState:
    """Serialized collision paint grid snapshot stored by the collision undo stack."""

    w: int
    h: int
    vals: tuple[int, ...]


class _UndoStack:
    """Bounded undo/redo history for destructive tilemap editing actions."""

    def __init__(self, limit: int = 50) -> None:
        self._limit = limit
        self._undo: deque[_UndoState] = deque()
        self._redo: deque[_UndoState] = deque()

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()

    def push(self, img: Image.Image) -> None:
        rgba = img.convert("RGBA").tobytes()
        st = _UndoState(img.width, img.height, rgba)
        self._undo.append(st)
        self._redo.clear()
        while len(self._undo) > self._limit:
            self._undo.popleft()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self, current: Image.Image) -> Image.Image | None:
        if not self._undo:
            return None
        self._redo.append(_UndoState(current.width, current.height, current.convert("RGBA").tobytes()))
        st = self._undo.pop()
        return Image.frombytes("RGBA", (st.w, st.h), st.rgba)

    def redo(self, current: Image.Image) -> Image.Image | None:
        if not self._redo:
            return None
        self._undo.append(_UndoState(current.width, current.height, current.convert("RGBA").tobytes()))
        st = self._redo.pop()
        return Image.frombytes("RGBA", (st.w, st.h), st.rgba)


# ---------------------------------------------------------------------------
# Tile grid widget
# ---------------------------------------------------------------------------

class _TileGridWidget(QWidget):
    """Displays a PNG with per-tile color-count overlays."""

    def __init__(self, tab: "TilemapTab", *, interactive: bool = True, mode: str = "colors") -> None:
        super().__init__(tab)
        self._tab = tab
        self._pixmap: QPixmap | None = None
        self._counts: list[list[int]] = []
        self._zoom = 4
        self._tile_w = 0
        self._tile_h = 0
        self._interactive = interactive
        self._mode = mode  # "colors" | "collision"
        self._col_grid: list[list[int]] | None = None
        self._col_colors: dict[int, QColor] = {}
        self._col_labels: dict[int, str] = {}
        self._dragging = False
        self._drag_button: Qt.MouseButton | None = None
        self._drag_last: tuple[int, int] | None = None
        self.setMouseTracking(True)

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.update()

    def set_collision_overlay(
        self,
        grid: list[list[int]] | None,
        colors: dict[int, QColor] | None,
        labels: dict[int, str] | None,
    ) -> None:
        self._col_grid = grid
        self._col_colors = dict(colors or {})
        self._col_labels = dict(labels or {})
        self.update()

    def set_data(self, img: Image.Image, counts: list[list[int]], zoom: int) -> None:
        self._zoom = zoom
        self._counts = counts
        # Convert PIL → QPixmap
        rgba = img.convert("RGBA")
        data = rgba.tobytes("raw", "RGBA")
        qimg = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
        self._pixmap = QPixmap.fromImage(qimg)
        # Resize widget to fit
        self._tile_w = rgba.width // 8
        self._tile_h = rgba.height // 8
        self.setFixedSize(self._tile_w * 8 * zoom + 2, self._tile_h * 8 * zoom + 2)
        self.update()

    def clear(self) -> None:
        self._pixmap = None
        self._counts = []
        self._tile_w = 0
        self._tile_h = 0
        self.setFixedSize(10, 10)
        self.update()

    def _to_tile(self, x: int, y: int) -> tuple[int, int] | None:
        z = self._zoom
        xx = x - 1
        yy = y - 1
        if xx < 0 or yy < 0:
            return None
        col = xx // (8 * z)
        row = yy // (8 * z)
        if 0 <= col < self._tile_w and 0 <= row < self._tile_h:
            return int(col), int(row)
        return None

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        if self._pixmap is None:
            p.end()
            return

        z = self._zoom
        cols_px = self._pixmap.width()
        rows_px = self._pixmap.height()

        # Draw image scaled (nearest-neighbor)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.drawPixmap(
            QRect(1, 1, cols_px * z, rows_px * z),
            self._pixmap,
            QRect(0, 0, cols_px, rows_px),
        )

        if self._mode == "collision" and self._col_grid is not None:
            for row_idx, row_vals in enumerate(self._col_grid):
                for col_idx, val in enumerate(row_vals):
                    c = self._col_colors.get(int(val))
                    if c is None:
                        continue
                    x = col_idx * 8 * z + 1
                    y = row_idx * 8 * z + 1
                    size = 8 * z
                    p.fillRect(x, y, size, size, c)
        elif getattr(self._tab, "_show_color_overlay", True):  # noqa: SLF001
            # Draw per-tile color-count overlays
            for row_idx, row_counts in enumerate(self._counts):
                for col_idx, count in enumerate(row_counts):
                    x = col_idx * 8 * z + 1
                    y = row_idx * 8 * z + 1
                    size = 8 * z
                    if count <= 3:
                        c = _COL_OK
                    elif count == 4:
                        c = _COL_WARN
                    else:
                        c = _COL_ERR
                    p.fillRect(x, y, size, size, c)

        if getattr(self._tab, "_show_grid_lines", False):  # noqa: SLF001
            w = self._tile_w * 8 * z
            h = self._tile_h * 8 * z
            alpha = 120 if z <= 2 else 80
            p.setPen(QPen(QColor(0, 0, 0, alpha)))
            for col in range(self._tile_w + 1):
                x = 1 + col * 8 * z
                p.drawLine(x, 1, x, 1 + h)
            for row in range(self._tile_h + 1):
                y = 1 + row * 8 * z
                p.drawLine(1, y, 1 + w, y)

        ht = self._tab._hover_tile  # noqa: SLF001
        if self._interactive and ht is not None:
            hx, hy = ht
            x = hx * 8 * z + 1
            y = hy * 8 * z + 1
            p.setPen(QPen(QColor(0, 0, 0, 200)))
            p.drawRect(x, y, 8 * z - 1, 8 * z - 1)
            p.setPen(QPen(QColor(255, 255, 255, 230)))
            p.drawRect(x + 1, y + 1, 8 * z - 3, 8 * z - 3)

        sel = getattr(self._tab, "_sel_rect", None)  # noqa: SLF001
        if self._interactive and self._mode != "collision" and sel is not None:
            sx = int(sel.x())
            sy = int(sel.y())
            sw = int(sel.width())
            sh = int(sel.height())
            if sw > 0 and sh > 0:
                x = sx * 8 * z + 1
                y = sy * 8 * z + 1
                w = sw * 8 * z
                h = sh * 8 * z
                pen = QPen(QColor(0, 240, 255, 230))
                pen.setStyle(Qt.PenStyle.DashLine)
                pen.setWidth(2 if z >= 4 else 1)
                p.setPen(pen)
                p.drawRect(x, y, w - 1, h - 1)

        shape_preview = getattr(self._tab, "_shape_preview_rect", None)  # noqa: SLF001
        if self._interactive and self._mode != "collision" and shape_preview is not None:
            sx, sy, sw, sh = shape_preview
            if sw > 0 and sh > 0:
                x = sx * 8 * z + 1
                y = sy * 8 * z + 1
                w = sw * 8 * z
                h = sh * 8 * z
                p.fillRect(x, y, w, h, QColor(0, 240, 255, 24))
                pen = QPen(QColor(0, 240, 255, 230))
                pen.setStyle(Qt.PenStyle.DashLine)
                pen.setWidth(2 if z >= 4 else 1)
                p.setPen(pen)
                if getattr(self._tab, "_shape_mode", "free") == "ellipse":  # noqa: SLF001
                    p.drawEllipse(x, y, w - 1, h - 1)
                else:
                    p.drawRect(x, y, w - 1, h - 1)

        # Stamp preview (ghost rectangle)
        if self._interactive and self._mode != "collision":
            try:
                tab = self._tab  # noqa: SLF001
                ht = getattr(tab, "_hover_tile", None)
                clip = getattr(tab, "_clipboard_img", None)
                tool = getattr(tab, "_tool", "")
                chk_edit = getattr(tab, "_chk_edit", None)
                if (tool == "stamp"
                        and ht is not None
                        and clip is not None
                        and chk_edit is not None
                        and chk_edit.isChecked()):
                    hx, hy = ht
                    cw = max(1, int(clip.width // 8))
                    ch = max(1, int(clip.height // 8))
                    w = min(cw, self._tile_w - hx)
                    h = min(ch, self._tile_h - hy)
                    if w > 0 and h > 0:
                        x = hx * 8 * z + 1
                        y = hy * 8 * z + 1
                        pw = w * 8 * z
                        ph = h * 8 * z
                        p.fillRect(x, y, pw, ph, QColor(0, 240, 255, 26))
                        pen = QPen(QColor(0, 240, 255, 220))
                        pen.setStyle(Qt.PenStyle.DashLine)
                        pen.setWidth(2 if z >= 4 else 1)
                        p.setPen(pen)
                        p.drawRect(x, y, pw - 1, ph - 1)
            except Exception:
                pass

        # NGPC screen bezel (20×19 tiles = 160×152 px)
        if self._interactive and getattr(self._tab, "_show_bezel", False):  # noqa: SLF001
            bx, by = getattr(self._tab, "_bezel_tile", (0, 0))  # noqa: SLF001
            bw, bh = 20, 19  # NGPC screen in tiles
            bpx = bx * 8 * z + 1
            bpy = by * 8 * z + 1
            bpw = bw * 8 * z
            bph = bh * 8 * z
            # Semi-transparent yellow fill
            p.fillRect(bpx, bpy, bpw, bph, QColor(255, 220, 0, 18))
            # Solid yellow border
            pen = QPen(QColor(255, 200, 0, 220))
            pen.setWidth(2)
            pen.setStyle(Qt.PenStyle.SolidLine)
            p.setPen(pen)
            p.drawRect(bpx, bpy, bpw - 1, bph - 1)
            # Corner label
            p.setPen(QPen(QColor(255, 200, 0, 200)))
            p.drawText(bpx + 4, bpy + 14, "NGPC 160×152")

        p.end()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._pixmap is None:
            super().mouseMoveEvent(event)
            return
        t = self._to_tile(event.pos().x(), event.pos().y())
        if t is not None:
            col, row = t
            if self._mode == "collision" and self._col_grid is not None:
                try:
                    val = int(self._col_grid[row][col])
                except Exception:
                    val = 0
                label = self._col_labels.get(val, str(val))
                self.setToolTip(tr("tilemap.col_tt", x=col, y=row, t=label, v=val))
                if self._interactive:
                    self._tab._on_hover_tile(col, row, 0)  # noqa: SLF001
            else:
                try:
                    count = int(self._counts[row][col]) if self._counts else 0
                except Exception:
                    count = 0
                status = tr("tilemap.tt_ok") if count <= 3 else (tr("tilemap.tt_limit") if count == 4 else tr("tilemap.tt_error"))
                self.setToolTip(tr("tilemap.tile_tt", x=col, y=row, n=count, status=status))
                if self._interactive:
                    self._tab._on_hover_tile(col, row, count)  # noqa: SLF001
        else:
            if self._interactive:
                self._tab._clear_hover_tile()  # noqa: SLF001

        # Bezel repositioning: Alt + left-button drag moves the bezel
        if (self._interactive
                and getattr(self._tab, "_show_bezel", False)  # noqa: SLF001
                and t is not None
                and event.buttons() & Qt.MouseButton.LeftButton
                and event.modifiers() & Qt.KeyboardModifier.AltModifier):
            self._tab._bezel_tile = t  # noqa: SLF001
            self.update()
            super().mouseMoveEvent(event)
            return

        if self._interactive and self._dragging and self._drag_button is not None:
            # End drag if the button is no longer held.
            if not (event.buttons() & self._drag_button):
                self._dragging = False
                self._drag_button = None
                self._drag_last = None
                self._tab._end_drag()  # noqa: SLF001
            elif t is not None and t != self._drag_last:
                self._drag_last = t
                self._tab._apply_drag(t[0], t[1])  # noqa: SLF001
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        if self._interactive:
            self._tab._clear_hover_tile()  # noqa: SLF001
        if self._dragging:
            self._dragging = False
            self._drag_button = None
            self._drag_last = None
            if self._interactive:
                self._tab._end_drag()  # noqa: SLF001
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if not self._interactive:
            super().mousePressEvent(event)
            return
        t = self._to_tile(event.pos().x(), event.pos().y())
        if t is not None:
            if self._tab._begin_drag(event.button(), event.modifiers()):  # noqa: SLF001
                self._dragging = True
                self._drag_button = event.button()
                self._drag_last = t
                self._tab._apply_drag(t[0], t[1])  # noqa: SLF001
                event.accept()
                return
            self._tab._on_tile_click(t[0], t[1], event.button(), event.modifiers())  # noqa: SLF001
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if not self._interactive:
            super().mouseReleaseEvent(event)
            return
        if self._dragging and self._drag_button is not None and event.button() == self._drag_button:
            self._dragging = False
            self._drag_button = None
            self._drag_last = None
            self._tab._end_drag()  # noqa: SLF001
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta != 0:
                self._tab._zoom_step(1 if delta > 0 else -1)  # noqa: SLF001
            event.accept()
        else:
            event.ignore()  # propagate to QScrollArea for normal scrolling


# ---------------------------------------------------------------------------
# TilemapTab
# ---------------------------------------------------------------------------

class TilemapTab(ProjectPathMixin, QWidget):
    """Tilemap viewer/editor tab with NGPC-specific color and collision tooling.

    Path helpers (_project_dir, _rel, _abs) come from ProjectPathMixin.
    """

    def __init__(
        self,
        project_data: dict | None = None,
        project_path: Path | None = None,
        on_save: Callable[[], None] | None = None,
        is_free_mode: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent) 
        self._data = project_data or {}
        self._project_path = project_path
        self._on_save_fn = on_save
        self._is_free_mode = is_free_mode
        self._img: Image.Image | None = None 
        self._counts: list[list[int]] = [] 
        self._counts_dirty = False
        self._current_path: Path | None = None 
        self._zoom = 4 
        self._dirty = False
        self._hover_tile: tuple[int, int] | None = None
        self._brush_tile: tuple[int, int] | None = None
        self._brush_img: Image.Image | None = None
        self._brush_bytes: bytes | None = None
        self._brush_variants: list[Image.Image] = []
        self._scr2_path: Path | None = None
        self._drag_action: str | None = None
        self._drag_changed: list[tuple[int, int]] = []
        self._drag_seen: set[int] = set()
        self._drag_pushed = False
        self._tool = "paint"
        self._shape_mode = "free"
        self._shape_drag_start: tuple[int, int] | None = None
        self._shape_preview_rect: tuple[int, int, int, int] | None = None
        self._stamp_presets: list[dict[str, str]] = self._load_stamp_presets()
        self._shortcut_bindings = self._load_shortcut_bindings()
        self._edit_shortcuts: list[QShortcut] = []
        self._sel_rect: QRect | None = None  # in tiles
        self._sel_drag_start: tuple[int, int] | None = None
        self._clipboard_img: Image.Image | None = None  # RGBA pixels, size multiple of 8
        self._line_anchor_tile: tuple[int, int] | None = None
        self._line_anchor_col: tuple[int, int] | None = None
        self._scene_context: dict | None = None 
        self._scene_base_dir: Path | None = None 
        self._active_tm: dict | None = None
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.timeout.connect(self._reload_from_disk)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_project_now)
        self._undo = _UndoStack(limit=40)
        self._tileset_tiles: list[bytes] = []
        self._tileset_img: Image.Image | None = None
        self._tileset_path: Path | None = None
        self._col_unique_rgba: list[bytes] = []
        self._col_map_ids: list[int] = []
        self._col_map_ids2: list[int] = []
        self._col_assign: list[int] = []
        self._col_types: list[dict] = []
        self._col_mode = "tileset"
        self._col_paint_grid: list[list[int]] = []
        self._col_brush_value = 1
        self._col_undo: list[_ColUndoState] = []
        self._col_redo: list[_ColUndoState] = []
        self._col_basis_dirty = True
        self._col_overlay_mode = QSettings("NGPCraft", "Engine").value("tilemap/col_overlay", "max", str)
        self._show_grid_lines = QSettings("NGPCraft", "Engine").value("tilemap/show_grid", True, bool)
        self._show_color_overlay = QSettings("NGPCraft", "Engine").value("tilemap/show_color_overlay", True, bool)
        self._show_bezel = False
        self._bezel_tile: tuple[int, int] = (0, 0)  # top-left corner in tile coords
        self._build_ui() 
        self._refresh_shape_ui()
        self.setAcceptDrops(True) 

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        center = QWidget()
        center_l = QVBoxLayout(center)
        center_l.setContentsMargins(0, 0, 0, 0)
        center_l.setSpacing(6)

        right = QWidget()
        right.setMinimumWidth(260)
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(4)
        self._right_tabs = QTabWidget()
        self._right_tabs.setTabPosition(QTabWidget.TabPosition.North)
        right_l.addWidget(self._right_tabs, 1)

        def _make_scroll_tab() -> tuple[QScrollArea, QVBoxLayout]:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            host = QWidget()
            host_l = QVBoxLayout(host)
            host_l.setContentsMargins(4, 4, 4, 4)
            host_l.setSpacing(6)
            scroll.setWidget(host)
            return scroll, host_l

        tab_workflow, workflow_l = _make_scroll_tab()
        tab_tools, tools_l = _make_scroll_tab()
        tab_export, export_l = _make_scroll_tab()

        self._ctx_tilemap_flow = ContextHelpBox(
            tr("tilemap.ctx_workflow_title"),
            tr("tilemap.ctx_workflow_body"),
            self,
        )
        workflow_l.addWidget(self._ctx_tilemap_flow)

        self._lbl_checklist = QLabel("")
        self._lbl_checklist.setWordWrap(True)
        self._lbl_checklist.setTextFormat(Qt.TextFormat.RichText)
        self._lbl_checklist.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        workflow_l.addWidget(self._lbl_checklist)


        # Source : scene pick + file management (merged group)
        self._source_group = QGroupBox(tr("tilemap.group_source"))
        source_l = QVBoxLayout(self._source_group)
        source_l.setSpacing(4)

        scene_row = QHBoxLayout()
        scene_row.addWidget(QLabel(tr("tilemap.scene_label")))
        self._scene_pick = QComboBox()
        self._scene_pick.setToolTip(tr("tilemap.scene_pick_tt"))
        scene_row.addWidget(self._scene_pick, 1)
        self._btn_scene_open = QPushButton(tr("tilemap.scene_open"))
        self._btn_scene_open.setToolTip(tr("tilemap.scene_open_tt"))
        self._btn_scene_open.setEnabled(False)
        self._btn_scene_open.clicked.connect(self._open_scene_tilemap)
        scene_row.addWidget(self._btn_scene_open)
        source_l.addLayout(scene_row)

        self._scene_lbl = QLabel(tr("tilemap.scene_none"))
        self._scene_lbl.setWordWrap(True)
        self._scene_lbl.setStyleSheet("color: gray; font-style: italic; font-size: 10px;")
        source_l.addWidget(self._scene_lbl)

        file_info_row = QHBoxLayout()
        file_info_row.addWidget(QLabel(tr("tilemap.file_label")))
        self._file_lbl = QLabel(tr("tilemap.no_file"))
        self._file_lbl.setWordWrap(True)
        self._file_lbl.setStyleSheet("color: gray; font-style: italic;")
        file_info_row.addWidget(self._file_lbl, 1)
        source_l.addLayout(file_info_row)

        file_open_row = QHBoxLayout()
        self._auto_reload = QCheckBox(tr("tilemap.auto_reload"))
        self._auto_reload.setChecked(True)
        self._auto_reload.setToolTip(tr("tilemap.auto_reload_tt"))
        file_open_row.addWidget(self._auto_reload)
        btn_open = QPushButton(tr("tilemap.open_file"))
        btn_open.clicked.connect(self._open_file)
        btn_open.setToolTip(tr("tilemap.open_file_tt"))
        file_open_row.addWidget(btn_open)
        btn_new = QPushButton(tr("tilemap.new_file"))
        btn_new.clicked.connect(self._new_file)
        btn_new.setToolTip(tr("tilemap.new_file_tt"))
        file_open_row.addWidget(btn_new)
        source_l.addLayout(file_open_row)

        file_save_row = QHBoxLayout()
        self._btn_resize = QPushButton(tr("tilemap.resize"))
        self._btn_resize.clicked.connect(self._resize_canvas)
        self._btn_resize.setEnabled(False)
        self._btn_resize.setToolTip(tr("tilemap.resize_tt"))
        file_save_row.addWidget(self._btn_resize)
        self._btn_save = QPushButton(tr("tilemap.save"))
        self._btn_save.clicked.connect(self._save_overwrite)
        self._btn_save.setEnabled(False)
        self._btn_save.setToolTip(tr("tilemap.save_tt"))
        file_save_row.addWidget(self._btn_save)
        self._btn_save_as = QPushButton(tr("tilemap.save_as"))
        self._btn_save_as.clicked.connect(self._save_as)
        self._btn_save_as.setEnabled(False)
        self._btn_save_as.setToolTip(tr("tilemap.save_as_tt"))
        file_save_row.addWidget(self._btn_save_as)
        source_l.addLayout(file_save_row)

        workflow_l.addWidget(self._source_group)

        self._view_group = QGroupBox(tr("tilemap.group_view"))
        view_l = QVBoxLayout(self._view_group)
        zoom_row = QHBoxLayout()
        zoom_lbl = QLabel(tr("tilemap.zoom"))
        zoom_lbl.setToolTip(tr("tilemap.zoom_tt"))
        zoom_row.addWidget(zoom_lbl)
        for z, label in [(1, "×1"), (2, "×2"), (4, "×4"), (8, "×8"), (16, "×16"), (32, "×32")]:
            btn = QToolButton()
            btn.setText(label)
            btn.setCheckable(True)
            btn.setChecked(z == self._zoom)
            btn.clicked.connect(lambda checked, zv=z: self._set_zoom(zv))
            btn.setToolTip(tr("tilemap.zoom_btn_tt", z=z))
            zoom_row.addWidget(btn)
            setattr(self, f"_zoom_btn_{z}", btn)
        zoom_row.addStretch()
        view_l.addLayout(zoom_row)
        overlay_row = QHBoxLayout()
        self._chk_grid = QCheckBox(tr("tilemap.gridlines"))
        self._chk_grid.setChecked(bool(self._show_grid_lines))
        self._chk_grid.setToolTip(tr("tilemap.gridlines_tt"))
        self._chk_grid.toggled.connect(self._on_gridlines_toggled)
        overlay_row.addWidget(self._chk_grid)
        self._chk_overlay = QCheckBox(tr("tilemap.show_overlay"))
        self._chk_overlay.setChecked(bool(self._show_color_overlay))
        self._chk_overlay.setToolTip(tr("tilemap.show_overlay_tt"))
        self._chk_overlay.toggled.connect(self._on_overlay_toggled)
        overlay_row.addWidget(self._chk_overlay)
        overlay_row.addStretch()
        view_l.addLayout(overlay_row)
        view_row_2 = QHBoxLayout()
        self._chk_bezel = QCheckBox(tr("tilemap.show_bezel"))
        self._chk_bezel.setChecked(False)
        self._chk_bezel.setToolTip(tr("tilemap.show_bezel_tt"))
        self._chk_bezel.toggled.connect(self._on_bezel_toggled)
        view_row_2.addWidget(self._chk_bezel)
        legend_lbl = QLabel(tr("tilemap.legend"))
        legend_lbl.setStyleSheet(
            "color: #888; font-size: 11px;"
        )
        view_row_2.addWidget(legend_lbl)
        view_row_2.addStretch()
        view_l.addLayout(view_row_2)
        limits_row = QHBoxLayout()
        self._lbl_size_limits = QLabel(tr("tilemap.size_limits"))
        self._lbl_size_limits.setToolTip(tr("tilemap.size_limits_tt"))
        self._lbl_size_limits.setStyleSheet("color: #888; font-size: 11px;")
        self._lbl_size_limits.setWordWrap(True)
        limits_row.addWidget(self._lbl_size_limits, 1)
        view_l.addLayout(limits_row)

        self._edit_group = QGroupBox(tr("tilemap.group_edit"))
        edit_l = QVBoxLayout(self._edit_group)
        edit_row_top = QHBoxLayout()
        self._chk_edit = QCheckBox(tr("tilemap.edit_mode"))
        self._chk_edit.setChecked(False)
        self._chk_edit.toggled.connect(self._on_edit_toggled)
        self._chk_edit.setToolTip(tr("tilemap.edit_mode_tt"))
        edit_row_top.addWidget(self._chk_edit)

        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)

        def _tool_btn(tool: str, label_key: str, tt_key: str) -> QToolButton:
            b = QToolButton()
            b.setText(tr(label_key))
            b.setCheckable(True)
            b.setToolTip(tr(tt_key))
            b.clicked.connect(lambda _checked=False, t=tool: self._set_tool(t))
            self._tool_group.addButton(b)
            return b

        self._btn_tool_paint = _tool_btn("paint", "tilemap.tool_paint", "tilemap.tool_paint_tt")
        self._btn_tool_pick = _tool_btn("pick", "tilemap.tool_pick", "tilemap.tool_pick_tt")
        self._btn_tool_erase = _tool_btn("erase", "tilemap.tool_erase", "tilemap.tool_erase_tt")
        self._btn_tool_fill = _tool_btn("fill", "tilemap.tool_fill", "tilemap.tool_fill_tt")
        self._btn_tool_replace = _tool_btn("replace", "tilemap.tool_replace", "tilemap.tool_replace_tt")
        self._btn_tool_select = _tool_btn("select", "tilemap.tool_select", "tilemap.tool_select_tt")
        self._btn_tool_stamp = _tool_btn("stamp", "tilemap.tool_stamp", "tilemap.tool_stamp_tt")
        self._btn_tool_paint.setChecked(True)

        for b in (
            self._btn_tool_paint,
            self._btn_tool_pick,
            self._btn_tool_erase,
        ):
            edit_row_top.addWidget(b)
        edit_row_top.addStretch()
        edit_l.addLayout(edit_row_top)
        edit_row_mid = QHBoxLayout()
        for b in (
            self._btn_tool_fill,
            self._btn_tool_replace,
            self._btn_tool_select,
            self._btn_tool_stamp,
        ):
            edit_row_mid.addWidget(b)
        edit_row_mid.addStretch()
        edit_l.addLayout(edit_row_mid)

        self._brush_lbl = QLabel(tr("tilemap.brush_none"))
        self._brush_lbl.setWordWrap(True)
        self._brush_lbl.setStyleSheet("color: gray;")
        self._brush_lbl.setToolTip(tr("tilemap.brush_tt"))
        edit_l.addWidget(self._brush_lbl)
        edit_row_actions = QHBoxLayout()
        self._btn_stamp_flip_h = QPushButton(tr("tilemap.stamp_flip_h"))
        self._btn_stamp_flip_h.clicked.connect(self._stamp_flip_h)
        self._btn_stamp_flip_h.setEnabled(False)
        self._btn_stamp_flip_h.setToolTip(tr("tilemap.stamp_flip_h_tt"))
        edit_row_actions.addWidget(self._btn_stamp_flip_h)
        self._btn_stamp_flip_v = QPushButton(tr("tilemap.stamp_flip_v"))
        self._btn_stamp_flip_v.clicked.connect(self._stamp_flip_v)
        self._btn_stamp_flip_v.setEnabled(False)
        self._btn_stamp_flip_v.setToolTip(tr("tilemap.stamp_flip_v_tt"))
        edit_row_actions.addWidget(self._btn_stamp_flip_v)
        self._btn_stamp_rot_r = QPushButton(tr("tilemap.stamp_rot_r"))
        self._btn_stamp_rot_r.clicked.connect(self._stamp_rot_r)
        self._btn_stamp_rot_r.setEnabled(False)
        self._btn_stamp_rot_r.setToolTip(tr("tilemap.stamp_rot_r_tt"))
        edit_row_actions.addWidget(self._btn_stamp_rot_r)
        self._chk_brush_variation = QCheckBox(tr("tilemap.brush_variation"))
        self._chk_brush_variation.setToolTip(tr("tilemap.brush_variation_tt"))
        self._chk_brush_variation.toggled.connect(lambda _on: self._on_tileset_selection_changed())
        edit_row_actions.addWidget(self._chk_brush_variation)
        self._stamp_preset_pick = QComboBox()
        self._stamp_preset_pick.setToolTip(tr("tilemap.stamp_preset_pick_tt"))
        self._stamp_preset_pick.currentIndexChanged.connect(self._refresh_stamp_presets_ui)
        edit_row_actions.addWidget(self._stamp_preset_pick, 1)
        self._btn_stamp_preset_save = QPushButton(tr("tilemap.stamp_preset_save"))
        self._btn_stamp_preset_save.clicked.connect(self._stamp_preset_save)
        self._btn_stamp_preset_save.setToolTip(tr("tilemap.stamp_preset_save_tt"))
        edit_row_actions.addWidget(self._btn_stamp_preset_save)
        self._btn_stamp_preset_apply = QPushButton(tr("tilemap.stamp_preset_apply"))
        self._btn_stamp_preset_apply.clicked.connect(self._stamp_preset_apply)
        self._btn_stamp_preset_apply.setToolTip(tr("tilemap.stamp_preset_apply_tt"))
        edit_row_actions.addWidget(self._btn_stamp_preset_apply)
        self._btn_stamp_preset_delete = QPushButton(tr("tilemap.stamp_preset_delete"))
        self._btn_stamp_preset_delete.clicked.connect(self._stamp_preset_delete)
        self._btn_stamp_preset_delete.setToolTip(tr("tilemap.stamp_preset_delete_tt"))
        edit_row_actions.addWidget(self._btn_stamp_preset_delete)
        edit_row_actions.addStretch()
        edit_l.addLayout(edit_row_actions)
        shape_row = QHBoxLayout()
        shape_row.addWidget(QLabel(tr("tilemap.shape")))
        self._shape_pick = QComboBox()
        for shape_key, label_key in _SHAPE_MODES:
            self._shape_pick.addItem(tr(label_key), shape_key)
        self._shape_pick.setToolTip(tr("tilemap.shape_tt"))
        self._shape_pick.currentIndexChanged.connect(self._on_shape_mode_changed)
        shape_row.addWidget(self._shape_pick, 1)
        self._lbl_shape_hint = QLabel(tr("tilemap.shape_hint_free"))
        self._lbl_shape_hint.setWordWrap(True)
        self._lbl_shape_hint.setStyleSheet("color: #888; font-size: 11px;")
        shape_row.addWidget(self._lbl_shape_hint, 2)
        edit_l.addLayout(shape_row)
        shortcut_row = QHBoxLayout()
        self._btn_shortcuts = QPushButton(tr("tilemap.shortcuts_btn"))
        self._btn_shortcuts.clicked.connect(self._open_shortcuts_dialog)
        self._btn_shortcuts.setToolTip(tr("tilemap.shortcuts_btn_tt"))
        shortcut_row.addWidget(self._btn_shortcuts)
        self._lbl_shortcuts = QLabel("")
        self._lbl_shortcuts.setWordWrap(True)
        self._lbl_shortcuts.setStyleSheet("color: #888; font-size: 11px;")
        shortcut_row.addWidget(self._lbl_shortcuts, 1)
        edit_l.addLayout(shortcut_row)
        edit_row_bottom = QHBoxLayout()
        self._btn_undo = QPushButton(tr("tilemap.undo"))
        self._btn_undo.clicked.connect(self._on_undo)
        self._btn_undo.setEnabled(False)
        self._btn_undo.setToolTip(tr("tilemap.undo_tt"))
        edit_row_bottom.addWidget(self._btn_undo)
        self._btn_redo = QPushButton(tr("tilemap.redo"))
        self._btn_redo.clicked.connect(self._on_redo)
        self._btn_redo.setEnabled(False)
        self._btn_redo.setToolTip(tr("tilemap.redo_tt"))
        edit_row_bottom.addWidget(self._btn_redo)
        self._btn_split = QPushButton(tr("tilemap.split_png"))
        self._btn_split.clicked.connect(self._export_scr_pngs)
        self._btn_split.setEnabled(False)
        self._btn_split.setToolTip(tr("tilemap.split_png_tt"))
        edit_row_bottom.addWidget(self._btn_split)
        edit_row_bottom.addStretch()
        edit_l.addLayout(edit_row_bottom)

        tools_l.addWidget(self._view_group)
        tools_l.addWidget(self._edit_group)

        self._layer_group = QGroupBox(tr("tilemap.group_export"))
        layer_l = QVBoxLayout(self._layer_group)
        scr2_row = QHBoxLayout()
        scr2_row.addWidget(QLabel(tr("tilemap.scr2")))
        self._scr2_lbl = QLabel(tr("tilemap.scr2_none"))
        self._scr2_lbl.setWordWrap(True)
        self._scr2_lbl.setStyleSheet("color: gray; font-style: italic;")
        scr2_row.addWidget(self._scr2_lbl, 1)
        self._btn_scr2_pick = QPushButton(tr("tilemap.scr2_pick"))
        self._btn_scr2_pick.clicked.connect(self._pick_scr2)
        self._btn_scr2_pick.setEnabled(False)
        self._btn_scr2_pick.setToolTip(tr("tilemap.scr2_pick_tt"))
        scr2_row.addWidget(self._btn_scr2_pick)
        self._btn_scr2_clear = QPushButton(tr("tilemap.scr2_clear"))
        self._btn_scr2_clear.clicked.connect(self._clear_scr2)
        self._btn_scr2_clear.setEnabled(False)
        self._btn_scr2_clear.setToolTip(tr("tilemap.scr2_clear_tt"))
        scr2_row.addWidget(self._btn_scr2_clear)
        self._chk_header = QCheckBox(tr("tilemap.header"))
        self._chk_header.setChecked(True)
        self._chk_header.setToolTip(tr("tilemap.header_tt"))
        scr2_row.addWidget(self._chk_header)
        layer_l.addLayout(scr2_row)

        # Tile compression row (CT-6)
        compress_row = QHBoxLayout()
        self._chk_compress = QCheckBox(tr("tilemap.compress"))
        self._chk_compress.setChecked(False)
        self._chk_compress.setToolTip(tr("tilemap.compress_tt"))
        compress_row.addWidget(self._chk_compress)
        self._combo_compress = QComboBox()
        self._combo_compress.addItem(tr("tilemap.compress_auto"), "both")
        self._combo_compress.addItem(tr("tilemap.compress_lz77"), "lz77")
        self._combo_compress.addItem(tr("tilemap.compress_rle"), "rle")
        self._combo_compress.setToolTip(tr("tilemap.compress_tt"))
        self._combo_compress.setEnabled(False)
        compress_row.addWidget(self._combo_compress)
        compress_row.addStretch()
        self._chk_compress.toggled.connect(self._combo_compress.setEnabled)
        layer_l.addLayout(compress_row)

        # Intended scroll plane (SCR1/SCR2) for single-layer maps (project metadata)
        plane_row = QHBoxLayout()
        plane_row.addWidget(QLabel(tr("tilemap.plane")))
        self._plane_pick = QComboBox()
        self._plane_pick.addItem(tr("tilemap.plane_auto"), "auto")
        self._plane_pick.addItem(tr("tilemap.plane_scr1"), "scr1")
        self._plane_pick.addItem(tr("tilemap.plane_scr2"), "scr2")
        self._plane_pick.setToolTip(tr("tilemap.plane_tt"))
        self._plane_pick.setEnabled(False)
        self._plane_pick.currentIndexChanged.connect(self._on_plane_changed)
        plane_row.addWidget(self._plane_pick, 1)
        layer_l.addLayout(plane_row)

        # Collision overlay (always visible)
        overlay_row = QHBoxLayout()
        overlay_row.addWidget(QLabel(tr("tilemap.col_overlay")))
        self._col_overlay = QComboBox()
        self._col_overlay.addItem(tr("tilemap.col_overlay_max"), "max")
        self._col_overlay.addItem(tr("tilemap.col_overlay_scr1"), "scr1")
        self._col_overlay.addItem(tr("tilemap.col_overlay_scr2"), "scr2")
        self._col_overlay.setToolTip(tr("tilemap.col_overlay_tt"))
        self._col_overlay.currentIndexChanged.connect(self._on_col_overlay_changed)
        idx = self._col_overlay.findData(self._col_overlay_mode)
        if idx >= 0:
            self._col_overlay.blockSignals(True)
            self._col_overlay.setCurrentIndex(idx)
            self._col_overlay.blockSignals(False)
        overlay_row.addWidget(self._col_overlay, 1)
        layer_l.addLayout(overlay_row)
        export_l.addWidget(self._layer_group)

        # Grid (map + collision)
        grid_g = QGroupBox(tr("tilemap.grid_group"))
        grid_l = QVBoxLayout(grid_g)

        # Drop hint (shown when no file loaded)
        self._drop_hint = QLabel(tr("tilemap.drop_hint"))
        self._drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_hint.setStyleSheet("color: gray; font-style: italic; padding: 40px;")
        grid_l.addWidget(self._drop_hint)

        self._grid_tabs = QTabWidget()
        self._grid_tabs.setVisible(False)
        self._grid_tabs.currentChanged.connect(self._on_grid_tab_changed)
        grid_l.addWidget(self._grid_tabs, 1)

        # ---- Map tab ----
        map_page = QWidget()
        map_page_l = QVBoxLayout(map_page)
        map_page_l.setContentsMargins(0, 0, 0, 0)

        # Main editor row: tileset + map grid
        self._grid_row = QWidget()
        grid_row_l = QHBoxLayout(self._grid_row)
        grid_row_l.setContentsMargins(0, 0, 0, 0)
        grid_row_l.setSpacing(8)

        self._tileset_g = QGroupBox(tr("tilemap.tileset_group"))
        self._tileset_g.setMaximumWidth(220)
        ts_l = QVBoxLayout(self._tileset_g)
        self._tileset_src = QLabel("")
        self._tileset_src.setStyleSheet("color: gray;")
        ts_l.addWidget(self._tileset_src)
        self._tileset_info = QLabel(tr("tilemap.tileset_none"))
        self._tileset_info.setStyleSheet("color: gray;")
        ts_l.addWidget(self._tileset_info)
        self._tileset = QListWidget()
        self._tileset.setViewMode(QListView.ViewMode.IconMode)
        self._tileset.setResizeMode(QListView.ResizeMode.Adjust)
        self._tileset.setMovement(QListView.Movement.Static)
        self._tileset.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._tileset.setIconSize(QSize(32, 32))
        self._tileset.setSpacing(4)
        self._tileset.itemSelectionChanged.connect(self._on_tileset_selection_changed)
        ts_l.addWidget(self._tileset, 1)
        ts_btns = QHBoxLayout()
        self._btn_tileset_load = QPushButton(tr("tilemap.tileset_load"))
        self._btn_tileset_load.clicked.connect(self._pick_tileset_png)
        self._btn_tileset_load.setEnabled(False)
        self._btn_tileset_load.setToolTip(tr("tilemap.tileset_load_tt"))
        ts_btns.addWidget(self._btn_tileset_load)
        self._btn_tileset_reset = QPushButton(tr("tilemap.tileset_reset"))
        self._btn_tileset_reset.clicked.connect(self._reset_tileset_to_map)
        self._btn_tileset_reset.setEnabled(False)
        self._btn_tileset_reset.setToolTip(tr("tilemap.tileset_reset_tt"))
        ts_btns.addWidget(self._btn_tileset_reset)
        self._btn_brush_erase = QPushButton(tr("tilemap.erase_brush"))
        self._btn_brush_erase.clicked.connect(self._set_brush_transparent)
        self._btn_brush_erase.setEnabled(False)
        self._btn_brush_erase.setToolTip(tr("tilemap.erase_brush_tt"))
        ts_btns.addWidget(self._btn_brush_erase)
        ts_btns.addStretch()
        ts_l.addLayout(ts_btns)
        self._tileset_g.setVisible(False)
        grid_row_l.addWidget(self._tileset_g, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._grid = _TileGridWidget(self, interactive=True, mode="colors")
        self._scroll.setWidget(self._grid)
        grid_row_l.addWidget(self._scroll, 1)
        self._scroll.setVisible(False)
        self._grid_row.setVisible(False)
        map_page_l.addWidget(self._grid_row, 1)
        self._grid_tabs.addTab(map_page, tr("tilemap.tab_map"))

        # ---- Collision tab ----
        col_page = QWidget()
        col_page_l = QVBoxLayout(col_page)
        col_page_l.setContentsMargins(0, 0, 0, 0)

        self._col_row = QWidget()
        col_row_l = QHBoxLayout(self._col_row)
        col_row_l.setContentsMargins(0, 0, 0, 0)
        col_row_l.setSpacing(8)

        self._col_g = QGroupBox(tr("tilemap.col_group"))
        self._col_g.setMaximumWidth(260)
        col_l = QVBoxLayout(self._col_g)
        self._col_info = QLabel("")
        self._col_info.setWordWrap(True)
        self._col_info.setStyleSheet("color: gray; font-size: 11px;")
        col_l.addWidget(self._col_info)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel(tr("tilemap.col_preset")))
        self._col_preset_pick = QComboBox()
        self._col_preset_pick.addItem(tr("tilemap.col_preset_custom"), "custom")
        self._col_preset_pick.addItem(tr("tilemap.col_preset_basic"), "basic")
        self._col_preset_pick.addItem(tr("tilemap.col_preset_platformer"), "platformer")
        self._col_preset_pick.addItem(tr("tilemap.col_preset_topdown"), "topdown")
        self._col_preset_pick.addItem(tr("tilemap.col_preset_shmup"), "shmup")
        self._col_preset_pick.addItem(tr("tilemap.col_preset_open"), "open")
        self._col_preset_pick.addItem(tr("tilemap.col_preset_full"), "full")
        self._col_preset_pick.setToolTip(tr("tilemap.col_preset_tt"))
        self._col_preset_pick.currentIndexChanged.connect(lambda _idx: self._refresh_collision_preset_ui())
        preset_row.addWidget(self._col_preset_pick, 1)
        self._btn_col_preset_apply = QPushButton(tr("tilemap.col_preset_apply"))
        self._btn_col_preset_apply.setToolTip(tr("tilemap.col_preset_apply_tt"))
        self._btn_col_preset_apply.clicked.connect(self._apply_collision_preset)
        preset_row.addWidget(self._btn_col_preset_apply)
        col_l.addLayout(preset_row)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(tr("tilemap.col_mode")))
        self._col_mode_pick = QComboBox()
        self._col_mode_pick.addItem(tr("tilemap.col_mode_tileset"), "tileset")
        self._col_mode_pick.addItem(tr("tilemap.col_mode_paint"), "paint")
        self._col_mode_pick.setToolTip(tr("tilemap.col_mode_tt"))
        self._col_mode_pick.currentIndexChanged.connect(self._on_col_mode_changed)
        mode_row.addWidget(self._col_mode_pick, 1)
        col_l.addLayout(mode_row)

        self._col_list = QListWidget()
        self._col_list.setViewMode(QListView.ViewMode.IconMode)
        self._col_list.setResizeMode(QListView.ResizeMode.Adjust)
        self._col_list.setMovement(QListView.Movement.Static)
        self._col_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._col_list.setIconSize(QSize(32, 32))
        self._col_list.setSpacing(4)
        self._col_list.currentRowChanged.connect(self._on_col_tile_selected)
        col_l.addWidget(self._col_list, 1)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel(tr("tilemap.col_type")))
        self._col_type = QComboBox()
        self._col_type.setToolTip(tr("tilemap.col_type_tt"))
        self._col_type.currentIndexChanged.connect(self._on_col_type_changed)
        type_row.addWidget(self._col_type, 1)
        col_l.addLayout(type_row)

        col_btns = QHBoxLayout()
        self._btn_col_reset = QPushButton(tr("tilemap.col_reset"))
        self._btn_col_reset.clicked.connect(self._col_reset_all)
        self._btn_col_reset.setToolTip(tr("tilemap.col_reset_tt"))
        col_btns.addWidget(self._btn_col_reset)
        self._btn_col_export = QPushButton(tr("tilemap.col_export"))
        self._btn_col_export.clicked.connect(self._col_export_header)
        self._btn_col_export.setToolTip(tr("tilemap.col_export_tt"))
        col_btns.addWidget(self._btn_col_export)
        self._btn_col_save = QPushButton(tr("tilemap.col_save"))
        self._btn_col_save.clicked.connect(self._col_save_to_project)
        self._btn_col_save.setToolTip(tr("tilemap.col_save_tt"))
        col_btns.addWidget(self._btn_col_save)
        col_l.addLayout(col_btns)

        self._col_g.setVisible(False)
        col_row_l.addWidget(self._col_g, 0)

        self._col_scroll = QScrollArea()
        self._col_scroll.setWidgetResizable(False)
        self._grid_col = _TileGridWidget(self, interactive=True, mode="collision")
        self._col_scroll.setWidget(self._grid_col)
        self._col_scroll.setVisible(False)
        col_row_l.addWidget(self._col_scroll, 1)

        col_page_l.addWidget(self._col_row, 1)
        self._grid_tabs.addTab(col_page, tr("tilemap.tab_collision"))

        center_l.addWidget(grid_g, 1)

        # Stats / results group
        results_g = QGroupBox(tr("tilemap.group_export_results"))
        results_l = QVBoxLayout(results_g)
        results_l.setSpacing(2)

        self._stats_lbl = QLabel("")
        self._stats_lbl.setWordWrap(True)
        results_l.addWidget(self._stats_lbl)

        self._unique_lbl = QLabel("")
        self._unique_lbl.setWordWrap(True)
        results_l.addWidget(self._unique_lbl)

        self._result_lbl = QLabel("")
        self._result_lbl.setWordWrap(True)
        self._result_lbl.setStyleSheet("font-weight: bold;")
        results_l.addWidget(self._result_lbl)

        # Dual-layer hint (shown only when tiles exceed 3 colors)
        self._hint_lbl = QLabel(tr("tilemap.dual_hint"))
        self._hint_lbl.setWordWrap(True)
        self._hint_lbl.setStyleSheet("color: #e07030; font-size: 11px; padding: 4px;")
        self._hint_lbl.setVisible(False)
        results_l.addWidget(self._hint_lbl)

        export_l.addWidget(results_g)

        self._ctx_tilemap_limits = ContextHelpBox(
            tr("tilemap.ctx_limits_title"),
            tr("tilemap.ctx_limits_body"),
            self,
            expanded=False,
        )
        export_l.addWidget(self._ctx_tilemap_limits)

        # Run button
        run_row = QHBoxLayout()
        self._btn_run = QPushButton(tr("tilemap.run"))
        self._btn_run.setToolTip(tr("tilemap.run_tooltip"))
        self._btn_run.clicked.connect(self._run_tilemap)
        self._btn_run.setEnabled(False)
        run_row.addWidget(self._btn_run)
        self._run_status = QLabel("")
        self._run_status.setWordWrap(True)
        run_row.addWidget(self._run_status, 1)
        export_l.addLayout(run_row)
        workflow_l.addStretch(1)
        tools_l.addStretch(1)
        export_l.addStretch(1)

        self._right_tabs.addTab(tab_workflow, tr("tilemap.tab_workflow"))
        self._right_tabs.addTab(tab_tools, tr("tilemap.tab_tools"))
        self._right_tabs.addTab(tab_export, tr("tilemap.tab_export"))

        splitter.addWidget(center)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1180, 340])

        self.setAcceptDrops(True)

        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self._on_undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, activated=self._on_redo)
        QShortcut(QKeySequence.StandardKey.Save, self, activated=self._save_overwrite)
        QShortcut(QKeySequence.StandardKey.Copy, self, activated=self._copy_selection)
        QShortcut(QKeySequence.StandardKey.Cut, self, activated=self._cut_selection)
        QShortcut(QKeySequence.StandardKey.Paste, self, activated=self._paste_selection)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self, activated=self._delete_selection_tiles)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._clear_selection)
        QShortcut(QKeySequence.StandardKey.Open, self, activated=self._open_file)
        QShortcut(QKeySequence.StandardKey.New, self, activated=self._new_file)
        QShortcut(QKeySequence("F5"), self, activated=self._run_tilemap)
        self._rebuild_edit_shortcuts()
        self._refresh_checklist()


    # ------------------------------------------------------------------
    # Scene integration
    # ------------------------------------------------------------------

    def set_scene(self, scene: dict | None, base_dir: Path | None) -> None:
        """Attach the active scene so the tab can browse and edit its tilemaps."""
        self._scene_context = scene
        self._scene_base_dir = base_dir
        self._active_tm = None
        self._refresh_plane_ui()
        self._scene_pick.clear()
        self._btn_scene_open.setEnabled(False)
        if not scene or not base_dir:
            self._scene_lbl.setText(tr("tilemap.scene_none"))
            self._scene_lbl.setStyleSheet("color: gray; font-style: italic;")
            self._refresh_checklist()
            return

        self._scene_lbl.setText(scene.get("label", "?"))
        self._scene_lbl.setStyleSheet("")
        for tm in scene.get("tilemaps", []) or []:
            name = tm.get("name") or Path(tm.get("file", "")).stem or "?"
            fn = Path(tm.get("file", "?")).name
            self._scene_pick.addItem(f"{name}  —  {fn}", tm)
        self._btn_scene_open.setEnabled(self._scene_pick.count() > 0)
        self._refresh_checklist()

    def _open_scene_tilemap(self) -> None:
        if not self._scene_base_dir:
            return
        tm = self._scene_pick.currentData() or {}
        rel = tm.get("file", "")
        if not rel:
            return
        self._active_tm = tm
        path = Path(rel)
        if not path.is_absolute():
            path = self._scene_base_dir / path
        self._load(path)
        self._maybe_autoload_tileset(path)

    # ------------------------------------------------------------------
    # Zoom
    # ------------------------------------------------------------------

    _ZOOM_STEPS = [1, 2, 4, 8, 16, 32]

    def _set_zoom(self, zoom: int) -> None:
        self._zoom = zoom
        for z in self._ZOOM_STEPS:
            btn = getattr(self, f"_zoom_btn_{z}", None)
            if btn:
                btn.setChecked(z == zoom)
        if self._img is not None:
            self._grid.set_data(self._img, self._counts, self._zoom)
            self._grid_col.set_data(self._img, self._counts, self._zoom)

    def _zoom_step(self, direction: int) -> None:
        """Step zoom up (+1) or down (-1) through the fixed zoom levels."""
        steps = self._ZOOM_STEPS
        try:
            idx = steps.index(self._zoom)
        except ValueError:
            idx = steps.index(4)  # fallback to ×4 if somehow out of range
        new_idx = max(0, min(len(steps) - 1, idx + direction))
        self._set_zoom(steps[new_idx])

    def _on_gridlines_toggled(self, on: bool) -> None:
        self._show_grid_lines = bool(on)
        QSettings("NGPCraft", "Engine").setValue("tilemap/show_grid", bool(on))
        self._grid.update()
        self._grid_col.update()

    def _on_overlay_toggled(self, on: bool) -> None:
        self._show_color_overlay = bool(on)
        QSettings("NGPCraft", "Engine").setValue("tilemap/show_color_overlay", bool(on))
        self._grid.update()

    def _on_bezel_toggled(self, on: bool) -> None:
        self._show_bezel = bool(on)
        self._grid.update()

    # ------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------

    def _open_file(self) -> None: 
        start = QSettings("NGPCraft", "Engine").value("tilemap/last_dir", "", str)
        path, _ = QFileDialog.getOpenFileName( 
            self, tr("tilemap.open_file"), start, 
            tr("tilemap.file_filter"), 
        ) 
        if path: 
            self._load(Path(path)) 

    def _load(self, path: Path) -> None: 
        if self._dirty:
            if QMessageBox.question(self, tr("tilemap.confirm_title"), tr("tilemap.confirm_discard")) != QMessageBox.StandardButton.Yes:
                return
        try: 
            img = quantize_image(Image.open(path).convert("RGBA")) 
        except Exception as e: 
            self._file_lbl.setText(tr("tilemap.load_error", err=str(e))) 
            return 

        # Pad to 8-pixel boundary
        w, h = img.size
        pw = ((w + 7) // 8) * 8
        ph = ((h + 7) // 8) * 8
        if pw != w or ph != h:
            padded = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
            padded.paste(img, (0, 0))
            img = padded

        self._img = img 
        self._current_path = path 
        self._dirty = False 
        self._col_undo.clear()
        self._col_redo.clear()
        self._hover_tile = None
        self._brush_tile = None
        self._brush_img = None
        self._brush_bytes = None
        self._sel_rect = None
        self._sel_drag_start = None
        self._scr2_path = None
        self._undo.clear()
        QSettings("NGPCraft", "Engine").setValue("tilemap/last_dir", str(path.parent))
        self._counts = colors_per_tile(img) 
        self._counts_dirty = False
        self._col_basis_dirty = True
 
        self._grid.set_data(img, self._counts, self._zoom)
        self._grid_col.set_data(img, self._counts, self._zoom)
        self._drop_hint.setVisible(False)
        self._grid_tabs.setVisible(True)
        self._grid_row.setVisible(True)
        self._scroll.setVisible(True)
        self._col_row.setVisible(True)
        self._col_scroll.setVisible(True)
        self._file_lbl.setText(path.name)
        self._file_lbl.setStyleSheet("")
        self._btn_run.setEnabled(True) 
        self._run_status.setText("") 
        self._update_stats() 
        self._install_watcher()
        self._btn_save.setEnabled(True)
        self._btn_save_as.setEnabled(True)
        self._btn_resize.setEnabled(True)
        self._btn_split.setEnabled(True)
        self._btn_scr2_pick.setEnabled(True)
        self._btn_scr2_clear.setEnabled(True)
        self._btn_tileset_load.setEnabled(True)
        self._btn_tileset_reset.setEnabled(False)
        self._refresh_undo_ui()
        self._refresh_stamp_actions_ui()
        self._refresh_scr2_ui()
        self._brush_lbl.setText(tr("tilemap.brush_none"))
        self._brush_lbl.setStyleSheet("color: gray;")
        self._tileset_img = None
        self._tileset_path = None
        self._build_tileset(self._img, tileset_name=tr("tilemap.tileset_map"))
        self._tileset_g.setVisible(True)
        self._btn_brush_erase.setEnabled(True)

        # Always resolve from scene to avoid Qt QVariant copy issue:
        # _open_scene_tilemap sets _active_tm from currentData() which returns a
        # COPY of the dict — writes to that copy never reach scene["tilemaps"].
        self._active_tm = self._match_active_tilemap(path)
        # Auto-register in scene["tilemaps"] when not found — otherwise _active_tm
        # stays None, the "Sauver dans le projet" button stays disabled, and collision
        # data can never be written to the scene (silent data loss).
        if (self._active_tm is None
                and self._scene_context is not None
                and self._scene_base_dir is not None
                and self._on_save_fn
                and not self._is_free_mode):
            try:
                rel = str(path.resolve().relative_to(Path(self._scene_base_dir).resolve()))
            except ValueError:
                rel = str(path)
            # Avoid duplicates (path sep variants)
            rel_norm = rel.replace("\\", "/")
            existing = next(
                (tm for tm in self._scene_context.get("tilemaps", [])
                 if isinstance(tm, dict)
                 and str(tm.get("file", "")).replace("\\", "/") == rel_norm),
                None,
            )
            if existing is not None:
                self._active_tm = existing
            else:
                new_entry: dict = {"name": path.stem, "file": rel, "export": True}
                self._scene_context.setdefault("tilemaps", []).append(new_entry)
                self._active_tm = new_entry
                self._scene_pick.addItem(f"{path.stem}  —  {path.name}", new_entry)
                self._btn_scene_open.setEnabled(True)
        self._refresh_plane_ui()
        self._refresh_collision_from_project()
        self._maybe_autoload_tileset(path)

        # Ensure edit UI is in sync with the visible tab (bug: edit checkbox could stay disabled until a tab switch)
        try:
            self._grid_tabs.setCurrentIndex(0)
        except Exception:
            pass
        self._on_grid_tab_changed(int(self._grid_tabs.currentIndex() if self._grid_tabs is not None else 0))

    def open_path(self, path: Path) -> None:
        """Public helper used by other tabs (Asset Browser)."""
        self._load(path)

    # ------------------------------------------------------------------
    # Project integration (collision storage)
    # ------------------------------------------------------------------

    def _match_active_tilemap(self, abs_path: Path) -> dict | None:
        scene = self._scene_context or {}
        base = self._scene_base_dir
        if not base:
            return None
        try:
            tgt = abs_path.resolve()
        except Exception:
            tgt = abs_path
        for tm in scene.get("tilemaps", []) or []:
            rel = tm.get("file", "")
            if not rel:
                continue
            p = Path(rel)
            if not p.is_absolute():
                p = base / p
            try:
                if p.resolve() == tgt:
                    return tm
            except Exception:
                if str(p) == str(abs_path):
                    return tm
        return None

    def _save_project_now(self) -> None:
        if not self._on_save_fn:
            return
        try:
            self._on_save_fn()
        except Exception:
            pass

    def _schedule_project_save(self) -> None:
        if not self._on_save_fn:
            return
        self._save_timer.start(350)

    # ------------------------------------------------------------------
    # Project integration (tilemap metadata)
    # ------------------------------------------------------------------

    def _refresh_plane_ui(self) -> None:
        tm = self._active_tm if isinstance(self._active_tm, dict) else None
        can_edit = bool(tm is not None and self._on_save_fn and not self._is_free_mode)
        if getattr(self, "_plane_pick", None) is None:
            return
        self._plane_pick.setEnabled(can_edit)

        want = "auto"
        if tm is not None:
            v = tm.get("plane", "auto")
            if isinstance(v, str) and v in ("auto", "scr1", "scr2"):
                want = v

        idx = self._plane_pick.findData(want)
        if idx < 0:
            idx = self._plane_pick.findData("auto")
        if idx < 0:
            idx = 0

        self._plane_pick.blockSignals(True)
        self._plane_pick.setCurrentIndex(int(idx))
        self._plane_pick.blockSignals(False)
        self._refresh_checklist()

    def _on_plane_changed(self, _idx: int) -> None:
        tm = self._active_tm if isinstance(self._active_tm, dict) else None
        if tm is None or self._is_free_mode or not self._on_save_fn:
            return
        v = self._plane_pick.currentData()
        plane = str(v) if isinstance(v, str) else "auto"
        if plane not in ("auto", "scr1", "scr2"):
            plane = "auto"
        if tm.get("plane", "auto") == plane:
            self._refresh_checklist()
            return
        tm["plane"] = plane
        self._schedule_project_save()
        self._refresh_checklist()

    # ------------------------------------------------------------------
    # Collision editor
    # ------------------------------------------------------------------

    def _on_grid_tab_changed(self, idx: int) -> None:
        is_collision = idx == 1
        for w in (
            self._chk_edit,
            self._btn_tool_paint,
            self._btn_tool_pick,
            self._btn_tool_erase,
            self._btn_tool_fill,
            self._btn_tool_replace,
            self._btn_tool_select,
            self._btn_tool_stamp,
            self._btn_undo,
            self._btn_redo,
        ):
            w.setEnabled(not is_collision and self._img is not None)
        if hasattr(self, "_btn_col_preset_apply"):
            self._btn_col_preset_apply.setEnabled(bool(is_collision and self._img is not None and self._col_preset_pick.currentData() != "custom"))
        if is_collision:
            self._chk_edit.setChecked(False)
            if self._col_basis_dirty:
                self._refresh_collision_from_project()
            else:
                self._refresh_collision_ui_mode()
        else:
            self._refresh_undo_ui()

    def _default_collision_types(self) -> list[dict]:
        preset = self._scene_collision_preset_key()
        return [dict(x) for x in _COLLISION_PRESETS.get(preset, _COLLISION_PRESETS["basic"])]

    def _scene_collision_preset_key(self) -> str:
        scene = self._scene_context if isinstance(self._scene_context, dict) else None
        mode = str((scene or {}).get("map_mode", "") or "").strip().lower()
        if mode in ("platformer", "topdown", "shmup", "open"):
            return mode
        return "basic"

    def _detect_collision_preset(self, types: list[dict] | None) -> str:
        if not isinstance(types, list) or not types:
            return self._scene_collision_preset_key()

        def _sig(arr: list[dict]) -> tuple[tuple[str, int], ...]:
            out: list[tuple[str, int]] = []
            for t in arr:
                try:
                    out.append((str(t.get("name", "")).strip().upper(), int(t.get("value", 0))))
                except Exception:
                    continue
            return tuple(out)

        cur = _sig(types)
        for key, preset in _COLLISION_PRESETS.items():
            if cur == _sig(preset):
                return key
        return "custom"

    def _refresh_collision_preset_ui(self) -> None:
        if not hasattr(self, "_col_preset_pick"):
            return
        key = self._detect_collision_preset(self._col_types)
        idx = self._col_preset_pick.findData(key)
        if idx < 0:
            idx = self._col_preset_pick.findData("custom")
        self._col_preset_pick.blockSignals(True)
        if idx >= 0:
            self._col_preset_pick.setCurrentIndex(idx)
        self._col_preset_pick.blockSignals(False)
        can_apply = self._img is not None and (self._col_preset_pick.currentData() != "custom")
        self._btn_col_preset_apply.setEnabled(bool(can_apply))

    def _sanitize_collision_values(self, valid_values: set[int]) -> None:
        if not valid_values:
            return
        if self._col_assign:
            self._col_assign = [v if int(v) in valid_values else 0 for v in self._col_assign]
        if self._col_paint_grid:
            for y, row in enumerate(self._col_paint_grid):
                for x, v in enumerate(row):
                    if int(v) not in valid_values:
                        self._col_paint_grid[y][x] = 0
        if int(self._col_brush_value) not in valid_values:
            self._col_brush_value = 0

    def _apply_collision_preset(self) -> None:
        key = str(self._col_preset_pick.currentData() or "custom").strip().lower()
        if key == "custom":
            return
        preset = _COLLISION_PRESETS.get(key)
        if not preset:
            return
        self._col_types = [dict(x) for x in preset]
        valid_values = {int(t.get("value", 0)) for t in self._col_types}
        self._sanitize_collision_values(valid_values)
        if isinstance(self._active_tm, dict):
            self._active_tm["collision_types"] = list(self._col_types)
            self._active_tm["collision_mode"] = self._col_mode
            if self._col_mode == "paint":
                self._active_tm["collision_paint"] = [list(row) for row in self._col_paint_grid]
            else:
                self._active_tm["collision_tileset"] = list(self._col_assign)
            self._schedule_project_save()
        self._refresh_collision_from_project()
        self._run_status.setText(tr("tilemap.col_preset_applied", preset=tr(f"tilemap.col_preset_{key}")))
        self._run_status.setStyleSheet("color: gray;")

    def _col_dims(self) -> tuple[int, int]:
        if self._img is None:
            return 0, 0
        return int(self._img.width // 8), int(self._img.height // 8)

    def _normalize_collision_paint(self, raw: object) -> list[list[int]]:
        tw, th = self._col_dims()
        grid = [[0 for _x in range(tw)] for _y in range(th)]
        if not (isinstance(raw, list) and raw):
            return grid
        for y in range(min(th, len(raw))):
            row = raw[y]
            if not isinstance(row, list):
                continue
            for x in range(min(tw, len(row))):
                try:
                    grid[y][x] = int(row[x])
                except Exception:
                    grid[y][x] = 0
        return grid

    def _build_collision_basis_fallback(self) -> bool:
        if self._img is None:
            return False
        tw, th = self._col_dims()
        tile_to_idx: dict[bytes, int] = {}
        unique: list[bytes] = []
        map_ids: list[int] = []
        blank = bytes([0] * (8 * 8 * 4))
        for ty in range(th):
            for tx in range(tw):
                tile = self._tile_img_at(tx, ty)
                b = blank if tile is None else tile.tobytes()
                idx = tile_to_idx.get(b)
                if idx is None:
                    idx = len(unique)
                    tile_to_idx[b] = idx
                    unique.append(b)
                map_ids.append(idx)
        self._col_unique_rgba = unique
        self._col_map_ids = map_ids
        self._col_map_ids2 = []
        return True

    def _collision_grid_from_tileset(self) -> list[list[int]]:
        grid_vals: list[list[int]] = []
        tw, th = self._col_dims()
        for ty in range(th):
            row: list[int] = []
            for tx in range(tw):
                pos = ty * tw + tx
                tid = int(self._col_map_ids[pos]) if pos < len(self._col_map_ids) else 0
                v1 = int(self._col_assign[tid]) if 0 <= tid < len(self._col_assign) else 0
                has2 = pos < len(self._col_map_ids2)
                v2 = 0
                if has2:
                    tid2 = int(self._col_map_ids2[pos])
                    v2 = int(self._col_assign[tid2]) if 0 <= tid2 < len(self._col_assign) else 0

                mode = self._col_overlay_mode
                if mode == "scr1":
                    row.append(v1)
                elif mode == "scr2":
                    row.append(v2 if has2 else 0)
                else:
                    row.append(max(v1, v2) if has2 else v1)
            grid_vals.append(row)
        return grid_vals

    def _collision_tile_id_at(self, tx: int, ty: int) -> int | None:
        tw, th = self._col_dims()
        if not (0 <= tx < tw and 0 <= ty < th):
            return None
        pos = ty * tw + tx
        tid1 = int(self._col_map_ids[pos]) if pos < len(self._col_map_ids) else None
        tid2 = int(self._col_map_ids2[pos]) if pos < len(self._col_map_ids2) else None
        mode = str(self._col_overlay_mode or "max")
        if mode == "scr1" or tid2 is None:
            return tid1
        if mode == "scr2":
            return tid2 if tid2 is not None else tid1
        v1 = int(self._col_assign[tid1]) if tid1 is not None and 0 <= tid1 < len(self._col_assign) else 0
        v2 = int(self._col_assign[tid2]) if tid2 is not None and 0 <= tid2 < len(self._col_assign) else 0
        if tid2 is not None and v2 > v1:
            return tid2
        return tid1 if tid1 is not None else tid2

    def _select_collision_tile_from_map(self, tx: int, ty: int) -> bool:
        if self._col_mode == "paint":
            return False
        tid = self._collision_tile_id_at(tx, ty)
        if tid is None or not (0 <= tid < self._col_list.count()):
            return False
        self._col_list.setCurrentRow(int(tid))
        item = self._col_list.item(int(tid))
        if item is not None:
            self._col_list.scrollToItem(item)
        return True

    def _collision_grid_snapshot(self) -> _ColUndoState:
        tw, th = self._col_dims()
        flat: list[int] = []
        for row in self._col_paint_grid:
            for v in row:
                flat.append(int(v))
        return _ColUndoState(tw, th, tuple(flat))

    def _restore_collision_snapshot(self, snap: _ColUndoState) -> None:
        vals = list(snap.vals)
        grid: list[list[int]] = []
        idx = 0
        for _y in range(int(snap.h)):
            row = []
            for _x in range(int(snap.w)):
                row.append(int(vals[idx]) if idx < len(vals) else 0)
                idx += 1
            grid.append(row)
        self._col_paint_grid = grid

    def _push_col_undo(self) -> None:
        self._col_undo.append(self._collision_grid_snapshot())
        if len(self._col_undo) > 40:
            self._col_undo.pop(0)
        self._col_redo.clear()

    def _refresh_collision_ui_mode(self) -> None:
        is_paint = self._col_mode == "paint"
        self._col_list.setEnabled(not is_paint)
        self._col_list.setVisible(not is_paint)
        mode_idx = self._col_mode_pick.findData(self._col_mode)
        if mode_idx >= 0 and self._col_mode_pick.currentIndex() != mode_idx:
            self._col_mode_pick.blockSignals(True)
            self._col_mode_pick.setCurrentIndex(mode_idx)
            self._col_mode_pick.blockSignals(False)
        if self._col_type.count() > 0:
            if is_paint:
                idx = self._col_type.findData(int(self._col_brush_value))
                if idx >= 0 and self._col_type.currentIndex() != idx:
                    self._col_type.blockSignals(True)
                    self._col_type.setCurrentIndex(idx)
                    self._col_type.blockSignals(False)
            else:
                self._on_col_tile_selected(int(self._col_list.currentRow()))
        self._refresh_undo_ui()

    def _collision_colors(self, types: list[dict]) -> dict[int, QColor]:
        palette = [
            QColor(255, 40, 40, 70),    # red
            QColor(40, 120, 255, 70),   # blue
            QColor(40, 220, 90, 70),    # green
            QColor(255, 210, 40, 80),   # yellow
            QColor(220, 40, 220, 70),   # magenta
            QColor(40, 220, 220, 70),   # cyan
            QColor(255, 140, 40, 70),   # orange
            QColor(160, 160, 160, 70),  # gray
        ]
        colors: dict[int, QColor] = {}
        k = 0
        for t in types:
            v = int(t.get("value", 0))
            name = str(t.get("name", "")).strip().upper()
            if v == 0 or name in ("NONE", "EMPTY", "AIR"):
                colors[v] = QColor(0, 0, 0, 0)
                continue
            if v in colors and colors[v].alpha() > 0:
                continue
            colors[v] = palette[k % len(palette)]
            k += 1
        return colors

    def _collision_labels(self, types: list[dict]) -> dict[int, str]:
        out: dict[int, str] = {}
        for t in types:
            try:
                out[int(t.get("value", 0))] = str(t.get("name", ""))
            except Exception:
                continue
        return out

    def _refresh_collision_from_project(self) -> None:
        if self._img is None:
            self._col_g.setVisible(False)
            self._col_scroll.setVisible(False)
            self._grid_col.set_collision_overlay(None, None, None)
            self._refresh_checklist()
            return

        if self._current_path is None or not self._current_path.exists():
            self._col_g.setVisible(True)
            self._col_scroll.setVisible(True)
            self._col_info.setText(tr("tilemap.col_need_saved"))
            self._btn_col_export.setEnabled(False)
            self._btn_col_reset.setEnabled(False)
            self._btn_col_save.setEnabled(False)
            self._grid_col.set_collision_overlay(None, None, None)
            self._col_basis_dirty = True
            self._refresh_checklist()
            return

        self._col_info.setText("")

        # Load overlay mode + types + assignment from project (if available)
        tm = self._active_tm
        mode = self._col_mode if self._col_mode in ("tileset", "paint") else "tileset"
        if isinstance(tm, dict):
            cm = str(tm.get("collision_mode", "tileset") or "tileset").strip().lower()
            if cm in ("tileset", "paint"):
                mode = cm
            cmode = tm.get("collision_overlay")
            if isinstance(cmode, str) and cmode in ("max", "scr1", "scr2"):
                if cmode != self._col_overlay_mode:
                    self._col_overlay_mode = cmode
                    idx = self._col_overlay.findData(cmode)
                    if idx >= 0:
                        self._col_overlay.blockSignals(True)
                        self._col_overlay.setCurrentIndex(idx)
                        self._col_overlay.blockSignals(False)
        types = (tm.get("collision_types") if isinstance(tm, dict) else None) or None
        if not isinstance(types, list) or not types:
            types = self._default_collision_types()
        self._col_types = list(types)
        self._refresh_collision_preset_ui()
        labels = self._collision_labels(self._col_types)
        colors = self._collision_colors(self._col_types)

        need_basis = self._col_basis_dirty or (not self._col_unique_rgba) or (not self._col_map_ids)
        if need_basis:
            ok = self._recompute_collision_basis()
            if not ok:
                self._col_g.setVisible(True)
                self._col_scroll.setVisible(True)
                if not (self._col_info.text() or "").strip():
                    self._col_info.setText(tr("tilemap.col_no_basis"))
                self._btn_col_export.setEnabled(False)
                self._btn_col_reset.setEnabled(False)
                self._btn_col_save.setEnabled(False)
                self._grid_col.set_collision_overlay(None, None, None)
                self._refresh_checklist()
                return
            self._col_basis_dirty = False

        assign = []
        if isinstance(tm, dict):
            got = tm.get("collision_tileset")
            if isinstance(got, list):
                assign = [int(x) if isinstance(x, (int, float)) else 0 for x in got]
        if not assign:
            assign = [0 for _ in range(len(self._col_unique_rgba))]
        if len(assign) < len(self._col_unique_rgba):
            assign.extend([0] * (len(self._col_unique_rgba) - len(assign)))
        if len(assign) > len(self._col_unique_rgba):
            assign = assign[: len(self._col_unique_rgba)]
        self._col_assign = assign

        has_scr2 = bool(self._col_map_ids2)
        self._update_col_overlay_availability(has_scr2)
        if not has_scr2 and self._col_overlay_mode == "scr2":
            self._col_overlay_mode = "scr1"
            idx = self._col_overlay.findData("scr1")
            if idx >= 0:
                self._col_overlay.blockSignals(True)
                self._col_overlay.setCurrentIndex(idx)
                self._col_overlay.blockSignals(False)
        self._col_mode = mode
        if self._col_mode == "paint":
            stored = tm.get("collision_paint") if isinstance(tm, dict) else None
            if isinstance(stored, list) and stored:
                self._col_paint_grid = self._normalize_collision_paint(stored)
            else:
                self._col_paint_grid = self._collision_grid_from_tileset()
        elif not self._col_paint_grid:
            self._col_paint_grid = self._normalize_collision_paint(None)

        grid_vals = self._col_paint_grid if self._col_mode == "paint" else self._collision_grid_from_tileset()

        self._grid_col.set_collision_overlay(grid_vals, colors, labels)

        # Rebuild UI list/combobox if needed, otherwise just refresh colors.
        need_rebuild_ui = (
            need_basis
            or self._col_list.count() != len(self._col_unique_rgba)
            or self._col_type.count() != len(self._col_types)
        )
        sel = self._col_list.currentRow()
        if need_rebuild_ui:
            self._col_list.clear()
            self._col_type.blockSignals(True)
            self._col_type.clear()
            for t in self._col_types:
                name = str(t.get("name", "?"))
                v = int(t.get("value", 0))
                self._col_type.addItem(f"{name} ({v})", v)
            self._col_type.blockSignals(False)

            for idx, rgba in enumerate(self._col_unique_rgba):
                item = QListWidgetItem(f"{idx}")
                item.setIcon(self._tile_icon(rgba))
                self._col_list.addItem(item)

        # Update item backgrounds from current assignment
        for idx in range(self._col_list.count()):
            item = self._col_list.item(idx)
            if item is None:
                continue
            val = int(self._col_assign[idx]) if idx < len(self._col_assign) else 0
            c = colors.get(val, QColor(0, 0, 0, 0))
            if c.alpha() > 0:
                item.setBackground(QBrush(QColor(c.red(), c.green(), c.blue(), 60)))
            else:
                item.setBackground(QBrush())

        if self._col_mode == "paint":
            tw, th = self._col_dims()
            self._col_info.setText(tr("tilemap.col_info_paint", w=tw, h=th))
        else:
            self._col_info.setText(tr("tilemap.col_info", n=len(self._col_unique_rgba)))
        self._col_g.setVisible(True)
        self._col_scroll.setVisible(True)
        self._btn_col_export.setEnabled(True)
        self._btn_col_reset.setEnabled(True)
        self._btn_col_save.setEnabled(bool(isinstance(tm, dict) and self._on_save_fn and not self._is_free_mode))

        if self._col_list.count() > 0:
            if sel < 0:
                sel = 0
            self._col_list.setCurrentRow(min(sel, self._col_list.count() - 1))
        self._refresh_collision_preset_ui()
        self._refresh_collision_ui_mode()
        self._refresh_checklist()

    def _recompute_collision_basis(self) -> bool:
        self._col_unique_rgba = []
        self._col_map_ids = []
        self._col_map_ids2 = []
        if self._img is None:
            return False

        tw = self._img.width // 8
        th = self._img.height // 8

        script = self._find_script()
        if script is None:
            return self._build_collision_basis_fallback()

        try:
            spec = importlib.util.spec_from_file_location("_ngpc_tilemap_mod", str(script))
            if spec is None or spec.loader is None:
                return self._build_collision_basis_fallback()
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            _tile_w, _tile_h, tiles, tile_sets = mod.extract_tiles(str(self._current_path), strict=False)
            if mod.needs_layer_split(tile_sets) and not (self._scr2_path and self._scr2_path.exists()):
                # Match ngpc_tilemap.py auto-split behavior (SCR1+SCR2 from a single PNG).
                s1t, s1s, s2t, s2s, _split_n = mod.split_layers(tiles, tile_sets)
                pals1, tpids1 = mod.assign_palettes(s1s, 16)
                pals2, tpids2 = mod.assign_palettes(s2s, 16)
                _pcols1, pimaps1 = mod.build_palette_index_maps(pals1, s1t, tpids1)
                _pcols2, pimaps2 = mod.build_palette_index_maps(pals2, s2t, tpids2)
                pool, pool_idx, map_t1, _map_p1 = mod.encode_tiles_and_map(s1t, tpids1, pimaps1, True)
                pool, _, map_t2, _map_p2 = mod.encode_tiles_and_map(
                    s2t, tpids2, pimaps2, True, tile_pool=pool, tile_pool_index=pool_idx
                )

                icons: list[bytes | None] = [None] * len(pool)
                for pos, tid in enumerate(map_t1):
                    if icons[tid] is None:
                        tx = pos % tw
                        ty = pos // tw
                        tile = self._tile_img_at(tx, ty)
                        if tile is not None:
                            icons[tid] = tile.tobytes()
                for pos, tid in enumerate(map_t2):
                    if icons[tid] is None:
                        tx = pos % tw
                        ty = pos // tw
                        tile = self._tile_img_at(tx, ty)
                        if tile is not None:
                            icons[tid] = tile.tobytes()

                self._col_unique_rgba = [b if b is not None else bytes([0] * (8 * 8 * 4)) for b in icons]
                self._col_map_ids = list(map_t1)
                self._col_map_ids2 = list(map_t2)
                return True

            if self._scr2_path and self._scr2_path.exists():
                tw2, th2, tiles2, tsets2 = mod.extract_tiles(str(self._scr2_path), strict=True)
                pals1, tpids1 = mod.assign_palettes(tile_sets, 16)
                pals2, tpids2 = mod.assign_palettes(tsets2, 16)
                _pcols1, pimaps1 = mod.build_palette_index_maps(pals1, tiles, tpids1)
                _pcols2, pimaps2 = mod.build_palette_index_maps(pals2, tiles2, tpids2)
                pool, pool_idx, map_t1, _map_p1 = mod.encode_tiles_and_map(tiles, tpids1, pimaps1, True)
                pool, _, _map_t2, _map_p2 = mod.encode_tiles_and_map(
                    tiles2, tpids2, pimaps2, True, tile_pool=pool, tile_pool_index=pool_idx
                )

                # capture icons from SCR1 then SCR2 for missing
                icons: list[bytes | None] = [None] * len(pool)
                for pos, tid in enumerate(map_t1):
                    if icons[tid] is None:
                        tx = pos % tw
                        ty = pos // tw
                        tile = self._tile_img_at(tx, ty)
                        if tile is not None:
                            icons[tid] = tile.tobytes()
                img2 = quantize_image(Image.open(self._scr2_path).convert("RGBA"))
                for pos, tid in enumerate(_map_t2):
                    if icons[tid] is None:
                        tx = pos % tw2
                        ty = pos // tw2
                        tile = img2.crop((tx * 8, ty * 8, tx * 8 + 8, ty * 8 + 8)).convert("RGBA")
                        icons[tid] = tile.tobytes()

                self._col_unique_rgba = [b if b is not None else bytes([0] * (8 * 8 * 4)) for b in icons]
                self._col_map_ids = list(map_t1)
                self._col_map_ids2 = list(_map_t2)
                return True

            pals, tpids = mod.assign_palettes(tile_sets, 16)
            _pcols, pimaps = mod.build_palette_index_maps(pals, tiles, tpids)
            pool, _pool_idx, map_t, _map_p = mod.encode_tiles_and_map(tiles, tpids, pimaps, True)

            icons: list[bytes | None] = [None] * len(pool)
            for pos, tid in enumerate(map_t):
                if icons[tid] is None:
                    tx = pos % tw
                    ty = pos // tw
                    tile = self._tile_img_at(tx, ty)
                    if tile is not None:
                        icons[tid] = tile.tobytes()
            self._col_unique_rgba = [b if b is not None else bytes([0] * (8 * 8 * 4)) for b in icons]
            self._col_map_ids = list(map_t)
            return True
        except Exception:
            return self._build_collision_basis_fallback()

    def _on_col_tile_selected(self, row: int) -> None:
        if self._col_mode == "paint":
            return
        if row < 0 or row >= len(self._col_assign):
            return
        val = int(self._col_assign[row])
        for i in range(self._col_type.count()):
            if int(self._col_type.itemData(i) or 0) == val:
                self._col_type.blockSignals(True)
                self._col_type.setCurrentIndex(i)
                self._col_type.blockSignals(False)
                break

    def _on_col_type_changed(self, _idx: int) -> None:
        if self._col_mode == "paint":
            self._col_brush_value = int(self._col_type.currentData() or 0)
            return
        row = int(self._col_list.currentRow())
        if row < 0 or row >= len(self._col_assign):
            return
        val = int(self._col_type.currentData() or 0)
        self._col_assign[row] = val
        if isinstance(self._active_tm, dict):
            self._active_tm["collision_mode"] = "tileset"
            self._active_tm["collision_types"] = list(self._col_types)
            self._active_tm["collision_tileset"] = list(self._col_assign)
            try:
                self._active_tm["collision_grid"] = self._collision_grid_from_tileset()
            except Exception:
                self._active_tm.pop("collision_grid", None)
            self._schedule_project_save()
        self._refresh_collision_from_project()

    def _update_col_overlay_availability(self, has_scr2: bool) -> None:
        model = self._col_overlay.model()
        if model is None or not hasattr(model, "item"):
            return
        try:
            # index 2 = "scr2"
            model.item(2).setEnabled(has_scr2)
        except Exception:
            pass

    def _on_col_overlay_changed(self, _idx: int) -> None:
        mode = str(self._col_overlay.currentData() or "max")
        if mode not in ("max", "scr1", "scr2"):
            mode = "max"
        self._col_overlay_mode = mode
        QSettings("NGPCraft", "Engine").setValue("tilemap/col_overlay", mode)
        if isinstance(self._active_tm, dict):
            self._active_tm["collision_overlay"] = mode
            self._schedule_project_save()
        self._refresh_collision_from_project()

    def _seed_tileset_assign_from_paint(self) -> None:
        if not self._col_assign or not self._col_paint_grid:
            return
        tw, th = self._col_dims()
        seen: set[int] = set()
        for ty in range(th):
            row = self._col_paint_grid[ty] if ty < len(self._col_paint_grid) else []
            for tx in range(tw):
                pos = ty * tw + tx
                if pos >= len(self._col_map_ids):
                    continue
                tid = int(self._col_map_ids[pos])
                if tid in seen or not (0 <= tid < len(self._col_assign)):
                    continue
                seen.add(tid)
                val = int(row[tx]) if tx < len(row) else 0
                self._col_assign[tid] = val

    def _on_col_mode_changed(self, _idx: int) -> None:
        mode = str(self._col_mode_pick.currentData() or "tileset").strip().lower()
        if mode not in ("tileset", "paint"):
            mode = "tileset"
        if mode == self._col_mode:
            self._refresh_collision_ui_mode()
            return
        if mode == "paint":
            self._col_paint_grid = self._collision_grid_from_tileset()
            self._col_undo.clear()
            self._col_redo.clear()
        else:
            self._seed_tileset_assign_from_paint()
        self._col_mode = mode
        if isinstance(self._active_tm, dict):
            self._active_tm["collision_mode"] = self._col_mode
            self._active_tm["collision_types"] = list(self._col_types or self._default_collision_types())
            self._active_tm["collision_tileset"] = list(self._col_assign)
            if self._col_mode == "paint":
                self._active_tm["collision_paint"] = [list(row) for row in self._col_paint_grid]
                self._active_tm["collision_grid"] = [list(row) for row in self._col_paint_grid]
            else:
                self._active_tm.pop("collision_paint", None)
                try:
                    self._active_tm["collision_grid"] = self._collision_grid_from_tileset()
                except Exception:
                    self._active_tm.pop("collision_grid", None)
            self._schedule_project_save()
        self._refresh_collision_from_project()

    def _col_reset_all(self) -> None:
        if self._col_mode == "paint":
            tw, th = self._col_dims()
            self._col_paint_grid = [[0 for _x in range(tw)] for _y in range(th)]
            self._col_undo.clear()
            self._col_redo.clear()
            if isinstance(self._active_tm, dict):
                self._active_tm["collision_mode"] = "paint"
                self._active_tm["collision_types"] = list(self._col_types or self._default_collision_types())
                self._active_tm["collision_paint"] = [list(row) for row in self._col_paint_grid]
                self._schedule_project_save()
            self._refresh_collision_from_project()
            return
        if not self._col_assign:
            return
        self._col_assign = [0 for _ in self._col_assign]
        if isinstance(self._active_tm, dict):
            self._active_tm["collision_mode"] = "tileset"
            self._active_tm["collision_types"] = list(self._col_types or self._default_collision_types())
            self._active_tm["collision_tileset"] = list(self._col_assign)
            self._active_tm.pop("collision_grid", None)
            self._schedule_project_save()
        self._refresh_collision_from_project()

    def _col_save_to_project(self) -> None:
        if not (isinstance(self._active_tm, dict) and self._on_save_fn and not self._is_free_mode):
            return
        self._active_tm["collision_mode"] = self._col_mode
        self._active_tm["collision_types"] = list(self._col_types or self._default_collision_types())
        if self._col_mode == "paint":
            self._active_tm["collision_paint"] = [list(row) for row in self._col_paint_grid]
            self._active_tm["collision_grid"] = [list(row) for row in self._col_paint_grid]
        else:
            self._active_tm["collision_tileset"] = list(self._col_assign)
            self._active_tm.pop("collision_paint", None)
            try:
                self._active_tm["collision_grid"] = self._collision_grid_from_tileset()
            except Exception:
                self._active_tm.pop("collision_grid", None)
        self._save_project_now()
        self._run_status.setText(tr("tilemap.col_saved"))
        self._run_status.setStyleSheet("color: #4ec94e;")
        self._refresh_checklist()

    def _col_export_header(self) -> None:
        if self._current_path is None:
            return
        base = self._current_path.stem
        name = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in base)
        if name and name[0].isdigit():
            name = "_" + name
        out = self._current_path.with_name(base + "_col.h")
        types = self._col_types or self._default_collision_types()
        labels = self._collision_labels(types)
        lines: list[str] = []
        lines.append("/* Generated by NgpCraft Engine - do not edit */")
        lines.append("/* Collision table for tilemap: %s */" % self._current_path.name)
        lines.append("")
        guard = (name + "_COL_H").upper()
        lines.append("#ifndef %s" % guard)
        lines.append("#define %s" % guard)
        lines.append("")
        lines.append('#include "ngpc_types.h"')
        lines.append("")
        for t in types:
            n = str(t.get("name", "")).upper()
            v = int(t.get("value", 0))
            macro = "COL_" + "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in n)
            lines.append("#define %-12s %d" % (macro, v))
        lines.append("")
        if self._col_mode == "paint":
            tw, th = self._col_dims()
            lines.append("#define %s_COL_MAP_W %d" % (name.upper(), tw))
            lines.append("#define %s_COL_MAP_H %d" % (name.upper(), th))
            lines.append("")
            arr_name = "g_%s_col_map" % name
            lines.append("/* Indexed by map tile (x + y * %s_COL_MAP_W) */" % name.upper())
            lines.append("static const u8 %s[%d] = {" % (arr_name, tw * th))
            flat_idx = 0
            for row in self._col_paint_grid:
                for v in row:
                    macro = labels.get(int(v), "")
                    token = "COL_" + "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in macro.upper()) if macro else str(int(v))
                    comma = "," if flat_idx + 1 < (tw * th) else ""
                    lines.append("    %s%s  /* cell %d */" % (token, comma, flat_idx))
                    flat_idx += 1
            lines.append("};")
        else:
            if not self._col_assign:
                return
            arr_name = "g_%s_col" % name
            lines.append("/* Indexed by tile index (same order as %s_tiles[] in %s_map.c) */" % (name, base))
            lines.append("static const u8 %s[%d] = {" % (arr_name, len(self._col_assign)))
            for i, v in enumerate(self._col_assign):
                macro = labels.get(int(v), "")
                if macro:
                    token = "COL_" + "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in macro.upper())
                else:
                    token = str(int(v))
                comma = "," if i + 1 < len(self._col_assign) else ""
                lines.append("    %s%s  /* tile %d */" % (token, comma, i))
            lines.append("};")
        lines.append("")
        lines.append("#endif /* %s */" % guard)
        lines.append("")
        try:
            out.write_text("\n".join(lines), encoding="utf-8")
            self._run_status.setText(tr("tilemap.col_export_ok", path=out.name))
            self._run_status.setStyleSheet("color: #4ec94e;")
        except Exception as e:
            self._run_status.setText(tr("tilemap.col_export_fail", err=str(e)))
            self._run_status.setStyleSheet("color: #e07030;")

    def _new_file(self) -> None:
        if self._dirty:
            if QMessageBox.question(self, tr("tilemap.confirm_title"), tr("tilemap.confirm_discard")) != QMessageBox.StandardButton.Yes:
                return

        prev_tileset_img = self._tileset_img
        prev_tileset_path = self._tileset_path

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("tilemap.new_title"))
        form = QFormLayout(dlg)

        limits = QLabel(tr("tilemap.size_limits_tt"))
        limits.setWordWrap(True)
        limits.setStyleSheet("color: #888; font-size: 11px;")
        form.addRow(limits)

        w_sp = QSpinBox()
        w_sp.setRange(1, 512)
        w_sp.setValue(QSettings("NGPCraft", "Engine").value("tilemap/new_w_tiles", 20, int))
        w_sp.setToolTip(tr("tilemap.size_limits_tt"))
        h_sp = QSpinBox()
        h_sp.setRange(1, 512)
        h_sp.setValue(QSettings("NGPCraft", "Engine").value("tilemap/new_h_tiles", 19, int))
        h_sp.setToolTip(tr("tilemap.size_limits_tt"))

        form.addRow(tr("tilemap.new_w"), w_sp)
        form.addRow(tr("tilemap.new_h"), h_sp)

        keep_tileset_cb: QCheckBox | None = None
        if prev_tileset_img is not None:
            keep_tileset_cb = QCheckBox(tr("tilemap.new_keep_tileset"))
            keep_tileset_cb.setToolTip(tr("tilemap.new_keep_tileset_tt"))
            keep_tileset_cb.setChecked(QSettings("NGPCraft", "Engine").value("tilemap/new_keep_tileset", True, bool))
            form.addRow(keep_tileset_cb)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        w_tiles = int(w_sp.value())
        h_tiles = int(h_sp.value())
        QSettings("NGPCraft", "Engine").setValue("tilemap/new_w_tiles", w_tiles)
        QSettings("NGPCraft", "Engine").setValue("tilemap/new_h_tiles", h_tiles)
        keep_tileset = bool(keep_tileset_cb.isChecked()) if keep_tileset_cb is not None else False
        if keep_tileset_cb is not None:
            QSettings("NGPCraft", "Engine").setValue("tilemap/new_keep_tileset", keep_tileset)

        img = Image.new("RGBA", (w_tiles * 8, h_tiles * 8), (0, 0, 0, 0))
        self._img = img
        self._current_path = None
        self._dirty = True
        self._col_undo.clear()
        self._col_redo.clear()
        self._hover_tile = None
        self._brush_tile = None
        self._brush_img = None
        self._brush_bytes = None
        self._sel_rect = None
        self._sel_drag_start = None
        self._scr2_path = None
        self._undo.clear()
        self._counts = colors_per_tile(img)
        self._counts_dirty = False
        self._col_basis_dirty = True
 
        self._grid.set_data(img, self._counts, self._zoom)
        self._drop_hint.setVisible(False)
        self._grid_tabs.setVisible(True)
        self._grid_row.setVisible(True)
        self._scroll.setVisible(True)
        self._grid_col.set_data(img, self._counts, self._zoom)
        self._col_row.setVisible(True)
        self._col_scroll.setVisible(True)
        self._file_lbl.setText(tr("tilemap.unsaved_file"))
        self._file_lbl.setStyleSheet("")
        self._run_status.setText(tr("tilemap.unsaved_hint"))
        self._run_status.setStyleSheet("color: gray;")
        self._update_stats()
        self._install_watcher()

        self._btn_save.setEnabled(True)
        self._btn_save_as.setEnabled(True)
        self._btn_resize.setEnabled(True)
        self._btn_split.setEnabled(False)
        self._btn_scr2_pick.setEnabled(False)
        self._btn_scr2_clear.setEnabled(False)
        self._btn_run.setEnabled(False)
        self._btn_tileset_load.setEnabled(True)
        self._btn_tileset_reset.setEnabled(False)
        self._refresh_undo_ui()
        self._refresh_stamp_actions_ui()
        self._refresh_scr2_ui()

        self._brush_lbl.setText(tr("tilemap.brush_none"))
        self._brush_lbl.setStyleSheet("color: gray;")
        if keep_tileset and prev_tileset_img is not None:
            self._tileset_img = prev_tileset_img
            self._tileset_path = prev_tileset_path
            ts_name = prev_tileset_path.name if prev_tileset_path is not None else tr("tilemap.tileset_load")
            self._build_tileset(prev_tileset_img, tileset_name=ts_name)
            self._btn_tileset_reset.setEnabled(True)
        else:
            self._tileset_img = None
            self._tileset_path = None
            self._build_tileset(self._img, tileset_name=tr("tilemap.tileset_map"))
            self._btn_tileset_reset.setEnabled(False)
        self._tileset_g.setVisible(True)
        self._btn_brush_erase.setEnabled(True)

        self._active_tm = None
        self._refresh_plane_ui()
        self._refresh_collision_from_project()

        # Keep edit UI usable immediately (no need to switch to Collision and back)
        try:
            self._grid_tabs.setCurrentIndex(0)
        except Exception:
            pass
        self._on_grid_tab_changed(int(self._grid_tabs.currentIndex() if self._grid_tabs is not None else 0))

    def _resize_canvas(self) -> None:
        if self._img is None:
            return

        if self._scr2_path and self._scr2_path.exists():
            if QMessageBox.question(self, tr("tilemap.resize_title"), tr("tilemap.resize_scr2_msg")) != QMessageBox.StandardButton.Yes:
                return
            self._scr2_path = None
            self._refresh_scr2_ui()
            self._col_basis_dirty = True

        cur_w_tiles = self._img.width // 8
        cur_h_tiles = self._img.height // 8

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("tilemap.resize_title"))
        form = QFormLayout(dlg)

        limits = QLabel(tr("tilemap.size_limits_tt"))
        limits.setWordWrap(True)
        limits.setStyleSheet("color: #888; font-size: 11px;")
        form.addRow(limits)

        w_sp = QSpinBox()
        w_sp.setRange(1, 1024)
        w_sp.setValue(cur_w_tiles)
        w_sp.setToolTip(tr("tilemap.size_limits_tt"))
        h_sp = QSpinBox()
        h_sp.setRange(1, 1024)
        h_sp.setValue(cur_h_tiles)
        h_sp.setToolTip(tr("tilemap.size_limits_tt"))
        form.addRow(tr("tilemap.resize_w"), w_sp)
        form.addRow(tr("tilemap.resize_h"), h_sp)

        anchor = QComboBox()
        anchor.addItem(tr("tilemap.anchor_tl"), (0, 0))
        anchor.addItem(tr("tilemap.anchor_tc"), (1, 0))
        anchor.addItem(tr("tilemap.anchor_tr"), (2, 0))
        anchor.addItem(tr("tilemap.anchor_cl"), (0, 1))
        anchor.addItem(tr("tilemap.anchor_cc"), (1, 1))
        anchor.addItem(tr("tilemap.anchor_cr"), (2, 1))
        anchor.addItem(tr("tilemap.anchor_bl"), (0, 2))
        anchor.addItem(tr("tilemap.anchor_bc"), (1, 2))
        anchor.addItem(tr("tilemap.anchor_br"), (2, 2))
        anchor.setToolTip(tr("tilemap.resize_anchor_tt"))
        anchor.setCurrentIndex(int(QSettings("NGPCraft", "Engine").value("tilemap/resize_anchor", 0, int)))
        form.addRow(tr("tilemap.resize_anchor"), anchor)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_w_tiles = int(w_sp.value())
        new_h_tiles = int(h_sp.value())
        QSettings("NGPCraft", "Engine").setValue("tilemap/resize_anchor", int(anchor.currentIndex()))

        if new_w_tiles == cur_w_tiles and new_h_tiles == cur_h_tiles:
            return

        ax, ay = anchor.currentData() or (0, 0)
        ax = int(ax)
        ay = int(ay)

        new_w_px = new_w_tiles * 8
        new_h_px = new_h_tiles * 8
        old_w_px = self._img.width
        old_h_px = self._img.height

        dx = 0 if ax == 0 else ((new_w_px - old_w_px) // 2 if ax == 1 else (new_w_px - old_w_px))
        dy = 0 if ay == 0 else ((new_h_px - old_h_px) // 2 if ay == 1 else (new_h_px - old_h_px))

        self._undo.push(self._img)
        out = Image.new("RGBA", (new_w_px, new_h_px), (0, 0, 0, 0))
        out.paste(self._img, (dx, dy))
        self._img = out
        self._dirty = True
        self._sel_rect = None
        self._sel_drag_start = None
        self._counts = colors_per_tile(self._img)
        self._counts_dirty = False
        self._grid.set_data(self._img, self._counts, self._zoom)
        self._grid_col.set_data(self._img, self._counts, self._zoom)
        if self._tileset_img is None:
            self._build_tileset(self._img, tileset_name=tr("tilemap.tileset_map"))
        self._col_basis_dirty = True
        self._refresh_collision_from_project()
        self._update_stats()
        self._refresh_undo_ui()

    def _install_watcher(self) -> None:
        self._watcher.removePaths(self._watcher.files())
        if self._current_path and self._current_path.exists():
            self._watcher.addPath(str(self._current_path))

    def _on_file_changed(self, _path: str) -> None:
        if not getattr(self, "_auto_reload", None) or not self._auto_reload.isChecked():
            return
        self._reload_timer.start(250)

    def _reload_from_disk(self) -> None:
        if self._current_path is None:
            return
        if not self._current_path.exists():
            self._reload_timer.start(350)
            return
        if self._dirty:
            if QMessageBox.question(self, tr("tilemap.reload_title"), tr("tilemap.reload_msg", path=self._current_path.name)) != QMessageBox.StandardButton.Yes:
                self._install_watcher()
                return
        self._load(self._current_path)

    def _update_stats(self) -> None:
        counts_flat = [c for row in self._counts for c in row]
        total = len(counts_flat)
        ok = sum(1 for c in counts_flat if c <= 3)
        warn = sum(1 for c in counts_flat if c == 4)
        err = sum(1 for c in counts_flat if c >= 5)
        self._stats_lbl.setText(
            tr("tilemap.stats", total=total, ok=ok, warn=warn, err=err)
        )
        needs_dual = err > 0 or warn > 0
        if needs_dual:
            self._result_lbl.setText(tr("tilemap.result_dual"))
            self._result_lbl.setStyleSheet("font-weight: bold; color: #e07030;")
        else:
            self._result_lbl.setText(tr("tilemap.result_single"))
            self._result_lbl.setStyleSheet("font-weight: bold; color: #4ec94e;")
        self._hint_lbl.setVisible(needs_dual)

        # Estimate unique tiles by hashing each 8×8 block
        n_unique = self._count_unique_tiles()
        if n_unique > 384:
            _u_css, _u_badge = "color: #e05050; font-weight: bold;", " 🔴"
        elif n_unique > 320:
            _u_css, _u_badge = "color: #e07030;", " 🔶"
        elif n_unique > 256:
            _u_css, _u_badge = "color: #e0a03a;", " ⚠"
        else:
            _u_css, _u_badge = "color: #4ec94e;", ""
        self._unique_lbl.setText(tr("tilemap.unique", n=n_unique, total=total) + _u_badge)
        self._unique_lbl.setStyleSheet(_u_css)

        self._update_size_limits_ui()
        self._refresh_checklist()

    def _check_item_html(self, status: str, title: str, detail: str) -> str:
        tag, color = {
            "ok": ("OK", "#4ec94e"),
            "warn": ("!", "#e0a03a"),
            "bad": ("KO", "#e07030"),
            "skip": ("-", "#7f8a96"),
        }.get(status, ("?", "#b8c0ca"))
        body = f"<b>{title}</b>"
        if detail:
            body += f" : {detail}"
        return f"<span style='color:{color}; font-weight:600;'>[{tag}]</span> {body}"

    def _refresh_checklist(self) -> None:
        if not hasattr(self, "_lbl_checklist"):
            return

        img_ok = self._img is not None
        file_ok = self._current_path is not None and self._current_path.exists()
        tm = self._active_tm if isinstance(self._active_tm, dict) else None
        has_project_link = bool(tm is not None and self._on_save_fn and not self._is_free_mode)
        script_ok = self._find_script() is not None

        source_status = "ok" if file_ok and not self._dirty else ("warn" if img_ok else "bad")
        if file_ok and self._current_path is not None:
            source_detail = self._current_path.name
            if self._dirty:
                source_detail += "  (" + tr("tilemap.check_source_dirty") + ")"
        elif img_ok:
            source_detail = tr("tilemap.check_source_unsaved")
        else:
            source_detail = tr("tilemap.check_not_loaded")

        size_status = "skip"
        size_detail = tr("tilemap.check_not_loaded")
        if img_ok and self._img is not None:
            tw = int(self._img.width // 8)
            th = int(self._img.height // 8)
            over_hw = tw > 32 or th > 32
            size_status = "warn" if over_hw else "ok"
            size_detail = tr("tilemap.check_size_detail", w=tw, h=th)
            if over_hw:
                size_detail += "  (" + tr("tilemap.check_size_over") + ")"

        color_status = "skip"
        color_detail = tr("tilemap.check_not_loaded")
        if img_ok:
            counts_flat = [c for row in self._counts for c in row]
            warn_tiles = sum(1 for c in counts_flat if c == 4)
            err_tiles = sum(1 for c in counts_flat if c >= 5)
            has_scr2 = bool(self._scr2_path and self._scr2_path.exists())
            plane = "auto"
            if tm is not None:
                plane = str(tm.get("plane", "auto") or "auto")
            plane_label = {
                "scr1": tr("tilemap.check_plane_scr1"),
                "scr2": tr("tilemap.check_plane_scr2"),
            }.get(plane, tr("tilemap.check_plane_auto"))
            if err_tiles == 0 and warn_tiles == 0:
                color_status = "ok"
                color_detail = tr("tilemap.check_colors_single", plane=plane_label)
            elif has_scr2:
                color_status = "ok"
                color_detail = tr("tilemap.check_colors_dual", warn=warn_tiles, err=err_tiles, plane=plane_label)
            elif err_tiles > 0:
                color_status = "bad"
                color_detail = tr("tilemap.check_colors_need_split", warn=warn_tiles, err=err_tiles, plane=plane_label)
            else:
                color_status = "warn"
                color_detail = tr("tilemap.check_colors_borderline", warn=warn_tiles, plane=plane_label)

        collision_status = "skip"
        collision_detail = tr("tilemap.check_collision_skip")
        if img_ok:
            if has_project_link:
                mode = str(tm.get("collision_mode", "tileset") if tm is not None else "tileset").strip().lower()
                if mode == "paint":
                    raw = tm.get("collision_paint") if tm is not None else None
                    tw = int(self._img.width // 8) if self._img is not None else 0
                    th = int(self._img.height // 8) if self._img is not None else 0
                    saved = (
                        isinstance(raw, list)
                        and len(raw) == th
                        and all(isinstance(r, list) and len(r) == tw for r in raw)
                    )
                else:
                    assign = tm.get("collision_tileset") if tm is not None else None
                    saved = isinstance(assign, list) and len(assign) > 0
                collision_status = "ok" if saved else "warn"
                collision_detail = tr("tilemap.check_collision_saved") if saved else tr("tilemap.check_collision_missing")
            elif file_ok:
                collision_status = "ok"
                collision_detail = tr("tilemap.check_collision_header")
            else:
                collision_status = "warn"
                collision_detail = tr("tilemap.check_collision_need_save")

        export_status = "skip"
        export_detail = tr("tilemap.check_not_loaded")
        if img_ok:
            if not file_ok or self._dirty:
                export_status = "warn"
                export_detail = tr("tilemap.check_export_need_save")
            elif script_ok:
                export_status = "ok"
                export_detail = tr("tilemap.check_export_ready")
            else:
                export_status = "warn"
                export_detail = tr("tilemap.check_export_need_script")

        budget_status = "skip"
        budget_detail = tr("tilemap.check_not_loaded")
        if img_ok:
            n_unique = self._count_unique_tiles()
            if n_unique <= 256:
                budget_status = "ok"
                budget_detail = tr("tilemap.check_budget_ok", n=n_unique)
            elif n_unique <= 384:
                budget_status = "warn"
                budget_detail = tr("tilemap.check_budget_warn", n=n_unique)
            else:
                budget_status = "bad"
                budget_detail = tr("tilemap.check_budget_bad", n=n_unique)

        rows = [
            self._check_item_html(source_status, tr("tilemap.check_source"), source_detail),
            self._check_item_html(size_status, tr("tilemap.check_size"), size_detail),
            self._check_item_html(color_status, tr("tilemap.check_colors"), color_detail),
            self._check_item_html(collision_status, tr("tilemap.check_collision"), collision_detail),
            self._check_item_html(budget_status, tr("tilemap.check_budget"), budget_detail),
            self._check_item_html(export_status, tr("tilemap.check_export"), export_detail),
        ]
        self._lbl_checklist.setText("<br>".join(rows))

    def _update_size_limits_ui(self) -> None:
        try:
            if self._img is None:
                return
            tw = int(self._img.width // 8)
            th = int(self._img.height // 8)
            over = bool(tw > 32 or th > 32)
            col = "#e07030" if over else "#888"
            if getattr(self, "_lbl_size_limits", None) is not None:
                self._lbl_size_limits.setStyleSheet(f"color: {col}; font-size: 11px;")
                tip = tr("tilemap.size_limits_tt")
                if over:
                    tip = tip + "\n" + tr("tilemap.size_limits_warn")
                self._lbl_size_limits.setToolTip(tip)
        except Exception:
            pass

    def _count_unique_tiles(self) -> int:
        if self._img is None:
            return 0
        img = self._img.convert("RGBA")
        seen: set[bytes] = set()
        w, h = img.size
        for row in range(h // 8):
            for col in range(w // 8):
                tile = img.crop((col * 8, row * 8, col * 8 + 8, row * 8 + 8))
                seen.add(tile.tobytes())
        return len(seen)

    def _tile_icon(self, tile_bytes: bytes, size: int = 32) -> QIcon:
        try:
            qimg = QImage(tile_bytes, 8, 8, QImage.Format.Format_RGBA8888).copy()
        except Exception:
            qimg = QImage(8, 8, QImage.Format.Format_RGBA8888)
            qimg.fill(QColor(0, 0, 0, 0))
        pm = QPixmap.fromImage(qimg).scaled(
            size, size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        return QIcon(pm)

    def _build_tileset(self, img: Image.Image | None, tileset_name: str) -> None:
        self._tileset_tiles = []
        self._tileset.clear()
        if img is None:
            self._tileset_info.setText(tr("tilemap.tileset_none"))
            self._tileset_info.setStyleSheet("color: gray;")
            self._tileset_src.setText("")
            return

        self._tileset_src.setText(tr("tilemap.tileset_source", name=tileset_name))
        self._tileset_src.setStyleSheet("color: gray;")

        tw = img.width // 8
        th = img.height // 8
        seen: set[bytes] = set()
        for ty in range(th):
            for tx in range(tw):
                tile = img.crop((tx * 8, ty * 8, tx * 8 + 8, ty * 8 + 8)).convert("RGBA")
                b = tile.tobytes()
                if b in seen:
                    continue
                if all(a < 128 for a in b[3::4]):
                    continue
                seen.add(b)
                self._tileset_tiles.append(b)
                item = QListWidgetItem("")
                item.setIcon(self._tile_icon(b))
                item.setData(Qt.ItemDataRole.UserRole, b)
                self._tileset.addItem(item)
                if len(self._tileset_tiles) >= 512:
                    break
            if len(self._tileset_tiles) >= 512:
                break

        self._tileset_info.setText(tr("tilemap.tileset_info", n=len(self._tileset_tiles)))
        self._tileset_info.setStyleSheet("color: gray;")

    def _resolve_project_path(self, rel_or_abs: str) -> Path | None:
        if not rel_or_abs:
            return None
        p = Path(rel_or_abs)
        if p.is_absolute():
            return p
        base = self._scene_base_dir or (self._project_path.parent if self._project_path else None)
        if base is None:
            return None
        return base / p

    def _save_tileset_path_to_project(self, tileset_path: Path | None) -> None:
        if not isinstance(self._active_tm, dict):
            return
        if self._is_free_mode:
            return
        base = self._scene_base_dir or (self._project_path.parent if self._project_path else None)
        if base is None or tileset_path is None:
            self._active_tm.pop("tileset", None)
            self._schedule_project_save()
            return
        try:
            rel = tileset_path.resolve().relative_to(base.resolve())
            self._active_tm["tileset"] = rel.as_posix()
        except Exception:
            self._active_tm["tileset"] = str(tileset_path)
        self._schedule_project_save()

    def _load_tileset_png(self, path: Path, *, save_to_project: bool) -> None:
        try:
            img = quantize_image(Image.open(path).convert("RGBA"))
        except Exception as e:
            QMessageBox.warning(self, tr("tilemap.tileset_load"), tr("tilemap.load_error", err=str(e)))
            return
        self._tileset_img = img
        self._tileset_path = path
        self._build_tileset(img, tileset_name=path.name)
        self._btn_tileset_reset.setEnabled(True)
        if save_to_project:
            self._save_tileset_path_to_project(path)

    def _guess_tileset_path(self, tilemap_path: Path) -> Path | None:
        base = tilemap_path.parent
        stem = tilemap_path.stem
        stems = [stem]
        if stem.lower().endswith("_scr1") or stem.lower().endswith("_scr2"):
            stems.append(stem[:-5])

        candidates: list[Path] = []
        for s in stems:
            candidates.extend([
                base / f"{s}_tileset.png",
                base / f"{s}_tiles.png",
                base / f"{s}_ts.png",
                base / f"{s}_tset.png",
            ])
        candidates.extend([base / "tileset.png", base / "tiles.png"])

        for c in candidates:
            if c.exists() and c.is_file():
                return c

        # Fallback heuristic: first PNG containing "tileset" in same dir.
        try:
            for c in sorted(base.glob("*.png")):
                n = c.name.lower()
                if "tileset" in n and c.is_file():
                    return c
        except Exception:
            pass
        return None

    def _maybe_autoload_tileset(self, tilemap_path: Path) -> None:
        if self._img is None:
            return
        if self._scene_base_dir is None and self._project_path is None:
            return
        if self._tileset_path is not None:
            return

        tm = self._active_tm if isinstance(self._active_tm, dict) else None
        if tm is not None:
            ts = tm.get("tileset")
            if isinstance(ts, str) and ts.strip():
                p = self._resolve_project_path(ts.strip())
                if p is not None and p.exists() and p.is_file():
                    self._load_tileset_png(p, save_to_project=False)
                    return

        guessed = self._guess_tileset_path(tilemap_path)
        if guessed is not None:
            self._load_tileset_png(guessed, save_to_project=False)

    def _pick_tileset_png(self) -> None:
        start = QSettings("NGPCraft", "Engine").value("tilemap/tileset_last_dir", "", str)
        path, _ = QFileDialog.getOpenFileName(
            self, tr("tilemap.tileset_load"), start, tr("tilemap.file_filter"),
        )
        if not path:
            return
        p = Path(path)
        QSettings("NGPCraft", "Engine").setValue("tilemap/tileset_last_dir", str(p.parent))
        self._load_tileset_png(p, save_to_project=True)

    def _reset_tileset_to_map(self) -> None:
        self._tileset_img = None
        self._tileset_path = None
        self._build_tileset(self._img, tileset_name=tr("tilemap.tileset_map"))
        self._btn_tileset_reset.setEnabled(False)
        self._save_tileset_path_to_project(None)

    # ------------------------------------------------------------------
    # Tile editing (paint by tile)
    # ------------------------------------------------------------------

    def _on_edit_toggled(self, on: bool) -> None:
        if self._img is None:
            self._chk_edit.setChecked(False)
            return
        if on:
            self._run_status.setText(tr("tilemap.edit_hint"))
            self._run_status.setStyleSheet("color: gray;")
        else:
            self._run_status.setText("")
        self._refresh_shape_ui()
        self._refresh_stamp_presets_ui()

    def _set_tool(self, tool: str) -> None:
        self._tool = tool
        btn = {
            "paint": getattr(self, "_btn_tool_paint", None),
            "pick": getattr(self, "_btn_tool_pick", None),
            "erase": getattr(self, "_btn_tool_erase", None),
            "fill": getattr(self, "_btn_tool_fill", None),
            "replace": getattr(self, "_btn_tool_replace", None),
            "select": getattr(self, "_btn_tool_select", None),
            "stamp": getattr(self, "_btn_tool_stamp", None),
        }.get(tool)
        if btn is not None:
            try:
                btn.setChecked(True)
            except Exception:
                pass
        if self._chk_edit.isChecked():
            self._run_status.setText(tr("tilemap.edit_hint"))
            self._run_status.setStyleSheet("color: gray;")
        self._refresh_shape_ui()
        self._grid.update()

    def _shape_mode_label(self) -> str:
        return tr({
            "free": "tilemap.shape_free",
            "rect": "tilemap.shape_rect",
            "ellipse": "tilemap.shape_ellipse",
        }.get(str(self._shape_mode or "free"), "tilemap.shape_free"))

    def _refresh_shape_ui(self) -> None:
        picker = getattr(self, "_shape_pick", None)
        hint = getattr(self, "_lbl_shape_hint", None)
        if picker is not None:
            idx = picker.findData(str(self._shape_mode or "free"))
            picker.blockSignals(True)
            picker.setCurrentIndex(idx if idx >= 0 else 0)
            picker.blockSignals(False)
            picker.setEnabled(bool(self._chk_edit.isChecked()))
        if hint is None:
            return
        if self._tool not in ("paint", "erase", "stamp"):
            hint.setText(tr("tilemap.shape_hint_unused"))
            return
        key = {
            "free": "tilemap.shape_hint_free",
            "rect": "tilemap.shape_hint_rect",
            "ellipse": "tilemap.shape_hint_ellipse",
        }.get(str(self._shape_mode or "free"), "tilemap.shape_hint_free")
        hint.setText(tr(key))

    def _on_shape_mode_changed(self, _idx: int) -> None:
        picker = getattr(self, "_shape_pick", None)
        if picker is None:
            return
        self._shape_mode = str(picker.currentData() or "free")
        self._shape_preview_rect = None
        self._shape_drag_start = None
        self._refresh_shape_ui()
        self._grid.update()

    def _on_hover_tile(self, tx: int, ty: int, _count: int) -> None:
        if self._hover_tile != (tx, ty):
            self._hover_tile = (tx, ty)
            self._grid.update()
        if self._chk_edit.isChecked():
            tool = self._tool
            if self._shape_mode != "free" and tool in ("paint", "erase", "stamp"):
                self._run_status.setText(
                    tr("tilemap.edit_shape", tool=tr(f"tilemap.tool_{tool}"), shape=self._shape_mode_label(), x=tx, y=ty)
                )
            elif tool == "erase":
                self._run_status.setText(tr("tilemap.edit_erase", x=tx, y=ty))
            elif tool == "select":
                self._run_status.setText(tr("tilemap.edit_select", x=tx, y=ty))
            elif tool == "stamp":
                self._run_status.setText(tr("tilemap.edit_stamp", x=tx, y=ty))
            elif tool == "fill":
                self._run_status.setText(tr("tilemap.edit_fill", x=tx, y=ty))
            elif tool == "replace":
                self._run_status.setText(tr("tilemap.edit_replace", x=tx, y=ty))
            elif tool == "pick" or self._brush_img is None:
                self._run_status.setText(tr("tilemap.edit_pick", x=tx, y=ty))
            else:
                self._run_status.setText(tr("tilemap.edit_paint", x=tx, y=ty))
            self._run_status.setStyleSheet("color: gray;")

    def _clear_hover_tile(self) -> None:
        if self._hover_tile is None:
            return
        self._hover_tile = None
        self._grid.update()

    def _refresh_stamp_actions_ui(self) -> None:
        enabled = bool(self._clipboard_img is not None or self._selected_tiles_rect() is not None)
        for btn_name in ("_btn_stamp_flip_h", "_btn_stamp_flip_v", "_btn_stamp_rot_r"):
            btn = getattr(self, btn_name, None)
            if btn is not None:
                btn.setEnabled(enabled)
        save_btn = getattr(self, "_btn_stamp_preset_save", None)
        if save_btn is not None:
            save_btn.setEnabled(enabled and self._chk_edit.isChecked())
        self._refresh_stamp_presets_ui()

    def _load_stamp_presets(self) -> list[dict[str, str]]:
        raw = QSettings("NGPCraft", "Engine").value("tilemap/stamp_presets", "[]", str)
        try:
            data = json.loads(str(raw or "[]"))
        except Exception:
            return []
        presets: list[dict[str, str]] = []
        if not isinstance(data, list):
            return presets
        for entry in data:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            png_b64 = str(entry.get("png") or "").strip()
            if not name or not png_b64:
                continue
            presets.append({"name": name, "png": png_b64})
        return presets

    def _save_stamp_presets(self) -> None:
        QSettings("NGPCraft", "Engine").setValue("tilemap/stamp_presets", json.dumps(self._stamp_presets))

    def _refresh_stamp_presets_ui(self) -> None:
        picker = getattr(self, "_stamp_preset_pick", None)
        if picker is None:
            return
        current_name = str(picker.currentData() or "")
        picker.blockSignals(True)
        picker.clear()
        picker.addItem(tr("tilemap.stamp_preset_none"), "")
        for entry in self._stamp_presets:
            picker.addItem(str(entry.get("name") or ""), str(entry.get("name") or ""))
        idx = picker.findData(current_name)
        if idx < 0:
            idx = 0
        picker.setCurrentIndex(idx)
        picker.blockSignals(False)
        has_presets = bool(self._stamp_presets)
        apply_btn = getattr(self, "_btn_stamp_preset_apply", None)
        if apply_btn is not None:
            apply_btn.setEnabled(has_presets and picker.currentIndex() > 0)
        delete_btn = getattr(self, "_btn_stamp_preset_delete", None)
        if delete_btn is not None:
            delete_btn.setEnabled(has_presets and picker.currentIndex() > 0)

    def _stamp_preset_to_clipboard(self, png_b64: str) -> Image.Image | None:
        try:
            data = base64.b64decode(png_b64.encode("ascii"))
            with BytesIO(data) as bio:
                img = Image.open(bio)
                return img.convert("RGBA")
        except Exception:
            return None

    def _stamp_preset_save(self) -> None:
        clip = self._ensure_stamp_clipboard()
        if clip is None:
            self._run_status.setText(tr("tilemap.need_stamp"))
            self._run_status.setStyleSheet("color: #e07030;")
            return
        suggested = tr("tilemap.stamp_preset_default", n=len(self._stamp_presets) + 1)
        name, ok = QInputDialog.getText(self, tr("tilemap.stamp_preset_save"), tr("tilemap.stamp_preset_name"), text=suggested)
        if not ok:
            return
        name = str(name or "").strip()
        if not name:
            return
        png_b64 = ""
        with BytesIO() as bio:
            clip.save(bio, format="PNG")
            png_b64 = base64.b64encode(bio.getvalue()).decode("ascii")
        replaced = False
        for entry in self._stamp_presets:
            if str(entry.get("name") or "") == name:
                entry["png"] = png_b64
                replaced = True
                break
        if not replaced:
            self._stamp_presets.append({"name": name, "png": png_b64})
        self._save_stamp_presets()
        self._refresh_stamp_presets_ui()
        picker = getattr(self, "_stamp_preset_pick", None)
        if picker is not None:
            idx = picker.findData(name)
            if idx >= 0:
                picker.setCurrentIndex(idx)
        self._run_status.setText(tr("tilemap.stamp_preset_saved", name=name))
        self._run_status.setStyleSheet("color: gray;")

    def _stamp_preset_apply(self) -> None:
        picker = getattr(self, "_stamp_preset_pick", None)
        if picker is None or picker.currentIndex() <= 0:
            return
        name = str(picker.currentData() or "")
        entry = next((e for e in self._stamp_presets if str(e.get("name") or "") == name), None)
        if entry is None:
            return
        clip = self._stamp_preset_to_clipboard(str(entry.get("png") or ""))
        if clip is None:
            self._run_status.setText(tr("tilemap.stamp_preset_invalid", name=name))
            self._run_status.setStyleSheet("color: #e07030;")
            return
        self._brush_variants = []
        self._clipboard_img = clip
        self._set_tool("stamp")
        self._update_stamp_label()
        self._refresh_stamp_presets_ui()
        self._grid.update()
        self._run_status.setText(tr("tilemap.stamp_preset_loaded", name=name))
        self._run_status.setStyleSheet("color: gray;")

    def _stamp_preset_delete(self) -> None:
        picker = getattr(self, "_stamp_preset_pick", None)
        if picker is None or picker.currentIndex() <= 0:
            return
        name = str(picker.currentData() or "")
        if not name:
            return
        if QMessageBox.question(
            self,
            tr("tilemap.stamp_preset_delete"),
            tr("tilemap.stamp_preset_delete_confirm", name=name),
        ) != QMessageBox.StandardButton.Yes:
            return
        self._stamp_presets = [e for e in self._stamp_presets if str(e.get("name") or "") != name]
        self._save_stamp_presets()
        self._refresh_stamp_presets_ui()
        self._run_status.setText(tr("tilemap.stamp_preset_deleted", name=name))
        self._run_status.setStyleSheet("color: gray;")

    def _ensure_stamp_clipboard(self) -> Image.Image | None:
        if self._clipboard_img is not None:
            return self._clipboard_img
        r = self._selected_tiles_rect()
        if r is None or self._img is None:
            return None
        x, y, w, h = r
        box = (x * 8, y * 8, (x + w) * 8, (y + h) * 8)
        self._brush_variants = []
        self._clipboard_img = self._img.crop(box).convert("RGBA")
        self._refresh_stamp_actions_ui()
        self._grid.update()
        return self._clipboard_img

    def _update_stamp_label(self) -> None:
        if self._brush_variants:
            self._brush_lbl.setText(tr("tilemap.brush_variation_dims", n=len(self._brush_variants)))
            self._brush_lbl.setStyleSheet("")
            self._refresh_stamp_actions_ui()
            return
        clip = self._clipboard_img
        if clip is None:
            self._refresh_stamp_actions_ui()
            return
        cw = max(1, int(clip.width // 8))
        ch = max(1, int(clip.height // 8))
        if cw == 1 and ch == 1:
            self._brush_lbl.setText(tr("tilemap.brush_stamp_single"))
        else:
            self._brush_lbl.setText(tr("tilemap.brush_stamp_dims", w=cw, h=ch))
        self._brush_lbl.setStyleSheet("")
        self._refresh_stamp_actions_ui()

    def _transform_stamp(self, op: str) -> None:
        if not self._chk_edit.isChecked() or self._grid_tabs.currentIndex() != 0:
            return
        clip = self._ensure_stamp_clipboard()
        if clip is None:
            self._run_status.setText(tr("tilemap.need_stamp"))
            self._run_status.setStyleSheet("color: #e07030;")
            return
        if op == "flip_h":
            self._clipboard_img = clip.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            self._run_status.setText(tr("tilemap.stamp_flip_h_done"))
        elif op == "flip_v":
            self._clipboard_img = clip.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            self._run_status.setText(tr("tilemap.stamp_flip_v_done"))
        elif op == "rot_r":
            self._clipboard_img = clip.transpose(Image.Transpose.ROTATE_270)
            self._run_status.setText(tr("tilemap.stamp_rot_r_done"))
        else:
            return
        self._run_status.setStyleSheet("color: gray;")
        self._set_tool("stamp")
        self._update_stamp_label()
        self._grid.update()

    def _stamp_flip_h(self) -> None:
        self._transform_stamp("flip_h")

    def _stamp_flip_v(self) -> None:
        self._transform_stamp("flip_v")

    def _stamp_rot_r(self) -> None:
        self._transform_stamp("rot_r")

    def _line_points(self, start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
        x0, y0 = int(start[0]), int(start[1])
        x1, y1 = int(end[0]), int(end[1])
        points: list[tuple[int, int]] = []
        dx = abs(x1 - x0)
        sx = 1 if x0 < x1 else -1
        dy = -abs(y1 - y0)
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            points.append((x0, y0))
            if x0 == x1 and y0 == y1:
                break
            e2 = err * 2
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy
        return points

    def _current_brush_tile(self) -> Image.Image | None:
        if self._brush_variants:
            return random.choice(self._brush_variants).copy()
        if self._brush_img is None:
            return None
        return self._brush_img

    def _shape_rect(self, start: tuple[int, int], end: tuple[int, int]) -> tuple[int, int, int, int]:
        x0 = min(int(start[0]), int(end[0]))
        y0 = min(int(start[1]), int(end[1]))
        x1 = max(int(start[0]), int(end[0]))
        y1 = max(int(start[1]), int(end[1]))
        return x0, y0, int(x1 - x0 + 1), int(y1 - y0 + 1)

    def _shape_points(self, start: tuple[int, int], end: tuple[int, int], shape_mode: str) -> list[tuple[int, int]]:
        x0, y0, w, h = self._shape_rect(start, end)
        if shape_mode == "ellipse":
            pts: list[tuple[int, int]] = []
            rx = max(0.5, w / 2.0)
            ry = max(0.5, h / 2.0)
            cx = x0 + (w / 2.0)
            cy = y0 + (h / 2.0)
            for ty in range(y0, y0 + h):
                for tx in range(x0, x0 + w):
                    nx = ((tx + 0.5) - cx) / rx
                    ny = ((ty + 0.5) - cy) / ry
                    if (nx * nx) + (ny * ny) <= 1.0:
                        pts.append((tx, ty))
            return pts
        return [(tx, ty) for ty in range(y0, y0 + h) for tx in range(x0, x0 + w)]

    def _apply_collision_line(self, start: tuple[int, int], end: tuple[int, int], val: int) -> None:
        tw, th = self._col_dims()
        points = self._line_points(start, end)
        changed: list[tuple[int, int]] = []
        pushed = False
        for tx, ty in points:
            if not (0 <= tx < tw and 0 <= ty < th):
                continue
            cur = int(self._col_paint_grid[ty][tx])
            if cur == int(val):
                continue
            if not pushed:
                self._push_col_undo()
                pushed = True
            self._col_paint_grid[ty][tx] = int(val)
            changed.append((tx, ty))
        if not changed:
            return
        self._col_redo.clear()
        if isinstance(self._active_tm, dict):
            self._active_tm["collision_mode"] = "paint"
            self._active_tm["collision_types"] = list(self._col_types or self._default_collision_types())
            self._active_tm["collision_paint"] = [list(row) for row in self._col_paint_grid]
            self._schedule_project_save()
        self._refresh_collision_from_project()

    def _apply_map_line(self, start: tuple[int, int], end: tuple[int, int], mode: str) -> None:
        if self._img is None:
            return
        points = self._line_points(start, end)
        changed: list[tuple[int, int]] = []
        pushed = False
        for tx, ty in points:
            if mode == "stamp":
                if self._clipboard_img is None:
                    continue
                if not pushed:
                    self._undo.push(self._img)
                    pushed = True
                changed.extend(self._stamp_at_no_undo(tx, ty, self._clipboard_img))
                continue
            if mode == "erase":
                tile_img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
            else:
                tile_img = self._current_brush_tile()
                if tile_img is None:
                    continue
            if not pushed:
                self._undo.push(self._img)
                pushed = True
            self._paint_tile_no_undo(tx, ty, tile_img)
            changed.append((tx, ty))
        if changed:
            self._after_tiles_changed(changed)

    def _apply_map_shape(self, start: tuple[int, int], end: tuple[int, int], mode: str, shape_mode: str) -> None:
        if self._img is None:
            return
        points = self._shape_points(start, end, shape_mode)
        changed: list[tuple[int, int]] = []
        pushed = False
        for tx, ty in points:
            if mode == "stamp":
                if self._clipboard_img is None:
                    continue
                if not pushed:
                    self._undo.push(self._img)
                    pushed = True
                changed.extend(self._stamp_at_no_undo(tx, ty, self._clipboard_img))
                continue
            if mode == "erase":
                tile_img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
            else:
                tile_img = self._current_brush_tile()
                if tile_img is None:
                    continue
            if not pushed:
                self._undo.push(self._img)
                pushed = True
            self._paint_tile_no_undo(tx, ty, tile_img)
            changed.append((tx, ty))
        if changed:
            self._after_tiles_changed(changed)

    def _begin_drag(self, button, mods) -> bool:
        if self._grid_tabs.currentIndex() == 1:
            if self._col_mode != "paint":
                return False
            if mods & (Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier):
                return False
            if button == Qt.MouseButton.LeftButton:
                self._drag_action = "col_paint"
            elif button == Qt.MouseButton.RightButton:
                self._drag_action = "col_erase"
            else:
                return False
            self._drag_changed = []
            self._drag_seen = set()
            self._drag_pushed = False
            return True
        if not self._chk_edit.isChecked() or self._img is None:
            return False
        if mods & (Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier):
            return False

        if button == Qt.MouseButton.LeftButton:
            if self._tool == "select":
                self._drag_action = "select"
                self._sel_drag_start = None
            elif self._tool == "stamp":
                if self._clipboard_img is None:
                    return False
                self._drag_action = "shape_stamp" if self._shape_mode != "free" else "stamp"
            elif self._tool == "erase":
                self._drag_action = "shape_erase" if self._shape_mode != "free" else "erase"
            else:
                if self._brush_img is None:
                    return False
                self._drag_action = "shape_paint" if self._shape_mode != "free" else "paint"
        elif button == Qt.MouseButton.RightButton:
            self._drag_action = "shape_erase" if self._shape_mode != "free" else "erase"
        else:
            return False

        self._drag_changed = []
        self._drag_seen = set()
        self._drag_pushed = False
        self._shape_drag_start = None
        self._shape_preview_rect = None
        return True

    def _apply_drag(self, tx: int, ty: int) -> None:
        if self._grid_tabs.currentIndex() == 1:
            if not self._drag_action or self._col_mode != "paint":
                return
            tw, th = self._col_dims()
            if not (0 <= tx < tw and 0 <= ty < th):
                return
            key = ty * tw + tx
            if key in self._drag_seen:
                return
            self._drag_seen.add(key)
            val = self._col_brush_value if self._drag_action == "col_paint" else 0
            cur = int(self._col_paint_grid[ty][tx]) if ty < len(self._col_paint_grid) and tx < len(self._col_paint_grid[ty]) else 0
            if cur == int(val):
                return
            if not self._drag_pushed:
                self._push_col_undo()
                self._drag_pushed = True
            self._col_paint_grid[ty][tx] = int(val)
            self._drag_changed.append((tx, ty))
            self._grid_col.set_collision_overlay(self._col_paint_grid, self._collision_colors(self._col_types), self._collision_labels(self._col_types))
            return
        if self._img is None or not self._drag_action:
            return
        if not self._is_valid_map_tile(tx, ty):
            return
        if self._drag_action.startswith("shape_"):
            if self._shape_drag_start is None:
                self._shape_drag_start = (tx, ty)
            self._shape_preview_rect = self._shape_rect(self._shape_drag_start, (tx, ty))
            self._grid.update()
            return
        if self._drag_action == "select":
            if self._sel_drag_start is None:
                self._sel_drag_start = (tx, ty)
            sx, sy = self._sel_drag_start
            x0 = min(sx, tx)
            y0 = min(sy, ty)
            x1 = max(sx, tx)
            y1 = max(sy, ty)
            self._sel_rect = QRect(int(x0), int(y0), int(x1 - x0 + 1), int(y1 - y0 + 1))
            self._grid.update()
            self._refresh_stamp_actions_ui()
            return
        tw, _th = self._map_dims()
        key = ty * tw + tx
        if key in self._drag_seen:
            return
        self._drag_seen.add(key)

        if not self._drag_pushed:
            self._undo.push(self._img)
            self._drag_pushed = True

        if self._drag_action == "paint":
            if self._brush_img is None:
                return
            self._paint_tile_no_undo(tx, ty, self._brush_img)
        elif self._drag_action == "stamp":
            if self._clipboard_img is None:
                return
            changed = self._stamp_at_no_undo(tx, ty, self._clipboard_img)
            self._drag_changed.extend(changed)
            self._grid.set_data(self._img, self._counts, self._zoom)
            return
        elif self._drag_action == "erase":
            self._paint_tile_no_undo(tx, ty, Image.new("RGBA", (8, 8), (0, 0, 0, 0)))
        else:
            return

        self._drag_changed.append((tx, ty))
        self._grid.set_data(self._img, self._counts, self._zoom)

    def _end_drag(self) -> None:
        changed = self._drag_changed
        action = self._drag_action
        self._drag_action = None
        self._drag_changed = []
        self._drag_seen = set()
        pushed = self._drag_pushed
        self._drag_pushed = False
        shape_start = self._shape_drag_start
        shape_preview = self._shape_preview_rect
        self._shape_drag_start = None
        self._shape_preview_rect = None
        if action in ("col_paint", "col_erase"):
            if pushed and changed and isinstance(self._active_tm, dict):
                self._active_tm["collision_mode"] = "paint"
                self._active_tm["collision_types"] = list(self._col_types or self._default_collision_types())
                self._active_tm["collision_paint"] = [list(row) for row in self._col_paint_grid]
                self._schedule_project_save()
            if pushed and changed:
                self._col_redo.clear()
                self._refresh_collision_from_project()
            return
        if action in ("shape_paint", "shape_erase", "shape_stamp"):
            if shape_start is not None and shape_preview is not None:
                sx, sy, sw, sh = shape_preview
                end = (sx + sw - 1, sy + sh - 1)
                mode = action.split("_", 1)[1]
                self._apply_map_shape(shape_start, end, mode, str(self._shape_mode or "rect"))
            self._grid.update()
            return
        if action == "select":
            self._sel_drag_start = None
            self._grid.update()
            return
        if not pushed or not changed:
            return
        self._after_tiles_changed(changed)

    def _on_tile_click(self, tx: int, ty: int, button, mods) -> None:
        if self._grid_tabs.currentIndex() == 1:
            if self._col_mode != "paint":
                if button in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
                    self._select_collision_tile_from_map(tx, ty)
                return
            if mods & Qt.KeyboardModifier.AltModifier:
                self._line_anchor_col = None
                return
            if mods & Qt.KeyboardModifier.ShiftModifier:
                val = self._col_brush_value if button == Qt.MouseButton.LeftButton else 0
                start = self._line_anchor_col or (tx, ty)
                self._apply_collision_line(start, (tx, ty), int(val))
                self._line_anchor_col = (tx, ty)
                return
            if mods & (Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier):
                return
            tw, th = self._col_dims()
            if not (0 <= tx < tw and 0 <= ty < th):
                return
            val = self._col_brush_value if button == Qt.MouseButton.LeftButton else 0
            cur = int(self._col_paint_grid[ty][tx]) if ty < len(self._col_paint_grid) and tx < len(self._col_paint_grid[ty]) else 0
            if cur == int(val):
                return
            self._push_col_undo()
            self._col_paint_grid[ty][tx] = int(val)
            self._col_redo.clear()
            if isinstance(self._active_tm, dict):
                self._active_tm["collision_mode"] = "paint"
                self._active_tm["collision_types"] = list(self._col_types or self._default_collision_types())
                self._active_tm["collision_paint"] = [list(row) for row in self._col_paint_grid]
                self._schedule_project_save()
            self._refresh_collision_from_project()
            self._line_anchor_col = (tx, ty)
            return
        if not self._chk_edit.isChecked() or self._img is None:
            return
        if not self._is_valid_map_tile(tx, ty):
            return
        if mods & Qt.KeyboardModifier.AltModifier:
            self._set_brush_from_map(tx, ty)
            self._line_anchor_tile = None
            return

        if button == Qt.MouseButton.RightButton:
            if mods & Qt.KeyboardModifier.ShiftModifier:
                start = self._line_anchor_tile or (tx, ty)
                self._apply_map_line(start, (tx, ty), "erase")
                self._line_anchor_tile = (tx, ty)
                return
            self._erase_tile(tx, ty)
            self._line_anchor_tile = (tx, ty)
            return

        if button != Qt.MouseButton.LeftButton:
            return

        if self._tool == "select":
            self._sel_rect = QRect(int(tx), int(ty), 1, 1)
            self._grid.update()
            self._refresh_stamp_actions_ui()
            return

        target = self._tile_bytes_at(tx, ty)
        if target is None:
            return

        tool = self._tool
        if mods & Qt.KeyboardModifier.ShiftModifier and tool in ("paint", "erase", "stamp"):
            if tool == "stamp":
                if self._clipboard_img is None:
                    self._run_status.setText(tr("tilemap.need_stamp"))
                    self._run_status.setStyleSheet("color: #e07030;")
                    return
                mode = "stamp"
            elif tool == "erase":
                mode = "erase"
            else:
                if self._brush_img is None:
                    self._run_status.setText(tr("tilemap.need_brush"))
                    self._run_status.setStyleSheet("color: #e07030;")
                    return
                mode = "paint"
            start = self._line_anchor_tile or (tx, ty)
            self._apply_map_line(start, (tx, ty), mode)
            self._line_anchor_tile = (tx, ty)
            return
        if mods & Qt.KeyboardModifier.ShiftModifier:
            if self._current_brush_tile() is None:
                self._run_status.setText(tr("tilemap.need_brush"))
                self._run_status.setStyleSheet("color: #e07030;")
                return
            self._flood_fill_tiles(tx, ty, target)
            self._line_anchor_tile = None
            return
        if mods & Qt.KeyboardModifier.ControlModifier:
            if self._current_brush_tile() is None:
                self._run_status.setText(tr("tilemap.need_brush"))
                self._run_status.setStyleSheet("color: #e07030;")
                return
            self._replace_all_tiles(target)
            self._line_anchor_tile = None
            return

        if tool == "pick":
            self._set_brush_from_map(tx, ty)
            self._line_anchor_tile = None
            return
        if tool == "erase":
            self._erase_tile(tx, ty)
            self._line_anchor_tile = (tx, ty)
            return
        if tool == "stamp":
            if self._clipboard_img is None:
                self._run_status.setText(tr("tilemap.need_stamp"))
                self._run_status.setStyleSheet("color: #e07030;")
                return
            self._undo.push(self._img)
            changed = self._stamp_at_no_undo(tx, ty, self._clipboard_img)
            if changed:
                self._after_tiles_changed(changed)
            self._line_anchor_tile = (tx, ty)
            return
        if tool == "fill":
            if self._current_brush_tile() is None:
                self._run_status.setText(tr("tilemap.need_brush"))
                self._run_status.setStyleSheet("color: #e07030;")
                return
            self._flood_fill_tiles(tx, ty, target)
            self._line_anchor_tile = None
            return
        if tool == "replace":
            if self._brush_img is None:
                self._run_status.setText(tr("tilemap.need_brush"))
                self._run_status.setStyleSheet("color: #e07030;")
                return
            self._replace_all_tiles(target)
            self._line_anchor_tile = None
            return

        # Paint (default)
        tile_img = self._current_brush_tile()
        if tile_img is None:
            self._set_brush_from_map(tx, ty)
            self._line_anchor_tile = None
            return
        self._paint_tile(tx, ty, tile_img)
        self._line_anchor_tile = (tx, ty)

    def _clear_selection(self) -> None:
        if self._sel_rect is None:
            return
        self._sel_rect = None
        self._sel_drag_start = None
        self._grid.update()
        self._refresh_stamp_actions_ui()

    def _selected_tiles_rect(self) -> tuple[int, int, int, int] | None:
        if self._img is None or self._sel_rect is None:
            return None
        x = int(self._sel_rect.x())
        y = int(self._sel_rect.y())
        w = int(self._sel_rect.width())
        h = int(self._sel_rect.height())
        if w <= 0 or h <= 0:
            return None
        tw, th = self._map_dims()
        if x < 0 or y < 0 or x >= tw or y >= th:
            return None
        w = min(w, tw - x)
        h = min(h, th - y)
        return x, y, w, h

    def _copy_selection(self) -> None:
        if not self._chk_edit.isChecked() or self._grid_tabs.currentIndex() != 0:
            return
        r = self._selected_tiles_rect()
        if r is None or self._img is None:
            return
        x, y, w, h = r
        box = (x * 8, y * 8, (x + w) * 8, (y + h) * 8)
        self._brush_variants = []
        self._clipboard_img = self._img.crop(box).convert("RGBA")
        self._grid.update()
        self._update_stamp_label()

    def _cut_selection(self) -> None:
        if not self._chk_edit.isChecked() or self._grid_tabs.currentIndex() != 0:
            return
        r = self._selected_tiles_rect()
        if r is None or self._img is None:
            return
        self._copy_selection()
        x, y, w, h = r
        self._undo.push(self._img)
        blank = Image.new("RGBA", (w * 8, h * 8), (0, 0, 0, 0))
        self._img.paste(blank, (x * 8, y * 8))
        self._counts_dirty = True
        changed = [(tx, ty) for ty in range(y, y + h) for tx in range(x, x + w)]
        self._after_tiles_changed(changed)

    def _delete_selection_tiles(self) -> None:
        if not self._chk_edit.isChecked() or self._grid_tabs.currentIndex() != 0:
            return
        r = self._selected_tiles_rect()
        if r is None or self._img is None:
            return
        x, y, w, h = r
        self._undo.push(self._img)
        blank = Image.new("RGBA", (w * 8, h * 8), (0, 0, 0, 0))
        self._img.paste(blank, (x * 8, y * 8))
        self._counts_dirty = True
        changed = [(tx, ty) for ty in range(y, y + h) for tx in range(x, x + w)]
        self._after_tiles_changed(changed)

    def _paste_selection(self) -> None:
        if not self._chk_edit.isChecked() or self._grid_tabs.currentIndex() != 0:
            return
        if self._img is None or self._clipboard_img is None:
            return

        if self._hover_tile is not None:
            tx, ty = self._hover_tile
        elif self._sel_rect is not None:
            tx = int(self._sel_rect.x())
            ty = int(self._sel_rect.y())
        else:
            tx, ty = 0, 0

        tw, th = self._map_dims()
        if not (0 <= tx < tw and 0 <= ty < th):
            return

        clip = self._clipboard_img.convert("RGBA")
        cw = clip.width // 8
        ch = clip.height // 8
        w = min(cw, tw - tx)
        h = min(ch, th - ty)
        if w <= 0 or h <= 0:
            return

        self._undo.push(self._img)
        region = clip.crop((0, 0, w * 8, h * 8)).convert("RGBA")
        self._img.paste(region, (tx * 8, ty * 8), region)
        self._counts_dirty = True
        # Move selection to pasted region so the user sees where it landed
        self._sel_rect = QRect(tx, ty, w, h)
        changed = [(x, y) for y in range(ty, ty + h) for x in range(tx, tx + w)]
        self._after_tiles_changed(changed)

    def _load_shortcut_bindings(self) -> dict[str, str]:
        raw = QSettings("NGPCraft", "Engine").value("tilemap/shortcut_bindings", "{}", str)
        try:
            data = json.loads(str(raw or "{}"))
        except Exception:
            data = {}
        bindings = {name: default for name, _label, default in _SHORTCUT_DEFAULTS}
        if isinstance(data, dict):
            for name in bindings:
                val = str(data.get(name) or "").strip()
                if val:
                    bindings[name] = val
        return bindings

    def _save_shortcut_bindings(self) -> None:
        QSettings("NGPCraft", "Engine").setValue("tilemap/shortcut_bindings", json.dumps(self._shortcut_bindings))

    def _shortcut_summary_text(self) -> str:
        keys: list[str] = []
        for name in ("paint", "pick", "erase", "fill", "replace", "select", "stamp"):
            seq = str(self._shortcut_bindings.get(name) or "")
            if seq:
                keys.append(seq)
        return tr("tilemap.shortcuts_summary", keys=" / ".join(keys))

    def _refresh_shortcuts_ui(self) -> None:
        lbl = getattr(self, "_lbl_shortcuts", None)
        if lbl is not None:
            lbl.setText(self._shortcut_summary_text())

    def _rebuild_edit_shortcuts(self) -> None:
        for sc in self._edit_shortcuts:
            sc.setParent(None)
            sc.deleteLater()
        self._edit_shortcuts = []
        for name, _label, _default in _SHORTCUT_DEFAULTS:
            seq = str(self._shortcut_bindings.get(name) or "").strip()
            if not seq:
                continue
            sc = QShortcut(QKeySequence(seq), self)
            if name in ("paint", "pick", "erase", "fill", "replace", "select", "stamp"):
                sc.activated.connect(lambda tool=name: self._shortcut_set_tool(tool))
            elif name == "stamp_flip_h":
                sc.activated.connect(self._stamp_flip_h)
            elif name == "stamp_flip_v":
                sc.activated.connect(self._stamp_flip_v)
            elif name == "stamp_rot_r":
                sc.activated.connect(self._stamp_rot_r)
            self._edit_shortcuts.append(sc)
        self._refresh_shortcuts_ui()

    def _open_shortcuts_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("tilemap.shortcuts_title"))
        layout = QVBoxLayout(dlg)
        form = QFormLayout()
        edits: dict[str, QKeySequenceEdit] = {}
        for name, label_key, _default in _SHORTCUT_DEFAULTS:
            edit = QKeySequenceEdit(QKeySequence(str(self._shortcut_bindings.get(name) or "")), dlg)
            edit.setClearButtonEnabled(True)
            edits[name] = edit
            form.addRow(tr(label_key), edit)
        layout.addLayout(form)
        hint = QLabel(tr("tilemap.shortcuts_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=dlg)
        reset_btn = btns.addButton(tr("tilemap.shortcuts_reset"), QDialogButtonBox.ButtonRole.ResetRole)
        reset_btn.clicked.connect(
            lambda: [
                edits[name].setKeySequence(QKeySequence(default))
                for name, _label, default in _SHORTCUT_DEFAULTS
            ]
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        bindings: dict[str, str] = {}
        for name, _label, default in _SHORTCUT_DEFAULTS:
            text = edits[name].keySequence().toString(QKeySequence.SequenceFormat.PortableText).strip()
            bindings[name] = text or default
        self._shortcut_bindings = bindings
        self._save_shortcut_bindings()
        self._rebuild_edit_shortcuts()
        self._run_status.setText(tr("tilemap.shortcuts_saved"))
        self._run_status.setStyleSheet("color: gray;")

    def _shortcut_set_tool(self, tool: str) -> None:
        if not self._chk_edit.isChecked() or self._grid_tabs.currentIndex() != 0:
            return
        self._set_tool(tool)

    def _map_dims(self) -> tuple[int, int]:
        if self._img is None:
            return 0, 0
        return int(self._img.width // 8), int(self._img.height // 8)

    def _is_valid_map_tile(self, tx: int, ty: int) -> bool:
        tw, th = self._map_dims()
        return 0 <= int(tx) < tw and 0 <= int(ty) < th

    def _tile_box(self, tx: int, ty: int) -> tuple[int, int, int, int]:
        x0 = tx * 8
        y0 = ty * 8
        return (x0, y0, x0 + 8, y0 + 8)

    def _tile_img_at(self, tx: int, ty: int) -> Image.Image | None:
        if self._img is None or not self._is_valid_map_tile(tx, ty):
            return None
        x0, y0, x1, y1 = self._tile_box(tx, ty)
        return self._img.crop((x0, y0, x1, y1)).convert("RGBA")

    def _tile_bytes_at(self, tx: int, ty: int) -> bytes | None:
        t = self._tile_img_at(tx, ty)
        return t.tobytes() if t is not None else None

    def _count_colors_in_tile(self, tile_img: Image.Image) -> int:
        seen: set[tuple[int, int, int]] = set()
        for r, g, b, a in tile_img.getdata():
            if a >= 128:
                seen.add((r, g, b))
        return len(seen)

    def _set_brush(self, tile_img: Image.Image, label: str) -> None:
        self._brush_variants = []
        self._brush_img = tile_img.convert("RGBA")
        self._brush_bytes = self._brush_img.tobytes()
        self._brush_lbl.setText(label)
        self._brush_lbl.setStyleSheet("")

    def _set_brush_variants(self, tiles: list[Image.Image], label: str) -> None:
        self._brush_variants = [tile.convert("RGBA") for tile in tiles if tile is not None]
        if not self._brush_variants:
            return
        self._brush_img = self._brush_variants[0]
        self._brush_bytes = self._brush_img.tobytes()
        self._brush_lbl.setText(label)
        self._brush_lbl.setStyleSheet("")

    def _set_brush_from_map(self, tx: int, ty: int) -> None:
        tile = self._tile_img_at(tx, ty)
        if tile is None:
            return
        self._set_brush(tile, tr("tilemap.brush", x=tx, y=ty))

    def _set_brush_transparent(self) -> None:
        self._set_brush(Image.new("RGBA", (8, 8), (0, 0, 0, 0)), tr("tilemap.brush_erase"))

    def _on_tileset_selection_changed(self) -> None:
        items = list(self._tileset.selectedItems()) if hasattr(self, "_tileset") else []
        if not items:
            return

        tiles: list[bytes] = []
        for item in items:
            try:
                data = item.data(Qt.ItemDataRole.UserRole)
            except Exception:
                data = None
            if isinstance(data, (bytes, bytearray)):
                tiles.append(bytes(data))

        if not tiles:
            return

        if len(tiles) == 1:
            try:
                img = Image.frombytes("RGBA", (8, 8), tiles[0])
            except Exception:
                return
            self._set_brush(img, tr("tilemap.brush_tileset"))
            self._run_status.setText(tr("tilemap.tileset_brush_ready"))
            self._run_status.setStyleSheet("color: gray;")
            return

        if self._chk_brush_variation.isChecked():
            variants: list[Image.Image] = []
            for data in tiles:
                try:
                    variants.append(Image.frombytes("RGBA", (8, 8), data))
                except Exception:
                    continue
            if not variants:
                return
            self._set_brush_variants(variants, tr("tilemap.brush_variation_dims", n=len(variants)))
            self._set_tool("paint")
            self._update_stamp_label()
            self._run_status.setText(tr("tilemap.tileset_variation_ready", n=len(variants)))
            self._run_status.setStyleSheet("color: gray;")
            return

        self._brush_variants = []
        clip = Image.new("RGBA", (len(tiles) * 8, 8), (0, 0, 0, 0))
        for i, data in enumerate(tiles):
            try:
                tile = Image.frombytes("RGBA", (8, 8), data)
            except Exception:
                continue
            clip.paste(tile, (i * 8, 0))
        self._clipboard_img = clip
        self._set_tool("stamp")
        self._update_stamp_label()
        self._run_status.setText(tr("tilemap.tileset_stamp_ready", n=len(tiles)))
        self._run_status.setStyleSheet("color: gray;")

    def _erase_tile(self, tx: int, ty: int) -> None:
        self._paint_tile(tx, ty, Image.new("RGBA", (8, 8), (0, 0, 0, 0)))

    def _paint_tile(self, tx: int, ty: int, tile_img: Image.Image) -> None:
        if self._img is None or not self._is_valid_map_tile(tx, ty):
            return
        self._undo.push(self._img)
        self._paint_tile_no_undo(tx, ty, tile_img)
        self._after_tiles_changed([(tx, ty)])

    def _paint_tile_no_undo(self, tx: int, ty: int, tile_img: Image.Image) -> None:
        if self._img is None or not self._is_valid_map_tile(tx, ty):
            return
        x0, y0, _x1, _y1 = self._tile_box(tx, ty)
        tile_img = tile_img.convert("RGBA").crop((0, 0, 8, 8))
        self._img.paste(tile_img, (x0, y0))
        if self._counts and 0 <= ty < len(self._counts) and 0 <= tx < len(self._counts[ty]):
            self._counts[ty][tx] = self._count_colors_in_tile(tile_img)

    def _stamp_at_no_undo(self, tx: int, ty: int, clip_img: Image.Image) -> list[tuple[int, int]]:
        if self._img is None:
            return []
        tw, th = self._map_dims()
        if tx < 0 or ty < 0 or tx >= tw or ty >= th:
            return []

        clip = clip_img.convert("RGBA")
        cw = int(clip.width // 8)
        ch = int(clip.height // 8)
        if cw <= 0 or ch <= 0:
            return []

        w = min(cw, tw - tx)
        h = min(ch, th - ty)
        if w <= 0 or h <= 0:
            return []

        region = clip.crop((0, 0, w * 8, h * 8)).convert("RGBA")
        self._img.paste(region, (tx * 8, ty * 8), region)

        changed: list[tuple[int, int]] = []
        if not self._counts:
            self._counts = colors_per_tile(self._img)
            self._counts_dirty = False
        for dy in range(h):
            for dx in range(w):
                rx = tx + dx
                ry = ty + dy
                tile = region.crop((dx * 8, dy * 8, dx * 8 + 8, dy * 8 + 8)).convert("RGBA")
                if 0 <= ry < len(self._counts) and 0 <= rx < len(self._counts[ry]):
                    self._counts[ry][rx] = self._count_colors_in_tile(tile)
                changed.append((rx, ry))
        return changed

    def _after_tiles_changed(self, tiles: list[tuple[int, int]]) -> None:
        if self._img is None:
            return
        self._dirty = True
        if not self._counts:
            self._counts = colors_per_tile(self._img)
            self._counts_dirty = False
        elif self._counts_dirty:
            seen: set[int] = set()
            tw = self._img.width // 8
            for tx, ty in tiles:
                k = int(ty) * tw + int(tx)
                if k in seen:
                    continue
                seen.add(k)
                if 0 <= ty < len(self._counts) and 0 <= tx < len(self._counts[ty]):
                    tile = self._tile_img_at(int(tx), int(ty))
                    if tile is not None:
                        self._counts[int(ty)][int(tx)] = self._count_colors_in_tile(tile)
            self._counts_dirty = False
        self._grid.set_data(self._img, self._counts, self._zoom)
        self._grid_col.set_data(self._img, self._counts, self._zoom)
        if self._tileset_img is None:
            self._build_tileset(self._img, tileset_name=tr("tilemap.tileset_map"))
        self._col_basis_dirty = True
        self._update_stats()
        self._refresh_undo_ui()

    def _replace_all_tiles(self, target_bytes: bytes) -> None:
        if self._img is None:
            return
        if not self._brush_variants and (self._brush_img is None or self._brush_bytes is None):
            return
        if not self._brush_variants and target_bytes == self._brush_bytes:
            return
        tw = self._img.width // 8
        th = self._img.height // 8
        changed: list[tuple[int, int]] = []

        self._undo.push(self._img)
        for ty in range(th):
            for tx in range(tw):
                b = self._tile_bytes_at(tx, ty)
                if b is not None and b == target_bytes:
                    tile_img = self._current_brush_tile()
                    if tile_img is None:
                        continue
                    self._paint_tile_no_undo(tx, ty, tile_img)
                    changed.append((tx, ty))

        if changed:
            self._after_tiles_changed(changed)

    def _flood_fill_tiles(self, start_tx: int, start_ty: int, target_bytes: bytes) -> None:
        if self._img is None:
            return
        if not self._brush_variants and (self._brush_img is None or self._brush_bytes is None):
            return
        if not self._brush_variants and target_bytes == self._brush_bytes:
            return

        tw = self._img.width // 8
        th = self._img.height // 8
        q: deque[tuple[int, int]] = deque()
        q.append((start_tx, start_ty))
        seen: set[int] = set()
        changed: list[tuple[int, int]] = []

        def _k(x: int, y: int) -> int:
            return y * tw + x

        self._undo.push(self._img)
        while q:
            tx, ty = q.popleft()
            if not (0 <= tx < tw and 0 <= ty < th):
                continue
            k = _k(tx, ty)
            if k in seen:
                continue
            seen.add(k)
            b = self._tile_bytes_at(tx, ty)
            if b is None or b != target_bytes:
                continue
            tile_img = self._current_brush_tile()
            if tile_img is None:
                continue
            self._paint_tile_no_undo(tx, ty, tile_img)
            changed.append((tx, ty))
            q.append((tx - 1, ty))
            q.append((tx + 1, ty))
            q.append((tx, ty - 1))
            q.append((tx, ty + 1))

        if changed:
            self._after_tiles_changed(changed)

    def _refresh_undo_ui(self) -> None:
        if self._grid_tabs.currentIndex() == 1 and self._col_mode == "paint":
            self._btn_undo.setEnabled(bool(self._col_undo))
            self._btn_redo.setEnabled(bool(self._col_redo))
            return
        self._btn_undo.setEnabled(self._undo.can_undo() and self._img is not None)
        self._btn_redo.setEnabled(self._undo.can_redo() and self._img is not None)

    def _on_undo(self) -> None:
        if self._grid_tabs.currentIndex() == 1 and self._col_mode == "paint":
            if not self._col_undo:
                return
            self._col_redo.append(self._collision_grid_snapshot())
            self._restore_collision_snapshot(self._col_undo.pop())
            if isinstance(self._active_tm, dict):
                self._active_tm["collision_mode"] = "paint"
                self._active_tm["collision_types"] = list(self._col_types or self._default_collision_types())
                self._active_tm["collision_paint"] = [list(row) for row in self._col_paint_grid]
                self._schedule_project_save()
            self._refresh_collision_from_project()
            return
        if self._img is None:
            return
        out = self._undo.undo(self._img)
        if out is None:
            return
        self._img = out
        self._dirty = True
        self._sel_rect = None
        self._sel_drag_start = None
        self._counts = colors_per_tile(self._img)
        self._counts_dirty = False
        self._grid.set_data(self._img, self._counts, self._zoom)
        self._grid_col.set_data(self._img, self._counts, self._zoom)
        if self._tileset_img is None:
            self._build_tileset(self._img, tileset_name=tr("tilemap.tileset_map"))
        self._col_basis_dirty = True
        self._refresh_collision_from_project()
        self._update_stats()
        self._refresh_undo_ui()

    def _on_redo(self) -> None:
        if self._grid_tabs.currentIndex() == 1 and self._col_mode == "paint":
            if not self._col_redo:
                return
            self._col_undo.append(self._collision_grid_snapshot())
            self._restore_collision_snapshot(self._col_redo.pop())
            if isinstance(self._active_tm, dict):
                self._active_tm["collision_mode"] = "paint"
                self._active_tm["collision_types"] = list(self._col_types or self._default_collision_types())
                self._active_tm["collision_paint"] = [list(row) for row in self._col_paint_grid]
                self._schedule_project_save()
            self._refresh_collision_from_project()
            return
        if self._img is None:
            return
        out = self._undo.redo(self._img)
        if out is None:
            return
        self._img = out
        self._dirty = True
        self._counts = colors_per_tile(self._img)
        self._counts_dirty = False
        self._grid.set_data(self._img, self._counts, self._zoom)
        self._grid_col.set_data(self._img, self._counts, self._zoom)
        if self._tileset_img is None:
            self._build_tileset(self._img, tileset_name=tr("tilemap.tileset_map"))
        self._col_basis_dirty = True
        self._refresh_collision_from_project()
        self._update_stats()
        self._refresh_undo_ui()

    def _save_overwrite(self) -> None:
        if self._img is None:
            return
        if self._current_path is None:
            self._save_as()
            return
        try:
            self._img.save(str(self._current_path))
            self._dirty = False
            self._run_status.setText(tr("tilemap.saved", path=str(self._current_path)))
            self._run_status.setStyleSheet("color: #4ec94e;")
            self._install_watcher()
            self._refresh_checklist()
        except Exception as e:
            QMessageBox.warning(self, tr("tilemap.save"), tr("tilemap.save_error", err=str(e)))

    def _save_as(self) -> None:
        if self._img is None:
            return
        default = str(self._current_path) if self._current_path else ""
        path, _ = QFileDialog.getSaveFileName(self, tr("tilemap.save_as"), default, "PNG (*.png)")
        if not path:
            return
        try:
            self._img.save(path)
            self._current_path = Path(path)
            self._dirty = False
            self._file_lbl.setText(self._current_path.name)
            self._file_lbl.setStyleSheet("")
            QSettings("NGPCraft", "Engine").setValue("tilemap/last_dir", str(self._current_path.parent))
            self._btn_split.setEnabled(True)
            self._btn_scr2_pick.setEnabled(True)
            self._btn_scr2_clear.setEnabled(True)
            self._btn_run.setEnabled(True)
            self._install_watcher()
            self._col_basis_dirty = True
            if self._active_tm is None and self._current_path is not None:
                self._active_tm = self._match_active_tilemap(self._current_path)
            self._refresh_collision_from_project()
            self._run_status.setText(tr("tilemap.saved", path=path))
            self._run_status.setStyleSheet("color: #4ec94e;")
            self._refresh_checklist()
        except Exception as e:
            QMessageBox.warning(self, tr("tilemap.save_as"), tr("tilemap.save_error", err=str(e)))

    def _split_to_layers(self) -> tuple[Image.Image, Image.Image, int]:
        if self._img is None:
            raise ValueError("No image")
        img = self._img.convert("RGBA")
        w, h = img.size
        scr1 = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        scr2 = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        px = img.load()
        p1 = scr1.load()
        p2 = scr2.load()
        split_n = 0
        for ty in range(h // 8):
            for tx in range(w // 8):
                counts: dict[tuple[int, int, int], int] = {}
                for y in range(8):
                    for x in range(8):
                        r, g, b, a = px[tx * 8 + x, ty * 8 + y]
                        if a < 128:
                            continue
                        key = (r, g, b)
                        counts[key] = counts.get(key, 0) + 1
                colors = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
                if len(colors) <= 3:
                    for y in range(8):
                        for x in range(8):
                            p1[tx * 8 + x, ty * 8 + y] = px[tx * 8 + x, ty * 8 + y]
                    continue
                split_n += 1
                top = {c for c, _n in colors[:3]}
                for y in range(8):
                    for x in range(8):
                        r, g, b, a = px[tx * 8 + x, ty * 8 + y]
                        if a < 128:
                            continue
                        if (r, g, b) in top:
                            p1[tx * 8 + x, ty * 8 + y] = (r, g, b, a)
                        else:
                            p2[tx * 8 + x, ty * 8 + y] = (r, g, b, a)
        return scr1, scr2, split_n

    def _export_scr_pngs(self) -> None:
        if self._img is None or self._current_path is None:
            return
        try:
            scr1, scr2, n = self._split_to_layers()
        except Exception as e:
            QMessageBox.warning(self, tr("tilemap.split_png"), tr("tilemap.split_fail", err=str(e)))
            return
        out1 = self._current_path.with_name(self._current_path.stem + "_scr1.png")
        out2 = self._current_path.with_name(self._current_path.stem + "_scr2.png")
        try:
            scr1.save(str(out1))
            scr2.save(str(out2))
            self._scr2_path = out2
            self._refresh_scr2_ui()
            self._col_basis_dirty = True
            if self._grid_tabs.currentIndex() == 1:
                self._refresh_collision_from_project()
            self._run_status.setText(tr("tilemap.split_ok", a=out1.name, b=out2.name, n=n))
            self._run_status.setStyleSheet("color: #4ec94e;")
            self._refresh_checklist()
        except Exception as e:
            QMessageBox.warning(self, tr("tilemap.split_png"), tr("tilemap.split_fail", err=str(e)))

    def _pick_scr2(self) -> None:
        if self._current_path is None:
            return
        start = str(self._current_path.parent)
        p, _ = QFileDialog.getOpenFileName(self, tr("tilemap.scr2_pick"), start, tr("tilemap.file_filter"))
        if not p:
            return
        self._scr2_path = Path(p)
        self._refresh_scr2_ui()
        self._col_basis_dirty = True
        if self._grid_tabs.currentIndex() == 1:
            self._refresh_collision_from_project()

    def _clear_scr2(self) -> None:
        self._scr2_path = None
        self._refresh_scr2_ui()
        self._col_basis_dirty = True
        if self._grid_tabs.currentIndex() == 1:
            self._refresh_collision_from_project()

    def _refresh_scr2_ui(self) -> None:
        if self._scr2_path and self._scr2_path.exists():
            self._scr2_lbl.setText(self._scr2_path.name)
            self._scr2_lbl.setStyleSheet("")
        else:
            self._scr2_lbl.setText(tr("tilemap.scr2_none"))
            self._scr2_lbl.setStyleSheet("color: gray; font-style: italic;")
        self._refresh_checklist()

    # ------------------------------------------------------------------
    # Drag & drop
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        """Accept dropped image files so a tilemap can be opened from outside the tab."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        """Open the first dropped image file as the active tilemap."""
        for url in event.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.suffix.lower() in (".png", ".bmp", ".gif"):
                self._load(p)
                break

    # ------------------------------------------------------------------
    # Run ngpc_tilemap.py
    # ------------------------------------------------------------------

    def _find_script(self) -> Path | None:
        repo_root = Path(__file__).resolve().parents[2]
        return find_script(
            "tilemap_script_path",
            default_candidates(repo_root, "ngpc_tilemap.py"),
        )

    def _run_tilemap(self) -> None:
        if self._current_path is None:
            return
        script = self._find_script()
        if script is None:
            start = script_dialog_start_dir("tilemap_script_path", fallback=self._scene_base_dir)
            p, _ = QFileDialog.getOpenFileName(
                self, tr("tilemap.find_script"), start, "Python (*.py)"
            )
            if not p:
                return
            script = Path(p)
            remember_script_path("tilemap_script_path", script)

        try:
            scr1 = self._current_path
            scr2 = self._scr2_path if (self._scr2_path and self._scr2_path.exists()) else None

            # If user opened *_scr2.png directly, try to auto-pair with *_scr1.png
            stem_l = scr1.stem.lower()
            if scr2 is None and stem_l.endswith("_scr2"):
                base = scr1.stem[:-5]
                cand1 = scr1.with_name(base + "_scr1" + scr1.suffix)
                if cand1.exists():
                    scr2 = scr1
                    scr1 = cand1

            out_base = scr1.stem
            if out_base.lower().endswith("_scr1") or out_base.lower().endswith("_scr2"):
                out_base = out_base[:-5]
            out_c = scr1.with_name(out_base + "_map.c")

            do_compress = getattr(self, "_chk_compress", None) is not None and self._chk_compress.isChecked()
            compress_algo = self._combo_compress.currentData() if do_compress else None
            bin_path = scr1.with_name(out_base + "_tiles.bin") if do_compress else None

            cmd = [_sys.executable, str(script), str(scr1), "-o", str(out_c)]
            if out_base:
                cmd += ["-n", out_base]
            if scr2 is not None and scr2.exists():
                cmd += ["--scr2", str(scr2)]
            if self._chk_header.isChecked():
                cmd += ["--header"]
            if do_compress and bin_path is not None:
                cmd += ["--tiles-bin", str(bin_path)]
            res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(scr1.parent), timeout=60)
            if res.returncode == 0:
                mode = ""
                for line in (res.stdout or "").splitlines():
                    if line.startswith("Mode:"):
                        mode = line.split(":", 1)[1].strip()
                        break
                msg = tr("tilemap.run_ok", path=out_c.name)
                if mode:
                    msg += "  (" + mode + ")"

                # CT-6: run compression step if requested
                if do_compress and bin_path is not None and bin_path.exists():
                    compress_script = script.parent / "ngpc_compress.py"
                    if not compress_script.exists():
                        msg += "  " + tr("tilemap.compress_no_script")
                    else:
                        out_lz = scr1.with_name(out_base + ("_rle" if compress_algo == "rle" else "_lz") + ".c")
                        cmp_cmd = [
                            _sys.executable, str(compress_script),
                            str(bin_path), "-o", str(out_lz),
                            "-m", str(compress_algo), "--header",
                        ]
                        cres = subprocess.run(cmp_cmd, capture_output=True, text=True, cwd=str(scr1.parent), timeout=30)
                        if cres.returncode == 0:
                            ratio_line = ""
                            for ln in (cres.stdout or "").splitlines():
                                if "%" in ln and ("Compressed" in ln or "LZ77" in ln or "RLE" in ln or "Winner" in ln):
                                    ratio_line = ln.strip()
                                    break
                            msg += "  " + tr("tilemap.compress_ok", file=out_lz.name)
                            if ratio_line:
                                msg += "  (" + ratio_line + ")"
                        else:
                            err_c = (cres.stderr or "").strip().splitlines()[:1]
                            msg += "  " + tr("tilemap.compress_fail") + (": " + err_c[0] if err_c else "")

                self._run_status.setText(msg)
                self._run_status.setStyleSheet("color: #4ec94e;")
            else:
                err = (res.stderr or "").strip().splitlines()[:1]
                extra = (": " + err[0]) if err else ""
                self._run_status.setText(tr("tilemap.run_fail", code=res.returncode) + extra)
                self._run_status.setStyleSheet("color: #e07030;")
            self._refresh_checklist()
        except Exception as e:
            self._run_status.setText(str(e))
            self._run_status.setStyleSheet("color: #e07030;")
            self._refresh_checklist()
