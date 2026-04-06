/*
 * ngpc_mapstream.c - Streaming tilemap for maps larger than 32x32 tiles
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * ── VRAM addressing ──────────────────────────────────────────────────────────
 *
 *   The K2GE tilemap is a 32×32 ring (toroidal).  Tile (vc, vr):
 *     word index = vr * 32 + vc
 *     byte addr  = vr * 0x40 + vc * 2      (for reference; we index as u16*)
 *
 *   World tile (wx, wy) maps to VRAM slot:
 *     vc = wx & 0x1F   (wx % 32)
 *     vr = wy & 0x1F   (wy % 32)
 *
 *   The hardware scroll registers hold the top-left pixel of the viewport and
 *   wrap the 32×32 ring toroidally.  Placing world tile (wx,wy) at slot
 *   (wx%32, wy%32) means the hardware automatically reads the right tile at
 *   every screen position — no software coordinate conversion needed per pixel.
 *
 * ── VRAM invariant ───────────────────────────────────────────────────────────
 *
 *   At all times, VRAM contains the world columns [cam_tx-1 .. cam_tx+20]
 *   and world rows [cam_ty-1 .. cam_ty+19].
 *   That is: 1 tile of left/top margin + 20/19 visible tiles + 1 tile of
 *   right/bottom margin.
 *
 *   Screen: 160×152 px = 20×19 tiles.
 *   Visible columns: cam_tx .. cam_tx+19  (rightmost = floor((cam_px+159)/8))
 *   Visible rows:    cam_ty .. cam_ty+18  (bottommost = floor((cam_py+151)/8))
 *
 *   The 1-tile right/bottom margin is critical for sub-tile scroll:
 *   even with cam_tx unchanged, cam_px can be up to cam_tx*8+7, making the
 *   rightmost visible tile cam_tx+19 (floor((cam_tx*8+7+159)/8) = cam_tx+20).
 *   That column is always pre-loaded in VRAM.
 *
 * ── Streaming strategy ───────────────────────────────────────────────────────
 *
 *   ngpc_mapstream_update() detects delta tile movement (dx, dy) and streams
 *   the new leading-edge column or row:
 *
 *     Right (dx>0): stream world column prev_cam_tx+21+i  (= cam_tx+20+i)
 *     Left  (dx<0): stream world column prev_cam_tx-2-i
 *     Down  (dy>0): stream world row    prev_cam_ty+20+i  (= cam_ty+19+i)
 *     Up    (dy<0): stream world row    prev_cam_ty-2-i
 *
 *   !! HISTORICAL BUG (fixed 2026-03-16) !!
 *   The original formulas were +20/-1/+19/-1 (off by 1 in all 4 directions).
 *   Those formulas re-streamed tiles already in VRAM (the old margin tile)
 *   instead of the NEW margin tile one step further.  Result: the VRAM slot
 *   for the true leading edge always contained stale data from the previous
 *   scroll cycle, causing 1-tile-wide glitching columns/rows at the edge of
 *   the screen whenever the camera crossed a tile boundary.
 *
 *   Why +21 for right movement?
 *     After init at cam_tx=T: VRAM has [T-1 .. T+20].
 *     After cam_tx advances to T+1: need [T .. T+21].
 *     New column to write = T+21 = prev_cam_tx+21.   ← correct
 *     Old (buggy) value T+20 = prev_cam_tx+20 was already present.
 *
 * ── VBlank commit pattern ─────────────────────────────────────────────────────
 *
 *   ngpc_mapstream_update() MUST be called immediately after ngpc_vsync()
 *   returns, BEFORE ngpng_apply_plane_scroll(), and BEFORE any game logic
 *   that computes the new camera position.  Correct order each frame:
 *
 *     ngpc_vsync();
 *     ngpc_mapstream_update(..., cam_px, cam_py);   // ← prev-frame camera
 *     ngpng_apply_plane_scroll(..., cam_px, cam_py); // ← same prev-frame camera
 *     // game logic runs, computes new cam_px/cam_py
 *     // new camera takes effect next VBlank
 *
 *   If update() and apply_plane_scroll() run during active scan (after game
 *   logic), the scroll register is updated before the tile write completes,
 *   revealing an un-populated VRAM slot — same leading-edge glitch.
 *
 *   Calling both with the SAME cam_px (prev frame) guarantees:
 *     1. Tiles for the new scroll position are in VRAM.
 *     2. Scroll register is set to that position.
 *     3. Active scan starts seeing correct tiles with zero tearing.
 *
 * ── VBlank budget ─────────────────────────────────────────────────────────────
 *
 *   Worst case per frame (dx=1): 1 column × 21 rows = 21 word writes = 42 B.
 *   At NGPC 6 MHz: well within the ~1.5 ms VBlank window even with OAM flush.
 *   MAX_DELTA=10: up to 210 writes, still safe (teleports should re-call init).
 *
 * ── FAR pointer note ──────────────────────────────────────────────────────────
 *
 *   cc900 truncates __far pointers when stored in struct fields, static
 *   variables, or arrays.  map_tiles is therefore passed as a function
 *   parameter at every call site — never stored between calls.
 *   The caller must also declare the array with NGP_FAR at the call site,
 *   otherwise cc900 emits a 16-bit near push, corrupting the ROM address.
 */

