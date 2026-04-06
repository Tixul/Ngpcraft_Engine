#ifndef NGPC_PROCGEN_ROOMS_H
#define NGPC_PROCGEN_ROOMS_H

/*
 * ngpc_procgen_rooms -- Pool de templates de rooms + utilitaires de rendu
 * =======================================================================
 * Ce fichier fournit un pool de templates PRÊTS À L'EMPLOI couvrant toutes
 * les combinaisons de sorties N/S/W/E, avec plusieurs VARIANTES graphiques
 * pour chaque configuration (plus de variété dans le donjon).
 *
 * 3 variantes par configuration d'exits (0..2) :
 *   Variante 0 — "plain"    : room vide, juste murs + sol + portes.
 *   Variante 1 — "pillars"  : 4 piliers symétriques à l'intérieur.
 *   Variante 2 — "divided"  : mur intérieur partiel (couloir dans la room).
 *
 * Pool total : 3 × 16 = 48 templates dans g_procgen_rooms[].
 *
 * ---------------------------------------------------------------------------
 * COMMENT AJOUTER TES PROPRES VARIANTES :
 *   1. Ajoute des entrées dans g_procgen_rooms[] avec variant > 2.
 *   2. Dans ngpc_procgen_fill_room(), ajoute un case pour ton variant.
 *   3. Utilise ngpc_procgen_generate() ou generate_ex() avec ton pool.
 *   4. Ajuste PROCGEN_ROOMS_COUNT à ton nouveau total.
 *
 * ---------------------------------------------------------------------------
 * Installation (mode single-header) :
 *
 *   Dans TOUS les .c qui lisent g_procgen_rooms :
 *     #include "ngpc_procgen/ngpc_procgen_rooms.h"
 *
 *   Dans EXACTEMENT UN .c de ton projet (ex: game.c) :
 *     #define PROCGEN_ROOMS_IMPL
 *     #include "ngpc_procgen/ngpc_procgen_rooms.h"
 *
 * Usage minimal :
 *   ngpc_procgen_generate_ex(&donjon, g_procgen_rooms,
 *                            PROCGEN_ROOMS_COUNT, seed, 20);
 *   // Dans le callback :
 *   ngpc_procgen_fill_room(cell, tpl, TILE_WALL, TILE_FLOOR, TILE_PILLAR, 0);
 * ---------------------------------------------------------------------------
 */

#include "ngpc_procgen/ngpc_procgen.h"

/* ── Taille du pool ─────────────────────────────────────────────────────── */

/* 16 configs × 3 variantes = 48 templates.
 * Tu peux ajouter tes propres entrées et augmenter ce compteur. */
#define PROCGEN_ROOMS_COUNT  48u

/* ── Indices de variante ────────────────────────────────────────────────── */

#define ROOM_VAR_PLAIN    0u  /* room vide, sol dégagé */
#define ROOM_VAR_PILLARS  1u  /* 4 piliers symétriques */
#define ROOM_VAR_DIVIDED  2u  /* mur central partiel */

/* ── Déclaration du pool ────────────────────────────────────────────────── */

extern const NgpcRoomTemplate NGP_FAR g_procgen_rooms[PROCGEN_ROOMS_COUNT];

/* ── Prototypes des fonctions de rendu ──────────────────────────────────── */

/*
 * Dessine une room prototype selon la variante de son template.
 * Gère ROOM_VAR_PLAIN, ROOM_VAR_PILLARS et ROOM_VAR_DIVIDED.
 *
 *   cell       : cellule de la room (pour exits et room_type)
 *   tpl        : template sélectionné (pour variant)
 *   tile_wall  : tile NGPC pour les murs
 *   tile_floor : tile NGPC pour le sol
 *   tile_deco  : tile NGPC pour les décorations (piliers, pilier)
 *   pal        : palette BG (0..1)
 */
void ngpc_procgen_fill_room(
    const ProcgenCell           *cell,
    const NgpcRoomTemplate NGP_FAR *tpl,
    u16                          tile_wall,
    u16                          tile_floor,
    u16                          tile_deco,
    u8                           pal
);

/*
 * Version simplifiée sans variante (rétrocompatibilité).
 * Identique à ngpc_procgen_fill_room() avec tile_deco=tile_wall, variant=0.
 */
