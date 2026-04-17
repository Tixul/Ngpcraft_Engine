"""
ui/tabs/scene_map_tab.py - Scene relationship map (Project group).

Shows all project scenes as draggable cards on an infinite canvas.
Arrows are drawn automatically from goto_scene / warp_to triggers.
Double-click a card to open the scene in the Level tab.
Right-click a card for context menu (rename, duplicate, delete, set start).
"""
from __future__ import annotations

import copy
import math
import uuid
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QPoint, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QCursor, QFont, QImage,
    QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QFrame,
    QGraphicsItem, QGraphicsScene, QGraphicsView,
    QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from i18n.lang import tr
from ui.tabs._project_path_mixin import ProjectPathMixin

# ── Layout constants ───────────────────────────────────────────────────────────
_CARD_W       = 192
_CARD_H       = 78
_CARD_R       = 7
_AUTO_COLS    = 4
_AUTO_COL_GAP = 40
_AUTO_ROW_GAP = 44

_THUMB_X = 134
_THUMB_W = 50
_THUMB_H = 38
_THUMB_Y = 6

_DOT_R = 5
_DOT_X = _CARD_W - 10
_DOT_Y = 10

# ── Colours ────────────────────────────────────────────────────────────────────
_C_BG            = QColor("#1a1a1e")
_C_CARD          = QColor("#28282d")
_C_CARD_BORDER   = QColor("#484855")
_C_START_CARD    = QColor("#1b3326")
_C_START_BORDER  = QColor("#4caf70")
_C_SEL_BORDER    = QColor("#5599cc")
_C_TITLE         = QColor("#dedede")
_C_SUB           = QColor("#808090")
_C_BADGE         = QColor("#4caf70")
_C_ARROW         = QColor("#4a6a88")
_C_ARROW_HL      = QColor("#88bbee")
_C_ARROW_DIM     = QColor("#2a3848")
_C_ARROW_SEL     = QColor("#aaddff")
_C_ARROW_LBL     = QColor("#6688aa")
_C_DOT_OK        = QColor("#4caf70")
_C_DOT_WARN      = QColor("#e0a020")
_C_DOT_EMPTY     = QColor("#555566")
_C_THUMB_BG      = QColor("#1a1a1e")
_C_START_STRIPE  = QColor("#2a5c3a")
_C_ENT_BADGE_BG  = QColor("#2a3848")

_NO_PLAYER_PROFILES = {"menu", "visual_novel", "puzzle", "race"}

_PROFILE_LABEL = {
    "platformer":       "Platformer",
    "run_gun":          "Run & Gun",
    "shmup":            "Shmup",
    "topdown_rpg":      "Top-Down RPG",
    "topdown_room":     "Top-Down",
    "topdown_world":    "World Map",
    "brawler":          "Brawler",
    "puzzle":           "Puzzle",
    "menu":             "Menu",
    "visual_novel":     "Visual Novel",
    "race":             "Race",
    "roguelite_room":   "Roguelite",
}


def _scene_status(scene_data: dict) -> str:
    has_tilemap = any(
        str(tm.get("file") or tm.get("path") or "").strip()
        for tm in (scene_data.get("tilemaps") or [])
    )
    if not has_tilemap:
        return "empty"
    profile = str(scene_data.get("level_profile") or "")
    if profile in _NO_PLAYER_PROFILES:
        return "ok"
    sprites = scene_data.get("sprites") or []
    player_types = {
        str(s.get("name") or s.get("id") or "")
        for s in sprites
        if str(s.get("gameplay_role") or "") == "player"
    }
    entities = scene_data.get("entities") or []
    has_player = any(str(e.get("type") or "") in player_types for e in entities)
    return "ok" if has_player else "warn"


# ── SceneCard ──────────────────────────────────────────────────────────────────

