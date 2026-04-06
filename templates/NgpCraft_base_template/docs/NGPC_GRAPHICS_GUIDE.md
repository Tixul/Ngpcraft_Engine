# Guide graphique NGPC — Pipeline PNG → tilemap → affichage

Ce guide couvre le pipeline complet d'affichage : de la génération des assets
jusqu'au rendu à l'écran, avec les deux méthodes disponibles et la checklist
de diagnostic quand ça ne marche pas.

---

## 1. Pipeline complet

```
PNG source
    │
    ▼
ngpc_tilemap.py  ──►  GraphX/foo.c + foo.h
                       (tiles u16/u8, tilemap, palettes)
    │
    ▼
Code C (méthode A ou B)
    │
    ▼
Affichage écran 160×152 px
```

---

## 2. Commandes ngpc_tilemap.py

### Plein écran (intro/menu) — tiles en bytes (u8, pratique pour cc900)

```bash
python tools/ngpc_tilemap.py assets/title.png \
  -o GraphX/title_intro.c -n title_intro --header \
  --emit-u8-tiles --black-is-transparent --no-dedupe
```

### Dual-layer explicite (SCR1 + SCR2)

```bash
python tools/ngpc_tilemap.py scr1.png --scr2 scr2.png \
  -o GraphX/level1.c -n level1 --header --emit-u8-tiles
```

