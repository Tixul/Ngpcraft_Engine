/*
 * ngpc_math.h - Math utilities (sin/cos, RNG, 32-bit multiply)
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * The TLCS-900/H has no native 32-bit multiply or FPU.
 * Sin/Cos use a 256-entry lookup table (angle 0-255 = 0-360 degrees).
 */

#ifndef NGPC_MATH_H
#define NGPC_MATH_H

#include "ngpc_types.h"

/* Sine lookup: angle 0-255 maps to full circle.
 * Returns -127 to +127 (fixed-point 8-bit). */
s8 ngpc_sin(u8 angle);

/* Cosine lookup (same range as sin). */
s8 ngpc_cos(u8 angle);

/* Seed the PRNG. Call after user input (e.g. title screen)
 * to get unpredictable values from VBCounter. */
void ngpc_rng_seed(void);

/* Returns a pseudo-random number from 0 to max (inclusive).
 * max must be < 32767. Uses 32-bit LCG. */
u16 ngpc_random(u16 max);

/* 32-bit signed multiply (needed because T900 lacks mul32).
 * Implemented via 16x16 partial products. */
s32 ngpc_mul32(s32 a, s32 b);

/* ---- Quick random (table-based) ---- */

/* Fast random: reads sequentially from a pre-shuffled 256-byte table.
 * Zero CPU cost (just a table lookup + index increment).
 * Lower quality than LCG but perfect for non-critical uses
 * (particle offsets, screen shake, tile variation, etc.). */
u8 ngpc_qrandom(void);

/* Reshuffle the QRandom table using the LCG (call once at start). */
void ngpc_qrandom_init(void);

#endif /* NGPC_MATH_H */
