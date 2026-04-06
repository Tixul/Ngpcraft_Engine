/*
 * gfx_data.c - Example / placeholder graphics data
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Replace or extend this file with your own tile/sprite graphics.
 *
 * Tile format (from ngpcspec.txt):
 *   8x8 pixels, 2 bits per pixel, stored as 8 x u16.
 *   Color 0 = transparent, colors 1-3 = opaque.
 */

#include "gfx_data.h"

/* Example: a simple filled square tile (all color 1) */
const u16 TILES_EXAMPLE[] = {
    /* Tile 0: solid fill (color 1 = 0x55 pattern in 2bpp) */
    0x5555, 0x5555, 0x5555, 0x5555,
    0x5555, 0x5555, 0x5555, 0x5555,

    /* Tile 1: border (color 2 edge, color 1 inside) */
    0xAAAA, 0xA55A, 0xA55A, 0xA55A,
    0xA55A, 0xA55A, 0xA55A, 0xAAAA,

    /* Tile 2: checkerboard (color 1 and 2 alternating) */
    0x6969, 0x9696, 0x6969, 0x9696,
    0x6969, 0x9696, 0x6969, 0x9696,

    /* Tile 3: diagonal (color 3) */
    0xC000, 0x3C00, 0x0F00, 0x03C0,
    0x00F0, 0x003C, 0x000F, 0x0003
};

/* Number of u16 words total (4 tiles x 8 words each) */
const u16 TILES_EXAMPLE_COUNT = 32;
