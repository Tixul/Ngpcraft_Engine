/*
 * ngpc_winani.h - Animated window/viewport transition
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Pattern from Pocket Tennis disassembly §4:
 *   Pocket Tennis animates WIN_X/Y/W/H (0x8002..0x8005) for a
 *   center-outward reveal / center-inward close transition.
 *   Constants confirmed in disassembly: 0xA0=160px, 0x98=152px,
 *   center = (80, 76).
 *
 * The K2GE window defines the VISIBLE area of the display.
 * WIN_X/Y = top-left origin, WIN_W/H = size.
 * Full screen = X:0, Y:0, W:160, H:152.
 * Zero size    = X:80, Y:76, W:0, H:0 (nothing visible).
 *
 * Note on WIN_W/H encoding: Pocket Tennis uses 0xA0 (=160) for full-width.
 * Sonic uses 0x9F (=159). Hardware behavior not confirmed by test yet.
 * This implementation uses the Pocket Tennis values (160/152).
 * If visuals are off by 1px on your hardware, define WINANI_SIZE_MINUS1.
 *
 * Usage:
 *   ngpc_win_init();           // set window to full screen (open)
 *   ngpc_win_close(4);         // start closing (e.g. at scene end)
 *   // in VBlank:
 *   if (ngpc_win_update()) { } // returns 1 when animation is done
 *   ngpc_win_open(4);          // start opening (e.g. at scene start)
 */

#ifndef NGPC_WINANI_H
#define NGPC_WINANI_H

#include "../../src/core/ngpc_types.h"

/* Initialize: set window to full screen (no animation). */
void ngpc_win_init(void);

/* Set to fully open immediately (no animation). */
void ngpc_win_set_full(void);

/* Set to fully closed immediately (nothing visible). */
void ngpc_win_set_closed(void);

/* Start opening animation from current state toward full screen.
 * speed: pixels expanded per frame on each side (1-40). */
void ngpc_win_open(u8 speed);

/* Start closing animation from current state toward center.
 * speed: pixels contracted per frame on each side (1-40). */
void ngpc_win_close(u8 speed);

/* Update animation state. Call once per VBlank.
 * Writes WIN_X/Y/W/H hardware registers.
 * Returns 1 when the animation has reached its target, 0 otherwise.
 * Safe to call even when idle (no-op, returns 1). */
u8 ngpc_win_update(void);

/* Returns 1 if currently animating (open or close in progress). */
u8 ngpc_win_busy(void);

#endif /* NGPC_WINANI_H */
