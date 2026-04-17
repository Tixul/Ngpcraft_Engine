/*
 * ngpc_font.c - Custom dialogue font loader and char mapping
 *
 * Font tile data is pre-transformed: background pixels encoded as color 2
 * (opaque fill), ink pixels as color 1. Color 0 is not used in the font.
 * NGPC hardware forces color-index 0 transparent on SCR1/SCR2 — using
 * color 2 for the background ensures an opaque dialog box background.
 */

#include "ngpc_font.h"
#include "ngpc_font_data.h"
#include "../../src/gfx/ngpc_gfx.h"
#ifdef NO_SYSFONT
#include "../../src/core/ngpc_hw.h"
#include "../../GraphX/gen/ngpc_custom_font.h"
#endif

void ngpc_font_load(void)
{
#ifndef NO_SYSFONT
    ngpc_gfx_load_tiles_at(ngpc_font_tiles,
                           (u16)(FONT_NUM_TILES * 8u),
                           FONT_TILE_BASE);
#endif
}

u16 ngpc_font_char_to_tile(char ch)
{
#ifdef NO_SYSFONT
    /* Custom font: tile slot == ASCII code (direct mapping, slots 32-127). */
    return (u16)(u8)ch;
#else
    u16 off;

    if (ch >= 'a' && ch <= 'z')
        off = (u16)((u8)ch - (u8)'a');
    else if (ch >= 'A' && ch <= 'Z')
        off = (u16)(44u + (u8)ch - (u8)'A');
    else if (ch >= '0' && ch <= '9')
        off = (u16)(26u + (u8)ch - (u8)'0');
    else {
        switch (ch) {
            case '-': off = 36u; break;
            case '/': off = 37u; break;
            case '+': off = 38u; break;
            case '=': off = 39u; break;
            case ':': off = 40u; break;
            case '.': off = 41u; break;
            case '!': off = 42u; break;
            case '?': off = 43u; break;
            case '>': off = FONT_TILE_CURSOR; break;
            default:  off = FONT_TILE_SPACE;  break;
        }
    }

    return (u16)(FONT_TILE_BASE + off);
#endif
}

void ngpc_font_apply_palette(u8 plane, u8 pal_slot)
{
#ifdef NO_SYSFONT
    ngpc_custom_font_set_palette(plane, pal_slot);
#else
    /* Default dialog font palette: ink=white, fill=dark blue background. */
    ngpc_gfx_set_palette(plane, pal_slot,
        RGB(0,0,0), RGB(15,15,15), RGB(0,0,8), RGB(0,0,0));
#endif
}
