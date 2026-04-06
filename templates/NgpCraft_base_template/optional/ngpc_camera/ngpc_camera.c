#include "ngpc_camera.h"
#include "ngpc_gfx.h"   /* ngpc_gfx_scroll */

/* ── Clamp interne ─────────────────────────────────── */

static void cam_clamp(NgpcCamera *cam)
{
    if (cam->flags & CAM_FLAG_CLAMP_X) {
        if (cam->level_w > CAM_SCR_W) {
            if (cam->x < 0)                          cam->x = 0;
            if (cam->x > cam->level_w - CAM_SCR_W)  cam->x = cam->level_w - CAM_SCR_W;
        } else {
            cam->x = 0;  /* niveau plus petit que l'écran : caméra fixe */
        }
    }
    if (cam->flags & CAM_FLAG_CLAMP_Y) {
        if (cam->level_h > CAM_SCR_H) {
            if (cam->y < 0)                          cam->y = 0;
            if (cam->y > cam->level_h - CAM_SCR_H)  cam->y = cam->level_h - CAM_SCR_H;
        } else {
            cam->y = 0;
        }
    }
}

/* ── API ───────────────────────────────────────────── */

void ngpc_cam_init(NgpcCamera *cam, s16 level_w, s16 level_h, u8 flags)
{
    cam->x       = 0;
    cam->y       = 0;
    cam->level_w = level_w;
    cam->level_h = level_h;
    cam->flags   = flags;
}

void ngpc_cam_follow(NgpcCamera *cam, s16 tx, s16 ty)
{
    cam->x = tx - (s16)(CAM_SCR_W / 2);
    cam->y = ty - (s16)(CAM_SCR_H / 2);
    cam_clamp(cam);
}

void ngpc_cam_follow_smooth(NgpcCamera *cam, s16 tx, s16 ty, u8 speed)
{
    s16 target_x = tx - (s16)(CAM_SCR_W / 2);
    s16 target_y = ty - (s16)(CAM_SCR_H / 2);
    s16 dx = target_x - cam->x;
    s16 dy = target_y - cam->y;

    /* Division entière : décale d'une fraction du delta chaque frame.
     * speed=1 → quasi instantané, speed=8 → très progressif.
     * Le +1/-1 évite de bloquer à 1 pixel de la cible quand dx/speed==0.
     * On clamp ensuite pour ne jamais dépasser la cible (évite oscillation). */
    {
        s16 sx, sy;
        sx = (dx > 0) ? (s16)((dx / speed) + 1) : (s16)((dx / speed) - 1);
        sy = (dy > 0) ? (s16)((dy / speed) + 1) : (s16)((dy / speed) - 1);
        /* Clamp : ne pas dépasser la cible */
        if (dx > 0 && sx > dx) sx = dx;
        if (dx < 0 && sx < dx) sx = dx;
        if (dy > 0 && sy > dy) sy = dy;
        if (dy < 0 && sy < dy) sy = dy;
        if (dx != 0) cam->x += sx;
        if (dy != 0) cam->y += sy;
    }

    cam_clamp(cam);
}

void ngpc_cam_apply(const NgpcCamera *cam, u8 plane)
{
    /* Les registres scroll hardware sont 8 bits (tilemap 256×256 px).
     * Troncature volontaire : les 8 bits bas de la position monde. */
    ngpc_gfx_scroll(plane, (u8)(cam->x & 0xFF), (u8)(cam->y & 0xFF));
}

void ngpc_cam_world_to_screen(const NgpcCamera *cam,
                               s16 wx, s16 wy,
                               s16 *sx, s16 *sy)
{
    *sx = wx - cam->x;
    *sy = wy - cam->y;
}

u8 ngpc_cam_on_screen(const NgpcCamera *cam, s16 wx, s16 wy, u8 margin)
{
    s16 sx = wx - cam->x;
    s16 sy = wy - cam->y;
    return sx >= -(s16)margin && sx < (s16)(CAM_SCR_W + margin) &&
           sy >= -(s16)margin && sy < (s16)(CAM_SCR_H + margin);
}
