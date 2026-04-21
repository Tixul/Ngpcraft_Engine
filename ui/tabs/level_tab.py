"""
ui/tabs/level_tab.py — Level / Entity Placement Editor (L-1)

Lets the user place entities on a tilemap background, define timed enemy
waves, and procedurally generate layouts based on entity roles.

Data stored in .ngpcraft:
    scenes[].entities     = [{"id": str, "type": str, "x": int, "y": int, "data": int}, ...]
    scenes[].waves        = [{"delay": int, "entities": [...]}, ...]
    scenes[].sprites[].gameplay_role = "player" | "enemy" | "item" | ...
    scenes[].level_size   = {"w": 20, "h": 19}

C export (_scene.h) contains:
    - Entity type #defines (with role comments)
    - Hitbox NgpngRect for each type
    - Prop u8 constants for each type
    - Static NgpngEnt[] placement array
    - Per-wave NgpngEnt[] arrays + delay table + pointer table
"""

from __future__ import annotations

import copy
import random
import re
import uuid
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QPoint, QSize, QSettings, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QHeaderView,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from ui.no_scroll import NoScrollSpinBox as QSpinBox, NoScrollComboBox as QComboBox  # noqa: F811
from core.collision_boxes import first_hurtbox
from core.scene_collision import fit_collision_grid

from core.entity_roles import (
    entity_effective_role,
    entity_override_role,
    migrate_scene_sprite_roles,
    scene_role_map,
    set_entity_role_override,
    set_scene_sprite_role,
)
from core.entity_types import get_entity_types, new_entity_type, ET_DEFAULTS
from core.audio_manifest import load_audio_manifest, load_sfx_names
from i18n.lang import tr
from ui.context_help import ContextHelpBox

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TILE_PX       = 8        # NGPC tile size in pixels
_SCREEN_W      = 20       # tiles
_SCREEN_H      = 19       # tiles
_DEFAULT_ZOOM  = 2
_ZOOM_STEPS    = [1, 2, 3, 4, 6, 8]
_DRAG_THRESHOLD = 3
_THUMB_SRC_PX  = 128

# Camera/layout modes (metadata)
_CAM_MODES = (
    ("single_screen", "level.cam_mode.single"),
    ("follow",        "level.cam_mode.follow"),
    ("forced_scroll", "level.cam_mode.forced"),
    ("segments",      "level.cam_mode.segments"),
    ("loop",          "level.cam_mode.loop"),
)
_CAM_MODE_TO_C: dict[str, int] = {
    "single_screen": 0,
    "follow": 1,
    "forced_scroll": 2,
    "segments": 3,
    "loop": 4,
}


def _cfg_int(cfg: dict | None, key: str, default: int) -> int:
    """Read an int config value while preserving explicit zeroes."""
    if not isinstance(cfg, dict):
        return int(default)
    raw = cfg.get(key, default)
    if raw is None or raw == "":
        return int(default)
    try:
        return int(raw)
    except Exception:
        return int(default)

_LAYOUT_PRESETS: tuple[tuple[str, str, dict], ...] = (
    ("single_screen_menu", "level.layout_preset.single_screen_menu", {
        "cam_mode": "single_screen",
        "scroll_x": False,
        "scroll_y": False,
        "forced": False,
        "speed_x": 0,
        "speed_y": 0,
        "loop_x": False,
        "loop_y": False,
        "clamp": True,
        "bounds_auto": True,
        "deadzone_x": 16,
        "deadzone_y": 12,
        "drop_margin_y": 20,
    }),
    ("platformer_follow", "level.layout_preset.platformer_follow", {
        "cam_mode": "follow",
        "scroll_x": True,
        "scroll_y": True,
        "forced": False,
        "speed_x": 0,
        "speed_y": 0,
        "loop_x": False,
        "loop_y": False,
        "clamp": True,
        "bounds_auto": True,
        "deadzone_x": 16,
        "deadzone_y": 12,
        "drop_margin_y": 20,
    }),
    ("platformer_room_lock", "level.layout_preset.platformer_room_lock", {
        "cam_mode": "follow",
        "scroll_x": True,
        "scroll_y": True,
        "forced": False,
        "speed_x": 0,
        "speed_y": 0,
        "loop_x": False,
        "loop_y": False,
        "clamp": True,
        "bounds_auto": False,
        "deadzone_x": 12,
        "deadzone_y": 10,
        "drop_margin_y": 16,
    }),
    ("run_gun_horizontal", "level.layout_preset.run_gun_horizontal", {
        "cam_mode": "follow",
        "scroll_x": True,
        "scroll_y": False,
        "forced": False,
        "speed_x": 0,
        "speed_y": 0,
        "loop_x": False,
        "loop_y": False,
        "clamp": True,
        "bounds_auto": True,
        "deadzone_x": 20,
        "deadzone_y": 12,
        "drop_margin_y": 18,
    }),
    ("shmup_vertical", "level.layout_preset.shmup_vertical", {
        "cam_mode": "forced_scroll",
        "scroll_x": False,
        "scroll_y": True,
        "forced": True,
        "speed_x": 0,
        "speed_y": 1,
        "loop_x": False,
        "loop_y": True,
        "clamp": True,
        "bounds_auto": True,
        "deadzone_x": 16,
        "deadzone_y": 12,
        "drop_margin_y": 20,
    }),
    ("topdown_room", "level.layout_preset.topdown_room", {
        "cam_mode": "follow",
        "scroll_x": True,
        "scroll_y": True,
        "forced": False,
        "speed_x": 0,
        "speed_y": 0,
        "loop_x": False,
        "loop_y": False,
        "clamp": True,
        "bounds_auto": True,
        "deadzone_x": 20,
        "deadzone_y": 16,
        "drop_margin_y": 20,
    }),
)

_ENTITY_STARTER_PRESETS: dict[str, tuple[tuple[str, str], ...]] = {
    "player": (
        ("player:spawn", "level.starter_player_spawn"),
        ("player:spawn_ground", "level.starter_player_ground"),
    ),
    "enemy": (
        ("enemy:patrol_left", "level.starter_enemy_patrol_left"),
        ("enemy:patrol_right", "level.starter_enemy_patrol_right"),
        ("enemy:guard", "level.starter_enemy_guard"),
        ("enemy:chase", "level.starter_enemy_chase"),
    ),
    "item": (
        ("item:collect_1", "level.starter_item_collect_1"),
        ("item:collect_5", "level.starter_item_collect_5"),
        ("item:collect_10", "level.starter_item_collect_10"),
    ),
    "block": (
        ("block:bump", "level.starter_block_bump"),
        ("block:breakable", "level.starter_block_breakable"),
        ("block:item_once", "level.starter_block_item_once"),
    ),
    "platform": (
        ("platform:static", "level.starter_platform_static"),
        ("platform:moving", "level.starter_platform_moving"),
    ),
    "npc": (
        ("npc:idle", "level.starter_npc_idle"),
    ),
    "trigger": (
        ("trigger:marker", "level.starter_trigger_marker"),
    ),
}

_COLLISION_EDIT_MODES: tuple[tuple[str, str], ...] = (
    ("brush", "level.collision_mode_brush"),
    ("rect", "level.collision_mode_rect"),
    ("fill", "level.collision_mode_fill"),
)

# Entity roles
_ROLES = ("player", "enemy", "item", "npc", "trigger", "block", "platform", "prop")
_ROLE_COLOR: dict[str, str] = {
    "player":  "#4ec94e",
    "enemy":   "#e05050",
    "item":    "#e0c040",
    "npc":     "#50a0e0",
    "trigger": "#b060e0",
    "block": "#c07a2f",
    "platform": "#3db6c6",
    "prop":    "#909090",
}
_ROLE_SHORT: dict[str, str] = {
    "player": "PL", "enemy": "EN", "item": "IT",
    "npc": "NP", "trigger": "TR", "block": "BL", "platform": "PF", "prop": "PR",
}

_HUD_WIDGET_KINDS: tuple[tuple[str, str], ...] = (
    ("icon", "level.hud_widget_kind_icon"),
    ("value", "level.hud_widget_kind_value"),
)
_HUD_WIDGET_METRICS: tuple[tuple[str, str], ...] = (
    ("hp", "level.hud_metric_hp"),
    ("score", "level.hud_metric_score"),
    ("collect", "level.hud_metric_collect"),
    ("timer", "level.hud_metric_timer"),
    ("lives", "level.hud_metric_lives"),
    ("continues", "level.hud_metric_continues"),
    ("lap_count", "level.hud_metric_lap_count"),
)
_HUD_COLOR_PRESETS: tuple[tuple[str, str], ...] = (
    ("white", "level.hud_color_white"),
    ("green", "level.hud_color_green"),
    ("amber", "level.hud_color_amber"),
    ("cyan", "level.hud_color_cyan"),
    ("red", "level.hud_color_red"),
    ("blue", "level.hud_color_blue"),
    ("black", "level.hud_color_black"),
)
_HUD_STYLE_PRESETS: tuple[tuple[str, str], ...] = (
    ("text", "level.hud_style_text"),
    ("band", "level.hud_style_band"),
)

_TRIGGER_CONDS: tuple[tuple[str, str], ...] = (
    ("enter_region",   "level.trigger_cond.enter_region"),
    ("leave_region",   "level.trigger_cond.leave_region"),
    ("cam_x_ge",       "level.trigger_cond.cam_x_ge"),
    ("cam_y_ge",       "level.trigger_cond.cam_y_ge"),
    ("timer_ge",       "level.trigger_cond.timer_ge"),
    ("wave_ge",        "level.trigger_cond.wave_ge"),
    ("btn_a",          "level.trigger_cond.btn_a"),
    ("btn_b",          "level.trigger_cond.btn_b"),
    ("btn_a_b",        "level.trigger_cond.btn_a_b"),
    ("btn_up",         "level.trigger_cond.btn_up"),
    ("btn_down",       "level.trigger_cond.btn_down"),
    ("btn_left",       "level.trigger_cond.btn_left"),
    ("btn_right",      "level.trigger_cond.btn_right"),
    ("btn_opt",        "level.trigger_cond.btn_opt"),
    ("on_jump",        "level.trigger_cond.on_jump"),
    ("wave_cleared",   "level.trigger_cond.wave_cleared"),
    ("health_le",      "level.trigger_cond.health_le"),
    ("health_ge",      "level.trigger_cond.health_ge"),
    ("enemy_count_le", "level.trigger_cond.enemy_count_le"),
    ("lives_le",       "level.trigger_cond.lives_le"),
    ("lives_ge",       "level.trigger_cond.lives_ge"),
    ("collectible_count_ge", "level.trigger_cond.collectible_count_ge"),
    ("flag_set",     "level.trigger_cond.flag_set"),
    ("flag_clear",   "level.trigger_cond.flag_clear"),
    ("variable_ge",  "level.trigger_cond.variable_ge"),
    ("variable_eq",  "level.trigger_cond.variable_eq"),
    ("timer_every",        "level.trigger_cond.timer_every"),
    ("scene_first_enter",  "level.trigger_cond.scene_first_enter"),
    ("on_nth_jump",        "level.trigger_cond.on_nth_jump"),
    ("on_wall_left",       "level.trigger_cond.on_wall_left"),
    ("on_wall_right",      "level.trigger_cond.on_wall_right"),
    ("on_ladder",          "level.trigger_cond.on_ladder"),
    ("on_ice",             "level.trigger_cond.on_ice"),
    ("on_conveyor",        "level.trigger_cond.on_conveyor"),
    ("on_spring",          "level.trigger_cond.on_spring"),
    ("player_has_item",    "level.trigger_cond.player_has_item"),
    ("item_count_ge",      "level.trigger_cond.item_count_ge"),
    ("npc_talked_to",      "level.trigger_cond.npc_talked_to"),
    ("entity_contact",     "level.trigger_cond.entity_contact"),
    ("count_eq",           "level.trigger_cond.count_eq"),
    ("entity_alive",       "level.trigger_cond.entity_alive"),
    ("entity_dead",        "level.trigger_cond.entity_dead"),
    ("quest_stage_eq",     "level.trigger_cond.quest_stage_eq"),
    ("ability_unlocked",   "level.trigger_cond.ability_unlocked"),
    ("resource_ge",        "level.trigger_cond.resource_ge"),
    ("combo_ge",           "level.trigger_cond.combo_ge"),
    ("lap_ge",             "level.trigger_cond.lap_ge"),
    ("btn_held_ge",        "level.trigger_cond.btn_held_ge"),
    ("chance",             "level.trigger_cond.chance"),
    ("on_land",       "level.trigger_cond.on_land"),
    ("on_hurt",       "level.trigger_cond.on_hurt"),
    ("on_death",      "level.trigger_cond.on_death"),
    ("score_ge",      "level.trigger_cond.score_ge"),
    ("timer_le",      "level.trigger_cond.timer_le"),
    ("variable_le",   "level.trigger_cond.variable_le"),
    ("on_crouch",     "level.trigger_cond.on_crouch"),
    ("cutscene_done", "level.trigger_cond.cutscene_done"),
    ("enemy_count_ge",   "level.trigger_cond.enemy_count_ge"),
    ("variable_ne",      "level.trigger_cond.variable_ne"),
    ("health_eq",        "level.trigger_cond.health_eq"),
    ("on_swim",          "level.trigger_cond.on_swim"),
    ("on_dash",          "level.trigger_cond.on_dash"),
    ("on_attack",        "level.trigger_cond.on_attack"),
    ("on_pickup",        "level.trigger_cond.on_pickup"),
    ("entity_in_region", "level.trigger_cond.entity_in_region"),
    ("all_switches_on",  "level.trigger_cond.all_switches_on"),
    ("block_on_tile",    "level.trigger_cond.block_on_tile"),
    ("dialogue_done",    "level.trigger_cond.dialogue_done"),
    ("choice_result",    "level.trigger_cond.choice_result"),
    ("menu_result",      "level.trigger_cond.menu_result"),
    ("entity_type_all_dead",      "level.trigger_cond.entity_type_all_dead"),
    ("entity_type_count_ge",      "level.trigger_cond.entity_type_count_ge"),
    ("entity_type_collected",     "level.trigger_cond.entity_type_collected"),
    ("entity_type_alive_le",      "level.trigger_cond.entity_type_alive_le"),
    ("entity_type_collected_ge",  "level.trigger_cond.entity_type_collected_ge"),
    ("entity_type_all_collected", "level.trigger_cond.entity_type_all_collected"),
    ("entity_type_activated",     "level.trigger_cond.entity_type_activated"),
    ("entity_type_all_activated", "level.trigger_cond.entity_type_all_activated"),
    ("entity_type_any_alive",     "level.trigger_cond.entity_type_any_alive"),
    ("entity_type_btn_a",         "level.trigger_cond.entity_type_btn_a"),
    ("entity_type_btn_b",         "level.trigger_cond.entity_type_btn_b"),
    ("entity_type_btn_opt",       "level.trigger_cond.entity_type_btn_opt"),
    ("entity_type_contact",       "level.trigger_cond.entity_type_contact"),
    ("entity_type_near_player",   "level.trigger_cond.entity_type_near_player"),
    ("entity_type_hit",           "level.trigger_cond.entity_type_hit"),
    ("entity_type_hit_ge",        "level.trigger_cond.entity_type_hit_ge"),
    ("entity_type_spawned",       "level.trigger_cond.entity_type_spawned"),
    ("entity_type_spawned_ge",    "level.trigger_cond.entity_type_spawned_ge"),
    ("on_custom_event",           "level.trigger_cond.on_custom_event"),
)
_TRIGGER_ENTITY_TYPE_CONDS = {
    "entity_type_all_dead",    "entity_type_count_ge",
    "entity_type_collected",   "entity_type_alive_le",
    "entity_type_collected_ge","entity_type_all_collected",
    "entity_type_activated",   "entity_type_all_activated",
    "entity_type_any_alive",   "entity_type_btn_a",
    "entity_type_btn_b",       "entity_type_btn_opt",
    "entity_type_contact",     "entity_type_near_player",
    "entity_type_hit",         "entity_type_hit_ge",
    "entity_type_spawned",     "entity_type_spawned_ge",
}
_TRIGGER_REGION_CONDS = {
    "enter_region", "leave_region",
    "btn_a", "btn_b", "btn_a_b", "btn_up", "btn_down", "btn_left", "btn_right", "btn_opt",
    "entity_in_region",
    "block_on_tile",
}
_TRIGGER_VALUE_CONDS = {
    "cam_x_ge", "cam_y_ge", "timer_ge", "wave_ge", "wave_cleared", "health_le", "health_ge", "enemy_count_le", "lives_le", "lives_ge", "collectible_count_ge",
    "variable_ge", "variable_eq",
    "timer_every",
    "on_nth_jump", "player_has_item", "item_count_ge", "npc_talked_to", "entity_contact", "count_eq",
    "entity_alive", "entity_dead", "ability_unlocked", "combo_ge", "lap_ge", "btn_held_ge", "chance", "quest_stage_eq", "resource_ge",
    "score_ge", "timer_le", "variable_le", "cutscene_done",
    "enemy_count_ge", "variable_ne", "health_eq", "entity_in_region",
    "all_switches_on",
    "entity_type_count_ge", "entity_type_alive_le",
    "entity_type_collected_ge", "entity_type_hit_ge", "entity_type_spawned_ge",
}
# Conditions that use flag_var_index (0..7) rather than a region or a generic value.
_TRIGGER_FLAG_CONDS  = {"flag_set", "flag_clear", "all_switches_on"}
_TRIGGER_VAR_CONDS   = {"variable_ge", "variable_eq", "variable_le", "variable_ne",
                        "count_eq", "quest_stage_eq", "resource_ge"}
_TRIGGER_DIALOGUE_CONDS = {"dialogue_done", "choice_result"}
_TRIGGER_CHOICE_CONDS   = {"choice_result"}
_TRIGGER_MENU_CONDS     = {"menu_result"}
_TRIGGER_PRESETS: tuple[tuple[str, str], ...] = (
    ("game_checkpoint_enter", "level.trigger_preset.game_checkpoint_enter"),
    ("game_exit_next_scene", "level.trigger_preset.game_exit_next_scene"),
    ("game_door_up_next_scene", "level.trigger_preset.game_door_up_next_scene"),
    ("game_warp_next_scene", "level.trigger_preset.game_warp_next_scene"),
    ("game_respawn_on_death", "level.trigger_preset.game_respawn_on_death"),
    ("game_save_on_checkpoint", "level.trigger_preset.game_save_on_checkpoint"),
    ("combat_player_fire_a", "level.trigger_preset.combat_player_fire_a"),
    ("combat_player_attack_event", "level.trigger_preset.combat_player_attack_event"),
    ("dialog_show_on_enter", "level.trigger_preset.dialog_show_on_enter"),
    ("dialog_npc_talk_show", "level.trigger_preset.dialog_npc_talk_show"),
    ("menu_cursor_enter", "level.trigger_preset.menu_cursor_enter"),
    ("menu_open_on_enter", "level.trigger_preset.menu_open_on_enter"),
    ("menu_show_on_enter", "level.trigger_preset.menu_show_on_enter"),
    ("menu_hide_on_leave", "level.trigger_preset.menu_hide_on_leave"),
    ("menu_confirm_scene", "level.trigger_preset.menu_confirm_scene"),
    ("menu_result_scene", "level.trigger_preset.menu_result_scene"),
    ("menu_hover_sfx", "level.trigger_preset.menu_hover_sfx"),
    ("hud_hide_on_health_le", "level.trigger_preset.hud_hide_on_health_le"),
    ("hud_show_on_health_ge", "level.trigger_preset.hud_show_on_health_ge"),
    ("race_lap_gate_crossed",    "level.trigger_preset.race_lap_gate_crossed"),
    ("race_countdown_start",     "level.trigger_preset.race_countdown_start"),
    ("race_countdown_unlock",    "level.trigger_preset.race_countdown_unlock"),
    ("puzzle_block_on_target",   "level.trigger_preset.puzzle_block_on_target"),
    ("puzzle_all_switches_done", "level.trigger_preset.puzzle_all_switches_done"),
    ("puzzle_reset_on_death",    "level.trigger_preset.puzzle_reset_on_death"),
    ("puzzle_door_toggle",       "level.trigger_preset.puzzle_door_toggle"),
    ("tcg_draw_phase",           "level.trigger_preset.tcg_draw_phase"),
    ("tcg_card_to_slot",         "level.trigger_preset.tcg_card_to_slot"),
    ("tcg_turn_end",             "level.trigger_preset.tcg_turn_end"),
)
_WAVE_PRESETS: tuple[tuple[str, str], ...] = (
    ("line_3", "level.wave_preset.line_3"),
    ("vee_5", "level.wave_preset.vee_5"),
    ("ground_pair", "level.wave_preset.ground_pair"),
)
_REGION_PRESETS: tuple[tuple[str, str], ...] = (
    ("spawn_point", "level.region_preset.spawn_point"),
    ("zone_marker", "level.region_preset.zone_marker"),
    ("checkpoint", "level.region_preset.checkpoint"),
    ("camera_lock", "level.region_preset.camera_lock"),
    ("exit_goal", "level.region_preset.exit_goal"),
    ("spawn_safe", "level.region_preset.spawn_safe"),
    ("hazard_floor", "level.region_preset.hazard_floor"),
    ("lap_gate", "level.region_preset.lap_gate"),
    ("race_waypoint", "level.region_preset.race_waypoint"),
    ("push_block", "level.region_preset.push_block"),
    ("card_slot", "level.region_preset.card_slot"),
    ("attractor", "level.region_preset.attractor"),
    ("repulsor", "level.region_preset.repulsor"),
)
_TRIGGER_COND_TO_ID: dict[str, int] = {
    name: idx for idx, (name, _label) in enumerate(_TRIGGER_CONDS)
}

# Wave overlay hues (cycles per wave index)
_WAVE_HUES = [200, 40, 140, 300, 20, 180, 80, 260]

# ---------------------------------------------------------------------------
# Tile collision constants (matching ngpc_tilecol.h values)
# ---------------------------------------------------------------------------
_TCOL_PASS    = 0   # passable / empty
_TCOL_SOLID   = 1   # solid all sides
_TCOL_ONE_WAY = 2   # one-way platform (solid from top only)
_TCOL_DAMAGE  = 3   # damage zone
_TCOL_LADDER  = 4   # climbable
_TCOL_WALL_N  = 5   # top-down: wall face north  (blocks northward exit)
_TCOL_WALL_S  = 6   # top-down: wall face south
_TCOL_WALL_E  = 7   # top-down: wall face east
_TCOL_WALL_W  = 8   # top-down: wall face west
_TCOL_WATER   = 9   # special (swim / slow / hazard) - game-defined
_TCOL_FIRE    = 10  # special (damage over time) - game-defined
_TCOL_VOID    = 11  # special (pit / kill / out-of-bounds) - game-defined
_TCOL_DOOR    = 12  # special (transition / trigger) - game-defined
_TCOL_STAIR_E = 13  # platformer slope: low on west, high on east
_TCOL_STAIR_W = 14  # platformer slope: low on east, high on west
_TCOL_SPRING      = 15  # launch / rebound tile
_TCOL_ICE         = 16  # slippery floor (no deceleration while sliding)
_TCOL_CONVEYOR_L  = 17  # conveyor belt pushing left
_TCOL_CONVEYOR_R  = 18  # conveyor belt pushing right
_TCOL_CORNER_NE   = 19  # wall corner open to North + East  (inner NE angle)
_TCOL_CORNER_NW   = 20  # wall corner open to North + West  (inner NW angle)
_TCOL_CORNER_SE   = 21  # wall corner open to South + East  (inner SE angle)
_TCOL_CORNER_SW   = 22  # wall corner open to South + West  (inner SW angle)

_ENT_FLAG_CLAMP_MAP = 1
_ENT_FLAG_ALLOW_LEDGE_FALL = 2
_ENT_FLAG_RESPAWN = 4
_ENT_FLAG_CLAMP_CAMERA = 8

# Canvas overlay colors per collision type
_TCOL_OVERLAY: dict[int, "QColor"] = {}   # filled after QColor is importable
_TCOL_NAMES: dict[int, str] = {
    _TCOL_PASS:    "PASS",
    _TCOL_SOLID:   "SOLID",
    _TCOL_ONE_WAY: "ONE_WAY",
    _TCOL_DAMAGE:  "DAMAGE",
    _TCOL_LADDER:  "LADDER",
    _TCOL_WALL_N:  "WALL_N",
    _TCOL_WALL_S:  "WALL_S",
    _TCOL_WALL_E:  "WALL_E",
    _TCOL_WALL_W:  "WALL_W",
    _TCOL_WATER:   "WATER",
    _TCOL_FIRE:    "FIRE",
    _TCOL_VOID:    "VOID",
    _TCOL_DOOR:    "DOOR",
    _TCOL_STAIR_E: "STAIR_E",
    _TCOL_STAIR_W: "STAIR_W",
    _TCOL_SPRING:     "SPRING",
    _TCOL_ICE:        "ICE",
    _TCOL_CONVEYOR_L: "CONVEYOR_L",
    _TCOL_CONVEYOR_R: "CONVEYOR_R",
}

# Tile role definitions per map mode
# Each entry: (role_key, tcol_constant, i18n_label_key)
_MAP_MODE_ROLES: dict[str, list[tuple[str, int, str]]] = {
    "platformer": [
        ("empty",    _TCOL_PASS,    "level.tile_role.platformer.empty"),
        ("floor",    _TCOL_SOLID,   "level.tile_role.platformer.floor"),
        ("platform", _TCOL_ONE_WAY, "level.tile_role.platformer.platform"),
        ("damage",   _TCOL_DAMAGE,  "level.tile_role.platformer.damage"),
        ("ladder",   _TCOL_LADDER,  "level.tile_role.platformer.ladder"),
        ("stair_e",  _TCOL_STAIR_E, "level.tile_role.platformer.stair_e"),
        ("stair_w",  _TCOL_STAIR_W, "level.tile_role.platformer.stair_w"),
        ("spring",      _TCOL_SPRING,      "level.tile_role.platformer.spring"),
        ("ice",         _TCOL_ICE,         "level.tile_role.platformer.ice"),
        ("conveyor_l",  _TCOL_CONVEYOR_L,  "level.tile_role.platformer.conveyor_l"),
        ("conveyor_r",  _TCOL_CONVEYOR_R,  "level.tile_role.platformer.conveyor_r"),
        ("water",    _TCOL_WATER,   "level.tile_role.platformer.water"),
        ("fire",     _TCOL_FIRE,    "level.tile_role.platformer.fire"),
        ("void",     _TCOL_VOID,    "level.tile_role.platformer.void"),
        ("door",     _TCOL_DOOR,    "level.tile_role.platformer.door"),
    ],
    "topdown": [
        ("empty",    _TCOL_PASS,    "level.tile_role.topdown.empty"),
        ("solid",    _TCOL_SOLID,   "level.tile_role.topdown.solid"),
        ("wall_n",   _TCOL_WALL_N,  "level.tile_role.topdown.wall_n"),
        ("wall_s",   _TCOL_WALL_S,  "level.tile_role.topdown.wall_s"),
        ("wall_e",   _TCOL_WALL_E,  "level.tile_role.topdown.wall_e"),
        ("wall_w",   _TCOL_WALL_W,    "level.tile_role.topdown.wall_w"),
        ("corner_ne",_TCOL_CORNER_NE,"level.tile_role.topdown.corner_ne"),
        ("corner_nw",_TCOL_CORNER_NW,"level.tile_role.topdown.corner_nw"),
        ("corner_se",_TCOL_CORNER_SE,"level.tile_role.topdown.corner_se"),
        ("corner_sw",_TCOL_CORNER_SW,"level.tile_role.topdown.corner_sw"),
        ("damage",   _TCOL_DAMAGE,  "level.tile_role.topdown.damage"),
        ("water",    _TCOL_WATER,   "level.tile_role.topdown.water"),
        ("fire",     _TCOL_FIRE,    "level.tile_role.topdown.fire"),
        ("void",     _TCOL_VOID,    "level.tile_role.topdown.void"),
        ("door",     _TCOL_DOOR,    "level.tile_role.topdown.door"),
    ],
    "shmup": [
        ("empty",    _TCOL_PASS,    "level.tile_role.shmup.empty"),
        ("solid",    _TCOL_SOLID,   "level.tile_role.shmup.solid"),
        ("damage",   _TCOL_DAMAGE,  "level.tile_role.shmup.damage"),
        ("fire",     _TCOL_FIRE,    "level.tile_role.shmup.fire"),
        ("void",     _TCOL_VOID,    "level.tile_role.shmup.void"),
    ],
    "open": [
        ("empty",    _TCOL_PASS,    "level.tile_role.open.empty"),
        ("solid",    _TCOL_SOLID,   "level.tile_role.open.solid"),
        ("damage",   _TCOL_DAMAGE,  "level.tile_role.open.damage"),
        ("water",    _TCOL_WATER,   "level.tile_role.open.water"),
        ("fire",     _TCOL_FIRE,    "level.tile_role.open.fire"),
        ("void",     _TCOL_VOID,    "level.tile_role.open.void"),
        ("door",     _TCOL_DOOR,    "level.tile_role.open.door"),
    ],
    # Puzzle: single-screen grid — floor, wall, pressure_plate (trigger sensor),
    # ice_floor (slippery, blocks slide), void_pit (reset/kill), door (togglable).
    # Reuses existing tcols: pressure_plate=DAMAGE, ice_floor=ICE, void_pit=VOID, door=DOOR.
    "puzzle": [
        ("floor",           _TCOL_PASS,   "level.tile_role.puzzle.floor"),
        ("wall",            _TCOL_SOLID,  "level.tile_role.puzzle.wall"),
        ("pressure_plate",  _TCOL_DAMAGE, "level.tile_role.puzzle.pressure_plate"),
        ("ice_floor",       _TCOL_ICE,    "level.tile_role.puzzle.ice_floor"),
        ("void_pit",        _TCOL_VOID,   "level.tile_role.puzzle.void_pit"),
        ("door",            _TCOL_DOOR,   "level.tile_role.puzzle.door"),
    ],
    # Race: topdown circuit — track surface, wall, boost strip, gravel (slow),
    # off-track void. Boost reuses CONVEYOR_R tcol; gravel reuses ICE tcol.
    "race": [
        ("track",        _TCOL_PASS,       "level.tile_role.race.track"),
        ("wall",         _TCOL_SOLID,      "level.tile_role.race.wall"),
        ("boost",        _TCOL_CONVEYOR_R, "level.tile_role.race.boost"),
        ("gravel",       _TCOL_ICE,        "level.tile_role.race.gravel"),
        ("void",         _TCOL_VOID,       "level.tile_role.race.void"),
    ],
}

_MAP_MODES = [
    ("none",        "level.map_mode.none"),
    ("platformer",  "level.map_mode.platformer"),
    ("topdown",     "level.map_mode.topdown"),
    ("shmup",       "level.map_mode.shmup"),
    ("open",        "level.map_mode.open"),
    ("race",        "level.map_mode.race"),
    ("puzzle",      "level.map_mode.puzzle"),
]
_MAP_MODE_TO_C: dict[str, int] = {
    "none": 0,
    "platformer": 1,
    "topdown": 2,
    "shmup": 3,
    "open": 4,
    "race": 5,
    "puzzle": 6,
}

_LEVEL_PROFILES: list[tuple[str, str]] = [
    ("none", "level.profile.none"),
    ("fighting", "level.profile.fighting"),
    ("platformer", "level.profile.platformer"),
    ("run_gun", "level.profile.run_gun"),
    ("shmup", "level.profile.shmup"),
    ("brawler", "level.profile.brawler"),
    ("topdown_rpg", "level.profile.topdown_rpg"),
    ("tactical", "level.profile.tactical"),
    ("tcg", "level.profile.tcg"),
    ("puzzle", "level.profile.puzzle"),
    ("menu", "level.profile.menu"),
    ("visual_novel", "level.profile.visual_novel"),
    ("rhythm", "level.profile.rhythm"),
    ("race", "level.profile.race"),
    ("roguelite_room", "level.profile.roguelite_room"),
]
_PROFILE_TO_C: dict[str, int] = {
    name: idx for idx, (name, _label) in enumerate(_LEVEL_PROFILES)
}

# ---------------------------------------------------------------------------
# Genre-aware priority sorting (Option A)
# ---------------------------------------------------------------------------
# For each genre, lists the trigger condition/action/region_kind/preset keys
# that should appear FIRST in their respective combos, separated from the rest
# by a visual divider.  Items not listed remain in their original order below.
# ---------------------------------------------------------------------------

_GENRE_PRIORITY_TRIGGER_CONDS: dict[str, list[str]] = {
    "platformer":  ["enter_region", "on_land", "on_wall_left", "on_wall_right", "health_le", "on_ladder", "on_spring"],
    "run_gun":     ["enter_region", "on_land", "health_le", "enemy_count_le", "wave_cleared"],
    "shmup":       ["wave_ge", "wave_cleared", "enemy_count_le", "cam_y_ge", "cam_x_ge", "health_le"],
    "brawler":     ["enter_region", "health_le", "combo_ge", "enemy_count_le", "btn_a"],
    "fighting":    ["health_le", "health_eq", "combo_ge", "timer_le", "btn_a", "btn_b"],
    "topdown_rpg": ["enter_region", "flag_set", "flag_clear", "npc_talked_to", "entity_contact", "dialogue_done", "choice_result", "menu_result", "player_has_item", "quest_stage_eq"],
    "tactical":    ["enter_region", "entity_alive", "entity_dead", "count_eq", "variable_ge"],
    "tcg":         ["entity_in_region", "count_eq", "variable_ge", "variable_eq", "flag_set", "scene_first_enter"],
    "puzzle":      ["all_switches_on", "block_on_tile", "count_eq", "flag_set", "enter_region", "variable_ge", "on_death"],
    "menu":        ["btn_a", "btn_b", "btn_up", "btn_down", "btn_left", "btn_right", "flag_set", "flag_clear", "scene_first_enter"],
    "visual_novel":["scene_first_enter", "flag_set", "dialogue_done", "choice_result", "menu_result", "quest_stage_eq", "btn_a"],
    "rhythm":      ["timer_ge", "timer_every", "btn_a", "btn_b", "combo_ge", "score_ge"],
    "race":        ["lap_ge", "enter_region", "timer_ge", "timer_le", "btn_a", "btn_held_ge"],
    "roguelite_room": ["enter_region", "entity_type_all_dead", "entity_type_count_ge", "flag_set", "flag_clear", "variable_ge", "variable_eq", "health_le", "enemy_count_le", "scene_first_enter"],
}

_GENRE_PRIORITY_TRIGGER_ACTS: dict[str, list[str]] = {
    "platformer":  ["set_checkpoint", "respawn_player", "play_sfx", "add_health", "set_gravity_dir", "goto_scene"],
    "run_gun":     ["fire_player_shot", "spawn_wave", "play_sfx", "add_health", "goto_scene"],
    "shmup":       ["spawn_wave", "spawn_entity", "play_sfx", "add_score", "screen_shake", "goto_scene"],
    "brawler":     ["add_health", "add_score", "screen_shake", "spawn_entity", "play_sfx", "goto_scene"],
    "fighting":    ["add_health", "set_health", "add_combo", "reset_combo", "set_timer", "end_game"],
    "topdown_rpg": ["show_dialogue", "open_menu", "set_npc_dialogue", "give_item", "set_flag", "set_quest_stage", "unlock_door", "goto_scene", "warp_to"],
    "tactical":    ["spawn_entity", "destroy_entity", "set_flag", "set_variable", "end_game"],
    "tcg":         ["spawn_entity", "destroy_entity", "move_entity_to", "emit_event", "set_variable", "inc_variable", "show_dialogue"],
    "puzzle":      ["toggle_tile", "reset_scene", "move_entity_to", "set_flag", "show_dialogue", "play_sfx", "goto_scene"],
    "menu":        ["show_entity", "hide_entity", "move_entity_to", "set_flag", "clear_flag", "toggle_flag", "goto_scene", "play_sfx", "emit_event"],
    "visual_novel":["show_dialogue", "open_menu", "set_npc_dialogue", "set_flag", "set_quest_stage", "fade_out", "fade_in", "goto_scene"],
    "rhythm":      ["add_score", "add_combo", "reset_combo", "play_sfx", "flash_screen", "end_game"],
    "race":        ["emit_event", "add_score", "set_timer", "save_game", "goto_scene", "play_sfx", "screen_shake"],
    "roguelite_room": ["spawn_entity", "enable_trigger", "give_item", "add_score", "inc_variable", "set_flag", "set_variable", "play_sfx", "save_game", "fade_out", "goto_scene"],
}

_GENRE_PRIORITY_REGION_KINDS: dict[str, list[str]] = {
    "platformer":  ["checkpoint", "spawn", "exit_goal", "danger_zone", "camera_lock"],
    "run_gun":     ["spawn", "exit_goal", "danger_zone", "camera_lock"],
    "shmup":       ["spawn", "danger_zone", "no_spawn"],
    "brawler":     ["spawn", "danger_zone", "exit_goal", "camera_lock"],
    "fighting":    ["spawn", "camera_lock"],
    "topdown_rpg": ["spawn", "exit_goal", "checkpoint", "zone", "no_spawn"],
    "tactical":    ["spawn", "zone", "no_spawn", "exit_goal"],
    "tcg":         ["card_slot", "zone", "spawn", "no_spawn"],
    "puzzle":      ["push_block", "zone", "checkpoint", "spawn", "exit_goal"],
    "menu":        ["zone", "spawn"],
    "visual_novel":["zone", "spawn"],
    "rhythm":      ["zone", "spawn", "danger_zone"],
    "race":        ["lap_gate", "race_waypoint", "spawn", "checkpoint", "no_spawn"],
    "roguelite_room": ["spawn", "exit_goal", "checkpoint", "zone", "no_spawn"],
}

_GENRE_PRIORITY_TRIGGER_PRESETS: dict[str, list[str]] = {
    "platformer":  ["game_checkpoint_enter", "game_respawn_on_death", "game_save_on_checkpoint", "game_exit_next_scene", "game_door_up_next_scene", "combat_player_fire_a"],
    "run_gun":     ["combat_player_fire_a", "game_respawn_on_death", "game_save_on_checkpoint", "game_exit_next_scene"],
    "shmup":       ["combat_player_fire_a", "combat_player_attack_event"],
    "brawler":     ["combat_player_attack_event", "game_exit_next_scene"],
    "fighting":    ["combat_player_attack_event", "hud_hide_on_health_le", "hud_show_on_health_ge"],
    "topdown_rpg": ["dialog_show_on_enter", "dialog_npc_talk_show", "menu_open_on_enter", "menu_result_scene", "game_save_on_checkpoint", "game_warp_next_scene"],
    "tactical":    ["menu_cursor_enter", "menu_confirm_scene"],
    "tcg":         ["tcg_draw_phase", "tcg_card_to_slot", "tcg_turn_end", "menu_confirm_scene"],
    "puzzle":      ["puzzle_block_on_target", "puzzle_all_switches_done", "puzzle_reset_on_death", "puzzle_door_toggle", "game_checkpoint_enter"],
    "menu":        ["menu_open_on_enter", "menu_result_scene", "menu_cursor_enter", "menu_confirm_scene", "menu_hover_sfx"],
    "visual_novel":["dialog_show_on_enter", "menu_open_on_enter", "menu_result_scene", "menu_show_on_enter", "menu_hide_on_leave"],
    "rhythm":      ["combat_player_fire_a", "hud_hide_on_health_le"],
    "race":        ["race_countdown_start", "race_countdown_unlock", "race_lap_gate_crossed", "game_save_on_checkpoint", "game_exit_next_scene"],
    "roguelite_room": ["game_respawn_on_death", "game_save_on_checkpoint", "game_exit_next_scene", "game_checkpoint_enter"],
}

_GENRE_PRIORITY_REGION_PRESETS: dict[str, list[str]] = {
    "platformer":  ["checkpoint", "spawn_point", "exit_goal", "camera_lock", "spawn_safe", "hazard_floor", "zone_marker"],
    "run_gun":     ["spawn_point", "exit_goal", "spawn_safe", "hazard_floor"],
    "shmup":       ["spawn_point", "spawn_safe", "hazard_floor"],
    "brawler":     ["spawn_point", "spawn_safe", "exit_goal", "hazard_floor", "zone_marker"],
    "fighting":    ["spawn_point", "camera_lock", "zone_marker"],
    "topdown_rpg": ["spawn_point", "zone_marker", "checkpoint", "exit_goal", "camera_lock", "spawn_safe"],
    "tactical":    ["spawn_point", "zone_marker", "exit_goal", "spawn_safe"],
    "tcg":         ["card_slot", "spawn_point", "zone_marker", "spawn_safe"],
    "puzzle":      ["push_block", "zone_marker", "spawn_point", "checkpoint", "exit_goal", "spawn_safe"],
    "menu":        ["zone_marker", "spawn_point", "spawn_safe"],
    "visual_novel":["zone_marker", "spawn_point", "spawn_safe"],
    "rhythm":      ["zone_marker", "spawn_point", "hazard_floor"],
    "race":        ["lap_gate", "race_waypoint", "spawn_point", "checkpoint", "exit_goal", "spawn_safe"],
    "roguelite_room": ["spawn_point", "exit_goal", "checkpoint", "zone_marker", "spawn_safe"],
}


def _reorder_combo_for_genre(combo, genre: str, priority_dict: dict[str, list[str]]) -> None:
    """Reorder a QComboBox so that genre-priority items appear first, then a
    separator, then everything else — preserving the current selection.

    Items with userData==None (separator items) are discarded and recreated.
    This function is safe to call even when genre has no entry in priority_dict
    (falls through to no-op reorder, i.e., just separator=0 priority items,
    which means no separator is inserted and order stays unchanged).
    """
    priority_keys: list[str] = priority_dict.get(genre, [])
    if not priority_keys:
        return  # nothing to reorder for this genre

    # Collect all (key, text) pairs currently in the combo (skip separators)
    all_items: list[tuple[str, str]] = []
    for i in range(combo.count()):
        d = combo.itemData(i)
        if d is not None:
            all_items.append((str(d), combo.itemText(i)))

    priority_set = set(priority_keys)
    # Build ordered priority list preserving the requested order
    key_to_text = dict(all_items)
    top: list[tuple[str, str]] = [(k, key_to_text[k]) for k in priority_keys if k in key_to_text]
    rest: list[tuple[str, str]] = [(k, t) for k, t in all_items if k not in priority_set]

    if not top:
        return  # none of the priority keys exist in this combo

    # Save current selection
    saved_data = combo.currentData()

    combo.blockSignals(True)
    try:
        combo.clear()
        for k, t in top:
            combo.addItem(t, k)
        if rest:
            combo.insertSeparator(combo.count())
            for k, t in rest:
                combo.addItem(t, k)
        # Restore selection
        if saved_data is not None:
            idx = combo.findData(saved_data)
            if idx >= 0:
                combo.setCurrentIndex(idx)
    finally:
        combo.blockSignals(False)


_PROFILE_PRESETS: dict[str, dict] = {
    # Minimal “starter defaults”; users can freely override afterwards.
    "fighting":     {"map_mode": "none",       "scroll_x": True,  "scroll_y": False, "forced": False, "loop_x": False, "loop_y": False, "gw": 32, "gh": 19},
    "platformer":   {"map_mode": "platformer", "scroll_x": True,  "scroll_y": True,  "forced": False, "loop_x": False, "loop_y": False},
    "run_gun":      {"map_mode": "platformer", "scroll_x": True,  "scroll_y": False, "forced": False, "loop_x": False, "loop_y": False},
    "shmup":        {"map_mode": "shmup",      "scroll_x": False, "scroll_y": True,  "forced": True,  "loop_x": False, "loop_y": True, "speed_x": 0, "speed_y": 1},
    "brawler":      {"map_mode": "none",       "scroll_x": True,  "scroll_y": True,  "forced": False, "loop_x": False, "loop_y": False},
    "topdown_rpg":  {"map_mode": "topdown",    "scroll_x": True,  "scroll_y": True,  "forced": False, "loop_x": False, "loop_y": False},
    "tactical":     {"map_mode": "topdown",    "scroll_x": True,  "scroll_y": True,  "forced": False, "loop_x": False, "loop_y": False},
    "tcg":          {"map_mode": "none",       "scroll_x": False, "scroll_y": False, "forced": False, "loop_x": False, "loop_y": False, "gw": 20, "gh": 19},
    "puzzle":       {"map_mode": "none",       "scroll_x": False, "scroll_y": False, "forced": False, "loop_x": False, "loop_y": False, "gw": 20, "gh": 19},
    "menu":         {"map_mode": "none",       "scroll_x": False, "scroll_y": False, "forced": False, "loop_x": False, "loop_y": False, "gw": 20, "gh": 19},
    "visual_novel": {"map_mode": "none",       "scroll_x": False, "scroll_y": False, "forced": False, "loop_x": False, "loop_y": False, "gw": 20, "gh": 19},
    "rhythm":       {"map_mode": "none",       "scroll_x": False, "scroll_y": True,  "forced": True,  "loop_x": False, "loop_y": True, "speed_x": 0, "speed_y": 1, "gw": 20, "gh": 19},
    "race":          {"map_mode": "race",    "scroll_x": True,  "scroll_y": True,  "forced": False, "loop_x": True,  "loop_y": True},
    "roguelite_room": {"map_mode": "topdown", "scroll_x": False, "scroll_y": False, "forced": False, "loop_x": False, "loop_y": False, "gw": 20, "gh": 19},
}

_TILE_SRC_CHOICES: list[tuple[str, str]] = [
    ("auto", "level.procgen_tile_src.auto"),
    ("scr1", "level.procgen_tile_src.scr1"),
    ("scr2", "level.procgen_tile_src.scr2"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_id() -> str:
    return uuid.uuid4().hex[:10]

def _init_tcol_overlays() -> None:
    """Populate _TCOL_OVERLAY once QColor is available."""
    _TCOL_OVERLAY.update({
        _TCOL_SOLID:   QColor(200, 60,  60,  80),
        _TCOL_ONE_WAY: QColor(60,  200, 120, 60),
        _TCOL_DAMAGE:  QColor(220, 140, 40,  70),
        _TCOL_LADDER:  QColor(120, 100, 220, 60),
        _TCOL_WALL_N:  QColor(200, 60,  200, 70),
        _TCOL_WALL_S:  QColor(200, 120, 60,  70),
        _TCOL_WALL_E:  QColor(60,  200, 200, 70),
        _TCOL_WALL_W:  QColor(60,  60,  200, 70),
        _TCOL_WATER:   QColor(40,  140, 220, 70),
        _TCOL_FIRE:    QColor(255, 80,  30,  80),
        _TCOL_VOID:    QColor(10,  10,  10,  90),
        _TCOL_DOOR:    QColor(240, 200, 60,  70),
        _TCOL_STAIR_E: QColor(120, 210, 120, 80),
        _TCOL_STAIR_W: QColor(80,  190, 170, 80),
        _TCOL_SPRING:      QColor(255, 64,  180, 90),
        _TCOL_ICE:         QColor(160, 220, 255, 80),
        _TCOL_CONVEYOR_L:  QColor(255, 180, 40,  80),
        _TCOL_CONVEYOR_R:  QColor(255, 140, 60,  80),
    })


def _type_to_c_const(name: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").upper()
    return f"ENT_{clean}" if clean else "ENT_UNKNOWN"


def _safe_c_id(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()


def _pil_to_qpixmap(img) -> QPixmap:
    rgba = img.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimg = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


def _load_bg_pixmap(path: Path) -> Optional[QPixmap]:
    try:
        pm = QPixmap(str(path))
        return pm if not pm.isNull() else None
    except Exception:
        return None


def _resolve_bg_plane_variant(path: Path, plane: str) -> Path:
    """
    Try to use the same-named exported SCR1/SCR2 PNG when available.

    Examples:
      bg.png        + plane=scr1 -> bg_scr1.png (if exists)
      bg_scr1.png   + plane=scr2 -> bg_scr2.png (if exists)
    """
    try:
        plane = str(plane).lower().strip()
    except Exception:
        plane = "scr1"
    if plane not in ("scr1", "scr2"):
        plane = "scr1"

    stem_l = path.stem.lower()
    if stem_l.endswith("_scr1") or stem_l.endswith("_scr2"):
        base = path.stem[:-5]
        cand = path.with_name(f"{base}_{plane}{path.suffix}")
        return cand if cand.exists() else path

    cand = path.with_name(f"{path.stem}_{plane}{path.suffix}")
    return cand if cand.exists() else path


def _wave_color(wi: int, alpha: int = 200) -> QColor:
    h = _WAVE_HUES[wi % len(_WAVE_HUES)]
    return QColor.fromHsv(h, 200, 230, alpha)


def _entity_color(type_name: str) -> QColor:
    h = abs(hash(type_name)) % 360
    return QColor.fromHsv(h, 180, 220, 200)

def _path_color(path_id: str, alpha: int = 220) -> QColor:
    h = abs(hash(path_id)) % 360
    return QColor.fromHsv(h, 210, 235, alpha)


def _path_point_to_px(pt: object) -> tuple[int, int]:
    """Return a path point as scene pixel coordinates.

    Backward compatibility:
    - new format: {"px": int, "py": int}
    - legacy format: {"x": tile_x, "y": tile_y}
    """
    if isinstance(pt, dict):
        if "px" in pt or "py" in pt:
            return int(pt.get("px", pt.get("x", 0)) or 0), int(pt.get("py", pt.get("y", 0)) or 0)
        return int(pt.get("x", 0) or 0) * _TILE_PX, int(pt.get("y", 0) or 0) * _TILE_PX
    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
        return int(pt[0]) * _TILE_PX, int(pt[1]) * _TILE_PX
    return 0, 0


def _path_point_make(px: int, py: int) -> dict[str, int]:
    return {"px": int(px), "py": int(py)}


def _path_point_label(index: int, pt: object) -> str:
    px, py = _path_point_to_px(pt)
    return f"{index}: ({px},{py}) px"


def _tile_id_variants(value: object, default: int) -> list[int]:
    out: list[int] = []
    if isinstance(value, int):
        out = [int(value)]
    elif isinstance(value, str):
        parts = re.split(r"[^0-9]+", value)
        out = [int(p) for p in parts if p != ""]
    elif isinstance(value, (list, tuple)):
        for item in value:
            try:
                out.append(int(item))
            except Exception:
                pass
    if not out:
        out = [int(default)]
    seen: set[int] = set()
    norm: list[int] = []
    for v in out:
        v = max(0, int(v))
        if v in seen:
            continue
        seen.add(v)
        norm.append(v)
    return norm or [int(default)]


def _tile_id_storage(value: object, default: int) -> int | list[int]:
    ids = _tile_id_variants(value, default)
    return ids[0] if len(ids) == 1 else ids


def _tile_id_text(value: object, default: int) -> str:
    return ",".join(str(v) for v in _tile_id_variants(value, default))


def _tile_id_pick(value: object, *, default: int, x: int = 0, y: int = 0, salt: int = 0) -> int:
    ids = _tile_id_variants(value, default)
    if len(ids) == 1:
        return ids[0]
    idx = (int(x) * 131 + int(y) * 17 + int(salt) * 73 + len(ids) * 11) % len(ids)
    return ids[idx]


def _tile_role_tt_key(tcol: int) -> str:
    return {
        _TCOL_PASS: "level.tcol.pass_tt",
        _TCOL_SOLID: "level.tcol.solid_tt",
        _TCOL_ONE_WAY: "level.tcol.one_way_tt",
        _TCOL_DAMAGE: "level.tcol.damage_tt",
        _TCOL_LADDER: "level.tcol.ladder_tt",
        _TCOL_WALL_N: "level.tcol.wall_n_tt",
        _TCOL_WALL_S: "level.tcol.wall_s_tt",
        _TCOL_WALL_E: "level.tcol.wall_e_tt",
        _TCOL_WALL_W: "level.tcol.wall_w_tt",
        _TCOL_WATER: "level.tcol.water_tt",
        _TCOL_FIRE: "level.tcol.fire_tt",
        _TCOL_VOID: "level.tcol.void_tt",
        _TCOL_DOOR: "level.tcol.door_tt",
        _TCOL_STAIR_E: "level.tcol.stair_e_tt",
        _TCOL_STAIR_W: "level.tcol.stair_w_tt",
        _TCOL_SPRING: "level.tcol.spring_tt",
    }.get(int(tcol), "level.tcol.pass_tt")


# ---------------------------------------------------------------------------
# Level canvas
# ---------------------------------------------------------------------------

class _LevelCanvas(QWidget):
    """Interactive entity placement canvas."""

    entity_selected = pyqtSignal(int)
    entity_placed   = pyqtSignal()
    coord_changed   = pyqtSignal(int, int)  # tile_x, tile_y  (-1,-1 = left canvas)

    def __init__(self, tab: "LevelTab", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tab = tab
        self._drag_kind: str = "none"  # "static" | "wave" | "none"
        self._drag_wave_sel: int = -1
        self._drag_idx: int = -1
        self._drag_start_mouse: QPoint | None = None
        self._is_dragging: bool = False
        self._drag_tile_off: tuple[int, int] = (0, 0)
        self._drag_collision_value: int = _TCOL_PASS
        self._collision_rect_start: tuple[int, int] | None = None
        self._collision_rect_preview: tuple[int, int, int, int] | None = None
        self._drag_cam: bool = False
        self._hover_pos: QPoint | None = None  # last known mouse position for hover effects

        # Regions editing
        self._drag_region: bool = False
        self._drag_region_idx: int = -1
        self._drag_region_off: tuple[int, int] = (0, 0)
        self._drag_region_start_mouse: QPoint | None = None
        self._drag_region_pushed: bool = False
        self._region_draw_start: tuple[int, int] | None = None
        self._region_preview: tuple[int, int, int, int] | None = None  # x,y,w,h in tiles

        # Paths editing
        self._drag_path: bool = False
        self._drag_path_idx: int = -1
        self._drag_point_idx: int = -1
        self._drag_path_start_mouse: QPoint | None = None
        self._drag_path_pushed: bool = False

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def _tile_px(self) -> int:
        return _TILE_PX * self._tab._zoom

    def sizeHint(self) -> QSize:
        tp = self._tile_px()
        return QSize(self._tab._grid_w * tp, self._tab._grid_h * tp)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _mouse_to_tile(self, pos: QPoint) -> tuple[int, int]:
        tp = self._tile_px()
        return (
            max(0, min(self._tab._grid_w - 1, pos.x() // tp)),
            max(0, min(self._tab._grid_h - 1, pos.y() // tp)),
        )

    def _mouse_to_scene_px(self, pos: QPoint) -> tuple[int, int]:
        zoom = max(1, int(self._tab._zoom))
        max_x = max(0, int(self._tab._grid_w * _TILE_PX) - 1)
        max_y = max(0, int(self._tab._grid_h * _TILE_PX) - 1)
        return (
            max(0, min(max_x, int(pos.x()) // zoom)),
            max(0, min(max_y, int(pos.y()) // zoom)),
        )

    def _entity_at_tile(self, tx: int, ty: int) -> int:
        for i in range(len(self._tab._entities) - 1, -1, -1):
            ent = self._tab._entities[i]
            ex, ey, ew, eh = self._entity_bounds(ent)
            if ex <= tx < (ex + ew) and ey <= ty < (ey + eh):
                return i
        return -1

    def _wave_entity_at_tile(self, tx: int, ty: int, wave_ents: list) -> int:
        for i in range(len(wave_ents) - 1, -1, -1):
            ent = wave_ents[i]
            ex, ey, ew, eh = self._entity_bounds(ent)
            if ex <= tx < (ex + ew) and ey <= ty < (ey + eh):
                return i
        return -1

    def _text_label_at_tile(self, tx: int, ty: int) -> int:
        """Return index of text label at tile (tx, ty), else -1."""
        lbls = getattr(self._tab, "_text_labels", []) or []
        for i in range(len(lbls) - 1, -1, -1):
            lbl = lbls[i]
            if not isinstance(lbl, dict):
                continue
            if int(lbl.get("x", 0)) == tx and int(lbl.get("y", 0)) == ty:
                return i
        return -1

    def _entity_bounds(self, ent: dict) -> tuple[int, int, int, int]:
        x = int(ent.get("x", 0))
        y = int(ent.get("y", 0))
        w_px, h_px = self._tab._type_sizes.get(str(ent.get("type", "")), (_TILE_PX, _TILE_PX))
        w_tiles = max(1, (int(w_px) + _TILE_PX - 1) // _TILE_PX)
        h_tiles = max(1, (int(h_px) + _TILE_PX - 1) // _TILE_PX)
        return x, y, w_tiles, h_tiles

    def _clamp_entity_origin(self, tx: int, ty: int, *, type_name: str | None) -> tuple[int, int]:
        w_px, h_px = self._tab._type_sizes.get(str(type_name or ""), (_TILE_PX, _TILE_PX))
        w_tiles = max(1, (int(w_px) + _TILE_PX - 1) // _TILE_PX)
        h_tiles = max(1, (int(h_px) + _TILE_PX - 1) // _TILE_PX)
        tx = max(0, min(int(self._tab._grid_w - w_tiles), int(tx)))
        ty = max(0, min(int(self._tab._grid_h - h_tiles), int(ty)))
        return int(tx), int(ty)

    def _apply_rules_xy(self, tx: int, ty: int, *, type_name: str | None, in_wave: bool) -> tuple[int, int]:
        rules = getattr(self._tab, "_level_rules", {}) or {}
        if not isinstance(rules, dict):
            return tx, ty
        if in_wave and not bool(rules.get("apply_to_waves", True)):
            return tx, ty

        if bool(rules.get("lock_y_en", False)):
            try:
                ty = int(rules.get("lock_y", ty))
            except Exception:
                pass

        if bool(rules.get("ground_band_en", False)):
            try:
                gmin = int(rules.get("ground_min_y", 0))
                gmax = int(rules.get("ground_max_y", self._tab._grid_h - 1))
                if gmin > gmax:
                    gmax = gmin
                ty = max(gmin, min(gmax, ty))
            except Exception:
                pass

        tx = max(0, min(self._tab._grid_w - 1, int(tx)))
        ty = max(0, min(self._tab._grid_h - 1, int(ty)))
        return tx, ty

    def _mirror_x(self, tx: int, *, type_name: str | None) -> int:
        rules = getattr(self._tab, "_level_rules", {}) or {}
        if not isinstance(rules, dict) or not bool(rules.get("mirror_en", False)):
            return tx
        try:
            axis = int(rules.get("mirror_axis_x", (self._tab._grid_w - 1) // 2))
        except Exception:
            axis = (self._tab._grid_w - 1) // 2
        axis = max(0, min(int(self._tab._grid_w - 1), axis))
        w_px, _h_px = self._tab._type_sizes.get(str(type_name or ""), (_TILE_PX, _TILE_PX))
        w_tiles = max(1, (int(w_px) + _TILE_PX - 1) // _TILE_PX)
        mx = axis * 2 - int(tx) - (w_tiles - 1)
        mx = max(0, min(int(self._tab._grid_w - w_tiles), int(mx)))
        return int(mx)

    def _point_hit(self, px: int, py: int, pts: list[dict], tp: int) -> int:
        """Return point index hit at pixel coords (px/py), else -1."""
        if not pts:
            return -1
        rad = max(6, tp // 4)
        best = -1
        best_d2 = rad * rad
        for i, pt in enumerate(pts):
            pt_px, pt_py = _path_point_to_px(pt)
            x = pt_px * self._tab._zoom
            y = pt_py * self._tab._zoom
            dx = x - px
            dy = y - py
            d2 = dx * dx + dy * dy
            if d2 <= best_d2:
                best = i
                best_d2 = d2
        return best

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        p = QPainter(self)
        tp  = self._tile_px()
        gw  = self._tab._grid_w
        gh  = self._tab._grid_h
        in_wave = self._tab._wave_edit

        # Background -------------------------------------------------------
        bg1 = getattr(self._tab, "_bg_pixmap_scr1", None)
        bg2 = getattr(self._tab, "_bg_pixmap_scr2", None)
        bg_front = getattr(self._tab, "_bg_front", "scr1")
        if bg1 is not None or bg2 is not None:
            order: list[tuple[str, QPixmap | None]] = [("scr1", bg1), ("scr2", bg2)]
            if bg_front == "scr2":
                order = [("scr1", bg1), ("scr2", bg2)]
            else:
                order = [("scr2", bg2), ("scr1", bg1)]

            for plane, pm_src in order:
                if pm_src is None:
                    continue
                loop_x = bool(getattr(self._tab, "_scroll_cfg", {}).get("loop_x", False))
                loop_y = bool(getattr(self._tab, "_scroll_cfg", {}).get("loop_y", False))
                # Keep the tilemap at its real pixel size (scaled only by the editor zoom),
                # never stretch it to the full scene grid size.
                pm = pm_src.scaled(
                    pm_src.width() * self._tab._zoom,
                    pm_src.height() * self._tab._zoom,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
                # Optional loop preview: tile the BG image to fill the scene.
                if loop_x or loop_y:
                    w_px = gw * tp
                    h_px = gh * tp
                    if loop_x and loop_y:
                        p.drawTiledPixmap(0, 0, w_px, h_px, pm)
                    elif loop_x:
                        step = max(1, pm.width())
                        for x in range(0, w_px, step):
                            p.drawPixmap(x, 0, pm)
                    else:  # loop_y
                        step = max(1, pm.height())
                        for y in range(0, h_px, step):
                            p.drawPixmap(0, y, pm)
                else:
                    p.drawPixmap(0, 0, pm)
                # Dim per layer so combined view stays readable.
                alpha = 110 if plane != bg_front else 70
                p.fillRect(0, 0, gw * tp, gh * tp, QColor(0, 0, 0, alpha))
        else:
            for cy in range(gh):
                for cx in range(gw):
                    col = QColor(38, 38, 42) if (cx + cy) % 2 == 0 else QColor(45, 45, 50)
                    p.fillRect(cx * tp, cy * tp, tp, tp, col)


        # Tilemap collision ghost overlay (read-only background layer) ------
        tm_cache = getattr(self._tab, "_col_map_tilemap_cache", None)
        if tm_cache is not None and self._tab._show_col_map:
            for cy in range(min(gh, len(tm_cache))):
                row = tm_cache[cy]
                for cx in range(min(gw, len(row))):
                    tcol = row[cx]
                    if tcol in _TCOL_OVERLAY:
                        base_c = _TCOL_OVERLAY[tcol]
                        ghost = QColor(base_c.red(), base_c.green(), base_c.blue(), 55)
                        p.fillRect(cx * tp, cy * tp, tp, tp, ghost)

        # Collision map overlay (manual / imported — full opacity) ----------
        col_map = self._tab._col_map
        if col_map is not None and self._tab._show_col_map:
            for cy in range(min(gh, len(col_map))):
                row = col_map[cy]
                for cx in range(min(gw, len(row))):
                    tcol = row[cx]
                    if tcol in _TCOL_OVERLAY:
                        p.fillRect(cx * tp, cy * tp, tp, tp, _TCOL_OVERLAY[tcol])
                        # Directional wall: draw a thick edge on the relevant side
                        if tcol in (_TCOL_WALL_N, _TCOL_WALL_S, _TCOL_WALL_E, _TCOL_WALL_W):
                            edge_pen = QPen(_TCOL_OVERLAY[tcol].darker(120))
                            edge_pen.setWidth(max(2, tp // 4))
                            p.setPen(edge_pen)
                            if tcol == _TCOL_WALL_N:
                                p.drawLine(cx*tp, cy*tp, (cx+1)*tp, cy*tp)
                            elif tcol == _TCOL_WALL_S:
                                p.drawLine(cx*tp, (cy+1)*tp, (cx+1)*tp, (cy+1)*tp)
                            elif tcol == _TCOL_WALL_E:
                                p.drawLine((cx+1)*tp, cy*tp, (cx+1)*tp, (cy+1)*tp)
                            elif tcol == _TCOL_WALL_W:
                                p.drawLine(cx*tp, cy*tp, cx*tp, (cy+1)*tp)
                        # Stair slope: diagonal showing ramp direction
                        elif tcol in (_TCOL_STAIR_E, _TCOL_STAIR_W):
                            stair_pen = QPen(_TCOL_OVERLAY[tcol].darker(160))
                            stair_pen.setWidth(max(2, tp // 4))
                            p.setPen(stair_pen)
                            if tcol == _TCOL_STAIR_E:
                                # Low west → high east: bottom-left to top-right
                                p.drawLine(cx*tp, (cy+1)*tp - 1, (cx+1)*tp - 1, cy*tp)
                            else:
                                # Low east → high west: bottom-right to top-left
                                p.drawLine((cx+1)*tp - 1, (cy+1)*tp - 1, cx*tp, cy*tp)

        if self._collision_rect_preview is not None:
            x, y, w, h = self._collision_rect_preview
            preview_col = _TCOL_OVERLAY.get(int(self._drag_collision_value), QColor(255, 255, 255, 70))
            p.fillRect(x * tp, y * tp, w * tp, h * tp, QColor(preview_col.red(), preview_col.green(), preview_col.blue(), 48))
            pen = QPen(QColor(255, 255, 255, 220))
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setWidth(2)
            p.setPen(pen)
            p.drawRect(x * tp, y * tp, w * tp - 1, h * tp - 1)

        # Grid lines -------------------------------------------------------
        grid_pen = QPen(QColor(80, 80, 90, 120))
        grid_pen.setWidth(1)
        p.setPen(grid_pen)
        for x in range(gw + 1):
            p.drawLine(x * tp, 0, x * tp, gh * tp)
        for y in range(gh + 1):
            p.drawLine(0, y * tp, gw * tp, y * tp)

        show_regions = bool(getattr(self._tab, "_show_regions", True) or getattr(self._tab, "_region_edit", False))
        show_triggers = bool(getattr(self._tab, "_show_triggers", True))
        show_paths = bool(getattr(self._tab, "_show_paths", True) or getattr(self._tab, "_path_edit", False))
        show_waves = bool(getattr(self._tab, "_show_waves", True) or getattr(self._tab, "_wave_edit", False))

        # Regions overlay --------------------------------------------------
        regs = getattr(self._tab, "_regions", []) or []
        if regs and show_regions:
            selr = int(getattr(self._tab, "_region_selected", -1))
            reg_by_id = {str(r.get("id", "") or ""): r for r in regs if isinstance(r, dict)}
            for i, r in enumerate(regs):
                x = int(r.get("x", 0))
                y = int(r.get("y", 0))
                w = max(1, int(r.get("w", 1)))
                h = max(1, int(r.get("h", 1)))
                kind = str(r.get("kind", "zone") or "zone")
                nm = str(r.get("name", "") or "region")
                if kind == "zone":
                    col = QColor(140, 100, 220, 46)
                    border_col = QColor(180, 140, 255, 220)
                elif kind == "danger_zone":
                    col = QColor(220, 40, 40, 60)
                    border_col = QColor(255, 60, 60, 220)
                elif kind == "checkpoint":
                    col = QColor(40, 180, 120, 56)
                    border_col = QColor(80, 230, 160, 220)
                elif kind == "camera_lock":
                    col = QColor(70, 160, 220, 52)
                    border_col = QColor(120, 210, 255, 220)
                elif kind == "exit_goal":
                    col = QColor(240, 200, 60, 52)
                    border_col = QColor(255, 220, 110, 220)
                elif kind == "spawn":
                    col = QColor(60, 200, 240, 52)
                    border_col = QColor(100, 230, 255, 220)
                else:  # no_spawn
                    col = QColor(240, 120, 40, 46)
                    border_col = QColor(255, 160, 80, 220)
                p.fillRect(x * tp, y * tp, w * tp, h * tp, col)
                pen = QPen(border_col)
                pen.setWidth(3 if i == selr else 2)
                p.setPen(pen)
                p.drawRect(x * tp, y * tp, w * tp - 1, h * tp - 1)
                p.setPen(QPen(QColor(255, 255, 255, 220)))
                p.drawText(x * tp + 4, y * tp + 14, nm)

            # Trigger badges (region-based triggers)
            if show_triggers:
                trigs = getattr(self._tab, "_triggers", []) or []
                for t in trigs:
                    if not isinstance(t, dict):
                        continue
                    cond = str(t.get("cond", "enter_region") or "enter_region")
                    if cond not in ("enter_region", "leave_region"):
                        continue
                    rid = str(t.get("region_id", "") or "")
                    if not rid or rid not in reg_by_id:
                        continue
                    r = reg_by_id[rid]
                    x = int(r.get("x", 0))
                    y = int(r.get("y", 0))
                    w = max(1, int(r.get("w", 1)))
                    ev = int(t.get("event", 0) or 0)
                    txt = f"T{ev}"
                    bc = QColor(240, 200, 60, 210) if cond == "enter_region" else QColor(200, 120, 240, 210)
                    bw = max(tp, len(txt) * 6 + 4)
                    bh = tp // 2 + 3
                    bx = x * tp + w * tp - bw
                    by = y * tp
                    p.fillRect(bx, by, bw, bh, bc)
                    p.setPen(QColor(0, 0, 0, 220))
                    p.drawText(bx + 2, by + bh - 2, txt)

        # move_entity_to destination marker (crosshair + dashed arrow)
        _sel_trig_idx = int(getattr(self._tab, "_trigger_selected", -1))
        if _sel_trig_idx >= 0:
            _trigs = getattr(self._tab, "_triggers", []) or []
            if 0 <= _sel_trig_idx < len(_trigs):
                _st = _trigs[_sel_trig_idx]
                if str(_st.get("action", "")) in ("move_entity_to", "teleport_player", "spawn_at_region"):
                    _dtx = int(_st.get("dest_tile_x", -1) or -1)
                    _dty = int(_st.get("dest_tile_y", -1) or -1)
                    if _dtx >= 0 and _dty >= 0:
                        _cx = _dtx * tp + tp // 2
                        _cy = _dty * tp + tp // 2
                        _arm = max(4, tp // 2)
                        # Crosshair
                        _xpen = QPen(QColor(255, 80, 80, 240))
                        _xpen.setWidth(2)
                        p.setPen(_xpen)
                        p.drawLine(_cx - _arm, _cy, _cx + _arm, _cy)
                        p.drawLine(_cx, _cy - _arm, _cx, _cy + _arm)
                        p.drawRect(_dtx * tp + 1, _dty * tp + 1, tp - 2, tp - 2)
                        # Dashed arrow from entity spawn to destination
                        _ent_tid = str(_st.get("entity_target_id", "") or "")
                        if _ent_tid:
                            _ents = getattr(self._tab, "_entities", []) or []
                            _ent = next((e for e in _ents if str(e.get("id", "") or "") == _ent_tid), None)
                            if _ent is not None:
                                _ex = int(_ent.get("x", 0)) * tp + tp // 2
                                _ey = int(_ent.get("y", 0)) * tp + tp // 2
                                _apen = QPen(QColor(255, 160, 80, 180))
                                _apen.setWidth(1)
                                _apen.setStyle(Qt.PenStyle.DashLine)
                                p.setPen(_apen)
                                p.drawLine(_ex, _ey, _cx, _cy)
        # Pick-dest mode: highlight tile under cursor
        if getattr(self._tab, "_pick_dest_mode", False) and self._hover_pos is not None:
            _hx = int(self._hover_pos.x()) // tp
            _hy = int(self._hover_pos.y()) // tp
            _pick_pen = QPen(QColor(80, 200, 255, 220))
            _pick_pen.setWidth(2)
            _pick_pen.setStyle(Qt.PenStyle.DotLine)
            p.setPen(_pick_pen)
            p.drawRect(_hx * tp, _hy * tp, tp - 1, tp - 1)

        if getattr(self._tab, "_region_edit", False) and self._region_preview is not None:
            x, y, w, h = self._region_preview
            pen = QPen(QColor(255, 255, 255, 220))
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setWidth(2)
            p.setPen(pen)
            p.drawRect(x * tp, y * tp, w * tp - 1, h * tp - 1)

        # Text labels overlay ----------------------------------------------
        lbls = getattr(self._tab, "_text_labels", []) or []
        if lbls:
            sell = int(getattr(self._tab, "_text_label_selected", -1))
            lbl_font = QFont("Courier", max(6, tp - 2))
            lbl_font.setFixedPitch(True)
            p.setFont(lbl_font)
            for li, lbl in enumerate(lbls):
                if not isinstance(lbl, dict):
                    continue
                lx = int(lbl.get("x", 0))
                ly = int(lbl.get("y", 0))
                txt = str(lbl.get("text") or "")
                if not txt:
                    txt = "(empty)"
                bx = lx * tp
                by = ly * tp
                bw = max(tp, len(txt) * max(5, tp - 2) + 4)
                bh = tp
                p.fillRect(bx, by, bw, bh, QColor(0, 0, 0, 160))
                if li == sell:
                    lbl_pen = QPen(QColor(255, 220, 80, 240))
                    lbl_pen.setWidth(2)
                    p.setPen(lbl_pen)
                    p.drawRect(bx, by, bw - 1, bh - 1)
                p.setPen(QColor(200, 255, 200, 230))
                p.drawText(bx + 2, by + bh - 2, txt)

        # Camera start preview (20×19 tiles) ------------------------------
        if getattr(self._tab, "_show_cam", True):
            cx, cy = getattr(self._tab, "_cam_tile", (0, 0))
            cpx, cpy = int(cx) * tp, int(cy) * tp
            cpw, cph = _SCREEN_W * tp, _SCREEN_H * tp
            p.fillRect(cpx, cpy, cpw, cph, QColor(80, 170, 255, 12))
            cam_pen = QPen(QColor(80, 170, 255, 210))
            cam_pen.setWidth(2)
            p.setPen(cam_pen)
            p.drawRect(cpx, cpy, cpw - 1, cph - 1)
            p.setPen(QPen(QColor(80, 170, 255, 220)))
            p.drawText(cpx + 4, cpy + 14, "CAM")
            # Deadzone overlay (follow mode only) — shows the zone where camera doesn't move
            layout_cfg = getattr(self._tab, "_layout_cfg", {}) or {}
            if str(layout_cfg.get("cam_mode", "") or "") == "follow":
                dz_x = _cfg_int(layout_cfg, "follow_deadzone_x", 16)
                dz_y = _cfg_int(layout_cfg, "follow_deadzone_y", 12)
                # Convert NGPC pixels → canvas pixels (tp = 8 NGPC px scaled by zoom)
                scale = max(1, tp // 8)
                dz_cw = dz_x * 2 * scale
                dz_ch = dz_y * 2 * scale
                dz_rx = cpx + (cpw - dz_cw) // 2
                dz_ry = cpy + (cph - dz_ch) // 2
                p.fillRect(dz_rx, dz_ry, dz_cw, dz_ch, QColor(255, 220, 60, 18))
                dz_pen = QPen(QColor(255, 220, 60, 200))
                dz_pen.setStyle(Qt.PenStyle.DashLine)
                dz_pen.setWidth(1)
                p.setPen(dz_pen)
                p.drawRect(dz_rx, dz_ry, dz_cw - 1, dz_ch - 1)
                p.setPen(QPen(QColor(255, 220, 60, 200)))
                p.drawText(dz_rx + 3, dz_ry + 12, "DZ")

        # Paths overlay ---------------------------------------------------
        paths = getattr(self._tab, "_paths", []) or []
        if paths and show_paths:
            selp = int(getattr(self._tab, "_path_selected", -1))
            selpt = int(getattr(self._tab, "_path_point_selected", -1))
            show_indices = bool(getattr(self._tab, "_path_edit", False))
            for pi, path in enumerate(paths):
                if not isinstance(path, dict):
                    continue
                pts = path.get("points", []) or []
                if not isinstance(pts, list) or len(pts) < 1:
                    continue
                pid = str(path.get("id", "") or f"path_{pi}")
                col = _path_color(pid, alpha=210 if pi == selp else 140)
                pen = QPen(col)
                pen.setWidth(3 if pi == selp else 2)
                p.setPen(pen)

                prev = None
                for pt in pts:
                    pt_px, pt_py = _path_point_to_px(pt)
                    x = pt_px * self._tab._zoom
                    y = pt_py * self._tab._zoom
                    if prev is not None:
                        p.drawLine(prev[0], prev[1], x, y)
                    prev = (x, y)

                if bool(path.get("loop", False)) and len(pts) >= 2:
                    a = pts[0]
                    b = pts[-1]
                    ax_px, ay_px = _path_point_to_px(a)
                    bx_px, by_px = _path_point_to_px(b)
                    ax = ax_px * self._tab._zoom
                    ay = ay_px * self._tab._zoom
                    bx = bx_px * self._tab._zoom
                    by = by_px * self._tab._zoom
                    p.drawLine(bx, by, ax, ay)

                for pti, pt in enumerate(pts):
                    pt_px, pt_py = _path_point_to_px(pt)
                    x = pt_px * self._tab._zoom
                    y = pt_py * self._tab._zoom
                    is_sel = (pi == selp) and (pti == selpt)
                    r = max(3, tp // 6) + (2 if is_sel else 0)
                    p.setBrush(QColor(255, 255, 255, 220) if is_sel else QColor(0, 0, 0, 0))
                    p.setPen(QPen(QColor(255, 255, 255, 240) if is_sel else col))
                    p.drawEllipse(QPoint(x, y), r, r)
                    if show_indices and (pi == selp):
                        p.setPen(QPen(QColor(255, 255, 255, 200)))
                        p.drawText(x + 4, y - 4, str(pti))

        # Static entities --------------------------------------------------
        static_opacity = 0.35 if in_wave else 1.0
        sel = self._tab._selected
        for i, ent in enumerate(self._tab._entities):
            self._draw_entity(p, tp, ent,
                              selected=(i == sel),
                              opacity=static_opacity,
                              badge=None)

        # Wave overlays ----------------------------------------------------
        if show_waves:
            for wi, wave in enumerate(self._tab._waves):
                is_cur = in_wave and (wi == self._tab._wave_selected)
                wave_ents = wave.get("entities", [])
                # In wave-edit mode show only the current wave; otherwise show all dimmed
                if in_wave and not is_cur:
                    continue
                opacity = 0.9 if is_cur else 0.5
                wc = _wave_color(wi)
                for j, ent in enumerate(wave_ents):
                    sel_in_wave = is_cur and (j == self._tab._wave_entity_sel)
                    self._draw_entity(p, tp, ent,
                                      selected=sel_in_wave,
                                      opacity=opacity,
                                      badge=f"W{wi}",
                                      badge_color=wc)

        # Bezel ------------------------------------------------------------
        if self._tab._show_bezel:
            bx, by = self._tab._bezel_tile
            bpx, bpy = bx * tp, by * tp
            bpw, bph = _SCREEN_W * tp, _SCREEN_H * tp
            p.fillRect(bpx, bpy, bpw, bph, QColor(255, 220, 0, 14))
            bezel_pen = QPen(QColor(255, 200, 0, 210))
            bezel_pen.setWidth(2)
            p.setPen(bezel_pen)
            p.drawRect(bpx, bpy, bpw - 1, bph - 1)
            p.setPen(QPen(QColor(255, 200, 0, 200)))
            p.drawText(bpx + 4, bpy + 14, "NGPC 160×152 (20×19 tiles)")

        p.end()

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        try:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                dy = int(event.angleDelta().y())
                if dy == 0:
                    event.ignore()
                    return
                steps = list(_ZOOM_STEPS)
                cur = int(getattr(self._tab, "_zoom", _DEFAULT_ZOOM))
                idx = steps.index(cur) if cur in steps else 0
                idx = min(len(steps) - 1, idx + 1) if dy > 0 else max(0, idx - 1)
                self._tab._set_zoom(int(steps[idx]))
                event.accept()
                return
        except Exception:
            pass
        event.ignore()

    def _draw_entity(self, p: QPainter, tp: int, ent: dict,
                     selected: bool, opacity: float,
                     badge: Optional[str],
                     badge_color: QColor | None = None) -> None:
        if "x" not in ent or "y" not in ent or "type" not in ent:
            return
        tx, ty = ent["x"], ent["y"]
        x_px, y_px = tx * tp, ty * tp

        w_px, h_px = self._tab._type_sizes.get(ent["type"], (_TILE_PX, _TILE_PX))
        w_tiles = max(1, (w_px + _TILE_PX - 1) // _TILE_PX)
        h_tiles = max(1, (h_px + _TILE_PX - 1) // _TILE_PX)
        draw_w, draw_h = w_tiles * tp, h_tiles * tp

        pm = self._tab._type_pixmaps.get(ent["type"])
        p.setOpacity(opacity)
        if pm is not None:
            scaled = pm.scaled(draw_w, draw_h,
                               Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(x_px, y_px, scaled)
        else:
            p.fillRect(x_px + 1, y_px + 1, draw_w - 2, draw_h - 2,
                       _entity_color(ent["type"]))
        p.setOpacity(1.0)

        # Outline / selection ring
        if selected:
            ring = QPen(QColor(255, 220, 0, 240))
            ring.setWidth(2)
            p.setPen(ring)
        else:
            ring = QPen(QColor(0, 0, 0, 100))
            ring.setWidth(1)
            p.setPen(ring)
        p.drawRect(x_px, y_px, draw_w - 1, draw_h - 1)

        # Wave badge (top-left)
        if badge is not None:
            bc = badge_color or QColor(180, 180, 180, 200)
            bw = max(tp, len(badge) * 5 + 4)
            bh = tp // 2 + 3
            p.fillRect(x_px, y_px, bw, bh, bc)
            p.setPen(QColor(255, 255, 255, 240))
            p.drawText(x_px + 2, y_px + bh - 2, badge)
        else:
            # Role badge (top-right corner of sprite) for static entities.
            # Use the effective role so a per-entity override is reflected in the canvas
            # (e.g. type=trigger with override=enemy shows "E", not "T").
            role = self._tab._entity_effective_role(ent)
            if role and role != "prop":
                short = _ROLE_SHORT.get(role, "??")
                rc = QColor(_ROLE_COLOR.get(role, "#888888"))
                rc.setAlpha(180)
                bw = max(tp, len(short) * 5 + 4)
                bh = tp // 2 + 3
                rx = x_px + draw_w - bw
                p.fillRect(rx, y_px, bw, bh, rc)
                p.setPen(QColor(255, 255, 255, 230))
                p.drawText(rx + 2, y_px + bh - 2, short)

        # Anchor / origin marker — centre du sprite = position world (x*8, y*8)
        # Indique où actor.x/actor.y = 0 se trouve en runtime (avant offset hitbox)
        ax = x_px + draw_w // 2
        ay = y_px + draw_h // 2
        arm = max(2, tp // 3)
        p.setPen(QPen(QColor(0, 0, 0, 90), 2))
        p.drawLine(ax - arm, ay, ax + arm, ay)
        p.drawLine(ax, ay - arm, ax, ay + arm)
        p.setPen(QPen(QColor(255, 255, 255, 160), 1))
        p.drawLine(ax - arm + 1, ay, ax + arm - 1, ay)
        p.drawLine(ax, ay - arm + 1, ax, ay + arm - 1)

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        in_wave = self._tab._wave_edit
        wsel    = self._tab._wave_selected
        tool    = str(getattr(self._tab, "_scene_tool", "entity") or "entity")

        if event.button() == Qt.MouseButton.LeftButton:
            # Trigger dest-tile pick mode: record tile and exit
            if getattr(self._tab, "_pick_dest_mode", False):
                tp = self._tile_px()
                tx = int(event.pos().x()) // tp
                ty = int(event.pos().y()) // tp
                self._tab._on_dest_tile_picked(tx, ty)
                self.update()
                return
            # Path edit mode overrides entity/region placement
            if getattr(self._tab, "_path_edit", False):
                tp = self._tile_px()
                px, py = int(event.pos().x()), int(event.pos().y())
                pidx = int(getattr(self._tab, "_path_selected", -1))
                if not (0 <= pidx < len(self._tab._paths)):
                    self._tab._add_path()
                    pidx = int(getattr(self._tab, "_path_selected", -1))
                if 0 <= pidx < len(self._tab._paths):
                    path = self._tab._paths[pidx]
                    pts = path.get("points", []) or []
                    hit = self._point_hit(px, py, pts, tp)
                    if hit >= 0:
                        self._tab._path_point_selected = hit
                        self._tab._refresh_path_points()
                        self._drag_path = True
                        self._drag_path_idx = pidx
                        self._drag_point_idx = hit
                        self._drag_path_start_mouse = event.pos()
                        self._drag_path_pushed = False
                        self.update()
                        return
                    px_world, py_world = self._mouse_to_scene_px(event.pos())
                    self._tab._push_undo()
                    pts.append(_path_point_make(px_world, py_world))
                    path["points"] = pts
                    self._tab._path_point_selected = len(pts) - 1
                    self._tab._refresh_path_points()
                    self.update()
                return

            # Region edit mode overrides entity placement
            if getattr(self._tab, "_region_edit", False):
                tx, ty = self._mouse_to_tile(event.pos())
                hit = self._tab._region_at_tile(tx, ty)
                if hit >= 0:
                    self._tab._region_selected = hit
                    self._tab._refresh_region_props()
                    self._drag_region = True
                    self._drag_region_idx = hit
                    self._drag_region_start_mouse = event.pos()
                    self._drag_region_pushed = False
                    rx = int(self._tab._regions[hit].get("x", 0))
                    ry = int(self._tab._regions[hit].get("y", 0))
                    self._drag_region_off = (tx - rx, ty - ry)
                    self.update()
                    return
                # Start drawing a new region
                self._region_draw_start = (tx, ty)
                self._region_preview = (tx, ty, 1, 1)
                self._tab._region_selected = -1
                self._tab._refresh_region_props()
                self.update()
                return

            # Camera tool (or Ctrl+drag override) moves camera start directly.
            if tool == "camera" or (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                tx, ty = self._mouse_to_tile(event.pos())
                self._tab._set_cam_tile(tx, ty)
                self._drag_cam = True
                self._drag_start_mouse = event.pos()
                self._is_dragging = True
                self.update()
                return

            if tool == "collision":
                tx, ty = self._mouse_to_tile(event.pos())
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    self._tab._pick_collision_brush(tx, ty)
                    self.update()
                    return
                edit_mode = self._tab._current_collision_edit_mode()
                paint_value = int(self._tab._current_collision_brush())
                if edit_mode == "fill":
                    if self._tab._fill_collision_region(tx, ty, paint_value):
                        self.entity_placed.emit()
                    self.update()
                    return
                if edit_mode == "rect":
                    self._drag_kind = "collision"
                    self._drag_idx = -1
                    self._drag_wave_sel = -1
                    self._drag_start_mouse = event.pos()
                    self._drag_collision_value = paint_value
                    self._collision_rect_start = (tx, ty)
                    self._collision_rect_preview = (tx, ty, 1, 1)
                    self._is_dragging = False
                    self.update()
                    return
                self._drag_kind = "collision"
                self._drag_idx = -1
                self._drag_wave_sel = -1
                self._drag_start_mouse = event.pos()
                self._drag_collision_value = paint_value
                self._is_dragging = False
                cur = self._tab._collision_value_at(tx, ty)
                if cur is not None and cur != int(self._drag_collision_value):
                    self._tab._push_undo()
                    self._is_dragging = True
                if self._tab._paint_collision_tile(tx, ty, self._drag_collision_value, push_undo=False):
                    self.entity_placed.emit()
                self.update()
                return

            pos = event.pos()
            tx, ty = self._mouse_to_tile(pos)

            if in_wave and 0 <= wsel < len(self._tab._waves):
                # ---- Wave placement mode ----
                wave_ents = self._tab._waves[wsel]["entities"]
                hit = self._wave_entity_at_tile(tx, ty, wave_ents)
                if hit >= 0:
                    self._tab._wave_entity_sel = hit
                    self._tab._refresh_wave_entity_props()
                    self._drag_kind = "wave"
                    self._drag_wave_sel = int(wsel)
                    self._drag_idx = hit
                    ent = wave_ents[hit]
                    self._drag_tile_off = (tx - int(ent.get("x", 0)), ty - int(ent.get("y", 0)))
                    self._drag_start_mouse = pos
                    self._is_dragging = False
                else:
                    type_name = self._tab._current_type()
                    if type_name:
                        tx, ty = self._apply_rules_xy(tx, ty, type_name=type_name, in_wave=True)
                        tx, ty = self._clamp_entity_origin(tx, ty, type_name=type_name)
                        self._tab._push_undo()
                        wave_ents.append({"type": type_name, "x": tx, "y": ty, "data": 0})
                        # Optional mirror placement
                        if (bool(getattr(self._tab, "_level_rules", {}).get("mirror_en", False))
                                and bool(getattr(self._tab, "_level_rules", {}).get("apply_to_waves", True))):
                            mx = self._mirror_x(tx, type_name=type_name)
                            if mx != tx and self._wave_entity_at_tile(mx, ty, wave_ents) < 0:
                                wave_ents.append({"type": type_name, "x": mx, "y": ty, "data": 0})
                        self._tab._wave_entity_sel = len(wave_ents) - 1
                        self._tab._refresh_wave_list()
                        self._tab._refresh_wave_entity_props()
                        self.entity_placed.emit()
                        self._drag_kind = "wave"
                        self._drag_wave_sel = int(wsel)
                        self._drag_idx = self._tab._wave_entity_sel
                        self._drag_start_mouse = pos
                        self._is_dragging = False
                    else:
                        self._tab._wave_entity_sel = -1
                        self._drag_kind = "none"
            else:
                # ---- Text label hit-test (click to select) ----
                lbl_hit = self._text_label_at_tile(tx, ty)
                if lbl_hit >= 0:
                    self._tab._text_label_selected = lbl_hit
                    self._tab._refresh_text_labels_ui()
                    self.update()
                    return

                # ---- Static placement mode ----
                hit = self._entity_at_tile(tx, ty)
                if hit >= 0:
                    self._tab._selected = hit
                    self._drag_kind = "static"
                    self._drag_wave_sel = -1
                    self._drag_idx = hit
                    ent = self._tab._entities[hit]
                    self._drag_tile_off = (tx - int(ent.get("x", 0)), ty - int(ent.get("y", 0)))
                    self._drag_start_mouse = pos
                    self._is_dragging = False
                    self.entity_selected.emit(hit)
                else:
                    type_name = self._tab._current_type()
                    if type_name and tool == "entity":
                        tx, ty = self._apply_rules_xy(tx, ty, type_name=type_name, in_wave=False)
                        tx, ty = self._clamp_entity_origin(tx, ty, type_name=type_name)
                        self._tab._push_undo()
                        self._tab._entities.append(self._tab._make_entity_with_type_starter(type_name, tx, ty))
                        # Optional mirror placement
                        if bool(getattr(self._tab, "_level_rules", {}).get("mirror_en", False)):
                            mx = self._mirror_x(tx, type_name=type_name)
                            if mx != tx and self._entity_at_tile(mx, ty) < 0:
                                self._tab._entities.append(self._tab._make_entity_with_type_starter(type_name, mx, ty))
                        new_idx = len(self._tab._entities) - 1
                        self._tab._selected = new_idx
                        self._drag_kind = "static"
                        self._drag_wave_sel = -1
                        self._drag_idx = new_idx
                        self._drag_start_mouse = pos
                        self._is_dragging = False
                        self.entity_selected.emit(new_idx)
                        self.entity_placed.emit()
                    else:
                        self._tab._selected = -1
                        self.entity_selected.emit(-1)
                        self._drag_kind = "none"
            self.update()

        elif event.button() == Qt.MouseButton.RightButton:
            # If a left-click entity/wave drag is in progress, cancel it and
            # ignore the right-click — avoids IndexError when the dragged entity
            # would otherwise be deleted while _drag_idx still references it.
            if self._drag_kind in ("static", "wave") and self._drag_start_mouse is not None:
                if self._is_dragging:
                    self._tab._undo()  # revert live position changes applied during the drag
                self._drag_idx = -1
                self._drag_kind = "none"
                self._drag_start_mouse = None
                self._is_dragging = False
                self.update()
                return
            if tool == "collision":
                tx, ty = self._mouse_to_tile(event.pos())
                edit_mode = self._tab._current_collision_edit_mode()
                if edit_mode == "fill":
                    if self._tab._fill_collision_region(tx, ty, _TCOL_PASS):
                        self.entity_placed.emit()
                    self.update()
                    return
                if edit_mode == "rect":
                    self._drag_kind = "collision"
                    self._drag_idx = -1
                    self._drag_wave_sel = -1
                    self._drag_start_mouse = event.pos()
                    self._drag_collision_value = _TCOL_PASS
                    self._collision_rect_start = (tx, ty)
                    self._collision_rect_preview = (tx, ty, 1, 1)
                    self._is_dragging = False
                    self.update()
                    return
                self._drag_kind = "collision"
                self._drag_idx = -1
                self._drag_wave_sel = -1
                self._drag_start_mouse = event.pos()
                self._drag_collision_value = _TCOL_PASS
                self._is_dragging = False
                cur = self._tab._collision_value_at(tx, ty)
                if cur is not None and cur != int(self._drag_collision_value):
                    self._tab._push_undo()
                    self._is_dragging = True
                if self._tab._paint_collision_tile(tx, ty, self._drag_collision_value, push_undo=False):
                    self.entity_placed.emit()
                self.update()
                return
            if getattr(self._tab, "_path_edit", False):
                tp = self._tile_px()
                px, py = int(event.pos().x()), int(event.pos().y())
                pidx = int(getattr(self._tab, "_path_selected", -1))
                if 0 <= pidx < len(self._tab._paths):
                    path = self._tab._paths[pidx]
                    pts = path.get("points", []) or []
                    hit = self._point_hit(px, py, pts, tp)
                    if hit >= 0:
                        self._tab._push_undo()
                        del pts[hit]
                        path["points"] = pts
                        self._tab._path_point_selected = min(hit, len(pts) - 1)
                        self._tab._refresh_path_points()
                        self.update()
                return
            if getattr(self._tab, "_region_edit", False):
                tx, ty = self._mouse_to_tile(event.pos())
                hit = self._tab._region_at_tile(tx, ty)
                if hit >= 0:
                    self._tab._push_undo()
                    del self._tab._regions[hit]
                    self._tab._region_selected = min(hit, len(self._tab._regions) - 1)
                    self._tab._refresh_region_list()
                    self._tab._refresh_region_props()
                    self.update()
                return
            tx, ty = self._mouse_to_tile(event.pos())
            if in_wave and 0 <= wsel < len(self._tab._waves):
                wave_ents = self._tab._waves[wsel]["entities"]
                hit = self._wave_entity_at_tile(tx, ty, wave_ents)
                if hit >= 0:
                    self._tab._push_undo()
                    del wave_ents[hit]
                    self._tab._wave_entity_sel = -1
                    self._tab._refresh_wave_list()
                    self._tab._refresh_wave_entity_props()
                    self.entity_placed.emit()
                    self.update()
            else:
                hit = self._entity_at_tile(tx, ty)
                if hit >= 0:
                    self._tab._push_undo()
                    del self._tab._entities[hit]
                    if self._tab._selected >= len(self._tab._entities):
                        self._tab._selected = len(self._tab._entities) - 1
                    self.entity_selected.emit(self._tab._selected)
                    self.entity_placed.emit()
                    self.update()

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._hover_pos = None
        self.coord_changed.emit(-1, -1)
        super().leaveEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        # Live coordinate display
        tp = self._tile_px()
        _cx = max(0, min(self._tab._grid_w - 1, event.pos().x() // tp))
        _cy = max(0, min(self._tab._grid_h - 1, event.pos().y() // tp))
        self._hover_pos = event.pos()
        if getattr(self._tab, "_pick_dest_mode", False):
            self.update()
        self.coord_changed.emit(int(_cx), int(_cy))

        # Path edit interactions (point drag)
        if (getattr(self._tab, "_path_edit", False)
                and self._drag_path
                and self._drag_path_idx >= 0
                and self._drag_point_idx >= 0
                and (event.buttons() & Qt.MouseButton.LeftButton)
                and self._drag_path_start_mouse is not None):
            pidx = int(self._drag_path_idx)
            if 0 <= pidx < len(self._tab._paths):
                path = self._tab._paths[pidx]
                pts = path.get("points", []) or []
                if 0 <= self._drag_point_idx < len(pts):
                    if not self._drag_path_pushed:
                        delta = event.pos() - self._drag_path_start_mouse
                        if abs(int(delta.x())) + abs(int(delta.y())) > _DRAG_THRESHOLD:
                            self._drag_path_pushed = True
                            self._tab._push_undo()
                    if self._drag_path_pushed:
                        px_world, py_world = self._mouse_to_scene_px(event.pos())
                        pts[self._drag_point_idx]["px"] = int(px_world)
                        pts[self._drag_point_idx]["py"] = int(py_world)
                        pts[self._drag_point_idx].pop("x", None)
                        pts[self._drag_point_idx].pop("y", None)
                        path["points"] = pts
                        self._tab._path_point_selected = int(self._drag_point_idx)
                        self._tab._refresh_path_points(no_list_rebuild=True)
                        self.update()
                        return

        # Region edit interactions
        if getattr(self._tab, "_region_edit", False):
            if (self._drag_region
                    and self._drag_region_idx >= 0
                    and event.buttons() & Qt.MouseButton.LeftButton):
                tx, ty = self._mouse_to_tile(event.pos())
                offx, offy = self._drag_region_off
                nx = max(0, min(int(self._tab._grid_w - 1), int(tx - offx)))
                ny = max(0, min(int(self._tab._grid_h - 1), int(ty - offy)))
                reg = self._tab._regions[self._drag_region_idx]
                # Keep region within bounds
                w = max(1, int(reg.get("w", 1)))
                h = max(1, int(reg.get("h", 1)))
                nx = min(nx, max(0, int(self._tab._grid_w - w)))
                ny = min(ny, max(0, int(self._tab._grid_h - h)))
                if (self._drag_region_start_mouse is not None) and (not self._drag_region_pushed):
                    delta = event.pos() - self._drag_region_start_mouse
                    if abs(delta.x()) > _DRAG_THRESHOLD or abs(delta.y()) > _DRAG_THRESHOLD:
                        self._tab._push_undo()
                        self._drag_region_pushed = True
                if (self._drag_region_pushed
                        and (int(reg.get("x", 0)) != nx or int(reg.get("y", 0)) != ny)):
                    reg["x"] = int(nx)
                    reg["y"] = int(ny)
                    self._tab._refresh_region_props()
                    self.update()
                return

            if (self._region_draw_start is not None
                    and event.buttons() & Qt.MouseButton.LeftButton):
                sx, sy = self._region_draw_start
                tx, ty = self._mouse_to_tile(event.pos())
                x0 = min(sx, tx)
                y0 = min(sy, ty)
                x1 = max(sx, tx)
                y1 = max(sy, ty)
                w = max(1, x1 - x0 + 1)
                h = max(1, y1 - y0 + 1)
                self._region_preview = (int(x0), int(y0), int(w), int(h))
                self.update()
                return

        # Ctrl+drag moves camera start
        if (self._drag_cam
                and event.buttons() & Qt.MouseButton.LeftButton
                and ((event.modifiers() & Qt.KeyboardModifier.ControlModifier)
                     or str(getattr(self._tab, "_scene_tool", "entity") or "entity") == "camera")):
            tx, ty = self._mouse_to_tile(event.pos())
            self._tab._set_cam_tile(tx, ty)
            self.update()
            return

        # Alt+drag repositions bezel
        if (self._tab._show_bezel
                and event.buttons() & Qt.MouseButton.LeftButton
                and event.modifiers() & Qt.KeyboardModifier.AltModifier):
            tx, ty = self._mouse_to_tile(event.pos())
            self._tab._bezel_tile = (tx, ty)
            self.update()
            return

        if (self._drag_kind == "collision"
                and self._drag_start_mouse is not None
                and (event.buttons() & (Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton))):
            tx, ty = self._mouse_to_tile(event.pos())
            if self._collision_rect_start is not None:
                sx, sy = self._collision_rect_start
                x0 = min(sx, tx)
                y0 = min(sy, ty)
                x1 = max(sx, tx)
                y1 = max(sy, ty)
                self._collision_rect_preview = (int(x0), int(y0), int(x1 - x0 + 1), int(y1 - y0 + 1))
                self.update()
                return
            cur = self._tab._collision_value_at(tx, ty)
            if cur is not None and cur != int(self._drag_collision_value) and not self._is_dragging:
                self._tab._push_undo()
                self._is_dragging = True
            if self._tab._paint_collision_tile(tx, ty, int(self._drag_collision_value), push_undo=False):
                self.entity_placed.emit()
                self.update()
            return

        # Wave entity drag (only in wave mode)
        if (self._tab._wave_edit
                and self._drag_kind == "wave"
                and self._drag_idx >= 0
                and self._drag_start_mouse is not None
                and event.buttons() & Qt.MouseButton.LeftButton):
            wsel = self._drag_wave_sel
            if 0 <= wsel < len(self._tab._waves):
                wave_ents = self._tab._waves[wsel]["entities"]
                if 0 <= self._drag_idx < len(wave_ents):
                    delta = event.pos() - self._drag_start_mouse
                    if (not self._is_dragging
                            and (abs(delta.x()) > _DRAG_THRESHOLD or abs(delta.y()) > _DRAG_THRESHOLD)):
                        self._tab._push_undo()
                        self._is_dragging = True
                    if self._is_dragging:
                        tx, ty = self._mouse_to_tile(event.pos())
                        ent = wave_ents[self._drag_idx]
                        offx, offy = self._drag_tile_off
                        tx -= int(offx)
                        ty -= int(offy)
                        tx, ty = self._apply_rules_xy(tx, ty, type_name=str(ent.get("type", "")), in_wave=True)
                        tx, ty = self._clamp_entity_origin(tx, ty, type_name=str(ent.get("type", "")))
                        if ent["x"] != tx or ent["y"] != ty:
                            ent["x"] = tx
                            ent["y"] = ty
                            self.entity_placed.emit()
                            self.update()
            return

        # Static entity drag (only in static mode)
        if (not self._tab._wave_edit
                and self._drag_idx >= 0
                and self._drag_start_mouse is not None
                and event.buttons() & Qt.MouseButton.LeftButton):
            delta = event.pos() - self._drag_start_mouse
            if (not self._is_dragging
                    and (abs(delta.x()) > _DRAG_THRESHOLD or abs(delta.y()) > _DRAG_THRESHOLD)):
                self._tab._push_undo()
                self._is_dragging = True
            if self._is_dragging:
                tx, ty = self._mouse_to_tile(event.pos())
                ent = self._tab._entities[self._drag_idx]
                offx, offy = self._drag_tile_off
                tx -= int(offx)
                ty -= int(offy)
                tx, ty = self._apply_rules_xy(tx, ty, type_name=str(ent.get("type", "")), in_wave=False)
                tx, ty = self._clamp_entity_origin(tx, ty, type_name=str(ent.get("type", "")))
                if ent["x"] != tx or ent["y"] != ty:
                    ent["x"] = tx
                    ent["y"] = ty
                    self.entity_placed.emit()
                    self.update()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            if self._collision_rect_start is not None and self._collision_rect_preview is not None:
                x, y, w, h = self._collision_rect_preview
                if self._tab._paint_collision_rect(x, y, w, h, int(self._drag_collision_value)):
                    self.entity_placed.emit()
                self._collision_rect_start = None
                self._collision_rect_preview = None
                self._drag_kind = "none"
                self._drag_start_mouse = None
                self._is_dragging = False
                self.update()
                return
            # Finish path point drag
            if getattr(self._tab, "_path_edit", False) and self._drag_path:
                self._drag_path = False
                self._drag_path_idx = -1
                self._drag_point_idx = -1
                self._drag_path_start_mouse = None
                self._drag_path_pushed = False
                self.update()
                return

            # Finish region draw
            if getattr(self._tab, "_region_edit", False):
                if self._region_draw_start is not None and self._region_preview is not None:
                    x, y, w, h = self._region_preview
                    self._tab._add_region_from_canvas(x, y, w, h)
                self._drag_region = False
                self._drag_region_idx = -1
                self._drag_region_start_mouse = None
                self._drag_region_pushed = False
                self._region_draw_start = None
                self._region_preview = None
                self.update()
                return

            if self._is_dragging and self._drag_idx >= 0:
                self.entity_placed.emit()
            self._drag_idx = -1
            self._drag_kind = "none"
            self._drag_wave_sel = -1
            self._drag_start_mouse = None
            self._is_dragging = False
            self._drag_tile_off = (0, 0)
            self._drag_cam = False
        elif event.button() == Qt.MouseButton.RightButton:
            if self._collision_rect_start is not None and self._collision_rect_preview is not None:
                x, y, w, h = self._collision_rect_preview
                if self._tab._paint_collision_rect(x, y, w, h, int(self._drag_collision_value)):
                    self.entity_placed.emit()
                self._collision_rect_start = None
                self._collision_rect_preview = None
                self._drag_kind = "none"
                self._drag_start_mouse = None
                self._is_dragging = False
                self.update()
                return

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z:
                self._tab._undo()
                return
            if event.key() == Qt.Key.Key_Y:
                self._tab._redo()
                return
            if event.key() == Qt.Key.Key_D:
                self._tab._duplicate_active_selection()
                return
            if event.key() == Qt.Key.Key_E:
                self._tab._export_scene_h()
                return
            if event.key() == Qt.Key.Key_0:
                if getattr(self._tab, "_btn_fit_bg", None) and self._tab._btn_fit_bg.isEnabled():
                    self._tab._fit_to_bg()
                return

        if event.key() == Qt.Key.Key_Escape:
            self._tab._set_scene_tool("select")
            return

        if event.modifiers() in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier):
            key = event.key()
            if key == Qt.Key.Key_S:
                self._tab._set_scene_tool("select")
                return
            if key == Qt.Key.Key_E:
                self._tab._set_scene_tool("entity")
                return
            if key == Qt.Key.Key_W:
                self._tab._set_scene_tool("wave")
                return
            if key == Qt.Key.Key_R:
                self._tab._set_scene_tool("region")
                return
            if key == Qt.Key.Key_P:
                self._tab._set_scene_tool("path")
                return
            if key == Qt.Key.Key_C:
                self._tab._set_scene_tool("camera")
                return
            if key == Qt.Key.Key_G:
                self._tab._set_scene_tool("collision")
                return

            if event.modifiers() == Qt.KeyboardModifier.NoModifier:
                if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
                    steps = list(_ZOOM_STEPS)
                    cur = int(getattr(self._tab, "_zoom", _DEFAULT_ZOOM))
                    idx = steps.index(cur) if cur in steps else 0
                    if idx + 1 < len(steps):
                        self._tab._set_zoom(steps[idx + 1])
                    return
                if key == Qt.Key.Key_Minus:
                    steps = list(_ZOOM_STEPS)
                    cur = int(getattr(self._tab, "_zoom", _DEFAULT_ZOOM))
                    idx = steps.index(cur) if cur in steps else len(steps) - 1
                    if idx > 0:
                        self._tab._set_zoom(steps[idx - 1])
                    return
                if key == Qt.Key.Key_F:
                    if getattr(self._tab, "_btn_fit_bg", None) and self._tab._btn_fit_bg.isEnabled():
                        self._tab._fit_to_bg()
                    return
                if key == Qt.Key.Key_F5:
                    self._tab._export_scene_h()
                    return

            step = 4 if event.modifiers() == Qt.KeyboardModifier.ShiftModifier else 1
            dx = 0
            dy = 0
            if key == Qt.Key.Key_Left:
                dx = -step
            elif key == Qt.Key.Key_Right:
                dx = step
            elif key == Qt.Key.Key_Up:
                dy = -step
            elif key == Qt.Key.Key_Down:
                dy = step
            if dx or dy:
                if getattr(self._tab, "_path_edit", False):
                    pidx = int(getattr(self._tab, "_path_selected", -1))
                    pti = int(getattr(self._tab, "_path_point_selected", -1))
                    if 0 <= pidx < len(self._tab._paths):
                        pts = self._tab._paths[pidx].get("points", []) or []
                        if 0 <= pti < len(pts):
                            pt = pts[pti]
                            cur_px, cur_py = _path_point_to_px(pt)
                            step = _TILE_PX if event.modifiers() == Qt.KeyboardModifier.ShiftModifier else 1
                            pdx = 0 if dx == 0 else (step if dx > 0 else -step)
                            pdy = 0 if dy == 0 else (step if dy > 0 else -step)
                            max_x = max(0, int(self._tab._grid_w * _TILE_PX) - 1)
                            max_y = max(0, int(self._tab._grid_h * _TILE_PX) - 1)
                            nx = max(0, min(max_x, cur_px + pdx))
                            ny = max(0, min(max_y, cur_py + pdy))
                            if nx != cur_px or ny != cur_py:
                                self._tab._push_undo()
                                pt["px"] = nx
                                pt["py"] = ny
                                pt.pop("x", None)
                                pt.pop("y", None)
                                self._tab._refresh_path_points(no_list_rebuild=True)
                                self.update()
                            return
                if getattr(self._tab, "_region_edit", False):
                    idx = int(getattr(self._tab, "_region_selected", -1))
                    if 0 <= idx < len(self._tab._regions):
                        reg = self._tab._regions[idx]
                        rw = max(1, int(reg.get("w", 1)))
                        rh = max(1, int(reg.get("h", 1)))
                        nx = max(0, min(self._tab._grid_w - rw, int(reg.get("x", 0)) + dx))
                        ny = max(0, min(self._tab._grid_h - rh, int(reg.get("y", 0)) + dy))
                        if nx != int(reg.get("x", 0)) or ny != int(reg.get("y", 0)):
                            self._tab._push_undo()
                            reg["x"] = nx
                            reg["y"] = ny
                            self._tab._refresh_region_props()
                            self._tab._refresh_region_list()
                            self.update()
                        return
                if self._tab._wave_edit:
                    wsel = self._tab._wave_selected
                    eidx = self._tab._wave_entity_sel
                    if 0 <= wsel < len(self._tab._waves):
                        wave_ents = self._tab._waves[wsel]["entities"]
                        if 0 <= eidx < len(wave_ents):
                            ent = wave_ents[eidx]
                            nx = max(0, min(self._tab._grid_w - 1, int(ent.get("x", 0)) + dx))
                            ny = max(0, min(self._tab._grid_h - 1, int(ent.get("y", 0)) + dy))
                            nx, ny = self._apply_rules_xy(nx, ny, type_name=str(ent.get("type", "")), in_wave=True)
                            if nx != int(ent.get("x", 0)) or ny != int(ent.get("y", 0)):
                                self._tab._push_undo()
                                ent["x"] = nx
                                ent["y"] = ny
                                self._tab._refresh_wave_entity_props()
                                self.entity_placed.emit()
                                self.update()
                            return
                if str(getattr(self._tab, "_scene_tool", "entity") or "entity") == "camera":
                    cx, cy = getattr(self._tab, "_cam_tile", (0, 0))
                    self._tab._set_cam_tile(int(cx) + dx, int(cy) + dy)
                    self.update()
                    return
                idx = self._tab._selected
                if 0 <= idx < len(self._tab._entities):
                    ent = self._tab._entities[idx]
                    nx = max(0, min(self._tab._grid_w - 1, int(ent.get("x", 0)) + dx))
                    ny = max(0, min(self._tab._grid_h - 1, int(ent.get("y", 0)) + dy))
                    nx, ny = self._apply_rules_xy(nx, ny, type_name=str(ent.get("type", "")), in_wave=False)
                    if nx != int(ent.get("x", 0)) or ny != int(ent.get("y", 0)):
                        self._tab._push_undo()
                        ent["x"] = nx
                        ent["y"] = ny
                        self._tab._refresh_props()
                        self.entity_placed.emit()
                        self.update()
                    return

        if event.key() == Qt.Key.Key_Delete:
            if getattr(self._tab, "_path_edit", False):
                pidx = int(getattr(self._tab, "_path_selected", -1))
                if 0 <= pidx < len(self._tab._paths):
                    path = self._tab._paths[pidx]
                    pts = path.get("points", []) or []
                    pti = int(getattr(self._tab, "_path_point_selected", -1))
                    if 0 <= pti < len(pts):
                        self._tab._push_undo()
                        del pts[pti]
                        path["points"] = pts
                        self._tab._path_point_selected = min(pti, len(pts) - 1)
                        self._tab._refresh_path_points()
                        self.update()
                return
            if getattr(self._tab, "_region_edit", False):
                idx = int(getattr(self._tab, "_region_selected", -1))
                if 0 <= idx < len(self._tab._regions):
                    self._tab._push_undo()
                    del self._tab._regions[idx]
                    self._tab._region_selected = min(idx, len(self._tab._regions) - 1)
                    self._tab._refresh_region_list()
                    self._tab._refresh_region_props()
                    self.update()
                return
            if self._tab._wave_edit:
                wsel = self._tab._wave_selected
                if 0 <= wsel < len(self._tab._waves):
                    wave_ents = self._tab._waves[wsel]["entities"]
                    eidx = self._tab._wave_entity_sel
                    if 0 <= eidx < len(wave_ents):
                        self._tab._push_undo()
                        del wave_ents[eidx]
                        self._tab._wave_entity_sel = min(eidx, len(wave_ents) - 1)
                        self._tab._refresh_wave_list()
                        self._tab._refresh_wave_entity_props()
                        self.entity_placed.emit()
                        self.update()
            else:
                idx = self._tab._selected
                if 0 <= idx < len(self._tab._entities):
                    self._tab._push_undo()
                    del self._tab._entities[idx]
                    self._tab._selected = min(idx, len(self._tab._entities) - 1)
                    self.entity_selected.emit(self._tab._selected)
                    self.entity_placed.emit()
                    self.update()
        else:
            super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# LevelTab
# ---------------------------------------------------------------------------

class _ProcgenTilePickerDialog(QDialog):
    """Visual multi-selection dialog for Procgen role -> tile mapping."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        source_pm: QPixmap | None,
        source_name: str,
        selected_ids: list[int],
        default_id: int,
    ) -> None:
        super().__init__(parent)
        self._default_id = int(default_id)
        self._reset_to_default = False
        self.setWindowTitle(tr("level.tile_role_picker_title"))
        self.resize(700, 520)

        root = QVBoxLayout(self)

        hint = QLabel(tr("level.tile_role_picker_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #aaa;")
        root.addWidget(hint)

        self._info = QLabel("")
        self._info.setWordWrap(True)
        self._info.setStyleSheet("color: #aaa; font-size: 10px;")
        root.addWidget(self._info)

        self._list = QListWidget()
        self._list.setViewMode(QListView.ViewMode.IconMode)
        self._list.setResizeMode(QListView.ResizeMode.Adjust)
        self._list.setMovement(QListView.Movement.Static)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self._list.setIconSize(QSize(32, 32))
        self._list.setGridSize(QSize(40, 52))
        self._list.setSpacing(4)
        root.addWidget(self._list, 1)

        if source_pm is None or source_pm.isNull():
            self._list.setEnabled(False)
            self._info.setText(tr("level.tile_role_picker_no_source"))
        else:
            try:
                tw = int(source_pm.width() // _TILE_PX)
                th = int(source_pm.height() // _TILE_PX)
            except Exception:
                tw = 0
                th = 0
            if tw <= 0 or th <= 0:
                self._list.setEnabled(False)
                self._info.setText(tr("level.tile_role_picker_no_source"))
            else:
                self._info.setText(
                    tr("level.tile_role_picker_source", name=(source_name or "atlas"), n=tw * th)
                )
                img = source_pm.toImage()
                selected = {int(v) for v in selected_ids}
                for tile_idx in range(tw * th):
                    tx = tile_idx % tw
                    ty = tile_idx // tw
                    crop = img.copy(tx * _TILE_PX, ty * _TILE_PX, _TILE_PX, _TILE_PX)
                    icon_pm = QPixmap.fromImage(crop).scaled(
                        32, 32,
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.FastTransformation,
                    )
                    item = QListWidgetItem(QIcon(icon_pm), str(tile_idx))
                    item.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
                    item.setData(Qt.ItemDataRole.UserRole, int(tile_idx))
                    item.setToolTip(
                        tr(
                            "level.tile_role_preview_tt",
                            idx=int(tile_idx),
                            x=int(tx),
                            y=int(ty),
                            w=int(tw),
                            h=int(th),
                            name=(source_name or "atlas"),
                        )
                    )
                    item.setSelected(tile_idx in selected)
                    self._list.addItem(item)

        btn_row = QHBoxLayout()
        btn_reset = QPushButton(tr("level.tile_role_picker_reset"))
        btn_reset.clicked.connect(self._on_reset_to_default)
        btn_row.addWidget(btn_reset)
        btn_row.addStretch()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        btn_row.addWidget(buttons)
        root.addLayout(btn_row)

    def _on_reset_to_default(self) -> None:
        self._reset_to_default = True
        self.accept()

    def selected_ids(self) -> list[int]:
        if self._reset_to_default:
            return [int(self._default_id)]
        ids: list[int] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item is None or not item.isSelected():
                continue
            ids.append(int(item.data(Qt.ItemDataRole.UserRole) or 0))
        return ids or [int(self._default_id)]


# ---------------------------------------------------------------------------
# BG layer card widgets (LDtk-style)
# ---------------------------------------------------------------------------

class _BgPlaneRow(QWidget):
    """BG plane row: header line (label + thumb + buttons) + filename line below."""

    THUMB_W = 40
    THUMB_H = 28

    def __init__(self, plane: str, parent: "QWidget | None" = None) -> None:
        super().__init__(parent)
        self._plane = plane
        self._on_change: "Callable | None" = None
        self._on_add:    "Callable | None" = None
        self._on_remove: "Callable | None" = None

        vl = QVBoxLayout(self)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(2)

        # ── Row 1: plane label + thumbnail + action buttons ──
        hl = QHBoxLayout()
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(4)

        lbl = QLabel(f"<b>{plane.upper()}</b>")
        lbl.setFixedWidth(36)
        hl.addWidget(lbl)

        self._thumb = QLabel()
        self._thumb.setFixedSize(self.THUMB_W, self.THUMB_H)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setStyleSheet("background:#2a2a2e; border:1px solid #444; border-radius:2px;")
        self._thumb.setText("—")
        hl.addWidget(self._thumb)

        hl.addStretch(1)

        self._btn_change = QPushButton("Changer…")
        self._btn_change.setFixedHeight(22)
        self._btn_change.setToolTip("Changer la tilemap assignée à ce plan")
        self._btn_change.clicked.connect(lambda: self._on_change(self._plane) if self._on_change else None)
        hl.addWidget(self._btn_change)

        self._btn_add = QPushButton("+")
        self._btn_add.setFixedSize(22, 22)
        self._btn_add.setToolTip("Ajouter une PNG tilemap à la scène et l'assigner à ce plan")
        self._btn_add.clicked.connect(lambda: self._on_add(self._plane) if self._on_add else None)
        hl.addWidget(self._btn_add)

        self._btn_remove = QPushButton("×")
        self._btn_remove.setFixedSize(22, 22)
        self._btn_remove.setToolTip("Retirer cette tilemap du plan (ne supprime pas le fichier)")
        self._btn_remove.setStyleSheet("color:#e05050;")
        self._btn_remove.setVisible(False)
        self._btn_remove.clicked.connect(lambda: self._on_remove(self._plane) if self._on_remove else None)
        hl.addWidget(self._btn_remove)

        vl.addLayout(hl)

        # ── Row 2: filename (full width, wraps) ──
        self._lbl_file = QLabel("(aucun)")
        self._lbl_file.setStyleSheet("color:#aaa; font-size:10px;")
        self._lbl_file.setWordWrap(True)
        vl.addWidget(self._lbl_file)

    def set_callbacks(self, on_change: "Callable", on_add: "Callable", on_remove: "Callable") -> None:
        self._on_change = on_change
        self._on_add    = on_add
        self._on_remove = on_remove

    def set_info(self, pixmap: "QPixmap | None", filename: str) -> None:
        has = pixmap is not None and not pixmap.isNull()
        if has:
            scaled = pixmap.scaled(
                self.THUMB_W, self.THUMB_H,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            self._thumb.setPixmap(scaled)
            self._thumb.setText("")
        else:
            self._thumb.clear()
            self._thumb.setText("—")
        self._lbl_file.setText(filename or "(aucun)")
        self._btn_remove.setVisible(bool(filename))

    def set_warn(self, warn: bool, tooltip: str = "") -> None:
        """Highlight the row when the tilemap's plane metadata conflicts with this slot."""
        if warn:
            self._lbl_file.setStyleSheet("color:#e07020; font-size:10px; font-weight:bold;")
            self._lbl_file.setToolTip(tooltip)
        else:
            self._lbl_file.setStyleSheet("color:#aaa; font-size:10px;")
            self._lbl_file.setToolTip("")


class _BgPickerDialog(QDialog):
    """Tilemap picker grid (thumbnail + name) for BG layer assignment."""

    THUMB_W = 80
    THUMB_H = 52

    def __init__(
        self,
        plane: str,
        bg_paths: list,
        bg_rels: list,
        current_idx: int,
        parent: "QWidget | None" = None,
    ) -> None:
        super().__init__(parent)
        plane_upper = plane.upper()
        self.setWindowTitle(f"Tilemap — {plane_upper}")
        self.setModal(True)
        self._chosen: int = current_idx

        lv = QVBoxLayout(self)
        lv.setSpacing(6)
        lv.addWidget(QLabel(f"<b>Choisir le fond pour {plane_upper} :</b>"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(260)
        inner = QWidget()
        from PyQt6.QtWidgets import QGridLayout
        grid = QGridLayout(inner)
        grid.setSpacing(6)
        scroll.setWidget(inner)
        lv.addWidget(scroll)

        # "None" tile (index 0)
        none_btn = QPushButton("(aucun)")
        none_btn.setFixedSize(self.THUMB_W, self.THUMB_H + 20)
        none_btn.setCheckable(True)
        none_btn.setChecked(current_idx == 0)
        none_btn.clicked.connect(lambda: self._pick(0))
        grid.addWidget(none_btn, 0, 0)

        col = 1
        row = 0
        cols_per_row = 4
        for i, (p, rel) in enumerate(zip(bg_paths, bg_rels)):
            real_idx = i + 1  # bg_rels[0] is None sentinel
            if p is None:
                continue
            frame = QFrame()
            frame.setFrameShape(QFrame.Shape.StyledPanel)
            fl = QVBoxLayout(frame)
            fl.setContentsMargins(2, 2, 2, 2)
            fl.setSpacing(2)

            thumb_lbl = QLabel()
            thumb_lbl.setFixedSize(self.THUMB_W, self.THUMB_H)
            thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb_lbl.setStyleSheet("background: #2a2a2e;")
            try:
                pm = QPixmap(str(p))
                if not pm.isNull():
                    pm = pm.scaled(
                        self.THUMB_W, self.THUMB_H,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.FastTransformation,
                    )
                    thumb_lbl.setPixmap(pm)
                else:
                    thumb_lbl.setText("?")
            except Exception:
                thumb_lbl.setText("?")
            fl.addWidget(thumb_lbl)

            name = str(p.name) if hasattr(p, "name") else str(rel or "?")
            if len(name) > 14:
                name = name[:13] + "…"
            name_lbl = QLabel(name)
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_lbl.setStyleSheet("font-size: 9px;")
            fl.addWidget(name_lbl)

            select_btn = QPushButton("Choisir")
            select_btn.setFixedHeight(20)
            if real_idx == current_idx:
                select_btn.setStyleSheet("font-weight: bold; color: #4ec94e;")
                select_btn.setText("✓ Actif")
            ri = real_idx  # capture for lambda
            select_btn.clicked.connect(lambda _=False, ri=ri: self._pick(ri))
            fl.addWidget(select_btn)

            grid.addWidget(frame, row, col)
            col += 1
            if col >= cols_per_row:
                col = 0
                row += 1

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        btns.rejected.connect(self.reject)
        lv.addWidget(btns)

    def _pick(self, idx: int) -> None:
        self._chosen = idx
        self.accept()

    def chosen_index(self) -> int:
        return self._chosen


# X-3 — OAM viewer color map (role → QColor hex)
_OAM_ROLE_COLORS: dict[str, str] = {
    "player":   "#4fc16e",
    "enemy":    "#e05050",
    "item":     "#f0c040",
    "npc":      "#60b8e0",
    "prop":     "#a060d0",
    "block":    "#7090b0",
    "platform": "#50a0a0",
    "trigger":  "#808080",
}
_OAM_EMPTY_COLOR   = "#2a2d32"
_OAM_OVERFLOW_COLOR = "#ff2020"
_OAM_SLOTS         = 64
_OAM_COLS          = 16


class _ConstantPickerWidget(QWidget):
    """Hybrid spinbox + project-constant selector for trigger value fields.

    Shows a compact combo (project constants) next to a spinbox.
    When a constant is selected the spinbox becomes read-only and mirrors its
    value.  When '(aucune)' is selected the spinbox is freely editable.
    Stores the chosen constant name so the C exporter can emit the macro name
    instead of a raw integer.
    """

    value_changed = pyqtSignal()

    def __init__(self, max_val: int = 65535, parent=None) -> None:
        super().__init__(parent)
        self._max_val = max_val
        self._updating = False
        self._consts: list[dict] = []   # [{name, value, comment}, …]

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        self._combo = QComboBox()
        self._combo.setFixedWidth(130)
        self._combo.addItem(tr("level.const_picker_none"), "")
        self._combo.setToolTip(tr("level.const_picker_tt"))
        self._combo.currentIndexChanged.connect(self._on_combo_changed)
        lay.addWidget(self._combo)

        self._spin = QSpinBox()
        self._spin.setRange(0, max_val)
        self._spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._spin.setFixedWidth(58)
        self._spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._spin.valueChanged.connect(self._on_spin_changed)
        lay.addWidget(self._spin)

    # ------------------------------------------------------------------ public
    def set_constants(self, consts: list[dict]) -> None:
        """Repopulate combo from project constants list."""
        self._consts = consts or []
        prev_name = self.const_name()
        self._updating = True
        try:
            self._combo.clear()
            self._combo.addItem(tr("level.const_picker_none"), "")
            for c in self._consts:
                name = str(c.get("name", "") or "").strip()
                val  = int(c.get("value", 0) or 0)
                if name:
                    self._combo.addItem(f"{name} = {val}", name)
            # Restore previous selection if still present
            idx = self._combo.findData(prev_name)
            self._combo.setCurrentIndex(idx if idx >= 0 else 0)
        finally:
            self._updating = False
        self._apply_const_state()

    def set_value(self, v: int, const_name: str = "") -> None:
        """Load a value + optional constant name (call with blockSignals held)."""
        self._updating = True
        try:
            idx = self._combo.findData(const_name) if const_name else -1
            self._combo.setCurrentIndex(idx if idx >= 0 else 0)
            self._spin.setValue(int(v) & self._max_val)
        finally:
            self._updating = False
        self._apply_const_state()

    def value(self) -> int:
        return int(self._spin.value())

    def const_name(self) -> str:
        return str(self._combo.currentData() or "")

    def block_signals(self, block: bool) -> None:
        self._combo.blockSignals(block)
        self._spin.blockSignals(block)

    # ---------------------------------------------------------------- internal
    def _on_combo_changed(self, _idx: int) -> None:
        if self._updating:
            return
        self._apply_const_state()
        if not self._updating:
            self.value_changed.emit()

    def _on_spin_changed(self, _v: int) -> None:
        if self._updating:
            return
        self.value_changed.emit()

    def _apply_const_state(self) -> None:
        """Sync spinbox value from selected constant; set read-only when locked."""
        name = self.const_name()
        if name:
            c = next((c for c in self._consts
                      if str(c.get("name", "") or "").strip() == name), None)
            if c is not None:
                self._updating = True
                try:
                    self._spin.setValue(int(c.get("value", 0) or 0) & self._max_val)
                finally:
                    self._updating = False
            self._spin.setReadOnly(True)
            self._spin.setStyleSheet("color: #7ab4e0;")
        else:
            self._spin.setReadOnly(False)
            self._spin.setStyleSheet("")


class _OamCanvasWidget(QWidget):
    """Visualises 64 NGPC hardware sprite slots as a 16×4 grid of colored squares."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # list of (color_hex, tooltip_str) — len == 64
        self._slots: list[tuple[str, str]] = [(_OAM_EMPTY_COLOR, "") for _ in range(_OAM_SLOTS)]
        self.setMinimumHeight(72)
        self.setMouseTracking(True)

    def set_slots(self, slots: list[tuple[str, str]]) -> None:
        self._slots = slots[:_OAM_SLOTS]
        while len(self._slots) < _OAM_SLOTS:
            self._slots.append((_OAM_EMPTY_COLOR, ""))
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w = self.width()
        box = max(4, w // (_OAM_COLS + 1))
        rows = (_OAM_SLOTS + _OAM_COLS - 1) // _OAM_COLS
        pad_x = (w - box * _OAM_COLS) // 2
        pad_y = 4
        p.setPen(QPen(QColor("#1a1c20"), 1))
        for i, (col, _tip) in enumerate(self._slots):
            col_i = i % _OAM_COLS
            row_i = i // _OAM_COLS
            x = pad_x + col_i * box
            y = pad_y + row_i * box
            p.fillRect(x + 1, y + 1, box - 2, box - 2, QColor(col))
        p.end()

    def mouseMoveEvent(self, event) -> None:
        w = self.width()
        box = max(4, w // (_OAM_COLS + 1))
        pad_x = (w - box * _OAM_COLS) // 2
        pad_y = 4
        mx, my = event.position().x(), event.position().y()
        col_i = int((mx - pad_x) // box)
        row_i = int((my - pad_y) // box)
        if 0 <= col_i < _OAM_COLS and 0 <= row_i < (_OAM_SLOTS // _OAM_COLS):
            idx = row_i * _OAM_COLS + col_i
            if 0 <= idx < len(self._slots):
                tip = self._slots[idx][1]
                self.setToolTip(f"Slot {idx}: {tip}" if tip else f"Slot {idx}: empty")
                return
        self.setToolTip("")


class LevelTab(QWidget):
    """Level / entity placement editor with wave system and procgen."""

    entities_changed = pyqtSignal()
    open_globals_tab_requested = pyqtSignal()   # emitted to switch to Globals tab

    def __init__(self, on_save=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_save = on_save

        # Core state
        self._scene:    Optional[dict] = None
        self._base_dir: Optional[Path] = None
        self._dgen_pa_png_rel: str = ""  # relative path to DungeonGen tileset PNG
        self._project_scenes:    list[dict] = []
        self._project_constants: list[dict] = []
        self._project_songs:     list = []   # list[AudioSong] from manifest
        self._project_sfx_map:   list[dict] = []  # sfx_map rows {"name": str, "project_id": int}
        self._entities: list[dict] = []
        self._selected: int = -1
        self._zoom:     int  = _DEFAULT_ZOOM
        self._grid_w:   int  = _SCREEN_W
        self._grid_h:   int  = _SCREEN_H

        # Visuals
        self._bg_pixmap_scr1:    Optional[QPixmap]         = None
        self._bg_pixmap_scr2:    Optional[QPixmap]         = None
        self._bg_paths:          list[Optional[Path]]      = []
        self._bg_rels:           list[Optional[str]]       = []
        self._bg_plane_hints:    dict[str, str]            = {}  # rel → "scr1"/"scr2"/"auto"
        self._bg_front:          str                       = "scr1"
        self._type_names:        list[str]                 = []
        self._type_pixmaps:      dict[str, QPixmap]        = {}
        self._type_sizes:        dict[str, tuple[int, int]]= {}
        self._type_list_pixmaps: dict[str, QPixmap]        = {}
        self._updating_props:    bool                      = False
        self._show_bezel:        bool                      = True
        self._bezel_tile:        tuple[int, int]           = (0, 0)
        self._show_cam:          bool                      = True
        self._show_regions:      bool                      = True
        self._show_triggers:     bool                      = True
        self._show_paths:        bool                      = True
        self._show_waves:        bool                      = True

        # Layout metadata (camera mode + optional clamp bounds)
        self._layout_cfg: dict = {
            "cam_mode": "single_screen",
            "bounds_auto": True,
            "clamp": True,
            "min_x": 0,
            "min_y": 0,
            "max_x": 0,
            "max_y": 0,
            "follow_deadzone_x": 16,
            "follow_deadzone_y": 12,
            "follow_drop_margin_y": 20,
            "cam_lag": 0,
        }

        # Layer metadata (SCR1/SCR2 parallax, etc.)
        self._layers_cfg: dict = {
            "scr1_parallax_x": 100,
            "scr1_parallax_y": 100,
            "scr2_parallax_x": 100,
            "scr2_parallax_y": 100,
            "bg_front": "scr1",
        }

        # Undo / redo (snapshots of both entities and waves)
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []

        # Roles
        self._entity_roles: dict[str, str] = {}
        self._level_profile: str = "none"

        # Waves
        self._waves:            list[dict] = []
        self._wave_selected:    int        = -1
        self._wave_edit:        bool       = False
        self._wave_entity_sel:  int        = -1
        self._scene_tool:       str        = "entity"
        self._collision_brush:  int        = _TCOL_SOLID
        self._collision_edit_mode: str     = "brush"

        # Regions (rectangles in tile coords)
        self._regions: list[dict] = []
        self._region_selected: int = -1
        self._region_edit: bool = False

        # Text labels (sysfont, static)
        self._text_labels: list[dict] = []
        self._text_label_selected: int = -1

        # Triggers (metadata tied to regions/camera/timers; exported to C)
        self._triggers: list[dict] = []
        self._trigger_selected: int = -1

        # Paths (routes; points in pixel coords)
        self._paths: list[dict] = []
        self._path_selected: int = -1
        self._path_edit: bool = False
        self._path_point_selected: int = -1

        # Trigger destination pick mode (move_entity_to tile picker)
        self._pick_dest_mode: bool = False

        # Placement rules / constraints (game-profile friendly)
        self._level_rules: dict = {
            "lock_y_en": False,
            "lock_y": 0,
            "ground_band_en": False,
            "ground_min_y": 0,
            "ground_max_y": _SCREEN_H - 1,
            "mirror_en": False,
            "mirror_axis_x": (_SCREEN_W - 1) // 2,
            "apply_to_waves": True,
            "hazard_damage": 1,
            "fire_damage": 1,
            "void_damage": 255,
            "void_instant": True,
            "hazard_invul": 30,
            "spring_force": 8,
            "spring_dir": "up",
            "conveyor_speed": 2,
            "ice_friction": 0,
            "water_drag": 2,
            "water_damage": 0,
            "zone_force": 2,
            "ladder_top_solid": False,
            "hud_enabled": False,
            "hud_show_hp": False,
            "hud_show_score": False,
            "hud_show_collect": False,
            "hud_show_timer": False,
            "hud_show_lives": False,
            "hud_pos": "top",
            "hud_font_mode": "system",
            "hud_fixed_plane": "none",
            "hud_text_color": "white",
            "hud_style": "text",
            "hud_band_color": "blue",
            "hud_band_rows": 2,
            "hud_digits_hp": 2,
            "hud_digits_score": 5,
            "hud_digits_collect": 3,
            "hud_digits_timer": 3,
            "hud_digits_lives": 2,
            "hud_digits_continues": 2,
            "goal_collectibles": 0,
            "time_limit_sec": 0,
            "start_lives": 0,
            "start_continues": 0,
            "continue_restore_lives": 3,
            "hud_custom_font_digits": [""] * 10,
            "hud_custom_items": [],
        }
        self._hud_widget_selected: int = -1
        self._hud_widget_updating: bool = False

        # Collision / tile map (procgen output)
        self._col_map:      Optional[list[list[int]]] = None   # [y][x] = TCOL_*
        self._col_map_meta: dict = {}
        self._col_map_base: Optional[list[list[int]]] = None
        self._show_col_map: bool = True
        self._map_mode:     str  = "none"
        # Visual tile ids per role per mode: {mode: {role_key: int | [int, ...]}}
        self._tile_ids:     dict[str, dict[str, object]] = {}

        _init_tcol_overlays()

        # Cache: (pixmap.cacheKey, tile_index) -> 24x24 preview pixmap
        self._tile_thumb_cache: dict[tuple[int, int], QPixmap] = {}
        # Large-map: viewport preview tile position
        self._build_ui()
        self._sync_scene_tool_buttons()
        self._refresh_type_starter_ui()

    # ------------------------------------------------------------------
    # Entity identity helpers
    # ------------------------------------------------------------------

    def _make_entity(self, type_name: str, x: int, y: int, *, data: int = 0) -> dict:
        """Create a static scene entity with a stable identifier."""
        return {"id": _new_id(), "type": type_name, "x": int(x), "y": int(y), "data": int(data)}

    @staticmethod
    def _sanitize_entity(e: dict) -> dict:
        """Ensure an entity dict loaded from JSON has all required keys.

        Random-wave entries (wave entries with rand=True) additionally carry
        spawn_side, count_min/max and interval fields, consumed by the
        ngpc_rwave runtime. Non-rand entries stay unchanged.
        """
        d = dict(e)
        d.setdefault("type", "")
        d.setdefault("x", 0)
        d.setdefault("y", 0)
        d.setdefault("data", 0)
        if bool(d.get("rand", False)):
            d["rand"] = True
            d.setdefault("spawn_side", 0)      # 0=right,1=left,2=top,3=bottom
            d.setdefault("count_min", 1)
            d.setdefault("count_max", 3)
            d.setdefault("interval", 30)       # frames between wave repeats
            d.setdefault("max_waves", 0)       # 0 = infinite cycles
            d.setdefault("spawn_behavior", "legacy")  # patrol|chase|fixed|random|flee|legacy
            d.setdefault("spawn_flags", 1)     # bit0=CLAMP_MAP by default
            # spawn_no_cull: when true, disable the auto CULL_OFFSCREEN flag the
            # exporter normally forces on wave spawns (off-screen drift kills).
            d.setdefault("spawn_no_cull", False)
        return d

    def _clamp_tile_xy(self, x: int, y: int) -> tuple[int, int]:
        return (
            max(0, min(int(self._grid_w) - 1, int(x))),
            max(0, min(int(self._grid_h) - 1, int(y))),
        )

    def _ensure_entity_ids(self) -> None:
        """Ensure every static scene entity has a unique persistent identifier."""
        seen: set[str] = set()
        for ent in self._entities:
            if not isinstance(ent, dict):
                continue
            eid = str(ent.get("id", "") or "").strip()
            if not eid or eid in seen:
                eid = _new_id()
                ent["id"] = eid
            seen.add(eid)

    def _prop_src_idx_for_sprite_name(self, sprite_name: str) -> int | None:
        """Return the runtime src_idx for a prop/NPC sprite type.

        The runtime assigns src_idx = i where i is the entity's position in the
        placed entities array (self._entities). PLAYER / ENEMY / TRIGGER entities
        are skipped by the runtime loader but their indices still count, so the
        src_idx of a prop equals its raw index in _entities regardless of how
        many players precede it.

        Returns None if no placed entity of that sprite type exists.
        """
        for i, ent in enumerate(self._entities):
            if not isinstance(ent, dict):
                continue
            if str(ent.get("type", "") or "").strip() == sprite_name:
                # Only count types that the runtime loads as props
                role = str(self._entity_roles.get(sprite_name, "prop") or "prop").strip().lower()
                if role not in ("player", "enemy", "trigger"):
                    return i
        return None

    def _entity_target_id_for_index(self, idx: int) -> str:
        """Resolve a legacy entity index to the current stable identifier."""
        if 0 <= idx < len(self._entities):
            ent = self._entities[idx]
            if isinstance(ent, dict):
                return str(ent.get("id", "") or "").strip()
        return ""

    def _entity_index_for_target_id(self, target_id: str) -> int | None:
        """Resolve a stable entity identifier to the current entity index."""
        tid = str(target_id or "").strip()
        if not tid:
            return None
        for i, ent in enumerate(self._entities):
            if isinstance(ent, dict) and str(ent.get("id", "") or "").strip() == tid:
                return i
        return None

    def _normalize_trigger_entity_refs(self) -> None:
        """Backfill stable trigger targets for older scenes that only stored indexes."""
        for trig in self._triggers:
            if not isinstance(trig, dict):
                continue
            act = str(trig.get("action", "") or "").strip().lower()
            if act not in ("show_entity", "hide_entity", "move_entity_to", "pause_entity_path", "resume_entity_path"):
                continue
            target_id = str(trig.get("entity_target_id", "") or "").strip()
            if target_id and self._entity_index_for_target_id(target_id) is not None:
                continue
            legacy_idx = int(trig.get("entity_index", trig.get("event", 0)) or 0)
            resolved_id = self._entity_target_id_for_index(legacy_idx)
            if resolved_id:
                trig["entity_target_id"] = resolved_id

    def _role_preview_source(self) -> tuple[QPixmap | None, str]:
        """Pick the best BG pixmap to sample tiles from (for Procgen role thumbnails)."""
        choice = "auto"
        try:
            choice = str(self._combo_tile_src.currentData() or "auto")
        except Exception:
            choice = "auto"
        try:
            i1 = int(self._combo_bg_scr1.currentIndex())
        except Exception:
            i1 = 0
        try:
            i2 = int(self._combo_bg_scr2.currentIndex())
        except Exception:
            i2 = 0

        if choice == "scr1":
            if self._bg_pixmap_scr1 is not None:
                return self._bg_pixmap_scr1, str(self._combo_bg_scr1.currentText() or "SCR1")
            return None, ""
        if choice == "scr2":
            if self._bg_pixmap_scr2 is not None:
                return self._bg_pixmap_scr2, str(self._combo_bg_scr2.currentText() or "SCR2")
            return None, ""

        if i1 > 0 and self._bg_pixmap_scr1 is not None:
            return self._bg_pixmap_scr1, str(self._combo_bg_scr1.currentText())
        if i2 > 0 and self._bg_pixmap_scr2 is not None:
            return self._bg_pixmap_scr2, str(self._combo_bg_scr2.currentText())
        if self._bg_pixmap_scr1 is not None:
            return self._bg_pixmap_scr1, "SCR1"
        if self._bg_pixmap_scr2 is not None:
            return self._bg_pixmap_scr2, "SCR2"
        return None, ""

    def _tile_thumb(self, tile_idx: int) -> tuple[QPixmap | None, str]:
        """Return a small pixmap preview for a tile index (8×8) from the selected BG."""
        pm_src, name = self._role_preview_source()
        if pm_src is None or pm_src.isNull():
            return None, ""

        try:
            tw = int(pm_src.width() // _TILE_PX)
            th = int(pm_src.height() // _TILE_PX)
        except Exception:
            return None, ""
        if tw <= 0 or th <= 0:
            return None, ""

        tx = int(tile_idx) % tw
        ty = int(tile_idx) // tw
        if ty < 0 or ty >= th:
            return None, ""

        key = (int(pm_src.cacheKey()), int(tile_idx))
        if key in self._tile_thumb_cache:
            pm = self._tile_thumb_cache[key]
        else:
            try:
                img = pm_src.toImage()
                x0 = tx * _TILE_PX
                y0 = ty * _TILE_PX
                crop = img.copy(x0, y0, _TILE_PX, _TILE_PX)
                pm = QPixmap.fromImage(crop).scaled(
                    24, 24,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
                self._tile_thumb_cache[key] = pm
            except Exception:
                return None, ""

        tip = tr("level.tile_role_preview_tt", idx=int(tile_idx), x=int(tx), y=int(ty), w=int(tw), h=int(th), name=name)
        return pm, tip

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ---- LEFT: tabbed panel -------------------------------------------
        left_tabs = QTabWidget()
        left_tabs.setMinimumWidth(150)

        # --- Tab 0: Entités ---
        tab_ent = QWidget()
        lv = QVBoxLayout(tab_ent)
        lv.setContentsMargins(4, 4, 4, 4)
        lv.setSpacing(3)

        lv.addWidget(QLabel(tr("level.types_label")))

        self._type_list = QListWidget()
        self._type_list.setIconSize(QSize(32, 32))
        self._type_list.setSpacing(2)
        self._type_list.setToolTip(tr("level.types_tt"))
        self._type_list.currentItemChanged.connect(self._on_type_selection_changed)
        lv.addWidget(self._type_list, 1)

        self._btn_add_from_template = QPushButton(tr("level.add_from_template"))
        self._btn_add_from_template.setToolTip(tr("level.add_from_template_tt"))
        self._btn_add_from_template.clicked.connect(self._on_add_from_template)
        lv.addWidget(self._btn_add_from_template)

        role_row = QHBoxLayout()
        role_row.addWidget(QLabel(tr("level.role_label")))
        self._combo_role = QComboBox()
        for r in _ROLES:
            self._combo_role.addItem(f"{_ROLE_SHORT[r]} {r}", r)
        self._combo_role.setToolTip(tr("level.role_tt"))
        self._combo_role.currentIndexChanged.connect(self._on_role_changed)
        role_row.addWidget(self._combo_role, 1)
        lv.addLayout(role_row)

        starter_row = QHBoxLayout()
        starter_row.addWidget(QLabel(tr("level.starter_label")))
        self._combo_type_starter = QComboBox()
        self._combo_type_starter.setToolTip(tr("level.starter_tt"))
        starter_row.addWidget(self._combo_type_starter, 1)
        self._btn_place_starter = QPushButton(tr("level.starter_place"))
        self._btn_place_starter.setToolTip(tr("level.starter_place_tt"))
        self._btn_place_starter.clicked.connect(self._place_selected_type_starter)
        self._btn_place_starter.setFixedWidth(62)
        starter_row.addWidget(self._btn_place_starter)
        lv.addLayout(starter_row)

        self._lbl_type_starter_hint = QLabel("")
        self._lbl_type_starter_hint.setWordWrap(True)
        self._lbl_type_starter_hint.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        lv.addWidget(self._lbl_type_starter_hint)

        prof_row = QHBoxLayout()
        prof_row.addWidget(QLabel(tr("level.profile_label")))
        self._combo_profile = QComboBox()
        for key, label_key in _LEVEL_PROFILES:
            self._combo_profile.addItem(tr(label_key), key)
        self._combo_profile.setToolTip(tr("level.profile_tt"))
        self._combo_profile.currentIndexChanged.connect(self._on_profile_changed)
        prof_row.addWidget(self._combo_profile, 1)
        self._btn_apply_profile = QPushButton(tr("level.profile_apply"))
        self._btn_apply_profile.setToolTip(tr("level.profile_apply_tt"))
        self._btn_apply_profile.clicked.connect(self._apply_profile_clicked)
        self._btn_apply_profile.setFixedWidth(74)
        prof_row.addWidget(self._btn_apply_profile)
        lv.addLayout(prof_row)

        self._ctx_level_flow = ContextHelpBox(
            tr("level.ctx_workflow_title"),
            tr("level.ctx_workflow_body"),
            self,
        )
        lv.addWidget(self._ctx_level_flow)

        lv.addWidget(QLabel(tr("level.place_hint")))
        left_tabs.addTab(tab_ent, tr("level.tab_entities"))

        # --- Tab 1: BG ---
        tab_bg = QWidget()
        bv = QVBoxLayout(tab_bg)
        bv.setContentsMargins(4, 4, 4, 4)
        bv.setSpacing(4)

        # Hidden state-holder combos live here (invisible, just need a parent)
        self._combo_bg_scr1 = QComboBox()
        self._combo_bg_scr1.currentIndexChanged.connect(self._on_bg_scr1_changed)
        self._combo_bg_scr1.setVisible(False)
        bv.addWidget(self._combo_bg_scr1)
        self._combo_bg_scr2 = QComboBox()
        self._combo_bg_scr2.currentIndexChanged.connect(self._on_bg_scr2_changed)
        self._combo_bg_scr2.setVisible(False)
        bv.addWidget(self._combo_bg_scr2)

        # Info label
        _info_lbl = QLabel("ℹ NGPC : 2 plans BG (SCR1 + SCR2) — 1 tilemap par plan.")
        _info_lbl.setStyleSheet("color:#888; font-size:9px;")
        _info_lbl.setWordWrap(True)
        bv.addWidget(_info_lbl)

        # Compact plane rows
        self._card_scr1 = _BgPlaneRow("scr1")
        self._card_scr1.set_callbacks(
            on_change=self._open_bg_picker,
            on_add=self._add_bg_png,
            on_remove=self._remove_bg_plane,
        )
        self._card_scr2 = _BgPlaneRow("scr2")
        self._card_scr2.set_callbacks(
            on_change=self._open_bg_picker,
            on_add=self._add_bg_png,
            on_remove=self._remove_bg_plane,
        )

        # Front selector
        self._combo_bg_front = QComboBox()
        self._combo_bg_front.addItem(tr("level.bg_front_scr1"), "scr1")
        self._combo_bg_front.addItem(tr("level.bg_front_scr2"), "scr2")
        self._combo_bg_front.setToolTip(tr("level.bg_front_tt"))
        self._combo_bg_front.currentIndexChanged.connect(self._on_bg_front_changed)
        self._combo_bg_front.setFixedWidth(62)

        _row1 = QHBoxLayout()
        _row1.setSpacing(4)
        _row1.addWidget(self._card_scr1, 1)
        bv.addLayout(_row1)
        bv.addWidget(self._card_scr2)

        front_row = QHBoxLayout()
        front_row.addWidget(QLabel("Devant:"))
        front_row.addWidget(self._combo_bg_front)
        front_row.addStretch()
        bv.addLayout(front_row)

        # Large-map info row (hidden until grid > screen)
        self._large_map_row = QWidget()
        lm_row = QHBoxLayout(self._large_map_row)
        lm_row.setContentsMargins(0, 0, 0, 0)
        lm_row.setSpacing(6)
        self._lbl_tile_budget = QLabel("")
        self._lbl_tile_budget.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        lm_row.addWidget(self._lbl_tile_budget)
        lm_row.addStretch()
        self._large_map_row.setVisible(False)
        bv.addWidget(self._large_map_row)

        # ── Chunk Map SCR1 (Track A — assembled large map) ────────────────
        grp_chunk = QGroupBox(tr("level.chunk_map_title"))
        grp_chunk.setToolTip(tr("level.chunk_tt"))
        ckv = QVBoxLayout(grp_chunk)
        ckv.setSpacing(4)
        ck_size_row = QHBoxLayout()
        ck_size_row.addWidget(QLabel(tr("level.chunk_rows")))
        self._spin_chunk_rows = QSpinBox()
        self._spin_chunk_rows.setRange(1, 8)
        self._spin_chunk_rows.setValue(1)
        self._spin_chunk_rows.setFixedWidth(40)
        ck_size_row.addWidget(self._spin_chunk_rows)
        ck_size_row.addWidget(QLabel(tr("level.chunk_cols")))
        self._spin_chunk_cols = QSpinBox()
        self._spin_chunk_cols.setRange(1, 8)
        self._spin_chunk_cols.setValue(1)
        self._spin_chunk_cols.setFixedWidth(40)
        ck_size_row.addWidget(self._spin_chunk_cols)
        ck_size_row.addStretch()
        ckv.addLayout(ck_size_row)
        self._tbl_chunk_grid = QTableWidget(1, 1)
        self._tbl_chunk_grid.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._tbl_chunk_grid.verticalHeader().setVisible(False)
        self._tbl_chunk_grid.horizontalHeader().setVisible(False)
        self._tbl_chunk_grid.setMaximumHeight(120)
        self._tbl_chunk_grid.setToolTip(tr("level.chunk_tt"))
        ckv.addWidget(self._tbl_chunk_grid)
        self._grp_chunk = grp_chunk
        bv.addWidget(grp_chunk)
        self._spin_chunk_rows.valueChanged.connect(self._on_chunk_grid_size_changed)
        self._spin_chunk_cols.valueChanged.connect(self._on_chunk_grid_size_changed)
        self._rebuild_chunk_grid_table(1, 1)

        bv.addStretch()
        left_tabs.addTab(tab_bg, tr("level.tab_bg"))

        root.addWidget(left_tabs)

        # ---- CENTER: canvas ----------------------------------------------
        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(4)

        # Control bar (size + limits)
        ctrl_row = QHBoxLayout()

        ctrl_row.addWidget(QLabel(tr("level.size_label")))
        self._spin_gw = QSpinBox()
        self._spin_gw.setRange(1, 255)
        self._spin_gw.setValue(_SCREEN_W)
        self._spin_gw.setToolTip(tr("level.size_w_tt"))
        self._spin_gw.setFixedWidth(46)
        self._spin_gw.valueChanged.connect(self._on_size_changed)
        ctrl_row.addWidget(self._spin_gw)
        ctrl_row.addWidget(QLabel("×"))
        self._spin_gh = QSpinBox()
        self._spin_gh.setRange(1, 255)
        self._spin_gh.setValue(_SCREEN_H)
        self._spin_gh.setToolTip(tr("level.size_h_tt"))
        self._spin_gh.setFixedWidth(46)
        self._spin_gh.valueChanged.connect(self._on_size_changed)
        ctrl_row.addWidget(self._spin_gh)
        ctrl_row.addWidget(QLabel(tr("level.size_tiles")))
        self._lbl_size_limits = QLabel("")
        self._lbl_size_limits.setToolTip(tr("level.size_limits_tt"))
        self._lbl_size_limits.setStyleSheet("color: #888; font-size: 10px;")
        ctrl_row.addWidget(self._lbl_size_limits)

        self._btn_fit_bg = QPushButton(tr("level.fit_bg"))
        self._btn_fit_bg.setToolTip(tr("level.fit_bg_tt"))
        self._btn_fit_bg.setEnabled(False)
        self._btn_fit_bg.clicked.connect(self._fit_to_bg)
        ctrl_row.addWidget(self._btn_fit_bg)
        cv.addLayout(ctrl_row)

        view_group = QGroupBox(tr("level.group_view"))
        view_group_l = QVBoxLayout(view_group)
        # Zoom row
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(QLabel(tr("level.zoom")))
        for z in _ZOOM_STEPS:
            btn = QPushButton(f"×{z}")
            btn.setFixedWidth(32)
            btn.setCheckable(True)
            btn.setChecked(z == _DEFAULT_ZOOM)
            btn.clicked.connect(lambda _checked, _z=z: self._set_zoom(_z))
            zoom_row.addWidget(btn)
            setattr(self, f"_zoom_btn_{z}", btn)
        zoom_row.addStretch()
        self._btn_undo = QPushButton(tr("level.undo"))
        self._btn_undo.setFixedWidth(60)
        self._btn_undo.setToolTip(tr("level.undo_tt"))
        self._btn_undo.setEnabled(False)
        self._btn_undo.clicked.connect(self._undo)
        zoom_row.addWidget(self._btn_undo)
        self._btn_redo = QPushButton(tr("level.redo"))
        self._btn_redo.setFixedWidth(60)
        self._btn_redo.setToolTip(tr("level.redo_tt"))
        self._btn_redo.setEnabled(False)
        self._btn_redo.clicked.connect(self._redo)
        zoom_row.addWidget(self._btn_redo)
        QShortcut(QKeySequence("Ctrl+Z"), self, self._undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, self._redo)
        view_group_l.addLayout(zoom_row)
        cv.addWidget(view_group)

        scene_group = QGroupBox(tr("level.group_scene"))
        scene_group_l = QVBoxLayout(scene_group)
        # Scene tools row
        tools_row = QHBoxLayout()
        tools_row.addWidget(QLabel(tr("level.scene_tools")))

        def _tool_btn(label_key: str, tip_key: str, mode: str, width: int = 72) -> QPushButton:
            btn = QPushButton(tr(label_key))
            btn.setCheckable(True)
            btn.setFixedWidth(width)
            btn.setToolTip(tr(tip_key))
            btn.clicked.connect(lambda _checked=False, _mode=mode: self._set_scene_tool(_mode))
            return btn

        self._btn_tool_select = _tool_btn("level.tool_select", "level.tool_select_tt", "select", 68)
        tools_row.addWidget(self._btn_tool_select)
        self._btn_tool_entity = _tool_btn("level.tool_entity", "level.tool_entity_tt", "entity", 74)
        tools_row.addWidget(self._btn_tool_entity)
        self._btn_tool_wave = _tool_btn("level.tool_wave", "level.tool_wave_tt", "wave", 68)
        tools_row.addWidget(self._btn_tool_wave)
        self._btn_tool_collision = _tool_btn("level.tool_collision", "level.tool_collision_tt", "collision", 82)
        tools_row.addWidget(self._btn_tool_collision)
        self._btn_tool_region = _tool_btn("level.tool_region", "level.tool_region_tt", "region", 72)
        tools_row.addWidget(self._btn_tool_region)
        self._btn_tool_path = _tool_btn("level.tool_path", "level.tool_path_tt", "path", 70)
        tools_row.addWidget(self._btn_tool_path)
        self._btn_tool_camera = _tool_btn("level.tool_camera", "level.tool_camera_tt", "camera", 72)
        tools_row.addWidget(self._btn_tool_camera)
        tools_row.addStretch()
        scene_group_l.addLayout(tools_row)

        overlays_row = QHBoxLayout()
        overlays_row.addWidget(QLabel(tr("level.scene_overlays")))
        self._chk_overlay_col = QCheckBox(tr("level.show_col_map"))
        self._chk_overlay_col.setToolTip(tr("level.show_col_map_tt"))
        self._chk_overlay_col.setChecked(self._show_col_map)
        self._chk_overlay_col.toggled.connect(self._on_col_map_toggled)
        overlays_row.addWidget(self._chk_overlay_col)
        self._chk_overlay_regions = QCheckBox(tr("level.show_regions"))
        self._chk_overlay_regions.setToolTip(tr("level.show_regions_tt"))
        self._chk_overlay_regions.setChecked(self._show_regions)
        self._chk_overlay_regions.toggled.connect(self._on_regions_toggled)
        overlays_row.addWidget(self._chk_overlay_regions)
        self._chk_overlay_triggers = QCheckBox(tr("level.show_triggers"))
        self._chk_overlay_triggers.setToolTip(tr("level.show_triggers_tt"))
        self._chk_overlay_triggers.setChecked(self._show_triggers)
        self._chk_overlay_triggers.toggled.connect(self._on_triggers_toggled)
        overlays_row.addWidget(self._chk_overlay_triggers)
        self._chk_overlay_paths = QCheckBox(tr("level.show_paths"))
        self._chk_overlay_paths.setToolTip(tr("level.show_paths_tt"))
        self._chk_overlay_paths.setChecked(self._show_paths)
        self._chk_overlay_paths.toggled.connect(self._on_paths_toggled)
        overlays_row.addWidget(self._chk_overlay_paths)
        self._chk_overlay_waves = QCheckBox(tr("level.show_waves"))
        self._chk_overlay_waves.setToolTip(tr("level.show_waves_tt"))
        self._chk_overlay_waves.setChecked(self._show_waves)
        self._chk_overlay_waves.toggled.connect(self._on_waves_toggled)
        overlays_row.addWidget(self._chk_overlay_waves)
        self._chk_overlay_cam = QCheckBox(tr("level.show_cam"))
        self._chk_overlay_cam.setToolTip(tr("level.show_cam_tt"))
        self._chk_overlay_cam.setChecked(self._show_cam)
        self._chk_overlay_cam.toggled.connect(self._on_cam_toggled)
        overlays_row.addWidget(self._chk_overlay_cam)
        self._chk_overlay_bezel = QCheckBox(tr("level.show_bezel"))
        self._chk_overlay_bezel.setToolTip(tr("level.show_bezel_tt"))
        self._chk_overlay_bezel.setChecked(self._show_bezel)
        self._chk_overlay_bezel.toggled.connect(self._on_bezel_toggled)
        overlays_row.addWidget(self._chk_overlay_bezel)
        overlays_row.addStretch()
        self._btn_dup_selection = QPushButton(tr("level.duplicate_selection"))
        self._btn_dup_selection.setToolTip(tr("level.duplicate_selection_tt"))
        self._btn_dup_selection.clicked.connect(self._duplicate_active_selection)
        overlays_row.addWidget(self._btn_dup_selection)
        scene_group_l.addLayout(overlays_row)
        cv.addWidget(scene_group)

        self._lbl_scene_tool_hint = QLabel("")
        self._lbl_scene_tool_hint.setWordWrap(True)
        self._lbl_scene_tool_hint.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        cv.addWidget(self._lbl_scene_tool_hint)

        collision_row = QHBoxLayout()
        self._lbl_collision_brush = QLabel(tr("level.collision_brush"))
        collision_row.addWidget(self._lbl_collision_brush)
        self._combo_collision_brush = QComboBox()
        self._combo_collision_brush.setToolTip(tr("level.collision_brush_tt"))
        self._combo_collision_brush.currentIndexChanged.connect(self._on_collision_brush_changed)
        collision_row.addWidget(self._combo_collision_brush, 1)
        collision_row.addWidget(QLabel(tr("level.collision_mode")))
        self._combo_collision_mode = QComboBox()
        self._combo_collision_mode.setToolTip(tr("level.collision_mode_tt"))
        for mode_key, label_key in _COLLISION_EDIT_MODES:
            self._combo_collision_mode.addItem(tr(label_key), mode_key)
        self._combo_collision_mode.currentIndexChanged.connect(self._on_collision_edit_mode_changed)
        collision_row.addWidget(self._combo_collision_mode)
        self._combo_collision_import_bg = QComboBox()
        self._combo_collision_import_bg.setToolTip(tr("level.collision_import_bg_tt"))
        self._combo_collision_import_bg.addItem(tr("level.collision_import_bg_auto"), "auto")
        self._combo_collision_import_bg.addItem(tr("level.collision_import_bg_scr1"), "scr1")
        self._combo_collision_import_bg.addItem(tr("level.collision_import_bg_scr2"), "scr2")
        collision_row.addWidget(self._combo_collision_import_bg)
        self._btn_collision_import_bg = QPushButton(tr("level.collision_import_bg"))
        self._btn_collision_import_bg.setToolTip(tr("level.collision_import_bg_btn_tt"))
        self._btn_collision_import_bg.clicked.connect(self._import_collision_from_bg)
        collision_row.addWidget(self._btn_collision_import_bg)
        self._lbl_collision_brush_hint = QLabel(tr("level.collision_brush_hint"))
        self._lbl_collision_brush_hint.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        collision_row.addWidget(self._lbl_collision_brush_hint, 2)
        cv.addLayout(collision_row)
        self._lbl_collision_source = QLabel("")
        self._lbl_collision_source.setWordWrap(True)
        self._lbl_collision_source.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        cv.addWidget(self._lbl_collision_source)

        # Canvas
        self._scroll = QScrollArea()
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setWidgetResizable(False)
        self._canvas = _LevelCanvas(self)
        self._canvas.entity_selected.connect(self._on_entity_selected)
        self._canvas.entity_placed.connect(self._on_entity_placed)
        self._canvas.coord_changed.connect(self._update_coords)
        self._scroll.setWidget(self._canvas)
        cv.addWidget(self._scroll, 1)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        self._lbl_status = QLabel(tr("level.no_scene"))
        self._lbl_status.setStyleSheet("color: gray; font-style: italic;")
        status_row.addWidget(self._lbl_status, 1)
        self._lbl_coords = QLabel("")
        self._lbl_coords.setStyleSheet("color: #9aa3ad; font-size: 10px; font-family: monospace;")
        self._lbl_coords.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self._lbl_coords)
        cv.addLayout(status_row)

        # ---- RIGHT: tabbed panel -----------------------------------------
        right = QWidget()
        right.setMinimumWidth(215)
        self._right_tabs = QTabWidget()
        self._right_tabs.setTabPosition(QTabWidget.TabPosition.North)

        # --- Tab 0: Entity props ------------------------------------------
        tab_ent = QWidget()
        ev = QVBoxLayout(tab_ent)
        ev.setContentsMargins(4, 4, 4, 4)
        ev.setSpacing(4)

        self._lbl_ent_type = QLabel(tr("level.no_entity"))
        self._lbl_ent_type.setWordWrap(True)
        ev.addWidget(self._lbl_ent_type)

        def _spin_row(parent_layout, label: str, lo: int, hi: int, attr: str) -> QSpinBox:
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            spin = QSpinBox()
            spin.setRange(lo, hi)
            spin.valueChanged.connect(lambda v, _a=attr: self._on_prop_changed(_a, v))
            row.addWidget(spin)
            parent_layout.addLayout(row)
            return spin

        self._spin_x    = _spin_row(ev, tr("level.prop_x"),    0, 255, "x")
        self._spin_y    = _spin_row(ev, tr("level.prop_y"),    0, 255, "y")
        self._spin_data = _spin_row(ev, tr("level.prop_data"), 0, 255, "data")
        self._spin_x.setToolTip(tr("level.prop_x_tt"))
        self._spin_y.setToolTip(tr("level.prop_y_tt"))
        self._spin_data.setToolTip(tr("level.prop_data_tt"))

        preset_row = QHBoxLayout()
        self._lbl_ent_preset = QLabel(tr("level.prop_preset"))
        self._lbl_ent_preset.setVisible(False)
        preset_row.addWidget(self._lbl_ent_preset)
        self._combo_ent_preset = QComboBox()
        self._combo_ent_preset.setVisible(False)
        self._combo_ent_preset.currentIndexChanged.connect(self._on_ent_preset_changed)
        preset_row.addWidget(self._combo_ent_preset, 1)
        ev.addLayout(preset_row)

        self._lbl_ent_runtime = QLabel("")
        self._lbl_ent_runtime.setWordWrap(True)
        self._lbl_ent_runtime.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        ev.addWidget(self._lbl_ent_runtime)

        self._btn_delete = QPushButton(tr("level.delete"))
        self._btn_delete.clicked.connect(self._delete_selected)
        ev.addWidget(self._btn_delete)

        # ---- Instance props (direction / behavior / path) ----
        grp_inst = QGroupBox(tr("level.grp_instance_props"))
        grp_inst.setFlat(True)
        iv = QVBoxLayout(grp_inst)
        iv.setSpacing(3)
        iv.setContentsMargins(4, 4, 4, 4)

        def _combo_row(parent_layout, label: str, items: list, tooltip: str, attr: str) -> QComboBox:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(88)
            row.addWidget(lbl)
            cb = QComboBox()
            for it in items:
                cb.addItem(it)
            cb.setToolTip(tooltip)
            cb.currentIndexChanged.connect(lambda v, _a=attr: self._on_inst_prop_changed(_a, v))
            row.addWidget(cb, 1)
            parent_layout.addLayout(row)
            return cb

        # Per-entity role override (optional). First item = "(type default)" which
        # clears the override and falls back to the sprite-type role. Following
        # items map to ROLE_VALUES from core.entity_roles.
        role_row = QHBoxLayout()
        role_lbl = QLabel(tr("level.prop_ent_role"))
        role_lbl.setFixedWidth(88)
        role_row.addWidget(role_lbl)
        self._combo_ent_role = QComboBox()
        self._combo_ent_role.addItem(tr("level.prop_ent_role_default"), "")
        for r in _ROLES:
            self._combo_ent_role.addItem(f"{_ROLE_SHORT[r]} {r}", r)
        self._combo_ent_role.setToolTip(tr("level.prop_ent_role_tt"))
        self._combo_ent_role.currentIndexChanged.connect(self._on_ent_role_changed)
        role_row.addWidget(self._combo_ent_role, 1)
        iv.addLayout(role_row)

        self._combo_ent_dir = _combo_row(
            iv, tr("level.prop_direction"),
            [tr("level.dir_right"), tr("level.dir_left"),
             tr("level.dir_up"),    tr("level.dir_down")],
            tr("level.prop_direction_tt"), "direction")

        self._combo_ent_behavior = _combo_row(
            iv, tr("level.prop_behavior"),
            [tr("level.beh_patrol"), tr("level.beh_chase"),
             tr("level.beh_fixed"),  tr("level.beh_random")],
            tr("level.prop_behavior_tt"), "behavior")

        path_row = QHBoxLayout()
        path_lbl = QLabel(tr("level.prop_path"))
        path_lbl.setFixedWidth(88)
        path_row.addWidget(path_lbl)
        self._combo_ent_path = QComboBox()
        self._combo_ent_path.addItem(tr("level.prop_path_none"))
        self._combo_ent_path.setToolTip(tr("level.prop_path_tt"))
        self._combo_ent_path.currentIndexChanged.connect(self._on_ent_path_changed)
        path_row.addWidget(self._combo_ent_path, 1)
        iv.addLayout(path_row)
        path_tools_row = QHBoxLayout()
        path_tools_row.addSpacing(88)
        self._btn_ent_path_edit = QPushButton(tr("level.prop_path_edit_btn"))
        self._btn_ent_path_edit.setToolTip(tr("level.prop_path_edit_btn_tt"))
        self._btn_ent_path_edit.clicked.connect(self._edit_selected_entity_path)
        path_tools_row.addWidget(self._btn_ent_path_edit)
        path_tools_row.addStretch()
        iv.addLayout(path_tools_row)
        self._chk_ent_clamp_map = QCheckBox(tr("level.prop_clamp_map"))
        self._chk_ent_clamp_map.setToolTip(tr("level.prop_clamp_map_tt"))
        self._chk_ent_clamp_map.toggled.connect(self._on_ent_clamp_map_toggled)
        iv.addWidget(self._chk_ent_clamp_map)
        self._chk_ent_clamp_camera = QCheckBox(tr("level.prop_clamp_camera"))
        self._chk_ent_clamp_camera.setToolTip(tr("level.prop_clamp_camera_tt"))
        self._chk_ent_clamp_camera.toggled.connect(self._on_ent_clamp_camera_toggled)
        iv.addWidget(self._chk_ent_clamp_camera)
        self._chk_ent_allow_ledge_fall = QCheckBox(tr("level.prop_allow_ledge_fall"))
        self._chk_ent_allow_ledge_fall.setToolTip(tr("level.prop_allow_ledge_fall_tt"))
        self._chk_ent_allow_ledge_fall.toggled.connect(self._on_ent_allow_ledge_fall_toggled)
        iv.addWidget(self._chk_ent_allow_ledge_fall)
        self._chk_ent_respawn = QCheckBox(tr("level.prop_respawn"))
        self._chk_ent_respawn.setToolTip(tr("level.prop_respawn_tt"))
        self._chk_ent_respawn.toggled.connect(self._on_ent_respawn_toggled)
        iv.addWidget(self._chk_ent_respawn)
        self._lbl_ent_path_status = QLabel(tr("level.prop_path_help_none_sel"))
        self._lbl_ent_path_status.setWordWrap(True)
        self._lbl_ent_path_status.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        iv.addWidget(self._lbl_ent_path_status)

        ev.addWidget(grp_inst)

        # ---- AI parameter spinboxes (shown/hidden based on behavior) ----
        self._grp_ai_params = QGroupBox(tr("level.grp_ai_params"))
        self._grp_ai_params.setFlat(True)
        aiv = QVBoxLayout(self._grp_ai_params)
        aiv.setSpacing(3)
        aiv.setContentsMargins(4, 4, 4, 4)

        def _spin_row_ai(parent_layout, label: str, lo: int, hi: int, default: int, tooltip: str, attr: str):
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(100)
            row.addWidget(lbl)
            sp = QSpinBox()
            sp.setRange(lo, hi)
            sp.setValue(default)
            sp.setToolTip(tooltip)
            sp.valueChanged.connect(lambda v, _a=attr: self._on_ai_param_changed(_a, v))
            row.addWidget(sp, 1)
            parent_layout.addLayout(row)
            return sp

        self._spin_ai_speed = _spin_row_ai(
            aiv, tr("level.prop_ai_speed"), 1, 255, 1,
            tr("level.prop_ai_speed_tt"), "ai_speed")
        self._row_ai_range = QWidget()
        rr = QVBoxLayout(self._row_ai_range)
        rr.setContentsMargins(0, 0, 0, 0)
        rr.setSpacing(3)
        self._spin_ai_range = _spin_row_ai(
            rr, tr("level.prop_ai_range"), 0, 255, 10,
            tr("level.prop_ai_range_tt"), "ai_range")
        self._spin_ai_lose_range = _spin_row_ai(
            rr, tr("level.prop_ai_lose_range"), 0, 255, 16,
            tr("level.prop_ai_lose_range_tt"), "ai_lose_range")
        aiv.addWidget(self._row_ai_range)
        self._row_ai_change = QWidget()
        rc = QVBoxLayout(self._row_ai_change)
        rc.setContentsMargins(0, 0, 0, 0)
        rc.setSpacing(3)
        self._spin_ai_change_every = _spin_row_ai(
            rc, tr("level.prop_ai_change_every"), 1, 255, 60,
            tr("level.prop_ai_change_every_tt"), "ai_change_every")
        aiv.addWidget(self._row_ai_change)
        self._grp_ai_params.setVisible(False)
        ev.addWidget(self._grp_ai_params)

        # ---- Shooting group (shown/hidden based on role: player or enemy) ----
        self._grp_shooting = QGroupBox(tr("level.grp_shooting"))
        self._grp_shooting.setFlat(True)
        shv = QVBoxLayout(self._grp_shooting)
        shv.setSpacing(3)
        shv.setContentsMargins(4, 4, 4, 4)

        # -- Player: shoot button combo --
        self._row_shoot_button = QWidget()
        _rb_layout = QHBoxLayout(self._row_shoot_button)
        _rb_layout.setContentsMargins(0, 0, 0, 0)
        _rb_lbl = QLabel(tr("level.shoot_button"))
        _rb_lbl.setFixedWidth(100)
        _rb_layout.addWidget(_rb_lbl)
        self._combo_shoot_button = QComboBox()
        for _txt, _dat in [
            (tr("level.shoot_btn_none"), "none"),
            (tr("level.shoot_btn_a"),    "A"),
            (tr("level.shoot_btn_b"),    "B"),
            (tr("level.shoot_btn_ab"),   "AB"),
        ]:
            self._combo_shoot_button.addItem(_txt, _dat)
        self._combo_shoot_button.setToolTip(tr("level.shoot_button_tt"))
        self._combo_shoot_button.currentIndexChanged.connect(self._on_shoot_button_changed)
        _rb_layout.addWidget(self._combo_shoot_button, 1)
        shv.addWidget(self._row_shoot_button)

        # -- Enemy: can-shoot checkbox --
        self._chk_can_shoot = QCheckBox(tr("level.shoot_can_shoot"))
        self._chk_can_shoot.setToolTip(tr("level.shoot_can_shoot_tt"))
        self._chk_can_shoot.toggled.connect(self._on_can_shoot_toggled)
        shv.addWidget(self._chk_can_shoot)

        # -- Shared sub-panel (visible when shooting is active) --
        self._row_shoot_params = QWidget()
        _sp_layout = QVBoxLayout(self._row_shoot_params)
        _sp_layout.setContentsMargins(0, 0, 0, 0)
        _sp_layout.setSpacing(3)

        def _shoot_row(label: str, tooltip: str, attr: str,
                       lo: int, hi: int, default: int) -> QSpinBox:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(100)
            row.addWidget(lbl)
            sp = QSpinBox()
            sp.setRange(lo, hi)
            sp.setValue(default)
            sp.setToolTip(tooltip)
            sp.valueChanged.connect(lambda v, _a=attr: self._on_shoot_param_changed(_a, v))
            row.addWidget(sp, 1)
            _sp_layout.addLayout(row)
            return sp

        # Bullet sprite combo
        _bs_row = QHBoxLayout()
        _bs_lbl = QLabel(tr("level.shoot_bullet_sprite"))
        _bs_lbl.setFixedWidth(100)
        _bs_row.addWidget(_bs_lbl)
        self._combo_bullet_sprite = QComboBox()
        self._combo_bullet_sprite.setToolTip(tr("level.shoot_bullet_sprite_tt"))
        self._combo_bullet_sprite.currentIndexChanged.connect(self._on_bullet_sprite_changed)
        _bs_row.addWidget(self._combo_bullet_sprite, 1)
        _sp_layout.addLayout(_bs_row)

        self._spin_bullet_speed_x = _shoot_row(
            tr("level.shoot_speed_x"), tr("level.shoot_speed_x_tt"), "speed_x", -8, 8, -2)
        self._spin_bullet_speed_y = _shoot_row(
            tr("level.shoot_speed_y"), tr("level.shoot_speed_y_tt"), "speed_y", -8, 8, 0)
        self._spin_bullet_fire_rate = _shoot_row(
            tr("level.shoot_fire_rate"), tr("level.shoot_fire_rate_tt"), "fire_rate", 1, 255, 40)

        # Enemy-only: fire condition + range
        self._row_fire_condition = QWidget()
        _fc_layout = QHBoxLayout(self._row_fire_condition)
        _fc_layout.setContentsMargins(0, 0, 0, 0)
        _fc_lbl = QLabel(tr("level.shoot_fire_condition"))
        _fc_lbl.setFixedWidth(100)
        _fc_layout.addWidget(_fc_lbl)
        self._combo_fire_condition = QComboBox()
        for _txt, _val in [
            (tr("level.shoot_cond_always"), 0),
            (tr("level.shoot_cond_range"),  1),
            (tr("level.shoot_cond_facing"), 2),
        ]:
            self._combo_fire_condition.addItem(_txt, _val)
        self._combo_fire_condition.setToolTip(tr("level.shoot_fire_condition_tt"))
        self._combo_fire_condition.currentIndexChanged.connect(self._on_fire_condition_changed)
        _fc_layout.addWidget(self._combo_fire_condition, 1)
        _sp_layout.addWidget(self._row_fire_condition)

        self._row_fire_range = QWidget()
        _fr_layout = QVBoxLayout(self._row_fire_range)
        _fr_layout.setContentsMargins(0, 0, 0, 0)
        self._spin_fire_range = _shoot_row(
            tr("level.shoot_fire_range"), tr("level.shoot_fire_range_tt"), "fire_range", 0, 255, 0)
        _sp_layout.addWidget(self._row_fire_range)

        # Note label
        self._lbl_shoot_type_note = QLabel(tr("level.shoot_type_note"))
        self._lbl_shoot_type_note.setWordWrap(True)
        self._lbl_shoot_type_note.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        _sp_layout.addWidget(self._lbl_shoot_type_note)

        shv.addWidget(self._row_shoot_params)
        self._grp_shooting.setVisible(False)
        ev.addWidget(self._grp_shooting)

        grp_spr = QGroupBox(tr("level.sprite_info_group"))
        sv = QVBoxLayout(grp_spr)
        sv.setSpacing(2)
        self._lbl_hitbox = QLabel("")
        self._lbl_hitbox.setWordWrap(True)
        self._lbl_hitbox.setStyleSheet("font-size: 10px; color: #bbb;")
        sv.addWidget(self._lbl_hitbox)
        self._lbl_props = QLabel("")
        self._lbl_props.setWordWrap(True)
        self._lbl_props.setStyleSheet("font-size: 10px; color: #bbb;")
        sv.addWidget(self._lbl_props)
        ev.addWidget(grp_spr)

        # ---- Entity type preset actions ----
        self._grp_etype_actions = QGroupBox(tr("level.etype_group"))
        self._grp_etype_actions.setFlat(True)
        etv = QVBoxLayout(self._grp_etype_actions)
        etv.setSpacing(3)
        etv.setContentsMargins(4, 4, 4, 4)

        self._lbl_etype_current = QLabel("")
        self._lbl_etype_current.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        self._lbl_etype_current.setWordWrap(True)
        etv.addWidget(self._lbl_etype_current)

        _et_btn_row = QHBoxLayout()
        self._btn_save_as_type = QPushButton(tr("level.etype_save_as"))
        self._btn_save_as_type.setToolTip(tr("level.etype_save_as_tt"))
        self._btn_save_as_type.clicked.connect(self._on_save_as_type)
        _et_btn_row.addWidget(self._btn_save_as_type)
        self._btn_apply_type = QPushButton(tr("level.etype_apply"))
        self._btn_apply_type.setToolTip(tr("level.etype_apply_tt"))
        self._btn_apply_type.clicked.connect(self._on_apply_type)
        _et_btn_row.addWidget(self._btn_apply_type)
        etv.addLayout(_et_btn_row)
        _btn_goto_globals = QPushButton(tr("level.etype_goto_globals"))
        _btn_goto_globals.setToolTip(tr("level.etype_goto_globals_tt"))
        _btn_goto_globals.setStyleSheet("color: #6ab0de; border: none; text-align: left; padding: 2px 0;")
        _btn_goto_globals.setCursor(Qt.CursorShape.PointingHandCursor)
        _btn_goto_globals.clicked.connect(lambda: self.open_globals_tab_requested.emit())
        etv.addWidget(_btn_goto_globals)
        self._grp_etype_actions.setVisible(False)
        ev.addWidget(self._grp_etype_actions)

        ev.addStretch()

        self._set_props_enabled(False)
        self._tab_entity = tab_ent
        self._right_tabs.addTab(tab_ent, tr("level.tab_entity"))

        # --- Tab 0b: Placement rules -------------------------------------
        tab_rules = QWidget()
        rlv = QVBoxLayout(tab_rules)
        rlv.setContentsMargins(4, 4, 4, 4)
        rlv.setSpacing(6)

        lbl_rules_intro = QLabel(tr("level.rules_intro"))
        lbl_rules_intro.setWordWrap(True)
        lbl_rules_intro.setStyleSheet(
            "color: #c8c8c8; font-size: 10px; background: #20242a; "
            "border: 1px solid #3a3f46; padding: 6px;"
        )
        rlv.addWidget(lbl_rules_intro)

        grp_rules = QGroupBox(tr("level.rules_group"))
        rv = QVBoxLayout(grp_rules)
        rv.setSpacing(6)

        row_lock = QHBoxLayout()
        self._chk_rule_lock_y = QCheckBox(tr("level.rules_lock_y"))
        self._chk_rule_lock_y.setToolTip(tr("level.rules_lock_y_tt"))
        self._chk_rule_lock_y.toggled.connect(self._on_rules_changed)
        row_lock.addWidget(self._chk_rule_lock_y)
        self._spin_rule_lock_y = QSpinBox()
        self._spin_rule_lock_y.setRange(0, 255)
        self._spin_rule_lock_y.setToolTip(tr("level.rules_lock_y_tt"))
        self._spin_rule_lock_y.valueChanged.connect(self._on_rules_changed)
        row_lock.addWidget(self._spin_rule_lock_y)
        row_lock.addStretch()
        rv.addLayout(row_lock)

        row_band = QHBoxLayout()
        self._chk_rule_ground_band = QCheckBox(tr("level.rules_ground_band"))
        self._chk_rule_ground_band.setToolTip(tr("level.rules_ground_band_tt"))
        self._chk_rule_ground_band.toggled.connect(self._on_rules_changed)
        row_band.addWidget(self._chk_rule_ground_band)
        row_band.addWidget(QLabel(tr("level.rules_ground_min")))
        self._spin_rule_ground_min = QSpinBox()
        self._spin_rule_ground_min.setRange(0, 255)
        self._spin_rule_ground_min.valueChanged.connect(self._on_rules_changed)
        row_band.addWidget(self._spin_rule_ground_min)
        row_band.addWidget(QLabel(tr("level.rules_ground_max")))
        self._spin_rule_ground_max = QSpinBox()
        self._spin_rule_ground_max.setRange(0, 255)
        self._spin_rule_ground_max.valueChanged.connect(self._on_rules_changed)
        row_band.addWidget(self._spin_rule_ground_max)
        row_band.addStretch()
        rv.addLayout(row_band)

        row_m = QHBoxLayout()
        self._chk_rule_mirror = QCheckBox(tr("level.rules_mirror"))
        self._chk_rule_mirror.setToolTip(tr("level.rules_mirror_tt"))
        self._chk_rule_mirror.toggled.connect(self._on_rules_changed)
        row_m.addWidget(self._chk_rule_mirror)
        row_m.addWidget(QLabel(tr("level.rules_mirror_axis")))
        self._spin_rule_mirror_axis = QSpinBox()
        self._spin_rule_mirror_axis.setRange(0, 255)
        self._spin_rule_mirror_axis.valueChanged.connect(self._on_rules_changed)
        row_m.addWidget(self._spin_rule_mirror_axis)
        row_m.addStretch()
        rv.addLayout(row_m)

        self._chk_rule_apply_waves = QCheckBox(tr("level.rules_apply_waves"))
        self._chk_rule_apply_waves.setToolTip(tr("level.rules_apply_waves_tt"))
        self._chk_rule_apply_waves.toggled.connect(self._on_rules_changed)
        rv.addWidget(self._chk_rule_apply_waves)

        hazard_sep = QLabel(tr("level.rules_hazards_group"))
        hazard_sep.setStyleSheet("color: #8fa4b8; font-size: 11px;")
        rv.addWidget(hazard_sep)

        row_hazard = QHBoxLayout()
        row_hazard.addWidget(QLabel(tr("level.rules_hazard_damage")))
        self._spin_rule_hazard_damage = QSpinBox()
        self._spin_rule_hazard_damage.setRange(0, 255)
        self._spin_rule_hazard_damage.setToolTip(tr("level.rules_hazard_damage_tt"))
        self._spin_rule_hazard_damage.valueChanged.connect(self._on_rules_changed)
        row_hazard.addWidget(self._spin_rule_hazard_damage)
        row_hazard.addWidget(QLabel(tr("level.rules_fire_damage")))
        self._spin_rule_fire_damage = QSpinBox()
        self._spin_rule_fire_damage.setRange(0, 255)
        self._spin_rule_fire_damage.setToolTip(tr("level.rules_fire_damage_tt"))
        self._spin_rule_fire_damage.valueChanged.connect(self._on_rules_changed)
        row_hazard.addWidget(self._spin_rule_fire_damage)
        row_hazard.addStretch()
        rv.addLayout(row_hazard)

        row_void = QHBoxLayout()
        self._chk_rule_void_instant = QCheckBox(tr("level.rules_void_instant"))
        self._chk_rule_void_instant.setToolTip(tr("level.rules_void_instant_tt"))
        self._chk_rule_void_instant.toggled.connect(self._on_rules_changed)
        row_void.addWidget(self._chk_rule_void_instant)
        row_void.addWidget(QLabel(tr("level.rules_void_damage")))
        self._spin_rule_void_damage = QSpinBox()
        self._spin_rule_void_damage.setRange(0, 255)
        self._spin_rule_void_damage.setToolTip(tr("level.rules_void_damage_tt"))
        self._spin_rule_void_damage.valueChanged.connect(self._on_rules_changed)
        row_void.addWidget(self._spin_rule_void_damage)
        row_void.addStretch()
        rv.addLayout(row_void)

        row_inv = QHBoxLayout()
        row_inv.addWidget(QLabel(tr("level.rules_hazard_invul")))
        self._spin_rule_hazard_invul = QSpinBox()
        self._spin_rule_hazard_invul.setRange(0, 255)
        self._spin_rule_hazard_invul.setToolTip(tr("level.rules_hazard_invul_tt"))
        self._spin_rule_hazard_invul.valueChanged.connect(self._on_rules_changed)
        row_inv.addWidget(self._spin_rule_hazard_invul)
        row_inv.addStretch()
        rv.addLayout(row_inv)

        row_spring = QHBoxLayout()
        row_spring.addWidget(QLabel(tr("level.rules_spring_force")))
        self._spin_rule_spring_force = QSpinBox()
        self._spin_rule_spring_force.setRange(0, 127)
        self._spin_rule_spring_force.setToolTip(tr("level.rules_spring_force_tt"))
        self._spin_rule_spring_force.valueChanged.connect(self._on_rules_changed)
        row_spring.addWidget(self._spin_rule_spring_force)
        row_spring.addWidget(QLabel(tr("level.rules_spring_dir")))
        self._combo_rule_spring_dir = QComboBox()
        self._combo_rule_spring_dir.setToolTip(tr("level.rules_spring_dir_tt"))
        self._combo_rule_spring_dir.addItem(tr("level.rules_spring_dir_up"), "up")
        self._combo_rule_spring_dir.addItem(tr("level.rules_spring_dir_down"), "down")
        self._combo_rule_spring_dir.addItem(tr("level.rules_spring_dir_left"), "left")
        self._combo_rule_spring_dir.addItem(tr("level.rules_spring_dir_right"), "right")
        self._combo_rule_spring_dir.addItem(tr("level.rules_spring_dir_opposite_touch"), "opposite_touch")
        self._combo_rule_spring_dir.currentIndexChanged.connect(self._on_rules_changed)
        row_spring.addWidget(self._combo_rule_spring_dir)
        row_spring.addStretch()
        rv.addLayout(row_spring)

        row_conveyor = QHBoxLayout()
        row_conveyor.addWidget(QLabel(tr("level.rules_conveyor_speed")))
        self._spin_rule_conveyor_speed = QSpinBox()
        self._spin_rule_conveyor_speed.setRange(1, 8)
        self._spin_rule_conveyor_speed.setToolTip(tr("level.rules_conveyor_speed_tt"))
        self._spin_rule_conveyor_speed.valueChanged.connect(self._on_rules_changed)
        row_conveyor.addWidget(self._spin_rule_conveyor_speed)
        row_conveyor.addStretch()
        rv.addLayout(row_conveyor)

        row_ice = QHBoxLayout()
        row_ice.addWidget(QLabel(tr("level.rules_ice_friction")))
        self._spin_rule_ice_friction = QSpinBox()
        self._spin_rule_ice_friction.setRange(0, 255)
        self._spin_rule_ice_friction.setToolTip(tr("level.rules_ice_friction_tt"))
        self._spin_rule_ice_friction.valueChanged.connect(self._on_rules_changed)
        row_ice.addWidget(self._spin_rule_ice_friction)
        row_ice.addStretch()
        rv.addLayout(row_ice)

        row_water = QHBoxLayout()
        row_water.addWidget(QLabel(tr("level.rules_water_drag")))
        self._spin_rule_water_drag = QSpinBox()
        self._spin_rule_water_drag.setRange(1, 8)
        self._spin_rule_water_drag.setToolTip(tr("level.rules_water_drag_tt"))
        self._spin_rule_water_drag.valueChanged.connect(self._on_rules_changed)
        row_water.addWidget(self._spin_rule_water_drag)
        row_water.addWidget(QLabel(tr("level.rules_water_damage")))
        self._spin_rule_water_damage = QSpinBox()
        self._spin_rule_water_damage.setRange(0, 255)
        self._spin_rule_water_damage.setToolTip(tr("level.rules_water_damage_tt"))
        self._spin_rule_water_damage.valueChanged.connect(self._on_rules_changed)
        row_water.addWidget(self._spin_rule_water_damage)
        row_water.addStretch()
        rv.addLayout(row_water)

        row_zone_force = QHBoxLayout()
        row_zone_force.addWidget(QLabel(tr("level.rules_zone_force")))
        self._spin_rule_zone_force = QSpinBox()
        self._spin_rule_zone_force.setRange(1, 8)
        self._spin_rule_zone_force.setToolTip(tr("level.rules_zone_force_tt"))
        self._spin_rule_zone_force.valueChanged.connect(self._on_rules_changed)
        row_zone_force.addWidget(self._spin_rule_zone_force)
        row_zone_force.addStretch()
        rv.addLayout(row_zone_force)

        row_ladder = QHBoxLayout()
        self._chk_rule_ladder_top_exit = QCheckBox(tr("level.rules_ladder_top_exit"))
        self._chk_rule_ladder_top_exit.setToolTip(tr("level.rules_ladder_top_exit_tt"))
        self._chk_rule_ladder_top_exit.toggled.connect(self._on_rules_changed)
        row_ladder.addWidget(self._chk_rule_ladder_top_exit)
        self._chk_rule_ladder_top_solid = QCheckBox(tr("level.rules_ladder_top_solid"))
        self._chk_rule_ladder_top_solid.setToolTip(tr("level.rules_ladder_top_solid_tt"))
        self._chk_rule_ladder_top_solid.toggled.connect(self._on_rules_changed)
        row_ladder.addWidget(self._chk_rule_ladder_top_solid)
        self._chk_rule_ladder_side_move = QCheckBox(tr("level.rules_ladder_side_move"))
        self._chk_rule_ladder_side_move.setToolTip(tr("level.rules_ladder_side_move_tt"))
        self._chk_rule_ladder_side_move.toggled.connect(self._on_rules_changed)
        row_ladder.addWidget(self._chk_rule_ladder_side_move)
        row_ladder.addStretch()
        rv.addLayout(row_ladder)

        hint = QLabel(tr("level.rules_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #aaa; font-size: 10px;")
        rv.addWidget(hint)

        rlv.addWidget(grp_rules)
        rlv.addStretch()
        self._right_tabs.addTab(tab_rules, tr("level.tab_rules"))

        # --- Tab 0c: HUD -------------------------------------------------
        tab_hud = QWidget()
        htv = QVBoxLayout(tab_hud)
        htv.setContentsMargins(0, 0, 0, 0)
        htv.setSpacing(0)
        hud_scroll = QScrollArea()
        hud_scroll.setWidgetResizable(True)
        hud_wrap = QWidget()
        huv = QVBoxLayout(hud_wrap)
        huv.setContentsMargins(4, 4, 4, 4)
        huv.setSpacing(6)

        hud_intro = QLabel(tr("level.hud_tab_intro"))
        hud_intro.setWordWrap(True)
        hud_intro.setStyleSheet(
            "color: #c8c8c8; font-size: 10px; background: #20242a; "
            "border: 1px solid #3a3f46; padding: 6px;"
        )
        huv.addWidget(hud_intro)

        grp_hud = QGroupBox(tr("level.rules_hud_group"))
        ghv = QVBoxLayout(grp_hud)
        ghv.setSpacing(6)

        # Master switch — when unchecked ngpng_hud is not compiled at all.
        self._chk_rule_hud_enabled = QCheckBox(tr("level.rules_hud_enabled"))
        self._chk_rule_hud_enabled.setToolTip(tr("level.rules_hud_enabled_tt"))
        self._chk_rule_hud_enabled.toggled.connect(self._on_rules_changed)
        self._chk_rule_hud_enabled.toggled.connect(self._on_hud_enabled_toggled)
        ghv.addWidget(self._chk_rule_hud_enabled)

        row_hud = QHBoxLayout()
        self._chk_rule_hud_hp = QCheckBox(tr("level.rules_hud_hp"))
        self._chk_rule_hud_hp.setToolTip(tr("level.rules_hud_hp_tt"))
        self._chk_rule_hud_hp.toggled.connect(self._on_rules_changed)
        row_hud.addWidget(self._chk_rule_hud_hp)
        self._chk_rule_hud_score = QCheckBox(tr("level.rules_hud_score"))
        self._chk_rule_hud_score.setToolTip(tr("level.rules_hud_score_tt"))
        self._chk_rule_hud_score.toggled.connect(self._on_rules_changed)
        row_hud.addWidget(self._chk_rule_hud_score)
        self._chk_rule_hud_collect = QCheckBox(tr("level.rules_hud_collect"))
        self._chk_rule_hud_collect.setToolTip(tr("level.rules_hud_collect_tt"))
        self._chk_rule_hud_collect.toggled.connect(self._on_rules_changed)
        row_hud.addWidget(self._chk_rule_hud_collect)
        self._chk_rule_hud_timer = QCheckBox(tr("level.rules_hud_timer"))
        self._chk_rule_hud_timer.setToolTip(tr("level.rules_hud_timer_tt"))
        self._chk_rule_hud_timer.toggled.connect(self._on_rules_changed)
        row_hud.addWidget(self._chk_rule_hud_timer)
        self._chk_rule_hud_lives = QCheckBox(tr("level.rules_hud_lives"))
        self._chk_rule_hud_lives.setToolTip(tr("level.rules_hud_lives_tt"))
        self._chk_rule_hud_lives.toggled.connect(self._on_rules_changed)
        row_hud.addWidget(self._chk_rule_hud_lives)
        row_hud.addStretch()
        ghv.addLayout(row_hud)

        row_hud_mode = QHBoxLayout()
        row_hud_mode.addWidget(QLabel(tr("level.rules_hud_pos")))
        self._combo_rule_hud_pos = QComboBox()
        self._combo_rule_hud_pos.addItem(tr("level.rules_hud_pos_top"), "top")
        self._combo_rule_hud_pos.addItem(tr("level.rules_hud_pos_bottom"), "bottom")
        self._combo_rule_hud_pos.setToolTip(tr("level.rules_hud_pos_tt"))
        self._combo_rule_hud_pos.currentIndexChanged.connect(self._on_rules_changed)
        row_hud_mode.addWidget(self._combo_rule_hud_pos)
        row_hud_mode.addWidget(QLabel(tr("level.rules_hud_font")))
        self._combo_rule_hud_font = QComboBox()
        self._combo_rule_hud_font.addItem(tr("level.rules_hud_font_system"), "system")
        self._combo_rule_hud_font.addItem(tr("level.rules_hud_font_custom"), "custom")
        self._combo_rule_hud_font.setToolTip(tr("level.rules_hud_font_tt"))
        self._combo_rule_hud_font.currentIndexChanged.connect(self._on_rules_changed)
        row_hud_mode.addWidget(self._combo_rule_hud_font)
        row_hud_mode.addStretch()
        ghv.addLayout(row_hud_mode)

        grp_hud_fixed = QGroupBox(tr("level.hud_fixed_group"))
        fhv = QVBoxLayout(grp_hud_fixed)
        fhv.setSpacing(4)
        row_hud_fixed = QHBoxLayout()
        row_hud_fixed.addWidget(QLabel(tr("level.hud_fixed_plane")))
        self._combo_rule_hud_fixed_plane = QComboBox()
        self._combo_rule_hud_fixed_plane.addItem(tr("level.hud_fixed_plane_none"), "none")
        self._combo_rule_hud_fixed_plane.addItem(tr("level.hud_fixed_plane_scr1"), "scr1")
        self._combo_rule_hud_fixed_plane.addItem(tr("level.hud_fixed_plane_scr2"), "scr2")
        self._combo_rule_hud_fixed_plane.setToolTip(tr("level.hud_fixed_plane_tt"))
        self._combo_rule_hud_fixed_plane.currentIndexChanged.connect(self._on_rules_changed)
        row_hud_fixed.addWidget(self._combo_rule_hud_fixed_plane, 1)
        row_hud_fixed.addStretch()
        fhv.addLayout(row_hud_fixed)
        lbl_hud_fixed = QLabel(tr("level.hud_fixed_hint"))
        lbl_hud_fixed.setWordWrap(True)
        lbl_hud_fixed.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        fhv.addWidget(lbl_hud_fixed)
        ghv.addWidget(grp_hud_fixed)

        self._grp_rule_hud_system = QGroupBox(tr("level.rules_hud_system_group"))
        hsv = QVBoxLayout(self._grp_rule_hud_system)
        hsv.setSpacing(4)
        hsv.setContentsMargins(4, 4, 4, 4)

        hud_system_hint = QLabel(tr("level.rules_hud_system_hint"))
        hud_system_hint.setWordWrap(True)
        hud_system_hint.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        hsv.addWidget(hud_system_hint)

        row_hud_style = QHBoxLayout()
        row_hud_style.addWidget(QLabel(tr("level.rules_hud_text_color")))
        self._combo_rule_hud_text_color = QComboBox()
        for key, label_key in _HUD_COLOR_PRESETS:
            self._combo_rule_hud_text_color.addItem(tr(label_key), key)
        self._combo_rule_hud_text_color.currentIndexChanged.connect(self._on_rules_changed)
        row_hud_style.addWidget(self._combo_rule_hud_text_color, 1)
        row_hud_style.addWidget(QLabel(tr("level.rules_hud_style")))
        self._combo_rule_hud_style = QComboBox()
        for key, label_key in _HUD_STYLE_PRESETS:
            self._combo_rule_hud_style.addItem(tr(label_key), key)
        self._combo_rule_hud_style.currentIndexChanged.connect(self._on_rules_changed)
        row_hud_style.addWidget(self._combo_rule_hud_style, 1)
        hsv.addLayout(row_hud_style)

        row_hud_band = QHBoxLayout()
        row_hud_band.addWidget(QLabel(tr("level.rules_hud_band_color")))
        self._combo_rule_hud_band_color = QComboBox()
        for key, label_key in _HUD_COLOR_PRESETS:
            self._combo_rule_hud_band_color.addItem(tr(label_key), key)
        self._combo_rule_hud_band_color.currentIndexChanged.connect(self._on_rules_changed)
        row_hud_band.addWidget(self._combo_rule_hud_band_color, 1)
        row_hud_band.addWidget(QLabel(tr("level.rules_hud_band_rows")))
        self._spin_rule_hud_band_rows = QSpinBox()
        self._spin_rule_hud_band_rows.setRange(1, 3)
        self._spin_rule_hud_band_rows.valueChanged.connect(self._on_rules_changed)
        row_hud_band.addWidget(self._spin_rule_hud_band_rows)
        row_hud_band.addStretch()
        hsv.addLayout(row_hud_band)

        row_hud_digits = QHBoxLayout()
        row_hud_digits.addWidget(QLabel(tr("level.rules_hud_digits_hp")))
        self._spin_rule_hud_digits_hp = QSpinBox()
        self._spin_rule_hud_digits_hp.setRange(1, 6)
        self._spin_rule_hud_digits_hp.valueChanged.connect(self._on_rules_changed)
        row_hud_digits.addWidget(self._spin_rule_hud_digits_hp)
        row_hud_digits.addWidget(QLabel(tr("level.rules_hud_digits_score")))
        self._spin_rule_hud_digits_score = QSpinBox()
        self._spin_rule_hud_digits_score.setRange(1, 6)
        self._spin_rule_hud_digits_score.valueChanged.connect(self._on_rules_changed)
        row_hud_digits.addWidget(self._spin_rule_hud_digits_score)
        row_hud_digits.addWidget(QLabel(tr("level.rules_hud_digits_collect")))
        self._spin_rule_hud_digits_collect = QSpinBox()
        self._spin_rule_hud_digits_collect.setRange(1, 6)
        self._spin_rule_hud_digits_collect.valueChanged.connect(self._on_rules_changed)
        row_hud_digits.addWidget(self._spin_rule_hud_digits_collect)
        row_hud_digits.addStretch()
        hsv.addLayout(row_hud_digits)

        row_hud_digits2 = QHBoxLayout()
        row_hud_digits2.addWidget(QLabel(tr("level.rules_hud_digits_timer")))
        self._spin_rule_hud_digits_timer = QSpinBox()
        self._spin_rule_hud_digits_timer.setRange(1, 6)
        self._spin_rule_hud_digits_timer.valueChanged.connect(self._on_rules_changed)
        row_hud_digits2.addWidget(self._spin_rule_hud_digits_timer)
        row_hud_digits2.addWidget(QLabel(tr("level.rules_hud_digits_lives")))
        self._spin_rule_hud_digits_lives = QSpinBox()
        self._spin_rule_hud_digits_lives.setRange(1, 6)
        self._spin_rule_hud_digits_lives.valueChanged.connect(self._on_rules_changed)
        row_hud_digits2.addWidget(self._spin_rule_hud_digits_lives)
        row_hud_digits2.addWidget(QLabel(tr("level.rules_hud_digits_continues")))
        self._spin_rule_hud_digits_continues = QSpinBox()
        self._spin_rule_hud_digits_continues.setRange(1, 6)
        self._spin_rule_hud_digits_continues.valueChanged.connect(self._on_rules_changed)
        row_hud_digits2.addWidget(self._spin_rule_hud_digits_continues)
        row_hud_digits2.addStretch()
        hsv.addLayout(row_hud_digits2)

        ghv.addWidget(self._grp_rule_hud_system)

        self._grp_rule_hud_custom = QGroupBox(tr("level.rules_hud_custom_group"))
        hcv = QVBoxLayout(self._grp_rule_hud_custom)
        hcv.setSpacing(4)
        hcv.setContentsMargins(4, 4, 4, 4)

        hud_custom_hint = QLabel(tr("level.rules_hud_custom_hint"))
        hud_custom_hint.setWordWrap(True)
        hud_custom_hint.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        hcv.addWidget(hud_custom_hint)

        font_digits_title = QLabel(tr("level.hud_font_digits_group"))
        font_digits_title.setStyleSheet("color: #8fa4b8; font-size: 11px;")
        hcv.addWidget(font_digits_title)

        self._combo_hud_font_digits: list[QComboBox] = []
        for base_digit in range(0, 10, 2):
            font_row = QHBoxLayout()
            for digit in (base_digit, base_digit + 1):
                font_row.addWidget(QLabel(tr("level.hud_font_digit_label", d=digit)))
                combo_digit = QComboBox()
                combo_digit.currentIndexChanged.connect(lambda _v, d=digit: self._on_hud_font_digit_changed(d))
                font_row.addWidget(combo_digit, 1)
                self._combo_hud_font_digits.append(combo_digit)
            hcv.addLayout(font_row)

        hud_custom_ctrl = QHBoxLayout()
        self._btn_hud_widget_add = QPushButton(tr("level.hud_widget_add"))
        self._btn_hud_widget_add.clicked.connect(self._add_hud_widget)
        hud_custom_ctrl.addWidget(self._btn_hud_widget_add)
        self._btn_hud_widget_del = QPushButton(tr("level.hud_widget_del"))
        self._btn_hud_widget_del.clicked.connect(self._remove_hud_widget)
        self._btn_hud_widget_del.setEnabled(False)
        hud_custom_ctrl.addWidget(self._btn_hud_widget_del)
        hud_custom_ctrl.addStretch()
        hcv.addLayout(hud_custom_ctrl)

        self._hud_widget_list = QListWidget()
        self._hud_widget_list.setMinimumHeight(150)
        self._hud_widget_list.currentRowChanged.connect(self._on_hud_widget_selected)
        hcv.addWidget(self._hud_widget_list)

        hud_name_row = QHBoxLayout()
        hud_name_row.addWidget(QLabel(tr("level.hud_widget_name")))
        self._edit_hud_widget_name = QLineEdit()
        self._edit_hud_widget_name.textChanged.connect(self._on_hud_widget_prop_changed)
        hud_name_row.addWidget(self._edit_hud_widget_name, 1)
        hcv.addLayout(hud_name_row)

        hud_kind_row = QHBoxLayout()
        hud_kind_row.addWidget(QLabel(tr("level.hud_widget_kind")))
        self._combo_hud_widget_kind = QComboBox()
        for key, label_key in _HUD_WIDGET_KINDS:
            self._combo_hud_widget_kind.addItem(tr(label_key), key)
        self._combo_hud_widget_kind.currentIndexChanged.connect(self._on_hud_widget_prop_changed)
        hud_kind_row.addWidget(self._combo_hud_widget_kind, 1)
        hud_kind_row.addWidget(QLabel(tr("level.hud_widget_metric")))
        self._combo_hud_widget_metric = QComboBox()
        for key, label_key in _HUD_WIDGET_METRICS:
            self._combo_hud_widget_metric.addItem(tr(label_key), key)
        self._combo_hud_widget_metric.currentIndexChanged.connect(self._on_hud_widget_prop_changed)
        hud_kind_row.addWidget(self._combo_hud_widget_metric, 1)
        hcv.addLayout(hud_kind_row)

        hud_pos_row = QHBoxLayout()
        hud_pos_row.addWidget(QLabel(tr("level.hud_widget_x")))
        self._spin_hud_widget_x = QSpinBox()
        self._spin_hud_widget_x.setRange(0, _SCREEN_W - 1)
        self._spin_hud_widget_x.valueChanged.connect(self._on_hud_widget_prop_changed)
        hud_pos_row.addWidget(self._spin_hud_widget_x)
        hud_pos_row.addWidget(QLabel(tr("level.hud_widget_y")))
        self._spin_hud_widget_y = QSpinBox()
        self._spin_hud_widget_y.setRange(0, _SCREEN_H - 1)
        self._spin_hud_widget_y.valueChanged.connect(self._on_hud_widget_prop_changed)
        hud_pos_row.addWidget(self._spin_hud_widget_y)
        hud_pos_row.addStretch()
        hcv.addLayout(hud_pos_row)

        hud_type_row = QHBoxLayout()
        self._lbl_hud_widget_type = QLabel(tr("level.hud_widget_type"))
        hud_type_row.addWidget(self._lbl_hud_widget_type)
        self._combo_hud_widget_type = QComboBox()
        self._combo_hud_widget_type.currentIndexChanged.connect(self._on_hud_widget_prop_changed)
        hud_type_row.addWidget(self._combo_hud_widget_type, 1)
        hcv.addLayout(hud_type_row)

        hud_value_row = QHBoxLayout()
        self._lbl_hud_widget_digits = QLabel(tr("level.hud_widget_digits"))
        hud_value_row.addWidget(self._lbl_hud_widget_digits)
        self._spin_hud_widget_digits = QSpinBox()
        self._spin_hud_widget_digits.setRange(1, 6)
        self._spin_hud_widget_digits.valueChanged.connect(self._on_hud_widget_prop_changed)
        hud_value_row.addWidget(self._spin_hud_widget_digits)
        self._chk_hud_widget_zero_pad = QCheckBox(tr("level.hud_widget_zero_pad"))
        self._chk_hud_widget_zero_pad.toggled.connect(self._on_hud_widget_prop_changed)
        hud_value_row.addWidget(self._chk_hud_widget_zero_pad)
        hud_value_row.addStretch()
        hcv.addLayout(hud_value_row)

        self._lbl_hud_widget_runtime = QLabel("")
        self._lbl_hud_widget_runtime.setWordWrap(True)
        self._lbl_hud_widget_runtime.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        hcv.addWidget(self._lbl_hud_widget_runtime)

        ghv.addWidget(self._grp_rule_hud_custom)

        row_goal = QHBoxLayout()
        row_goal.addWidget(QLabel(tr("level.rules_goal_collectibles")))
        self._spin_rule_goal_collectibles = QSpinBox()
        self._spin_rule_goal_collectibles.setRange(0, 999)
        self._spin_rule_goal_collectibles.setToolTip(tr("level.rules_goal_collectibles_tt"))
        self._spin_rule_goal_collectibles.valueChanged.connect(self._on_rules_changed)
        row_goal.addWidget(self._spin_rule_goal_collectibles)
        row_goal.addWidget(QLabel(tr("level.rules_time_limit")))
        self._spin_rule_time_limit = QSpinBox()
        self._spin_rule_time_limit.setRange(0, 9999)
        self._spin_rule_time_limit.setToolTip(tr("level.rules_time_limit_tt"))
        self._spin_rule_time_limit.valueChanged.connect(self._on_rules_changed)
        row_goal.addWidget(self._spin_rule_time_limit)
        row_goal.addWidget(QLabel(tr("level.rules_start_lives")))
        self._spin_rule_start_lives = QSpinBox()
        self._spin_rule_start_lives.setRange(0, 99)
        self._spin_rule_start_lives.setToolTip(tr("level.rules_start_lives_tt"))
        self._spin_rule_start_lives.valueChanged.connect(self._on_rules_changed)
        row_goal.addWidget(self._spin_rule_start_lives)
        row_goal.addWidget(QLabel(tr("level.rules_start_continues")))
        self._spin_rule_start_continues = QSpinBox()
        self._spin_rule_start_continues.setRange(0, 99)
        self._spin_rule_start_continues.setToolTip(tr("level.rules_start_continues_tt"))
        self._spin_rule_start_continues.valueChanged.connect(self._on_rules_changed)
        row_goal.addWidget(self._spin_rule_start_continues)
        row_goal.addWidget(QLabel(tr("level.rules_continue_restore_lives")))
        self._spin_rule_continue_restore_lives = QSpinBox()
        self._spin_rule_continue_restore_lives.setRange(0, 99)
        self._spin_rule_continue_restore_lives.setToolTip(tr("level.rules_continue_restore_lives_tt"))
        self._spin_rule_continue_restore_lives.valueChanged.connect(self._on_rules_changed)
        row_goal.addWidget(self._spin_rule_continue_restore_lives)
        row_goal.addStretch()
        ghv.addLayout(row_goal)

        huv.addWidget(grp_hud)
        huv.addStretch()
        hud_scroll.setWidget(hud_wrap)
        htv.addWidget(hud_scroll)
        self._tab_hud = tab_hud
        self._right_tabs.addTab(tab_hud, tr("level.tab_hud"))

        # --- Tab 1: Wave editor -------------------------------------------
        tab_waves = QWidget()
        wv = QVBoxLayout(tab_waves)
        wv.setContentsMargins(4, 4, 4, 4)
        wv.setSpacing(4)

        waves_split = QSplitter(Qt.Orientation.Vertical)

        waves_top = QWidget()
        wtv = QVBoxLayout(waves_top)
        wtv.setContentsMargins(0, 0, 0, 0)
        wtv.setSpacing(4)

        wave_ctrl = QHBoxLayout()
        self._btn_wave_add = QPushButton(tr("level.wave_add"))
        self._btn_wave_add.clicked.connect(self._add_wave)
        wave_ctrl.addWidget(self._btn_wave_add)
        self._btn_wave_del = QPushButton(tr("level.wave_del"))
        self._btn_wave_del.clicked.connect(self._remove_wave)
        self._btn_wave_del.setEnabled(False)
        wave_ctrl.addWidget(self._btn_wave_del)
        wtv.addLayout(wave_ctrl)

        wave_preset_row = QHBoxLayout()
        wave_preset_row.addWidget(QLabel(tr("level.wave_preset_label")))
        self._combo_wave_preset = QComboBox()
        for key, label_key in _WAVE_PRESETS:
            self._combo_wave_preset.addItem(tr(label_key), key)
        self._combo_wave_preset.setToolTip(tr("level.wave_preset_tt"))
        wave_preset_row.addWidget(self._combo_wave_preset, 1)
        self._btn_wave_add_preset = QPushButton(tr("level.wave_preset_add"))
        self._btn_wave_add_preset.setToolTip(tr("level.wave_preset_add_tt"))
        self._btn_wave_add_preset.clicked.connect(self._add_wave_preset)
        wave_preset_row.addWidget(self._btn_wave_add_preset)
        wtv.addLayout(wave_preset_row)

        self._lbl_wave_preset_hint = QLabel(tr("level.wave_preset_hint"))
        self._lbl_wave_preset_hint.setWordWrap(True)
        self._lbl_wave_preset_hint.setStyleSheet("color: #8f98a3; font-size: 10px;")
        wtv.addWidget(self._lbl_wave_preset_hint)

        self._wave_list = QListWidget()
        self._wave_list.currentRowChanged.connect(self._on_wave_selected)
        wtv.addWidget(self._wave_list, 1)
        _sc = QShortcut(QKeySequence(Qt.Key.Key_Insert), self._wave_list)
        _sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        _sc.activated.connect(self._add_wave)
        _sc2 = QShortcut(QKeySequence(Qt.Key.Key_Delete), self._wave_list)
        _sc2.setContext(Qt.ShortcutContext.WidgetShortcut)
        _sc2.activated.connect(self._remove_wave)
        _sc3 = QShortcut(QKeySequence("Ctrl+D"), self._wave_list)
        _sc3.setContext(Qt.ShortcutContext.WidgetShortcut)
        _sc3.activated.connect(self._dup_wave)

        delay_row = QHBoxLayout()
        delay_row.addWidget(QLabel(tr("level.wave_delay")))
        self._spin_wave_delay = QSpinBox()
        self._spin_wave_delay.setRange(0, 9999)
        self._spin_wave_delay.setToolTip(tr("level.wave_delay_tt"))
        self._spin_wave_delay.valueChanged.connect(self._on_wave_delay_changed)
        self._spin_wave_delay.setEnabled(False)
        delay_row.addWidget(self._spin_wave_delay)
        delay_row.addWidget(QLabel("f"))
        wtv.addLayout(delay_row)
        # Wave spawn X helper — shows suggested map X so enemy enters from off-screen right.
        # Formula: x = floor(delay * speed_x / 8) + screen_w_tiles + margin
        self._lbl_wave_spawn_x = QLabel("")
        self._lbl_wave_spawn_x.setStyleSheet("color: #888; font-size: 10px;")
        self._lbl_wave_spawn_x.setToolTip(
            "X carte suggéré pour que l'ennemi spawne hors de l'écran à droite.\n"
            "Formule : x = delay × speed_x / 8 + 21\n"
            "(speed_x=1, écran=20 tuiles, marge=1)"
        )
        wtv.addWidget(self._lbl_wave_spawn_x)

        self._btn_wave_edit = QPushButton(tr("level.wave_edit_off"))
        self._btn_wave_edit.setCheckable(True)
        self._btn_wave_edit.setToolTip(tr("level.wave_edit_tt"))
        self._btn_wave_edit.toggled.connect(self._on_wave_edit_toggled)
        self._btn_wave_edit.setEnabled(False)
        wtv.addWidget(self._btn_wave_edit)

        waves_bottom = QWidget()
        wbv = QVBoxLayout(waves_bottom)
        wbv.setContentsMargins(0, 0, 0, 0)
        wbv.setSpacing(4)

        wbv.addWidget(QLabel(tr("level.wave_entities")))
        self._wave_ent_list = QListWidget()
        self._wave_ent_list.currentRowChanged.connect(self._on_wave_ent_row_changed)
        wbv.addWidget(self._wave_ent_list, 1)

        self._btn_wave_ent_del = QPushButton(tr("level.wave_ent_del"))
        self._btn_wave_ent_del.clicked.connect(self._delete_wave_entity)
        self._btn_wave_ent_del.setEnabled(False)
        wbv.addWidget(self._btn_wave_ent_del)

        # ---- Random-wave per-entity properties (ngpc_rwave director) --------
        # Shown when an individual wave entity is selected. A rand entry is
        # lifted out of the scripted NgpcWaveEntry table at export time and
        # produces a standalone NgpcRWave director instance at runtime.
        self._wave_ent_rand_box = QGroupBox(tr("level.wave_rand_group"))
        self._wave_ent_rand_box.setEnabled(False)
        _werv = QVBoxLayout(self._wave_ent_rand_box)
        _werv.setContentsMargins(6, 4, 6, 4)
        _werv.setSpacing(4)

        self._chk_wave_ent_rand = QCheckBox(tr("level.wave_rand_toggle"))
        self._chk_wave_ent_rand.setToolTip(tr("level.wave_rand_toggle_tt"))
        self._chk_wave_ent_rand.toggled.connect(self._on_wave_ent_rand_toggled)
        _werv.addWidget(self._chk_wave_ent_rand)

        self._wave_ent_rand_fields = QWidget()
        _werf = QVBoxLayout(self._wave_ent_rand_fields)
        _werf.setContentsMargins(0, 0, 0, 0)
        _werf.setSpacing(4)

        _side_row = QHBoxLayout()
        _side_row.addWidget(QLabel(tr("level.wave_rand_side")))
        self._cb_wave_ent_rand_side = QComboBox()
        self._cb_wave_ent_rand_side.setToolTip(tr("level.wave_rand_side_tt"))
        for _key in ("level.wave_rand_side_right", "level.wave_rand_side_left",
                     "level.wave_rand_side_top",   "level.wave_rand_side_bottom"):
            self._cb_wave_ent_rand_side.addItem(tr(_key))
        self._cb_wave_ent_rand_side.currentIndexChanged.connect(
            self._on_wave_ent_rand_field_changed
        )
        _side_row.addWidget(self._cb_wave_ent_rand_side, 1)
        _werf.addLayout(_side_row)

        _count_row = QHBoxLayout()
        _count_row.addWidget(QLabel(tr("level.wave_rand_count")))
        _count_row.addWidget(QLabel(tr("level.wave_rand_min")))
        self._sb_wave_ent_rand_cmin = QSpinBox()
        self._sb_wave_ent_rand_cmin.setRange(1, 255)
        self._sb_wave_ent_rand_cmin.setToolTip(tr("level.wave_rand_count_tt"))
        self._sb_wave_ent_rand_cmin.valueChanged.connect(
            self._on_wave_ent_rand_field_changed
        )
        _count_row.addWidget(self._sb_wave_ent_rand_cmin)
        _count_row.addWidget(QLabel(tr("level.wave_rand_max")))
        self._sb_wave_ent_rand_cmax = QSpinBox()
        self._sb_wave_ent_rand_cmax.setRange(1, 255)
        self._sb_wave_ent_rand_cmax.setToolTip(tr("level.wave_rand_count_tt"))
        self._sb_wave_ent_rand_cmax.valueChanged.connect(
            self._on_wave_ent_rand_field_changed
        )
        _count_row.addWidget(self._sb_wave_ent_rand_cmax)
        _werf.addLayout(_count_row)

        _ivl_row = QHBoxLayout()
        _ivl_row.addWidget(QLabel(tr("level.wave_rand_interval")))
        self._sb_wave_ent_rand_ivl = QSpinBox()
        self._sb_wave_ent_rand_ivl.setRange(1, 255)
        self._sb_wave_ent_rand_ivl.setToolTip(tr("level.wave_rand_interval_tt"))
        self._sb_wave_ent_rand_ivl.valueChanged.connect(
            self._on_wave_ent_rand_field_changed
        )
        _ivl_row.addWidget(self._sb_wave_ent_rand_ivl)
        _ivl_row.addWidget(QLabel(tr("level.wave_rand_frames")))
        _werf.addLayout(_ivl_row)

        # max_waves: 0 = infinite cycles; N = stop after N waves completed.
        _maxw_row = QHBoxLayout()
        _maxw_row.addWidget(QLabel(tr("level.wave_rand_max_waves")))
        self._sb_wave_ent_rand_maxw = QSpinBox()
        self._sb_wave_ent_rand_maxw.setRange(0, 65535)
        self._sb_wave_ent_rand_maxw.setSpecialValueText(tr("level.wave_rand_max_waves_inf"))
        self._sb_wave_ent_rand_maxw.setToolTip(tr("level.wave_rand_max_waves_tt"))
        self._sb_wave_ent_rand_maxw.valueChanged.connect(
            self._on_wave_ent_rand_field_changed
        )
        _maxw_row.addWidget(self._sb_wave_ent_rand_maxw, 1)
        _werf.addLayout(_maxw_row)

        # spawn_behavior: how enemies act once spawned (PATROL / CHASE / FIXED /
        # RANDOM / FLEE). "legacy" keeps the old data-driven movement for
        # backwards-compatibility with projects that relied on it.
        _beh_row = QHBoxLayout()
        _beh_row.addWidget(QLabel(tr("level.wave_rand_behavior")))
        self._cb_wave_ent_rand_beh = QComboBox()
        for _bkey, _blabel in (
            ("patrol", tr("level.beh_patrol")),
            ("chase",  tr("level.beh_chase")),
            ("fixed",  tr("level.beh_fixed")),
            ("random", tr("level.beh_random")),
            ("legacy", tr("level.wave_rand_behavior_legacy")),
        ):
            self._cb_wave_ent_rand_beh.addItem(_blabel, _bkey)
        self._cb_wave_ent_rand_beh.setToolTip(tr("level.wave_rand_behavior_tt"))
        self._cb_wave_ent_rand_beh.currentIndexChanged.connect(
            self._on_wave_ent_rand_field_changed
        )
        _beh_row.addWidget(self._cb_wave_ent_rand_beh, 1)
        _werf.addLayout(_beh_row)

        # Flags toggles: clamp to map + disable auto CULL_OFFSCREEN.
        self._chk_wave_ent_rand_clamp = QCheckBox(tr("level.wave_rand_clamp_map"))
        self._chk_wave_ent_rand_clamp.setToolTip(tr("level.wave_rand_clamp_map_tt"))
        self._chk_wave_ent_rand_clamp.toggled.connect(
            self._on_wave_ent_rand_field_changed
        )
        _werf.addWidget(self._chk_wave_ent_rand_clamp)

        self._chk_wave_ent_rand_no_cull = QCheckBox(tr("level.wave_rand_no_cull"))
        self._chk_wave_ent_rand_no_cull.setToolTip(tr("level.wave_rand_no_cull_tt"))
        self._chk_wave_ent_rand_no_cull.toggled.connect(
            self._on_wave_ent_rand_field_changed
        )
        _werf.addWidget(self._chk_wave_ent_rand_no_cull)

        self._wave_ent_rand_fields.setVisible(False)
        _werv.addWidget(self._wave_ent_rand_fields)
        wbv.addWidget(self._wave_ent_rand_box)

        self._wave_ent_rand_updating = False

        waves_split.addWidget(waves_top)
        waves_split.addWidget(waves_bottom)
        waves_split.setStretchFactor(0, 1)
        waves_split.setStretchFactor(1, 1)

        settings = QSettings("NGPCraft", "Engine")
        saved = settings.value("level_tab/waves_splitter_state")
        if saved:
            try:
                waves_split.restoreState(saved)
            except Exception:
                pass
        else:
            waves_split.setSizes([520, 260])

        waves_split.splitterMoved.connect(
            lambda _pos, _idx, _s=waves_split: QSettings("NGPCraft", "Engine").setValue(
                "level_tab/waves_splitter_state", _s.saveState()
            )
        )

        wv.addWidget(waves_split, 1)

        self._tab_waves = tab_waves
        self._right_tabs.addTab(tab_waves, tr("level.tab_waves"))

        # --- Tab 1b: Regions ---------------------------------------------
        tab_regions = QWidget()
        rv = QVBoxLayout(tab_regions)
        rv.setContentsMargins(4, 4, 4, 4)
        rv.setSpacing(4)

        reg_ctrl = QHBoxLayout()
        self._btn_reg_add = QPushButton(tr("level.region_add"))
        self._btn_reg_add.clicked.connect(self._add_region)
        reg_ctrl.addWidget(self._btn_reg_add)
        self._btn_reg_del = QPushButton(tr("level.region_del"))
        self._btn_reg_del.clicked.connect(self._remove_region)
        self._btn_reg_del.setEnabled(False)
        reg_ctrl.addWidget(self._btn_reg_del)
        reg_ctrl.addStretch()
        rv.addLayout(reg_ctrl)

        reg_preset_row = QHBoxLayout()
        reg_preset_row.addWidget(QLabel(tr("level.region_preset_label")))
        self._combo_reg_preset = QComboBox()
        for key, label_key in _REGION_PRESETS:
            self._combo_reg_preset.addItem(tr(label_key), key)
        self._combo_reg_preset.setToolTip(tr("level.region_preset_tt"))
        reg_preset_row.addWidget(self._combo_reg_preset, 1)
        self._btn_reg_add_preset = QPushButton(tr("level.region_preset_add"))
        self._btn_reg_add_preset.setToolTip(tr("level.region_preset_add_tt"))
        self._btn_reg_add_preset.clicked.connect(self._add_region_preset)
        reg_preset_row.addWidget(self._btn_reg_add_preset)
        rv.addLayout(reg_preset_row)

        self._lbl_reg_preset_hint = QLabel(tr("level.region_preset_hint"))
        self._lbl_reg_preset_hint.setWordWrap(True)
        self._lbl_reg_preset_hint.setStyleSheet("color: #8f98a3; font-size: 10px;")
        rv.addWidget(self._lbl_reg_preset_hint)

        self._btn_reg_edit = QPushButton(tr("level.region_edit_off"))
        self._btn_reg_edit.setCheckable(True)
        self._btn_reg_edit.setToolTip(tr("level.region_edit_tt"))
        self._btn_reg_edit.toggled.connect(self._on_region_edit_toggled)
        rv.addWidget(self._btn_reg_edit)

        self._reg_list = QListWidget()
        self._reg_list.currentRowChanged.connect(self._on_region_selected)
        rv.addWidget(self._reg_list, 1)
        _sc = QShortcut(QKeySequence(Qt.Key.Key_Insert), self._reg_list)
        _sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        _sc.activated.connect(self._add_region)
        _sc2 = QShortcut(QKeySequence(Qt.Key.Key_Delete), self._reg_list)
        _sc2.setContext(Qt.ShortcutContext.WidgetShortcut)
        _sc2.activated.connect(self._remove_region)

        grp_reg = QGroupBox(tr("level.region_props_group"))
        rpv = QVBoxLayout(grp_reg)
        rpv.setSpacing(4)
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(tr("level.region_name")))
        self._edit_reg_name = QLineEdit()
        self._edit_reg_name.textChanged.connect(self._on_region_prop_changed)
        name_row.addWidget(self._edit_reg_name, 1)
        rpv.addLayout(name_row)

        kind_row = QHBoxLayout()
        kind_row.addWidget(QLabel(tr("level.region_kind")))
        self._combo_reg_kind = QComboBox()
        for k, lk in (("zone", "level.region_kind.zone"),
                      ("no_spawn", "level.region_kind.no_spawn"),
                      ("danger_zone", "level.region_kind.danger_zone"),
                      ("checkpoint", "level.region_kind.checkpoint"),
                      ("camera_lock", "level.region_kind.camera_lock"),
                      ("exit_goal", "level.region_kind.exit_goal"),
                      ("spawn", "level.region_kind.spawn"),
                      ("attractor", "level.region_kind.attractor"),
                      ("repulsor", "level.region_kind.repulsor"),
                      ("lap_gate", "level.region_kind.lap_gate"),
                      ("race_waypoint", "level.region_kind.race_waypoint"),
                      ("push_block", "level.region_kind.push_block"),
                      ("card_slot", "level.region_kind.card_slot")):
            self._combo_reg_kind.addItem(tr(lk), k)
        self._combo_reg_kind.currentIndexChanged.connect(self._on_region_prop_changed)
        kind_row.addWidget(self._combo_reg_kind, 1)
        rpv.addLayout(kind_row)

        # Gate index — only visible when kind == "lap_gate"
        gate_row = QHBoxLayout()
        self._lbl_gate_index = QLabel(tr("level.region_gate_index"))
        gate_row.addWidget(self._lbl_gate_index)
        self._spin_reg_gate = QSpinBox()
        self._spin_reg_gate.setRange(0, 31)
        self._spin_reg_gate.setToolTip(tr("level.region_gate_index_tt"))
        self._spin_reg_gate.valueChanged.connect(self._on_region_prop_changed)
        gate_row.addWidget(self._spin_reg_gate)
        gate_row.addStretch()
        rpv.addLayout(gate_row)
        self._row_gate_index = gate_row  # kept for show/hide
        self._lbl_gate_index.hide()
        self._spin_reg_gate.hide()

        # Waypoint index — only visible when kind == "race_waypoint"
        wp_row = QHBoxLayout()
        self._lbl_wp_index = QLabel(tr("level.region_wp_index"))
        wp_row.addWidget(self._lbl_wp_index)
        self._spin_reg_wp = QSpinBox()
        self._spin_reg_wp.setRange(0, 63)
        self._spin_reg_wp.setToolTip(tr("level.region_wp_index_tt"))
        self._spin_reg_wp.valueChanged.connect(self._on_region_prop_changed)
        wp_row.addWidget(self._spin_reg_wp)
        wp_row.addStretch()
        rpv.addLayout(wp_row)
        self._lbl_wp_index.hide()
        self._spin_reg_wp.hide()

        # Slot type — only visible when kind == "card_slot"
        slot_row = QHBoxLayout()
        self._lbl_slot_type = QLabel(tr("level.region_slot_type"))
        slot_row.addWidget(self._lbl_slot_type)
        self._spin_reg_slot_type = QSpinBox()
        self._spin_reg_slot_type.setRange(0, 15)
        self._spin_reg_slot_type.setToolTip(tr("level.region_slot_type_tt"))
        self._spin_reg_slot_type.valueChanged.connect(self._on_region_prop_changed)
        slot_row.addWidget(self._spin_reg_slot_type)
        slot_row.addStretch()
        rpv.addLayout(slot_row)
        self._lbl_slot_type.hide()
        self._spin_reg_slot_type.hide()

        xy_row = QHBoxLayout()
        xy_row.addWidget(QLabel(tr("level.region_x")))
        self._spin_reg_x = QSpinBox()
        self._spin_reg_x.setRange(0, 255)
        self._spin_reg_x.valueChanged.connect(self._on_region_prop_changed)
        xy_row.addWidget(self._spin_reg_x)
        xy_row.addWidget(QLabel(tr("level.region_y")))
        self._spin_reg_y = QSpinBox()
        self._spin_reg_y.setRange(0, 255)
        self._spin_reg_y.valueChanged.connect(self._on_region_prop_changed)
        xy_row.addWidget(self._spin_reg_y)
        rpv.addLayout(xy_row)

        wh_row = QHBoxLayout()
        wh_row.addWidget(QLabel(tr("level.region_w")))
        self._spin_reg_w = QSpinBox()
        self._spin_reg_w.setRange(1, 255)
        self._spin_reg_w.valueChanged.connect(self._on_region_prop_changed)
        wh_row.addWidget(self._spin_reg_w)
        wh_row.addWidget(QLabel(tr("level.region_h")))
        self._spin_reg_h = QSpinBox()
        self._spin_reg_h.setRange(1, 255)
        self._spin_reg_h.valueChanged.connect(self._on_region_prop_changed)
        wh_row.addWidget(self._spin_reg_h)
        rpv.addLayout(wh_row)

        rv.addWidget(grp_reg)
        self._set_region_props_enabled(False)

        self._right_tabs.addTab(tab_regions, tr("level.tab_regions"))

        # --- Tab 1b2: Text Labels -----------------------------------------
        tab_labels = QWidget()
        tab_labels.setToolTip(tr("level.text_label_tt"))
        lbv = QVBoxLayout(tab_labels)
        lbv.setContentsMargins(4, 4, 4, 4)
        lbv.setSpacing(4)

        lbl_ctrl = QHBoxLayout()
        self._btn_lbl_add = QPushButton(tr("level.text_label_add"))
        self._btn_lbl_add.clicked.connect(self._add_text_label)
        lbl_ctrl.addWidget(self._btn_lbl_add)
        self._btn_lbl_del = QPushButton(tr("level.text_label_del"))
        self._btn_lbl_del.clicked.connect(self._remove_text_label)
        self._btn_lbl_del.setEnabled(False)
        lbl_ctrl.addWidget(self._btn_lbl_del)
        lbl_ctrl.addStretch()
        lbv.addLayout(lbl_ctrl)

        self._lbl_list = QListWidget()
        self._lbl_list.currentRowChanged.connect(self._on_text_label_selected)
        lbv.addWidget(self._lbl_list, 1)

        grp_lbl = QGroupBox(tr("level.text_labels_group"))
        lpv = QVBoxLayout(grp_lbl)
        lpv.setSpacing(4)

        lbl_text_row = QHBoxLayout()
        lbl_text_row.addWidget(QLabel(tr("level.text_label_text")))
        self._edit_lbl_text = QLineEdit()
        self._edit_lbl_text.setMaxLength(20)
        self._edit_lbl_text.setPlaceholderText(tr("level.text_label_placeholder"))
        self._edit_lbl_text.textChanged.connect(self._on_text_label_prop_changed)
        lbl_text_row.addWidget(self._edit_lbl_text, 1)
        lpv.addLayout(lbl_text_row)

        lbl_xy_row = QHBoxLayout()
        lbl_xy_row.addWidget(QLabel(tr("level.text_label_x")))
        self._spin_lbl_x = QSpinBox()
        self._spin_lbl_x.setRange(0, 19)
        self._spin_lbl_x.valueChanged.connect(self._on_text_label_prop_changed)
        lbl_xy_row.addWidget(self._spin_lbl_x)
        lbl_xy_row.addWidget(QLabel(tr("level.text_label_y")))
        self._spin_lbl_y = QSpinBox()
        self._spin_lbl_y.setRange(0, 18)
        self._spin_lbl_y.valueChanged.connect(self._on_text_label_prop_changed)
        lbl_xy_row.addWidget(self._spin_lbl_y)
        lpv.addLayout(lbl_xy_row)

        lbl_pal_row = QHBoxLayout()
        lbl_pal_row.addWidget(QLabel(tr("level.text_label_pal")))
        self._spin_lbl_pal = QSpinBox()
        self._spin_lbl_pal.setRange(0, 15)
        self._spin_lbl_pal.valueChanged.connect(self._on_text_label_prop_changed)
        lbl_pal_row.addWidget(self._spin_lbl_pal)
        lbl_pal_row.addWidget(QLabel(tr("level.text_label_plane")))
        self._combo_lbl_plane = QComboBox()
        self._combo_lbl_plane.addItem("SCR1", "scr1")
        self._combo_lbl_plane.addItem("SCR2", "scr2")
        self._combo_lbl_plane.currentIndexChanged.connect(self._on_text_label_prop_changed)
        lbl_pal_row.addWidget(self._combo_lbl_plane)
        lpv.addLayout(lbl_pal_row)

        lbv.addWidget(grp_lbl)
        self._set_text_label_props_enabled(False)

        self._right_tabs.addTab(tab_labels, tr("level.text_labels_group"))

        # --- Tab 1c: Triggers --------------------------------------------
        tab_trig = QWidget()
        tv = QVBoxLayout(tab_trig)
        tv.setContentsMargins(4, 4, 4, 4)
        tv.setSpacing(4)

        trig_ctrl = QHBoxLayout()
        self._btn_trig_add = QPushButton(tr("level.trigger_add"))
        self._btn_trig_add.clicked.connect(self._add_trigger)
        trig_ctrl.addWidget(self._btn_trig_add)
        self._btn_trig_del = QPushButton(tr("level.trigger_del"))
        self._btn_trig_del.clicked.connect(self._remove_trigger)
        self._btn_trig_del.setEnabled(False)
        trig_ctrl.addWidget(self._btn_trig_del)
        trig_ctrl.addSpacing(8)
        trig_ctrl.addWidget(QLabel(tr("level.trigger_preset_label")))
        self._combo_trig_preset = QComboBox()
        for key, label_key in _TRIGGER_PRESETS:
            self._combo_trig_preset.addItem(tr(label_key), key)
        self._combo_trig_preset.setToolTip(tr("level.trigger_preset_tt"))
        trig_ctrl.addWidget(self._combo_trig_preset)
        self._btn_trig_add_preset = QPushButton(tr("level.trigger_preset_add"))
        self._btn_trig_add_preset.setToolTip(tr("level.trigger_preset_add_tt"))
        self._btn_trig_add_preset.clicked.connect(self._add_trigger_preset)
        trig_ctrl.addWidget(self._btn_trig_add_preset)
        trig_ctrl.addStretch()
        tv.addLayout(trig_ctrl)

        trig_quick = QHBoxLayout()
        trig_quick.addWidget(QLabel(tr("level.trigger_quick_region")))
        self._btn_trig_region_enter = QPushButton(tr("level.trigger_quick_enter"))
        self._btn_trig_region_enter.setToolTip(tr("level.trigger_quick_enter_tt"))
        self._btn_trig_region_enter.clicked.connect(lambda: self._add_trigger_from_selected_region("enter_region"))
        trig_quick.addWidget(self._btn_trig_region_enter)
        self._btn_trig_region_leave = QPushButton(tr("level.trigger_quick_leave"))
        self._btn_trig_region_leave.setToolTip(tr("level.trigger_quick_leave_tt"))
        self._btn_trig_region_leave.clicked.connect(lambda: self._add_trigger_from_selected_region("leave_region"))
        trig_quick.addWidget(self._btn_trig_region_leave)
        trig_quick.addStretch()
        tv.addLayout(trig_quick)

        self._trig_list = QListWidget()
        self._trig_list.currentRowChanged.connect(self._on_trigger_selected)
        tv.addWidget(self._trig_list, 1)
        _sc = QShortcut(QKeySequence(Qt.Key.Key_Insert), self._trig_list)
        _sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        _sc.activated.connect(self._add_trigger)
        _sc2 = QShortcut(QKeySequence(Qt.Key.Key_Delete), self._trig_list)
        _sc2.setContext(Qt.ShortcutContext.WidgetShortcut)
        _sc2.activated.connect(self._remove_trigger)
        _sc3 = QShortcut(QKeySequence("Ctrl+D"), self._trig_list)
        _sc3.setContext(Qt.ShortcutContext.WidgetShortcut)
        _sc3.activated.connect(self._duplicate_trigger)

        grp_tr = QGroupBox(tr("level.trigger_props_group"))
        tpp = QVBoxLayout(grp_tr)
        tpp.setSpacing(4)

        # Name row + Duplicate button
        tname_row = QHBoxLayout()
        tname_row.addWidget(QLabel(tr("level.trigger_name")))
        self._edit_trig_name = QLineEdit()
        self._edit_trig_name.textChanged.connect(self._on_trigger_prop_changed)
        tname_row.addWidget(self._edit_trig_name, 1)
        self._btn_trig_dup = QPushButton(tr("level.trigger_dup"))
        self._btn_trig_dup.setToolTip(tr("level.trigger_dup_tt"))
        self._btn_trig_dup.setEnabled(False)
        self._btn_trig_dup.clicked.connect(self._duplicate_trigger)
        tname_row.addWidget(self._btn_trig_dup)
        tpp.addLayout(tname_row)

        # Condition section separator
        _sep_cond = QLabel(tr("level.trigger_sec_condition"))
        _sep_cond.setStyleSheet("color: #667799; font-size: 11px;")
        tpp.addWidget(_sep_cond)

        cond_row = QHBoxLayout()
        cond_row.addWidget(QLabel(tr("level.trigger_cond")))
        self._combo_trig_cond = QComboBox()
        for k, lk in _TRIGGER_CONDS:
            self._combo_trig_cond.addItem(tr(lk), k)
        self._combo_trig_cond.setToolTip(tr("level.trigger_cond_tt"))
        self._combo_trig_cond.currentIndexChanged.connect(self._on_trigger_cond_changed)
        cond_row.addWidget(self._combo_trig_cond, 1)
        tpp.addLayout(cond_row)

        # Region / value row (shown conditionally by cond type)
        target_row = QHBoxLayout()
        self._lbl_trig_region = QLabel(tr("level.trigger_region"))
        target_row.addWidget(self._lbl_trig_region)
        self._combo_trig_region = QComboBox()
        self._combo_trig_region.currentIndexChanged.connect(self._on_trigger_prop_changed)
        target_row.addWidget(self._combo_trig_region, 1)
        self._lbl_trig_value = QLabel(tr("level.trigger_value"))
        target_row.addWidget(self._lbl_trig_value)
        self._spin_trig_value = _ConstantPickerWidget(max_val=65535)
        self._spin_trig_value.setToolTip(tr("level.trigger_value_tt"))
        self._spin_trig_value.value_changed.connect(self._on_trigger_prop_changed)
        target_row.addWidget(self._spin_trig_value)
        # NPC/entity combo — shown for npc_talked_to / entity_contact instead of _spin_trig_value
        self._combo_trig_npc_entity = QComboBox()
        self._combo_trig_npc_entity.setToolTip("Entité NPC/prop cible")
        self._combo_trig_npc_entity.setVisible(False)
        self._combo_trig_npc_entity.currentIndexChanged.connect(self._on_trigger_prop_changed)
        target_row.addWidget(self._combo_trig_npc_entity, 1)
        # Flag/variable index widget (0..7) — shown for flag_set/flag_clear/variable_ge/variable_eq conditions
        # and for set_flag/clear_flag/set_variable/inc_variable actions.
        self._lbl_trig_flag_var = QLabel(tr("level.trigger_flag_var_index"))
        self._lbl_trig_flag_var.setVisible(False)
        target_row.addWidget(self._lbl_trig_flag_var)
        self._spin_trig_flag_var = QSpinBox()
        self._spin_trig_flag_var.setRange(0, 7)
        self._spin_trig_flag_var.setToolTip(tr("level.trigger_flag_var_index_tt"))
        self._spin_trig_flag_var.setVisible(False)
        self._spin_trig_flag_var.valueChanged.connect(self._on_trigger_prop_changed)
        self._spin_trig_flag_var.valueChanged.connect(lambda _: self._update_flag_var_tooltip())
        target_row.addWidget(self._spin_trig_flag_var)
        self._lbl_trig_flag_var_name = QLabel("")
        self._lbl_trig_flag_var_name.setStyleSheet("color: #9aa3ad; font-style: italic;")
        self._lbl_trig_flag_var_name.setVisible(False)
        target_row.addWidget(self._lbl_trig_flag_var_name)
        # Dialogue selector for dialogue_done / choice_result conditions
        self._combo_trig_cond_dialogue = QComboBox()
        self._combo_trig_cond_dialogue.setToolTip(tr("level.trigger_cond_dialogue_tt"))
        self._combo_trig_cond_dialogue.setVisible(False)
        self._combo_trig_cond_dialogue.currentIndexChanged.connect(self._on_trigger_prop_changed)
        target_row.addWidget(self._combo_trig_cond_dialogue, 1)
        # Choice index selector (0/1) for choice_result condition
        from PyQt6.QtWidgets import QSpinBox as _QSpinBox
        self._spin_trig_choice_idx = _QSpinBox()
        self._spin_trig_choice_idx.setRange(0, 1)
        self._spin_trig_choice_idx.setFixedWidth(48)
        self._spin_trig_choice_idx.setToolTip(tr("level.trigger_choice_idx_tt"))
        self._spin_trig_choice_idx.setVisible(False)
        self._spin_trig_choice_idx.valueChanged.connect(self._on_trigger_prop_changed)
        target_row.addWidget(self._spin_trig_choice_idx)
        # Menu selector for menu_result condition
        self._combo_trig_cond_menu = QComboBox()
        self._combo_trig_cond_menu.setToolTip(tr("level.trigger_cond_menu_tt"))
        self._combo_trig_cond_menu.setVisible(False)
        self._combo_trig_cond_menu.currentIndexChanged.connect(self._on_cond_menu_changed)
        target_row.addWidget(self._combo_trig_cond_menu, 1)
        # Menu item selector for menu_result condition
        self._lbl_trig_menu_item = QLabel(tr("level.trigger_menu_item_lbl"))
        self._lbl_trig_menu_item.setVisible(False)
        target_row.addWidget(self._lbl_trig_menu_item)
        self._combo_trig_menu_item = QComboBox()
        self._combo_trig_menu_item.setToolTip(tr("level.trigger_menu_item_tt"))
        self._combo_trig_menu_item.setVisible(False)
        self._combo_trig_menu_item.currentIndexChanged.connect(self._on_trigger_prop_changed)
        target_row.addWidget(self._combo_trig_menu_item)
        # Entity type selector — shown for entity_type_all_dead / count_ge / collected conditions
        self._lbl_trig_entity_type = QLabel("Type :")
        self._lbl_trig_entity_type.setVisible(False)
        target_row.addWidget(self._lbl_trig_entity_type)
        self._combo_trig_entity_type = QComboBox()
        self._combo_trig_entity_type.setToolTip(tr("level.trigger_cond_entity_type_tt"))
        self._combo_trig_entity_type.setVisible(False)
        self._combo_trig_entity_type.currentIndexChanged.connect(self._on_trigger_prop_changed)
        target_row.addWidget(self._combo_trig_entity_type, 1)
        # Custom event selector — shown for on_custom_event condition
        self._lbl_trig_cev = QLabel("Événement :")
        self._lbl_trig_cev.setVisible(False)
        target_row.addWidget(self._lbl_trig_cev)
        self._combo_trig_cev = QComboBox()
        self._combo_trig_cev.setToolTip("Événement personnalisé à écouter (défini dans Globals → Événements).")
        self._combo_trig_cev.setVisible(False)
        self._combo_trig_cev.currentIndexChanged.connect(self._on_trigger_prop_changed)
        target_row.addWidget(self._combo_trig_cev, 1)
        # Item selector — shown for give_item / remove_item actions and player_has_item condition
        self._lbl_trig_item = QLabel("Item :")
        self._lbl_trig_item.setVisible(False)
        target_row.addWidget(self._lbl_trig_item)
        self._combo_trig_item = QComboBox()
        self._combo_trig_item.setToolTip("Item défini dans Globals → Items. Résolu en index à l'export.")
        self._combo_trig_item.setVisible(False)
        self._combo_trig_item.currentIndexChanged.connect(self._on_trigger_prop_changed)
        target_row.addWidget(self._combo_trig_item, 1)
        tpp.addLayout(target_row)

        # Action section separator
        _sep_act = QLabel(tr("level.trigger_sec_action"))
        _sep_act.setStyleSheet("color: #667799; font-size: 11px;")
        tpp.addWidget(_sep_act)

        act_row = QHBoxLayout()
        act_row.addWidget(QLabel(tr("level.trigger_action")))
        self._combo_trig_action = QComboBox()
        for k, lk in (
            ("emit_event",       "level.trigger_action.emit_event"),
            ("play_sfx",         "level.trigger_action.play_sfx"),
            ("start_bgm",        "level.trigger_action.start_bgm"),
            ("stop_bgm",         "level.trigger_action.stop_bgm"),
            ("fade_bgm",         "level.trigger_action.fade_bgm"),
            ("goto_scene",       "level.trigger_action.goto_scene"),
            ("warp_to",          "level.trigger_action.warp_to"),
            ("add_score",        "level.trigger_action.add_score"),
            ("spawn_wave",       "level.trigger_action.spawn_wave"),
            ("pause_scroll",     "level.trigger_action.pause_scroll"),
            ("resume_scroll",    "level.trigger_action.resume_scroll"),
            ("spawn_entity",     "level.trigger_action.spawn_entity"),
            ("set_scroll_speed", "level.trigger_action.set_scroll_speed"),
            ("play_anim",        "level.trigger_action.play_anim"),
            ("force_jump",       "level.trigger_action.force_jump"),
            ("fire_player_shot", "level.trigger_action.fire_player_shot"),
            ("enable_trigger",   "level.trigger_action.enable_trigger"),
            ("disable_trigger",  "level.trigger_action.disable_trigger"),
            ("show_entity",      "level.trigger_action.show_entity"),
            ("hide_entity",      "level.trigger_action.hide_entity"),
            ("move_entity_to",   "level.trigger_action.move_entity_to"),
            ("pause_entity_path","level.trigger_action.pause_entity_path"),
            ("resume_entity_path","level.trigger_action.resume_entity_path"),
            ("screen_shake",     "level.trigger_action.screen_shake"),
            ("set_cam_target",   "level.trigger_action.set_cam_target"),
            ("cycle_player_form","level.trigger_action.cycle_player_form"),
            ("set_player_form",  "level.trigger_action.set_player_form"),
            ("set_checkpoint",   "level.trigger_action.set_checkpoint"),
            ("respawn_player",   "level.trigger_action.respawn_player"),
            ("set_flag",         "level.trigger_action.set_flag"),
            ("clear_flag",       "level.trigger_action.clear_flag"),
            ("set_variable",          "level.trigger_action.set_variable"),
            ("inc_variable",          "level.trigger_action.inc_variable"),
            ("lock_player_input",     "level.trigger_action.lock_player_input"),
            ("unlock_player_input",   "level.trigger_action.unlock_player_input"),
            ("enable_multijump",      "level.trigger_action.enable_multijump"),
            ("disable_multijump",     "level.trigger_action.disable_multijump"),
            ("reset_scene",           "level.trigger_action.reset_scene"),
            ("show_dialogue",         "level.trigger_action.show_dialogue"),
            ("open_menu",             "level.trigger_action.open_menu"),
            ("set_npc_dialogue",      "level.trigger_action.set_npc_dialogue"),
            ("give_item",             "level.trigger_action.give_item"),
            ("remove_item",           "level.trigger_action.remove_item"),
            ("drop_item",             "level.trigger_action.drop_item"),
            ("drop_random_item",      "level.trigger_action.drop_random_item"),
            ("unlock_door",           "level.trigger_action.unlock_door"),
            ("enable_wall_grab",      "level.trigger_action.enable_wall_grab"),
            ("disable_wall_grab",     "level.trigger_action.disable_wall_grab"),
            ("set_gravity_dir",       "level.trigger_action.set_gravity_dir"),
            ("add_resource",          "level.trigger_action.add_resource"),
            ("remove_resource",       "level.trigger_action.remove_resource"),
            ("unlock_ability",        "level.trigger_action.unlock_ability"),
            ("set_quest_stage",       "level.trigger_action.set_quest_stage"),
            ("play_cutscene",         "level.trigger_action.play_cutscene"),
            ("end_game",              "level.trigger_action.end_game"),
            ("dec_variable",    "level.trigger_action.dec_variable"),
            ("add_health",      "level.trigger_action.add_health"),
            ("set_health",      "level.trigger_action.set_health"),
            ("add_lives",       "level.trigger_action.add_lives"),
            ("set_lives",       "level.trigger_action.set_lives"),
            ("destroy_entity",  "level.trigger_action.destroy_entity"),
            ("teleport_player", "level.trigger_action.teleport_player"),
            ("toggle_flag",     "level.trigger_action.toggle_flag"),
            ("set_score",       "level.trigger_action.set_score"),
            ("set_timer",       "level.trigger_action.set_timer"),
            ("pause_timer",     "level.trigger_action.pause_timer"),
            ("resume_timer",    "level.trigger_action.resume_timer"),
            ("fade_out",        "level.trigger_action.fade_out"),
            ("fade_in",         "level.trigger_action.fade_in"),
            ("camera_lock",     "level.trigger_action.camera_lock"),
            ("camera_unlock",   "level.trigger_action.camera_unlock"),
            ("add_combo",       "level.trigger_action.add_combo"),
            ("reset_combo",     "level.trigger_action.reset_combo"),
            ("flash_screen",    "level.trigger_action.flash_screen"),
            ("spawn_at_region", "level.trigger_action.spawn_at_region"),
            ("save_game",       "level.trigger_action.save_game"),
            ("set_bgm_volume",  "level.trigger_action.set_bgm_volume"),
            ("toggle_tile",     "level.trigger_action.toggle_tile"),
            ("flip_sprite_h",   "level.trigger_action.flip_sprite_h"),
            ("flip_sprite_v",   "level.trigger_action.flip_sprite_v"),
            ("init_game_vars",  "level.trigger_action.init_game_vars"),
            ("stop_wave_rand",  "level.trigger_action.stop_wave_rand"),
        ):
            self._combo_trig_action.addItem(tr(lk), k)
        self._combo_trig_action.setToolTip(tr("level.trigger_action_tt"))
        self._combo_trig_action.currentIndexChanged.connect(self._on_trigger_action_changed)
        act_row.addWidget(self._combo_trig_action, 1)
        tpp.addLayout(act_row)

        # Primary param row: event/scene/target combo (shown conditionally)
        params_a_row = QHBoxLayout()
        self._lbl_trig_evt = QLabel(tr("level.trigger_event"))
        params_a_row.addWidget(self._lbl_trig_evt)
        self._spin_trig_event = QSpinBox()
        self._spin_trig_event.setRange(0, 255)
        self._spin_trig_event.setToolTip(tr("level.trigger_event_tt"))
        self._spin_trig_event.valueChanged.connect(self._on_trigger_prop_changed)
        params_a_row.addWidget(self._spin_trig_event)
        self._combo_trig_scene = QComboBox()
        self._combo_trig_scene.setToolTip(tr("level.trigger_scene_tt"))
        self._combo_trig_scene.currentIndexChanged.connect(self._on_trigger_prop_changed)
        self._combo_trig_scene.setVisible(False)
        params_a_row.addWidget(self._combo_trig_scene, 1)
        self._combo_trig_target = QComboBox()
        self._combo_trig_target.setToolTip(tr("level.trigger_target_tt"))
        self._combo_trig_target.currentIndexChanged.connect(self._on_trigger_prop_changed)
        self._combo_trig_target.setVisible(False)
        params_a_row.addWidget(self._combo_trig_target, 1)
        self._combo_trig_entity = QComboBox()
        self._combo_trig_entity.setToolTip(tr("level.trigger_entity_tt"))
        self._combo_trig_entity.currentIndexChanged.connect(self._on_trigger_prop_changed)
        self._combo_trig_entity.setVisible(False)
        params_a_row.addWidget(self._combo_trig_entity, 1)
        self._combo_trig_bgm = QComboBox()
        self._combo_trig_bgm.setToolTip(tr("level.trigger_bgm_tt"))
        self._combo_trig_bgm.currentIndexChanged.connect(self._on_trigger_prop_changed)
        self._combo_trig_bgm.setVisible(False)
        params_a_row.addWidget(self._combo_trig_bgm, 1)
        self._combo_trig_sfx = QComboBox()
        self._combo_trig_sfx.setToolTip(tr("level.trigger_sfx_tt"))
        self._combo_trig_sfx.currentIndexChanged.connect(self._on_trigger_prop_changed)
        self._combo_trig_sfx.setVisible(False)
        params_a_row.addWidget(self._combo_trig_sfx, 1)
        params_a_row.addStretch()
        tpp.addLayout(params_a_row)

        # Secondary param row (shown conditionally when action needs a second param)
        params_b_row = QHBoxLayout()
        self._lbl_trig_param = QLabel(tr("level.trigger_param"))
        params_b_row.addWidget(self._lbl_trig_param)
        self._spin_trig_param = QSpinBox()
        self._spin_trig_param.setRange(0, 255)
        self._spin_trig_param.setToolTip(tr("level.trigger_param_tt"))
        self._spin_trig_param.valueChanged.connect(self._on_trigger_prop_changed)
        params_b_row.addWidget(self._spin_trig_param)
        self._combo_trig_dest_region = QComboBox()
        self._combo_trig_dest_region.setToolTip(tr("level.trigger_dest_region_tt"))
        self._combo_trig_dest_region.currentIndexChanged.connect(self._on_trigger_prop_changed)
        self._combo_trig_dest_region.setVisible(False)
        params_b_row.addWidget(self._combo_trig_dest_region, 1)
        self._combo_trig_dialogue = QComboBox()
        self._combo_trig_dialogue.setToolTip(tr("level.trigger_dialogue_tt"))
        self._combo_trig_dialogue.currentIndexChanged.connect(self._on_trigger_prop_changed)
        self._combo_trig_dialogue.setVisible(False)
        params_b_row.addWidget(self._combo_trig_dialogue, 1)
        # Menu combo for open_menu action
        self._combo_trig_menu = QComboBox()
        self._combo_trig_menu.setToolTip(tr("level.trigger_open_menu_tt"))
        self._combo_trig_menu.currentIndexChanged.connect(self._on_trigger_prop_changed)
        self._combo_trig_menu.setVisible(False)
        params_b_row.addWidget(self._combo_trig_menu, 1)
        self._btn_trig_pick_dest = QPushButton(tr("level.trigger_pick_dest"))
        self._btn_trig_pick_dest.setToolTip(tr("level.trigger_pick_dest_tt"))
        self._btn_trig_pick_dest.setCheckable(True)
        self._btn_trig_pick_dest.setVisible(False)
        self._btn_trig_pick_dest.setFixedWidth(64)
        self._btn_trig_pick_dest.toggled.connect(self._on_pick_dest_toggled)
        params_b_row.addWidget(self._btn_trig_pick_dest)
        self._lbl_trig_dest_tile = QLabel("")
        self._lbl_trig_dest_tile.setToolTip(tr("level.trigger_pick_dest_tt"))
        self._lbl_trig_dest_tile.setVisible(False)
        params_b_row.addWidget(self._lbl_trig_dest_tile)
        params_b_row.addStretch()
        tpp.addLayout(params_b_row)

        # Once row
        once_row = QHBoxLayout()
        self._chk_trig_once = QCheckBox(tr("level.trigger_once"))
        self._chk_trig_once.setToolTip(tr("level.trigger_once_tt"))
        self._chk_trig_once.toggled.connect(self._on_trigger_prop_changed)
        once_row.addWidget(self._chk_trig_once)
        once_row.addStretch()
        tpp.addLayout(once_row)

        # --- AND conditions group (T-14) ----------------------------------
        grp_extra = QGroupBox(tr("level.trigger_extra_conds"))
        grp_extra.setFlat(True)
        grp_extra.setToolTip(tr("level.trigger_extra_conds_tt"))
        ev = QVBoxLayout(grp_extra)
        ev.setContentsMargins(4, 2, 4, 2)
        ev.setSpacing(2)

        self._extra_cond_list = QListWidget()
        self._extra_cond_list.setMaximumHeight(72)
        self._extra_cond_list.currentRowChanged.connect(self._on_extra_cond_sel_changed)
        ev.addWidget(self._extra_cond_list)

        ec_ctrl = QHBoxLayout()
        self._btn_extra_cond_add = QPushButton(tr("level.trigger_extra_cond_add"))
        self._btn_extra_cond_add.setFixedWidth(26)
        self._btn_extra_cond_add.clicked.connect(self._on_extra_cond_add)
        ec_ctrl.addWidget(self._btn_extra_cond_add)
        self._btn_extra_cond_del = QPushButton(tr("level.trigger_extra_cond_del"))
        self._btn_extra_cond_del.setFixedWidth(26)
        self._btn_extra_cond_del.setEnabled(False)
        self._btn_extra_cond_del.clicked.connect(self._on_extra_cond_del)
        ec_ctrl.addWidget(self._btn_extra_cond_del)
        ec_ctrl.addStretch()
        ev.addLayout(ec_ctrl)

        # Inline editor (hidden until a row is selected)
        self._ec_editor = QWidget()
        ec_ed = QHBoxLayout(self._ec_editor)
        ec_ed.setContentsMargins(0, 0, 0, 0)
        ec_ed.setSpacing(4)
        self._combo_ec_cond = QComboBox()
        for _key, _label_key in _TRIGGER_CONDS:
            _lbl = tr(_label_key)
            self._combo_ec_cond.addItem(_lbl, _key)
        self._combo_ec_cond.currentIndexChanged.connect(self._on_extra_cond_changed)
        ec_ed.addWidget(self._combo_ec_cond, 2)

        self._lbl_ec_region = QLabel(tr("level.trigger_region"))
        ec_ed.addWidget(self._lbl_ec_region)
        self._combo_ec_region = QComboBox()
        self._combo_ec_region.currentIndexChanged.connect(self._on_extra_cond_changed)
        ec_ed.addWidget(self._combo_ec_region, 2)

        self._lbl_ec_value = QLabel(tr("level.trigger_value"))
        ec_ed.addWidget(self._lbl_ec_value)
        self._spin_ec_value = QSpinBox()
        self._spin_ec_value.setRange(0, 65535)
        self._spin_ec_value.setFixedWidth(56)
        self._spin_ec_value.valueChanged.connect(self._on_extra_cond_changed)
        ec_ed.addWidget(self._spin_ec_value)

        self._ec_editor.setVisible(False)
        ev.addWidget(self._ec_editor)

        tpp.addWidget(grp_extra)

        # --- OR groups section (TRIG-OR1) ----------------------------------
        grp_or = QGroupBox(tr("level.trigger_or_groups"))
        grp_or.setFlat(True)
        grp_or.setToolTip(tr("level.trigger_or_groups_tt"))
        ov = QVBoxLayout(grp_or)
        ov.setContentsMargins(4, 2, 4, 2)
        ov.setSpacing(2)

        or_hdr = QHBoxLayout()
        or_hdr.addWidget(QLabel(tr("level.trigger_or_group_label")))
        self._combo_or_group = QComboBox()
        self._combo_or_group.currentIndexChanged.connect(self._on_or_group_sel_changed)
        or_hdr.addWidget(self._combo_or_group, 1)
        self._btn_or_group_add = QPushButton(tr("level.trigger_extra_cond_add"))
        self._btn_or_group_add.setFixedWidth(26)
        self._btn_or_group_add.setToolTip(tr("level.trigger_or_group_add_tt"))
        self._btn_or_group_add.clicked.connect(self._on_or_group_add)
        or_hdr.addWidget(self._btn_or_group_add)
        self._btn_or_group_del = QPushButton(tr("level.trigger_extra_cond_del"))
        self._btn_or_group_del.setFixedWidth(26)
        self._btn_or_group_del.setEnabled(False)
        self._btn_or_group_del.clicked.connect(self._on_or_group_del)
        or_hdr.addWidget(self._btn_or_group_del)
        ov.addLayout(or_hdr)

        self._or_cond_list = QListWidget()
        self._or_cond_list.setMaximumHeight(60)
        self._or_cond_list.currentRowChanged.connect(self._on_or_cond_sel_changed)
        ov.addWidget(self._or_cond_list)

        oc_ctrl = QHBoxLayout()
        self._btn_or_cond_add = QPushButton(tr("level.trigger_extra_cond_add"))
        self._btn_or_cond_add.setFixedWidth(26)
        self._btn_or_cond_add.setEnabled(False)
        self._btn_or_cond_add.clicked.connect(self._on_or_cond_add)
        oc_ctrl.addWidget(self._btn_or_cond_add)
        self._btn_or_cond_del = QPushButton(tr("level.trigger_extra_cond_del"))
        self._btn_or_cond_del.setFixedWidth(26)
        self._btn_or_cond_del.setEnabled(False)
        self._btn_or_cond_del.clicked.connect(self._on_or_cond_del)
        oc_ctrl.addWidget(self._btn_or_cond_del)
        oc_ctrl.addStretch()
        ov.addLayout(oc_ctrl)

        self._or_cond_editor = QWidget()
        oe_ed = QHBoxLayout(self._or_cond_editor)
        oe_ed.setContentsMargins(0, 0, 0, 0)
        oe_ed.setSpacing(4)
        self._combo_or_cond = QComboBox()
        for _key, _label_key in _TRIGGER_CONDS:
            self._combo_or_cond.addItem(tr(_label_key), _key)
        self._combo_or_cond.currentIndexChanged.connect(self._on_or_cond_changed)
        oe_ed.addWidget(self._combo_or_cond, 2)
        self._lbl_or_region = QLabel(tr("level.trigger_region"))
        oe_ed.addWidget(self._lbl_or_region)
        self._combo_or_region = QComboBox()
        self._combo_or_region.currentIndexChanged.connect(self._on_or_cond_changed)
        oe_ed.addWidget(self._combo_or_region, 2)
        self._lbl_or_value = QLabel(tr("level.trigger_value"))
        oe_ed.addWidget(self._lbl_or_value)
        self._spin_or_value = QSpinBox()
        self._spin_or_value.setRange(0, 65535)
        self._spin_or_value.setFixedWidth(56)
        self._spin_or_value.valueChanged.connect(self._on_or_cond_changed)
        oe_ed.addWidget(self._spin_or_value)
        self._or_cond_editor.setVisible(False)
        ov.addWidget(self._or_cond_editor)

        self._grp_or = grp_or
        tpp.addWidget(grp_or)

        tv.addWidget(grp_tr)
        self._set_trigger_props_enabled(False)

        self._right_tabs.addTab(tab_trig, tr("level.tab_triggers"))

        # --- Tab 1d: Paths -----------------------------------------------
        tab_paths = QWidget()
        pv = QVBoxLayout(tab_paths)
        pv.setContentsMargins(4, 4, 4, 4)
        pv.setSpacing(4)

        path_ctrl = QHBoxLayout()
        self._btn_path_add = QPushButton(tr("level.path_add"))
        self._btn_path_add.clicked.connect(self._add_path)
        path_ctrl.addWidget(self._btn_path_add)
        self._btn_path_del = QPushButton(tr("level.path_del"))
        self._btn_path_del.clicked.connect(self._remove_path)
        self._btn_path_del.setEnabled(False)
        path_ctrl.addWidget(self._btn_path_del)
        path_ctrl.addStretch()
        pv.addLayout(path_ctrl)

        self._btn_path_edit = QPushButton(tr("level.path_edit_off"))
        self._btn_path_edit.setCheckable(True)
        self._btn_path_edit.setToolTip(tr("level.path_edit_tt"))
        self._btn_path_edit.toggled.connect(self._on_path_edit_toggled)
        pv.addWidget(self._btn_path_edit)

        path_intro = QLabel(tr("level.path_intro"))
        path_intro.setWordWrap(True)
        path_intro.setStyleSheet(
            "color: #c8c8c8; font-size: 10px; background: #20242a; "
            "border: 1px solid #3a3f46; padding: 6px;"
        )
        pv.addWidget(path_intro)

        self._btn_path_assign_selected = QPushButton(tr("level.path_assign_selected"))
        self._btn_path_assign_selected.setToolTip(tr("level.path_assign_selected_tt"))
        self._btn_path_assign_selected.clicked.connect(self._assign_selected_path_to_entity)
        pv.addWidget(self._btn_path_assign_selected)

        self._lbl_path_links = QLabel(tr("level.path_links_no_path"))
        self._lbl_path_links.setWordWrap(True)
        self._lbl_path_links.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        pv.addWidget(self._lbl_path_links)

        self._path_list = QListWidget()
        self._path_list.currentRowChanged.connect(self._on_path_selected)
        pv.addWidget(self._path_list, 1)

        grp_path = QGroupBox(tr("level.path_props_group"))
        ppv = QVBoxLayout(grp_path)
        ppv.setSpacing(4)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(tr("level.path_name")))
        self._edit_path_name = QLineEdit()
        self._edit_path_name.setToolTip(tr("level.path_name_tt"))
        self._edit_path_name.textChanged.connect(self._on_path_prop_changed)
        name_row.addWidget(self._edit_path_name, 1)
        self._chk_path_loop = QCheckBox(tr("level.path_loop"))
        self._chk_path_loop.setToolTip(tr("level.path_loop_tt"))
        self._chk_path_loop.toggled.connect(self._on_path_prop_changed)
        name_row.addWidget(self._chk_path_loop)
        name_row.addWidget(QLabel(tr("level.path_speed")))
        self._spn_path_speed = QSpinBox()
        self._spn_path_speed.setRange(1, 8)
        self._spn_path_speed.setValue(1)
        self._spn_path_speed.setToolTip(tr("level.path_speed_tt"))
        self._spn_path_speed.valueChanged.connect(self._on_path_prop_changed)
        name_row.addWidget(self._spn_path_speed)
        ppv.addLayout(name_row)

        ppv.addWidget(QLabel(tr("level.path_points")))
        self._path_point_list = QListWidget()
        self._path_point_list.currentRowChanged.connect(self._on_path_point_selected)
        ppv.addWidget(self._path_point_list, 1)

        pt_ctrl = QHBoxLayout()
        self._btn_path_pt_add = QPushButton(tr("level.path_point_add"))
        self._btn_path_pt_add.clicked.connect(self._add_path_point)
        pt_ctrl.addWidget(self._btn_path_pt_add)
        self._btn_path_pt_del = QPushButton(tr("level.path_point_del"))
        self._btn_path_pt_del.clicked.connect(self._remove_path_point)
        pt_ctrl.addWidget(self._btn_path_pt_del)
        pt_ctrl.addStretch()
        ppv.addLayout(pt_ctrl)

        coord_row = QHBoxLayout()
        coord_row.addWidget(QLabel(tr("level.path_point_x")))
        self._spn_path_pt_x = QSpinBox()
        self._spn_path_pt_x.setRange(0, 32767)
        self._spn_path_pt_x.setSuffix(" px")
        self._spn_path_pt_x.setToolTip(tr("level.path_point_coord_tt"))
        self._spn_path_pt_x.valueChanged.connect(self._on_path_point_coord_changed)
        coord_row.addWidget(self._spn_path_pt_x)
        coord_row.addSpacing(8)
        coord_row.addWidget(QLabel(tr("level.path_point_y")))
        self._spn_path_pt_y = QSpinBox()
        self._spn_path_pt_y.setRange(0, 32767)
        self._spn_path_pt_y.setSuffix(" px")
        self._spn_path_pt_y.setToolTip(tr("level.path_point_coord_tt"))
        self._spn_path_pt_y.valueChanged.connect(self._on_path_point_coord_changed)
        coord_row.addWidget(self._spn_path_pt_y)
        coord_row.addStretch()
        ppv.addLayout(coord_row)

        hint = QLabel(tr("level.path_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #aaa; font-size: 10px;")
        ppv.addWidget(hint)

        pv.addWidget(grp_path)
        self._set_path_props_enabled(False)

        self._tab_paths = tab_paths
        self._right_tabs.addTab(tab_paths, tr("level.tab_paths"))

        # --- Tab 2: Procgen -----------------------------------------------
        tab_gen = QWidget()
        gv = QVBoxLayout(tab_gen)
        gv.setContentsMargins(2, 2, 2, 2)
        gv.setSpacing(0)

        self._procgen_sub_tabs = QTabWidget()
        self._procgen_sub_tabs.setDocumentMode(True)

        # ── Sub-tab A : Design Map (design-time, existing content) ────────
        tab_design = QWidget()
        tab_design_v = QVBoxLayout(tab_design)
        tab_design_v.setContentsMargins(4, 4, 4, 4)
        tab_design_v.setSpacing(5)

        proc_split = QSplitter(Qt.Orientation.Vertical)

        proc_top = QWidget()
        ptv = QVBoxLayout(proc_top)
        ptv.setContentsMargins(0, 0, 0, 0)
        ptv.setSpacing(5)

        # ---- Map mode ----
        ptv.addWidget(QLabel(tr("level.procgen_map_mode")))
        self._combo_map_mode = QComboBox()
        for key, label in _MAP_MODES:
            self._combo_map_mode.addItem(tr(label), key)
        self._combo_map_mode.currentIndexChanged.connect(self._on_map_mode_changed)
        ptv.addWidget(self._combo_map_mode)

        # ---- Open-field density (only visible for "open" mode) ----
        self._open_density_widget = QWidget()
        od_row = QHBoxLayout(self._open_density_widget)
        od_row.setContentsMargins(0, 0, 0, 0)
        od_row.addWidget(QLabel(tr("level.procgen_obstacle_density")))
        self._spin_open_dens = QSpinBox()
        self._spin_open_dens.setRange(1, 60)
        self._spin_open_dens.setValue(20)
        self._spin_open_dens.setSuffix("%")
        od_row.addWidget(self._spin_open_dens)
        self._open_density_widget.setVisible(False)
        ptv.addWidget(self._open_density_widget)

        # ---- Top-down generation mode (scatter / BSP) ----
        self._td_mode_widget = QWidget()
        tm_row = QHBoxLayout(self._td_mode_widget)
        tm_row.setContentsMargins(0, 0, 0, 0)
        tm_row.addWidget(QLabel(tr("level.procgen_td_gen_mode")))
        self._combo_td_gen_mode = QComboBox()
        self._combo_td_gen_mode.addItem(tr("level.procgen_td_mode_scatter"), "scatter")
        self._combo_td_gen_mode.addItem(tr("level.procgen_td_mode_bsp"),     "bsp")
        tm_row.addWidget(self._combo_td_gen_mode, 1)
        self._td_mode_widget.setVisible(False)
        ptv.addWidget(self._td_mode_widget)

        # CA smoothing (scatter only)
        self._chk_td_ca = QCheckBox(tr("level.procgen_td_ca"))
        self._chk_td_ca.setToolTip(tr("level.procgen_td_ca_tt"))
        self._chk_td_ca.setChecked(True)
        self._chk_td_ca.setVisible(False)
        ptv.addWidget(self._chk_td_ca)

        # Output size (scatter only) — min = 1 screen, max = 32×32 (hardware window)
        self._td_scatter_widget = QWidget()
        scat_sz_row = QHBoxLayout(self._td_scatter_widget)
        scat_sz_row.setContentsMargins(0, 0, 0, 0)
        scat_sz_row.addWidget(QLabel(tr("level.procgen_td_scatter_out_size") + ":"))
        self._spin_td_scatter_out_w = QSpinBox()
        self._spin_td_scatter_out_w.setRange(_SCREEN_W, 32)
        self._spin_td_scatter_out_w.setValue(_SCREEN_W)
        self._spin_td_scatter_out_w.setToolTip(tr("level.procgen_td_scatter_out_size_tt"))
        self._spin_td_scatter_out_w.setPrefix("W ")
        scat_sz_row.addWidget(self._spin_td_scatter_out_w)
        self._spin_td_scatter_out_h = QSpinBox()
        self._spin_td_scatter_out_h.setRange(_SCREEN_H, 32)
        self._spin_td_scatter_out_h.setValue(_SCREEN_H)
        self._spin_td_scatter_out_h.setToolTip(tr("level.procgen_td_scatter_out_size_tt"))
        self._spin_td_scatter_out_h.setPrefix("H ")
        scat_sz_row.addWidget(self._spin_td_scatter_out_h)
        scat_sz_row.addStretch()
        self._td_scatter_widget.setVisible(False)
        ptv.addWidget(self._td_scatter_widget)

        # BSP depth / loop / output-size (BSP only)
        self._td_bsp_widget = QWidget()
        bsp_v = QVBoxLayout(self._td_bsp_widget)
        bsp_v.setContentsMargins(0, 0, 0, 0)
        bsp_v.setSpacing(2)
        bsp_row = QHBoxLayout()
        bsp_row.setContentsMargins(0, 0, 0, 0)
        bsp_row.addWidget(QLabel(tr("level.procgen_td_bsp_depth")))
        self._spin_td_bsp_depth = QSpinBox()
        self._spin_td_bsp_depth.setRange(2, 7)
        self._spin_td_bsp_depth.setValue(4)
        self._spin_td_bsp_depth.setToolTip(tr("level.procgen_td_bsp_depth_tt"))
        bsp_row.addWidget(self._spin_td_bsp_depth)
        bsp_row.addWidget(QLabel(tr("level.procgen_td_bsp_loop")))
        self._spin_td_loop_pct = QSpinBox()
        self._spin_td_loop_pct.setRange(0, 50)
        self._spin_td_loop_pct.setValue(15)
        self._spin_td_loop_pct.setSuffix("%")
        self._spin_td_loop_pct.setToolTip(tr("level.procgen_td_bsp_loop_tt"))
        bsp_row.addWidget(self._spin_td_loop_pct)
        bsp_v.addLayout(bsp_row)
        bsp_sz_row = QHBoxLayout()
        bsp_sz_row.setContentsMargins(0, 0, 0, 0)
        bsp_sz_row.addWidget(QLabel(tr("level.procgen_td_bsp_out_size") + ":"))
        self._spin_td_bsp_out_w = QSpinBox()
        self._spin_td_bsp_out_w.setRange(0, 200)
        self._spin_td_bsp_out_w.setValue(0)
        self._spin_td_bsp_out_w.setSpecialValueText("auto")
        self._spin_td_bsp_out_w.setToolTip(tr("level.procgen_td_bsp_out_size_tt"))
        self._spin_td_bsp_out_w.setPrefix("W ")
        bsp_sz_row.addWidget(self._spin_td_bsp_out_w)
        self._spin_td_bsp_out_h = QSpinBox()
        self._spin_td_bsp_out_h.setRange(0, 200)
        self._spin_td_bsp_out_h.setValue(0)
        self._spin_td_bsp_out_h.setSpecialValueText("auto")
        self._spin_td_bsp_out_h.setToolTip(tr("level.procgen_td_bsp_out_size_tt"))
        self._spin_td_bsp_out_h.setPrefix("H ")
        bsp_sz_row.addWidget(self._spin_td_bsp_out_h)
        bsp_sz_row.addStretch()
        bsp_v.addLayout(bsp_sz_row)
        bsp_spr_row = QHBoxLayout()
        bsp_spr_row.setContentsMargins(0, 0, 0, 0)
        bsp_spr_row.addWidget(QLabel(tr("level.procgen_td_bsp_sprite_sz") + ":"))
        self._spin_td_bsp_sprite = QSpinBox()
        self._spin_td_bsp_sprite.setRange(1, 6)
        self._spin_td_bsp_sprite.setValue(1)
        self._spin_td_bsp_sprite.setToolTip(tr("level.procgen_td_bsp_sprite_sz_tt"))
        bsp_spr_row.addWidget(self._spin_td_bsp_sprite)
        bsp_spr_row.addStretch()
        bsp_v.addLayout(bsp_spr_row)
        self._td_bsp_widget.setVisible(False)
        ptv.addWidget(self._td_bsp_widget)

        self._combo_td_gen_mode.currentIndexChanged.connect(self._on_td_gen_mode_changed)

        # ---- Top-down directional walls option ----
        self._chk_dir_walls = QCheckBox(tr("level.procgen_dir_walls"))
        self._chk_dir_walls.setToolTip(tr("level.procgen_dir_walls_tt"))
        self._chk_dir_walls.setChecked(True)
        self._chk_dir_walls.setVisible(False)
        ptv.addWidget(self._chk_dir_walls)

        # ---- Top-down feature toggles (what to include in generation) ----
        self._topdown_features_widget = QWidget()
        tf_v = QVBoxLayout(self._topdown_features_widget)
        tf_v.setContentsMargins(0, 0, 0, 0)
        tf_v.setSpacing(2)
        tf_v.addWidget(QLabel(tr("level.procgen_td_include")))
        self._chk_td_int_walls = QCheckBox(tr("level.procgen_td_int_walls"))
        self._chk_td_int_walls.setChecked(True)
        tf_v.addWidget(self._chk_td_int_walls)
        self._chk_td_water = QCheckBox(tr("level.procgen_td_water"))
        self._chk_td_water.setChecked(True)
        tf_v.addWidget(self._chk_td_water)
        border_lbl = QLabel(tr("level.procgen_td_borders"))
        border_lbl.setStyleSheet("font-size: 10px; color: #aaa;")
        tf_v.addWidget(border_lbl)
        tf_borders = QHBoxLayout()
        tf_borders.setContentsMargins(0, 0, 0, 0)
        self._chk_td_border_n = QCheckBox("N")
        self._chk_td_border_n.setChecked(True)
        self._chk_td_border_s = QCheckBox("S")
        self._chk_td_border_s.setChecked(True)
        self._chk_td_border_e = QCheckBox("E")
        self._chk_td_border_e.setChecked(True)
        self._chk_td_border_w = QCheckBox("W")
        self._chk_td_border_w.setChecked(True)
        for _c in (self._chk_td_border_n, self._chk_td_border_s,
                   self._chk_td_border_e, self._chk_td_border_w):
            tf_borders.addWidget(_c)
        tf_borders.addStretch()
        tf_v.addLayout(tf_borders)
        self._topdown_features_widget.setVisible(False)
        ptv.addWidget(self._topdown_features_widget)

        # ---- Top-down interior wall density ----
        self._wall_dens_widget = QWidget()
        wd_row = QHBoxLayout(self._wall_dens_widget)
        wd_row.setContentsMargins(0, 0, 0, 0)
        wd_row.addWidget(QLabel(tr("level.procgen_wall_density")))
        self._spin_wall_dens = QSpinBox()
        self._spin_wall_dens.setRange(1, 80)
        self._spin_wall_dens.setValue(20)
        self._spin_wall_dens.setSuffix("%")
        self._spin_wall_dens.setToolTip(tr("level.procgen_wall_density_tt"))
        wd_row.addWidget(self._spin_wall_dens)
        self._wall_dens_widget.setVisible(False)
        ptv.addWidget(self._wall_dens_widget)

        # ---- Tile role → visual tile index (dynamic per mode) ----
        ptv.addWidget(QLabel(tr("level.procgen_tile_roles")))
        tile_roles_note = QLabel(tr("level.procgen_tile_roles_note"))
        tile_roles_note.setWordWrap(True)
        tile_roles_note.setStyleSheet("color: #aaa; font-size: 10px;")
        ptv.addWidget(tile_roles_note)
        self._tile_role_scroll = QScrollArea()
        self._tile_role_scroll.setWidgetResizable(True)
        self._tile_role_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._tile_role_inner = QWidget()
        self._tile_role_layout = QVBoxLayout(self._tile_role_inner)
        self._tile_role_layout.setContentsMargins(2, 2, 2, 2)
        self._tile_role_layout.setSpacing(2)
        self._tile_role_scroll.setWidget(self._tile_role_inner)
        self._tile_role_scroll.setVisible(False)
        ptv.addWidget(self._tile_role_scroll, 1)

        proc_bottom = QWidget()
        pbv = QVBoxLayout(proc_bottom)
        pbv.setContentsMargins(0, 0, 0, 0)
        pbv.setSpacing(5)

        # ---- Common procgen params ----
        seed_row = QHBoxLayout()
        seed_row.addWidget(QLabel(tr("level.procgen_seed")))
        self._spin_seed = QSpinBox()
        self._spin_seed.setRange(0, 999999)
        self._spin_seed.setValue(42)
        seed_row.addWidget(self._spin_seed, 1)
        self._btn_rand_seed = QPushButton("🎲")
        self._btn_rand_seed.setFixedWidth(28)
        self._btn_rand_seed.clicked.connect(
            lambda: self._spin_seed.setValue(random.randint(0, 999999)))
        seed_row.addWidget(self._btn_rand_seed)
        pbv.addLayout(seed_row)

        margin_row = QHBoxLayout()
        margin_row.addWidget(QLabel(tr("level.procgen_margin")))
        self._spin_margin = QSpinBox()
        self._spin_margin.setRange(0, 10)
        self._spin_margin.setValue(1)
        margin_row.addWidget(self._spin_margin)
        margin_row.addWidget(QLabel("tiles"))
        pbv.addLayout(margin_row)

        enemy_row = QHBoxLayout()
        enemy_row.addWidget(QLabel(tr("level.procgen_enemy_density")))
        self._spin_enemy_dens = QSpinBox()
        self._spin_enemy_dens.setRange(0, 50)
        self._spin_enemy_dens.setValue(10)
        self._spin_enemy_dens.setSuffix("%")
        enemy_row.addWidget(self._spin_enemy_dens)
        pbv.addLayout(enemy_row)

        item_row = QHBoxLayout()
        item_row.addWidget(QLabel(tr("level.procgen_item_density")))
        self._spin_item_dens = QSpinBox()
        self._spin_item_dens.setRange(0, 20)
        self._spin_item_dens.setValue(5)
        self._spin_item_dens.setSuffix("%")
        item_row.addWidget(self._spin_item_dens)
        pbv.addLayout(item_row)

        # ---- Optional: generate tilemap PNG(s) from the collision map ----
        self._chk_gen_tilemaps = QCheckBox(tr("level.procgen_gen_tilemaps"))
        self._chk_gen_tilemaps.setToolTip(tr("level.procgen_gen_tilemaps_tt"))
        self._chk_gen_tilemaps.setChecked(True)
        pbv.addWidget(self._chk_gen_tilemaps)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel(tr("level.procgen_tile_out")))
        self._chk_gen_scr1 = QCheckBox("SCR1")
        self._chk_gen_scr1.setToolTip(tr("level.procgen_tile_out_scr1_tt"))
        self._chk_gen_scr1.setChecked(True)
        out_row.addWidget(self._chk_gen_scr1)
        self._chk_gen_scr2 = QCheckBox("SCR2")
        self._chk_gen_scr2.setToolTip(tr("level.procgen_tile_out_scr2_tt"))
        self._chk_gen_scr2.setChecked(False)
        out_row.addWidget(self._chk_gen_scr2)
        out_row.addStretch()
        pbv.addLayout(out_row)

        src_row = QHBoxLayout()
        src_row.addWidget(QLabel(tr("level.procgen_tile_src")))
        self._combo_tile_src = QComboBox()
        for key, label_key in _TILE_SRC_CHOICES:
            self._combo_tile_src.addItem(tr(label_key), key)
        self._combo_tile_src.setToolTip(tr("level.procgen_tile_src_tt"))
        self._combo_tile_src.currentIndexChanged.connect(
            lambda _idx: self._rebuild_tile_role_ui(self._map_mode)
            if self._map_mode in _MAP_MODE_ROLES else None
        )
        src_row.addWidget(self._combo_tile_src, 1)
        pbv.addLayout(src_row)

        hint = QLabel(tr("level.procgen_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #aaa; font-size: 10px;")
        pbv.addWidget(hint)

        self._btn_generate = QPushButton(tr("level.procgen_generate"))
        self._btn_generate.clicked.connect(self._do_procgen)
        pbv.addWidget(self._btn_generate)
        pbv.addStretch()

        proc_split.addWidget(proc_top)
        proc_split.addWidget(proc_bottom)
        proc_split.setStretchFactor(0, 1)
        proc_split.setStretchFactor(1, 0)

        settings = QSettings("NGPCraft", "Engine")
        saved = settings.value("level_tab/procgen_splitter_state")
        if saved:
            try:
                proc_split.restoreState(saved)
            except Exception:
                pass
        else:
            proc_split.setSizes([620, 240])

        proc_split.splitterMoved.connect(
            lambda _pos, _idx, _s=proc_split: QSettings("NGPCraft", "Engine").setValue(
                "level_tab/procgen_splitter_state", _s.saveState()
            )
        )

        tab_design_v.addWidget(proc_split, 1)

        self._procgen_sub_tabs.addTab(tab_design,                            "Design Map")
        self._procgen_sub_tabs.addTab(self._build_procgen_dungeongen_tab(), "DungeonGen")
        self._procgen_sub_tabs.addTab(self._build_procgen_assets_tab(),     "Procgen Assets")
        # Hidden (WIP — not ready for use):
        self._tab_dfs  = self._build_procgen_dfs_tab()
        self._tab_cave = self._build_procgen_cave_tab()
        gv.addWidget(self._procgen_sub_tabs, 1)

        self._tab_procgen = tab_gen
        self._right_tabs.addTab(tab_gen, tr("level.tab_procgen"))

        # --- Tab 3: Layout / scroll --------------------------------------
        tab_layout = QWidget()
        lv = QVBoxLayout(tab_layout)
        lv.setContentsMargins(4, 4, 4, 4)
        lv.setSpacing(6)

        grp_cam = QGroupBox(tr("level.layout_cam_group"))
        camv = QVBoxLayout(grp_cam)
        camv.setSpacing(4)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(tr("level.layout_cam_mode")))
        self._combo_cam_mode = QComboBox()
        for key, label_key in _CAM_MODES:
            self._combo_cam_mode.addItem(tr(label_key), key)
        self._combo_cam_mode.setToolTip(tr("level.layout_cam_mode_tt"))
        self._combo_cam_mode.currentIndexChanged.connect(self._on_layout_changed)
        mode_row.addWidget(self._combo_cam_mode, 1)
        self._btn_cam_mode_preset = QPushButton(tr("level.layout_cam_mode_preset"))
        self._btn_cam_mode_preset.setToolTip(tr("level.layout_cam_mode_preset_tt"))
        self._btn_cam_mode_preset.clicked.connect(self._apply_cam_mode_preset)
        self._btn_cam_mode_preset.setFixedWidth(74)
        mode_row.addWidget(self._btn_cam_mode_preset)
        camv.addLayout(mode_row)

        layout_preset_row = QHBoxLayout()
        layout_preset_row.addWidget(QLabel(tr("level.layout_preset_label")))
        self._combo_layout_preset = QComboBox()
        for preset_key, label_key, _cfg in _LAYOUT_PRESETS:
            self._combo_layout_preset.addItem(tr(label_key), preset_key)
        self._combo_layout_preset.setToolTip(tr("level.layout_preset_tt"))
        layout_preset_row.addWidget(self._combo_layout_preset, 1)
        self._btn_layout_preset = QPushButton(tr("level.layout_preset_apply"))
        self._btn_layout_preset.setToolTip(tr("level.layout_preset_apply_tt"))
        self._btn_layout_preset.clicked.connect(self._apply_layout_preset_clicked)
        layout_preset_row.addWidget(self._btn_layout_preset)
        camv.addLayout(layout_preset_row)

        self._lbl_layout_preset_hint = QLabel(tr("level.layout_preset_hint"))
        self._lbl_layout_preset_hint.setWordWrap(True)
        self._lbl_layout_preset_hint.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        camv.addWidget(self._lbl_layout_preset_hint)

        cam_row = QHBoxLayout()
        cam_row.addWidget(QLabel(tr("level.layout_cam_x")))
        self._spin_cam_x = QSpinBox()
        self._spin_cam_x.setRange(0, 255)
        cam_row.addWidget(self._spin_cam_x, 1)
        cam_row.addWidget(QLabel(tr("level.layout_cam_y")))
        self._spin_cam_y = QSpinBox()
        self._spin_cam_y.setRange(0, 255)
        cam_row.addWidget(self._spin_cam_y, 1)
        camv.addLayout(cam_row)

        clamp_row = QHBoxLayout()
        self._chk_cam_clamp = QCheckBox(tr("level.layout_cam_clamp"))
        self._chk_cam_clamp.setToolTip(tr("level.layout_cam_clamp_tt"))
        self._chk_cam_clamp.toggled.connect(self._on_layout_changed)
        clamp_row.addWidget(self._chk_cam_clamp)
        self._chk_cam_bounds_auto = QCheckBox(tr("level.layout_cam_bounds_auto"))
        self._chk_cam_bounds_auto.setToolTip(tr("level.layout_cam_bounds_auto_tt"))
        self._chk_cam_bounds_auto.toggled.connect(self._on_layout_changed)
        clamp_row.addWidget(self._chk_cam_bounds_auto)
        clamp_row.addStretch()
        self._btn_cam_bounds_from_map = QPushButton(tr("level.layout_cam_bounds_from_map"))
        self._btn_cam_bounds_from_map.setToolTip(tr("level.layout_cam_bounds_from_map_tt"))
        self._btn_cam_bounds_from_map.clicked.connect(self._cam_bounds_from_map)
        clamp_row.addWidget(self._btn_cam_bounds_from_map)
        camv.addLayout(clamp_row)

        bounds_row = QHBoxLayout()
        bounds_row.addWidget(QLabel(tr("level.layout_cam_min")))
        self._spin_cam_min_x = QSpinBox()
        self._spin_cam_min_x.setRange(0, 255)
        self._spin_cam_min_x.valueChanged.connect(self._on_layout_changed)
        bounds_row.addWidget(self._spin_cam_min_x)
        self._spin_cam_min_y = QSpinBox()
        self._spin_cam_min_y.setRange(0, 255)
        self._spin_cam_min_y.valueChanged.connect(self._on_layout_changed)
        bounds_row.addWidget(self._spin_cam_min_y)
        bounds_row.addSpacing(6)
        bounds_row.addWidget(QLabel(tr("level.layout_cam_max")))
        self._spin_cam_max_x = QSpinBox()
        self._spin_cam_max_x.setRange(0, 255)
        self._spin_cam_max_x.valueChanged.connect(self._on_layout_changed)
        bounds_row.addWidget(self._spin_cam_max_x)
        self._spin_cam_max_y = QSpinBox()
        self._spin_cam_max_y.setRange(0, 255)
        self._spin_cam_max_y.valueChanged.connect(self._on_layout_changed)
        bounds_row.addWidget(self._spin_cam_max_y)
        camv.addLayout(bounds_row)

        follow_row = QHBoxLayout()
        follow_row.addWidget(QLabel(tr("level.layout_follow_deadzone")))
        self._spin_cam_deadzone_x = QSpinBox()
        self._spin_cam_deadzone_x.setRange(0, 79)
        self._spin_cam_deadzone_x.setToolTip(tr("level.layout_follow_deadzone_tt"))
        self._spin_cam_deadzone_x.valueChanged.connect(self._on_layout_changed)
        follow_row.addWidget(self._spin_cam_deadzone_x)
        self._spin_cam_deadzone_y = QSpinBox()
        self._spin_cam_deadzone_y.setRange(0, 71)
        self._spin_cam_deadzone_y.setToolTip(tr("level.layout_follow_deadzone_tt"))
        self._spin_cam_deadzone_y.valueChanged.connect(self._on_layout_changed)
        follow_row.addWidget(self._spin_cam_deadzone_y)
        follow_row.addWidget(QLabel("X/Y"))
        follow_row.addStretch()
        camv.addLayout(follow_row)

        drop_row = QHBoxLayout()
        drop_row.addWidget(QLabel(tr("level.layout_follow_drop_margin")))
        self._spin_cam_drop_margin_y = QSpinBox()
        self._spin_cam_drop_margin_y.setRange(0, 71)
        self._spin_cam_drop_margin_y.setToolTip(tr("level.layout_follow_drop_margin_tt"))
        self._spin_cam_drop_margin_y.valueChanged.connect(self._on_layout_changed)
        drop_row.addWidget(self._spin_cam_drop_margin_y)
        drop_row.addStretch()
        camv.addLayout(drop_row)

        lag_row = QHBoxLayout()
        lag_row.addWidget(QLabel(tr("level.layout_cam_lag")))
        self._spin_cam_lag = QSpinBox()
        self._spin_cam_lag.setRange(0, 4)
        self._spin_cam_lag.setToolTip(tr("level.layout_cam_lag_tt"))
        self._spin_cam_lag.valueChanged.connect(self._on_layout_changed)
        lag_row.addWidget(self._spin_cam_lag)
        lag_row.addStretch()
        camv.addLayout(lag_row)

        self._btn_cam_from_bezel = QPushButton(tr("level.layout_cam_from_bezel"))
        self._btn_cam_from_bezel.setToolTip(tr("level.layout_cam_from_bezel_tt"))
        self._btn_cam_from_bezel.clicked.connect(self._on_cam_from_bezel)
        camv.addWidget(self._btn_cam_from_bezel)

        cam_hint = QLabel(tr("level.layout_cam_hint"))
        cam_hint.setWordWrap(True)
        cam_hint.setStyleSheet("color: #aaa; font-size: 10px;")
        camv.addWidget(cam_hint)

        lv.addWidget(grp_cam)

        grp_scroll = QGroupBox(tr("level.layout_scroll_group"))
        sv = QVBoxLayout(grp_scroll)
        sv.setSpacing(4)

        axis_row = QHBoxLayout()
        self._chk_scroll_x = QCheckBox(tr("level.layout_scroll_x"))
        self._chk_scroll_y = QCheckBox(tr("level.layout_scroll_y"))
        axis_row.addWidget(self._chk_scroll_x)
        axis_row.addWidget(self._chk_scroll_y)
        axis_row.addStretch()
        sv.addLayout(axis_row)

        self._chk_forced_scroll = QCheckBox(tr("level.layout_forced_scroll"))
        self._chk_forced_scroll.setToolTip(tr("level.layout_forced_scroll_tt"))
        sv.addWidget(self._chk_forced_scroll)

        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel(tr("level.layout_speed_x")))
        self._spin_speed_x = QSpinBox()
        self._spin_speed_x.setRange(-8, 8)
        self._spin_speed_x.setValue(0)
        speed_row.addWidget(self._spin_speed_x, 1)
        speed_row.addWidget(QLabel(tr("level.layout_speed_y")))
        self._spin_speed_y = QSpinBox()
        self._spin_speed_y.setRange(-8, 8)
        self._spin_speed_y.setValue(0)
        speed_row.addWidget(self._spin_speed_y, 1)
        sv.addLayout(speed_row)

        loop_row = QHBoxLayout()
        self._chk_loop_x = QCheckBox(tr("level.layout_loop_x"))
        self._chk_loop_y = QCheckBox(tr("level.layout_loop_y"))
        loop_row.addWidget(self._chk_loop_x)
        loop_row.addWidget(self._chk_loop_y)
        loop_row.addStretch()
        sv.addLayout(loop_row)

        lv.addWidget(grp_scroll)

        grp_layers = QGroupBox(tr("level.layers_group"))
        layv = QVBoxLayout(grp_layers)
        layv.setSpacing(4)

        par1 = QHBoxLayout()
        par1.addWidget(QLabel(tr("level.layers_scr1")))
        par1.addWidget(QLabel(tr("level.layers_parallax")))
        self._spin_scr1_par_x = QSpinBox()
        self._spin_scr1_par_x.setRange(0, 200)
        self._spin_scr1_par_x.setSuffix("%")
        self._spin_scr1_par_x.setToolTip(tr("level.layers_parallax_tt"))
        self._spin_scr1_par_x.valueChanged.connect(self._on_layers_changed)
        par1.addWidget(self._spin_scr1_par_x)
        self._spin_scr1_par_y = QSpinBox()
        self._spin_scr1_par_y.setRange(0, 200)
        self._spin_scr1_par_y.setSuffix("%")
        self._spin_scr1_par_y.setToolTip(tr("level.layers_parallax_tt"))
        self._spin_scr1_par_y.valueChanged.connect(self._on_layers_changed)
        par1.addWidget(self._spin_scr1_par_y)
        par1.addWidget(QLabel("X/Y"))
        par1.addStretch()
        layv.addLayout(par1)

        par2 = QHBoxLayout()
        par2.addWidget(QLabel(tr("level.layers_scr2")))
        par2.addWidget(QLabel(tr("level.layers_parallax")))
        self._spin_scr2_par_x = QSpinBox()
        self._spin_scr2_par_x.setRange(0, 200)
        self._spin_scr2_par_x.setSuffix("%")
        self._spin_scr2_par_x.setToolTip(tr("level.layers_parallax_tt"))
        self._spin_scr2_par_x.valueChanged.connect(self._on_layers_changed)
        par2.addWidget(self._spin_scr2_par_x)
        self._spin_scr2_par_y = QSpinBox()
        self._spin_scr2_par_y.setRange(0, 200)
        self._spin_scr2_par_y.setSuffix("%")
        self._spin_scr2_par_y.setToolTip(tr("level.layers_parallax_tt"))
        self._spin_scr2_par_y.valueChanged.connect(self._on_layers_changed)
        par2.addWidget(self._spin_scr2_par_y)
        par2.addWidget(QLabel("X/Y"))
        par2.addStretch()
        layv.addLayout(par2)

        layers_hint = QLabel(tr("level.layers_hint"))
        layers_hint.setWordWrap(True)
        layers_hint.setStyleSheet("color: #aaa; font-size: 10px;")
        layv.addWidget(layers_hint)

        lv.addWidget(grp_layers)

        # X-1 — Palette cycling (ngpc_palfx)
        grp_palfx = QGroupBox(tr("level.palfx_group"))
        pfv = QVBoxLayout(grp_palfx)
        pfv.setSpacing(4)
        pfx_hint = QLabel(tr("level.palfx_hint"))
        pfx_hint.setWordWrap(True)
        pfx_hint.setStyleSheet("color: #aaa; font-size: 10px;")
        pfv.addWidget(pfx_hint)
        self._tbl_palfx = QTableWidget(0, 3)
        self._tbl_palfx.setHorizontalHeaderLabels([
            tr("level.palfx_col_plane"),
            tr("level.palfx_col_pal"),
            tr("level.palfx_col_speed"),
        ])
        self._tbl_palfx.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._tbl_palfx.setMaximumHeight(120)
        self._tbl_palfx.setToolTip(tr("level.palfx_tt"))
        pfv.addWidget(self._tbl_palfx)
        pfx_btns = QHBoxLayout()
        btn_palfx_add = QPushButton(tr("level.palfx_add"))
        btn_palfx_add.clicked.connect(self._add_palfx_row)
        btn_palfx_del = QPushButton(tr("level.palfx_del"))
        btn_palfx_del.clicked.connect(self._del_palfx_row)
        pfx_btns.addWidget(btn_palfx_add)
        pfx_btns.addWidget(btn_palfx_del)
        pfx_btns.addStretch()
        pfv.addLayout(pfx_btns)
        lv.addWidget(grp_palfx)

        # ── Scènes voisines (Track B — edge warps) ────────────────────────
        grp_nb = QGroupBox(tr("level.neighbors_title"))
        nbv = QVBoxLayout(grp_nb)
        nbv.setSpacing(4)
        self._combo_nb: dict[str, QComboBox] = {}
        for _dir_key, _dir_label in (
            ("north", tr("level.nb_north")),
            ("south", tr("level.nb_south")),
            ("west",  tr("level.nb_west")),
            ("east",  tr("level.nb_east")),
        ):
            _row = QHBoxLayout()
            _lbl = QLabel(_dir_label)
            _lbl.setFixedWidth(46)
            _row.addWidget(_lbl)
            _cmb = QComboBox()
            _cmb.setToolTip(tr("level.nb_tt"))
            _cmb.currentIndexChanged.connect(self._on_neighbors_changed)
            _row.addWidget(_cmb, 1)
            nbv.addLayout(_row)
            self._combo_nb[_dir_key] = _cmb
        lv.addWidget(grp_nb)

        lv.addStretch()

        # Wire signals
        self._spin_cam_x.valueChanged.connect(self._on_layout_changed)
        self._spin_cam_y.valueChanged.connect(self._on_layout_changed)
        self._chk_scroll_x.toggled.connect(self._on_layout_changed)
        self._chk_scroll_y.toggled.connect(self._on_layout_changed)
        self._chk_forced_scroll.toggled.connect(self._on_layout_changed)
        self._spin_speed_x.valueChanged.connect(self._on_layout_changed)
        self._spin_speed_y.valueChanged.connect(self._on_layout_changed)
        self._chk_loop_x.toggled.connect(self._on_layout_changed)
        self._chk_loop_y.toggled.connect(self._on_layout_changed)
        self._update_layout_widgets()

        lv.addStretch()
        tab_layout_scroll = QScrollArea()
        tab_layout_scroll.setWidget(tab_layout)
        tab_layout_scroll.setWidgetResizable(True)
        tab_layout_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._tab_layout = tab_layout_scroll
        self._right_tabs.addTab(tab_layout_scroll, tr("level.tab_layout"))

        # ── X-3 OAM viewer tab ────────────────────────────────────────────────
        tab_oam = QWidget()
        ov = QVBoxLayout(tab_oam)
        ov.setContentsMargins(4, 4, 4, 4)
        ov.setSpacing(4)

        self._oam_canvas = _OamCanvasWidget(self)
        self._oam_canvas.setFixedHeight(80)
        ov.addWidget(self._oam_canvas)

        self._lbl_oam_total = QLabel("")
        self._lbl_oam_total.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ov.addWidget(self._lbl_oam_total)

        self._tbl_oam = QTableWidget(0, 4)
        self._tbl_oam.setHorizontalHeaderLabels([
            tr("level.oam_col_slot"),
            tr("level.oam_col_type"),
            tr("level.oam_col_dims"),
            tr("level.oam_col_parts"),
        ])
        self._tbl_oam.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._tbl_oam.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._tbl_oam.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._tbl_oam.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._tbl_oam.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tbl_oam.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        ov.addWidget(self._tbl_oam)

        oam_hint = QLabel(tr("level.oam_hint"))
        oam_hint.setWordWrap(True)
        oam_hint.setStyleSheet("color: #9aa3ad; font-size: 10px;")
        ov.addWidget(oam_hint)

        self._right_tabs.addTab(tab_oam, tr("level.tab_oam"))

        # Bottom panel: export + budget (resizable via vertical splitter)
        bottom = QWidget()
        bv = QVBoxLayout(bottom)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(4)

        self._ctx_level_export = ContextHelpBox(
            tr("level.ctx_export_title"),
            tr("level.ctx_export_body"),
            self,
            expanded=False,
        )
        bv.addWidget(self._ctx_level_export)

        grp_export = QGroupBox(tr("level.export_group"))
        xv = QVBoxLayout(grp_export)
        xv.setSpacing(4)
        xv.addWidget(QLabel(tr("level.sym_label")))
        self._edit_sym = QLineEdit()
        self._edit_sym.setPlaceholderText("scene_name")
        xv.addWidget(self._edit_sym)
        self._btn_save = QPushButton(tr("level.save"))
        self._btn_save.setToolTip(tr("level.save_tt"))
        self._btn_save.clicked.connect(self._save_entities)
        xv.addWidget(self._btn_save)
        self._btn_export = QPushButton(tr("level.export_h"))
        self._btn_export.setToolTip(tr("level.export_h_tt"))
        self._btn_export.clicked.connect(self._export_scene_h)
        xv.addWidget(self._btn_export)
        bv.addWidget(grp_export)

        grp_budget = QGroupBox(tr("level.budget_group"))
        bbv = QVBoxLayout(grp_budget)
        self._lbl_budget = QLabel("")
        self._lbl_budget.setWordWrap(True)
        bbv.addWidget(self._lbl_budget)
        bv.addWidget(grp_budget)

        grp_diag = QGroupBox(tr("level.diag_group"))
        dvv = QVBoxLayout(grp_diag)
        self._lbl_checklist = QLabel("")
        self._lbl_checklist.setWordWrap(True)
        self._lbl_checklist.setTextFormat(Qt.TextFormat.RichText)
        self._lbl_checklist.setStyleSheet("color: #d7dde5; font-size: 10px;")
        dvv.addWidget(self._lbl_checklist)
        self._lbl_diag = QLabel("")
        self._lbl_diag.setWordWrap(True)
        self._lbl_diag.setStyleSheet("color: #bbb; font-size: 10px;")
        dvv.addWidget(self._lbl_diag)
        bv.addWidget(grp_diag)

        # Right splitter: top (tabs) | bottom (export/budget)
        right_split = QSplitter(Qt.Orientation.Vertical)
        right_split.addWidget(self._right_tabs)
        right_split.addWidget(bottom)
        right_split.setStretchFactor(0, 1)
        right_split.setStretchFactor(1, 0)

        settings = QSettings("NGPCraft", "Engine")
        saved = settings.value("level_tab/right_splitter_state")
        if saved:
            try:
                right_split.restoreState(saved)
            except Exception:
                pass
        else:
            right_split.setSizes([700, 220])

        right_split.splitterMoved.connect(
            lambda _pos, _idx, _s=right_split: QSettings("NGPCraft", "Engine").setValue(
                "level_tab/right_splitter_state", _s.saveState()
            )
        )

        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(4)
        rv.addWidget(right_split, 1)

        # Main splitter: left (types) | center (canvas) | right (tabs)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_tabs)
        splitter.addWidget(center)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)

        settings = QSettings("NGPCraft", "Engine")
        saved = settings.value("level_tab/main_splitter_state")
        if saved:
            try:
                splitter.restoreState(saved)
            except Exception:
                pass
        else:
            splitter.setSizes([160, 700, 280])

        splitter.splitterMoved.connect(
            lambda _pos, _idx, _s=splitter: QSettings("NGPCraft", "Engine").setValue(
                "level_tab/main_splitter_state", _s.saveState()
            )
        )

        root.addWidget(splitter, 1)

    # ------------------------------------------------------------------
    # Zoom
    # ------------------------------------------------------------------

    def _set_zoom(self, z: int) -> None:
        self._zoom = z
        for zs in _ZOOM_STEPS:
            btn = getattr(self, f"_zoom_btn_{zs}", None)
            if btn:
                btn.setChecked(zs == z)
        self._canvas.updateGeometry()
        self._canvas.resize(self._canvas.sizeHint())
        self._canvas.update()

    def _scene_tool_hint(self, mode: str) -> str:
        return tr({
            "select": "level.tool_hint_select",
            "entity": "level.tool_hint_entity",
            "wave": "level.tool_hint_wave",
            "collision": "level.tool_hint_collision",
            "region": "level.tool_hint_region",
            "path": "level.tool_hint_path",
            "camera": "level.tool_hint_camera",
        }.get(str(mode or "entity"), "level.tool_hint_entity"))

    def _sync_scene_tool_buttons(self) -> None:
        current = str(getattr(self, "_scene_tool", "entity") or "entity")
        if current == "wave" and not (len(self._waves) > 0 and self._wave_selected >= 0):
            current = "entity"
            self._scene_tool = current
            self._wave_edit = False
        if current == "path" and not self._paths:
            current = "entity"
            self._scene_tool = current
            self._path_edit = False
        buttons = {
            "select": getattr(self, "_btn_tool_select", None),
            "entity": getattr(self, "_btn_tool_entity", None),
            "wave": getattr(self, "_btn_tool_wave", None),
            "collision": getattr(self, "_btn_tool_collision", None),
            "region": getattr(self, "_btn_tool_region", None),
            "path": getattr(self, "_btn_tool_path", None),
            "camera": getattr(self, "_btn_tool_camera", None),
        }
        for mode, btn in buttons.items():
            if btn is None:
                continue
            btn.blockSignals(True)
            btn.setChecked(mode == current)
            if mode == "wave":
                btn.setEnabled(len(self._waves) > 0 and self._wave_selected >= 0)
            elif mode == "path":
                btn.setEnabled(len(self._paths) > 0)
            else:
                btn.setEnabled(True)
            btn.blockSignals(False)
        if getattr(self, "_lbl_scene_tool_hint", None) is not None:
            self._lbl_scene_tool_hint.setText(self._scene_tool_hint(current))
        self._refresh_collision_brush_ui()

    def _set_scene_tool(self, mode: str) -> None:
        mode = str(mode or "entity").strip().lower()
        if mode not in ("select", "entity", "wave", "collision", "region", "path", "camera"):
            mode = "entity"
        if mode == "wave" and not (len(self._waves) > 0 and self._wave_selected >= 0):
            mode = "entity"
        if mode == "path" and not self._paths:
            mode = "entity"

        self._scene_tool = mode
        self._wave_edit = (mode == "wave")
        self._region_edit = (mode == "region")
        self._path_edit = (mode == "path")
        if mode == "collision":
            self._on_col_map_toggled(True)

        if not self._wave_edit:
            self._wave_entity_sel = -1
        if not self._path_edit:
            self._path_point_selected = -1

        try:
            self._btn_wave_edit.blockSignals(True)
            self._btn_wave_edit.setChecked(self._wave_edit)
            self._btn_wave_edit.setText(tr("level.wave_edit_on") if self._wave_edit else tr("level.wave_edit_off"))
        except Exception:
            pass
        finally:
            try:
                self._btn_wave_edit.blockSignals(False)
            except Exception:
                pass

        try:
            self._btn_reg_edit.blockSignals(True)
            self._btn_reg_edit.setChecked(self._region_edit)
            self._btn_reg_edit.setText(tr("level.region_edit_on") if self._region_edit else tr("level.region_edit_off"))
        except Exception:
            pass
        finally:
            try:
                self._btn_reg_edit.blockSignals(False)
            except Exception:
                pass

        try:
            self._btn_path_edit.blockSignals(True)
            self._btn_path_edit.setChecked(self._path_edit)
            self._btn_path_edit.setText(tr("level.path_edit_on") if self._path_edit else tr("level.path_edit_off"))
        except Exception:
            pass
        finally:
            try:
                self._btn_path_edit.blockSignals(False)
            except Exception:
                pass

        if self._path_edit and self._path_selected < 0 and self._paths:
            self._path_selected = 0
            self._refresh_path_list()
            self._refresh_path_props()

        self._sync_scene_tool_buttons()
        self._canvas.update()

    # ------------------------------------------------------------------
    # Scene loading
    # ------------------------------------------------------------------

    def _set_project_scenes(self, project_data: dict | None) -> None:
        # Keep a reference to the project root so entity_types can be modified
        self._project_data_root: dict | None = project_data if isinstance(project_data, dict) else None
        scenes: list[dict] = []
        consts: list[dict] = []
        if isinstance(project_data, dict):
            raw = project_data.get("scenes", []) or []
            if isinstance(raw, list):
                for s in raw:
                    if isinstance(s, dict):
                        scenes.append(s)
            raw_c = project_data.get("constants", []) or []
            if isinstance(raw_c, list):
                for c in raw_c:
                    if isinstance(c, dict) and str(c.get("name", "") or "").strip():
                        consts.append(c)
        self._project_scenes = scenes
        self._project_constants = consts
        # --- Entity types + templates (templates take priority) ---
        raw_tpls = (project_data.get("entity_templates", []) or []) if isinstance(project_data, dict) else []
        raw_et   = (project_data.get("entity_types",    []) or []) if isinstance(project_data, dict) else []
        self._project_entity_types: list[dict] = (
            [t for t in raw_tpls if isinstance(t, dict)]
            + [t for t in raw_et  if isinstance(t, dict)]
        )
        # --- Game flags / vars ---
        raw_gf = (project_data.get("game_flags", []) or []) if isinstance(project_data, dict) else []
        self._project_game_flags: list[str] = [
            str(raw_gf[i]) if i < len(raw_gf) and raw_gf[i] else ""
            for i in range(8)
        ]
        raw_gv = (project_data.get("game_vars", []) or []) if isinstance(project_data, dict) else []
        self._project_game_vars: list[dict] = []
        for i in range(8):
            entry = raw_gv[i] if i < len(raw_gv) and isinstance(raw_gv[i], dict) else {}
            self._project_game_vars.append({"name": str(entry.get("name", "") or ""), "init": int(entry.get("init", 0) or 0)})
        # --- Audio: songs + sfx_map ---
        self._project_songs = []
        self._project_sfx_map = []
        if isinstance(project_data, dict):
            audio = project_data.get("audio", {}) or {}
            if isinstance(audio, dict):
                man_rel = str(audio.get("manifest") or "").strip()
                if man_rel and self._base_dir:
                    man_path = Path(man_rel)
                    if not man_path.is_absolute():
                        man_path = self._base_dir / man_rel
                    if man_path.is_file():
                        try:
                            manifest = load_audio_manifest(man_path)
                            self._project_songs = list(manifest.songs or [])
                            self._project_sfx_map = list(
                                load_sfx_names(manifest, man_path.parent)
                            )  # [(idx, name), ...]
                        except Exception:
                            pass
                sfx_map_rows = audio.get("sfx_map", []) or []
                if isinstance(sfx_map_rows, list) and sfx_map_rows:
                    self._project_sfx_map = [
                        (i, str(r.get("name") or f"sfx_{i}"))
                        for i, r in enumerate(sfx_map_rows)
                        if isinstance(r, dict)
                    ]
        picker = getattr(self, "_spin_trig_value", None)
        if isinstance(picker, _ConstantPickerWidget):
            picker.set_constants(consts)
        self._refresh_trigger_scene_combo()
        self._refresh_trigger_bgm_combo()
        self._refresh_trigger_sfx_combo()
        self._refresh_neighbor_combos()
        self._refresh_procgen_scene_combos()
        self._restore_procgen_assets_state()

    def _scene_idx_for_id(self, sid: str) -> int | None:
        sid = str(sid or "").strip()
        if not sid:
            return None
        for i, s in enumerate(self._project_scenes):
            if str(s.get("id") or "").strip() == sid:
                return int(i)
        return None

    def _scene_id_for_idx(self, idx: int) -> str | None:
        try:
            idx = int(idx)
        except Exception:
            return None
        if 0 <= idx < len(self._project_scenes):
            sid = str(self._project_scenes[idx].get("id") or "").strip()
            return sid or None
        return None

    def _next_scene_id_after_current(self) -> str:
        if not isinstance(self._scene, dict):
            return ""
        cur_sid = str(self._scene.get("id") or "").strip()
        cur_idx = self._scene_idx_for_id(cur_sid)
        if cur_idx is None:
            return ""
        next_sid = self._scene_id_for_idx(cur_idx + 1)
        return str(next_sid or "")

    def _apply_next_scene_target(self, trig: dict) -> None:
        sid = self._next_scene_id_after_current()
        trig["scene_to"] = sid
        idx = self._scene_idx_for_id(sid) if sid else None
        trig["event"] = int(idx if idx is not None else 0) & 0xFF

    def _refresh_trigger_scene_combo(self) -> None:
        cmb = getattr(self, "_combo_trig_scene", None)
        if cmb is None:
            return
        cmb.blockSignals(True)
        try:
            cmb.clear()
            for i, s in enumerate(self._project_scenes):
                label = str(s.get("label") or "?")
                sid = str(s.get("id") or "").strip()
                cmb.addItem(f"[{i}] {label}", sid)
        finally:
            cmb.blockSignals(False)

    def _refresh_trigger_bgm_combo(self) -> None:
        cmb = getattr(self, "_combo_trig_bgm", None)
        if cmb is None:
            return
        cmb.blockSignals(True)
        try:
            cmb.clear()
            for song in self._project_songs:
                label = f"[{song.idx}] {song.name or song.song_id or '?'}"
                cmb.addItem(label, int(song.idx))
        finally:
            cmb.blockSignals(False)

    def _refresh_trigger_sfx_combo(self) -> None:
        cmb = getattr(self, "_combo_trig_sfx", None)
        if cmb is None:
            return
        cmb.blockSignals(True)
        try:
            cmb.clear()
            for idx, name in self._project_sfx_map:
                cmb.addItem(f"[{idx}] {name}", int(idx))
        finally:
            cmb.blockSignals(False)

    # ------------------------------------------------------------------
    # Track B — neighbour warps helpers
    # ------------------------------------------------------------------

    def _refresh_neighbor_combos(self, current_values: dict | None = None) -> None:
        """Repopulate all 4 neighbour direction combos from _project_scenes."""
        combo_nb = getattr(self, "_combo_nb", None)
        if combo_nb is None:
            return
        _scene = getattr(self, "_scene", None)
        cur_scene_id = str(_scene.get("id") or "") if _scene else ""
        for dir_key, cmb in combo_nb.items():
            want = str((current_values or {}).get(dir_key) or "") if current_values else ""
            cmb.blockSignals(True)
            try:
                cmb.clear()
                cmb.addItem(tr("level.nb_none"), "")
                for s in getattr(self, "_project_scenes", []):
                    sid = str(s.get("id") or "").strip()
                    if not sid or sid == cur_scene_id:
                        continue
                    label = str(s.get("label") or sid)
                    cmb.addItem(label, sid)
                idx = cmb.findData(want)
                cmb.setCurrentIndex(idx if idx >= 0 else 0)
            finally:
                cmb.blockSignals(False)

    def _collect_neighbors(self) -> dict:
        """Return neighbors dict {direction: scene_id} from UI combos (omit empty)."""
        combo_nb = getattr(self, "_combo_nb", None)
        if combo_nb is None:
            return {}
        result: dict[str, str] = {}
        for dir_key, cmb in combo_nb.items():
            sid = str(cmb.currentData() or "").strip()
            if sid:
                result[dir_key] = sid
        return result

    def _on_neighbors_changed(self) -> None:
        """Called when any neighbour combo changes — persists to scene immediately."""
        if self._scene is None:
            return
        nb = self._collect_neighbors()
        if nb:
            self._scene["neighbors"] = nb
        else:
            self._scene.pop("neighbors", None)

    # ------------------------------------------------------------------
    # Track A — chunk map grid helpers
    # ------------------------------------------------------------------

    def _tilemap_rel_paths(self) -> list[str]:
        """Return relative paths of all tilemaps in the current scene."""
        scene = getattr(self, "_scene", None)
        if scene is None:
            return []
        paths: list[str] = []
        for tm in (scene.get("tilemaps") or []):
            p = str(tm.get("path") or "").strip()
            if p:
                paths.append(p)
        return paths

    def _rebuild_chunk_grid_table(self, rows: int, cols: int) -> None:
        """Rebuild _tbl_chunk_grid with QComboBox cells, preserving existing values."""
        tbl = getattr(self, "_tbl_chunk_grid", None)
        if tbl is None:
            return
        # Capture existing values before rebuild
        old_vals: list[list[str]] = []
        for r in range(tbl.rowCount()):
            row_vals: list[str] = []
            for c in range(tbl.columnCount()):
                w = tbl.cellWidget(r, c)
                row_vals.append(str(w.currentData() or "") if w else "")
            old_vals.append(row_vals)

        tilemap_paths = self._tilemap_rel_paths()
        tbl.blockSignals(True)
        try:
            tbl.setRowCount(rows)
            tbl.setColumnCount(cols)
            for r in range(rows):
                for c in range(cols):
                    cmb = QComboBox()
                    cmb.addItem(tr("level.chunk_none"), "")
                    for p in tilemap_paths:
                        cmb.addItem(p, p)
                    want = old_vals[r][c] if r < len(old_vals) and c < len(old_vals[r]) else ""
                    idx = cmb.findData(want)
                    cmb.setCurrentIndex(idx if idx >= 0 else 0)
                    cmb.currentIndexChanged.connect(self._on_chunk_grid_changed)
                    tbl.setCellWidget(r, c, cmb)
        finally:
            tbl.blockSignals(False)
        # Adjust height to content
        row_h = 26 * rows + 4
        tbl.setFixedHeight(min(row_h, 120))

    def _on_chunk_grid_size_changed(self) -> None:
        rows = int(getattr(self, "_spin_chunk_rows", None) and self._spin_chunk_rows.value() or 1)
        cols = int(getattr(self, "_spin_chunk_cols", None) and self._spin_chunk_cols.value() or 1)
        self._rebuild_chunk_grid_table(rows, cols)
        self._on_chunk_grid_changed()

    def _on_chunk_grid_changed(self) -> None:
        """Persist chunk map to scene immediately."""
        if self._scene is None:
            return
        cmap = self._collect_bg_chunk_map()
        if cmap:
            self._scene["bg_chunk_map"] = cmap
        else:
            self._scene.pop("bg_chunk_map", None)

    def _collect_bg_chunk_map(self) -> dict:
        """Return {'grid': [[rel_path, ...], ...]} from table (omit if all empty)."""
        tbl = getattr(self, "_tbl_chunk_grid", None)
        if tbl is None:
            return {}
        grid: list[list[str]] = []
        any_set = False
        for r in range(tbl.rowCount()):
            row: list[str] = []
            for c in range(tbl.columnCount()):
                w = tbl.cellWidget(r, c)
                val = str(w.currentData() or "") if w else ""
                row.append(val)
                if val:
                    any_set = True
            grid.append(row)
        return {"grid": grid} if any_set else {}

    def _load_chunk_map_ui(self, bg_chunk_map: dict) -> None:
        """Populate chunk grid table from scene data."""
        grid = bg_chunk_map.get("grid") if isinstance(bg_chunk_map, dict) else None
        if not grid or not isinstance(grid, list):
            self._spin_chunk_rows.blockSignals(True)
            self._spin_chunk_cols.blockSignals(True)
            self._spin_chunk_rows.setValue(1)
            self._spin_chunk_cols.setValue(1)
            self._spin_chunk_rows.blockSignals(False)
            self._spin_chunk_cols.blockSignals(False)
            self._rebuild_chunk_grid_table(1, 1)
            return
        rows = len(grid)
        cols = max((len(row) for row in grid if isinstance(row, list)), default=1)
        self._spin_chunk_rows.blockSignals(True)
        self._spin_chunk_cols.blockSignals(True)
        self._spin_chunk_rows.setValue(max(1, min(8, rows)))
        self._spin_chunk_cols.setValue(max(1, min(8, cols)))
        self._spin_chunk_rows.blockSignals(False)
        self._spin_chunk_cols.blockSignals(False)
        self._rebuild_chunk_grid_table(rows, cols)
        # Set values
        tbl = self._tbl_chunk_grid
        tilemap_paths = self._tilemap_rel_paths()
        for r, row in enumerate(grid):
            if not isinstance(row, list) or r >= tbl.rowCount():
                continue
            for c, val in enumerate(row):
                if c >= tbl.columnCount():
                    continue
                w = tbl.cellWidget(r, c)
                if w is None:
                    continue
                val_str = str(val or "").strip()
                # Add the path if not already in combo (e.g. path referenced but not yet in scene)
                if val_str and w.findData(val_str) < 0:
                    w.addItem(val_str, val_str)
                idx = w.findData(val_str)
                w.blockSignals(True)
                w.setCurrentIndex(idx if idx >= 0 else 0)
                w.blockSignals(False)

    def set_scene(self, scene: dict | None, base_dir: Path | None, project_data: dict | None = None) -> None:
        """Load a scene into the level editor and rebuild all derived UI state."""
        self._set_project_scenes(project_data)
        self._scene   = scene
        self._base_dir = base_dir

        self._type_names.clear()
        self._type_pixmaps.clear()
        self._type_sizes.clear()
        self._type_list_pixmaps.clear()
        self._type_list.clear()
        self._bg_pixmap_scr1 = None
        self._bg_pixmap_scr2 = None
        self._bg_paths  = [None]
        self._bg_rels   = [None]
        self._bg_plane_hints = {}
        self._bg_front  = "scr1"
        self._selected  = -1
        self._entity_roles = {}
        self._level_profile = "none"
        self._waves = []
        self._wave_selected   = -1
        self._wave_edit       = False
        self._wave_entity_sel = -1
        self._scene_tool      = "entity"
        self._regions = []
        self._region_selected = -1
        self._region_edit = False
        self._text_labels = []
        self._text_label_selected = -1
        self._triggers = []
        self._trigger_selected = -1
        self._paths = []
        self._path_selected = -1
        self._path_edit = False
        self._path_point_selected = -1
        self._pick_dest_mode = False
        self._layers_cfg = {
            "scr1_parallax_x": 100,
            "scr1_parallax_y": 100,
            "scr2_parallax_x": 100,
            "scr2_parallax_y": 100,
            "bg_front": "scr1",
        }
        if hasattr(self, "_tbl_palfx"):
            self._tbl_palfx.setRowCount(0)
        self._col_map = None
        self._col_map_tilemap_cache = None
        self._clear_col_map_import_meta()
        self._tile_ids = {}
        self._map_mode = "none"
        self._cam_tile: tuple[int, int] = (0, 0)
        self._scroll_cfg: dict = {
            "scroll_x": False,
            "scroll_y": False,
            "forced":   False,
            "speed_x":  0,
            "speed_y":  0,
            "loop_x":   False,
            "loop_y":   False,
        }
        self._layout_cfg = {
            "cam_mode": "single_screen",
            "bounds_auto": True,
            "clamp": True,
            "min_x": 0,
            "min_y": 0,
            "max_x": 0,
            "max_y": 0,
            "follow_deadzone_x": 16,
            "follow_deadzone_y": 12,
            "follow_drop_margin_y": 20,
            "cam_lag": 0,
        }

        self._set_scene_tool("entity")

        self._combo_bg_scr1.blockSignals(True)
        self._combo_bg_scr2.blockSignals(True)
        self._combo_bg_front.blockSignals(True)
        self._combo_bg_scr1.clear()
        self._combo_bg_scr2.clear()
        self._combo_bg_scr1.addItem(tr("level.bg_none"))
        self._combo_bg_scr2.addItem(tr("level.bg_none"))
        self._combo_bg_scr1.blockSignals(False)
        self._combo_bg_scr2.blockSignals(False)
        self._combo_bg_front.setCurrentIndex(0)
        self._combo_bg_front.blockSignals(False)

        # Reset procgen UI state (will be reloaded from scene if present)
        self._combo_map_mode.blockSignals(True)
        idx_none = self._combo_map_mode.findData("none")
        if idx_none >= 0:
            self._combo_map_mode.setCurrentIndex(idx_none)
        self._combo_map_mode.blockSignals(False)
        self._open_density_widget.setVisible(False)
        self._td_mode_widget.setVisible(False)
        self._chk_td_ca.setVisible(False)
        self._td_scatter_widget.setVisible(False)
        self._td_bsp_widget.setVisible(False)
        self._chk_dir_walls.setVisible(False)
        self._topdown_features_widget.setVisible(False)
        self._wall_dens_widget.setVisible(False)
        self._tile_role_scroll.setVisible(False)

        if scene is None:
            self._entities = []
            self._lbl_status.setText(tr("level.no_scene"))
            self._canvas.update()
            self._update_budget()
            self._refresh_wave_list()
            self._refresh_region_list()
            self._refresh_region_props()
            self._refresh_text_labels_ui()
            self._refresh_trigger_list()
            self._refresh_trigger_props()
            self._refresh_path_list()
            self._refresh_path_props()
            try:
                self._combo_profile.setCurrentIndex(0)
            except Exception:
                pass
            # Layout defaults
            self._spin_cam_x.setValue(int(self._bezel_tile[0]))
            self._spin_cam_y.setValue(int(self._bezel_tile[1]))
            self._chk_scroll_x.setChecked(False)
            self._chk_scroll_y.setChecked(False)
            self._chk_forced_scroll.setChecked(False)
            self._spin_speed_x.setValue(0)
            self._spin_speed_y.setValue(0)
            self._chk_loop_x.setChecked(False)
            self._chk_loop_y.setChecked(False)
            try:
                self._combo_cam_mode.setCurrentIndex(0)
            except Exception:
                pass
            self._chk_cam_clamp.setChecked(True)
            self._chk_cam_bounds_auto.setChecked(True)
            self._cam_bounds_from_map()
            self._spin_cam_deadzone_x.setValue(16)
            self._spin_cam_deadzone_y.setValue(12)
            self._spin_cam_drop_margin_y.setValue(20)
            self._spin_cam_lag.setValue(0)
            self._on_layout_changed()
            # Layers defaults
            try:
                self._spin_scr1_par_x.setValue(100)
                self._spin_scr1_par_y.setValue(100)
                self._spin_scr2_par_x.setValue(100)
                self._spin_scr2_par_y.setValue(100)
            except Exception:
                pass
            self._on_layers_changed()
            # Rules defaults
            try:
                self._chk_rule_lock_y.setChecked(False)
                self._spin_rule_lock_y.setValue(0)
                self._chk_rule_ground_band.setChecked(False)
                self._spin_rule_ground_min.setValue(0)
                self._spin_rule_ground_max.setValue(max(0, int(self._grid_h) - 1))
                self._chk_rule_mirror.setChecked(False)
                self._spin_rule_mirror_axis.setValue(max(0, (int(self._grid_w) - 1) // 2))
                self._chk_rule_apply_waves.setChecked(True)
                self._spin_rule_hazard_damage.setValue(1)
                self._spin_rule_fire_damage.setValue(1)
                self._chk_rule_void_instant.setChecked(True)
                self._spin_rule_void_damage.setValue(255)
                self._spin_rule_hazard_invul.setValue(30)
                self._chk_rule_hud_hp.setChecked(False)
                self._chk_rule_hud_score.setChecked(True)
                self._chk_rule_hud_collect.setChecked(True)
                self._chk_rule_hud_timer.setChecked(False)
                self._chk_rule_hud_lives.setChecked(False)
                self._combo_rule_hud_pos.setCurrentIndex(0)
                self._combo_rule_hud_font.setCurrentIndex(0)
                self._combo_rule_hud_fixed_plane.setCurrentIndex(0)
                self._combo_rule_hud_text_color.setCurrentIndex(0)
                self._combo_rule_hud_style.setCurrentIndex(0)
                idx_band = self._combo_rule_hud_band_color.findData("blue")
                self._combo_rule_hud_band_color.setCurrentIndex(idx_band if idx_band >= 0 else 0)
                self._spin_rule_hud_band_rows.setValue(2)
                self._spin_rule_hud_digits_hp.setValue(2)
                self._spin_rule_hud_digits_score.setValue(5)
                self._spin_rule_hud_digits_collect.setValue(3)
                self._spin_rule_hud_digits_timer.setValue(3)
                self._spin_rule_hud_digits_lives.setValue(2)
                self._spin_rule_hud_digits_continues.setValue(2)
                self._spin_rule_goal_collectibles.setValue(0)
                self._spin_rule_time_limit.setValue(0)
                self._spin_rule_start_lives.setValue(0)
                self._spin_rule_start_continues.setValue(0)
            except Exception:
                pass
            self._on_rules_changed()
            self._refresh_neighbor_combos()
            self._load_chunk_map_ui({})
            return

        # Load entities, roles, waves
        self._entities     = [self._sanitize_entity(e) for e in scene.get("entities", [])]
        self._ensure_entity_ids()
        self._entity_roles = migrate_scene_sprite_roles(scene)

        # Game profile (optional)
        prof = str(scene.get("level_profile", "none") or "none").strip()
        known = {k for k, _ in _LEVEL_PROFILES}
        if prof not in known:
            prof = "none"
        self._level_profile = prof
        try:
            idx = self._combo_profile.findData(prof)
            self._combo_profile.blockSignals(True)
            self._combo_profile.setCurrentIndex(idx if idx >= 0 else 0)
            self._combo_profile.blockSignals(False)
        except Exception:
            pass
        self._apply_genre_combo_order(prof)

        raw_waves = scene.get("waves", []) or []
        self._waves = [
            {"delay": int(w.get("delay", 0)),
              "entities": [self._sanitize_entity(e) for e in w.get("entities", [])]}
            for w in raw_waves
        ]

        raw_regs = scene.get("regions", []) or []
        _reg_list = []
        for r in raw_regs:
            if not isinstance(r, dict):
                continue
            rd = {"id": str(r.get("id") or "") or _new_id(),
                  "name": str(r.get("name", "")),
                  "kind": str(r.get("kind", "zone") or "zone"),
                  "x": int(r.get("x", 0)),
                  "y": int(r.get("y", 0)),
                  "w": max(1, int(r.get("w", 1))),
                  "h": max(1, int(r.get("h", 1)))}
            if r.get("kind") == "lap_gate":
                rd["gate_index"] = max(0, min(31, int(r.get("gate_index", 0))))
            if r.get("kind") == "race_waypoint":
                rd["wp_index"] = max(0, min(63, int(r.get("wp_index", 0))))
            if r.get("kind") == "card_slot":
                rd["slot_type"] = max(0, min(15, int(r.get("slot_type", 0))))
            _reg_list.append(rd)
        self._regions = _reg_list

        raw_lbls = scene.get("text_labels", []) or []
        self._text_labels = [
            {"id": str(l.get("id") or "") or uuid.uuid4().hex[:8],
             "text": str(l.get("text") or "")[:20],
             "x": max(0, min(19, int(l.get("x", 0)))),
             "y": max(0, min(18, int(l.get("y", 0)))),
             "pal": max(0, min(15, int(l.get("pal", 0)))),
             "plane": "scr2" if str(l.get("plane", "scr1") or "scr1").lower() == "scr2" else "scr1"}
            for l in raw_lbls if isinstance(l, dict)
        ]
        self._text_label_selected = -1

        raw_tr = scene.get("triggers", []) or []
        self._triggers = [
            {"id": str(t.get("id") or "") or _new_id(),
             "name": str(t.get("name", "")),
             "cond": str(t.get("cond", "enter_region") or "enter_region"),
             "region_id": str(t.get("region_id", "") or ""),
             "value": int(t.get("value", 0) or 0),
             "action": str(t.get("action", "") or "").strip().lower() or "emit_event",
             "scene_to": str(t.get("scene_to", "") or ""),
             "spawn_index": int(t.get("spawn_index", 0) or 0),
             "target_id": str(t.get("target_id", "") or ""),
             "entity_target_id": str(t.get("entity_target_id", "") or ""),
             "entity_index": int(t.get("entity_index", t.get("event", 0)) or 0),
             "dest_region_id": str(t.get("dest_region_id", "") or ""),
             "dest_tile_x": int(t.get("dest_tile_x", -1) if t.get("dest_tile_x") is not None else -1),
             "dest_tile_y": int(t.get("dest_tile_y", -1) if t.get("dest_tile_y") is not None else -1),
             "dialogue_id": str(t.get("dialogue_id", "") or ""),
             "cond_dialogue_id": str(t.get("cond_dialogue_id", "") or ""),
             "choice_idx": int(t.get("choice_idx", 0) or 0),
             "npc_dialogue_id": str(t.get("npc_dialogue_id", "") or ""),
             "menu_id": str(t.get("menu_id", "") or ""),
             "event": int(t.get("event", 0) or 0),
             "param": int(t.get("param", 0) or 0),
             "once": bool(t.get("once", True)),
             "value_const": str(t.get("value_const", "") or ""),
             "flag_var_index": int(t.get("flag_var_index", 0) or 0),
             "extra_conds": copy.deepcopy(t.get("extra_conds", []) or []),
             "or_groups": copy.deepcopy(t.get("or_groups", []) or [])}
            for t in raw_tr if isinstance(t, dict)
        ]
        # Back-compat: map legacy numeric index -> stable scene id (if possible).
        for t in self._triggers:
            if not isinstance(t, dict):
                continue
            if str(t.get("action") or "").strip().lower() != "goto_scene":
                continue
            if str(t.get("scene_to") or "").strip():
                continue
            sid = self._scene_id_for_idx(int(t.get("event", 0) or 0))
            if sid:
                t["scene_to"] = sid
        self._normalize_trigger_entity_refs()
        self._refresh_trigger_regions()

        raw_paths = scene.get("paths", []) or []
        self._paths = []
        for p in raw_paths:
            if not isinstance(p, dict):
                continue
            pts_in = p.get("points", []) or []
            pts: list[dict] = []
            if isinstance(pts_in, list):
                for pt in pts_in:
                    px, py = _path_point_to_px(pt)
                    pts.append(_path_point_make(px, py))
            self._paths.append({
                "id": str(p.get("id") or "") or _new_id(),
                "name": str(p.get("name", "")),
                "loop": bool(p.get("loop", False)),
                "speed": max(1, min(8, int(p.get("speed", 1) or 1))),
                "points": pts,
            })

        # Load entity types using one gameplay frame as preview/placement size.
        for spr in scene.get("sprites", []) or []:
            rel = spr.get("file", "")
            if not rel:
                continue
            p = Path(rel)
            if base_dir and not p.is_absolute():
                p = base_dir / p
            name = p.stem
            if name not in self._type_names:
                self._type_names.append(name)
                try:
                    from PIL import Image as _PILImg
                    img = _PILImg.open(p).convert("RGBA")
                    iw, ih = img.width, img.height
                    fw = max(1, int(spr.get("frame_w", 8) or 8))
                    fh = max(1, int(spr.get("frame_h", 8) or 8))
                    fc = max(1, int(spr.get("frame_count", 1) or 1))
                    fw = min(fw, iw) if iw > 0 else fw
                    fh = min(fh, ih) if ih > 0 else fh
                    self._type_sizes[name] = (fw, fh)
                    src = img.crop((0, 0, fw, fh))
                    src.thumbnail((_THUMB_SRC_PX, _THUMB_SRC_PX), _PILImg.NEAREST)
                    self._type_pixmaps[name] = _pil_to_qpixmap(src)
                    ico = img.crop((0, 0, fw, fh))
                    ico.thumbnail((32, 32), _PILImg.NEAREST)
                    pm_list = _pil_to_qpixmap(ico)
                    self._type_list_pixmaps[name] = pm_list
                    item = QListWidgetItem(QIcon(pm_list), f"{name}  ({fw}×{fh}, {fc}f)")
                except Exception:
                    self._type_sizes[name] = (_TILE_PX, _TILE_PX)
                    item = QListWidgetItem(name)
                item.setData(Qt.ItemDataRole.UserRole, name)
                role = self._entity_roles.get(name, "prop")
                self._update_type_item_label(item, name, role)
                self._type_list.addItem(item)
        if self._type_list.count() > 0:
            try:
                self._type_list.setCurrentRow(0)
            except Exception:
                pass
        else:
            try:
                self._combo_role.setCurrentIndex(len(_ROLES) - 1)
            except Exception:
                pass
        self._refresh_type_starter_ui()

        # Background combos (SCR1/SCR2 preview)
        self._bg_paths = [None]
        self._bg_rels  = [None]
        self._bg_plane_hints = {}
        self._combo_bg_scr1.blockSignals(True)
        self._combo_bg_scr2.blockSignals(True)
        self._combo_bg_front.blockSignals(True)
        self._combo_bg_scr1.clear()
        self._combo_bg_scr2.clear()
        self._combo_bg_scr1.addItem(tr("level.bg_none"))
        self._combo_bg_scr2.addItem(tr("level.bg_none"))

        tilemaps = scene.get("tilemaps", []) or []
        plane_scr1_rel: str | None = None
        plane_scr2_rel: str | None = None
        for tm in tilemaps:
            if not isinstance(tm, dict):
                continue
            rel = str(tm.get("file", "") or "").strip()
            if not rel:
                continue
            p = Path(rel)
            if base_dir and not p.is_absolute():
                p = base_dir / p
            self._bg_paths.append(p)
            self._bg_rels.append(rel)
            tm_plane = str(tm.get("plane", "auto") or "auto").lower()
            self._bg_plane_hints[rel] = tm_plane
            self._combo_bg_scr1.addItem(p.name)
            self._combo_bg_scr2.addItem(p.name)
            if plane_scr1_rel is None and tm_plane == "scr1":
                plane_scr1_rel = rel
            if plane_scr2_rel is None and tm_plane == "scr2":
                plane_scr2_rel = rel

        want_scr1 = str(scene.get("level_bg_scr1") or "").strip() or plane_scr1_rel or ""
        want_scr2 = str(scene.get("level_bg_scr2") or "").strip() or plane_scr2_rel or ""
        want_front = str(scene.get("level_bg_front") or "scr1").strip().lower()
        if want_front not in ("scr1", "scr2"):
            want_front = "scr1"
        self._bg_front = want_front

        def _idx_for_rel(want: str) -> int:
            if not want:
                return 0
            for i, r in enumerate(self._bg_rels):
                if r == want:
                    return i
            return 0

        self._combo_bg_scr1.setCurrentIndex(_idx_for_rel(want_scr1))
        self._combo_bg_scr2.setCurrentIndex(_idx_for_rel(want_scr2))
        front_idx = self._combo_bg_front.findData(self._bg_front)
        self._combo_bg_front.setCurrentIndex(front_idx if front_idx >= 0 else 0)

        self._combo_bg_scr1.blockSignals(False)
        self._combo_bg_scr2.blockSignals(False)
        self._combo_bg_front.blockSignals(False)

        self._on_bg_scr1_changed(int(self._combo_bg_scr1.currentIndex()))
        self._on_bg_scr2_changed(int(self._combo_bg_scr2.currentIndex()))
        self._on_bg_front_changed(int(self._combo_bg_front.currentIndex()))

        # Grid size
        size = scene.get("level_size", {})
        gw = int(size.get("w", _SCREEN_W))
        gh = int(size.get("h", _SCREEN_H))
        self._grid_w = gw
        self._grid_h = gh
        self._spin_gw.blockSignals(True)
        self._spin_gh.blockSignals(True)
        self._spin_gw.setValue(gw)
        self._spin_gh.setValue(gh)
        self._spin_gw.blockSignals(False)
        self._spin_gh.blockSignals(False)
        self._on_size_changed()

        # Auto-fill symbol
        scene_name = scene.get("name", "scene")
        safe = re.sub(r"[^a-zA-Z0-9]+", "_", scene_name).strip("_").lower()
        self._edit_sym.setText(safe)

        # Load procgen / collision metadata
        self._tile_ids = copy.deepcopy(scene.get("tile_ids", {}) or {})
        self._map_mode = str(scene.get("map_mode", "none") or "none")
        mm_idx = self._combo_map_mode.findData(self._map_mode)
        if mm_idx < 0:
            self._map_mode = "none"
            mm_idx = self._combo_map_mode.findData("none")
        self._combo_map_mode.blockSignals(True)
        if mm_idx >= 0:
            self._combo_map_mode.setCurrentIndex(mm_idx)
        self._combo_map_mode.blockSignals(False)
        self._on_map_mode_changed(self._combo_map_mode.currentIndex())

        # ── Restore procgen UI params ─────────────────────────────────
        pp = scene.get("procgen_params")
        if isinstance(pp, dict) and pp:
            try:
                self._spin_seed.setValue(int(pp.get("seed", 42)))
                self._spin_margin.setValue(int(pp.get("margin", 1)))
                self._spin_enemy_dens.setValue(int(pp.get("enemy_dens", 10)))
                self._spin_item_dens.setValue(int(pp.get("item_dens", 5)))
                self._spin_open_dens.setValue(int(pp.get("open_dens", 20)))
                self._spin_td_bsp_depth.setValue(int(pp.get("td_bsp_depth", 4)))
                self._spin_td_loop_pct.setValue(int(pp.get("td_loop_pct", 15)))
                self._spin_td_bsp_out_w.setValue(int(pp.get("td_bsp_out_w", 0)))
                self._spin_td_bsp_out_h.setValue(int(pp.get("td_bsp_out_h", 0)))
                self._spin_td_bsp_sprite.setValue(int(pp.get("td_bsp_sprite", 1)))
                self._spin_td_scatter_out_w.setValue(int(pp.get("td_scatter_out_w", 20)))
                self._spin_td_scatter_out_h.setValue(int(pp.get("td_scatter_out_h", 18)))
                self._spin_wall_dens.setValue(int(pp.get("wall_dens", 20)))
                self._chk_td_ca.setChecked(bool(pp.get("td_ca", True)))
                self._chk_dir_walls.setChecked(bool(pp.get("dir_walls", True)))
                self._chk_td_int_walls.setChecked(bool(pp.get("td_int_walls", True)))
                self._chk_td_water.setChecked(bool(pp.get("td_water", True)))
                self._chk_td_border_n.setChecked(bool(pp.get("td_border_n", True)))
                self._chk_td_border_s.setChecked(bool(pp.get("td_border_s", True)))
                self._chk_td_border_e.setChecked(bool(pp.get("td_border_e", True)))
                self._chk_td_border_w.setChecked(bool(pp.get("td_border_w", True)))
                self._chk_gen_tilemaps.setChecked(bool(pp.get("gen_tilemaps", True)))
                self._chk_gen_scr1.setChecked(bool(pp.get("gen_scr1", True)))
                self._chk_gen_scr2.setChecked(bool(pp.get("gen_scr2", False)))
                ts_idx = self._combo_tile_src.findData(pp.get("tile_src", "auto"))
                if ts_idx >= 0:
                    self._combo_tile_src.setCurrentIndex(ts_idx)
                td_idx = self._combo_td_gen_mode.findData(pp.get("td_gen_mode", "scatter"))
                if td_idx >= 0:
                    self._combo_td_gen_mode.setCurrentIndex(td_idx)
            except Exception:
                pass

        # ── Restore runtime DungeonGen params ────────────────────────
        dg = scene.get("rt_dungeongen_params")
        self._chk_dgen_enabled.setChecked(isinstance(dg, dict) and bool(dg.get("enabled", False)))
        if isinstance(dg, dict) and dg:
            try:
                _seed_mode = dg.get("seed_mode", "rtc")
                _seed_idx = 1 if _seed_mode == "fixed" else 0
                self._combo_dgen_seed_mode.setCurrentIndex(_seed_idx)
                self._spin_dgen_seed_value.setValue(max(1, min(65535, int(dg.get("seed_fixed", 1)))))
                self._spin_dgen_seed_value.setEnabled(_seed_mode == "fixed")
                self._spin_dgen_mw_min.setValue(max(4, min(32, int(dg.get("room_mw_min", 10)))))
                self._spin_dgen_mw_max.setValue(max(4, min(32, int(dg.get("room_mw_max", 16)))))
                self._spin_dgen_mh_min.setValue(max(4, min(32, int(dg.get("room_mh_min", 10)))))
                self._spin_dgen_mh_max.setValue(max(4, min(32, int(dg.get("room_mh_max", 16)))))
                self._spin_dgen_max_exits.setValue(max(0, min(4, int(dg.get("max_exits", 4)))))
                self._spin_dgen_cell_w.setValue(max(1, min(4, int(dg.get("cell_w_tiles", 2)))))
                self._spin_dgen_cell_h.setValue(max(1, min(4, int(dg.get("cell_h_tiles", 2)))))
                self._spin_dgen_gpc1.setValue(int(dg.get("ground_pct_1", 70)))
                self._spin_dgen_gpc2.setValue(int(dg.get("ground_pct_2", 20)))
                self._spin_dgen_gpc3.setValue(int(dg.get("ground_pct_3", 10)))
                self._spin_dgen_eau_freq.setValue(int(dg.get("eau_freq", 40)))
                self._spin_dgen_vide_freq.setValue(int(dg.get("vide_freq", 30)))
                self._spin_dgen_vide_margin.setValue(int(dg.get("vide_margin", 3)))
                self._spin_dgen_tonneau_freq.setValue(int(dg.get("tonneau_freq", 50)))
                self._spin_dgen_tonneau_max.setValue(max(1, min(2, int(dg.get("tonneau_max", 2)))))
                self._spin_dgen_escalier_freq.setValue(int(dg.get("escalier_freq", 0)))
                self._spin_dgen_enemy_min.setValue(int(dg.get("enemy_min", 0)))
                self._spin_dgen_enemy_max.setValue(int(dg.get("enemy_max", 3)))
                self._spin_dgen_enemy_density.setValue(max(1, int(dg.get("enemy_density", 16))))
                self._spin_dgen_ene2_pct.setValue(max(0, min(100, int(dg.get("ene2_pct", 50)))))
                self._spin_dgen_item_freq.setValue(int(dg.get("item_freq", 50)))
                self._spin_dgen_n_rooms.setValue(max(0, int(dg.get("n_rooms", 0))))
                self._spin_dgen_enemy_ramp_rooms.setValue(max(0, int(dg.get("enemy_ramp_rooms", 0))))
                self._spin_dgen_safe_room_every.setValue(max(0, int(dg.get("safe_room_every", 0))))
                self._spin_dgen_min_exits.setValue(max(0, min(4, int(dg.get("min_exits", 0)))))
                self._spin_dgen_cluster_size_max.setValue(max(2, min(4, int(dg.get("cluster_size_max", 4)))))
                self._spin_dgen_tier_cols.setValue(max(0, int(dg.get("tier_cols", 0))))
                def _fmt_tier_row(key: str) -> str:
                    vals = dg.get(key, [])
                    return ", ".join(str(v) for v in vals) if vals else ""
                self._edit_dgen_tier_ene_max.setText(_fmt_tier_row("tier_ene_max"))
                self._edit_dgen_tier_item_freq.setText(_fmt_tier_row("tier_item_freq"))
                self._edit_dgen_tier_eau_freq.setText(_fmt_tier_row("tier_eau_freq"))
                self._edit_dgen_tier_vide_freq.setText(_fmt_tier_row("tier_vide_freq"))
                self._chk_dgen_multifloor.setChecked(bool(dg.get("multifloor", False)))
                self._spin_dgen_floor_var.setValue(max(0, min(7, int(dg.get("floor_var", 0)))))
                self._spin_dgen_max_floors.setValue(int(dg.get("max_floors", 0)))
                bs_idx = self._combo_dgen_boss_scene.findData(dg.get("boss_scene", ""))
                if bs_idx >= 0:
                    self._combo_dgen_boss_scene.setCurrentIndex(bs_idx)
                # Pool ennemis / items
                self._set_dgen_pool(
                    getattr(self, "_tbl_dgen_ene_pool",  None) or QTableWidget(),
                    "enemy", dg.get("enemy_pool", []) or [], has_max=True)
                self._set_dgen_pool(
                    getattr(self, "_tbl_dgen_item_pool", None) or QTableWidget(),
                    "item",  dg.get("item_pool",  []) or [], has_max=False)
                # Player selector
                _pc = getattr(self, "_combo_dgen_player", None)
                if _pc is not None:
                    _pid_idx = _pc.findData(dg.get("player_entity_id", ""))
                    _pc.setCurrentIndex(_pid_idx if _pid_idx >= 0 else 0)
                # Comportement eau
                _wc = dg.get("water_behavior", "water")
                _wc_idx = self._combo_dgen_water_col.findData(_wc)
                self._combo_dgen_water_col.setCurrentIndex(_wc_idx if _wc_idx >= 0 else 1)
                # Comportement trou
                _vb = dg.get("void_behavior", "death")
                _vb_idx = self._combo_dgen_void_behavior.findData(_vb)
                self._combo_dgen_void_behavior.setCurrentIndex(_vb_idx if _vb_idx >= 0 else 0)
                self._spin_dgen_void_damage.setValue(max(0, min(255, int(dg.get("void_damage", 0)))))
                _vs_id = dg.get("void_scene", "")
                _vs_idx = self._combo_dgen_void_scene.findData(_vs_id)
                self._combo_dgen_void_scene.setCurrentIndex(_vs_idx if _vs_idx >= 0 else 0)
                # Mettre à jour la visibilité des widgets conditionnels
                _vb_mode = self._combo_dgen_void_behavior.currentData()
                self._wdg_void_scene_row.setVisible(_vb_mode == "scene")
                self._wdg_void_damage_row.setVisible(_vb_mode != "death")
            except Exception:
                pass

        # ── Restore runtime DFS params ────────────────────────────────
        dp = scene.get("rt_dfs_params")
        self._chk_dfs_enabled.setChecked(isinstance(dp, dict) and bool(dp.get("enabled", False)))
        if isinstance(dp, dict) and dp:
            try:
                self._spin_dfs_grid_w.setValue(int(dp.get("grid_w", 4)))
                self._spin_dfs_grid_h.setValue(int(dp.get("grid_h", 4)))
                self._spin_dfs_room_w.setValue(max(20, min(32, int(dp.get("room_w", 20)))))
                self._spin_dfs_room_h.setValue(max(19, min(32, int(dp.get("room_h", 19)))))
                self._spin_dfs_max_enemies.setValue(int(dp.get("max_enemies", 4)))
                self._spin_dfs_item_chance.setValue(int(dp.get("item_chance", 25)))
                self._spin_dfs_loop_pct.setValue(int(dp.get("loop_pct", 20)))
                self._spin_dfs_max_active.setValue(int(dp.get("max_active", 8)))
                sm_idx = self._combo_dfs_start_mode.findData(dp.get("start_mode", "corner"))
                if sm_idx >= 0:
                    self._combo_dfs_start_mode.setCurrentIndex(sm_idx)
                self._chk_dfs_multifloor.setChecked(bool(dp.get("multifloor", False)))
                self._spin_dfs_floor_var.setValue(int(dp.get("floor_var", 0)))
                self._spin_dfs_max_floors.setValue(int(dp.get("max_floors", 0)))
                bs_idx = self._combo_dfs_boss_scene.findData(dp.get("boss_scene", ""))
                if bs_idx >= 0:
                    self._combo_dfs_boss_scene.setCurrentIndex(bs_idx)
                ls_idx = self._combo_dfs_loop_scene.findData(dp.get("loop_scene", ""))
                if ls_idx >= 0:
                    self._combo_dfs_loop_scene.setCurrentIndex(ls_idx)
                self._spin_dfs_tier_count.setValue(int(dp.get("tier_count", 5)))
                self._spin_dfs_floors_per_tier.setValue(int(dp.get("floors_per_tier", 5)))
                tier = dp.get("tier_table")
                if isinstance(tier, list):
                    for r, row_vals in enumerate(tier):
                        if r >= 4 or not isinstance(row_vals, list):
                            break
                        for c, val in enumerate(row_vals):
                            if c >= 5:
                                break
                            self._dfs_tier_table.setItem(r, c, QTableWidgetItem(str(val)))
            except Exception:
                pass

        # ── Restore runtime Cave params ───────────────────────────────
        cp = scene.get("rt_cave_params")
        self._chk_cave_enabled.setChecked(isinstance(cp, dict) and bool(cp.get("enabled", False)))
        if isinstance(cp, dict) and cp:
            try:
                self._spin_cave_wall_pct.setValue(int(cp.get("wall_pct", 45)))
                self._spin_cave_iterations.setValue(int(cp.get("iterations", 5)))
                self._spin_cave_max_enemies.setValue(int(cp.get("max_enemies", 6)))
                self._spin_cave_max_chests.setValue(int(cp.get("max_items", cp.get("max_chests", 2))))
                self._spin_cave_pickup_type.setValue(int(cp.get("pickup_type", 0)))
                self._refresh_cave_item_pool(selected=cp.get("item_pool", []) or [])
                self._chk_cave_multifloor.setChecked(bool(cp.get("multifloor", False)))
                self._spin_cave_floor_var.setValue(int(cp.get("floor_var", 0)))
                self._spin_cave_max_floors.setValue(int(cp.get("max_floors", 0)))
                cb_idx = self._combo_cave_boss_scene.findData(cp.get("boss_scene", ""))
                if cb_idx >= 0:
                    self._combo_cave_boss_scene.setCurrentIndex(cb_idx)
                self._spin_cave_tier_count.setValue(int(cp.get("tier_count", 5)))
                self._spin_cave_floors_per_tier.setValue(int(cp.get("floors_per_tier", 5)))
                tier = cp.get("tier_table")
                if isinstance(tier, list):
                    for r, row_vals in enumerate(tier):
                        if r >= 3 or not isinstance(row_vals, list):
                            break
                        for c, val in enumerate(row_vals):
                            if c >= 5:
                                break
                            self._cave_tier_table.setItem(r, c, QTableWidgetItem(str(val)))
            except Exception:
                pass

        raw_col = scene.get("col_map", None)
        self._clear_col_map_import_meta()
        if isinstance(raw_col, list) and raw_col:
            try:
                col = [[int(v) for v in row] for row in raw_col]
                if len(col) == gh and all(isinstance(r, list) and len(r) == gw for r in col):
                    self._col_map = col
                elif col:
                    # Dimensions mismatch (e.g. grid resized) — resize to fit
                    self._col_map = fit_collision_grid(col, gw, gh)
            except Exception:
                self._col_map = None
        raw_col_meta = scene.get("col_map_meta", {}) or {}
        if isinstance(raw_col_meta, dict):
            self._col_map_meta = copy.deepcopy(raw_col_meta)
        self._restore_col_map_import_base()
        # Auto-import tilemap collision when the scene has no col_map yet.
        # This lets the user define solid tiles once in the tilemap tab and have
        # them appear automatically in the level tab; subsequent manual paints
        # (spring, damage …) are then saved as part of col_map and take priority.
        if self._col_map is None:
            self._auto_import_collision_silent()
        self._refresh_collision_source_ui()

        # Load layout / scroll metadata (optional)
        cam = scene.get("level_cam_tile", {}) or {}
        if isinstance(cam, dict):
            cam_x = int(cam.get("x", self._bezel_tile[0]))
            cam_y = int(cam.get("y", self._bezel_tile[1]))
        else:
            cam_x, cam_y = self._bezel_tile

        # Load bezel position
        bz = scene.get("level_bezel") or {}
        if isinstance(bz, dict):
            self._bezel_tile = (int(bz.get("tx", 0)), int(bz.get("ty", 0)))
        sc = scene.get("level_scroll", {}) or {}
        if not isinstance(sc, dict):
            sc = {}

        # New layout metadata
        layout = scene.get("level_layout", {}) or {}
        if not isinstance(layout, dict):
            layout = {}
        cam_mode = str(layout.get("cam_mode", "") or "").strip()
        if cam_mode not in _CAM_MODE_TO_C:
            # Backward-compat: infer from scroll flags
            if bool(sc.get("forced", False)):
                cam_mode = "forced_scroll"
            elif bool(sc.get("loop_x", False)) or bool(sc.get("loop_y", False)):
                cam_mode = "loop"
            elif bool(sc.get("scroll_x", False)) or bool(sc.get("scroll_y", False)):
                cam_mode = "follow"
            else:
                cam_mode = "single_screen"
        clamp = bool(layout.get("clamp", True))
        bounds_auto = bool(layout.get("bounds_auto", True))
        min_x = int(layout.get("min_x", 0) or 0)
        min_y = int(layout.get("min_y", 0) or 0)
        max_x = int(layout.get("max_x", 0) or 0)
        max_y = int(layout.get("max_y", 0) or 0)
        follow_deadzone_x = _cfg_int(layout, "follow_deadzone_x", 16)
        follow_deadzone_y = _cfg_int(layout, "follow_deadzone_y", 12)
        follow_drop_margin_y = _cfg_int(layout, "follow_drop_margin_y", 20)
        cam_lag = int(layout.get("cam_lag", 0) or 0)
        self._layout_cfg = {
            "cam_mode": cam_mode,
            "bounds_auto": bounds_auto,
            "clamp": clamp,
            "min_x": min_x,
            "min_y": min_y,
            "max_x": max_x,
            "max_y": max_y,
            "follow_deadzone_x": max(0, min(79, follow_deadzone_x)),
            "follow_deadzone_y": max(0, min(71, follow_deadzone_y)),
            "follow_drop_margin_y": max(0, min(71, follow_drop_margin_y)),
            "cam_lag": max(0, min(4, cam_lag)),
        }

        # Layer metadata (parallax)
        layers = scene.get("level_layers", {}) or {}
        if not isinstance(layers, dict):
            layers = {}
        self._layers_cfg = {
            "scr1_parallax_x": _cfg_int(layers, "scr1_parallax_x", 100),
            "scr1_parallax_y": _cfg_int(layers, "scr1_parallax_y", 100),
            "scr2_parallax_x": _cfg_int(layers, "scr2_parallax_x", 100),
            "scr2_parallax_y": _cfg_int(layers, "scr2_parallax_y", 100),
            "bg_front": str(layers.get("bg_front", self._bg_front or "scr1") or (self._bg_front or "scr1")),
        }
        self._load_pal_cycles(scene.get("pal_cycles") or [])

        # Placement rules
        rules = scene.get("level_rules", {}) or {}
        rules = rules if isinstance(rules, dict) else {}
        lock_y = int(rules.get("lock_y", 0) or 0)
        gmin = int(rules.get("ground_min_y", 0) or 0)
        gmax = int(rules.get("ground_max_y", max(0, gh - 1)) or max(0, gh - 1))
        axis = int(rules.get("mirror_axis_x", max(0, (gw - 1) // 2)) or max(0, (gw - 1) // 2))
        lock_y = max(0, min(lock_y, max(0, gh - 1)))
        gmin = max(0, min(gmin, max(0, gh - 1)))
        gmax = max(0, min(gmax, max(0, gh - 1)))
        if gmin > gmax:
            gmax = gmin
        axis = max(0, min(axis, max(0, gw - 1)))
        self._level_rules = {
            "lock_y_en": bool(rules.get("lock_y_en", False)),
            "lock_y": lock_y,
            "ground_band_en": bool(rules.get("ground_band_en", False)),
            "ground_min_y": gmin,
            "ground_max_y": gmax,
            "mirror_en": bool(rules.get("mirror_en", False)),
            "mirror_axis_x": axis,
            "apply_to_waves": bool(rules.get("apply_to_waves", True)),
            "hazard_damage": int(rules.get("hazard_damage", 1) or 1),
            "fire_damage": int(rules.get("fire_damage", 1) or 1),
            "void_damage": int(rules.get("void_damage", 255) or 255),
            "void_instant": bool(rules.get("void_instant", True)),
            "hazard_invul": _cfg_int(rules, "hazard_invul", 30),
            "spring_force": max(0, min(127, _cfg_int(rules, "spring_force", 8))),
            "spring_dir": str(rules.get("spring_dir", "up") or "up"),
            "conveyor_speed": max(1, min(8, int(rules.get("conveyor_speed", 2) or 2))),
            "ice_friction": max(0, min(255, int(rules.get("ice_friction", 0) or 0))),
            "water_drag": max(1, min(8, int(rules.get("water_drag", 2) or 2))),
            "water_damage": max(0, min(255, int(rules.get("water_damage", 0) or 0))),
            "zone_force": max(1, min(8, int(rules.get("zone_force", 2) or 2))),
            "ladder_top_solid": bool(rules.get("ladder_top_solid", False)),
            "ladder_top_exit": bool(rules.get("ladder_top_exit", True)),
            "ladder_side_move": bool(rules.get("ladder_side_move", False)),
            "hud_enabled": bool(rules.get("hud_enabled", False)),
            "hud_show_hp": bool(rules.get("hud_show_hp", False)),
            "hud_show_score": bool(rules.get("hud_show_score", False)),
            "hud_show_collect": bool(rules.get("hud_show_collect", True)),
            "hud_show_timer": bool(rules.get("hud_show_timer", False)),
            "hud_show_lives": bool(rules.get("hud_show_lives", False)),
            "hud_pos": str(rules.get("hud_pos", "top") or "top"),
            "hud_font_mode": str(rules.get("hud_font_mode", "system") or "system"),
            "hud_fixed_plane": str(rules.get("hud_fixed_plane", "none") or "none"),
            "hud_text_color": str(rules.get("hud_text_color", "white") or "white"),
            "hud_style": str(rules.get("hud_style", "text") or "text"),
            "hud_band_color": str(rules.get("hud_band_color", "blue") or "blue"),
            "hud_band_rows": int(rules.get("hud_band_rows", 2) or 2),
            "hud_digits_hp": int(rules.get("hud_digits_hp", 2) or 2),
            "hud_digits_score": int(rules.get("hud_digits_score", 5) or 5),
            "hud_digits_collect": int(rules.get("hud_digits_collect", 3) or 3),
            "hud_digits_timer": int(rules.get("hud_digits_timer", 3) or 3),
            "hud_digits_lives": int(rules.get("hud_digits_lives", 2) or 2),
            "hud_digits_continues": int(rules.get("hud_digits_continues", 2) or 2),
            "goal_collectibles": int(rules.get("goal_collectibles", 0) or 0),
            "time_limit_sec": int(rules.get("time_limit_sec", 0) or 0),
            "start_lives": int(rules.get("start_lives", 0) or 0),
            "start_continues": int(rules.get("start_continues", 0) or 0),
            "continue_restore_lives": int(rules.get("continue_restore_lives", 3) or 0),
            "hud_custom_font_digits": list(rules.get("hud_custom_font_digits", [""] * 10) or [""] * 10),
            "hud_custom_items": copy.deepcopy(rules.get("hud_custom_items", []) or []),
        }

        self._spin_cam_x.blockSignals(True)
        self._spin_cam_y.blockSignals(True)
        self._combo_cam_mode.blockSignals(True)
        self._chk_cam_clamp.blockSignals(True)
        self._chk_cam_bounds_auto.blockSignals(True)
        self._spin_cam_min_x.blockSignals(True)
        self._spin_cam_min_y.blockSignals(True)
        self._spin_cam_max_x.blockSignals(True)
        self._spin_cam_max_y.blockSignals(True)
        self._spin_cam_deadzone_x.blockSignals(True)
        self._spin_cam_deadzone_y.blockSignals(True)
        self._spin_cam_drop_margin_y.blockSignals(True)
        self._spin_cam_lag.blockSignals(True)
        self._chk_scroll_x.blockSignals(True)
        self._chk_scroll_y.blockSignals(True)
        self._chk_forced_scroll.blockSignals(True)
        self._spin_speed_x.blockSignals(True)
        self._spin_speed_y.blockSignals(True)
        self._chk_loop_x.blockSignals(True)
        self._chk_loop_y.blockSignals(True)
        self._spin_scr1_par_x.blockSignals(True)
        self._spin_scr1_par_y.blockSignals(True)
        self._spin_scr2_par_x.blockSignals(True)
        self._spin_scr2_par_y.blockSignals(True)
        self._chk_rule_lock_y.blockSignals(True)
        self._spin_rule_lock_y.blockSignals(True)
        self._chk_rule_ground_band.blockSignals(True)
        self._spin_rule_ground_min.blockSignals(True)
        self._spin_rule_ground_max.blockSignals(True)
        self._chk_rule_mirror.blockSignals(True)
        self._spin_rule_mirror_axis.blockSignals(True)
        self._chk_rule_apply_waves.blockSignals(True)
        self._spin_rule_hazard_damage.blockSignals(True)
        self._spin_rule_fire_damage.blockSignals(True)
        self._chk_rule_void_instant.blockSignals(True)
        self._spin_rule_void_damage.blockSignals(True)
        self._spin_rule_hazard_invul.blockSignals(True)
        self._spin_rule_spring_force.blockSignals(True)
        self._combo_rule_spring_dir.blockSignals(True)
        self._spin_rule_conveyor_speed.blockSignals(True)
        self._spin_rule_ice_friction.blockSignals(True)
        self._spin_rule_water_drag.blockSignals(True)
        self._spin_rule_water_damage.blockSignals(True)
        self._spin_rule_zone_force.blockSignals(True)
        self._chk_rule_ladder_top_solid.blockSignals(True)
        self._chk_rule_ladder_top_exit.blockSignals(True)
        self._chk_rule_ladder_side_move.blockSignals(True)
        self._chk_rule_hud_hp.blockSignals(True)
        self._chk_rule_hud_score.blockSignals(True)
        self._chk_rule_hud_collect.blockSignals(True)
        self._chk_rule_hud_timer.blockSignals(True)
        self._chk_rule_hud_lives.blockSignals(True)
        self._combo_rule_hud_pos.blockSignals(True)
        self._combo_rule_hud_font.blockSignals(True)
        self._combo_rule_hud_fixed_plane.blockSignals(True)
        self._combo_rule_hud_text_color.blockSignals(True)
        self._combo_rule_hud_style.blockSignals(True)
        self._combo_rule_hud_band_color.blockSignals(True)
        self._spin_rule_hud_band_rows.blockSignals(True)
        self._spin_rule_hud_digits_hp.blockSignals(True)
        self._spin_rule_hud_digits_score.blockSignals(True)
        self._spin_rule_hud_digits_collect.blockSignals(True)
        self._spin_rule_hud_digits_timer.blockSignals(True)
        self._spin_rule_hud_digits_lives.blockSignals(True)
        self._spin_rule_hud_digits_continues.blockSignals(True)
        self._spin_rule_goal_collectibles.blockSignals(True)
        self._spin_rule_time_limit.blockSignals(True)
        self._spin_rule_start_lives.blockSignals(True)
        self._spin_rule_start_continues.blockSignals(True)
        self._spin_rule_continue_restore_lives.blockSignals(True)
        try:
            self._spin_cam_x.setValue(cam_x)
            self._spin_cam_y.setValue(cam_y)
            self._chk_scroll_x.setChecked(bool(sc.get("scroll_x", False)))
            self._chk_scroll_y.setChecked(bool(sc.get("scroll_y", False)))
            self._chk_forced_scroll.setChecked(bool(sc.get("forced", False)))
            self._spin_speed_x.setValue(int(sc.get("speed_x", 0)))
            self._spin_speed_y.setValue(int(sc.get("speed_y", 0)))
            self._chk_loop_x.setChecked(bool(sc.get("loop_x", False)))
            self._chk_loop_y.setChecked(bool(sc.get("loop_y", False)))
            idx_mode = self._combo_cam_mode.findData(cam_mode)
            self._combo_cam_mode.setCurrentIndex(idx_mode if idx_mode >= 0 else 0)
            self._chk_cam_clamp.setChecked(clamp)
            self._chk_cam_bounds_auto.setChecked(bounds_auto)
            self._spin_cam_min_x.setValue(min_x)
            self._spin_cam_min_y.setValue(min_y)
            self._spin_cam_max_x.setValue(max_x)
            self._spin_cam_max_y.setValue(max_y)
            self._spin_cam_deadzone_x.setValue(int(self._layout_cfg.get("follow_deadzone_x", 16)))
            self._spin_cam_deadzone_y.setValue(int(self._layout_cfg.get("follow_deadzone_y", 12)))
            self._spin_cam_drop_margin_y.setValue(int(self._layout_cfg.get("follow_drop_margin_y", 20)))
            self._spin_cam_lag.setValue(int(self._layout_cfg.get("cam_lag", 0)))
            self._spin_scr1_par_x.setValue(int(self._layers_cfg.get("scr1_parallax_x", 100)))
            self._spin_scr1_par_y.setValue(int(self._layers_cfg.get("scr1_parallax_y", 100)))
            self._spin_scr2_par_x.setValue(int(self._layers_cfg.get("scr2_parallax_x", 100)))
            self._spin_scr2_par_y.setValue(int(self._layers_cfg.get("scr2_parallax_y", 100)))
            self._chk_rule_lock_y.setChecked(bool(self._level_rules.get("lock_y_en", False)))
            self._spin_rule_lock_y.setValue(int(self._level_rules.get("lock_y", 0)))
            self._chk_rule_ground_band.setChecked(bool(self._level_rules.get("ground_band_en", False)))
            self._spin_rule_ground_min.setValue(int(self._level_rules.get("ground_min_y", 0)))
            self._spin_rule_ground_max.setValue(int(self._level_rules.get("ground_max_y", max(0, gh - 1))))
            self._chk_rule_mirror.setChecked(bool(self._level_rules.get("mirror_en", False)))
            self._spin_rule_mirror_axis.setValue(int(self._level_rules.get("mirror_axis_x", max(0, (gw - 1)//2))))
            self._chk_rule_apply_waves.setChecked(bool(self._level_rules.get("apply_to_waves", True)))
            self._spin_rule_hazard_damage.setValue(int(self._level_rules.get("hazard_damage", 1)))
            self._spin_rule_fire_damage.setValue(int(self._level_rules.get("fire_damage", 1)))
            self._chk_rule_void_instant.setChecked(bool(self._level_rules.get("void_instant", True)))
            self._spin_rule_void_damage.setValue(int(self._level_rules.get("void_damage", 255)))
            self._spin_rule_hazard_invul.setValue(int(self._level_rules.get("hazard_invul", 30)))
            self._spin_rule_spring_force.setValue(int(self._level_rules.get("spring_force", 8)))
            idx_spring_dir = self._combo_rule_spring_dir.findData(str(self._level_rules.get("spring_dir", "up") or "up"))
            self._combo_rule_spring_dir.setCurrentIndex(idx_spring_dir if idx_spring_dir >= 0 else 0)
            self._spin_rule_conveyor_speed.setValue(int(self._level_rules.get("conveyor_speed", 2)))
            self._spin_rule_ice_friction.setValue(int(self._level_rules.get("ice_friction", 0)))
            self._spin_rule_water_drag.setValue(int(self._level_rules.get("water_drag", 2)))
            self._spin_rule_water_damage.setValue(int(self._level_rules.get("water_damage", 0)))
            self._spin_rule_zone_force.setValue(int(self._level_rules.get("zone_force", 2)))
            self._chk_rule_ladder_top_solid.setChecked(bool(self._level_rules.get("ladder_top_solid", False)))
            self._chk_rule_ladder_top_exit.setChecked(bool(self._level_rules.get("ladder_top_exit", True)))
            self._chk_rule_ladder_side_move.setChecked(bool(self._level_rules.get("ladder_side_move", False)))
            hud_en = bool(self._level_rules.get("hud_enabled", False))
            self._chk_rule_hud_enabled.setChecked(hud_en)
            self._on_hud_enabled_toggled(hud_en)
            self._chk_rule_hud_hp.setChecked(bool(self._level_rules.get("hud_show_hp", False)))
            self._chk_rule_hud_score.setChecked(bool(self._level_rules.get("hud_show_score", False)))
            self._chk_rule_hud_collect.setChecked(bool(self._level_rules.get("hud_show_collect", True)))
            self._chk_rule_hud_timer.setChecked(bool(self._level_rules.get("hud_show_timer", False)))
            self._chk_rule_hud_lives.setChecked(bool(self._level_rules.get("hud_show_lives", False)))
            idx_hud_pos = self._combo_rule_hud_pos.findData(str(self._level_rules.get("hud_pos", "top")))
            self._combo_rule_hud_pos.setCurrentIndex(idx_hud_pos if idx_hud_pos >= 0 else 0)
            idx_hud_font = self._combo_rule_hud_font.findData(str(self._level_rules.get("hud_font_mode", "system")))
            self._combo_rule_hud_font.setCurrentIndex(idx_hud_font if idx_hud_font >= 0 else 0)
            idx_hud_fixed = self._combo_rule_hud_fixed_plane.findData(str(self._level_rules.get("hud_fixed_plane", "none")))
            self._combo_rule_hud_fixed_plane.setCurrentIndex(idx_hud_fixed if idx_hud_fixed >= 0 else 0)
            idx_hud_text_color = self._combo_rule_hud_text_color.findData(str(self._level_rules.get("hud_text_color", "white")))
            self._combo_rule_hud_text_color.setCurrentIndex(idx_hud_text_color if idx_hud_text_color >= 0 else 0)
            idx_hud_style = self._combo_rule_hud_style.findData(str(self._level_rules.get("hud_style", "text")))
            self._combo_rule_hud_style.setCurrentIndex(idx_hud_style if idx_hud_style >= 0 else 0)
            idx_hud_band_color = self._combo_rule_hud_band_color.findData(str(self._level_rules.get("hud_band_color", "blue")))
            self._combo_rule_hud_band_color.setCurrentIndex(idx_hud_band_color if idx_hud_band_color >= 0 else 0)
            self._spin_rule_hud_band_rows.setValue(int(self._level_rules.get("hud_band_rows", 2)))
            self._spin_rule_hud_digits_hp.setValue(int(self._level_rules.get("hud_digits_hp", 2)))
            self._spin_rule_hud_digits_score.setValue(int(self._level_rules.get("hud_digits_score", 5)))
            self._spin_rule_hud_digits_collect.setValue(int(self._level_rules.get("hud_digits_collect", 3)))
            self._spin_rule_hud_digits_timer.setValue(int(self._level_rules.get("hud_digits_timer", 3)))
            self._spin_rule_hud_digits_lives.setValue(int(self._level_rules.get("hud_digits_lives", 2)))
            self._spin_rule_hud_digits_continues.setValue(int(self._level_rules.get("hud_digits_continues", 2)))
            self._spin_rule_goal_collectibles.setValue(int(self._level_rules.get("goal_collectibles", 0)))
            self._spin_rule_time_limit.setValue(int(self._level_rules.get("time_limit_sec", 0)))
            self._spin_rule_start_lives.setValue(int(self._level_rules.get("start_lives", 0)))
            self._spin_rule_start_continues.setValue(int(self._level_rules.get("start_continues", 0)))
            self._spin_rule_continue_restore_lives.setValue(int(self._level_rules.get("continue_restore_lives", 3)))
            self._hud_widget_selected = -1
            self._refresh_hud_widget_type_combo("")
            self._refresh_hud_font_digit_combos()
            self._refresh_hud_custom_ui()
        finally:
            self._spin_cam_x.blockSignals(False)
            self._spin_cam_y.blockSignals(False)
            self._combo_cam_mode.blockSignals(False)
            self._chk_cam_clamp.blockSignals(False)
            self._chk_cam_bounds_auto.blockSignals(False)
            self._spin_cam_min_x.blockSignals(False)
            self._spin_cam_min_y.blockSignals(False)
            self._spin_cam_max_x.blockSignals(False)
            self._spin_cam_max_y.blockSignals(False)
            self._spin_cam_deadzone_x.blockSignals(False)
            self._spin_cam_deadzone_y.blockSignals(False)
            self._spin_cam_drop_margin_y.blockSignals(False)
            self._spin_cam_lag.blockSignals(False)
            self._chk_scroll_x.blockSignals(False)
            self._chk_scroll_y.blockSignals(False)
            self._chk_forced_scroll.blockSignals(False)
            self._spin_speed_x.blockSignals(False)
            self._spin_speed_y.blockSignals(False)
            self._chk_loop_x.blockSignals(False)
            self._chk_loop_y.blockSignals(False)
            self._spin_scr1_par_x.blockSignals(False)
            self._spin_scr1_par_y.blockSignals(False)
            self._spin_scr2_par_x.blockSignals(False)
            self._spin_scr2_par_y.blockSignals(False)
            self._chk_rule_lock_y.blockSignals(False)
            self._spin_rule_lock_y.blockSignals(False)
            self._chk_rule_ground_band.blockSignals(False)
            self._spin_rule_ground_min.blockSignals(False)
            self._spin_rule_ground_max.blockSignals(False)
            self._chk_rule_mirror.blockSignals(False)
            self._spin_rule_mirror_axis.blockSignals(False)
            self._chk_rule_apply_waves.blockSignals(False)
            self._spin_rule_hazard_damage.blockSignals(False)
            self._spin_rule_fire_damage.blockSignals(False)
            self._chk_rule_void_instant.blockSignals(False)
            self._spin_rule_void_damage.blockSignals(False)
            self._spin_rule_hazard_invul.blockSignals(False)
            self._spin_rule_spring_force.blockSignals(False)
            self._combo_rule_spring_dir.blockSignals(False)
            self._spin_rule_conveyor_speed.blockSignals(False)
            self._spin_rule_zone_force.blockSignals(False)
            self._chk_rule_ladder_top_solid.blockSignals(False)
            self._chk_rule_ladder_top_exit.blockSignals(False)
            self._chk_rule_ladder_side_move.blockSignals(False)
            self._chk_rule_hud_hp.blockSignals(False)
            self._chk_rule_hud_score.blockSignals(False)
            self._chk_rule_hud_collect.blockSignals(False)
            self._chk_rule_hud_timer.blockSignals(False)
            self._chk_rule_hud_lives.blockSignals(False)
            self._combo_rule_hud_pos.blockSignals(False)
            self._combo_rule_hud_font.blockSignals(False)
            self._combo_rule_hud_fixed_plane.blockSignals(False)
            self._combo_rule_hud_text_color.blockSignals(False)
            self._combo_rule_hud_style.blockSignals(False)
            self._combo_rule_hud_band_color.blockSignals(False)
            self._spin_rule_hud_band_rows.blockSignals(False)
            self._spin_rule_hud_digits_hp.blockSignals(False)
            self._spin_rule_hud_digits_score.blockSignals(False)
            self._spin_rule_hud_digits_collect.blockSignals(False)
            self._spin_rule_hud_digits_timer.blockSignals(False)
            self._spin_rule_hud_digits_lives.blockSignals(False)
            self._spin_rule_hud_digits_continues.blockSignals(False)
            self._spin_rule_goal_collectibles.blockSignals(False)
            self._spin_rule_time_limit.blockSignals(False)
            self._spin_rule_start_lives.blockSignals(False)
            self._spin_rule_start_continues.blockSignals(False)
            self._spin_rule_continue_restore_lives.blockSignals(False)

        self._on_layout_changed()
        self._on_layers_changed()
        self._on_rules_changed()

        # Load neighbours (Track B)
        _nb_raw = scene.get("neighbors") or {} if scene else {}
        _nb_raw = _nb_raw if isinstance(_nb_raw, dict) else {}
        self._refresh_neighbor_combos(current_values=_nb_raw)

        # Load chunk map (Track A)
        _chunk_raw = scene.get("bg_chunk_map") or {} if scene else {}
        self._load_chunk_map_ui(_chunk_raw if isinstance(_chunk_raw, dict) else {})

        # Reset undo
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._update_undo_buttons()

        self._refresh_wave_list()
        self._refresh_region_list()
        self._refresh_region_props()
        self._refresh_text_labels_ui()
        self._refresh_trigger_list()
        self._refresh_trigger_props()
        self._refresh_path_list()
        self._refresh_path_props()

        n = len(self._entities)
        self._lbl_status.setText(tr("level.status", n=n))
        self._canvas.updateGeometry()
        self._canvas.resize(self._canvas.sizeHint())
        self._canvas.update()
        self._update_budget()

    # ------------------------------------------------------------------
    # Entity type / role
    # ------------------------------------------------------------------

    def _current_type(self) -> Optional[str]:
        # QListWidget.selectedItems() can lag behind currentItem() during signal
        # cascades (notably from currentItemChanged before selectionChanged has
        # propagated). Prefer currentItem(), fall back to selectedItems()[0].
        # Without this, _on_type_selection_changed / _on_role_changed intermittently
        # see None and silently abort, producing the "role combo stuck" symptom.
        cur = self._type_list.currentItem()
        if cur is not None:
            return cur.data(Qt.ItemDataRole.UserRole) or cur.text() or None
        items = self._type_list.selectedItems()
        if items:
            return items[0].data(Qt.ItemDataRole.UserRole) or items[0].text() or None
        return None

    def _type_tile_span(self, type_name: str) -> tuple[int, int]:
        w_px, h_px = self._type_sizes.get(str(type_name or ""), (_TILE_PX, _TILE_PX))
        return (
            max(1, (int(w_px) + _TILE_PX - 1) // _TILE_PX),
            max(1, (int(h_px) + _TILE_PX - 1) // _TILE_PX),
        )

    def _selected_type_starter(self) -> str:
        combo = getattr(self, "_combo_type_starter", None)
        if combo is None or combo.currentIndex() < 0:
            return ""
        return str(combo.currentData() or "")

    def _refresh_type_starter_ui(self) -> None:
        combo = getattr(self, "_combo_type_starter", None)
        hint = getattr(self, "_lbl_type_starter_hint", None)
        btn = getattr(self, "_btn_place_starter", None)
        if combo is None or hint is None or btn is None:
            return
        type_name = str(self._current_type() or "").strip()
        role = self._entity_role_for_type(type_name) if type_name else "prop"
        starter_items = _ENTITY_STARTER_PRESETS.get(role, ())
        cur = str(combo.currentData() or "")
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(tr("level.starter_none"), "")
        for starter_id, label_key in starter_items:
            combo.addItem(tr(label_key), starter_id)
        idx = combo.findData(cur)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)
        has_type = bool(type_name)
        has_starters = bool(starter_items)
        combo.setEnabled(has_type and has_starters)
        btn.setEnabled(has_type)
        if not has_type:
            hint.setText(tr("level.starter_hint_no_type"))
        elif not has_starters:
            hint.setText(tr("level.starter_hint_no_role", role=role))
        else:
            hint.setText(tr("level.starter_hint_role", role=role))

    def _visible_center_tile(self) -> tuple[int, int]:
        viewport = self._scroll.viewport() if hasattr(self, "_scroll") else None
        if viewport is None:
            return self._clamp_tile_xy(int(self._grid_w) // 2, int(self._grid_h) // 2)
        tp = max(1, _TILE_PX * int(getattr(self, "_zoom", _DEFAULT_ZOOM)))
        vx = int(self._scroll.horizontalScrollBar().value()) + max(0, viewport.width() // 2)
        vy = int(self._scroll.verticalScrollBar().value()) + max(0, viewport.height() // 2)
        return self._clamp_tile_xy(vx // tp, vy // tp)

    def _snap_entity_to_ground(self, type_name: str, x: int, y: int) -> tuple[int, int]:
        w_tiles, h_tiles = self._type_tile_span(type_name)
        probe_x = max(0, min(int(self._grid_w) - 1, int(x) + max(0, w_tiles // 2)))
        start_y = max(0, int(y) + h_tiles)
        support_tiles = {_TCOL_SOLID, _TCOL_ONE_WAY, _TCOL_STAIR_E, _TCOL_STAIR_W, _TCOL_WALL_N, _TCOL_SPRING}
        for foot_y in range(start_y, int(self._grid_h)):
            if int(self._collision_value_at(probe_x, foot_y) or _TCOL_PASS) in support_tiles:
                return self._clamp_tile_xy(x, foot_y - h_tiles)
        return self._clamp_tile_xy(x, y)

    def _ensure_simple_path_for_entity(self, ent: dict) -> None:
        path_id = str(ent.get("path_id", "") or "")
        if path_id:
            return
        # Always create a new dedicated path — never reuse an existing one,
        # so each moving platform gets its own independent path.
        x = int(ent.get("x", 0) or 0)
        y = int(ent.get("y", 0) or 0)
        px = x * _TILE_PX
        py = y * _TILE_PX
        max_px = max(0, int(self._grid_w * _TILE_PX) - 1)
        path = {
            "id": _new_id(),
            "name": self._next_path_name(),
            "loop": True,
            "speed": 1,
            "points": [
                _path_point_make(px, py),
                _path_point_make(min(max_px, px + (4 * _TILE_PX)), py),
            ],
        }
        self._paths.append(path)
        ent["path_id"] = str(path["id"])
        self._refresh_path_list()
        self._refresh_path_props()

    def _apply_type_starter(self, ent: dict, starter_id: str) -> dict:
        starter = str(starter_id or "").strip().lower()
        if not starter:
            return ent
        role = self._entity_role_for_type(str(ent.get("type", "")))
        if role == "player":
            if starter == "player:spawn_ground":
                ent["x"], ent["y"] = self._snap_entity_to_ground(str(ent.get("type", "")), int(ent.get("x", 0)), int(ent.get("y", 0)))
        elif role == "enemy":
            if starter == "enemy:patrol_left":
                ent["behavior"] = 0
                ent["direction"] = 1
            elif starter == "enemy:patrol_right":
                ent["behavior"] = 0
                ent["direction"] = 0
            elif starter == "enemy:guard":
                ent["behavior"] = 2
                ent["direction"] = 0
            elif starter == "enemy:chase":
                ent["behavior"] = 1
                ent["direction"] = 0
        elif role == "item":
            if starter == "item:collect_1":
                ent["data"] = 0
            elif starter == "item:collect_5":
                ent["data"] = 5
            elif starter == "item:collect_10":
                ent["data"] = 10
        elif role == "block":
            if starter == "block:bump":
                ent["data"] = 0
            elif starter == "block:breakable":
                ent["data"] = 1
            elif starter == "block:item_once":
                ent["data"] = 2
        elif role == "platform":
            if starter == "platform:static":
                ent.pop("path_id", None)
            elif starter == "platform:moving":
                self._ensure_simple_path_for_entity(ent)
        return ent

    def _make_entity_with_type_starter(self, type_name: str, x: int, y: int) -> dict:
        ent = self._make_entity(type_name, x, y)
        return self._apply_type_starter(ent, self._selected_type_starter())

    def _place_selected_type_starter(self) -> None:
        type_name = str(self._current_type() or "").strip()
        if not type_name:
            return
        tx, ty = self._visible_center_tile()
        tx, ty = self._canvas._apply_rules_xy(tx, ty, type_name=type_name, in_wave=False)
        tx, ty = self._canvas._clamp_entity_origin(tx, ty, type_name=type_name)
        self._push_undo()
        self._entities.append(self._make_entity_with_type_starter(type_name, tx, ty))
        self._selected = len(self._entities) - 1
        self._canvas.entity_selected.emit(self._selected)
        self._canvas.entity_placed.emit()
        self._canvas.update()

    def _on_type_selection_changed(self, curr, _prev) -> None:
        # Read the new type name directly from the signal's `curr` argument —
        # it's guaranteed fresh, unlike _current_type() which can briefly see
        # a stale selection during Qt's cascaded currentItemChanged →
        # selectionChanged notifications.
        name: Optional[str] = None
        if curr is not None:
            name = curr.data(Qt.ItemDataRole.UserRole) or curr.text() or None
        if not name:
            name = self._current_type()
        # Always refresh the role combo on type switches, even when we fail to
        # resolve a name (reset to "prop" so it doesn't linger on the previous
        # type's role).
        self._combo_role.blockSignals(True)
        if name:
            role = self._entity_roles.get(name, "prop")
            idx  = list(_ROLES).index(role) if role in _ROLES else len(_ROLES) - 1
            self._combo_role.setCurrentIndex(idx)
        else:
            prop_idx = list(_ROLES).index("prop") if "prop" in _ROLES else 0
            self._combo_role.setCurrentIndex(prop_idx)
        self._combo_role.blockSignals(False)
        self._refresh_type_starter_ui()

    def _on_role_changed(self, idx: int) -> None:
        name = self._current_type()
        if name is None:
            return
        role = self._combo_role.itemData(idx)
        self._entity_roles[name] = set_scene_sprite_role(self._scene, name, role)
        items = self._type_list.selectedItems()
        if items:
            items[0].setToolTip(f"Rôle : {self._entity_roles[name]}")
            self._update_type_item_label(items[0], name, self._entity_roles[name])
        if self._scene is not None:
            self._on_save()
        self._refresh_hud_widget_type_combo()
        self._refresh_hud_font_digit_combos()
        self._refresh_dgen_pool_combos()
        self._refresh_type_starter_ui()
        self._canvas.update()

    def _update_type_item_label(self, item: QListWidgetItem, name: str, role: str | None = None) -> None:
        if role is None:
            role = self._entity_roles.get(name, "prop")
        short = _ROLE_SHORT.get(role, "??")
        size = self._type_sizes.get(name)

        # Compute role-specific index badge.
        # Use scene sprite order from self._scene directly — reliable even when
        # _type_names is being built incrementally during the load loop.
        idx_badge = ""
        tooltip_extra = ""
        try:
            scene_sprites = [
                Path(s.get("file", "")).stem
                for s in (self._scene.get("sprites") or [])
                if s.get("file")
            ]
            if name in scene_sprites:
                sprite_pos = scene_sprites.index(name)
                if role == "player":
                    form_idx = sum(
                        1 for n in scene_sprites[:sprite_pos]
                        if str(self._entity_roles.get(n, "prop")) == "player"
                    )
                    idx_badge = f" [form {form_idx}]"
                    tooltip_extra = f"\nForme index {form_idx} — utiliser dans set_player_form / cycle_player_form"
                elif role in ("npc", "prop", "item", "trigger"):
                    # Use the real runtime src_idx (entity placement index), not sprite list index
                    real_src_idx = self._prop_src_idx_for_sprite_name(name)
                    if real_src_idx is not None:
                        idx_badge = f" [id {real_src_idx}]"
                        tooltip_extra = f"\nsrc_idx {real_src_idx} — utiliser dans npc_talked_to / entity_contact"
        except (ValueError, AttributeError, TypeError):
            pass

        if size:
            w, h = size
            label = f"[{short}] {name}  ({w}×{h}){idx_badge}"
        else:
            label = f"[{short}] {name}{idx_badge}"
        item.setText(label)
        item.setToolTip(f"Rôle : {role}{tooltip_extra}")

    # ------------------------------------------------------------------
    # Background
    # ------------------------------------------------------------------

    def _load_bg_at(self, idx: int, plane: str) -> Optional[QPixmap]:
        if idx <= 0 or idx >= len(self._bg_paths):
            return None
        p = self._bg_paths[idx]
        if not p:
            return None
        return _load_bg_pixmap(_resolve_bg_plane_variant(p, plane))

    @staticmethod
    def _pixmap_is_large_map(pm: Optional["QPixmap"]) -> bool:
        """Return True if the pixmap dimensions exceed the 32×32 tile hardware window."""
        if pm is None or pm.isNull():
            return False
        return (pm.width() > 32 * _TILE_PX) or (pm.height() > 32 * _TILE_PX)

    def _check_dual_stream(self, new_pm: Optional["QPixmap"], new_plane: str,
                           other_pm: Optional["QPixmap"], other_plane: str) -> bool:
        """Return True (and show error) if loading new_pm on new_plane would create a
        dual-stream conflict (both planes > 32×32 tiles simultaneously)."""
        if not self._pixmap_is_large_map(new_pm):
            return False
        if not self._pixmap_is_large_map(other_pm):
            return False
        # Both are large — conflict
        from PyQt6.QtWidgets import QMessageBox
        nw = new_pm.width() // _TILE_PX if new_pm else 0
        nh = new_pm.height() // _TILE_PX if new_pm else 0
        ow = other_pm.width() // _TILE_PX if other_pm else 0
        oh = other_pm.height() // _TILE_PX if other_pm else 0
        body = tr("level.dual_stream_body").format(
            w=32, h=32,
            plane=new_plane.upper(), other_plane=other_plane.upper(),
            ow=ow, oh=oh,
        )
        QMessageBox.warning(self, tr("level.dual_stream_title"), body)
        return True

    def _refresh_bg_fit_btn(self) -> None:
        has = (self._bg_pixmap_scr1 is not None) or (self._bg_pixmap_scr2 is not None)
        self._btn_fit_bg.setEnabled(bool(has))

    def _rebuild_tilemap_collision_cache(self) -> None:
        """Recompute the tilemap-derived collision grid used as a ghost overlay.

        Called every time the active BG tilemap changes so the level tab always
        reflects the current tilemap collision without requiring a manual import.
        The result is stored in _col_map_tilemap_cache and rendered at reduced
        opacity behind _col_map in the canvas.
        """
        try:
            rel, path, _label = self._resolve_collision_import_bg()
            if not rel or path is None:
                self._col_map_tilemap_cache = None
                return
            tm = self._scene_tilemap_entry_for_rel(rel)
            if tm is None:
                self._col_map_tilemap_cache = None
                return
            from core.scene_collision import _tilemap_has_collision
            if not _tilemap_has_collision(tm):
                self._col_map_tilemap_cache = None
                return
            grid = self._tilemap_collision_grid(tm, path)
            gw = int(getattr(self, "_grid_w", len(grid[0]) if grid else 20))
            gh = int(getattr(self, "_grid_h", len(grid) if grid else 19))
            self._col_map_tilemap_cache = fit_collision_grid(grid, gw, gh)
        except Exception:
            self._col_map_tilemap_cache = None

    def _on_bg_scr1_changed(self, idx: int) -> None:
        candidate = self._load_bg_at(idx, "scr1")
        if self._check_dual_stream(candidate, "SCR1", self._bg_pixmap_scr2, "SCR2"):
            # Revert combo to "none" without re-triggering this handler
            self._combo_bg_scr1.blockSignals(True)
            self._combo_bg_scr1.setCurrentIndex(0)
            self._combo_bg_scr1.blockSignals(False)
            return
        self._bg_pixmap_scr1 = candidate
        self._refresh_bg_fit_btn()
        self._rebuild_tilemap_collision_cache()
        self._canvas.update()
        if self._map_mode in _MAP_MODE_ROLES:
            self._rebuild_tile_role_ui(self._map_mode)
        self._update_size_limits_ui()
        self._refresh_bg_cards()

    def _on_bg_scr2_changed(self, idx: int) -> None:
        candidate = self._load_bg_at(idx, "scr2")
        if self._check_dual_stream(candidate, "SCR2", self._bg_pixmap_scr1, "SCR1"):
            # Revert combo to "none" without re-triggering this handler
            self._combo_bg_scr2.blockSignals(True)
            self._combo_bg_scr2.setCurrentIndex(0)
            self._combo_bg_scr2.blockSignals(False)
            return
        self._bg_pixmap_scr2 = candidate
        self._refresh_bg_fit_btn()
        self._rebuild_tilemap_collision_cache()
        self._canvas.update()
        if self._map_mode in _MAP_MODE_ROLES:
            self._rebuild_tile_role_ui(self._map_mode)
        self._update_size_limits_ui()
        self._refresh_bg_cards()

    def _on_bg_front_changed(self, _idx: int) -> None:
        v = self._combo_bg_front.currentData()
        front = str(v) if isinstance(v, str) else "scr1"
        if front not in ("scr1", "scr2"):
            front = "scr1"
        self._bg_front = front
        self._on_layers_changed()
        self._canvas.update()
        self._refresh_bg_cards()

    def _open_bg_picker(self, plane: str) -> None:
        """Open the tilemap picker dialog for the given plane."""
        paths_without_sentinel = [p for p in self._bg_paths[1:] if p is not None]
        rels_without_sentinel  = [r for r in self._bg_rels[1:]  if r is not None]
        combo = self._combo_bg_scr1 if plane == "scr1" else self._combo_bg_scr2
        current_idx = int(combo.currentIndex())
        dlg = _BgPickerDialog(
            plane=plane,
            bg_paths=paths_without_sentinel,
            bg_rels=rels_without_sentinel,
            current_idx=current_idx,
            parent=self,
        )
        if dlg.exec() == _BgPickerDialog.DialogCode.Accepted:
            combo.setCurrentIndex(dlg.chosen_index())

    def _add_bg_png(self, plane: str) -> None:
        """Browse for a PNG, add it to the scene tilemaps, assign to plane."""
        base = None
        try:
            proj = getattr(self, "_project_path", None) or getattr(self, "_base_dir", None)
            if proj:
                base = str(Path(proj).parent) if Path(proj).is_file() else str(proj)
        except Exception:
            pass
        path, _ = QFileDialog.getOpenFileName(
            self, f"Ajouter tilemap PNG pour {plane.upper()}", base or "", "PNG (*.png)"
        )
        if not path:
            return
        try:
            abs_p = Path(path).resolve()
            try:
                proj_dir = Path(getattr(self, "_base_dir", None) or abs_p.parent)
                rel = str(abs_p.relative_to(proj_dir))
            except Exception:
                rel = str(abs_p)
            idx = self._ensure_bg_item(rel, abs_p)
            if hasattr(self, "_scene") and isinstance(self._scene, dict):
                tilemaps = self._scene.setdefault("tilemaps", [])
                rel_norm = str(rel).replace("\\", "/")
                already = any(
                    str(tm.get("file", "")).replace("\\", "/") == rel_norm
                    for tm in tilemaps if isinstance(tm, dict)
                )
                if not already:
                    tilemaps.append({"name": abs_p.stem, "file": rel, "export": True})
            combo = self._combo_bg_scr1 if plane == "scr1" else self._combo_bg_scr2
            combo.setCurrentIndex(idx)
        except Exception as e:
            QMessageBox.warning(self, "Erreur", f"Impossible d'ajouter la tilemap :\n{e}")

    def _remove_bg_plane(self, plane: str) -> None:
        combo = self._combo_bg_scr1 if plane == "scr1" else self._combo_bg_scr2
        combo.setCurrentIndex(0)

    def _refresh_bg_cards(self) -> None:
        """Sync the visual layer cards with current BG state."""
        if not hasattr(self, "_card_scr1"):
            return
        hints = getattr(self, "_bg_plane_hints", {})
        rels = getattr(self, "_bg_rels", [None])

        idx1 = int(self._combo_bg_scr1.currentIndex()) if hasattr(self, "_combo_bg_scr1") else 0
        name1 = self._combo_bg_scr1.currentText() if idx1 > 0 else ""
        self._card_scr1.set_info(self._bg_pixmap_scr1 if idx1 > 0 else None, name1)
        rel1 = rels[idx1] if 0 < idx1 < len(rels) else None
        hint1 = hints.get(rel1, "auto") if rel1 else "auto"
        warn1 = bool(name1) and hint1 == "scr2"
        self._card_scr1.set_warn(warn1, f"Cette tilemap a plane=scr2 dans l'onglet Tilemap mais est assignée à SCR1 ici (la scène prend le dessus)." if warn1 else "")

        idx2 = int(self._combo_bg_scr2.currentIndex()) if hasattr(self, "_combo_bg_scr2") else 0
        name2 = self._combo_bg_scr2.currentText() if idx2 > 0 else ""
        self._card_scr2.set_info(self._bg_pixmap_scr2 if idx2 > 0 else None, name2)
        rel2 = rels[idx2] if 0 < idx2 < len(rels) else None
        hint2 = hints.get(rel2, "auto") if rel2 else "auto"
        warn2 = bool(name2) and hint2 == "scr1"
        self._card_scr2.set_warn(warn2, f"Cette tilemap a plane=scr1 dans l'onglet Tilemap mais est assignée à SCR2 ici (la scène prend le dessus)." if warn2 else "")

    def _fit_to_bg(self) -> None:
        pm1 = self._bg_pixmap_scr1
        pm2 = self._bg_pixmap_scr2
        if pm1 is None and pm2 is None:
            return
        w = max((pm1.width()  if pm1 else 0), (pm2.width()  if pm2 else 0))
        h = max((pm1.height() if pm1 else 0), (pm2.height() if pm2 else 0))
        self._spin_gw.setValue(max(1, w // _TILE_PX))
        self._spin_gh.setValue(max(1, h // _TILE_PX))
        self._update_size_limits_ui()

    def _on_bezel_toggled(self, checked: bool) -> None:
        self._show_bezel = checked
        for attr in ("_chk_bezel", "_chk_overlay_bezel"):
            w = getattr(self, attr, None)
            if w is not None and bool(w.isChecked()) != bool(checked):
                w.blockSignals(True)
                w.setChecked(bool(checked))
                w.blockSignals(False)
        self._canvas.update()

    def _on_cam_toggled(self, checked: bool) -> None:
        self._show_cam = checked
        for attr in ("_chk_cam", "_chk_overlay_cam"):
            w = getattr(self, attr, None)
            if w is not None and bool(w.isChecked()) != bool(checked):
                w.blockSignals(True)
                w.setChecked(bool(checked))
                w.blockSignals(False)
        self._canvas.update()

    def _on_col_map_toggled(self, checked: bool) -> None:
        self._show_col_map = checked
        for attr in ("_chk_col_map", "_chk_overlay_col"):
            w = getattr(self, attr, None)
            if w is not None and bool(w.isChecked()) != bool(checked):
                w.blockSignals(True)
                w.setChecked(bool(checked))
                w.blockSignals(False)
        self._canvas.update()
        self._refresh_collision_source_ui()

    def _collision_brush_choices(self) -> list[int]:
        vals: list[int] = []
        mode = str(self._map_mode or "none").strip().lower()
        for _role_key, tcol, _label_key in _MAP_MODE_ROLES.get(mode, []):
            if int(tcol) not in vals:
                vals.append(int(tcol))
        if not vals:
            vals = sorted(int(v) for v in _TCOL_NAMES)
        if _TCOL_PASS in vals:
            vals = [_TCOL_PASS] + [v for v in vals if v != _TCOL_PASS]
        return vals

    def _collision_brush_label(self, tcol: int) -> str:
        mode = str(self._map_mode or "none").strip().lower()
        for _role_key, role_tcol, label_key in _MAP_MODE_ROLES.get(mode, []):
            if int(role_tcol) == int(tcol):
                return tr(label_key)
        return _TCOL_NAMES.get(int(tcol), str(int(tcol)))

    def _refresh_collision_brush_ui(self) -> None:
        combo = getattr(self, "_combo_collision_brush", None)
        mode_combo = getattr(self, "_combo_collision_mode", None)
        hint = getattr(self, "_lbl_collision_brush_hint", None)
        if combo is None:
            return
        current = int(combo.currentData() if combo.currentIndex() >= 0 else self._collision_brush)
        choices = self._collision_brush_choices()
        if current not in choices:
            current = choices[1] if len(choices) > 1 else choices[0]
        combo.blockSignals(True)
        combo.clear()
        for tcol in choices:
            combo.addItem(f"{self._collision_brush_label(tcol)} ({_TCOL_NAMES.get(int(tcol), int(tcol))})", int(tcol))
        idx = combo.findData(int(current))
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)
        self._collision_brush = int(combo.currentData() or current or _TCOL_PASS)
        enabled = str(getattr(self, "_scene_tool", "entity") or "entity") == "collision"
        if mode_combo is not None:
            current_mode = str(mode_combo.currentData() or self._collision_edit_mode or "brush")
            if current_mode not in {m for m, _ in _COLLISION_EDIT_MODES}:
                current_mode = "brush"
            mode_combo.blockSignals(True)
            idx = mode_combo.findData(current_mode)
            mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
            mode_combo.blockSignals(False)
            self._collision_edit_mode = str(mode_combo.currentData() or current_mode)
        if hint is not None:
            hint.setText(tr({
                "brush": "level.collision_mode_hint_brush",
                "rect": "level.collision_mode_hint_rect",
                "fill": "level.collision_mode_hint_fill",
            }.get(str(self._collision_edit_mode or "brush"), "level.collision_mode_hint_brush")))
        has_bg_source = (getattr(self, "_combo_bg_scr1", None) is not None and self._combo_bg_scr1.count() > 1) or (
            getattr(self, "_combo_bg_scr2", None) is not None and self._combo_bg_scr2.count() > 1
        )
        import_combo = getattr(self, "_combo_collision_import_bg", None)
        import_btn = getattr(self, "_btn_collision_import_bg", None)
        if import_combo is not None:
            import_combo.setEnabled(enabled and has_bg_source)
        if import_btn is not None:
            import_btn.setEnabled(enabled and has_bg_source)
        for attr in ("_combo_collision_brush", "_combo_collision_mode", "_lbl_collision_brush", "_lbl_collision_brush_hint"):
            w = getattr(self, attr, None)
            if w is not None:
                w.setEnabled(enabled)

    def _on_collision_brush_changed(self, _idx: int) -> None:
        combo = getattr(self, "_combo_collision_brush", None)
        if combo is None:
            return
        self._collision_brush = int(combo.currentData() or _TCOL_PASS)

    def _current_collision_brush(self) -> int:
        combo = getattr(self, "_combo_collision_brush", None)
        if combo is not None and combo.currentIndex() >= 0:
            return int(combo.currentData() or self._collision_brush)
        return int(self._collision_brush)

    def _on_collision_edit_mode_changed(self, _idx: int) -> None:
        combo = getattr(self, "_combo_collision_mode", None)
        if combo is None:
            return
        self._collision_edit_mode = str(combo.currentData() or "brush")
        self._refresh_collision_brush_ui()

    def _current_collision_edit_mode(self) -> str:
        combo = getattr(self, "_combo_collision_mode", None)
        if combo is not None and combo.currentIndex() >= 0:
            return str(combo.currentData() or self._collision_edit_mode or "brush")
        return str(self._collision_edit_mode or "brush")

    def _set_collision_brush(self, tcol: int) -> None:
        self._collision_brush = int(tcol)
        combo = getattr(self, "_combo_collision_brush", None)
        if combo is not None:
            idx = combo.findData(int(tcol))
            if idx >= 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(idx)
                combo.blockSignals(False)
        self._refresh_collision_brush_ui()

    def _collision_value_at(self, tx: int, ty: int) -> int | None:
        if not (0 <= int(tx) < int(self._grid_w) and 0 <= int(ty) < int(self._grid_h)):
            return None
        if (
            isinstance(self._col_map, list)
            and len(self._col_map) == int(self._grid_h)
            and all(isinstance(r, list) and len(r) == int(self._grid_w) for r in self._col_map)
        ):
            return int(self._col_map[ty][tx])
        return _TCOL_PASS

    def _ensure_col_map_size(self) -> bool:
        gw = max(1, int(self._grid_w))
        gh = max(1, int(self._grid_h))
        old = self._col_map if isinstance(self._col_map, list) else None
        valid = (
            isinstance(old, list)
            and len(old) == gh
            and all(isinstance(r, list) and len(r) == gw for r in old)
        )
        if valid:
            return True
        new_map = [[_TCOL_PASS for _x in range(gw)] for _y in range(gh)]
        if isinstance(old, list):
            copy_h = min(gh, len(old))
            copy_w = min(gw, min((len(r) for r in old if isinstance(r, list)), default=0))
            for y in range(copy_h):
                row = old[y]
                if not isinstance(row, list):
                    continue
                for x in range(copy_w):
                    try:
                        new_map[y][x] = int(row[x])
                    except Exception:
                        new_map[y][x] = _TCOL_PASS
        self._col_map = new_map
        return True

    def _paint_collision_tile(self, tx: int, ty: int, tcol: int, *, push_undo: bool = True) -> bool:
        if not self._ensure_col_map_size():
            return False
        if not (0 <= int(tx) < int(self._grid_w) and 0 <= int(ty) < int(self._grid_h)):
            return False
        cur = int(self._col_map[ty][tx])
        tcol = int(tcol)
        if cur == tcol:
            return False
        if push_undo:
            self._push_undo()
        self._col_map[ty][tx] = tcol
        if not self._show_col_map:
            self._on_col_map_toggled(True)
        self._canvas.update()
        self._update_diagnostics()
        return True

    def _paint_collision_rect(self, tx: int, ty: int, w: int, h: int, tcol: int, *, push_undo: bool = True) -> bool:
        if not self._ensure_col_map_size():
            return False
        x0 = max(0, min(int(self._grid_w) - 1, int(tx)))
        y0 = max(0, min(int(self._grid_h) - 1, int(ty)))
        x1 = max(x0, min(int(self._grid_w), x0 + max(1, int(w))))
        y1 = max(y0, min(int(self._grid_h), y0 + max(1, int(h))))
        tcol = int(tcol)
        changed = False
        for cy in range(y0, y1):
            for cx in range(x0, x1):
                if int(self._col_map[cy][cx]) != tcol:
                    changed = True
                    break
            if changed:
                break
        if not changed:
            return False
        if push_undo:
            self._push_undo()
        for cy in range(y0, y1):
            for cx in range(x0, x1):
                self._col_map[cy][cx] = tcol
        if not self._show_col_map:
            self._on_col_map_toggled(True)
        self._canvas.update()
        self._update_diagnostics()
        return True

    def _fill_collision_region(self, tx: int, ty: int, tcol: int, *, push_undo: bool = True) -> bool:
        if not self._ensure_col_map_size():
            return False
        if not (0 <= int(tx) < int(self._grid_w) and 0 <= int(ty) < int(self._grid_h)):
            return False
        target = int(self._col_map[int(ty)][int(tx)])
        tcol = int(tcol)
        if target == tcol:
            return False
        stack = [(int(tx), int(ty))]
        changed_cells: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        while stack:
            cx, cy = stack.pop()
            if (cx, cy) in seen:
                continue
            seen.add((cx, cy))
            if not (0 <= cx < int(self._grid_w) and 0 <= cy < int(self._grid_h)):
                continue
            if int(self._col_map[cy][cx]) != target:
                continue
            changed_cells.append((cx, cy))
            stack.append((cx - 1, cy))
            stack.append((cx + 1, cy))
            stack.append((cx, cy - 1))
            stack.append((cx, cy + 1))
        if not changed_cells:
            return False
        if push_undo:
            self._push_undo()
        for cx, cy in changed_cells:
            self._col_map[cy][cx] = tcol
        if not self._show_col_map:
            self._on_col_map_toggled(True)
        self._canvas.update()
        self._update_diagnostics()
        return True

    def _pick_collision_brush(self, tx: int, ty: int) -> bool:
        picked = self._collision_value_at(tx, ty)
        if picked is None:
            return False
        self._set_collision_brush(int(picked))
        return True

    def _clear_col_map_import_meta(self) -> None:
        self._col_map_meta = {}
        self._col_map_base = None

    def _count_col_map_overrides(self) -> int | None:
        if not (isinstance(self._col_map, list) and isinstance(self._col_map_base, list)):
            return None
        gh = min(len(self._col_map), len(self._col_map_base))
        changed = 0
        for y in range(gh):
            row_a = self._col_map[y]
            row_b = self._col_map_base[y]
            if not (isinstance(row_a, list) and isinstance(row_b, list)):
                continue
            gw = min(len(row_a), len(row_b))
            for x in range(gw):
                if int(row_a[x]) != int(row_b[x]):
                    changed += 1
        return changed

    def _refresh_collision_source_ui(self) -> None:
        lbl = getattr(self, "_lbl_collision_source", None)
        if lbl is None:
            return
        if self._col_map is None:
            lbl.setText("")
            return
        meta = self._col_map_meta if isinstance(self._col_map_meta, dict) else {}
        rel = str(meta.get("rel", "") or "").strip()
        plane = str(meta.get("plane", "") or "").strip().upper()
        if rel:
            overrides = self._count_col_map_overrides()
            if overrides is None:
                lbl.setText(tr("level.collision_source_import_unknown", src=plane or rel, rel=rel))
            else:
                lbl.setText(tr("level.collision_source_import", src=plane or rel, rel=rel, n=int(overrides)))
            return
        lbl.setText(tr("level.collision_source_manual"))

    def _scene_tilemap_entry_for_rel(self, rel: str) -> dict | None:
        rel_norm = str(rel or "").strip().replace("\\", "/")
        if not rel_norm or not isinstance(self._scene, dict):
            return None
        for tm in self._scene.get("tilemaps", []) or []:
            if not isinstance(tm, dict):
                continue
            tm_rel = str(tm.get("file", "") or "").strip().replace("\\", "/")
            if tm_rel == rel_norm:
                return tm
        return None

    def _resolve_collision_import_bg(self) -> tuple[str | None, Path | None, str]:
        choice = str(getattr(self, "_combo_collision_import_bg", None).currentData() if getattr(self, "_combo_collision_import_bg", None) is not None else "auto")
        front = str(getattr(self, "_bg_front", "scr1") or "scr1")
        candidates: list[tuple[str, int]] = []
        if choice == "scr1":
            candidates = [("scr1", int(self._combo_bg_scr1.currentIndex()))]
        elif choice == "scr2":
            candidates = [("scr2", int(self._combo_bg_scr2.currentIndex()))]
        else:
            ordered = [front, "scr2" if front == "scr1" else "scr1"]
            for plane in ordered:
                combo = self._combo_bg_scr1 if plane == "scr1" else self._combo_bg_scr2
                candidates.append((plane, int(combo.currentIndex())))
        for plane, idx in candidates:
            if 0 < idx < len(self._bg_rels):
                rel = self._bg_rels[idx]
                path = self._bg_paths[idx]
                if rel and path:
                    return str(rel), Path(path), plane.upper()
        return None, None, ""

    def _tilemap_collision_grid(self, tm: dict, path: Path) -> list[list[int]]:
        from PIL import Image as _PILImg

        img = _PILImg.open(path).convert("RGBA")
        tw = max(1, int(img.width // _TILE_PX))
        th = max(1, int(img.height // _TILE_PX))

        # Pre-resolved grid saved by the tilemap editor — always correct regardless
        # of tile pool ID ordering (tileset mode uses NGPC pipeline IDs which differ
        # from the raw pixel-hash IDs this function would otherwise derive).
        pre = tm.get("collision_grid")
        if isinstance(pre, list) and pre:
            grid = [[_TCOL_PASS for _x in range(tw)] for _y in range(th)]
            for y in range(min(th, len(pre))):
                row = pre[y]
                if not isinstance(row, list):
                    continue
                for x in range(min(tw, len(row))):
                    try:
                        grid[y][x] = int(row[x])
                    except Exception:
                        grid[y][x] = _TCOL_PASS
            return grid

        mode = str(tm.get("collision_mode", "tileset") or "tileset").strip().lower()
        if mode == "paint":
            raw = tm.get("collision_paint", []) or []
            grid = [[_TCOL_PASS for _x in range(tw)] for _y in range(th)]
            if isinstance(raw, list):
                for y in range(min(th, len(raw))):
                    row = raw[y]
                    if not isinstance(row, list):
                        continue
                    for x in range(min(tw, len(row))):
                        try:
                            grid[y][x] = int(row[x])
                        except Exception:
                            grid[y][x] = _TCOL_PASS
            return grid

        assign = [int(v) for v in (tm.get("collision_tileset", []) or [])]
        if not assign:
            return [[_TCOL_PASS for _x in range(tw)] for _y in range(th)]
        tile_ids: dict[bytes, int] = {}
        grid = [[_TCOL_PASS for _x in range(tw)] for _y in range(th)]
        next_id = 0
        for ty in range(th):
            for tx in range(tw):
                tile = img.crop((tx * _TILE_PX, ty * _TILE_PX, tx * _TILE_PX + _TILE_PX, ty * _TILE_PX + _TILE_PX))
                key = tile.tobytes()
                tid = tile_ids.get(key)
                if tid is None:
                    tid = next_id
                    tile_ids[key] = tid
                    next_id += 1
                grid[ty][tx] = assign[tid] if 0 <= tid < len(assign) else _TCOL_PASS
        return grid

    def _apply_imported_collision_grid(self, grid: list[list[int]]) -> tuple[int, int]:
        gw = max(1, int(self._grid_w))
        gh = max(1, int(self._grid_h))
        src_h = len(grid) if isinstance(grid, list) else 0
        src_w = max((len(row) for row in grid if isinstance(row, list)), default=0)
        new_map = [[_TCOL_PASS for _x in range(gw)] for _y in range(gh)]
        for y in range(min(gh, src_h)):
            row = grid[y]
            if not isinstance(row, list):
                continue
            for x in range(min(gw, len(row))):
                try:
                    new_map[y][x] = int(row[x])
                except Exception:
                    new_map[y][x] = _TCOL_PASS
        self._push_undo()
        self._col_map = new_map
        if not self._show_col_map:
            self._on_col_map_toggled(True)
        self._canvas.update()
        self._update_diagnostics()
        self._refresh_collision_source_ui()
        return src_w, src_h

    def _restore_col_map_import_base(self) -> None:
        self._col_map_base = None
        meta = self._col_map_meta if isinstance(self._col_map_meta, dict) else {}
        rel = str(meta.get("rel", "") or "").strip()
        if not rel:
            return
        tm = self._scene_tilemap_entry_for_rel(rel)
        if tm is None:
            return
        path = Path(rel)
        if self._base_dir and not path.is_absolute():
            path = self._base_dir / path
        if not path.exists():
            return
        try:
            self._col_map_base = self._tilemap_collision_grid(tm, path)
        except Exception:
            self._col_map_base = None

    def _auto_import_collision_silent(self) -> None:
        """Silently import tilemap collision at scene load when col_map is absent.

        Called once per scene the first time it is opened in the level tab.
        After this point col_map is the single source of truth: the user can
        freely paint on top (spring, damage, etc.) and those values persist.
        No dialog is shown — fails silently if no tilemap collision is defined.
        """
        try:
            rel, path, label = self._resolve_collision_import_bg()
            if not rel or path is None:
                return
            tm = self._scene_tilemap_entry_for_rel(rel)
            if tm is None:
                return
            # Only auto-import when the tilemap has real collision data.
            from core.scene_collision import _tilemap_has_collision
            if not _tilemap_has_collision(tm):
                return
            grid = self._tilemap_collision_grid(tm, path)
            self._apply_imported_collision_grid(grid)
            self._col_map_meta = {
                "kind":  "tilemap_import",
                "rel":   str(rel),
                "plane": str(label or "").lower(),
            }
            self._col_map_base = copy.deepcopy(grid)
        except Exception:
            pass

    def _import_collision_from_bg(self) -> None:
        rel, path, label = self._resolve_collision_import_bg()
        if not rel or path is None:
            QMessageBox.information(self, tr("level.save_title"), tr("level.collision_import_bg_none"))
            return
        tm = self._scene_tilemap_entry_for_rel(rel)
        if tm is None:
            QMessageBox.warning(self, tr("level.save_title"), tr("level.collision_import_bg_missing_entry", src=label or rel))
            return
        try:
            grid = self._tilemap_collision_grid(tm, path)
        except Exception as exc:
            QMessageBox.warning(self, tr("level.save_title"), tr("level.collision_import_bg_fail", src=label or rel, err=str(exc)))
            return
        src_w, src_h = self._apply_imported_collision_grid(grid)
        self._col_map_meta = {
            "kind": "tilemap_import",
            "rel": str(rel),
            "plane": str(label or "").lower(),
        }
        self._col_map_base = copy.deepcopy(grid)
        self._refresh_collision_source_ui()
        msg_key = "level.collision_import_bg_ok"
        if src_w != int(self._grid_w) or src_h != int(self._grid_h):
            msg_key = "level.collision_import_bg_ok_crop"
        QMessageBox.information(
            self,
            tr("level.save_title"),
            tr(msg_key, src=label or rel, sw=src_w, sh=src_h, dw=int(self._grid_w), dh=int(self._grid_h)),
        )

    def _on_regions_toggled(self, checked: bool) -> None:
        self._show_regions = checked
        w = getattr(self, "_chk_overlay_regions", None)
        if w is not None and bool(w.isChecked()) != bool(checked):
            w.blockSignals(True)
            w.setChecked(bool(checked))
            w.blockSignals(False)
        self._canvas.update()

    def _on_triggers_toggled(self, checked: bool) -> None:
        self._show_triggers = checked
        w = getattr(self, "_chk_overlay_triggers", None)
        if w is not None and bool(w.isChecked()) != bool(checked):
            w.blockSignals(True)
            w.setChecked(bool(checked))
            w.blockSignals(False)
        self._canvas.update()

    def _on_paths_toggled(self, checked: bool) -> None:
        self._show_paths = checked
        w = getattr(self, "_chk_overlay_paths", None)
        if w is not None and bool(w.isChecked()) != bool(checked):
            w.blockSignals(True)
            w.setChecked(bool(checked))
            w.blockSignals(False)
        self._canvas.update()

    def _on_waves_toggled(self, checked: bool) -> None:
        self._show_waves = checked
        w = getattr(self, "_chk_overlay_waves", None)
        if w is not None and bool(w.isChecked()) != bool(checked):
            w.blockSignals(True)
            w.setChecked(bool(checked))
            w.blockSignals(False)
        self._canvas.update()

    def _on_cam_from_bezel(self) -> None:
        bx, by = self._bezel_tile
        self._spin_cam_x.setValue(int(bx))
        self._spin_cam_y.setValue(int(by))
        self._on_layout_changed()

    def _update_layout_widgets(self) -> None:
        forced = bool(self._chk_forced_scroll.isChecked())
        sx_en = forced and bool(self._chk_scroll_x.isChecked())
        sy_en = forced and bool(self._chk_scroll_y.isChecked())
        self._spin_speed_x.setEnabled(sx_en)
        self._spin_speed_y.setEnabled(sy_en)

    def _on_layout_changed(self) -> None:
        self._cam_tile = (int(self._spin_cam_x.value()), int(self._spin_cam_y.value()))
        self._scroll_cfg = {
            "scroll_x": bool(self._chk_scroll_x.isChecked()),
            "scroll_y": bool(self._chk_scroll_y.isChecked()),
            "forced":   bool(self._chk_forced_scroll.isChecked()),
            "speed_x":  int(self._spin_speed_x.value()),
            "speed_y":  int(self._spin_speed_y.value()),
            "loop_x":   bool(self._chk_loop_x.isChecked()),
            "loop_y":   bool(self._chk_loop_y.isChecked()),
        }
        self._layout_cfg = {
            "cam_mode": str(self._combo_cam_mode.currentData() or "single_screen"),
            "bounds_auto": bool(self._chk_cam_bounds_auto.isChecked()),
            "clamp": bool(self._chk_cam_clamp.isChecked()),
            "min_x": int(self._spin_cam_min_x.value()),
            "min_y": int(self._spin_cam_min_y.value()),
            "max_x": int(self._spin_cam_max_x.value()),
            "max_y": int(self._spin_cam_max_y.value()),
            "follow_deadzone_x": int(self._spin_cam_deadzone_x.value()),
            "follow_deadzone_y": int(self._spin_cam_deadzone_y.value()),
            "follow_drop_margin_y": int(self._spin_cam_drop_margin_y.value()),
            "cam_lag": int(self._spin_cam_lag.value()),
        }
        self._update_cam_bounds_ui()
        self._apply_cam_clamp()
        self._update_layout_widgets()
        self._canvas.update()
        self._update_diagnostics()

    def _update_rules_widgets(self) -> None:
        lock_en = bool(self._chk_rule_lock_y.isChecked())
        band_en = bool(self._chk_rule_ground_band.isChecked())
        mir_en = bool(self._chk_rule_mirror.isChecked())

        self._spin_rule_lock_y.setEnabled(lock_en)
        self._spin_rule_ground_min.setEnabled(band_en)
        self._spin_rule_ground_max.setEnabled(band_en)
        self._spin_rule_mirror_axis.setEnabled(mir_en)
        self._spin_rule_void_damage.setEnabled(not bool(self._chk_rule_void_instant.isChecked()))
        self._spin_rule_goal_collectibles.setEnabled(True)
        self._spin_rule_time_limit.setEnabled(True)
        self._spin_rule_start_lives.setEnabled(True)
        self._spin_rule_start_continues.setEnabled(True)
        self._spin_rule_continue_restore_lives.setEnabled(True)
        hud_font_mode = str(self._combo_rule_hud_font.currentData() or "system")
        hud_style = str(self._combo_rule_hud_style.currentData() or "text") if hasattr(self, "_combo_rule_hud_style") else "text"
        if hasattr(self, "_grp_rule_hud_system"):
            self._grp_rule_hud_system.setVisible(hud_font_mode == "system")
        if hasattr(self, "_grp_rule_hud_custom"):
            self._grp_rule_hud_custom.setVisible(hud_font_mode == "custom")
        if hasattr(self, "_combo_rule_hud_band_color"):
            self._combo_rule_hud_band_color.setEnabled(hud_style == "band")
        if hasattr(self, "_spin_rule_hud_band_rows"):
            self._spin_rule_hud_band_rows.setEnabled(hud_style == "band")

        try:
            self._spin_rule_lock_y.setRange(0, max(0, int(self._grid_h) - 1))
            self._spin_rule_ground_min.setRange(0, max(0, int(self._grid_h) - 1))
            self._spin_rule_ground_max.setRange(0, max(0, int(self._grid_h) - 1))
            self._spin_rule_mirror_axis.setRange(0, max(0, int(self._grid_w) - 1))
        except Exception:
            pass

    def _on_hud_enabled_toggled(self, enabled: bool) -> None:
        """Enable/disable all HUD sub-controls when the master HUD switch changes."""
        for w in (
            self._chk_rule_hud_hp, self._chk_rule_hud_score,
            self._chk_rule_hud_collect, self._chk_rule_hud_timer,
            self._chk_rule_hud_lives, self._combo_rule_hud_pos,
            self._combo_rule_hud_font,
        ):
            w.setEnabled(enabled)
        for grp in (self._grp_rule_hud_system, self._grp_rule_hud_custom):
            grp.setEnabled(enabled)

    def _on_rules_changed(self, *_args) -> None:
        lock_en = bool(self._chk_rule_lock_y.isChecked())
        lock_y = int(self._spin_rule_lock_y.value())
        band_en = bool(self._chk_rule_ground_band.isChecked())
        gmin = int(self._spin_rule_ground_min.value())
        gmax = int(self._spin_rule_ground_max.value())
        if gmin > gmax:
            gmax = gmin
            self._spin_rule_ground_max.blockSignals(True)
            try:
                self._spin_rule_ground_max.setValue(int(gmax))
            finally:
                self._spin_rule_ground_max.blockSignals(False)
        mir_en = bool(self._chk_rule_mirror.isChecked())
        axis = int(self._spin_rule_mirror_axis.value())
        apply_waves = bool(self._chk_rule_apply_waves.isChecked())
        hazard_damage = int(self._spin_rule_hazard_damage.value())
        fire_damage = int(self._spin_rule_fire_damage.value())
        void_instant = bool(self._chk_rule_void_instant.isChecked())
        void_damage = int(self._spin_rule_void_damage.value())
        hazard_invul = int(self._spin_rule_hazard_invul.value())
        spring_force = int(self._spin_rule_spring_force.value())
        spring_dir = str(self._combo_rule_spring_dir.currentData() or "up")
        conveyor_speed = int(self._spin_rule_conveyor_speed.value())
        ice_friction = int(self._spin_rule_ice_friction.value())
        water_drag = int(self._spin_rule_water_drag.value())
        water_damage = int(self._spin_rule_water_damage.value())
        zone_force = int(self._spin_rule_zone_force.value())
        ladder_top_solid = bool(self._chk_rule_ladder_top_solid.isChecked())
        ladder_top_exit = bool(self._chk_rule_ladder_top_exit.isChecked())
        ladder_side_move = bool(self._chk_rule_ladder_side_move.isChecked())
        hud_enabled = bool(self._chk_rule_hud_enabled.isChecked())
        hud_show_hp = bool(self._chk_rule_hud_hp.isChecked())
        hud_show_score = bool(self._chk_rule_hud_score.isChecked())
        hud_show_collect = bool(self._chk_rule_hud_collect.isChecked())
        hud_show_timer = bool(self._chk_rule_hud_timer.isChecked())
        hud_show_lives = bool(self._chk_rule_hud_lives.isChecked())
        hud_pos = str(self._combo_rule_hud_pos.currentData() or "top")
        hud_font_mode = str(self._combo_rule_hud_font.currentData() or "system")
        hud_fixed_plane = str(self._combo_rule_hud_fixed_plane.currentData() or "none")
        hud_text_color = str(self._combo_rule_hud_text_color.currentData() or "white")
        hud_style = str(self._combo_rule_hud_style.currentData() or "text")
        hud_band_color = str(self._combo_rule_hud_band_color.currentData() or "blue")
        hud_band_rows = int(self._spin_rule_hud_band_rows.value())
        hud_digits_hp = int(self._spin_rule_hud_digits_hp.value())
        hud_digits_score = int(self._spin_rule_hud_digits_score.value())
        hud_digits_collect = int(self._spin_rule_hud_digits_collect.value())
        hud_digits_timer = int(self._spin_rule_hud_digits_timer.value())
        hud_digits_lives = int(self._spin_rule_hud_digits_lives.value())
        hud_digits_continues = int(self._spin_rule_hud_digits_continues.value())
        goal_collectibles = int(self._spin_rule_goal_collectibles.value())
        time_limit_sec = int(self._spin_rule_time_limit.value())
        start_lives = int(self._spin_rule_start_lives.value())
        start_continues = int(self._spin_rule_start_continues.value())
        continue_restore_lives = int(self._spin_rule_continue_restore_lives.value())

        self._level_rules = {
            "lock_y_en": lock_en,
            "lock_y": lock_y,
            "ground_band_en": band_en,
            "ground_min_y": gmin,
            "ground_max_y": gmax,
            "mirror_en": mir_en,
            "mirror_axis_x": axis,
            "apply_to_waves": apply_waves,
            "hazard_damage": hazard_damage,
            "fire_damage": fire_damage,
            "void_damage": void_damage,
            "void_instant": void_instant,
            "hazard_invul": hazard_invul,
            "spring_force": spring_force,
            "spring_dir": spring_dir,
            "conveyor_speed": conveyor_speed,
            "ice_friction": ice_friction,
            "water_drag": water_drag,
            "water_damage": water_damage,
            "zone_force": zone_force,
            "ladder_top_solid": ladder_top_solid,
            "ladder_top_exit": ladder_top_exit,
            "ladder_side_move": ladder_side_move,
            "hud_enabled": hud_enabled,
            "hud_show_hp": hud_show_hp,
            "hud_show_score": hud_show_score,
            "hud_show_collect": hud_show_collect,
            "hud_show_timer": hud_show_timer,
            "hud_show_lives": hud_show_lives,
            "hud_pos": hud_pos,
            "hud_font_mode": hud_font_mode,
            "hud_fixed_plane": hud_fixed_plane,
            "hud_text_color": hud_text_color,
            "hud_style": hud_style,
            "hud_band_color": hud_band_color,
            "hud_band_rows": hud_band_rows,
            "hud_digits_hp": hud_digits_hp,
            "hud_digits_score": hud_digits_score,
            "hud_digits_collect": hud_digits_collect,
            "hud_digits_timer": hud_digits_timer,
            "hud_digits_lives": hud_digits_lives,
            "hud_digits_continues": hud_digits_continues,
            "goal_collectibles": goal_collectibles,
            "time_limit_sec": time_limit_sec,
            "start_lives": start_lives,
            "start_continues": start_continues,
            "continue_restore_lives": continue_restore_lives,
            "hud_custom_font_digits": self._current_hud_font_digit_names(),
            "hud_custom_items": copy.deepcopy(self._hud_widgets()),
        }
        self._update_rules_widgets()
        self._refresh_hud_custom_ui()
        self._canvas.update()
        self._update_diagnostics()

    def _hud_widgets(self) -> list[dict]:
        widgets = self._level_rules.get("hud_custom_items", []) or []
        if not isinstance(widgets, list):
            widgets = []
        clean: list[dict] = []
        for w in widgets:
            if isinstance(w, dict):
                clean.append(w)
        self._level_rules["hud_custom_items"] = clean
        return clean

    def _current_hud_font_digit_names(self) -> list[str]:
        combos = getattr(self, "_combo_hud_font_digits", []) or []
        names: list[str] = []
        for combo in combos[:10]:
            names.append(str(combo.currentData() or ""))
        while len(names) < 10:
            names.append("")
        return names[:10]

    def _refresh_hud_font_digit_combos(self) -> None:
        combos = getattr(self, "_combo_hud_font_digits", None)
        if not combos:
            return
        names = sorted(str(k) for k in (self._entity_roles or {}).keys())
        current = list(self._level_rules.get("hud_custom_font_digits", [""] * 10) or [""] * 10)
        while len(current) < 10:
            current.append("")
        for digit, combo in enumerate(combos[:10]):
            keep = str(current[digit] or "")
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(tr("level.hud_widget_type_none"), "")
            digit_names = list(names)
            if keep and keep not in digit_names:
                digit_names.append(keep)
                digit_names.sort()
            for name in digit_names:
                combo.addItem(name, name)
            idx = combo.findData(keep)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)

    def _on_hud_font_digit_changed(self, _digit: int) -> None:
        self._level_rules["hud_custom_font_digits"] = self._current_hud_font_digit_names()
        self._refresh_hud_widget_props()
        self._on_rules_changed()

    def _refresh_hud_widget_type_combo(self, keep_value: str = "") -> None:
        combo = getattr(self, "_combo_hud_widget_type", None)
        if combo is None:
            return
        if not keep_value and 0 <= self._hud_widget_selected < len(self._hud_widgets()):
            keep_value = str(self._hud_widgets()[self._hud_widget_selected].get("type_name", "") or "")
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(tr("level.hud_widget_type_none"), "")
        names = sorted(str(k) for k in (self._entity_roles or {}).keys())
        if keep_value and keep_value not in names:
            names.append(keep_value)
            names.sort()
        for name in names:
            combo.addItem(name, name)
        idx = combo.findData(keep_value)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def _hud_widget_label(self, widget: dict, idx: int) -> str:
        kind = str(widget.get("kind", "icon") or "icon")
        metric = str(widget.get("metric", "score") or "score")
        name = str(widget.get("name", "") or "").strip()
        kind_lbl = tr("level.hud_widget_kind_icon") if kind == "icon" else tr("level.hud_widget_kind_value")
        metric_lbl = dict((k, tr(v)) for k, v in _HUD_WIDGET_METRICS).get(metric, metric)
        x = int(widget.get("x", 0) or 0)
        y = int(widget.get("y", 0) or 0)
        title = name or f"{kind_lbl} {idx + 1}"
        if kind == "value":
            digits = int(widget.get("digits", 5) or 5)
            return f"{title} [{kind_lbl} / {metric_lbl} / {digits}d] ({x},{y})"
        return f"{title} [{kind_lbl} / {metric_lbl}] ({x},{y})"

    def _set_hud_widget_props_enabled(self, enabled: bool) -> None:
        for attr in (
            "_edit_hud_widget_name",
            "_combo_hud_widget_kind",
            "_combo_hud_widget_metric",
            "_spin_hud_widget_x",
            "_spin_hud_widget_y",
            "_combo_hud_widget_type",
            "_spin_hud_widget_digits",
            "_chk_hud_widget_zero_pad",
        ):
            w = getattr(self, attr, None)
            if w is not None:
                w.setEnabled(enabled)
        self._btn_hud_widget_del.setEnabled(enabled)

    def _refresh_hud_widget_props(self) -> None:
        widgets = self._hud_widgets()
        idx = self._hud_widget_selected
        enabled = 0 <= idx < len(widgets)
        self._hud_widget_updating = True
        try:
            if not enabled:
                self._edit_hud_widget_name.setText("")
                self._combo_hud_widget_kind.setCurrentIndex(0)
                self._combo_hud_widget_metric.setCurrentIndex(0)
                self._spin_hud_widget_x.setValue(0)
                self._spin_hud_widget_y.setValue(0)
                self._spin_hud_widget_digits.setValue(5)
                self._chk_hud_widget_zero_pad.setChecked(True)
                self._refresh_hud_widget_type_combo("")
                self._lbl_hud_widget_runtime.setText(tr("level.hud_widget_none_sel"))
                self._set_hud_widget_props_enabled(False)
                return
            widget = widgets[idx]
            self._edit_hud_widget_name.setText(str(widget.get("name", "") or ""))
            kind = str(widget.get("kind", "icon") or "icon")
            metric = str(widget.get("metric", "score") or "score")
            kind_idx = self._combo_hud_widget_kind.findData(kind)
            metric_idx = self._combo_hud_widget_metric.findData(metric)
            self._combo_hud_widget_kind.setCurrentIndex(kind_idx if kind_idx >= 0 else 0)
            self._combo_hud_widget_metric.setCurrentIndex(metric_idx if metric_idx >= 0 else 0)
            self._spin_hud_widget_x.setValue(int(widget.get("x", 0) or 0))
            self._spin_hud_widget_y.setValue(int(widget.get("y", 0) or 0))
            self._spin_hud_widget_digits.setValue(int(widget.get("digits", 5) or 5))
            self._chk_hud_widget_zero_pad.setChecked(bool(widget.get("zero_pad", True)))
            self._refresh_hud_widget_type_combo(str(widget.get("type_name", "") or ""))
            type_name = str(widget.get("type_name", "") or "")
            if kind == "icon":
                self._lbl_hud_widget_runtime.setText(
                    tr("level.hud_widget_runtime_icon", metric=dict((k, tr(v)) for k, v in _HUD_WIDGET_METRICS).get(metric, metric), type_name=type_name or tr("level.hud_widget_type_none"))
                )
            else:
                font_ready = all(bool(s) for s in self._level_rules.get("hud_custom_font_digits", [""] * 10))
                self._lbl_hud_widget_runtime.setText(
                    tr(
                        "level.hud_widget_runtime_value",
                        metric=dict((k, tr(v)) for k, v in _HUD_WIDGET_METRICS).get(metric, metric),
                        digits=int(widget.get("digits", 5) or 5),
                        zero=tr("level.yes") if bool(widget.get("zero_pad", True)) else tr("level.no"),
                        font=tr("level.yes") if font_ready else tr("level.no"),
                    )
                )
            self._set_hud_widget_props_enabled(True)
            self._combo_hud_widget_type.setEnabled(kind == "icon")
            self._spin_hud_widget_digits.setEnabled(kind == "value")
            self._chk_hud_widget_zero_pad.setEnabled(kind == "value")
        finally:
            self._hud_widget_updating = False

    def _refresh_hud_widget_list(self) -> None:
        if not hasattr(self, "_hud_widget_list"):
            return
        widgets = self._hud_widgets()
        cur = self._hud_widget_selected
        self._hud_widget_list.blockSignals(True)
        self._hud_widget_list.clear()
        for i, widget in enumerate(widgets):
            self._hud_widget_list.addItem(self._hud_widget_label(widget, i))
        if widgets:
            cur = min(max(cur, 0), len(widgets) - 1)
            self._hud_widget_list.setCurrentRow(cur)
            self._hud_widget_selected = cur
        else:
            self._hud_widget_selected = -1
        self._hud_widget_list.blockSignals(False)
        self._refresh_hud_widget_props()

    def _refresh_hud_custom_ui(self) -> None:
        if not hasattr(self, "_grp_rule_hud_custom"):
            return
        is_custom = str(self._combo_rule_hud_font.currentData() or "system") == "custom"
        self._grp_rule_hud_custom.setVisible(is_custom)
        self._btn_hud_widget_add.setEnabled(is_custom)
        self._refresh_hud_font_digit_combos()
        self._refresh_hud_widget_list()

    def _add_hud_widget(self) -> None:
        widgets = self._hud_widgets()
        widgets.append({
            "name": f"hud_{len(widgets) + 1}",
            "kind": "icon",
            "metric": "score",
            "type_name": "",
            "x": 0,
            "y": 0,
            "digits": 5,
            "zero_pad": True,
        })
        self._hud_widget_selected = len(widgets) - 1
        self._refresh_hud_widget_list()
        self._on_rules_changed()

    def _remove_hud_widget(self) -> None:
        widgets = self._hud_widgets()
        idx = self._hud_widget_selected
        if not (0 <= idx < len(widgets)):
            return
        del widgets[idx]
        self._hud_widget_selected = min(idx, len(widgets) - 1)
        self._refresh_hud_widget_list()
        self._on_rules_changed()

    def _on_hud_widget_selected(self, row: int) -> None:
        self._hud_widget_selected = int(row)
        self._refresh_hud_widget_props()

    def _on_hud_widget_prop_changed(self, *_args) -> None:
        if self._hud_widget_updating:
            return
        widgets = self._hud_widgets()
        idx = self._hud_widget_selected
        if not (0 <= idx < len(widgets)):
            return
        widget = widgets[idx]
        widget["name"] = str(self._edit_hud_widget_name.text() or "").strip()
        widget["kind"] = str(self._combo_hud_widget_kind.currentData() or "icon")
        widget["metric"] = str(self._combo_hud_widget_metric.currentData() or "score")
        widget["x"] = int(self._spin_hud_widget_x.value())
        widget["y"] = int(self._spin_hud_widget_y.value())
        widget["type_name"] = str(self._combo_hud_widget_type.currentData() or "")
        widget["digits"] = int(self._spin_hud_widget_digits.value())
        widget["zero_pad"] = bool(self._chk_hud_widget_zero_pad.isChecked())
        self._refresh_hud_widget_list()
        self._refresh_hud_widget_props()
        self._on_rules_changed()

    def _on_layers_changed(self, *_args) -> None:
        try:
            front = str(getattr(self, "_bg_front", "scr1") or "scr1").strip().lower()
        except Exception:
            front = "scr1"
        if front not in ("scr1", "scr2"):
            front = "scr1"
        self._layers_cfg = {
            "scr1_parallax_x": int(self._spin_scr1_par_x.value()),
            "scr1_parallax_y": int(self._spin_scr1_par_y.value()),
            "scr2_parallax_x": int(self._spin_scr2_par_x.value()),
            "scr2_parallax_y": int(self._spin_scr2_par_y.value()),
            "bg_front": front,
        }

    # ------------------------------------------------------------------
    # X-1 — Palette cycling helpers
    # ------------------------------------------------------------------

    def _add_palfx_row(self) -> None:
        row = self._tbl_palfx.rowCount()
        self._tbl_palfx.insertRow(row)
        # Plane combo
        plane_cb = QComboBox()
        for p in ("SCR1", "SCR2", "SPR"):
            plane_cb.addItem(p, p)
        self._tbl_palfx.setCellWidget(row, 0, plane_cb)
        # Pal ID spinbox
        pal_spin = QSpinBox()
        pal_spin.setRange(0, 15)
        self._tbl_palfx.setCellWidget(row, 1, pal_spin)
        # Speed spinbox
        spd_spin = QSpinBox()
        spd_spin.setRange(1, 255)
        spd_spin.setValue(4)
        spd_spin.setToolTip(tr("level.palfx_speed_tt"))
        self._tbl_palfx.setCellWidget(row, 2, spd_spin)

    def _del_palfx_row(self) -> None:
        rows = sorted({idx.row() for idx in self._tbl_palfx.selectedIndexes()}, reverse=True)
        if not rows:
            r = self._tbl_palfx.rowCount()
            if r > 0:
                rows = [r - 1]
        for r in rows:
            self._tbl_palfx.removeRow(r)

    def _collect_pal_cycles(self) -> list:
        result = []
        for r in range(self._tbl_palfx.rowCount()):
            plane_w = self._tbl_palfx.cellWidget(r, 0)
            pal_w   = self._tbl_palfx.cellWidget(r, 1)
            spd_w   = self._tbl_palfx.cellWidget(r, 2)
            if not (plane_w and pal_w and spd_w):
                continue
            result.append({
                "plane":  str(plane_w.currentData() or "SPR"),
                "pal_id": int(pal_w.value()),
                "speed":  int(spd_w.value()),
            })
        return result

    def _load_pal_cycles(self, cycles: list) -> None:
        self._tbl_palfx.setRowCount(0)
        for cy in (cycles or []):
            if not isinstance(cy, dict):
                continue
            self._add_palfx_row()
            row = self._tbl_palfx.rowCount() - 1
            plane_w = self._tbl_palfx.cellWidget(row, 0)
            pal_w   = self._tbl_palfx.cellWidget(row, 1)
            spd_w   = self._tbl_palfx.cellWidget(row, 2)
            plane_val = str(cy.get("plane") or "SPR").upper()
            idx = plane_w.findData(plane_val)
            if idx >= 0:
                plane_w.setCurrentIndex(idx)
            pal_w.setValue(max(0, min(15, int(cy.get("pal_id") or 0))))
            spd_w.setValue(max(1, min(255, int(cy.get("speed") or 4))))

    def _update_cam_bounds_ui(self) -> None:
        clamp = bool(self._chk_cam_clamp.isChecked())
        auto = bool(self._chk_cam_bounds_auto.isChecked())
        mode = str(self._combo_cam_mode.currentData() or "single_screen")
        enable = clamp and (not auto)
        for w in (self._spin_cam_min_x, self._spin_cam_min_y, self._spin_cam_max_x, self._spin_cam_max_y):
            w.setEnabled(enable)
        follow_enable = (mode == "follow")
        self._spin_cam_deadzone_x.setEnabled(follow_enable)
        self._spin_cam_deadzone_y.setEnabled(follow_enable)
        self._spin_cam_drop_margin_y.setEnabled(follow_enable)
        self._btn_cam_bounds_from_map.setEnabled(bool(clamp))
        if clamp and auto:
            self._cam_bounds_from_map()

    def _cam_bounds_from_map(self) -> None:
        max_x = max(0, int(self._grid_w) - _SCREEN_W)
        max_y = max(0, int(self._grid_h) - _SCREEN_H)
        self._spin_cam_min_x.blockSignals(True)
        self._spin_cam_min_y.blockSignals(True)
        self._spin_cam_max_x.blockSignals(True)
        self._spin_cam_max_y.blockSignals(True)
        try:
            self._spin_cam_min_x.setValue(0)
            self._spin_cam_min_y.setValue(0)
            self._spin_cam_max_x.setValue(int(max_x))
            self._spin_cam_max_y.setValue(int(max_y))
        finally:
            self._spin_cam_min_x.blockSignals(False)
            self._spin_cam_min_y.blockSignals(False)
            self._spin_cam_max_x.blockSignals(False)
            self._spin_cam_max_y.blockSignals(False)

    def _apply_cam_clamp(self) -> None:
        if not bool(self._chk_cam_clamp.isChecked()):
            return
        min_x = int(self._spin_cam_min_x.value())
        min_y = int(self._spin_cam_min_y.value())
        max_x = int(self._spin_cam_max_x.value())
        max_y = int(self._spin_cam_max_y.value())
        x = max(min_x, min(max_x, int(self._cam_tile[0])))
        y = max(min_y, min(max_y, int(self._cam_tile[1])))
        if (x, y) != self._cam_tile:
            self._set_cam_tile(x, y, update_ui=True)

    def _set_cam_tile(self, tx: int, ty: int, *, update_ui: bool = True) -> None:
        self._cam_tile = (int(tx), int(ty))
        if update_ui:
            self._spin_cam_x.blockSignals(True)
            self._spin_cam_y.blockSignals(True)
            try:
                self._spin_cam_x.setValue(int(tx))
                self._spin_cam_y.setValue(int(ty))
            finally:
                self._spin_cam_x.blockSignals(False)
                self._spin_cam_y.blockSignals(False)
            self._on_layout_changed()

    def _apply_cam_mode_preset(self) -> None:
        mode = str(self._combo_cam_mode.currentData() or "single_screen")
        self._chk_scroll_x.blockSignals(True)
        self._chk_scroll_y.blockSignals(True)
        self._chk_forced_scroll.blockSignals(True)
        self._spin_speed_x.blockSignals(True)
        self._spin_speed_y.blockSignals(True)
        self._chk_loop_x.blockSignals(True)
        self._chk_loop_y.blockSignals(True)
        try:
            if mode == "single_screen":
                self._chk_scroll_x.setChecked(False)
                self._chk_scroll_y.setChecked(False)
                self._chk_forced_scroll.setChecked(False)
                self._spin_speed_x.setValue(0)
                self._spin_speed_y.setValue(0)
                self._chk_loop_x.setChecked(False)
                self._chk_loop_y.setChecked(False)
            elif mode == "follow":
                self._chk_forced_scroll.setChecked(False)
                self._chk_scroll_x.setChecked(True)
                self._chk_scroll_y.setChecked(True)
                self._spin_speed_x.setValue(0)
                self._spin_speed_y.setValue(0)
                self._spin_cam_deadzone_x.setValue(16)
                self._spin_cam_deadzone_y.setValue(12)
                self._spin_cam_drop_margin_y.setValue(20)
                self._chk_cam_clamp.setChecked(True)
            elif mode == "forced_scroll":
                self._chk_forced_scroll.setChecked(True)
                if not (self._chk_scroll_x.isChecked() or self._chk_scroll_y.isChecked()):
                    self._chk_scroll_x.setChecked(True)
                if self._spin_speed_x.value() == 0 and self._spin_speed_y.value() == 0:
                    self._spin_speed_x.setValue(1 if self._chk_scroll_x.isChecked() else 0)
                    self._spin_speed_y.setValue(1 if self._chk_scroll_y.isChecked() else 0)
            elif mode == "segments":
                self._chk_scroll_x.setChecked(True)
                self._chk_forced_scroll.setChecked(False)
            elif mode == "loop":
                if not (self._chk_loop_x.isChecked() or self._chk_loop_y.isChecked()):
                    self._chk_loop_x.setChecked(True)
        finally:
            self._chk_scroll_x.blockSignals(False)
            self._chk_scroll_y.blockSignals(False)
            self._chk_forced_scroll.blockSignals(False)
            self._spin_speed_x.blockSignals(False)
            self._spin_speed_y.blockSignals(False)
            self._chk_loop_x.blockSignals(False)
            self._chk_loop_y.blockSignals(False)
        self._on_layout_changed()

    def _apply_layout_preset_clicked(self) -> None:
        preset_key = str(self._combo_layout_preset.currentData() or "").strip()
        if not preset_key:
            return
        self._apply_layout_preset(preset_key)

    def _apply_layout_preset(self, preset_key: str) -> None:
        cfg = None
        for key, _label_key, data in _LAYOUT_PRESETS:
            if key == preset_key:
                cfg = data
                break
        if not isinstance(cfg, dict):
            return

        cam_mode = str(cfg.get("cam_mode", "single_screen") or "single_screen")
        idx_mode = self._combo_cam_mode.findData(cam_mode)

        widgets = [
            self._combo_cam_mode,
            self._chk_scroll_x,
            self._chk_scroll_y,
            self._chk_forced_scroll,
            self._spin_speed_x,
            self._spin_speed_y,
            self._chk_loop_x,
            self._chk_loop_y,
            self._chk_cam_clamp,
            self._chk_cam_bounds_auto,
            self._spin_cam_deadzone_x,
            self._spin_cam_deadzone_y,
            self._spin_cam_drop_margin_y,
        ]
        for widget in widgets:
            widget.blockSignals(True)
        try:
            if idx_mode >= 0:
                self._combo_cam_mode.setCurrentIndex(idx_mode)
            self._chk_scroll_x.setChecked(bool(cfg.get("scroll_x", False)))
            self._chk_scroll_y.setChecked(bool(cfg.get("scroll_y", False)))
            self._chk_forced_scroll.setChecked(bool(cfg.get("forced", False)))
            self._spin_speed_x.setValue(int(cfg.get("speed_x", 0) or 0))
            self._spin_speed_y.setValue(int(cfg.get("speed_y", 0) or 0))
            self._chk_loop_x.setChecked(bool(cfg.get("loop_x", False)))
            self._chk_loop_y.setChecked(bool(cfg.get("loop_y", False)))
            self._chk_cam_clamp.setChecked(bool(cfg.get("clamp", True)))
            self._chk_cam_bounds_auto.setChecked(bool(cfg.get("bounds_auto", True)))
            self._spin_cam_deadzone_x.setValue(_cfg_int(cfg, "deadzone_x", 16))
            self._spin_cam_deadzone_y.setValue(_cfg_int(cfg, "deadzone_y", 12))
            self._spin_cam_drop_margin_y.setValue(_cfg_int(cfg, "drop_margin_y", 20))
        finally:
            for widget in widgets:
                widget.blockSignals(False)

        self._lbl_layout_preset_hint.setText(tr(f"level.layout_preset_hint_{preset_key}"))
        self._on_layout_changed()

    def _on_map_mode_changed(self, _idx: int) -> None:
        mode = self._combo_map_mode.currentData()
        self._map_mode = mode
        self._open_density_widget.setVisible(mode == "open")
        is_td = (mode == "topdown")
        self._td_mode_widget.setVisible(is_td)
        self._chk_dir_walls.setVisible(is_td)
        self._topdown_features_widget.setVisible(is_td)
        if is_td:
            self._on_td_gen_mode_changed()
        else:
            self._chk_td_ca.setVisible(False)
            self._td_bsp_widget.setVisible(False)
            self._wall_dens_widget.setVisible(False)
        has_roles = mode in _MAP_MODE_ROLES
        self._tile_role_scroll.setVisible(has_roles)
        if has_roles:
            self._rebuild_tile_role_ui(mode)
        self._refresh_collision_brush_ui()
        self._update_diagnostics()

    def _on_td_gen_mode_changed(self, _idx: int = 0) -> None:
        is_bsp = self._combo_td_gen_mode.currentData() == "bsp"
        self._chk_td_ca.setVisible(not is_bsp)
        self._td_scatter_widget.setVisible(not is_bsp)
        self._td_bsp_widget.setVisible(is_bsp)
        self._wall_dens_widget.setVisible(not is_bsp)

    def _rebuild_tile_role_ui(self, mode: str) -> None:
        """Repopulate the visual tile-role mapping UI for the given mode."""
        # Clear old widgets
        while self._tile_role_layout.count():
            item = self._tile_role_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if mode not in _MAP_MODE_ROLES:
            return

        # Ensure per-mode dict exists
        if mode not in self._tile_ids:
            self._tile_ids[mode] = {}

        for role_key, tcol, label_key in _MAP_MODE_ROLES[mode]:
            row_w = QWidget()
            row_h = QHBoxLayout(row_w)
            row_h.setContentsMargins(0, 0, 0, 0)
            row_h.setSpacing(4)
            role_tip = tr(_tile_role_tt_key(tcol))
            entry = self._tile_ids[mode].get(role_key, tcol)

            # Tile thumbnail (from selected BG)
            thumb = QLabel("")
            thumb.setFixedSize(26, 26)
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb.setStyleSheet("border: 1px solid #333; background: #111;")
            thumb.setToolTip(role_tip)
            row_h.addWidget(thumb)
            # Color swatch
            swatch = QLabel("■")
            swatch_col = _TCOL_OVERLAY.get(tcol, QColor(160, 160, 160))
            swatch.setStyleSheet(
                f"color: rgba({swatch_col.red()},{swatch_col.green()},"
                f"{swatch_col.blue()},255); font-size: 12px;")
            swatch.setToolTip(role_tip)
            row_h.addWidget(swatch)
            # Label
            lbl = QLabel(tr(label_key))
            lbl.setStyleSheet("font-size: 10px;")
            lbl.setToolTip(role_tip)
            row_h.addWidget(lbl, 1)

            edit = QLineEdit()
            edit.setFixedWidth(140)
            edit.setPlaceholderText(tr("level.tile_role_list_ph"))
            edit.setText(_tile_id_text(entry, tcol))
            edit.setToolTip(role_tip + "\n\n" + tr("level.tile_role_list_tt"))

            def _update_thumb(v: object, _lbl=thumb, _tcol=tcol) -> None:
                ids = _tile_id_variants(v, _tcol)
                pm, tip = self._tile_thumb(int(ids[0]))
                if pm is not None:
                    _lbl.setPixmap(pm)
                    _lbl.setText("")
                else:
                    _lbl.setPixmap(QPixmap())
                    _lbl.setText("—")
                    tip = ""
                if tip and len(ids) > 1:
                    tip = tip + "\n" + tr(
                        "level.tile_role_preview_multi_tt",
                        n=len(ids),
                        values=", ".join(str(x) for x in ids),
                    )
                _lbl.setToolTip(tip)

            def _apply_ids(ids_value: object, _m=mode, _k=role_key, _e=edit, _upd=_update_thumb, _tcol=tcol) -> None:
                ids = _tile_id_variants(ids_value, _tcol)
                text = ",".join(str(v) for v in ids)
                if _e.text().strip() != text:
                    _e.blockSignals(True)
                    _e.setText(text)
                    _e.blockSignals(False)
                self._on_tile_role_id_changed(_m, _k, ids if len(ids) > 1 else ids[0])
                _upd(ids)

            def _commit_ids(_e=edit) -> None:
                _apply_ids(_e.text())

            def _pick_ids(_default=tcol, _e=edit, _app=_apply_ids) -> None:
                current_ids = _tile_id_variants(_e.text(), _default)
                pm_src, src_name = self._role_preview_source()
                dlg = _ProcgenTilePickerDialog(
                    self,
                    source_pm=pm_src,
                    source_name=src_name,
                    selected_ids=current_ids,
                    default_id=_default,
                )
                if dlg.exec() != int(QDialog.DialogCode.Accepted):
                    return
                _app(dlg.selected_ids())

            _update_thumb(entry)
            edit.editingFinished.connect(_commit_ids)
            row_h.addWidget(edit)

            btn_pick = QPushButton(tr("level.tile_role_pick"))
            btn_pick.setToolTip(role_tip + "\n\n" + tr("level.tile_role_pick_tt"))
            btn_pick.clicked.connect(_pick_ids)
            row_h.addWidget(btn_pick)
            self._tile_role_layout.addWidget(row_w)

        self._tile_role_layout.addStretch()

    def _on_tile_role_id_changed(self, mode: str, role_key: str, value: object) -> None:
        if mode not in self._tile_ids:
            self._tile_ids[mode] = {}
        self._tile_ids[mode][role_key] = _tile_id_storage(value, 0)
        if self._scene is not None:
            self._scene["tile_ids"] = copy.deepcopy(self._tile_ids)
            self._scene["map_mode"] = str(self._map_mode or "none")
            self._on_save()
        self._update_diagnostics()

    # ------------------------------------------------------------------
    # Map generators
    # ------------------------------------------------------------------

    def _apply_dir_walls(self, col: list[list[int]], gw: int, gh: int) -> None:
        """Convert single-face SOLID border tiles to directional wall types."""
        for cy in range(gh):
            for cx in range(gw):
                if col[cy][cx] != _TCOL_SOLID:
                    continue
                n_free = (cy > 0)     and col[cy-1][cx] == _TCOL_PASS
                s_free = (cy < gh-1)  and col[cy+1][cx] == _TCOL_PASS
                w_free = (cx > 0)     and col[cy][cx-1] == _TCOL_PASS
                e_free = (cx < gw-1)  and col[cy][cx+1] == _TCOL_PASS
                open_count = sum([n_free, s_free, w_free, e_free])
                if open_count == 1:
                    # One open face → directional wall.
                    # WALL_X = "entry from X is blocked" (runtime semantics).
                    # s_free: open space is south, player enters from south → block southward entry = WALL_S.
                    # n_free: open space is north, player enters from north → block northward entry = WALL_N.
                    if s_free:
                        col[cy][cx] = _TCOL_WALL_S
                    elif n_free:
                        col[cy][cx] = _TCOL_WALL_N
                    elif e_free:
                        col[cy][cx] = _TCOL_WALL_E
                    elif w_free:
                        col[cy][cx] = _TCOL_WALL_W
                elif open_count == 2 and not (n_free and s_free) and not (e_free and w_free):
                    # Two perpendicular open faces → corner tile
                    if n_free and e_free:
                        col[cy][cx] = _TCOL_CORNER_NE
                    elif n_free and w_free:
                        col[cy][cx] = _TCOL_CORNER_NW
                    elif s_free and e_free:
                        col[cy][cx] = _TCOL_CORNER_SE
                    elif s_free and w_free:
                        col[cy][cx] = _TCOL_CORNER_SW

    def _gen_platformer(self, rng: random.Random, gw: int, gh: int) -> list[list[int]]:
        col = [[_TCOL_PASS] * gw for _ in range(gh)]
        # Solid border
        for x in range(gw):
            col[0][x]    = _TCOL_SOLID
            col[gh-1][x] = _TCOL_SOLID
        for y in range(gh):
            col[y][0]    = _TCOL_SOLID
            col[y][gw-1] = _TCOL_SOLID
        # One-way platforms
        for _ in range(max(2, gw // 4)):
            py     = rng.randint(3, gh - 4)
            px     = rng.randint(2, gw - 6)
            length = rng.randint(3, min(8, gw - px - 2))
            for x in range(px, px + length):
                col[py][x] = _TCOL_ONE_WAY
        # Solid pillars
        for _ in range(gw // 6):
            py = rng.randint(2, gh - 3)
            px = rng.randint(2, gw - 2)
            if col[py][px] == _TCOL_PASS:
                col[py][px] = _TCOL_SOLID
        # Ladders
        for _ in range(2):
            lx     = rng.randint(3, gw - 3)
            ly_top = rng.randint(2, gh // 2)
            ly_bot = rng.randint(gh // 2, gh - 2)
            for ly in range(ly_top, ly_bot + 1):
                if col[ly][lx] == _TCOL_PASS:
                    col[ly][lx] = _TCOL_LADDER
        # Damage spikes on floor
        for x in range(2, gw - 2):
            if col[gh-2][x] == _TCOL_PASS and rng.random() < 0.08:
                col[gh-2][x] = _TCOL_DAMAGE
        return col

    def _gen_topdown(
        self, rng: random.Random, gw: int, gh: int,
        dir_walls: bool, wall_dens: float = 0.20,
        gen_int_walls: bool = True, gen_water: bool = True,
        border_n: bool = True, border_s: bool = True,
        border_e: bool = True, border_w: bool = True,
    ) -> list[list[int]]:
        col = [[_TCOL_PASS] * gw for _ in range(gh)]
        # Border walls (per-side optional)
        if border_n:
            for x in range(gw): col[0][x]      = _TCOL_SOLID
        if border_s:
            for x in range(gw): col[gh-1][x]   = _TCOL_SOLID
        if border_w:
            for y in range(gh): col[y][0]       = _TCOL_SOLID
        if border_e:
            for y in range(gh): col[y][gw-1]    = _TCOL_SOLID
        # Interior wall clusters (density-driven)
        if gen_int_walls:
            n_clusters = max(1, int(gw * gh * wall_dens / 4))
            for _ in range(n_clusters):
                wx = rng.randint(2, gw - 3)
                wy = rng.randint(2, gh - 3)
                cw = rng.randint(1, 3)
                ch = rng.randint(1, 3)
                for dy in range(ch):
                    for dx in range(cw):
                        nx, ny = wx + dx, wy + dy
                        if 1 <= nx < gw-1 and 1 <= ny < gh-1:
                            col[ny][nx] = _TCOL_SOLID
        # Water bodies: connected blobs (pond) or random-walk rivers
        if gen_water:
            n_bodies = max(1, (gw * gh) // 200)
            for _ in range(n_bodies):
                sx = rng.randint(2, gw - 3)
                sy = rng.randint(2, gh - 3)
                if col[sy][sx] != _TCOL_PASS:
                    continue
                if rng.random() < 0.5:
                    # River: random walk
                    river_len = rng.randint(max(3, (gw + gh) // 8), max(4, (gw + gh) // 5))
                    rx, ry = sx, sy
                    dirs = [(0, 1), (0, -1), (1, 0), (-1, 0)]
                    last_d = rng.choice(dirs)
                    for _s in range(river_len):
                        if col[ry][rx] == _TCOL_PASS:
                            col[ry][rx] = _TCOL_DAMAGE
                        if rng.random() < 0.7:
                            d = last_d
                        else:
                            d = rng.choice(dirs)
                        nx2, ny2 = rx + d[0], ry + d[1]
                        if 1 <= nx2 < gw - 1 and 1 <= ny2 < gh - 1:
                            rx, ry = nx2, ny2
                            last_d = d
                else:
                    # Pond: BFS blob
                    blob_size = rng.randint(3, max(4, (gw * gh) // 80))
                    queue = [(sx, sy)]
                    visited: set[tuple[int, int]] = {(sx, sy)}
                    placed = 0
                    while queue and placed < blob_size:
                        bx, by = queue.pop(rng.randint(0, len(queue) - 1))
                        if col[by][bx] == _TCOL_PASS:
                            col[by][bx] = _TCOL_DAMAGE
                            placed += 1
                        for ddx, ddy in [(0,1),(0,-1),(1,0),(-1,0)]:
                            nx2, ny2 = bx + ddx, by + ddy
                            if (1 <= nx2 < gw - 1 and 1 <= ny2 < gh - 1
                                    and (nx2, ny2) not in visited
                                    and col[ny2][nx2] == _TCOL_PASS):
                                visited.add((nx2, ny2))
                                queue.append((nx2, ny2))
        if dir_walls:
            self._apply_dir_walls(col, gw, gh)
            _dw = {_TCOL_WALL_N, _TCOL_WALL_S, _TCOL_WALL_E, _TCOL_WALL_W,
                   _TCOL_CORNER_NE, _TCOL_CORNER_NW, _TCOL_CORNER_SE, _TCOL_CORNER_SW}
            if border_n and border_w and col[0][1] in _dw and col[1][0] in _dw:
                col[0][0] = _TCOL_CORNER_SE
            if border_n and border_e and col[0][gw-2] in _dw and col[1][gw-1] in _dw:
                col[0][gw-1] = _TCOL_CORNER_SW
            if border_s and border_w and col[gh-1][1] in _dw and col[gh-2][0] in _dw:
                col[gh-1][0] = _TCOL_CORNER_NE
            if border_s and border_e and col[gh-1][gw-2] in _dw and col[gh-2][gw-1] in _dw:
                col[gh-1][gw-1] = _TCOL_CORNER_NW
        return col

    # ------------------------------------------------------------------
    # Topdown shared helpers
    # ------------------------------------------------------------------

    def _td_carve_tunnel(
        self,
        col: list[list[int]],
        gw: int, gh: int,
        p1: tuple[int, int],
        p2: tuple[int, int],
        rng: random.Random,
        corridor_w: int = 1,
    ) -> None:
        """L-shaped tunnel between p1 and p2, corridor_w tiles wide."""
        x1, y1 = p1
        x2, y2 = p2
        half = corridor_w // 2
        offsets = range(-half, corridor_w - half)
        if rng.random() < 0.5:
            # Horizontal first, then vertical
            for x in range(min(x1, x2), max(x1, x2) + 1):
                for dw in offsets:
                    ny = y1 + dw
                    if 0 <= x < gw and 0 <= ny < gh:
                        col[ny][x] = _TCOL_PASS
            for y in range(min(y1, y2), max(y1, y2) + 1):
                for dw in offsets:
                    nx = x2 + dw
                    if 0 <= nx < gw and 0 <= y < gh:
                        col[y][nx] = _TCOL_PASS
        else:
            # Vertical first, then horizontal
            for y in range(min(y1, y2), max(y1, y2) + 1):
                for dw in offsets:
                    nx = x1 + dw
                    if 0 <= nx < gw and 0 <= y < gh:
                        col[y][nx] = _TCOL_PASS
            for x in range(min(x1, x2), max(x1, x2) + 1):
                for dw in offsets:
                    ny = y2 + dw
                    if 0 <= x < gw and 0 <= ny < gh:
                        col[ny][x] = _TCOL_PASS

    def _td_cellular_smooth(
        self,
        col: list[list[int]],
        gw: int, gh: int,
        iterations: int = 3,
    ) -> None:
        """
        B5/S3 CA smoothing on interior wall tiles.
        - SOLID survives if >= 3 SOLID neighbours (8-dir).
        - PASS becomes SOLID if >= 5 SOLID neighbours.
        - Special tiles (water, damage…) are preserved unchanged.
        - OOB cells count as SOLID (reinforces the border).
        """
        _PRESERVE = {
            _TCOL_DAMAGE, _TCOL_WATER, _TCOL_FIRE, _TCOL_VOID,
            _TCOL_DOOR, _TCOL_LADDER,
        }
        for _ in range(iterations):
            new_col = [row[:] for row in col]
            for cy in range(1, gh - 1):
                for cx in range(1, gw - 1):
                    if col[cy][cx] in _PRESERVE:
                        continue
                    walls = 0
                    for dy in range(-1, 2):
                        for dx in range(-1, 2):
                            if dx == 0 and dy == 0:
                                continue
                            ny2, nx2 = cy + dy, cx + dx
                            if ny2 < 0 or ny2 >= gh or nx2 < 0 or nx2 >= gw:
                                walls += 1
                            elif col[ny2][nx2] == _TCOL_SOLID:
                                walls += 1
                    if col[cy][cx] == _TCOL_SOLID:
                        new_col[cy][cx] = _TCOL_SOLID if walls >= 3 else _TCOL_PASS
                    else:
                        new_col[cy][cx] = _TCOL_SOLID if walls >= 5 else _TCOL_PASS
            col[:] = new_col

    def _td_flood_fix(
        self,
        col: list[list[int]],
        gw: int, gh: int,
        rng: random.Random,
        min_region: int = 8,
        corridor_w: int = 1,
    ) -> None:
        """
        Connectivity repair:
        - Finds all walkable (PASS + special) regions by BFS.
        - Tiny regions (< min_region) are filled with SOLID.
        - Larger isolated regions are connected to the main one via L-tunnel.
        """
        from collections import deque
        _WALKABLE = {
            _TCOL_PASS, _TCOL_DAMAGE, _TCOL_WATER, _TCOL_FIRE,
            _TCOL_LADDER, _TCOL_DOOR,
        }

        def bfs(sx: int, sy: int) -> set[tuple[int, int]]:
            q: deque[tuple[int, int]] = deque([(sx, sy)])
            vis: set[tuple[int, int]] = {(sx, sy)}
            while q:
                cx, cy = q.popleft()
                for ddx, ddy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx2, ny2 = cx + ddx, cy + ddy
                    if (0 <= nx2 < gw and 0 <= ny2 < gh
                            and (nx2, ny2) not in vis
                            and col[ny2][nx2] in _WALKABLE):
                        vis.add((nx2, ny2))
                        q.append((nx2, ny2))
            return vis

        all_w = {(x, y) for y in range(gh) for x in range(gw) if col[y][x] in _WALKABLE}
        seen: set[tuple[int, int]] = set()
        regions: list[set[tuple[int, int]]] = []
        for pos in all_w:
            if pos in seen:
                continue
            r = bfs(*pos)
            regions.append(r)
            seen |= r

        if len(regions) <= 1:
            return

        regions.sort(key=len, reverse=True)
        main = regions[0]

        for small in regions[1:]:
            if len(small) < min_region:
                for x, y in small:
                    if col[y][x] == _TCOL_PASS:
                        col[y][x] = _TCOL_SOLID
            else:
                s_samp = list(small)
                m_samp = list(main)
                if len(s_samp) > 40:
                    s_samp = rng.sample(s_samp, 40)
                if len(m_samp) > 40:
                    m_samp = rng.sample(m_samp, 40)
                best_d = 10 ** 9
                best_pair: tuple[tuple[int, int], tuple[int, int]] | None = None
                for p1 in s_samp:
                    for p2 in m_samp:
                        d = abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])
                        if d < best_d:
                            best_d = d
                            best_pair = (p1, p2)
                if best_pair:
                    self._td_carve_tunnel(col, gw, gh, best_pair[0], best_pair[1], rng, corridor_w)
                    main = main | small

    def _gen_topdown_bsp(
        self,
        rng: random.Random,
        gw: int, gh: int,
        gen_water: bool,
        border_n: bool, border_s: bool,
        border_e: bool, border_w: bool,
        bsp_depth: int,
        loop_pct: int,
        corridor_w: int = 1,
    ) -> list[list[int]]:
        """BSP room placement + MST corridor graph + optional water."""
        import heapq

        col: list[list[int]] = [[_TCOL_SOLID] * gw for _ in range(gh)]

        if not border_n:
            for x in range(gw): col[0][x]      = _TCOL_PASS
        if not border_s:
            for x in range(gw): col[gh-1][x]   = _TCOL_PASS
        if not border_w:
            for y in range(gh): col[y][0]       = _TCOL_PASS
        if not border_e:
            for y in range(gh): col[y][gw-1]    = _TCOL_PASS

        x0 = 1 if border_w else 0
        x1 = (gw - 1) if border_e else gw
        y0 = 1 if border_n else 0
        y1 = (gh - 1) if border_s else gh

        # Minimum BSP leaf size and minimum room size scale with corridor_w
        # so rooms are always navigable for sprites of that footprint.
        min_leaf = max(4, corridor_w * 3 + 2)
        min_room = max(2, corridor_w + 1)

        if x1 - x0 < min_leaf * 2 or y1 - y0 < min_leaf * 2:
            return col

        # --- BSP partition ---
        class _Leaf:
            __slots__ = ('x', 'y', 'w', 'h', 'left', 'right', 'room')
            def __init__(self, lx: int, ly: int, lw: int, lh: int) -> None:
                self.x, self.y, self.w, self.h = lx, ly, lw, lh
                self.left = self.right = self.room = None

            def split(self, _rng: random.Random, min_sz: int = 4) -> bool:
                if self.left:
                    return False
                go_h = _rng.random() < 0.5
                if self.w > self.h * 1.25:
                    go_h = False
                elif self.h > self.w * 1.25:
                    go_h = True
                span = self.h if go_h else self.w
                if span < min_sz * 2:
                    return False
                pos = _rng.randint(min_sz, span - min_sz)
                if go_h:
                    self.left  = _Leaf(self.x,       self.y,       self.w,       pos)
                    self.right = _Leaf(self.x,       self.y + pos, self.w,       self.h - pos)
                else:
                    self.left  = _Leaf(self.x,       self.y,       pos,          self.h)
                    self.right = _Leaf(self.x + pos, self.y,       self.w - pos, self.h)
                return True

        root = _Leaf(x0, y0, x1 - x0, y1 - y0)
        leaves: list[_Leaf] = [root]
        for _ in range(bsp_depth):
            grew = False
            nxt: list[_Leaf] = []
            for lf in leaves:
                if lf.split(rng, min_sz=min_leaf):
                    assert lf.left is not None and lf.right is not None
                    nxt += [lf.left, lf.right]
                    grew = True
                else:
                    nxt.append(lf)
            leaves = nxt
            if not grew:
                break

        # --- Carve rooms in leaf nodes ---
        rooms: list[tuple[int, int]] = []
        for lf in leaves:
            shrink_w = rng.randint(1, max(1, lf.w - min_room - 1))
            shrink_h = rng.randint(1, max(1, lf.h - min_room - 1))
            rw = max(min_room, lf.w - shrink_w)
            rh = max(min_room, lf.h - shrink_h)
            rx = lf.x + rng.randint(1, max(1, lf.w - rw - 1))
            ry = lf.y + rng.randint(1, max(1, lf.h - rh - 1))
            rx = max(x0, min(rx, x1 - rw))
            ry = max(y0, min(ry, y1 - rh))
            rw = min(rw, x1 - rx)
            rh = min(rh, y1 - ry)
            if rw < min_room or rh < min_room:
                continue
            for dy in range(rh):
                for dx in range(rw):
                    col[ry + dy][rx + dx] = _TCOL_PASS
            lf.room = (rx + rw // 2, ry + rh // 2)
            rooms.append(lf.room)

        # --- MST + loop corridors ---
        if len(rooms) >= 2:
            heap: list[tuple[int, int, int]] = []
            for i in range(len(rooms)):
                for j in range(i + 1, len(rooms)):
                    d = abs(rooms[i][0] - rooms[j][0]) + abs(rooms[i][1] - rooms[j][1])
                    heapq.heappush(heap, (d, i, j))

            par = list(range(len(rooms)))

            def _find(n: int) -> int:
                while par[n] != n:
                    par[n] = par[par[n]]
                    n = par[n]
                return n

            def _union(a: int, b: int) -> None:
                par[_find(a)] = _find(b)

            mst_e: list[tuple[int, int]] = []
            extra_e: list[tuple[int, int]] = []
            while heap:
                _, i, j = heapq.heappop(heap)
                if _find(i) == _find(j):
                    extra_e.append((i, j))
                else:
                    _union(i, j)
                    mst_e.append((i, j))

            for i, j in mst_e:
                self._td_carve_tunnel(col, gw, gh, rooms[i], rooms[j], rng, corridor_w)

            if extra_e and loop_pct > 0:
                n_loops = max(1, int(len(extra_e) * loop_pct / 100))
                for i, j in rng.sample(extra_e, min(n_loops, len(extra_e))):
                    self._td_carve_tunnel(col, gw, gh, rooms[i], rooms[j], rng, corridor_w)

        # --- Water (ponds only — rivers don't fit well in corridor maps) ---
        if gen_water and gw > 4 and gh > 4:
            for _ in range(max(1, (gw * gh) // 300)):
                sx = rng.randint(2, gw - 3)
                sy = rng.randint(2, gh - 3)
                if col[sy][sx] != _TCOL_PASS:
                    continue
                blob_size = rng.randint(2, max(3, (gw * gh) // 150))
                q2: list[tuple[int, int]] = [(sx, sy)]
                vis2: set[tuple[int, int]] = {(sx, sy)}
                placed = 0
                while q2 and placed < blob_size:
                    bx, by = q2.pop(rng.randint(0, len(q2) - 1))
                    if col[by][bx] == _TCOL_PASS:
                        col[by][bx] = _TCOL_DAMAGE
                        placed += 1
                    for ddx, ddy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                        nx2, ny2 = bx + ddx, by + ddy
                        if (1 <= nx2 < gw - 1 and 1 <= ny2 < gh - 1
                                and (nx2, ny2) not in vis2
                                and col[ny2][nx2] == _TCOL_PASS):
                            vis2.add((nx2, ny2))
                            q2.append((nx2, ny2))

        return col

    def _gen_shmup(self, rng: random.Random, gw: int, gh: int) -> list[list[int]]:
        col = [[_TCOL_PASS] * gw for _ in range(gh)]
        # Top / bottom solid borders
        for x in range(gw):
            col[0][x]    = _TCOL_SOLID
            col[gh-1][x] = _TCOL_SOLID
        # Right-side terrain columns
        for cx in range(gw // 2, gw):
            if rng.random() < 0.25:
                height = rng.randint(1, gh // 3)
                if rng.random() < 0.5:
                    for cy in range(1, 1 + height):
                        col[cy][cx] = _TCOL_SOLID
                else:
                    for cy in range(gh - 1 - height, gh - 1):
                        col[cy][cx] = _TCOL_SOLID
        # Damage strips
        for _ in range(2):
            dy = rng.randint(2, gh - 3)
            for cx in range(gw // 4, gw * 3 // 4):
                if rng.random() < 0.3 and col[dy][cx] == _TCOL_PASS:
                    col[dy][cx] = _TCOL_DAMAGE
        return col

    def _gen_open(self, rng: random.Random, gw: int, gh: int,
                  obstacle_dens: float) -> list[list[int]]:
        col = [[_TCOL_PASS] * gw for _ in range(gh)]
        n_obs = int(gw * gh * obstacle_dens)
        for _ in range(n_obs):
            cx = rng.randint(1, gw - 2)
            cy = rng.randint(1, gh - 2)
            col[cy][cx] = _TCOL_SOLID
        for _ in range(max(1, n_obs // 10)):
            cx = rng.randint(1, gw - 2)
            cy = rng.randint(1, gh - 2)
            if col[cy][cx] == _TCOL_PASS:
                col[cy][cx] = _TCOL_DAMAGE
        return col

    def _on_size_changed(self) -> None:
        self._grid_w = self._spin_gw.value()
        self._grid_h = self._spin_gh.value()
        self._update_size_limits_ui()
        try:
            self._update_cam_bounds_ui()
            self._apply_cam_clamp()
        except Exception:
            pass
        try:
            self._update_rules_widgets()
            # Clamp current values to new ranges
            self._spin_rule_lock_y.setValue(min(int(self._spin_rule_lock_y.value()), max(0, int(self._grid_h) - 1)))
            self._spin_rule_ground_min.setValue(min(int(self._spin_rule_ground_min.value()), max(0, int(self._grid_h) - 1)))
            self._spin_rule_ground_max.setValue(min(int(self._spin_rule_ground_max.value()), max(0, int(self._grid_h) - 1)))
            self._spin_rule_mirror_axis.setValue(min(int(self._spin_rule_mirror_axis.value()), max(0, int(self._grid_w) - 1)))
            self._on_rules_changed()
        except Exception:
            pass
        self._canvas.updateGeometry()
        self._canvas.resize(self._canvas.sizeHint())
        self._canvas.update()
        self._update_diagnostics()

    def _update_size_limits_ui(self) -> None:
        try:
            gw, gh = int(self._grid_w), int(self._grid_h)
            single = (gw <= _SCREEN_W and gh <= _SCREEN_H)
            over32 = (gw > 32 or gh > 32)
            if single:
                txt, col = tr("level.size_info_single"), "#888"
            elif over32:
                txt, col = tr("level.size_info_stream"), "#4caf50"
            else:
                txt, col = tr("level.size_info_multi"), "#888"
            self._lbl_size_limits.setText(txt)
            self._lbl_size_limits.setStyleSheet(f"color: {col}; font-size: 10px;")
            tip = tr("level.size_limits_tt")
            if over32:
                tip = tip + "\n" + tr("level.size_limits_warn")
            self._lbl_size_limits.setToolTip(tip)
            # SCR2 constraint hint: when SCR1 is in stream mode, warn that SCR2 must stay ≤ 32×32
            scr1_is_large = self._pixmap_is_large_map(getattr(self, "_bg_pixmap_scr1", None))
            lbl_scr2_hint = getattr(self, "_lbl_scr2_stream_hint", None)
            if lbl_scr2_hint is not None:
                if over32 and scr1_is_large:
                    lbl_scr2_hint.setText(tr("level.scr2_limited_hint"))
                    lbl_scr2_hint.setStyleSheet("color: #ff9800; font-size: 10px;")
                    lbl_scr2_hint.setVisible(True)
                else:
                    lbl_scr2_hint.setVisible(False)
            elif over32 and scr1_is_large:
                # Fallback: append to the size-limits label tooltip
                extra = "\n" + tr("level.scr2_limited_hint")
                self._lbl_size_limits.setToolTip(tip + extra)
            # Show/hide large-map row
            large_row = getattr(self, "_large_map_row", None)
            if large_row is not None:
                large_row.setVisible(over)
            # Budget label: show grid dimensions + stream indicator
            lbl_bgt = getattr(self, "_lbl_tile_budget", None)
            if lbl_bgt is not None:
                if over:
                    gw = int(self._grid_w)
                    gh = int(self._grid_h)
                    pm1 = getattr(self, "_bg_pixmap_scr1", None)
                    pm2 = getattr(self, "_bg_pixmap_scr2", None)
                    pm = pm1 or pm2
                    if pm is not None and not pm.isNull():
                        est = (pm.width() // _TILE_PX) * (pm.height() // _TILE_PX)
                        # Budget thresholds are for unique tiles (unknown until export)
                        # Show map tile count as a reference
                        bgt_col = "#9aa3ad"
                        if est > 384:
                            bgt_col = "#e03030"
                            bgt_txt = f"{gw}\xd7{gh} \u2014 STREAM  \ud83d\udd34 ~{est} tiles"
                        elif est > 320:
                            bgt_col = "#e07020"
                            bgt_txt = f"{gw}\xd7{gh} \u2014 STREAM  \U0001f7e0 ~{est} tiles"
                        elif est > 256:
                            bgt_col = "#c0a000"
                            bgt_txt = f"{gw}\xd7{gh} \u2014 STREAM  \u26a0 ~{est} tiles"
                        else:
                            bgt_txt = f"{gw}\xd7{gh} \u2014 STREAM"
                        lbl_bgt.setStyleSheet(f"color: {bgt_col}; font-size: 10px;")
                    else:
                        bgt_txt = f"{gw}\xd7{gh} \u2014 STREAM"
                        lbl_bgt.setStyleSheet("color: #9aa3ad; font-size: 10px;")
                    lbl_bgt.setText(bgt_txt)
                else:
                    lbl_bgt.setText("")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Game profile (presets)
    # ------------------------------------------------------------------

    def _on_profile_changed(self, _idx: int) -> None:
        try:
            self._level_profile = str(self._combo_profile.currentData() or "none")
        except Exception:
            self._level_profile = "none"
        self._apply_genre_combo_order(self._level_profile)
        self._update_diagnostics()

    def _apply_genre_combo_order(self, genre: str) -> None:
        """Reorder all genre-sensitive combos so the most relevant items for
        the given genre appear first, separated from the rest by a divider.
        Safe to call with any genre value; no-ops when genre has no entry."""
        try:
            _reorder_combo_for_genre(self._combo_trig_cond,   genre, _GENRE_PRIORITY_TRIGGER_CONDS)
            _reorder_combo_for_genre(self._combo_trig_action, genre, _GENRE_PRIORITY_TRIGGER_ACTS)
            _reorder_combo_for_genre(self._combo_trig_preset, genre, _GENRE_PRIORITY_TRIGGER_PRESETS)
            _reorder_combo_for_genre(self._combo_reg_kind,    genre, _GENRE_PRIORITY_REGION_KINDS)
            _reorder_combo_for_genre(self._combo_reg_preset,  genre, _GENRE_PRIORITY_REGION_PRESETS)
        except Exception:
            pass

    def _apply_profile_clicked(self) -> None:
        self._apply_profile_preset(str(self._level_profile or "none"))

    def _apply_profile_preset(self, profile: str) -> None:
        preset = _PROFILE_PRESETS.get(profile)
        if not preset:
            return

        # Size (optional)
        gw = preset.get("gw")
        gh = preset.get("gh")
        if isinstance(gw, int) and isinstance(gh, int):
            self._spin_gw.blockSignals(True)
            self._spin_gh.blockSignals(True)
            self._spin_gw.setValue(max(1, min(255, int(gw))))
            self._spin_gh.setValue(max(1, min(255, int(gh))))
            self._spin_gw.blockSignals(False)
            self._spin_gh.blockSignals(False)
            self._on_size_changed()

        # Procgen map mode (optional)
        map_mode = str(preset.get("map_mode", "") or "").strip()
        if map_mode:
            idx = self._combo_map_mode.findData(map_mode)
            if idx >= 0:
                self._combo_map_mode.blockSignals(True)
                self._combo_map_mode.setCurrentIndex(idx)
                self._combo_map_mode.blockSignals(False)
                self._on_map_mode_changed(int(self._combo_map_mode.currentIndex()))

        # Layout defaults (scroll / forced / loop / speed)
        def _set_chk(w, key: str) -> None:
            if key in preset:
                w.blockSignals(True)
                w.setChecked(bool(preset[key]))
                w.blockSignals(False)

        def _set_spin(w, key: str) -> None:
            if key in preset:
                w.blockSignals(True)
                w.setValue(int(preset[key]))
                w.blockSignals(False)

        _set_chk(self._chk_scroll_x, "scroll_x")
        _set_chk(self._chk_scroll_y, "scroll_y")
        _set_chk(self._chk_forced_scroll, "forced")
        _set_chk(self._chk_loop_x, "loop_x")
        _set_chk(self._chk_loop_y, "loop_y")
        _set_spin(self._spin_speed_x, "speed_x")
        _set_spin(self._spin_speed_y, "speed_y")
        self._on_layout_changed()

    def _set_level_profile_value(self, profile: str) -> None:
        known = {k for k, _label in _LEVEL_PROFILES}
        profile = str(profile or "none").strip()
        if profile not in known:
            profile = "none"
        self._level_profile = profile
        idx = self._combo_profile.findData(profile)
        self._combo_profile.blockSignals(True)
        self._combo_profile.setCurrentIndex(idx if idx >= 0 else 0)
        self._combo_profile.blockSignals(False)
        self._update_diagnostics()

    def _has_nonzero_col_map(self) -> bool:
        if not isinstance(self._col_map, list):
            return False
        for row in self._col_map:
            if not isinstance(row, list):
                continue
            for cell in row:
                try:
                    if int(cell) != 0:
                        return True
                except Exception:
                    if cell:
                        return True
        return False

    def _scene_is_guided_workflow_empty(self) -> bool:
        has_scroll = any((
            bool(self._scroll_cfg.get("scroll_x")),
            bool(self._scroll_cfg.get("scroll_y")),
            bool(self._scroll_cfg.get("forced")),
            bool(self._scroll_cfg.get("loop_x")),
            bool(self._scroll_cfg.get("loop_y")),
            int(self._scroll_cfg.get("speed_x", 0) or 0) != 0,
            int(self._scroll_cfg.get("speed_y", 0) or 0) != 0,
        ))
        has_rules = any((
            bool(getattr(self, "_chk_rule_lock_y", None) and self._chk_rule_lock_y.isChecked()),
            bool(getattr(self, "_chk_rule_ground_band", None) and self._chk_rule_ground_band.isChecked()),
            bool(getattr(self, "_chk_rule_mirror", None) and self._chk_rule_mirror.isChecked()),
        ))
        return not any((
            self._entities,
            self._waves,
            self._regions,
            self._triggers,
            self._paths,
            self._has_nonzero_col_map(),
            str(self._map_mode or "none").strip() != "none",
            str(self._level_profile or "none").strip() != "none",
            has_scroll,
            has_rules,
        ))


    # ------------------------------------------------------------------
    # Undo / Redo
    # ------------------------------------------------------------------

    _UNDO_MAX = 64

    def _snapshot(self) -> dict:
        return {
            "entities": copy.deepcopy(self._entities),
            "waves":    copy.deepcopy(self._waves),
            "col_map":  copy.deepcopy(self._col_map),
            "col_map_meta": copy.deepcopy(self._col_map_meta),
            "col_map_base": copy.deepcopy(self._col_map_base),
            "regions":  copy.deepcopy(self._regions),
            "text_labels": copy.deepcopy(self._text_labels),
            "triggers": copy.deepcopy(self._triggers),
            "paths":    copy.deepcopy(self._paths),
        }

    def _restore(self, snap: dict) -> None:
        self._entities = snap["entities"]
        self._waves    = snap["waves"]
        self._col_map  = snap.get("col_map", None)
        self._col_map_meta = snap.get("col_map_meta", {}) or {}
        self._col_map_base = snap.get("col_map_base", None)
        self._regions  = snap.get("regions", [])
        self._text_labels = snap.get("text_labels", [])
        self._triggers = snap.get("triggers", [])
        self._paths    = snap.get("paths", [])
        self._ensure_entity_ids()
        self._normalize_trigger_entity_refs()
        self._refresh_collision_source_ui()

    def _push_undo(self) -> None:
        self._undo_stack.append(self._snapshot())
        if len(self._undo_stack) > self._UNDO_MAX:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._update_undo_buttons()

    def _undo(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append(self._snapshot())
        self._restore(self._undo_stack.pop())
        self._selected = min(self._selected, len(self._entities) - 1)
        self._update_undo_buttons()
        self._refresh_props()
        self._refresh_wave_list()
        self._region_selected = min(self._region_selected, len(self._regions) - 1)
        self._refresh_region_list()
        self._refresh_region_props()
        self._text_label_selected = min(self._text_label_selected, len(self._text_labels) - 1)
        self._refresh_text_labels_ui()
        self._trigger_selected = min(self._trigger_selected, len(self._triggers) - 1)
        self._refresh_trigger_list()
        self._refresh_trigger_props()
        self._path_selected = min(self._path_selected, len(self._paths) - 1)
        if 0 <= self._path_selected < len(self._paths):
            pts = (self._paths[self._path_selected].get("points", []) or [])
            self._path_point_selected = min(self._path_point_selected, len(pts) - 1)
        else:
            self._path_point_selected = -1
        self._refresh_path_list()
        self._refresh_path_props()
        self._on_entity_placed()
        self._canvas.update()

    def _redo(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot())
        self._restore(self._redo_stack.pop())
        self._selected = min(self._selected, len(self._entities) - 1)
        self._update_undo_buttons()
        self._refresh_props()
        self._refresh_wave_list()
        self._region_selected = min(self._region_selected, len(self._regions) - 1)
        self._refresh_region_list()
        self._refresh_region_props()
        self._text_label_selected = min(self._text_label_selected, len(self._text_labels) - 1)
        self._refresh_text_labels_ui()
        self._trigger_selected = min(self._trigger_selected, len(self._triggers) - 1)
        self._refresh_trigger_list()
        self._refresh_trigger_props()
        self._path_selected = min(self._path_selected, len(self._paths) - 1)
        if 0 <= self._path_selected < len(self._paths):
            pts = (self._paths[self._path_selected].get("points", []) or [])
            self._path_point_selected = min(self._path_point_selected, len(pts) - 1)
        else:
            self._path_point_selected = -1
        self._refresh_path_list()
        self._refresh_path_props()
        self._on_entity_placed()
        self._canvas.update()

    def _update_undo_buttons(self) -> None:
        self._btn_undo.setEnabled(bool(self._undo_stack))
        self._btn_redo.setEnabled(bool(self._redo_stack))

    def _copy_name(self, base_name: str, used_names: set[str], fallback: str) -> str:
        root = str(base_name or fallback).strip() or fallback
        if root.endswith("_copy"):
            root = root[:-5].rstrip("_") or fallback
        cand = f"{root}_copy"
        if cand not in used_names:
            return cand
        n = 2
        while True:
            cand = f"{root}_copy{n}"
            if cand not in used_names:
                return cand
            n += 1

    def _dup_offset_xy(self, x: int, y: int, *, w: int = 1, h: int = 1) -> tuple[int, int]:
        max_x = max(0, int(self._grid_w) - max(1, int(w)))
        max_y = max(0, int(self._grid_h) - max(1, int(h)))
        ox = max(-int(x), min(1, max_x - int(x)))
        oy = max(-int(y), min(1, max_y - int(y)))
        if ox == 0 and oy == 0:
            if int(x) > 0:
                ox = -1
            elif int(y) > 0:
                oy = -1
        return max(0, min(max_x, int(x) + ox)), max(0, min(max_y, int(y) + oy))

    def _dup_offset_points(self, pts: list[dict]) -> list[dict]:
        if not pts:
            return []
        max_x, max_y = self._path_px_limits()
        for ox, oy in (
            (_TILE_PX, 0), (0, _TILE_PX), (_TILE_PX, _TILE_PX),
            (-_TILE_PX, 0), (0, -_TILE_PX), (-_TILE_PX, -_TILE_PX),
        ):
            shifted: list[dict] = []
            ok = True
            for pt in pts:
                x, y = _path_point_to_px(pt)
                x += ox
                y += oy
                if not (0 <= x <= max_x and 0 <= y <= max_y):
                    ok = False
                    break
                shifted.append(_path_point_make(x, y))
            if ok:
                return shifted
        return copy.deepcopy(pts)

    def _duplicate_active_selection(self) -> None:
        # Path editor: prefer duplicating the selected point, otherwise duplicate the whole path.
        if getattr(self, "_path_edit", False):
            pidx = int(getattr(self, "_path_selected", -1))
            if 0 <= pidx < len(self._paths):
                self._push_undo()
                path = self._paths[pidx]
                pts = path.get("points", []) or []
                pti = int(getattr(self, "_path_point_selected", -1))
                if 0 <= pti < len(pts):
                    src_pt = pts[pti]
                    src_px, src_py = _path_point_to_px(src_pt)
                    max_x, max_y = self._path_px_limits()
                    nx = min(max_x, src_px + _TILE_PX)
                    ny = src_py
                    if nx == src_px and src_px > 0:
                        nx = max(0, src_px - _TILE_PX)
                    if ny == src_py and src_py > 0 and nx == src_px:
                        ny = max(0, src_py - _TILE_PX)
                    pts.insert(pti + 1, _path_point_make(nx, ny))
                    path["points"] = pts
                    self._path_point_selected = pti + 1
                    self._refresh_path_list()
                    self._refresh_path_points()
                else:
                    dup = copy.deepcopy(path)
                    dup["id"] = _new_id()
                    dup["name"] = self._copy_name(
                        str(path.get("name", "") or "path"),
                        {str(p.get("name", "") or "") for p in self._paths if isinstance(p, dict)},
                        "path",
                    )
                    dup["points"] = self._dup_offset_points(list(dup.get("points", []) or []))
                    self._paths.insert(pidx + 1, dup)
                    self._path_selected = pidx + 1
                    self._path_point_selected = -1
                    self._refresh_path_list()
                    self._refresh_path_props()
                self._canvas.update()
                self._update_diagnostics()
            return

        # Region editor duplicates the selected region.
        if getattr(self, "_region_edit", False):
            idx = int(getattr(self, "_region_selected", -1))
            if 0 <= idx < len(self._regions):
                self._push_undo()
                src = self._regions[idx]
                dup = copy.deepcopy(src)
                dup["id"] = _new_id()
                dup["name"] = self._copy_name(
                    str(src.get("name", "") or "region"),
                    {str(r.get("name", "") or "") for r in self._regions if isinstance(r, dict)},
                    "region",
                )
                nx, ny = self._dup_offset_xy(
                    int(src.get("x", 0)),
                    int(src.get("y", 0)),
                    w=max(1, int(src.get("w", 1))),
                    h=max(1, int(src.get("h", 1))),
                )
                dup["x"] = nx
                dup["y"] = ny
                self._regions.insert(idx + 1, dup)
                self._region_selected = idx + 1
                self._refresh_region_list()
                self._refresh_region_props()
                self._refresh_trigger_regions()
                self._canvas.update()
                self._update_diagnostics()
            return

        # Wave edit duplicates the selected wave entity.
        if getattr(self, "_wave_edit", False):
            widx = int(getattr(self, "_wave_selected", -1))
            eidx = int(getattr(self, "_wave_entity_sel", -1))
            if 0 <= widx < len(self._waves):
                wave_ents = self._waves[widx].get("entities", [])
                if 0 <= eidx < len(wave_ents):
                    self._push_undo()
                    src = copy.deepcopy(wave_ents[eidx])
                    nx, ny = self._dup_offset_xy(int(src.get("x", 0)), int(src.get("y", 0)))
                    src["x"] = nx
                    src["y"] = ny
                    wave_ents.insert(eidx + 1, src)
                    self._wave_entity_sel = eidx + 1
                    self._refresh_wave_list()
                    self._refresh_wave_entity_props()
                    self._canvas.update()
                    self._update_budget()
            return

        # Default: duplicate the selected static entity.
        idx = int(getattr(self, "_selected", -1))
        if 0 <= idx < len(self._entities):
            self._push_undo()
            src = copy.deepcopy(self._entities[idx])
            src["id"] = _new_id()
            w_px, h_px = self._type_sizes.get(str(src.get("type", "")), (_TILE_PX, _TILE_PX))
            w_tiles = max(1, (int(w_px) + _TILE_PX - 1) // _TILE_PX)
            h_tiles = max(1, (int(h_px) + _TILE_PX - 1) // _TILE_PX)
            nx, ny = self._dup_offset_xy(int(src.get("x", 0)), int(src.get("y", 0)), w=w_tiles, h=h_tiles)
            src["x"] = nx
            src["y"] = ny
            self._entities.insert(idx + 1, src)
            self._selected = idx + 1
            self._canvas.entity_selected.emit(self._selected)
            self._canvas.entity_placed.emit()
            self._canvas.update()

    # ------------------------------------------------------------------
    # Entity slots
    # ------------------------------------------------------------------

    def _on_entity_selected(self, idx: int) -> None:
        self._selected = idx
        self._refresh_props()
        self._update_budget()
        # Sync type list to the selected entity's type so the role dropdown
        # reflects (and allows changing) that type's role on the fly.
        if 0 <= idx < len(self._entities):
            ent_type = self._entities[idx].get("type", "")
            for row in range(self._type_list.count()):
                item = self._type_list.item(row)
                if item and item.data(Qt.ItemDataRole.UserRole) == ent_type:
                    if self._type_list.currentRow() != row:
                        self._type_list.setCurrentRow(row)
                    break

    def _update_coords(self, tx: int, ty: int) -> None:
        if tx < 0:
            self._lbl_coords.setText("")
            return
        px_x = tx * _TILE_PX
        px_y = ty * _TILE_PX
        self._lbl_coords.setText(f"tile ({tx}, {ty})  px ({px_x}, {px_y})")

    def _on_entity_placed(self) -> None:
        n = len(self._entities)
        self._lbl_status.setText(tr("level.status", n=n))
        self._update_budget()
        self._refresh_props()
        if self._wave_edit:
            self._refresh_wave_entity_props()

    def _on_prop_changed(self, attr: str, value: int) -> None:
        if self._updating_props:
            return
        idx = self._selected
        if 0 <= idx < len(self._entities):
            self._entities[idx][attr] = value
            if attr == "data":
                self._refresh_entity_runtime_ui()
            self._canvas.update()
            self._update_diagnostics()

    def _delete_selected(self) -> None:
        idx = self._selected
        if 0 <= idx < len(self._entities):
            self._push_undo()
            del self._entities[idx]
            self._selected = min(idx, len(self._entities) - 1)
            self._canvas.entity_selected.emit(self._selected)
            self._canvas.entity_placed.emit()
            self._canvas.update()
            self._refresh_props()

    def _on_inst_prop_changed(self, attr: str, value: int) -> None:
        if self._updating_props:
            return
        idx = self._selected
        if 0 <= idx < len(self._entities):
            self._entities[idx][attr] = value
            if attr == "behavior":
                self._refresh_entity_runtime_ui()
            self._canvas.update()
            self._update_diagnostics()

    def _on_ai_param_changed(self, attr: str, value: int) -> None:
        if self._updating_props:
            return
        idx = self._selected
        if 0 <= idx < len(self._entities):
            if value == {"ai_speed": 1, "ai_range": 10, "ai_lose_range": 16, "ai_change_every": 60}.get(attr, 0):
                self._entities[idx].pop(attr, None)
            else:
                self._entities[idx][attr] = value
            self._update_diagnostics()

    def _on_ent_role_changed(self, combo_idx: int) -> None:
        if self._updating_props:
            return
        idx = self._selected
        if not (0 <= idx < len(self._entities)):
            return
        # itemData is "" for the default entry, or one of _ROLES for an explicit override.
        data = self._combo_ent_role.itemData(combo_idx)
        raw = str(data or "").strip().lower()
        # If the chosen override equals the sprite-type role, clear it (no-op storage).
        type_name = str(self._entities[idx].get("type", "") or "").strip()
        type_role = str(self._entity_roles.get(type_name, "prop") or "prop").strip().lower()
        if raw == type_role:
            raw = ""
        set_entity_role_override(self._entities[idx], raw)
        # Refresh the read-only role label in the header too.
        self._refresh_props()
        self._update_diagnostics()
        self._canvas.update()

    def _on_ent_clamp_map_toggled(self, checked: bool) -> None:
        if self._updating_props:
            return
        idx = self._selected
        if not (0 <= idx < len(self._entities)):
            return
        flags = int(self._entities[idx].get("flags", 0) or 0)
        if checked:
            flags |= _ENT_FLAG_CLAMP_MAP
        else:
            flags &= ~_ENT_FLAG_CLAMP_MAP
        if flags:
            self._entities[idx]["flags"] = flags
        else:
            self._entities[idx].pop("flags", None)
        self._refresh_entity_runtime_ui()
        self._canvas.update()
        self._update_diagnostics()

    def _on_ent_clamp_camera_toggled(self, checked: bool) -> None:
        if self._updating_props:
            return
        idx = self._selected
        if not (0 <= idx < len(self._entities)):
            return
        flags = int(self._entities[idx].get("flags", 0) or 0)
        if checked:
            flags |= _ENT_FLAG_CLAMP_CAMERA
        else:
            flags &= ~_ENT_FLAG_CLAMP_CAMERA
        if flags:
            self._entities[idx]["flags"] = flags
        else:
            self._entities[idx].pop("flags", None)
        self._refresh_entity_runtime_ui()
        self._canvas.update()
        self._update_diagnostics()

    def _on_ent_allow_ledge_fall_toggled(self, checked: bool) -> None:
        if self._updating_props:
            return
        idx = self._selected
        if not (0 <= idx < len(self._entities)):
            return
        flags = int(self._entities[idx].get("flags", 0) or 0)
        if checked:
            flags |= _ENT_FLAG_ALLOW_LEDGE_FALL
        else:
            flags &= ~_ENT_FLAG_ALLOW_LEDGE_FALL
        if flags:
            self._entities[idx]["flags"] = flags
        else:
            self._entities[idx].pop("flags", None)
        self._refresh_entity_runtime_ui()
        self._canvas.update()
        self._update_diagnostics()

    def _on_ent_respawn_toggled(self, checked: bool) -> None:
        if self._updating_props:
            return
        idx = self._selected
        if not (0 <= idx < len(self._entities)):
            return
        self._entities[idx]["respawn"] = bool(checked)
        if not checked:
            self._entities[idx].pop("respawn", None)
        self._refresh_entity_runtime_ui()
        self._canvas.update()
        self._update_diagnostics()

    def _on_ent_path_changed(self, combo_idx: int) -> None:
        if self._updating_props:
            return
        idx = self._selected
        if 0 <= idx < len(self._entities):
            if combo_idx <= 0:
                self._entities[idx].pop("path_id", None)
            else:
                path_idx = combo_idx - 1
                if 0 <= path_idx < len(self._paths):
                    self._entities[idx]["path_id"] = str(self._paths[path_idx].get("id", ""))
                    self._path_selected = path_idx
                    self._path_point_selected = -1
            self._canvas.update()
            self._refresh_entity_runtime_ui()
        self._refresh_ent_path_status()
        self._refresh_path_list()
        self._refresh_path_props()
        self._update_diagnostics()

    # ------------------------------------------------------------------
    # Entity type preset actions (A1 / A2)
    # ------------------------------------------------------------------

    def _et_fields_from_entity(self, ent: dict) -> dict:
        """Extract the type-relevant fields from an entity instance."""
        return {
            "role":            str(ent.get("role", "enemy")),
            "behavior":        int(ent.get("behavior", 0)),
            "ai_speed":        int(ent.get("ai_speed", 1) or 1),
            "ai_range":        int(ent.get("ai_range", 10) or 10),
            "ai_lose_range":   int(ent.get("ai_lose_range", 16) or 16),
            "ai_change_every": int(ent.get("ai_change_every", 60) or 60),
            "direction":       int(ent.get("direction", 0)),
            "data":            int(ent.get("data", 0)),
            "flags":           int(ent.get("flags", 0)),
        }

    def _on_save_as_type(self) -> None:
        """Save current entity as a template in Globals → entity_templates."""
        if self._project_data_root is None:
            return
        idx = self._selected
        if not (0 <= idx < len(self._entities)):
            return
        ent = self._entities[idx]

        default_name = str(ent.get("type", "")).strip().replace(" ", "_") or "new_template"
        name, ok = QInputDialog.getText(
            self, tr("level.etype_save_title"), tr("level.etype_save_prompt"), text=default_name
        )
        if not ok or not name.strip():
            return

        import re as _re
        from core.entity_templates import (
            new_entity_template as _new_tpl,
            get_entity_templates as _get_tpls,
            snapshot_sprite_fields as _snap_spr,
        )
        safe_name = _re.sub(r"[^A-Za-z0-9_]", "_", name.strip()).strip("_") or "new_template"
        type_id = f"etpl_{safe_name}"

        # Get sprite meta for this entity type to capture visual data
        sprite_meta = self._sprite_meta_for_type(str(ent.get("type", "")))

        tpls = self._project_data_root.setdefault("entity_templates", [])
        existing = next((t for t in tpls if isinstance(t, dict) and t.get("id") == type_id), None)

        behavior_params = self._et_fields_from_entity(ent)
        if existing is not None:
            existing.update(behavior_params)
            existing["name"] = safe_name
            if sprite_meta:
                existing.update(_snap_spr(sprite_meta))
        else:
            new_t = _new_tpl(safe_name, sprite_meta=sprite_meta, behavior_params=behavior_params)
            new_t["id"] = type_id
            tpls.append(new_t)

        # Refresh merged list
        raw_et = (self._project_data_root.get("entity_types", []) or [])
        self._project_entity_types = (
            [t for t in tpls if isinstance(t, dict)]
            + [t for t in raw_et if isinstance(t, dict)]
        )

        ent["type_id"] = type_id
        self._refresh_etype_label()

        if self._on_save:
            self._on_save()

    def _on_apply_type(self) -> None:
        """Apply a type preset to current entity (A2)."""
        if not self._project_entity_types:
            QMessageBox.information(self, tr("level.etype_apply_title"), tr("level.etype_no_types"))
            return
        idx = self._selected
        if not (0 <= idx < len(self._entities)):
            return

        items = [f"{t.get('name', t.get('id', '?'))}  [{t.get('id', '')}]"
                 for t in self._project_entity_types]
        choice, ok = QInputDialog.getItem(
            self, tr("level.etype_apply_title"), tr("level.etype_apply_prompt"),
            items, 0, False
        )
        if not ok:
            return

        chosen_idx = items.index(choice)
        t = self._project_entity_types[chosen_idx]
        ent = self._entities[idx]

        for field in ("role", "behavior", "ai_speed", "ai_range", "ai_lose_range",
                      "ai_change_every", "direction", "data", "flags"):
            if field in t:
                if t[field] == ET_DEFAULTS.get(field):
                    ent.pop(field, None)
                else:
                    ent[field] = t[field]
        ent["type_id"] = t.get("id", "")

        # Refresh the inspector UI
        self._updating_props = True
        try:
            self._combo_ent_behavior.setCurrentIndex(int(ent.get("behavior", 0)))
            self._spin_ai_speed.setValue(max(1, min(255, int(ent.get("ai_speed", 1) or 1))))
            self._spin_ai_range.setValue(max(0, min(255, int(ent.get("ai_range", 10) or 10))))
            self._spin_ai_lose_range.setValue(max(0, min(255, int(ent.get("ai_lose_range", 16) or 16))))
            self._spin_ai_change_every.setValue(max(1, min(255, int(ent.get("ai_change_every", 60) or 60))))
        finally:
            self._updating_props = False

        self._refresh_entity_runtime_ui()
        self._refresh_etype_label()
        self._canvas.update()
        self._update_diagnostics()

    def _refresh_etype_label(self) -> None:
        """Update the type_id hint label and group visibility."""
        idx = self._selected
        if not (0 <= idx < len(self._entities)):
            self._grp_etype_actions.setVisible(False)
            return
        self._grp_etype_actions.setVisible(True)
        tid = str(self._entities[idx].get("type_id", "") or "")
        if tid:
            t = next((x for x in self._project_entity_types if isinstance(x, dict) and x.get("id") == tid), None)
            label = t.get("name", tid) if t else tid
            self._lbl_etype_current.setText(tr("level.etype_based_on", name=label))
        else:
            self._lbl_etype_current.setText("")

    def _on_add_from_template(self) -> None:
        """Add a sprite to the scene from a saved entity template, then auto-fill behavior."""
        if self._project_data_root is None or self._scene is None:
            return
        from core.entity_templates import get_entity_templates as _get_tpls, apply_template_to_scene_sprite as _apply_spr
        tpls = [t for t in _get_tpls(self._project_data_root) if isinstance(t, dict) and t.get("file")]
        if not tpls:
            QMessageBox.information(
                self,
                tr("level.add_from_template"),
                tr("level.no_templates_with_sprite"),
            )
            return

        items = [
            f"{t.get('name', '?')}  [{Path(t.get('file', '')).name}]"
            for t in tpls
        ]
        choice, ok = QInputDialog.getItem(
            self,
            tr("level.add_from_template"),
            tr("level.add_from_template_prompt"),
            items, 0, False,
        )
        if not ok:
            return

        chosen_idx = items.index(choice)
        tpl = tpls[chosen_idx]
        file_rel = tpl.get("file", "")

        # Check if sprite is already in the scene
        scene_sprites = self._scene.setdefault("sprites", [])
        existing_spr = next(
            (s for s in scene_sprites if s.get("file") == file_rel),
            None,
        )
        if existing_spr is None:
            # Auto-import: create a new sprite entry from the template snapshot
            import copy as _copy
            from core.entity_templates import TEMPLATE_SPRITE_KEYS as _SPR_KEYS
            new_spr = {k: _copy.deepcopy(tpl[k]) for k in _SPR_KEYS if k in tpl}
            # Compute frame_count from image if possible
            scene_sprites.append(new_spr)
            if self._on_save:
                self._on_save()
            # Refresh type list so the new sprite appears
            self.set_scene(self._scene, self._base_dir, self._project_data_root)
            QMessageBox.information(
                self,
                tr("level.add_from_template"),
                tr("level.template_sprite_added", name=Path(file_rel).name),
            )
        else:
            QMessageBox.information(
                self,
                tr("level.add_from_template"),
                tr("level.template_sprite_exists", name=Path(file_rel).name),
            )

    def _refresh_ent_path_combo(self) -> None:
        """Rebuild the patrol-path combo from current self._paths (preserves selection)."""
        ent_path_id = ""
        idx = self._selected
        if 0 <= idx < len(self._entities):
            ent_path_id = str(self._entities[idx].get("path_id", "") or "")
        self._combo_ent_path.blockSignals(True)
        self._combo_ent_path.clear()
        self._combo_ent_path.addItem(tr("level.prop_path_none"))
        for p in self._paths:
            nm = str(p.get("name", "") or p.get("id", "?"))
            self._combo_ent_path.addItem(nm)
        # Restore selection
        sel = 0
        for i, p in enumerate(self._paths):
            if str(p.get("id", "")) == ent_path_id:
                sel = i + 1
                break
        self._combo_ent_path.setCurrentIndex(sel)
        self._combo_ent_path.blockSignals(False)
        self._refresh_ent_path_status()
        self._refresh_path_assignment_ui()

    def _format_entity_ref(self, idx: int, ent: dict) -> str:
        return f"{ent.get('type', '?')}#{idx} @ ({int(ent.get('x', 0))},{int(ent.get('y', 0))})"

    def _entities_for_path_id(self, path_id: str) -> list[tuple[int, dict]]:
        out: list[tuple[int, dict]] = []
        if not path_id:
            return out
        for i, ent in enumerate(self._entities):
            if str(ent.get("path_id", "") or "") == path_id:
                out.append((i, ent))
        return out

    def _path_px_limits(self) -> tuple[int, int]:
        return (
            max(0, int(self._grid_w * _TILE_PX) - 1),
            max(0, int(self._grid_h * _TILE_PX) - 1),
        )

    def _path_index_for_id(self, path_id: str) -> int:
        pid = str(path_id or "").strip()
        if not pid:
            return -1
        for i, path in enumerate(self._paths):
            if str(path.get("id", "") or "") == pid:
                return i
        return -1

    def _duplicate_path_for_entity(self, ent_idx: int, path_idx: int) -> int:
        src = self._paths[path_idx]
        dup = copy.deepcopy(src)
        dup["id"] = _new_id()
        dup["name"] = self._copy_name(
            str(src.get("name", "") or "path"),
            {str(p.get("name", "") or "") for p in self._paths if isinstance(p, dict)},
            "path",
        )
        self._paths.insert(path_idx + 1, dup)
        self._entities[ent_idx]["path_id"] = str(dup.get("id", ""))
        return path_idx + 1

    def _refresh_ent_path_status(self) -> None:
        if not hasattr(self, "_lbl_ent_path_status"):
            return
        idx = self._selected
        if not (0 <= idx < len(self._entities)):
            self._lbl_ent_path_status.setText(tr("level.prop_path_help_none_sel"))
            return
        if not self._paths:
            self._lbl_ent_path_status.setText(tr("level.prop_path_help_no_paths"))
            return
        pid = str(self._entities[idx].get("path_id", "") or "")
        if not pid:
            self._lbl_ent_path_status.setText(tr("level.prop_path_help_unassigned"))
            return
        path_name = pid
        for p in self._paths:
            if str(p.get("id", "")) == pid:
                path_name = str(p.get("name", "") or p.get("id", "?"))
                break
        self._lbl_ent_path_status.setText(tr("level.prop_path_help_assigned", path=path_name))

    def _edit_selected_entity_path(self) -> None:
        idx = self._selected
        if not (0 <= idx < len(self._entities)):
            return
        ent = self._entities[idx]
        pid = str(ent.get("path_id", "") or "").strip()
        path_idx = self._path_index_for_id(pid)
        changed = False
        if path_idx < 0:
            self._push_undo()
            changed = True
            self._ensure_simple_path_for_entity(ent)
            pid = str(ent.get("path_id", "") or "").strip()
            path_idx = self._path_index_for_id(pid)
        elif len(self._entities_for_path_id(pid)) > 1:
            self._push_undo()
            changed = True
            path_idx = self._duplicate_path_for_entity(idx, path_idx)
        if not (0 <= path_idx < len(self._paths)):
            return
        self._path_selected = path_idx
        pts = self._paths[path_idx].get("points", []) or []
        self._path_point_selected = 0 if pts else -1
        self._refresh_path_list()
        self._refresh_path_props()
        self._refresh_props()
        if hasattr(self, "_right_tabs") and hasattr(self, "_tab_paths"):
            self._right_tabs.setCurrentWidget(self._tab_paths)
        self._set_scene_tool("path")
        self._canvas.update()
        if changed:
            self._update_diagnostics()

    def _refresh_path_assignment_ui(self) -> None:
        if not hasattr(self, "_lbl_path_links"):
            return
        has_path = 0 <= self._path_selected < len(self._paths)
        has_ent = 0 <= self._selected < len(self._entities)
        self._btn_path_assign_selected.setEnabled(has_path and has_ent)
        if has_ent:
            target_line = tr(
                "level.path_target_selected",
                entity=self._format_entity_ref(self._selected, self._entities[self._selected]),
            )
        else:
            target_line = tr("level.path_target_none")
        if not has_path:
            self._lbl_path_links.setText(target_line + "<br>" + tr("level.path_links_no_path"))
            return
        path_id = str(self._paths[self._path_selected].get("id", "") or "")
        linked = [self._format_entity_ref(i, ent) for i, ent in self._entities_for_path_id(path_id)]
        links_line = (
            tr("level.path_links_some", entities=", ".join(linked))
            if linked else
            tr("level.path_links_none")
        )
        self._lbl_path_links.setText(target_line + "<br>" + links_line)

    def _assign_selected_path_to_entity(self) -> None:
        if not (0 <= self._selected < len(self._entities)):
            return
        if not (0 <= self._path_selected < len(self._paths)):
            return
        self._entities[self._selected]["path_id"] = str(self._paths[self._path_selected].get("id", ""))
        self._canvas.update()
        self._refresh_props()
        self._refresh_path_list()
        self._refresh_path_props()
        self._update_diagnostics()

    # ------------------------------------------------------------------
    # Properties panel
    # ------------------------------------------------------------------

    def _sprite_meta_for_type(self, type_name: str) -> Optional[dict]:
        if not self._scene:
            return None
        for spr in self._scene.get("sprites", []) or []:
            rel = spr.get("file", "")
            if rel and Path(rel).stem == type_name:
                return spr
        return None

    def _entity_effective_role(self, ent: dict | None) -> str:
        """Return the effective role for an entity dict: per-instance override if
        set, else the sprite-type role. Used anywhere UI decisions (canvas badge,
        behavior/AI gating) must respect the override chosen in the right panel."""
        if not isinstance(ent, dict):
            return "prop"
        ov = str(ent.get("role") or "").strip().lower()
        from core.entity_roles import ROLE_VALUES as _RV
        if ov in _RV:
            return ov
        return self._entity_role_for_type(str(ent.get("type", "") or ""))

    def _entity_role_for_type(self, type_name: str) -> str:
        if self._scene is not None:
            return scene_role_map(self._scene).get(type_name, "prop")
        return str((self._entity_roles or {}).get(type_name, "prop") or "prop").strip().lower()

    def _ctrl_bindings_summary(self, spr: dict) -> str:
        ctrl = dict((spr or {}).get("ctrl") or {})
        role = str(ctrl.get("role", "none") or "none").strip().lower()
        if role != "player":
            return tr("level.player_ctrl_summary_none")
        labels = [
            ("left", "L"),
            ("right", "R"),
            ("up", "U"),
            ("down", "D"),
            ("jump", "J"),
            ("action", "A"),
        ]
        parts: list[str] = []
        for key, short in labels:
            val = str(ctrl.get(key) or "-")
            parts.append(f"{short}={val}")
        return ", ".join(parts)

    def _refresh_props(self) -> None:
        idx = self._selected
        if 0 <= idx < len(self._entities):
            ent = self._entities[idx]
            type_role = self._entity_role_for_type(ent["type"])
            override = entity_override_role(ent)
            eff_role = override or type_role
            self._updating_props = True
            if override:
                role_html = (
                    f"<small>{tr('level.ent_role_line_override', role=eff_role, base=type_role)}</small>"
                )
            else:
                role_html = f"<small>{tr('level.ent_role_line', role=eff_role)}</small>"
            self._lbl_ent_type.setText(
                f"<b>{ent['type']}</b><br><small>{_type_to_c_const(ent['type'])}</small><br>{role_html}")
            # Sync the override combo. Item 0 = default (no override); others map 1:1 to _ROLES.
            target_idx = 0
            if override:
                try:
                    target_idx = 1 + list(_ROLES).index(override)
                except ValueError:
                    target_idx = 0
            if self._combo_ent_role.currentIndex() != target_idx:
                self._combo_ent_role.blockSignals(True)
                self._combo_ent_role.setCurrentIndex(target_idx)
                self._combo_ent_role.blockSignals(False)
            self._spin_x.setValue(ent.get("x", 0))
            self._spin_y.setValue(ent.get("y", 0))
            self._spin_data.setValue(ent.get("data", 0))
            self._combo_ent_dir.setCurrentIndex(int(ent.get("direction", 0)))
            self._combo_ent_behavior.setCurrentIndex(int(ent.get("behavior", 0)))
            self._spin_ai_speed.setValue(max(1, min(255, int(ent.get("ai_speed", 1) or 1))))
            self._spin_ai_range.setValue(max(0, min(255, int(ent.get("ai_range", 10) or 10))))
            self._spin_ai_lose_range.setValue(max(0, min(255, int(ent.get("ai_lose_range", 16) or 16))))
            self._spin_ai_change_every.setValue(max(1, min(255, int(ent.get("ai_change_every", 60) or 60))))
            # Patrol path combo
            pid = str(ent.get("path_id", "") or "")
            self._combo_ent_path.setCurrentIndex(0)
            for i, p in enumerate(self._paths):
                if str(p.get("id", "")) == pid:
                    self._combo_ent_path.setCurrentIndex(i + 1)
                    break
            self._chk_ent_clamp_map.setChecked(bool(int(ent.get("flags", 0) or 0) & _ENT_FLAG_CLAMP_MAP))
            self._chk_ent_clamp_camera.setChecked(bool(int(ent.get("flags", 0) or 0) & _ENT_FLAG_CLAMP_CAMERA))
            self._chk_ent_allow_ledge_fall.setChecked(
                bool(int(ent.get("flags", 0) or 0) & _ENT_FLAG_ALLOW_LEDGE_FALL)
            )
            self._chk_ent_respawn.setChecked(bool(ent.get("respawn", False)))
            self._updating_props = False
            self._set_props_enabled(True)
            self._refresh_ent_path_status()
            self._refresh_path_assignment_ui()
            self._refresh_sprite_info(ent["type"])
            self._refresh_entity_runtime_ui()
        else:
            self._lbl_ent_type.setText(tr("level.no_entity"))
            self._set_props_enabled(False)
            self._refresh_ent_path_status()
            self._refresh_path_assignment_ui()
            self._lbl_hitbox.setText("")
            self._lbl_props.setText("")
            self._lbl_ent_runtime.setText("")
            self._lbl_ent_preset.setVisible(False)
            self._combo_ent_preset.setVisible(False)

    def _refresh_sprite_info(self, type_name: str) -> None:
        spr = self._sprite_meta_for_type(type_name)
        if spr is None:
            self._lbl_hitbox.setText(tr("level.sprite_no_meta"))
            self._lbl_props.setText("")
            return
        hb = first_hurtbox(spr, int(spr.get("frame_w", 8) or 8), int(spr.get("frame_h", 8) or 8))
        self._lbl_hitbox.setText(
            tr("level.sprite_hitbox",
               x=hb.get("x", 0), y=hb.get("y", 0),
               w=hb.get("w", 0), h=hb.get("h", 0)))
        props = spr.get("props") or {}
        if props:
            _PL = {"hp": "HP", "damage": "Dmg", "max_speed": "Vmax",
                   "weight": "Pds", "friction": "Frict", "jump_force": "Saut",
                   "inv_frames": "i-frm", "score": "Score",
                   "anim_spd": "Anim", "type_id": "TypeID"}
            self._lbl_props.setText(
                "  ".join(f"{_PL.get(k, k)}={v}" for k, v in props.items()))
        else:
            self._lbl_props.setText(tr("level.sprite_no_props"))

    def _refresh_entity_runtime_ui(self) -> None:
        if not hasattr(self, "_lbl_ent_runtime"):
            return
        idx = self._selected
        if not (0 <= idx < len(self._entities)):
            self._lbl_ent_runtime.setText("")
            self._lbl_ent_preset.setVisible(False)
            self._combo_ent_preset.setVisible(False)
            self._combo_ent_behavior.setToolTip(tr("level.prop_behavior_tt"))
            self._spin_data.setToolTip(tr("level.prop_data_tt"))
            if hasattr(self, "_chk_ent_allow_ledge_fall"):
                self._chk_ent_allow_ledge_fall.setToolTip(tr("level.prop_allow_ledge_fall_tt"))
            if hasattr(self, "_grp_ai_params"):
                self._grp_ai_params.setVisible(False)
            if hasattr(self, "_grp_shooting"):
                self._grp_shooting.setVisible(False)
            return

        ent = self._entities[idx]
        # Use the effective role so enemy-specific widgets (behavior/AI/shooting)
        # light up when an entity is overridden to role=enemy even if its sprite
        # type declares a different role.
        role = self._entity_effective_role(ent)
        spr = self._sprite_meta_for_type(str(ent.get("type", ""))) or {}
        props = spr.get("props") or {}
        data = int(ent.get("data", 0) or 0)
        behavior = int(ent.get("behavior", 0) or 0)
        clamp_map = bool(int(ent.get("flags", 0) or 0) & _ENT_FLAG_CLAMP_MAP)
        can_fall_ledge = bool(int(ent.get("flags", 0) or 0) & _ENT_FLAG_ALLOW_LEDGE_FALL)

        self._combo_ent_behavior.setEnabled(role == "enemy")
        self._combo_ent_behavior.setToolTip(
            tr("level.prop_behavior_tt") if role == "enemy"
            else tr("level.prop_behavior_unused_tt")
        )
        if hasattr(self, "_chk_ent_allow_ledge_fall"):
            self._chk_ent_allow_ledge_fall.setToolTip(tr("level.prop_allow_ledge_fall_tt"))

        # ---- AI params group visibility ----
        if role == "enemy" and behavior != 2:  # 2=fixed → no movement params
            self._grp_ai_params.setVisible(True)
            self._spin_ai_speed.setVisible(True)
            self._row_ai_range.setVisible(behavior == 1)       # chase only
            self._row_ai_change.setVisible(behavior == 3)      # random only
        else:
            self._grp_ai_params.setVisible(False)

        # ---- Shooting group visibility + population ----
        self._refresh_shooting_ui(role, spr)

        preset_items: list[tuple[str, object]] = []
        runtime_text = tr("level.ent_runtime_generic")
        data_tip = tr("level.prop_data_tt")
        path_id = str(ent.get("path_id", "") or "")

        if role == "player":
            ctrl = spr.get("ctrl") or {}
            runtime_text = tr(
                "level.ent_runtime_player",
                ctrl=str(ctrl.get("role", "none") or "none"),
                bindings=self._ctrl_bindings_summary(spr),
                move=int(props.get("move_type", 0) or 0),
                gravity=int(props.get("gravity", 0) or 0),
                jump=int(props.get("jump_force", 0) or 0),
                clamp=tr("level.runtime_yes") if clamp_map else tr("level.runtime_no"),
            )
        elif role == "enemy":
            preset_items = [
                (tr("level.prop_preset_custom"), ""),
                (tr("level.enemy_preset_patrol_left"), "enemy:patrol_left"),
                (tr("level.enemy_preset_patrol_right"), "enemy:patrol_right"),
                (tr("level.enemy_preset_chase"), "enemy:chase"),
                (tr("level.enemy_preset_fixed"), "enemy:fixed"),
                (tr("level.enemy_preset_random"), "enemy:random"),
            ]
            runtime_text = tr(
                "level.ent_runtime_enemy",
                behavior=tr(("level.beh_patrol", "level.beh_chase", "level.beh_fixed", "level.beh_random")[max(0, min(3, behavior))]),
                direction=tr(("level.dir_right", "level.dir_left", "level.dir_up", "level.dir_down")[max(0, min(3, int(ent.get("direction", 0) or 0)))]),
                gravity=int(props.get("gravity", 0) or 0),
                damage=int(props.get("damage", 0) or 0),
            )
            if can_fall_ledge:
                runtime_text += " " + tr("level.ent_runtime_can_fall_ledge")
        elif role == "item":
            preset_items = [
                (tr("level.prop_preset_custom"), ""),
                (tr("level.item_preset_collect_1"), "item:0"),
                (tr("level.item_preset_collect_2"), "item:2"),
                (tr("level.item_preset_collect_5"), "item:5"),
                (tr("level.item_preset_collect_10"), "item:10"),
            ]
            runtime_text = tr(
                "level.ent_runtime_item",
                score=int(props.get("score", 0) or 0) * 10,
                heal=int(props.get("hp", 0) or 0),
                mult=max(1, data if data > 0 else 1),
            )
            data_tip = tr("level.prop_data_item_tt")
        elif role == "block":
            preset_items = [
                (tr("level.prop_preset_custom"), ""),
                (tr("level.block_preset_bump"), "block:0"),
                (tr("level.block_preset_breakable"), "block:1"),
                (tr("level.block_preset_item_once"), "block:2"),
            ]
            runtime_text = tr(
                "level.ent_runtime_block",
                mode=tr({
                    0: "level.block_mode_bump",
                    1: "level.block_mode_breakable",
                    2: "level.block_mode_item_once",
                }.get(data, "level.block_mode_custom")),
                data=data,
            )
            data_tip = tr("level.prop_data_block_tt")
        elif role == "platform":
            preset_items = [
                (tr("level.prop_preset_custom"), ""),
                (tr("level.platform_preset_static"), "platform:static"),
                (tr("level.platform_preset_moving"), "platform:moving"),
            ]
            runtime_text = tr(
                "level.ent_runtime_platform",
                moving=tr("level.yes") if path_id else tr("level.no"),
                path=path_id or tr("level.prop_path_none"),
            )
            data_tip = tr("level.prop_data_platform_tt")
        elif role == "npc":
            runtime_text = tr("level.ent_runtime_npc")
        elif role == "trigger":
            runtime_text = tr("level.ent_runtime_trigger")

        self._lbl_ent_runtime.setText(runtime_text)
        self._spin_data.setToolTip(data_tip)

        show_preset = bool(preset_items)
        self._lbl_ent_preset.setVisible(show_preset)
        self._combo_ent_preset.setVisible(show_preset)
        if show_preset:
            self._combo_ent_preset.blockSignals(True)
            self._combo_ent_preset.clear()
            for label, val in preset_items:
                self._combo_ent_preset.addItem(label, val)
            preset_val: object = ""
            if role == "block" and any(val == f"block:{data}" for _label, val in preset_items):
                preset_val = f"block:{data}"
            elif role == "enemy":
                if behavior == 0:
                    preset_val = "enemy:patrol_left" if int(ent.get("direction", 0) or 0) == 1 else "enemy:patrol_right"
                elif behavior == 1:
                    preset_val = "enemy:chase"
                elif behavior == 2:
                    preset_val = "enemy:fixed"
                elif behavior == 3:
                    preset_val = "enemy:random"
            elif role == "item" and any(val == f"item:{data}" for _label, val in preset_items):
                preset_val = f"item:{data}"
            elif role == "platform":
                preset_val = "platform:moving" if path_id else "platform:static"
            idx_p = self._combo_ent_preset.findData(preset_val)
            self._combo_ent_preset.setCurrentIndex(max(0, idx_p))
            self._combo_ent_preset.blockSignals(False)

        # Refresh the entity type preset group
        if hasattr(self, "_grp_etype_actions"):
            self._refresh_etype_label()

    # ------------------------------------------------------------------
    # Shooting UI helpers
    # ------------------------------------------------------------------

    def _refresh_bullet_sprite_combo(self) -> None:
        """Populate _combo_bullet_sprite with all sprite names in the current scene."""
        cb = self._combo_bullet_sprite
        cb.blockSignals(True)
        cb.clear()
        cb.addItem(tr("level.shoot_no_sprite"), "")
        if self._scene:
            for spr in (self._scene.get("sprites") or []):
                rel = str(spr.get("file") or "")
                name = Path(rel).stem if rel else str(spr.get("name") or "")
                if name:
                    cb.addItem(name, name)
        cb.blockSignals(False)

    def _refresh_shooting_ui(self, role: str, spr: dict) -> None:
        """Show/hide and populate the shooting group based on role."""
        if role not in ("player", "enemy"):
            self._grp_shooting.setVisible(False)
            return

        shooting = dict(spr.get("shooting") or {})
        self._grp_shooting.setVisible(True)
        self._updating_props = True

        # Role-specific widgets
        is_player = role == "player"
        self._row_shoot_button.setVisible(is_player)
        self._chk_can_shoot.setVisible(not is_player)
        self._row_fire_condition.setVisible(not is_player)
        self._row_fire_range.setVisible(False)

        # Populate bullet sprite combo
        self._refresh_bullet_sprite_combo()
        bullet_sprite = str(shooting.get("bullet_sprite") or "")
        idx_bs = self._combo_bullet_sprite.findData(bullet_sprite)
        self._combo_bullet_sprite.setCurrentIndex(max(0, idx_bs))

        speed_x_default = 4 if is_player else -2
        self._spin_bullet_speed_x.setValue(int(shooting.get("speed_x", speed_x_default) or speed_x_default))
        self._spin_bullet_speed_y.setValue(int(shooting.get("speed_y", 0) or 0))
        fire_rate_default = 10 if is_player else 40
        self._spin_bullet_fire_rate.setValue(int(shooting.get("fire_rate", fire_rate_default) or fire_rate_default))

        if is_player:
            btn = str(shooting.get("button", "none") or "none")
            idx_btn = self._combo_shoot_button.findData(btn)
            self._combo_shoot_button.setCurrentIndex(max(0, idx_btn))
            active = btn not in ("none", "")
            self._row_shoot_params.setVisible(active)
        else:
            can_shoot = bool(shooting.get("can_shoot", False))
            self._chk_can_shoot.setChecked(can_shoot)
            self._row_shoot_params.setVisible(can_shoot)
            cond = int(shooting.get("fire_condition", 0) or 0)
            idx_cond = self._combo_fire_condition.findData(cond)
            self._combo_fire_condition.setCurrentIndex(max(0, idx_cond))
            self._row_fire_range.setVisible(cond == 1)
            self._spin_fire_range.setValue(int(shooting.get("fire_range", 0) or 0))

        self._updating_props = False

    def _shooting_spr(self) -> Optional[dict]:
        """Return the sprite dict for the currently selected entity, or None."""
        idx = self._selected
        if not (0 <= idx < len(self._entities)):
            return None
        return self._sprite_meta_for_type(str(self._entities[idx].get("type", "")))

    def _write_shooting(self, key: str, value: object) -> None:
        """Write a key into spr['shooting'] for the current entity's sprite type."""
        spr = self._shooting_spr()
        if spr is None or self._updating_props:
            return
        if "shooting" not in spr or not isinstance(spr.get("shooting"), dict):
            spr["shooting"] = {}
        spr["shooting"][key] = value
        self._update_diagnostics()

    def _on_shoot_button_changed(self, _idx: int) -> None:
        if self._updating_props:
            return
        btn = self._combo_shoot_button.currentData() or "none"
        self._write_shooting("button", btn)
        self._row_shoot_params.setVisible(btn not in ("none", ""))

    def _on_can_shoot_toggled(self, checked: bool) -> None:
        if self._updating_props:
            return
        self._write_shooting("can_shoot", checked)
        self._row_shoot_params.setVisible(checked)

    def _on_shoot_param_changed(self, attr: str, value: int) -> None:
        self._write_shooting(attr, value)

    def _on_fire_condition_changed(self, _idx: int) -> None:
        if self._updating_props:
            return
        cond = self._combo_fire_condition.currentData() or 0
        self._write_shooting("fire_condition", cond)
        self._row_fire_range.setVisible(cond == 1)

    def _on_bullet_sprite_changed(self, _idx: int) -> None:
        if self._updating_props:
            return
        name = self._combo_bullet_sprite.currentData() or ""
        self._write_shooting("bullet_sprite", name)

    def _on_ent_preset_changed(self, combo_idx: int) -> None:
        if self._updating_props:
            return
        idx = self._selected
        if not (0 <= idx < len(self._entities)):
            return
        role = self._entity_effective_role(self._entities[idx])
        raw = self._combo_ent_preset.itemData(combo_idx)
        if raw in (None, ""):
            return
        self._updating_props = True
        if role == "enemy" and isinstance(raw, str):
            if raw == "enemy:patrol_left":
                self._entities[idx]["behavior"] = 0
                self._entities[idx]["direction"] = 1
                self._combo_ent_behavior.setCurrentIndex(0)
                self._combo_ent_dir.setCurrentIndex(1)
            elif raw == "enemy:patrol_right":
                self._entities[idx]["behavior"] = 0
                self._entities[idx]["direction"] = 0
                self._combo_ent_behavior.setCurrentIndex(0)
                self._combo_ent_dir.setCurrentIndex(0)
            elif raw == "enemy:chase":
                self._entities[idx]["behavior"] = 1
                self._combo_ent_behavior.setCurrentIndex(1)
            elif raw == "enemy:fixed":
                self._entities[idx]["behavior"] = 2
                self._combo_ent_behavior.setCurrentIndex(2)
            elif raw == "enemy:random":
                self._entities[idx]["behavior"] = 3
                self._combo_ent_behavior.setCurrentIndex(3)
        elif role == "block" and isinstance(raw, str) and raw.startswith("block:"):
            value = int(raw.split(":", 1)[1] or 0)
            self._entities[idx]["data"] = value
            self._spin_data.setValue(value)
        elif role == "item" and isinstance(raw, str) and raw.startswith("item:"):
            value = int(raw.split(":", 1)[1] or 0)
            self._entities[idx]["data"] = value
            self._spin_data.setValue(value)
        elif role == "platform" and isinstance(raw, str):
            if raw == "platform:static":
                self._entities[idx].pop("path_id", None)
                self._combo_ent_path.setCurrentIndex(0)
            elif raw == "platform:moving":
                path_id = str(self._entities[idx].get("path_id", "") or "")
                if not path_id:
                    self._ensure_simple_path_for_entity(self._entities[idx])
                    path_id = str(self._entities[idx].get("path_id", "") or "")
                path_idx = self._path_index_for_id(path_id)
                self._combo_ent_path.setCurrentIndex(path_idx + 1 if path_idx >= 0 else 0)
        self._updating_props = False
        self._refresh_entity_runtime_ui()
        self._refresh_ent_path_status()
        self._refresh_path_list()
        self._refresh_path_props()
        self._canvas.update()
        self._update_diagnostics()

    def _set_props_enabled(self, enabled: bool) -> None:
        self._spin_x.setEnabled(enabled)
        self._spin_y.setEnabled(enabled)
        self._spin_data.setEnabled(enabled)
        self._btn_delete.setEnabled(enabled)
        self._combo_ent_role.setEnabled(enabled)
        self._combo_ent_dir.setEnabled(enabled)
        self._combo_ent_behavior.setEnabled(enabled)
        self._combo_ent_path.setEnabled(enabled)
        self._btn_ent_path_edit.setEnabled(enabled)
        self._combo_ent_preset.setEnabled(enabled)
        self._chk_ent_clamp_map.setEnabled(enabled)
        self._chk_ent_clamp_camera.setEnabled(enabled)
        self._chk_ent_allow_ledge_fall.setEnabled(enabled)
        if hasattr(self, "_grp_ai_params"):
            self._grp_ai_params.setEnabled(enabled)
        if hasattr(self, "_grp_shooting"):
            self._grp_shooting.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Wave system
    # ------------------------------------------------------------------

    def _refresh_wave_list(self) -> None:
        self._wave_list.blockSignals(True)
        self._wave_list.clear()
        for wi, wave in enumerate(self._waves):
            delay  = wave.get("delay", 0)
            n_ents = len(wave.get("entities", []))
            col    = _wave_color(wi)
            item   = QListWidgetItem(f"Vague {wi}  ({delay}f)  [{n_ents} ent.]")
            item.setForeground(col)
            self._wave_list.addItem(item)
        if 0 <= self._wave_selected < self._wave_list.count():
            self._wave_list.setCurrentRow(self._wave_selected)
        self._wave_list.blockSignals(False)
        self._btn_wave_del.setEnabled(len(self._waves) > 0 and self._wave_selected >= 0)
        self._btn_wave_edit.setEnabled(len(self._waves) > 0 and self._wave_selected >= 0)
        self._refresh_wave_entities()
        self._sync_scene_tool_buttons()

    def _refresh_wave_entities(self) -> None:
        self._wave_ent_list.clear()
        if 0 <= self._wave_selected < len(self._waves):
            wave_ents = self._waves[self._wave_selected].get("entities", [])
            for ent in wave_ents:
                if not isinstance(ent, dict) or "type" not in ent:
                    continue
                self._wave_ent_list.addItem(
                    f"{ent['type']} @ ({ent.get('x', '?')},{ent.get('y', '?')})")
            self._btn_wave_ent_del.setEnabled(len(wave_ents) > 0)
        else:
            self._btn_wave_ent_del.setEnabled(False)

    def refresh_wave_entity_props(self) -> None:
        """Refresh the wave-entity side panel while preserving current selection."""
        self._refresh_wave_entities()
        if 0 <= self._wave_entity_sel < self._wave_ent_list.count():
            self._wave_ent_list.setCurrentRow(self._wave_entity_sel)

    # Expose for _LevelCanvas
    def _refresh_wave_entity_props(self) -> None:
        self.refresh_wave_entity_props()

    def _add_wave(self) -> None:
        self._push_undo()
        self._waves.append({"delay": 0, "entities": []})
        self._wave_selected = len(self._waves) - 1
        self._refresh_wave_list()
        self._spin_wave_delay.setEnabled(True)
        self._spin_wave_delay.blockSignals(True)
        self._spin_wave_delay.setValue(0)
        self._spin_wave_delay.blockSignals(False)
        self._canvas.update()
        self._update_budget()

    def _remove_wave(self) -> None:
        if not (0 <= self._wave_selected < len(self._waves)):
            return
        self._push_undo()
        del self._waves[self._wave_selected]
        self._wave_selected = max(-1, min(self._wave_selected, len(self._waves) - 1))
        if self._wave_edit and len(self._waves) == 0:
            self._wave_edit = False
            self._btn_wave_edit.setChecked(False)
            self._btn_wave_edit.setText(tr("level.wave_edit_off"))
        self._refresh_wave_list()
        self._canvas.update()
        self._update_budget()

    def _dup_wave(self) -> None:
        if not (0 <= self._wave_selected < len(self._waves)):
            return
        self._push_undo()
        new_wave = copy.deepcopy(self._waves[self._wave_selected])
        self._waves.insert(self._wave_selected + 1, new_wave)
        self._wave_selected += 1
        self._refresh_wave_list()
        self._canvas.update()
        self._update_budget()

    def _on_wave_selected(self, row: int) -> None:
        self._wave_selected   = row
        self._wave_entity_sel = -1
        if 0 <= row < len(self._waves):
            delay = self._waves[row].get("delay", 0)
            self._spin_wave_delay.blockSignals(True)
            self._spin_wave_delay.setValue(delay)
            self._spin_wave_delay.blockSignals(False)
            self._spin_wave_delay.setEnabled(True)
            self._btn_wave_edit.setEnabled(True)
            self._lbl_wave_spawn_x.setText(f"→ spawn X suggéré : {self._wave_spawn_x(delay)} tuiles")
        else:
            self._spin_wave_delay.setEnabled(False)
            self._btn_wave_edit.setEnabled(False)
            self._lbl_wave_spawn_x.setText("")
        self._btn_wave_del.setEnabled(row >= 0 and len(self._waves) > 0)
        self._refresh_wave_entities()
        self._refresh_wave_ent_rand_panel()
        self._canvas.update()

    def _wave_spawn_x(self, delay: int) -> int:
        """Suggest map tile X so enemy spawns just off the right screen edge."""
        speed_x = max(1, int((self._scene or {}).get("level_scroll", {}).get("speed_x", 1) or 1))
        return int(delay * speed_x // 8) + 21

    def _next_wave_delay(self, step: int = 60) -> int:
        if not self._waves:
            return 0
        return max(0, int(self._waves[-1].get("delay", 0) or 0) + int(step))

    def _suggest_wave_type_name(self) -> str:
        current = str(self._current_type() or "").strip()
        if current:
            return current
        for name in self._type_names:
            if str(self._entity_roles.get(name, "prop")) == "enemy":
                return name
        return str(self._type_names[0] if self._type_names else "").strip()

    def _make_wave_entity(self, type_name: str, x: int, y: int, *, data: int = 0) -> dict:
        return {"type": str(type_name), "x": int(x), "y": int(y), "data": int(data)}

    def _build_wave_preset(self, preset_key: str) -> dict | None:
        type_name = self._suggest_wave_type_name()
        if not type_name:
            QMessageBox.information(self, tr("level.save_title"), tr("level.wave_preset_need_type"))
            return None

        cam_x, cam_y = self._cam_tile
        center_y = max(1, min(int(self._grid_h) - 2, int(cam_y) + (_SCREEN_H // 2)))
        spawn_x = max(0, min(int(self._grid_w) - 1, self._wave_spawn_x(self._next_wave_delay())))
        entities: list[dict] = []
        delay = 0

        if preset_key == "line_3":
            delay = self._next_wave_delay(60)
            for y in (center_y - 3, center_y, center_y + 3):
                _x, _y = self._clamp_tile_xy(spawn_x, y)
                entities.append(self._make_wave_entity(type_name, _x, _y))
        elif preset_key == "vee_5":
            delay = self._next_wave_delay(90)
            offsets = ((0, 0), (2, -2), (2, 2), (4, -4), (4, 4))
            for dx, dy in offsets:
                _x, _y = self._clamp_tile_xy(spawn_x + dx, center_y + dy)
                entities.append(self._make_wave_entity(type_name, _x, _y))
        elif preset_key == "ground_pair":
            delay = self._next_wave_delay(45)
            ground_y = max(0, min(int(self._grid_h) - 1, int(cam_y) + _SCREEN_H - 2))
            base_x = max(0, min(int(self._grid_w) - 1, int(cam_x) + 12))
            for dx in (0, 4):
                _x, _y = self._clamp_tile_xy(base_x + dx, ground_y)
                entities.append(self._make_wave_entity(type_name, _x, _y))
        else:
            return None

        return {"delay": int(delay), "entities": entities}

    def _add_wave_preset(self) -> None:
        preset_key = str(self._combo_wave_preset.currentData() or "").strip()
        if not preset_key:
            return
        wave = self._build_wave_preset(preset_key)
        if wave is None:
            return
        self._push_undo()
        self._waves.append(wave)
        self._wave_selected = len(self._waves) - 1
        self._wave_entity_sel = -1
        self._refresh_wave_list()
        self._on_wave_selected(self._wave_selected)
        self._canvas.update()
        self._update_budget()
        self._update_diagnostics()

    def _on_wave_delay_changed(self, value: int) -> None:
        if 0 <= self._wave_selected < len(self._waves):
            self._waves[self._wave_selected]["delay"] = value
            item = self._wave_list.item(self._wave_selected)
            if item:
                n = len(self._waves[self._wave_selected].get("entities", []))
                item.setText(f"Vague {self._wave_selected}  ({value}f)  [{n} ent.]")
        self._lbl_wave_spawn_x.setText(f"→ spawn X suggéré : {self._wave_spawn_x(value)} tuiles")

    def _on_wave_edit_toggled(self, checked: bool) -> None:
        self._set_scene_tool("wave" if checked else "entity")

    def _on_wave_ent_row_changed(self, row: int) -> None:
        self._wave_entity_sel = row
        self._refresh_wave_ent_rand_panel()
        self._canvas.update()

    # ---- Random-wave per-entity panel ------------------------------------

    def _current_wave_entity(self) -> dict | None:
        if not (0 <= self._wave_selected < len(self._waves)):
            return None
        ents = self._waves[self._wave_selected].get("entities") or []
        if not (0 <= self._wave_entity_sel < len(ents)):
            return None
        e = ents[self._wave_entity_sel]
        return e if isinstance(e, dict) else None

    def _refresh_wave_ent_rand_panel(self) -> None:
        """Repopulate the rand sub-panel from the current wave-entity selection."""
        if not hasattr(self, "_wave_ent_rand_box"):
            return
        ent = self._current_wave_entity()
        enabled = ent is not None
        self._wave_ent_rand_box.setEnabled(enabled)
        self._wave_ent_rand_updating = True
        try:
            if ent is None:
                self._chk_wave_ent_rand.setChecked(False)
                self._wave_ent_rand_fields.setVisible(False)
                return
            is_rand = bool(ent.get("rand", False))
            self._chk_wave_ent_rand.setChecked(is_rand)
            self._wave_ent_rand_fields.setVisible(is_rand)
            if is_rand:
                self._cb_wave_ent_rand_side.setCurrentIndex(
                    max(0, min(3, int(ent.get("spawn_side", 0))))
                )
                self._sb_wave_ent_rand_cmin.setValue(
                    max(1, int(ent.get("count_min", 1)))
                )
                self._sb_wave_ent_rand_cmax.setValue(
                    max(1, int(ent.get("count_max", 3)))
                )
                self._sb_wave_ent_rand_ivl.setValue(
                    max(1, int(ent.get("interval", 30)))
                )
                self._sb_wave_ent_rand_maxw.setValue(
                    max(0, min(65535, int(ent.get("max_waves", 0) or 0)))
                )
                _beh_key = str(ent.get("spawn_behavior", "legacy") or "legacy").strip().lower()
                _beh_idx = self._cb_wave_ent_rand_beh.findData(_beh_key)
                if _beh_idx < 0:
                    _beh_idx = self._cb_wave_ent_rand_beh.findData("legacy")
                self._cb_wave_ent_rand_beh.setCurrentIndex(max(0, _beh_idx))
                self._chk_wave_ent_rand_clamp.setChecked(
                    bool(int(ent.get("spawn_flags", 0) or 0) & 0x01)
                )
                self._chk_wave_ent_rand_no_cull.setChecked(
                    bool(ent.get("spawn_no_cull", False))
                )
        finally:
            self._wave_ent_rand_updating = False

    def _on_wave_ent_rand_toggled(self, checked: bool) -> None:
        if self._wave_ent_rand_updating:
            return
        ent = self._current_wave_entity()
        if ent is None:
            return
        self._push_undo()
        if checked:
            ent["rand"] = True
            ent.setdefault("spawn_side", 0)
            ent.setdefault("count_min", 1)
            ent.setdefault("count_max", 3)
            ent.setdefault("interval", 30)
            ent.setdefault("max_waves", 0)
            ent.setdefault("spawn_behavior", "legacy")
            ent.setdefault("spawn_flags", 1)   # CLAMP_MAP default
        else:
            # Drop rand keys so exports stay clean when the user reverts.
            for k in (
                "rand", "spawn_side", "count_min", "count_max", "interval",
                "max_waves", "spawn_behavior", "spawn_flags", "spawn_no_cull",
            ):
                ent.pop(k, None)
        # Re-read the entity so spinbox defaults populate after a True->False->True
        # toggle cycle; no need to rebuild the wave list (entity count unchanged).
        self._refresh_wave_ent_rand_panel()

    def _on_wave_ent_rand_field_changed(self, *_args) -> None:
        if self._wave_ent_rand_updating:
            return
        ent = self._current_wave_entity()
        if ent is None or not bool(ent.get("rand", False)):
            return
        cmin = int(self._sb_wave_ent_rand_cmin.value())
        cmax = int(self._sb_wave_ent_rand_cmax.value())
        # Keep cmax >= cmin without fighting the user; clamp silently.
        if cmax < cmin:
            cmax = cmin
            self._wave_ent_rand_updating = True
            try:
                self._sb_wave_ent_rand_cmax.setValue(cmax)
            finally:
                self._wave_ent_rand_updating = False
        self._push_undo()
        ent["spawn_side"] = int(self._cb_wave_ent_rand_side.currentIndex())
        ent["count_min"]  = cmin
        ent["count_max"]  = cmax
        ent["interval"]   = int(self._sb_wave_ent_rand_ivl.value())
        ent["max_waves"]  = int(self._sb_wave_ent_rand_maxw.value())
        _beh_key = self._cb_wave_ent_rand_beh.currentData() or "legacy"
        ent["spawn_behavior"] = str(_beh_key)
        _flags = int(ent.get("spawn_flags", 0) or 0)
        if self._chk_wave_ent_rand_clamp.isChecked():
            _flags |= 0x01  # NGPNG_ENT_FLAG_CLAMP_MAP
        else:
            _flags &= ~0x01
        ent["spawn_flags"] = _flags
        if self._chk_wave_ent_rand_no_cull.isChecked():
            ent["spawn_no_cull"] = True
        else:
            ent.pop("spawn_no_cull", None)

    def _delete_wave_entity(self) -> None:
        if not (0 <= self._wave_selected < len(self._waves)):
            return
        wave_ents = self._waves[self._wave_selected]["entities"]
        eidx = self._wave_entity_sel
        if 0 <= eidx < len(wave_ents):
            self._push_undo()
            del wave_ents[eidx]
            self._wave_entity_sel = min(eidx, len(wave_ents) - 1)
            self._refresh_wave_list()
            self._canvas.update()
            self._update_budget()

    # ------------------------------------------------------------------
    # Procgen sub-tab builders
    # ------------------------------------------------------------------

    def _build_procgen_dungeongen_tab(self) -> QWidget:
        """Build and return the DungeonGen runtime configuration sub-tab."""
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(8)

        # ── Master enable ─────────────────────────────────────────────────
        self._chk_dgen_enabled = QCheckBox(
            "Enable DungeonGen runtime generation for this scene")
        self._chk_dgen_enabled.setToolTip(
            "When checked, the Export button writes dungeongen_config.h.\n"
            "Include it BEFORE #include \"ngpc_dungeongen/ngpc_dungeongen.h\" in your code.\n"
            "Uncheck = scene uses static Design Map or another procgen mode.")
        self._chk_dgen_enabled.setStyleSheet("font-weight: bold;")
        v.addWidget(self._chk_dgen_enabled)

        self._dgen_params_widget = QWidget()
        dgen_v = QVBoxLayout(self._dgen_params_widget)
        dgen_v.setContentsMargins(0, 0, 0, 0)
        dgen_v.setSpacing(8)

        def _dgen_toggle(checked: bool) -> None:
            self._dgen_params_widget.setEnabled(checked)

        self._chk_dgen_enabled.toggled.connect(_dgen_toggle)
        self._dgen_params_widget.setEnabled(False)

        v.addWidget(self._dgen_params_widget, 1)
        v = dgen_v  # noqa: F841

        # ── Seed ─────────────────────────────────────────────────────────
        grp_seed = QGroupBox("Seed de génération")
        seed_v = QVBoxLayout(grp_seed)
        seed_v.setSpacing(4)

        seed_row = QHBoxLayout()
        seed_row.addWidget(QLabel("Mode:"))
        self._combo_dgen_seed_mode = QComboBox()
        self._combo_dgen_seed_mode.addItem("RTC (aléatoire à chaque boot)", "rtc")
        self._combo_dgen_seed_mode.addItem("Fixe (valeur saisie)", "fixed")
        self._combo_dgen_seed_mode.setToolTip(
            "RTC : ngpc_dungeongen_set_rtc_seed() — donjon différent à chaque session.\n"
            "Fixe : ngpc_dungeongen_set_seed(N) — même donjon reproductible (debug, partage).")
        seed_row.addWidget(self._combo_dgen_seed_mode)
        seed_row.addWidget(QLabel("Valeur:"))
        self._spin_dgen_seed_value = QSpinBox()
        self._spin_dgen_seed_value.setRange(1, 65535)
        self._spin_dgen_seed_value.setValue(1)
        self._spin_dgen_seed_value.setEnabled(False)
        self._spin_dgen_seed_value.setToolTip("Seed fixe (1–65535) — ignorée si mode RTC.")
        seed_row.addWidget(self._spin_dgen_seed_value)
        seed_row.addStretch()
        seed_v.addLayout(seed_row)

        def _dgen_seed_mode_changed(index: int) -> None:
            self._spin_dgen_seed_value.setEnabled(
                self._combo_dgen_seed_mode.itemData(index) == "fixed")
        self._combo_dgen_seed_mode.currentIndexChanged.connect(_dgen_seed_mode_changed)

        v.addWidget(grp_seed)

        # ── Salle ────────────────────────────────────────────────────────
        grp_room = QGroupBox("Salle (cellules logiques)")
        room_v = QVBoxLayout(grp_room)
        room_v.setSpacing(4)

        wrow = QHBoxLayout()
        wrow.addWidget(QLabel("Largeur min:"))
        self._spin_dgen_mw_min = QSpinBox()
        self._spin_dgen_mw_min.setRange(4, 32)
        self._spin_dgen_mw_min.setValue(10)
        self._spin_dgen_mw_min.setToolTip("DUNGEONGEN_ROOM_MW_MIN — largeur minimale d'une salle en cellules")
        wrow.addWidget(self._spin_dgen_mw_min)
        wrow.addWidget(QLabel("max:"))
        self._spin_dgen_mw_max = QSpinBox()
        self._spin_dgen_mw_max.setRange(4, 32)
        self._spin_dgen_mw_max.setValue(16)
        self._spin_dgen_mw_max.setToolTip("DUNGEONGEN_ROOM_MW_MAX — largeur maximale (≤32, taille tilemap HW)")
        wrow.addWidget(self._spin_dgen_mw_max)
        wrow.addStretch()
        room_v.addLayout(wrow)

        hrow = QHBoxLayout()
        hrow.addWidget(QLabel("Hauteur min:"))
        self._spin_dgen_mh_min = QSpinBox()
        self._spin_dgen_mh_min.setRange(4, 32)
        self._spin_dgen_mh_min.setValue(10)
        self._spin_dgen_mh_min.setToolTip("DUNGEONGEN_ROOM_MH_MIN — hauteur minimale d'une salle en cellules")
        hrow.addWidget(self._spin_dgen_mh_min)
        hrow.addWidget(QLabel("max:"))
        self._spin_dgen_mh_max = QSpinBox()
        self._spin_dgen_mh_max.setRange(4, 32)
        self._spin_dgen_mh_max.setValue(16)
        self._spin_dgen_mh_max.setToolTip("DUNGEONGEN_ROOM_MH_MAX — hauteur maximale (≤32, taille tilemap HW)")
        hrow.addWidget(self._spin_dgen_mh_max)
        hrow.addStretch()
        room_v.addLayout(hrow)

        exit_row = QHBoxLayout()
        exit_row.addWidget(QLabel("Max sorties (0-4):"))
        self._spin_dgen_max_exits = QSpinBox()
        self._spin_dgen_max_exits.setRange(0, 4)
        self._spin_dgen_max_exits.setValue(4)
        self._spin_dgen_max_exits.setToolTip(
            "DUNGEONGEN_MAX_EXITS — nombre de sorties max par salle (N/S/E/W).\n"
            "Détermine le nombre de styles disponibles (0→1, 1→2, 2→5, 3→6, 4→7).")
        exit_row.addWidget(self._spin_dgen_max_exits)
        exit_row.addStretch()
        room_v.addLayout(exit_row)

        cell_row = QHBoxLayout()
        cell_row.addWidget(QLabel("Taille cellule (tiles NGPC):"))
        self._spin_dgen_cell_w = QSpinBox()
        self._spin_dgen_cell_w.setRange(1, 4)
        self._spin_dgen_cell_w.setValue(2)
        self._spin_dgen_cell_w.setReadOnly(True)
        self._spin_dgen_cell_w.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self._spin_dgen_cell_w.setStyleSheet("color: #888;")
        self._spin_dgen_cell_w.setToolTip(
            "Lecture seule — piloté par 'Taille cellule source' dans l'onglet Procgen Assets.\n"
            "DUNGEONGEN_CELL_W_TILES = 1 (8×8), 2 (16×16) ou 4 (32×32).")
        cell_row.addWidget(self._spin_dgen_cell_w)
        cell_row.addWidget(QLabel("x"))
        self._spin_dgen_cell_h = QSpinBox()
        self._spin_dgen_cell_h.setRange(1, 4)
        self._spin_dgen_cell_h.setValue(2)
        self._spin_dgen_cell_h.setReadOnly(True)
        self._spin_dgen_cell_h.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self._spin_dgen_cell_h.setStyleSheet("color: #888;")
        self._spin_dgen_cell_h.setToolTip(
            "Lecture seule — piloté par 'Taille cellule source' dans l'onglet Procgen Assets.\n"
            "DUNGEONGEN_CELL_H_TILES = 1 (8×8), 2 (16×16) ou 4 (32×32).")
        cell_row.addWidget(self._spin_dgen_cell_h)
        cell_row.addWidget(QLabel("tiles  ⬅ réglé dans Procgen Assets"))
        cell_row.addStretch()
        room_v.addLayout(cell_row)

        cell_note = QLabel("Cellule 2x2 = metatile 16x16px  |  Cellule 1x1 = tile 8x8px  |  max salle 16x16 cellules = tilemap HW 32x32")
        cell_note.setStyleSheet("color:#aaa;font-size:10px;")
        cell_note.setWordWrap(True)
        room_v.addWidget(cell_note)
        v.addWidget(grp_room)

        # ── Sol ──────────────────────────────────────────────────────────
        grp_ground = QGroupBox("Sol — mix des 3 variantes (somme = 100%)")
        ground_v = QVBoxLayout(grp_ground)
        ground_v.setSpacing(4)

        g1row = QHBoxLayout()
        g1row.addWidget(QLabel("Variante 1:"))
        self._spin_dgen_gpc1 = QSpinBox()
        self._spin_dgen_gpc1.setRange(0, 100)
        self._spin_dgen_gpc1.setValue(70)
        self._spin_dgen_gpc1.setSuffix("%")
        self._spin_dgen_gpc1.setToolTip("DUNGEONGEN_GROUND_PCT_1 — sol principal (tile variante 1)")
        g1row.addWidget(self._spin_dgen_gpc1)
        g1row.addWidget(QLabel("Variante 2:"))
        self._spin_dgen_gpc2 = QSpinBox()
        self._spin_dgen_gpc2.setRange(0, 100)
        self._spin_dgen_gpc2.setValue(20)
        self._spin_dgen_gpc2.setSuffix("%")
        self._spin_dgen_gpc2.setToolTip("DUNGEONGEN_GROUND_PCT_2 — detail sol (tile variante 2)")
        g1row.addWidget(self._spin_dgen_gpc2)
        g1row.addWidget(QLabel("Variante 3:"))
        self._spin_dgen_gpc3 = QSpinBox()
        self._spin_dgen_gpc3.setRange(0, 100)
        self._spin_dgen_gpc3.setValue(10)
        self._spin_dgen_gpc3.setSuffix("%")
        self._spin_dgen_gpc3.setToolTip("DUNGEONGEN_GROUND_PCT_3 — accent sol (tile variante 3). Auto-ajuste pour sommer a 100.")
        g1row.addWidget(self._spin_dgen_gpc3)
        g1row.addStretch()
        ground_v.addLayout(g1row)

        self._lbl_dgen_ground_sum = QLabel("Somme: 100%")
        self._lbl_dgen_ground_sum.setStyleSheet("color:#aaa;font-size:10px;")
        ground_v.addWidget(self._lbl_dgen_ground_sum)

        def _update_ground_sum() -> None:
            s = self._spin_dgen_gpc1.value() + self._spin_dgen_gpc2.value() + self._spin_dgen_gpc3.value()
            ok = s == 100
            self._lbl_dgen_ground_sum.setText(f"Somme: {s}%  {'OK' if ok else '(PCT_3 sera auto-ajuste a l export)'}")
            self._lbl_dgen_ground_sum.setStyleSheet(
                "color:#5f5;font-size:10px;" if ok else "color:#fa0;font-size:10px;")

        self._spin_dgen_gpc1.valueChanged.connect(lambda _: _update_ground_sum())
        self._spin_dgen_gpc2.valueChanged.connect(lambda _: _update_ground_sum())
        self._spin_dgen_gpc3.valueChanged.connect(lambda _: _update_ground_sum())
        _update_ground_sum()
        v.addWidget(grp_ground)

        # ── Population ───────────────────────────────────────────────────
        grp_pop = QGroupBox("Population — elements visuels")
        pop_v = QVBoxLayout(grp_pop)
        pop_v.setSpacing(4)

        def _freq_row(label: str, default: int, tip: str) -> QSpinBox:
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            spin = QSpinBox()
            spin.setRange(0, 100)
            spin.setValue(default)
            spin.setSuffix("%")
            spin.setToolTip(tip)
            row.addWidget(spin)
            row.addStretch()
            pop_v.addLayout(row)
            return spin

        self._spin_dgen_eau_freq = _freq_row(
            "Eau (bande traversante):", 40,
            "DUNGEONGEN_EAU_FREQ — % de chance d'une bande d'eau. Seulement si <=2 sorties. 0=desactive.")
        self._spin_dgen_vide_freq = _freq_row(
            "Fosse (vide 2x2):", 30,
            "DUNGEONGEN_VIDE_FREQ — % de chance d'une fosse (zone vide 2x2 cellules). 0=desactive.")
        self._spin_dgen_tonneau_freq = _freq_row(
            "Decoration A (prop mural):", 50,
            "DUNGEONGEN_TONNEAU_FREQ — % de chance d'un ou deux props decoratifs contre un mur.\n"
            "Tile : role 'Decoration A' dans l'onglet Procgen Assets. 0=desactive.")
        self._spin_dgen_escalier_freq = QSpinBox()   # cache, compat JSON legacy
        self._spin_dgen_escalier_freq.setRange(0, 100)
        self._spin_dgen_escalier_freq.setValue(0)
        self._spin_dgen_escalier_freq.hide()

        tno_row = QHBoxLayout()
        tno_row.addWidget(QLabel("Max decoration A:"))
        self._spin_dgen_tonneau_max = QSpinBox()
        self._spin_dgen_tonneau_max.setRange(1, 2)
        self._spin_dgen_tonneau_max.setValue(2)
        self._spin_dgen_tonneau_max.setToolTip("DUNGEONGEN_TONNEAU_MAX — 1 ou 2 props decoratifs max par salle.")
        tno_row.addWidget(self._spin_dgen_tonneau_max)
        tno_row.addStretch()
        pop_v.addLayout(tno_row)

        margin_row = QHBoxLayout()
        margin_row.addWidget(QLabel("Marge autour sorties (cellules):"))
        self._spin_dgen_vide_margin = QSpinBox()
        self._spin_dgen_vide_margin.setRange(1, 6)
        self._spin_dgen_vide_margin.setValue(3)
        self._spin_dgen_vide_margin.setToolTip(
            "DUNGEONGEN_VIDE_MARGIN — zone de protection autour des ouvertures de sortie.\n"
            "Une fosse ne sera jamais placee a moins de N cellules d'une sortie.")
        margin_row.addWidget(self._spin_dgen_vide_margin)
        margin_row.addStretch()
        pop_v.addLayout(margin_row)

        v.addWidget(grp_pop)

        # ── Comportements Eau & Trou ──────────────────────────────────────
        grp_behav = QGroupBox("Comportements — Eau & Trou")
        beh_v = QVBoxLayout(grp_behav)
        beh_v.setSpacing(4)

        eau_row = QHBoxLayout()
        eau_row.addWidget(QLabel("Eau :"))
        self._combo_dgen_water_col = QComboBox()
        self._combo_dgen_water_col.addItem("Passable (aucun effet)",        "pass")
        self._combo_dgen_water_col.addItem("Dommages / effet (DGNCOL_WATER)", "water")
        self._combo_dgen_water_col.addItem("Solide (mur infranchissable)",  "solid")
        self._combo_dgen_water_col.addItem("Mort instant",                  "death")
        self._combo_dgen_water_col.setCurrentIndex(1)
        self._combo_dgen_water_col.setToolTip(
            "DUNGEONGEN_WATER_COL — comportement retourné par collision_at() sur une case eau.\n"
            "'Dommages' = DGNCOL_WATER (le game code interprète comme il veut).\n"
            "'Solide' = le pont reste franchissable, mais les cases eau sont des murs.\n"
            "'Mort instant' = DGNCOL_VOID (chute immédiate).")
        self._combo_dgen_water_col.currentIndexChanged.connect(
            lambda: self._store_scene_state(save_project=True, update_status=False))
        eau_row.addWidget(self._combo_dgen_water_col, 1)
        beh_v.addLayout(eau_row)

        void_row = QHBoxLayout()
        void_row.addWidget(QLabel("Trou (fosse) :"))
        self._combo_dgen_void_behavior = QComboBox()
        self._combo_dgen_void_behavior.addItem("Mort instant",              "death")
        self._combo_dgen_void_behavior.addItem("Étage inférieur (multifloor)", "floor")
        self._combo_dgen_void_behavior.addItem("Goto scène →",              "scene")
        self._combo_dgen_void_behavior.setToolTip(
            "DUNGEONGEN_VOID_BEHAVIOR — indique au game code le comportement d'une chute.\n"
            "Dans tous les cas collision_at() retourne DGNCOL_VOID.\n"
            "'Étage inférieur' = utilise le système multifloor (décrémenter floor_var).\n"
            "'Goto scène' = le game code effectue la transition vers DUNGEONGEN_VOID_SCENE_ID.")

        def _void_behavior_changed():
            mode = self._combo_dgen_void_behavior.currentData()
            self._wdg_void_scene_row.setVisible(mode == "scene")
            self._wdg_void_damage_row.setVisible(mode != "death")
            self._store_scene_state(save_project=True, update_status=False)

        self._combo_dgen_void_behavior.currentIndexChanged.connect(_void_behavior_changed)
        void_row.addWidget(self._combo_dgen_void_behavior, 1)
        beh_v.addLayout(void_row)

        dmg_row = QHBoxLayout()
        dmg_row.addWidget(QLabel("  Dommages chute :"))
        self._spin_dgen_void_damage = QSpinBox()
        self._spin_dgen_void_damage.setRange(0, 255)
        self._spin_dgen_void_damage.setValue(0)
        self._spin_dgen_void_damage.setToolTip(
            "DUNGEONGEN_VOID_DAMAGE — dommages infligés lors de la chute (0 = aucun).\n"
            "Interprété par le game code.")
        self._spin_dgen_void_damage.valueChanged.connect(
            lambda: self._store_scene_state(save_project=True, update_status=False))
        dmg_row.addWidget(self._spin_dgen_void_damage)
        dmg_row.addStretch()
        self._wdg_void_damage_row = QWidget()
        self._wdg_void_damage_row.setLayout(dmg_row)
        self._wdg_void_damage_row.setVisible(False)
        beh_v.addWidget(self._wdg_void_damage_row)

        vs_row = QHBoxLayout()
        vs_row.addWidget(QLabel("  Scène cible :"))
        self._combo_dgen_void_scene = QComboBox()
        self._combo_dgen_void_scene.addItem("(aucune)", "")
        self._combo_dgen_void_scene.setToolTip(
            "DUNGEONGEN_VOID_SCENE_ID — scène vers laquelle transiter lors d'une chute.")
        self._combo_dgen_void_scene.currentIndexChanged.connect(
            lambda: self._store_scene_state(save_project=True, update_status=False))
        vs_row.addWidget(self._combo_dgen_void_scene, 1)
        self._wdg_void_scene_row = QWidget()
        self._wdg_void_scene_row.setLayout(vs_row)
        self._wdg_void_scene_row.setVisible(False)
        beh_v.addWidget(self._wdg_void_scene_row)

        v.addWidget(grp_behav)

        # ── Entites ──────────────────────────────────────────────────────
        grp_ent = QGroupBox("Entites — ennemis + item (sprites GFX_SPR)")
        ent_v = QVBoxLayout(grp_ent)
        ent_v.setSpacing(4)

        en_row = QHBoxLayout()
        en_row.addWidget(QLabel("Ennemis min:"))
        self._spin_dgen_enemy_min = QSpinBox()
        self._spin_dgen_enemy_min.setRange(0, 8)
        self._spin_dgen_enemy_min.setValue(0)
        self._spin_dgen_enemy_min.setToolTip("DUNGEONGEN_ENEMY_MIN — nombre minimum d'ennemis par salle.")
        en_row.addWidget(self._spin_dgen_enemy_min)
        en_row.addWidget(QLabel("max:"))
        self._spin_dgen_enemy_max = QSpinBox()
        self._spin_dgen_enemy_max.setRange(0, 8)
        self._spin_dgen_enemy_max.setValue(3)
        self._spin_dgen_enemy_max.setToolTip(
            "DUNGEONGEN_ENEMY_MAX — plafond absolu d'ennemis. Le cap reel est auto-calcule\n"
            "selon la surface interieure / ENEMY_DENSITY, borne par [min, max].")
        en_row.addWidget(self._spin_dgen_enemy_max)
        en_row.addStretch()
        ent_v.addLayout(en_row)

        dens_row = QHBoxLayout()
        dens_row.addWidget(QLabel("Densite (cellules/ennemi):"))
        self._spin_dgen_enemy_density = QSpinBox()
        self._spin_dgen_enemy_density.setRange(4, 64)
        self._spin_dgen_enemy_density.setValue(16)
        self._spin_dgen_enemy_density.setToolTip(
            "DUNGEONGEN_ENEMY_DENSITY — surface interieure (cellules) par ennemi autorise.\n"
            "Petite valeur = plus d'ennemis dans les grandes salles. 16 = 1 ennemi / 16 cellules.")
        dens_row.addWidget(self._spin_dgen_enemy_density)
        dens_row.addStretch()
        ent_v.addLayout(dens_row)

        ene2_row = QHBoxLayout()
        ene2_row.addWidget(QLabel("% petit ennemi (ENE2 8x8):"))
        self._spin_dgen_ene2_pct = QSpinBox()
        self._spin_dgen_ene2_pct.setRange(0, 100)
        self._spin_dgen_ene2_pct.setValue(50)
        self._spin_dgen_ene2_pct.setSuffix("%")
        self._spin_dgen_ene2_pct.setToolTip(
            "DUNGEONGEN_ENE2_PCT — % de chance qu'un ennemi soit ENE2 (8x8, 1 sprite slot).\n"
            "Le reste sera ENE1 (16x16, 4 sprite slots).\n"
            "0% = tous ENE1.  100% = tous ENE2.")
        ene2_row.addWidget(self._spin_dgen_ene2_pct)
        ene2_row.addStretch()
        ent_v.addLayout(ene2_row)

        item_row = QHBoxLayout()
        item_row.addWidget(QLabel("Item par salle:"))
        self._spin_dgen_item_freq = QSpinBox()
        self._spin_dgen_item_freq.setRange(0, 100)
        self._spin_dgen_item_freq.setValue(50)
        self._spin_dgen_item_freq.setSuffix("%")
        self._spin_dgen_item_freq.setToolTip("DUNGEONGEN_ITEM_FREQ — % de chance d'un item 16x16 dans la salle. 0=desactive.")
        item_row.addWidget(self._spin_dgen_item_freq)
        item_row.addStretch()
        ent_v.addLayout(item_row)

        ent_note = QLabel(
            "Sprites sur GFX_SPR.  Taille detectee depuis _mspr.c  (8x8=1 slot, 16x16=4, 32x32=16).\n"
            "Definir les sprites dans les pools ci-dessous. Slots = enemy_max * max_sz_pool + 4 item.")
        ent_note.setWordWrap(True)
        ent_note.setStyleSheet("color:#aaa;font-size:10px;")
        ent_v.addWidget(ent_note)
        v.addWidget(grp_ent)

        # ── Pool ennemis ─────────────────────────────────────────────────
        grp_ene_pool = QGroupBox("Pool ennemis — sprites selectionnes pour ce donjon")
        ene_pool_v = QVBoxLayout(grp_ene_pool)
        ene_pool_v.setSpacing(4)

        ene_pool_note = QLabel(
            "Chaque entree : un sprite ennemi + poids (proba relative) + max instances/salle.\n"
            "Le comportement peut etre force explicitement par entree, avec un parametre selon le mode.\n"
            "32x32 plafonne a max=2. Poids 0 = exclure. Vide = utilise legacy ENE1/ENE2.")
        ene_pool_note.setWordWrap(True)
        ene_pool_note.setStyleSheet("color:#aaa;font-size:10px;")
        ene_pool_v.addWidget(ene_pool_note)

        self._tbl_dgen_ene_pool = QTableWidget(0, 5)
        self._tbl_dgen_ene_pool.setHorizontalHeaderLabels(
            ["Entite (role=enemy)", "Poids", "Max/salle", "Comportement", "Param"]
        )
        self._tbl_dgen_ene_pool.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tbl_dgen_ene_pool.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._tbl_dgen_ene_pool.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._tbl_dgen_ene_pool.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._tbl_dgen_ene_pool.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self._tbl_dgen_ene_pool.setColumnWidth(1, 75)
        self._tbl_dgen_ene_pool.setColumnWidth(2, 80)
        self._tbl_dgen_ene_pool.setColumnWidth(3, 165)
        self._tbl_dgen_ene_pool.setColumnWidth(4, 76)
        self._tbl_dgen_ene_pool.setMaximumHeight(130)
        self._tbl_dgen_ene_pool.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        ene_pool_v.addWidget(self._tbl_dgen_ene_pool)

        ene_pool_btn_row = QHBoxLayout()
        btn_ene_add = QPushButton("+ Ajouter")
        btn_ene_add.setFixedWidth(90)
        btn_ene_add.clicked.connect(lambda: self._dgen_pool_add_row(
            self._tbl_dgen_ene_pool, "enemy", "", 1, 4))
        btn_ene_rem = QPushButton("- Supprimer")
        btn_ene_rem.setFixedWidth(90)
        btn_ene_rem.clicked.connect(lambda: self._dgen_pool_remove_row(
            self._tbl_dgen_ene_pool))
        ene_pool_btn_row.addWidget(btn_ene_add)
        ene_pool_btn_row.addWidget(btn_ene_rem)
        ene_pool_btn_row.addStretch()
        ene_pool_v.addLayout(ene_pool_btn_row)
        v.addWidget(grp_ene_pool)

        # ── Pool items ───────────────────────────────────────────────────
        grp_item_pool = QGroupBox("Pool items — sprites selectionnes pour ce donjon")
        item_pool_v = QVBoxLayout(grp_item_pool)
        item_pool_v.setSpacing(4)

        item_pool_note = QLabel(
            "Chaque entree : un sprite item + poids. Max 16x16 (32x32 non supporte pour les items).\n"
            "Vide = utilise legacy ITEM.")
        item_pool_note.setWordWrap(True)
        item_pool_note.setStyleSheet("color:#aaa;font-size:10px;")
        item_pool_v.addWidget(item_pool_note)

        self._tbl_dgen_item_pool = QTableWidget(0, 2)
        self._tbl_dgen_item_pool.setHorizontalHeaderLabels(["Entite (role=item)", "Poids"])
        self._tbl_dgen_item_pool.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tbl_dgen_item_pool.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._tbl_dgen_item_pool.setColumnWidth(1, 60)
        self._tbl_dgen_item_pool.setMaximumHeight(110)
        self._tbl_dgen_item_pool.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        item_pool_v.addWidget(self._tbl_dgen_item_pool)

        item_pool_btn_row = QHBoxLayout()
        btn_item_add = QPushButton("+ Ajouter")
        btn_item_add.setFixedWidth(90)
        btn_item_add.clicked.connect(lambda: self._dgen_pool_add_row(
            self._tbl_dgen_item_pool, "item", "", 1, None))
        btn_item_rem = QPushButton("- Supprimer")
        btn_item_rem.setFixedWidth(90)
        btn_item_rem.clicked.connect(lambda: self._dgen_pool_remove_row(
            self._tbl_dgen_item_pool))
        item_pool_btn_row.addWidget(btn_item_add)
        item_pool_btn_row.addWidget(btn_item_rem)
        item_pool_btn_row.addStretch()
        item_pool_v.addLayout(item_pool_btn_row)
        v.addWidget(grp_item_pool)

        # ── Player ───────────────────────────────────────────────────────
        grp_player = QGroupBox("Player — sprite utilise dans ce donjon")
        player_v = QVBoxLayout(grp_player)
        player_v.setSpacing(4)

        player_note = QLabel(
            "Selectionnez l'entite avec gameplay_role=player utilisee par le joueur.\n"
            "Quand DungeonGen est actif, le canvas est completement ignore a l'export —\n"
            "seules les pools et ce choix definissent les entites de la scene.")
        player_note.setWordWrap(True)
        player_note.setStyleSheet("color:#aaa;font-size:10px;")
        player_v.addWidget(player_note)

        player_row = QHBoxLayout()
        player_row.addWidget(QLabel("Entite player:"))
        self._combo_dgen_player = QComboBox()
        self._combo_dgen_player.setToolTip(
            "Entite avec role=player. Canvas ignore quand DungeonGen est actif.")
        self._combo_dgen_player.currentIndexChanged.connect(
            lambda _: self._store_scene_state(save_project=True, update_status=False))
        player_row.addWidget(self._combo_dgen_player, 1)
        player_row.addStretch()
        player_v.addLayout(player_row)
        v.addWidget(grp_player)

        # ── Navigation ───────────────────────────────────────────────────
        grp_nav = QGroupBox("Navigation — rooms avant boss")
        nav_v = QVBoxLayout(grp_nav)
        nav_v.setSpacing(4)

        nr_row = QHBoxLayout()
        nr_row.addWidget(QLabel("Rooms avant boss (0 = infini):"))
        self._spin_dgen_n_rooms = QSpinBox()
        self._spin_dgen_n_rooms.setRange(0, 9999)
        self._spin_dgen_n_rooms.setValue(0)
        self._spin_dgen_n_rooms.setToolTip(
            "DUNGEONGEN_N_ROOMS — nombre de salles a visiter avant de declencher le boss.\n"
            "0 = pas de limite. Exporte comme constante C pour le code de jeu.\n"
            "Usage : if (rooms_visited >= DUNGEONGEN_N_ROOMS && DUNGEONGEN_N_ROOMS) { goto boss; }")
        nr_row.addWidget(self._spin_dgen_n_rooms)
        nr_row.addStretch()
        nav_v.addLayout(nr_row)

        ramp_row = QHBoxLayout()
        ramp_row.addWidget(QLabel("Ramp difficulte tous les N rooms (0 = off):"))
        self._spin_dgen_enemy_ramp_rooms = QSpinBox()
        self._spin_dgen_enemy_ramp_rooms.setRange(0, 999)
        self._spin_dgen_enemy_ramp_rooms.setValue(0)
        self._spin_dgen_enemy_ramp_rooms.setToolTip(
            "DUNGEONGEN_ENEMY_RAMP_ROOMS — +1 ennemi max tous les N rooms jusqu'a ENEMY_MAX.\n"
            "0 = desactive. Ex : 5 → cap+1 room 5, cap+2 room 10...")
        ramp_row.addWidget(self._spin_dgen_enemy_ramp_rooms)
        ramp_row.addStretch()
        nav_v.addLayout(ramp_row)

        safe_row = QHBoxLayout()
        safe_row.addWidget(QLabel("Safe room toutes les N rooms (0 = off):"))
        self._spin_dgen_safe_room_every = QSpinBox()
        self._spin_dgen_safe_room_every.setRange(0, 999)
        self._spin_dgen_safe_room_every.setValue(0)
        self._spin_dgen_safe_room_every.setToolTip(
            "DUNGEONGEN_SAFE_ROOM_EVERY — toutes les N rooms : 0 ennemi + item garanti.\n"
            "0 = desactive. Ex : 5 → rooms 5,10,15... sont des checkpoints.")
        safe_row.addWidget(self._spin_dgen_safe_room_every)
        safe_row.addStretch()
        nav_v.addLayout(safe_row)

        mexits_row = QHBoxLayout()
        mexits_row.addWidget(QLabel("Sorties min par salle (0 = pas de contrainte):"))
        self._spin_dgen_min_exits = QSpinBox()
        self._spin_dgen_min_exits.setRange(0, 4)
        self._spin_dgen_min_exits.setValue(0)
        self._spin_dgen_min_exits.setToolTip(
            "DUNGEONGEN_MIN_EXITS — rejette les styles ayant moins de N sorties.\n"
            "0 = pas de contrainte. 1 = dead-end OK. 2 = au moins 2 sorties.")
        mexits_row.addWidget(self._spin_dgen_min_exits)
        mexits_row.addStretch()
        nav_v.addLayout(mexits_row)

        cl_row = QHBoxLayout()
        cl_row.addWidget(QLabel("Taille max cluster (2-4 rooms):"))
        self._spin_dgen_cluster_size_max = QSpinBox()
        self._spin_dgen_cluster_size_max.setRange(2, 4)
        self._spin_dgen_cluster_size_max.setValue(4)
        self._spin_dgen_cluster_size_max.setToolTip(
            "DUNGEONGEN_CLUSTER_SIZE_MAX — nombre max de salles par cluster.\n"
            "Un cluster = un lot de salles formant un arbre local avec backtrack libre.\n"
            "La transition entre clusters se fait via l'escalier (one-way).\n"
            "2 = lineaire (entry + leaf+stair), 3 = recommande, 4 = max.")
        cl_row.addWidget(self._spin_dgen_cluster_size_max)
        cl_row.addStretch()
        nav_v.addLayout(cl_row)

        nav_note = QLabel(
            "Modele cluster : chaque lot de salles forme un arbre local (2-4 rooms).\n"
            "Backtrack libre dans le cluster. L'escalier mene au cluster suivant (one-way).\n"
            "Navigation geree par ngpc_cluster.c — le module expose exits + has_stair.")
        nav_note.setWordWrap(True)
        nav_note.setStyleSheet("color:#aaa;font-size:10px;")
        nav_v.addWidget(nav_note)
        v.addWidget(grp_nav)

        # ── Tiers de difficulte ───────────────────────────────────────────
        grp_tier = QGroupBox("Tiers de difficulte")
        tier_v = QVBoxLayout(grp_tier)
        tier_v.setSpacing(4)

        tier_cols_row = QHBoxLayout()
        tier_cols_row.addWidget(QLabel("Nombre de tiers (0 = desactive):"))
        self._spin_dgen_tier_cols = QSpinBox()
        self._spin_dgen_tier_cols.setRange(0, 10)
        self._spin_dgen_tier_cols.setValue(0)
        self._spin_dgen_tier_cols.setToolTip(
            "DUNGEONGEN_TIER_COLS — nombre de paliers de difficulte.\n"
            "0 = desactive (utilise les frequences statiques).\n"
            "Appeler ngpc_dungeongen_set_tier(i) depuis le code de jeu apres un boss/zone.")
        tier_cols_row.addWidget(self._spin_dgen_tier_cols)
        tier_cols_row.addStretch()
        tier_v.addLayout(tier_cols_row)

        tier_note = QLabel(
            "Valeurs par tier separees par virgules (autant que le nombre de tiers).\n"
            "Ramp s'applique en bonus sur enemy_max du tier courant.")
        tier_note.setWordWrap(True)
        tier_note.setStyleSheet("color:#aaa;font-size:10px;")
        tier_v.addWidget(tier_note)

        for lbl_text, attr in [
            ("Enemy max par tier:",   "_edit_dgen_tier_ene_max"),
            ("Item freq par tier:",   "_edit_dgen_tier_item_freq"),
            ("Eau freq par tier:",    "_edit_dgen_tier_eau_freq"),
            ("Vide freq par tier:",   "_edit_dgen_tier_vide_freq"),
        ]:
            row = QHBoxLayout()
            row.addWidget(QLabel(lbl_text))
            edit = QLineEdit("1, 2, 3")
            edit.setPlaceholderText("ex: 1, 2, 3, 4, 5")
            setattr(self, attr, edit)
            row.addWidget(edit)
            tier_v.addLayout(row)

        v.addWidget(grp_tier)

        # ── Multi-floor ──────────────────────────────────────────────────
        grp_floor = QGroupBox("Multi-floor progression")
        floor_v = QVBoxLayout(grp_floor)
        floor_v.setSpacing(4)

        self._chk_dgen_multifloor = QCheckBox("Enable multi-floor")
        self._chk_dgen_multifloor.setToolTip(
            "Exporte DUNGEONGEN_MULTIFLOOR, FLOOR_VAR, MAX_FLOORS dans dungeongen_config.h.")
        floor_v.addWidget(self._chk_dgen_multifloor)

        fvar_row = QHBoxLayout()
        fvar_row.addWidget(QLabel("Floor variable index (0-7):"))
        self._spin_dgen_floor_var = QSpinBox()
        self._spin_dgen_floor_var.setRange(0, 7)
        self._spin_dgen_floor_var.setValue(0)
        self._spin_dgen_floor_var.setToolTip("Slot game_vars[] qui stocke l'etage courant (DUNGEONGEN_FLOOR_VAR).")
        fvar_row.addWidget(self._spin_dgen_floor_var)
        fvar_row.addStretch()
        floor_v.addLayout(fvar_row)

        mf_row = QHBoxLayout()
        mf_row.addWidget(QLabel("Max floors (0 = infini):"))
        self._spin_dgen_max_floors = QSpinBox()
        self._spin_dgen_max_floors.setRange(0, 99)
        self._spin_dgen_max_floors.setValue(0)
        self._spin_dgen_max_floors.setToolTip("DUNGEONGEN_MAX_FLOORS — apres N etages, goto boss scene. 0=boucle infinie.")
        mf_row.addWidget(self._spin_dgen_max_floors)
        mf_row.addStretch()
        floor_v.addLayout(mf_row)

        boss_row = QHBoxLayout()
        boss_row.addWidget(QLabel("Boss/end scene:"))
        self._combo_dgen_boss_scene = QComboBox()
        self._combo_dgen_boss_scene.addItem("(none)", "")
        self._combo_dgen_boss_scene.setToolTip("Scene de destination quand max_floors est atteint (DUNGEONGEN_BOSS_SCENE_ID).")
        boss_row.addWidget(self._combo_dgen_boss_scene, 1)
        floor_v.addLayout(boss_row)
        v.addWidget(grp_floor)

        # ── Export ───────────────────────────────────────────────────────
        self._btn_export_dgen_config = QPushButton("Export  dungeongen_config.h")
        self._btn_export_dgen_config.setToolTip(
            "Ecrit GraphX/gen/dungeongen_config.h avec tous les #define DUNGEONGEN_*.\n"
            "Inclure ce fichier AVANT #include \"ngpc_dungeongen/ngpc_dungeongen.h\".")
        self._btn_export_dgen_config.clicked.connect(self._export_dungeongen_config)
        v.addWidget(self._btn_export_dgen_config)

        export_note = QLabel(
            "Ajouter au Makefile:\n"
            "  OBJS += $(OBJ_DIR)/optional/ngpc_dungeongen/ngpc_dungeongen.rel\n"
            "  OBJS += $(OBJ_DIR)/GraphX/tiles_procgen.rel\n"
            "  OBJS += $(OBJ_DIR)/GraphX/sprites_lab.rel\n"
            "Dans le code : #include \"GraphX/gen/dungeongen_config.h\" avant ngpc_dungeongen.h"
        )
        export_note.setWordWrap(True)
        export_note.setStyleSheet("color:#aaa;font-size:10px;font-family:monospace;")
        v.addWidget(export_note)

        scroll.setWidget(inner)
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        return tab

    def _export_dungeongen_config(self) -> None:
        """Write GraphX/gen/dungeongen_config.h from the DungeonGen sub-tab params."""
        try:
            from core.procgen_config_gen import make_dungeongen_config_h
            self._store_scene_state(save_project=False, update_status=False)
            gen_dir = self._procgen_gen_dir()
            content = make_dungeongen_config_h(
                scene=self._scene,
                project_data=self._project_data_root if isinstance(self._project_data_root, dict) else None,
            )
            out = gen_dir / "dungeongen_config.h"
            out.write_text(content, encoding="utf-8")
            QMessageBox.information(self, "Export", f"Written: {out}")
        except Exception as exc:
            QMessageBox.critical(self, "Export error", str(exc))

    # ------------------------------------------------------------------
    # DungeonGen entity pool helpers
    # ------------------------------------------------------------------

    def _dgen_behavior_entries(self) -> list[tuple[str, str]]:
        """User-facing DungeonGen enemy behavior choices."""
        return [
            ("Auto (depuis move_type du sprite)", "auto"),
            ("Patrouille ligne droite", "patrol"),
            ("Patrouille aleatoire", "random"),
            ("Chasse joueur", "chase"),
            ("Fuite du joueur", "flee"),
            ("Fixe / immobile", "fixed"),
        ]

    def _dgen_behavior_param_meta(self, behavior: str) -> dict[str, object]:
        """Describe the optional per-behavior numeric parameter."""
        mode = str(behavior or "auto").strip().lower()
        if mode == "random":
            return {
                "enabled": True,
                "default": 24,
                "minimum": 4,
                "maximum": 255,
                "suffix": " fr",
                "tooltip": (
                    "Intervalle de changement de direction pour la patrouille aleatoire.\n"
                    "Valeur en frames. Plus petit = plus nerveux."
                ),
            }
        if mode in ("chase", "flee"):
            return {
                "enabled": True,
                "default": 5,
                "minimum": 1,
                "maximum": 31,
                "suffix": " t",
                "tooltip": (
                    "Rayon d'aggro en tiles de 8 px.\n"
                    "Dans ce rayon l'ennemi chasse le joueur, ou le fuit selon le comportement."
                ),
            }
        return {
            "enabled": False,
            "default": 0,
            "minimum": 0,
            "maximum": 255,
            "suffix": "",
            "tooltip": "Aucun parametre supplementaire pour ce comportement.",
        }

    def _sync_dgen_behavior_param_spin(
        self,
        behavior: str,
        spin: QSpinBox | None,
        force_default: bool = False,
    ) -> None:
        """Refresh one behavior param spin according to the selected behavior."""
        if spin is None:
            return
        meta = self._dgen_behavior_param_meta(behavior)
        enabled = bool(meta["enabled"])
        minimum = int(meta["minimum"])
        maximum = int(meta["maximum"])
        default = int(meta["default"])
        spin.blockSignals(True)
        spin.setRange(minimum, maximum)
        spin.setSuffix(str(meta["suffix"]))
        spin.setToolTip(str(meta["tooltip"]))
        spin.setEnabled(enabled)
        if not enabled:
            spin.setValue(0)
        else:
            cur = int(spin.value())
            if force_default or cur < minimum or cur > maximum or cur == 0:
                spin.setValue(default)
        spin.blockSignals(False)

    def _make_dgen_behavior_param_spin(
        self,
        behavior: str = "auto",
        value: int | None = None,
        on_change=None,
    ) -> QSpinBox:
        """Build a spinbox for the optional DungeonGen enemy behavior parameter."""
        spin = QSpinBox()
        spin.setRange(0, 255)
        spin.setAccelerated(True)
        spin.setFixedWidth(72)
        spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        if value is not None:
            spin.setValue(max(0, min(255, int(value))))
        self._sync_dgen_behavior_param_spin(behavior, spin, force_default=(value is None))
        if on_change is not None:
            spin.valueChanged.connect(lambda _: on_change())
        return spin

    def _make_dgen_behavior_combo(
        self,
        behavior: str = "auto",
        on_change=None,
    ) -> QComboBox:
        """Build a behavior combo for DungeonGen enemy pool rows."""
        combo = QComboBox()
        for label, value in self._dgen_behavior_entries():
            combo.addItem(label, value)
        combo.setToolTip(
            "Comportement de l'ennemi généré par DungeonGen.\n"
            "Auto = ancien comportement déduit depuis move_type.\n"
            "Patrouille ligne droite = mur à mur.\n"
            "Patrouille aléatoire = direction pseudo-aléatoire.\n"
            "Chasse/Fuite = utilise le rayon d'aggro du champ Param.\n"
            "Fixe = ne bouge pas."
        )
        idx = combo.findData(str(behavior or "auto"))
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        if on_change is not None:
            combo.currentIndexChanged.connect(lambda _: on_change())
        return combo

    def _dgen_pool_add_row(
        self,
        table: QTableWidget,
        role: str,
        entity_id: str = "",
        weight: int = 1,
        max_count: int | None = 4,
        behavior: str = "auto",
        behavior_arg: int | None = None,
    ) -> None:
        """Append one row to a DungeonGen entity pool table."""
        row = table.rowCount()
        table.insertRow(row)

        combo = QComboBox()
        combo.addItem("(aucune)", "")
        role_map = self._entity_roles or {}
        for name, r in sorted(role_map.items()):
            if str(r or "").lower() == role.lower():
                combo.addItem(name, name)
        idx = combo.findData(entity_id)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.currentIndexChanged.connect(
            lambda _: self._store_scene_state(save_project=True, update_status=False))
        table.setCellWidget(row, 0, combo)

        w_spin = QSpinBox()
        w_spin.setRange(1, 100)
        w_spin.setValue(max(1, int(weight or 1)))
        w_spin.valueChanged.connect(
            lambda _: self._store_scene_state(save_project=True, update_status=False))
        table.setCellWidget(row, 1, w_spin)

        if table.columnCount() >= 3 and max_count is not None:
            mc_spin = QSpinBox()
            mc_spin.setRange(1, 8)
            mc_spin.setValue(max(1, min(8, int(max_count or 4))))
            mc_spin.setToolTip(
                "Nombre max d'instances de ce sprite par salle.\n"
                "32x32 est automatiquement plafonne a 2 a l'export.")
            mc_spin.valueChanged.connect(
                lambda _: self._store_scene_state(save_project=True, update_status=False))
            table.setCellWidget(row, 2, mc_spin)

        if table.columnCount() >= 4 and str(role or "").lower() == "enemy":
            beh_combo = self._make_dgen_behavior_combo(
                behavior=behavior,
                on_change=None,
            )
            table.setCellWidget(row, 3, beh_combo)
            if table.columnCount() >= 5:
                arg_spin = self._make_dgen_behavior_param_spin(
                    behavior=behavior,
                    value=behavior_arg,
                    on_change=lambda: self._store_scene_state(save_project=True, update_status=False),
                )
                table.setCellWidget(row, 4, arg_spin)
                beh_combo.currentIndexChanged.connect(
                    lambda _, _combo=beh_combo, _spin=arg_spin: (
                        self._sync_dgen_behavior_param_spin(str(_combo.currentData() or "auto"), _spin),
                        self._store_scene_state(save_project=True, update_status=False)
                    )
                )
            else:
                beh_combo.currentIndexChanged.connect(
                    lambda _: self._store_scene_state(save_project=True, update_status=False)
                )

    def _dgen_pool_remove_row(self, table: QTableWidget) -> None:
        """Remove selected rows from a DungeonGen pool table."""
        rows = sorted({idx.row() for idx in table.selectedIndexes()}, reverse=True)
        for r in rows:
            table.removeRow(r)
        if not rows and table.rowCount() > 0:
            table.removeRow(table.rowCount() - 1)
        self._store_scene_state(save_project=True, update_status=False)

    def _get_dgen_pool(self, table: QTableWidget, has_max: bool = False) -> list[dict]:
        """Collect pool data from a pool table. Returns list of dicts."""
        result = []
        for r in range(table.rowCount()):
            combo = table.cellWidget(r, 0)
            w_spin = table.cellWidget(r, 1)
            entity_id = str(combo.currentData() or "") if combo else ""
            if not entity_id:
                continue
            entry: dict = {
                "entity_id": entity_id,
                "weight":    int(w_spin.value()) if w_spin else 1,
            }
            if has_max:
                mc_spin = table.cellWidget(r, 2)
                entry["max_count"] = int(mc_spin.value()) if mc_spin else 4
            if table.columnCount() >= 4:
                beh_combo = table.cellWidget(r, 3)
                if isinstance(beh_combo, QComboBox):
                    entry["behavior"] = str(beh_combo.currentData() or "auto")
            if table.columnCount() >= 5:
                arg_spin = table.cellWidget(r, 4)
                if isinstance(arg_spin, QSpinBox):
                    entry["behavior_arg"] = int(arg_spin.value())
            result.append(entry)
        return result

    def _set_dgen_pool(
        self,
        table: QTableWidget,
        role: str,
        pool_data: list,
        has_max: bool = False,
    ) -> None:
        """Load pool data into a pool table, replacing existing rows."""
        table.setRowCount(0)
        for entry in (pool_data or []):
            if not isinstance(entry, dict):
                continue
            entity_id = str(entry.get("entity_id", "") or "")
            weight    = max(1, int(entry.get("weight", 1) or 1))
            max_count = max(1, int(entry.get("max_count", 4) or 4)) if has_max else None
            behavior = str(entry.get("behavior", "auto") or "auto")
            behavior_arg = entry.get("behavior_arg", None)
            self._dgen_pool_add_row(table, role, entity_id, weight, max_count, behavior, behavior_arg)

    def _refresh_dgen_pool_combos(self) -> None:
        """Rebuild entity comboboxes in DungeonGen pool tables and player combo."""
        role_map = dict(self._entity_roles or {})
        for _et in (getattr(self, "_project_entity_types", None) or []):
            if not isinstance(_et, dict):
                continue
            _et_name = str(_et.get("name") or "").strip()
            if not _et_name or _et_name in role_map:
                continue
            _et_role = str(_et.get("role") or "prop").strip().lower()
            if _et_role:
                role_map[_et_name] = _et_role
        for table, role, has_max in [
            (getattr(self, "_tbl_dgen_ene_pool",  None), "enemy", True),
            (getattr(self, "_tbl_dgen_item_pool", None), "item",  False),
        ]:
            if table is None:
                continue
            for r in range(table.rowCount()):
                combo = table.cellWidget(r, 0)
                if not isinstance(combo, QComboBox):
                    continue
                cur = str(combo.currentData() or "")
                combo.blockSignals(True)
                combo.clear()
                combo.addItem("(aucune)", "")
                for name, rl in sorted(role_map.items()):
                    if str(rl or "").lower() == role.lower():
                        combo.addItem(name, name)
                idx = combo.findData(cur)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
                combo.blockSignals(False)
        player_combo = getattr(self, "_combo_dgen_player", None)
        if player_combo is not None:
            cur = str(player_combo.currentData() or "")
            player_combo.blockSignals(True)
            player_combo.clear()
            player_combo.addItem("(aucune)", "")
            for name, rl in sorted(role_map.items()):
                if str(rl or "").lower() == "player":
                    player_combo.addItem(name, name)
            idx = player_combo.findData(cur)
            player_combo.setCurrentIndex(idx if idx >= 0 else 0)
            player_combo.blockSignals(False)

    def _build_procgen_dfs_tab(self) -> QWidget:
        """Build and return the Dungeon DFS runtime configuration sub-tab."""
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(8)

        # ── Master enable ─────────────────────────────────────────────────
        self._chk_dfs_enabled = QCheckBox(
            "Enable Dungeon DFS runtime generation for this scene")
        self._chk_dfs_enabled.setToolTip(
            "When checked, the Export button writes procgen_config.h and the build\n"
            "pipeline includes it automatically.\n"
            "Uncheck = this scene uses static Design Map or no runtime procgen.")
        self._chk_dfs_enabled.setStyleSheet("font-weight: bold;")
        v.addWidget(self._chk_dfs_enabled)

        # Container that holds all params — disabled when master is off
        self._dfs_params_widget = QWidget()
        dfs_params_v = QVBoxLayout(self._dfs_params_widget)
        dfs_params_v.setContentsMargins(0, 0, 0, 0)
        dfs_params_v.setSpacing(8)

        def _dfs_toggle(checked: bool) -> None:
            self._dfs_params_widget.setEnabled(checked)

        self._chk_dfs_enabled.toggled.connect(_dfs_toggle)
        self._dfs_params_widget.setEnabled(False)  # disabled until checked

        # Wire container into the outer layout NOW, before rebinding v
        v.addWidget(self._dfs_params_widget, 1)

        # Alias for shorter code below — all subsequent v.addWidget() target the container
        v = dfs_params_v  # noqa: F841 — intentional rebind

        # ── Grid size ────────────────────────────────────────────────────
        grp_grid = QGroupBox("Grid size (rooms)")
        grid_v = QVBoxLayout(grp_grid)
        grid_v.setSpacing(4)
        grid_row = QHBoxLayout()
        grid_row.addWidget(QLabel("W:"))
        self._spin_dfs_grid_w = QSpinBox()
        self._spin_dfs_grid_w.setRange(2, 8)
        self._spin_dfs_grid_w.setValue(4)
        self._spin_dfs_grid_w.setToolTip("Grid width in rooms (PROCGEN_GRID_W). RAM: W×H bytes.")
        grid_row.addWidget(self._spin_dfs_grid_w)
        grid_row.addWidget(QLabel("H:"))
        self._spin_dfs_grid_h = QSpinBox()
        self._spin_dfs_grid_h.setRange(2, 8)
        self._spin_dfs_grid_h.setValue(4)
        self._spin_dfs_grid_h.setToolTip("Grid height in rooms (PROCGEN_GRID_H). RAM: W×H bytes.")
        grid_row.addWidget(self._spin_dfs_grid_h)
        grid_row.addStretch()
        grid_v.addLayout(grid_row)

        room_row = QHBoxLayout()
        room_row.addWidget(QLabel("Room size (tiles):"))
        self._spin_dfs_room_w = QSpinBox()
        self._spin_dfs_room_w.setRange(20, 32)
        self._spin_dfs_room_w.setValue(20)
        self._spin_dfs_room_w.setToolTip(
            "PROCGEN_ROOM_W — width of each room in tiles (20–32).\n"
            "20 = full screen, no camera scroll. 21–32 = follow cam inside the room.\n"
            "Max hardware BG tilemap is 32×32 — fits in VRAM without streaming.")
        room_row.addWidget(self._spin_dfs_room_w)
        room_row.addWidget(QLabel("×"))
        self._spin_dfs_room_h = QSpinBox()
        self._spin_dfs_room_h.setRange(19, 32)
        self._spin_dfs_room_h.setValue(19)
        self._spin_dfs_room_h.setToolTip(
            "PROCGEN_ROOM_H — height of each room in tiles (19–32).\n"
            "19 = full screen, no camera scroll. 20–32 = follow cam inside the room.\n"
            "Max hardware BG tilemap is 32×32 — fits in VRAM without streaming.")
        room_row.addWidget(self._spin_dfs_room_h)
        room_row.addWidget(QLabel("tiles"))
        room_row.addStretch()
        grid_v.addLayout(room_row)

        ram_note = QLabel("RAM: ~72 B base + W×H cells  •  Room 20×19 = single screen / 32×32 = HW max (no streaming)")
        ram_note.setStyleSheet("color:#aaa;font-size:10px;")
        grid_v.addWidget(ram_note)
        v.addWidget(grp_grid)

        # ── Content generation ───────────────────────────────────────────
        grp_content = QGroupBox("Content per room")
        content_v = QVBoxLayout(grp_content)
        content_v.setSpacing(4)

        max_row = QHBoxLayout()
        max_row.addWidget(QLabel("Max enemies per room:"))
        self._spin_dfs_max_enemies = QSpinBox()
        self._spin_dfs_max_enemies.setRange(0, 12)
        self._spin_dfs_max_enemies.setValue(4)
        self._spin_dfs_max_enemies.setToolTip("PROCGEN_MAX_ENEMIES — max entities placed per room")
        max_row.addWidget(self._spin_dfs_max_enemies)
        max_row.addStretch()
        content_v.addLayout(max_row)

        item_row = QHBoxLayout()
        item_row.addWidget(QLabel("Item chance per room:"))
        self._spin_dfs_item_chance = QSpinBox()
        self._spin_dfs_item_chance.setRange(0, 100)
        self._spin_dfs_item_chance.setValue(25)
        self._spin_dfs_item_chance.setSuffix("%")
        self._spin_dfs_item_chance.setToolTip("PROCGEN_ITEM_CHANCE — percent chance an item spawns in a room")
        item_row.addWidget(self._spin_dfs_item_chance)
        item_row.addStretch()
        content_v.addLayout(item_row)

        loop_row = QHBoxLayout()
        loop_row.addWidget(QLabel("Loop injection:"))
        self._spin_dfs_loop_pct = QSpinBox()
        self._spin_dfs_loop_pct.setRange(0, 80)
        self._spin_dfs_loop_pct.setValue(20)
        self._spin_dfs_loop_pct.setSuffix("%")
        self._spin_dfs_loop_pct.setToolTip("PROCGEN_LOOP_PCT — extra corridors added after DFS for loops")
        loop_row.addWidget(self._spin_dfs_loop_pct)
        loop_row.addStretch()
        content_v.addLayout(loop_row)

        active_row = QHBoxLayout()
        active_row.addWidget(QLabel("Max active enemies (global):"))
        self._spin_dfs_max_active = QSpinBox()
        self._spin_dfs_max_active.setRange(1, 40)
        self._spin_dfs_max_active.setValue(8)
        self._spin_dfs_max_active.setToolTip("PROCGEN_MAX_ACTIVE — max live enemies across all rooms simultaneously")
        active_row.addWidget(self._spin_dfs_max_active)
        active_row.addStretch()
        content_v.addLayout(active_row)

        start_row = QHBoxLayout()
        start_row.addWidget(QLabel("Player start mode:"))
        self._combo_dfs_start_mode = QComboBox()
        self._combo_dfs_start_mode.addItem("Corner (0,0)", "corner")
        self._combo_dfs_start_mode.addItem("Random room", "random")
        self._combo_dfs_start_mode.addItem("Furthest from exit", "far_exit")
        self._combo_dfs_start_mode.setToolTip("PROCGEN_START_MODE — where the player spawns in the dungeon")
        start_row.addWidget(self._combo_dfs_start_mode, 1)
        content_v.addLayout(start_row)

        v.addWidget(grp_content)

        # ── Difficulty tiers ─────────────────────────────────────────────
        grp_tiers = QGroupBox("Difficulty tiers")
        tiers_v = QVBoxLayout(grp_tiers)
        tiers_v.setSpacing(4)

        tier_cfg_row = QHBoxLayout()
        tier_cfg_row.addWidget(QLabel("Tiers actifs :"))
        self._spin_dfs_tier_count = QSpinBox()
        self._spin_dfs_tier_count.setRange(1, 5)
        self._spin_dfs_tier_count.setValue(5)
        self._spin_dfs_tier_count.setToolTip(
            "Nombre de colonnes exportées (1–5). Les colonnes désactivées sont grisées\n"
            "et non incluses dans le .h. Exporte PROCGEN_TIER_COUNT.")
        tier_cfg_row.addWidget(self._spin_dfs_tier_count)
        tier_cfg_row.addSpacing(16)
        tier_cfg_row.addWidget(QLabel("Floors par tier :"))
        self._spin_dfs_floors_per_tier = QSpinBox()
        self._spin_dfs_floors_per_tier.setRange(1, 50)
        self._spin_dfs_floors_per_tier.setValue(5)
        self._spin_dfs_floors_per_tier.setToolTip(
            "Nombre d'étages par palier de difficulté.\n"
            "tier = floor ÷ floors_per_tier, plafonné à tier_count-1.\n"
            "Exporte PROCGEN_FLOORS_PER_TIER.")
        tier_cfg_row.addWidget(self._spin_dfs_floors_per_tier)
        tier_cfg_row.addStretch()
        tiers_v.addLayout(tier_cfg_row)

        tier_note = QLabel("Colonnes grisées = non exportées. tier = floor ÷ floors_per_tier, plafonné à tier_count−1.")
        tier_note.setWordWrap(True)
        tier_note.setStyleSheet("color:#aaa;font-size:10px;")
        tiers_v.addWidget(tier_note)

        self._dfs_tier_table = QTableWidget(4, 5)
        self._dfs_tier_table.setHorizontalHeaderLabels(
            ["Tier 0", "Tier 1", "Tier 2", "Tier 3", "Tier 4"]
        )
        self._dfs_tier_table.setVerticalHeaderLabels(
            ["Max enemies", "Item chance%", "Loop pct%", "Max active"]
        )
        _defaults = [
            [2, 3, 4, 5, 6],
            [30, 25, 20, 15, 10],
            [10, 15, 20, 25, 30],
            [4, 6, 8, 10, 12],
        ]
        for r, row_vals in enumerate(_defaults):
            for c, val in enumerate(row_vals):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._dfs_tier_table.setItem(r, c, item)
        self._dfs_tier_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self._dfs_tier_table.setFixedHeight(130)
        tiers_v.addWidget(self._dfs_tier_table)

        def _dfs_update_tier_cols(n: int) -> None:
            for c in range(5):
                active = c < n
                for r in range(4):
                    it = self._dfs_tier_table.item(r, c)
                    if it:
                        flags = it.flags()
                        if active:
                            it.setFlags(flags | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable)
                            it.setForeground(self._dfs_tier_table.palette().text())
                        else:
                            it.setFlags(flags & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsEditable)
                            it.setForeground(self._dfs_tier_table.palette().mid())

        self._spin_dfs_tier_count.valueChanged.connect(_dfs_update_tier_cols)
        _dfs_update_tier_cols(5)
        v.addWidget(grp_tiers)

        # ── Multi-floor progression ──────────────────────────────────────
        grp_floor = QGroupBox("Multi-floor progression")
        floor_v = QVBoxLayout(grp_floor)
        floor_v.setSpacing(4)

        self._chk_dfs_multifloor = QCheckBox("Enable multi-floor (export goto_scene + var triggers)")
        self._chk_dfs_multifloor.setToolTip(
            "When enabled, exports C header constants and a trigger template for\n"
            "chaining floors via goto_scene + inc_variable(FLOOR).")
        floor_v.addWidget(self._chk_dfs_multifloor)

        var_row = QHBoxLayout()
        var_row.addWidget(QLabel("Floor variable index (0-7):"))
        self._spin_dfs_floor_var = QSpinBox()
        self._spin_dfs_floor_var.setRange(0, 7)
        self._spin_dfs_floor_var.setValue(0)
        self._spin_dfs_floor_var.setToolTip("Which game_vars[] slot tracks the current floor number")
        var_row.addWidget(self._spin_dfs_floor_var)
        var_row.addStretch()
        floor_v.addLayout(var_row)

        max_floor_row = QHBoxLayout()
        max_floor_row.addWidget(QLabel("Max floors (0 = infinite):"))
        self._spin_dfs_max_floors = QSpinBox()
        self._spin_dfs_max_floors.setRange(0, 99)
        self._spin_dfs_max_floors.setValue(0)
        self._spin_dfs_max_floors.setToolTip("After this many floors, goto the boss/end scene. 0 = loop forever.")
        max_floor_row.addWidget(self._spin_dfs_max_floors)
        max_floor_row.addStretch()
        floor_v.addLayout(max_floor_row)

        boss_row = QHBoxLayout()
        boss_row.addWidget(QLabel("Boss/end scene:"))
        self._combo_dfs_boss_scene = QComboBox()
        self._combo_dfs_boss_scene.addItem("(none)", "")
        self._combo_dfs_boss_scene.setToolTip("Scene to go to when max floors is reached")
        boss_row.addWidget(self._combo_dfs_boss_scene, 1)
        floor_v.addLayout(boss_row)

        loop_scene_row = QHBoxLayout()
        loop_scene_row.addWidget(QLabel("Reload scene (self-loop):"))
        self._combo_dfs_loop_scene = QComboBox()
        self._combo_dfs_loop_scene.addItem("(same scene)", "")
        self._combo_dfs_loop_scene.setToolTip(
            "Scene to goto_scene for each new floor. Leave blank = self-reload.")
        loop_scene_row.addWidget(self._combo_dfs_loop_scene, 1)
        floor_v.addLayout(loop_scene_row)

        v.addWidget(grp_floor)

        # ── Export ───────────────────────────────────────────────────────
        self._btn_export_dfs_config = QPushButton("Export  procgen_config.h")
        self._btn_export_dfs_config.setToolTip(
            "Write GraphX/gen/procgen_config.h with #define constants for all parameters above.")
        self._btn_export_dfs_config.clicked.connect(self._export_dfs_config)
        v.addWidget(self._btn_export_dfs_config)

        export_note = QLabel(
            "Include GraphX/gen/procgen_config.h before ngpc_procgen.h in your game code.\n"
            "Tier table exported as PROCGEN_TIER_* arrays in the header."
        )
        export_note.setWordWrap(True)
        export_note.setStyleSheet("color:#aaa;font-size:10px;")
        v.addWidget(export_note)

        v.addStretch()

        scroll.setWidget(inner)

        outer_v = QVBoxLayout(tab)
        outer_v.setContentsMargins(0, 0, 0, 0)
        outer_v.addWidget(scroll)
        return tab

    def _build_procgen_cave_tab(self) -> QWidget:
        """Build and return the Cave (cellular automaton) runtime config sub-tab."""
        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(8)

        # ── Master enable ─────────────────────────────────────────────────
        self._chk_cave_enabled = QCheckBox(
            "Enable Cave runtime generation for this scene")
        self._chk_cave_enabled.setToolTip(
            "When checked, the Export button writes cavegen_config.h and the build\n"
            "pipeline includes it automatically.\n"
            "Uncheck = this scene uses static Design Map or no runtime cave gen.")
        self._chk_cave_enabled.setStyleSheet("font-weight: bold;")
        v.addWidget(self._chk_cave_enabled)

        # Container that holds all params — disabled when master is off
        self._cave_params_widget = QWidget()
        cave_params_v = QVBoxLayout(self._cave_params_widget)
        cave_params_v.setContentsMargins(0, 0, 0, 0)
        cave_params_v.setSpacing(8)

        def _cave_toggle(checked: bool) -> None:
            self._cave_params_widget.setEnabled(checked)

        self._chk_cave_enabled.toggled.connect(_cave_toggle)
        self._cave_params_widget.setEnabled(False)  # disabled until checked

        # Wire container into the outer layout NOW, before rebinding v
        v.addWidget(self._cave_params_widget, 1)

        # Alias for shorter code below — all subsequent v.addWidget() target the container
        v = cave_params_v  # noqa: F841 — intentional rebind

        # ── Cave generation params ───────────────────────────────────────
        grp_gen = QGroupBox("Cave generation  (ngpc_cavegen)")
        gen_v = QVBoxLayout(grp_gen)
        gen_v.setSpacing(4)

        note = QLabel(
            "32×32 tile cellular automaton cave. RAM: 1024 B (cave grid) + ProcgenMap overhead."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#aaa;font-size:10px;")
        gen_v.addWidget(note)

        wall_row = QHBoxLayout()
        wall_row.addWidget(QLabel("Initial wall %:"))
        self._spin_cave_wall_pct = QSpinBox()
        self._spin_cave_wall_pct.setRange(30, 70)
        self._spin_cave_wall_pct.setValue(45)
        self._spin_cave_wall_pct.setSuffix("%")
        self._spin_cave_wall_pct.setToolTip(
            "CAVEGEN_WALL_PCT — seed density. 40-50% gives organic caves; <35% = sparse, >55% = very dense.")
        wall_row.addWidget(self._spin_cave_wall_pct)
        wall_row.addStretch()
        gen_v.addLayout(wall_row)

        iter_row = QHBoxLayout()
        iter_row.addWidget(QLabel("CA iterations:"))
        self._spin_cave_iterations = QSpinBox()
        self._spin_cave_iterations.setRange(1, 10)
        self._spin_cave_iterations.setValue(5)
        self._spin_cave_iterations.setToolTip(
            "CAVEGEN_ITERATIONS — smoothing passes. More = rounder caves, heavier init cost.")
        iter_row.addWidget(self._spin_cave_iterations)
        iter_row.addStretch()
        gen_v.addLayout(iter_row)

        v.addWidget(grp_gen)

        # ── Content ──────────────────────────────────────────────────────
        grp_content = QGroupBox("Content per cave")
        content_v = QVBoxLayout(grp_content)
        content_v.setSpacing(4)

        enem_row = QHBoxLayout()
        enem_row.addWidget(QLabel("Max enemies:"))
        self._spin_cave_max_enemies = QSpinBox()
        self._spin_cave_max_enemies.setRange(0, 16)
        self._spin_cave_max_enemies.setValue(6)
        self._spin_cave_max_enemies.setToolTip("CAVEGEN_MAX_ENEMIES — enemies placed in open floor cells")
        enem_row.addWidget(self._spin_cave_max_enemies)
        enem_row.addStretch()
        content_v.addLayout(enem_row)

        chest_row = QHBoxLayout()
        chest_row.addWidget(QLabel("Max items:"))
        self._spin_cave_max_chests = QSpinBox()
        self._spin_cave_max_chests.setRange(0, 8)
        self._spin_cave_max_chests.setValue(2)
        self._spin_cave_max_chests.setToolTip("CAVEGEN_MAX_ITEMS — item pickups placed in open floor cells")
        chest_row.addWidget(self._spin_cave_max_chests)
        chest_row.addStretch()
        content_v.addLayout(chest_row)

        pickup_row = QHBoxLayout()
        pickup_row.addWidget(QLabel("Pickup entity type index:"))
        self._spin_cave_pickup_type = QSpinBox()
        self._spin_cave_pickup_type.setRange(0, 255)
        self._spin_cave_pickup_type.setValue(0)
        self._spin_cave_pickup_type.setToolTip(
            "CAVEGEN_PICKUP_TYPE — index de l'entity type générique 'pickup' (role=item).\n"
            "Le runtime spawne cet entity type et applique le sprite de l'item via g_item_table[idx].sprite_id."
        )
        self._spin_cave_pickup_type.valueChanged.connect(lambda: self._store_scene_state(save_project=True, update_status=False))
        pickup_row.addWidget(self._spin_cave_pickup_type)
        pickup_row.addStretch()
        content_v.addLayout(pickup_row)

        # Item pool — which items can the procgen place
        pool_lbl = QLabel("Item pool:")
        pool_lbl.setToolTip(
            "Items que le procgen peut placer sur la map.\n"
            "Exporté comme CAVEGEN_ITEM_POOL[] + CAVEGEN_ITEM_POOL_SIZE.\n"
            "Vide = tous les items éligibles (le runtime choisit)."
        )
        content_v.addWidget(pool_lbl)
        self._list_cave_item_pool = QListWidget()
        self._list_cave_item_pool.setToolTip(pool_lbl.toolTip())
        self._list_cave_item_pool.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self._list_cave_item_pool.setMaximumHeight(80)
        self._list_cave_item_pool.itemSelectionChanged.connect(lambda: self._store_scene_state(save_project=True, update_status=False))
        content_v.addWidget(self._list_cave_item_pool)

        v.addWidget(grp_content)

        # ── Difficulty tiers ─────────────────────────────────────────────
        grp_tiers = QGroupBox("Difficulty tiers")
        tiers_v = QVBoxLayout(grp_tiers)
        tiers_v.setSpacing(4)

        cave_tier_cfg_row = QHBoxLayout()
        cave_tier_cfg_row.addWidget(QLabel("Tiers actifs :"))
        self._spin_cave_tier_count = QSpinBox()
        self._spin_cave_tier_count.setRange(1, 5)
        self._spin_cave_tier_count.setValue(5)
        self._spin_cave_tier_count.setToolTip(
            "Nombre de colonnes exportées (1–5). Exporte CAVEGEN_TIER_COUNT.")
        cave_tier_cfg_row.addWidget(self._spin_cave_tier_count)
        cave_tier_cfg_row.addSpacing(16)
        cave_tier_cfg_row.addWidget(QLabel("Floors par tier :"))
        self._spin_cave_floors_per_tier = QSpinBox()
        self._spin_cave_floors_per_tier.setRange(1, 50)
        self._spin_cave_floors_per_tier.setValue(5)
        self._spin_cave_floors_per_tier.setToolTip(
            "Nombre d'étages par palier de difficulté.\n"
            "tier = floor ÷ floors_per_tier, plafonné à tier_count-1.\n"
            "Exporte CAVEGEN_FLOORS_PER_TIER.")
        cave_tier_cfg_row.addWidget(self._spin_cave_floors_per_tier)
        cave_tier_cfg_row.addStretch()
        tiers_v.addLayout(cave_tier_cfg_row)

        cave_tier_note = QLabel("Colonnes grisées = non exportées. tier = floor ÷ floors_per_tier, plafonné à tier_count−1.")
        cave_tier_note.setWordWrap(True)
        cave_tier_note.setStyleSheet("color:#aaa;font-size:10px;")
        tiers_v.addWidget(cave_tier_note)

        self._cave_tier_table = QTableWidget(3, 5)
        self._cave_tier_table.setHorizontalHeaderLabels(
            ["Tier 0", "Tier 1", "Tier 2", "Tier 3", "Tier 4"]
        )
        self._cave_tier_table.setVerticalHeaderLabels(
            ["Wall %", "Max enemies", "Max items"]
        )
        _cave_defaults = [
            [45, 47, 50, 52, 55],
            [3, 4, 6, 8, 10],
            [3, 2, 2, 1, 1],
        ]
        for r, row_vals in enumerate(_cave_defaults):
            for c, val in enumerate(row_vals):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._cave_tier_table.setItem(r, c, item)
        self._cave_tier_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self._cave_tier_table.setFixedHeight(104)
        tiers_v.addWidget(self._cave_tier_table)

        def _cave_update_tier_cols(n: int) -> None:
            for c in range(5):
                active = c < n
                for r in range(3):
                    it = self._cave_tier_table.item(r, c)
                    if it:
                        flags = it.flags()
                        if active:
                            it.setFlags(flags | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable)
                            it.setForeground(self._cave_tier_table.palette().text())
                        else:
                            it.setFlags(flags & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsEditable)
                            it.setForeground(self._cave_tier_table.palette().mid())

        self._spin_cave_tier_count.valueChanged.connect(_cave_update_tier_cols)
        _cave_update_tier_cols(5)

        v.addWidget(grp_tiers)

        # ── Multi-floor progression ──────────────────────────────────────
        grp_floor = QGroupBox("Multi-floor progression")
        floor_v = QVBoxLayout(grp_floor)
        floor_v.setSpacing(4)

        self._chk_cave_multifloor = QCheckBox("Enable multi-floor")
        self._chk_cave_multifloor.setToolTip(
            "Export goto_scene + inc_variable trigger template for chained cave floors.")
        floor_v.addWidget(self._chk_cave_multifloor)

        cvar_row = QHBoxLayout()
        cvar_row.addWidget(QLabel("Floor variable index (0-7):"))
        self._spin_cave_floor_var = QSpinBox()
        self._spin_cave_floor_var.setRange(0, 7)
        self._spin_cave_floor_var.setValue(0)
        self._spin_cave_floor_var.setToolTip("Which game_vars[] slot tracks the current floor number")
        cvar_row.addWidget(self._spin_cave_floor_var)
        cvar_row.addStretch()
        floor_v.addLayout(cvar_row)

        cmax_row = QHBoxLayout()
        cmax_row.addWidget(QLabel("Max floors (0 = infinite):"))
        self._spin_cave_max_floors = QSpinBox()
        self._spin_cave_max_floors.setRange(0, 99)
        self._spin_cave_max_floors.setValue(0)
        cmax_row.addWidget(self._spin_cave_max_floors)
        cmax_row.addStretch()
        floor_v.addLayout(cmax_row)

        cboss_row = QHBoxLayout()
        cboss_row.addWidget(QLabel("Boss/end scene:"))
        self._combo_cave_boss_scene = QComboBox()
        self._combo_cave_boss_scene.addItem("(none)", "")
        cboss_row.addWidget(self._combo_cave_boss_scene, 1)
        floor_v.addLayout(cboss_row)

        v.addWidget(grp_floor)

        # ── Export ───────────────────────────────────────────────────────
        self._btn_export_cave_config = QPushButton("Export  cavegen_config.h")
        self._btn_export_cave_config.setToolTip(
            "Write GraphX/gen/cavegen_config.h with #define constants for all parameters above.")
        self._btn_export_cave_config.clicked.connect(self._export_cave_config)
        v.addWidget(self._btn_export_cave_config)

        export_note = QLabel(
            "Include GraphX/gen/cavegen_config.h before ngpc_cavegen.h in your game code."
        )
        export_note.setWordWrap(True)
        export_note.setStyleSheet("color:#aaa;font-size:10px;")
        v.addWidget(export_note)

        v.addStretch()
        scroll.setWidget(inner)

        outer_v = QVBoxLayout(tab)
        outer_v.setContentsMargins(0, 0, 0, 0)
        outer_v.addWidget(scroll)
        return tab

    def _build_procgen_assets_tab(self) -> QWidget:
        """Build and return the Procgen Assets sub-tab (project-level DungeonGen tileset config)."""
        from core.dungeongen_tiles_export import TILE_ROLE_ORDER, COMPACT_SOURCE_ROLES, COMPACT_DERIVED_ROLES

        tab = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(8)

        note = QLabel(
            "Configuration au niveau PROJET — s'applique à toutes les scènes DungeonGen.\n"
            "Les fichiers tiles_procgen.h/c sont regénérés à chaque export."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #aaa; font-size: 10px;")
        v.addWidget(note)

        grp_ts = QGroupBox("DungeonGen Tileset")
        ts_v = QVBoxLayout(grp_ts)
        ts_v.setSpacing(5)

        png_row = QHBoxLayout()
        png_row.addWidget(QLabel("Tileset PNG:"))
        self._lbl_dgen_pa_png = QLabel("(aucun)")
        self._lbl_dgen_pa_png.setStyleSheet("color: #bbb; font-size: 10px;")
        self._lbl_dgen_pa_png.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        png_row.addWidget(self._lbl_dgen_pa_png, 1)
        btn_browse_png = QPushButton("Browse…")
        btn_browse_png.setFixedWidth(70)
        btn_browse_png.clicked.connect(self._pick_dgen_pa_png)
        png_row.addWidget(btn_browse_png)
        ts_v.addLayout(png_row)

        cell_row = QHBoxLayout()
        cell_row.addWidget(QLabel("Taille cellule source:"))
        self._combo_dgen_pa_cell_size = QComboBox()
        self._combo_dgen_pa_cell_size.addItem("8×8 px  (1 tile NGPC)",  "8x8")
        self._combo_dgen_pa_cell_size.addItem("16×16 px (2×2 tiles NGPC)", "16x16")
        self._combo_dgen_pa_cell_size.addItem("32×32 px (4×4 tiles NGPC)", "32x32")
        self._combo_dgen_pa_cell_size.setCurrentIndex(1)
        self._combo_dgen_pa_cell_size.setToolTip(
            "Taille d'une cellule dans le PNG source.\n"
            "8×8 : chaque cellule = 1 tile NGPC — index tile = index cellule.\n"
            "16×16 : chaque cellule = 2×2 tiles NGPC (4 tiles) — mode recommandé.\n"
            "32×32 : chaque cellule = 4×4 tiles NGPC (16 tiles).\n\n"
            "Doit correspondre à la grille du PNG tileset.\n"
            "Mettre à jour aussi 'Taille cellule (tiles NGPC)' dans l'onglet DungeonGen de chaque scène."
        )
        self._combo_dgen_pa_cell_size.currentIndexChanged.connect(
            lambda _: (self._save_procgen_assets_state(), self._refresh_dgen_pa_preview()))
        cell_row.addWidget(self._combo_dgen_pa_cell_size, 1)
        ts_v.addLayout(cell_row)

        self._dgen_pa_preview = QLabel()
        self._dgen_pa_preview.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._dgen_pa_preview.setMinimumHeight(120)
        self._dgen_pa_preview.setMaximumHeight(320)
        self._dgen_pa_preview.setStyleSheet("background: #1a1a26; border: 1px solid #333;")
        self._dgen_pa_preview.setText("<span style='color:#555; font-size:10px;'>Charger un PNG pour voir l'aperçu…</span>")
        self._dgen_pa_preview.setTextFormat(Qt.TextFormat.RichText)
        ts_v.addWidget(self._dgen_pa_preview)

        v.addWidget(grp_ts)

        grp_roles = QGroupBox("Tile Roles — index dans le PNG")
        roles_v = QVBoxLayout(grp_roles)
        roles_v.setSpacing(4)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(6)
        mode_row.addWidget(QLabel("Mode tileset :"))
        self._combo_dgen_tileset_mode = QComboBox()
        self._combo_dgen_tileset_mode.addItem("Full (26 rôles, tous en PNG)", "full")
        self._combo_dgen_tileset_mode.addItem("Compact (13 source + rot/flip outil+HW)", "compact")
        self._combo_dgen_tileset_mode.setToolTip(
            "Full : chaque rôle directionnel a sa propre cellule dans le PNG (26 cellules min).\n"
            "Compact : seulement wall_s, corner_nw, int_wall_s, int_corner_nw, door_s.\n"
            "  - wall_s = mur extérieur plein du bas, corner_nw = coin extérieur haut-gauche\n"
            "  - int_wall_s = mur intérieur plein du bas, int_corner_nw = coin intérieur haut-gauche\n"
            "  - door_s = ouverture/porte du bas (ne pas utiliser une arche verticale ici)\n"
            "  • wall_e = rotation 90°CCW de wall_s (outil à l'export)\n"
            "  • int_wall_e = rotation 90°CCW de int_wall_s (outil à l'export)\n"
            "  • door_e = rotation 90°CCW de door_s (outil à l'export)\n"
            "  • wall_n/w = flip hardware V/H de wall_s/wall_e\n"
            "  • corners ext/int = flip hardware de corner_nw / int_corner_nw\n"
            "Économise ~13 cellules dans le PNG."
        )
        mode_row.addWidget(self._combo_dgen_tileset_mode)
        mode_row.addStretch()
        roles_v.addLayout(mode_row)

        roles_note = QLabel(
            "Index = numéro de la cellule dans le PNG (gauche→droite, haut→bas, depuis 0).\n"
            "La taille d'une cellule est définie par 'Taille cellule source' ci-dessus."
        )
        roles_note.setWordWrap(True)
        roles_note.setStyleSheet("color: #aaa; font-size: 10px;")
        roles_v.addWidget(roles_note)

        _compact_source_keys: set[str] = {rk for rk, _ in COMPACT_SOURCE_ROLES}
        _full_keys: set[str]    = {rk for rk, _ in TILE_ROLE_ORDER}
        _all_role_list: list[tuple[str, str]] = list(TILE_ROLE_ORDER)
        for rk, cs in COMPACT_SOURCE_ROLES:
            if rk not in _full_keys:
                _all_role_list.append((rk, cs))

        _derived_info: dict[str, str] = {}
        for drk, _dcs, src_key, hflip, vflip, is_rot in COMPACT_DERIVED_ROLES:
            if is_rot:
                _derived_info[drk] = f"→ rotation 90°CCW de '{src_key}' (outil export)"
            elif hflip and vflip:
                _derived_info[drk] = f"→ flip HV de '{src_key}' (hardware)"
            elif hflip:
                _derived_info[drk] = f"→ flip H de '{src_key}' (hardware)"
            else:
                _derived_info[drk] = f"→ flip V de '{src_key}' (hardware)"
        _derived_info["door"] = "→ remplacé par 'door_s' en mode compact"

        self._dgen_pa_role_spins: dict[str, QSpinBox] = {}
        self._dgen_pa_role_rows:  dict[str, QWidget]  = {}

        for role_key, c_suffix in _all_role_list:
            row_wdg = QWidget()
            row_wdg.setContentsMargins(0, 0, 0, 0)
            row_h = QHBoxLayout(row_wdg)
            row_h.setContentsMargins(0, 0, 0, 0)
            row_h.setSpacing(6)
            lbl = QLabel(f"{role_key}")
            lbl.setFixedWidth(130)
            lbl.setStyleSheet("font-size: 10px;")
            lbl.setToolTip(f"C define: TILE_{c_suffix}")
            row_h.addWidget(lbl)

            is_derived = role_key in _derived_info and role_key not in _compact_source_keys and role_key != "door_s"
            if is_derived:
                spin = QSpinBox()
                spin.setRange(-1, 9999)
                spin.setValue(-1)
                spin.setSpecialValueText("—")
                spin.setFixedWidth(90)
                spin.setMinimumWidth(90)
                spin.setToolTip(f"Index cellule PNG pour le rôle '{role_key}' (TILE_{c_suffix})\n— = rôle non utilisé")
                spin.valueChanged.connect(lambda _, _k=role_key: self._save_procgen_assets_state())
                row_h.addWidget(spin)
                info_lbl = QLabel(_derived_info.get(role_key, ""))
                info_lbl.setStyleSheet("color: #666; font-size: 9px; font-style: italic;")
                row_h.addWidget(info_lbl)
                self._dgen_pa_role_spins[role_key] = spin
            else:
                spin = QSpinBox()
                spin.setRange(-1, 9999)
                spin.setValue(-1)
                spin.setSpecialValueText("—")
                spin.setFixedWidth(90)
                spin.setMinimumWidth(90)
                spin.setToolTip(f"Index cellule PNG pour le rôle '{role_key}' (TILE_{c_suffix})\n— = rôle non utilisé")
                spin.valueChanged.connect(lambda _, _k=role_key: self._save_procgen_assets_state())
                row_h.addWidget(spin)
                self._dgen_pa_role_spins[role_key] = spin

            row_h.addStretch()
            roles_v.addWidget(row_wdg)
            self._dgen_pa_role_rows[role_key] = row_wdg

        self._combo_dgen_tileset_mode.currentIndexChanged.connect(
            lambda _: self._update_tile_role_mode_visibility()
        )
        self._update_tile_role_mode_visibility()

        v.addWidget(grp_roles)

        grp_ene = QGroupBox("Pool Ennemis — sprites VRAM (sprites_lab.h)")
        ene_v = QVBoxLayout(grp_ene)
        ene_v.setSpacing(4)
        ene_note = QLabel(
            "Ces entités sont chargées en VRAM et utilisées par ngpc_dungeongen_spawn().\n"
            "Chaque entrée doit avoir un fichier *_mspr.c dans GraphX/.\n"
            "Le comportement exporté peut être défini explicitement par entrée."
        )
        ene_note.setWordWrap(True)
        ene_note.setStyleSheet("color: #aaa; font-size: 10px;")
        ene_v.addWidget(ene_note)
        self._tbl_dgen_pa_ene_pool = QTableWidget(0, 5)
        self._tbl_dgen_pa_ene_pool.setHorizontalHeaderLabels(
            ["Entité (entity_id)", "Poids", "Max/salle", "Comportement", "Param"]
        )
        self._tbl_dgen_pa_ene_pool.horizontalHeader().setStretchLastSection(False)
        self._tbl_dgen_pa_ene_pool.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tbl_dgen_pa_ene_pool.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._tbl_dgen_pa_ene_pool.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._tbl_dgen_pa_ene_pool.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._tbl_dgen_pa_ene_pool.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self._tbl_dgen_pa_ene_pool.setColumnWidth(1, 75)
        self._tbl_dgen_pa_ene_pool.setColumnWidth(2, 80)
        self._tbl_dgen_pa_ene_pool.setColumnWidth(3, 165)
        self._tbl_dgen_pa_ene_pool.setColumnWidth(4, 76)
        self._tbl_dgen_pa_ene_pool.setFixedHeight(120)
        self._tbl_dgen_pa_ene_pool.itemChanged.connect(lambda _: self._save_procgen_assets_state())
        ene_v.addWidget(self._tbl_dgen_pa_ene_pool)
        ene_btns = QHBoxLayout()
        btn_ene_add = QPushButton("+ Ajouter")
        btn_ene_add.setFixedWidth(80)
        btn_ene_add.clicked.connect(self._dgen_pa_ene_add_row)
        btn_ene_rem = QPushButton("− Supprimer")
        btn_ene_rem.setFixedWidth(90)
        btn_ene_rem.clicked.connect(self._dgen_pa_ene_remove_row)
        ene_btns.addWidget(btn_ene_add)
        ene_btns.addWidget(btn_ene_rem)
        ene_btns.addStretch()
        ene_v.addLayout(ene_btns)
        v.addWidget(grp_ene)

        grp_item = QGroupBox("Pool Items — sprites VRAM (sprites_lab.h)")
        item_v = QVBoxLayout(grp_item)
        item_v.setSpacing(4)
        item_note = QLabel("Ces entités items sont chargées en VRAM (max 16×16 px).")
        item_note.setWordWrap(True)
        item_note.setStyleSheet("color: #aaa; font-size: 10px;")
        item_v.addWidget(item_note)
        self._tbl_dgen_pa_item_pool = QTableWidget(0, 3)
        self._tbl_dgen_pa_item_pool.setHorizontalHeaderLabels(["Entité (entity_id)", "Poids", "Max/salle"])
        self._tbl_dgen_pa_item_pool.horizontalHeader().setStretchLastSection(False)
        self._tbl_dgen_pa_item_pool.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tbl_dgen_pa_item_pool.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._tbl_dgen_pa_item_pool.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._tbl_dgen_pa_item_pool.setColumnWidth(1, 75)
        self._tbl_dgen_pa_item_pool.setColumnWidth(2, 80)
        self._tbl_dgen_pa_item_pool.setFixedHeight(100)
        self._tbl_dgen_pa_item_pool.itemChanged.connect(lambda _: self._save_procgen_assets_state())
        item_v.addWidget(self._tbl_dgen_pa_item_pool)
        item_btns = QHBoxLayout()
        btn_item_add = QPushButton("+ Ajouter")
        btn_item_add.setFixedWidth(80)
        btn_item_add.clicked.connect(self._dgen_pa_item_add_row)
        btn_item_rem = QPushButton("− Supprimer")
        btn_item_rem.setFixedWidth(90)
        btn_item_rem.clicked.connect(self._dgen_pa_item_remove_row)
        item_btns.addWidget(btn_item_add)
        item_btns.addWidget(btn_item_rem)
        item_btns.addStretch()
        item_v.addLayout(item_btns)
        v.addWidget(grp_item)

        v.addStretch()
        scroll.setWidget(inner)
        outer_v = QVBoxLayout(tab)
        outer_v.setContentsMargins(0, 0, 0, 0)
        outer_v.addWidget(scroll)
        return tab

    def _dgen_pa_ene_add_row(self) -> None:
        tbl = self._tbl_dgen_pa_ene_pool
        tbl.blockSignals(True)
        r = tbl.rowCount()
        tbl.insertRow(r)
        tbl.setItem(r, 0, QTableWidgetItem(""))
        tbl.setItem(r, 1, QTableWidgetItem("1"))
        tbl.setItem(r, 2, QTableWidgetItem("4"))
        beh_combo = self._make_dgen_behavior_combo(behavior="auto", on_change=None)
        arg_spin = self._make_dgen_behavior_param_spin(
            behavior="auto",
            value=None,
            on_change=self._save_procgen_assets_state,
        )
        tbl.setCellWidget(r, 3, beh_combo)
        tbl.setCellWidget(r, 4, arg_spin)
        beh_combo.currentIndexChanged.connect(
            lambda _, _combo=beh_combo, _spin=arg_spin: (
                self._sync_dgen_behavior_param_spin(str(_combo.currentData() or "auto"), _spin),
                self._save_procgen_assets_state()
            )
        )
        tbl.blockSignals(False)
        self._save_procgen_assets_state()

    def _dgen_pa_ene_remove_row(self) -> None:
        tbl = self._tbl_dgen_pa_ene_pool
        rows = sorted(set(i.row() for i in tbl.selectedItems()), reverse=True)
        if not rows:
            r = tbl.rowCount() - 1
            if r >= 0:
                rows = [r]
        for r in rows:
            tbl.removeRow(r)
        self._save_procgen_assets_state()

    def _dgen_pa_item_add_row(self) -> None:
        tbl = self._tbl_dgen_pa_item_pool
        tbl.blockSignals(True)
        r = tbl.rowCount()
        tbl.insertRow(r)
        tbl.setItem(r, 0, QTableWidgetItem(""))
        tbl.setItem(r, 1, QTableWidgetItem("1"))
        tbl.setItem(r, 2, QTableWidgetItem("1"))
        tbl.blockSignals(False)
        self._save_procgen_assets_state()

    def _dgen_pa_item_remove_row(self) -> None:
        tbl = self._tbl_dgen_pa_item_pool
        rows = sorted(set(i.row() for i in tbl.selectedItems()), reverse=True)
        if not rows:
            r = tbl.rowCount() - 1
            if r >= 0:
                rows = [r]
        for r in rows:
            tbl.removeRow(r)
        self._save_procgen_assets_state()

    def _pick_dgen_pa_png(self) -> None:
        """File picker for the DungeonGen tileset PNG."""
        start = QSettings("NGPCraft", "Engine").value("level/dgen_pa_png_dir", "", str)
        path, _ = QFileDialog.getOpenFileName(
            self, "Sélectionner le tileset DungeonGen", start,
            "Images PNG (*.png);;Tous les fichiers (*)"
        )
        if not path:
            return
        p = Path(path)
        QSettings("NGPCraft", "Engine").setValue("level/dgen_pa_png_dir", str(p.parent))
        rel = path
        if self._base_dir:
            try:
                rel = str(p.relative_to(self._base_dir))
            except ValueError:
                rel = path
        self._dgen_pa_png_rel = rel
        self._lbl_dgen_pa_png.setText(p.name)
        self._lbl_dgen_pa_png.setToolTip(rel)
        self._save_procgen_assets_state()
        self._refresh_dgen_pa_preview()

    def _save_procgen_assets_state(self) -> None:
        """Persist DungeonGen procgen assets config to project_data_root and trigger project save."""
        if not isinstance(self._project_data_root, dict):
            return
        pa = self._project_data_root.setdefault("procgen_assets", {})
        if not isinstance(pa, dict):
            pa = {}
            self._project_data_root["procgen_assets"] = pa
        da = pa.get("dungeongen")
        if not isinstance(da, dict):
            da = {}
        pa["dungeongen"] = da

        da["tileset_png"] = str(getattr(self, "_dgen_pa_png_rel", "") or "").strip()

        cell_combo = getattr(self, "_combo_dgen_pa_cell_size", None)
        cell_size_key = "16x16"
        if cell_combo is not None:
            cell_size_key = str(cell_combo.currentData() or "16x16")
            da["cell_size"] = cell_size_key

        _cell_tiles = {"8x8": 1, "16x16": 2, "32x32": 4}
        _ct = _cell_tiles.get(cell_size_key, 2)
        for _spin_name in ("_spin_dgen_cell_w", "_spin_dgen_cell_h"):
            _sp = getattr(self, _spin_name, None)
            if _sp is not None and _sp.value() != _ct:
                _sp.blockSignals(True)
                _sp.setValue(_ct)
                _sp.blockSignals(False)

        _mode_combo = getattr(self, "_combo_dgen_tileset_mode", None)
        _tmode = "full"
        if _mode_combo is not None:
            _tmode = str(_mode_combo.currentData() or "full")
        da["tileset_mode"] = _tmode

        role_spins = getattr(self, "_dgen_pa_role_spins", {})
        tile_roles = {}
        for role_key, spin in role_spins.items():
            v = spin.value()
            if v >= 0:
                tile_roles[role_key] = [v]
        da["tile_roles"] = tile_roles

        tbl_ene = getattr(self, "_tbl_dgen_pa_ene_pool", None)
        if tbl_ene is not None:
            ene_pool = []
            for row in range(tbl_ene.rowCount()):
                eid_item = tbl_ene.item(row, 0)
                w_item   = tbl_ene.item(row, 1)
                mx_item  = tbl_ene.item(row, 2)
                beh_combo = tbl_ene.cellWidget(row, 3)
                arg_spin = tbl_ene.cellWidget(row, 4) if tbl_ene.columnCount() >= 5 else None
                eid = (eid_item.text().strip() if eid_item else "")
                if not eid:
                    continue
                try:
                    w = max(1, int(w_item.text())) if w_item else 1
                except ValueError:
                    w = 1
                try:
                    mx = max(1, int(mx_item.text())) if mx_item else 4
                except ValueError:
                    mx = 4
                behavior = str(beh_combo.currentData() or "auto") if isinstance(beh_combo, QComboBox) else "auto"
                behavior_arg = int(arg_spin.value()) if isinstance(arg_spin, QSpinBox) else 0
                ene_pool.append({
                    "entity_id": eid,
                    "weight": w,
                    "max_count": mx,
                    "behavior": behavior,
                    "behavior_arg": behavior_arg,
                })
            da["enemy_pool"] = ene_pool

        tbl_item = getattr(self, "_tbl_dgen_pa_item_pool", None)
        if tbl_item is not None:
            item_pool = []
            for row in range(tbl_item.rowCount()):
                eid_item = tbl_item.item(row, 0)
                w_item   = tbl_item.item(row, 1)
                mx_item  = tbl_item.item(row, 2)
                eid = (eid_item.text().strip() if eid_item else "")
                if not eid:
                    continue
                try:
                    w = max(1, int(w_item.text())) if w_item else 1
                except ValueError:
                    w = 1
                try:
                    mx = max(1, int(mx_item.text())) if mx_item else 1
                except ValueError:
                    mx = 1
                item_pool.append({"entity_id": eid, "weight": w, "max_count": mx})
            da["item_pool"] = item_pool

        if self._on_save:
            self._on_save()

    def _update_tile_role_mode_visibility(self) -> None:
        """Show/hide tile role rows based on current tileset mode (full or compact)."""
        try:
            from core.dungeongen_tiles_export import TILE_ROLE_ORDER, COMPACT_SOURCE_ROLES
        except ImportError:
            return
        _mode_combo = getattr(self, "_combo_dgen_tileset_mode", None)
        mode = "full"
        if _mode_combo is not None:
            mode = str(_mode_combo.currentData() or "full")

        role_rows = getattr(self, "_dgen_pa_role_rows", {})
        if not role_rows:
            return

        if mode == "compact":
            _visible_keys: set[str] = {rk for rk, _ in COMPACT_SOURCE_ROLES}
        else:
            _visible_keys = {rk for rk, _ in TILE_ROLE_ORDER}

        for role_key, row_wdg in role_rows.items():
            row_wdg.setVisible(role_key in _visible_keys)

    def _restore_procgen_assets_state(self) -> None:
        """Restore Procgen Assets UI widgets from project_data_root."""
        pd = self._project_data_root if isinstance(self._project_data_root, dict) else {}
        pa = (pd.get("procgen_assets") or {}) if pd else {}
        da = (pa.get("dungeongen") or {}) if isinstance(pa, dict) else {}
        if not isinstance(da, dict):
            da = {}

        png_rel = str(da.get("tileset_png", "") or "").strip()
        self._dgen_pa_png_rel = png_rel
        lbl = getattr(self, "_lbl_dgen_pa_png", None)
        if lbl is not None:
            lbl.setText(Path(png_rel).name if png_rel else "(aucun)")
            lbl.setToolTip(png_rel)

        cell_combo = getattr(self, "_combo_dgen_pa_cell_size", None)
        if cell_combo is not None:
            idx = cell_combo.findData(da.get("cell_size", "16x16"))
            cell_combo.blockSignals(True)
            cell_combo.setCurrentIndex(idx if idx >= 0 else 1)
            cell_combo.blockSignals(False)

        _mode_combo = getattr(self, "_combo_dgen_tileset_mode", None)
        if _mode_combo is not None:
            _tmode = str(da.get("tileset_mode", "full") or "full")
            _tmode_idx = _mode_combo.findData(_tmode)
            _mode_combo.blockSignals(True)
            _mode_combo.setCurrentIndex(_tmode_idx if _tmode_idx >= 0 else 0)
            _mode_combo.blockSignals(False)
            self._update_tile_role_mode_visibility()

        role_spins = getattr(self, "_dgen_pa_role_spins", {})
        tile_roles = da.get("tile_roles", {}) or {}
        for role_key, spin in role_spins.items():
            vals = tile_roles.get(role_key)
            if isinstance(vals, list):
                val = vals[0] if vals else -1
            elif vals is None:
                val = -1
            else:
                val = int(vals)
            spin.blockSignals(True)
            spin.setValue(max(-1, int(val)))
            spin.blockSignals(False)

        tbl_ene = getattr(self, "_tbl_dgen_pa_ene_pool", None)
        if tbl_ene is not None:
            tbl_ene.blockSignals(True)
            tbl_ene.setRowCount(0)
            for entry in (da.get("enemy_pool") or []):
                if not isinstance(entry, dict):
                    continue
                r = tbl_ene.rowCount()
                tbl_ene.insertRow(r)
                tbl_ene.setItem(r, 0, QTableWidgetItem(str(entry.get("entity_id", ""))))
                tbl_ene.setItem(r, 1, QTableWidgetItem(str(entry.get("weight", 1))))
                tbl_ene.setItem(r, 2, QTableWidgetItem(str(entry.get("max_count", 4))))
                _beh = str(entry.get("behavior", "auto") or "auto")
                _arg = entry.get("behavior_arg", None)
                _beh_combo = self._make_dgen_behavior_combo(
                    behavior=_beh,
                    on_change=None,
                )
                _arg_spin = self._make_dgen_behavior_param_spin(
                    behavior=_beh,
                    value=_arg,
                    on_change=self._save_procgen_assets_state,
                )
                tbl_ene.setCellWidget(r, 3, _beh_combo)
                tbl_ene.setCellWidget(r, 4, _arg_spin)
                _beh_combo.currentIndexChanged.connect(
                    lambda _, _combo=_beh_combo, _spin=_arg_spin: (
                        self._sync_dgen_behavior_param_spin(str(_combo.currentData() or "auto"), _spin),
                        self._save_procgen_assets_state()
                    )
                )
            tbl_ene.blockSignals(False)

        tbl_item = getattr(self, "_tbl_dgen_pa_item_pool", None)
        if tbl_item is not None:
            tbl_item.blockSignals(True)
            tbl_item.setRowCount(0)
            for entry in (da.get("item_pool") or []):
                if not isinstance(entry, dict):
                    continue
                r = tbl_item.rowCount()
                tbl_item.insertRow(r)
                tbl_item.setItem(r, 0, QTableWidgetItem(str(entry.get("entity_id", ""))))
                tbl_item.setItem(r, 1, QTableWidgetItem(str(entry.get("weight", 1))))
                tbl_item.setItem(r, 2, QTableWidgetItem(str(entry.get("max_count", 1))))
            tbl_item.blockSignals(False)

        self._refresh_dgen_pa_preview()

    def _refresh_dgen_pa_preview(self) -> None:
        """Redraw the tileset PNG preview with grid overlay and cell index labels."""
        from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QFont, QFontMetrics
        from PyQt6.QtCore import Qt as _Qt

        lbl = getattr(self, "_dgen_pa_preview", None)
        if lbl is None:
            return

        png_rel = str(getattr(self, "_dgen_pa_png_rel", "") or "").strip()
        if not png_rel:
            lbl.setText("<span style='color:#555; font-size:10px;'>Charger un PNG pour voir l'aperçu…</span>")
            lbl.setTextFormat(_Qt.TextFormat.RichText)
            lbl.setPixmap(QPixmap())
            return

        png_path = Path(png_rel) if Path(png_rel).is_absolute() else None
        if png_path is None and self._base_dir:
            png_path = self._base_dir / png_rel
        if png_path is None or not png_path.exists():
            lbl.setText(f"<span style='color:#a55; font-size:10px;'>PNG introuvable : {png_rel}</span>")
            lbl.setTextFormat(_Qt.TextFormat.RichText)
            lbl.setPixmap(QPixmap())
            return

        cell_combo = getattr(self, "_combo_dgen_pa_cell_size", None)
        cell_size_key = str(cell_combo.currentData() or "16x16") if cell_combo else "16x16"
        cell_px = {"8x8": 8, "16x16": 16, "32x32": 32}.get(cell_size_key, 16)

        src = QPixmap(str(png_path))
        if src.isNull():
            lbl.setText(f"<span style='color:#a55; font-size:10px;'>Impossible de charger le PNG.</span>")
            lbl.setTextFormat(_Qt.TextFormat.RichText)
            lbl.setPixmap(QPixmap())
            return

        img_w = src.width()
        img_h = src.height()

        if cell_px > img_w or cell_px > img_h:
            lbl.setText(
                f"<span style='color:#a55; font-size:10px;'>"
                f"PNG {img_w}×{img_h}px trop petit pour cell_size={cell_size_key}.</span>"
            )
            lbl.setTextFormat(_Qt.TextFormat.RichText)
            lbl.setPixmap(QPixmap())
            return

        n_cols = max(1, img_w // cell_px)
        n_rows = max(1, img_h // cell_px)

        TARGET_CELL_DISP = 40
        MAX_W = 560
        MAX_SCALE = 4.0

        scale_for_target = TARGET_CELL_DISP / cell_px
        scale_for_maxw   = MAX_W / img_w
        scale = min(scale_for_target, scale_for_maxw, MAX_SCALE)
        scale = max(scale, 0.5)

        disp_w    = max(1, int(img_w * scale))
        disp_h    = max(1, int(img_h * scale))
        cell_disp = max(1, int(cell_px * scale))

        canvas = QPixmap(disp_w, disp_h)
        canvas.fill(QColor("#1a1a26"))

        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        scaled_src = src.scaled(disp_w, disp_h,
                                _Qt.AspectRatioMode.IgnoreAspectRatio,
                                _Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap(0, 0, scaled_src)

        grid_pen = QPen(QColor(255, 200, 0, 160))
        grid_pen.setWidth(1)
        painter.setPen(grid_pen)
        for col in range(n_cols + 1):
            x = col * cell_disp
            painter.drawLine(x, 0, x, disp_h)
        for row in range(n_rows + 1):
            y = row * cell_disp
            painter.drawLine(0, y, disp_w, y)

        LABEL_THRESHOLD = 22
        if cell_disp >= LABEL_THRESHOLD:
            font_sz = max(7, min(10, cell_disp // 4))
            fnt = QFont("monospace", font_sz)
            fnt.setBold(True)
            painter.setFont(fnt)
            fm = QFontMetrics(fnt)
            th = fm.ascent()

            for row in range(n_rows):
                for col in range(n_cols):
                    idx = row * n_cols + col
                    txt = str(idx)
                    x0 = col * cell_disp + 2
                    y0 = row * cell_disp + th + 1
                    painter.setPen(QColor(0, 0, 0, 210))
                    painter.drawText(x0 + 1, y0 + 1, txt)
                    painter.setPen(QColor(255, 230, 50))
                    painter.drawText(x0, y0, txt)

        painter.end()

        lbl.setPixmap(canvas)
        lbl.setTextFormat(_Qt.TextFormat.PlainText)
        lbl.setMinimumHeight(min(disp_h, 320))
        lbl.setMaximumHeight(max(disp_h + 4, 120))

    # ------------------------------------------------------------------
    # Procedural generation
    # ------------------------------------------------------------------

    def _do_procgen(self) -> None:
        if self._scene is None:
            QMessageBox.warning(self, tr("level.procgen_title"),
                                tr("level.no_project_context"))
            return
        if not self._type_names:
            QMessageBox.information(self, tr("level.procgen_title"),
                                    tr("level.procgen_no_types"))
            return

        seed         = self._spin_seed.value()
        margin       = self._spin_margin.value()
        enemy_dens   = self._spin_enemy_dens.value() / 100.0
        item_dens    = self._spin_item_dens.value() / 100.0
        mode         = self._combo_map_mode.currentData()

        rng  = random.Random(seed)
        gw, gh = self._grid_w, self._grid_h

        # Snapshot BEFORE any changes so Ctrl+Z restores the pre-generation state
        self._push_undo()

        # Generate/update collision map depending on mode
        if mode == "platformer":
            self._col_map = self._gen_platformer(rng, gw, gh)
        elif mode == "topdown":
            _dir_walls = bool(self._chk_dir_walls.isChecked())
            _gen_water = bool(self._chk_td_water.isChecked())
            _bn = bool(self._chk_td_border_n.isChecked())
            _bs = bool(self._chk_td_border_s.isChecked())
            _be = bool(self._chk_td_border_e.isChecked())
            _bw = bool(self._chk_td_border_w.isChecked())
            _td_mode = self._combo_td_gen_mode.currentData() or "scatter"
            _corridor_w = 1  # overridden in BSP branch

            if _td_mode == "bsp":
                _out_w = self._spin_td_bsp_out_w.value()
                _out_h = self._spin_td_bsp_out_h.value()
                bsp_gw = _out_w if _out_w >= 6 else gw
                bsp_gh = _out_h if _out_h >= 6 else gh
                _sprite_sz = self._spin_td_bsp_sprite.value()
                _corridor_w = _sprite_sz + 1
                col = self._gen_topdown_bsp(
                    rng, bsp_gw, bsp_gh,
                    gen_water=_gen_water,
                    border_n=_bn, border_s=_bs, border_e=_be, border_w=_bw,
                    bsp_depth=self._spin_td_bsp_depth.value(),
                    loop_pct=self._spin_td_loop_pct.value(),
                    corridor_w=_corridor_w,
                )
                if bsp_gw != gw or bsp_gh != gh:
                    gw, gh = bsp_gw, bsp_gh
                    self._grid_w, self._grid_h = gw, gh
                    self._spin_gw.blockSignals(True)
                    self._spin_gh.blockSignals(True)
                    self._spin_gw.setValue(gw)
                    self._spin_gh.setValue(gh)
                    self._spin_gw.blockSignals(False)
                    self._spin_gh.blockSignals(False)
                    self._on_size_changed()
            else:
                _scat_w = int(self._spin_td_scatter_out_w.value())
                _scat_h = int(self._spin_td_scatter_out_h.value())
                # Clamp to hardware safe range: [screen, 32]
                _scat_w = max(_SCREEN_W, min(32, _scat_w))
                _scat_h = max(_SCREEN_H, min(32, _scat_h))
                scat_gw, scat_gh = _scat_w, _scat_h
                col = self._gen_topdown(
                    rng, scat_gw, scat_gh,
                    dir_walls=False,        # applied below after flood-fix
                    wall_dens=self._spin_wall_dens.value() / 100.0,
                    gen_int_walls=bool(self._chk_td_int_walls.isChecked()),
                    gen_water=_gen_water,
                    border_n=_bn, border_s=_bs, border_e=_be, border_w=_bw,
                )
                if self._chk_td_ca.isChecked():
                    self._td_cellular_smooth(col, scat_gw, scat_gh)
                if scat_gw != gw or scat_gh != gh:
                    gw, gh = scat_gw, scat_gh
                    self._grid_w, self._grid_h = gw, gh
                    self._spin_gw.blockSignals(True)
                    self._spin_gh.blockSignals(True)
                    self._spin_gw.setValue(gw)
                    self._spin_gh.setValue(gh)
                    self._spin_gw.blockSignals(False)
                    self._spin_gh.blockSignals(False)
                    self._on_size_changed()

            # Shared post-processing for both modes
            _flood_cw = _corridor_w if _td_mode == "bsp" else 1
            self._td_flood_fix(col, gw, gh, rng, corridor_w=_flood_cw)
            if _dir_walls:
                self._apply_dir_walls(col, gw, gh)
                # Border corners: only assign if both adjacent border tiles are
                # already directional (wall/corner), so BSP maps with solid-only
                # borders don't get phantom corner tiles at the 4 screen edges.
                _dw = {_TCOL_WALL_N, _TCOL_WALL_S, _TCOL_WALL_E, _TCOL_WALL_W,
                       _TCOL_CORNER_NE, _TCOL_CORNER_NW, _TCOL_CORNER_SE, _TCOL_CORNER_SW}
                if _bn and _bw and col[0][1] in _dw and col[1][0] in _dw:
                    col[0][0] = _TCOL_CORNER_SE
                if _bn and _be and col[0][gw-2] in _dw and col[1][gw-1] in _dw:
                    col[0][gw-1] = _TCOL_CORNER_SW
                if _bs and _bw and col[gh-1][1] in _dw and col[gh-2][0] in _dw:
                    col[gh-1][0] = _TCOL_CORNER_NE
                if _bs and _be and col[gh-1][gw-2] in _dw and col[gh-2][gw-1] in _dw:
                    col[gh-1][gw-1] = _TCOL_CORNER_NW
            self._col_map = col
        elif mode == "shmup":
            self._col_map = self._gen_shmup(rng, gw, gh)
        elif mode == "open":
            dens = self._spin_open_dens.value() / 100.0
            self._col_map = self._gen_open(rng, gw, gh, dens)
        else:
            self._col_map = None
        self._clear_col_map_import_meta()
        self._refresh_collision_source_ui()

        def _type_footprint(type_name: str) -> tuple[int, int]:
            w_px, h_px = self._type_sizes.get(type_name, (_TILE_PX, _TILE_PX))
            w_tiles = max(1, (int(w_px) + _TILE_PX - 1) // _TILE_PX)
            h_tiles = max(1, (int(h_px) + _TILE_PX - 1) // _TILE_PX)
            return int(w_tiles), int(h_tiles)

        def _apply_rules_xy(tx: int, ty: int, *, type_name: str, in_wave: bool) -> tuple[int, int]:
            rules = getattr(self, "_level_rules", {}) or {}
            if not isinstance(rules, dict):
                return tx, ty
            if in_wave and not bool(rules.get("apply_to_waves", True)):
                return tx, ty

            if bool(rules.get("lock_y_en", False)):
                try:
                    ty = int(rules.get("lock_y", ty))
                except Exception:
                    pass

            if bool(rules.get("ground_band_en", False)):
                try:
                    gmin = int(rules.get("ground_min_y", 0))
                    gmax = int(rules.get("ground_max_y", self._grid_h - 1))
                    if gmin > gmax:
                        gmax = gmin
                    ty = max(gmin, min(gmax, ty))
                except Exception:
                    pass

            w_tiles, h_tiles = _type_footprint(type_name)
            tx = max(0, min(int(gw - w_tiles), int(tx)))
            ty = max(0, min(int(gh - h_tiles), int(ty)))
            return int(tx), int(ty)

        # Candidate anchor positions (when a map exists, only on passable tiles)
        all_pos: list[tuple[int, int]] = []
        for y in range(margin, gh - margin):
            for x in range(margin, gw - margin):
                if self._col_map is None or self._col_map[y][x] == _TCOL_PASS:
                    all_pos.append((x, y))

        # Exclude no-spawn regions (kind=no_spawn)
        no_spawn: set[tuple[int, int]] = set()
        for r in self._regions:
            try:
                if str(r.get("kind", "zone") or "zone") != "no_spawn":
                    continue
                rx = int(r.get("x", 0))
                ry = int(r.get("y", 0))
                rw = max(1, int(r.get("w", 1)))
                rh = max(1, int(r.get("h", 1)))
            except Exception:
                continue
            for ty in range(max(0, ry), min(gh, ry + rh)):
                for tx in range(max(0, rx), min(gw, rx + rw)):
                    no_spawn.add((tx, ty))

        filtered = [p for p in all_pos if p not in no_spawn]
        filtered_out = len(all_pos) - len(filtered)
        all_pos = filtered

        if not all_pos:
            QMessageBox.warning(self, tr("level.procgen_title"),
                                tr("level.procgen_no_space"))
            self._canvas.update()
            return

        rng.shuffle(all_pos)
        used_tiles: set[tuple[int, int]] = set()

        def _footprint_tiles(tx: int, ty: int, w_tiles: int, h_tiles: int) -> list[tuple[int, int]]:
            return [(tx + dx, ty + dy) for dy in range(h_tiles) for dx in range(w_tiles)]

        def _can_place(type_name: str, tx: int, ty: int) -> bool:
            w_tiles, h_tiles = _type_footprint(type_name)
            if tx < 0 or ty < 0 or tx + w_tiles > gw or ty + h_tiles > gh:
                return False

            # Footprint must not overlap no-spawn, collisions, or other entities.
            for fx, fy in _footprint_tiles(tx, ty, w_tiles, h_tiles):
                if (fx, fy) in no_spawn:
                    return False
                if (fx, fy) in used_tiles:
                    return False
                if self._col_map is not None:
                    try:
                        if int(self._col_map[fy][fx]) != _TCOL_PASS:
                            return False
                    except Exception:
                        return False
            return True

        def _mark_used(type_name: str, tx: int, ty: int) -> None:
            w_tiles, h_tiles = _type_footprint(type_name)
            for fx, fy in _footprint_tiles(tx, ty, w_tiles, h_tiles):
                used_tiles.add((fx, fy))

        def _pick_for_type(type_name: str, *, prefer: str = "any") -> Optional[tuple[int, int]]:
            # prefer: "any" | "player"
            cand: list[tuple[int, int]] = []
            if prefer == "player":
                # Build a short preferred candidate list first (depends on map mode).
                for tx, ty in all_pos:
                    tx2, ty2 = _apply_rules_xy(tx, ty, type_name=type_name, in_wave=False)
                    if _can_place(type_name, tx2, ty2):
                        cand.append((tx2, ty2))
                if not cand:
                    return None
                if mode == "platformer":
                    cand.sort(key=lambda p: (p[0], -p[1]))  # left, then bottom
                elif mode == "shmup":
                    cx = gw // 2
                    cand.sort(key=lambda p: (abs(p[0] - cx), -p[1]))  # center, then bottom
                else:  # topdown/open/none
                    cx, cy = gw // 2, gh // 2
                    cand.sort(key=lambda p: (abs(p[0] - cx) + abs(p[1] - cy), p[0], p[1]))
                # Pick among the best few to avoid always identical layouts for the same seed+rules.
                best = cand[: min(12, len(cand))]
                return rng.choice(best) if best else cand[0]

            # Generic: first fit found in shuffled order.
            for tx, ty in all_pos:
                tx2, ty2 = _apply_rules_xy(tx, ty, type_name=type_name, in_wave=False)
                if _can_place(type_name, tx2, ty2):
                    return (tx2, ty2)
            return None

        # Group types by role
        by_role: dict[str, list[str]] = {r: [] for r in _ROLES}
        for t in self._type_names:
            by_role[self._entity_roles.get(t, "prop")].append(t)

        new_entities: list[dict] = []

        # 1 player
        if by_role["player"]:
            t = rng.choice(by_role["player"])
            pos = _pick_for_type(t, prefer="player")
            if pos:
                new_entities.append(self._make_entity(t, pos[0], pos[1]))
                _mark_used(t, pos[0], pos[1])

        # N enemies
        if by_role["enemy"]:
            n_en = int(len(all_pos) * enemy_dens)
            if enemy_dens > 0 and n_en == 0:
                n_en = 1
            for _ in range(n_en):
                t = rng.choice(by_role["enemy"])
                pos = _pick_for_type(t)
                if pos is None:
                    break
                new_entities.append(self._make_entity(t, pos[0], pos[1]))
                _mark_used(t, pos[0], pos[1])

        # M items
        if by_role["item"]:
            n_it = int(len(all_pos) * item_dens)
            if item_dens > 0 and n_it == 0:
                n_it = 1
            for _ in range(n_it):
                t = rng.choice(by_role["item"])
                pos = _pick_for_type(t)
                if pos is None:
                    break
                new_entities.append(self._make_entity(t, pos[0], pos[1]))
                _mark_used(t, pos[0], pos[1])

        # 1 per NPC and trigger type
        for role in ("npc", "trigger"):
            for t in by_role[role]:
                pos = _pick_for_type(t)
                if pos:
                    new_entities.append(self._make_entity(t, pos[0], pos[1]))
                    _mark_used(t, pos[0], pos[1])

        self._entities = new_entities
        self._selected = -1

        # Optional: generate tilemap PNGs for SCR1/SCR2 (stored as scene tilemaps).
        if (self._col_map is not None
                and mode in _MAP_MODE_ROLES
                and bool(getattr(self, "_chk_gen_tilemaps", None) and self._chk_gen_tilemaps.isChecked())
                and (bool(getattr(self, "_chk_gen_scr1", None) and self._chk_gen_scr1.isChecked())
                     or bool(getattr(self, "_chk_gen_scr2", None) and self._chk_gen_scr2.isChecked()))):
            try:
                self._procgen_write_tilemaps(seed=seed, map_mode=mode, col_map=self._col_map, gw=gw, gh=gh)
            except Exception as exc:
                QMessageBox.warning(self, tr("level.procgen_title"), tr("level.procgen_tilemap_failed", err=str(exc)))

        self._canvas.update()
        self._on_entity_placed()
        extra = tr("level.procgen_no_spawn_note", n=filtered_out) if filtered_out else ""
        self._lbl_status.setText(tr("level.procgen_done", n=len(new_entities), seed=seed, extra=extra))

    def _procgen_pick_tile_source_path(self) -> Path | None:
        """Return a tile source PNG path (used to sample 8×8 tiles), or None."""
        if self._base_dir is None:
            return None
        choice = "auto"
        try:
            choice = str(self._combo_tile_src.currentData() or "auto")
        except Exception:
            choice = "auto"

        def _sel_path(which: str) -> Path | None:
            try:
                idx = int(self._combo_bg_scr1.currentIndex()) if which == "scr1" else int(self._combo_bg_scr2.currentIndex())
            except Exception:
                idx = 0
            if not (0 <= idx < len(self._bg_paths)):
                return None
            p = self._bg_paths[idx]
            return p if isinstance(p, Path) else None

        if choice == "scr1":
            return _sel_path("scr1")
        if choice == "scr2":
            return _sel_path("scr2")
        # auto
        p1 = _sel_path("scr1")
        if p1 is not None:
            return p1
        return _sel_path("scr2")

    def _procgen_output_dir(self) -> Path:
        """Pick an output directory for generated tilemaps (best-effort)."""
        base = self._base_dir or Path(".")
        # Prefer the first existing scene tilemap's folder.
        try:
            tilemaps = (self._scene or {}).get("tilemaps", []) or []
            for tm in tilemaps:
                if not isinstance(tm, dict):
                    continue
                rel = str(tm.get("file", "") or "").strip()
                if not rel:
                    continue
                p = Path(rel)
                if self._base_dir and not p.is_absolute():
                    p = self._base_dir / p
                return p.parent
        except Exception:
            pass
        # Fallback to GraphX/src if it exists, else GraphX, else base.
        cand = base / "GraphX" / "src"
        if cand.exists():
            return cand
        cand = base / "GraphX"
        if cand.exists():
            return cand
        return base

    def _procgen_add_tilemap_to_scene(self, rel: str, plane: str) -> None:
        if self._scene is None:
            return
        tms = self._scene.get("tilemaps", []) or []
        if not isinstance(tms, list):
            tms = []
        # Update existing entry if present, else append.
        for tm in tms:
            if isinstance(tm, dict) and str(tm.get("file", "") or "") == rel:
                tm["plane"] = plane
                self._scene["tilemaps"] = tms
                return
        tms.append({"file": rel, "plane": plane})
        self._scene["tilemaps"] = tms

    def _procgen_write_tilemaps(self, *, seed: int, map_mode: str, col_map: list[list[int]], gw: int, gh: int) -> None:
        """Generate SCR1/SCR2 tilemap PNGs from the collision map and role→tile mapping."""
        src_path = self._procgen_pick_tile_source_path()
        if src_path is None or (not src_path.exists()):
            raise RuntimeError(tr("level.procgen_tilemap_need_bg"))

        try:
            from PIL import Image as _PILImg
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc

        src_img = _PILImg.open(src_path).convert("RGBA")
        tw = int(src_img.width // _TILE_PX)
        th = int(src_img.height // _TILE_PX)
        if tw <= 0 or th <= 0:
            raise RuntimeError(tr("level.procgen_tilemap_bad_src"))

        # Build collision->role map for visual tiles.
        tcol_to_role: dict[int, str] = {tcol: role_key for role_key, tcol, _lbl in _MAP_MODE_ROLES.get(map_mode, [])}
        role_to_tid = (self._tile_ids or {}).get(map_mode, {}) if isinstance(self._tile_ids, dict) else {}

        def _tile_idx_for_tcol(tcol: int, *, x: int, y: int) -> int:
            rk = tcol_to_role.get(int(tcol), "empty")
            return _tile_id_pick(role_to_tid.get(rk, int(tcol)), default=int(tcol), x=x, y=y, salt=seed)

        # Cache tile crops by tile index (significant speedup).
        tile_cache: dict[int, object] = {}

        def _get_tile(tile_idx: int):
            ti = int(tile_idx)
            if ti in tile_cache:
                return tile_cache[ti]
            if ti < 0:
                ti = 0
            tx = ti % tw
            ty = ti // tw
            if ty < 0 or ty >= th:
                tx, ty = 0, 0
            x0 = tx * _TILE_PX
            y0 = ty * _TILE_PX
            tile = src_img.crop((x0, y0, x0 + _TILE_PX, y0 + _TILE_PX))
            tile_cache[int(tile_idx)] = tile
            return tile

        out_img = _PILImg.new("RGBA", (int(gw) * _TILE_PX, int(gh) * _TILE_PX), (0, 0, 0, 0))
        for y in range(int(gh)):
            row = col_map[y] if y < len(col_map) else []
            for x in range(int(gw)):
                tcol = int(row[x]) if x < len(row) else 0
                tid = _tile_idx_for_tcol(tcol, x=x, y=y)
                out_img.paste(_get_tile(tid), (int(x) * _TILE_PX, int(y) * _TILE_PX))

        out_dir = self._procgen_output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        scene_name = str((self._scene or {}).get("name", "") or (self._scene or {}).get("label", "") or "scene")
        safe_scene = re.sub(r"[^a-zA-Z0-9]+", "_", scene_name).strip("_").lower() or "scene"
        safe_mode = re.sub(r"[^a-zA-Z0-9]+", "_", str(map_mode or "map")).strip("_").lower() or "map"

        def _write(plane: str) -> tuple[Path, str]:
            fname = f"{safe_scene}_{safe_mode}_seed{int(seed)}_{plane}.png"
            p = out_dir / fname
            # Avoid overwriting: add numeric suffix.
            if p.exists():
                for i in range(2, 9999):
                    cand = out_dir / f"{safe_scene}_{safe_mode}_seed{int(seed)}_{plane}_{i}.png"
                    if not cand.exists():
                        p = cand
                        break
            out_img.save(p)
            rel = p
            if self._base_dir is not None:
                try:
                    rel = p.relative_to(self._base_dir)
                except Exception:
                    rel = p
            rel_s = Path(rel).as_posix()
            self._procgen_add_tilemap_to_scene(rel_s, plane)
            return p, rel_s

        created: list[tuple[str, int]] = []
        if self._chk_gen_scr1.isChecked():
            _p, rel = _write("scr1")
            created.append(("scr1", self._ensure_bg_item(rel, _p)))
            self._combo_bg_scr1.setCurrentIndex(created[-1][1])
            self._on_bg_scr1_changed(created[-1][1])
        if self._chk_gen_scr2.isChecked():
            _p, rel = _write("scr2")
            created.append(("scr2", self._ensure_bg_item(rel, _p)))
            self._combo_bg_scr2.setCurrentIndex(created[-1][1])
            self._on_bg_scr2_changed(created[-1][1])

    # ------------------------------------------------------------------
    # Procgen config header export (DFS + Cave)
    # ------------------------------------------------------------------

    def _procgen_gen_dir(self) -> Path:
        """Return the gen output dir (GraphX/gen/ or base dir fallback)."""
        base = self._base_dir or Path(".")
        cand = base / "GraphX" / "gen"
        cand.mkdir(parents=True, exist_ok=True)
        return cand

    def _export_dfs_config(self) -> None:
        """Write GraphX/gen/procgen_config.h from the DFS sub-tab params."""
        try:
            gen_dir = self._procgen_gen_dir()

            grid_w = self._spin_dfs_grid_w.value()
            grid_h = self._spin_dfs_grid_h.value()
            max_enemies = self._spin_dfs_max_enemies.value()
            item_chance = self._spin_dfs_item_chance.value()
            loop_pct    = self._spin_dfs_loop_pct.value()
            max_active  = self._spin_dfs_max_active.value()
            start_mode_map = {"corner": 0, "random": 1, "far_exit": 2}
            start_mode  = start_mode_map.get(
                self._combo_dfs_start_mode.currentData() or "corner", 0)
            multifloor  = self._chk_dfs_multifloor.isChecked()
            floor_var   = self._spin_dfs_floor_var.value()
            max_floors  = self._spin_dfs_max_floors.value()
            boss_scene  = str(self._combo_dfs_boss_scene.currentData() or "")

            # Read tier table (4 rows × 5 cols)
            tier_rows = []
            for r in range(4):
                row_vals = []
                for c in range(5):
                    item = self._dfs_tier_table.item(r, c)
                    try:
                        row_vals.append(int(item.text()) if item else 0)
                    except ValueError:
                        row_vals.append(0)
                tier_rows.append(row_vals)

            def _arr(vals: list) -> str:
                return "{" + ", ".join(str(v) for v in vals) + "}"

            lines = [
                "/* procgen_config.h — auto-generated by NgpCraft Engine */",
                "/* DO NOT EDIT — re-export from Level > Procgen > Dungeon DFS */",
                "#ifndef PROCGEN_CONFIG_H",
                "#define PROCGEN_CONFIG_H",
                "",
                f"#define PROCGEN_GRID_W          {grid_w}",
                f"#define PROCGEN_GRID_H          {grid_h}",
                f"#define PROCGEN_MAX_ENEMIES     {max_enemies}",
                f"#define PROCGEN_ITEM_CHANCE     {item_chance}",
                f"#define PROCGEN_LOOP_PCT        {loop_pct}",
                f"#define PROCGEN_MAX_ACTIVE      {max_active}",
                f"#define PROCGEN_START_MODE      {start_mode}",
                f"#define PROCGEN_MULTIFLOOR      {1 if multifloor else 0}",
                f"#define PROCGEN_FLOOR_VAR       {floor_var}",
                f"#define PROCGEN_MAX_FLOORS      {max_floors}",
                "",
                "/* Tier table — index by (game_var[FLOOR] / 5), clamped to 4 */",
                f"#define PROCGEN_TIER_MAX_ENEMIES    {_arr(tier_rows[0])}",
                f"#define PROCGEN_TIER_ITEM_CHANCE    {_arr(tier_rows[1])}",
                f"#define PROCGEN_TIER_LOOP_PCT       {_arr(tier_rows[2])}",
                f"#define PROCGEN_TIER_MAX_ACTIVE     {_arr(tier_rows[3])}",
            ]

            if multifloor and boss_scene:
                lines += [
                    "",
                    f'/* Boss/end scene ID — use with ngpc_goto_scene() */',
                    f'#define PROCGEN_BOSS_SCENE_ID   "{boss_scene}"',
                ]

            lines += ["", "#endif /* PROCGEN_CONFIG_H */", ""]

            out = gen_dir / "procgen_config.h"
            out.write_text("\n".join(lines), encoding="utf-8")
            QMessageBox.information(self, "Export", f"Written: {out}")
        except Exception as exc:
            QMessageBox.critical(self, "Export error", str(exc))

    def _export_cave_config(self) -> None:
        """Write GraphX/gen/cavegen_config.h from the Cave sub-tab params."""
        try:
            from core.procgen_config_gen import write_cavegen_config_h
            # Save current UI state to scene first so the generator sees up-to-date data
            self._store_scene_state(save_project=False, update_status=False)
            gen_dir = self._procgen_gen_dir()
            out = write_cavegen_config_h(
                scene=self._scene or {},
                export_dir=gen_dir,
                project_data=self._project_data_root,
            )
            QMessageBox.information(self, "Export", f"Written: {out}")
            return
        except Exception as exc:
            QMessageBox.critical(self, "Export error", str(exc))
            return

    def _refresh_procgen_scene_combos(self) -> None:
        """Repopulate boss/loop scene combos in DFS and Cave sub-tabs."""
        # (combo, empty_label) — loop_scene uses "same scene" semantics
        entries = [
            (getattr(self, "_combo_dfs_boss_scene",  None), "(none)"),
            (getattr(self, "_combo_dfs_loop_scene",  None), "(same scene)"),
            (getattr(self, "_combo_cave_boss_scene", None), "(none)"),
        ]
        for combo, empty_label in entries:
            if combo is None:
                continue
            cur = str(combo.currentData() or "")
            combo.blockSignals(True)
            try:
                combo.clear()
                combo.addItem(empty_label, "")
                for s in getattr(self, "_project_scenes", []):
                    sid   = str(s.get("id") or "").strip()
                    label = str(s.get("label") or sid)
                    if sid:
                        combo.addItem(label, sid)
                idx = combo.findData(cur)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
            finally:
                combo.blockSignals(False)

    def _ensure_bg_item(self, rel: str, abs_path: Path) -> int:
        """Ensure (rel, abs_path) is present in BG combo lists; return index."""
        rel_norm = str(rel).replace("\\", "/")
        for i, r in enumerate(self._bg_rels):
            if r is not None and str(r).replace("\\", "/") == rel_norm:
                return int(i)
        self._bg_paths.append(abs_path)
        self._bg_rels.append(rel)
        self._combo_bg_scr1.addItem(abs_path.name)
        self._combo_bg_scr2.addItem(abs_path.name)
        return len(self._bg_rels) - 1

    # ------------------------------------------------------------------
    # Budget
    # ------------------------------------------------------------------

    def _update_budget(self) -> None:
        n_static = len(self._entities)
        n_wave   = sum(len(w.get("entities", [])) for w in self._waves)
        self._lbl_budget.setText(
            tr("level.budget", n=n_static, nw=n_wave, max=64))
        self._rebuild_oam_view()
        self._update_diagnostics()

    # ------------------------------------------------------------------
    # X-3 — OAM viewer
    # ------------------------------------------------------------------

    def _oam_parts_for_type(self, type_name: str) -> tuple[int, int, int]:
        """Return (hw_parts, frame_w, frame_h) for one entity of this type."""
        spr = self._sprite_meta_for_type(str(type_name or ""))
        if spr:
            fw = max(1, int(spr.get("frame_w", 8) or 8))
            fh = max(1, int(spr.get("frame_h", 8) or 8))
        else:
            fw, fh = self._type_sizes.get(str(type_name or ""), (8, 8))
        cols = max(1, (fw + 7) // 8)
        rows = max(1, (fh + 7) // 8)
        return cols * rows, fw, fh

    def _rebuild_oam_view(self) -> None:
        if not hasattr(self, "_oam_canvas"):
            return
        # Worst-case: static entities + all wave entities at same time
        all_ents: list[dict] = list(self._entities or [])
        for w in (self._waves or []):
            all_ents.extend(w.get("entities", []) or [])

        # Build per-slot allocation list
        OAM_MAX = _OAM_SLOTS
        slot_data: list[tuple[str, str]] = []  # (color_hex, tooltip)
        table_rows: list[tuple[int, str, str, int]] = []  # slot_start, type, dims, parts

        slot_cursor = 0
        role_map = self._entity_roles or {}

        for ent in all_ents:
            t = str(ent.get("type", "") or "")
            parts, fw, fh = self._oam_parts_for_type(t)
            role = str(role_map.get(t, "prop") or "prop").lower()
            color = _OAM_ROLE_COLORS.get(role, _OAM_ROLE_COLORS["prop"])
            slot_start = slot_cursor
            for _ in range(parts):
                if slot_cursor >= OAM_MAX:
                    slot_data.append((_OAM_OVERFLOW_COLOR, f"{t} (overflow)"))
                else:
                    slot_data.append((color, f"{t} {fw}×{fh} [{role}]"))
                slot_cursor += 1
            table_rows.append((slot_start, t, f"{fw}×{fh}", parts))

        # Pad empty slots
        while len(slot_data) < OAM_MAX:
            slot_data.append((_OAM_EMPTY_COLOR, ""))

        self._oam_canvas.set_slots(slot_data)

        total = min(slot_cursor, OAM_MAX + slot_cursor - OAM_MAX) if slot_cursor > OAM_MAX else slot_cursor
        overflow = max(0, slot_cursor - OAM_MAX)
        if overflow > 0:
            self._lbl_oam_total.setStyleSheet("color: #e05050; font-weight: bold;")
            self._lbl_oam_total.setText(
                tr("level.oam_total_overflow", used=slot_cursor, max=OAM_MAX, over=overflow))
        else:
            pct = int(slot_cursor * 100 / OAM_MAX) if OAM_MAX else 0
            color = "#f0c040" if pct >= 75 else "#75d17f"
            self._lbl_oam_total.setStyleSheet(f"color: {color};")
            self._lbl_oam_total.setText(tr("level.oam_total", used=slot_cursor, max=OAM_MAX))

        # Update table
        self._tbl_oam.setRowCount(0)
        for slot_start, tname, dims, parts in table_rows:
            row = self._tbl_oam.rowCount()
            self._tbl_oam.insertRow(row)
            slot_lbl = f"{slot_start}–{slot_start + parts - 1}" if parts > 1 else str(slot_start)
            role = str(role_map.get(tname, "prop") or "prop").lower()
            color_hex = _OAM_ROLE_COLORS.get(role, _OAM_ROLE_COLORS["prop"])
            fg = QColor(color_hex)
            for c_idx, txt in enumerate((slot_lbl, tname, dims, str(parts))):
                item = QTableWidgetItem(txt)
                item.setForeground(fg)
                self._tbl_oam.setItem(row, c_idx, item)

    def _diag_join_labels(self, names: list[str], *, limit: int = 4) -> str:
        vals = [str(n).strip() for n in names if str(n).strip()]
        if len(vals) <= limit:
            return ", ".join(vals)
        return ", ".join(vals[:limit]) + tr("level.diag_more_suffix", n=len(vals) - limit)

    def _diag_check_html(self, label: str, state: str, detail: str = "") -> str:
        if state == "ok":
            icon = "&#10003;"
            color = "#75d17f"
        elif state == "na":
            icon = "&#8212;"
            color = "#8a929b"
        else:
            icon = "&#9888;"
            color = "#f0b44c"
        tail = f" <span style='color:#9aa3ad;'>({detail})</span>" if detail else ""
        return f"<span style='color:{color};'>{icon}</span> <b>{label}</b>{tail}"

    def _profile_label(self, profile: str) -> str:
        key = dict(_LEVEL_PROFILES).get(str(profile or "").strip(), "")
        return tr(key) if key else str(profile or "none")

    def _map_mode_label(self, mode: str) -> str:
        key = dict(_MAP_MODES).get(str(mode or "").strip(), "")
        return tr(key) if key else str(mode or "none")

    def _update_diagnostics(self) -> None:
        blockers: list[str] = []
        hints: list[str] = []

        # Player presence
        player_types = {t for t, r in (self._entity_roles or {}).items() if r == "player"}
        has_player = any(e.get("type") in player_types for e in (self._entities or []))
        if not has_player:
            for w in (self._waves or []):
                for e in (w.get("entities", []) or []):
                    if e.get("type") in player_types:
                        has_player = True
                        break
                if has_player:
                    break
        if player_types and not has_player:
            blockers.append(tr("level.diag_missing_player"))

        mm = str(self._combo_map_mode.currentData() or "none")
        gen_tilemaps = bool(getattr(self, "_chk_gen_tilemaps", None) and self._chk_gen_tilemaps.isChecked())

        # Collision map presence/size when procgen mode enabled
        colmap_ok = True
        if mm != "none":
            if self._col_map is None:
                colmap_ok = False
                blockers.append(tr("level.diag_colmap_missing"))
            else:
                ok = (
                    isinstance(self._col_map, list)
                    and len(self._col_map) == int(self._grid_h)
                    and all(isinstance(r, list) and len(r) == int(self._grid_w) for r in self._col_map)
                )
                if not ok:
                    colmap_ok = False
                    blockers.append(tr("level.diag_colmap_size", w=int(self._grid_w), h=int(self._grid_h)))

        # Procgen visual mapping sanity when PNG generation is enabled
        procgen_mapping_ok = True
        procgen_mapping_used = (
            mm in _MAP_MODE_ROLES
            and gen_tilemaps
        )
        if procgen_mapping_used:
            role_map = (self._tile_ids or {}).get(mm, {}) if isinstance(self._tile_ids, dict) else {}
            missing_roles: list[str] = []
            pm_src, src_name = self._role_preview_source()
            atlas_tiles = 0
            if pm_src is None or pm_src.isNull():
                procgen_mapping_ok = False
                blockers.append(tr("level.diag_tile_source_missing"))
            else:
                try:
                    atlas_tiles = int(pm_src.width() // _TILE_PX) * int(pm_src.height() // _TILE_PX)
                except Exception:
                    atlas_tiles = 0
                if atlas_tiles <= 0:
                    procgen_mapping_ok = False
                    blockers.append(tr("level.diag_tile_source_missing"))
            for role_key, tcol, label_key in _MAP_MODE_ROLES.get(mm, []):
                if role_key not in role_map:
                    missing_roles.append(tr(label_key))
                ids = _tile_id_variants(role_map.get(role_key, tcol), tcol)
                if atlas_tiles > 0:
                    bad = [str(v) for v in ids if int(v) >= int(atlas_tiles)]
                    if bad:
                        procgen_mapping_ok = False
                        blockers.append(
                            tr(
                                "level.diag_tile_ids_oob",
                                role=tr(label_key),
                                values=", ".join(bad),
                                total=int(atlas_tiles),
                                name=(src_name or "atlas"),
                            )
                        )
            if missing_roles:
                procgen_mapping_ok = False
                blockers.append(tr("level.diag_tile_ids_missing", roles=self._diag_join_labels(missing_roles)))

        # Camera bounds sanity
        camera_ok = True
        try:
            max_cam_x = max(0, int(self._grid_w) - _SCREEN_W)
            max_cam_y = max(0, int(self._grid_h) - _SCREEN_H)
            cam_x = int(self._cam_tile[0])
            cam_y = int(self._cam_tile[1])
            if cam_x < 0 or cam_y < 0 or cam_x > max_cam_x or cam_y > max_cam_y:
                camera_ok = False
                blockers.append(tr("level.diag_cam_start_oob", max_x=max_cam_x, max_y=max_cam_y))
            if bool(self._chk_cam_clamp.isChecked()) and not bool(self._chk_cam_bounds_auto.isChecked()):
                min_x = int(self._spin_cam_min_x.value())
                min_y = int(self._spin_cam_min_y.value())
                max_x = int(self._spin_cam_max_x.value())
                max_y = int(self._spin_cam_max_y.value())
                if min_x > max_x or min_y > max_y:
                    camera_ok = False
                    blockers.append(tr("level.diag_cam_bounds_bad"))
                elif min_x < 0 or min_y < 0 or max_x > max_cam_x or max_y > max_cam_y:
                    camera_ok = False
                    blockers.append(tr("level.diag_cam_bounds_oob", max_x=max_cam_x, max_y=max_cam_y))
        except Exception:
            camera_ok = False

        # Rules sanity
        if bool(self._chk_rule_ground_band.isChecked()):
            try:
                gmin = int(self._spin_rule_ground_min.value())
                gmax = int(self._spin_rule_ground_max.value())
                if gmin > gmax:
                    blockers.append(tr("level.diag_rules_ground_bad"))
            except Exception:
                pass
        try:
            if str(self._combo_rule_hud_font.currentData() or "system") == "custom":
                hud_widgets = self._hud_widgets()
                has_value_widget = any(str(w.get("kind", "icon") or "icon") == "value" for w in hud_widgets if isinstance(w, dict))
                digit_names = list(self._level_rules.get("hud_custom_font_digits", [""] * 10) or [""] * 10)
                if has_value_widget and (len(digit_names) < 10 or any(not str(v).strip() for v in digit_names[:10])):
                    hints.append(tr("level.diag_hud_font_incomplete"))
            fixed_plane = str(self._combo_rule_hud_fixed_plane.currentData() or "none")
            if fixed_plane == "scr1" and int(self._combo_bg_scr1.currentIndex()) <= 0:
                hints.append(tr("level.diag_hud_fixed_plane_missing", plane="SCR1"))
            elif fixed_plane == "scr2" and int(self._combo_bg_scr2.currentIndex()) <= 0:
                hints.append(tr("level.diag_hud_fixed_plane_missing", plane="SCR2"))
            try:
                scroll_scene = (
                    (int(self._grid_w) > _SCREEN_W or int(self._grid_h) > _SCREEN_H)
                    and (bool(self._chk_scroll_x.isChecked()) or bool(self._chk_scroll_y.isChecked()))
                )
            except Exception:
                scroll_scene = False
            if scroll_scene:
                def _hint_small_plane_wrap(plane_name: str, pixmap: QPixmap | None, combo_idx: int, par_x: int, par_y: int) -> None:
                    if pixmap is None or combo_idx <= 0:
                        return
                    if fixed_plane == plane_name:
                        return
                    if par_x == 0 and par_y == 0:
                        return
                    if pixmap.width() > (_SCREEN_W * 8) or pixmap.height() > (_SCREEN_H * 8):
                        return
                    hints.append(
                        tr(
                            "level.diag_small_bg_wrap",
                            plane=plane_name.upper(),
                            w=max(1, int(pixmap.width()) // 8),
                            h=max(1, int(pixmap.height()) // 8),
                        )
                    )
                _hint_small_plane_wrap(
                    "scr1",
                    self._bg_pixmap_scr1,
                    int(self._combo_bg_scr1.currentIndex()),
                    int(self._spin_scr1_par_x.value()),
                    int(self._spin_scr1_par_y.value()),
                )
                _hint_small_plane_wrap(
                    "scr2",
                    self._bg_pixmap_scr2,
                    int(self._combo_bg_scr2.currentIndex()),
                    int(self._spin_scr2_par_x.value()),
                    int(self._spin_scr2_par_y.value()),
                )
        except Exception:
            pass

        # Profile-guided hints (soft warnings, not blockers)
        profile = str(self._level_profile or self._combo_profile.currentData() or "none").strip() or "none"
        if profile != "none":
            prof_label = self._profile_label(profile)
            expected_map_mode = {
                "platformer": "platformer",
                "run_gun": "platformer",
                "shmup": "shmup",
                "topdown_rpg": "topdown",
                "tactical": "topdown",
            }.get(profile, "")
            if expected_map_mode and mm != expected_map_mode:
                hints.append(
                    tr(
                        "level.diag_profile_map_mode",
                        profile=prof_label,
                        expected=self._map_mode_label(expected_map_mode),
                        current=self._map_mode_label(mm),
                    )
                )
            if profile in ("shmup", "rhythm"):
                if not bool(self._chk_forced_scroll.isChecked()):
                    hints.append(tr("level.diag_profile_forced_scroll", profile=prof_label))
                if not bool(self._chk_scroll_y.isChecked()):
                    hints.append(tr("level.diag_profile_scroll_y", profile=prof_label))
            if profile == "run_gun" and not bool(self._chk_scroll_x.isChecked()):
                hints.append(tr("level.diag_profile_scroll_x", profile=prof_label))
            if profile == "fighting" and not bool(self._chk_rule_lock_y.isChecked()):
                hints.append(tr("level.diag_profile_lock_y", profile=prof_label))
            if profile == "brawler" and not bool(self._chk_rule_ground_band.isChecked()):
                hints.append(tr("level.diag_profile_ground_band", profile=prof_label))

        # PHY-0: platformer col_map has no ladder tile → climbing won't be generated
        if mm == "platformer" and colmap_ok and self._col_map is not None:
            has_ladder_tile = any(
                _TCOL_LADDER in row
                for row in self._col_map
                if isinstance(row, list)
            )
            if not has_ladder_tile:
                hints.append(tr("level.diag_no_ladder_in_colmap"))

        # STREAM-DUAL: both SCR1 and SCR2 have tilemaps AND the grid exceeds 32×32.
        # The generator will block SCR2 streaming (SCR1 via ngpc_mapstream takes priority).
        # SCR2 falls back to HW scroll wrap → visual glitch if SCR2 map > 32×32.
        try:
            _gw = int(self._grid_w)
            _gh = int(self._grid_h)
            _scr1_sel = int(self._combo_bg_scr1.currentIndex()) > 0
            _scr2_sel = int(self._combo_bg_scr2.currentIndex()) > 0
            if (_gw > 32 or _gh > 32) and _scr1_sel and _scr2_sel:
                hints.append(tr("level.diag_dual_large_map"))
        except Exception:
            pass

        # PERF-PAR-1: parallax overflow hint when map height > 41 tiles and vertical parallax active
        try:
            _gh = int(self._grid_h)
            _scr1_par_y = _cfg_int(self._layers_cfg, "scr1_parallax_y", 100)
            _scr2_par_y = _cfg_int(self._layers_cfg, "scr2_parallax_y", 100)
            _par_y_active = (_scr1_par_y not in (0, 100)) or (_scr2_par_y not in (0, 100))
            if _gh > 41 and _par_y_active:
                hints.append(tr("level.diag_parallax_overflow"))
        except Exception:
            pass

        # Regions sanity
        refs_ok = True
        for reg in self._regions:
            x = int(reg.get("x", 0))
            y = int(reg.get("y", 0))
            w = max(1, int(reg.get("w", 1)))
            h = max(1, int(reg.get("h", 1)))
            if x < 0 or y < 0 or (x + w) > int(self._grid_w) or (y + h) > int(self._grid_h):
                refs_ok = False
                blockers.append(tr("level.diag_region_oob", name=str(reg.get("name", "") or "region")))

        # Paths sanity
        path_ids = {str(p.get("id", "") or "") for p in self._paths if isinstance(p, dict)}
        max_path_x = int(self._grid_w * _TILE_PX)
        max_path_y = int(self._grid_h * _TILE_PX)
        for path in self._paths:
            name = str(path.get("name", "") or "path")
            pts = path.get("points", []) or []
            if len(pts) < 2:
                refs_ok = False
                blockers.append(tr("level.diag_path_short", name=name))
                continue
            if any(
                (lambda pxy: pxy[0] < 0 or pxy[1] < 0 or pxy[0] >= max_path_x or pxy[1] >= max_path_y)(_path_point_to_px(pt))
                for pt in pts
            ):
                refs_ok = False
                blockers.append(tr("level.diag_path_oob", name=name))

        bad_path_ents = [
            self._format_entity_ref(i, ent)
            for i, ent in enumerate(self._entities)
            if str(ent.get("path_id", "") or "").strip()
            and str(ent.get("path_id", "") or "").strip() not in path_ids
        ]
        if bad_path_ents:
            refs_ok = False
            blockers.append(tr("level.diag_entity_path_missing", ents=self._diag_join_labels(bad_path_ents, limit=3)))

        # Trigger reference sanity
        trig_issues = self._collect_trigger_issues()
        if trig_issues:
            refs_ok = False
            blockers.extend(trig_issues)

        sym_ok = bool(str(self._edit_sym.text()).strip())
        checklist_lines = [
            f"<b>{tr('level.diag_checklist_title')}</b>",
            self._diag_check_html(
                tr("level.diag_check_blockers"),
                "ok" if not blockers else "warn",
                tr("level.diag_check_blockers_ok") if not blockers else tr("level.diag_check_blockers_bad", n=len(blockers)),
            ),
            self._diag_check_html(
                tr("level.diag_check_camera"),
                "ok" if camera_ok else "warn",
            ),
            self._diag_check_html(
                tr("level.diag_check_refs"),
                "ok" if refs_ok else "warn",
            ),
            self._diag_check_html(
                tr("level.diag_check_player"),
                "ok" if has_player else ("na" if not player_types else "warn"),
                tr("level.diag_check_player_na") if not player_types else "",
            ),
            self._diag_check_html(
                tr("level.diag_check_export_sym"),
                "ok" if sym_ok else "warn",
                tr("level.diag_check_export_sym_missing") if not sym_ok else "",
            ),
            self._diag_check_html(
                tr("level.diag_check_procgen"),
                "ok" if (not procgen_mapping_used or procgen_mapping_ok) else "warn",
                tr("level.diag_check_not_used") if not procgen_mapping_used else "",
            ),
            self._diag_check_html(
                tr("level.diag_check_profile"),
                "ok" if not hints else ("na" if profile == "none" else "warn"),
                tr("level.diag_check_profile_na") if profile == "none" else (tr("level.diag_check_profile_bad", n=len(hints)) if hints else ""),
            ),
        ]
        self._lbl_checklist.setText("<br>".join(checklist_lines))

        sections: list[str] = []
        if blockers:
            sections.append(tr("level.diag_blockers_title"))
            sections.extend(f"- {s}" for s in blockers)
        if hints:
            if sections:
                sections.append("")
            sections.append(tr("level.diag_hints_title"))
            sections.extend(f"- {s}" for s in hints)
        if sections:
            self._lbl_diag.setText("\n".join(sections))
        else:
            self._lbl_diag.setText(tr("level.diag_ok"))

    # ------------------------------------------------------------------
    # Triggers
    # ------------------------------------------------------------------

    def _trigger_cond_label(self, cond: str) -> str:
        key = dict(_TRIGGER_CONDS).get(str(cond), "")
        return tr(key) if key else str(cond)

    def _trigger_action_label(self, action: str) -> str:
        key = {
            "emit_event":       "level.trigger_action.emit_event",
            "play_sfx":         "level.trigger_action.play_sfx",
            "start_bgm":        "level.trigger_action.start_bgm",
            "stop_bgm":         "level.trigger_action.stop_bgm",
            "fade_bgm":         "level.trigger_action.fade_bgm",
            "goto_scene":       "level.trigger_action.goto_scene",
            "add_score":        "level.trigger_action.add_score",
            "spawn_wave":       "level.trigger_action.spawn_wave",
            "pause_scroll":     "level.trigger_action.pause_scroll",
            "resume_scroll":    "level.trigger_action.resume_scroll",
            "spawn_entity":     "level.trigger_action.spawn_entity",
            "set_scroll_speed": "level.trigger_action.set_scroll_speed",
            "play_anim":        "level.trigger_action.play_anim",
            "force_jump":       "level.trigger_action.force_jump",
            "fire_player_shot": "level.trigger_action.fire_player_shot",
            "enable_trigger":   "level.trigger_action.enable_trigger",
            "disable_trigger":  "level.trigger_action.disable_trigger",
            "show_entity":      "level.trigger_action.show_entity",
            "hide_entity":      "level.trigger_action.hide_entity",
            "move_entity_to":   "level.trigger_action.move_entity_to",
            "pause_entity_path":"level.trigger_action.pause_entity_path",
            "resume_entity_path":"level.trigger_action.resume_entity_path",
            "screen_shake":     "level.trigger_action.screen_shake",
            "set_cam_target":   "level.trigger_action.set_cam_target",
            "cycle_player_form":"level.trigger_action.cycle_player_form",
            "set_player_form":  "level.trigger_action.set_player_form",
            "set_checkpoint":   "level.trigger_action.set_checkpoint",
            "respawn_player":   "level.trigger_action.respawn_player",
            "stop_wave_rand":   "level.trigger_action.stop_wave_rand",
        }.get(str(action), "")
        return tr(key) if key else str(action)

    def _refresh_trigger_regions(self) -> None:
        """Refresh the region combo used by triggers (keeps selection stable via region_id)."""
        if not hasattr(self, "_combo_trig_region"):
            return
        cur = ""
        try:
            cur = str(self._combo_trig_region.currentData() or "")
        except Exception:
            cur = ""

        self._combo_trig_region.blockSignals(True)
        try:
            self._combo_trig_region.clear()
            self._combo_trig_region.addItem(tr("level.trigger_region_none"), "")
            for r in self._regions:
                rid = str(r.get("id", "") or "")
                nm = str(r.get("name", "") or "region")
                kind = str(r.get("kind", "zone") or "zone")
                self._combo_trig_region.addItem(f"{nm} [{kind}]", rid)
            if cur:
                idx = self._combo_trig_region.findData(cur)
                if idx >= 0:
                    self._combo_trig_region.setCurrentIndex(idx)
        finally:
            self._combo_trig_region.blockSignals(False)

    def _refresh_npc_entity_combo(self, cond: str = "npc_talked_to") -> None:
        """Rebuild _combo_trig_npc_entity with NPC/prop sprites sorted by src_idx."""
        cmb = getattr(self, "_combo_trig_npc_entity", None)
        if cmb is None:
            return
        if cond == "npc_talked_to":
            cmb.setToolTip("Entité NPC/prop — se déclenche quand le joueur est adjacent + PAD_A")
        else:
            cmb.setToolTip("Entité NPC/prop — se déclenche au contact (AABB overlap)")
        scene_sprites = [
            s for s in (self._scene.get("sprites") or [])
            if s.get("file")
        ]
        cmb.blockSignals(True)
        try:
            cmb.clear()
            for sp in scene_sprites:
                name = Path(sp.get("file", "")).stem
                role = str(self._entity_roles.get(name, "prop") or "prop").strip().lower()
                if role in ("npc", "prop", "item", "trigger"):
                    # src_idx MUST match the runtime value: index of the entity in the
                    # placed entities array (entities[] in JSON), not the sprite list index.
                    src_idx = self._prop_src_idx_for_sprite_name(name)
                    if src_idx is None:
                        continue  # sprite declared but no placed entity — skip
                    if cond == "npc_talked_to":
                        label = f"{name}  [id {src_idx}] — adjacent+A"
                    else:
                        label = f"{name}  [id {src_idx}] — contact"
                    cmb.addItem(label, src_idx)
            if cmb.count() == 0:
                cmb.addItem("(aucun NPC/prop placé dans cette scène)", 0)
        finally:
            cmb.blockSignals(False)

    # ------------------------------------------------------------------
    # Extra AND conditions (T-14)
    # ------------------------------------------------------------------

    def _refresh_extra_cond_list(self) -> None:
        """Rebuild the QListWidget from t['extra_conds']."""
        idx = int(self._trigger_selected)
        t = self._triggers[idx] if 0 <= idx < len(self._triggers) else None
        extra = list(t.get("extra_conds", []) if t else [])
        sel = self._extra_cond_list.currentRow()
        self._extra_cond_list.blockSignals(True)
        try:
            self._extra_cond_list.clear()
            if not extra:
                self._extra_cond_list.addItem(tr("level.trigger_extra_cond_none"))
            else:
                for ec in extra:
                    c = str(ec.get("cond", "enter_region"))
                    c_lbl = self._trigger_cond_label(c)
                    rid = str(ec.get("region_id", "") or "")
                    v = int(ec.get("value", 0) or 0)
                    reg_by_id = {str(r.get("id", "") or ""): r for r in self._regions}
                    if rid and rid in reg_by_id:
                        target = str(reg_by_id[rid].get("name", "") or "region")
                    elif c in _TRIGGER_REGION_CONDS:
                        target = "—"
                    else:
                        target = str(v)
                    self._extra_cond_list.addItem(f"[{c_lbl}]  {target}")
        finally:
            self._extra_cond_list.blockSignals(False)
        # Restore selection
        if extra and 0 <= sel < len(extra):
            self._extra_cond_list.setCurrentRow(sel)
        elif extra:
            self._extra_cond_list.setCurrentRow(0)
        self._update_extra_cond_ui()

    def _update_extra_cond_ui(self) -> None:
        """Show/hide inline editor and update del button based on selection."""
        idx = int(self._trigger_selected)
        t = self._triggers[idx] if 0 <= idx < len(self._triggers) else None
        extra = list(t.get("extra_conds", []) if t else [])
        row = self._extra_cond_list.currentRow()
        valid = bool(extra) and 0 <= row < len(extra)
        self._btn_extra_cond_del.setEnabled(valid)
        self._ec_editor.setVisible(valid)
        if not valid:
            return
        ec = extra[row]
        cond = str(ec.get("cond", "enter_region"))
        ci = self._combo_ec_cond.findData(cond)
        self._combo_ec_cond.blockSignals(True)
        self._combo_ec_cond.setCurrentIndex(ci if ci >= 0 else 0)
        self._combo_ec_cond.blockSignals(False)
        self._refresh_extra_cond_regions(ec)
        needs_region = cond in _TRIGGER_REGION_CONDS
        needs_value = cond in _TRIGGER_VALUE_CONDS
        self._lbl_ec_region.setVisible(needs_region)
        self._combo_ec_region.setVisible(needs_region)
        self._lbl_ec_value.setVisible(needs_value)
        self._spin_ec_value.setVisible(needs_value)
        self._spin_ec_value.blockSignals(True)
        self._spin_ec_value.setValue(int(ec.get("value", 0) or 0))
        self._spin_ec_value.blockSignals(False)

    def _refresh_extra_cond_regions(self, ec: dict) -> None:
        rid = str(ec.get("region_id", "") or "")
        self._combo_ec_region.blockSignals(True)
        try:
            self._combo_ec_region.clear()
            self._combo_ec_region.addItem(tr("level.trigger_region_none"), "")
            for r in self._regions:
                r_id = str(r.get("id", "") or "")
                r_nm = str(r.get("name", "") or "region")
                self._combo_ec_region.addItem(r_nm, r_id)
            ri = self._combo_ec_region.findData(rid)
            self._combo_ec_region.setCurrentIndex(ri if ri >= 0 else 0)
        finally:
            self._combo_ec_region.blockSignals(False)

    def _on_extra_cond_sel_changed(self, _row: int) -> None:
        self._update_extra_cond_ui()

    def _on_extra_cond_add(self) -> None:
        idx = int(self._trigger_selected)
        if not (0 <= idx < len(self._triggers)):
            return
        self._push_undo()
        t = self._triggers[idx]
        extra = list(t.get("extra_conds", []))
        extra.append({"cond": "enter_region", "region_id": "", "value": 0})
        t["extra_conds"] = extra
        self._refresh_extra_cond_list()
        self._extra_cond_list.setCurrentRow(len(extra) - 1)

    def _on_extra_cond_del(self) -> None:
        idx = int(self._trigger_selected)
        if not (0 <= idx < len(self._triggers)):
            return
        t = self._triggers[idx]
        extra = list(t.get("extra_conds", []))
        row = self._extra_cond_list.currentRow()
        if not (0 <= row < len(extra)):
            return
        self._push_undo()
        del extra[row]
        t["extra_conds"] = extra
        self._refresh_extra_cond_list()

    def _on_extra_cond_changed(self, *_args) -> None:
        idx = int(self._trigger_selected)
        if not (0 <= idx < len(self._triggers)):
            return
        t = self._triggers[idx]
        extra = list(t.get("extra_conds", []))
        row = self._extra_cond_list.currentRow()
        if not (0 <= row < len(extra)):
            return
        ec = extra[row]
        new_cond = str(self._combo_ec_cond.currentData() or "enter_region")
        ec["cond"] = new_cond
        ec["region_id"] = str(self._combo_ec_region.currentData() or "")
        ec["value"] = int(self._spin_ec_value.value())
        # Update visibility for newly selected cond type
        needs_region = new_cond in _TRIGGER_REGION_CONDS
        needs_value = new_cond in _TRIGGER_VALUE_CONDS
        self._lbl_ec_region.setVisible(needs_region)
        self._combo_ec_region.setVisible(needs_region)
        self._lbl_ec_value.setVisible(needs_value)
        self._spin_ec_value.setVisible(needs_value)
        self._refresh_extra_cond_list()

    # ------------------------------------------------------------------
    # OR groups (TRIG-OR1) — each group is AND, OR between groups
    # ------------------------------------------------------------------

    def _refresh_or_groups_ui(self) -> None:
        """Reload OR-groups state from current trigger and refresh all OR widgets."""
        idx = int(self._trigger_selected)
        t = self._triggers[idx] if 0 <= idx < len(self._triggers) else None
        or_groups = [
            [dict(ec) for ec in (og or []) if isinstance(ec, dict)]
            for og in (t.get("or_groups", []) or [])
            if isinstance(og, list)
        ] if t else []
        # Store OR-groups state on self so handlers can access it
        self._or_groups_data: list[list[dict]] = or_groups
        self._refresh_or_group_selector()
        # Select first group if any
        if or_groups:
            self._combo_or_group.setCurrentIndex(0)
        self._refresh_or_cond_list()

    def _refresh_or_group_selector(self) -> None:
        """Rebuild the OR-group QComboBox."""
        ogs = getattr(self, "_or_groups_data", [])
        self._combo_or_group.blockSignals(True)
        try:
            self._combo_or_group.clear()
            if not ogs:
                self._combo_or_group.addItem(tr("level.trigger_or_no_groups"))
            else:
                for i in range(len(ogs)):
                    n_conds = len(ogs[i])
                    self._combo_or_group.addItem(
                        tr("level.trigger_or_group_n").format(n=i + 1, count=n_conds)
                    )
        finally:
            self._combo_or_group.blockSignals(False)
        has_groups = bool(ogs)
        self._btn_or_group_del.setEnabled(has_groups)
        self._btn_or_cond_add.setEnabled(has_groups)

    def _refresh_or_cond_list(self) -> None:
        """Rebuild the OR-cond QListWidget for the currently selected OR group."""
        ogs = getattr(self, "_or_groups_data", [])
        g = self._combo_or_group.currentIndex()
        self._or_cond_list.blockSignals(True)
        try:
            self._or_cond_list.clear()
            if not ogs or not (0 <= g < len(ogs)):
                self._or_cond_list.addItem(tr("level.trigger_extra_cond_none"))
                self._btn_or_cond_del.setEnabled(False)
                return
            for ec in ogs[g]:
                c = str(ec.get("cond", "enter_region"))
                c_lbl = self._trigger_cond_label(c)
                rid = str(ec.get("region_id", "") or "")
                v = int(ec.get("value", 0) or 0)
                reg_by_id = {str(r.get("id", "") or ""): r for r in self._regions}
                if rid and rid in reg_by_id:
                    target = str(reg_by_id[rid].get("name", "") or "region")
                elif c in _TRIGGER_REGION_CONDS:
                    target = "—"
                else:
                    target = str(v)
                self._or_cond_list.addItem(f"[{c_lbl}]  {target}")
        finally:
            self._or_cond_list.blockSignals(False)
        if ogs[g]:
            self._or_cond_list.setCurrentRow(0)
        self._update_or_cond_editor()

    def _update_or_cond_editor(self) -> None:
        """Show OR-cond inline editor whenever a group is active.
        If a condition row is selected, load its data. Otherwise keep the
        current editor state so the user can configure the next condition to add."""
        ogs = getattr(self, "_or_groups_data", [])
        g = self._combo_or_group.currentIndex()
        row = self._or_cond_list.currentRow()
        has_group = bool(ogs) and 0 <= g < len(ogs)
        valid = has_group and bool(ogs[g]) and 0 <= row < len(ogs[g])
        self._btn_or_cond_del.setEnabled(valid)
        # Editor is visible whenever an OR group is active (not just when a row is selected).
        self._or_cond_editor.setVisible(has_group)
        if not has_group:
            return
        if valid:
            # Load selected condition into editor.
            ec = ogs[g][row]
            cond = str(ec.get("cond", "enter_region"))
            ci = self._combo_or_cond.findData(cond)
            self._combo_or_cond.blockSignals(True)
            self._combo_or_cond.setCurrentIndex(ci if ci >= 0 else 0)
            self._combo_or_cond.blockSignals(False)
            rid = str(ec.get("region_id", "") or "")
            self._combo_or_region.blockSignals(True)
            try:
                self._combo_or_region.clear()
                self._combo_or_region.addItem(tr("level.trigger_region_none"), "")
                for r in self._regions:
                    r_id = str(r.get("id", "") or "")
                    r_nm = str(r.get("name", "") or "region")
                    self._combo_or_region.addItem(r_nm, r_id)
                ri = self._combo_or_region.findData(rid)
                self._combo_or_region.setCurrentIndex(ri if ri >= 0 else 0)
            finally:
                self._combo_or_region.blockSignals(False)
            self._spin_or_value.blockSignals(True)
            self._spin_or_value.setValue(int(ec.get("value", 0) or 0))
            self._spin_or_value.blockSignals(False)
        else:
            # No row selected: repopulate region combo without changing the selection,
            # so the editor stays usable for configuring the next condition to add.
            cur_rid = str(self._combo_or_region.currentData() or "")
            self._combo_or_region.blockSignals(True)
            try:
                self._combo_or_region.clear()
                self._combo_or_region.addItem(tr("level.trigger_region_none"), "")
                for r in self._regions:
                    r_id = str(r.get("id", "") or "")
                    r_nm = str(r.get("name", "") or "region")
                    self._combo_or_region.addItem(r_nm, r_id)
                ri = self._combo_or_region.findData(cur_rid)
                if ri >= 0:
                    self._combo_or_region.setCurrentIndex(ri)
            finally:
                self._combo_or_region.blockSignals(False)
        # Update field visibility based on the current combo state.
        cond = str(self._combo_or_cond.currentData() or "enter_region")
        needs_region = cond in _TRIGGER_REGION_CONDS
        needs_value = cond in _TRIGGER_VALUE_CONDS
        self._lbl_or_region.setVisible(needs_region)
        self._combo_or_region.setVisible(needs_region)
        self._lbl_or_value.setVisible(needs_value)
        self._spin_or_value.setVisible(needs_value)

    def _on_or_group_sel_changed(self, _idx: int) -> None:
        self._refresh_or_cond_list()

    def _on_or_group_add(self) -> None:
        idx = int(self._trigger_selected)
        if not (0 <= idx < len(self._triggers)):
            return
        self._push_undo()
        t = self._triggers[idx]
        or_groups = list(t.get("or_groups", []) or [])
        or_groups.append([])  # empty group — user picks conditions via the editor
        t["or_groups"] = or_groups
        self._refresh_or_groups_ui()
        self._combo_or_group.setCurrentIndex(len(or_groups) - 1)
        self._refresh_or_cond_list()

    def _on_or_group_del(self) -> None:
        idx = int(self._trigger_selected)
        if not (0 <= idx < len(self._triggers)):
            return
        t = self._triggers[idx]
        or_groups = list(t.get("or_groups", []) or [])
        g = self._combo_or_group.currentIndex()
        if not (0 <= g < len(or_groups)):
            return
        self._push_undo()
        del or_groups[g]
        t["or_groups"] = or_groups
        self._refresh_or_groups_ui()

    def _on_or_cond_sel_changed(self, _row: int) -> None:
        self._update_or_cond_editor()

    def _on_or_cond_add(self) -> None:
        idx = int(self._trigger_selected)
        if not (0 <= idx < len(self._triggers)):
            return
        t = self._triggers[idx]
        or_groups = list(t.get("or_groups", []) or [])
        g = self._combo_or_group.currentIndex()
        if not (0 <= g < len(or_groups)):
            return
        self._push_undo()
        group = list(or_groups[g])
        # Read from the editor widgets — user already chose the condition they want.
        new_cond = str(self._combo_or_cond.currentData() or "enter_region")
        new_rid = str(self._combo_or_region.currentData() or "") if new_cond in _TRIGGER_REGION_CONDS else ""
        new_val = int(self._spin_or_value.value()) if new_cond in _TRIGGER_VALUE_CONDS else 0
        group.append({"cond": new_cond, "region_id": new_rid, "value": new_val})
        or_groups[g] = group
        t["or_groups"] = or_groups
        self._refresh_or_groups_ui()
        self._combo_or_group.setCurrentIndex(g)
        self._refresh_or_cond_list()
        self._or_cond_list.setCurrentRow(len(group) - 1)

    def _on_or_cond_del(self) -> None:
        idx = int(self._trigger_selected)
        if not (0 <= idx < len(self._triggers)):
            return
        t = self._triggers[idx]
        or_groups = list(t.get("or_groups", []) or [])
        g = self._combo_or_group.currentIndex()
        row = self._or_cond_list.currentRow()
        if not (0 <= g < len(or_groups)) or not (0 <= row < len(or_groups[g])):
            return
        self._push_undo()
        group = list(or_groups[g])
        del group[row]
        or_groups[g] = group
        t["or_groups"] = or_groups
        self._refresh_or_groups_ui()
        self._combo_or_group.setCurrentIndex(g)
        self._refresh_or_cond_list()

    def _on_or_cond_changed(self, *_args) -> None:
        idx = int(self._trigger_selected)
        if not (0 <= idx < len(self._triggers)):
            return
        t = self._triggers[idx]
        or_groups = list(t.get("or_groups", []) or [])
        g = self._combo_or_group.currentIndex()
        row = self._or_cond_list.currentRow()
        if not (0 <= g < len(or_groups)) or not (0 <= row < len(or_groups[g])):
            return
        ec = or_groups[g][row]
        new_cond = str(self._combo_or_cond.currentData() or "enter_region")
        ec["cond"] = new_cond
        if new_cond in _TRIGGER_REGION_CONDS:
            ec["region_id"] = str(self._combo_or_region.currentData() or "")
        else:
            ec["region_id"] = ""
        if new_cond in _TRIGGER_VALUE_CONDS:
            ec["value"] = int(self._spin_or_value.value())
        else:
            ec["value"] = 0
        t["or_groups"] = or_groups
        self._update_or_cond_editor()
        self._refresh_or_cond_list()

    def _refresh_trigger_targets(self, *, current_idx: int = -1) -> None:
        """Rebuild the target-trigger combo from current self._triggers (excludes self)."""
        if not hasattr(self, "_combo_trig_target"):
            return
        cur = str(self._combo_trig_target.currentData() or "")
        self._combo_trig_target.blockSignals(True)
        try:
            self._combo_trig_target.clear()
            for i, t in enumerate(self._triggers):
                if i == current_idx:
                    continue
                tid = str(t.get("id", "") or "")
                nm = str(t.get("name", "") or f"trig_{i}")
                self._combo_trig_target.addItem(f"[{i}] {nm}", tid)
            if cur:
                idx = self._combo_trig_target.findData(cur)
                if idx >= 0:
                    self._combo_trig_target.setCurrentIndex(idx)
        finally:
            self._combo_trig_target.blockSignals(False)

    def _refresh_trigger_entities(self) -> None:
        """Rebuild the entity-target combo from current static scene entities."""
        if not hasattr(self, "_combo_trig_entity"):
            return
        cur = str(self._combo_trig_entity.currentData() or "").strip()
        self._combo_trig_entity.blockSignals(True)
        try:
            self._combo_trig_entity.clear()
            for i, ent in enumerate(self._entities):
                if not isinstance(ent, dict):
                    continue
                eid = str(ent.get("id", "") or "").strip()
                if not eid:
                    continue
                typ = str(ent.get("type", "") or "?")
                role = str(self._entity_roles.get(typ, "prop") or "prop").strip().lower()
                if role in ("player", "enemy", "trigger"):
                    continue
                x = int(ent.get("x", 0) or 0)
                y = int(ent.get("y", 0) or 0)
                self._combo_trig_entity.addItem(f"[{i}] {typ} [{role}] @ ({x},{y})", eid)
            if cur:
                idx = self._combo_trig_entity.findData(cur)
                if idx >= 0:
                    self._combo_trig_entity.setCurrentIndex(idx)
        finally:
            self._combo_trig_entity.blockSignals(False)

    def _refresh_trigger_dest_regions(self) -> None:
        """Rebuild the destination-region combo from current scene regions."""
        if not hasattr(self, "_combo_trig_dest_region"):
            return
        cur = str(self._combo_trig_dest_region.currentData() or "")
        self._combo_trig_dest_region.blockSignals(True)
        try:
            self._combo_trig_dest_region.clear()
            for i, reg in enumerate(self._regions):
                if not isinstance(reg, dict):
                    continue
                rid = str(reg.get("id", "") or "")
                nm = str(reg.get("name", "") or f"region_{i}")
                x = int(reg.get("x", 0) or 0)
                y = int(reg.get("y", 0) or 0)
                self._combo_trig_dest_region.addItem(f"[{i}] {nm} @ ({x},{y})", rid)
            if cur:
                idx = self._combo_trig_dest_region.findData(cur)
                if idx >= 0:
                    self._combo_trig_dest_region.setCurrentIndex(idx)
        finally:
            self._combo_trig_dest_region.blockSignals(False)

    def _refresh_dialogue_combo(self) -> None:
        """Rebuild the dialogue combo from current scene dialogues."""
        if not hasattr(self, "_combo_trig_dialogue"):
            return
        sel_idx = self._trigger_selected if hasattr(self, "_trigger_selected") else -1
        cur_did = ""
        if 0 <= sel_idx < len(self._triggers):
            cur_did = str(self._triggers[sel_idx].get("dialogue_id", "") or "")
        self._combo_trig_dialogue.blockSignals(True)
        try:
            self._combo_trig_dialogue.clear()
            dlgs = (self._scene or {}).get("dialogues") or []
            if not dlgs:
                self._combo_trig_dialogue.addItem(tr("level.trigger_dialogue_empty"), "")
            for i, d in enumerate(dlgs):
                did = str(d.get("id", "") or f"dlg_{i:02d}")
                self._combo_trig_dialogue.addItem(f"[{i}] {did}", did)
            if cur_did:
                idx = self._combo_trig_dialogue.findData(cur_did)
                if idx >= 0:
                    self._combo_trig_dialogue.setCurrentIndex(idx)
        finally:
            self._combo_trig_dialogue.blockSignals(False)

    def _refresh_cond_dialogue_combo(self, cur_did: str = "") -> None:
        """Rebuild the condition dialogue combo (used by dialogue_done condition)."""
        ccd = getattr(self, "_combo_trig_cond_dialogue", None)
        if ccd is None:
            return
        if not cur_did:
            sel_idx = self._trigger_selected if hasattr(self, "_trigger_selected") else -1
            if 0 <= sel_idx < len(self._triggers):
                cur_did = str(self._triggers[sel_idx].get("cond_dialogue_id", "") or "")
        ccd.blockSignals(True)
        try:
            ccd.clear()
            dlgs = (self._scene or {}).get("dialogues") or []
            if not dlgs:
                ccd.addItem(tr("level.trigger_dialogue_empty"), "")
            for i, d in enumerate(dlgs):
                did = str(d.get("id", "") or f"dlg_{i:02d}")
                ccd.addItem(f"[{i}] {did}", did)
            if cur_did:
                idx = ccd.findData(cur_did)
                if idx >= 0:
                    ccd.setCurrentIndex(idx)
        finally:
            ccd.blockSignals(False)

    def _refresh_cond_menu_combo(self) -> None:
        """Rebuild the condition menu combo (used by menu_result condition)."""
        ccm = getattr(self, "_combo_trig_cond_menu", None)
        if ccm is None:
            return
        menus = (self._scene or {}).get("menus") or []
        prev = ccm.currentData()
        ccm.blockSignals(True)
        ccm.clear()
        for m in menus:
            mid = str(m.get("id", "") or "")
            ccm.addItem(mid, mid)
        if prev:
            idx = ccm.findData(prev)
            if idx >= 0:
                ccm.setCurrentIndex(idx)
        ccm.blockSignals(False)
        self._refresh_menu_item_combo()

    def _refresh_menu_item_combo(self) -> None:
        """Rebuild the menu item combo based on currently selected menu in _combo_trig_cond_menu."""
        ccm = getattr(self, "_combo_trig_cond_menu", None)
        cmi = getattr(self, "_combo_trig_menu_item", None)
        if ccm is None or cmi is None:
            return
        mid = str(ccm.currentData() or "").strip()
        menus = (self._scene or {}).get("menus") or []
        items = []
        for m in menus:
            if str(m.get("id", "") or "").strip() == mid:
                items = m.get("items") or []
                break
        prev_idx = cmi.currentIndex()
        cmi.blockSignals(True)
        cmi.clear()
        for i, it in enumerate(items):
            label = str(it.get("label", "") or f"Item {i}")
            cmi.addItem(f"{i}: {label}", i)
        if 0 <= prev_idx < cmi.count():
            cmi.setCurrentIndex(prev_idx)
        cmi.blockSignals(False)

    def _on_cond_menu_changed(self, _index: int = -1) -> None:
        """Called when menu_result condition menu selection changes — refresh item list."""
        self._refresh_menu_item_combo()
        self._on_trigger_prop_changed()

    def _refresh_entity_type_cond_combo(self, cur_name: str = "") -> None:
        """Rebuild _combo_trig_entity_type from entity types used in this scene."""
        cmb = getattr(self, "_combo_trig_entity_type", None)
        if cmb is None:
            return
        from core.scene_level_gen import _collect_entity_types  # type: ignore[attr-defined]
        scene = self._scene if isinstance(self._scene, dict) else {}
        type_names = _collect_entity_types(scene)
        prev = cur_name or str(cmb.currentData() or "")
        cmb.blockSignals(True)
        cmb.clear()
        for name in type_names:
            cmb.addItem(name, name)
        if prev:
            idx = cmb.findData(prev)
            if idx >= 0:
                cmb.setCurrentIndex(idx)
        cmb.blockSignals(False)

    def _refresh_trig_cev_combo(self, cur_cev_id: str = "") -> None:
        """Rebuild _combo_trig_cev from project custom_events list."""
        cmb = getattr(self, "_combo_trig_cev", None)
        if cmb is None:
            return
        pd = self._project_data_root if isinstance(self._project_data_root, dict) else {}
        cev_list = pd.get("custom_events", []) or []
        if not cur_cev_id:
            sel_idx = self._trigger_selected if hasattr(self, "_trigger_selected") else -1
            if 0 <= sel_idx < len(self._triggers):
                cur_cev_id = str(self._triggers[sel_idx].get("cev_id", "") or "")
        prev = cur_cev_id or str(cmb.currentData() or "")
        cmb.blockSignals(True)
        cmb.clear()
        for ev in cev_list:
            if not isinstance(ev, dict):
                continue
            ev_id = str(ev.get("id", "") or "")
            ev_name = str(ev.get("name", ev_id) or ev_id)
            cmb.addItem(ev_name, ev_id)
        if not cmb.count():
            cmb.addItem("(aucun événement défini)", "")
        if prev:
            idx = cmb.findData(prev)
            if idx >= 0:
                cmb.setCurrentIndex(idx)
        cmb.blockSignals(False)

    def _refresh_cave_item_pool(self, selected: list | None = None) -> None:
        """Rebuild the cave item pool list from project item_table; restore selection."""
        lst = getattr(self, "_list_cave_item_pool", None)
        if lst is None:
            return
        pd = self._project_data_root if isinstance(self._project_data_root, dict) else {}
        item_list = pd.get("item_table", []) or []
        if selected is None:
            selected = []
        selected_set = set(str(s) for s in selected)
        lst.blockSignals(True)
        lst.clear()
        for i, it in enumerate(item_list):
            if not isinstance(it, dict):
                continue
            name = str(it.get("name", "") or f"item_{i}")
            label = f"[{i}] {name}"
            from PyQt6.QtWidgets import QListWidgetItem
            lwi = QListWidgetItem(label)
            lwi.setData(256, name)  # Qt.UserRole = 256
            lst.addItem(lwi)
            if name in selected_set:
                lwi.setSelected(True)
        if not lst.count():
            from PyQt6.QtWidgets import QListWidgetItem
            ph = QListWidgetItem("(aucun item défini dans Globals)")
            ph.setFlags(ph.flags() & ~ph.flags())  # not selectable
            lst.addItem(ph)
        lst.blockSignals(False)

    def _get_cave_item_pool_selected(self) -> list[str]:
        """Return list of selected item names from _list_cave_item_pool."""
        lst = getattr(self, "_list_cave_item_pool", None)
        if lst is None:
            return []
        result = []
        for i in range(lst.count()):
            item = lst.item(i)
            if item and item.isSelected():
                name = item.data(256)
                if name:
                    result.append(str(name))
        return result

    def _refresh_trig_item_combo(self, cur_item_name: str = "") -> None:
        """Rebuild _combo_trig_item from project item_table list."""
        cmb = getattr(self, "_combo_trig_item", None)
        if cmb is None:
            return
        pd = self._project_data_root if isinstance(self._project_data_root, dict) else {}
        item_list = pd.get("item_table", []) or []
        if not cur_item_name:
            sel_idx = self._trigger_selected if hasattr(self, "_trigger_selected") else -1
            if 0 <= sel_idx < len(self._triggers):
                cur_item_name = str(self._triggers[sel_idx].get("item_id", "") or "")
        prev = cur_item_name or str(cmb.currentData() or "")
        cmb.blockSignals(True)
        cmb.clear()
        for i, it in enumerate(item_list):
            if not isinstance(it, dict):
                continue
            name = str(it.get("name", "") or f"item_{i}")
            cmb.addItem(f"[{i}] {name}", name)
        if not cmb.count():
            cmb.addItem("(aucun item défini)", "")
        if prev:
            idx = cmb.findData(prev)
            if idx >= 0:
                cmb.setCurrentIndex(idx)
        cmb.blockSignals(False)

    def _refresh_menu_combo(self, cur_mid: str = "") -> None:
        """Rebuild the menu combo from current scene menus."""
        cm = getattr(self, "_combo_trig_menu", None)
        if cm is None:
            return
        if not cur_mid:
            sel_idx = self._trigger_selected if hasattr(self, "_trigger_selected") else -1
            if 0 <= sel_idx < len(self._triggers):
                cur_mid = str(self._triggers[sel_idx].get("menu_id", "") or "")
        cm.blockSignals(True)
        try:
            cm.clear()
            menus = (self._scene or {}).get("menus") or []
            if not menus:
                cm.addItem(tr("level.trigger_dialogue_empty"), "")
            for i, m in enumerate(menus):
                mid = str(m.get("id", "") or f"menu_{i:02d}")
                cm.addItem(f"[{i}] {mid}", mid)
            if cur_mid:
                idx = cm.findData(cur_mid)
                if idx >= 0:
                    cm.setCurrentIndex(idx)
        finally:
            cm.blockSignals(False)

    def _trigger_issue_text(self, trig: dict) -> str:
        """Return a short human-readable issue for an invalid trigger, if any."""
        if not isinstance(trig, dict):
            return ""
        act = str(trig.get("action", "") or "").strip().lower()
        if act not in ("show_entity", "hide_entity", "move_entity_to", "pause_entity_path", "resume_entity_path"):
            return ""

        target_id = str(trig.get("entity_target_id", "") or "").strip()
        if target_id:
            if self._entity_index_for_target_id(target_id) is None:
                return tr("level.trigger_issue_missing_entity")
        else:
            legacy_idx = int(trig.get("entity_index", trig.get("event", 0)) or 0)
            if not (0 <= legacy_idx < len(self._entities)):
                return tr("level.trigger_issue_missing_entity")

        if act == "move_entity_to":
            dest_region_id = str(trig.get("dest_region_id", "") or "").strip()
            if dest_region_id:
                if not any(str(r.get("id", "") or "").strip() == dest_region_id for r in self._regions):
                    return tr("level.trigger_issue_missing_dest_region")
            else:
                pidx = int(trig.get("param", 0) or 0)
                if not (0 <= pidx < len(self._regions)):
                    return tr("level.trigger_issue_missing_dest_region")
        return ""

    def _collect_trigger_issues(self) -> list[str]:
        """Collect invalid-trigger diagnostics for save/export feedback."""
        issues: list[str] = []
        for i, trig in enumerate(self._triggers):
            issue = self._trigger_issue_text(trig)
            if not issue:
                continue
            name = str(trig.get("name", "") or f"trig_{i}")
            issues.append(tr("level.trigger_issue_line", name=name, issue=issue))
        return issues

    def _set_trigger_props_enabled(self, enabled: bool) -> None:
        for w in (
            self._edit_trig_name, self._combo_trig_cond, self._combo_trig_action,
            self._combo_trig_region, self._spin_trig_value,
            self._spin_trig_event, self._combo_trig_scene, self._combo_trig_target,
            self._combo_trig_entity, self._spin_trig_param, self._combo_trig_dest_region,
            self._chk_trig_once,
            self._extra_cond_list, self._btn_extra_cond_add,
            self._btn_trig_dup,
        ):
            w.setEnabled(enabled)
        if not enabled:
            self._ec_editor.setVisible(False)
            self._btn_extra_cond_del.setEnabled(False)

    def _refresh_trigger_list(self) -> None:
        self._trig_list.blockSignals(True)
        try:
            self._trig_list.clear()
            reg_by_id = {str(r.get("id", "") or ""): r for r in self._regions}
            for t in self._triggers:
                nm = str(t.get("name", "") or "trigger")
                cond = str(t.get("cond", "enter_region") or "enter_region")
                cond_lbl = self._trigger_cond_label(cond)
                rid = str(t.get("region_id", "") or "")
                rnm = ""
                if rid and rid in reg_by_id:
                    rnm = str(reg_by_id[rid].get("name", "") or "region")
                val = int(t.get("value", 0) or 0)
                act = str(t.get("action", "") or "").strip().lower() or "emit_event"
                act_lbl = self._trigger_action_label(act)
                a0 = int(t.get("event", 0) or 0) & 0xFF
                a1 = int(t.get("param", 0) or 0) & 0xFF
                once = " once" if bool(t.get("once", True)) else ""
                if cond in _TRIGGER_REGION_CONDS:
                    target = (rnm or "—")
                else:
                    target = str(val)

                if act == "emit_event":
                    rhs = f"ev {a0} p {a1}"
                elif act == "play_sfx":
                    rhs = f"sfx {a0}"
                elif act == "start_bgm":
                    rhs = f"bgm {a0}"
                elif act == "fade_bgm":
                    rhs = f"fade {a0}"
                elif act == "stop_bgm":
                    rhs = "stop"
                elif act in ("show_entity", "hide_entity", "move_entity_to", "pause_entity_path", "resume_entity_path"):
                    ent_target_id = str(t.get("entity_target_id", "") or "").strip()
                    ent_idx = self._entity_index_for_target_id(ent_target_id)
                    if ent_idx is None:
                        ent_idx = int(t.get("entity_index", t.get("event", 0)) or 0)
                    ent_name = f"entity {ent_idx}"
                    if 0 <= ent_idx < len(self._entities):
                        ent = self._entities[ent_idx]
                        ent_name = f"{ent.get('type', '?')}#{ent_idx}"
                    if act == "move_entity_to":
                        dest_id = str(t.get("dest_region_id", "") or "").strip()
                        dest_name = ""
                        if dest_id and dest_id in reg_by_id:
                            dest_name = str(reg_by_id[dest_id].get("name", "") or "")
                        if not dest_name and 0 <= a1 < len(self._regions):
                            dest_name = str(self._regions[a1].get("name", "") or f"region_{a1}")
                        rhs = f"{ent_name} -> {dest_name or ('region ' + str(a1))}"
                    elif act == "pause_entity_path":
                        rhs = f"pause {ent_name}"
                    elif act == "resume_entity_path":
                        rhs = f"resume {ent_name}"
                    else:
                        rhs = ent_name
                elif act == "cycle_player_form":
                    rhs = tr("level.trigger_player_form_cycle_rhs")
                elif act == "set_player_form":
                    rhs = tr("level.trigger_player_form_rhs", idx=a0)
                elif act == "fire_player_shot":
                    rhs = tr("level.trigger_player_fire_rhs")
                elif act == "goto_scene":
                    scene_label = ""
                    sid = str(t.get("scene_to", "") or "").strip()
                    if sid:
                        sidx = self._scene_idx_for_id(sid)
                        if sidx is not None and 0 <= sidx < len(self._project_scenes):
                            scene_label = str(self._project_scenes[sidx].get("label") or "")
                    if not scene_label:
                        scene_label = f"scene {a0}"
                    rhs = scene_label
                elif act == "set_checkpoint":
                    rhs = tr("level.trigger_checkpoint_rhs")
                elif act == "respawn_player":
                    rhs = tr("level.trigger_respawn_rhs")
                elif act == "toggle_tile":
                    dest_id = str(t.get("dest_region_id", "") or "").strip()
                    dest_name = ""
                    if dest_id and dest_id in reg_by_id:
                        dest_name = str(reg_by_id[dest_id].get("name", "") or "")
                    if not dest_name:
                        dest_name = f"region {a0}"
                    rhs = f"{dest_name} → type {a1}"
                else:
                    rhs = f"a0 {a0} a1 {a1}"

                issue = self._trigger_issue_text(t)
                suffix = f"  [! {issue}]" if issue else ""
                self._trig_list.addItem(f"{nm}  [{cond_lbl}]  {target}  -> {act_lbl}: {rhs}{once}{suffix}")
            if 0 <= self._trigger_selected < self._trig_list.count():
                self._trig_list.setCurrentRow(int(self._trigger_selected))
        finally:
            self._trig_list.blockSignals(False)
        valid = 0 <= self._trigger_selected < len(self._triggers)
        self._btn_trig_del.setEnabled(valid)
        self._btn_trig_dup.setEnabled(valid)

    def _refresh_trigger_props(self) -> None:
        idx = int(self._trigger_selected)
        if not (0 <= idx < len(self._triggers)):
            self._set_trigger_props_enabled(False)
            try:
                self._edit_trig_name.setText("")
            except Exception:
                pass
            self._btn_trig_del.setEnabled(False)
            self._btn_trig_dup.setEnabled(False)
            return

        t = self._triggers[idx]
        self._set_trigger_props_enabled(True)
        self._btn_trig_del.setEnabled(True)
        self._btn_trig_dup.setEnabled(True)
        self._edit_trig_name.blockSignals(True)
        self._combo_trig_cond.blockSignals(True)
        self._combo_trig_region.blockSignals(True)
        self._combo_trig_action.blockSignals(True)
        self._spin_trig_value.block_signals(True)
        self._spin_trig_event.blockSignals(True)
        self._combo_trig_scene.blockSignals(True)
        self._combo_trig_target.blockSignals(True)
        self._combo_trig_entity.blockSignals(True)
        self._spin_trig_param.blockSignals(True)
        self._combo_trig_dest_region.blockSignals(True)
        self._chk_trig_once.blockSignals(True)
        try:
            self._edit_trig_name.setText(str(t.get("name", "")))
            cond = str(t.get("cond", "enter_region") or "enter_region")
            ci = self._combo_trig_cond.findData(cond)
            self._combo_trig_cond.setCurrentIndex(ci if ci >= 0 else 0)
            self._refresh_trigger_regions()
            self._combo_trig_region.blockSignals(True)  # re-block: _refresh_trigger_regions unblocks internally
            rid = str(t.get("region_id", "") or "")
            ri = self._combo_trig_region.findData(rid)
            self._combo_trig_region.setCurrentIndex(ri if ri >= 0 else 0)
            act = str(t.get("action", "") or "").strip().lower() or "emit_event"
            ai = self._combo_trig_action.findData(act)
            self._combo_trig_action.setCurrentIndex(ai if ai >= 0 else 0)
            self._spin_trig_value.set_value(int(t.get("value", 0) or 0),
                                             str(t.get("value_const", "") or ""))
            # NPC/entity combo — restore from t["value"] (= src_idx)
            npc_cmb = getattr(self, "_combo_trig_npc_entity", None)
            if npc_cmb is not None and cond in ("npc_talked_to", "entity_contact"):
                self._refresh_npc_entity_combo(cond)
                npc_cmb.blockSignals(True)
                src_idx_val = int(t.get("value", 0) or 0)
                ni = npc_cmb.findData(src_idx_val)
                if ni < 0 and npc_cmb.count() > 0:
                    # Stored value doesn't match any placed entity (stale or never set).
                    # Default to first item and immediately sync t["value"] so the JSON
                    # reflects what the user sees.
                    ni = 0
                    actual = npc_cmb.itemData(0)
                    if actual is not None:
                        t["value"] = int(actual)
                npc_cmb.setCurrentIndex(ni if ni >= 0 else 0)
                npc_cmb.blockSignals(False)
            self._spin_trig_event.setValue(int(t.get("event", 0) or 0))
            # BGM combo for start_bgm
            if act == "start_bgm":
                bgm_idx = int(t.get("event", 0) or 0)
                bi = self._combo_trig_bgm.findData(bgm_idx)
                if bi >= 0:
                    self._combo_trig_bgm.setCurrentIndex(bi)
            # SFX combo for play_sfx
            if act == "play_sfx":
                sfx_idx = int(t.get("event", 0) or 0)
                si = self._combo_trig_sfx.findData(sfx_idx)
                if si >= 0:
                    self._combo_trig_sfx.setCurrentIndex(si)
            # Scene picker for goto_scene / warp_to
            if act in ("goto_scene", "warp_to"):
                sid = str(t.get("scene_to", "") or "").strip()
                if not sid:
                    sid = self._scene_id_for_idx(int(t.get("event", 0) or 0)) or ""
                si = self._combo_trig_scene.findData(sid) if sid else -1
                if si >= 0:
                    self._combo_trig_scene.setCurrentIndex(si)
            if act == "warp_to":
                self._spin_trig_param.setValue(int(t.get("spawn_index", 0) or 0))
            # Target trigger picker for enable/disable_trigger
            if act in ("enable_trigger", "disable_trigger"):
                self._refresh_trigger_targets(current_idx=idx)
                self._combo_trig_target.blockSignals(True)  # re-block: _refresh_trigger_targets unblocks internally
                tid = str(t.get("target_id", "") or "")
                ti = self._combo_trig_target.findData(tid) if tid else -1
                if ti < 0:
                    ti = self._combo_trig_target.findData(str(int(t.get("event", 0) or 0)))
                self._combo_trig_target.setCurrentIndex(ti if ti >= 0 else 0)
            if act in ("show_entity", "hide_entity", "move_entity_to", "pause_entity_path", "resume_entity_path"):
                self._refresh_trigger_entities()
                self._combo_trig_entity.blockSignals(True)  # re-block: _refresh_trigger_entities unblocks internally
                ent_target_id = str(t.get("entity_target_id", "") or "").strip()
                if not ent_target_id:
                    ent_target_id = self._entity_target_id_for_index(int(t.get("entity_index", t.get("event", 0)) or 0))
                ei = self._combo_trig_entity.findData(ent_target_id) if ent_target_id else -1
                self._combo_trig_entity.setCurrentIndex(ei if ei >= 0 else 0)
            if act == "move_entity_to":
                self._refresh_trigger_dest_regions()
                self._combo_trig_dest_region.blockSignals(True)  # re-block: _refresh_trigger_dest_regions unblocks internally
                rid = str(t.get("dest_region_id", "") or "")
                ri = self._combo_trig_dest_region.findData(rid) if rid else -1
                if ri < 0:
                    pidx = int(t.get("param", 0) or 0)
                    if 0 <= pidx < len(self._regions):
                        rid = str(self._regions[pidx].get("id", "") or "")
                        ri = self._combo_trig_dest_region.findData(rid) if rid else -1
                self._combo_trig_dest_region.setCurrentIndex(ri if ri >= 0 else 0)
            if act in ("teleport_player", "spawn_at_region", "toggle_tile"):
                self._refresh_trigger_dest_regions()
                self._combo_trig_dest_region.blockSignals(True)  # re-block: _refresh_trigger_dest_regions unblocks internally
                rid = str(t.get("dest_region_id", "") or "")
                ri = self._combo_trig_dest_region.findData(rid) if rid else -1
                self._combo_trig_dest_region.setCurrentIndex(ri if ri >= 0 else 0)
            if act == "show_dialogue":
                self._refresh_dialogue_combo()
                self._combo_trig_dialogue.blockSignals(True)
                did = str(t.get("dialogue_id", "") or "")
                di = self._combo_trig_dialogue.findData(did) if did else -1
                self._combo_trig_dialogue.setCurrentIndex(di if di >= 0 else 0)
                self._combo_trig_dialogue.blockSignals(False)
            if act == "set_npc_dialogue":
                self._refresh_dialogue_combo()
                self._combo_trig_dialogue.blockSignals(True)
                npc_did = str(t.get("npc_dialogue_id", "") or "")
                ndi = self._combo_trig_dialogue.findData(npc_did) if npc_did else -1
                self._combo_trig_dialogue.setCurrentIndex(ndi if ndi >= 0 else 0)
                self._combo_trig_dialogue.blockSignals(False)
            # Load cond_dialogue_id for dialogue_done / choice_result conditions
            ccd = getattr(self, "_combo_trig_cond_dialogue", None)
            if ccd is not None and cond in _TRIGGER_DIALOGUE_CONDS:
                self._refresh_cond_dialogue_combo()
                ccd.blockSignals(True)
                cdid = str(t.get("cond_dialogue_id", "") or "")
                cdi = ccd.findData(cdid) if cdid else -1
                ccd.setCurrentIndex(cdi if cdi >= 0 else 0)
                ccd.blockSignals(False)
            # Load choice index for choice_result
            sci = getattr(self, "_spin_trig_choice_idx", None)
            if sci is not None and cond in _TRIGGER_CHOICE_CONDS:
                sci.blockSignals(True)
                sci.setValue(int(t.get("choice_idx", 0) or 0))
                sci.blockSignals(False)
            # Load menu_id for open_menu
            cm = getattr(self, "_combo_trig_menu", None)
            if cm is not None and act == "open_menu":
                self._refresh_menu_combo()
                cm.blockSignals(True)
                mid = str(t.get("menu_id", "") or "")
                mi = cm.findData(mid) if mid else -1
                cm.setCurrentIndex(mi if mi >= 0 else 0)
                cm.blockSignals(False)
            # Load cond_menu_id + menu_item_idx for menu_result condition
            ccm = getattr(self, "_combo_trig_cond_menu", None)
            cmi = getattr(self, "_combo_trig_menu_item", None)
            if ccm is not None and cond in _TRIGGER_MENU_CONDS:
                self._refresh_cond_menu_combo()
                ccm.blockSignals(True)
                cmid = str(t.get("cond_menu_id", "") or "")
                cmi_idx = ccm.findData(cmid) if cmid else -1
                ccm.setCurrentIndex(cmi_idx if cmi_idx >= 0 else 0)
                ccm.blockSignals(False)
                self._refresh_menu_item_combo()
                if cmi is not None:
                    cmi.blockSignals(True)
                    stored_item_idx = int(t.get("menu_item_idx", 0) or 0)
                    item_ci = cmi.findData(stored_item_idx)
                    cmi.setCurrentIndex(item_ci if item_ci >= 0 else 0)
                    cmi.blockSignals(False)
            self._spin_trig_param.setValue(int(t.get("param", 0) or 0))
            self._chk_trig_once.setChecked(bool(t.get("once", True)))
            spn_fv = getattr(self, "_spin_trig_flag_var", None)
            if spn_fv is not None:
                spn_fv.blockSignals(True)
                spn_fv.setValue(int(t.get("flag_var_index", 0) or 0))
                spn_fv.blockSignals(False)
            # Load cond_type_name for entity_type_* conditions
            cmb_et = getattr(self, "_combo_trig_entity_type", None)
            if cmb_et is not None and cond in _TRIGGER_ENTITY_TYPE_CONDS:
                ctn = str(t.get("cond_type_name", "") or "")
                self._refresh_entity_type_cond_combo(cur_name=ctn)
                et_idx = cmb_et.findData(ctn) if ctn else -1
                cmb_et.blockSignals(True)
                cmb_et.setCurrentIndex(et_idx if et_idx >= 0 else 0)
                cmb_et.blockSignals(False)
            # Load cev_id for on_custom_event condition
            cmb_cev = getattr(self, "_combo_trig_cev", None)
            if cmb_cev is not None and cond == "on_custom_event":
                cev_id = str(t.get("cev_id", "") or "")
                self._refresh_trig_cev_combo(cur_cev_id=cev_id)
                cev_idx = cmb_cev.findData(cev_id) if cev_id else -1
                cmb_cev.blockSignals(True)
                cmb_cev.setCurrentIndex(cev_idx if cev_idx >= 0 else 0)
                cmb_cev.blockSignals(False)
            # Load item_id for give_item / remove_item / player_has_item
            cmb_it = getattr(self, "_combo_trig_item", None)
            if cmb_it is not None and (act in ("give_item", "remove_item", "drop_item") or cond in ("player_has_item", "item_count_ge")):
                item_name = str(t.get("item_id", "") or "")
                self._refresh_trig_item_combo(cur_item_name=item_name)
                it_idx = cmb_it.findData(item_name) if item_name else -1
                cmb_it.blockSignals(True)
                cmb_it.setCurrentIndex(it_idx if it_idx >= 0 else 0)
                cmb_it.blockSignals(False)
        finally:
            self._edit_trig_name.blockSignals(False)
            self._combo_trig_cond.blockSignals(False)
            self._combo_trig_region.blockSignals(False)
            self._combo_trig_action.blockSignals(False)
            self._spin_trig_value.block_signals(False)
            self._spin_trig_event.blockSignals(False)
            self._combo_trig_scene.blockSignals(False)
            self._combo_trig_target.blockSignals(False)
            self._combo_trig_entity.blockSignals(False)
            self._spin_trig_param.blockSignals(False)
            self._combo_trig_dest_region.blockSignals(False)
            self._chk_trig_once.blockSignals(False)

        self._update_trigger_ui_for_cond()
        self._update_trigger_ui_for_action()
        self._refresh_extra_cond_list()
        self._refresh_or_groups_ui()

    def _update_trigger_ui_for_cond(self) -> None:
        cond = str(self._combo_trig_cond.currentData() or "enter_region")
        needs_region = cond in _TRIGGER_REGION_CONDS
        needs_value = cond in _TRIGGER_VALUE_CONDS
        needs_flag_var = cond in _TRIGGER_FLAG_CONDS or cond in _TRIGGER_VAR_CONDS
        needs_dlg = cond in _TRIGGER_DIALOGUE_CONDS
        # npc_talked_to / entity_contact use a named combo instead of the raw spinbox
        needs_npc_combo = cond in ("npc_talked_to", "entity_contact")
        self._lbl_trig_region.setVisible(needs_region)
        self._combo_trig_region.setVisible(needs_region)
        self._lbl_trig_value.setVisible(needs_value and not needs_npc_combo)
        self._spin_trig_value.setVisible(needs_value and not needs_npc_combo)
        npc_cmb = getattr(self, "_combo_trig_npc_entity", None)
        if npc_cmb is not None:
            npc_cmb.setVisible(needs_npc_combo)
            if needs_npc_combo:
                self._refresh_npc_entity_combo(cond)

        # Dynamic tooltip on the value field for conds that reference entity indices
        if cond in ("set_player_form", "cycle_player_form"):
            lines = ["Index de forme joueur (sprites rôle player dans l'ordre de la scène).", ""]
            form_idx = 0
            for name in self._type_names:
                role = str(self._entity_roles.get(name, "prop") or "prop").strip().lower()
                if role == "player":
                    lines.append(f"  {form_idx} → {name}")
                    form_idx += 1
            if form_idx == 0:
                lines.append("  (aucun sprite player dans cette scène)")
            self._spin_trig_value.setToolTip("\n".join(lines))
        else:
            self._spin_trig_value.setToolTip(tr("level.trigger_value_tt"))

        lbl_fv = getattr(self, "_lbl_trig_flag_var", None)
        spn_fv = getattr(self, "_spin_trig_flag_var", None)
        lbl_fv_name = getattr(self, "_lbl_trig_flag_var_name", None)
        if lbl_fv is not None:
            lbl_fv.setVisible(needs_flag_var)
        if spn_fv is not None:
            spn_fv.setVisible(needs_flag_var)
        if lbl_fv_name is not None:
            lbl_fv_name.setVisible(needs_flag_var)
        self._update_flag_var_tooltip()

        ccd = getattr(self, "_combo_trig_cond_dialogue", None)
        if ccd is not None:
            ccd.setVisible(needs_dlg)
            if needs_dlg:
                self._refresh_cond_dialogue_combo()
        # choice_result: also show choice index spin
        needs_choice = cond in _TRIGGER_CHOICE_CONDS
        sci = getattr(self, "_spin_trig_choice_idx", None)
        if sci is not None:
            sci.setVisible(needs_choice)
        # menu_result: show menu + item combos
        needs_menu_result = cond in _TRIGGER_MENU_CONDS
        ccm = getattr(self, "_combo_trig_cond_menu", None)
        lmi = getattr(self, "_lbl_trig_menu_item", None)
        cmi = getattr(self, "_combo_trig_menu_item", None)
        if ccm is not None:
            ccm.setVisible(needs_menu_result)
            if needs_menu_result:
                self._refresh_cond_menu_combo()
        if lmi is not None:
            lmi.setVisible(needs_menu_result)
        if cmi is not None:
            cmi.setVisible(needs_menu_result)
        # entity type conditions: show type combo
        needs_entity_type = cond in _TRIGGER_ENTITY_TYPE_CONDS
        lbl_et = getattr(self, "_lbl_trig_entity_type", None)
        cmb_et = getattr(self, "_combo_trig_entity_type", None)
        if lbl_et is not None:
            lbl_et.setVisible(needs_entity_type)
        if cmb_et is not None:
            cmb_et.setVisible(needs_entity_type)
            if needs_entity_type:
                self._refresh_entity_type_cond_combo()
        # on_custom_event: show custom event combo
        needs_cev = (cond == "on_custom_event")
        lbl_cev = getattr(self, "_lbl_trig_cev", None)
        cmb_cev = getattr(self, "_combo_trig_cev", None)
        if lbl_cev is not None:
            lbl_cev.setVisible(needs_cev)
        if cmb_cev is not None:
            cmb_cev.setVisible(needs_cev)
            if needs_cev:
                self._refresh_trig_cev_combo()
        # player_has_item / item_count_ge: show item combo
        needs_item = cond in ("player_has_item", "item_count_ge")
        lbl_it = getattr(self, "_lbl_trig_item", None)
        cmb_it = getattr(self, "_combo_trig_item", None)
        if lbl_it is not None:
            lbl_it.setVisible(needs_item)
        if cmb_it is not None:
            cmb_it.setVisible(needs_item)
            if needs_item:
                self._refresh_trig_item_combo()

    def _update_trigger_ui_for_action(self) -> None:
        act = str(self._combo_trig_action.currentData() or "emit_event")
        # Always hide audio combos first; individual branches re-show them.
        self._combo_trig_bgm.setVisible(False)
        self._combo_trig_sfx.setVisible(False)
        # Always hide pick-dest widgets first; move_entity_to branch re-shows them.
        self._btn_trig_pick_dest.setVisible(False)
        self._lbl_trig_dest_tile.setVisible(False)
        # Always hide dialogue/menu/item combos first; individual branches re-show them.
        self._combo_trig_dialogue.setVisible(False)
        cm = getattr(self, "_combo_trig_menu", None)
        if cm is not None:
            cm.setVisible(False)
        lbl_it = getattr(self, "_lbl_trig_item", None)
        cmb_it = getattr(self, "_combo_trig_item", None)
        if lbl_it is not None:
            lbl_it.setVisible(False)
        if cmb_it is not None:
            cmb_it.setVisible(False)
        # Default widgets exist; we only change labels/visibility.
        if act == "emit_event":
            self._lbl_trig_evt.setText(tr("level.trigger_event"))
            self._lbl_trig_param.setText(tr("level.trigger_param"))
            self._spin_trig_event.setToolTip(tr("level.trigger_event_tt"))
            self._spin_trig_param.setToolTip(tr("level.trigger_param_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(True)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(True)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
        elif act == "play_sfx":
            self._lbl_trig_evt.setText(tr("level.trigger_sfx"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
            if self._combo_trig_sfx.count() > 0:
                self._combo_trig_sfx.setVisible(True)
                self._spin_trig_event.setVisible(False)
            else:
                self._combo_trig_sfx.setVisible(False)
                self._spin_trig_event.setToolTip(tr("level.trigger_sfx_tt"))
                self._spin_trig_event.setVisible(True)
        elif act == "start_bgm":
            self._lbl_trig_evt.setText(tr("level.trigger_bgm"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
            if self._combo_trig_bgm.count() > 0:
                self._combo_trig_bgm.setVisible(True)
                self._spin_trig_event.setVisible(False)
            else:
                self._combo_trig_bgm.setVisible(False)
                self._spin_trig_event.setToolTip(tr("level.trigger_bgm_tt"))
                self._spin_trig_event.setVisible(True)
        elif act == "fade_bgm":
            self._lbl_trig_evt.setText(tr("level.trigger_fade"))
            self._spin_trig_event.setToolTip(tr("level.trigger_fade_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act == "goto_scene":
            self._lbl_trig_evt.setText(tr("level.trigger_scene"))
            self._combo_trig_scene.setToolTip(tr("level.trigger_scene_tt"))
            self._lbl_trig_evt.setVisible(True)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            if self._combo_trig_scene.count() > 0:
                self._spin_trig_event.setVisible(False)
                self._combo_trig_scene.setVisible(True)
            else:
                # Fallback: manual numeric index (no project context)
                self._spin_trig_event.setToolTip(tr("level.trigger_scene_tt"))
                self._spin_trig_event.setVisible(True)
                self._combo_trig_scene.setVisible(False)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act == "warp_to":
            self._lbl_trig_evt.setText(tr("level.trigger_scene"))
            self._combo_trig_scene.setToolTip(tr("level.trigger_scene_tt"))
            self._lbl_trig_evt.setVisible(True)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            if self._combo_trig_scene.count() > 0:
                self._spin_trig_event.setVisible(False)
                self._combo_trig_scene.setVisible(True)
            else:
                self._spin_trig_event.setToolTip(tr("level.trigger_scene_tt"))
                self._spin_trig_event.setVisible(True)
                self._combo_trig_scene.setVisible(False)
            self._lbl_trig_param.setText(tr("level.trigger_spawn_index"))
            self._spin_trig_param.setToolTip(tr("level.trigger_spawn_index_tt"))
            self._lbl_trig_param.setVisible(True)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(True)
        elif act == "add_score":
            self._lbl_trig_evt.setText(tr("level.trigger_score"))
            self._spin_trig_event.setToolTip(tr("level.trigger_score_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act == "stop_bgm":
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(False)
            self._spin_trig_event.setVisible(False)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act == "spawn_wave":
            self._lbl_trig_evt.setText(tr("level.trigger_wave_idx"))
            self._spin_trig_event.setToolTip(tr("level.trigger_wave_idx_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act in ("pause_scroll", "resume_scroll"):
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(False)
            self._spin_trig_event.setVisible(False)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act == "spawn_entity":
            self._lbl_trig_evt.setText(tr("level.trigger_ent_type"))
            self._spin_trig_event.setToolTip(tr("level.trigger_ent_type_tt"))
            self._lbl_trig_param.setText(tr("level.trigger_slot"))
            self._spin_trig_param.setToolTip(tr("level.trigger_slot_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(True)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(True)
        elif act == "set_scroll_speed":
            self._lbl_trig_evt.setText(tr("level.trigger_spd_x"))
            self._spin_trig_event.setToolTip(tr("level.trigger_spd_x_tt"))
            self._lbl_trig_param.setText(tr("level.trigger_spd_y"))
            self._spin_trig_param.setToolTip(tr("level.trigger_spd_y_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(True)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(True)
        elif act == "play_anim":
            # a0 = entity type, a1 = anim state index
            self._lbl_trig_evt.setText(tr("level.trigger_ent_type"))
            self._spin_trig_event.setToolTip(tr("level.trigger_ent_type_tt"))
            self._lbl_trig_param.setText(tr("level.trigger_anim_state"))
            self._spin_trig_param.setToolTip(tr("level.trigger_anim_state_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(True)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(True)
        elif act == "force_jump":
            self._lbl_trig_evt.setText(tr("level.trigger_force_ent"))
            self._spin_trig_event.setToolTip(tr("level.trigger_force_ent_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act == "fire_player_shot":
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(False)
            self._spin_trig_event.setVisible(False)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act in ("enable_trigger", "disable_trigger"):
            self._lbl_trig_evt.setText(tr("level.trigger_target"))
            self._combo_trig_scene.setVisible(False)
            self._spin_trig_event.setVisible(False)
            self._refresh_trigger_targets(current_idx=self._trigger_selected)
            self._combo_trig_target.setVisible(True)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act in ("show_entity", "hide_entity", "pause_entity_path", "resume_entity_path"):
            self._lbl_trig_evt.setText(tr("level.trigger_entity"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._refresh_trigger_entities()
            if self._combo_trig_entity.count() > 0:
                self._spin_trig_event.setVisible(False)
                self._combo_trig_entity.setVisible(True)
            else:
                self._spin_trig_event.setToolTip(tr("level.trigger_entity_tt"))
                self._spin_trig_event.setVisible(True)
                self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act == "move_entity_to":
            self._lbl_trig_evt.setText(tr("level.trigger_entity"))
            self._lbl_trig_param.setText(tr("level.trigger_dest_region"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._refresh_trigger_entities()
            self._refresh_trigger_dest_regions()
            if self._combo_trig_entity.count() > 0:
                self._spin_trig_event.setVisible(False)
                self._combo_trig_entity.setVisible(True)
            else:
                self._spin_trig_event.setToolTip(tr("level.trigger_entity_tt"))
                self._spin_trig_event.setVisible(True)
                self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            # Check if a dest tile is set on the current trigger
            _sel_t = self._triggers[self._trigger_selected] if 0 <= self._trigger_selected < len(self._triggers) else None
            _has_tile = _sel_t is not None and int(_sel_t.get("dest_tile_x", -1) or -1) >= 0
            if _has_tile:
                # Tile coords override region combo
                _tx = int(_sel_t.get("dest_tile_x", 0))
                _ty = int(_sel_t.get("dest_tile_y", 0))
                self._lbl_trig_dest_tile.setText(f"\u2192 ({_tx}, {_ty})")
                self._lbl_trig_dest_tile.setVisible(True)
                self._lbl_trig_param.setVisible(False)
                self._combo_trig_dest_region.setVisible(False)
                self._spin_trig_param.setVisible(False)
            else:
                self._lbl_trig_param.setVisible(True)
                if self._combo_trig_dest_region.count() > 0:
                    self._spin_trig_param.setVisible(False)
                    self._combo_trig_dest_region.setVisible(True)
                else:
                    self._spin_trig_param.setToolTip(tr("level.trigger_dest_region_tt"))
                    self._spin_trig_param.setVisible(True)
                    self._combo_trig_dest_region.setVisible(False)
            self._btn_trig_pick_dest.setVisible(True)
        elif act == "toggle_tile":
            self._lbl_trig_param.setText(tr("level.trigger_toggle_tile_region"))
            self._spin_trig_param.setToolTip(tr("level.trigger_toggle_tile_type_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(False)
            self._spin_trig_event.setVisible(False)
            self._lbl_trig_param.setVisible(True)
            self._refresh_trigger_dest_regions()
            if self._combo_trig_dest_region.count() > 0:
                self._spin_trig_param.setVisible(False)
                self._combo_trig_dest_region.setVisible(True)
            else:
                self._spin_trig_param.setToolTip(tr("level.trigger_toggle_tile_type_tt"))
                self._spin_trig_param.setVisible(True)
                self._combo_trig_dest_region.setVisible(False)
        elif act == "screen_shake":
            self._lbl_trig_evt.setText(tr("level.trigger_shake_int"))
            self._spin_trig_event.setToolTip(tr("level.trigger_shake_int_tt"))
            self._lbl_trig_param.setText(tr("level.trigger_shake_dur"))
            self._spin_trig_param.setToolTip(tr("level.trigger_shake_dur_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(True)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(True)
        elif act == "set_cam_target":
            self._lbl_trig_evt.setText(tr("level.trigger_cam_x"))
            self._spin_trig_event.setToolTip(tr("level.trigger_cam_x_tt"))
            self._lbl_trig_param.setText(tr("level.trigger_cam_y"))
            self._spin_trig_param.setToolTip(tr("level.trigger_cam_y_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(True)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(True)
        elif act in ("cycle_player_form", "set_checkpoint", "respawn_player"):
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(False)
            self._spin_trig_event.setVisible(False)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act in ("set_flag", "clear_flag"):
            # Only needs the flag index (0..7) — shown via _spin_trig_flag_var.
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(False)
            self._spin_trig_event.setVisible(False)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act == "set_variable":
            self._lbl_trig_evt.setText(tr("level.trigger_var_value"))
            self._spin_trig_event.setToolTip(tr("level.trigger_var_value_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act == "inc_variable":
            self._lbl_trig_evt.setText(tr("level.trigger_var_cap"))
            self._spin_trig_event.setToolTip(tr("level.trigger_var_cap_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act == "set_player_form":
            self._lbl_trig_evt.setText(tr("level.trigger_player_form"))
            # Dynamic tooltip: list available player forms in this scene
            _form_lines = ["Index de forme joueur :"]
            _fi = 0
            for _n in self._type_names:
                if str(self._entity_roles.get(_n, "prop") or "prop").strip().lower() == "player":
                    _form_lines.append(f"  {_fi} → {_n}")
                    _fi += 1
            if _fi == 0:
                _form_lines.append("  (aucun sprite player dans cette scène)")
            self._spin_trig_event.setToolTip("\n".join(_form_lines))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act == "enable_multijump":
            self._lbl_trig_evt.setText(tr("level.trigger_multijump_count"))
            self._spin_trig_event.setToolTip(tr("level.trigger_multijump_count_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act in ("disable_multijump", "reset_scene", "enable_wall_grab", "disable_wall_grab"):
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(False)
            self._spin_trig_event.setVisible(False)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act == "show_dialogue":
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(False)
            self._spin_trig_event.setVisible(False)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
            self._combo_trig_dialogue.setVisible(True)
            self._refresh_dialogue_combo()
        elif act == "open_menu":
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(False)
            self._spin_trig_event.setVisible(False)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
            cm = getattr(self, "_combo_trig_menu", None)
            if cm is not None:
                cm.setVisible(True)
                self._refresh_menu_combo()
        elif act == "set_npc_dialogue":
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._lbl_trig_evt.setVisible(False)
            self._spin_trig_event.setVisible(False)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
            self._combo_trig_entity.setVisible(True)
            self._combo_trig_dialogue.setVisible(True)
            self._refresh_dialogue_combo()
        elif act in ("give_item", "remove_item", "drop_item"):
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(False)
            self._spin_trig_event.setVisible(False)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
            lbl_it = getattr(self, "_lbl_trig_item", None)
            cmb_it = getattr(self, "_combo_trig_item", None)
            if lbl_it is not None:
                lbl_it.setVisible(True)
            if cmb_it is not None:
                cmb_it.setVisible(True)
                self._refresh_trig_item_combo()
        elif act == "unlock_door":
            self._lbl_trig_evt.setText(tr("level.trigger_door_id"))
            self._spin_trig_event.setToolTip(tr("level.trigger_door_id_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act == "set_gravity_dir":
            self._lbl_trig_evt.setText(tr("level.trigger_gravity_dir"))
            self._spin_trig_event.setToolTip(tr("level.trigger_gravity_dir_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act in ("add_resource", "remove_resource"):
            self._lbl_trig_evt.setText(tr("level.trigger_resource_amount"))
            self._spin_trig_event.setToolTip(tr("level.trigger_resource_amount_tt"))
            self._lbl_trig_param.setText(tr("level.trigger_resource_type"))
            self._spin_trig_param.setToolTip(tr("level.trigger_resource_type_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(True)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(True)
        elif act == "unlock_ability":
            self._lbl_trig_evt.setText(tr("level.trigger_ability_id"))
            self._spin_trig_event.setToolTip(tr("level.trigger_ability_id_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act == "set_quest_stage":
            self._lbl_trig_evt.setText(tr("level.trigger_quest_stage"))
            self._spin_trig_event.setToolTip(tr("level.trigger_quest_stage_tt"))
            self._lbl_trig_param.setText(tr("level.trigger_quest_id"))
            self._spin_trig_param.setToolTip(tr("level.trigger_quest_id_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(True)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(True)
        elif act == "play_cutscene":
            self._lbl_trig_evt.setText(tr("level.trigger_cutscene_id"))
            self._spin_trig_event.setToolTip(tr("level.trigger_cutscene_id_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act == "end_game":
            self._lbl_trig_evt.setText(tr("level.trigger_end_game_result"))
            self._spin_trig_event.setToolTip(tr("level.trigger_end_game_result_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act == "dec_variable":
            self._lbl_trig_evt.setText(tr("level.trigger_var_cap"))
            self._spin_trig_event.setToolTip(tr("level.trigger_var_cap_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act in ("add_health", "set_health"):
            self._lbl_trig_evt.setText(tr("level.trigger_health_amount"))
            self._spin_trig_event.setToolTip(tr("level.trigger_health_amount_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act in ("add_lives", "set_lives"):
            self._lbl_trig_evt.setText(tr("level.trigger_lives_amount"))
            self._spin_trig_event.setToolTip(tr("level.trigger_lives_amount_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act == "destroy_entity":
            self._lbl_trig_evt.setText(tr("level.trigger_entity"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._refresh_trigger_entities()
            if self._combo_trig_entity.count() > 0:
                self._spin_trig_event.setVisible(False)
                self._combo_trig_entity.setVisible(True)
            else:
                self._spin_trig_event.setToolTip(tr("level.trigger_entity_tt"))
                self._spin_trig_event.setVisible(True)
                self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act == "teleport_player":
            self._lbl_trig_param.setText(tr("level.trigger_dest_region"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(False)
            self._spin_trig_event.setVisible(False)
            self._refresh_trigger_dest_regions()
            _sel_t2 = self._triggers[self._trigger_selected] if 0 <= self._trigger_selected < len(self._triggers) else None
            _has_tile2 = _sel_t2 is not None and int(_sel_t2.get("dest_tile_x", -1) or -1) >= 0
            if _has_tile2:
                _tx2 = int(_sel_t2.get("dest_tile_x", 0))
                _ty2 = int(_sel_t2.get("dest_tile_y", 0))
                self._lbl_trig_dest_tile.setText(f"\u2192 ({_tx2}, {_ty2})")
                self._lbl_trig_dest_tile.setVisible(True)
                self._lbl_trig_param.setVisible(False)
                self._combo_trig_dest_region.setVisible(False)
                self._spin_trig_param.setVisible(False)
            else:
                self._lbl_trig_param.setVisible(True)
                if self._combo_trig_dest_region.count() > 0:
                    self._spin_trig_param.setVisible(False)
                    self._combo_trig_dest_region.setVisible(True)
                else:
                    self._spin_trig_param.setToolTip(tr("level.trigger_dest_region_tt"))
                    self._spin_trig_param.setVisible(True)
                    self._combo_trig_dest_region.setVisible(False)
            self._btn_trig_pick_dest.setVisible(True)
        elif act == "toggle_flag":
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(False)
            self._spin_trig_event.setVisible(False)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act == "set_score":
            self._lbl_trig_evt.setText(tr("level.trigger_score_hi"))
            self._spin_trig_event.setToolTip(tr("level.trigger_score_hi_tt"))
            self._lbl_trig_param.setText(tr("level.trigger_score_lo"))
            self._spin_trig_param.setToolTip(tr("level.trigger_score_lo_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(True)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(True)
        elif act == "set_timer":
            self._lbl_trig_evt.setText(tr("level.trigger_timer_value"))
            self._spin_trig_event.setToolTip(tr("level.trigger_timer_value_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act in ("pause_timer", "resume_timer"):
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(False)
            self._spin_trig_event.setVisible(False)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act in ("fade_out", "fade_in"):
            self._lbl_trig_evt.setText(tr("level.trigger_fade_dur"))
            self._spin_trig_event.setToolTip(tr("level.trigger_fade_dur_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act in ("camera_lock", "camera_unlock", "reset_combo", "save_game"):
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(False)
            self._spin_trig_event.setVisible(False)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act == "add_combo":
            self._lbl_trig_evt.setText(tr("level.trigger_combo_amount"))
            self._spin_trig_event.setToolTip(tr("level.trigger_combo_amount_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act == "flash_screen":
            self._lbl_trig_evt.setText(tr("level.trigger_flash_int"))
            self._spin_trig_event.setToolTip(tr("level.trigger_flash_int_tt"))
            self._lbl_trig_param.setText(tr("level.trigger_flash_dur"))
            self._spin_trig_param.setToolTip(tr("level.trigger_flash_dur_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(True)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(True)
        elif act == "spawn_at_region":
            self._lbl_trig_evt.setText(tr("level.trigger_ent_type"))
            self._spin_trig_event.setToolTip(tr("level.trigger_ent_type_tt"))
            self._lbl_trig_param.setText(tr("level.trigger_dest_region"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._refresh_trigger_dest_regions()
            _sel_t3 = self._triggers[self._trigger_selected] if 0 <= self._trigger_selected < len(self._triggers) else None
            _has_tile3 = _sel_t3 is not None and int(_sel_t3.get("dest_tile_x", -1) or -1) >= 0
            if _has_tile3:
                _tx3 = int(_sel_t3.get("dest_tile_x", 0))
                _ty3 = int(_sel_t3.get("dest_tile_y", 0))
                self._lbl_trig_dest_tile.setText(f"\u2192 ({_tx3}, {_ty3})")
                self._lbl_trig_dest_tile.setVisible(True)
                self._lbl_trig_param.setVisible(False)
                self._combo_trig_dest_region.setVisible(False)
                self._spin_trig_param.setVisible(False)
            else:
                self._lbl_trig_param.setVisible(True)
                if self._combo_trig_dest_region.count() > 0:
                    self._spin_trig_param.setVisible(False)
                    self._combo_trig_dest_region.setVisible(True)
                else:
                    self._spin_trig_param.setToolTip(tr("level.trigger_dest_region_tt"))
                    self._spin_trig_param.setVisible(True)
                    self._combo_trig_dest_region.setVisible(False)
            self._btn_trig_pick_dest.setVisible(True)
        elif act == "set_bgm_volume":
            self._lbl_trig_evt.setText(tr("level.trigger_bgm_vol"))
            self._spin_trig_event.setToolTip(tr("level.trigger_bgm_vol_tt"))
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        elif act in ("flip_sprite_h", "flip_sprite_v"):
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(False)
            self._spin_trig_event.setVisible(False)
            self._lbl_trig_param.setVisible(False)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(False)
        else:
            # Fallback: show both params
            self._combo_trig_scene.setVisible(False)
            self._combo_trig_target.setVisible(False)
            self._combo_trig_entity.setVisible(False)
            self._lbl_trig_evt.setVisible(True)
            self._spin_trig_event.setVisible(True)
            self._lbl_trig_param.setVisible(True)
            self._combo_trig_dest_region.setVisible(False)
            self._spin_trig_param.setVisible(True)
        # Show flag/var index widget for flag/variable actions.
        needs_fv_action = act in ("set_flag", "clear_flag", "set_variable", "inc_variable", "dec_variable", "toggle_flag", "init_game_vars")
        lbl_fv = getattr(self, "_lbl_trig_flag_var", None)
        spn_fv = getattr(self, "_spin_trig_flag_var", None)
        lbl_fv_name = getattr(self, "_lbl_trig_flag_var_name", None)
        if lbl_fv is not None:
            lbl_fv.setVisible(needs_fv_action)
        if spn_fv is not None:
            spn_fv.setVisible(needs_fv_action)
        if lbl_fv_name is not None:
            lbl_fv_name.setVisible(needs_fv_action)
        self._update_flag_var_tooltip()

    def _update_flag_var_tooltip(self) -> None:
        """Update the flag/var spinbox tooltip and inline name label."""
        spn_fv = getattr(self, "_spin_trig_flag_var", None)
        if spn_fv is None:
            return
        idx = int(spn_fv.value())
        cond = str(self._combo_trig_cond.currentData() or "")
        act  = str(self._combo_trig_action.currentData() or "")
        is_var = cond in _TRIGGER_VAR_CONDS or act in ("set_variable", "inc_variable", "dec_variable")
        lbl_name = getattr(self, "_lbl_trig_flag_var_name", None)
        if is_var:
            entry = {}
            if hasattr(self, "_project_game_vars") and idx < len(self._project_game_vars):
                entry = self._project_game_vars[idx]
            name = entry.get("name", "") or tr("proj.gamevars_unnamed_var", i=idx)
            init = int(entry.get("init", 0) or 0)
            spn_fv.setToolTip(tr("proj.gamevars_var_tooltip", i=idx, name=name, init=init))
            if lbl_name is not None:
                lbl_name.setText(f"— {name}" if entry.get("name") else f"— ({name})")
        else:
            name = ""
            if hasattr(self, "_project_game_flags") and idx < len(self._project_game_flags):
                name = self._project_game_flags[idx]
            raw_name = name
            name = name or tr("proj.gamevars_unnamed_flag", i=idx)
            spn_fv.setToolTip(tr("proj.gamevars_flag_tooltip", i=idx, name=name))
            if lbl_name is not None:
                lbl_name.setText(f"— {name}" if raw_name else f"— ({name})")

    def _on_trigger_selected(self, idx: int) -> None:
        self._trigger_selected = int(idx)
        self._refresh_trigger_props()

    def _on_trigger_cond_changed(self, _idx: int) -> None:
        self._update_trigger_ui_for_cond()
        self._on_trigger_prop_changed()
    
    def _on_trigger_action_changed(self, _idx: int) -> None:
        self._update_trigger_ui_for_action()
        self._on_trigger_prop_changed()

    def _on_pick_dest_toggled(self, checked: bool) -> None:
        """Enter/exit the tile-picker mode for move_entity_to destination."""
        self._pick_dest_mode = bool(checked)
        if checked:
            self._canvas.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self._canvas.unsetCursor()

    def _on_dest_tile_picked(self, tx: int, ty: int) -> None:
        """Called when the user clicks the canvas in pick-dest mode."""
        self._pick_dest_mode = False
        try:
            self._btn_trig_pick_dest.blockSignals(True)
            self._btn_trig_pick_dest.setChecked(False)
        finally:
            self._btn_trig_pick_dest.blockSignals(False)
        self._canvas.unsetCursor()
        idx = self._trigger_selected
        if not (0 <= idx < len(self._triggers)):
            return
        t = self._triggers[idx]
        self._push_undo()
        t["dest_tile_x"] = int(tx)
        t["dest_tile_y"] = int(ty)
        t["dest_region_id"] = ""  # tile coords take precedence
        self._lbl_trig_dest_tile.setText(f"\u2192 ({tx}, {ty})")
        self._lbl_trig_dest_tile.setVisible(True)
        self._combo_trig_dest_region.setVisible(False)
        self._lbl_trig_param.setVisible(False)
        self._spin_trig_param.setVisible(False)
        self._mark_dirty()
        self._canvas.update()

    def _clear_dest_tile(self) -> None:
        """Remove the dest_tile from the selected trigger (revert to region picker)."""
        idx = self._trigger_selected
        if not (0 <= idx < len(self._triggers)):
            return
        t = self._triggers[idx]
        self._push_undo()
        t["dest_tile_x"] = -1
        t["dest_tile_y"] = -1
        self._update_trigger_ui_for_action()
        self._mark_dirty()
        self._canvas.update()

    def _next_trigger_name(self, prefix: str = "trig") -> str:
        used = {str(t.get("name", "")).strip() for t in self._triggers}
        n = 1
        prefix = re.sub(r"[^a-zA-Z0-9_]+", "_", str(prefix or "trig")).strip("_") or "trig"
        while True:
            cand = f"{prefix}_{n}"
            if cand not in used:
                return cand
            n += 1

    def _selected_region_id(self) -> str:
        if 0 <= self._region_selected < len(self._regions):
            return str(self._regions[self._region_selected].get("id", "") or "")
        return ""

    def _selected_entity_target_id(self) -> str:
        if 0 <= self._selected < len(self._entities):
            return str(self._entities[self._selected].get("target_id", "") or "")
        return ""

    def _build_trigger_dict(self) -> dict:
        return {
            "id": _new_id(),
            "name": self._next_trigger_name(),
            "cond": "enter_region",
            "region_id": self._selected_region_id(),
            "value": 0,
            "action": "emit_event",
            "event": 0,
            "param": 0,
            "once": True,
        }

    def _apply_trigger_preset(self, trig: dict, preset_key: str) -> None:
        rid = self._selected_region_id()
        ent_target_id = self._selected_entity_target_id()
        base = {
            "cond": "enter_region",
            "region_id": rid,
            "value": 0,
            "value_const": 0,
            "action": "emit_event",
            "scene_to": "",
            "target_id": "",
            "entity_target_id": "",
            "entity_index": 0,
            "dest_region_id": "",
            "dest_tile_x": 0,
            "dest_tile_y": 0,
            "event": 0,
            "param": 0,
            "dialogue_id": "",
            "npc_dialogue_id": "",
            "menu_id": "",
            "cond_dialogue_id": "",
            "cond_menu_id": "",
            "cond_type_name": "",
            "cev_id": "",
            "item_id": "",
            "menu_item_idx": 0,
            "choice_idx": 0,
            "flag_var_index": 0,
            "spawn_index": 0,
            "a0": 0,
            "a1": 0,
            "once": False,
            "extra_conds": [],
        }
        trig.update(base)

        if preset_key == "menu_cursor_enter":
            trig["name"] = self._next_trigger_name("menu_cursor")
            trig["cond"] = "enter_region"
            trig["action"] = "move_entity_to"
            trig["entity_target_id"] = ent_target_id
            trig["dest_region_id"] = rid
            trig["once"] = False
        elif preset_key == "game_checkpoint_enter":
            trig["name"] = self._next_trigger_name("checkpoint")
            trig["cond"] = "enter_region"
            trig["action"] = "set_checkpoint"
            trig["once"] = False
        elif preset_key == "game_warp_next_scene":
            trig["name"] = self._next_trigger_name("warp_exit")
            trig["cond"] = "enter_region"
            trig["action"] = "warp_to"
            self._apply_next_scene_target(trig)
            trig["spawn_index"] = 0
            trig["param"] = 0
            trig["once"] = True
        elif preset_key == "game_exit_next_scene":
            trig["name"] = self._next_trigger_name("exit_goal")
            trig["cond"] = "enter_region"
            trig["action"] = "goto_scene"
            self._apply_next_scene_target(trig)
            trig["once"] = True
        elif preset_key == "game_door_up_next_scene":
            trig["name"] = self._next_trigger_name("door_exit")
            trig["cond"] = "btn_up"
            trig["action"] = "goto_scene"
            self._apply_next_scene_target(trig)
            trig["once"] = True
        elif preset_key == "game_respawn_on_death":
            trig["name"] = self._next_trigger_name("respawn_on_death")
            trig["cond"] = "on_death"
            trig["region_id"] = ""
            trig["action"] = "respawn_player"
            trig["once"] = False
        elif preset_key == "game_save_on_checkpoint":
            trig["name"] = self._next_trigger_name("save_checkpoint")
            trig["cond"] = "enter_region"
            trig["action"] = "save_game"
            trig["once"] = False
        elif preset_key == "menu_show_on_enter":
            trig["name"] = self._next_trigger_name("menu_show")
            trig["cond"] = "enter_region"
            trig["action"] = "show_entity"
            trig["entity_target_id"] = ent_target_id
            trig["once"] = False
        elif preset_key == "menu_hide_on_leave":
            trig["name"] = self._next_trigger_name("menu_hide")
            trig["cond"] = "leave_region"
            trig["action"] = "hide_entity"
            trig["entity_target_id"] = ent_target_id
            trig["once"] = False
        elif preset_key == "menu_open_on_enter":
            trig["name"] = self._next_trigger_name("menu_open")
            trig["cond"] = "enter_region"
            trig["action"] = "open_menu"
            trig["once"] = False
        elif preset_key == "menu_result_scene":
            trig["name"] = self._next_trigger_name("menu_result")
            trig["cond"] = "menu_result"
            trig["region_id"] = ""
            trig["action"] = "goto_scene"
            self._apply_next_scene_target(trig)
            trig["menu_item_idx"] = 0
            trig["value"] = 0
            trig["once"] = False
        elif preset_key == "menu_confirm_scene":
            trig["name"] = self._next_trigger_name("menu_confirm")
            trig["cond"] = "btn_a"
            trig["action"] = "goto_scene"
            self._apply_next_scene_target(trig)
            trig["once"] = True
        elif preset_key == "menu_hover_sfx":
            trig["name"] = self._next_trigger_name("menu_hover")
            trig["cond"] = "enter_region"
            trig["action"] = "play_sfx"
            trig["event"] = 0
            trig["once"] = False
        elif preset_key == "combat_player_fire_a":
            trig["name"] = self._next_trigger_name("player_fire")
            trig["cond"] = "btn_a"
            trig["action"] = "fire_player_shot"
            trig["once"] = False
        elif preset_key == "combat_player_attack_event":
            trig["name"] = self._next_trigger_name("player_attack")
            trig["cond"] = "btn_a"
            trig["action"] = "emit_event"
            trig["event"] = 1
            trig["param"] = 0
            trig["once"] = False
        elif preset_key == "hud_hide_on_health_le":
            trig["name"] = self._next_trigger_name("hud_hide_hp")
            trig["cond"] = "health_le"
            trig["value"] = 2
            trig["action"] = "hide_entity"
            trig["entity_target_id"] = ent_target_id
            trig["once"] = False
        elif preset_key == "hud_show_on_health_ge":
            trig["name"] = self._next_trigger_name("hud_show_hp")
            trig["cond"] = "health_ge"
            trig["value"] = 3
            trig["action"] = "show_entity"
            trig["entity_target_id"] = ent_target_id
            trig["once"] = False
        elif preset_key == "race_lap_gate_crossed":
            # emit_event when player crosses a lap_gate region (lap_ge condition)
            trig["name"] = self._next_trigger_name("lap_gate")
            trig["cond"] = "lap_ge"
            trig["value"] = 1
            trig["action"] = "emit_event"
            trig["event"] = 1
            trig["param"] = 0
            trig["once"] = False
        elif preset_key == "race_countdown_start":
            # On scene enter: lock input + set timer — unlock when timer reaches 0
            trig["name"] = self._next_trigger_name("countdown_start")
            trig["cond"] = "scene_first_enter"
            trig["action"] = "lock_player_input"
            trig["once"] = True
        elif preset_key == "race_countdown_unlock":
            trig["name"] = self._next_trigger_name("countdown_go")
            trig["cond"] = "timer_ge"
            trig["region_id"] = ""
            trig["value"] = 180
            trig["action"] = "unlock_player_input"
            trig["once"] = True
        elif preset_key == "puzzle_block_on_target":
            # A pushable block has landed on a specific region → play sfx + set flag
            trig["name"] = self._next_trigger_name("block_target")
            trig["cond"] = "block_on_tile"
            trig["region_id"] = rid
            trig["action"] = "play_sfx"
            trig["event"] = 0
            trig["param"] = 0
            trig["once"] = False
        elif preset_key == "puzzle_all_switches_done":
            # All switches in group 0 are active → goto next scene
            trig["name"] = self._next_trigger_name("all_done")
            trig["cond"] = "all_switches_on"
            trig["flag_var_index"] = 0
            trig["value"] = 1
            trig["action"] = "goto_scene"
            self._apply_next_scene_target(trig)
            trig["once"] = True
        elif preset_key == "puzzle_reset_on_death":
            # Player falls in void_pit or dies → reset_scene
            trig["name"] = self._next_trigger_name("reset_on_death")
            trig["cond"] = "on_death"
            trig["action"] = "reset_scene"
            trig["once"] = False
        elif preset_key == "puzzle_door_toggle":
            # All switches on → toggle door tile (open passage)
            trig["name"] = self._next_trigger_name("door_open")
            trig["cond"] = "all_switches_on"
            trig["flag_var_index"] = 0
            trig["value"] = 1
            trig["action"] = "toggle_tile"
            trig["dest_region_id"] = rid
            trig["param"] = 0   # tile type 0 = PASS (open)
            trig["once"] = True
        elif preset_key == "dialog_show_on_enter":
            trig["name"] = self._next_trigger_name("dialog_enter")
            trig["cond"] = "enter_region"
            trig["action"] = "show_dialogue"
            trig["once"] = True
        elif preset_key == "dialog_npc_talk_show":
            trig["name"] = self._next_trigger_name("npc_talk")
            trig["cond"] = "npc_talked_to"
            trig["region_id"] = ""
            trig["value"] = 0
            trig["action"] = "show_dialogue"
            trig["once"] = False
        elif preset_key == "tcg_draw_phase":
            # On scene enter: spawn N card entities from the deck pool
            trig["name"] = self._next_trigger_name("draw_phase")
            trig["cond"] = "scene_first_enter"
            trig["action"] = "spawn_entity"
            trig["event"] = 0
            trig["param"] = 0   # entity type index for "card" entity
            trig["once"] = True
        elif preset_key == "tcg_card_to_slot":
            # Card entity enters a card_slot region → emit event "card played"
            trig["name"] = self._next_trigger_name("card_played")
            trig["cond"] = "entity_in_region"
            trig["region_id"] = rid
            trig["action"] = "emit_event"
            trig["event"] = 1   # event ID 1 = "card played"
            trig["param"] = 0
            trig["once"] = False
        elif preset_key == "tcg_turn_end":
            # Variable (cards played count) >= N → emit event "turn end"
            trig["name"] = self._next_trigger_name("turn_end")
            trig["cond"] = "variable_ge"
            trig["flag_var_index"] = 0  # variable 0 = "cards played this turn"
            trig["value"] = 1           # N = 1 card played → end turn (user adjusts)
            trig["action"] = "emit_event"
            trig["event"] = 2           # event ID 2 = "turn end"
            trig["param"] = 0
            trig["once"] = False

    def _add_trigger_preset(self) -> None:
        preset_key = str(self._combo_trig_preset.currentData() or "").strip()
        if not preset_key:
            return
        self._push_undo()
        trig = self._build_trigger_dict()
        self._apply_trigger_preset(trig, preset_key)
        self._triggers.append(trig)
        self._trigger_selected = len(self._triggers) - 1
        self._refresh_trigger_list()
        self._refresh_trigger_props()
        self._canvas.update()
        self._update_diagnostics()

    def _add_trigger_from_selected_region(self, cond: str) -> None:
        rid = self._selected_region_id()
        if not rid:
            QMessageBox.information(self, tr("level.save_title"), tr("level.trigger_quick_need_region"))
            return
        self._push_undo()
        trig = self._build_trigger_dict()
        trig["cond"] = str(cond or "enter_region")
        trig["region_id"] = rid
        trig["name"] = self._next_trigger_name("enter_zone" if trig["cond"] == "enter_region" else "leave_zone")
        self._triggers.append(trig)
        self._trigger_selected = len(self._triggers) - 1
        self._refresh_trigger_list()
        self._refresh_trigger_props()
        self._canvas.update()
        self._update_diagnostics()

    def _add_trigger(self) -> None:
        self._push_undo()
        t = self._build_trigger_dict()
        self._triggers.append(t)
        self._trigger_selected = len(self._triggers) - 1
        self._refresh_trigger_list()
        self._refresh_trigger_props()
        self._canvas.update()
        self._update_diagnostics()

    def _remove_trigger(self) -> None:
        idx = int(self._trigger_selected)
        if not (0 <= idx < len(self._triggers)):
            return
        self._push_undo()
        del self._triggers[idx]
        self._trigger_selected = min(idx, len(self._triggers) - 1)
        self._refresh_trigger_list()
        self._refresh_trigger_props()
        self._canvas.update()
        self._update_diagnostics()

    def _duplicate_trigger(self) -> None:
        idx = int(self._trigger_selected)
        if not (0 <= idx < len(self._triggers)):
            return
        self._push_undo()
        src = self._triggers[idx]
        dup = copy.deepcopy(src)
        dup["id"] = _new_id()
        # Assign a unique name: append _2, _3... until free
        base = str(src.get("name", "trigger") or "trigger").rstrip("0123456789").rstrip("_")
        used = {str(t.get("name", "")) for t in self._triggers}
        n = 2
        while True:
            cand = f"{base}_{n}"
            if cand not in used:
                break
            n += 1
        dup["name"] = cand
        self._triggers.insert(idx + 1, dup)
        self._trigger_selected = idx + 1
        self._refresh_trigger_list()
        self._refresh_trigger_props()
        self._canvas.update()
        self._update_diagnostics()

    def _on_trigger_prop_changed(self, *_args) -> None:
        idx = int(self._trigger_selected)
        if not (0 <= idx < len(self._triggers)):
            return
        t = self._triggers[idx]
        t["name"] = str(self._edit_trig_name.text()).strip() or t.get("name", "")
        t["cond"] = str(self._combo_trig_cond.currentData() or "enter_region")
        t["region_id"] = str(self._combo_trig_region.currentData() or "")
        t["action"] = str(self._combo_trig_action.currentData() or "emit_event")
        t["value"] = self._spin_trig_value.value()
        t["value_const"] = self._spin_trig_value.const_name()
        # NPC/entity combo overrides value
        npc_cmb = getattr(self, "_combo_trig_npc_entity", None)
        if npc_cmb is not None and npc_cmb.isVisible():
            src_idx_data = npc_cmb.currentData()
            if src_idx_data is not None:
                t["value"] = int(src_idx_data)
        act_now = str(t.get("action") or "").strip().lower()
        if act_now == "start_bgm" and self._combo_trig_bgm.isVisible():
            bgm_idx = self._combo_trig_bgm.currentData()
            if bgm_idx is not None:
                t["event"] = int(bgm_idx) & 0xFF
                self._spin_trig_event.blockSignals(True)
                try:
                    self._spin_trig_event.setValue(t["event"])
                finally:
                    self._spin_trig_event.blockSignals(False)
        elif act_now == "play_sfx" and self._combo_trig_sfx.isVisible():
            sfx_idx = self._combo_trig_sfx.currentData()
            if sfx_idx is not None:
                t["event"] = int(sfx_idx) & 0xFF
                self._spin_trig_event.blockSignals(True)
                try:
                    self._spin_trig_event.setValue(t["event"])
                finally:
                    self._spin_trig_event.blockSignals(False)
        elif act_now in ("goto_scene", "warp_to") and self._combo_trig_scene.isVisible():
            sid = str(self._combo_trig_scene.currentData() or "").strip()
            t["scene_to"] = sid
            si = self._scene_idx_for_id(sid)
            if si is None:
                si = int(self._spin_trig_event.value())
            t["event"] = int(si) & 0xFF
            self._spin_trig_event.blockSignals(True)
            try:
                self._spin_trig_event.setValue(int(t["event"]))
            finally:
                self._spin_trig_event.blockSignals(False)
            if act_now == "warp_to":
                t["spawn_index"] = int(self._spin_trig_param.value())
            elif self._combo_trig_dest_region.isVisible():
                t["dest_region_id"] = str(self._combo_trig_dest_region.currentData() or "").strip()
        elif act_now in ("show_entity", "hide_entity", "move_entity_to", "pause_entity_path", "resume_entity_path") and self._combo_trig_entity.isVisible():
            ent_target_id = str(self._combo_trig_entity.currentData() or "").strip()
            ent_idx = self._entity_index_for_target_id(ent_target_id)
            if ent_idx is None:
                ent_idx = int(self._spin_trig_event.value())
            t["entity_target_id"] = ent_target_id
            t["entity_index"] = int(ent_idx)
            t["event"] = int(ent_idx) & 0xFF
            self._spin_trig_event.blockSignals(True)
            try:
                self._spin_trig_event.setValue(int(t["event"]))
            finally:
                self._spin_trig_event.blockSignals(False)
            if act_now == "move_entity_to" and self._combo_trig_dest_region.isVisible():
                rid = str(self._combo_trig_dest_region.currentData() or "").strip()
                t["dest_region_id"] = rid
                ridx = next(
                    (i for i, reg in enumerate(self._regions)
                     if str(reg.get("id", "") or "").strip() == rid),
                    int(self._spin_trig_param.value()),
                )
                self._spin_trig_param.blockSignals(True)
                try:
                    self._spin_trig_param.setValue(int(ridx) & 0xFF)
                finally:
                    self._spin_trig_param.blockSignals(False)
        elif act_now in ("teleport_player", "spawn_at_region") and self._combo_trig_dest_region.isVisible():
            rid = str(self._combo_trig_dest_region.currentData() or "").strip()
            ridx = next(
                (i for i, reg in enumerate(self._regions)
                 if str(reg.get("id", "") or "").strip() == rid),
                int(self._spin_trig_param.value()),
            )
            t["dest_region_id"] = rid
            self._spin_trig_param.blockSignals(True)
            try:
                self._spin_trig_param.setValue(int(ridx) & 0xFF)
            finally:
                self._spin_trig_param.blockSignals(False)
        elif act_now == "toggle_tile" and self._combo_trig_dest_region.isVisible():
            rid = str(self._combo_trig_dest_region.currentData() or "").strip()
            t["dest_region_id"] = rid
            ridx = next(
                (i for i, reg in enumerate(self._regions)
                 if str(reg.get("id", "") or "").strip() == rid),
                0,
            )
            t["a0"] = int(ridx) & 0xFF
            # a1 = tile type — preserved from _spin_trig_param if visible,
            # or kept from existing t["param"]
            if self._spin_trig_param.isVisible():
                t["param"] = int(self._spin_trig_param.value())
        elif act_now == "show_dialogue" and self._combo_trig_dialogue.isVisible():
            did = str(self._combo_trig_dialogue.currentData() or "").strip()
            t["dialogue_id"] = did
            dlgs = (self._scene or {}).get("dialogues") or []
            didx = next((i for i, d in enumerate(dlgs)
                         if str(d.get("id", "") or "").strip() == did), 0)
            t["a0"] = int(didx) & 0xFF
        elif act_now == "open_menu":
            cm = getattr(self, "_combo_trig_menu", None)
            if cm is not None and cm.isVisible():
                mid = str(cm.currentData() or "").strip()
                t["menu_id"] = mid
                menus = (self._scene or {}).get("menus") or []
                midx = next((i for i, m in enumerate(menus)
                             if str(m.get("id", "") or "").strip() == mid), 0)
                t["a0"] = int(midx) & 0xFF
        elif act_now == "set_npc_dialogue" and self._combo_trig_entity.isVisible():
            ent_target_id = str(self._combo_trig_entity.currentData() or "").strip()
            ent_idx = self._entity_index_for_target_id(ent_target_id) or 0
            t["entity_target_id"] = ent_target_id
            t["a0"] = int(ent_idx) & 0xFF
            if self._combo_trig_dialogue.isVisible():
                npc_did = str(self._combo_trig_dialogue.currentData() or "").strip()
                t["npc_dialogue_id"] = npc_did
                dlgs = (self._scene or {}).get("dialogues") or []
                npc_didx = next((i for i, d in enumerate(dlgs)
                                 if str(d.get("id", "") or "").strip() == npc_did), 0)
                t["a1"] = int(npc_didx) & 0xFF

        # Save cond_menu_id + menu_item_idx for menu_result condition
        ccm = getattr(self, "_combo_trig_cond_menu", None)
        cmi = getattr(self, "_combo_trig_menu_item", None)
        if ccm is not None and ccm.isVisible():
            cmid = str(ccm.currentData() or "").strip()
            t["cond_menu_id"] = cmid
            menus = (self._scene or {}).get("menus") or []
            cmidx = next((i for i, m in enumerate(menus)
                          if str(m.get("id", "") or "").strip() == cmid), 0)
            region_from_menu = int(cmidx) & 0xFF
            t["region"] = region_from_menu
            if cmi is not None:
                item_idx = int(cmi.currentData() or 0)
                t["menu_item_idx"] = item_idx
                t["value"] = item_idx
        # Save cond_dialogue_id for dialogue_done / choice_result conditions
        ccd = getattr(self, "_combo_trig_cond_dialogue", None)
        if ccd is not None and ccd.isVisible():
            cdid = str(ccd.currentData() or "").strip()
            t["cond_dialogue_id"] = cdid
            dlgs = (self._scene or {}).get("dialogues") or []
            cdidx = next((i for i, d in enumerate(dlgs)
                          if str(d.get("id", "") or "").strip() == cdid), 0)
            # For choice_result: region = dialogue_idx, value = choice_idx
            cond_now = str(self._combo_trig_cond.currentData() or "")
            if cond_now in _TRIGGER_CHOICE_CONDS:
                t["region"] = int(cdidx)
                sci = getattr(self, "_spin_trig_choice_idx", None)
                t["choice_idx"] = int(sci.value() if sci else 0)
                t["value"] = int(sci.value() if sci else 0)
            else:
                t["value"] = int(cdidx)
        elif act_now in ("enable_trigger", "disable_trigger") and self._combo_trig_target.isVisible():
            tid = str(self._combo_trig_target.currentData() or "").strip()
            t["target_id"] = tid
            # Resolve to index for a0
            tidx = next((i for i, tr in enumerate(self._triggers)
                         if str(tr.get("id", "")) == tid), 255)
            t["event"] = int(tidx) & 0xFF
            self._spin_trig_event.blockSignals(True)
            try:
                self._spin_trig_event.setValue(t["event"])
            finally:
                self._spin_trig_event.blockSignals(False)
        else:
            t["scene_to"] = str(t.get("scene_to", "") or "")
            t["target_id"] = str(t.get("target_id", "") or "")
            t["entity_target_id"] = str(t.get("entity_target_id", "") or "")
            t["event"] = int(self._spin_trig_event.value())
        if act_now == "move_entity_to" and not self._combo_trig_dest_region.isVisible():
            t["dest_region_id"] = str(t.get("dest_region_id", "") or "")
        t["param"] = int(self._spin_trig_param.value())
        t["once"] = bool(self._chk_trig_once.isChecked())
        # Persist flag/variable index for flag/var conditions and actions.
        spn_fv = getattr(self, "_spin_trig_flag_var", None)
        if spn_fv is not None and spn_fv.isVisible():
            t["flag_var_index"] = int(spn_fv.value())
        # Persist cond_type_name for entity_type_* conditions.
        cmb_et = getattr(self, "_combo_trig_entity_type", None)
        if cmb_et is not None and cmb_et.isVisible():
            t["cond_type_name"] = str(cmb_et.currentData() or "")
        # Persist cev_id for on_custom_event condition.
        cmb_cev = getattr(self, "_combo_trig_cev", None)
        if cmb_cev is not None and cmb_cev.isVisible():
            t["cev_id"] = str(cmb_cev.currentData() or "")
        # Persist item_id for give_item / remove_item / drop_item actions
        # and player_has_item / item_count_ge conditions.
        cmb_it = getattr(self, "_combo_trig_item", None)
        if cmb_it is not None and cmb_it.isVisible():
            item_name = str(cmb_it.currentData() or "")
            t["item_id"] = item_name
            pd = self._project_data_root if isinstance(self._project_data_root, dict) else {}
            item_list = pd.get("item_table", []) or []
            item_idx = next(
                (i for i, it in enumerate(item_list)
                 if isinstance(it, dict) and str(it.get("name", "") or "") == item_name),
                0,
            )
            # item_count_ge: item_idx goes to region (not event); value spinner holds count
            cond_now = str(self._combo_trig_cond.currentData() or "")
            if cond_now != "item_count_ge":
                t["event"] = int(item_idx) & 0xFF
                self._spin_trig_event.blockSignals(True)
                try:
                    self._spin_trig_event.setValue(t["event"])
                finally:
                    self._spin_trig_event.blockSignals(False)
        self._refresh_trigger_list()
        self._canvas.update()
        self._update_diagnostics()

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    def _next_path_name(self) -> str:
        used = {str(p.get("name", "")).strip() for p in self._paths if isinstance(p, dict)}
        n = 1
        while True:
            cand = f"path_{n}"
            if cand not in used:
                return cand
            n += 1

    def _set_path_props_enabled(self, enabled: bool) -> None:
        for w in (
            self._edit_path_name, self._chk_path_loop, self._spn_path_speed,
            self._path_point_list, self._btn_path_pt_add, self._btn_path_pt_del,
            self._spn_path_pt_x, self._spn_path_pt_y,
        ):
            try:
                w.setEnabled(bool(enabled))
            except Exception:
                pass
        self._btn_path_del.setEnabled(bool(enabled))

    def _refresh_path_list(self) -> None:
        self._path_list.blockSignals(True)
        try:
            self._path_list.clear()
            loop_tag = tr("level.path_loop_tag")
            for p in self._paths:
                nm = str(p.get("name", "") or "path")
                pts = p.get("points", []) or []
                loop = bool(p.get("loop", False))
                assigned = len(self._entities_for_path_id(str(p.get("id", "") or "")))
                self._path_list.addItem(
                    tr(
                        "level.path_list_item",
                        name=nm,
                        n=len(pts),
                        assigned=assigned,
                        loop=(loop_tag if loop else ""),
                    )
                )
            if 0 <= self._path_selected < self._path_list.count():
                self._path_list.setCurrentRow(self._path_selected)
        finally:
            self._path_list.blockSignals(False)
        self._set_path_props_enabled(0 <= self._path_selected < len(self._paths))
        self._refresh_ent_path_combo()
        self._sync_scene_tool_buttons()

    def _refresh_path_points(self, *, no_list_rebuild: bool = False) -> None:
        if not (0 <= self._path_selected < len(self._paths)):
            self._path_point_list.clear()
            self._sync_path_point_coord_spinboxes()
            return
        path = self._paths[self._path_selected]
        pts = path.get("points", []) or []
        if not isinstance(pts, list):
            pts = []
        if no_list_rebuild:
            idx = int(self._path_point_selected)
            if 0 <= idx < self._path_point_list.count() and 0 <= idx < len(pts):
                self._path_point_list.item(idx).setText(_path_point_label(idx, pts[idx]))
            self._sync_path_point_coord_spinboxes()
            return

        self._path_point_list.blockSignals(True)
        try:
            self._path_point_list.clear()
            for i, pt in enumerate(pts):
                self._path_point_list.addItem(_path_point_label(i, pt))
            if 0 <= self._path_point_selected < self._path_point_list.count():
                self._path_point_list.setCurrentRow(self._path_point_selected)
        finally:
            self._path_point_list.blockSignals(False)
        self._sync_path_point_coord_spinboxes()

    def _refresh_path_props(self) -> None:
        if 0 <= self._path_selected < len(self._paths):
            p = self._paths[self._path_selected]
            self._edit_path_name.blockSignals(True)
            self._chk_path_loop.blockSignals(True)
            self._spn_path_speed.blockSignals(True)
            try:
                self._edit_path_name.setText(str(p.get("name", "") or ""))
                self._chk_path_loop.setChecked(bool(p.get("loop", False)))
                self._spn_path_speed.setValue(max(1, min(8, int(p.get("speed", 1)))))
            finally:
                self._edit_path_name.blockSignals(False)
                self._chk_path_loop.blockSignals(False)
                self._spn_path_speed.blockSignals(False)
            self._set_path_props_enabled(True)
            self._refresh_path_points()
        else:
            self._edit_path_name.setText("")
            self._chk_path_loop.setChecked(False)
            self._path_point_list.clear()
            self._set_path_props_enabled(False)
        self._refresh_path_assignment_ui()

    def _add_path(self) -> None:
        self._push_undo()
        p = {"id": _new_id(), "name": self._next_path_name(), "loop": False, "speed": 1, "points": []}
        self._paths.append(p)
        self._path_selected = len(self._paths) - 1
        self._path_point_selected = -1
        self._refresh_path_list()
        self._refresh_path_props()
        self._canvas.update()
        self._update_diagnostics()

    def _remove_path(self) -> None:
        idx = int(self._path_selected)
        if not (0 <= idx < len(self._paths)):
            return
        self._push_undo()
        del self._paths[idx]
        self._path_selected = min(idx, len(self._paths) - 1)
        self._path_point_selected = -1
        self._refresh_path_list()
        self._refresh_path_props()
        self._canvas.update()
        self._update_diagnostics()

    def _on_path_selected(self, idx: int) -> None:
        self._path_selected = int(idx)
        self._path_point_selected = -1
        self._refresh_path_props()
        self._canvas.update()

    def _on_path_point_selected(self, idx: int) -> None:
        self._path_point_selected = int(idx)
        self._sync_path_point_coord_spinboxes()
        self._canvas.update()

    def _sync_path_point_coord_spinboxes(self) -> None:
        max_x, max_y = self._path_px_limits()
        for spn, lim in ((self._spn_path_pt_x, max_x), (self._spn_path_pt_y, max_y)):
            spn.blockSignals(True)
            try:
                spn.setRange(0, max(0, lim))
            finally:
                spn.blockSignals(False)
        pt = None
        if 0 <= self._path_selected < len(self._paths):
            pts = self._paths[self._path_selected].get("points", []) or []
            idx = int(self._path_point_selected)
            if 0 <= idx < len(pts):
                pt = pts[idx]
        has_pt = pt is not None
        px, py = _path_point_to_px(pt) if has_pt else (0, 0)
        for spn, v in ((self._spn_path_pt_x, px), (self._spn_path_pt_y, py)):
            spn.blockSignals(True)
            try:
                spn.setValue(int(v))
                spn.setEnabled(has_pt and self._path_point_list.isEnabled())
            finally:
                spn.blockSignals(False)

    def _on_path_point_coord_changed(self, *_args) -> None:
        if not (0 <= self._path_selected < len(self._paths)):
            return
        pts = self._paths[self._path_selected].get("points", []) or []
        idx = int(self._path_point_selected)
        if not (0 <= idx < len(pts)):
            return
        new_pt = _path_point_make(
            int(self._spn_path_pt_x.value()),
            int(self._spn_path_pt_y.value()),
        )
        cur_px, cur_py = _path_point_to_px(pts[idx])
        if (int(new_pt["px"]), int(new_pt["py"])) == (int(cur_px), int(cur_py)):
            return
        self._push_undo()
        pts[idx] = new_pt
        self._refresh_path_points(no_list_rebuild=True)
        self._canvas.update()
        self._update_diagnostics()

    def _on_path_prop_changed(self, *_args) -> None:
        idx = int(self._path_selected)
        if not (0 <= idx < len(self._paths)):
            return
        p = self._paths[idx]
        p["name"] = str(self._edit_path_name.text()).strip() or p.get("name", "")
        p["loop"] = bool(self._chk_path_loop.isChecked())
        p["speed"] = int(self._spn_path_speed.value())
        self._refresh_path_list()
        self._canvas.update()
        self._update_diagnostics()

    def _on_path_edit_toggled(self, on: bool) -> None:
        self._set_scene_tool("path" if on else "entity")

    def _add_path_point(self) -> None:
        if not (0 <= self._path_selected < len(self._paths)):
            return
        self._push_undo()
        p = self._paths[self._path_selected]
        pts = p.get("points", []) or []
        tx, ty = self._cam_tile
        pts.append(_path_point_make(int(tx) * _TILE_PX, int(ty) * _TILE_PX))
        p["points"] = pts
        self._path_point_selected = len(pts) - 1
        self._refresh_path_list()
        self._refresh_path_points()
        self._canvas.update()
        self._update_diagnostics()

    def _remove_path_point(self) -> None:
        if not (0 <= self._path_selected < len(self._paths)):
            return
        p = self._paths[self._path_selected]
        pts = p.get("points", []) or []
        if not pts:
            return
        idx = int(self._path_point_selected)
        if not (0 <= idx < len(pts)):
            idx = len(pts) - 1
        self._push_undo()
        del pts[idx]
        p["points"] = pts
        self._path_point_selected = min(idx, len(pts) - 1)
        self._refresh_path_list()
        self._refresh_path_points()
        self._canvas.update()
        self._update_diagnostics()
    # ------------------------------------------------------------------
    # Regions
    # ------------------------------------------------------------------

    def _region_at_tile(self, tx: int, ty: int) -> int:
        for i, r in enumerate(self._regions):
            x = int(r.get("x", 0))
            y = int(r.get("y", 0))
            w = max(1, int(r.get("w", 1)))
            h = max(1, int(r.get("h", 1)))
            if x <= tx < x + w and y <= ty < y + h:
                return i
        return -1

    def _refresh_region_list(self) -> None:
        self._reg_list.blockSignals(True)
        try:
            self._reg_list.clear()
            for r in self._regions:
                nm = str(r.get("name", "") or "region")
                kind = str(r.get("kind", "zone") or "zone")
                x = int(r.get("x", 0))
                y = int(r.get("y", 0))
                w = int(r.get("w", 1))
                h = int(r.get("h", 1))
                self._reg_list.addItem(f"{nm}  [{kind}]  ({x},{y}) {w}×{h}")
            if 0 <= self._region_selected < self._reg_list.count():
                self._reg_list.setCurrentRow(int(self._region_selected))
        finally:
            self._reg_list.blockSignals(False)
        self._btn_reg_del.setEnabled(0 <= self._region_selected < len(self._regions))
        self._refresh_trigger_regions()
        self._sync_scene_tool_buttons()

    def _set_region_props_enabled(self, enabled: bool) -> None:
        for w in (
            self._edit_reg_name, self._combo_reg_kind,
            self._spin_reg_x, self._spin_reg_y, self._spin_reg_w, self._spin_reg_h,
            self._spin_reg_gate, self._spin_reg_wp, self._spin_reg_slot_type,
        ):
            w.setEnabled(enabled)

    def _refresh_region_props(self) -> None:
        idx = int(self._region_selected)
        if not (0 <= idx < len(self._regions)):
            self._set_region_props_enabled(False)
            try:
                self._edit_reg_name.setText("")
            except Exception:
                pass
            self._btn_reg_del.setEnabled(False)
            self._lbl_gate_index.hide()
            self._spin_reg_gate.hide()
            self._lbl_wp_index.hide()
            self._spin_reg_wp.hide()
            self._lbl_slot_type.hide()
            self._spin_reg_slot_type.hide()
            self._canvas.update()
            return

        r = self._regions[idx]
        self._set_region_props_enabled(True)
        self._btn_reg_del.setEnabled(True)
        self._edit_reg_name.blockSignals(True)
        self._combo_reg_kind.blockSignals(True)
        self._spin_reg_x.blockSignals(True)
        self._spin_reg_y.blockSignals(True)
        self._spin_reg_w.blockSignals(True)
        self._spin_reg_h.blockSignals(True)
        self._spin_reg_gate.blockSignals(True)
        self._spin_reg_wp.blockSignals(True)
        self._spin_reg_slot_type.blockSignals(True)
        try:
            self._edit_reg_name.setText(str(r.get("name", "")))
            k = str(r.get("kind", "zone") or "zone")
            ki = self._combo_reg_kind.findData(k)
            self._combo_reg_kind.setCurrentIndex(ki if ki >= 0 else 0)
            self._spin_reg_x.setValue(int(r.get("x", 0)))
            self._spin_reg_y.setValue(int(r.get("y", 0)))
            self._spin_reg_w.setValue(max(1, int(r.get("w", 1))))
            self._spin_reg_h.setValue(max(1, int(r.get("h", 1))))
            is_gate = (k == "lap_gate")
            self._lbl_gate_index.setVisible(is_gate)
            self._spin_reg_gate.setVisible(is_gate)
            self._spin_reg_gate.setValue(max(0, min(31, int(r.get("gate_index", 0)))))
            is_wp = (k == "race_waypoint")
            self._lbl_wp_index.setVisible(is_wp)
            self._spin_reg_wp.setVisible(is_wp)
            self._spin_reg_wp.setValue(max(0, min(63, int(r.get("wp_index", 0)))))
            is_card_slot = (k == "card_slot")
            self._lbl_slot_type.setVisible(is_card_slot)
            self._spin_reg_slot_type.setVisible(is_card_slot)
            self._spin_reg_slot_type.setValue(max(0, min(15, int(r.get("slot_type", 0)))))
        finally:
            self._edit_reg_name.blockSignals(False)
            self._combo_reg_kind.blockSignals(False)
            self._spin_reg_x.blockSignals(False)
            self._spin_reg_y.blockSignals(False)
            self._spin_reg_w.blockSignals(False)
            self._spin_reg_h.blockSignals(False)
            self._spin_reg_gate.blockSignals(False)
            self._spin_reg_wp.blockSignals(False)
            self._spin_reg_slot_type.blockSignals(False)
        self._canvas.update()

    def _on_region_selected(self, idx: int) -> None:
        self._region_selected = int(idx)
        self._refresh_region_props()

    def _on_region_edit_toggled(self, on: bool) -> None:
        self._set_scene_tool("region" if on else "entity")

    def _next_region_name(self) -> str:
        used = {str(r.get("name", "")).strip() for r in self._regions}
        n = 1
        while True:
            cand = f"region_{n}"
            if cand not in used:
                return cand
            n += 1

    def _next_region_name_from_base(self, base: str) -> str:
        base = re.sub(r"[^a-zA-Z0-9_]+", "_", str(base or "region").strip()).strip("_") or "region"
        used = {str(r.get("name", "")).strip() for r in self._regions}
        if base not in used:
            return base
        n = 2
        while True:
            cand = f"{base}_{n}"
            if cand not in used:
                return cand
            n += 1

    def _build_region_preset(self, preset_key: str) -> dict | None:
        cam_x, cam_y = self._cam_tile
        if preset_key == "checkpoint":
            x = int(cam_x) + (_SCREEN_W // 2) - 2
            y = int(cam_y) + (_SCREEN_H // 2) - 2
            w, h = 4, 4
            kind = "checkpoint"
            name = self._next_region_name_from_base("checkpoint")
        elif preset_key == "camera_lock":
            x = int(cam_x)
            y = int(cam_y)
            w, h = _SCREEN_W, _SCREEN_H
            kind = "camera_lock"
            name = self._next_region_name_from_base("camera_lock")
        elif preset_key == "exit_goal":
            x = int(cam_x) + _SCREEN_W - 3
            y = int(cam_y) + _SCREEN_H - 5
            w, h = 3, 5
            kind = "exit_goal"
            name = self._next_region_name_from_base("exit_goal")
        elif preset_key == "spawn_point":
            x = int(cam_x) + (_SCREEN_W // 2) - 1
            y = int(cam_y) + (_SCREEN_H // 2) - 1
            w, h = 3, 3
            kind = "spawn"
            name = self._next_region_name_from_base("spawn")
        elif preset_key == "spawn_safe":
            x = int(cam_x) + (_SCREEN_W // 2) - 4
            y = int(cam_y) + (_SCREEN_H // 2) - 3
            w, h = 8, 6
            kind = "no_spawn"
            name = self._next_region_name_from_base("spawn_safe")
        elif preset_key == "hazard_floor":
            x = int(cam_x) + (_SCREEN_W // 2) - 4
            y = int(cam_y) + _SCREEN_H - 2
            w, h = 8, 2
            kind = "danger_zone"
            name = self._next_region_name_from_base("hazard_floor")
        elif preset_key == "zone_marker":
            x = int(cam_x) + (_SCREEN_W // 2) - 2
            y = int(cam_y) + (_SCREEN_H // 2) - 2
            w, h = 4, 4
            kind = "zone"
            name = self._next_region_name_from_base("zone")
        elif preset_key == "attractor":
            x = int(cam_x) + (_SCREEN_W // 2) - 3
            y = int(cam_y) + (_SCREEN_H // 2) - 3
            w, h = 6, 6
            kind = "attractor"
            name = self._next_region_name_from_base("attractor")
        elif preset_key == "repulsor":
            x = int(cam_x) + (_SCREEN_W // 2) - 3
            y = int(cam_y) + (_SCREEN_H // 2) - 3
            w, h = 6, 6
            kind = "repulsor"
            name = self._next_region_name_from_base("repulsor")
        elif preset_key == "lap_gate":
            # Thin horizontal strip across the track — gate_index auto-increments
            existing_gates = [r for r in self._regions if isinstance(r, dict) and r.get("kind") == "lap_gate"]
            gate_index = len(existing_gates)
            x = int(cam_x) + (_SCREEN_W // 2) - 4
            y = int(cam_y) + (_SCREEN_H // 2) - 1
            w, h = 8, 2
            kind = "lap_gate"
            name = self._next_region_name_from_base("gate_0" if gate_index == 0 else f"gate_{gate_index}")
            x = max(0, min(int(self._grid_w) - 1, int(x)))
            y = max(0, min(int(self._grid_h) - 1, int(y)))
            w = max(1, min(int(w), max(1, int(self._grid_w) - x)))
            h = max(1, min(int(h), max(1, int(self._grid_h) - y)))
            return {"id": _new_id(), "name": name, "kind": kind, "x": x, "y": y, "w": w, "h": h, "gate_index": gate_index}
        elif preset_key == "push_block":
            # 1×1 tile pushable block at camera center — index auto-increments
            existing_pbs = [r for r in self._regions if isinstance(r, dict) and r.get("kind") == "push_block"]
            x = int(cam_x) + (_SCREEN_W // 2)
            y = int(cam_y) + (_SCREEN_H // 2)
            x = max(0, min(int(self._grid_w) - 1, int(x)))
            y = max(0, min(int(self._grid_h) - 1, int(y)))
            name = self._next_region_name_from_base(f"block_{len(existing_pbs)}")
            return {"id": _new_id(), "name": name, "kind": "push_block",
                    "x": x, "y": y, "w": 1, "h": 1}
        elif preset_key == "race_waypoint":
            # Small square at camera center — wp_index auto-increments
            existing_wps = [r for r in self._regions if isinstance(r, dict) and r.get("kind") == "race_waypoint"]
            wp_index = len(existing_wps)
            x = int(cam_x) + (_SCREEN_W // 2) - 1
            y = int(cam_y) + (_SCREEN_H // 2) - 1
            w, h = 2, 2
            name = self._next_region_name_from_base(f"wp_{wp_index}")
            x = max(0, min(int(self._grid_w) - 1, int(x)))
            y = max(0, min(int(self._grid_h) - 1, int(y)))
            w = max(1, min(int(w), max(1, int(self._grid_w) - x)))
            h = max(1, min(int(h), max(1, int(self._grid_h) - y)))
            return {"id": _new_id(), "name": name, "kind": "race_waypoint", "x": x, "y": y, "w": w, "h": h, "wp_index": wp_index}
        elif preset_key == "card_slot":
            existing_slots = [r for r in self._regions if isinstance(r, dict) and r.get("kind") == "card_slot"]
            slot_type = min(len(existing_slots), 15)
            x = int(cam_x) + (_SCREEN_W // 2) - 2
            y = int(cam_y) + (_SCREEN_H // 2) - 2
            w, h = 4, 4
            name = self._next_region_name_from_base(f"slot_{len(existing_slots)}")
            x = max(0, min(int(self._grid_w) - 1, int(x)))
            y = max(0, min(int(self._grid_h) - 1, int(y)))
            w = max(1, min(int(w), max(1, int(self._grid_w) - x)))
            h = max(1, min(int(h), max(1, int(self._grid_h) - y)))
            return {"id": _new_id(), "name": name, "kind": "card_slot", "x": x, "y": y, "w": w, "h": h, "slot_type": slot_type}
        else:
            return None

        x = max(0, min(int(self._grid_w) - 1, int(x)))
        y = max(0, min(int(self._grid_h) - 1, int(y)))
        w = max(1, min(int(w), max(1, int(self._grid_w) - x)))
        h = max(1, min(int(h), max(1, int(self._grid_h) - y)))
        return {"id": _new_id(), "name": name, "kind": kind, "x": x, "y": y, "w": w, "h": h}

    def _add_region_preset(self) -> None:
        preset_key = str(self._combo_reg_preset.currentData() or "").strip()
        if not preset_key:
            return
        reg = self._build_region_preset(preset_key)
        if reg is None:
            return
        self._push_undo()
        self._regions.append(reg)
        self._region_selected = len(self._regions) - 1
        self._refresh_region_list()
        self._refresh_region_props()
        self._refresh_trigger_regions()
        self._canvas.update()
        self._update_diagnostics()

    def _add_region_from_canvas(self, x: int, y: int, w: int, h: int) -> None:
        self._push_undo()
        reg = {"id": _new_id(), "name": self._next_region_name(), "kind": "zone", "x": int(x), "y": int(y), "w": int(w), "h": int(h)}
        self._regions.append(reg)
        self._region_selected = len(self._regions) - 1
        self._refresh_region_list()
        self._refresh_region_props()
        self._refresh_trigger_regions()
        self._update_diagnostics()

    def _add_region(self) -> None:
        self._push_undo()
        reg = {"id": _new_id(), "name": self._next_region_name(), "kind": "zone", "x": 0, "y": 0, "w": 4, "h": 4}
        self._regions.append(reg)
        self._region_selected = len(self._regions) - 1
        self._refresh_region_list()
        self._refresh_region_props()
        self._refresh_trigger_regions()
        self._update_diagnostics()

    def _remove_region(self) -> None:
        idx = int(self._region_selected)
        if not (0 <= idx < len(self._regions)):
            return
        self._push_undo()
        del self._regions[idx]
        self._region_selected = min(idx, len(self._regions) - 1)
        self._refresh_region_list()
        self._refresh_region_props()
        self._refresh_trigger_regions()
        self._update_diagnostics()

    def _on_region_prop_changed(self, *_args) -> None:
        idx = int(self._region_selected)
        if not (0 <= idx < len(self._regions)):
            return
        r = self._regions[idx]
        r["name"] = str(self._edit_reg_name.text()).strip() or r.get("name", "")
        r["kind"] = str(self._combo_reg_kind.currentData() or "zone")
        r["x"] = int(self._spin_reg_x.value())
        r["y"] = int(self._spin_reg_y.value())
        r["w"] = int(self._spin_reg_w.value())
        r["h"] = int(self._spin_reg_h.value())
        is_gate = (r["kind"] == "lap_gate")
        self._lbl_gate_index.setVisible(is_gate)
        self._spin_reg_gate.setVisible(is_gate)
        if is_gate:
            r["gate_index"] = int(self._spin_reg_gate.value())
        else:
            r.pop("gate_index", None)
        is_wp = (r["kind"] == "race_waypoint")
        self._lbl_wp_index.setVisible(is_wp)
        self._spin_reg_wp.setVisible(is_wp)
        if is_wp:
            r["wp_index"] = int(self._spin_reg_wp.value())
        else:
            r.pop("wp_index", None)
        is_card_slot = (r["kind"] == "card_slot")
        self._lbl_slot_type.setVisible(is_card_slot)
        self._spin_reg_slot_type.setVisible(is_card_slot)
        if is_card_slot:
            r["slot_type"] = int(self._spin_reg_slot_type.value())
        else:
            r.pop("slot_type", None)
        self._refresh_region_list()
        self._canvas.update()
        self._refresh_trigger_regions()
        self._update_diagnostics()

    # ------------------------------------------------------------------
    # Text labels
    # ------------------------------------------------------------------

    def _set_text_label_props_enabled(self, enabled: bool) -> None:
        for w in (self._edit_lbl_text, self._spin_lbl_x, self._spin_lbl_y,
                  self._spin_lbl_pal, self._combo_lbl_plane):
            w.setEnabled(enabled)

    def _refresh_text_labels_ui(self) -> None:
        self._lbl_list.blockSignals(True)
        try:
            self._lbl_list.clear()
            for lbl in self._text_labels:
                if not isinstance(lbl, dict):
                    continue
                txt = str(lbl.get("text") or "(empty)")
                x = int(lbl.get("x", 0))
                y = int(lbl.get("y", 0))
                pl = str(lbl.get("plane", "scr1") or "scr1").upper()
                self._lbl_list.addItem(f'"{txt}"  ({x},{y}) [{pl}]')
            if 0 <= self._text_label_selected < self._lbl_list.count():
                self._lbl_list.setCurrentRow(int(self._text_label_selected))
        finally:
            self._lbl_list.blockSignals(False)
        self._btn_lbl_del.setEnabled(0 <= self._text_label_selected < len(self._text_labels))

        idx = int(self._text_label_selected)
        if not (0 <= idx < len(self._text_labels)):
            self._set_text_label_props_enabled(False)
            return
        self._set_text_label_props_enabled(True)
        lbl = self._text_labels[idx]
        self._edit_lbl_text.blockSignals(True)
        self._spin_lbl_x.blockSignals(True)
        self._spin_lbl_y.blockSignals(True)
        self._spin_lbl_pal.blockSignals(True)
        self._combo_lbl_plane.blockSignals(True)
        try:
            self._edit_lbl_text.setText(str(lbl.get("text") or ""))
            self._spin_lbl_x.setValue(int(lbl.get("x", 0)))
            self._spin_lbl_y.setValue(int(lbl.get("y", 0)))
            self._spin_lbl_pal.setValue(int(lbl.get("pal", 0)))
            plane = str(lbl.get("plane", "scr1") or "scr1").lower()
            pi = 1 if plane == "scr2" else 0
            self._combo_lbl_plane.setCurrentIndex(pi)
        finally:
            self._edit_lbl_text.blockSignals(False)
            self._spin_lbl_x.blockSignals(False)
            self._spin_lbl_y.blockSignals(False)
            self._spin_lbl_pal.blockSignals(False)
            self._combo_lbl_plane.blockSignals(False)
        self._canvas.update()

    def _on_text_label_selected(self, idx: int) -> None:
        self._text_label_selected = int(idx)
        self._refresh_text_labels_ui()

    def _add_text_label(self) -> None:
        self._push_undo()
        lbl = {"id": uuid.uuid4().hex[:8], "text": "", "x": 0, "y": 0, "pal": 0, "plane": "scr1"}
        self._text_labels.append(lbl)
        self._text_label_selected = len(self._text_labels) - 1
        self._refresh_text_labels_ui()
        self._update_diagnostics()

    def _remove_text_label(self) -> None:
        idx = int(self._text_label_selected)
        if not (0 <= idx < len(self._text_labels)):
            return
        self._push_undo()
        del self._text_labels[idx]
        self._text_label_selected = min(idx, len(self._text_labels) - 1)
        self._refresh_text_labels_ui()
        self._update_diagnostics()

    def _on_text_label_prop_changed(self, *_args) -> None:
        idx = int(self._text_label_selected)
        if not (0 <= idx < len(self._text_labels)):
            return
        lbl = self._text_labels[idx]
        raw = str(self._edit_lbl_text.text())
        # Keep only printable ASCII (32-126)
        cleaned = "".join(c for c in raw if 32 <= ord(c) <= 126)[:20]
        lbl["text"] = cleaned
        lbl["x"] = max(0, min(19, int(self._spin_lbl_x.value())))
        lbl["y"] = max(0, min(18, int(self._spin_lbl_y.value())))
        lbl["pal"] = max(0, min(15, int(self._spin_lbl_pal.value())))
        lbl["plane"] = str(self._combo_lbl_plane.currentData() or "scr1")
        self._refresh_text_labels_ui()

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _store_scene_state(self, *, save_project: bool, update_status: bool) -> bool:
        if self._scene is None:
            if update_status:
                QMessageBox.warning(self, tr("level.save_title"),
                                    tr("level.no_project_context"))
            return False
        self._scene["entities"]     = [dict(e) for e in self._entities]
        self._scene["waves"]        = [
            {"delay": w["delay"], "entities": [dict(e) for e in w["entities"]]}
            for w in self._waves
        ]
        self._scene["regions"]      = [dict(r) for r in self._regions]
        self._scene["text_labels"]  = [dict(l) for l in self._text_labels]
        self._scene["triggers"]     = [dict(t) for t in self._triggers]
        self._scene["paths"]        = copy.deepcopy(self._paths)
        self._entity_roles = migrate_scene_sprite_roles(self._scene)
        self._scene["level_size"]   = {"w": self._grid_w, "h": self._grid_h}
        self._scene["level_profile"] = str(self._level_profile or "none")

        # Background preview (SCR1/SCR2) metadata
        try:
            i1 = int(self._combo_bg_scr1.currentIndex())
        except Exception:
            i1 = 0
        try:
            i2 = int(self._combo_bg_scr2.currentIndex())
        except Exception:
            i2 = 0
        rel1 = self._bg_rels[i1] if (0 <= i1 < len(self._bg_rels)) else None
        rel2 = self._bg_rels[i2] if (0 <= i2 < len(self._bg_rels)) else None
        if rel1:
            self._scene["level_bg_scr1"] = str(rel1)
        else:
            self._scene.pop("level_bg_scr1", None)
        if rel2:
            self._scene["level_bg_scr2"] = str(rel2)
        else:
            self._scene.pop("level_bg_scr2", None)
        self._scene["level_bg_front"] = str(self._bg_front or "scr1")

        # Layout / scroll metadata
        self._scene["level_cam_tile"] = {"x": int(self._cam_tile[0]), "y": int(self._cam_tile[1])}
        self._scene["level_bezel"] = {"tx": int(self._bezel_tile[0]), "ty": int(self._bezel_tile[1])}
        self._scene["level_scroll"]   = dict(self._scroll_cfg)
        self._scene["level_layout"]   = dict(self._layout_cfg)
        self._scene["level_layers"]   = dict(self._layers_cfg)
        self._scene["pal_cycles"]     = self._collect_pal_cycles()
        self._scene["level_rules"]    = copy.deepcopy(self._level_rules)

        self._scene["map_mode"]     = str(self._combo_map_mode.currentData() or "none")
        if self._col_map is not None:
            self._scene["col_map"] = copy.deepcopy(self._col_map)
            if self._col_map_meta:
                self._scene["col_map_meta"] = copy.deepcopy(self._col_map_meta)
            else:
                self._scene.pop("col_map_meta", None)
        else:
            self._scene.pop("col_map", None)
            self._scene.pop("col_map_meta", None)
        if self._tile_ids:
            self._scene["tile_ids"] = copy.deepcopy(self._tile_ids)
        else:
            self._scene.pop("tile_ids", None)
        # Track B — neighbor warps
        nb = self._collect_neighbors()
        if nb:
            self._scene["neighbors"] = nb
        else:
            self._scene.pop("neighbors", None)
        # Track A — chunk map
        cmap = self._collect_bg_chunk_map()
        if cmap:
            self._scene["bg_chunk_map"] = cmap
        else:
            self._scene.pop("bg_chunk_map", None)
        # ── Procgen UI params (design-time) ──────────────────────────
        try:
            self._scene["procgen_params"] = {
                "seed":             int(self._spin_seed.value()),
                "margin":           int(self._spin_margin.value()),
                "enemy_dens":       int(self._spin_enemy_dens.value()),
                "item_dens":        int(self._spin_item_dens.value()),
                "open_dens":        int(self._spin_open_dens.value()),
                "td_gen_mode":      str(self._combo_td_gen_mode.currentData() or "scatter"),
                "td_bsp_depth":     int(self._spin_td_bsp_depth.value()),
                "td_loop_pct":      int(self._spin_td_loop_pct.value()),
                "td_bsp_out_w":     int(self._spin_td_bsp_out_w.value()),
                "td_bsp_out_h":     int(self._spin_td_bsp_out_h.value()),
                "td_bsp_sprite":    int(self._spin_td_bsp_sprite.value()),
                "td_scatter_out_w": int(self._spin_td_scatter_out_w.value()),
                "td_scatter_out_h": int(self._spin_td_scatter_out_h.value()),
                "wall_dens":        int(self._spin_wall_dens.value()),
                "td_ca":            self._chk_td_ca.isChecked(),
                "dir_walls":        self._chk_dir_walls.isChecked(),
                "td_int_walls":     self._chk_td_int_walls.isChecked(),
                "td_water":         self._chk_td_water.isChecked(),
                "td_border_n":      self._chk_td_border_n.isChecked(),
                "td_border_s":      self._chk_td_border_s.isChecked(),
                "td_border_e":      self._chk_td_border_e.isChecked(),
                "td_border_w":      self._chk_td_border_w.isChecked(),
                "gen_tilemaps":     self._chk_gen_tilemaps.isChecked(),
                "gen_scr1":         self._chk_gen_scr1.isChecked(),
                "gen_scr2":         self._chk_gen_scr2.isChecked(),
                "tile_src":         str(self._combo_tile_src.currentData() or "auto"),
            }
        except Exception:
            pass
        # ── Runtime DungeonGen params ────────────────────────────────────
        try:
            if self._chk_dgen_enabled.isChecked():
                self._scene["rt_dungeongen_params"] = {
                    "enabled":        True,
                    "seed_mode":      self._combo_dgen_seed_mode.currentData(),
                    "seed_fixed":     int(self._spin_dgen_seed_value.value()),
                    "room_mw_min":    int(self._spin_dgen_mw_min.value()),
                    "room_mw_max":    int(self._spin_dgen_mw_max.value()),
                    "room_mh_min":    int(self._spin_dgen_mh_min.value()),
                    "room_mh_max":    int(self._spin_dgen_mh_max.value()),
                    "max_exits":      int(self._spin_dgen_max_exits.value()),
                    "cell_w_tiles":   int(self._spin_dgen_cell_w.value()),
                    "cell_h_tiles":   int(self._spin_dgen_cell_h.value()),
                    "ground_pct_1":   int(self._spin_dgen_gpc1.value()),
                    "ground_pct_2":   int(self._spin_dgen_gpc2.value()),
                    "ground_pct_3":   int(self._spin_dgen_gpc3.value()),
                    "eau_freq":       int(self._spin_dgen_eau_freq.value()),
                    "vide_freq":      int(self._spin_dgen_vide_freq.value()),
                    "vide_margin":    int(self._spin_dgen_vide_margin.value()),
                    "tonneau_freq":   int(self._spin_dgen_tonneau_freq.value()),
                    "tonneau_max":    int(self._spin_dgen_tonneau_max.value()),
                    "enemy_min":      int(self._spin_dgen_enemy_min.value()),
                    "enemy_max":      int(self._spin_dgen_enemy_max.value()),
                    "enemy_density":  int(self._spin_dgen_enemy_density.value()),
                    "ene2_pct":       int(self._spin_dgen_ene2_pct.value()),
                    "item_freq":      int(self._spin_dgen_item_freq.value()),
                    "n_rooms":           int(self._spin_dgen_n_rooms.value()),
                    "enemy_ramp_rooms":  int(self._spin_dgen_enemy_ramp_rooms.value()),
                    "safe_room_every":   int(self._spin_dgen_safe_room_every.value()),
                    "min_exits":         int(self._spin_dgen_min_exits.value()),
                    "cluster_size_max":  int(self._spin_dgen_cluster_size_max.value()),
                    "tier_cols":         int(self._spin_dgen_tier_cols.value()),
                    "tier_ene_max":      [int(x.strip()) for x in self._edit_dgen_tier_ene_max.text().split(",") if x.strip()],
                    "tier_item_freq":    [int(x.strip()) for x in self._edit_dgen_tier_item_freq.text().split(",") if x.strip()],
                    "tier_eau_freq":     [int(x.strip()) for x in self._edit_dgen_tier_eau_freq.text().split(",") if x.strip()],
                    "tier_vide_freq":    [int(x.strip()) for x in self._edit_dgen_tier_vide_freq.text().split(",") if x.strip()],
                    "multifloor":        bool(self._chk_dgen_multifloor.isChecked()),
                    "floor_var":      int(self._spin_dgen_floor_var.value()),
                    "max_floors":     int(self._spin_dgen_max_floors.value()),
                    "boss_scene":     str(self._combo_dgen_boss_scene.currentData() or ""),
                    "enemy_pool":     self._get_dgen_pool(
                        getattr(self, "_tbl_dgen_ene_pool", None) or QTableWidget(),
                        has_max=True),
                    "item_pool":      self._get_dgen_pool(
                        getattr(self, "_tbl_dgen_item_pool", None) or QTableWidget(),
                        has_max=False),
                    "player_entity_id": str(
                        (getattr(self, "_combo_dgen_player", None) and
                         self._combo_dgen_player.currentData()) or ""),
                    "water_behavior":   str(self._combo_dgen_water_col.currentData() or "water"),
                    "void_behavior":    str(self._combo_dgen_void_behavior.currentData() or "death"),
                    "void_damage":      int(self._spin_dgen_void_damage.value()),
                    "void_scene":       str(self._combo_dgen_void_scene.currentData() or ""),
                }
            else:
                self._scene.pop("rt_dungeongen_params", None)
        except Exception:
            pass
        # ── Runtime DFS + Cave params ────────────────────────────────────
        def _read_tier_table(tbl, nrows: int) -> list:
            rows = []
            for r in range(nrows):
                row_vals = []
                for c in range(5):
                    it = tbl.item(r, c)
                    try:
                        row_vals.append(int(it.text()) if it else 0)
                    except (ValueError, AttributeError):
                        row_vals.append(0)
                rows.append(row_vals)
            return rows

        # ── Runtime DFS params ───────────────────────────────────────────
        try:
            if self._chk_dfs_enabled.isChecked():
                self._scene["rt_dfs_params"] = {
                    "enabled":     True,
                    "grid_w":      int(self._spin_dfs_grid_w.value()),
                    "grid_h":      int(self._spin_dfs_grid_h.value()),
                    "room_w":      int(self._spin_dfs_room_w.value()),
                    "room_h":      int(self._spin_dfs_room_h.value()),
                    "max_enemies": int(self._spin_dfs_max_enemies.value()),
                    "item_chance": int(self._spin_dfs_item_chance.value()),
                    "loop_pct":    int(self._spin_dfs_loop_pct.value()),
                    "max_active":  int(self._spin_dfs_max_active.value()),
                    "start_mode":  str(self._combo_dfs_start_mode.currentData() or "corner"),
                    "multifloor":  bool(self._chk_dfs_multifloor.isChecked()),
                    "floor_var":   int(self._spin_dfs_floor_var.value()),
                    "max_floors":  int(self._spin_dfs_max_floors.value()),
                    "boss_scene":  str(self._combo_dfs_boss_scene.currentData() or ""),
                    "loop_scene":  str(self._combo_dfs_loop_scene.currentData() or ""),
                    "tier_count":       int(self._spin_dfs_tier_count.value()),
                    "floors_per_tier":  int(self._spin_dfs_floors_per_tier.value()),
                    "tier_table":       _read_tier_table(self._dfs_tier_table, 4),
                }
            else:
                self._scene.pop("rt_dfs_params", None)
        except Exception:
            pass
        # ── Runtime Cave params ──────────────────────────────────────────
        try:
            if self._chk_cave_enabled.isChecked():
                self._scene["rt_cave_params"] = {
                    "enabled":          True,
                    "wall_pct":         int(self._spin_cave_wall_pct.value()),
                    "iterations":       int(self._spin_cave_iterations.value()),
                    "max_enemies":      int(self._spin_cave_max_enemies.value()),
                    "max_items":        int(self._spin_cave_max_chests.value()),
                    "pickup_type":      int(self._spin_cave_pickup_type.value()),
                    "item_pool":        self._get_cave_item_pool_selected(),
                    "multifloor":       bool(self._chk_cave_multifloor.isChecked()),
                    "floor_var":        int(self._spin_cave_floor_var.value()),
                    "max_floors":       int(self._spin_cave_max_floors.value()),
                    "boss_scene":       str(self._combo_cave_boss_scene.currentData() or ""),
                    "tier_count":       int(self._spin_cave_tier_count.value()),
                    "floors_per_tier":  int(self._spin_cave_floors_per_tier.value()),
                    "tier_table":       _read_tier_table(self._cave_tier_table, 3),
                }
            else:
                self._scene.pop("rt_cave_params", None)
        except Exception:
            pass
        if save_project and self._on_save:
            self._on_save()
        if update_status:
            self._lbl_status.setText(tr("level.saved", n=len(self._entities)))
        return True

    def flush_scene_state(self) -> bool:
        return self._store_scene_state(save_project=False, update_status=False)

    def _save_entities(self) -> None:
        self._store_scene_state(save_project=True, update_status=True)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _export_scene_h(self) -> None:
        if self._scene is None:
            QMessageBox.warning(self, tr("level.export_title"),
                                tr("level.no_project_context"))
            return
        if not self._entities and not self._waves:
            QMessageBox.information(self, tr("level.export_title"),
                                    tr("level.export_empty"))
            return
        export_scene = dict(self._scene)
        export_scene["entities"] = [dict(e) for e in self._entities]
        export_scene["waves"] = [
            {"delay": int(w.get("delay", 0) or 0), "entities": [dict(e) for e in (w.get("entities") or [])]}
            for w in self._waves
        ]
        export_scene["regions"] = [dict(r) for r in self._regions]
        export_scene["text_labels"] = [dict(l) for l in self._text_labels]
        export_scene["triggers"] = [dict(t) for t in self._triggers]
        export_scene["paths"] = copy.deepcopy(self._paths)

        core_issues: list[str] = []
        try:
            from core.scene_level_gen import collect_scene_level_issues
            core_issues = collect_scene_level_issues(
                project_data={"scenes": [dict(s) for s in (self._project_scenes or [])]},
                scene=export_scene,
            )
        except Exception:
            core_issues = []
        trig_issues = self._collect_trigger_issues()
        all_issues = list(dict.fromkeys(trig_issues + core_issues))
        if all_issues:
            QMessageBox.warning(
                self,
                tr("level.export_title"),
                tr("level.export_trigger_issues", details="\n".join(f"- {item}" for item in all_issues)),
            )
            return

        sym = self._edit_sym.text().strip() or "scene"
        h   = _make_scene_h(sym, self._entities, self._waves,
                            self._scene, self._entity_roles,
                            col_map=self._col_map,
                            map_mode=str(self._combo_map_mode.currentData() or "none"),
                            tile_ids=self._tile_ids,
                            cam_tile=self._cam_tile,
                            scroll_cfg=self._scroll_cfg,
                            layout_cfg=self._layout_cfg,
                            layers_cfg=self._layers_cfg,
                            rules_cfg=self._level_rules,
                            regions=self._regions,
                            triggers=self._triggers,
                            paths=self._paths,
                            map_w=self._grid_w,
                            map_h=self._grid_h)

        path, _ = QFileDialog.getSaveFileName(
            self, tr("level.export_title"),
            f"{sym}_scene.h",
            "C Header (*.h);;All files (*.*)",
        )
        if not path:
            return
        try:
            Path(path).write_text(h, encoding="utf-8")
            self._lbl_status.setText(tr("level.exported", path=Path(path).name))
        except Exception as exc:
            QMessageBox.warning(self, tr("level.export_title"), str(exc))


# ---------------------------------------------------------------------------
# C header generation
# ---------------------------------------------------------------------------

_PROP_CTYPES: dict[str, str] = {
    "hp": "u8", "damage": "u8", "max_speed": "u8",
    "weight": "u8", "friction": "u8", "jump_force": "u8",
    "inv_frames": "u8", "score": "u8",
    "anim_spd": "u8", "type_id": "u8", "behavior": "u8",
}


def _make_scene_h(
    sym:          str,
    entities:     list[dict],
    waves:        list[dict],
    scene:        dict,
    entity_roles: dict[str, str],
    *,
    col_map:      Optional[list[list[int]]] = None,
    map_mode:     str = "none",
    tile_ids:     Optional[dict[str, dict[str, object]]] = None,
    cam_tile:     Optional[tuple[int, int]] = None,
    scroll_cfg:   Optional[dict] = None,
    layout_cfg:   Optional[dict] = None,
    layers_cfg:   Optional[dict] = None,
    rules_cfg:    Optional[dict] = None,
    regions:      Optional[list[dict]] = None,
    triggers:     Optional[list[dict]] = None,
    paths:        Optional[list[dict]] = None,
    map_w:        Optional[int] = None,
    map_h:        Optional[int] = None,
) -> str:
    """Generate a complete scene header: entity IDs + hitboxes + props + static entities + waves."""

    guard = f"_{sym.upper()}_SCENE_H_"

    # Collect all unique types (static first, then wave types)
    seen_types: list[str] = []
    for ent in entities:
        if ent["type"] not in seen_types:
            seen_types.append(ent["type"])
    for wave in waves:
        for ent in wave.get("entities", []):
            if ent["type"] not in seen_types:
                seen_types.append(ent["type"])

    # Sprite metadata lookup
    sprite_meta: dict[str, dict] = {}
    for spr in scene.get("sprites", []) or []:
        rel = spr.get("file", "")
        if rel:
            sprite_meta[Path(rel).stem] = spr

    sep = "/* " + "-" * 66 + " */"

    lines = [
        "/* Auto-generated by NgpCraft Engine — do not edit */",
        f"/* Scene: {sym} */",
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        '#include "ngpc_types.h"   /* u8,u16,s16 */',
        "",
        "/* Standalone types (avoid conflicts with optional template modules). */",
        "#ifndef NGPNG_LEVEL_TYPES",
        "#define NGPNG_LEVEL_TYPES",
        "typedef struct { s16 x, y, w, h; } NgpngRect;",
        "typedef struct { u8 type; u8 x; u8 y; u8 data; } NgpngEnt;",
        "#endif",
        "",
    ]

    # ---- Entity type IDs ----
    lines += [sep, "/* Entity type IDs                                                    */", sep]
    for i, t in enumerate(seen_types):
        role     = entity_roles.get(t, "prop")
        role_cmt = f"  /* [{role}] */" if role != "prop" else ""
        lines.append(f"#define {_type_to_c_const(t):30s} {i}{role_cmt}")
    lines.append("")

    # ---- Hitboxes ----
    lines += [sep, "/* Hitboxes — {x, y, w, h} relative to sprite top-left               */", sep]
    any_hb = False
    for t in seen_types:
        meta = sprite_meta.get(t)
        if meta is None:
            lines.append(f"/* {t}: sprite not found in scene */")
            continue
        hb = first_hurtbox(meta, int(meta.get("frame_w", 8) or 8), int(meta.get("frame_h", 8) or 8))
        x, y, w, h = hb.get("x", 0), hb.get("y", 0), hb.get("w", 0), hb.get("h", 0)
        cid = _safe_c_id(t)
        lines.append(f"static const NgpngRect g_{cid}_hitbox = {{{x}, {y}, {w}, {h}}};")
        any_hb = True
    if not any_hb:
        lines.append("/* (no hitboxes defined — use the Hitbox tab) */")
    lines.append("")

    # ---- Props ----
    prop_block: list[str] = []
    for t in seen_types:
        meta  = sprite_meta.get(t)
        if not meta:
            continue
        props = meta.get("props") or {}
        if not props:
            continue
        cid = _safe_c_id(t)
        prop_block.append(f"/* {t} */")
        for k, v in props.items():
            ctype = _PROP_CTYPES.get(k, "u8")
            prop_block.append(f"static const {ctype} g_{cid}_{k} = {int(v)};")
    if prop_block:
        lines += [sep, "/* Sprite props                                                       */", sep]
        lines.extend(prop_block)
        lines.append("")

    # ---- Static entity placement ----
    if entities:
        lines += [sep, f"/* Static entity placement — g_{sym}_entities[]                        */", sep]
        lines.append(f"static const NgpngEnt g_{sym}_entities[] = {{")
        for ent in entities:
            c = _type_to_c_const(ent["type"])
            x, y, d = ent.get("x", 0), ent.get("y", 0), ent.get("data", 0)
            lines.append(f"    {{{c}, {x:3d}, {y:3d}, {d:3d}}},")
        lines.append("    {0}  /* sentinel (type=0) */")
        lines.append("};")
        lines.append("")

        # Parallel tables — generated only when at least one value differs from default
        def _write_u8_table(tname: str, data: list, comment: str) -> None:
            lines.append(f"/* {comment} */")
            lines.append(f"static const u8 {tname}[] = {{")
            per = 16
            for i in range(0, len(data), per):
                chunk = ", ".join(f"{int(v):3d}" for v in data[i:i + per])
                lines.append(f"    {chunk},")
            lines.append("};")
            lines.append("")

        dirs = [int(e.get("direction", 0)) for e in entities]
        if any(d != 0 for d in dirs):
            _write_u8_table(
                f"g_{sym}_ent_dirs", dirs,
                "Initial direction per entity (0=right 1=left 2=up 3=down)")

        behs = [int(e.get("behavior", 0)) for e in entities]
        if any(b != 0 for b in behs):
            lines.append(f"#define {sym.upper()}_ENTITY_BEHAVIOR_TABLE 1")
            _write_u8_table(
                f"g_{sym}_ent_behaviors", behs,
                "Behavior per entity (0=patrol 1=chase 2=fixed 3=random)")

        path_index_by_id = {str(p.get("id", "")): i
                            for i, p in enumerate(paths or [])}
        path_idxs = []
        for e in entities:
            pid = str(e.get("path_id", "") or "")
            path_idxs.append(path_index_by_id[pid] if pid and pid in path_index_by_id else 255)
        _write_u8_table(
            f"g_{sym}_ent_paths", path_idxs,
            "Patrol path index per entity (255=none)")
        lines.append(f"#define {sym.upper()}_ENTITY_PATH_TABLE 1")
        lines.append("")

        ent_flags = [int(e.get("flags", 0) or 0) & 0xFF for e in entities]
        if any(f != 0 for f in ent_flags):
            lines.append(f"#define {sym.upper()}_ENTITY_FLAG_TABLE 1")
            _write_u8_table(
                f"g_{sym}_ent_flags", ent_flags,
                "Instance flags per entity (bit0=clamp within map)")

    # ---- Enemy waves ----
    if waves:
        lines += [
            sep,
            "/* Enemy waves                                                        */",
            "/*   Use: wave arrays + g_<scene>_wave_delays[] + _WAVE_COUNT.        */",
            sep,
        ]
        # Per-wave NgpngEnt arrays
        for wi, wave in enumerate(waves):
            delay      = wave.get("delay", 0)
            wave_ents  = wave.get("entities", [])
            cname      = f"g_{sym}_wave{wi}"
            lines.append(f"/* Wave {wi} — fires after {delay} frames */")
            lines.append(f"static const NgpngEnt {cname}[] = {{")
            for ent in wave_ents:
                c    = _type_to_c_const(ent["type"])
                x, y = ent.get("x", 0), ent.get("y", 0)
                d    = ent.get("data", 0)
                lines.append(f"    {{{c}, {x:3d}, {y:3d}, {d:3d}}},")
            lines.append("    {0}  /* sentinel (type=0) */")
            lines.append("};")
        lines.append("")

        # Delay table (u16 ? delays can exceed 255 frames)
        delays_str = ", ".join(str(w.get("delay", 0)) for w in waves)
        counts_str = ", ".join(str(len((w.get("entities", []) or [])) & 0xFF) for w in waves)
        lines.append(f"#define {sym.upper()}_WAVE_COUNT {len(waves)}")
        lines.append(f"static const u16 g_{sym}_wave_delays[] = {{{delays_str}}};")
        lines.append(f"static const u8 g_{sym}_wave_entity_counts[] = {{{counts_str}}};")
        lines.append("")

    # ---- Collision map + visual tile IDs (procgen) ----
    if map_w is None or map_h is None:
        sz = scene.get("level_size", {}) or {}
        map_w = int(sz.get("w", _SCREEN_W))
        map_h = int(sz.get("h", _SCREEN_H))

    def _fmt_u8_array(name: str, data: list[int], per_line: int = 16) -> None:
        lines.append(f"static const u8 {name}[] = {{")
        for i in range(0, len(data), per_line):
            chunk = ", ".join(f"{int(v):3d}" for v in data[i:i+per_line])
            lines.append(f"    {chunk},")
        lines.append("};")
        lines.append("")

    if col_map is not None:
        ok = (
            isinstance(col_map, list)
            and len(col_map) == int(map_h)
            and all(isinstance(r, list) and len(r) == int(map_w) for r in col_map)
        )
        if ok:
            lines += [sep, "/* Tile collision map (u8 per tile)                                  */", sep]
            lines += [
                "/* Types (compatible with optional/ngpc_tilecol/ngpc_tilecol.h): */",
                "#ifndef TILE_PASS",
                "#define TILE_PASS       0",
                "#define TILE_SOLID      1",
                "#define TILE_ONE_WAY    2",
                "#define TILE_DAMAGE     3",
                "#define TILE_LADDER     4",
                "#endif",
                "/* Project-specific (top-down directional walls): */",
                "#ifndef TILE_WALL_N",
                "#define TILE_WALL_N     5",
                "#define TILE_WALL_S     6",
                "#define TILE_WALL_E     7",
                "#define TILE_WALL_W     8",
                "#endif",
                "/* Project-specific / optional (extend as needed): */",
                "#ifndef TILE_WATER",
                "#define TILE_WATER      9",
                "#define TILE_FIRE       10",
                "#define TILE_VOID       11",
                "#define TILE_DOOR       12",
                "#endif",
                "#ifndef TILE_STAIR_E",
                "#define TILE_STAIR_E    13",
                "#define TILE_STAIR_W    14",
                "#endif",
                "#ifndef TILE_SPRING",
                "#define TILE_SPRING     15",
                "#endif",
                "",
                f"#define {sym.upper()}_MAP_W {int(map_w)}",
                f"#define {sym.upper()}_MAP_H {int(map_h)}",
                "",
            ]

            flat_col: list[int] = []
            for y in range(int(map_h)):
                for x in range(int(map_w)):
                    flat_col.append(int(col_map[y][x]))
            _fmt_u8_array(f"g_{sym}_tilecol", flat_col)

            if map_mode in _MAP_MODE_ROLES:
                tcol_to_role = {tcol: role_key for role_key, tcol, _lbl in _MAP_MODE_ROLES[map_mode]}
                tid = (tile_ids or {}).get(map_mode, {})
                flat_vis: list[int] = []
                for i, t in enumerate(flat_col):
                    rk = tcol_to_role.get(t)
                    if rk is None:
                        flat_vis.append(0)
                    else:
                        x = i % int(map_w)
                        y = i // int(map_w)
                        flat_vis.append(_tile_id_pick(tid.get(rk, t), default=int(t), x=x, y=y))
                lines += [sep, "/* Visual tile IDs (u8)                                               */", sep]
                _fmt_u8_array(f"g_{sym}_tilemap_ids", flat_vis)

    # ---- Regions (rectangles in tile coordinates) ----
    regs = regions
    if regs is None:
        regs = scene.get("regions", []) or []
    if isinstance(regs, list) and regs:
        # kind mapping is project-defined; keep it simple and extend as needed.
        kind_to_id = {"zone": 0, "no_spawn": 1, "danger_zone": 2, "checkpoint": 3, "exit_goal": 4, "camera_lock": 5, "spawn": 6, "attractor": 7, "repulsor": 8, "lap_gate": 9, "card_slot": 10, "race_waypoint": 11, "push_block": 12}

        lines += [sep, "/* Regions (tile coordinates)                                         */", sep]
        lines += [
            "#ifndef REGION_KIND_ZONE",
            "#define REGION_KIND_ZONE        0",
            "#define REGION_KIND_NO_SPAWN    1",
            "#define REGION_KIND_DANGER_ZONE 2",
            "#define REGION_KIND_CHECKPOINT  3",
            "#define REGION_KIND_EXIT_GOAL   4",
            "#define REGION_KIND_CAMERA_LOCK 5",
            "#define REGION_KIND_SPAWN       6",
            "#define REGION_KIND_ATTRACTOR   7",
            "#define REGION_KIND_REPULSOR    8",
            "#define REGION_KIND_LAP_GATE    9",
            "#define REGION_KIND_CARD_SLOT  10",
            "#endif",
            f"#define {sym.upper()}_REGION_COUNT {len(regs)}",
            "",
        ]

        def _safe_region_macro(name: str) -> str:
            clean = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").upper()
            return clean or "REGION"

        # Per-region index defines
        used_macros: set[str] = set()
        for i, r in enumerate(regs):
            nm = str((r or {}).get("name", "") or f"region_{i}")
            macro = _safe_region_macro(nm)
            if macro in used_macros:
                macro = f"{macro}_{i}"
            used_macros.add(macro)
            lines.append(f"#define {sym.upper()}_REGION_{macro} {i}")
        lines.append("")

        lines.append(f"static const NgpngRect g_{sym}_regions[] = {{")
        for r in regs:
            if not isinstance(r, dict):
                continue
            x = int(r.get("x", 0))
            y = int(r.get("y", 0))
            w = max(1, int(r.get("w", 1)))
            h = max(1, int(r.get("h", 1)))
            lines.append(f"    {{{x}, {y}, {w}, {h}}},")
        lines.append("};")
        lines.append("")

        lines.append(f"static const u8 g_{sym}_region_kind[] = {{")
        for r in regs:
            kind = str((r or {}).get("kind", "zone") or "zone")
            lines.append(f"    {int(kind_to_id.get(kind, 0))},")
        lines.append("};")
        lines.append("")

        # gate_index array — only emitted when at least one lap_gate region exists
        has_lap_gates = any(str((r or {}).get("kind", "")) == "lap_gate" for r in regs)
        if has_lap_gates:
            lines.append(f"/* gate_index: ordered sequence for lap_gate regions (0=start/finish, 1..N=checkpoints) */")
            lines.append(f"static const u8 g_{sym}_region_gate_index[] = {{")
            for r in regs:
                if not isinstance(r, dict):
                    continue
                gate_idx = int(r.get("gate_index", 0)) if str(r.get("kind", "")) == "lap_gate" else 0
                lines.append(f"    {gate_idx},")
            lines.append("};")
            lines.append("")

        # slot_type array — only emitted when at least one card_slot region exists
        has_card_slots = any(str((r or {}).get("kind", "")) == "card_slot" for r in regs)
        if has_card_slots:
            lines.append(f"/* slot_type: per-region card slot type (0=field, 1=hand, 2=discard, 3=deck, 4-15=user-defined) */")
            lines.append(f"static const u8 g_{sym}_region_slot_type[] = {{")
            for r in regs:
                if not isinstance(r, dict):
                    continue
                slot_t = int(r.get("slot_type", 0)) if str(r.get("kind", "")) == "card_slot" else 0
                lines.append(f"    {slot_t},")
            lines.append("};")
            lines.append("")

    # ---- Triggers (conditions -> actions) ----
    trigs = triggers
    if trigs is None:
        trigs = scene.get("triggers", []) or []

    if isinstance(trigs, list) and trigs:
        cond_to_id = dict(_TRIGGER_COND_TO_ID)

        act_to_id = {
            "emit_event":       0,
            "play_sfx":         1,
            "start_bgm":        2,
            "stop_bgm":         3,
            "fade_bgm":         4,
            "goto_scene":       5,
            "add_score":        17,
            "spawn_wave":       6,
            "pause_scroll":     7,
            "resume_scroll":    8,
            "spawn_entity":     9,
            "set_scroll_speed": 10,
            "play_anim":        11,
            "force_jump":       12,
            "fire_player_shot": 23,
            "enable_trigger":   13,
            "disable_trigger":  14,
            "screen_shake":     15,
            "set_cam_target":   16,
            "show_entity":      18,
            "hide_entity":      19,
            "move_entity_to":   20,
            "pause_entity_path": 26,
            "resume_entity_path": 27,
            "cycle_player_form": 21,
            "set_player_form":   22,
            "set_checkpoint":    24,
            "respawn_player":    25,
            "set_flag":        28,
            "clear_flag":      29,
            "set_variable":    30,
            "inc_variable":    31,
            "warp_to":         32,
            "lock_player_input":   33,
            "unlock_player_input": 34,
            "enable_multijump":    35,
            "disable_multijump":   36,
            "reset_scene":         37,
            "show_dialogue":       38,
            "open_menu":           75,
            "set_npc_dialogue":    74,
            "give_item":           39,
            "remove_item":         40,
            "unlock_door":         41,
            "enable_wall_grab":    42,
            "disable_wall_grab":   43,
            "set_gravity_dir":     44,
            "add_resource":        45,
            "remove_resource":     46,
            "unlock_ability":      47,
            "set_quest_stage":     48,
            "play_cutscene":       49,
            "end_game":            50,
            "dec_variable":   51,
            "add_health":     52,
            "set_health":     53,
            "add_lives":      54,
            "set_lives":      55,
            "destroy_entity": 56,
            "teleport_player":57,
            "toggle_flag":    58,
            "set_score":      59,
            "set_timer":      60,
            "pause_timer":    61,
            "resume_timer":   62,
            "fade_out":        63,
            "fade_in":         64,
            "camera_lock":     65,
            "camera_unlock":   66,
            "add_combo":       67,
            "reset_combo":     68,
            "flash_screen":    69,
            "spawn_at_region": 70,
            "save_game":       71,
            "set_bgm_volume":  72,
            "toggle_tile":     73,
            "flip_sprite_h":   76,
            "flip_sprite_v":   77,
            "init_game_vars":  78,
            "stop_wave_rand":  79,
        }

        # Region ID -> index mapping (best-effort)
        regs_for_map = regs if isinstance(regs, list) else (scene.get("regions", []) or [])
        rid_to_idx: dict[str, int] = {}
        for i, r in enumerate(regs_for_map):
            if isinstance(r, dict):
                rid = str(r.get("id", "") or "").strip()
                if rid:
                    rid_to_idx[rid] = int(i)

        lines += [sep, "/* Triggers (conditions -> actions)                                    */", sep]
        lines += ["#ifndef TRIG_ENTER_REGION"]
        for cond_name, cond_id in cond_to_id.items():
            macro = re.sub(r"[^A-Z0-9]+", "_", cond_name.upper()).strip("_")
            lines.append(f"#define TRIG_{macro:<16} {cond_id}")
        lines += [
            "#endif",
            "",
            "#ifndef TRIG_ACT_EMIT_EVENT",
            "#define TRIG_ACT_EMIT_EVENT       0",
            "#define TRIG_ACT_PLAY_SFX         1",
            "#define TRIG_ACT_START_BGM        2",
            "#define TRIG_ACT_STOP_BGM         3",
            "#define TRIG_ACT_FADE_BGM         4",
            "#define TRIG_ACT_GOTO_SCENE       5",
            "#define TRIG_ACT_ADD_SCORE       17",
            "#define TRIG_ACT_SPAWN_WAVE       6",
            "#define TRIG_ACT_PAUSE_SCROLL     7",
            "#define TRIG_ACT_RESUME_SCROLL    8",
            "#define TRIG_ACT_SPAWN_ENTITY     9",
            "#define TRIG_ACT_SET_SCROLL_SPEED 10",
            "#define TRIG_ACT_PLAY_ANIM        11",
            "#define TRIG_ACT_FORCE_JUMP       12",
            "#define TRIG_ACT_FIRE_PLAYER_SHOT 23",
            "#define TRIG_ACT_ENABLE_TRIGGER   13",
            "#define TRIG_ACT_DISABLE_TRIGGER  14",
            "#define TRIG_ACT_SCREEN_SHAKE     15",
            "#define TRIG_ACT_SET_CAM_TARGET   16",
            "#define TRIG_ACT_SHOW_ENTITY      18",
            "#define TRIG_ACT_HIDE_ENTITY      19",
            "#define TRIG_ACT_MOVE_ENTITY_TO   20",
            "#define TRIG_ACT_PAUSE_ENTITY_PATH 26",
            "#define TRIG_ACT_RESUME_ENTITY_PATH 27",
            "#define TRIG_ACT_CYCLE_PLAYER_FORM 21",
            "#define TRIG_ACT_SET_PLAYER_FORM  22",
            "#define TRIG_ACT_SET_CHECKPOINT   24",
            "#define TRIG_ACT_RESPAWN_PLAYER   25",
            "#define TRIG_ACT_SET_FLAG         28",
            "#define TRIG_ACT_CLEAR_FLAG       29",
            "#define TRIG_ACT_SET_VARIABLE     30",
            "#define TRIG_ACT_INC_VARIABLE     31",
            "#define TRIG_ACT_WARP_TO          32",
            "#define TRIG_ACT_LOCK_PLAYER_INPUT   33",
            "#define TRIG_ACT_UNLOCK_PLAYER_INPUT 34",
            "#define TRIG_ACT_ENABLE_MULTIJUMP    35",
            "#define TRIG_ACT_DISABLE_MULTIJUMP   36",
            "#define TRIG_ACT_RESET_SCENE         37",
            "#define TRIG_ACT_SHOW_DIALOGUE       38",
            "#define TRIG_ACT_GIVE_ITEM           39",
            "#define TRIG_ACT_REMOVE_ITEM         40",
            "#define TRIG_ACT_UNLOCK_DOOR         41",
            "#define TRIG_ACT_ENABLE_WALL_GRAB    42",
            "#define TRIG_ACT_DISABLE_WALL_GRAB   43",
            "#define TRIG_ACT_SET_GRAVITY_DIR     44",
            "#define TRIG_ACT_ADD_RESOURCE        45",
            "#define TRIG_ACT_REMOVE_RESOURCE     46",
            "#define TRIG_ACT_UNLOCK_ABILITY      47",
            "#define TRIG_ACT_SET_QUEST_STAGE     48",
            "#define TRIG_ACT_PLAY_CUTSCENE       49",
            "#define TRIG_ACT_END_GAME            50",
            "#define TRIG_ACT_DEC_VARIABLE    51",
            "#define TRIG_ACT_ADD_HEALTH      52",
            "#define TRIG_ACT_SET_HEALTH      53",
            "#define TRIG_ACT_ADD_LIVES       54",
            "#define TRIG_ACT_SET_LIVES       55",
            "#define TRIG_ACT_DESTROY_ENTITY  56",
            "#define TRIG_ACT_TELEPORT_PLAYER 57",
            "#define TRIG_ACT_TOGGLE_FLAG     58",
            "#define TRIG_ACT_SET_SCORE       59",
            "#define TRIG_ACT_SET_TIMER       60",
            "#define TRIG_ACT_PAUSE_TIMER     61",
            "#define TRIG_ACT_RESUME_TIMER    62",
            "#define TRIG_ACT_FADE_OUT        63",
            "#define TRIG_ACT_FADE_IN         64",
            "#define TRIG_ACT_CAMERA_LOCK     65",
            "#define TRIG_ACT_CAMERA_UNLOCK   66",
            "#define TRIG_ACT_ADD_COMBO       67",
            "#define TRIG_ACT_RESET_COMBO     68",
            "#define TRIG_ACT_FLASH_SCREEN    69",
            "#define TRIG_ACT_SPAWN_AT_REGION 70",
            "#define TRIG_ACT_SAVE_GAME       71",
            "#define TRIG_ACT_SET_BGM_VOLUME  72",
            "#define TRIG_ACT_TOGGLE_TILE      73",
            "#define TRIG_ACT_SET_NPC_DIALOGUE 74",
            "#define TRIG_ACT_OPEN_MENU        75",
            "#define TRIG_ACT_FLIP_SPRITE_H    76",
            "#define TRIG_ACT_FLIP_SPRITE_V    77",
            "#define TRIG_ACT_INIT_GAME_VARS   78",
            "#endif",
            "",
            "#ifndef NGPNG_TRIGGER_T",
            "#define NGPNG_TRIGGER_T",
            "typedef struct { u8 cond; u8 region; u16 value; u8 action; u8 a0; u8 a1; u8 once; } NgpngTrigger;",
            "#endif",
            "",
            f"#define {sym.upper()}_TRIGGER_COUNT {len(trigs)}",
            "",
        ]

        def _safe_trig_macro(name: str) -> str:
            clean = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").upper()
            return clean or "TRIG"

        used_tmacros: set[str] = set()
        for i, t in enumerate(trigs):
            if not isinstance(t, dict):
                continue
            nm = str(t.get("name", "") or f"trig_{i}")
            macro = _safe_trig_macro(nm)
            if macro in used_tmacros:
                macro = f"{macro}_{i}"
            used_tmacros.add(macro)
            lines.append(f"#define {sym.upper()}_TRIG_{macro} {i}")
        lines.append("")

        lines.append(f"static const NgpngTrigger g_{sym}_triggers[] = {{")
        for t in trigs:
            if not isinstance(t, dict):
                continue
            cond = str(t.get("cond", "enter_region") or "enter_region")
            cid = int(cond_to_id.get(cond, 0))
            rid = str(t.get("region_id", "") or "").strip()
            region_idx = int(rid_to_idx.get(rid, 255))
            value = int(t.get("value", 0) or 0) & 0xFFFF
            # For dialogue_done: resolve cond_dialogue_id → index (value = dlg_idx)
            if cond == "dialogue_done":
                cdid = str(t.get("cond_dialogue_id", "") or "").strip()
                if cdid:
                    dlgs = scene.get("dialogues") or []
                    cdidx = next((i for i, d in enumerate(dlgs)
                                  if str(d.get("id", "") or "").strip() == cdid), None)
                    if cdidx is not None:
                        value = int(cdidx) & 0xFFFF
            # For choice_result: region = dialogue_idx, value = choice_idx
            elif cond == "choice_result":
                cdid = str(t.get("cond_dialogue_id", "") or "").strip()
                if cdid:
                    dlgs = scene.get("dialogues") or []
                    cdidx = next((i for i, d in enumerate(dlgs)
                                  if str(d.get("id", "") or "").strip() == cdid), None)
                    if cdidx is not None:
                        region_idx = int(cdidx) & 0xFF
                value = int(t.get("choice_idx", 0) or 0) & 0xFFFF
            # For menu_result: region = menu_idx, value = item_idx
            elif cond == "menu_result":
                cmid = str(t.get("cond_menu_id", "") or "").strip()
                if cmid:
                    menus = scene.get("menus") or []
                    cmidx = next((i for i, m in enumerate(menus)
                                  if str(m.get("id", "") or "").strip() == cmid), None)
                    if cmidx is not None:
                        region_idx = int(cmidx) & 0xFF
                value = int(t.get("menu_item_idx", 0) or 0) & 0xFFFF
            act = str(t.get("action", "") or "").strip().lower() or "emit_event"
            aid = int(act_to_id.get(act, 0))
            a0_raw = int(t.get("a0", t.get("event", 0)) or 0)
            # Resolve a0 from stable IDs (re-resolves at export time for robustness)
            if act in ("enable_trigger", "disable_trigger"):
                tid = str(t.get("target_id", "") or "")
                if tid:
                    resolved = next((i for i, tr in enumerate(trigs)
                                     if str(tr.get("id", "")) == tid), None)
                    if resolved is not None:
                        a0_raw = resolved
            elif act in ("show_entity", "hide_entity", "move_entity_to", "pause_entity_path", "resume_entity_path"):
                ent_target_id = str(t.get("entity_target_id", "") or "").strip()
                if ent_target_id:
                    resolved = self._entity_index_for_target_id(ent_target_id)
                    a0_raw = 255 if resolved is None else resolved
                else:
                    a0_raw = int(t.get("entity_index", t.get("event", 0)) or 0)
            elif act in ("set_flag", "clear_flag", "set_variable", "inc_variable",
                         "dec_variable", "toggle_flag", "init_game_vars"):
                a0_raw = int(t.get("flag_var_index", 0) or 0) & 0xFF
            elif act == "show_dialogue":
                dlg_id = str(t.get("dialogue_id", "") or "").strip()
                if dlg_id:
                    dlgs = scene.get("dialogues") or []
                    resolved = next((i for i, d in enumerate(dlgs)
                                     if str(d.get("id", "") or "").strip() == dlg_id), None)
                    if resolved is not None:
                        a0_raw = resolved
            elif act == "open_menu":
                mid = str(t.get("menu_id", "") or "").strip()
                if mid:
                    menus = scene.get("menus") or []
                    midx = next((i for i, m in enumerate(menus)
                                 if str(m.get("id", "") or "").strip() == mid), None)
                    if midx is not None:
                        a0_raw = int(midx)
            elif act == "set_npc_dialogue":
                ent_target_id = str(t.get("entity_target_id", "") or "").strip()
                if ent_target_id:
                    resolved = self._entity_index_for_target_id(ent_target_id)
                    a0_raw = 255 if resolved is None else resolved
            a0 = int(a0_raw) & 0xFF
            a1_raw = int(t.get("a1", t.get("param", 0)) or 0)
            if act in ("move_entity_to", "teleport_player", "spawn_at_region"):
                rid = str(t.get("dest_region_id", "") or "").strip()
                if rid:
                    a1_raw = int(rid_to_idx.get(rid, a1_raw))
            elif act == "toggle_tile":
                rid = str(t.get("dest_region_id", "") or "").strip()
                if rid:
                    a0 = int(rid_to_idx.get(rid, a0))
                a1_raw = int(t.get("param", 0) or 0)
            elif act == "set_npc_dialogue":
                npc_did = str(t.get("npc_dialogue_id", "") or "").strip()
                if npc_did:
                    dlgs = scene.get("dialogues") or []
                    npc_didx = next((i for i, d in enumerate(dlgs)
                                     if str(d.get("id", "") or "").strip() == npc_did), None)
                    if npc_didx is not None:
                        a1_raw = int(npc_didx)
            a1 = int(a1_raw) & 0xFF
            once = 1 if bool(t.get("once", True)) else 0
            lines.append(f"    {{{cid}, {region_idx}, (u16){value}, {aid}, {a0}, {a1}, {once}}},")
        lines.append("};")
        lines.append("")

        # Extra AND conditions (T-14) — only emitted when at least one trigger has them
        all_extra: list[list[dict]] = [
            [ec for ec in (t.get("extra_conds", []) or []) if isinstance(ec, dict)]
            if isinstance(t, dict) else []
            for t in trigs
        ]
        if any(len(ecs) > 0 for ecs in all_extra):
            lines += [
                "#ifndef NGPNG_COND_T",
                "#define NGPNG_COND_T",
                "typedef struct { u8 cond; u8 region; u16 value; } NgpngCond;",
                "#endif",
                "",
                f"#define {sym.upper()}_TRIG_EXTRA_CONDS 1",
                "",
            ]
            flat_conds: list[tuple[int, int, int]] = []
            cond_starts: list[int] = []
            cond_counts: list[int] = []
            for ecs in all_extra:
                cond_starts.append(len(flat_conds))
                cond_counts.append(len(ecs))
                for ec in ecs:
                    ec_cond = str(ec.get("cond", "enter_region") or "enter_region")
                    ec_cid = int(cond_to_id.get(ec_cond, 0))
                    ec_rid = str(ec.get("region_id", "") or "").strip()
                    ec_ridx = int(rid_to_idx.get(ec_rid, 255))
                    ec_val = int(ec.get("value", 0) or 0) & 0xFFFF
                    flat_conds.append((ec_cid, ec_ridx, ec_val))

            lines.append(f"static const NgpngCond g_{sym}_trig_conds[] = {{")
            for (ec_cid, ec_ridx, ec_val) in flat_conds:
                lines.append(f"    {{{ec_cid}, {ec_ridx}, (u16){ec_val}}},")
            lines.append("};")
            lines.append("")

            def _u8_row(data: list[int]) -> str:
                return ", ".join(str(v) for v in data)

            lines.append(f"static const u8 g_{sym}_trig_cond_count[] = {{{_u8_row(cond_counts)}}};")
            lines.append(f"static const u8 g_{sym}_trig_cond_start[] = {{{_u8_row(cond_starts)}}};")
            lines.append("")

        # OR-groups: trigger fires if primary+extra_conds OR any or_group is all-true
        all_or_groups: list[list[list[dict]]] = [
            [
                [ec for ec in (og or []) if isinstance(ec, dict)]
                for og in (t.get("or_groups", []) or [])
                if isinstance(og, list)
            ]
            if isinstance(t, dict) else []
            for t in trigs
        ]
        if any(len(ogs) > 0 for ogs in all_or_groups):
            lines += [
                "#ifndef NGPNG_COND_T",
                "#define NGPNG_COND_T",
                "typedef struct { u8 cond; u8 region; u16 value; } NgpngCond;",
                "#endif",
                "",
                f"#define {sym.upper()}_TRIG_HAS_OR_GROUPS 1",
                "",
            ]
            flat_or_conds: list[tuple[int, int, int]] = []
            or_cond_starts: list[int] = []
            or_cond_counts: list[int] = []
            or_group_starts: list[int] = []
            or_group_counts: list[int] = []
            for ogs in all_or_groups:
                or_group_starts.append(len(or_cond_starts))
                or_group_counts.append(len(ogs))
                for og in ogs:
                    or_cond_starts.append(len(flat_or_conds))
                    or_cond_counts.append(len(og))
                    for ec in og:
                        ec_cond = str(ec.get("cond", "enter_region") or "enter_region")
                        ec_cid = int(cond_to_id.get(ec_cond, 0))
                        ec_rid = str(ec.get("region_id", "") or "").strip()
                        ec_ridx = int(rid_to_idx.get(ec_rid, 255))
                        ec_val = int(ec.get("value", 0) or 0) & 0xFFFF
                        flat_or_conds.append((ec_cid, ec_ridx, ec_val))
            lines.append(f"static const NgpngCond g_{sym}_trig_or_conds[] = {{")
            for (oc_cid, oc_ridx, oc_val) in flat_or_conds:
                lines.append(f"    {{{oc_cid}, {oc_ridx}, (u16){oc_val}}},")
            lines.append("};")
            lines.append("")

            def _u8_row_or(data: list[int]) -> str:
                return ", ".join(str(v) for v in data)

            lines.append(f"static const u8 g_{sym}_trig_or_cond_start[] = {{{_u8_row_or(or_cond_starts)}}};")
            lines.append(f"static const u8 g_{sym}_trig_or_cond_count[] = {{{_u8_row_or(or_cond_counts)}}};")
            lines.append(f"static const u8 g_{sym}_trig_or_group_start[] = {{{_u8_row_or(or_group_starts)}}};")
            lines.append(f"static const u8 g_{sym}_trig_or_group_count[] = {{{_u8_row_or(or_group_counts)}}};")
            lines.append("")

    # ---- Paths (routes; points in pixel coords) ----
    pths = paths
    if pths is None:
        pths = scene.get("paths", []) or []
    if not isinstance(pths, list):
        pths = []

    pths = [p for p in pths if isinstance(p, dict)]
    if pths:
        lines += [sep, "/* Paths (routes)                                                     */", sep]
        lines += [
            "#ifndef NGPNG_POINT_T",
            "#define NGPNG_POINT_T",
            "typedef struct { s16 x; s16 y; } NgpngPoint;",
            "#endif",
            "",
            f"#define {sym.upper()}_PATH_COUNT {len(pths)}",
            "",
        ]

        def _safe_path_macro(name: str) -> str:
            clean = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").upper()
            return clean or "PATH"

        used_pmacros: set[str] = set()
        for i, p in enumerate(pths):
            nm = str(p.get("name", "") or f"path_{i}")
            macro = _safe_path_macro(nm)
            if macro in used_pmacros:
                macro = f"{macro}_{i}"
            used_pmacros.add(macro)
            lines.append(f"#define {sym.upper()}_PATH_{macro} {i}")
        lines.append("")

        points_flat: list[tuple[int, int]] = []
        offsets: list[int] = []
        lengths: list[int] = []
        flags: list[int] = []
        speeds: list[int] = []

        for p in pths:
            offsets.append(len(points_flat))
            pts_in = p.get("points", []) or []
            pts: list[tuple[int, int]] = []
            if isinstance(pts_in, list):
                for pt in pts_in:
                    pts.append(_path_point_to_px(pt))
            points_flat.extend(pts)
            lengths.append(len(pts))
            flags.append(1 if bool(p.get("loop", False)) else 0)
            speeds.append(max(1, min(8, int(p.get("speed", 1) or 1))))

        if not points_flat:
            points_flat = [(0, 0)]

        lines.append(f"static const u16 g_{sym}_path_offsets[] = {{ " + ", ".join(str(int(o)) for o in offsets) + " };")
        lines.append(f"static const u8  g_{sym}_path_lengths[] = {{ " + ", ".join(str(int(n) & 0xFF) for n in lengths) + " };")
        lines.append(f"static const u8  g_{sym}_path_flags[]   = {{ " + ", ".join(str(int(f) & 0xFF) for f in flags) + " };")
        lines.append(f"static const u8  g_{sym}_path_speeds[]  = {{ " + ", ".join(str(int(s) & 0xFF) for s in speeds) + " };")
        lines.append("")
        lines.append(f"static const NgpngPoint g_{sym}_path_points[] = {{")
        for x, y in points_flat:
            lines.append(f"    {{{int(x)}, {int(y)}}},")
        lines.append("};")
        lines.append("")

    # ---- Plane layering (SCR1/SCR2) metadata (optional) ----
    lyr = layers_cfg
    if lyr is None:
        lyr = scene.get("level_layers", {}) or {}
    if not isinstance(lyr, dict):
        lyr = {}

    def _clip_pct(v: int) -> int:
        return max(0, min(200, int(v)))

    scr1_px = _clip_pct(_cfg_int(lyr, "scr1_parallax_x", 100))
    scr1_py = _clip_pct(_cfg_int(lyr, "scr1_parallax_y", 100))
    scr2_px = _clip_pct(_cfg_int(lyr, "scr2_parallax_x", 100))
    scr2_py = _clip_pct(_cfg_int(lyr, "scr2_parallax_y", 100))

    front = str(lyr.get("bg_front", scene.get("level_bg_front", "scr1") or "scr1") or "scr1").strip().lower()
    if front not in ("scr1", "scr2"):
        front = "scr1"

    lines += [sep, "/* Plane layering (SCR1/SCR2) metadata                                */", sep]
    lines += [
        f"#define {sym.upper()}_BG_FRONT {1 if front == 'scr1' else 2}  /* 1=SCR1, 2=SCR2 */",
        f"#define {sym.upper()}_SCR1_PARALLAX_X_PCT {scr1_px}",
        f"#define {sym.upper()}_SCR1_PARALLAX_Y_PCT {scr1_py}",
        f"#define {sym.upper()}_SCR2_PARALLAX_X_PCT {scr2_px}",
        f"#define {sym.upper()}_SCR2_PARALLAX_Y_PCT {scr2_py}",
        "",
    ]

    # ---- Game profile / map mode metadata ----
    map_mode_now = str(map_mode or scene.get("map_mode", "none") or "none").strip().lower()
    if map_mode_now not in _MAP_MODE_TO_C:
        map_mode_now = "none"

    profile = str(scene.get("level_profile", "none") or "none").strip()
    if profile not in _PROFILE_TO_C:
        profile = "none"

    profile_preset = _PROFILE_PRESETS.get(profile, {}) if profile != "none" else {}
    hint_map_mode = str(profile_preset.get("map_mode", map_mode_now) or "none").strip().lower()
    if hint_map_mode not in _MAP_MODE_TO_C:
        hint_map_mode = "none"

    hint_scroll_x = 1 if bool(profile_preset.get("scroll_x", False)) else 0
    hint_scroll_y = 1 if bool(profile_preset.get("scroll_y", False)) else 0
    hint_forced = 1 if bool(profile_preset.get("forced", False)) else 0
    hint_loop_x = 1 if bool(profile_preset.get("loop_x", False)) else 0
    hint_loop_y = 1 if bool(profile_preset.get("loop_y", False)) else 0
    hint_lock_y = 1 if profile == "fighting" else 0
    hint_ground_band = 1 if profile == "brawler" else 0

    lines += [sep, "/* Game profile / map mode metadata                                    */", sep]
    lines += [
        "#ifndef NGPNG_LEVEL_META_ENUMS",
        "#define NGPNG_LEVEL_META_ENUMS",
        "#define NGPNG_MAP_MODE_NONE 0",
        "#define NGPNG_MAP_MODE_PLATFORMER 1",
        "#define NGPNG_MAP_MODE_TOPDOWN 2",
        "#define NGPNG_MAP_MODE_SHMUP 3",
        "#define NGPNG_MAP_MODE_OPEN 4",
        "#define NGPNG_PROFILE_NONE 0",
        "#define NGPNG_PROFILE_FIGHTING 1",
        "#define NGPNG_PROFILE_PLATFORMER 2",
        "#define NGPNG_PROFILE_RUN_GUN 3",
        "#define NGPNG_PROFILE_SHMUP 4",
        "#define NGPNG_PROFILE_BRAWLER 5",
        "#define NGPNG_PROFILE_TOPDOWN_RPG 6",
        "#define NGPNG_PROFILE_TACTICAL 7",
        "#define NGPNG_PROFILE_PUZZLE 8",
        "#define NGPNG_PROFILE_VISUAL_NOVEL 9",
        "#define NGPNG_PROFILE_RHYTHM 10",
        "#define NGPNG_SPRING_DIR_UP 0",
        "#define NGPNG_SPRING_DIR_DOWN 1",
        "#define NGPNG_SPRING_DIR_LEFT 2",
        "#define NGPNG_SPRING_DIR_RIGHT 3",
        "#define NGPNG_SPRING_DIR_OPPOSITE_TOUCH 4",
        "#endif",
        "",
        f"#define {sym.upper()}_MAP_MODE {_MAP_MODE_TO_C.get(map_mode_now, 0)}",
        f"#define {sym.upper()}_PROFILE {_PROFILE_TO_C.get(profile, 0)}",
        f"#define {sym.upper()}_PROFILE_MAP_MODE_HINT {_MAP_MODE_TO_C.get(hint_map_mode, 0)}",
        f"#define {sym.upper()}_PROFILE_SCROLL_X_HINT {hint_scroll_x}",
        f"#define {sym.upper()}_PROFILE_SCROLL_Y_HINT {hint_scroll_y}",
        f"#define {sym.upper()}_PROFILE_FORCED_SCROLL_HINT {hint_forced}",
        f"#define {sym.upper()}_PROFILE_LOOP_X_HINT {hint_loop_x}",
        f"#define {sym.upper()}_PROFILE_LOOP_Y_HINT {hint_loop_y}",
        f"#define {sym.upper()}_PROFILE_RULE_LOCK_Y_HINT {hint_lock_y}",
        f"#define {sym.upper()}_PROFILE_RULE_GROUND_BAND_HINT {hint_ground_band}",
        "",
    ]

    # ---- Placement rules / constraints (optional metadata) ----
    rules = rules_cfg
    if rules is None:
        rules = scene.get("level_rules", {}) or {}
    if not isinstance(rules, dict):
        rules = {}

    lock_en = 1 if bool(rules.get("lock_y_en", False)) else 0
    lock_y = int(rules.get("lock_y", 0) or 0) & 0xFF
    band_en = 1 if bool(rules.get("ground_band_en", False)) else 0
    gmin = int(rules.get("ground_min_y", 0) or 0) & 0xFF
    gmax = int(rules.get("ground_max_y", 0) or 0) & 0xFF
    mir_en = 1 if bool(rules.get("mirror_en", False)) else 0
    axis = int(rules.get("mirror_axis_x", 0) or 0) & 0xFF
    apply_waves = 1 if bool(rules.get("apply_to_waves", True)) else 0
    hazard_damage = int(rules.get("hazard_damage", 1) or 1) & 0xFF
    fire_damage = int(rules.get("fire_damage", 1) or 1) & 0xFF
    void_damage = int(rules.get("void_damage", 255) or 255) & 0xFF
    void_instant = 1 if bool(rules.get("void_instant", True)) else 0
    hazard_invul = int(rules.get("hazard_invul", 30) or 30) & 0xFF
    spring_force = max(0, min(127, int(rules.get("spring_force", 8) or 8))) & 0xFF
    spring_dir_name = str(rules.get("spring_dir", "up") or "up").strip().lower()
    spring_dir = {
        "up": 0,
        "down": 1,
        "left": 2,
        "right": 3,
        "opposite_touch": 4,
    }.get(spring_dir_name, 0)
    conveyor_speed = max(1, min(8, int(rules.get("conveyor_speed", 2) or 2))) & 0xFF
    zone_force     = max(1, min(8, int(rules.get("zone_force", 2) or 2))) & 0xFF
    ladder_top_solid = 1 if bool(rules.get("ladder_top_solid", False)) else 0
    ladder_top_exit = 1 if bool(rules.get("ladder_top_exit", True)) else 0
    ladder_side_move = 1 if bool(rules.get("ladder_side_move", False)) else 0
    hud_color_to_c = {
        "white": 0,
        "green": 1,
        "amber": 2,
        "cyan": 3,
        "red": 4,
        "blue": 5,
        "black": 6,
    }
    hud_style_to_c = {
        "text": 0,
        "band": 1,
    }
    hud_flags = 0
    if bool(rules.get("hud_show_hp", False)):
        hud_flags |= 2
    if bool(rules.get("hud_show_score", True)):
        hud_flags |= 1
    if bool(rules.get("hud_show_collect", True)):
        hud_flags |= 4
    if bool(rules.get("hud_show_timer", False)):
        hud_flags |= 8
    if bool(rules.get("hud_show_lives", False)):
        hud_flags |= 16
    hud_pos = 1 if str(rules.get("hud_pos", "top") or "top").strip().lower() == "bottom" else 0
    hud_font_mode = 1 if str(rules.get("hud_font_mode", "system") or "system").strip().lower() == "custom" else 0
    hud_fixed_plane = 0
    hud_fixed_plane_name = str(rules.get("hud_fixed_plane", "none") or "none").strip().lower()
    if hud_fixed_plane_name == "scr1":
        hud_fixed_plane = 1
    elif hud_fixed_plane_name == "scr2":
        hud_fixed_plane = 2
    hud_text_color = int(hud_color_to_c.get(str(rules.get("hud_text_color", "white") or "white").strip().lower(), 0))
    hud_style = int(hud_style_to_c.get(str(rules.get("hud_style", "text") or "text").strip().lower(), 0))
    hud_band_color = int(hud_color_to_c.get(str(rules.get("hud_band_color", "blue") or "blue").strip().lower(), 5))
    hud_band_rows = max(1, min(3, int(rules.get("hud_band_rows", 2) or 2))) & 0xFF
    hud_digits_hp = max(1, min(6, int(rules.get("hud_digits_hp", 2) or 2))) & 0xFF
    hud_digits_score = max(1, min(6, int(rules.get("hud_digits_score", 5) or 5))) & 0xFF
    hud_digits_collect = max(1, min(6, int(rules.get("hud_digits_collect", 3) or 3))) & 0xFF
    hud_digits_timer = max(1, min(6, int(rules.get("hud_digits_timer", 3) or 3))) & 0xFF
    hud_digits_lives = max(1, min(6, int(rules.get("hud_digits_lives", 2) or 2))) & 0xFF
    hud_digits_continues = max(1, min(6, int(rules.get("hud_digits_continues", 2) or 2))) & 0xFF
    goal_collectibles = int(rules.get("goal_collectibles", 0) or 0) & 0xFFFF
    time_limit_sec = int(rules.get("time_limit_sec", 0) or 0) & 0xFFFF
    start_lives = int(rules.get("start_lives", 0) or 0) & 0xFF
    start_continues = int(rules.get("start_continues", 0) or 0) & 0xFF
    continue_restore_lives = int(rules.get("continue_restore_lives", 3) or 0) & 0xFF
    hud_metric_to_c = {
        "hp": 0,
        "score": 1,
        "collect": 2,
        "timer": 3,
        "lives": 4,
        "continues": 5,
        "lap_count": 6,
    }
    hud_kind_to_c = {
        "icon": 0,
        "value": 1,
    }
    hud_digit_names = list(rules.get("hud_custom_font_digits", [""] * 10) or [""] * 10)
    while len(hud_digit_names) < 10:
        hud_digit_names.append("")
    hud_digit_names = hud_digit_names[:10]
    hud_custom_items_raw = rules.get("hud_custom_items", []) or []
    hud_custom_items: list[tuple[int, int, int, int, int, int, int]] = []
    if isinstance(hud_custom_items_raw, list):
        type_idx_by_name = {str(name): i for i, name in enumerate(seen_types)}
        hud_digit_types = [int(type_idx_by_name.get(str(name).strip(), 255)) for name in hud_digit_names]
        for item in hud_custom_items_raw:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", "icon") or "icon").strip().lower()
            metric = str(item.get("metric", "score") or "score").strip().lower()
            type_name = str(item.get("type_name", "") or "").strip()
            kind_id = int(hud_kind_to_c.get(kind, 0))
            metric_id = int(hud_metric_to_c.get(metric, 1))
            type_id = int(type_idx_by_name.get(type_name, 255))
            x = max(0, min(19, int(item.get("x", 0) or 0)))
            y = max(0, min(18, int(item.get("y", 0) or 0)))
            digits = max(1, min(6, int(item.get("digits", 5) or 5)))
            flags = 1 if bool(item.get("zero_pad", True)) else 0
            if kind_id == 0 and type_id == 255:
                continue
            hud_custom_items.append((kind_id, metric_id, type_id, x, y, digits, flags))
    else:
        hud_digit_types = [255] * 10

    lines += [sep, "/* Placement rules (optional metadata)                                */", sep]
    lines += [
        f"#define {sym.upper()}_RULE_LOCK_Y_EN {lock_en}",
        f"#define {sym.upper()}_RULE_LOCK_Y {lock_y}",
        f"#define {sym.upper()}_RULE_GROUND_BAND_EN {band_en}",
        f"#define {sym.upper()}_RULE_GROUND_MIN_Y {gmin}",
        f"#define {sym.upper()}_RULE_GROUND_MAX_Y {gmax}",
        f"#define {sym.upper()}_RULE_MIRROR_EN {mir_en}",
        f"#define {sym.upper()}_RULE_MIRROR_AXIS_X {axis}",
        f"#define {sym.upper()}_RULE_APPLY_TO_WAVES {apply_waves}",
        f"#define {sym.upper()}_RULE_HAZARD_DAMAGE {hazard_damage}",
        f"#define {sym.upper()}_RULE_FIRE_DAMAGE {fire_damage}",
        f"#define {sym.upper()}_RULE_VOID_DAMAGE {void_damage}",
        f"#define {sym.upper()}_RULE_VOID_INSTANT {void_instant}",
        f"#define {sym.upper()}_RULE_HAZARD_INVUL {hazard_invul}",
        f"#define {sym.upper()}_RULE_SPRING_FORCE {spring_force}",
        f"#define {sym.upper()}_RULE_SPRING_DIR {spring_dir}",
        f"#define {sym.upper()}_RULE_CONVEYOR_SPEED {conveyor_speed}",
        f"#define {sym.upper()}_RULE_ZONE_FORCE {zone_force}",
        f"#define {sym.upper()}_RULE_LADDER_TOP_SOLID {ladder_top_solid}",
        f"#define {sym.upper()}_RULE_LADDER_TOP_EXIT {ladder_top_exit}",
        f"#define {sym.upper()}_RULE_LADDER_SIDE_MOVE {ladder_side_move}",
        f"#define {sym.upper()}_RULE_HUD_FLAGS {hud_flags}",
        f"#define {sym.upper()}_RULE_HUD_POS {hud_pos}",
        f"#define {sym.upper()}_RULE_HUD_FONT_MODE {hud_font_mode}",
        f"#define {sym.upper()}_RULE_HUD_FIXED_PLANE {hud_fixed_plane}",
        f"#define {sym.upper()}_RULE_HUD_TEXT_COLOR {hud_text_color}",
        f"#define {sym.upper()}_RULE_HUD_STYLE {hud_style}",
        f"#define {sym.upper()}_RULE_HUD_BAND_COLOR {hud_band_color}",
        f"#define {sym.upper()}_RULE_HUD_BAND_ROWS {hud_band_rows}",
        f"#define {sym.upper()}_RULE_HUD_DIGITS_HP {hud_digits_hp}",
        f"#define {sym.upper()}_RULE_HUD_DIGITS_SCORE {hud_digits_score}",
        f"#define {sym.upper()}_RULE_HUD_DIGITS_COLLECT {hud_digits_collect}",
        f"#define {sym.upper()}_RULE_HUD_DIGITS_TIMER {hud_digits_timer}",
        f"#define {sym.upper()}_RULE_HUD_DIGITS_LIVES {hud_digits_lives}",
        f"#define {sym.upper()}_RULE_HUD_DIGITS_CONTINUES {hud_digits_continues}",
        f"#define {sym.upper()}_RULE_GOAL_COLLECTIBLES {goal_collectibles}",
        f"#define {sym.upper()}_RULE_TIME_LIMIT_SEC {time_limit_sec}",
        f"#define {sym.upper()}_RULE_START_LIVES {start_lives}",
        f"#define {sym.upper()}_RULE_START_CONTINUES {start_continues}",
        f"#define {sym.upper()}_RULE_CONTINUE_RESTORE_LIVES {continue_restore_lives}",
        "",
    ]

    if hud_custom_items:
        lines += [
            "#ifndef NGPNG_HUD_ITEM_T",
            "#define NGPNG_HUD_ITEM_T",
            "typedef struct { u8 kind; u8 metric; u8 type; u8 x; u8 y; u8 digits; u8 flags; } NgpngHudItem;",
            "#endif",
            "",
            f"#define {sym.upper()}_HUD_ITEM_COUNT {len(hud_custom_items)}",
            f"static const NgpngHudItem g_{sym}_hud_items[] = {{",
        ]
        for kind_id, metric_id, type_id, x, y, digits, flags in hud_custom_items:
            lines.append(f"    {{{kind_id}, {metric_id}, {type_id}, {x}, {y}, {digits}, {flags}}},")
        lines += [
            "};",
            "",
        ]
    if any(v != 255 for v in hud_digit_types):
        lines.append(f"static const u8 g_{sym}_hud_digit_types[] = {{{', '.join(str(int(v)) for v in hud_digit_types)}}};")
        lines.append(f"#define {sym.upper()}_HUD_DIGIT_TYPES 1")
        lines.append("")

    # ---- Layout / scrolling metadata (optional; game-defined semantics) ----
    cam_x, cam_y = 0, 0
    if cam_tile is not None:
        cam_x, cam_y = int(cam_tile[0]), int(cam_tile[1])
    else:
        cam = scene.get("level_cam_tile", {}) or {}
        if isinstance(cam, dict):
            cam_x = int(cam.get("x", 0))
            cam_y = int(cam.get("y", 0))

    sc = scroll_cfg
    if sc is None:
        sc = scene.get("level_scroll", {}) or {}
    if not isinstance(sc, dict):
        sc = {}

    lay = layout_cfg
    if lay is None:
        lay = scene.get("level_layout", {}) or {}
    if not isinstance(lay, dict):
        lay = {}

    cam_mode = str(lay.get("cam_mode", "") or "").strip()
    if cam_mode not in _CAM_MODE_TO_C:
        cam_mode = "single_screen"
    clamp = 1 if bool(lay.get("clamp", True)) else 0
    bounds_auto = bool(lay.get("bounds_auto", True))
    if bounds_auto:
        min_x = 0
        min_y = 0
        max_x = max(0, (int(map_w) - _SCREEN_W) * 8) if map_w is not None else 0
        max_y = max(0, (int(map_h) - _SCREEN_H) * 8) if map_h is not None else 0
    else:
        min_x = int(lay.get("min_x", 0) or 0) * 8
        min_y = int(lay.get("min_y", 0) or 0) * 8
        max_x = int(lay.get("max_x", 0) or 0) * 8
        max_y = int(lay.get("max_y", 0) or 0) * 8
    follow_deadzone_x = max(0, min(79, _cfg_int(lay, "follow_deadzone_x", 16)))
    follow_deadzone_y = max(0, min(71, _cfg_int(lay, "follow_deadzone_y", 12)))
    follow_drop_margin_y = max(0, min(71, _cfg_int(lay, "follow_drop_margin_y", 20)))

    lines += [sep, "/* Layout / scroll metadata                                           */", sep]
    lines += [
        f"#define {sym.upper()}_MAP_W {int(map_w)}",
        f"#define {sym.upper()}_MAP_H {int(map_h)}",
        f"#define {sym.upper()}_CAM_MODE {_CAM_MODE_TO_C.get(cam_mode, 0)}",
        f"#define {sym.upper()}_CAM_CLAMP {clamp}",
        f"#define {sym.upper()}_CAM_MIN_X {int(min_x)}",
        f"#define {sym.upper()}_CAM_MIN_Y {int(min_y)}",
        f"#define {sym.upper()}_CAM_MAX_X {int(max_x)}",
        f"#define {sym.upper()}_CAM_MAX_Y {int(max_y)}",
        f"#define {sym.upper()}_CAM_FOLLOW_DEADZONE_X {int(follow_deadzone_x)}",
        f"#define {sym.upper()}_CAM_FOLLOW_DEADZONE_Y {int(follow_deadzone_y)}",
        f"#define {sym.upper()}_CAM_FOLLOW_DROP_MARGIN_Y {int(follow_drop_margin_y)}",
        f"#define {sym.upper()}_CAM_TILE_X {cam_x}",
        f"#define {sym.upper()}_CAM_TILE_Y {cam_y}",
        f"#define {sym.upper()}_SCROLL_X {1 if bool(sc.get('scroll_x', False)) else 0}",
        f"#define {sym.upper()}_SCROLL_Y {1 if bool(sc.get('scroll_y', False)) else 0}",
        f"#define {sym.upper()}_FORCED_SCROLL {1 if bool(sc.get('forced', False)) else 0}",
        f"#define {sym.upper()}_SCROLL_SPEED_X {int(sc.get('speed_x', 0))}",
        f"#define {sym.upper()}_SCROLL_SPEED_Y {int(sc.get('speed_y', 0))}",
        f"#define {sym.upper()}_LOOP_X {1 if bool(sc.get('loop_x', False)) else 0}",
        f"#define {sym.upper()}_LOOP_Y {1 if bool(sc.get('loop_y', False)) else 0}",
        "",
    ]

    lines.append(f"#endif /* {guard} */")
    lines.append("")
    return "\n".join(lines)
