"""
ui/tabs/mechanics_tab.py — Mechanics enable/disable tab (project-level).

Hosts the toggle list for every gameplay mechanic registered in
core.mechanics.MECHANICS_REGISTRY. Disabling a mechanic:
  - hides its config UI in scene/entity panels
  - and, depending on the mechanic, either NULLs its exported pointer, emits
    neutral defaults, or gates the related runtime/UI path.

Each mechanic row shows:
  - checkbox + label
  - description paragraph
  - breadcrumb(s) — exact UI path where to configure the mechanic once enabled
                    (so the user doesn't have to hunt through menus)

A search field at the top filters mechanics by id/label/description/keywords
in real time (case-insensitive substring match).

Adding a new mechanic = append a dict to MECHANICS_REGISTRY in core/mechanics.py.
This tab refreshes automatically from the registry; no UI code change required.
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt, QSettings, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox as _QtComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox as _QtSpinBox,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Wheel-scroll guarded widgets — mechanics settings must NOT change when the
# user scrolls the tab. Wheel is disabled entirely on spinboxes and combos:
# the previous "allow when focused" check was unreliable because Qt's
# StrongFocus policy grabs focus from the first wheel event, after which
# subsequent ticks mutate the value. Users change values via click + typing
# or the on-widget arrows; the wheel is reserved for page scroll.
# ---------------------------------------------------------------------------

class _NoScrollSpinBox(_QtSpinBox):
    """QSpinBox that always ignores wheel events. `event.ignore()` lets the
    event bubble up to the enclosing QScrollArea so the page scrolls."""
    def wheelEvent(self, event):  # noqa: N802 (Qt naming)
        event.ignore()


class _NoScrollComboBox(_QtComboBox):
    """Same idea as _NoScrollSpinBox for combo boxes."""
    def wheelEvent(self, event):  # noqa: N802
        event.ignore()


# Rebind the Qt names so every existing call site in this file (and the
# factory helpers) picks up the guarded variant without code changes.
QSpinBox = _NoScrollSpinBox
QComboBox = _NoScrollComboBox


def _clear_layout(layout) -> None:
    """Recursively delete all widgets/layout items from a Qt layout."""
    while layout.count():
        item = layout.takeAt(0)
        child = item.layout()
        if child is not None:
            _clear_layout(child)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


# Shared row builder for inline config widgets — keeps inline factory code tight.
def _row(parent_lay, label_text: str, widget: QWidget, label_width: int = 160) -> None:
    r = QHBoxLayout()
    lbl = QLabel(label_text)
    lbl.setFixedWidth(label_width)
    lbl.setStyleSheet("color:#c8d0d8; font-size:10px;")
    r.addWidget(lbl)
    r.addWidget(widget, 1)
    parent_lay.addLayout(r)


def _scene_picker(project_data: dict, current_id: str, on_change) -> QComboBox:
    """Combo listing all scenes in the project + a leading '(scène courante)' entry.
    Used by mechanics that need to pick a scene as a BG reference."""
    cb = QComboBox()
    cb.addItem("(scène courante au moment du screen)", "")
    scenes = project_data.get("scenes", []) if isinstance(project_data, dict) else []
    if isinstance(scenes, list):
        for sc in scenes:
            if not isinstance(sc, dict):
                continue
            sid = str(sc.get("id") or "").strip()
            label = str(sc.get("label") or sc.get("name") or sid)
            if sid:
                cb.addItem(label, sid)
    idx = cb.findData(current_id or "")
    cb.setCurrentIndex(max(0, idx))
    cb.currentIndexChanged.connect(on_change)
    return cb

from core.mechanics import (
    CATEGORY_DISPLAY_ORDER,
    CATEGORY_LABELS,
    MECHANICS_REGISTRY,
    get_mechanic_config,
    get_mechanics,
    search_mechanics,
    set_mechanic_config_field,
    set_mechanic_enabled,
)
from i18n.lang import tr


# ---------------------------------------------------------------------------
# Inline config widgets — one factory per mechanic that exposes tunable params
# directly in the MechanicsTab (i.e. project-level settings with no per-entity
# config). Add a new entry to INLINE_CONFIG_FACTORIES below to plug a new one.
# ---------------------------------------------------------------------------

def _build_death_fade_config(project_data: dict, on_change) -> QWidget:
    """Inline config for MECH-12 fade_transitions: wait/fade/color used by
    automatic player-death fades AND by fade_out / fade_in trigger actions."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 4, 0, 0)
    lay.setSpacing(4)
    cfg = get_mechanic_config(project_data, "fade_transitions")

    def _row(label: str, spin: QSpinBox) -> None:
        r = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(140)
        lbl.setStyleSheet("color:#c8d0d8; font-size:10px;")
        r.addWidget(lbl)
        r.addWidget(spin, 1)
        lay.addLayout(r)

    sp_wait = QSpinBox()
    sp_wait.setRange(0, 255)
    sp_wait.setValue(int(cfg.get("wait_frames", 60) or 60))
    sp_wait.setToolTip(tr("mech.death_fade.wait_tt"))
    sp_wait.valueChanged.connect(
        lambda v: (set_mechanic_config_field(project_data, "fade_transitions", "wait_frames", int(v)), on_change())
    )
    _row(tr("mech.death_fade.wait"), sp_wait)

    sp_fade = QSpinBox()
    sp_fade.setRange(1, 255)
    sp_fade.setValue(int(cfg.get("fade_frames", 64) or 64))
    sp_fade.setToolTip(tr("mech.death_fade.fade_tt"))
    sp_fade.valueChanged.connect(
        lambda v: (set_mechanic_config_field(project_data, "fade_transitions", "fade_frames", int(v)), on_change())
    )
    _row(tr("mech.death_fade.fade"), sp_fade)

    r = QHBoxLayout()
    lbl_color = QLabel(tr("mech.death_fade.color"))
    lbl_color.setFixedWidth(140)
    lbl_color.setStyleSheet("color:#c8d0d8; font-size:10px;")
    r.addWidget(lbl_color)
    cb_color = QComboBox()
    cb_color.addItem(tr("mech.death_fade.color_black"), "black")
    cb_color.addItem(tr("mech.death_fade.color_white"), "white")
    pre = str(cfg.get("fade_color", "black") or "black")
    idx = cb_color.findData(pre)
    cb_color.setCurrentIndex(max(0, idx))
    cb_color.currentIndexChanged.connect(
        lambda _i: (set_mechanic_config_field(project_data, "fade_transitions", "fade_color", cb_color.currentData() or "black"), on_change())
    )
    r.addWidget(cb_color, 1)
    lay.addLayout(r)
    return w


