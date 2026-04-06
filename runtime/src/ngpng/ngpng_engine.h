/* ngpng_engine.h -- Camera, scroll, region helpers.
 * Part of the ngpng static module layer (NGPC PNG Manager).
 * Overwritten on next export -- do not hand-edit.
 */
#ifndef NGPNG_ENGINE_H
#define NGPNG_ENGINE_H

#include "ngpc_hw.h"   /* u8, s8, s16, u16  (found via -Isrc/core) */
#include "ngpc_gfx.h"  /* ngpc_gfx_scroll, GFX_SCR1/2 (found via -Isrc/gfx) */
#include "scenes_autogen.h"  /* NgpSceneDef, NgpngRect  (found via -IGraphX) */

/* Camera modes */
#ifndef CAM_MODE_SINGLE_SCREEN
#define CAM_MODE_SINGLE_SCREEN 0
#define CAM_MODE_FOLLOW        1
#define CAM_MODE_FORCED_SCROLL 2
#define CAM_MODE_SEGMENTS      3
#define CAM_MODE_LOOP          4
#endif

/* Region kinds */
#ifndef REGION_KIND_ZONE
#define REGION_KIND_ZONE        0
#define REGION_KIND_NO_SPAWN    1
#define REGION_KIND_DANGER_ZONE 2
#define REGION_KIND_CHECKPOINT  3
#define REGION_KIND_EXIT_GOAL   4
#define REGION_KIND_CAMERA_LOCK 5
#define REGION_KIND_SPAWN       6
#define REGION_KIND_ATTRACTOR   7
#define REGION_KIND_REPULSOR    8
#endif

/* HUD plane lock */
#ifndef NGPNG_HUD_FIXED_NONE
#define NGPNG_HUD_FIXED_NONE 0
#define NGPNG_HUD_FIXED_SCR1 1
#define NGPNG_HUD_FIXED_SCR2 2
#endif

/* Fast inline tilecol lookup — _tc/_mw/_mh must be RAM-cached locals.
 * Assumes _tc != NULL. Negative coords cast to large u16, fail bounds → oob_. */
#define NGPNG_TILECOL_FAST(_tc, _mw, _mh, _wx, _wy, _oob) \
    (((u16)((u16)(_wx) >> 3u) < (u16)(_mw) && \
      (u16)((u16)(_wy) >> 3u) < (u16)(_mh)) \
     ? (_tc)[(u16)((u16)((u16)(_wy) >> 3u) * (u16)(_mw) \
              + (u16)((u16)(_wx) >> 3u))] \
     : (u8)(_oob))

/* ---- Engine functions ---- */
s16  ngpng_wrap_axis(s16 value, s16 size_px);
s16  ngpng_axis_delta(s16 world, s16 cam, s16 size_px, u8 loop);
void ngpng_apply_camera_constraints(const NgpSceneDef *sc, s16 *cam_px, s16 *cam_py);
void ngpng_follow_player_camera(const NgpSceneDef *sc, s16 player_wx, s16 player_wy, s16 *cam_px, s16 *cam_py);
u8   ngpng_region_camera_lock_bounds(const NgpSceneDef *sc, u8 region_idx, s16 *min_x, s16 *min_y, s16 *max_x, s16 *max_y);
void ngpng_apply_camera_lock_region(const NgpSceneDef *sc, s16 player_wx, s16 player_wy, s16 *cam_px, s16 *cam_py);
/* OPT-E: merged camera update — follow + lock region + lag + constraints in one call. */
void ngpng_update_camera(const NgpSceneDef *sc, s16 player_wx, s16 player_wy, s16 *cam_px, s16 *cam_py);
void ngpng_update_plane_scroll(const NgpSceneDef *sc, s16 cam_px, s16 cam_py);
u8   ngpng_region_contains_world_point(const NgpSceneDef *sc, u8 region_idx, s16 wx, s16 wy);
u8   ngpng_tile_has_floor(const NgpSceneDef *sc, u8 tile);
u8   ngpng_tile_is_stair(u8 tile);
u8   ngpng_tile_floor_y(const NgpSceneDef *sc, u8 tile, s16 wx, s16 wy, s16 *surface_y);
u8   ngpng_floor_probe_world(const NgpSceneDef *sc, s16 wx, s16 wy, s16 *surface_y);
u8   ngpng_first_blocking_ceiling_y(const NgpSceneDef *sc, s16 wx_left, s16 wx_right, s16 wy_from, s16 wy_to, u8 max_steps, s16 *hit_y);
u8   ngpng_tile_blocks_ceiling(u8 tile);
u8   ngpng_tile_blocks_left(u8 tile);
u8   ngpng_tile_blocks_right(u8 tile);
u8   ngpng_tile_is_damage(u8 tile);
u8   ngpng_tile_is_fire(u8 tile);
u8   ngpng_tile_is_void(u8 tile);
u8   ngpng_tile_is_door(u8 tile);
u8   ngpng_tile_is_spring(u8 tile);
u8   ngpng_tilecol_world(const NgpSceneDef *sc, s16 wx, s16 wy, u8 oob_value);
u8   ngpng_tile_is_ladder(u8 tile);
u8   ngpng_tile_is_water(u8 tile);

/* SCENE_FLAG_HAS_WATER fallback — defined here so static runtime files compile
 * even before scenes_autogen.h has been regenerated with the new flag. */
#ifndef SCENE_FLAG_HAS_WATER
#define SCENE_FLAG_HAS_WATER 0x0200u /* TILE_WATER (9) present */
#endif

#endif /* NGPNG_ENGINE_H */
