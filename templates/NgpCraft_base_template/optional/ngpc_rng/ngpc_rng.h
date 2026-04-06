#ifndef NGPC_RNG_H
#define NGPC_RNG_H

/*
 * ngpc_rng -- Deterministic pseudo-random number generator
 * =========================================================
 * xorshift32 algorithm (period 2^32 - 1, no multiplication).
 * Each NgpcRng instance has its own state -- reproducible results.
 *
 * Difference from ngpc_math.c (ngpc_random):
 *   ngpc_random()  : shared global state, not reproducible across sessions
 *   NgpcRng        : explicit per-instance state, controlled seed
 *
 * xorshift32 advantage on TLCS-900/H:
 *   No multiplication -> fast on the NGPC CPU.
 *   Ideal for procedural dungeons, loot, AI, enemy placement.
 *
 * ---------------------------------------------------------------------------
 * Installation:
 *   Copy ngpc_rng/ into src/
 *   Add  OBJS += src/ngpc_rng/ngpc_rng.rel  to the Makefile
 *   #include "ngpc_rng/ngpc_rng.h"
 * ---------------------------------------------------------------------------
 *
 * Typical usage:
 *
 *   NgpcRng rng;
 *   ngpc_rng_init(&rng, 0x1234);          // fixed seed -> same dungeon
 *   ngpc_rng_init_vbl(&rng);              // hardware timer seed -> random
 *
 *   u8 d6    = ngpc_rng_range(&rng, 1, 6); // six-sided die [1..6]
 *   if (ngpc_rng_chance(&rng, 25)) { }     // 25% chance
 *   s8 jitter = ngpc_rng_signed(&rng, 3);  // [-3..+3]
 *   ngpc_rng_shuffle(&rng, arr, 4);        // Fisher-Yates on 4 elements
 */

#include "ngpc_hw.h"  /* u8, u16, u32, s8 */

/* ── State structure ──────────────────────────────────────────────────── */

typedef struct {
    u32 state; /* xorshift32 internal state -- must never be 0 */
} NgpcRng;

/* ── Initialization ──────────────────────────────────────────────────── */

/*
 * Initialize the RNG with a 16-bit seed.
 * Same seed -> same sequence -> reproducible dungeon.
 * seed = 0 is accepted (automatically converted to a non-zero state).
 */
void ngpc_rng_init(NgpcRng *rng, u16 seed);

/*
 * Initialize the RNG from the NGPC hardware timer counter (TVAL0, 0x006D).
 * Non-reproducible -- use for non-deterministic gameplay.
 * Prefer calling after a few frames (timer is more entropic).
 */
void ngpc_rng_init_vbl(NgpcRng *rng);

/* ── Number generation ───────────────────────────────────────────────── */

/*
 * Generate the next 16-bit integer in [0..65535].
 * Advances the internal state by one xorshift32 step.
 */
u16 ngpc_rng_next(NgpcRng *rng);

/*
 * Generate a random byte in [0..255].
 */
u8 ngpc_rng_u8(NgpcRng *rng);

/*
 * Generate an integer in the closed interval [min..max].
 * Precondition: max >= min and (max - min) <= 254.
 * Uniform distribution modulo (max-min+1).
 */
u8 ngpc_rng_range(NgpcRng *rng, u8 min, u8 max);

/*
 * Return 1 with probability pct/100, 0 otherwise.
 * pct = 0    -> always 0
 * pct >= 100 -> always 1
 * Examples: pct=25 -> 25% chance, pct=50 -> coin flip.
 */
u8 ngpc_rng_chance(NgpcRng *rng, u8 pct);

/*
 * Generate a signed integer in [-range..+range].
 * Useful for speed or position jitter.
 * range: recommended 0..63 (avoids s8 overflow).
 */
s8 ngpc_rng_signed(NgpcRng *rng, u8 range);

/* ── Utilities ───────────────────────────────────────────────────────── */

/*
 * Shuffle a byte array in-place (Fisher-Yates).
 * arr : pointer to the array
 * n   : number of elements (max 255)
 * Same rng + same seed -> same permutation.
 */
void ngpc_rng_shuffle(NgpcRng *rng, u8 *arr, u8 n);

/*
 * Randomly select an active bit from a 16-bit mask.
 * Useful for picking a free direction, slot, etc.
 * Returns the index of the selected bit (0..15).
 * If mask == 0, returns 0 (degenerate case -- check before calling).
 */
u8 ngpc_rng_pick_mask(NgpcRng *rng, u16 mask);

#endif /* NGPC_RNG_H */
