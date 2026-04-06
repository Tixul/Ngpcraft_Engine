/* ngpng_player_runtime.c -- Stable player physics helpers.
 * Part of the ngpng static module layer (NGPC PNG Manager).
 * NOT generated -- this file is project-independent.
 *
 * Feature gates (defined via Makefile CDEFS, auto-injected by the tool):
 *   NGPNG_HAS_LADDER   -- full ladder impl; else stubs return 0
 *   NGPNG_HAS_SPRING   -- spring tile physics
 *   NGPNG_HAS_DOOR     -- door tile impl; else stub returns 0
 *   NGPNG_HAS_ICE      -- ice ground detection
 *   NGPNG_HAS_CONVEYOR -- conveyor belt additive vx in apply_tile_effects
 */
#include "ngpng_player_ctrl.h"   /* NgpngPlayerActor (generated per project, in same dir) */
#include "ngpng_player_runtime.h"

/* =========================================================================
 * World clamp helpers
 * ========================================================================= */

void ngpng_player_clamp_world(const NgpSceneDef *sc, NgpngPlayerActor *p,
    s16 cam_px, s16 cam_py,
    s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h,
    s8 render_off_x, s8 render_off_y, u8 frame_w, u8 frame_h)
{
    s16 wx;
    s16 wy;
    s16 min_x;
    s16 min_y;
    s16 max_x;
    s16 max_y;
    if (!sc || !p) return;
    if ((p->flags & NGPNG_ENT_FLAG_CLAMP_MAP) == 0u) return;
    wx = (s16)(cam_px + p->x);
    wy = (s16)(cam_py + p->y);
    (void)render_off_x;
    (void)render_off_y;
    (void)frame_w;
    (void)frame_h;
    min_x = (s16)(-hb_x);
    min_y = (s16)(-hb_y);
    max_x = (s16)((s16)(sc->map_w * 8u) - hb_x - hb_w);
    max_y = (s16)((s16)(sc->map_h * 8u) - hb_y - hb_h);
    if (max_x < min_x) max_x = min_x;
    if (max_y < min_y) max_y = min_y;
    if (wx < min_x) wx = min_x;
    if (wy < min_y) wy = min_y;
    if (wx > max_x) wx = max_x;
    if (wy > max_y) wy = max_y;
    p->x = (s16)(wx - cam_px);
    p->y = (s16)(wy - cam_py);
}

void ngpng_player_clamp_world_xy(const NgpSceneDef *sc, s16 *wx, s16 *wy,
    s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h, u8 flags)
{
    if ((flags & NGPNG_ENT_FLAG_CLAMP_MAP) == 0u) return;
    if (!sc || !wx || !wy) return;
    {
        s16 min_x = (s16)(-hb_x);
        s16 min_y = (s16)(-hb_y);
        s16 max_x = (s16)((s16)(sc->map_w * 8u) - hb_x - hb_w);
        s16 max_y = (s16)((s16)(sc->map_h * 8u) - hb_y - hb_h);
        if (max_x < min_x) max_x = min_x;
        if (max_y < min_y) max_y = min_y;
        if (*wx < min_x) *wx = min_x;
        if (*wy < min_y) *wy = min_y;
        if (*wx > max_x) *wx = max_x;
        if (*wy > max_y) *wy = max_y;
    }
}

/* =========================================================================
 * Ladder helpers
 * ========================================================================= */

#if NGPNG_HAS_LADDER

