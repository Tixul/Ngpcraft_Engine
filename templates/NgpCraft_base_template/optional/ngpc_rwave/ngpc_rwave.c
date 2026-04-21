#include "ngpc_rwave.h"
#include "ngpc_rtc.h"

/* --- Internal xorshift16 RNG (period 65535, state must be non-zero) --- */

static u16 rng_next(NgpcRWave *rw)
{
    u16 s = rw->rng_state;
    s ^= (u16)(s << 7);
    s ^= (u16)(s >> 9);
    s ^= (u16)(s << 8);
    if (s == 0u) s = 0xA5A5u; /* guard against the xorshift zero attractor */
    rw->rng_state = s;
    return s;
}

static u8 rng_u8(NgpcRWave *rw)       { return (u8)(rng_next(rw) & 0xFFu); }
static u8 rng_range(NgpcRWave *rw,
                    u8 min, u8 max)
{
    u8 span = (u8)(max - min + 1u);
    return (u8)(min + (rng_u8(rw) % span));
}
static s16 rng_signed(NgpcRWave *rw, u8 max)
{
    u16 r = rng_next(rw);
    s16 mag = (s16)((r >> 1) % (u16)(max + 1u));
    return (r & 1u) ? (s16)(-mag) : mag;
}

/* --- Side picking -------------------------------------------------------- */

static u8 pick_side(NgpcRWave *rw)
{
    u8 mask = rw->sides_mask;
    u8 candidates[4];
    u8 n = 0u;
    u8 i;

    if (mask == 0u) mask = NGPC_RWAVE_SIDES_ALL;
    for (i = 0u; i < 4u; i++) {
        if (mask & (u8)(1u << i)) {
            candidates[n++] = i;
        }
    }
    /* n is at least 1 because mask != 0 after the fallback above. */
    return candidates[rng_u8(rw) % n];
}

/* --- Director ------------------------------------------------------------ */

static void pick_new_wave(NgpcRWave *rw)
{
    const NgpcRWaveTier *t;
    u8 etype, count;
    u8 jitter_extra;
    u8 tier_idx;
    s16 cx, cy;
    u8 interval;

    /* Tier index from wave progression (clamped). */
    tier_idx = (u8)(rw->wave_count / rw->waves_per_tier);
    if (tier_idx >= rw->tier_count) tier_idx = (u8)(rw->tier_count - 1u);
    rw->tier = tier_idx;
    t = &rw->tiers[tier_idx];

    /* Enemy type : 1..type_count */
    etype = (u8)(1u + (rng_u8(rw) % rw->type_count));

    /* Count : tier range + small extra jitter (0..2). */
    count = rng_range(rw, t->min_count, t->max_count);
    jitter_extra = (u8)(rng_u8(rw) % 3u);
    count = (u8)(count + jitter_extra);

    /* Safe band center, 16-px margin on both sides. */
    cx = (s16)(16u + (rng_u8(rw) % (u8)(rw->screen_w - 32u)));
    cy = (s16)(16u + (rng_u8(rw) % (u8)(rw->screen_h - 32u)));

    /* Intra-wave cadence (clamped to [1,max]). */
    if (rw->intra_interval_max < rw->intra_interval_min)
        rw->intra_interval_max = rw->intra_interval_min;
    interval = rng_range(rw, rw->intra_interval_min, rw->intra_interval_max);
    if (interval == 0u) interval = 1u;

    rw->wave_remaining    = count;
    rw->wave_enemy_type   = etype;
    rw->wave_side         = pick_side(rw);
    rw->wave_center_x     = cx;
    rw->wave_center_y     = cy;
    rw->wave_interval     = interval;
    rw->wave_spawn_timer  = 0u;
    rw->wave_spawn_index  = 0u;

    rw->wave_count++;
    rw->dir_wave_timer = t->wave_interval_fr;
}

static void fill_spawn(NgpcRWave *rw, NgpcRWaveSpawn *out)
{
    s16 jitter = rng_signed(rw, rw->axis_jitter_max);
    s16 off = (s16)rw->offscreen_margin;
    s16 spawn_x = 0, spawn_y = 0;
    s8  vx = 0, vy = 0;

    switch (rw->wave_side) {
    case NGPC_RWAVE_SIDE_LEFT:
        spawn_x = (s16)(-off);
        spawn_y = rw->wave_center_y + jitter;
        vx = 1; vy = 0;
        break;
    case NGPC_RWAVE_SIDE_TOP:
        spawn_x = rw->wave_center_x + jitter;
        spawn_y = (s16)(-off);
        vx = 0; vy = 1;
        break;
    case NGPC_RWAVE_SIDE_BOTTOM:
        spawn_x = rw->wave_center_x + jitter;
        spawn_y = (s16)(rw->screen_h + off);
        vx = 0; vy = -1;
        break;
    case NGPC_RWAVE_SIDE_RIGHT:
    default:
        spawn_x = (s16)(rw->screen_w + off);
        spawn_y = rw->wave_center_y + jitter;
        vx = -1; vy = 0;
        break;
    }

    out->x          = spawn_x;
    out->y          = spawn_y;
    out->vx         = vx;
    out->vy         = vy;
    out->side       = rw->wave_side;
    out->enemy_type = rw->wave_enemy_type;
    out->index      = rw->wave_spawn_index;
    out->wave_id    = rw->wave_count;
    out->tier       = rw->tier;
}

