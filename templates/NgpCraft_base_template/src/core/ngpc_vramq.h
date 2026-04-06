/*
 * ngpc_vramq.h - Queued VRAM updates flushed during VBlank
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Purpose:
 * - Queue VRAM writes from gameplay code
 * - Flush them during VBlank to reduce active-scanline VRAM contention
 *
 * Notes:
 * - Queue operations work in 16-bit words (u16), matching NGPC VRAM access.
 * - Destination must be inside VRAM (0x8000-0xBFFF).
 * - Flush is automatically called from ngpc_sys VBlank ISR.
 */

#ifndef NGPC_VRAMQ_H
#define NGPC_VRAMQ_H

#include "ngpc_types.h"

/* Maximum queued commands per frame (kept small for RAM footprint). */
#define VRAMQ_MAX_CMDS 16

/* Reset queue state (called by ngpc_init). */
void ngpc_vramq_init(void);

/* Queue copy: src[0..len_words-1] -> dst[0..len_words-1].
 * Returns 1 on success, 0 if invalid args or queue full. */
u8 ngpc_vramq_copy(volatile u16 *dst, const u16 *src, u16 len_words);

/* Queue fill: dst[0..len_words-1] = value.
 * Returns 1 on success, 0 if invalid args or queue full. */
u8 ngpc_vramq_fill(volatile u16 *dst, u16 value, u16 len_words);

/* Flush queued commands now (normally called in VBlank ISR). */
void ngpc_vramq_flush(void);

/* Clear queued commands without flushing. */
void ngpc_vramq_clear(void);

/* Diagnostics counters. */
u8 ngpc_vramq_pending(void);
u8 ngpc_vramq_dropped(void);
void ngpc_vramq_clear_dropped(void);

#endif /* NGPC_VRAMQ_H */

