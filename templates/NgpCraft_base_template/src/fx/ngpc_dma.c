/*
 * ngpc_dma.c - MicroDMA helpers
 *
 * Part of NgpCraft_base_template (MIT License)
 */

#include "ngpc_hw.h"
#include "ngpc_dma.h"

/* TLCS-900 MicroDMA transfer modes (mem->I/O, source increment).
 * Values match SDK `HDMA.H` (which uses octal literals). */
#define DMA_MODE_SINC1  0x08 /* byte  */
#define DMA_MODE_SINC2  0x09 /* word  */
#define DMA_MODE_SINC4  0x0A /* dword */

static FuncPtr s_done_cb[4];
static volatile u8 s_done_flag[4];
static volatile u8 s_was_active[4];

/* Auto-rearm configuration (installed on INTTCn / HW_INT_DMA*). */
static volatile u8 s_rearm_enabled[4];
static volatile u8 s_rearm_elem[4];      /* 0=u8, 1=u16, 2=u32 */
static volatile u8 s_rearm_vector[4];    /* DMAxV start vector */
static volatile u16 s_rearm_count[4];    /* DMACn value */
static volatile u8 NGP_FAR *s_rearm_dst[4];
static const void NGP_FAR *s_rearm_src[4];

/* Some hardware/flashcart setups have proven fragile with DMA completion
 * interrupts during early experiments. The DMA core works without these
 * handlers (polling `__DMACn` is enough). Enable only when validated. */
#ifndef NGP_DMA_INSTALL_DONE_ISR
#define NGP_DMA_INSTALL_DONE_ISR 0
#endif

/* Assembly helpers (avoid fragile inline-asm stack-offset assumptions). */
void dma0_program_asm(const u8 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count);
void dma1_program_asm(const u8 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count);
void dma2_program_asm(const u8 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count);
void dma3_program_asm(const u8 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count);
void dma0_program_u16_asm(const u16 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count);
void dma1_program_u16_asm(const u16 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count);
void dma2_program_u16_asm(const u16 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count);
void dma3_program_u16_asm(const u16 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count);
void dma0_program_u32_asm(const u32 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count);
void dma1_program_u32_asm(const u32 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count);
void dma2_program_u32_asm(const u32 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count);
void dma3_program_u32_asm(const u32 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count);

/* ---- Low-level channel programming ---- */

static void dma0_program(const u8 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count)
{
    (void)DMA_MODE_SINC1;
    dma0_program_asm(src, dst, count);
}

static void dma1_program(const u8 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count)
{
    (void)DMA_MODE_SINC1;
    dma1_program_asm(src, dst, count);
}

static void dma2_program(const u8 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count)
{
    (void)DMA_MODE_SINC1;
    dma2_program_asm(src, dst, count);
}

static void dma3_program(const u8 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count)
{
    (void)DMA_MODE_SINC1;
    dma3_program_asm(src, dst, count);
}

static void dma0_program_u16(const u16 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count)
{
    (void)DMA_MODE_SINC2;
    dma0_program_u16_asm(src, dst, count);
}

static void dma1_program_u16(const u16 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count)
{
    (void)DMA_MODE_SINC2;
    dma1_program_u16_asm(src, dst, count);
}

static void dma2_program_u16(const u16 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count)
{
    (void)DMA_MODE_SINC2;
    dma2_program_u16_asm(src, dst, count);
}

static void dma3_program_u16(const u16 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count)
{
    (void)DMA_MODE_SINC2;
    dma3_program_u16_asm(src, dst, count);
}

static void dma0_program_u32(const u32 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count)
{
    (void)DMA_MODE_SINC4;
    dma0_program_u32_asm(src, dst, count);
}

static void dma1_program_u32(const u32 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count)
{
    (void)DMA_MODE_SINC4;
    dma1_program_u32_asm(src, dst, count);
}

static void dma2_program_u32(const u32 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count)
{
    (void)DMA_MODE_SINC4;
    dma2_program_u32_asm(src, dst, count);
}

