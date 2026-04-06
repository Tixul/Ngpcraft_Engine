"""
ui/navigator_panel.py - Global project navigator shown next to the main tabs.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.entity_roles import scene_role, sprite_gameplay_role
from i18n.lang import tr


class NavigatorPanel(QWidget):
    """Permanent project tree listing scenes and key scene-owned objects."""

    scene_requested = pyqtSignal(object)
    open_scene_tab_requested = pyqtSignal(str)
    open_asset_in_palette = pyqtSignal(object)
    open_asset_in_tilemap = pyqtSignal(object)
    open_asset_in_editor = pyqtSignal(object)
    open_sprite_in_hitbox = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project_data: dict = {}
        self._current_scene_id = ""
        self._expanded_scene_ids: set[str] = set()
        self._selected_payload: dict | None = None
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_project_data(self, project_data: dict | None) -> None:
        self._project_data = project_data if isinstance(project_data, dict) else {}
        self.refresh()

    def set_current_scene(self, scene: dict | None) -> None:
        scene_id = self._scene_id(scene)
        if scene_id:
            self._current_scene_id = scene_id
            self._expanded_scene_ids.add(scene_id)
        else:
            self._current_scene_id = ""
        self._sync_selection()

    def refresh(self) -> None:
        self._rebuild_tree()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setMinimumWidth(220)
        self.setMaximumWidth(380)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        title_row = QHBoxLayout()
        title = QLabel(tr("nav.title"))
        title.setStyleSheet("font-weight: bold;")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self._btn_refresh = QPushButton(tr("nav.refresh"))
        self._btn_refresh.setToolTip(tr("nav.refresh_tt"))
        self._btn_refresh.clicked.connect(self.refresh)
        title_row.addWidget(self._btn_refresh)
        root.addLayout(title_row)

        self._filter_edit = QLineEdit(self)
        self._filter_edit.setPlaceholderText(tr("nav.filter_ph"))
        self._filter_edit.textChanged.connect(self._rebuild_tree)
        root.addWidget(self._filter_edit)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet("color: #99a3ad; font-size: 10px;")
        root.addWidget(self._summary)

        self._tree = QTreeWidget(self)
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setUniformRowHeights(True)
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.itemExpanded.connect(self._on_item_expanded)
        self._tree.itemCollapsed.connect(self._on_item_collapsed)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        root.addWidget(self._tree, 1)

        inspect_frame = QFrame(self)
        inspect_frame.setFrameShape(QFrame.Shape.StyledPanel)
        inspect_frame.setStyleSheet("QFrame { border: 1px solid #3a424c; border-radius: 4px; }")
        inspect_l = QVBoxLayout(inspect_frame)
        inspect_l.setContentsMargins(8, 8, 8, 8)
        inspect_l.setSpacing(6)
        self._inspect_title = QLabel(tr("nav.inspect_title_empty"))
        self._inspect_title.setStyleSheet("font-weight: bold;")
        inspect_l.addWidget(self._inspect_title)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumHeight(150)
        body_wrap = QWidget(scroll)
        body_l = QVBoxLayout(body_wrap)
        body_l.setContentsMargins(0, 0, 0, 0)
        body_l.setSpacing(4)
        self._inspect_body = QLabel(tr("nav.inspect_body_empty"))
        self._inspect_body.setWordWrap(True)
        self._inspect_body.setTextFormat(Qt.TextFormat.RichText)
        self._inspect_body.setStyleSheet("color: #aab4be;")
        body_l.addWidget(self._inspect_body)
        body_l.addStretch(1)
        scroll.setWidget(body_wrap)
        inspect_l.addWidget(scroll)
        act_row = QHBoxLayout()
        self._inspect_btn_primary = QPushButton("")
        self._inspect_btn_primary.clicked.connect(lambda: self._run_inspector_action("primary"))
        self._inspect_btn_secondary = QPushButton("")
        self._inspect_btn_secondary.clicked.connect(lambda: self._run_inspector_action("secondary"))
        act_row.addWidget(self._inspect_btn_primary)
        act_row.addWidget(self._inspect_btn_secondary)
        act_row.addStretch(1)
        inspect_l.addLayout(act_row)
        root.addWidget(inspect_frame)

        self._hint = QLabel(tr("nav.hint"))
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: #8ea0b3; font-size: 10px;")
        root.addWidget(self._hint)
        self._update_inspector(None)

    # ------------------------------------------------------------------
    # Tree data
    # ------------------------------------------------------------------

    def _scene_id(self, scene: dict | None) -> str:
        if not isinstance(scene, dict):
            return ""
        sid = str(scene.get("id") or "").strip()
        if sid:
            return sid
        return str(scene.get("label") or "").strip()

    def _scene_label(self, scene: dict) -> str:
        return str(scene.get("label") or "").strip() or tr("nav.scene_untitled")

    def _scene_ref(self, scene_id: str) -> dict | None:
        scenes = self._project_data.get("scenes", []) if isinstance(self._project_data, dict) else []
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            if self._scene_id(scene) == scene_id:
                return scene
        return None

    def _kind_payload(self, kind: str, scene: dict, **extra) -> dict:
        payload = {"kind": kind, "scene_id": self._scene_id(scene)}
        payload.update(extra)
        return payload

    def _palette_payload(self, sprite: dict) -> dict | None:
        rel = str(sprite.get("file") or "").strip()
        if not rel:
            return None
        return {
            "path": rel,
            "frame_w": int(sprite.get("frame_w", 8) or 8),
            "frame_h": int(sprite.get("frame_h", 8) or 8),
            "frame_count": int(sprite.get("frame_count", 1) or 1),
        }

    def _entity_label(self, scene: dict, ent: dict) -> str:
        type_id = str(ent.get("type") or "").strip() or "?"
        role = scene_role(scene, type_id, "")
        x = int(ent.get("x", 0) or 0)
        y = int(ent.get("y", 0) or 0)
        if role:
            return tr("nav.entity_label_role", type=type_id, role=role, x=x, y=y)
        return tr("nav.entity_label", type=type_id, x=x, y=y)

    def _wave_label(self, wave: dict, index: int) -> str:
        count = len([e for e in (wave.get("entities", []) or []) if isinstance(e, dict)])
        delay = int(wave.get("delay", 0) or 0)
        return tr("nav.wave_label", index=index + 1, count=count, delay=delay)

    def _region_label(self, region: dict, index: int) -> str:
        label = str(region.get("label") or "").strip()
        kind = str(region.get("kind") or "zone").strip()
        if label:
            return tr("nav.region_label_named", label=label, kind=kind)
        return tr("nav.region_label", index=index + 1, kind=kind)

    def _trigger_label(self, trig: dict, index: int) -> str:
        label = str(trig.get("label") or "").strip()
        cond = str(trig.get("cond") or "?").strip()
        action = str(trig.get("action") or "event").strip()
        if label:
            return tr("nav.trigger_label_named", label=label, cond=cond, action=action)
        return tr("nav.trigger_label", index=index + 1, cond=cond, action=action)

    def _path_label(self, path: dict, index: int) -> str:
        label = str(path.get("label") or path.get("id") or "").strip()
        pts = len([pt for pt in (path.get("points", []) or []) if isinstance(pt, dict)])
        if label:
            return tr("nav.path_label_named", label=label, points=pts)
        return tr("nav.path_label", index=index + 1, points=pts)

    def _bool_word(self, value: object) -> str:
        return tr("nav.yes") if bool(value) else tr("nav.no")

    def _kv_html(self, label: str, value: object) -> str:
        return f"<b>{label}</b> : {value}"

    def _scene_inspector(self, scene: dict) -> tuple[str, str, tuple[str, str] | None, tuple[str, str] | None]:
        body = [
            self._kv_html(tr("nav.inspect_scene_label"), self._scene_label(scene)),
            self._kv_html(tr("nav.inspect_scene_id"), self._scene_id(scene) or "-"),
            self._kv_html(tr("nav.inspect_scene_profile"), str(scene.get("level_profile") or "-")),
            self._kv_html(tr("nav.inspect_scene_map_mode"), str(scene.get("map_mode") or "none")),
            self._kv_html(tr("nav.inspect_scene_cam_mode"), str((scene.get("level_layout") or {}).get("cam_mode") or "-")),
            self._kv_html(tr("nav.inspect_scene_counts"), tr(
                "nav.inspect_scene_counts_value",
                sprites=len([x for x in (scene.get("sprites", []) or []) if isinstance(x, dict)]),
                tilemaps=len([x for x in (scene.get("tilemaps", []) or []) if isinstance(x, dict)]),
                entities=len([x for x in (scene.get("entities", []) or []) if isinstance(x, dict)]),
                waves=len([x for x in (scene.get("waves", []) or []) if isinstance(x, dict)]),
            )),
        ]
        return (
            tr("nav.inspect_scene_title"),
            "<br>".join(body),
            (tr("nav.open_project"), "project"),
            (tr("nav.open_level"), "level"),
        )

    def _group_inspector(self, payload: dict, scene: dict) -> tuple[str, str, tuple[str, str] | None, tuple[str, str] | None]:
        group = str(payload.get("group") or "").strip()
        counts = {
            "sprites": len([x for x in (scene.get("sprites", []) or []) if isinstance(x, dict)]),
            "tilemaps": len([x for x in (scene.get("tilemaps", []) or []) if isinstance(x, dict)]),
            "entities": len([x for x in (scene.get("entities", []) or []) if isinstance(x, dict)]),
            "waves": len([x for x in (scene.get("waves", []) or []) if isinstance(x, dict)]),
            "regions": len([x for x in (scene.get("regions", []) or []) if isinstance(x, dict)]),
            "triggers": len([x for x in (scene.get("triggers", []) or []) if isinstance(x, dict)]),
            "paths": len([x for x in (scene.get("paths", []) or []) if isinstance(x, dict)]),
        }
        title = tr("nav.inspect_group_title", group=group)
        body = "<br>".join([
            self._kv_html(tr("nav.inspect_scene_label"), self._scene_label(scene)),
            self._kv_html(tr("nav.inspect_group_name"), group),
            self._kv_html(tr("nav.inspect_group_count"), counts.get(group, 0)),
        ])
        primary = "palette" if group == "sprites" else ("tilemap" if group == "tilemaps" else "level")
        primary_label = (
            tr("nav.open_palette") if primary == "palette"
            else tr("nav.open_tilemap") if primary == "tilemap"
            else tr("nav.open_level")
        )
        return title, body, (primary_label, primary), (tr("nav.open_project"), "project")

    def _sprite_inspector(self, sprite: dict, scene: dict) -> tuple[str, str, tuple[str, str] | None, tuple[str, str] | None]:
        rel = str(sprite.get("file") or "").strip()
        role = sprite_gameplay_role(sprite, "-")
        fixed = str(sprite.get("fixed_palette") or "").strip() or "-"
        body = "<br>".join([
            self._kv_html(tr("nav.inspect_scene_label"), self._scene_label(scene)),
            self._kv_html(tr("nav.inspect_file"), rel or "-"),
            self._kv_html(tr("nav.inspect_role"), role),
            self._kv_html(tr("nav.inspect_fixed_palette"), fixed),
            self._kv_html(tr("nav.inspect_frames"), tr(
                "nav.inspect_frames_value",
                w=int(sprite.get("frame_w", 8) or 8),
                h=int(sprite.get("frame_h", 8) or 8),
                n=int(sprite.get("frame_count", 1) or 1),
            )),
            self._kv_html(tr("nav.inspect_export"), self._bool_word(sprite.get("export", True))),
            self._kv_html(tr("nav.inspect_hitboxes"), len(sprite.get("hitboxes", []) or [])),
        ])
        return (
            tr("nav.inspect_sprite_title"),
            body,
            (tr("nav.open_palette"), "palette_sprite"),
            (tr("nav.open_hitbox"), "hitbox_sprite"),
        )

    def _tilemap_inspector(self, tilemap: dict, scene: dict) -> tuple[str, str, tuple[str, str] | None, tuple[str, str] | None]:
        rel = str(tilemap.get("file") or "").strip()
        body = "<br>".join([
            self._kv_html(tr("nav.inspect_scene_label"), self._scene_label(scene)),
            self._kv_html(tr("nav.inspect_file"), rel or "-"),
            self._kv_html(tr("nav.inspect_plane"), str(tilemap.get("plane") or "auto")),
            self._kv_html(tr("nav.inspect_export"), self._bool_word(tilemap.get("export", True))),
        ])
        return (
            tr("nav.inspect_tilemap_title"),
            body,
            (tr("nav.open_tilemap"), "tilemap_asset"),
            (tr("nav.open_editor"), "editor_tilemap"),
        )

    def _entity_inspector(self, entity: dict, scene: dict) -> tuple[str, str, tuple[str, str] | None, tuple[str, str] | None]:
        type_id = str(entity.get("type") or "").strip() or "?"
        role = scene_role(scene, type_id, "-")
        body = "<br>".join([
            self._kv_html(tr("nav.inspect_scene_label"), self._scene_label(scene)),
            self._kv_html(tr("nav.inspect_type"), type_id),
            self._kv_html(tr("nav.inspect_role"), role),
            self._kv_html(tr("nav.inspect_pos"), tr(
                "nav.inspect_pos_value",
                x=int(entity.get("x", 0) or 0),
                y=int(entity.get("y", 0) or 0),
            )),
            self._kv_html(tr("nav.inspect_data"), int(entity.get("data", 0) or 0)),
            self._kv_html(tr("nav.inspect_behavior"), str(entity.get("behavior") or "-")),
            self._kv_html(tr("nav.inspect_path"), str(entity.get("path_id") or "-")),
        ])
        return (
            tr("nav.inspect_entity_title"),
            body,
            (tr("nav.open_level"), "level"),
            (tr("nav.open_project"), "project"),
        )

    def _wave_inspector(self, wave: dict, scene: dict, wave_index: int) -> tuple[str, str, tuple[str, str] | None, tuple[str, str] | None]:
        body = "<br>".join([
            self._kv_html(tr("nav.inspect_scene_label"), self._scene_label(scene)),
            self._kv_html(tr("nav.inspect_index"), wave_index + 1),
            self._kv_html(tr("nav.inspect_delay"), int(wave.get("delay", 0) or 0)),
            self._kv_html(tr("nav.inspect_count"), len([x for x in (wave.get("entities", []) or []) if isinstance(x, dict)])),
        ])
        return tr("nav.inspect_wave_title"), body, (tr("nav.open_level"), "level"), (tr("nav.open_project"), "project")

    def _region_inspector(self, region: dict, scene: dict, region_index: int) -> tuple[str, str, tuple[str, str] | None, tuple[str, str] | None]:
        body = "<br>".join([
            self._kv_html(tr("nav.inspect_scene_label"), self._scene_label(scene)),
            self._kv_html(tr("nav.inspect_index"), region_index + 1),
            self._kv_html(tr("nav.inspect_label"), str(region.get("label") or "-")),
            self._kv_html(tr("nav.inspect_kind"), str(region.get("kind") or "zone")),
            self._kv_html(tr("nav.inspect_rect"), tr(
                "nav.inspect_rect_value",
                x=int(region.get("x", 0) or 0),
                y=int(region.get("y", 0) or 0),
                w=max(1, int(region.get("w", 1) or 1)),
                h=max(1, int(region.get("h", 1) or 1)),
            )),
        ])
        return tr("nav.inspect_region_title"), body, (tr("nav.open_level"), "level"), (tr("nav.open_project"), "project")

    def _trigger_inspector(self, trigger: dict, scene: dict, trig_index: int) -> tuple[str, str, tuple[str, str] | None, tuple[str, str] | None]:
        body = "<br>".join([
            self._kv_html(tr("nav.inspect_scene_label"), self._scene_label(scene)),
            self._kv_html(tr("nav.inspect_index"), trig_index + 1),
            self._kv_html(tr("nav.inspect_label"), str(trigger.get("label") or "-")),
            self._kv_html(tr("nav.inspect_cond"), str(trigger.get("cond") or "-")),
            self._kv_html(tr("nav.inspect_action"), str(trigger.get("action") or "event")),
            self._kv_html(tr("nav.inspect_target"), str(trigger.get("target_id") or trigger.get("entity_target_id") or trigger.get("goto_scene") or "-")),
        ])
        return tr("nav.inspect_trigger_title"), body, (tr("nav.open_level"), "level"), (tr("nav.open_project"), "project")

    def _path_inspector(self, path: dict, scene: dict, path_index: int) -> tuple[str, str, tuple[str, str] | None, tuple[str, str] | None]:
        body = "<br>".join([
            self._kv_html(tr("nav.inspect_scene_label"), self._scene_label(scene)),
            self._kv_html(tr("nav.inspect_index"), path_index + 1),
            self._kv_html(tr("nav.inspect_label"), str(path.get("label") or path.get("id") or "-")),
            self._kv_html(tr("nav.inspect_points"), len([pt for pt in (path.get("points", []) or []) if isinstance(pt, dict)])),
            self._kv_html(tr("nav.inspect_loop"), self._bool_word(path.get("loop", False))),
        ])
        return tr("nav.inspect_path_title"), body, (tr("nav.open_level"), "level"), (tr("nav.open_project"), "project")

    def _inspector_content(self, payload: dict | None) -> tuple[str, str, tuple[str, str] | None, tuple[str, str] | None]:
        if not isinstance(payload, dict):
            return tr("nav.inspect_title_empty"), tr("nav.inspect_body_empty"), None, None
        scene = self._scene_ref(str(payload.get("scene_id") or "").strip())
        kind = str(payload.get("kind") or "").strip()
        if kind == "scene" and scene is not None:
            return self._scene_inspector(scene)
        if kind == "group" and scene is not None:
            return self._group_inspector(payload, scene)
        if kind == "sprite" and scene is not None:
            return self._sprite_inspector(payload.get("sprite") or {}, scene)
        if kind == "tilemap" and scene is not None:
            return self._tilemap_inspector(payload.get("tilemap") or {}, scene)
        if kind == "entity" and scene is not None:
            return self._entity_inspector(payload.get("entity") or {}, scene)
        if kind == "wave" and scene is not None:
            return self._wave_inspector(payload.get("wave") or {}, scene, int(payload.get("wave_index", 0) or 0))
        if kind == "region" and scene is not None:
            return self._region_inspector(payload.get("region") or {}, scene, int(payload.get("region_index", 0) or 0))
        if kind == "trigger" and scene is not None:
            return self._trigger_inspector(payload.get("trigger") or {}, scene, int(payload.get("trigger_index", 0) or 0))
        if kind == "path" and scene is not None:
            return self._path_inspector(payload.get("path") or {}, scene, int(payload.get("path_index", 0) or 0))
        return tr("nav.inspect_title_empty"), tr("nav.inspect_body_empty"), None, None

    def _update_inspector(self, payload: dict | None) -> None:
        self._selected_payload = payload if isinstance(payload, dict) else None
        title, body, primary, secondary = self._inspector_content(payload)
        self._inspect_title.setText(title)
        self._inspect_body.setText(body)
        self._set_inspector_button(self._inspect_btn_primary, primary)
        self._set_inspector_button(self._inspect_btn_secondary, secondary)

    def _set_inspector_button(self, btn: QPushButton, action: tuple[str, str] | None) -> None:
        if action is None:
            btn.hide()
            btn.setProperty("inspect_action", "")
            return
        btn.show()
        btn.setText(action[0])
        btn.setProperty("inspect_action", action[1])

    def _run_inspector_action(self, which: str) -> None:
        btn = self._inspect_btn_primary if which == "primary" else self._inspect_btn_secondary
        action = str(btn.property("inspect_action") or "").strip()
        payload = self._selected_payload
        if not action or not isinstance(payload, dict):
            return
        scene = self._emit_scene_for_payload(payload)
        if action in {"project", "level", "palette", "tilemap", "hitbox"}:
            self.open_scene_tab_requested.emit(action)
            return
        if action == "palette_sprite":
            pal = self._palette_payload(payload.get("sprite") or {})
            if pal is not None:
                self.open_asset_in_palette.emit(pal)
            return
        if action == "hitbox_sprite":
            self.open_sprite_in_hitbox.emit(payload.get("sprite"))
            return
        if action == "tilemap_asset":
            rel = str((payload.get("tilemap") or {}).get("file") or "").strip()
            if rel:
                self.open_asset_in_tilemap.emit(rel)
            return
        if action == "editor_tilemap":
            rel = str((payload.get("tilemap") or {}).get("file") or "").strip()
            if rel:
                self.open_asset_in_editor.emit(rel)
            return
        if action == "editor_sprite":
            rel = str((payload.get("sprite") or {}).get("file") or "").strip()
            if rel:
                self.open_asset_in_editor.emit(rel)
            return

    def _scene_sections(self, scene: dict) -> list[tuple[str, str, list[dict]]]:
        sprites = [spr for spr in (scene.get("sprites", []) or []) if isinstance(spr, dict)]
        tilemaps = [tm for tm in (scene.get("tilemaps", []) or []) if isinstance(tm, dict)]
        entities = [ent for ent in (scene.get("entities", []) or []) if isinstance(ent, dict)]
        waves = [wave for wave in (scene.get("waves", []) or []) if isinstance(wave, dict)]
        regions = [reg for reg in (scene.get("regions", []) or []) if isinstance(reg, dict)]
        triggers = [trig for trig in (scene.get("triggers", []) or []) if isinstance(trig, dict)]
        paths = [path for path in (scene.get("paths", []) or []) if isinstance(path, dict)]

        sprite_items = []
        for spr in sprites:
            rel = str(spr.get("file") or "").strip()
            label = Path(rel).stem if rel else tr("nav.asset_unnamed")
            sprite_items.append(
                {
                    "label": label,
                    "payload": self._kind_payload("sprite", scene, sprite=spr),
                }
            )

        tilemap_items = []
        for tm in tilemaps:
            rel = str(tm.get("file") or "").strip()
            label = Path(rel).stem if rel else tr("nav.asset_unnamed")
            tilemap_items.append(
                {
                    "label": label,
                    "payload": self._kind_payload("tilemap", scene, tilemap=tm),
                }
            )

        entity_items = [
            {
                "label": self._entity_label(scene, ent),
                "payload": self._kind_payload("entity", scene, entity=ent),
            }
            for ent in entities
        ]
        wave_items = [
            {
                "label": self._wave_label(wave, i),
                "payload": self._kind_payload("wave", scene, wave=wave, wave_index=i),
            }
            for i, wave in enumerate(waves)
        ]
        region_items = [
            {
                "label": self._region_label(reg, i),
                "payload": self._kind_payload("region", scene, region=reg, region_index=i),
            }
            for i, reg in enumerate(regions)
        ]
        trigger_items = [
            {
                "label": self._trigger_label(trig, i),
                "payload": self._kind_payload("trigger", scene, trigger=trig, trigger_index=i),
            }
            for i, trig in enumerate(triggers)
        ]
        path_items = [
            {
                "label": self._path_label(path, i),
                "payload": self._kind_payload("path", scene, path=path, path_index=i),
            }
            for i, path in enumerate(paths)
        ]

        return [
            ("sprites", tr("nav.group_sprites", n=len(sprite_items)), sprite_items),
            ("tilemaps", tr("nav.group_tilemaps", n=len(tilemap_items)), tilemap_items),
            ("entities", tr("nav.group_entities", n=len(entity_items)), entity_items),
            ("waves", tr("nav.group_waves", n=len(wave_items)), wave_items),
            ("regions", tr("nav.group_regions", n=len(region_items)), region_items),
            ("triggers", tr("nav.group_triggers", n=len(trigger_items)), trigger_items),
            ("paths", tr("nav.group_paths", n=len(path_items)), path_items),
        ]

    def _matches_filter(self, text: str, needle: str) -> bool:
        return not needle or needle in str(text or "").lower()

    def _rebuild_tree(self) -> None:
        scenes = [s for s in (self._project_data.get("scenes", []) if isinstance(self._project_data, dict) else []) if isinstance(s, dict)]
        needle = self._filter_edit.text().strip().lower()

        self._tree.blockSignals(True)
        self._tree.clear()
        shown_scenes = 0
        shown_items = 0

        for scene in scenes:
            scene_id = self._scene_id(scene)
            scene_label = self._scene_label(scene)
            scene_match = self._matches_filter(scene_label, needle)
            sections = self._scene_sections(scene)

            scene_item = QTreeWidgetItem([scene_label])
            scene_item.setData(0, Qt.ItemDataRole.UserRole, self._kind_payload("scene", scene))
            scene_item.setToolTip(0, scene_label)

            scene_visible = scene_match
            for sec_key, sec_label, sec_items in sections:
                matching = [
                    row for row in sec_items
                    if scene_match or self._matches_filter(sec_label, needle) or self._matches_filter(row["label"], needle)
                ]
                if not matching and not (scene_match and not needle):
                    if not scene_match:
                        continue
                group_item = QTreeWidgetItem([sec_label])
                group_item.setData(0, Qt.ItemDataRole.UserRole, self._kind_payload("group", scene, group=sec_key))
                group_item.setToolTip(0, sec_label)
                for row in matching:
                    child = QTreeWidgetItem([row["label"]])
                    child.setData(0, Qt.ItemDataRole.UserRole, row["payload"])
                    child.setToolTip(0, row["label"])
                    group_item.addChild(child)
                    shown_items += 1
                scene_item.addChild(group_item)
                if matching:
                    scene_visible = True

            if not scene_visible:
                continue

            self._tree.addTopLevelItem(scene_item)
            shown_scenes += 1

            # expand the scene if it matches the current filters or selection
            if scene_id == self._current_scene_id or scene_id in self._expanded_scene_ids or bool(needle):
                scene_item.setExpanded(True)
                for i in range(scene_item.childCount()):
                    scene_item.child(i).setExpanded(bool(needle) or scene_id == self._current_scene_id)

        self._tree.blockSignals(False)
        self._summary.setText(tr("nav.summary", scenes=shown_scenes, items=shown_items))
        self._sync_selection()

    def _sync_selection(self) -> None:
        if not self._current_scene_id or self._tree.topLevelItemCount() <= 0:
            return
        current = self._tree.currentItem()
        if current is not None:
            payload = current.data(0, Qt.ItemDataRole.UserRole) or {}
            if str(payload.get("scene_id") or "") == self._current_scene_id:
                return
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            payload = item.data(0, Qt.ItemDataRole.UserRole) or {}
            if str(payload.get("scene_id") or "") == self._current_scene_id:
                self._tree.setCurrentItem(item)
                return

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _emit_scene_for_payload(self, payload: dict | None) -> dict | None:
        if not isinstance(payload, dict):
            return None
        scene = self._scene_ref(str(payload.get("scene_id") or "").strip())
        if scene is not None:
            self.scene_requested.emit(scene)
        return scene

    def _open_payload(self, payload: dict | None) -> None:
        if not isinstance(payload, dict):
            return
        scene = self._emit_scene_for_payload(payload)
        kind = str(payload.get("kind") or "").strip()
        if kind == "scene":
            self.open_scene_tab_requested.emit("project")
            return
        if kind == "group":
            group = str(payload.get("group") or "").strip()
            if group == "sprites":
                self.open_scene_tab_requested.emit("palette")
            elif group == "tilemaps":
                self.open_scene_tab_requested.emit("tilemap")
            else:
                self.open_scene_tab_requested.emit("level")
            return
        if kind == "sprite":
            pal = self._palette_payload(payload.get("sprite") or {})
            if pal is not None:
                self.open_asset_in_palette.emit(pal)
            return
        if kind == "tilemap":
            tilemap = payload.get("tilemap") or {}
            rel = str(tilemap.get("file") or "").strip()
            if rel:
                self.open_asset_in_tilemap.emit(rel)
            return
        if kind in {"entity", "wave", "region", "trigger", "path"} and scene is not None:
            self.open_scene_tab_requested.emit("level")

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        self._emit_scene_for_payload(payload)
        self._update_inspector(payload)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        self._open_payload(item.data(0, Qt.ItemDataRole.UserRole))

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        payload = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if str(payload.get("kind") or "") == "scene":
            scene_id = str(payload.get("scene_id") or "").strip()
            if scene_id:
                self._expanded_scene_ids.add(scene_id)

    def _on_item_collapsed(self, item: QTreeWidgetItem) -> None:
        payload = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if str(payload.get("kind") or "") == "scene":
            scene_id = str(payload.get("scene_id") or "").strip()
            if scene_id:
                self._expanded_scene_ids.discard(scene_id)

    def _show_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        payload = item.data(0, Qt.ItemDataRole.UserRole) or {}
        self._update_inspector(payload)
        kind = str(payload.get("kind") or "").strip()
        menu = QMenu(self)
        self._emit_scene_for_payload(payload)

        if kind == "scene":
            menu.addAction(tr("nav.open_project"), lambda: self.open_scene_tab_requested.emit("project"))
            menu.addAction(tr("nav.open_level"), lambda: self.open_scene_tab_requested.emit("level"))
        elif kind == "group":
            group = str(payload.get("group") or "").strip()
            if group == "sprites":
                menu.addAction(tr("nav.open_palette"), lambda: self.open_scene_tab_requested.emit("palette"))
            elif group == "tilemaps":
                menu.addAction(tr("nav.open_tilemap"), lambda: self.open_scene_tab_requested.emit("tilemap"))
            else:
                menu.addAction(tr("nav.open_level"), lambda: self.open_scene_tab_requested.emit("level"))
        elif kind == "sprite":
            sprite = payload.get("sprite")
            pal = self._palette_payload(sprite or {})
            if pal is not None:
                menu.addAction(tr("nav.open_palette"), lambda s=pal: self.open_asset_in_palette.emit(s))
            menu.addAction(tr("nav.open_hitbox"), lambda s=sprite: self.open_sprite_in_hitbox.emit(s))
            rel = str((sprite or {}).get("file") or "").strip()
            if rel:
                menu.addAction(tr("nav.open_editor"), lambda p=rel: self.open_asset_in_editor.emit(p))
        elif kind == "tilemap":
            tilemap = payload.get("tilemap") or {}
            rel = str(tilemap.get("file") or "").strip()
            if rel:
                menu.addAction(tr("nav.open_tilemap"), lambda p=rel: self.open_asset_in_tilemap.emit(p))
                menu.addAction(tr("nav.open_editor"), lambda p=rel: self.open_asset_in_editor.emit(p))
        elif kind in {"entity", "wave", "region", "trigger", "path"}:
            menu.addAction(tr("nav.open_level"), lambda: self.open_scene_tab_requested.emit("level"))

        if menu.isEmpty():
            return
        menu.exec(self._tree.viewport().mapToGlobal(pos))
