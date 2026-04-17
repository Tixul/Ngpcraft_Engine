# ngpc_dungeongen — Générateur de donjon scrollable

**Statut : ✅ Validé**

Génère des salles de donjon riches avec murs complets (8 types coins/faces),
eau + pont, fosses, tonneaux, escalier, et spawn d'ennemis/items depuis des
pools configurés dans NgpCraft Engine. Les salles peuvent dépasser la taille
de l'écran — scrolling caméra automatique.

**Complémentaire de :** `optional/ngpc_procgen/` (navigation entre salles)
et `optional/ngpc_cavegen/` (cave ouverte).

**Dépend de :** `ngpc_gfx`, `ngpc_sprite`, `ngpc_rtc`

**Assets générés par NgpCraft Engine :**
- `GraphX/gen/tiles_procgen.c/.h` — tileset terrain (onglet Procgen Assets)
- `GraphX/gen/sprites_lab.c/.h` — pools sprites ennemis/items

**Makefile :**
```makefile
OBJS += $(OBJ_DIR)/src/ngpc_dungeongen/ngpc_dungeongen.rel
OBJS += $(OBJ_DIR)/GraphX/gen/tiles_procgen.rel
OBJS += $(OBJ_DIR)/GraphX/gen/sprites_lab.rel
```

---

## Architecture

```
optional/ngpc_dungeongen/
└── ngpc_dungeongen.h   — structures, API publique, tous les #define configurables
└── ngpc_dungeongen.c   — générateur de salle + spawner + sync sprites

GraphX/gen/              (auto-généré par NgpCraft Engine)
├── tiles_procgen.h/c   — tileset terrain (26 rôles : floor, murs, coins, eau…)
├── sprites_lab.h/c     — tile data sprites VRAM + pools (s_ene_*, s_item_*)
└── dungeongen_config.h — paramètres runtime (#define DUNGEONGEN_*)
```

---

## Concepts clés

### Métatile

Une salle est une grille de **métatiles**. En mode 16×16 (défaut) :
- 1 métatile = 2×2 tiles NGPC = 16×16 pixels
- Salle 16×16 métatiles = 32×32 tiles NGPC = 256×256 pixels
- Écran NGPC = 20×19 tiles = 10×9.5 métatiles

Si la salle dépasse 20 métatiles de large ou 19 de haut → scroll requis.
`ngpc_dgroom.scroll_max_x / scroll_max_y` indiquent le scroll maximum en pixels.

### Déterminisme

Même `room_idx` + même seed session = même salle (layout + population identiques).
La seed session vient du RTC (`set_rtc_seed()`) ou d'une valeur fixe (`set_seed()`).

### Sortie murale (DGN_EXIT_*)

Chaque salle peut avoir 0..4 sorties (N/S/E/W). Les positions d'ouverture sont
exposées dans `ngpc_dgroom.door_col_lo/hi` (ouvertures N/S) et
`door_row_lo/hi` (ouvertures E/W) en métatiles. La navigation entre salles est
à la charge du code appelant.

---

## Pipeline NgpCraft Engine → code C

### 1. Onglet Procgen Assets (projet)

Configure le tileset et les pools une seule fois pour tout le projet :

| Champ | Description |
|---|---|
| Tileset PNG | PNG source découpé en cellules de taille uniforme |
| Taille cellule source | 8×8 / 16×16 / 32×32 px — taille d'une cellule dans le PNG |
| Tile Roles (26) | Index cellule PNG pour chaque rôle (floor, murs, coins, eau…) |
| Pool Ennemis | Entités chargées en VRAM pour les ennemis (entity_id, poids, max/salle) |
| Pool Items | Entités chargées en VRAM pour les items (entity_id, poids, max/salle) |

Génère : `tiles_procgen.h/c` + `sprites_lab.h/c`

### 2. Onglet DungeonGen (scène)

