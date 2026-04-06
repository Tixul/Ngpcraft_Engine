/*
 * ngpc_gfx.c - Tile/scroll/palette graphics
 *
 * Part of NgpCraft_base_template (MIT License)
 * Written from hardware specification (ngpcspec.txt).
 */

#include "ngpc_hw.h"
#include "ngpc_gfx.h"

/* ---- Internal helpers ---- */

/* Get base pointer for a scroll plane's tile map. */
static volatile u16 *scr_map(u8 plane)
{
    return (plane == GFX_SCR1) ? HW_SCR1_MAP : HW_SCR2_MAP;
}

/* Get base pointer for a plane's palette RAM.
 * ngpcspec.txt: sprites=0x8200, scr1=0x8280, scr2=0x8300.
 * Each palette = 4 consecutive u16 entries. */
static volatile u16 *pal_base(u8 plane)
{
    if (plane == GFX_SPR)  return HW_PAL_SPR;
    if (plane == GFX_SCR1) return HW_PAL_SCR1;
    return HW_PAL_SCR2;
}

/* ---- Public API ---- */

void ngpc_gfx_load_tiles(const u16 NGP_FAR *tiles, u16 count)
{
    volatile u8 *dst = (volatile u8 *)HW_TILE_DATA;
    u16 i;

    /* Write explicit little-endian byte pairs to match NGPC tile format
     * regardless of CPU/toolchain 16-bit store ordering. */
    for (i = 0; i < count; i++) {
        u16 w = tiles[i];
        dst[(u16)(i * 2u) + 0u] = (u8)(w & 0xFFu);
        dst[(u16)(i * 2u) + 1u] = (u8)(w >> 8);
    }
}

void ngpc_gfx_load_tiles_at(const u16 NGP_FAR *tiles, u16 count, u16 offset)
{
    volatile u8 *dst = (volatile u8 *)HW_TILE_DATA + ((u16)(offset * TILE_WORDS) * 2u);
    u16 i;

    for (i = 0; i < count; i++) {
        u16 w = tiles[i];
        dst[(u16)(i * 2u) + 0u] = (u8)(w & 0xFFu);
        dst[(u16)(i * 2u) + 1u] = (u8)(w >> 8);
    }
}

void ngpc_gfx_load_tiles_u8(const u8 NGP_FAR *tiles, u16 tile_count)
{
    volatile u8 *dst = (volatile u8 *)HW_TILE_DATA;
    u16 i;
    u16 bytes = (u16)(tile_count * 16u);

    for (i = 0; i < bytes; i++)
        dst[i] = tiles[i];
}

void ngpc_gfx_load_tiles_u8_at(const u8 NGP_FAR *tiles, u16 tile_count, u16 offset)
{
    volatile u8 *dst = (volatile u8 *)HW_TILE_DATA + (u16)(offset * 16u);
    u16 i;
    u16 bytes = (u16)(tile_count * 16u);

    for (i = 0; i < bytes; i++)
        dst[i] = tiles[i];
}

/* Build a scroll plane map entry from components. */
static u16 make_entry(u16 tile, u8 pal, u8 hflip, u8 vflip)
{
    /*
     * ngpcspec.txt "Data Format for Scroll Plane VRAM":
     *   low byte  = tile number bits 7-0
     *   high byte:
     *     bit 7 = H flip
     *     bit 6 = V flip
     *     bit 4-1 = palette (0-15)
     *     bit 0 = tile number bit 8
     */
    return (tile & 0xFF)
         | ((((tile >> 8) & 1) << 8))
         | ((u16)(pal & 0xF) << 9)
         | ((u16)(hflip & 1) << 15)
         | ((u16)(vflip & 1) << 14);
}

void ngpc_gfx_put_tile(u8 plane, u8 x, u8 y, u16 tile, u8 pal)
{
    volatile u16 *map = scr_map(plane);
    map[(u16)y * (u16)SCR_MAP_W + (u16)x] = make_entry(tile, pal, 0, 0);
}

void ngpc_gfx_put_tile_ex(u8 plane, u8 x, u8 y, u16 tile, u8 pal,
                           u8 hflip, u8 vflip)
{
    volatile u16 *map = scr_map(plane);
    map[(u16)y * (u16)SCR_MAP_W + (u16)x] = make_entry(tile, pal, hflip, vflip);
}

void ngpc_gfx_get_tile(u8 plane, u8 x, u8 y, u16 *tile, u8 *pal)
{
    volatile u16 *map = scr_map(plane);
    u16 entry = map[(u16)y * (u16)SCR_MAP_W + (u16)x];

    *tile = (entry & 0xFF) | (((entry >> 8) & 1) << 8);
    *pal  = (u8)((entry >> 9) & 0xF);
}