void ngpc_procgen_fill_simple(
    const ProcgenCell *cell,
    u16                tile_wall,
    u16                tile_floor,
    u8                 pal
);

/* =========================================================================
 * IMPLÉMENTATION — activer dans UN seul .c avec #define PROCGEN_ROOMS_IMPL
 * ========================================================================= */

#ifdef PROCGEN_ROOMS_IMPL

#ifndef GFX_SCR1
#define GFX_SCR1  0u
#endif
extern void ngpc_gfx_fill_rect(u8 scr, u8 x, u8 y, u8 w, u8 h,
                                u16 tile, u8 pal);
extern void ngpc_gfx_put_tile(u8 scr, u8 x, u8 y, u16 tile, u8 pal);

/* ──────────────────────────────────────────────────────────────────────────
 * Pool de templates — 3 variantes × 16 configs = 48 entrées.
 *
 * Principe d'indexation :
 *   entries[config * 3 + variant] → template pour (exits=config, variant=v).
 *
 * ngpc_procgen_pick_template() sélectionne aléatoirement parmi les entrées
 * dont exits_mask est compatible avec les exits requis de la cellule.
 * Le pool étendu garantit plusieurs choix possibles → variété visuelle.
 * ──────────────────────────────────────────────────────────────────────────
 */
const NgpcRoomTemplate NGP_FAR g_procgen_rooms[PROCGEN_ROOMS_COUNT] = {
    /* ------------------------------------------------------------------ */
    /* config 0x00 — aucune sortie (dead end ou erreur, fallback)         */
    /* ------------------------------------------------------------------ */
    { 0x00u, ROOM_VAR_PLAIN   },   /*  0 */
    { 0x00u, ROOM_VAR_PILLARS },   /*  1 */
    { 0x00u, ROOM_VAR_DIVIDED },   /*  2 */

    /* ------------------------------------------------------------------ */
    /* config 0x01 — Nord seulement                                        */
    /* ------------------------------------------------------------------ */
    { PROCGEN_EXIT_N, ROOM_VAR_PLAIN   },   /*  3 */
    { PROCGEN_EXIT_N, ROOM_VAR_PILLARS },   /*  4 */
    { PROCGEN_EXIT_N, ROOM_VAR_DIVIDED },   /*  5 */

    /* ------------------------------------------------------------------ */
    /* config 0x02 — Sud seulement                                         */
    /* ------------------------------------------------------------------ */
    { PROCGEN_EXIT_S, ROOM_VAR_PLAIN   },   /*  6 */
    { PROCGEN_EXIT_S, ROOM_VAR_PILLARS },   /*  7 */
    { PROCGEN_EXIT_S, ROOM_VAR_DIVIDED },   /*  8 */

    /* ------------------------------------------------------------------ */
    /* config 0x03 — Nord+Sud (couloir vertical)                           */
    /* ------------------------------------------------------------------ */
    { PROCGEN_EXIT_N | PROCGEN_EXIT_S, ROOM_VAR_PLAIN   },   /*  9 */
    { PROCGEN_EXIT_N | PROCGEN_EXIT_S, ROOM_VAR_PILLARS },   /* 10 */
    { PROCGEN_EXIT_N | PROCGEN_EXIT_S, ROOM_VAR_DIVIDED },   /* 11 */

    /* ------------------------------------------------------------------ */
    /* config 0x04 — Ouest seulement                                       */
    /* ------------------------------------------------------------------ */
    { PROCGEN_EXIT_W, ROOM_VAR_PLAIN   },   /* 12 */
    { PROCGEN_EXIT_W, ROOM_VAR_PILLARS },   /* 13 */
    { PROCGEN_EXIT_W, ROOM_VAR_DIVIDED },   /* 14 */

    /* ------------------------------------------------------------------ */
    /* config 0x05 — Nord+Ouest                                            */
    /* ------------------------------------------------------------------ */
    { PROCGEN_EXIT_N | PROCGEN_EXIT_W, ROOM_VAR_PLAIN   },   /* 15 */
    { PROCGEN_EXIT_N | PROCGEN_EXIT_W, ROOM_VAR_PILLARS },   /* 16 */
    { PROCGEN_EXIT_N | PROCGEN_EXIT_W, ROOM_VAR_DIVIDED },   /* 17 */

    /* ------------------------------------------------------------------ */
    /* config 0x06 — Sud+Ouest                                             */
    /* ------------------------------------------------------------------ */
    { PROCGEN_EXIT_S | PROCGEN_EXIT_W, ROOM_VAR_PLAIN   },   /* 18 */
    { PROCGEN_EXIT_S | PROCGEN_EXIT_W, ROOM_VAR_PILLARS },   /* 19 */
    { PROCGEN_EXIT_S | PROCGEN_EXIT_W, ROOM_VAR_DIVIDED },   /* 20 */

    /* ------------------------------------------------------------------ */
    /* config 0x07 — Nord+Sud+Ouest                                        */
    /* ------------------------------------------------------------------ */
    { PROCGEN_EXIT_N | PROCGEN_EXIT_S | PROCGEN_EXIT_W, ROOM_VAR_PLAIN   },   /* 21 */
    { PROCGEN_EXIT_N | PROCGEN_EXIT_S | PROCGEN_EXIT_W, ROOM_VAR_PILLARS },   /* 22 */
    { PROCGEN_EXIT_N | PROCGEN_EXIT_S | PROCGEN_EXIT_W, ROOM_VAR_DIVIDED },   /* 23 */

    /* ------------------------------------------------------------------ */
    /* config 0x08 — Est seulement                                         */
    /* ------------------------------------------------------------------ */
    { PROCGEN_EXIT_E, ROOM_VAR_PLAIN   },   /* 24 */
    { PROCGEN_EXIT_E, ROOM_VAR_PILLARS },   /* 25 */
    { PROCGEN_EXIT_E, ROOM_VAR_DIVIDED },   /* 26 */

    /* ------------------------------------------------------------------ */
    /* config 0x09 — Nord+Est                                              */
    /* ------------------------------------------------------------------ */
    { PROCGEN_EXIT_N | PROCGEN_EXIT_E, ROOM_VAR_PLAIN   },   /* 27 */
    { PROCGEN_EXIT_N | PROCGEN_EXIT_E, ROOM_VAR_PILLARS },   /* 28 */
    { PROCGEN_EXIT_N | PROCGEN_EXIT_E, ROOM_VAR_DIVIDED },   /* 29 */

    /* ------------------------------------------------------------------ */
    /* config 0x0A — Sud+Est                                               */
    /* ------------------------------------------------------------------ */
    { PROCGEN_EXIT_S | PROCGEN_EXIT_E, ROOM_VAR_PLAIN   },   /* 30 */
    { PROCGEN_EXIT_S | PROCGEN_EXIT_E, ROOM_VAR_PILLARS },   /* 31 */
    { PROCGEN_EXIT_S | PROCGEN_EXIT_E, ROOM_VAR_DIVIDED },   /* 32 */

    /* ------------------------------------------------------------------ */
    /* config 0x0B — Nord+Sud+Est                                          */
    /* ------------------------------------------------------------------ */
    { PROCGEN_EXIT_N | PROCGEN_EXIT_S | PROCGEN_EXIT_E, ROOM_VAR_PLAIN   },   /* 33 */
    { PROCGEN_EXIT_N | PROCGEN_EXIT_S | PROCGEN_EXIT_E, ROOM_VAR_PILLARS },   /* 34 */
    { PROCGEN_EXIT_N | PROCGEN_EXIT_S | PROCGEN_EXIT_E, ROOM_VAR_DIVIDED },   /* 35 */

    /* ------------------------------------------------------------------ */
    /* config 0x0C — Ouest+Est (couloir horizontal)                        */
    /* ------------------------------------------------------------------ */
    { PROCGEN_EXIT_W | PROCGEN_EXIT_E, ROOM_VAR_PLAIN   },   /* 36 */
    { PROCGEN_EXIT_W | PROCGEN_EXIT_E, ROOM_VAR_PILLARS },   /* 37 */
    { PROCGEN_EXIT_W | PROCGEN_EXIT_E, ROOM_VAR_DIVIDED },   /* 38 */

    /* ------------------------------------------------------------------ */
    /* config 0x0D — Nord+Ouest+Est                                        */
    /* ------------------------------------------------------------------ */
    { PROCGEN_EXIT_N | PROCGEN_EXIT_W | PROCGEN_EXIT_E, ROOM_VAR_PLAIN   },   /* 39 */
    { PROCGEN_EXIT_N | PROCGEN_EXIT_W | PROCGEN_EXIT_E, ROOM_VAR_PILLARS },   /* 40 */
    { PROCGEN_EXIT_N | PROCGEN_EXIT_W | PROCGEN_EXIT_E, ROOM_VAR_DIVIDED },   /* 41 */

    /* ------------------------------------------------------------------ */
    /* config 0x0E — Sud+Ouest+Est                                         */
    /* ------------------------------------------------------------------ */
    { PROCGEN_EXIT_S | PROCGEN_EXIT_W | PROCGEN_EXIT_E, ROOM_VAR_PLAIN   },   /* 42 */
    { PROCGEN_EXIT_S | PROCGEN_EXIT_W | PROCGEN_EXIT_E, ROOM_VAR_PILLARS },   /* 43 */
    { PROCGEN_EXIT_S | PROCGEN_EXIT_W | PROCGEN_EXIT_E, ROOM_VAR_DIVIDED },   /* 44 */

    /* ------------------------------------------------------------------ */
    /* config 0x0F — Toutes directions (carrefour)                         */
    /* ------------------------------------------------------------------ */
    { PROCGEN_EXIT_ALL, ROOM_VAR_PLAIN   },   /* 45 */
    { PROCGEN_EXIT_ALL, ROOM_VAR_PILLARS },   /* 46 */
    { PROCGEN_EXIT_ALL, ROOM_VAR_DIVIDED }    /* 47 */
};

