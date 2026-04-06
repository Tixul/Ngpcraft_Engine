#ifndef NGPC_ANIM_H
#define NGPC_ANIM_H

/*
 * ngpc_anim -- Animation de sprites par séquence de frames
 * =========================================================
 * NgpcAnimDef : définition statique en ROM (const), zéro RAM.
 * NgpcAnim    : état courant en RAM, 4 octets par sprite animé.
 *
 * Modes : LOOP (boucle), PINGPONG (aller-retour), ONESHOT (joue une fois).
 * Dépendance : aucune (stand-alone).
 *
 * Usage:
 *   Copier ngpc_anim/ dans src/
 *   OBJS += src/ngpc_anim/ngpc_anim.rel
 *   #include "ngpc_anim/ngpc_anim.h"
 *
 * Exemple :
 *   static const u8 run_frames[] = { 2, 3, 4, 5 };  // indices tile relatifs
 *   static const NgpcAnimDef anim_run = ANIM_DEF(run_frames, 4, 4, ANIM_LOOP);
 *
 *   NgpcAnim anim;
 *   ngpc_anim_play(&anim, &anim_run);
 *
 *   // Chaque frame :
 *   ngpc_anim_update(&anim);
 *   ngpc_sprite_set(0, x, y, TILE_BASE + ngpc_anim_tile(&anim), pal, flags);
 */

#include "ngpc_hw.h"  /* u8 */

/* ── Flags de comportement ──────────────────────────────── */
#define ANIM_ONESHOT    0x00   /* joue une fois et s'arrête sur la dernière frame */
#define ANIM_LOOP       0x01   /* boucle en retournant à la frame 0 */
#define ANIM_PINGPONG   0x03   /* aller-retour (implique loop) */

/* ── Définition (const, en ROM) ─────────────────────────── */
typedef struct {
    const u8 *frames;    /* tableau d'indices tile (0 = première tile du set) */
    u8        count;     /* nombre de frames dans la séquence */
    u8        speed;     /* frames NGPC par frame d'anim (1=60fps, 4=15fps, 8=7fps) */
    u8        flags;     /* ANIM_LOOP / ANIM_PINGPONG / ANIM_ONESHOT */
} NgpcAnimDef;

/* ── Macro de définition (données constantes en ROM) ──────
 * Ex: static const NgpcAnimDef anim_idle = ANIM_DEF(idle_frames, 2, 8, ANIM_LOOP); */
#define ANIM_DEF(frm, cnt, spd, flg) { (frm), (u8)(cnt), (u8)(spd), (u8)(flg) }

/* ── État courant (en RAM, 4 octets) ────────────────────── */
typedef struct {
    const NgpcAnimDef *def;    /* définition courante (NULL = pas d'anim) */
    u8 frame;                  /* index courant dans def->frames[] */
    u8 tick;                   /* compteur décroissant avant la prochaine frame */
    u8 flags;                  /* bit0=done, bit1=dir(pingpong: 0=avant 1=arrière) */
} NgpcAnim;

/* ── API ────────────────────────────────────────────────── */

/* Lance ou change l'animation. Repart toujours depuis la frame 0.
 * Si def == anim courante et non terminée, ne fait rien (évite restart). */
void ngpc_anim_play(NgpcAnim *a, const NgpcAnimDef *def);

/* Force le restart même si def est déjà l'animation courante. */
void ngpc_anim_restart(NgpcAnim *a);

/* Met à jour l'animation. Appeler une fois par frame.
 * Retourne 1 si la frame visible a changé ce frame, 0 sinon. */
u8 ngpc_anim_update(NgpcAnim *a);

/* Tile courant à utiliser pour ngpc_sprite_set.
 * Ajouter TILE_BASE : ngpc_sprite_set(id, x, y, TILE_BASE + ngpc_anim_tile(&a), pal, f); */
u8 ngpc_anim_tile(const NgpcAnim *a);

/* 1 si l'animation ONESHOT est terminée (reste sur la dernière frame). */
#define ngpc_anim_done(a)   ((a)->flags & 0x01)

#endif /* NGPC_ANIM_H */
