/* ngpc_dma_raster.h - Raster effects using MicroDMA (no CPU HBlank ISR)
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * This module is a high-level wrapper on top of `ngpc_dma` for the most common
 * use-case on NGPC: per-scanline scroll tables.
 *
 * Compared to `ngpc_raster`:
 * - `ngpc_raster` uses a CPU HBlank interrupt handler (fast but time-budgeted).
 * - `ngpc_dma_raster` uses MicroDMA to write the scroll registers each scanline,
 *   so the CPU does not run code during HBlank (more CPU time for gameplay).
 *
 * Constraints / rules:
 * - Tables should live in RAM.
 * - MicroDMA is one-shot: call `ngpc_dma_raster_rearm()` once per frame during
 *   VBlank, as early as possible (right after `ngpc_vsync()`).
 * - Uses Timer0 (HBlank) and optionally Timer1 (Timer0 overflow). Timer0 is a
 *   shared resource with `ngpc_raster` (mutually exclusive).
 *   With `ngpc_sprmux`, you can coexist by running sprmux on Timer1 (CPU ISR)
 *   while MicroDMA uses Timer0 as its trigger (i.e. use X-only DMA raster, or
 *   otherwise ensure Timer1 is not used as a MicroDMA start vector).
 */
 
#ifndef NGPC_DMA_RASTER_H
#define NGPC_DMA_RASTER_H

#include "ngpc_types.h"
#include "ngpc_gfx.h"     /* GFX_SCR1, GFX_SCR2 */
#include "ngpc_dma.h"     /* NgpcDmaU8Stream/NgpcDmaU16Stream, timer helpers */
#include "ngpc_raster.h"  /* RasterBand (speed bands helper) */

typedef struct {
    u8 plane; /* GFX_SCR1 or GFX_SCR2 */
    u8 enabled;

    /* Tables (typically in RAM). Any can be NULL. */
    const u8 NGP_FAR *table_x;
    const u8 NGP_FAR *table_y;

    /* Internal DMA streams (CH0/CH1 by default). */
    NgpcDmaU8Stream stream_x;
    NgpcDmaU8Stream stream_y;
} NgpcDmaRaster;

/* Variant: single-channel word table that updates X+Y together.
 *
 * This is closer to how some commercial games do it (Ganbare Neo Poke-kun):
 * - One MicroDMA channel
 * - Timer0 (HBlank) as the only trigger
 * - Word mode writes dst_reg (X) + dst_reg+1 (Y) each scanline */
typedef struct {
    u8 plane; /* GFX_SCR1 or GFX_SCR2 */
    u8 enabled;

    /* Table in RAM, 152 entries. Pack as (Y<<8) | X. */
    const u16 NGP_FAR *table_xy;

    /* Internal DMA stream (CH0 by default). */
    NgpcDmaU16Stream stream_xy;
} NgpcDmaRasterXY;

/* Configure tables and plane. Does not start timers or DMA. */
void ngpc_dma_raster_begin(NgpcDmaRaster *r,
                           u8 plane,
                           const u8 NGP_FAR *table_x,
                           const u8 NGP_FAR *table_y);

/* Same as begin(), but lets you choose channels (advanced use). */
void ngpc_dma_raster_begin_ex(NgpcDmaRaster *r,
                              u8 plane,
                              u8 ch_x,
                              const u8 NGP_FAR *table_x,
                              u8 ch_y,
                              const u8 NGP_FAR *table_y);

/* Enable timers and arm base configuration (does not re-arm the one-shot counters). */
void ngpc_dma_raster_enable(NgpcDmaRaster *r);

/* Call once per frame during VBlank, as early as possible. */
void ngpc_dma_raster_rearm(const NgpcDmaRaster *r);

/* Stop DMA channels and disable timers used by this module. */
void ngpc_dma_raster_disable(NgpcDmaRaster *r);

/* Convenience: build a 152-byte parallax table from RasterBands (same model as ngpc_raster_parallax).
 * out_table must point to an array of 152 bytes (RAM recommended).
 * base_x is your camera X (or any scroll base value). */
void ngpc_dma_raster_build_parallax_table(u8 *out_table,
                                         const RasterBand *bands,
                                         u8 count,
                                         u16 base_x);

/* ---- Word XY variant (1 channel, Timer0 only) ---- */

/* Configure XY table and plane. Does not start timers or DMA. */
void ngpc_dma_raster_xy_begin(NgpcDmaRasterXY *r,
                              u8 plane,
                              const u16 NGP_FAR *table_xy);

/* Same as begin(), but lets you choose the channel (advanced use). */
void ngpc_dma_raster_xy_begin_ex(NgpcDmaRasterXY *r,
                                 u8 plane,
                                 u8 channel,
                                 const u16 NGP_FAR *table_xy);

/* Enable Timer0 and arm base configuration (does not re-arm the one-shot counter). */
void ngpc_dma_raster_xy_enable(NgpcDmaRasterXY *r);

/* Call once per frame during VBlank, as early as possible. */
void ngpc_dma_raster_xy_rearm(const NgpcDmaRasterXY *r);

/* Stop DMA channel and disable Timer0 used by this module. */
void ngpc_dma_raster_xy_disable(NgpcDmaRasterXY *r);

/* Convenience: build a 152-entry packed XY table (Y constant).
 * out_table_xy must point to an array of 152 u16 entries (RAM recommended).
 * Each entry is packed as (Y<<8) | X. */
void ngpc_dma_raster_build_parallax_table_xy(u16 *out_table_xy,
                                             const RasterBand *bands,
                                             u8 count,
                                             u16 base_x,
                                             u8 y);

#endif /* NGPC_DMA_RASTER_H */
