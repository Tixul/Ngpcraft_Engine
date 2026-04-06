#ifndef NGPC_POOL_H
#define NGPC_POOL_H

/*
 * ngpc_pool -- Pool d'objets générique à taille fixe
 * ===================================================
 * Allocation/libération O(1), zéro fragmentation, zéro malloc.
 * Bitmask u16 → max 16 slots par pool.
 * ~1 octet RAM par slot (pour le bitmask), zéro overhead sur les objets.
 *
 * Usage:
 *   Copier ngpc_pool/ dans src/
 *   OBJS += src/ngpc_pool/ngpc_pool.rel
 *   #include "ngpc_pool/ngpc_pool.h"
 *
 * Exemple (pool de 8 balles) :
 *   typedef struct { s16 x, y; s8 vx, vy; u8 active; } Bullet;
 *   NGPC_POOL_DECL(BulletPool, Bullet, 8);
 *   static BulletPool bpool;
 *   NGPC_POOL_INIT(&bpool, 8);
 *
 *   // Spawner une balle :
 *   u8 idx = ngpc_pool_alloc(&bpool.hdr);
 *   if (idx != POOL_NONE) { bpool.items[idx].x = 50; ... }
 *
 *   // Libérer :
 *   ngpc_pool_free(&bpool.hdr, idx);
 *
 *   // Itérer sur les actifs :
 *   POOL_EACH(&bpool.hdr, i) { bpool.items[i].x += bpool.items[i].vx; }
 */

#include "ngpc_hw.h"  /* u8, u16 */

#define POOL_NONE   0xFF   /* retourné par ngpc_pool_alloc() si pool plein */
#define POOL_MAX    16     /* taille maximale d'un pool */

/* ── En-tête du pool (tracking des slots actifs) ────────── */
typedef struct {
    u16 mask;        /* bit i = 1 si slot i est occupé */
    u8  count;       /* nombre de slots actifs */
    u8  capacity;    /* capacité totale (fixé à la création) */
} NgpcPoolHdr;

/* ── Fonctions de gestion ───────────────────────────────── */

/* Alloue le premier slot libre. Retourne son index ou POOL_NONE si plein. */
u8 ngpc_pool_alloc(NgpcPoolHdr *p);

/* Libère le slot idx. Ne fait rien si idx invalide ou déjà libre. */
void ngpc_pool_free(NgpcPoolHdr *p, u8 idx);

/* Vide le pool entier (tous les slots deviennent libres). */
void ngpc_pool_clear(NgpcPoolHdr *p);

/* 1 si le slot idx est actuellement occupé. */
#define ngpc_pool_active(p, idx)  (((p)->mask >> (idx)) & 1u)

/* Nombre de slots occupés. */
#define ngpc_pool_count(p)        ((p)->count)

/* ── Macro d'itération sur les slots actifs ─────────────── */
/* Itère uniquement sur les slots occupés.
 * IMPORTANT (cc900/C89) : déclarer la variable avant le bloc !
 *
 * Usage :
 *   u8 i;
 *   POOL_EACH(&pool.hdr, i) { pool.items[i].x += 1; }
 */
#define POOL_EACH(p, i) \
    for ((i) = 0; (i) < (p)->capacity; (i)++) \
        if (ngpc_pool_active((p), i))

/* ── Macro de déclaration d'un pool typé ────────────────── */
/* Crée un type struct { NgpcPoolHdr hdr; Type items[N]; }    */
#define NGPC_POOL_DECL(Name, Type, N) \
    typedef struct { NgpcPoolHdr hdr; Type items[(N)]; } Name

/* ── Macro d'initialisation (à appeler avant le premier alloc) */
#define NGPC_POOL_INIT(pool_ptr, N) \
    do { \
        (pool_ptr)->hdr.mask     = 0; \
        (pool_ptr)->hdr.count    = 0; \
        (pool_ptr)->hdr.capacity = (u8)(N); \
    } while(0)

#endif /* NGPC_POOL_H */
