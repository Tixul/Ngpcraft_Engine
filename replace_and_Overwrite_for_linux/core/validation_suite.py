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


DEFAULT_EXPORT_DIR = "GraphX/gen"


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
    ValidationProjectSpec(
        key="mini_shmup",
        folder_name="validation_mini_shmup",
        project_name="Validation Mini Shmup",
        template_id="shmup_example",
        description="Scrolling shooter using waves, paths, parallax, SFX/BGM and template-ready scene export.",
    ),
    ValidationProjectSpec(
        key="mini_platformer",
        folder_name="validation_mini_platformer",
        project_name="Validation Mini Platformer",
        template_id="platformer_example",
        description="Platformer case covering collision, slopes, moving platforms, enemies, checkpoints and HUD.",
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
        if spec.key == "sprite_lab":
            _patch_sprite_lab_project(project_dir)
        elif spec.key == "mini_topdown":
            _patch_topdown_project(project_dir)
        generated.append((spec, project_dir))

    manifest = _write_manifest(destination_root, generated)
    log(f"[QA-1] manifest: {manifest}")
    return [path for _spec, path in generated]