static void dma3_program_u32(const u32 NGP_FAR *src, volatile u8 NGP_FAR *dst, u16 count)
{
    (void)DMA_MODE_SINC4;
    dma3_program_u32_asm(src, dst, count);
}

static void dma0_clear(void)
{
    __asm("ld wa,0");
    __asm("ldcw dmac0,wa");
    __asm("ld a,0");
    __asm("ldcb dmam0,a");
}

static void dma1_clear(void)
{
    __asm("ld wa,0");
    __asm("ldcw dmac1,wa");
    __asm("ld a,0");
    __asm("ldcb dmam1,a");
}

static void dma2_clear(void)
{
    __asm("ld wa,0");
    __asm("ldcw dmac2,wa");
    __asm("ld a,0");
    __asm("ldcb dmam2,a");
}

static void dma3_clear(void)
{
    __asm("ld wa,0");
    __asm("ldcw dmac3,wa");
    __asm("ld a,0");
    __asm("ldcb dmam3,a");
}

static void dma_set_start_vector(u8 channel, u8 vector)
{
    switch (channel) {
    case NGPC_DMA_CH0: HW_DMA0V = vector; break;
    case NGPC_DMA_CH1: HW_DMA1V = vector; break;
    case NGPC_DMA_CH2: HW_DMA2V = vector; break;
    case NGPC_DMA_CH3: HW_DMA3V = vector; break;
    }
}

/* ---- INTTCn (End MicroDMA) ISRs ----
 *
 * These are installed into HW_INT_DMA0..3. They can:
 * - expose "done" events (NGP_DMA_INSTALL_DONE_ISR)
 * - auto-rearm the channel immediately after DMAC reaches 0 (NGP_DMA_INSTALL_REARM_ISR)
 */

static void dma_rearm_in_isr(u8 channel)
{
    if (!NGP_DMA_INSTALL_REARM_ISR) return;
    if (channel > NGPC_DMA_CH3) return;
    if (!s_rearm_enabled[channel]) return;

    dma_set_start_vector(channel, 0);

    switch (s_rearm_elem[channel]) {
    default:
    case 0: /* u8 */
        switch (channel) {
        case NGPC_DMA_CH0: dma0_program((const u8 NGP_FAR *)s_rearm_src[channel], s_rearm_dst[channel], s_rearm_count[channel]); break;
        case NGPC_DMA_CH1: dma1_program((const u8 NGP_FAR *)s_rearm_src[channel], s_rearm_dst[channel], s_rearm_count[channel]); break;
        case NGPC_DMA_CH2: dma2_program((const u8 NGP_FAR *)s_rearm_src[channel], s_rearm_dst[channel], s_rearm_count[channel]); break;
        case NGPC_DMA_CH3: dma3_program((const u8 NGP_FAR *)s_rearm_src[channel], s_rearm_dst[channel], s_rearm_count[channel]); break;
        }
        break;
    case 1: /* u16 */
        switch (channel) {
        case NGPC_DMA_CH0: dma0_program_u16((const u16 NGP_FAR *)s_rearm_src[channel], s_rearm_dst[channel], s_rearm_count[channel]); break;
        case NGPC_DMA_CH1: dma1_program_u16((const u16 NGP_FAR *)s_rearm_src[channel], s_rearm_dst[channel], s_rearm_count[channel]); break;
        case NGPC_DMA_CH2: dma2_program_u16((const u16 NGP_FAR *)s_rearm_src[channel], s_rearm_dst[channel], s_rearm_count[channel]); break;
        case NGPC_DMA_CH3: dma3_program_u16((const u16 NGP_FAR *)s_rearm_src[channel], s_rearm_dst[channel], s_rearm_count[channel]); break;
        }
        break;
    case 2: /* u32 */
        switch (channel) {
        case NGPC_DMA_CH0: dma0_program_u32((const u32 NGP_FAR *)s_rearm_src[channel], s_rearm_dst[channel], s_rearm_count[channel]); break;
        case NGPC_DMA_CH1: dma1_program_u32((const u32 NGP_FAR *)s_rearm_src[channel], s_rearm_dst[channel], s_rearm_count[channel]); break;
        case NGPC_DMA_CH2: dma2_program_u32((const u32 NGP_FAR *)s_rearm_src[channel], s_rearm_dst[channel], s_rearm_count[channel]); break;
        case NGPC_DMA_CH3: dma3_program_u32((const u32 NGP_FAR *)s_rearm_src[channel], s_rearm_dst[channel], s_rearm_count[channel]); break;
        }
        break;
    }

    dma_set_start_vector(channel, s_rearm_vector[channel]);
}

