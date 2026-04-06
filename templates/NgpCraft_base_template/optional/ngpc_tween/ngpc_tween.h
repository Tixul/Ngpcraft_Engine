#ifndef NGPC_TWEEN_H
#define NGPC_TWEEN_H

/*
 * ngpc_tween -- Interpolation de valeur dans le temps
 * ===================================================
 * Tweene une valeur fx16 de 'from' à 'to' en N frames avec easing.
 * 10 octets RAM par NgpcTween.
 *
 * Modes :
 *   One-shot (défaut)  : va de from à to et s'arrête (TWEEN_DONE).
 *   TWEEN_LOOP         : repart depuis from quand terminé.
 *   TWEEN_PINGPONG     : va de from à to puis de to à from, en boucle.
 *
 * Nécessite : ngpc_easing/ et ngpc_fixed/ dans le même répertoire src/.
 *
 * Usage :
 *   Copier ngpc_tween/ dans src/
 *   OBJS += $(OBJ_DIR)/src/ngpc_tween/ngpc_tween.rel
 *   #include "ngpc_tween/ngpc_tween.h"
 *
 * Exemple — fondu luminosité 0→8 en 30 frames :
 *   NgpcTween fade;
 *   ngpc_tween_start(&fade, INT_TO_FX(0), INT_TO_FX(8), 30,
 *                    TWEEN_EASE_OUT_QUAD, 0);
 *   // Chaque frame :
 *   ngpc_tween_update(&fade);
 *   ngpc_palfx_set_brightness(0, FX_TO_INT(fade.value));
 *
 * Exemple — déplacement caméra lissé :
 *   NgpcTween cx;
 *   ngpc_tween_start(&cx, cam_x, target_x, 20, TWEEN_EASE_OUT_CUBIC, 0);
 *   // Chaque frame :
 *   ngpc_tween_update(&cx);
 *   ngpc_gfx_set_scroll_x(GFX_SCR1, FX_TO_INT(cx.value));
 *
 * Exemple — pulsation en boucle (PINGPONG) :
 *   NgpcTween pulse;
 *   ngpc_tween_start(&pulse, INT_TO_FX(0), INT_TO_FX(8), 30,
 *                    TWEEN_EASE_SMOOTH, TWEEN_PINGPONG);
 */

#include "ngpc_easing/ngpc_easing.h"   /* EASE_*, fx16, FX_LERP, FX_SHIFT */

/* ── Fonctions d'easing disponibles ─────────────────────── */
#define TWEEN_EASE_LINEAR      0
#define TWEEN_EASE_IN_QUAD     1
#define TWEEN_EASE_OUT_QUAD    2
#define TWEEN_EASE_INOUT_QUAD  3
#define TWEEN_EASE_IN_CUBIC    4
#define TWEEN_EASE_OUT_CUBIC   5
#define TWEEN_EASE_INOUT_CUBIC 6
#define TWEEN_EASE_SMOOTH      7

/* ── Flags ───────────────────────────────────────────────── */
#define TWEEN_LOOP      0x01   /* relance depuis from quand terminé */
#define TWEEN_PINGPONG  0x02   /* aller-retour en boucle (les from/to s'échangent) */
#define TWEEN_DONE      0x04   /* terminé (one-shot seulement) */

/* ── Struct (10 octets RAM) ──────────────────────────────── */
typedef struct {
    fx16 from;     /* valeur de départ             — 2 octets */
    fx16 to;       /* valeur cible                 — 2 octets */
    fx16 value;    /* valeur courante (à lire)     — 2 octets */
    u8   tick;     /* frame courante (0..duration) — 1 octet  */
    u8   duration; /* durée totale (frames, max 255)— 1 octet */
    u8   flags;    /* TWEEN_LOOP / DONE / PINGPONG — 1 octet  */
    u8   ease;     /* TWEEN_EASE_*                 — 1 octet  */
} NgpcTween;

/* ── API ─────────────────────────────────────────────────── */

/*
 * Lance le tween.
 * flags : 0 (one-shot) | TWEEN_LOOP | TWEEN_PINGPONG.
 * ease  : TWEEN_EASE_*.
 * Si duration == 0 : value = to immédiatement, flag DONE posé.
 */
void ngpc_tween_start(NgpcTween *tw, fx16 from, fx16 to,
                      u8 duration, u8 ease, u8 flags);

/*
 * Met à jour le tween — appeler UNE FOIS par frame.
 * Retourne 1 si encore en cours, 0 si terminé (one-shot).
 * Lire tw->value pour la valeur interpolée courante.
 */
u8 ngpc_tween_update(NgpcTween *tw);

/*
 * Repart depuis le début (conserve from/to/duration/ease/flags actuels).
 * Attention : après un PINGPONG, from/to peuvent être dans l'ordre inverse.
 * Pour repartir from → to d'origine, appeler ngpc_tween_start() à nouveau.
 */
void ngpc_tween_restart(NgpcTween *tw);

/* 1 si le tween one-shot est terminé. */
#define ngpc_tween_is_done(tw)     ((tw)->flags & TWEEN_DONE)

/* 1 si le tween est encore actif (en cours ou en boucle). */
#define ngpc_tween_is_running(tw)  (!((tw)->flags & TWEEN_DONE))

#endif /* NGPC_TWEEN_H */
