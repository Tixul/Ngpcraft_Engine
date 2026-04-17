/* ngpng_entities.h -- Entity structs, type helpers, entity management.
 * Part of the ngpng static module layer (NGPC PNG Manager).
 * Overwritten on next export -- do not hand-edit.
 */
#ifndef NGPNG_ENTITIES_H
#define NGPNG_ENTITIES_H

#include "ngpc_hw.h"       /* u8, s8, s16, u16  (found via -Isrc/core) */
#include "ngpc_sprite.h"   /* NgpcMetasprite, MsprPart, SPR_* (found via -Isrc/gfx) */
#include "ngpng_engine.h"  /* ngpng_apply_camera_constraints, ngpng_update_plane_scroll
                              (found in same ngpng/ dir) */

/* ---- Role constants ---- */
#ifndef NGPNG_ROLE_PROP
#define NGPNG_ROLE_PROP     0
#define NGPNG_ROLE_PLAYER   1
#define NGPNG_ROLE_ENEMY    2
#define NGPNG_ROLE_ITEM     3
#define NGPNG_ROLE_NPC      4
#define NGPNG_ROLE_TRIGGER  5
#define NGPNG_ROLE_PLATFORM 6
#define NGPNG_ROLE_BLOCK    7
#endif

/* ---- Entity flag constants ---- */
#ifndef NGPNG_ENT_FLAG_CLAMP_MAP
#define NGPNG_ENT_FLAG_CLAMP_MAP        1u
#define NGPNG_ENT_FLAG_ALLOW_LEDGE_FALL 2u
#define NGPNG_ENT_FLAG_RESPAWN          4u  /* world entity respawns after leaving activation radius */
#endif

/* ---- Behavior codes ---- */
#ifndef NGPNG_BEHAVIOR_PATROL
#define NGPNG_BEHAVIOR_PATROL 0
#define NGPNG_BEHAVIOR_CHASE  1
#define NGPNG_BEHAVIOR_FIXED  2
#define NGPNG_BEHAVIOR_RANDOM 3
#define NGPNG_BEHAVIOR_FLEE   4
#endif

/* ---- Animation state codes ---- */
#ifndef NGPNG_ANIM_IDLE
#define NGPNG_ANIM_IDLE  0u
#define NGPNG_ANIM_WALK  1u
#define NGPNG_ANIM_JUMP  2u
#define NGPNG_ANIM_FALL  3u
#define NGPNG_ANIM_DEATH 4u
#endif

/* ---- World entity activation system ---- */
#ifndef NGPNG_WORLD_ACTIVATION
#define NGPNG_WORLD_ACTIVATION 0
#endif
#ifndef NGPNG_MAX_WORLD_ENTITIES
#define NGPNG_MAX_WORLD_ENTITIES 32u
#endif
#ifndef NGPNG_ACTIVATION_RADIUS_TILES
#define NGPNG_ACTIVATION_RADIUS_TILES 8u
#endif
/* Activation border in pixels added to each side of the screen rect */
#define NGPNG_ACTIVATION_RADIUS_PX ((s16)((s16)NGPNG_ACTIVATION_RADIUS_TILES * 8))

/* World entity lifecycle states */
#define NGPNG_WE_ALIVE     0u
#define NGPNG_WE_DEAD      1u
#define NGPNG_WE_COLLECTED 2u

/* World entity flags (stored in NgpngWorldEnt.flags) */
#define NGPNG_WE_FLAG_RESPAWN 0x01u  /* respawn after zone re-entry if killed */

typedef struct {
    s16 world_x;     /* initial world X (pixels) */
    s16 world_y;     /* initial world Y (pixels) */
    u8  type;        /* entity type index */
    u8  role;        /* NGPNG_ROLE_xxx */
    u8  data;        /* entity-specific param */
    u8  ent_idx;     /* index into sc->entities[] for spawn params */
    u8  state;       /* NGPNG_WE_ALIVE / DEAD / COLLECTED */
    u8  active_idx;  /* pool slot index, 0xFF = inactive */
    u8  flags;       /* NGPNG_WE_FLAG_xxx */
    u8  _pad;
} NgpngWorldEnt;

