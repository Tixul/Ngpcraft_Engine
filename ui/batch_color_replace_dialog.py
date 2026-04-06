"""
ui/batch_color_replace_dialog.py — Batch color replacement across a scene (feature H).

Lets the user pick a source RGB444 color and a target RGB444 color, previews
which sprites in the current scene are affected (pixel count), then applies
the in-place replacement to all matching PNG files.

After accept(), .applied is True if at least one file was modified.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.rgb444 import snap
from i18n.lang import tr


# ---------------------------------------------------------------------------
# Pure helpers (no Qt)
# ---------------------------------------------------------------------------

def _count_pixels(path: Path, src: tuple[int, int, int]) -> int:
    """Count opaque pixels matching src (after RGB444 snap) in a PNG."""
    try:
        img = Image.open(path).convert("RGBA")
        count = 0
        for r, g, b, a in img.getdata():
            if a >= 128 and snap(r, g, b) == src:
                count += 1
        return count
    except Exception:
        return 0


def _replace_color(
    path: Path,
    src: tuple[int, int, int],
    dst: tuple[int, int, int],
) -> int:
    """
    Replace all opaque pixels matching src with dst in the PNG (in-place).
    Returns number of pixels changed, or -1 on error.
    """
    try:
        img = Image.open(path).convert("RGBA")
        px = img.load()
        w, h = img.size
        changed = 0
        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                if a >= 128 and snap(r, g, b) == src:
                    px[x, y] = (*dst, a)
                    changed += 1
        img.save(str(path))
        return changed
    except Exception:
        return -1


# ---------------------------------------------------------------------------
# Qt helpers
# ---------------------------------------------------------------------------

def _pil_to_qpixmap(img: Image.Image, max_size: int = 40) -> QPixmap:
    rgba = img.convert("RGBA")
    w, h = rgba.size
    factor = max(1, min(max_size // max(w, 1), max_size // max(h, 1)))
    scaled = rgba.resize((w * factor, h * factor), Image.NEAREST)
    data = scaled.tobytes("raw", "RGBA")
    qimg = QImage(data, scaled.width, scaled.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


def _swatch_pixmap(r: int, g: int, b: int, sw: int = 44, sh: int = 30) -> QPixmap:
    img = Image.new("RGB", (sw, sh), (r, g, b))
    data = img.convert("RGBA").tobytes("raw", "RGBA")
    qimg = QImage(data, sw, sh, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class BatchColorReplaceDialog(QDialog):
    """
    Replace one RGB444 color across all PNG files of a scene.

    Args:
        sprites:  list of sprite dicts from the scene (keys: 'file', 'name').
        base_dir: project root used to resolve relative paths.

    Attributes:
        applied: True after accept() if at least one file was saved.
    """

    def __init__(
        self,
        sprites: list[dict],
        base_dir: Path | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("batch.title"))
        self.setMinimumSize(560, 480)
        self._sprites = sprites
        self._base_dir = base_dir
        self._src: tuple[int, int, int] | None = None
        self._dst: tuple[int, int, int] | None = None
        self.applied = False
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # Source color row
        src_g = QGroupBox(tr("batch.source_group"))
        src_l = QHBoxLayout(src_g)
        self._src_swatch = QLabel()
        self._src_swatch.setFixedSize(44, 30)
        self._src_swatch.setStyleSheet("border: 1px solid gray;")
        src_l.addWidget(self._src_swatch)
        self._src_lbl = QLabel(tr("batch.none_selected"))
        self._src_lbl.setStyleSheet("color: gray;")
        src_l.addWidget(self._src_lbl, 1)
        btn_src = QPushButton(tr("batch.source_btn"))
        btn_src.clicked.connect(self._pick_source)
        src_l.addWidget(btn_src)
        root.addWidget(src_g)

        # Target color row
        dst_g = QGroupBox(tr("batch.target_group"))
        dst_l = QHBoxLayout(dst_g)
        self._dst_swatch = QLabel()
        self._dst_swatch.setFixedSize(44, 30)
        self._dst_swatch.setStyleSheet("border: 1px solid gray;")
        dst_l.addWidget(self._dst_swatch)
        self._dst_lbl = QLabel(tr("batch.none_selected"))
        self._dst_lbl.setStyleSheet("color: gray;")
        dst_l.addWidget(self._dst_lbl, 1)
        btn_dst = QPushButton(tr("batch.target_btn"))
        btn_dst.clicked.connect(self._pick_target)
        dst_l.addWidget(btn_dst)
        root.addWidget(dst_g)

        # Affected sprites preview
        prev_g = QGroupBox(tr("batch.preview_group"))
        prev_l = QVBoxLayout(prev_g)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._preview_widget = QWidget()
        self._preview_layout = QVBoxLayout(self._preview_widget)
        self._preview_layout.setSpacing(3)
        scroll.setWidget(self._preview_widget)
        prev_l.addWidget(scroll)
        root.addWidget(prev_g, 1)

        # Buttons
        box = QDialogButtonBox()
        self._apply_btn = box.addButton(
            tr("batch.apply_btn"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._do_apply)
        box.addButton(QDialogButtonBox.StandardButton.Cancel).clicked.connect(self.reject)
        root.addWidget(box)

    # ------------------------------------------------------------------
    # Color picking
    # ------------------------------------------------------------------

    def _pick_color(
        self, initial: tuple[int, int, int] | None = None
    ) -> tuple[int, int, int] | None:
        init = QColor(*initial) if initial else QColor(255, 0, 0)
        dlg = QColorDialog(init, self)
        if dlg.exec() != QColorDialog.DialogCode.Accepted:
            return None
        c = dlg.selectedColor()
        return snap(c.red(), c.green(), c.blue())

    def _pick_source(self) -> None:
        c = self._pick_color(self._src)
        if c is None:
            return
        self._src = c
        r, g, b = c
        self._src_swatch.setPixmap(_swatch_pixmap(r, g, b))
        self._src_lbl.setText(f"#{r:02X}{g:02X}{b:02X}  ({r}, {g}, {b})")
        self._src_lbl.setStyleSheet("")
        self._refresh_preview()
        self._update_apply_btn()

    def _pick_target(self) -> None:
        c = self._pick_color(self._dst)
        if c is None:
            return
        self._dst = c
        r, g, b = c
        self._dst_swatch.setPixmap(_swatch_pixmap(r, g, b))
        self._dst_lbl.setText(f"#{r:02X}{g:02X}{b:02X}  ({r}, {g}, {b})")
        self._dst_lbl.setStyleSheet("")
        self._update_apply_btn()

    def _update_apply_btn(self) -> None:
        self._apply_btn.setEnabled(self._src is not None and self._dst is not None)

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _abs(self, rel: str) -> Path:
        p = Path(rel)
        if p.is_absolute():
            return p
        return (self._base_dir / p) if self._base_dir else p

    def _refresh_preview(self) -> None:
        while self._preview_layout.count():
            item = self._preview_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        if self._src is None:
            return

        found_any = False
        for spr in self._sprites:
            rel = str(spr.get("file") or "").strip()
            if not rel:
                continue
            path = self._abs(rel)
            if not path.exists():
                continue
            count = _count_pixels(path, self._src)
            if count == 0:
                continue
            found_any = True

            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(2, 2, 2, 2)
            h.setSpacing(8)

            thumb_lbl = QLabel()
            try:
                thumb_lbl.setPixmap(_pil_to_qpixmap(Image.open(path), max_size=40))
            except Exception:
                pass
            thumb_lbl.setFixedSize(44, 44)
            h.addWidget(thumb_lbl)

            name = spr.get("name") or path.stem
            h.addWidget(QLabel(f"<b>{name}</b>  —  {count} px"), 1)
            self._preview_layout.addWidget(row)

        if not found_any:
            lbl = QLabel(tr("batch.none_affected"))
            lbl.setStyleSheet("color: gray;")
            self._preview_layout.addWidget(lbl)

        self._preview_layout.addStretch()

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def _do_apply(self) -> None:
        if self._src is None or self._dst is None:
            return

        affected = [
            self._abs(str(spr.get("file") or ""))
            for spr in self._sprites
            if (spr.get("file") or "").strip()
        ]
        affected = [
            p for p in affected
            if p.exists() and _count_pixels(p, self._src) > 0
        ]

        if not affected:
            QMessageBox.information(self, tr("batch.title"), tr("batch.none_affected"))
            return

        ans = QMessageBox.question(
            self,
            tr("batch.title"),
            tr("batch.confirm", n=len(affected)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        n_ok = 0
        errs: list[str] = []
        for path in affected:
            res = _replace_color(path, self._src, self._dst)
            if res >= 0:
                n_ok += 1
            else:
                errs.append(path.name)

        msg = tr("batch.done", n=n_ok)
        if errs:
            msg += "\n" + tr("batch.errors", files=", ".join(errs))
        QMessageBox.information(self, tr("batch.title"), msg)
        self.applied = True
        self.accept()
