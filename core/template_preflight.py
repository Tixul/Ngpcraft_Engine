"""Preflight checks for Template 2026 compatibility."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from core.rgb444 import snap


@dataclass(frozen=True)
class TemplateIssue:
    """One blocking issue found before a template-ready export."""

    scene_label: str
    asset_label: str
    message: str

    def summary(self) -> str:
        """Return a compact user-facing summary line."""
        return f"[{self.scene_label}] {self.asset_label}: {self.message}"


def _is_enabled(obj: dict) -> bool:
    return bool(obj.get("export", True)) if isinstance(obj, dict) else False


def _visible_rgb444_count(img: Image.Image, *, x0: int, y0: int, w: int, h: int) -> int:
    rgba = img.convert("RGBA")
    px = rgba.load()
    colors: set[tuple[int, int, int]] = set()
    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            r, g, b, a = px[x, y]
            if a >= 128:
                colors.add(snap(r, g, b))
    return len(colors)


def _sprite_needs_auto_split(img: Image.Image) -> bool:
    """Return True if the sprite can be handled via 2-layer auto-split."""
    try:
        from core.layer_split import split_layers
        result = split_layers(img)
        return result.n_layers_needed == 2 and len(result.layers) >= 2
    except Exception:
        return False


def _first_sprite_color_issue(img: Image.Image, frame_w: int, frame_h: int) -> str | None:
    frames_x = img.width // frame_w
    frames_y = img.height // frame_h
    frame_idx = 0
    for fy in range(frames_y):
        for fx in range(frames_x):
            for ty in range(frame_h // 8):
                for tx in range(frame_w // 8):
                    count = _visible_rgb444_count(
                        img,
                        x0=fx * frame_w + tx * 8,
                        y0=fy * frame_h + ty * 8,
                        w=8,
                        h=8,
                    )
                    if count > 3:
                        # If the sprite can be auto-split into 2 layers the
                        # exporter handles it transparently — not a blocking issue.
                        if _sprite_needs_auto_split(img):
                            return None
                        return (
                            f"frame {frame_idx} tile ({tx},{ty}) uses {count} visible colors "
                            f"(max 3)"
                        )
            frame_idx += 1
    return None


def _first_tilemap_color_issue(img: Image.Image) -> str | None:
    tiles_x = img.width // 8
    tiles_y = img.height // 8
    for ty in range(tiles_y):
        for tx in range(tiles_x):
            count = _visible_rgb444_count(img, x0=tx * 8, y0=ty * 8, w=8, h=8)
            if count > 3:
                return f"tile ({tx},{ty}) uses {count} visible colors (max 3 per plane)"
    return None


def _check_sprite(scene_label: str, project_dir: Path, spr: dict) -> list[TemplateIssue]:
    issues: list[TemplateIssue] = []
    rel = str(spr.get("file") or "").strip()
    name = str(spr.get("name") or Path(rel).stem or "sprite")
    if not rel:
        issues.append(TemplateIssue(scene_label, name, "missing source file"))
        return issues

    path = Path(rel)
    if not path.is_absolute():
        path = project_dir / path
    if not path.exists():
        issues.append(TemplateIssue(scene_label, name, f"missing file: {rel}"))
        return issues

    try:
        frame_w = int(spr.get("frame_w", 8) or 8)
        frame_h = int(spr.get("frame_h", 8) or 8)
    except Exception:
        issues.append(TemplateIssue(scene_label, name, "invalid frame size"))
        return issues

    if frame_w <= 0 or frame_h <= 0:
        issues.append(TemplateIssue(scene_label, name, "frame size must be > 0"))
        return issues
    if (frame_w % 8) or (frame_h % 8):
        issues.append(TemplateIssue(scene_label, name, f"frame size {frame_w}x{frame_h} must be a multiple of 8"))
        return issues

    try:
        img = Image.open(path).convert("RGBA")
    except Exception as exc:
        issues.append(TemplateIssue(scene_label, name, f"cannot open image: {exc}"))
        return issues

    if (img.width % frame_w) or (img.height % frame_h):
        issues.append(
            TemplateIssue(
                scene_label,
                name,
                f"image size {img.width}x{img.height} must align with frame size {frame_w}x{frame_h}",
            )
        )
        return issues

    color_issue = _first_sprite_color_issue(img, frame_w, frame_h)
    if color_issue:
        issues.append(TemplateIssue(scene_label, name, color_issue))
    return issues


def _check_tilemap(scene_label: str, project_dir: Path, tm: dict) -> list[TemplateIssue]:
    issues: list[TemplateIssue] = []
    rel = str(tm.get("file") or "").strip()
    name = str(tm.get("name") or Path(rel).stem or "tilemap")
    if not rel:
        issues.append(TemplateIssue(scene_label, name, "missing source file"))
        return issues

    path = Path(rel)
    if not path.is_absolute():
        path = project_dir / path
    if not path.exists():
        issues.append(TemplateIssue(scene_label, name, f"missing file: {rel}"))
        return issues

    try:
        img = Image.open(path).convert("RGBA")
    except Exception as exc:
        issues.append(TemplateIssue(scene_label, name, f"cannot open image: {exc}"))
        return issues

    if (img.width % 8) or (img.height % 8):
        pw = ((img.width + 7) // 8) * 8
        ph = ((img.height + 7) // 8) * 8
        padded = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        padded.paste(img, (0, 0))
        img = padded

    color_issue = _first_tilemap_color_issue(img)
    if color_issue:
        issues.append(TemplateIssue(scene_label, name, color_issue))
    return issues


def _check_dgen_tileset(project_dir: Path, project_data: dict) -> list[TemplateIssue]:
    """Check the DungeonGen tileset PNG for NGPC color constraints (max 3 per 8×8 block)."""
    issues: list[TemplateIssue] = []
    pa = project_data.get("procgen_assets", {}) if isinstance(project_data, dict) else {}
    da = (pa.get("dungeongen") or {}) if isinstance(pa, dict) else {}
    if not isinstance(da, dict):
        return issues

    png_rel = str(da.get("tileset_png") or "").strip()
    if not png_rel:
        return issues

    png_path = Path(png_rel) if Path(png_rel).is_absolute() else project_dir / png_rel
    if not png_path.exists():
        # File-not-found already reported by export_validation; skip here.
        return issues

    try:
        img = Image.open(png_path).convert("RGBA")
    except Exception as exc:
        issues.append(TemplateIssue("project", "DungeonGen tileset", f"cannot open image: {exc}"))
        return issues

    # Pad to 8px multiple just in case
    if (img.width % 8) or (img.height % 8):
        pw = ((img.width + 7) // 8) * 8
        ph = ((img.height + 7) // 8) * 8
        padded = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        padded.paste(img, (0, 0))
        img = padded

    color_issue = _first_tilemap_color_issue(img)
    if color_issue:
        issues.append(TemplateIssue(
            "project",
            f"DungeonGen tileset ({png_path.name})",
            color_issue,
        ))
    return issues


def collect_template_2026_issues(
    *,
    project_data: dict,
    project_dir: Path,
    scenes: list[dict] | None = None,
) -> list[TemplateIssue]:
    """Return blocking compatibility issues for a template-ready export."""
    issues: list[TemplateIssue] = []
    scene_list = scenes if scenes is not None else list(project_data.get("scenes") or [])
    for scene in scene_list:
        if not isinstance(scene, dict):
            continue
        scene_label = str(scene.get("label") or scene.get("id") or "scene")
        for spr in scene.get("sprites") or []:
            if isinstance(spr, dict) and _is_enabled(spr):
                issues.extend(_check_sprite(scene_label, project_dir, spr))
        for tm in scene.get("tilemaps") or []:
            if isinstance(tm, dict) and _is_enabled(tm):
                issues.extend(_check_tilemap(scene_label, project_dir, tm))
    # DungeonGen tileset — project-level color check (same hardware constraint as tilemaps)
    issues.extend(_check_dgen_tileset(project_dir, project_data))
    return issues


def format_template_2026_report(issues: list[TemplateIssue], *, max_items: int = 12) -> str:
    """Format the first issues into a short report block."""
    lines = [f"- {issue.summary()}" for issue in issues[:max_items]]
    remaining = len(issues) - min(len(issues), max_items)
    if remaining > 0:
        lines.append(f"- ... + {remaining} more")
    return "\n".join(lines)
