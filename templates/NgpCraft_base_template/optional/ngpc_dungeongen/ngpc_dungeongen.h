/*
 * ngpc_dungeongen.h -- Generateur de donjon scrollable (metatile 16x16)
 * ======================================================================
 * Genere des salles de donjon riches avec :
 *   - Murs exterieurs / interieurs (8 types de coins + faces)
 *   - Population : eau traversante + pont, fosse (vide), tonneau, escalier
 *   - Entites   : ennemis sprites (ENE1 16x16, ENE2 8x8) + item 16x16
 *   - Scroll    : salles jusqu'a 16x16 metatiles (32x32 NGPC tiles)
 *   - Seed RTC  : session aleatoire differente a chaque lancement
 *
 * Complementaire de ngpc_procgen (DFS multi-room) et ngpc_cavegen (cave).
 * Ce module gere le CONTENU VISUEL d'une salle ; la navigation entre salles
 * reste dans le code appelant.
 *
 * ---------------------------------------------------------------------------
 * Dependances: ngpc_gfx, ngpc_sprite, ngpc_rtc
 * Assets generes par les outils :
 *   GraphX/tiles_procgen.c/.h   (export_procgen_tiles.py)
 *   GraphX/sprites_lab.c/.h     (export_sprites_lab.py)
 *
 * Installation :
 *   Copier optional/ngpc_dungeongen/ dans src/
 *   OBJS += $(OBJ_DIR)/src/ngpc_dungeongen/ngpc_dungeongen.rel
 *   OBJS += $(OBJ_DIR)/GraphX/tiles_procgen.rel
 *   OBJS += $(OBJ_DIR)/GraphX/sprites_lab.rel
 *   #include "ngpc_dungeongen/ngpc_dungeongen.h"
 * ---------------------------------------------------------------------------
 *
 * Usage minimal :
 *
 *   ngpc_dungeongen_set_rtc_seed();    // seed session RTC (1 fois au boot)
 *   ngpc_dungeongen_init();            // charge assets VRAM + palettes
 *   ngpc_dungeongen_enter(0u, 0xFFu); // room 0, style auto
 *   ngpc_dungeongen_spawn();           // ennemis + item en sprites
 *   // dans la boucle :
 *   ngpc_dungeongen_sync_sprites(cam_x, cam_y);  // sync camera chaque frame
 */

#ifndef NGPC_DUNGEONGEN_H
#define NGPC_DUNGEONGEN_H

#include "ngpc_hw.h"   /* u8, u16, s16 */

/* =========================================================================
 * Configuration -- tous ces defines sont injectables par le tool via -D
 * ou en #define avant l'include.
 * ========================================================================= */

/* ---- Sol : mix des 3 variantes (doit sommer a 100) ---- */
#ifndef DUNGEONGEN_GROUND_PCT_1
#define DUNGEONGEN_GROUND_PCT_1   70u
#endif
#ifndef DUNGEONGEN_GROUND_PCT_2
#define DUNGEONGEN_GROUND_PCT_2   20u
#endif
#ifndef DUNGEONGEN_GROUND_PCT_3
#define DUNGEONGEN_GROUND_PCT_3   10u
#endif

/* ---- Population : frequences (0=desactive, 100=systematique) ---- */
#ifndef DUNGEONGEN_EAU_FREQ
#define DUNGEONGEN_EAU_FREQ       40u   /* % bande eau par salle <=2 sorties */
#endif
#ifndef DUNGEONGEN_VIDE_FREQ
#define DUNGEONGEN_VIDE_FREQ      30u   /* % fosse par salle */
#endif
#ifndef DUNGEONGEN_TONNEAU_FREQ
#define DUNGEONGEN_TONNEAU_FREQ   50u   /* % tonneau par salle */
#endif
#ifndef DUNGEONGEN_TONNEAU_MAX
#define DUNGEONGEN_TONNEAU_MAX     2u   /* max tonneaux (1 ou 2) */
#endif
#ifndef DUNGEONGEN_ESCALIER_FREQ
#define DUNGEONGEN_ESCALIER_FREQ  40u   /* % escalier par salle */
#endif
#ifndef DUNGEONGEN_VIDE_MARGIN
#define DUNGEONGEN_VIDE_MARGIN     3u   /* marge metatiles autour sorties */
#endif

