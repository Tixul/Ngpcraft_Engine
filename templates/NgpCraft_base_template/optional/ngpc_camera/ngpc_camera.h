#ifndef NGPC_CAMERA_H
#define NGPC_CAMERA_H

/*
 * ngpc_camera -- Caméra avec suivi et scroll
 * ===========================================
 * Gère la position caméra en coords monde, le clamp sur les bords
 * de niveau, et applique le scroll via ngpc_gfx_scroll().
 *
 * RAM state : sizeof(NgpcCamera) = 10 octets par caméra.
 *
 * Usage:
 *   Copier ngpc_camera/ dans src/
 *   OBJS += src/ngpc_camera/ngpc_camera.rel
 *   #include "ngpc_camera/ngpc_camera.h"
 */

#include "ngpc_hw.h"  /* s16, u8 */

/* Taille de l'écran NGPC (pixels) */
#define CAM_SCR_W  160
#define CAM_SCR_H  152

typedef struct {
    s16 x;        /* position haut-gauche caméra en coords monde (pixels) */
    s16 y;
    s16 level_w;  /* largeur du niveau en pixels (0 = infini, pas de clamp) */
    s16 level_h;  /* hauteur du niveau en pixels */
    u8  flags;    /* CAM_FLAG_* */
} NgpcCamera;

#define CAM_FLAG_CLAMP_X  (1 << 0)   /* clamper sur les bords horizontaux */
#define CAM_FLAG_CLAMP_Y  (1 << 1)   /* clamper sur les bords verticaux   */
#define CAM_FLAG_CLAMP    (CAM_FLAG_CLAMP_X | CAM_FLAG_CLAMP_Y)

/* ── Init ────────────────────────────────────────────── */

/* Initialise la caméra. level_w/h en pixels. flags = CAM_FLAG_CLAMP usuel. */
void ngpc_cam_init(NgpcCamera *cam, s16 level_w, s16 level_h, u8 flags);

/* ── Suivi ───────────────────────────────────────────── */

/* Centre la caméra instantanément sur (tx, ty) monde. */
void ngpc_cam_follow(NgpcCamera *cam, s16 tx, s16 ty);

/* Suivi progressif (lerp). speed : 1 = lent, 8 = rapide.
 * Appeler chaque frame avant ngpc_cam_apply(). */
void ngpc_cam_follow_smooth(NgpcCamera *cam, s16 tx, s16 ty, u8 speed);

/* ── Application ─────────────────────────────────────── */

/* Applique la position caméra au scroll plane (GFX_SCR1 ou GFX_SCR2).
 * Appeler une fois par frame après le suivi. */
void ngpc_cam_apply(const NgpcCamera *cam, u8 plane);

/* ── Conversion de coordonnées ───────────────────────── */

/* Coords monde → coords écran.
 * Utiliser pour placer sprites (ngpc_sprite_move) depuis coords monde. */
void ngpc_cam_world_to_screen(const NgpcCamera *cam,
                               s16 wx, s16 wy,
                               s16 *sx, s16 *sy);

/* 1 si le point monde (wx, wy) est visible à l'écran (+ marge de sécurité). */
u8 ngpc_cam_on_screen(const NgpcCamera *cam, s16 wx, s16 wy, u8 margin);

#endif /* NGPC_CAMERA_H */
