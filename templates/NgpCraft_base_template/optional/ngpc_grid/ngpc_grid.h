#ifndef NGPC_GRID_H
#define NGPC_GRID_H

/*
 * ngpc_grid -- Logique grille pour jeux puzzle
 * ==============================================
 * Grille de cellules u8 avec accès indexé, conversion coords, et
 * utilitaires pour Sokoban, match-3, taquin, Puyo, etc.
 *
 * La grille est un flat array u8[] fourni par le jeu (en RAM).
 * NgpcGrid ne fait qu'encapsuler l'accès et les conversions.
 *
 * Taille par cellule : 1 octet (valeurs 0-255 définies par le jeu).
 * Taille d'une grille 8×8 : 64 octets.
 *
 * Dépend de : ngpc_hw.h uniquement
 *
 * Usage :
 *   Copier ngpc_grid/ dans src/
 *   #include "ngpc_grid/ngpc_grid.h"   (header-only)
 *
 * Exemple — Sokoban 8×8 :
 *   #define GRID_W  8
 *   #define GRID_H  8
 *   #define CELL_EMPTY   0
 *   #define CELL_WALL    1
 *   #define CELL_BOX     2
 *   #define CELL_GOAL    3
 *
 *   static u8 cells[GRID_W * GRID_H];
 *   static NgpcGrid grid;
 *   ngpc_grid_init(&grid, cells, GRID_W, GRID_H);
 *
 *   // Déplacer un objet (Sokoban) :
 *   u8 *src = ngpc_grid_at(&grid, player_x, player_y);
 *   u8 *dst = ngpc_grid_at(&grid, player_x + dx, player_y + dy);
 *   if (dst && *dst == CELL_EMPTY) {
 *       *dst = *src;
 *       *src = CELL_EMPTY;
 *   }
 *
 *   // Rendu — placer chaque cellule comme sprite ou tile :
 *   u8 x, y;
 *   for (y = 0; y < GRID_H; y++) {
 *       for (x = 0; x < GRID_W; x++) {
 *           u8 sx, sy;
 *           ngpc_grid_to_screen(&grid, x, y, 8, 8, &sx, &sy);
 *           ngpc_sprite_set(SPR_GRID + y * GRID_W + x, sx, sy,
 *                           tile_for_cell[ngpc_grid_get(&grid, x, y)], 0, 0);
 *       }
 *   }
 *
 * Exemple — match-3 (détecter un alignement horizontal) :
 *   u8 count = ngpc_grid_count_h(&grid, x, y, CELL_RED);
 *   if (count >= 3) { clear_match(); }
 */

#include "ngpc_hw.h"

/* ── Struct (4 octets) ───────────────────────────────────── */
typedef struct {
    u8 *cells;  /* flat array [ty * w + tx] = valeur de la cellule */
    u8  w;      /* largeur en cellules */
    u8  h;      /* hauteur en cellules */
    u8  pad;    /* alignement */
} NgpcGrid;

/* ── Init ─────────────────────────────────────────────────── */

/* Initialise une grille sur un buffer existant. */
static void ngpc_grid_init(NgpcGrid *g, u8 *cells, u8 w, u8 h) {
    g->cells = cells;
    g->w     = w;
    g->h     = h;
    g->pad   = 0;
}

/* Remplit toutes les cellules avec une valeur. */
static void ngpc_grid_fill(NgpcGrid *g, u8 value) {
    u8 i;
    u16 n = (u16)g->w * g->h;
    for (i = 0; i < (u8)n; i++) g->cells[i] = value;
    /* Note : si w*h > 255, boucler sur u16. Grilles jusqu'à 16×16 (256 cellules) OK. */
}

/* ── Accès cellules ───────────────────────────────────────── */

/* 1 si (tx, ty) est dans les bornes. */
static u8 ngpc_grid_in_bounds(const NgpcGrid *g, s8 tx, s8 ty) {
    return (tx >= 0 && ty >= 0 && (u8)tx < g->w && (u8)ty < g->h);
}

/* Valeur de la cellule (sans vérification de bornes). */
static u8 ngpc_grid_get(const NgpcGrid *g, u8 tx, u8 ty) {
    return g->cells[(u16)ty * g->w + tx];
}

/* Modifie la cellule (sans vérification de bornes). */
static void ngpc_grid_set(NgpcGrid *g, u8 tx, u8 ty, u8 value) {
    g->cells[(u16)ty * g->w + tx] = value;
}

