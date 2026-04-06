"""
ui/layer_split_dialog.py - Dialog showing the result of a multilayer sprite split.

Displays each layer with:
- Layer letter (A, B, C, ...)
- Color count and color swatches
- Preview (composite over checkerboard)
- --fixed-palette argument string + copy button
- Save as PNG button

Renders layers in order: A at bottom, B on top, etc.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.layer_split import LayerInfo, SplitResult
from core.palette_remap import composite_on_checker
from i18n.lang import tr


_LAYER_LETTERS = "ABCDEFGHIJ"
_PREVIEW_ZOOM = 4
_SWATCH_SIZE = 20


def _pil_to_qpixmap(img: Image.Image) -> QPixmap:
    rgb = img.convert("RGBA")
    data = rgb.tobytes("raw", "RGBA")
    from PyQt6.QtGui import QImage
    qimg = QImage(data, rgb.width, rgb.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


def _make_preview(img: Image.Image, zoom: int) -> QPixmap:
    comp = composite_on_checker(img)
    w, h = comp.size
    scaled = comp.resize((w * zoom, h * zoom), Image.NEAREST)
    return _pil_to_qpixmap(scaled)


class _SwatchLabel(QLabel):
    """Small color swatch used to display one RGB444 layer color."""

    def __init__(self, r: int, g: int, b: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(_SWATCH_SIZE, _SWATCH_SIZE)
        self.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border: 1px solid #333;"
        )
        self.setToolTip(f"RGB({r},{g},{b})  →  0x{(r>>4) | ((g>>4)<<4) | ((b>>4)<<8):04X}")


class LayerPanel(QGroupBox):
    """Widget showing a single layer's preview, swatches, palette arg, and save button."""

    def __init__(self, layer: LayerInfo, source_path: Path | None, parent: QWidget | None = None) -> None:
        letter = _LAYER_LETTERS[layer.index] if layer.index < len(_LAYER_LETTERS) else str(layer.index)
        title = tr("pal.split_layer_label", letter=letter, n=len(layer.colors))
        super().__init__(title, parent)
        self._layer = layer
        self._source_path = source_path
        self._letter = letter
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # Preview
        preview_pm = _make_preview(self._layer.image, _PREVIEW_ZOOM)
        preview_lbl = QLabel()
        preview_lbl.setPixmap(preview_pm)
        preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(preview_lbl)

        # Color swatches
        swatch_row = QHBoxLayout()
        swatch_row.addWidget(QLabel("Colors:"))
        for r, g, b in self._layer.colors:
            swatch_row.addWidget(_SwatchLabel(r, g, b))
        swatch_row.addStretch()
        layout.addLayout(swatch_row)

        # --fixed-palette row
        pal_row = QHBoxLayout()
        pal_row.addWidget(QLabel(tr("pal.split_fixed_pal_label")))
        self._pal_edit = QLineEdit(self._layer.fixed_palette_arg)
        self._pal_edit.setReadOnly(True)
        self._pal_edit.setStyleSheet("font-family: monospace;")
        pal_row.addWidget(self._pal_edit, 1)
        copy_btn = QPushButton(tr("pal.split_copy_pal"))
        copy_btn.setFixedWidth(60)
        copy_btn.clicked.connect(self._copy_pal)
        pal_row.addWidget(copy_btn)
        layout.addLayout(pal_row)

        # Save button
        save_btn = QPushButton(tr("pal.split_save_layer", letter=self._letter))
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)

    def _copy_pal(self) -> None:
        QApplication.clipboard().setText(self._pal_edit.text())

    def _save(self) -> None:
        if self._source_path:
            stem = self._source_path.stem
            default = str(self._source_path.parent / f"{stem}_layer{self._letter}.png")
        else:
            default = f"layer{self._letter}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, tr("pal.split_save_layer", letter=self._letter), default, "PNG (*.png)"
        )
        if path:
            self._layer.image.save(path)


class LayerSplitDialog(QDialog):
    """Dialog displaying all layers from a SplitResult."""

    def __init__(
        self,
        result: SplitResult,
        source_path: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("pal.split_title"))
        self.setMinimumWidth(500)
        self._result = result
        self._source_path = source_path
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)

        # Info banner
        info = QLabel(tr("pal.split_info"))
        info.setWordWrap(True)
        info.setStyleSheet("color: #555; font-style: italic;")
        root.addWidget(info)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(sep)

        # Scroll area with layer panels side by side
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        h_layout = QHBoxLayout(container)
        h_layout.setSpacing(12)
        for layer in self._result.layers:
            panel = LayerPanel(layer, self._source_path, container)
            h_layout.addWidget(panel)
        h_layout.addStretch()
        scroll.setWidget(container)
        root.addWidget(scroll)

        # Composite preview (all layers stacked)
        if len(self._result.layers) > 1:
            comp_group = QGroupBox("Aperçu composité (toutes couches)")
            comp_layout = QVBoxLayout(comp_group)
            comp_img = self._result.layers[0].image.copy()
            for layer in self._result.layers[1:]:
                comp_img.paste(layer.image, (0, 0), layer.image)
            comp_pm = _make_preview(comp_img, _PREVIEW_ZOOM)
            comp_lbl = QLabel()
            comp_lbl.setPixmap(comp_pm)
            comp_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            comp_layout.addWidget(comp_lbl)
            root.addWidget(comp_group)

        # Close button
        close_btn = QPushButton(tr("pal.split_close"))
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)
