/*
 * ngpc_tileblitter.c - Blit W×H tilewords from ROM to scroll plane
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Sonic §6.9 addressing (byte-level on the 2KB tilemap):
 *
 *   Column advance (+1 tile = +2 bytes), wraps at 32 cols = 64 bytes:
 *     addr = (addr & 0xFFC0) | ((addr + 2) & 0x003F)
 *
 *   Row advance (+1 row = +64 bytes), wraps at 2KB plane:
 *     addr = (addr & 0xF800) | ((addr + 0x40) & 0x07FF)
 *
 * We work with byte offsets into the tilemap because the wrap masks
 * operate on byte addresses.  The map bases (0x9000 / 0x9800) are
 * near addresses so a simple cast to volatile u8* is safe.
 *
 * NGP_FAR on src: ROM is at 0x200000+ (far pointer territory).
 * The compiler must see NGP_FAR (__far) on the pointer or it will
 * generate a 16-bit load from a truncated near address → garbage tiles.
 */

#include "ngpc_tileblitter.h"
#include "../../src/core/ngpc_hw.h"

/* Return byte-addressed base of the scroll plane tilemap. */
static volatile u8 *map_base(u8 plane)
{
    return (volatile u8 *)(plane == GFX_SCR1
                           ? (u16)0x9000u
                           : (u16)0x9800u);
}

void ngpc_tblit(u8 plane, u8 x, u8 y, u8 w, u8 h,
                const u16 NGP_FAR *src)
{
    volatile u8 *base = map_base(plane);
    u16 row_addr = (u16)((u16)y * 0x40u + (u16)x * 2u);
    u8 row, col;
    u16 col_addr, tw;

    for (row = 0; row < h; row++) {
        col_addr = row_addr;
        for (col = 0; col < w; col++) {
            tw = *src++;
            base[col_addr]      = (u8)(tw & 0xFFu);
            base[col_addr + 1u] = (u8)(tw >> 8);
            /* Column advance: wrap at 32 cols (64 bytes) */
            col_addr = (col_addr & 0xFFC0u) | ((u16)(col_addr + 2u) & 0x003Fu);
        }
        /* Row advance: wrap at 2KB plane */
        row_addr = (row_addr & 0xF800u) | ((u16)(row_addr + 0x40u) & 0x07FFu);
    }
}

void ngpc_tblit_hflip(u8 plane, u8 x, u8 y, u8 w, u8 h,
                      const u16 NGP_FAR *src)
{
    /*
     * Sonic §6.9 H-flip:
     *   - Start from the rightmost column: x + w - 1
     *   - Step left (-2 bytes per column)
     *   - XOR each tileword's bit15 (H.F) to flip tile horizontally
     *
     * Wrap for left step (-2): same formula but subtract:
     *   col_addr = (col_addr & 0xFFC0) | ((col_addr - 2) & 0x003F)
     */
    volatile u8 *base = map_base(plane);
    /* Start address: column (x + w - 1), same row y */
    u8 x_right = (u8)((u8)(x + w - 1u) & 0x1Fu);
    u16 row_addr = (u16)((u16)y * 0x40u + (u16)x_right * 2u);
    u8 row, col;
    u16 col_addr, tw;

    for (row = 0; row < h; row++) {
        col_addr = row_addr;
        for (col = 0; col < w; col++) {
            tw  = *src++;
            tw ^= 0x8000u; /* toggle H.F (bit15) */
            base[col_addr]      = (u8)(tw & 0xFFu);
            base[col_addr + 1u] = (u8)(tw >> 8);
            /* Column step left: wrap at 32 cols (64 bytes) */
            col_addr = (col_addr & 0xFFC0u) | ((u16)(col_addr - 2u) & 0x003Fu);
        }
        /* Row advance: wrap at 2KB plane */
        row_addr = (row_addr & 0xF800u) | ((u16)(row_addr + 0x40u) & 0x07FFu);
    }
}
