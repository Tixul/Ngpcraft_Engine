"""
core/monster_table_gen.py — Generate monster_table.h from project monster_table.

Project data format (in .ngpcraft):
    {
        "monster_table": [
            {
                "name": "Slime", "max_hp": 12,
                "attack_min": 1, "attack_range": 3,
                "defense": 0,
                "crit_chance_pct": 5, "crit_multiplier": 20,  # ×2.0 stored ×10
                "miss_chance_pct": 5,
                "sprite_id": 0, "palette_base": 0, "sprite_slot": 20,
                "xp_drop": 3, "gold_drop": 2,
                "item_drops": [{"item_id": 0, "chance_pct": 25}],
            },
        ]
    }

All fields beyond "name" are optional with sane defaults so existing projects
(without a monster_table key) and projects upgraded from earlier versions both
load cleanly. sprite_slot is auto-allocated starting at 20 by step 4 when absent.

Generated output (monster_table.h):
    typedef struct {
        u8 max_hp; u8 attack_min; u8 attack_range;
        u8 defense; u8 crit_chance_pct; u8 crit_multiplier_x10;
        u8 miss_chance_pct;
        u8 sprite_id; u8 palette_base; u8 sprite_slot;
        u8 xp_drop; u8 gold_drop;
    } NgpcMonster;
    typedef struct { u8 item_id; u8 chance_pct; } NgpcMonsterDrop;
    #define MONSTER_COUNT N
    #define MONSTER_IDX_<NAME> i
    static const NgpcMonster g_monster_table[MONSTER_COUNT] = { ... };
    static const char *g_monster_names[MONSTER_COUNT] = { ... };
    static const NgpcMonsterDrop g_monster_drops[MONSTER_DROP_COUNT] = { ... };
    static const u8 g_monster_drop_offsets[MONSTER_COUNT + 1u] = { ... };

Usage:
    from core.monster_table_gen import write_monster_table_h
    path = write_monster_table_h(project_data=data, export_dir=Path("GraphX/gen"))
"""
from __future__ import annotations

import re
from pathlib import Path

_OUTPUT_FILENAME = "monster_table.h"

_DEFAULT_MAX_HP = 10
_DEFAULT_CRIT_MULT_X10 = 20   # ×2.0
_AUTO_SLOT_START = 20         # matches jrpg_demo.c ENEMY_SPR_SLOT
_AUTO_SLOT_STEP = 4           # rough metasprite footprint per monster


def _sanitize_name(name: str) -> str:
    """Return an UPPER_CASE C identifier from an arbitrary monster name."""
    s = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip()).strip("_").upper()
    return s or "UNNAMED"


def _escape_c_string(s: str) -> str:
    """Escape a Python string for use as a C string literal body."""
    return (
        s.replace("\\", "\\\\")
         .replace("\"", "\\\"")
         .replace("\n", "\\n")
         .replace("\r", "")
         .replace("\t", "\\t")
    )


def _read_entry(entry: dict) -> dict:
    """Normalise one raw monster entry — clamp + fill defaults. sprite_slot is
    resolved by the caller because auto-allocation needs cross-row state."""
    return {
        "name":            str(entry.get("name", "") or "").strip() or "monster",
        "max_hp":          max(1, min(255, int(entry.get("max_hp", _DEFAULT_MAX_HP) or _DEFAULT_MAX_HP))),
        "attack_min":      max(0, min(255, int(entry.get("attack_min", 1) or 0))),
        "attack_range":    max(0, min(255, int(entry.get("attack_range", 1) or 0))),
        "defense":         max(0, min(255, int(entry.get("defense", 0) or 0))),
        "crit_chance_pct": max(0, min(100, int(entry.get("crit_chance_pct", 0) or 0))),
        "crit_multiplier": max(10, min(255, int(entry.get("crit_multiplier", _DEFAULT_CRIT_MULT_X10) or _DEFAULT_CRIT_MULT_X10))),
        "miss_chance_pct": max(0, min(100, int(entry.get("miss_chance_pct", 0) or 0))),
        "sprite_id":       max(0, min(255, int(entry.get("sprite_id", 0) or 0))),
        "sprite_name":     str(entry.get("sprite_name", "") or "").strip(),
        "palette_base":    max(0, min(255, int(entry.get("palette_base", 0) or 0))),
        "xp_drop":         max(0, min(255, int(entry.get("xp_drop", 0) or 0))),
        "gold_drop":       max(0, min(255, int(entry.get("gold_drop", 0) or 0))),
        "item_drops":      entry.get("item_drops") if isinstance(entry.get("item_drops"), list) else [],
    }