void ngpc_gfx_clear(u8 plane)
{
    volatile u16 *map = scr_map(plane);
    u16 i;

    for (i = 0; i < SCR_MAP_W * SCR_MAP_H; i++)
        map[i] = 0;
}

void ngpc_gfx_fill(u8 plane, u16 tile, u8 pal)
{
    volatile u16 *map = scr_map(plane);
    u16 entry = make_entry(tile, pal, 0, 0);
    u16 i;

    for (i = 0; i < SCR_MAP_W * SCR_MAP_H; i++)
        map[i] = entry;
}

void ngpc_gfx_fill_rect(u8 plane, u8 x, u8 y, u8 w, u8 h, u16 tile, u8 pal)
{
    volatile u16 *map = scr_map(plane);
    u16 entry = make_entry(tile, pal, 0, 0);
    u8 row, col, yr, xc;
    u16 base;

    for (row = 0; row < h; row++) {
        yr   = (u8)((u8)(y + row) & 0x1Fu);
        base = (u16)yr * (u16)SCR_MAP_W;
        for (col = 0; col < w; col++) {
            xc = (u8)((u8)(x + col) & 0x1Fu);
            map[base + xc] = entry;
        }
    }
}

void ngpc_gfx_set_rect_pal(u8 plane, u8 x, u8 y, u8 w, u8 h, u8 pal)
{
    /*
     * Sonic §3.3: tileword high byte mask 0xC1 = 1100_0001
     *   keeps H.F (bit15), V.F (bit14), tile_bit8 (bit8)
     *   replaces palette CP.C (bits 12:9).
     * Full u16 mask: ~(0xF << 9) = 0xE1FF
     */
    volatile u16 *map = scr_map(plane);
    u16 pal_bits = (u16)((u16)(pal & 0x0Fu) << 9);
    u8 row, col, yr, xc;
    u16 base, entry;

    for (row = 0; row < h; row++) {
        yr   = (u8)((u8)(y + row) & 0x1Fu);
        base = (u16)yr * (u16)SCR_MAP_W;
        for (col = 0; col < w; col++) {
            xc    = (u8)((u8)(x + col) & 0x1Fu);
            entry = map[base + xc];
            entry = (entry & 0xE1FFu) | pal_bits;
            map[base + xc] = entry;
        }
    }
}

void ngpc_gfx_set_palette(u8 plane, u8 pal_id, u16 c0, u16 c1, u16 c2, u16 c3)
{
    /*
     * ngpcspec.txt: palette RAM is 16-bit access ONLY.
     * Each palette = 4 consecutive u16 entries.
     * palette[pal_id * 4 + 0..3] = c0..c3.
     */
    volatile u16 *base = pal_base(plane);
    u16 off = pal_id * 4;

    base[off + 0] = c0;
    base[off + 1] = c1;
    base[off + 2] = c2;
    base[off + 3] = c3;
}

void ngpc_gfx_set_bg_color(u16 color)
{
    /* Set background palette entry 0 and enable background.
     * ngpcspec.txt: BG palette at 0x83E0, BG_CTL at 0x8118.
     * BGON = bit7=1, bit6=0 (value 0x80) enables background color. */
    HW_PAL_BG[0] = color;
    HW_BG_CTL = 0x80;
}

void ngpc_gfx_scroll(u8 plane, u8 x, u8 y)
{
    /* ngpcspec.txt: scroll offsets at 0x8032-0x8035. */
    if (plane == GFX_SCR1) {
        HW_SCR1_OFS_X = x;
        HW_SCR1_OFS_Y = y;
    } else {
        HW_SCR2_OFS_X = x;
        HW_SCR2_OFS_Y = y;
    }
}

void ngpc_gfx_scroll_parallax(u8 cam_x, u8 cam_y, u8 scr1_shift, u8 scr2_shift)
{
    /* SCR1: 0xFF = fix at 0 (static layer / HUD), else arithmetic shift. */
    if (scr1_shift == 0xFFu) {
        HW_SCR1_OFS_X = 0u;
        HW_SCR1_OFS_Y = 0u;
    } else {
        HW_SCR1_OFS_X = (u8)(cam_x >> scr1_shift);
        HW_SCR1_OFS_Y = (u8)(cam_y >> scr1_shift);
    }
    /* SCR2: same. cam_x/cam_y are u8 so >> is logical (zero-fill) — always well-defined. */
    if (scr2_shift == 0xFFu) {
        HW_SCR2_OFS_X = 0u;
        HW_SCR2_OFS_Y = 0u;
    } else {
        HW_SCR2_OFS_X = (u8)(cam_x >> scr2_shift);
        HW_SCR2_OFS_Y = (u8)(cam_y >> scr2_shift);
    }
}