static void __interrupt isr_dma0_inttc(void)
{
    if (NGP_DMA_INSTALL_DONE_ISR) {
        s_done_flag[0] = 1;
    }
    dma_rearm_in_isr(0);
    if (NGP_DMA_INSTALL_DONE_ISR) {
        if (s_done_cb[0]) s_done_cb[0]();
    }
}

static void __interrupt isr_dma1_inttc(void)
{
    if (NGP_DMA_INSTALL_DONE_ISR) {
        s_done_flag[1] = 1;
    }
    dma_rearm_in_isr(1);
    if (NGP_DMA_INSTALL_DONE_ISR) {
        if (s_done_cb[1]) s_done_cb[1]();
    }
}

static void __interrupt isr_dma2_inttc(void)
{
    if (NGP_DMA_INSTALL_DONE_ISR) {
        s_done_flag[2] = 1;
    }
    dma_rearm_in_isr(2);
    if (NGP_DMA_INSTALL_DONE_ISR) {
        if (s_done_cb[2]) s_done_cb[2]();
    }
}

static void __interrupt isr_dma3_inttc(void)
{
    if (NGP_DMA_INSTALL_DONE_ISR) {
        s_done_flag[3] = 1;
    }
    dma_rearm_in_isr(3);
    if (NGP_DMA_INSTALL_DONE_ISR) {
        if (s_done_cb[3]) s_done_cb[3]();
    }
}

typedef enum {
    DMA_ELEM_U8 = 0,
    DMA_ELEM_U16 = 1,
    DMA_ELEM_U32 = 2
} DmaElem;

static void dma_start_common(u8 channel,
                             volatile u8 NGP_FAR *dst_reg,
                             const void NGP_FAR *src_table,
                             u16 count,
                             u8 start_vector,
                             DmaElem elem)
{
    if (channel > NGPC_DMA_CH3) return;
    if (!dst_reg || !src_table) return;
    if (count == 0) return;
#if !NGP_DMA_ALLOW_VBLANK_TRIGGER
    if (start_vector == NGPC_DMA_VEC_VBLANK) return;
#endif

    s_done_flag[channel] = 0;
    s_was_active[channel] = 1;
    dma_set_start_vector(channel, 0);

    switch (elem) {
    case DMA_ELEM_U8:
        switch (channel) {
        case NGPC_DMA_CH0: dma0_program((const u8 NGP_FAR *)src_table, dst_reg, count); break;
        case NGPC_DMA_CH1: dma1_program((const u8 NGP_FAR *)src_table, dst_reg, count); break;
        case NGPC_DMA_CH2: dma2_program((const u8 NGP_FAR *)src_table, dst_reg, count); break;
        case NGPC_DMA_CH3: dma3_program((const u8 NGP_FAR *)src_table, dst_reg, count); break;
        }
        break;
    case DMA_ELEM_U16:
        switch (channel) {
        case NGPC_DMA_CH0: dma0_program_u16((const u16 NGP_FAR *)src_table, dst_reg, count); break;
        case NGPC_DMA_CH1: dma1_program_u16((const u16 NGP_FAR *)src_table, dst_reg, count); break;
        case NGPC_DMA_CH2: dma2_program_u16((const u16 NGP_FAR *)src_table, dst_reg, count); break;
        case NGPC_DMA_CH3: dma3_program_u16((const u16 NGP_FAR *)src_table, dst_reg, count); break;
        }
        break;
    case DMA_ELEM_U32:
        switch (channel) {
        case NGPC_DMA_CH0: dma0_program_u32((const u32 NGP_FAR *)src_table, dst_reg, count); break;
        case NGPC_DMA_CH1: dma1_program_u32((const u32 NGP_FAR *)src_table, dst_reg, count); break;
        case NGPC_DMA_CH2: dma2_program_u32((const u32 NGP_FAR *)src_table, dst_reg, count); break;
        case NGPC_DMA_CH3: dma3_program_u32((const u32 NGP_FAR *)src_table, dst_reg, count); break;
        }
        break;
    }

    dma_set_start_vector(channel, start_vector);
}

