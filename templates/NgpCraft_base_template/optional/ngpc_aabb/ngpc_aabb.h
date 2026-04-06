#ifndef NGPC_AABB_H
#define NGPC_AABB_H

/*
 * ngpc_aabb -- Collision rectangles AABB complète
 * ================================================
 * Rectangles axis-aligned (pas de rotation, pas d'allocation).
 * Zéro état global — fonctions pures, zéro RAM statique.
 *
 * Dépend de : ngpc_fixed.h (pour ngpc_swept_aabb)
 *
 * Usage:
 *   Copier ngpc_aabb/ dans src/
 *   OBJS += src/ngpc_aabb/ngpc_aabb.rel
 *   #include "ngpc_aabb/ngpc_aabb.h"
 */

#include "ngpc_hw.h"          /* s16, u8, s8 */
#include "../ngpc_fixed/ngpc_fixed.h"  /* fx16, pour swept */

/* ══════════════════════════════════════════════════════
 * TYPES
 * ══════════════════════════════════════════════════════ */

typedef struct {
    s16 x, y;   /* coin haut-gauche en pixels (coords monde) */
    u8  w, h;   /* largeur, hauteur en pixels (max 255 px) */
} NgpcRect;

/* Côtés frappés — combiner avec | */
#define COL_NONE    0
#define COL_LEFT    (1 << 0)   /* gauche de A touche droite de B  */
#define COL_RIGHT   (1 << 1)   /* droite de A touche gauche de B  */
#define COL_TOP     (1 << 2)   /* haut de A touche bas de B       */
#define COL_BOTTOM  (1 << 3)   /* bas de A touche haut de B       */
#define COL_ANY     (COL_LEFT | COL_RIGHT | COL_TOP | COL_BOTTOM)

/*
 * Résultat d'un test de collision complet.
 *
 * sides  : TOUS les côtés de A qui touchent B (peut avoir plusieurs bits).
 *          Ex: COL_BOTTOM|COL_RIGHT si le coin bas-droit de A est dans B.
 *          Utiliser pour savoir "suis-je au sol ?", "contre un mur ?", etc.
 *
 * push_x : correction X à appliquer sur A pour sortir de B (0 si MTV sur Y).
 * push_y : correction Y à appliquer sur A pour sortir de B (0 si MTV sur X).
 *          Le MTV (Minimum Translation Vector) résout sur un seul axe à la fois.
 *          Si push_x != 0 → résolution horizontale, si push_y != 0 → verticale.
 *
 * Usage :
 *   NgpcCollResult cr;
 *   if (ngpc_rect_test(&a, &b, &cr)) {
 *       a.x += cr.push_x;
 *       a.y += cr.push_y;
 *       if (cr.sides & COL_BOTTOM) on_ground = 1;
 *   }
 */
typedef struct {
    u8  sides;    /* COL_* flags : tous les côtés touchés */
    s16 push_x;   /* correction X minimale (MTV), 0 si résolution sur Y */
    s16 push_y;   /* correction Y minimale (MTV), 0 si résolution sur X */
} NgpcCollResult;

/* Résultat d'un swept test (objet en mouvement vs statique) */
typedef struct {
    u8   hit;     /* 1 si collision cette frame, 0 sinon */
    fx16 t;       /* moment d'impact [0..FX_ONE] (0=immédiat, FX_ONE=fin frame) */
    s8   nx, ny;  /* normale de collision (-1, 0, ou +1) */
} NgpcSweptResult;

/* ══════════════════════════════════════════════════════
 * MACROS DE CONSTRUCTION
 * ══════════════════════════════════════════════════════ */

#define NGPC_RECT(px, py, pw, ph) \
    { (s16)(px), (s16)(py), (u8)(pw), (u8)(ph) }

/* Bord droit / bas (pixel exclu, comme en mathématiques) */
#define RECT_RIGHT(r)   ((r)->x + (s16)(r)->w)
#define RECT_BOTTOM(r)  ((r)->y + (s16)(r)->h)

/* Centre approximatif */
#define RECT_CX(r)   ((r)->x + (s16)(r)->w / 2)
#define RECT_CY(r)   ((r)->y + (s16)(r)->h / 2)

