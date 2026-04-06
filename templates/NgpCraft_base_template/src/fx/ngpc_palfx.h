/*
 * ngpc_palfx.h - Palette effects (fade, cycle, flash)
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Animates palettes automatically. Call ngpc_palfx_update() once per frame.
 * Supports up to PALFX_MAX_SLOTS simultaneous effects.
 *
 * Effects:
 *   - Fade to black / fade to white / fade to any target palette
 *   - Color cycling (water, lava, rainbow)
 *   - Flash (damage hit, menu selection)
 */

#ifndef NGPC_PALFX_H
#define NGPC_PALFX_H

#include "ngpc_types.h"
#include "ngpc_gfx.h"    /* GFX_SCR1, GFX_SCR2, GFX_SPR */

/* Maximum simultaneous palette effects. */
#define PALFX_MAX_SLOTS  4

/* Effect types. */
#define PALFX_NONE    0
#define PALFX_FADE    1
#define PALFX_CYCLE   2
#define PALFX_FLASH   3

/* ---- Fade ---- */

/* Fade a palette toward a target over N frames.
 * plane: GFX_SCR1, GFX_SCR2, or GFX_SPR
 * pal_id: palette number (0-15)
 * target: array of 4 u16 RGB colors to fade toward
 * speed: frames per fade step (1 = fastest, 15 = slow)
 * Returns slot index (0..PALFX_MAX_SLOTS-1) or 0xFF if no slot free. */
u8 ngpc_palfx_fade(u8 plane, u8 pal_id, const u16 *target, u8 speed);

/* Convenience: fade to black. */
u8 ngpc_palfx_fade_to_black(u8 plane, u8 pal_id, u8 speed);

/* Convenience: fade to white. */
u8 ngpc_palfx_fade_to_white(u8 plane, u8 pal_id, u8 speed);

/* ---- Cycle ---- */

/* Cycle colors 1-3 of a palette (color 0 = transparent, untouched).
 * Rotates c1 -> c2 -> c3 -> c1 every 'speed' frames.
 * Good for water, lava, rainbow effects.
 * Returns slot index or 0xFF. */
u8 ngpc_palfx_cycle(u8 plane, u8 pal_id, u8 speed);

/* ---- Flash ---- */

/* Flash a palette to a solid color, then restore.
 * color: the flash color (all 4 entries set to this)
 * duration: total flash duration in frames
 * Returns slot index or 0xFF. */
u8 ngpc_palfx_flash(u8 plane, u8 pal_id, u16 color, u8 duration);

/* ---- Update / control ---- */

/* Call once per frame. Advances all active effects. */
void ngpc_palfx_update(void);

/* Check if a specific slot's effect is still active. */
u8 ngpc_palfx_active(u8 slot);

/* Stop a specific effect and restore the original palette. */
void ngpc_palfx_stop(u8 slot);

/* Stop all effects. */
void ngpc_palfx_stop_all(void);

#endif /* NGPC_PALFX_H */
