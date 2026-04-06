"""
ui/remap_wizard.py - Color-by-color remapping wizard (Phase 3b).

Walks the user through mapping each source color to a target color so the
two sprites can share the same palette slot (--fixed-palette).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup, QDialog, QDialogButtonBox, QFileDialog,
    QGroupBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QRadioButton, QScrollArea,
    QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from core.sprite_loader import SpriteData, load_sprite, remap_palette
from i18n.lang import tr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pil_to_qpixmap(img: Image.Image) -> QPixmap:
    rgba = img.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimg = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


def _make_swatch(r: int, g: int, b: int, w: int = 24, h: int = 24) -> QPixmap:
    img = Image.new("RGB", (w, h), (r, g, b))
    return _pil_to_qpixmap(img)


def _preview_pixmap(img: Image.Image, max_size: int = 160) -> QPixmap:
    """Scale image to max_size×max_size (nearest-neighbor, integer factor)."""
    w, h = img.size
    factor = max(1, min(max_size // w, max_size // h))
    scaled = img.resize((w * factor, h * factor), Image.NEAREST)
    return _pil_to_qpixmap(scaled)


def _highlight_color(img: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    """Return a copy of img where all pixels NOT matching `color` are dimmed to 30%."""
    rgba = img.convert("RGBA").copy()
    px = rgba.load()
    w, h = rgba.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 128:
                continue
            if (r, g, b) != color:
                px[x, y] = (r // 4, g // 4, b // 4, a)
    return rgba


# ---------------------------------------------------------------------------
# RemapWizardDialog
# ---------------------------------------------------------------------------

class RemapWizardDialog(QDialog):
    """
    Step-by-step palette remap wizard.

    For each non-transparent color in the source sprite, the user picks the
    corresponding color from the target sprite (or skips it).
    The result is a remapped SpriteData accessible via .result_data.
    """

    def __init__(self, source_data: SpriteData, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("remap.title"))
        self.setMinimumSize(680, 460)
        self._source = source_data
        self._target: SpriteData | None = None
        # mapping[source_color_idx] = target_color_idx | None  (None = keep)
        self._mapping: dict[int, int | None] = {}
        self._step = 0  # index into source.palette
        self.result_data: SpriteData | None = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # Top: target picker
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("remap.target_label")))
        self._target_lbl = QLabel("—")
        self._target_lbl.setStyleSheet("color: gray; font-style: italic;")
        self._target_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        top.addWidget(self._target_lbl, 1)
        btn_pick = QPushButton(tr("remap.pick_target"))
        btn_pick.clicked.connect(self._pick_target)
        top.addWidget(btn_pick)
        root.addLayout(top)

        # Stack: step page | preview page
        self._stack = QStackedWidget()

        self._stack.addWidget(self._make_step_page())
        self._stack.addWidget(self._make_preview_page())
        root.addWidget(self._stack, 1)

        # Bottom buttons
        bot = QHBoxLayout()
        self._step_lbl = QLabel("")
        bot.addWidget(self._step_lbl, 1)
        self._btn_skip = QPushButton(tr("remap.skip"))
        self._btn_skip.clicked.connect(self._skip)
        bot.addWidget(self._btn_skip)
        self._btn_prev = QPushButton(tr("remap.prev"))
        self._btn_prev.clicked.connect(self._go_prev)
        self._btn_prev.setEnabled(False)
        bot.addWidget(self._btn_prev)
        self._btn_next = QPushButton(tr("remap.next"))
        self._btn_next.clicked.connect(self._go_next)
        self._btn_next.setEnabled(False)
        bot.addWidget(self._btn_next)
        btn_cancel = QPushButton(tr("remap.cancel"))
        btn_cancel.clicked.connect(self.reject)
        bot.addWidget(btn_cancel)
        root.addLayout(bot)

    def _make_step_page(self) -> QWidget:
        page = QWidget()
        h = QHBoxLayout(page)

        # Left: source image + source color swatch
        left_g = QGroupBox(tr("remap.source_label"))
        left_l = QVBoxLayout(left_g)
        self._src_img_lbl = QLabel()
        self._src_img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._src_img_lbl.setFixedSize(180, 160)
        left_l.addWidget(self._src_img_lbl)
        self._src_color_lbl = QLabel()
        self._src_color_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_l.addWidget(self._src_color_lbl)
        self._src_swatch = QLabel()
        self._src_swatch.setFixedSize(40, 24)
        self._src_swatch.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_l.addWidget(self._src_swatch, alignment=Qt.AlignmentFlag.AlignHCenter)
        left_l.addStretch()
        h.addWidget(left_g)

        # Right: target color radio buttons
        right_g = QGroupBox(tr("remap.target_colors"))
        right_l = QVBoxLayout(right_g)
        self._radio_scroll = QScrollArea()
        self._radio_scroll.setWidgetResizable(True)
        self._radio_container = QWidget()
        self._radio_layout = QVBoxLayout(self._radio_container)
        self._radio_layout.setSpacing(4)
        self._radio_scroll.setWidget(self._radio_container)
        right_l.addWidget(self._radio_scroll)
        h.addWidget(right_g, 1)

        return page

    def _make_preview_page(self) -> QWidget:
        page = QWidget()
        h = QHBoxLayout(page)

        # Left: remapped source
        left_g = QGroupBox(tr("remap.source_remapped"))
        left_l = QVBoxLayout(left_g)
        self._result_lbl = QLabel()
        self._result_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._result_lbl.setFixedSize(200, 200)
        left_l.addWidget(self._result_lbl)
        btn_save = QPushButton(tr("remap.apply_save"))
        btn_save.clicked.connect(self._save_result)
        left_l.addWidget(btn_save)
        left_l.addStretch()
        h.addWidget(left_g)

        # Right: target reference
        right_g = QGroupBox(tr("remap.target_ref"))
        right_l = QVBoxLayout(right_g)
        self._target_ref_lbl = QLabel()
        self._target_ref_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._target_ref_lbl.setFixedSize(200, 200)
        right_l.addWidget(self._target_ref_lbl)
        right_l.addStretch()
        h.addWidget(right_g)

        return page

    # ------------------------------------------------------------------
    # Target selection
    # ------------------------------------------------------------------

    def _pick_target(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("remap.pick_target"), "",
            "PNG (*.png);;All images (*.png *.bmp *.gif)",
        )
        if not path:
            return
        try:
            self._target = load_sprite(Path(path))
            self._target_lbl.setText(Path(path).name)
            self._target_lbl.setStyleSheet("")
            self._mapping = {}
            self._step = 0
            self._update_step_ui()
            self._btn_next.setEnabled(True)
            self._stack.setCurrentIndex(0)
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _update_step_ui(self) -> None:
        src = self._source
        tgt = self._target
        if tgt is None or not src.palette:
            return

        total = len(src.palette)
        i = self._step
        if i >= total:
            self._show_preview()
            return

        color = src.palette[i]
        r, g, b = color
        word = (r >> 4) | ((g >> 4) << 4) | ((b >> 4) << 8)

        self._step_lbl.setText(tr("remap.step", i=i + 1, total=total))
        self._btn_prev.setEnabled(i > 0)

        # Update source preview (dimmed highlight)
        highlighted = _highlight_color(src.hw, color)
        pm = _preview_pixmap(highlighted, 160)
        self._src_img_lbl.setPixmap(pm)
        self._src_swatch.setPixmap(_make_swatch(r, g, b))
        self._src_color_lbl.setText(f"0x{word:04X}  ({r},{g},{b})")

        # Rebuild radio buttons for target colors
        # Clear old widgets
        while self._radio_layout.count():
            item = self._radio_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        self._radio_group_widget = QButtonGroup(self)
        prev_selection = self._mapping.get(i)

        for ti, tc in enumerate(tgt.palette):
            tr_, tg_, tb_ = tc
            tw = (tr_ >> 4) | ((tg_ >> 4) << 4) | ((tb_ >> 4) << 8)
            row_w = QWidget()
            row_h = QHBoxLayout(row_w)
            row_h.setContentsMargins(4, 2, 4, 2)
            radio = QRadioButton(f"0x{tw:04X}  ({tr_},{tg_},{tb_})")
            if prev_selection == ti:
                radio.setChecked(True)
            swatch = QLabel()
            swatch.setFixedSize(20, 16)
            swatch.setPixmap(_make_swatch(tr_, tg_, tb_, 20, 16))
            row_h.addWidget(swatch)
            row_h.addWidget(radio)
            row_h.addStretch()
            self._radio_group_widget.addButton(radio, ti)
            self._radio_layout.addWidget(row_w)

        self._radio_layout.addStretch()

        # Update Next button label
        if i == total - 1:
            self._btn_next.setText(tr("remap.show_preview"))
        else:
            self._btn_next.setText(tr("remap.next"))

    def _go_next(self) -> None:
        if self._target is None:
            QMessageBox.information(self, "", tr("remap.no_target"))
            return
        # Record selection
        selected = self._radio_group_widget.checkedId() if hasattr(self, "_radio_group_widget") else -1
        self._mapping[self._step] = selected if selected >= 0 else None
        self._step += 1
        if self._step >= len(self._source.palette):
            self._show_preview()
        else:
            self._update_step_ui()

    def _skip(self) -> None:
        self._mapping[self._step] = None
        self._step += 1
        if self._step >= len(self._source.palette):
            self._show_preview()
        else:
            self._update_step_ui()

    def _go_prev(self) -> None:
        if self._step > 0:
            self._step -= 1
            self._stack.setCurrentIndex(0)
            self._update_step_ui()

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _show_preview(self) -> None:
        if self._target is None:
            return
        self.result_data = self._build_result()
        # Update preview labels
        src_pm = _preview_pixmap(self.result_data.hw, 190)
        self._result_lbl.setPixmap(src_pm)
        tgt_pm = _preview_pixmap(self._target.hw, 190)
        self._target_ref_lbl.setPixmap(tgt_pm)
        # Switch to preview page
        self._stack.setCurrentIndex(1)
        self._btn_skip.setEnabled(False)
        self._btn_prev.setEnabled(True)
        self._btn_next.setEnabled(False)
        self._step_lbl.setText(tr("remap.source_remapped"))

    def _build_result(self) -> SpriteData:
        src = self._source
        tgt = self._target
        assert tgt is not None
        new_palette = []
        for i, src_color in enumerate(src.palette):
            ti = self._mapping.get(i)
            if ti is not None and 0 <= ti < len(tgt.palette):
                new_palette.append(tgt.palette[ti])
            else:
                new_palette.append(src_color)
        return remap_palette(src, new_palette)

    def _save_result(self) -> None:
        if self.result_data is None:
            return
        default = str(
            self._source.path.parent / (self._source.path.stem + "_remapped.png")
        )
        path, _ = QFileDialog.getSaveFileName(
            self, tr("remap.apply_save"), default, tr("remap.file_filter")
        )
        if path:
            self.result_data.hw.save(path)
            QMessageBox.information(self, "✓", tr("remap.saved", path=path))
            self.accept()  # saved → apply result in caller
