/* ngpng_entities.c -- Entity structs, type helpers, entity management.
 * Part of the ngpng static module layer (NGPC PNG Manager).
 * Overwritten on next export -- do not hand-edit.
 *
 * Project-specific sizing constants (NGPNG_AUTORUN_MAX_ENEMIES, etc.) are
 * injected via Makefile CDEFS by the generated export.  The #ifndef fallbacks
 * below match the default layout (1 player with 4 sprite slots,
 * NGPNG_AUTORUN_SPR_BASE = 0).  If your project overrides NGPNG_AUTORUN_SPR_BASE
 * you must also update the corresponding CDEFS in your generated Makefile.
 */
#include "ngpng_entities.h"

/* Sprite priority used for all entities. Set to SPR_MIDDLE during dialogue
 * so entities pass behind SCR2 (dialog overlay). Reset to SPR_FRONT after. */
u8 g_ngpng_entity_prio = (u8)SPR_FRONT;

/* ---- Sizing / slot constants (fallbacks; real values come from CDEFS) ---- */
#ifndef NGPNG_AUTORUN_SPR_BASE
#define NGPNG_AUTORUN_SPR_BASE 0u
#endif
#ifndef NGPNG_AUTORUN_MAX_ENEMIES
#define NGPNG_AUTORUN_MAX_ENEMIES 16u
#endif
#ifndef NGPNG_AUTORUN_MAX_FX
#define NGPNG_AUTORUN_MAX_FX 8u
#endif
#ifndef NGPNG_AUTORUN_MAX_PROPS
#define NGPNG_AUTORUN_MAX_PROPS 16u
#endif
#ifndef NGPNG_AUTORUN_ENEMY_SLOT_COUNT
#define NGPNG_AUTORUN_ENEMY_SLOT_COUNT 16u
#endif
#ifndef NGPNG_AUTORUN_HUD_SPR_BASE
#define NGPNG_AUTORUN_HUD_SPR_BASE 56u
#endif
#ifndef NGPNG_AUTORUN_ENEMY_SPR_BASE
#define NGPNG_AUTORUN_ENEMY_SPR_BASE ((u8)(NGPNG_AUTORUN_SPR_BASE + 10u))
#endif
#ifndef NGPNG_AUTORUN_FX_SPR_BASE
#define NGPNG_AUTORUN_FX_SPR_BASE ((u8)(NGPNG_AUTORUN_SPR_BASE + 34u))
#endif
#ifndef NGPNG_AUTORUN_PROP_SPR_BASE
#define NGPNG_AUTORUN_PROP_SPR_BASE ((u8)(NGPNG_AUTORUN_SPR_BASE + 42u))
#endif
#ifndef NGPNG_AUTORUN_PROP_SPR_COUNT
#define NGPNG_AUTORUN_PROP_SPR_COUNT 14u
#endif
#ifndef NGPNG_AUTORUN_ENT_PREVIEW
#define NGPNG_AUTORUN_ENT_PREVIEW 1
#endif
#ifndef NGPNG_ENEMY_PARTS_MAX
#define NGPNG_ENEMY_PARTS_MAX 0u
#endif
#ifndef NGPNG_PERF7_LEGACY_REDRAW
#define NGPNG_PERF7_LEGACY_REDRAW 1
#endif

/* ==========================================================================
 * World entity activation system (NGPNG_WORLD_ACTIVATION)
 * Globals, init, tick and kill-notification functions.
 * Gated so zero overhead when feature is disabled.
 * ========================================================================== */
#if NGPNG_WORLD_ACTIVATION

/* Forward declarations — functions defined later in this file */
u8   ngpng_entity_role(const NgpSceneDef *sc, u8 type);
void ngpng_enemy_kill(NgpngEnemy *enemies, u8 *active_count, u8 idx);
void ngpng_enemy_hide(NgpngEnemy *enemies, u8 idx);
void ngpng_enemy_spawn(const NgpSceneDef *sc, NgpngEnemy *enemies,
    u8 *active_count, u8 *alloc_idx,
    const NgpngEnt *src, u8 ent_idx, u8 assigned_path_idx, u8 assigned_behavior, u8 assigned_flags);

NgpngWorldEnt g_ngpng_world_ents[NGPNG_MAX_WORLD_ENTITIES];
u8            g_ngpng_world_ent_count = 0u;

/* Set to 1 during world_tick deactivation so ngpng_enemy_kill does NOT also
 * mark the world entity as DEAD (it is merely frozen, not killed). */
static u8 s_world_deactivating = 0u;

void ngpng_world_init(const NgpSceneDef *sc)
{
    u8 i;
    u8 raw_flags;
    g_ngpng_world_ent_count = 0u;
    if (!sc || !sc->entities) return;
    for (i = 0u; i < sc->entity_count && g_ngpng_world_ent_count < (u8)NGPNG_MAX_WORLD_ENTITIES; ++i) {
        const NgpngEnt *e = &sc->entities[i];
        u8 role = ngpng_effective_role_at(sc, i);
        NgpngWorldEnt *we;
        if (role != NGPNG_ROLE_ENEMY) continue;   /* enemies only for now */
        we = &g_ngpng_world_ents[g_ngpng_world_ent_count];
        we->world_x    = (s16)((s16)e->x * 8);
        we->world_y    = (s16)((s16)e->y * 8);
        we->type       = e->type;
        we->role       = role;
        we->data       = e->data;
        we->ent_idx    = i;
        we->state      = NGPNG_WE_ALIVE;
        we->active_idx = 0xFFu;
        raw_flags      = (sc->entity_flags && i < sc->entity_count) ? sc->entity_flags[i] : 0u;
        we->flags      = (raw_flags & NGPNG_ENT_FLAG_RESPAWN) ? NGPNG_WE_FLAG_RESPAWN : 0u;
        we->_pad       = 0u;
        g_ngpng_world_ent_count = (u8)(g_ngpng_world_ent_count + 1u);
    }
}

void ngpng_world_on_enemy_killed(u8 pool_idx)
{
    u8 i;
    if (s_world_deactivating) return;  /* zone exit, not a real kill */
    for (i = 0u; i < g_ngpng_world_ent_count; ++i) {
        if (g_ngpng_world_ents[i].active_idx == pool_idx) {
            g_ngpng_world_ents[i].state      = NGPNG_WE_DEAD;
            g_ngpng_world_ents[i].active_idx = 0xFFu;
            return;
        }
    }
}

void ngpng_world_tick(const NgpSceneDef *sc,
    NgpngEnemy *enemies, u8 *enemy_active_count, u8 *enemy_alloc_idx,
    s16 cam_px, s16 cam_py)
{
    u8  i;
    s16 border;
    s16 lx;
    s16 rx;
    s16 ty;
    s16 by;

    if (!sc || !sc->entities) return;
    border = NGPNG_ACTIVATION_RADIUS_PX;
    lx = (s16)(cam_px - border);
    rx = (s16)(cam_px + 160 + border);
    ty = (s16)(cam_py - border);
    by = (s16)(cam_py + 152 + border);

    for (i = 0u; i < g_ngpng_world_ent_count; ++i) {
        NgpngWorldEnt *we = &g_ngpng_world_ents[i];
        u8 in_radius;

        /* COLLECTED = permanently gone, never respawn */
        if (we->state == NGPNG_WE_COLLECTED) continue;

        in_radius = (we->world_x >= lx && we->world_x < rx &&
                     we->world_y >= ty && we->world_y < by) ? 1u : 0u;

        if (in_radius && we->active_idx == 0xFFu) {
            /* --- Activate --- */
            u8 prev_alloc;
            u8 ent_path;
            u8 ent_behavior;
            u8 ent_flags;
            u8 prev_count;

            /* Permanently dead and no respawn flag: skip */
            if (we->state == NGPNG_WE_DEAD && !(we->flags & NGPNG_WE_FLAG_RESPAWN)) continue;

            ent_path     = (sc->entity_paths)     ? sc->entity_paths[we->ent_idx]                           : 0xFFu;
            ent_behavior = (sc->entity_behaviors) ? sc->entity_behaviors[we->ent_idx]                       : 0u;
            /* Strip RESPAWN bit from runtime ent_flags — it is a lifecycle flag, not a spawn flag */
            ent_flags    = (sc->entity_flags)     ? (u8)(sc->entity_flags[we->ent_idx] & ~NGPNG_ENT_FLAG_RESPAWN) : 0u;

            prev_count = *enemy_active_count;
            prev_alloc = *enemy_alloc_idx;
            ngpng_enemy_spawn(sc, enemies, enemy_active_count, enemy_alloc_idx,
                &sc->entities[we->ent_idx], we->ent_idx, ent_path, ent_behavior, ent_flags);

            if (*enemy_active_count > prev_count) {
                /* Slot used = alloc_idx - 1 (with wrap) */
                u8 assigned = (*enemy_alloc_idx == 0u) ?
                    (u8)((u8)NGPNG_AUTORUN_MAX_ENEMIES - 1u) :
                    (u8)(*enemy_alloc_idx - 1u);
                we->active_idx = assigned;
                we->state      = NGPNG_WE_ALIVE;
            }
            (void)prev_alloc;

        } else if (!in_radius && we->active_idx != 0xFFu) {
            /* --- Deactivate (freeze, not a kill) --- */
            s_world_deactivating = 1u;
            ngpng_enemy_kill(enemies, enemy_active_count, we->active_idx);
            s_world_deactivating = 0u;
            /* If RESPAWN flag: reset ALIVE now so re-entry will spawn it again */
            we->state      = NGPNG_WE_ALIVE;
            we->active_idx = 0xFFu;
        }
    }
}

#else  /* !NGPNG_WORLD_ACTIVATION — stub no-ops so callers always compile */

void ngpng_world_init(const NgpSceneDef *sc)      { (void)sc; }
void ngpng_world_on_enemy_killed(u8 pool_idx)     { (void)pool_idx; }
void ngpng_world_tick(const NgpSceneDef *sc,
    void *enemies, u8 *enemy_active_count, u8 *enemy_alloc_idx,
    s16 cam_px, s16 cam_py)
{
    (void)sc; (void)enemies; (void)enemy_active_count;
    (void)enemy_alloc_idx; (void)cam_px; (void)cam_py;
}

#endif /* NGPNG_WORLD_ACTIVATION */

/* ==========================================================================
 * Shared type / anim helpers (compiled when enemies or props are present)
 * ========================================================================== */
#if NGPNG_HAS_ENEMY || NGPNG_HAS_PROP_ACTOR || NGPNG_HAS_PLAYER

u8 ngpng_entity_role(const NgpSceneDef *sc, u8 type)
{
    if (!sc->type_roles) return (type == 0u) ? NGPNG_ROLE_PLAYER : NGPNG_ROLE_ENEMY;
    if (type >= sc->type_role_count) return NGPNG_ROLE_PROP;
    return sc->type_roles[type];
}

u8 ngpng_effective_role_at(const NgpSceneDef *sc, u8 idx)
{
    u8 ov;
    if (!sc || !sc->entities || idx >= sc->entity_count) return NGPNG_ROLE_PROP;
    if (sc->entity_role_override) {
        ov = sc->entity_role_override[idx];
        if (ov != 0xFFu) return ov;
    }
    return ngpng_entity_role(sc, sc->entities[idx].type);
}

u8 ngpng_type_u8(const u8 *arr, u8 count, u8 type, u8 fallback)
{
    if (!arr || type >= count) return fallback;
    return arr[type];
}

s8 ngpng_type_s8(const s8 *arr, u8 count, u8 type, s8 fallback)
{
    if (!arr || type >= count) return fallback;
    return arr[type];
}

s8 ngpng_type_attack_s8(const s8 *arr, const s8 *fallback_arr, u8 count, u8 type, s8 fallback)
{
    if (arr && type < count) return arr[type];
    if (fallback_arr && type < count) return fallback_arr[type];
    return fallback;
}

u8 ngpng_type_attack_u8(const u8 *arr, const u8 *fallback_arr, u8 count, u8 type, u8 fallback)
{
    if (arr && type < count) return arr[type];
    if (fallback_arr && type < count) return fallback_arr[type];
    return fallback;
}

u8 ngpng_type_attack_damage_u8(const u8 *arr, const u8 *fallback_arr, u8 count, u8 type, u8 fallback)
{
    u8 v = 0u;
    if (arr && type < count) {
        v = arr[type];
        if (v != 0u) return v;
    }
    if (fallback_arr && type < count) return fallback_arr[type];
    return fallback;
}

u8 ngpng_type_anim_start(const NgpSceneDef *sc, u8 type, u8 state)
{
    if (!sc) return 0u;
    switch (state) {
        case NGPNG_ANIM_WALK:  return ngpng_type_u8(sc->type_anim_walk_start,  sc->type_role_count, type, 0u);
        case NGPNG_ANIM_JUMP:  return ngpng_type_u8(sc->type_anim_jump_start,  sc->type_role_count, type, 0u);
        case NGPNG_ANIM_FALL:  return ngpng_type_u8(sc->type_anim_fall_start,  sc->type_role_count, type, 0u);
        case NGPNG_ANIM_DEATH: return ngpng_type_u8(sc->type_anim_death_start, sc->type_role_count, type, 0u);
        default:               return ngpng_type_u8(sc->type_anim_idle_start,  sc->type_role_count, type, 0u);
    }
}

u8 ngpng_type_anim_count(const NgpSceneDef *sc, u8 type, u8 state)
{
    if (!sc) return 1u;
    switch (state) {
        case NGPNG_ANIM_WALK:  return ngpng_type_u8(sc->type_anim_walk_count,  sc->type_role_count, type, 0u);
        case NGPNG_ANIM_JUMP:  return ngpng_type_u8(sc->type_anim_jump_count,  sc->type_role_count, type, 0u);
        case NGPNG_ANIM_FALL:  return ngpng_type_u8(sc->type_anim_fall_count,  sc->type_role_count, type, 0u);
        case NGPNG_ANIM_DEATH: return ngpng_type_u8(sc->type_anim_death_count, sc->type_role_count, type, 0u);
        default:               return ngpng_type_u8(sc->type_anim_idle_count,  sc->type_role_count, type, 1u);
    }
}

u8 ngpng_type_anim_speed(const NgpSceneDef *sc, u8 type)
{
    return sc ? ngpng_type_u8(sc->type_anim_speed, sc->type_role_count, type, 6u) : 6u;
}

u8 ngpng_type_anim_frame_local(const NgpSceneDef *sc, u8 type, u8 state, u8 tick)
{
    u8 count = ngpng_type_anim_count(sc, type, state);
    u8 spd   = ngpng_type_anim_speed(sc, type);
    if (count == 0u) { count = ngpng_type_anim_count(sc, type, NGPNG_ANIM_IDLE); state = NGPNG_ANIM_IDLE; }
    if (count == 0u) return 0u;
    if (spd == 0u) spd = 1u;
    /* Fast paths for common pow2 speed and count values.
     * Replaces u8 software div/mod (~60-100 cycles each) with shifts/masks. */
    {
        u8 frame = (spd == 1u) ? tick :
                   (spd == 2u) ? (u8)(tick >> 1) :
                   (spd == 4u) ? (u8)(tick >> 2) :
                   (u8)(tick / spd);
        return (count == 1u) ? 0u :
               (count == 2u) ? (u8)(frame & 1u) :
               (count == 4u) ? (u8)(frame & 3u) :
               (u8)(frame % count);
    }
}

u8 ngpng_type_anim_frame_abs(const NgpSceneDef *sc, u8 type, u8 state, u8 tick)
{
    u8 start = ngpng_type_anim_start(sc, type, state);
    return (u8)(start + ngpng_type_anim_frame_local(sc, type, state, tick));
}

/* ngpng_add_s8_clamped / ngpng_clamp_s8_range: static helpers used internally.
 * NOT exported in entities.h — the generated file keeps its own static copies
 * for shooting/bullet and player-physics code that stays there. */
static s8 ngpng_add_s8_clamped(s8 value, s8 delta)
{
    s16 sum = (s16)value + (s16)delta;
    if (sum >  127) return  127;
    if (sum < -127) return -127;
    return (s8)sum;
}

static s8 ngpng_clamp_s8_range(s8 value, s8 min_value, s8 max_value)
{
    if (value < min_value) return min_value;
    if (value > max_value) return max_value;
    return value;
}

u8 ngpng_attack_box_count(const NgpSceneDef *sc, u8 type)
{
    if (!sc) return 0u;
    return ngpng_type_u8(sc->attack_hitbox_count, sc->type_role_count, type, 0u);
}

u8 ngpng_attack_box_start(const NgpSceneDef *sc, u8 type)
{
    if (!sc) return 0u;
    return ngpng_type_u8(sc->attack_hitbox_start, sc->type_role_count, type, 0u);
}

u8 ngpng_attack_window_active(u8 anim_frame, u8 active_start, u8 active_len, u8 active_anim_state, u8 cur_anim_state)
{
    u8 i;
    if (active_anim_state != 0xFFu && active_anim_state != cur_anim_state) return 0u;
    if (active_len == 0u || active_len >= 4u) return 1u;
    anim_frame   = (u8)(anim_frame   & 0x03u);
    active_start = (u8)(active_start & 0x03u);
    for (i = 0u; i < active_len; ++i) {
        if (anim_frame == (u8)((active_start + i) & 0x03u)) return 1u;
    }
    return 0u;
}

u8 ngpng_find_first_type_by_role(const NgpSceneDef *sc, u8 role)
{
    u8 i;
    for (i = 0; i < sc->type_role_count; ++i) if (sc->type_roles[i] == role) return i;
    return 0xFFu;
}

u8 ngpng_first_flags_by_role(const NgpSceneDef *sc, u8 role)
{
    u8 i;
    if (!sc || !sc->entities) return 0u;
    for (i = 0u; i < sc->entity_count; ++i) {
        if (ngpng_effective_role_at(sc, i) != role) continue;
        if (!sc->entity_flags) return 0u;
        return sc->entity_flags[i];
    }
    return 0u;
}

u8 ngpng_count_types_by_role(const NgpSceneDef *sc, u8 role)
{
    u8 i;
    u8 count = 0u;
    if (!sc || !sc->type_roles) return 0u;
    for (i = 0; i < sc->type_role_count; ++i) if (sc->type_roles[i] == role) count = (u8)(count + 1u);
    return count;
}