def _build_damage_popup_config(project_data: dict, on_change) -> QWidget:
    """Inline config for MECH-11 damage_popup: plane (SCR1/SCR2), ttl, rise,
    palette. Includes a visible warning that the chosen plane must be fixed."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 4, 0, 0)
    lay.setSpacing(4)
    cfg = get_mechanic_config(project_data, "damage_popup")

    # Hardware constraint warning — popups are rendered on a tilemap plane,
    # which means they scroll WITH that plane. The plane has to be parallax-
    # locked (= "fixe") in the Scene Layout otherwise digits drift with the
    # camera and look broken.
    warn = QLabel(tr("mech.dmg_popup.fixed_warn"))
    warn.setWordWrap(True)
    warn.setStyleSheet(
        "color:#d8a23a; font-size:10px; background:#3a2f10;"
        " border:1px solid #5e4a18; border-radius:3px; padding:4px;"
    )
    lay.addWidget(warn)

    def _row(label: str, widget: QWidget) -> None:
        r = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(140)
        lbl.setStyleSheet("color:#c8d0d8; font-size:10px;")
        r.addWidget(lbl)
        r.addWidget(widget, 1)
        lay.addLayout(r)

    cb_plane = QComboBox()
    cb_plane.addItem("SCR2  (recommandé — souvent HUD)", "SCR2")
    cb_plane.addItem("SCR1  (si SCR2 est utilisé pour autre chose)", "SCR1")
    pre = str(cfg.get("plane", "SCR2") or "SCR2").upper()
    idx = cb_plane.findData(pre)
    cb_plane.setCurrentIndex(max(0, idx))
    cb_plane.setToolTip(tr("mech.dmg_popup.plane_tt"))
    cb_plane.currentIndexChanged.connect(
        lambda _i: (set_mechanic_config_field(project_data, "damage_popup", "plane", cb_plane.currentData() or "SCR2"), on_change())
    )
    _row(tr("mech.dmg_popup.plane"), cb_plane)

    sp_ttl = QSpinBox()
    sp_ttl.setRange(10, 120)
    sp_ttl.setValue(int(cfg.get("ttl_frames", 40) or 40))
    sp_ttl.setToolTip(tr("mech.dmg_popup.ttl_tt"))
    sp_ttl.valueChanged.connect(
        lambda v: (set_mechanic_config_field(project_data, "damage_popup", "ttl_frames", int(v)), on_change())
    )
    _row(tr("mech.dmg_popup.ttl"), sp_ttl)

    sp_rise = QSpinBox()
    sp_rise.setRange(0, 4)
    sp_rise.setValue(int(cfg.get("rise_tiles", 2) or 2))
    sp_rise.setToolTip(tr("mech.dmg_popup.rise_tt"))
    sp_rise.valueChanged.connect(
        lambda v: (set_mechanic_config_field(project_data, "damage_popup", "rise_tiles", int(v)), on_change())
    )
    _row(tr("mech.dmg_popup.rise"), sp_rise)

    sp_pal = QSpinBox()
    sp_pal.setRange(0, 15)
    sp_pal.setValue(int(cfg.get("palette", 1) or 1))
    sp_pal.setToolTip(tr("mech.dmg_popup.palette_tt"))
    sp_pal.valueChanged.connect(
        lambda v: (set_mechanic_config_field(project_data, "damage_popup", "palette", int(v)), on_change())
    )
    _row(tr("mech.dmg_popup.palette"), sp_pal)
    return w


def _build_highscore_config(project_data: dict, on_change) -> QWidget:
    """Inline config for MECH-6 highscore: the parameters actually consumed by
    the current exporter/runtime path."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 4, 0, 0)
    lay.setSpacing(4)
    cfg = get_mechanic_config(project_data, "highscore")

    def _set(key, value):
        set_mechanic_config_field(project_data, "highscore", key, value)
        on_change()

    # Save toggle
    cb_save = QCheckBox(tr("mech.hiscore.save"))
    cb_save.setChecked(bool(cfg.get("save_to_flash", True)))
    cb_save.setToolTip(tr("mech.hiscore.save_tt"))
    cb_save.toggled.connect(lambda v: _set("save_to_flash", bool(v)))
    lay.addWidget(cb_save)

    note = QLabel(
        "Flash save OFF keeps the hi-score table active at runtime, but only in RAM for the current session."
    )
    note.setWordWrap(True)
    note.setStyleSheet(
        "color:#d8a23a; font-size:10px; background:#3a2f10;"
        " border:1px solid #5e4a18; border-radius:3px; padding:4px;"
    )
    lay.addWidget(note)

    # Auto-submit toggle
    cb_auto = QCheckBox(tr("mech.hiscore.auto_submit"))
    cb_auto.setChecked(bool(cfg.get("auto_submit", True)))
    cb_auto.setToolTip(tr("mech.hiscore.auto_submit_tt"))
    cb_auto.toggled.connect(lambda v: _set("auto_submit", bool(v)))
    lay.addWidget(cb_auto)

    # Number of entries
    sp_n = QSpinBox()
    sp_n.setRange(1, 10)
    sp_n.setValue(int(cfg.get("num_entries", 10) or 10))
    sp_n.setToolTip(tr("mech.hiscore.num_tt"))
    sp_n.valueChanged.connect(lambda v: _set("num_entries", int(v)))
    _row(lay, tr("mech.hiscore.num"), sp_n)

    # Initials length
    sp_i = QSpinBox()
    sp_i.setRange(1, 5)
    sp_i.setValue(int(cfg.get("initials_length", 3) or 3))
    sp_i.setToolTip(tr("mech.hiscore.initials_tt"))
    sp_i.valueChanged.connect(lambda v: _set("initials_length", int(v)))
    _row(lay, tr("mech.hiscore.initials"), sp_i)

    # Default initials displayed for empty entries (e.g. "AAA")
    le_def = QLineEdit()
    le_def.setMaxLength(5)
    le_def.setText(str(cfg.get("default_initials", "AAA") or "AAA")[:5])
    le_def.setToolTip(tr("mech.hiscore.default_initials_tt"))
    le_def.editingFinished.connect(lambda: _set("default_initials", le_def.text()[:5]))
    _row(lay, tr("mech.hiscore.default_initials"), le_def)

    # Default score for empty entries
    sp_ds = QSpinBox()
    sp_ds.setRange(0, 65535)
    sp_ds.setValue(int(cfg.get("default_score", 0) or 0))
    sp_ds.setToolTip(tr("mech.hiscore.default_score_tt"))
    sp_ds.valueChanged.connect(lambda v: _set("default_score", int(v)))
    _row(lay, tr("mech.hiscore.default_score"), sp_ds)

    return w