/* ---- Entites : ennemis + items ---- */
#ifndef DUNGEONGEN_ENEMY_MIN
#define DUNGEONGEN_ENEMY_MIN       0u   /* min ennemis par salle */
#endif
#ifndef DUNGEONGEN_ENEMY_MAX
#define DUNGEONGEN_ENEMY_MAX       3u   /* max ennemis (plafond absolu) */
#endif
#ifndef DUNGEONGEN_ENEMY_DENSITY
#define DUNGEONGEN_ENEMY_DENSITY  16u   /* metatiles/ennemi (scaling taille) */
#endif
#ifndef DUNGEONGEN_ENE2_PCT
#define DUNGEONGEN_ENE2_PCT       50u   /* % chance ennemi = ENE2 8x8 (vs ENE1 16x16) */
#endif
#ifndef DUNGEONGEN_ITEM_FREQ
#define DUNGEONGEN_ITEM_FREQ      50u   /* % item par salle (0=desactive) */
#endif

/* ---- Navigation : nombre de salles avant boss (0=infini) ---- */
/* Cette constante est exportee pour le CODE DE JEU uniquement.  */
/* ngpc_dungeongen ne gere pas la navigation entre salles.        */
#ifndef DUNGEONGEN_N_ROOMS
#define DUNGEONGEN_N_ROOMS         0u   /* 0 = pas de limite */
#endif

/* ---- Navigation cluster : taille max d'un lot de salles (2..4) ---- */
/* Utilise par ngpc_cluster pour borner la profondeur de l'arbre.       */
/* Valeur recommandee : 3. Maximum absolu : 4 (contrainte RAM).         */
#ifndef DUNGEONGEN_CLUSTER_SIZE_MAX
#define DUNGEONGEN_CLUSTER_SIZE_MAX  3u
#endif

/* ---- Difficulte : rampe ennemis par room_idx (0=desactive) ---- */
/* +1 au cap d'ennemis tous les N rooms, jusqu'a ENEMY_MAX.        */
#ifndef DUNGEONGEN_ENEMY_RAMP_ROOMS
#define DUNGEONGEN_ENEMY_RAMP_ROOMS  0u
#endif

/* ---- Salles safe/checkpoint (0=desactive) ---- */
/* Toutes les N rooms : 0 ennemis + item garanti. */
#ifndef DUNGEONGEN_SAFE_ROOM_EVERY
#define DUNGEONGEN_SAFE_ROOM_EVERY   0u
#endif

/* ---- Nombre minimum de sorties par salle (0=pas de contrainte) ---- */
#ifndef DUNGEONGEN_MIN_EXITS
#define DUNGEONGEN_MIN_EXITS         0u
#endif

/* ---- Tiers de difficulte (DUNGEONGEN_TIER_COLS=0 = desactive) ---- */
/* Quand TIER_COLS > 0, le tier courant (set via ngpc_dungeongen_set_tier) remplace */
/* les frequences statiques pour 4 parametres : enemy_max, item_freq, eau_freq,    */
/* vide_freq. Le tier est externe au module : le code de jeu appelle set_tier()    */
/* apres un boss, un floor, un changement de zone.                                 */
/* La rampe (ENEMY_RAMP_ROOMS) s'applique en bonus sur enemy_max du tier courant.  */
/*                                                                                  */
/* Quand TIER_COLS > 0, definir aussi les 4 tableaux (TIER_COLS valeurs chacun) :  */
/*   DUNGEONGEN_TIER_ENE_MAX   { 1u, 2u, 3u }   enemy_max par tier                */
/*   DUNGEONGEN_TIER_ITEM_FREQ { 60u, 50u, 40u } item_freq par tier               */
/*   DUNGEONGEN_TIER_EAU_FREQ  { 20u, 40u, 60u } eau_freq  par tier               */
/*   DUNGEONGEN_TIER_VIDE_FREQ { 10u, 30u, 50u } vide_freq par tier               */
#ifndef DUNGEONGEN_TIER_COLS
#define DUNGEONGEN_TIER_COLS         0u   /* 0 = tiers desactives */
#endif