#include "ngpc_mapstream.h"
#include "../../src/core/ngpc_hw.h"

/* ---- Internal helpers ---- */

static volatile u16 *ms_map_base(u8 plane)
{
    return (volatile u16 *)(plane == GFX_SCR1
                            ? (u16)0x9000u
                            : (u16)0x9800u);
}

/* Write one tileword to VRAM at slot (vc, vr).
 * Tilemap VRAM (0x9000/0x9800) requires 16-bit (word) writes. */
static void ms_put(volatile u16 *base, u8 vc, u8 vr, u16 tw)
{
    u16 idx = (u16)((u16)vr * 0x20u + (u16)vc);
    base[idx] = tw;
}

/* Read tileword from large map ROM.  Returns 0 (empty) if out of bounds.
 * map_tiles is passed by the caller — never stored (cc900 far ptr issue). */
static u16 ms_get(const u16 NGP_FAR *map_tiles, u16 map_w, u16 map_h,
                  s16 wx, s16 wy)
{
    u16 idx;
    if (wx < 0 || (u16)wx >= map_w) return 0u;
    if (wy < 0 || (u16)wy >= map_h) return 0u;
    idx = (u16)((u16)wy * map_w + (u16)wx);
    return map_tiles[idx];
}

/* Write world column wx to VRAM, for rows near cam_ty.
 * Covers rows [cam_ty-1 .. cam_ty+19] = 21 rows (viewport + 1 margin each). */
static void ms_stream_col(const NgpcMapStream *ms,
                          const u16 NGP_FAR *map_tiles,
                          s16 wx, s16 cam_ty)
{
    volatile u16 *base = ms_map_base(ms->plane);
    u8  vc = (u8)((u16)wx & 0x1Fu);
    s16 wy;
    s16 wy_end = (s16)(cam_ty + 20); /* exclusive: cam_ty+19 is last visible */

    for (wy = (s16)(cam_ty - 1); wy < wy_end; wy++) {
        u8 vr = (u8)((u16)wy & 0x1Fu);
        ms_put(base, vc, vr, ms_get(map_tiles, ms->map_w, ms->map_h, wx, wy));
    }
}

/* Write world row wy to VRAM, for columns near cam_tx.
 * Covers cols [cam_tx-1 .. cam_tx+20] = 22 cols (viewport + 1 margin each). */
static void ms_stream_row(const NgpcMapStream *ms,
                          const u16 NGP_FAR *map_tiles,
                          s16 wy, s16 cam_tx)
{
    volatile u16 *base = ms_map_base(ms->plane);
    u8  vr = (u8)((u16)wy & 0x1Fu);
    s16 wx;
    s16 wx_end = (s16)(cam_tx + 21); /* exclusive: cam_tx+19 is last visible */

    for (wx = (s16)(cam_tx - 1); wx < wx_end; wx++) {
        u8 vc = (u8)((u16)wx & 0x1Fu);
        ms_put(base, vc, vr, ms_get(map_tiles, ms->map_w, ms->map_h, wx, wy));
    }
}

/* ---- Public API ---- */