def _build_game_over_flow_config(project_data: dict, on_change) -> QWidget:
    """Inline config for MECH-13 game_over_flow: Continue / Final overlays and
    the hi-score name-entry caption are consumed by the exporter."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 4, 0, 0)
    lay.setSpacing(4)
    cfg = get_mechanic_config(project_data, "game_over_flow")

    def _set(key, value):
        set_mechanic_config_field(project_data, "game_over_flow", key, value)
        on_change()

    # --- Continue screen section ---
    cb_cont = QCheckBox(tr("mech.gof.enable_continue"))
    cb_cont.setChecked(bool(cfg.get("enable_continue", True)))
    cb_cont.setToolTip(tr("mech.gof.enable_continue_tt"))
    cb_cont.toggled.connect(lambda v: _set("enable_continue", bool(v)))
    lay.addWidget(cb_cont)

    note = QLabel(
        "Current exporter renders the Continue / Final overlays, the hi-score name-entry flow, and a modal hi-score board."
    )
    note.setWordWrap(True)
    note.setStyleSheet(
        "color:#d8a23a; font-size:10px; background:#3a2f10;"
        " border:1px solid #5e4a18; border-radius:3px; padding:4px;"
    )
    lay.addWidget(note)

    sp_cd = QSpinBox()
    sp_cd.setRange(1, 60)
    sp_cd.setValue(int(cfg.get("continue_countdown_sec", 9) or 9))
    sp_cd.setSuffix(" s")
    sp_cd.setToolTip(tr("mech.gof.countdown_tt"))
    sp_cd.valueChanged.connect(lambda v: _set("continue_countdown_sec", int(v)))
    _row(lay, tr("mech.gof.countdown"), sp_cd)

    sp_uses = QSpinBox()
    sp_uses.setRange(0, 20)
    sp_uses.setValue(int(cfg.get("continue_max_uses", 3) or 3))
    sp_uses.setToolTip(tr("mech.gof.max_uses_tt"))
    sp_uses.valueChanged.connect(lambda v: _set("continue_max_uses", int(v)))
    _row(lay, tr("mech.gof.max_uses"), sp_uses)

    le_prompt = QLineEdit()
    le_prompt.setMaxLength(16)
    le_prompt.setText(str(cfg.get("text_continue_prompt", "CONTINUE?") or "CONTINUE?"))
    le_prompt.editingFinished.connect(lambda: _set("text_continue_prompt", le_prompt.text()[:16]))
    _row(lay, tr("mech.gof.text_continue"), le_prompt)

    # Separator label
    sep_lbl = QLabel("── Final game over ──")
    sep_lbl.setStyleSheet("color:#d8a23a; font-size:10px; font-weight:bold; margin-top:6px;")
    lay.addWidget(sep_lbl)

    cb_final = QCheckBox(tr("mech.gof.enable_final"))
    cb_final.setChecked(bool(cfg.get("enable_final_screen", True)))
    cb_final.toggled.connect(lambda v: _set("enable_final_screen", bool(v)))
    lay.addWidget(cb_final)

    sp_min = QSpinBox()
    sp_min.setRange(0, 30)
    sp_min.setValue(int(cfg.get("final_min_duration_sec", 3) or 3))
    sp_min.setSuffix(" s")
    sp_min.setToolTip(tr("mech.gof.final_min_tt"))
    sp_min.valueChanged.connect(lambda v: _set("final_min_duration_sec", int(v)))
    _row(lay, tr("mech.gof.final_min"), sp_min)

    le_final = QLineEdit()
    le_final.setMaxLength(16)
    le_final.setText(str(cfg.get("text_final", "GAME OVER") or "GAME OVER"))
    le_final.editingFinished.connect(lambda: _set("text_final", le_final.text()[:16]))
    _row(lay, tr("mech.gof.text_final"), le_final)

    le_ne = QLineEdit()
    le_ne.setMaxLength(20)
    le_ne.setText(str(cfg.get("text_name_entry", "ENTER NAME") or "ENTER NAME")[:20])
    le_ne.editingFinished.connect(lambda: _set("text_name_entry", le_ne.text()[:20]))
    _row(lay, tr("mech.gof.text_name_entry"), le_ne)

    return w


def _sprite_type_picker(
    project_data: dict, current: str, on_change, *, allow_empty: bool = True,
    empty_label: str = "(aucun)",
) -> QComboBox:
    """Combo of every sprite type registered across the project's scenes.
    Used by mechanics that need to pick an arbitrary sprite (drone visual,
    bullet sprite, etc.). Deduplicates types across scenes."""
    cb = QComboBox()
    if allow_empty:
        cb.addItem(empty_label, "")
    seen: set[str] = set()
    scenes = project_data.get("scenes", []) if isinstance(project_data, dict) else []
    if isinstance(scenes, list):
        for sc in scenes:
            if not isinstance(sc, dict):
                continue
            for spr in (sc.get("sprites") or []):
                if not isinstance(spr, dict):
                    continue
                name = str(spr.get("name") or spr.get("id") or "").strip()
                if name and name not in seen:
                    seen.add(name)
                    cb.addItem(name, name)
    idx = cb.findData(current or "")
    cb.setCurrentIndex(max(0, idx))
    cb.currentIndexChanged.connect(on_change)
    return cb


def _build_option_satellite_config(project_data: dict, on_change) -> QWidget:
    """Inline config for MECH-14 option_satellite: count, lag, spacing, sprite,
    formation, destructible, plus a live OAM cost estimator."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 4, 0, 0)
    lay.setSpacing(4)
    cfg = get_mechanic_config(project_data, "option_satellite")

    def _set(key, value):
        set_mechanic_config_field(project_data, "option_satellite", key, value)
        on_change()

    # OAM estimator — updates live as max_options changes. The drone runtime
    # uses 1 sprite per drone every frame (centred 8×8 or 16×16), so the cost
    # is `max_options × 1`. Bullets fired by drones share the player bullet
    # pool, so they don't add a fixed OAM cost here.
    oam_lbl = QLabel()
    oam_lbl.setWordWrap(True)
    oam_lbl.setStyleSheet(
        "color:#8fb8e8; font-size:10px; background:#252b34;"
        " border:1px solid #3a4a5e; border-radius:3px; padding:4px;"
    )
    oam_warn = QLabel(tr("mech.option.oam_warn"))
    oam_warn.setWordWrap(True)
    oam_warn.setStyleSheet(
        "color:#d8a23a; font-size:10px; background:#3a2f10;"
        " border:1px solid #5e4a18; border-radius:3px; padding:4px;"
    )

    def _refresh_oam():
        n = int(get_mechanic_config(project_data, "option_satellite").get("max_options", 2) or 2)
        oam_lbl.setText(tr("mech.option.oam_estimate", n=n, oam=n))
        oam_warn.setVisible(n >= 3)  # arbitrary visual threshold; 3+ usually means HUD pressure

    lay.addWidget(oam_lbl)
    lay.addWidget(oam_warn)

    sp_max = QSpinBox()
    sp_max.setRange(1, 4)
    sp_max.setValue(int(cfg.get("max_options", 2) or 2))
    sp_max.setToolTip(tr("mech.option.max_tt"))
    sp_max.valueChanged.connect(lambda v: (_set("max_options", int(v)), _refresh_oam()))
    _row(lay, tr("mech.option.max"), sp_max)

    sp_delay = QSpinBox()
    sp_delay.setRange(0, 60)
    sp_delay.setValue(int(cfg.get("delay_frames", 12) or 12))
    sp_delay.setSuffix(" f")
    sp_delay.setToolTip(tr("mech.option.delay_tt"))
    sp_delay.valueChanged.connect(lambda v: _set("delay_frames", int(v)))
    _row(lay, tr("mech.option.delay"), sp_delay)

    sp_spacing = QSpinBox()
    sp_spacing.setRange(0, 60)
    sp_spacing.setValue(int(cfg.get("spacing_frames", 8) or 8))
    sp_spacing.setSuffix(" f")
    sp_spacing.setToolTip(tr("mech.option.spacing_tt"))
    sp_spacing.valueChanged.connect(lambda v: _set("spacing_frames", int(v)))
    _row(lay, tr("mech.option.spacing"), sp_spacing)

    sp_start = QSpinBox()
    sp_start.setRange(0, 4)
    sp_start.setValue(int(cfg.get("start_count", 0) or 0))
    sp_start.setToolTip(tr("mech.option.start_count_tt"))
    sp_start.valueChanged.connect(lambda v: _set("start_count", int(v)))
    _row(lay, tr("mech.option.start_count"), sp_start)

    cb_fire = QCheckBox(tr("mech.option.fire_sync"))
    cb_fire.setChecked(bool(cfg.get("fire_sync_with_player", True)))
    cb_fire.setToolTip(tr("mech.option.fire_sync_tt"))
    cb_fire.toggled.connect(lambda v: _set("fire_sync_with_player", bool(v)))
    lay.addWidget(cb_fire)

    cb_destr = QCheckBox(tr("mech.option.destructible"))
    cb_destr.setChecked(bool(cfg.get("destructible", False)))
    cb_destr.setToolTip(tr("mech.option.destructible_tt"))
    cb_destr.toggled.connect(lambda v: _set("destructible", bool(v)))
    lay.addWidget(cb_destr)

    cb_sprite = _sprite_type_picker(
        project_data, str(cfg.get("sprite_type", "") or ""),
        lambda _i: _set("sprite_type", cb_sprite.currentData() or ""),
    )
    cb_sprite.setToolTip(tr("mech.option.sprite_tt"))
    _row(lay, tr("mech.option.sprite"), cb_sprite)

    cb_bullet = _sprite_type_picker(
        project_data, str(cfg.get("bullet_sprite", "") or ""),
        lambda _i: _set("bullet_sprite", cb_bullet.currentData() or ""),
        empty_label="(même balle que joueur)",
    )
    cb_bullet.setToolTip(tr("mech.option.bullet_tt"))
    _row(lay, tr("mech.option.bullet"), cb_bullet)

    cb_form = QComboBox()
    cb_form.addItem(tr("mech.option.formation_trail"), "trail")
    cb_form.addItem(tr("mech.option.formation_v"), "v")
    cb_form.addItem(tr("mech.option.formation_parallel"), "parallel")
    pre = str(cfg.get("formation", "trail") or "trail")
    idx = cb_form.findData(pre)
    cb_form.setCurrentIndex(max(0, idx))
    cb_form.setToolTip(tr("mech.option.formation_tt"))
    cb_form.currentIndexChanged.connect(
        lambda _i: _set("formation", cb_form.currentData() or "trail")
    )
    _row(lay, tr("mech.option.formation"), cb_form)

    _refresh_oam()
    return w


