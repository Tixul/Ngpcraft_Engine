from __future__ import annotations

from typing import Any


_CELL_SIZE_TO_TILES: dict[str, tuple[int, int]] = {
    "8x8": (1, 1),
    "16x16": (2, 2),
    "32x32": (4, 4),
}


def parse_dungeongen_cell_size(cell_cfg: Any) -> tuple[int, int]:
    """Return source-cell size in NGPC 8x8 tiles for a stored cell-size label."""
    key = str(cell_cfg or "16x16").strip().lower()
    return _CELL_SIZE_TO_TILES.get(key, (2, 2))


def dungeongen_cell_label(cell_w_tiles: int, cell_h_tiles: int) -> str:
    """Return a human-readable pixel label for a cell size."""
    return f"{int(cell_w_tiles) * 8}x{int(cell_h_tiles) * 8}"


def dungeongen_group_cells_per_variant(
    *,
    source_cell_w_tiles: int,
    source_cell_h_tiles: int,
    runtime_cell_w_tiles: int,
    runtime_cell_h_tiles: int,
) -> int:
    """Return how many source cells are needed to build one runtime metatile."""
    src_w = max(1, int(source_cell_w_tiles))
    src_h = max(1, int(source_cell_h_tiles))
    rt_w = max(1, int(runtime_cell_w_tiles))
    rt_h = max(1, int(runtime_cell_h_tiles))

    if rt_w < src_w or rt_h < src_h:
        raise ValueError(
            "DungeonGen tileset incompatible: runtime cell "
            f"{dungeongen_cell_label(rt_w, rt_h)} is smaller than source cell "
            f"{dungeongen_cell_label(src_w, src_h)}."
        )
    if (rt_w % src_w) != 0 or (rt_h % src_h) != 0:
        raise ValueError(
            "DungeonGen tileset incompatible: runtime cell "
            f"{dungeongen_cell_label(rt_w, rt_h)} must be an integer multiple of source cell "
            f"{dungeongen_cell_label(src_w, src_h)}."
        )
    return (rt_w // src_w) * (rt_h // src_h)


def normalize_dungeongen_runtime_cells(
    *,
    source_cell_w_tiles: int,
    source_cell_h_tiles: int,
    requested_cell_w_tiles: int,
    requested_cell_h_tiles: int,
    tile_roles: dict[str, list[int]] | None = None,
) -> tuple[int, int, str | None]:
    """
    Normalize legacy simple-role setups.

    If every role maps to at most one source cell, a larger runtime cell size would
    only repeat that source cell. In that case we clamp the runtime back to the
    source size for backward compatibility.
    """
    src_w = max(1, min(4, int(source_cell_w_tiles)))
    src_h = max(1, min(4, int(source_cell_h_tiles)))
    req_w = max(1, min(4, int(requested_cell_w_tiles)))
    req_h = max(1, min(4, int(requested_cell_h_tiles)))

    wants_grouping = (req_w > src_w) or (req_h > src_h)
    if not wants_grouping or not isinstance(tile_roles, dict) or not tile_roles:
        return req_w, req_h, None

    non_empty_lengths: list[int] = []
    for raw in tile_roles.values():
        if isinstance(raw, list):
            n = len(raw)
        elif raw in (None, ""):
            n = 0
        else:
            n = 1
        if n > 0:
            non_empty_lengths.append(n)

    if non_empty_lengths and max(non_empty_lengths) <= 1:
        reason = (
            "Legacy DungeonGen role mapping detected: each role references a single "
            f"source cell ({dungeongen_cell_label(src_w, src_h)}). "
            f"Runtime cell size has been clamped to {dungeongen_cell_label(src_w, src_h)}. "
            "To use larger runtime cells, assign grouped source cells per role variant."
        )
        return src_w, src_h, reason

    return req_w, req_h, None
