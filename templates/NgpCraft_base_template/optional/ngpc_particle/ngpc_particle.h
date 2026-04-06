#ifndef NGPC_PARTICLE_H
#define NGPC_PARTICLE_H

/*
 * ngpc_particle -- Pool de particules simples (effets visuels)
 * ============================================================
 * PARTICLE_POOL_SIZE × 12 octets RAM (défaut : 16 × 12 = 192 octets).
 *
 * Pas de rendu intégré : le module gère la physique et la durée de vie.
 * Le code jeu dessine les particules actives (voir exemple ci-dessous).
 *
 * Usage :
 *   Copier ngpc_particle/ dans src/
 *   OBJS += $(OBJ_DIR)/src/ngpc_particle/ngpc_particle.rel
 *   #include "ngpc_particle/ngpc_particle.h"
 *
 * Exemple — explosion + affichage sprite :
 *   static NgpcParticlePool fx;
 *   ngpc_particle_pool_init(&fx);
 *
 *   // À l'explosion :
 *   ngpc_particle_burst(&fx, INT_TO_FX(80), INT_TO_FX(76),
 *                       6, INT_TO_FX(1), 20, SPARK_TILE, 2, PART_GRAVITY);
 *
 *   // Chaque frame :
 *   u8 spr = SPR_FX_BASE;
 *   ngpc_particle_update(&fx);
 *   for (i = 0; i < PARTICLE_POOL_SIZE; i++) {
 *       NgpcParticle *p = &fx.slots[i];
 *       if (!p->life) { ngpc_sprite_hide(spr++); continue; }
 *       ngpc_sprite_set(spr++, ngpc_particle_px(p), ngpc_particle_py(p),
 *                       p->tile, p->pal, SPR_FRONT);
 *   }
 *
 * Taille du pool (surcharger avant l'include) :
 *   #define PARTICLE_POOL_SIZE 32
 */

#include "ngpc_fixed/ngpc_fixed.h"   /* fx16, FxVec2, FX_ADD, FX_MUL, FX_TO_INT */

/* ── Pool size ────────────────────────────────────────────── */
#ifndef PARTICLE_POOL_SIZE
#define PARTICLE_POOL_SIZE  16
#endif

/* ── Gravité particule (surcharger avant l'include) ──────── */
#ifndef PARTICLE_GRAVITY
#define PARTICLE_GRAVITY    ((fx16)2)   /* 0.125 px/frame² — légère */
#endif

/* ── Flags ───────────────────────────────────────────────── */
#define PART_GRAVITY  0x01   /* appliquer PARTICLE_GRAVITY à vel.y */

/* ── Struct particule (12 octets) ────────────────────────── */
typedef struct {
    FxVec2 pos;   /* position sous-pixel (x, y)     — 4 octets */
    FxVec2 vel;   /* vitesse (px/frame)              — 4 octets */
    u8     life;  /* durée de vie (0 = slot libre)   — 1 octet  */
    u8     tile;  /* tile sprite (index dans char RAM)— 1 octet */
    u8     pal;   /* palette (0-15)                  — 1 octet  */
    u8     flags; /* PART_GRAVITY                    — 1 octet  */
} NgpcParticle;

/* ── Pool ────────────────────────────────────────────────── */
typedef struct {
    NgpcParticle slots[PARTICLE_POOL_SIZE];
} NgpcParticlePool;

/* ── API ─────────────────────────────────────────────────── */

/* Initialise le pool (tous les slots à life = 0). */
void ngpc_particle_pool_init(NgpcParticlePool *pool);

/*
 * Émet une particule dans un slot libre.
 * x, y, vx, vy : en fx16.
 * life : durée de vie en frames.
 * tile : index tile pour ngpc_sprite_set.
 * pal  : palette (0-15).
 * flags: PART_GRAVITY ou 0.
 * Retourne 1 si un slot a été alloué, 0 si pool plein.
 */
u8 ngpc_particle_emit(NgpcParticlePool *pool,
                      fx16 x, fx16 y, fx16 vx, fx16 vy,
                      u8 life, u8 tile, u8 pal, u8 flags);

/*
 * Émet 'count' particules en étoile autour du point (x, y).
 * Directions : 8 directions équidistantes (E, W, S, N, SE, SW, NE, NW).
 * Si count > 8, recommence depuis E (boucle).
 * speed : vitesse initiale (fx16), ex: INT_TO_FX(1).
 */
void ngpc_particle_burst(NgpcParticlePool *pool,
                         fx16 x, fx16 y, u8 count,
                         fx16 speed, u8 life, u8 tile, u8 pal, u8 flags);

/*
 * Met à jour toutes les particules actives — appeler UNE FOIS par frame.
 * Applique gravité (si PART_GRAVITY), intègre pos += vel, décrémente life.
 */
void ngpc_particle_update(NgpcParticlePool *pool);

/* Nombre de particules actuellement actives (life > 0). */
u8 ngpc_particle_count(const NgpcParticlePool *pool);

/* ── Accès rapides ───────────────────────────────────────── */

/* Position pixel entière pour ngpc_sprite_set. */
#define ngpc_particle_px(p)  ((u8)FX_TO_INT((p)->pos.x))
#define ngpc_particle_py(p)  ((u8)FX_TO_INT((p)->pos.y))

/* 1 si la particule est active. */
#define ngpc_particle_alive(p) ((p)->life > 0)

#endif /* NGPC_PARTICLE_H */
