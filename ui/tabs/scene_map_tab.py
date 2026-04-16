"""
ui/tabs/scene_map_tab.py - Scene relationship map (Project group).

Shows all project scenes as draggable cards on an infinite canvas.
Arrows are drawn automatically from goto_scene / warp_to triggers.
Double-click a card to open the scene in the Level tab.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QCursor, QFont, QPainter, QPainterPath, QPen,
)
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsScene, QGraphicsView,
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from i18n.lang import tr
from ui.tabs._project_path_mixin import ProjectPathMixin

# ── Layout constants ───────────────────────────────────────────────────────────
_CARD_W       = 168
_CARD_H       = 78
_CARD_R       = 7       # corner radius
_AUTO_COLS    = 4
_AUTO_COL_GAP = 52
_AUTO_ROW_GAP = 44

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
_C_ARROW_LBL     = QColor("#6688aa")

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


# ── SceneCard ──────────────────────────────────────────────────────────────────

class SceneCard(QGraphicsItem):
    """Draggable card representing one scene."""

    def __init__(
        self,
        scene_data: dict,
        is_start: bool,
        on_moved: "Callable[[str, int, int], None]",
        on_open:  "Callable[[str], None]",
    ) -> None:
        super().__init__()
        self._data     = scene_data
        self._is_start = is_start
        self._on_moved = on_moved
        self._on_open  = on_open

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsScenePositionChanges)
        self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
        self.setToolTip(scene_data.get("label", ""))
        self.setZValue(1)

    # ------------------------------------------------------------------
    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, _CARD_W, _CARD_H)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: N802
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

        # Title
        f_title = QFont()
        f_title.setPixelSize(13)
        f_title.setBold(True)
        painter.setFont(f_title)
        painter.setPen(_C_TITLE)
        label = self._data.get("label", "?")
        painter.drawText(
            QRectF(10, 8, _CARD_W - 20, 22),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            label,
        )

        # Profile type
        profile = str(self._data.get("level_profile") or "")
        prof_str = _PROFILE_LABEL.get(profile, profile or "—")
        f_sub = QFont()
        f_sub.setPixelSize(11)
        painter.setFont(f_sub)
        painter.setPen(_C_SUB)
        painter.drawText(QRectF(10, 32, _CARD_W - 20, 16), Qt.AlignmentFlag.AlignLeft, prof_str)

        # Dimensions  (level_size = {"w": N, "h": N})
        ls = self._data.get("level_size") or {}
        if isinstance(ls, dict):
            mw, mh = ls.get("w"), ls.get("h")
            if mw and mh:
                painter.drawText(
                    QRectF(10, 50, _CARD_W - 20, 16),
                    Qt.AlignmentFlag.AlignLeft,
                    f"{mw}×{mh} tiles",
                )

        # START badge (bottom-right)
        if self._is_start:
            f_badge = QFont()
            f_badge.setPixelSize(9)
            f_badge.setBold(True)
            painter.setFont(f_badge)
            painter.setPen(_C_BADGE)
            painter.drawText(
                QRectF(0, 0, _CARD_W - 7, _CARD_H - 5),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
                "▶ START",
            )

    # ------------------------------------------------------------------
    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        pos = self.pos()
        self._on_moved(self._data.get("id", ""), int(pos.x()), int(pos.y()))

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self._on_open(self._data.get("id", ""))

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            sc = self.scene()
            if sc:
                # Notify all arrows that geometry may have changed
                for item in sc.items():
                    if isinstance(item, SceneArrow):
                        item.prepareGeometryChange()
        return super().itemChange(change, value)


# ── SceneArrow ─────────────────────────────────────────────────────────────────

class SceneArrow(QGraphicsItem):
    """Directed arrow from one SceneCard to another, labelled with a condition."""

    def __init__(self, src: SceneCard, dst: SceneCard, label: str) -> None:
        super().__init__()
        self._src   = src
        self._dst   = dst
        self._label = label
        self.setZValue(0)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemHasNoContents, False)

    # ------------------------------------------------------------------
    @staticmethod
    def _edge_point(card: SceneCard, toward: QPointF) -> QPointF:
        """Return the point on card's scene-space border facing `toward`."""
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
        t  = min(tx, ty) - 3      # 3 px inset from border
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

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: N802
        sp, dp = self._endpoints()

        pen = QPen(_C_ARROW, 1.4, Qt.PenStyle.SolidLine)
        painter.setPen(pen)
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
            painter.setBrush(QBrush(_C_ARROW))
            painter.setPen(Qt.PenStyle.NoPen)
            path = QPainterPath()
            path.moveTo(dp)
            path.lineTo(p1)
            path.lineTo(p2)
            path.closeSubpath()
            painter.drawPath(path)

        # Condition label at midpoint
        if self._label:
            mx = (sp.x() + dp.x()) / 2
            my = (sp.y() + dp.y()) / 2
            f = QFont()
            f.setPixelSize(10)
            painter.setFont(f)
            painter.setPen(_C_ARROW_LBL)
            painter.drawText(
                QRectF(mx - 55, my - 10, 110, 20),
                Qt.AlignmentFlag.AlignCenter,
                self._label,
            )


# ── SceneMapScene ──────────────────────────────────────────────────────────────

class SceneMapScene(QGraphicsScene):

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setBackgroundBrush(QBrush(_C_BG))
        self._cards: dict[str, SceneCard] = {}

    # ------------------------------------------------------------------
    def build(
        self,
        scenes:      list[dict],
        start_label: str,
        on_moved:    Callable,
        on_open:     Callable,
    ) -> None:
        self.clear()
        self._cards.clear()

        has_any_pos = any(s.get("map_x") is not None for s in scenes)

        for i, sc in enumerate(scenes):
            is_start = sc.get("label", "") == start_label
            card = SceneCard(sc, is_start, on_moved, on_open)

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

        # Arrows: scan all triggers for goto_scene / warp_to
        # scene_to stores the destination scene id (UUID) directly
        seen: set[tuple] = set()          # deduplicate same src→dst pair

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
                self.addItem(SceneArrow(src_card, dst_card, cond))

    # ------------------------------------------------------------------
    def apply_auto_layout(self, scenes: list[dict]) -> None:
        """Reposition all cards in a clean grid, update scene data."""
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
        if isinstance(item, SceneCard):
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        else:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)


# ── SceneMapTab ────────────────────────────────────────────────────────────────

class SceneMapTab(ProjectPathMixin, QWidget):
    """Project-group tab: scene relationship map."""

    open_scene_requested = pyqtSignal(str)   # scene id

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

        tb_lay.addStretch()

        self._lbl_hint = QLabel(tr("map.hint"))
        self._lbl_hint.setStyleSheet("color:#555; font-size:11px;")
        tb_lay.addWidget(self._lbl_hint)

        root.addWidget(tb)

        # Canvas
        self._map_scene = SceneMapScene()
        self._map_view  = SceneMapView(self._map_scene)
        root.addWidget(self._map_view, 1)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Rebuild the canvas from current project_data."""
        scenes      = list((self._data or {}).get("scenes") or [])
        start_label = str(((self._data or {}).get("game") or {}).get("start_scene") or "").strip()
        self._map_scene.build(scenes, start_label, self._on_card_moved, self._on_card_open)
        self._map_view.fit_all()
        self._built = True

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
