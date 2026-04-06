/*
 * ngpc_cavegen.c -- Implémentation du générateur de caves procédurales
 *
 * Algorithme en 4 passes :
 *   1. Remplissage aléatoire (wall_pct % murs, bordures toujours mur).
 *   2. Lissage cellulaire 5 × in-place (règle Moore 5/4).
 *   3. Flood-fill itératif depuis le centre → suppression des îlots isolés.
 *   4. Placement des entités (entrée, sortie, ennemis, coffres) par sections.
 *
 * Le lissage est fait in-place (pas de double-buffer) pour économiser la RAM.
 * L'effet de bord directionnel est négligeable et donne des formes organiques.
 *
 * Budget RAM :
 *   NgpcCaveMap = 1032 octets sur le tas/BSS du jeu.
 *   Aucune allocation locale > 16 octets dans les fonctions.
 */

#include "ngpc_cavegen/ngpc_cavegen.h"

/* ── Constantes internes ────────────────────────────────────────────────── */

#define CAVE_W  CAVEGEN_W   /* 32 */
#define CAVE_H  CAVEGEN_H   /* 32 */

/* Marqueur temporaire utilisé pendant le flood-fill.
 * Valeur choisie hors de la plage CAVE_* (0..5). */
#define CAVE_MARK  0xFEu

/* Écran NGPC visible */
#define VIEW_W  20u
#define VIEW_H  19u

/* ── Utilitaires ────────────────────────────────────────────────────────── */

/* Différence absolue sans stdlib abs() (cc900 ne l'a pas toujours). */
static u8 cave_abs_diff(u8 a, u8 b)
{
    return (a >= b) ? (u8)(a - b) : (u8)(b - a);
}

/* ── Étape 1 : remplissage aléatoire ────────────────────────────────────── */

static void cave_init(u8 *map, NgpcRng *rng, u8 wall_pct)
{
    u16 i;
    u8  x, y;

    /* Toutes les cellules intérieures : aléatoire selon wall_pct */
    for (i = 0u; i < (u16)(CAVE_W * CAVE_H); i++) {
        x = (u8)(i % CAVE_W);
        y = (u8)(i / CAVE_W);
        /* Bordures : toujours mur pour borner la cave */
        if (x == 0u || x == (u8)(CAVE_W - 1u) ||
            y == 0u || y == (u8)(CAVE_H - 1u)) {
            map[i] = CAVE_WALL;
        } else {
            map[i] = (ngpc_rng_u8(rng) % 100u < wall_pct) ? CAVE_WALL : CAVE_FLOOR;
        }
    }
}

/* ── Étape 2 : lissage cellulaire (automate de Moore) ───────────────────── */

/* Compte les murs dans le voisinage de Moore 3×3 (8 voisins + soi-même). */
static u8 cave_count_walls(const u8 *map, u8 x, u8 y)
{
    u8  count;
    s8  dx, dy;
    s8  nx, ny;

    count = 0u;
    for (dy = -1; dy <= 1; dy++) {
        for (dx = -1; dx <= 1; dx++) {
            if (dx == 0 && dy == 0) continue;
            nx = (s8)x + dx;
            ny = (s8)y + dy;
            /* Hors-grille = mur (renforce les bordures) */
            if (nx < 0 || nx >= (s8)CAVE_W || ny < 0 || ny >= (s8)CAVE_H) {
                count++;
            } else if (map[(u16)(u8)ny * CAVE_W + (u8)nx] == CAVE_WALL) {
                count++;
            }
        }
    }
    return count;
}

static void cave_smooth(u8 *map)
{
    u8  pass;
    u8  x, y;
    u8  walls;

    for (pass = 0u; pass < 5u; pass++) {
        /* In-place : légère dérive directionnelle, acceptable pour l'esthétique */
        for (y = 1u; y < (u8)(CAVE_H - 1u); y++) {
            for (x = 1u; x < (u8)(CAVE_W - 1u); x++) {
                walls = cave_count_walls(map, x, y);
                map[(u16)y * CAVE_W + x] = (walls >= 5u) ? CAVE_WALL : CAVE_FLOOR;
            }
        }
    }
}

