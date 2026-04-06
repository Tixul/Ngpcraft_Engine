/*
 * ngpc_cavegen_example.c -- Exemples d'utilisation ngpc_procgen + ngpc_cavegen
 * ============================================================================
 * Ce fichier montre comment utiliser les deux modules dans un jeu NGPC.
 *
 * STYLE 1 : Dicing Knight (donjon room-by-room avec carte)
 *   - Génération complète en début de partie.
 *   - Navigation porte par porte.
 *   - Contenu procédural (ennemis, items) par room.
 *   - Map miniature du donjon affichable (depuis ProcgenMap.cells[]).
 *
 * STYLE 2 : Cave Noir (cave ouverte avec scrolling)
 *   - Cave 32×32 générée en début de partie.
 *   - Le joueur se déplace librement, la caméra suit.
 *   - Fog-of-war optionnel (à implémenter dans le jeu).
 *
 * ============================================================================
 * Pour compiler cet exemple (test dans le template) :
 *   - Ajouter aux OBJS: ngpc_procgen.rel  ngpc_cavegen.rel
 *   - Inclure les headers correspondants.
 *   - Définir PROCGEN_ROOMS_IMPL dans un seul .c.
 * ============================================================================
 */

/* ---- Includes ---- */
#include "ngpc_hw.h"
#include "ngpc_sys.h"
#include "ngpc_gfx.h"
#include "ngpc_text.h"
#include "ngpc_input.h"
#include "ngpc_timing.h"
#include "ngpc_rng/ngpc_rng.h"

/* Activer l'implémentation des templates ici (un seul .c) */
#define PROCGEN_ROOMS_IMPL
#include "ngpc_procgen/ngpc_procgen.h"
#include "ngpc_procgen/ngpc_procgen_rooms.h"
#include "ngpc_cavegen/ngpc_cavegen.h"

/* ── Tiles prototype (à remplacer par tes vrais assets) ─────────────────── */
/* Ces valeurs supposent que tes tiles sont chargés à partir du slot 128. */
#define TILE_WALL    128u
#define TILE_FLOOR   129u
#define TILE_DECO    130u  /* piliers, déco */
#define TILE_PLAYER  131u
#define TILE_ENEMY   132u
#define TILE_CHEST   133u
#define TILE_EXIT    134u
#define TILE_DOOR    135u

/* ============================================================================
 * STYLE 1 : DONJON DICING KNIGHT
 * ============================================================================
 */

/* Données globales du donjon */
static ProcgenMap       s_dungeon;
static ProcgenContent   s_content[PROCGEN_MAX_ROOMS];

/* Position du joueur en tiles dans la room courante */
static u8 s_player_x;
static u8 s_player_y;

/*
 * Callback chargé par ngpc_procgen_load_room().
 * Appelé à chaque transition de room.
 */
static void dungeon_load_room_cb(
    const ProcgenCell              *cell,
    const NgpcRoomTemplate NGP_FAR *tpl,
    u8                              entry_dir,
    void                           *userdata)
{
    u8  idx;
    (void)userdata;

    /* Dessiner la room selon sa variante */
    ngpc_procgen_fill_room(cell, tpl,
                           TILE_WALL, TILE_FLOOR, TILE_DECO, 0u);

    /* Récupérer l'index depuis map->current_idx (déjà mis à jour) */
    idx = s_dungeon.current_idx;

    /* Première visite → spawner les ennemis */
    if (!(cell->flags & PROCGEN_FLAG_VISITED)) {
        /* s_content[idx].count ennemis de type s_content[idx].enemies */
        /* → ton code de spawn ici */
        (void)s_content[idx].count;   /* utiliser selon ton pool d'entités */
        (void)s_content[idx].enemies;
    }

    /* Afficher le type de room */
    switch (cell->room_type) {
    case PROCGEN_ROOM_START:
        ngpc_text_print(GFX_SCR1, 0, 8, 1, "START");
        break;
    case PROCGEN_ROOM_EXIT:
        ngpc_text_print(GFX_SCR1, 0, 8, 1, "BOSS!");
        ngpc_gfx_put_tile(GFX_SCR1, 10u, 9u, TILE_EXIT, 0u);
        break;
    case PROCGEN_ROOM_SHOP:
        ngpc_text_print(GFX_SCR1, 0, 8, 1, "SHOP");
        break;
    default:
        break;
    }

    /* Afficher les coffres si présents */
    if (s_content[idx].items != 0u && !(cell->flags & PROCGEN_FLAG_CLEARED)) {
        ngpc_gfx_put_tile(GFX_SCR1, 5u, 9u, TILE_CHEST, 0u);
    }

    (void)entry_dir;
}

