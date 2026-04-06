/*
 * ngpc_assert.c - Runtime assert helper for debug builds
 *
 * Part of NgpCraft_base_template (MIT License)
 */

#include "ngpc_hw.h"
#include "ngpc_gfx.h"
#include "ngpc_text.h"
#include "ngpc_assert.h"

#if NGP_PROFILE_RELEASE || !NGP_ENABLE_DEBUG

void ngpc_assert_fail(const char *file, u16 line)
{
    (void)file;
    (void)line;
}

#else

static const char *basename(const char *path)
{
    const char *p = path;
    const char *last = path;

    while (p && *p) {
        if (*p == '/' || *p == '\\')
            last = p + 1;
        p++;
    }
    return last;
}

static void copy_name(char *dst, const char *src, u8 max)
{
    u8 i;
    for (i = 0; i < max; i++) {
        char c = src[i];
        if (!c) {
            break;
        }
        if ((u8)c < 0x20 || (u8)c > 0x7E)
            c = '?';
        dst[i] = c;
    }
    while (i < max) {
        dst[i++] = 0;
    }
}

void ngpc_assert_fail(const char *file, u16 line)
{
    const char *name = basename(file);
    char short_name[13];
    u8 blink = 0;
    volatile u16 delay;

    copy_name(short_name, name, 12);
    short_name[12] = 0;

    ngpc_gfx_set_viewport(0, 0, SCREEN_W, SCREEN_H);
    ngpc_gfx_scroll(GFX_SCR1, 0, 0);
    ngpc_gfx_set_bg_color(RGB(4, 0, 0));
    ngpc_gfx_set_palette(GFX_SCR1, 0,
        RGB(0, 0, 0), RGB(15, 15, 15), RGB(15, 0, 0), RGB(8, 0, 0));
    ngpc_gfx_fill(GFX_SCR1, ' ', 0);

    ngpc_text_print(GFX_SCR1, 0, 2, 4, "ASSERT FAIL");
    ngpc_text_print(GFX_SCR1, 0, 2, 7, "FILE:");
    ngpc_text_print(GFX_SCR1, 0, 8, 7, short_name);
    ngpc_text_print(GFX_SCR1, 0, 2, 9, "LINE:");
    ngpc_text_print_dec(GFX_SCR1, 0, 8, 9, line, 5);

    while (1) {
        HW_WATCHDOG = WATCHDOG_CLEAR;
        blink ^= 1;
        if (blink)
            ngpc_gfx_set_bg_color(RGB(15, 0, 0));
        else
            ngpc_gfx_set_bg_color(RGB(4, 0, 0));

        for (delay = 0; delay < 18000; delay++) {
            /* busy wait for blink pacing */
        }
    }
}

#endif /* NGP_PROFILE_RELEASE || !NGP_ENABLE_DEBUG */
