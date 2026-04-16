/*
 * ngpc_palman.h - Dynamic sprite palette slot manager
 *
 * Part of NgpCraft_base_template (MIT License)
 *
 * NGPC has 16 hardware sprite palette slots (0x8200..0x827F, 4 colors each).
 * By default, palette slots are assigned at compile time (baked in ROM data)
 * and stay occupied even when an entity is off-screen.
 *
 * This module recycles palette slots at runtime using an LRU eviction policy:
 *   - acquire(type, pal_data): upload palette to HW and return slot index
 *   - release(type): decrement ref_count; slot stays alive (LRU grace period)
 *   - When a new type needs a slot: evict the least-recently-released idle slot
 *
 * Result: scenes with N entity types only need min(N_active, 16) palette slots.
 *
 * ---- HOW TO INTEGRATE ----
 *
 * 1. Copy this directory (optional/ngpc_palman/) into your project.
 *
 * 2. Add to your makefile OBJS:
 *      $(OBJ_DIR)/optional/ngpc_palman/ngpc_palman.rel \
 *    And add the compile rule if not covered by the wildcard:
 *      $(OBJ_DIR)/optional/%.rel: optional/%.c
 *          $(PYTHON) tools/build_utils.py compile $< $@ $(CC900_CPU) $(CDEFS)
 *
 * 3. In your game init:
 *      ngpc_palman_init();
 *
 * 4. Each frame, call once:
 *      ngpc_palman_tick();
 *
 * 5. At entity spawn:
 *      u8 pal_slot = ngpc_palman_acquire(type_id, pal_data_ptr);
 *      entity.pal = pal_slot;
 *
 * 6. At entity death / deactivation:
 *      ngpc_palman_release(type_id);
 *
 * The draw path is unchanged: use entity.pal as the sprite palette index.
 *
 * ---- LRU GRACE PERIOD ----
 *
 * When ref_count reaches 0, the slot is NOT immediately freed. It stays
 * loaded (lru_tick records the release frame). If the same entity type
 * respawns before eviction, acquire() returns instantly (0 HW upload).
 * Eviction only happens when a new type needs a slot and all 16 are occupied
 * by idle (ref_count==0) types — the oldest one is evicted.
 *
 * ---- HARDWARE REFERENCE ----
 *
 * Sprite palette RAM: 0x8200..0x827F (K2GE, 16 palettes x 4 colors x 2 bytes)
 * Color format: 0BGR (12-bit: B[11:8] G[7:4] R[3:0], bits 15-12 unused)
 * OAM palette index: 0x8C00+sprite_id (CP.C, 1 byte, 0-15)
 * Writes are immediate (no shadow): safe to call any time outside HBlank.
 */

#ifndef NGPC_PALMAN_H
#define NGPC_PALMAN_H

#include "../../src/core/ngpc_types.h"

#ifndef NGP_FAR
#define NGP_FAR
#endif

/* Total hardware sprite palette slots */
#define NGPC_PALMAN_SLOTS   16u

/* Sentinel: slot or type is unoccupied / not found */
#define NGPC_PALMAN_FREE    0xFFu
#define NGPC_PALMAN_NONE    0xFFu

/*
 * One entry in the palette slot table.
 * 64 bytes total BSS (16 x 4 bytes).
 */
typedef struct {
    u8  type_loaded;  /* entity type occupying this slot; NGPC_PALMAN_FREE = empty */
    u8  ref_count;    /* number of active entities of this type                    */
    u8  lru_tick;     /* low-8 of frame counter at last release (LRU clock)        */
    u8  _pad;
} NgpPalSlot;

/* Slot table — readable for debug display */
extern NgpPalSlot g_pal_slots[NGPC_PALMAN_SLOTS];

/* ---- API ---- */

/* Initialize all slots to FREE. Call once at scene/game start. */
void ngpc_palman_init(void);

/* Advance the LRU clock. Call exactly once per frame (e.g. top of game loop). */
void ngpc_palman_tick(void);

/*
 * Acquire a palette slot for 'type_id'.
 *
 * type_id  : your entity type index (0..254; 0xFF is reserved for NGPC_PALMAN_FREE).
 * pal_data : pointer to 4 u16 colors [c0, c1, c2, c3] in ROM or RAM.
 *            c0 is typically transparent (black). Use the RGB() macro.
 *            For ROM data (0x200000+) use NGP_FAR on the pointer declaration.
 *
 * Returns: hardware palette slot index (0-15).
 *          Returns NGPC_PALMAN_NONE (0xFF) only if all 16 slots are occupied
 *          by active entities (ref_count > 0) — extremely unlikely in practice.
 *
 * Side effect: uploads pal_data to hardware immediately via ngpc_gfx_set_palette().
 *              If the type was already loaded, NO hardware upload occurs.
 */
u8 ngpc_palman_acquire(u8 type_id, const u16 NGP_FAR *pal_data);

/*
 * Release one entity of 'type_id'.
 * Decrements ref_count. If ref_count hits 0, records lru_tick for eviction.
 * The slot stays loaded — a matching acquire() before eviction is instant.
 */
void ngpc_palman_release(u8 type_id);

/*
 * Find the slot currently holding 'type_id'.
 * Returns slot index 0-15, or NGPC_PALMAN_NONE if not loaded.
 * No side effects. Useful for assertions or debug.
 */
u8 ngpc_palman_find(u8 type_id);

#endif /* NGPC_PALMAN_H */
