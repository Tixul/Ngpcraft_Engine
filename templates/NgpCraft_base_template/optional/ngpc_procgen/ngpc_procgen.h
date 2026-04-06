#ifndef NGPC_PROCGEN_H
#define NGPC_PROCGEN_H

/*
 * ngpc_procgen -- Procedural dungeon generator (Dicing Knight style)
 * ==================================================================
 * Generates a map of rooms connected by doors on a 2D grid.
 * Each room occupies exactly one NGPC screen (20x19 tiles, 160x152 px).
 * Navigation via N/S/E/W doors -- no intra-room scrolling.
 *
 * Algorithm: DFS recursive backtracker on PROCGEN_GRID_W x GRID_H grid.
 *   - Guarantees a fully connected dungeon (spanning tree).
 *   - PROCGEN_MAX_ACTIVE < GRID_W*GRID_H -> gaps in the grid (more organic).
 *   - The room farthest from start (BFS) becomes the exit.
 *
 * Reproducibility: same seed -> same dungeon (useful for fixed levels).
 * Hardware seed:   ngpc_rng_init_vbl -> random dungeon each run.
 *
 * ---------------------------------------------------------------------------
 * Dependencies: ngpc_rng
 * Installation:
 *   Copy ngpc_rng/ and ngpc_procgen/ into src/
 *   OBJS += src/ngpc_rng/ngpc_rng.rel src/ngpc_procgen/ngpc_procgen.rel
 *   #include "ngpc_procgen/ngpc_procgen.h"
 * ---------------------------------------------------------------------------
 *
 * Minimal usage:
 *
 *   ProcgenMap dungeon;
 *   ngpc_procgen_generate(&dungeon, g_templates, TEMPLATE_COUNT, 0x4A2B);
 *   ngpc_procgen_load_room(&dungeon, dungeon.start_idx,
 *                          g_templates, my_load_callback, 0xFF, NULL);
 *
 * Room navigation:
 *
 *   u8 next = ngpc_procgen_neighbor(&dungeon, dungeon.current_idx, PROCGEN_DIR_E);
 *   if (next != 0xFF) {
 *       ngpc_procgen_load_room(&dungeon, next, g_templates,
 *                              my_load_callback, PROCGEN_DIR_E, NULL);
 *       u8 sx, sy;
 *       ngpc_procgen_spawn_pos(PROCGEN_DIR_E, &sx, &sy);
 *       player.x = (s16)sx * 8;
 *       player.y = (s16)sy * 8;
 *   }
 */

#include "ngpc_hw.h"           /* u8, u16, u32, s8 */
#include "ngpc_rng/ngpc_rng.h" /* NgpcRng */

/* ── Configuration (can be overridden before the include) ────────────── */

#ifndef PROCGEN_GRID_W
#define PROCGEN_GRID_W   4   /* grid columns */
#endif
#ifndef PROCGEN_GRID_H
#define PROCGEN_GRID_H   4   /* grid rows */
#endif
#ifndef PROCGEN_MAX_ROOMS
#define PROCGEN_MAX_ROOMS   ((u8)(PROCGEN_GRID_W * PROCGEN_GRID_H))
#endif
/* Rooms actually generated. < MAX_ROOMS -> non-full grid. */
#ifndef PROCGEN_MAX_ACTIVE
#define PROCGEN_MAX_ACTIVE  12
#endif
/* Maximum size of the user template array. */
#ifndef PROCGEN_MAX_TEMPLATES
#define PROCGEN_MAX_TEMPLATES  16
#endif

/* ── NGPC screen dimensions and door positions ───────────────────────── */

#define PROCGEN_SCREEN_W   20  /* visible tiles horizontally (160 px) */
#define PROCGEN_SCREEN_H   19  /* visible tiles vertically   (152 px) */

/* North and South doors: 2 tiles wide, centered on cols 9..10 */
#define PROCGEN_DOOR_COL   9   /* first column of N/S door */
#define PROCGEN_DOOR_W     2   /* N/S door width in tiles  */

