# Asset Pipeline Example

End-to-end workflow for a background tilemap:

## 1. Export tilemap C + optional tile binary

```bash
python tools/ngpc_tilemap.py assets/level1_bg.png \
  -o GraphX/level1_bg.c -n level1_bg --header \
  --tiles-bin GraphX/level1_bg_tiles.bin
```

For fixed full-screen screens (intro/title), prefer raw byte tiles:

```bash
python tools/ngpc_tilemap.py assets/title.png \
  -o GraphX/title_intro.c -n title_intro --header \
  --emit-u8-tiles --black-is-transparent --no-dedupe
```

Outputs:
- `GraphX/level1_bg.c/.h` (tiles, map, palettes)
- Optional `GraphX/level1_bg_tiles.bin` (raw tile words, little-endian)
- Optional with `--emit-u8-tiles`: `<name>_tiles_u8[]` + `<name>_tile_count`

## 2. Compress tiles binary (optional)

```bash
python tools/ngpc_compress.py GraphX/level1_bg_tiles.bin \
  -o GraphX/level1_bg_tiles_lz.c -n level1_bg_tiles -m lz77 --header
```

Resulting runtime symbols:
- `level1_bg_tiles_lz[]`
- `level1_bg_tiles_lz_len`

## 3. Runtime loading

See `examples/asset_pipeline_example.c`:
- Preferred: use `src/gfx/ngpc_tilemap_blit.h` macros (safe path, windjammer-style).
- `example_bg_blit_scr1(...)` / `example_bg_blit_scr2(...)` for the safe path.
- `example_bg_load_raw(...)` and `example_bg_load_lz(...)` show the classic helper path.
  If you use the updated template, the tile-load helpers are configured for cc900 ROM pointers
  (`NGP_FAR=__far`). If you still see corruption, use the macro path as a fallback.

## 4. Integrate into project

1. Add generated `GraphX/*.c` files to your build object list.
2. Include generated headers in your game code.
3. Call one load function in your state init (`title_init`, `level_init`, etc.).

Notes:
- Template policy: index `0` is transparency; max 3 visible colors per 8x8 tile.
- Tilemap limits: max 32x32 cells and 512 unique tiles.
- By default opaque black is preserved; use `--black-is-transparent` for legacy intro behavior.
