/* ngpng_engine.c -- Camera, scroll, region helpers.
 * Part of the ngpng static module layer (NGPC PNG Manager).
 * Overwritten on next export -- do not hand-edit.
 */
#include "ngpng_engine.h"

/* Compute (v * pct / 100) without 32-bit arithmetic.
 * Divide first to stay within s16: q = v/100, r = v%100.
 * result = q*pct + r*pct/100. Safe: q*100 <= 32700, r*100 <= 9900.
 * Short-circuits for common values avoid software mul/div on T900.
 * At 8 calls/frame (4 planes x 2 axes), each saved division ~= 150 cycles.
 * 50%/25%/75%/200% are the standard parallax presets after 0% and 100%. */
static s16 ngpng_scale_pct(s16 v, s16 pct)
{
    s16 q, r;
    if (pct == 100) return v;
    if (pct == 0)   return 0;
    if (pct == 50)  return (s16)(v >> 1);           /* paralax 1:2 — sra 1 */
    if (pct == 25)  return (s16)(v >> 2);           /* parallax 1:4 — sra 2 */
    if (pct == 75)  return (s16)(v - (v >> 2));     /* 100% - 25% — exact */
    if (pct == 200) return (s16)(v + v);            /* foreground 2:1 */
    q = (s16)(v / (s16)100);
    r = (s16)(v % (s16)100);
    return (s16)(q * pct + r * pct / (s16)100);
}

s16 ngpng_wrap_axis(s16 value, s16 size_px)
{
    s16 v;
    if (size_px <= 0) return value;
    /* pow2 fast path: & mask (~5 cycles) vs % (~150 cycles on T900).
     * Maps with tile counts that are powers of 2 (64, 128, 256 px…) hit this. */
    if ((size_px & (size_px - 1)) == 0)
        return (s16)((u16)value & (u16)(size_px - 1u));
    v = (s16)(value % size_px);
    if (v < 0) v = (s16)(v + size_px);
    return v;
}

s16 ngpng_axis_delta(s16 world, s16 cam, s16 size_px, u8 loop)
{
    s16 d = (s16)(world - cam);
    s16 half;
    if (!loop || size_px <= 0) return d;
    half = (s16)(size_px >> 1);  /* >> 1 replaces / 2 — safe, size_px > 0 */
    if (d > half) d = (s16)(d - size_px);
    else if (d < (s16)(-half)) d = (s16)(d + size_px);
    return d;
}

void ngpng_apply_camera_constraints(const NgpSceneDef *sc, s16 *cam_px, s16 *cam_py)
{
    s16 map_px_w = (s16)(sc->map_w * 8u);
    s16 map_px_h = (s16)(sc->map_h * 8u);
    if (sc->loop_x) *cam_px = ngpng_wrap_axis(*cam_px, map_px_w);
    if (sc->loop_y) *cam_py = ngpng_wrap_axis(*cam_py, map_px_h);
    /* DungeonGen: cam_max_x/y are 0 (room size unknown at scene compile time).
     * The DungeonGen camera code clamps dynamically via scroll_max_x/y in the
     * generated update loop — skip the static clamp here to avoid resetting to 0. */
    if (sc->cam_clamp && !(sc->scene_flags & SCENE_FLAG_RUNTIME_DUNGEONGEN)) {
        s16 min_x = (s16)sc->cam_min_x;
        s16 min_y = (s16)sc->cam_min_y;
        s16 max_x = (s16)sc->cam_max_x;
        s16 max_y = (s16)sc->cam_max_y;
        if (!sc->loop_x) {
            if (*cam_px < min_x) *cam_px = min_x;
            if (*cam_px > max_x) *cam_px = max_x;
        }
        if (!sc->loop_y) {
            if (*cam_py < min_y) *cam_py = min_y;
            if (*cam_py > max_y) *cam_py = max_y;
        }
    }
}

