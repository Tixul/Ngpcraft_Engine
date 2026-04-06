/*
 * ngpc_sprite.c - Sprite management
 *
 * Part of NGPC Template 2026 (MIT License)
 * Written from hardware specification (ngpcspec.txt).
 */

#include "ngpc_hw.h"
#include "ngpc_sprite.h"
#include "ngpc_config.h"

#if NGP_ENABLE_SPR_SHADOW
static u8 s_spr_shadow_data[SPR_MAX * 4u];
static u8 s_spr_shadow_pal[SPR_MAX];
static u8 s_spr_dirty = 0;
static u8 s_spr_dirty_min = 255;
static u8 s_spr_dirty_max = 0;
static volatile u8 s_spr_frame_busy = 0;

static void spr_mark_dirty(u8 id)
{
    if (!s_spr_dirty) {
        s_spr_dirty = 1;
        s_spr_dirty_min = id;
        s_spr_dirty_max = id;
        return;
    }
    if (id < s_spr_dirty_min) s_spr_dirty_min = id;
    if (id > s_spr_dirty_max) s_spr_dirty_max = id;
}
#endif

/* ---- Public API ---- */

void ngpc_sprite_frame_begin(void)
{
#if NGP_ENABLE_SPR_SHADOW
    s_spr_frame_busy = 1;
#endif
}

void ngpc_sprite_frame_end(void)
{
#if NGP_ENABLE_SPR_SHADOW
    s_spr_frame_busy = 0;
#endif
}

void ngpc_sprite_flush(void)
{
#if NGP_ENABLE_SPR_SHADOW
    u8 min_id, max_id, count;
    u16 i;

    if (!s_spr_dirty)
        return;
    if (s_spr_frame_busy)
        return;

    min_id = s_spr_dirty_min;
    max_id = s_spr_dirty_max;
    count = (u8)(max_id - min_id + 1u);

    /* Flush sprite attribs (4 bytes per sprite). */
    {
        volatile u8 *dst = HW_SPR_DATA + ((u16)min_id << 2);
        const u8 *src = &s_spr_shadow_data[(u16)min_id << 2];
        u16 bytes = (u16)count * 4u;

        for (i = 0; i < bytes; i++)
            dst[i] = src[i];
    }

    /* Flush sprite palette indices (1 byte per sprite). */
    {
        volatile u8 *dstp = HW_SPR_PAL + min_id;
        const u8 *srcp = &s_spr_shadow_pal[min_id];

        for (i = 0; i < count; i++)
            dstp[i] = (u8)(srcp[i] & 0x0F);
    }

    s_spr_dirty = 0;
    s_spr_dirty_min = 255;
    s_spr_dirty_max = 0;
#endif
}

void ngpc_sprite_set(u8 id, u8 x, u8 y, u16 tile, u8 pal, u8 flags)
{
    /*
     * ngpcspec.txt "Sprite VRAM Format":
     *   0x8800 + id*4:
     *     [0] = tile number (low 8 bits)
     *     [1] = flags: bit7=Hflip, bit6=Vflip, bit4-3=priority,
     *            bit2=Hchain, bit1=Vchain, bit0=tile bit8
     *     [2] = X position
     *     [3] = Y position
     *   0x8C00 + id:
     *     bits 3-0 = palette (0-15)
     */
#if NGP_ENABLE_SPR_SHADOW
    u16 off = (u16)id << 2;
    s_spr_shadow_data[off + 0u] = (u8)(tile & 0xFF);
    s_spr_shadow_data[off + 1u] = (u8)(flags | (u8)((tile >> 8) & 1));
    s_spr_shadow_data[off + 2u] = x;
    s_spr_shadow_data[off + 3u] = y;
    s_spr_shadow_pal[id] = pal & 0x0F;
    spr_mark_dirty(id);
#else
    volatile u8 *s = HW_SPR_DATA + ((u16)id << 2);

    s[0] = (u8)(tile & 0xFF);
    s[1] = flags | (u8)((tile >> 8) & 1);
    s[2] = x;
    s[3] = y;

    HW_SPR_PAL[id] = pal & 0x0F;
#endif
}

void ngpc_sprite_move(u8 id, u8 x, u8 y)
{
#if NGP_ENABLE_SPR_SHADOW
    u16 off = (u16)id << 2;
    s_spr_shadow_data[off + 2u] = x;
    s_spr_shadow_data[off + 3u] = y;
    spr_mark_dirty(id);
#else
    volatile u8 *s = HW_SPR_DATA + ((u16)id << 2);
    s[2] = x;
    s[3] = y;
#endif
}

void ngpc_sprite_hide(u8 id)
{
    /* Set priority to 00 = hidden. Keep other bits. */
#if NGP_ENABLE_SPR_SHADOW
    u16 off = (u16)id << 2;
    s_spr_shadow_data[off + 1u] &= ~(3u << 3);
    spr_mark_dirty(id);
#else
    volatile u8 *s = HW_SPR_DATA + ((u16)id << 2);
    s[1] &= ~(3 << 3);  /* Clear priority bits */
#endif
}

void ngpc_sprite_hide_all(void)
{
    u8 i;
    for (i = 0; i < SPR_MAX; i++)
        ngpc_sprite_hide(i);
}

void ngpc_sprite_set_flags(u8 id, u8 flags)
{
    /* Preserve tile bit 8 (bit 0), replace everything else. */
#if NGP_ENABLE_SPR_SHADOW
    u16 off = (u16)id << 2;
    s_spr_shadow_data[off + 1u] = (u8)((s_spr_shadow_data[off + 1u] & 0x01u) | flags);
    spr_mark_dirty(id);
#else
    volatile u8 *s = HW_SPR_DATA + ((u16)id << 2);
    s[1] = (s[1] & 0x01) | flags;
#endif
}

void ngpc_sprite_set_tile(u8 id, u16 tile)
{
#if NGP_ENABLE_SPR_SHADOW
    u16 off = (u16)id << 2;
    s_spr_shadow_data[off + 0u] = (u8)(tile & 0xFF);
    s_spr_shadow_data[off + 1u] = (u8)((s_spr_shadow_data[off + 1u] & 0xFEu) | (u8)((tile >> 8) & 1));
    spr_mark_dirty(id);
#else
    volatile u8 *s = HW_SPR_DATA + ((u16)id << 2);
    s[0] = (u8)(tile & 0xFF);
    s[1] = (s[1] & 0xFE) | (u8)((tile >> 8) & 1);
#endif
}

u8 ngpc_sprite_get_pal(u8 id)
{
#if NGP_ENABLE_SPR_SHADOW
    return s_spr_shadow_pal[id] & 0x0F;
#else
    return HW_SPR_PAL[id] & 0x0F;
#endif
}
