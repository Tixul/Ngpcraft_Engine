"""
ui/tabs/vram_tab.py - VRAM usage visualization (Phase 2c).

Shows:
- 512-tile grid colored by allocation (reserved / sysfont / sprites)
- palette-slot bars (sprites + BG scroll planes)
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QRect, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QGroupBox, QHBoxLayout, QLabel, QScrollArea,
    QPushButton, QVBoxLayout, QWidget,
)

from core.project_model import (
    TILE_MAX, TILE_RESERVED, TILE_USER_START, PAL_MAX_SPR, PAL_MAX_BG,
    analyze_scene_bg_palette_banks,
    build_scene_vram_usage,
)
from i18n.lang import tr
from ui.context_help import ContextHelpBox

_COL_FREE     = QColor(30,  30,  40)
_COL_RESERVED = QColor(55,  55,  65)
_COL_SYSFONT  = QColor(85,  85,  95)
_COL_SPR      = QColor(86, 156, 214)
_COL_TM       = QColor(78, 201, 176)
_COL_CONFLICT = QColor(244, 71, 71)
_COL_PAL_FREE = QColor(40,  40,  50)
_COL_BORDER   = QColor(0,   0,   0)


def _word_to_rgb(word: int) -> tuple[int, int, int]:
    """Convert NGPC RGB444 word (r4 | g4<<4 | b4<<8) to 8-bit RGB for display."""
    r4 = word & 0xF
    g4 = (word >> 4) & 0xF
    b4 = (word >> 8) & 0xF
    return (r4 * 17, g4 * 17, b4 * 17)


# ---------------------------------------------------------------------------
# Tile grid widget
# ---------------------------------------------------------------------------

class _TileMapWidget(QWidget):
    """Compact 512-slot tile occupancy widget used by the VRAM tab."""

    COLS = 32
    ROWS = 16
    CW   = 18
    CH   = 10

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._usage: list[tuple[int, int, int] | None] = [None] * TILE_MAX
        self._names: list[str | None] = [None] * TILE_MAX
        self.setFixedSize(self.COLS * self.CW + 2, self.ROWS * self.CH + 2)
        self.setMouseTracking(True)

    def set_usage(self, usage: list, names: list | None = None) -> None:
        self._usage = usage[:]
        self._names = names[:] if names else [None] * TILE_MAX
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setPen(_COL_BORDER)
        for i in range(TILE_MAX):
            row, col = divmod(i, self.COLS)
            x = col * self.CW + 1
            y = row * self.CH + 1
            if i < TILE_RESERVED:
                c = _COL_RESERVED
            elif i < TILE_USER_START:
                c = _COL_SYSFONT
            elif i < len(self._usage) and self._usage[i] is not None:
                c = QColor(*self._usage[i])
            else:
                c = _COL_FREE
            p.fillRect(x, y, self.CW - 1, self.CH - 1, c)
        p.end()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        col = (event.pos().x() - 1) // self.CW
        row = (event.pos().y() - 1) // self.CH
        idx = row * self.COLS + col
        if 0 <= idx < TILE_MAX:
            if idx < TILE_RESERVED:
                tip = tr("vram.tt_reserved", i=idx)
            elif idx < TILE_USER_START:
                tip = tr("vram.tt_sysfont", i=idx)
            elif idx < len(self._names) and self._names[idx] is not None:
                tip = tr("vram.tt_used", i=idx, name=self._names[idx])
            else:
                tip = tr("vram.tt_free", i=idx)
            self.setToolTip(tip)
        super().mouseMoveEvent(event)


# ---------------------------------------------------------------------------
# Palette bar widget
# ---------------------------------------------------------------------------

class _PaletteBarWidget(QWidget):
    """Simple horizontal palette-slot usage bar for one hardware bank."""

    SW = 34
    SH = 30

    def __init__(self, max_slots: int, used_color: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._max = int(max_slots)
        self._used = 0
        self._used_color = used_color
        self.setFixedHeight(self.SH + 6)
        self.setMinimumWidth(self._max * self.SW + 2)

    def set_used(self, n: int) -> None:
        self._used = n
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setPen(_COL_BORDER)
        for i in range(self._max):
            x = i * self.SW + 1
            y = 3
            c = self._used_color if i < self._used else _COL_PAL_FREE
            p.fillRect(x, y, self.SW - 1, self.SH - 1, c)
            p.setPen(QColor(200, 200, 200) if i < self._used else QColor(80, 80, 80))
            p.drawText(QRect(x, y, self.SW - 1, self.SH - 1),
                       Qt.AlignmentFlag.AlignCenter, str(i))
            p.setPen(_COL_BORDER)
        p.end()


# ---------------------------------------------------------------------------
# Palette bank widget (sprite slots — rich swatches)
# ---------------------------------------------------------------------------

class _PaletteBankWidget(QWidget):
    """Shows up to 16 sprite palette slots with 4-color swatches, tooltips and click-to-open."""
    SW = 38   # slot width
    SH = 48   # slot height
    NR = 12   # top row height (slot number + badge)

    slot_clicked = pyqtSignal(int)  # slot index

    def __init__(self, max_slots: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._max = int(max_slots)
        self._slots: list[dict | None] = [None] * self._max
        self.setFixedHeight(self.SH + 6)
        self.setMinimumWidth(self._max * self.SW + 2)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

    def set_slots(self, slots: list[dict | None]) -> None:
        n = len(slots)
        self._slots = list(slots[:self._max]) + [None] * max(0, self._max - n)
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        small_font = QFont(p.font())
        small_font.setPointSize(max(6, p.font().pointSize() - 2))
        p.setFont(small_font)

        for i in range(self._max):
            slot = self._slots[i] if i < len(self._slots) else None
            x = i * self.SW + 1
            y = 3

            if slot is None:
                # Free slot: uniform dark background + grey number
                p.fillRect(x, y, self.SW - 1, self.SH - 1, _COL_PAL_FREE)
                p.setPen(QColor(70, 70, 80))
                p.drawText(QRect(x, y, self.SW - 1, self.NR - 1),
                           Qt.AlignmentFlag.AlignCenter, str(i))
            else:
                # Used slot: dark header row + 4 color swatches
                p.fillRect(x, y, self.SW - 1, self.NR - 1, QColor(45, 45, 58))

                # Slot number (left side of header)
                names = slot.get("names", [])
                p.setPen(QColor(200, 200, 200))
                num_w = self.SW // 2
                p.drawText(QRect(x + 1, y, num_w - 1, self.NR - 1),
                           Qt.AlignmentFlag.AlignCenter, str(i))

                # Shared badge: "×N" on the right side of header
                if len(names) > 1:
                    p.setPen(QColor(255, 210, 70))
                    badge = f"\u00d7{len(names)}"
                    p.drawText(QRect(x + num_w, y, self.SW - num_w - 2, self.NR - 1),
                               Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, badge)

                # 4 color swatches below the header
                words = slot.get("words", [0, 0, 0, 0])
                sw_w = (self.SW - 1) // 4
                sw_h = self.SH - self.NR - 1
                sy = y + self.NR
                for ci in range(4):
                    sx = x + ci * sw_w
                    word = words[ci] if ci < len(words) else 0
                    if word == 0:
                        swatch_col = QColor(22, 22, 30)   # transparent / empty
                    else:
                        r8, g8, b8 = _word_to_rgb(word)
                        swatch_col = QColor(r8, g8, b8)
                    p.fillRect(sx, sy, sw_w, sw_h, swatch_col)
                    if ci > 0:
                        p.setPen(QColor(0, 0, 0))
                        p.drawLine(sx, sy, sx, sy + sw_h - 1)

            # Slot border
            p.setPen(QColor(0, 0, 0))
            p.drawRect(x, y, self.SW - 1, self.SH - 1)

        p.end()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        i = (event.pos().x() - 1) // self.SW
        if 0 <= i < self._max:
            slot = self._slots[i] if i < len(self._slots) else None
            if slot is None:
                self.setToolTip(tr("vram.pal_slot_free", i=i))
            else:
                names = slot.get("names", [])
                tip_names = "\n".join(names[:8])
                if len(names) > 8:
                    tip_names += f"\n... (+{len(names) - 8})"
                self.setToolTip(tr("vram.pal_slot_tip", i=i, names=tip_names))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            i = (event.pos().x() - 1) // self.SW
            if 0 <= i < self._max:
                slot = self._slots[i] if i < len(self._slots) else None
                if slot is not None:
                    self.slot_clicked.emit(i)
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# VramTab
# ---------------------------------------------------------------------------

class VramTab(QWidget):
    """Visualize tile and palette allocation for the current project or scene."""

    scene_modified = pyqtSignal(object)        # dict payload (scene)
    open_sprite_in_palette = pyqtSignal(object)  # dict payload {path, frame_w, ...}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project_data: dict | None = None
        self._base_dir: Path | None = None
        self._active_scene_id: str | None = None
        self._scenes: list[dict] = []
        self._current_scene: dict | None = None
        self._suggest_spr_tile_base: int | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        self._ctx_vram = ContextHelpBox(
            tr("vram.ctx_workflow_title"),
            tr("vram.ctx_workflow_body"),
            self,
        )
        root.addWidget(self._ctx_vram)

        top = QHBoxLayout()
        top.addWidget(QLabel(tr("vram.scene_label")))
        self._scene_pick = QComboBox()
        self._scene_pick.currentIndexChanged.connect(self._on_scene_changed)
        top.addWidget(self._scene_pick, 1)
        root.addLayout(top)

        # Tile map
        tile_g = QGroupBox(tr("vram.tiles_group"))
        tile_l = QVBoxLayout(tile_g)

        legend = QHBoxLayout()
        for col, text in (
            (_COL_RESERVED, tr("vram.legend_reserved")),
            (_COL_SYSFONT,  tr("vram.legend_sysfont")),
            (_COL_SPR,      tr("vram.legend_sprites")),
            (_COL_TM,       tr("vram.legend_tilemaps")),
            (_COL_CONFLICT, tr("vram.legend_conflict")),
            (_COL_FREE,     tr("vram.legend_free")),
        ):
            dot = QLabel("■")
            dot.setStyleSheet(f"color: rgb({col.red()},{col.green()},{col.blue()});")
            legend.addWidget(dot)
            legend.addWidget(QLabel(text))
            legend.addSpacing(12)
        legend.addStretch()
        tile_l.addLayout(legend)

        tile_scroll = QScrollArea()
        tile_scroll.setWidgetResizable(False)
        self._tile_map = _TileMapWidget()
        tile_scroll.setWidget(self._tile_map)
        tile_scroll.setFixedHeight(self._tile_map.height() + 4)
        tile_l.addWidget(tile_scroll)

        self._tile_status = QLabel(tr("vram.no_project"))
        tile_l.addWidget(self._tile_status)

        # Suggestions (conflict helpers)
        self._suggest_g = QGroupBox(tr("vram.suggest_group"))
        s_l = QVBoxLayout(self._suggest_g)
        self._suggest_lbl = QLabel("")
        self._suggest_lbl.setWordWrap(True)
        s_l.addWidget(self._suggest_lbl)
        s_btns = QHBoxLayout()
        self._btn_fix_spr_base = QPushButton(tr("vram.suggest_fix_spr_base"))
        self._btn_fix_spr_base.clicked.connect(self._apply_fix_spr_base)
        s_btns.addWidget(self._btn_fix_spr_base)
        self._btn_fix_tm_pack = QPushButton(tr("vram.suggest_fix_tm_pack"))
        self._btn_fix_tm_pack.clicked.connect(self._apply_fix_tm_pack)
        s_btns.addWidget(self._btn_fix_tm_pack)
        s_btns.addStretch()
        s_l.addLayout(s_btns)
        self._suggest_g.setVisible(False)
        tile_l.addWidget(self._suggest_g)
        root.addWidget(tile_g)

        # Palette bars
        pal_g = QGroupBox(tr("vram.pals_group"))
        pal_l = QVBoxLayout(pal_g)

        pal_l.addWidget(QLabel(tr("vram.pals_spr")))
        self._pal_spr = _PaletteBankWidget(PAL_MAX_SPR)
        self._pal_spr.slot_clicked.connect(self._on_pal_slot_clicked)
        pal_l.addWidget(self._pal_spr)
        self._pal_spr_status = QLabel("")
        pal_l.addWidget(self._pal_spr_status)
        self._pal_slot_data: list[dict | None] = [None] * PAL_MAX_SPR

        pal_l.addSpacing(6)
        pal_l.addWidget(QLabel(tr("vram.pals_bg1")))
        self._pal_bg1 = _PaletteBarWidget(PAL_MAX_BG, _COL_TM)
        pal_l.addWidget(self._pal_bg1)
        self._pal_bg1_status = QLabel("")
        pal_l.addWidget(self._pal_bg1_status)
        self._pal_bg1_analysis = QLabel("")
        self._pal_bg1_analysis.setWordWrap(True)
        self._pal_bg1_analysis.setStyleSheet("color: #aaa; font-size: 10px;")
        pal_l.addWidget(self._pal_bg1_analysis)

        pal_l.addSpacing(6)
        pal_l.addWidget(QLabel(tr("vram.pals_bg2")))
        self._pal_bg2 = _PaletteBarWidget(PAL_MAX_BG, QColor(197, 134, 192))
        pal_l.addWidget(self._pal_bg2)
        self._pal_bg2_status = QLabel("")
        pal_l.addWidget(self._pal_bg2_status)
        self._pal_bg2_analysis = QLabel("")
        self._pal_bg2_analysis.setWordWrap(True)
        self._pal_bg2_analysis.setStyleSheet("color: #aaa; font-size: 10px;")
        pal_l.addWidget(self._pal_bg2_analysis)

        root.addWidget(pal_g)

        root.addStretch()

    def set_scene(self, scene: dict | None, base_dir: Path | None) -> None:
        """Select the scene that should stay highlighted in the VRAM view."""
        self._active_scene_id = str(scene.get("id")) if isinstance(scene, dict) and scene.get("id") is not None else None
        if base_dir is not None:
            self._base_dir = base_dir
        self._reselect_active_scene()

    def refresh(self, project_data: dict, project_path: Path | None = None) -> None:
        """Rebuild the VRAM view from the latest project data snapshot."""
        self._project_data = project_data
        self._base_dir = project_path.parent if project_path else self._base_dir
        self._scenes = list(project_data.get("scenes", []) or [])
        self._rebuild_scene_picker()
        self._render_current_scene()

    def _rebuild_scene_picker(self) -> None:
        self._scene_pick.blockSignals(True)
        self._scene_pick.clear()
        self._scene_pick.addItem(tr("vram.scene_worst"), "__worst__")
        for s in self._scenes:
            sid = str(s.get("id", ""))
            label = str(s.get("label", sid or "?"))
            self._scene_pick.addItem(label, sid)
        self._scene_pick.blockSignals(False)
        self._reselect_active_scene()

    def _reselect_active_scene(self) -> None:
        if getattr(self, "_scene_pick", None) is None:
            return
        if self._active_scene_id:
            idx = self._scene_pick.findData(self._active_scene_id)
            if idx >= 0:
                self._scene_pick.setCurrentIndex(idx)
                return
        if self._scene_pick.count() > 0 and self._scene_pick.currentIndex() < 0:
            self._scene_pick.setCurrentIndex(0)

    def _on_scene_changed(self, _idx: int) -> None:
        self._render_current_scene()

    def _render_current_scene(self) -> None:
        if not self._project_data or not self._scenes:
            self._tile_map.set_usage([None] * TILE_MAX, [None] * TILE_MAX)
            self._tile_status.setText(tr("vram.no_project"))
            self._suggest_g.setVisible(False)
            self._current_scene = None
            self._pal_slot_data = [None] * PAL_MAX_SPR
            self._pal_spr.set_slots(self._pal_slot_data)
            self._pal_bg1.set_used(0)
            self._pal_bg2.set_used(0)
            self._pal_spr_status.setText("")
            self._pal_bg1_status.setText("")
            self._pal_bg2_status.setText("")
            self._pal_bg1_analysis.setText("")
            self._pal_bg2_analysis.setText("")
            return

        pick = str(self._scene_pick.currentData() or "__worst__")
        scene = None
        if pick == "__worst__":
            best = None
            best_score = -1
            for s in self._scenes:
                u, _n, st = build_scene_vram_usage(self._project_data, s, self._base_dir)
                occupied = sum(1 for i in range(TILE_USER_START, TILE_MAX) if u[i] is not None)
                score = occupied
                if st.tile_overflow or st.tile_conflict:
                    score += 10000
                if score > best_score:
                    best_score = score
                    best = s
            scene = best
        else:
            for s in self._scenes:
                if str(s.get("id", "")) == pick:
                    scene = s
                    break
            if scene is None:
                scene = self._scenes[0]

        usage, names, stats = build_scene_vram_usage(self._project_data, scene or {}, self._base_dir)
        self._current_scene = scene
        self._tile_map.set_usage(usage, names)

        t_total = TILE_MAX - TILE_USER_START
        occupied = sum(1 for i in range(TILE_USER_START, TILE_MAX) if usage[i] is not None)
        t_free = max(0, t_total - occupied)

        warn_bits: list[str] = []
        if stats.tile_conflict:
            warn_bits.append(tr("vram.conflict"))
        if stats.tile_overflow:
            warn_bits.append(tr("vram.overflow"))
        # Tile budget thresholds (independent of conflict/overflow)
        if not warn_bits:
            if occupied > 384:
                warn_bits.append("🔴")
                _tile_css = "color: #e05050; font-weight: bold;"
            elif occupied > 320:
                warn_bits.append("🔶")
                _tile_css = "color: #e07030;"
            elif occupied > 256:
                warn_bits.append("⚠")
                _tile_css = "color: #e0a03a;"
            else:
                _tile_css = ""
        else:
            _tile_css = "color: #e05050;"
        warn_txt = ("  " + " ".join(warn_bits)) if warn_bits else ""
        est = " ~" if stats.is_estimated else ""
        self._tile_status.setText(
            tr("vram.tiles_status_scene", used=occupied, total=t_total, free=t_free, raw=stats.tile_used_raw, est=est, warn=warn_txt)
        )
        self._tile_status.setStyleSheet(_tile_css)
        self._update_suggestions(scene, names, stats)

        spr_base = int(getattr(stats, "spr_pal_base", 0))
        spr_slots = int(stats.spr_pal_used)
        spr_end = spr_base + spr_slots
        spr_free = max(0, PAL_MAX_SPR - spr_end)
        spr_over = spr_end > PAL_MAX_SPR
        self._pal_slot_data = self._build_pal_slot_data(scene, stats)
        self._pal_spr.set_slots(self._pal_slot_data)
        if spr_base:
            self._pal_spr_status.setText(
                tr(
                    "vram.pals_status_base",
                    base=spr_base,
                    used=spr_slots,
                    end=spr_end,
                    total=PAL_MAX_SPR,
                    free=spr_free,
                    warn=tr("vram.overflow") if spr_over else "",
                )
            )
        else:
            self._pal_spr_status.setText(
                tr("vram.pals_status", used=spr_end, total=PAL_MAX_SPR, free=spr_free, warn=tr("vram.overflow") if spr_over else "")
            )
        self._pal_spr_status.setStyleSheet("color: #e05050;" if spr_over else "")

        bg1_used = int(stats.bg_pal_scr1_used)
        bg1_free = max(0, PAL_MAX_BG - bg1_used)
        bg1_over = bg1_used > PAL_MAX_BG
        self._pal_bg1.set_used(min(bg1_used, PAL_MAX_BG))
        self._pal_bg1_status.setText(
            tr("vram.pals_status", used=bg1_used, total=PAL_MAX_BG, free=bg1_free, warn=tr("vram.overflow") if bg1_over else "")
        )
        self._pal_bg1_status.setStyleSheet("color: #e05050;" if bg1_over else "")

        bg2_used = int(stats.bg_pal_scr2_used)
        bg2_free = max(0, PAL_MAX_BG - bg2_used)
        bg2_over = bg2_used > PAL_MAX_BG
        self._pal_bg2.set_used(min(bg2_used, PAL_MAX_BG))
        self._pal_bg2_status.setText(
            tr("vram.pals_status", used=bg2_used, total=PAL_MAX_BG, free=bg2_free, warn=tr("vram.overflow") if bg2_over else "")
        )
        self._pal_bg2_status.setStyleSheet("color: #e05050;" if bg2_over else "")

        bg_analysis = analyze_scene_bg_palette_banks(scene or {}, self._base_dir)
        self._pal_bg1_analysis.setText(self._format_bg_palette_analysis(bg_analysis.get("scr1")))
        self._pal_bg2_analysis.setText(self._format_bg_palette_analysis(bg_analysis.get("scr2")))

    def _update_suggestions(self, scene: dict | None, names: list[str | None], stats) -> None:
        self._suggest_spr_tile_base = None
        self._btn_fix_spr_base.setVisible(False)
        self._btn_fix_tm_pack.setVisible(False)

        if not scene:
            self._suggest_g.setVisible(False)
            return

        conflicts = [n for n in (names or []) if isinstance(n, str) and n.startswith("CONFLICT:")]
        if not conflicts and not bool(getattr(stats, "tile_overflow", False)):
            self._suggest_g.setVisible(False)
            return

        lines: list[str] = []

        if conflicts:
            has_spr = any("SPR " in c for c in conflicts)
            has_tm = any("TM " in c for c in conflicts)

            if has_tm and has_spr:
                try:
                    min_base = max(int(TILE_USER_START), int(getattr(stats, "tm_tile_end", TILE_USER_START)))
                except Exception:
                    min_base = int(TILE_USER_START)
                self._suggest_spr_tile_base = min_base
                self._btn_fix_spr_base.setText(tr("vram.suggest_fix_spr_base_at", base=min_base))
                self._btn_fix_spr_base.setVisible(True)
                lines.append(tr("vram.suggest_spr_base", base=min_base))

            if has_tm and not has_spr:
                self._btn_fix_tm_pack.setVisible(True)
                lines.append(tr("vram.suggest_tm_pack"))

            # Show a short example
            example = conflicts[0].replace("CONFLICT:", "").strip()
            lines.append(tr("vram.suggest_example", ex=example))

        if bool(getattr(stats, "tile_overflow", False)):
            lines.append(tr("vram.suggest_overflow"))

        self._suggest_lbl.setText("\n".join([s for s in lines if s.strip()]))
        self._suggest_g.setVisible(True)

    def _format_bg_palette_analysis(self, analysis) -> str:
        if analysis is None:
            return ""
        entries = tuple(getattr(analysis, "entries", ()) or ())
        groups = tuple(getattr(analysis, "identical_groups", ()) or ())
        if not entries:
            text = tr("vram.bg_pal_analysis_empty")
        elif groups:
            parts: list[str] = []
            count_by_name = {str(e.name): int(getattr(e, "palette_count", 0)) for e in entries}
            for names in groups:
                n = count_by_name.get(str(names[0]), 0) if names else 0
                parts.append(tr("vram.bg_pal_analysis_group", names=" + ".join(names), n=n))
            text = tr("vram.bg_pal_analysis_match", groups=" ; ".join(parts))
        elif len(entries) == 1:
            text = tr("vram.bg_pal_analysis_single", name=entries[0].name, n=entries[0].palette_count)
        else:
            text = tr("vram.bg_pal_analysis_none")
        if bool(getattr(analysis, "is_estimated", False)):
            text += "\n" + tr("vram.bg_pal_analysis_est")
        return text

    # ------------------------------------------------------------------
    # Palette bank helpers
    # ------------------------------------------------------------------

    def _spr_palette_words(self, spr: dict, fixed: str) -> list[int]:
        """Return 4 NGPC palette words for a sprite (index 0 = transparent 0x0000)."""
        if fixed:
            parts = [s.strip() for s in fixed.split(",") if s.strip()]
            if len(parts) == 4:
                try:
                    words: list[int] = []
                    for s in parts:
                        s = s.lower()
                        if s.startswith("0x"):
                            s = s[2:]
                        words.append(int(s, 16))
                    return words
                except ValueError:
                    pass

        if self._base_dir:
            rel = str(spr.get("file", "")).strip()
            if rel:
                p = self._base_dir / rel
                try:
                    from PIL import Image
                    from core.rgb444 import palette_from_image, to_word_sprite
                    img = Image.open(p)
                    colors = palette_from_image(img)[:3]
                    words = [0x0000]  # slot 0 = transparent
                    for r8, g8, b8 in colors:
                        words.append(to_word_sprite(r8, g8, b8))
                    while len(words) < 4:
                        words.append(0x0000)
                    return words[:4]
                except Exception:
                    pass

        return [0x0000, 0x0000, 0x0000, 0x0000]

    def _build_pal_slot_data(self, scene: dict, stats) -> list[dict | None]:
        """Build per-slot data for _PaletteBankWidget (one entry per sprite palette slot)."""
        result: list[dict | None] = [None] * PAL_MAX_SPR

        bundle_cfg = (self._project_data.get("bundle") or {}) if self._project_data else {}
        try:
            spr_pal_base = int(scene.get("spr_pal_base", bundle_cfg.get("pal_base", 0)))
        except Exception:
            spr_pal_base = 0

        cursor = spr_pal_base
        fixed_to_slot: dict[str, int] = {}  # fixed_palette string → first assigned slot index

        for spr in scene.get("sprites", []) or []:
            fixed = str(spr.get("fixed_palette") or "").strip()
            reuse_req = bool(spr.get("reuse_palette", False))
            # Detect sharing: explicit flag OR same fixed_palette already allocated.
            # reuse_ok requires the palette to already be in fixed_to_slot — if the
            # "original" sprite hasn't been processed yet, fall through to normal alloc.
            auto_share = bool(fixed) and fixed in fixed_to_slot
            reuse_ok = (reuse_req or auto_share) and bool(fixed) and fixed in fixed_to_slot
            name = str(spr.get("name") or spr.get("file", "?"))

            if reuse_ok:
                # Share the slot already assigned to this fixed_palette
                slot_i = fixed_to_slot[fixed]
                if 0 <= slot_i < PAL_MAX_SPR and result[slot_i] is not None:
                    result[slot_i]["names"].append(name)
            else:
                slot_i = cursor
                if 0 <= slot_i < PAL_MAX_SPR:
                    words = self._spr_palette_words(spr, fixed)
                    result[slot_i] = {"words": words, "names": [name], "sprite": spr}
                if fixed:
                    fixed_to_slot[fixed] = slot_i
                cursor += 1

        return result

    def _on_pal_slot_clicked(self, slot_i: int) -> None:
        if slot_i < 0 or slot_i >= len(self._pal_slot_data):
            return
        slot = self._pal_slot_data[slot_i]
        if slot is None:
            return
        spr = slot.get("sprite")
        if not spr:
            return
        rel = str(spr.get("file", "")).strip()
        if not rel:
            return
        base = self._base_dir
        p = (base / rel) if base else Path(rel)
        payload = {
            "path": str(p),
            "frame_w": int(spr.get("frame_w", 8) or 8),
            "frame_h": int(spr.get("frame_h", 8) or 8),
            "frame_count": int(spr.get("frame_count", 1) or 1),
        }
        self.open_sprite_in_palette.emit(payload)

    def _apply_fix_spr_base(self) -> None:
        if not self._current_scene or self._suggest_spr_tile_base is None:
            return
        self._current_scene["spr_tile_base"] = int(self._suggest_spr_tile_base)
        self.scene_modified.emit(self._current_scene)

    def _apply_fix_tm_pack(self) -> None:
        if not self._current_scene:
            return
        tms = self._current_scene.get("tilemaps", [])
        if not isinstance(tms, list) or not tms:
            return
        changed = False
        for tm in tms:
            if not isinstance(tm, dict):
                continue
            if "tile_base" in tm:
                tm.pop("tile_base", None)
                changed = True
        if changed:
            self.scene_modified.emit(self._current_scene)
