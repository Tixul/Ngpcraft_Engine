/*
 * ngpc_metasprite.h - Metasprite system (multi-tile sprite objects)
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * A metasprite is a group of 8x8 hardware sprites assembled into a
 * larger object (e.g. 16x16, 24x32, etc.). The system handles:
 *   - Positioning all parts relative to a center point
 *   - H/V flip of the entire group (swaps quad layout automatically)
 *   - Animation via frame tables
 *   - Hiding/showing entire groups
 *
 * Max 16 parts per metasprite (covers up to 32x32 px = 4x4 tiles).
 */

#ifndef NGPC_METASPRITE_H
#define NGPC_METASPRITE_H

#include "ngpc_types.h"
#include "ngpc_hw.h"     /* SPR_HFLIP, SPR_VFLIP, SPR_FRONT, etc. */

/* Maximum parts (8x8 sprites) per metasprite. */
#define MSPR_MAX_PARTS  16

/* A single part of a metasprite definition. */
typedef struct {
    s8  ox;         /* X offset from metasprite origin (signed) */
    s8  oy;         /* Y offset from metasprite origin (signed) */
    u16 tile;       /* Tile index (0-511) */
    u8  pal;        /* Palette number (0-15) */
    u8  flags;      /* Per-part flags (SPR_HFLIP etc, combined with group flags) */
} MsprPart;

/* A metasprite definition (const, stored in ROM). */
typedef struct {
    u8       count;                 /* Number of 8x8 parts */
    u8       width;                 /* Bounding box width in pixels (for flip calc) */
    u8       height;                /* Bounding box height in pixels (for flip calc) */
    MsprPart parts[MSPR_MAX_PARTS]; /* Part definitions */
} NgpcMetasprite;

/* A metasprite animation frame table entry. */
typedef struct {
    const NgpcMetasprite *frame;    /* Pointer to metasprite definition */
    u8 duration;                    /* Duration in frames (1-255) */
} MsprAnimFrame;

/* Draw a metasprite at screen position (x, y).
 * spr_start: first hardware sprite slot to use (0-63).
 * x, y: screen position of the metasprite origin.
 * def: pointer to metasprite definition.
 * flags: group-level flags (SPR_HFLIP, SPR_VFLIP, SPR_FRONT, etc.)
 *        H/V flip swaps part offsets automatically.
 * Returns: number of hardware sprites used. */
u8 ngpc_mspr_draw(u8 spr_start, s16 x, s16 y,
                   const NgpcMetasprite *def, u8 flags);

/* Hide a metasprite (hides spr_start..spr_start+count-1). */
void ngpc_mspr_hide(u8 spr_start, u8 count);

/* ---- Animation helpers ---- */

/* Metasprite animator state (one per animated object). */
typedef struct {
    const MsprAnimFrame *anim;  /* Current animation table */
    u8  frame_count;            /* Number of frames in animation */
    u8  current;                /* Current frame index */
    u8  timer;                  /* Countdown to next frame */
    u8  loop;                   /* 1 = loop, 0 = stop at last frame */
} MsprAnimator;

/* Start an animation.
 * anim: array of MsprAnimFrame entries.
 * count: number of entries.
 * loop: 1 = loop, 0 = play once. */
void ngpc_mspr_anim_start(MsprAnimator *a, const MsprAnimFrame *anim,
                           u8 count, u8 loop);

/* Tick the animator (call once per frame).
 * Returns: pointer to the current metasprite definition. */
const NgpcMetasprite *ngpc_mspr_anim_update(MsprAnimator *a);

/* Check if a non-looping animation has finished. */
u8 ngpc_mspr_anim_done(const MsprAnimator *a);

#endif /* NGPC_METASPRITE_H */