void ngpng_follow_player_camera(const NgpSceneDef *sc, s16 player_wx, s16 player_wy, s16 *cam_px, s16 *cam_py)
{
    s16 left;
    s16 right;
    s16 top;
    s16 bottom;
    u8 dzx;
    u8 dzy;
    u8 drop_y;
    if (!sc || !cam_px || !cam_py) return;
    if (sc->cam_mode != CAM_MODE_FOLLOW) return;
    dzx = sc->cam_follow_deadzone_x;
    dzy = sc->cam_follow_deadzone_y;
    drop_y = sc->cam_follow_drop_margin_y;
    left = (s16)(*cam_px + 80 - dzx);
    right = (s16)(*cam_px + 80 + dzx);
    if (player_wx < left) *cam_px = (s16)(player_wx - (80 - dzx));
    else if (player_wx > right) *cam_px = (s16)(player_wx - (80 + dzx));
    top = (s16)(*cam_py + 72 - dzy);
    bottom = (s16)(*cam_py + 72 + dzy + drop_y);
    if (player_wy < top) *cam_py = (s16)(player_wy - (72 - dzy));
    else if (player_wy > bottom) *cam_py = (s16)(player_wy - (72 + dzy + drop_y));
    ngpng_apply_camera_constraints(sc, cam_px, cam_py);
}

/* ngpng_region_contains_world_point declared before ngpng_apply_camera_lock_region
 * (which calls it) to satisfy C89 forward-declaration requirements. */
u8 ngpng_region_contains_world_point(const NgpSceneDef *sc, u8 region_idx, s16 wx, s16 wy)
{
    const NgpngRect *r;
    s16 tx;
    s16 ty;
    if (!sc || !sc->regions || region_idx >= sc->region_count) return 0u;
    r = &sc->regions[region_idx];
    tx = (s16)(wx >> 3);
    ty = (s16)(wy >> 3);
    return (u8)((tx >= r->x) && (ty >= r->y) && (tx < (s16)(r->x + r->w)) && (ty < (s16)(r->y + r->h)));
}

u8 ngpng_region_camera_lock_bounds(const NgpSceneDef *sc, u8 region_idx, s16 *min_x, s16 *min_y, s16 *max_x, s16 *max_y)
{
    const NgpngRect *r;
    s16 rx0;
    s16 ry0;
    s16 rx1;
    s16 ry1;
    if (!sc || !min_x || !min_y || !max_x || !max_y) return 0u;
    if (!sc->regions || region_idx >= sc->region_count) return 0u;
    if (!sc->region_kind || sc->region_kind[region_idx] != REGION_KIND_CAMERA_LOCK) return 0u;
    r = &sc->regions[region_idx];
    rx0 = (s16)r->x;
    ry0 = (s16)r->y;
    rx1 = (s16)(r->x + r->w - 20);
    ry1 = (s16)(r->y + r->h - 19);
    if (rx1 < rx0) rx1 = rx0;
    if (ry1 < ry0) ry1 = ry0;
    *min_x = (s16)(rx0 * 8);
    *min_y = (s16)(ry0 * 8);
    *max_x = (s16)(rx1 * 8);
    *max_y = (s16)(ry1 * 8);
    return 1u;
}

void ngpng_apply_camera_lock_region(const NgpSceneDef *sc, s16 player_wx, s16 player_wy, s16 *cam_px, s16 *cam_py)
{
    u8 i;
    u8 best = 0xFFu;
    u16 best_area = 0u;
    u16 area;
    s16 min_x;
    s16 min_y;
    s16 max_x;
    s16 max_y;
    if (!sc || !cam_px || !cam_py || !sc->region_kind || !sc->regions) return;
    for (i = 0; i < sc->region_count; ++i) {
        if (sc->region_kind[i] != REGION_KIND_CAMERA_LOCK) continue;
        if (!ngpng_region_contains_world_point(sc, i, player_wx, player_wy)) continue;
        area = (u16)(sc->regions[i].w * sc->regions[i].h);
        if (best == 0xFFu || area < best_area) {
            best = i;
            best_area = area;
        }
    }
    if (best == 0xFFu) return;
    if (!ngpng_region_camera_lock_bounds(sc, best, &min_x, &min_y, &max_x, &max_y)) return;
    if (!sc->loop_x) {
        if (*cam_px < min_x) *cam_px = min_x;
        if (*cam_px > max_x) *cam_px = max_x;
    }
    if (!sc->loop_y) {
        if (*cam_py < min_y) *cam_py = min_y;
        if (*cam_py > max_y) *cam_py = max_y;
    }
}