u8 ngpng_find_nth_type_by_role(const NgpSceneDef *sc, u8 role, u8 nth)
{
    u8 i;
    u8 seen = 0u;
    if (!sc || !sc->type_roles) return 0xFFu;
    for (i = 0; i < sc->type_role_count; ++i) {
        if (sc->type_roles[i] != role) continue;
        if (seen == nth) return i;
        seen = (u8)(seen + 1u);
    }
    return 0xFFu;
}

void ngpng_player_apply_form(const NgpSceneDef *sc, u8 form_idx,
    u8 *player_type, s8 *player_hb_x, s8 *player_hb_y, u8 *player_hb_w, u8 *player_hb_h,
    s8 *player_body_x, s8 *player_body_y, u8 *player_body_w, u8 *player_body_h,
    s8 *player_render_off_x, s8 *player_render_off_y, u8 *player_frame_w, u8 *player_frame_h,
    u8 *player_hp, u8 *player_hp_max, u8 reset_hp)
{
    u8 type;
    u8 hp_max;
    if (!sc) return;
    type = ngpng_find_nth_type_by_role(sc, NGPNG_ROLE_PLAYER, form_idx);
    if (type == 0xFFu) type = ngpng_find_first_type_by_role(sc, NGPNG_ROLE_PLAYER);
    *player_type = type;
    if (type == 0xFFu) return;
    *player_hb_x = ngpng_type_s8(sc->hitbox_x, sc->type_role_count, type, 0);
    *player_hb_y = ngpng_type_s8(sc->hitbox_y, sc->type_role_count, type, 0);
    *player_hb_w = ngpng_type_u8(sc->hitbox_w, sc->type_role_count, type, 8u);
    *player_hb_h = ngpng_type_u8(sc->hitbox_h, sc->type_role_count, type, 8u);
    *player_body_x = ngpng_type_s8(sc->body_x, sc->type_role_count, type, *player_hb_x);
    *player_body_y = ngpng_type_s8(sc->body_y, sc->type_role_count, type, *player_hb_y);
    *player_body_w = ngpng_type_u8(sc->body_w, sc->type_role_count, type, *player_hb_w);
    *player_body_h = ngpng_type_u8(sc->body_h, sc->type_role_count, type, *player_hb_h);
    *player_render_off_x = ngpng_type_s8(sc->render_off_x, sc->type_role_count, type,
        (s8)((*player_hb_x < 0) ? *player_hb_x : 0));
    *player_render_off_y = ngpng_type_s8(sc->render_off_y, sc->type_role_count, type,
        (s8)((*player_hb_y < 0) ? *player_hb_y : 0));
    *player_frame_w = ngpng_type_u8(sc->frame_w, sc->type_role_count, type, 8u);
    *player_frame_h = ngpng_type_u8(sc->frame_h, sc->type_role_count, type, 8u);
    hp_max = ngpng_type_u8(sc->type_hp, sc->type_role_count, type, 3u);
    *player_hp_max = hp_max;
    if (reset_hp || *player_hp > hp_max) *player_hp = hp_max;
}

u8 ngpng_rects_overlap(s16 ax, s16 ay, u8 aw, u8 ah, s16 bx, s16 by, u8 bw, u8 bh)
{
    if ((s16)(ax + aw) <= bx) return 0;
    if ((s16)(bx + bw) <= ax) return 0;
    if ((s16)(ay + ah) <= by) return 0;
    if ((s16)(by + bh) <= ay) return 0;
    return 1;
}

static u8 ngpng_rects_touch_or_overlap(s16 ax, s16 ay, u8 aw, u8 ah, s16 bx, s16 by, u8 bw, u8 bh)
{
    if ((s16)(ax + aw) < bx) return 0;
    if ((s16)(bx + bw) < ax) return 0;
    if ((s16)(ay + ah) < by) return 0;
    if ((s16)(by + bh) < ay) return 0;
    return 1;
}

void ngpng_clamp_world_rect(const NgpSceneDef *sc, s16 *wx, s16 *wy, u8 w, u8 h)
{
    s16 max_x;
    s16 max_y;
    if (!sc || !wx || !wy) return;
    max_x = (s16)(sc->map_w * 8u);
    max_y = (s16)(sc->map_h * 8u);
    if (max_x < (s16)w) max_x = (s16)w;
    if (max_y < (s16)h) max_y = (s16)h;
    max_x = (s16)(max_x - (s16)w);
    max_y = (s16)(max_y - (s16)h);
    if (*wx < 0) *wx = 0;
    if (*wy < 0) *wy = 0;
    if (*wx > max_x) *wx = max_x;
    if (*wy > max_y) *wy = max_y;
}

void ngpng_clamp_camera_rect(s16 *wx, s16 *wy, s16 cam_px, s16 cam_py, u8 w, u8 h)
{
    s16 min_x;
    s16 min_y;
    s16 max_x;
    s16 max_y;
    if (!wx || !wy) return;
    min_x = cam_px;
    min_y = cam_py;
    max_x = (s16)(cam_px + (s16)(160 - (s16)w));
    max_y = (s16)(cam_py + (s16)(152 - (s16)h));
    if (max_x < min_x) max_x = min_x;
    if (max_y < min_y) max_y = min_y;
    if (*wx < min_x) *wx = min_x;
    if (*wy < min_y) *wy = min_y;
    if (*wx > max_x) *wx = max_x;
    if (*wy > max_y) *wy = max_y;
}

s8 ngpng_step_toward(s16 cur, s16 dst, s8 step)
{
    s16 diff = (s16)(dst - cur);
    if (diff > (s16)step)  return step;
    if (diff < (s16)(-step)) return (s8)(-step);
    return (s8)diff; /* snap: exact delta when within reach */
}

void ngpng_find_player_spawn(const NgpSceneDef *sc, s16 cam_px, s16 cam_py, s16 *sx, s16 *sy)
{
    u8 i;
    *sx = 24;
    *sy = 72;
    if (!sc->entities) return;
    for (i = 0; i < sc->entity_count; ++i) {
        const NgpngEnt *e = &sc->entities[i];
        s8 rox;
        s8 roy;
        if (ngpng_effective_role_at(sc, i) != NGPNG_ROLE_PLAYER) continue;
        rox = ngpng_type_s8(sc->render_off_x, sc->type_role_count, e->type, 0);
        roy = ngpng_type_s8(sc->render_off_y, sc->type_role_count, e->type, 0);
        *sx = (s16)((s16)e->x * 8 - rox - cam_px);
        *sy = (s16)((s16)e->y * 8 - roy - cam_py);
        return;
    }
}

void ngpng_place_player_on_respawn(const NgpSceneDef *sc, u8 checkpoint_region,
    s16 *cam_px, s16 *cam_py, s16 *sx, s16 *sy)
{
    s16 wx;
    s16 wy;
    if (!sc || !cam_px || !cam_py || !sx || !sy) return;
    if (checkpoint_region >= sc->region_count || !sc->regions) {
        ngpng_find_player_spawn(sc, *cam_px, *cam_py, sx, sy);
        ngpng_update_plane_scroll(sc, *cam_px, *cam_py);
        return;
    }
    wx = (s16)(sc->regions[checkpoint_region].x * 8);
    wy = (s16)(sc->regions[checkpoint_region].y * 8);
    *cam_px = (s16)(wx - 80);
    *cam_py = (s16)(wy - 72);
    if (*cam_px < 0) *cam_px = 0;
    if (*cam_py < 0) *cam_py = 0;
    ngpng_apply_camera_constraints(sc, cam_px, cam_py);
    *sx = (s16)(wx - *cam_px);
    *sy = (s16)(wy - *cam_py);
    ngpng_update_plane_scroll(sc, *cam_px, *cam_py);
}

#endif /* NGPNG_HAS_ENEMY || NGPNG_HAS_PROP_ACTOR */

/* ==========================================================================
 * Sprite draw helpers
 * ========================================================================== */
#if NGPNG_HAS_ENEMY || NGPNG_HAS_FX || NGPNG_HAS_PROP_ACTOR

u8 ngpng_sprite_mspr_draw(u8 spr_start, s16 x, s16 y, const NgpcMetasprite *def, u8 flags)
{
    u8 i;
    u8 count;
    u8 group_hflip = (flags & SPR_HFLIP) ? 1u : 0u;
    u8 group_vflip = (flags & SPR_VFLIP) ? 1u : 0u;
    u8 priority    = (u8)(flags & 0x18u);
    if (!def) return 0u;
    if (spr_start >= 64u) return 0u;
    count = def->count;
    if ((u16)spr_start + count > 64u) count = (u8)(64u - spr_start);
    for (i = 0; i < count; ++i) {
        const MsprPart *p = &def->parts[i];
        s16 px;
        s16 py;
        u8 part_flags = p->flags;
        if (group_hflip) px = (s16)(x + (s16)(def->width - 8u) - (s16)p->ox);
        else             px = (s16)(x + (s16)p->ox);
        if (group_vflip) py = (s16)(y + (s16)(def->height - 8u) - (s16)p->oy);
        else             py = (s16)(y + (s16)p->oy);
        if (group_hflip) part_flags ^= SPR_HFLIP;
        if (group_vflip) part_flags ^= SPR_VFLIP;
        part_flags = (u8)((part_flags & (u8)~0x18u) | priority);
        if (px < -7 || px > 159 || py < -7 || py > 151)
            ngpc_sprite_hide((u8)(spr_start + i));
        else
            ngpc_sprite_set((u8)(spr_start + i),
                (u8)((u16)px & 0xFFu), (u8)((u16)py & 0xFFu),
                p->tile, p->pal, part_flags);
    }
    return count;
}

void ngpng_sprite_hide_range(u8 start, u8 count)
{
    u8 i;
    for (i = 0; i < count; ++i) {
        if ((u16)start + i >= 64u) break;
        ngpc_sprite_hide((u8)(start + i));
    }
}

static void ngpng_sprite_mspr_move(u8 spr_start, s16 x, s16 y, const NgpcMetasprite *def, u8 flags)
{
    u8 i;
    u8 count;
    u8 group_hflip = (flags & SPR_HFLIP) ? 1u : 0u;
    u8 group_vflip = (flags & SPR_VFLIP) ? 1u : 0u;
    if (!def) return;
    if (spr_start >= 64u) return;
    count = def->count;
    if ((u16)spr_start + count > 64u) count = (u8)(64u - spr_start);
    for (i = 0; i < count; ++i) {
        const MsprPart *p = &def->parts[i];
        s16 px;
        s16 py;
        if (group_hflip) px = (s16)(x + (s16)(def->width  - 8u) - (s16)p->ox);
        else             px = (s16)(x + (s16)p->ox);
        if (group_vflip) py = (s16)(y + (s16)(def->height - 8u) - (s16)p->oy);
        else             py = (s16)(y + (s16)p->oy);
        if (px < -7 || px > 159 || py < -7 || py > 151)
            ngpc_sprite_hide((u8)(spr_start + i));
        else
            ngpc_sprite_move((u8)(spr_start + i),
                (u8)((u16)px & 0xFFu), (u8)((u16)py & 0xFFu));
    }
}

static u8 ngpng_sprite_mspr_fully_visible(s16 x, s16 y, const NgpcMetasprite *def)
{
    s16 right;
    s16 bottom;
    if (!def) return 0u;
    right = (s16)(x + (s16)def->width - 1);
    bottom = (s16)(y + (s16)def->height - 1);
    if (x < 0 || y < 0) return 0u;
    if (right > 159 || bottom > 151) return 0u;
    return 1u;
}

static u8 ngpng_sprite_mspr_intersects_screen(s16 x, s16 y, const NgpcMetasprite *def)
{
    s16 right;
    s16 bottom;
    if (!def) return 0u;
    right = (s16)(x + (s16)def->width);
    bottom = (s16)(y + (s16)def->height);
    if (x >= 160 || y >= 152) return 0u;
    if (right <= 0 || bottom <= 0) return 0u;
    return 1u;
}

static void ngpng_sprite_mspr_sync(u8 spr_start, s16 x, s16 y, const NgpcMetasprite *def,
    u8 frame_idx, u8 render_flags,
    u8 *visible, u8 *last_spr, u8 *last_used_parts,
    s16 *last_x, s16 *last_y, u8 *last_frame, u8 *last_flags)
{
    u8 count;
    u8 same_slot;
    if (!def || !visible || !last_spr || !last_used_parts ||
            !last_x || !last_y || !last_frame || !last_flags) return;
    if (spr_start >= 64u) return;
    count = def->count;
    if ((u16)spr_start + count > 64u) count = (u8)(64u - spr_start);
    if (count == 0u) {
        if (*visible && *last_used_parts > 0u)
            ngpng_sprite_hide_range(*last_spr, *last_used_parts);
        *visible = 0u;
        *last_used_parts = 0u;
        *last_frame = 0xFFu;
        *last_flags = 0xFFu;
        *last_x = (s16)-32768;
        *last_y = (s16)-32768;
        return;
    }
    if (!*visible) {
        ngpng_sprite_mspr_draw(spr_start, x, y, def, render_flags);
        *visible = 1u;
        *last_spr = spr_start;
        *last_used_parts = count;
        *last_frame = frame_idx;
        *last_flags = render_flags;
        *last_x = x;
        *last_y = y;
        return;
    }
    same_slot = (u8)(*last_spr == spr_start);
    if (!same_slot) {
        if (*last_used_parts > 0u) ngpng_sprite_hide_range(*last_spr, *last_used_parts);
        ngpng_sprite_mspr_draw(spr_start, x, y, def, render_flags);
    } else if (*last_frame != frame_idx || *last_flags != render_flags || *last_used_parts != count) {
        ngpng_sprite_mspr_draw(spr_start, x, y, def, render_flags);
        if (*last_used_parts > count)
            ngpng_sprite_hide_range((u8)(spr_start + count), (u8)(*last_used_parts - count));
    } else if (*last_x != x || *last_y != y) {
        if (ngpng_sprite_mspr_fully_visible(*last_x, *last_y, def) &&
                ngpng_sprite_mspr_fully_visible(x, y, def))
            ngpng_sprite_mspr_move(spr_start, x, y, def, render_flags);
        else
            ngpng_sprite_mspr_draw(spr_start, x, y, def, render_flags);
    } else {
        return;
    }
    *visible = 1u;
    *last_spr = spr_start;
    *last_used_parts = count;
    *last_frame = frame_idx;
    *last_flags = render_flags;
    *last_x = x;
    *last_y = y;
}

#if NGPNG_HAS_ENEMY
static u8 ngpng_enemy_slot_span(void)
{
    u8 span = (u8)NGPNG_ENEMY_PARTS_MAX;
    if (span != 0u) return span;
    if ((u8)NGPNG_AUTORUN_MAX_ENEMIES == 0u) return 1u;
    span = (u8)(NGPNG_AUTORUN_ENEMY_SLOT_COUNT / (u8)NGPNG_AUTORUN_MAX_ENEMIES);
    return (span != 0u) ? span : 1u;
}

static u8 ngpng_enemy_slot_base_for_idx(u8 idx, u8 *slot_out, u8 *span_out)
{
    u8 span = ngpng_enemy_slot_span();
    u16 slot = (u16)NGPNG_AUTORUN_ENEMY_SPR_BASE + ((u16)idx * (u16)span);
    u16 end = (u16)NGPNG_AUTORUN_ENEMY_SPR_BASE + (u16)NGPNG_AUTORUN_ENEMY_SLOT_COUNT;
    if (!slot_out) return 0u;
    if (slot >= 64u || slot >= end) return 0u;
    if (slot + span > end) span = (u8)(end - slot);
    if (slot + span > 64u) span = (u8)(64u - slot);
    if (span == 0u) return 0u;
    *slot_out = (u8)slot;
    if (span_out) *span_out = span;
    return 1u;
}
#endif

#if NGPNG_HAS_PROP_ACTOR
static u32 s_ngpng_prop_spr_mask = 0UL;

static u8 ngpng_prop_spr_tracked_count(void)
{
    return (NGPNG_AUTORUN_PROP_SPR_COUNT > 32u) ? 32u : (u8)NGPNG_AUTORUN_PROP_SPR_COUNT;
}

static u32 ngpng_prop_spr_bits(u8 off, u8 count)
{
    u32 bits = 0UL;
    u8 tracked = ngpng_prop_spr_tracked_count();
    u8 i;
    if (count == 0u || off >= tracked) return 0UL;
    if ((u16)off + count > tracked) count = (u8)(tracked - off);
    for (i = 0u; i < count; ++i)
        bits |= (1UL << (off + i));
    return bits;
}

static u8 ngpng_prop_spr_valid(u8 spr, u8 count)
{
    u8 tracked = ngpng_prop_spr_tracked_count();
    u16 off;
    if (count == 0u || spr < (u8)NGPNG_AUTORUN_PROP_SPR_BASE) return 0u;
    off = (u16)(spr - (u8)NGPNG_AUTORUN_PROP_SPR_BASE);
    if (off >= tracked) return 0u;
    if (off + count > tracked) return 0u;
    return 1u;
}

static void ngpng_prop_spr_mark(u8 spr, u8 count)
{
    u8 off;
    if (!ngpng_prop_spr_valid(spr, count)) return;
    off = (u8)(spr - (u8)NGPNG_AUTORUN_PROP_SPR_BASE);
    s_ngpng_prop_spr_mask |= ngpng_prop_spr_bits(off, count);
}

static void ngpng_prop_spr_free(u8 spr, u8 count)
{
    u8 off;
    if (!ngpng_prop_spr_valid(spr, count)) return;
    off = (u8)(spr - (u8)NGPNG_AUTORUN_PROP_SPR_BASE);
    s_ngpng_prop_spr_mask &= ~ngpng_prop_spr_bits(off, count);
}

static u8 ngpng_prop_spr_can_extend(u8 spr, u8 old_count, u8 new_count)
{
    u8 off;
    u8 tracked = ngpng_prop_spr_tracked_count();
    u32 bits;
    if (!ngpng_prop_spr_valid(spr, old_count)) return 0u;
    if (new_count <= old_count) return 1u;
    off = (u8)(spr - (u8)NGPNG_AUTORUN_PROP_SPR_BASE);
    if ((u16)off + new_count > tracked) return 0u;
    bits = ngpng_prop_spr_bits((u8)(off + old_count), (u8)(new_count - old_count));
    return ((s_ngpng_prop_spr_mask & bits) == 0UL) ? 1u : 0u;
}