class SceneCard(QGraphicsItem):
    """Draggable card representing one scene."""

    def __init__(
        self,
        scene_data:   dict,
        is_start:     bool,
        on_moved:     "Callable[[str, int, int], None]",
        on_open:      "Callable[[str], None]",
        project_path: "Optional[Path]" = None,
    ) -> None:
        super().__init__()
        self._data         = scene_data
        self._is_start     = is_start
        self._on_moved     = on_moved
        self._on_open      = on_open
        self._project_path = project_path
        self._thumb:       "Optional[QPixmap]" = None
        self._thumb_tried  = False
        self._status       = _scene_status(scene_data)
        self._entity_count = len(scene_data.get("entities") or [])

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsScenePositionChanges)
        self.setAcceptHoverEvents(True)
        self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
        self.setToolTip(scene_data.get("label", ""))
        self.setZValue(1)

    # ------------------------------------------------------------------
    def scene_id(self) -> str:
        return str(self._data.get("id") or "")

    def _load_thumb(self) -> None:
        if self._thumb_tried:
            return
        self._thumb_tried = True
        base = self._project_path.parent if self._project_path else None
        if not base:
            return
        for tm in (self._data.get("tilemaps") or []):
            rel = str(tm.get("file") or tm.get("path") or "").strip()
            if not rel:
                continue
            p = Path(rel) if Path(rel).is_absolute() else base / rel
            if p.exists():
                px = QPixmap(str(p))
                if not px.isNull():
                    self._thumb = px.scaled(
                        _THUMB_W, _THUMB_H,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                break

    # ------------------------------------------------------------------
    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, _CARD_W, _CARD_H)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: N802
        self._load_thumb()
        rect = QRectF(0.5, 0.5, _CARD_W - 1, _CARD_H - 1)

        # Background
        painter.setBrush(QBrush(_C_START_CARD if self._is_start else _C_CARD))
        if self.isSelected():
            painter.setPen(QPen(_C_SEL_BORDER, 2.0))
        elif self._is_start:
            painter.setPen(QPen(_C_START_BORDER, 1.5))
        else:
            painter.setPen(QPen(_C_CARD_BORDER, 1.0))
        painter.drawRoundedRect(rect, _CARD_R, _CARD_R)

        # MAP-5: green top stripe on start card
        if self._is_start:
            painter.save()
            painter.setClipRect(QRectF(1, 1, _CARD_W - 2, 5))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(_C_START_STRIPE))
            painter.drawRoundedRect(QRectF(1, 1, _CARD_W - 2, 12), _CARD_R, _CARD_R)
            painter.restore()

        # Thumbnail area
        th_rect = QRectF(_THUMB_X, _THUMB_Y, _THUMB_W, _THUMB_H)
        painter.setPen(QPen(_C_CARD_BORDER, 0.5))
        painter.setBrush(QBrush(_C_THUMB_BG))
        painter.drawRect(th_rect)
        if self._thumb and not self._thumb.isNull():
            ox = _THUMB_X + (_THUMB_W - self._thumb.width()) // 2
            oy = _THUMB_Y + (_THUMB_H - self._thumb.height()) // 2
            painter.drawPixmap(int(ox), int(oy), self._thumb)

        # Status dot
        dot_color = {"ok": _C_DOT_OK, "warn": _C_DOT_WARN, "empty": _C_DOT_EMPTY}.get(
            self._status, _C_DOT_EMPTY
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(dot_color))
        painter.drawEllipse(QRectF(_DOT_X - _DOT_R, _DOT_Y - _DOT_R, _DOT_R * 2, _DOT_R * 2))

        # Title
        text_w = _THUMB_X - 16
        f_title = QFont()
        f_title.setPixelSize(13)
        f_title.setBold(True)
        painter.setFont(f_title)
        painter.setPen(_C_TITLE)
        painter.drawText(
            QRectF(10, 8, text_w, 22),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._data.get("label", "?"),
        )

        # Profile type
        profile = str(self._data.get("level_profile") or "")
        prof_str = _PROFILE_LABEL.get(profile, profile or "—")
        f_sub = QFont()
        f_sub.setPixelSize(11)
        painter.setFont(f_sub)
        painter.setPen(_C_SUB)
        painter.drawText(QRectF(10, 32, text_w, 16), Qt.AlignmentFlag.AlignLeft, prof_str)

        # Dimensions
        ls = self._data.get("level_size") or {}
        if isinstance(ls, dict):
            mw, mh = ls.get("w"), ls.get("h")
            if mw and mh:
                painter.drawText(
                    QRectF(10, 50, text_w - 32, 16),
                    Qt.AlignmentFlag.AlignLeft,
                    f"{mw}×{mh} tiles",
                )

        # MAP-10: entity count badge
        if self._entity_count > 0:
            f_cnt = QFont()
            f_cnt.setPixelSize(9)
            painter.setFont(f_cnt)
            txt = f"⬡ {self._entity_count}"
            bw = 8 + len(txt) * 6
            bx = text_w - bw + 2
            by = 52
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(_C_ENT_BADGE_BG))
            painter.drawRoundedRect(QRectF(bx, by, bw, 12), 3, 3)
            painter.setPen(_C_SUB)
            painter.drawText(QRectF(bx, by, bw, 12), Qt.AlignmentFlag.AlignCenter, txt)

        # MAP-5: START pill badge
        if self._is_start:
            f_badge = QFont()
            f_badge.setPixelSize(9)
            f_badge.setBold(True)
            painter.setFont(f_badge)
            pill = QRectF(_CARD_W - 50, _CARD_H - 16, 43, 11)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(_C_START_BORDER))
            painter.drawRoundedRect(pill, 5, 5)
            painter.setPen(QColor("#000"))
            painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, "▶ START")

    # ------------------------------------------------------------------
    def hoverEnterEvent(self, event) -> None:  # noqa: N802
        sc = self.scene()
        if sc:
            sc._set_hover(self.scene_id())
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802
        sc = self.scene()
        if sc:
            sc._set_hover(None)
        super().hoverLeaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        pos = self.pos()
        self._on_moved(self._data.get("id", ""), int(pos.x()), int(pos.y()))

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self._on_open(self._data.get("id", ""))

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        sc = self.scene()
        if sc:
            sp = event.screenPos()
            sc.card_context_requested.emit(self.scene_id(), int(sp.x()), int(sp.y()))
        event.accept()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            sc = self.scene()
            if sc:
                for item in sc.items():
                    if isinstance(item, SceneArrow):
                        item.prepareGeometryChange()
        return super().itemChange(change, value)


