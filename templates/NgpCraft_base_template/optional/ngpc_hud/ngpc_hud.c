#include "ngpc_hud.h"
#include "ngpc_gfx.h"    /* ngpc_gfx_put_tile */
#include "ngpc_text.h"   /* ngpc_text_print_dec, ngpc_text_print_num */
#include "ngpc_sprite.h" /* ngpc_sprite_set, ngpc_sprite_hide */

/* ── Barre de valeur ─────────────────────────────────────── */

void ngpc_hud_bar_init(NgpcHudBar *bar,
                       u8 plane, u8 tx, u8 ty, u8 len,
                       u8 max_val,
                       u16 tile_full, u16 tile_half, u16 tile_empty,
                       u8 pal)
{
    bar->plane      = plane;
    bar->tx         = tx;
    bar->ty         = ty;
    bar->len        = len;
    bar->cur        = max_val;
    bar->max_val    = max_val;
    bar->tile_full  = tile_full;
    bar->tile_half  = tile_half;
    bar->tile_empty = tile_empty;
    bar->pal        = pal;
}

void ngpc_hud_bar_draw(const NgpcHudBar *bar)
{
    u8 i;
    u8 cur = bar->cur;

    if (bar->tile_half != 0) {
        /* Précision double : 2 unités par tile (full=2, half=1, empty=0) */
        for (i = 0; i < bar->len; i++) {
            u16 t;
            if (cur >= 2) {
                t = bar->tile_full;
                cur -= 2;
            } else if (cur == 1) {
                t = bar->tile_half;
                cur = 0;
            } else {
                t = bar->tile_empty;
            }
            ngpc_gfx_put_tile(bar->plane, (u8)(bar->tx + i), bar->ty, t, bar->pal);
        }
    } else {
        /* Précision simple : 1 unité par tile (full=1, empty=0) */
        for (i = 0; i < bar->len; i++) {
            u16 t = (cur > 0) ? bar->tile_full : bar->tile_empty;
            if (cur > 0) cur--;
            ngpc_gfx_put_tile(bar->plane, (u8)(bar->tx + i), bar->ty, t, bar->pal);
        }
    }
}

void ngpc_hud_bar_set(NgpcHudBar *bar, u8 value)
{
    if (value > bar->max_val) value = bar->max_val;
    bar->cur = value;
    ngpc_hud_bar_draw(bar);
}

/* ── Score ───────────────────────────────────────────────── */

void ngpc_hud_score_draw(u8 plane, u8 pal, u8 tx, u8 ty,
                         u16 score, u8 digits, u8 zero_pad)
{
    if (zero_pad)
        ngpc_text_print_dec(plane, pal, tx, ty, score, digits);
    else
        ngpc_text_print_num(plane, pal, tx, ty, score, digits);
}

/* ── Vies ────────────────────────────────────────────────── */

void ngpc_hud_lives_draw(u8 spr_base, u8 x, u8 y,
                         u8 lives, u8 max_lives,
                         u16 tile, u8 pal, u8 spacing)
{
    u8 i;
    for (i = 0; i < max_lives; i++) {
        if (i < lives) {
            ngpc_sprite_set((u8)(spr_base + i),
                            (u8)(x + i * spacing), y,
                            tile, pal, 0);
        } else {
            ngpc_sprite_hide((u8)(spr_base + i));
        }
    }
}
