/*
 * dma_example.c - MicroDMA usage examples (raster-style effects)
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * This file is documentation-by-example and is not compiled by default.
 *
 * MicroDMA in this template is meant for "table -> fixed register" streaming:
 * - It is great for per-scanline register updates (scroll offsets, etc.)
 * - It is NOT a bulk VRAM memcpy feature (no dst++)
 *
 * Hardware rules recap:
 * - Do NOT use VBlank (0x0B) as a MicroDMA start vector (watchdog => power off).
 * - MicroDMA is one-shot: re-arm every frame, as early as possible during VBlank.
 * - If two channels share the same start vector, they run in CHAIN (CH0 then CH1).
 *   To run two streams "in parallel", use two different start vectors (Timer0 + Timer1).
 */

#include "../src/core/ngpc_hw.h"
#include "../src/core/ngpc_sys.h"
#include "../src/core/ngpc_timing.h"
#include "../src/fx/ngpc_dma.h"

/* Example 1: single stream on Timer0/HBlank.
 * Updates HW_SCR1_OFS_X once per scanline (152 bytes per frame). */
void example_dma_scr1_x_timer0(void)
{
    static u8 scr1_x[152];
    static NgpcDmaHblankStream s_x;
    u16 i;

    /* Build a small sawtooth table (0..31 repeating). */
    for (i = 0; i < 152; i++) {
        scr1_x[i] = (u8)(i & 31u);
    }

    ngpc_dma_init();
    ngpc_dma_timer0_hblank_enable();
    ngpc_dma_hblank_stream_begin(&s_x, NGPC_DMA_CH0, &HW_SCR1_OFS_X, scr1_x, 152u);

    for (;;) {
        ngpc_vsync();
        /* IMPORTANT: re-arm early in VBlank (right after ngpc_vsync()). */
        ngpc_dma_hblank_stream_rearm(&s_x);
    }
}

/* Example 2: dual stream without CHAIN using Timer0 + Timer1.
 *
 * - Timer0 clock = TI0 (HBlank) => start vector 0x10
 * - Timer1 clock = TO0TRG (Timer0 overflow) => start vector 0x11
 *
 * Updates SCR1 X and SCR1 Y in the same frame without CPU HBlank ISR. */
void example_dma_scr1_xy_timer01(void)
{
    static u8 scr1_x[152];
    static u8 scr1_y[152];
    static NgpcDmaU8Stream s_x;
    static NgpcDmaU8Stream s_y;
    u16 i;

    for (i = 0; i < 152; i++) {
        scr1_x[i] = (u8)(i & 31u);
        scr1_y[i] = (u8)((i * 2u) & 31u);
    }

    ngpc_dma_init();
    ngpc_dma_timer01_hblank_enable();

    ngpc_dma_stream_begin_u8(&s_x, NGPC_DMA_CH0, &HW_SCR1_OFS_X, scr1_x, 152u, NGPC_DMA_VEC_TIMER0);
    ngpc_dma_stream_begin_u8(&s_y, NGPC_DMA_CH1, &HW_SCR1_OFS_Y, scr1_y, 152u, NGPC_DMA_VEC_TIMER1);

    for (;;) {
        ngpc_vsync();
        ngpc_dma_stream_rearm_u8(&s_x);
        ngpc_dma_stream_rearm_u8(&s_y);
    }
}

