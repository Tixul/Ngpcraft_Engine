/*
 * ngpc_timing.h - VSync synchronization and CPU speed control
 *
 * Part of NgpCraft_base_template (MIT License)
 */

#ifndef NGPC_TIMING_H
#define NGPC_TIMING_H

#include "ngpc_types.h"

/* Wait for the next vertical blank interrupt.
 * Busy-waits until g_vb_counter changes.
 * This is the standard way to sync to 60 fps. */
void ngpc_vsync(void);

/* Check if currently in vertical blank period.
 * Returns 1 if vblank active, 0 if displaying. */
u8 ngpc_in_vblank(void);

/* Sleep for n frames (at reduced CPU speed to save battery). */
void ngpc_sleep(u8 frames);

/* Set CPU clock speed.
 *   0 = 6.144 MHz (full speed)
 *   1 = 3.072 MHz
 *   2 = 1.536 MHz
 *   3 = 0.768 MHz
 *   4 = 0.384 MHz (slowest)
 * Uses BIOS VECT_CLOCKGEARSET. */
void ngpc_cpu_speed(u8 divider);

#endif /* NGPC_TIMING_H */