/* ---- Public API ---- */

void ngpc_dma_init(void)
{
    u8 i;

    for (i = 0; i < 4; i++) {
        s_done_cb[i] = (FuncPtr)0;
        s_done_flag[i] = 0;
        s_was_active[i] = 0;
        s_rearm_enabled[i] = 0;
        s_rearm_elem[i] = 0;
        s_rearm_vector[i] = 0;
        s_rearm_count[i] = 0;
        s_rearm_dst[i] = (volatile u8 NGP_FAR *)0;
        s_rearm_src[i] = (const void NGP_FAR *)0;
    }

    if (NGP_DMA_INSTALL_DONE_ISR || NGP_DMA_INSTALL_REARM_ISR) {
        HW_INT_DMA0 = isr_dma0_inttc;
        HW_INT_DMA1 = isr_dma1_inttc;
        HW_INT_DMA2 = isr_dma2_inttc;
        HW_INT_DMA3 = isr_dma3_inttc;

        /* Enable INTTC0..3 at a low interrupt level (1).
         * Bit layout (INTETC01/23): enable+level for INTTC0/2 (low nibble) and INTTC1/3 (high nibble).
         * 0x99 = enable both + level=1 for each. */
        HW_INTETC01 = 0x99;
        HW_INTETC23 = 0x99;
    }
}

void ngpc_dma_start_table_u8(u8 channel,
                             volatile u8 NGP_FAR *dst_reg,
                             const u8 NGP_FAR *src_table,
                             u16 count,
                             u8 start_vector)
{
    dma_start_common(channel, dst_reg, src_table, count, start_vector, DMA_ELEM_U8);
}

void ngpc_dma_start_table_u16(u8 channel,
                              volatile u8 NGP_FAR *dst_reg,
                              const u16 NGP_FAR *src_table,
                              u16 count,
                              u8 start_vector)
{
    dma_start_common(channel, dst_reg, src_table, count, start_vector, DMA_ELEM_U16);
}

void ngpc_dma_start_table_u32(u8 channel,
                              volatile u8 NGP_FAR *dst_reg,
                              const u32 NGP_FAR *src_table,
                              u16 count,
                              u8 start_vector)
{
    dma_start_common(channel, dst_reg, src_table, count, start_vector, DMA_ELEM_U32);
}

void ngpc_dma_link_hblank(u8 channel, volatile u8 NGP_FAR *dst_reg,
                          const u8 NGP_FAR *src_table, u16 count)
{
    ngpc_dma_start_table_u8(channel, dst_reg, src_table, count, NGPC_DMA_VEC_TIMER0);
}

void ngpc_dma_link_vblank(u8 channel, volatile u8 NGP_FAR *dst_reg,
                          const u8 NGP_FAR *src_table, u16 count)
{
    ngpc_dma_start_table_u8(channel, dst_reg, src_table, count, NGPC_DMA_VEC_VBLANK);
}

void ngpc_dma_link_hblank_u16(u8 channel, volatile u8 NGP_FAR *dst_reg,
                              const u16 NGP_FAR *src_table, u16 count)
{
    ngpc_dma_start_table_u16(channel, dst_reg, src_table, count, NGPC_DMA_VEC_TIMER0);
}

