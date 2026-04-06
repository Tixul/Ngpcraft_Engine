/*
 * ngpc_bitmap.c - Software bitmap mode
 *
 * Part of NgpCraft_base_template (MIT License)
 * Written from hardware specification (ngpcspec.txt).
 *
 * Emulates a 160x152 pixel framebuffer by mapping 380 unique tiles
 * onto a scroll plane and writing pixels directly into tile RAM.
 *
 * Tile format: 8 rows of u16, 2bpp.
 *   Pixel at column c in row r = bits (15 - c*2) and (14 - c*2) of tile[r].
 */

#include "ngpc_hw.h"
#include "ngpc_gfx.h"
#include "ngpc_bitmap.h"

/* ---- State ---- */

static u16 s_tile_offset;   /* First tile index used by the bitmap */

/* ---- Internal helpers ---- */

/* Get pointer to the u16 word containing pixel (x, y). */
static volatile u16 *pixel_addr(u8 x, u8 y)
{
    u16 tile_x  = x >> 3;          /* x / 8 */
    u16 tile_y  = y >> 3;          /* y / 8 */
    u16 tile_id = s_tile_offset + tile_y * BMP_TW + tile_x;
    u8  row     = y & 7;           /* y % 8 */

    return HW_TILE_DATA + tile_id * TILE_WORDS + row;
}

/* Bit mask for a pixel column (2 bits). */
#define PX_SHIFT(col)   (14 - ((col) & 7) * 2)
#define PX_MASK(col)    ((u16)0x03 << PX_SHIFT(col))

/* ---- Public API ---- */

void ngpc_bmp_init(u8 plane, u16 tile_offset, u8 pal)
{
    volatile u16 *map;
    volatile u16 *tiles;
    u16 tx, ty, i;

    s_tile_offset = tile_offset;

    /* Set up scroll plane: assign consecutive tiles in reading order. */
    map = (plane == GFX_SCR1) ? HW_SCR1_MAP : HW_SCR2_MAP;
    for (ty = 0; ty < BMP_TH; ty++) {
        for (tx = 0; tx < BMP_TW; tx++) {
            u16 tile_id = tile_offset + ty * BMP_TW + tx;
            map[ty * SCR_MAP_W + tx] = SCR_TILE(tile_id, pal);
        }
    }

    /* Clear all bitmap tile data. */
    tiles = HW_TILE_DATA + tile_offset * TILE_WORDS;
    for (i = 0; i < BMP_TILES * TILE_WORDS; i++)
        tiles[i] = 0;
}

void ngpc_bmp_pixel(u8 x, u8 y, u8 color)
{
    volatile u16 *addr;
    u8 shift;

    if (x >= BMP_W || y >= BMP_H) return;

    addr  = pixel_addr(x, y);
    shift = PX_SHIFT(x);
    *addr = (*addr & ~PX_MASK(x)) | ((u16)(color & 3) << shift);
}

u8 ngpc_bmp_get_pixel(u8 x, u8 y)
{
    if (x >= BMP_W || y >= BMP_H) return 0;
    return (u8)((*pixel_addr(x, y) >> PX_SHIFT(x)) & 3);
}

void ngpc_bmp_clear(void)
{
    volatile u16 *tiles = HW_TILE_DATA + s_tile_offset * TILE_WORDS;
    u16 i;

    for (i = 0; i < BMP_TILES * TILE_WORDS; i++)
        tiles[i] = 0;
}

void ngpc_bmp_hline(u8 x, u8 y, u8 w, u8 color)
{
    u8 end, i;

    if (y >= BMP_H) return;
    end = x + w;
    if (end > BMP_W) end = BMP_W;

    for (i = x; i < end; i++)
        ngpc_bmp_pixel(i, y, color);
}

void ngpc_bmp_vline(u8 x, u8 y, u8 h, u8 color)
{
    u8 end, j;

    if (x >= BMP_W) return;
    end = y + h;
    if (end > BMP_H) end = BMP_H;

    for (j = y; j < end; j++)
        ngpc_bmp_pixel(x, j, color);
}

void ngpc_bmp_line(u8 x1, u8 y1, u8 x2, u8 y2, u8 color)
{
    /* Bresenham's line algorithm. */
    s16 dx, dy, sx, sy, err, e2;

    dx = (s16)x2 - (s16)x1;
    if (dx < 0) dx = -dx;
    dy = (s16)y2 - (s16)y1;
    if (dy < 0) dy = -dy;
    dy = -dy;

    sx = (x1 < x2) ? 1 : -1;
    sy = (y1 < y2) ? 1 : -1;
    err = dx + dy;

    while (1) {
        ngpc_bmp_pixel(x1, y1, color);

        if (x1 == x2 && y1 == y2) break;

        e2 = err * 2;
        if (e2 >= dy) {
            err += dy;
            x1 += sx;
        }
        if (e2 <= dx) {
            err += dx;
            y1 += sy;
        }
    }
}

void ngpc_bmp_rect(u8 x, u8 y, u8 w, u8 h, u8 color)
{
    if (w == 0 || h == 0) return;

    ngpc_bmp_hline(x, y, w, color);                 /* top    */
    ngpc_bmp_hline(x, y + h - 1, w, color);         /* bottom */
    if (h > 2) {
        ngpc_bmp_vline(x, y + 1, h - 2, color);     /* left   */
        ngpc_bmp_vline(x + w - 1, y + 1, h - 2, color); /* right */
    }
}

void ngpc_bmp_fill_rect(u8 x, u8 y, u8 w, u8 h, u8 color)
{
    u8 j, end;

    end = y + h;
    if (end > BMP_H) end = BMP_H;

    for (j = y; j < end; j++)
        ngpc_bmp_hline(x, j, w, color);
}
