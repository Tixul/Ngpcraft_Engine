/*
 * ngpc_winani.c - Animated window/viewport transition
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Pocket Tennis §4: center-symmetric animation.
 *   Open:  W grows 0→160, H grows 0→152. X = (160-W)/2, Y = (152-H)/2.
 *   Close: W shrinks 160→0, H shrinks 152→0. Same centering formula.
 *
 * Each frame: W and H change by (speed * 2) pixels total
 * (speed pixels on each side). X and Y are derived automatically.
 */

#include "ngpc_winani.h"
#include "../../src/core/ngpc_hw.h"

#define WIN_IDLE    0
#define WIN_OPENING 1
#define WIN_CLOSING 2

/* Full-screen dimensions (Pocket Tennis values: 0xA0 / 0x98). */
#define WIN_FULL_W  SCREEN_W   /* 160 */
#define WIN_FULL_H  SCREEN_H   /* 152 */

static u8 s_state;
static u8 s_speed;
static u8 s_w;  /* current window width  (0 = closed, WIN_FULL_W = open) */
static u8 s_h;  /* current window height (0 = closed, WIN_FULL_H = open) */

/* Write current W/H to hardware with center-origin math. */
static void apply_hw(void)
{
    HW_WIN_X = (u8)((WIN_FULL_W - s_w) / 2u);
    HW_WIN_Y = (u8)((WIN_FULL_H - s_h) / 2u);
    HW_WIN_W = s_w;
    HW_WIN_H = s_h;
}

/* ---- Public API ---- */

void ngpc_win_init(void)
{
    s_state = WIN_IDLE;
    s_w = WIN_FULL_W;
    s_h = WIN_FULL_H;
    apply_hw();
}

void ngpc_win_set_full(void)
{
    s_state = WIN_IDLE;
    s_w = WIN_FULL_W;
    s_h = WIN_FULL_H;
    apply_hw();
}

void ngpc_win_set_closed(void)
{
    s_state = WIN_IDLE;
    s_w = 0;
    s_h = 0;
    apply_hw();
}

void ngpc_win_open(u8 speed)
{
    s_state = WIN_OPENING;
    s_speed = speed ? speed : 1u;
}

void ngpc_win_close(u8 speed)
{
    s_state = WIN_CLOSING;
    s_speed = speed ? speed : 1u;
}

u8 ngpc_win_update(void)
{
    u8 step;
    u8 done = 0;

    if (s_state == WIN_IDLE)
        return 1;

    /* Each side expands/contracts by s_speed, so total delta = s_speed * 2.
     * Use a local u8 step clamped to avoid overflow. */
    step = (u8)(s_speed * 2u);

    if (s_state == WIN_OPENING) {
        if (s_w >= (u8)(WIN_FULL_W - step)) {
            s_w = WIN_FULL_W;
        } else {
            s_w = (u8)(s_w + step);
        }

        if (s_h >= (u8)(WIN_FULL_H - step)) {
            s_h = WIN_FULL_H;
        } else {
            s_h = (u8)(s_h + step);
        }

        if (s_w >= WIN_FULL_W && s_h >= WIN_FULL_H) {
            s_state = WIN_IDLE;
            done = 1;
        }

    } else { /* WIN_CLOSING */
        if (s_w <= step) {
            s_w = 0;
        } else {
            s_w = (u8)(s_w - step);
        }

        if (s_h <= step) {
            s_h = 0;
        } else {
            s_h = (u8)(s_h - step);
        }

        if (s_w == 0 && s_h == 0) {
            s_state = WIN_IDLE;
            done = 1;
        }
    }

    apply_hw();
    return done;
}

u8 ngpc_win_busy(void)
{
    return (s_state != WIN_IDLE) ? 1u : 0u;
}
