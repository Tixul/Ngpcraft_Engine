"""
core/dungeongen_sprites_export.py
==================================
Entity pool → GraphX/gen/sprites_lab.c + sprites_lab.h

Génère les arrays pool pour le module ngpc_dungeongen :
  - SPRITES_LAB[] + SPRITES_LAB_COUNT  (tile data concaténé pour load VRAM)
  - SPR_TILE_BASE                       (#define TILE_BASE + nb_tiles_procgen)
  - DUNGEONGEN_ENE_POOL_SIZE / DUNGEONGEN_ITEM_POOL_SIZE
  - s_ene_tiles[], s_ene_pals[], s_ene_is16[], s_ene_w[]
  - s_item_tiles[], s_item_pals[], s_item_w[]

Chaque entrée pool référence un entity_id du projet. Le script
cherche {entity_name}_mspr.c dans base_dir/GraphX/ pour extraire
tiles[], tile_base, pal_base et tiles_count.

Correspondance id → fichier :
  entity_id "etype_goblin", name "Goblin"
  → cherche "goblin_mspr.c" dans GraphX/
  → fallback: recherche partielle sur la partie après "etype_"

Si le mspr.c n'est pas trouvé, valeurs placeholder + warning.
Si la pool est vide, la section correspondante n'est pas émise
(#ifdef DUNGEONGEN_ENE_POOL_SIZE reste inactif).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Lecture du SPR_TILE_BASE depuis tiles_procgen.h (si disponible)
# ---------------------------------------------------------------------------

def _read_spr_tile_base(gen_dir: Path) -> int:
    """
    Lis TILE_BASE et TILES_PROCGEN_COUNT depuis gen_dir/tiles_procgen.h.
    TILES_PROCGEN_COUNT est stocké en mots u16, pas en tiles 8x8.
    SPR_TILE_BASE = TILE_BASE + ceil(TILES_PROCGEN_COUNT / 8).
    Retourne 128 si le fichier n'existe pas.
    """
    h = gen_dir / "tiles_procgen.h"
    if not h.exists():
        return 128
    text = h.read_text(encoding="utf-8", errors="replace")
    m_base  = re.search(r"#define\s+TILE_BASE\s+(\d+)", text)
    m_count = re.search(r"#define\s+TILES_PROCGEN_COUNT\s+(\d+)", text)
    base = int(m_base.group(1)) if m_base else 128
    count_words = int(m_count.group(1)) if m_count else 0
    count_tiles = (count_words + 7) // 8
    return base + count_tiles


# ---------------------------------------------------------------------------
# Index des mspr.c dans GraphX/
# ---------------------------------------------------------------------------

def _build_mspr_index(graphx_dir: Path) -> dict[str, Path]:
    """
    Scanne graphx_dir (et graphx_dir/gen/) pour *_mspr.c.
    Les mspr.c peuvent être directement dans GraphX/ ou dans GraphX/gen/ selon
    qu'ils ont été exportés par l'engine ou placés manuellement.
    Retourne {base_sprite_name: path}.
    ex: "goblin_mspr.c" → {"goblin": Path(...)}
    """
    index: dict[str, Path] = {}
    if not graphx_dir.is_dir():
        return index
    # Scan GraphX/ et GraphX/gen/ (les deux layouts sont supportés)
    dirs_to_scan = [graphx_dir, graphx_dir / "gen"]
    for scan_dir in dirs_to_scan:
        if not scan_dir.is_dir():
            continue
        for f in scan_dir.glob("*_mspr.c"):
            stem = f.stem  # "goblin_mspr"
            base = stem[:-5] if stem.endswith("_mspr") else stem
            if base not in index:  # GraphX/ a la priorité sur gen/
                index[base] = f
    return index


def _match_entity(entity_id: str, entity_name: str, index: dict[str, Path]) -> Path | None:
    """
    Cherche le mspr.c correspondant à un entity_id/name.
    Stratégie (par priorité) :
      1. entity_name lowercase → exact match
      2. entity_id sans préfixe "etype_" → exact match
      3. Recherche de suffixe dans l'index
    """
    def _norm(s: str) -> str:
        return s.lower().strip().replace(" ", "_").replace("-", "_")

    candidates: list[str] = []
    if entity_name:
        candidates.append(_norm(entity_name))
    if entity_id:
        n = entity_id
        if n.startswith("etype_"):
            n = n[6:]
        candidates.append(_norm(n))

    for c in candidates:
        if c in index:
            return index[c]

    # Recherche partielle : l'index contient le candidat ou inversement
    for c in candidates:
        for k, v in index.items():
            if k == c or k.endswith("_" + c) or c.endswith("_" + k):
                return v

    return None


# ---------------------------------------------------------------------------
# Parsing d'un fichier *_mspr.c
# ---------------------------------------------------------------------------

def _parse_mspr_c(path: Path) -> dict[str, Any]:
    """
    Extrait depuis un fichier *_mspr.c :
      tiles       : list[int]  — valeurs u16 du tableau _tiles[]
      tile_base   : int        — VRAM slot de départ (selon l'export original)
      pal_base    : int        — slot palette sprite
      tiles_count : int        — nombre de mots u16 dans _tiles[]
      is_16x16    : bool       — True si 4 tiles (32 mots), False si 1 tile (8 mots)
      pal_colors  : list[int]  — 4 couleurs RGB444 (mots u16) de la palette sprite
    """
    text = path.read_text(encoding="utf-8", errors="replace")

    # Nom de base du symbole : "goblin_mspr.c" → "goblin"
    stem = path.stem  # "goblin_mspr"
    sym  = stem[:-5] if stem.endswith("_mspr") else stem  # "goblin"

    # tiles_count
    m = re.search(rf"{re.escape(sym)}_tiles_count\s*=\s*(\d+)", text)
    tiles_count = int(m.group(1)) if m else 0

    # tile_base
    m = re.search(rf"{re.escape(sym)}_tile_base\s*=\s*(\d+)", text)
    tile_base = int(m.group(1)) if m else 0

    # pal_base
    m = re.search(rf"{re.escape(sym)}_pal_base\s*=\s*(\d+)", text)
    pal_base = int(m.group(1)) if m else 0

    # palettes[] array — 4 couleurs RGB444
    m = re.search(
        rf"{re.escape(sym)}_palettes\[\]\s*=\s*\{{([^}}]+)\}}",
        text,
        re.DOTALL,
    )
    pal_colors: list[int] = [0x0000, 0x0000, 0x0000, 0x0000]
    if m:
        raw = m.group(1)
        vals = [int(tok, 0) for tok in re.findall(r"0[xX][0-9A-Fa-f]+|\d+", raw)]
        for i in range(min(4, len(vals))):
            pal_colors[i] = vals[i]

    # tiles[] array  (les valeurs u16 entre accolades)
    m = re.search(
        rf"{re.escape(sym)}_tiles\[\]\s*=\s*\{{([^}}]+)\}}",
        text,
        re.DOTALL,
    )
    tiles: list[int] = []
    if m:
        raw = m.group(1)
        for tok in re.findall(r"0[xX][0-9A-Fa-f]+|\d+", raw):
            tiles.append(int(tok, 0))
    elif tiles_count > 0:
        # Fallback : tableau vide de zéros
        tiles = [0] * tiles_count

    # tile_count : nombre de tiles 8×8 dans ce sprite
    #   1  = 8×8   (8 mots)
    #   4  = 16×16 (32 mots, grille 2×2)
    #   16 = 32×32 (128 mots, grille 4×4)
    n_words = len(tiles)
    if n_words >= 128:
        tile_count = 16
    elif n_words >= 32:
        tile_count = 4
    else:
        tile_count = 1

    return {
        "tiles":       tiles,
        "tile_base":   tile_base,
        "pal_base":    pal_base,
        "pal_colors":  pal_colors,
        "tiles_count": tiles_count,
        "tile_count":  tile_count,
    }


# ---------------------------------------------------------------------------
# Résolution d'une pool entry
# ---------------------------------------------------------------------------

def _resolve_pool_entry(
    entry: dict,
    entity_types: list[dict],
    mspr_index: dict[str, Path],
    warnings: list[str],
    role: str = "?",
    allow_32x32: bool = True,
) -> dict[str, Any]:
    """
    Résout une entrée pool {entity_id, weight, max_count} en données sprite.
    Retourne un dict avec : tile_data, tile_count, pal_base, weight, max_count, label.

    tile_count : 1=8×8, 4=16×16, 16=32×32.
    max_count  : nombre max d'instances par salle (32×32 plafonné à 2).
    allow_32x32 : False pour les items (max 16×16).
    """
    entity_id = str(entry.get("entity_id", "") or "").strip()
    weight    = max(1, int(entry.get("weight", 1) or 1))
    max_count = max(1, int(entry.get("max_count", 4) or 4))

    # Trouver le nom de l'entité dans entity_types
    entity_name = ""
    for et in entity_types:
        if isinstance(et, dict) and et.get("id") == entity_id:
            entity_name = str(et.get("name", "") or "")
            break

    label = entity_name or entity_id or "?"

    # Chercher le mspr.c correspondant
    mspr_path = _match_entity(entity_id, entity_name, mspr_index)
    if mspr_path is None:
        warnings.append(
            f"WARN [{role}] entité '{label}' ({entity_id}) : "
            f"aucun _mspr.c trouvé dans GraphX/ — valeurs placeholder."
        )
        return {
            "tile_data":  [0] * 8,   # 1 tile vide 8×8
            "tile_count": 1,
            "pal_base":   0,
            "pal_colors": [0x0000, 0x0000, 0x0000, 0x0000],
            "weight":     weight,
            "max_count":  max_count,
            "label":      label,
        }

    info = _parse_mspr_c(mspr_path)
    if not info["tiles"]:
        warnings.append(
            f"WARN [{role}] entité '{label}' : "
            f"tiles[] vide dans {mspr_path.name} — 1 tile vide utilisée."
        )
        info["tiles"] = [0] * 8
        info["tile_count"] = 1

    tc = info["tile_count"]

    # Items ne peuvent pas être 32×32
    if not allow_32x32 and tc >= 16:
        warnings.append(
            f"WARN [{role}] entité '{label}' : sprite 32×32 non supporté pour les items "
            f"(réduit à 16×16)."
        )
        tc = 4
        info["tiles"] = info["tiles"][:32]

    # 32×32 : plafonner max_count à 2 (budget sprites)
    if tc >= 16 and max_count > 2:
        max_count = 2

    return {
        "tile_data":  info["tiles"],
        "tile_count": tc,
        "pal_base":   info["pal_base"],
        "pal_colors": info["pal_colors"],
        "weight":     weight,
        "max_count":  max_count,
        "label":      label,
    }


# ---------------------------------------------------------------------------
# Entrée publique
# ---------------------------------------------------------------------------

def export_sprites_lab(
    enemy_pool: list[dict],        # [{"entity_id": str, "weight": int}, ...]
    item_pool:  list[dict],        # [{"entity_id": str, "weight": int}, ...]
    entity_types: list[dict],
    base_dir: Path,
    out_dir: Path,
) -> tuple[Path, Path]:
    """
    Génère sprites_lab.c et sprites_lab.h dans out_dir.

    Lit les *_mspr.c depuis base_dir/GraphX/ pour chaque entité dans les pools.
    Concatène leurs tile data dans SPRITES_LAB[].
    Calcule les offsets VRAM à partir de SPR_TILE_BASE (lu dans tiles_procgen.h).

    Retourne (path_c, path_h).
    """
    base_dir = Path(base_dir)
    out_dir  = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    graphx_dir  = base_dir / "GraphX"
    mspr_index  = _build_mspr_index(graphx_dir)
    spr_tile_base = _read_spr_tile_base(out_dir)

    warnings: list[str] = []

    # --- Résolution des pools ---
    ene_entries  = [
        _resolve_pool_entry(e, entity_types, mspr_index, warnings, "enemy",
                            allow_32x32=True)
        for e in (enemy_pool or [])
        if isinstance(e, dict) and str(e.get("entity_id", "")).strip()
    ]
    item_entries = [
        _resolve_pool_entry(e, entity_types, mspr_index, warnings, "item",
                            allow_32x32=False)
        for e in (item_pool or [])
        if isinstance(e, dict) and str(e.get("entity_id", "")).strip()
    ]

    # --- Construction de SPRITES_LAB[] (tile data concaténé) ---
    # et calcul des tile slots VRAM pour chaque entrée
    all_words:   list[int] = []
    tile_cursor: int = 0  # tiles consommées depuis SPR_TILE_BASE

    def _assign_vram(entry: dict) -> int:
        """Append tile data to all_words, return VRAM slot."""
        nonlocal tile_cursor
        slot = spr_tile_base + tile_cursor
        all_words.extend(entry["tile_data"])
        # Nombre de tiles 8×8 = mots / 8
        n_tiles = max(1, len(entry["tile_data"]) // 8)
        tile_cursor += n_tiles
        return slot

    ene_slots:  list[int] = [_assign_vram(e) for e in ene_entries]
    item_slots: list[int] = [_assign_vram(e) for e in item_entries]

    n_words = len(all_words)

    # -----------------------------------------------------------------------
    # Calcul de DUNGEONGEN_ENE_SLOTS_PER (max tile_count dans le pool ennemi)
    # Calcul de DUNGEONGEN_ITEM_SLOTS_PER (max tile_count dans le pool items)
    # -----------------------------------------------------------------------
    if ene_entries:
        max_ene_sz = max(e["tile_count"] for e in ene_entries)
    else:
        max_ene_sz = 4  # défaut legacy 16x16

    if item_entries:
        max_item_sz = max(e["tile_count"] for e in item_entries)
    else:
        max_item_sz = 4  # défaut legacy 16x16

    # -----------------------------------------------------------------------
    # Génération .h
    # -----------------------------------------------------------------------
    has_ene  = len(ene_entries)  > 0
    has_item = len(item_entries) > 0

    lines_h: list[str] = [
        "/*",
        " * sprites_lab.h -- Sprites DungeonGen (généré automatiquement)",
        " * NE PAS ÉDITER — regénérer via l'onglet Procgen Assets de l'engine.",
        " */",
        "",
        "#ifndef SPRITES_LAB_H",
        "#define SPRITES_LAB_H",
        "",
        '#include "ngpc_types.h"',
        "",
        "/* ---- Tile VRAM ---- */",
        f"#define SPR_TILE_BASE  {spr_tile_base}u",
        "",
        "/* ---- Sprites array (chargé par ngpc_dungeongen_enter) ---- */",
        f"extern const u16 NGP_FAR SPRITES_LAB[{n_words}u];",
        f"extern const u16          SPRITES_LAB_COUNT;",
        "",
        "/* ---- Slots sprite par ennemi / item (max tile_count du pool) ---- */",
        f"/* 1=8x8, 4=16x16, 16=32x32 */",
        f"#define DUNGEONGEN_ENE_SLOTS_PER   {max_ene_sz}u",
        f"#define DUNGEONGEN_ITEM_SLOTS_PER  {max_item_sz}u",
        "",
    ]

    if has_ene:
        n_ene = len(ene_entries)
        lines_h += [
            f"/* ---- Pool ennemis ({n_ene} entrée(s)) ---- */",
            f"#define DUNGEONGEN_ENE_POOL_SIZE  {n_ene}u",
            f"extern const u16 s_ene_tiles[{n_ene}u];",
            f"extern const u8  s_ene_pals [{n_ene}u];",
            f"extern const u8  s_ene_sz   [{n_ene}u];   /* tile_count: 1/4/16 */",
            f"extern const u8  s_ene_max  [{n_ene}u];   /* max instances par salle */",
            f"extern const u8  s_ene_w    [{n_ene}u];",
            "",
        ]

    if has_item:
        n_item = len(item_entries)
        lines_h += [
            f"/* ---- Pool items ({n_item} entrée(s)) ---- */",
            f"#define DUNGEONGEN_ITEM_POOL_SIZE {n_item}u",
            f"extern const u16 s_item_tiles[{n_item}u];",
            f"extern const u8  s_item_pals [{n_item}u];",
            f"extern const u8  s_item_sz   [{n_item}u];   /* tile_count: 1 ou 4 */",
            f"extern const u8  s_item_max  [{n_item}u];   /* max instances par salle */",
            f"extern const u8  s_item_w    [{n_item}u];",
            "",
        ]

    # -----------------------------------------------------------------------
    # Legacy compat defines — toujours requis par ngpc_dungeongen_init()
    # En pool mode, ENE1 = pool[0], ENE2 = pool[1] (ou pool[0]), ITEM = item[0]
    # -----------------------------------------------------------------------
    _zero_pal = [0x0000, 0x0000, 0x0000, 0x0000]

    def _ent_slot(entries: list, slots: list, idx: int) -> int:
        return slots[idx] if idx < len(slots) else 0

    def _ent_pal(entries: list, idx: int) -> int:
        return entries[idx]["pal_base"] if idx < len(entries) else 0

    def _ent_colors(entries: list, idx: int) -> list[int]:
        return entries[idx]["pal_colors"] if idx < len(entries) else _zero_pal

    ene1_slot   = _ent_slot(ene_entries, ene_slots, 0)
    ene1_pal    = _ent_pal(ene_entries, 0)
    ene1_colors = _ent_colors(ene_entries, 0)

    ene2_slot   = _ent_slot(ene_entries, ene_slots, 1) if len(ene_entries) > 1 else ene1_slot
    ene2_pal    = _ent_pal(ene_entries, 1) if len(ene_entries) > 1 else ene1_pal
    ene2_colors = _ent_colors(ene_entries, 1) if len(ene_entries) > 1 else ene1_colors

    item_slot   = _ent_slot(item_entries, item_slots, 0)
    item_pal    = _ent_pal(item_entries, 0)
    item_colors = _ent_colors(item_entries, 0)

    lines_h += [
        "/* ---- Compat legacy + init palettes (ngpc_dungeongen_init) ---- */",
        f"#define SPR_ENE1_TILE     {ene1_slot}u",
        f"#define PAL_SPR_ENE1      {ene1_pal}u",
        f"#define PAL_SPR_ENE1_C0   0x{ene1_colors[0]:04X}u",
        f"#define PAL_SPR_ENE1_C1   0x{ene1_colors[1]:04X}u",
        f"#define PAL_SPR_ENE1_C2   0x{ene1_colors[2]:04X}u",
        f"#define PAL_SPR_ENE1_C3   0x{ene1_colors[3]:04X}u",
        "",
        f"#define SPR_ENE2_TILE     {ene2_slot}u",
        f"#define PAL_SPR_ENE2      {ene2_pal}u",
        f"#define PAL_SPR_ENE2_C0   0x{ene2_colors[0]:04X}u",
        f"#define PAL_SPR_ENE2_C1   0x{ene2_colors[1]:04X}u",
        f"#define PAL_SPR_ENE2_C2   0x{ene2_colors[2]:04X}u",
        f"#define PAL_SPR_ENE2_C3   0x{ene2_colors[3]:04X}u",
        "",
        f"#define SPR_ITEM_TILE     {item_slot}u",
        f"#define PAL_SPR_ITEM      {item_pal}u",
        f"#define PAL_SPR_ITEM_C0   0x{item_colors[0]:04X}u",
        f"#define PAL_SPR_ITEM_C1   0x{item_colors[1]:04X}u",
        f"#define PAL_SPR_ITEM_C2   0x{item_colors[2]:04X}u",
        f"#define PAL_SPR_ITEM_C3   0x{item_colors[3]:04X}u",
        "",
    ]

    lines_h += ["#endif /* SPRITES_LAB_H */"]

    # -----------------------------------------------------------------------
    # Génération .c
    # -----------------------------------------------------------------------
    lines_c: list[str] = [
        "/*",
        " * sprites_lab.c -- Sprites DungeonGen (généré automatiquement)",
        " * NE PAS ÉDITER.",
        " */",
        "",
        '#include "sprites_lab.h"',
        "",
        "/* Tile data concaténé (tous sprites pool) */",
        f"const u16 NGP_FAR SPRITES_LAB[{n_words}u] = {{",
    ]

    # Émettre le tile data avec commentaires par entité
    word_idx = 0
    for entries_group, slots_group, label_prefix in [
        (ene_entries,  ene_slots,  "enemy"),
        (item_entries, item_slots, "item"),
    ]:
        for entry, slot in zip(entries_group, slots_group):
            lbl = entry["label"]
            words = entry["tile_data"]
            n_tiles = max(1, len(words) // 8)
            lines_c.append(f"    /* {label_prefix}: {lbl} — slot {slot}, {n_tiles} tile(s) */")
            for ti in range(0, len(words), 8):
                row = words[ti:ti + 8]
                hex_vals = ", ".join(f"0x{w:04X}u" for w in row)
                lines_c.append(f"    {hex_vals},")
            word_idx += len(words)

    lines_c += [
        "};",
        "",
        f"const u16 SPRITES_LAB_COUNT = {n_words}u;",
        "",
    ]

    def _u16_list(vals: list[int]) -> str:
        return ", ".join(f"{v}u" for v in vals)

    def _u8_list(vals: list[int]) -> str:
        return ", ".join(f"{v}u" for v in vals)

    if has_ene:
        n_ene = len(ene_entries)
        lines_c += [
            "/* ---- Pool ennemis ---- */",
            f"const u16 s_ene_tiles[{n_ene}u] = {{ {_u16_list(ene_slots)} }};",
            f"const u8  s_ene_pals [{n_ene}u] = {{ {_u8_list([e['pal_base']   for e in ene_entries])} }};",
            f"const u8  s_ene_sz   [{n_ene}u] = {{ {_u8_list([e['tile_count'] for e in ene_entries])} }};",
            f"const u8  s_ene_max  [{n_ene}u] = {{ {_u8_list([e['max_count']  for e in ene_entries])} }};",
            f"const u8  s_ene_w    [{n_ene}u] = {{ {_u8_list([e['weight']     for e in ene_entries])} }};",
            "",
        ]

    if has_item:
        n_item = len(item_entries)
        lines_c += [
            "/* ---- Pool items ---- */",
            f"const u16 s_item_tiles[{n_item}u] = {{ {_u16_list(item_slots)} }};",
            f"const u8  s_item_pals [{n_item}u] = {{ {_u8_list([e['pal_base']   for e in item_entries])} }};",
            f"const u8  s_item_sz   [{n_item}u] = {{ {_u8_list([e['tile_count'] for e in item_entries])} }};",
            f"const u8  s_item_max  [{n_item}u] = {{ {_u8_list([e['max_count']  for e in item_entries])} }};",
            f"const u8  s_item_w    [{n_item}u] = {{ {_u8_list([e['weight']     for e in item_entries])} }};",
            "",
        ]

    # -----------------------------------------------------------------------
    # Écriture
    # -----------------------------------------------------------------------
    out_h = out_dir / "sprites_lab.h"
    out_c = out_dir / "sprites_lab.c"
    out_h.write_text("\n".join(lines_h), encoding="utf-8")
    out_c.write_text("\n".join(lines_c), encoding="utf-8")

    for w in warnings:
        print(w)

    print(
        f"sprites_lab: {len(ene_entries)} ennemi(s), {len(item_entries)} item(s), "
        f"{n_words} mots u16, SPR_TILE_BASE={spr_tile_base}"
    )

    return out_c, out_h
