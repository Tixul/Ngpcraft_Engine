/* ngpc_font_data.h - Auto-generated from letter_font+upper.png */
/* Font: 73 tiles x 8 rows, 2-color (transparent + ink)        */
/* Tile order: a-z | 0-9 | -/+=:.!? | A-Z | [space] [?] [>]   */
#ifndef NGPC_FONT_DATA_H
#define NGPC_FONT_DATA_H
#include "../../src/core/ngpc_types.h"

#define FONT_NUM_TILES  73u
#ifndef FONT_TILE_BASE
#define FONT_TILE_BASE  128u
#endif

/* 73 tiles x 8 words per tile = 584 u16 values (defined in ngpc_font_data.c).
 * Declared extern so cc900 generates a far-pointer reference (ROM data at 0x200000+).
 * Using static-in-header would make this a same-TU symbol, causing cc900 to generate
 * a near reference which truncates the ROM address and reads garbage. */
extern const u16 NGP_FAR ngpc_font_tiles[FONT_NUM_TILES * 8u];

#endif /* NGPC_FONT_DATA_H */
