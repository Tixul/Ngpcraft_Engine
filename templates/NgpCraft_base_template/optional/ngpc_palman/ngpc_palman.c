/*
 * ngpc_palman.c - Dynamic sprite palette slot manager
 *
 * Part of NgpCraft_base_template (MIT License)
 */

#include "ngpc_palman.h"
#include "../../src/gfx/ngpc_gfx.h"

/* ---- State (64 bytes BSS) ---- */

NgpPalSlot g_pal_slots[NGPC_PALMAN_SLOTS];

static u8 s_lru_tick;  /* free-running frame counter, low 8 bits */

/* ---- Internal helpers ---- */

/*
 * Find the best slot to evict or reuse:
 *   Pass 1 — look for a completely free slot (type_loaded == NGPC_PALMAN_FREE).
 *   Pass 2 — among idle slots (ref_count == 0), evict the oldest (largest age).
 * Returns NGPC_PALMAN_NONE if every slot has active entities.
 */
static u8 find_free_or_evict(void)
{
    u8 i;
    u8 best;
    u8 best_age;
    u8 age;

    /* Pass 1: prefer a completely empty slot */
    for (i = 0; i < NGPC_PALMAN_SLOTS; i++) {
        if (g_pal_slots[i].type_loaded == NGPC_PALMAN_FREE) {
            return i;
        }
    }

    /* Pass 2: evict least-recently-released idle slot */
    best     = NGPC_PALMAN_NONE;
    best_age = 0;
    for (i = 0; i < NGPC_PALMAN_SLOTS; i++) {
        if (g_pal_slots[i].ref_count == 0) {
            /* Age = how many ticks since release (wraps at 256, OK for LRU) */
            age = (u8)(s_lru_tick - g_pal_slots[i].lru_tick);
            if (best == NGPC_PALMAN_NONE || age > best_age) {
                best     = i;
                best_age = age;
            }
        }
    }
    return best;
}

/* ---- Public API ---- */

void ngpc_palman_init(void)
{
    u8 i;
    for (i = 0; i < NGPC_PALMAN_SLOTS; i++) {
        g_pal_slots[i].type_loaded = NGPC_PALMAN_FREE;
        g_pal_slots[i].ref_count   = 0;
        g_pal_slots[i].lru_tick    = 0;
        g_pal_slots[i]._pad        = 0;
    }
    s_lru_tick = 0;
}

void ngpc_palman_tick(void)
{
    s_lru_tick++;
}

u8 ngpc_palman_find(u8 type_id)
{
    u8 i;
    for (i = 0; i < NGPC_PALMAN_SLOTS; i++) {
        if (g_pal_slots[i].type_loaded == type_id) {
            return i;
        }
    }
    return NGPC_PALMAN_NONE;
}

u8 ngpc_palman_acquire(u8 type_id, const u16 NGP_FAR *pal_data)
{
    u8 slot;

    /* Already loaded — just bump ref_count, no HW upload needed */
    slot = ngpc_palman_find(type_id);
    if (slot != NGPC_PALMAN_NONE) {
        g_pal_slots[slot].ref_count++;
        return slot;
    }

    /* Need a new (or evicted) slot */
    slot = find_free_or_evict();
    if (slot == NGPC_PALMAN_NONE) {
        /* All 16 slots occupied by active entities — caller must handle this */
        return NGPC_PALMAN_NONE;
    }

    /* Upload palette to hardware sprite palette RAM (0x8200 + slot*8) */
    ngpc_gfx_set_palette(GFX_SPR, slot,
                         pal_data[0], pal_data[1], pal_data[2], pal_data[3]);

    g_pal_slots[slot].type_loaded = type_id;
    g_pal_slots[slot].ref_count   = 1;
    g_pal_slots[slot].lru_tick    = s_lru_tick;
    return slot;
}

void ngpc_palman_release(u8 type_id)
{
    u8 slot;

    slot = ngpc_palman_find(type_id);
    if (slot == NGPC_PALMAN_NONE) {
        return;
    }
    if (g_pal_slots[slot].ref_count > 0) {
        g_pal_slots[slot].ref_count--;
        if (g_pal_slots[slot].ref_count == 0) {
            /* Record release time for LRU; slot stays loaded (grace period) */
            g_pal_slots[slot].lru_tick = s_lru_tick;
        }
    }
}
