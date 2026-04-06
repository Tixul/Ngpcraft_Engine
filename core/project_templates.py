"""
core/project_templates.py - Starter templates for new NGPC projects.

The wizard scaffolds the vanilla NGPC C template first. This module handles
the project-specific layer: registry of available templates, writing the
initial .ngpcraft file, and dispatching any example-specific asset setup.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from core.entity_roles import migrate_scene_sprite_roles


DEFAULT_TEMPLATE_ID = "blank"
DEFAULT_EXAMPLE_EXPORT_DIR = r"GraphX\gen"


@dataclass(frozen=True)
class ProjectTemplateSpec:
    """Metadata shown by the new-project wizard for one starter template."""

    template_id: str
    label_key: str
    desc_key: str


_TEMPLATES: tuple[ProjectTemplateSpec, ...] = (
    ProjectTemplateSpec(
        template_id="blank",
        label_key="wizard.template_blank",
        desc_key="wizard.template_blank_desc",
    ),
    # TODO: add updated example templates here when ready.
    # Each entry needs a ProjectTemplateSpec above + a matching branch in
    # build_project_data() below + i18n keys in strings_fr/strings_en.
)


def list_project_templates() -> list[ProjectTemplateSpec]:
    """Return the starter templates supported by the wizard."""
    return list(_TEMPLATES)


def normalize_project_template(template_id: str | None) -> str:
    """Return a valid template id, falling back to `DEFAULT_TEMPLATE_ID`."""
    wanted = str(template_id or "").strip()
    valid = {spec.template_id for spec in _TEMPLATES}
    return wanted if wanted in valid else DEFAULT_TEMPLATE_ID


def _project_data_base(*, project_name: str, rom_name: str) -> dict:
    return {
        "version": 1,
        "name": project_name,
        "project_name": project_name,
        "rom_name": rom_name,
        "graphx_dir": "GraphX",
        "export_dir": DEFAULT_EXAMPLE_EXPORT_DIR,
        "bundle": {"tile_base": 256, "pal_base": 0, "entries": []},
        "scenes": [],
        "save_config": {
            "save_score": False,
            "save_lives": False,
            "save_collectibles": False,
            "save_player_form": False,
            "save_hp": False,
            "save_continues": False,
            "save_keys": False,
            "save_bosses": False,
            "save_stages": False,
            "save_abilities": False,
            "save_money": False,
            "save_ammo": False,
            "save_player_level": False,
            "save_experience": False,
            "save_best_time": False,
            "custom_fields": [],
        },
    }


def _blank_project_data(*, project_name: str, rom_name: str) -> dict:
    return _project_data_base(project_name=project_name, rom_name=rom_name)


def _set_scene_dimensions(scene: dict, *, width: int, height: int) -> None:
    """Keep all scene size fields aligned with current validation/export code."""
    scene["level_size"] = {"w": int(width), "h": int(height)}
    scene["map_w"] = int(width)
    scene["map_h"] = int(height)
    scene["grid_w"] = int(width)
    scene["grid_h"] = int(height)


def build_project_data(*, template_id: str, destination: Path, project_name: str, rom_name: str) -> dict:
    """Build the initial `.ngpcraft` payload for a newly scaffolded project.

    Depending on `template_id`, this can be a blank project or a populated
    example that also installs placeholder assets into `destination`.
    """
    template_id = normalize_project_template(template_id)
    # TODO: dispatch example templates here, e.g.:
    #   if template_id == "my_example":
    #       data = _install_my_example(destination, project_name, rom_name)
    #   else:
    data = _blank_project_data(project_name=project_name, rom_name=rom_name)
    for scene in data.get("scenes", []) or []:
        migrate_scene_sprite_roles(scene)
    return data


def write_project_file(*, destination: Path, project_name: str, rom_name: str, template_id: str) -> Path:
    """Generate `project.ngpcraft` for a new project and return its path."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    data = build_project_data(
        template_id=template_id,
        destination=destination,
        project_name=project_name,
        rom_name=rom_name,
    )
    out = destination / "project.ngpcraft"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out
