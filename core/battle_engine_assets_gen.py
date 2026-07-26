"""
core/battle_engine_assets_gen.py — Emits the project-specific .h/.c companion
files that wire the static battle_engine.c template to the actual sprite +
tilemap symbols of the user's project.

Three artefacts are generated next to the rest of the gen/ output:

    battle_engine_assets.h   — extern decls of helper functions
    battle_engine_assets.c   — function bodies: load BG tilemap, load sprite
                               tiles+palettes, draw hero portrait, draw monster
                               portrait. The .c #includes every per-sprite
                               <name>_mspr.h and (optionally) the BG <name>_map.h.

The battle_engine.c static template calls these helpers — that keeps it
project-agnostic while still rendering the user's actual assets.
"""
from __future__ import annotations

import re
from pathlib import Path

from core.mechanics import get_mechanic_config


_OUTPUT_H = "battle_engine_assets.h"
_OUTPUT_C = "battle_engine_assets.c"

# VRAM tile layout during battle :
#   0x20..0x7F  = BIOS sysfont (~96 tiles, BIOS-managed)
#   128..       = BG tilemap (NGPNG_RANDOM_ENCOUNTER_TILE_BASE = 128 in demo)
#   320..       = battle hero sprite (NGPNG_BATTLE_HERO_TILE_BASE)
#   320 + hero_tile_count = first monster sprite
#   (each monster follows immediately after the previous one)
# Tile counts are READ from the exported <name>_mspr.c files at codegen time
# so the layout adapts to the actual sprite sizes — critical for gameplay
# sprites used as battle portraits (e.g. player_topdown with 54 tiles
# vs the demo's dedicated 13-tile battle portrait).
_BG_TILE_BASE          = 128
_BG_PAL_BASE_SCR2      = 0
_HERO_TILE_BASE        = 320
_HERO_PAL_BASE         = 10
_MONSTER_PAL_BASE_0    = 11
_MONSTER_PAL_STRIDE    = 1
_DEFAULT_TILE_RESERVE  = 16    # fallback if we can't parse tile count

# Regex to parse <name>_tiles_count from generated *_mspr.c.
_TILES_COUNT_RE = re.compile(r"(\w+)_tiles_count\s*=\s*(\d+)\s*u?\s*;")


