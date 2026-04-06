/*
 * ngpc_lut.h - Precomputed lookup tables (fast math)
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * The TLCS-900/H has no FPU and no hardware divide for large values.
 * These tables trade ROM space for zero-cost runtime math.
 *
 * All angles use the 0-255 convention (256 = full circle).
 */

#ifndef NGPC_LUT_H
#define NGPC_LUT_H

#include "ngpc_types.h"

/* ---- Angle / direction ---- */

/* Compute the angle from (0,0) to (dx,dy) in 0-255 format.
 * dx, dy: signed 8-bit deltas (-128 to 127).
 * Returns: angle 0-255 (0=right, 64=down, 128=left, 192=up).
 * Uses a 32x32 octant lookup table (256 bytes ROM). */
u8 ngpc_lut_atan2(s8 dx, s8 dy);

/* ---- Square root ---- */

/* Integer square root of a 16-bit value.
 * Returns: floor(sqrt(n)), 0-255.
 * Uses a 256-entry table for values 0-65535 via binary search. */
u8 ngpc_lut_sqrt16(u16 n);

/* ---- Distance ---- */

/* Approximate distance between two points (no sqrt).
 * Uses the alpha max + beta min approximation:
 *   dist ~= max(|dx|,|dy|) + 0.414 * min(|dx|,|dy|)
 * Max error: ~4%. Much faster than true sqrt.
 * dx, dy: signed 16-bit deltas. Returns: approximate distance. */
u16 ngpc_lut_dist(s16 dx, s16 dy);

/* ---- Division ---- */

/* Fast divide by small constants (0-255).
 * Returns: n / divisor (truncated).
 * Uses reciprocal multiplication: (n * recip[d]) >> 16.
 * Only accurate for n < 4096. */
u16 ngpc_lut_div(u16 n, u8 divisor);

#endif /* NGPC_LUT_H */
