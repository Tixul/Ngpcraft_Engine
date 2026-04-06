/*
 * ngpc_gfx.h - Tile/scroll/palette graphics functions
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Planes: use GFX_SCR1 or GFX_SCR2 to select scroll plane.
 */

#ifndef NGPC_GFX_H
#define NGPC_GFX_H

#include "ngpc_types.h"

/* cc900 supports memory qualifiers for pointer displacement: __near/__far.
 * The makefile defines NGP_FAR=__far and NGP_NEAR=__near for cc900 builds.
 * When building with another toolchain, you can leave these undefined. */
#ifndef NGP_FAR
#define NGP_FAR
#endif

/* Plane identifiers */
#define GFX_SCR1    0
#define GFX_SCR2    1
#define GFX_SPR     2

/* Copy tile data into character RAM.
 * tiles: array of u16 words (8 words per tile).
 * count: number of u16 words to copy (= num_tiles * 8).
 * Tiles are loaded starting at tile index 0. */
void ngpc_gfx_load_tiles(const u16 NGP_FAR *tiles, u16 count);

/* Copy tile data at a specific tile offset.
 * offset: tile index to start at (0-511). */
void ngpc_gfx_load_tiles_at(const u16 NGP_FAR *tiles, u16 count, u16 offset);

/* Note (cc900 near/far hazard):
 * If your tiles/map data lives in cart ROM (0x200000+), passing pointers through
 * generic helpers can be toolchain-sensitive. If you see corrupted/truncated
 * backgrounds but your generated data is correct, prefer the macro-based path:
 *   `#include "ngpc_tilemap_blit.h"`
 *   `NGP_TILEMAP_BLIT_SCR1(asset_prefix, tile_base);`
 */

/* Copy raw tile bytes into character RAM.
 * tiles: array of bytes (16 bytes per tile, NGPC native layout).
 * tile_count: number of tiles (not words).
 * This path avoids any ambiguity around 16-bit store ordering. */
void ngpc_gfx_load_tiles_u8(const u8 NGP_FAR *tiles, u16 tile_count);
void ngpc_gfx_load_tiles_u8_at(const u8 NGP_FAR *tiles, u16 tile_count, u16 offset);

/* Place a tile on a scroll plane.
 * plane: GFX_SCR1 or GFX_SCR2
 * x, y: tile coordinates (0-31)
 * tile: tile index (0-511)
 * pal: palette number (0-15) */
void ngpc_gfx_put_tile(u8 plane, u8 x, u8 y, u16 tile, u8 pal);

/* Place a tile with flip control.
 * hflip: 1 = mirror horizontally
 * vflip: 1 = mirror vertically
 * Hardware supports this per-tile on scroll planes (spec bits 7/6). */
void ngpc_gfx_put_tile_ex(u8 plane, u8 x, u8 y, u16 tile, u8 pal,
                           u8 hflip, u8 vflip);

/* Read back tile index and palette at a position. */
void ngpc_gfx_get_tile(u8 plane, u8 x, u8 y, u16 *tile, u8 *pal);

/* Clear all tiles on a scroll plane (set to tile 0, palette 0). */
void ngpc_gfx_clear(u8 plane);

/* Fill entire plane with one tile + palette. */
void ngpc_gfx_fill(u8 plane, u16 tile, u8 pal);

/* Fill a W×H rectangle with one tile + palette.
 * x, y: top-left tile coordinates (0-31).
 * Wraps around the 32×32 map if x+w or y+h exceeds 31.
 * Sonic disassembly §3.2: uses wrap-safe (BC+0x40)&0x07FF addressing. */
void ngpc_gfx_fill_rect(u8 plane, u8 x, u8 y, u8 w, u8 h, u16 tile, u8 pal);

/* Set palette on a W×H rectangle without touching tile indices or flip bits.
 * x, y: top-left tile coordinates (0-31). Wraps at 32.
 * Sonic disassembly §3.3: mask 0xC1 keeps H.F + V.F + tile_bit8, replaces CP.C. */
void ngpc_gfx_set_rect_pal(u8 plane, u8 x, u8 y, u8 w, u8 h, u8 pal);

