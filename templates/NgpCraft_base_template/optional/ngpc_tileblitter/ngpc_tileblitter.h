/*
 * ngpc_tileblitter.h - Blit a W×H rectangle of tilewords from ROM to tilemap
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Pattern from Sonic disassembly §6.9 (routine core at 0x0003EC91):
 *   - Stride +0x40 bytes per tilemap row, wrap-safe on 2KB plane
 *   - Stride +2 bytes per column, wrap-safe on 32 columns
 *   - Optional H-flip: right-to-left step + XOR bit15 of each tileword
 *
 * Difference from NGP_TILEMAP_BLIT_SCR1 (macro in ngpc_tilemap_blit.h):
 *   That macro blits a full-screen asset (20×19) starting at tile (0,0).
 *   ngpc_tblit() blits any W×H region to any (x,y) position, including
 *   partial updates (HUD zone, scrolling room, animated tile block).
 *
 * Source tileword format (u16):
 *   Same as the K2GE scroll plane format produced by ngpc_tilemap.py:
 *   bits 7:0   = tile index low 8 bits
 *   bit  8     = tile index bit 8
 *   bits 12:9  = palette index (0-15)
 *   bit  14    = V flip
 *   bit  15    = H flip
 *
 * Usage:
 *   // Draw a 10×8 block from ROM at screen position (5, 3)
 *   ngpc_tblit(GFX_SCR1, 5, 3, 10, 8, my_room_tiles);
 *
 *   // Mirror the same block horizontally
 *   ngpc_tblit_hflip(GFX_SCR1, 5, 3, 10, 8, my_room_tiles);
 */

#ifndef NGPC_TILEBLITTER_H
#define NGPC_TILEBLITTER_H

#include "../../src/core/ngpc_types.h"
#include "../../src/gfx/ngpc_gfx.h"  /* GFX_SCR1, GFX_SCR2, NGP_FAR */

/* Blit W×H tilewords from a ROM array to a scroll plane rectangle.
 * plane : GFX_SCR1 or GFX_SCR2.
 * x, y  : top-left tile position (0-31).  Wraps at 32 columns / 32 rows.
 * w, h  : rectangle size in tiles.
 * src   : row-major array of w*h u16 tilewords (must use NGP_FAR if in ROM). */
void ngpc_tblit(u8 plane, u8 x, u8 y, u8 w, u8 h,
                const u16 NGP_FAR *src);

/* Same as ngpc_tblit() but the source is mirrored horizontally.
 * Sonic §6.9 H-flip: step right-to-left + XOR each tileword's bit15 (H.F).
 * The source array is still in left-to-right order; the mirror is applied
 * during the blit, not by reversing the array. */
void ngpc_tblit_hflip(u8 plane, u8 x, u8 y, u8 w, u8 h,
                      const u16 NGP_FAR *src);

#endif /* NGPC_TILEBLITTER_H */
