/* ngpc_tilemap_blit.h - Safe tilemap blitting helpers (macro-based)
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Why macros?
 * - cc900 has near/far memory models. Some const assets live in ROM at 0x200000+.
 * - Passing pointers to ROM data through generic helper functions can truncate
 *   addresses (near pointer), causing reads from the wrong location.
 * - This header provides a "windjammer-style" path that directly indexes the
 *   generated symbols (prefix_tiles/map/pals/...) in the caller TU.
 *
 * Generated asset contract (tools/ngpc_tilemap.py):
 *   prefix_tiles_count = number of u16 words (8 words per tile)
 *   prefix_tiles[]     = u16 words, NGPC tile format (8 rows)
 *   prefix_map_w/h/len, prefix_map_tiles[], prefix_map_pals[]
 *   prefix_palette_count, prefix_palettes[] (RGB444, 4 entries per palette)
 *
 * Use:
 *   #include "ngpc_tilemap_blit.h"
 *   NGP_TILEMAP_BLIT_SCR1(my_asset, 128);
 */

#ifndef NGPC_TILEMAP_BLIT_H
#define NGPC_TILEMAP_BLIT_H

#include "ngpc_hw.h"
#include "ngpc_gfx.h"

/* Copy u16 tile words to Character RAM using explicit byte writes.
 * tile_base is a tile index (0-511). */
#define NGP_TILEMAP_LOAD_TILES_VRAM(prefix, tile_base)                           \
    do {                                                                         \
        u16 __tile;                                                              \
        u16 __tiles = (u16)((prefix##_tiles_count) / TILE_WORDS);                \
        for (__tile = 0; __tile < __tiles; __tile++) {                           \
            volatile u8 *__dst = (volatile u8 *)(                                \
                0xA000u + (u32)((u16)(tile_base) + __tile) * 16u);               \
            u16 __w;                                                             \
            for (__w = 0; __w < TILE_WORDS; __w++) {                             \
                u16 __v = (prefix##_tiles[(u16)(__tile * TILE_WORDS + __w)]);    \
                __dst[(u16)(__w * 2u) + 0u] = (u8)(__v & 0xFFu);                 \
                __dst[(u16)(__w * 2u) + 1u] = (u8)(__v >> 8);                    \
            }                                                                    \
        }                                                                        \
    } while (0)

#define NGP_TILEMAP_LOAD_PALETTES_SCR1(prefix)                                   \
    do {                                                                         \
        u16 __i;                                                                 \
        for (__i = 0; __i < (u16)(prefix##_palette_count); __i++) {              \
            ngpc_gfx_set_palette(                                                \
                GFX_SCR1,                                                        \
                (u8)__i,                                                         \
                prefix##_palettes[(u16)(__i * 4u) + 0u],                         \
                prefix##_palettes[(u16)(__i * 4u) + 1u],                         \
                prefix##_palettes[(u16)(__i * 4u) + 2u],                         \
                prefix##_palettes[(u16)(__i * 4u) + 3u]);                        \
        }                                                                        \
    } while (0)

#define NGP_TILEMAP_LOAD_PALETTES_SCR2(prefix)                                   \
    do {                                                                         \
        u16 __i;                                                                 \
        for (__i = 0; __i < (u16)(prefix##_palette_count); __i++) {              \
            ngpc_gfx_set_palette(                                                \
                GFX_SCR2,                                                        \
                (u8)__i,                                                         \
                prefix##_palettes[(u16)(__i * 4u) + 0u],                         \
                prefix##_palettes[(u16)(__i * 4u) + 1u],                         \
                prefix##_palettes[(u16)(__i * 4u) + 2u],                         \
                prefix##_palettes[(u16)(__i * 4u) + 3u]);                        \
        }                                                                        \
    } while (0)

/* Write the visible map area into the plane's 32x32 VRAM map.
 * Guard: skips tiles whose source coordinates exceed 32x32 — those belong
 * to maps larger than the hardware tilemap and must be handled by streaming. */
#define NGP_TILEMAP_PUT_MAP_SCR1(prefix, tile_base)                              \
    do {                                                                         \
        u16 __i;                                                                 \
        for (__i = 0; __i < (u16)(prefix##_map_len); __i++) {                    \
            u8 __x = (u8)(__i % (u16)(prefix##_map_w));                          \
            u8 __y = (u8)(__i / (u16)(prefix##_map_w));                          \
            u16 __off;                                                           \
            u16 __tile;                                                          \
            u16 __pal;                                                           \
            if (__x >= 32u || __y >= 32u) continue;                              \
            __off  = (u16)__y * 32u + (u16)__x;                                  \
            __tile = (u16)((u16)(tile_base) + prefix##_map_tiles[__i]);          \
            __pal  = (u16)(prefix##_map_pals[__i] & 0x0Fu);                      \
            HW_SCR1_MAP[__off] = (u16)(__tile + (__pal << 9));                   \
        }                                                                        \
    } while (0)

#define NGP_TILEMAP_PUT_MAP_SCR2(prefix, tile_base)                              \
    do {                                                                         \
        u16 __i;                                                                 \
        for (__i = 0; __i < (u16)(prefix##_map_len); __i++) {                    \
            u8 __x = (u8)(__i % (u16)(prefix##_map_w));                          \
            u8 __y = (u8)(__i / (u16)(prefix##_map_w));                          \
            u16 __off;                                                           \
            u16 __tile;                                                          \
            u16 __pal;                                                           \
            if (__x >= 32u || __y >= 32u) continue;                              \
            __off  = (u16)__y * 32u + (u16)__x;                                  \
            __tile = (u16)((u16)(tile_base) + prefix##_map_tiles[__i]);          \
            __pal  = (u16)(prefix##_map_pals[__i] & 0x0Fu);                      \
            HW_SCR2_MAP[__off] = (u16)(__tile + (__pal << 9));                   \
        }                                                                        \
    } while (0)

/* Convenience: load tiles + palettes + map for a single-layer background. */
#define NGP_TILEMAP_BLIT_SCR1(prefix, tile_base)                                 \
    do {                                                                         \
        NGP_TILEMAP_LOAD_TILES_VRAM(prefix, tile_base);                          \
        NGP_TILEMAP_LOAD_PALETTES_SCR1(prefix);                                  \
        NGP_TILEMAP_PUT_MAP_SCR1(prefix, tile_base);                             \
    } while (0)

#define NGP_TILEMAP_BLIT_SCR2(prefix, tile_base)                                 \
    do {                                                                         \
        NGP_TILEMAP_LOAD_TILES_VRAM(prefix, tile_base);                          \
        NGP_TILEMAP_LOAD_PALETTES_SCR2(prefix);                                  \
        NGP_TILEMAP_PUT_MAP_SCR2(prefix, tile_base);                             \
    } while (0)

#endif /* NGPC_TILEMAP_BLIT_H */

