# ngpc_procgen — Générateur de donjons procéduraux (Dicing Knight style)

**Statut : ✅ Validé** (2026-03-15)

Génère un donjon room-by-room sur une grille 4×4, avec transitions de portes,
contenu procédural (ennemis / items) et injection de boucles pour casser
la monotonie du DFS pur.

**Dépend de :** `optional/ngpc_rng/`
**RAM jeu :** 136 octets (ProcgenMap + ProcgenContent×16)

**Makefile :**
```makefile
OBJS += src/optional/ngpc_rng/ngpc_rng.rel
OBJS += src/optional/ngpc_procgen/ngpc_procgen.rel
```

---

## Architecture

```
optional/ngpc_procgen/
├── ngpc_procgen.h        — structures, API publique
├── ngpc_procgen.c        — DFS + inject_loops + gen_content
└── ngpc_procgen_rooms.h  — pool 48 templates + fill_room() (single-header)
```

---

## Concepts clés

### Grille de rooms

Le donjon est une grille **PROCGEN_GRID_W × PROCGEN_GRID_H** (défaut 4×4 = 16 cellules max).
Chaque cellule active = un écran NGPC complet (20×19 tiles).

```
+---+---+---+---+
| S |   | . |   |   S = start      @ = joueur actuel
+---+---+---+---+   . = visitée    X = exit (boss)
|   | @ |===|   |   = = boucle     ? = non visitée
+---+---+---+---+
|   | . | X |   |
+---+---+---+---+
```

Les transitions se font via des **portes** (N/S/W/E) dessinées sur les bords de l'écran.

### Algorithme de génération

```
1. DFS depuis cellule 0,0 → arbre couvrant connexe
2. BFS → room la plus lointaine du start = EXIT (boss)
3. Assignation templates (exits_mask → template compatible aléatoire)
4. [generate_ex] Injection de boucles :
   → paires adjacentes non-connectées, chacune a loop_pct% de connexion
   → re-assignation templates (les exits ont changé)
```

**Effet du `loop_pct` :**

| loop_pct | Résultat |
|---|---|
| 0 | Labyrinthe parfait — 1 seul chemin vers chaque room |
| 15 | Quelques raccourcis, moins frustrant |
| **20** | **Recommandé — bon équilibre variété / lisibilité** |
| 30 | Donjon très ouvert |
| 50+ | Presque toutes les rooms interconnectées |

---

## API complète

### Génération du donjon

```c
/* Recommandé (avec boucles optionnelles) */
void ngpc_procgen_generate_ex(
    ProcgenMap                    *map,
    const NgpcRoomTemplate NGP_FAR *templates,
    u8                             tpl_count,
    u16                            seed,
    u8                             loop_pct   /* 0=aucune boucle, 20=recommandé */
);

/* Compatibilité ascendante (= generate_ex avec loop_pct=0) */
void ngpc_procgen_generate(
    ProcgenMap *map, const NgpcRoomTemplate NGP_FAR *templates,
    u8 tpl_count, u16 seed
);
```

### Contenu procédural

```c
typedef struct {
    u8 enemies; /* bitmask types ennemis (jeu-défini : bit0=slime, bit1=archer…) */
    u8 items;   /* bitmask objets (bit0=clé, bit1=potion, bit2=épée…) */
    u8 count;   /* nombre d'ennemis à spawner dans cette room */
    u8 special; /* 0=rien  1=boss  2=shop  3=secret */
} ProcgenContent;

void ngpc_procgen_gen_content(
    const ProcgenMap *map,
    ProcgenContent   *content,     /* tableau [PROCGEN_MAX_ROOMS] fourni par l'appelant */
    u8                max_enemies, /* max ennemis par room NORMAL (recommandé : 2..4) */
    u8                item_chance  /* % chance item dans room NORMAL (recommandé : 30..50) */
);
```

Règles appliquées automatiquement :

| Room type | enemies | items | count | special |
|---|---|---|---|---|
| START | 0 | 0 | 0 | 0 |
| NORMAL | aléatoire | aléatoire | 1..max | 0 |
| EXIT | 0xFF | 0 | max | **1** (boss) |
| SHOP | 0 | 0xFF | 0 | **2** (shop) |
| SECRET | 1 type | 0xFF | 1 | **3** (secret) |

### Navigation

```c
/* Index du voisin (0xFF = PROCGEN_IDX_NONE si pas de porte ou hors grille) */
u8 ngpc_procgen_neighbor(const ProcgenMap *map, u8 room_idx, u8 dir);

/* Position tile du joueur selon la porte d'entrée */
void ngpc_procgen_spawn_pos(u8 entry_dir, u8 *out_x, u8 *out_y);

/* Charger une room (marque VISITED, déclenche le callback de rendu) */
void ngpc_procgen_load_room(ProcgenMap *map, u8 idx,
    const NgpcRoomTemplate NGP_FAR *templates,
    ProcgenLoadFn load_fn, u8 entry_dir, void *userdata);

/* Seed 16-bit unique et reproductible par room (pour spawner de façon déterministe) */
u16 ngpc_procgen_room_seed(const ProcgenMap *map, u8 room_idx);
```

