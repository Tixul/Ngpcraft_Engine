/*
 * ngpc_dma.h - MicroDMA helpers (interrupt-driven table streaming)
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * This module configures TLCS-900/H MicroDMA channels to stream data from
 * memory to a fixed destination register, triggered by an interrupt vector.
 * Typical use case: per-line register updates on HBlank (raster-like effects
 * without heavy ISR code).
 *
 * Notes:
 * - This implementation targets "src++ -> fixed dst" mem->I/O modes:
 *   byte (0x08), word (0x09), dword (0x0A).
 * - Trigger source is selected with a "start vector" value (e.g. HBlank).
 * - Completion interrupts are exposed via callback or poll.
 *
 * Hardware note (NGPC):
 * - Avoid using VBlank as a MicroDMA start vector in production code.
 *   On real hardware it can starve the mandatory VBlank ISR (watchdog => power off).
 *   Prefer Timer0/HBlank or another timer-based trigger.
 */

#ifndef NGPC_DMA_H
#define NGPC_DMA_H

#include "ngpc_types.h"

/* cc900 supports memory qualifiers for pointer displacement: __near/__far.
 * The makefile defines NGP_FAR=__far and NGP_NEAR=__near for cc900 builds.
 * When building with another toolchain, you can leave these undefined. */
#ifndef NGP_FAR
#define NGP_FAR
#endif

/* If set to 0 (default), ngpc_dma will refuse to link MicroDMA to the VBlank
 * start vector to avoid accidentally disabling the mandatory VBlank ISR on
 * real hardware. Define to 1 only if you know exactly what you're doing. */
#ifndef NGP_DMA_ALLOW_VBLANK_TRIGGER
#define NGP_DMA_ALLOW_VBLANK_TRIGGER 0
#endif

/* If set to 1, ngpc_dma installs INTTCn ("End MicroDMA") ISRs that can
 * automatically re-arm channels configured with ngpc_dma_autorearm_*().
 * Default off until validated on your hardware/flashcart setup. */
#ifndef NGP_DMA_INSTALL_REARM_ISR
#define NGP_DMA_INSTALL_REARM_ISR 0
#endif

#define NGPC_DMA_CH0  0
#define NGPC_DMA_CH1  1
#define NGPC_DMA_CH2  2
#define NGPC_DMA_CH3  3

/* Start vector values from ngpcspec interrupt table. */
#define NGPC_DMA_VEC_RTC      0x0A
#define NGPC_DMA_VEC_VBLANK   0x0B
#define NGPC_DMA_VEC_Z80      0x0C
#define NGPC_DMA_VEC_TIMER0   0x10
#define NGPC_DMA_VEC_TIMER1   0x11
#define NGPC_DMA_VEC_TIMER2   0x12
#define NGPC_DMA_VEC_TIMER3   0x13
#define NGPC_DMA_VEC_SER_TX   0x18
#define NGPC_DMA_VEC_SER_RX   0x19

/* Initialize DMA module state.
 * If `NGP_DMA_INSTALL_DONE_ISR=1`, also installs DMA completion ISRs (HW_INT_DMA0..3).
 * Call after ngpc_init(). */
void ngpc_dma_init(void);

/* Program channel as byte stream (src increments, dst fixed register).
 * channel: NGPC_DMA_CH0..CH3
 * dst_reg: destination register address (for example &HW_SCR1_OFS_X)
 * src_table: source bytes in RAM/ROM
 * count: transfer count in bytes
 * start_vector: event vector that triggers each DMA step (0x0A..0x19) */
void ngpc_dma_start_table_u8(u8 channel,
                             volatile u8 NGP_FAR *dst_reg,
                             const u8 NGP_FAR *src_table,
                             u16 count,
                             u8 start_vector);

/* Program channel as word stream (src increments by 2, dst fixed register).
 * dst_reg is the FIRST register address (byte address); the word write will
 * update dst_reg and dst_reg+1 (e.g. SCR2_OFS_X/Y at 0x8034/0x8035).
 * count is the number of 16-bit transfers (not bytes). */
void ngpc_dma_start_table_u16(u8 channel,
                              volatile u8 NGP_FAR *dst_reg,
                              const u16 NGP_FAR *src_table,
                              u16 count,
                              u8 start_vector);

/* Program channel as dword stream (src increments by 4, dst fixed register).
 * dst_reg is the FIRST register address (byte address); the dword write will
 * update dst_reg..dst_reg+3 (e.g. SCR1_OFS_X/Y + SCR2_OFS_X/Y at 0x8032..0x8035).
 * count is the number of 32-bit transfers (not bytes). */
void ngpc_dma_start_table_u32(u8 channel,
                              volatile u8 NGP_FAR *dst_reg,
                              const u32 NGP_FAR *src_table,
                              u16 count,
                              u8 start_vector);

