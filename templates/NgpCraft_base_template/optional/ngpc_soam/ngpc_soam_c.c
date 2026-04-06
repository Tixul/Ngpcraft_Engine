/*
 * ngpc_soam_c.c - Shadow OAM: variables + non-flush functions (C part)
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Split:
 *   ngpc_soam_c.c       -- this file: begin, put, hide, hide_all, used + data
 *   ngpc_soam_flush.asm -- flush() and flush_partial() via LDIRW/LDIR
 *
 * ngpc_soam.c in this folder is the original reference (not compiled).
 *
 * Variables are non-static so ngpc_soam_flush.asm can extern them.
 */

#include "ngpc_soam.h"

/* Shadow buffers (320 bytes RAM total).
 * Layout per slot (4 bytes):
 *   [0] = tile_lo  (bits 7:0 of 9-bit tile index)
 *   [1] = attr     (flags | tile_bit8) -- PR.C=00 means Hide
 *   [2] = x        (H.P)
 *   [3] = y        (V.P)
 * s_col[slot] = palette index (0-15, low nibble) */
u8 s_oam[SPR_MAX * 4];
u8 s_col[SPR_MAX];

/* High-water-mark: highest (slot + 1) filled this frame. */
u8 s_used;
u8 s_used_prev;

/* ---- Public API ---- */

void ngpc_soam_begin(void)
{
    s_used_prev = s_used;
    s_used = 0;
}

void ngpc_soam_put(u8 slot, u8 x, u8 y, u16 tile, u8 flags, u8 pal)
{
    u8 attr;
    u8 *p;

    if (slot >= SPR_MAX)
        return;

    /* Safety: if priority bits are SPR_HIDE, promote to SPR_FRONT. */
    attr = flags;
    if ((attr & (3u << 3)) == (u8)SPR_HIDE)
        attr = (u8)((attr & (u8)~(3u << 3)) | (u8)SPR_FRONT);

    /* Merge tile bit8 into attr bit0 (ngpcspec sprite format). */
    attr = (u8)(attr | (u8)((tile >> 8) & 1u));

    p = &s_oam[(u16)slot * 4u];
    p[0] = (u8)(tile & 0xFFu);
    p[1] = attr;
    p[2] = x;
    p[3] = y;
    s_col[slot] = pal & 0x0Fu;

    /* Advance high-water-mark. */
    if ((u8)(slot + 1u) > s_used)
        s_used = (u8)(slot + 1u);
}

void ngpc_soam_hide(u8 slot)
{
    if (slot < SPR_MAX)
        s_oam[(u16)slot * 4u + 1u] = 0; /* attr=0 -> PR.C=00 = Hide */
}

void ngpc_soam_hide_all(void)
{
    u8 i;
    volatile u8 *p = HW_SPR_DATA + 1; /* byte 1 = attr */
    for (i = 0; i < SPR_MAX; i++) {
        *p = 0;
        p += 4;
    }
    s_used = 0;
    s_used_prev = 0;
}

u8 ngpc_soam_used(void)
{
    return s_used;
}
