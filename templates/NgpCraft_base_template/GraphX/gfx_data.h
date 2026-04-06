/*
 * gfx_data.h - Graphics asset declarations (tiles, sprites, palettes)
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * This header declares all graphical data arrays.
 * The actual data lives in .c files in this folder.
 *
 * Typical workflow:
 *   1. Design tiles/sprites in Piskel or tile editor
 *   2. Export as NGPC 2bpp C arrays (8x8 tiles, 16 bytes each)
 *   3. Drop the .c files into this GraphX/ folder
 *   4. Declare the arrays here
 *   5. Add the .c files to the makefile OBJS list
 *
 * Tile format (from ngpcspec.txt):
 *   Each tile = 8x8 pixels, 2 bits per pixel = 16 bytes.
 *   Stored as 8 rows of 2 bytes (u16) each.
 *   Pixel 0 is upper-right, progressing leftward.
 */

#ifndef GFX_DATA_H
#define GFX_DATA_H

#include "ngpc_types.h"

/* ---- Example tile set ---- */
extern const u16 TILES_EXAMPLE[];
extern const u16 TILES_EXAMPLE_COUNT;   /* Number of u16 words */

/* ---- Sprite data (for multi-tile sprites) ---- */
/* extern const u8 SPR_PLAYER_FRAMES[];  */
/* extern const u8 SPR_PLAYER_FRAME_COUNT; */

/* ---- Palette presets ---- */
/* Define your game palettes here as arrays of 4 RGB values.
 * Example:
 *   extern const u16 PAL_PLAYER[4];
 *   extern const u16 PAL_TERRAIN[4];
 */

#endif /* GFX_DATA_H */
