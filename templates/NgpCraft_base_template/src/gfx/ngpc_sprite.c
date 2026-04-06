/*
 * ngpc_sprite.c - Sprite management
 *
 * Part of NgpCraft_base_template (MIT License)
 * Written from hardware specification (ngpcspec.txt).
 */

#include "ngpc_hw.h"
#include "ngpc_sprite.h"

/* ---- Public API ---- */

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
    volatile u8 *s = HW_SPR_DATA + ((u16)id << 2);

    s[0] = (u8)(tile & 0xFF);
    s[1] = flags | (u8)((tile >> 8) & 1);
    s[2] = x;
    s[3] = y;

    HW_SPR_PAL[id] = pal & 0x0F;
}

void ngpc_sprite_move(u8 id, u8 x, u8 y)
{
    volatile u8 *s = HW_SPR_DATA + ((u16)id << 2);
    s[2] = x;
    s[3] = y;
}

void ngpc_sprite_hide(u8 id)
{
    /* Set priority to 00 = hidden. Keep other bits. */
    volatile u8 *s = HW_SPR_DATA + ((u16)id << 2);
    s[1] &= ~(3 << 3);  /* Clear priority bits */
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
    volatile u8 *s = HW_SPR_DATA + ((u16)id << 2);
    s[1] = (s[1] & 0x01) | flags;
}

void ngpc_sprite_set_tile(u8 id, u16 tile)
{
    volatile u8 *s = HW_SPR_DATA + ((u16)id << 2);
    s[0] = (u8)(tile & 0xFF);
    s[1] = (s[1] & 0xFE) | (u8)((tile >> 8) & 1);
}

u8 ngpc_sprite_get_pal(u8 id)
{
    return HW_SPR_PAL[id] & 0x0F;
}