#if NGPNG_WORLD_ACTIVATION
extern NgpngWorldEnt g_ngpng_world_ents[NGPNG_MAX_WORLD_ENTITIES];
extern u8            g_ngpng_world_ent_count;
#endif

/* ---- Structs (gated per feature) ---- */

#if NGPNG_HAS_ENEMY
typedef struct NgpngEnemy {
    u8  active;
    u8  type;
    u8  hp;
    u8  anim;
    u8  data;
    u8  path_idx;
    u8  path_step;
    u8  fire_cd;
    u8  last_frame;
    u8  last_flags;
    u8  pal;
    u8  flags;
    u8  face_hflip;
    s8  hb_x;
    s8  hb_y;
    u8  hb_w;
    u8  hb_h;
    s8  body_x;
    s8  body_y;
    u8  body_w;
    u8  body_h;
    s8  atk_hb_x;
    s8  atk_hb_y;
    u8  atk_hb_w;
    u8  atk_hb_h;
    u8  damage;
    s8  atk_kb_x;
    s8  atk_kb_y;
    u8  score;
    u8  ent_flags;
    u8  visible;
    u8  last_used_parts;
    s16 world_x;
    s16 world_y;
    s16 ox;
    s16 oy;
    s16 last_sx;
    s16 last_sy;
    u16 last_tile;
    s8  vx;
    s8  vy;
    u8  on_ground;
    u8  gravity;
    u8  behavior;
    /* OPT-2A-BOUNDS: patrol world-X bounds. Set at spawn for BEHAVIOR_PATROL enemies.
     * patrol_max > patrol_min → use direct X comparison instead of should_turn_platformer.
     * patrol_max == patrol_min (0,0) → no bounds, fall back to tile detection. */
    s16 patrol_min;
    s16 patrol_max;
    /* Anim state cache: refreshed from ROM only on state change (0xFF = stale).
     * Eliminates ngpng_type_anim_{start/count/speed} ROM lookups every frame. */
    u8  cached_anim_st;    /* last anim state — 0xFF forces refresh on first call */
    u8  cached_anim_start; /* frame index offset for cached_anim_st */
    u8  cached_anim_count; /* frame count for cached_anim_st */
    u8  cached_anim_spd;   /* frames-per-tick speed (same for all states of a type) */
    /* Draw cache: updated by ngpng_enemies_update, consumed by ngpng_enemies_draw */
    u8                    cached_anim_frame; /* 0xFF = stale */
    const NgpcMetasprite *cached_def;
    s8                    cached_rox;
    s8                    cached_roy;
} NgpngEnemy;
#endif /* NGPNG_HAS_ENEMY */

#if NGPNG_HAS_FX
typedef struct NgpngFx {
    u8  active;
    u8  visible;
    u8  type;
    u8  frame_base;
    u8  frame_count;
    u8  anim;
    u8  last_frame;
    u8  pal;
    u8  flags;
    s16 world_x;
    s16 world_y;
    s16 ox;
    s16 oy;
    s16 last_sx;
    s16 last_sy;
    u16 last_tile;
} NgpngFx;
#endif /* NGPNG_HAS_FX */

#if NGPNG_HAS_PROP_ACTOR
typedef struct NgpngPropActor {
    u8  active;
    u8  visible;
    u8  role;
    u8  type;
    u8  src_idx;
    u8  anim;
    u8  anim_state;
    u8  moving;
    u8  paused;
    u8  path_idx;
    u8  path_step;
    u8  data;
    u8  state;
    u8  bump_timer;
    u8  ent_flags;
    s8  hb_x;
    s8  hb_y;
    u8  hb_w;
    u8  hb_h;
    s8  body_x;
    s8  body_y;
    u8  body_w;
    u8  body_h;
    s16 world_x;
    s16 world_y;
    s16 prev_world_x;
    s16 prev_world_y;
    s16 home_y;
    s16 target_x;
    s16 target_y;
    u8  draw_visible;
    u8  last_draw_frame;
    u8  last_draw_flags;
    u8  last_used_parts;
    u8  last_draw_spr;
    s16 last_draw_sx;
    s16 last_draw_sy;
    /* Draw cache: updated by ngpng_props_update, consumed by ngpng_props_draw */
    /* OPT-ANIM-CACHE: anim start/count/speed cached per prop, refreshed only on anim_state change.
     * Every other frame: pure RAM arithmetic, 0 ROM lookups. */
    u8  cached_anim_st;    /* last anim_state — 0xFF forces refresh on first call */
    u8  cached_anim_start; /* frame index offset for cached_anim_st */
    u8  cached_anim_count; /* frame count for cached_anim_st */
    u8  cached_anim_spd;   /* frames-per-tick speed */
    u8                    cached_anim_frame; /* 0xFF = stale */
    const NgpcMetasprite *cached_def;
    s8                    cached_rox;
    s8                    cached_roy;
} NgpngPropActor;
#endif /* NGPNG_HAS_PROP_ACTOR */

