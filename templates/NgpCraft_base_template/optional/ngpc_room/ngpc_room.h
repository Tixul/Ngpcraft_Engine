#ifndef NGPC_ROOM_H
#define NGPC_ROOM_H

/*
 * ngpc_room -- Transitions entre rooms (timer + état)
 * =====================================================
 * Machine d'état qui séquence le passage d'une room à une autre :
 *   1. ROOM_FADE_OUT  (N frames) — le jeu applique son effet de sortie
 *   2. ROOM_LOAD      (1 frame)  — le jeu charge la room suivante
 *   3. ROOM_FADE_IN   (N frames) — le jeu applique son effet d'entrée
 *   4. ROOM_DONE      (1 frame)  — signal de fin, puis retour IDLE
 *
 * ngpc_room ne gère QUE le timing et l'état.
 * L'effet visuel (fade, slide) est géré par le jeu avec ngpc_palfx ou ngpc_tween.
 *
 * 4 octets RAM par NgpcRoom.
 *
 * Dépend de : ngpc_hw.h uniquement
 *
 * Usage :
 *   Copier ngpc_room/ dans src/
 *   OBJS += src/ngpc_room/ngpc_room.rel
 *   #include "ngpc_room/ngpc_room.h"
 *
 * Exemple avec ngpc_palfx :
 *   static NgpcRoom room;
 *   ngpc_room_init(&room, 30);   // 30 frames par phase
 *
 *   // Déclencher une transition (player passe une porte) :
 *   ngpc_palfx_fade_to_black(GFX_SCR1, 0, 2);
 *   ngpc_palfx_fade_to_black(GFX_SPR,  0, 2);
 *   ngpc_room_go(&room, ROOM_CAVE);
 *
 *   // Chaque frame :
 *   u8 r = ngpc_room_update(&room);
 *   if (r == ROOM_LOAD) {
 *       load_level(room.next_room);
 *       ngpc_gfx_set_palette(GFX_SCR1, 0, 0, 0, 0, 0);  // palettes à noir
 *       ngpc_gfx_set_palette(GFX_SPR,  0, 0, 0, 0, 0);
 *       ngpc_palfx_fade(GFX_SCR1, 0, bg_colors, 2);     // fade vers vraies couleurs
 *       ngpc_palfx_fade(GFX_SPR,  0, spr_colors, 2);
 *       ngpc_room_loaded(&room);
 *   }
 *   if (r == ROOM_DONE) gameplay_active = 1;
 */

#include "ngpc_hw.h"

/* ── Retours de ngpc_room_update() ──────────────────────── */
#define ROOM_IDLE      0   /* pas de transition */
#define ROOM_FADE_OUT  1   /* phase sortie       */
#define ROOM_LOAD      2   /* charger next_room  */
#define ROOM_FADE_IN   3   /* phase entrée       */
#define ROOM_DONE      4   /* terminé (1 frame)  */

/* ── Struct (4 octets RAM) ───────────────────────────────── */
typedef struct {
    u8 state;      /* ROOM_* courant                  */
    u8 next_room;  /* index room cible                */
    u8 timer;      /* frames restantes dans la phase  */
    u8 duration;   /* durée de chaque phase (frames)  */
} NgpcRoom;

/* ── API ─────────────────────────────────────────────────── */

/* Initialise la structure. phase_frames = durée de chaque phase (ex: 30). */
void ngpc_room_init(NgpcRoom *r, u8 phase_frames);

/*
 * Démarre une transition vers 'next_room'.
 * Le jeu doit lancer son effet visuel de sortie en même temps.
 * N'a pas d'effet si une transition est déjà en cours.
 */
void ngpc_room_go(NgpcRoom *r, u8 next_room);

/*
 * Signale que le chargement est terminé — appeler PENDANT ROOM_LOAD.
 * Lance la phase ROOM_FADE_IN.
 * Le jeu doit lancer son effet visuel d'entrée après cet appel.
 */
void ngpc_room_loaded(NgpcRoom *r);

/*
 * Met à jour la transition — appeler UNE FOIS par frame.
 * Retourne ROOM_IDLE / ROOM_FADE_OUT / ROOM_LOAD / ROOM_FADE_IN / ROOM_DONE.
 */
u8 ngpc_room_update(NgpcRoom *r);

/* 1 si une transition est en cours (bloquer gameplay + input). */
#define ngpc_room_in_transition(r)  ((r)->state != ROOM_IDLE)

/*
 * Progression de la phase courante en [0..255].
 * 0 = début de la phase, 255 = fin.
 * Utile pour interpoler un effet visuel sans ngpc_palfx.
 *   ROOM_FADE_OUT : brightness = 255 - ngpc_room_progress(r)
 *   ROOM_FADE_IN  : brightness = ngpc_room_progress(r)
 */
u8 ngpc_room_progress(const NgpcRoom *r);

#endif /* NGPC_ROOM_H */
