"""
core/battle_anchors.py — Static layout constants for the JRPG battle HUD
                         + Battle Assets scene helpers (v1.1.3).

The 8 anchor zones (portraits, HP boxes, menus, dialog box, BG frame) are
**hardcoded** for v1 : the user cannot move them visually in the engine UI.
The reasoning : a scene-canvas editor for anchors proved confusing in UX
testing (anchors invisible without dedicated render, no clear way to
distinguish "edit position" from "edit content"). For v1 we ship a fixed,
battle-tested layout matching ``jrpg_demo.c``. Customization power is moved
to the Mechanics tab inline_config (menu items, display toggles, audio,
formulas) — that's where ALL the variation lives now.

These constants are still consumed by ``battle_engine_gen.py`` which emits
them as ``BE_ANCHOR_*_X/Y/W/H`` #defines in the generated header. Positions
are in PIXELS (already multiplied — no tile conversion needed). The user can
swap in a custom background tilemap via ``mechanics_config.battle_engine.bg_tilemap``
to fit the visual style of their game.

Reference image for the user : the zones documented here mark the screen
regions where the runtime draws HUD elements. The user's BG should ideally
leave these areas plain (text will overdraw them) — see the table below.
"""
from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Battle Assets scene (v1.1.3 — re-introduced after v1.1 tear-down)
# ---------------------------------------------------------------------------
# Container scene for monster sprites + battle BG tilemap. Auto-spawned when
# battle_engine mech is ON. Distinct from gameplay scenes : not startable,
# not target of goto_scene, hidden from random_encounters per-scene list.
# Sprites/tilemaps added here flow through the normal aggregation helpers
# (_list_project_sprites / _list_project_tilemaps) and appear in dropdowns.

BATTLE_ASSETS_SCENE_ID:    str = "scene_battle_assets"
BATTLE_ASSETS_SCENE_LABEL: str = "📦 Battle Assets"


def make_default_battle_assets_scene() -> dict:
    """Return a fresh empty Battle Assets scene dict. The user populates
    sprites/tilemaps via the standard Level tab UI."""
    return {
        "id":              BATTLE_ASSETS_SCENE_ID,
        "label":           BATTLE_ASSETS_SCENE_LABEL,
        "level_profile":   "menu",
        "level_size":      {"w": 20, "h": 18},
        "level_layout":    {"cam_mode": "fixed", "scroll_x": False, "scroll_y": False},
        "level_rules":     {},
        "entities":        [],
        "sprites":         [],  # ← user drops monster sprites here
        "tilemaps":        [],  # ← user drops battle BG tilemap here
        "triggers":        [],
        "waves":           [],
        "is_battle_assets_scene": True,
        "auto_generated":        True,
        "managed_by_mechanic":   "battle_engine",
    }


def is_battle_assets_scene(scene: dict) -> bool:
    if not isinstance(scene, dict):
        return False
    return bool(scene.get("is_battle_assets_scene"))


def find_battle_assets_scene(project_data: dict) -> Optional[dict]:
    if not isinstance(project_data, dict):
        return None
    scenes = project_data.get("scenes", [])
    if not isinstance(scenes, list):
        return None
    for sc in scenes:
        if is_battle_assets_scene(sc):
            return sc
    return None


# Order matters : used as the canonical kind list for codegen iteration.
BATTLE_ANCHOR_KINDS: list[str] = [
    "player_portrait",
    "enemy_portrait",
    "hp_box_player",
    "hp_box_enemy",
    "cmd_menu_box",
    "item_status_box",
    "dialog_box",
    "bg_box_top",
]

# Static layout in PIXELS (NGPC screen = 160×152 = 20×19 tiles of 8 px).
# Values are derived from ``jrpg_demo.c`` (the working reference game) :
# portrait coords match HERO_BATTLE_X / ENEMY_BATTLE_X literally ; HUD box
# coords come from the text-grid positions in ``jrpg_battle_draw_*()``
# multiplied by 8 to give pixel-precise BE_ANCHOR_* values.
BATTLE_ANCHOR_KIND_INFO: dict[str, dict] = {
    "player_portrait": {
        "label":  "Portrait héros",
        "x":   8, "y":  44,           # demo autorun L707 : (8 + hero_dx, 44 + hero_dy)
        "w":  24, "h":  24,
        "desc":  "Sprite du héros pendant le combat (gauche-milieu, 24×24 px)",
    },
    "enemy_portrait": {
        "label":  "Portrait ennemi",
        "x": 112, "y":  18,           # demo autorun L708 : (112 + enemy_dx, 18 + enemy_dy)
        "w":  24, "h":  24,
        "desc":  "Sprite de l'ennemi (haut-droite, 24×24 px, HFLIP).",
    },
    "hp_box_enemy": {
        "label":  "Boîte HP ennemi",
        "x":   8, "y":   8,           # text(1,1) × 8 — demo L419
        "w":  64, "h":  32,
        "desc":  "Nom ennemi (1,1) + HP (1,3) — haut-gauche.",
    },
    "hp_box_player": {
        "label":  "Boîte HP héros",
        "x":  72, "y":  64,           # text(9,8) × 8 — demo L420
        "w":  64, "h":  32,
        "desc":  "Nom héros (9,8) + HP (9,10) — milieu-droite.",
    },
    "cmd_menu_box": {
        "label":  "Menu commandes",
        "x":   8, "y": 112,           # text(1,14) × 8
        "w":  64, "h":  32,
        "desc":  "Menu ATTACK/ITEM/GUARD/RUN (et sub-menu items) — 8×4 cells",
    },
    "item_status_box": {
        "label":  "Status / inventaire",
        "x":  88, "y": 112,           # text(11,14) × 8
        "w":  64, "h":  32,
        "desc":  "Cadre droite : qté items, GUARD/READY, hint bouton — 8×4 cells",
    },
    "dialog_box": {
        "label":  "Dialog box",
        "x":   0, "y": 112,           # text(0,14) × 8
        "w": 160, "h":  40,
        "desc":  "Messages combat (pleine largeur, 20×5 cells). Recouvre cmd_menu_box quand visible.",
    },
    "bg_box_top": {
        "label":  "Cadre fond haut",
        "x":   0, "y":   0,           # text(0,0) × 8
        "w": 160, "h":  40,
        "desc":  "Cadre décoratif haut (20×5 cells). Contient les boîtes HP.",
    },
}