/* Convenience wrappers. */
void ngpc_dma_link_hblank(u8 channel, volatile u8 NGP_FAR *dst_reg,
                          const u8 NGP_FAR *src_table, u16 count);
/* WARNING (hardware): see NGP_DMA_ALLOW_VBLANK_TRIGGER in this header. */
void ngpc_dma_link_vblank(u8 channel, volatile u8 NGP_FAR *dst_reg,
                          const u8 NGP_FAR *src_table, u16 count);

void ngpc_dma_link_hblank_u16(u8 channel, volatile u8 NGP_FAR *dst_reg,
                              const u16 NGP_FAR *src_table, u16 count);
void ngpc_dma_link_hblank_u32(u8 channel, volatile u8 NGP_FAR *dst_reg,
                              const u32 NGP_FAR *src_table, u16 count);

/* ---- Timer helpers (HBlank clock) ----
 *
 * MicroDMA uses interrupt requests as its trigger sources. On NGPC, the most
 * useful source for raster-style effects is Timer0 with clock source TI0
 * (wired to HBlank). These helpers configure the timers but do NOT install
 * any CPU HBlank ISR.
 *
 * Notes:
 * - Timer0 is a shared resource: ngpc_raster and ngpc_sprmux also use it.
 * - Using MicroDMA with start_vector=Timer0 can "steal" the Timer0 IRQ,
 *   which is good (no CPU ISR cost) but incompatible with sprmux/raster.
 * - To run two MicroDMA channels without CHAIN, you can use Timer1 as a
 *   second start vector (Timer1 clock = TO0TRG, i.e. Timer0 overflow).
 */

/* Configure and start Timer0 in TI0(HBlank) mode (fire each scanline). */
void ngpc_dma_timer0_hblank_enable(void);
/* Same as ngpc_dma_timer0_hblank_enable(), but with a custom interval.
 * treg0=1 => 1 trigger per line (byte/word tables)
 * treg0=2 => 1 trigger per 2 lines (common for dword tables, see Ganbare) */
void ngpc_dma_timer0_hblank_enable_treg0(u8 treg0);
void ngpc_dma_timer0_hblank_disable(void);

/* Configure and start Timer0 (TI0/HBlank) and Timer1 (TO0TRG), both ticking once per scanline. */
void ngpc_dma_timer01_hblank_enable(void);
void ngpc_dma_timer01_hblank_disable(void);

/* Enable Timer1 clocked from Timer0 overflow (assumes Timer0 already running). */
void ngpc_dma_timer1_from_timer0_enable(void);
void ngpc_dma_timer1_from_timer0_enable_treg1(u8 treg1);
void ngpc_dma_timer1_disable(void);

/* ---- Frame-rearmed HBlank streaming helper ----
 *
 * MicroDMA tables are one-shot: once `DMACn` reaches 0, the channel stops.
 * For per-frame HBlank effects (152 scanlines), you typically want the same
 * 152-byte table to replay every frame. The safe pattern is:
 *
 *   - Use Timer0/HBlank as the start vector (0x10)
 *   - Re-arm the channel once per frame during VBlank
 *     (e.g. right after `ngpc_vsync()` returns)
 *
 * This helper stores the parameters and provides a `rearm()` call.
 * Note: it does NOT configure Timer0 for HBlank; you must do that separately.
 */

typedef struct {
    u8 channel;
    volatile u8 NGP_FAR *dst_reg;
    const u8 NGP_FAR *src_table;
    u16 count;
} NgpcDmaHblankStream;

/* Configure the stream (does not start it). */
void ngpc_dma_hblank_stream_begin(NgpcDmaHblankStream *s,
                                  u8 channel,
                                  volatile u8 NGP_FAR *dst_reg,
                                  const u8 NGP_FAR *src_table,
                                  u16 count);

/* Re-arm the stream for the next frame (call once per frame during VBlank). */
void ngpc_dma_hblank_stream_rearm(const NgpcDmaHblankStream *s);

/* Stop the channel and disable the stream. */
void ngpc_dma_hblank_stream_end(NgpcDmaHblankStream *s);

/* ---- General stream helper (stores start vector) ----
 *
 * Same concept as NgpcDmaHblankStream, but supports any start vector
 * (Timer0, Timer1, serial, etc.). Useful for "dual vector" setups to avoid
 * MicroDMA CHAIN.
 */

typedef struct {
    u8 channel;
    volatile u8 NGP_FAR *dst_reg;
    const u8 NGP_FAR *src_table;
    u16 count;
    u8 start_vector;
} NgpcDmaU8Stream;

void ngpc_dma_stream_begin_u8(NgpcDmaU8Stream *s,
                              u8 channel,
                              volatile u8 NGP_FAR *dst_reg,
                              const u8 NGP_FAR *src_table,
                              u16 count,
                              u8 start_vector);