/* OPT-E: merged camera update — follow + lock region + lag + constraints in one pass.
 * Replaces the 4-call sequence emitted by template_integration:
 *   ngpng_follow_player_camera (internal constraint) + ngpng_apply_camera_lock_region
 *   + lag arithmetic + ngpng_apply_camera_constraints.
 * Key saving: the constraint inside ngpng_follow_player_camera was applied to the
 * temporary target, then thrown away by the lag step — now there is only one final
 * constraint call, after the lag interpolation. */
void ngpng_update_camera(const NgpSceneDef *sc, s16 player_wx, s16 player_wy, s16 *cam_px, s16 *cam_py)
{
    s16 tpx;
    s16 tpy;
    s16 min_x;
    s16 min_y;
    s16 max_x;
    s16 max_y;
    u8 i;
    u8 best;
    u16 best_area;
    u16 area;
    if (!sc || !cam_px || !cam_py) return;
    tpx = *cam_px;
    tpy = *cam_py;
    /* Step 1: follow player (no internal constraint — save that for after lag) */
    if (sc->cam_mode == CAM_MODE_FOLLOW) {
        u8 dzx     = sc->cam_follow_deadzone_x;
        u8 dzy     = sc->cam_follow_deadzone_y;
        u8 drop_y  = sc->cam_follow_drop_margin_y;
        s16 left   = (s16)(tpx + 80 - dzx);
        s16 right  = (s16)(tpx + 80 + dzx);
        s16 top    = (s16)(tpy + 72 - dzy);
        s16 bottom = (s16)(tpy + 72 + dzy + drop_y);
        if (player_wx < left)  tpx = (s16)(player_wx - (80 - dzx));
        else if (player_wx > right) tpx = (s16)(player_wx - (80 + dzx));
        if (player_wy < top)   tpy = (s16)(player_wy - (72 - dzy));
        else if (player_wy > bottom) tpy = (s16)(player_wy - (72 + dzy + drop_y));
    }
    /* Step 2: lock region (inline — avoids a second function call + stack frame) */
    if (sc->region_kind && sc->regions) {
        best      = 0xFFu;
        best_area = 0u;
        for (i = 0u; i < sc->region_count; ++i) {
            if (sc->region_kind[i] != REGION_KIND_CAMERA_LOCK) continue;
            if (!ngpng_region_contains_world_point(sc, i, player_wx, player_wy)) continue;
            area = (u16)(sc->regions[i].w * sc->regions[i].h);
            if (best == 0xFFu || area < best_area) { best = i; best_area = area; }
        }
        if (best != 0xFFu && ngpng_region_camera_lock_bounds(sc, best, &min_x, &min_y, &max_x, &max_y)) {
            if (!sc->loop_x) {
                if (tpx < min_x) tpx = min_x;
                if (tpx > max_x) tpx = max_x;
            }
            if (!sc->loop_y) {
                if (tpy < min_y) tpy = min_y;
                if (tpy > max_y) tpy = max_y;
            }
        }
    }
    /* Step 3: lag interpolation */
    if (sc->cam_lag > 0u) {
        *cam_px = (s16)(*cam_px + (s16)((tpx - *cam_px) >> sc->cam_lag));
        *cam_py = (s16)(*cam_py + (s16)((tpy - *cam_py) >> sc->cam_lag));
    } else {
        *cam_px = tpx;
        *cam_py = tpy;
    }
    /* Step 4: single final constraint — covers both snap and post-lag drift */
    ngpng_apply_camera_constraints(sc, cam_px, cam_py);
}

/* OPT-D: merged function — compute scale_pct 4x once, then stream + scroll.
 * Replaces the old ngpng_queue_plane_stream + ngpng_apply_plane_scroll pair
 * which each computed the same 4 scale_pct values independently. */
