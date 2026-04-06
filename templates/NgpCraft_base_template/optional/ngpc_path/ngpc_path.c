#include "ngpc_path.h"

/*
 * BFS de la CIBLE vers la SOURCE (flood-fill depuis la cible).
 * Remplit dist[] : dist[y*map_w+x] = distance depuis la cible (0 = cible).
 * 0xFF = non-visité ou solide.
 *
 * Avantage : avec dist[], on peut trouver le premier pas depuis n'importe
 * quelle source sans refaire le BFS.
 */

#define _DIST_INF  0xFF
#define _QUEUE_CAP 64

/* Encode une position (x, y) en 1 octet : (y << 4) | x (x,y < 16) */
#define _ENC(x, y)   ((u8)(((u8)(y) << 4) | (u8)(x)))
#define _DEC_X(v)    ((u8)((v) & 0x0F))
#define _DEC_Y(v)    ((u8)((v) >> 4))

/* Directions 4-connexité */
static const s8 _dx[4] = { 0,  0, -1, 1 };
static const s8 _dy[4] = {-1,  1,  0, 0 };

/*
 * Effectue le BFS depuis (tx, ty).
 * Remplit dist_buf[256] avec les distances (0xFF si non-atteint).
 */
static void _bfs(const u8 *map, u8 map_w, u8 map_h,
                 u8 tx, u8 ty,
                 u8 *dist_buf)
{
    /* File circulaire */
    u8 queue[_QUEUE_CAP];
    u8 qhead = 0, qtail = 0, qsize = 0;
    u8 i;
    u16 n = (u16)map_w * map_h;

    /* Init : tout à infini */
    for (i = 0; i < (u8)n; i++) dist_buf[i] = _DIST_INF;

    /* Cible = distance 0 */
    if (tx >= map_w || ty >= map_h) return;
    if (map[(u16)ty * map_w + tx] != 0) return; /* cible solide */

    dist_buf[(u16)ty * map_w + tx] = 0;
    queue[qtail] = _ENC(tx, ty);
    qtail = (u8)((qtail + 1) & (_QUEUE_CAP - 1));
    qsize = 1;

    while (qsize > 0) {
        u8 cur = queue[qhead];
        u8 cx  = _DEC_X(cur);
        u8 cy  = _DEC_Y(cur);
        u8 cd  = dist_buf[(u16)cy * map_w + cx];

        qhead = (u8)((qhead + 1) & (_QUEUE_CAP - 1));
        qsize--;

        /* Limite de distance (queue pleine si on va trop loin) */
        if (cd == (u8)(_QUEUE_CAP - 2)) continue;

        for (i = 0; i < 4; i++) {
            s8 nx = (s8)((s8)cx + _dx[i]);
            s8 ny = (s8)((s8)cy + _dy[i]);
            u16 idx;

            if (nx < 0 || ny < 0 || (u8)nx >= map_w || (u8)ny >= map_h) continue;
            idx = (u16)(u8)ny * map_w + (u8)nx;

            if (map[idx] != 0) continue;             /* solide */
            if (dist_buf[idx] != _DIST_INF) continue; /* déjà visité */
            if (qsize >= _QUEUE_CAP) continue;        /* queue pleine */

            dist_buf[idx] = (u8)(cd + 1);
            queue[qtail]  = _ENC((u8)nx, (u8)ny);
            qtail  = (u8)((qtail + 1) & (_QUEUE_CAP - 1));
            qsize++;
        }
    }
}

u8 ngpc_path_step(const u8 *map, u8 map_w, u8 map_h,
                  u8 sx, u8 sy, u8 tx, u8 ty,
                  s8 *out_dx, s8 *out_dy)
{
    /* Buffers statiques — pas de stack overflow sur NGPC (pas de RTOS) */
    static u8 dist[PATH_MAX_W * PATH_MAX_H];

    u8 i, best_dir;
    u8 best_dist;

    *out_dx = 0;
    *out_dy = 0;

    if (sx == tx && sy == ty) return 0;  /* déjà arrivé */

    /* BFS depuis la cible */
    _bfs(map, map_w, map_h, tx, ty, dist);

    /* Source inatteignable ? */
    if (dist[(u16)sy * map_w + sx] == _DIST_INF) return 0;

    /* Choisir le voisin de (sx, sy) avec la distance minimale */
    best_dir  = 4;
    best_dist = _DIST_INF;

    for (i = 0; i < 4; i++) {
        s8 nx = (s8)((s8)sx + _dx[i]);
        s8 ny = (s8)((s8)sy + _dy[i]);
        u16 idx;
        u8  nd;

        if (nx < 0 || ny < 0 || (u8)nx >= map_w || (u8)ny >= map_h) continue;
        idx = (u16)(u8)ny * map_w + (u8)nx;
        if (map[idx] != 0) continue;   /* solide */

        nd = dist[idx];
        if (nd < best_dist) {
            best_dist = nd;
            best_dir  = i;
        }
    }

    if (best_dir == 4) return 0;  /* aucun voisin accessible */

    *out_dx = _dx[best_dir];
    *out_dy = _dy[best_dir];
    return 1;
}

u8 ngpc_path_dist(const u8 *map, u8 map_w, u8 map_h,
                  u8 sx, u8 sy, u8 tx, u8 ty)
{
    static u8 dist[PATH_MAX_W * PATH_MAX_H];

    if (sx == tx && sy == ty) return 0;

    _bfs(map, map_w, map_h, tx, ty, dist);

    return dist[(u16)sy * map_w + sx];
}