/* ---- Shared type / anim helpers ---- */
#if NGPNG_HAS_ENEMY || NGPNG_HAS_PROP_ACTOR || NGPNG_HAS_PLAYER

u8  ngpng_entity_role(const NgpSceneDef *sc, u8 type);
u8  ngpng_type_u8(const u8 *arr, u8 count, u8 type, u8 fallback);
s8  ngpng_type_s8(const s8 *arr, u8 count, u8 type, s8 fallback);
s8  ngpng_type_attack_s8(const s8 *arr, const s8 *fallback_arr, u8 count, u8 type, s8 fallback);
u8  ngpng_type_attack_u8(const u8 *arr, const u8 *fallback_arr, u8 count, u8 type, u8 fallback);
u8  ngpng_type_attack_damage_u8(const u8 *arr, const u8 *fallback_arr, u8 count, u8 type, u8 fallback);
u8  ngpng_type_anim_start(const NgpSceneDef *sc, u8 type, u8 state);
u8  ngpng_type_anim_count(const NgpSceneDef *sc, u8 type, u8 state);
u8  ngpng_type_anim_speed(const NgpSceneDef *sc, u8 type);
u8  ngpng_type_anim_frame_local(const NgpSceneDef *sc, u8 type, u8 state, u8 tick);
u8  ngpng_type_anim_frame_abs(const NgpSceneDef *sc, u8 type, u8 state, u8 tick);
/* ngpng_add_s8_clamped / ngpng_clamp_s8_range: static in entities.c (not exported);
 * the generated file emits its own static copies for shooting/player-physics. */
u8  ngpng_attack_box_count(const NgpSceneDef *sc, u8 type);
u8  ngpng_attack_box_start(const NgpSceneDef *sc, u8 type);
u8  ngpng_attack_window_active(u8 anim_frame, u8 active_start, u8 active_len, u8 active_anim_state, u8 cur_anim_state);
u8  ngpng_find_first_type_by_role(const NgpSceneDef *sc, u8 role);
/* Use a short exported symbol for CC900/TULINK compatibility; map the longer
 * generated name onto it via macro alias. */
u8  ngpng_first_flags_by_role(const NgpSceneDef *sc, u8 role);
#define ngpng_find_first_entity_flags_by_role ngpng_first_flags_by_role
u8  ngpng_count_types_by_role(const NgpSceneDef *sc, u8 role);
u8  ngpng_find_nth_type_by_role(const NgpSceneDef *sc, u8 role, u8 nth);
void ngpng_player_apply_form(const NgpSceneDef *sc, u8 form_idx,
    u8 *player_type, s8 *player_hb_x, s8 *player_hb_y, u8 *player_hb_w, u8 *player_hb_h,
    s8 *player_body_x, s8 *player_body_y, u8 *player_body_w, u8 *player_body_h,
    s8 *player_render_off_x, s8 *player_render_off_y, u8 *player_frame_w, u8 *player_frame_h,
    u8 *player_hp, u8 *player_hp_max, u8 reset_hp);
u8  ngpng_rects_overlap(s16 ax, s16 ay, u8 aw, u8 ah, s16 bx, s16 by, u8 bw, u8 bh);
void ngpng_clamp_world_rect(const NgpSceneDef *sc, s16 *wx, s16 *wy, u8 w, u8 h);
s8  ngpng_step_toward(s16 cur, s16 dst, s8 step);
void ngpng_find_player_spawn(const NgpSceneDef *sc, s16 cam_px, s16 cam_py, s16 *sx, s16 *sy);
void ngpng_place_player_on_respawn(const NgpSceneDef *sc, u8 checkpoint_region,
    s16 *cam_px, s16 *cam_py, s16 *sx, s16 *sy);