def _read_sprite_tile_count(export_dir: Path, sprite_name: str) -> int:
    """Return the tile count (NOT u16 words) for a generated sprite, or a
    safe default if the file is missing / unparseable. tiles_count in the
    generated .c is in u16 words ; each tile is 8 words → tile_count = words / 8.
    """
    mspr_c = export_dir / f"{sprite_name}_mspr.c"
    if not mspr_c.is_file():
        return _DEFAULT_TILE_RESERVE
    try:
        text = mspr_c.read_text(encoding="utf-8")
    except OSError:
        return _DEFAULT_TILE_RESERVE
    m = _TILES_COUNT_RE.search(text)
    if not m:
        return _DEFAULT_TILE_RESERVE
    words = int(m.group(2))
    return max(1, words // 8)


# Regex to parse <name>_palette_count from generated *_mspr.c.
_PALETTE_COUNT_RE = re.compile(r"(\w+)_palette_count\s*=\s*(\d+)\s*u?\s*;")
# Regex to detect <name>_layer1 symbols in generated *_mspr.h.
_LAYER1_RE = re.compile(r"_HAS_LAYER1\s+1")


def _read_sprite_palette_count(export_dir: Path, sprite_name: str) -> int:
    """Return the palette count for a generated sprite, or 1 as default."""
    mspr_c = export_dir / f"{sprite_name}_mspr.c"
    if not mspr_c.is_file():
        return 1
    try:
        text = mspr_c.read_text(encoding="utf-8")
    except OSError:
        return 1
    m = _PALETTE_COUNT_RE.search(text)
    if not m:
        return 1
    return max(1, int(m.group(2)))


def _sprite_has_layer1(export_dir: Path, sprite_name: str) -> bool:
    """Return True if the sprite has a layer1 secondary layer."""
    mspr_h = export_dir / f"{sprite_name}_mspr.h"
    if not mspr_h.is_file():
        return False
    try:
        text = mspr_h.read_text(encoding="utf-8")
    except OSError:
        return False
    return bool(_LAYER1_RE.search(text))


def _safe_sym(name: str) -> str:
    """Sanitize a user-facing name into a C-identifier-safe token."""
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", name.strip()).strip("_")
    return s or "asset"


def _aggregate_project_sprites(project_data: dict) -> list[str]:
    """Return the project-wide sprite NAME list in scene-iteration order.
    Mirrors monster_table_gen._aggregate_project_sprites so that
    `hero_sprite_id` and monster `sprite_id` resolve against the same list.
    """
    if not isinstance(project_data, dict):
        return []
    scenes = project_data.get("scenes", []) or []
    if not isinstance(scenes, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for sc in scenes:
        if not isinstance(sc, dict):
            continue
        for spr in (sc.get("sprites") or []):
            if not isinstance(spr, dict):
                continue
            name = str(spr.get("name", "") or "").strip()
            if name and name not in seen:
                seen.add(name)
                out.append(name)
    return out


def _resolve_hero_sprite(project_data: dict, cfg: dict) -> str | None:
    """Return the sprite NAME for the hero, or None if no project sprite exists.

    Precedence:
      1. cfg["hero_sprite_name"]   — explicit picker (added in v1.1.6)
      2. project sprite at index cfg["hero_sprite_id"]  — numeric legacy field
      3. project sprite at index 0  — fallback (first sprite encountered)
    """
    names = _aggregate_project_sprites(project_data)
    if not names:
        return None
    hero_name = str(cfg.get("hero_sprite_name", "") or "").strip()
    if hero_name and hero_name in names:
        return hero_name
    try:
        idx = int(cfg.get("hero_sprite_id", 0) or 0)
    except (TypeError, ValueError):
        idx = 0
    if 0 <= idx < len(names):
        return names[idx]
    return names[0]


def _resolve_monster_sprites(project_data: dict) -> list[tuple[str, str]]:
    """Return [(resolved_sprite_name, requested_name)] per monster.

    Resolution rules:
      - If sprite_name is set AND that sprite exists in any project scene
        → use it (resolved == requested).
      - If sprite_name is set but NOT found in any scene → resolved is "" and
        requested holds the user's value (codegen emits a /* missing: ... */
        comment so the user knows to add the sprite to a scene).
      - If sprite_name is unset → fall back to sprite_id as positional index
        into the aggregated project sprite list ; on out-of-range, ("", "").

    The hard rule is "never silently fall back to the wrong sprite" — a
    user-typed sprite_name takes priority over positional lookup, and a
    typo / missing-sprite case produces a no-draw rather than the wrong art.
    """
    if not isinstance(project_data, dict):
        return []
    monsters = project_data.get("monster_table", []) or []
    if not isinstance(monsters, list):
        return []
    names = _aggregate_project_sprites(project_data)
    out: list[tuple[str, str]] = []
    for entry in monsters:
        if not isinstance(entry, dict):
            out.append(("", ""))
            continue
        sn = str(entry.get("sprite_name", "") or "").strip()
        if sn:
            if sn in names:
                out.append((sn, sn))
            else:
                out.append(("", sn))  # missing — codegen emits a comment
            continue
        try:
            sid = int(entry.get("sprite_id", 0) or 0)
        except (TypeError, ValueError):
            sid = 0
        if 0 <= sid < len(names):
            out.append((names[sid], ""))
        else:
            out.append(("", ""))
    return out


def _resolve_bg_tilemap(cfg: dict) -> str | None:
    """Return the bg tilemap NAME (codegen prefix) or None if unset / blank."""
    raw = str(cfg.get("bg_tilemap", "") or "").strip()
    if not raw:
        return None
    return _safe_sym(raw)


def make_battle_engine_assets_h() -> str:
    return "\n".join([
        "/* battle_engine_assets.h — auto-generated by NgpCraft Engine */",
        "/* DO NOT EDIT — re-export from the project to update. */",
        "/* Project-specific helpers consumed by battle_engine.c. */",
        "#ifndef BATTLE_ENGINE_ASSETS_GEN_H",
        "#define BATTLE_ENGINE_ASSETS_GEN_H",
        "",
        "#include \"ngpc_types.h\"",
        "",
        "/* Load the battle BG (palettes + tiles + tilemap blit). No-op when",
        "   the project's battle_engine.bg_tilemap field is empty.            */",
        "void battle_engine_load_bg(void);",
        "",
        "/* Load every sprite asset referenced by the battle (hero + each      */",
        "/* monster). Tiles + palettes pushed to VRAM at the bases stored in   */",
        "/* the per-sprite headers (set by the engine's sprite export pass).   */",
        "void battle_engine_load_sprites(void);",
        "",
        "/* Draw the hero portrait at pixel (x, y) using anim frame_idx. */",
        "void battle_engine_draw_hero(s16 x, s16 y, u16 frame_idx);",
        "",
        "/* Draw the enemy portrait at pixel (x, y) for the current monster.  */",
        "/* monster_idx indexes g_monster_table[]. Falls back silently when no */",
        "/* sprite is configured for that monster.                             */",
        "void battle_engine_draw_monster(u8 monster_idx, s16 x, s16 y, u16 frame_idx);",
        "",
        "#endif /* BATTLE_ENGINE_ASSETS_GEN_H */",
        "",
    ])


def make_battle_engine_assets_c(*, project_data: dict, export_dir: Path | None = None) -> str:
    cfg = get_mechanic_config(project_data, "battle_engine")
    hero_name = _resolve_hero_sprite(project_data, cfg)
    monster_resolved = _resolve_monster_sprites(project_data)  # [(resolved, requested), ...]
    bg_name = _resolve_bg_tilemap(cfg)

    # Unique sprite names to include (hero + monsters), preserving order
    sprite_includes: list[str] = []
    seen_inc: set[str] = set()
    if hero_name:
        sprite_includes.append(hero_name); seen_inc.add(hero_name)
    for resolved, _req in monster_resolved:
        if resolved and resolved not in seen_inc:
            sprite_includes.append(resolved); seen_inc.add(resolved)

    # Compute tile bases dynamically based on actual sprite tile counts.
    # Hero starts at 320 ; each monster starts right after the previous
    # sprite in VRAM. Without this, a gameplay-portrait hero (e.g. 54-tile
    # player_topdown walk-cycle) would overlap the monster's slot 333 and
    # corrupt both sprites' tiles.
    tile_base_of: dict[str, int] = {}
    palette_count_of: dict[str, int] = {}
    has_layer1_of: dict[str, bool] = {}
    cursor = _HERO_TILE_BASE
    def _record(name: str) -> None:
        nonlocal cursor
        if export_dir is not None:
            tile_count = _read_sprite_tile_count(export_dir, name)
            palette_count_of[name] = _read_sprite_palette_count(export_dir, name)
            has_layer1_of[name] = _sprite_has_layer1(export_dir, name)
        else:
            tile_count = _DEFAULT_TILE_RESERVE
            palette_count_of[name] = 1
            has_layer1_of[name] = False
        tile_base_of[name] = cursor
        cursor += tile_count
    if hero_name:
        _record(hero_name)
    for resolved, _req in monster_resolved:
        if not resolved or resolved in tile_base_of:
            continue
        _record(resolved)

    # Compute palette bases dynamically — each sprite reserves `palette_count`
    # contiguous slots so layer1 (which uses palette index 1) renders with the
    # right colors. Hero starts at pal_base 10 ; monsters chain after it.
    pal_base_of: dict[str, int] = {}
    pal_cursor = _HERO_PAL_BASE
    if hero_name:
        pal_base_of[hero_name] = pal_cursor
        pal_cursor += palette_count_of[hero_name]
    for resolved, _req in monster_resolved:
        if not resolved or resolved in pal_base_of:
            continue
        pal_base_of[resolved] = pal_cursor
        pal_cursor += palette_count_of[resolved]

    lines: list[str] = [
        "/* battle_engine_assets.c — auto-generated by NgpCraft Engine */",
        "/* DO NOT EDIT — re-export from the project to update. */",
        "",
        "#include \"ngpc_hw.h\"",
        "#include \"ngpc_gfx.h\"",
        "#include \"ngpc_sprite.h\"",
        "#include \"ngpc_metasprite.h\"",
        "#include \"../../src/gfx/ngpc_tilemap_blit.h\"",
        "",
        "#include \"battle_engine_assets.h\"",
        "#include \"monster_table.h\"",
        "",
    ]
    if bg_name:
        lines.append(f"#include \"{bg_name}_map.h\"")
    for s in sprite_includes:
        lines.append(f"#include \"{s}_mspr.h\"")
    lines.append("")

    # ---- battle_engine_load_bg ---------------------------------------------
    # BG goes on SCR2 (back layer). Demo pattern: NGP_TILEMAP_BLIT_SCR2.
    lines += [
        "void battle_engine_load_bg(void)",
        "{",
    ]
    if bg_name:
        lines += [
            f"    NGP_TILEMAP_BLIT_SCR2({bg_name}, {_BG_TILE_BASE}u);",
        ]
    else:
        lines += [
            "    /* No bg_tilemap configured in mech battle_engine — solid bg color only. */",
        ]
    lines += ["}", ""]

    # ---- helper + battle_engine_load_sprites -------------------------------
    # Push all palette variants of a sprite (palette_count contiguous slots
    # starting at base). Critical for layer1-using sprites whose layer1 frames
    # reference palette index 1 — without this, layer1 sub-sprites read the
    # WRONG palette slot (the monster's, or stale gameplay data).
    lines += [
        "/* Push <count> palettes from <palettes>[] starting at SPR slot <base>. */",
        "static void be_push_palettes(const u16 NGP_FAR *palettes, u8 count, u8 base)",
        "{",
        "    u8 i;",
        "    for (i = 0u; i < count; i++) {",
        "        ngpc_gfx_set_palette(GFX_SPR, (u8)(base + i),",
        "            palettes[(u16)(i * 4u) + 0u],",
        "            palettes[(u16)(i * 4u) + 1u],",
        "            palettes[(u16)(i * 4u) + 2u],",
        "            palettes[(u16)(i * 4u) + 3u]);",
        "    }",
        "}",
        "",
        "void battle_engine_load_sprites(void)",
        "{",
    ]
    if not sprite_includes:
        lines += [
            "    /* No project sprites configured — nothing to load. */",
        ]
    else:
        if hero_name:
            t_base = tile_base_of[hero_name]
            p_base = pal_base_of[hero_name]
            p_cnt  = palette_count_of[hero_name]
            lines += [
                f"    /* Hero portrait '{hero_name}' : tile {t_base} / pal {p_base} ({p_cnt} pal). */",
                f"    {hero_name}_tile_base = {t_base}u;",
                f"    {hero_name}_pal_base  = {p_base}u;",
                f"    be_push_palettes({hero_name}_palettes, {hero_name}_palette_count, {p_base}u);",
                f"    ngpc_gfx_load_tiles_at({hero_name}_tiles, {hero_name}_tiles_count, {t_base}u);",
                "",
            ]
        for resolved, _req in monster_resolved:
            if not resolved or resolved == hero_name:
                continue
            if resolved not in pal_base_of:
                continue
            t_base = tile_base_of[resolved]
            p_base = pal_base_of[resolved]
            p_cnt  = palette_count_of[resolved]
            lines += [
                f"    /* Monster '{resolved}' : tile {t_base} / pal {p_base} ({p_cnt} pal). */",
                f"    {resolved}_tile_base = {t_base}u;",
                f"    {resolved}_pal_base  = {p_base}u;",
                f"    be_push_palettes({resolved}_palettes, {resolved}_palette_count, {p_base}u);",
                f"    ngpc_gfx_load_tiles_at({resolved}_tiles, {resolved}_tiles_count, {t_base}u);",
                "",
            ]
    lines += ["}", ""]

    # ---- battle_engine_draw_hero -------------------------------------------
    try:
        hero_frame_pinned = int(cfg.get("hero_portrait_frame", 0) or 0)
    except (TypeError, ValueError):
        hero_frame_pinned = 0
    hero_animate = bool(cfg.get("hero_portrait_animate", False))
    lines += [
        "void battle_engine_draw_hero(s16 x, s16 y, u16 frame_idx)",
        "{",
    ]
    if hero_name:
        hero_has_l1 = has_layer1_of.get(hero_name, False)
        lines.append("    /* HERO_SPR_SLOT = 0 ; SPR_MIDDLE priority like demo. */")
        if hero_animate:
            anim_expr = f"{hero_name}_anim[(frame_idx / 20u) % {hero_name}_anim_count].frame"
            l1_expr   = f"{hero_name}_layer1_anim[(frame_idx / 20u) % {hero_name}_layer1_anim_count].frame"
        else:
            lines.append("    (void)frame_idx;  /* pinned to portrait frame */")
            anim_expr = (
                f"{hero_name}_anim[({hero_frame_pinned}u < {hero_name}_anim_count) "
                f"? {hero_frame_pinned}u : 0u].frame"
            )
            l1_expr = (
                f"{hero_name}_layer1_anim[({hero_frame_pinned}u < {hero_name}_layer1_anim_count) "
                f"? {hero_frame_pinned}u : 0u].frame"
            )
        lines += [
            "    /* Base layer at slots 0-3. */",
            "    ngpc_mspr_draw(0u, x, y,",
            f"                   {anim_expr},",
            "                   (u8)SPR_MIDDLE);",
        ]
        if hero_has_l1:
            lines += [
                "    /* Layer1 at slots 4-7 (uses palette index 1 — must be loaded). */",
                "    ngpc_mspr_draw(4u, x, y,",
                f"                   {l1_expr},",
                "                   (u8)SPR_MIDDLE);",
            ]
    else:
        lines += [
            "    (void)x; (void)y; (void)frame_idx; /* no hero sprite configured */",
        ]
    lines += ["}", ""]

    # ---- battle_engine_draw_monster ----------------------------------------
    # Build a switch dispatching on monster_idx → the right sprite anim array.
    lines += [
        "void battle_engine_draw_monster(u8 monster_idx, s16 x, s16 y, u16 frame_idx)",
        "{",
    ]
    drawable = any(bool(r) for r, _ in monster_resolved)
    if not drawable:
        lines += [
            "    (void)monster_idx; (void)x; (void)y; (void)frame_idx;",
            "    /* No monster has a sprite configured in any project scene.   */",
            "    /* TIP: add the sprite PNG to a scene (e.g. Battle Assets)    */",
            "    /*      so it gets exported and becomes available here.       */",
        ]
    else:
        lines += [
            "#if defined(MONSTER_COUNT)",
            "#if MONSTER_COUNT > 0u",
            "    u8 slot = g_monster_table[monster_idx].sprite_slot;",
            "    switch (monster_idx) {",
        ]
        for i, (resolved, requested) in enumerate(monster_resolved):
            lines.append(f"    case {i}u:")
            if resolved:
                # Demo uses SPR_MIDDLE | SPR_HFLIP for enemy (faces left toward hero).
                lines += [
                    f"        ngpc_mspr_draw(slot, x, y,",
                    f"                       {resolved}_anim[frame_idx % {resolved}_anim_count].frame,",
                    "                       (u8)(SPR_MIDDLE | SPR_HFLIP));",
                ]
            else:
                if requested:
                    lines.append(
                        f"        /* monster {i} requests sprite '{requested}' but it is not "
                        f"in any project scene — add it to a scene (e.g. Battle Assets) so the "
                        f"engine exports it. */"
                    )
                else:
                    lines.append(
                        f"        /* monster {i} has no sprite_name and no resolvable sprite_id. */"
                    )
                lines.append("        (void)slot;")
            lines.append("        break;")
        lines += [
            "    default:",
            "        (void)slot; (void)x; (void)y; (void)frame_idx;",
            "        break;",
            "    }",
            "#else",
            "    (void)monster_idx; (void)x; (void)y; (void)frame_idx;",
            "#endif",
            "#else",
            "    (void)monster_idx; (void)x; (void)y; (void)frame_idx;",
            "#endif",
        ]
    lines += ["}", ""]

    return "\n".join(lines)


def write_battle_engine_assets(*, project_data: dict, export_dir: Path) -> tuple[Path, Path]:
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    h_path = export_dir / _OUTPUT_H
    c_path = export_dir / _OUTPUT_C
    h_path.write_text(make_battle_engine_assets_h(), encoding="utf-8")
    c_path.write_text(
        make_battle_engine_assets_c(project_data=project_data, export_dir=export_dir),
        encoding="utf-8",
    )
    return h_path, c_path