u8 ngpng_player_touches_ladder(const NgpSceneDef *sc,
    s16 px, s16 py, u8 frame_w, u8 frame_h)
{
    s16 x0;
    s16 x1;
    s16 cx;
    s16 cy0;
    s16 cym;
    s16 cy1;
    /* OPT-C: no ladder tiles in this scene — skip 9 tilecol_world calls. */
    if (!sc || !(sc->scene_flags & SCENE_FLAG_HAS_LADDER)) return 0u;
    x0  = (s16)(px + 1);
    x1  = (s16)(px + ((frame_w > 0u) ? (frame_w - 2u) : 0u));
    cx  = (s16)(px + (frame_w / 2u));
    cy0 = (s16)(py + 4);
    cym = (s16)(py + (frame_h / 2u));
    cy1 = (s16)(py + frame_h - 2);
    if (x1 < x0) x1 = x0;
    return (u8)(
        ngpng_tile_is_ladder(ngpng_tilecol_world(sc, x0, cy0, TILE_PASS)) ||
        ngpng_tile_is_ladder(ngpng_tilecol_world(sc, cx, cy0, TILE_PASS)) ||
        ngpng_tile_is_ladder(ngpng_tilecol_world(sc, x1, cy0, TILE_PASS)) ||
        ngpng_tile_is_ladder(ngpng_tilecol_world(sc, x0, cym, TILE_PASS)) ||
        ngpng_tile_is_ladder(ngpng_tilecol_world(sc, cx, cym, TILE_PASS)) ||
        ngpng_tile_is_ladder(ngpng_tilecol_world(sc, x1, cym, TILE_PASS)) ||
        ngpng_tile_is_ladder(ngpng_tilecol_world(sc, x0, cy1, TILE_PASS)) ||
        ngpng_tile_is_ladder(ngpng_tilecol_world(sc, cx, cy1, TILE_PASS)) ||
        ngpng_tile_is_ladder(ngpng_tilecol_world(sc, x1, cy1, TILE_PASS))
    );
}

u8 ngpng_player_find_ladder_below(const NgpSceneDef *sc,
    s16 wx, s16 wy, s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h, s16 *snap_wx)
{
    static const s8 k_offsets[] = { 0, 4, -4, 8, -8 };
    u8 i;
    u8 j;
    s16 foot_y;
    s16 probes_x[3];
    /* OPT-C: no ladder tiles in this scene — skip probe loops. */
    if (!sc || !(sc->scene_flags & SCENE_FLAG_HAS_LADDER)) return 0u;
    foot_y      = (s16)(wy + hb_y + hb_h);
    probes_x[0] = (s16)(wx + hb_x + 1);
    probes_x[1] = (s16)(wx + hb_x + (hb_w / 2u));
    probes_x[2] = (s16)(wx + hb_x + ((hb_w > 1u) ? (hb_w - 2u) : 0u));
    if (probes_x[2] < probes_x[0]) probes_x[2] = probes_x[0];
    for (i = 0u; i < (u8)(sizeof(k_offsets) / sizeof(k_offsets[0])); ++i) {
        for (j = 0u; j < 3u; ++j) {
            s16 probe_x;
            s16 probe_y;
            u8  tile;
            probe_x = (s16)(probes_x[j] + (s16)k_offsets[i]);
            probe_y = (s16)(foot_y + 1);
            tile    = ngpng_tilecol_world(sc, probe_x, probe_y, TILE_PASS);
            if (!ngpng_tile_is_ladder(tile)) continue;
            if (snap_wx) {
                s16 tile_center_x;
                tile_center_x = (s16)((s16)(((u16)probe_x >> 3u) * 8u) + 4);
                *snap_wx = (s16)(tile_center_x - hb_x - (hb_w / 2u));
            }
            return 1u;
        }
    }
    return 0u;
}

u8 ngpng_player_try_ladder_top_exit(const NgpSceneDef *sc,
    s16 *wx, s16 *wy, s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h)
{
    s16 foot_y;
    s16 left_x;
    s16 right_x;
    if (!sc || !wx || !wy) return 0u;
    foot_y  = (s16)(*wy + hb_y + hb_h);
    left_x  = (s16)(*wx + hb_x + 1);
    right_x = (s16)(*wx + hb_x + ((hb_w > 1u) ? (hb_w - 2u) : 0u));
    {
        u8  tileL;
        u8  tileR;
        u8  tileAboveL;
        u8  tileAboveR;
        s16 floor_yL;
        s16 floor_yR;
        s16 floor_y;
        u8  hasL;
        u8  hasR;
        tileL      = ngpng_tilecol_world(sc, left_x,  foot_y,            TILE_PASS);
        tileR      = ngpng_tilecol_world(sc, right_x, foot_y,            TILE_PASS);
        tileAboveL = ngpng_tilecol_world(sc, left_x,  (s16)(foot_y - 8), TILE_PASS);
        tileAboveR = ngpng_tilecol_world(sc, right_x, (s16)(foot_y - 8), TILE_PASS);
        hasL = 0u;
        hasR = 0u;
        if (tileL == TILE_LADDER) {
            if (sc->ladder_top_solid && !ngpng_tile_is_ladder(tileAboveL) &&
                ngpng_tile_floor_y(sc, tileL, left_x, foot_y, &floor_yL)) hasL = 1u;
        } else if (ngpng_tile_floor_y(sc, tileL, left_x, foot_y, &floor_yL)) {
            hasL = 1u;
        }
        if (tileR == TILE_LADDER) {
            if (sc->ladder_top_solid && !ngpng_tile_is_ladder(tileAboveR) &&
                ngpng_tile_floor_y(sc, tileR, right_x, foot_y, &floor_yR)) hasR = 1u;
        } else if (ngpng_tile_floor_y(sc, tileR, right_x, foot_y, &floor_yR)) {
            hasR = 1u;
        }
        if (!hasL && !hasR) return 0u;
        floor_y = hasL ? floor_yL : floor_yR;
        if (hasR && floor_yR < floor_y) floor_y = floor_yR;
        *wy = (s16)(floor_y - hb_y - hb_h);
        return 1u;
    }
}

