"""
ui/tabs/editor_tab.py - Minimal sprite/tile retouch editor (Phase 6 MVP).

Scope (MVP):
- Open PNG, edit pixels with Pencil/Eraser/Picker/Fill
- Palette locked to RGB444 (opaque pixels snapped)
- 8×8 grid + per-tile color-count overlay (<=3 ok)
- Undo/Redo
- Save (overwrite) / Save as
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from PyQt6.QtCore import Qt, QSettings, QSize, QTimer, QFileSystemWatcher
from PyQt6.QtGui import QColor, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QColorDialog,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.rgb444 import colors_per_tile, palette_from_image, quantize_image, snap
from i18n.lang import tr


def _pil_to_qpixmap(img: Image.Image) -> QPixmap:
    rgba = img.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimg = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


def _pil_to_qimage(img: Image.Image) -> QImage:
    rgba = img.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimg = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
    return qimg.copy()


def _qimage_to_pil(img: QImage) -> Image.Image | None:
    if img.isNull():
        return None
    try:
        qimg = img.convertToFormat(QImage.Format.Format_RGBA8888)
    except Exception:
        qimg = img
    w, h = qimg.width(), qimg.height()
    if w <= 0 or h <= 0:
        return None
    ptr = qimg.bits()
    ptr.setsize(w * h * 4)
    data = bytes(ptr)
    return Image.frombytes("RGBA", (w, h), data)


def _make_zoom_pixmap(img: Image.Image, zoom: int) -> QPixmap:
    w, h = img.size
    scaled = img.resize((w * zoom, h * zoom), Image.NEAREST)
    return _pil_to_qpixmap(scaled)


def _rgb_to_word(rgb: tuple[int, int, int]) -> int:
    r, g, b = rgb
    return (r >> 4) | ((g >> 4) << 4) | ((b >> 4) << 8)


def _rgb_icon(rgb: tuple[int, int, int], size: int = 14) -> QIcon:
    r, g, b = rgb
    pm = QPixmap(size, size)
    pm.fill(QColor(r, g, b))
    return QIcon(pm)


@dataclass
class _UndoState:
    """Serialized image snapshot stored by the editor undo stack."""

    w: int
    h: int
    rgba: bytes


class _UndoStack:
    """Bounded undo/redo history for the pixel editor."""

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


class _EditorCanvas(QWidget):
    """Canvas widget responsible for rendering and pointer interaction in EditorTab."""

    def __init__(self, parent: "EditorTab") -> None:
        super().__init__(parent)
        self._tab = parent
        self.setMouseTracking(True)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(25, 25, 32))

        img = self._tab._img  # noqa: SLF001
        if img is None:
            p.end()
            return

        zoom = self._tab._zoom  # noqa: SLF001
        pm = self._tab._pixmap  # noqa: SLF001
        if pm is not None and not pm.isNull():
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            p.drawPixmap(0, 0, pm)

        if self._tab._tile_overlay:  # noqa: SLF001
            counts = self._tab._tile_counts  # noqa: SLF001
            if counts:
                for row, row_counts in enumerate(counts):
                    for col, cnt in enumerate(row_counts):
                        x = col * 8 * zoom
                        y = row * 8 * zoom
                        size = 8 * zoom
                        if cnt <= 3:
                            c = QColor(0, 200, 80, 40)
                        elif cnt == 4:
                            c = QColor(255, 160, 0, 80)
                        else:
                            c = QColor(255, 30, 30, 110)
                        p.fillRect(x, y, size, size, c)

        if self._tab._grid:  # noqa: SLF001
            p.setPen(QColor(0, 0, 0, 80))
            w, h = img.size
            for x in range(0, w + 1, 8):
                p.drawLine(x * zoom, 0, x * zoom, h * zoom)
            for y in range(0, h + 1, 8):
                p.drawLine(0, y * zoom, w * zoom, y * zoom)

        hp = self._tab._hover_px  # noqa: SLF001
        if hp is not None:
            hx, hy = hp
            x = hx * zoom
            y = hy * zoom
            p.setPen(QColor(0, 0, 0, 210))
            p.drawRect(x, y, zoom - 1, zoom - 1)
            p.setPen(QColor(255, 255, 255, 230))
            p.drawRect(x + 1, y + 1, max(0, zoom - 3), max(0, zoom - 3))

        # Selection (final + live dragging)
        sel = self._tab._sel_rect  # noqa: SLF001
        if sel is None:
            sel = self._tab._sel_temp  # noqa: SLF001
        if sel is not None:
            sx, sy, sw, sh = sel
            pen = QPen(QColor(255, 255, 255, 220))
            if self._tab._sel_temp is not None:  # noqa: SLF001
                pen = QPen(QColor(255, 220, 80, 230))
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawRect(sx * zoom, sy * zoom, max(1, sw * zoom) - 1, max(1, sh * zoom) - 1)

        p.end()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self._tab._tool == "select":  # noqa: SLF001
            self._tab._begin_select(event.pos().x(), event.pos().y())  # noqa: SLF001
            event.accept()
            return

        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            erase = event.button() == Qt.MouseButton.RightButton
            self._tab._begin_stroke(event.pos().x(), event.pos().y(), erase=erase)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if event.buttons() & Qt.MouseButton.LeftButton and self._tab._tool == "select":  # noqa: SLF001
            self._tab._continue_select(event.pos().x(), event.pos().y())  # noqa: SLF001
            event.accept()
            return

        if event.buttons() & (Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton):
            erase = bool(event.buttons() & Qt.MouseButton.RightButton)
            self._tab._continue_stroke(event.pos().x(), event.pos().y(), erase=erase)
            event.accept()
            return
        self._tab._hover(event.pos().x(), event.pos().y())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self._tab._tool == "select":  # noqa: SLF001
            self._tab._end_select(event.pos().x(), event.pos().y())  # noqa: SLF001
            event.accept()
            return

        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self._tab._end_stroke()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            dy = event.angleDelta().y()
            if dy > 0:
                self._tab._step_zoom(1)
            elif dy < 0:
                self._tab._step_zoom(-1)
            event.accept()
            return
        super().wheelEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._tab._clear_hover()
        super().leaveEvent(event)


class EditorTab(QWidget):
    """Pixel-level sprite/tile editor with quantized NGPC-aware tooling."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path: Path | None = None
        self._img: Image.Image | None = None
        self._pixmap: QPixmap | None = None
        self._zoom = 8
        self._grid = True
        self._tile_overlay = True
        self._tile_counts: list[list[int]] = []
        self._dirty = False

        self._tool = "pencil"  # pencil/eraser/picker/fill
        self._color: tuple[int, int, int] = (255, 255, 255)
        self._brush_size = 1
        self._sym_h = False
        self._sym_v = False
        self._hover_px: tuple[int, int] | None = None
        self._sel_anchor: tuple[int, int] | None = None
        self._sel_rect: tuple[int, int, int, int] | None = None  # x,y,w,h in px coords
        self._sel_temp: tuple[int, int, int, int] | None = None
        self._replace_mode = False
        self._last_px: tuple[int, int] | None = None
        self._stroke_active = False
        self._stroke_erase = False
        self._clip_img: Image.Image | None = None

        self._ext_palette: list[tuple[int, int, int]] = []
        self._ext_palette_path: Path | None = None

        self._scene: dict | None = None
        self._scene_base: Path | None = None
        self._rail_btns: list[tuple[QToolButton, Path]] = []  # (button, abs_path)

        self._undo = _UndoStack(limit=60)
        self._stats_timer = QTimer(self)
        self._stats_timer.setSingleShot(True)
        self._stats_timer.timeout.connect(self._recompute_stats)

        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.timeout.connect(self._reload_from_disk)

        self._build_ui()
        self.setAcceptDrops(True)

        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self._on_undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, activated=self._on_redo)
        QShortcut(QKeySequence.StandardKey.Save, self, activated=self._save_overwrite)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, activated=self._save_as)
        QShortcut(QKeySequence.StandardKey.ZoomIn, self, activated=lambda: self._step_zoom(1))
        QShortcut(QKeySequence.StandardKey.ZoomOut, self, activated=lambda: self._step_zoom(-1))
        QShortcut(QKeySequence("P"), self, activated=lambda: self._set_tool("pencil"))
        QShortcut(QKeySequence("E"), self, activated=lambda: self._set_tool("eraser"))
        QShortcut(QKeySequence("I"), self, activated=lambda: self._set_tool("picker"))
        QShortcut(QKeySequence("F"), self, activated=lambda: self._set_tool("fill"))
        QShortcut(QKeySequence("S"), self, activated=lambda: self._set_tool("select"))
        QShortcut(QKeySequence("G"), self, activated=lambda: self._chk_grid.toggle())
        QShortcut(QKeySequence("O"), self, activated=lambda: self._chk_overlay.toggle())
        QShortcut(QKeySequence("H"), self, activated=lambda: self._chk_sym_h.toggle())
        QShortcut(QKeySequence("V"), self, activated=lambda: self._chk_sym_v.toggle())
        QShortcut(QKeySequence("R"), self, activated=self._start_replace_mode)
        QShortcut(QKeySequence.StandardKey.SelectAll, self, activated=self._select_all)
        QShortcut(QKeySequence.StandardKey.Copy, self, activated=self._copy_selection)
        QShortcut(QKeySequence.StandardKey.Cut, self, activated=self._cut_selection)
        QShortcut(QKeySequence.StandardKey.Paste, self, activated=self._paste)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self, activated=self._clear_selection_pixels)
        QShortcut(QKeySequence(Qt.Key.Key_Backspace), self, activated=self._clear_selection_pixels)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._cancel_modes)
        QShortcut(QKeySequence.StandardKey.Open, self, activated=self._open_file)
        QShortcut(QKeySequence("Ctrl+["), self, activated=self._flip_h)
        QShortcut(QKeySequence("Ctrl+]"), self, activated=self._flip_v)
        QShortcut(QKeySequence("Ctrl+Shift+["), self, activated=self._rot_l)
        QShortcut(QKeySequence("Ctrl+Shift+]"), self, activated=self._rot_r)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(6)

        # File row
        file_row = QHBoxLayout()
        file_row.addWidget(QLabel(tr("ed.file")))
        self._file_lbl = QLabel(tr("ed.no_file"))
        self._file_lbl.setStyleSheet("color: gray; font-style: italic;")
        self._file_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        file_row.addWidget(self._file_lbl, 1)
        self._auto_reload = QCheckBox(tr("ed.auto_reload"))
        self._auto_reload.setChecked(True)
        self._auto_reload.setToolTip(tr("ed.tt.auto_reload"))
        file_row.addWidget(self._auto_reload)
        btn_open = QPushButton(tr("ed.open"))
        btn_open.setToolTip(tr("ed.tt.open"))
        btn_open.clicked.connect(self._open_file)
        file_row.addWidget(btn_open)
        self._btn_save = QPushButton(tr("ed.save"))
        self._btn_save.setToolTip(tr("ed.tt.save"))
        self._btn_save.clicked.connect(self._save_overwrite)
        self._btn_save.setEnabled(False)
        file_row.addWidget(self._btn_save)
        btn_save_as = QPushButton(tr("ed.save_as"))
        btn_save_as.setToolTip(tr("ed.tt.save_as"))
        btn_save_as.clicked.connect(self._save_as)
        btn_save_as.setEnabled(False)
        self._btn_save_as = btn_save_as
        file_row.addWidget(btn_save_as)
        root.addLayout(file_row)

        # Tools + zoom
        tool_row = QHBoxLayout()
        tool_row.addWidget(QLabel(tr("ed.tool")))
        self._btn_pencil = QToolButton()
        self._btn_pencil.setText(tr("ed.pencil"))
        self._btn_pencil.setCheckable(True)
        self._btn_pencil.setChecked(True)
        self._btn_pencil.setToolTip(tr("ed.tt.pencil"))
        self._btn_pencil.clicked.connect(lambda: self._set_tool("pencil"))
        tool_row.addWidget(self._btn_pencil)
        self._btn_eraser = QToolButton()
        self._btn_eraser.setText(tr("ed.eraser"))
        self._btn_eraser.setCheckable(True)
        self._btn_eraser.setToolTip(tr("ed.tt.eraser"))
        self._btn_eraser.clicked.connect(lambda: self._set_tool("eraser"))
        tool_row.addWidget(self._btn_eraser)
        self._btn_picker = QToolButton()
        self._btn_picker.setText(tr("ed.picker"))
        self._btn_picker.setCheckable(True)
        self._btn_picker.setToolTip(tr("ed.tt.picker"))
        self._btn_picker.clicked.connect(lambda: self._set_tool("picker"))
        tool_row.addWidget(self._btn_picker)
        self._btn_fill = QToolButton()
        self._btn_fill.setText(tr("ed.fill"))
        self._btn_fill.setCheckable(True)
        self._btn_fill.setToolTip(tr("ed.tt.fill"))
        self._btn_fill.clicked.connect(lambda: self._set_tool("fill"))
        tool_row.addWidget(self._btn_fill)
        self._btn_select = QToolButton()
        self._btn_select.setText(tr("ed.select"))
        self._btn_select.setCheckable(True)
        self._btn_select.setToolTip(tr("ed.tt.select"))
        self._btn_select.clicked.connect(lambda: self._set_tool("select"))
        tool_row.addWidget(self._btn_select)

        tool_row.addSpacing(12)
        tool_row.addWidget(QLabel(tr("ed.color")))
        self._btn_color = QPushButton("")
        self._btn_color.setFixedWidth(44)
        self._btn_color.setToolTip(tr("ed.tt.color"))
        self._btn_color.clicked.connect(self._pick_color)
        tool_row.addWidget(self._btn_color)
        self._refresh_color_button()

        tool_row.addSpacing(16)
        tool_row.addWidget(QLabel(tr("ed.zoom")))
        for z in (1, 2, 4, 8, 16, 32):
            b = QToolButton()
            b.setText(f"×{z}")
            b.setCheckable(True)
            b.setChecked(z == self._zoom)
            b.setToolTip(tr("ed.tt.zoom_btn", z=z))
            b.clicked.connect(lambda _chk, zv=z: self._set_zoom(zv))
            setattr(self, f"_zoom_{z}", b)
            tool_row.addWidget(b)
        self._chk_grid = QCheckBox(tr("ed.grid"))
        self._chk_grid.setChecked(True)
        self._chk_grid.setToolTip(tr("ed.tt.grid"))
        self._chk_grid.toggled.connect(lambda v: self._set_grid(bool(v)))
        tool_row.addWidget(self._chk_grid)
        self._chk_overlay = QCheckBox(tr("ed.tile_overlay"))
        self._chk_overlay.setChecked(True)
        self._chk_overlay.setToolTip(tr("ed.tt.overlay"))
        self._chk_overlay.toggled.connect(lambda v: self._set_tile_overlay(bool(v)))
        tool_row.addWidget(self._chk_overlay)

        tool_row.addSpacing(12)
        tool_row.addWidget(QLabel(tr("ed.brush")))
        self._cmb_brush = QComboBox()
        for s in (1, 2, 3):
            self._cmb_brush.addItem(str(s), s)
        self._cmb_brush.setCurrentIndex(0)
        self._cmb_brush.setToolTip(tr("ed.tt.brush"))
        self._cmb_brush.currentIndexChanged.connect(self._on_brush_changed)
        tool_row.addWidget(self._cmb_brush)

        tool_row.addSpacing(12)
        self._chk_sym_h = QCheckBox(tr("ed.sym_h"))
        self._chk_sym_h.setChecked(False)
        self._chk_sym_h.setToolTip(tr("ed.tt.sym_h"))
        self._chk_sym_h.toggled.connect(lambda v: self._set_symmetry(bool(v), self._sym_v))
        tool_row.addWidget(self._chk_sym_h)
        self._chk_sym_v = QCheckBox(tr("ed.sym_v"))
        self._chk_sym_v.setChecked(False)
        self._chk_sym_v.setToolTip(tr("ed.tt.sym_v"))
        self._chk_sym_v.toggled.connect(lambda v: self._set_symmetry(self._sym_h, bool(v)))
        tool_row.addWidget(self._chk_sym_v)
        tool_row.addStretch()

        self._btn_undo = QPushButton(tr("ed.undo"))
        self._btn_undo.clicked.connect(self._on_undo)
        self._btn_undo.setEnabled(False)
        self._btn_undo.setToolTip(tr("ed.tt.undo"))
        tool_row.addWidget(self._btn_undo)
        self._btn_redo = QPushButton(tr("ed.redo"))
        self._btn_redo.clicked.connect(self._on_redo)
        self._btn_redo.setEnabled(False)
        self._btn_redo.setToolTip(tr("ed.tt.redo"))
        tool_row.addWidget(self._btn_redo)
        root.addLayout(tool_row)

        ops_row = QHBoxLayout()
        ops_row.addWidget(QLabel(tr("ed.ops")))
        self._btn_flip_h = QPushButton(tr("ed.flip_h"))
        self._btn_flip_h.clicked.connect(self._flip_h)
        self._btn_flip_h.setEnabled(False)
        self._btn_flip_h.setToolTip(tr("ed.tt.flip_h"))
        ops_row.addWidget(self._btn_flip_h)
        self._btn_flip_v = QPushButton(tr("ed.flip_v"))
        self._btn_flip_v.clicked.connect(self._flip_v)
        self._btn_flip_v.setEnabled(False)
        self._btn_flip_v.setToolTip(tr("ed.tt.flip_v"))
        ops_row.addWidget(self._btn_flip_v)
        self._btn_rot_l = QPushButton(tr("ed.rot_l"))
        self._btn_rot_l.clicked.connect(self._rot_l)
        self._btn_rot_l.setEnabled(False)
        self._btn_rot_l.setToolTip(tr("ed.tt.rot_l"))
        ops_row.addWidget(self._btn_rot_l)
        self._btn_rot_r = QPushButton(tr("ed.rot_r"))
        self._btn_rot_r.clicked.connect(self._rot_r)
        self._btn_rot_r.setEnabled(False)
        self._btn_rot_r.setToolTip(tr("ed.tt.rot_r"))
        ops_row.addWidget(self._btn_rot_r)
        self._btn_replace = QPushButton(tr("ed.replace"))
        self._btn_replace.clicked.connect(self._start_replace_mode)
        self._btn_replace.setEnabled(False)
        self._btn_replace.setToolTip(tr("ed.tt.replace"))
        ops_row.addWidget(self._btn_replace)
        ops_row.addStretch()
        root.addLayout(ops_row)

        sel_row = QHBoxLayout()
        sel_row.addWidget(QLabel(tr("ed.sel_ops")))
        self._btn_sel_all = QPushButton(tr("ed.sel_all"))
        self._btn_sel_all.setToolTip(tr("ed.tt.sel_all"))
        self._btn_sel_all.clicked.connect(self._select_all)
        self._btn_sel_all.setEnabled(False)
        sel_row.addWidget(self._btn_sel_all)
        self._btn_copy = QPushButton(tr("ed.copy"))
        self._btn_copy.setToolTip(tr("ed.tt.copy"))
        self._btn_copy.clicked.connect(self._copy_selection)
        self._btn_copy.setEnabled(False)
        sel_row.addWidget(self._btn_copy)
        self._btn_cut = QPushButton(tr("ed.cut"))
        self._btn_cut.setToolTip(tr("ed.tt.cut"))
        self._btn_cut.clicked.connect(self._cut_selection)
        self._btn_cut.setEnabled(False)
        sel_row.addWidget(self._btn_cut)
        self._btn_paste = QPushButton(tr("ed.paste"))
        self._btn_paste.setToolTip(tr("ed.tt.paste"))
        self._btn_paste.clicked.connect(self._paste)
        self._btn_paste.setEnabled(False)
        sel_row.addWidget(self._btn_paste)
        self._btn_clear_sel = QPushButton(tr("ed.sel_clear"))
        self._btn_clear_sel.setToolTip(tr("ed.tt.sel_clear"))
        self._btn_clear_sel.clicked.connect(self._clear_selection_pixels)
        self._btn_clear_sel.setEnabled(False)
        sel_row.addWidget(self._btn_clear_sel)
        sel_row.addStretch()
        root.addLayout(sel_row)

        # Split view: canvas + palette
        mid = QHBoxLayout()
        mid.setSpacing(8)

        # Scene thumbnail rail (hidden until a scene is active)
        self._rail_scroll = QScrollArea()
        self._rail_scroll.setFixedWidth(92)
        self._rail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rail_scroll.setWidgetResizable(True)
        self._rail_scroll.setVisible(False)
        _rail_widget = QWidget()
        self._rail_layout = QVBoxLayout(_rail_widget)
        self._rail_layout.setContentsMargins(4, 4, 4, 4)
        self._rail_layout.setSpacing(6)
        self._rail_scroll.setWidget(_rail_widget)
        mid.addWidget(self._rail_scroll)

        canvas_g = QGroupBox(tr("ed.canvas"))
        cl = QVBoxLayout(canvas_g)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._canvas = _EditorCanvas(self)
        self._canvas.setMinimumSize(240, 160)
        self._scroll.setWidget(self._canvas)
        cl.addWidget(self._scroll, 1)
        self._status = QLabel("")
        cl.addWidget(self._status)
        self._cursor = QLabel("")
        self._cursor.setStyleSheet("color: gray;")
        cl.addWidget(self._cursor)
        mid.addWidget(canvas_g, 3)

        pal_g = QGroupBox(tr("ed.palette"))
        pl = QVBoxLayout(pal_g)

        scene_row = QHBoxLayout()
        scene_row.addWidget(QLabel(tr("ed.scene_palette")))
        self._scene_combo = QComboBox()
        self._scene_combo.setEnabled(False)
        self._scene_combo.setToolTip(tr("ed.tt.scene_combo"))
        scene_row.addWidget(self._scene_combo, 1)
        self._btn_scene_pal = QPushButton(tr("ed.scene_load"))
        self._btn_scene_pal.clicked.connect(self._load_palette_from_scene_selection)
        self._btn_scene_pal.setEnabled(False)
        self._btn_scene_pal.setToolTip(tr("ed.tt.scene_load"))
        scene_row.addWidget(self._btn_scene_pal)
        pl.addLayout(scene_row)

        ext_row = QHBoxLayout()
        self._btn_load_pal = QPushButton(tr("ed.load_palette"))
        self._btn_load_pal.setToolTip(tr("ed.tt.load_palette"))
        self._btn_load_pal.clicked.connect(self._load_external_palette)
        ext_row.addWidget(self._btn_load_pal)
        self._btn_apply_pal = QPushButton(tr("ed.apply_palette"))
        self._btn_apply_pal.setToolTip(tr("ed.tt.apply_palette"))
        self._btn_apply_pal.clicked.connect(self._apply_external_palette)
        self._btn_apply_pal.setEnabled(False)
        ext_row.addWidget(self._btn_apply_pal)
        self._btn_manual_map = QPushButton(tr("ed.manual_map"))
        self._btn_manual_map.setToolTip(tr("ed.tt.manual_map"))
        self._btn_manual_map.clicked.connect(self._manual_palette_map)
        self._btn_manual_map.setEnabled(False)
        ext_row.addWidget(self._btn_manual_map)
        ext_row.addStretch()
        pl.addLayout(ext_row)

        self._ext_lbl = QLabel(tr("ed.ext_none"))
        self._ext_lbl.setStyleSheet("color: gray; font-style: italic;")
        pl.addWidget(self._ext_lbl)

        self._ext_container = QWidget()
        self._ext_layout = QHBoxLayout(self._ext_container)
        self._ext_layout.setContentsMargins(0, 0, 0, 0)
        self._ext_layout.setSpacing(4)
        self._ext_layout.addStretch()
        pl.addWidget(self._ext_container)

        self._pal_lbl = QLabel("")
        self._pal_lbl.setStyleSheet("color: gray;")
        pl.addWidget(self._pal_lbl)
        self._pal_container = QWidget()
        self._pal_layout = QVBoxLayout(self._pal_container)
        self._pal_layout.setSpacing(4)
        self._pal_layout.addStretch()
        pal_scroll = QScrollArea()
        pal_scroll.setWidgetResizable(True)
        pal_scroll.setWidget(self._pal_container)
        pl.addWidget(pal_scroll, 1)
        mid.addWidget(pal_g, 1)

        root.addLayout(mid, 1)

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def _open_file(self) -> None:
        start = QSettings("NGPCraft", "Engine").value("ed/last_dir", "", str)
        path, _ = QFileDialog.getOpenFileName(
            self, tr("ed.open"), start, tr("pal.file_filter")
        )
        if not path:
            return
        self.open_path(Path(path))

    def open_path(self, path: Path) -> None:
        """Load an image from disk into the editor, prompting before discarding edits."""
        if self._dirty:
            if QMessageBox.question(
                self, tr("ed.confirm_title"), tr("ed.confirm_discard")
            ) != QMessageBox.StandardButton.Yes:
                return
        try:
            img = Image.open(path).convert("RGBA")
        except Exception as e:
            QMessageBox.warning(self, tr("ed.open"), tr("ed.load_error", err=str(e)))
            return

        self._path = path
        self._img = quantize_image(img)
        self._dirty = False
        self._update_rail_highlight(path)
        self._hover_px = None
        self._sel_anchor = None
        self._sel_rect = None
        self._sel_temp = None
        self._cursor.setText("")
        self._undo.clear()
        self._install_watcher()
        QSettings("NGPCraft", "Engine").setValue("ed/last_dir", str(path.parent))

        self._file_lbl.setText(str(path))
        self._file_lbl.setStyleSheet("")
        self._btn_save.setEnabled(True)
        self._btn_save_as.setEnabled(True)
        for b in (self._btn_flip_h, self._btn_flip_v, self._btn_rot_l, self._btn_rot_r, self._btn_replace):
            b.setEnabled(True)
        self._btn_apply_pal.setEnabled(bool(self._img and self._ext_palette))
        self._btn_manual_map.setEnabled(bool(self._img and self._ext_palette))
        self._refresh_all()

    def _save_overwrite(self) -> None:
        if self._path is None or self._img is None:
            return
        try:
            self._img.save(str(self._path))
            self._dirty = False
            self._status.setText(tr("ed.saved", path=str(self._path)))
            self._install_watcher()
        except Exception as e:
            QMessageBox.warning(self, tr("ed.save"), tr("ed.save_error", err=str(e)))

    def _save_as(self) -> None:
        if self._img is None:
            return
        default = str(self._path) if self._path else ""
        path, _ = QFileDialog.getSaveFileName(self, tr("ed.save_as"), default, "PNG (*.png)")
        if not path:
            return
        try:
            self._img.save(path)
            self._status.setText(tr("ed.saved", path=path))
        except Exception as e:
            QMessageBox.warning(self, tr("ed.save_as"), tr("ed.save_error", err=str(e)))

    # ------------------------------------------------------------------
    # External palette
    # ------------------------------------------------------------------

    def _load_external_palette(self) -> None:
        start = QSettings("NGPCraft", "Engine").value("ed/last_dir", "", str)
        path, _ = QFileDialog.getOpenFileName(self, tr("ed.load_palette"), start, tr("pal.file_filter"))
        if not path:
            return
        try:
            img = quantize_image(Image.open(path).convert("RGBA"))
            pal = palette_from_image(img)
        except Exception as e:
            QMessageBox.warning(self, tr("ed.load_palette"), tr("ed.load_error", err=str(e)))
            return

        self._set_external_palette(pal, Path(path))

    def _refresh_ext_palette_panel(self) -> None:
        while self._ext_layout.count() > 1:
            it = self._ext_layout.takeAt(0)
            if w := it.widget():
                w.deleteLater()

        if not self._ext_palette:
            self._ext_lbl.setText(tr("ed.ext_none"))
            self._ext_lbl.setStyleSheet("color: gray; font-style: italic;")
            return

        name = self._ext_palette_path.name if self._ext_palette_path else "?"
        self._ext_lbl.setText(tr("ed.ext_loaded", name=name, n=len(self._ext_palette)))
        self._ext_lbl.setStyleSheet("color: gray;")

        for (r, g, b) in self._ext_palette[:16]:
            btn = QPushButton("")
            btn.setFixedSize(18, 16)
            btn.setStyleSheet(f"background-color: rgb({r},{g},{b}); border: 1px solid #333;")
            btn.clicked.connect(lambda _c, col=(r, g, b): self._set_current_color(col))
            self._ext_layout.insertWidget(self._ext_layout.count() - 1, btn)

    def _set_external_palette(self, pal: list[tuple[int, int, int]], path: Path | None) -> None:
        self._ext_palette = [snap(*c) for c in pal]
        self._ext_palette_path = path
        self._btn_apply_pal.setEnabled(bool(self._img and self._ext_palette))
        self._btn_manual_map.setEnabled(bool(self._img and self._ext_palette))
        self._refresh_ext_palette_panel()

    def _apply_external_palette(self) -> None:
        if self._img is None or not self._ext_palette:
            return
        ext = [snap(*c) for c in self._ext_palette if c]
        if not ext:
            return

        def _nearest(col: tuple[int, int, int]) -> tuple[int, int, int]:
            r, g, b = col
            r4, g4, b4 = (r >> 4), (g >> 4), (b >> 4)
            best = ext[0]
            br4, bg4, bb4 = (best[0] >> 4), (best[1] >> 4), (best[2] >> 4)
            best_d = (r4 - br4) ** 2 + (g4 - bg4) ** 2 + (b4 - bb4) ** 2
            for rr, gg, bb in ext[1:]:
                d = (r4 - (rr >> 4)) ** 2 + (g4 - (gg >> 4)) ** 2 + (b4 - (bb >> 4)) ** 2
                if d < best_d:
                    best_d = d
                    best = (rr, gg, bb)
            return best

        self._undo.push(self._img)
        px = self._img.load()
        w, h = self._img.size
        cache: dict[tuple[int, int, int], tuple[int, int, int]] = {}
        for yy in range(h):
            for xx in range(w):
                r, g, b, a = px[xx, yy]
                if a < 128:
                    continue
                key = (r, g, b)
                out = cache.get(key)
                if out is None:
                    out = _nearest(key)
                    cache[key] = out
                px[xx, yy] = (out[0], out[1], out[2], 255)

        self._after_edit(throttle=False)

    def _manual_palette_map(self) -> None:
        if self._img is None or not self._ext_palette:
            return

        px = self._img.load()
        w, h = self._img.size
        counts: dict[tuple[int, int, int], int] = {}
        for yy in range(h):
            for xx in range(w):
                r, g, b, a = px[xx, yy]
                if a < 128:
                    continue
                counts[(r, g, b)] = counts.get((r, g, b), 0) + 1

        src_pal = [snap(*c) for c in palette_from_image(self._img)]
        src_pal.sort(key=lambda c: (-counts.get(c, 0), _rgb_to_word(c)))
        dst_pal = [snap(*c) for c in self._ext_palette]
        if not src_pal or not dst_pal:
            return

        def _nearest(col: tuple[int, int, int]) -> tuple[int, int, int]:
            r, g, b = col
            r4, g4, b4 = (r >> 4), (g >> 4), (b >> 4)
            best = dst_pal[0]
            br4, bg4, bb4 = (best[0] >> 4), (best[1] >> 4), (best[2] >> 4)
            best_d = (r4 - br4) ** 2 + (g4 - bg4) ** 2 + (b4 - bb4) ** 2
            for rr, gg, bb in dst_pal[1:]:
                d = (r4 - (rr >> 4)) ** 2 + (g4 - (gg >> 4)) ** 2 + (b4 - (bb >> 4)) ** 2
                if d < best_d:
                    best_d = d
                    best = (rr, gg, bb)
            return best

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("ed.map_title"))
        dlg.setModal(True)
        dlg.setMinimumWidth(560)

        root = QVBoxLayout(dlg)
        info = QLabel(tr("ed.map_hint"))
        info.setStyleSheet("color: gray;")
        root.addWidget(info)

        tbl = QTableWidget(len(src_pal), 4)
        tbl.setHorizontalHeaderLabels([tr("ed.map_src"), tr("ed.map_count"), tr("ed.map_dst"), tr("ed.map_word")])
        tbl.verticalHeader().setVisible(False)
        tbl.setAlternatingRowColors(True)
        tbl.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        tbl.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        combos: list[QComboBox] = []
        for row, src in enumerate(src_pal):
            src_item = QTableWidgetItem(f"0x{_rgb_to_word(src):03X}")
            src_item.setIcon(_rgb_icon(src))
            tbl.setItem(row, 0, src_item)

            cnt_item = QTableWidgetItem(str(counts.get(src, 0)))
            tbl.setItem(row, 1, cnt_item)

            combo = QComboBox()
            combo.addItem(_rgb_icon(src), tr("ed.map_keep"))
            for dst in dst_pal:
                combo.addItem(_rgb_icon(dst), f"0x{_rgb_to_word(dst):03X}")

            nearest = _nearest(src)
            try:
                combo.setCurrentIndex(1 + dst_pal.index(nearest))
            except Exception:
                combo.setCurrentIndex(0)

            tbl.setCellWidget(row, 2, combo)

            w_item = QTableWidgetItem("")
            tbl.setItem(row, 3, w_item)

            def _update_word(_idx: int, *, r=row, src_col=src, cb=combo) -> None:
                if cb.currentIndex() <= 0:
                    w = _rgb_to_word(src_col)
                else:
                    w = _rgb_to_word(dst_pal[cb.currentIndex() - 1])
                it = tbl.item(r, 3)
                if it:
                    it.setText(f"0x{w:03X}")

            combo.currentIndexChanged.connect(_update_word)
            _update_word(combo.currentIndex())
            combos.append(combo)

        root.addWidget(tbl, 1)

        btns = QHBoxLayout()
        btns.addStretch()
        btn_cancel = QPushButton(tr("ed.map_cancel"))
        btn_cancel.clicked.connect(dlg.reject)
        btns.addWidget(btn_cancel)
        btn_apply = QPushButton(tr("ed.map_apply"))
        btn_apply.clicked.connect(dlg.accept)
        btns.addWidget(btn_apply)
        root.addLayout(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        mapping: dict[tuple[int, int, int], tuple[int, int, int]] = {}
        for row, src in enumerate(src_pal):
            cb = combos[row]
            if cb.currentIndex() <= 0:
                continue
            mapping[src] = dst_pal[cb.currentIndex() - 1]

        if not mapping:
            return

        self._undo.push(self._img)
        px = self._img.load()
        w, h = self._img.size
        for yy in range(h):
            for xx in range(w):
                r, g, b, a = px[xx, yy]
                if a < 128:
                    continue
                repl = mapping.get((r, g, b))
                if repl is None:
                    continue
                px[xx, yy] = (repl[0], repl[1], repl[2], 255)
        self._after_edit(throttle=False)

    def _install_watcher(self) -> None:
        self._watcher.removePaths(self._watcher.files())
        if self._path and self._path.exists():
            self._watcher.addPath(str(self._path))

    def _on_file_changed(self, _p: str) -> None:
        if not self._auto_reload.isChecked():
            return
        self._reload_timer.start(250)

    def _reload_from_disk(self) -> None:
        if self._path is None:
            return
        if not self._path.exists():
            self._reload_timer.start(350)
            return
        if self._dirty:
            if QMessageBox.question(self, tr("ed.reload_title"), tr("ed.reload_msg", path=self._path.name)) != QMessageBox.StandardButton.Yes:
                self._install_watcher()
                return
        self.open_path(self._path)

    # ------------------------------------------------------------------
    # Tools / actions
    # ------------------------------------------------------------------

    def _set_tool(self, tool: str) -> None:
        self._tool = tool
        for t, btn in (
            ("pencil", self._btn_pencil),
            ("eraser", self._btn_eraser),
            ("picker", self._btn_picker),
            ("fill", self._btn_fill),
            ("select", self._btn_select),
        ):
            btn.setChecked(t == tool)

    def _cancel_modes(self) -> None:
        if self._replace_mode:
            self._replace_mode = False
            self._cursor.setText("")
            self._set_tool("pencil")
        if self._sel_anchor is not None or self._sel_temp is not None or self._sel_rect is not None:
            self._sel_anchor = None
            self._sel_temp = None
            self._sel_rect = None
            self._refresh_selection_ui()
            self._canvas.update()

    def _pick_color(self) -> None:
        initial = QColor(*self._color)
        chosen = QColorDialog.getColor(initial, self, tr("ed.pick_color"))
        if not chosen.isValid():
            return
        self._color = snap(chosen.red(), chosen.green(), chosen.blue())
        self._refresh_color_button()

    def _refresh_color_button(self) -> None:
        r, g, b = self._color
        self._btn_color.setStyleSheet(f"background-color: rgb({r},{g},{b}); border: 1px solid #333;")

    def _set_zoom(self, zoom: int) -> None:
        self._zoom = zoom
        for z in (1, 2, 4, 8, 16, 32):
            b = getattr(self, f"_zoom_{z}", None)
            if b:
                b.setChecked(z == zoom)
        self._refresh_pixmap()

    def _step_zoom(self, delta: int) -> None:
        steps = [1, 2, 4, 8, 16, 32]
        try:
            idx = steps.index(self._zoom)
        except ValueError:
            idx = 3
        idx = max(0, min(len(steps) - 1, idx + delta))
        self._set_zoom(steps[idx])

    def _set_grid(self, on: bool) -> None:
        self._grid = on
        self._canvas.update()

    def _set_tile_overlay(self, on: bool) -> None:
        self._tile_overlay = on
        self._canvas.update()

    def _on_brush_changed(self, _idx: int) -> None:
        try:
            self._brush_size = int(self._cmb_brush.currentData())
        except Exception:
            self._brush_size = int(self._cmb_brush.currentText() or "1")

    def _set_symmetry(self, sym_h: bool, sym_v: bool) -> None:
        self._sym_h = sym_h
        self._sym_v = sym_v

    def _start_replace_mode(self) -> None:
        if self._img is None:
            return
        self._replace_mode = True
        self._set_tool("picker")
        self._cursor.setText(tr("ed.replace_hint"))

    def _replace_color(self, src: tuple[int, int, int]) -> None:
        chosen = QColorDialog.getColor(QColor(*src), self, tr("ed.replace_title"))
        if not chosen.isValid():
            return
        dst = snap(chosen.red(), chosen.green(), chosen.blue())
        if dst == src:
            return

        if self._img is None:
            return
        self._undo.push(self._img)
        px = self._img.load()
        w, h = self._img.size
        sel = self._sel_rect
        if sel is not None:
            x0, y0, sw, sh = sel
            x1 = min(w, x0 + sw)
            y1 = min(h, y0 + sh)
            xr = range(max(0, x0), max(0, x1))
            yr = range(max(0, y0), max(0, y1))
        else:
            xr = range(w)
            yr = range(h)
        changed = 0
        for yy in yr:
            for xx in xr:
                r, g, b, a = px[xx, yy]
                if a < 128:
                    continue
                if (r, g, b) == src:
                    px[xx, yy] = (dst[0], dst[1], dst[2], a)
                    changed += 1

        self._after_edit(throttle=False)
        self._cursor.setText(tr("ed.replace_done", n=changed))

    def _flip_h(self) -> None:
        if self._img is None:
            return
        self._undo.push(self._img)
        sel = self._sel_rect
        if sel is None:
            try:
                self._img = self._img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            except Exception:
                self._img = self._img.transpose(Image.FLIP_LEFT_RIGHT)
        else:
            x, y, w, h = sel
            region = self._img.crop((x, y, x + w, y + h))
            try:
                region = region.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            except Exception:
                region = region.transpose(Image.FLIP_LEFT_RIGHT)
            self._img.paste(region, (x, y))
        self._after_edit(throttle=False)

    def _flip_v(self) -> None:
        if self._img is None:
            return
        self._undo.push(self._img)
        sel = self._sel_rect
        if sel is None:
            try:
                self._img = self._img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            except Exception:
                self._img = self._img.transpose(Image.FLIP_TOP_BOTTOM)
        else:
            x, y, w, h = sel
            region = self._img.crop((x, y, x + w, y + h))
            try:
                region = region.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
            except Exception:
                region = region.transpose(Image.FLIP_TOP_BOTTOM)
            self._img.paste(region, (x, y))
        self._after_edit(throttle=False)

    def _rot_l(self) -> None:
        if self._img is None:
            return
        sel = self._sel_rect
        if sel is not None and sel[2] != sel[3]:
            QMessageBox.information(self, tr("ed.confirm_title"), tr("ed.sel_square_rot"))
            return
        self._undo.push(self._img)
        if sel is None:
            try:
                self._img = self._img.transpose(Image.Transpose.ROTATE_90)
            except Exception:
                self._img = self._img.transpose(Image.ROTATE_90)
        else:
            x, y, w, h = sel
            region = self._img.crop((x, y, x + w, y + h))
            try:
                region = region.transpose(Image.Transpose.ROTATE_90)
            except Exception:
                region = region.transpose(Image.ROTATE_90)
            self._img.paste(region, (x, y))
        self._after_edit(throttle=False)

    def _rot_r(self) -> None:
        if self._img is None:
            return
        sel = self._sel_rect
        if sel is not None and sel[2] != sel[3]:
            QMessageBox.information(self, tr("ed.confirm_title"), tr("ed.sel_square_rot"))
            return
        self._undo.push(self._img)
        if sel is None:
            try:
                self._img = self._img.transpose(Image.Transpose.ROTATE_270)
            except Exception:
                self._img = self._img.transpose(Image.ROTATE_270)
        else:
            x, y, w, h = sel
            region = self._img.crop((x, y, x + w, y + h))
            try:
                region = region.transpose(Image.Transpose.ROTATE_270)
            except Exception:
                region = region.transpose(Image.ROTATE_270)
            self._img.paste(region, (x, y))
        self._after_edit(throttle=False)

    def _on_undo(self) -> None:
        if self._img is None:
            return
        out = self._undo.undo(self._img)
        if out is None:
            return
        self._img = out
        self._dirty = True
        self._refresh_all()

    def _on_redo(self) -> None:
        if self._img is None:
            return
        out = self._undo.redo(self._img)
        if out is None:
            return
        self._img = out
        self._dirty = True
        self._refresh_all()

    # ------------------------------------------------------------------
    # Stroke handling
    # ------------------------------------------------------------------

    def _to_px(self, x: int, y: int) -> tuple[int, int] | None:
        if self._img is None:
            return None
        px = x // self._zoom
        py = y // self._zoom
        if 0 <= px < self._img.width and 0 <= py < self._img.height:
            return px, py
        return None

    def _in_selection(self, x: int, y: int) -> bool:
        sel = self._sel_rect
        if sel is None:
            return True
        sx, sy, sw, sh = sel
        return sx <= x < (sx + sw) and sy <= y < (sy + sh)

    def _rect_from_two_points(self, a: tuple[int, int], b: tuple[int, int]) -> tuple[int, int, int, int]:
        x0 = min(a[0], b[0])
        y0 = min(a[1], b[1])
        x1 = max(a[0], b[0]) + 1
        y1 = max(a[1], b[1]) + 1
        return x0, y0, max(1, x1 - x0), max(1, y1 - y0)

    def _begin_select(self, x: int, y: int) -> None:
        if self._img is None:
            return
        p = self._to_px(x, y)
        if p is None:
            return
        self._sel_anchor = p
        self._sel_temp = (p[0], p[1], 1, 1)
        self._canvas.update()

    def _continue_select(self, x: int, y: int) -> None:
        if self._img is None or self._sel_anchor is None:
            return
        p = self._to_px(x, y)
        if p is None:
            return
        self._sel_temp = self._rect_from_two_points(self._sel_anchor, p)
        self._canvas.update()

    def _end_select(self, x: int, y: int) -> None:
        if self._img is None or self._sel_anchor is None:
            self._sel_anchor = None
            self._sel_temp = None
            return
        p = self._to_px(x, y)
        if p is None:
            self._sel_anchor = None
            self._sel_temp = None
            self._canvas.update()
            return
        self._sel_rect = self._rect_from_two_points(self._sel_anchor, p)
        self._sel_anchor = None
        self._sel_temp = None
        self._refresh_selection_ui()
        self._canvas.update()

    def _hover(self, x: int, y: int) -> None:
        if self._img is None:
            self._cursor.setText("")
            if self._hover_px is not None:
                self._hover_px = None
                self._canvas.update()
            return
        p = self._to_px(x, y)
        if p is None:
            self._cursor.setText("")
            if self._hover_px is not None:
                self._hover_px = None
                self._canvas.update()
            return
        px, py = p
        if self._hover_px != (px, py):
            self._hover_px = (px, py)
            self._canvas.update()
        tx, ty = px // 8, py // 8
        r, g, b, a = self._img.getpixel((px, py))
        if a < 128:
            col = tr("ed.cursor_trans")
        else:
            col = f"0x{((r>>4)|((g>>4)<<4)|((b>>4)<<8)):03X}"
        msg = tr("ed.cursor", x=px, y=py, tx=tx, ty=ty, col=col)
        if self._sel_rect is not None:
            msg += "  " + tr("ed.sel", w=self._sel_rect[2], h=self._sel_rect[3])
        self._cursor.setText(msg)

    def _clear_hover(self) -> None:
        if self._hover_px is None:
            return
        self._hover_px = None
        self._cursor.setText("")
        self._canvas.update()

    def _begin_stroke(self, x: int, y: int, *, erase: bool) -> None:
        if self._img is None:
            return
        p = self._to_px(x, y)
        if p is None:
            return
        self._stroke_active = True
        self._last_px = p
        self._stroke_erase = erase

        if self._tool in ("pencil", "eraser", "fill"):
            self._undo.push(self._img)

        if self._tool == "picker":
            self._picker_at(p[0], p[1])
            self._stroke_active = False
            return
        if self._tool == "fill":
            for fx, fy in self._sym_points(p[0], p[1]):
                self._fill_at(fx, fy)
            self._stroke_active = False
            self._after_edit()
            return

        self._draw_point(p[0], p[1])
        self._after_edit(throttle=True)

    def _continue_stroke(self, x: int, y: int, *, erase: bool) -> None:
        if not self._stroke_active or self._img is None:
            return
        self._stroke_erase = erase
        p = self._to_px(x, y)
        if p is None:
            return
        if self._last_px is None:
            self._last_px = p
            return
        if p == self._last_px:
            return
        self._draw_line(self._last_px[0], self._last_px[1], p[0], p[1])
        self._last_px = p
        self._after_edit(throttle=True)

    def _end_stroke(self) -> None:
        if not self._stroke_active:
            return
        self._stroke_active = False
        self._last_px = None
        self._after_edit(throttle=False)

    def _draw_point(self, x: int, y: int) -> None:
        if self._img is None:
            return
        for px, py in self._sym_points(x, y):
            self._draw_brush(px, py)

    def _sym_points(self, x: int, y: int) -> list[tuple[int, int]]:
        if self._img is None:
            return [(x, y)]
        w, h = self._img.size
        pts: set[tuple[int, int]] = {(x, y)}
        if self._sym_h:
            pts.add((w - 1 - x, y))
        if self._sym_v:
            pts.add((x, h - 1 - y))
        if self._sym_h and self._sym_v:
            pts.add((w - 1 - x, h - 1 - y))
        return sorted(pts)

    def _draw_brush(self, x: int, y: int) -> None:
        if self._img is None:
            return
        px = self._img.load()
        size = max(1, int(self._brush_size))
        half = size // 2
        start = -half
        end = start + size
        for dy in range(start, end):
            yy = y + dy
            if yy < 0 or yy >= self._img.height:
                continue
            for dx in range(start, end):
                xx = x + dx
                if xx < 0 or xx >= self._img.width:
                    continue
                if not self._in_selection(xx, yy):
                    continue
                if self._tool == "eraser" or self._stroke_erase:
                    px[xx, yy] = (0, 0, 0, 0)
                else:
                    r, g, b = self._color
                    px[xx, yy] = (r, g, b, 255)

    def _draw_line(self, x0: int, y0: int, x1: int, y1: int) -> None:
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        x, y = x0, y0
        while True:
            self._draw_point(x, y)
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy

    def _picker_at(self, x: int, y: int) -> None:
        if self._img is None:
            return
        r, g, b, a = self._img.getpixel((x, y))
        if a < 128:
            return

        if self._replace_mode:
            self._replace_mode = False
            src = snap(r, g, b)
            self._replace_color(src)
            self._set_tool("pencil")
            return

        self._color = snap(r, g, b)
        self._refresh_color_button()
        self._set_tool("pencil")

    def _fill_at(self, x: int, y: int) -> None:
        if self._img is None:
            return
        if not self._in_selection(x, y):
            return
        img = self._img
        px = img.load()
        target = px[x, y]
        if self._stroke_erase:
            repl = (0, 0, 0, 0)
        else:
            r, g, b = self._color
            repl = (r, g, b, 255)
        if target == repl:
            return
        w, h = img.size
        q: deque[tuple[int, int]] = deque()
        q.append((x, y))
        seen: set[int] = set()

        def _k(xx: int, yy: int) -> int:
            return yy * w + xx

        while q:
            cx, cy = q.popleft()
            if not self._in_selection(cx, cy):
                continue
            key = _k(cx, cy)
            if key in seen:
                continue
            seen.add(key)
            if px[cx, cy] != target:
                continue
            px[cx, cy] = repl
            if cx > 0:
                q.append((cx - 1, cy))
            if cx + 1 < w:
                q.append((cx + 1, cy))
            if cy > 0:
                q.append((cx, cy - 1))
            if cy + 1 < h:
                q.append((cx, cy + 1))

    # ------------------------------------------------------------------
    # Selection actions
    # ------------------------------------------------------------------

    def _refresh_selection_ui(self) -> None:
        has_img = self._img is not None
        has_sel = has_img and self._sel_rect is not None
        self._btn_sel_all.setEnabled(has_img)
        self._btn_copy.setEnabled(has_sel)
        self._btn_cut.setEnabled(has_sel)
        self._btn_paste.setEnabled(has_img)
        self._btn_clear_sel.setEnabled(has_sel)

    def _select_all(self) -> None:
        if self._img is None:
            return
        self._sel_rect = (0, 0, self._img.width, self._img.height)
        self._refresh_selection_ui()
        self._canvas.update()

    def _selection_box(self) -> tuple[int, int, int, int] | None:
        if self._img is None:
            return None
        if self._sel_rect is None:
            return (0, 0, self._img.width, self._img.height)
        return self._sel_rect

    def _copy_selection(self) -> None:
        if self._img is None:
            return
        sel = self._selection_box()
        if sel is None:
            return
        x, y, w, h = sel
        region = self._img.crop((x, y, x + w, y + h))
        self._clip_img = region.copy()
        try:
            QApplication.clipboard().setImage(_pil_to_qimage(region))
        except Exception:
            pass
        self._status.setText(tr("ed.clip_copied", w=w, h=h))

    def _clear_selection_pixels(self) -> None:
        if self._img is None or self._sel_rect is None:
            return
        x, y, w, h = self._sel_rect
        self._undo.push(self._img)
        px = self._img.load()
        for yy in range(y, min(self._img.height, y + h)):
            for xx in range(x, min(self._img.width, x + w)):
                px[xx, yy] = (0, 0, 0, 0)
        self._after_edit(throttle=False)

    def _cut_selection(self) -> None:
        if self._img is None or self._sel_rect is None:
            return
        self._copy_selection()
        self._clear_selection_pixels()

    def _get_paste_source(self) -> Image.Image | None:
        if self._clip_img is not None:
            return self._clip_img.copy()
        try:
            qimg = QApplication.clipboard().image()
        except Exception:
            return None
        return _qimage_to_pil(qimg)

    def _paste(self) -> None:
        if self._img is None:
            return
        src = self._get_paste_source()
        if src is None:
            self._status.setText(tr("ed.clip_empty"))
            return

        if self._sel_rect is not None:
            dx, dy = self._sel_rect[0], self._sel_rect[1]
        elif self._hover_px is not None:
            dx, dy = self._hover_px
        else:
            dx, dy = 0, 0

        dx = max(0, min(self._img.width - 1, int(dx)))
        dy = max(0, min(self._img.height - 1, int(dy)))
        max_w = max(0, self._img.width - dx)
        max_h = max(0, self._img.height - dy)
        w = min(src.width, max_w)
        h = min(src.height, max_h)
        if w <= 0 or h <= 0:
            return

        src = src.convert("RGBA").crop((0, 0, w, h))
        self._undo.push(self._img)
        base_region = self._img.crop((dx, dy, dx + w, dy + h)).convert("RGBA")
        try:
            composed = Image.alpha_composite(base_region, src)
        except Exception:
            composed = src
        self._img.paste(composed, (dx, dy))
        self._sel_rect = (dx, dy, w, h)
        self._refresh_selection_ui()
        self._after_edit(throttle=False)
        self._status.setText(tr("ed.clip_pasted", w=w, h=h))

    def _after_edit(self, throttle: bool = True) -> None:
        self._dirty = True
        self._refresh_pixmap()
        self._btn_undo.setEnabled(self._undo.can_undo())
        self._btn_redo.setEnabled(self._undo.can_redo())
        if throttle:
            self._stats_timer.start(180)
        else:
            self._recompute_stats()

    # ------------------------------------------------------------------
    # Refresh / stats
    # ------------------------------------------------------------------

    def _refresh_all(self) -> None:
        self._refresh_pixmap()
        self._recompute_stats()
        self._btn_undo.setEnabled(self._undo.can_undo())
        self._btn_redo.setEnabled(self._undo.can_redo())
        self._btn_apply_pal.setEnabled(bool(self._img and self._ext_palette))
        self._btn_manual_map.setEnabled(bool(self._img and self._ext_palette))
        self._refresh_ext_palette_panel()
        self._refresh_selection_ui()

    def _refresh_pixmap(self) -> None:
        if self._img is None:
            self._pixmap = None
            self._canvas.setFixedSize(240, 160)
            self._canvas.update()
            return
        pm = _make_zoom_pixmap(self._img, self._zoom)
        self._pixmap = pm
        self._canvas.setFixedSize(pm.size())
        self._canvas.update()

    def _recompute_stats(self) -> None:
        if self._img is None:
            self._tile_counts = []
            self._status.setText("")
            self._pal_lbl.setText("")
            self._refresh_palette_panel([])
            return
        try:
            self._tile_counts = colors_per_tile(self._img)
            flat = [c for row in self._tile_counts for c in row]
            max_c = max(flat) if flat else 0
            if max_c <= 3:
                self._status.setText(tr("pal.all_tiles_ok"))
                self._status.setStyleSheet("color: #4ec94e;")
            else:
                self._status.setText(tr("pal.too_many_colors", max_c=max_c))
                self._status.setStyleSheet("color: #e07030;")
        except Exception as e:
            self._status.setText(str(e))
            self._status.setStyleSheet("color: #e07030;")

        pal = palette_from_image(self._img)
        self._pal_lbl.setText(tr("ed.palette_count", n=len(pal)))
        self._refresh_palette_panel(pal)
        self._canvas.update()

    def _refresh_palette_panel(self, pal: list[tuple[int, int, int]]) -> None:
        while self._pal_layout.count() > 1:
            it = self._pal_layout.takeAt(0)
            if w := it.widget():
                w.deleteLater()
        for i, (r, g, b) in enumerate(pal[:32]):
            row = QHBoxLayout()
            btn = QPushButton("")
            btn.setFixedSize(26, 18)
            btn.setStyleSheet(f"background-color: rgb({r},{g},{b}); border: 1px solid #333;")
            btn.clicked.connect(lambda _c, col=(r, g, b): self._set_current_color(col))
            row.addWidget(btn)
            row.addWidget(QLabel(f"#{i:02d}  0x{(r>>4)|((g>>4)<<4)|((b>>4)<<8):03X}"))
            row.addStretch()
            wrap = QWidget()
            wrap.setLayout(row)
            self._pal_layout.insertWidget(self._pal_layout.count() - 1, wrap)

    def _set_current_color(self, col: tuple[int, int, int]) -> None:
        self._color = snap(*col)
        self._refresh_color_button()
        self._set_tool("pencil")

    # ------------------------------------------------------------------
    # Scene integration (optional, Project mode)
    # ------------------------------------------------------------------

    def set_scene(self, scene: dict | None, base_dir: Path | None) -> None:
        """Attach a scene so the editor can browse its sprite sources and palettes."""
        self._scene = scene
        self._scene_base = base_dir
        self._refresh_scene_sources()
        self._refresh_rail()

    def _refresh_scene_sources(self) -> None:
        self._scene_combo.blockSignals(True)
        self._scene_combo.clear()

        items: list[tuple[str, Path]] = []
        if self._scene and self._scene_base:
            for spr in self._scene.get("sprites", []):
                rel = spr.get("file", "")
                if not rel:
                    continue
                p = Path(rel)
                abs_p = p if p.is_absolute() else (self._scene_base / p)
                label = abs_p.name
                if not abs_p.exists():
                    label = f"{label} ({tr('ed.missing')})"
                items.append((label, abs_p))

        for label, p in items:
            self._scene_combo.addItem(label, p)

        self._scene_combo.blockSignals(False)
        has = bool(items)
        self._scene_combo.setEnabled(has)
        self._btn_scene_pal.setEnabled(has)

    def _load_palette_from_scene_selection(self) -> None:
        data = self._scene_combo.currentData()
        if not data:
            return
        p = Path(str(data))
        if not p.exists():
            QMessageBox.warning(self, tr("ed.load_palette"), tr("ed.load_error", err=tr("ed.missing")))
            return
        try:
            img = quantize_image(Image.open(p).convert("RGBA"))
            pal = palette_from_image(img)
        except Exception as e:
            QMessageBox.warning(self, tr("ed.load_palette"), tr("ed.load_error", err=str(e)))
            return
        self._set_external_palette(pal, p)

    # ------------------------------------------------------------------
    # Sprite rail
    # ------------------------------------------------------------------

    def _refresh_rail(self) -> None:
        while self._rail_layout.count():
            item = self._rail_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()
        self._rail_btns.clear()

        scene = self._scene
        base_dir = self._scene_base
        if not scene or not base_dir:
            self._rail_scroll.setVisible(False)
            return

        self._rail_scroll.setVisible(True)
        lbl = QLabel(scene.get("label", ""))
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("font-weight: bold; font-size: 9px;")
        lbl.setWordWrap(True)
        self._rail_layout.addWidget(lbl)

        for spr in scene.get("sprites", []):
            rel = spr.get("file", "")
            if not rel:
                continue
            p = Path(rel)
            abs_p = p if p.is_absolute() else (base_dir / p)
            self._add_rail_thumb(abs_p, spr.get("name", ""))
        self._rail_layout.addStretch()

        if self._path:
            self._update_rail_highlight(self._path)

    def _add_rail_thumb(self, path: Path, name: str) -> None:
        btn = QToolButton()
        btn.setFixedSize(80, 80)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setText((name or path.stem)[:10])
        btn.setToolTip(str(path))
        if path.exists():
            try:
                img = Image.open(path).convert("RGBA")
                img.thumbnail((52, 52), Image.NEAREST)
                data = img.tobytes("raw", "RGBA")
                qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
                pm = QPixmap.fromImage(qimg.copy())
                btn.setIcon(QIcon(pm))
                btn.setIconSize(QSize(52, 52))
                btn.clicked.connect(lambda _c, p=path, b=btn: self._rail_select(p, b))
            except Exception:
                btn.setEnabled(False)
        else:
            btn.setStyleSheet("color: gray;")
            btn.setEnabled(False)
        self._rail_btns.append((btn, path))
        self._rail_layout.addWidget(btn)

    def _rail_select(self, path: Path, clicked_btn: QToolButton) -> None:
        for b, _ in self._rail_btns:
            b.setStyleSheet("")
        clicked_btn.setStyleSheet("border: 2px solid #569ed6; border-radius: 3px;")
        self.open_path(path)

    def _update_rail_highlight(self, path: Path) -> None:
        for b, p in self._rail_btns:
            b.setStyleSheet(
                "border: 2px solid #569ed6; border-radius: 3px;" if p == path else ""
            )

    # ------------------------------------------------------------------
    # Drag & drop
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        """Accept dropped image files so the editor can open them directly."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        """Open the first dropped image file in the pixel editor."""
        for url in event.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.suffix.lower() in (".png", ".bmp", ".gif"):
                self.open_path(p)
                break
