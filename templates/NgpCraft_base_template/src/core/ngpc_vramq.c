/*
 * ngpc_vramq.c - Queued VRAM updates flushed during VBlank
 *
 * Part of NgpCraft_base_template (MIT License)
 */

#include "ngpc_hw.h"
#include "ngpc_vramq.h"

/* ASM helper: word block copy via LDIRW -- see ngpc_vramq_asm.asm.
 * Args are u32 to guarantee 4-byte stack slots in cc900 large model. */
void ngpc_memcpy_w(u32 dst_addr, u32 src_addr, u32 words);

#define VRAM_ADDR_MIN  0x8000
#define VRAM_ADDR_MAX  0xBFFF

#define CMD_COPY  1
#define CMD_FILL  2

/* Compact command storage:
 * - dst is stored as 16-bit address (VRAM is in 0x8000-0xBFFF)
 * - copy source uses full pointer
 */
static u8                s_cmd_type[VRAMQ_MAX_CMDS];
static u16               s_cmd_dst[VRAMQ_MAX_CMDS];
static u16               s_cmd_len[VRAMQ_MAX_CMDS];
static const u16        *s_cmd_src[VRAMQ_MAX_CMDS];
static u16               s_cmd_fill[VRAMQ_MAX_CMDS];
static volatile u8       s_cmd_count;
static volatile u8       s_drop_count;
static volatile u8       s_lock;

static u8 dst_range_ok(volatile u16 *dst, u16 len_words)
{
    u32 start;
    u32 bytes;
    u32 end;

    if (!dst || len_words == 0)
        return 0;

    start = (u32)(u16)(u32)dst;
    bytes = (u32)len_words << 1;
    end = start + bytes - 1;

    if (start < VRAM_ADDR_MIN) return 0;
    if (end > VRAM_ADDR_MAX) return 0;
    return 1;
}

void ngpc_vramq_init(void)
{
    s_cmd_count = 0;
    s_drop_count = 0;
    s_lock = 0;
}

u8 ngpc_vramq_copy(volatile u16 *dst, const u16 *src, u16 len_words)
{
    u8 idx;

    if (!src || !dst_range_ok(dst, len_words))
        return 0;

    s_lock = 1;
    idx = s_cmd_count;
    if (idx >= VRAMQ_MAX_CMDS) {
        s_drop_count++;
        s_lock = 0;
        return 0;
    }

    s_cmd_dst[idx] = (u16)(u32)dst;
    s_cmd_len[idx] = len_words;
    s_cmd_src[idx] = src;
    s_cmd_fill[idx] = 0;
    s_cmd_type[idx] = CMD_COPY;
    s_cmd_count = (u8)(idx + 1);
    s_lock = 0;

    return 1;
}

u8 ngpc_vramq_fill(volatile u16 *dst, u16 value, u16 len_words)
{
    u8 idx;

    if (!dst_range_ok(dst, len_words))
        return 0;

    s_lock = 1;
    idx = s_cmd_count;
    if (idx >= VRAMQ_MAX_CMDS) {
        s_drop_count++;
        s_lock = 0;
        return 0;
    }

    s_cmd_dst[idx] = (u16)(u32)dst;
    s_cmd_len[idx] = len_words;
    s_cmd_src[idx] = (const u16 *)0;
    s_cmd_fill[idx] = value;
    s_cmd_type[idx] = CMD_FILL;
    s_cmd_count = (u8)(idx + 1);
    s_lock = 0;

    return 1;
}

void ngpc_vramq_flush(void)
{
    u8 i;
    u8 count;

    if (s_lock)
        return;

    count = s_cmd_count;
    if (count == 0)
        return;

    s_lock = 1;

    for (i = 0; i < count; i++) {
        volatile u16 *dst = (volatile u16 *)(u32)s_cmd_dst[i];
        u16 len = s_cmd_len[i];

        if (s_cmd_type[i] == CMD_COPY) {
            /* LDIRW block copy via ASM helper (faster than C word loop). */
            ngpc_memcpy_w((u32)s_cmd_dst[i], (u32)s_cmd_src[i], (u32)len);
        } else if (s_cmd_type[i] == CMD_FILL) {
            u16 v = s_cmd_fill[i];
            while (len--) {
                *dst++ = v;
            }
        }
    }

    s_cmd_count = 0;
    s_lock = 0;
}

void ngpc_vramq_clear(void)
{
    if (s_lock)
        return;
    s_cmd_count = 0;
}

u8 ngpc_vramq_pending(void)
{
    return s_cmd_count;
}

u8 ngpc_vramq_dropped(void)
{
    return s_drop_count;
}

void ngpc_vramq_clear_dropped(void)
{
    s_drop_count = 0;
}