/* ──────────────────────────────────────────────────────────────────────────
 * Sous-routine : dessine la base (murs périmètre + sol intérieur + portes).
 * Appelée par toutes les variantes.
 * ────────────────────────────────────────────────────────────────────────── */
static void room_draw_base(const ProcgenCell *cell,
                            u16 tile_wall, u16 tile_floor, u8 pal)
{
    u8 x, y;

    /* Périmètre : murs */
    ngpc_gfx_fill_rect(GFX_SCR1,
                       0u, 0u,
                       (u8)PROCGEN_SCREEN_W,
                       (u8)PROCGEN_SCREEN_H,
                       tile_wall, pal);

    /* Intérieur : sol */
    ngpc_gfx_fill_rect(GFX_SCR1,
                       1u, 1u,
                       (u8)(PROCGEN_SCREEN_W - 2u),
                       (u8)(PROCGEN_SCREEN_H - 2u),
                       tile_floor, pal);

    /* Porte Nord */
    if (cell->exits & PROCGEN_EXIT_N) {
        for (x = (u8)PROCGEN_DOOR_COL;
             x < (u8)(PROCGEN_DOOR_COL + PROCGEN_DOOR_W); x++) {
            ngpc_gfx_put_tile(GFX_SCR1, x, 0u, tile_floor, pal);
        }
    }
    /* Porte Sud */
    if (cell->exits & PROCGEN_EXIT_S) {
        for (x = (u8)PROCGEN_DOOR_COL;
             x < (u8)(PROCGEN_DOOR_COL + PROCGEN_DOOR_W); x++) {
            ngpc_gfx_put_tile(GFX_SCR1, x,
                              (u8)(PROCGEN_SCREEN_H - 1u), tile_floor, pal);
        }
    }
    /* Porte Ouest */
    if (cell->exits & PROCGEN_EXIT_W) {
        for (y = (u8)PROCGEN_DOOR_ROW;
             y < (u8)(PROCGEN_DOOR_ROW + PROCGEN_DOOR_H); y++) {
            ngpc_gfx_put_tile(GFX_SCR1, 0u, y, tile_floor, pal);
        }
    }
    /* Porte Est */
    if (cell->exits & PROCGEN_EXIT_E) {
        for (y = (u8)PROCGEN_DOOR_ROW;
             y < (u8)(PROCGEN_DOOR_ROW + PROCGEN_DOOR_H); y++) {
            ngpc_gfx_put_tile(GFX_SCR1,
                              (u8)(PROCGEN_SCREEN_W - 1u), y, tile_floor, pal);
        }
    }
}

