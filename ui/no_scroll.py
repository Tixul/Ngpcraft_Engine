"""no_scroll.py — Drop-in replacements for QSpinBox, QDoubleSpinBox, QComboBox.

Wheel events are ignored unless the widget has keyboard focus (i.e. the user
explicitly clicked or tabbed into it).  When ignored, Qt automatically
propagates the wheel event to the parent widget (typically a QScrollArea),
so the panel still scrolls normally.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QComboBox, QDoubleSpinBox, QSpinBox


class NoScrollSpinBox(QSpinBox):
    def wheelEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()


class NoScrollDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()


class NoScrollComboBox(QComboBox):
    def wheelEvent(self, event) -> None:  # type: ignore[override]
        event.ignore()
