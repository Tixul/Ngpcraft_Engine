"""
core/game_vars_gen.py - Generate ngpc_game_vars.h from project game_flags / game_vars.

Tree-shaking: only emits #define aliases for slots that are either named by the user
OR referenced in at least one trigger condition/action across all scenes.
Unnamed + unreferenced slots are silently skipped.

Project data format (in .ngpcraft):
    {
        "game_flags": ["flag_0", "has_sword", "", "visited_town", ...],   # 8 strings
        "game_vars":  [
            {"name": "coins",  "init": 0},
            {"name": "health", "init": 3},
            ...
        ]                                                                  # 8 entries
    }

Generated output (ngpc_game_vars.h):
    #ifndef NGPC_GAME_VARS_GEN_H
    #define NGPC_GAME_VARS_GEN_H
    /* Flags: s_ngpng_flags[i] */
    #define GAME_FLAG_0  0  /* has_sword   */
    #define GAME_FLAG_3  3  /* visited_town */
    /* Variables: s_ngpng_vars[i] */
    #define GAME_VAR_0   0  /* coins  (init: 0) */
    #define GAME_VAR_1   1  /* health (init: 3) */
    static const u8 g_game_var_inits[8] = { 0, 3, 0, 0, 0, 0, 0, 0 };
    #endif

Usage:
    from core.game_vars_gen import write_game_vars_h, collect_used_indices
    path = write_game_vars_h(project_data=data, export_dir=Path("GraphX/gen"))
"""
from __future__ import annotations

import re
from pathlib import Path

_OUTPUT_FILENAME = "ngpc_game_vars.h"
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_COUNT = 8

# Trigger condition/action types that access game_flags via flag_var_index / action_flag_var
_FLAG_CONDS = frozenset({
    "flag_set", "flag_clear", "all_switches_on",
})
_FLAG_ACTIONS = frozenset({
    "set_flag", "clear_flag", "toggle_flag",
})

# Trigger condition/action types that access game_vars via flag_var_index / action_flag_var
_VAR_CONDS = frozenset({
    "variable_ge", "variable_eq", "variable_le", "variable_ne",
    "count_eq", "quest_stage_eq", "resource_ge",
})
_VAR_ACTIONS = frozenset({
    "set_variable", "inc_variable", "dec_variable",
})


