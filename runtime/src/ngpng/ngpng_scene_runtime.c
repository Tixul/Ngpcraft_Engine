/* ngpng_scene_runtime.c -- Scene enter/reset helpers.
 * Part of the ngpng static module layer (NGPC PNG Manager).
 * Overwritten on next export -- do not hand-edit.
 */
#include "ngpng_scene_runtime.h"

static u8 ngpng_scene_runtime_continue_lives(const NgpSceneDef *sc)
{
    if (!sc) return 0u;
    if (sc->continue_restore_lives > 0u) return sc->continue_restore_lives;
    return sc->start_lives;
}

static u8 ngpng_scene_runtime_find_unused_prop_type(const NgpSceneDef *sc)
{
    u8 type_idx;
    u8 ent_idx;
    u8 used;
    if (!sc || !sc->type_roles || sc->type_role_count == 0u) return 0xFFu;
    for (type_idx = 0; type_idx < sc->type_role_count; ++type_idx) {
        if (ngpng_entity_role(sc, type_idx) != NGPNG_ROLE_PROP) continue;
        used = 0u;
        if (sc->entities) {
            for (ent_idx = 0; ent_idx < sc->entity_count; ++ent_idx) {
                if (sc->entities[ent_idx].type == type_idx) {
                    used = 1u;
                    break;
                }
            }
        }
        if (!used) return type_idx;
    }
    return 0xFFu;
}

static void ngpng_scene_runtime_refresh_player_meta(const NgpSceneDef *sc,
    NgpngSceneRuntimeState *rt)
{
    if (!sc || !rt) return;
    if (rt->player_form) *rt->player_form = 0u;
    if (rt->player_form_mode) *rt->player_form_mode = 0u;
    if (rt->player_form_count) {
        *rt->player_form_count = ngpng_count_types_by_role(sc, NGPNG_ROLE_PLAYER);
    }
    if (rt->player_ent_flags) {
        *rt->player_ent_flags = ngpng_find_first_entity_flags_by_role(sc, NGPNG_ROLE_PLAYER);
    }
    if (rt->player_type && rt->player_hb_x && rt->player_hb_y &&
        rt->player_hb_w && rt->player_hb_h &&
        rt->player_body_x && rt->player_body_y &&
        rt->player_body_w && rt->player_body_h &&
        rt->player_render_off_x && rt->player_render_off_y &&
        rt->player_frame_w && rt->player_frame_h &&
        rt->player_hp && rt->player_hp_max) {
        ngpng_player_apply_form(sc, 0u,
            rt->player_type,
            rt->player_hb_x, rt->player_hb_y, rt->player_hb_w, rt->player_hb_h,
            rt->player_body_x, rt->player_body_y, rt->player_body_w, rt->player_body_h,
            rt->player_render_off_x, rt->player_render_off_y,
            rt->player_frame_w, rt->player_frame_h,
            rt->player_hp, rt->player_hp_max,
            1u);
    }
    if (rt->explosion_type) {
        *rt->explosion_type = ngpng_scene_runtime_find_unused_prop_type(sc);
    }
}