/* ---- Taille des salles (metatiles, 1 metatile = 16x16 px = 2x2 NGPC tiles) ---- */
#ifndef DUNGEONGEN_ROOM_MW_MIN
#define DUNGEONGEN_ROOM_MW_MIN    10u
#endif
#ifndef DUNGEONGEN_ROOM_MW_MAX
#define DUNGEONGEN_ROOM_MW_MAX    16u
#endif
#ifndef DUNGEONGEN_ROOM_MH_MIN
#define DUNGEONGEN_ROOM_MH_MIN    10u
#endif
#ifndef DUNGEONGEN_ROOM_MH_MAX
#define DUNGEONGEN_ROOM_MH_MAX    16u
#endif

/* ---- Nombre max de sorties (0..4) ---- */
#ifndef DUNGEONGEN_MAX_EXITS
#define DUNGEONGEN_MAX_EXITS       4u
#endif

/* ---- Taille d'une cellule logique en tiles NGPC (8x8 px chacun) ---- */
/* Defaut : 2x2 tiles = metatile 16x16px.                               */
/* Exemple 8x8 : DUNGEONGEN_CELL_W_TILES=1, DUNGEONGEN_CELL_H_TILES=1  */
#ifndef DUNGEONGEN_CELL_W_TILES
#define DUNGEONGEN_CELL_W_TILES    2u
#endif
#ifndef DUNGEONGEN_CELL_H_TILES
#define DUNGEONGEN_CELL_H_TILES    2u
#endif

/* =========================================================================
 * Constantes publiques
 * ========================================================================= */

/* ---- Valeurs de collision retournees par ngpc_dungeongen_collision_at() ---- */
#define DGNCOL_PASS     0u   /* sol libre, traversable */
#define DGNCOL_SOLID    1u   /* mur (exterieur ou interieur) */
#define DGNCOL_WATER    2u   /* eau (comportement configurable via DUNGEONGEN_WATER_COL) */
#define DGNCOL_VOID     3u   /* fosse : mort */
#define DGNCOL_TRIGGER  4u   /* escalier : game code gere la transition */

/* Comportement de la collision eau (defaut = DGNCOL_WATER).
 * Remplacer par DGNCOL_SOLID pour rendre l'eau infranchissable (avec pont).
 * Le jeu interprete DGNCOL_WATER comme dommages ou mort selon ses propres regles. */
#ifndef DUNGEONGEN_WATER_COL
#define DUNGEONGEN_WATER_COL  DGNCOL_WATER
#endif

/* Masques de sorties murales (pour ngpc_dgroom.exits) */
#define DGN_EXIT_N   0x01u
#define DGN_EXIT_S   0x02u
#define DGN_EXIT_E   0x04u
#define DGN_EXIT_W   0x08u

/* Types de salle pour le modele cluster (defini par l'appelant avant enter) */
#define DGEN_ROOM_ENTRY  0u   /* point d'entree du cluster, pas de back-exit */
#define DGEN_ROOM_NODE   1u   /* noeud intermediaire : 1 back + 1-2 forward */
#define DGEN_ROOM_LEAF   2u   /* feuille : 1 back uniquement (+ escalier opt.) */