/* West and East doors: 3 tiles tall, centered on rows 8..10 */
#define PROCGEN_DOOR_ROW   8   /* first row of E/W door    */
#define PROCGEN_DOOR_H     3   /* E/W door height in tiles */

/* ── Directions (indices 0..3) ───────────────────────────────────────── */

#define PROCGEN_DIR_N   0u
#define PROCGEN_DIR_S   1u
#define PROCGEN_DIR_W   2u
#define PROCGEN_DIR_E   3u

/* Exit bitmasks (combinable with |) */
#define PROCGEN_EXIT_N   0x01u
#define PROCGEN_EXIT_S   0x02u
#define PROCGEN_EXIT_W   0x04u
#define PROCGEN_EXIT_E   0x08u
#define PROCGEN_EXIT_ALL 0x0Fu

/* ── Room types ──────────────────────────────────────────────────────── */

#define PROCGEN_ROOM_NONE    0u  /* empty cell in the grid       */
#define PROCGEN_ROOM_NORMAL  1u  /* ordinary room                */
#define PROCGEN_ROOM_START   2u  /* player starting point        */
#define PROCGEN_ROOM_EXIT    3u  /* level exit (farthest room)   */
#define PROCGEN_ROOM_SHOP    4u  /* shop (assign manually)       */
#define PROCGEN_ROOM_SECRET  5u  /* secret room                  */

/* ── Runtime flags (bitfield in ProcgenCell.flags) ───────────────────── */

#define PROCGEN_FLAG_VISITED  0x01u  /* player has entered at least once */
#define PROCGEN_FLAG_CLEARED  0x02u  /* all enemies defeated              */
#define PROCGEN_FLAG_LOCKED   0x04u  /* doors temporarily locked          */

/* ── Sentinel value ──────────────────────────────────────────────────── */

#define PROCGEN_IDX_NONE  0xFFu  /* invalid index (out of grid, no neighbor) */

/* ── Structures ──────────────────────────────────────────────────────── */

/*
 * NgpcRoomTemplate: room template metadata.
 * No pointers -- safe in far ROM without NGP_FAR in the struct.
 * Actual graphic data (tiles, maps) is handled by the load callback.
 */
typedef struct {
    u8 exits_mask; /* PROCGEN_EXIT_* combination this template supports */
    u8 variant;    /* graphic variant index (0 = default, 1+ = variants) */
} NgpcRoomTemplate;

/*
 * ProcgenCell: one cell in the grid (4 bytes, compact).
 * template_id and exits are set by ngpc_procgen_generate.
 * flags are modified by the game at runtime.
 */
typedef struct {
    u8 template_id; /* index into the NgpcRoomTemplate[] array provided */
    u8 exits;       /* doors actually open = PROCGEN_EXIT_* combined     */
    u8 room_type;   /* PROCGEN_ROOM_*                                    */
    u8 flags;       /* PROCGEN_FLAG_* (runtime, initialized to 0)        */
} ProcgenCell;

/*
 * ProcgenMap: complete level map.
 * Total size: 16 x 4 + 8 = 72 bytes in RAM.
 * cells[] is indexed by procgen_cell_idx(x, y).
 * Inactive cells have room_type == PROCGEN_ROOM_NONE.
 */
typedef struct {
    ProcgenCell cells[PROCGEN_MAX_ROOMS]; /* GRID_W x GRID_H grid */
    u8 start_idx;   /* index of the starting room  */
    u8 exit_idx;    /* index of the exit room      */
    u8 room_count;  /* number of active rooms      */
    u8 current_idx; /* index of the current room   */
    u8 seed_hi;     /* high byte of generation seed */
    u8 seed_lo;     /* low byte  of generation seed */
    u8 _pad[2];     /* 4-byte alignment padding    */
} ProcgenMap;

