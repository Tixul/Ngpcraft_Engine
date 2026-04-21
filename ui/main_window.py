"""
ui/main_window.py - Main application window with tab widget.

Tabs are organised into three persistent groups selectable via a button bar:

  [Project]  Project, Globals
  [Scene]    Level, Palette, Tilemap, Dialogues, Sprite Setup
  [Tools]    Editor, VRAM Map, Bundle
  [Help]     Help

Switching groups shows/hides the relevant QTabWidget tabs so each group
acts as a self-contained workspace. The last active tab within each group
is remembered across group switches.
"""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import Qt, QSettings, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.project_model import TILE_MAX, PAL_MAX_SPR, project_tile_estimate, project_pal_estimate, set_pipeline_tool_paths
from core.template_integration import default_export_dir_rel
from i18n.lang import tr
from ui.start_dialog import add_recent
from ui.tool_finder import find_script, default_candidates
from ui.tabs.bundle_tab import BundleTab
from ui.tabs.dialogues_tab import DialoguesTab
from ui.tabs.editor_tab import EditorTab
from ui.tabs.help_tab import HelpTab
from ui.tabs.hitbox_tab import HitboxTab
from ui.tabs.level_tab import LevelTab
from ui.navigator_panel import NavigatorPanel
from ui.tabs.palette_tab import PaletteTab
from ui.tabs.globals_tab import GlobalsTab
from ui.tabs.project_tab import ProjectTab, FontTab
from ui.tabs.scene_map_tab import SceneMapTab
from ui.tabs.tilemap_tab import TilemapTab
from ui.tabs.vram_tab import VramTab


