# ngpc_cavegen — Générateur de caves procédurales (Cave Noir style)

Génère une cave 32×32 tiles par automate cellulaire. La map entière est créée
en début de partie ; le joueur s'y déplace librement avec scrolling.

**Dépend de :** `optional/ngpc_rng/`
**RAM jeu :** 1412 octets (NgpcCaveMap 1032 + viewport[380])

**Makefile :**
```makefile
OBJS += src/optional/ngpc_rng/ngpc_rng.rel
OBJS += src/optional/ngpc_cavegen/ngpc_cavegen.rel
```

---

## Architecture

```
optional/ngpc_cavegen/
├── ngpc_cavegen.h              — structures, API publique
├── ngpc_cavegen.c              — algorithme complet
└── ngpc_cavegen_example.c      — démo jouable (+ exemple donjon)
```

---

## Algorithme en 4 passes

```
PASS 1 — Remplissage aléatoire
   Chaque tile intérieur → CAVE_WALL avec probabilité wall_pct/100.
   Bordures toujours CAVE_WALL.

PASS 2 — Lissage × 5 (automate de Moore 5/4)
   Pour chaque tile :
     si voisins_mur(8-connexe) >= 5 → CAVE_WALL
     sinon                           → CAVE_FLOOR
   In-place (pas de double-buffer) → légère dérive organique.

PASS 3 — Connexité (flood-fill itératif)
   Depuis le tile CAVE_FLOOR le plus proche du centre :
     marquer tout CAVE_FLOOR connexe → enlever les îlots isolés.

PASS 4 — Placement des entités
   Entrée  : premier CAVE_FLOOR dans le tiers gauche  (x < 11)
   Sortie  : premier CAVE_FLOOR dans le tiers droit   (x > 21)
   Ennemis + Coffres : 1 par section 8×8 (grille 4×4), distance min. entrée
```

---

## Paramètres de génération

| `wall_pct` | Résultat |
|---|---|
| 40 | Cave très ouverte, peu de murs, grandes salles |
| **47** | **Recommandé — caverne naturelle équilibrée** |
| 52 | Cave étroite, couloirs, nombreux cul-de-sac |
| 55+ | Très peu de sol, passages rares |

---

## Structures

```c
/* Types de tiles retournés dans la map */
#define CAVE_WALL    0u   /* mur solide */
#define CAVE_FLOOR   1u   /* sol passable */
#define CAVE_ENTRY   2u   /* spawn joueur */
#define CAVE_EXIT    3u   /* sortie du niveau */
#define CAVE_CHEST   4u   /* coffre / objet */
#define CAVE_ENEMY   5u   /* spawn ennemi */

typedef struct {
    u8  map[32 * 32];  /* 1024 octets — CAVE_* par tile */
    u8  entry_x, entry_y;
    u8  exit_x,  exit_y;
    u8  enemy_count;   /* ennemis réellement placés */
    u8  chest_count;   /* coffres réellement placés */
    u16 seed;
} NgpcCaveMap;         /* 1032 octets total */
```

---

## API

```c
/* Génération complète */
void ngpc_cavegen_generate(
    NgpcCaveMap *out,
    u16          seed,
    u8           wall_pct,    /* densité murs 0..100 (recommandé : 47) */
    u8           max_enemies, /* max ennemis placés  (recommandé : 6..12) */
    u8           max_chests   /* max coffres placés  (recommandé : 2..5)  */
);

/* Extraction d'une fenêtre 20×19 pour l'affichage NGPC */
void ngpc_cavegen_viewport(
    const NgpcCaveMap *m,
    u8                 cam_x,    /* colonne gauche (0..12) */
    u8                 cam_y,    /* rangée haute   (0..13) */
    u8                *out       /* out[20*19] = CAVE_* */
);

/* Caméra centrée sur le joueur (clampée aux bornes) */
void ngpc_cavegen_cam_center(u8 px, u8 py, u8 *cam_x, u8 *cam_y);
```

---

## Intégration dans un jeu

### Init

```c
static NgpcCaveMap g_cave;
static u8 g_view[20 * 19];
static u8 g_px, g_py;
static u8 g_cam_x, g_cam_y;

void cave_init(u16 seed)
{
    ngpc_cavegen_generate(&g_cave, seed, 47u, 8u, 3u);

    g_px = g_cave.entry_x;
    g_py = g_cave.entry_y;
    ngpc_cavegen_cam_center(g_px, g_py, &g_cam_x, &g_cam_y);

    ngpc_cavegen_viewport(&g_cave, g_cam_x, g_cam_y, g_view);
    cave_render();  /* → écrire g_view dans VRAM */
}
```

### Rendu