/* ──────────────────────────────────────────────────────────────────────────
 * Variante 1 : Pillars (4 piliers à positions symétriques).
 *
 * Disposition sur un écran 20×19 (intérieur 18×17, rangées 1..17, cols 1..18) :
 *   Piliers à (4,4), (15,4), (4,14), (15,14) — symétriques, hors passages.
 *
 * Les piliers sont des murs 1×1. Le jeu peut décider de les rendre
 * infranchissables (tile_deco = tile_wall en collision) ou non.
 * ────────────────────────────────────────────────────────────────────────── */
static void room_draw_pillars(u16 tile_deco, u8 pal)
{
    ngpc_gfx_put_tile(GFX_SCR1,  4u,  4u, tile_deco, pal);
    ngpc_gfx_put_tile(GFX_SCR1, 15u,  4u, tile_deco, pal);
    ngpc_gfx_put_tile(GFX_SCR1,  4u, 14u, tile_deco, pal);
    ngpc_gfx_put_tile(GFX_SCR1, 15u, 14u, tile_deco, pal);
}

/* ──────────────────────────────────────────────────────────────────────────
 * Variante 2 : Divided — mur horizontal partiel au milieu (y=9).
 * Laisse un passage de 4 tiles au centre (cols 8..11).
 *
 * Utilisée pour créer des rooms avec deux sous-zones, forçant le joueur
 * à contourner ou trouver l'ouverture centrale.
 *
 * Adapté selon les exits : si des portes sont sur les cotés (W/E),
 * l'ouverture est toujours alignée avec le couloir principal.
 * ────────────────────────────────────────────────────────────────────────── */