/* Pointeur vers la cellule (NULL si hors bornes). */
static u8 *ngpc_grid_at(NgpcGrid *g, s8 tx, s8 ty) {
    if (!ngpc_grid_in_bounds(g, tx, ty)) return 0;
    return &g->cells[(u16)(u8)ty * g->w + (u8)tx];
}

/* Valeur avec bornes sécurisées (retourne 'out_val' si hors grille). */
static u8 ngpc_grid_get_safe(const NgpcGrid *g, s8 tx, s8 ty, u8 out_val) {
    if (!ngpc_grid_in_bounds(g, tx, ty)) return out_val;
    return g->cells[(u16)(u8)ty * g->w + (u8)tx];
}

/* Échange deux cellules. */
static void ngpc_grid_swap(NgpcGrid *g, u8 ax, u8 ay, u8 bx, u8 by) {
    u8 tmp = ngpc_grid_get(g, ax, ay);
    ngpc_grid_set(g, ax, ay, ngpc_grid_get(g, bx, by));
    ngpc_grid_set(g, bx, by, tmp);
}

/* ── Conversions coords ───────────────────────────────────── */

/*
 * Tile (tx, ty) → position pixel écran (sx, sy).
 * origin_x/y : position pixel du coin haut-gauche de la grille.
 * cell_w/h   : taille d'une cellule en pixels.
 */
static void ngpc_grid_to_screen(const NgpcGrid *g,
                                 u8 tx, u8 ty,
                                 u8 origin_x, u8 origin_y,
                                 u8 cell_w,   u8 cell_h,
                                 u8 *sx,      u8 *sy)
{
    (void)g;
    *sx = (u8)(origin_x + tx * cell_w);
    *sy = (u8)(origin_y + ty * cell_h);
}

/*
 * Position pixel → tile (tx, ty).
 * Retourne 1 si dans les bornes, 0 sinon.
 * Utile pour le clic ou le curseur D-pad en pixels.
 */
static u8 ngpc_grid_from_screen(const NgpcGrid *g,
                                 u8 px, u8 py,
                                 u8 origin_x, u8 origin_y,
                                 u8 cell_w,   u8 cell_h,
                                 u8 *tx,      u8 *ty)
{
    if (px < origin_x || py < origin_y) return 0;
    *tx = (u8)((px - origin_x) / cell_w);
    *ty = (u8)((py - origin_y) / cell_h);
    return (*tx < g->w && *ty < g->h);
}

/* ── Comptage (match-3, détection) ───────────────────────── */

/*
 * Compte les cellules consécutives de valeur 'value' depuis (tx, ty)
 * vers la droite (horizontal).
 */
static u8 ngpc_grid_count_h(const NgpcGrid *g, u8 tx, u8 ty, u8 value) {
    u8 n = 0, x = tx;
    while (x < g->w && ngpc_grid_get(g, x, ty) == value) { n++; x++; }
    return n;
}

/*
 * Compte les cellules consécutives de valeur 'value' depuis (tx, ty)
 * vers le bas (vertical).
 */
static u8 ngpc_grid_count_v(const NgpcGrid *g, u8 tx, u8 ty, u8 value) {
    u8 n = 0, y = ty;
    while (y < g->h && ngpc_grid_get(g, tx, y) == value) { n++; y++; }
    return n;
}

/*
 * Cherche la première cellule de valeur 'value' dans la grille.
 * Retourne 1 et remplit *tx/*ty si trouvée, 0 sinon.
 */
static u8 ngpc_grid_find(const NgpcGrid *g, u8 value, u8 *tx, u8 *ty) {
    u8 x, y;
    for (y = 0; y < g->h; y++) {
        for (x = 0; x < g->w; x++) {
            if (ngpc_grid_get(g, x, y) == value) {
                *tx = x; *ty = y;
                return 1;
            }
        }
    }
    return 0;
}

/* Nombre de cellules d'une valeur donnée dans toute la grille. */
static u8 ngpc_grid_count(const NgpcGrid *g, u8 value) {
    u8 x, y, n = 0;
    for (y = 0; y < g->h; y++)
        for (x = 0; x < g->w; x++)
            if (ngpc_grid_get(g, x, y) == value) n++;
    return n;
}

#endif /* NGPC_GRID_H */
