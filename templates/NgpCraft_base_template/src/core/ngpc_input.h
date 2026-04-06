/*
 * ngpc_input.h - Joypad input with edge detection
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * Call ngpc_input_update() once per frame (in VBI or before game logic).
 * Then use ngpc_pad_held/pressed/released to read button state.
 */

#ifndef NGPC_INPUT_H
#define NGPC_INPUT_H

#include "ngpc_types.h"

/* Current button state (held this frame). */
extern u8 ngpc_pad_held;

/* Buttons newly pressed this frame (rising edge). */
extern u8 ngpc_pad_pressed;

/* Buttons released this frame (falling edge). */
extern u8 ngpc_pad_released;

/* Buttons auto-repeated this frame (menu-style repeat). */
extern u8 ngpc_pad_repeat;

/* Configure auto-repeat timing (frames). */
void ngpc_input_set_repeat(u8 delay, u8 rate);

/* Read joypad and compute edges. Call once per frame. */
void ngpc_input_update(void);

#endif /* NGPC_INPUT_H */
