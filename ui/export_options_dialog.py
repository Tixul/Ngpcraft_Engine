from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from i18n.lang import tr


@dataclass
class ExportOptions:
    """Serializable set of export toggles chosen by the user."""

    scope: str = "all"
    include_disabled_assets: bool = False
    export_sprites: bool = True
    export_tilemaps: bool = True
    export_hitbox_props: bool = True
    export_level_data: bool = True
    export_scene_loader: bool = True
    export_scenes_autogen: bool = True
    export_autogen_mk: bool = True


class ExportOptionsDialog(QDialog):
    """Dialog used to choose which parts of a scene/project export should run."""

    def __init__(self, parent: QWidget | None = None, *, title: str | None = None, allow_scope: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle(title or tr("export_opts.title"))

        root = QVBoxLayout(self)
        root.setSpacing(8)

        self._scope_all = QRadioButton(tr("export_opts.scope_all"))
        self._scope_current = QRadioButton(tr("export_opts.scope_current"))
        self._scope_all.setChecked(True)

        if allow_scope:
            g_scope = QGroupBox(tr("export_opts.scope_group"))
            v = QVBoxLayout(g_scope)
            v.addWidget(self._scope_all)
            v.addWidget(self._scope_current)
            root.addWidget(g_scope)

        g_assets = QGroupBox(tr("export_opts.assets_group"))
        v_assets = QVBoxLayout(g_assets)
        self._chk_sprites = QCheckBox(tr("export_opts.export_sprites"))
        self._chk_tilemaps = QCheckBox(tr("export_opts.export_tilemaps"))
        self._chk_include_disabled = QCheckBox(tr("export_opts.include_disabled"))
        self._chk_sprites.setChecked(True)
        self._chk_tilemaps.setChecked(True)
        self._chk_include_disabled.setChecked(False)
        v_assets.addWidget(self._chk_sprites)
        v_assets.addWidget(self._chk_tilemaps)
        v_assets.addWidget(self._chk_include_disabled)
        root.addWidget(g_assets)

        g_meta = QGroupBox(tr("export_opts.meta_group"))
        v_meta = QVBoxLayout(g_meta)
        self._chk_hitbox = QCheckBox(tr("export_opts.export_hitbox"))
        self._chk_level = QCheckBox(tr("export_opts.export_level"))
        self._chk_scene_loader = QCheckBox(tr("export_opts.export_scene_loader"))
        self._chk_scenes_autogen = QCheckBox(tr("export_opts.export_scenes_autogen"))
        self._chk_autogen_mk = QCheckBox(tr("export_opts.export_autogen_mk"))
        for w in (self._chk_hitbox, self._chk_level, self._chk_scene_loader, self._chk_scenes_autogen, self._chk_autogen_mk):
            w.setChecked(True)
        v_meta.addWidget(self._chk_hitbox)
        v_meta.addWidget(self._chk_level)
        v_meta.addWidget(self._chk_scene_loader)
        v_meta.addWidget(self._chk_scenes_autogen)
        v_meta.addWidget(self._chk_autogen_mk)
        root.addWidget(g_meta)

        self._note = QLabel(tr("export_opts.note"))
        self._note.setWordWrap(True)
        self._note.setStyleSheet("color: #888; font-size: 10px;")
        root.addWidget(self._note)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        root.addWidget(btns)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        self._chk_sprites.toggled.connect(self._sync_checks)
        self._chk_tilemaps.toggled.connect(self._sync_checks)
        self._sync_checks()

    def _sync_checks(self) -> None:
        self._chk_hitbox.setEnabled(self._chk_sprites.isChecked())
        if not self._chk_sprites.isChecked():
            self._chk_hitbox.setChecked(False)

    def options(self) -> ExportOptions:
        """Return the current checkbox/radio state as an `ExportOptions` object."""
        scope = "current" if self._scope_current.isChecked() else "all"
        return ExportOptions(
            scope=scope,
            include_disabled_assets=self._chk_include_disabled.isChecked(),
            export_sprites=self._chk_sprites.isChecked(),
            export_tilemaps=self._chk_tilemaps.isChecked(),
            export_hitbox_props=self._chk_hitbox.isChecked(),
            export_level_data=self._chk_level.isChecked(),
            export_scene_loader=self._chk_scene_loader.isChecked(),
            export_scenes_autogen=self._chk_scenes_autogen.isChecked(),
            export_autogen_mk=self._chk_autogen_mk.isChecked(),
        )
