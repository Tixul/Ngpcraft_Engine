/*
 * ngpc_debug.c - CPU profiler and debug overlay
 *
 * Part of NgpCraft_base_template (MIT License)
 * Written from hardware specification (ngpcspec.txt).
 *
 * Uses HW_RAS_V (0x8009) to read the current vertical raster position.
 * The visible area is 152 lines (0-151), then VBlank (~46 lines).
 * Total ~198 lines per frame at 60 Hz.
 *
 * Active display budget: 152 scanlines.
 * If game logic uses more than 152 lines, it's overflowing into VBlank.
 */

#include "ngpc_hw.h"
#include "ngpc_gfx.h"
#include "ngpc_text.h"
#include "ngpc_debug.h"

#if NGPC_DEBUG

/* ---- State ---- */

static u8 s_start_line;    /* Raster line at begin() */
static u8 s_used_lines;    /* Lines consumed last frame */
static u8 s_pct;           /* Percentage of frame budget used */
static u8 s_frame_count;   /* Frames counted this second */
static u8 s_fps;           /* FPS from last second */
static u8 s_fps_timer;     /* VBlank counter for FPS calculation */

/* Budget: visible area = 152 lines. */
#define FRAME_BUDGET 152

/* ---- Public API ---- */

void ngpc_debug_begin(void)
{
    s_start_line = HW_RAS_V;
}

void ngpc_debug_end(void)
{
    u8 end_line = HW_RAS_V;

    /* Handle wrap-around (if begin was in VBlank, end in active). */
    if (end_line >= s_start_line)
        s_used_lines = end_line - s_start_line;
    else
        s_used_lines = (198 - s_start_line) + end_line;

    /* Calculate percentage: (lines / 152) * 100 */
    s_pct = (u8)(((u16)s_used_lines * 100) / FRAME_BUDGET);

    /* FPS counter: count frames over 60 VBlanks (= 1 second). */
    s_frame_count++;
    s_fps_timer++;
    if (s_fps_timer >= 60) {
        s_fps = s_frame_count;
        s_frame_count = 0;
        s_fps_timer = 0;
    }
}

void ngpc_debug_draw_bar(u8 plane, u8 pal_ok, u8 pal_warn, u8 pal_over)
{
    /*
     * Draw a bar on the bottom tile row (y=18) of the screen.
     * Bar length = (used_lines / 152) * 20 tiles.
     * Color depends on usage: green < 80%, yellow 80-100%, red > 100%.
     */
    u8 bar_len;
    u8 pal;
    u8 i;
    u16 solid_tile = 0; /* Use tile 0 as solid block (or any filled tile) */

    /* Calculate bar length in tiles (0-20). */
    bar_len = (u8)(((u16)s_used_lines * SCREEN_TW) / FRAME_BUDGET);
    if (bar_len > SCREEN_TW) bar_len = SCREEN_TW;

    /* Choose color based on budget usage. */
    if (s_pct > 100)
        pal = pal_over;     /* red: overflowed */
    else if (s_pct > 80)
        pal = pal_warn;     /* yellow: tight */
    else
        pal = pal_ok;       /* green: OK */

    /* Draw the bar. */
    for (i = 0; i < SCREEN_TW; i++) {
        if (i < bar_len)
            ngpc_gfx_put_tile(plane, i, SCREEN_TH - 1, solid_tile, pal);
        else
            ngpc_gfx_put_tile(plane, i, SCREEN_TH - 1, 0, 0); /* clear */
    }
}

void ngpc_debug_print_pct(u8 plane, u8 pal, u8 x, u8 y)
{
    /* Print "XX%" using text functions. */
    ngpc_text_print_num(plane, pal, x, y, (u16)s_pct, 3);
    ngpc_text_print(plane, pal, x + 3, y, "%");
}

void ngpc_debug_print_fps(u8 plane, u8 pal, u8 x, u8 y)
{
    ngpc_text_print_num(plane, pal, x, y, (u16)s_fps, 2);
    ngpc_text_print(plane, pal, x + 2, y, "FPS");
}

u8 ngpc_debug_get_lines(void)
{
    return s_used_lines;
}

u8 ngpc_debug_get_pct(void)
{
    return s_pct;
}

#endif /* NGPC_DEBUG */
