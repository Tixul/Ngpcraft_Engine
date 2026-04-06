"""Static validation helpers for the export pipeline contract.

These checks do not run the exporters. They look for high-signal issues that
often lead to broken or confusing exports: output filename collisions, invalid
export_dir layouts, and stale/missing generated autogen files.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from i18n.lang import tr


_RE_SAFE = re.compile(r"[^0-9a-zA-Z_]+")


@dataclass
class ExportValidationIssue:
    """One export pipeline issue detected from project metadata/files."""

    severity: str
    message: str
    scene_label: str = ""
    asset_label: str = ""


def _safe_ident(value: str) -> str:
    text = (value or "").strip()
    text = _RE_SAFE.sub("_", text).strip("_")
    if not text:
        return "scene"
    if text[0].isdigit():
        text = "_" + text
    return text.lower()


def _abs_path(base_dir: Path | None, rel: str) -> Path:
    path = Path(rel)
    if path.is_absolute() or base_dir is None:
        return path
    return base_dir / path


def _export_enabled(obj: dict) -> bool:
    return not (isinstance(obj, dict) and obj.get("export", True) is False)


def _sprite_export_name(spr: dict) -> str:
    name = str(spr.get("name") or "").strip()
    if name:
        return name
    rel = str(spr.get("file") or "").strip()
    return Path(rel).stem if rel else "sprite"


def _sprite_fingerprint(base_dir: Path | None, spr: dict) -> tuple[str, int, int, int, str]:
    rel = str(spr.get("file") or "").strip()
    abs_p = _abs_path(base_dir, rel)
    return (
        str(abs_p).lower(),
        int(spr.get("frame_w", 8) or 8),
        int(spr.get("frame_h", 8) or 8),
        int(spr.get("frame_count", 1) or 1),
        str(spr.get("fixed_palette") or "").strip().lower(),
    )


def _tilemap_output_base(tm: dict) -> str:
    rel = str(tm.get("file") or "").strip()
    stem = Path(rel).stem
    if stem.lower().endswith("_scr1") or stem.lower().endswith("_scr2"):
        stem = stem[:-5]
    return stem


def _tilemap_fingerprint(base_dir: Path | None, tm: dict) -> tuple[str, str]:
    rel = str(tm.get("file") or "").strip()
    abs_p = _abs_path(base_dir, rel)
    return (str(abs_p).lower(), _tilemap_output_base(tm).lower())


def _audio_manifest_path(project_dir: Path | None, project_data: dict) -> Path | None:
    audio = project_data.get("audio", {}) if isinstance(project_data, dict) else {}
    if not isinstance(audio, dict):
        return None
    rel = str(audio.get("manifest") or "").strip()
    if not rel:
        return None
    return _abs_path(project_dir, rel)


def collect_export_pipeline_issues(project_dir: Path | None, project_data: dict) -> list[ExportValidationIssue]:
    """Return static export pipeline issues with good signal/no exporter run."""

    if not isinstance(project_data, dict):
        return []

    issues: list[ExportValidationIssue] = []
    scenes = [s for s in (project_data.get("scenes") or []) if isinstance(s, dict)]

    export_dir_rel = str(project_data.get("export_dir") or "").strip()
    export_dir = _abs_path(project_dir, export_dir_rel) if export_dir_rel and project_dir else None
    export_has_artifacts = False

    if export_dir is not None:
        if export_dir.exists() and not export_dir.is_dir():
            issues.append(ExportValidationIssue("bad", tr("proj.validation_export_dir_is_file")))
        elif project_dir is not None:
            try:
                export_dir.resolve().relative_to(project_dir.resolve())
            except Exception:
                issues.append(ExportValidationIssue("warn", tr("proj.validation_export_dir_outside")))
        if export_dir.exists() and export_dir.is_dir():
            export_has_artifacts = any(
                [
                    (export_dir / "assets_autogen.mk").exists(),
                    (export_dir / "scenes_autogen.h").exists(),
                    (export_dir / "scenes_autogen.c").exists(),
                    any(export_dir.glob("scene_*.h")),
                    any(export_dir.glob("scene_*_level.h")),
                    any(export_dir.glob("*.c")),
                ]
            )

    scene_safe_seen: dict[str, str] = {}
    sprite_name_seen: dict[str, tuple[tuple[str, int, int, int, str], str, str]] = {}
    tilemap_name_seen: dict[str, tuple[tuple[str, str], str, str]] = {}

    for scene in scenes:
        scene_label = str(scene.get("label") or "").strip() or "?"
        scene_id = str(scene.get("id") or "").strip()
        scene_safe = _safe_ident(scene_label or scene_id or "scene")

        prev_scene = scene_safe_seen.get(scene_safe)
        if prev_scene and prev_scene != scene_label:
            issues.append(
                ExportValidationIssue(
                    "bad",
                    tr("proj.validation_scene_safe_collision", first=prev_scene, second=scene_label, safe=scene_safe),
                    scene_label=scene_label,
                )
            )
        else:
            scene_safe_seen[scene_safe] = scene_label

        for spr in (scene.get("sprites") or []):
            if not isinstance(spr, dict) or not _export_enabled(spr):
                continue
            export_name = _sprite_export_name(spr)
            fp = _sprite_fingerprint(project_dir, spr)
            prev = sprite_name_seen.get(export_name.lower())
            if prev and prev[0] != fp:
                issues.append(
                    ExportValidationIssue(
                        "bad",
                        tr("proj.validation_sprite_export_name_collision", first=prev[1], second=scene_label, name=export_name),
                        scene_label=scene_label,
                        asset_label=export_name,
                    )
                )
            else:
                sprite_name_seen[export_name.lower()] = (fp, scene_label, export_name)

        for tm in (scene.get("tilemaps") or []):
            if not isinstance(tm, dict) or not _export_enabled(tm):
                continue
            base = _tilemap_output_base(tm)
            fp = _tilemap_fingerprint(project_dir, tm)
            prev = tilemap_name_seen.get(base.lower())
            if prev and prev[0] != fp:
                issues.append(
                    ExportValidationIssue(
                        "bad",
                        tr("proj.validation_tilemap_export_name_collision", first=prev[1], second=scene_label, name=base),
                        scene_label=scene_label,
                        asset_label=base,
                    )
                )
            else:
                tilemap_name_seen[base.lower()] = (fp, scene_label, base)

        if export_dir is not None and export_has_artifacts:
            level_h = export_dir / f"scene_{scene_safe}_level.h"
            loader_h = export_dir / f"scene_{scene_safe}.h"
            if not level_h.exists():
                issues.append(
                    ExportValidationIssue(
                        "warn",
                        tr("proj.validation_missing_scene_level_header", path=level_h.name),
                        scene_label=scene_label,
                    )
                )
            if not loader_h.exists():
                issues.append(
                    ExportValidationIssue(
                        "warn",
                        tr("proj.validation_missing_scene_loader_header", path=loader_h.name),
                        scene_label=scene_label,
                    )
                )

    if export_dir is not None and export_has_artifacts:
        assets_mk = export_dir / "assets_autogen.mk"
        scenes_h = export_dir / "scenes_autogen.h"
        scenes_c = export_dir / "scenes_autogen.c"
        if not assets_mk.exists():
            issues.append(ExportValidationIssue("warn", tr("proj.validation_missing_assets_autogen")))
        else:
            try:
                mk_text = assets_mk.read_text(encoding="utf-8", errors="replace")
            except Exception:
                mk_text = ""
            if "audio_autogen.mk" not in mk_text:
                issues.append(ExportValidationIssue("warn", tr("proj.validation_assets_autogen_missing_audio_include")))
        if not (scenes_h.exists() and scenes_c.exists()):
            issues.append(ExportValidationIssue("warn", tr("proj.validation_missing_scenes_autogen")))

    manifest_path = _audio_manifest_path(project_dir, project_data)
    if manifest_path is not None and manifest_path.exists():
        exports_dir = manifest_path.parent
        has_audio_exports = exports_dir.exists() and any(exports_dir.glob("*.c"))
        if has_audio_exports:
            mk_parent = export_dir if export_dir is not None else exports_dir
            audio_mk = mk_parent / "audio_autogen.mk"
            if export_has_artifacts and not audio_mk.exists():
                issues.append(ExportValidationIssue("warn", tr("proj.validation_missing_audio_autogen", path=str(mk_parent))))

    return issues


# ---------------------------------------------------------------------------
# Globals consistency checks (C1/C2) — appended to errs list
# ---------------------------------------------------------------------------

def validate_globals_consistency(*, project_data: dict, errs: list[str]) -> None:
    """Append warning strings to *errs* for globals/scene consistency issues.

    C1 — flag or variable referenced in a trigger but has no name in Globals.
    C2 — entity instance has a type_id that no longer exists in entity_types.
    """
    if not isinstance(project_data, dict):
        return

    # Lazy import to avoid circular deps at module load time
    from core.game_vars_gen import collect_used_indices, _COUNT
    from core.entity_types import get_entity_types

    _W = "[warning] "

    # -- C1: unnamed but referenced flags/vars -------------------------------
    raw_flags = project_data.get("game_flags", []) or []
    flag_names = [str(raw_flags[i]).strip() if i < len(raw_flags) else "" for i in range(_COUNT)]

    raw_vars = project_data.get("game_vars", []) or []
    var_names = []
    for i in range(_COUNT):
        entry = raw_vars[i] if i < len(raw_vars) and isinstance(raw_vars[i], dict) else {}
        var_names.append(str(entry.get("name", "") or "").strip())

    used_flag_idx, used_var_idx = collect_used_indices(project_data)

    for idx in sorted(used_flag_idx):
        if not flag_names[idx]:
            errs.append(f"{_W}Flag {idx} référencé dans un trigger mais sans nom (Globals → Variables).")

    for idx in sorted(used_var_idx):
        if not var_names[idx]:
            errs.append(f"{_W}Variable {idx} référencée dans un trigger mais sans nom (Globals → Variables).")

    # -- C2: entity type_id not found in entity_types or entity_templates ----
    from core.entity_templates import get_entity_templates as _get_tpls
    known_ids = {
        t["id"]
        for t in (get_entity_types(project_data) + _get_tpls(project_data))
        if isinstance(t, dict) and t.get("id")
    }
    reported: set[str] = set()

    for scene in project_data.get("scenes", []) or []:
        if not isinstance(scene, dict):
            continue
        scene_name = str(scene.get("name") or scene.get("label") or "?")
        for ent in scene.get("entities", []) or []:
            if not isinstance(ent, dict):
                continue
            tid = ent.get("type_id")
            if tid and tid not in known_ids and tid not in reported:
                reported.add(tid)
                errs.append(f"{_W}Type « {tid} » (scène « {scene_name} ») introuvable dans Globals → Types d'entités.")
        for wave in scene.get("waves", []) or []:
            if not isinstance(wave, dict):
                continue
            for ent in wave.get("entities", []) or []:
                if not isinstance(ent, dict):
                    continue
                tid = ent.get("type_id")
                if tid and tid not in known_ids and tid not in reported:
                    reported.add(tid)
                    errs.append(f"{_W}Type « {tid} » (wave scène « {scene_name} ») introuvable dans Globals → Types d'entités.")