void ngpc_mapstream_init(NgpcMapStream *ms, u8 plane,
                         const u16 NGP_FAR *map_tiles,
                         u16 map_w, u16 map_h,
                         s16 cam_px, s16 cam_py)
{
    volatile u16 *base;
    s16 wx, wy;
    s16 tx = (s16)(cam_px >> 3);
    s16 ty = (s16)(cam_py >> 3);

    ms->map_w       = map_w;
    ms->map_h       = map_h;
    ms->plane       = plane;
    ms->prev_cam_tx = tx;
    ms->prev_cam_ty = ty;

    base = ms_map_base(plane);

    /* Blit the visible viewport + 1-tile margin on each edge.
     * 22 cols x 21 rows = 462 tile writes — call from scene init, not VBlank. */
    for (wy = (s16)(ty - 1); wy < (s16)(ty + 20); wy++) {
        for (wx = (s16)(tx - 1); wx < (s16)(tx + 21); wx++) {
            u8 vc = (u8)((u16)wx & 0x1Fu);
            u8 vr = (u8)((u16)wy & 0x1Fu);
            ms_put(base, vc, vr,
                   ms_get(map_tiles, map_w, map_h, wx, wy));
        }
    }
}

void ngpc_mapstream_update(NgpcMapStream *ms,
                           const u16 NGP_FAR *map_tiles,
                           s16 cam_px, s16 cam_py)
{
    s16 cam_tx = (s16)(cam_px >> 3);
    s16 cam_ty = (s16)(cam_py >> 3);
    s16 dx = (s16)(cam_tx - ms->prev_cam_tx);
    s16 dy = (s16)(cam_ty - ms->prev_cam_ty);
    s16 i;

    /* Clamp: if camera jumps > MAX_DELTA tiles, stream what we can.
     * Call ngpc_mapstream_init() again after a scene teleport. */
    if (dx >  (s16)NGPC_MAPSTREAM_MAX_DELTA) dx =  (s16)NGPC_MAPSTREAM_MAX_DELTA;
    if (dx < -(s16)NGPC_MAPSTREAM_MAX_DELTA) dx = -(s16)NGPC_MAPSTREAM_MAX_DELTA;
    if (dy >  (s16)NGPC_MAPSTREAM_MAX_DELTA) dy =  (s16)NGPC_MAPSTREAM_MAX_DELTA;
    if (dy < -(s16)NGPC_MAPSTREAM_MAX_DELTA) dy = -(s16)NGPC_MAPSTREAM_MAX_DELTA;

    /* Horizontal streaming */
    if (dx > 0) {
        /* Scrolled right: stream the column entering on the right edge.
         * +21 not +20: prev_cam_tx+20 was already blitted; the NEW margin
         * column is prev_cam_tx+21 (= cam_tx+20). */
        for (i = 0; i < dx; i++)
            ms_stream_col(ms, map_tiles, (s16)(ms->prev_cam_tx + 21 + i), cam_ty);
    } else if (dx < 0) {
        /* Scrolled left: stream the column entering on the left edge.
         * -2 not -1: prev_cam_tx-1 was already blitted; new margin = -2. */
        for (i = 0; i > dx; i--)
            ms_stream_col(ms, map_tiles, (s16)(ms->prev_cam_tx + i - 2), cam_ty);
    }

    /* Vertical streaming */
    if (dy > 0) {
        /* Scrolled down: stream the row entering at the bottom edge.
         * +20 not +19: prev_cam_ty+19 was already blitted; new margin = +20. */
        for (i = 0; i < dy; i++)
            ms_stream_row(ms, map_tiles, (s16)(ms->prev_cam_ty + 20 + i), cam_tx);
    } else if (dy < 0) {
        /* Scrolled up: stream the row entering at the top edge.
         * -2 not -1: prev_cam_ty-1 was already blitted; new margin = -2. */
        for (i = 0; i > dy; i--)
            ms_stream_row(ms, map_tiles, (s16)(ms->prev_cam_ty + i - 2), cam_tx);
    }

    ms->prev_cam_tx = cam_tx;
    ms->prev_cam_ty = cam_ty;
}

void ngpc_mapstream_write_tile(const NgpcMapStream *ms,
                               const u16 NGP_FAR *map_tiles,
                               s16 wx, s16 wy)
{
    volatile u16 *base = ms_map_base(ms->plane);
    u8 vc = (u8)((u16)wx & 0x1Fu);
    u8 vr = (u8)((u16)wy & 0x1Fu);
    ms_put(base, vc, vr, ms_get(map_tiles, ms->map_w, ms->map_h, wx, wy));
}
