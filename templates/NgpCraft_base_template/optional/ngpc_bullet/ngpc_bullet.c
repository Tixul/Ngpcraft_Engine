#include "ngpc_bullet.h"

/* Dimensions de l'écran NGPC */
#define _BULLET_SCR_W  160
#define _BULLET_SCR_H  152

u8 ngpc_bullet_spawn(NgpcBulletPool *pool,
                     fx16 x, fx16 y, s8 vx, s8 vy,
                     u8 w, u8 h, u8 tile, u8 pal,
                     u8 life, u8 flags) {
    u8 idx;
    NgpcBullet *b;

    idx = ngpc_pool_alloc(&pool->hdr);
    if (idx == POOL_NONE) return POOL_NONE;

    b = &pool->items[idx];
    b->x     = x;
    b->y     = y;
    b->vx    = vx;
    b->vy    = vy;
    b->w     = w;
    b->h     = h;
    b->tile  = tile;
    b->pal   = pal;
    b->life  = life;
    b->flags = flags;
    return idx;
}

void ngpc_bullet_update(NgpcBulletPool *pool) {
    u8 i;
    NgpcBullet *b;
    s16 px, py;
    u8  dead;

    POOL_EACH(&pool->hdr, i) {
        b    = &pool->items[i];
        dead = 0;

        /* Déplacement */
        b->x = FX_ADD(b->x, INT_TO_FX((s16)b->vx));
        b->y = FX_ADD(b->y, INT_TO_FX((s16)b->vy));

        /* Décrémenter TTL si limité */
        if (b->life > 0) {
            b->life--;
            if (b->life == 0) dead = 1;
        }

        /* Vérification hors écran */
        if (!dead) {
            px = FX_TO_INT(b->x);
            py = FX_TO_INT(b->y);
            if (px + (s16)b->w <= 0 || px >= (s16)_BULLET_SCR_W ||
                py + (s16)b->h <= 0 || py >= (s16)_BULLET_SCR_H) {
                dead = 1;
            }
        }

        if (dead) ngpc_pool_free(&pool->hdr, i);
    }
}

u8 ngpc_bullet_hits(const NgpcBulletPool *pool, u8 idx, const NgpcRect *target) {
    NgpcRect br;
    const NgpcBullet *b = &pool->items[idx];

    br.x = FX_TO_INT(b->x);
    br.y = FX_TO_INT(b->y);
    br.w = b->w;
    br.h = b->h;
    return ngpc_rect_overlap(&br, target);
}