static void ngpng_scene_runtime_refresh_player_projectile(const NgpSceneDef *sc,
    NgpngSceneRuntimeState *rt)
{
    u8 bullet_type;
    if (!rt) return;
    if (rt->player_bullet_type) *rt->player_bullet_type = 0xFFu;
    if (rt->player_bullet_ready) *rt->player_bullet_ready = 0u;
    if (!sc ||
        !rt->player_bullet_type ||
        !rt->player_bullet_ready ||
        !rt->player_bullet_tile ||
        !rt->player_bullet_pal ||
        !rt->player_bullet_flags ||
        !rt->player_bullet_ox ||
        !rt->player_bullet_oy ||
        !rt->player_bullet_hb_x ||
        !rt->player_bullet_hb_y ||
        !rt->player_bullet_hb_w ||
        !rt->player_bullet_hb_h ||
        !rt->player_bullet_damage ||
        !rt->player_bullet_kb_x ||
        !rt->player_bullet_kb_y) {
        return;
    }
    bullet_type = *rt->player_bullet_type;
    if (bullet_type == 0xFFu) return;
#if NGPNG_HAS_ENEMY || NGPNG_HAS_FX || NGPNG_HAS_PROP_ACTOR
    if (ngpng_entity_sprite_info(sc, bullet_type, 0u,
        rt->player_bullet_tile, rt->player_bullet_pal, rt->player_bullet_flags,
        rt->player_bullet_ox, rt->player_bullet_oy)) {
        *rt->player_bullet_ready = 1u;
    }
#endif
    *rt->player_bullet_hb_x = ngpng_type_attack_s8(sc->attack_hitbox_x, sc->hitbox_x,
        sc->type_role_count, bullet_type, 0);
    *rt->player_bullet_hb_y = ngpng_type_attack_s8(sc->attack_hitbox_y, sc->hitbox_y,
        sc->type_role_count, bullet_type, 0);
    *rt->player_bullet_hb_w = ngpng_type_attack_u8(sc->attack_hitbox_w, sc->hitbox_w,
        sc->type_role_count, bullet_type, 8u);
    *rt->player_bullet_hb_h = ngpng_type_attack_u8(sc->attack_hitbox_h, sc->hitbox_h,
        sc->type_role_count, bullet_type, 8u);
    *rt->player_bullet_damage = ngpng_type_attack_damage_u8(sc->attack_hitbox_damage,
        sc->type_damage, sc->type_role_count, bullet_type, 1u);
    *rt->player_bullet_kb_x = ngpng_type_attack_s8(sc->attack_hitbox_kb_x, 0,
        sc->type_role_count, bullet_type, 0);
    *rt->player_bullet_kb_y = ngpng_type_attack_s8(sc->attack_hitbox_kb_y, 0,
        sc->type_role_count, bullet_type, 0);
}

void ngpng_scene_runtime_enter_view(const NgpSceneDef *sc, u8 scene_idx,
    s16 *cam_px, s16 *cam_py, u16 *tx, u16 *ty)
{
    if (!sc || !cam_px || !cam_py || !tx || !ty) return;
    *cam_px = (s16)(sc->cam_tile_x * 8u);
    *cam_py = (s16)(sc->cam_tile_y * 8u);
    ngpng_apply_camera_constraints(sc, cam_px, cam_py);
    ngpng_update_plane_scroll(sc, *cam_px, *cam_py);
    (void)scene_idx;
    *tx = (u16)(*cam_px >> 3);
    *ty = (u16)(*cam_py >> 3);
}