/*
 * ProcgenLoadFn: callback invoked by ngpc_procgen_load_room to load
 * and display the room on screen.
 *
 *   cell      : cell data (exits, room_type, flags, template_id)
 *   tpl       : template selected by the generator
 *   entry_dir : direction FROM which the player arrives (PROCGEN_DIR_*)
 *               0xFF (PROCGEN_IDX_NONE) = initial load (starting room)
 *   userdata  : free pointer passed through from ngpc_procgen_load_room
 */
typedef void (*ProcgenLoadFn)(
    const ProcgenCell              *cell,
    const NgpcRoomTemplate NGP_FAR *tpl,
    u8                              entry_dir,
    void                           *userdata
);

/* ── Utility macros ──────────────────────────────────────────────────── */

/* X coordinate (column) of a cell by its index */
#define procgen_cell_x(idx)       ((u8)((idx) % PROCGEN_GRID_W))
/* Y coordinate (row) of a cell by its index */
#define procgen_cell_y(idx)       ((u8)((idx) / PROCGEN_GRID_W))
/* Index of a cell from its coordinates (x, y) */
#define procgen_cell_idx(x, y)    ((u8)((u8)(y) * (u8)PROCGEN_GRID_W + (u8)(x)))
/* 1 if the cell is an active room (not NONE) */
#define procgen_cell_active(map, idx) \
    ((map)->cells[(idx)].room_type != PROCGEN_ROOM_NONE)

/* ── Public API ──────────────────────────────────────────────────────── */

/*
 * Generate a new dungeon and fill map.
 *
 *   map       : ProcgenMap to fill (result)
 *   templates : template array in ROM (far pointer)
 *   tpl_count : number of templates (<= PROCGEN_MAX_TEMPLATES)
 *   seed      : generation seed (same seed = same dungeon)
 *
 * After the call:
 *   map->start_idx  = starting room
 *   map->exit_idx   = farthest room -> level exit
 *   map->room_count = number of active rooms
 *   map->current_idx = 0 (not loaded)
 */
void ngpc_procgen_generate(
    ProcgenMap                     *map,
    const NgpcRoomTemplate NGP_FAR *templates,
    u8                              tpl_count,
    u16                             seed
);

/*
 * Load and display a room. Updates map->current_idx.
 * Marks the cell as PROCGEN_FLAG_VISITED.
 * Calls load_fn for rendering (immediate, synchronous).
 *
 *   idx       : index of the room to load
 *   templates : same array passed to ngpc_procgen_generate
 *   load_fn   : render callback (may be NULL for silent navigation)
 *   entry_dir : PROCGEN_DIR_* from which the player arrives,
 *               or PROCGEN_IDX_NONE (0xFF) for the initial load
 *   userdata  : arbitrary data forwarded to load_fn
 */
void ngpc_procgen_load_room(
    ProcgenMap                     *map,
    u8                              idx,
    const NgpcRoomTemplate NGP_FAR *templates,
    ProcgenLoadFn                   load_fn,
    u8                              entry_dir,
    void                           *userdata
);

/*
 * Return the index of the neighboring room in direction dir.
 * Returns PROCGEN_IDX_NONE (0xFF) if:
 *   - no exit in that direction
 *   - grid boundary
 */
u8 ngpc_procgen_neighbor(const ProcgenMap *map, u8 room_idx, u8 dir);

/*
 * Compute the player spawn position on entering a room.
 * entry_dir: direction FROM which the player arrives.
 *   PROCGEN_DIR_N -> spawn near top    (after North door)
 *   PROCGEN_DIR_S -> spawn near bottom
 *   PROCGEN_DIR_W -> spawn near left
 *   PROCGEN_DIR_E -> spawn near right
 *   0xFF          -> spawn at center
 * out_x, out_y: tile coordinates (multiply by 8 for pixels).
 */
void ngpc_procgen_spawn_pos(u8 entry_dir, u8 *out_x, u8 *out_y);

