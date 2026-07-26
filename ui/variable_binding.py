"""
ui/variable_binding.py — Reusable widget to bind a mechanic config field to a
project game variable.

Use case: a mechanic config (e.g. battle_engine.xp_variable) needs to reference
a project-level variable that other systems can read/write (display in HUD,
quest rewards, etc.). This widget surfaces:
  - a dropdown of the 16 game_vars (named or "(libre)")
  - a "(aucune)" entry to mean "unbound / feature disabled"
  - a "➕ Créer / nommer une variable…" entry that opens an inline dialog
    to name a free slot (or rename the current one) without leaving the
    mechanic config panel.

Storage : the binding value is an int 0-15 (slot index) or None (unbound).
The widget mutates `project_data["game_vars"][slot]` when the inline dialog
saves a new name/init, and calls the provided `on_save` callback so the parent
panel can persist the change.

Limitation v1 : project game_vars are u8 (0-255). For XP/gold counters that
exceed 255, the value caps. v2 should add u16-pair support.

Typical use::

    self.xp_picker = VariableBindingWidget(
        project_data=self._data,
        on_save=self._save,
        usage_label="XP",
    )
    self.xp_picker.set_binding(current_xp_slot_or_None)
    self.xp_picker.binding_changed.connect(self._on_xp_var_changed)
    form.addRow("Variable XP :", self.xp_picker)
"""
from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QShowEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

# Mirror of core.game_vars_gen._COUNT — kept here as a constant so this module
# stays self-contained (no Qt-on-import-time core dep cycle).
GAME_VAR_COUNT = 16

_CREATE_SENTINEL = "__create__"


