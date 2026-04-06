#ifndef NGPC_PLATFORM_H
#define NGPC_PLATFORM_H

/*
 * ngpc_platform -- Physique platformer 2D (gravité, saut, coyote time)
 * =====================================================================
 * 11 octets RAM par NgpcPlatform.
 *
 * Fonctionnement :
 *   1. Appeler ngpc_platform_update() une fois par frame.
 *      → applique gravité, intègre la position, décrémente les timers.
 *   2. Résoudre les collisions (code jeu).
 *      → si sol détecté : ajuster pos.y, puis appeler ngpc_platform_land().
 *   3. Sur pression bouton saut : ngpc_platform_press_jump().
 *   4. Sur relâchement bouton saut : ngpc_platform_release_jump().
 *
 * Coyote time : quelques frames après avoir quitté le sol, le saut reste
 * possible (évite la frustration en bord de plateforme).
 * Jump buffer : si le joueur appuie sur saut juste avant d'atterrir,
 * le saut s'exécute automatiquement à l'atterrissage.
 *
 * Constantes surchargeables (définir avant l'include) :
 *   #define PLAT_GRAVITY         4    // 0.25 px/frame²
 *   #define PLAT_MAX_FALL       64    // 4.0 px/frame
 *   #define PLAT_JUMP_VEL      -56    // -3.5 px/frame (saut)
 *   #define PLAT_JUMP_CUT_VEL  -16    // -1.0 px/frame (variable height)
 *   #define PLAT_COYOTE_FRAMES   6
 *   #define PLAT_JUMP_BUF_FRAMES 8
 *
 * Usage :
 *   Copier ngpc_platform/ dans src/
 *   OBJS += $(OBJ_DIR)/src/ngpc_platform/ngpc_platform.rel
 *   #include "ngpc_platform/ngpc_platform.h"
 */

#include "ngpc_fixed/ngpc_fixed.h"   /* fx16, FxVec2, FX_ADD, FX_MIN */

/* ── Constantes (fx16 = s16 × 1/16) ─────────────────────
 * Notation : valeur_entiere = valeur_flottante × 16
 * (FX_LIT n'est pas fiable pour les flottants négatifs.) */

#ifndef PLAT_GRAVITY
#define PLAT_GRAVITY         ((fx16)4)    /* 0.25 px/frame²  (FX_ONE/4) */
#endif
#ifndef PLAT_MAX_FALL
#define PLAT_MAX_FALL        ((fx16)64)   /* 4.0  px/frame   (INT_TO_FX(4)) */
#endif
#ifndef PLAT_JUMP_VEL
#define PLAT_JUMP_VEL        ((fx16)-56)  /* -3.5 px/frame   (-(3*16+8)) */
#endif
#ifndef PLAT_JUMP_CUT_VEL
#define PLAT_JUMP_CUT_VEL    ((fx16)-16)  /* -1.0 px/frame   (-FX_ONE) */
#endif
#ifndef PLAT_COYOTE_FRAMES
#define PLAT_COYOTE_FRAMES   6
#endif
#ifndef PLAT_JUMP_BUF_FRAMES
#define PLAT_JUMP_BUF_FRAMES 8
#endif

/* ── Flags ───────────────────────────────────────────────── */
#define PLAT_ON_GROUND  0x01   /* au sol (posé par ngpc_platform_land) */
#define PLAT_JUMPING    0x02   /* saut en cours (bouton tenu) */

/* ── Struct (11 octets RAM) ──────────────────────────────── */
typedef struct {
    FxVec2 pos;       /* position sous-pixel (x, y)     — 4 octets */
    FxVec2 vel;       /* vitesse instantanée (px/frame)  — 4 octets */
    u8     flags;     /* PLAT_ON_GROUND | PLAT_JUMPING   — 1 octet  */
    u8     coyote;    /* frames coyote restantes          — 1 octet  */
    u8     jump_buf;  /* frames buffer de saut restantes  — 1 octet  */
} NgpcPlatform;

/* ── API ─────────────────────────────────────────────────── */

/* Initialise l'état au repos à la position (x, y) en fx16. */
void ngpc_platform_init(NgpcPlatform *p, fx16 x, fx16 y);

/*
 * Met à jour la physique — appeler UNE FOIS par frame, avant la résolution
 * de collision.
 *   - Gère le coyote time (basé sur le flag ON_GROUND du frame précédent).
 *   - Efface PLAT_ON_GROUND (la collision le remettra si besoin).
 *   - Applique la gravité et plafonne la chute.
 *   - Intègre pos += vel.
 *   - Décrémente jump_buf.
 */
void ngpc_platform_update(NgpcPlatform *p);

/*
 * Appeler quand la résolution de collision détecte le sol ce frame.
 * → Annule vel.y, pose le flag ON_GROUND, efface JUMPING.
 * → Si un saut est bufferisé (jump_buf > 0), l'exécute immédiatement.
 *
 * Le code jeu doit corriger pos.y avant d'appeler cette fonction :
 *   p->pos.y = INT_TO_FX(ground_y - sprite_height);
 *   ngpc_platform_land(&p);
 */
void ngpc_platform_land(NgpcPlatform *p);

/*
 * À appeler sur pression du bouton saut (frame où le bouton passe à PRESSED).
 * → Saute immédiatement si au sol ou si coyote time actif.
 * → Sinon, enregistre le jump_buf pour le prochain atterrissage.
 */
void ngpc_platform_press_jump(NgpcPlatform *p);

/*
 * À appeler quand le bouton saut est relâché.
 * Coupe la montée si vel.y est encore négatif (variable jump height).
 */
void ngpc_platform_release_jump(NgpcPlatform *p);

/* ── Accès rapides ───────────────────────────────────────── */

/* 1 si posé sur le sol ce frame. */
#define ngpc_platform_on_ground(p)  ((p)->flags & PLAT_ON_GROUND)

/* 1 si saut en cours (bouton tenu). */
#define ngpc_platform_is_jumping(p) ((p)->flags & PLAT_JUMPING)

/* Position pixel entière. */
#define ngpc_platform_px(p)         FX_TO_INT((p)->pos.x)
#define ngpc_platform_py(p)         FX_TO_INT((p)->pos.y)

#endif /* NGPC_PLATFORM_H */
