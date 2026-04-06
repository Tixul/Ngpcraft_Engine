#ifndef NGPC_ACTOR_H
#define NGPC_ACTOR_H

/*
 * ngpc_actor -- Mouvement top-down 4/8 directions avec friction
 * =============================================================
 * 17 octets RAM par NgpcActor.
 * Adapté RPG, twin-stick, dungeon crawler.
 *
 * Principe :
 *   Chaque frame, appeler ngpc_actor_move() avec la direction de la
 *   manette, puis ngpc_actor_update() pour intégrer la physique.
 *   Si ngpc_actor_move() n'est pas appelé ce frame, la friction
 *   décélère automatiquement le personnage.
 *
 * 4 vs 8 directions :
 *   8 dirs (défaut) : diagonales normalisées (×0.707) pour éviter un
 *                     déplacement 41 % plus rapide en diagonal.
 *   4 dirs          : passer une seule direction (dx XOR dy non nul)
 *                     ou utiliser le helper ACTOR_4DIR_X/Y ci-dessous.
 *
 * Usage :
 *   Copier ngpc_actor/ dans src/
 *   OBJS += $(OBJ_DIR)/src/ngpc_actor/ngpc_actor.rel
 *   #include "ngpc_actor/ngpc_actor.h"
 *
 * Exemple :
 *   NgpcActor hero;
 *   ngpc_actor_init(&hero, INT_TO_FX(80), INT_TO_FX(76),
 *                   ACTOR_DEFAULT_SPEED, ACTOR_DEFAULT_ACCEL,
 *                   ACTOR_DEFAULT_FRICTION);
 *
 *   // Chaque frame :
 *   s8 dx = (ngpc_pad & PAD_RIGHT) - (ngpc_pad & PAD_LEFT ? 1 : 0);
 *   s8 dy = (ngpc_pad & PAD_DOWN)  - (ngpc_pad & PAD_UP   ? 1 : 0);
 *   ngpc_actor_move(&hero, dx, dy);
 *   ngpc_actor_update(&hero);
 *   ngpc_sprite_set(0, ngpc_actor_px(&hero), ngpc_actor_py(&hero), tile, pal, hero.dir_x < 0 ? SPR_HFLIP : 0);
 */

#include "ngpc_fixed/ngpc_fixed.h"   /* fx16, FxVec2, FX_MUL, FX_ADD */

/* ── Valeurs par défaut ──────────────────────────────────
 * Définir avant l'include pour surcharger. */
#ifndef ACTOR_DEFAULT_SPEED
#define ACTOR_DEFAULT_SPEED    ((fx16)32)  /* INT_TO_FX(2) — 2.0 px/frame    */
#endif
#ifndef ACTOR_DEFAULT_ACCEL
#define ACTOR_DEFAULT_ACCEL    ((fx16)4)   /* FX_QUARTER   — 0.25 px/frame²  */
#endif
#ifndef ACTOR_DEFAULT_FRICTION
#define ACTOR_DEFAULT_FRICTION ((fx16)12)  /* 12/16 = 0.75 — ralentit en 75% */
#endif

/* Constante de normalisation diagonale : 11/16 ≈ 0.6875 ≈ 1/√2 */
#define _ACTOR_DIAG_NORM  ((fx16)11)

/* ── Flags ───────────────────────────────────────────────── */
#define ACTOR_MOVING  0x01   /* ngpc_actor_move() a été appelé ce frame */

/* ── Struct (17 octets RAM) ──────────────────────────────── */
typedef struct {
    FxVec2 pos;      /* position sous-pixel (x, y)        — 4 octets */
    FxVec2 vel;      /* vitesse (px/frame)                — 4 octets */
    fx16   speed;    /* vitesse max (fx16)                — 2 octets */
    fx16   accel;    /* accélération par frame (fx16)     — 2 octets */
    fx16   friction; /* facteur de friction [0..FX_ONE]  — 2 octets */
    s8     dir_x;    /* dernière direction H (-1, 0, +1)  — 1 octet  */
    s8     dir_y;    /* dernière direction V (-1, 0, +1)  — 1 octet  */
    u8     flags;    /* ACTOR_MOVING                      — 1 octet  */
} NgpcActor;

/* ── API ─────────────────────────────────────────────────── */

/*
 * Initialise l'acteur au repos à la position (x, y) en fx16.
 * speed, accel, friction sont en fx16.
 */
void ngpc_actor_init(NgpcActor *a, fx16 x, fx16 y,
                     fx16 speed, fx16 accel, fx16 friction);

/*
 * Applique une direction ce frame.
 * dx, dy ∈ {-1, 0, +1}.
 * En diagonale (dx≠0 et dy≠0), la vitesse est normalisée par ≈0.707.
 * Met à jour dir_x et dir_y si la direction est non nulle.
 * Doit être appelé AVANT ngpc_actor_update().
 */
void ngpc_actor_move(NgpcActor *a, s8 dx, s8 dy);

/*
 * Intègre la physique et la position.
 * Applique la friction si ngpc_actor_move() n'a pas été appelé ce frame.
 * Appeler UNE FOIS par frame, après ngpc_actor_move().
 */
void ngpc_actor_update(NgpcActor *a);

/* Stoppe instantanément le mouvement (vel = 0). */
void ngpc_actor_stop(NgpcActor *a);

/* ── Accès rapides ───────────────────────────────────────── */

/* Position pixel entière. */
#define ngpc_actor_px(a)       FX_TO_INT((a)->pos.x)
#define ngpc_actor_py(a)       FX_TO_INT((a)->pos.y)

/* 1 si l'acteur s'est déplacé ce frame. */
#define ngpc_actor_is_moving(a) ((a)->flags & ACTOR_MOVING)

/* ── Helpers 4 directions ────────────────────────────────── */
/*
 * En mode 4 directions (RPG vue du dessus), passer une seule composante
 * à la fois en prioritisant l'axe horizontal ou vertical.
 * Ex (priorité horizontal) :
 *   ngpc_actor_move(&a, ACTOR_4DIR_H(dx, dy), ACTOR_4DIR_V(dx, dy));
 */
#define ACTOR_4DIR_H(dx, dy)   ((dx) ? (dx) : 0)
#define ACTOR_4DIR_V(dx, dy)   ((dx) ? 0    : (dy))

#endif /* NGPC_ACTOR_H */
