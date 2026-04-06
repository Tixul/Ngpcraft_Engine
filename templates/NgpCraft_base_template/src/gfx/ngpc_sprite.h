/*
 * ngpc_sprite.h - Sprite management
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * NGPC supports 64 sprites, each 8x8 pixels.
 * Sprites reference tiles from the same character RAM as scroll planes.
 */

#ifndef NGPC_SPRITE_H
#define NGPC_SPRITE_H

#include "ngpc_types.h"

/* Set a sprite's attributes.
 * id: sprite number (0-63)
 * x, y: screen position in pixels
 * tile: tile index (0-511)
 * pal: palette number (0-15)
 * flags: combination of SPR_FRONT/MID/BEHIND, SPR_HFLIP/VFLIP, SPR_HCHAIN/VCHAIN */
void ngpc_sprite_set(u8 id, u8 x, u8 y, u16 tile, u8 pal, u8 flags);

/* Move a sprite without changing its tile or flags. */
void ngpc_sprite_move(u8 id, u8 x, u8 y);

/* Hide a sprite (set priority to SPR_HIDE). */
void ngpc_sprite_hide(u8 id);

/* Hide all 64 sprites. */
void ngpc_sprite_hide_all(void);

/* Change flags (priority, flip) without touching position or tile.
 * flags: combination of SPR_FRONT/MID/BEHIND + SPR_HFLIP/VFLIP */
void ngpc_sprite_set_flags(u8 id, u8 flags);

/* Change tile index without touching position or flags. */
void ngpc_sprite_set_tile(u8 id, u16 tile);

/* Read back a sprite's current palette. */
u8 ngpc_sprite_get_pal(u8 id);

#endif /* NGPC_SPRITE_H */
