/*
 * carthdr.h - NGPC cartridge ROM header
 *
 * Part of NgpCraft_base_template (MIT License)
 * Format defined by SNK BIOS, documented in ngpcspec.txt "Cart ROM Header Info".
 *
 * The linker places these constants at 0x200000 (start of cart ROM).
 * The BIOS reads this header to identify the cartridge and find the entry point.
 *
 * IMPORTANT: CartTitle must be exactly 12 ASCII characters (pad with spaces).
 */

#ifndef CARTHDR_H
#define CARTHDR_H

#include "ngpc_types.h"

extern void main(void);

/* 28 bytes: license string (third-party use) */
const char Licensed[28] = " LICENSED BY SNK CORPORATION";

/* 4 bytes: entry point (the BIOS jumps here after boot) */
const FuncPtr EntryPoint = main;

/* 2 bytes: game ID (0x0000 = development/homebrew) */
const short CartID = 0x0000;

/* 1 byte: version sub-code */
/* 1 byte: system code (0x00 = monochrome, 0x10 = color) */
const short CartSystem = 0x1000;

/* 12 bytes: game title (pad with spaces to exactly 12 chars) */
const char CartTitle[12] = "NGPC2026    ";

/* 16 bytes: reserved (must be zero) */
const long CartReserved[4] = { 0, 0, 0, 0 };

#endif /* CARTHDR_H */
