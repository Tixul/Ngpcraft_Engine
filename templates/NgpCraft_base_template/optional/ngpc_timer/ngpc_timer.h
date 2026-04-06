#ifndef NGPC_TIMER_H
#define NGPC_TIMER_H

/*
 * ngpc_timer -- Timers de jeu (countdown, cooldown, repeat)
 * ===========================================================
 * 3 octets RAM par NgpcTimer.
 * Appeler ngpc_timer_update() une fois par frame pour chaque timer actif.
 *
 * Usage:
 *   Copier ngpc_timer/ dans src/
 *   OBJS += src/ngpc_timer/ngpc_timer.rel
 *   #include "ngpc_timer/ngpc_timer.h"
 *
 * Exemple cooldown d'attaque:
 *   static NgpcTimer attack_cd;
 *   ngpc_timer_start(&attack_cd, 20);          // 20 frames cooldown
 *
 *   if (ngpc_timer_update(&attack_cd)) {        // update chaque frame
 *       // timer expiré — attaque de nouveau autorisée
 *   }
 *   if (!ngpc_timer_active(&attack_cd)) { ... attaquer ... }
 */

#include "ngpc_hw.h"  /* u8 */

/* ── Flags ──────────────────────────────────────────────── */
#define TIMER_FLAG_ACTIVE   0x01   /* timer en cours */
#define TIMER_FLAG_REPEAT   0x02   /* repart automatiquement */
#define TIMER_FLAG_DONE     0x04   /* a expiré ce frame (one-shot) */

/* ── Type ───────────────────────────────────────────────── */
typedef struct {
    u8 count;    /* frames restantes */
    u8 period;   /* durée/période de départ */
    u8 flags;    /* TIMER_FLAG_* */
} NgpcTimer;

/* ── API ────────────────────────────────────────────────── */

/* Démarre un timer one-shot (s'arrête après 'frames' frames).
 * Retourne immédiatement si frames == 0 avec flag DONE. */
void ngpc_timer_start(NgpcTimer *t, u8 frames);

/* Démarre un timer répétitif (se relance automatiquement toutes les 'period' frames). */
void ngpc_timer_start_repeat(NgpcTimer *t, u8 period);

/* Stoppe le timer sans modifier la valeur restante. */
void ngpc_timer_stop(NgpcTimer *t);

/* Repart depuis le début (utilise la période mémorisée). */
void ngpc_timer_restart(NgpcTimer *t);

/* Met à jour le timer — appeler une fois par frame.
 * Retourne 1 si le timer a expiré ce frame, 0 sinon. */
u8 ngpc_timer_update(NgpcTimer *t);

/* 1 si le timer est en cours de décompte. */
#define ngpc_timer_active(t)    ((t)->flags & TIMER_FLAG_ACTIVE)

/* 1 si le timer one-shot vient d'expirer (vrai pendant 1 frame seulement). */
#define ngpc_timer_done(t)      ((t)->flags & TIMER_FLAG_DONE)

/* Frames restantes avant expiration. */
#define ngpc_timer_remaining(t) ((t)->count)

#endif /* NGPC_TIMER_H */
