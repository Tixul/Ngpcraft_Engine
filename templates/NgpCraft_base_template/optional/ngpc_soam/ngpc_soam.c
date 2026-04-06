/*
 * ngpc_soam.c - Shadow OAM double-buffer  [REFERENCE ONLY - NOT COMPILED]
 *
 * For the compiled split see:
 *   ngpc_soam_c.c       -- begin/put/hide/hide_all/used + variable storage
 *   ngpc_soam_flush.asm -- flush/flush_partial via LDIRW (hot path ASM)
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Sonic disassembly §1.1 push sequence:
 *   0x0003C017: XDE=0x8800, XHL=shadow_oam, BC=0x80, LDIRW  (256 bytes)
 *   0x0003C02D: XDE=0x8C00, XHL=shadow_col, BC=0x20, LDIRW  (64 bytes)
 *
 * Tail-clear (Pocket Tennis §7.2):
 *   Track highest slot filled (s_used). In flush(), hide slots
 *   from s_used to s_used_prev before pushing to hardware.
 *   This avoids stale sprites from the previous frame staying visible.
 */

#include "ngpc_soam.h"

/* Shadow buffers (320 bytes RAM total).
 * Layout per slot (4 bytes):
 *   [0] = tile_lo  (bits 7:0 of 9-bit tile index)
 *   [1] = attr     (flags | tile_bit8) — PR.C=00 means Hide
 *   [2] = x        (H.P)
 *   [3] = y        (V.P)
 * shadow_col[slot] = palette index (0-15, low nibble) */
static u8 s_oam[SPR_MAX * 4];
static u8 s_col[SPR_MAX];

/* High-water-mark: highest (slot + 1) filled this frame. */
static u8 s_used;
static u8 s_used_prev;

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
        s_oam[(u16)slot * 4u + 1u] = 0; /* attr=0 → PR.C=00 = Hide */
}

void ngpc_soam_flush(void)
{
    volatile u8 *hw_oam = HW_SPR_DATA;
    volatile u8 *hw_col = HW_SPR_PAL;
    u8  i;
    u16 b; /* u16 required: SPR_MAX*4 = 256, u8 would wrap 255->0 (infinite loop) */

    /* Tail-clear: hide slots that were used last frame but not this frame.
     * Write only the attr byte (stride 4) — cheapest safe hide (PT §7.2). */
    for (i = s_used; i < s_used_prev; i++)
        s_oam[(u16)i * 4u + 1u] = 0;

    /* Push shadow OAM to hardware (equivalent to LDIRW). */
    for (b = 0u; b < (u16)SPR_MAX * 4u; b++)
        hw_oam[b] = s_oam[b];

    /* Push shadow palette to hardware. */
    for (i = 0u; i < SPR_MAX; i++)
        hw_col[i] = s_col[i];
}

void ngpc_soam_flush_partial(void)
{
    volatile u8 *hw_oam = HW_SPR_DATA;
    volatile u8 *hw_col = HW_SPR_PAL;
    volatile u8 *hw_attr;
    u16 bytes;
    u16 b;
    u8  i;

    /* Copy only the used prefix (dense slots 0..used-1). */
    bytes = (u16)s_used * 4u;
    for (b = 0u; b < bytes; b++)
        hw_oam[b] = s_oam[b];

    /* Palette indices: copy used, and clear tail up to previous watermark. */
    for (i = 0u; i < s_used; i++)
        hw_col[i] = s_col[i];

    /* Tail-clear: clear only the HW attr byte (stride 4) for leftover slots.
     * This matches what real games do (attr=0 => hidden). */
    hw_attr = HW_SPR_DATA + 1u + (u16)s_used * 4u;
    for (i = s_used; i < s_used_prev; i++) {
        *hw_attr = 0;
        hw_attr += 4;
        hw_col[i] = 0;
    }
}

void ngpc_soam_hide_all(void)
{
    u8 i;
    /* Direct HW write: set attr byte (stride 4) to 0 on all 64 slots. */
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