static u8 ngpng_prop_spr_alloc(u8 count, u8 *spr_out)
{
    u8 off;
    u8 tracked = ngpng_prop_spr_tracked_count();
    if (!spr_out || count == 0u || count > tracked) return 0u;
    for (off = 0u; (u16)off + count <= tracked; ++off) {
        u32 bits = ngpng_prop_spr_bits(off, count);
        if ((s_ngpng_prop_spr_mask & bits) != 0UL) continue;
        s_ngpng_prop_spr_mask |= bits;
        *spr_out = (u8)((u8)NGPNG_AUTORUN_PROP_SPR_BASE + off);
        return 1u;
    }
    return 0u;
}

static u8 ngpng_prop_spr_acquire(const NgpngPropActor *prop, u8 count, u8 *spr_out)
{
    u8 cur_spr;
    u8 cur_count;
    if (!prop || !spr_out || count == 0u) return 0u;
    cur_spr = prop->last_draw_spr;
    cur_count = prop->last_used_parts;
    if (prop->draw_visible && cur_count > 0u) {
        if (!ngpng_prop_spr_valid(cur_spr, cur_count)) return 0u;
        if (count <= cur_count) {
            *spr_out = cur_spr;
            return 1u;
        }
        if (ngpng_prop_spr_can_extend(cur_spr, cur_count, count)) {
            ngpng_prop_spr_mark((u8)(cur_spr + cur_count), (u8)(count - cur_count));
            *spr_out = cur_spr;
            return 1u;
        }
        if (!ngpng_prop_spr_alloc(count, spr_out)) return 0u;
        ngpng_prop_spr_free(cur_spr, cur_count);
        return 1u;
    }
    return ngpng_prop_spr_alloc(count, spr_out);
}
#endif

void ngpng_player_layer_sync(u8 spr_start, u8 slot_count, s16 x, s16 y, u8 frame_idx,
    const MsprAnimFrame *anim, u8 anim_count, u8 render_flags,
    u8 *visible, s16 *last_x, s16 *last_y, u8 *last_frame, u8 *last_flags)
{
    const NgpcMetasprite *def;
    u8 drawn;
    if (!anim || anim_count == 0u) return;
    frame_idx = (u8)(frame_idx % anim_count);
    def = anim[frame_idx].frame;
    if (!def) return;
    if (!*visible) {
        drawn = ngpng_sprite_mspr_draw(spr_start, x, y, def, render_flags);
        if (slot_count > drawn) ngpng_sprite_hide_range((u8)(spr_start + drawn), (u8)(slot_count - drawn));
        if (drawn > 0u) {
            *visible    = 1u;
            *last_frame = frame_idx;
            *last_flags = render_flags;
            *last_x     = x;
            *last_y     = y;
        }
        return;
    }
    if (*last_frame != frame_idx || *last_flags != render_flags) {
        drawn = ngpng_sprite_mspr_draw(spr_start, x, y, def, render_flags);
        if (slot_count > drawn) ngpng_sprite_hide_range((u8)(spr_start + drawn), (u8)(slot_count - drawn));
        *visible    = (u8)(drawn > 0u);
        *last_frame = frame_idx;
        *last_flags = render_flags;
        *last_x     = x;
        *last_y     = y;
        return;
    }
    if (*last_x != x || *last_y != y) {
        if (ngpng_sprite_mspr_fully_visible(*last_x, *last_y, def) &&
                ngpng_sprite_mspr_fully_visible(x, y, def))
            ngpng_sprite_mspr_move(spr_start, x, y, def, render_flags);
        else
            ngpng_sprite_mspr_draw(spr_start, x, y, def, render_flags);
        *last_x = x;
        *last_y = y;
    }
}

u8 ngpng_entity_sprite_info(const NgpSceneDef *sc, u8 type, u8 frame_idx,
    u16 *tile, u8 *pal, u8 *flags, s16 *ox, s16 *oy)
{
    const NgpcMetasprite *def;
    const MsprPart *part;
    if (!sc->resolve_entity_frame) return 0u;
    def = sc->resolve_entity_frame(type, frame_idx);
    if (!def || def->count == 0u) return 0u;
    part  = &def->parts[0];
    *tile  = part->tile;
    *pal   = part->pal;
    *flags = (u8)(SPR_FRONT | (u8)part->flags);
    *ox    = (s16)part->ox;
    *oy    = (s16)part->oy;
    return 1u;
}

#endif /* NGPNG_HAS_ENEMY || NGPNG_HAS_FX || NGPNG_HAS_PROP_ACTOR */

/* ==========================================================================
 * Enemy management
 * ========================================================================== */
#if NGPNG_HAS_ENEMY

static void ngpng_enemy_hide_cached(NgpngEnemy *enemies, u8 idx)
{
    u8 slot;
    u8 span;
    if (ngpng_enemy_slot_base_for_idx(idx, &slot, &span) &&
            (enemies[idx].visible || enemies[idx].last_used_parts > 0u)) {
        ngpng_sprite_hide_range(slot, span);
    }
    enemies[idx].visible         = 0u;
    enemies[idx].last_used_parts = 0u;
    enemies[idx].last_sx         = (s16)-32768;
    enemies[idx].last_sy         = (s16)-32768;
    enemies[idx].last_tile       = 0xFFFFu;
    enemies[idx].last_flags      = 0xFFu;
    enemies[idx].last_frame      = 0xFFu;
}

void ngpng_enemy_hide(NgpngEnemy *enemies, u8 idx)
{
    ngpng_enemy_hide_cached(enemies, idx);
}

/* Update the per-enemy draw cache.
 * OPT-ANIM-CACHE: anim start/count/speed are cached per enemy and refreshed from
 * ROM only when the animation state changes (rare: ~once per patrol bounce).
 * Every other frame: pure RAM arithmetic, 0 ROM lookups.
 * resolve_entity_frame is only called when the output frame index changes. */
static void ngpng_enemy_update_draw_cache(const NgpSceneDef *sc, NgpngEnemy *e)
{
    u8 anim_st;
    u8 new_frame;
    u8 local_frame;
    u8 spd_frame;
    if (!sc || !sc->resolve_entity_frame) return;
    anim_st = ((e->vy < (s8)-1) ? NGPNG_ANIM_JUMP :
              ((e->vy > (s8)1)  ? NGPNG_ANIM_FALL :
              ((e->vx != 0)     ? NGPNG_ANIM_WALK : NGPNG_ANIM_IDLE)));
    /* Refresh anim cache on state change only — 3-5 ROM reads total, not per frame */
    if (anim_st != e->cached_anim_st) {
        e->cached_anim_st    = anim_st;
        e->cached_anim_start = ngpng_type_anim_start(sc, e->type, anim_st);
        e->cached_anim_count = ngpng_type_anim_count(sc, e->type, anim_st);
        e->cached_anim_spd   = ngpng_type_anim_speed(sc, e->type);
        if (e->cached_anim_count == 0u) {
            e->cached_anim_count = ngpng_type_anim_count(sc, e->type, NGPNG_ANIM_IDLE);
            e->cached_anim_start = ngpng_type_anim_start(sc, e->type, NGPNG_ANIM_IDLE);
        }
        if (e->cached_anim_count == 0u) e->cached_anim_count = 1u;
        if (e->cached_anim_spd   == 0u) e->cached_anim_spd   = 1u;
    }
    /* Compute frame — same fast-paths as ngpng_type_anim_frame_local, all RAM */
    spd_frame = (e->cached_anim_spd == 1u) ? e->anim :
                (e->cached_anim_spd == 2u) ? (u8)(e->anim >> 1) :
                (e->cached_anim_spd == 4u) ? (u8)(e->anim >> 2) :
                (u8)(e->anim / e->cached_anim_spd);
    local_frame = (e->cached_anim_count == 1u) ? 0u :
                  (e->cached_anim_count == 2u) ? (u8)(spd_frame & 1u) :
                  (e->cached_anim_count == 4u) ? (u8)(spd_frame & 3u) :
                  (u8)(spd_frame % e->cached_anim_count);
    new_frame = (u8)(e->cached_anim_start + local_frame);
    if (new_frame != e->cached_anim_frame) {
        e->cached_anim_frame = new_frame;
        e->cached_def = sc->resolve_entity_frame(e->type, new_frame);
    }
}

void ngpng_enemies_clear(NgpngEnemy *enemies, u8 *active_count, u8 *alloc_idx)
{
    u8 i;
    for (i = 0; i < (u8)NGPNG_AUTORUN_MAX_ENEMIES; ++i) {
        enemies[i].active    = 0u;
        enemies[i].visible   = 0u;
        enemies[i].last_used_parts = 0u;
        enemies[i].last_sx   = (s16)-32768;
        enemies[i].last_sy   = (s16)-32768;
        enemies[i].last_tile = 0xFFFFu;
        enemies[i].cached_anim_st    = 0xFFu; /* force refresh on first update */
        enemies[i].cached_anim_start = 0u;
        enemies[i].cached_anim_count = 0u;
        enemies[i].cached_anim_spd   = 0u;
        enemies[i].cached_anim_frame = 0xFFu;
        enemies[i].cached_def        = 0;
    }
    *active_count = 0u;
    *alloc_idx    = 0u;
}

void ngpng_enemy_kill(NgpngEnemy *enemies, u8 *active_count, u8 idx)
{
    if (!enemies[idx].active) return;
    enemies[idx].active = 0u;
    ngpng_enemy_hide(enemies, idx);
    if (*active_count > 0u) *active_count = (u8)(*active_count - 1u);
    ngpng_world_on_enemy_killed(idx);  /* no-op when NGPNG_WORLD_ACTIVATION=0 */
}

void ngpng_enemy_spawn(const NgpSceneDef *sc, NgpngEnemy *enemies,
    u8 *active_count, u8 *alloc_idx,
    const NgpngEnt *src, u8 ent_idx, u8 assigned_path_idx, u8 assigned_behavior, u8 assigned_flags)
{
    u8 k;
    if (ngpng_entity_role(sc, src->type) != NGPNG_ROLE_ENEMY) return;
    if (*active_count >= (u8)NGPNG_AUTORUN_MAX_ENEMIES) return;
    for (k = 0; k < (u8)NGPNG_AUTORUN_MAX_ENEMIES; ++k) {
        u8 i = (u8)(*alloc_idx + k);
        if (i >= (u8)NGPNG_AUTORUN_MAX_ENEMIES) i = (u8)(i - (u8)NGPNG_AUTORUN_MAX_ENEMIES);
        if (!enemies[i].active) {
            enemies[i].active      = 1u;
            enemies[i].type        = src->type;
            enemies[i].hp          = ngpng_type_u8(sc->type_hp, sc->type_role_count, src->type, 1u);
            enemies[i].anim        = 0u;
            enemies[i].data        = src->data;
            enemies[i].path_idx    = 0xFFu;
            enemies[i].path_step   = 0u;
            enemies[i].behavior    = assigned_behavior;
            enemies[i].patrol_min  = 0;
            enemies[i].patrol_max  = 0;
            /* OPT-2A-BOUNDS: pre-computed patrol world-X bounds from generator.
             * ent_idx=0xFF = wave spawn (no static bounds available). */
            if (assigned_behavior == (u8)NGPNG_BEHAVIOR_PATROL &&
                ent_idx != 0xFFu && sc->ent_patrol_min && sc->ent_patrol_max) {
                enemies[i].patrol_min = sc->ent_patrol_min[ent_idx];
                enemies[i].patrol_max = sc->ent_patrol_max[ent_idx];
            }
            enemies[i].fire_cd     = (u8)(24u + ((i & 3u) * 8u));
            enemies[i].last_frame  = 0xFFu;
            enemies[i].last_flags  = 0xFFu;
            enemies[i].pal         = 0u;
            enemies[i].flags       = (u8)SPR_FRONT;
            enemies[i].face_hflip  = 0u;
            enemies[i].hb_x  = ngpng_type_s8(sc->hitbox_x, sc->type_role_count, src->type, 0);
            enemies[i].hb_y  = ngpng_type_s8(sc->hitbox_y, sc->type_role_count, src->type, 0);
            enemies[i].hb_w  = ngpng_type_u8(sc->hitbox_w, sc->type_role_count, src->type, 8u);
            enemies[i].hb_h  = ngpng_type_u8(sc->hitbox_h, sc->type_role_count, src->type, 8u);
            enemies[i].body_x = ngpng_type_s8(sc->body_x, sc->type_role_count, src->type, enemies[i].hb_x);
            enemies[i].body_y = ngpng_type_s8(sc->body_y, sc->type_role_count, src->type, enemies[i].hb_y);
            enemies[i].body_w = ngpng_type_u8(sc->body_w, sc->type_role_count, src->type, enemies[i].hb_w);
            enemies[i].body_h = ngpng_type_u8(sc->body_h, sc->type_role_count, src->type, enemies[i].hb_h);
            enemies[i].atk_hb_x = ngpng_type_attack_s8(sc->attack_hitbox_x, sc->hitbox_x, sc->type_role_count, src->type, enemies[i].hb_x);
            enemies[i].atk_hb_y = ngpng_type_attack_s8(sc->attack_hitbox_y, sc->hitbox_y, sc->type_role_count, src->type, enemies[i].hb_y);
            enemies[i].atk_hb_w = ngpng_type_attack_u8(sc->attack_hitbox_w, sc->hitbox_w, sc->type_role_count, src->type, enemies[i].hb_w);
            enemies[i].atk_hb_h = ngpng_type_attack_u8(sc->attack_hitbox_h, sc->hitbox_h, sc->type_role_count, src->type, enemies[i].hb_h);
            enemies[i].damage  = ngpng_type_attack_damage_u8(sc->attack_hitbox_damage, sc->type_damage, sc->type_role_count, src->type, 1u);
            enemies[i].atk_kb_x = ngpng_type_attack_s8(sc->attack_hitbox_kb_x, 0, sc->type_role_count, src->type, 0);
            enemies[i].atk_kb_y = ngpng_type_attack_s8(sc->attack_hitbox_kb_y, 0, sc->type_role_count, src->type, 0);
            enemies[i].score   = ngpng_type_u8(sc->type_score, sc->type_role_count, src->type, 0u);
            enemies[i].ent_flags = assigned_flags;
            enemies[i].gravity = ngpng_type_u8(sc->type_gravity, sc->type_role_count, src->type, 0u);
            enemies[i].on_ground = 0u;
            enemies[i].visible = 0u;
            enemies[i].last_used_parts = 0u;
            enemies[i].world_x = (s16)(((s16)src->x * 8) - ngpng_type_s8(sc->render_off_x, sc->type_role_count, src->type, 0));
            enemies[i].world_y = (s16)(((s16)src->y * 8) - ngpng_type_s8(sc->render_off_y, sc->type_role_count, src->type, 0));
            enemies[i].ox      = 0;
            enemies[i].oy      = 0;
            enemies[i].last_sx = (s16)-32768;
            enemies[i].last_sy = (s16)-32768;
            enemies[i].last_tile = 0xFFFFu;
            enemies[i].cached_anim_frame = 0xFFu;
            enemies[i].cached_def        = 0;
            enemies[i].cached_rox = ngpng_type_s8(sc->render_off_x, sc->type_role_count, src->type,
                (s8)((enemies[i].hb_x < 0) ? enemies[i].hb_x : 0));
            enemies[i].cached_roy = ngpng_type_s8(sc->render_off_y, sc->type_role_count, src->type,
                (s8)((enemies[i].hb_y < 0) ? enemies[i].hb_y : 0));
            enemies[i].vx = -2;
            enemies[i].vy = 0;
            if (sc->path_count > 0u && assigned_path_idx != 0xFFu && assigned_path_idx < sc->path_count) {
                enemies[i].path_idx = assigned_path_idx;
            } else if (assigned_behavior == 0xFFu &&
                sc->path_count > 0u && src->data > 0u && src->data <= sc->path_count) {
                enemies[i].path_idx = (u8)(src->data - 1u);
            }
            /* OPT-2E: gate platformer init on behavior only (not gravity).
             * Allows PATROL enemies with gravity=0 (flat terrain) to get
             * correct vx init and skip floor probes + gravity entirely. */
            if (enemies[i].behavior != 0xFFu) {
                if (enemies[i].behavior == NGPNG_BEHAVIOR_FIXED) enemies[i].vx = 0;
                else enemies[i].vx = (src->y & 1u) ? (s8)1 : (s8)-1;
            } else {
                /* data movement patterns (paths=[]):
                 *  0=straight  1=drift down  2=drift up  3=alt by y
                 *  4=zigzag (flips vy every 16f)  5=fast (vx=-4)
                 *  6=patrol (va-et-vient, flip vx every 48f)
                 *  7=aggro  (patrol + chase quand joueur <5 tiles) */
                if      (src->data == 1u) enemies[i].vy = 1;
                else if (src->data == 2u) enemies[i].vy = -1;
                else if (src->data == 3u) enemies[i].vy = (src->y & 1u) ? 1 : -1;
                else if (src->data == 4u) enemies[i].vy = (src->y & 1u) ? 1 : -1;
                else if (src->data == 5u) { enemies[i].vx = -4; }
                else if (src->data == 6u || src->data == 7u) {
                    enemies[i].vx = (src->y & 1u) ? (s8)1 : (s8)-1;
                }
            }
            *active_count = (u8)(*active_count + 1u);
            *alloc_idx    = (u8)(i + 1u);
            if (*alloc_idx >= (u8)NGPNG_AUTORUN_MAX_ENEMIES) *alloc_idx = 0u;
            return;
        }
    }
}

void ngpng_enemies_reset_scene(const NgpSceneDef *sc, NgpngEnemy *enemies,
    u8 *enemy_active_count, u8 *enemy_alloc_idx)
{
    ngpng_enemies_clear(enemies, enemy_active_count, enemy_alloc_idx);
    /* Wave sequencer (NgpcWaveSeq) is restarted by the caller via ngpc_wave_start(). */
#if NGPNG_WORLD_ACTIVATION
    /* Populate world entity registry; ngpng_world_tick() handles proximity spawning. */
    ngpng_world_init(sc);
#else
    {
        u8 i;
        if (!sc->entities) return;
        for (i = 0u; i < sc->entity_count; ++i) {
            const NgpngEnt *e = &sc->entities[i];
            u8 ent_path     = 0xFFu;
            u8 ent_behavior = 0u;
            u8 ent_flags    = 0u;
            if (ngpng_effective_role_at(sc, i) != NGPNG_ROLE_ENEMY) continue;
            if (sc->entity_paths)     ent_path     = sc->entity_paths[i];
            if (sc->entity_behaviors) ent_behavior = sc->entity_behaviors[i];
            if (sc->entity_flags)     ent_flags    = sc->entity_flags[i];
            ngpng_enemy_spawn(sc, enemies, enemy_active_count, enemy_alloc_idx, e, i, ent_path, ent_behavior, ent_flags);
        }
    }
#endif
}
/* Wave spawning is now driven by NgpcWaveSeq (ngpc_wave module) in the generated
 * main.c: ngpc_wave_update(&wave_seq) returns each NgpcWaveEntry, the caller
 * extracts {type,x,y,data} and calls ngpng_enemy_spawn() directly. */

