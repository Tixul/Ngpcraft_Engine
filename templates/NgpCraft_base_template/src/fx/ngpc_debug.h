/*
 * ngpc_debug.h - CPU profiler and debug overlay
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Measures how many scanlines the game logic takes per frame using
 * the hardware raster position register (0x8009). Displays a colored
 * bar at the bottom of the screen: green = OK, yellow = tight, red = over.
 *
 * Disable for release builds with: #define NGPC_DEBUG 0
 */

#ifndef NGPC_DEBUG_H
#define NGPC_DEBUG_H

#include "ngpc_types.h"

#ifndef NGPC_DEBUG
#if NGP_PROFILE_RELEASE
#define NGPC_DEBUG 0
#elif NGP_ENABLE_PROFILER
#define NGPC_DEBUG 1
#else
#define NGPC_DEBUG 0
#endif
#endif

#if NGPC_DEBUG

/* Call at the START of your frame logic (after vsync + input update). */
void ngpc_debug_begin(void);

/* Call at the END of your frame logic (before the next vsync). */
void ngpc_debug_end(void);

/* Draw a profiler bar on the bottom row of a scroll plane.
 * plane: GFX_SCR1 or GFX_SCR2
 * pal_ok: palette for green (budget OK)
 * pal_warn: palette for yellow (> 80% budget)
 * pal_over: palette for red (overflowed into VBlank)
 * Requires 1 tile slot for the bar block. */
void ngpc_debug_draw_bar(u8 plane, u8 pal_ok, u8 pal_warn, u8 pal_over);

/* Print CPU usage as "XX%" at the given position. */
void ngpc_debug_print_pct(u8 plane, u8 pal, u8 x, u8 y);

/* Print current FPS counter (based on VBlank vs actual frames). */
void ngpc_debug_print_fps(u8 plane, u8 pal, u8 x, u8 y);

/* Raw accessors for custom display. */
u8 ngpc_debug_get_lines(void);     /* Scanlines used last frame */
u8 ngpc_debug_get_pct(void);       /* CPU usage 0-100+ (can exceed 100) */

#else /* NGPC_DEBUG == 0 */

/* All calls compile to nothing in release builds. */
#define ngpc_debug_begin()
#define ngpc_debug_end()
#define ngpc_debug_draw_bar(p, ok, w, ov)
#define ngpc_debug_print_pct(p, pal, x, y)
#define ngpc_debug_print_fps(p, pal, x, y)
#define ngpc_debug_get_lines() 0
#define ngpc_debug_get_pct()   0

#endif /* NGPC_DEBUG */

#endif /* NGPC_DEBUG_H */
