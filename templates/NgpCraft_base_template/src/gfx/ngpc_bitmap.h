/*
 * ngpc_bitmap.h - Software bitmap mode (pixel-level rendering)
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * The NGPC has no hardware bitmap mode. This module emulates one
 * by assigning a unique tile to each screen position (20x19 = 380 tiles)
 * and writing pixels directly into tile RAM.
 *
 * 2bpp mode: 4 colors per pixel (one palette), full 160x152 screen.
 * Writes go straight to VRAM - no flush needed, but write during VBlank
 * to avoid tearing.
 *
 * Tile budget: 380 of 512 tiles are used, leaving 132 for other uses.
 * RAM cost: none (writes directly to VRAM).
 */

#ifndef NGPC_BITMAP_H
#define NGPC_BITMAP_H

#include "ngpc_types.h"

/* Bitmap dimensions (same as screen) */
#define BMP_W       160
#define BMP_H       152
#define BMP_TW      20      /* tiles wide  */
#define BMP_TH      19      /* tiles tall  */
#define BMP_TILES   380     /* total tiles used (20 * 19) */

/* Initialize bitmap mode on a scroll plane.
 * plane: GFX_SCR1 or GFX_SCR2
 * tile_offset: first tile index to use (0-131, must leave room for 380 tiles)
 * pal: palette to use for all bitmap tiles (0-15)
 *
 * Sets up the scroll plane map and clears the tile data. */
void ngpc_bmp_init(u8 plane, u16 tile_offset, u8 pal);

/* Set a single pixel. color: 0-3. */
void ngpc_bmp_pixel(u8 x, u8 y, u8 color);

/* Read a single pixel back. Returns 0-3. */
u8 ngpc_bmp_get_pixel(u8 x, u8 y);

/* Clear the entire bitmap (all pixels to color 0). */
void ngpc_bmp_clear(void);

/* Draw a line (Bresenham). color: 0-3. */
void ngpc_bmp_line(u8 x1, u8 y1, u8 x2, u8 y2, u8 color);

/* Draw a rectangle outline. */
void ngpc_bmp_rect(u8 x, u8 y, u8 w, u8 h, u8 color);

/* Draw a filled rectangle. */
void ngpc_bmp_fill_rect(u8 x, u8 y, u8 w, u8 h, u8 color);

/* Draw a horizontal line (fast, operates on whole tile rows). */
void ngpc_bmp_hline(u8 x, u8 y, u8 w, u8 color);

/* Draw a vertical line. */
void ngpc_bmp_vline(u8 x, u8 y, u8 h, u8 color);

#endif /* NGPC_BITMAP_H */