/* Nombre de styles disponibles selon DUNGEONGEN_MAX_EXITS */
#if DUNGEONGEN_MAX_EXITS == 0
#define DUNGEONGEN_N_STYLES  1u
#elif DUNGEONGEN_MAX_EXITS == 1
#define DUNGEONGEN_N_STYLES  2u
#elif DUNGEONGEN_MAX_EXITS == 2
#define DUNGEONGEN_N_STYLES  5u
#elif DUNGEONGEN_MAX_EXITS == 3
#define DUNGEONGEN_N_STYLES  6u
#else
#define DUNGEONGEN_N_STYLES  7u
#endif

/* =========================================================================
 * Structures publiques
 * ========================================================================= */

/*
 * Informations sur la salle courante.
 * Mis a jour par ngpc_dungeongen_enter() puis ngpc_dungeongen_spawn().
 * Lire apres chaque appel a ces fonctions.
 */
typedef struct {
    /* Geometrie */
    u8  room_w;        /* largeur en metatiles */
    u8  room_h;        /* hauteur en metatiles */
    u8  exits;         /* bitmask DGN_EXIT_* des sorties actives */
    u8  style_idx;     /* index style (0..DUNGEONGEN_N_STYLES-1) */
    u8  door_col_lo;   /* premiere colonne metatile de l'ouverture N/S */
    u8  door_col_hi;   /* derniere colonne metatile de l'ouverture N/S */
    u8  door_row_lo;   /* premiere rangee metatile de l'ouverture E/W */
    u8  door_row_hi;   /* derniere rangee metatile de l'ouverture E/W */
    s16 scroll_max_x;  /* scroll max horizontal en pixels (0 si salle = ecran) */
    s16 scroll_max_y;  /* scroll max vertical en pixels */
    /* Population (mis a jour par ngpc_dungeongen_enter) */
    u8  has_water;      /* 1 si bande d'eau presente (pas de murs interieurs) */
    u8  is_safe_room;   /* 1 si salle safe (0 ennemis, item garanti) */
    /* Navigation cluster (mis a jour par ngpc_dungeongen_enter) */
    u8  room_type;      /* DGEN_ROOM_ENTRY / NODE / LEAF — passe via ngpc_dgroom_set_type() */
    u8  has_stair;      /* 1 si escalier present dans cette room (leaf uniquement) */
    u8  stair_mx;       /* position X de l'escalier en metatiles (valide si has_stair) */
    u8  stair_my;       /* position Y de l'escalier en metatiles (valide si has_stair) */
    /* Entites (mis a jour par ngpc_dungeongen_spawn) */
    u8  enemy_count;    /* nombre d'ennemis spawnes */
    u8  item_active;    /* 1 si item present */
} NgpcDungeonRoom;

/* Salle courante : remplie par ngpc_dungeongen_enter() */
extern NgpcDungeonRoom ngpc_dgroom;

/* =========================================================================
 * API
 * ========================================================================= */

/*
 * Initialise la seed de session depuis le RTC.
 * Appeler une fois au boot avant ngpc_dungeongen_init().
 * Sans cet appel : seed=0 (donjon identique a chaque run, utile en debug).
 */
void ngpc_dungeongen_set_rtc_seed(void);

/*
 * Charge les assets graphiques en VRAM et configure les palettes.
 * Appeler une fois apres ngpc_init() et ngpc_gfx_scroll()/clear() initiaux.
 * Charge : tiles_procgen (terrain) + sprites_lab (entites).
 * Configure : PAL_TERRAIN, PAL_EAU sur GFX_SCR1 ; palettes sprites sur GFX_SPR.
 */
void ngpc_dungeongen_init(void);

/*
 * Genere et dessine une salle.
 * Efface GFX_SCR1 avant le dessin.
 * Met a jour ngpc_dgroom (dimensions, exits, scroll_max, door positions).
 *
 * room_idx   : index de salle (0..65534). Meme index = meme salle (deterministe).
 * style_idx  : forcer un style particulier (0..DUNGEONGEN_N_STYLES-1).
 *              Passer 0xFF pour derivation automatique depuis room_idx.
 */
