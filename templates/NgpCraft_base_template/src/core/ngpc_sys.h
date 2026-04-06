/*
 * ngpc_sys.h - System initialization, VBI handler, shutdown
 *
 * Part of NgpCraft_base_template (MIT License)
 */

#ifndef NGPC_SYS_H
#define NGPC_SYS_H

#include "ngpc_types.h"

/* Frame counter, incremented by VBI at 60 Hz. */
extern volatile u8 g_vb_counter;

/* Apply power-off bug patch for prototype firmware (OS_Version == 0x00).
 * Safe no-op on all retail hardware. Call once at startup before ngpc_init().
 * Equivalent to SYS_PATCH from system.lib (SNK, 1998). */
void ngpc_sys_patch(void);

/* Initialize NGPC hardware:
 * - Detects mono/color mode
 * - Installs interrupt vectors (VBL mandatory)
 * - Sets viewport to 160x152
 * - Enables interrupts
 * Call this first in main(). */
void ngpc_init(void);

/* Returns 1 if running on NGPC Color, 0 if monochrome NGP. */
u8 ngpc_is_color(void);

/* Returns LANG_ENGLISH (0) or LANG_JAPANESE (1).
 * Value is read once from BIOS register 0x6F87 during ngpc_init() and cached.
 * Use this to select localized strings or assets at startup. */
u8 ngpc_get_language(void);

/* Perform system shutdown via BIOS. Call when USR_SHUTDOWN is set. */
void ngpc_shutdown(void);

/* Call BIOS to load the built-in system font into tile RAM. */
void ngpc_load_sysfont(void);

/* Copy len bytes from src to dst (no alignment required). */
void ngpc_memcpy(u8 *dst, const u8 *src, u16 len);

/* Fill len bytes at dst with val. */
void ngpc_memset(u8 *dst, u8 val, u16 len);

#endif /* NGPC_SYS_H */
