#include "ngpc_anim.h"

/* flags internes (NgpcAnim.flags) */
#define _ANIM_DONE  0x01
#define _ANIM_BACK  0x02   /* direction ping-pong : 0=avant 1=arrière */

void ngpc_anim_play(NgpcAnim *a, const NgpcAnimDef *def) {
    /* Évite de redémarrer si c'est déjà l'anim courante et non terminée */
    if (a->def == def && !(a->flags & _ANIM_DONE)) return;
    a->def   = def;
    a->frame = 0;
    a->tick  = def ? def->speed : 1;
    a->flags = 0;
}

void ngpc_anim_restart(NgpcAnim *a) {
    a->frame = 0;
    a->tick  = a->def ? a->def->speed : 1;
    a->flags = 0;
}

u8 ngpc_anim_update(NgpcAnim *a) {
    if (!a->def || a->def->count == 0) return 0;
    if (a->flags & _ANIM_DONE) return 0;

    if (a->tick > 1) { a->tick--; return 0; }
    a->tick = a->def->speed;

    if (a->def->flags & ANIM_PINGPONG) {
        /* Mode ping-pong */
        if (!(a->flags & _ANIM_BACK)) {
            a->frame++;
            if (a->frame >= a->def->count) {
                /* atteint la fin — repart en arrière */
                a->frame = (a->def->count > 1) ? a->def->count - 2 : 0;
                a->flags |= _ANIM_BACK;
            }
        } else {
            if (a->frame == 0) {
                /* atteint le début — repart en avant */
                a->frame = (a->def->count > 1) ? 1 : 0;
                a->flags &= ~_ANIM_BACK;
            } else {
                a->frame--;
            }
        }
    } else if (a->def->flags & ANIM_LOOP) {
        /* Mode loop */
        a->frame++;
        if (a->frame >= a->def->count) a->frame = 0;
    } else {
        /* Mode one-shot */
        if (a->frame < a->def->count - 1) {
            a->frame++;
        } else {
            a->flags |= _ANIM_DONE;
            return 0;
        }
    }
    return 1;
}

u8 ngpc_anim_tile(const NgpcAnim *a) {
    if (!a->def) return 0;
    return a->def->frames[a->frame];
}
