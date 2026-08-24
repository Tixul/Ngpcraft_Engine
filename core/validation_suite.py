"""Generate a reusable validation suite of small NGPC projects.

Goal (QA-1):
- create a small battery of end-to-end projects that exercise the tool as a
  production workflow, not only feature by feature.
- rely on the real scaffold/template path so each validation case is buildable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw

from core.project_scaffold import (
    ScaffoldParams,
    derive_cart_title,
    sanitize_rom_name,
    scaffold_project,
)


DEFAULT_EXPORT_DIR = r"GraphX\gen"


@dataclass(frozen=True)
class ValidationProjectSpec:
    """Metadata for one generated validation project."""

    key: str
    folder_name: str
    project_name: str
    template_id: str
    description: str


VALIDATION_PROJECTS: tuple[ValidationProjectSpec, ...] = (
    ValidationProjectSpec(
        key="sprite_lab",
        folder_name="validation_sprite_lab",
        project_name="Validation Sprite Lab",
        template_id="blank",
        description="Asset-heavy project focused on sprite export, hitboxes, anim states, HUD widgets and loader generation.",
    ),
    # NOTE: template_id must be a real id from core.project_templates
    # (only "blank" exists today). normalize_project_template() silently falls
    # back to "blank" for anything else, which is how these two cases spent
    # months scaffolding EMPTY projects — no scene, "(no scenes to export)",
    # build never attempted. The content now comes from the _patch_* functions
    # below, exactly like sprite_lab and mini_topdown.
    ValidationProjectSpec(
        key="mini_shmup",
        folder_name="validation_mini_shmup",
        project_name="Validation Mini Shmup",
        template_id="blank",
        description="Vertical scrolling shooter: forced scroll, timed waves, player shooting, enemy HP/score, death FX and HUD.",
    ),
    ValidationProjectSpec(
        key="mini_platformer",
        folder_name="validation_mini_platformer",
        project_name="Validation Mini Platformer",
        template_id="blank",
        description="Platformer case covering gravity/jump, solid + one-way tiles, spring, ladder, hazard, void pit, enemies, checkpoint and goal.",
    ),
    ValidationProjectSpec(
        key="mini_topdown",
        folder_name="validation_mini_topdown",
        project_name="Validation Mini TopDown",
        template_id="blank",
        description="Top-down room with NPC/item interactions, door/checkpoint regions and trigger-driven flow.",
    ),
)


def _project_data_base(*, project_name: str, rom_name: str) -> dict:
    return {
        "version": 1,
        "name": project_name,
        "project_name": project_name,
        "rom_name": rom_name,
        "graphx_dir": "GraphX",
        "bundle": {"tile_base": 256, "pal_base": 0, "entries": []},
        "scenes": [],
    }


def _set_scene_dimensions(scene: dict, *, width: int, height: int) -> None:
    scene["level_size"] = {"w": int(width), "h": int(height)}
    scene["map_w"] = int(width)
    scene["map_h"] = int(height)
    scene["grid_w"] = int(width)
    scene["grid_h"] = int(height)


def _write_project_ngpng(project_root: Path, data: dict) -> Path:
    out = project_root / "project.ngpcraft"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def _make_sprite_sheet(path: Path, frame_w: int, frame_h: int, colors: list[tuple[int, int, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (frame_w * len(colors), frame_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for idx, color in enumerate(colors):
        ox = idx * frame_w
        draw.rounded_rectangle((ox + 1, 1, ox + frame_w - 2, frame_h - 2), radius=max(1, min(frame_w, frame_h) // 5), fill=color)
        draw.rectangle((ox + 2, 2, ox + frame_w - 3, frame_h - 3), outline=(255, 255, 255, 160))
        draw.rectangle((ox + frame_w // 3, frame_h // 3, ox + frame_w // 3 + 1, frame_h // 3 + 1), fill=(0, 0, 0, 180))
    img.save(path)


def _make_topdown_bg(path: Path, map_w: int = 20, map_h: int = 19) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (map_w * 8, map_h * 8), (32, 72, 48, 255))
    draw = ImageDraw.Draw(img)
    for ty in range(map_h):
        for tx in range(map_w):
            x0 = tx * 8
            y0 = ty * 8
            base = (44, 96, 60, 255) if (tx + ty) % 2 == 0 else (38, 82, 54, 255)
            draw.rectangle((x0, y0, x0 + 7, y0 + 7), fill=base)
    for tx in range(map_w):
        draw.rectangle((tx * 8, 0, tx * 8 + 7, 7), fill=(86, 58, 36, 255))
        draw.rectangle((tx * 8, (map_h - 1) * 8, tx * 8 + 7, map_h * 8 - 1), fill=(86, 58, 36, 255))
    for ty in range(map_h):
        draw.rectangle((0, ty * 8, 7, ty * 8 + 7), fill=(86, 58, 36, 255))
        draw.rectangle(((map_w - 1) * 8, ty * 8, map_w * 8 - 1, ty * 8 + 7), fill=(86, 58, 36, 255))
    for tx in range(7, 13):
        draw.rectangle((tx * 8, 8 * 8, tx * 8 + 7, 8 * 8 + 7), fill=(96, 44, 44, 255))
    img.save(path)


def _make_sprite_lab_bg(path: Path, map_w: int = 20, map_h: int = 19) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (map_w * 8, map_h * 8), (22, 30, 48, 255))
    draw = ImageDraw.Draw(img)
    for ty in range(map_h):
        for tx in range(map_w):
            x0 = tx * 8
            y0 = ty * 8
            if tx in (0, map_w - 1) or ty in (0, map_h - 1):
                fill = (72, 78, 92, 255)
            elif ty % 4 == 0:
                fill = (28, 40, 62, 255)
            else:
                fill = (24, 34, 54, 255)
            draw.rectangle((x0, y0, x0 + 7, y0 + 7), fill=fill)
    img.save(path)


# ---------------------------------------------------------------------------
# Collision codes used by the generated col_map. Mirrors the runtime table
# read in template_integration.py (_tile_values): 1 solid, 2 one-way, 3 damage,
# 4 ladder, 11 void, 15 spring.
# ---------------------------------------------------------------------------
TCOL_PASS, TCOL_SOLID, TCOL_ONE_WAY, TCOL_DAMAGE = 0, 1, 2, 3
TCOL_LADDER, TCOL_VOID, TCOL_SPRING = 4, 11, 15


def _make_shmup_bg(path: Path, map_w: int, map_h: int) -> None:
    """Star field with lane markers — tall enough to scroll and loop."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (map_w * 8, map_h * 8), (10, 12, 30, 255))
    draw = ImageDraw.Draw(img)
    for ty in range(map_h):
        for tx in range(map_w):
            x0, y0 = tx * 8, ty * 8
            if tx in (0, map_w - 1):
                fill = (40, 48, 84, 255)          # side rails
            elif (tx * 5 + ty * 3) % 17 == 0:
                fill = (18, 22, 46, 255)          # nebula speckle
            else:
                fill = (10, 12, 30, 255)
            draw.rectangle((x0, y0, x0 + 7, y0 + 7), fill=fill)
            if (tx * 7 + ty * 11) % 23 == 0:      # star
                draw.rectangle((x0 + 3, y0 + 3, x0 + 4, y0 + 4), fill=(196, 208, 255, 255))
    for ty in range(0, map_h, 6):                 # horizontal lane markers
        draw.rectangle((8, ty * 8 + 3, (map_w - 1) * 8 - 1, ty * 8 + 4), fill=(28, 34, 66, 255))
    img.save(path)