void ngpc_dma_stream_rearm_u8(const NgpcDmaU8Stream *s);
void ngpc_dma_stream_end_u8(NgpcDmaU8Stream *s);

typedef struct {
    u8 channel;
    volatile u8 NGP_FAR *dst_reg;
    const u16 NGP_FAR *src_table;
    u16 count;
    u8 start_vector;
} NgpcDmaU16Stream;

void ngpc_dma_stream_begin_u16(NgpcDmaU16Stream *s,
                               u8 channel,
                               volatile u8 NGP_FAR *dst_reg,
                               const u16 NGP_FAR *src_table,
                               u16 count,
                               u8 start_vector);
void ngpc_dma_stream_rearm_u16(const NgpcDmaU16Stream *s);
void ngpc_dma_stream_end_u16(NgpcDmaU16Stream *s);

typedef struct {
    u8 channel;
    volatile u8 NGP_FAR *dst_reg;
    const u32 NGP_FAR *src_table;
    u16 count;
    u8 start_vector;
} NgpcDmaU32Stream;

void ngpc_dma_stream_begin_u32(NgpcDmaU32Stream *s,
                               u8 channel,
                               volatile u8 NGP_FAR *dst_reg,
                               const u32 NGP_FAR *src_table,
                               u16 count,
                               u8 start_vector);
void ngpc_dma_stream_rearm_u32(const NgpcDmaU32Stream *s);
void ngpc_dma_stream_end_u32(NgpcDmaU32Stream *s);

/* Stop channel trigger and clear mode/count. */
void ngpc_dma_stop(u8 channel);

/* Read current remaining transfer count from hardware register. */
u16 ngpc_dma_remaining(u8 channel);
u8  ngpc_dma_active(u8 channel);

/* Completion handling (set callback and/or poll done flag). */
void ngpc_dma_set_done_handler(u8 channel, FuncPtr cb);
/* Returns 1 once when the armed channel completes.
 * Works with or without DMA completion ISRs:
 * - If `NGP_DMA_INSTALL_DONE_ISR=1`, it uses the ISR-set done flag.
 * - Otherwise, it falls back to polling `__DMACn` until it reaches 0. */
u8   ngpc_dma_poll_done(u8 channel);

/* ---- Ping-pong buffer helper (Ganbare-style) ----
 *
 * Useful when you rebuild a per-line table in main code while MicroDMA is
 * reading it: write into the back buffer, then swap during VBlank.
 *
 * Ganbare uses a stride of 0x0134 for a 152-line *word* table (0x130 bytes used
 * + 4 bytes padding), but you can use any stride >= bytes_used_per_frame.
 */

#define NGPC_DMA_PP_STRIDE_WORD152  0x0134u

typedef struct {
    u8 NGP_FAR *base;
    u16 stride;
    u16 offset; /* 0 or stride */
} NgpcDmaPingPong;

void ngpc_dma_pp_init(NgpcDmaPingPong *pp, u8 NGP_FAR *base, u16 stride);
u8 NGP_FAR *ngpc_dma_pp_front(const NgpcDmaPingPong *pp);
u8 NGP_FAR *ngpc_dma_pp_back(const NgpcDmaPingPong *pp);
void ngpc_dma_pp_swap(NgpcDmaPingPong *pp);

/* ---- Auto-rearm on INTTCn (End MicroDMA) ----
 *
 * MicroDMA tables are one-shot and DMAxV auto-clears when DMAC reaches 0.
 * Auto-rearm closes the window where the trigger source (Timer0/Timer1) could
 * fall back to a CPU interrupt if it keeps firing while DMAxV is 0.
 *
 * Requires `NGP_DMA_INSTALL_REARM_ISR=1` and calling ngpc_dma_init().
 */

void ngpc_dma_autorearm_begin_u8(u8 channel,
                                 volatile u8 NGP_FAR *dst_reg,
                                 const u8 NGP_FAR *src_table,
                                 u16 count,
                                 u8 start_vector);
void ngpc_dma_autorearm_begin_u16(u8 channel,
                                  volatile u8 NGP_FAR *dst_reg,
                                  const u16 NGP_FAR *src_table,
                                  u16 count,
                                  u8 start_vector);
void ngpc_dma_autorearm_begin_u32(u8 channel,
                                  volatile u8 NGP_FAR *dst_reg,
                                  const u32 NGP_FAR *src_table,
                                  u16 count,
                                  u8 start_vector);

void ngpc_dma_autorearm_set_src_u8(u8 channel, const u8 NGP_FAR *src_table);
void ngpc_dma_autorearm_set_src_u16(u8 channel, const u16 NGP_FAR *src_table);
void ngpc_dma_autorearm_set_src_u32(u8 channel, const u32 NGP_FAR *src_table);

void ngpc_dma_autorearm_enable(u8 channel);
void ngpc_dma_autorearm_disable(u8 channel);

#endif /* NGPC_DMA_H */