def _build_pause_menu_config(project_data: dict, on_change) -> QWidget:
    """Inline config for the PAUSE-1 pause menu mechanic.

    Stores under ``project_data["pause_menu"]`` (top-level, not under
    ``mechanics_config``) so the codegen reader in template_integration.py
    keeps working unchanged. Schema::

        {
            "enabled": true,                    (mirror of mechanics.pause_menu)
            "items":   [
                { "label": "RESUME",  "action": "resume" },
                { "label": "TITLE",   "action": "goto_scene_reset",
                                       "target": "intro" },
                ...
            ]
        }

    The widget is a 2-column layout: list of items on the left (with add /
    remove / up / down), edit panel on the right (label / action / target).
    Selecting an item shows its edit panel; "Add" appends a new RESUME-style
    item. Max 8 items (the visible menu rows on a 152-px screen).
    """
    PRESET_ACTIONS = [
        ("resume",                "Reprendre"),
        ("goto_scene_reset",      "Aller à scène (reset)"),
        ("goto_scene_preserve",   "Aller à scène (preserve)"),
        ("save_game",             "Sauvegarder (TODO)"),
    ]

    w = QWidget()
    outer = QVBoxLayout(w)
    outer.setContentsMargins(0, 4, 0, 0)
    outer.setSpacing(6)

    # ---- Backing-store accessor (creates dict on first edit) -----------
    def _cfg() -> dict:
        cfg = project_data.get("pause_menu") if isinstance(project_data, dict) else None
        if not isinstance(cfg, dict):
            cfg = {"enabled": True, "items": []}
            if isinstance(project_data, dict):
                project_data["pause_menu"] = cfg
        cfg.setdefault("enabled", True)
        cfg.setdefault("items", [])
        if not isinstance(cfg["items"], list):
            cfg["items"] = []
        return cfg

    cfg = _cfg()

    # ---- Items list (left column) --------------------------------------
    body = QHBoxLayout()
    body.setSpacing(8)
    outer.addLayout(body)

    left = QVBoxLayout()
    left.setSpacing(4)
    left_box = QFrame()
    left_box.setLayout(left)
    left_box.setFrameShape(QFrame.Shape.StyledPanel)
    left_box.setStyleSheet(
        "QFrame { background:#252b34; border:1px solid #3a4a5e; border-radius:3px; }"
    )
    left.addWidget(QLabel("<b>Items du menu</b> (max 8)"))
    list_w = QListWidget()
    list_w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    list_w.setMinimumHeight(150)
    left.addWidget(list_w, 1)

    btn_row = QHBoxLayout()
    btn_add = QPushButton("+ Ajouter")
    btn_del = QPushButton("− Supprimer")
    btn_up  = QPushButton("↑")
    btn_dn  = QPushButton("↓")
    btn_up.setMaximumWidth(32)
    btn_dn.setMaximumWidth(32)
    for b in (btn_add, btn_del, btn_up, btn_dn):
        btn_row.addWidget(b)
    btn_row.addStretch()
    left.addLayout(btn_row)
    body.addWidget(left_box, 1)

    # ---- Item edit panel (right column) --------------------------------
    right = QVBoxLayout()
    right.setSpacing(4)
    right_box = QFrame()
    right_box.setLayout(right)
    right_box.setFrameShape(QFrame.Shape.StyledPanel)
    right_box.setStyleSheet(
        "QFrame { background:#252b34; border:1px solid #3a4a5e; border-radius:3px; }"
    )
    right.addWidget(QLabel("<b>Item sélectionné</b>"))

    le_label = QLineEdit()
    le_label.setMaxLength(12)
    le_label.setPlaceholderText("Label (12 chars max)")
    _row(right, "Label", le_label, 80)

    cb_action = QComboBox()
    for aid, alabel in PRESET_ACTIONS:
        cb_action.addItem(alabel, aid)
    _row(right, "Action", cb_action, 80)

    cb_target = QComboBox()
    cb_target.addItem("(N/A — resume ne navigue pas)", "")

    def _refresh_target_combo(current: str = "") -> None:
        cb_target.blockSignals(True)
        cb_target.clear()
        cb_target.addItem("(scène courante)", "")
        scenes = project_data.get("scenes", []) if isinstance(project_data, dict) else []
        if isinstance(scenes, list):
            for sc in scenes:
                if not isinstance(sc, dict):
                    continue
                label = str(sc.get("label") or sc.get("name") or sc.get("id") or "?")
                cb_target.addItem(label, label)
        idx = cb_target.findData(current or "")
        cb_target.setCurrentIndex(max(0, idx))
        cb_target.blockSignals(False)

    _refresh_target_combo()
    _row(right, "Scène cible", cb_target, 80)

    hint = QLabel(
        "<small><i>"
        "resume: ferme le menu, reprend la partie.<br>"
        "goto_scene_reset: full reset vers la scène cible (titre/main menu).<br>"
        "goto_scene_preserve: transition modale, scène cible doit fournir un<br>"
        "trigger return_to_caller pour revenir à la position d'origine.<br>"
        "save_game: pas encore implémenté côté runtime (S3.6)."
        "</i></small>"
    )
    hint.setWordWrap(True)
    hint.setStyleSheet("color:#8a96a4;")
    right.addWidget(hint)
    right.addStretch()
    body.addWidget(right_box, 2)

    # ---- Item state helpers --------------------------------------------
    def _items() -> list:
        return _cfg()["items"]

    def _selected_idx() -> int:
        row = list_w.currentRow()
        return row if row >= 0 else -1

    def _set_panel_enabled(enabled: bool) -> None:
        le_label.setEnabled(enabled)
        cb_action.setEnabled(enabled)
        cb_target.setEnabled(enabled)

    def _refresh_list(select: int = -1) -> None:
        list_w.blockSignals(True)
        list_w.clear()
        for i, it in enumerate(_items()):
            label = str(it.get("label", f"ITEM{i}")).strip() or f"ITEM{i}"
            act   = str(it.get("action", "resume"))
            txt   = f"{i+1}. {label}  ({act})"
            list_w.addItem(QListWidgetItem(txt))
        if select >= 0 and select < len(_items()):
            list_w.setCurrentRow(select)
        list_w.blockSignals(False)

    def _load_into_panel() -> None:
        idx = _selected_idx()
        if idx < 0 or idx >= len(_items()):
            _set_panel_enabled(False)
            le_label.setText("")
            cb_action.setCurrentIndex(0)
            cb_target.setCurrentIndex(0)
            return
        _set_panel_enabled(True)
        it = _items()[idx]
        le_label.blockSignals(True)
        cb_action.blockSignals(True)
        le_label.setText(str(it.get("label", "")))
        act_idx = cb_action.findData(str(it.get("action", "resume")))
        cb_action.setCurrentIndex(max(0, act_idx))
        le_label.blockSignals(False)
        cb_action.blockSignals(False)
        _refresh_target_combo(str(it.get("target", "")))
        # disable target combo when the selected action does not use it
        act = cb_action.currentData() or "resume"
        cb_target.setEnabled(act in ("goto_scene_reset", "goto_scene_preserve"))

    def _persist(field: str, value) -> None:
        idx = _selected_idx()
        if idx < 0 or idx >= len(_items()):
            return
        _items()[idx][field] = value
        _refresh_list(select=idx)
        on_change()

    # ---- Wire signals --------------------------------------------------
    list_w.currentRowChanged.connect(lambda _i: _load_into_panel())

    def _on_add():
        items = _items()
        if len(items) >= 8:
            return
        items.append({"label": "ITEM", "action": "resume"})
        _refresh_list(select=len(items) - 1)
        on_change()
    btn_add.clicked.connect(_on_add)

    def _on_del():
        idx = _selected_idx()
        if idx < 0:
            return
        _items().pop(idx)
        _refresh_list(select=min(idx, len(_items()) - 1))
        _load_into_panel()
        on_change()
    btn_del.clicked.connect(_on_del)

    def _on_up():
        idx = _selected_idx()
        if idx <= 0:
            return
        items = _items()
        items[idx - 1], items[idx] = items[idx], items[idx - 1]
        _refresh_list(select=idx - 1)
        on_change()
    btn_up.clicked.connect(_on_up)

    def _on_dn():
        idx = _selected_idx()
        items = _items()
        if idx < 0 or idx >= len(items) - 1:
            return
        items[idx + 1], items[idx] = items[idx], items[idx + 1]
        _refresh_list(select=idx + 1)
        on_change()
    btn_dn.clicked.connect(_on_dn)

    def _on_label_changed(text: str):
        _persist("label", text[:12])
    le_label.textEdited.connect(_on_label_changed)

    def _on_action_changed(_i: int):
        act = cb_action.currentData() or "resume"
        _persist("action", act)
        cb_target.setEnabled(act in ("goto_scene_reset", "goto_scene_preserve"))
    cb_action.currentIndexChanged.connect(_on_action_changed)

    def _on_target_changed(_i: int):
        _persist("target", cb_target.currentData() or "")
    cb_target.currentIndexChanged.connect(_on_target_changed)

    _refresh_list()
    _load_into_panel()
    return w