/* ══════════════════════════════════════════════════════
 * FONCTIONS DE BASE
 * ══════════════════════════════════════════════════════ */

/* 1 si les deux rectangles se chevauchent */
u8 ngpc_rect_overlap(const NgpcRect *a, const NgpcRect *b);

/* 1 si le point (px, py) est dans le rectangle */
u8 ngpc_rect_contains(const NgpcRect *r, s16 px, s16 py);

/* Rectangle d'intersection dans *out. Si pas d'overlap : w==0, h==0 */
void ngpc_rect_intersect(const NgpcRect *a, const NgpcRect *b, NgpcRect *out);

/* Déplace r de (dx, dy) */
void ngpc_rect_offset(NgpcRect *r, s16 dx, s16 dy);

/* ══════════════════════════════════════════════════════
 * DÉTECTION DE CÔTÉ + RÉSOLUTION
 * ══════════════════════════════════════════════════════ */

/*
 * Test complet : overlap + quels côtés + push minimal pour sortir.
 * Retourne 1 si collision, 0 sinon.
 * *out rempli seulement si collision.
 *
 * push_x / push_y = décalage à appliquer sur A pour ne plus chevaucher B.
 * Le push est sur l'axe à pénétration minimale (MTV = Minimum Translation Vector).
 *
 * Exemple (joueur A vs mur B) :
 *   NgpcCollResult r;
 *   if (ngpc_rect_test(&player, &wall, &r)) {
 *       player.x += r.push_x;
 *       player.y += r.push_y;
 *       if (r.sides & COL_BOTTOM) on_ground = 1;
 *   }
 */
u8 ngpc_rect_test(const NgpcRect *a, const NgpcRect *b, NgpcCollResult *out);

/*
 * Teste N rectangles statiques contre un rectangle mobile.
 * Retourne le nombre de collisions. Applique le push cumulé sur *rx, *ry.
 *
 * Exemple : joueur vs liste d'ennemis
 *   NgpcRect enemies[8]; u8 n = 8;
 *   u8 hits = ngpc_rect_test_many(&player, enemies, n, &rx, &ry, NULL);
 */
u8 ngpc_rect_test_many(const NgpcRect *moving,
                        const NgpcRect *statics, u8 count,
                        s16 *rx, s16 *ry,
                        u8 *sides_out);

/* ══════════════════════════════════════════════════════
 * SWEPT AABB (objets à grande vitesse : balles, projectiles)
 * ══════════════════════════════════════════════════════
 *
 * Teste si le rect 'a' en mouvement (vx, vy en fx16 px/frame)
 * va frapper le rect 'b' statique cette frame.
 *
 * Retourne :
 *   result.hit = 1 si collision
 *   result.t   = moment du hit en fx16 [0..FX_ONE]
 *                (0 = tout de suite, FX_ONE = fin de frame, >FX_ONE = pas de hit)
 *   result.nx/ny = normale de collision (ex: nx=-1 = hit côté gauche de B)
 *
 * Usage typique (balle vs ennemi) :
 *   NgpcSweptResult sr;
 *   ngpc_swept_aabb(&bullet_rect, bullet_vx, bullet_vy, &enemy_rect, &sr);
 *   if (sr.hit) {
 *       // réduire vie ennemi
 *       // arrêter balle : pos += vel * sr.t
 *   }
 *
 * Contrainte : vx et vy en fx16 (ex: INT_TO_FX(5) = 5 px/frame).
 * Pas de rotation. B doit être statique (ou en mouvement relatif).
 */
void ngpc_swept_aabb(const NgpcRect *a, fx16 vx, fx16 vy,
                     const NgpcRect *b,
                     NgpcSweptResult *result);

/* ══════════════════════════════════════════════════════
 * HELPERS CÔTÉS INDIVIDUELS
 * ══════════════════════════════════════════════════════ */

/* Pénétration sur X uniquement (pour résolution custom) */
s16 ngpc_rect_push_x(const NgpcRect *a, const NgpcRect *b);

/* Pénétration sur Y uniquement */
s16 ngpc_rect_push_y(const NgpcRect *a, const NgpcRect *b);

#endif /* NGPC_AABB_H */
