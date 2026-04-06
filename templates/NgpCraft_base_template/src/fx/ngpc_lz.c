/*
 * ngpc_lz.c - Tile data decompression (RLE + LZ77)
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Standard decompression algorithms. The compression is done offline
 * by a companion Python tool (ngpc_compress.py).
 *
 * RLE: ~50 bytes of code, ~2 cycles per output byte.
 * LZ77: ~120 bytes of code, ~5-10 cycles per output byte.
 * Both are fast enough to decompress a full tileset during loading.
 */

#include "ngpc_hw.h"
#include "ngpc_gfx.h"
#include "ngpc_lz.h"

/* ---- RLE ---- */

u16 ngpc_rle_decompress(u8 *dst, const u8 *src, u16 src_len)
{
    const u8 *end = src + src_len;
    u8 *out = dst;

    while (src < end) {
        u8 ctrl = *src++;

        if (ctrl & 0x80) {
            /* Run: repeat next byte N+1 times. */
            u8 count = (ctrl & 0x7F) + 1;
            u8 val = *src++;
            while (count--)
                *out++ = val;
        } else {
            /* Literal: copy next N+1 bytes. */
            u8 count = ctrl + 1;
            while (count--)
                *out++ = *src++;
        }
    }

    return (u16)(out - dst);
}

/* ---- LZ77 (LZSS) ---- */

u16 ngpc_lz_decompress(u8 *dst, const u8 *src, u16 src_len)
{
    const u8 *end = src + src_len;
    u8 *out = dst;

    while (src < end) {
        u8 flags = *src++;
        u8 bit;

        for (bit = 0; bit < 8 && src < end; bit++) {
            if (flags & 0x80) {
                /* Match: copy from earlier in the output. */
                u8 b0 = *src++;
                u8 b1 = *src++;
                u16 offset = ((u16)(b0 >> 4) << 8) | (u16)b1;
                u8  length = (b0 & 0x0F) + 3;
                u8 *match  = out - offset;

                while (length--)
                    *out++ = *match++;
            } else {
                /* Literal: copy one byte. */
                *out++ = *src++;
            }

            flags <<= 1;
        }
    }

    return (u16)(out - dst);
}

/* ---- Convenience ---- */

/*
 * Temporary RAM buffer for decompression.
 * Max size: limited by available RAM. 2KB covers ~128 tiles.
 * For larger tilesets, decompress in chunks.
 */
#define DECOMP_BUF_SIZE  2048
static u8 s_decomp_buf[DECOMP_BUF_SIZE];

void ngpc_rle_to_tiles(const u8 *src, u16 src_len, u16 tile_offset)
{
    u16 out_len = ngpc_rle_decompress(s_decomp_buf, src, src_len);
    u16 word_count = out_len / 2;   /* Tile data is u16 words */

    ngpc_gfx_load_tiles_at((const u16 *)s_decomp_buf, word_count, tile_offset);
}

void ngpc_lz_to_tiles(const u8 *src, u16 src_len, u16 tile_offset)
{
    u16 out_len = ngpc_lz_decompress(s_decomp_buf, src, src_len);
    u16 word_count = out_len / 2;

    ngpc_gfx_load_tiles_at((const u16 *)s_decomp_buf, word_count, tile_offset);
}