class VariableBindingWidget(QWidget):
    """Combo + edit button that binds a config field to a project game_var.

    Emits :sig:`binding_changed(int | None)` whenever the user selects a
    different variable (or unbinds it). Does not emit when the inline
    "Créer / nommer" dialog merely renames a slot without changing the bound
    slot — call :meth:`refresh` from outside if you need to repaint after
    external edits to ``project_data["game_vars"]``.
    """

    binding_changed = pyqtSignal(object)  # int | None

    def __init__(
        self,
        project_data: dict,
        on_save: Callable[[], None] = lambda: None,
        usage_label: str = "variable",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._data = project_data
        self._on_save = on_save
        self._usage_label = usage_label
        self._current: Optional[int] = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self._combo = QComboBox()
        self._combo.setMinimumWidth(200)
        self._combo.setToolTip(
            "Sélectionne la variable projet liée à ce champ.\n"
            "« (aucune) » = système désactivé / valeur ignorée.\n"
            "« Créer / nommer » = ouvre un dialog pour nommer un slot libre."
        )
        self._combo.currentIndexChanged.connect(self._on_combo_changed)
        lay.addWidget(self._combo, 1)

        self._btn_edit = QPushButton("✏")
        self._btn_edit.setFixedWidth(28)
        self._btn_edit.setToolTip("Renommer la variable bound ou créer/nommer une nouvelle")
        self._btn_edit.clicked.connect(self._open_create_dialog)
        lay.addWidget(self._btn_edit)

        self.refresh()

    # ---------------------------------------------------------------- API

    def get_binding(self) -> Optional[int]:
        """Return the bound slot index (0-15) or None if unbound."""
        return self._current

    def set_binding(self, slot: Optional[int]) -> None:
        """Set the bound slot programmatically. Does NOT emit binding_changed."""
        if isinstance(slot, int) and 0 <= slot < GAME_VAR_COUNT:
            self._current = slot
        else:
            self._current = None
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the combo from current project data. Preserves selection."""
        self._combo.blockSignals(True)
        self._combo.clear()
        self._combo.addItem("(aucune — désactivé)", None)

        vars_list = self._read_vars_list()
        for i in range(GAME_VAR_COUNT):
            entry = vars_list[i] if i < len(vars_list) and isinstance(vars_list[i], dict) else {}
            name = str(entry.get("name", "") or "").strip()
            init = int(entry.get("init", 0) or 0)
            if name:
                label = f"Var {i} — {name} (init {init})"
            else:
                label = f"Var {i} — (libre)"
            self._combo.addItem(label, i)

        self._combo.insertSeparator(self._combo.count())
        self._combo.addItem("➕ Créer / nommer une variable…", _CREATE_SENTINEL)

        # Restore selection
        target_idx = 0  # default = (aucune)
        if isinstance(self._current, int):
            for i in range(self._combo.count()):
                if self._combo.itemData(i) == self._current:
                    target_idx = i
                    break
        self._combo.setCurrentIndex(target_idx)
        self._combo.blockSignals(False)

    # ---------------------------------------------------------------- Qt

    def showEvent(self, event: QShowEvent) -> None:  # type: ignore[override]
        # Refresh names on every show — picks up renames done in Globals tab.
        self.refresh()
        super().showEvent(event)

    # ---------------------------------------------------------- handlers

    def _on_combo_changed(self, index: int) -> None:
        data = self._combo.itemData(index)
        if data == _CREATE_SENTINEL:
            # Pop the dialog. If accepted, _open_create_dialog will update
            # self._current and emit. Always refresh to undo the selection if
            # the user cancelled.
            self._open_create_dialog()
            self.refresh()
            return
        new_val = data if isinstance(data, int) else None
        if new_val != self._current:
            self._current = new_val
            self.binding_changed.emit(new_val)

    # ---------------------------------------------------------- helpers

    def _read_vars_list(self) -> list:
        if not isinstance(self._data, dict):
            return []
        v = self._data.get("game_vars", [])
        return v if isinstance(v, list) else []

    def _pad_vars_list(self) -> list:
        vars_list = list(self._read_vars_list())
        while len(vars_list) < GAME_VAR_COUNT:
            vars_list.append({"name": "", "init": 0})
        return vars_list

    def _open_create_dialog(self) -> None:
        """Dialog : choose slot + set name + set init value."""
        vars_list = self._pad_vars_list()

        # Default slot : current binding, or first unnamed slot, or 0.
        if isinstance(self._current, int):
            default_slot = self._current
        else:
            default_slot = next(
                (i for i in range(GAME_VAR_COUNT)
                 if not str((vars_list[i] if isinstance(vars_list[i], dict) else {}).get("name", "") or "").strip()),
                0,
            )

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Variable projet — {self._usage_label}")
        form = QFormLayout(dlg)

        slot_spin = QSpinBox()
        slot_spin.setRange(0, GAME_VAR_COUNT - 1)
        slot_spin.setValue(default_slot)
        slot_spin.setToolTip("Index du slot dans la table des 16 game_vars du projet")
        form.addRow("Slot (0-15) :", slot_spin)

        cur_entry = vars_list[default_slot] if isinstance(vars_list[default_slot], dict) else {}
        name_edit = QLineEdit(str(cur_entry.get("name", "") or ""))
        name_edit.setMaxLength(24)
        name_edit.setPlaceholderText(f"ex: {self._usage_label.lower()}_total")
        form.addRow("Nom :", name_edit)

        init_spin = QSpinBox()
        init_spin.setRange(0, 255)
        init_spin.setValue(int(cur_entry.get("init", 0) or 0))
        init_spin.setToolTip("Valeur initiale (au démarrage du jeu)")
        form.addRow("Valeur initiale :", init_spin)

        warn = QLabel(
            "ℹ Les variables projet sont u8 (range 0-255). "
            "Pour des valeurs &gt; 255, paire de slots = chantier v2."
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color:#888;font-size:10px;")
        form.addRow(warn)

        # When user changes slot, repopulate name/init from that slot's data
        def _on_slot_changed(new_slot: int) -> None:
            e = vars_list[new_slot] if isinstance(vars_list[new_slot], dict) else {}
            name_edit.setText(str(e.get("name", "") or ""))
            init_spin.setValue(int(e.get("init", 0) or 0))
        slot_spin.valueChanged.connect(_on_slot_changed)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        chosen_slot = int(slot_spin.value())
        new_name = name_edit.text().strip()
        new_init = max(0, min(255, int(init_spin.value())))
        vars_list[chosen_slot] = {"name": new_name, "init": new_init}
        if isinstance(self._data, dict):
            self._data["game_vars"] = vars_list
        self._on_save()

        # Auto-bind to the chosen slot
        old = self._current
        self._current = chosen_slot
        self.refresh()
        if old != chosen_slot:
            self.binding_changed.emit(chosen_slot)
