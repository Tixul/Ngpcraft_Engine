/*
 * ngpc_procgen.c -- Implémentation du générateur de donjons procéduraux
 *
 * Algorithme DFS "recursive backtracker" :
 *   1. Empiler la room de départ, marquer visitée.
 *   2. Tant que pile non-vide et room_count < MAX_ACTIVE :
 *        - Mélanger les 4 directions (ngpc_rng_shuffle).
 *        - Pour chaque direction : si voisin valide et non-visité → creuser.
 *        - Si aucun voisin disponible → dépiler (backtrack).
 *   3. BFS depuis le départ → room la plus lointaine = sortie.
 *   4. Assigner un template à chaque room active.
 *
 * Propriétés :
 *   - Donjon entièrement connexe (arbre couvrant = toutes rooms accessibles).
 *   - PROCGEN_MAX_ACTIVE < GRID_W*GRID_H → trous dans la grille.
 *   - Reproductible : même seed → même donjon.
 */

#include "ngpc_procgen/ngpc_procgen.h"

/* ── Tables de navigation (statiques, en ROM) ───────────────────────────── */

/* Déplacements en tiles par direction (DIR_N, DIR_S, DIR_W, DIR_E) */
static const s8 s_dx[4] = {  0,  0, -1,  1 };
static const s8 s_dy[4] = { -1,  1,  0,  0 };

/* Bits d'exit correspondant à chaque direction */
static const u8 s_exit_bits[4] = {
    PROCGEN_EXIT_N,
    PROCGEN_EXIT_S,
    PROCGEN_EXIT_W,
    PROCGEN_EXIT_E
};

/* Exit opposé pour creuser le passage en sens inverse */
static const u8 s_opposite_exit[4] = {
    PROCGEN_EXIT_S,  /* opposé de N = S */
    PROCGEN_EXIT_N,  /* opposé de S = N */
    PROCGEN_EXIT_E,  /* opposé de W = E */
    PROCGEN_EXIT_W   /* opposé de E = W */
};

/* ── DFS carver ─────────────────────────────────────────────────────────── */

static void dfs_carve(ProcgenMap *map, NgpcRng *rng, u8 start)
{
    /* Variables déclarées en tête de bloc (C89) */
    u8  stack[PROCGEN_MAX_ROOMS]; /* pile DFS (max = nb total de cellules) */
    u16 visited;                  /* bitmask : bit i = cellule i visitée  */
    u8  top;                      /* hauteur de pile (0 = vide) */
    u8  dirs[4];                  /* tableau de directions à mélanger */
    u8  cur;                      /* cellule au sommet de pile */
    u8  cx, cy;                   /* coordonnées de cur */
    u8  d, dir;                   /* index et direction courante */
    u8  nx, ny, nidx;             /* voisin candidat */
    u8  found;                    /* 1 si un voisin valide a été trouvé */

    /* ── Initialisation ── */
    top     = 0u;
    visited = 0u;
    dirs[0] = 0u; dirs[1] = 1u; dirs[2] = 2u; dirs[3] = 3u;

    /* Room de départ */
    map->cells[start].room_type   = PROCGEN_ROOM_START;
    map->cells[start].exits       = 0u;
    map->cells[start].template_id = 0u;
    map->cells[start].flags       = 0u;
    map->room_count = 1u;
    map->start_idx  = start;
    visited |= (u16)(1u << start);
    stack[top++] = start;

    /* ── Boucle DFS ── */
    while (top > 0u && map->room_count < (u8)PROCGEN_MAX_ACTIVE) {
        cur = stack[top - 1u];
        cx  = procgen_cell_x(cur);
        cy  = procgen_cell_y(cur);

        /* Mélanger les directions pour varier la forme du donjon */
        ngpc_rng_shuffle(rng, dirs, 4u);

        found = 0u;
        for (d = 0u; d < 4u && !found; d++) {
            dir = dirs[d];

            /* Calcul du voisin (overflow u8 → 255 si hors grille côté négatif) */
            nx = (u8)((int)cx + (int)s_dx[dir]);
            ny = (u8)((int)cy + (int)s_dy[dir]);

            /* Vérification des bornes (le cast u8 gère le underflow) */
            if (nx >= (u8)PROCGEN_GRID_W) continue;
            if (ny >= (u8)PROCGEN_GRID_H) continue;

            nidx = procgen_cell_idx(nx, ny);

            /* Déjà visité ? */
            if ((visited >> nidx) & 1u) continue;

            /* ── Creuser le passage ── */
            map->cells[cur].exits  |= s_exit_bits[dir];
            map->cells[nidx].exits  = s_opposite_exit[dir];
            map->cells[nidx].room_type   = PROCGEN_ROOM_NORMAL;
            map->cells[nidx].template_id = 0u;
            map->cells[nidx].flags       = 0u;
            visited |= (u16)(1u << nidx);
            stack[top++] = nidx;
            map->room_count++;
            found = 1u;
        }

        /* Aucun voisin disponible → backtrack */
        if (!found) {
            top--;
        }
    }
}