/*
 * Initialise le donjon : génération + chargement de la room de départ.
 */
static void dungeon_init(u16 seed)
{
    /* Générer avec 20% de boucles pour casser la monotonie du DFS pur */
    ngpc_procgen_generate_ex(&s_dungeon,
                              g_procgen_rooms, PROCGEN_ROOMS_COUNT,
                              seed,
                              20u);   /* loop_pct = 20% */

    /* Générer le contenu : max 3 ennemis, 40% chance d'item par room */
    ngpc_procgen_gen_content(&s_dungeon, s_content, 3u, 40u);

    /* Charger la room de départ */
    ngpc_procgen_load_room(&s_dungeon,
                            s_dungeon.start_idx,
                            g_procgen_rooms,
                            dungeon_load_room_cb,
                            0xFFu,  /* entrée initiale */
                            0);

    /* Spawner le joueur au centre */
    ngpc_procgen_spawn_pos(0xFFu, &s_player_x, &s_player_y);
}

/*
 * Update frame donjon : gestion des déplacements et transitions de room.
 * Appelé chaque frame depuis le game loop.
 */
static void dungeon_update(void)
{
    u8 cur;
    u8 next_room;
    u8 dir;

    cur = s_dungeon.current_idx;

    /* Déplacement joueur (simplifié, à remplacer par ta logique d'acteur) */
    if (ngpc_pad_pressed & PAD_LEFT)  { if (s_player_x > 1u) s_player_x--; }
    if (ngpc_pad_pressed & PAD_RIGHT) { if (s_player_x < 18u) s_player_x++; }
    if (ngpc_pad_pressed & PAD_UP)    { if (s_player_y > 1u) s_player_y--; }
    if (ngpc_pad_pressed & PAD_DOWN)  { if (s_player_y < 17u) s_player_y++; }

    /* Afficher le joueur */
    ngpc_gfx_put_tile(GFX_SCR1, s_player_x, s_player_y, TILE_PLAYER, 0u);

    /* Détection des transitions de room par les bords */
    dir = 0xFFu;
    if (s_player_y == 0u && (s_dungeon.cells[cur].exits & PROCGEN_EXIT_N))
        dir = PROCGEN_DIR_N;
    else if (s_player_y == 18u && (s_dungeon.cells[cur].exits & PROCGEN_EXIT_S))
        dir = PROCGEN_DIR_S;
    else if (s_player_x == 0u && (s_dungeon.cells[cur].exits & PROCGEN_EXIT_W))
        dir = PROCGEN_DIR_W;
    else if (s_player_x == 19u && (s_dungeon.cells[cur].exits & PROCGEN_EXIT_E))
        dir = PROCGEN_DIR_E;

    if (dir != 0xFFu) {
        next_room = ngpc_procgen_neighbor(&s_dungeon, cur, dir);
        if (next_room != PROCGEN_IDX_NONE) {
            /* Charger la room voisine */
            ngpc_procgen_load_room(&s_dungeon,
                                    next_room,
                                    g_procgen_rooms,
                                    dungeon_load_room_cb,
                                    dir,
                                    0);
            /* Repositionner le joueur à la porte d'entrée */
            ngpc_procgen_spawn_pos(dir, &s_player_x, &s_player_y);
        }
    }
}

/*
 * Affiche une mini-map du donjon dans le coin haut-gauche (optionnel).
 * Chaque room = 1 caractère : ' '=non visitée, '.'=visitée, 'S'=start,
 * 'X'=exit, '@'=joueur.
 */
