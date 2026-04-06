/*
 * ngpc_raster_chain.h - CPU raster splits without MicroDMA
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Pattern from Sonic disassembly §2.2-2.3:
 *   Instead of a 152-entry table streamed by MicroDMA, Sonic uses
 *   Timer0 IRQs with dynamic TREG0 reprogramming to fire exactly at
 *   specific scanlines, writes 1-2 video registers per IRQ, then
 *   chains to the next handler.
 *
 * Advantage over ngpc_dma_raster:
 *   - VBlank ISR always runs normally → watchdog always fed → no power-off risk
 *   - No MicroDMA required → works even if DMA is not yet validated
 *   - Lower RAM: no 152-byte scroll table
 *
 * Advantage over ngpc_raster (scroll-table mode):
 *   - Only fires at the N split scanlines, not at all 152 HBlanks
 *   - Lower CPU overhead for simple split screens (2-4 splits)
 *
 * Limitation:
 *   - Maximum RCHAIN_MAX_SPLITS splits per frame
 *   - Accuracy ±1 scanline (TREG0 latency after TRUN restart)
 *   - Writes all 4 scroll registers (SCR1_X/Y and SCR2_X/Y) at each split
 *
 * RESOURCE CONFLICT: shares Timer0 with ngpc_raster, ngpc_dma_raster,
 *   and ngpc_sprmux. Use only one at a time.
 *
 * Usage:
 *   static const RasterSplit splits[] = {
 *       { 0,   0, 0,  0, 0  },  // line 0 : scroll baseline
 *       { 64,  8, 0,  4, 0  },  // line 64: background slower
 *       { 128, 0, 0,  0, 0  },  // line 128: HUD, no scroll
 *   };
 *
 *   // in VBlank handler:
 *   ngpc_rchain_arm(splits, 3);
 */

#ifndef NGPC_RASTER_CHAIN_H
#define NGPC_RASTER_CHAIN_H

#include "../../src/core/ngpc_types.h"

/* Maximum splits (scanline breakpoints) per frame. */
#define RCHAIN_MAX_SPLITS  8

/* One scanline split: at scanline 'line', write the given scroll values. */
typedef struct {
    u8 line;    /* Scanline to trigger on (0-151). */
    u8 scr1x;   /* SCR1 horizontal scroll offset.  */
    u8 scr1y;   /* SCR1 vertical scroll offset.    */
    u8 scr2x;   /* SCR2 horizontal scroll offset.  */
    u8 scr2y;   /* SCR2 vertical scroll offset.    */
} RChainSplit;

/* Initialize the raster chain system (no Timer0 started yet). */
void ngpc_rchain_init(void);

/* Arm the raster chain for the upcoming frame.
 * splits : array of RChainSplit, sorted by ascending 'line'.
 * count  : number of entries (clamped to RCHAIN_MAX_SPLITS).
 * CALL FROM YOUR VBLANK HANDLER, as early as possible.
 * The splits[] array must remain valid until the next arm() call. */
void ngpc_rchain_arm(const RChainSplit *splits, u8 count);

/* Stop Timer0 and clear the chain ISR.
 * Call when switching to a scene that does not need raster effects. */
void ngpc_rchain_disarm(void);

#endif /* NGPC_RASTER_CHAIN_H */
