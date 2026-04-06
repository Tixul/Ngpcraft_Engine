/* ngpc_dma_raster.c - Raster effects using MicroDMA (no CPU HBlank ISR)
 *
 * Part of NgpCraft_base_template (MIT License)
 */

#include "ngpc_hw.h"
#include "ngpc_dma_raster.h"

static volatile u8 NGP_FAR *plane_reg_x(u8 plane)
{
    if (plane == GFX_SCR2)
        return (volatile u8 NGP_FAR *)&HW_SCR2_OFS_X;
    return (volatile u8 NGP_FAR *)&HW_SCR1_OFS_X;
}

static volatile u8 NGP_FAR *plane_reg_y(u8 plane)
{
    if (plane == GFX_SCR2)
        return (volatile u8 NGP_FAR *)&HW_SCR2_OFS_Y;
    return (volatile u8 NGP_FAR *)&HW_SCR1_OFS_Y;
}

void ngpc_dma_raster_begin(NgpcDmaRaster *r,
                           u8 plane,
                           const u8 NGP_FAR *table_x,
                           const u8 NGP_FAR *table_y)
{
    ngpc_dma_raster_begin_ex(r, plane, NGPC_DMA_CH0, table_x, NGPC_DMA_CH1, table_y);
}

void ngpc_dma_raster_begin_ex(NgpcDmaRaster *r,
                              u8 plane,
                              u8 ch_x,
                              const u8 NGP_FAR *table_x,
                              u8 ch_y,
                              const u8 NGP_FAR *table_y)
{
    volatile u8 NGP_FAR *reg_x;
    volatile u8 NGP_FAR *reg_y;

    if (!r) return;

    r->plane = plane;
    r->enabled = 0;
    r->table_x = table_x;
    r->table_y = table_y;

    reg_x = plane_reg_x(plane);
    reg_y = plane_reg_y(plane);

    /* Default mapping:
     * - X uses Timer0 (0x10)
     * - Y uses Timer1 (0x11) when both exist, else Timer0 (0x10) */
    if (table_x) {
        ngpc_dma_stream_begin_u8(&r->stream_x, ch_x, reg_x, table_x, (u16)SCREEN_H, NGPC_DMA_VEC_TIMER0);
    } else if (table_y) {
        /* Y-only: use the X stream slot so we still run with Timer0. */
        ngpc_dma_stream_begin_u8(&r->stream_x, ch_x, reg_y, table_y, (u16)SCREEN_H, NGPC_DMA_VEC_TIMER0);
    } else {
        ngpc_dma_stream_begin_u8(&r->stream_x, ch_x, reg_x, (const u8 NGP_FAR *)0, 0, 0);
    }

    if (table_x && table_y) {
        ngpc_dma_stream_begin_u8(&r->stream_y, ch_y, reg_y, table_y, (u16)SCREEN_H, NGPC_DMA_VEC_TIMER1);
    } else {
        ngpc_dma_stream_begin_u8(&r->stream_y, ch_y, reg_y, (const u8 NGP_FAR *)0, 0, 0);
    }
}

void ngpc_dma_raster_enable(NgpcDmaRaster *r)
{
    if (!r) return;

    r->enabled = 0;

    if (!r->table_x && !r->table_y) {
        return;
    }

    /* X+Y uses Timer0+Timer1 to avoid CHAIN.
     * X-only uses Timer0.
     * Y-only uses Timer0 (Timer1 depends on Timer0 anyway). */
    if (r->table_x && r->table_y) {
        ngpc_dma_timer01_hblank_enable();
    } else {
        ngpc_dma_timer0_hblank_enable();
    }

    r->enabled = 1;
}

void ngpc_dma_raster_rearm(const NgpcDmaRaster *r)
{
    if (!r) return;
    if (!r->enabled) return;

    /* Call early during VBlank so the first visible lines are not missed. */
    if (r->table_x) {
        ngpc_dma_stream_rearm_u8(&r->stream_x);
        if (r->table_y)
            ngpc_dma_stream_rearm_u8(&r->stream_y);
    } else if (r->table_y) {
        /* Y-only mapped to stream_x. */
        ngpc_dma_stream_rearm_u8(&r->stream_x);
    }
}