static void dungeon_draw_minimap(void)
{
    u8 x, y, idx;
    char c;
    char row[PROCGEN_GRID_W + 1];

    row[PROCGEN_GRID_W] = '\0';

    for (y = 0u; y < (u8)PROCGEN_GRID_H; y++) {
        for (x = 0u; x < (u8)PROCGEN_GRID_W; x++) {
            idx = procgen_cell_idx(x, y);
            if (s_dungeon.cells[idx].room_type == PROCGEN_ROOM_NONE) {
                c = ' ';
            } else if (idx == s_dungeon.current_idx) {
                c = '@';
            } else if (idx == s_dungeon.exit_idx) {
                c = 'X';
            } else if (idx == s_dungeon.start_idx) {
                c = 'S';
            } else if (s_dungeon.cells[idx].flags & PROCGEN_FLAG_VISITED) {
                c = '.';
            } else {
                c = '?';
            }
            row[x] = c;
        }
        ngpc_text_print(GFX_SCR1, 0, (u8)(15u + y), 1u, row);
    }
}


/* ============================================================================
 * STYLE 2 : CAVE NOIR (cave ouverte avec scrolling)
 * ============================================================================
 */

/* Données globales de la cave */
static NgpcCaveMap s_cave;
static u8 s_view[20u * 19u];  /* viewport courant = 380 octets */

/* Position joueur dans la cave (en tiles) */
static u8 s_cave_px;
static u8 s_cave_py;

/* Caméra (top-left du viewport) */
static u8 s_cam_x;
static u8 s_cam_y;

/* Tiles pour la cave (à remplacer par tes assets) */
static const u16 s_cave_tiles[6] = {
    TILE_WALL,   /* CAVE_WALL  = 0 */
    TILE_FLOOR,  /* CAVE_FLOOR = 1 */
    TILE_FLOOR,  /* CAVE_ENTRY = 2 (sol sous l'entrée) */
    TILE_EXIT,   /* CAVE_EXIT  = 3 */
    TILE_CHEST,  /* CAVE_CHEST = 4 */
    TILE_ENEMY   /* CAVE_ENEMY = 5 */
};

/*
 * Rendu du viewport dans VRAM (tile par tile).
 * Dans un vrai jeu, utilise DMA ou VRAM queue pour éviter le Character Over.
 */
static void cave_render_view(void)
{
    u8  vx, vy;
    u8  tile_type;
    u16 tile_idx;

    for (vy = 0u; vy < 19u; vy++) {
        for (vx = 0u; vx < 20u; vx++) {
            tile_type = s_view[(u16)vy * 20u + vx];
            tile_idx  = s_cave_tiles[tile_type < 6u ? tile_type : 0u];
            ngpc_gfx_put_tile(GFX_SCR1, vx, vy, tile_idx, 0u);
        }
    }
}

/*
 * Initialise la cave : génération + rendu initial.
 */
static void cave_init(u16 seed)
{
    /* Générer cave : wall_pct=47, 8 ennemis max, 3 coffres max */
    ngpc_cavegen_generate(&s_cave, seed, 47u, 8u, 3u);

    /* Positionner le joueur à l'entrée */
    s_cave_px = s_cave.entry_x;
    s_cave_py = s_cave.entry_y;

    /* Centrer la caméra sur le joueur */
    ngpc_cavegen_cam_center(s_cave_px, s_cave_py, &s_cam_x, &s_cam_y);

    /* Premier rendu */
    ngpc_cavegen_viewport(&s_cave, s_cam_x, s_cam_y, s_view);
    cave_render_view();
}

/*
 * Update frame cave : déplacement + collision + scrolling.
 */