/* --- Public API ---------------------------------------------------------- */

void ngpc_rwave_init(NgpcRWave *rw,
                     const NgpcRWaveTier *tiers, u8 tier_count,
                     u8 type_count,
                     u8 screen_w, u8 screen_h)
{
    rw->tiers            = tiers;
    rw->tier_count       = (tier_count == 0u) ? 1u : tier_count;
    rw->type_count       = (type_count == 0u) ? 1u : type_count;
    rw->screen_w         = screen_w;
    rw->screen_h         = screen_h;

    /* Defaults tuned for a 160x152 playfield; caller may override. */
    rw->offscreen_margin = 8u;
    rw->axis_jitter_max  = 20u;
    rw->waves_per_tier   = 10u;
    rw->intra_interval_min = 6u;
    rw->intra_interval_max = 10u;
    rw->sides_mask       = NGPC_RWAVE_SIDES_ALL;

    rw->dir_wave_timer   = 0u;
    rw->wave_count       = 0u;
    rw->tier             = 0u;
    rw->max_waves        = 0u; /* 0 = infinite (default) */

    rw->wave_remaining   = 0u;
    rw->wave_spawn_timer = 0u;
    rw->wave_interval    = 8u;
    rw->wave_spawn_index = 0u;
    rw->wave_enemy_type  = 1u;
    rw->wave_side        = NGPC_RWAVE_SIDE_RIGHT;
    rw->wave_center_x    = (s16)(screen_w / 2);
    rw->wave_center_y    = (s16)(screen_h / 2);

    rw->rng_state        = 0xBEEFu; /* deterministic default seed */
    rw->active           = 1u;
}

static void rwave_warmup(NgpcRWave *rw)
{
    /* Xorshift is sensitive to low-entropy seeds: the first few outputs are
     * strongly correlated with the seed. Spin the generator a handful of
     * times so the initial rolls used by pick_new_wave are well mixed. */
    u8 k;
    for (k = 0u; k < 8u; k++) (void)rng_next(rw);
}

void ngpc_rwave_seed(NgpcRWave *rw, u16 seed)
{
    rw->rng_state = (seed == 0u) ? 0xA5A5u : seed;
    rwave_warmup(rw);
}

/* Additional per-director stir (e.g. the wave index inside a scene) so two
 * directors initialized from the same RTC second do not produce the same
 * output sequence. Callers that use the stir variant should pass a value
 * that is unique per director — a counter or wave index is sufficient. */
void ngpc_rwave_seed_stir(NgpcRWave *rw, u16 stir)
{
    rw->rng_state ^= (u16)(stir * 0x9E37u + 0x5A5Fu);
    if (rw->rng_state == 0u) rw->rng_state = 0xA5A5u;
    rwave_warmup(rw);
}

void ngpc_rwave_seed_rtc(NgpcRWave *rw)
{
    NgpcTime t;
    u16 s;
    u16 sec2, min2, hr2;

    ngpc_rtc_get(&t);
    /* BCD fields are packed as two nibbles (tens|units). The units nibble
     * changes every tick; the tens nibble changes every 10 ticks. Splitting
     * and combining both nibbles gives roughly 7 bits of entropy per second
     * instead of ~3 when the raw BCD byte is used as-is. */
    sec2 = (u16)((u16)t.second ^ (u16)((u16)t.second << 4));
    min2 = (u16)((u16)t.minute ^ (u16)((u16)t.minute << 3));
    hr2  = (u16)((u16)t.hour   ^ (u16)((u16)t.hour   << 5));
    s = sec2
      ^ (u16)(min2 << 2)
      ^ (u16)(hr2  << 7)
      ^ (u16)((u16)t.day    << 1)
      ^ (u16)((u16)t.extra  << 11);
    if (s == 0u) s = 0xA5A5u;
    rw->rng_state = s;
    rwave_warmup(rw);
}

void ngpc_rwave_pause(NgpcRWave *rw)  { rw->active = 0u; }
void ngpc_rwave_resume(NgpcRWave *rw) { rw->active = 1u; }

u8 ngpc_rwave_update(NgpcRWave *rw, NgpcRWaveSpawn *out)
{
    if (!rw->active) return 0u;

    /* Hard cap: once `max_waves` full waves have been emitted and the current
     * wave is exhausted, the director stops emitting. max_waves == 0 keeps the
     * infinite behaviour (default for roguelite-style endless spawners). */
    if (rw->max_waves != 0u
        && rw->wave_count >= rw->max_waves
        && rw->wave_remaining == 0u) {
        return 0u;
    }

    /* Waiting for next wave to start. */
    if (rw->dir_wave_timer > 0u) {
        rw->dir_wave_timer--;
        return 0u;
    }

    /* Previous wave exhausted -> pick a new one. */
    if (rw->wave_remaining == 0u) {
        pick_new_wave(rw);
        /* Fall through so the first enemy of the new wave can spawn now
         * (intra-wave timer starts at 0). */
    }

    /* Cadence gate between successive enemies of the current wave. */
    if (rw->wave_spawn_timer > 0u) {
        rw->wave_spawn_timer--;
        return 0u;
    }

    fill_spawn(rw, out);
    rw->wave_spawn_index++;
    rw->wave_remaining--;
    rw->wave_spawn_timer = rw->wave_interval;
    return 1u;
}
