#include "ngpc_inventory.h"

void ngpc_inv_init(NgpcInventory *inv)
{
    u8 i;
    for (i = 0; i < INV_SLOTS; i++) {
        inv->id[i]    = INV_EMPTY;
        inv->count[i] = 0;
    }
    for (i = 0; i < INV_EQUIP_SLOTS; i++) {
        inv->equip[i] = INV_EMPTY;
    }
}

u8 ngpc_inv_add(NgpcInventory *inv, u8 id, u8 count)
{
    u8 i, free_slot;

    if (id == INV_EMPTY || count == 0) return 0;

    /* Chercher si l'item existe déjà */
    for (i = 0; i < INV_SLOTS; i++) {
        if (inv->id[i] == id) {
            inv->count[i] = (u8)(inv->count[i] + count);
            return 1;
        }
    }

    /* Chercher un slot libre */
    free_slot = INV_NONE;
    for (i = 0; i < INV_SLOTS; i++) {
        if (inv->id[i] == INV_EMPTY) {
            free_slot = i;
            break;
        }
    }
    if (free_slot == INV_NONE) return 0;   /* inventaire plein */

    inv->id[free_slot]    = id;
    inv->count[free_slot] = count;
    return 1;
}

u8 ngpc_inv_remove(NgpcInventory *inv, u8 id, u8 count)
{
    u8 i;
    if (id == INV_EMPTY || count == 0) return 0;

    for (i = 0; i < INV_SLOTS; i++) {
        if (inv->id[i] == id) {
            if (inv->count[i] < count) return 0;
            inv->count[i] = (u8)(inv->count[i] - count);
            if (inv->count[i] == 0) {
                inv->id[i] = INV_EMPTY;
            }
            return 1;
        }
    }
    return 0;
}

u8 ngpc_inv_has(const NgpcInventory *inv, u8 id)
{
    u8 i;
    if (id == INV_EMPTY) return 0;
    for (i = 0; i < INV_SLOTS; i++) {
        if (inv->id[i] == id) return inv->count[i];
    }
    return 0;
}

u8 ngpc_inv_find(const NgpcInventory *inv, u8 id)
{
    u8 i;
    if (id == INV_EMPTY) return INV_NONE;
    for (i = 0; i < INV_SLOTS; i++) {
        if (inv->id[i] == id) return i;
    }
    return INV_NONE;
}

u8 ngpc_inv_used(const NgpcInventory *inv)
{
    u8 i, n = 0;
    for (i = 0; i < INV_SLOTS; i++) {
        if (inv->id[i] != INV_EMPTY) n++;
    }
    return n;
}

void ngpc_inv_equip(NgpcInventory *inv, u8 slot, u8 id)
{
    if (slot >= INV_EQUIP_SLOTS) return;
    inv->equip[slot] = id;
}

u8 ngpc_inv_is_equipped(const NgpcInventory *inv, u8 id)
{
    u8 i;
    if (id == INV_EMPTY) return 0;
    for (i = 0; i < INV_EQUIP_SLOTS; i++) {
        if (inv->equip[i] == id) return 1;
    }
    return 0;
}