void ngpng_enemies_force_jump_by_type(NgpngEnemy *enemies, u8 type)
{
    u8 i;
    for (i = 0u; i < (u8)NGPNG_AUTORUN_MAX_ENEMIES; ++i) {
        if (!enemies[i].active || enemies[i].type != type) continue;
        if (enemies[i].gravity == 0u || !enemies[i].on_ground) continue;
        enemies[i].vy       = -4;
        enemies[i].on_ground = 0u;
    }
}

static u8 ngpng_enemy_should_turn_platformer(const NgpSceneDef *sc, const NgpngEnemy *e)
{
    s16 probe_x;
    s16 wall_y0;
    s16 wall_y1;
    s16 foot_y;
    s16 floor_x;
    s16 floor_y;
    u8 t0;
    u8 t1;
    if (!sc || !e || !sc->tilecol || e->vx == 0) return 0u;
    wall_y0 = (s16)(e->world_y + e->body_y + 1);
    wall_y1 = (s16)(e->world_y + e->body_y + ((e->body_h > 0u) ? (e->body_h - 1u) : 0u));
    if (wall_y1 < wall_y0) wall_y1 = wall_y0;
    foot_y = (s16)(e->world_y + e->body_y + e->body_h + 1);
    if (e->vx > 0) {
        probe_x = (s16)(e->world_x + e->body_x + e->body_w + 1);
        t0 = ngpng_tilecol_world(sc, probe_x, wall_y0, TILE_SOLID);
        t1 = ngpng_tilecol_world(sc, probe_x, wall_y1, TILE_SOLID);
        if (ngpng_tile_blocks_right(t0) || ngpng_tile_blocks_right(t1)) return 1u;
        floor_x = (s16)(e->world_x + e->body_x + e->body_w);
    } else {
        probe_x = (s16)(e->world_x + e->body_x - 1);
        t0 = ngpng_tilecol_world(sc, probe_x, wall_y0, TILE_SOLID);
        t1 = ngpng_tilecol_world(sc, probe_x, wall_y1, TILE_SOLID);
        if (ngpng_tile_blocks_left(t0) || ngpng_tile_blocks_left(t1)) return 1u;
        floor_x = (s16)(e->world_x + e->body_x);
    }
    if (e->ent_flags & NGPNG_ENT_FLAG_ALLOW_LEDGE_FALL) return 0u;
    /* OPT-SHOULD-TURN-EDGE: edge situation only changes when crossing a tile column
     * (every 8px at 1px/frame). Skip floor probe on non-boundary frames — saves ~7/8 calls. */
    if (((u8)floor_x & 7u) != 0u) return 0u;
    return ngpng_floor_probe_world(sc, floor_x, foot_y, &floor_y) ? 0u : 1u;
}

static void ngpng_enemy_resolve_horizontal_block(const NgpSceneDef *sc, NgpngEnemy *e)
{
    s16 wall_y0;
    s16 wall_y1;
    s16 probe_x;
    u8 t0;
    u8 t1;
    if (!sc || !e || !sc->tilecol || e->vx == 0) return;
    wall_y0 = (s16)(e->world_y + e->body_y + 1);
    wall_y1 = (s16)(e->world_y + e->body_y + ((e->body_h > 0u) ? (e->body_h - 1u) : 0u));
    if (wall_y1 < wall_y0) wall_y1 = wall_y0;
    if (e->vx > 0) {
        u16 tx;
        probe_x = (s16)(e->world_x + e->body_x + ((e->body_w > 0u) ? (e->body_w - 1u) : 0u));
        t0 = ngpng_tilecol_world(sc, probe_x, wall_y0, TILE_SOLID);
        t1 = ngpng_tilecol_world(sc, probe_x, wall_y1, TILE_SOLID);
        if (!ngpng_tile_blocks_right(t0) && !ngpng_tile_blocks_right(t1)) return;
        tx = (probe_x <= 0) ? 0u : (u16)(((u16)probe_x) >> 3u);
        e->world_x = (s16)((s16)(tx * 8u) - e->body_x - e->body_w);
    } else {
        u16 tx;
        probe_x = (s16)(e->world_x + e->body_x);
        t0 = ngpng_tilecol_world(sc, probe_x, wall_y0, TILE_SOLID);
        t1 = ngpng_tilecol_world(sc, probe_x, wall_y1, TILE_SOLID);
        if (!ngpng_tile_blocks_left(t0) && !ngpng_tile_blocks_left(t1)) return;
        tx = (probe_x < 0) ? 0u : (u16)(((u16)probe_x) >> 3u);
        e->world_x = (s16)((s16)((tx + 1u) * 8u) - e->body_x);
    }
    if (e->behavior == (u8)NGPNG_BEHAVIOR_PATROL || e->behavior == (u8)NGPNG_BEHAVIOR_RANDOM)
        e->vx = (s8)(-e->vx);
    else
        e->vx = 0;
}

static void ngpng_enemy_pick_topdown_dir(NgpngEnemy *e, u8 seed)
{
    if (!e) return;
    switch (seed & 3u) {
        case 0u: e->vx = 1;  e->vy = 0;  break;
        case 1u: e->vx = -1; e->vy = 0;  break;
        case 2u: e->vx = 0;  e->vy = 1;  break;
        default: e->vx = 0;  e->vy = -1; break;
    }
}

static void ngpng_enemy_pick_patrol_topdown_dir(NgpngEnemy *e, u8 seed)
{
    if (!e) return;
    if (seed & 1u) {
        e->vx = (seed & 2u) ? (s8)1 : (s8)-1;
        e->vy = 0;
    } else {
        e->vx = 0;
        e->vy = (seed & 2u) ? (s8)1 : (s8)-1;
    }
}

static void ngpng_enemy_apply_topdown_behavior(
    const NgpSceneDef *sc, NgpngEnemy *e, s16 player_wx, s16 player_wy, u8 seed)
{
    s16 dx;
    s16 dy;
    s16 adx;
    s16 ady;
    s16 radius_px;
    u8 radius_tiles;
    u8 random_interval;
    (void)sc;
    if (!e || e->behavior == 0xFFu) return;
    radius_tiles = (u8)((e->data > 0u) ? e->data : 5u);
    radius_px = (s16)((s16)radius_tiles * 8);
    random_interval = (u8)((e->data > 0u) ? e->data : 24u);
    switch (e->behavior) {
        case NGPNG_BEHAVIOR_FIXED:
            e->vx = 0;
            e->vy = 0;
            return;
        case NGPNG_BEHAVIOR_RANDOM:
            if ((e->vx == 0 && e->vy == 0) ||
                (random_interval > 0u && (e->anim % random_interval) == 0u)) {
                ngpng_enemy_pick_topdown_dir(e, (u8)(seed + e->anim));
            }
            return;
        case NGPNG_BEHAVIOR_CHASE:
        case NGPNG_BEHAVIOR_FLEE:
            dx = (s16)(player_wx - e->world_x);
            dy = (s16)(player_wy - e->world_y);
            adx = (dx < 0) ? (s16)(-dx) : dx;
            ady = (dy < 0) ? (s16)(-dy) : dy;
            if (adx > radius_px || ady > radius_px) {
                e->vx = 0;
                e->vy = 0;
                return;
            }
            e->vx = (dx > 2) ? (s8)1 : ((dx < -2) ? (s8)-1 : (s8)0);
            e->vy = (dy > 2) ? (s8)1 : ((dy < -2) ? (s8)-1 : (s8)0);
            if (e->behavior == NGPNG_BEHAVIOR_FLEE) {
                e->vx = (s8)(-e->vx);
                e->vy = (s8)(-e->vy);
            }
            return;
        case NGPNG_BEHAVIOR_PATROL:
        default:
            if (e->vx == 0 && e->vy == 0)
                ngpng_enemy_pick_patrol_topdown_dir(e, (u8)(seed + e->anim));
            else if (e->vx != 0) {
                e->vx = (e->vx > 0) ? (s8)1 : (s8)-1;
                e->vy = 0;
            } else {
                e->vy = (e->vy > 0) ? (s8)1 : (s8)-1;
                e->vx = 0;
            }
            return;
    }
}

static void ngpng_enemy_resolve_topdown_block(const NgpSceneDef *sc, NgpngEnemy *e, u8 seed)
{
    if (!sc || !e) return;
#if defined(NGPNG_HAS_DUNGEONGEN) && (NGPNG_HAS_DUNGEONGEN)
    if (!sc->tilecol) {
        /* Dungeongen: no static tilecol — use dynamic dungeon collision. */
        extern u8 ngpc_dungeongen_world_rect_hits_solid(s16 x0, s16 y0, s16 x1, s16 y1);
        s16 _bx0 = (s16)(e->world_x + (s16)e->body_x);
        s16 _by0 = (s16)(e->world_y + (s16)e->body_y);
        s16 _bx1 = (s16)(_bx0 + (s16)e->body_w - 1);
        s16 _by1 = (s16)(_by0 + (s16)e->body_h - 1);
        if (ngpc_dungeongen_world_rect_hits_solid(_bx0, _by0, _bx1, _by1)) {
            e->world_x = (s16)(e->world_x - (s16)e->vx);
            e->world_y = (s16)(e->world_y - (s16)e->vy);
            if (e->behavior == (u8)NGPNG_BEHAVIOR_PATROL)
                ngpng_enemy_pick_patrol_topdown_dir(e, (u8)(seed + 7u));
            else if (e->behavior == (u8)NGPNG_BEHAVIOR_RANDOM)
                ngpng_enemy_pick_topdown_dir(e, (u8)(seed + 13u));
            else { e->vx = 0; e->vy = 0; }
        }
        return;
    }
#endif
    if (!sc->tilecol) return;

    if (e->vx > 0) {
        s16 probe_x = (s16)(e->world_x + e->body_x + ((e->body_w > 0u) ? (e->body_w - 1u) : 0u));
        s16 y0 = (s16)(e->world_y + e->body_y + 1);
        s16 y1 = (s16)(e->world_y + e->body_y + ((e->body_h > 0u) ? (e->body_h - 1u) : 0u));
        u8 t0;
        u8 t1;
        if (y1 < y0) y1 = y0;
        t0 = ngpng_tilecol_world(sc, probe_x, y0, TILE_SOLID);
        t1 = ngpng_tilecol_world(sc, probe_x, y1, TILE_SOLID);
        if (ngpng_tile_blocks_right(t0) || ngpng_tile_blocks_right(t1)) {
            u16 tx = (probe_x <= 0) ? 0u : (u16)(((u16)probe_x) >> 3u);
            e->world_x = (s16)((s16)(tx * 8u) - e->body_x - e->body_w);
            if (e->behavior == (u8)NGPNG_BEHAVIOR_PATROL) { e->vx = -1; e->vy = 0; }
            else if (e->behavior == (u8)NGPNG_BEHAVIOR_RANDOM) ngpng_enemy_pick_topdown_dir(e, (u8)(seed + 17u));
            else e->vx = 0;
        }
    } else if (e->vx < 0) {
        s16 probe_x = (s16)(e->world_x + e->body_x);
        s16 y0 = (s16)(e->world_y + e->body_y + 1);
        s16 y1 = (s16)(e->world_y + e->body_y + ((e->body_h > 0u) ? (e->body_h - 1u) : 0u));
        u8 t0;
        u8 t1;
        if (y1 < y0) y1 = y0;
        t0 = ngpng_tilecol_world(sc, probe_x, y0, TILE_SOLID);
        t1 = ngpng_tilecol_world(sc, probe_x, y1, TILE_SOLID);
        if (ngpng_tile_blocks_left(t0) || ngpng_tile_blocks_left(t1)) {
            u16 tx = (probe_x < 0) ? 0u : (u16)(((u16)probe_x) >> 3u);
            e->world_x = (s16)((s16)((tx + 1u) * 8u) - e->body_x);
            if (e->behavior == (u8)NGPNG_BEHAVIOR_PATROL) { e->vx = 1; e->vy = 0; }
            else if (e->behavior == (u8)NGPNG_BEHAVIOR_RANDOM) ngpng_enemy_pick_topdown_dir(e, (u8)(seed + 23u));
            else e->vx = 0;
        }
    }

    if (e->vy > 0) {
        s16 probe_y = (s16)(e->world_y + e->body_y + ((e->body_h > 0u) ? (e->body_h - 1u) : 0u));
        s16 x0 = (s16)(e->world_x + e->body_x + 1);
        s16 x1 = (s16)(e->world_x + e->body_x + ((e->body_w > 0u) ? (e->body_w - 1u) : 0u));
        u8 t0;
        u8 t1;
        if (x1 < x0) x1 = x0;
        t0 = ngpng_tilecol_world(sc, x0, probe_y, TILE_SOLID);
        t1 = ngpng_tilecol_world(sc, x1, probe_y, TILE_SOLID);
        if (t0 == TILE_SOLID || t1 == TILE_SOLID) {
            u16 ty = (probe_y <= 0) ? 0u : (u16)(((u16)probe_y) >> 3u);
            e->world_y = (s16)((s16)(ty * 8u) - e->body_y - e->body_h);
            if (e->behavior == (u8)NGPNG_BEHAVIOR_PATROL) { e->vx = 0; e->vy = -1; }
            else if (e->behavior == (u8)NGPNG_BEHAVIOR_RANDOM) ngpng_enemy_pick_topdown_dir(e, (u8)(seed + 31u));
            else e->vy = 0;
        }
    } else if (e->vy < 0) {
        s16 probe_y = (s16)(e->world_y + e->body_y);
        s16 x0 = (s16)(e->world_x + e->body_x + 1);
        s16 x1 = (s16)(e->world_x + e->body_x + ((e->body_w > 0u) ? (e->body_w - 1u) : 0u));
        u8 t0;
        u8 t1;
        if (x1 < x0) x1 = x0;
        t0 = ngpng_tilecol_world(sc, x0, probe_y, TILE_SOLID);
        t1 = ngpng_tilecol_world(sc, x1, probe_y, TILE_SOLID);
        if (t0 == TILE_SOLID || t1 == TILE_SOLID) {
            u16 ty = (probe_y < 0) ? 0u : (u16)(((u16)probe_y) >> 3u);
            e->world_y = (s16)((s16)((ty + 1u) * 8u) - e->body_y);
            if (e->behavior == (u8)NGPNG_BEHAVIOR_PATROL) { e->vx = 0; e->vy = 1; }
            else if (e->behavior == (u8)NGPNG_BEHAVIOR_RANDOM) ngpng_enemy_pick_topdown_dir(e, (u8)(seed + 37u));
            else e->vy = 0;
        }
    }
}

static u8 ngpng_enemy_touches_deadly_tile(const NgpSceneDef *sc, const NgpngEnemy *e)
{
    s16 x0;
    s16 x1;
    s16 xm;
    s16 y0;
    s16 y1;
    u8 t0;
    u8 t1;
    u8 t2;
    u8 t3;
    if (!sc || !e) return 0u;
    x0 = (s16)(e->world_x + e->body_x + 1);
    x1 = (s16)(e->world_x + e->body_x + ((e->body_w > 0u) ? (e->body_w - 1u) : 0u) - 1);
    if (x1 < x0) x1 = x0;
    xm = (s16)(e->world_x + e->body_x + (e->body_w / 2u));
    y0 = (s16)(e->world_y + e->body_y + 1);
    y1 = (s16)(e->world_y + e->body_y + e->body_h + 1);
    t0 = ngpng_tilecol_world(sc, x0, y0, TILE_PASS);
    t1 = ngpng_tilecol_world(sc, x1, y0, TILE_PASS);
    t2 = ngpng_tilecol_world(sc, x0, y1, TILE_PASS);
    t3 = ngpng_tilecol_world(sc, xm, y1, TILE_PASS);
    return (u8)(ngpng_tile_is_void(t0) || ngpng_tile_is_void(t1) ||
                ngpng_tile_is_void(t2) || ngpng_tile_is_void(t3) ||
                ngpng_tile_is_damage(t0) || ngpng_tile_is_damage(t1) ||
                ngpng_tile_is_damage(t2) || ngpng_tile_is_damage(t3) ||
                ngpng_tile_is_fire(t0) || ngpng_tile_is_fire(t1) ||
                ngpng_tile_is_fire(t2) || ngpng_tile_is_fire(t3));
}

static void ngpng_enemy_apply_platformer_behavior(const NgpSceneDef *sc, NgpngEnemy *e, s16 player_wx, u8 seed, u8 frame_timer)
{
    s16 dx;
    if (!e || e->behavior == 0xFFu) return;
    switch (e->behavior) {
        case NGPNG_BEHAVIOR_FIXED:
            e->vx = 0;
            return;
        case NGPNG_BEHAVIOR_CHASE:
            if (e->gravity == 0u) return; /* chase requires gravity */
            dx = (s16)(player_wx - e->world_x);
            if (dx < -6) e->vx = -1;
            else if (dx > 6) e->vx = 1;
            else e->vx = 0;
            break;
        case NGPNG_BEHAVIOR_FLEE:
            if (e->gravity == 0u) return; /* flee requires gravity */
            dx = (s16)(player_wx - e->world_x);
            if (dx < -6) e->vx = 1;
            else if (dx > 6) e->vx = -1;
            else e->vx = 0;
            break;
        case NGPNG_BEHAVIOR_RANDOM:
            if (e->vx == 0 || (e->anim & 0x1Fu) == 0u)
                e->vx = ((seed + e->anim) & 1u) ? (s8)1 : (s8)-1;
            break;
        case NGPNG_BEHAVIOR_PATROL:
        default:
            if (e->patrol_max > e->patrol_min) {
                /* OPT-2A-BOUNDS: direct world-X comparison, 0 tile calls.
                 * Works with gravity=0 (Y fixed at spawn) or gravity>0 (flat terrain). */
                if (e->world_x <= e->patrol_min) { e->vx = 1; return; }
                if (e->world_x >= e->patrol_max) { e->vx = -1; return; }
                if (e->vx == 0) e->vx = (seed & 1u) ? (s8)1 : (s8)-1;
                return; /* bounds handle turning — skip should_turn */
            }
            /* No bounds: tile detection. Requires gravity for floor probe. */
            if (e->gravity == 0u) {
                if (e->vx == 0) e->vx = (seed & 1u) ? (s8)1 : (s8)-1;
                return;
            }
            if (e->vx == 0) e->vx = (seed & 1u) ? (s8)1 : (s8)-1;
            else e->vx = (e->vx > 0) ? (s8)1 : (s8)-1;
            break;
    }
    /* OPT-A: skip tile turn-check every other frame (no bounds path only).
     * Enemies move 1px/frame; missing 1 check = at most 1px overshoot into wall. */
    if (e->gravity > 0u && e->vx != 0 && !(frame_timer & 1u) && ngpng_enemy_should_turn_platformer(sc, e))
        e->vx = (s8)(-e->vx);
}

