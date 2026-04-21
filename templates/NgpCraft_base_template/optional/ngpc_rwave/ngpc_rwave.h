#ifndef NGPC_RWAVE_H
#define NGPC_RWAVE_H

/*
 * ngpc_rwave -- Random wave director (shmup / arena / survival)
 * ==============================================================
 * Emits procedural spawn events over time, organized in difficulty tiers.
 * Each wave picks: enemy type, count, entry side, entry position.
 * One spawn is emitted every `wave_interval` frames until the wave is
 * drained; then the director waits `tier.wave_interval_fr` frames before
 * starting a new wave, cycling through tiers as waves accumulate.
 *
 * This module does NOT own enemy sprites/entities -- it only produces
 * spawn events. The caller handles drawing, movement and despawning.
 *
 * Depends on: ngpc_hw.h and ngpc_rtc.h (both in src/core, part of base
 * template). Uses an internal 16-bit xorshift RNG, self-contained.
 *
 * RAM: ~28 bytes per NgpcRWave instance.
 *
 * Installation:
 *   Copy ngpc_rwave/ into src/
 *   OBJS += src/ngpc_rwave/ngpc_rwave.rel
 *   #include "ngpc_rwave/ngpc_rwave.h"
 *
 * Typical usage:
 *
 *   static const NgpcRWaveTier tiers[] = {
 *       { 3u, 5u, 180u },  // tier 0 : warm-up
 *       { 4u, 6u, 150u },  // tier 1 : medium
 *       { 4u, 7u, 120u },  // tier 2 : harder
 *       { 5u, 8u,  90u },  // tier 3 : intense
 *   };
 *
 *   static NgpcRWave rw;
 *
 *   void game_init(void) {
 *       ngpc_rwave_init(&rw, tiers, 4, 3, 160, 152);
 *       ngpc_rwave_seed_rtc(&rw);          // non-deterministic seed
 *   }
 *
 *   void game_frame(void) {
 *       NgpcRWaveSpawn s;
 *       while (ngpc_rwave_update(&rw, &s)) {
 *           spawn_enemy(s.enemy_type, s.x, s.y,
 *                       s.vx * enemy_speed(s.enemy_type),
 *                       s.vy * enemy_speed(s.enemy_type));
 *       }
 *   }
 */

#include "ngpc_hw.h"

/* --- Side selection ---------------------------------------------------- */

#define NGPC_RWAVE_SIDE_RIGHT   0u  /* enters from right, moves left  */
#define NGPC_RWAVE_SIDE_LEFT    1u  /* enters from left,  moves right */
#define NGPC_RWAVE_SIDE_TOP     2u  /* enters from top,   moves down  */
#define NGPC_RWAVE_SIDE_BOTTOM  3u  /* enters from bottom, moves up   */

#define NGPC_RWAVE_SIDES_ALL    0x0Fu
#define NGPC_RWAVE_SIDES_HORIZ  0x03u  /* RIGHT + LEFT only */
#define NGPC_RWAVE_SIDES_VERT   0x0Cu  /* TOP + BOTTOM only */

/* --- Tier configuration (ROM) ------------------------------------------ */

typedef struct {
    u8 min_count;        /* minimum enemies per wave in this tier */
    u8 max_count;        /* maximum enemies per wave in this tier */
    u8 wave_interval_fr; /* frames to wait before starting next wave */
} NgpcRWaveTier;

/* --- Spawn event output ------------------------------------------------ */

typedef struct {
    s16 x;          /* spawn X in pixels (may be off-screen, see margin) */
    s16 y;          /* spawn Y in pixels                                 */
    s8  vx;         /* unit direction X : -1, 0, or +1                   */
    s8  vy;         /* unit direction Y : -1, 0, or +1                   */
    u8  side;       /* NGPC_RWAVE_SIDE_*                                 */
    u8  enemy_type; /* 1..type_count (picked per wave)                   */
    u8  index;      /* 0..count-1 within the current wave                */
    u16 wave_id;    /* sequence number of the current wave (1-based)     */
    u8  tier;       /* current difficulty tier                           */
} NgpcRWaveSpawn;