**Notes importantes :**
- `--emit-u8-tiles` : tiles en u8 (poids moitié en RAM, NGP_FAR toujours requis)
- `tiles_count` = nombre de mots u16 (= nb_tiles × 8), **pas** le nombre de tiles
- `map_tiles[]` = indices 0..N dans le set unique (ajouter TILE_BASE à l'affichage)
- `--no-dedupe` : désactive la déduplication (utile pour les écrans plein écran)

---

## 3. Méthode A — Helpers (méthode normale)

C'est la méthode recommandée. Elle nécessite que les helpers soient compilés
avec les signatures `NGP_FAR` correctes (template à jour).

```c
#include "ngpc_gfx.h"
#include "../GraphX/intro_ngpc_craft_png.h"

#define INTRO_TILE_BASE 128u  /* évite d'écraser la sysfont BIOS (tiles 32-127) */

static void intro_init(void)
{
    u16 i;

    ngpc_gfx_clear(GFX_SCR1);
    ngpc_gfx_clear(GFX_SCR2);
    ngpc_gfx_set_bg_color(RGB(0, 0, 0));

    /* Tiles — NGP_FAR géré en interne par le helper */
    ngpc_gfx_load_tiles_at(intro_ngpc_craft_png_tiles,
                           intro_ngpc_craft_png_tiles_count,
                           INTRO_TILE_BASE);

    /* Palettes */
    for (i = 0; i < (u16)intro_ngpc_craft_png_palette_count; ++i) {
        u16 off = (u16)i * 4u;
        ngpc_gfx_set_palette(GFX_SCR1, (u8)i,
            intro_ngpc_craft_png_palettes[off + 0],
            intro_ngpc_craft_png_palettes[off + 1],
            intro_ngpc_craft_png_palettes[off + 2],
            intro_ngpc_craft_png_palettes[off + 3]);
    }

    /* Map */
    for (i = 0; i < intro_ngpc_craft_png_map_len; ++i) {
        u8 x   = (u8)(i % intro_ngpc_craft_png_map_w);
        u8 y   = (u8)(i / intro_ngpc_craft_png_map_w);
        u16 tile = (u16)(INTRO_TILE_BASE + intro_ngpc_craft_png_map_tiles[i]);
        u8 pal = (u8)(intro_ngpc_craft_png_map_pals[i] & 0x0Fu);
        ngpc_gfx_put_tile(GFX_SCR1, x, y, tile, pal);
    }
}
```

---

## 4. Méthode B — VRAM brut / macros (solution de secours)

Utilise `src/gfx/ngpc_tilemap_blit.h`. Écrit directement en VRAM sans passer
de pointeurs en paramètre — évite totalement les problèmes near/far.

À utiliser quand :
- On suspecte un problème de pointeurs dans les helpers
- On veut une voie d'affichage 100% directe pour diagnostiquer

```c
#include "ngpc_tilemap_blit.h"
#include "../GraphX/intro_ngpc_craft_png.h"

#define INTRO_TILE_BASE 128u

static void intro_init(void)
{
    ngpc_gfx_clear(GFX_SCR1);
    ngpc_gfx_clear(GFX_SCR2);
    ngpc_gfx_set_bg_color(RGB(0, 0, 0));

    NGP_TILEMAP_BLIT_SCR1(intro_ngpc_craft_png, INTRO_TILE_BASE);
}
```

Ce que fait la macro :
1. Copie les tiles vers Character RAM (VRAM) à `0xA000` (16 bytes par tile)
2. Écrit la tilemap u16 directement dans `HW_SCR1_MAP` (0x9000)
3. Charge les palettes via `ngpc_gfx_set_palette()`

Fonctionne avec n'importe quel préfixe généré par `ngpc_tilemap.py` tant que
les symboles suivent le contrat (`prefix_tiles`, `prefix_map_tiles`,
`prefix_palettes`...).

---

## 5. Deux classes de bugs (rendu corrompu)

### Classe #1 — Init vidéo (registres)

Règle générale :
- Ne **jamais** écraser un registre vidéo entier avec `0` / `0xFF` si tous les
  bits ne sont pas connus.
- Préférer les opérations bitwise (`|=`, `&=`, `^=`) sur les bits documentés.

Exemple : `HW_SCR_PRIO` (0x8030) — le template force uniquement le bit 7
(priorité SCR1/SCR2) dans `src/core/ngpc_sys.c`.

### Classe #2 — cc900 near/far + assets en ROM

**Contexte :** la ROM est linkée à `0x200000`. Les assets `const` générées
vivent donc en `0x200000+`. cc900 a un modèle near/far : si un pointeur est
traité comme "near" (16 bits), l'adresse est tronquée → lecture au mauvais
endroit.

**Symptôme typique :** le converter sort des données correctes, mais le rendu
via certains helpers est "n'importe quoi" ou décalé.

**Fix :** les helpers du template utilisent `NGP_FAR` dans leurs signatures.
Voir [NGPC_CC900_GUIDE.md](NGPC_CC900_GUIDE.md) § Far pointers.

---

## 6. Checklist rapide — quand ça casse

1. **Palettes** : sont-elles chargées sur la bonne plane (SCR1 vs SCR2) ?
2. **Tile base** : as-tu évité d'écraser la sysfont (`tile_base >= 128`) ?
3. **Helpers** : es-tu sur un template qui définit `NGP_FAR` + signatures à jour ?
4. **Secours** : est-ce que `NGP_TILEMAP_BLIT_SCR1/_SCR2` rend OK ?
   - Si oui → l'asset est sain, le problème est dans les helpers (near/far)
   - Si non → l'asset est peut-être corrompu ou l'init vidéo est incorrecte
5. **Données brutes** : vérifier les tiles/map/palettes générées byte-à-byte
   avant d'accuser le pipeline C

---

## 7. Contraintes tilemap

| Contrainte | Valeur |
|---|---|
| Carte SCR | 32×32 tiles |
| Écran visible | 20×19 tiles (160×152 px) |
| Tiles disponibles | 128–511 (0–31 réservés, 32–127 = sysfont BIOS) |
| Palettes SCR | 16 palettes × 4 couleurs, format `0x0BGR` |
| Palette 0 couleur 0 | Transparente pour les scroll planes |
| Tiles max ROM | 512 tiles total (Character RAM = 8 KB) |

---

## 8. Adressage tilemap wrap-safe (Sonic disassembly §3.2 / §6.9)

Ces formules sont extraites du désassemblage de Sonic NGPC et confirmées par
`ngpc_gfx_fill_rect()` et `optional/ngpc_tileblitter/`.

### Coordonnées tile → offset byte dans la map

```c
/* Base plane : SCR1 = 0x9000, SCR2 = 0x9800
 * Chaque entrée = 2 bytes (u16). Stride d'une ligne = 32 * 2 = 64 bytes. */
u16 byte_addr = (u16)y * 0x40u + (u16)x * 2u;
```

### Avance d'une colonne (wrap 32 colonnes = 64 bytes)

```c
byte_addr = (byte_addr & 0xFFC0u) | ((u16)(byte_addr + 2u) & 0x003Fu);
/* Partie haute &0xFFC0 = conserve la ligne, &0x003F = boucle dans 64 bytes */
```

### Avance d'une ligne (wrap plane 2 KB)

```c
byte_addr = (byte_addr & 0xF800u) | ((u16)(byte_addr + 0x40u) & 0x07FFu);
/* Partie haute &0xF800 = conserve l'adresse de base, &0x07FF = boucle 2 KB */
```

### Modifier la palette sans toucher le tile index (Sonic §3.3)

Tileword high byte layout : `bit7=H.F | bit6=V.F | bits4:1=CP.C | bit0=tile_bit8`

Mask `0xC1` (sur le high byte) garde H.F + V.F + tile_bit8, remplace CP.C.
Sur le u16 complet (mask `0xE1FF = ~(0xF << 9)`) :

```c
entry = (entry & 0xE1FFu) | ((u16)(pal & 0x0Fu) << 9u);
```

API disponible : `ngpc_gfx_set_rect_pal(plane, x, y, w, h, pal)`

### Clear total tilemap + tile RAM en une passe (Pocket Tennis §5.2)

Pocket Tennis efface SCR1 (2KB) + SCR2 (2KB) + Character RAM (8KB) en
un seul `LDIRW` depuis 0x9000 sur 0x3000 bytes :

```c
/* Équivalent C89 : */
volatile u16 *p = (volatile u16 *)0x9000;
u16 i;
for (i = 0; i < 0x1800u; i++)
    p[i] = 0;
```

Utile pour une réinitialisation complète du mode graphique entre deux scènes.

---

## 9. Fonctions utilitaires tilemap (nouvelles dans v2026)

### `ngpc_gfx_fill_rect()` — remplir un rectangle avec une tile

```c
void ngpc_gfx_fill_rect(u8 plane, u8 x, u8 y, u8 w, u8 h, u16 tile, u8 pal);
```

Remplit un rectangle W×H tiles avec la même entrée tilemap (tile index + palette).
Wrap-safe : les coordonnées bouclent automatiquement sur 32 colonnes/lignes.

```c
/* Fond uniforme sur toute la carte SCR1 (32×32 tiles) */
ngpc_gfx_fill_rect(GFX_SCR1, 0, 0, 32, 32, TILE_SKY, 0);

/* Zone HUD en bas (toute la largeur visible, 2 lignes) */
ngpc_gfx_fill_rect(GFX_SCR1, 0, 17, 20, 2, TILE_HUD_BG, 1);

/* Effacer une zone de 4×3 tiles en (8, 5) */
ngpc_gfx_fill_rect(GFX_SCR1, 8, 5, 4, 3, 0, 0);
```

> **Différence avec `ngpc_gfx_fill()`** : `fill()` remplit le plan entier (32×32).
> `fill_rect()` remplit n'importe quelle sous-région à n'importe quelle position.

---

### `ngpc_gfx_set_rect_pal()` — changer la palette d'un rectangle

```c
void ngpc_gfx_set_rect_pal(u8 plane, u8 x, u8 y, u8 w, u8 h, u8 pal);
```

Change la palette des entrées tilemap dans le rectangle W×H, **sans toucher**
au tile index, au bit H.flip ni au bit V.flip (mask `0xE1FF`).

Pattern Sonic §3.3 : `entry = (entry & 0xE1FFu) | ((pal & 0x0F) << 9)`.

```c
/* Flash de dommage : passer toute la zone ennemie en palette rouge */
ngpc_gfx_set_rect_pal(GFX_SCR1, enemy_tx, enemy_ty, 2, 2, PAL_RED);

/* Après le flash : restaurer la palette normale */
ngpc_gfx_set_rect_pal(GFX_SCR1, enemy_tx, enemy_ty, 2, 2, PAL_NORMAL);

/* Changer la palette d'un item ramassable sans recharger sa tile */
ngpc_gfx_set_rect_pal(GFX_SCR2, item_tx, item_ty, 1, 1, PAL_GOLD);
```

> **Usage typique :** effet de "clignotement" ou "teinte" sur une zone tilemap
> sans avoir à reblitter les tiles.

---

### `ngpc_tblit()` / `ngpc_tblit_hflip()` — blitter un rectangle depuis la ROM

Module optionnel : `optional/ngpc_tileblitter/` — voir `optional/README.md §ngpc_tileblitter`.

Ces fonctions gèrent les mises à jour partielles de tilemap pour des assets
stockés en ROM sous forme de tilewords u16 pré-construits :

```c
/* Inclure le module copié dans src/ */
#include "ngpc_tileblitter/ngpc_tileblitter.h"

/* Données en ROM : 4*3 = 12 tilewords (tile index + palette + flip déjà encodés) */
static const u16 NGP_FAR room1_door[12] = {
    0x0080, 0x0081, 0x0082, 0x0083,   /* ligne 0 : tiles 128-131, palette 0 */
    0x0090, 0x0091, 0x0092, 0x0093,   /* ligne 1 */
    0x00A0, 0x00A1, 0x00A2, 0x00A3,   /* ligne 2 */
};

/* Blitter la porte à la position (10, 5) */
ngpc_tblit(GFX_SCR1, 10, 5, 4, 3, room1_door);

/* Version miroir (même asset, porte côté droit) */
ngpc_tblit_hflip(GFX_SCR1, 16, 5, 4, 3, room1_door);
```

**Quand utiliser `ngpc_tblit` vs `ngpc_gfx_put_tile` :**

| Besoin | Solution |
|---|---|
| Poser un seul tile | `ngpc_gfx_put_tile()` |
| Remplir un bloc uniforme | `ngpc_gfx_fill_rect()` |
| Dessiner un décor rectangulaire depuis la ROM | `ngpc_tblit()` |
| Idem en miroir horizontal | `ngpc_tblit_hflip()` |
| Charger un écran complet | `NGP_TILEMAP_BLIT_SCR1()` macro |

---

## 10. HBlank: raster (CPU), MicroDMA, sprmux (beaucoup de sprites)

Le NGPC a trois "familles" de trucs HBlank (scanline) utiles:

- `ngpc_raster`: ISR CPU sur Timer0 (HBlank) -> modifie 1-2 registres par ligne.
- `ngpc_dma_raster`: MicroDMA (pas d'ISR CPU) -> stream 152 bytes vers un registre a chaque HBlank.
- `ngpc_sprmux`: multiplexage sprites -> reprogramme des slots sprites pendant HBlank.

### Regle d'or: Timer0 est la ressource critique

- Timer0 est connecte a HBlank.
- MicroDMA utilise les requetes d'interruption comme "triggers": si un canal MicroDMA est arme sur `Timer0 (0x10)`, la requete Timer0 est consommee par le DMA (le CPU n'execute pas de code HBlank).
- Donc `ngpc_raster` (CPU Timer0) et `ngpc_dma_raster` (MicroDMA Timer0) sont exclusifs.

### Nouveau combo utile (base sur les patterns Pocket Tennis/Sonic)

Tu peux faire tourner **MicroDMA (Timer0)** + **sprmux (Timer1)** dans le meme frame:

- MicroDMA: `Timer0 (0x10)` comme start vector
- sprmux: ISR CPU sur `Timer1`, clocke depuis `Timer0 overflow (TO0TRG)`

Ca permet typiquement:
- Parallax scroll (MicroDMA X-only sur SCR1 ou SCR2)
- Beaucoup de sprites (sprmux) en meme temps

Contraintes:
- Timer1 ne doit pas etre utilise comme start vector MicroDMA (sinon l'ISR sprmux sur Timer1 ne tournera pas).
- Pour eviter 2 ISRs par scanline, prefere ce mode avec MicroDMA actif sur Timer0.

API:
- `ngpc_sprmux_flush()` -> sprmux sur Timer0 (mode classique)
- `ngpc_sprmux_flush_timer1()` -> sprmux sur Timer1 (mode "coexistence MicroDMA")

---

## 11. Grandes cartes et streaming tilemap (ngpc_mapstream)

### Principe

La VRAM tilemap hardware est figée à **32×32 tiles = 256×256 px** par plane.
Pour des niveaux plus grands, on exploite le comportement toroïdal du hardware :

- Le tile monde `(wx, wy)` est stocké en VRAM à la position `(wx % 32, wy % 32)`
- Quand la caméra scroll de 1 case vers la droite, la colonne qui vient d'entrer dans le viewport
  est écrite dans le slot VRAM qui vient de "passer derrière" (invisible)
- Le hardware gère le wrap automatiquement via les registres scroll 8-bit

### Cas A — Projet PNG Manager (automatique)

Pour tout projet géré par le PNG Manager, **rien à faire** : si le background d'une scène dépasse
32×32 tiles, l'export génère automatiquement `scene_X_stream_planes()` dans le header de scène.
Cette fonction est appelée chaque frame via `ngpng_apply_plane_scroll()`.

Il suffit de fournir une grande PNG en background dans l'onglet Projet — le streaming est transparent.

### Cas B — Utilisation manuelle (`ngpc_mapstream`)

Pour un projet sans PNG Manager, le module optionnel `optional/ngpc_mapstream/` expose une API explicite.
Les données ROM doivent être des tilewords **absolus** (tile base déjà inclus). Voir `optional/README.md §ngpc_mapstream`.

```c
#include "ngpc_mapstream/ngpc_mapstream.h"

/* Array ROM : tilewords ABSOLUS (tile_base + relative_index + palette<<9). */
/* Généré manuellement ou via ngpc_tilemap.py + post-processing.            */
extern const u16 NGP_FAR g_level1_bg_map[128u * 32u];

NgpcMapStream g_ms;

/* Scene init (avant la boucle principale) : */
ngpc_mapstream_init(&g_ms, GFX_SCR1,
                    g_level1_bg_map, 128u, 32u,
                    cam_px, cam_py);

/* Boucle principale — après ngpc_vsync(), avant draw : */
ngpc_mapstream_update(&g_ms, cam_px, cam_py);
ngpc_cam_apply(&cam, GFX_SCR1);    /* scroll hardware normal */
```

### Tailles recommandées

| Cas d'usage | Dimensions conseillées | Map ROM |
|---|---|---|
| Platformer horizontal | 64×20 à 128×24 tiles | 10–25 KB |
| Shmup vertical | 20×64 à 24×128 tiles | 10–25 KB |
| Top-down / aventure | 32×32 à 64×64 tiles | 8–32 KB |
| Grand monde | jusqu'à 256×256 tiles | jusqu'à 128 KB |

### Budget tiles (Character RAM)

Les tiles graphiques (tileset) sont limités à **384 slots** (128–511, slots 0–127 réservés) :

| Unique tiles | Statut |
|---|---|
| ≤ 256 | ✅ OK — marge confortable pour les sprites |
| 257–320 | ⚠️ Attention — peu de marge |
| 321–384 | 🔶 Limite critique |
| > 384 | 🔴 Impossible — ne compilera pas correctement |

> **Conseil :** répéter les tiles (sol, mur, ciel) pour réduire le tileset unique.
> Un niveau de 128×32 peut souvent tenir en 50–100 tiles distincts avec un bon découpage.

### Contrainte : indices absolus (cas manuel uniquement)

Pour l'utilisation **manuelle** de `ngpc_mapstream_init()`, le tableau `map_tiles[]` doit contenir des tilewords avec le tile base **déjà inclus** (ex. : tile 0 du tileset → tileword `0x0080` si TILE_BASE = 128).

En **cas PNG Manager** (Cas A), ce calcul est fait automatiquement dans le code généré — aucune manipulation nécessaire.

### Téléportation caméra

Si la caméra saute de plus de `NGPC_MAPSTREAM_MAX_DELTA` tiles (défaut : 10) en un frame (transition de scène, warp), appelle `ngpc_mapstream_init()` à nouveau pour re-blitter le viewport complet.