#endif /* NGPNG_HAS_ENEMY || NGPNG_HAS_PROP_ACTOR || NGPNG_HAS_PLAYER */

/* ---- Sprite draw helpers ---- */
#if NGPNG_HAS_ENEMY || NGPNG_HAS_FX || NGPNG_HAS_PROP_ACTOR

u8   ngpng_sprite_mspr_draw(u8 spr_start, s16 x, s16 y, const NgpcMetasprite *def, u8 flags);
void ngpng_sprite_hide_range(u8 start, u8 count);
void ngpng_player_layer_sync(u8 spr_start, u8 slot_count, s16 x, s16 y, u8 frame_idx,
    const MsprAnimFrame *anim, u8 anim_count, u8 render_flags,
    u8 *visible, s16 *last_x, s16 *last_y, u8 *last_frame, u8 *last_flags);
u8   ngpng_entity_sprite_info(const NgpSceneDef *sc, u8 type, u8 frame_idx,
    u16 *tile, u8 *pal, u8 *flags, s16 *ox, s16 *oy);

#endif /* NGPNG_HAS_ENEMY || NGPNG_HAS_FX || NGPNG_HAS_PROP_ACTOR */

/* ---- Enemy management ---- */
#if NGPNG_HAS_ENEMY

void ngpng_enemy_hide(NgpngEnemy *enemies, u8 idx);
void ngpng_enemies_clear(NgpngEnemy *enemies, u8 *active_count, u8 *alloc_idx);
void ngpng_enemy_kill(NgpngEnemy *enemies, u8 *active_count, u8 idx);
void ngpng_enemy_spawn(const NgpSceneDef *sc, NgpngEnemy *enemies, u8 *active_count, u8 *alloc_idx,
    const NgpngEnt *src, u8 ent_idx, u8 assigned_path_idx, u8 assigned_behavior, u8 assigned_flags);
/* Wave sequencing is driven by NgpcWaveSeq in the generated main.c.
 * The runtime only handles entity spawning; ngpc_wave_update() drives timing. */
void ngpng_enemies_reset_scene(const NgpSceneDef *sc, NgpngEnemy *enemies,
    u8 *enemy_active_count, u8 *enemy_alloc_idx);
void ngpng_enemies_force_jump_by_type(NgpngEnemy *enemies, u8 type);
/* World entity activation system (NGPNG_WORLD_ACTIVATION=1) */
void ngpng_world_init(const NgpSceneDef *sc);
void ngpng_world_tick(const NgpSceneDef *sc,
    NgpngEnemy *enemies, u8 *enemy_active_count, u8 *enemy_alloc_idx,
    s16 cam_px, s16 cam_py);
void ngpng_world_on_enemy_killed(u8 pool_idx);
void ngpng_enemies_update(const NgpSceneDef *sc,
    const u8 *_tc, u16 _mw, u16 _mh,
    NgpngEnemy *enemies,
    u8 *enemy_active_count, s16 cam_px, s16 cam_py, s16 player_wx, s16 player_wy,
    u8 frame_timer);
void ngpng_enemy_sync(const NgpSceneDef *sc, NgpngEnemy *enemies, u8 idx,
    s16 cam_px, s16 cam_py, u8 frame_idx);
void ngpng_enemies_draw(const NgpSceneDef *sc, NgpngEnemy *enemies, s16 cam_px, s16 cam_py);

#endif /* NGPNG_HAS_ENEMY */

/* ---- Fx management ---- */
#if NGPNG_HAS_FX

void ngpng_fx_hide(NgpngFx *fx, u8 idx);
void ngpng_fx_clear(NgpngFx *fx, u8 *active_count, u8 *alloc_idx);
void ngpng_fx_kill(NgpngFx *fx, u8 *active_count, u8 idx);
void ngpng_fx_spawn(NgpngFx *fx, u8 *active_count, u8 *alloc_idx,
    u8 fx_type, s16 world_x, s16 world_y);
void ngpng_fx_spawn_anim_state(const NgpSceneDef *sc, NgpngFx *fx, u8 *active_count, u8 *alloc_idx,
    u8 fx_type, u8 anim_state, s16 world_x, s16 world_y);
