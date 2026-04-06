#include "ngpc_aabb.h"

/* ── Helpers internes ─────────────────────────────── */

static s16 s16_abs(s16 v) { return v < 0 ? -v : v; }
static s16 s16_min(s16 a, s16 b) { return a < b ? a : b; }
static s16 s16_max(s16 a, s16 b) { return a > b ? a : b; }

/* ── Fonctions de base ────────────────────────────── */

u8 ngpc_rect_overlap(const NgpcRect *a, const NgpcRect *b)
{
    return !(a->x + (s16)a->w <= b->x ||
             b->x + (s16)b->w <= a->x ||
             a->y + (s16)a->h <= b->y ||
             b->y + (s16)b->h <= a->y);
}

u8 ngpc_rect_contains(const NgpcRect *r, s16 px, s16 py)
{
    return px >= r->x && px < r->x + (s16)r->w &&
           py >= r->y && py < r->y + (s16)r->h;
}

void ngpc_rect_intersect(const NgpcRect *a, const NgpcRect *b, NgpcRect *out)
{
    s16 x1 = s16_max(a->x, b->x);
    s16 y1 = s16_max(a->y, b->y);
    s16 x2 = s16_min(RECT_RIGHT(a),  RECT_RIGHT(b));
    s16 y2 = s16_min(RECT_BOTTOM(a), RECT_BOTTOM(b));
    if (x2 > x1 && y2 > y1) {
        out->x = x1; out->y = y1;
        out->w = (u8)(x2 - x1);
        out->h = (u8)(y2 - y1);
    } else {
        out->x = out->y = 0;
        out->w = out->h = 0;
    }
}

void ngpc_rect_offset(NgpcRect *r, s16 dx, s16 dy)
{
    r->x += dx;
    r->y += dy;
}

/* ── Détection de côté + push ─────────────────────── */

u8 ngpc_rect_test(const NgpcRect *a, const NgpcRect *b, NgpcCollResult *out)
{
    /* Pénétrations sur chaque axe */
    s16 pen_left  = RECT_RIGHT(b)  - a->x;          /* B droit  - A gauche */
    s16 pen_right = RECT_RIGHT(a)  - b->x;          /* A droit  - B gauche */
    s16 pen_top   = RECT_BOTTOM(b) - a->y;          /* B bas    - A haut   */
    s16 pen_bot   = RECT_BOTTOM(a) - b->y;          /* A bas    - B haut   */

    /* Pas d'overlap si une pénétration est <= 0 */
    if (pen_left <= 0 || pen_right <= 0 ||
        pen_top  <= 0 || pen_bot   <= 0)
        return 0;

    /* MTV : axe à pénétration minimale */
    s16 min_x = s16_min(pen_left, pen_right);
    s16 min_y = s16_min(pen_top,  pen_bot);

    if (out) {
        /* TOUS les côtés géométriquement touchés (peut être 2 bits) */
        out->sides = COL_NONE;
        if (pen_left  < pen_right)  out->sides |= COL_LEFT;
        if (pen_right <= pen_left)  out->sides |= COL_RIGHT;
        if (pen_top   < pen_bot)    out->sides |= COL_TOP;
        if (pen_bot   <= pen_top)   out->sides |= COL_BOTTOM;

        /* Push MTV : résoudre sur l'axe à pénétration minimale.
         * push_x et push_y sont mutuellement exclusifs (un seul != 0). */
        if (min_x <= min_y) {
            out->push_x = (pen_left < pen_right) ? pen_left : -pen_right;
            out->push_y = 0;
        } else {
            out->push_x = 0;
            out->push_y = (pen_top < pen_bot) ? pen_top : -pen_bot;
        }
    }
    return 1;
}

u8 ngpc_rect_test_many(const NgpcRect *moving,
                        const NgpcRect *statics, u8 count,
                        s16 *rx, s16 *ry,
                        u8 *sides_out)
{
    NgpcRect tmp;
    NgpcCollResult cr;
    u8 hits = 0;
    u8 sides = COL_NONE;
    u8 i;

    tmp = *moving;
    tmp.x = *rx;
    tmp.y = *ry;

    for (i = 0; i < count; i++) {
        if (ngpc_rect_test(&tmp, &statics[i], &cr)) {
            tmp.x += cr.push_x;
            tmp.y += cr.push_y;
            sides |= cr.sides;
            hits++;
        }
    }

    *rx = tmp.x;
    *ry = tmp.y;
    if (sides_out) *sides_out = sides;
    return hits;
}

