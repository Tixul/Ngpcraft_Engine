#ifndef NGPC_PUSHBLOCK_H
#define NGPC_PUSHBLOCK_H

/*
 * ngpc_pushblock -- Blocs poussables style Sokoban (top-down, tile-based)
 * =======================================================================
 * Physique discrète : un bloc se déplace d'exactement 1 tile à la fois.
 * Gère la collision tile (TILE_SOLID), la collision bloc-bloc, et la
 * détection de chute dans un tile "void" (configurable).
 *
 * Usage type :
 *   1. Déclarer un pool : NgpcPushBlock blocks[SCENE_PUSH_BLOCK_COUNT];
 *   2. Init depuis l'export éditeur :
 *        for (u8 i = 0; i < SCENE_PUSH_BLOCK_COUNT; i++)
 *            ngpc_pushblock_init(&blocks[i],
 *                scene_push_block_tiles[i].tx,
 *                scene_push_block_tiles[i].ty);
 *   3. Dans le game loop, après avoir déterminé le déplacement joueur
 *      (pdx, pdy en tiles, ±1 ou 0) :
 *        for (i = 0; i < SCENE_PUSH_BLOCK_COUNT; i++)
 *            ngpc_pushblock_try_push(&blocks[i], blocks,
 *                SCENE_PUSH_BLOCK_COUNT,
 *                player_tx, player_ty, pdx, pdy,
 *                &col, TILE_VOID_TYPE);
 *   4. Condition "bloc sur cible" (pour TRIG_BLOCK_ON_TILE) :
 *        if (ngpc_pushblock_on_region(&blocks[i], rx, ry, rw, rh)) { ... }
 *
 * Dépendances :
 *   ngpc_tilecol/ngpc_tilecol.h
 *
 * Copier ngpc_pushblock/ dans src/
 * OBJS += src/ngpc_pushblock/ngpc_pushblock.rel
 * #include "ngpc_pushblock/ngpc_pushblock.h"
 */

#include "ngpc_hw.h"
#include "../ngpc_tilecol/ngpc_tilecol.h"

/* ── Résultat d'une tentative de poussée ─────────────────────────────── */

#define PUSH_NONE   0   /* bloc non adjacent ou bloqué (mur/autre bloc)  */
#define PUSH_MOVED  1   /* bloc déplacé d'un tile                        */
#define PUSH_VOID   2   /* bloc tombé dans un tile void (désactivé)      */

/* ── Structure (6 octets) ────────────────────────────────────────────── */

typedef struct {
    s16 tx, ty;   /* position tile courante (0,0 = haut-gauche)         */
    u8  active;   /* 1 = présent, 0 = supprimé (chu dans void / retiré) */
    u8  _pad;
} NgpcPushBlock;  /* 6 octets                                           */

/* ── Type tile exporté par l'éditeur ─────────────────────────────────── */

/*
 * NgpcPbTile -- Position initiale d'un bloc (export éditeur).
 * Guard #ifndef pour coexister avec ngpc_vehicle.h si les deux sont inclus.
 */
#ifndef NGPC_PB_TILE_T
#define NGPC_PB_TILE_T
typedef struct { s16 tx; s16 ty; } NgpcPbTile;
#endif

/* ── API ─────────────────────────────────────────────────────────────── */

/*
 * ngpc_pushblock_init -- Initialise le bloc à la position tile (tx, ty).
 */
void ngpc_pushblock_init(NgpcPushBlock *b, s16 tx, s16 ty);

/*
 * ngpc_pushblock_try_push -- Tente de pousser le bloc.
 *
 *   ptx / pty  : position tile du joueur AVANT son déplacement
 *   dx  / dy   : déplacement du joueur (±1 ou 0 — une seule direction à la fois)
 *   others     : pool complet des blocs (collision bloc-bloc ; le bloc lui-même
 *                est ignoré automatiquement)
 *   n_others   : taille du pool
 *   col        : carte de collision (NULL = aucun mur)
 *   void_type  : type de tile dans lequel le bloc "tombe" et est désactivé
 *                (ex : TILE_VOID custom). Passer 0 pour désactiver.
 *
 *   Retourne PUSH_MOVED, PUSH_VOID ou PUSH_NONE.
 */
u8 ngpc_pushblock_try_push(NgpcPushBlock *b,
                            NgpcPushBlock *others, u8 n_others,
                            s16 ptx, s16 pty, s8 dx, s8 dy,
                            const NgpcTileCol *col, u8 void_type);

/*
 * ngpc_pushblock_on_region -- 1 si le bloc actif est dans la région tile
 *   (rx, ry, rw, rh). Utiliser pour implémenter TRIG_BLOCK_ON_TILE.
 *
 *   Exemple :
 *     if (ngpc_pushblock_on_region(&b, region.x, region.y, region.w, region.h))
 *         trigger_fire(TRIG_BLOCK_ON_TILE);
 */
u8 ngpc_pushblock_on_region(const NgpcPushBlock *b,
                             s16 rx, s16 ry, s16 rw, s16 rh);

/*
 * ngpc_pushblock_tile_type -- Type du tile sous le bloc (via ngpc_tilecol_type).
 *   Utile pour détecter TILE_DAMAGE (pressure_plate) ou d'autres surfaces.
 *   Retourne TILE_SOLID si col == NULL ou bloc inactif.
 */
u8 ngpc_pushblock_tile_type(const NgpcPushBlock *b, const NgpcTileCol *col);

/*
 * ngpc_pushblock_pixel -- Position pixel coin haut-gauche du bloc.
 *   Utiliser NGPC_TILE_SIZE (8) comme tile_size dans un projet standard.
 */
void ngpc_pushblock_pixel(const NgpcPushBlock *b, u8 tile_size,
                           s16 *out_px, s16 *out_py);

#endif /* NGPC_PUSHBLOCK_H */
