#include "ngpc_pushblock.h"

void ngpc_pushblock_init(NgpcPushBlock *b, s16 tx, s16 ty)
{
    b->tx     = tx;
    b->ty     = ty;
    b->active = 1;
    b->_pad   = 0;
}

u8 ngpc_pushblock_try_push(NgpcPushBlock *b,
                            NgpcPushBlock *others, u8 n_others,
                            s16 ptx, s16 pty, s8 dx, s8 dy,
                            const NgpcTileCol *col, u8 void_type)
{
    s16 ntx, nty;
    u8  i, tile;

    if (!b->active)  return PUSH_NONE;
    if (!dx && !dy)  return PUSH_NONE;

    /* Le joueur doit se déplacer vers la case du bloc */
    if ((s16)(ptx + (s16)dx) != b->tx || (s16)(pty + (s16)dy) != b->ty)
        return PUSH_NONE;

    ntx = (s16)(b->tx + (s16)dx);
    nty = (s16)(b->ty + (s16)dy);

    /* Tile solide à destination */
    if (col && ngpc_tilecol_is_solid(col, ntx, nty))
        return PUSH_NONE;

    /* Collision bloc-bloc à destination */
    for (i = 0; i < n_others; ++i) {
        if (!others[i].active)   continue;
        if (&others[i] == b)     continue;
        if (others[i].tx == ntx && others[i].ty == nty)
            return PUSH_NONE;
    }

    /* Déplacer le bloc */
    b->tx = ntx;
    b->ty = nty;

    /* Chute dans un tile void ? */
    if (void_type && col) {
        tile = ngpc_tilecol_type(col, ntx, nty);
        if (tile == void_type) {
            b->active = 0;
            return PUSH_VOID;
        }
    }

    return PUSH_MOVED;
}

u8 ngpc_pushblock_on_region(const NgpcPushBlock *b,
                             s16 rx, s16 ry, s16 rw, s16 rh)
{
    if (!b->active) return 0;
    return (u8)(b->tx >= rx && b->tx < (s16)(rx + rw) &&
                b->ty >= ry && b->ty < (s16)(ry + rh));
}

u8 ngpc_pushblock_tile_type(const NgpcPushBlock *b, const NgpcTileCol *col)
{
    if (!b->active || !col) return (u8)TILE_SOLID;
    return ngpc_tilecol_type(col, b->tx, b->ty);
}

void ngpc_pushblock_pixel(const NgpcPushBlock *b, u8 tile_size,
                           s16 *out_px, s16 *out_py)
{
    *out_px = (s16)(b->tx * (s16)tile_size);
    *out_py = (s16)(b->ty * (s16)tile_size);
}