void ngpng_scene_runtime_full_reset(const NgpSceneDef *sc,
    NgpngSceneRuntimeState *rt,
    u8 lives_mode, u8 reset_continues,
    u8 reset_checkpoints, u8 hide_all_sprites, u8 reset_hud)
{
    if (!sc || !rt) return;
#if NGPNG_HAS_ENEMY
    if (rt->enemies && rt->enemy_active_count && rt->enemy_alloc_idx) {
        ngpng_enemies_reset_scene(sc, rt->enemies, rt->enemy_active_count, rt->enemy_alloc_idx);
    }
#endif
#if NGPNG_HAS_FX
    if (rt->fx && rt->fx_active_count && rt->fx_alloc_idx) {
        ngpng_fx_clear(rt->fx, rt->fx_active_count, rt->fx_alloc_idx);
    }
#endif
#if NGPNG_HAS_PROP_ACTOR
    if (rt->props && rt->prop_count) {
        ngpng_props_reset_scene(sc, rt->props, rt->prop_count);
    }
#endif
    ngpng_scene_runtime_refresh_player_meta(sc, rt);
    ngpng_scene_runtime_refresh_player_projectile(sc, rt);
    if (rt->player_invul) *rt->player_invul = 0u;
    if (rt->game_over) *rt->game_over = 0u;
    if (rt->stage_clear) *rt->stage_clear = 0u;
    if (rt->lives) {
        if (lives_mode == NGPNG_SCENE_RT_LIVES_START) {
            *rt->lives = sc->start_lives;
        } else if (lives_mode == NGPNG_SCENE_RT_LIVES_CONTINUE) {
            *rt->lives = ngpng_scene_runtime_continue_lives(sc);
        }
    }
    if (reset_continues && rt->continues_left) {
        *rt->continues_left = sc->start_continues;
    }
    if (rt->respawn_timer) *rt->respawn_timer = 0u;
    if (rt->fire_cd) *rt->fire_cd = 0u;
    if (rt->player_platform) *rt->player_platform = 0xFFu;
    if (rt->collectible_count) *rt->collectible_count = 0u;
    if (reset_checkpoints) {
        if (rt->checkpoint_scene) *rt->checkpoint_scene = 0xFFu;
        if (rt->checkpoint_region) *rt->checkpoint_region = 0xFFu;
    }
    if (hide_all_sprites) {
        ngpc_sprite_hide_all();
    }
#if defined(NGPNG_HAS_HUD) && NGPNG_HAS_HUD
    if (reset_hud) {
        ngpng_hud_reset(sc);
    }
#else
    (void)reset_hud;
#endif
#if defined(NGPNG_HAS_TRIGGERS) && NGPNG_HAS_TRIGGERS
    if (rt->trig_fired && rt->trig_enabled && rt->reg_prev) {
        ngpng_reset_trigger_state(rt->trig_fired, rt->trig_enabled, rt->reg_prev);
    }
#endif
    if (rt->runtime_forced_scroll && rt->runtime_scroll_paused &&
        rt->runtime_scroll_speed_x && rt->runtime_scroll_speed_y) {
        ngpng_reset_scene_scroll_state(sc,
            rt->runtime_forced_scroll,
            rt->runtime_scroll_paused,
            rt->runtime_scroll_speed_x,
            rt->runtime_scroll_speed_y);
    }
}

void ngpng_scene_runtime_place_respawn(const NgpSceneDef *sc,
    u8 cur_scene, u8 checkpoint_scene, u8 checkpoint_region,
    s16 *cam_px, s16 *cam_py, u16 *tx, u16 *ty,
    s16 *spawn_x, s16 *spawn_y)
{
    u8 region = 0xFFu;
    if (!sc || !cam_px || !cam_py || !tx || !ty || !spawn_x || !spawn_y) return;
    if (checkpoint_scene == cur_scene) {
        region = checkpoint_region;
    }
    ngpng_place_player_on_respawn(sc, region, cam_px, cam_py, spawn_x, spawn_y);
    *tx = (u16)(*cam_px >> 3);
    *ty = (u16)(*cam_py >> 3);
}

void ngpng_scene_runtime_place_spawn(const NgpSceneDef *sc,
    u8 checkpoint_region, u8 requested_spawn,
    s16 *cam_px, s16 *cam_py, u16 *tx, u16 *ty,
    s16 *spawn_x, s16 *spawn_y)
{
    s16 wp_x;
    s16 wp_y;
    if (!sc || !cam_px || !cam_py || !tx || !ty || !spawn_x || !spawn_y) return;
    ngpng_place_player_on_respawn(sc, checkpoint_region, cam_px, cam_py, spawn_x, spawn_y);
    if (requested_spawn != 0xFFu && sc->spawn_points && requested_spawn < sc->spawn_count) {
        wp_x = sc->spawn_points[requested_spawn].x;
        wp_y = sc->spawn_points[requested_spawn].y;
        *cam_px = (s16)(wp_x - (s16)80);
        *cam_py = (s16)(wp_y - (s16)76);
        ngpng_apply_camera_constraints(sc, cam_px, cam_py);
        *spawn_x = (s16)(wp_x - *cam_px);
        *spawn_y = (s16)(wp_y - *cam_py);
    }
    *tx = (u16)(*cam_px >> 3);
    *ty = (u16)(*cam_py >> 3);
}