#else /* !NGPNG_HAS_LADDER — stubs */

u8 ngpng_player_touches_ladder(const NgpSceneDef *sc,
    s16 px, s16 py, u8 frame_w, u8 frame_h)
{ (void)sc; (void)px; (void)py; (void)frame_w; (void)frame_h; return 0u; }

u8 ngpng_player_find_ladder_below(const NgpSceneDef *sc,
    s16 wx, s16 wy, s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h, s16 *snap_wx)
{ (void)sc; (void)wx; (void)wy; (void)hb_x; (void)hb_y; (void)hb_w; (void)hb_h; (void)snap_wx; return 0u; }

u8 ngpng_player_try_ladder_top_exit(const NgpSceneDef *sc,
    s16 *wx, s16 *wy, s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h)
{ (void)sc; (void)wx; (void)wy; (void)hb_x; (void)hb_y; (void)hb_w; (void)hb_h; return 0u; }

#endif /* NGPNG_HAS_LADDER */

/* =========================================================================
 * Spring helper
 * ========================================================================= */

#if NGPNG_HAS_SPRING

u8 ngpng_player_spring_touch_side(const NgpSceneDef *sc,
    const u8 NGP_FAR *_tc, u16 _mw, u16 _mh,
    s16 px, s16 py, s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h, s8 vx, s8 vy)
{
    s16 x0;
    s16 x1;
    s16 xm;
    s16 y0;
    s16 y1;
    s16 ym;
    u8 hit_top;
    u8 hit_bottom;
    u8 hit_left;
    u8 hit_right;
    if (!sc) return NGPNG_SPRING_TOUCH_NONE;
    x0 = (s16)(px + hb_x + 1);
    x1 = (s16)(px + hb_x + ((hb_w > 0u) ? (hb_w - 1u) : 0u) - 1);
    xm = (s16)(px + hb_x + (hb_w / 2u));
    y0 = (s16)(py + hb_y + 1);
    y1 = (s16)(py + hb_y + ((hb_h > 0u) ? hb_h : 1u));
    ym = (s16)(py + hb_y + (hb_h / 2u));
    if (x1 < x0) x1 = x0;
    if (y1 < y0) y1 = y0;
    /* Proximity guard: 5 representative probes before the full 12-probe scan.
     * If no spring tile is adjacent to the player bounding box, return early.
     * Cost when far from spring: 5 tilecol instead of 12 (saves ~7/frame). */
    if (!ngpng_tile_is_spring(NGPNG_TILECOL_FAST(_tc, _mw, _mh, xm,            ym,            TILE_PASS)) &&
        !ngpng_tile_is_spring(NGPNG_TILECOL_FAST(_tc, _mw, _mh, xm,            (s16)(y0 - 1), TILE_PASS)) &&
        !ngpng_tile_is_spring(NGPNG_TILECOL_FAST(_tc, _mw, _mh, xm,            y1,            TILE_PASS)) &&
        !ngpng_tile_is_spring(NGPNG_TILECOL_FAST(_tc, _mw, _mh, (s16)(x0 - 1), ym,            TILE_PASS)) &&
        !ngpng_tile_is_spring(NGPNG_TILECOL_FAST(_tc, _mw, _mh, (s16)(x1 + 1), ym,            TILE_PASS)))
        return NGPNG_SPRING_TOUCH_NONE;
    hit_top    = (u8)(ngpng_tile_is_spring(NGPNG_TILECOL_FAST(_tc, _mw, _mh, x0, (s16)(y0 - 1), TILE_PASS)) ||
                      ngpng_tile_is_spring(NGPNG_TILECOL_FAST(_tc, _mw, _mh, x1, (s16)(y0 - 1), TILE_PASS)) ||
                      ngpng_tile_is_spring(NGPNG_TILECOL_FAST(_tc, _mw, _mh, xm, (s16)(y0 - 1), TILE_PASS)));
    hit_bottom = (u8)(ngpng_tile_is_spring(NGPNG_TILECOL_FAST(_tc, _mw, _mh, x0, y1, TILE_PASS)) ||
                      ngpng_tile_is_spring(NGPNG_TILECOL_FAST(_tc, _mw, _mh, x1, y1, TILE_PASS)) ||
                      ngpng_tile_is_spring(NGPNG_TILECOL_FAST(_tc, _mw, _mh, xm, y1, TILE_PASS)));
    hit_left   = (u8)(ngpng_tile_is_spring(NGPNG_TILECOL_FAST(_tc, _mw, _mh, (s16)(x0 - 1), y0,            TILE_PASS)) ||
                      ngpng_tile_is_spring(NGPNG_TILECOL_FAST(_tc, _mw, _mh, (s16)(x0 - 1), ym,            TILE_PASS)) ||
                      ngpng_tile_is_spring(NGPNG_TILECOL_FAST(_tc, _mw, _mh, (s16)(x0 - 1), (s16)(y1 - 1), TILE_PASS)));
    hit_right  = (u8)(ngpng_tile_is_spring(NGPNG_TILECOL_FAST(_tc, _mw, _mh, (s16)(x1 + 1), y0,            TILE_PASS)) ||
                      ngpng_tile_is_spring(NGPNG_TILECOL_FAST(_tc, _mw, _mh, (s16)(x1 + 1), ym,            TILE_PASS)) ||
                      ngpng_tile_is_spring(NGPNG_TILECOL_FAST(_tc, _mw, _mh, (s16)(x1 + 1), (s16)(y1 - 1), TILE_PASS)));
    if (hit_bottom && (vy >= 0 || (!hit_left && !hit_right))) return NGPNG_SPRING_TOUCH_BOTTOM;
    if (hit_top    && (vy <= 0 || (!hit_left && !hit_right))) return NGPNG_SPRING_TOUCH_TOP;
    if (hit_left   && (vx <= 0 || !hit_right))                return NGPNG_SPRING_TOUCH_LEFT;
    if (hit_right  && (vx >= 0 || !hit_left))                 return NGPNG_SPRING_TOUCH_RIGHT;
    if (hit_bottom) return NGPNG_SPRING_TOUCH_BOTTOM;
    if (hit_top)    return NGPNG_SPRING_TOUCH_TOP;
    if (hit_left)   return NGPNG_SPRING_TOUCH_LEFT;
    if (hit_right)  return NGPNG_SPRING_TOUCH_RIGHT;
    return NGPNG_SPRING_TOUCH_NONE;
}

