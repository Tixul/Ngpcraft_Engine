/*
 * ngpc_raster.h - HBlank raster effects (scanline tricks)
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Changes video registers mid-frame using the Timer 0 HBlank interrupt.
 * The K2GE generates 152 HBlank interrupts per frame (one per scanline).
 * Registers like scroll offset and palette take effect immediately on the
 * next scanline, enabling effects impossible with per-frame updates alone.
 *
 * Effects possible:
 *   - Parallax scrolling (different scroll speed per band)
 *   - Palette swap per scanline (> 146 colors on screen)
 *   - Screen split (HUD on top, game on bottom)
 *   - Wave/distortion (variable scroll per line)
 *   - Gradient background
 *
 * WARNING: the ISR must be extremely fast (~5 us per scanline at 6 MHz).
 * Only write 1-2 registers per HBlank. Heavy operations will cause glitches.
 *
 * Usage:
 *   1. Call ngpc_raster_init() once
 *   2. Fill a scroll table with ngpc_raster_set_scroll_table()
 *      OR register per-line callbacks with ngpc_raster_set_callback()
 *   3. Effects run automatically via the HBlank ISR
 *   4. Call ngpc_raster_disable() to stop
 */

#ifndef NGPC_RASTER_H
#define NGPC_RASTER_H

#include "ngpc_types.h"
#include "ngpc_gfx.h"    /* GFX_SCR1, GFX_SCR2 */

/* Maximum number of per-line callbacks. */
#define RASTER_MAX_CB   8

/* Raster callback: called at a specific scanline. */
typedef void (*RasterCallback)(u8 line);

/* Initialize the raster system (installs Timer 0 HBlank ISR).
 * Must be called after ngpc_init(). */
void ngpc_raster_init(void);

/* Disable raster effects (removes HBlank ISR). */
void ngpc_raster_disable(void);

/* ---- Scroll table mode ---- */

/* Set a per-scanline scroll offset table for a plane.
 * plane: GFX_SCR1 or GFX_SCR2
 * table_x: array of 152 u8 X scroll offsets (one per scanline), or NULL
 * table_y: array of 152 u8 Y scroll offsets, or NULL
 * If a table is NULL, that axis is not modified by the raster ISR. */
void ngpc_raster_set_scroll_table(u8 plane, const u8 *table_x, const u8 *table_y);

/* Clear scroll tables (stop per-line scrolling). */
void ngpc_raster_clear_scroll(void);

/* ---- Callback mode ---- */

/* Register a callback to be called at a specific scanline.
 * line: scanline number (0-151)
 * cb: function to call (must be VERY fast, ~10 instructions max)
 * Returns slot index or 0xFF if no slot free. */
u8 ngpc_raster_set_callback(u8 line, RasterCallback cb);

/* Remove all callbacks. */
void ngpc_raster_clear_callbacks(void);

/* ---- Convenience: parallax ---- */

/* Setup simple parallax scrolling with N horizontal bands.
 * bands: array of band definitions (top_line, scroll_x multiplier).
 * count: number of bands (max 8).
 * base_x: the base scroll value (your camera X position).
 * Multipliers are 8-bit fixed-point: 128 = 0.5x, 256 = 1.0x, etc.
 * Call this every frame with the updated base_x. */
typedef struct {
    u8  top_line;   /* First scanline of this band (0-151) */
    u16 speed;      /* Scroll speed: 256 = 1.0x, 128 = 0.5x, 64 = 0.25x */
} RasterBand;

void ngpc_raster_parallax(u8 plane, const RasterBand *bands,
                           u8 count, u16 base_x);

#endif /* NGPC_RASTER_H */
