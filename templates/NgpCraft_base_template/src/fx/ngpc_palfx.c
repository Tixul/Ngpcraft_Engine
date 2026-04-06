/*
 * ngpc_palfx.c - Palette effects
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Fade algorithm: interpolates each R/G/B channel (4-bit, 0-15) independently.
 * Each step moves one unit toward the target per channel.
 * At speed=1, a full 0->15 transition takes 15 frames (~0.25s).
 */

#include "ngpc_hw.h"
#include "ngpc_gfx.h"
#include "ngpc_palfx.h"

/* ---- Internal state ---- */

typedef struct {
    u8  type;           /* PALFX_NONE / FADE / CYCLE / FLASH */
    u8  plane;          /* GFX_SCR1 / GFX_SCR2 / GFX_SPR */
    u8  pal_id;         /* Palette number */
    u8  speed;          /* Frames per step */
    u8  timer;          /* Countdown to next step */
    u8  remaining;      /* Steps / frames remaining */
    u16 original[4];    /* Saved original colors */
    u16 target[4];      /* Target colors (fade) */
    u16 current[4];     /* Current interpolated colors */
} PalfxSlot;

static PalfxSlot s_slots[PALFX_MAX_SLOTS];

/* ---- Helpers ---- */

/* Extract R/G/B channels from a 12-bit color. */
#define COLOR_R(c) ((c) & 0xF)
#define COLOR_G(c) (((c) >> 4) & 0xF)
#define COLOR_B(c) (((c) >> 8) & 0xF)

/* Read current palette from hardware. */
static void read_palette(u8 plane, u8 pal_id, u16 *out)
{
    volatile u16 *base;
    u16 off;

    if (plane == GFX_SPR)       base = HW_PAL_SPR;
    else if (plane == GFX_SCR1) base = HW_PAL_SCR1;
    else                        base = HW_PAL_SCR2;

    off = (u16)pal_id * 4;
    out[0] = base[off + 0];
    out[1] = base[off + 1];
    out[2] = base[off + 2];
    out[3] = base[off + 3];
}

/* Write palette to hardware. */
static void write_palette(u8 plane, u8 pal_id, const u16 *colors)
{
    ngpc_gfx_set_palette(plane, pal_id,
                         colors[0], colors[1], colors[2], colors[3]);
}

/* Allocate a free slot. */
static u8 alloc_slot(void)
{
    u8 i;
    for (i = 0; i < PALFX_MAX_SLOTS; i++) {
        if (s_slots[i].type == PALFX_NONE)
            return i;
    }
    return 0xFF;
}

/* Step one channel toward target. */
static u8 step_channel(u16 cur, u16 tgt)
{
    if (cur < tgt) return (u8)(cur + 1);
    if (cur > tgt) return (u8)(cur - 1);
    return (u8)cur;
}

/* Interpolate one color one step toward target. */
static u16 step_color(u16 cur, u16 tgt)
{
    u8 r = step_channel(COLOR_R(cur), COLOR_R(tgt));
    u8 g = step_channel(COLOR_G(cur), COLOR_G(tgt));
    u8 b = step_channel(COLOR_B(cur), COLOR_B(tgt));
    return (u16)r | ((u16)g << 4) | ((u16)b << 8);
}

/* Check if two colors are equal. */
static u8 color_eq(u16 a, u16 b)
{
    return ((a & 0xFFF) == (b & 0xFFF)) ? 1 : 0;
}

/* ---- Update routines per effect type ---- */

static void update_fade(PalfxSlot *s)
{
    u8 i, done;

    s->timer--;
    if (s->timer > 0) return;
    s->timer = s->speed;

    /* Step each color channel. */
    done = 1;
    for (i = 0; i < 4; i++) {
        s->current[i] = step_color(s->current[i], s->target[i]);
        if (!color_eq(s->current[i], s->target[i]))
            done = 0;
    }

    write_palette(s->plane, s->pal_id, s->current);

    if (done)
        s->type = PALFX_NONE;
}

static void update_cycle(PalfxSlot *s)
{
    u16 tmp;

    s->timer--;
    if (s->timer > 0) return;
    s->timer = s->speed;

    /* Rotate colors 1 -> 2 -> 3 -> 1. Color 0 untouched. */
    tmp = s->current[1];
    s->current[1] = s->current[2];
    s->current[2] = s->current[3];
    s->current[3] = tmp;

    write_palette(s->plane, s->pal_id, s->current);
}