/* ── BFS pour trouver la room la plus éloignée ──────────────────────────── */

static u8 find_exit_room(const ProcgenMap *map)
{
    u8  dist[PROCGEN_MAX_ROOMS];
    u8  queue[PROCGEN_MAX_ROOMS];
    u8  head, tail;
    u8  i, cur, dir;
    u8  cx, cy, nx, ny, nidx;
    u8  max_dist, exit_idx;

    /* Initialiser toutes les distances à 0xFF (= non atteint) */
    for (i = 0u; i < (u8)PROCGEN_MAX_ROOMS; i++) {
        dist[i] = 0xFFu;
    }

    /* BFS depuis la room de départ */
    head = 0u; tail = 0u;
    dist[map->start_idx] = 0u;
    queue[tail++] = map->start_idx;

    while (head != tail) {
        cur = queue[head++];
        cx  = procgen_cell_x(cur);
        cy  = procgen_cell_y(cur);

        for (dir = 0u; dir < 4u; dir++) {
            if (!(map->cells[cur].exits & s_exit_bits[dir])) continue;
            nx = (u8)((int)cx + (int)s_dx[dir]);
            ny = (u8)((int)cy + (int)s_dy[dir]);
            if (nx >= (u8)PROCGEN_GRID_W) continue;
            if (ny >= (u8)PROCGEN_GRID_H) continue;
            nidx = procgen_cell_idx(nx, ny);
            if (dist[nidx] != 0xFFu) continue;
            dist[nidx] = (u8)(dist[cur] + 1u);
            queue[tail++] = nidx;
        }
    }

    /* Trouver la room NORMAL la plus lointaine */
    max_dist = 0u;
    exit_idx = map->start_idx; /* fallback si aucune NORMAL trouvée */
    for (i = 0u; i < (u8)PROCGEN_MAX_ROOMS; i++) {
        if (map->cells[i].room_type != PROCGEN_ROOM_NORMAL) continue;
        if (dist[i] == 0xFFu) continue; /* non atteinte (ne devrait pas arriver) */
        if (dist[i] > max_dist) {
            max_dist = dist[i];
            exit_idx = i;
        }
    }
    return exit_idx;
}

/* ── Assignation des templates ──────────────────────────────────────────── */

static void assign_templates(
    ProcgenMap                    *map,
    NgpcRng                       *rng,
    const NgpcRoomTemplate NGP_FAR *templates,
    u8                             count)
{
    u8 i;
    for (i = 0u; i < (u8)PROCGEN_MAX_ROOMS; i++) {
        if (map->cells[i].room_type == PROCGEN_ROOM_NONE) continue;
        map->cells[i].template_id = ngpc_procgen_pick_template(
            rng, map->cells[i].exits, templates, count);
    }
}

/* ── API publique ───────────────────────────────────────────────────────── */

