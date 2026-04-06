#!/usr/bin/env python3
"""
ngpc_compress.py - Tile data compression for NgpCraft_base_template

Compresses binary data using RLE or LZ77/LZSS, matching the decompressor
in src/ngpc_lz.c. Outputs a C source file with a const u8 array.

Usage:
    python ngpc_compress.py <input> -o <output.c> [-m rle|lz77] [-n ARRAY_NAME]
    python ngpc_compress.py tiles.bin -o tiles_lz.c -m lz77 -n level1_tiles

Both modes:
    python ngpc_compress.py tiles.bin -o tiles_both.c -m both -n my_tiles

MIT License
"""

import argparse
import sys
import os
import re

# Keep short suffixes for asset names:
# - LZ77/LZSS data uses "_lz" (project convention), not "_lz77".
SUFFIX_RLE = "_rle"
SUFFIX_LZ = "_lz"


# ---------------------------------------------------------------------------
# RLE compressor
#
# Format (matching ngpc_rle_decompress):
#   While data remains:
#     Control byte B:
#       If B & 0x80: run of (B & 0x7F) + 1 copies of the next byte
#       Else:        (B + 1) literal bytes follow
#
# Max run length:  128 (0xFF = 127+1)
# Max literal run: 128 (0x7F = 127+1)
# ---------------------------------------------------------------------------

def rle_compress(data):
    """Compress data using RLE. Returns bytes."""
    out = bytearray()
    i = 0
    n = len(data)

    while i < n:
        # Check for a run (3+ identical bytes to be worth encoding)
        if i + 2 < n and data[i] == data[i + 1] == data[i + 2]:
            val = data[i]
            run_len = 1
            while i + run_len < n and data[i + run_len] == val and run_len < 128:
                run_len += 1
            out.append(0x80 | (run_len - 1))
            out.append(val)
            i += run_len
        else:
            # Literal run: collect bytes until we hit a run of 3+
            lit_start = i
            while i < n and (i - lit_start) < 128:
                # Look ahead: if next 3 bytes are the same, stop literals
                if (i + 2 < n and data[i] == data[i + 1] == data[i + 2]):
                    break
                i += 1
            lit_len = i - lit_start
            if lit_len > 0:
                out.append(lit_len - 1)
                out.extend(data[lit_start:lit_start + lit_len])

    return bytes(out)


def rle_decompress(data):
    """Decompress RLE stream produced by rle_compress(). Returns bytes."""
    out = bytearray()
    i = 0
    n = len(data)

    while i < n:
        ctrl = data[i]
        i += 1
        if ctrl & 0x80:
            if i >= n:
                raise ValueError("RLE stream truncated in run token")
            count = (ctrl & 0x7F) + 1
            val = data[i]
            i += 1
            out.extend([val] * count)
        else:
            count = ctrl + 1
            if i + count > n:
                raise ValueError("RLE stream truncated in literal token")
            out.extend(data[i:i + count])
            i += count

    return bytes(out)


# ---------------------------------------------------------------------------
# LZ77 (LZSS) compressor
#
# Format (matching ngpc_lz_decompress):
#   While data remains:
#     Flag byte (8 bits, MSB first):
#       bit = 0: literal byte follows
#       bit = 1: match (2 bytes):
#         Byte 0: (offset_high << 4) | (length - 3)
#         Byte 1: offset_low
#         offset = ((b0 >> 4) << 8) | b1   (12-bit, 1-4096)
#         length = (b0 & 0x0F) + 3         (3-18 bytes)
#
# Window size: 4096 bytes
# Min match:   3 bytes
# Max match:   18 bytes
# ---------------------------------------------------------------------------

def lz77_find_match(data, pos, window_size=4096, max_len=18, min_len=3):
    """Find the longest match in the sliding window."""
    best_offset = 0
    best_length = 0
    n = len(data)

    start = max(0, pos - window_size)

    for j in range(start, pos):
        length = 0
        while (length < max_len and
               pos + length < n and
               data[j + length] == data[pos + length]):
            length += 1
        if length >= min_len and length > best_length:
            best_offset = pos - j
            best_length = length
            if length == max_len:
                break

    if best_length >= min_len:
        return best_offset, best_length
    return 0, 0


def lz77_compress(data):
    """Compress data using LZ77/LZSS. Returns bytes."""
    out = bytearray()
    i = 0
    n = len(data)

    while i < n:
        # Collect up to 8 items (literal or match) for one flag byte
        flag = 0
        items = bytearray()
        count = 0

        while count < 8 and i < n:
            offset, length = lz77_find_match(data, i)
            if length > 0:
                # Match
                flag |= (0x80 >> count)
                b0 = ((offset >> 8) << 4) | (length - 3)
                b1 = offset & 0xFF
                items.append(b0)
                items.append(b1)
                i += length
            else:
                # Literal
                items.append(data[i])
                i += 1
            count += 1

        out.append(flag)
        out.extend(items)

    return bytes(out)


def lz77_decompress(data):
    """Decompress LZ77/LZSS stream produced by lz77_compress(). Returns bytes."""
    out = bytearray()
    i = 0
    n = len(data)

    while i < n:
        flags = data[i]
        i += 1

        for bit in range(8):
            if i >= n:
                break

            if flags & (0x80 >> bit):
                if i + 1 >= n:
                    raise ValueError("LZ77 stream truncated in match token")
                b0 = data[i]
                b1 = data[i + 1]
                i += 2

                offset = ((b0 >> 4) << 8) | b1
                length = (b0 & 0x0F) + 3

                if offset == 0 or offset > len(out):
                    raise ValueError("LZ77 invalid offset %d at output %d" %
                                     (offset, len(out)))

                src_pos = len(out) - offset
                for _ in range(length):
                    out.append(out[src_pos])
                    src_pos += 1
            else:
                out.append(data[i])
                i += 1

    return bytes(out)


