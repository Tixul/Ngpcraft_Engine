"""
core/scene_presets.py - Reusable scene starter presets for Project/Level workflows.

Each preset sets profile/map_mode, camera, scroll, HUD rules, layer parallax, and
injects minimal starter regions/triggers when the scene still has none — without
touching existing sprites or tilemaps.
"""

from __future__ import annotations

import copy
import uuid


SCENE_PRESETS: tuple[tuple[str, str], ...] = (
    ("platformer_basic",   "proj.scene_preset.platformer"),
    ("shmup_vertical",     "proj.scene_preset.shmup"),
    ("run_gun_horizontal", "proj.scene_preset.run_gun"),
    ("brawler_stage",      "proj.scene_preset.brawler"),
    ("fighting_1v1",       "proj.scene_preset.fighting"),
    ("topdown_room",       "proj.scene_preset.topdown"),
    ("race_topdown",       "proj.scene_preset.race"),
    ("puzzle_grid",        "proj.scene_preset.puzzle"),
    ("tcg_screen",         "proj.scene_preset.tcg"),
    ("rhythm_vertical",    "proj.scene_preset.rhythm"),
    ("tactical_grid",      "proj.scene_preset.tactical"),
    ("intro_skipable",     "proj.scene_preset.intro"),
    ("menu_single",        "proj.scene_preset.menu"),
    ("roguelite_room",     "proj.scene_preset.roguelite_room"),
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def apply_scene_preset(scene: dict, preset_key: str) -> bool:
    """
    Apply one named scene preset in-place.

    Preserves existing assets (sprites/tilemaps) and only fills
    gameplay/layout metadata. Starter regions/triggers are only injected
    when the scene has none.
    """
    if not isinstance(scene, dict):
        return False
    key = str(preset_key or "").strip().lower()
    if not key:
        return False

    dispatch = {
        "platformer_basic":   _apply_platformer_basic,
        "shmup_vertical":     _apply_shmup_vertical,
        "run_gun_horizontal": _apply_run_gun_horizontal,
        "brawler_stage":      _apply_brawler_stage,
        "fighting_1v1":       _apply_fighting_1v1,
        "topdown_room":       _apply_topdown_room,
        "race_topdown":       _apply_race_topdown,
        "puzzle_grid":        _apply_puzzle_grid,
        "tcg_screen":         _apply_tcg_screen,
        "rhythm_vertical":    _apply_rhythm_vertical,
        "tactical_grid":      _apply_tactical_grid,
        "intro_skipable":     _apply_intro_skipable,
        "menu_single":        _apply_menu_single,
        "roguelite_room":     _apply_roguelite_room,
    }
    fn = dispatch.get(key)
    _ensure_scene_lists(scene)
    return fn(scene) if fn else False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_scene_size(scene: dict, w: int, h: int) -> None:
    scene["level_size"] = {"w": int(w), "h": int(h)}
    scene["map_w"] = int(w)
    scene["map_h"] = int(h)
    scene["grid_w"] = int(w)
    scene["grid_h"] = int(h)


def _ensure_rules(scene: dict) -> dict:
    rules = scene.get("level_rules", {}) or {}
    if not isinstance(rules, dict):
        rules = {}
    scene["level_rules"] = rules
    return rules


def _ensure_layout(scene: dict) -> dict:
    layout = scene.get("level_layout", {}) or {}
    if not isinstance(layout, dict):
        layout = {}
    scene["level_layout"] = layout
    return layout


def _ensure_scroll(scene: dict) -> dict:
    scroll = scene.get("level_scroll", {}) or {}
    if not isinstance(scroll, dict):
        scroll = {}
    scene["level_scroll"] = scroll
    return scroll


def _ensure_layers(scene: dict) -> dict:
    layers = scene.get("level_layers", {}) or {}
    if not isinstance(layers, dict):
        layers = {}
    scene["level_layers"] = layers
    return layers


def _ensure_scene_lists(scene: dict) -> None:
    for key in ("regions", "triggers", "paths", "text_labels", "dialogues", "menus"):
        if not isinstance(scene.get(key), list):
            scene[key] = []


def _apply_rule_defaults(scene: dict, **overrides) -> dict:
    rules = _ensure_rules(scene)
    map_w = _map_w(scene, 20)
    map_h = _map_h(scene, 19)
    defaults = {
        "lock_y_en": False,
        "lock_y": 0,
        "ground_band_en": False,
        "ground_min_y": 0,
        "ground_max_y": max(0, map_h - 1),
        "mirror_en": False,
        "mirror_axis_x": max(0, (map_w - 1) // 2),
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
        "ladder_top_exit": True,
        "ladder_side_move": False,
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
    for key, value in defaults.items():
        rules.setdefault(key, copy.deepcopy(value))
    for key, value in overrides.items():
        rules[key] = copy.deepcopy(value)
    return rules


def _hud_value_item(name: str, metric: str, x: int, y: int, digits: int, zero_pad: bool = False) -> dict:
    return {
        "name": str(name or "hud_item"),
        "kind": "value",
        "metric": str(metric or "score"),
        "type_name": "",
        "x": int(x),
        "y": int(y),
        "digits": int(digits),
        "zero_pad": bool(zero_pad),
    }


def _set_layer_defaults(layers: dict) -> None:
    layers.setdefault("scr1_parallax_x", 100)
    layers.setdefault("scr1_parallax_y", 100)
    layers.setdefault("scr2_parallax_x", 100)
    layers.setdefault("scr2_parallax_y", 100)
    layers.setdefault("bg_front", "scr1")


def _regions_empty(scene: dict) -> bool:
    r = scene.get("regions", [])
    return isinstance(r, list) and not r


def _triggers_empty(scene: dict) -> bool:
    t = scene.get("triggers", [])
    return isinstance(t, list) and not t


def _map_w(scene: dict, default: int) -> int:
    return int(scene.get("map_w", default) or default)


def _map_h(scene: dict, default: int) -> int:
    return int(scene.get("map_h", default) or default)


def _reg(label: str, kind: str, x: int, y: int, w: int, h: int, **extra) -> dict:
    d = {"id": _new_id("reg"), "name": label, "kind": kind,
         "x": x, "y": y, "w": w, "h": h}
    d.update(extra)
    return d


def _trig(name: str, cond: str, action: str, **kw) -> dict:
    d = {
        "id": _new_id("trig"), "name": name,
        "cond": cond, "action": action,
        "region_id": "", "value": 0,
        "value_const": "",
        "scene_to": "", "target_id": "", "entity_target_id": "",
        "entity_index": 0, "dest_region_id": "",
        "dest_tile_x": -1, "dest_tile_y": -1,
        "dialogue_id": "", "npc_dialogue_id": "", "menu_id": "",
        "cond_dialogue_id": "", "cond_menu_id": "",
        "menu_item_idx": 0, "choice_idx": 0,
        "flag_var_index": 0, "spawn_index": 0,
        "event": 0, "param": 0, "a0": 0, "a1": 0,
        "once": False, "extra_conds": [],
    }
    d.update(kw)
    return d


# ---------------------------------------------------------------------------
# 1 — Platformer
# ---------------------------------------------------------------------------

def _apply_platformer_basic(scene: dict) -> bool:
    _ensure_scene_size(scene, 64, 19)
    scene["level_profile"] = "platformer"
    scene["map_mode"] = "platformer"

    _ensure_scroll(scene).update({
        "scroll_x": True, "scroll_y": True,
        "forced": False, "speed_x": 0, "speed_y": 0,
        "loop_x": False, "loop_y": False,
    })
    _ensure_layout(scene).update({
        "cam_mode": "follow", "bounds_auto": True, "clamp": True,
        "follow_deadzone_x": 16, "follow_deadzone_y": 12, "follow_drop_margin_y": 20,
    })
    rules = _apply_rule_defaults(
        scene,
        hud_enabled=True,
        hud_show_hp=False,
        hud_show_score=True,
        hud_show_collect=True,
        hud_show_timer=False,
        hud_show_lives=True,
        hud_pos="top",
        hud_font_mode="system",
        hud_text_color="white",
        hud_style="text",
        hud_band_color="blue",
        hud_band_rows=2,
        hud_digits_score=5,
        hud_digits_collect=3,
        hud_digits_lives=2,
        start_lives=3,
        start_continues=2,
        continue_restore_lives=3,
    )
    rules["goal_collectibles"] = max(0, int(rules.get("goal_collectibles", 0) or 0))
    layers = _ensure_layers(scene)
    _set_layer_defaults(layers)
    layers["scr2_parallax_x"] = 50
    layers["scr2_parallax_y"] = 80

    checkpoint_region = None
    if _regions_empty(scene):
        h = _map_h(scene, 19)
        w = _map_w(scene, 64)
        checkpoint_region = _reg("checkpoint_start", "checkpoint", 1, max(0, h - 5), 4, 4)
        scene["regions"] = [
            checkpoint_region,
            _reg("goal_exit",        "exit_goal",  max(0, w - 5), max(0, h - 5), 4, 4),
        ]
    else:
        checkpoint_region = next(
            (
                reg for reg in (scene.get("regions") or [])
                if isinstance(reg, dict) and str(reg.get("kind") or "") == "checkpoint"
            ),
            None,
        )
    if _triggers_empty(scene):
        triggers: list[dict] = []
        if isinstance(checkpoint_region, dict):
            triggers.append(
                _trig(
                    "checkpoint_touch",
                    "enter_region",
                    "set_checkpoint",
                    region_id=str(checkpoint_region.get("id") or ""),
                    once=False,
                )
            )
        triggers.append(_trig("respawn_on_death", "on_death", "respawn_player", once=False))
        scene["triggers"] = triggers
    return True


# ---------------------------------------------------------------------------
# 2 — Shmup vertical
# ---------------------------------------------------------------------------

def _apply_shmup_vertical(scene: dict) -> bool:
    _ensure_scene_size(scene, 20, 96)
    scene["level_profile"] = "shmup"
    scene["map_mode"] = "shmup"

    _ensure_scroll(scene).update({
        "scroll_x": False, "scroll_y": True,
        "forced": True, "speed_x": 0, "speed_y": 1,
        "loop_x": False, "loop_y": True,
    })
    _ensure_layout(scene).update({
        "cam_mode": "forced_scroll", "bounds_auto": True, "clamp": True,
        "follow_deadzone_x": 16, "follow_deadzone_y": 12, "follow_drop_margin_y": 20,
    })
    _apply_rule_defaults(
        scene,
        hud_enabled=True,
        hud_show_hp=False,
        hud_show_score=True,
        hud_show_collect=False,
        hud_show_timer=False,
        hud_show_lives=True,
        hud_pos="top",
        hud_font_mode="system",
        hud_text_color="white",
        hud_style="text",
        hud_band_color="blue",
        hud_band_rows=2,
        hud_digits_score=5,
        hud_digits_lives=2,
        start_lives=3,
        start_continues=2,
        continue_restore_lives=3,
        goal_collectibles=0,
    )
    layers = _ensure_layers(scene)
    _set_layer_defaults(layers)
    layers["scr2_parallax_x"] = 100
    layers["scr2_parallax_y"] = 40   # slow star background

    if _regions_empty(scene):
        h = _map_h(scene, 96)
        scene["regions"] = [
            _reg("player_spawn", "spawn", 8, max(0, h - 4), 4, 3),
        ]
    return True


# ---------------------------------------------------------------------------
# 3 — Run & Gun horizontal
# ---------------------------------------------------------------------------

def _apply_run_gun_horizontal(scene: dict) -> bool:
    _ensure_scene_size(scene, 96, 19)
    scene["level_profile"] = "run_gun"
    scene["map_mode"] = "platformer"

    _ensure_scroll(scene).update({
        "scroll_x": True, "scroll_y": False,
        "forced": False, "speed_x": 0, "speed_y": 0,
        "loop_x": False, "loop_y": False,
    })
    _ensure_layout(scene).update({
        "cam_mode": "follow", "bounds_auto": True, "clamp": True,
        "follow_deadzone_x": 20, "follow_deadzone_y": 8, "follow_drop_margin_y": 20,
    })
    _apply_rule_defaults(
        scene,
        hud_enabled=True,
        hud_show_hp=False,
        hud_show_score=True,
        hud_show_collect=False,
        hud_show_timer=False,
        hud_show_lives=True,
        hud_pos="top",
        hud_font_mode="system",
        hud_text_color="white",
        hud_style="text",
        hud_band_color="blue",
        hud_band_rows=2,
        hud_digits_score=5,
        hud_digits_lives=2,
        start_lives=3,
        start_continues=2,
        continue_restore_lives=3,
        goal_collectibles=0,
    )
    layers = _ensure_layers(scene)
    _set_layer_defaults(layers)
    layers["scr2_parallax_x"] = 50
    layers["scr2_parallax_y"] = 100

    if _regions_empty(scene):
        h = _map_h(scene, 19)
        w = _map_w(scene, 96)
        scene["regions"] = [
            _reg("player_spawn", "spawn",     1,            max(0, h - 5), 3, 4),
            _reg("goal_exit",    "exit_goal", max(0, w - 5), max(0, h - 5), 4, 4),
        ]
    if _triggers_empty(scene):
        scene["triggers"] = [
            _trig("player_fire", "btn_a", "fire_player_shot", once=False),
            _trig("respawn_on_death", "on_death", "respawn_player", once=False),
        ]
    return True


# ---------------------------------------------------------------------------
# 4 — Brawler stage
# ---------------------------------------------------------------------------

def _apply_brawler_stage(scene: dict) -> bool:
    _ensure_scene_size(scene, 48, 19)
    scene["level_profile"] = "brawler"
    scene["map_mode"] = "none"

    _ensure_scroll(scene).update({
        "scroll_x": True, "scroll_y": True,
        "forced": False, "speed_x": 0, "speed_y": 0,
        "loop_x": False, "loop_y": False,
    })
    _ensure_layout(scene).update({
        "cam_mode": "follow", "bounds_auto": True, "clamp": True,
        "follow_deadzone_x": 32, "follow_deadzone_y": 16, "follow_drop_margin_y": 20,
    })
    h = _map_h(scene, 19)
    _apply_rule_defaults(
        scene,
        ground_band_en=True,
        ground_min_y=max(0, h - 8),
        ground_max_y=max(max(0, h - 8), h - 2),
        hud_enabled=True,
        hud_show_hp=True,
        hud_show_score=True,
        hud_show_collect=False,
        hud_show_timer=False,
        hud_show_lives=True,
        hud_pos="top",
        hud_font_mode="system",
        hud_text_color="white",
        hud_style="band",
        hud_band_color="amber",
        hud_band_rows=2,
        hud_digits_hp=2,
        hud_digits_score=5,
        hud_digits_lives=2,
        start_lives=3,
        start_continues=2,
        continue_restore_lives=3,
        goal_collectibles=0,
    )
    layers = _ensure_layers(scene)
    _set_layer_defaults(layers)
    layers["scr2_parallax_x"] = 30   # slow crowd background
    layers["scr2_parallax_y"] = 0

    if _regions_empty(scene):
        h = _map_h(scene, 19)
        w = _map_w(scene, 48)
        scene["regions"] = [
            _reg("player_spawn", "spawn",     3,            max(0, h - 6), 4, 5),
            _reg("stage_end",    "exit_goal", max(0, w - 5), max(0, h - 6), 4, 5),
        ]
    if _triggers_empty(scene):
        scene["triggers"] = [
            _trig("player_attack", "btn_a", "emit_event", event=1, param=0, once=False),
        ]
    return True


# ---------------------------------------------------------------------------
# 5 — Fighting 1v1
# ---------------------------------------------------------------------------

def _apply_fighting_1v1(scene: dict) -> bool:
    _ensure_scene_size(scene, 32, 19)
    scene["level_profile"] = "fighting"
    scene["map_mode"] = "none"

    _ensure_scroll(scene).update({
        "scroll_x": False, "scroll_y": False,
        "forced": False, "speed_x": 0, "speed_y": 0,
        "loop_x": False, "loop_y": False,
    })
    _ensure_layout(scene).update({
        "cam_mode": "single_screen", "bounds_auto": True, "clamp": True,
        "follow_deadzone_x": 16, "follow_deadzone_y": 12, "follow_drop_margin_y": 20,
    })
    h = _map_h(scene, 19)
    _apply_rule_defaults(
        scene,
        lock_y_en=True,
        lock_y=max(0, h - 5),
        hud_enabled=True,
        hud_show_hp=True,
        hud_show_score=False,
        hud_show_collect=False,
        hud_show_timer=True,
        hud_show_lives=False,
        hud_pos="top",
        hud_font_mode="system",
        hud_text_color="white",
        hud_style="band",
        hud_band_color="red",
        hud_band_rows=2,
        hud_digits_hp=2,
        hud_digits_timer=2,
        start_lives=0,
        start_continues=0,
        continue_restore_lives=0,
        time_limit_sec=99,
        goal_collectibles=0,
    )
    layers = _ensure_layers(scene)
    _set_layer_defaults(layers)
    layers["scr2_parallax_x"] = 0   # fully static arena background
    layers["scr2_parallax_y"] = 0

    if _regions_empty(scene):
        h = _map_h(scene, 19)
        w = _map_w(scene, 32)
        scene["regions"] = [
            _reg("spawn_p1",    "spawn",       3,            max(0, h - 7), 3, 5),
            _reg("spawn_p2",    "spawn",       max(0, w - 6), max(0, h - 7), 3, 5),
            _reg("arena_lock",  "camera_lock", 0, 0, w, h),
        ]
    return True


# ---------------------------------------------------------------------------
# 6 — Top-down room (RPG/adventure)
# ---------------------------------------------------------------------------

def _apply_topdown_room(scene: dict) -> bool:
    _ensure_scene_size(scene, 32, 32)
    scene["level_profile"] = "topdown_rpg"
    scene["map_mode"] = "topdown"

    _ensure_scroll(scene).update({
        "scroll_x": True, "scroll_y": True,
        "forced": False, "speed_x": 0, "speed_y": 0,
        "loop_x": False, "loop_y": False,
    })
    _ensure_layout(scene).update({
        "cam_mode": "follow", "bounds_auto": True, "clamp": True,
        "follow_deadzone_x": 20, "follow_deadzone_y": 16, "follow_drop_margin_y": 20,
    })
    rules = _apply_rule_defaults(
        scene,
        hud_enabled=False,
        hud_show_hp=False,
        hud_show_score=False,
        hud_show_collect=False,
        hud_show_timer=False,
        hud_show_lives=False,
        hud_pos="top",
        hud_font_mode="system",
    )
    rules["start_lives"] = max(0, int(rules.get("start_lives", 0) or 0))
    rules["start_continues"] = max(0, int(rules.get("start_continues", 0) or 0))
    layers = _ensure_layers(scene)
    _set_layer_defaults(layers)

    if _regions_empty(scene):
        h = _map_h(scene, 32)
        w = _map_w(scene, 32)
        scene["regions"] = [
            _reg("player_spawn", "spawn",     14, 14, 3, 3),
            _reg("room_exit",    "exit_goal", max(0, w - 5), max(0, h - 5), 4, 4),
        ]
    return True


# ---------------------------------------------------------------------------
# 7 — Top-down race circuit
# ---------------------------------------------------------------------------

def _apply_race_topdown(scene: dict) -> bool:
    _ensure_scene_size(scene, 48, 48)
    scene["level_profile"] = "race"
    scene["map_mode"] = "race"

    _ensure_scroll(scene).update({
        "scroll_x": True, "scroll_y": True,
        "forced": False, "speed_x": 0, "speed_y": 0,
        "loop_x": True, "loop_y": True,
    })
    _ensure_layout(scene).update({
        "cam_mode": "follow", "bounds_auto": True, "clamp": True,
        "follow_deadzone_x": 20, "follow_deadzone_y": 20, "follow_drop_margin_y": 20,
    })
    rules = _apply_rule_defaults(
        scene,
        hud_enabled=True,
        hud_show_hp=False,
        hud_show_score=True,
        hud_show_collect=False,
        hud_show_timer=True,
        hud_show_lives=False,
        hud_pos="top",
        hud_font_mode="system",
        hud_text_color="white",
        hud_style="band",
        hud_band_color="cyan",
        hud_band_rows=1,
        hud_digits_timer=3,
        hud_digits_score=3,
        start_lives=0,
        start_continues=0,
        continue_restore_lives=0,
        goal_collectibles=0,
        time_limit_sec=0,
    )
    if not (rules.get("hud_custom_items") or []):
        rules["hud_custom_items"] = [_hud_value_item("lap_counter", "lap_count", 112, 0, 2, False)]
    layers = _ensure_layers(scene)
    _set_layer_defaults(layers)

    if _regions_empty(scene):
        scene["regions"] = [
            _reg("player_spawn", "spawn",     22, 22, 4, 4),
            _reg("gate_0",       "lap_gate",  20, 20, 8, 2, gate_index=0),
            _reg("wp_0",         "race_waypoint", 24, 16, 2, 2, wp_index=0),
        ]
    if _triggers_empty(scene):
        scene["triggers"] = [
            _trig("countdown_start", "scene_first_enter", "lock_player_input", once=True),
            _trig("countdown_go", "timer_ge", "unlock_player_input", value=180, once=True),
            _trig("lap_gate_cross",  "lap_ge", "emit_event", value=1, event=1, param=0, once=False),
        ]
    return True


# ---------------------------------------------------------------------------
# 8 — Puzzle grid (Sokoban-style)
# ---------------------------------------------------------------------------

def _apply_puzzle_grid(scene: dict) -> bool:
    _ensure_scene_size(scene, 20, 19)
    scene["level_profile"] = "puzzle"
    scene["map_mode"] = "puzzle"

    _ensure_scroll(scene).update({
        "scroll_x": False, "scroll_y": False,
        "forced": False, "speed_x": 0, "speed_y": 0,
        "loop_x": False, "loop_y": False,
    })
    _ensure_layout(scene).update({
        "cam_mode": "single_screen", "bounds_auto": True, "clamp": True,
        "follow_deadzone_x": 16, "follow_deadzone_y": 12, "follow_drop_margin_y": 20,
    })
    _apply_rule_defaults(
        scene,
        hud_enabled=True,
        hud_show_hp=False,
        hud_show_score=False,
        hud_show_collect=True,
        hud_show_timer=False,
        hud_show_lives=False,
        hud_pos="top",
        hud_font_mode="system",
        hud_text_color="white",
        hud_style="text",
        hud_band_color="blue",
        hud_band_rows=2,
        hud_digits_collect=3,
        start_lives=0,
        start_continues=0,
        continue_restore_lives=0,
        goal_collectibles=0,
        time_limit_sec=0,
    )
    layers = _ensure_layers(scene)
    _set_layer_defaults(layers)

    target_0 = None
    target_1 = None
    if _regions_empty(scene):
        target_0 = _reg("target_0", "zone", 4, 14, 2, 2)
        target_1 = _reg("target_1", "zone", 14, 14, 2, 2)
        scene["regions"] = [
            _reg("player_spawn", "spawn",      9,  9, 2, 2),
            _reg("block_0",      "push_block",  4,  7, 1, 1),
            _reg("block_1",      "push_block", 14,  7, 1, 1),
            target_0,
            target_1,
        ]
    else:
        zone_regions = [
            reg for reg in (scene.get("regions") or [])
            if isinstance(reg, dict) and str(reg.get("kind") or "") == "zone"
        ]
        target_0 = zone_regions[0] if len(zone_regions) > 0 else None
        target_1 = zone_regions[1] if len(zone_regions) > 1 else None
    if _triggers_empty(scene):
        triggers: list[dict] = []
        if isinstance(target_0, dict):
            triggers.append(
                _trig(
                    "block_on_target_0",
                    "block_on_tile",
                    "play_sfx",
                    region_id=str(target_0.get("id") or ""),
                    event=0,
                    once=False,
                )
            )
        if isinstance(target_1, dict):
            triggers.append(
                _trig(
                    "block_on_target_1",
                    "block_on_tile",
                    "play_sfx",
                    region_id=str(target_1.get("id") or ""),
                    event=0,
                    once=False,
                )
            )
        triggers.append(_trig("reset_on_death", "on_death", "reset_scene", once=False))
        scene["triggers"] = triggers
    return True


# ---------------------------------------------------------------------------
# 9 — TCG / Card game
# ---------------------------------------------------------------------------

def _apply_tcg_screen(scene: dict) -> bool:
    _ensure_scene_size(scene, 20, 19)
    scene["level_profile"] = "tcg"
    scene["map_mode"] = "none"

    _ensure_scroll(scene).update({
        "scroll_x": False, "scroll_y": False,
        "forced": False, "speed_x": 0, "speed_y": 0,
        "loop_x": False, "loop_y": False,
    })
    _ensure_layout(scene).update({
        "cam_mode": "single_screen", "bounds_auto": True, "clamp": True,
        "follow_deadzone_x": 16, "follow_deadzone_y": 12, "follow_drop_margin_y": 20,
    })
    _apply_rule_defaults(
        scene,
        hud_enabled=False,
        hud_show_hp=False,
        hud_show_score=False,
        hud_show_collect=False,
        hud_show_timer=False,
        hud_show_lives=False,
        hud_pos="top",
        hud_font_mode="system",
        start_lives=0,
        start_continues=0,
        continue_restore_lives=0,
        goal_collectibles=0,
        time_limit_sec=0,
    )
    layers = _ensure_layers(scene)
    _set_layer_defaults(layers)

    slot_regions: list[dict] = []
    if _regions_empty(scene):
        slot_regions = [
            _reg("slot_0", "card_slot", 2, 3, 4, 4, slot_type=0),
            _reg("slot_1", "card_slot", 8, 3, 4, 4, slot_type=1),
            _reg("slot_2", "card_slot", 14, 3, 4, 4, slot_type=2),
        ]
        scene["regions"] = [
            _reg("player_spawn", "spawn",     8, 15, 4, 3),
            *slot_regions,
        ]
    else:
        slot_regions = [
            reg for reg in (scene.get("regions") or [])
            if isinstance(reg, dict) and str(reg.get("kind") or "") == "card_slot"
        ]
    if _triggers_empty(scene):
        scene["triggers"] = [
            _trig("draw_phase", "scene_first_enter", "spawn_entity", event=0, param=0, once=True),
            *[
                _trig(
                    f"card_played_slot_{idx}",
                    "entity_in_region",
                    "emit_event",
                    region_id=str(slot.get("id") or ""),
                    event=1,
                    param=idx,
                    once=False,
                )
                for idx, slot in enumerate(slot_regions)
            ],
            _trig("turn_end", "variable_ge", "emit_event", flag_var_index=0, value=1, event=2, param=0, once=False),
        ]
    return True


# ---------------------------------------------------------------------------
# 10 — Rhythm game
# ---------------------------------------------------------------------------

def _apply_rhythm_vertical(scene: dict) -> bool:
    _ensure_scene_size(scene, 20, 32)
    scene["level_profile"] = "rhythm"
    scene["map_mode"] = "none"

    _ensure_scroll(scene).update({
        "scroll_x": False, "scroll_y": True,
        "forced": True, "speed_x": 0, "speed_y": 1,
        "loop_x": False, "loop_y": True,
    })
    _ensure_layout(scene).update({
        "cam_mode": "forced_scroll", "bounds_auto": True, "clamp": True,
        "follow_deadzone_x": 16, "follow_deadzone_y": 12, "follow_drop_margin_y": 20,
    })
    _apply_rule_defaults(
        scene,
        hud_enabled=True,
        hud_show_hp=False,
        hud_show_score=True,
        hud_show_collect=True,
        hud_show_timer=False,
        hud_show_lives=False,
        hud_pos="top",
        hud_font_mode="system",
        hud_text_color="white",
        hud_style="band",
        hud_band_color="green",
        hud_band_rows=1,
        hud_digits_score=5,
        hud_digits_collect=3,
        start_lives=0,
        start_continues=0,
        continue_restore_lives=0,
        goal_collectibles=0,
        time_limit_sec=0,
    )
    layers = _ensure_layers(scene)
    _set_layer_defaults(layers)
    layers["scr2_parallax_x"] = 100
    layers["scr2_parallax_y"] = 40   # slow background drift

    if _regions_empty(scene):
        h = _map_h(scene, 32)
        scene["regions"] = [
            _reg("hit_zone", "zone", 7, max(0, h - 5), 6, 3),
        ]
    if _triggers_empty(scene):
        scene["triggers"] = [
            _trig("player_hit", "btn_a", "fire_player_shot", once=False),
        ]
    return True


# ---------------------------------------------------------------------------
# 11 — Tactical grid
# ---------------------------------------------------------------------------

def _apply_tactical_grid(scene: dict) -> bool:
    _ensure_scene_size(scene, 24, 24)
    scene["level_profile"] = "tactical"
    scene["map_mode"] = "topdown"

    _ensure_scroll(scene).update({
        "scroll_x": True, "scroll_y": True,
        "forced": False, "speed_x": 0, "speed_y": 0,
        "loop_x": False, "loop_y": False,
    })
    _ensure_layout(scene).update({
        "cam_mode": "follow", "bounds_auto": True, "clamp": True,
        "follow_deadzone_x": 8, "follow_deadzone_y": 8, "follow_drop_margin_y": 8,
    })
    _apply_rule_defaults(
        scene,
        hud_enabled=False,
        hud_show_hp=False,
        hud_show_score=False,
        hud_show_collect=False,
        hud_show_timer=False,
        hud_show_lives=False,
        hud_pos="top",
        hud_font_mode="system",
        start_lives=0,
        start_continues=0,
        continue_restore_lives=0,
        goal_collectibles=0,
        time_limit_sec=0,
    )
    layers = _ensure_layers(scene)
    _set_layer_defaults(layers)

    victory_zone = None
    if _regions_empty(scene):
        w = _map_w(scene, 24)
        h = _map_h(scene, 24)
        victory_zone = _reg("victory_zone", "exit_goal", 10, 10, 4, 4)
        scene["regions"] = [
            _reg("team_a_spawn", "spawn",    2,            10, 3, 4),
            _reg("team_b_spawn", "spawn",    max(0, w - 5), 10, 3, 4),
            _reg("objective",    "zone",     10, 10, 4, 4),
            victory_zone,
        ]
    else:
        victory_zone = next(
            (
                reg for reg in (scene.get("regions") or [])
                if isinstance(reg, dict) and str(reg.get("kind") or "") == "exit_goal"
            ),
            None,
        )
    if _triggers_empty(scene) and isinstance(victory_zone, dict):
        scene["triggers"] = [
            _trig(
                "objective_complete",
                "enter_region",
                "end_game",
                region_id=str(victory_zone.get("id") or ""),
                once=True,
            )
        ]
    return True


# ---------------------------------------------------------------------------
# 12 — Intro skipable (A or B = skip to next scene)
# ---------------------------------------------------------------------------

def _apply_intro_skipable(scene: dict) -> bool:
    _ensure_scene_size(scene, 20, 19)
    scene["level_profile"] = "visual_novel"
    scene["map_mode"] = "none"

    _ensure_scroll(scene).update({
        "scroll_x": False, "scroll_y": False,
        "forced": False, "speed_x": 0, "speed_y": 0,
        "loop_x": False, "loop_y": False,
    })
    _ensure_layout(scene).update({
        "cam_mode": "single_screen", "bounds_auto": True, "clamp": True,
        "follow_deadzone_x": 16, "follow_deadzone_y": 12, "follow_drop_margin_y": 20,
    })
    _apply_rule_defaults(
        scene,
        hud_enabled=False,
        hud_show_hp=False,
        hud_show_score=False,
        hud_show_collect=False,
        hud_show_timer=False,
        hud_show_lives=False,
        hud_pos="top",
        hud_font_mode="custom",
        start_lives=0,
        start_continues=0,
        continue_restore_lives=0,
        goal_collectibles=0,
        time_limit_sec=0,
    )
    layers = _ensure_layers(scene)
    _set_layer_defaults(layers)

    if _triggers_empty(scene):
        scene["triggers"] = [
            _trig("skip_a", "btn_a", "goto_scene", once=True),
            _trig("skip_b", "btn_b", "goto_scene", once=True),
        ]
    return True


# ---------------------------------------------------------------------------
# 13 — Single-screen menu / visual novel
# ---------------------------------------------------------------------------

def _apply_menu_single(scene: dict) -> bool:
    _ensure_scene_size(scene, 20, 19)
    scene["level_profile"] = "menu"
    scene["map_mode"] = "none"

    _ensure_scroll(scene).update({
        "scroll_x": False, "scroll_y": False,
        "forced": False, "speed_x": 0, "speed_y": 0,
        "loop_x": False, "loop_y": False,
    })
    _ensure_layout(scene).update({
        "cam_mode": "single_screen", "bounds_auto": True, "clamp": True,
        "follow_deadzone_x": 0, "follow_deadzone_y": 0, "follow_drop_margin_y": 0,
    })
    rules = _apply_rule_defaults(
        scene,
        hud_enabled=False,
        hud_show_hp=False,
        hud_show_score=False,
        hud_show_collect=False,
        hud_show_timer=False,
        hud_show_lives=False,
        hud_pos="top",
        hud_font_mode="custom",
        start_lives=0,
        start_continues=0,
        continue_restore_lives=0,
        goal_collectibles=0,
        time_limit_sec=0,
    )
    rules["hud_fixed_plane"] = str(rules.get("hud_fixed_plane", "none") or "none")
    layers = _ensure_layers(scene)
    _set_layer_defaults(layers)

    if _triggers_empty(scene):
        # Starter triggers for a 2-item sprite cursor menu.
        # flag 0 = selected item index (0=item1, 1=item2).
        # Replace entity_target_id with the name of your cursor entity.
        # Add show_entity / hide_entity triggers for the cursor sprites.
        scene["triggers"] = [
            # Navigate DOWN: move cursor from item1 to item2
            _trig("nav_down",      "btn_down",  "set_flag",
                  flag_var_index=0, once=False,
                  extra_conds=[{"cond": "flag_clear", "flag_var_index": 0, "value": 0}]),
            # Navigate UP: move cursor back to item1
            _trig("nav_up",        "btn_up",    "clear_flag",
                  flag_var_index=0, once=False,
                  extra_conds=[{"cond": "flag_set", "flag_var_index": 0, "value": 0}]),
            # Confirm item1 (flag=0) — set scene_to
            _trig("confirm_item1", "btn_a",     "goto_scene",
                  once=False,
                  extra_conds=[{"cond": "flag_clear", "flag_var_index": 0, "value": 0}]),
            # Confirm item2 (flag=1) — set scene_to
            _trig("confirm_item2", "btn_a",     "goto_scene",
                  once=False,
                  extra_conds=[{"cond": "flag_set",   "flag_var_index": 0, "value": 0}]),
            # Menu enter SFX
            _trig("scene_sfx",     "scene_first_enter", "play_sfx", once=True),
        ]
    return True


# ---------------------------------------------------------------------------
# 14 — Roguelite room (20×19 → 32×32, no streaming)
# ---------------------------------------------------------------------------

def _apply_roguelite_room(scene: dict) -> bool:
    """Apply a roguelite room-by-room preset.

    Default 20×19 (single-screen, no scroll).  Users can resize the room
    up to 32×32 via Layout → Room size — the camera then follows the player
    within the room bounds.  No map streaming needed: the hardware BG
    tilemap is 32×32 tiles and fits entirely in VRAM.
    """
    _ensure_scene_size(scene, 20, 19)
    scene["level_profile"] = "roguelite_room"
    scene["map_mode"] = "topdown"

    _ensure_scroll(scene).update({
        "scroll_x": False, "scroll_y": False,
        "forced": False, "speed_x": 0, "speed_y": 0,
        "loop_x": False, "loop_y": False,
    })
    _ensure_layout(scene).update({
        "cam_mode": "single_screen", "bounds_auto": True, "clamp": True,
        "follow_deadzone_x": 12, "follow_deadzone_y": 10, "follow_drop_margin_y": 0,
    })
    rules = _apply_rule_defaults(
        scene,
        hud_enabled=True,
        hud_show_hp=True,
        hud_show_score=True,
        hud_show_collect=True,
        hud_show_timer=False,
        hud_show_lives=True,
        hud_pos="top",
        hud_font_mode="system",
        start_lives=3,
        start_continues=2,
        goal_collectibles=0,
        time_limit_sec=0,
    )
    rules["start_lives"]     = max(0, int(rules.get("start_lives",     3) or 3))
    rules["start_continues"] = max(0, int(rules.get("start_continues", 2) or 2))
    layers = _ensure_layers(scene)
    _set_layer_defaults(layers)

    if _regions_empty(scene):
        scene["regions"] = [
            _reg("player_spawn", "spawn",     8, 8, 3, 3),
            _reg("room_exit",    "exit_goal", 14, 14, 3, 3),
        ]
    if _triggers_empty(scene):
        scene["triggers"] = [
            _trig("room_cleared", "entity_type_all_dead", "play_sfx", once=True),
            _trig("exit_reached", "enter_region",         "goto_scene", once=True,
                  extra_conds=[{"cond": "entity_type_all_dead", "value": 0}]),
            _trig("death_respawn", "on_death",            "respawn_player", once=False),
        ]
    return True
