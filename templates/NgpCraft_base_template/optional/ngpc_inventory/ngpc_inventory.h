#ifndef NGPC_INVENTORY_H
#define NGPC_INVENTORY_H

/*
 * ngpc_inventory -- Item inventory with equipment slots
 * ======================================================
 * Fixed array of INV_SLOTS items {id, count}.
 * 4 equipment slots (weapon, armor, acc1, acc2).
 * id == 0 = empty slot (INV_EMPTY).
 *
 * Depends on: ngpc_hw.h only
 *
 * RAM: INV_SLOTS * 2 + INV_EQUIP_SLOTS = 36 bytes (default).
 *
 * Usage:
 *   Copy ngpc_inventory/ into src/
 *   OBJS += src/ngpc_inventory/ngpc_inventory.rel
 *   #include "ngpc_inventory/ngpc_inventory.h"
 *
 * Define item IDs in the game (0 = empty, reserved):
 *   #define ITEM_SWORD   1
 *   #define ITEM_SHIELD  2
 *   #define ITEM_POTION  3
 *   #define ITEM_KEY     4
 *
 * Example:
 *   static NgpcInventory inv;
 *   ngpc_inv_init(&inv);
 *
 *   ngpc_inv_add(&inv, ITEM_POTION, 3);
 *   ngpc_inv_add(&inv, ITEM_SWORD,  1);
 *
 *   if (ngpc_inv_has(&inv, ITEM_POTION)) {
 *       ngpc_inv_remove(&inv, ITEM_POTION, 1);
 *       player_hp += 3;
 *   }
 *
 *   // Equip:
 *   ngpc_inv_equip(&inv, INV_SLOT_WEAPON, ITEM_SWORD);
 *   u8 weapon = ngpc_inv_equipped(&inv, INV_SLOT_WEAPON);  // -> ITEM_SWORD
 */

#include "ngpc_hw.h"

/* ── Configurable size ───────────────────────────────────────────────── */
#ifndef INV_SLOTS
#define INV_SLOTS        16   /* inventory slots (max 255) */
#endif

#ifndef INV_EQUIP_SLOTS
#define INV_EQUIP_SLOTS   4   /* equipment slots */
#endif

/* ── Equipment slot indices ──────────────────────────────────────────── */
#define INV_SLOT_WEAPON  0
#define INV_SLOT_ARMOR   1
#define INV_SLOT_ACC1    2
#define INV_SLOT_ACC2    3

/* Empty item ID */
#define INV_EMPTY        0
/* Slot not found */
#define INV_NONE         0xFF

/* ── Struct ──────────────────────────────────────────────────────────── */
typedef struct {
    u8 id   [INV_SLOTS];         /* item ID (0 = empty)        */
    u8 count[INV_SLOTS];         /* quantity                   */
    u8 equip[INV_EQUIP_SLOTS];   /* equipped IDs (0 = nothing) */
} NgpcInventory;

/* ── API ─────────────────────────────────────────────────────────────── */

/* Clear the inventory and all equipment slots. */
void ngpc_inv_init(NgpcInventory *inv);

/*
 * Add `count` copies of item `id` (id != 0).
 * If the item is already present, increment its quantity.
 * If absent, find a free slot.
 * Returns 1 on success, 0 if inventory is full or id == 0.
 */
u8 ngpc_inv_add(NgpcInventory *inv, u8 id, u8 count);

/*
 * Remove `count` copies of item `id`.
 * If quantity drops to 0, the slot is freed.
 * Returns 1 on success, 0 if item absent or insufficient quantity.
 */
u8 ngpc_inv_remove(NgpcInventory *inv, u8 id, u8 count);

/*
 * Return the total quantity of item `id` (0 if absent).
 */
u8 ngpc_inv_has(const NgpcInventory *inv, u8 id);

/*
 * Return the slot index holding `id`, or INV_NONE if absent.
 */
u8 ngpc_inv_find(const NgpcInventory *inv, u8 id);

/*
 * Number of occupied slots.
 */
u8 ngpc_inv_used(const NgpcInventory *inv);

/*
 * Equip item `id` in slot `slot` (INV_SLOT_WEAPON, etc.).
 * Use INV_EMPTY (0) to unequip.
 */
void ngpc_inv_equip(NgpcInventory *inv, u8 slot, u8 id);

/*
 * Return the ID equipped in slot `slot` (INV_EMPTY if none).
 */
#define ngpc_inv_equipped(inv, slot)  ((inv)->equip[(slot)])

/*
 * Return 1 if item `id` is equipped in any slot.
 */
u8 ngpc_inv_is_equipped(const NgpcInventory *inv, u8 id);

#endif /* NGPC_INVENTORY_H */
