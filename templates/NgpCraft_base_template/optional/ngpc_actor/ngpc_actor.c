#include "ngpc_actor.h"

void ngpc_actor_init(NgpcActor *a, fx16 x, fx16 y,
                     fx16 speed, fx16 accel, fx16 friction) {
    a->pos.x    = x;
    a->pos.y    = y;
    a->vel.x    = 0;
    a->vel.y    = 0;
    a->speed    = speed;
    a->accel    = accel;
    a->friction = friction;
    a->dir_x    = 0;
    a->dir_y    = 0;
    a->flags    = 0;
}

void ngpc_actor_move(NgpcActor *a, s8 dx, s8 dy) {
    fx16 ax, ay;

    if (!dx && !dy) return;

    /* Accélération dans la direction demandée */
    ax = dx ? (dx > 0 ? a->accel : -a->accel) : 0;
    ay = dy ? (dy > 0 ? a->accel : -a->accel) : 0;

    /* Normalisation diagonale : ×0.6875 ≈ 1/√2 pour éviter le boost diagonal */
    if (dx && dy) {
        ax = FX_MUL(ax, _ACTOR_DIAG_NORM);
        ay = FX_MUL(ay, _ACTOR_DIAG_NORM);
    }

    a->vel.x = FX_ADD(a->vel.x, ax);
    a->vel.y = FX_ADD(a->vel.y, ay);

    /* Clamp vitesse max */
    if (a->vel.x >  a->speed) a->vel.x =  a->speed;
    if (a->vel.x < -a->speed) a->vel.x = -a->speed;
    if (a->vel.y >  a->speed) a->vel.y =  a->speed;
    if (a->vel.y < -a->speed) a->vel.y = -a->speed;

    /* Mémoriser la direction pour les sprites/animations */
    if (dx) a->dir_x = dx;
    if (dy) a->dir_y = dy;

    a->flags |= ACTOR_MOVING;
}

void ngpc_actor_update(NgpcActor *a) {
    /* Friction quand aucune direction n'est appliquée ce frame */
    if (!(a->flags & ACTOR_MOVING)) {
        a->vel.x = FX_MUL(a->vel.x, a->friction);
        a->vel.y = FX_MUL(a->vel.y, a->friction);
    }
    /* Préparer le flag pour le frame suivant */
    a->flags &= ~ACTOR_MOVING;

    /* Intégration position */
    a->pos.x = FX_ADD(a->pos.x, a->vel.x);
    a->pos.y = FX_ADD(a->pos.y, a->vel.y);
}

void ngpc_actor_stop(NgpcActor *a) {
    a->vel.x = 0;
    a->vel.y = 0;
    a->flags &= ~ACTOR_MOVING;
}
