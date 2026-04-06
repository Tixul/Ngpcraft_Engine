#ifndef NGPC_KINEMATIC_H
#define NGPC_KINEMATIC_H

/*
 * ngpc_kinematic -- Corps physique générique avec intégration tilecol
 * ====================================================================
 * Déplace un objet avec vélocité fx16, friction multiplicative et
 * rebond configurable. Intègre ngpc_tilecol_move() pour la résolution
 * de collision automatique.
 *
 * Cas d'usage : rochers, barils, ennemis à physique simple, balles.
 * Pour le joueur platformer → préférer ngpc_platform.
 * Pour le top-down → préférer ngpc_actor.
 *
 * Dépend de : ngpc_fixed, ngpc_tilecol
 *
 * Usage :
 *   Copier ngpc_kinematic/ dans src/ (+ ngpc_fixed/, ngpc_tilecol/)
 *   OBJS += src/ngpc_kinematic/ngpc_kinematic.rel
 *   #include "ngpc_kinematic/ngpc_kinematic.h"
 *
 * Exemple — boule qui rebondit et roule :
 *   static NgpcKinematic ball;
 *   ngpc_kinematic_init(&ball, INT_TO_FX(80), INT_TO_FX(30),
 *                       KIN_FRICTION_MEDIUM, KIN_BOUNCE_ELASTIC);
 *
 *   // Chaque frame :
 *   ngpc_kinematic_apply_gravity(&ball, KIN_GRAVITY, KIN_MAX_FALL);
 *   ngpc_kinematic_move(&ball, &col, BALL_W, BALL_H);
 *   ngpc_sprite_set(SPR_BALL,
 *                   ngpc_kinematic_px(&ball), ngpc_kinematic_py(&ball),
 *                   BALL_TILE, 0, 0);
 *
 * Friction :
 *   KIN_FRICTION_NONE   = FX_ONE (0%) — aucune friction, vélocité conservée
 *   KIN_FRICTION_LOW    = 15 (6%)     — glissant (glace, espace)
 *   KIN_FRICTION_MEDIUM = 14 (12%)    — sol normal
 *   KIN_FRICTION_HIGH   = 12 (25%)    — lourd (boue, eau)
 *
 * Rebond :
 *   KIN_BOUNCE_NONE     = 0           — pas de rebond (s'arrête au mur)
 *   KIN_BOUNCE_SOFT     = 8 (50%)     — rebond amorti
 *   KIN_BOUNCE_ELASTIC  = 13 (81%)    — rebond vif
 *   KIN_BOUNCE_PERFECT  = FX_ONE      — rebond parfait (physique idéale)
 */

#include "ngpc_hw.h"
#include "../ngpc_fixed/ngpc_fixed.h"
#include "../ngpc_tilecol/ngpc_tilecol.h"

/* ── Constantes prédéfinies ──────────────────────────────── */

#define KIN_GRAVITY         ((fx16)4)    /* 0.25 px/frame² */
#define KIN_MAX_FALL        ((fx16)64)   /* 4.0 px/frame   */

#define KIN_FRICTION_NONE   FX_ONE       /* ×1.000 */
#define KIN_FRICTION_LOW    ((fx16)15)   /* ×0.937 */
#define KIN_FRICTION_MEDIUM ((fx16)14)   /* ×0.875 */
#define KIN_FRICTION_HIGH   ((fx16)12)   /* ×0.750 */

#define KIN_BOUNCE_NONE     ((fx16)0)
#define KIN_BOUNCE_SOFT     ((fx16)8)    /* ×0.500 */
#define KIN_BOUNCE_ELASTIC  ((fx16)13)   /* ×0.813 */
#define KIN_BOUNCE_PERFECT  FX_ONE       /* ×1.000 */

/* ── Flags ───────────────────────────────────────────────── */
#define KIN_ON_GROUND  0x01
#define KIN_ON_CEIL    0x02
#define KIN_ON_WALL    0x04

/* ── Struct (11 octets) ──────────────────────────────────── */
typedef struct {
    FxVec2 pos;      /* position fx16 (pixel.sous-pixel)         — 4 octets */
    FxVec2 vel;      /* vélocité fx16 (px/frame)                 — 4 octets */
    fx16   friction; /* facteur multiplicatif [0..FX_ONE]        — 2 octets */
    fx16   bounce;   /* coefficient de rebond [0..FX_ONE]        — 2 octets */
    u8     flags;    /* KIN_ON_GROUND | KIN_ON_CEIL | KIN_ON_WALL — 1 octet */
} NgpcKinematic;

/* ── API ─────────────────────────────────────────────────── */

/*
 * Initialise le corps physique à la position (x, y).
 * friction : KIN_FRICTION_* — appliqué à vel.x et vel.y chaque frame.
 * bounce   : KIN_BOUNCE_*  — coefficient de rebond [0..FX_ONE].
 */
void ngpc_kinematic_init(NgpcKinematic *k, fx16 x, fx16 y,
                         fx16 friction, fx16 bounce);

/*
 * Ajoute la gravité à vel.y, plafonnée à max_fall.
 * Appeler AVANT ngpc_kinematic_move().
 * Omettre pour des objets sans gravité (top-down, objets flottants).
 */
void ngpc_kinematic_apply_gravity(NgpcKinematic *k,
                                  fx16 gravity, fx16 max_fall);

/*
 * Met à jour le corps :
 *   1. Applique friction à vel.x et vel.y
 *   2. Intègre la position (pos += vel)
 *   3. Appelle ngpc_tilecol_move() pour la résolution de collision
 *   4. Applique le rebond sur les axes bloqués
 *   5. Met à jour k->flags (KIN_ON_GROUND, KIN_ON_CEIL, KIN_ON_WALL)
 *
 * col : descripteur de la map de collision (NgpcTileCol)
 * w, h : dimensions de la hitbox en pixels
 *
 * Contrainte : |vel| ≤ 8 px/frame pour éviter le tunnel-through.
 */
void ngpc_kinematic_move(NgpcKinematic *k,
                         const NgpcTileCol *col, u8 w, u8 h);

/*
 * Ajoute une impulsion instantanée à la vélocité.
 * Exemple : explosion → ngpc_kinematic_impulse(&rock, INT_TO_FX(-2), INT_TO_FX(-4));
 */
void ngpc_kinematic_impulse(NgpcKinematic *k, fx16 ix, fx16 iy);

/* Stoppe le corps instantanément (vel = 0). */
void ngpc_kinematic_stop(NgpcKinematic *k);

/* Position pixel entière (pour ngpc_sprite_set). */
#define ngpc_kinematic_px(k)         ((u8)FX_TO_INT((k)->pos.x))
#define ngpc_kinematic_py(k)         ((u8)FX_TO_INT((k)->pos.y))

/* 1 si posé sur le sol. */
#define ngpc_kinematic_on_ground(k)  ((k)->flags & KIN_ON_GROUND)

#endif /* NGPC_KINEMATIC_H */