# Map of inline_config tag → factory(project_data, on_change_callback) → QWidget.
# Add new mechanics' inline widgets here.
INLINE_CONFIG_FACTORIES = {
    "fade_transitions":   _build_death_fade_config,
    "damage_popup":       _build_damage_popup_config,
    "highscore":          _build_highscore_config,
    "game_over_flow":     _build_game_over_flow_config,
    "option_satellite":   _build_option_satellite_config,
    "pause_menu":         _build_pause_menu_config,
}


class MechanicsTab(QWidget):
    """Top-level tab to enable/disable gameplay mechanics."""

    mechanics_changed = pyqtSignal()

    def __init__(
        self,
        project_data: dict,
        on_save: Optional[Callable[[], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._project_data = project_data
        self._on_save = on_save
        # id → (row_widget, checkbox)  — used by search filter + state sync
        self._rows: dict[str, tuple[QWidget, QCheckBox]] = {}
        # category_id → header button (clickable, holds the arrow indicator)
        self._cat_headers: dict[str, QPushButton] = {}
        # category_id → list of row widgets in that category (for bulk show/hide)
        self._cat_rows: dict[str, list[QWidget]] = {}
        # category_id → True=expanded / False=collapsed. Loaded from QSettings.
        self._cat_state: dict[str, bool] = {}
        self._search_query: str = ""
        # Persisted collapse state — survives restarts. Each category is keyed
        # under "mechanics_tab/cat_<id>" so adding a new category doesn't reset
        # the user's existing prefs.
        self._settings = QSettings("NGPCraft", "Engine")
        self._rebuild_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_project_data(self, project_data: dict) -> None:
        """Swap the backing project (e.g. after Open Project). Re-populates the
        toggles from the new data."""
        self._project_data = project_data
        self._rebuild_ui(preserve_search=True)

    def refresh_dynamic_sources(self) -> None:
        """Rebuild inline config widgets whose combos depend on project scenes
        or sprite types. Safe to call after project structure edits."""
        self._rebuild_ui(preserve_search=True)

    def _rebuild_ui(self, *, preserve_search: bool = False) -> None:
        search_text = ""
        if preserve_search and hasattr(self, "_search") and self._search is not None:
            search_text = self._search.text()

        outer = self.layout()
        if outer is not None:
            _clear_layout(outer)

        self._rows.clear()
        self._cat_headers.clear()
        self._cat_rows.clear()
        self._cat_state.clear()
        self._search_query = ""

        self._build_ui()
        self._populate_from_project()

        if preserve_search and search_text:
            self._search.setText(search_text)
        else:
            self._on_search_changed("")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = self.layout()
        if outer is None:
            outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # Header / intro
        header = QLabel(tr("mechanics.intro"))
        header.setWordWrap(True)
        header.setStyleSheet(
            "background:#2d3744; border:1px solid #4a7fb4; border-radius:4px;"
            " padding:8px; color:#d8e2f0; font-size:11px;"
        )
        outer.addWidget(header)

        # Search field — filters mechanics by name/desc/keywords on every keystroke
        search_row = QHBoxLayout()
        search_lbl = QLabel(tr("mechanics.search"))
        search_lbl.setStyleSheet("color:#9aa3ad; font-size:11px;")
        search_row.addWidget(search_lbl)
        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("mechanics.search_placeholder"))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self._search, 1)
        outer.addLayout(search_row)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(4, 4, 4, 4)
        body_layout.setSpacing(12)

        # Group by category — preserve registry order within each category
        by_category: dict[str, list[dict]] = {}
        for m in MECHANICS_REGISTRY:
            by_category.setdefault(m["category"], []).append(m)

        # Cat order: known ones first (per CATEGORY_DISPLAY_ORDER), then any
        # unknown category in registry order.
        seen_cats: set[str] = set()
        cat_order: list[str] = []
        for c in CATEGORY_DISPLAY_ORDER:
            if c in by_category:
                cat_order.append(c)
                seen_cats.add(c)
        for c in by_category:
            if c not in seen_cats:
                cat_order.append(c)

        for cat_id in cat_order:
            entries = by_category.get(cat_id) or []
            if not entries:
                continue
            # Restore saved collapse state — default expanded.
            expanded = self._settings.value(
                f"mechanics_tab/cat_{cat_id}", True, type=bool
            )
            self._cat_state[cat_id] = bool(expanded)

            cat_btn = QPushButton()
            cat_btn.setFlat(True)
            cat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            cat_btn.setStyleSheet(
                "QPushButton { color:#d8a23a; font-weight:bold; font-size:12px;"
                " text-align:left; border:none; padding:4px 0; background:transparent; }"
                "QPushButton:hover { color:#f0c060; }"
            )
            cat_btn.clicked.connect(
                lambda _checked, _cid=cat_id: self._on_cat_toggle(_cid)
            )
            body_layout.addWidget(cat_btn)
            self._cat_headers[cat_id] = cat_btn

            row_list: list[QWidget] = []
            for m in entries:
                row = self._build_mechanic_row(m)
                body_layout.addWidget(row)
                row_list.append(row)
            self._cat_rows[cat_id] = row_list

            # Apply initial state (arrow + row visibility)
            self._apply_cat_state(cat_id)

        body_layout.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

    def _build_mechanic_row(self, m: dict) -> QWidget:
        """One row per mechanic: checkbox + label + description + config paths."""
        row = QFrame()
        row.setStyleSheet(
            "QFrame { background:#1f242b; border:1px solid #2c333a;"
            " border-radius:4px; }"
        )
        lay = QVBoxLayout(row)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(5)

        # Top line: checkbox (acts as label)
        cb = QCheckBox(m["label"])
        cb.setStyleSheet("font-weight:bold; font-size:11px;")
        cb.toggled.connect(lambda checked, _mid=m["id"]: self._on_toggled(_mid, checked))
        lay.addWidget(cb)

        # Description paragraph
        lbl_desc = QLabel(m["description"])
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color:#c8d0d8; font-size:10px; margin-left:20px;")
        lay.addWidget(lbl_desc)

        # Inline config widget (project-level params configured here directly,
        # not via Scene/entity panel). Only present for mechanics that declare
        # an "inline_config" key in the registry.
        inline_tag = m.get("inline_config")
        if inline_tag and inline_tag in INLINE_CONFIG_FACTORIES:
            inline_frame = QFrame()
            inline_frame.setStyleSheet(
                "QFrame { background:#262c34; border:1px solid #3a8fbf;"
                " border-radius:3px; padding:4px; }"
            )
            inline_lay = QVBoxLayout(inline_frame)
            inline_lay.setContentsMargins(8, 6, 8, 6)
            inline_lay.setSpacing(4)
            header_lbl = QLabel(tr("mech.inline_config_header"))
            header_lbl.setStyleSheet("color:#8fb8e8; font-size:10px; font-weight:bold;")
            inline_lay.addWidget(header_lbl)
            try:
                config_widget = INLINE_CONFIG_FACTORIES[inline_tag](
                    self._project_data,
                    self._on_inline_config_changed,
                )
                inline_lay.addWidget(config_widget)
            except Exception:
                # Defensive: a buggy factory shouldn't kill the whole tab.
                err_lbl = QLabel(f"(inline config error for {inline_tag})")
                err_lbl.setStyleSheet("color:#c44; font-size:9px;")
                inline_lay.addWidget(err_lbl)
            lay.addWidget(inline_frame)

        # Config breadcrumbs — exact UI paths where to configure the mechanic
        for path_label, hint in (m.get("config_locations") or []):
            path_frame = QFrame()
            path_frame.setStyleSheet(
                "QFrame { background:#262c34; border-left:3px solid #4a7fb4;"
                " border-radius:2px; }"
            )
            path_lay = QVBoxLayout(path_frame)
            path_lay.setContentsMargins(8, 4, 8, 4)
            path_lay.setSpacing(2)
            lbl_path = QLabel(f"📍 {path_label}")
            lbl_path.setWordWrap(True)
            lbl_path.setStyleSheet(
                "color:#8fb8e8; font-size:10px; font-weight:bold;"
            )
            path_lay.addWidget(lbl_path)
            if hint:
                lbl_hint = QLabel(hint)
                lbl_hint.setWordWrap(True)
                lbl_hint.setStyleSheet("color:#9aa3ad; font-size:9px;")
                path_lay.addWidget(lbl_hint)
            lay.addWidget(path_frame)

        self._rows[m["id"]] = (row, cb)
        return row

    # ------------------------------------------------------------------
    # Category collapse / expand
    # ------------------------------------------------------------------

    def _apply_cat_state(self, cat_id: str) -> None:
        """Refresh the category header's arrow + the visibility of its rows
        based on self._cat_state[cat_id]. When a search is active, force
        expanded so the user sees matches regardless of saved state."""
        expanded = self._cat_state.get(cat_id, True)
        # During a search, force categories with matches to expand. The
        # search filter takes care of hiding non-matching rows individually.
        if self._search_query:
            display_expanded = True
        else:
            display_expanded = expanded
        arrow = "▼" if display_expanded else "▶"
        btn = self._cat_headers.get(cat_id)
        if btn is not None:
            btn.setText(f"{arrow}  {CATEGORY_LABELS.get(cat_id, cat_id)}")
        for row in self._cat_rows.get(cat_id, []):
            # Search filter still has the final word on per-row visibility — it
            # re-runs after this and may hide individual rows that don't match.
            row.setVisible(display_expanded)

    def _on_cat_toggle(self, cat_id: str) -> None:
        # When a search is active, clicking a header still flips the *saved*
        # state, but the displayed state stays forced-expanded until the
        # search is cleared. This way the user can pre-set their collapse
        # layout while filtering.
        new_state = not self._cat_state.get(cat_id, True)
        self._cat_state[cat_id] = new_state
        self._settings.setValue(f"mechanics_tab/cat_{cat_id}", new_state)
        self._apply_cat_state(cat_id)
        # Re-run search filter so per-row visibility stays consistent
        if self._search_query:
            self._on_search_changed(self._search_query)

    # ------------------------------------------------------------------
    # Search filter
    # ------------------------------------------------------------------

    def _on_search_changed(self, text: str) -> None:
        self._search_query = text or ""
        matching_ids = {m["id"] for m in search_mechanics(self._search_query)}

        # Refresh category headers first — they decide whether their rows can
        # be visible at all (collapsed → all rows hidden regardless of match).
        for cat_id in self._cat_headers:
            self._apply_cat_state(cat_id)

        for mid, (row_widget, _cb) in self._rows.items():
            # Find this row's category
            row_cat = next(
                (m["category"] for m in MECHANICS_REGISTRY if m["id"] == mid),
                None,
            )
            cat_visible = True
            if row_cat is not None:
                if self._search_query:
                    cat_visible = True  # forced-expand during search
                else:
                    cat_visible = self._cat_state.get(row_cat, True)
            row_widget.setVisible(cat_visible and (mid in matching_ids))

        # Hide a category header entirely if no row in it matches the search
        for cat_id, header in self._cat_headers.items():
            cat_has_match = any(
                m["id"] in matching_ids
                for m in MECHANICS_REGISTRY
                if m["category"] == cat_id
            )
            header.setVisible(cat_has_match)

    # ------------------------------------------------------------------
    # State sync
    # ------------------------------------------------------------------

    def _populate_from_project(self) -> None:
        """Read project["mechanics"] (with defaults for missing keys) and set
        each checkbox accordingly. Signals are blocked to avoid spurious saves."""
        state = get_mechanics(self._project_data)
        for mid, (_row, cb) in self._rows.items():
            cb.blockSignals(True)
            cb.setChecked(state.get(mid, False))
            cb.blockSignals(False)

    # Mechanic dependency map — { dependent_id: required_id }.
    # When `dependent_id` is enabled, `required_id` is auto-enabled too
    # (the dependent has no meaning without its base). When `required_id`
    # is disabled, every dependent is auto-disabled (would become orphan).
    _MECHANIC_DEPENDS_ON = {
        "wave_scroll_spawn": "wave_spawning",
    }

    def _on_toggled(self, mid: str, checked: bool) -> None:
        set_mechanic_enabled(self._project_data, mid, checked)
        # Auto-apply dependencies so orphan combos can't exist.
        propagated: list[str] = []
        if checked:
            req = self._MECHANIC_DEPENDS_ON.get(mid)
            if req and not get_mechanics(self._project_data).get(req, False):
                set_mechanic_enabled(self._project_data, req, True)
                propagated.append(req)
        else:
            for dep_id, req_id in self._MECHANIC_DEPENDS_ON.items():
                if req_id == mid and get_mechanics(self._project_data).get(dep_id, False):
                    set_mechanic_enabled(self._project_data, dep_id, False)
                    propagated.append(dep_id)
        # Sync the affected checkboxes visually so the UI reflects the new state
        # without waiting for a full reload.
        for pid in propagated:
            row = self._rows.get(pid)
            if row is not None:
                _row, cb = row
                cb.blockSignals(True)
                cb.setChecked(get_mechanics(self._project_data).get(pid, False))
                cb.blockSignals(False)
        self.mechanics_changed.emit()
        if self._on_save:
            self._on_save()

    def _on_inline_config_changed(self) -> None:
        """Called by inline config widgets when one of their params changes.
        Mutates project_data directly via set_mechanic_config_field; here we
        just persist + bubble up the change signal."""
        self.mechanics_changed.emit()
        if self._on_save:
            self._on_save()