void ngpng_update_plane_scroll(const NgpSceneDef *sc, s16 cam_px, s16 cam_py)
{
    s16 scr1x = ngpng_scale_pct(cam_px, (s16)sc->scr1_parallax_x_pct);
    s16 scr1y = ngpng_scale_pct(cam_py, (s16)sc->scr1_parallax_y_pct);
    s16 scr2x = ngpng_scale_pct(cam_px, (s16)sc->scr2_parallax_x_pct);
    s16 scr2y = ngpng_scale_pct(cam_py, (s16)sc->scr2_parallax_y_pct);
    if (sc->hud_fixed_plane == NGPNG_HUD_FIXED_SCR1) { scr1x = 0; scr1y = 0; }
    else if (sc->hud_fixed_plane == NGPNG_HUD_FIXED_SCR2) { scr2x = 0; scr2y = 0; }
    if (sc->stream_planes) sc->stream_planes(scr1x, scr1y, scr2x, scr2y);
    HW_SCR_PRIO = (u8)((HW_SCR_PRIO & 0x7Fu) | ((sc->bg_front == 2u) ? 0x80u : 0u));
    ngpc_gfx_scroll(GFX_SCR1, (u8)scr1x, (u8)scr1y);
    ngpc_gfx_scroll(GFX_SCR2, (u8)scr2x, (u8)scr2y);
}

u8 ngpng_tile_has_floor(const NgpSceneDef *sc, u8 tile)
{
    (void)sc;
    switch (tile) {
        case TILE_SOLID:
        case TILE_ONE_WAY:
        case TILE_DAMAGE:
        case TILE_WATER:
        case TILE_DOOR:
        case TILE_WALL_N:
        case TILE_STAIR_E:
        case TILE_STAIR_W:
        case TILE_SPRING:
        case TILE_ICE:
        case TILE_CONVEYOR_L:
        case TILE_CONVEYOR_R:
            return 1u;
        default:
            return 0u;
    }
}

u8 ngpng_tile_is_stair(u8 tile)
{
    return (tile == TILE_STAIR_E || tile == TILE_STAIR_W) ? 1u : 0u;
}

u8 ngpng_tile_floor_y(const NgpSceneDef *sc, u8 tile, s16 wx, s16 wy, s16 *surface_y)
{
    s16 ty;
    u8 lx;
    u8 tile_above;
    u16 tx_above;
    u16 ty_above;
    if (!surface_y) return 0u;
    if (wx < 0 || wy < 0) return 0u;
    if (tile == TILE_LADDER) {
        if (!(sc && sc->ladder_top_solid)) return 0u;
        tile_above = TILE_PASS;
        if (sc->tilecol && wy >= 8) {
            tx_above = (u16)((u16)wx >> 3u);
            ty_above = (u16)((u16)(wy - 8) >> 3u);
            if (tx_above < (u16)sc->map_w && ty_above < (u16)sc->map_h)
                tile_above = sc->tilecol[(u16)(ty_above * (u16)sc->map_w + tx_above)];
        }
        if (tile_above == TILE_LADDER) return 0u;
    } else if (!ngpng_tile_has_floor(sc, tile)) {
        return 0u;
    }
    ty = (s16)(s16)(((u16)wy >> 3u) * 8u);
    if (ngpng_tile_is_stair(tile)) {
        lx = (u8)((u16)wx & 7u);
        if (tile == TILE_STAIR_E) *surface_y = (s16)(ty + (s16)(7u - lx));
        else *surface_y = (s16)(ty + (s16)lx);
        return 1u;
    }
    *surface_y = ty;
    return 1u;
}

u8 ngpng_floor_probe_world(const NgpSceneDef *sc, s16 wx, s16 wy, s16 *surface_y)
{
    s16 sx;
    s16 sy;
    s16 best_y;
    u8 tile;
    if (!sc || !surface_y || !sc->tilecol || sc->map_w == 0u || sc->map_h == 0u) return 0u;
    sx = wx;
    sy = wy;
    if (sx < 0) sx = 0;
    if (sy < 0) sy = 0;
    if (sx >= (s16)(sc->map_w * 8u)) sx = (s16)(sc->map_w * 8u - 1u);
    if (sy >= (s16)(sc->map_h * 8u)) sy = (s16)(sc->map_h * 8u - 1u);
    tile = ngpng_tilecol_world(sc, sx, sy, TILE_SOLID);
    if (!ngpng_tile_floor_y(sc, tile, sx, sy, surface_y)) return 0u;
    if (wy < *surface_y) return 0u;
    best_y = *surface_y;
    while (best_y > 0) {
        s16 above_probe_y;
        s16 above_surface_y;
        u8 above_tile;
        above_probe_y = (s16)(best_y - 1);
        above_tile = ngpng_tilecol_world(sc, sx, above_probe_y, TILE_PASS);
        if (!ngpng_tile_floor_y(sc, above_tile, sx, above_probe_y, &above_surface_y)) break;
        if (above_surface_y >= best_y) break;
        if (wy < above_surface_y) break;
        best_y = above_surface_y;
    }
    *surface_y = best_y;
    return 1u;
}