def sanitize_c_identifier(name):
    """Convert an arbitrary string into a valid C identifier."""
    name = re.sub(r"[^0-9A-Za-z_]", "_", name)
    if not name:
        name = "asset"
    if name[0].isdigit():
        name = "asset_" + name
    return name


def verify_roundtrip(raw, compressed, algo):
    """Validate compressor output by decoding and comparing to input."""
    if algo == "rle":
        decoded = rle_decompress(compressed)
    elif algo == "lz77":
        decoded = lz77_decompress(compressed)
    else:
        raise ValueError("Unknown algorithm for verification: %s" % algo)

    if decoded != raw:
        raise ValueError("Verification failed: decoded output mismatch")


# ---------------------------------------------------------------------------
# C output
# ---------------------------------------------------------------------------

def format_c_array(name, data, algo_label, raw_size):
    """Format compressed data as a C source file."""
    lines = []
    lines.append("/* Generated by ngpc_compress.py - do not edit */")
    lines.append("")
    lines.append('#include "ngpc_types.h"')
    lines.append("")
    lines.append("/* Algorithm: %s */" % algo_label)
    lines.append("/* %s_len = compressed size, %s_raw_len = decompressed size */" %
                 (name, name))
    lines.append("")
    lines.append("const u16 %s_len = %du;" % (name, len(data)))
    lines.append("const u16 %s_raw_len = %du;" % (name, raw_size))
    lines.append("")
    lines.append("const u8 %s[] = {" % name)

    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hex_vals = ", ".join("0x%02X" % b for b in chunk)
        if i + 16 < len(data):
            hex_vals += ","
        lines.append("    " + hex_vals)

    lines.append("};")
    lines.append("")
    return "\n".join(lines)


def format_c_header(name, algo_label):
    """Format a matching .h extern declaration."""
    guard = name.upper() + "_H"
    lines = []
    lines.append("/* Generated by ngpc_compress.py - do not edit */")
    lines.append("")
    lines.append("#ifndef %s" % guard)
    lines.append("#define %s" % guard)
    lines.append("")
    lines.append('#include "ngpc_types.h"')
    lines.append("")
    lines.append("extern const u16 %s_len;" % name)
    lines.append("extern const u16 %s_raw_len;" % name)
    lines.append("extern const u8 %s[];" % name)
    lines.append("")
    lines.append("#endif /* %s */" % guard)
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Compress tile data for NGPC (RLE or LZ77/LZSS)")
    parser.add_argument("input", help="Input binary file")
    parser.add_argument("-o", "--output", required=True,
                        help="Output .c file")
    parser.add_argument("-m", "--mode", choices=["rle", "lz77", "both"],
                        default="lz77",
                        help="Compression algorithm (default: lz77)")
    parser.add_argument("-n", "--name", default=None,
                        help="C array name (default: derived from filename)")
    parser.add_argument("--header", action="store_true",
                        help="Also generate a .h file with extern declarations")
    parser.add_argument("--no-verify", action="store_true",
                        help="Skip decode/compare verification step")
    args = parser.parse_args()

    # Read input
    with open(args.input, "rb") as f:
        raw = f.read()

    if len(raw) == 0:
        print("Error: input file is empty", file=sys.stderr)
        sys.exit(1)

    # Derive array name from filename if not specified
    if args.name:
        base_name = args.name
    else:
        base_name = os.path.splitext(os.path.basename(args.input))[0]
    base_name = sanitize_c_identifier(base_name)

    original_size = len(raw)

    if args.mode == "both":
        # Compress with both, pick the smaller one
        rle_data = rle_compress(raw)
        lz_data = lz77_compress(raw)

        print("Original:  %d bytes" % original_size)
        print("RLE:       %d bytes (%.1f%%)" % (
            len(rle_data), len(rle_data) / original_size * 100))
        print("LZ77:      %d bytes (%.1f%%)" % (
            len(lz_data), len(lz_data) / original_size * 100))

        if len(rle_data) <= len(lz_data):
            compressed = rle_data
            algo = "rle"
            print("Winner:    RLE")
            name = base_name + SUFFIX_RLE
        else:
            compressed = lz_data
            algo = "lz77"
            print("Winner:    LZ77")
            name = base_name + SUFFIX_LZ
    elif args.mode == "rle":
        compressed = rle_compress(raw)
        algo = "rle"
        name = base_name + SUFFIX_RLE
    else:
        compressed = lz77_compress(raw)
        algo = "lz77"
        name = base_name + SUFFIX_LZ

    ratio = len(compressed) / original_size * 100 if original_size > 0 else 0

    if not args.no_verify:
        verify_roundtrip(raw, compressed, algo)

    # Write .c
    c_src = format_c_array(name, compressed, algo, original_size)
    with open(args.output, "w") as f:
        f.write(c_src)

    # Write .h if requested
    if args.header:
        h_path = os.path.splitext(args.output)[0] + ".h"
        h_src = format_c_header(name, algo)
        with open(h_path, "w") as f:
            f.write(h_src)
        print("Header:    %s" % h_path)

    if args.mode != "both":
        print("Original:  %d bytes" % original_size)
        print("Compressed: %d bytes (%.1f%%)" % (len(compressed), ratio))

    print("Output:    %s  (array: %s, %d bytes)" % (
        args.output, name, len(compressed)))


if __name__ == "__main__":
    main()
