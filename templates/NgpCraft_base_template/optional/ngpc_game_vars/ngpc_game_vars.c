/*
 * ngpc_game_vars.c -- Persistent flags & variables
 * See ngpc_game_vars.h for documentation.
 */

#include "ngpc_game_vars.h"

/*
 * Include the generated header produced by PNG Manager export.
 * It defines g_game_var_inits[8] with the default init values.
 * If not exported yet, ngpc_gv_init() will zero all variables.
 */
#ifdef NGPC_GAME_VARS_GEN_H
/* already included via ngpc_game_vars.h or user's main -- nothing to do */
#endif

/* ---- State ------------------------------------------------------------ */

u8 ngpc_gv_flags[NGPC_GV_FLAG_COUNT];
u8 ngpc_gv_vars[NGPC_GV_VAR_COUNT];

/* ---- Init ------------------------------------------------------------- */

void ngpc_gv_init(void)
{
    u8 i;
    for (i = 0u; i < NGPC_GV_FLAG_COUNT; ++i) ngpc_gv_flags[i] = 0u;
#ifdef NGPC_GAME_VARS_GEN_H
    for (i = 0u; i < NGPC_GV_VAR_COUNT; ++i)  ngpc_gv_vars[i]  = g_game_var_inits[i];
#else
    for (i = 0u; i < NGPC_GV_VAR_COUNT; ++i)  ngpc_gv_vars[i]  = 0u;
#endif
}

/* ---- Flags ------------------------------------------------------------ */

void ngpc_gv_set_flag(u8 idx)
{
    if (idx < NGPC_GV_FLAG_COUNT) ngpc_gv_flags[idx] = 1u;
}

void ngpc_gv_clear_flag(u8 idx)
{
    if (idx < NGPC_GV_FLAG_COUNT) ngpc_gv_flags[idx] = 0u;
}

void ngpc_gv_toggle_flag(u8 idx)
{
    if (idx < NGPC_GV_FLAG_COUNT) ngpc_gv_flags[idx] ^= 1u;
}

u8 ngpc_gv_get_flag(u8 idx)
{
    return (idx < NGPC_GV_FLAG_COUNT) ? ngpc_gv_flags[idx] : 0u;
}

/* ---- Variables -------------------------------------------------------- */

void ngpc_gv_set_var(u8 idx, u8 val)
{
    if (idx < NGPC_GV_VAR_COUNT) ngpc_gv_vars[idx] = val;
}

void ngpc_gv_inc_var(u8 idx, u8 cap)
{
    if (idx < NGPC_GV_VAR_COUNT) {
        if (cap == 0u || ngpc_gv_vars[idx] < cap) ngpc_gv_vars[idx]++;
    }
}

void ngpc_gv_dec_var(u8 idx)
{
    if (idx < NGPC_GV_VAR_COUNT && ngpc_gv_vars[idx] > 0u) ngpc_gv_vars[idx]--;
}

u8 ngpc_gv_get_var(u8 idx)
{
    return (idx < NGPC_GV_VAR_COUNT) ? ngpc_gv_vars[idx] : 0u;
}

/* ---- Trigger dispatch ------------------------------------------------- */

#define _GV_ACT_SET_FLAG       28u
#define _GV_ACT_CLEAR_FLAG     29u
#define _GV_ACT_SET_VARIABLE   30u
#define _GV_ACT_INC_VARIABLE   31u
#define _GV_ACT_DEC_VARIABLE   51u
#define _GV_ACT_TOGGLE_FLAG    58u
#define _GV_ACT_INIT_GAME_VARS 74u

u8 ngpc_gv_dispatch(u8 action, u8 a0, u8 a1)
{
    switch (action) {
    case _GV_ACT_SET_FLAG:       ngpc_gv_set_flag(a0);     return 1u;
    case _GV_ACT_CLEAR_FLAG:     ngpc_gv_clear_flag(a0);   return 1u;
    case _GV_ACT_TOGGLE_FLAG:    ngpc_gv_toggle_flag(a0);  return 1u;
    case _GV_ACT_SET_VARIABLE:   ngpc_gv_set_var(a0, a1);  return 1u;
    case _GV_ACT_INC_VARIABLE:   ngpc_gv_inc_var(a0, a1);  return 1u;
    case _GV_ACT_DEC_VARIABLE:   ngpc_gv_dec_var(a0);      return 1u;
    case _GV_ACT_INIT_GAME_VARS: ngpc_gv_init();            return 1u;
    default:                                                 return 0u;
    }
}
