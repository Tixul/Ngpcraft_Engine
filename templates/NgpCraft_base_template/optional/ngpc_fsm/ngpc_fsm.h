#ifndef NGPC_FSM_H
#define NGPC_FSM_H

/*
 * ngpc_fsm -- Machine d'états finis (Finite State Machine)
 * =========================================================
 * Suivi léger des transitions d'état. Header-only, 3 octets RAM.
 * Les états sont des u8 — définir ses propres constantes (enum ou #define).
 *
 * Usage:
 *   Copier ngpc_fsm/ dans src/ (header-only, rien à compiler)
 *   #include "ngpc_fsm/ngpc_fsm.h"
 *
 * Exemple :
 *   #define ST_IDLE  0
 *   #define ST_RUN   1
 *   #define ST_JUMP  2
 *
 *   NgpcFsm fsm;
 *   ngpc_fsm_init(&fsm, ST_IDLE);
 *
 *   // Chaque frame :
 *   switch (fsm.cur) {
 *     case ST_IDLE:
 *       if (ngpc_fsm_entered(&fsm)) { ... init idle ... }
 *       if (input_right) ngpc_fsm_goto(&fsm, ST_RUN);
 *       break;
 *     case ST_RUN:
 *       if (ngpc_fsm_entered(&fsm)) { ... init run ... }
 *       ...
 *   }
 *   ngpc_fsm_tick(&fsm);   // toujours en fin de frame
 */

#include "ngpc_hw.h"  /* u8 */

/* ── Type ───────────────────────────────────────────────── */
typedef struct {
    u8 cur;       /* état courant */
    u8 prev;      /* état précédent (avant la dernière transition) */
    u8 entered;   /* 1 le premier frame après une transition */
} NgpcFsm;

/* ── API (macros / inline pour zéro overhead) ───────────── */

/* Initialise la FSM dans l'état 'initial'. */
#define ngpc_fsm_init(f, initial) \
    do { (f)->cur = (initial); (f)->prev = (initial); (f)->entered = 1; } while(0)

/* Déclenche une transition vers 'new_state'.
 * 'entered' sera vrai pendant exactement 1 frame. */
#define ngpc_fsm_goto(f, new_state) \
    do { (f)->prev = (f)->cur; (f)->cur = (new_state); (f)->entered = 1; } while(0)

/* 1 si on est au premier frame de l'état courant. */
#define ngpc_fsm_entered(f)   ((f)->entered)

/* 1 si l'état a changé depuis le frame précédent. */
#define ngpc_fsm_changed(f)   ((f)->cur != (f)->prev)

/* À appeler en FIN de frame, après la logique de mise à jour. */
#define ngpc_fsm_tick(f)      do { (f)->entered = 0; (f)->prev = (f)->cur; } while(0)

#endif /* NGPC_FSM_H */
