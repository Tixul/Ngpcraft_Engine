/*
 * ngpc_raster_chain.c - CPU raster splits without MicroDMA
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Sonic §2.3 chain pattern (each ISR handler):
 *   1. Write 1-2 video registers
 *   2. Reprogram TREG0 = (next_split.line - this_split.line)
 *   3. Stop + restart Timer0 so the count resets from the new TREG0
 *   4. RETI
 *
 * This implementation uses a single ISR function with a state index,
 * equivalent to Sonic's RAM function-pointer chain but simpler in C.
 *
 * Timer0 HBlank clock:
 *   T01MOD bits 1-0 = 0b00 (TI0 clock source, internal)
 *   TREG0 = N  → ISR fires N HBlanks after (re)start
 *   HBlank rate = 152 per frame (one per visible scanline)
 */

#include "ngpc_raster_chain.h"
#include "../../src/core/ngpc_hw.h"

/* ---- State ---- */

static const RChainSplit *s_splits;
static u8 s_count;
static volatile u8 s_idx; /* current split index (incremented by ISR) */

/* ---- HBlank ISR ---- */

static void __interrupt isr_rchain(void)
{
    u8 i = s_idx;

    /* Write scroll registers for the current split. */
    HW_SCR1_OFS_X = s_splits[i].scr1x;
    HW_SCR1_OFS_Y = s_splits[i].scr1y;
    HW_SCR2_OFS_X = s_splits[i].scr2x;
    HW_SCR2_OFS_Y = s_splits[i].scr2y;

    i++;
    s_idx = i;

    if (i < s_count) {
        /* Reprogram timer for the delta to the next split.
         * Stop, set TREG0, restart so the counter reloads from 0. */
        HW_TRUN  &= (u8)~0x01u;                                  /* stop  */
        HW_TREG0  = (u8)(s_splits[i].line - s_splits[i - 1u].line);
        HW_TRUN  |= 0x01u;                                        /* start */
    } else {
        /* All splits processed: stop timer until next VBlank. */
        HW_TRUN &= (u8)~0x01u;
    }
}

/* ---- Public API ---- */

void ngpc_rchain_init(void)
{
    s_splits = 0;
    s_count  = 0;
    s_idx    = 0;
}

void ngpc_rchain_arm(const RChainSplit *splits, u8 count)
{
    if (!splits || count == 0)
        return;

    s_splits = splits;
    s_count  = (count > RCHAIN_MAX_SPLITS) ? RCHAIN_MAX_SPLITS : count;
    s_idx    = 0;

    /* Install ISR on Timer0 vector. */
    HW_INT_TIM0 = (IntHandler *)isr_rchain;

    /* Configure Timer0 for HBlank clock.
     * T01MOD bits 1-0 = 0b00: TI0 source (internal, same as ngpc_raster).
     * TREG0 = first split's line number. */
    HW_TRUN  &= (u8)~0xC3u; /* stop, clear clock source bits */
    HW_T01MOD &= (u8)~0xC3u;
    HW_TREG0   = splits[0].line ? splits[0].line : 1u; /* 0 would fire immediately */
    HW_TRUN   |= 0x01u; /* start */
}

void ngpc_rchain_disarm(void)
{
    HW_TRUN &= (u8)~0x01u; /* stop Timer0 */
    /* Do not NULL HW_INT_TIM0: a late-firing interrupt is harmless
     * with the timer stopped, but a NULL pointer crash is not. */
    s_count = 0;
    s_idx   = 0;
}
