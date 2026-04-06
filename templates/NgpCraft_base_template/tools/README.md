# tools/

Scripts Python pour le pipeline assets et l'outillage du template.

Prérequis : Python 3.10+, Pillow (`pip install pillow`).

---

## Pipeline graphique

### `ngpc_tilemap.py`
**PNG → tilemap C/H pour les scroll planes (SCR1/SCR2).**

Prend un PNG dont chaque tile 8×8 a ≤ 3 couleurs visibles et génère les tableaux
`tiles[]`, `map_tiles[]` et `palettes[]` prêts à être chargés en VRAM.
Si une tile dépasse 3 couleurs, le pipeline bascule automatiquement en dual-layer
(deux fichiers C séparés).

```sh
python tools/ngpc_tilemap.py GraphX/bg.png -o GraphX/bg.c --header
```

---

### `ngpc_sprite_export.py`
**PNG spritesheet → metasprite C/H (un seul asset à la fois).**

Gère la déduplication de tiles, l'attribution de palettes, et génère les structures
`NgpcMetasprite` + table d'animation. Exporte aussi `name_tile_base` et `name_pal_base`
dans les fichiers générés pour un placement VRAM déterministe.

```sh
python tools/ngpc_sprite_export.py GraphX/player.png \
    -o GraphX/player_mspr.c \
    --frame-w 16 --frame-h 16 \
    --tile-base 256 --pal-base 0 \
    --header
```

Options utiles :
- `--tile-base N` : slot tile de départ (défaut 0)
- `--pal-base N` : slot palette de départ, 0–15 (défaut 0)
- `--fixed-palette A,B,C,D` : force une palette RGB444 externe, utile pour partager
  la palette d'un autre sprite déjà exporté
- `--frame-count N` : nombre de frames à exporter (défaut = toutes)
- `--anim-duration N` : durée par frame dans la table d'animation

---

### `ngpc_sprite_bundle.py`
**Infrastructure générique pour exporter plusieurs sprites en séquence.**

Fournit la classe `SpriteBundle` qui track automatiquement `tile_base` / `pal_base`
et vérifie les overflows (512 tiles max, 16 palettes max). À importer dans le script
d'export spécifique à votre jeu.

Fonctions utilitaires disponibles :
- `load_rgba(path)` — ouvre un PNG en RGBA
- `make_sheet(frames, w, h, out)` — assemble une sprite sheet horizontale
- `make_sheet_from_files(paths, w, h, out)` — idem depuis une liste de fichiers
- `split_two_layers(frames, w, h)` — split un sprite 6 couleurs en 2 layers de 3
- `read_palette(mspr_c, symbol)` — lit 4 mots RGB444 depuis un `*_mspr.c` généré

```python
# Exemple : script d'export jeu-spécifique
from pathlib import Path
from ngpc_sprite_bundle import SpriteBundle, load_rgba, make_sheet, split_two_layers

project_root = Path(__file__).resolve().parent.parent
bundle = SpriteBundle(
    project_root=project_root,
    out_dir=project_root / "GraphX",
    gen_dir=project_root / "GraphX" / "_gen",
    tile_base=256,
    pal_base=0,
)

# Export normal (avance tile_base ET pal_base)
sheet = bundle.gen_dir / "enemy_sheet.png"
make_sheet([load_rgba(f) for f in sorted((project_root / "art").glob("enemy*.png"))], 8, 8, sheet)
bundle.export("enemy", sheet, 8, 8, anim_duration=4)

# Export avec palette partagée (avance tile_base seulement)
saved_pal = bundle.pal_base - 1  # palette allouée par l'export précédent
bundle.export_reuse_palette("enemy_b", sheet_b, 8, 8, shared_pal_base=saved_pal)

print(f"Done. tile_base={bundle.tile_base}, pal_base={bundle.pal_base}")
```

---

### `ngpc_palette_viewer.py`
**Visualise les palettes sprite de tous les `*_mspr.c` d'un dossier GraphX.**

Génère trois fichiers :
- `ngpc_palettes.gpl` — palette chargeable directement dans Aseprite
- `ngpc_palettes.png` — swatch visuel (4 colonnes × 16 lignes)
- `ngpc_palettes.txt` — rapport texte : slot / sprite / hex / RGB

Utile pour vérifier les allocations palettes et éviter les collisions.

```sh
python tools/ngpc_palette_viewer.py
# ou
python tools/ngpc_palette_viewer.py GraphX --out GraphX
```

---

## Compression

### `ngpc_compress.py`
**Compresse des données binaires (tiles, maps) en RLE ou LZ77/LZSS.**

La sortie correspond au décompresseur embarqué dans `src/ngpc_lz.c`.
Génère un fichier `.c` avec un tableau `const u8`.

```sh
python tools/ngpc_compress.py tiles.bin -o tiles_lz.c -m lz77 -n level1_tiles
python tools/ngpc_compress.py tiles.bin -o tiles_both.c -m both -n my_tiles
```

Modes : `rle`, `lz77`, `both` (génère les deux dans le même fichier).

---

## Outillage projet

### `ngpc_project_init.py`
**Crée un nouveau projet à partir de ce template.**

Copie le template dans un dossier cible en sautant les artefacts générés
(`bin/`, `build/`, `__pycache__/`, etc.) et renomme les identifiants du projet
(`NAME` dans le makefile, `CartTitle` dans `carthdr.h`).

```sh
python tools/ngpc_project_init.py C:/dev/MonJeu --name "Mon Jeu NGPC" --rom-name monjeu
python tools/ngpc_project_init.py C:/dev/MonJeu --dry-run   # prévisualise sans copier
```

---

### `build_utils.py`
**Helpers cross-platform appelés par le Makefile.**

N'est pas destiné à être lancé directement. Utilisé en interne par les cibles `make clean`,
`make` (déplacement de la ROM finale `.ngc`, conversion interne `.s24 → .ngp`).

---

### `ngpc-aseprite-color-tools.zip`
**Extension Aseprite pour travailler en palette NGPC.**

Contient des scripts Lua à installer dans Aseprite pour contraindre les couleurs
à la gamme RGB444 du NGPC et faciliter la création d'assets hardware-correct.
Voir le README dans l'archive.