def _make_platformer_bg(path: Path, col_map: list[list[int]]) -> None:
    """Draw the background straight FROM the collision map.

    Keeping both from one source is deliberate: a validation case where the
    picture and the collision disagree tests nothing useful, and any future
    edit to col_map stays visible on screen.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    map_h, map_w = len(col_map), len(col_map[0])
    palette = {
        TCOL_PASS:    (26, 34, 58, 255),
        TCOL_SOLID:   (92, 78, 58, 255),
        TCOL_ONE_WAY: (140, 116, 72, 255),
        TCOL_DAMAGE:  (168, 52, 48, 255),
        TCOL_LADDER:  (150, 126, 70, 255),
        TCOL_VOID:    (8, 8, 14, 255),
        TCOL_SPRING:  (60, 172, 120, 255),
    }
    img = Image.new("RGBA", (map_w * 8, map_h * 8), (26, 34, 58, 255))
    draw = ImageDraw.Draw(img)
    for ty in range(map_h):
        for tx in range(map_w):
            code = col_map[ty][tx]
            x0, y0 = tx * 8, ty * 8
            draw.rectangle((x0, y0, x0 + 7, y0 + 7), fill=palette.get(code, (26, 34, 58, 255)))
            if code == TCOL_SOLID:
                draw.rectangle((x0, y0, x0 + 7, y0), fill=(126, 108, 80, 255))
            elif code == TCOL_ONE_WAY:
                draw.rectangle((x0, y0, x0 + 7, y0 + 1), fill=(200, 176, 120, 255))
            elif code == TCOL_LADDER:
                draw.rectangle((x0 + 2, y0, x0 + 2, y0 + 7), fill=(214, 190, 120, 255))
                draw.rectangle((x0 + 5, y0, x0 + 5, y0 + 7), fill=(214, 190, 120, 255))
            elif code == TCOL_SPRING:
                draw.rectangle((x0 + 1, y0 + 4, x0 + 6, y0 + 7), fill=(120, 236, 176, 255))
    img.save(path)


def _shmup_project_data() -> dict:
    """Vertical forced-scroll shooter.

    Covers: shmup level profile, forced+looping vertical scroll, timed waves,
    player shooting (bullet sprite resolved by name), enemy HP/score/death FX,
    and the score HUD.
    """
    map_w, map_h = 20, 38  # two screens tall, looping
    scene = {
        "id": "shmup_stage_1",
        "label": "stage_1",
        "spr_tile_base": 256,
        "sprites": [
            {
                "name": "ship_player",
                "file": r"GraphX\ship_player_sheet.png",
                "frame_w": 16, "frame_h": 16, "frame_count": 2,
                "anim_duration": 8,
                "hitboxes": [{"x": 4, "y": 4, "w": 8, "h": 8}],
                "props": {"hp": 3, "damage": 1, "max_speed": 3, "accel": 8,
                          "move_type": 1, "gravity": 0, "axis_x": 1, "axis_y": 1,
                          "shoot_cooldown": 8, "inv_frames": 40, "type_id": 0},
                "ctrl": {"role": "player", "left": "PAD_LEFT", "right": "PAD_RIGHT",
                         "up": "PAD_UP", "down": "PAD_DOWN", "action": "PAD_A"},
                # vy negative = the shot travels up the screen
                "shooting": {"button": "A", "bullet_sprite": "shot_player",
                             "speed_x": 0, "speed_y": -6, "fire_rate": 8, "fire_range": 0},
            },
            {
                "name": "shot_player",
                "file": r"GraphX\shot_player_sheet.png",
                "frame_w": 8, "frame_h": 8, "frame_count": 2,
                "anim_duration": 4,
                "hitboxes": [{"x": 2, "y": 0, "w": 4, "h": 8}],
                "props": {"damage": 1, "max_speed": 6, "move_type": 1},
                "ctrl": {"role": "prop"},
            },
            {
                "name": "drone_enemy",
                "file": r"GraphX\drone_enemy_sheet.png",
                "frame_w": 16, "frame_h": 16, "frame_count": 2,
                "anim_duration": 6,
                "hitboxes": [{"x": 2, "y": 2, "w": 12, "h": 12}],
                "props": {"hp": 1, "damage": 1, "max_speed": 2, "move_type": 1,
                          "score": 10, "gravity": 0, "type_id": 1},
                "ctrl": {"role": "enemy"},
            },
            {
                "name": "turret_enemy",
                "file": r"GraphX\turret_enemy_sheet.png",
                "frame_w": 16, "frame_h": 16, "frame_count": 2,
                "anim_duration": 10,
                "hitboxes": [{"x": 2, "y": 2, "w": 12, "h": 12}],
                "props": {"hp": 3, "damage": 1, "max_speed": 1, "move_type": 1,
                          "score": 50, "gravity": 0, "type_id": 2},
                "ctrl": {"role": "enemy"},
            },
        ],
        "tilemaps": [{"name": "star_bg", "file": r"GraphX\star_bg.png", "plane": "scr2"}],
        "entities": [
            {"id": "ent_ship", "type": "ship_player", "x": 9, "y": 15, "data": 0, "flags": 1, "role": "player"},
            {"id": "ent_drone_a", "type": "drone_enemy", "x": 5, "y": 3, "data": 0},
            {"id": "ent_drone_b", "type": "drone_enemy", "x": 13, "y": 3, "data": 0},
        ],
        # delay = frames since scene start
        "waves": [
            {"delay": 120, "entities": [
                {"type": "drone_enemy", "x": 4, "y": 1, "data": 0},
                {"type": "drone_enemy", "x": 9, "y": 1, "data": 0},
                {"type": "drone_enemy", "x": 14, "y": 1, "data": 0},
            ]},
            {"delay": 300, "entities": [
                {"type": "drone_enemy", "x": 2, "y": 1, "data": 0},
                {"type": "drone_enemy", "x": 6, "y": 1, "data": 0},
                {"type": "drone_enemy", "x": 12, "y": 1, "data": 0},
                {"type": "drone_enemy", "x": 16, "y": 1, "data": 0},
            ]},
            {"delay": 540, "entities": [
                {"type": "turret_enemy", "x": 7, "y": 1, "data": 0},
                {"type": "turret_enemy", "x": 11, "y": 1, "data": 0},
            ]},
        ],
        "regions": [],
        "triggers": [
            {"id": "trig_score_gate", "name": "score_gate", "cond": "score_ge", "region_id": "",
             "value": 100, "action": "add_score", "a0": 25, "a1": 0, "once": True},
        ],
        "paths": [],
        "entity_roles": {"ship_player": "player", "drone_enemy": "enemy",
                         "turret_enemy": "enemy", "shot_player": "prop"},
        "level_profile": "shmup",
        "level_bg_scr2": r"GraphX\star_bg.png",
        "level_bg_front": "scr2",
        "level_cam_tile": {"x": 0, "y": 0},
        "level_scroll": {"scroll_x": False, "scroll_y": True, "forced": True,
                         "speed_x": 0, "speed_y": 1, "loop_x": False, "loop_y": True},
        "level_layout": {"cam_mode": "forced_scroll", "bounds_auto": True, "clamp": True,
                         "min_x": 0, "min_y": 0, "max_x": 0, "max_y": 19,
                         "follow_deadzone_x": 16, "follow_deadzone_y": 12,
                         "follow_drop_margin_y": 20, "cam_lag": 0},
        "level_layers": {"scr1_parallax_x": 100, "scr1_parallax_y": 100,
                         "scr2_parallax_x": 100, "scr2_parallax_y": 100},
        "level_rules": {
            "hud_enabled": True, "hud_show_hp": True, "hud_show_score": True,
            "hud_show_collect": False, "hud_show_timer": False, "hud_show_lives": True,
            "hud_pos": "top", "hud_font_mode": "system",
            "hud_digits_hp": 1, "hud_digits_score": 5, "hud_digits_lives": 1,
            "start_lives": 3, "hazard_damage": 1, "hazard_invul": 40,
        },
        "map_mode": "shmup",
        "col_map": [[TCOL_PASS for _x in range(map_w)] for _y in range(map_h)],
    }
    _set_scene_dimensions(scene, width=map_w, height=map_h)
    data = _project_data_base(project_name="Validation Mini Shmup", rom_name="validation_mini_shmup")
    data["export_dir"] = DEFAULT_EXPORT_DIR
    data["game"] = {"start_scene": scene["label"]}
    data["scenes"] = [scene]
    data["mechanics"] = {
        "shooting": True, "hit_feedback": True, "death_fx": True, "scoring": True,
        "wave_spawning": True, "wave_scroll_spawn": True, "damage_popup": True,
        "game_over_flow": True,
    }
    return data


def _platformer_col_map(map_w: int, map_h: int) -> list[list[int]]:
    """Ground, a pit, a one-way ledge, a ladder, a spring and a spike strip."""
    col = [[TCOL_PASS for _x in range(map_w)] for _y in range(map_h)]
    floor_y = map_h - 3
    for tx in range(map_w):
        for ty in range(floor_y, map_h):
            col[ty][tx] = TCOL_SOLID
    # side walls so the player cannot leave the level
    for ty in range(map_h):
        col[ty][0] = TCOL_SOLID
        col[ty][map_w - 1] = TCOL_SOLID
    # a pit with void at the bottom (kills / respawns)
    for tx in range(14, 18):
        for ty in range(floor_y, map_h):
            col[ty][tx] = TCOL_PASS
        col[map_h - 1][tx] = TCOL_VOID
    # one-way ledge you can jump through from below
    for tx in range(6, 11):
        col[floor_y - 4][tx] = TCOL_ONE_WAY
    # ladder from the floor up to a second one-way ledge
    for ty in range(floor_y - 8, floor_y):
        col[ty][22] = TCOL_LADDER
    for tx in range(20, 26):
        col[floor_y - 8][tx] = TCOL_ONE_WAY
    # spring pad on the ground
    col[floor_y - 1][30] = TCOL_SPRING
    # spike strip
    for tx in range(33, 36):
        col[floor_y - 1][tx] = TCOL_DAMAGE
    return col


def _platformer_project_data() -> dict:
    """Side-view platformer.

    Covers: platformer profile + follow camera, gravity/jump physics, solid and
    one-way tiles, ladder, spring, damage tile, void pit, a walking enemy,
    collectibles, a checkpoint region and an exit goal.
    """
    map_w, map_h = 40, 19
    col_map = _platformer_col_map(map_w, map_h)
    floor_y = map_h - 3
    scene = {
        "id": "platformer_stage_1",
        "label": "stage_1",
        "spr_tile_base": 256,
        "sprites": [
            {
                "name": "hero_side",
                "file": r"GraphX\hero_side_sheet.png",
                "frame_w": 16, "frame_h": 16, "frame_count": 4,
                "anim_duration": 6,
                "hitboxes": [{"x": 3, "y": 2, "w": 10, "h": 14}],
                "anims": {
                    "idle": {"start": 0, "count": 1, "spd": 12, "loop": 0},
                    "run": {"start": 0, "count": 4, "spd": 5, "loop": 0},
                },
                "props": {"hp": 5, "damage": 1, "max_speed": 4, "accel": 8, "weight": 100,
                          "jump_force": 9, "gravity": 2, "max_fall_speed": 20,
                          "move_type": 2, "can_jump": 1, "gravity_dir": 0,
                          "inv_frames": 30, "type_id": 0, "flip_x_dir": 1},
                "ctrl": {"role": "player", "left": "PAD_LEFT", "right": "PAD_RIGHT",
                         "up": "PAD_UP", "down": "PAD_DOWN", "jump": "PAD_A", "action": "PAD_B"},
            },
            {
                "name": "walker_enemy",
                "file": r"GraphX\walker_enemy_sheet.png",
                "frame_w": 16, "frame_h": 16, "frame_count": 2,
                "anim_duration": 8,
                "hitboxes": [{"x": 2, "y": 2, "w": 12, "h": 14}],
                "props": {"hp": 1, "damage": 1, "max_speed": 1, "weight": 128,
                          "gravity": 4, "move_type": 2, "can_jump": 0, "gravity_dir": 0,
                          "score": 20, "type_id": 1},
                "ctrl": {"role": "enemy"},
            },
            {
                "name": "gem_item",
                "file": r"GraphX\gem_item_sheet.png",
                "frame_w": 8, "frame_h": 8, "frame_count": 2,
                "anim_duration": 10,
                "hitboxes": [{"x": 0, "y": 0, "w": 8, "h": 8}],
                "props": {"score": 25},
                "ctrl": {"role": "item"},
            },
        ],
        "tilemaps": [{"name": "side_bg", "file": r"GraphX\side_bg.png", "plane": "scr2"}],
        "entities": [
            {"id": "ent_hero_side", "type": "hero_side", "x": 2, "y": floor_y - 1, "data": 0, "flags": 1, "role": "player"},
            {"id": "ent_walker_a", "type": "walker_enemy", "x": 11, "y": floor_y - 1, "data": 0},
            {"id": "ent_walker_b", "type": "walker_enemy", "x": 27, "y": floor_y - 1, "data": 0},
            {"id": "ent_gem_a", "type": "gem_item", "x": 8, "y": floor_y - 5, "data": 0},
            {"id": "ent_gem_b", "type": "gem_item", "x": 22, "y": floor_y - 9, "data": 0},
            {"id": "ent_gem_c", "type": "gem_item", "x": 31, "y": floor_y - 6, "data": 0},
        ],
        "waves": [],
        "regions": [
            {"id": "reg_checkpoint", "name": "checkpoint", "x": 12, "y": floor_y - 3, "w": 2, "h": 3, "kind": "checkpoint"},
            {"id": "reg_goal", "name": "stage_exit", "x": 37, "y": floor_y - 3, "w": 2, "h": 3, "kind": "exit_goal"},
        ],
        "triggers": [
            {"id": "trig_all_gems", "name": "all_gems", "cond": "collectible_count_ge", "region_id": "",
             "value": 3, "action": "add_score", "a0": 100, "a1": 0, "once": True},
            {"id": "trig_checkpoint", "name": "checkpoint_bonus", "cond": "enter_region",
             "region_id": "reg_checkpoint", "value": 0, "action": "add_score", "a0": 10, "a1": 0, "once": True},
        ],
        "paths": [],
        "entity_roles": {"hero_side": "player", "walker_enemy": "enemy", "gem_item": "item"},
        "level_profile": "platformer",
        "level_bg_scr2": r"GraphX\side_bg.png",
        "level_bg_front": "scr2",
        "level_cam_tile": {"x": 0, "y": 0},
        "level_scroll": {"scroll_x": True, "scroll_y": False, "forced": False,
                         "speed_x": 0, "speed_y": 0, "loop_x": False, "loop_y": False},
        "level_layout": {"cam_mode": "follow", "bounds_auto": True, "clamp": True,
                         "min_x": 0, "min_y": 0, "max_x": map_w - 20, "max_y": 0,
                         "follow_deadzone_x": 16, "follow_deadzone_y": 12,
                         "follow_drop_margin_y": 20, "cam_lag": 0},
        "level_layers": {"scr1_parallax_x": 100, "scr1_parallax_y": 100,
                         "scr2_parallax_x": 100, "scr2_parallax_y": 100},
        "level_rules": {
            "hud_enabled": True, "hud_show_hp": True, "hud_show_score": True,
            "hud_show_collect": True, "hud_show_timer": False, "hud_show_lives": True,
            "hud_pos": "top", "hud_font_mode": "system",
            "hud_digits_hp": 1, "hud_digits_score": 5, "hud_digits_collect": 1, "hud_digits_lives": 1,
            "start_lives": 3, "goal_collectibles": 3,
            "hazard_damage": 1, "hazard_invul": 30,
            "void_damage": 255, "void_instant": True,
            "spring_force": 15, "spring_dir": "up",
            "ladder_top_solid": False, "ladder_top_exit": True, "ladder_side_move": False,
        },
        "map_mode": "platformer",
        "col_map": col_map,
    }
    _set_scene_dimensions(scene, width=map_w, height=map_h)
    data = _project_data_base(project_name="Validation Mini Platformer", rom_name="validation_mini_platformer")
    data["export_dir"] = DEFAULT_EXPORT_DIR
    data["game"] = {"start_scene": scene["label"]}
    data["scenes"] = [scene]
    data["mechanics"] = {
        "platformer_physics": True, "hit_feedback": True, "death_fx": True,
        "scoring": True, "damage_popup": True, "game_over_flow": True,
        "fade_transitions": True,
    }
    return data


def _sprite_lab_project_data() -> dict:
    map_w, map_h = 20, 19
    scene = {
        "id": "sprite_lab_main",
        "label": "sprite_lab",
        "spr_tile_base": 256,
        "sprites": [
            {
                "name": "hero_lab",
                "file": r"GraphX\hero_lab_sheet.png",
                "frame_w": 16, "frame_h": 16, "frame_count": 4,
                "anim_duration": 6,
                "hitboxes": [{"x": 2, "y": 2, "w": 12, "h": 12}],
                "anims": {
                    "idle": {"start": 0, "count": 1, "spd": 12, "loop": 0},
                    "run": {"start": 0, "count": 4, "spd": 5, "loop": 0},
                },
                "props": {"hp": 4, "damage": 1, "max_speed": 2, "gravity": 0, "move_type": 0, "axis_x": 1, "axis_y": 1},
                "ctrl": {"role": "player", "left": "PAD_LEFT", "right": "PAD_RIGHT", "up": "PAD_UP", "down": "PAD_DOWN", "action": "PAD_A"},
            },
            {
                "name": "enemy_lab",
                "file": r"GraphX\enemy_lab_sheet.png",
                "frame_w": 16, "frame_h": 16, "frame_count": 2,
                "anim_duration": 8,
                "hitboxes": [{"x": 1, "y": 1, "w": 14, "h": 14}],
                "props": {"hp": 2, "damage": 1, "score": 10, "gravity": 0},
                "ctrl": {"role": "enemy"},
            },
            {
                "name": "pickup_lab",
                "file": r"GraphX\pickup_lab_sheet.png",
                "frame_w": 8, "frame_h": 8, "frame_count": 2,
                "anim_duration": 10,
                "hitboxes": [{"x": 0, "y": 0, "w": 8, "h": 8}],
                "props": {"score": 25},
                "ctrl": {"role": "item"},
            },
        ],
        "tilemaps": [{"name": "lab_bg", "file": r"GraphX\lab_bg.png", "plane": "scr2"}],
        "entities": [
            {"id": "ent_player_lab", "type": "hero_lab", "x": 4, "y": 9, "data": 0},
            {"id": "ent_enemy_lab", "type": "enemy_lab", "x": 11, "y": 8, "data": 0},
            {"id": "ent_pickup_lab", "type": "pickup_lab", "x": 15, "y": 10, "data": 0},
        ],
        "waves": [],
        "regions": [{"id": "reg_right", "name": "right_gate", "x": 16, "y": 0, "w": 4, "h": map_h, "kind": "zone"}],
        "triggers": [
            {"id": "trig_goal", "name": "goal_collect", "cond": "collectible_count_ge", "region_id": "", "value": 1, "action": "add_score", "a0": 50, "a1": 0, "once": True},
        ],
        "paths": [],
        "entity_roles": {"hero_lab": "player", "enemy_lab": "enemy", "pickup_lab": "item"},
        "level_profile": "topdown_rpg",
        "level_bg_scr2": r"GraphX\lab_bg.png",
        "level_bg_front": "scr2",
        "level_cam_tile": {"x": 0, "y": 0},
        "level_scroll": {"scroll_x": False, "scroll_y": False, "forced": False, "speed_x": 0, "speed_y": 0, "loop_x": False, "loop_y": False},
        "level_layout": {"cam_mode": "single_screen", "bounds_auto": True, "clamp": True, "min_x": 0, "min_y": 0, "max_x": 0, "max_y": 0},
        "level_layers": {"scr1_parallax_x": 100, "scr1_parallax_y": 100, "scr2_parallax_x": 100, "scr2_parallax_y": 100},
        "level_rules": {
            "hud_show_score": True, "hud_show_collect": True, "hud_show_timer": False, "hud_show_lives": False,
            "hud_pos": "top", "hud_font_mode": "system",
        },
        "map_mode": "open",
        "col_map": [[0 for _x in range(map_w)] for _y in range(map_h)],
    }
    _set_scene_dimensions(scene, width=map_w, height=map_h)
    data = _project_data_base(project_name="Validation Sprite Lab", rom_name="validation_sprite_lab")
    data["export_dir"] = DEFAULT_EXPORT_DIR
    data["game"] = {"start_scene": scene["label"]}
    data["scenes"] = [scene]
    return data


def _topdown_project_data() -> dict:
    map_w, map_h = 20, 19
    col_map = [[0 for _x in range(map_w)] for _y in range(map_h)]
    for tx in range(map_w):
        col_map[0][tx] = 1
        col_map[map_h - 1][tx] = 1
    for ty in range(map_h):
        col_map[ty][0] = 1
        col_map[ty][map_w - 1] = 1
    for tx in range(7, 13):
        col_map[8][tx] = 1
    col_map[8][9] = 12
    col_map[8][10] = 12

    scene = {
        "id": "topdown_room_1",
        "label": "room_1",
        "spr_tile_base": 256,
        "sprites": [
            {
                "name": "hero_top",
                "file": r"GraphX\hero_top_sheet.png",
                "frame_w": 16, "frame_h": 16, "frame_count": 3,
                "anim_duration": 6,
                "hitboxes": [{"x": 2, "y": 2, "w": 12, "h": 12}],
                "props": {"hp": 3, "damage": 0, "max_speed": 2, "axis_x": 1, "axis_y": 1, "move_type": 0},
                "ctrl": {"role": "player", "left": "PAD_LEFT", "right": "PAD_RIGHT", "up": "PAD_UP", "down": "PAD_DOWN", "action": "PAD_A"},
            },
            {
                "name": "npc_top",
                "file": r"GraphX\npc_top_sheet.png",
                "frame_w": 16, "frame_h": 16, "frame_count": 2,
                "anim_duration": 8,
                "hitboxes": [{"x": 2, "y": 2, "w": 12, "h": 12}],
                "props": {"hp": 1},
                "ctrl": {"role": "npc"},
            },
            {
                "name": "key_item",
                "file": r"GraphX\key_item_sheet.png",
                "frame_w": 8, "frame_h": 8, "frame_count": 2,
                "anim_duration": 10,
                "hitboxes": [{"x": 0, "y": 0, "w": 8, "h": 8}],
                "props": {"score": 1},
                "ctrl": {"role": "item"},
            },
        ],
        "tilemaps": [{"name": "top_bg", "file": r"GraphX\top_bg.png", "plane": "scr2"}],
        "entities": [
            {"id": "ent_player_top", "type": "hero_top", "x": 3, "y": 14, "data": 0},
            {"id": "ent_npc_top", "type": "npc_top", "x": 6, "y": 5, "data": 0},
            {"id": "ent_key_top", "type": "key_item", "x": 14, "y": 13, "data": 0},
        ],
        "waves": [],
        "regions": [
            {"id": "reg_npc", "name": "npc_zone", "x": 4, "y": 3, "w": 4, "h": 4, "kind": "zone"},
            {"id": "reg_door", "name": "door_zone", "x": 9, "y": 7, "w": 2, "h": 2, "kind": "exit_goal"},
            {"id": "reg_save", "name": "save_zone", "x": 1, "y": 13, "w": 3, "h": 3, "kind": "checkpoint"},
        ],
        "triggers": [
            {"id": "trig_npc", "name": "npc_hint", "cond": "enter_region", "region_id": "reg_npc", "value": 0, "action": "add_score", "a0": 5, "a1": 0, "once": True},
            {"id": "trig_key", "name": "key_bonus", "cond": "collectible_count_ge", "region_id": "", "value": 1, "action": "show_entity", "a0": 0, "a1": 0, "once": True},
        ],
        "paths": [],
        "entity_roles": {"hero_top": "player", "npc_top": "npc", "key_item": "item"},
        "level_profile": "topdown_rpg",
        "level_bg_scr2": r"GraphX\top_bg.png",
        "level_bg_front": "scr2",
        "level_cam_tile": {"x": 0, "y": 0},
        "level_scroll": {"scroll_x": False, "scroll_y": False, "forced": False, "speed_x": 0, "speed_y": 0, "loop_x": False, "loop_y": False},
        "level_layout": {"cam_mode": "single_screen", "bounds_auto": True, "clamp": True, "min_x": 0, "min_y": 0, "max_x": 0, "max_y": 0},
        "level_layers": {"scr1_parallax_x": 100, "scr1_parallax_y": 100, "scr2_parallax_x": 100, "scr2_parallax_y": 100},
        "level_rules": {"hud_show_score": True, "hud_show_collect": True, "hud_show_timer": False, "hud_show_lives": False, "hud_pos": "top", "hud_font_mode": "system"},
        "map_mode": "topdown",
        "col_map": col_map,
    }
    _set_scene_dimensions(scene, width=map_w, height=map_h)
    data = _project_data_base(project_name="Validation Mini TopDown", rom_name="validation_mini_topdown")
    data["export_dir"] = DEFAULT_EXPORT_DIR
    data["game"] = {"start_scene": scene["label"]}
    data["scenes"] = [scene]
    return data


def _patch_sprite_lab_project(project_root: Path) -> None:
    graphx = project_root / "GraphX"
    _make_sprite_sheet(graphx / "hero_lab_sheet.png", 16, 16, [(54, 114, 214), (72, 138, 232), (54, 114, 214), (90, 160, 250)])
    _make_sprite_sheet(graphx / "enemy_lab_sheet.png", 16, 16, [(180, 64, 64), (210, 90, 90)])
    _make_sprite_sheet(graphx / "pickup_lab_sheet.png", 8, 8, [(244, 220, 64), (255, 242, 94)])
    _make_sprite_lab_bg(graphx / "lab_bg.png")
    _write_project_ngpng(project_root, _sprite_lab_project_data())


def _patch_topdown_project(project_root: Path) -> None:
    graphx = project_root / "GraphX"
    _make_sprite_sheet(graphx / "hero_top_sheet.png", 16, 16, [(72, 136, 220), (90, 154, 238), (108, 172, 255)])
    _make_sprite_sheet(graphx / "npc_top_sheet.png", 16, 16, [(164, 112, 72), (182, 130, 90)])
    _make_sprite_sheet(graphx / "key_item_sheet.png", 8, 8, [(240, 208, 80), (255, 230, 112)])
    _make_topdown_bg(graphx / "top_bg.png")
    _write_project_ngpng(project_root, _topdown_project_data())


def _patch_shmup_project(project_root: Path) -> None:
    graphx = project_root / "GraphX"
    _make_sprite_sheet(graphx / "ship_player_sheet.png", 16, 16, [(88, 168, 248), (128, 196, 255)])
    _make_sprite_sheet(graphx / "shot_player_sheet.png", 8, 8, [(255, 236, 128), (255, 252, 200)])
    _make_sprite_sheet(graphx / "drone_enemy_sheet.png", 16, 16, [(204, 72, 72), (232, 104, 104)])
    _make_sprite_sheet(graphx / "turret_enemy_sheet.png", 16, 16, [(168, 96, 200), (196, 128, 228)])
    _make_shmup_bg(graphx / "star_bg.png", 20, 38)
    _write_project_ngpng(project_root, _shmup_project_data())


def _patch_platformer_project(project_root: Path) -> None:
    graphx = project_root / "GraphX"
    _make_sprite_sheet(graphx / "hero_side_sheet.png", 16, 16,
                       [(96, 200, 132), (120, 220, 152), (96, 200, 132), (140, 236, 176)])
    _make_sprite_sheet(graphx / "walker_enemy_sheet.png", 16, 16, [(196, 84, 64), (224, 112, 88)])
    _make_sprite_sheet(graphx / "gem_item_sheet.png", 8, 8, [(120, 216, 248), (168, 236, 255)])
    _make_platformer_bg(graphx / "side_bg.png", _platformer_col_map(40, 19))
    _write_project_ngpng(project_root, _platformer_project_data())


def _write_manifest(destination_root: Path, generated: list[tuple[ValidationProjectSpec, Path]]) -> Path:
    lines = [
        "# NGPC PNG Manager validation suite\n",
        "\n",
        "Generated projects:\n",
    ]
    for spec, path in generated:
        lines.append(f"- {spec.project_name}: `{path.name}`\n")
        lines.append(f"  - {spec.description}\n")
    out = destination_root / "VALIDATION_SUITE.md"
    out.write_text("".join(lines), encoding="utf-8")
    return out


def build_validation_suite(
    *,
    destination_root: Path,
    template_root: Path,
    log: Callable[[str], None] = print,
) -> list[Path]:
    """Create the 4 validation projects under `destination_root`."""

    destination_root = Path(destination_root)
    destination_root.mkdir(parents=True, exist_ok=True)
    generated: list[tuple[ValidationProjectSpec, Path]] = []

    for spec in VALIDATION_PROJECTS:
        project_dir = destination_root / spec.folder_name
        if project_dir.exists():
            raise RuntimeError(f"Validation project already exists: {project_dir}")
        rom_name = sanitize_rom_name(spec.folder_name)
        params = ScaffoldParams(
            destination=project_dir,
            project_name=spec.project_name,
            rom_name=rom_name,
            cart_title=derive_cart_title(spec.project_name),
            project_template=spec.template_id,
            enable_sound=True,
            enable_flash_save=True,
            enable_debug=True,
            enable_dma=True,
        )
        log(f"[QA-1] scaffold {spec.project_name}")
        scaffold_project(params, template_root)
        patcher = {
            "sprite_lab":      _patch_sprite_lab_project,
            "mini_shmup":      _patch_shmup_project,
            "mini_platformer": _patch_platformer_project,
            "mini_topdown":    _patch_topdown_project,
        }.get(spec.key)
        if patcher is None:
            # A spec with no content builder scaffolds an EMPTY project: the
            # export then logs "(no scenes to export)" and the build is never
            # attempted, while the run still reports export_exit_code 0. Fail
            # loudly instead of shipping a case that validates nothing.
            raise RuntimeError(
                f"validation spec {spec.key!r} has no project content builder"
            )
        patcher(project_dir)
        generated.append((spec, project_dir))

    manifest = _write_manifest(destination_root, generated)
    log(f"[QA-1] manifest: {manifest}")
    return [path for _spec, path in generated]