/* ── Étape 3 : flood-fill pour retirer les îlots isolés ─────────────────── */

/*
 * Marque à 0xFE toutes les cellules CAVE_FLOOR connectées à (sx, sy).
 * Algorithme itératif multi-passes (O(n²) au pire, ~64 passes pour 32×32).
 * En pratique < 20 passes pour une cave typique = rapide sur NGPC.
 */
static void cave_flood_mark(u8 *map, u8 sx, u8 sy)
{
    u16 i;
    u8  x, y;
    u8  changed;

    if (map[(u16)sy * CAVE_W + sx] != CAVE_FLOOR) return;
    map[(u16)sy * CAVE_W + sx] = CAVE_MARK;

    do {
        changed = 0u;
        for (i = 0u; i < (u16)(CAVE_W * CAVE_H); i++) {
            if (map[i] != CAVE_FLOOR) continue;
            x = (u8)(i % CAVE_W);
            y = (u8)(i / CAVE_W);
            /* Propager si un voisin 4-connexe est marqué */
            if (x > 0u        && map[i - 1u]       == CAVE_MARK) { map[i] = CAVE_MARK; changed++; continue; }
            if (x < CAVE_W-1u && map[i + 1u]       == CAVE_MARK) { map[i] = CAVE_MARK; changed++; continue; }
            if (y > 0u        && map[i - CAVE_W]   == CAVE_MARK) { map[i] = CAVE_MARK; changed++; continue; }
            if (y < CAVE_H-1u && map[i + CAVE_W]   == CAVE_MARK) { map[i] = CAVE_MARK; changed++; continue; }
        }
    } while (changed);
}

/*
 * Cherche le premier CAVE_FLOOR en spirale depuis le centre.
 * Remplit *out_x, *out_y. Retourne 0 si aucun trouvé (cave 100% mur).
 */
static u8 cave_find_center_floor(const u8 *map, u8 *out_x, u8 *out_y)
{
    u8 r, x, y;
    u8 cx, cy;

    cx = (u8)(CAVE_W / 2u);
    cy = (u8)(CAVE_H / 2u);

    for (r = 0u; r < (u8)(CAVE_W / 2u); r++) {
        for (y = (u8)((cy >= r) ? cy - r : 0u);
             y <= (u8)((cy + r < CAVE_H) ? cy + r : CAVE_H - 1u);
             y++) {
            for (x = (u8)((cx >= r) ? cx - r : 0u);
                 x <= (u8)((cx + r < CAVE_W) ? cx + r : CAVE_W - 1u);
                 x++) {
                if (map[(u16)y * CAVE_W + x] == CAVE_FLOOR) {
                    *out_x = x;
                    *out_y = y;
                    return 1u;
                }
            }
        }
    }
    return 0u;
}

static void cave_remove_islands(u8 *map)
{
    u16 i;
    u8  fx, fy;

    /* Chercher un sol près du centre */
    if (!cave_find_center_floor(map, &fx, &fy)) {
        return; /* cave vide, rien à faire */
    }

    /* Marquer la région principale */
    cave_flood_mark(map, fx, fy);

    /* Convertir : CAVE_MARK→FLOOR, CAVE_FLOOR restant→WALL (îlots) */
    for (i = 0u; i < (u16)(CAVE_W * CAVE_H); i++) {
        if (map[i] == CAVE_MARK)   map[i] = CAVE_FLOOR;
        else if (map[i] == CAVE_FLOOR) map[i] = CAVE_WALL;
    }
}

/* ── Étape 4 : placement des entités ────────────────────────────────────── */

/*
 * Trouve le premier CAVE_FLOOR dans une colonne/rangée donnée.
 * Si x_fixed != 0xFF → cherche dans la colonne x_fixed, en variant y depuis y_start.
 * Si y_fixed != 0xFF → cherche dans la rangée y_fixed, en variant x depuis x_start.
 * Retourne 1 si trouvé.
 */
