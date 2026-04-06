#include "ngpc_particle.h"

/*
 * Vecteurs unitaires fx16 pour les 8 directions de burst.
 * Cardinals : 16 = 1.0, Diagonales : 11 ≈ 0.6875 ≈ 1/√2.
 * Ordre : E, W, S, N, SE, SW, NE, NW.
 */
static const fx16 _burst_vx[8] = {
     16, -16,   0,   0,   11, -11,  11, -11
};
static const fx16 _burst_vy[8] = {
      0,   0,  16, -16,   11,  11, -11, -11
};

void ngpc_particle_pool_init(NgpcParticlePool *pool) {
    u8 i;
    for (i = 0; i < PARTICLE_POOL_SIZE; i++) {
        pool->slots[i].life = 0;
    }
}

u8 ngpc_particle_emit(NgpcParticlePool *pool,
                      fx16 x, fx16 y, fx16 vx, fx16 vy,
                      u8 life, u8 tile, u8 pal, u8 flags) {
    u8 i;
    NgpcParticle *p;

    if (life == 0) return 0;

    for (i = 0; i < PARTICLE_POOL_SIZE; i++) {
        p = &pool->slots[i];
        if (p->life == 0) {
            p->pos.x = x;
            p->pos.y = y;
            p->vel.x = vx;
            p->vel.y = vy;
            p->life  = life;
            p->tile  = tile;
            p->pal   = pal;
            p->flags = flags;
            return 1;
        }
    }
    return 0;  /* pool plein */
}

void ngpc_particle_burst(NgpcParticlePool *pool,
                         fx16 x, fx16 y, u8 count,
                         fx16 speed, u8 life, u8 tile, u8 pal, u8 flags) {
    u8 i;
    fx16 vx, vy;

    for (i = 0; i < count; i++) {
        vx = FX_MUL(speed, _burst_vx[i & 7]);
        vy = FX_MUL(speed, _burst_vy[i & 7]);
        ngpc_particle_emit(pool, x, y, vx, vy, life, tile, pal, flags);
    }
}

void ngpc_particle_update(NgpcParticlePool *pool) {
    u8 i;
    NgpcParticle *p;

    for (i = 0; i < PARTICLE_POOL_SIZE; i++) {
        p = &pool->slots[i];
        if (p->life == 0) continue;

        /* Gravité optionnelle */
        if (p->flags & PART_GRAVITY) {
            p->vel.y = FX_ADD(p->vel.y, PARTICLE_GRAVITY);
        }

        /* Intégration position */
        p->pos.x = FX_ADD(p->pos.x, p->vel.x);
        p->pos.y = FX_ADD(p->pos.y, p->vel.y);

        /* Décrémenter durée de vie */
        p->life--;
    }
}

u8 ngpc_particle_count(const NgpcParticlePool *pool) {
    u8 i, n;
    n = 0;
    for (i = 0; i < PARTICLE_POOL_SIZE; i++) {
        if (pool->slots[i].life > 0) n++;
    }
    return n;
}