void ngpc_dma_link_hblank_u32(u8 channel, volatile u8 NGP_FAR *dst_reg,
                              const u32 NGP_FAR *src_table, u16 count)
{
    ngpc_dma_start_table_u32(channel, dst_reg, src_table, count, NGPC_DMA_VEC_TIMER0);
}

/* ---- Timer helpers ---- */

void ngpc_dma_timer0_hblank_enable(void)
{
    ngpc_dma_timer0_hblank_enable_treg0(0x01);
}

void ngpc_dma_timer0_hblank_enable_treg0(u8 treg0)
{
    /* Timer0 clock = TI0 (HBlank), 8-bit mode. */
    HW_T01MOD &= (u8)~0xC3; /* clear TMOD(7-6) and T0CLK(1-0) */
    HW_TREG0 = treg0;
    HW_TRUN |= 0x01;
}

void ngpc_dma_timer0_hblank_disable(void)
{
    HW_TRUN &= (u8)~0x01;
}

void ngpc_dma_timer01_hblank_enable(void)
{
    /* Timer0 clock = TI0 (HBlank), Timer1 clock = TO0TRG (Timer0 overflow output). */
    HW_T01MOD &= (u8)~0xCF; /* clear TMOD(7-6), T1CLK(3-2), T0CLK(1-0); preserve PWMMOD */
    HW_TREG0 = 0x01;
    HW_TREG1 = 0x01;
    HW_TRUN |= 0x03;
}

void ngpc_dma_timer01_hblank_disable(void)
{
    HW_TRUN &= (u8)~0x03;
}

void ngpc_dma_timer1_from_timer0_enable(void)
{
    ngpc_dma_timer1_from_timer0_enable_treg1(0x01);
}

void ngpc_dma_timer1_from_timer0_enable_treg1(u8 treg1)
{
    /* Timer1 clock = TO0TRG (Timer0 overflow). Timer0 must already be running. */
    HW_T01MOD &= (u8)~0x0C; /* clear T1CLK(3-2) => 00: TO0TRG */
    HW_TREG1 = treg1;
    HW_TRUN |= 0x02;
}

void ngpc_dma_timer1_disable(void)
{
    HW_TRUN &= (u8)~0x02;
}

void ngpc_dma_hblank_stream_begin(NgpcDmaHblankStream *s,
                                  u8 channel,
                                  volatile u8 NGP_FAR *dst_reg,
                                  const u8 NGP_FAR *src_table,
                                  u16 count)
{
    if (!s) return;
    s->channel = channel;
    s->dst_reg = dst_reg;
    s->src_table = src_table;
    s->count = count;
}

void ngpc_dma_hblank_stream_rearm(const NgpcDmaHblankStream *s)
{
    if (!s) return;
    ngpc_dma_start_table_u8(s->channel, s->dst_reg, s->src_table, s->count, NGPC_DMA_VEC_TIMER0);
}

void ngpc_dma_hblank_stream_end(NgpcDmaHblankStream *s)
{
    if (!s) return;
    ngpc_dma_stop(s->channel);
}

void ngpc_dma_stream_begin_u8(NgpcDmaU8Stream *s,
                              u8 channel,
                              volatile u8 NGP_FAR *dst_reg,
                              const u8 NGP_FAR *src_table,
                              u16 count,
                              u8 start_vector)
{
    if (!s) return;
    s->channel = channel;
    s->dst_reg = dst_reg;
    s->src_table = src_table;
    s->count = count;
    s->start_vector = start_vector;
}

void ngpc_dma_stream_rearm_u8(const NgpcDmaU8Stream *s)
{
    if (!s) return;
    ngpc_dma_start_table_u8(s->channel, s->dst_reg, s->src_table, s->count, s->start_vector);
}

void ngpc_dma_stream_end_u8(NgpcDmaU8Stream *s)
{
    if (!s) return;
    ngpc_dma_stop(s->channel);
}

void ngpc_dma_stream_begin_u16(NgpcDmaU16Stream *s,
                               u8 channel,
                               volatile u8 NGP_FAR *dst_reg,
                               const u16 NGP_FAR *src_table,
                               u16 count,
                               u8 start_vector)
{
    if (!s) return;
    s->channel = channel;
    s->dst_reg = dst_reg;
    s->src_table = src_table;
    s->count = count;
    s->start_vector = start_vector;
}

