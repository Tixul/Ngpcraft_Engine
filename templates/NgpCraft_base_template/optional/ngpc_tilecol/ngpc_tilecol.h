#ifndef NGPC_TILECOL_H
#define NGPC_TILECOL_H

/*
 * ngpc_tilecol -- Collision avec une tilemap typée
 * =================================================
 * Chaque tile de la map a un TYPE (u8) qui définit son comportement.
 * Supporte les tiles solides, les plateformes traversables, les zones
 * de dommage, et les échelles.
 *
 * Dépend de : ngpc_aabb.h (COL_* flags, NgpcRect)
 *
 * Coût RAM de la map : map_w × map_h octets
 *   20×19 tiles = 380 octets   (un écran)
 *   32×32 tiles = 1024 octets  (attention au budget 12 KB)
 *
 * Usage:
 *   Copier ngpc_tilecol/ dans src/
 *   OBJS += src/ngpc_tilecol/ngpc_tilecol.rel
 *   #include "ngpc_tilecol/ngpc_tilecol.h"
 */

#include "ngpc_hw.h"
#include "../ngpc_aabb/ngpc_aabb.h"  /* COL_*, NgpcRect */

/* ══════════════════════════════════════════════════════
 * TYPES DE TILES
 * ══════════════════════════════════════════════════════
 *
 * Mettre dans ta map de collision (u8 par tile) :
 *   0 = TILE_PASS    : passable, aucune collision
 *   1 = TILE_SOLID   : solide sur tous les côtés
 *   2 = TILE_ONE_WAY : plateforme traversable — solide seulement par le haut
 *                      (saut à travers possible, atterrissage sur le dessus)
 *   3 = TILE_DAMAGE  : passable mais signal de dommage (retourné dans result)
 *   4 = TILE_LADDER  : zone d'échelle (passable, mais signal d'escalade)
 *   5-15 : libres pour usage projet (vérifier avec ngpc_tilecol_type_at())
 */
#define TILE_PASS       0
#define TILE_SOLID      1
#define TILE_ONE_WAY    2
#define TILE_DAMAGE     3
#define TILE_LADDER     4

#define NGPC_TILE_SIZE  8   /* tiles NGPC = 8×8 pixels */

/* ══════════════════════════════════════════════════════
 * STRUCTURES
 * ══════════════════════════════════════════════════════ */

/* Descripteur de map de collision */
typedef struct {
    const u8 *map;   /* flat array [ty * map_w + tx] = type du tile */
    u8  map_w;       /* largeur en tiles */
    u8  map_h;       /* hauteur en tiles */
} NgpcTileCol;

/*
 * Résultat d'un appel à ngpc_tilecol_move()
 *
 * sides    : COL_* flags — quels bords de la hitbox ont touché un tile solide
 * tile_x   : type du tile qui a causé la collision horizontale (0 si aucune)
 * tile_y   : type du tile qui a causé la collision verticale (0 si aucune)
 * in_ladder: 1 si le rect est à l'intérieur d'une zone TILE_LADDER
 * in_damage: 1 si le rect touche un tile TILE_DAMAGE
 *
 * Usage typique après ngpc_tilecol_move() :
 *   if (res.sides & COL_BOTTOM) on_ground = 1;  // atterri
 *   if (res.sides & COL_TOP)    vel_y = 0;      // tête dans plafond
 *   if (res.sides & COL_LEFT || res.sides & COL_RIGHT) vel_x = 0;
 *   if (res.in_damage) player_take_hit();
 *   if (res.in_ladder) can_climb = 1;
 */
typedef struct {
    u8  sides;      /* COL_* combinés */
    u8  tile_x;     /* type tile collision horizontale */
    u8  tile_y;     /* type tile collision verticale   */
    u8  in_ladder;  /* 1 si dans zone échelle          */
    u8  in_damage;  /* 1 si dans zone dommage          */
} NgpcMoveResult;

/* ══════════════════════════════════════════════════════
 * LECTURE DE MAP
 * ══════════════════════════════════════════════════════ */

/* Type du tile à (tx, ty). Retourne TILE_SOLID si hors bornes. */
u8 ngpc_tilecol_type(const NgpcTileCol *col, s16 tx, s16 ty);

/* Type du tile à la position pixel (wx, wy). Retourne TILE_SOLID si hors bornes. */
u8 ngpc_tilecol_type_at(const NgpcTileCol *col, s16 wx, s16 wy);