static u8 cave_find_floor_col(const u8 *map,
                               u8 col_lo, u8 col_hi,
                               u8 target_y,
                               u8 *out_x, u8 *out_y)
{
    u8 x, y, dy;

    for (x = col_lo; x <= col_hi; x++) {
        /* Chercher depuis target_y vers le haut et le bas alternativement */
        for (dy = 0u; dy < CAVE_H / 2u; dy++) {
            if (target_y >= dy) {
                y = (u8)(target_y - dy);
                if (map[(u16)y * CAVE_W + x] == CAVE_FLOOR) {
                    *out_x = x; *out_y = y; return 1u;
                }
            }
            y = (u8)(target_y + dy);
            if (y < CAVE_H && map[(u16)y * CAVE_W + x] == CAVE_FLOOR) {
                *out_x = x; *out_y = y; return 1u;
            }
        }
    }
    return 0u;
}

/*
 * Place une entité (tile_type) dans une section de 8×8 tiles.
 * Évite les tiles trop proches de (avoid_x, avoid_y).
 * Retourne 1 si placé, 0 sinon.
 */
static u8 cave_place_in_section(u8 *map, NgpcRng *rng,
                                 u8 sect_x, u8 sect_y,
                                 u8 tile_type,
                                 u8 avoid_x, u8 avoid_y,
                                 u8 min_dist)
{
    u8  i, j, x, y;
    u8  start_i, start_j;
    u8  dx, dy;

    /* Point de départ aléatoire dans la section (rend le placement varié) */
    start_i = ngpc_rng_u8(rng) & 7u;
    start_j = ngpc_rng_u8(rng) & 7u;

    for (j = 0u; j < 8u; j++) {
        for (i = 0u; i < 8u; i++) {
            x = (u8)((u8)(sect_x * 8u) + (u8)((start_i + i) & 7u));
            y = (u8)((u8)(sect_y * 8u) + (u8)((start_j + j) & 7u));

            if (x >= CAVE_W || y >= CAVE_H) continue;
            if (map[(u16)y * CAVE_W + x] != CAVE_FLOOR) continue;

            /* Distance Manhattan par rapport au point à éviter */
            dx = cave_abs_diff(x, avoid_x);
            dy = cave_abs_diff(y, avoid_y);
            if ((u8)(dx + dy) < min_dist) continue;

            map[(u16)y * CAVE_W + x] = tile_type;
            return 1u;
        }
    }
    return 0u;
}

static void cave_place_entities(NgpcCaveMap *out, NgpcRng *rng,
                                 u8 max_enemies, u8 max_chests)
{
    u8 sx, sy;  /* index de section (0..3) */
    u8 enemy_count;
    u8 chest_count;
    u8 roll;

    enemy_count = 0u;
    chest_count = 0u;

    /* Parcourir les 4×4 sections (chacune = 8×8 tiles).
     * On tente de placer 1 entité par section, en variant aléatoirement
     * entre ennemi et coffre selon les slots restants. */
    for (sy = 0u; sy < 4u; sy++) {
        for (sx = 0u; sx < 4u; sx++) {

            /* Sections proches de l'entrée → plus de chances de coffre */
            roll = ngpc_rng_u8(rng) % 4u;

            if (roll == 0u && chest_count < max_chests) {
                /* Tenter de placer un coffre */
                if (cave_place_in_section(out->map, rng, sx, sy,
                                          CAVE_CHEST,
                                          out->entry_x, out->entry_y, 5u)) {
                    chest_count++;
                }
            } else if (enemy_count < max_enemies) {
                /* Tenter de placer un ennemi */
                if (cave_place_in_section(out->map, rng, sx, sy,
                                          CAVE_ENEMY,
                                          out->entry_x, out->entry_y, 6u)) {
                    enemy_count++;
                }
            }
        }
    }

    out->enemy_count = enemy_count;
    out->chest_count = chest_count;
}