class MainWindow(QMainWindow):
    """Top-level window coordinating project state and all editor tabs."""

    def __init__(
        self,
        project_path: Path | None,
        is_new: bool = False,
        is_free_mode: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project_path = project_path
        self._is_new = is_new
        self._is_free_mode = is_free_mode
        self._project_data: dict = {}

        if is_free_mode:
            pass  # no project file, no data to load
        elif is_new and project_path is not None and project_path.exists():
            # A scaffolded project already ships with a populated .ngpcraft.
            # Loading it preserves starter templates instead of overwriting them.
            self._load_project()
            if self._ensure_new_project_defaults():
                self._save_project()
        elif is_new:
            self._init_new_project()
        else:
            self._load_project()

        self._build_ui()
        self._register_pipeline_tools()
        self._update_title()
        if not is_free_mode and project_path:
            add_recent(str(project_path))

        settings = QSettings("NGPCraft", "Engine")
        if settings.contains("main_window/geometry"):
            self.restoreGeometry(settings.value("main_window/geometry"))

        # Silent app-update check — runs 4 s after window opens, non-blocking
        QTimer.singleShot(4000, self._start_silent_update_check)

    # ------------------------------------------------------------------
    # Project I/O
    # ------------------------------------------------------------------

    def _init_new_project(self) -> None:
        self._project_path.parent.mkdir(parents=True, exist_ok=True)
        self._project_data = {
            "version": 1,
            "name": self._project_path.parent.name,
            "graphx_dir": "GraphX",
            "bundle": {"tile_base": 256, "pal_base": 0, "entries": []},
        }
        self._ensure_new_project_defaults()
        self._save_project()

    def _ensure_new_project_defaults(self) -> bool:
        """Fill defaults that every freshly created project should persist."""
        if not isinstance(self._project_data, dict):
            return False
        changed = False
        if not str(self._project_data.get("export_dir") or "").strip():
            self._project_data["export_dir"] = default_export_dir_rel(self._project_data)
            changed = True
        return changed

    def _load_project(self) -> None:
        try:
            self._project_data = json.loads(self._project_path.read_text(encoding="utf-8"))
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"Cannot open project:\n{exc}")
            self._project_data = {"version": 1, "name": "?", "graphx_dir": "GraphX",
                                  "bundle": {"tile_base": 256, "pal_base": 0, "entries": []}}

    def _flush_live_scene_state(self) -> None:
        level_tab = getattr(self, "_level_tab", None)
        if level_tab is None:
            return
        try:
            level_tab.flush_scene_state()
        except Exception:
            pass

    def _save_project(self) -> None:
        if self._project_path is None:
            return  # free mode — nothing to persist
        self._flush_live_scene_state()
        try:
            self._project_path.write_text(
                json.dumps(self._project_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            if hasattr(self, "_save_label"):
                self._save_label.setText("✓ Saved")
                self._save_timer.start(2000)
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"Cannot save project:\n{exc}")
        if hasattr(self, "_navigator"):
            self._navigator.set_project_data(self._project_data)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setMinimumSize(860, 560)

        self._tabs = QTabWidget()
        self._navigator = NavigatorPanel(self)
        self._navigator.scene_requested.connect(self._on_navigator_scene_requested)
        self._navigator.open_scene_tab_requested.connect(self._open_scene_tab)
        self._navigator.open_asset_in_palette.connect(self._open_sprite_in_palette)
        self._navigator.open_asset_in_tilemap.connect(self._open_in_tilemap)
        self._navigator.open_asset_in_editor.connect(self._open_in_editor)
        self._navigator.open_sprite_in_hitbox.connect(self._open_in_hitbox)

        self._project_tab = ProjectTab(
            project_data=self._project_data,
            project_path=self._project_path,
            on_save=self._save_project,
            is_free_mode=self._is_free_mode,
            parent=self,
        )
        self._project_tab.scene_activated.connect(self._on_scene_activated)
        self._project_tab.open_asset_in_palette.connect(self._open_in_palette)
        self._project_tab.open_asset_in_tilemap.connect(self._open_in_tilemap)
        self._project_tab.open_asset_in_editor.connect(self._open_in_editor)
        self._project_tab.open_sprite_in_palette.connect(self._open_sprite_in_palette)
        self._project_tab.open_sprite_in_hitbox.connect(self._open_in_hitbox)
        self._project_tab.open_scene_tab.connect(self._open_scene_tab)
        self._tabs.addTab(self._project_tab, tr("tab.project"))

        self._globals_tab = GlobalsTab(
            project_data=self._project_data,
            project_path=self._project_path,
            on_save=self._save_project,
            parent=self,
        )
        self._tabs.addTab(self._globals_tab, tr("tab.globals"))

        # Wire GlobalsTab ↔ ProjectTab signal + inject reference for export delegation
        self._globals_tab.manifest_reloaded.connect(self._project_tab.set_audio_manifest)
        self._project_tab.set_globals_tab(self._globals_tab)
        # Sync initial manifest state (signal was emitted before connection existed)
        self._project_tab.set_audio_manifest(self._globals_tab.audio_manifest)

        self._font_tab = FontTab(
            project_data=self._project_data,
            project_path=self._project_path,
            on_save=self._save_project,
            parent=self,
        )
        self._tabs.addTab(self._font_tab, tr("tab.font"))

        self._map_tab = SceneMapTab(
            project_data=self._project_data,
            project_path=self._project_path,
            on_save=self._save_project,
            parent=self,
        )
        self._map_tab.open_scene_requested.connect(self._on_map_open_scene)
        self._tabs.addTab(self._map_tab, tr("tab.map"))

        # --- Group: Scene ---
        self._level_tab = LevelTab(on_save=self._save_project, parent=self)
        self._level_tab.open_globals_tab_requested.connect(
            lambda: self._navigate_to(self._globals_tab)
        )
        self._tabs.addTab(self._level_tab, tr("tab.level"))

        self._palette_tab = PaletteTab(self)
        self._palette_tab.apply_anim_to_scene_requested.connect(self._apply_anim_to_scene)
        self._palette_tab.apply_scene_palette_requested.connect(self._apply_scene_palette)
        self._tabs.addTab(self._palette_tab, tr("tab.palette"))

        self._tilemap_tab = TilemapTab(
            project_data=self._project_data,
            project_path=self._project_path,
            on_save=self._save_project,
            is_free_mode=self._is_free_mode,
            parent=self,
        )
        self._tabs.addTab(self._tilemap_tab, tr("tab.tilemap"))

        self._dialogues_tab = DialoguesTab(on_save=self._save_project, parent=self)
        self._dialogues_tab.scene_modified.connect(self._on_scene_modified)
        self._tabs.addTab(self._dialogues_tab, tr("tab.dialogues"))

        self._hitbox_tab = HitboxTab(self)
        self._hitbox_tab.hitboxes_changed.connect(self._save_project)
        self._tabs.addTab(self._hitbox_tab, tr("tab.hitbox"))

        # --- Group: Tools ---
        self._editor_tab = EditorTab(self)
        self._tabs.addTab(self._editor_tab, tr("tab.editor"))

        self._vram_tab = VramTab(self)
        self._vram_tab.scene_modified.connect(self._on_scene_modified)
        self._vram_tab.open_sprite_in_palette.connect(self._open_sprite_in_palette)
        self._tabs.addTab(self._vram_tab, tr("tab.vram"))

        self._bundle_tab = BundleTab(
            project_data=self._project_data,
            project_path=self._project_path,
            on_save=self._save_project,
            parent=self,
        )
        self._bundle_tab.open_sprite_in_palette.connect(self._open_sprite_in_palette)
        self._bundle_tab.scene_changed.connect(self._on_scene_activated)
        self._tabs.addTab(self._bundle_tab, tr("tab.bundle"))

        # --- Group: Help ---
        self._help_tab = HelpTab(self)
        self._tabs.addTab(self._help_tab, tr("tab.help"))

        # --- Group bar (above tabs) ---
        self._active_group: str = "project"
        self._active_tab_per_group: dict[str, QWidget] = {}

        _GROUP_BTN_STYLE = (
            "QPushButton { padding: 2px 14px; border-radius: 4px; font-weight: bold; }"
            "QPushButton:checked { background: #2a4a2a; color: #88dd88; border: 1px solid #448844; }"
            "QPushButton:!checked { background: transparent; color: #aaaaaa; border: 1px solid transparent; }"
            "QPushButton:!checked:hover { color: #dddddd; border: 1px solid #555555; }"
        )
        self._group_btn_grp = QButtonGroup(self)
        self._group_btn_grp.setExclusive(True)
        group_bar_widget = QWidget()
        group_bar_widget.setFixedHeight(30)
        group_bar_layout = QHBoxLayout(group_bar_widget)
        group_bar_layout.setContentsMargins(4, 2, 4, 2)
        group_bar_layout.setSpacing(6)
        for _gkey, _glabel_key, _gtt_key in [
            ("project", "group.project", "group.project_tt"),
            ("scene",   "group.scene",   "group.scene_tt"),
            ("tools",   "group.tools",   "group.tools_tt"),
            ("help",    "group.help",    "group.help_tt"),
        ]:
            _gbtn = QPushButton(tr(_glabel_key))
            _gbtn.setCheckable(True)
            _gbtn.setFlat(True)
            _gbtn.setFixedHeight(24)
            _gbtn.setStyleSheet(_GROUP_BTN_STYLE)
            _gbtn.setToolTip(tr(_gtt_key))
            _gbtn.clicked.connect(lambda _chk, g=_gkey: self._switch_to_group(g))
            self._group_btn_grp.addButton(_gbtn)
            group_bar_layout.addWidget(_gbtn)
            setattr(self, f"_group_btn_{_gkey}", _gbtn)
        group_bar_layout.addStretch()

        # Wrap group bar + tabs in a container
        _tabs_container = QWidget()
        _tabs_layout = QVBoxLayout(_tabs_container)
        _tabs_layout.setContentsMargins(0, 0, 0, 0)
        _tabs_layout.setSpacing(0)
        _tabs_layout.addWidget(group_bar_widget)
        _tabs_layout.addWidget(self._tabs)

        self._tabs.setCurrentIndex(0)
        self._navigator.set_project_data(self._project_data)
        self._central_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._central_splitter.addWidget(self._navigator)
        self._central_splitter.addWidget(_tabs_container)
        self._central_splitter.setStretchFactor(0, 0)
        self._central_splitter.setStretchFactor(1, 1)
        self._central_splitter.setCollapsible(0, False)
        self._central_splitter.setCollapsible(1, False)
        self._central_splitter.setSizes([280, 980])
        self.setCentralWidget(self._central_splitter)

        # Status bar
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._update_status()

        # Save indicator — flashes "✓ Saved" for 2 s after each auto-save
        self._save_label = QLabel("")
        self._save_label.setStyleSheet("color: #66bb66; font-size: 11px; padding: 0 8px;")
        self._status.addPermanentWidget(self._save_label)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(lambda: self._save_label.setText(""))

        # Restore active group from previous session
        settings = QSettings("NGPCraft", "Engine")
        _saved_group = settings.value("ui/active_group", "project", type=str)
        if _saved_group not in self._TAB_GROUPS:
            _saved_group = "project"
        self._switch_to_group(_saved_group, initial=True)
        if settings.contains("main_window/central_splitter"):
            try:
                self._central_splitter.restoreState(settings.value("main_window/central_splitter"))
            except Exception:
                pass

        # Refresh VRAM tab whenever the user switches to it (catches plane/asset changes)
        self._tabs.currentChanged.connect(self._on_tab_changed)

        # Global navigation shortcuts
        sc_next = QShortcut(QKeySequence("Ctrl+Tab"), self)
        sc_next.activated.connect(self._next_visible_tab)
        sc_prev = QShortcut(QKeySequence("Ctrl+Shift+Tab"), self)
        sc_prev.activated.connect(self._prev_visible_tab)
        # Initial VRAM refresh if project loaded
        if not self._is_free_mode:
            self._vram_tab.refresh(self._project_data, self._project_path)
            scene = self._project_tab.current_scene()
            if scene is not None:
                self._on_scene_activated(scene)

    # ------------------------------------------------------------------
    # Tab groups
    # ------------------------------------------------------------------

    _TAB_GROUPS: dict[str, tuple[str, ...]] = {
        "project": ("_project_tab", "_globals_tab", "_font_tab", "_map_tab"),
        "scene":   ("_level_tab", "_palette_tab", "_tilemap_tab", "_dialogues_tab", "_hitbox_tab"),
        "tools":   ("_editor_tab", "_vram_tab", "_bundle_tab"),
        "help":    ("_help_tab",),
    }

    def _switch_to_group(self, name: str, *, initial: bool = False) -> None:
        """Activate a tab group: show its tabs, hide all others, restore last active tab."""
        self._active_group = name
        if not initial:
            QSettings("NGPCraft", "Engine").setValue("ui/active_group", name)
        group_attrs = self._TAB_GROUPS.get(name, ())
        for gkey, gattrs in self._TAB_GROUPS.items():
            visible = (gkey == name)
            for attr in gattrs:
                tab = getattr(self, attr, None)
                if tab is None:
                    continue
                idx = self._tabs.indexOf(tab)
                if idx >= 0:
                    self._tabs.setTabVisible(idx, visible)
        # Update group button checked state
        for gkey in self._TAB_GROUPS:
            btn = getattr(self, f"_group_btn_{gkey}", None)
            if btn is not None:
                btn.setChecked(gkey == name)
        # Navigate to last remembered tab in group, or first visible tab.
        # Exception: the "project" group always reopens on _project_tab so that
        # entering the category lands on the project overview, not a sub-tab
        # (police/globals/map) the user happened to leave active.
        if name != "project":
            remembered = self._active_tab_per_group.get(name)
            if remembered is not None:
                r_idx = self._tabs.indexOf(remembered)
                if r_idx >= 0 and self._tabs.isTabVisible(r_idx):
                    self._tabs.setCurrentWidget(remembered)
                    return
        for attr in group_attrs:
            tab = getattr(self, attr, None)
            if tab is None:
                continue
            idx = self._tabs.indexOf(tab)
            if idx >= 0 and self._tabs.isTabVisible(idx):
                self._tabs.setCurrentWidget(tab)
                return

    def _on_map_open_scene(self, sid: str) -> None:
        """Handle double-click on a scene card: select the scene then open Level tab."""
        self._project_tab.activate_scene_by_id(sid)
        self._navigate_to(self._level_tab)

    def _navigate_to(self, widget: QWidget | None) -> None:
        """Switch to the group that owns widget, then activate it."""
        if widget is None:
            return
        for gkey, gattrs in self._TAB_GROUPS.items():
            for attr in gattrs:
                if getattr(self, attr, None) is widget:
                    if self._active_group != gkey:
                        self._switch_to_group(gkey)
                    self._tabs.setCurrentWidget(widget)
                    return
        # Fallback: just navigate directly
        self._tabs.setCurrentWidget(widget)

    def _next_visible_tab(self) -> None:
        n = self._tabs.count()
        idx = self._tabs.currentIndex()
        for i in range(1, n + 1):
            candidate = (idx + i) % n
            if self._tabs.isTabVisible(candidate):
                self._tabs.setCurrentIndex(candidate)
                return

    def _prev_visible_tab(self) -> None:
        n = self._tabs.count()
        idx = self._tabs.currentIndex()
        for i in range(1, n + 1):
            candidate = (idx - i) % n
            if self._tabs.isTabVisible(candidate):
                self._tabs.setCurrentIndex(candidate)
                return

    def _on_tab_changed(self, _idx: int) -> None:
        current = self._tabs.currentWidget()
        # Remember last active tab per group
        for gkey, gattrs in self._TAB_GROUPS.items():
            for attr in gattrs:
                if getattr(self, attr, None) is current:
                    # Never pin _map_tab as the remembered tab for the project group
                    if not (gkey == "project" and attr == "_map_tab"):
                        self._active_tab_per_group[gkey] = current
                    break
        if current is self._vram_tab:
            self._vram_tab.refresh(self._project_data, self._project_path)
        if current is self._globals_tab:
            self._globals_tab._load_entity_types_from_project()

    def _register_pipeline_tools(self) -> None:
        """Find pipeline tools via QSettings/candidates and register them with the core model."""
        repo_root = Path(__file__).resolve().parent.parent
        set_pipeline_tool_paths(
            tilemap=find_script("tilemap_script_path", default_candidates(repo_root, "ngpc_tilemap.py")),
            sprite=find_script("export_script_path", default_candidates(repo_root, "ngpc_sprite_export.py")),
        )

    def _update_title(self) -> None:
        from core.version import APP_VERSION
        base = f"{tr('app.title')} v{APP_VERSION}"
        if self._is_free_mode:
            self.setWindowTitle(f"{base} — {tr('start.free_mode')}")
        else:
            name = self._project_data.get("name", "?")
            self.setWindowTitle(f"{base} — {name}")

    def _update_status(self) -> None:
        if self._is_free_mode:
            self._status.showMessage(tr("start.free_mode"))
        else:
            name = self._project_data.get("name", "?")
            used_t = project_tile_estimate(self._project_data)
            used_p = project_pal_estimate(self._project_data)
            self._status.showMessage(
                f"{tr('status.project', name=name)}   |   "
                f"{tr('status.tiles', used=used_t, total=TILE_MAX)}   |   "
                f"{tr('status.palettes', used=used_p, total=PAL_MAX_SPR)}"
            )

    # ------------------------------------------------------------------
    # Cross-tab communication
    # ------------------------------------------------------------------

    def _canonical_scene_ref(self, scene) -> dict | None:
        """
        Some tabs/widgets may emit a detached scene dict (copy) via Qt item data.
        Always resolve to the in-project reference so edits persist in self._project_data.
        """
        if scene is None:
            return None
        if not isinstance(scene, dict):
            return None
        scenes = self._project_data.get("scenes", []) if isinstance(self._project_data, dict) else []
        if not isinstance(scenes, list) or not scenes:
            return scene

        sid = str(scene.get("id") or "").strip()
        if sid:
            for s in scenes:
                if isinstance(s, dict) and str(s.get("id") or "").strip() == sid:
                    return s

        label = str(scene.get("label") or "").strip()
        if label:
            for s in scenes:
                if isinstance(s, dict) and str(s.get("label") or "").strip() == label:
                    return s

        return scene

    def _on_scene_activated(self, scene) -> None:
        """Called when the user selects a scene in ProjectTab."""
        self._flush_live_scene_state()
        scene = self._canonical_scene_ref(scene)
        base_dir = self._project_path.parent if self._project_path else None
        self._palette_tab.set_scene(scene, base_dir)
        self._editor_tab.set_scene(scene, base_dir)
        self._bundle_tab.set_scene(scene, base_dir)
        self._tilemap_tab.set_scene(scene, base_dir)
        self._level_tab.set_scene(scene, base_dir, self._project_data)
        self._dialogues_tab.set_scene(scene, base_dir, self._project_data)
        self._vram_tab.set_scene(scene, base_dir)
        self._hitbox_tab.set_project(self._project_data, base_dir)
        self._hitbox_tab.set_scene(scene, base_dir)
        self._vram_tab.refresh(self._project_data, self._project_path)
        self._navigator.set_project_data(self._project_data)
        self._navigator.set_current_scene(scene)
        self._update_status()

    def _on_scene_modified(self, scene) -> None:
        self._save_project()
        self._on_scene_activated(scene)

    def _on_navigator_scene_requested(self, scene) -> None:
        scene = self._canonical_scene_ref(scene)
        if scene is None:
            return
        if self._project_tab.select_scene(scene):
            return
        self._on_scene_activated(scene)

    def _open_in_palette(self, path) -> None:
        self._navigate_to(self._palette_tab)
        p = Path(path)
        base_dir = self._project_path.parent if self._project_path else None
        if base_dir and not p.is_absolute():
            p = base_dir / p
        self._palette_tab.open_path(p)

    def _open_in_tilemap(self, path) -> None:
        self._navigate_to(self._tilemap_tab)
        p = Path(path)
        base_dir = self._project_path.parent if self._project_path else None
        if base_dir and not p.is_absolute():
            p = base_dir / p
        self._tilemap_tab.open_path(p)

    def _open_in_editor(self, path) -> None:
        self._navigate_to(self._editor_tab)
        p = Path(path)
        base_dir = self._project_path.parent if self._project_path else None
        if base_dir and not p.is_absolute():
            p = base_dir / p
        self._editor_tab.open_path(p)

    def _open_in_hitbox(self, payload) -> None:
        """
        Payload can be:
          - Path / str: open file without scene context
          - dict: {sprite_meta dict + optional base_dir}
        """
        self._navigate_to(self._hitbox_tab)
        base_dir = self._project_path.parent if self._project_path else None
        if isinstance(payload, dict):
            self._hitbox_tab.open_sprite(payload, base_dir)
        else:
            self._hitbox_tab.open_path(Path(payload))

    def _open_sprite_in_palette(self, payload) -> None:
        """
        Payload can be:
          - Path / str: open file only
          - dict: {path, frame_w, frame_h, frame_count}
        """
        self._navigate_to(self._palette_tab)
        if isinstance(payload, dict):
            p = Path(payload.get("path", ""))
            fw = int(payload.get("frame_w", 8))
            fh = int(payload.get("frame_h", 8))
            fc = int(payload.get("frame_count", 1))
            base_dir = self._project_path.parent if self._project_path else None
            if base_dir and not p.is_absolute():
                p = base_dir / p
            self._palette_tab.open_sprite(p, fw, fh, fc)
        else:
            p = Path(payload)
            base_dir = self._project_path.parent if self._project_path else None
            if base_dir and not p.is_absolute():
                p = base_dir / p
            self._palette_tab.open_path(p)

    def _open_scene_tab(self, tab_name: str) -> None:
        target = {
            "project": getattr(self, "_project_tab", None),
            "palette": getattr(self, "_palette_tab", None),
            "tilemap": getattr(self, "_tilemap_tab", None),
            "level": getattr(self, "_level_tab", None),
            "hitbox": getattr(self, "_hitbox_tab", None),
        }.get(str(tab_name or "").strip().lower())
        if target is None:
            return
        self._navigate_to(target)

    def _apply_anim_to_scene(self, payload: dict) -> None:
        if self._is_free_mode:
            return
        scene = self._project_tab.current_scene()
        if not scene or not payload:
            return
        p = Path(payload.get("path", ""))
        fw = int(payload.get("frame_w", 8))
        fh = int(payload.get("frame_h", 8))
        fc = int(payload.get("frame_count", 1))

        base_dir = self._project_path.parent if self._project_path else None
        if base_dir and not p.is_absolute():
            p = base_dir / p
        try:
            target = p.resolve()
        except Exception:
            target = p

        updated = False
        for spr in scene.get("sprites", []) or []:
            rel = spr.get("file", "")
            if not rel:
                continue
            sp = Path(rel)
            if base_dir and not sp.is_absolute():
                sp = base_dir / sp
            try:
                sp2 = sp.resolve()
            except Exception:
                sp2 = sp
            if sp2 == target:
                spr["frame_w"] = fw
                spr["frame_h"] = fh
                spr["frame_count"] = fc
                updated = True
                break

        if not updated:
            return

        self._save_project()
        self._project_tab.refresh_current_scene()
        self._on_scene_activated(scene)
        self._palette_tab.show_status(tr("pal.anim_applied"))

    def _apply_scene_palette(self, payload: dict) -> None:
        """
        Called when PaletteTab finishes applying a shared-palette remap.
        payload = {"old": old_key, "new": new_key}
        Updates fixed_palette fields on all sprites in the current scene that
        matched old_key, so the project stays consistent.
        """
        if self._is_free_mode:
            return
        old_key: str = payload.get("old", "")
        new_key: str = payload.get("new", "")
        if not old_key or not new_key or old_key == new_key:
            return

        updated = False
        for scene in self._project_data.get("scenes", []) or []:
            for spr in scene.get("sprites", []) or []:
                fp = str(spr.get("fixed_palette") or "").strip()
                if not fp:
                    continue
                # Normalise to the same format as old_key for comparison
                from ui.tabs.palette_tab import _fixed_palette_key, _parse_fixed_palette_words
                words = _parse_fixed_palette_words(fp)
                if words is None:
                    continue
                if _fixed_palette_key(words) == old_key:
                    spr["fixed_palette"] = new_key
                    updated = True

        if updated:
            self._save_project()
            scene = self._project_tab.current_scene()
            if scene:
                self._on_scene_activated(scene)

    # ------------------------------------------------------------------
    # App update check
    # ------------------------------------------------------------------

    def _start_silent_update_check(self) -> None:
        """Delegate to HelpTab's background update checker (non-blocking)."""
        try:
            self._help_tab.start_silent_update_check()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Window events
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Persist window geometry before the application closes."""
        settings = QSettings("NGPCraft", "Engine")
        settings.setValue("main_window/geometry", self.saveGeometry())
        if hasattr(self, "_central_splitter"):
            settings.setValue("main_window/central_splitter", self._central_splitter.saveState())
        if not self._is_free_mode:
            self._save_project()
        super().closeEvent(event)
