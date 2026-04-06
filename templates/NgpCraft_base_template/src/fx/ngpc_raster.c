/*
 * ngpc_raster.c - HBlank raster effects
 *
 * Part of NgpCraft_base_template (MIT License)
 * Written from hardware specification (ngpcspec.txt).
 *
 * Timer 0 on the TLCS-900/H is connected to the HBlank signal.
 * When configured properly, it fires an interrupt at each scanline.
 * We read HW_RAS_V to know which line we're on and apply the effect.
 *
 * Timer 0 setup:
 *   - TRUN bit 0 = enable Timer 0
 *   - T01MOD bits 1-0 = clock source (we use the HBlank signal)
 *   - TREG0 = reload value (1 = fire every HBlank)
 *   - Interrupt vector at 0x6FD4 (HW_INT_TIM0)
 */

#include "ngpc_hw.h"
#include "ngpc_gfx.h"
#include "ngpc_raster.h"

/* ---- State ---- */

/* Scroll table pointers (NULL = not active). */
static const u8 *s_scroll_x;
static const u8 *s_scroll_y;
static u8        s_scroll_plane;

/* Per-line callbacks. */
typedef struct {
    u8              line;
    RasterCallback  cb;
} RasterCbEntry;

static RasterCbEntry s_callbacks[RASTER_MAX_CB];
static u8            s_cb_count;

/* Parallax scroll buffer (filled by ngpc_raster_parallax). */
static u8 s_parallax_buf[152];
static u8 s_parallax_active;

/* ---- HBlank ISR ---- */

static void __interrupt isr_hblank(void)
{
    u8 line = HW_RAS_V;

    /* Safety: only process visible lines. */
    if (line >= 152) return;

    /* Scroll table mode: write scroll registers for this line. */
    if (s_scroll_x || s_scroll_y || s_parallax_active) {
        if (s_parallax_active) {
            if (s_scroll_plane == GFX_SCR1)
                HW_SCR1_OFS_X = s_parallax_buf[line];
            else
                HW_SCR2_OFS_X = s_parallax_buf[line];
        } else {
            if (s_scroll_x) {
                if (s_scroll_plane == GFX_SCR1)
                    HW_SCR1_OFS_X = s_scroll_x[line];
                else
                    HW_SCR2_OFS_X = s_scroll_x[line];
            }
            if (s_scroll_y) {
                if (s_scroll_plane == GFX_SCR1)
                    HW_SCR1_OFS_Y = s_scroll_y[line];
                else
                    HW_SCR2_OFS_Y = s_scroll_y[line];
            }
        }
    }

    /* Callback mode: check if any callback is registered for this line. */
    if (s_cb_count > 0) {
        u8 i;
        for (i = 0; i < s_cb_count; i++) {
            if (s_callbacks[i].line == line)
                s_callbacks[i].cb(line);
        }
    }
}

/* ---- Public API ---- */

void ngpc_raster_init(void)
{
    /* Clear state. */
    s_scroll_x = 0;
    s_scroll_y = 0;
    s_scroll_plane = GFX_SCR1;
    s_cb_count = 0;
    s_parallax_active = 0;

    /* Install HBlank interrupt handler. */
    HW_INT_TIM0 = (IntHandler *)isr_hblank;

    /*
     * Configure Timer 0 for HBlank:
     * - TREG0 = 1 (fire every HBlank)
     * - T01MOD: Timer 0 clock source = internal (bits 1-0)
     * - TRUN bit 0 = 1 (start Timer 0)
     *
     * Note: exact timer configuration may need tuning on real hardware.
     * The HBlank signal is ~32 us per line (6144000 Hz / 192 lines / 60 Hz).
     */
    HW_T01MOD &= (u8)~0xC3; /* Timer0 clock = TI0, 8-bit mode */
    HW_TREG0 = 0x01;
    HW_TRUN |= 0x01;   /* Enable Timer 0 */
}

void ngpc_raster_disable(void)
{
    HW_TRUN &= (u8)~0x01;  /* Stop Timer 0 */
    /* Do not clear HW_INT_TIM0 to zero: a pending interrupt firing after
     * the timer is stopped would jump to address 0 and crash.  The old
     * handler is harmless if it runs one extra time. */

    s_scroll_x = 0;
    s_scroll_y = 0;
    s_cb_count = 0;
    s_parallax_active = 0;
}

void ngpc_raster_set_scroll_table(u8 plane, const u8 *table_x, const u8 *table_y)
{
    s_scroll_plane = plane;
    s_scroll_x = table_x;
    s_scroll_y = table_y;
    s_parallax_active = 0;
}

void ngpc_raster_clear_scroll(void)
{
    s_scroll_x = 0;
    s_scroll_y = 0;
    s_parallax_active = 0;
}

u8 ngpc_raster_set_callback(u8 line, RasterCallback cb)
{
    if (s_cb_count >= RASTER_MAX_CB) return 0xFF;

    s_callbacks[s_cb_count].line = line;
    s_callbacks[s_cb_count].cb   = cb;
    s_cb_count++;

    return s_cb_count - 1;
}

void ngpc_raster_clear_callbacks(void)
{
    s_cb_count = 0;
}

void ngpc_raster_parallax(u8 plane, const RasterBand *bands,
                           u8 count, u16 base_x)
{
    u8 i, line;

    s_scroll_plane = plane;
    s_parallax_active = 1;

    /* Fill the 152-line buffer with per-band scroll values. */
    for (i = 0; i < count; i++) {
        u8 start = bands[i].top_line;
        u8 end   = (i + 1 < count) ? bands[i + 1].top_line : 152;

        /* scroll_x = (base_x * speed) >> 8 */
        u8 sx = (u8)(((u32)base_x * (u32)bands[i].speed) >> 8);

        for (line = start; line < end; line++)
            s_parallax_buf[line] = sx;
    }
}
