"""
ui/tabs/dialogues_tab.py — Dialogue Bank editor (DLG-1/2/3).

Per-scene dialogue management:
  - List of dialogues (named banks, one per interaction)
  - Each dialogue = ordered list of lines {speaker, text, portrait}
  - NGPC preview box (160×32)
  - CSV import / export

Data stored in scene["dialogues"] = [
    {"id": "intro", "lines": [{"speaker": "Elder", "text": "Hello.", "portrait": ""}]}
]

Export → scene_<safe>_dialogs.h (called from scene_level_gen.py).
Action show_dialogue(a0 = dialogue_index) drives runtime.
"""
from __future__ import annotations

import csv
import io
import re
import uuid
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QRect, QSize, QPoint, pyqtSignal
from PyQt6.QtGui import (
    QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap, QTransform,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from i18n.lang import tr

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SPEAKER_MAX = 12   # chars
_TEXT_MAX    = 80   # chars (2 lines × 40 on NGPC 160-wide screen)
_PREVIEW_W   = 160
_PREVIEW_H   = 40
_PREVIEW_SCALE = 3   # display at 3× for readability

_RE_SAFE = re.compile(r"[^a-zA-Z0-9_]+")


def _safe_id(s: str) -> str:
    return _RE_SAFE.sub("_", s).strip("_").lower() or "dlg"


# ---------------------------------------------------------------------------
# NGPC Dialog Preview widget
# ---------------------------------------------------------------------------

class _NgpcDialogPreview(QWidget):
    """
    Renders an NGPC dialog box at 3× scale.

    When a background sprite PNG is provided (16×16, 4 tiles 8×8):
      [TL] corner   [TR] H-border top
      [BL] fill     [BR] V-border right
    Tiles are extracted and painted with H/V transforms for all sides.

    When a portrait sprite PNG is provided the first 24×24 px are shown
    scaled inside the portrait slot.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._speaker        = ""
        self._text           = ""
        self._palette: list[str] = []   # [word1, word2, word3] NGPC RGB444
        # Pixmaps (None = not loaded / not set)
        self._portrait_px: QPixmap | None = None
        self._bg_tiles: list[QPixmap] | None = None   # [corner, hborder, fill, vborder_r]
        pw = _PREVIEW_W * _PREVIEW_SCALE
        ph = _PREVIEW_H * _PREVIEW_SCALE
        self.setFixedSize(pw + 2, ph + 2)

    def set_line(self, speaker: str, text: str,
                 portrait_px: "QPixmap | None" = None,
                 bg_tiles: "list[QPixmap] | None" = None,
                 palette: "list[str] | None" = None) -> None:
        self._speaker     = speaker[:_SPEAKER_MAX]
        self._text        = text[:_TEXT_MAX]
        self._portrait_px = portrait_px
        self._bg_tiles    = bg_tiles
        # palette = [word1, word2, word3] (NGPC RGB444 hex, slots 1-3)
        self._palette     = palette or []
        self.update()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _flip(px: QPixmap, hflip: bool, vflip: bool) -> QPixmap:
        """Return px flipped horizontally and/or vertically."""
        if not hflip and not vflip:
            return px
        return px.transformed(QTransform().scale(
            -1 if hflip else 1,
             -1 if vflip else 1,
        ))

    def _draw_tile_tiled(self, p: QPainter, tile: QPixmap,
                         x: int, y: int, w: int, h: int,
                         hflip: bool = False, vflip: bool = False) -> None:
        """Fill rect (x,y,w,h) by repeating tile (scaled to t×t)."""
        t = 8 * _PREVIEW_SCALE
        src = self._flip(tile.scaled(t, t, Qt.AspectRatioMode.IgnoreAspectRatio,
                                     Qt.TransformationMode.FastTransformation),
                         hflip, vflip)
        for tx in range(x, x + w, t):
            for ty in range(y, y + h, t):
                p.drawPixmap(tx, ty, src)

    # ------------------------------------------------------------------
    # paintEvent
    # ------------------------------------------------------------------

    def paintEvent(self, _event):
        s = _PREVIEW_SCALE
        pw = _PREVIEW_W * s
        ph = _PREVIEW_H * s
        t  = 8 * s          # 1 tile at scale

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        tiles = self._bg_tiles  # [corner, hborder, fill, vborder_r]

        if tiles and len(tiles) == 4:
            corner, hborder, fill, vborder_r = tiles

            # Centre fill
            self._draw_tile_tiled(p, fill, t, t, pw - 2*t, ph - 2*t)

            # Top / bottom H-border
            self._draw_tile_tiled(p, hborder,  t, 0,      pw - 2*t, t)           # top
            self._draw_tile_tiled(p, hborder,  t, ph - t, pw - 2*t, t, vflip=True)  # bot

            # Left / right V-border
            self._draw_tile_tiled(p, vborder_r, pw - t, t, t, ph - 2*t)          # right
            self._draw_tile_tiled(p, vborder_r, 0,      t, t, ph - 2*t, hflip=True) # left

            # Corners
            ct = corner.scaled(t, t, Qt.AspectRatioMode.IgnoreAspectRatio,
                                Qt.TransformationMode.FastTransformation)
            p.drawPixmap(0,       0,       ct)
            p.drawPixmap(pw - t,  0,       self._flip(ct, True,  False))
            p.drawPixmap(0,       ph - t,  self._flip(ct, False, True))
            p.drawPixmap(pw - t,  ph - t,  self._flip(ct, True,  True))

        else:
            # Default: plain dark box
            p.fillRect(0, 0, pw, ph, QColor("#1a1a2e"))
            p.setPen(QPen(QColor("#aaaacc"), 1))
            p.drawRect(0, 0, pw - 1, ph - 1)

        # Portrait slot
        port_w = 24 * s
        x_text = 2 * s
        if self._portrait_px and not self._portrait_px.isNull():
            scaled_port = self._portrait_px.scaled(
                port_w, ph - 4 * s,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            px_x = 2 * s
            px_y = (ph - scaled_port.height()) // 2
            p.drawPixmap(px_x, px_y, scaled_port)
            x_text = px_x + port_w + 2 * s
        elif self._portrait_px is not None:
            # Explicitly set but null (file missing) — show placeholder
            p.fillRect(2*s, 2*s, port_w, ph - 4*s, QColor("#2a2a44"))
            p.setPen(QPen(QColor("#6666aa"), 1))
            p.drawRect(2*s, 2*s, port_w - 1, ph - 4*s - 1)
            font_p = QFont("Courier", max(6, s * 4))
            p.setFont(font_p)
            p.setPen(QColor("#888888"))
            p.drawText(QRect(2*s, 2*s, port_w, ph - 4*s),
                       Qt.AlignmentFlag.AlignCenter, "?")
            x_text = 2*s + port_w + 2*s

        # Palette colors: slot1=text, slot2=speaker, slot3=accent (fallback if not set)
        def _pal_color(slot: int, fallback: str) -> QColor:
            """slot=1/2/3; returns QColor from self._palette or fallback hex string."""
            idx = slot - 1
            if idx < len(self._palette):
                try:
                    w = int(self._palette[idx], 16) & 0x0FFF
                    r4 = w & 0xF; g4 = (w >> 4) & 0xF; b4 = (w >> 8) & 0xF
                    return QColor(r4 * 17, g4 * 17, b4 * 17)
                except (ValueError, TypeError):
                    pass
            return QColor(fallback)

        # Speaker name
        font_sm = QFont("Courier", max(5, s * 4))
        font_sm.setBold(True)
        p.setFont(font_sm)
        p.setPen(_pal_color(2, "#ffdd88"))
        if self._speaker:
            p.drawText(x_text, 0, pw - x_text - s, 10 * s,
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       self._speaker)

        # Text body
        font_body = QFont("Courier", max(5, s * 4))
        p.setFont(font_body)
        p.setPen(_pal_color(1, "#dddddd"))
        p.drawText(QRect(x_text, 10 * s, pw - x_text - s, ph - 12 * s),
                   Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
                   | Qt.TextFlag.TextWordWrap,
                   self._text or "")

        p.end()


# ---------------------------------------------------------------------------
# Main tab widget
# ---------------------------------------------------------------------------

class DialoguesTab(QWidget):
    """Dialogue bank editor, one bank per scene."""

    scene_modified = pyqtSignal(object)   # dict payload (scene)

    def __init__(self, on_save=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_save = on_save
        self._scene: dict | None = None
        self._base_dir: str | None = None
        self._project_data: dict | None = None

        # Mutable state
        self._sel_dlg: int = -1         # selected dialogue index
        self._sel_line: int = -1        # selected line index
        self._sel_menu: int = -1        # selected menu index
        self._sel_menu_item: int = -1   # selected menu item index

        # Debounce timer — prevents save on every keystroke
        from PyQt6.QtCore import QTimer
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)   # ms after last keystroke
        self._save_timer.timeout.connect(self._flush_save)

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Top bar ──────────────────────────────────────────────────
        bar = QHBoxLayout()
        bar.setSpacing(6)

        self._lbl_scene = QLabel(tr("dlg.scene_label"))
        self._lbl_scene.setStyleSheet("color:#aaaacc; font-size:12px;")
        bar.addWidget(self._lbl_scene)

        self._combo_scene = QComboBox()
        self._combo_scene.setMinimumWidth(180)
        self._combo_scene.currentIndexChanged.connect(self._on_scene_changed)
        bar.addWidget(self._combo_scene)

        bar.addStretch(1)

        self._btn_import_csv = QPushButton(tr("dlg.import_csv"))
        self._btn_import_csv.setToolTip(tr("dlg.import_csv_tt"))
        self._btn_import_csv.clicked.connect(self._on_import_csv)
        bar.addWidget(self._btn_import_csv)

        self._btn_export_csv = QPushButton(tr("dlg.export_csv"))
        self._btn_export_csv.setToolTip(tr("dlg.export_csv_tt"))
        self._btn_export_csv.clicked.connect(self._on_export_csv)
        bar.addWidget(self._btn_export_csv)

        root.addLayout(bar)

        # ── Main splitter: left panel | right stack ──────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── LEFT PANEL: dialogue list + menu list ────────────────────
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(4)

        lbl_dlg = QLabel(tr("dlg.dialogues"))
        lbl_dlg.setStyleSheet("color:#ccccdd; font-weight:bold; font-size:12px;")
        lv.addWidget(lbl_dlg)

        self._list_dlg = QListWidget()
        self._list_dlg.setStyleSheet(
            "QListWidget { background:#1e1e28; color:#ccccdd; border:1px solid #333; }"
            "QListWidget::item:selected { background:#3a3a55; }"
        )
        self._list_dlg.currentRowChanged.connect(self._on_dlg_selected)
        lv.addWidget(self._list_dlg, 2)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self._btn_add_dlg = QPushButton("+")
        self._btn_add_dlg.setFixedWidth(32)
        self._btn_add_dlg.setToolTip(tr("dlg.add_dialogue_tt"))
        self._btn_add_dlg.clicked.connect(self._on_add_dlg)
        self._btn_del_dlg = QPushButton("−")
        self._btn_del_dlg.setFixedWidth(32)
        self._btn_del_dlg.setToolTip(tr("dlg.del_dialogue_tt"))
        self._btn_del_dlg.clicked.connect(self._on_del_dlg)
        self._btn_ren_dlg = QPushButton(tr("dlg.rename"))
        self._btn_ren_dlg.clicked.connect(self._on_rename_dlg)
        btn_row.addWidget(self._btn_add_dlg)
        btn_row.addWidget(self._btn_del_dlg)
        btn_row.addWidget(self._btn_ren_dlg)
        btn_row.addStretch(1)
        lv.addLayout(btn_row)

        sep_lm = QFrame()
        sep_lm.setFrameShape(QFrame.Shape.HLine)
        sep_lm.setStyleSheet("color:#444455;")
        lv.addWidget(sep_lm)

        lbl_menus = QLabel(tr("dlg.menus"))
        lbl_menus.setStyleSheet("color:#ccccdd; font-weight:bold; font-size:12px;")
        lv.addWidget(lbl_menus)

        self._list_menus = QListWidget()
        self._list_menus.setStyleSheet(
            "QListWidget { background:#1e1e28; color:#ccccdd; border:1px solid #333; }"
            "QListWidget::item:selected { background:#3a3a55; }"
        )
        self._list_menus.setMaximumHeight(110)
        self._list_menus.currentRowChanged.connect(self._on_menu_selected)
        lv.addWidget(self._list_menus)

        menu_btn_row = QHBoxLayout()
        menu_btn_row.setSpacing(4)
        self._btn_add_menu = QPushButton("+")
        self._btn_add_menu.setFixedWidth(32)
        self._btn_add_menu.setToolTip(tr("dlg.add_menu_tt"))
        self._btn_add_menu.clicked.connect(self._on_add_menu)
        self._btn_del_menu = QPushButton("−")
        self._btn_del_menu.setFixedWidth(32)
        self._btn_del_menu.setToolTip(tr("dlg.del_menu_tt"))
        self._btn_del_menu.clicked.connect(self._on_del_menu)
        self._btn_ren_menu = QPushButton(tr("dlg.rename"))
        self._btn_ren_menu.clicked.connect(self._on_rename_menu)
        menu_btn_row.addWidget(self._btn_add_menu)
        menu_btn_row.addWidget(self._btn_del_menu)
        menu_btn_row.addWidget(self._btn_ren_menu)
        menu_btn_row.addStretch(1)
        lv.addLayout(menu_btn_row)

        left.setMinimumWidth(160)
        left.setMaximumWidth(260)
        splitter.addWidget(left)

        # ── RIGHT STACK: page 0 = line editor / page 1 = menu editor ─
        self._right_stack = QStackedWidget()

        # ── Page 0: dialogue line editor ─────────────────────────────
        page0 = QWidget()
        rv = QVBoxLayout(page0)
        rv.setContentsMargins(6, 0, 0, 0)
        rv.setSpacing(4)

        lbl_lines = QLabel(tr("dlg.lines"))
        lbl_lines.setStyleSheet("color:#ccccdd; font-weight:bold; font-size:12px;")
        rv.addWidget(lbl_lines)

        self._list_lines = QListWidget()
        self._list_lines.setStyleSheet(
            "QListWidget { background:#1e1e28; color:#ccccdd; border:1px solid #333; }"
            "QListWidget::item:selected { background:#3a3a55; }"
        )
        self._list_lines.currentRowChanged.connect(self._on_line_selected)
        rv.addWidget(self._list_lines, 1)

        line_btns = QHBoxLayout()
        line_btns.setSpacing(4)
        self._btn_add_line = QPushButton("+")
        self._btn_add_line.setFixedWidth(32)
        self._btn_add_line.setToolTip(tr("dlg.add_line_tt"))
        self._btn_add_line.clicked.connect(self._on_add_line)
        self._btn_del_line = QPushButton("−")
        self._btn_del_line.setFixedWidth(32)
        self._btn_del_line.setToolTip(tr("dlg.del_line_tt"))
        self._btn_del_line.clicked.connect(self._on_del_line)
        self._btn_up_line = QPushButton("↑")
        self._btn_up_line.setFixedWidth(32)
        self._btn_up_line.clicked.connect(self._on_move_line_up)
        self._btn_dn_line = QPushButton("↓")
        self._btn_dn_line.setFixedWidth(32)
        self._btn_dn_line.clicked.connect(self._on_move_line_dn)
        line_btns.addWidget(self._btn_add_line)
        line_btns.addWidget(self._btn_del_line)
        line_btns.addWidget(self._btn_up_line)
        line_btns.addWidget(self._btn_dn_line)
        line_btns.addStretch(1)
        rv.addLayout(line_btns)

        # ── On Done (dialogue-level) ──────────────────────────────────────
        self._on_done_widget = QWidget()
        od = QHBoxLayout(self._on_done_widget)
        od.setContentsMargins(0, 4, 0, 0)
        od.setSpacing(6)
        od_lbl = QLabel(tr("dlg.on_done"))
        od_lbl.setStyleSheet("color:#aaaacc; font-size:11px;")
        od_lbl.setToolTip(tr("dlg.on_done_tt"))
        od.addWidget(od_lbl)
        self._on_done_action_cb = QComboBox()
        self._on_done_action_cb.setToolTip(tr("dlg.on_done_tt"))
        self._on_done_action_cb.addItem(tr("dlg.on_done_close"),      "close")
        self._on_done_action_cb.addItem(tr("dlg.on_done_next_dlg"),   "next_dlg")
        self._on_done_action_cb.addItem(tr("dlg.on_done_set_flag"),   "set_flag")
        self._on_done_action_cb.addItem(tr("dlg.on_done_emit_event"), "emit_event")
        self._on_done_action_cb.setMinimumWidth(150)
        self._on_done_action_cb.currentIndexChanged.connect(self._on_on_done_action_changed)
        od.addWidget(self._on_done_action_cb)
        self._on_done_dlg_cb = QComboBox()
        self._on_done_dlg_cb.setMinimumWidth(110)
        self._on_done_dlg_cb.currentIndexChanged.connect(self._on_on_done_param_changed)
        od.addWidget(self._on_done_dlg_cb)
        self._on_done_n_sb = QSpinBox()
        self._on_done_n_sb.setRange(0, 63)
        self._on_done_n_sb.setFixedWidth(52)
        self._on_done_n_sb.valueChanged.connect(self._on_on_done_param_changed)
        od.addWidget(self._on_done_n_sb)
        od.addStretch(1)
        self._on_done_widget.setVisible(False)
        rv.addWidget(self._on_done_widget)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#444455;")
        rv.addWidget(sep)

        form = QHBoxLayout()
        form.setSpacing(8)

        spk_col = QVBoxLayout()
        spk_col.setSpacing(2)
        lbl_spk = QLabel(tr("dlg.speaker"))
        lbl_spk.setStyleSheet("color:#aaaacc; font-size:11px;")
        spk_col.addWidget(lbl_spk)
        self._edit_speaker = QLineEdit()
        self._edit_speaker.setMaxLength(_SPEAKER_MAX)
        self._edit_speaker.setPlaceholderText(tr("dlg.speaker_ph"))
        self._edit_speaker.setFixedWidth(100)
        self._edit_speaker.textChanged.connect(self._on_speaker_changed)
        spk_col.addWidget(self._edit_speaker)
        form.addLayout(spk_col)

        por_col = QVBoxLayout()
        por_col.setSpacing(2)
        lbl_por = QLabel(tr("dlg.portrait"))
        lbl_por.setStyleSheet("color:#aaaacc; font-size:11px;")
        por_col.addWidget(lbl_por)
        por_row = QHBoxLayout()
        por_row.setSpacing(4)
        self._combo_portrait = QComboBox()
        self._combo_portrait.setIconSize(QSize(32, 32))
        self._combo_portrait.setMinimumWidth(160)
        self._combo_portrait.currentIndexChanged.connect(self._on_portrait_changed)
        por_row.addWidget(self._combo_portrait)
        self._lbl_portrait_thumb = QLabel()
        self._lbl_portrait_thumb.setFixedSize(1, 1)
        self._lbl_portrait_thumb.setVisible(False)
        por_col.addLayout(por_row)
        form.addLayout(por_col)

        rv.addLayout(form)

        lbl_txt = QLabel(tr("dlg.text"))
        lbl_txt.setStyleSheet("color:#aaaacc; font-size:11px;")
        rv.addWidget(lbl_txt)
        self._edit_text = QLineEdit()
        self._edit_text.setMaxLength(_TEXT_MAX)
        self._edit_text.setPlaceholderText(tr("dlg.text_ph"))
        self._edit_text.textChanged.connect(self._on_text_changed)
        rv.addWidget(self._edit_text)

        self._lbl_chars = QLabel("0 / 80")
        self._lbl_chars.setStyleSheet("color:#666688; font-size:10px;")
        rv.addWidget(self._lbl_chars)

        # ── Choices section ──────────────────────────────────────────
        sep_ch = QFrame()
        sep_ch.setFrameShape(QFrame.Shape.HLine)
        sep_ch.setStyleSheet("color:#444455;")
        rv.addWidget(sep_ch)

        ch_hdr = QHBoxLayout()
        ch_hdr.setSpacing(4)
        self._lbl_choices = QLabel(tr("dlg.choices").format(n=0))
        self._lbl_choices.setStyleSheet("color:#aaaacc; font-size:11px;")
        ch_hdr.addWidget(self._lbl_choices)
        ch_hdr.addStretch(1)
        self._btn_add_choice = QPushButton("+")
        self._btn_add_choice.setFixedSize(22, 22)
        self._btn_add_choice.setToolTip(tr("dlg.add_choice_tt"))
        self._btn_add_choice.clicked.connect(self._on_add_choice)
        ch_hdr.addWidget(self._btn_add_choice)
        self._btn_del_choice = QPushButton("−")
        self._btn_del_choice.setFixedSize(22, 22)
        self._btn_del_choice.setToolTip(tr("dlg.del_choice_tt"))
        self._btn_del_choice.clicked.connect(self._on_del_choice)
        ch_hdr.addWidget(self._btn_del_choice)
        rv.addLayout(ch_hdr)

        # Two choice rows (QWidget, QLineEdit, QComboBox)
        self._choice_rows: list[tuple] = []
        for ci, num in enumerate(("①", "②")):
            crow_w = QWidget()
            crow = QHBoxLayout(crow_w)
            crow.setContentsMargins(0, 0, 0, 0)
            crow.setSpacing(4)
            lbl_ci = QLabel(num)
            lbl_ci.setStyleSheet("color:#888899; font-size:11px;")
            lbl_ci.setFixedWidth(14)
            crow.addWidget(lbl_ci)
            le = QLineEdit()
            le.setMaxLength(12)
            le.setPlaceholderText(tr("dlg.choice_label"))
            le.setFixedWidth(90)
            le.textChanged.connect(lambda txt, i=ci: self._on_choice_label_changed(i, txt))
            cb = QComboBox()
            cb.setToolTip(tr("dlg.choice_goto"))
            cb.setMinimumWidth(120)
            cb.currentIndexChanged.connect(lambda _, i=ci: self._on_choice_goto_changed(i))
            crow.addWidget(le)
            crow.addWidget(cb)
            crow.addStretch(1)
            crow_w.setVisible(False)
            rv.addWidget(crow_w)
            self._choice_rows.append((crow_w, le, cb))

        # ── Preview / config section ─────────────────────────────────
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color:#444455;")
        rv.addWidget(sep2)

        bg_row = QHBoxLayout()
        bg_row.setSpacing(6)
        lbl_bg = QLabel(tr("dlg.bg_sprite"))
        lbl_bg.setStyleSheet("color:#aaaacc; font-size:11px;")
        bg_row.addWidget(lbl_bg)
        self._combo_bg = QComboBox()
        self._combo_bg.setToolTip(tr("dlg.bg_sprite_tt"))
        self._combo_bg.setFixedWidth(140)
        self._combo_bg.currentIndexChanged.connect(self._on_bg_changed)
        bg_row.addWidget(self._combo_bg)
        lbl_bg_hint = QLabel(tr("dlg.bg_sprite_hint"))
        lbl_bg_hint.setStyleSheet("color:#555577; font-size:10px;")
        bg_row.addWidget(lbl_bg_hint)
        bg_row.addStretch(1)
        rv.addLayout(bg_row)

        fs_row = QHBoxLayout()
        fs_row.setSpacing(6)
        self._chk_full_screen = QCheckBox(tr("dlg.full_screen"))
        self._chk_full_screen.setToolTip(tr("dlg.full_screen_tt"))
        self._chk_full_screen.stateChanged.connect(self._on_full_screen_changed)
        fs_row.addWidget(self._chk_full_screen)
        fs_row.addStretch(1)
        rv.addLayout(fs_row)

        pal_row = QHBoxLayout()
        pal_row.setSpacing(4)
        lbl_pal = QLabel(tr("dlg.palette"))
        lbl_pal.setStyleSheet("color:#aaaacc; font-size:11px;")
        pal_row.addWidget(lbl_pal)
        t_swatch = QLabel("T")
        t_swatch.setFixedSize(20, 20)
        t_swatch.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t_swatch.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #888,stop:0.49 #888,stop:0.5 #fff,stop:1 #fff);"
            "border:1px solid #555; color:#000; font-size:9px; font-weight:bold;"
        )
        t_swatch.setToolTip(tr("dlg.palette_slot0_tt"))
        pal_row.addWidget(t_swatch)
        _DLG_PAL_DEFAULTS = ["0000", "0888", "0FFF"]
        _DLG_PAL_LABELS   = ["1", "2", "3"]
        _DLG_PAL_TT       = ["dlg.palette_slot1_tt", "dlg.palette_slot2_tt", "dlg.palette_slot3_tt"]
        self._pal_swatches: list[QPushButton] = []
        for i in range(3):
            btn = QPushButton(_DLG_PAL_LABELS[i])
            btn.setFixedSize(20, 20)
            btn.setToolTip(tr(_DLG_PAL_TT[i]))
            btn.setProperty("pal_idx", i + 1)
            btn.setProperty("ngpc_word", _DLG_PAL_DEFAULTS[i])
            self._apply_swatch_style(btn, _DLG_PAL_DEFAULTS[i])
            btn.clicked.connect(lambda _checked, b=btn: self._on_swatch_clicked(b))
            pal_row.addWidget(btn)
            self._pal_swatches.append(btn)
        pal_row.addStretch(1)
        rv.addLayout(pal_row)

        lbl_prev = QLabel(tr("dlg.preview"))
        lbl_prev.setStyleSheet("color:#aaaacc; font-size:11px;")
        rv.addWidget(lbl_prev)

        self._preview = _NgpcDialogPreview()
        rv.addWidget(self._preview)
        rv.addStretch(1)

        self._right_stack.addWidget(page0)

        # ── Page 1: menu item editor ──────────────────────────────────
        page1 = QWidget()
        mv = QVBoxLayout(page1)
        mv.setContentsMargins(6, 0, 0, 0)
        mv.setSpacing(4)

        lbl_mitems = QLabel(tr("dlg.menu_items"))
        lbl_mitems.setStyleSheet("color:#ccccdd; font-weight:bold; font-size:12px;")
        mv.addWidget(lbl_mitems)

        self._list_menu_items = QListWidget()
        self._list_menu_items.setStyleSheet(
            "QListWidget { background:#1e1e28; color:#ccccdd; border:1px solid #333; }"
            "QListWidget::item:selected { background:#3a3a55; }"
        )
        self._list_menu_items.currentRowChanged.connect(self._on_menu_item_selected)
        mv.addWidget(self._list_menu_items, 1)

        item_btns = QHBoxLayout()
        item_btns.setSpacing(4)
        self._btn_add_item = QPushButton("+")
        self._btn_add_item.setFixedWidth(32)
        self._btn_add_item.setToolTip(tr("dlg.add_item_tt"))
        self._btn_add_item.clicked.connect(self._on_add_menu_item)
        self._btn_del_item = QPushButton("−")
        self._btn_del_item.setFixedWidth(32)
        self._btn_del_item.setToolTip(tr("dlg.del_item_tt"))
        self._btn_del_item.clicked.connect(self._on_del_menu_item)
        self._btn_up_item = QPushButton("↑")
        self._btn_up_item.setFixedWidth(32)
        self._btn_up_item.clicked.connect(self._on_move_item_up)
        self._btn_dn_item = QPushButton("↓")
        self._btn_dn_item.setFixedWidth(32)
        self._btn_dn_item.clicked.connect(self._on_move_item_dn)
        item_btns.addWidget(self._btn_add_item)
        item_btns.addWidget(self._btn_del_item)
        item_btns.addWidget(self._btn_up_item)
        item_btns.addWidget(self._btn_dn_item)
        item_btns.addStretch(1)
        mv.addLayout(item_btns)

        sep_mi = QFrame()
        sep_mi.setFrameShape(QFrame.Shape.HLine)
        sep_mi.setStyleSheet("color:#444455;")
        mv.addWidget(sep_mi)

        item_form = QHBoxLayout()
        item_form.setSpacing(8)

        ilbl_col = QVBoxLayout()
        ilbl_col.setSpacing(2)
        lbl_il = QLabel(tr("dlg.item_label"))
        lbl_il.setStyleSheet("color:#aaaacc; font-size:11px;")
        ilbl_col.addWidget(lbl_il)
        self._edit_item_label = QLineEdit()
        self._edit_item_label.setMaxLength(16)
        self._edit_item_label.setPlaceholderText(tr("dlg.choice_label"))
        self._edit_item_label.setFixedWidth(110)
        self._edit_item_label.setEnabled(False)
        self._edit_item_label.textChanged.connect(self._on_item_label_changed)
        ilbl_col.addWidget(self._edit_item_label)
        item_form.addLayout(ilbl_col)

        igoto_col = QVBoxLayout()
        igoto_col.setSpacing(2)
        lbl_ig = QLabel(tr("dlg.item_goto"))
        lbl_ig.setStyleSheet("color:#aaaacc; font-size:11px;")
        igoto_col.addWidget(lbl_ig)
        self._combo_item_goto = QComboBox()
        self._combo_item_goto.setMinimumWidth(140)
        self._combo_item_goto.setToolTip(tr("dlg.choice_goto"))
        self._combo_item_goto.setEnabled(False)
        self._combo_item_goto.currentIndexChanged.connect(self._on_item_goto_changed)
        igoto_col.addWidget(self._combo_item_goto)
        item_form.addLayout(igoto_col)

        mv.addLayout(item_form)
        mv.addStretch(1)

        self._right_stack.addWidget(page1)
        self._right_stack.setCurrentIndex(0)

        splitter.addWidget(self._right_stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        self._set_editing_enabled(False)

    # ------------------------------------------------------------------
    # Public API (called from main_window._on_scene_activated)
    # ------------------------------------------------------------------

    def set_scene(self, scene: dict | None, base_dir: str, project_data: dict) -> None:
        self._scene = scene
        self._base_dir = base_dir
        self._project_data = project_data

        self._sel_dlg = -1
        self._sel_line = -1
        self._sel_menu = -1
        self._sel_menu_item = -1

        self._refresh_scene_combo()

        # Select the active scene in combo FIRST — portrait/bg combos depend on it
        if scene is not None:
            sid = str(scene.get("id") or scene.get("label") or "")
            for i in range(self._combo_scene.count()):
                if self._combo_scene.itemData(i) == sid:
                    self._combo_scene.setCurrentIndex(i)
                    break

        # Now scene is selected → _scene_sprites() returns correct data
        self._refresh_portrait_combo()
        self._refresh_bg_combo()
        self._load_palette_swatches()
        self._refresh_dlg_list()
        self._refresh_menu_list()
        self._refresh_choice_goto_combos()
        self._right_stack.setCurrentIndex(0)
        self._set_editing_enabled(False)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _current_scene_data(self) -> dict | None:
        """Return the scene dict currently selected in the combo."""
        if self._project_data is None:
            return None
        idx = self._combo_scene.currentIndex()
        if idx < 0:
            return None
        sid = self._combo_scene.itemData(idx)
        for sc in (self._project_data.get("scenes") or []):
            sc_id = str(sc.get("id") or sc.get("label") or "")
            if sc_id == sid:
                return sc
        return None

    def _get_dialogues(self, scene: dict | None = None) -> list:
        sc = scene or self._current_scene_data()
        if sc is None:
            return []
        if "dialogues" not in sc:
            sc["dialogues"] = []
        return sc["dialogues"]

    def _refresh_scene_combo(self) -> None:
        self._combo_scene.blockSignals(True)
        self._combo_scene.clear()
        if self._project_data:
            for sc in (self._project_data.get("scenes") or []):
                label = str(sc.get("label") or sc.get("id") or "")
                sid = str(sc.get("id") or label)
                self._combo_scene.addItem(label, sid)
        self._combo_scene.blockSignals(False)

    # ------------------------------------------------------------------
    # PNG helpers — load sprite pixmaps for preview
    # ------------------------------------------------------------------

    def _scene_sprites(self) -> "list[dict]":
        """Return the sprites list for the currently selected scene."""
        sc = self._current_scene_data()
        if sc is None:
            return []
        return sc.get("sprites") or []

    def _sprite_png_path(self, sprite_name: str) -> "Path | None":
        """Return absolute Path to a sprite's PNG by stem name, or None."""
        if not sprite_name:
            return None
        base = Path(self._base_dir) if self._base_dir else None
        for sp in self._scene_sprites():
            rel = str(sp.get("file") or "")
            if not rel:
                continue
            stem = Path(rel).stem
            if stem != sprite_name:
                continue
            if base is None:
                p = Path(rel)
            else:
                p = (base / rel).resolve()
            return p if p.exists() else None
        return None

    def _load_portrait_pixmap(self, sprite_name: str) -> "QPixmap | None":
        """Load first frame of portrait sprite as QPixmap, or None."""
        if not sprite_name:
            return None   # no portrait — slot hidden
        path = self._sprite_png_path(sprite_name)
        if path is None:
            return QPixmap()   # set but missing — show placeholder
        px = QPixmap(str(path))
        return px if not px.isNull() else QPixmap()

    def _load_bg_tiles(self, sprite_name: str) -> "list[QPixmap] | None":
        """
        Load 4 tiles from the 16×16 background sprite PNG.
        Returns [corner, hborder, fill, vborder_r] or None if not available.
        Tile layout:
          [0,0] corner TL   [8,0] H-border top
          [0,8] fill        [8,8] V-border right
        """
        if not sprite_name:
            return None
        path = self._sprite_png_path(sprite_name)
        if path is None:
            return None
        full = QPixmap(str(path))
        if full.isNull() or full.width() < 16 or full.height() < 16:
            return None
        def crop(x: int, y: int) -> QPixmap:
            return full.copy(x, y, 8, 8)
        return [crop(0, 0), crop(8, 0), crop(0, 8), crop(8, 8)]

    def _refresh_portrait_combo(self) -> None:
        from PyQt6.QtGui import QIcon
        self._combo_portrait.blockSignals(True)
        prev = self._combo_portrait.currentData()
        self._combo_portrait.clear()
        # Slot 0 — no portrait
        self._combo_portrait.addItem(QIcon(), tr("dlg.portrait_none"), "")
        base = Path(self._base_dir) if self._base_dir else None
        for sp in self._scene_sprites():
            rel = str(sp.get("file") or "")
            if not rel:
                continue
            stem = Path(rel).stem
            # Build 32×32 icon from PNG
            icon = QIcon()
            if base is not None:
                p = (base / rel).resolve()
                if p.exists():
                    px = QPixmap(str(p))
                    if not px.isNull():
                        thumb = px.scaled(
                            32, 32,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        icon = QIcon(thumb)
            self._combo_portrait.addItem(icon, stem, stem)
        # Restore selection by data
        idx = self._combo_portrait.findData(prev) if prev else -1
        self._combo_portrait.setCurrentIndex(idx if idx >= 0 else 0)
        self._combo_portrait.blockSignals(False)

    def _refresh_dlg_list(self) -> None:
        self._list_dlg.blockSignals(True)
        self._list_dlg.clear()
        for d in self._get_dialogues():
            self._list_dlg.addItem(str(d.get("id") or "(unnamed)"))
        self._list_dlg.blockSignals(False)
        # Restore selection
        if 0 <= self._sel_dlg < self._list_dlg.count():
            self._list_dlg.setCurrentRow(self._sel_dlg)
            self._refresh_line_list()
            self._load_on_done()
        else:
            self._sel_dlg = -1
            self._refresh_line_list()
            if hasattr(self, "_on_done_widget"):
                self._on_done_widget.setVisible(False)

    def _refresh_line_list(self) -> None:
        self._list_lines.blockSignals(True)
        self._list_lines.clear()
        dlgs = self._get_dialogues()
        if 0 <= self._sel_dlg < len(dlgs):
            for ln in (dlgs[self._sel_dlg].get("lines") or []):
                spk = str(ln.get("speaker") or "")
                txt = str(ln.get("text") or "")
                preview = f"{spk}: {txt}" if spk else txt
                n_ch = len(ln.get("choices") or [])
                if n_ch:
                    preview = f"▸ {preview}"
                self._list_lines.addItem(preview[:62])
        self._list_lines.blockSignals(False)
        if 0 <= self._sel_line < self._list_lines.count():
            self._list_lines.setCurrentRow(self._sel_line)
            self._load_line_into_form()
        else:
            self._sel_line = -1
            self._clear_form()

    def _load_line_into_form(self) -> None:
        dlgs = self._get_dialogues()
        if not (0 <= self._sel_dlg < len(dlgs)):
            return
        lines = dlgs[self._sel_dlg].get("lines") or []
        if not (0 <= self._sel_line < len(lines)):
            return
        ln = lines[self._sel_line]
        self._edit_speaker.blockSignals(True)
        self._edit_text.blockSignals(True)
        self._combo_portrait.blockSignals(True)
        self._edit_speaker.setText(str(ln.get("speaker") or ""))
        self._edit_text.setText(str(ln.get("text") or ""))
        txt = str(ln.get("text") or "")
        self._lbl_chars.setText(f"{len(txt)} / {_TEXT_MAX}")
        por = str(ln.get("portrait") or "")
        idx = self._combo_portrait.findData(por)
        if idx >= 0:
            self._combo_portrait.setCurrentIndex(idx)
        else:
            self._combo_portrait.setCurrentIndex(0)
        self._edit_speaker.blockSignals(False)
        self._edit_text.blockSignals(False)
        self._combo_portrait.blockSignals(False)
        self._load_choices_into_form()
        self._update_preview()
        self._set_editing_enabled(True)
        self._update_choices_visibility()

    def _clear_form(self) -> None:
        self._edit_speaker.blockSignals(True)
        self._edit_text.blockSignals(True)
        self._edit_speaker.setText("")
        self._edit_text.setText("")
        self._lbl_chars.setText(f"0 / {_TEXT_MAX}")
        self._edit_speaker.blockSignals(False)
        self._edit_text.blockSignals(False)
        self._preview.set_line("", "")
        self._set_editing_enabled(False)

    def _update_preview(self) -> None:
        spk = self._edit_speaker.text()
        txt = self._edit_text.text()
        por_name = self._combo_portrait.currentData() or ""
        sc = self._current_scene_data()
        bg_name = str((sc.get("dialogue_config") or {}).get("bg_sprite") or "") if sc else ""
        portrait_px = self._load_portrait_pixmap(por_name)
        bg_tiles    = self._load_bg_tiles(bg_name)
        pal         = self._current_palette()
        self._preview.set_line(spk, txt, portrait_px, bg_tiles, pal)

    def _update_portrait_thumb(self, por_name: str,
                               portrait_px: "QPixmap | None") -> None:
        """Update the 32×32 thumbnail next to the portrait combo."""
        lbl = self._lbl_portrait_thumb
        if not por_name:
            lbl.clear()
            lbl.setToolTip("")
            return
        if portrait_px is None or portrait_px.isNull():
            lbl.clear()
            lbl.setText("?")
            lbl.setToolTip(tr("dlg.portrait_missing").format(name=por_name))
            return
        thumb = portrait_px.scaled(
            32, 32,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        lbl.setPixmap(thumb)
        lbl.setToolTip(por_name)

    def _set_editing_enabled(self, enabled: bool) -> None:
        for w in (self._edit_speaker, self._edit_text, self._combo_portrait,
                  self._btn_del_line, self._btn_up_line, self._btn_dn_line,
                  self._btn_add_choice, self._btn_del_choice):
            w.setEnabled(enabled)
        if not enabled:
            for crow_w, _le, _cb in self._choice_rows:
                crow_w.setVisible(False)
            self._lbl_choices.setText(tr("dlg.choices").format(n=0))

    def _refresh_bg_combo(self) -> None:
        """Rebuild background sprite combo; restore saved value for current scene."""
        self._combo_bg.blockSignals(True)
        prev = self._combo_bg.currentData() or ""
        self._combo_bg.clear()
        self._combo_bg.addItem(tr("dlg.bg_none"), "")
        for sp in self._scene_sprites():
            stem = Path(str(sp.get("file") or "")).stem
            if stem:
                self._combo_bg.addItem(stem, stem)
        # Load saved value from scene dialogue_config
        sc = self._current_scene_data()
        saved = ""
        if sc is not None:
            saved = str((sc.get("dialogue_config") or {}).get("bg_sprite") or "")
        target = saved or prev
        idx = self._combo_bg.findData(target) if target else 0
        self._combo_bg.setCurrentIndex(idx if idx >= 0 else 0)
        self._combo_bg.blockSignals(False)

        # Sync full_screen checkbox
        self._chk_full_screen.blockSignals(True)
        fs = bool((sc.get("dialogue_config") or {}).get("full_screen") or False) if sc else False
        self._chk_full_screen.setChecked(fs)
        self._chk_full_screen.blockSignals(False)

    def _on_bg_changed(self, _idx: int) -> None:
        sc = self._current_scene_data()
        if sc is None:
            return
        cfg = sc.setdefault("dialogue_config", {})
        cfg["bg_sprite"] = self._combo_bg.currentData() or ""
        self._update_preview()
        self._mark_dirty()

    def _on_full_screen_changed(self, _state: int) -> None:
        sc = self._current_scene_data()
        if sc is None:
            return
        cfg = sc.setdefault("dialogue_config", {})
        cfg["full_screen"] = self._chk_full_screen.isChecked()
        self._mark_dirty()

    # ------------------------------------------------------------------
    # Palette helpers
    # ------------------------------------------------------------------

    _DLG_PAL_DEFAULTS = ["0000", "0888", "0FFF"]

    @staticmethod
    def _ngpc_word_to_qcolor(word_hex: str) -> "QColor":
        """Convert a 3-hex-digit NGPC RGB444 word (e.g. '0FFF') to QColor."""
        try:
            w = int(word_hex, 16) & 0x0FFF
        except (ValueError, TypeError):
            w = 0
        r4 = (w >> 0) & 0xF
        g4 = (w >> 4) & 0xF
        b4 = (w >> 8) & 0xF
        return QColor(r4 * 17, g4 * 17, b4 * 17)

    @staticmethod
    def _qcolor_to_ngpc_word(c: "QColor") -> str:
        """Snap QColor to nearest RGB444 and return 3-hex-digit word string."""
        r4 = c.red()   >> 4
        g4 = c.green() >> 4
        b4 = c.blue()  >> 4
        return f"{r4 | (g4 << 4) | (b4 << 8):04X}"

    def _apply_swatch_style(self, btn: "QPushButton", word_hex: str) -> None:
        c = self._ngpc_word_to_qcolor(word_hex)
        luma = c.red() * 299 + c.green() * 587 + c.blue() * 114
        txt_col = "#000000" if luma > 128000 else "#ffffff"
        btn.setStyleSheet(
            f"QPushButton {{ background:{c.name()}; color:{txt_col};"
            f" border:1px solid #555; font-size:9px; font-weight:bold; }}"
            f"QPushButton:hover {{ border:1px solid #aaa; }}"
        )
        btn.setToolTip(f"0x{word_hex}  RGB({c.red()},{c.green()},{c.blue()})")
        btn.setProperty("ngpc_word", word_hex)

    def _load_palette_swatches(self) -> None:
        """Read saved palette from current scene config and update swatches."""
        sc = self._current_scene_data()
        pal = list((sc.get("dialogue_config") or {}).get("palette") or []) if sc else []
        # Pad / truncate to 3 entries (slots 1-3)
        while len(pal) < 3:
            pal.append(self._DLG_PAL_DEFAULTS[len(pal)])
        for i, btn in enumerate(self._pal_swatches):
            self._apply_swatch_style(btn, pal[i])

    def _on_swatch_clicked(self, btn: "QPushButton") -> None:
        from PyQt6.QtWidgets import QColorDialog
        word = str(btn.property("ngpc_word") or "0000")
        initial = self._ngpc_word_to_qcolor(word)
        chosen = QColorDialog.getColor(initial, self, tr("dlg.palette_pick_title"))
        if not chosen.isValid():
            return
        # Snap to RGB444
        new_word = self._qcolor_to_ngpc_word(chosen)
        self._apply_swatch_style(btn, new_word)
        # Save to scene config
        sc = self._current_scene_data()
        if sc is None:
            return
        cfg = sc.setdefault("dialogue_config", {})
        pal = list(cfg.get("palette") or self._DLG_PAL_DEFAULTS[:])
        while len(pal) < 3:
            pal.append(self._DLG_PAL_DEFAULTS[len(pal)])
        idx = int(btn.property("pal_idx") or 1) - 1   # 0-based in list
        pal[idx] = new_word
        cfg["palette"] = pal
        self._update_preview()
        self._mark_dirty()

    def _current_palette(self) -> "list[str]":
        """Return [word1, word2, word3] for slots 1-3 (slot 0 = transparent)."""
        sc = self._current_scene_data()
        pal = list((sc.get("dialogue_config") or {}).get("palette") or []) if sc else []
        while len(pal) < 3:
            pal.append(self._DLG_PAL_DEFAULTS[len(pal)])
        return pal[:3]

    def _mark_dirty(self) -> None:
        """Immediate save — use for structural changes (add/del/rename/reorder).
        Does NOT emit scene_modified — dialogue data is self-contained and does
        not affect other tabs (level, tilemap, etc.)."""
        self._save_timer.stop()
        self._flush_save()

    def _mark_dirty_text(self) -> None:
        """Debounced save — use for text field changes to avoid save-on-every-keystroke.
        Does NOT emit scene_modified (no UI reload) — just writes to disk silently."""
        self._save_timer.start()

    def _flush_save(self) -> None:
        # Write to disk only — do NOT emit scene_modified here, that would
        # call set_scene on all tabs and reset the dialogue selection mid-typing.
        if self._on_save:
            self._on_save()

    # ------------------------------------------------------------------
    # Slot handlers — dialogue list
    # ------------------------------------------------------------------

    def _on_scene_changed(self, _idx: int) -> None:
        self._sel_dlg = -1
        self._sel_line = -1
        self._sel_menu = -1
        self._sel_menu_item = -1
        self._refresh_portrait_combo()
        self._refresh_bg_combo()
        self._load_palette_swatches()
        self._refresh_dlg_list()
        self._refresh_menu_list()
        self._refresh_choice_goto_combos()
        self._right_stack.setCurrentIndex(0)
        self._clear_form()

    def _on_dlg_selected(self, row: int) -> None:
        if row < 0:
            return
        self._sel_dlg = row
        self._sel_line = -1
        # Deselect menus when a dialogue is selected
        self._list_menus.blockSignals(True)
        self._list_menus.setCurrentRow(-1)
        self._list_menus.blockSignals(False)
        self._sel_menu = -1
        self._right_stack.setCurrentIndex(0)
        self._refresh_line_list()
        self._load_on_done()
        self._set_editing_enabled(False)

    def _on_add_dlg(self) -> None:
        sc = self._current_scene_data()
        if sc is None:
            return
        dlgs = self._get_dialogues(sc)
        new_id = f"dlg_{len(dlgs):02d}"
        dlgs.append({"id": new_id, "lines": []})
        self._sel_dlg = len(dlgs) - 1
        self._refresh_dlg_list()
        self._list_dlg.setCurrentRow(self._sel_dlg)
        self._refresh_choice_goto_combos()
        self._refresh_item_goto_combo()
        self._mark_dirty()

    def _on_del_dlg(self) -> None:
        sc = self._current_scene_data()
        if sc is None:
            return
        dlgs = self._get_dialogues(sc)
        if not (0 <= self._sel_dlg < len(dlgs)):
            return
        name = dlgs[self._sel_dlg].get("id", "")
        reply = QMessageBox.question(
            self, tr("dlg.confirm_delete_title"),
            tr("dlg.confirm_delete_msg").format(name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        dlgs.pop(self._sel_dlg)
        self._sel_dlg = max(0, self._sel_dlg - 1)
        self._sel_line = -1
        self._refresh_dlg_list()
        self._refresh_choice_goto_combos()
        self._refresh_item_goto_combo()
        self._mark_dirty()

    def _on_rename_dlg(self) -> None:
        sc = self._current_scene_data()
        if sc is None:
            return
        dlgs = self._get_dialogues(sc)
        if not (0 <= self._sel_dlg < len(dlgs)):
            return
        from PyQt6.QtWidgets import QInputDialog
        old = str(dlgs[self._sel_dlg].get("id") or "")
        new_id, ok = QInputDialog.getText(
            self, tr("dlg.rename_title"), tr("dlg.rename_label"), text=old
        )
        if not ok or not new_id.strip():
            return
        dlgs[self._sel_dlg]["id"] = _safe_id(new_id.strip())
        self._refresh_dlg_list()
        self._list_dlg.setCurrentRow(self._sel_dlg)
        self._refresh_choice_goto_combos()
        self._refresh_item_goto_combo()
        self._mark_dirty()

    # ------------------------------------------------------------------
    # Slot handlers — line list
    # ------------------------------------------------------------------

    def _on_line_selected(self, row: int) -> None:
        self._sel_line = row
        if row >= 0:
            self._load_line_into_form()
            self._set_editing_enabled(True)
        else:
            self._clear_form()

    def _on_add_line(self) -> None:
        sc = self._current_scene_data()
        if sc is None:
            return
        dlgs = self._get_dialogues(sc)
        if not (0 <= self._sel_dlg < len(dlgs)):
            return
        lines = dlgs[self._sel_dlg].setdefault("lines", [])
        lines.append({"speaker": "", "text": "", "portrait": ""})
        self._sel_line = len(lines) - 1
        self._refresh_line_list()
        self._list_lines.setCurrentRow(self._sel_line)
        self._edit_speaker.setFocus()
        self._mark_dirty()

    def _on_del_line(self) -> None:
        sc = self._current_scene_data()
        if sc is None:
            return
        dlgs = self._get_dialogues(sc)
        if not (0 <= self._sel_dlg < len(dlgs)):
            return
        lines = dlgs[self._sel_dlg].get("lines") or []
        if not (0 <= self._sel_line < len(lines)):
            return
        lines.pop(self._sel_line)
        self._sel_line = max(0, self._sel_line - 1)
        self._refresh_line_list()
        self._mark_dirty()

    def _on_move_line_up(self) -> None:
        self._swap_lines(self._sel_line, self._sel_line - 1)

    def _on_move_line_dn(self) -> None:
        self._swap_lines(self._sel_line, self._sel_line + 1)

    def _swap_lines(self, a: int, b: int) -> None:
        sc = self._current_scene_data()
        if sc is None:
            return
        dlgs = self._get_dialogues(sc)
        if not (0 <= self._sel_dlg < len(dlgs)):
            return
        lines = dlgs[self._sel_dlg].get("lines") or []
        if not (0 <= a < len(lines) and 0 <= b < len(lines)):
            return
        lines[a], lines[b] = lines[b], lines[a]
        self._sel_line = b
        self._refresh_line_list()
        self._list_lines.setCurrentRow(self._sel_line)
        self._mark_dirty()

    # ------------------------------------------------------------------
    # Slot handlers — form fields
    # ------------------------------------------------------------------

    def _on_speaker_changed(self, text: str) -> None:
        self._write_field("speaker", text, debounce=True)
        self._update_preview()
        self._refresh_line_label()

    def _on_text_changed(self, text: str) -> None:
        self._write_field("text", text, debounce=True)
        self._lbl_chars.setText(f"{len(text)} / {_TEXT_MAX}")
        c = "#dd4444" if len(text) > _TEXT_MAX else "#666688"
        self._lbl_chars.setStyleSheet(f"color:{c}; font-size:10px;")
        self._update_preview()
        self._refresh_line_label()

    def _on_portrait_changed(self, _idx: int) -> None:
        por = self._combo_portrait.currentData() or ""
        self._write_field("portrait", por)
        self._update_preview()

    def _write_field(self, key: str, value: str, debounce: bool = False) -> None:
        sc = self._current_scene_data()
        if sc is None:
            return
        dlgs = self._get_dialogues(sc)
        if not (0 <= self._sel_dlg < len(dlgs)):
            return
        lines = dlgs[self._sel_dlg].get("lines") or []
        if not (0 <= self._sel_line < len(lines)):
            return
        lines[self._sel_line][key] = value
        if debounce:
            self._mark_dirty_text()
        else:
            self._mark_dirty()

    def _refresh_line_label(self) -> None:
        if not (0 <= self._sel_line < self._list_lines.count()):
            return
        spk = self._edit_speaker.text()
        txt = self._edit_text.text()
        preview = f"{spk}: {txt}" if spk else txt
        n_ch = self._n_choices()
        if n_ch:
            preview = f"▸ {preview}"
        item = self._list_lines.item(self._sel_line)
        if item:
            item.setText(preview[:62])

    # ------------------------------------------------------------------
    # Choices in dialogue lines
    # ------------------------------------------------------------------

    def _n_choices(self) -> int:
        dlgs = self._get_dialogues()
        if not (0 <= self._sel_dlg < len(dlgs)):
            return 0
        lines = dlgs[self._sel_dlg].get("lines") or []
        if not (0 <= self._sel_line < len(lines)):
            return 0
        return len(lines[self._sel_line].get("choices") or [])

    def _update_choices_visibility(self) -> None:
        n = self._n_choices()
        self._lbl_choices.setText(tr("dlg.choices").format(n=n))
        self._btn_add_choice.setEnabled(n < 2)
        self._btn_del_choice.setEnabled(n > 0)
        for i, (crow_w, _le, _cb) in enumerate(self._choice_rows):
            crow_w.setVisible(i < n)

    def _load_choices_into_form(self) -> None:
        dlgs = self._get_dialogues()
        if not (0 <= self._sel_dlg < len(dlgs)):
            return
        lines = dlgs[self._sel_dlg].get("lines") or []
        if not (0 <= self._sel_line < len(lines)):
            return
        choices = list(lines[self._sel_line].get("choices") or [])
        for i, (crow_w, le, cb) in enumerate(self._choice_rows):
            le.blockSignals(True)
            cb.blockSignals(True)
            if i < len(choices):
                le.setText(str(choices[i].get("label") or ""))
                goto = str(choices[i].get("goto") or "")
                idx = cb.findData(goto)
                cb.setCurrentIndex(idx if idx >= 0 else 0)
            else:
                le.setText("")
                cb.setCurrentIndex(0)
            le.blockSignals(False)
            cb.blockSignals(False)

    def _refresh_choice_goto_combos(self) -> None:
        """Rebuild goto combos in choice rows from current scene dialogues."""
        sc = self._current_scene_data()
        dlg_ids = [str(d.get("id") or "") for d in (sc.get("dialogues") or [] if sc else []) if d.get("id")]
        for _crow_w, _le, cb in self._choice_rows:
            prev = str(cb.currentData() or "")
            cb.blockSignals(True)
            cb.clear()
            cb.addItem(tr("dlg.choice_goto_none"), "")
            for did in dlg_ids:
                cb.addItem(did, did)
            idx = cb.findData(prev) if prev else 0
            cb.setCurrentIndex(idx if idx >= 0 else 0)
            cb.blockSignals(False)
        self._refresh_on_done_combo()

    # ------------------------------------------------------------------
    # On Done helpers
    # ------------------------------------------------------------------

    def _refresh_on_done_combo(self) -> None:
        """Rebuild the next-dialogue combo for on_done=next_dlg."""
        if not hasattr(self, "_on_done_dlg_cb"):
            return
        sc = self._current_scene_data()
        dlg_ids = [str(d.get("id") or "") for d in (sc.get("dialogues") or [] if sc else []) if d.get("id")]
        prev = str(self._on_done_dlg_cb.currentData() or "")
        self._on_done_dlg_cb.blockSignals(True)
        self._on_done_dlg_cb.clear()
        for did in dlg_ids:
            self._on_done_dlg_cb.addItem(did, did)
        idx = self._on_done_dlg_cb.findData(prev)
        self._on_done_dlg_cb.setCurrentIndex(idx if idx >= 0 else 0)
        self._on_done_dlg_cb.blockSignals(False)

    def _load_on_done(self) -> None:
        """Populate on_done widgets from the currently selected dialogue."""
        if not hasattr(self, "_on_done_widget"):
            return
        dlgs = self._get_dialogues()
        if not (0 <= self._sel_dlg < len(dlgs)):
            self._on_done_widget.setVisible(False)
            return
        self._on_done_widget.setVisible(True)
        on_done = dlgs[self._sel_dlg].get("on_done") or {}
        action = str(on_done.get("action") or "close")

        self._on_done_action_cb.blockSignals(True)
        idx = self._on_done_action_cb.findData(action)
        self._on_done_action_cb.setCurrentIndex(idx if idx >= 0 else 0)
        self._on_done_action_cb.blockSignals(False)

        self._refresh_on_done_combo()

        if action == "next_dlg":
            target = str(on_done.get("id") or "")
            self._on_done_dlg_cb.blockSignals(True)
            idx2 = self._on_done_dlg_cb.findData(target)
            self._on_done_dlg_cb.setCurrentIndex(idx2 if idx2 >= 0 else 0)
            self._on_done_dlg_cb.blockSignals(False)
        elif action in ("set_flag", "emit_event"):
            self._on_done_n_sb.blockSignals(True)
            self._on_done_n_sb.setValue(int(on_done.get("n") or 0))
            self._on_done_n_sb.blockSignals(False)

        self._update_on_done_param_visibility()

    def _update_on_done_param_visibility(self) -> None:
        action = self._on_done_action_cb.currentData() or "close"
        self._on_done_dlg_cb.setVisible(action == "next_dlg")
        self._on_done_n_sb.setVisible(action in ("set_flag", "emit_event"))

    def _save_on_done(self) -> None:
        dlgs = self._get_dialogues()
        if not (0 <= self._sel_dlg < len(dlgs)):
            return
        action = self._on_done_action_cb.currentData() or "close"
        if action == "close":
            dlgs[self._sel_dlg].pop("on_done", None)
        elif action == "next_dlg":
            target = str(self._on_done_dlg_cb.currentData() or "")
            dlgs[self._sel_dlg]["on_done"] = {"action": "next_dlg", "id": target}
        elif action in ("set_flag", "emit_event"):
            dlgs[self._sel_dlg]["on_done"] = {"action": action, "n": self._on_done_n_sb.value()}
        self._mark_dirty()

    def _on_on_done_action_changed(self) -> None:
        self._update_on_done_param_visibility()
        self._save_on_done()

    def _on_on_done_param_changed(self) -> None:
        self._save_on_done()

    def _on_add_choice(self) -> None:
        dlgs = self._get_dialogues()
        if not (0 <= self._sel_dlg < len(dlgs)):
            return
        lines = dlgs[self._sel_dlg].get("lines") or []
        if not (0 <= self._sel_line < len(lines)):
            return
        choices = lines[self._sel_line].setdefault("choices", [])
        if len(choices) >= 2:
            return
        choices.append({"label": "", "goto": ""})
        self._update_choices_visibility()
        self._refresh_line_list()
        self._list_lines.setCurrentRow(self._sel_line)
        self._mark_dirty()

    def _on_del_choice(self) -> None:
        dlgs = self._get_dialogues()
        if not (0 <= self._sel_dlg < len(dlgs)):
            return
        lines = dlgs[self._sel_dlg].get("lines") or []
        if not (0 <= self._sel_line < len(lines)):
            return
        choices = lines[self._sel_line].get("choices") or []
        if not choices:
            return
        choices.pop()
        if not choices:
            lines[self._sel_line].pop("choices", None)
        self._update_choices_visibility()
        self._refresh_line_list()
        self._list_lines.setCurrentRow(self._sel_line)
        self._mark_dirty()

    def _on_choice_label_changed(self, idx: int, text: str) -> None:
        dlgs = self._get_dialogues()
        if not (0 <= self._sel_dlg < len(dlgs)):
            return
        lines = dlgs[self._sel_dlg].get("lines") or []
        if not (0 <= self._sel_line < len(lines)):
            return
        choices = lines[self._sel_line].get("choices") or []
        if 0 <= idx < len(choices):
            choices[idx]["label"] = text
        self._mark_dirty_text()

    def _on_choice_goto_changed(self, ci: int) -> None:
        dlgs = self._get_dialogues()
        if not (0 <= self._sel_dlg < len(dlgs)):
            return
        lines = dlgs[self._sel_dlg].get("lines") or []
        if not (0 <= self._sel_line < len(lines)):
            return
        choices = lines[self._sel_line].get("choices") or []
        if not (0 <= ci < len(choices)):
            return
        _crow_w, _le, cb = self._choice_rows[ci]
        choices[ci]["goto"] = str(cb.currentData() or "")
        self._mark_dirty()

    # ------------------------------------------------------------------
    # Menus
    # ------------------------------------------------------------------

    def _get_menus(self, scene: dict | None = None) -> list:
        sc = scene or self._current_scene_data()
        if sc is None:
            return []
        if "menus" not in sc:
            sc["menus"] = []
        return sc["menus"]

    def _refresh_menu_list(self) -> None:
        self._list_menus.blockSignals(True)
        self._list_menus.clear()
        for m in self._get_menus():
            n = len(m.get("items") or [])
            self._list_menus.addItem(f"{m.get('id', '?')}  ({n})")
        self._list_menus.blockSignals(False)
        if 0 <= self._sel_menu < self._list_menus.count():
            self._list_menus.setCurrentRow(self._sel_menu)

    def _on_menu_selected(self, row: int) -> None:
        if row < 0:
            return
        self._sel_menu = row
        self._sel_menu_item = -1
        # Deselect dialogue list
        self._list_dlg.blockSignals(True)
        self._list_dlg.setCurrentRow(-1)
        self._list_dlg.blockSignals(False)
        self._sel_dlg = -1
        self._refresh_item_goto_combo()
        self._refresh_menu_item_list()
        self._right_stack.setCurrentIndex(1)

    def _refresh_menu_item_list(self) -> None:
        self._list_menu_items.blockSignals(True)
        self._list_menu_items.clear()
        menus = self._get_menus()
        if 0 <= self._sel_menu < len(menus):
            for it in (menus[self._sel_menu].get("items") or []):
                label = str(it.get("label") or "")
                goto  = str(it.get("goto")  or "")
                self._list_menu_items.addItem(f"{label}  → {goto}" if goto else label)
        self._list_menu_items.blockSignals(False)
        if 0 <= self._sel_menu_item < self._list_menu_items.count():
            self._list_menu_items.setCurrentRow(self._sel_menu_item)
            self._load_menu_item_form()
        else:
            self._sel_menu_item = -1
            self._clear_menu_item_form()

    def _load_menu_item_form(self) -> None:
        menus = self._get_menus()
        if not (0 <= self._sel_menu < len(menus)):
            return
        items = menus[self._sel_menu].get("items") or []
        if not (0 <= self._sel_menu_item < len(items)):
            return
        it = items[self._sel_menu_item]
        self._edit_item_label.blockSignals(True)
        self._combo_item_goto.blockSignals(True)
        self._edit_item_label.setText(str(it.get("label") or ""))
        goto = str(it.get("goto") or "")
        idx = self._combo_item_goto.findData(goto)
        self._combo_item_goto.setCurrentIndex(idx if idx >= 0 else 0)
        self._edit_item_label.blockSignals(False)
        self._combo_item_goto.blockSignals(False)
        self._edit_item_label.setEnabled(True)
        self._combo_item_goto.setEnabled(True)

    def _clear_menu_item_form(self) -> None:
        self._edit_item_label.blockSignals(True)
        self._edit_item_label.setText("")
        self._edit_item_label.blockSignals(False)
        self._edit_item_label.setEnabled(False)
        self._combo_item_goto.setEnabled(False)

    def _on_menu_item_selected(self, row: int) -> None:
        self._sel_menu_item = row
        if row >= 0:
            self._load_menu_item_form()
        else:
            self._clear_menu_item_form()

    def _on_add_menu(self) -> None:
        sc = self._current_scene_data()
        if sc is None:
            return
        menus = self._get_menus(sc)
        new_id = f"menu_{len(menus):02d}"
        menus.append({"id": new_id, "items": []})
        self._sel_menu = len(menus) - 1
        self._refresh_menu_list()
        self._list_menus.setCurrentRow(self._sel_menu)
        self._mark_dirty()

    def _on_del_menu(self) -> None:
        sc = self._current_scene_data()
        if sc is None:
            return
        menus = self._get_menus(sc)
        if not (0 <= self._sel_menu < len(menus)):
            return
        name = menus[self._sel_menu].get("id", "")
        reply = QMessageBox.question(
            self, tr("dlg.confirm_delete_title"),
            tr("dlg.confirm_delete_msg").format(name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        menus.pop(self._sel_menu)
        self._sel_menu = max(0, self._sel_menu - 1)
        self._sel_menu_item = -1
        self._refresh_menu_list()
        self._mark_dirty()

    def _on_rename_menu(self) -> None:
        sc = self._current_scene_data()
        if sc is None:
            return
        menus = self._get_menus(sc)
        if not (0 <= self._sel_menu < len(menus)):
            return
        from PyQt6.QtWidgets import QInputDialog
        old = str(menus[self._sel_menu].get("id") or "")
        new_id, ok = QInputDialog.getText(
            self, tr("dlg.rename_title"), tr("dlg.rename_label"), text=old
        )
        if not ok or not new_id.strip():
            return
        menus[self._sel_menu]["id"] = _safe_id(new_id.strip())
        self._refresh_menu_list()
        self._list_menus.setCurrentRow(self._sel_menu)
        self._mark_dirty()

    def _on_add_menu_item(self) -> None:
        sc = self._current_scene_data()
        if sc is None:
            return
        menus = self._get_menus(sc)
        if not (0 <= self._sel_menu < len(menus)):
            return
        items = menus[self._sel_menu].setdefault("items", [])
        if len(items) >= 8:
            return
        items.append({"label": "", "goto": ""})
        self._sel_menu_item = len(items) - 1
        self._refresh_menu_item_list()
        self._list_menu_items.setCurrentRow(self._sel_menu_item)
        self._edit_item_label.setFocus()
        self._refresh_menu_list()
        self._mark_dirty()

    def _on_del_menu_item(self) -> None:
        sc = self._current_scene_data()
        if sc is None:
            return
        menus = self._get_menus(sc)
        if not (0 <= self._sel_menu < len(menus)):
            return
        items = menus[self._sel_menu].get("items") or []
        if not (0 <= self._sel_menu_item < len(items)):
            return
        items.pop(self._sel_menu_item)
        self._sel_menu_item = max(0, self._sel_menu_item - 1)
        self._refresh_menu_item_list()
        self._refresh_menu_list()
        self._mark_dirty()

    def _on_move_item_up(self) -> None:
        self._swap_menu_items(self._sel_menu_item, self._sel_menu_item - 1)

    def _on_move_item_dn(self) -> None:
        self._swap_menu_items(self._sel_menu_item, self._sel_menu_item + 1)

    def _swap_menu_items(self, a: int, b: int) -> None:
        sc = self._current_scene_data()
        if sc is None:
            return
        menus = self._get_menus(sc)
        if not (0 <= self._sel_menu < len(menus)):
            return
        items = menus[self._sel_menu].get("items") or []
        if not (0 <= a < len(items) and 0 <= b < len(items)):
            return
        items[a], items[b] = items[b], items[a]
        self._sel_menu_item = b
        self._refresh_menu_item_list()
        self._list_menu_items.setCurrentRow(self._sel_menu_item)
        self._mark_dirty()

    def _on_item_label_changed(self, text: str) -> None:
        sc = self._current_scene_data()
        if sc is None:
            return
        menus = self._get_menus(sc)
        if not (0 <= self._sel_menu < len(menus)):
            return
        items = menus[self._sel_menu].get("items") or []
        if not (0 <= self._sel_menu_item < len(items)):
            return
        items[self._sel_menu_item]["label"] = text
        goto = str(items[self._sel_menu_item].get("goto") or "")
        item = self._list_menu_items.item(self._sel_menu_item)
        if item:
            item.setText(f"{text}  → {goto}" if goto else text)
        self._mark_dirty_text()

    def _on_item_goto_changed(self, _idx: int) -> None:
        sc = self._current_scene_data()
        if sc is None:
            return
        menus = self._get_menus(sc)
        if not (0 <= self._sel_menu < len(menus)):
            return
        items = menus[self._sel_menu].get("items") or []
        if not (0 <= self._sel_menu_item < len(items)):
            return
        goto = str(self._combo_item_goto.currentData() or "")
        items[self._sel_menu_item]["goto"] = goto
        self._mark_dirty()

    def _refresh_item_goto_combo(self, cur_goto: str = "") -> None:
        """Populate item goto combo with dialogues from the current scene."""
        self._combo_item_goto.blockSignals(True)
        prev = cur_goto or str(self._combo_item_goto.currentData() or "")
        self._combo_item_goto.clear()
        self._combo_item_goto.addItem(tr("dlg.choice_goto_none"), "")
        sc = self._current_scene_data()
        for d in (sc.get("dialogues") or [] if sc else []):
            did = str(d.get("id") or "")
            if did:
                self._combo_item_goto.addItem(did, did)
        idx = self._combo_item_goto.findData(prev) if prev else 0
        self._combo_item_goto.setCurrentIndex(idx if idx >= 0 else 0)
        self._combo_item_goto.blockSignals(False)

    # ------------------------------------------------------------------
    # CSV Import / Export
    # ------------------------------------------------------------------

    def _on_import_csv(self) -> None:
        """
        Import CSV into the currently selected scene.

        Expected columns (order matters, header optional):
          dialogue_id, line_index, speaker, text, portrait

        If header row detected (first cell == 'dialogue_id'), it is skipped.
        Rows are grouped by dialogue_id; within each group, sorted by
        line_index (int).  Existing dialogues with the same ID are REPLACED;
        new IDs are appended.
        """
        sc = self._current_scene_data()
        if sc is None:
            QMessageBox.warning(self, tr("dlg.import_csv"),
                                tr("dlg.import_no_scene"))
            return

        path, _ = QFileDialog.getOpenFileName(
            self, tr("dlg.import_csv_title"), "",
            "CSV files (*.csv);;All files (*)"
        )
        if not path:
            return

        try:
            raw = Path(path).read_text(encoding="utf-8-sig")
        except Exception as exc:
            QMessageBox.critical(self, tr("dlg.import_csv"),
                                 f"Read error:\n{exc}")
            return

        try:
            imported = _parse_dialogue_csv(raw)
        except Exception as exc:
            QMessageBox.critical(self, tr("dlg.import_csv"),
                                 f"Parse error:\n{exc}")
            return

        if not imported:
            QMessageBox.information(self, tr("dlg.import_csv"),
                                    tr("dlg.import_empty"))
            return

        dlgs = self._get_dialogues(sc)
        # Build index of existing dialogue IDs
        existing = {d["id"]: i for i, d in enumerate(dlgs)}

        replaced = 0
        added = 0
        for dlg_id, lines in imported.items():
            new_dlg = {"id": dlg_id, "lines": lines}
            if dlg_id in existing:
                dlgs[existing[dlg_id]] = new_dlg
                replaced += 1
            else:
                dlgs.append(new_dlg)
                existing[dlg_id] = len(dlgs) - 1
                added += 1

        self._sel_dlg = 0
        self._sel_line = -1
        self._refresh_dlg_list()
        self._mark_dirty()

        QMessageBox.information(
            self, tr("dlg.import_csv"),
            tr("dlg.import_done").format(added=added, replaced=replaced),
        )

    def _on_export_csv(self) -> None:
        """Export the current scene's dialogues as CSV."""
        sc = self._current_scene_data()
        if sc is None:
            return
        dlgs = self._get_dialogues(sc)
        if not dlgs:
            QMessageBox.information(self, tr("dlg.export_csv"),
                                    tr("dlg.export_empty"))
            return

        scene_label = str(sc.get("label") or sc.get("id") or "scene")
        default_name = f"{_safe_id(scene_label)}_dialogues.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, tr("dlg.export_csv_title"), default_name,
            "CSV files (*.csv);;All files (*)"
        )
        if not path:
            return

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["dialogue_id", "line_index", "speaker", "text", "portrait"])
        for dlg in dlgs:
            did = str(dlg.get("id") or "")
            for i, ln in enumerate(dlg.get("lines") or []):
                w.writerow([
                    did, i,
                    str(ln.get("speaker") or ""),
                    str(ln.get("text") or ""),
                    str(ln.get("portrait") or ""),
                ])
        try:
            Path(path).write_text(buf.getvalue(), encoding="utf-8-sig")
            QMessageBox.information(self, tr("dlg.export_csv"),
                                    tr("dlg.export_done").format(path=path))
        except Exception as exc:
            QMessageBox.critical(self, tr("dlg.export_csv"), str(exc))


# ---------------------------------------------------------------------------
# CSV parser (standalone, no Qt dependency)
# ---------------------------------------------------------------------------

def _parse_dialogue_csv(raw: str) -> dict[str, list[dict]]:
    """
    Parse CSV text → {dialogue_id: [{"speaker":…, "text":…, "portrait":…}]}

    Columns: dialogue_id, line_index, speaker, text, portrait
    Header row (first cell == 'dialogue_id') is detected and skipped.
    Rows are sorted by line_index within each dialogue_id.
    """
    reader = csv.reader(io.StringIO(raw))
    rows = list(reader)
    if not rows:
        return {}

    # Detect header
    start = 0
    if rows and rows[0] and rows[0][0].strip().lower() in ("dialogue_id", "id"):
        start = 1

    # Collect raw rows
    buckets: dict[str, list[tuple[int, dict]]] = {}
    for row in rows[start:]:
        if len(row) < 4:
            continue
        did   = _safe_id(row[0].strip())
        try:
            idx = int(row[1].strip())
        except ValueError:
            idx = 0
        speaker  = row[2].strip()[:_SPEAKER_MAX]
        text     = row[3].strip()[:_TEXT_MAX]
        portrait = row[4].strip() if len(row) > 4 else ""
        if not did:
            continue
        buckets.setdefault(did, []).append(
            (idx, {"speaker": speaker, "text": text, "portrait": portrait})
        )

    # Sort by line_index, keep insertion order of dialogue IDs
    result: dict[str, list[dict]] = {}
    for did, items in buckets.items():
        items.sort(key=lambda t: t[0])
        result[did] = [ln for _, ln in items]
    return result