void ngpng_fx_update(const NgpSceneDef *sc, NgpngFx *fx, u8 *fx_active_count,
    s16 cam_px, s16 cam_py);
void ngpng_fx_sync(const NgpSceneDef *sc, NgpngFx *fx, u8 idx, s16 cam_px, s16 cam_py);

#endif /* NGPNG_HAS_FX */

/* ---- Prop actor management ---- */
#if NGPNG_HAS_PROP_ACTOR

void ngpng_props_clear(NgpngPropActor *props);
u8   ngpng_prop_find_by_src(const NgpngPropActor *props, u8 prop_count, u8 src_idx);
void ngpng_props_set_anim_by_type(NgpngPropActor *props, u8 prop_count, u8 type, u8 anim_state);
void ngpng_props_reset_scene(const NgpSceneDef *sc, NgpngPropActor *props, u8 *prop_count);
void ngpng_props_apply_path_step(const NgpSceneDef *sc, NgpngPropActor *prop);
void ngpng_props_update(const NgpSceneDef *sc, NgpngPropActor *props, u8 prop_count, s16 cam_px, s16 cam_py);
void ngpng_player_apply_platform_delta(const NgpngPropActor *props, u8 prop_count,
    u8 rider_idx, s16 *px, s16 *py);
u8   ngpng_player_resolve_platforms(const NgpngPropActor *props, u8 prop_count,
    s16 prev_world_x, s16 prev_world_y, s16 cam_px, s16 cam_py,
    s16 *px, s16 *py, s8 *vy, u8 *on_ground, u8 *coyote,
    s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h);
void ngpng_player_collect_items(const NgpSceneDef *sc, NgpngPropActor *props, u8 prop_count,
    s16 player_world_x, s16 player_world_y, s8 player_hb_x, s8 player_hb_y,
    u8 player_hb_w, u8 player_hb_h, u16 *score, u8 *hp, u8 hp_max, u16 *collectible_count);
void ngpng_player_collide_damage_props(const NgpSceneDef *sc, NgpngPropActor *props, u8 prop_count,
    s16 player_world_x, s16 player_world_y, s8 *player_vx, s8 *player_vy,
    s8 player_hb_x, s8 player_hb_y, u8 player_hb_w, u8 player_hb_h,
    u8 *hp, u8 *invul);
void ngpng_player_collide_solid_props(const NgpngPropActor *props, u8 prop_count,
    s16 cam_px, s16 cam_py,
    s16 *px, s16 *py, s8 *vx, s8 *vy,
    s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h);
void ngpng_player_bump_blocks(const NgpSceneDef *sc, NgpngPropActor *props, u8 prop_count,
    s16 prev_world_x, s16 prev_world_y, s16 cam_px, s16 cam_py,
    s16 *px, s16 *py, s8 *vy, s8 hb_x, s8 hb_y, u8 hb_w, u8 hb_h,
    u16 *score, u8 *hp, u8 hp_max, u16 *collectible_count);
void ngpng_props_draw(const NgpSceneDef *sc, NgpngPropActor *props, u8 prop_count,
    s16 cam_px, s16 cam_py);

#endif /* NGPNG_HAS_PROP_ACTOR */

/* ---- Combat / player-enemy collision ---- */
#if NGPNG_HAS_COMBAT

void ngpng_player_collide_enemies(const NgpSceneDef *sc, NgpngEnemy *enemies,
    u8 *enemy_active_count, s16 px, s16 *py, s8 *player_vx, s8 *player_vy,
    s8 player_hb_x, s8 player_hb_y, u8 player_hb_w, u8 player_hb_h,
    s16 cam_px, s16 cam_py, u8 *hp, u8 *invul, u16 *score, u8 explosion_type,
    NgpngFx *fx, u8 *fx_active_count, u8 *fx_alloc_idx);

#endif /* NGPNG_HAS_COMBAT */

/* Sprite priority used for all entities. Set to SPR_MIDDLE during dialogue
 * so entities pass behind SCR2 (dialog overlay). Reset to SPR_FRONT after. */
extern u8 g_ngpng_entity_prio;

#endif /* NGPNG_ENTITIES_H */
