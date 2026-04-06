/*
 * ngpc_text.h - Text rendering on scroll planes
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Requires system font loaded (ngpc_load_sysfont) or custom font tiles.
 * System font maps ASCII codes directly to tile indices.
 */

#ifndef NGPC_TEXT_H
#define NGPC_TEXT_H

#include "ngpc_types.h"

/* Print a null-terminated string at tile position (x, y).
 * plane: GFX_SCR1 or GFX_SCR2
 * pal: palette number (0-15) */
void ngpc_text_print(u8 plane, u8 pal, u8 x, u8 y, const char *str);

/* Print a decimal number (0-65535) at tile position.
 * digits: max digits to display (right-aligned, zero-padded). */
void ngpc_text_print_dec(u8 plane, u8 pal, u8 x, u8 y, u16 value, u8 digits);

/* Print a hex number (16-bit) at tile position.
 * digits: number of hex digits (1-4). */
void ngpc_text_print_hex(u8 plane, u8 pal, u8 x, u8 y, u16 value, u8 digits);

/* Print a decimal number without zero-padding (space-padded left).
 * digits: field width (1-5). E.g. value=42, digits=5 -> "   42". */
void ngpc_text_print_num(u8 plane, u8 pal, u8 x, u8 y, u16 value, u8 digits);

/* Print a 32-bit hex number (8 hex digits). */
void ngpc_text_print_hex32(u8 plane, u8 pal, u8 x, u8 y, u32 value);

/* Fill the visible screen (20x19 tiles) from a tile index array.
 * map: array of 20*19 = 380 u16 tile indices.
 * pal: palette applied to all tiles. */
void ngpc_text_tile_screen(u8 plane, u8 pal, const u16 *map);

#endif /* NGPC_TEXT_H */