#else /* !NGPNG_HAS_SPRING — stub */

u8 ngpng_player_spring_touch_side(const NgpSceneDef *sc,
    const u8 NGP_FAR *_tc, u16 _mw, u16 _mh,
    s16 px, s16 py, s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h, s8 vx, s8 vy)
{ (void)sc; (void)_tc; (void)_mw; (void)_mh;
  (void)px; (void)py; (void)hb_x; (void)hb_y; (void)hb_w; (void)hb_h; (void)vx; (void)vy;
  return NGPNG_SPRING_TOUCH_NONE; }

#endif /* NGPNG_HAS_SPRING */

/* =========================================================================
 * Tile effect application (damage / fire / void / spring / conveyor)
 * ========================================================================= */

void ngpng_player_apply_tile_effects(const NgpSceneDef *sc,
    const u8 NGP_FAR *_tc, u16 _mw, u16 _mh,
    s16 px, s16 py, s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h,
    s8 *vx, s8 *vy, u8 *on_ground, u8 *coyote, u8 *hp, u8 *invul)
{
    s16 x0;
    s16 x1;
    s16 xm;
    s16 y0;
    s16 y1;
    s16 ym;
    u8 t0;
    u8 t1;
    u8 t2;
    u8 t3;
    u8 t4;
    u8 hit_damage;
    u8 hit_fire;
    u8 hit_void;
    u8 dmg;
#if NGPNG_HAS_SPRING
    u8 spring_touch;
    u8 spring_dir;
    u8 spring_force;
#endif
    if (!hp || !invul || !vx || !vy || !on_ground || !coyote || *hp == 0u) return;
    x0 = (s16)(px + hb_x + 1);
    x1 = (s16)(px + hb_x + ((hb_w > 0u) ? (hb_w - 1u) : 0u) - 1);
    xm = (s16)(px + hb_x + (hb_w / 2u));
    y0 = (s16)(py + hb_y + 1);
    y1 = (s16)(py + hb_y + ((hb_h > 0u) ? (hb_h - 1u) : 0u) - 1);
    ym = (s16)(py + hb_y + (hb_h / 2u));
    if (x1 < x0) x1 = x0;
    if (y1 < y0) y1 = y0;
    /* Deadly tile detection (damage / fire / void).
     * Skip entirely if this scene has no deadly tiles — saves 5 tilecol/frame. */
    if (sc && (sc->scene_flags & SCENE_FLAG_HAS_DEADLY)) {
        t0 = NGPNG_TILECOL_FAST(_tc, _mw, _mh, x0, y0, TILE_PASS);
        t1 = NGPNG_TILECOL_FAST(_tc, _mw, _mh, x1, y0, TILE_PASS);
        t2 = NGPNG_TILECOL_FAST(_tc, _mw, _mh, x0, y1, TILE_PASS);
        t3 = NGPNG_TILECOL_FAST(_tc, _mw, _mh, x1, y1, TILE_PASS);
        t4 = NGPNG_TILECOL_FAST(_tc, _mw, _mh, xm, ym, TILE_PASS);
        hit_void = (u8)(ngpng_tile_is_void(t0) || ngpng_tile_is_void(t1) ||
                        ngpng_tile_is_void(t2) || ngpng_tile_is_void(t3) ||
                        ngpng_tile_is_void(t4));
        if (hit_void) {
            if (sc->void_instant) { *hp = 0u; return; }
            if (*invul != 0u) return;
            dmg = sc->void_damage;
            if (dmg == 0u) return;
            *hp = (dmg >= *hp) ? 0u : (u8)(*hp - dmg);
            *invul = sc->hazard_invul;
            return;
        }
        if (*invul == 0u) {
            hit_damage = (u8)(ngpng_tile_is_damage(t0) || ngpng_tile_is_damage(t1) ||
                              ngpng_tile_is_damage(t2) || ngpng_tile_is_damage(t3) ||
                              ngpng_tile_is_damage(t4));
            hit_fire   = (u8)(ngpng_tile_is_fire(t0) || ngpng_tile_is_fire(t1) ||
                              ngpng_tile_is_fire(t2) || ngpng_tile_is_fire(t3) ||
                              ngpng_tile_is_fire(t4));
            if (hit_fire || hit_damage) {
                dmg = hit_fire
                    ? (u8)((sc->fire_damage  != 0u) ? sc->fire_damage  : 0u)
                    : (u8)((sc->hazard_damage != 0u) ? sc->hazard_damage : 0u);
                if (dmg != 0u) {
                    *hp = (dmg >= *hp) ? 0u : (u8)(*hp - dmg);
                    *invul = sc->hazard_invul;
                }
            }
        }
    }
#if NGPNG_HAS_SPRING
    if (!sc) return;
    spring_force = sc->spring_force;
    if (spring_force == 0u) return;
    spring_touch = ngpng_player_spring_touch_side(sc, _tc, _mw, _mh, px, py, hb_x, hb_y, hb_w, hb_h, *vx, *vy);
    if (spring_touch == NGPNG_SPRING_TOUCH_NONE) return;
    spring_dir = sc->spring_dir;
    if (spring_dir == (u8)NGPNG_SPRING_DIR_OPPOSITE_TOUCH) {
        if      (spring_touch == NGPNG_SPRING_TOUCH_BOTTOM) spring_dir = (u8)NGPNG_SPRING_DIR_UP;
        else if (spring_touch == NGPNG_SPRING_TOUCH_TOP)    spring_dir = (u8)NGPNG_SPRING_DIR_DOWN;
        else if (spring_touch == NGPNG_SPRING_TOUCH_LEFT)   spring_dir = (u8)NGPNG_SPRING_DIR_RIGHT;
        else if (spring_touch == NGPNG_SPRING_TOUCH_RIGHT)  spring_dir = (u8)NGPNG_SPRING_DIR_LEFT;
    }
    if (spring_dir == (u8)NGPNG_SPRING_DIR_UP) {
        if (spring_touch != NGPNG_SPRING_TOUCH_BOTTOM || *vy < 0) return;
        *vy = (s8)(-(s8)spring_force);
    } else if (spring_dir == (u8)NGPNG_SPRING_DIR_DOWN) {
        if (spring_touch != NGPNG_SPRING_TOUCH_TOP || *vy > 0) return;
        *vy = (s8)spring_force;
    } else if (spring_dir == (u8)NGPNG_SPRING_DIR_LEFT) {
        if (spring_touch != NGPNG_SPRING_TOUCH_RIGHT) return;
        *vx = (s8)(-(s8)spring_force);
        if (*vy > 0) *vy = 0;
    } else if (spring_dir == (u8)NGPNG_SPRING_DIR_RIGHT) {
        if (spring_touch != NGPNG_SPRING_TOUCH_LEFT) return;
        *vx = (s8)spring_force;
        if (*vy > 0) *vy = 0;
    }
    *on_ground = 0u;
    *coyote    = 0u;
#endif /* NGPNG_HAS_SPRING */
#if NGPNG_HAS_CONVEYOR
    /* Top-down: always "on ground" (no gravity); platform: gate on on_ground. */
#if defined(NGPNG_MOVE_TOPDOWN) && NGPNG_MOVE_TOPDOWN
    if (sc) {
#else
    if (sc && *on_ground) {
#endif
        s16 _cv_fy;
        u8  _cv_tL;
        u8  _cv_tR;
        u8  _cv_spd;
        /* Top-down: probe hitbox centre; platform: probe one pixel below foot. */
#if defined(NGPNG_MOVE_TOPDOWN) && NGPNG_MOVE_TOPDOWN
        _cv_fy  = ym;
#else
        _cv_fy  = (s16)(py + hb_y + hb_h + 1);
#endif
        _cv_tL  = NGPNG_TILECOL_FAST(_tc, _mw, _mh, x0, _cv_fy, TILE_PASS);
        _cv_tR  = NGPNG_TILECOL_FAST(_tc, _mw, _mh, x1, _cv_fy, TILE_PASS);
        _cv_spd = (sc->conveyor_speed > 0u) ? sc->conveyor_speed : 1u;
        if      (_cv_tL == TILE_CONVEYOR_R || _cv_tR == TILE_CONVEYOR_R) *vx = (s8)(*vx + (s8)_cv_spd);
        else if (_cv_tL == TILE_CONVEYOR_L || _cv_tR == TILE_CONVEYOR_L) *vx = (s8)(*vx - (s8)_cv_spd);
    }
#endif /* NGPNG_HAS_CONVEYOR */
#if defined(NGPNG_HAS_WATER) && NGPNG_HAS_WATER
    /* Water slow-down: halve velocity when hitbox centre overlaps TILE_WATER. */
    if (sc && (sc->scene_flags & SCENE_FLAG_HAS_WATER)) {
        if (NGPNG_TILECOL_FAST(_tc, _mw, _mh, xm, ym, TILE_PASS) == TILE_WATER) {
            *vx = (s8)(*vx >> 1);
            *vy = (s8)(*vy >> 1);
        }
    }
#endif /* NGPNG_HAS_WATER */
}

/* =========================================================================
 * Door tile helper
 * ========================================================================= */

#if NGPNG_HAS_DOOR

u8 ngpng_player_touches_door_tile(const NgpSceneDef *sc,
    s16 px, s16 py, s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h)
{
    s16 x0;
    s16 x1;
    s16 xm;
    s16 y0;
    s16 y1;
    u8 t0;
    u8 t1;
    u8 t2;
    if (!sc) return 0u;
    x0 = (s16)(px + hb_x + 1);
    x1 = (s16)(px + hb_x + ((hb_w > 0u) ? (hb_w - 1u) : 0u) - 1);
    if (x1 < x0) x1 = x0;
    xm = (s16)(px + hb_x + (hb_w / 2u));
    y0 = (s16)(py + hb_y + (hb_h / 2u));
    y1 = (s16)(py + hb_y + hb_h);
    t0 = ngpng_tilecol_world(sc, x0, y0, TILE_PASS);
    t1 = ngpng_tilecol_world(sc, x1, y0, TILE_PASS);
    t2 = ngpng_tilecol_world(sc, xm, y1, TILE_PASS);
    return (u8)(ngpng_tile_is_door(t0) || ngpng_tile_is_door(t1) || ngpng_tile_is_door(t2));
}

#else /* !NGPNG_HAS_DOOR — stub */

u8 ngpng_player_touches_door_tile(const NgpSceneDef *sc,
    s16 px, s16 py, s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h)
{ (void)sc; (void)px; (void)py; (void)hb_x; (void)hb_y; (void)hb_w; (void)hb_h; return 0u; }

#endif /* NGPNG_HAS_DOOR */

/* =========================================================================
 * Ice ground helper
 * ========================================================================= */

#if NGPNG_HAS_ICE

u8 ngpng_player_on_ice_ground(const NgpSceneDef *sc,
    s16 px, s16 py, s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h)
{
    s16 xf;
    s16 xt;
    s16 yf;
    if (!sc) return 0u;
    xf = (s16)(px + hb_x + 2);
    xt = (s16)(px + hb_x + hb_w - 3);
    if (xt < xf) xt = xf;
    yf = (s16)(py + hb_y + hb_h + 1);
    return (u8)(ngpng_tilecol_world(sc, xf, yf, TILE_PASS) == TILE_ICE ||
                ngpng_tilecol_world(sc, xt, yf, TILE_PASS) == TILE_ICE);
}

#else /* !NGPNG_HAS_ICE — stub */

u8 ngpng_player_on_ice_ground(const NgpSceneDef *sc,
    s16 px, s16 py, s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h)
{ (void)sc; (void)px; (void)py; (void)hb_x; (void)hb_y; (void)hb_w; (void)hb_h; return 0u; }

#endif /* NGPNG_HAS_ICE */

/* =========================================================================
 * Top-down AABB tile collision clamp
 * Applies vx then vy (X-first sweep), probes 2 corner pixels per axis edge,
 * and pushes out of SOLID and directional WALL_* tiles.
 * WALL_N blocks downward entry, WALL_S blocks upward, WALL_E blocks leftward,
 * WALL_W blocks rightward.
 * ========================================================================= */

#if defined(NGPNG_MOVE_TOPDOWN) && NGPNG_MOVE_TOPDOWN

void ngpng_player_clamp_tilecol_topdown(
    const u8 NGP_FAR *tc, u16 map_w, u16 map_h,
    s16 cam_px, s16 cam_py,
    s16 *actor_x, s16 *actor_y,
    s8  *vx, s8  *vy,
    s8  hb_x, s8  hb_y, u8 hb_w, u8 hb_h)
{
    s16 wx;
    s16 wy;
    s16 bx0;
    s16 bx1;
    s16 by0;
    s16 by1;
    u16 tx;
    u16 ty;
    u8  t0;
    u8  t1;
    u8  hw;
    u8  hh;

    if (!tc || !actor_x || !actor_y || !vx || !vy) return;
    if (map_w == 0u || map_h == 0u) return;

    hw = (u8)(hb_w > 0u ? hb_w - 1u : 0u);
    hh = (u8)(hb_h > 0u ? hb_h - 1u : 0u);
    wx = (s16)(cam_px + *actor_x);
    wy = (s16)(cam_py + *actor_y);

    /* ---- X axis: apply vx, probe right or left edge, push out ---- */
    wx  = (s16)(wx + *vx);
    bx0 = (s16)(wx + hb_x);
    bx1 = (s16)(bx0 + (s16)hw);
    by0 = (s16)(wy + hb_y);
    by1 = (s16)(by0 + (s16)hh);

    if (*vx > 0) {
        /* Moving right: probe right edge at top and bottom corners.
         * TILE_WALL_W = tile's west face is solid = blocks entry from the west. */
        t0 = NGPNG_TILECOL_FAST(tc, map_w, map_h, bx1, by0, TILE_PASS);
        t1 = NGPNG_TILECOL_FAST(tc, map_w, map_h, bx1, by1, TILE_PASS);
        if ((t0 == TILE_SOLID || t0 == TILE_WALL_W) ||
            (t1 == TILE_SOLID || t1 == TILE_WALL_W)) {
            tx  = (u16)((u16)bx1 >> 3u);
            bx1 = (s16)((s16)((u16)(tx << 3u)) - 1);
            wx  = (s16)((s16)bx1 - (s16)hb_x - (s16)hw);
            *vx = 0;
        }
    } else if (*vx < 0) {
        /* Moving left: probe left edge at top and bottom corners.
         * TILE_WALL_E = tile's east face is solid = blocks entry from the east. */
        t0 = NGPNG_TILECOL_FAST(tc, map_w, map_h, bx0, by0, TILE_PASS);
        t1 = NGPNG_TILECOL_FAST(tc, map_w, map_h, bx0, by1, TILE_PASS);
        if ((t0 == TILE_SOLID || t0 == TILE_WALL_E) ||
            (t1 == TILE_SOLID || t1 == TILE_WALL_E)) {
            tx  = (u16)((u16)bx0 >> 3u);
            bx0 = (s16)((s16)((u16)((u16)tx + 1u) << 3u));
            wx  = (s16)((s16)bx0 - (s16)hb_x);
            *vx = 0;
        }
    }

    /* ---- Y axis: apply vy, probe bottom or top edge, push out (updated bx) ---- */
    wy  = (s16)(wy + *vy);
    bx0 = (s16)(wx + hb_x);
    bx1 = (s16)(bx0 + (s16)hw);
    by0 = (s16)(wy + hb_y);
    by1 = (s16)(by0 + (s16)hh);

    if (*vy > 0) {
        /* Moving down: probe bottom edge at left and right corners.
         * TILE_WALL_N = tile's north face is solid = blocks entry from above. */
        t0 = NGPNG_TILECOL_FAST(tc, map_w, map_h, bx0, by1, TILE_PASS);
        t1 = NGPNG_TILECOL_FAST(tc, map_w, map_h, bx1, by1, TILE_PASS);
        if ((t0 == TILE_SOLID || t0 == TILE_WALL_N) ||
            (t1 == TILE_SOLID || t1 == TILE_WALL_N)) {
            ty  = (u16)((u16)by1 >> 3u);
            by1 = (s16)((s16)((u16)(ty << 3u)) - 1);
            wy  = (s16)((s16)by1 - (s16)hb_y - (s16)hh);
            *vy = 0;
        }
    } else if (*vy < 0) {
        /* Moving up: probe top edge at left and right corners.
         * TILE_WALL_S = tile's south face is solid = blocks entry from below. */
        t0 = NGPNG_TILECOL_FAST(tc, map_w, map_h, bx0, by0, TILE_PASS);
        t1 = NGPNG_TILECOL_FAST(tc, map_w, map_h, bx1, by0, TILE_PASS);
        if ((t0 == TILE_SOLID || t0 == TILE_WALL_S) ||
            (t1 == TILE_SOLID || t1 == TILE_WALL_S)) {
            ty  = (u16)((u16)by0 >> 3u);
            by0 = (s16)((s16)((u16)((u16)ty + 1u) << 3u));
            wy  = (s16)((s16)by0 - (s16)hb_y);
            *vy = 0;
        }
    }

    *actor_x = (s16)(wx - cam_px);
    *actor_y = (s16)(wy - cam_py);
}

#endif /* NGPNG_MOVE_TOPDOWN */
