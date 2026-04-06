"""
ui/tabs/hitbox_tab.py - Hitbox / collision editor (roadmap item B).

For each frame of a sprite, lets the user draw AABB bounding rectangles
(x, y, w, h) in sprite-local coordinates (origin = sprite center).

Exports as a C header:
    typedef struct { s8 x; s8 y; u8 w; u8 h; } NgpcSprHit;
    static const NgpcSprHit g_name_hit[N] = { ... };

Stores per-frame data in .ngpcraft:
    scenes[].sprites[].hurtboxes = [{x, y, w, h}, ...]
    scenes[].sprites[].hitboxes_attack_multi = [{x, y, w, h, damage?, knockback_x?, knockback_y?, active_start?, active_len?, priority?}, ...]
    scenes[].sprites[].hitboxes_attack = [{x, y, w, h, damage?, knockback_x?, knockback_y?, active_start?, active_len?, priority?}, ...]  # legacy fallback
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image
from PyQt6.QtCore import Qt, QPoint, QRect, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QInputDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.entity_roles import sprite_gameplay_role
from core.entity_templates import (
    find_template_for_file,
    new_entity_template,
    snapshot_sprite_fields,
    get_entity_templates,
)
from core.collision_boxes import (
    box_enabled,
    first_attack_hitbox,
    sprite_attack_hitboxes,
    sprite_hurtboxes,
    store_sprite_boxes,
)
from core.hitbox_export import ANIM_STATES, make_anims_h, make_ctrl_h, make_hitbox_h, make_motion_h, make_props_h
from core.sprite_named_anims_gen import make_named_anims_h
from i18n.lang import tr
from ui.context_help import ContextHelpBox

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HANDLE_R = 5          # handle radius in canvas pixels
_HITBOX_ALPHA = 55     # fill alpha (0-255)
_DEFAULT_ZOOM = 8
_ZOOM_MIN = 2
_ZOOM_MAX = 36


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pil_to_qpixmap(img: Image.Image) -> QPixmap:
    rgba = img.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimg = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


def _make_checker(w: int, h: int, sq: int = 4) -> QPixmap:
    pm = QPixmap(w, h)
    painter = QPainter(pm)
    for cy in range(0, h, sq):
        for cx in range(0, w, sq):
            c = QColor(200, 200, 200) if (cx // sq + cy // sq) % 2 == 0 else QColor(240, 240, 240)
            painter.fillRect(cx, cy, sq, sq, c)
    painter.end()
    return pm


def _fmt_tiles(px: int) -> str:
    return f"{(float(px) / 8.0):.2f}"


def _simulate_jump_rise_px(jump_force: int, rise_gravity: int) -> tuple[int, int]:
    vy = -max(0, int(jump_force))
    grav = max(1, int(rise_gravity))
    rise_px = 0
    rise_frames = 0
    while vy < 0:
        rise_px += -vy
        rise_frames += 1
        vy += grav
    return rise_px, rise_frames


def _platformer_jump_metrics(jump_force: int, gravity: int, max_fall_speed: int) -> dict[str, int | str]:
    gravity_eff = max(1, int(gravity))
    hold_gravity = max(1, int(gravity) // 2)
    tap_px, tap_frames = _simulate_jump_rise_px(jump_force, gravity_eff)
    hold_px, hold_frames = _simulate_jump_rise_px(jump_force, hold_gravity)
    fall_cap = min(max(0, int(max_fall_speed)), 6)
    return {
        "tap_px": tap_px,
        "tap_tiles": _fmt_tiles(tap_px),
        "tap_frames": tap_frames,
        "hold_px": hold_px,
        "hold_tiles": _fmt_tiles(hold_px),
        "hold_frames": hold_frames,
        "gravity_eff": gravity_eff,
        "hold_gravity": hold_gravity,
        "fall_cap": fall_cap,
    }


# ---------------------------------------------------------------------------
# HitboxCanvas
# ---------------------------------------------------------------------------

class HitboxCanvas(QWidget):
    """
    Displays a single sprite frame (zoomed) with a draggable red AABB.

    Coordinate system:
    - Origin (0, 0) = centre du sprite frame
    - x = bord gauche de la hitbox (peut être négatif)
    - y = bord haut de la hitbox  (peut être négatif)
    - w, h = dimensions (toujours > 0)
    """

    hitbox_changed = pyqtSignal(dict)  # {"x": int, "y": int, "w": int, "h": int}
    zoom_request   = pyqtSignal(int)   # +1 or -1

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._zoom: int = _DEFAULT_ZOOM
        self._frame_px: Optional[QPixmap] = None
        self._frame_w: int = 8
        self._frame_h: int = 8
        self._hb: dict = {"x": -4, "y": -4, "w": 8, "h": 8}
        self._secondary_hb: Optional[dict] = None
        self._box_kind: str = "hurtbox"

        # drag state
        self._drag_handle: Optional[str] = None
        self._drag_origin: Optional[QPoint] = None
        self._drag_hb_snap: Optional[dict] = None

        self.setMouseTracking(True)
        self.setMinimumSize(64, 64)

    # ------------------------------------------------------------------
    # Public setters
    # ------------------------------------------------------------------

    def set_frame(self, img: Image.Image, zoom: int = _DEFAULT_ZOOM) -> None:
        """Display a new sprite frame preview at the requested zoom level."""
        self._zoom = zoom
        self._frame_w = img.width
        self._frame_h = img.height
        self._frame_px = _pil_to_qpixmap(img)
        self.setFixedSize(img.width * zoom, img.height * zoom)
        self.update()

    def set_hitbox(self, hb: dict) -> None:
        """Replace the currently edited hitbox rectangle and repaint the canvas."""
        self._hb = {
            "x": int(hb.get("x", 0)),
            "y": int(hb.get("y", 0)),
            "w": max(1, int(hb.get("w", 8))),
            "h": max(1, int(hb.get("h", 8))),
            "enabled": bool(hb.get("enabled", True)),
        }
        self.update()

    def set_secondary_hitbox(self, hb: Optional[dict]) -> None:
        if not isinstance(hb, dict):
            self._secondary_hb = None
        else:
            self._secondary_hb = {
                "x": int(hb.get("x", 0)),
                "y": int(hb.get("y", 0)),
                "w": max(1, int(hb.get("w", 8))),
                "h": max(1, int(hb.get("h", 8))),
                "enabled": bool(hb.get("enabled", True)),
            }
        self.update()

    def set_box_kind(self, kind: str) -> None:
        self._box_kind = "attack" if str(kind) == "attack" else "hurtbox"
        self.update()

    def get_hitbox(self) -> dict:
        """Return a copy of the current hitbox rectangle in sprite-local coordinates."""
        return dict(self._hb)

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def _canvas_rect(self) -> QRect:
        """Hitbox rectangle in canvas (screen) pixels."""
        z = self._zoom
        cx = (self._frame_w // 2 + self._hb["x"]) * z
        cy = (self._frame_h // 2 + self._hb["y"]) * z
        cw = self._hb["w"] * z
        ch = self._hb["h"] * z
        return QRect(cx, cy, cw, ch)

    def _canvas_rect_from_box(self, hb: dict) -> QRect:
        z = self._zoom
        cx = (self._frame_w // 2 + int(hb.get("x", 0))) * z
        cy = (self._frame_h // 2 + int(hb.get("y", 0))) * z
        cw = max(1, int(hb.get("w", 8))) * z
        ch = max(1, int(hb.get("h", 8))) * z
        return QRect(cx, cy, cw, ch)

    def _handles(self) -> dict[str, QPoint]:
        r = self._canvas_rect()
        mx = r.left() + r.width() // 2
        my = r.top() + r.height() // 2
        return {
            "NW": QPoint(r.left(), r.top()),
            "N":  QPoint(mx, r.top()),
            "NE": QPoint(r.right(), r.top()),
            "E":  QPoint(r.right(), my),
            "SE": QPoint(r.right(), r.bottom()),
            "S":  QPoint(mx, r.bottom()),
            "SW": QPoint(r.left(), r.bottom()),
            "W":  QPoint(r.left(), my),
        }

    def _hit_handle(self, pos: QPoint) -> Optional[str]:
        for name, pt in self._handles().items():
            if (pos - pt).manhattanLength() <= _HANDLE_R + 4:
                return name
        return None

    def _hit_rect(self, pos: QPoint) -> bool:
        return self._canvas_rect().contains(pos)

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # type: ignore[override]
        """Render checkerboard, sprite frame, hitbox and resize handles."""
        z = self._zoom
        fw = self._frame_w * z
        fh = self._frame_h * z

        p = QPainter(self)

        # Checkerboard background
        p.drawPixmap(0, 0, _make_checker(fw, fh))

        # Sprite frame (nearest-neighbour upscale)
        if self._frame_px:
            p.drawPixmap(0, 0, self._frame_px.scaled(
                fw, fh,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            ))

        if self._secondary_hb is not None:
            sr = self._canvas_rect_from_box(self._secondary_hb)
            p.fillRect(sr, QColor(160, 160, 160, 35))
            p.setPen(QPen(QColor(140, 140, 140), 1, Qt.PenStyle.DashLine))
            p.drawRect(sr)

        active_enabled = bool(self._hb.get("enabled", True))
        if self._box_kind == "attack":
            fill_color = QColor(255, 96, 64, _HITBOX_ALPHA)
            border_color = QColor(224, 64, 32)
            handle_color = QColor(214, 64, 32)
        else:
            fill_color = QColor(64, 160, 255, _HITBOX_ALPHA)
            border_color = QColor(48, 112, 224)
            handle_color = QColor(48, 112, 224)
        if not active_enabled:
            fill_color = QColor(160, 160, 160, 35)
            border_color = QColor(150, 150, 150)
            handle_color = QColor(120, 120, 120)

        # Active box fill
        r = self._canvas_rect()
        p.fillRect(r, fill_color)

        # Active box border
        pen = QPen(border_color)
        pen.setWidth(2)
        p.setPen(pen)
        p.drawRect(r)

        # Origin crosshair (green dashed)
        ox = (self._frame_w // 2) * z
        oy = (self._frame_h // 2) * z
        p.setPen(QPen(QColor(0, 200, 50), 1, Qt.PenStyle.DashLine))
        p.drawLine(ox - 8, oy, ox + 8, oy)
        p.drawLine(ox, oy - 8, ox, oy + 8)

        # Handles (white circles with red border)
        p.setBrush(QBrush(QColor(255, 255, 255)))
        p.setPen(QPen(handle_color, 1))
        for pt in self._handles().values():
            p.drawEllipse(pt, _HANDLE_R, _HANDLE_R)

        p.end()

    # ------------------------------------------------------------------
    # Mouse interaction
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        """Begin moving/resizing the hitbox or start drawing a new rectangle."""
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.pos()
        h = self._hit_handle(pos)
        if h:
            self._drag_handle = h
        elif self._hit_rect(pos):
            self._drag_handle = "MOVE"
        else:
            # Start drawing a new rect anchored at click position
            z = self._zoom
            px = pos.x() // z - self._frame_w // 2
            py = pos.y() // z - self._frame_h // 2
            self._hb = {"x": px, "y": py, "w": 1, "h": 1}
            self._drag_handle = "SE"
        self._drag_origin = pos
        self._drag_hb_snap = dict(self._hb)
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        """Update cursor feedback or live-edit the hitbox while dragging."""
        if self._drag_handle is None:
            # Cursor shape feedback only
            h = self._hit_handle(event.pos())
            if h in ("NW", "SE"):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif h in ("NE", "SW"):
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif h in ("N", "S"):
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif h in ("E", "W"):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif self._hit_rect(event.pos()):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.setCursor(Qt.CursorShape.CrossCursor)
            return

        z = self._zoom
        delta = event.pos() - self._drag_origin
        dx = delta.x() // z
        dy = delta.y() // z
        s = self._drag_hb_snap

        if self._drag_handle == "MOVE":
            self._hb["x"] = s["x"] + dx
            self._hb["y"] = s["y"] + dy
        else:
            hb = dict(s)
            if "N" in self._drag_handle:
                new_h = s["h"] - dy
                if new_h >= 1:
                    hb["y"] = s["y"] + dy
                    hb["h"] = new_h
            if "S" in self._drag_handle:
                hb["h"] = max(1, s["h"] + dy)
            if "W" in self._drag_handle:
                new_w = s["w"] - dx
                if new_w >= 1:
                    hb["x"] = s["x"] + dx
                    hb["w"] = new_w
            if "E" in self._drag_handle:
                hb["w"] = max(1, s["w"] + dx)
            self._hb = hb

        self.update()
        self.hitbox_changed.emit(dict(self._hb))
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        """Finish the current drag gesture and emit the committed hitbox state."""
        if event.button() == Qt.MouseButton.LeftButton and self._drag_handle is not None:
            self._drag_handle = None
            self._drag_origin = None
            self._drag_hb_snap = None
            self.hitbox_changed.emit(dict(self._hb))
        event.accept()

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        """Translate mouse-wheel motion into zoom requests for the parent tab."""
        delta = event.angleDelta().y()
        if delta > 0:
            self.zoom_request.emit(1)
        elif delta < 0:
            self.zoom_request.emit(-1)
        event.accept()  # consumed → QScrollArea ne scroll pas


# ---------------------------------------------------------------------------
# HitboxTab
# ---------------------------------------------------------------------------

_PROPS_DEFAULTS: dict = {
    # Physique / Mouvement
    "max_speed":      4,    # u8 — vitesse max (unités jeu/tick)
    "sprint_speed":   8,    # u8 — vitesse max en sprint (>= max_speed)
    "accel":          8,    # u8 — accélération (ticks pour atteindre max_speed)
    "decel":         16,    # u8 — décélération au relâchement
    "weight":       128,    # u8 — masse : 0=léger, 255=lourd
    "friction":     255,    # u8 — adhérence : 0=glace, 255=grip total
    "brake_force":   32,    # u8 (fx16 raw) — décélération active bouton frein
    "jump_force":     0,    # u8 — force de saut initiale ; 0=ne peut pas sauter
    "gravity":        4,    # u8 — force de gravité (0=aucune, shmup/topdown)
    "max_fall_speed": 32,   # u8 — vitesse terminale de chute
    "move_type":      0,    # u8 — 0=4-dir, 1=8-dir, 2=side+jump, 3=forced_scroll
    "axis_x":         1,    # u8 bool — peut se déplacer en X
    "axis_y":         1,    # u8 bool — peut se déplacer en Y
    "can_jump":       0,    # u8 bool — accès au saut
    "gravity_dir":    0,    # u8 — 0=bas, 1=haut, 2=aucun
    # Projectiles
    "shoot_cooldown": 10,   # u8 — frames entre deux tirs
    "bullet_speed":    4,   # s8 — vitesse bullet px/frame
    "bullet_ttl":     60,   # u8 — durée de vie bullet en frames (0=illimité)
    "bullet_w":        4,   # u8 — largeur hitbox bullet (px)
    "bullet_h":        4,   # u8 — hauteur hitbox bullet (px)
    # Combat
    "hp":             1,    # u8 — points de vie ; 0=invincible
    "damage":         0,    # u8 — dommages au contact
    "inv_frames":    30,    # u8 — frames d'invincibilité après dégât
    # IA
    "behavior":       0,    # u8 — comportement par défaut : 0=patrol,1=chase,2=fixed,3=random
    # Divers
    "score":          0,    # u8 — valeur score ×10 sur défaite (0–2550 pts)
    "anim_spd":       4,    # u8 — ticks par frame d'anim (1–60 ; 0=statique)
    "type_id":        0,    # u8 — tag de type entité (défini par le jeu)
    "flip_x_dir":     0,    # u8 bool — flip horizontal auto selon la direction X
    # Top-down control/move (player only)
    "td_control":     0,    # u8 — 0=absolute, 1=relative (rotation L/R)
    "td_move":        0,    # u8 — 0=direct, 1=advance, 2=vehicle
    # Top-down vehicle physics (active when td_move=2)
    "td_speed_max":          48,  # u8 (×16) — vitesse max vehicle (avant)
    "td_speed_max_reverse":   0,  # u8 (×16) — vitesse max marche arrière (0 = même que td_speed_max)
    "td_accel":               4,  # u8 (×16) — accélération par frame
    "td_brake":               6,  # u8 (×16) — décélération active (frein)
    "td_friction":            2,  # u8 (×16) — friction passive par frame
    "td_turn_rate":           4,  # u8 — frames entre chaque step de rotation (1=max)
    "td_decel_rate":          1,  # u8 — frames entre chaque tick de friction (1=chaque frame)
}


class HitboxTab(QWidget):
    """Hitbox editor tab — roadmap item B."""

    hitboxes_changed = pyqtSignal()  # emitted when data is saved → triggers project save

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project_data: dict = {}
        self._base_dir: Optional[Path] = None
        self._scene: Optional[dict] = None
        self._sprite_meta: Optional[dict] = None
        self._file_path: Optional[Path] = None
        self._full_img: Optional[Image.Image] = None
        self._frame_w: int = 8
        self._frame_h: int = 8
        self._frame_count: int = 1
        self._current_frame: int = 0
        self._current_attack_box: int = 0
        self._hurtboxes: list[dict] = []
        self._attack_hitboxes: list[dict] = []
        self._active_box_kind: str = "hurtbox"
        self._props: dict = {}
        self._prop_widgets: dict[str, tuple[QCheckBox, QSpinBox]] = {}
        self._ctrl: dict = {}                  # {"role": str, "left": str|None, ...}
        self._ctrl_action_cbs: dict[str, QComboBox] = {}  # pad_name → combo of actions
        self._anims: dict = {}                 # {state: {start,count,loop,spd}}
        # _anim_rows[state] = (enable_cb, start_sb, count_sb, loop_cb, spd_sb, play_btn)
        self._anim_rows: dict[str, tuple] = {}
        self._motion_patterns: list[dict] = []  # [{name, steps, window, anim}]
        # dir_frames: {"mode": "none"|"4dir"|"8dir", "N":f, "NE":f, "E":f, "SE":f, "S":f}
        self._dir_frames: dict = {}
        self._dir_frame_widgets: dict[str, "QSpinBox"] = {}   # key→spinbox
        self._dir_mode_combo: "QComboBox | None" = None
        self._zoom: int = _DEFAULT_ZOOM
        self._updating_spinboxes: bool = False
        self._updating_props: bool = False
        self._updating_frame_size: bool = False
        self._rail_btns: list[tuple[QToolButton, str]] = []  # (button, rel_file)
        self._rail_anim_timers: list[QTimer] = []           # A-2: per-thumb anim timers
        # Anim preview state
        self._preview_state: Optional[str] = None
        self._preview_tick: int = 0

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(0)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        outer.addWidget(self._splitter)

        # Preview timer (drives per-state anim playback in canvas)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(False)
        self._preview_timer.timeout.connect(self._on_preview_tick)

        # ---- RAIL: sprite thumbnail list (hidden until a scene is active) ----
        self._rail_scroll = QScrollArea()
        self._rail_scroll.setMinimumWidth(60)
        self._rail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rail_scroll.setWidgetResizable(True)
        self._rail_scroll.setVisible(False)
        _rail_widget = QWidget()
        self._rail_layout = QVBoxLayout(_rail_widget)
        self._rail_layout.setContentsMargins(4, 4, 4, 4)
        self._rail_layout.setSpacing(6)
        self._rail_scroll.setWidget(_rail_widget)
        self._splitter.addWidget(self._rail_scroll)

        # ---- LEFT: canvas + frame navigation --------------------------------
        left = QVBoxLayout()

        self._lbl_file = QLabel(tr("hitbox.no_sprite"))
        self._lbl_file.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_file.setStyleSheet("color: gray; font-style: italic;")
        left.addWidget(self._lbl_file)

        # Frame size row (editable — allows per-frame split in free mode)
        fsize_row = QHBoxLayout()
        fsize_row.setSpacing(4)
        fsize_lbl = QLabel(tr("hitbox.frame_size_lbl"))
        fsize_lbl.setStyleSheet("font-size: 10px; color: #aaa;")
        fsize_row.addWidget(fsize_lbl)
        self._sb_fw = QSpinBox()
        self._sb_fw.setRange(1, 4096)
        self._sb_fw.setFixedWidth(52)
        self._sb_fw.setToolTip(tr("hitbox.tt_frame_w"))
        fsize_row.addWidget(self._sb_fw)
        fsize_x = QLabel("×")
        fsize_x.setStyleSheet("font-size: 10px; color: #aaa;")
        fsize_row.addWidget(fsize_x)
        self._sb_fh = QSpinBox()
        self._sb_fh.setRange(1, 4096)
        self._sb_fh.setFixedWidth(52)
        self._sb_fh.setToolTip(tr("hitbox.tt_frame_h"))
        fsize_row.addWidget(self._sb_fh)
        self._lbl_fcount = QLabel("")
        self._lbl_fcount.setStyleSheet("font-size: 10px; color: #888;")
        fsize_row.addWidget(self._lbl_fcount)

        # Preset combo — common NGPC sprite frame sizes
        self._cb_frame_preset = QComboBox()
        self._cb_frame_preset.setFixedWidth(68)
        self._cb_frame_preset.setToolTip(tr("hitbox.tt_frame_preset"))
        for label, fw, fh in [
            ("—",    0,  0),
            ("8×8",  8,  8),
            ("8×16", 8, 16),
            ("16×8", 16, 8),
            ("16×16",16, 16),
            ("16×24",16, 24),
            ("16×32",16, 32),
            ("24×24",24, 24),
            ("32×32",32, 32),
        ]:
            self._cb_frame_preset.addItem(label, (fw, fh))
        fsize_row.addWidget(self._cb_frame_preset)
        fsize_row.addStretch()
        left.addLayout(fsize_row)
        self._sb_fw.valueChanged.connect(self._on_frame_size_changed)
        self._sb_fh.valueChanged.connect(self._on_frame_size_changed)
        self._cb_frame_preset.currentIndexChanged.connect(self._on_frame_preset_selected)

        self._scroll = QScrollArea()
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setWidgetResizable(False)
        self._canvas = HitboxCanvas()
        self._canvas.hitbox_changed.connect(self._on_canvas_hitbox_changed)
        self._canvas.zoom_request.connect(self._on_zoom_request)
        self._scroll.setWidget(self._canvas)
        left.addWidget(self._scroll, 1)

        # Frame navigation row
        nav = QHBoxLayout()
        self._btn_prev = QPushButton("◀")
        self._btn_prev.setFixedWidth(36)
        self._btn_prev.setToolTip(tr("hitbox.prev_frame"))
        self._btn_prev.clicked.connect(self._prev_frame)
        nav.addWidget(self._btn_prev)

        self._lbl_frame = QLabel("1 / 1")
        self._lbl_frame.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav.addWidget(self._lbl_frame, 1)

        self._btn_next = QPushButton("▶")
        self._btn_next.setFixedWidth(36)
        self._btn_next.setToolTip(tr("hitbox.next_frame"))
        self._btn_next.clicked.connect(self._next_frame)
        nav.addWidget(self._btn_next)
        left.addLayout(nav)

        # Zoom row
        zoom_row = QHBoxLayout()
        self._btn_zoom_out = QPushButton("−")
        self._btn_zoom_out.setFixedWidth(28)
        self._btn_zoom_out.setToolTip(tr("hitbox.zoom_out"))
        self._btn_zoom_out.clicked.connect(self._zoom_out)
        zoom_row.addWidget(self._btn_zoom_out)
        self._lbl_zoom = QLabel(f"×{_DEFAULT_ZOOM}")
        self._lbl_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zoom_row.addWidget(self._lbl_zoom, 1)
        self._btn_zoom_in = QPushButton("+")
        self._btn_zoom_in.setFixedWidth(28)
        self._btn_zoom_in.setToolTip(tr("hitbox.zoom_in"))
        self._btn_zoom_in.clicked.connect(self._zoom_in)
        zoom_row.addWidget(self._btn_zoom_in)
        left.addLayout(zoom_row)

        left_w = QWidget()
        left_w.setLayout(left)
        left_w.setMinimumWidth(120)
        self._splitter.addWidget(left_w)

        # ---- RIGHT: spinboxes + actions -------------------------------------
        right = QVBoxLayout()
        right.setSpacing(8)

        self._ctx_hitbox = ContextHelpBox(
            tr("hitbox.ctx_workflow_title"),
            tr("hitbox.ctx_workflow_body"),
            self,
        )
        right.addWidget(self._ctx_hitbox)

        self._lbl_checklist = QLabel("")
        self._lbl_checklist.setWordWrap(True)
        self._lbl_checklist.setTextFormat(Qt.TextFormat.RichText)
        self._lbl_checklist.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        right.addWidget(self._lbl_checklist)

        # Coordinates group
        grp = QGroupBox(tr("hitbox.coords"))
        grp.setCheckable(True)
        grp.setChecked(True)
        _grp_outer = QVBoxLayout(grp)
        _grp_outer.setContentsMargins(0, 0, 0, 0)
        _grp_outer.setSpacing(0)
        _grp_coords_content = QWidget()
        g_l = QVBoxLayout(_grp_coords_content)
        g_l.setSpacing(4)
        _grp_outer.addWidget(_grp_coords_content)
        grp.toggled.connect(_grp_coords_content.setVisible)

        self._tabs_box_kind = QTabWidget()
        self._tabs_box_kind.addTab(QWidget(), tr("hitbox.box_kind_hurtbox"))
        self._tabs_box_kind.addTab(QWidget(), tr("hitbox.box_kind_attack"))
        self._tabs_box_kind.currentChanged.connect(self._on_box_kind_changed)
        g_l.addWidget(self._tabs_box_kind)

        self._attack_nav_row = QHBoxLayout()
        self._btn_attack_prev = QPushButton("◀")
        self._btn_attack_prev.setFixedWidth(30)
        self._btn_attack_prev.setToolTip(tr("hitbox.attack_box_prev_tt"))
        self._btn_attack_prev.clicked.connect(self._prev_attack_box)
        self._attack_nav_row.addWidget(self._btn_attack_prev)
        self._lbl_attack_box = QLabel("")
        self._lbl_attack_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._attack_nav_row.addWidget(self._lbl_attack_box, 1)
        self._btn_attack_add = QPushButton("+")
        self._btn_attack_add.setFixedWidth(30)
        self._btn_attack_add.setToolTip(tr("hitbox.attack_box_add_tt"))
        self._btn_attack_add.clicked.connect(self._add_attack_box)
        self._attack_nav_row.addWidget(self._btn_attack_add)
        self._btn_attack_remove = QPushButton("−")
        self._btn_attack_remove.setFixedWidth(30)
        self._btn_attack_remove.setToolTip(tr("hitbox.attack_box_remove_tt"))
        self._btn_attack_remove.clicked.connect(self._remove_attack_box)
        self._attack_nav_row.addWidget(self._btn_attack_remove)
        self._btn_attack_next = QPushButton("▶")
        self._btn_attack_next.setFixedWidth(30)
        self._btn_attack_next.setToolTip(tr("hitbox.attack_box_next_tt"))
        self._btn_attack_next.clicked.connect(self._next_attack_box)
        self._attack_nav_row.addWidget(self._btn_attack_next)
        g_l.addLayout(self._attack_nav_row)

        def _spin_row(label_key: str, vmin: int, vmax: int) -> QSpinBox:
            row = QHBoxLayout()
            lbl = QLabel(tr(label_key))
            lbl.setFixedWidth(22)
            row.addWidget(lbl)
            sb = QSpinBox()
            sb.setRange(vmin, vmax)
            row.addWidget(sb)
            g_l.addLayout(row)
            return sb

        self._sb_x = _spin_row("hitbox.x", -128, 127)
        self._sb_y = _spin_row("hitbox.y", -128, 127)
        self._sb_w = _spin_row("hitbox.w", 1, 255)
        self._sb_h = _spin_row("hitbox.h", 1, 255)
        for sb in (self._sb_x, self._sb_y, self._sb_w, self._sb_h):
            sb.valueChanged.connect(self._on_spinbox_changed)

        self._cb_box_enabled = QCheckBox(tr("hitbox.box_enabled"))
        self._cb_box_enabled.setToolTip(tr("hitbox.box_enabled_tt"))
        self._cb_box_enabled.toggled.connect(self._on_box_enabled_changed)
        g_l.addWidget(self._cb_box_enabled)

        self._row_attack_damage = QHBoxLayout()
        self._lbl_attack_damage = QLabel(tr("hitbox.attack_damage"))
        self._lbl_attack_damage.setToolTip(tr("hitbox.attack_damage_tt"))
        self._row_attack_damage.addWidget(self._lbl_attack_damage)
        self._sb_attack_damage = QSpinBox()
        self._sb_attack_damage.setRange(0, 255)
        self._sb_attack_damage.setSpecialValueText(tr("hitbox.attack_damage_default"))
        self._sb_attack_damage.setToolTip(tr("hitbox.attack_damage_tt"))
        self._sb_attack_damage.valueChanged.connect(self._on_attack_damage_changed)
        self._row_attack_damage.addWidget(self._sb_attack_damage)
        g_l.addLayout(self._row_attack_damage)

        self._row_attack_kbx = QHBoxLayout()
        self._lbl_attack_kbx = QLabel(tr("hitbox.attack_kbx"))
        self._lbl_attack_kbx.setToolTip(tr("hitbox.attack_kbx_tt"))
        self._row_attack_kbx.addWidget(self._lbl_attack_kbx)
        self._sb_attack_kbx = QSpinBox()
        self._sb_attack_kbx.setRange(-127, 127)
        self._sb_attack_kbx.setToolTip(tr("hitbox.attack_kbx_tt"))
        self._sb_attack_kbx.valueChanged.connect(self._on_attack_knockback_changed)
        self._row_attack_kbx.addWidget(self._sb_attack_kbx)
        g_l.addLayout(self._row_attack_kbx)

        self._row_attack_kby = QHBoxLayout()
        self._lbl_attack_kby = QLabel(tr("hitbox.attack_kby"))
        self._lbl_attack_kby.setToolTip(tr("hitbox.attack_kby_tt"))
        self._row_attack_kby.addWidget(self._lbl_attack_kby)
        self._sb_attack_kby = QSpinBox()
        self._sb_attack_kby.setRange(-127, 127)
        self._sb_attack_kby.setToolTip(tr("hitbox.attack_kby_tt"))
        self._sb_attack_kby.valueChanged.connect(self._on_attack_knockback_changed)
        self._row_attack_kby.addWidget(self._sb_attack_kby)
        g_l.addLayout(self._row_attack_kby)

        self._row_attack_prio = QHBoxLayout()
        self._lbl_attack_prio = QLabel(tr("hitbox.attack_priority"))
        self._lbl_attack_prio.setToolTip(tr("hitbox.attack_priority_tt"))
        self._row_attack_prio.addWidget(self._lbl_attack_prio)
        self._sb_attack_prio = QSpinBox()
        self._sb_attack_prio.setRange(0, 255)
        self._sb_attack_prio.setToolTip(tr("hitbox.attack_priority_tt"))
        self._sb_attack_prio.valueChanged.connect(self._on_attack_window_changed)
        self._row_attack_prio.addWidget(self._sb_attack_prio)
        g_l.addLayout(self._row_attack_prio)

        self._row_attack_anim_state = QHBoxLayout()
        self._lbl_attack_anim_state = QLabel(tr("hitbox.attack_anim_state"))
        self._lbl_attack_anim_state.setToolTip(tr("hitbox.attack_anim_state_tt"))
        self._row_attack_anim_state.addWidget(self._lbl_attack_anim_state)
        self._cb_attack_anim_state = QComboBox()
        self._cb_attack_anim_state.addItem(tr("hitbox.attack_anim_any"), 0xFF)
        for _asi, _asn in enumerate(ANIM_STATES):
            self._cb_attack_anim_state.addItem(_asn, _asi)
        self._cb_attack_anim_state.setToolTip(tr("hitbox.attack_anim_state_tt"))
        self._cb_attack_anim_state.currentIndexChanged.connect(self._on_attack_window_changed)
        self._row_attack_anim_state.addWidget(self._cb_attack_anim_state)
        g_l.addLayout(self._row_attack_anim_state)

        self._row_attack_start = QHBoxLayout()
        self._lbl_attack_start = QLabel(tr("hitbox.attack_window_start"))
        self._lbl_attack_start.setToolTip(tr("hitbox.attack_window_start_tt"))
        self._row_attack_start.addWidget(self._lbl_attack_start)
        self._sb_attack_start = QSpinBox()
        self._sb_attack_start.setRange(0, 255)
        self._sb_attack_start.setToolTip(tr("hitbox.attack_window_start_tt"))
        self._sb_attack_start.valueChanged.connect(self._on_attack_window_changed)
        self._row_attack_start.addWidget(self._sb_attack_start)
        g_l.addLayout(self._row_attack_start)

        self._row_attack_len = QHBoxLayout()
        self._lbl_attack_len = QLabel(tr("hitbox.attack_window_len"))
        self._lbl_attack_len.setToolTip(tr("hitbox.attack_window_len_tt"))
        self._row_attack_len.addWidget(self._lbl_attack_len)
        self._sb_attack_len = QSpinBox()
        self._sb_attack_len.setRange(0, 255)
        self._sb_attack_len.setSpecialValueText(tr("hitbox.attack_window_len_default"))
        self._sb_attack_len.setToolTip(tr("hitbox.attack_window_len_tt"))
        self._sb_attack_len.valueChanged.connect(self._on_attack_window_changed)
        self._row_attack_len.addWidget(self._sb_attack_len)
        g_l.addLayout(self._row_attack_len)
        right.addWidget(grp)

        # Origin hint
        self._lbl_box_hint = QLabel(tr("hitbox.origin_hint_hurtbox"))
        hint = self._lbl_box_hint
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 10px;")
        right.addWidget(hint)

        self._lbl_usage_hint = QLabel("")
        self._lbl_usage_hint.setWordWrap(True)
        self._lbl_usage_hint.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        right.addWidget(self._lbl_usage_hint)

        self._btn_copy_other = QPushButton("")
        self._btn_copy_other.clicked.connect(self._copy_from_other_box)
        right.addWidget(self._btn_copy_other)

        # Copy to all frames
        self._btn_copy_all = QPushButton(tr("hitbox.copy_all"))
        self._btn_copy_all.setToolTip(tr("hitbox.copy_all_tip"))
        self._btn_copy_all.clicked.connect(self._copy_to_all)
        right.addWidget(self._btn_copy_all)

        right.addSpacing(8)

        # ---- Sprite properties (per-sprite, not per-frame) ------------------

        def _props_grp(title_key: str, parent_layout: QVBoxLayout) -> QVBoxLayout:
            grp = QGroupBox(tr(title_key))
            grp.setCheckable(True)
            grp.setChecked(True)
            grp_outer = QVBoxLayout(grp)
            grp_outer.setContentsMargins(0, 0, 0, 0)
            grp_outer.setSpacing(0)
            content_w = QWidget()
            gl = QVBoxLayout(content_w)
            gl.setSpacing(3)
            grp_outer.addWidget(content_w)
            grp.toggled.connect(content_w.setVisible)
            parent_layout.addWidget(grp)
            return gl

        def _psb(gl: QVBoxLayout, prop_key: str, label_key: str, tooltip_key: str, vmax: int = 255) -> None:
            """Build one prop row: [checkbox] [label] [spinbox]. Stores in _prop_widgets."""
            row = QHBoxLayout()
            cb = QCheckBox()
            cb.setFixedWidth(18)
            cb.setToolTip(tr(tooltip_key))
            row.addWidget(cb)
            lbl = QLabel(tr(label_key))
            lbl.setFixedWidth(44)
            lbl.setToolTip(tr(tooltip_key))
            row.addWidget(lbl)
            sb = QSpinBox()
            sb.setRange(0, vmax)
            sb.setEnabled(False)  # starts disabled until checked
            sb.setToolTip(tr(tooltip_key))
            row.addWidget(sb)
            gl.addLayout(row)
            cb.toggled.connect(lambda checked, s=sb: s.setEnabled(checked))
            cb.toggled.connect(self._on_props_changed)
            sb.valueChanged.connect(self._on_props_changed)
            self._prop_widgets[prop_key] = (cb, sb)

        # Group 1 — Physique / Mouvement
        gl_phy = _props_grp("hitbox.grp_physics", right)
        _psb(gl_phy, "max_speed",      "hitbox.max_speed",      "hitbox.tt_max_speed")
        _psb(gl_phy, "sprint_speed",   "hitbox.sprint_speed",   "hitbox.tt_sprint_speed")
        _psb(gl_phy, "accel",          "hitbox.accel",          "hitbox.tt_accel")
        _psb(gl_phy, "decel",          "hitbox.decel",          "hitbox.tt_decel")
        _psb(gl_phy, "weight",         "hitbox.weight",         "hitbox.tt_weight")
        _psb(gl_phy, "friction",       "hitbox.friction",       "hitbox.tt_friction")
        _psb(gl_phy, "brake_force",    "hitbox.brake_force",    "hitbox.tt_brake_force")
        _psb(gl_phy, "jump_force",     "hitbox.jump_force",     "hitbox.tt_jump_force")
        _psb(gl_phy, "gravity",        "hitbox.gravity",        "hitbox.tt_gravity")
        _psb(gl_phy, "max_fall_speed", "hitbox.max_fall_speed", "hitbox.tt_max_fall_speed")
        _psb(gl_phy, "move_type",      "hitbox.move_type",      "hitbox.tt_move_type",      vmax=3)
        _psb(gl_phy, "axis_x",         "hitbox.axis_x",         "hitbox.tt_axis_x",         vmax=1)
        _psb(gl_phy, "axis_y",         "hitbox.axis_y",         "hitbox.tt_axis_y",         vmax=1)
        _psb(gl_phy, "can_jump",       "hitbox.can_jump",       "hitbox.tt_can_jump",       vmax=1)
        _psb(gl_phy, "gravity_dir",    "hitbox.gravity_dir",    "hitbox.tt_gravity_dir",    vmax=2)

        # Group 2 — Projectiles
        gl_proj = _props_grp("hitbox.grp_projectiles", right)
        _psb(gl_proj, "shoot_cooldown", "hitbox.shoot_cooldown", "hitbox.tt_shoot_cooldown")
        _psb(gl_proj, "bullet_speed",   "hitbox.bullet_speed",   "hitbox.tt_bullet_speed")
        _psb(gl_proj, "bullet_ttl",     "hitbox.bullet_ttl",     "hitbox.tt_bullet_ttl")
        _psb(gl_proj, "bullet_w",       "hitbox.bullet_w",       "hitbox.tt_bullet_w")
        _psb(gl_proj, "bullet_h",       "hitbox.bullet_h",       "hitbox.tt_bullet_h")

        # Group 3 — Combat
        gl_cbt = _props_grp("hitbox.grp_combat", right)
        _psb(gl_cbt, "hp",         "hitbox.hp",         "hitbox.tt_hp")
        _psb(gl_cbt, "damage",     "hitbox.damage",     "hitbox.tt_damage")
        _psb(gl_cbt, "inv_frames", "hitbox.inv_frames", "hitbox.tt_inv_frames")

        # Group 4 — Top-down (player only)
        gl_td = _props_grp("hitbox.grp_topdown", right)
        _psb(gl_td, "td_control",          "hitbox.td_control",          "hitbox.tt_td_control",          vmax=1)
        _psb(gl_td, "td_move",             "hitbox.td_move",             "hitbox.tt_td_move",              vmax=2)
        _psb(gl_td, "td_speed_max",        "hitbox.td_speed_max",        "hitbox.tt_td_speed_max")
        _psb(gl_td, "td_speed_max_reverse","hitbox.td_speed_max_reverse","hitbox.tt_td_speed_max_reverse")
        _psb(gl_td, "td_accel",            "hitbox.td_accel",            "hitbox.tt_td_accel")
        _psb(gl_td, "td_brake",            "hitbox.td_brake",            "hitbox.tt_td_brake")
        _psb(gl_td, "td_friction",         "hitbox.td_friction",         "hitbox.tt_td_friction")
        _psb(gl_td, "td_turn_rate",        "hitbox.td_turn_rate",        "hitbox.tt_td_turn_rate")
        _psb(gl_td, "td_decel_rate",       "hitbox.td_decel_rate",       "hitbox.tt_td_decel_rate")

        # Group 5 — Divers
        gl_misc = _props_grp("hitbox.grp_misc", right)
        _psb(gl_misc, "behavior", "hitbox.behavior", "hitbox.tt_behavior", vmax=3)
        _psb(gl_misc, "score",    "hitbox.score",    "hitbox.tt_score")
        _psb(gl_misc, "anim_spd", "hitbox.anim_spd", "hitbox.tt_anim_spd")
        _psb(gl_misc, "type_id",  "hitbox.type_id",  "hitbox.tt_type_id")
        _psb(gl_misc, "flip_x_dir", "hitbox.flip_x_dir", "hitbox.tt_flip_x_dir", vmax=1)

        props_hint = QLabel(tr("hitbox.props_hint"))
        props_hint.setWordWrap(True)
        props_hint.setStyleSheet("color: gray; font-size: 10px;")
        right.addWidget(props_hint)

        self._lbl_jump_summary = QLabel("")
        self._lbl_jump_summary.setWordWrap(True)
        self._lbl_jump_summary.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        right.addWidget(self._lbl_jump_summary)

        right.addSpacing(8)

        # ---- Controller group -------------------------------------------
        # Action options list for each pad-button combo
        _ACTION_OPTIONS: list[tuple[str, str | None]] = [
            (tr("hitbox.ctrl_pad_none"),    None),
            (tr("hitbox.ctrl_act_left"),    "left"),
            (tr("hitbox.ctrl_act_right"),   "right"),
            (tr("hitbox.ctrl_act_up"),      "up"),
            (tr("hitbox.ctrl_act_down"),    "down"),
            (tr("hitbox.ctrl_act_jump"),    "jump"),
            (tr("hitbox.ctrl_act_action"),  "action"),
            (tr("hitbox.ctrl_act_accel"),   "accel"),
            (tr("hitbox.ctrl_act_brake"),   "brake"),
            (tr("hitbox.ctrl_act_sprint"),  "sprint"),
            (tr("hitbox.ctrl_act_shoot"),   "shoot"),
        ]
        _PAD_ROWS: list[str] = [
            "PAD_UP", "PAD_DOWN", "PAD_LEFT", "PAD_RIGHT",
            "PAD_A", "PAD_B", "PAD_OPTION",
        ]

        ctrl_grp = QGroupBox(tr("hitbox.grp_controller"))
        ctrl_grp.setToolTip(tr("hitbox.tt_ctrl_role"))
        ctrl_grp.setCheckable(True)
        ctrl_grp.setChecked(True)
        _ctrl_outer = QVBoxLayout(ctrl_grp)
        _ctrl_outer.setContentsMargins(0, 0, 0, 0)
        _ctrl_outer.setSpacing(0)
        _ctrl_content = QWidget()
        gl_ctrl = QVBoxLayout(_ctrl_content)
        gl_ctrl.setSpacing(4)
        _ctrl_outer.addWidget(_ctrl_content)
        ctrl_grp.toggled.connect(_ctrl_content.setVisible)

        # Role row
        role_row = QHBoxLayout()
        role_lbl = QLabel(tr("hitbox.ctrl_role"))
        role_lbl.setFixedWidth(76)
        role_row.addWidget(role_lbl)
        self._ctrl_role_cb = QComboBox()
        self._populate_ctrl_role_combo()
        role_row.addWidget(self._ctrl_role_cb)
        gl_ctrl.addLayout(role_row)

        self._lbl_ctrl_hint = QLabel("")
        self._lbl_ctrl_hint.setWordWrap(True)
        self._lbl_ctrl_hint.setStyleSheet("color: gray; font-size: 10px;")
        gl_ctrl.addWidget(self._lbl_ctrl_hint)
        self._lbl_ctrl_gameplay = QLabel("")
        self._lbl_ctrl_gameplay.setWordWrap(True)
        self._lbl_ctrl_gameplay.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        gl_ctrl.addWidget(self._lbl_ctrl_gameplay)

        # Bindings sub-widget (hidden when role=None)
        # UI is button-centric: one row per physical PAD button → choose action
        self._ctrl_bindings_widget = QWidget()
        bl = QVBoxLayout(self._ctrl_bindings_widget)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(3)

        def _pad_row(pad_name: str) -> QComboBox:
            row = QHBoxLayout()
            lbl = QLabel(pad_name)
            lbl.setFixedWidth(72)
            lbl.setStyleSheet("font-family: monospace; font-size: 10px;")
            row.addWidget(lbl)
            cb = QComboBox()
            for disp, val in _ACTION_OPTIONS:
                cb.addItem(disp, val)
            cb.currentIndexChanged.connect(self._on_ctrl_changed)
            row.addWidget(cb)
            bl.addLayout(row)
            return cb

        for _pad in _PAD_ROWS:
            self._ctrl_action_cbs[_pad] = _pad_row(_pad)

        # Preset button
        _preset_row = QHBoxLayout()
        _preset_row.addStretch()
        self._btn_ctrl_preset = QPushButton(tr("hitbox.ctrl_preset"))
        self._btn_ctrl_preset.setToolTip(tr("hitbox.ctrl_preset_tt"))
        self._btn_ctrl_preset.clicked.connect(self._show_ctrl_preset_menu)
        _preset_row.addWidget(self._btn_ctrl_preset)
        bl.addLayout(_preset_row)

        gl_ctrl.addWidget(self._ctrl_bindings_widget)
        right.addWidget(ctrl_grp)

        self._ctrl_role_cb.currentIndexChanged.connect(self._on_ctrl_role_changed)
        self._ctrl_bindings_widget.setVisible(False)
        self._refresh_ctrl_ui()

        right.addSpacing(8)

        # ---- Motion Patterns group (ngpc_motion) ------------------------------
        motion_grp = QGroupBox(tr("hitbox.grp_motion"))
        motion_grp.setToolTip(tr("hitbox.tt_motion"))
        motion_grp.setCheckable(True)
        motion_grp.setChecked(True)
        _motion_outer = QVBoxLayout(motion_grp)
        _motion_outer.setContentsMargins(0, 0, 0, 0)
        _motion_outer.setSpacing(0)
        _motion_content = QWidget()
        _motion_vbox = QVBoxLayout(_motion_content)
        _motion_vbox.setSpacing(2)
        _motion_vbox.setContentsMargins(4, 4, 4, 4)
        _motion_outer.addWidget(_motion_content)
        motion_grp.toggled.connect(_motion_content.setVisible)

        _motion_hint = QLabel(tr("hitbox.motion_hint"))
        _motion_hint.setWordWrap(True)
        _motion_hint.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        _motion_vbox.addWidget(_motion_hint)

        self._motion_table = QTableWidget(0, 4)
        self._motion_table.setHorizontalHeaderLabels([
            tr("hitbox.motion_col_name"),
            tr("hitbox.motion_col_steps"),
            tr("hitbox.motion_col_window"),
            tr("hitbox.motion_col_anim"),
        ])
        self._motion_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self._motion_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._motion_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents)
        self._motion_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents)
        self._motion_table.setMaximumHeight(130)
        self._motion_table.setToolTip(tr("hitbox.tt_motion_table"))
        self._motion_table.itemChanged.connect(self._on_motion_changed)
        _motion_vbox.addWidget(self._motion_table)

        _motion_notation = QLabel(tr("hitbox.motion_notation"))
        _motion_notation.setWordWrap(True)
        _motion_notation.setStyleSheet("color: #666; font-size: 9px;")
        _motion_vbox.addWidget(_motion_notation)

        _motion_btn_row = QHBoxLayout()
        self._btn_motion_add = QPushButton(tr("hitbox.motion_add"))
        self._btn_motion_del = QPushButton(tr("hitbox.motion_del"))
        self._btn_motion_preset = QPushButton(tr("hitbox.motion_preset"))
        self._btn_motion_add.setToolTip(tr("hitbox.tt_motion_add"))
        self._btn_motion_del.setToolTip(tr("hitbox.tt_motion_del"))
        self._btn_motion_preset.setToolTip(tr("hitbox.tt_motion_preset"))
        self._btn_motion_add.clicked.connect(self._add_motion_pattern)
        self._btn_motion_del.clicked.connect(self._del_motion_pattern)
        self._btn_motion_preset.clicked.connect(self._show_motion_preset_menu)
        _motion_btn_row.addWidget(self._btn_motion_add)
        _motion_btn_row.addWidget(self._btn_motion_del)
        _motion_btn_row.addStretch()
        _motion_btn_row.addWidget(self._btn_motion_preset)
        _motion_vbox.addLayout(_motion_btn_row)

        right.addWidget(motion_grp)
        right.addSpacing(8)

        # ---- Animation States group ------------------------------------------
        anim_grp = QGroupBox(tr("hitbox.grp_anims"))
        anim_grp.setToolTip(tr("hitbox.tt_anims"))
        anim_grp.setCheckable(True)
        anim_grp.setChecked(True)
        _anim_outer = QVBoxLayout(anim_grp)
        _anim_outer.setContentsMargins(0, 0, 0, 0)
        _anim_outer.setSpacing(0)
        _anim_content = QWidget()
        gl_anim = QVBoxLayout(_anim_content)
        gl_anim.setSpacing(2)
        gl_anim.setContentsMargins(4, 4, 4, 4)
        _anim_outer.addWidget(_anim_content)
        anim_grp.toggled.connect(_anim_content.setVisible)

        # Column headers
        hdr = QHBoxLayout()
        hdr.setSpacing(4)
        for text, width, tip in [
            (tr("hitbox.anim_col_enable"), 28, tr("hitbox.tt_anim_enable_col")),
            (tr("hitbox.anim_col_state"), 72, ""),
            (tr("hitbox.anim_col_start"), 62, tr("hitbox.tt_anim_start")),
            (tr("hitbox.anim_col_count"), 62, tr("hitbox.tt_anim_count")),
            (tr("hitbox.anim_col_loop"), 44, tr("hitbox.tt_anim_loop")),
            (tr("hitbox.anim_col_spd"), 62, tr("hitbox.tt_anim_spd")),
            (tr("hitbox.anim_col_preview"), 52, tr("hitbox.tt_anim_preview")),
        ]:
            lbl = QLabel(text)
            lbl.setFixedWidth(width)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("font-size: 10px; color: #bbb; font-weight: bold;")
            if tip:
                lbl.setToolTip(tip)
            hdr.addWidget(lbl)
        gl_anim.addLayout(hdr)

        for state in ANIM_STATES:
            row = QHBoxLayout()
            row.setSpacing(4)

            en_cb = QCheckBox()
            en_cb.setFixedWidth(28)
            en_cb.setToolTip(tr("hitbox.tt_anim_enable", state=state))
            row.addWidget(en_cb)

            name_lbl = QLabel(state)
            name_lbl.setFixedWidth(72)
            name_lbl.setStyleSheet("font-size: 10px;")
            row.addWidget(name_lbl)

            start_sb = QSpinBox()
            start_sb.setRange(0, 254)
            start_sb.setFixedWidth(62)
            start_sb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            start_sb.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            start_sb.setToolTip(tr("hitbox.tt_anim_start"))
            row.addWidget(start_sb)

            count_sb = QSpinBox()
            count_sb.setRange(1, 255)
            count_sb.setFixedWidth(62)
            count_sb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            count_sb.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            count_sb.setToolTip(tr("hitbox.tt_anim_count"))
            row.addWidget(count_sb)

            loop_cb = QCheckBox()
            loop_cb.setFixedWidth(44)
            loop_cb.setChecked(True)
            loop_cb.setEnabled(False)
            loop_cb.setToolTip(tr("hitbox.tt_anim_loop"))
            row.addWidget(loop_cb)

            spd_sb = QSpinBox()
            spd_sb.setRange(1, 60)
            spd_sb.setValue(6)
            spd_sb.setFixedWidth(62)
            spd_sb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            spd_sb.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            spd_sb.setToolTip(tr("hitbox.tt_anim_spd"))
            row.addWidget(spd_sb)

            play_btn = QPushButton(tr("hitbox.anim_preview_play"))
            play_btn.setFixedWidth(52)
            play_btn.setEnabled(False)
            play_btn.setToolTip(tr("hitbox.tt_anim_preview"))
            row.addWidget(play_btn)

            gl_anim.addLayout(row)

            # Wire enable toggle
            def _on_anim_enable(checked, s=start_sb, c=count_sb, lc=loop_cb,
                                sp=spd_sb, pb=play_btn):
                self._set_anim_spin_interactive(s, checked)
                self._set_anim_spin_interactive(c, checked)
                lc.setEnabled(checked)
                self._set_anim_spin_interactive(sp, checked)
                pb.setEnabled(checked)
                self._on_anims_changed()
            en_cb.toggled.connect(_on_anim_enable)
            start_sb.valueChanged.connect(self._on_anims_changed)
            count_sb.valueChanged.connect(self._on_anims_changed)
            loop_cb.toggled.connect(self._on_anims_changed)
            spd_sb.valueChanged.connect(self._on_anims_changed)
            play_btn.clicked.connect(lambda _c, st=state: self._toggle_preview(st))

            self._anim_rows[state] = (en_cb, start_sb, count_sb, loop_cb, spd_sb, play_btn)

            self._set_anim_spin_interactive(start_sb, False)
            self._set_anim_spin_interactive(count_sb, False)
            self._set_anim_spin_interactive(spd_sb, False)

        right.addWidget(anim_grp)

        # ---- Directional frames group ----------------------------------------
        dir_grp = QGroupBox(tr("hitbox.grp_dir_frames"))
        dir_grp_lay = QVBoxLayout(dir_grp)
        dir_grp_lay.setContentsMargins(6, 4, 6, 4)
        dir_grp_lay.setSpacing(4)

        # Mode selector
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(tr("hitbox.dir_mode")))
        self._dir_mode_combo = QComboBox()
        self._dir_mode_combo.addItem(tr("hitbox.dir_mode_none"),  "none")
        self._dir_mode_combo.addItem(tr("hitbox.dir_mode_4dir"),  "4dir")
        self._dir_mode_combo.addItem(tr("hitbox.dir_mode_8dir"),  "8dir")
        self._dir_mode_combo.currentIndexChanged.connect(self._on_dir_mode_changed)
        mode_row.addWidget(self._dir_mode_combo)
        mode_row.addStretch()
        dir_grp_lay.addLayout(mode_row)

        # Hint label
        self._dir_hint_lbl = QLabel(tr("hitbox.dir_hint"))
        self._dir_hint_lbl.setWordWrap(True)
        self._dir_hint_lbl.setStyleSheet("color: #888; font-size: 10px;")
        dir_grp_lay.addWidget(self._dir_hint_lbl)

        # Grid: label | spinbox   for each direction to define
        # dirs_to_show order: N, NE (8dir only), E, SE (8dir only), S
        dir_grid = QGridLayout()
        dir_grid.setHorizontalSpacing(8)
        dir_grid.setVerticalSpacing(2)
        _DIR_LABELS = [
            ("N",  tr("hitbox.dir_N")),
            ("NE", tr("hitbox.dir_NE")),
            ("E",  tr("hitbox.dir_E")),
            ("SE", tr("hitbox.dir_SE")),
            ("S",  tr("hitbox.dir_S")),
        ]
        self._dir_frame_widgets = {}
        for row_i, (dkey, dlbl) in enumerate(_DIR_LABELS):
            lbl_w = QLabel(dlbl)
            sb = QSpinBox()
            sb.setRange(0, 255)
            sb.setFixedWidth(72)
            sb.setToolTip(tr("hitbox.dir_frame_tt", dir=dlbl))
            sb.valueChanged.connect(self._on_dir_frame_changed)
            auto_lbl = QLabel("")
            auto_lbl.setStyleSheet("color: #888; font-size: 10px;")
            dir_grid.addWidget(lbl_w,    row_i, 0)
            dir_grid.addWidget(sb,       row_i, 1)
            dir_grid.addWidget(auto_lbl, row_i, 2)
            self._dir_frame_widgets[dkey] = sb
            # store auto label for later update
            setattr(self, f"_dir_auto_lbl_{dkey}", auto_lbl)
        dir_grp_lay.addLayout(dir_grid)

        self._dir_widgets_container = dir_grp
        right.addWidget(dir_grp)
        self._refresh_dir_ui()

        self._lbl_spd_hint = QLabel("")
        self._lbl_spd_hint.setWordWrap(True)
        self._lbl_spd_hint.setStyleSheet("color: #b8860b; font-size: 10px;")
        right.addWidget(self._lbl_spd_hint)

        right.addSpacing(8)

        # ── Named animations (ngpc_anim module) ────────────────────────────
        named_anim_grp = QGroupBox(tr("hitbox.grp_named_anims"))
        named_anim_grp.setToolTip(tr("hitbox.tt_named_anims"))
        named_anim_grp.setCheckable(True)
        named_anim_grp.setChecked(True)
        _na_outer = QVBoxLayout(named_anim_grp)
        _na_outer.setContentsMargins(0, 0, 0, 0)
        _na_outer.setSpacing(0)
        _na_content = QWidget()
        _na_vbox = QVBoxLayout(_na_content)
        _na_vbox.setSpacing(2)
        _na_vbox.setContentsMargins(4, 4, 4, 4)
        _na_outer.addWidget(_na_content)
        named_anim_grp.toggled.connect(_na_content.setVisible)

        self._named_anims_table = QTableWidget(0, 4)
        self._named_anims_table.setHorizontalHeaderLabels([
            tr("hitbox.na_col_name"),
            tr("hitbox.na_col_frames"),
            tr("hitbox.na_col_speed"),
            tr("hitbox.na_col_mode"),
        ])
        self._named_anims_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._named_anims_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._named_anims_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._named_anims_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._named_anims_table.setMaximumHeight(120)
        self._named_anims_table.setToolTip(tr("hitbox.tt_named_anims_table"))
        _na_vbox.addWidget(self._named_anims_table)

        _na_btn_row = QHBoxLayout()
        self._btn_na_add = QPushButton(tr("hitbox.na_add"))
        self._btn_na_del = QPushButton(tr("hitbox.na_del"))
        self._btn_na_add.clicked.connect(self._add_named_anim)
        self._btn_na_del.clicked.connect(self._del_named_anim)
        _na_btn_row.addWidget(self._btn_na_add)
        _na_btn_row.addWidget(self._btn_na_del)
        _na_btn_row.addStretch()
        _na_vbox.addLayout(_na_btn_row)

        right.addWidget(named_anim_grp)
        right.addSpacing(4)

        # Save to project
        self._btn_save = QPushButton(tr("hitbox.save"))
        self._btn_save.setToolTip(tr("hitbox.save_tip"))
        self._btn_save.clicked.connect(self._save_hitboxes)
        right.addWidget(self._btn_save)

        # Export _hitbox.h
        self._btn_export = QPushButton(tr("hitbox.export"))
        self._btn_export.clicked.connect(self._export_h)
        right.addWidget(self._btn_export)

        # Export _props.h
        self._btn_export_props = QPushButton(tr("hitbox.export_props"))
        self._btn_export_props.clicked.connect(self._export_props_h)
        right.addWidget(self._btn_export_props)

        # Export _ctrl.h
        self._btn_export_ctrl = QPushButton(tr("hitbox.export_ctrl"))
        self._btn_export_ctrl.clicked.connect(self._export_ctrl_h)
        right.addWidget(self._btn_export_ctrl)

        # Export _anims.h
        self._btn_export_anims = QPushButton(tr("hitbox.export_anims"))
        self._btn_export_anims.clicked.connect(self._export_anims_h)
        right.addWidget(self._btn_export_anims)

        # Export _namedanims.h  (ngpc_anim module)
        self._btn_export_named_anims = QPushButton(tr("hitbox.export_named_anims"))
        self._btn_export_named_anims.clicked.connect(self._export_named_anims_h)
        right.addWidget(self._btn_export_named_anims)

        # Export _motion.h  (ngpc_motion module)
        self._btn_export_motion = QPushButton(tr("hitbox.export_motion"))
        self._btn_export_motion.clicked.connect(self._export_motion_h)
        right.addWidget(self._btn_export_motion)

        # Save as / update entity template (project-level prefab)
        right.addSpacing(6)
        self._btn_save_template = QPushButton(tr("hitbox.save_template"))
        self._btn_save_template.setToolTip(tr("hitbox.save_template_tt"))
        self._btn_save_template.clicked.connect(self._on_save_template)
        right.addWidget(self._btn_save_template)

        self._lbl_template_badge = QLabel("")
        self._lbl_template_badge.setWordWrap(True)
        self._lbl_template_badge.setStyleSheet("font-style: italic; color: #88ccaa; font-size: 11px;")
        right.addWidget(self._lbl_template_badge)

        # Status label
        self._lbl_status = QLabel("")
        self._lbl_status.setWordWrap(True)
        self._lbl_status.setStyleSheet("font-style: italic; color: #888;")
        right.addWidget(self._lbl_status)

        right.addStretch()

        # Wrap right panel in a scroll area (many props → may overflow)
        right_w = QWidget()
        right_w.setLayout(right)
        right_w.setMinimumWidth(200)
        right_scroll = QScrollArea()
        right_scroll.setWidget(right_w)
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        right_scroll.setMinimumWidth(300)
        self._splitter.addWidget(right_scroll)

        # Initial splitter sizes: rail=92, canvas=stretch, right=320
        self._splitter.setSizes([92, 560, 320])

        self._set_controls_enabled(False)

    def _set_anim_spin_interactive(self, sb: QSpinBox, interactive: bool) -> None:
        """Keep values readable when an anim row is inactive, but editable only when enabled."""
        sb.setEnabled(True)
        sb.setReadOnly(not interactive)
        sb.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        sb.setFocusPolicy(
            Qt.FocusPolicy.StrongFocus
            if interactive else
            Qt.FocusPolicy.NoFocus
        )

    def _set_controls_enabled(self, enabled: bool) -> None:
        is_player = str(self._ctrl_role_cb.currentData() or "none") == "player"
        for w in (
            self._btn_prev, self._btn_next, self._btn_copy_all, self._btn_copy_other,
            self._btn_save, self._btn_export, self._btn_export_props,
            self._btn_export_anims, self._btn_save_template,
            self._sb_x, self._sb_y, self._sb_w, self._sb_h, self._cb_box_enabled, self._sb_attack_damage, self._sb_attack_kbx, self._sb_attack_kby,
            self._sb_attack_prio, self._sb_attack_start, self._sb_attack_len,
            self._ctrl_role_cb, self._tabs_box_kind, self._btn_attack_prev, self._btn_attack_next, self._btn_attack_add, self._btn_attack_remove,
        ):
            w.setEnabled(enabled)
        self._sb_attack_damage.setEnabled(enabled and self._active_box_kind == "attack")
        self._sb_attack_kbx.setEnabled(enabled and self._active_box_kind == "attack")
        self._sb_attack_kby.setEnabled(enabled and self._active_box_kind == "attack")
        self._sb_attack_prio.setEnabled(enabled and self._active_box_kind == "attack")
        self._sb_attack_start.setEnabled(enabled and self._active_box_kind == "attack")
        self._sb_attack_len.setEnabled(enabled and self._active_box_kind == "attack")
        self._btn_export_ctrl.setEnabled(enabled and is_player)
        self._btn_zoom_out.setEnabled(enabled and self._zoom > _ZOOM_MIN)
        self._btn_zoom_in.setEnabled(enabled and self._zoom < _ZOOM_MAX)
        self._sb_fw.setEnabled(enabled)
        self._sb_fh.setEnabled(enabled)
        self._cb_frame_preset.setEnabled(enabled)
        for cb, sb in self._prop_widgets.values():
            cb.setEnabled(enabled)
            sb.setEnabled(enabled and cb.isChecked())
        for action_cb in self._ctrl_action_cbs.values():
            action_cb.setEnabled(enabled and is_player)
        for en_cb, start_sb, count_sb, loop_cb, spd_sb, play_btn in self._anim_rows.values():
            en_cb.setEnabled(enabled)
            row_on = enabled and en_cb.isChecked()
            if enabled:
                self._set_anim_spin_interactive(start_sb, row_on)
                self._set_anim_spin_interactive(count_sb, row_on)
                self._set_anim_spin_interactive(spd_sb, row_on)
            else:
                start_sb.setEnabled(False)
                count_sb.setEnabled(False)
                spd_sb.setEnabled(False)
            loop_cb.setEnabled(row_on)
            play_btn.setEnabled(row_on)
        self._refresh_checklist()

    def _check_item_html(self, status: str, title: str, detail: str) -> str:
        tag, color = {
            "ok": ("OK", "#75d17f"),
            "warn": ("!", "#f0b44c"),
            "bad": ("KO", "#e26d6d"),
            "skip": ("-", "#7f8a96"),
        }.get(status, ("?", "#b8c0ca"))
        body = f"<b>{title}</b>"
        if detail:
            body += f" : {detail}"
        return f"<span style='color:{color}; font-weight:600;'>[{tag}]</span> {body}"

    def _refresh_checklist(self) -> None:
        if not hasattr(self, "_lbl_checklist"):
            return
        file_ok = self._file_path is not None and self._file_path.exists()
        img_ok = self._full_img is not None
        slice_ok = False
        slice_detail = tr("hitbox.check_not_loaded")
        if img_ok and self._frame_w > 0 and self._frame_h > 0:
            iw, ih = self._full_img.width, self._full_img.height
            slice_ok = (iw % self._frame_w == 0) and (ih % self._frame_h == 0)
            slice_detail = tr(
                "hitbox.check_frames_detail",
                fw=self._frame_w,
                fh=self._frame_h,
                count=self._frame_count,
            )
        hitboxes_ok = False
        hitbox_detail = tr("hitbox.check_not_loaded")
        if img_ok:
            valid_count = 0
            for hb in self._hurtboxes[: self._frame_count]:
                if not isinstance(hb, dict):
                    continue
                try:
                    if bool(hb.get("enabled", True)) and int(hb.get("w", 0)) > 0 and int(hb.get("h", 0)) > 0:
                        valid_count += 1
                except Exception:
                    pass
            hitboxes_ok = valid_count >= self._frame_count
            hitbox_detail = tr("hitbox.check_hitboxes_detail", n=valid_count, total=self._frame_count)
        role = str((self._ctrl or {}).get("role", "none") or "none").strip()
        role_ok = role != "none"
        role_detail = tr("hitbox.check_role_none") if not role_ok else tr("hitbox.check_role_detail", role=role)
        anims = self._collect_anims()
        anim_count = len(anims)
        anim_ranges_ok = True
        for data in anims.values():
            try:
                start = int(data.get("start", 0))
                count = int(data.get("count", 1))
            except Exception:
                start = 0
                count = 0
            if start < 0 or count <= 0 or start >= self._frame_count or (start + count) > self._frame_count:
                anim_ranges_ok = False
                break
        save_ok = self._sprite_meta is not None
        props_enabled = sum(1 for cb, _sb in self._prop_widgets.values() if cb.isChecked())
        genre_state, genre_detail = self._genre_fit_state()

        rows = [
            self._check_item_html(
                "ok" if file_ok else "bad",
                tr("hitbox.check_sprite"),
                self._file_path.name if file_ok and self._file_path else tr("hitbox.check_not_loaded"),
            ),
            self._check_item_html(
                "ok" if slice_ok else ("warn" if img_ok else "skip"),
                tr("hitbox.check_frames"),
                slice_detail,
            ),
            self._check_item_html(
                "ok" if hitboxes_ok else ("warn" if img_ok else "skip"),
                tr("hitbox.check_hitboxes"),
                hitbox_detail,
            ),
            self._check_item_html(
                "ok" if role_ok else "skip",
                tr("hitbox.check_role"),
                role_detail,
            ),
            self._check_item_html(
                "ok" if anim_count > 0 and anim_ranges_ok else ("warn" if anim_count > 0 else "skip"),
                tr("hitbox.check_anims"),
                tr("hitbox.check_anims_detail", n=anim_count) if anim_count > 0 else tr("hitbox.check_anims_none"),
            ),
            self._check_item_html(
                "ok" if save_ok else "warn",
                tr("hitbox.check_project"),
                tr("hitbox.check_project_ok", n=props_enabled) if save_ok else tr("hitbox.no_project_context"),
            ),
            self._check_item_html(
                genre_state,
                tr("hitbox.check_genre_fit"),
                genre_detail,
            ),
        ]
        self._lbl_checklist.setText("<br>".join(rows))

    # ------------------------------------------------------------------
    # Public API (called by MainWindow)
    # ------------------------------------------------------------------

    def set_project(self, project_data: dict, base_dir: Optional[Path]) -> None:
        """Attach the current project payload and its base directory."""
        self._project_data = project_data
        self._base_dir = base_dir
        self._refresh_checklist()

    def set_scene(self, scene: Optional[dict], base_dir: Optional[Path]) -> None:
        """Attach the active scene so the sprite rail reflects current selection."""
        self._scene = scene
        self._base_dir = base_dir
        self._refresh_rail()
        self._refresh_checklist()

    def open_sprite(self, sprite_meta: dict, base_dir: Optional[Path] = None) -> None:
        """Open a sprite entry (from scene) for hitbox editing."""
        if base_dir:
            self._base_dir = base_dir
        self._sprite_meta = sprite_meta
        self._update_rail_highlight(sprite_meta.get("file", ""))

        rel = sprite_meta.get("file", "")
        if not rel:
            return
        p = Path(rel)
        if self._base_dir and not p.is_absolute():
            p = self._base_dir / p
        if not p.exists():
            self._lbl_file.setText(f"[{tr('hitbox.not_found')}] {p.name}")
            self._set_controls_enabled(False)
            self._refresh_checklist()
            return

        try:
            self._full_img = Image.open(p).convert("RGBA")
        except Exception as exc:
            self._lbl_file.setText(f"Error: {exc}")
            return

        self._file_path = p
        # Use per-frame dimensions from sprite meta when available.
        meta_fw = int(sprite_meta.get("frame_w") or 0)
        meta_fh = int(sprite_meta.get("frame_h") or 0)
        iw, ih = self._full_img.width, self._full_img.height
        if meta_fw > 0 and meta_fh > 0 and meta_fw <= iw and meta_fh <= ih:
            self._frame_w = meta_fw
            self._frame_h = meta_fh
        else:
            self._frame_w = iw
            self._frame_h = ih
        self._updating_frame_size = True
        self._sb_fw.setMaximum(iw)
        self._sb_fh.setMaximum(ih)
        self._sb_fw.setValue(self._frame_w)
        self._sb_fh.setValue(self._frame_h)
        self._updating_frame_size = False
        cols = iw // self._frame_w
        rows = ih // self._frame_h
        self._frame_count = max(1, cols * rows)
        self._lbl_fcount.setText(f"({self._frame_count}f)")
        self._lbl_file.setText(p.name)

        self._hurtboxes = sprite_hurtboxes(sprite_meta, self._frame_w, self._frame_h)
        self._attack_hitboxes = sprite_attack_hitboxes(sprite_meta, self._frame_w, self._frame_h)
        if not self._hurtboxes:
            self._hurtboxes.append(self._default_hurtbox())
        if not self._attack_hitboxes:
            self._attack_hitboxes.append(first_attack_hitbox(sprite_meta, self._frame_w, self._frame_h))

        # Load sprite props (per-sprite, not per-frame).
        # A prop key present in saved data → checkbox checked + value loaded.
        # A prop key absent → checkbox unchecked + default value shown (grayed).
        raw_props = sprite_meta.get("props") or {}
        self._updating_props = True
        for k, (cb, sb) in self._prop_widgets.items():
            if k in raw_props:
                sb.setValue(int(raw_props[k]))
                cb.setChecked(True)
                sb.setEnabled(True)
            else:
                sb.setValue(_PROPS_DEFAULTS.get(k, 0))
                cb.setChecked(False)
                sb.setEnabled(False)
        self._props = {k: int(raw_props[k]) for k in raw_props if k in _PROPS_DEFAULTS}
        self._updating_props = False
        self._refresh_props_summary()

        # Load ctrl config
        self._load_ctrl(sprite_meta.get("ctrl") or {})

        # Load animation states
        self._load_anims(sprite_meta.get("anims") or {})
        # Load named animations (ngpc_anim module)
        self._load_named_anims(sprite_meta.get("named_anims") or [])
        # Load motion patterns (ngpc_motion module)
        self._load_motion_patterns(sprite_meta.get("motion_patterns") or [])
        # Load directional frames
        self._load_dir_frames()

        self._current_frame = 0
        self._current_attack_box = 0
        self._active_box_kind = "hurtbox"
        if hasattr(self, "_tabs_box_kind"):
            self._tabs_box_kind.blockSignals(True)
            self._tabs_box_kind.setCurrentIndex(0)
            self._tabs_box_kind.blockSignals(False)
        self._stop_preview()
        self._set_controls_enabled(True)
        self._lbl_status.setText("")
        self._refresh_frame()
        self._refresh_checklist()
        self._update_template_badge()

    def open_path(self, path: Path) -> None:
        """Open a PNG directly (free mode / no scene context)."""
        if not path.exists():
            return
        try:
            img = Image.open(path)
            fw, fh = img.width, img.height
        except Exception:
            fw, fh = 8, 8
        meta = {
            "file": str(path),
            "frame_w": fw,
            "frame_h": fh,
            "frame_count": 1,
        }
        self.open_sprite(meta, path.parent)

    # ------------------------------------------------------------------
    # Sprite rail
    # ------------------------------------------------------------------

    def _refresh_rail(self) -> None:
        """Rebuild the left sprite thumbnail rail from the current scene."""
        # A-2: stop and clear all per-thumb animation timers
        for t in self._rail_anim_timers:
            t.stop()
        self._rail_anim_timers.clear()
        while self._rail_layout.count():
            item = self._rail_layout.takeAt(0)
            if w := item.widget():
                w.deleteLater()
        self._rail_btns.clear()

        scene = self._scene
        base_dir = self._base_dir
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
            path = base_dir / spr.get("file", "")
            self._add_rail_thumb(path, spr.get("name", ""), spr)
        self._rail_layout.addStretch()

        # Restore highlight for the currently open sprite
        if self._sprite_meta:
            self._update_rail_highlight(self._sprite_meta.get("file", ""))

    def _add_rail_thumb(self, path: Path, name: str, sprite_cfg: dict) -> None:
        btn = QToolButton()
        btn.setFixedSize(80, 80)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setText((name or path.stem)[:10])
        btn.setToolTip(str(path))
        rel = sprite_cfg.get("file", "")
        if path.exists():
            try:
                img = Image.open(path).convert("RGBA")
                fw = int(sprite_cfg.get("frame_w") or img.width)
                fh = int(sprite_cfg.get("frame_h") or img.height)
                # A-2: build frame pixmap list for thumbnail animation
                frame_pms: list[QPixmap] = []
                if fw > 0 and fh > 0 and fw <= img.width and fh <= img.height:
                    cols = img.width // fw
                    n_frames = cols * (img.height // fh)
                    for fi in range(n_frames):
                        cx = (fi % cols) * fw
                        cy = (fi // cols) * fh
                        frame_img = img.crop((cx, cy, cx + fw, cy + fh))
                        frame_img = frame_img.copy()
                        frame_img.thumbnail((52, 52), Image.NEAREST)
                        frame_pms.append(_pil_to_qpixmap(frame_img))
                if not frame_pms:
                    thumb = img.copy()
                    thumb.thumbnail((52, 52), Image.NEAREST)
                    frame_pms.append(_pil_to_qpixmap(thumb))
                btn.setIcon(QIcon(frame_pms[0]))
                btn.setIconSize(QSize(52, 52))
                btn.clicked.connect(lambda _c, m=sprite_cfg, b=btn: self._rail_select(m, b))
                # A-2: start animation timer if sprite has an idle/walk anim state
                anims = sprite_cfg.get("anims") or {}
                anim_start, anim_count, anim_spd = 0, 1, 8
                for state in ("idle", "walk", "run"):
                    a = anims.get(state)
                    if a:
                        anim_start = int(a.get("start") or 0)
                        anim_count = max(1, int(a.get("count") or 1))
                        anim_spd   = max(1, int(a.get("spd") or 8))
                        break
                if anim_count > 1 and len(frame_pms) > 1:
                    seq = [
                        frame_pms[min(anim_start + i, len(frame_pms) - 1)]
                        for i in range(anim_count)
                    ]
                    tick_ms = max(16, int(anim_spd * 1000 / 60))
                    _idx = [0]

                    def _on_tick(b=btn, s=seq, idx=_idx) -> None:
                        idx[0] = (idx[0] + 1) % len(s)
                        b.setIcon(QIcon(s[idx[0]]))

                    t = QTimer(self)
                    t.setInterval(tick_ms)
                    t.timeout.connect(_on_tick)
                    t.start()
                    self._rail_anim_timers.append(t)
            except Exception:
                btn.setEnabled(False)
        else:
            btn.setStyleSheet("color: gray;")
            btn.setEnabled(False)
        self._rail_btns.append((btn, rel))
        self._rail_layout.addWidget(btn)

    def _rail_select(self, sprite_meta: dict, clicked_btn: QToolButton) -> None:
        # Flush current sprite before switching so no edits are lost.
        if self._sprite_meta is not None and self._sprite_meta is not sprite_meta:
            self._save_hitboxes()
        for b, _ in self._rail_btns:
            b.setStyleSheet("")
        clicked_btn.setStyleSheet("border: 2px solid #569ed6; border-radius: 3px;")
        self.open_sprite(sprite_meta)

    def _update_rail_highlight(self, rel_file: str) -> None:
        for b, r in self._rail_btns:
            b.setStyleSheet(
                "border: 2px solid #569ed6; border-radius: 3px;" if r == rel_file else ""
            )

    # ------------------------------------------------------------------
    # Frame management
    # ------------------------------------------------------------------

    def _crop_frame(self, idx: int) -> Image.Image:
        """Crop frame `idx` from the full sprite sheet."""
        if self._full_img is None:
            return Image.new("RGBA", (self._frame_w, self._frame_h))
        fw, fh = self._frame_w, self._frame_h
        cols = max(1, self._full_img.width // fw)
        col = idx % cols
        row = idx // cols
        x0, y0 = col * fw, row * fh
        return self._full_img.crop((x0, y0, x0 + fw, y0 + fh))

    def _default_hurtbox(self) -> dict:
        return {
            "x": -(self._frame_w // 2),
            "y": -(self._frame_h // 2),
            "w": self._frame_w,
            "h": self._frame_h,
            "enabled": True,
        }

    def _default_attack_hitbox(self) -> dict:
        return {
            "x": 0,
            "y": 0,
            "w": max(1, self._frame_w // 2),
            "h": max(1, self._frame_h // 2),
            "damage": 0,
            "knockback_x": 0,
            "knockback_y": 0,
            "active_start": 0,
            "active_len": 0,
            "active_anim_state": 0xFF,
            "priority": 0,
            "enabled": True,
        }

    def _boxes_for_kind(self, kind: str) -> list[dict]:
        return self._attack_hitboxes if kind == "attack" else self._hurtboxes

    def _default_box_for_kind(self, kind: str) -> dict:
        return self._default_attack_hitbox() if kind == "attack" else self._default_hurtbox()

    def _box_edit_index(self, kind: str) -> int:
        return self._current_attack_box if kind == "attack" else self._current_frame

    def _ensure_box(self, kind: str, fi: int) -> dict:
        boxes = self._boxes_for_kind(kind)
        default_box = self._default_box_for_kind(kind)
        while len(boxes) <= fi:
            boxes.append(dict(default_box))
        return boxes[fi]

    def _current_box(self) -> dict:
        return self._ensure_box(self._active_box_kind, self._box_edit_index(self._active_box_kind))

    def _secondary_box(self) -> dict:
        other = "attack" if self._active_box_kind == "hurtbox" else "hurtbox"
        return self._ensure_box(other, self._box_edit_index(other))

    def _box_kind_label(self, kind: str) -> str:
        return tr("hitbox.box_kind_attack") if kind == "attack" else tr("hitbox.box_kind_hurtbox")

    def _scene_profile(self) -> str:
        if not isinstance(self._scene, dict):
            return "none"
        return str(self._scene.get("level_profile", "none") or "none").strip() or "none"

    def _genre_fit_state(self) -> tuple[str, str]:
        profile = self._scene_profile()
        if profile in ("fighting", "brawler"):
            return "warn", tr("hitbox.genre_fit_fighting")
        if profile in ("platformer", "run_gun"):
            return "ok", tr("hitbox.genre_fit_platformer")
        if profile in ("shmup",):
            return "ok", tr("hitbox.genre_fit_shmup")
        if profile in ("topdown_rpg", "tactical"):
            return "ok", tr("hitbox.genre_fit_topdown")
        return "ok", tr("hitbox.genre_fit_generic")

    def _refresh_box_hint(self) -> None:
        if not hasattr(self, "_lbl_box_hint"):
            return
        if self._active_box_kind == "attack":
            self._lbl_box_hint.setText(tr("hitbox.origin_hint_attack"))
        else:
            self._lbl_box_hint.setText(tr("hitbox.origin_hint_hurtbox"))

    def _refresh_attack_box_nav(self) -> None:
        if not hasattr(self, "_lbl_attack_box"):
            return
        is_attack = self._active_box_kind == "attack"
        count = max(1, len(self._attack_hitboxes))
        self._current_attack_box = max(0, min(self._current_attack_box, count - 1))
        self._lbl_attack_box.setText(tr("hitbox.attack_box_index", idx=self._current_attack_box + 1, total=count))
        self._btn_attack_prev.setVisible(is_attack)
        self._btn_attack_next.setVisible(is_attack)
        self._btn_attack_add.setVisible(is_attack)
        self._btn_attack_remove.setVisible(is_attack)
        self._lbl_attack_box.setVisible(is_attack)
        self._btn_attack_prev.setEnabled(bool(self._sprite_meta is not None) and is_attack and self._current_attack_box > 0)
        self._btn_attack_next.setEnabled(bool(self._sprite_meta is not None) and is_attack and self._current_attack_box < (count - 1))
        self._btn_attack_add.setEnabled(bool(self._sprite_meta is not None) and is_attack)
        self._btn_attack_remove.setEnabled(bool(self._sprite_meta is not None) and is_attack and count > 1)

    def _refresh_attack_box_ui(self, hb: dict | None = None) -> None:
        is_attack = self._active_box_kind == "attack"
        self._refresh_attack_box_nav()
        if hasattr(self, "_lbl_attack_damage"):
            self._lbl_attack_damage.setEnabled(is_attack)
        if hasattr(self, "_sb_attack_damage"):
            self._sb_attack_damage.blockSignals(True)
            self._sb_attack_damage.setValue(int((hb or {}).get("damage", 0) or 0))
            self._sb_attack_damage.blockSignals(False)
            self._sb_attack_damage.setEnabled(bool(self._sprite_meta is not None) and is_attack)
        if hasattr(self, "_sb_attack_kbx"):
            self._sb_attack_kbx.blockSignals(True)
            self._sb_attack_kbx.setValue(int((hb or {}).get("knockback_x", 0) or 0))
            self._sb_attack_kbx.blockSignals(False)
            self._sb_attack_kbx.setEnabled(bool(self._sprite_meta is not None) and is_attack)
        if hasattr(self, "_sb_attack_kby"):
            self._sb_attack_kby.blockSignals(True)
            self._sb_attack_kby.setValue(int((hb or {}).get("knockback_y", 0) or 0))
            self._sb_attack_kby.blockSignals(False)
            self._sb_attack_kby.setEnabled(bool(self._sprite_meta is not None) and is_attack)
        if hasattr(self, "_sb_attack_prio"):
            self._sb_attack_prio.blockSignals(True)
            self._sb_attack_prio.setValue(int((hb or {}).get("priority", 0) or 0))
            self._sb_attack_prio.blockSignals(False)
            self._sb_attack_prio.setEnabled(bool(self._sprite_meta is not None) and is_attack)
        if hasattr(self, "_sb_attack_start"):
            self._sb_attack_start.blockSignals(True)
            self._sb_attack_start.setValue(int((hb or {}).get("active_start", 0) or 0))
            self._sb_attack_start.blockSignals(False)
            self._sb_attack_start.setEnabled(bool(self._sprite_meta is not None) and is_attack)
        if hasattr(self, "_sb_attack_len"):
            self._sb_attack_len.blockSignals(True)
            self._sb_attack_len.setValue(int((hb or {}).get("active_len", 0) or 0))
            self._sb_attack_len.blockSignals(False)
            self._sb_attack_len.setEnabled(bool(self._sprite_meta is not None) and is_attack)
        if hasattr(self, "_cb_attack_anim_state"):
            anim_state_val = int((hb or {}).get("active_anim_state", 0xFF) or 0xFF) & 0xFF
            idx = self._cb_attack_anim_state.findData(anim_state_val)
            if idx < 0:
                idx = 0
            self._cb_attack_anim_state.blockSignals(True)
            self._cb_attack_anim_state.setCurrentIndex(idx)
            self._cb_attack_anim_state.blockSignals(False)
            self._cb_attack_anim_state.setEnabled(bool(self._sprite_meta is not None) and is_attack)
        if hasattr(self, "_btn_copy_other"):
            self._btn_copy_other.setText(
                tr("hitbox.copy_from_hurtbox") if is_attack else tr("hitbox.copy_from_attack")
            )
            self._btn_copy_other.setEnabled(bool(self._sprite_meta is not None))
        if hasattr(self, "_btn_copy_all"):
            self._btn_copy_all.setEnabled(bool(self._sprite_meta is not None) and not is_attack)
        if hasattr(self, "_lbl_usage_hint"):
            _state, detail = self._genre_fit_state()
            self._lbl_usage_hint.setText(detail)

    def _refresh_frame(self) -> None:
        fi = self._current_frame
        frame = self._crop_frame(fi)
        self._canvas.set_frame(frame, self._zoom)
        self._canvas.set_box_kind(self._active_box_kind)
        hb = self._current_box()
        self._canvas.set_hitbox(hb)
        self._canvas.set_secondary_hitbox(self._secondary_box())
        self._refresh_box_hint()

        self._updating_spinboxes = True
        self._sb_x.setValue(hb["x"])
        self._sb_y.setValue(hb["y"])
        self._sb_w.setValue(hb["w"])
        self._sb_h.setValue(hb["h"])
        self._cb_box_enabled.blockSignals(True)
        self._cb_box_enabled.setChecked(bool(hb.get("enabled", True)))
        self._cb_box_enabled.blockSignals(False)
        self._updating_spinboxes = False
        self._refresh_attack_box_ui(hb)

        self._lbl_frame.setText(f"{fi + 1} / {self._frame_count}")
        self._btn_prev.setEnabled(fi > 0)
        self._btn_next.setEnabled(fi < self._frame_count - 1)

    def _on_box_kind_changed(self) -> None:
        if not hasattr(self, "_tabs_box_kind"):
            return
        self._active_box_kind = "attack" if int(self._tabs_box_kind.currentIndex()) == 1 else "hurtbox"
        self._refresh_frame()

    def _copy_from_other_box(self) -> None:
        fi = self._box_edit_index(self._active_box_kind)
        source_kind = "hurtbox" if self._active_box_kind == "attack" else "attack"
        src = dict(self._ensure_box(source_kind, self._box_edit_index(source_kind)))
        dst = dict(self._ensure_box(self._active_box_kind, fi))
        dst["x"] = int(src.get("x", dst.get("x", 0)) or 0)
        dst["y"] = int(src.get("y", dst.get("y", 0)) or 0)
        dst["w"] = int(src.get("w", dst.get("w", 1)) or 1)
        dst["h"] = int(src.get("h", dst.get("h", 1)) or 1)
        if self._active_box_kind == "attack":
            dst["damage"] = int(dst.get("damage", 0) or 0)
        self._boxes_for_kind(self._active_box_kind)[fi] = dst
        self._refresh_frame()
        self._lbl_status.setText(tr("hitbox.copied_from_other"))
        self._refresh_checklist()

    def _on_frame_size_changed(self) -> None:
        """Recompute frame_count when the user edits frame W or H spinboxes."""
        if self._updating_frame_size or self._full_img is None:
            return
        fw = self._sb_fw.value()
        fh = self._sb_fh.value()
        if fw <= 0 or fh <= 0:
            return
        iw, ih = self._full_img.width, self._full_img.height
        # Clamp to image size
        fw = min(fw, iw)
        fh = min(fh, ih)
        self._frame_w = fw
        self._frame_h = fh
        cols = iw // fw
        rows = ih // fh
        self._frame_count = max(1, cols * rows)
        self._lbl_fcount.setText(f"({self._frame_count}f)")
        self._stop_preview()
        self._current_frame = 0
        self._refresh_frame()
        self._refresh_checklist()

    def _on_frame_preset_selected(self) -> None:
        """Apply a preset (fw, fh) when the user picks one from the combo."""
        data = self._cb_frame_preset.currentData()
        if not data:
            return
        fw, fh = data
        if fw <= 0 or fh <= 0:
            return
        self._updating_frame_size = True
        self._sb_fw.setValue(fw)
        self._sb_fh.setValue(fh)
        self._updating_frame_size = False
        # Reset combo to "—" so it acts as a one-shot trigger
        self._cb_frame_preset.blockSignals(True)
        self._cb_frame_preset.setCurrentIndex(0)
        self._cb_frame_preset.blockSignals(False)
        self._on_frame_size_changed()

    def _prev_frame(self) -> None:
        self._stop_preview()
        if self._current_frame > 0:
            self._current_frame -= 1
            self._refresh_frame()

    def _next_frame(self) -> None:
        self._stop_preview()
        if self._current_frame < self._frame_count - 1:
            self._current_frame += 1
            self._refresh_frame()

    def keyPressEvent(self, event) -> None:
        mod = event.modifiers()
        key = event.key()
        ctrl = mod == Qt.KeyboardModifier.ControlModifier
        alt  = mod == Qt.KeyboardModifier.AltModifier
        none = mod == Qt.KeyboardModifier.NoModifier

        if ctrl:
            if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
                self._zoom_in()
                return
            if key == Qt.Key.Key_Minus:
                self._zoom_out()
                return
            if key == Qt.Key.Key_S:
                self._save_hitboxes()
                return
        if none and key == Qt.Key.Key_F5:
            self._export_h()
            return
        if alt:
            if key == Qt.Key.Key_Left:
                self._prev_attack_box()
                return
            if key == Qt.Key.Key_Right:
                self._next_attack_box()
                return
        if none:
            if key == Qt.Key.Key_Left:
                self._prev_frame()
                return
            if key == Qt.Key.Key_Right:
                self._next_frame()
                return
            if key == Qt.Key.Key_Insert:
                self._add_attack_box()
                return
            if key == Qt.Key.Key_Delete:
                self._remove_attack_box()
                return
        super().keyPressEvent(event)

    def _prev_attack_box(self) -> None:
        if self._current_attack_box > 0:
            self._current_attack_box -= 1
            self._refresh_frame()

    def _next_attack_box(self) -> None:
        if self._current_attack_box < max(0, len(self._attack_hitboxes) - 1):
            self._current_attack_box += 1
            self._refresh_frame()

    def _add_attack_box(self) -> None:
        hb = dict(self._current_box()) if self._active_box_kind == "attack" else dict(self._default_attack_hitbox())
        self._attack_hitboxes.append(hb)
        self._current_attack_box = len(self._attack_hitboxes) - 1
        self._lbl_status.setText(tr("hitbox.attack_box_added"))
        self._refresh_frame()
        self._refresh_checklist()

    def _remove_attack_box(self) -> None:
        if len(self._attack_hitboxes) <= 1:
            return
        self._attack_hitboxes.pop(self._current_attack_box)
        self._current_attack_box = max(0, min(self._current_attack_box, len(self._attack_hitboxes) - 1))
        self._lbl_status.setText(tr("hitbox.attack_box_removed"))
        self._refresh_frame()
        self._refresh_checklist()

    # ------------------------------------------------------------------
    # Anim preview
    # ------------------------------------------------------------------

    def _toggle_preview(self, state: str) -> None:
        """Start or stop preview for the given anim state."""
        if self._preview_state == state:
            self._stop_preview()
            return
        self._stop_preview()
        rows = self._anim_rows.get(state)
        if not rows:
            return
        en_cb, start_sb, count_sb, loop_cb, spd_sb, play_btn = rows
        if not en_cb.isChecked():
            return
        start = start_sb.value()
        if start >= self._frame_count:
            return
        self._preview_state = state
        self._preview_tick = 0
        # 1 tick per frame; interval = spd ticks × (1000ms / 60fps)
        interval_ms = max(16, int(spd_sb.value() * 1000 / 60))
        self._preview_timer.setInterval(interval_ms)
        self._preview_timer.start()
        play_btn.setText(tr("hitbox.anim_preview_stop"))
        # Jump immediately to start frame
        self._current_frame = min(start, self._frame_count - 1)
        self._refresh_frame()

    def _stop_preview(self) -> None:
        """Stop any running preview and reset button text."""
        if not self._preview_timer.isActive():
            self._preview_state = None
            return
        self._preview_timer.stop()
        if self._preview_state:
            rows = self._anim_rows.get(self._preview_state)
            if rows:
                rows[5].setText(tr("hitbox.anim_preview_play"))
        self._preview_state = None
        self._preview_tick = 0

    def _on_preview_tick(self) -> None:
        """Advance the canvas to the next frame of the active preview state."""
        if not self._preview_state:
            return
        rows = self._anim_rows.get(self._preview_state)
        if not rows:
            self._stop_preview()
            return
        en_cb, start_sb, count_sb, loop_cb, spd_sb, play_btn = rows
        if not en_cb.isChecked():
            self._stop_preview()
            return
        start = start_sb.value()
        count = max(1, count_sb.value())
        loop  = loop_cb.isChecked()
        self._preview_tick += 1
        if not loop and self._preview_tick >= count:
            # Hold on last frame then stop
            self._current_frame = min(start + count - 1, self._frame_count - 1)
            self._refresh_frame()
            self._stop_preview()
            return
        frame_in_state = self._preview_tick % count
        self._current_frame = min(start + frame_in_state, self._frame_count - 1)
        self._refresh_frame()

    def _zoom_in(self) -> None:
        self._on_zoom_request(1)

    def _zoom_out(self) -> None:
        self._on_zoom_request(-1)

    def _on_zoom_request(self, delta: int) -> None:
        new_zoom = max(_ZOOM_MIN, min(_ZOOM_MAX, self._zoom + delta))
        if new_zoom == self._zoom:
            return
        self._zoom = new_zoom
        self._lbl_zoom.setText(f"×{self._zoom}")
        self._btn_zoom_out.setEnabled(self._zoom > _ZOOM_MIN)
        self._btn_zoom_in.setEnabled(self._zoom < _ZOOM_MAX)
        if self._full_img is not None:
            self._refresh_frame()

    # ------------------------------------------------------------------
    # Hitbox sync: canvas ↔ spinboxes
    # ------------------------------------------------------------------

    def _on_canvas_hitbox_changed(self, hb: dict) -> None:
        fi = self._box_edit_index(self._active_box_kind)
        boxes = self._boxes_for_kind(self._active_box_kind)
        while len(boxes) <= fi:
            boxes.append(dict(self._default_box_for_kind(self._active_box_kind)))
        cur = dict(boxes[fi]) if fi < len(boxes) else dict(self._default_box_for_kind(self._active_box_kind))
        cur.update({
            "x": hb["x"],
            "y": hb["y"],
            "w": hb["w"],
            "h": hb["h"],
            "enabled": bool(cur.get("enabled", True)),
        })
        boxes[fi] = cur

        self._updating_spinboxes = True
        self._sb_x.setValue(hb["x"])
        self._sb_y.setValue(hb["y"])
        self._sb_w.setValue(hb["w"])
        self._sb_h.setValue(hb["h"])
        self._updating_spinboxes = False
        self._refresh_attack_box_ui(cur)
        self._refresh_checklist()

    def _on_spinbox_changed(self) -> None:
        if self._updating_spinboxes:
            return
        fi = self._box_edit_index(self._active_box_kind)
        boxes = self._boxes_for_kind(self._active_box_kind)
        while len(boxes) <= fi:
            boxes.append(dict(self._default_box_for_kind(self._active_box_kind)))
        hb = dict(boxes[fi])
        hb.update({
            "x": self._sb_x.value(),
            "y": self._sb_y.value(),
            "w": self._sb_w.value(),
            "h": self._sb_h.value(),
            "enabled": bool(hb.get("enabled", True)),
        })
        boxes[fi] = hb
        self._canvas.set_hitbox(hb)
        self._canvas.set_secondary_hitbox(self._secondary_box())
        self._refresh_attack_box_ui(hb)
        self._refresh_checklist()

    def _on_box_enabled_changed(self, checked: bool) -> None:
        fi = self._box_edit_index(self._active_box_kind)
        box = self._ensure_box(self._active_box_kind, fi)
        box["enabled"] = bool(checked)
        self._canvas.set_hitbox(box)
        self._canvas.set_secondary_hitbox(self._secondary_box())
        self._refresh_attack_box_ui(box)
        self._refresh_checklist()

    def _on_attack_damage_changed(self) -> None:
        if self._active_box_kind != "attack":
            return
        fi = self._current_attack_box
        box = self._ensure_box("attack", fi)
        box["damage"] = int(self._sb_attack_damage.value() or 0)
        self._refresh_checklist()

    def _on_attack_knockback_changed(self) -> None:
        if self._active_box_kind != "attack":
            return
        fi = self._current_attack_box
        box = self._ensure_box("attack", fi)
        box["knockback_x"] = int(self._sb_attack_kbx.value() or 0)
        box["knockback_y"] = int(self._sb_attack_kby.value() or 0)
        self._refresh_checklist()

    def _on_attack_window_changed(self) -> None:
        if self._active_box_kind != "attack":
            return
        fi = self._current_attack_box
        box = self._ensure_box("attack", fi)
        box["priority"] = int(self._sb_attack_prio.value() or 0)
        box["active_start"] = int(self._sb_attack_start.value() or 0)
        box["active_len"] = int(self._sb_attack_len.value() or 0)
        box["active_anim_state"] = int(self._cb_attack_anim_state.currentData() or 0xFF) & 0xFF
        self._refresh_checklist()

    def _on_props_changed(self) -> None:
        if self._updating_props:
            return
        self._props = {
            k: sb.value()
            for k, (cb, sb) in self._prop_widgets.items()
            if cb.isChecked()
        }
        self._refresh_props_summary()
        self._refresh_checklist()
        self._refresh_spd_hint()

    def _prop_effective_value(self, key: str) -> int:
        pair = self._prop_widgets.get(key)
        if not pair:
            return int(_PROPS_DEFAULTS.get(key, 0) or 0)
        cb, sb = pair
        if cb.isChecked():
            return int(sb.value())
        return int(_PROPS_DEFAULTS.get(key, 0) or 0)

    def _refresh_props_summary(self) -> None:
        if not hasattr(self, "_lbl_jump_summary"):
            return
        move_type = self._prop_effective_value("move_type")
        can_jump = self._prop_effective_value("can_jump")
        jump_force = self._prop_effective_value("jump_force")
        gravity = self._prop_effective_value("gravity")
        max_fall_speed = self._prop_effective_value("max_fall_speed")
        weight = self._prop_effective_value("weight")

        if move_type != 2:
            self._lbl_jump_summary.setText(tr("hitbox.jump_summary_move_type", move_type=move_type))
            return
        if not can_jump or jump_force <= 0:
            self._lbl_jump_summary.setText(tr("hitbox.jump_summary_disabled", jump=jump_force, gravity=gravity))
            return
        metrics = _platformer_jump_metrics(jump_force, gravity, max_fall_speed)
        self._lbl_jump_summary.setText(
            tr(
                "hitbox.jump_summary_enabled_exact",
                jump=jump_force,
                gravity=gravity,
                tap_px=metrics["tap_px"],
                tap_tiles=metrics["tap_tiles"],
                tap_frames=metrics["tap_frames"],
                hold_px=metrics["hold_px"],
                hold_tiles=metrics["hold_tiles"],
                hold_frames=metrics["hold_frames"],
                gravity_eff=metrics["gravity_eff"],
                hold_gravity=metrics["hold_gravity"],
                fall_cap=metrics["fall_cap"],
                weight=weight,
            )
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _copy_to_all(self) -> None:
        if self._active_box_kind == "attack":
            return
        fi = self._current_frame
        boxes = self._boxes_for_kind(self._active_box_kind)
        if fi >= len(boxes):
            return
        hb = dict(boxes[fi])
        copies = [dict(hb) for _ in range(self._frame_count)]
        if self._active_box_kind == "attack":
            self._attack_hitboxes = copies
        else:
            self._hurtboxes = copies
        self._lbl_status.setText(tr("hitbox.copied_all"))
        self._refresh_checklist()

    def _save_hitboxes(self) -> None:
        if self._sprite_meta is None:
            self._lbl_status.setText(tr("hitbox.no_project_context"))
            return
        # Persist frame dimensions back so the project stays consistent.
        self._sprite_meta["frame_w"] = self._frame_w
        self._sprite_meta["frame_h"] = self._frame_h
        store_sprite_boxes(self._sprite_meta, self._hurtboxes, self._attack_hitboxes)
        # Only save enabled (checked) props — absent key = disabled.
        self._sprite_meta["props"] = {
            k: sb.value()
            for k, (cb, sb) in self._prop_widgets.items()
            if cb.isChecked()
        }
        self._sprite_meta["ctrl"] = self._collect_ctrl()
        anims = self._collect_anims()
        if anims:
            self._sprite_meta["anims"] = anims
        elif "anims" in self._sprite_meta:
            del self._sprite_meta["anims"]
        named_anims = self._collect_named_anims()
        if named_anims:
            self._sprite_meta["named_anims"] = named_anims
        elif "named_anims" in self._sprite_meta:
            del self._sprite_meta["named_anims"]
        motion_patterns = self._collect_motion_patterns()
        if motion_patterns:
            self._sprite_meta["motion_patterns"] = motion_patterns
        elif "motion_patterns" in self._sprite_meta:
            del self._sprite_meta["motion_patterns"]
        dir_frames = self._collect_dir_frames()
        if dir_frames:
            self._sprite_meta["dir_frames"] = dir_frames
        elif "dir_frames" in self._sprite_meta:
            del self._sprite_meta["dir_frames"]
        self.hitboxes_changed.emit()
        self._lbl_status.setText(tr("hitbox.saved"))
        self._refresh_checklist()

    # ------------------------------------------------------------------
    # Directional frames
    # ------------------------------------------------------------------

    # Direction convention matches ngpc_vehicle: 0=E 1=NE 2=N 3=NW 4=W 5=SW 6=S 7=SE
    # We only store unique frames (N, NE, E, SE, S).
    # NW=mirror(NE), W=mirror(E), SW=mirror(SE) — derived at export time.
    _DIR_KEYS_8 = ("N", "NE", "E", "SE", "S")
    _DIR_KEYS_4 = ("N", "E", "S")   # W = mirror(E)

    def _on_dir_mode_changed(self, _idx: int) -> None:
        self._refresh_dir_ui()
        self._on_dir_frame_changed()

    def _on_dir_frame_changed(self) -> None:
        self._dir_frames = self._collect_dir_frames()
        self._update_dir_auto_labels()

    def _refresh_dir_ui(self) -> None:
        if self._dir_mode_combo is None:
            return
        mode = str(self._dir_mode_combo.currentData() or "none")
        visible_keys = {
            "8dir": set(self._DIR_KEYS_8),
            "4dir": set(self._DIR_KEYS_4),
        }.get(mode, set())
        for dkey, sb in self._dir_frame_widgets.items():
            sb.setEnabled(dkey in visible_keys)
            auto_lbl = getattr(self, f"_dir_auto_lbl_{dkey}", None)
            if auto_lbl:
                auto_lbl.setVisible(dkey in visible_keys)
        self._update_dir_auto_labels()

    def _update_dir_auto_labels(self) -> None:
        """Show mirror annotations next to each spinbox."""
        if self._dir_mode_combo is None:
            return
        mode = str(self._dir_mode_combo.currentData() or "none")
        mirror_of = {
            "8dir": {"NE": None, "E": None, "SE": None,
                     "N": None,  "S": None},
            "4dir": {"N": None, "E": None, "S": None},
        }.get(mode, {})
        mirror_labels = {
            "8dir": {"NE": "← NW flip", "E": "← W flip", "SE": "← SW flip"},
            "4dir": {"E": "← W flip"},
        }.get(mode, {})
        for dkey in self._dir_frame_widgets:
            auto_lbl = getattr(self, f"_dir_auto_lbl_{dkey}", None)
            if auto_lbl:
                auto_lbl.setText(mirror_labels.get(dkey, ""))

    def _collect_dir_frames(self) -> dict:
        if self._dir_mode_combo is None:
            return {}
        mode = str(self._dir_mode_combo.currentData() or "none")
        if mode == "none":
            return {}
        keys = self._DIR_KEYS_8 if mode == "8dir" else self._DIR_KEYS_4
        d: dict = {"mode": mode}
        for k in keys:
            sb = self._dir_frame_widgets.get(k)
            d[k] = int(sb.value()) if sb else 0
        return d

    def _load_dir_frames(self) -> None:
        if self._sprite_meta is None or self._dir_mode_combo is None:
            return
        df = self._sprite_meta.get("dir_frames") or {}
        mode = str(df.get("mode", "none") or "none")
        if mode not in ("none", "4dir", "8dir"):
            mode = "none"
        idx = self._dir_mode_combo.findData(mode)
        self._dir_mode_combo.blockSignals(True)
        self._dir_mode_combo.setCurrentIndex(max(0, idx))
        self._dir_mode_combo.blockSignals(False)
        for dkey, sb in self._dir_frame_widgets.items():
            sb.blockSignals(True)
            sb.setValue(int(df.get(dkey, 0) or 0))
            sb.blockSignals(False)
        self._dir_frames = dict(df)
        self._refresh_dir_ui()

    def _on_ctrl_role_changed(self) -> None:
        self._refresh_ctrl_ui()
        self._on_ctrl_changed()

    def _on_ctrl_changed(self) -> None:
        self._ctrl = self._collect_ctrl()
        self._refresh_checklist()

    def _populate_ctrl_role_combo(self, keep_role: str | None = None) -> None:
        combo = getattr(self, "_ctrl_role_cb", None)
        if combo is None:
            return
        cur = str(keep_role if keep_role is not None else combo.currentData() or "none").strip().lower()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(tr("hitbox.ctrl_role_none"), "none")
        combo.addItem(tr("hitbox.ctrl_role_player"), "player")
        if cur == "enemy":
            combo.addItem(tr("hitbox.ctrl_role_enemy_legacy"), "enemy")
        elif cur == "npc":
            combo.addItem(tr("hitbox.ctrl_role_npc_legacy"), "npc")
        idx = combo.findData(cur if cur in ("none", "player", "enemy", "npc") else "none")
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def _refresh_ctrl_ui(self) -> None:
        role = str(self._ctrl_role_cb.currentData() or "none")
        is_player = role == "player"
        gameplay_role = sprite_gameplay_role(self._sprite_meta or {})
        self._ctrl_bindings_widget.setVisible(is_player)
        self._lbl_ctrl_hint.setText(tr(f"hitbox.ctrl_hint_{role}") if role in ("none", "player", "enemy", "npc") else "")
        if hasattr(self, "_lbl_ctrl_gameplay"):
            detail = tr("hitbox.ctrl_gameplay_role", role=gameplay_role)
            mismatch = False
            if gameplay_role == "player" and role != "player":
                detail += " " + tr("hitbox.ctrl_gameplay_warn_player")
                mismatch = True
            elif gameplay_role != "player" and role == "player":
                detail += " " + tr("hitbox.ctrl_gameplay_warn_mismatch", role=gameplay_role)
                mismatch = True
            else:
                detail += " " + tr("hitbox.ctrl_gameplay_ok")
            self._lbl_ctrl_gameplay.setText(detail)
            self._lbl_ctrl_gameplay.setStyleSheet(
                "color: #e07020; font-size: 10px; font-weight: bold;" if mismatch
                else "color: #9aa3ad; font-size: 10px;"
            )
        if hasattr(self, "_btn_export_ctrl"):
            self._btn_export_ctrl.setToolTip(
                tr("hitbox.export_ctrl_player_tt") if is_player
                else tr("hitbox.export_ctrl_player_only_tt")
            )
            self._btn_export_ctrl.setEnabled(bool(self._file_path) and is_player)
        for action_cb in self._ctrl_action_cbs.values():
            action_cb.setEnabled(bool(self._file_path) and is_player)
        if hasattr(self, "_btn_ctrl_preset"):
            self._btn_ctrl_preset.setEnabled(bool(self._file_path) and is_player)

    def _collect_ctrl(self) -> dict:
        """Build action→button dict from the button-centric UI."""
        role = self._ctrl_role_cb.currentData() or "none"
        result: dict = {"role": role}
        for pad_name, cb in self._ctrl_action_cbs.items():
            action = cb.currentData()  # str action key or None
            if action:
                result[action] = pad_name
        return result

    def _load_ctrl(self, ctrl: dict) -> None:
        """Populate button-centric Controller UI from a saved ctrl dict.

        The stored format is action→button (e.g. {"left":"PAD_LEFT"}).
        We invert it to pad→action to fill the UI rows.
        Also handles legacy dicts that may omit some keys (falls back to defaults).
        """
        role = str(ctrl.get("role", "none") or "none").strip().lower()
        self._populate_ctrl_role_combo(role)
        self._refresh_ctrl_ui()

        # Build pad_name → action reverse map (skip "role" key)
        pad_to_action: dict[str, str] = {}
        for key, val in ctrl.items():
            if key == "role" or not val:
                continue
            # val is a PAD_xxx string, key is the action name
            pad_to_action[str(val)] = str(key)

        # If the stored dict has no pad assignments at all (empty ctrl, first load)
        # seed with sensible defaults so the player template is usable immediately
        if not pad_to_action and role == "player":
            pad_to_action = {
                "PAD_LEFT":  "left",  "PAD_RIGHT": "right",
                "PAD_UP":    "up",    "PAD_DOWN":  "down",
                "PAD_A":     "jump",  "PAD_B":     "action",
            }

        for pad_name, cb in self._ctrl_action_cbs.items():
            action = pad_to_action.get(pad_name, None)
            idx = cb.findData(action)
            cb.blockSignals(True)
            cb.setCurrentIndex(max(0, idx))
            cb.blockSignals(False)
        self._ctrl = self._collect_ctrl()

    # ---- Controller presets --------------------------------------------------

    _CTRL_PRESETS: dict[str, dict] = {
        "platformer": {
            "role": "player",
            "left": "PAD_LEFT", "right": "PAD_RIGHT",
            "jump": "PAD_A",    "action": "PAD_B",
        },
        "shmup_h": {
            "role": "player",
            "left": "PAD_LEFT", "right": "PAD_RIGHT",
            "up":   "PAD_UP",   "down":  "PAD_DOWN",
            "shoot": "PAD_A",   "action": "PAD_B",
        },
        "topdown4": {
            "role": "player",
            "left": "PAD_LEFT", "right": "PAD_RIGHT",
            "up":   "PAD_UP",   "down":  "PAD_DOWN",
            "action": "PAD_A",
        },
        "topdown8": {
            "role": "player",
            "left": "PAD_LEFT", "right": "PAD_RIGHT",
            "up":   "PAD_UP",   "down":  "PAD_DOWN",
            "action": "PAD_A",  "sprint": "PAD_B",
        },
        "rpg": {
            "role": "player",
            "left": "PAD_LEFT", "right": "PAD_RIGHT",
            "up":   "PAD_UP",   "down":  "PAD_DOWN",
            "action": "PAD_A",  "sprint": "PAD_B",
        },
    }

    def _show_ctrl_preset_menu(self) -> None:
        menu = QMenu(self)
        preset_labels = [
            ("platformer", tr("hitbox.ctrl_preset_platformer")),
            ("shmup_h",    tr("hitbox.ctrl_preset_shmup_h")),
            ("topdown4",   tr("hitbox.ctrl_preset_topdown4")),
            ("topdown8",   tr("hitbox.ctrl_preset_topdown8")),
            ("rpg",        tr("hitbox.ctrl_preset_rpg")),
        ]
        for key, label in preset_labels:
            act = menu.addAction(label)
            act.setData(key)
        chosen = menu.exec(self._btn_ctrl_preset.mapToGlobal(
            self._btn_ctrl_preset.rect().bottomLeft()
        ))
        if chosen is not None:
            self._apply_ctrl_preset(chosen.data())

    def _apply_ctrl_preset(self, preset_key: str) -> None:
        preset = self._CTRL_PRESETS.get(preset_key)
        if not preset:
            return
        self._load_ctrl(preset)
        self._on_ctrl_changed()

    # ------------------------------------------------------------------
    # Animation states
    # ------------------------------------------------------------------

    def _on_anims_changed(self) -> None:
        self._anims = self._collect_anims()
        self._refresh_checklist()
        self._refresh_spd_hint()

    def _refresh_spd_hint(self) -> None:
        def _is_pow2(n: int) -> bool:
            return n > 0 and (n & (n - 1)) == 0

        bad: list[str] = []
        pair = self._prop_widgets.get("anim_spd")
        if pair:
            cb, sb = pair
            if cb.isChecked() and not _is_pow2(sb.value()):
                bad.append(f"anim_spd={sb.value()}")
        for state, (en_cb, _s, _c, _l, spd_sb, _p) in self._anim_rows.items():
            if en_cb.isChecked() and not _is_pow2(spd_sb.value()):
                bad.append(f"{state}.spd={spd_sb.value()}")
        if bad:
            self._lbl_spd_hint.setText(
                "💡 " + ", ".join(bad)
                + " — utilise 1,2,4,8,16,32 pour éviter les divisions (T900 sans mul/div hw)"
            )
        else:
            self._lbl_spd_hint.setText("")

    def _collect_anims(self) -> dict:
        result = {}
        for state, (en_cb, start_sb, count_sb, loop_cb, spd_sb, _pb) in self._anim_rows.items():
            if en_cb.isChecked():
                result[state] = {
                    "start": start_sb.value(),
                    "count": count_sb.value(),
                    "loop":  loop_cb.isChecked(),
                    "spd":   spd_sb.value(),
                }
        return result

    def _load_anims(self, anims: dict) -> None:
        for state, (en_cb, start_sb, count_sb, loop_cb, spd_sb, play_btn) in self._anim_rows.items():
            data = anims.get(state)
            en_cb.blockSignals(True)
            start_sb.blockSignals(True)
            count_sb.blockSignals(True)
            loop_cb.blockSignals(True)
            spd_sb.blockSignals(True)
            if data:
                en_cb.setChecked(True)
                start_sb.setValue(int(data.get("start", 0)))
                count_sb.setValue(max(1, int(data.get("count", 1))))
                loop_cb.setChecked(bool(data.get("loop", True)))
                spd_sb.setValue(max(1, int(data.get("spd", 6))))
                self._set_anim_spin_interactive(start_sb, True)
                self._set_anim_spin_interactive(count_sb, True)
                loop_cb.setEnabled(True)
                self._set_anim_spin_interactive(spd_sb, True)
                play_btn.setEnabled(True)
            else:
                en_cb.setChecked(False)
                start_sb.setValue(0)
                count_sb.setValue(1)
                loop_cb.setChecked(True)
                spd_sb.setValue(6)
                self._set_anim_spin_interactive(start_sb, False)
                self._set_anim_spin_interactive(count_sb, False)
                loop_cb.setEnabled(False)
                self._set_anim_spin_interactive(spd_sb, False)
                play_btn.setEnabled(False)
            play_btn.setText(tr("hitbox.anim_preview_play"))
            en_cb.blockSignals(False)
            start_sb.blockSignals(False)
            count_sb.blockSignals(False)
            loop_cb.blockSignals(False)
            spd_sb.blockSignals(False)
        self._anims = self._collect_anims()
        self._refresh_checklist()

    # ── Named animations (ngpc_anim) ───────────────────────────────────────

    def _load_named_anims(self, named_anims: list) -> None:
        tbl = self._named_anims_table
        tbl.blockSignals(True)
        tbl.setRowCount(0)
        for entry in named_anims or []:
            row = tbl.rowCount()
            tbl.insertRow(row)
            tbl.setItem(row, 0, QTableWidgetItem(str(entry.get("name") or "")))
            frames = entry.get("frames") or []
            tbl.setItem(row, 1, QTableWidgetItem(", ".join(str(f) for f in frames)))
            tbl.setItem(row, 2, QTableWidgetItem(str(entry.get("speed") or 6)))
            mode_item = QTableWidgetItem(str(entry.get("mode") or "loop"))
            tbl.setItem(row, 3, mode_item)
        tbl.blockSignals(False)

    def _collect_named_anims(self) -> list:
        result = []
        tbl = self._named_anims_table
        for row in range(tbl.rowCount()):
            name = str((tbl.item(row, 0) or QTableWidgetItem("")).text()).strip()
            frames_raw = str((tbl.item(row, 1) or QTableWidgetItem("")).text()).strip()
            speed_raw = str((tbl.item(row, 2) or QTableWidgetItem("6")).text()).strip()
            mode = str((tbl.item(row, 3) or QTableWidgetItem("loop")).text()).strip().lower()
            if not name:
                continue
            frames = []
            for tok in frames_raw.replace(";", ",").split(","):
                tok = tok.strip()
                if tok.isdigit():
                    frames.append(int(tok))
            speed = int(speed_raw) if speed_raw.isdigit() else 6
            speed = max(1, min(255, speed))
            if mode not in ("loop", "pingpong", "oneshot"):
                mode = "loop"
            if not frames:
                continue
            result.append({"name": name, "frames": frames, "speed": speed, "mode": mode})
        return result

    def _add_named_anim(self) -> None:
        tbl = self._named_anims_table
        row = tbl.rowCount()
        tbl.insertRow(row)
        tbl.setItem(row, 0, QTableWidgetItem("anim_name"))
        tbl.setItem(row, 1, QTableWidgetItem("0, 1"))
        tbl.setItem(row, 2, QTableWidgetItem("6"))
        tbl.setItem(row, 3, QTableWidgetItem("loop"))
        tbl.editItem(tbl.item(row, 0))

    def _del_named_anim(self) -> None:
        tbl = self._named_anims_table
        rows = sorted({idx.row() for idx in tbl.selectedIndexes()}, reverse=True)
        for row in rows:
            tbl.removeRow(row)

    # ── Motion Patterns (ngpc_motion) ──────────────────────────────────────

    def _load_motion_patterns(self, patterns: list) -> None:
        tbl = self._motion_table
        tbl.blockSignals(True)
        tbl.setRowCount(0)
        for entry in patterns or []:
            row = tbl.rowCount()
            tbl.insertRow(row)
            tbl.setItem(row, 0, QTableWidgetItem(str(entry.get("name")   or "")))
            tbl.setItem(row, 1, QTableWidgetItem(str(entry.get("steps")  or "")))
            tbl.setItem(row, 2, QTableWidgetItem(str(entry.get("window") or "20")))
            tbl.setItem(row, 3, QTableWidgetItem(str(entry.get("anim")   or "")))
        tbl.blockSignals(False)

    def _collect_motion_patterns(self) -> list:
        result = []
        tbl = self._motion_table
        for row in range(tbl.rowCount()):
            name    = str((tbl.item(row, 0) or QTableWidgetItem("")).text()).strip()
            steps   = str((tbl.item(row, 1) or QTableWidgetItem("")).text()).strip()
            win_raw = str((tbl.item(row, 2) or QTableWidgetItem("20")).text()).strip()
            anim    = str((tbl.item(row, 3) or QTableWidgetItem("")).text()).strip().lower()
            if not name:
                continue
            try:
                window = max(4, min(120, int(win_raw)))
            except ValueError:
                window = 20
            result.append({"name": name, "steps": steps, "window": window, "anim": anim})
        return result

    def _on_motion_changed(self) -> None:
        self._motion_patterns = self._collect_motion_patterns()

    def _add_motion_pattern(self) -> None:
        tbl = self._motion_table
        row = tbl.rowCount()
        tbl.insertRow(row)
        tbl.setItem(row, 0, QTableWidgetItem("PAT_NAME"))
        tbl.setItem(row, 1, QTableWidgetItem("D DR R+A"))
        tbl.setItem(row, 2, QTableWidgetItem("20"))
        tbl.setItem(row, 3, QTableWidgetItem("special"))
        tbl.editItem(tbl.item(row, 0))

    def _del_motion_pattern(self) -> None:
        tbl = self._motion_table
        rows = sorted({idx.row() for idx in tbl.selectedIndexes()}, reverse=True)
        for row in rows:
            tbl.removeRow(row)

    def _show_motion_preset_menu(self) -> None:
        """Show a dropdown of common fighting-game motion patterns."""
        _PRESETS: list[tuple] = [
            # (label, name, steps, window, anim)
            ("Quarter-circle → + A  (↓↘→+A)", "QCF_A",  "D DR R+A",  20, "special"),
            ("Quarter-circle → + B  (↓↘→+B)", "QCF_B",  "D DR R+B",  20, "special"),
            ("Quarter-circle ← + A  (↓↙←+A)", "QCB_A",  "D DL L+A",  20, "special"),
            ("Quarter-circle ← + B  (↓↙←+B)", "QCB_B",  "D DL L+B",  20, "special"),
            None,
            ("Dragon Punch + A  (→↓↘+A)",      "DP_A",   "R D DR+A",  20, "attack"),
            ("Dragon Punch + B  (→↓↘+B)",      "DP_B",   "R D DR+B",  20, "attack"),
            None,
            ("Double-tap →  (dash avant)",     "DASH_F", "R N R",     15, "run"),
            ("Double-tap ←  (dash arrière)",   "DASH_B", "L N L",     15, "run"),
            None,
            ("Saisie manuelle (ligne vide)",   None,     "",           20, ""),
        ]
        menu = QMenu(self)
        for item in _PRESETS:
            if item is None:
                menu.addSeparator()
                continue
            label, name, steps, window, anim = item
            act = menu.addAction(label)
            act.setData((name, steps, window, anim))

        chosen = menu.exec(
            self._btn_motion_preset.mapToGlobal(
                self._btn_motion_preset.rect().bottomLeft()
            )
        )
        if chosen is None or chosen.data() is None:
            return
        name, steps, window, anim = chosen.data()
        tbl = self._motion_table
        row = tbl.rowCount()
        tbl.insertRow(row)
        tbl.setItem(row, 0, QTableWidgetItem(name or "PAT_NAME"))
        tbl.setItem(row, 1, QTableWidgetItem(steps or ""))
        tbl.setItem(row, 2, QTableWidgetItem(str(window)))
        tbl.setItem(row, 3, QTableWidgetItem(anim or ""))
        if not name:
            tbl.editItem(tbl.item(row, 0))

    def _export_motion_h(self) -> None:
        if self._file_path is None:
            return
        patterns = self._collect_motion_patterns()
        if not patterns:
            QMessageBox.information(
                self, tr("hitbox.export_motion"), tr("hitbox.no_motion_patterns")
            )
            return
        anim_states = list(self._collect_anims().keys())
        name = self._file_path.stem
        out_text, errors = make_motion_h(name, self._file_path.name, patterns, anim_states)
        if errors:
            msg = "\n".join(f"• {e}" for e in errors)
            if not out_text:
                QMessageBox.warning(
                    self, tr("hitbox.export_motion"),
                    tr("hitbox.motion_export_errors") + ":\n\n" + msg,
                )
                return
            QMessageBox.warning(
                self, tr("hitbox.export_motion"),
                tr("hitbox.motion_export_partial") + ":\n\n" + msg,
            )
        if not out_text:
            return
        default_name = str(self._file_path.parent / f"{name}_motion.h")
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("hitbox.export_motion_title"),
            default_name,
            "C Headers (*.h);;All files (*.*)",
        )
        if not out_path:
            return
        try:
            Path(out_path).write_text(out_text, encoding="utf-8")
            self._lbl_status.setText(tr("hitbox.exported", path=Path(out_path).name))
        except Exception as exc:
            QMessageBox.warning(self, "Export Error", str(exc))

    def _export_named_anims_h(self) -> None:
        if self._file_path is None:
            return
        named_anims = self._collect_named_anims()
        if not named_anims:
            QMessageBox.information(
                self, tr("hitbox.export_named_anims"), tr("hitbox.no_named_anims")
            )
            return
        name = self._file_path.stem
        out_text = make_named_anims_h(name, self._file_path.name, named_anims)
        if not out_text:
            QMessageBox.information(
                self, tr("hitbox.export_named_anims"), tr("hitbox.no_named_anims")
            )
            return
        default_name = str(self._file_path.parent / f"{name}_namedanims.h")
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("hitbox.export_named_anims_title"),
            default_name,
            "C Headers (*.h);;All files (*.*)",
        )
        if not out_path:
            return
        try:
            Path(out_path).write_text(out_text, encoding="utf-8")
            self._lbl_status.setText(tr("hitbox.exported", path=Path(out_path).name))
        except Exception as exc:
            QMessageBox.warning(self, "Export Error", str(exc))

    def _export_anims_h(self) -> None:
        if self._file_path is None:
            return
        anims = self._collect_anims()
        if not anims:
            QMessageBox.information(
                self, tr("hitbox.export_anims"), tr("hitbox.no_anims_enabled")
            )
            return
        name = self._file_path.stem
        out_text = make_anims_h(name, self._file_path.name, anims)
        default_name = str(self._file_path.parent / f"{name}_anims.h")
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("hitbox.export_anims_title"),
            default_name,
            "C Headers (*.h);;All files (*.*)",
        )
        if not out_path:
            return
        try:
            Path(out_path).write_text(out_text, encoding="utf-8")
            self._lbl_status.setText(tr("hitbox.exported", path=Path(out_path).name))
        except Exception as exc:
            QMessageBox.warning(self, "Export Error", str(exc))

    def _export_ctrl_h(self) -> None:
        if self._file_path is None:
            return
        ctrl = self._collect_ctrl()
        role = sprite_gameplay_role(self._sprite_meta or {}, ctrl.get("role", "none"))
        if role == "prop":
            QMessageBox.information(
                self, tr("hitbox.export_ctrl"), tr("hitbox.no_ctrl_role")
            )
            return
        if role != "player":
            QMessageBox.information(
                self, tr("hitbox.export_ctrl"), tr("hitbox.no_ctrl_player")
            )
            return
        props = {
            k: sb.value()
            for k, (cb, sb) in self._prop_widgets.items()
            if cb.isChecked()
        }
        name = self._file_path.stem
        out_text = make_ctrl_h(name, self._file_path.name, ctrl, props, role=role)
        default_name = str(self._file_path.parent / f"{name}_ctrl.h")
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("hitbox.export_ctrl_title"),
            default_name,
            "C Headers (*.h);;All files (*.*)",
        )
        if not out_path:
            return
        try:
            from pathlib import Path as _Path
            _Path(out_path).write_text(out_text, encoding="utf-8")
            self._lbl_status.setText(tr("hitbox.exported", path=_Path(out_path).name))
        except Exception as exc:
            QMessageBox.warning(self, "Export Error", str(exc))

    def _export_h(self) -> None:
        if self._file_path is None:
            return

        name = self._file_path.stem
        fc = self._frame_count
        out_text = make_hitbox_h(
            name, self._file_path.name,
            self._frame_w, self._frame_h, fc,
            self._hurtboxes,
        )
        default_name = str(self._file_path.parent / f"{name}_hitbox.h")
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("hitbox.export_title"),
            default_name,
            "C Headers (*.h);;All files (*.*)",
        )
        if not out_path:
            return
        try:
            Path(out_path).write_text(out_text, encoding="utf-8")
            self._lbl_status.setText(tr("hitbox.exported", path=Path(out_path).name))
        except Exception as exc:
            QMessageBox.warning(self, "Export Error", str(exc))

    def _export_props_h(self) -> None:
        if self._file_path is None:
            return

        # Only export checked props
        props = {
            k: sb.value()
            for k, (cb, sb) in self._prop_widgets.items()
            if cb.isChecked()
        }
        if not props:
            QMessageBox.information(
                self, tr("hitbox.export_props"), tr("hitbox.no_props_enabled")
            )
            return

        name = self._file_path.stem
        fc   = self._frame_count
        out_text = make_props_h(
            name, self._file_path.name,
            self._frame_w, self._frame_h, fc,
            props,
        )
        default_name = str(self._file_path.parent / f"{name}_props.h")
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            tr("hitbox.export_props_title"),
            default_name,
            "C Headers (*.h);;All files (*.*)",
        )
        if not out_path:
            return
        try:
            Path(out_path).write_text(out_text, encoding="utf-8")
            self._lbl_status.setText(tr("hitbox.exported", path=Path(out_path).name))
        except Exception as exc:
            QMessageBox.warning(self, "Export Error", str(exc))

    # ------------------------------------------------------------------
    # Entity template — save / badge
    # ------------------------------------------------------------------

    def _update_template_badge(self) -> None:
        if not hasattr(self, '_lbl_template_badge'):
            return
        if self._sprite_meta is None or not isinstance(self._project_data, dict):
            self._lbl_template_badge.setText('')
            return
        file_rel = self._sprite_meta.get('file', '')
        tpl = find_template_for_file(self._project_data, file_rel)
        if tpl:
            self._lbl_template_badge.setText(
                tr('hitbox.template_badge', name=tpl.get('name', '?'))
            )
            self._btn_save_template.setText(tr('hitbox.update_template'))
        else:
            self._lbl_template_badge.setText('')
            self._btn_save_template.setText(tr('hitbox.save_template'))

    def _on_save_template(self) -> None:
        if self._sprite_meta is None or not isinstance(self._project_data, dict):
            return
        self._save_hitboxes()
        file_rel = self._sprite_meta.get('file', '')
        existing = find_template_for_file(self._project_data, file_rel)
        if existing:
            reply = QMessageBox.question(
                self,
                tr('hitbox.update_template'),
                tr('hitbox.update_template_confirm', name=existing.get('name', '?')),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            existing.update(snapshot_sprite_fields(self._sprite_meta))
            role = (
                self._sprite_meta.get('gameplay_role')
                or self._sprite_meta.get('ctrl', {}).get('role', '')
            )
            if role:
                existing['role'] = role
        else:
            from pathlib import Path as _Path
            suggested = _Path(file_rel).stem if file_rel else 'template'
            name, ok = QInputDialog.getText(
                self,
                tr('hitbox.save_template'),
                tr('hitbox.save_template_prompt'),
                text=suggested,
            )
            if not ok or not name.strip():
                return
            tpl = new_entity_template(name.strip(), sprite_meta=self._sprite_meta)
            self._project_data.setdefault('entity_templates', []).append(tpl)
        mw = self.parent()
        while mw is not None and not hasattr(mw, '_save_project'):
            mw = mw.parent() if hasattr(mw, 'parent') and callable(mw.parent) else None
        if mw is not None:
            mw._save_project()
        self._lbl_status.setText(tr('hitbox.template_saved'))
        self._update_template_badge()