void ngpc_dma_stream_rearm_u16(const NgpcDmaU16Stream *s)
{
    if (!s) return;
    ngpc_dma_start_table_u16(s->channel, s->dst_reg, s->src_table, s->count, s->start_vector);
}

void ngpc_dma_stream_end_u16(NgpcDmaU16Stream *s)
{
    if (!s) return;
    ngpc_dma_stop(s->channel);
}

void ngpc_dma_stream_begin_u32(NgpcDmaU32Stream *s,
                               u8 channel,
                               volatile u8 NGP_FAR *dst_reg,
                               const u32 NGP_FAR *src_table,
                               u16 count,
                               u8 start_vector)
{
    if (!s) return;
    s->channel = channel;
    s->dst_reg = dst_reg;
    s->src_table = src_table;
    s->count = count;
    s->start_vector = start_vector;
}

void ngpc_dma_stream_rearm_u32(const NgpcDmaU32Stream *s)
{
    if (!s) return;
    ngpc_dma_start_table_u32(s->channel, s->dst_reg, s->src_table, s->count, s->start_vector);
}

void ngpc_dma_stream_end_u32(NgpcDmaU32Stream *s)
{
    if (!s) return;
    ngpc_dma_stop(s->channel);
}

void ngpc_dma_stop(u8 channel)
{
    if (channel > NGPC_DMA_CH3) return;

    dma_set_start_vector(channel, 0);
    s_was_active[channel] = 0;
    s_done_flag[channel] = 0;

    switch (channel) {
    case NGPC_DMA_CH0: dma0_clear(); break;
    case NGPC_DMA_CH1: dma1_clear(); break;
    case NGPC_DMA_CH2: dma2_clear(); break;
    case NGPC_DMA_CH3: dma3_clear(); break;
    }
}

u16 ngpc_dma_remaining(u8 channel)
{
    switch (channel) {
    case NGPC_DMA_CH0: return __DMAC0;
    case NGPC_DMA_CH1: return __DMAC1;
    case NGPC_DMA_CH2: return __DMAC2;
    case NGPC_DMA_CH3: return __DMAC3;
    default: return 0;
    }
}

u8 ngpc_dma_active(u8 channel)
{
    return (ngpc_dma_remaining(channel) != 0) ? 1 : 0;
}

void ngpc_dma_set_done_handler(u8 channel, FuncPtr cb)
{
    if (channel > NGPC_DMA_CH3) return;
    s_done_cb[channel] = cb;
}

u8 ngpc_dma_poll_done(u8 channel)
{
    u8 done_isr;

    if (channel > NGPC_DMA_CH3) return 0;

    /* If completion ISRs are installed, prefer the explicit done flag. */
    done_isr = s_done_flag[channel];
    if (done_isr) {
        s_done_flag[channel] = 0;
        s_was_active[channel] = 0;
        return 1;
    }

    /* Polling fallback (works even when NGP_DMA_INSTALL_DONE_ISR=0):
     * consider "done" only if we previously armed the channel and the
     * hardware counter reached 0. */
    if (s_was_active[channel] && (ngpc_dma_remaining(channel) == 0)) {
        s_was_active[channel] = 0;
        return 1;
    }

    return 0;
}

/* ---- Ping-pong buffers ---- */

void ngpc_dma_pp_init(NgpcDmaPingPong *pp, u8 NGP_FAR *base, u16 stride)
{
    if (!pp) return;
    pp->base = base;
    pp->stride = stride;
    pp->offset = 0;
}

u8 NGP_FAR *ngpc_dma_pp_front(const NgpcDmaPingPong *pp)
{
    if (!pp || !pp->base) return (u8 NGP_FAR *)0;
    return pp->base + pp->offset;
}