/* --- Director state ---------------------------------------------------- */

typedef struct {
    /* Static config (set by ngpc_rwave_init, caller may tweak after). */
    const NgpcRWaveTier *tiers;
    u8  tier_count;
    u8  type_count;           /* enemy_type picked in [1..type_count] */
    u8  screen_w;
    u8  screen_h;
    u8  offscreen_margin;     /* default 8 px                          */
    u8  axis_jitter_max;      /* default 20 px perpendicular spread    */
    u8  waves_per_tier;       /* default 10 waves                      */
    u8  intra_interval_min;   /* default 6 frames  (spawn cadence min) */
    u8  intra_interval_max;   /* default 10 frames (spawn cadence max) */
    u8  sides_mask;           /* default NGPC_RWAVE_SIDES_ALL          */

    /* Director state. */
    u8  dir_wave_timer;
    u16 wave_count;
    u8  tier;

    /* Optional hard cap on total waves emitted. 0 = infinite (default);
     * any non-zero value stops the director after `max_waves` full waves
     * have been picked (ngpc_rwave_update returns 0 from then on). */
    u16 max_waves;

    /* Current wave state. */
    u8  wave_remaining;
    u8  wave_spawn_timer;
    u8  wave_interval;
    u8  wave_spawn_index;
    u8  wave_enemy_type;
    u8  wave_side;
    s16 wave_center_x;
    s16 wave_center_y;

    /* xorshift16 state (never 0). */
    u16 rng_state;
    u8  active;               /* 0 = paused */
} NgpcRWave;

/* --- API --------------------------------------------------------------- */

/*
 * Initialize the director.
 *   tiers      : ROM table, indexed 0..tier_count-1
 *   type_count : how many enemy types the caller can spawn (1..255)
 *   screen_w/h : playfield dimensions in pixels (e.g. 160,152)
 *
 * After init, the RNG state is a fixed default. Call ngpc_rwave_seed() or
 * ngpc_rwave_seed_rtc() to get different sequences across runs.
 * All tuning fields (margin, jitter, waves_per_tier, sides_mask, etc.) are
 * writable after init if defaults don't match your game.
 */
void ngpc_rwave_init(NgpcRWave *rw,
                     const NgpcRWaveTier *tiers, u8 tier_count,
                     u8 type_count,
                     u8 screen_w, u8 screen_h);

/* Seed the RNG with a specific 16-bit value. Same seed -> same sequence.
 * seed == 0 is accepted (converted to a non-zero state internally). */
void ngpc_rwave_seed(NgpcRWave *rw, u16 seed);

/* Seed the RNG from the battery-backed RTC (second + minute + hour + day).
 * Gives a different sequence at every boot as long as >=1 second elapses
 * between reboots. Requires ngpc_rtc.h to be available. */
void ngpc_rwave_seed_rtc(NgpcRWave *rw);

/* Stir additional entropy into the current RNG state (on top of whatever
 * ngpc_rwave_seed*() left there). Call after seeding when several directors
 * share the same RTC second — otherwise each one produces the same rolls.
 * Pass a per-director unique value (e.g. the director's index). */
void ngpc_rwave_seed_stir(NgpcRWave *rw, u16 stir);

/* Pause / resume the director. A paused director emits nothing but keeps
 * its state (tier/wave_count) intact. */
void ngpc_rwave_pause(NgpcRWave *rw);
void ngpc_rwave_resume(NgpcRWave *rw);

/*
 * Advance the director by one frame and maybe emit a spawn.
 * Call once per frame. If a spawn is due, fills *out and returns 1.
 * Returns 0 if nothing to spawn this frame.
 *
 * Spawns never come in bursts -- at most one per call -- so a simple `if`
 * test is enough; no draining loop needed. (A loop still works and is
 * harmless since subsequent calls within the same frame won't advance
 * the director state until the next frame tick anyway.)
 */
u8 ngpc_rwave_update(NgpcRWave *rw, NgpcRWaveSpawn *out);

#endif /* NGPC_RWAVE_H */
