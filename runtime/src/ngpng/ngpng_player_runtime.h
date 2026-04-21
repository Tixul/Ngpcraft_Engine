/* ngpng_player_runtime.h -- Stable player physics helpers.
 * Part of the ngpng static module layer (NGPC PNG Manager).
 * NOT generated -- copy this file as-is to the exported project.
 *
 * Feature gates (defined via Makefile CDEFS, auto-injected by the tool):
 *   NGPNG_HAS_LADDER   -- full ladder detection; else stubs return 0
 *   NGPNG_HAS_SPRING   -- spring tile physics in apply_tile_effects
 *   NGPNG_HAS_DOOR     -- door tile detection; else stub returns 0
 *   NGPNG_HAS_ICE      -- ice ground detection
 *   NGPNG_HAS_CONVEYOR -- conveyor belt additive vx
 *   NGPNG_HAS_WATER    -- water tile slow-down effect (halves vx/vy)
 *   NGPNG_MOVE_TOPDOWN -- enables ngpng_player_clamp_tilecol_topdown (4-dir/8-dir)
 *   NGPNG_MOVE_PLATFORM-- platformer gravity+jump mode (default when no flag set)
 *
 * Include order: ngpng_player_ctrl.h must be included before this header
 * (it defines NgpngPlayerActor). The generated ngpng_autorun_main.c
 * handles this automatically.
 */
#ifndef NGPNG_PLAYER_RUNTIME_H
#define NGPNG_PLAYER_RUNTIME_H

#include "ngpng_engine.h"      /* NgpSceneDef, tile helpers (found in same ngpng/ dir) */
#include "ngpng_player_ctrl.h" /* NgpngPlayerActor (generated per project)             */

/* Entity flags — mirror ngpng_entities.h; guarded against redefinition. */
#ifndef NGPNG_ENT_FLAG_CLAMP_MAP
#define NGPNG_ENT_FLAG_CLAMP_MAP    1u
#endif
#ifndef NGPNG_ENT_FLAG_CLAMP_CAMERA
#define NGPNG_ENT_FLAG_CLAMP_CAMERA 8u
#endif

/* Spring direction constants (used by spring_touch_side and apply_tile_effects).
 * Guarded: the generated file may also emit them when has_spring is set. */
#ifndef NGPNG_SPRING_DIR_UP
#define NGPNG_SPRING_DIR_UP             0
#define NGPNG_SPRING_DIR_DOWN           1
#define NGPNG_SPRING_DIR_LEFT           2
#define NGPNG_SPRING_DIR_RIGHT          3
#define NGPNG_SPRING_DIR_OPPOSITE_TOUCH 4
#endif

#ifndef NGPNG_SPRING_TOUCH_NONE
#define NGPNG_SPRING_TOUCH_NONE   0u
#define NGPNG_SPRING_TOUCH_TOP    1u
#define NGPNG_SPRING_TOUCH_BOTTOM 2u
#define NGPNG_SPRING_TOUCH_LEFT   3u
#define NGPNG_SPRING_TOUCH_RIGHT  4u
#endif

/* ---- World clamp helpers ---- */
void ngpng_player_clamp_world(const NgpSceneDef *sc, NgpngPlayerActor *p,
    s16 cam_px, s16 cam_py,
    s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h,
    s8 render_off_x, s8 render_off_y, u8 frame_w, u8 frame_h);

void ngpng_player_clamp_world_xy(const NgpSceneDef *sc, s16 *wx, s16 *wy,
    s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h, u8 flags);

/* Confines the actor to the 160x152 screen viewport using hitbox extents.
 * No-op when NGPNG_ENT_FLAG_CLAMP_CAMERA is not set in p->flags. */
void ngpng_player_clamp_camera(NgpngPlayerActor *p,
    s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h);

/* ---- Ladder helpers (real implementation when NGPNG_HAS_LADDER, stubs otherwise) ---- */
u8 ngpng_player_touches_ladder(const NgpSceneDef *sc,
    s16 px, s16 py, u8 frame_w, u8 frame_h);

u8 ngpng_player_find_ladder_below(const NgpSceneDef *sc,
    s16 wx, s16 wy, s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h, s16 *snap_wx);

u8 ngpng_player_try_ladder_top_exit(const NgpSceneDef *sc,
    s16 *wx, s16 *wy, s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h);

/* ---- Spring helper (stub when NGPNG_HAS_SPRING=0) ---- */
u8 ngpng_player_spring_touch_side(const NgpSceneDef *sc,
    const u8 NGP_FAR *_tc, u16 _mw, u16 _mh,
    s16 px, s16 py, s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h, s8 vx, s8 vy);

/* ---- Tile effect application (damage / fire / void / spring / conveyor) ---- */
void ngpng_player_apply_tile_effects(const NgpSceneDef *sc,
    const u8 NGP_FAR *_tc, u16 _mw, u16 _mh,
    s16 px, s16 py, s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h,
    s8 *vx, s8 *vy, u8 *on_ground, u8 *coyote, u8 *hp, u8 *invul);

/* ---- Door tile helper (stub when NGPNG_HAS_DOOR=0) ---- */
u8 ngpng_player_touches_door_tile(const NgpSceneDef *sc,
    s16 px, s16 py, s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h);

/* ---- Ice ground helper (only meaningful when NGPNG_HAS_ICE=1) ---- */
u8 ngpng_player_on_ice_ground(const NgpSceneDef *sc,
    s16 px, s16 py, s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h);

/* ---- Top-down AABB tile clamp (compiled when NGPNG_MOVE_TOPDOWN=1) ----
 * Applies vx/vy, probes corner pixels, pushes out of SOLID/WALL_* tiles.
 * Handles directional walls: WALL_N/S/E/W block only from their facing side.
 * Call after CTRL_UPDATE, before ngpng_player_clamp_world. */
#if defined(NGPNG_MOVE_TOPDOWN) && NGPNG_MOVE_TOPDOWN
void ngpng_player_clamp_tilecol_topdown(
    const u8 NGP_FAR *tc, u16 map_w, u16 map_h,
    s16 cam_px, s16 cam_py,
    s16 *actor_x, s16 *actor_y,
    s8  *vx, s8  *vy,
    s8  hb_x, s8  hb_y, u8 hb_w, u8 hb_h);
#endif /* NGPNG_MOVE_TOPDOWN */

#endif /* NGPNG_PLAYER_RUNTIME_H */