# ── SceneArrow ─────────────────────────────────────────────────────────────────

class SceneArrow(QGraphicsItem):
    """Directed arrow from one SceneCard to another, labelled with a condition."""

    def __init__(self, src: SceneCard, dst: SceneCard, label: str, action: str = "goto_scene") -> None:
        super().__init__()
        self._src    = src
        self._dst    = dst
        self._label  = label
        self._action = action
        self.setZValue(0)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemHasNoContents, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)

    # ------------------------------------------------------------------
    @staticmethod
    def _edge_point(card: SceneCard, toward: QPointF) -> QPointF:
        r  = card.sceneBoundingRect()
        cx, cy = r.center().x(), r.center().y()
        dx, dy = toward.x() - cx, toward.y() - cy
        length = math.sqrt(dx * dx + dy * dy)
        if length < 1e-6:
            return r.center()
        dx /= length
        dy /= length
        hw, hh = r.width() / 2, r.height() / 2
        tx = (hw / abs(dx)) if abs(dx) > 1e-6 else 1e9
        ty = (hh / abs(dy)) if abs(dy) > 1e-6 else 1e9
        t  = min(tx, ty) - 3
        return QPointF(cx + dx * t, cy + dy * t)

    def _endpoints(self):
        dst_c = self._dst.sceneBoundingRect().center()
        src_c = self._src.sceneBoundingRect().center()
        return self._edge_point(self._src, dst_c), self._edge_point(self._dst, src_c)

    def boundingRect(self) -> QRectF:
        sp, dp = self._endpoints()
        x = min(sp.x(), dp.x()) - 24
        y = min(sp.y(), dp.y()) - 24
        w = abs(dp.x() - sp.x()) + 48
        h = abs(dp.y() - sp.y()) + 48
        return QRectF(x, y, max(w, 48), max(h, 48))

    def shape(self) -> QPainterPath:
        sp, dp = self._endpoints()
        path = QPainterPath(sp)
        path.lineTo(dp)
        stroker = QPainterPathStroker()
        stroker.setWidth(12)
        return stroker.createStroke(path)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: N802
        sp, dp = self._endpoints()

        hovered_id = getattr(self.scene(), "_hovered_id", None)
        connected  = (hovered_id is None
                      or self._src.scene_id() == hovered_id
                      or self._dst.scene_id() == hovered_id)

        if self.isSelected():
            col, lw = _C_ARROW_SEL, 2.2
        elif not connected:
            col, lw = _C_ARROW_DIM, 1.0
        elif hovered_id is not None:
            col, lw = _C_ARROW_HL, 1.8
        else:
            col, lw = _C_ARROW, 1.4

        painter.setPen(QPen(col, lw, Qt.PenStyle.SolidLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(sp, dp)

        # Arrowhead
        dx = dp.x() - sp.x()
        dy = dp.y() - sp.y()
        length = math.sqrt(dx * dx + dy * dy)
        if length > 1e-6:
            dx /= length
            dy /= length
            aw, ax = 9.0, 4.5
            p1 = QPointF(dp.x() - dx * aw + dy * ax, dp.y() - dy * aw - dx * ax)
            p2 = QPointF(dp.x() - dx * aw - dy * ax, dp.y() - dy * aw + dx * ax)
            painter.setBrush(QBrush(col))
            painter.setPen(Qt.PenStyle.NoPen)
            path = QPainterPath()
            path.moveTo(dp)
            path.lineTo(p1)
            path.lineTo(p2)
            path.closeSubpath()
            painter.drawPath(path)

        # Condition label (only when not dimmed)
        if self._label and connected:
            mx = (sp.x() + dp.x()) / 2
            my = (sp.y() + dp.y()) / 2
            f = QFont()
            f.setPixelSize(10)
            painter.setFont(f)
            painter.setPen(_C_ARROW_SEL if self.isSelected() else _C_ARROW_LBL)
            painter.drawText(
                QRectF(mx - 55, my - 10, 110, 20),
                Qt.AlignmentFlag.AlignCenter,
                self._label,
            )

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            sc = self.scene()
            if sc:
                if value:
                    sc.arrow_selected.emit(
                        self._src._data.get("label", "?"),
                        self._dst._data.get("label", "?"),
                        self._label,
                        self._action,
                    )
                else:
                    sc.arrow_cleared.emit()
        return super().itemChange(change, value)


# ── SceneMapScene ──────────────────────────────────────────────────────────────

class SceneMapScene(QGraphicsScene):
    card_context_requested = pyqtSignal(str, int, int)       # scene_id, screen_x, screen_y
    arrow_selected         = pyqtSignal(str, str, str, str)  # src_lbl, dst_lbl, cond, action
    arrow_cleared          = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setBackgroundBrush(QBrush(_C_BG))
        self._cards:      dict[str, SceneCard] = {}
        self._hovered_id: Optional[str]         = None

    # ------------------------------------------------------------------
    def _set_hover(self, card_id: Optional[str]) -> None:
        if self._hovered_id == card_id:
            return
        self._hovered_id = card_id
        for item in self.items():
            if isinstance(item, SceneArrow):
                item.update()

    def build(
        self,
        scenes:       list[dict],
        start_label:  str,
        on_moved:     Callable,
        on_open:      Callable,
        project_path: "Optional[Path]" = None,
    ) -> None:
        self.clear()
        self._cards.clear()
        self._hovered_id = None

        for i, sc in enumerate(scenes):
            is_start = sc.get("label", "") == start_label
            card = SceneCard(sc, is_start, on_moved, on_open, project_path)

            if sc.get("map_x") is not None:
                x, y = int(sc["map_x"]), int(sc["map_y"])
            else:
                col = i % _AUTO_COLS
                row = i // _AUTO_COLS
                x   = col * (_CARD_W + _AUTO_COL_GAP)
                y   = row * (_CARD_H + _AUTO_ROW_GAP)

            card.setPos(x, y)
            self.addItem(card)
            self._cards[sc.get("id", "")] = card

        seen: set[tuple] = set()
        for sc in scenes:
            src_id   = sc.get("id", "")
            src_card = self._cards.get(src_id)
            if not src_card:
                continue
            for trig in (sc.get("triggers") or []):
                act = str(trig.get("action") or "")
                if act not in ("goto_scene", "warp_to"):
                    continue
                dst_id = str(trig.get("scene_to") or "").strip()
                if not dst_id:
                    continue
                dst_card = self._cards.get(dst_id)
                if not dst_card or dst_id == src_id:
                    continue
                cond = str(trig.get("cond") or "")
                key  = (src_id, dst_id, cond)
                if key in seen:
                    continue
                seen.add(key)
                self.addItem(SceneArrow(src_card, dst_card, cond, act))

    # ------------------------------------------------------------------
    def apply_auto_layout(self, scenes: list[dict]) -> None:
        for i, sc in enumerate(scenes):
            card = self._cards.get(sc.get("id", ""))
            if not card:
                continue
            col = i % _AUTO_COLS
            row = i // _AUTO_COLS
            x   = col * (_CARD_W + _AUTO_COL_GAP)
            y   = row * (_CARD_H + _AUTO_ROW_GAP)
            card.setPos(x, y)
            sc["map_x"] = x
            sc["map_y"] = y

    def apply_filter(self, profile: str) -> None:
        for item in self.items():
            if isinstance(item, SceneCard):
                visible = (not profile or
                           str(item._data.get("level_profile") or "") == profile)
                item.setVisible(visible)
        for item in self.items():
            if isinstance(item, SceneArrow):
                item.setVisible(item._src.isVisible() and item._dst.isVisible())


# ── SceneMapView ───────────────────────────────────────────────────────────────

class SceneMapView(QGraphicsView):

    def __init__(self, gscene: SceneMapScene, parent=None) -> None:
        super().__init__(gscene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(self.Shape.NoFrame)
        self._zoom = 1.0

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta  = event.angleDelta().y()
        factor = 1.15 if delta > 0 else (1.0 / 1.15)
        new_z  = self._zoom * factor
        if 0.1 <= new_z <= 5.0:
            self._zoom = new_z
            self.scale(factor, factor)

    def fit_all(self) -> None:
        r = self.scene().itemsBoundingRect()
        if r.isNull():
            return
        self.fitInView(r.adjusted(-48, -48, 48, 48), Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = self.transform().m11()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        item = self.itemAt(event.pos())
        if isinstance(item, (SceneCard, SceneArrow)):
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        else:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)


# ── Arrow info strip (MAP-6) ───────────────────────────────────────────────────

class _ArrowInfoStrip(QFrame):
    """Bottom strip that appears when a transition arrow is selected."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(28)
        self.setStyleSheet(
            "background:#1e2a38; border-top:1px solid #2a4a6a;"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 2, 6, 2)
        lay.setSpacing(8)

        self._lbl = QLabel()
        self._lbl.setStyleSheet("color:#aaddff; font-size:11px;")
        lay.addWidget(self._lbl, 1)

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(18, 18)
        btn_close.setStyleSheet(
            "background:transparent; color:#557; border:none; font-size:10px;"
        )
        btn_close.clicked.connect(self.hide)
        lay.addWidget(btn_close)
        self.hide()

    def show_info(self, src: str, dst: str, cond: str, action: str) -> None:
        act_str  = "⤳ Warp" if action == "warp_to" else "→"
        cond_str = f"   [{cond}]" if cond else ""
        self._lbl.setText(f"<b>{src}</b>  {act_str}  <b>{dst}</b>{cond_str}")
        self.show()


# ── SceneMapTab ────────────────────────────────────────────────────────────────

class SceneMapTab(ProjectPathMixin, QWidget):
    """Project-group tab: scene relationship map."""

    open_scene_requested = pyqtSignal(str)

    def __init__(
        self,
        project_data:  dict,
        project_path:  "Path | None",
        on_save:       Callable,
        parent:        "QWidget | None" = None,
    ) -> None:
        super().__init__(parent)
        self._data         = project_data
        self._project_path = project_path
        self._on_save      = on_save
        self._built        = False
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Toolbar
        tb = QWidget()
        tb.setFixedHeight(32)
        tb.setStyleSheet("background:#222226; border-bottom:1px solid #333;")
        tb_lay = QHBoxLayout(tb)
        tb_lay.setContentsMargins(6, 2, 6, 2)
        tb_lay.setSpacing(6)

        btn_fit = QPushButton(tr("map.fit"))
        btn_fit.setFixedHeight(24)
        btn_fit.setToolTip(tr("map.fit_tt"))
        btn_fit.clicked.connect(self._on_fit)
        tb_lay.addWidget(btn_fit)

        btn_auto = QPushButton(tr("map.auto_layout"))
        btn_auto.setFixedHeight(24)
        btn_auto.setToolTip(tr("map.auto_layout_tt"))
        btn_auto.clicked.connect(self._on_auto_layout)
        tb_lay.addWidget(btn_auto)

        btn_export = QPushButton("Export PNG")
        btn_export.setFixedHeight(24)
        btn_export.setToolTip("Export scene map as PNG")
        btn_export.clicked.connect(self._on_export_png)
        tb_lay.addWidget(btn_export)

        tb_lay.addStretch()

        # MAP-7: profile filter
        lbl_filter = QLabel("Filter:")
        lbl_filter.setStyleSheet("color:#888; font-size:11px;")
        tb_lay.addWidget(lbl_filter)

        self._combo_filter = QComboBox()
        self._combo_filter.setFixedHeight(24)
        self._combo_filter.setMinimumWidth(120)
        self._combo_filter.setToolTip("Filter by scene profile")
        self._combo_filter.currentIndexChanged.connect(self._on_filter_changed)
        tb_lay.addWidget(self._combo_filter)

        self._lbl_hint = QLabel(tr("map.hint"))
        self._lbl_hint.setStyleSheet("color:#555; font-size:11px;")
        tb_lay.addWidget(self._lbl_hint)

        root.addWidget(tb)

        # Canvas
        self._map_scene = SceneMapScene()
        self._map_scene.card_context_requested.connect(self._on_card_context)
        self._map_scene.arrow_selected.connect(self._on_arrow_selected)
        self._map_scene.arrow_cleared.connect(self._on_arrow_cleared)
        self._map_view  = SceneMapView(self._map_scene)
        root.addWidget(self._map_view, 1)

        # MAP-6: arrow info strip
        self._info_strip = _ArrowInfoStrip()
        root.addWidget(self._info_strip)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        scenes      = list((self._data or {}).get("scenes") or [])
        start_label = str(((self._data or {}).get("game") or {}).get("start_scene") or "").strip()
        self._map_scene.build(
            scenes, start_label,
            self._on_card_moved, self._on_card_open,
            self._project_path,
        )
        self._rebuild_filter_combo(scenes)
        self._map_view.fit_all()
        self._built = True

    def _rebuild_filter_combo(self, scenes: list[dict]) -> None:
        self._combo_filter.blockSignals(True)
        prev = self._combo_filter.currentData()
        self._combo_filter.clear()
        self._combo_filter.addItem("All profiles", "")
        seen: set[str] = set()
        for sc in scenes:
            p = str(sc.get("level_profile") or "")
            if p and p not in seen:
                seen.add(p)
                self._combo_filter.addItem(_PROFILE_LABEL.get(p, p), p)
        idx = self._combo_filter.findData(prev)
        self._combo_filter.setCurrentIndex(idx if idx >= 0 else 0)
        self._combo_filter.blockSignals(False)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh()

    # ------------------------------------------------------------------
    def _on_card_moved(self, sid: str, x: int, y: int) -> None:
        for sc in ((self._data or {}).get("scenes") or []):
            if sc.get("id") == sid:
                sc["map_x"] = x
                sc["map_y"] = y
                break
        self._on_save()

    def _on_card_open(self, sid: str) -> None:
        self.open_scene_requested.emit(sid)

    def _on_fit(self) -> None:
        self._map_view.fit_all()

    def _on_auto_layout(self) -> None:
        scenes = list((self._data or {}).get("scenes") or [])
        self._map_scene.apply_auto_layout(scenes)
        self._on_save()
        self._map_view.fit_all()

    # MAP-8 ---------------------------------------------------------------
    def _on_export_png(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Scene Map", "scene_map.png", "PNG (*.png)"
        )
        if not path:
            return
        rect = self._map_scene.itemsBoundingRect().adjusted(-24, -24, 24, 24)
        if rect.isEmpty():
            return
        img = QImage(int(rect.width()), int(rect.height()), QImage.Format.Format_ARGB32)
        img.fill(_C_BG)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._map_scene.render(p, source=rect)
        p.end()
        img.save(path)

    # MAP-7 ---------------------------------------------------------------
    def _on_filter_changed(self) -> None:
        profile = self._combo_filter.currentData() or ""
        self._map_scene.apply_filter(profile)

    # MAP-6 ---------------------------------------------------------------
    def _on_arrow_selected(self, src: str, dst: str, cond: str, action: str) -> None:
        self._info_strip.show_info(src, dst, cond, action)

    def _on_arrow_cleared(self) -> None:
        for item in self._map_scene.selectedItems():
            if isinstance(item, SceneArrow):
                return
        self._info_strip.hide()

    # MAP-4 ---------------------------------------------------------------
    def _on_card_context(self, sid: str, x: int, y: int) -> None:
        scenes = list((self._data or {}).get("scenes") or [])
        scene_data = next((s for s in scenes if s.get("id") == sid), None)
        if not scene_data:
            return

        menu = QMenu(self)
        act_open      = menu.addAction("Open scene")
        menu.addSeparator()
        act_rename    = menu.addAction("Rename…")
        act_duplicate = menu.addAction("Duplicate")
        menu.addSeparator()
        act_start     = menu.addAction("Set as start scene")
        menu.addSeparator()
        act_delete    = menu.addAction("Delete scene…")

        chosen = menu.exec(QPoint(x, y))
        if chosen == act_open:
            self._on_card_open(sid)
        elif chosen == act_rename:
            self._ctx_rename(scene_data)
        elif chosen == act_duplicate:
            self._ctx_duplicate(scene_data)
        elif chosen == act_start:
            self._ctx_set_start(scene_data.get("label", ""))
        elif chosen == act_delete:
            self._ctx_delete(sid, scene_data)

    def _ctx_rename(self, scene_data: dict) -> None:
        old = scene_data.get("label", "")
        new, ok = QInputDialog.getText(self, "Rename scene", "New name:", text=old)
        if ok and new.strip() and new.strip() != old:
            scene_data["label"] = new.strip()
            self._on_save()
            self.refresh()

    def _ctx_duplicate(self, scene_data: dict) -> None:
        new_scene         = copy.deepcopy(scene_data)
        new_scene["id"]   = str(uuid.uuid4())
        new_scene["label"] = scene_data.get("label", "scene") + " (copy)"
        new_scene.pop("map_x", None)
        new_scene.pop("map_y", None)
        scenes = (self._data or {}).setdefault("scenes", [])
        scenes.append(new_scene)
        self._on_save()
        self.refresh()

    def _ctx_set_start(self, label: str) -> None:
        (self._data or {}).setdefault("game", {})["start_scene"] = label
        self._on_save()
        self.refresh()

    def _ctx_delete(self, sid: str, scene_data: dict) -> None:
        label = scene_data.get("label", sid)
        reply = QMessageBox.question(
            self,
            "Delete scene",
            f"Delete scene «{label}»?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        scenes = (self._data or {}).get("scenes") or []
        (self._data or {})["scenes"] = [s for s in scenes if s.get("id") != sid]
        self._on_save()
        self.refresh()