/* Set a 4-color palette.
 * plane: GFX_SCR1, GFX_SCR2, or GFX_SPR
 * pal_id: palette number (0-15)
 * c0-c3: colors (use RGB() macro) */
void ngpc_gfx_set_palette(u8 plane, u8 pal_id, u16 c0, u16 c1, u16 c2, u16 c3);

/* Set background color (single RGB value). */
void ngpc_gfx_set_bg_color(u16 color);

/* Set scroll offset for a plane. */
void ngpc_gfx_scroll(u8 plane, u8 x, u8 y);

/* Apply parallax scroll to both planes using power-of-two right-shifts.
 * Cheaper than % division: uses SAR (T900 arithmetic shift) — no software mul/div.
 * cam_x, cam_y: camera pixel position (truncated to u8 for the hardware register).
 * scr1_shift: right-shift applied to cam for SCR1. 0=1:1, 1=1:2, 2=1:4, 3=1:8.
 * scr2_shift: same for SCR2.
 * Pass 0xFF to fix a plane at offset 0 (static background / HUD layer).
 * Typical: scr1_shift=0 (main bg, 1:1), scr2_shift=1 (distant bg, half speed).
 * Confirmed: Ganbare Neo Poke-kun uses sra 1 for 2:1 parallax (analysis §4.2). */
void ngpc_gfx_scroll_parallax(u8 cam_x, u8 cam_y, u8 scr1_shift, u8 scr2_shift);

/* Swap plane priority (toggle which plane is in front). */
void ngpc_gfx_swap_planes(void);

/* Set viewport (window) area. */
void ngpc_gfx_set_viewport(u8 x, u8 y, u8 w, u8 h);

/* ---- Screen effects (hardware features, new in 2026 template) ---- */

/* Screen shake: offset ALL sprites by (dx, dy) pixels.
 * Hardware register 0x8020/0x8021 adds this to every sprite position.
 * Set (0, 0) to stop. Does NOT affect scroll planes. */
void ngpc_gfx_sprite_offset(u8 dx, u8 dy);

/* Invert the entire LCD display (negative photo effect).
 * enable: 1 = inverted, 0 = normal.
 * Takes effect on the next scanline. */
void ngpc_gfx_lcd_invert(u8 enable);

/* Set the color shown outside the viewport window (letterbox bars).
 * Uses background palette entries. pal_index: 0-7. */
void ngpc_gfx_set_outside_color(u8 pal_index);

/* Check if Character Over occurred this frame.
 * Returns 1 if too many sprites/tiles overloaded the renderer.
 * Cleared automatically at end of VBlank. */
u8 ngpc_gfx_char_over(void);

/* Write a single palette color directly to hardware (no software state).
 * Use for per-frame hit-flash / invincibility effects.
 * Restore with ngpc_gfx_set_palette() on the next frame.
 * Sonic disassembly §15: direct HW write for instant effect, restore from shadow next frame.
 * plane:     GFX_SCR1, GFX_SCR2, or GFX_SPR
 * pal_id:    palette index (0-15)
 * color_idx: color slot (0-3)
 * color:     12-bit RGB value (use RGB() macro) */
void ngpc_gfx_set_color_direct(u8 plane, u8 pal_id, u8 color_idx, u16 color);

/* ---- Software tile rotation (not supported by hardware) ---- */

/* Rotate tile data 90 degrees clockwise.
 * src: source tile (8 x u16 words, 2bpp 8x8).
 * dst: destination buffer (8 x u16 words, must not overlap src).
 * Works on RAM buffers. Use ngpc_gfx_load_tiles_at() to send to VRAM.
 * Note: 180 degrees = hardware H-flip + V-flip (free, use put_tile_ex). */
void ngpc_tile_rotate90(const u16 *src, u16 *dst);

/* Rotate tile data 90 degrees counter-clockwise (= 270 CW). */
void ngpc_tile_rotate270(const u16 *src, u16 *dst);

/* Rotate and load directly to VRAM at a tile offset.
 * Convenience: rotates src into a temp buffer then writes to tile RAM. */
void ngpc_tile_rotate90_to(const u16 *src, u16 dest_tile_id);
void ngpc_tile_rotate270_to(const u16 *src, u16 dest_tile_id);

#endif /* NGPC_GFX_H */