def _aggregate_project_sprites(project_data: dict) -> list[str]:
    """Aggregate all sprite NAMES across scenes (project-wide, dedup, in order).
    Mirror of ui.tabs.mechanics_tab._list_project_sprites but returns just the
    names (codegen doesn't need labels)."""
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


def make_monster_table_h(*, project_data: dict) -> str:
    """Return the full content of monster_table.h as a string."""
    data = project_data if isinstance(project_data, dict) else {}
    raw = data.get("monster_table", []) or []
    if not isinstance(raw, list):
        raw = []

    # First pass: collect explicit user-assigned slots so auto-allocator can
    # skip them (prevents collision when user mixes explicit + auto).
    explicit_slots: set[int] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        s = entry.get("sprite_slot")
        if isinstance(s, (int, float)) and int(s) > 0:
            explicit_slots.add(max(0, min(255, int(s))))

    # Resolve sprite_name → sprite_id at export time : the position of the
    # name in the project-wide aggregated sprite list IS its ID for v1.1.2.
    # (Future v1.5 will emit proper mspr_<name> symbol references instead.)
    project_sprite_names = _aggregate_project_sprites(data)
    name_to_id: dict[str, int] = {n: i for i, n in enumerate(project_sprite_names)}

    monsters: list[dict] = []
    auto_slot = _AUTO_SLOT_START
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        m = _read_entry(entry)
        # Sprite : NAME wins (UI picker), sprite_id is legacy fallback.
        if m["sprite_name"] and m["sprite_name"] in name_to_id:
            m["sprite_id"] = name_to_id[m["sprite_name"]]
        explicit = entry.get("sprite_slot")
        if isinstance(explicit, (int, float)) and int(explicit) > 0:
            m["sprite_slot"] = max(0, min(255, int(explicit)))
        else:
            while auto_slot in explicit_slots and auto_slot < 255:
                auto_slot += _AUTO_SLOT_STEP
            m["sprite_slot"] = auto_slot
            auto_slot = min(255, auto_slot + _AUTO_SLOT_STEP)
        monsters.append(m)

    lines: list[str] = [
        "/* monster_table.h — auto-generated by NgpCraft Engine */",
        "/* DO NOT EDIT — re-export from the project tab to update. */",
        "#ifndef MONSTER_TABLE_GEN_H",
        "#define MONSTER_TABLE_GEN_H",
        "",
        "typedef struct {",
        "    u8 max_hp;",
        "    u8 attack_min; u8 attack_range;",
        "    u8 defense;",
        "    u8 crit_chance_pct; u8 crit_multiplier_x10;",
        "    u8 miss_chance_pct;",
        "    u8 sprite_id; u8 palette_base; u8 sprite_slot;",
        "    u8 xp_drop; u8 gold_drop;",
        "} NgpcMonster;",
        "",
        "typedef struct { u8 item_id; u8 chance_pct; } NgpcMonsterDrop;",
        "",
    ]

    if not monsters:
        lines += [
            "#define MONSTER_COUNT       0u",
            "#define MONSTER_DROP_COUNT  0u",
            "/* (no monsters defined) */",
            "",
            "#endif /* MONSTER_TABLE_GEN_H */",
            "",
        ]
        return "\n".join(lines)

    lines.append(f"#define MONSTER_COUNT       {len(monsters)}u")
    lines.append("")
    lines.append("/* ---- Per-monster index constants ---- */")
    # Dedupe safe-names so duplicate user-facing names ("monster", "monster")
    # don't produce duplicate #define macros (C error THC1-322). Append a
    # numeric suffix on collision : MONSTER_IDX_MONSTER, MONSTER_IDX_MONSTER_2, ...
    _seen: dict[str, int] = {}
    for i, m in enumerate(monsters):
        base = _sanitize_name(m["name"])
        if base in _seen:
            _seen[base] += 1
            safe = f"{base}_{_seen[base]}"
        else:
            _seen[base] = 1
            safe = base
        lines.append(f"#define MONSTER_IDX_{safe:<24} {i}u  /* {m['name']} */")

    lines.append("")
    lines.append("static const NgpcMonster g_monster_table[MONSTER_COUNT] = {")
    for i, m in enumerate(monsters):
        sep = "," if i < len(monsters) - 1 else ""
        lines.append(
            f"    /* [{i}] {m['name']:<20} */ "
            f"{{ {m['max_hp']:>3}u, {m['attack_min']:>3}u, {m['attack_range']:>3}u, "
            f"{m['defense']:>3}u, {m['crit_chance_pct']:>3}u, {m['crit_multiplier']:>3}u, "
            f"{m['miss_chance_pct']:>3}u, {m['sprite_id']:>3}u, {m['palette_base']:>3}u, "
            f"{m['sprite_slot']:>3}u, {m['xp_drop']:>3}u, {m['gold_drop']:>3}u }}{sep}"
        )
    lines += ["};", ""]

    # Name table — referenced by battle_engine for dialog templates ("{enemy}").
    lines.append("static const char *g_monster_names[MONSTER_COUNT] = {")
    for i, m in enumerate(monsters):
        sep = "," if i < len(monsters) - 1 else ""
        lines.append(f"    \"{_escape_c_string(m['name'])}\"{sep}")
    lines += ["};", ""]

    # Sprite-name table — for v1.5 runtime that wants to look up the mspr_<name>
    # symbol dynamically. v1.1.2 keeps sprite_id as the runtime path ; this
    # table is informational + future-proofing.
    lines.append("static const char *g_monster_sprite_names[MONSTER_COUNT] = {")
    for i, m in enumerate(monsters):
        sep = "," if i < len(monsters) - 1 else ""
        sn = m.get("sprite_name", "") or ""
        lines.append(f"    \"{_escape_c_string(sn)}\"{sep}")
    lines += ["};", ""]

    # Flattened item-drops with per-monster offset lookup.
    # Monster i's drops live at g_monster_drops[offsets[i] .. offsets[i+1]).
    flat_drops: list[tuple[int, int, str]] = []
    offsets: list[int] = []
    for m in monsters:
        offsets.append(len(flat_drops))
        for drop in m["item_drops"]:
            if not isinstance(drop, dict):
                continue
            item_id = max(0, min(255, int(drop.get("item_id", 0) or 0)))
            chance = max(0, min(100, int(drop.get("chance_pct", 0) or 0)))
            flat_drops.append((item_id, chance, m["name"]))
    offsets.append(len(flat_drops))  # sentinel for length calc

    if flat_drops:
        lines.append(f"#define MONSTER_DROP_COUNT  {len(flat_drops)}u")
        lines.append("static const NgpcMonsterDrop g_monster_drops[MONSTER_DROP_COUNT] = {")
        for i, (item_id, chance, mname) in enumerate(flat_drops):
            sep = "," if i < len(flat_drops) - 1 else ""
            lines.append(f"    /* [{i}] {mname:<20} */ {{ {item_id:>3}u, {chance:>3}u }}{sep}")
        lines += ["};", ""]
        lines.append(f"static const u8 g_monster_drop_offsets[MONSTER_COUNT + 1u] = {{")
        for i, off in enumerate(offsets):
            sep = "," if i < len(offsets) - 1 else ""
            lines.append(f"    {off:>3}u{sep}")
        lines += ["};", ""]
    else:
        lines += [
            "#define MONSTER_DROP_COUNT  0u",
            "/* g_monster_drops[] omitted — no monster has item drops. */",
            "",
        ]

    lines += [
        "#endif /* MONSTER_TABLE_GEN_H */",
        "",
    ]
    return "\n".join(lines)


def write_monster_table_h(*, project_data: dict, export_dir: Path) -> Path:
    """Write ``monster_table.h`` to *export_dir*. Returns the written path."""
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    content = make_monster_table_h(project_data=project_data)
    out = export_dir / _OUTPUT_FILENAME
    out.write_text(content, encoding="utf-8")
    return out