void ngpc_dungeongen_enter(u16 room_idx, u8 style_idx);

/*
 * Retourne le nombre de styles disponibles (= DUNGEONGEN_N_STYLES).
 * Utiliser pour cycler les styles avec le bouton A dans l'editeur.
 */
u8 ngpc_dungeongen_n_styles(void);

/*
 * Spawne les entites (ennemis + item) pour la salle courante.
 * Appelle ngpc_sprite_hide_all() en premier.
 * Doit etre appele apres ngpc_dungeongen_enter().
 * Les positions sont en pixels-monde (metatile * 16) ; utilisees par sync_sprites.
 */
void ngpc_dungeongen_spawn(void);

/*
 * Synchronise les sprites vers leurs positions ecran.
 * A appeler chaque frame, apres la mise a jour camera.
 * cam_x, cam_y : position camera courante en pixels.
 * Cache automatiquement les sprites hors de l'ecran (160x152 px).
 */
void ngpc_dungeongen_sync_sprites(u8 cam_x, u8 cam_y);

/*
 * Retourne le type de collision a la position (mx, my) en metatiles.
 * Recalcul depuis l'etat interne (aucune carte de collision en RAM).
 * Appeler apres ngpc_dungeongen_enter() et ngpc_dungeongen_set_room_type().
 *
 * Retourne DGNCOL_PASS | DGNCOL_SOLID | DGNCOL_WATER | DGNCOL_VOID | DGNCOL_TRIGGER.
 *
 * Note : la detection des fosses (VIDE/VIDE_BORD) n'est pas incluse dans
 * cette version (necessite stockage de leur position en RAM). Le game code
 * peut complementer avec une verification tile si besoin.
 */
u8 ngpc_dungeongen_collision_at(u8 mx, u8 my);

/*
 * Definit le type de la salle courante dans le modele cluster.
 * Doit etre appele APRES ngpc_dungeongen_enter().
 * room_type : DGEN_ROOM_ENTRY | DGEN_ROOM_NODE | DGEN_ROOM_LEAF
 *
 * Effets :
 *   DGEN_ROOM_LEAF + avec_escalier=1 → place l'escalier au sol (tile exit_stair)
 *     a une position libre (hors eau, void, murs, sorties murales).
 *     ngpc_dgroom.has_stair, stair_mx, stair_my sont mis a jour.
 *   Autres types : ngpc_dgroom.has_stair = 0.
 *
 * Typiquement appele par ngpc_cluster.c, pas directement par le game code.
 */
void ngpc_dungeongen_set_room_type(u8 room_type, u8 avec_escalier);

/*
 * Retourne une seed u16 reproductible pour la salle room_idx + session courante.
 * Multiplicateur different du RNG interne : decorrelation garantie.
 * Utile pour piloter des comportements IA ou des evenements propres a chaque salle
 * de facon deterministe sans recoder le RNG dans le code appelant.
 * Appeler apres ngpc_dungeongen_set_rtc_seed() (ou pas, si debug seed=0).
 */
u16 ngpc_dungeongen_room_seed(u16 room_idx);

#if DUNGEONGEN_TIER_COLS > 0
/*
 * Avance le tier de difficulte (0..DUNGEONGEN_TIER_COLS-1).
 * A appeler depuis le code de jeu apres un boss, un floor, un changement de zone.
 * Tier hors plage : clampe automatiquement au dernier tier.
 * Affecte les prochains appels a ngpc_dungeongen_enter() + ngpc_dungeongen_spawn().
 */
void ngpc_dungeongen_set_tier(u8 tier);

/*
 * Retourne le tier courant (0..DUNGEONGEN_TIER_COLS-1).
 */
u8 ngpc_dungeongen_get_tier(void);
#endif /* DUNGEONGEN_TIER_COLS > 0 */

#endif /* NGPC_DUNGEONGEN_H */