static void room_draw_divided(const ProcgenCell *cell, u16 tile_deco, u8 pal)
{
    u8 x;
    u8 gap_lo;
    u8 gap_hi;

    /* Ouverture centrale : 4 tiles, colonnes 8..11 (milieu de l'écran 20px) */
    gap_lo = 8u;
    gap_hi = 11u;

    /* Mur horizontal à mi-hauteur (y = 9, milieu de l'écran 19 tiles) */
    for (x = 1u; x < (u8)(PROCGEN_SCREEN_W - 1u); x++) {
        /* Laisser le gap au centre, et respecter les portes W/E */
        if (x >= gap_lo && x <= gap_hi) continue;
        /* Éviter de bloquer les colonnes de porte Nord/Sud si elles existent */
        if (x >= (u8)PROCGEN_DOOR_COL &&
            x <  (u8)(PROCGEN_DOOR_COL + PROCGEN_DOOR_W) &&
            ((cell->exits & PROCGEN_EXIT_N) || (cell->exits & PROCGEN_EXIT_S))) {
            continue;
        }
        ngpc_gfx_put_tile(GFX_SCR1, x, 9u, tile_deco, pal);
    }
    (void)cell; /* supprime warning si pas de portes latérales */
}

/* ──────────────────────────────────────────────────────────────────────────
 * API principale : dessine selon la variante du template.
 * ────────────────────────────────────────────────────────────────────────── */
void ngpc_procgen_fill_room(
    const ProcgenCell              *cell,
    const NgpcRoomTemplate NGP_FAR *tpl,
    u16                             tile_wall,
    u16                             tile_floor,
    u16                             tile_deco,
    u8                              pal)
{
    /* Base identique pour toutes les variantes */
    room_draw_base(cell, tile_wall, tile_floor, pal);

    /* Overlay selon variante */
    if (tpl->variant == ROOM_VAR_PILLARS) {
        room_draw_pillars(tile_deco, pal);
    } else if (tpl->variant == ROOM_VAR_DIVIDED) {
        room_draw_divided(cell, tile_deco, pal);
    }
    /* ROOM_VAR_PLAIN : rien à ajouter */
}

/* Rétrocompatibilité */
void ngpc_procgen_fill_simple(
    const ProcgenCell *cell,
    u16                tile_wall,
    u16                tile_floor,
    u8                 pal)
{
    room_draw_base(cell, tile_wall, tile_floor, pal);
}

#endif /* PROCGEN_ROOMS_IMPL */

#endif /* NGPC_PROCGEN_ROOMS_H */
