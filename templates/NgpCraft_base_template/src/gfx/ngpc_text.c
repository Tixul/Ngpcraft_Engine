/*
 * ngpc_text.c - Text rendering on scroll planes
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * The NGPC system font (loaded via BIOS SYSFONTSET) maps printable
 * ASCII characters directly to tile indices (e.g. 'A' -> tile 0x41).
 */

#include "ngpc_hw.h"
#include "ngpc_gfx.h"
#include "ngpc_text.h"

#define FONT_ASCII_MIN 0x20
#define FONT_ASCII_MAX 0x80

/* ---- Public API ---- */

void ngpc_text_print(u8 plane, u8 pal, u8 x, u8 y, const char *str)
{
    u8 cx = x;

    while (*str) {
        u8 ch = (u8)*str;

        if (ch >= FONT_ASCII_MIN && ch < FONT_ASCII_MAX) {
            ngpc_gfx_put_tile(plane, cx, y, ch, pal);
        }

        cx++;
        if (cx >= SCREEN_TW)
            break;

        str++;
    }
}

void ngpc_text_print_dec(u8 plane, u8 pal, u8 x, u8 y, u16 value, u8 digits)
{
    u8 buf[5];
    u8 i;
    u16 v = value;
    u16 tile;

    /* Fill buffer right-to-left. */
    for (i = 0; i < 5; i++) {
        buf[4 - i] = (u8)(v % 10);
        v /= 10;
    }

    /* Print requested number of digits (zero-padded, right-aligned). */
    for (i = 5 - digits; i < 5; i++) {
        tile = (u16)(buf[i] + '0');
        ngpc_gfx_put_tile(plane, x, y, tile, pal);
        x++;
    }
}

void ngpc_text_print_hex(u8 plane, u8 pal, u8 x, u8 y, u16 value, u8 digits)
{
    u8 i;
    u16 shift;
    u8 nibble;
    u16 tile;

    for (i = 0; i < digits; i++) {
        shift = (digits - 1 - i) * 4;
        nibble = (u8)((value >> shift) & 0xF);

        if (nibble < 10)
            tile = (u16)(nibble + '0');
        else
            tile = (u16)((nibble - 10) + 'A');

        ngpc_gfx_put_tile(plane, x + i, y, tile, pal);
    }
}

void ngpc_text_print_num(u8 plane, u8 pal, u8 x, u8 y, u16 value, u8 digits)
{
    u8 buf[5];
    u8 i;
    u16 v = value;
    u8 leading = 1;

    /* Fill buffer right-to-left. */
    for (i = 0; i < 5; i++) {
        buf[4 - i] = (u8)(v % 10);
        v /= 10;
    }

    /* Print: spaces for leading zeros, then digits. */
    for (i = 5 - digits; i < 5; i++) {
        u16 tile;
        if (leading && buf[i] == 0 && i < 4) {
            tile = ' ';
        } else {
            leading = 0;
            tile = (u16)(buf[i] + '0');
        }
        ngpc_gfx_put_tile(plane, x, y, tile, pal);
        x++;
    }
}

void ngpc_text_print_hex32(u8 plane, u8 pal, u8 x, u8 y, u32 value)
{
    /* Print high 16 bits then low 16 bits. */
    ngpc_text_print_hex(plane, pal, x, y, (u16)(value >> 16), 4);
    ngpc_text_print_hex(plane, pal, x + 4, y, (u16)(value & 0xFFFF), 4);
}

void ngpc_text_tile_screen(u8 plane, u8 pal, const u16 *map)
{
    /* Fill the visible 20x19 tile area from an array of tile indices. */
    u8 tx, ty;
    u16 idx = 0;

    for (ty = 0; ty < SCREEN_TH; ty++) {
        for (tx = 0; tx < SCREEN_TW; tx++) {
            ngpc_gfx_put_tile(plane, tx, ty, map[idx], pal);
            idx++;
        }
    }
}
