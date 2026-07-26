/*
 * random_encounters.c — step counter + chance roll + battle dispatch.
 *
 * Called by the autorun every frame for scenes where the mech is enabled
 * (gating is done in template_integration.py via g_scene_random_encounters_en).
 * This module accumulates one tick per call, rolls the chance every
 * RE_STEPS_PER_CHECK ticks, and on a hit picks a random monster from EITHER
 * the per-scene override pool (if defined) OR the project-wide default pool,
 * then calls battle_engine_enter().
 *
 * v1.1.2 : added per-scene pool override (g_re_scene_pool_offset[cur_scene]).
 */
#include "ngpc_hw.h"
#include "ngpc_math.h"

#include "../../GraphX/gen/random_encounters.h"
#include "../../GraphX/gen/battle_engine.h"

static u8 s_re_step_accum;

void random_encounters_on_step(u8 cur_scene)
{
    u8 pool_count;
    const u8 *pool;
    u8 pick_idx;

    /* Don't trigger if a battle is already running. */
    if (battle_engine_is_active()) {
        return;
    }

    s_re_step_accum++;
    if (s_re_step_accum < RE_STEPS_PER_CHECK) {
        return;
    }
    s_re_step_accum = 0u;

    /* Roll chance. */
    if ((u8)(ngpc_qrandom() % 100u) >= RE_CHANCE_PCT) {
        return;
    }

    /* Pool selection : prefer per-scene override, fall back to default. */
#if RE_SCENE_POOLS_LEN > 0u
    {
        u8 off = g_re_scene_pool_offset[cur_scene];
        if (off != 0xFFu) {
            pool       = &g_re_scene_pools[off];
            pool_count = g_re_scene_pool_count[cur_scene];
        } else
#endif
        {
#if RE_POOL_COUNT > 0u
            pool       = g_re_pool;
            pool_count = RE_POOL_COUNT;
#else
            /* No default pool and no per-scene override : nothing to fight. */
            return;
#endif
        }
#if RE_SCENE_POOLS_LEN > 0u
    }
#endif

    if (pool_count == 0u) {
        return;
    }

    pick_idx = (u8)(ngpc_qrandom() % pool_count);
    battle_engine_enter(pool[pick_idx]);
}
