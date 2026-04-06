/*
 * ngpc_soam.h - Shadow OAM double-buffer for 64 hardware sprites
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Pattern from Sonic disassembly §1.1-1.4:
 *   - Two RAM buffers: shadow_oam[64*4] + shadow_col[64]
 *   - Build the full OAM state in RAM during game logic
 *   - Push atomically to hardware (0x8800 + 0x8C00) in VBlank
 *   - No tearing: hardware is updated in one burst, not incrementally
 *
 * Difference from ngpc_sprmux:
 *   ngpc_sprmux  = true multiplexing via HBlank ISR, supports >64 sprites
 *   ngpc_soam    = clean double-buffer, max 64 sprites, zero ISR overhead
 *
 * Usage per frame:
 *   ngpc_soam_begin();                              // start of game logic
 *   ngpc_soam_put(0, x, y, tile, SPR_FRONT, pal);  // fill slots 0..N-1
 *   ngpc_soam_put(1, ...);
 *   ...
 *   // in VBlank handler:
 *   ngpc_soam_flush();                              // push shadow to hardware
 *   // or: ngpc_soam_flush_partial();               // faster if slots are dense 0..N-1
 */

#ifndef NGPC_SOAM_H
#define NGPC_SOAM_H

#include "../../src/core/ngpc_types.h"
#include "../../src/core/ngpc_hw.h"

/* Begin a new frame: reset the slot cursor.
 * Call once per frame before any ngpc_soam_put() calls. */
void ngpc_soam_begin(void);

/* Write one sprite into the shadow OAM at the given slot (0-63).
 * x, y   : screen position in pixels.
 * tile   : tile index (0-511).
 * flags  : SPR_FRONT / SPR_MIDDLE / SPR_BEHIND / SPR_HIDE + SPR_HFLIP / SPR_VFLIP.
 *          If priority bits = SPR_HIDE, defaults to SPR_FRONT (safety guard).
 * pal    : palette index (0-15).
 * Slots should be filled 0, 1, 2 ... for correct tail-clear. */
void ngpc_soam_put(u8 slot, u8 x, u8 y, u16 tile, u8 flags, u8 pal);

/* Hide a single slot (PR.C = 00).  Does not advance the slot cursor. */
void ngpc_soam_hide(u8 slot);

/* Push the shadow OAM to hardware registers 0x8800 and 0x8C00.
 * Hides tail slots (above watermark) left over from the previous frame.
 * MUST be called during VBlank (or just after) for tear-free updates. */
void ngpc_soam_flush(void);

/* Variant flush optimized for the common case "slots 0..N-1 are used".
 *
 * What it does:
 * - copies only slots [0..used-1] to HW (instead of always copying all 64)
 * - tail-clear hides previous-frame leftover slots by clearing only the HW attr byte
 *   (stride 4) for slots [used..used_prev-1]
 * - updates HW palette indices (0x8C00) for [0..used_prev-1] so no stale palette lingers
 *
 * Constraints:
 * - Intended for dense slot usage (0,1,2,...). Same assumption as the default tail-clear.
 * - MUST be called during VBlank (or just after) for tear-free updates. */
void ngpc_soam_flush_partial(void);

/* Hide all 64 hardware sprite slots immediately (direct HW write).
 * Safe to call at any time (e.g. during scene transitions). */
void ngpc_soam_hide_all(void);

/* Returns the high-water-mark: highest slot index written + 1.
 * Useful to know how many sprites were submitted this frame. */
u8 ngpc_soam_used(void);

#endif /* NGPC_SOAM_H */
