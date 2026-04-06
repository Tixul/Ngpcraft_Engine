#ifndef NGPC_ABL_H
#define NGPC_ABL_H

/*
 * ngpc_abl -- AABB list manager with bitmask results
 * ===================================================
 * Registers up to NGPC_ABL_MAX (32) rectangles with a numeric ID,
 * tests all pairs in O(n^2), and stores results as u32 bitmasks.
 *
 * Useful when multiple categories of objects need to test each other
 * without manual loops (bullets vs enemies, enemies vs player...).
 * Bitmasks allow group filtering without extra code.
 *
 * RAM:  32 x NgpcRect (192 B) + 32 x u32 masks (128 B) + u32 active (4 B)
 *     = 324 bytes
 *
 * Depends on: ngpc_aabb.h (NgpcRect, ngpc_rect_overlap)
 *
 * --------------------------------------------------------------------------
 * Installation:
 *   Same folder as ngpc_aabb:
 *   OBJS += src/ngpc_aabb/ngpc_abl.rel
 *   #include "ngpc_aabb/ngpc_abl.h"
 * --------------------------------------------------------------------------
 *
 * IDs: 0..NGPC_ABL_MAX-1 (0..31). Use named constants:
 *   #define ID_PLAYER     0
 *   #define ID_ENEMY_BASE 1   // enemies 1..5
 *   #define MASK_ENEMIES  0x3Eu  // bits 1-5
 *
 * Typical usage (frame loop):
 *   // 1. Update positions
 *   ngpc_abl_set(ID_PLAYER, px, py, 8, 8);
 *   for (i = 0; i < enemy_count; i++)
 *       ngpc_abl_set(ID_ENEMY_BASE + i, ex[i], ey[i], 8, 8);
 *
 *   // 2. Test all pairs
 *   ngpc_abl_test_all();
 *
 *   // 3. Read results
 *   if (ngpc_abl_hit_mask(ID_PLAYER) & MASK_ENEMIES) player_hit();
 *   for (i = 0; i < enemy_count; i++)
 *       if (ngpc_abl_hit(ID_ENEMY_BASE + i, ID_BULLET_BASE + i)) enemy_dead(i);
 */

#include "ngpc_aabb.h"   /* NgpcRect, ngpc_rect_overlap */

#define NGPC_ABL_MAX 32u  /* valid IDs: 0..31 */

/* ── API ─────────────────────────────────────────────────────────────── */

/* Reset all slots (active_mask = 0, all bitmasks cleared). */
void ngpc_abl_clear(void);

/* Register or update the rect for object `id` (0..31).
 * The object becomes active immediately. */
void ngpc_abl_set(u8 id, s16 x, s16 y, u8 w, u8 h);

/* Remove object `id` from the active list and clear its bitmask. */
void ngpc_abl_remove(u8 id);

/* Test all active pairs in O(n^2) and fill the bitmasks.
 * Call once per frame before reading results.
 * Each pair is tested once (symmetric: hit(A,B) == hit(B,A)). */
void ngpc_abl_test_all(void);

/* Return 1 if id_a and id_b are colliding (after ngpc_abl_test_all). */
u8  ngpc_abl_hit(u8 id_a, u8 id_b);

/* Return the bitmask of all objects colliding with `id`.
 * Bit j == 1 means object `id` overlaps object `j`.
 * Example: if (ngpc_abl_hit_mask(ID_PLAYER) & MASK_ENEMIES) { ... }
 * Returns 0 if id >= NGPC_ABL_MAX or if there are no collisions. */
u32 ngpc_abl_hit_mask(u8 id);

#endif /* NGPC_ABL_H */