u8 ngpng_first_blocking_ceiling_y(const NgpSceneDef *sc,
    s16 wx_left, s16 wx_right, s16 wy_from, s16 wy_to, u8 max_steps, s16 *hit_y)
{
    /* OPT-CEILING-TILE: scan tile-row-by-tile-row instead of pixel-by-pixel.
     * Original: up to max_steps iterations = 2*max_steps ngpng_tilecol_world calls.
     * After:    ceil(max_steps/8)+1 tile rows = ~3 iterations for max_steps=16.
     * hit_y returned as tile-top pixel — caller uses (hit_y>>3) anyway, no change. */
    s16 swap_y;
    s16 min_scan_y;
    s16 tt_from;
    s16 tt_to;
    s16 tt;
    s16 probe_y;
    u8 tile_l;
    u8 tile_r;
    if (!sc || !hit_y) return 0u;
    if (wy_from < wy_to) {
        swap_y = wy_from;
        wy_from = wy_to;
        wy_to = swap_y;
    }
    if (max_steps > 0u) {
        min_scan_y = (s16)(wy_from - (s16)max_steps);
        if (wy_to < min_scan_y) wy_to = min_scan_y;
    }
    tt_from = (s16)((u16)wy_from >> 3u);
    tt_to   = (s16)((u16)(wy_to > 0 ? wy_to : 0) >> 3u);
    for (tt = tt_from; tt >= tt_to; --tt) {
        probe_y = (s16)((u16)tt * 8u);
        tile_l = ngpng_tilecol_world(sc, wx_left,  probe_y, TILE_PASS);
        tile_r = ngpng_tilecol_world(sc, wx_right, probe_y, TILE_PASS);
        if (ngpng_tile_blocks_ceiling(tile_l) || ngpng_tile_blocks_ceiling(tile_r)) {
            *hit_y = probe_y;
            return 1u;
        }
    }
    return 0u;
}

u8 ngpng_tile_blocks_ceiling(u8 tile)
{
    return (tile == TILE_SOLID || tile == TILE_WALL_S) ? 1u : 0u;
}

u8 ngpng_tile_blocks_left(u8 tile)
{
    return (tile == TILE_SOLID || tile == TILE_WALL_E) ? 1u : 0u;
}

u8 ngpng_tile_blocks_right(u8 tile)
{
    return (tile == TILE_SOLID || tile == TILE_WALL_W) ? 1u : 0u;
}

u8 ngpng_tile_is_damage(u8 tile)
{
    return (tile == TILE_DAMAGE) ? 1u : 0u;
}

u8 ngpng_tile_is_fire(u8 tile)
{
    return (tile == TILE_FIRE) ? 1u : 0u;
}

u8 ngpng_tile_is_void(u8 tile)
{
    return (tile == TILE_VOID) ? 1u : 0u;
}

u8 ngpng_tile_is_door(u8 tile)
{
    return (tile == TILE_DOOR) ? 1u : 0u;
}

u8 ngpng_tile_is_spring(u8 tile)
{
    return (tile == TILE_SPRING) ? 1u : 0u;
}

u8 ngpng_tilecol_world(const NgpSceneDef *sc, s16 wx, s16 wy, u8 oob_value)
{
    u16 tx;
    u16 ty;
    if (!sc || !sc->tilecol) return oob_value;
    if (wx < 0 || wy < 0) return oob_value;
    tx = (u16)((u16)wx >> 3u);
    ty = (u16)((u16)wy >> 3u);
    if (tx >= (u16)sc->map_w || ty >= (u16)sc->map_h) return oob_value;
    return sc->tilecol[(u16)(ty * (u16)sc->map_w + tx)];
}

u8 ngpng_tile_is_ladder(u8 tile)
{
    return (tile == TILE_LADDER) ? 1u : 0u;
}

u8 ngpng_tile_is_water(u8 tile)
{
    return (tile == TILE_WATER) ? 1u : 0u;
}
