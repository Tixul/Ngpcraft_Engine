"""
ui/new_project_wizard.py - Wizard for creating a new NGPC C project.

3-page QWizard:
  Page 1 (Identity) : project name, ROM identifier, cart title, destination folder
  Page 2 (Options)  : Makefile feature flags (sound, flash save, debug, DMA)
  Page 3 (Tools)    : compiler path, emulator path

After exec() returns Accepted:
  wizard.chosen_path  -> Path to the created project.ngpcraft
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
    QCheckBox,
    QComboBox,
)

from core.project_scaffold import (
    ScaffoldParams,
    derive_cart_title,
    find_template_root,
    sanitize_rom_name,
    scaffold_project,
)
from core.project_templates import DEFAULT_TEMPLATE_ID, list_project_templates
from i18n.lang import tr

_SETTINGS_ORG = "NGPC"
_SETTINGS_APP = "GraphXManager"


# ---------------------------------------------------------------------------
# Page 1 — Identity
# ---------------------------------------------------------------------------

class _IdentityPage(QWizardPage):
    """Wizard page collecting project name, destination and starter template."""

    def __init__(self, parent: QWizard) -> None:
        super().__init__(parent)
        self.setTitle(tr("wizard.page_identity"))
        self.setSubTitle(tr("wizard.page_identity_sub"))

        settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        default_dir = settings.value("wizard/dest_dir", str(Path.home() / "Documents"), type=str)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Project name
        name_row = QHBoxLayout()
        name_lbl = QLabel(tr("wizard.name_label"))
        name_lbl.setFixedWidth(160)
        self._name_edit = QLineEdit("MonJeu")
        self._name_edit.setPlaceholderText("MonJeu")
        name_row.addWidget(name_lbl)
        name_row.addWidget(self._name_edit)
        layout.addLayout(name_row)

        # ROM identifier (auto-derived, editable)
        rom_row = QHBoxLayout()
        rom_lbl = QLabel(tr("wizard.rom_name_label"))
        rom_lbl.setFixedWidth(160)
        self._rom_edit = QLineEdit()
        self._rom_edit.setPlaceholderText("mon_jeu")
        rom_row.addWidget(rom_lbl)
        rom_row.addWidget(self._rom_edit)
        layout.addLayout(rom_row)
        rom_hint = QLabel(tr("wizard.rom_name_hint"))
        rom_hint.setStyleSheet("color: gray; font-style: italic; margin-left: 165px;")
        layout.addWidget(rom_hint)

        # Cart title (auto-derived, editable, 12-char limit)
        cart_row = QHBoxLayout()
        cart_lbl = QLabel(tr("wizard.cart_title_label"))
        cart_lbl.setFixedWidth(160)
        self._cart_edit = QLineEdit()
        self._cart_edit.setPlaceholderText("MON JEU")
        self._cart_edit.setMaxLength(12)
        cart_row.addWidget(cart_lbl)
        cart_row.addWidget(self._cart_edit)
        layout.addLayout(cart_row)
        cart_hint = QLabel(tr("wizard.cart_title_hint"))
        cart_hint.setStyleSheet("color: gray; font-style: italic; margin-left: 165px;")
        layout.addWidget(cart_hint)

        # Destination folder
        dest_lbl = QLabel(tr("wizard.dest_label"))
        layout.addWidget(dest_lbl)
        dest_row = QHBoxLayout()
        self._dest_edit = QLineEdit(default_dir)
        self._dest_edit.setMinimumWidth(220)
        browse_btn = QPushButton(tr("wizard.browse"))
        browse_btn.clicked.connect(self._browse_dest)
        dest_row.addWidget(self._dest_edit)
        dest_row.addWidget(browse_btn)
        layout.addLayout(dest_row)

        # Path preview label
        self._preview_lbl = QLabel()
        self._preview_lbl.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(self._preview_lbl)

        # Starter template
        tpl_group = QGroupBox(tr("wizard.template_group"))
        tpl_layout = QVBoxLayout(tpl_group)
        tpl_row = QHBoxLayout()
        tpl_lbl = QLabel(tr("wizard.template_label"))
        tpl_lbl.setFixedWidth(160)
        self._template_combo = QComboBox()
        for spec in list_project_templates():
            self._template_combo.addItem(tr(spec.label_key), spec.template_id)
        saved_tpl = settings.value("wizard/template_id", DEFAULT_TEMPLATE_ID, type=str)
        idx = self._template_combo.findData(saved_tpl)
        if idx >= 0:
            self._template_combo.setCurrentIndex(idx)
        tpl_row.addWidget(tpl_lbl)
        tpl_row.addWidget(self._template_combo)
        tpl_layout.addLayout(tpl_row)

        self._template_desc = QLabel()
        self._template_desc.setWordWrap(True)
        self._template_desc.setStyleSheet("color: gray; font-style: italic; margin-left: 165px;")
        tpl_layout.addWidget(self._template_desc)
        self._template_combo.currentIndexChanged.connect(self._on_template_changed)
        self._on_template_changed()
        layout.addWidget(tpl_group)

        layout.addStretch()

        # Connections: auto-derive rom/cart from name
        self._name_edit.textChanged.connect(self._on_name_changed)
        self._dest_edit.textChanged.connect(self._update_preview)
        self._name_edit.textChanged.connect(self._update_preview)

        self._auto_rom = True   # track whether rom field has been manually edited
        self._auto_cart = True
        self._rom_edit.textEdited.connect(lambda: setattr(self, "_auto_rom", False))
        self._cart_edit.textEdited.connect(lambda: setattr(self, "_auto_cart", False))

        self._on_name_changed(self._name_edit.text())

    # ------------------------------------------------------------------
    def _on_name_changed(self, text: str) -> None:
        if self._auto_rom:
            self._rom_edit.setText(sanitize_rom_name(text))
        if self._auto_cart:
            self._cart_edit.setText(derive_cart_title(text).strip())
        self._update_preview()

    def _update_preview(self) -> None:
        base = self._dest_edit.text().strip()
        name = self._name_edit.text().strip() or "MonJeu"
        if base:
            full = str(Path(base) / name)
            self._preview_lbl.setText(tr("wizard.dest_preview").format(path=full))
        else:
            self._preview_lbl.setText("")

    def _browse_dest(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, tr("wizard.dest_label"), self._dest_edit.text()
        )
        if d:
            self._dest_edit.setText(d)

    def _on_template_changed(self) -> None:
        idx = self._template_combo.currentIndex()
        if idx < 0:
            self._template_desc.setText("")
            return
        template_id = str(self._template_combo.itemData(idx) or DEFAULT_TEMPLATE_ID)
        for spec in list_project_templates():
            if spec.template_id == template_id:
                self._template_desc.setText(tr(spec.desc_key))
                return
        self._template_desc.setText("")

    # ------------------------------------------------------------------
    def validatePage(self) -> bool:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, tr("wizard.title"), tr("wizard.name_empty"))
            self._name_edit.setFocus()
            return False

        base = self._dest_edit.text().strip()
        if not base:
            QMessageBox.warning(self, tr("wizard.title"), tr("wizard.dest_empty"))
            self._dest_edit.setFocus()
            return False

        dest = Path(base) / name
        if dest.exists():
            QMessageBox.warning(
                self,
                tr("wizard.title"),
                tr("wizard.dest_exists").format(path=str(dest)),
            )
            return False

        # Persist destination dir for next time
        settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        settings.setValue("wizard/dest_dir", base)
        settings.setValue("wizard/template_id", self.project_template())
        return True

    # ------------------------------------------------------------------
    # Accessors for the wizard
    def project_name(self) -> str:
        return self._name_edit.text().strip() or "MonJeu"

    def rom_name(self) -> str:
        return sanitize_rom_name(self._rom_edit.text() or self._name_edit.text())

    def cart_title(self) -> str:
        raw = self._cart_edit.text() or self._name_edit.text()
        return derive_cart_title(raw)

    def destination(self) -> Path:
        name = self._name_edit.text().strip() or "MonJeu"
        return Path(self._dest_edit.text().strip()) / name

    def project_template(self) -> str:
        return str(self._template_combo.currentData() or DEFAULT_TEMPLATE_ID)


# ---------------------------------------------------------------------------
# Page 2 — Options
# ---------------------------------------------------------------------------

class _OptionsPage(QWizardPage):
    """Wizard page exposing the Makefile feature toggles for the new project."""

    def __init__(self, parent: QWizard) -> None:
        super().__init__(parent)
        self.setTitle(tr("wizard.page_options"))
        self.setSubTitle(tr("wizard.page_options_sub"))

        layout = QVBoxLayout(self)

        grp = QGroupBox("Makefile")
        grp_layout = QVBoxLayout(grp)

        self._sound_cb = QCheckBox(tr("wizard.sound_label"))
        self._sound_cb.setChecked(True)
        self._flash_cb = QCheckBox(tr("wizard.flash_label"))
        self._flash_cb.setChecked(False)
        self._debug_cb = QCheckBox(tr("wizard.debug_label"))
        self._debug_cb.setChecked(False)
        self._dma_cb = QCheckBox(tr("wizard.dma_label"))
        self._dma_cb.setChecked(False)

        grp_layout.addWidget(self._sound_cb)
        grp_layout.addWidget(self._flash_cb)
        grp_layout.addWidget(self._debug_cb)
        grp_layout.addWidget(self._dma_cb)

        layout.addWidget(grp)
        layout.addStretch()

    # Accessors
    def enable_sound(self) -> bool:
        return self._sound_cb.isChecked()

    def enable_flash_save(self) -> bool:
        return self._flash_cb.isChecked()

    def enable_debug(self) -> bool:
        return self._debug_cb.isChecked()

    def enable_dma(self) -> bool:
        return self._dma_cb.isChecked()


# ---------------------------------------------------------------------------
# Page 3 — Tools
# ---------------------------------------------------------------------------

class _ToolsPage(QWizardPage):
    """Wizard page collecting compiler and emulator paths persisted in settings."""

    def __init__(self, parent: QWizard) -> None:
        super().__init__(parent)
        self.setTitle(tr("wizard.page_tools"))
        self.setSubTitle(tr("wizard.page_tools_sub"))

        settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        saved_compiler = settings.value("wizard/compiler_path", "", type=str)
        saved_system_lib = settings.value("wizard/system_lib_path", "", type=str)
        saved_emu = settings.value("run/emulator_path", "", type=str)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Compiler
        compiler_lbl = QLabel(tr("wizard.compiler_label"))
        layout.addWidget(compiler_lbl)
        compiler_row = QHBoxLayout()
        self._compiler_edit = QLineEdit(saved_compiler)
        self._compiler_edit.setPlaceholderText("C:\\ngpcbins\\T900")
        browse_cc = QPushButton(tr("wizard.browse"))
        browse_cc.clicked.connect(self._browse_compiler)
        compiler_row.addWidget(self._compiler_edit)
        compiler_row.addWidget(browse_cc)
        layout.addLayout(compiler_row)
        compiler_hint = QLabel(tr("wizard.compiler_hint"))
        compiler_hint.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(compiler_hint)

        layout.addSpacing(12)

        # system.lib (optional, required only for flash save)
        system_lib_lbl = QLabel(tr("wizard.system_lib_label"))
        layout.addWidget(system_lib_lbl)
        system_lib_row = QHBoxLayout()
        self._system_lib_edit = QLineEdit(saved_system_lib)
        self._system_lib_edit.setPlaceholderText("C:\\path\\to\\system.lib")
        browse_system_lib = QPushButton(tr("wizard.browse"))
        browse_system_lib.clicked.connect(self._browse_system_lib)
        system_lib_row.addWidget(self._system_lib_edit)
        system_lib_row.addWidget(browse_system_lib)
        layout.addLayout(system_lib_row)
        system_lib_hint = QLabel(tr("wizard.system_lib_hint"))
        system_lib_hint.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(system_lib_hint)

        layout.addSpacing(12)

        # Emulator (optional)
        emu_lbl = QLabel(tr("wizard.emu_label"))
        layout.addWidget(emu_lbl)
        emu_row = QHBoxLayout()
        self._emu_edit = QLineEdit(saved_emu)
        self._emu_edit.setPlaceholderText("C:\\emu\\race.exe")
        browse_emu = QPushButton(tr("wizard.browse"))
        browse_emu.clicked.connect(self._browse_emu)
        emu_row.addWidget(self._emu_edit)
        emu_row.addWidget(browse_emu)
        layout.addLayout(emu_row)
        emu_hint = QLabel(tr("wizard.emu_hint"))
        emu_hint.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(emu_hint)

        layout.addSpacing(16)

        # Toshiba warning
        note = QLabel(tr("wizard.toshiba_note"))
        note.setWordWrap(True)
        note.setStyleSheet("color: #cc8800;")
        layout.addWidget(note)

        layout.addStretch()

    # ------------------------------------------------------------------
    def _browse_compiler(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, tr("wizard.compiler_label"), self._compiler_edit.text()
        )
        if d:
            self._compiler_edit.setText(d)

    def _browse_system_lib(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("wizard.system_lib_label"),
            self._system_lib_edit.text(),
            "Library (*.lib);;All files (*.*)",
        )
        if path:
            self._system_lib_edit.setText(path)

    def _browse_emu(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("wizard.emu_label"),
            self._emu_edit.text(),
            "Exécutable (*.exe);;Tous les fichiers (*.*)",
        )
        if path:
            self._emu_edit.setText(path)

    def validatePage(self) -> bool:
        # Persist settings
        settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        settings.setValue("wizard/compiler_path", self._compiler_edit.text().strip())
        settings.setValue("wizard/system_lib_path", self._system_lib_edit.text().strip())
        settings.setValue("run/emulator_path", self._emu_edit.text().strip())
        return True

    # Accessors
    def compiler_path(self) -> str:
        return self._compiler_edit.text().strip()

    def system_lib_path(self) -> str:
        return self._system_lib_edit.text().strip()

    def emulator_path(self) -> str:
        return self._emu_edit.text().strip()


# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------

class NewNgpcProjectWizard(QWizard):
    """
    3-page wizard that scaffolds a new NGPC C project from the bundled template.

    After exec() == Accepted:
        self.chosen_path  ->  Path to the created project.ngpcraft  (or None on failure)
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.chosen_path: Path | None = None

        self.setWindowTitle(tr("wizard.title"))
        self.setMinimumWidth(520)
        self.setMinimumHeight(380)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)

        self._template_root = find_template_root()

        self._page1 = _IdentityPage(self)
        self._page2 = _OptionsPage(self)
        self._page3 = _ToolsPage(self)

        self.addPage(self._page1)
        self.addPage(self._page2)
        self.addPage(self._page3)

    # ------------------------------------------------------------------
    def accept(self) -> None:
        """Called when the user clicks Finish on the last page."""
        if not self._template_root:
            QMessageBox.critical(self, tr("wizard.title"), tr("wizard.no_template"))
            return  # do NOT call super().accept() → dialog stays open

        params = ScaffoldParams(
            destination=self._page1.destination(),
            project_name=self._page1.project_name(),
            rom_name=self._page1.rom_name(),
            cart_title=self._page1.cart_title(),
            project_template=self._page1.project_template(),
            enable_sound=self._page2.enable_sound(),
            enable_flash_save=self._page2.enable_flash_save(),
            enable_debug=self._page2.enable_debug(),
            enable_dma=self._page2.enable_dma(),
            compiler_path=self._page3.compiler_path(),
            system_lib_path=self._page3.system_lib_path(),
            emulator_path=self._page3.emulator_path(),
        )

        try:
            ngpng_path = scaffold_project(params, self._template_root)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self,
                tr("wizard.title"),
                tr("wizard.create_error").format(err=exc),
            )
            return  # stay open so user can fix the problem

        self.chosen_path = ngpng_path
        super().accept()