static void update_flash(PalfxSlot *s)
{
    s->remaining--;
    if (s->remaining == 0) {
        /* Restore original palette. */
        write_palette(s->plane, s->pal_id, s->original);
        s->type = PALFX_NONE;
    }
}

/* ---- Public API ---- */

u8 ngpc_palfx_fade(u8 plane, u8 pal_id, const u16 *target, u8 speed)
{
    u8 slot = alloc_slot();
    PalfxSlot *s;
    u8 i;

    if (slot == 0xFF) return 0xFF;

    s = &s_slots[slot];
    s->type   = PALFX_FADE;
    s->plane  = plane;
    s->pal_id = pal_id;
    s->speed  = (speed > 0) ? speed : 1; /* speed=0 interdit : min 1 */
    s->timer  = 1; /* start immediately */

    read_palette(plane, pal_id, s->original);
    for (i = 0; i < 4; i++) {
        s->current[i] = s->original[i];
        s->target[i]  = target[i];
    }

    return slot;
}

u8 ngpc_palfx_fade_to_black(u8 plane, u8 pal_id, u8 speed)
{
    static const u16 black[4] = { 0, 0, 0, 0 };
    return ngpc_palfx_fade(plane, pal_id, black, speed);
}

u8 ngpc_palfx_fade_to_white(u8 plane, u8 pal_id, u8 speed)
{
    static const u16 white[4] = { 0x0FFF, 0x0FFF, 0x0FFF, 0x0FFF };
    return ngpc_palfx_fade(plane, pal_id, white, speed);
}

u8 ngpc_palfx_cycle(u8 plane, u8 pal_id, u8 speed)
{
    u8 slot = alloc_slot();
    PalfxSlot *s;

    if (slot == 0xFF) return 0xFF;

    s = &s_slots[slot];
    s->type   = PALFX_CYCLE;
    s->plane  = plane;
    s->pal_id = pal_id;
    s->speed  = (speed > 0) ? speed : 1; /* speed=0 interdit : min 1 */
    s->timer  = s->speed;

    read_palette(plane, pal_id, s->original);
    read_palette(plane, pal_id, s->current);

    return slot;
}

u8 ngpc_palfx_flash(u8 plane, u8 pal_id, u16 color, u8 duration)
{
    u8 slot = alloc_slot();
    PalfxSlot *s;
    u16 flash_pal[4];

    if (slot == 0xFF) return 0xFF;

    if (duration == 0) {
        /* duration=0 : rien à faire, pas de flash */
        return 0xFF;
    }

    s = &s_slots[slot];
    s->type      = PALFX_FLASH;
    s->plane     = plane;
    s->pal_id    = pal_id;
    s->remaining = duration;

    read_palette(plane, pal_id, s->original);

    /* Set all 4 entries to the flash color. */
    flash_pal[0] = color;
    flash_pal[1] = color;
    flash_pal[2] = color;
    flash_pal[3] = color;
    write_palette(plane, pal_id, flash_pal);

    return slot;
}

void ngpc_palfx_update(void)
{
    u8 i;
    for (i = 0; i < PALFX_MAX_SLOTS; i++) {
        switch (s_slots[i].type) {
        case PALFX_FADE:  update_fade(&s_slots[i]);  break;
        case PALFX_CYCLE: update_cycle(&s_slots[i]); break;
        case PALFX_FLASH: update_flash(&s_slots[i]); break;
        default: break;
        }
    }
}

u8 ngpc_palfx_active(u8 slot)
{
    if (slot >= PALFX_MAX_SLOTS) return 0;
    return (s_slots[slot].type != PALFX_NONE) ? 1 : 0;
}

void ngpc_palfx_stop(u8 slot)
{
    if (slot >= PALFX_MAX_SLOTS) return;
    if (s_slots[slot].type != PALFX_NONE) {
        write_palette(s_slots[slot].plane,
                      s_slots[slot].pal_id,
                      s_slots[slot].original);
        s_slots[slot].type = PALFX_NONE;
    }
}

void ngpc_palfx_stop_all(void)
{
    u8 i;
    for (i = 0; i < PALFX_MAX_SLOTS; i++)
        ngpc_palfx_stop(i);
}