```c
/* Correspondance CAVE_* → tile NGPC (à adapter avec tes assets) */
static const u16 s_tiles[6] = {
    TILE_WALL, TILE_FLOOR, TILE_FLOOR, TILE_EXIT, TILE_CHEST, TILE_ENEMY
};

void cave_render(void)
{
    u8 x, y;
    for (y = 0u; y < 19u; y++) {
        for (x = 0u; x < 20u; x++) {
            u8 t = g_view[(u16)y * 20u + x];
            ngpc_gfx_put_tile(GFX_SCR1, x, y, s_tiles[t < 6u ? t : 0u], 0u);
        }
    }
}
```

### Update (chaque frame)

```c
void cave_update(void)
{
    u8 new_px = g_px, new_py = g_py;
    u8 tile;
    u8 new_cam_x, new_cam_y;

    /* Déplacement */
    if (ngpc_pad_pressed & PAD_LEFT)  new_px--;
    if (ngpc_pad_pressed & PAD_RIGHT) new_px++;
    if (ngpc_pad_pressed & PAD_UP)    new_py--;
    if (ngpc_pad_pressed & PAD_DOWN)  new_py++;

    /* Collision tilemap */
    tile = g_cave.map[(u16)new_py * CAVEGEN_W + new_px];
    if (tile == CAVE_WALL) { new_px = g_px; new_py = g_py; }

    /* Collecte / sortie */
    if (tile == CAVE_CHEST) {
        g_cave.map[(u16)new_py * CAVEGEN_W + new_px] = CAVE_FLOOR;
        /* déclencher collecte */
    } else if (tile == CAVE_EXIT) {
        /* → niveau suivant */
    }

    g_px = new_px;
    g_py = new_py;

    /* Scrolling */
    ngpc_cavegen_cam_center(g_px, g_py, &new_cam_x, &new_cam_y);
    if (new_cam_x != g_cam_x || new_cam_y != g_cam_y) {
        g_cam_x = new_cam_x; g_cam_y = new_cam_y;
        ngpc_cavegen_viewport(&g_cave, g_cam_x, g_cam_y, g_view);
        cave_render();
    }

    /* Afficher le joueur (position relative dans le viewport) */
    ngpc_gfx_put_tile(GFX_SCR1,
                      (u8)(g_px - g_cam_x),
                      (u8)(g_py - g_cam_y),
                      TILE_PLAYER, 0u);
}
```

### Fog of war (optionnel)

```c
/* Tableau de visibilité 32×32 = 1024 octets supplémentaires */
static u8 g_fog[CAVEGEN_W * CAVEGEN_H];

void cave_reveal_area(u8 px, u8 py, u8 radius) {
    u8 x, y, dx, dy;
    for (y = (u8)(py >= radius ? py-radius : 0u);
         y <= (u8)(py+radius < CAVEGEN_H ? py+radius : CAVEGEN_H-1u); y++) {
        for (x = (u8)(px >= radius ? px-radius : 0u);
             x <= (u8)(px+radius < CAVEGEN_W ? px+radius : CAVEGEN_W-1u); x++) {
            dx = (x > px) ? (u8)(x-px) : (u8)(px-x);
            dy = (y > py) ? (u8)(y-py) : (u8)(py-y);
            if ((u8)(dx+dy) <= radius) g_fog[(u16)y*CAVEGEN_W+x] = 1u;
        }
    }
}
/* Dans cave_render() : si g_fog[map_y*32+map_x]==0 → tile_wall au lieu du vrai tile */
```

---

## Plusieurs niveaux / floors

```c
u16 g_seed = 0xCAFEu;

void next_floor(void)
{
    g_seed = (u16)(g_seed * 0x6C07u + 0x3925u); /* LCG simple */
    cave_init(g_seed);
    /* Le joueur repart de g_cave.entry_x/y */
}
```

---

## Budget RAM

| Donnée | Taille | Note |
|---|---|---|
| `NgpcCaveMap.map` | 1024 octets | Map 32×32 |
| `NgpcCaveMap` header | 8 octets | Positions + compteurs |
| Viewport `u8[380]` | 380 octets | 20×19, re-calculé au scroll |
| Fog of war (optionnel) | 1024 octets | +1KB si activé |
| **Total sans fog** | **1412 octets** | ~16% des 9KB disponibles |
| **Total avec fog** | **2436 octets** | ~27% |

---

## Notes hardware

- La grille 32×32 correspond exactement à la limite hardware NGPC des tilemaps BG (32×32).
- `ngpc_cavegen_viewport()` extrait 20×19 tiles depuis la map 32×32.
- Pour un scrolling fluide, écrire le viewport en VBlank via `ngpc_vramq` plutôt que tile par tile.
- L'entrée est toujours côté gauche, la sortie côté droit → le joueur progresse naturellement de gauche à droite.

---

## Voir aussi

- `optional/ngpc_procgen/` — donjon room-by-room style Dicing Knight
- `ngpc_cavegen_example.c` — démo jouable des deux modes
- `Doc de dev/Final/GAMEPLAY_MECHANICS.md` — collision tilemap, acteurs