void ngpc_dma_raster_disable(NgpcDmaRaster *r)
{
    if (!r) return;

    if (r->enabled) {
        ngpc_dma_stop(r->stream_x.channel);
        if (r->table_x && r->table_y) {
            ngpc_dma_stop(r->stream_y.channel);
            ngpc_dma_timer01_hblank_disable();
        } else {
            ngpc_dma_timer0_hblank_disable();
        }
    }

    r->enabled = 0;
}

void ngpc_dma_raster_build_parallax_table(u8 *out_table,
                                         const RasterBand *bands,
                                         u8 count,
                                         u16 base_x)
{
    u8 i;
    u8 line;

    if (!out_table) return;
    if (!bands || count == 0) {
        /* Default: no parallax (0). */
        for (line = 0; line < (u8)SCREEN_H; line++)
            out_table[line] = 0;
        return;
    }

    /* Fill the 152-line buffer with per-band scroll values. */
    for (i = 0; i < count; i++) {
        u8 start = bands[i].top_line;
        u8 end = (u8)((i + 1 < count) ? bands[i + 1].top_line : (u8)SCREEN_H);

        /* scroll_x = (base_x * speed) >> 8 */
        u8 sx = (u8)(((u32)base_x * (u32)bands[i].speed) >> 8);

        for (line = start; line < end; line++)
            out_table[line] = sx;
    }
}

void ngpc_dma_raster_xy_begin(NgpcDmaRasterXY *r,
                              u8 plane,
                              const u16 NGP_FAR *table_xy)
{
    ngpc_dma_raster_xy_begin_ex(r, plane, NGPC_DMA_CH0, table_xy);
}

void ngpc_dma_raster_xy_begin_ex(NgpcDmaRasterXY *r,
                                 u8 plane,
                                 u8 channel,
                                 const u16 NGP_FAR *table_xy)
{
    volatile u8 NGP_FAR *reg_xy;

    if (!r) return;

    r->plane = plane;
    r->enabled = 0;
    r->table_xy = table_xy;

    reg_xy = plane_reg_x(plane);

    if (table_xy) {
        ngpc_dma_stream_begin_u16(&r->stream_xy, channel, reg_xy, table_xy, (u16)SCREEN_H, NGPC_DMA_VEC_TIMER0);
    } else {
        ngpc_dma_stream_begin_u16(&r->stream_xy, channel, reg_xy, (const u16 NGP_FAR *)0, 0, 0);
    }
}

void ngpc_dma_raster_xy_enable(NgpcDmaRasterXY *r)
{
    if (!r) return;

    r->enabled = 0;

    if (!r->table_xy) {
        return;
    }

    /* Single channel, Timer0 only (no CHAIN concerns). */
    ngpc_dma_timer0_hblank_enable();
    r->enabled = 1;
}

void ngpc_dma_raster_xy_rearm(const NgpcDmaRasterXY *r)
{
    if (!r) return;
    if (!r->enabled) return;

    ngpc_dma_stream_rearm_u16(&r->stream_xy);
}

void ngpc_dma_raster_xy_disable(NgpcDmaRasterXY *r)
{
    if (!r) return;

    if (r->enabled) {
        ngpc_dma_stop(r->stream_xy.channel);
        ngpc_dma_timer0_hblank_disable();
    }

    r->enabled = 0;
}

void ngpc_dma_raster_build_parallax_table_xy(u16 *out_table_xy,
                                             const RasterBand *bands,
                                             u8 count,
                                             u16 base_x,
                                             u8 y)
{
    u8 i;
    u8 line;

    if (!out_table_xy) return;

    if (!bands || count == 0) {
        /* Default: no parallax (0). */
        for (line = 0; line < (u8)SCREEN_H; line++)
            out_table_xy[line] = (u16)(((u16)y << 8) | 0);
        return;
    }

    /* Fill the 152-line buffer with per-band scroll values. */
    for (i = 0; i < count; i++) {
        u8 start = bands[i].top_line;
        u8 end = (u8)((i + 1 < count) ? bands[i + 1].top_line : (u8)SCREEN_H);

        /* scroll_x = (base_x * speed) >> 8 */
        u8 sx = (u8)(((u32)base_x * (u32)bands[i].speed) >> 8);
        u16 packed = (u16)(((u16)y << 8) | sx);

        for (line = start; line < end; line++)
            out_table_xy[line] = packed;
    }
}
