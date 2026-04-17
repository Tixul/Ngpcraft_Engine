"""
core/dungeongen_tiles_export.py
================================
PNG tileset → GraphX/gen/tiles_procgen.c + tiles_procgen.h

Convention PNG :
  - Peut être une bande verticale (1 colonne) OU une grille rectangulaire.
  - Largeur = n_cols * cell_w_tiles * 8 px  (n_cols ≥ 1)
  - Hauteur = n_rows * cell_h_tiles * 8 px  (n_rows ≥ 1)
  - Index cellule : gauche→droite, haut→bas (raster order)
  - Format PNG indexé (palette 4 couleurs max) ou RGBA (on extrait la palette)

Génère :
  tiles_procgen.h  — defines TILE_xxx + extern array + TILE_BASE + TILES_PROCGEN_COUNT
  tiles_procgen.c  — const u8 TILES_PROCGEN[]

Les roles tile sont définis dans _TILE_ROLE_ORDER (même ordre que le module C).
Les indices tile_idx dans tile_roles pointent vers l'index de CELLULE dans le PNG
(0 = première cellule haut-gauche, numérotation raster par cellule de cell_w×cell_h tiles).
Un rôle non assigné utilise la tile 0 (sol fallback) et génère un warning.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

try:
    from PIL import Image
except ImportError:
    raise ImportError("Pillow requis : pip install Pillow")

from core.dungeongen_cells import dungeongen_group_cells_per_variant

# ---------------------------------------------------------------------------
# Ordre fixe des rôles (doit correspondre aux defines dans tiles_procgen.h)
# ---------------------------------------------------------------------------

TILE_ROLE_ORDER: list[tuple[str, str]] = [
    # (json_key,         C_define_suffix)
    ("floor_1",          "GROUND_1"),
    ("floor_2",          "GROUND_2"),
    ("floor_3",          "GROUND_3"),
    ("wall_n",           "WALL_EXT_N"),
    ("wall_s",           "WALL_EXT_S"),
    ("wall_e",           "WALL_EXT_E"),
    ("wall_w",           "WALL_EXT_W"),
    ("corner_nw",        "WALL_EXT_NW"),
    ("corner_ne",        "WALL_EXT_NE"),
    ("corner_sw",        "WALL_EXT_SW"),
    ("corner_se",        "WALL_EXT_SE"),
    ("int_wall_n",       "WALL_INT_N"),
    ("int_wall_s",       "WALL_INT_S"),
    ("int_wall_e",       "WALL_INT_E"),
    ("int_wall_w",       "WALL_INT_W"),
    ("int_corner_nw",    "WALL_INT_NW"),
    ("int_corner_ne",    "WALL_INT_NE"),
    ("int_corner_sw",    "WALL_INT_SW"),
    ("int_corner_se",    "WALL_INT_SE"),
    ("water",            "EAU_H"),
    ("bridge",           "PONT_H"),
    ("void",             "VIDE"),
    ("deco_a",           "TONNEAU"),
    ("deco_c",           "DECO_C"),
    ("exit_stair",       "EXIT_STAIR"),
    ("door",             "DOOR"),
]

# Tile base VRAM (les tiles 0–127 sont réservés NGPC / sysfont)
TILE_BASE_DEFAULT = 128

# ---------------------------------------------------------------------------
# Mode compact — rôles source (PNG) et rôles dérivés (rotation/flip)
# ---------------------------------------------------------------------------
# Rôles lus depuis le PNG en mode compact (13 entrées au lieu de 26)
COMPACT_SOURCE_ROLES: list[tuple[str, str]] = [
    ("floor_1",       "GROUND_1"),
    ("floor_2",       "GROUND_2"),
    ("floor_3",       "GROUND_3"),
    ("wall_s",        "WALL_EXT_S"),    # source murs ext (N/E/W dérivés)
    ("corner_nw",     "WALL_EXT_NW"),   # source coins ext (NE/SW/SE dérivés)
    ("int_wall_s",    "WALL_INT_S"),    # source murs int
    ("int_corner_nw", "WALL_INT_NW"),  # source coins int
    ("water",         "EAU_H"),
    ("bridge",        "PONT_H"),
    ("void",          "VIDE"),
    ("deco_a",        "TONNEAU"),
    ("deco_c",        "DECO_C"),
    ("exit_stair",    "EXIT_STAIR"),
    ("door_s",        "DOOR_S"),        # source porte (N/E/W dérivés)
]

# (role_dérivé, C_suffix, source_role, hflip, vflip, is_rotation_90cw)
# is_rotation=True  → nouvelle tile dans le binaire (rotation 90° CW par le tool)
# is_rotation=False → même tile que source, hardware flip au runtime
COMPACT_DERIVED_ROLES: list[tuple[str, str, str, bool, bool, bool]] = [
    # Murs extérieurs
    ("wall_e",        "WALL_EXT_E",  "wall_s",        False, False, True),   # rot 90°CCW
    ("wall_n",        "WALL_EXT_N",  "wall_s",        False, True,  False),  # Vflip(wall_s)
    ("wall_w",        "WALL_EXT_W",  "wall_e",        True,  False, False),  # Hflip(wall_e)
    # Coins extérieurs (tous depuis corner_nw, aucune rotation)
    ("corner_ne",     "WALL_EXT_NE", "corner_nw",     True,  False, False),  # Hflip
    ("corner_sw",     "WALL_EXT_SW", "corner_nw",     False, True,  False),  # Vflip
    ("corner_se",     "WALL_EXT_SE", "corner_nw",     True,  True,  False),  # HVflip
    # Murs intérieurs
    ("int_wall_e",    "WALL_INT_E",  "int_wall_s",    False, False, True),   # rot 90°CCW
    ("int_wall_n",    "WALL_INT_N",  "int_wall_s",    False, True,  False),  # Vflip
    ("int_wall_w",    "WALL_INT_W",  "int_wall_e",    True,  False, False),  # Hflip
    # Coins intérieurs
    ("int_corner_ne", "WALL_INT_NE", "int_corner_nw", True,  False, False),
    ("int_corner_sw", "WALL_INT_SW", "int_corner_nw", False, True,  False),
    ("int_corner_se", "WALL_INT_SE", "int_corner_nw", True,  True,  False),
    # Portes
    ("door_e",        "DOOR_E",      "door_s",        False, False, True),   # rot 90°CCW
    ("door_n",        "DOOR_N",      "door_s",        False, True,  False),  # Vflip
    ("door_w",        "DOOR_W",      "door_e",        True,  False, False),  # Hflip
]

# Constantes flip (valeurs passées à _put_cell_ex dans ngpc_dungeongen.c)
DGN_FLIP_NONE = 0
DGN_FLIP_H    = 1
DGN_FLIP_V    = 2
DGN_FLIP_HV   = 3

# ---------------------------------------------------------------------------
# Extraction 2bpp
# ---------------------------------------------------------------------------

def _extract_palette(img: Image.Image) -> list[tuple[int, int, int]]:
    """Extract up to 3 opaque colors from an RGBA image by frequency.

    Scans the entire image, counts occurrences of each RGB444-snapped color,
    then returns the 3 most frequent non-transparent colors.  Using frequency
    (rather than first-encountered raster order) ensures that when the tileset
    contains multiple color groups (e.g. blue water tiles near the top of the
    sheet and brown terrain tiles further down), the dominant / most-used
    colors win — not whichever group happens to appear first in scan order.
    """
    from collections import Counter
    rgba = img.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size
    freq: Counter[tuple[int, int, int]] = Counter()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a >= 128:
                rgb = (r >> 4 << 4, g >> 4 << 4, b >> 4 << 4)  # snap to RGB444
                freq[rgb] += 1
    # Return the 3 most common colors (stable: most-frequent first)
    return [color for color, _ in freq.most_common(3)]


def _encode_tile_2bpp(tile_img: Image.Image, palette: list[tuple[int, int, int]]) -> bytes:
    """
    Convert a 8×8 RGBA tile image to NGPC 2bpp format (16 bytes).
    NGPC 2bpp : chaque tile = 8 rangées × 1 mot u16.
    Pixel order dans une rangée : bits (14-col*2, 15-col*2), gauche -> droite.
    Index 0 = transparent, 1-3 = couleurs palette.
    """
    rgba = tile_img.convert("RGBA")
    px = rgba.load()
    result = bytearray(16)
    for row in range(8):
        row_word = 0
        for col in range(8):
            r, g, b, a = px[col, row]
            if a < 128:
                idx = 0
            else:
                rgb = (r >> 4 << 4, g >> 4 << 4, b >> 4 << 4)
                try:
                    idx = palette.index(rgb) + 1  # 1-based (0 = transparent)
                except ValueError:
                    idx = 1  # fallback à couleur 1
                idx = min(idx, 3)
            row_word |= (idx & 0x3) << (14 - col * 2)
        result[row * 2]     = row_word & 0xFF
        result[row * 2 + 1] = (row_word >> 8) & 0xFF
    return bytes(result)


def _extract_metatile(
    img: Image.Image,
    meta_idx: int,
    cell_w: int,
    cell_h: int,
    palette: list[tuple[int, int, int]],
    n_cols_in_png: int = 1,
) -> bytes:
    """
    Extrait les cell_w × cell_h tiles 8×8 d'un metatile et les encode en 2bpp.
    Retourne cell_w*cell_h*16 bytes, ordre L→R, T→B.

    n_cols_in_png : nombre de colonnes de cellules dans le PNG (1 = bande verticale).
    meta_idx est l'index raster (gauche→droite, haut→bas).
    """
    result = bytearray()
    # meta_idx is the cell (metatile) index in the PNG grid.
    # Each cell is cell_w × cell_h tiles of 8px each.
    meta_col = meta_idx % n_cols_in_png
    meta_row = meta_idx // n_cols_in_png
    for ty in range(cell_h):
        for tx in range(cell_w):
            x0 = (meta_col * cell_w + tx) * 8
            y0 = (meta_row * cell_h + ty) * 8
            tile = img.crop((x0, y0, x0 + 8, y0 + 8))
            result += _encode_tile_2bpp(tile, palette)
    return bytes(result)


# ---------------------------------------------------------------------------
# Rotation 90° CW d'une metatile source (mode compact)
# ---------------------------------------------------------------------------

def _rotate90cw_metatile(
    img: Image.Image,
    meta_idx: int,
    cell_w: int,
    cell_h: int,
    palette: list[tuple[int, int, int]],
    n_cols_in_png: int,
) -> bytes:
    """Extrait une metatile du PNG, la fait tourner 90° dans le sens horaire,
    et la ré-encode en 2bpp.

    Fonctionne pour toute cellule carrée (cell_w == cell_h) ou rectangulaire.
    Après rotation 90° CW d'un bloc cell_px_w × cell_px_h :
      - nouvelle largeur  = cell_px_h
      - nouvelle hauteur  = cell_px_w
    On ré-encode ensuite les tiles 8×8 dans l'ordre raster du bloc tourné.
    Le binaire résultant a le même nombre de tiles que la source
    (cell_w * cell_h tiles) mais leur arrangement interne est tourné.
    """
    # meta_idx is the cell (metatile) index in the PNG grid.
    meta_col = meta_idx % n_cols_in_png
    meta_row = meta_idx // n_cols_in_png
    cell_px_w = cell_w * 8
    cell_px_h = cell_h * 8
    x0 = meta_col * cell_px_w
    y0 = meta_row * cell_px_h
    crop = img.crop((x0, y0, x0 + cell_px_w, y0 + cell_px_h)).convert("RGBA")
    # PIL rotate(90) = 90° dans le sens antihoraire
    rotated = crop.rotate(90, expand=True)
    # rotated est maintenant cell_px_h × cell_px_w (largeur et hauteur échangées)
    rot_w = cell_px_h  # largeur du bloc tourné (en px)
    rot_h = cell_px_w  # hauteur du bloc tourné (en px)
    # On encode les tiles dans l'ordre raster: cell_h colonnes × cell_w rangées
    result = bytearray()
    tiles_across = rot_w // 8   # = cell_h
    tiles_down   = rot_h // 8   # = cell_w
    for ty in range(tiles_down):
        for tx in range(tiles_across):
            tile = rotated.crop((tx * 8, ty * 8, tx * 8 + 8, ty * 8 + 8))
            result += _encode_tile_2bpp(tile, palette)
    return bytes(result)


# ---------------------------------------------------------------------------
# Entrée publique
# ---------------------------------------------------------------------------

def export_tiles_procgen(
    png_path: Path,
    cell_w_tiles: int,
    cell_h_tiles: int,
    tile_roles: dict[str, list[int]],   # {role_key: [tile_idx, ...]}
    out_dir: Path,
    tile_base: int = TILE_BASE_DEFAULT,
    sym_prefix: str = "TILES_PROCGEN",
    rt_cell_w_tiles: int = 0,
    rt_cell_h_tiles: int = 0,
    compact_mode: bool = False,
) -> tuple[Path, Path]:
    """
    Lit le PNG tileset, encode toutes les tiles assignées aux rôles, génère
    tiles_procgen.c et tiles_procgen.h dans out_dir.

    cell_w_tiles / cell_h_tiles : dimensions d'une cellule SOURCE dans le PNG
      (en tiles 8×8). Ex: 1×1 si le PNG est une grille de tiles 8×8.

    rt_cell_w_tiles / rt_cell_h_tiles : dimensions d'une cellule RUNTIME
      (nombre de tiles NGPC 8×8 par cellule de donjon). Doit correspondre à
      DUNGEONGEN_CELL_W_TILES / _CELL_H_TILES dans dungeongen_config.h.
      Si 0 (par défaut), utilise cell_w_tiles × cell_h_tiles (pas de réplication).
      Le runtime doit être de même taille que la cellule source, ou un multiple
      entier dans chaque axe. Exemples supportés :
        - source 1×1 -> runtime 1×1, 2×2, 4×4...
        - source 2×2 -> runtime 2×2, 4×4...
      Le cas inverse (source 2×2 -> runtime 1×1) n'est pas supporté.

    tile_roles: dict rôle → liste d'indices metatile dans le PNG.
      Un rôle avec plusieurs indices = variantes (on prend le premier pour le define C,
      toutes les variantes sont exportées et accessibles via un offset).

    Retourne (path_c, path_h).
    """
    png_path = Path(png_path)
    out_dir  = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not png_path.exists():
        raise FileNotFoundError(f"PNG tileset introuvable : {png_path}")

    img = Image.open(png_path).convert("RGBA")
    iw, ih = img.size
    cell_px_w = cell_w_tiles * 8
    cell_px_h = cell_h_tiles * 8
    # Indices in tile_roles are cell (metatile) indices — same grid as the UI picker.
    # A cell is cell_px_w × cell_px_h pixels.  Validate that the PNG dimensions
    # are divisible by the cell size.
    if iw % cell_px_w != 0:
        raise ValueError(f"PNG width {iw}px non divisible par {cell_px_w}px (cell_w_tiles={cell_w_tiles})")
    if ih % cell_px_h != 0:
        raise ValueError(f"PNG height {ih}px non divisible par {cell_px_h}px (cell_h_tiles={cell_h_tiles})")
    n_cols_in_png = iw // cell_px_w   # columns of metatiles
    n_rows_in_png = ih // cell_px_h   # rows    of metatiles
    n_meta_in_png = n_cols_in_png * n_rows_in_png  # total metatiles in PNG

    # Runtime tiles per metatile (must match DUNGEONGEN_CELL_W/H_TILES).
    # The runtime cell can be identical to the source crop, or a whole-number
    # upscale of it in each axis.
    _rt_cw = rt_cell_w_tiles if rt_cell_w_tiles > 0 else cell_w_tiles
    _rt_ch = rt_cell_h_tiles if rt_cell_h_tiles > 0 else cell_h_tiles
    cells_per_variant = dungeongen_group_cells_per_variant(
        source_cell_w_tiles=cell_w_tiles,
        source_cell_h_tiles=cell_h_tiles,
        runtime_cell_w_tiles=_rt_cw,
        runtime_cell_h_tiles=_rt_ch,
    )
    tiles_per_meta = _rt_cw * _rt_ch
    group_w = _rt_cw // cell_w_tiles
    group_h = _rt_ch // cell_h_tiles

    def _split_tiles(data: bytes, tiles_w: int, tiles_h: int) -> list[list[bytes]]:
        tiles = [
            data[(i * 16):((i + 1) * 16)]
            for i in range(tiles_w * tiles_h)
        ]
        return [
            tiles[(row * tiles_w):((row + 1) * tiles_w)]
            for row in range(tiles_h)
        ]

    def _assemble_runtime_variant(source_cells: list[bytes]) -> bytes:
        if len(source_cells) != cells_per_variant:
            raise ValueError(
                f"DungeonGen internal error: expected {cells_per_variant} source cells, "
                f"got {len(source_cells)}."
            )
        if cells_per_variant == 1:
            return source_cells[0]

        split_cells = [
            _split_tiles(cell_data, cell_w_tiles, cell_h_tiles)
            for cell_data in source_cells
        ]
        out = bytearray()
        for gy in range(group_h):
            row_cells = split_cells[(gy * group_w):((gy + 1) * group_w)]
            for src_ty in range(cell_h_tiles):
                for cell_rows in row_cells:
                    for tile_bytes in cell_rows[src_ty]:
                        out += tile_bytes
        return bytes(out)

    # -----------------------------------------------------------------------
    # Groupes de rôles — chaque groupe extrait sa propre palette depuis ses
    # tiles uniquement.  Les groupes compatibles (union ≤ 3 couleurs visibles)
    # partagent le même slot palette ; les autres obtiennent un slot distinct.
    # NGPC scroll layer supporte jusqu'à 16 slots palette.
    # -----------------------------------------------------------------------
    _GROUND_ROLES:   set[str] = {"floor_1", "floor_2", "floor_3"}
    _WALL_EXT_ROLES: set[str] = {
        "wall_n", "wall_s", "wall_e", "wall_w",
        "corner_nw", "corner_ne", "corner_sw", "corner_se",
    }
    _WALL_INT_ROLES: set[str] = {
        "int_wall_n", "int_wall_s", "int_wall_e", "int_wall_w",
        "int_corner_nw", "int_corner_ne", "int_corner_sw", "int_corner_se",
    }
    _EAU_ROLES:    set[str] = {"water"}
    _BRIDGE_ROLES: set[str] = {"bridge"}
    _DECO_ROLES:   set[str] = {"void", "deco_a", "deco_c", "exit_stair", "door", "door_s"}
    _ROLE_GROUPS: list[tuple[str, set[str]]] = [
        ("GROUND",   _GROUND_ROLES),
        ("WALL_EXT", _WALL_EXT_ROLES),
        ("WALL_INT", _WALL_INT_ROLES),
        ("EAU",      _EAU_ROLES),
        ("BRIDGE",   _BRIDGE_ROLES),
        ("DECO",     _DECO_ROLES),
    ]

    # Must be defined before _palette_from_role_group (closure reference)
    _source_order = COMPACT_SOURCE_ROLES if compact_mode else TILE_ROLE_ORDER

    def _palette_from_role_group(group_roles: set[str]) -> list[tuple[int, int, int]]:
        from collections import Counter
        freq: Counter[tuple[int, int, int]] = Counter()
        for rk, _ in _source_order:
            if rk not in group_roles:
                continue
            idxs = tile_roles.get(rk, [])
            if not idxs:
                continue  # rôle non assigné : ne pas polluer avec tile 0
            for mi in idxs:
                if mi < 0 or mi >= n_meta_in_png:
                    mi = 0
                mc = mi % n_cols_in_png  # metatile column
                mr = mi // n_cols_in_png  # metatile row
                x0 = mc * cell_px_w
                y0 = mr * cell_px_h
                crop = img.crop((x0, y0, x0 + cell_px_w, y0 + cell_px_h)).convert("RGBA")
                cpx = crop.load()
                for cy in range(cell_px_h):
                    for cx in range(cell_px_w):
                        r, g, b, a = cpx[cx, cy]
                        if a >= 128:
                            freq[(r >> 4 << 4, g >> 4 << 4, b >> 4 << 4)] += 1
        return [c for c, _ in freq.most_common(3)]

    # Extraire les couleurs de chaque groupe
    _fallback_pal: list[tuple[int, int, int]] = [(0, 0, 0)]
    group_raw_colors: list[tuple[str, list[tuple[int, int, int]]]] = [
        (gname, _palette_from_role_group(groles) or _fallback_pal)
        for gname, groles in _ROLE_GROUPS
    ]

    def _assign_group_slots(
        groups: list[tuple[str, list[tuple[int, int, int]]]]
    ) -> tuple[dict[str, int], list[list[tuple[int, int, int]]]]:
        """Assign palette slots; merge groups whose colors fit in 3 visible."""
        slots: list[set[tuple[int, int, int]]] = []
        group_to_slot: dict[str, int] = {}
        for gname, colors in groups:
            cset = set(colors)
            for i, slot in enumerate(slots):
                if len(slot | cset) <= 3:
                    slots[i] = slot | cset
                    group_to_slot[gname] = i
                    break
            else:
                group_to_slot[gname] = len(slots)
                slots.append(set(cset))
        return group_to_slot, [sorted(s) for s in slots]

    group_to_slot, slot_color_lists = _assign_group_slots(group_raw_colors)

    # Table role_key → palette de couleurs pour l'encodage 2bpp.
    # IMPORTANT : utiliser slot_color_lists[slot_idx] (l'ordre exact des defines
    # PAL_SLOTx_Cy générés) afin que l'index 2bpp en encodage corresponde
    # au bon registre de palette au runtime.
    role_to_palette: dict[str, list[tuple[int, int, int]]] = {}
    for gname, groles in _ROLE_GROUPS:
        slot_idx = group_to_slot[gname]
        slot_cols = slot_color_lists[slot_idx]  # même ordre que PAL_SLOTx_Cy
        for rk in groles:
            role_to_palette[rk] = slot_cols
    _default_pal: list[tuple[int, int, int]] = slot_color_lists[0]

    # -----------------------------------------------------------------------
    # Construire la séquence des metatiles
    # Mode full  : ordre TILE_ROLE_ORDER (26 rôles, tous en PNG)
    # Mode compact : COMPACT_SOURCE_ROLES (14 rôles PNG) + dérivés (rot/flip)
    # -----------------------------------------------------------------------
    warnings: list[str] = []

    role_offsets: dict[str, int] = {}   # role_key → tile offset dans l'array généré
    role_flip:    dict[str, int] = {}   # role_key → DGN_FLIP_* (0=NONE par défaut)
    all_tile_data = bytearray()

    for role_key, _c_suffix in _source_order:
        indices = tile_roles.get(role_key, [])
        if not indices:
            warnings.append(f"WARN rôle '{role_key}' non assigné — tile 0 utilisée")
            indices = [0] * max(1, cells_per_variant)

        role_offsets[role_key] = len(all_tile_data) // 16  # offset en tiles 8×8
        role_flip[role_key]    = DGN_FLIP_NONE

        role_palette = role_to_palette.get(role_key, _default_pal)

        if cells_per_variant > 1 and (len(indices) % cells_per_variant) != 0:
            raise ValueError(
                f"DungeonGen role '{role_key}' requires groups of {cells_per_variant} "
                f"source cells for a runtime cell of {_rt_cw}x{_rt_ch} tiles "
                f"(source cell {cell_w_tiles}x{cell_h_tiles}). "
                f"Current selection count: {len(indices)}."
            )

        variant_groups: list[list[int]]
        if cells_per_variant == 1:
            variant_groups = [[int(meta_idx)] for meta_idx in indices]
        else:
            variant_groups = [
                [int(meta_idx) for meta_idx in indices[i:(i + cells_per_variant)]]
                for i in range(0, len(indices), cells_per_variant)
            ]

        for group in variant_groups:
            source_cells: list[bytes] = []
            for meta_idx in group:
                if meta_idx < 0 or meta_idx >= n_meta_in_png:
                    warnings.append(
                        f"WARN rôle '{role_key}' : index {meta_idx} hors PNG "
                        f"(max {n_meta_in_png - 1}) — tile 0 utilisée"
                    )
                    meta_idx = 0
                source_cells.append(
                    _extract_metatile(
                        img,
                        meta_idx,
                        cell_w_tiles,
                        cell_h_tiles,
                        role_palette,
                        n_cols_in_png,
                    )
                )
            all_tile_data += _assemble_runtime_variant(source_cells)

    # -----------------------------------------------------------------------
    # Mode compact — ajouter les tiles dérivées (rotations) + flip-only
    # -----------------------------------------------------------------------
    if compact_mode:
        for (drk, _dcs, src_key, hflip, vflip, is_rot) in COMPACT_DERIVED_ROLES:
            if is_rot:
                # Rotation 90° CW : nouvelle tile dans le binaire
                src_indices = tile_roles.get(src_key, [0])
                src_idx = src_indices[0] if src_indices else 0
                src_palette = role_to_palette.get(src_key, _default_pal)
                if src_idx < 0 or src_idx >= n_meta_in_png:
                    warnings.append(
                        f"WARN compact mode rôle dérivé '{drk}' : "
                        f"source '{src_key}' index {src_idx} hors PNG — tile 0 utilisée"
                    )
                    src_idx = 0
                role_offsets[drk] = len(all_tile_data) // 16
                role_flip[drk]    = DGN_FLIP_NONE
                all_tile_data += _rotate90cw_metatile(
                    img, src_idx, cell_w_tiles, cell_h_tiles, src_palette, n_cols_in_png
                )
            else:
                # Flip-only : même tile que la source, aucune nouvelle donnée
                flip_val = (DGN_FLIP_V if vflip else 0) | (DGN_FLIP_H if hflip else 0)
                role_offsets[drk] = role_offsets.get(src_key, 0)
                role_flip[drk]    = flip_val

    n_tiles_total = len(all_tile_data) // 16  # nombre de tiles 8×8

    # -----------------------------------------------------------------------
    # Palette NGPC RGB444
    # -----------------------------------------------------------------------
    def _rgb444_word(r: int, g: int, b: int) -> int:
        return (r >> 4) | ((g >> 4) << 4) | ((b >> 4) << 8)

    def _make_pal_padded(colors: list[tuple[int, int, int]]) -> list[int]:
        """RGB444 words, padded to 4 entries (index 0 = 0x0000 transparent)."""
        words = [_rgb444_word(r, g, b) for r, g, b in colors]
        padded = [0x0000] + words[:3]
        while len(padded) < 4:
            padded.append(0x0000)
        return padded

    n_slots = len(slot_color_lists)

    # -----------------------------------------------------------------------
    # Génération .h — palettes RGB444 pour les defines C
    # -----------------------------------------------------------------------
    lines_h: list[str] = [
        "/*",
        " * tiles_procgen.h -- Tileset DungeonGen (généré automatiquement)",
        f" * Source : {png_path.name}",
        f" * Cellule : {cell_w_tiles}×{cell_h_tiles} tiles NGPC (8×8px chacune)",
        " * NE PAS ÉDITER — regénérer via l'onglet Procgen Assets de l'engine.",
        " */",
        "",
        "#ifndef TILES_PROCGEN_H",
        "#define TILES_PROCGEN_H",
        "",
        '#include "ngpc_hw.h"',
        "",
        f"#define TILE_BASE           {tile_base}u",
        f"#define {sym_prefix}_COUNT  {n_tiles_total * 8}u",  # u16 word count (8 per tile)
        f"#define TILES_PER_META      {tiles_per_meta}u",
        "",
        f"/* Palette slots SCR1 ({n_slots} slot(s) alloue(s) sur 16 disponibles) */",
    ]

    # Slot index par groupe
    for gname, slot_idx in group_to_slot.items():
        lines_h.append(f"#define PAL_{gname:<12} {slot_idx}u")

    lines_h += [
        "/* Backward compat */",
        "#define PAL_TERRAIN      PAL_GROUND",
        "",
        f"/* Couleurs par slot (0..{n_slots - 1}) — index 0 = transparent */",
    ]

    # Couleurs par slot
    for si, scols in enumerate(slot_color_lists):
        pal_padded = _make_pal_padded(scols)
        lines_h.append(f"/* Slot {si} */")
        for ci, w in enumerate(pal_padded):
            lines_h.append(f"#define PAL_SLOT{si}_C{ci}  0x{w:04X}u")

    lines_h.append("")
    lines_h.append("/* Alias couleurs par groupe */")
    for gname, slot_idx in group_to_slot.items():
        for ci in range(4):
            lines_h.append(f"#define PAL_{gname}_C{ci}  PAL_SLOT{slot_idx}_C{ci}")

    lines_h += [
        "",
        "/* Backward compat — PAL_TERRAIN_Cx = PAL_GROUND_Cx */",
        "#define PAL_TERRAIN_C0   PAL_GROUND_C0",
        "#define PAL_TERRAIN_C1   PAL_GROUND_C1",
        "#define PAL_TERRAIN_C2   PAL_GROUND_C2",
        "#define PAL_TERRAIN_C3   PAL_GROUND_C3",
    ]

    # Constantes flip — utilisées par _put_cell_ex dans ngpc_dungeongen.c
    lines_h += [
        "",
        "/* Flip flags pour _put_cell_ex() — voir ngpc_dungeongen.h DGN_FLIP_* */",
        "#ifndef DGN_FLIP_NONE",
        "#define DGN_FLIP_NONE  0u",
        "#define DGN_FLIP_H     1u",
        "#define DGN_FLIP_V     2u",
        "#define DGN_FLIP_HV    3u",
        "#endif",
        "",
        "/* Defines des rôles — slot VRAM depuis TILE_BASE */",
        f"/* Mode : {'compact (rotation+flip)' if compact_mode else 'full (tous les rôles en PNG)'} */",
        "",
    ]

    # Names that might collide with standard tile-collision constants in scenes_autogen.h.
    # Wrap those with #ifndef so that whichever header is included first wins.
    _COLLISION_NAMES: set[str] = {
        "PASS", "SOLID", "ONE_WAY", "DAMAGE", "LADDER",
        "WALL_N", "WALL_S", "WALL_E", "WALL_W",
        "WATER", "FIRE", "VOID", "DOOR",
        "STAIR_E", "STAIR_W", "SPRING", "ICE",
        "CONVEYOR_L", "CONVEYOR_R",
    }

    # En mode compact, émettre les defines pour TOUS les rôles (sources + dérivés),
    # plus TILE_*_FLIP pour chaque direction. En mode full, TILE_*_FLIP = 0 pour tous.
    _all_role_defines: list[tuple[str, str]] = (
        list(COMPACT_SOURCE_ROLES) + [(drk, dcs) for drk, dcs, *_ in COMPACT_DERIVED_ROLES]
        if compact_mode else list(TILE_ROLE_ORDER)
    )

    for role_key, c_suffix in _all_role_defines:
        off  = role_offsets.get(role_key, 0)
        flip = role_flip.get(role_key, DGN_FLIP_NONE)
        flip_names = {0: "DGN_FLIP_NONE", 1: "DGN_FLIP_H", 2: "DGN_FLIP_V", 3: "DGN_FLIP_HV"}
        flip_str = flip_names.get(flip, str(flip) + "u")
        if c_suffix in _COLLISION_NAMES:
            lines_h.append(f"#ifndef TILE_{c_suffix}")
            lines_h.append(f"#define TILE_{c_suffix:<18} {tile_base + off}u")
            lines_h.append(f"#endif")
        else:
            lines_h.append(f"#define TILE_{c_suffix:<18} {tile_base + off}u")
        lines_h.append(f"#undef  TILE_{c_suffix}_FLIP")
        lines_h.append(f"#define TILE_{c_suffix}_FLIP    {flip_str}")

    # Alias de compatibilité attendus par ngpc_dungeongen.c
    eau_off   = role_offsets.get("water",  0)
    pont_off  = role_offsets.get("bridge", 0)
    vide_off  = role_offsets.get("void",   0)
    lines_h += [
        "",
        "/* Alias de compatibilité (vertical/border variants + compat mode full) */",
        f"#define TILE_EAU_V         {tile_base + eau_off}u  /* = TILE_EAU_H */",
        f"#define TILE_PONT_V        {tile_base + pont_off}u  /* = TILE_PONT_H */",
        f"#define TILE_VIDE_BORD     {tile_base + vide_off}u  /* = TILE_VIDE */",
    ]
    if compact_mode:
        # Alias compat mode full → compact : TILE_DOOR → TILE_DOOR_S
        door_s_off = role_offsets.get("door_s", 0)
        lines_h += [
            f"#ifndef TILE_DOOR",
            f"#define TILE_DOOR          {tile_base + door_s_off}u  /* = TILE_DOOR_S */",
            f"#define TILE_DOOR_FLIP     DGN_FLIP_NONE",
            f"#endif",
        ]
    else:
        # En mode full, émettre les defines TILE_*_FLIP = 0 pour toutes les directions
        # (déjà émis dans la boucle ci-dessus)
        pass

    # u16 word count: 8 u16 words per tile (2bpp: 8 rows × 1 u16/row)
    n_u16_words = n_tiles_total * 8

    lines_h += [
        "",
        f"extern const u16 NGP_FAR {sym_prefix}[{n_u16_words}u];",
        "",
        "#endif /* TILES_PROCGEN_H */",
    ]

    # -----------------------------------------------------------------------
    # Génération .c  — stocker comme u16 little-endian words
    # -----------------------------------------------------------------------
    # all_tile_data is raw bytes: 16 bytes per tile (8 rows × 2 bytes/row).
    # ngpc_gfx_load_tiles_at expects const u16*: pair consecutive bytes → one u16 (LE).
    hex_rows: list[str] = []
    for tile_idx in range(n_tiles_total):
        base = tile_idx * 16
        tile_bytes = all_tile_data[base:base + 16]
        # 8 u16 words per tile (row by row)
        words = []
        for row in range(8):
            lo = tile_bytes[row * 2]
            hi = tile_bytes[row * 2 + 1]
            words.append(lo | (hi << 8))
        hex_vals = ", ".join(f"0x{w:04X}u" for w in words)
        # Comment on first tile of each metatile
        comment = ""
        if tile_idx % tiles_per_meta == 0:
            meta_tile = tile_idx // tiles_per_meta
            for rk, _ in _all_role_defines:
                off = role_offsets.get(rk, -1)
                count = len(tile_roles.get(rk, [0])) * tiles_per_meta
                if off <= tile_idx < off + count:
                    comment = f"  /* metatile {meta_tile}: {rk} */"
                    break
        hex_rows.append(f"    {hex_vals},{comment}")

    lines_c: list[str] = [
        "/*",
        " * tiles_procgen.c -- Tileset DungeonGen (généré automatiquement)",
        " * NE PAS ÉDITER.",
        " */",
        "",
        '#include "tiles_procgen.h"',
        "",
        f"const u16 NGP_FAR {sym_prefix}[{n_u16_words}u] = {{",
    ] + hex_rows + [
        "};",
    ]

    # -----------------------------------------------------------------------
    # Écriture
    # -----------------------------------------------------------------------
    out_h = out_dir / "tiles_procgen.h"
    out_c = out_dir / "tiles_procgen.c"
    out_h.write_text("\n".join(lines_h), encoding="utf-8")
    out_c.write_text("\n".join(lines_c), encoding="utf-8")

    for w in warnings:
        print(w)

    return out_c, out_h