/* ── Swept AABB ───────────────────────────────────── */
/*
 * Algorithme : Minkowski sum + ray cast
 * On expande B par les dimensions de A, puis on teste un rayon
 * depuis le centre de A dans la direction (vx, vy).
 *
 * En pratique pour le NGPC on travaille sur les bords, pas les centres,
 * avec de l'arithmétique fixe-point.
 *
 * Contrainte de validité : |vx| < NGPC_TILE_SIZE * FX_ONE (typ. < 8px/frame)
 */
void ngpc_swept_aabb(const NgpcRect *a, fx16 vx, fx16 vy,
                     const NgpcRect *b,
                     NgpcSweptResult *result)
{
    /* Expandre B par les demi-dimensions de A (Minkowski sum) */
    s16 bx = b->x - (s16)a->w;
    s16 by = b->y - (s16)a->h;
    s16 bw = (s16)b->w + (s16)a->w;
    s16 bh = (s16)b->h + (s16)a->h;

    /* Origine du rayon = coin haut-gauche de A */
    s16 ox = a->x;
    s16 oy = a->y;

    /* Temps d'entrée et de sortie sur chaque axe, en fx16 */
    fx16 tx_entry, tx_exit, ty_entry, ty_exit;
    fx16 t_entry, t_exit;

    result->hit = 0;
    result->t   = FX_ONE + FX_ONE;  /* > FX_ONE = pas de hit */
    result->nx  = 0;
    result->ny  = 0;

    /* Axe X */
    if (vx == 0) {
        /* Pas de mouvement horizontal : vérifier si déjà en overlap X */
        if (ox < bx || ox >= bx + bw) return;
        tx_entry = FX_MINVAL;
        tx_exit  = FX_MAXVAL;
    } else if (vx > 0) {
        tx_entry = FX_DIV(INT_TO_FX(bx - ox),      vx);
        tx_exit  = FX_DIV(INT_TO_FX(bx + bw - ox), vx);
    } else {
        tx_entry = FX_DIV(INT_TO_FX(bx + bw - ox), vx);
        tx_exit  = FX_DIV(INT_TO_FX(bx - ox),      vx);
    }

    /* Axe Y */
    if (vy == 0) {
        if (oy < by || oy >= by + bh) return;
        ty_entry = FX_MINVAL;
        ty_exit  = FX_MAXVAL;
    } else if (vy > 0) {
        ty_entry = FX_DIV(INT_TO_FX(by - oy),      vy);
        ty_exit  = FX_DIV(INT_TO_FX(by + bh - oy), vy);
    } else {
        ty_entry = FX_DIV(INT_TO_FX(by + bh - oy), vy);
        ty_exit  = FX_DIV(INT_TO_FX(by - oy),      vy);
    }

    /* Intersection des intervalles */
    t_entry = (tx_entry > ty_entry) ? tx_entry : ty_entry;
    t_exit  = (tx_exit  < ty_exit)  ? tx_exit  : ty_exit;

    /* Pas de collision si t_entry > t_exit, ou hit dans le passé/futur lointain */
    if (t_entry > t_exit || t_entry >= FX_ONE || t_exit <= 0)
        return;

    result->hit = 1;
    result->t   = t_entry < 0 ? 0 : t_entry;

    /* Normale : axe qui a eu le t_entry le plus tardif */
    if (tx_entry > ty_entry) {
        result->nx = (vx > 0) ? -1 : 1;
        result->ny = 0;
    } else {
        result->nx = 0;
        result->ny = (vy > 0) ? -1 : 1;
    }
}

/* ── Push axe unique ──────────────────────────────── */

s16 ngpc_rect_push_x(const NgpcRect *a, const NgpcRect *b)
{
    s16 push_right = RECT_RIGHT(b) - a->x;
    s16 push_left  = b->x - RECT_RIGHT(a);
    return (s16_abs(push_right) < s16_abs(push_left)) ? push_right : push_left;
}

s16 ngpc_rect_push_y(const NgpcRect *a, const NgpcRect *b)
{
    s16 push_down = RECT_BOTTOM(b) - a->y;
    s16 push_up   = b->y - RECT_BOTTOM(a);
    return (s16_abs(push_down) < s16_abs(push_up)) ? push_down : push_up;
}
