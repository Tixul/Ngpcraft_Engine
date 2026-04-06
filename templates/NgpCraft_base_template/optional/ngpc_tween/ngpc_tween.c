#include "ngpc_tween.h"

/* Applique la fonction d'easing choisie à t ∈ [0..FX_ONE]. */
static fx16 _apply_ease(u8 ease, fx16 t) {
    switch (ease) {
        case TWEEN_EASE_IN_QUAD:     return EASE_IN_QUAD(t);
        case TWEEN_EASE_OUT_QUAD:    return EASE_OUT_QUAD(t);
        case TWEEN_EASE_INOUT_QUAD:  return EASE_INOUT_QUAD(t);
        case TWEEN_EASE_IN_CUBIC:    return EASE_IN_CUBIC(t);
        case TWEEN_EASE_OUT_CUBIC:   return EASE_OUT_CUBIC(t);
        case TWEEN_EASE_INOUT_CUBIC: return EASE_INOUT_CUBIC(t);
        case TWEEN_EASE_SMOOTH:      return EASE_SMOOTH(t);
        default:                     return t; /* TWEEN_EASE_LINEAR */
    }
}

void ngpc_tween_start(NgpcTween *tw, fx16 from, fx16 to,
                      u8 duration, u8 ease, u8 flags) {
    tw->from     = from;
    tw->to       = to;
    tw->value    = from;
    tw->tick     = 0;
    tw->duration = duration;
    tw->ease     = ease;
    tw->flags    = flags & (TWEEN_LOOP | TWEEN_PINGPONG);

    if (duration == 0) {
        tw->value  = to;
        tw->flags |= TWEEN_DONE;
    }
}

u8 ngpc_tween_update(NgpcTween *tw) {
    fx16 t;

    if (tw->flags & TWEEN_DONE) return 0;

    if (tw->tick >= tw->duration) {
        /* Fin de phase — fixer la valeur finale */
        tw->value = tw->to;

        if (tw->flags & TWEEN_PINGPONG) {
            /* Inverser from/to pour la phase retour */
            fx16 tmp = tw->from;
            tw->from = tw->to;
            tw->to   = tmp;
            tw->tick = 0;
        } else if (tw->flags & TWEEN_LOOP) {
            tw->tick = 0;
        } else {
            tw->flags |= TWEEN_DONE;
            return 0;
        }
        return 1;
    }

    /* t = tick / duration en fx16 */
    t = (fx16)(((s16)tw->tick << FX_SHIFT) / (s16)tw->duration);
    t = _apply_ease(tw->ease, t);

    tw->value = FX_LERP(tw->from, tw->to, t);
    tw->tick++;
    return 1;
}

void ngpc_tween_restart(NgpcTween *tw) {
    tw->tick  = 0;
    tw->value = tw->from;
    tw->flags &= ~TWEEN_DONE;
}