def _safe_ident(name: str, fallback: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", name.strip()).strip("_")
    return s if s and _IDENT_RE.match(s) else fallback


def _iter_trigger_cond_refs(trig: dict):
    """Yield (is_flag: bool, index: int) for every flag/var reference in one trigger."""
    # Main condition
    cond = trig.get("cond", "")
    idx = trig.get("flag_var_index")
    if idx is not None:
        if cond in _FLAG_CONDS:
            yield (True, int(idx))
        elif cond in _VAR_CONDS:
            yield (False, int(idx))

    # Extra AND conditions
    for extra in trig.get("extra_conds", []) or []:
        if not isinstance(extra, dict):
            continue
        econd = extra.get("cond", "")
        eidx = extra.get("flag_var_index")
        if eidx is not None:
            if econd in _FLAG_CONDS:
                yield (True, int(eidx))
            elif econd in _VAR_CONDS:
                yield (False, int(eidx))

    # OR groups
    for grp in trig.get("or_groups", []) or []:
        if not isinstance(grp, dict):
            continue
        for gcond in grp.get("conditions", []) or []:
            if not isinstance(gcond, dict):
                continue
            gcond_type = gcond.get("cond", "")
            gidx = gcond.get("flag_var_index")
            if gidx is not None:
                if gcond_type in _FLAG_CONDS:
                    yield (True, int(gidx))
                elif gcond_type in _VAR_CONDS:
                    yield (False, int(gidx))

    # Action
    action = trig.get("action", "")
    aidx = trig.get("action_flag_var")
    if aidx is not None:
        if action in _FLAG_ACTIONS:
            yield (True, int(aidx))
        elif action in _VAR_ACTIONS:
            yield (False, int(aidx))


def collect_used_indices(project_data: dict) -> tuple[set[int], set[int]]:
    """Scan all triggers in all scenes.

    Returns:
        (used_flag_indices, used_var_indices) — sets of int in range 0-7.
    """
    used_flags: set[int] = set()
    used_vars: set[int] = set()
    if not isinstance(project_data, dict):
        return used_flags, used_vars
    for scene in project_data.get("scenes", []) or []:
        if not isinstance(scene, dict):
            continue
        for trig in scene.get("triggers", []) or []:
            if not isinstance(trig, dict):
                continue
            for is_flag, idx in _iter_trigger_cond_refs(trig):
                if 0 <= idx < _COUNT:
                    (used_flags if is_flag else used_vars).add(idx)
    return used_flags, used_vars


def make_game_vars_h(*, project_data: dict) -> str:
    """Return the full content of ngpc_game_vars.h as a string.

    Tree-shaking: a slot is emitted only if it is named OR referenced in a trigger.
    The g_game_var_inits[8] array is always emitted in full (runtime compatibility).
    """
    data = project_data if isinstance(project_data, dict) else {}

    raw_flags = data.get("game_flags", []) or []
    if not isinstance(raw_flags, list):
        raw_flags = []
    raw_vars = data.get("game_vars", []) or []
    if not isinstance(raw_vars, list):
        raw_vars = []

    # Resolve names and inits
    flag_names: list[str] = []
    for i in range(_COUNT):
        raw = str(raw_flags[i]) if i < len(raw_flags) else ""
        flag_names.append(_safe_ident(raw, ""))   # empty string = unnamed

    var_names: list[str] = []
    var_inits: list[int] = []
    for i in range(_COUNT):
        entry = raw_vars[i] if i < len(raw_vars) and isinstance(raw_vars[i], dict) else {}
        var_names.append(_safe_ident(str(entry.get("name", "") or ""), ""))
        var_inits.append(max(0, min(255, int(entry.get("init", 0) or 0))))

    # Collect which indices are actually referenced in triggers
    used_flag_idx, used_var_idx = collect_used_indices(data)

    # A slot is active if it has a user-given name OR is referenced in a trigger
    active_flags = [
        i for i in range(_COUNT)
        if flag_names[i] or i in used_flag_idx
    ]
    active_vars = [
        i for i in range(_COUNT)
        if var_names[i] or i in used_var_idx
    ]

    lines: list[str] = [
        "/* ngpc_game_vars.h — auto-generated by NgpCraft Engine */",
        "/* DO NOT EDIT — re-export from the project tab to update. */",
        "#ifndef NGPC_GAME_VARS_GEN_H",
        "#define NGPC_GAME_VARS_GEN_H",
        "",
    ]

    # --- Flags section ---
    lines.append("/* ---- Persistent flags (s_ngpng_flags[i]) ---- */")
    if active_flags:
        max_fn = max(
            len(flag_names[i]) if flag_names[i] else len(f"flag_{i}")
            for i in active_flags
        )
        for i in active_flags:
            name = flag_names[i] or f"flag_{i}"
            define = f"GAME_FLAG_{i}"
            pad = " " * (max_fn + 2 - len(name))
            lines.append(f"#define {define}  {i}   /* {name}{pad}*/")
    else:
        lines.append("/* (no flags defined or referenced) */")

    lines.append("")

    # --- Variables section ---
    lines.append("/* ---- Persistent variables (s_ngpng_vars[i]) ---- */")
    if active_vars:
        max_vn = max(
            len(var_names[i]) if var_names[i] else len(f"var_{i}")
            for i in active_vars
        )
        for i in active_vars:
            name = var_names[i] or f"var_{i}"
            define = f"GAME_VAR_{i}"
            pad = " " * (max_vn - len(name))
            lines.append(f"#define {define}   {i}   /* {name}{pad} (init: {var_inits[i]}) */")
    else:
        lines.append("/* (no variables defined or referenced) */")

    # Init array — always [8] for runtime ABI compatibility
    inits_csv = ", ".join(str(v) for v in var_inits)
    lines += [
        "",
        f"static const u8 g_game_var_inits[{_COUNT}] = {{ {inits_csv} }};",
        "",
        "#endif /* NGPC_GAME_VARS_GEN_H */",
        "",
    ]
    return "\n".join(lines)


def write_game_vars_h(*, project_data: dict, export_dir: Path) -> Path:
    """Write ``ngpc_game_vars.h`` to *export_dir*. Returns the written path."""
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    content = make_game_vars_h(project_data=project_data)
    out = export_dir / _OUTPUT_FILENAME
    out.write_text(content, encoding="utf-8")
    return out
