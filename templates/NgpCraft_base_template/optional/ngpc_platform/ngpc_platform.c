#include "ngpc_platform.h"

void ngpc_platform_init(NgpcPlatform *p, fx16 x, fx16 y) {
    p->pos.x   = x;
    p->pos.y   = y;
    p->vel.x   = 0;
    p->vel.y   = 0;
    p->flags   = 0;
    p->coyote  = 0;
    p->jump_buf = 0;
}

void ngpc_platform_update(NgpcPlatform *p) {
    /* Coyote time : recharger depuis le sol, ou décompter en l'air */
    if (p->flags & PLAT_ON_GROUND) {
        p->coyote = PLAT_COYOTE_FRAMES;
    } else if (p->coyote > 0) {
        p->coyote--;
    }

    /* Effacer le flag sol : la collision le remettra si besoin ce frame */
    p->flags &= ~PLAT_ON_GROUND;

    /* Gravité */
    p->vel.y = FX_ADD(p->vel.y, PLAT_GRAVITY);
    if (p->vel.y > PLAT_MAX_FALL) p->vel.y = PLAT_MAX_FALL;

    /* Décrémenter buffer de saut */
    if (p->jump_buf > 0) p->jump_buf--;

    /* Intégration position */
    p->pos.x = FX_ADD(p->pos.x, p->vel.x);
    p->pos.y = FX_ADD(p->pos.y, p->vel.y);
}

void ngpc_platform_land(NgpcPlatform *p) {
    p->vel.y  = 0;
    p->flags |= PLAT_ON_GROUND;
    p->flags &= ~PLAT_JUMPING;

    /* Saut bufferisé : exécuter maintenant qu'on est au sol */
    if (p->jump_buf > 0) {
        p->jump_buf = 0;
        p->vel.y    = PLAT_JUMP_VEL;
        p->coyote   = 0;
        p->flags   &= ~PLAT_ON_GROUND;
        p->flags   |= PLAT_JUMPING;
    }
}

void ngpc_platform_press_jump(NgpcPlatform *p) {
    if ((p->flags & PLAT_ON_GROUND) || p->coyote > 0) {
        /* Saut immédiat */
        p->vel.y    = PLAT_JUMP_VEL;
        p->coyote   = 0;
        p->jump_buf = 0;
        p->flags   |= PLAT_JUMPING;
        p->flags   &= ~PLAT_ON_GROUND;
    } else {
        /* Stocker le saut pour l'atterrissage suivant */
        p->jump_buf = PLAT_JUMP_BUF_FRAMES;
    }
}

void ngpc_platform_release_jump(NgpcPlatform *p) {
    /* Variable jump height : couper la montée si encore rapide */
    if ((p->flags & PLAT_JUMPING) && p->vel.y < PLAT_JUMP_CUT_VEL) {
        p->vel.y = PLAT_JUMP_CUT_VEL;
    }
    p->flags &= ~PLAT_JUMPING;
}