void ngpng_enemies_update(const NgpSceneDef *sc,
    const u8 NGP_FAR *_tc, u16 _mw, u16 _mh,
    NgpngEnemy *enemies,
    u8 *enemy_active_count, s16 cam_px, s16 cam_py, s16 player_wx, s16 player_wy,
    u8 frame_timer)
{
    u8 i;
    u8 processed = 0u;
    (void)_tc;
    if (*enemy_active_count == 0u) return;
    for (i = 0; i < (u8)NGPNG_AUTORUN_MAX_ENEMIES; ++i) {
        if (!enemies[i].active) continue;
        processed = (u8)(processed + 1u);
        enemies[i].anim = (u8)(enemies[i].anim + 1u);
        /* Off-screen guard: skip expensive tilecol physics for enemies far outside viewport.
         * PLATFORMER: only drift enemies behind the camera (esx < -96).
         * Enemies ahead (esx > 256) are frozen until the camera reaches them.
         * CULL_OFFSCREEN: when flagged, auto-kill once we're far outside the hard
         * cull zone (≈1 screen beyond the drift margin) so random-wave spawns can
         * never accumulate into permanent occupants of the enemy pool. */
        {
            s16 esx = (s16)(enemies[i].world_x - cam_px);
            s16 esy = (s16)(enemies[i].world_y - cam_py);
            if (esx < -96 || esx > 256 || esy < -96 || esy > 248) {
                if (enemies[i].ent_flags & NGPNG_ENT_FLAG_CULL_OFFSCREEN) {
                    if (esx < -256 || esx > 416 || esy < -256 || esy > 408) {
                        ngpng_enemy_kill(enemies, enemy_active_count, i);
                        continue;
                    }
                }
                if (esx < -96) {
                    enemies[i].world_x = (s16)(enemies[i].world_x + enemies[i].vx);
                    enemies[i].world_y = (s16)(enemies[i].world_y + enemies[i].vy);
                    if (enemies[i].ent_flags & NGPNG_ENT_FLAG_CLAMP_MAP)
                        ngpng_clamp_world_rect(sc, &enemies[i].world_x, &enemies[i].world_y,
                            enemies[i].body_w, enemies[i].body_h);
                    if (enemies[i].ent_flags & NGPNG_ENT_FLAG_CLAMP_CAMERA)
                        ngpng_clamp_camera_rect(&enemies[i].world_x, &enemies[i].world_y,
                            cam_px, cam_py, enemies[i].body_w, enemies[i].body_h);
                }
                if (processed >= *enemy_active_count) break;
                continue;
            }
        }
        if (enemies[i].path_idx != 0xFFu && sc->path_points && sc->path_offsets && sc->path_lengths) {
            u8 pi = enemies[i].path_idx;
            u8 plen = sc->path_lengths[pi];
            if (pi < sc->path_count && plen > 0u) {
                u16 off = sc->path_offsets[pi];
                const NgpngPoint *pt = &sc->path_points[off + enemies[i].path_step];
                s16 dst_x = (s16)((s16)pt->x * 8);
                s16 dst_y = (s16)((s16)pt->y * 8);
                {
                    s8 espd = sc->path_speeds ? (s8)sc->path_speeds[pi] : 2;
                    enemies[i].vx = ngpng_step_toward(enemies[i].world_x, dst_x, espd);
                    enemies[i].vy = ngpng_step_toward(enemies[i].world_y, dst_y, espd);
                }
                enemies[i].world_x = (s16)(enemies[i].world_x + enemies[i].vx);
                enemies[i].world_y = (s16)(enemies[i].world_y + enemies[i].vy);
                if (enemies[i].ent_flags & NGPNG_ENT_FLAG_CLAMP_MAP)
                    ngpng_clamp_world_rect(sc, &enemies[i].world_x, &enemies[i].world_y,
                        enemies[i].body_w, enemies[i].body_h);
                if (enemies[i].ent_flags & NGPNG_ENT_FLAG_CLAMP_CAMERA)
                    ngpng_clamp_camera_rect(&enemies[i].world_x, &enemies[i].world_y,
                        cam_px, cam_py, enemies[i].body_w, enemies[i].body_h);
                if (enemies[i].vx == 0 && enemies[i].vy == 0) {
                    enemies[i].path_step = (u8)(enemies[i].path_step + 1u);
                    if (enemies[i].path_step >= plen) {
                        if (sc->path_flags && sc->path_flags[pi]) enemies[i].path_step = 0u;
                        else {
                            enemies[i].path_idx = 0xFFu;
                            enemies[i].path_step = 0u;
                            enemies[i].vx = -2;
                        }
                    }
                }
                ngpng_enemy_update_draw_cache(sc, &enemies[i]);
                continue;
            }
        }
        if (enemies[i].behavior != 0xFFu) {
            if (enemies[i].gravity > 0u)
                ngpng_enemy_apply_platformer_behavior(sc, &enemies[i], player_wx, i, frame_timer);
            else
                ngpng_enemy_apply_topdown_behavior(sc, &enemies[i], player_wx, player_wy, i);
        } else {
            /* data=4: zigzag -- flip vy every 16 frames. */
            if (enemies[i].data == 4u && (enemies[i].anim & 0x1Fu) == 0x10u) {
                enemies[i].vy = (s8)(-enemies[i].vy);
            }
            /* legacy movement branch only; gravity is applied below for all enemies */
            /* data=6/7: patrol -- flip vx every 48 frames. */
            if ((enemies[i].data == 6u || enemies[i].data == 7u) &&
                (enemies[i].anim % 48u) == 0u && enemies[i].anim != 0u) {
                enemies[i].vx = (s8)(-enemies[i].vx);
            }
            /* data=7: aggro radius = 5 tiles (40px). If player within range, chase. */
            if (enemies[i].data == 7u) {
                s16 dx = (s16)(player_wx - enemies[i].world_x);
                s16 dy = (s16)(player_wy - enemies[i].world_y);
                if (dx < 0) dx = (s16)(-dx);
                if (dy < 0) dy = (s16)(-dy);
                if (dx < 40 && dy < 40) {
                    enemies[i].vx = (s8)((player_wx > enemies[i].world_x) ? 1 : -1);
                    if (dy > 4) enemies[i].vy = (s8)((player_wy > enemies[i].world_y) ? 1 : -1);
                    else enemies[i].vy = 0;
                }
            }
        }
        /* Gravity: apply per-type gravity to vy, cap at 6 (anti-tunneling). */
        if (enemies[i].gravity > 0u) {
            if (enemies[i].vy < 6) enemies[i].vy = (s8)(enemies[i].vy + (s8)enemies[i].gravity);
            else enemies[i].vy = 6;
        }
        enemies[i].world_x = (s16)(enemies[i].world_x + enemies[i].vx);
        enemies[i].world_y = (s16)(enemies[i].world_y + enemies[i].vy);
        if (enemies[i].ent_flags & NGPNG_ENT_FLAG_CLAMP_MAP)
            ngpng_clamp_world_rect(sc, &enemies[i].world_x, &enemies[i].world_y,
                enemies[i].body_w, enemies[i].body_h);
        if (enemies[i].ent_flags & NGPNG_ENT_FLAG_CLAMP_CAMERA)
            ngpng_clamp_camera_rect(&enemies[i].world_x, &enemies[i].world_y,
                cam_px, cam_py, enemies[i].body_w, enemies[i].body_h);
        if (enemies[i].gravity > 0u) {
            /* OPT-K: skip floor probe on odd frames when already on_ground.
             * Undo the gravity step so the enemy stays planted. */
            if (enemies[i].on_ground && (frame_timer & 1u)) {
                enemies[i].world_y = (s16)(enemies[i].world_y - enemies[i].vy);
                enemies[i].vy = 0;
            } else {
            s16 efy = (s16)(enemies[i].world_y + enemies[i].body_y + enemies[i].body_h);
            s16 efloorL;
            s16 efloorR;
            s16 efloor;
            u8 ehasL = ngpng_floor_probe_world(sc,
                (s16)(enemies[i].world_x + enemies[i].body_x + 1), efy, &efloorL);
            u8 ehasR = ngpng_floor_probe_world(sc,
                (s16)(enemies[i].world_x + enemies[i].body_x +
                    ((enemies[i].body_w > 1u) ? (enemies[i].body_w - 2u) : 0u)),
                efy, &efloorR);
            if ((ehasL || ehasR) && enemies[i].vy >= 0) {
                efloor = ehasL ? efloorL : efloorR;
                if (ehasR && efloorR < efloor) efloor = efloorR;
                enemies[i].world_y = (s16)(efloor - enemies[i].body_y - enemies[i].body_h);
                enemies[i].vy = 0;
                enemies[i].on_ground = 1u;
            } else {
                enemies[i].on_ground = 0u;
            }
            }
            if (enemies[i].vx != 0)
                ngpng_enemy_resolve_horizontal_block(sc, &enemies[i]);
#if NGPNG_HAS_DEADLY_TILE
            if ((sc->scene_flags & SCENE_FLAG_HAS_DEADLY) &&
                    ngpng_enemy_touches_deadly_tile(sc, &enemies[i])) {
                ngpng_enemy_kill(enemies, enemy_active_count, i);
                continue;
            }
#endif
        } else if (enemies[i].behavior != 0xFFu) {
            ngpng_enemy_resolve_topdown_block(sc, &enemies[i], (u8)(i + frame_timer));
        } else if (enemies[i].vy != 0) {
            /* Shmup-style bounce (no gravity). */
            if (enemies[i].world_y < 16) {
                enemies[i].world_y = 16;
                enemies[i].vy = (s8)(-enemies[i].vy);
            } else if (enemies[i].world_y > 136) {
                enemies[i].world_y = 136;
                enemies[i].vy = (s8)(-enemies[i].vy);
            }
        }
        if (enemies[i].world_x < -24 || enemies[i].world_x > (s16)(_mw * 8u + 24u) ||
            enemies[i].world_y < -24 || enemies[i].world_y > (s16)(_mh * 8u + 24u)) {
            ngpng_enemy_kill(enemies, enemy_active_count, i);
            continue;
        }
        ngpng_enemy_update_draw_cache(sc, &enemies[i]);
        if (processed >= *enemy_active_count) break;
    }
}

void ngpng_enemy_sync(const NgpSceneDef *sc, NgpngEnemy *enemies, u8 idx,
    s16 cam_px, s16 cam_py, u8 frame_idx)
{
    NgpngEnemy *e   = &enemies[idx];
    u8 slot         = 0u;
    u8 render_flags;
    s16 sx;
    s16 sy;
    s16 px;
    s16 py;
    u16 tile;
    if (!ngpng_enemy_slot_base_for_idx(idx, &slot, 0)) return;
    if (slot >= (u8)NGPNG_AUTORUN_HUD_SPR_BASE) return;
    if (!e->active) { ngpng_enemy_hide(enemies, idx); return; }
    tile = e->last_tile;
    if (e->last_frame != frame_idx || e->last_tile == 0xFFFFu) {
        if (!ngpng_entity_sprite_info(sc, e->type, frame_idx, &tile, &e->pal, &e->flags, &e->ox, &e->oy)) {
            ngpng_enemy_hide(enemies, idx); return;
        }
        e->last_frame = frame_idx;
    }
    if (ngpng_type_u8(sc->type_flip_x_dir, sc->type_role_count, e->type, 0u)) {
        if (e->vx < 0) e->face_hflip = 1u;
        else if (e->vx > 0) e->face_hflip = 0u;
    }
    render_flags = (u8)((e->flags & (u8)~SPR_HFLIP) | (e->face_hflip ? SPR_HFLIP : 0u));
    sx = (s16)(e->world_x - cam_px);
    sy = (s16)(e->world_y - cam_py);
    px = (s16)(sx + e->ox);
    py = (s16)(sy + e->oy);
    if (px < -24 || px > 176 || py < -24 || py > 168) {
        if (e->visible) { ngpc_sprite_hide(slot); e->visible = 0u; }
        return;
    }
    if (!e->visible) {
        ngpc_sprite_set(slot, (u8)((u16)px & 0xFFu), (u8)((u16)py & 0xFFu), tile, e->pal, render_flags);
        e->visible    = 1u;
        e->last_used_parts = 0u;
        e->last_tile  = tile;
        e->last_flags = render_flags;
        e->last_sx    = px;
        e->last_sy    = py;
    } else {
        if (e->last_tile != tile || e->last_flags != render_flags) {
            ngpc_sprite_set(slot, (u8)((u16)px & 0xFFu), (u8)((u16)py & 0xFFu), tile, e->pal, render_flags);
            e->last_tile  = tile;
            e->last_flags = render_flags;
            e->last_sx    = px;
            e->last_sy    = py;
        } else if (e->last_sx != px || e->last_sy != py) {
            ngpc_sprite_move(slot, (u8)((u16)px & 0xFFu), (u8)((u16)py & 0xFFu));
            e->last_sx = px;
            e->last_sy = py;
        }
    }
}

void ngpng_enemies_draw(const NgpSceneDef *sc, NgpngEnemy *enemies, s16 cam_px, s16 cam_py)
{
    u8 i;
    u8 spr     = (u8)NGPNG_AUTORUN_ENEMY_SPR_BASE;
    u8 spr_end = (u8)(NGPNG_AUTORUN_ENEMY_SPR_BASE + NGPNG_AUTORUN_ENEMY_SLOT_COUNT);
    if (!sc || !sc->resolve_entity_frame || NGPNG_AUTORUN_ENEMY_SLOT_COUNT == 0u) return;
#if NGPNG_PERF7_LEGACY_REDRAW
    ngpng_sprite_hide_range((u8)NGPNG_AUTORUN_ENEMY_SPR_BASE, (u8)NGPNG_AUTORUN_ENEMY_SLOT_COUNT);
    for (i = 0u; i < (u8)NGPNG_AUTORUN_MAX_ENEMIES; ++i) {
        NgpngEnemy *e = &enemies[i];
        const NgpcMetasprite *def;
        u8 anim_frame;
        u8 render_flags;
        u8 used;
        s16 sx;
        s16 sy;
        if (!e->active) continue;
        if (spr >= spr_end) break;
        anim_frame = e->cached_anim_frame;
        def        = e->cached_def;
        if (anim_frame == 0xFFu || !def || def->count == 0u) continue;
        if (ngpng_type_u8(sc->type_flip_x_dir, sc->type_role_count, e->type, 0u)) {
            if (e->vx < 0) e->face_hflip = 1u;
            else if (e->vx > 0) e->face_hflip = 0u;
        }
        render_flags = (u8)(g_ngpng_entity_prio | (e->face_hflip ? SPR_HFLIP : 0u));
        sx = (s16)(e->world_x - cam_px + e->cached_rox);
        sy = (s16)(e->world_y - cam_py + e->cached_roy);
        if (!ngpng_sprite_mspr_intersects_screen(sx, sy, def)) continue;
        if ((u16)spr + def->count > spr_end) continue;
        used = ngpng_sprite_mspr_draw(spr, sx, sy, def, render_flags);
        if (used == 0u) continue;
        spr = (u8)(spr + used);
    }
#else
    for (i = 0u; i < (u8)NGPNG_AUTORUN_MAX_ENEMIES; ++i) {
        NgpngEnemy *e = &enemies[i];
        const NgpcMetasprite *def;
        u8 anim_frame;
        u8 render_flags;
        u8 slot;
        u8 slot_span;
        u8 slot_state;
        s16 sx;
        s16 sy;
        if (!e->active) {
            ngpng_enemy_hide_cached(enemies, i);
            continue;
        }
        anim_frame = e->cached_anim_frame;
        def        = e->cached_def;
        if (anim_frame == 0xFFu || !def || def->count == 0u) {
            ngpng_enemy_hide_cached(enemies, i);
            continue;
        }
        if (ngpng_type_u8(sc->type_flip_x_dir, sc->type_role_count, e->type, 0u)) {
            if (e->vx < 0) e->face_hflip = 1u;
            else if (e->vx > 0) e->face_hflip = 0u;
        }
        render_flags = (u8)(g_ngpng_entity_prio | (e->face_hflip ? SPR_HFLIP : 0u));
        sx = (s16)(e->world_x - cam_px + e->cached_rox);
        sy = (s16)(e->world_y - cam_py + e->cached_roy);
        if (!ngpng_sprite_mspr_intersects_screen(sx, sy, def)) {
            ngpng_enemy_hide_cached(enemies, i);
            continue;
        }
        if (!ngpng_enemy_slot_base_for_idx(i, &slot, &slot_span)) {
            ngpng_enemy_hide_cached(enemies, i);
            continue;
        }
        if (def->count > slot_span) {
            ngpng_enemy_hide_cached(enemies, i);
            continue;
        }
        slot_state = slot;
        ngpng_sprite_mspr_sync(slot, sx, sy, def, anim_frame, render_flags,
            &e->visible, &slot_state, &e->last_used_parts,
            &e->last_sx, &e->last_sy, &e->last_frame, &e->last_flags);
    }
#endif
}

#endif /* NGPNG_HAS_ENEMY */

/* ==========================================================================
 * Fx management
 * ========================================================================== */
#if NGPNG_HAS_FX