### Flags de runtime (modifiés par le jeu)

```c
PROCGEN_FLAG_VISITED  /* room déjà visitée → ne pas re-spawner les ennemis */
PROCGEN_FLAG_CLEARED  /* tous ennemis vaincus → peut débloquer porte boss */
PROCGEN_FLAG_LOCKED   /* portes verrouillées (combat en cours) */
```

---

## Pool de templates — `ngpc_procgen_rooms.h`

**48 templates** (3 variantes × 16 configurations d'exits).

### Variantes

| ID | Nom | Description | Tiles utilisés |
|---|---|---|---|
| 0 | `ROOM_VAR_PLAIN` | Room vide — sol dégagé | wall + floor |
| 1 | `ROOM_VAR_PILLARS` | 4 piliers symétriques | wall + floor + **deco** |
| 2 | `ROOM_VAR_DIVIDED` | Mur horizontal partiel avec passage central | wall + floor + **deco** |

```
PLAIN              PILLARS            DIVIDED
####################  ####################  ####################
#                  #  #                  #  #                  #
#                  #  #  [P]      [P]   #  #                  #
#                  #  #                  #  ######  ####  ######
#                  #  #                  #  #                  #
#                  #  #  [P]      [P]   #  #                  #
####################  ####################  ####################
```

### Activation

```c
/* Dans UN SEUL .c de ton projet */
#define PROCGEN_ROOMS_IMPL
#include "ngpc_procgen/ngpc_procgen_rooms.h"

/* Dans les autres .c (lecture seule) */
#include "ngpc_procgen/ngpc_procgen_rooms.h"
```

### Rendu

```c
/* Dans ton callback ProcgenLoadFn : */
void my_room_load(const ProcgenCell *cell, const NgpcRoomTemplate NGP_FAR *tpl,
                  u8 entry_dir, void *ud)
{
    ngpc_procgen_fill_room(cell, tpl,
                           TILE_WALL,    /* mur périmètre */
                           TILE_FLOOR,   /* sol intérieur */
                           TILE_PILLAR,  /* piliers / mur diviseur */
                           0u);          /* palette BG */
}
```

### Ajouter tes propres variantes

```c
/* 1. Dans g_procgen_rooms[] → ajouter des entrées avec variant > 2 */
{ PROCGEN_EXIT_N | PROCGEN_EXIT_S, 3u },  /* couloir + coffre central */

/* 2. Dans ngpc_procgen_fill_room() */
} else if (tpl->variant == 3u) {
    ngpc_gfx_put_tile(GFX_SCR1, 10u, 9u, TILE_CHEST, pal);
}

/* 3. Mettre à jour PROCGEN_ROOMS_COUNT */
#define PROCGEN_ROOMS_COUNT  50u  /* 48 + 2 nouvelles */
```

---

## Exemple complet

```c
/* ---- Données globales ---- */
static ProcgenMap     g_dungeon;
static ProcgenContent g_content[PROCGEN_MAX_ROOMS];
static u8 g_px, g_py;

/* ---- Callback de rendu ---- */
static void room_load_cb(const ProcgenCell *cell,
                         const NgpcRoomTemplate NGP_FAR *tpl,
                         u8 entry_dir, void *ud)
{
    u8 idx = g_dungeon.current_idx;
    (void)ud; (void)entry_dir;

    ngpc_procgen_fill_room(cell, tpl, TILE_WALL, TILE_FLOOR, TILE_PILLAR, 0u);

    if (!(cell->flags & PROCGEN_FLAG_VISITED)) {
        /* Première visite : spawner ennemis selon g_content[idx] */
        u8 n = g_content[idx].count;
        u8 boss = (g_content[idx].special == 1u);
        /* ton spawn_enemy(n, boss) ici */
        (void)n; (void)boss;
    }

    if (g_content[idx].items != 0u && !(cell->flags & PROCGEN_FLAG_CLEARED)) {
        ngpc_gfx_put_tile(GFX_SCR1, 10u, 9u, TILE_CHEST, 0u);
    }
}

/* ---- Initialisation ---- */
void level_init(u16 seed)
{
    ngpc_procgen_generate_ex(&g_dungeon,
                             g_procgen_rooms, PROCGEN_ROOMS_COUNT,
                             seed, 20u);                /* 20% boucles */

    ngpc_procgen_gen_content(&g_dungeon, g_content, 3u, 40u);

    ngpc_procgen_load_room(&g_dungeon, g_dungeon.start_idx,
                           g_procgen_rooms, room_load_cb, 0xFFu, 0);
    ngpc_procgen_spawn_pos(0xFFu, &g_px, &g_py);
}

/* ---- Update (chaque frame) ---- */
void level_update(void)
{
    u8 cur = g_dungeon.current_idx;
    u8 dir = 0xFFu;
    u8 next;

    /* Déplacement joueur → mettre à jour g_px, g_py */

    /* Détection transition */
    if      (g_py == 0u  && (g_dungeon.cells[cur].exits & PROCGEN_EXIT_N)) dir = PROCGEN_DIR_N;
    else if (g_py == 18u && (g_dungeon.cells[cur].exits & PROCGEN_EXIT_S)) dir = PROCGEN_DIR_S;
    else if (g_px == 0u  && (g_dungeon.cells[cur].exits & PROCGEN_EXIT_W)) dir = PROCGEN_DIR_W;
    else if (g_px == 19u && (g_dungeon.cells[cur].exits & PROCGEN_EXIT_E)) dir = PROCGEN_DIR_E;

    if (dir != 0xFFu) {
        next = ngpc_procgen_neighbor(&g_dungeon, cur, dir);
        if (next != PROCGEN_IDX_NONE) {
            ngpc_procgen_load_room(&g_dungeon, next,
                                   g_procgen_rooms, room_load_cb, dir, 0);
            ngpc_procgen_spawn_pos(dir, &g_px, &g_py);
        }
    }
}
```

---

## Budget RAM / ROM

| Donnée | Taille | Emplacement |
|---|---|---|
| `ProcgenMap` | 72 octets | RAM (BSS ou global) |
| `ProcgenContent[16]` | 64 octets | RAM (BSS ou global) |
| `g_procgen_rooms[48]` | 96 octets | ROM (far) |
| Stack DFS interne | 16 octets max | Stack (temporaire) |
| **Total RAM** | **136 octets** | |

---

---

## Patron alternatif — shoot'em up / niveau infini

`ngpc_procgen` est conçu pour des jeux **room-by-room** (RPG, roguelite, dungeon crawler).
Pour un genre **sans rooms** (shooter, shmup, runner), un director de spawn léger suffit
et ne nécessite pas le module complet.

### Pattern validé : director de difficulté par tiers

Utilisé dans `Shmup_StarGunner` niveau 3 infini (validé 2026-03-15) :

```c
/* Dépend uniquement de ngpc_qrandom() — disponible dans le core (ngpc_math.c). */
typedef struct { u8 wave_interval_fr; u8 min_count; u8 max_count; u8 ast_chance; } InfTier;

static const InfTier s_inf_tiers[5] = {
    /* tier 0 (waves  1-10): warm-up  */ { 180u, 3u, 5u,  0u },
    /* tier 1 (waves 11-20): medium   */ { 150u, 4u, 6u, 20u },
    /* tier 2 (waves 21-30): harder   */ { 120u, 4u, 7u, 35u },
    /* tier 3 (waves 31-40): combos   */ { 100u, 5u, 7u, 55u },
    /* tier 4 (waves 41+  ): intense  */ {  80u, 5u, 8u, 70u },
};

static void shmup_inf_update(void)
{
    if (s_inf_wave_timer > 0u) { s_inf_wave_timer--; return; }
    if (s_wave_remaining != 0u) return;   /* attendre fin de spawn */

    u8 tier = (u8)(s_inf_wave_count / 10u);
    if (tier >= 5u) tier = 4u;
    const InfTier *t = &s_inf_tiers[tier];

    u8 etype = (u8)(1u + (ngpc_qrandom() % 4u));  /* type ennemi aléatoire */
    u8 count = (u8)(t->min_count + (ngpc_qrandom() % (u8)(t->max_count - t->min_count + 1u)));
    u8 cy    = (u8)(8u + (ngpc_qrandom() % (u8)(PLAYFIELD_H_PX - 24u)));

    stage_start_wave(etype, count, 8u, cy);
    s_inf_wave_count++;

    /* Tier 1+ : combo astéroïde aléatoire */
    if (t->ast_chance > 0u && (ngpc_qrandom() % 100u) < t->ast_chance)
        s_inf_ast_pending = 20u;

    s_inf_wave_timer = t->wave_interval_fr;
}
```

**Règles clés du pattern :**
- Compter les vagues (`s_inf_wave_count`) → calculer le tier en divisant par 10
- `ngpc_qrandom()` (table de 256 entrées, 0 cycle PRNG) pour type/count/position
- Timer en frames entre vagues (pas en pixels-scroll comme `stage.c`)
- Garder le boss désactivé : `if (s_current_level != SHMUP_LEVEL_INF) boss1_spawn();`
- Drops : `if ((ngpc_qrandom() % 20u) < 9u) return;` → 55% drop rate

---

## Voir aussi

- `optional/ngpc_cavegen/` — cave procédurale style Cave Noir (scrolling 32×32)
- `optional/ngpc_rng/` — PRNG xorshift16 reproductible
- `ngpc_cavegen_example.c` — démonstration des deux modes (donjon + cave)
- `Shmup_StarGunner/src/game/shmup.c` → `shmup_inf_update()` — director infini validé
