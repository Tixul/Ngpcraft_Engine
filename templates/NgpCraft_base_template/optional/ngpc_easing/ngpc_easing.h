#ifndef NGPC_EASING_H
#define NGPC_EASING_H

/*
 * ngpc_easing -- Fonctions de lissage (easing) en fixe-point 8.4
 * ================================================================
 * Toutes les fonctions prennent t ∈ [0..FX_ONE] et retournent [0..FX_ONE].
 * Header-only : pas de .c à ajouter au makefile.
 *
 * Nécessite : #include "ngpc_fixed/ngpc_fixed.h" avant (ou en même temps).
 *
 * Précision : format 8.4 (1/16 px). Les fonctions cubiques perdent 1 LSB
 * aux extrémités — comportement attendu sur CPU sans FPU.
 *
 * Usage :
 *   fx16 y = EASE_OUT_QUAD(t);                     // t ∈ [0..FX_ONE]
 *   fx16 pos = FX_LERP(a, b, EASE_OUT_QUAD(t));    // interpolation lissée
 *   fx16 pos = EASE_LERP(a, b, frame, 20, EASE_OUT_CUBIC); // tick 0..20
 *
 * Copier ngpc_easing/ dans optional/ (ou src/), pas de makefile à modifier.
 */

#include "ngpc_fixed/ngpc_fixed.h"   /* fx16, FX_ONE, FX_HALF, FX_MUL, FX_LERP */

/* ── Helpers internes (préfixe _EZ_) ─────────────────── */

#define _EZ_SQ(t)    FX_MUL((t), (t))               /* t²  */
#define _EZ_CB(t)    FX_MUL(_EZ_SQ(t), (t))         /* t³  */

/* ── Linéaire ──────────────────────────────────────────── */

/* y = t  (identité) */
#define EASE_LINEAR(t)         (t)

/* ── Quadratique (t²) ─────────────────────────────────── */

/* Accélère depuis 0 : y = t² */
#define EASE_IN_QUAD(t)        _EZ_SQ(t)

/* Décélère vers 1 : y = 1 - (1-t)² */
#define EASE_OUT_QUAD(t)       ((fx16)(FX_ONE - _EZ_SQ(FX_ONE - (t))))

/* Accélère puis décélère : 2t² si t<0.5, sinon 1 - 2(1-t)² */
#define EASE_INOUT_QUAD(t)     ((fx16)((t) < FX_HALF                           \
    ? (_EZ_SQ(t) << 1)                                                          \
    : (FX_ONE - (_EZ_SQ(FX_ONE - (t)) << 1))))

/* ── Cubique (t³) ─────────────────────────────────────── */

/* Accélère depuis 0 : y = t³ */
#define EASE_IN_CUBIC(t)       _EZ_CB(t)

/* Décélère vers 1 : y = 1 - (1-t)³ */
#define EASE_OUT_CUBIC(t)      ((fx16)(FX_ONE - _EZ_CB(FX_ONE - (t))))

/* Accélère puis décélère : 4t³ si t<0.5, sinon 1 - 4(1-t)³ */
#define EASE_INOUT_CUBIC(t)    ((fx16)((t) < FX_HALF                           \
    ? (_EZ_CB(t) << 2)                                                          \
    : (FX_ONE - (_EZ_CB(FX_ONE - (t)) << 2))))

/* ── Lissage Hermite (smooth step) ────────────────────── */

/* y = 3t² - 2t³  (dérivée nulle en t=0 et t=1, courbe en S).
 * Préféré à EASE_INOUT_QUAD pour les transitions de caméra
 * ou de palette — pente plus douce aux extremes. */
#define EASE_SMOOTH(t)         ((fx16)(FX_MUL(INT_TO_FX(3), _EZ_SQ(t))        \
                                     - FX_MUL(INT_TO_FX(2), _EZ_CB(t))))

/* ── Lerp avec easing intégré ─────────────────────────── */

/*
 * Convertit un compteur entier [0..total] en t fx16 [0..FX_ONE].
 * Attention : utilise une division entière (lente) — appeler une seule
 * fois par frame, pas dans une boucle interne.
 */
#define _EZ_T(tick, total)  ((fx16)(((s16)(tick) << FX_SHIFT) / (s16)(total)))

/*
 * EASE_LERP(a, b, tick, total, fn)
 * Interpole de a à b avec la fonction d'easing fn.
 * tick : frame actuelle (u8 ou s16), total : durée totale.
 *
 * Exemple — déplacer un sprite de x=10 à x=100 en 30 frames avec ease-out :
 *   fx16 x = EASE_LERP(INT_TO_FX(10), INT_TO_FX(100), frame, 30, EASE_OUT_QUAD);
 *   ngpc_sprite_set_x(spr, FX_TO_INT(x));
 */
#define EASE_LERP(a, b, tick, total, fn) \
    FX_LERP((a), (b), fn(_EZ_T((tick), (total))))

#endif /* NGPC_EASING_H */