void ngpng_fx_hide(NgpngFx *fx, u8 idx)
{
    u8 slot = (u8)(NGPNG_AUTORUN_FX_SPR_BASE + idx);
    if (fx[idx].visible) ngpc_sprite_hide(slot);
    fx[idx].visible   = 0u;
    fx[idx].last_sx   = (s16)-32768;
    fx[idx].last_sy   = (s16)-32768;
    fx[idx].last_tile = 0xFFFFu;
}

void ngpng_fx_clear(NgpngFx *fx, u8 *active_count, u8 *alloc_idx)
{
    u8 i;
    for (i = 0; i < (u8)NGPNG_AUTORUN_MAX_FX; ++i) {
        fx[i].active    = 0u;
        fx[i].visible   = 0u;
        fx[i].frame_base = 0u;
        fx[i].frame_count = 0u;
        fx[i].last_sx   = (s16)-32768;
        fx[i].last_sy   = (s16)-32768;
        fx[i].last_tile = 0xFFFFu;
    }
    *active_count = 0u;
    *alloc_idx    = 0u;
}

void ngpng_fx_kill(NgpngFx *fx, u8 *active_count, u8 idx)
{
    if (!fx[idx].active) return;
    fx[idx].active = 0u;
    ngpng_fx_hide(fx, idx);
    if (*active_count > 0u) *active_count = (u8)(*active_count - 1u);
}

void ngpng_fx_spawn(NgpngFx *fx, u8 *active_count, u8 *alloc_idx,
    u8 fx_type, s16 world_x, s16 world_y)
{
    u8 k;
    if (fx_type == 0xFFu) return;
    if (*active_count >= (u8)NGPNG_AUTORUN_MAX_FX) return;
    for (k = 0; k < (u8)NGPNG_AUTORUN_MAX_FX; ++k) {
        u8 i = (u8)(*alloc_idx + k);
        if (i >= (u8)NGPNG_AUTORUN_MAX_FX) i = (u8)(i - (u8)NGPNG_AUTORUN_MAX_FX);
        if (!fx[i].active) {
            fx[i].active     = 1u;
            fx[i].visible    = 0u;
            fx[i].type       = fx_type;
            fx[i].frame_base = 0u;
            fx[i].frame_count = 0u;
            fx[i].anim       = 0u;
            fx[i].last_frame = 0xFFu;
            fx[i].pal        = 0u;
            fx[i].flags      = (u8)SPR_FRONT;
            fx[i].world_x    = world_x;
            fx[i].world_y    = world_y;
            fx[i].ox         = 0;
            fx[i].oy         = 0;
            fx[i].last_sx    = (s16)-32768;
            fx[i].last_sy    = (s16)-32768;
            fx[i].last_tile  = 0xFFFFu;
            *active_count = (u8)(*active_count + 1u);
            *alloc_idx    = (u8)(i + 1u);
            if (*alloc_idx >= (u8)NGPNG_AUTORUN_MAX_FX) *alloc_idx = 0u;
            return;
        }
    }
}

void ngpng_fx_spawn_anim_state(const NgpSceneDef *sc, NgpngFx *fx, u8 *active_count, u8 *alloc_idx,
    u8 fx_type, u8 anim_state, s16 world_x, s16 world_y)
{
    u8 k;
    u8 frame_base;
    u8 frame_count;
    if (!sc) {
        ngpng_fx_spawn(fx, active_count, alloc_idx, fx_type, world_x, world_y);
        return;
    }
    frame_base  = ngpng_type_anim_start(sc, fx_type, anim_state);
    frame_count = ngpng_type_anim_count(sc, fx_type, anim_state);
    if (frame_count == 0u) {
        ngpng_fx_spawn(fx, active_count, alloc_idx, fx_type, world_x, world_y);
        return;
    }
    if (*active_count >= (u8)NGPNG_AUTORUN_MAX_FX) return;
    for (k = 0; k < (u8)NGPNG_AUTORUN_MAX_FX; ++k) {
        u8 i = (u8)(*alloc_idx + k);
        if (i >= (u8)NGPNG_AUTORUN_MAX_FX) i = (u8)(i - (u8)NGPNG_AUTORUN_MAX_FX);
        if (!fx[i].active) {
            fx[i].active      = 1u;
            fx[i].visible     = 0u;
            fx[i].type        = fx_type;
            fx[i].frame_base  = frame_base;
            fx[i].frame_count = frame_count;
            fx[i].anim        = 0u;
            fx[i].last_frame  = 0xFFu;
            fx[i].pal         = 0u;
            fx[i].flags       = (u8)SPR_FRONT;
            fx[i].world_x     = world_x;
            fx[i].world_y     = world_y;
            fx[i].ox          = 0;
            fx[i].oy          = 0;
            fx[i].last_sx     = (s16)-32768;
            fx[i].last_sy     = (s16)-32768;
            fx[i].last_tile   = 0xFFFFu;
            *active_count = (u8)(*active_count + 1u);
            *alloc_idx    = (u8)(i + 1u);
            if (*alloc_idx >= (u8)NGPNG_AUTORUN_MAX_FX) *alloc_idx = 0u;
            return;
        }
    }
}

void ngpng_fx_sync(const NgpSceneDef *sc, NgpngFx *fx, u8 idx, s16 cam_px, s16 cam_py)
{
    NgpngFx *f  = &fx[idx];
    u8 slot     = (u8)(NGPNG_AUTORUN_FX_SPR_BASE + idx);
    u8 frame_idx;
    s16 sx;
    s16 sy;
    s16 px;
    s16 py;
    u16 tile;
    if (!f->active) { ngpng_fx_hide(fx, idx); return; }
    if (slot >= (u8)NGPNG_AUTORUN_HUD_SPR_BASE) return;
    frame_idx = (u8)(f->anim / 6u);
    if (f->frame_count > 0u) {
        if (frame_idx >= f->frame_count) frame_idx = (u8)(f->frame_count - 1u);
        frame_idx = (u8)(f->frame_base + frame_idx);
    }
    tile      = f->last_tile;
    if (f->last_frame != frame_idx || f->last_tile == 0xFFFFu) {
        if (!ngpng_entity_sprite_info(sc, f->type, frame_idx, &tile, &f->pal, &f->flags, &f->ox, &f->oy)) {
            ngpng_fx_hide(fx, idx); return;
        }
        f->last_frame = frame_idx;
    }
    sx = (s16)(f->world_x - cam_px);
    sy = (s16)(f->world_y - cam_py);
    px = (s16)(sx + f->ox);
    py = (s16)(sy + f->oy);
    if (!f->visible) {
        ngpc_sprite_set(slot, (u8)((u16)px & 0xFFu), (u8)((u16)py & 0xFFu), tile, f->pal, f->flags);
        f->visible   = 1u;
        f->last_tile = tile;
        f->last_sx   = px;
        f->last_sy   = py;
    } else {
        if (f->last_tile != tile) { ngpc_sprite_set_tile(slot, tile); f->last_tile = tile; }
        if (f->last_sx != px || f->last_sy != py) {
            ngpc_sprite_move(slot, (u8)((u16)px & 0xFFu), (u8)((u16)py & 0xFFu));
            f->last_sx = px;
            f->last_sy = py;
        }
    }
}

void ngpng_fx_update(const NgpSceneDef *sc, NgpngFx *fx, u8 *fx_active_count,
    s16 cam_px, s16 cam_py)
{
    u8 i;
    u8 processed = 0u;
    if (*fx_active_count == 0u) return;
    for (i = 0; i < (u8)NGPNG_AUTORUN_MAX_FX; ++i) {
        if (!fx[i].active) continue;
        processed = (u8)(processed + 1u);
        fx[i].anim = (u8)(fx[i].anim + 1u);
        if ((fx[i].frame_count > 0u && fx[i].anim >= (u8)(fx[i].frame_count * 6u)) ||
            (fx[i].frame_count == 0u && fx[i].anim > 18u)) {
            ngpng_fx_kill(fx, fx_active_count, i);
            continue;
        }
        ngpng_fx_sync(sc, fx, i, cam_px, cam_py);
        if (processed >= *fx_active_count) break;
    }
}

#endif /* NGPNG_HAS_FX */

/* ==========================================================================
 * Prop actor management
 * ========================================================================== */
#if NGPNG_HAS_PROP_ACTOR

static void ngpng_prop_hide_draw(NgpngPropActor *props, u8 idx)
{
    if (props[idx].draw_visible && props[idx].last_used_parts > 0u) {
        ngpng_prop_spr_free(props[idx].last_draw_spr, props[idx].last_used_parts);
        ngpng_sprite_hide_range(props[idx].last_draw_spr, props[idx].last_used_parts);
    }
    props[idx].draw_visible    = 0u;
    props[idx].last_draw_frame = 0xFFu;
    props[idx].last_draw_flags = 0xFFu;
    props[idx].last_used_parts = 0u;
    props[idx].last_draw_spr   = 0u;
    props[idx].last_draw_sx    = (s16)-32768;
    props[idx].last_draw_sy    = (s16)-32768;
}

void ngpng_props_clear(NgpngPropActor *props)
{
    u8 i;
    s_ngpng_prop_spr_mask = 0UL;
    for (i = 0u; i < (u8)NGPNG_AUTORUN_MAX_PROPS; ++i) {
        props[i].active       = 0u;
        props[i].visible      = 0u;
        props[i].role         = NGPNG_ROLE_PROP;
        props[i].type         = 0u;
        props[i].src_idx      = 0xFFu;
        props[i].anim         = 0u;
        props[i].anim_state   = NGPNG_ANIM_IDLE;
        props[i].moving       = 0u;
        props[i].paused       = 0u;
        props[i].path_idx     = 0xFFu;
        props[i].path_step    = 0u;
        props[i].data         = 0u;
        props[i].state        = 0u;
        props[i].bump_timer   = 0u;
        props[i].hb_x         = 0u;
        props[i].hb_y         = 0u;
        props[i].hb_w         = 8u;
        props[i].hb_h         = 8u;
        props[i].body_x       = 0u;
        props[i].body_y       = 0u;
        props[i].body_w       = 8u;
        props[i].body_h       = 8u;
        props[i].world_x      = 0;
        props[i].world_y      = 0;
        props[i].prev_world_x = 0;
        props[i].prev_world_y = 0;
        props[i].home_y       = 0;
        props[i].target_x     = 0;
        props[i].target_y     = 0;
        props[i].draw_visible = 0u;
        props[i].last_draw_frame = 0xFFu;
        props[i].last_draw_flags = 0xFFu;
        props[i].last_used_parts = 0u;
        props[i].last_draw_spr   = 0u;
        props[i].last_draw_sx    = (s16)-32768;
        props[i].last_draw_sy    = (s16)-32768;
        props[i].cached_anim_st    = 0xFFu;
        props[i].cached_anim_frame = 0xFFu;
        props[i].cached_def        = 0;
        props[i].cached_rox        = 0;
        props[i].cached_roy        = 0;
    }
}

u8 ngpng_prop_find_by_src(const NgpngPropActor *props, u8 prop_count, u8 src_idx)
{
    u8 i;
    for (i = 0u; i < prop_count && i < (u8)NGPNG_AUTORUN_MAX_PROPS; ++i) {
        if (props[i].active && props[i].src_idx == src_idx) return i;
    }
    return 0xFFu;
}

void ngpng_props_set_anim_by_type(NgpngPropActor *props, u8 prop_count, u8 type, u8 anim_state)
{
    u8 i;
    for (i = 0u; i < prop_count && i < (u8)NGPNG_AUTORUN_MAX_PROPS; ++i) {
        if (!props[i].active || props[i].type != type) continue;
        props[i].anim_state = anim_state;
        props[i].anim = 0u;
        props[i].cached_anim_st    = 0xFFu; /* force anim cache refresh on next update */
        props[i].cached_anim_frame = 0xFFu; /* invalidate draw cache */
    }
}

void ngpng_props_reset_scene(const NgpSceneDef *sc, NgpngPropActor *props, u8 *prop_count)
{
    u8 i;
    u8 n = 0u;
    ngpng_props_clear(props);
    *prop_count = 0u;
    s_ngpng_prop_spr_mask = 0UL;
    ngpng_sprite_hide_range((u8)NGPNG_AUTORUN_PROP_SPR_BASE, (u8)NGPNG_AUTORUN_PROP_SPR_COUNT);
    if (!sc || !sc->entities) return;
    for (i = 0u; i < sc->entity_count; ++i) {
        const NgpngEnt *src = &sc->entities[i];
        u8 role;
        if (n >= (u8)NGPNG_AUTORUN_MAX_PROPS) break;
        role = ngpng_effective_role_at(sc, i);
        if (role == NGPNG_ROLE_PLAYER || role == NGPNG_ROLE_ENEMY || role == NGPNG_ROLE_TRIGGER) continue;
        props[n].active       = 1u;
        props[n].visible      = 1u;
        props[n].role         = role;
        props[n].type         = src->type;
        props[n].src_idx      = i;
        props[n].anim         = 0u;
        props[n].anim_state   = NGPNG_ANIM_IDLE;
        props[n].moving       = 0u;
        props[n].paused       = 0u;
        props[n].path_idx     = 0xFFu;
        props[n].path_step    = 0u;
        props[n].data         = src->data;
        props[n].state        = 0u;
        props[n].bump_timer   = 0u;
        props[n].ent_flags    = sc->entity_flags ? sc->entity_flags[i] : 0u;
        props[n].hb_x  = ngpng_type_s8(sc->hitbox_x, sc->type_role_count, src->type, 0);
        props[n].hb_y  = ngpng_type_s8(sc->hitbox_y, sc->type_role_count, src->type, 0);
        props[n].hb_w  = ngpng_type_u8(sc->hitbox_w, sc->type_role_count, src->type, 8u);
        props[n].hb_h  = ngpng_type_u8(sc->hitbox_h, sc->type_role_count, src->type, 8u);
        props[n].body_x = ngpng_type_s8(sc->body_x, sc->type_role_count, src->type, props[n].hb_x);
        props[n].body_y = ngpng_type_s8(sc->body_y, sc->type_role_count, src->type, props[n].hb_y);
        props[n].body_w = ngpng_type_u8(sc->body_w, sc->type_role_count, src->type, props[n].hb_w);
        props[n].body_h = ngpng_type_u8(sc->body_h, sc->type_role_count, src->type, props[n].hb_h);
        props[n].world_x = (s16)(((s16)src->x * 8) - ngpng_type_s8(sc->render_off_x, sc->type_role_count, src->type, 0));
        props[n].world_y = (s16)(((s16)src->y * 8) - ngpng_type_s8(sc->render_off_y, sc->type_role_count, src->type, 0));
        props[n].prev_world_x = props[n].world_x;
        props[n].prev_world_y = props[n].world_y;
        props[n].home_y       = props[n].world_y;
        props[n].target_x     = props[n].world_x;
        props[n].target_y     = props[n].world_y;
        props[n].draw_visible = 0u;
        props[n].last_draw_frame = 0xFFu;
        props[n].last_draw_flags = 0xFFu;
        props[n].last_used_parts = 0u;
        props[n].last_draw_spr   = 0u;
        props[n].last_draw_sx    = (s16)-32768;
        props[n].last_draw_sy    = (s16)-32768;
        props[n].cached_anim_st    = 0xFFu;
        props[n].cached_anim_frame = 0xFFu;
        props[n].cached_def        = 0;
        props[n].cached_rox = ngpng_type_s8(sc->render_off_x, sc->type_role_count, src->type,
            (s8)((props[n].hb_x < 0) ? props[n].hb_x : 0));
        props[n].cached_roy = ngpng_type_s8(sc->render_off_y, sc->type_role_count, src->type,
            (s8)((props[n].hb_y < 0) ? props[n].hb_y : 0));
        if (sc->entity_paths && i < sc->entity_count) {
            u8 assigned = sc->entity_paths[i];
            if (assigned != 0xFFu && assigned < sc->path_count) props[n].path_idx = assigned;
        }
        ++n;
    }
    *prop_count = n;
}

void ngpng_props_apply_path_step(const NgpSceneDef *sc, NgpngPropActor *prop)
{
    u8 pi;
    u8 plen;
    u16 off;
    const NgpngPoint *pt;
    s16 dst_x;
    s16 dst_y;
    if (!sc || !prop) return;
    if (prop->path_idx == 0xFFu || prop->path_idx >= sc->path_count) return;
    if (!sc->path_points || !sc->path_offsets || !sc->path_lengths) return;
    pi   = prop->path_idx;
    plen = sc->path_lengths[pi];
    if (plen == 0u) return;
    off = sc->path_offsets[pi];
    if (prop->path_step >= plen) prop->path_step = 0u;
    pt    = &sc->path_points[off + prop->path_step];
    dst_x = (s16)((s16)pt->x * 8);
    dst_y = (s16)((s16)pt->y * 8);
    {
        s8 spd = (sc->path_speeds) ? (s8)sc->path_speeds[pi] : 1;
        prop->world_x = (s16)(prop->world_x + ngpng_step_toward(prop->world_x, dst_x, spd));
        prop->world_y = (s16)(prop->world_y + ngpng_step_toward(prop->world_y, dst_y, spd));
    }
    if (prop->ent_flags & NGPNG_ENT_FLAG_CLAMP_MAP)
        ngpng_clamp_world_rect(sc, &prop->world_x, &prop->world_y, prop->body_w, prop->body_h);
    if (prop->world_x == dst_x && prop->world_y == dst_y) {
        prop->path_step = (u8)(prop->path_step + 1u);
        if (prop->path_step >= plen) {
            if (sc->path_flags && sc->path_flags[pi]) prop->path_step = 0u;
            else { prop->path_step = (u8)(plen - 1u); prop->paused = 1u; }
        }
    }
}

/* OPT-ANIM-CACHE: same pattern as ngpng_enemy_update_draw_cache.
 * anim_state is explicit in NgpngPropActor (not derived from physics).
 * Refresh start/count/spd from ROM only on anim_state change (~once per transition).
 * Every other frame: pure RAM arithmetic, 0 ROM lookups for the frame calc. */