void ngpc_procgen_generate(
    ProcgenMap                    *map,
    const NgpcRoomTemplate NGP_FAR *templates,
    u8                             tpl_count,
    u16                            seed)
{
    NgpcRng rng;
    u8 i;

    /* Réinitialiser toutes les cellules */
    for (i = 0u; i < (u8)PROCGEN_MAX_ROOMS; i++) {
        map->cells[i].room_type   = PROCGEN_ROOM_NONE;
        map->cells[i].exits       = 0u;
        map->cells[i].template_id = 0u;
        map->cells[i].flags       = 0u;
    }
    map->room_count  = 0u;
    map->current_idx = 0u;
    map->exit_idx    = 0u;
    map->start_idx   = 0u;
    map->seed_hi     = (u8)(seed >> 8);
    map->seed_lo     = (u8)(seed & 0xFFu);

    ngpc_rng_init(&rng, seed);

    /* 1. Générer la structure du donjon (DFS depuis coin haut-gauche) */
    dfs_carve(map, &rng, 0u);

    /* 2. Trouver et marquer la sortie */
    map->exit_idx = find_exit_room(map);
    map->cells[map->exit_idx].room_type = PROCGEN_ROOM_EXIT;

    /* 3. Assigner les templates */
    if (templates != 0 && tpl_count > 0u) {
        assign_templates(map, &rng, templates, tpl_count);
    }
}

void ngpc_procgen_load_room(
    ProcgenMap                    *map,
    u8                             idx,
    const NgpcRoomTemplate NGP_FAR *templates,
    ProcgenLoadFn                  load_fn,
    u8                             entry_dir,
    void                          *userdata)
{
    u8 tpl_id;
    const NgpcRoomTemplate NGP_FAR *tpl;

    if (idx >= (u8)PROCGEN_MAX_ROOMS) return;
    if (map->cells[idx].room_type == PROCGEN_ROOM_NONE) return;

    map->current_idx = idx;

    /* Appeler le callback AVANT de marquer VISITED.
     * Ainsi, dans le callback :
     *   !(cell->flags & PROCGEN_FLAG_VISITED) → première visite → spawner ennemis
     *     (cell->flags & PROCGEN_FLAG_VISITED) → retour      → ne rien respawner
     */
    if (load_fn != 0) {
        tpl_id = map->cells[idx].template_id;
        tpl    = templates + (u16)tpl_id;
        load_fn(&map->cells[idx], tpl, entry_dir, userdata);
    }

    /* Marquer après le callback pour que le prochain retour soit détecté */
    map->cells[idx].flags |= PROCGEN_FLAG_VISITED;
}

u8 ngpc_procgen_neighbor(const ProcgenMap *map, u8 room_idx, u8 dir)
{
    u8 cx, cy, nx, ny;

    if (room_idx >= (u8)PROCGEN_MAX_ROOMS) return PROCGEN_IDX_NONE;
    if (!(map->cells[room_idx].exits & s_exit_bits[dir])) return PROCGEN_IDX_NONE;

    cx = procgen_cell_x(room_idx);
    cy = procgen_cell_y(room_idx);
    nx = (u8)((int)cx + (int)s_dx[dir]);
    ny = (u8)((int)cy + (int)s_dy[dir]);

    if (nx >= (u8)PROCGEN_GRID_W) return PROCGEN_IDX_NONE;
    if (ny >= (u8)PROCGEN_GRID_H) return PROCGEN_IDX_NONE;

    return procgen_cell_idx(nx, ny);
}

void ngpc_procgen_spawn_pos(u8 entry_dir, u8 *out_x, u8 *out_y)
{
    switch (entry_dir) {
    case PROCGEN_DIR_N:
        /* Arrivée par le Nord → spawner juste sous la porte Nord */
        *out_x = (u8)PROCGEN_DOOR_COL;
        *out_y = 1u;
        break;
    case PROCGEN_DIR_S:
        /* Arrivée par le Sud → spawner juste au-dessus de la porte Sud */
        *out_x = (u8)PROCGEN_DOOR_COL;
        *out_y = (u8)(PROCGEN_SCREEN_H - 2u);
        break;
    case PROCGEN_DIR_W:
        /* Arrivée par l'Ouest → spawner juste à droite de la porte Ouest */
        *out_x = 1u;
        *out_y = (u8)PROCGEN_DOOR_ROW;
        break;
    case PROCGEN_DIR_E:
        /* Arrivée par l'Est → spawner juste à gauche de la porte Est */
        *out_x = (u8)(PROCGEN_SCREEN_W - 2u);
        *out_y = (u8)PROCGEN_DOOR_ROW;
        break;
    default:
        /* Chargement initial ou direction inconnue → centre de l'écran */
        *out_x = (u8)(PROCGEN_SCREEN_W / 2u);
        *out_y = (u8)(PROCGEN_SCREEN_H / 2u);
        break;
    }
}