u8 NGP_FAR *ngpc_dma_pp_back(const NgpcDmaPingPong *pp)
{
    if (!pp || !pp->base) return (u8 NGP_FAR *)0;
    return pp->base + (pp->offset ^ pp->stride);
}

void ngpc_dma_pp_swap(NgpcDmaPingPong *pp)
{
    if (!pp) return;
    pp->offset ^= pp->stride;
}

/* ---- Auto-rearm on INTTCn ---- */

void ngpc_dma_autorearm_begin_u8(u8 channel,
                                 volatile u8 NGP_FAR *dst_reg,
                                 const u8 NGP_FAR *src_table,
                                 u16 count,
                                 u8 start_vector)
{
    if (channel > NGPC_DMA_CH3) return;
    s_rearm_elem[channel] = 0;
    s_rearm_dst[channel] = dst_reg;
    s_rearm_src[channel] = (const void NGP_FAR *)src_table;
    s_rearm_count[channel] = count;
    s_rearm_vector[channel] = start_vector;
}

void ngpc_dma_autorearm_begin_u16(u8 channel,
                                  volatile u8 NGP_FAR *dst_reg,
                                  const u16 NGP_FAR *src_table,
                                  u16 count,
                                  u8 start_vector)
{
    if (channel > NGPC_DMA_CH3) return;
    s_rearm_elem[channel] = 1;
    s_rearm_dst[channel] = dst_reg;
    s_rearm_src[channel] = (const void NGP_FAR *)src_table;
    s_rearm_count[channel] = count;
    s_rearm_vector[channel] = start_vector;
}

void ngpc_dma_autorearm_begin_u32(u8 channel,
                                  volatile u8 NGP_FAR *dst_reg,
                                  const u32 NGP_FAR *src_table,
                                  u16 count,
                                  u8 start_vector)
{
    if (channel > NGPC_DMA_CH3) return;
    s_rearm_elem[channel] = 2;
    s_rearm_dst[channel] = dst_reg;
    s_rearm_src[channel] = (const void NGP_FAR *)src_table;
    s_rearm_count[channel] = count;
    s_rearm_vector[channel] = start_vector;
}

void ngpc_dma_autorearm_set_src_u8(u8 channel, const u8 NGP_FAR *src_table)
{
    if (channel > NGPC_DMA_CH3) return;
    s_rearm_src[channel] = (const void NGP_FAR *)src_table;
}

void ngpc_dma_autorearm_set_src_u16(u8 channel, const u16 NGP_FAR *src_table)
{
    if (channel > NGPC_DMA_CH3) return;
    s_rearm_src[channel] = (const void NGP_FAR *)src_table;
}

void ngpc_dma_autorearm_set_src_u32(u8 channel, const u32 NGP_FAR *src_table)
{
    if (channel > NGPC_DMA_CH3) return;
    s_rearm_src[channel] = (const void NGP_FAR *)src_table;
}

void ngpc_dma_autorearm_enable(u8 channel)
{
    if (channel > NGPC_DMA_CH3) return;
    if (!NGP_DMA_INSTALL_REARM_ISR) return;
    s_rearm_enabled[channel] = 1;

    switch (s_rearm_elem[channel]) {
    default:
    case 0:
        ngpc_dma_start_table_u8(channel, s_rearm_dst[channel], (const u8 NGP_FAR *)s_rearm_src[channel],
                                s_rearm_count[channel], s_rearm_vector[channel]);
        break;
    case 1:
        ngpc_dma_start_table_u16(channel, s_rearm_dst[channel], (const u16 NGP_FAR *)s_rearm_src[channel],
                                 s_rearm_count[channel], s_rearm_vector[channel]);
        break;
    case 2:
        ngpc_dma_start_table_u32(channel, s_rearm_dst[channel], (const u32 NGP_FAR *)s_rearm_src[channel],
                                 s_rearm_count[channel], s_rearm_vector[channel]);
        break;
    }
}

void ngpc_dma_autorearm_disable(u8 channel)
{
    if (channel > NGPC_DMA_CH3) return;
    s_rearm_enabled[channel] = 0;
}