/* ── API publique ───────────────────────────────────────────────────────── */

void ngpc_cavegen_generate(
    NgpcCaveMap *out,
    u16          seed,
    u8           wall_pct,
    u8           max_enemies,
    u8           max_chests)
{
    NgpcRng rng;
    u8 center_y;

    out->seed        = seed;
    out->entry_x     = 0u;
    out->entry_y     = 0u;
    out->exit_x      = 0u;
    out->exit_y      = 0u;
    out->enemy_count = 0u;
    out->chest_count = 0u;

    ngpc_rng_init(&rng, seed);

    /* Clamp wall_pct */
    if (wall_pct > 65u) wall_pct = 65u;
    if (wall_pct < 35u) wall_pct = 35u;

    /* ── Phase 1 : remplissage ── */
    cave_init(out->map, &rng, wall_pct);

    /* ── Phase 2 : lissage ── */
    cave_smooth(out->map);

    /* ── Phase 3 : connexité ── */
    cave_remove_islands(out->map);

    /* ── Phase 4a : entrée (colonne 1..7, côté gauche) ── */
    center_y = (u8)(CAVE_H / 2u);
    if (!cave_find_floor_col(out->map, 1u, 7u, center_y,
                              &out->entry_x, &out->entry_y)) {
        /* Fallback : chercher n'importe où à gauche */
        cave_find_floor_col(out->map, 1u, (u8)(CAVE_W / 2u), center_y,
                            &out->entry_x, &out->entry_y);
    }
    out->map[(u16)out->entry_y * CAVE_W + out->entry_x] = CAVE_ENTRY;

    /* ── Phase 4b : sortie (colonne CAVE_W-8..CAVE_W-2, côté droit) ── */
    if (!cave_find_floor_col(out->map,
                              (u8)(CAVE_W - 8u), (u8)(CAVE_W - 2u), center_y,
                              &out->exit_x, &out->exit_y)) {
        /* Fallback : chercher n'importe où à droite */
        cave_find_floor_col(out->map,
                            (u8)(CAVE_W / 2u), (u8)(CAVE_W - 2u), center_y,
                            &out->exit_x, &out->exit_y);
    }
    out->map[(u16)out->exit_y * CAVE_W + out->exit_x] = CAVE_EXIT;

    /* ── Phase 4c : ennemis et coffres ── */
    cave_place_entities(out, &rng, max_enemies, max_chests);
}

void ngpc_cavegen_viewport(
    const NgpcCaveMap *m,
    u8                 cam_x,
    u8                 cam_y,
    u8                *out)
{
    u8 vx, vy;
    u8 mx, my;

    /* Clamper la caméra dans les bornes de la carte */
    if (cam_x + VIEW_W > CAVE_W) cam_x = (u8)(CAVE_W - VIEW_W);
    if (cam_y + VIEW_H > CAVE_H) cam_y = (u8)(CAVE_H - VIEW_H);

    for (vy = 0u; vy < VIEW_H; vy++) {
        my = (u8)(cam_y + vy);
        for (vx = 0u; vx < VIEW_W; vx++) {
            mx = (u8)(cam_x + vx);
            out[(u16)vy * VIEW_W + vx] = m->map[(u16)my * CAVE_W + mx];
        }
    }
}

void ngpc_cavegen_cam_center(u8 px, u8 py, u8 *cam_x, u8 *cam_y)
{
    /* Centrer la caméra sur le joueur */
    *cam_x = (px >= VIEW_W / 2u) ? (u8)(px - VIEW_W / 2u) : 0u;
    *cam_y = (py >= VIEW_H / 2u) ? (u8)(py - VIEW_H / 2u) : 0u;

    /* Borner */
    if (*cam_x + VIEW_W > CAVE_W) *cam_x = (u8)(CAVE_W - VIEW_W);
    if (*cam_y + VIEW_H > CAVE_H) *cam_y = (u8)(CAVE_H - VIEW_H);
}