u16 ngpc_procgen_room_seed(const ProcgenMap *map, u8 room_idx)
{
    u16 base;
    /* Mixer le seed global avec l'index de room pour un seed unique par room */
    base = (u16)((u16)map->seed_hi << 8 | (u16)map->seed_lo);
    return (u16)(base ^ (u16)((u16)room_idx * 0x9E37u));
}

/* ── Injection de boucles ───────────────────────────────────────────────── */

/*
 * Parcourt toutes les paires de cellules adjacentes NON connectées.
 * Chaque paire a une probabilité loop_pct/100 d'être connectée.
 * Ajoute les exits des deux côtés. Re-assigne ensuite les templates.
 */
static void inject_loops(
    ProcgenMap                    *map,
    NgpcRng                       *rng,
    const NgpcRoomTemplate NGP_FAR *templates,
    u8                             tpl_count,
    u8                             loop_pct)
{
    u8 i;
    u8 cx, cy;
    u8 nx, ny;
    u8 nidx;
    u8 dir;
    u8 roll;

    if (loop_pct == 0u) return;

    for (i = 0u; i < (u8)PROCGEN_MAX_ROOMS; i++) {
        if (map->cells[i].room_type == PROCGEN_ROOM_NONE) continue;
        cx = procgen_cell_x(i);
        cy = procgen_cell_y(i);

        /* Seulement E et S pour éviter de traiter chaque paire deux fois */
        for (dir = PROCGEN_DIR_S; dir <= PROCGEN_DIR_E; dir++) {
            /* Déjà connectée dans cette direction ? */
            if (map->cells[i].exits & s_exit_bits[dir]) continue;

            nx = (u8)((int)cx + (int)s_dx[dir]);
            ny = (u8)((int)cy + (int)s_dy[dir]);
            if (nx >= (u8)PROCGEN_GRID_W) continue;
            if (ny >= (u8)PROCGEN_GRID_H) continue;

            nidx = procgen_cell_idx(nx, ny);
            if (map->cells[nidx].room_type == PROCGEN_ROOM_NONE) continue;

            /* Tirage aléatoire */
            roll = ngpc_rng_u8(rng) % 100u;
            if (roll >= loop_pct) continue;

            /* Ouvrir le passage */
            map->cells[i].exits    |= s_exit_bits[dir];
            map->cells[nidx].exits |= s_opposite_exit[dir];
        }
    }

    /* Re-assigner les templates (les exits ont changé) */
    if (templates != 0 && tpl_count > 0u) {
        assign_templates(map, rng, templates, tpl_count);
    }
}

/* ── generate_ex ────────────────────────────────────────────────────────── */

void ngpc_procgen_generate_ex(
    ProcgenMap                    *map,
    const NgpcRoomTemplate NGP_FAR *templates,
    u8                             tpl_count,
    u16                            seed,
    u8                             loop_pct)
{
    NgpcRng rng;
    u8 i;

    for (i = 0u; i < (u8)PROCGEN_MAX_ROOMS; i++) {
        map->cells[i].room_type   = PROCGEN_ROOM_NONE;
        map->cells[i].exits       = 0u;
        map->cells[i].template_id = 0u;
        map->cells[i].flags       = 0u;
    }
    map->room_count  = 0u;
    map->current_idx = 0u;
    map->exit_idx    = 0u;
    map->start_idx   = 0u;
    map->seed_hi     = (u8)(seed >> 8);
    map->seed_lo     = (u8)(seed & 0xFFu);

    ngpc_rng_init(&rng, seed);

    dfs_carve(map, &rng, 0u);

    map->exit_idx = find_exit_room(map);
    map->cells[map->exit_idx].room_type = PROCGEN_ROOM_EXIT;

    if (templates != 0 && tpl_count > 0u) {
        assign_templates(map, &rng, templates, tpl_count);
    }

    /* Injection de boucles APRES l'assignation initiale des templates */
    if (loop_pct > 0u) {
        inject_loops(map, &rng, templates, tpl_count, loop_pct);
    }
}