static void cave_update(void)
{
    u8 new_px;
    u8 new_py;
    u8 cam_changed;
    u8 new_cam_x;
    u8 new_cam_y;
    u8 tile_at;

    new_px = s_cave_px;
    new_py = s_cave_py;

    if (ngpc_pad_pressed & PAD_LEFT)  { if (new_px > 0u)           new_px--; }
    if (ngpc_pad_pressed & PAD_RIGHT) { if (new_px < CAVEGEN_W-1u) new_px++; }
    if (ngpc_pad_pressed & PAD_UP)    { if (new_py > 0u)           new_py--; }
    if (ngpc_pad_pressed & PAD_DOWN)  { if (new_py < CAVEGEN_H-1u) new_py++; }

    /* Collision tilemap : vérifier que la destination est du sol */
    tile_at = s_cave.map[(u16)new_py * CAVEGEN_W + new_px];
    if (tile_at == CAVE_WALL) {
        /* Mouvement bloqué */
        new_px = s_cave_px;
        new_py = s_cave_py;
    }

    /* Collecte coffre / sortie */
    if (tile_at == CAVE_CHEST) {
        s_cave.map[(u16)new_py * CAVEGEN_W + new_px] = CAVE_FLOOR;
        /* → déclencher collecte d'objet */
    } else if (tile_at == CAVE_EXIT) {
        /* → transition vers niveau suivant */
    }

    s_cave_px = new_px;
    s_cave_py = new_py;

    /* Mettre à jour la caméra si le joueur est proche du bord du viewport */
    ngpc_cavegen_cam_center(s_cave_px, s_cave_py, &new_cam_x, &new_cam_y);
    cam_changed = (new_cam_x != s_cam_x || new_cam_y != s_cam_y);
    s_cam_x = new_cam_x;
    s_cam_y = new_cam_y;

    /* Ré-extraire et re-rendre le viewport si la caméra a bougé */
    if (cam_changed) {
        ngpc_cavegen_viewport(&s_cave, s_cam_x, s_cam_y, s_view);
        cave_render_view();
    }

    /* Afficher le joueur (position relative dans le viewport) */
    if (s_cave_px >= s_cam_x && s_cave_py >= s_cam_y) {
        ngpc_gfx_put_tile(GFX_SCR1,
                          (u8)(s_cave_px - s_cam_x),
                          (u8)(s_cave_py - s_cam_y),
                          TILE_PLAYER, 0u);
    }

    /* Afficher les stats */
    ngpc_text_print_num(GFX_SCR1, 0, 0, 0u, s_cave.enemy_count, 2u);
    ngpc_text_print(    GFX_SCR1, 0, 2, 0u, " EN");
    ngpc_text_print_num(GFX_SCR1, 0, 3, 0u, s_cave.chest_count, 2u);
    ngpc_text_print(    GFX_SCR1, 0, 5, 0u, " CH");
}

/* ============================================================================
 * MAIN DE DÉMONSTRATION
 * ============================================================================
 */

/*
 * Pour tester, ajouter cet appel à ton main.c dans la loop de jeu.
 * Sélectionner le mode avec PAD_OPTION : Donjon / Cave.
 */
void procgen_demo_main(void)
{
    u8 mode;      /* 0 = donjon, 1 = cave */
    u16 seed;

    seed = 0xCAFEu;  /* Remplacer par ngpc_rng_u16(&some_rng) pour aléatoire */
    mode = 0u;

    ngpc_init();
    ngpc_gfx_set_bg_color(0u);

    dungeon_init(seed);

    while (1) {
        ngpc_vsync();
        ngpc_input_update();

        /* Basculer entre donjon et cave avec OPTION */
        if (ngpc_pad_pressed & PAD_OPTION) {
            mode = (mode == 0u) ? 1u : 0u;
            ngpc_gfx_clear(GFX_SCR1);
            if (mode == 0u) {
                dungeon_init(seed);
            } else {
                cave_init((u16)(seed ^ 0x1234u));
            }
        }

        /* Nouveau seed avec B */
        if (ngpc_pad_pressed & PAD_B) {
            seed = (u16)(seed * 0x6C07u + 0x3925u); /* LCG simple */
            ngpc_gfx_clear(GFX_SCR1);
            if (mode == 0u) {
                dungeon_init(seed);
            } else {
                cave_init(seed);
            }
        }

        if (mode == 0u) {
            dungeon_update();
            dungeon_draw_minimap();
        } else {
            cave_update();
        }
    }
}
