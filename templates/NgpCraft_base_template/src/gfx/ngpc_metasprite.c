/*
 * ngpc_metasprite.c - Metasprite system
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Key design: when the group has SPR_HFLIP, part offsets are mirrored
 * horizontally (ox = width - 8 - ox) and each part's own H-flip is toggled.
 * Same logic for SPR_VFLIP with oy. This ensures the metasprite looks
 * correct when flipped without requiring separate definitions per direction.
 */

#include "ngpc_hw.h"
#include "ngpc_sprite.h"
#include "ngpc_metasprite.h"

/* ---- Public API ---- */

u8 ngpc_mspr_draw(u8 spr_start, s16 x, s16 y,
                   const NgpcMetasprite *def, u8 flags)
{
    u8 i;
    u8 group_hflip = (flags & SPR_HFLIP) ? 1 : 0;
    u8 group_vflip = (flags & SPR_VFLIP) ? 1 : 0;
    /* Priority bits from group flags (mask out flip bits). */
    u8 priority = flags & 0x18; /* bits 4-3 = priority */

    for (i = 0; i < def->count; i++) {
        const MsprPart *p = &def->parts[i];
        s16 px, py;
        u8 part_flags;

        /* Compute position with flip-aware offset swap. */
        if (group_hflip)
            px = x + (s16)(def->width - 8) - (s16)p->ox;
        else
            px = x + (s16)p->ox;

        if (group_vflip)
            py = y + (s16)(def->height - 8) - (s16)p->oy;
        else
            py = y + (s16)p->oy;

        /* Skip parts that are completely off-screen. */
        if (px < -7 || px > 159 || py < -7 || py > 151) {
            ngpc_sprite_hide(spr_start + i);
            continue;
        }

        /* Combine part flags with group flags.
         * Group flip toggles (XOR) the part's own flip. */
        part_flags = p->flags;
        if (group_hflip) part_flags ^= SPR_HFLIP;
        if (group_vflip) part_flags ^= SPR_VFLIP;

        /* Override priority with group priority. */
        part_flags = (part_flags & ~0x18) | priority;

        ngpc_sprite_set(spr_start + i,
                        (u8)((u16)px & 0xFF),
                        (u8)((u16)py & 0xFF),
                        p->tile, p->pal, part_flags);
    }

    return def->count;
}

void ngpc_mspr_hide(u8 spr_start, u8 count)
{
    u8 i;
    for (i = 0; i < count; i++)
        ngpc_sprite_hide(spr_start + i);
}

/* ---- Animation ---- */

void ngpc_mspr_anim_start(MsprAnimator *a, const MsprAnimFrame *anim,
                           u8 count, u8 loop)
{
    a->anim = anim;
    a->frame_count = count;
    a->current = 0;
    a->timer = anim[0].duration;
    a->loop = loop;
}

const NgpcMetasprite *ngpc_mspr_anim_update(MsprAnimator *a)
{
    if (a->timer > 0)
        a->timer--;

    if (a->timer == 0) {
        /* Advance to next frame. */
        if (a->current < a->frame_count - 1) {
            a->current++;
            a->timer = a->anim[a->current].duration;
        } else if (a->loop) {
            a->current = 0;
            a->timer = a->anim[0].duration;
        }
        /* If not looping and at last frame, timer stays 0 (done). */
    }

    return a->anim[a->current].frame;
}

u8 ngpc_mspr_anim_done(const MsprAnimator *a)
{
    return (!a->loop && a->current >= a->frame_count - 1 && a->timer == 0)
           ? 1 : 0;
}
