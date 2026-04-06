/*
 * ngpc_input.c - Joypad input with edge detection
 *
 * Part of NgpCraft_base_template (MIT License)
 * Written from hardware specification (ngpcspec.txt).
 *
 * The template uses joypad bits as read from HW_JOYPAD, with the
 * convention 1 = pressed for public PAD_* masks and edge detection.
 */

#include "ngpc_hw.h"
#include "ngpc_input.h"

/* ---- State ---- */

u8 ngpc_pad_held     = 0;
u8 ngpc_pad_pressed  = 0;
u8 ngpc_pad_released = 0;
u8 ngpc_pad_repeat   = 0;

static u8 s_pad_prev = 0;
static u8 s_repeat_delay = 15;
static u8 s_repeat_rate  = 4;
static u8 s_repeat_timer[8];

void ngpc_input_set_repeat(u8 delay, u8 rate)
{
    s_repeat_delay = delay;
    s_repeat_rate  = rate;
}

/* ---- Public API ---- */

void ngpc_input_update(void)
{
    u8 i;
    u8 mask;
    u8 raw;

    /* Read joypad register.
     * ngpcspec.txt: 0x6F82 "Sys Lever" - button state.
     * Bits: 7=POWER 6=OPTION 5=B 4=A 3=RIGHT 2=LEFT 1=DOWN 0=UP */
    raw = HW_JOYPAD;

    ngpc_pad_held     = raw;
    ngpc_pad_pressed  = raw & ~s_pad_prev;   /* newly pressed  */
    ngpc_pad_released = ~raw & s_pad_prev;   /* newly released */
    ngpc_pad_repeat   = 0;

    mask = 1;
    for (i = 0; i < 8; ++i) {
        if (raw & mask) {
            if (ngpc_pad_pressed & mask) {
                s_repeat_timer[i] = s_repeat_delay;
            } else {
                if (s_repeat_timer[i] > 0) {
                    --s_repeat_timer[i];
                } else {
                    ngpc_pad_repeat |= mask;
                    s_repeat_timer[i] = s_repeat_rate;
                }
            }
        } else {
            s_repeat_timer[i] = 0;
        }
        mask <<= 1;
    }

    s_pad_prev = raw;
}
