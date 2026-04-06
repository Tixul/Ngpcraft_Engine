/*
 * ngpc_log.c - Lightweight debug log ring buffer
 *
 * Part of NgpCraft_base_template (MIT License)
 */

#include "ngpc_hw.h"
#include "ngpc_gfx.h"
#include "ngpc_text.h"
#include "ngpc_log.h"

#define LOG_TYPE_HEX 1
#define LOG_TYPE_STR 2

/* 24 entries x 12 bytes ~= 288 bytes RAM. */
#define LOG_MAX_ENTRIES 24
#define LOG_LABEL_LEN   4
#define LOG_STR_LEN     4

typedef struct {
    u8   type;
    char label[LOG_LABEL_LEN];
    u16  value;
    char text[LOG_STR_LEN];
    u8   _pad;
} NgpcLogEntry;

static NgpcLogEntry s_entries[LOG_MAX_ENTRIES];
static u8 s_head;
static u8 s_count;

static void copy_fixed(char *dst, const char *src, u8 len)
{
    u8 i;
    for (i = 0; i < len; i++) {
        char c = (src && src[i]) ? src[i] : ' ';
        if ((u8)c < 0x20 || (u8)c > 0x7E)
            c = ' ';
        dst[i] = c;
    }
    while (i < len) {
        dst[i++] = ' ';
    }
}

static u8 alloc_slot(void)
{
    u8 idx;

    if (s_count < LOG_MAX_ENTRIES) {
        idx = (u8)((s_head + s_count) % LOG_MAX_ENTRIES);
        s_count++;
        return idx;
    }

    /* Full: overwrite oldest and advance head. */
    idx = s_head;
    s_head = (u8)((s_head + 1) % LOG_MAX_ENTRIES);
    return idx;
}

void ngpc_log_init(void)
{
    s_head = 0;
    s_count = 0;
}

void ngpc_log_clear(void)
{
    s_head = 0;
    s_count = 0;
}

void ngpc_log_hex(const char *label, u16 value)
{
    u8 idx = alloc_slot();
    s_entries[idx].type = LOG_TYPE_HEX;
    s_entries[idx].value = value;
    copy_fixed(s_entries[idx].label, label, LOG_LABEL_LEN);
    copy_fixed(s_entries[idx].text, (const char *)0, LOG_STR_LEN);
}

void ngpc_log_str(const char *label, const char *str)
{
    u8 idx = alloc_slot();
    s_entries[idx].type = LOG_TYPE_STR;
    s_entries[idx].value = 0;
    copy_fixed(s_entries[idx].label, label, LOG_LABEL_LEN);
    copy_fixed(s_entries[idx].text, str, LOG_STR_LEN);
}

void ngpc_log_dump(u8 plane, u8 pal, u8 x, u8 y)
{
    u8 rows;
    u8 i;

    if (y >= SCREEN_TH)
        return;

    rows = (u8)(SCREEN_TH - y);
    if (rows > s_count)
        rows = s_count;

    for (i = 0; i < rows; i++) {
        u8 idx = (u8)((s_head + s_count - 1 - i) % LOG_MAX_ENTRIES);
        const NgpcLogEntry *e = &s_entries[idx];
        u8 row = (u8)(y + i);

        ngpc_text_print(plane, pal, x, row, "    :    ");
        ngpc_gfx_put_tile(plane, x + 4, row, ':', pal);

        ngpc_gfx_put_tile(plane, x + 0, row, (u16)e->label[0], pal);
        ngpc_gfx_put_tile(plane, x + 1, row, (u16)e->label[1], pal);
        ngpc_gfx_put_tile(plane, x + 2, row, (u16)e->label[2], pal);
        ngpc_gfx_put_tile(plane, x + 3, row, (u16)e->label[3], pal);

        if (e->type == LOG_TYPE_HEX) {
            ngpc_text_print_hex(plane, pal, x + 5, row, e->value, 4);
        } else {
            ngpc_gfx_put_tile(plane, x + 5, row, (u16)e->text[0], pal);
            ngpc_gfx_put_tile(plane, x + 6, row, (u16)e->text[1], pal);
            ngpc_gfx_put_tile(plane, x + 7, row, (u16)e->text[2], pal);
            ngpc_gfx_put_tile(plane, x + 8, row, (u16)e->text[3], pal);
        }
    }
}

u8 ngpc_log_count(void)
{
    return s_count;
}
