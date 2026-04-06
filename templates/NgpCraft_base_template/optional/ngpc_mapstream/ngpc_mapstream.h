/*
 * ngpc_mapstream.h - Streaming tilemap for maps larger than 32x32 tiles
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * The NGPC scroll planes are each 32x32 tiles (256x256 px), toroidal.
 * This module streams new columns / rows into VRAM as the camera moves,
 * allowing maps of any size stored in ROM.
 *
 * Technique:
 *   - World tile (wx, wy) maps to VRAM slot (wx % 32, wy % 32)
 *   - When the camera scrolls right by 1 tile, the new right-edge column
 *     is written to the VRAM column that just "wrapped around" (hidden)
 *   - Same principle for left / up / down
 *   - Init: blits the initial visible viewport + 1-tile margin
 *
 * Map data format (map_tiles[]):
 *   Row-major array of u16 tilewords in K2GE scroll-plane format,
 *   same as produced by ngpc_tilemap.py:
 *     bits  7:0  = tile index low 8 bits
 *     bit   8    = tile index bit 8
 *     bits 12:9  = palette index (0-15)
 *     bit  14    = V flip
 *     bit  15    = H flip
 *   IMPORTANT: the tile index must be ABSOLUTE (tile base already baked in).
 *   The PNG Manager exporter handles this automatically.
 *
 * Index arithmetic:
 *   map_tiles[wy * map_w + wx]
 *   Safe for maps up to 256x256 tiles (u16 index, max 65535).
 *   Larger maps require a custom u32-index variant.
 *
 * Usage:
 *   // Scene init:
 *   NgpcMapStream g_ms;
 *   ngpc_mapstream_init(&g_ms, GFX_SCR1,
 *                       g_level1_bg_map, 128, 32,
 *                       cam_px, cam_py);
 *
 *   // Main loop (call AFTER ngpc_vsync()):
 *   ngpc_mapstream_update(&g_ms, cam_px, cam_py);
 *
 * Makefile:
 *   OBJS += src/ngpc_mapstream/ngpc_mapstream.rel
 */

#ifndef NGPC_MAPSTREAM_H
#define NGPC_MAPSTREAM_H

#include "../../src/core/ngpc_types.h"
#include "../../src/gfx/ngpc_gfx.h"  /* GFX_SCR1, GFX_SCR2, NGP_FAR */

/* Maximum tiles-per-frame the camera can travel and still stream correctly.
 * If the camera moves faster than this (e.g. scene teleport), call
 * ngpc_mapstream_init() again to force a full viewport re-blit.
 * At 8px/tile and 60fps, 10 tiles = 80px/frame = 4800px/s — well above
 * any realistic smooth-scroll speed. */
#ifndef NGPC_MAPSTREAM_MAX_DELTA
#define NGPC_MAPSTREAM_MAX_DELTA 10u
#endif

typedef struct {
    /* NOTE: map_tiles FAR pointer is stored as a module-static in .c
     * (cc900 truncates __far pointers in struct fields to 16-bit near). */
    u16 map_w;       /* map width  in tiles (max 256, u16 safe) */
    u16 map_h;       /* map height in tiles (max 256, u16 safe) */
    s16 prev_cam_tx; /* last camera position, tiles X           */
    s16 prev_cam_ty; /* last camera position, tiles Y           */
    u8  plane;       /* GFX_SCR1 or GFX_SCR2                   */
} NgpcMapStream;

/* Initialise the stream and blit the initial viewport into VRAM.
 * Call once at scene load, before the first ngpc_vsync().
 * cam_px/cam_py: camera pixel position (top-left corner of the screen). */
void ngpc_mapstream_init(NgpcMapStream *ms, u8 plane,
                         const u16 NGP_FAR *map_tiles,
                         u16 map_w, u16 map_h,
                         s16 cam_px, s16 cam_py);

/* Stream new columns / rows based on camera movement.
 * Call every frame AFTER ngpc_vsync() and before drawing.
 * map_tiles: same FAR pointer passed to ngpc_mapstream_init().
 * cam_px/cam_py: current camera pixel position. */
void ngpc_mapstream_update(NgpcMapStream *ms,
                           const u16 NGP_FAR *map_tiles,
                           s16 cam_px, s16 cam_py);

/* ---- Camera bounds helpers ---- */
/*
 * Maximum valid camera pixel position (top-left corner of the screen) before
 * the viewport would show tiles beyond the map edge.
 *
 * Sonic disassembly §9.6: camera is clamped to [min_x..max_x] / [min_y..max_y]
 * before the streaming trigger fires.  Without clamping the camera can move into
 * the OOB region (ms_get returns 0 = blank tile), but scroll regs still advance,
 * visually showing a black strip at the edge.
 *
 * ms: pointer to NgpcMapStream (must be initialized before use).
 *
 * Usage:
 *   cam_px = NGPC_MS_CLAMP_X(&g_ms, cam_px);
 *   cam_py = NGPC_MS_CLAMP_Y(&g_ms, cam_py);
 *   ngpc_mapstream_update(&g_ms, map_tiles, cam_px, cam_py);
 */
#define NGPC_MS_CAM_MAX_X(ms) \
    ((s16)(((s16)(ms)->map_w - (s16)SCREEN_TW) << 3))
#define NGPC_MS_CAM_MAX_Y(ms) \
    ((s16)(((s16)(ms)->map_h - (s16)SCREEN_TH) << 3))

#define NGPC_MS_CLAMP_X(ms, px) \
    ((s16)((px) < (s16)0 ? (s16)0 \
         : (px) > NGPC_MS_CAM_MAX_X(ms) ? NGPC_MS_CAM_MAX_X(ms) \
         : (px)))
#define NGPC_MS_CLAMP_Y(ms, py) \
    ((s16)((py) < (s16)0 ? (s16)0 \
         : (py) > NGPC_MS_CAM_MAX_Y(ms) ? NGPC_MS_CAM_MAX_Y(ms) \
         : (py)))

/* Restore a single world tile (wx, wy) from the map ROM into VRAM.
 * Use this to undo tile corruption from text overlays or other direct VRAM
 * writes. wx/wy: world tile coordinates (out-of-bounds writes 0 safely).
 * Typical use: restore tiles overwritten by a debug text overlay before
 * writing the next frame's text to the same world position. */
void ngpc_mapstream_write_tile(const NgpcMapStream *ms,
                               const u16 NGP_FAR *map_tiles,
                               s16 wx, s16 wy);

#endif /* NGPC_MAPSTREAM_H */
