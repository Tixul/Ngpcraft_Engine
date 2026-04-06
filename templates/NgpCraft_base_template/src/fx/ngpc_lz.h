/*
 * ngpc_lz.h - Tile data decompression (RLE + LZ77)
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Compress assets offline (Python tool), decompress at runtime on NGPC.
 * Two algorithms depending on data type:
 *
 *   RLE: good for tiles with large uniform areas (simple, fast).
 *        Format: [count, value] pairs. count bit 7 = run flag.
 *        Ratio: ~1.5:1 to 2:1.
 *
 *   LZ77 (LZSS variant): general-purpose compression.
 *        Format: flag byte + literal/match pairs.
 *        Ratio: ~2:1 to 4:1.
 *
 * Both decompress to a u8 destination buffer (RAM or VRAM via cast).
 */

#ifndef NGPC_LZ_H
#define NGPC_LZ_H

#include "ngpc_types.h"

/* ---- RLE decompression ---- */

/*
 * RLE stream format:
 *   While data remains:
 *     Read control byte B.
 *     If B & 0x80:  run of (B & 0x7F) + 1 copies of the next byte.
 *     Else:         (B + 1) literal bytes follow.
 *
 * Decompress RLE-compressed data.
 * dst: output buffer
 * src: compressed data
 * src_len: size of compressed data in bytes
 * Returns: number of bytes written to dst.
 */
u16 ngpc_rle_decompress(u8 *dst, const u8 *src, u16 src_len);

/* ---- LZ77 (LZSS) decompression ---- */

/*
 * LZ77 stream format:
 *   While data remains:
 *     Read flag byte (8 bits, MSB first).
 *     For each bit (7 down to 0):
 *       If bit = 0: literal byte follows, copy to output.
 *       If bit = 1: match follows (2 bytes):
 *         Byte 0: offset high 4 bits (4) + length - 3 (4)
 *         Byte 1: offset low 8 bits
 *         => offset = ((b0 >> 4) << 8) | b1  (12-bit, 1-4096)
 *         => length = (b0 & 0x0F) + 3        (3-18 bytes)
 *         Copy 'length' bytes from (dst_pos - offset) to dst_pos.
 *
 * Decompress LZ77/LZSS-compressed data.
 * dst: output buffer
 * src: compressed data
 * src_len: size of compressed data in bytes
 * Returns: number of bytes written to dst.
 */
u16 ngpc_lz_decompress(u8 *dst, const u8 *src, u16 src_len);

/* ---- Convenience: decompress directly to tile RAM ---- */

/* Decompress RLE data and load as tiles starting at tile_offset. */
void ngpc_rle_to_tiles(const u8 *src, u16 src_len, u16 tile_offset);

/* Decompress LZ77 data and load as tiles starting at tile_offset. */
void ngpc_lz_to_tiles(const u8 *src, u16 src_len, u16 tile_offset);

#endif /* NGPC_LZ_H */
