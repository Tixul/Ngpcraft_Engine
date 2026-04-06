"""
ui/reduce_colors_dialog.py — Guided color reduction dialog (feature G).

Shows all palette colors, suggests closest pairs ordered by ΔE (Euclidean
distance in RGB444 space), and lets the user iteratively merge pairs until
the desired count is reached.

On accept, .result_data contains the remapped SpriteData with pixels updated.
"""

from __future__ import annotations

import math
from PIL import Image

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.sprite_loader import SpriteData, remap_palette
from i18n.lang import tr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pil_to_qpixmap(img: Image.Image) -> QPixmap:
    rgba = img.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimg = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


def _preview_pixmap(img: Image.Image, max_size: int = 210) -> QPixmap:
    w, h = img.size
    factor = max(1, min(max_size // max(w, 1), max_size // max(h, 1)))
    return _pil_to_qpixmap(img.resize((w * factor, h * factor), Image.NEAREST))


def _swatch_pixmap(r: int, g: int, b: int, sw: int = 28, sh: int = 20) -> QPixmap:
    img = Image.new("RGB", (sw, sh), (r, g, b))
    return _pil_to_qpixmap(img)


def _delta_e(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    """Euclidean distance in RGB8 space (both already snapped to RGB444)."""
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(c1, c2)))


def _sorted_pairs(
    palette: list[tuple[int, int, int]],
) -> list[tuple[float, int, int]]:
    """All distinct index pairs sorted by ascending ΔE."""
    pairs: list[tuple[float, int, int]] = []
    n = len(palette)
    for i in range(n):
        for j in range(i + 1, n):
            pairs.append((_delta_e(palette[i], palette[j]), i, j))
    pairs.sort(key=lambda x: x[0])
    return pairs


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class ReduceColorsDialog(QDialog):
    """
    Iterative color reduction assistant.

    Attributes:
        result_data: populated after accept() — remapped SpriteData.
    """

    def __init__(self, data: SpriteData, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("reduce.title"))
        self.setMinimumSize(700, 500)
        self._original = data
        # Working palette (mutable; indices shift as we pop merged colors)
        self._palette: list[tuple[int, int, int]] = list(data.palette)
        # Chain remap: color → its replacement (may be multi-hop)
        self._remap: dict[tuple[int, int, int], tuple[int, int, int]] = {}
        self.result_data: SpriteData | None = None
        self._build_ui()
        self._refresh()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(6)

        body = QHBoxLayout()

        # Left: live preview
        left_g = QGroupBox(tr("reduce.preview"))
        left_l = QVBoxLayout(left_g)
        self._preview_lbl = QLabel()
        self._preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_lbl.setFixedSize(220, 220)
        left_l.addWidget(self._preview_lbl)
        self._count_lbl = QLabel()
        self._count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_l.addWidget(self._count_lbl)
        left_l.addStretch()
        body.addWidget(left_g)

        # Right: merge suggestions
        right_g = QGroupBox(tr("reduce.suggestions"))
        right_l = QVBoxLayout(right_g)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._sugg_widget = QWidget()
        self._sugg_layout = QVBoxLayout(self._sugg_widget)
        self._sugg_layout.setSpacing(3)
        scroll.setWidget(self._sugg_widget)
        right_l.addWidget(scroll)
        body.addWidget(right_g, 1)

        root.addLayout(body, 1)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = box.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText(tr("reduce.apply"))
        box.accepted.connect(self._on_apply)
        box.rejected.connect(self.reject)
        root.addWidget(box)

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        # Update preview
        current = self._build_current()
        if current is not None:
            self._preview_lbl.setPixmap(_preview_pixmap(current.hw, 210))
        self._count_lbl.setText(tr("reduce.color_count", n=len(self._palette)))

        # Rebuild suggestion rows
        while self._sugg_layout.count():
            item = self._sugg_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        pairs = _sorted_pairs(self._palette)
        if not pairs:
            lbl = QLabel(tr("reduce.no_pairs"))
            lbl.setStyleSheet("color: gray;")
            self._sugg_layout.addWidget(lbl)
        else:
            for d, i, j in pairs[:20]:
                self._sugg_layout.addWidget(self._make_row(d, i, j))
        self._sugg_layout.addStretch()

    def _make_row(self, d: float, i: int, j: int) -> QWidget:
        c1, c2 = self._palette[i], self._palette[j]

        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(2, 2, 2, 2)
        h.setSpacing(6)

        sw1 = QLabel()
        sw1.setPixmap(_swatch_pixmap(*c1))
        sw1.setFixedSize(28, 20)
        sw1.setToolTip(f"#{c1[0]:02X}{c1[1]:02X}{c1[2]:02X}")
        h.addWidget(sw1)

        h.addWidget(QLabel("↔"))

        sw2 = QLabel()
        sw2.setPixmap(_swatch_pixmap(*c2))
        sw2.setFixedSize(28, 20)
        sw2.setToolTip(f"#{c2[0]:02X}{c2[1]:02X}{c2[2]:02X}")
        h.addWidget(sw2)

        h.addWidget(QLabel(f"  ΔE={d:.0f}"), 1)

        btn_a = QPushButton(tr("reduce.keep_a"))
        btn_a.setMaximumWidth(110)
        btn_a.setToolTip(f"Garder  #{c1[0]:02X}{c1[1]:02X}{c1[2]:02X}")
        btn_a.clicked.connect(lambda _, _i=i, _j=j: self._merge(keep=_i, discard=_j))
        h.addWidget(btn_a)

        btn_b = QPushButton(tr("reduce.keep_b"))
        btn_b.setMaximumWidth(110)
        btn_b.setToolTip(f"Garder  #{c2[0]:02X}{c2[1]:02X}{c2[2]:02X}")
        btn_b.clicked.connect(lambda _, _i=i, _j=j: self._merge(keep=_j, discard=_i))
        h.addWidget(btn_b)

        return row

    # ------------------------------------------------------------------
    # Merge logic
    # ------------------------------------------------------------------

    def _resolve(self, c: tuple[int, int, int]) -> tuple[int, int, int]:
        """Follow the remap chain (with cycle-guard) to the final representative."""
        seen: set[tuple[int, int, int]] = set()
        while c in self._remap and c not in seen:
            seen.add(c)
            c = self._remap[c]
        return c

    def _merge(self, keep: int, discard: int) -> None:
        """Replace palette[discard] with palette[keep] everywhere."""
        keep_color    = self._palette[keep]
        discard_color = self._palette[discard]
        # Record the substitution (resolve() handles transitive chains)
        self._remap[discard_color] = keep_color
        self._palette.pop(discard)
        self._refresh()

    def _build_current(self) -> SpriteData | None:
        """Apply the accumulated remap to the original SpriteData."""
        if not self._remap:
            return self._original
        new_pal = [self._resolve(c) for c in self._original.palette]
        try:
            return remap_palette(self._original, new_pal)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def _on_apply(self) -> None:
        self.result_data = self._build_current()
        self.accept()
