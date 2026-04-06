#ifndef NGPC_BULLET_H
#define NGPC_BULLET_H

/*
 * ngpc_bullet -- Pool de projectiles précâblé
 * ============================================
 * Pool statique de BULLET_POOL_SIZE bullets (défaut 16).
 * Position fx16 (sous-pixel), vitesse s8 (px/frame entiers).
 * Expiration automatique : hors écran OU TTL épuisé.
 * Rendu à la charge du jeu.
 *
 * Dépend de : ngpc_pool, ngpc_fixed, ngpc_aabb (pour ngpc_bullet_hits).
 *
 * Usage :
 *   Copier ngpc_bullet/ dans src/ (+ ngpc_pool/, ngpc_fixed/, ngpc_aabb/)
 *   OBJS += $(OBJ_DIR)/src/ngpc_bullet/ngpc_bullet.rel
 *   #include "ngpc_bullet/ngpc_bullet.h"
 *
 * Exemple — tir joueur :
 *   static NgpcBulletPool bullets;
 *   NGPC_BULLET_POOL_INIT(&bullets);
 *
 *   // À la pression du bouton :
 *   ngpc_bullet_spawn(&bullets,
 *       hero.pos.x, hero.pos.y,   // position de départ
 *       4, 0,                      // vx=4, vy=0 (vers la droite)
 *       4, 4,                      // hitbox 4×4
 *       BULLET_TILE, 1,            // tile + palette
 *       60,                        // TTL : 60 frames (1 seconde)
 *       BULLET_PLAYER);
 *
 *   // Chaque frame :
 *   ngpc_bullet_update(&bullets);
 *   POOL_EACH(&bullets.hdr, i) {
 *       NgpcBullet *b = &bullets.items[i];
 *       ngpc_sprite_set(SPR_BULLET + i,
 *                       ngpc_bullet_px(b), ngpc_bullet_py(b),
 *                       b->tile, b->pal, SPR_FRONT);
 *       // Collision vs ennemis :
 *       NgpcRect er = { enemy.x, enemy.y, 16, 16 };
 *       if (ngpc_bullet_hits(&bullets, i, &er)) {
 *           enemy_hurt();
 *           ngpc_bullet_kill(&bullets, i);
 *       }
 *   }
 */

#include "../ngpc_pool/ngpc_pool.h"    /* NgpcPoolHdr, POOL_EACH, POOL_NONE */
#include "../ngpc_fixed/ngpc_fixed.h"  /* fx16, FX_TO_INT, INT_TO_FX, FX_ADD */
#include "../ngpc_aabb/ngpc_aabb.h"    /* NgpcRect, ngpc_rect_overlap */

/* ── Pool size ───────────────────────────────────────────── */
#ifndef BULLET_POOL_SIZE
#define BULLET_POOL_SIZE  16
#endif

/* ── Flags ───────────────────────────────────────────────── */
#define BULLET_PLAYER  0x01   /* projectile allié (joueur) */
#define BULLET_ENEMY   0x02   /* projectile ennemi */

/* ── Struct bullet (12 octets) ───────────────────────────── */
typedef struct {
    fx16 x, y;   /* position sous-pixel (coin haut-gauche)   — 4 octets */
    s8   vx, vy; /* vitesse (pixels entiers/frame)            — 2 octets */
    u8   tile;   /* index tile pour ngpc_sprite_set           — 1 octet  */
    u8   pal;    /* palette (0-15)                            — 1 octet  */
    u8   w, h;   /* taille hitbox (pixels)                    — 2 octets */
    u8   life;   /* TTL en frames (0 = OOB uniquement)        — 1 octet  */
    u8   flags;  /* BULLET_PLAYER / BULLET_ENEMY              — 1 octet  */
} NgpcBullet;

/* ── Pool ────────────────────────────────────────────────── */
typedef struct {
    NgpcPoolHdr hdr;
    NgpcBullet  items[BULLET_POOL_SIZE];
} NgpcBulletPool;

/* Initialiser le pool avant toute utilisation. */
#define NGPC_BULLET_POOL_INIT(p)  NGPC_POOL_INIT((p), BULLET_POOL_SIZE)

/* ── API ─────────────────────────────────────────────────── */

/*
 * Spawne un projectile dans un slot libre.
 * x, y  : position de départ (fx16).
 * vx/vy : vitesse (s8, pixels entiers/frame). Exemples : 4/-3.
 * w, h  : dimensions de la hitbox en pixels.
 * life  : TTL en frames. 0 = illimité (expire uniquement hors écran).
 * flags : BULLET_PLAYER | BULLET_ENEMY | ...
 * Retourne l'index du slot ou POOL_NONE si pool plein.
 */
u8 ngpc_bullet_spawn(NgpcBulletPool *pool,
                     fx16 x, fx16 y, s8 vx, s8 vy,
                     u8 w, u8 h, u8 tile, u8 pal,
                     u8 life, u8 flags);

/*
 * Met à jour tous les bullets actifs — appeler UNE FOIS par frame.
 * Déplace (pos += vel), décrémente life si > 0,
 * libère automatiquement les bullets expirés ou hors écran.
 */
void ngpc_bullet_update(NgpcBulletPool *pool);

/*
 * Teste si le bullet 'idx' (actif) chevauche le rect cible.
 * Retourne 1 si collision, 0 sinon.
 * N'expire pas le bullet — appeler ngpc_bullet_kill() pour le supprimer.
 *
 * Usage typique dans POOL_EACH :
 *   POOL_EACH(&pool->hdr, i) {
 *       NgpcRect er = { ex, ey, ew, eh };
 *       if (ngpc_bullet_hits(pool, i, &er)) { ... ngpc_bullet_kill(pool, i); }
 *   }
 */
u8 ngpc_bullet_hits(const NgpcBulletPool *pool, u8 idx, const NgpcRect *target);

/* Libère un bullet (fin de vie après collision). */
#define ngpc_bullet_kill(pool, idx)  ngpc_pool_free(&(pool)->hdr, (idx))

/* Position pixel entière (pour ngpc_sprite_set). */
#define ngpc_bullet_px(b)  ((u8)FX_TO_INT((b)->x))
#define ngpc_bullet_py(b)  ((u8)FX_TO_INT((b)->y))

#endif /* NGPC_BULLET_H */
