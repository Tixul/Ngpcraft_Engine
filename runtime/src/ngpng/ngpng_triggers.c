/* ngpng_triggers.c -- Trigger condition evaluator and scroll/scene state helpers.
 * Part of the ngpng static module layer (NGPC PNG Manager).
 * Overwritten on next export -- do not hand-edit.
 *
 * Project-specific sizing (NGPNG_AUTORUN_MAX_TRIG, NGPNG_AUTORUN_MAX_REG) and
 * NGPNG_HAS_TRIGGERS are injected via Makefile CDEFS on export.
 * The #ifndef fallbacks below match the default layout (64 triggers, 64 regions).
 */
#include "ngpng_triggers.h"

/* ---- Sizing fallbacks (real values come from Makefile CDEFS) ---- */
#ifndef NGPNG_AUTORUN_MAX_TRIG
#define NGPNG_AUTORUN_MAX_TRIG 64u
#endif
#ifndef NGPNG_AUTORUN_MAX_REG
#define NGPNG_AUTORUN_MAX_REG 64u
#endif

/* ==========================================================================
 * Scroll / scene state (always compiled)
 * ========================================================================== */

void ngpng_reset_scene_scroll_state(const NgpSceneDef *sc,
    u8 *forced_scroll_on, u8 *scroll_paused,
    s16 *scroll_speed_x, s16 *scroll_speed_y)
{
    if (!sc) {
        *forced_scroll_on = 0u;
        *scroll_paused    = 0u;
        *scroll_speed_x   = 0;
        *scroll_speed_y   = 0;
        return;
    }
    *forced_scroll_on = sc->forced_scroll ? 1u : 0u;
    *scroll_paused    = 0u;
    *scroll_speed_x   = sc->scroll_speed_x;
    *scroll_speed_y   = sc->scroll_speed_y;
}

/* ==========================================================================
 * Trigger state (compiled only when NGPNG_HAS_TRIGGERS)
 * ========================================================================== */
#if NGPNG_HAS_TRIGGERS

void ngpng_reset_trigger_state(u8 *trig_state, u8 *trig_enabled, u8 *reg_state)
{
    u8 i;
    for (i = 0; i < (u8)NGPNG_AUTORUN_MAX_TRIG; ++i) {
        trig_state[i]   = 0u;
        trig_enabled[i] = 1u;
    }
    for (i = 0; i < (u8)NGPNG_AUTORUN_MAX_REG; ++i) reg_state[i] = 0u;
}

u8 ngpng_trigger_cond_met(u8 cond, u8 region, u16 value,
    const u8 *in_reg, const u8 *prev_reg, u8 reg_n,
    u16 tx, u16 ty, u16 timer, u8 next_wave,
    u8 player_hp, u8 lives, u8 enemy_active_count,
    u16 collectible_count, u16 pad_pressed, u8 player_jump_started,
    u16 npc_talked, u16 entity_contact)
{
    u8 fire = 0u;
    if (cond == TRIG_ENTER_REGION || cond == TRIG_LEAVE_REGION) {
        if (region < reg_n) {
            u8 in = in_reg[region];
            if (cond == TRIG_ENTER_REGION) fire = (u8)(in && !prev_reg[region]);
            if (cond == TRIG_LEAVE_REGION) fire = (u8)(!in && prev_reg[region]);
        }
    } else if (cond == TRIG_CAM_X_GE) {
        fire = ((u16)tx >= value) ? 1u : 0u;
    } else if (cond == TRIG_CAM_Y_GE) {
        fire = ((u16)ty >= value) ? 1u : 0u;
    } else if (cond == TRIG_TIMER_GE) {
        fire = (timer >= value) ? 1u : 0u;
    } else if (cond == TRIG_WAVE_GE) {
        fire = ((u16)next_wave >= value) ? 1u : 0u;
    } else if (cond == TRIG_BTN_A) {
        fire = (pad_pressed & PAD_A) ? 1u : 0u;
    } else if (cond == TRIG_BTN_B) {
        fire = (pad_pressed & PAD_B) ? 1u : 0u;
    } else if (cond == TRIG_BTN_A_B) {
        fire = ((pad_pressed & PAD_A) && (pad_pressed & PAD_B)) ? 1u : 0u;
    } else if (cond == TRIG_BTN_UP) {
        fire = (pad_pressed & PAD_UP) ? 1u : 0u;
    } else if (cond == TRIG_BTN_DOWN) {
        fire = (pad_pressed & PAD_DOWN) ? 1u : 0u;
    } else if (cond == TRIG_BTN_LEFT) {
        fire = (pad_pressed & PAD_LEFT) ? 1u : 0u;
    } else if (cond == TRIG_BTN_RIGHT) {
        fire = (pad_pressed & PAD_RIGHT) ? 1u : 0u;
    } else if (cond == TRIG_BTN_OPT) {
        fire = (pad_pressed & PAD_OPTION) ? 1u : 0u;
    } else if (cond == TRIG_ON_JUMP) {
        fire = player_jump_started ? 1u : 0u;
    } else if (cond == TRIG_WAVE_CLEARED) {
        fire = (((u16)next_wave > value) && (enemy_active_count == 0u)) ? 1u : 0u;
    } else if (cond == TRIG_HEALTH_LE) {
        fire = (player_hp <= (u8)value) ? 1u : 0u;
    } else if (cond == TRIG_HEALTH_GE) {
        fire = (player_hp >= (u8)value) ? 1u : 0u;
    } else if (cond == TRIG_ENEMY_COUNT_LE) {
        fire = (enemy_active_count <= (u8)value) ? 1u : 0u;
    } else if (cond == TRIG_LIVES_LE) {
        fire = (lives <= (u8)value) ? 1u : 0u;
    } else if (cond == TRIG_LIVES_GE) {
        fire = (lives >= (u8)value) ? 1u : 0u;
    } else if (cond == TRIG_COLLECTIBLE_COUNT_GE) {
        fire = (collectible_count >= value) ? 1u : 0u;
    } else if (cond == TRIG_TIMER_EVERY) {
        fire = (value > 0u && (timer % value == 0u)) ? 1u : 0u;
    } else if (cond == TRIG_SCENE_FIRST_ENTER) {
        fire = (timer == 0u) ? 1u : 0u;
    } else if (cond == TRIG_NPC_TALKED_TO) {
        /* value = src_idx of the NPC/prop entity. Bit set when player adjacent + PAD_A. */
        if (value < 16u) fire = (u8)((npc_talked >> (u8)value) & 1u);
    } else if (cond == TRIG_ENTITY_CONTACT) {
        /* value = src_idx of the prop/NPC entity. Bit set when player AABB overlaps entity AABB. */
        if (value < 16u) fire = (u8)((entity_contact >> (u8)value) & 1u);
    }
    if (fire && (cond == TRIG_BTN_A || cond == TRIG_BTN_B || cond == TRIG_BTN_A_B ||
                 cond == TRIG_BTN_UP || cond == TRIG_BTN_DOWN ||
                 cond == TRIG_BTN_LEFT || cond == TRIG_BTN_RIGHT || cond == TRIG_BTN_OPT)) {
        if (region != 255u) fire = (region < reg_n) ? in_reg[region] : 0u;
    }
    return fire;
}

#endif /* NGPNG_HAS_TRIGGERS */
