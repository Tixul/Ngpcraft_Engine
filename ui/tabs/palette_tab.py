"""
ui/tabs/palette_tab.py - Palette editor tab (Phase 1 MVP).

Features:
- Open a PNG, display original and RGB444-quantized previews with zoom
- Detect and list opaque colors as clickable swatches
- Click a swatch → QColorDialog → snap to RGB444 → remap pixels live
- Color 0 is treated as the "transparent" slot (not editable)
- Per-tile color count overlay (green ≤3, red >3)
- Layer suggestion: "N colors → X layers recommended" with split button
- Layer split dialog: preview each layer, copy --fixed-palette, save PNGs
- Save remapped PNG
- Copy --fixed-palette string to clipboard
"""

from __future__ import annotations

import subprocess
import sys as _sys
import tempfile
from pathlib import Path

from PIL import Image
from PyQt6.QtCore import QMimeData, QSettings, Qt, QSize, QFileSystemWatcher, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap, QClipboard
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from ui.no_scroll import NoScrollSpinBox as QSpinBox  # noqa: F811

from core.layer_split import layers_needed, split_layers
from core.palette_remap import composite_on_checker, palette_to_fixed_arg
from core.rgb444 import colors_per_tile, from_word, palette_from_image, snap, to_word, to_word_sprite, quantize_image
from core.sprite_loader import SpriteData, load_sprite, remap_palette
from i18n.lang import tr
from ui.context_help import ContextHelpBox
from ui.tool_finder import default_candidates, find_script, script_dialog_start_dir, remember_script_path


# ---------------------------------------------------------------------------
# PIL Image → QPixmap helper
# ---------------------------------------------------------------------------