static void ngpng_prop_update_draw_cache(const NgpSceneDef *sc, NgpngPropActor *p)
{
    u8 anim_st;
    u8 new_frame;
    u8 local_frame;
    u8 spd_frame;
    if (!sc || !sc->resolve_entity_frame) return;
    anim_st = (p->anim_state <= NGPNG_ANIM_DEATH) ? p->anim_state : NGPNG_ANIM_IDLE;
    if (anim_st != p->cached_anim_st) {
        p->cached_anim_st    = anim_st;
        p->cached_anim_start = ngpng_type_anim_start(sc, p->type, anim_st);
        p->cached_anim_count = ngpng_type_anim_count(sc, p->type, anim_st);
        p->cached_anim_spd   = ngpng_type_anim_speed(sc, p->type);
        if (p->cached_anim_count == 0u) {
            p->cached_anim_count = ngpng_type_anim_count(sc, p->type, NGPNG_ANIM_IDLE);
            p->cached_anim_start = ngpng_type_anim_start(sc, p->type, NGPNG_ANIM_IDLE);
        }
        if (p->cached_anim_count == 0u) p->cached_anim_count = 1u;
        if (p->cached_anim_spd   == 0u) p->cached_anim_spd   = 1u;
    }
    spd_frame = (p->cached_anim_spd == 1u) ? p->anim :
                (p->cached_anim_spd == 2u) ? (u8)(p->anim >> 1) :
                (p->cached_anim_spd == 4u) ? (u8)(p->anim >> 2) :
                (u8)(p->anim / p->cached_anim_spd);
    local_frame = (p->cached_anim_count == 1u) ? 0u :
                  (p->cached_anim_count == 2u) ? (u8)(spd_frame & 1u) :
                  (p->cached_anim_count == 4u) ? (u8)(spd_frame & 3u) :
                  (u8)(spd_frame % p->cached_anim_count);
    new_frame = (u8)(p->cached_anim_start + local_frame);
    if (new_frame != p->cached_anim_frame) {
        p->cached_anim_frame = new_frame;
        p->cached_def = sc->resolve_entity_frame(p->type, new_frame);
    }
}

void ngpng_props_update(const NgpSceneDef *sc, NgpngPropActor *props, u8 prop_count, s16 cam_px, s16 cam_py)
{
    u8 i;
    for (i = 0u; i < prop_count && i < (u8)NGPNG_AUTORUN_MAX_PROPS; ++i) {
        if (!props[i].active) continue;
        /* Screen-space cull: skip static props (no path, not moving, not block)
         * that are well outside the camera view. Path/moving/block props must
         * advance their state even when off-screen so they are correct when
         * the camera reaches them. Margin: 48px beyond each screen edge. */
        if (props[i].path_idx == 0xFFu && !props[i].moving
                && props[i].role != NGPNG_ROLE_BLOCK) {
            s16 rx = (s16)(props[i].world_x - cam_px);
            s16 ry = (s16)(props[i].world_y - cam_py);
            if (rx < (s16)-48 || rx > (s16)208 || ry < (s16)-48 || ry > (s16)200) continue;
        }
        props[i].anim         = (u8)(props[i].anim + 1u);
        props[i].prev_world_x = props[i].world_x;
        props[i].prev_world_y = props[i].world_y;
        /* OPT-E + OPT-ANIM-CACHE: static props throttled to every 4 frames.
         * ngpng_prop_update_draw_cache uses all-RAM arithmetic; only does ROM
         * lookups when anim_state actually changes (~once per transition). */
        if (props[i].path_idx == 0xFFu && !props[i].moving
                && props[i].role != NGPNG_ROLE_BLOCK
                && (props[i].anim & 3u) != 0u) {
            /* skip — cached values remain valid */
        } else {
            ngpng_prop_update_draw_cache(sc, &props[i]);
        }
        if (props[i].role == NGPNG_ROLE_BLOCK) {
            props[i].home_y = props[i].target_y;
            if (props[i].bump_timer > 0u) {
                u8 bt = props[i].bump_timer;
                if      (bt >= 5u) props[i].world_y = (s16)(props[i].home_y - 3);
                else if (bt >= 3u) props[i].world_y = (s16)(props[i].home_y - 1);
                else               props[i].world_y = props[i].home_y;
                props[i].bump_timer = (u8)(bt - 1u);
                continue;
            }
            props[i].world_y = props[i].home_y;
            continue;
        }
        if (props[i].path_idx != 0xFFu && !props[i].paused) {
            ngpng_props_apply_path_step(sc, &props[i]);
            continue;
        }
        if (!props[i].moving) continue;
        if (props[i].world_x < props[i].target_x) {
            s16 nx = (s16)(props[i].world_x + 2);
            props[i].world_x = (nx > props[i].target_x) ? props[i].target_x : nx;
        } else if (props[i].world_x > props[i].target_x) {
            s16 nx = (s16)(props[i].world_x - 2);
            props[i].world_x = (nx < props[i].target_x) ? props[i].target_x : nx;
        }
        if (props[i].world_y < props[i].target_y) {
            s16 ny = (s16)(props[i].world_y + 2);
            props[i].world_y = (ny > props[i].target_y) ? props[i].target_y : ny;
        } else if (props[i].world_y > props[i].target_y) {
            s16 ny = (s16)(props[i].world_y - 2);
            props[i].world_y = (ny < props[i].target_y) ? props[i].target_y : ny;
        }
        if (props[i].world_x == props[i].target_x && props[i].world_y == props[i].target_y)
            props[i].moving = 0u;
        if (props[i].ent_flags & NGPNG_ENT_FLAG_CLAMP_MAP)
            ngpng_clamp_world_rect(sc, &props[i].world_x, &props[i].world_y, props[i].body_w, props[i].body_h);
        if (props[i].ent_flags & NGPNG_ENT_FLAG_CLAMP_CAMERA)
            ngpng_clamp_camera_rect(&props[i].world_x, &props[i].world_y, cam_px, cam_py,
                props[i].body_w, props[i].body_h);
    }
}

void ngpng_player_apply_platform_delta(const NgpngPropActor *props, u8 prop_count,
    u8 rider_idx, s16 *px, s16 *py)
{
    const NgpngPropActor *p;
    if (!px || !py) return;
    if (rider_idx == 0xFFu || rider_idx >= prop_count || rider_idx >= (u8)NGPNG_AUTORUN_MAX_PROPS) return;
    p = &props[rider_idx];
    if (!p->active || !p->visible || p->role != NGPNG_ROLE_PLATFORM) return;
    *px = (s16)(*px + (p->world_x - p->prev_world_x));
    *py = (s16)(*py + (p->world_y - p->prev_world_y));
}

u8 ngpng_player_resolve_platforms(const NgpngPropActor *props, u8 prop_count,
    s16 prev_world_x, s16 prev_world_y, s16 cam_px, s16 cam_py,
    s16 *px, s16 *py, s8 *vy, u8 *on_ground, u8 *coyote,
    s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h)
{
    u8 i;
    u8 best      = 0xFFu;
    s16 best_top = 32767;
    s16 world_x;
    s16 world_y;
    s16 prev_left;
    s16 prev_right;
    s16 prev_foot;
    s16 foot;
    if (!px || !py || !vy || !on_ground) return 0xFFu;
    if (*vy < 0) return 0xFFu;
    world_x    = (s16)(cam_px + *px);
    world_y    = (s16)(cam_py + *py);
    prev_left  = (s16)(prev_world_x + hb_x + 1);
    prev_right = (s16)(prev_world_x + hb_x + ((hb_w > 1u) ? (hb_w - 2u) : 0u));
    prev_foot  = (s16)(prev_world_y + hb_y + hb_h);
    foot       = (s16)(world_y + hb_y + hb_h);
    for (i = 0u; i < prop_count && i < (u8)NGPNG_AUTORUN_MAX_PROPS; ++i) {
        const NgpngPropActor *p = &props[i];
        s16 plat_left;
        s16 plat_right;
        s16 plat_top;
        if (!p->active || !p->visible || p->role != NGPNG_ROLE_PLATFORM) continue;
        plat_left  = (s16)(p->world_x + p->body_x);
        plat_right = (s16)(plat_left + p->body_w);
        plat_top   = (s16)(p->world_y + p->body_y);
        if (prev_right <= plat_left || prev_left >= plat_right) continue;
        if (prev_foot > (s16)(plat_top + 4)) continue;
        if (foot < (s16)(plat_top - 2) || foot > (s16)(plat_top + 8)) continue;
        if (plat_top < best_top) { best_top = plat_top; best = i; }
    }
    if (best != 0xFFu) {
        const NgpngPropActor *p = &props[best];
        *py       = (s16)((p->world_y + p->body_y) - hb_y - hb_h - cam_py);
        *vy       = 0;
        *on_ground = 1u;
        if (coyote) *coyote = 0u;
    }
    return best;
}

void ngpng_player_collect_items(const NgpSceneDef *sc, NgpngPropActor *props, u8 prop_count,
    s16 player_world_x, s16 player_world_y, s8 player_hb_x, s8 player_hb_y,
    u8 player_hb_w, u8 player_hb_h, u16 *score, u8 *hp, u8 hp_max, u16 *collectible_count)
{
    u8 i;
    s16 ax;
    s16 ay;
    if (!sc || !props) return;
    ax = (s16)(player_world_x + player_hb_x);
    ay = (s16)(player_world_y + player_hb_y);
    for (i = 0u; i < prop_count && i < (u8)NGPNG_AUTORUN_MAX_PROPS; ++i) {
        u8 score_gain;
        u8 heal_gain;
        u8 mult;
        s16 bx;
        s16 by;
        if (!props[i].active || !props[i].visible || props[i].role != NGPNG_ROLE_ITEM) continue;
        bx = (s16)(props[i].world_x + props[i].hb_x);
        by = (s16)(props[i].world_y + props[i].hb_y);
        if (!ngpng_rects_overlap(ax, ay, player_hb_w, player_hb_h, bx, by, props[i].hb_w, props[i].hb_h)) continue;
        mult       = props[i].data ? props[i].data : 1u;
        score_gain = ngpng_type_u8(sc->type_score, sc->type_role_count, props[i].type, 0u);
        heal_gain  = ngpng_type_u8(sc->type_hp,    sc->type_role_count, props[i].type, 0u);
        if (score_gain == 0u && heal_gain == 0u) score_gain = 1u;
        if (score     && score_gain > 0u) *score = (u16)(*score + ((u16)score_gain * (u16)mult * 10u));
        if (hp && heal_gain > 0u && *hp < hp_max) {
            u16 next_hp = (u16)(*hp + (u16)(heal_gain * mult));
            *hp = (next_hp > hp_max) ? hp_max : (u8)next_hp;
        }
        if (collectible_count) *collectible_count = (u16)(*collectible_count + (u16)mult);
        ngpng_prop_hide_draw(props, i);
        props[i].active  = 0u;
        props[i].visible = 0u;
    }
}

void ngpng_player_collide_damage_props(const NgpSceneDef *sc, NgpngPropActor *props, u8 prop_count,
    s16 player_world_x, s16 player_world_y, s8 *player_vx, s8 *player_vy,
    s8 player_hb_x, s8 player_hb_y, u8 player_hb_w, u8 player_hb_h,
    u8 *hp, u8 *invul)
{
    u8 i;
    u8 best_hit      = 0u;
    u8 best_priority = 0u;
    u8 best_damage   = 0u;
    s8 best_kb_x     = 0;
    s8 best_kb_y     = 0;
    s16 ax;
    s16 ay;
    if (!sc || !props || !player_vx || !player_vy || !hp || !invul) return;
    if (*hp == 0u || *invul != 0u) return;
    ax = (s16)(player_world_x + player_hb_x);
    ay = (s16)(player_world_y + player_hb_y);
    for (i = 0u; i < prop_count && i < (u8)NGPNG_AUTORUN_MAX_PROPS; ++i) {
        u8 atk_count;
        u8 atk_start;
        u8 atk_idx;
        u8 type_damage;
        u8 prop_anim_state;
        if (!props[i].active || !props[i].visible || props[i].role != NGPNG_ROLE_PROP) continue;
        type_damage = ngpng_type_u8(sc->type_damage, sc->type_role_count, props[i].type, 0u);
        prop_anim_state = props[i].anim_state;
        if (type_damage > 0u &&
            ngpng_rects_overlap(ax, ay, player_hb_w, player_hb_h,
                (s16)(props[i].world_x + props[i].hb_x), (s16)(props[i].world_y + props[i].hb_y),
                props[i].hb_w, props[i].hb_h)) {
            if (!best_hit) {
                best_hit = 1u;
                best_priority = 0u;
                best_damage = type_damage;
                best_kb_x = ngpng_type_attack_s8(sc->attack_hitbox_kb_x, 0, sc->type_role_count, props[i].type, 0);
                best_kb_y = ngpng_type_attack_s8(sc->attack_hitbox_kb_y, 0, sc->type_role_count, props[i].type, 0);
            }
        }
        atk_count = ngpng_attack_box_count(sc, props[i].type);
        if (atk_count == 0u) continue;
        atk_start = ngpng_attack_box_start(sc, props[i].type);
        for (atk_idx = 0u; atk_idx < atk_count; ++atk_idx) {
            s16 atk_x;
            s16 atk_y;
            u8 atk_w;
            u8 atk_h;
            u8 atk_damage;
            s8 atk_kb_x;
            s8 atk_kb_y;
            u8 atk_priority;
            u8 atk_active_start;
            u8 atk_active_len;
            u8 atk_anim_state;
            u8 anim_frame = (u8)((props[i].anim / 8u) & 0x03u);
            if (sc->attack_hitboxes_x && sc->attack_hitboxes_y &&
                sc->attack_hitboxes_w && sc->attack_hitboxes_h) {
                u8 flat_idx = (u8)(atk_start + atk_idx);
                atk_x = (s16)(props[i].world_x + sc->attack_hitboxes_x[flat_idx]);
                atk_y = (s16)(props[i].world_y + sc->attack_hitboxes_y[flat_idx]);
                atk_w = sc->attack_hitboxes_w[flat_idx];
                atk_h = sc->attack_hitboxes_h[flat_idx];
                atk_damage = sc->attack_hitboxes_damage
                    ? sc->attack_hitboxes_damage[flat_idx] : 0u;
                if (atk_damage == 0u) {
                    atk_damage = ngpng_type_u8(sc->type_damage, sc->type_role_count, props[i].type, 0u);
                }
                atk_kb_x = sc->attack_hitboxes_kb_x
                    ? sc->attack_hitboxes_kb_x[flat_idx] : 0;
                atk_kb_y = sc->attack_hitboxes_kb_y
                    ? sc->attack_hitboxes_kb_y[flat_idx] : 0;
                atk_priority = sc->attack_hitboxes_priority
                    ? sc->attack_hitboxes_priority[flat_idx] : 0u;
                atk_active_start = sc->attack_hitboxes_active_start
                    ? sc->attack_hitboxes_active_start[flat_idx] : 0u;
                atk_active_len = sc->attack_hitboxes_active_len
                    ? sc->attack_hitboxes_active_len[flat_idx] : 0u;
                atk_anim_state = sc->attack_hitboxes_anim_state
                    ? sc->attack_hitboxes_anim_state[flat_idx] : 0xFFu;
            } else {
                atk_x = (s16)(props[i].world_x + ngpng_type_attack_s8(
                    sc->attack_hitbox_x, sc->hitbox_x, sc->type_role_count, props[i].type, props[i].hb_x));
                atk_y = (s16)(props[i].world_y + ngpng_type_attack_s8(
                    sc->attack_hitbox_y, sc->hitbox_y, sc->type_role_count, props[i].type, props[i].hb_y));
                atk_w = ngpng_type_attack_u8(
                    sc->attack_hitbox_w, sc->hitbox_w, sc->type_role_count, props[i].type, props[i].hb_w);
                atk_h = ngpng_type_attack_u8(
                    sc->attack_hitbox_h, sc->hitbox_h, sc->type_role_count, props[i].type, props[i].hb_h);
                atk_damage = ngpng_type_attack_damage_u8(
                    sc->attack_hitbox_damage, sc->type_damage, sc->type_role_count, props[i].type, 0u);
                atk_kb_x = ngpng_type_attack_s8(sc->attack_hitbox_kb_x, 0, sc->type_role_count, props[i].type, 0);
                atk_kb_y = ngpng_type_attack_s8(sc->attack_hitbox_kb_y, 0, sc->type_role_count, props[i].type, 0);
                atk_priority = ngpng_type_u8(sc->attack_hitbox_priority, sc->type_role_count, props[i].type, 0u);
                atk_active_start = ngpng_type_u8(sc->attack_hitbox_active_start, sc->type_role_count, props[i].type, 0u);
                atk_active_len = ngpng_type_u8(sc->attack_hitbox_active_len, sc->type_role_count, props[i].type, 0u);
                atk_anim_state = sc->attack_hitbox_anim_state
                    ? ngpng_type_u8(sc->attack_hitbox_anim_state, sc->type_role_count, props[i].type, 0xFFu)
                    : 0xFFu;
            }
            if (atk_w == 0u || atk_h == 0u || atk_damage == 0u) continue;
            if (!ngpng_attack_window_active(anim_frame, atk_active_start, atk_active_len, atk_anim_state, prop_anim_state)) continue;
            if (!ngpng_rects_overlap(ax, ay, player_hb_w, player_hb_h, atk_x, atk_y, atk_w, atk_h)) continue;
            if (!best_hit || atk_priority >= best_priority) {
                best_hit = 1u;
                best_priority = atk_priority;
                best_damage = atk_damage;
                best_kb_x = atk_kb_x;
                best_kb_y = atk_kb_y;
            }
        }
    }
    if (!best_hit) return;
    if (best_damage >= *hp) *hp = 0u;
    else *hp = (u8)(*hp - best_damage);
    *player_vx = ngpng_add_s8_clamped(*player_vx, best_kb_x);
    *player_vy = ngpng_add_s8_clamped(*player_vy, best_kb_y);
    *invul = (sc && sc->hazard_invul > 0u) ? sc->hazard_invul : 30u;
}

