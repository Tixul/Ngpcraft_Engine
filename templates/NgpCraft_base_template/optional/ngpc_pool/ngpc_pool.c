#include "ngpc_pool.h"

u8 ngpc_pool_alloc(NgpcPoolHdr *p) {
    u8 i;
    if (p->count >= p->capacity) return POOL_NONE;
    for (i = 0; i < p->capacity; i++) {
        if (!ngpc_pool_active(p, i)) {
            p->mask |= (u16)(1u << i);
            p->count++;
            return i;
        }
    }
    return POOL_NONE;
}

void ngpc_pool_free(NgpcPoolHdr *p, u8 idx) {
    if (idx >= p->capacity) return;
    if (!ngpc_pool_active(p, idx)) return;
    p->mask &= ~(u16)(1u << idx);
    p->count--;
}

void ngpc_pool_clear(NgpcPoolHdr *p) {
    p->mask  = 0;
    p->count = 0;
}
