/* ngpng_scene_runtime.h -- Scene enter/reset helpers.
 * Part of the ngpng static module layer (NGPC PNG Manager).
 * Overwritten on next export -- do not hand-edit.
 */
#ifndef NGPNG_SCENE_RUNTIME_H
#define NGPNG_SCENE_RUNTIME_H

#include "ngpng_entities.h"
#include "ngpng_triggers.h"
#include "ngpng_hud.h"

/* Forward declarations so pointer fields compile regardless of feature flags.
 * Full struct definitions are in ngpng_entities.h, gated by NGPNG_HAS_* flags. */
struct NgpngEnemy;
struct NgpngFx;
struct NgpngPropActor;

typedef struct NgpngSceneRuntimeState {
    struct NgpngEnemy     *enemies;
    u8             *enemy_active_count;
    u8             *enemy_alloc_idx;
    struct NgpngFx        *fx;
    u8             *fx_active_count;
    u8             *fx_alloc_idx;
    struct NgpngPropActor *props;
    u8             *prop_count;
    u8             *player_form;
    u8             *player_form_mode;
    u8             *player_form_count;
    u8             *player_ent_flags;
    u8             *player_type;
    s8             *player_hb_x;
    s8             *player_hb_y;
    u8             *player_hb_w;
    u8             *player_hb_h;
    s8             *player_body_x;
    s8             *player_body_y;
    u8             *player_body_w;
    u8             *player_body_h;
    s8             *player_render_off_x;
    s8             *player_render_off_y;
    u8             *player_frame_w;
    u8             *player_frame_h;
    u8             *player_hp;
    u8             *player_hp_max;
    u8             *explosion_type;
    u8             *player_bullet_type;
    u16            *player_bullet_tile;
    u8             *player_bullet_pal;
    u8             *player_bullet_flags;
    s8             *player_bullet_hb_x;
    s8             *player_bullet_hb_y;
    u8             *player_bullet_hb_w;
    u8             *player_bullet_hb_h;
    u8             *player_bullet_damage;
    s8             *player_bullet_kb_x;
    s8             *player_bullet_kb_y;
    s16            *player_bullet_ox;
    s16            *player_bullet_oy;
    u8             *player_bullet_ready;
    u8             *player_invul;
    u8             *game_over;
    u8             *stage_clear;
    u8             *lives;
    u8             *continues_left;
    u8             *respawn_timer;
    u8             *fire_cd;
    u8             *player_platform;
    u16            *collectible_count;
    u8             *checkpoint_scene;
    u8             *checkpoint_region;
    u8             *trig_fired;
    u8             *trig_enabled;
    u8             *reg_prev;
    u8             *runtime_forced_scroll;
    u8             *runtime_scroll_paused;
    s16            *runtime_scroll_speed_x;
    s16            *runtime_scroll_speed_y;
} NgpngSceneRuntimeState;

#define NGPNG_SCENE_RT_LIVES_KEEP     0u
#define NGPNG_SCENE_RT_LIVES_START    1u
#define NGPNG_SCENE_RT_LIVES_CONTINUE 2u

void ngpng_scene_runtime_enter_view(const NgpSceneDef *sc, u8 scene_idx,
    s16 *cam_px, s16 *cam_py, u16 *tx, u16 *ty);

void ngpng_scene_runtime_full_reset(const NgpSceneDef *sc,
    NgpngSceneRuntimeState *rt,
    u8 lives_mode, u8 reset_continues,
    u8 reset_checkpoints, u8 hide_all_sprites, u8 reset_hud);

void ngpng_scene_runtime_place_respawn(const NgpSceneDef *sc,
    u8 cur_scene, u8 checkpoint_scene, u8 checkpoint_region,
    s16 *cam_px, s16 *cam_py, u16 *tx, u16 *ty,
    s16 *spawn_x, s16 *spawn_y);

void ngpng_scene_runtime_place_spawn(const NgpSceneDef *sc,
    u8 checkpoint_region, u8 requested_spawn,
    s16 *cam_px, s16 *cam_py, u16 *tx, u16 *ty,
    s16 *spawn_x, s16 *spawn_y);

#endif /* NGPNG_SCENE_RUNTIME_H */
