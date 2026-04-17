"""
core/procgen_config_gen.py — Generate procgen_config.h and cavegen_config.h
from scene rt_dfs_params / rt_cave_params stored in .ngpcraft JSON.

These headers are read at compile time by ngpc_procgen.h and ngpc_cavegen.h
to configure the runtime dungeon/cave generators without hand-editing C.

Scene data format (in .ngpcraft scenes[]):
    {
        "rt_dfs_params": {
            "grid_w":      4,
            "grid_h":      4,
            "max_enemies": 4,
            "item_chance": 25,
            "loop_pct":    20,
            "max_active":  8,
            "start_mode":  "corner",   # corner | random | far_exit
            "multifloor":  false,
            "floor_var":   0,
            "max_floors":  0,
            "boss_scene":  "",
            "loop_scene":  "",
            "tier_table":  [[2,3,4,5,6], [30,25,20,15,10], [10,15,20,25,30], [4,6,8,10,12]]
        },
        "rt_cave_params": {
            "wall_pct":    45,
            "iterations":  5,
            "max_enemies": 6,
            "max_chests":  2,
            "multifloor":  false,
            "floor_var":   0,
            "max_floors":  0,
            "boss_scene":  "",
            "tier_table":  [[45,47,50,52,55], [3,4,6,8,10], [3,2,2,1,1]]
        }
    }

Generated output — procgen_config.h:
    #define PROCGEN_GRID_W          4
    #define PROCGEN_GRID_H          4
    #define PROCGEN_MAX_ENEMIES     4
    ...
    #define PROCGEN_TIER_MAX_ENEMIES    {2, 3, 4, 5, 6}
    ...

Usage:
    from core.procgen_config_gen import write_procgen_config_h, write_cavegen_config_h
    write_procgen_config_h(scene=scene_dict, export_dir=Path("GraphX/gen"))
    write_cavegen_config_h(scene=scene_dict, export_dir=Path("GraphX/gen"))
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.dungeongen_cells import normalize_dungeongen_runtime_cells, parse_dungeongen_cell_size

_DFS_FILENAME  = "procgen_config.h"
_CAVE_FILENAME = "cavegen_config.h"

_START_MODE_MAP = {"corner": 0, "random": 1, "far_exit": 2}

_DFS_TIER_DEFAULTS = [
    [2, 3, 4, 5, 6],       # max_enemies
    [30, 25, 20, 15, 10],  # item_chance
    [10, 15, 20, 25, 30],  # loop_pct
    [4, 6, 8, 10, 12],     # max_active
]

_CAVE_TIER_DEFAULTS = [
    [45, 47, 50, 52, 55],  # wall_pct
    [3, 4, 6, 8, 10],      # max_enemies
    [3, 2, 2, 1, 1],       # max_items
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _arr(vals: list[int]) -> str:
    """Format an int list as a C initialiser array."""
    return "{" + ", ".join(str(v) for v in vals) + "}"


def _read_tier_row(tier_table: list, row: int, ncols: int = 5,
                   default: list[int] | None = None) -> list[int]:
    """Extract one row from a tier table, with safe fallback."""
    if default is None:
        default = [0] * ncols
    try:
        row_data = tier_table[row]
        result = []
        for c in range(ncols):
            try:
                result.append(_int(row_data[c]))
            except (IndexError, TypeError):
                result.append(default[c] if c < len(default) else 0)
        return result
    except (IndexError, TypeError):
        return list(default[:ncols]) if default else [0] * ncols


# ---------------------------------------------------------------------------
# DFS / Dungeon procgen
# ---------------------------------------------------------------------------

def make_procgen_config_h(*, scene: dict) -> str:
    """Return the full content of procgen_config.h as a string.

    Reads ``scene["rt_dfs_params"]``; falls back to sensible defaults
    so the generated header is always syntactically valid even for older
    scenes that pre-date the DFS sub-tab.
    """
    dp: dict = {}
    raw = scene.get("rt_dfs_params") if isinstance(scene, dict) else None
    if isinstance(raw, dict):
        dp = raw

    grid_w          = _int(dp.get("grid_w"),           4)
    grid_h          = _int(dp.get("grid_h"),           4)
    room_w          = max(20, min(32, _int(dp.get("room_w"),          20)))
    room_h          = max(19, min(32, _int(dp.get("room_h"),          19)))
    max_enemies     = _int(dp.get("max_enemies"),      4)
    item_chance     = _int(dp.get("item_chance"),     25)
    loop_pct        = _int(dp.get("loop_pct"),        20)
    max_active      = _int(dp.get("max_active"),       8)
    start_mode      = _START_MODE_MAP.get(
        str(dp.get("start_mode") or "corner"), 0)
    multifloor      = bool(dp.get("multifloor", False))
    floor_var       = _int(dp.get("floor_var"),        0)
    max_floors      = _int(dp.get("max_floors"),       0)
    boss_scene      = str(dp.get("boss_scene") or "").strip()
    tier_count      = max(1, min(5, _int(dp.get("tier_count"),      5)))
    floors_per_tier = max(1,        _int(dp.get("floors_per_tier"), 5))

    # Tier table — 4 rows × tier_count cols
    tier_table = dp.get("tier_table")
    if not isinstance(tier_table, list) or len(tier_table) < 4:
        tier_table = _DFS_TIER_DEFAULTS

    t_enemies = _read_tier_row(tier_table, 0, tier_count, _DFS_TIER_DEFAULTS[0])
    t_items   = _read_tier_row(tier_table, 1, tier_count, _DFS_TIER_DEFAULTS[1])
    t_loop    = _read_tier_row(tier_table, 2, tier_count, _DFS_TIER_DEFAULTS[2])
    t_active  = _read_tier_row(tier_table, 3, tier_count, _DFS_TIER_DEFAULTS[3])

    lines = [
        "/* procgen_config.h — auto-generated by NgpCraft Engine */",
        "/* DO NOT EDIT — re-export from Level > Procgen > Dungeon DFS */",
        "#ifndef PROCGEN_CONFIG_H",
        "#define PROCGEN_CONFIG_H",
        "",
        f"#define PROCGEN_GRID_W          {grid_w}u",
        f"#define PROCGEN_GRID_H          {grid_h}u",
        f"#define PROCGEN_ROOM_W          {room_w}u",
        f"#define PROCGEN_ROOM_H          {room_h}u",
        f"#define PROCGEN_MAX_ENEMIES     {max_enemies}u",
        f"#define PROCGEN_ITEM_CHANCE     {item_chance}u",
        f"#define PROCGEN_LOOP_PCT        {loop_pct}u",
        f"#define PROCGEN_MAX_ACTIVE      {max_active}u",
        f"#define PROCGEN_START_MODE      {start_mode}u",
        f"#define PROCGEN_MULTIFLOOR      {1 if multifloor else 0}u",
        f"#define PROCGEN_FLOOR_VAR       {floor_var}u",
        f"#define PROCGEN_MAX_FLOORS      {max_floors}u",
        f"#define PROCGEN_TIER_COUNT      {tier_count}u",
        f"#define PROCGEN_FLOORS_PER_TIER {floors_per_tier}u",
        "",
        f"/* Tier table — index by (game_var[PROCGEN_FLOOR_VAR] / PROCGEN_FLOORS_PER_TIER), clamped to PROCGEN_TIER_COUNT-1 */",
        f"#define PROCGEN_TIER_MAX_ENEMIES    {_arr(t_enemies)}",
        f"#define PROCGEN_TIER_ITEM_CHANCE    {_arr(t_items)}",
        f"#define PROCGEN_TIER_LOOP_PCT       {_arr(t_loop)}",
        f"#define PROCGEN_TIER_MAX_ACTIVE     {_arr(t_active)}",
    ]

    if multifloor and boss_scene:
        lines += [
            "",
            "/* Boss/end scene ID — use with ngpc_goto_scene() */",
            f'#define PROCGEN_BOSS_SCENE_ID   "{boss_scene}"',
        ]

    lines += ["", "#endif /* PROCGEN_CONFIG_H */", ""]
    return "\n".join(lines)


def write_procgen_config_h(*, scene: dict, export_dir: Path) -> Path:
    """Write ``procgen_config.h`` to *export_dir*. Returns the written path."""
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    content = make_procgen_config_h(scene=scene)
    out = export_dir / _DFS_FILENAME
    out.write_text(content, encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Cave / cellular automaton
# ---------------------------------------------------------------------------

def make_cavegen_config_h(*, scene: dict, project_data: dict | None = None) -> str:
    """Return the full content of cavegen_config.h as a string."""
    cp: dict = {}
    raw = scene.get("rt_cave_params") if isinstance(scene, dict) else None
    if isinstance(raw, dict):
        cp = raw

    wall_pct        = _int(cp.get("wall_pct"),         45)
    iterations      = _int(cp.get("iterations"),        5)
    max_enemies     = _int(cp.get("max_enemies"),       6)
    max_items       = _int(cp.get("max_items", cp.get("max_chests", 2)), 2)
    pickup_type     = _int(cp.get("pickup_type"),       0)
    multifloor      = bool(cp.get("multifloor", False))
    floor_var       = _int(cp.get("floor_var"),         0)
    max_floors      = _int(cp.get("max_floors"),        0)
    boss_scene      = str(cp.get("boss_scene") or "").strip()
    tier_count      = max(1, min(5, _int(cp.get("tier_count"),      5)))
    floors_per_tier = max(1,        _int(cp.get("floors_per_tier"), 5))

    # Tier table — 3 rows × tier_count cols
    tier_table = cp.get("tier_table")
    if not isinstance(tier_table, list) or len(tier_table) < 3:
        tier_table = _CAVE_TIER_DEFAULTS

    t_wall    = _read_tier_row(tier_table, 0, tier_count, _CAVE_TIER_DEFAULTS[0])
    t_enemies = _read_tier_row(tier_table, 1, tier_count, _CAVE_TIER_DEFAULTS[1])
    t_items   = _read_tier_row(tier_table, 2, tier_count, _CAVE_TIER_DEFAULTS[2])

    lines = [
        "/* cavegen_config.h — auto-generated by NgpCraft Engine */",
        "/* DO NOT EDIT — re-export from Level > Procgen > Cave */",
        "#ifndef CAVEGEN_CONFIG_H",
        "#define CAVEGEN_CONFIG_H",
        "",
        f"#define CAVEGEN_WALL_PCT         {wall_pct}u",
        f"#define CAVEGEN_ITERATIONS       {iterations}u",
        f"#define CAVEGEN_MAX_ENEMIES      {max_enemies}u",
        f"#define CAVEGEN_MAX_ITEMS        {max_items}u",
        f"#define CAVEGEN_PICKUP_TYPE      {pickup_type}u",
        f"#define CAVEGEN_MULTIFLOOR       {1 if multifloor else 0}u",
        f"#define CAVEGEN_FLOOR_VAR        {floor_var}u",
        f"#define CAVEGEN_MAX_FLOORS       {max_floors}u",
        f"#define CAVEGEN_TIER_COUNT       {tier_count}u",
        f"#define CAVEGEN_FLOORS_PER_TIER  {floors_per_tier}u",
        "",
        f"/* Tier table — index by (game_var[CAVEGEN_FLOOR_VAR] / CAVEGEN_FLOORS_PER_TIER), clamped to CAVEGEN_TIER_COUNT-1 */",
        f"#define CAVEGEN_TIER_WALL_PCT       {_arr(t_wall)}",
        f"#define CAVEGEN_TIER_MAX_ENEMIES    {_arr(t_enemies)}",
        f"#define CAVEGEN_TIER_MAX_ITEMS      {_arr(t_items)}",
    ]

    # Item pool — resolve names to indices
    pool_names: list[str] = [str(n) for n in (cp.get("item_pool") or []) if n]
    item_table: list[dict] = []
    if isinstance(project_data, dict):
        item_table = project_data.get("item_table", []) or []
        if not isinstance(item_table, list):
            item_table = []
    pool_indices: list[int] = []
    for name in pool_names:
        idx = next(
            (i for i, it in enumerate(item_table)
             if isinstance(it, dict) and str(it.get("name", "") or "").strip() == name),
            None,
        )
        if idx is not None:
            pool_indices.append(idx)
    if pool_indices:
        pool_arr = "{" + ", ".join(f"{i}u" for i in pool_indices) + "}"
        lines += [
            "",
            "/* Item pool — indices into g_item_table[] eligible for chest drops */",
            f"#define CAVEGEN_ITEM_POOL_SIZE   {len(pool_indices)}u",
            f"static const u8 g_cavegen_item_pool[CAVEGEN_ITEM_POOL_SIZE] = {pool_arr};",
        ]
    else:
        lines += [
            "",
            "/* Item pool — empty means runtime chooses freely */",
            "#define CAVEGEN_ITEM_POOL_SIZE   0u",
        ]

    if multifloor and boss_scene:
        lines += [
            "",
            "/* Boss/end scene ID — use with ngpc_goto_scene() */",
            f'#define CAVEGEN_BOSS_SCENE_ID   "{boss_scene}"',
        ]

    lines += ["", "#endif /* CAVEGEN_CONFIG_H */", ""]
    return "\n".join(lines)


def write_cavegen_config_h(*, scene: dict, export_dir: Path, project_data: dict | None = None) -> Path:
    """Write ``cavegen_config.h`` to *export_dir*. Returns the written path."""
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    content = make_cavegen_config_h(scene=scene, project_data=project_data)
    out = export_dir / _CAVE_FILENAME
    out.write_text(content, encoding="utf-8")
    return out



# DungeonGen / ngpc_dungeongen (scrollable metatile rooms)
# ---------------------------------------------------------------------------

_DUNGEONGEN_FILENAME = "dungeongen_config.h"

_DUNGEONGEN_DEFAULTS: dict = {
    "ground_pct_1":   70,
    "ground_pct_2":   20,
    "ground_pct_3":   10,
    "eau_freq":       40,
    "vide_freq":      30,
    "vide_margin":     3,
    "tonneau_freq":   50,
    "tonneau_max":     2,
    "escalier_freq":   0,
    "enemy_min":       0,
    "enemy_max":       3,
    "enemy_density":  16,
    "ene2_pct":       50,
    "item_freq":      50,
    "n_rooms":         0,
    "enemy_ramp_rooms": 0,
    "safe_room_every":  0,
    "min_exits":          0,
    "cluster_size_max":   4,
    "tier_cols":          0,
    "tier_ene_max":    [],
    "tier_item_freq":  [],
    "tier_eau_freq":   [],
    "tier_vide_freq":  [],
    "room_mw_min":    10,
    "room_mw_max":    16,
    "room_mh_min":    10,
    "room_mh_max":    16,
    "max_exits":       4,
    "cell_w_tiles":    2,
    "cell_h_tiles":    2,
    "multifloor":  False,
    "floor_var":       0,
    "max_floors":      0,
    "boss_scene":     "",
    "water_behavior": "water",
    "void_behavior":  "death",
    "void_damage":     0,
    "void_scene":     "",
}


def make_dungeongen_config_h(*, scene: dict, project_data: dict | None = None) -> str:
    """Return the full content of dungeongen_config.h as a string.

    Reads ``scene["rt_dungeongen_params"]``; falls back to sensible defaults.
    All values are emitted as ``#define DUNGEONGEN_*`` overrides that are read
    by the ``#ifndef`` guards in ngpc_dungeongen.h before it sets its own defaults.
    Include this header BEFORE including ngpc_dungeongen.h.
    """
    dp: dict = {}
    raw = scene.get("rt_dungeongen_params") if isinstance(scene, dict) else None
    if isinstance(raw, dict):
        dp = raw

    def _g(key: str) -> Any:
        val = dp.get(key)
        return val if val is not None else _DUNGEONGEN_DEFAULTS[key]

    procgen_assets = (project_data.get("procgen_assets") or {}) if isinstance(project_data, dict) else {}
    dgen_assets = (procgen_assets.get("dungeongen") or {}) if isinstance(procgen_assets, dict) else {}
    tile_roles = (dgen_assets.get("tile_roles") or {}) if isinstance(dgen_assets, dict) else {}
    src_cw, src_ch = parse_dungeongen_cell_size(
        dgen_assets.get("cell_size", "16x16") if isinstance(dgen_assets, dict) else "16x16"
    )

    ground_pct_1   = _int(_g("ground_pct_1"),  70)
    ground_pct_2   = _int(_g("ground_pct_2"),  20)
    ground_pct_3   = _int(_g("ground_pct_3"),  10)
    # Clamp so sum == 100 (adjust pct_3 silently)
    total = ground_pct_1 + ground_pct_2
    ground_pct_3   = max(0, 100 - total)

    eau_freq       = _int(_g("eau_freq"),       40)
    vide_freq      = _int(_g("vide_freq"),      30)
    vide_margin    = _int(_g("vide_margin"),     3)
    tonneau_freq   = _int(_g("tonneau_freq"),   50)

    def _role_assigned(key: str) -> bool:
        v = tile_roles.get(key)
        return bool(v) if isinstance(v, list) else (v is not None)

    if not _role_assigned("water"):
        eau_freq = 0
    if not _role_assigned("void"):
        vide_freq = 0
    if not _role_assigned("deco_a"):
        tonneau_freq = 0
    tonneau_max    = max(1, min(2, _int(_g("tonneau_max"), 2)))
    escalier_freq  = _int(_g("escalier_freq"),   0)
    enemy_min      = _int(_g("enemy_min"),       0)
    enemy_max      = max(enemy_min, _int(_g("enemy_max"), 3))
    enemy_density  = max(1, _int(_g("enemy_density"), 16))
    ene2_pct       = max(0, min(100, _int(_g("ene2_pct"), 50)))
    item_freq      = _int(_g("item_freq"),      50)
    n_rooms           = max(0, _int(_g("n_rooms"), 0))
    enemy_ramp_rooms  = max(0, _int(_g("enemy_ramp_rooms"), 0))
    safe_room_every   = max(0, _int(_g("safe_room_every"), 0))
    min_exits         = max(0, min(4, _int(_g("min_exits"), 0)))
    cluster_size_max  = max(2, min(4, _int(_g("cluster_size_max"), 4)))
    tier_cols         = max(0, _int(_g("tier_cols"), 0))

    def _row(key: str, n: int, default_val: int) -> list[int]:
        raw_row = _g(key)
        if isinstance(raw_row, list) and raw_row:
            vals = [max(0, int(v)) for v in raw_row]
            while len(vals) < n:
                vals.append(default_val)
            return vals[:n]
        return [default_val] * n

    tier_ene_max   = _row("tier_ene_max",   tier_cols, enemy_max) if tier_cols else []
    tier_item_freq = _row("tier_item_freq", tier_cols, item_freq) if tier_cols else []
    tier_eau_freq  = _row("tier_eau_freq",  tier_cols, eau_freq)  if tier_cols else []
    tier_vide_freq = _row("tier_vide_freq", tier_cols, vide_freq) if tier_cols else []
    if tier_ene_max:
        enemy_max = max(enemy_max, max(tier_ene_max))

    _max_room_w    = max(4, 32 // max(1, src_cw))
    _max_room_h    = max(4, 32 // max(1, src_ch))
    room_mw_max    = max(4, min(_max_room_w, _int(_g("room_mw_max"), 16)))
    room_mw_min    = max(4, min(room_mw_max, _int(_g("room_mw_min"), 10)))
    room_mh_max    = max(4, min(_max_room_h, _int(_g("room_mh_max"), 16)))
    room_mh_min    = max(4, min(room_mh_max, _int(_g("room_mh_min"), 10)))
    max_exits      = max(0, min(4, _int(_g("max_exits"), 4)))
    cell_w_tiles, cell_h_tiles, cell_reason = normalize_dungeongen_runtime_cells(
        source_cell_w_tiles=src_cw,
        source_cell_h_tiles=src_ch,
        requested_cell_w_tiles=_int(_g("cell_w_tiles"), 2),
        requested_cell_h_tiles=_int(_g("cell_h_tiles"), 2),
        tile_roles=tile_roles if isinstance(tile_roles, dict) else {},
    )
    multifloor     = bool(_g("multifloor"))
    floor_var      = max(0, min(7, _int(_g("floor_var"), 0)))
    max_floors     = _int(_g("max_floors"), 0)
    boss_scene     = str(_g("boss_scene") or "").strip()

    _WATER_COL_MAP = {
        "pass":  "DGNCOL_PASS",
        "water": "DGNCOL_WATER",
        "solid": "DGNCOL_SOLID",
        "death": "DGNCOL_VOID",
    }
    water_behavior  = str(_g("water_behavior") or "water")
    water_col_def   = _WATER_COL_MAP.get(water_behavior, "DGNCOL_WATER")
    _VOID_BEH_MAP   = {"death": 0, "floor": 1, "scene": 2}
    void_behavior   = str(_g("void_behavior") or "death")
    void_behavior_n = _VOID_BEH_MAP.get(void_behavior, 0)
    void_damage     = max(0, min(255, _int(_g("void_damage"), 0)))
    void_scene      = str(_g("void_scene") or "").strip()

    lines = [
        "/* dungeongen_config.h — auto-generated by NgpCraft Engine */",
        "/* DO NOT EDIT — re-export from Level > Procgen > DungeonGen */",
        "/* Include this header BEFORE #include \"ngpc_dungeongen/ngpc_dungeongen.h\" */",
        "#ifndef DUNGEONGEN_CONFIG_H",
        "#define DUNGEONGEN_CONFIG_H",
        "",
        "/* ---- Sol : mix des 3 variantes (somme = 100) ---- */",
        f"#define DUNGEONGEN_GROUND_PCT_1    {ground_pct_1}u",
        f"#define DUNGEONGEN_GROUND_PCT_2    {ground_pct_2}u",
        f"#define DUNGEONGEN_GROUND_PCT_3    {ground_pct_3}u",
        "",
        "/* ---- Population : frequences (0=desactive, 100=systematique) ---- */",
        f"#define DUNGEONGEN_EAU_FREQ        {eau_freq}u",
        f"#define DUNGEONGEN_VIDE_FREQ       {vide_freq}u",
        f"#define DUNGEONGEN_VIDE_MARGIN     {vide_margin}u",
        f"#define DUNGEONGEN_TONNEAU_FREQ    {tonneau_freq}u",
        f"#define DUNGEONGEN_TONNEAU_MAX     {tonneau_max}u",
        f"#define DUNGEONGEN_ESCALIER_FREQ   {escalier_freq}u",
        "",
        "/* ---- Entites ---- */",
        f"#define DUNGEONGEN_ENEMY_MIN       {enemy_min}u",
        f"#define DUNGEONGEN_ENEMY_MAX       {enemy_max}u",
        f"#define DUNGEONGEN_ENEMY_DENSITY   {enemy_density}u",
        f"#define DUNGEONGEN_ENE2_PCT        {ene2_pct}u",
        f"#define DUNGEONGEN_ITEM_FREQ       {item_freq}u",
        "",
        "/* ---- Navigation (lu par le code de jeu, pas par le module) ---- */",
        f"#define DUNGEONGEN_N_ROOMS           {n_rooms}u",
        f"#define DUNGEONGEN_CLUSTER_SIZE_MAX  {cluster_size_max}u",
        "",
        "/* ---- Difficulte progressive ---- */",
        f"#define DUNGEONGEN_ENEMY_RAMP_ROOMS  {enemy_ramp_rooms}u",
        f"#define DUNGEONGEN_SAFE_ROOM_EVERY   {safe_room_every}u",
        f"#define DUNGEONGEN_MIN_EXITS         {min_exits}u",
        "",
        "/* ---- Taille des salles (cellules logiques) ---- */",
        f"#define DUNGEONGEN_ROOM_MW_MIN     {room_mw_min}u",
        f"#define DUNGEONGEN_ROOM_MW_MAX     {room_mw_max}u",
        f"#define DUNGEONGEN_ROOM_MH_MIN     {room_mh_min}u",
        f"#define DUNGEONGEN_ROOM_MH_MAX     {room_mh_max}u",
        "",
        "/* ---- Sorties et cellule ---- */",
        f"#define DUNGEONGEN_MAX_EXITS       {max_exits}u",
        f"#define DUNGEONGEN_CELL_W_TILES    {cell_w_tiles}u",
        f"#define DUNGEONGEN_CELL_H_TILES    {cell_h_tiles}u",
    ]

    if cell_reason:
        lines += ["", f"/* {cell_reason} */"]

    if tier_cols > 0:
        def _fmt_row(vals: list[int]) -> str:
            return "{ " + ", ".join(f"{v}u" for v in vals) + " }"
        lines += [
            "",
            "/* ---- Tiers de difficulte ---- */",
            f"#define DUNGEONGEN_TIER_COLS         {tier_cols}u",
            f"#define DUNGEONGEN_TIER_ENE_MAX      {_fmt_row(tier_ene_max)}",
            f"#define DUNGEONGEN_TIER_ITEM_FREQ    {_fmt_row(tier_item_freq)}",
            f"#define DUNGEONGEN_TIER_EAU_FREQ     {_fmt_row(tier_eau_freq)}",
            f"#define DUNGEONGEN_TIER_VIDE_FREQ    {_fmt_row(tier_vide_freq)}",
        ]

    lines += [
        "",
        "/* ---- Comportement eau (DGNCOL_* retourné par collision_at sur case eau) ---- */",
        f"#define DUNGEONGEN_WATER_COL       {water_col_def}",
        "",
        "/* ---- Comportement trou/fosse ---- */",
        "/* 0=mort instant, 1=etage inferieur (multifloor), 2=goto scene            */",
        "/* Dans tous les cas collision_at() retourne DGNCOL_VOID.                  */",
        "/* Ces defines sont des HINTS pour le game code — pas utilisés par le gen. */",
        f"#define DUNGEONGEN_VOID_BEHAVIOR   {void_behavior_n}u",
        f"#define DUNGEONGEN_VOID_DAMAGE     {void_damage}u",
    ]
    if void_behavior == "scene" and void_scene:
        lines.append(f'#define DUNGEONGEN_VOID_SCENE_ID   "{void_scene}"')

    if multifloor:
        lines += [
            "",
            "/* ---- Multi-floor progression ---- */",
            f"#define DUNGEONGEN_MULTIFLOOR      1u",
            f"#define DUNGEONGEN_FLOOR_VAR       {floor_var}u",
            f"#define DUNGEONGEN_MAX_FLOORS      {max_floors}u",
        ]
        if boss_scene:
            lines += [f'#define DUNGEONGEN_BOSS_SCENE_ID   "{boss_scene}"']

    lines += ["", "#endif /* DUNGEONGEN_CONFIG_H */", ""]
    return "\n".join(lines)


def write_dungeongen_config_h(*, scene: dict, export_dir: Path, project_data: dict | None = None) -> Path:
    """Write ``dungeongen_config.h`` to *export_dir*. Returns the written path."""
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    content = make_dungeongen_config_h(scene=scene, project_data=project_data)
    out = export_dir / _DUNGEONGEN_FILENAME
    out.write_text(content, encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Batch — write all for all scenes that have runtime params
# ---------------------------------------------------------------------------

def write_all_procgen_configs(*, project_data: dict, export_dir: Path) -> list[Path]:
    """Scan all scenes and write procgen_config.h, cavegen_config.h, dungeongen_config.h.

    Only the *last* scene with rt_dfs_params / rt_cave_params wins
    (the expectation is that a project uses one set of DFS params and
    one set of Cave params project-wide, not per-scene).

    Returns a list of written file paths.
    """
    export_dir = Path(export_dir)
    scenes = (project_data.get("scenes") or []) if isinstance(project_data, dict) else []

    last_dfs:        dict | None = None
    last_cave:       dict | None = None
    last_dungeongen: dict | None = None

    for sc in scenes:
        if not isinstance(sc, dict):
            continue
        dfs = sc.get("rt_dfs_params")
        if isinstance(dfs, dict) and dfs.get("enabled", False):
            last_dfs = sc
        cave = sc.get("rt_cave_params")
        if isinstance(cave, dict) and cave.get("enabled", False):
            last_cave = sc
        dgen = sc.get("rt_dungeongen_params")
        if isinstance(dgen, dict) and dgen.get("enabled", False):
            last_dungeongen = sc

    written: list[Path] = []
    if last_dfs is not None:
        written.append(write_procgen_config_h(scene=last_dfs, export_dir=export_dir))
    if last_cave is not None:
        written.append(write_cavegen_config_h(scene=last_cave, export_dir=export_dir))
    if last_dungeongen is not None:
        written.append(write_dungeongen_config_h(
            scene=last_dungeongen,
            export_dir=export_dir,
            project_data=project_data,
        ))
    return written