void ngpng_player_collide_solid_props(const NgpngPropActor *props, u8 prop_count,
    s16 cam_px, s16 cam_py,
    s16 *px, s16 *py, s8 *vx, s8 *vy,
    s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h)
{
    u8  i;
    s16 ax;
    s16 ay;
    s16 bx;
    s16 by;
    s16 pa_r;
    s16 pa_b;
    s16 pb_r;
    s16 pb_b;
    s16 ovx;
    s16 ovy;
    if (!props || !px || !py || !vx || !vy) return;
    ax = (s16)(cam_px + *px + (s16)hb_x);
    ay = (s16)(cam_py + *py + (s16)hb_y);
    for (i = 0u; i < prop_count && i < (u8)NGPNG_AUTORUN_MAX_PROPS; ++i) {
        if (!props[i].active) continue;
        if (!props[i].visible) continue;
        if (props[i].role != NGPNG_ROLE_NPC && props[i].role != NGPNG_ROLE_PROP) continue;
        if (props[i].hb_w == 0u) continue;
        if (props[i].hb_h == 0u) continue;
        bx   = (s16)(props[i].world_x + (s16)props[i].hb_x);
        by   = (s16)(props[i].world_y + (s16)props[i].hb_y);
        pa_r = (s16)(ax + (s16)hb_w);
        pa_b = (s16)(ay + (s16)hb_h);
        pb_r = (s16)(bx + (s16)props[i].hb_w);
        pb_b = (s16)(by + (s16)props[i].hb_h);
        if (ax >= pb_r) continue;
        if (pa_r <= bx) continue;
        if (ay >= pb_b) continue;
        if (pa_b <= by) continue;
        ovx = (s16)((pa_r < pb_r ? pa_r : pb_r) - (ax > bx ? ax : bx));
        ovy = (s16)((pa_b < pb_b ? pa_b : pb_b) - (ay > by ? ay : by));
        if (ovx <= ovy) {
            if ((s16)(ax + (s16)(hb_w >> 1)) < (s16)(bx + (s16)(props[i].hb_w >> 1))) {
                *px = (s16)(*px - ovx);
                ax  = (s16)(ax  - ovx);
            } else {
                *px = (s16)(*px + ovx);
                ax  = (s16)(ax  + ovx);
            }
            *vx = 0;
        } else {
            if ((s16)(ay + (s16)(hb_h >> 1)) < (s16)(by + (s16)(props[i].hb_h >> 1))) {
                *py = (s16)(*py - ovy);
                ay  = (s16)(ay  - ovy);
            } else {
                *py = (s16)(*py + ovy);
                ay  = (s16)(ay  + ovy);
            }
            *vy = 0;
        }
    }
}

void ngpng_player_bump_blocks(const NgpSceneDef *sc, NgpngPropActor *props, u8 prop_count,
    s16 prev_world_x, s16 prev_world_y, s16 cam_px, s16 cam_py,
    s16 *px, s16 *py, s8 *vy, s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h,
    u16 *score, u8 *hp, u8 hp_max, u16 *collectible_count)
{
    u8 i;
    s16 world_x;
    s16 world_y;
    s16 left;
    s16 right;
    s16 prev_head;
    s16 head;
    if (!sc || !props || !px || !py || !vy) return;
    if (*vy >= 0) return;
    world_x   = (s16)(cam_px + *px);
    world_y   = (s16)(cam_py + *py);
    left      = (s16)(world_x + hb_x + 1);
    right     = (s16)(world_x + hb_x + ((hb_w > 1u) ? (hb_w - 2u) : 0u));
    prev_head = (s16)(prev_world_y + hb_y);
    head      = (s16)(world_y + hb_y);
    for (i = 0u; i < prop_count && i < (u8)NGPNG_AUTORUN_MAX_PROPS; ++i) {
        s16 bx0;
        s16 bx1;
        s16 by0;
        s16 by1;
        u8 block_kind;
        if (!props[i].active || !props[i].visible || props[i].role != NGPNG_ROLE_BLOCK) continue;
        bx0 = (s16)(props[i].world_x + props[i].body_x);
        bx1 = (s16)(bx0 + props[i].body_w);
        by0 = (s16)(props[i].world_y + props[i].body_y);
        by1 = (s16)(by0 + props[i].body_h);
        if (right <= bx0 || left >= bx1) continue;
        if (prev_head < by1 - 2 || head > by1 + 2) continue;
        *py = (s16)(by1 - hb_y - cam_py);
        *vy = 0;
        props[i].bump_timer = 6u;
        block_kind = props[i].data;
        if (block_kind == 1u) {
            ngpng_prop_hide_draw(props, i);
            props[i].active  = 0u;
            props[i].visible = 0u;
        } else if (block_kind == 2u) {
            if (props[i].state == 0u) {
                u8 score_gain = ngpng_type_u8(sc->type_score, sc->type_role_count, props[i].type, 1u);
                u8 heal_gain  = ngpng_type_u8(sc->type_hp,    sc->type_role_count, props[i].type, 0u);
                if (score) *score = (u16)(*score + ((u16)score_gain * 10u));
                if (collectible_count) *collectible_count = (u16)(*collectible_count + 1u);
                if (hp && heal_gain > 0u && *hp < hp_max) {
                    u16 next_hp = (u16)(*hp + heal_gain);
                    *hp = (next_hp > hp_max) ? hp_max : (u8)next_hp;
                }
                props[i].state = 1u;
                props[i].anim  = 8u;
            }
        }
        return;
    }
}

void ngpng_props_draw(const NgpSceneDef *sc, NgpngPropActor *props, u8 prop_count,
    s16 cam_px, s16 cam_py)
{
    u8 i;
    u8 pass;
    u8 spr     = (u8)NGPNG_AUTORUN_PROP_SPR_BASE;
    u8 spr_end = (u8)(NGPNG_AUTORUN_PROP_SPR_BASE + NGPNG_AUTORUN_PROP_SPR_COUNT);
    if (!NGPNG_AUTORUN_ENT_PREVIEW || !sc || NGPNG_AUTORUN_PROP_SPR_COUNT == 0u) return;
#if NGPNG_PERF7_LEGACY_REDRAW
    ngpng_sprite_hide_range((u8)NGPNG_AUTORUN_PROP_SPR_BASE, (u8)NGPNG_AUTORUN_PROP_SPR_COUNT);
    /* OPT-2B: use cached_def directly — skip draw_entity_anim function pointer dispatch.
     * cached_def is already resolved in props_update; no ROM lookup needed here. */
    for (pass = 0u; pass < 2u && spr < spr_end; ++pass) {
        for (i = prop_count; i > 0u && spr < spr_end; ) {
            const NgpcMetasprite *def;
            u8 used;
            s16 sx;
            s16 sy;
            --i;
            if (i >= (u8)NGPNG_AUTORUN_MAX_PROPS) continue;
            if (!props[i].active || !props[i].visible) continue;
            if (((props[i].role == NGPNG_ROLE_PLATFORM) ? 0u : 1u) != pass) continue;
            def = props[i].cached_def;
            if (!def || def->count == 0u) continue;
            sx = (s16)(props[i].world_x - cam_px + props[i].cached_rox);
            sy = (s16)(props[i].world_y - cam_py + props[i].cached_roy);
            if (!ngpng_sprite_mspr_intersects_screen(sx, sy, def)) continue;
            if ((u16)spr + def->count > spr_end) continue;
            used = ngpng_sprite_mspr_draw(spr, sx, sy, def, g_ngpng_entity_prio);
            if (used == 0u) continue;
            spr = (u8)(spr + used);
        }
    }
#else
    if (!sc->resolve_entity_frame) return;
    for (i = 0u; i < prop_count && i < (u8)NGPNG_AUTORUN_MAX_PROPS; ++i) {
        if (!props[i].active || !props[i].visible) ngpng_prop_hide_draw(props, i);
    }
    /* OPT-F: skip platform pass entirely when scene has no ROLE_PLATFORM props.
     * Saves 1 full sweep (~21 iterations) for shmup/platformer scenes without
     * moving platforms. When platforms exist, both passes run unchanged. */
    for (pass = (sc->scene_flags & SCENE_FLAG_HAS_PLATFORMS) ? 0u : 1u; pass < 2u; ++pass) {
        for (i = prop_count; i > 0u; ) {
            const NgpcMetasprite *def;
            u8 anim_frame;
            u8 old_spr;
            u8 old_count;
            u8 spr_start;
            s16 sx;
            s16 sy;
            --i;
            if (i >= (u8)NGPNG_AUTORUN_MAX_PROPS) continue;
            if (!props[i].active || !props[i].visible) continue;
            if (((props[i].role == NGPNG_ROLE_PLATFORM) ? 0u : 1u) != pass) continue;
            anim_frame = props[i].cached_anim_frame;
            def        = props[i].cached_def;
            if (anim_frame == 0xFFu || !def || def->count == 0u) {
                ngpng_prop_hide_draw(props, i);
                continue;
            }
            sx = (s16)(props[i].world_x - cam_px + props[i].cached_rox);
            sy = (s16)(props[i].world_y - cam_py + props[i].cached_roy);
            if (!ngpng_sprite_mspr_intersects_screen(sx, sy, def)) {
                ngpng_prop_hide_draw(props, i);
                continue;
            }
            old_spr = props[i].last_draw_spr;
            old_count = props[i].last_used_parts;
            if (!ngpng_prop_spr_acquire(&props[i], def->count, &spr_start)) {
                ngpng_prop_hide_draw(props, i);
                continue;
            }
            /* OPT-B: props are mostly static — skip the 7-pointer sync call when
             * position, frame, flags and slot are unchanged from last frame. */
            if (props[i].draw_visible &&
                props[i].last_draw_spr   == spr_start &&
                props[i].last_used_parts == def->count &&
                props[i].last_draw_sx    == sx &&
                props[i].last_draw_sy    == sy &&
                props[i].last_draw_frame == anim_frame &&
                props[i].last_draw_flags == g_ngpng_entity_prio) {
                continue;
            }
            ngpng_sprite_mspr_sync(spr_start, sx, sy, def, anim_frame, g_ngpng_entity_prio,
                &props[i].draw_visible, &props[i].last_draw_spr, &props[i].last_used_parts,
                &props[i].last_draw_sx, &props[i].last_draw_sy,
                &props[i].last_draw_frame, &props[i].last_draw_flags);
            if (spr_start == old_spr && old_count > props[i].last_used_parts)
                ngpng_prop_spr_free((u8)(spr_start + props[i].last_used_parts),
                    (u8)(old_count - props[i].last_used_parts));
        }
    }
#endif
}

#endif /* NGPNG_HAS_PROP_ACTOR */

/* ==========================================================================
 * Combat / player-enemy collision
 * ========================================================================== */
#if NGPNG_HAS_COMBAT

void ngpng_player_collide_enemies(const NgpSceneDef *sc, NgpngEnemy *enemies,
    u8 *enemy_active_count, s16 px, s16 *py, s8 *player_vx, s8 *player_vy,
    s8 player_hb_x, s8 player_hb_y, u8 player_hb_w, u8 player_hb_h,
    s16 cam_px, s16 cam_py, u8 *hp, u8 *invul, u16 *score, u8 explosion_type,
    NgpngFx *fx, u8 *fx_active_count, u8 *fx_alloc_idx)
{
    u8 i;
    u8 processed     = 0u;
    u8 best_hit      = 0u;
    u8 best_priority = 0u;
    u8 best_damage   = 0u;
    s8 best_kb_x     = 0;
    s8 best_kb_y     = 0;
    s16 ax;
    s16 ay;
    if (!py || !player_vx || !player_vy || !hp || !invul) return;
    if (*hp == 0u || *invul != 0u || *enemy_active_count == 0u) return;
    ax = (s16)(px + player_hb_x);
    ay = (s16)(*py + player_hb_y);
    for (i = 0; i < (u8)NGPNG_AUTORUN_MAX_ENEMIES; ++i) {
        s16 exs;
        s16 eys;
        u8 touch_hurt;
        s16 enemy_top;
        s16 player_bottom;
        if (!enemies[i].active) continue;
        processed    = (u8)(processed + 1u);
        exs          = (s16)((enemies[i].world_x - cam_px) + enemies[i].hb_x);
        eys          = (s16)((enemies[i].world_y - cam_py) + enemies[i].hb_y);
        touch_hurt   = ngpng_rects_overlap(ax, ay, player_hb_w, player_hb_h,
                                            exs, eys, enemies[i].hb_w, enemies[i].hb_h);
        enemy_top    = eys;
        player_bottom = (s16)(*py + player_hb_y + player_hb_h);
        if (touch_hurt && enemies[i].gravity > 0u && *player_vy > 0 &&
            player_bottom <= (s16)(enemy_top + 6)) {
            s16 ex = enemies[i].world_x;
            s16 ey = enemies[i].world_y;
            s8 ex_rox = ngpng_type_s8(sc->render_off_x, sc->type_role_count, enemies[i].type,
                (s8)((enemies[i].hb_x < 0) ? enemies[i].hb_x : 0));
            s8 ex_roy = ngpng_type_s8(sc->render_off_y, sc->type_role_count, enemies[i].type,
                (s8)((enemies[i].hb_y < 0) ? enemies[i].hb_y : 0));
            ex = (s16)(ex + ex_rox);
            ey = (s16)(ey + ex_roy);
            *py        = (s16)(enemy_top - player_hb_y - player_hb_h);
            *player_vy = -4;
            if (score) *score = (u16)(*score + enemies[i].score);
            ngpng_enemy_kill(enemies, enemy_active_count, i);
            if (sc && ngpng_type_anim_count(sc, enemies[i].type, NGPNG_ANIM_DEATH) > 0u) {
                ngpng_fx_spawn_anim_state(sc, fx, fx_active_count, fx_alloc_idx,
                    enemies[i].type, NGPNG_ANIM_DEATH, ex, ey);
            } else {
                ngpng_fx_spawn(fx, fx_active_count, fx_alloc_idx, explosion_type, ex, ey);
            }
            return;
        } else {
            u8 atk_count = ngpng_attack_box_count(sc, enemies[i].type);
            u8 atk_start = ngpng_attack_box_start(sc, enemies[i].type);
            u8 atk_idx;
            u8 cur_anim_state = (enemies[i].vy < -1) ? NGPNG_ANIM_JUMP :
                ((enemies[i].vy > 1) ? NGPNG_ANIM_FALL :
                ((enemies[i].vx != 0) ? NGPNG_ANIM_WALK : NGPNG_ANIM_IDLE));
            if (atk_count == 0u) atk_count = 1u;
            for (atk_idx = 0u; atk_idx < atk_count; ++atk_idx) {
                s16 atk_x;
                s16 atk_y;
                u8 atk_w;
                u8 atk_h;
                s8 atk_kb_x;
                s8 atk_kb_y;
                u8 atk_damage;
                u8 atk_priority;
                u8 atk_active_start;
                u8 atk_active_len;
                u8 atk_anim_state;
                u8 anim_frame = (u8)((enemies[i].anim / 8u) & 0x03u);
                if (sc->attack_hitboxes_x && sc->attack_hitboxes_y &&
                    sc->attack_hitboxes_w && sc->attack_hitboxes_h) {
                    u8 flat_idx = (u8)(atk_start + atk_idx);
                    atk_x = (s16)((enemies[i].world_x - cam_px) + sc->attack_hitboxes_x[flat_idx]);
                    atk_y = (s16)((enemies[i].world_y - cam_py) + sc->attack_hitboxes_y[flat_idx]);
                    atk_w = sc->attack_hitboxes_w[flat_idx];
                    atk_h = sc->attack_hitboxes_h[flat_idx];
                    atk_damage = sc->attack_hitboxes_damage
                        ? sc->attack_hitboxes_damage[flat_idx] : enemies[i].damage;
                    if (atk_damage == 0u) atk_damage = enemies[i].damage;
                    atk_kb_x = sc->attack_hitboxes_kb_x
                        ? sc->attack_hitboxes_kb_x[flat_idx] : enemies[i].atk_kb_x;
                    atk_kb_y = sc->attack_hitboxes_kb_y
                        ? sc->attack_hitboxes_kb_y[flat_idx] : enemies[i].atk_kb_y;
                    atk_priority = sc->attack_hitboxes_priority
                        ? sc->attack_hitboxes_priority[flat_idx] : 0u;
                    atk_active_start = sc->attack_hitboxes_active_start
                        ? sc->attack_hitboxes_active_start[flat_idx] : 0u;
                    atk_active_len = sc->attack_hitboxes_active_len
                        ? sc->attack_hitboxes_active_len[flat_idx] : 0u;
                    atk_anim_state = sc->attack_hitboxes_anim_state
                        ? sc->attack_hitboxes_anim_state[flat_idx] : 0xFFu;
                } else {
                    atk_x = (s16)((enemies[i].world_x - cam_px) + enemies[i].atk_hb_x);
                    atk_y = (s16)((enemies[i].world_y - cam_py) + enemies[i].atk_hb_y);
                    atk_w = enemies[i].atk_hb_w;
                    atk_h = enemies[i].atk_hb_h;
                    atk_damage   = enemies[i].damage;
                    atk_kb_x     = enemies[i].atk_kb_x;
                    atk_kb_y     = enemies[i].atk_kb_y;
                    atk_priority = ngpng_type_u8(sc->attack_hitbox_priority,
                        sc->type_role_count, enemies[i].type, 0u);
                    atk_active_start = ngpng_type_u8(sc->attack_hitbox_active_start,
                        sc->type_role_count, enemies[i].type, 0u);
                    atk_active_len = ngpng_type_u8(sc->attack_hitbox_active_len,
                        sc->type_role_count, enemies[i].type, 0u);
                    atk_anim_state = sc->attack_hitbox_anim_state
                        ? ngpng_type_u8(sc->attack_hitbox_anim_state,
                            sc->type_role_count, enemies[i].type, 0xFFu)
                        : 0xFFu;
                }
                if (atk_w == 0u || atk_h == 0u) continue;
                if (!ngpng_attack_window_active(anim_frame, atk_active_start, atk_active_len, atk_anim_state, cur_anim_state)) continue;
                if (!ngpng_rects_overlap(ax, ay, player_hb_w, player_hb_h,
                                          atk_x, atk_y, atk_w, atk_h)) continue;
                if (!best_hit || atk_priority > best_priority) {
                    best_hit      = 1u;
                    best_priority = atk_priority;
                    best_damage   = atk_damage;
                    best_kb_x     = atk_kb_x;
                    best_kb_y     = atk_kb_y;
                }
            }
        }
        if (processed >= *enemy_active_count) break;
    }
    if (!best_hit) return;
    if (best_damage >= *hp) *hp = 0u;
    else *hp = (u8)(*hp - best_damage);
    *player_vx = ngpng_add_s8_clamped(*player_vx, best_kb_x);
    *player_vy = ngpng_add_s8_clamped(*player_vy, best_kb_y);
    *invul = 30u;
}

#endif /* NGPNG_HAS_COMBAT */