Configure les paramètres runtime (fréquences, tailles, difficulté) qui génèrent
`dungeongen_config.h`. Voir section [Paramètres de configuration](#paramètres-de-configuration).

### 3. Inclusion dans le code C

```c
/* OBLIGATOIRE : inclure AVANT le module */
#include "dungeongen_config.h"
#include "ngpc_dungeongen/ngpc_dungeongen.h"
```

---

## API complète

### Initialisation

```c
/* Seed de session depuis le RTC (une fois au boot — seed différente à chaque run) */
void ngpc_dungeongen_set_rtc_seed(void);

/* Seed manuelle (debug, rejouabilité, saisie joueur) — seed=0 normalisé en 1 */
void ngpc_dungeongen_set_seed(u16 seed);

/* Charge tiles_procgen + sprites_lab en VRAM, configure palettes SCR1 + sprites.
   Appeler après ngpc_init() et before enter(). */
void ngpc_dungeongen_init(void);
```

### Par salle

```c
/* Génère et dessine la salle sur GFX_SCR1.
   room_idx : 0..65534 — reproductible (même seed → même salle)
   style_idx : 0..DUNGEONGEN_N_STYLES-1 pour forcer un style, 0xFF = auto */
void ngpc_dungeongen_enter(u16 room_idx, u8 style_idx);

/* Définit le type de salle dans le modèle cluster (APRÈS enter()).
   room_type : DGEN_ROOM_ENTRY / DGEN_ROOM_NODE / DGEN_ROOM_LEAF
   avec_escalier : 1 = placer escalier automatiquement si LEAF */
void ngpc_dungeongen_set_room_type(u8 room_type, u8 avec_escalier);

/* Spawne ennemis + item depuis les pools VRAM. Appeler après enter() + set_room_type(). */
void ngpc_dungeongen_spawn(void);
```

### Chaque frame

```c
/* Synchronise positions sprites selon la caméra. Appeler après mise à jour caméra. */
void ngpc_dungeongen_sync_sprites(u8 cam_x, u8 cam_y);
```

### Collision

```c
/* Collision à (mx, my) en métatiles. Recalcul à la volée, sans carte RAM.
   Returns: DGNCOL_PASS | DGNCOL_SOLID | DGNCOL_WATER | DGNCOL_VOID | DGNCOL_TRIGGER */
u8 ngpc_dungeongen_collision_at(u8 mx, u8 my);
```

| Valeur | Signification |
|---|---|
| `DGNCOL_PASS` | Sol libre, traversable |
| `DGNCOL_SOLID` | Mur (extérieur ou intérieur) |
| `DGNCOL_WATER` | Eau (comportement défini par `DUNGEONGEN_WATER_COL`) |
| `DGNCOL_VOID` | Fosse — mort ou dommages |
| `DGNCOL_TRIGGER` | Escalier — transition de niveau |

### Navigation et utilitaires

```c
/* Nombre de styles disponibles (= DUNGEONGEN_N_STYLES) */
u8 ngpc_dungeongen_n_styles(void);

/* Style correspondant à un bitmask de sorties (pour ngpc_cluster) */
u8 ngpc_dungeongen_style_for_exits(u8 exits_mask);

/* Seed reproductible pour la salle — décorrélé du RNG interne.
   Utile pour IA déterministe ou événements propres à chaque salle. */
u16 ngpc_dungeongen_room_seed(u16 room_idx);
```

### Tiers de difficulté

```c
#if DUNGEONGEN_TIER_COLS > 0
/* Avance le tier (0..TIER_COLS-1). Appeler après boss/floor/changement de zone. */
void ngpc_dungeongen_set_tier(u8 tier);

/* Retourne le tier courant */
u8   ngpc_dungeongen_get_tier(void);
#endif
```

---

## Structure NgpcDungeonRoom

```c
extern NgpcDungeonRoom ngpc_dgroom;  /* mis à jour par enter() puis spawn() */

/* Géométrie */
u8  room_w        /* largeur en métatiles */
u8  room_h        /* hauteur en métatiles */
u8  exits         /* bitmask DGN_EXIT_N | DGN_EXIT_S | DGN_EXIT_E | DGN_EXIT_W */
u8  style_idx     /* index style sélectionné (0..DUNGEONGEN_N_STYLES-1) */
u8  door_col_lo   /* première colonne métatile ouverture N/S */
u8  door_col_hi   /* dernière colonne métatile ouverture N/S */
u8  door_row_lo   /* première rangée métatile ouverture E/W */
u8  door_row_hi   /* dernière rangée métatile ouverture E/W */
s16 scroll_max_x  /* scroll max horizontal pixels (0 si salle ≤ écran) */
s16 scroll_max_y  /* scroll max vertical pixels */

/* Population */
u8  has_water     /* 1 si bande d'eau présente */
u8  is_safe_room  /* 1 si salle safe (0 ennemi, item garanti) */

/* Cluster */
u8  room_type     /* DGEN_ROOM_ENTRY / NODE / LEAF */
u8  has_stair     /* 1 si escalier présent */
u8  stair_mx      /* position X escalier en métatiles (valide si has_stair) */
u8  stair_my      /* position Y escalier en métatiles */

/* Entités (après spawn) */
u8  enemy_count   /* ennemis spawnés */
u8  item_active   /* 1 si item présent */
```

---

## Paramètres de configuration

Tous injectables via `dungeongen_config.h` (généré par l'engine) ou `-D` en Makefile.
Chaque `#define` est protégé par `#ifndef` — les valeurs par défaut s'appliquent
si non surchargées.

### Sol
| Define | Défaut | Description |
|---|---|---|
| `DUNGEONGEN_GROUND_PCT_1` | 70 | % tile sol variante 1 (somme 1+2+3 = 100) |
| `DUNGEONGEN_GROUND_PCT_2` | 20 | % tile sol variante 2 |
| `DUNGEONGEN_GROUND_PCT_3` | 10 | % tile sol variante 3 |

### Population
| Define | Défaut | Description |
|---|---|---|
| `DUNGEONGEN_EAU_FREQ` | 40 | % eau par salle (salles ≤ 2 sorties) |
| `DUNGEONGEN_VIDE_FREQ` | 30 | % fosse par salle |
| `DUNGEONGEN_VIDE_MARGIN` | 3 | Marge métatiles autour des sorties (sans fosse) |
| `DUNGEONGEN_TONNEAU_FREQ` | 50 | % tonneau par salle |
| `DUNGEONGEN_TONNEAU_MAX` | 2 | Max tonneaux (1 ou 2) |
| `DUNGEONGEN_ESCALIER_FREQ` | 0 | % escalier auto (sinon via set_room_type) |
| `DUNGEONGEN_WATER_COL` | `DGNCOL_WATER` | Valeur de collision de l'eau (`DGNCOL_SOLID` = infranchissable) |

### Entités
| Define | Défaut | Description |
|---|---|---|
| `DUNGEONGEN_ENEMY_MIN` | 0 | Min ennemis par salle |
| `DUNGEONGEN_ENEMY_MAX` | 3 | Max ennemis par salle (plafond absolu) |
| `DUNGEONGEN_ENEMY_DENSITY` | 16 | Métatiles par ennemi (scaling taille salle) |
| `DUNGEONGEN_ENE2_PCT` | 50 | % chance ennemi ENE2 (8×8) vs ENE1 (16×16) |
| `DUNGEONGEN_ITEM_FREQ` | 50 | % item par salle (0 = désactivé) |

### Navigation
| Define | Défaut | Description |
|---|---|---|
| `DUNGEONGEN_N_ROOMS` | 0 | Nombre salles avant boss — info code jeu uniquement |
| `DUNGEONGEN_CLUSTER_SIZE_MAX` | 4 | Profondeur max arbre cluster (2..4) |

### Difficulté progressive
| Define | Défaut | Description |
|---|---|---|
| `DUNGEONGEN_ENEMY_RAMP_ROOMS` | 0 | +1 ennemi max tous les N rooms (0 = off) |
| `DUNGEONGEN_SAFE_ROOM_EVERY` | 0 | Salle safe toutes les N rooms (0 = off) |
| `DUNGEONGEN_MIN_EXITS` | 0 | Nombre minimum de sorties par salle |

### Taille des salles
| Define | Défaut | Description |
|---|---|---|
| `DUNGEONGEN_ROOM_MW_MIN` | 10 | Largeur min en métatiles |
| `DUNGEONGEN_ROOM_MW_MAX` | 16 | Largeur max en métatiles |
| `DUNGEONGEN_ROOM_MH_MIN` | 10 | Hauteur min en métatiles |
| `DUNGEONGEN_ROOM_MH_MAX` | 16 | Hauteur max en métatiles |
| `DUNGEONGEN_MAX_EXITS` | 4 | Nombre max de sorties (0..4) |
| `DUNGEONGEN_CELL_W_TILES` | 2 | Largeur d'une cellule en tiles NGPC (1/2/4) |
| `DUNGEONGEN_CELL_H_TILES` | 2 | Hauteur d'une cellule en tiles NGPC (1/2/4) |

### Tiers de difficulté
| Define | Défaut | Description |
|---|---|---|
| `DUNGEONGEN_TIER_COLS` | 0 | Nombre de tiers (0 = désactivé) |
| `DUNGEONGEN_TIER_ENE_MAX` | — | Tableau : max ennemis par tier |
| `DUNGEONGEN_TIER_ITEM_FREQ` | — | Tableau : fréquence item par tier |
| `DUNGEONGEN_TIER_EAU_FREQ` | — | Tableau : fréquence eau par tier |
| `DUNGEONGEN_TIER_VIDE_FREQ` | — | Tableau : fréquence fosse par tier |

---

## Exemple complet

```c
#include "dungeongen_config.h"          /* OBLIGATOIRE avant le module */
#include "ngpc_dungeongen/ngpc_dungeongen.h"

static u16  g_room_idx = 0u;
static u8   g_cam_x = 0u, g_cam_y = 0u;
static u8   g_px, g_py;

/* ---- Init ---- */
void game_init(void)
{
    ngpc_dungeongen_set_rtc_seed();    /* seed RTC — session unique */
    ngpc_dungeongen_init();            /* VRAM + palettes */

    ngpc_dungeongen_enter(0u, 0xFFu); /* salle 0, style auto */
    ngpc_dungeongen_set_room_type(DGEN_ROOM_ENTRY, 0u);
    ngpc_dungeongen_spawn();           /* ennemis + item */

    /* Position de départ : centre de la salle */
    g_px = (u8)(ngpc_dgroom.room_w * DUNGEONGEN_CELL_W_TILES * 4u);
    g_py = (u8)(ngpc_dgroom.room_h * DUNGEONGEN_CELL_H_TILES * 4u);
}

/* ---- Update (chaque frame) ---- */
void game_update(void)
{
    u8 new_px = g_px, new_py = g_py;
    s16 cx, cy;

    /* Déplacer new_px/new_py via le pad... */

    /* Collision en métatiles */
    {
        u8 mx  = (u8)(new_px / (DUNGEONGEN_CELL_W_TILES * 8u));
        u8 my  = (u8)(new_py / (DUNGEONGEN_CELL_H_TILES * 8u));
        u8 col = ngpc_dungeongen_collision_at(mx, my);

        if (col == DGNCOL_SOLID)   { new_px = g_px; new_py = g_py; }
        if (col == DGNCOL_VOID)    { /* mort joueur */ }
        if (col == DGNCOL_TRIGGER) {
            /* Escalier → salle suivante */
            g_room_idx++;
            ngpc_dungeongen_enter(g_room_idx, 0xFFu);
            ngpc_dungeongen_set_room_type(DGEN_ROOM_NODE, 0u);
            ngpc_dungeongen_spawn();
        }
    }
    g_px = new_px; g_py = new_py;

    /* Transition murale Nord */
    if (g_py < (u8)(DUNGEONGEN_CELL_H_TILES * 8u)
        && (ngpc_dgroom.exits & DGN_EXIT_N))
    {
        u8 door_x = (u8)(ngpc_dgroom.door_col_lo * DUNGEONGEN_CELL_W_TILES * 8u);
        u8 door_w = (u8)((ngpc_dgroom.door_col_hi - ngpc_dgroom.door_col_lo + 1u)
                         * DUNGEONGEN_CELL_W_TILES * 8u);
        if (g_px >= door_x && g_px < (u8)(door_x + door_w)) {
            g_room_idx++;
            ngpc_dungeongen_enter(g_room_idx, 0xFFu);
            ngpc_dungeongen_spawn();
            /* Spawn côté Sud de la nouvelle salle */
            g_py = (u8)((ngpc_dgroom.room_h - 2u) * DUNGEONGEN_CELL_H_TILES * 8u);
        }
    }

    /* Caméra clampée aux scroll_max */
    cx = (s16)g_px - 80;
    cy = (s16)g_py - 76;
    if (cx < 0) cx = 0;
    if (cy < 0) cy = 0;
    if (cx > ngpc_dgroom.scroll_max_x) cx = ngpc_dgroom.scroll_max_x;
    if (cy > ngpc_dgroom.scroll_max_y) cy = ngpc_dgroom.scroll_max_y;
    g_cam_x = (u8)cx;
    g_cam_y = (u8)cy;
    ngpc_gfx_scroll(GFX_SCR1, g_cam_x, g_cam_y);

    /* Sync sprites */
    ngpc_dungeongen_sync_sprites(g_cam_x, g_cam_y);
}
```

---

## Multi-floors (tiers)

```c
/* Après un boss ou un escalier de fin de floor */
void next_floor(void)
{
    u8 current_tier = ngpc_dungeongen_get_tier();
    if (current_tier < DUNGEONGEN_TIER_COLS - 1u)
        ngpc_dungeongen_set_tier((u8)(current_tier + 1u));

    g_room_idx = 0u;
    ngpc_dungeongen_enter(g_room_idx, 0xFFu);
    ngpc_dungeongen_set_room_type(DGEN_ROOM_ENTRY, 0u);
    ngpc_dungeongen_spawn();
}
```

---

## Notes de performance

- `collision_at()` recalcule depuis l'état interne — pas de carte de collision en RAM.
  Appel O(1), sûr chaque frame.
- `sync_sprites()` parcourt `ENE_MAX + 1` entités — constant, budget prévisible.
- `enter()` efface et redessine toute la tilemap GFX_SCR1 → appeler uniquement
  à la transition de salle, pas dans la boucle principale.
- Tileset ROM (tiles_procgen) lu via pointeurs FAR — pas de copie en RAM.

---

## Budget RAM

| Donnée | Taille |
|---|---|
| `NgpcDungeonRoom` (ngpc_dgroom) | ~28 octets |
| État interne générateur | ~80 octets |
| Positions sprites (ENE_MAX + 1 items) | 4 × (ENE_MAX + 1) octets |
| **Total indicatif** | **~120–160 octets** |

Aucune carte de collision ni tilemap de collision en RAM.

---

## Voir aussi

- `optional/ngpc_procgen/README.md` — navigation arborescente room-by-room
- `optional/ngpc_cavegen/README.md` — cave ouverte scrollante
- `optional/ngpc_cavegen/ngpc_cavegen_example.c` — démo jouable des 3 modes