/*
 * Compute a reproducible 16-bit seed unique to a room.
 * Useful for placing enemies/items deterministically per room.
 * Example:
 *   NgpcRng room_rng;
 *   ngpc_rng_init(&room_rng, ngpc_procgen_room_seed(&dungeon, idx));
 *   nb_enemies = ngpc_rng_range(&room_rng, 1, 4);
 */
u16 ngpc_procgen_room_seed(const ProcgenMap *map, u8 room_idx);

/*
 * Select the best template for a given exits mask.
 * Randomly picks among all compatible templates
 * (template exits_mask must contain all required exits).
 * Returns 0 if no compatible template (fallback to template 0).
 *
 *   rng       : local RNG (advanced as needed)
 *   exits_req : required exits (PROCGEN_EXIT_* combined)
 *   templates : template array
 *   count     : number of templates
 */
u8 ngpc_procgen_pick_template(
    NgpcRng                        *rng,
    u8                              exits_req,
    const NgpcRoomTemplate NGP_FAR *templates,
    u8                              count
);

/* ── Procedural room content ─────────────────────────────────────────── */

/*
 * ProcgenContent: entities and data for a room generated procedurally.
 * Parallel array to ProcgenMap.cells[], indexed the same way.
 * The game allocates this array and passes it to ngpc_procgen_gen_content().
 *
 * Each field is a free bitmask: the game defines the meaning of the bits.
 *   enemies : bitmask of enemy types present (bit 0 = type A, bit 1 = B...)
 *   items   : bitmask of items present      (bit 0 = key, bit 1 = potion...)
 *   count   : total number of enemies to spawn (0..8)
 *   special : room-specific data (0 = none, 1..15 = event id, key, etc.)
 *
 * Example:
 *   ProcgenContent content[PROCGEN_MAX_ROOMS];
 *   ngpc_procgen_gen_content(&map, content, 3, 40);
 *   if (content[idx].enemies & 0x01) spawn_slime(x, y);
 *   if (content[idx].items   & 0x01) spawn_key(cx, cy);
 */
typedef struct {
    u8 enemies; /* enemy type bitmask (game-defined, max 8 types) */
    u8 items;   /* item bitmask       (game-defined, max 8 types) */
    u8 count;   /* enemies to spawn (0..8)                        */
    u8 special; /* special data: 0=none, 1-15=event/key/boss id   */
} ProcgenContent;

/*
 * Generate a dungeon with optional loop injection.
 * Replaces ngpc_procgen_generate() for new projects.
 *
 *   loop_pct : 0  = no loops (identical behavior to generate)
 *              15 = ~15% of possible shortcuts added
 *              30 = very open dungeon, less maze-like
 *
 * After the call, map is ready and templates are assigned.
 */
void ngpc_procgen_generate_ex(
    ProcgenMap                     *map,
    const NgpcRoomTemplate NGP_FAR *templates,
    u8                              tpl_count,
    u16                             seed,
    u8                              loop_pct
);

/*
 * Generate procedural content (enemies, items, events) for all active rooms.
 * Result is deterministic from map->seed.
 *
 *   content     : array [PROCGEN_MAX_ROOMS] provided by the caller
 *   max_enemies : max enemies per normal room (1..8, recommended: 1..4)
 *   item_chance : % chance a NORMAL room contains an item (0..100)
 *
 * Rules applied:
 *   - Room START  -> count=0, items=0, special=0
 *   - Room EXIT   -> count=max_enemies, enemies=0xFF, special=1 (boss flag)
 *   - Room SHOP   -> count=0, items=0xFF, special=2 (shop flag)
 *   - Room SECRET -> count=1, items=0xFF, special=3 (secret flag)
 *   - Room NORMAL -> count=rng(1..max_enemies), random enemies and items
 *   - Room CLEARED-> count=0 (already cleared, PROCGEN_FLAG_CLEARED set)
 */
void ngpc_procgen_gen_content(
    const ProcgenMap *map,
    ProcgenContent   *content,
    u8                max_enemies,
    u8                item_chance
);

#endif /* NGPC_PROCGEN_H */