/* 1 si le tile à (tx, ty) bloque le mouvement (TILE_SOLID uniquement) */
u8 ngpc_tilecol_is_solid(const NgpcTileCol *col, s16 tx, s16 ty);

/* ══════════════════════════════════════════════════════
 * TESTS DE ZONE
 * ══════════════════════════════════════════════════════ */

/* 1 si un tile SOLID quelconque est dans la zone rect (wx,wy,rw,rh) */
u8 ngpc_tilecol_rect_solid(const NgpcTileCol *col,
                            s16 wx, s16 wy, u8 rw, u8 rh);

/* 1 si un tile SOLID ou ONE_WAY est dans la zone rect.
 * Pour ONE_WAY : ne compte que si prev_bottom < haut du tile (atterrissage par le haut).
 * prev_bottom = ry + rh - 1 AVANT le mouvement vertical. */
u8 ngpc_tilecol_rect_ground(const NgpcTileCol *col,
                             s16 wx, s16 wy, u8 rw, u8 rh,
                             s16 prev_bottom);

/* ══════════════════════════════════════════════════════
 * DÉTECTIONS DIRECTIONNELLES
 * ══════════════════════════════════════════════════════ */

/* 1 si le rect a un tile solide directement en-dessous (à ry + rh) */
u8 ngpc_tilecol_on_ground(const NgpcTileCol *col,
                           s16 rx, s16 ry, u8 rw, u8 rh);

/* 1 si le rect a un tile solide directement au-dessus (à ry - 1) */
u8 ngpc_tilecol_on_ceiling(const NgpcTileCol *col,
                            s16 rx, s16 ry, u8 rw, u8 rh);

/* 1 si le rect a un tile solide directement à gauche (à rx - 1) */
u8 ngpc_tilecol_on_wall_left(const NgpcTileCol *col,
                              s16 rx, s16 ry, u8 rw, u8 rh);

/* 1 si le rect a un tile solide directement à droite (à rx + rw) */
u8 ngpc_tilecol_on_wall_right(const NgpcTileCol *col,
                               s16 rx, s16 ry, u8 rw, u8 rh);

/* Distance en pixels jusqu'au sol (tile solide ou one-way) depuis les pieds.
 * Retourne max_dist si rien trouvé dans la plage. 0 = déjà posé. */
s16 ngpc_tilecol_ground_dist(const NgpcTileCol *col,
                              s16 rx, s16 ry, u8 rw, u8 rh,
                              u8 max_dist);

/* ══════════════════════════════════════════════════════
 * MOUVEMENT + RÉSOLUTION (fonction principale)
 * ══════════════════════════════════════════════════════
 *
 * Déplace le rect de (*rx, *ry, rw, rh) par (dx, dy) pixels,
 * résout les collisions contre la tilemap, met à jour *rx/*ry,
 * et remplit *result.
 *
 * Algorithme : axe X d'abord, puis axe Y.
 * Résolution par recul pixel-par-pixel → correct et simple.
 *
 * CONTRAINTE : |dx| et |dy| ≤ NGPC_TILE_SIZE (8 pixels) par frame.
 * Au-delà, des tiles peuvent être "traversés". Vitesse max recommandée :
 * 4-6 px/frame (= FX_LIT(4..6) en fx16, soit INT_TO_FX puis FX_TO_INT).
 *
 * Exemple platformer complet :
 *
 *   // Chaque frame :
 *   vel_y = FX_ADD(vel_y, GRAVITY);                    // gravité
 *   vel_y = FX_MIN(vel_y, MAX_FALL);                   // clamp chute
 *
 *   s16 dx = FX_TO_INT(vel_x);                         // pixels entiers
 *   s16 dy = FX_TO_INT(vel_y);
 *
 *   NgpcMoveResult res;
 *   ngpc_tilecol_move(&map, &px, &py, PW, PH, dx, dy, &res);
 *
 *   if (res.sides & COL_BOTTOM) { on_ground = 1; vel_y = 0; }
 *   if (res.sides & COL_TOP)    { vel_y = 0; }  // plafond
 *   if (res.sides & (COL_LEFT|COL_RIGHT)) { vel_x = 0; }
 *   if (res.in_damage) { player_hurt(); }
 */
void ngpc_tilecol_move(const NgpcTileCol *col,
                       s16 *rx, s16 *ry, u8 rw, u8 rh,
                       s16 dx, s16 dy,
                       NgpcMoveResult *result);

#endif /* NGPC_TILECOL_H */
