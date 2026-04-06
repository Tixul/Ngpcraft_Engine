"""
core/report_html.py - Generate a simple HTML report for a .ngpcraft project.

Goal: provide a quick, shareable overview (budgets, scenes, missing files)
without building/compiling anything.
"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from core.project_model import (
    TILE_MAX,
    TILE_USER_START,
    PAL_MAX_SPR,
    sprite_tile_estimate,
    scene_tile_estimate,
    scene_pal_estimate,
    project_tile_estimate,
    project_pal_estimate,
    analyze_scene_bg_palette_banks,
    analyze_scene_bg_palette_banks_exact,
)


def _esc(s: object) -> str:
    return html.escape(str(s), quote=True)


def build_report_html(
    project_data: dict,
    project_path: Path | None,
) -> str:
    """Return a standalone HTML summary for a `.ngpcraft` project.

    The report is intended for quick inspection and sharing: budgets, scene
    contents, palette sharing and missing asset files. It does not invoke any
    exporter tool and only relies on project metadata plus filesystem checks.
    """
    name = project_data.get("name", "?")
    graphx_dir = project_data.get("graphx_dir", "GraphX")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    total_tiles = project_tile_estimate(project_data)
    total_pals = project_pal_estimate(project_data)

    usable_tiles = TILE_MAX - TILE_USER_START
    over_tiles = total_tiles > usable_tiles
    over_pals = total_pals > PAL_MAX_SPR

    base_dir = project_path.parent if project_path else None

    scenes = project_data.get("scenes", []) or []

    def abs_path(rel: str) -> Path:
        p = Path(rel)
        if base_dir and not p.is_absolute():
            return base_dir / p
        return p

    missing: list[str] = []
    for scene in scenes:
        for spr in scene.get("sprites", []) or []:
            p = abs_path(spr.get("file", ""))
            if spr.get("file") and not p.exists():
                missing.append(str(p))
        for tm in scene.get("tilemaps", []) or []:
            p = abs_path(tm.get("file", ""))
            if tm.get("file") and not p.exists():
                missing.append(str(p))

    # Palette sharing stats (by fixed_palette string)
    fp_counts: dict[str, int] = {}
    for scene in scenes:
        for spr in scene.get("sprites", []) or []:
            fp = spr.get("fixed_palette") or ""
            if fp:
                fp_counts[fp] = fp_counts.get(fp, 0) + 1

    shared = sorted(((k, v) for (k, v) in fp_counts.items() if v >= 2), key=lambda kv: (-kv[1], kv[0]))

    def _fmt_bg_groups(analysis: dict | None) -> tuple[list[str], bool]:
        lines: list[str] = []
        estimated = False
        if not isinstance(analysis, dict):
            return lines, estimated
        for plane in ("scr1", "scr2"):
            plane_info = analysis.get(plane)
            if plane_info is None:
                continue
            estimated = estimated or bool(getattr(plane_info, "is_estimated", False))
            groups = getattr(plane_info, "identical_groups", ()) or ()
            if not groups:
                continue
            text = " / ".join(", ".join(_esc(name) for name in group) for group in groups)
            lines.append(f"<b>{plane.upper()}</b>: {text}")
        return lines, estimated

    bg_rows: list[tuple[str, list[str], list[str], bool]] = []
    for scene in scenes:
        label = str(scene.get("label", "?") or "?")
        soft = analyze_scene_bg_palette_banks(scene, base_dir)
        exact = analyze_scene_bg_palette_banks_exact(scene, base_dir)
        soft_lines, soft_est = _fmt_bg_groups(soft)
        exact_lines, exact_est = _fmt_bg_groups(exact)
        if soft_lines or exact_lines:
            bg_rows.append((label, exact_lines, soft_lines, bool(soft_est or exact_est)))

    css = """
    :root { color-scheme: dark; }
    body { font-family: Segoe UI, Arial, sans-serif; background:#14141a; color:#e8e8ee; margin: 18px; }
    h1,h2,h3 { margin: 0.4em 0; }
    .muted { color:#a9a9b2; }
    .card { background:#1b1b23; border:1px solid #2a2a36; border-radius: 10px; padding: 12px 14px; margin: 10px 0; }
    .bad { color:#ff8a8a; font-weight: 700; }
    .ok  { color:#7fe07f; font-weight: 700; }
    table { width:100%; border-collapse: collapse; margin-top: 8px; }
    th, td { border-bottom: 1px solid #2a2a36; padding: 6px 8px; text-align: left; vertical-align: top; }
    th { color:#bfc3d0; font-weight: 600; }
    code { color:#c8d1ff; }
    ul { margin: 6px 0 0 18px; }
    """

    parts: list[str] = []
    parts.append("<!doctype html>")
    parts.append("<html><head>")
    parts.append('<meta charset="utf-8">')
    parts.append(f"<title>{_esc(name)} — NgpCraft Engine report</title>")
    parts.append(f"<style>{css}</style>")
    parts.append("</head><body>")

    parts.append(f"<h1>{_esc(name)}</h1>")
    parts.append('<div class="muted">NgpCraft Engine — report</div>')
    parts.append(f'<div class="muted">Generated: {_esc(now)}</div>')
    if project_path:
        parts.append(f'<div class="muted">Project: <code>{_esc(project_path)}</code></div>')
    parts.append(f'<div class="muted">GraphX dir: <code>{_esc(graphx_dir)}</code></div>')

    badge_bad = '<span class="bad">OVERFLOW</span>'
    badge_ok = '<span class="ok">OK</span>'
    badge_none = '<span class="muted">(none)</span>'

    parts.append('<div class="card">')
    parts.append("<h2>Budgets</h2>")
    parts.append(
        f"<div>Tiles (sprites): <b>{total_tiles}</b> / <b>{usable_tiles}</b> "
        f"{badge_bad if over_tiles else badge_ok}</div>"
    )
    parts.append(
        f"<div>Palettes (sprites): <b>{total_pals}</b> / <b>{PAL_MAX_SPR}</b> "
        f"{badge_bad if over_pals else badge_ok}</div>"
    )
    parts.append("</div>")

    parts.append('<div class="card">')
    parts.append("<h2>Scenes</h2>")
    if not scenes:
        parts.append('<div class="muted">(no scenes)</div>')
    else:
        parts.append("<table>")
        parts.append("<tr><th>Scene</th><th>Tiles ~</th><th>Palettes ~</th><th>Sprites</th><th>Tilemaps</th></tr>")
        for scene in scenes:
            label = scene.get("label", "?")
            tiles = scene_tile_estimate(scene)
            pals = scene_pal_estimate(scene)

            spr_lines: list[str] = []
            for spr in scene.get("sprites", []) or []:
                rel = spr.get("file", "?")
                fw = spr.get("frame_w", 8)
                fh = spr.get("frame_h", 8)
                fc = spr.get("frame_count", 1)
                t_est = sprite_tile_estimate(spr)
                fp = spr.get("fixed_palette") or ""
                shared_tag = " ↔" if fp else ""
                spr_lines.append(
                    f"{_esc(Path(rel).name)} ({fw}×{fh}×{fc}) — {t_est} tiles{_esc(shared_tag)}"
                )
            tm_lines: list[str] = []
            for tm in scene.get("tilemaps", []) or []:
                rel = tm.get("file", "?")
                tm_lines.append(_esc(Path(rel).name))

            parts.append(
                "<tr>"
                f"<td><b>{_esc(label)}</b></td>"
                f"<td>{tiles}</td>"
                f"<td>{pals}</td>"
                f"<td>{'<br>'.join(spr_lines) if spr_lines else badge_none}</td>"
                f"<td>{'<br>'.join(tm_lines) if tm_lines else badge_none}</td>"
                "</tr>"
            )
        parts.append("</table>")
    parts.append("</div>")

    parts.append('<div class="card">')
    parts.append("<h2>BG Palette Banks</h2>")
    if not bg_rows:
        parts.append('<div class="muted">(no identical BG palette banks detected)</div>')
    else:
        parts.append("<table>")
        parts.append("<tr><th>Scene</th><th>Exact reuse</th><th>Same contents</th></tr>")
        for label, exact_lines, soft_lines, estimated in bg_rows:
            exact_html = "<br>".join(exact_lines) if exact_lines else badge_none
            soft_html = "<br>".join(soft_lines) if soft_lines else badge_none
            if estimated:
                soft_html += '<br><span class="muted">(estimated)</span>'
            parts.append(
                "<tr>"
                f"<td><b>{_esc(label)}</b></td>"
                f"<td>{exact_html}</td>"
                f"<td>{soft_html}</td>"
                "</tr>"
            )
        parts.append("</table>")
    parts.append("</div>")

    parts.append('<div class="card">')
    parts.append("<h2>Shared palettes</h2>")
    if not shared:
        parts.append('<div class="muted">(none)</div>')
    else:
        parts.append("<ul>")
        for fp, cnt in shared[:30]:
            parts.append(f"<li><b>{cnt} sprites</b> — <code>{_esc(fp)}</code></li>")
        if len(shared) > 30:
            parts.append(f"<li class=\"muted\">(+{len(shared) - 30} more)</li>")
        parts.append("</ul>")
    parts.append("</div>")

    parts.append('<div class="card">')
    parts.append("<h2>Missing files</h2>")
    if not missing:
        parts.append('<div class="ok">None ✓</div>')
    else:
        parts.append("<ul>")
        for p in missing[:80]:
            parts.append(f"<li><code>{_esc(p)}</code></li>")
        if len(missing) > 80:
            parts.append(f"<li class=\"muted\">(+{len(missing) - 80} more)</li>")
        parts.append("</ul>")
    parts.append("</div>")

    parts.append("</body></html>")
    return "\n".join(parts)