void ngpc_gfx_swap_planes(void)
{
    /* ngpcspec.txt: 0x8030 bit 7 toggles priority. */
    HW_SCR_PRIO ^= 0x80;
}

void ngpc_gfx_set_viewport(u8 x, u8 y, u8 w, u8 h)
{
    HW_WIN_X = x;
    HW_WIN_Y = y;
    HW_WIN_W = w;
    HW_WIN_H = h;
}

/* ---- Screen effects ---- */

void ngpc_gfx_sprite_offset(u8 dx, u8 dy)
{
    /* ngpcspec.txt "Sprite Position Offset Function":
     * 0x8020/0x8021 - offset added to ALL sprite positions.
     * H = H.P + PO.H,  V = V.P + PO.V
     * Perfect for screen shake without moving each sprite. */
    HW_SPR_OFS_X = dx;
    HW_SPR_OFS_Y = dy;
}

void ngpc_gfx_lcd_invert(u8 enable)
{
    /* ngpcspec.txt "2D Control Register" 0x8012:
     * Bit 7 NEG: 0 = normal, 1 = inverted display.
     * Takes effect on next scanline. */
    if (enable)
        HW_LCD_CTL |= 0x80;
    else
        HW_LCD_CTL &= ~0x80;
}

void ngpc_gfx_set_outside_color(u8 pal_index)
{
    /* ngpcspec.txt "2D Control Register" 0x8012:
     * Bits 2-0 OOWC = outside-window color palette index.
     * Colors the area outside the viewport (letterbox bars).
     * Uses background color palette at 0x83E0. */
    HW_LCD_CTL = (HW_LCD_CTL & 0xF8) | (pal_index & 0x07);
}

u8 ngpc_gfx_char_over(void)
{
    /* ngpcspec.txt "2D Status Register" 0x8010:
     * Bit 7 C.OVR: 1 = Character Over has occurred.
     * Cleared at end of VBlank automatically.
     * Useful for detecting sprite/tile overload. */
    return (HW_STATUS & STATUS_CHAR_OVR) ? 1 : 0;
}

void ngpc_gfx_set_color_direct(u8 plane, u8 pal_id, u8 color_idx, u16 color)
{
    volatile u16 *base = pal_base(plane);
    base[(u16)(pal_id * 4u) + (u16)color_idx] = color;
}

/* ---- Software tile rotation ---- */
/*
 * NGPC tile format: 8 rows of u16, 2bpp (2 bits per pixel).
 * Row r = tile[r]. Pixel at column c = bits (14 - c*2) and (15 - c*2).
 * Hardware only supports H-flip and V-flip; 90-degree rotation
 * must be done in software by rearranging pixel data.
 *
 * Best used at load time (pre-rotate), not per-frame on 6 MHz CPU.
 */

/* Extract 2-bit pixel value at (col, row) from tile data. */
#define TILE_GET_PX(tile, col, row) \
    (((tile)[(row)] >> (14 - (col) * 2)) & 0x03)

void ngpc_tile_rotate90(const u16 *src, u16 *dst)
{
    /*
     * 90 degrees clockwise:
     *   source(col, row) -> dest(7 - row, col)
     *   so dest(dc, dr) reads from source(col = dr, row = 7 - dc)
     */
    u8 dr, dc;
    u16 row;
    u8 px;

    for (dr = 0; dr < 8; dr++) {
        row = 0;
        for (dc = 0; dc < 8; dc++) {
            px = TILE_GET_PX(src, dr, 7 - dc);
            row |= (u16)px << (14 - dc * 2);
        }
        dst[dr] = row;
    }
}

void ngpc_tile_rotate270(const u16 *src, u16 *dst)
{
    /*
     * 90 degrees counter-clockwise (= 270 CW):
     *   source(col, row) -> dest(row, 7 - col)
     *   so dest(dc, dr) reads from source(col = 7 - dr, row = dc)
     */
    u8 dr, dc;
    u16 row;
    u8 px;

    for (dr = 0; dr < 8; dr++) {
        row = 0;
        for (dc = 0; dc < 8; dc++) {
            px = TILE_GET_PX(src, 7 - dr, dc);
            row |= (u16)px << (14 - dc * 2);
        }
        dst[dr] = row;
    }
}

void ngpc_tile_rotate90_to(const u16 *src, u16 dest_tile_id)
{
    u16 tmp[8];
    ngpc_tile_rotate90(src, tmp);
    ngpc_gfx_load_tiles_at(tmp, 8, dest_tile_id);
}

void ngpc_tile_rotate270_to(const u16 *src, u16 dest_tile_id)
{
    u16 tmp[8];
    ngpc_tile_rotate270(src, tmp);
    ngpc_gfx_load_tiles_at(tmp, 8, dest_tile_id);
}