def _pil_to_qpixmap(img: Image.Image) -> QPixmap:
    """Convert a PIL RGBA image to a QPixmap."""
    rgb = img.convert("RGBA")
    data = rgb.tobytes("raw", "RGBA")
    qimg = QImage(data, rgb.width, rgb.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


def _make_zoom_pixmap(img: Image.Image, zoom: int) -> QPixmap:
    """Return a nearest-neighbor zoomed QPixmap."""
    w, h = img.size
    scaled = img.resize((w * zoom, h * zoom), Image.NEAREST)
    return _pil_to_qpixmap(scaled)

def _parse_fixed_palette_words(s: str) -> list[int] | None:
    if not s:
        return None
    parts = [p.strip() for p in str(s).split(",") if p.strip()]
    if len(parts) != 4:
        return None
    out: list[int] = []
    try:
        for p in parts:
            pp = p.strip().lower()
            if pp.startswith("0x"):
                pp = pp[2:]
            out.append(int(pp, 16))
    except Exception:
        return None
    if len(out) != 4:
        return None
    out[0] = 0x0000  # enforce transparent slot
    return out


def _fixed_palette_key(words: list[int]) -> str:
    w = (words + [0, 0, 0, 0])[:4]
    w[0] = 0x0000
    return ",".join(f"0x{int(x) & 0xFFFF:04X}" for x in w)


def _palette_icon_from_words(words: list[int], w: int = 72, h: int = 18) -> QIcon:
    img = QImage(w, h, QImage.Format.Format_RGBA8888)
    img.fill(QColor(0, 0, 0, 0))

    painter = QPainter(img)
    try:
        seg_w = max(1, w // 4)
        for i in range(4):
            word = int(words[i]) if i < len(words) else 0
            x0 = i * seg_w
            ww = seg_w if i < 3 else (w - x0)
            if i == 0 or word == 0:
                # checker for transparent/empty
                c1 = QColor(240, 240, 240)
                c2 = QColor(180, 180, 180)
                size = 4
                for yy in range(0, h, size):
                    for xx in range(0, ww, size):
                        c = c1 if (((xx // size) + (yy // size)) % 2 == 0) else c2
                        painter.fillRect(x0 + xx, yy, size, size, c)
            else:
                r, g, b = from_word(word)
                painter.fillRect(x0, 0, ww, h, QColor(r, g, b))
        painter.setPen(QColor(60, 60, 60))
        painter.drawRect(0, 0, w - 1, h - 1)
    finally:
        painter.end()
    return QIcon(QPixmap.fromImage(img))


# ---------------------------------------------------------------------------
# Color tile overlay
# ---------------------------------------------------------------------------

def _make_overlay_pixmap(
    img: Image.Image, zoom: int, tile_w: int = 8, tile_h: int = 8
) -> QPixmap:
    """
    Return a QPixmap same size as img×zoom with semi-transparent per-tile
    color-count overlay: green if ≤3 opaque colors, red if >3.
    """
    counts = colors_per_tile(img, tile_w, tile_h)
    cols = img.width // tile_w
    rows = img.height // tile_h
    overlay = Image.new("RGBA", (img.width * zoom, img.height * zoom), (0, 0, 0, 0))
    px = overlay.load()
    tile_pw = tile_w * zoom
    tile_ph = tile_h * zoom
    for row in range(rows):
        for col in range(cols):
            count = counts[row][col] if row < len(counts) and col < len(counts[row]) else 0
            if count <= 3:
                color = (0, 220, 0, 55)
            else:
                color = (220, 0, 0, 100)
            for ty in range(tile_ph):
                for tx in range(tile_pw):
                    px[col * tile_pw + tx, row * tile_ph + ty] = color
    return _pil_to_qpixmap(overlay)


# ---------------------------------------------------------------------------
# Color swatch button
# ---------------------------------------------------------------------------

class SwatchButton(QPushButton):
    """A small colored square button representing one palette slot."""

    SWATCH_SIZE = 28

    def __init__(self, index: int, color: tuple[int, int, int] | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.index = index
        self.setFixedSize(self.SWATCH_SIZE, self.SWATCH_SIZE)
        self.setFlat(True)
        self._set_color(color)

    def update_color(self, color: tuple[int, int, int]) -> None:
        """Refresh the swatch visual after an external palette change."""
        self._set_color(color)

    def _set_color(self, color: tuple[int, int, int] | None) -> None:
        if color is None:
            self.setStyleSheet("background-color: transparent; border: 1px solid gray;")
        else:
            r, g, b = color
            self.setStyleSheet(
                f"background-color: rgb({r},{g},{b}); border: 1px solid #333;"
            )


# ---------------------------------------------------------------------------
# Preview label (supports overlay)
# ---------------------------------------------------------------------------

class OverlayLabel(QLabel):
    """QLabel that can optionally paint a semi-transparent tile overlay."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._overlay: QPixmap | None = None

    def set_overlay(self, overlay: QPixmap | None) -> None:
        """Set or clear the semi-transparent tile overlay drawn above the preview."""
        self._overlay = overlay
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        """Paint the base pixmap first, then the optional overlay on top of it."""
        super().paintEvent(event)
        if self._overlay and self.pixmap() and not self.pixmap().isNull():
            from PyQt6.QtGui import QPainter
            pm = self.pixmap()
            # AlignCenter: pixmap is drawn centred in the label — match that offset.
            x = max(0, (self.width()  - pm.width())  // 2)
            y = max(0, (self.height() - pm.height()) // 2)
            painter = QPainter(self)
            painter.drawPixmap(x, y, self._overlay)
            painter.end()


# ---------------------------------------------------------------------------
# PaletteTab
# ---------------------------------------------------------------------------

class PaletteTab(QWidget): 
    """Sprite palette editor and preview tab for standalone assets or scene sprites."""

    apply_anim_to_scene_requested = pyqtSignal(object)  # dict payload
    apply_scene_palette_requested = pyqtSignal(object)  # dict payload

    def __init__(self, parent: QWidget | None = None) -> None: 
        super().__init__(parent) 
        self._data: SpriteData | None = None 
        self._zoom: int = 4 
        self._show_overlay: bool = True
        self._mono_mode: bool = False
        self._dirty: bool = False
        self._anim_playing: bool = False
        self._swatches: list[SwatchButton] = [] 
        self._swatch_labels: list[QLabel] = [] 
        self._scene_context: dict | None = None 
        self._scene_base_dir: Path | None = None 
        self._scene_pal_groups: dict[str, list[dict]] = {}
        self._scene_pal_selected: str | None = None
        self._scene_pal_old_words: list[int] | None = None
        self._scene_pal_new_words: list[int] | None = None
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.timeout.connect(self._reload_from_disk)
        self._anim_timer = QTimer(self)
        self._anim_timer.setSingleShot(False)
        self._anim_timer.timeout.connect(self._on_anim_tick)
        self._anim_timer.setInterval(120)
        self._build_ui()
        self._pal_vsplit.splitterMoved.connect(self._save_splitter_sizes)
        self._main_hsplit.splitterMoved.connect(self._save_splitter_sizes)
        self._restore_splitter_sizes()
        self.setAcceptDrops(True)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None: 
        root = QHBoxLayout(self)
        root.setSpacing(8)

        # Scene thumbnail rail (hidden by default, appears when a scene is active)
        self._rail_scroll = QScrollArea()
        self._rail_scroll.setFixedWidth(92)
        self._rail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rail_scroll.setWidgetResizable(True)
        self._rail_scroll.setVisible(False)
        rail_widget = QWidget()
        self._rail_layout = QVBoxLayout(rail_widget)
        self._rail_layout.setContentsMargins(4, 4, 4, 4)
        self._rail_layout.setSpacing(6)
        self._rail_scroll.setWidget(rail_widget)
        root.addWidget(self._rail_scroll)

        # Left: controls + previews
        left = QVBoxLayout()
        left.setSpacing(6)

        file_group = QGroupBox(tr("pal.group_file"))
        file_group_l = QVBoxLayout(file_group)
        # File row 
        file_row = QHBoxLayout() 
        self._file_label = QLabel(tr("pal.no_file")) 
        self._file_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed) 
        file_row.addWidget(QLabel(tr("pal.file_label"))) 
        file_row.addWidget(self._file_label, 1) 
        self._auto_reload = QCheckBox(tr("pal.auto_reload"))
        self._auto_reload.setChecked(True)
        file_row.addWidget(self._auto_reload)
        open_btn = QPushButton(tr("pal.open_file")) 
        open_btn.clicked.connect(self._open_file) 
        file_row.addWidget(open_btn) 
        file_group_l.addLayout(file_row)
        left.addWidget(file_group)

        view_group = QGroupBox(tr("pal.group_view"))
        view_group_l = QVBoxLayout(view_group)
        # Zoom row
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(QLabel(tr("pal.zoom")))
        for factor, key in ((1, "pal.zoom_x1"), (2, "pal.zoom_x2"), (4, "pal.zoom_x4"), (8, "pal.zoom_x8")): 
            btn = QPushButton(tr(key)) 
            btn.setFixedWidth(36)
            btn.setCheckable(True)
            btn.setChecked(factor == self._zoom)
            btn.clicked.connect(lambda checked, f=factor: self._set_zoom(f))
            setattr(self, f"_zoom_btn_{factor}", btn) 
            zoom_row.addWidget(btn) 
        self._overlay_check = QCheckBox(tr("pal.overlay_tiles"))
        self._overlay_check.setChecked(True)
        self._overlay_check.toggled.connect(self._toggle_overlay)
        zoom_row.addWidget(self._overlay_check)
        self._mono_check = QCheckBox(tr("pal.mono_mode"))
        self._mono_check.setChecked(False)
        self._mono_check.setToolTip(tr("pal.mono_mode_tt"))
        self._mono_check.toggled.connect(self._toggle_mono)
        zoom_row.addWidget(self._mono_check)
        zoom_row.addStretch()
        view_group_l.addLayout(zoom_row)
        left.addWidget(view_group)

        self._ctx_palette_flow = ContextHelpBox(
            tr("pal.ctx_workflow_title"),
            tr("pal.ctx_workflow_body"),
            self,
        )
        left.addWidget(self._ctx_palette_flow)

        # Preview area: original + HW side by side
        preview_row = QHBoxLayout()
        preview_row.setSpacing(12)

        orig_group = QGroupBox(tr("pal.preview_original"))
        orig_layout = QVBoxLayout(orig_group)
        self._orig_scroll = QScrollArea()
        self._orig_scroll.setWidgetResizable(False)
        self._orig_label = QLabel(tr("pal.drop_hint"))
        self._orig_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._orig_label.setMinimumSize(160, 120)
        self._orig_scroll.setWidget(self._orig_label)
        orig_layout.addWidget(self._orig_scroll)
        preview_row.addWidget(orig_group)

        hw_group = QGroupBox(tr("pal.preview_hw"))
        hw_layout = QVBoxLayout(hw_group)
        self._hw_scroll = QScrollArea()
        self._hw_scroll.setWidgetResizable(False)
        self._hw_label = OverlayLabel()
        self._hw_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hw_label.setMinimumSize(160, 120)
        self._hw_scroll.setWidget(self._hw_label)
        hw_layout.addWidget(self._hw_scroll)
        preview_row.addWidget(hw_group)

        left.addLayout(preview_row)

        # Tile status label 
        self._tile_status = QLabel("") 
        left.addWidget(self._tile_status) 

        # Animation preview
        self._anim_group = QGroupBox(tr("pal.anim_group"))
        anim_layout = QVBoxLayout(self._anim_group)
        anim_layout.setSpacing(4)

        cfg = QHBoxLayout()
        cfg.addWidget(QLabel(tr("pal.anim_frame_w")))
        self._anim_fw = QSpinBox()
        self._anim_fw.setRange(1, 4096)
        self._anim_fw.setSingleStep(8)
        self._anim_fw.valueChanged.connect(self._on_anim_cfg_changed)
        cfg.addWidget(self._anim_fw)

        cfg.addWidget(QLabel(tr("pal.anim_frame_h")))
        self._anim_fh = QSpinBox()
        self._anim_fh.setRange(1, 4096)
        self._anim_fh.setSingleStep(8)
        self._anim_fh.valueChanged.connect(self._on_anim_cfg_changed)
        cfg.addWidget(self._anim_fh)

        cfg.addWidget(QLabel(tr("pal.anim_frame_count")))
        self._anim_count = QSpinBox()
        self._anim_count.setRange(1, 9999)
        self._anim_count.valueChanged.connect(self._on_anim_cfg_changed)
        cfg.addWidget(self._anim_count)

        cfg.addWidget(QLabel(tr("pal.anim_frame_index")))
        self._anim_idx = QSpinBox()
        self._anim_idx.setRange(0, 0)
        self._anim_idx.valueChanged.connect(lambda _v: self._refresh_anim_preview())
        cfg.addWidget(self._anim_idx)

        self._anim_prev = QPushButton(tr("pal.anim_prev"))
        self._anim_prev.clicked.connect(self._anim_prev_frame)
        cfg.addWidget(self._anim_prev)

        self._anim_play = QPushButton(tr("pal.anim_play"))
        self._anim_play.clicked.connect(self._toggle_anim)
        cfg.addWidget(self._anim_play)

        self._anim_next = QPushButton(tr("pal.anim_next"))
        self._anim_next.clicked.connect(self._anim_next_frame)
        cfg.addWidget(self._anim_next)

        cfg.addWidget(QLabel(tr("pal.anim_delay")))
        self._anim_delay = QSpinBox()
        self._anim_delay.setRange(30, 5000)
        self._anim_delay.setSingleStep(10)
        self._anim_delay.setValue(120)
        self._anim_delay.valueChanged.connect(self._on_anim_delay_changed)
        cfg.addWidget(self._anim_delay)

        self._anim_auto = QPushButton(tr("pal.anim_auto"))
        self._anim_auto.clicked.connect(self._anim_auto_guess)
        self._anim_auto.setToolTip(tr("pal.anim_auto_tt"))
        cfg.addWidget(self._anim_auto)

        self._anim_apply_scene = QPushButton(tr("pal.anim_apply_scene"))
        self._anim_apply_scene.clicked.connect(self._request_apply_anim_to_scene)
        self._anim_apply_scene.setEnabled(False)
        self._anim_apply_scene.setToolTip(tr("pal.anim_apply_scene_tt"))
        cfg.addWidget(self._anim_apply_scene)

        cfg.addStretch()
        anim_layout.addLayout(cfg)

        self._anim_info = QLabel("")
        self._anim_info.setStyleSheet("color: gray;")
        anim_layout.addWidget(self._anim_info)

        self._anim_scroll = QScrollArea()
        self._anim_scroll.setWidgetResizable(False)
        self._anim_label = QLabel(tr("pal.no_file"))
        self._anim_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._anim_label.setMinimumSize(160, 120)
        self._anim_scroll.setWidget(self._anim_label)
        anim_layout.addWidget(self._anim_scroll)

        self._anim_group.setEnabled(False)
        left.addWidget(self._anim_group)

        left.addStretch()
        left_w = QWidget()
        left_w.setLayout(left)

        # Right: palette panel
        right = QVBoxLayout()
        right.setSpacing(6)

        self._ctx_palette_limits = ContextHelpBox(
            tr("pal.ctx_limits_title"),
            tr("pal.ctx_limits_body"),
            self,
            expanded=False,
        )
        right.addWidget(self._ctx_palette_limits)

        # Scene palettes (project mode)
        self._scene_pals_group = QGroupBox(tr("pal.scene_pals_group"))
        scene_pals_l = QVBoxLayout(self._scene_pals_group)
        self._scene_pals_hint = QLabel(tr("pal.scene_pals_hint"))
        self._scene_pals_hint.setWordWrap(True)
        self._scene_pals_hint.setStyleSheet("color: gray; font-size: 11px;")
        scene_pals_l.addWidget(self._scene_pals_hint)

        self._scene_pals_scroll = QScrollArea()
        self._scene_pals_scroll.setWidgetResizable(True)
        self._scene_pals_container = QWidget()
        self._scene_pals_layout = QVBoxLayout(self._scene_pals_container)
        self._scene_pals_layout.setSpacing(4)
        self._scene_pals_layout.addStretch()
        self._scene_pals_scroll.setWidget(self._scene_pals_container)
        scene_pals_l.addWidget(self._scene_pals_scroll, 1)

        self._scene_pal_edit_title = QLabel(tr("pal.scene_pals_edit_none"))
        self._scene_pal_edit_title.setStyleSheet("font-weight: bold;")
        scene_pals_l.addWidget(self._scene_pal_edit_title)

        self._scene_pal_rows: list[tuple[QPushButton, QLabel]] = []
        for i in range(4):
            row = QHBoxLayout()
            btn = QPushButton("")
            btn.setFixedSize(SwatchButton.SWATCH_SIZE, SwatchButton.SWATCH_SIZE)
            btn.setFlat(True)
            btn.clicked.connect(lambda _checked=False, idx=i: self._edit_scene_palette_slot(idx))
            lbl = QLabel("")
            lbl.setStyleSheet("font-family: monospace;")
            row.addWidget(btn)
            row.addWidget(lbl)
            row.addStretch()
            w = QWidget()
            w.setLayout(row)
            scene_pals_l.addWidget(w)
            self._scene_pal_rows.append((btn, lbl))

        self._scene_pal_apply = QPushButton(tr("pal.scene_pals_apply"))
        self._scene_pal_apply.clicked.connect(self._apply_scene_palette)
        self._scene_pal_apply.setEnabled(False)
        self._scene_pal_apply.setToolTip(tr("pal.scene_pals_apply_tt"))
        scene_pals_l.addWidget(self._scene_pal_apply)

        self._scene_pals_group.setVisible(False)

        pal_group = QGroupBox(tr("pal.palette_group"))
        pal_layout = QVBoxLayout(pal_group)

        self._pal_scroll = QScrollArea()
        self._pal_scroll.setWidgetResizable(True)
        self._pal_container = QWidget()
        self._pal_layout = QVBoxLayout(self._pal_container)
        self._pal_layout.setSpacing(4)
        self._pal_layout.addStretch()
        self._pal_scroll.setWidget(self._pal_container)
        pal_layout.addWidget(self._pal_scroll)

        self._click_hint = QLabel(tr("pal.click_to_edit"))
        self._click_hint.setWordWrap(True)
        pal_layout.addWidget(self._click_hint)

        # Vertical splitter: scene palettes (top) + main palette (bottom)
        self._pal_vsplit = QSplitter(Qt.Orientation.Vertical)
        self._pal_vsplit.addWidget(self._scene_pals_group)
        self._pal_vsplit.addWidget(pal_group)
        self._pal_vsplit.setSizes([200, 320])
        right.addWidget(self._pal_vsplit, 1)

        # Layer suggestion label
        self._layer_suggest = QLabel("")
        self._layer_suggest.setWordWrap(True)
        self._layer_suggest.setAlignment(Qt.AlignmentFlag.AlignLeft)
        right.addWidget(self._layer_suggest)

        # Split button (hidden until > 3 colors)
        self._split_btn = QPushButton("")
        self._split_btn.clicked.connect(self._open_split_dialog)
        self._split_btn.setEnabled(False)
        self._split_btn.setVisible(False)
        right.addWidget(self._split_btn)

        # Export panel
        export_group = QGroupBox(tr("export.group"))
        export_layout = QVBoxLayout(export_group)
        export_layout.setSpacing(4)

        row_png = QHBoxLayout()
        self._btn_png_sprite = QPushButton(tr("export.png_sprite"))
        self._btn_png_sprite.clicked.connect(self._export_png_sprite)
        self._btn_png_sprite.setEnabled(False)
        row_png.addWidget(self._btn_png_sprite)
        self._btn_png_palette = QPushButton(tr("export.png_palette"))
        self._btn_png_palette.clicked.connect(self._export_png_palette)
        self._btn_png_palette.setEnabled(False)
        row_png.addWidget(self._btn_png_palette)
        export_layout.addLayout(row_png)

        row_c = QHBoxLayout()
        self._btn_c_sprite = QPushButton(tr("export.c_sprite"))
        self._btn_c_sprite.clicked.connect(self._export_c_sprite)
        self._btn_c_sprite.setEnabled(False)
        row_c.addWidget(self._btn_c_sprite)
        self._btn_c_palette = QPushButton(tr("export.c_palette"))
        self._btn_c_palette.clicked.connect(self._export_c_palette)
        self._btn_c_palette.setEnabled(False)
        row_c.addWidget(self._btn_c_palette)
        export_layout.addLayout(row_c)

        self._copy_btn = QPushButton(tr("pal.copy_fixed_pal"))
        self._copy_btn.clicked.connect(self._copy_fixed_palette)
        self._copy_btn.setEnabled(False)
        export_layout.addWidget(self._copy_btn)

        self._remap_btn = QPushButton(tr("remap.btn"))
        self._remap_btn.clicked.connect(self._open_remap_wizard)
        self._remap_btn.setEnabled(False)
        export_layout.addWidget(self._remap_btn)

        self._reduce_btn = QPushButton(tr("reduce.btn"))
        self._reduce_btn.clicked.connect(self._open_reduce_dialog)
        self._reduce_btn.setEnabled(False)
        export_layout.addWidget(self._reduce_btn)

        right.addWidget(export_group)
        right.addStretch()
        right_w = QWidget()
        right_w.setLayout(right)

        # Horizontal splitter: previews (left) | palette panel (right)
        self._main_hsplit = QSplitter(Qt.Orientation.Horizontal)
        self._main_hsplit.addWidget(left_w)
        self._main_hsplit.addWidget(right_w)
        self._main_hsplit.setSizes([600, 320])
        root.addWidget(self._main_hsplit, 1)

    # ------------------------------------------------------------------
    # Splitter persistence
    # ------------------------------------------------------------------

    def _save_splitter_sizes(self) -> None:
        s = QSettings("NGPCraft", "Engine")
        if self._scene_pals_group.isVisible():
            s.setValue("pal/vsplit_sizes", self._pal_vsplit.sizes())
        s.setValue("pal/hsplit_sizes", self._main_hsplit.sizes())

    def _restore_splitter_sizes(self) -> None:
        s = QSettings("NGPCraft", "Engine")
        raw = s.value("pal/hsplit_sizes", None)
        if raw:
            try:
                self._main_hsplit.setSizes([int(x) for x in raw])
            except Exception:
                pass

    def _restore_vsplit_sizes(self) -> None:
        """Restore (or set default) vsplit after scene_pals_group becomes visible."""
        s = QSettings("NGPCraft", "Engine")
        raw = s.value("pal/vsplit_sizes", None)
        try:
            sizes = [int(x) for x in raw] if raw else [250, 400]
            if len(sizes) == 2 and sum(sizes) > 0:
                self._pal_vsplit.setSizes(sizes)
            else:
                self._pal_vsplit.setSizes([250, 400])
        except Exception:
            self._pal_vsplit.setSizes([250, 400])

    # ------------------------------------------------------------------
    # Scene thumbnail rail
    # ------------------------------------------------------------------

    def set_scene(self, scene: dict | None, base_dir: Path | None) -> None:
        """Attach the currently selected scene so the tab can expose scene helpers.""" 
        self._scene_context = scene 
        self._scene_base_dir = base_dir 
        self._refresh_rail() 
        self._refresh_scene_palettes()
        self._update_anim_apply_scene_state()

    def _sprite_palette_words(self, spr: dict) -> list[int] | None:
        """
        Retourne les 4 palette-words d'un sprite :
        - Si fixed_palette est défini, parse directement.
        - Sinon, charge le PNG et extrait les 3 premières couleurs opaques.
        """
        fp = str(spr.get("fixed_palette") or "").strip()
        if fp:
            return _parse_fixed_palette_words(fp)
        # Charger depuis le PNG
        rel = str(spr.get("file") or "").strip()
        if not rel:
            return None
        base_dir = self._scene_base_dir
        p = Path(rel)
        if base_dir and not p.is_absolute():
            p = base_dir / p
        if not p.exists():
            return None
        try:
            img = quantize_image(Image.open(p).convert("RGBA"))
            colors = palette_from_image(img)  # list of (r,g,b) opaque, max 3
            words = [0x0000]  # slot 0 = transparent
            for c in colors[:3]:
                words.append(to_word_sprite(*c))
            while len(words) < 4:
                words.append(0x0000)
            return words[:4]
        except Exception:
            return None

    def _refresh_scene_palettes(self) -> None:
        # Clear list
        while self._scene_pals_layout.count():
            item = self._scene_pals_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()
        self._scene_pals_layout.addStretch()

        self._scene_pal_groups = {}
        self._scene_pal_selected = None
        self._scene_pal_old_words = None
        self._scene_pal_new_words = None
        self._scene_pal_edit_title.setText(tr("pal.scene_pals_edit_none"))
        self._scene_pal_apply.setEnabled(False)
        self._update_scene_palette_editor_ui()

        scene = self._scene_context
        base_dir = self._scene_base_dir
        if not scene or not base_dir:
            self._scene_pals_group.setVisible(False)
            return

        groups: dict[str, list[dict]] = {}
        for spr in scene.get("sprites", []) or []:
            words = self._sprite_palette_words(spr)
            if words is None:
                continue
            key = _fixed_palette_key(words)
            groups.setdefault(key, []).append(spr)

        # Only show groups with ≥ 2 sprites (shared palettes are the point of this panel)
        # — single-sprite palettes are still useful to edit, keep them too
        self._scene_pal_groups = groups
        if not groups:
            self._scene_pals_group.setVisible(False)
            return

        self._scene_pals_group.setVisible(True)
        self._restore_vsplit_sizes()
        for key, sprites in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            words = _parse_fixed_palette_words(key) or [0, 0, 0, 0]
            btn = QToolButton()
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            btn.setIcon(_palette_icon_from_words(words))
            btn.setIconSize(QSize(72, 18))
            btn.setText(tr("pal.scene_pals_entry", n=len(sprites)))
            btn.setToolTip(key + "\n" + "\n".join(str(s.get("name") or Path(s.get("file", "")).stem) for s in sprites[:10]))
            btn.clicked.connect(lambda _checked=False, k=key: self._select_scene_palette(k))
            self._scene_pals_layout.insertWidget(self._scene_pals_layout.count() - 1, btn)

    def _select_scene_palette(self, key: str) -> None:
        words = _parse_fixed_palette_words(key)
        if words is None:
            return
        self._scene_pal_selected = key
        self._scene_pal_old_words = list(words)
        self._scene_pal_new_words = list(words)
        sprites = self._scene_pal_groups.get(key, [])
        self._scene_pal_edit_title.setText(tr("pal.scene_pals_edit_title", n=len(sprites)))
        self._update_scene_palette_editor_ui()

    def _update_scene_palette_editor_ui(self) -> None:
        words = self._scene_pal_new_words
        for i, (btn, lbl) in enumerate(self._scene_pal_rows):
            if words is None:
                btn.setEnabled(False)
                btn.setStyleSheet("background-color: transparent; border: 1px solid gray;")
                lbl.setText("")
                continue

            word = int(words[i]) if i < len(words) else 0
            if i == 0:
                btn.setEnabled(False)
                btn.setStyleSheet("background-color: transparent; border: 1px solid gray;")
            else:
                btn.setEnabled(True)
                if word == 0:
                    btn.setStyleSheet("background-color: transparent; border: 1px solid gray;")
                else:
                    r, g, b = from_word(word)
                    btn.setStyleSheet(f"background-color: rgb({r},{g},{b}); border: 1px solid #333;")
            lbl.setText(f"0x{word:04X}")

        changed = bool(
            self._scene_pal_old_words is not None
            and self._scene_pal_new_words is not None
            and self._scene_pal_old_words[:4] != self._scene_pal_new_words[:4]
        )
        sprites = self._scene_pal_groups.get(self._scene_pal_selected or "", [])
        self._scene_pal_apply.setText(tr("pal.scene_pals_apply_n", n=len(sprites)))
        self._scene_pal_apply.setEnabled(changed and len(sprites) > 0)

    def _edit_scene_palette_slot(self, idx: int) -> None:
        if self._scene_pal_new_words is None or idx <= 0 or idx >= 4:
            return
        cur_w = int(self._scene_pal_new_words[idx])
        r, g, b = from_word(cur_w) if cur_w else (0, 0, 0)
        initial = QColor(r, g, b)
        c = QColorDialog.getColor(initial, self, tr("pal.scene_pals_pick"))
        if not c.isValid():
            return
        rs, gs, bs = snap(int(c.red()), int(c.green()), int(c.blue()))
        word = to_word_sprite(rs, gs, bs)
        self._scene_pal_new_words[idx] = int(word)
        self._update_scene_palette_editor_ui()

    def _apply_scene_palette(self) -> None:
        if not self._scene_pal_selected or self._scene_pal_old_words is None or self._scene_pal_new_words is None:
            return
        scene = self._scene_context
        base_dir = self._scene_base_dir
        if not scene or not base_dir:
            return
        sprites = self._scene_pal_groups.get(self._scene_pal_selected, [])
        if not sprites:
            return
        if QMessageBox.question(
            self,
            tr("pal.scene_pals_apply_title"),
            tr("pal.scene_pals_apply_msg", n=len(sprites)),
        ) != QMessageBox.StandardButton.Yes:
            return

        # Build RGB mapping (only from non-zero visible slots).
        mapping: dict[tuple[int, int, int], tuple[int, int, int]] = {}
        for i in (1, 2, 3):
            ow = int(self._scene_pal_old_words[i])
            nw = int(self._scene_pal_new_words[i])
            if ow == 0 or ow == nw:
                continue
            o_rgb = from_word(ow)
            n_rgb = from_word(nw) if nw != 0 else from_word(ow)
            if o_rgb not in mapping:
                mapping[o_rgb] = n_rgb

        ok = 0
        fail = 0
        for spr in sprites:
            rel = str(spr.get("file") or "").strip()
            if not rel:
                fail += 1
                continue
            p = Path(rel)
            if not p.is_absolute():
                p = base_dir / p
            if not p.exists():
                fail += 1
                continue
            try:
                img = quantize_image(Image.open(p).convert("RGBA"))
                px = img.load()
                w, h = img.size
                for y in range(h):
                    for x in range(w):
                        r, g, b, a = px[x, y]
                        if a < 128:
                            continue
                        key = (r, g, b)
                        if key in mapping:
                            nr, ng, nb = mapping[key]
                            px[x, y] = (nr, ng, nb, a)
                img.save(str(p))
                ok += 1
            except Exception:
                fail += 1

        new_key = _fixed_palette_key(self._scene_pal_new_words)
        payload = {"old": self._scene_pal_selected, "new": new_key}
        self.apply_scene_palette_requested.emit(payload)

        # If current sprite is affected, reload it (also refreshes previews/palette).
        if self._data is not None:
            try:
                cur = self._data.path.resolve()
            except Exception:
                cur = self._data.path
            for spr in sprites:
                rel = str(spr.get("file") or "").strip()
                if not rel:
                    continue
                sp = Path(rel)
                if not sp.is_absolute():
                    sp = base_dir / sp
                try:
                    if sp.resolve() == cur:
                        self._load(self._data.path)
                        break
                except Exception:
                    if str(sp) == str(self._data.path):
                        self._load(self._data.path)
                        break

        self.show_status(tr("pal.scene_pals_applied", ok=ok, fail=fail))
        self._refresh_scene_palettes()

    def _refresh_rail(self) -> None:
        # Clear old thumbnails
        while self._rail_layout.count():
            item = self._rail_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        scene = self._scene_context
        base_dir = self._scene_base_dir

        if not scene or not base_dir:
            self._rail_scroll.setVisible(False)
            return

        self._rail_scroll.setVisible(True)

        # Label showing scene name
        lbl = QLabel(scene.get("label", ""))
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("font-weight: bold; font-size: 9px;")
        lbl.setWordWrap(True)
        self._rail_layout.addWidget(lbl)

        for spr in scene.get("sprites", []): 
            self._add_rail_thumb( 
                base_dir / spr.get("file", ""), 
                spr.get("name", ""), 
                shared=bool(spr.get("fixed_palette")), 
                sprite_cfg=spr,
            ) 
        for tm in scene.get("tilemaps", []): 
            self._add_rail_thumb(base_dir / tm.get("file", ""), tm.get("name", "")) 

        self._rail_layout.addStretch()

    def _add_rail_thumb(
        self,
        path: Path,
        name: str,
        shared: bool = False,
        sprite_cfg: dict | None = None,
    ) -> None:
        btn = QToolButton() 
        btn.setFixedSize(80, 80) 
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon) 
        label = (name or path.stem)[:10] 
        btn.setText(label + (" ↔" if shared else "")) 
        tip = str(path)
        if shared:
            tip += "\n↔ palette partagée (--fixed-palette)"
        btn.setToolTip(tip)
        if shared:
            btn.setStyleSheet("border: 2px solid #569ed6; border-radius: 3px;")
        if path.exists(): 
            try: 
                img = Image.open(path).convert("RGBA") 
                img.thumbnail((52, 52), Image.NEAREST) 
                pm = _pil_to_qpixmap(img) 
                btn.setIcon(QIcon(pm)) 
                btn.setIconSize(QSize(52, 52)) 
                if sprite_cfg:
                    fw = int(sprite_cfg.get("frame_w", 8))
                    fh = int(sprite_cfg.get("frame_h", 8))
                    fc = int(sprite_cfg.get("frame_count", 1))
                    btn.clicked.connect(lambda _checked, p=path, a=fw, b=fh, c=fc: self.open_sprite(p, a, b, c))
                else:
                    btn.clicked.connect(lambda _checked, p=path: self._load(p))
            except Exception: 
                btn.setEnabled(False) 
        else: 
            btn.setStyleSheet("color: gray;") 
            btn.setEnabled(False) 
        self._rail_layout.addWidget(btn) 

    # ------------------------------------------------------------------
    # File open / drag-drop
    # ------------------------------------------------------------------

    def _open_file(self) -> None: 
        start = QSettings("NGPCraft", "Engine").value("pal/last_dir", "", str)
        path, _ = QFileDialog.getOpenFileName( 
            self, tr("pal.open_file"), start, tr("pal.file_filter") 
        ) 
        if path: 
            self._load(Path(path)) 

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        """Accept dropped image files so other tabs/browsers can open sprites here."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        """Open the first dropped image file in the palette editor."""
        for url in event.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.suffix.lower() in (".png", ".bmp", ".gif"):
                self._load(p)
                break

    def _load(self, path: Path) -> None: 
        prev_cfg: tuple[int, int, int, int, int] | None = None
        if self._data is not None and self._data.path == path:
            try:
                prev_cfg = (
                    int(self._anim_fw.value()),
                    int(self._anim_fh.value()),
                    int(self._anim_count.value()),
                    int(self._anim_idx.value()),
                    int(self._anim_delay.value()),
                )
            except Exception:
                prev_cfg = None

        try: 
            self._data = load_sprite(path) 
        except Exception as exc: 
            QMessageBox.warning(self, "Error", str(exc)) 
            return 
        self._dirty = False
        QSettings("NGPCraft", "Engine").setValue("pal/last_dir", str(path.parent))
        self._file_label.setText(str(path)) 
        self._refresh_previews() 
        self._refresh_palette_panel() 
        for btn in (self._btn_png_sprite, self._btn_png_palette,
                    self._btn_c_sprite, self._btn_c_palette,
                    self._copy_btn, self._remap_btn, self._reduce_btn):
            btn.setEnabled(True)
        self._install_watcher()
        self._setup_anim_defaults(prev_cfg)
        self._update_anim_apply_scene_state()

    def open_path(self, path: Path) -> None:
        """Public helper used by other tabs (Asset Browser, scene rail)."""
        self._load(path)

    def open_sprite(self, path: Path, frame_w: int, frame_h: int, frame_count: int) -> None:
        """Open a spritesheet and prefill the animation preview config."""
        self._load(path)
        if self._data is None:
            return
        self._set_anim_playing(False)
        img_w, img_h = self._data.hw.size

        self._anim_fw.blockSignals(True)
        self._anim_fh.blockSignals(True)
        self._anim_count.blockSignals(True)
        self._anim_idx.blockSignals(True)
        try:
            self._anim_fw.setValue(max(1, min(int(frame_w), img_w)))
            self._anim_fh.setValue(max(1, min(int(frame_h), img_h)))
            self._anim_count.setValue(max(1, int(frame_count)))
            self._anim_idx.setValue(0)
        finally:
            self._anim_fw.blockSignals(False)
            self._anim_fh.blockSignals(False)
            self._anim_count.blockSignals(False)
            self._anim_idx.blockSignals(False)
        self._on_anim_cfg_changed()

    def show_status(self, text: str) -> None:
        """Small helper for cross-tab actions to display a message."""
        try:
            self._tile_status.setText(text)
        except Exception:
            pass

    def _install_watcher(self) -> None:
        self._watcher.removePaths(self._watcher.files())
        if self._data is None:
            return
        p = self._data.path
        if p.exists():
            self._watcher.addPath(str(p))

    def _on_file_changed(self, _path: str) -> None:
        if self._data is None or not self._auto_reload.isChecked():
            return
        # Debounce and handle atomic-save patterns (delete + rename).
        self._reload_timer.start(250)

    def _reload_from_disk(self) -> None:
        if self._data is None:
            return
        p = self._data.path
        if not p.exists():
            # File may be mid-save; retry shortly.
            self._reload_timer.start(350)
            return
        if self._dirty:
            if QMessageBox.question(
                self,
                tr("pal.reload_title"),
                tr("pal.reload_msg", path=p.name),
            ) != QMessageBox.StandardButton.Yes:
                self._install_watcher()
                return
        self._load(p)

    # ------------------------------------------------------------------
    # Zoom / overlay
    # ------------------------------------------------------------------

    def _set_zoom(self, factor: int) -> None:
        self._zoom = factor
        for f in (1, 2, 4, 8):
            btn = getattr(self, f"_zoom_btn_{f}", None)
            if btn:
                btn.setChecked(f == factor)
        self._refresh_previews()

    def _toggle_overlay(self, checked: bool) -> None:
        self._show_overlay = checked
        self._refresh_previews()

    def _toggle_mono(self, checked: bool) -> None:
        self._mono_mode = checked
        self._refresh_previews()

    # ------------------------------------------------------------------
    # Preview refresh
    # ------------------------------------------------------------------

    def _refresh_previews(self) -> None: 
        if self._data is None: 
            return

        # Composite over checker to show transparency
        orig_comp = composite_on_checker(self._data.original)
        orig_pm = _make_zoom_pixmap(orig_comp, self._zoom)
        self._orig_label.setPixmap(orig_pm)
        self._orig_label.resize(orig_pm.size())

        hw_comp = composite_on_checker(self._data.hw)
        hw_display = hw_comp.convert("L") if self._mono_mode else hw_comp
        hw_pm = _make_zoom_pixmap(hw_display, self._zoom)
        self._hw_label.setPixmap(hw_pm)
        self._hw_label.resize(hw_pm.size())

        if self._show_overlay:
            overlay_pm = _make_overlay_pixmap(self._data.hw, self._zoom)
            self._hw_label.set_overlay(overlay_pm)
        else:
            self._hw_label.set_overlay(None)

        # Tile status (relevant for tilemap mode — 3 colors max per 8×8 tile)
        counts_flat = [c for row in colors_per_tile(self._data.hw) for c in row]
        max_colors = max(counts_flat) if counts_flat else 0
        if max_colors <= 3: 
            self._tile_status.setText(tr("pal.all_tiles_ok")) 
            self._tile_status.setStyleSheet("color: green;") 
        else: 
            self._tile_status.setText(tr("pal.too_many_colors", max_c=max_colors)) 
            self._tile_status.setStyleSheet("color: darkorange;") 
        self._refresh_anim_preview()

    # ------------------------------------------------------------------
    # Animation preview
    # ------------------------------------------------------------------

    def _setup_anim_defaults(self, prev_cfg: tuple[int, int, int, int, int] | None) -> None:
        if self._data is None:
            return
        self._anim_group.setEnabled(True)
        w, h = self._data.hw.size
        # Keep current config if reloading same file.
        if prev_cfg is not None:
            fw, fh, fc, fi, delay = prev_cfg
        else:
            # If the file belongs to the active scene, reuse its sprite configuration.
            fw, fh, fc = self._guess_anim_cfg(w, h)
            if self._scene_context and self._scene_base_dir:
                try:
                    target = self._data.path.resolve()
                except Exception:
                    target = self._data.path
                for spr in self._scene_context.get("sprites", []) or []:
                    rel = spr.get("file", "")
                    if not rel:
                        continue
                    p = Path(rel)
                    if not p.is_absolute():
                        p = self._scene_base_dir / p
                    try:
                        pp = p.resolve()
                    except Exception:
                        pp = p
                    if pp == target:
                        fw = int(spr.get("frame_w", fw))
                        fh = int(spr.get("frame_h", fh))
                        fc = int(spr.get("frame_count", fc))
                        break
            fi, delay = 0, 120

        self._anim_timer.setInterval(int(delay))
        self._anim_delay.blockSignals(True)
        self._anim_delay.setValue(int(delay))
        self._anim_delay.blockSignals(False)

        self._anim_fw.blockSignals(True)
        self._anim_fh.blockSignals(True)
        self._anim_fw.setRange(1, max(1, w))
        self._anim_fh.setRange(1, max(1, h))
        self._anim_fw.setValue(max(1, min(int(fw), w)))
        self._anim_fh.setValue(max(1, min(int(fh), h)))
        self._anim_fw.blockSignals(False)
        self._anim_fh.blockSignals(False)

        self._anim_count.blockSignals(True)
        self._anim_count.setValue(max(1, int(fc)))
        self._anim_count.blockSignals(False)

        self._anim_idx.blockSignals(True)
        self._anim_idx.setValue(max(0, int(fi)))
        self._anim_idx.blockSignals(False)

        self._on_anim_cfg_changed()
        self._update_anim_apply_scene_state()

    def _guess_anim_cfg(self, w: int, h: int) -> tuple[int, int, int]:
        """
        Best-effort default guess for animation preview.

        Handles common layouts:
        - Vertical strip: frames stacked, full width
        - Horizontal strip: frames side-by-side, full height
        - Square frames: size = min(w, h) when divisible
        """
        w = max(1, int(w))
        h = max(1, int(h))

        # Prefer square frames when it clearly matches strip layout
        if h >= w * 2 and w % 8 == 0 and (h % w) == 0:
            fw = w
            fh = w
            fc = max(1, h // w)
            return fw, fh, fc
        if w >= h * 2 and h % 8 == 0 and (w % h) == 0:
            fw = h
            fh = h
            fc = max(1, w // h)
            return fw, fh, fc

        fw = w
        if fw >= 8 and (fw % 8) != 0:
            fw2 = fw - (fw % 8)
            if fw2 >= 8:
                fw = fw2

        # Try to find a tile-aligned divisor of height, preferring square frames first.
        candidates = [fw, 256, 128, 64, 32, 16, 8]
        fh = None
        for c in candidates:
            if c <= h and (h % c) == 0 and c >= 1:
                fh = int(c)
                break
        if fh is None:
            fh = 8 if h >= 8 else h
        if fh >= 8 and (fh % 8) != 0:
            fh2 = fh - (fh % 8)
            if fh2 >= 8:
                fh = fh2

        cols = max(1, w // fw) if fw > 0 else 1
        rows = max(1, h // fh) if fh > 0 else 1
        fc = max(1, cols * rows)
        return int(fw), int(fh), int(fc)

    def _find_scene_sprite_by_path(self) -> dict | None:
        if self._data is None or not self._scene_context or not self._scene_base_dir:
            return None
        try:
            target = self._data.path.resolve()
        except Exception:
            target = self._data.path
        for spr in self._scene_context.get("sprites", []) or []:
            rel = spr.get("file", "")
            if not rel:
                continue
            p = Path(rel)
            if not p.is_absolute():
                p = self._scene_base_dir / p
            try:
                pp = p.resolve()
            except Exception:
                pp = p
            if pp == target:
                return spr
        return None

    def _update_anim_apply_scene_state(self) -> None:
        try:
            self._anim_apply_scene.setEnabled(self._find_scene_sprite_by_path() is not None)
        except Exception:
            pass

    def _frame_rect(self, index: int) -> tuple[int, int, int, int] | None:
        if self._data is None:
            return None
        img_w, img_h = self._data.hw.size
        fw = int(self._anim_fw.value())
        fh = int(self._anim_fh.value())
        if fw < 1 or fh < 1:
            return None
        cols = img_w // fw
        rows = img_h // fh
        if cols <= 0 or rows <= 0:
            return None
        total = cols * rows
        if total <= 0:
            return None
        i = max(0, min(index, total - 1))
        col = i % cols
        row = i // cols
        x0 = col * fw
        y0 = row * fh
        return (x0, y0, x0 + fw, y0 + fh)

    def _on_anim_cfg_changed(self) -> None:
        if self._data is None:
            return
        img_w, img_h = self._data.hw.size
        fw = int(self._anim_fw.value())
        fh = int(self._anim_fh.value())
        valid = fw > 0 and fh > 0 and fw <= img_w and fh <= img_h
        cols = (img_w // fw) if valid else 0
        rows = (img_h // fh) if valid else 0
        total = cols * rows if valid else 0
        use = min(max(1, int(self._anim_count.value())), total if total > 0 else 1)
        if total <= 0:
            if self._anim_playing:
                self._set_anim_playing(False)
            self._anim_info.setText(tr("pal.anim_invalid"))
            self._anim_info.setStyleSheet("color: #e07030;")
            self._anim_idx.setRange(0, 0)
            self._anim_play.setEnabled(False)
            self._anim_prev.setEnabled(False)
            self._anim_next.setEnabled(False)
            return

        if int(self._anim_count.value()) != use:
            self._anim_count.blockSignals(True)
            self._anim_count.setValue(int(use))
            self._anim_count.blockSignals(False)

        warn_bits: list[str] = []
        if (fw % 8) != 0 or (fh % 8) != 0:
            warn_bits.append(tr("pal.anim_warn_8"))
        if (img_w % fw) != 0 or (img_h % fh) != 0:
            warn_bits.append(tr("pal.anim_warn_div"))
        warn = ("  ⚠ " + " · ".join(warn_bits)) if warn_bits else ""
        self._anim_info.setText(tr("pal.anim_info", cols=cols, rows=rows, total=total, use=use) + warn)
        self._anim_info.setStyleSheet("color: #e07030;" if warn_bits else "color: gray;")
        self._anim_idx.setRange(0, max(0, use - 1))
        if self._anim_idx.value() > use - 1:
            self._anim_idx.setValue(max(0, use - 1))

        can_anim = use >= 2
        self._anim_play.setEnabled(can_anim)
        self._anim_prev.setEnabled(True)
        self._anim_next.setEnabled(True)
        if not can_anim and self._anim_playing:
            self._set_anim_playing(False)
        self._refresh_anim_preview()
        self._update_anim_apply_scene_state()

    def _anim_auto_guess(self) -> None:
        if self._data is None:
            return
        self._set_anim_playing(False)
        w, h = self._data.hw.size
        fw, fh, fc = self._guess_anim_cfg(w, h)
        self._anim_fw.blockSignals(True)
        self._anim_fh.blockSignals(True)
        self._anim_count.blockSignals(True)
        self._anim_idx.blockSignals(True)
        try:
            self._anim_fw.setValue(int(fw))
            self._anim_fh.setValue(int(fh))
            self._anim_count.setValue(int(fc))
            self._anim_idx.setValue(0)
        finally:
            self._anim_fw.blockSignals(False)
            self._anim_fh.blockSignals(False)
            self._anim_count.blockSignals(False)
            self._anim_idx.blockSignals(False)
        self._on_anim_cfg_changed()

    def _refresh_anim_preview(self) -> None:
        if self._data is None:
            self._anim_label.setText(tr("pal.no_file"))
            self._anim_label.setPixmap(QPixmap())
            return
        rect = self._frame_rect(int(self._anim_idx.value()))
        if rect is None:
            self._anim_label.setText(tr("pal.anim_invalid"))
            self._anim_label.setPixmap(QPixmap())
            return
        try:
            frame = self._data.hw.crop(rect)
            comp = composite_on_checker(frame)
            anim_display = comp.convert("L") if self._mono_mode else comp
            pm = _make_zoom_pixmap(anim_display, self._zoom)
            self._anim_label.setPixmap(pm)
            self._anim_label.resize(pm.size())
            self._anim_label.setText("")
        except Exception:
            self._anim_label.setText(tr("pal.anim_invalid"))
            self._anim_label.setPixmap(QPixmap())

    def _set_anim_playing(self, playing: bool) -> None:
        self._anim_playing = playing
        if playing:
            self._anim_play.setText(tr("pal.anim_pause"))
            self._anim_timer.start()
        else:
            self._anim_play.setText(tr("pal.anim_play"))
            self._anim_timer.stop()

    def _toggle_anim(self) -> None:
        if self._data is None:
            return
        self._set_anim_playing(not self._anim_playing)

    def _on_anim_tick(self) -> None:
        if self._data is None:
            self._set_anim_playing(False)
            return
        max_i = int(self._anim_idx.maximum())
        if max_i <= 0:
            self._set_anim_playing(False)
            return
        cur = int(self._anim_idx.value())
        self._anim_idx.setValue(0 if cur >= max_i else cur + 1)

    def _anim_prev_frame(self) -> None:
        if self._data is None:
            return
        max_i = int(self._anim_idx.maximum())
        cur = int(self._anim_idx.value())
        self._anim_idx.setValue(max_i if cur <= 0 else cur - 1)

    def _anim_next_frame(self) -> None:
        if self._data is None:
            return
        max_i = int(self._anim_idx.maximum())
        cur = int(self._anim_idx.value())
        self._anim_idx.setValue(0 if cur >= max_i else cur + 1)

    def _on_anim_delay_changed(self, v: int) -> None:
        self._anim_timer.setInterval(int(v))
        if self._anim_playing:
            self._anim_timer.start()

    def _request_apply_anim_to_scene(self) -> None:
        spr = self._find_scene_sprite_by_path()
        if spr is None or self._data is None:
            return
        payload = {
            "path": self._data.path,
            "frame_w": int(self._anim_fw.value()),
            "frame_h": int(self._anim_fh.value()),
            "frame_count": int(self._anim_count.value()),
        }
        self.apply_anim_to_scene_requested.emit(payload)

    # ------------------------------------------------------------------
    # Palette panel
    # ------------------------------------------------------------------

    def _refresh_palette_panel(self) -> None:
        # Remove existing swatches
        while self._pal_layout.count() > 1:
            item = self._pal_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._swatches = []
        self._swatch_labels = []

        if self._data is None:
            self._layer_suggest.setText("")
            self._split_btn.setVisible(False)
            return

        palette = self._data.palette
        self._refresh_layer_suggestion(len(palette))

        # Insert swatches (0 = transparent placeholder)
        for i, color in enumerate(palette):
            row = QHBoxLayout()

            swatch = SwatchButton(i, color)
            swatch.clicked.connect(lambda checked, idx=i: self._edit_color(idx))
            swatch.setToolTip(tr("pal.color_index", i=i))
            self._swatches.append(swatch)
            row.addWidget(swatch)

            word = to_word(*color)
            word_label = QLabel(tr("pal.word_label", word=word))
            word_label.setStyleSheet("font-family: monospace;")
            self._swatch_labels.append(word_label)
            row.addWidget(word_label)
            row.addStretch()

            container = QWidget()
            container.setLayout(row)
            self._pal_layout.insertWidget(self._pal_layout.count() - 1, container)

    # ------------------------------------------------------------------
    # Layer suggestion
    # ------------------------------------------------------------------

    def _refresh_layer_suggestion(self, n_colors: int) -> None:
        """Update the layer suggestion label and split button visibility."""
        n = n_colors
        n_layers = layers_needed(n)

        if n == 0:
            self._layer_suggest.setText("")
            self._layer_suggest.setStyleSheet("")
            self._split_btn.setVisible(False)
            return

        if n <= 3:
            text = tr("pal.suggest_ok", n=n)
            self._layer_suggest.setStyleSheet("color: green;")
            self._split_btn.setVisible(False)
        elif n_layers == 2:
            r = n - 3  # colors in second layer
            text = tr("pal.suggest_2", n=n, r=r)
            self._layer_suggest.setStyleSheet("color: darkorange;")
            self._split_btn.setText(tr("pal.split_btn", n=n_layers))
            self._split_btn.setEnabled(True)
            self._split_btn.setVisible(True)
        elif n_layers == 3:
            r = n - 6  # colors in third layer
            text = tr("pal.suggest_3", n=n, r=r)
            self._layer_suggest.setStyleSheet("color: darkorange;")
            self._split_btn.setText(tr("pal.split_btn", n=n_layers))
            self._split_btn.setEnabled(True)
            self._split_btn.setVisible(True)
        else:
            text = tr("pal.suggest_too_many", n=n, layers=n_layers)
            self._layer_suggest.setStyleSheet("color: red;")
            self._split_btn.setText(tr("pal.split_btn", n=n_layers))
            self._split_btn.setEnabled(True)
            self._split_btn.setVisible(True)

        self._layer_suggest.setText(text)

    # ------------------------------------------------------------------
    # Layer split dialog
    # ------------------------------------------------------------------

    def _open_split_dialog(self) -> None:
        if self._data is None:
            return
        from ui.layer_split_dialog import LayerSplitDialog
        result = split_layers(self._data.hw)
        dlg = LayerSplitDialog(result, source_path=self._data.path, parent=self)
        dlg.exec()

    # ------------------------------------------------------------------
    # Color editing
    # ------------------------------------------------------------------

    def _edit_color(self, index: int) -> None: 
        if self._data is None: 
            return 
        old_color = self._data.palette[index] 
        initial = QColor(*old_color)
        chosen = QColorDialog.getColor(initial, self, tr("pal.color_index", i=index))
        if not chosen.isValid():
            return

        snapped = snap(chosen.red(), chosen.green(), chosen.blue())
        new_palette = list(self._data.palette)
        new_palette[index] = snapped 
 
        self._data = remap_palette(self._data, new_palette) 
        self._dirty = True
        self._refresh_previews() 
        self._refresh_palette_panel() 

    # ------------------------------------------------------------------
    # Export methods
    # ------------------------------------------------------------------

    def _export_png_sprite(self) -> None:
        """Save the RGB444-quantized sprite PNG."""
        if self._data is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("export.png_sprite"), str(self._data.path), "PNG (*.png)"
        )
        if not path:
            return
        try:
            self._data.hw.save(path)
            self._tile_status.setText(tr("export.success", path=path))
        except Exception as exc:
            QMessageBox.warning(self, "Export", tr("export.error", err=str(exc)))

    def _export_png_palette(self) -> None:
        """Save a 16px-per-swatch color strip PNG of the palette."""
        if self._data is None:
            return
        stem = self._data.path.stem
        default = str(self._data.path.with_name(stem + "_pal.png"))
        path, _ = QFileDialog.getSaveFileName(
            self, tr("export.png_palette"), default, "PNG (*.png)"
        )
        if not path:
            return
        n = len(self._data.palette)
        sw = 16
        img = Image.new("RGBA", (n * sw, sw))
        for i, color in enumerate(self._data.palette):
            x0 = i * sw
            if i == 0:
                for py in range(sw):
                    for px_ in range(sw):
                        c = 200 if (px_ // 4 + py // 4) % 2 == 0 else 128
                        img.putpixel((x0 + px_, py), (c, c, c, 255))
            else:
                r, g, b = color
                for py in range(sw):
                    for px_ in range(sw):
                        img.putpixel((x0 + px_, py), (r, g, b, 255))
        try:
            img.save(path)
            self._tile_status.setText(tr("export.success", path=path))
        except Exception as exc:
            QMessageBox.warning(self, "Export", tr("export.error", err=str(exc)))

    def _find_export_script(self) -> Path | None:
        """Return path to ngpc_sprite_export.py, trying QSettings cache then common locations."""
        repo_root = Path(__file__).resolve().parents[2]
        return find_script(
            "export_script_path",
            default_candidates(repo_root, "ngpc_sprite_export.py"),
        )

    def _export_c_sprite(self) -> None:
        """Call ngpc_sprite_export.py to generate name_mspr.c / name_mspr.h."""
        if self._data is None:
            return
        script = self._find_export_script()
        if script is None:
            start = script_dialog_start_dir("export_script_path")
            p, _ = QFileDialog.getOpenFileName(
                self, tr("export.find_script"), start, "Python (*.py)"
            )
            if not p:
                return
            script = Path(p)
            remember_script_path("export_script_path", script)

        img_w, img_h = self._data.hw.size
        fw = int(self._anim_fw.value())
        fh = int(self._anim_fh.value())
        fc = int(self._anim_count.value())
        if fw <= 0 or fh <= 0 or (fw % 8) or (fh % 8) or (img_w % fw) or (img_h % fh):
            QMessageBox.warning(self, ".c export", tr("pal.anim_invalid"))
            return
        total_frames = (img_w // fw) * (img_h // fh)
        if fc < 1 or fc > total_frames:
            QMessageBox.warning(self, ".c export", tr("pal.anim_invalid"))
            return

        name = self._data.path.stem
        out_dir = self._data.path.parent

        with tempfile.TemporaryDirectory(prefix="ngpc_pngmgr_") as tmp_dir:
            tmp_png = Path(tmp_dir) / (name + "__ngpctmp.png")
            try:
                self._data.hw.save(str(tmp_png))
            except Exception as exc:
                QMessageBox.warning(self, "Export", tr("export.error", err=str(exc)))
                return

            try:
                from core.sprite_export_cli import run_sprite_export
                res, out_c = run_sprite_export(
                    script=script,
                    input_png=tmp_png,
                    out_dir=out_dir,
                    name=name,
                    frame_w=fw,
                    frame_h=fh,
                    frame_count=fc,
                    output_c=(out_dir / f"{name}_mspr.c"),
                    header=True,
                    timeout_s=30,
                )
                if res.returncode == 0:
                    self._tile_status.setText(tr("export.success", path=str(out_c)))
                else:
                    err = (res.stderr or res.stdout).strip()
                    QMessageBox.warning(
                        self, ".c export",
                        tr("export.c_sprite_fail", code=res.returncode) + f"\n{err}"
                    )
            except subprocess.TimeoutExpired:
                QMessageBox.warning(self, ".c export", "Timeout (>30s)")
            except Exception as exc:
                QMessageBox.warning(self, ".c export", str(exc))

    def _export_c_palette(self) -> None:
        """Generate a C array  const u16 name_pal[] = { ... };  and save it."""
        if self._data is None:
            return
        name = self._data.path.stem
        default = str(self._data.path.with_name(name + "_pal.c"))
        path, _ = QFileDialog.getSaveFileName(
            self, tr("export.c_palette"), default, "C source (*.c)"
        )
        if not path:
            return

        n = len(self._data.palette)
        lines = [f"/* {name} palette — RGB444 (NGPC) */\n",
                 f"const u16 {name}_pal[{n}] = {{\n"]
        for i, color in enumerate(self._data.palette):
            word = to_word(*color)
            comment = "/* transparent */" if i == 0 else f"/* #{color[0]:02X}{color[1]:02X}{color[2]:02X} */"
            sep = "," if i < n - 1 else " "
            lines.append(f"    0x{word:04X}u{sep}  {comment}\n")
        lines.append("};\n")

        try:
            Path(path).write_text("".join(lines), encoding="utf-8")
            self._tile_status.setText(tr("export.c_palette_saved", path=path))
        except Exception as exc:
            QMessageBox.warning(self, "Export", tr("export.error", err=str(exc)))

    # ------------------------------------------------------------------
    # Copy --fixed-palette
    # ------------------------------------------------------------------

    def _copy_fixed_palette(self) -> None:
        if self._data is None:
            return
        arg = palette_to_fixed_arg(self._data.palette)
        QApplication.clipboard().setText(arg)
        self._tile_status.setText(tr("pal.copied") + f"  {arg}")

    # ------------------------------------------------------------------
    # Remap wizard
    # ------------------------------------------------------------------

    def _open_remap_wizard(self) -> None:
        if self._data is None:
            return
        from ui.remap_wizard import RemapWizardDialog
        dlg = RemapWizardDialog(self._data, self)
        if dlg.exec() == RemapWizardDialog.DialogCode.Accepted and dlg.result_data is not None:
            self._data = dlg.result_data
            self._dirty = True
            self._refresh_previews()
            self._refresh_palette_panel()

    # ------------------------------------------------------------------
    # Guided color reduction (G)
    # ------------------------------------------------------------------

    def _open_reduce_dialog(self) -> None:
        if self._data is None:
            return
        from ui.reduce_colors_dialog import ReduceColorsDialog
        dlg = ReduceColorsDialog(self._data, self)
        if dlg.exec() == ReduceColorsDialog.DialogCode.Accepted and dlg.result_data is not None:
            self._data = dlg.result_data
            self._dirty = True
            self._refresh_previews()
            self._refresh_palette_panel()
