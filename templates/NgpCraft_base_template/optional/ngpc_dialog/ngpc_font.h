/*
 * ngpc_font.h - Custom dialogue font (73 tiles, 8x8px)
 *
 * Font order: a-z | 0-9 | -/+=:.!? | A-Z | [space(70)] [?(71)] [>(72)]
 *
 * Usage:
 *   ngpc_font_load();                  // call once at init
 *   u16 t = ngpc_font_char_to_tile(c); // get absolute tile index
 *   ngpc_gfx_put_tile(plane, x, y, t, pal);
 */

#ifndef NGPC_FONT_H
#define NGPC_FONT_H

#include "../../src/core/ngpc_types.h"

/* First tile slot used by the custom font in TILE_RAM.
 * Tiles 0-31   : reserved
 * Tiles 32-127 : BIOS sysfont (if loaded)
 * Tiles 128+   : custom font starts here */
#ifndef FONT_TILE_BASE
#define FONT_TILE_BASE  128u
#endif

/* Total number of glyph tiles in the font. */
#define FONT_NUM_TILES  73u

/* Special tile offsets within the font (relative to FONT_TILE_BASE). */
#define FONT_TILE_SPACE   70u   /* blank tile used for ' ' and unknowns */
#define FONT_TILE_CURSOR  72u   /* '>' selection cursor */

/* Load the 73 font tiles into TILE_RAM at FONT_TILE_BASE.
 * No-op when NO_SYSFONT is defined (custom font already loaded at boot). */
void ngpc_font_load(void);

/* Set palette slot to the font's colors.
 * When NO_SYSFONT: uses colors extracted from the custom font PNG.
 * Otherwise: default dialog palette (white ink, dark fill). */
void ngpc_font_apply_palette(u8 plane, u8 pal_slot);

/* Convert an ASCII character to its absolute tile index.
 * Returns FONT_TILE_BASE + FONT_TILE_SPACE for unsupported characters. */
u16 ngpc_font_char_to_tile(char ch);

#endif /* NGPC_FONT_H */
