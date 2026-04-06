#include "ngpc_transition.h"
#include "../fx/ngpc_palfx.h"

void ngpc_transition_init(NgpcTransition *tr, u8 phase_frames)
{
    ngpc_room_init(&tr->room, phase_frames ? phase_frames : 1);
    tr->type         = TRANS_FADE;
    tr->phase_frames = phase_frames ? phase_frames : 1;
}

void ngpc_transition_start(NgpcTransition *tr, u8 type)
{
    if (ngpc_room_in_transition(&tr->room)) return;
    tr->type = type;

    switch (type) {
        case TRANS_FADE: {
            u8 spd = _TRANS_SPEED(tr->phase_frames);
            /* Assombrir SCR1 + SCR2 + SPR vers le noir */
            ngpc_palfx_fade_to_black(GFX_SCR1, 0xFF, spd);
            ngpc_palfx_fade_to_black(GFX_SCR2, 0xFF, spd);
            ngpc_palfx_fade_to_black(GFX_SPR,  0xFF, spd);
            break;
        }
        case TRANS_FLASH: {
            /* Éclair blanc court sur tous les plans */
            ngpc_palfx_flash(GFX_SCR1, 0xFF, 0xFFFFu, 8u);
            ngpc_palfx_flash(GFX_SCR2, 0xFF, 0xFFFFu, 8u);
            ngpc_palfx_flash(GFX_SPR,  0xFF, 0xFFFFu, 8u);
            break;
        }
        case TRANS_INSTANT:
        default:
            /* Pas d'effet visuel */
            break;
    }

    ngpc_room_go(&tr->room, 0);  /* next_room ignoré — géré par le jeu */
}

void ngpc_transition_loaded(NgpcTransition *tr)
{
    /*
     * Pour TRANS_FADE : à ce stade le jeu a chargé ses nouvelles palettes.
     * Le fade-in doit être déclenché par le jeu APRÈS cet appel :
     *   ngpc_palfx_fade(GFX_SCR1, 0xFF, target_pal, spd);
     * ou en utilisant ngpc_transition_progress() pour interpoler manuellement.
     * (Le module ne connaît pas les couleurs cibles de la nouvelle scène.)
     */
    ngpc_room_loaded(&tr->room);
}

u8 ngpc_transition_update(NgpcTransition *tr)
{
    return ngpc_room_update(&tr->room);
}
