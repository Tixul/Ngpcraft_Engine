/* ngpng_triggers.h -- Trigger condition evaluator and scroll/scene state helpers.
 * Part of the ngpng static module layer (NGPC PNG Manager).
 * Overwritten on next export -- do not hand-edit.
 */
#ifndef NGPNG_TRIGGERS_H
#define NGPNG_TRIGGERS_H

#include "ngpc_hw.h"        /* u8, s8, s16, u16, PAD_* (found via -Isrc/core) */
#include "scenes_autogen.h" /* NgpSceneDef, TRIG_*, NgpngTrigger (found via -IGraphX) */

/* ---- Scroll / scene state ---- */
void ngpng_reset_scene_scroll_state(const NgpSceneDef *sc,
    u8 *forced_scroll_on, u8 *scroll_paused,
    s16 *scroll_speed_x, s16 *scroll_speed_y);

/* ---- Trigger state (compiled only when NGPNG_HAS_TRIGGERS) ---- */
#if NGPNG_HAS_TRIGGERS

void ngpng_reset_trigger_state(u8 *trig_state, u8 *trig_enabled, u8 *reg_state);
/* npc_talked    : bitmask — bit N set when prop src_idx==N is within 24px AND PAD_A pressed.
 * entity_contact: bitmask — bit N set when player AABB overlaps prop src_idx==N AABB.
 * Both computed in ngpng_autorun_main before the trigger loop. */
u8   ngpng_trigger_cond_met(u8 cond, u8 region, u16 value,
    const u8 *in_reg, const u8 *prev_reg, u8 reg_n,
    u16 tx, u16 ty, u16 timer, u8 next_wave,
    u8 player_hp, u8 lives, u8 enemy_active_count,
    u16 collectible_count, u16 pad_pressed, u8 player_jump_started,
    u16 npc_talked, u16 entity_contact, u8 dlg_done);

#endif /* NGPNG_HAS_TRIGGERS */

#endif /* NGPNG_TRIGGERS_H */