/* ── Génération de contenu ──────────────────────────────────────────────── */

void ngpc_procgen_gen_content(
    const ProcgenMap *map,
    ProcgenContent   *content,
    u8                max_enemies,
    u8                item_chance)
{
    NgpcRng rng;
    u8 i;
    u8 base_seed_hi;
    u8 base_seed_lo;
    u16 room_seed;
    u8 roll;
    u8 count;

    base_seed_hi = map->seed_hi;
    base_seed_lo = map->seed_lo;

    for (i = 0u; i < (u8)PROCGEN_MAX_ROOMS; i++) {
        content[i].enemies = 0u;
        content[i].items   = 0u;
        content[i].count   = 0u;
        content[i].special = 0u;

        if (map->cells[i].room_type == PROCGEN_ROOM_NONE) continue;

        /* Seed unique et reproductible pour chaque room */
        room_seed = (u16)((u16)((u16)base_seed_hi << 8u) | (u16)base_seed_lo);
        room_seed = (u16)(room_seed ^ (u16)((u16)i * 0x9E37u));
        ngpc_rng_init(&rng, room_seed);

        switch (map->cells[i].room_type) {
        case PROCGEN_ROOM_START:
            /* Room de départ toujours vide */
            break;

        case PROCGEN_ROOM_EXIT:
            /* Boss room : max ennemis, flag boss */
            content[i].enemies = 0xFFu; /* tous les types */
            content[i].count   = max_enemies;
            content[i].special = 1u;    /* flag boss */
            break;

        case PROCGEN_ROOM_SHOP:
            /* Boutique : pas d'ennemis, tous les items */
            content[i].items   = 0xFFu;
            content[i].special = 2u;    /* flag shop */
            break;

        case PROCGEN_ROOM_SECRET:
            /* Room secrète : 1 ennemi gardien + loot rare */
            content[i].enemies = (u8)(1u << (ngpc_rng_u8(&rng) & 0x07u));
            content[i].items   = 0xFFu;
            content[i].count   = 1u;
            content[i].special = 3u;    /* flag secret */
            break;

        case PROCGEN_ROOM_NORMAL:
        default:
            /* Room normale : ennemis et objets aléatoires */
            if (max_enemies > 0u) {
                count = (u8)(1u + ngpc_rng_u8(&rng) % max_enemies);
                content[i].count = count;
                /* Choisir 1..3 types d'ennemis aléatoirement */
                content[i].enemies = ngpc_rng_u8(&rng);
                if (content[i].enemies == 0u) content[i].enemies = 1u;
            }
            /* Chance de trouver un objet */
            roll = ngpc_rng_u8(&rng) % 100u;
            if (roll < item_chance) {
                content[i].items = (u8)(1u << (ngpc_rng_u8(&rng) & 0x07u));
            }
            break;
        }
    }
}

u8 ngpc_procgen_pick_template(
    NgpcRng                       *rng,
    u8                             exits_req,
    const NgpcRoomTemplate NGP_FAR *templates,
    u8                             count)
{
    u8 candidates[PROCGEN_MAX_TEMPLATES];
    u8 n_cand;
    u8 i;

    if (count == 0u || templates == 0) return 0u;

    n_cand = 0u;
    for (i = 0u; i < count && i < (u8)PROCGEN_MAX_TEMPLATES; i++) {
        /* Compatible si le template supporte TOUS les exits requis */
        if ((templates[i].exits_mask & exits_req) == exits_req) {
            candidates[n_cand] = i;
            n_cand++;
        }
    }

    if (n_cand == 0u) return 0u; /* fallback : template 0 */

    return candidates[ngpc_rng_u8(rng) % n_cand];
}
