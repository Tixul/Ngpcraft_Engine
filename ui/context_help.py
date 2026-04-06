"""
ui/context_help.py - Small reusable contextual help callout for dense tool UIs.

The widget is intentionally lightweight:
- short title + rich-text body
- collapsible to avoid permanently occupying space
- local stylesheet so it can be dropped into existing tabs without side effects
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget
from i18n.lang import tr


class ContextHelpBox(QFrame):
    """Compact collapsible help block used inside tabs near the active controls."""

    def __init__(
        self,
        title: str,
        body: str,
        parent: QWidget | None = None,
        *,
        expanded: bool = True,
    ) -> None:
        super().__init__(parent)
        self._dismissed = False
        self.setObjectName("contextHelpBox")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            """
            QFrame#contextHelpBox {
                background: #f6f1d5;
                border: 1px solid #d7c98a;
                border-radius: 6px;
            }
            QLabel#contextHelpTitle {
                color: #58481f;
                font-weight: 700;
            }
            QLabel#contextHelpBody {
                color: #58481f;
            }
            QToolButton#contextHelpToggle {
                border: none;
                padding: 0px;
            }
            QToolButton#contextHelpDismiss {
                border: none;
                padding: 0px 2px;
                color: #58481f;
                font-weight: 700;
            }
            QToolButton#contextHelpRestore {
                border: none;
                color: #58481f;
                font-weight: 700;
                padding: 1px 0px;
                text-align: left;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        self._content = QWidget(self)
        content_root = QVBoxLayout(self._content)
        content_root.setContentsMargins(0, 0, 0, 0)
        content_root.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        self._toggle = QToolButton(self)
        self._toggle.setObjectName("contextHelpToggle")
        self._toggle.setCheckable(True)
        self._toggle.setChecked(expanded)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._toggle.toggled.connect(self._on_toggled)
        header.addWidget(self._toggle, 0, Qt.AlignmentFlag.AlignTop)

        self._title = QLabel(title, self)
        self._title.setObjectName("contextHelpTitle")
        self._title.setWordWrap(True)
        header.addWidget(self._title, 1)

        self._dismiss = QToolButton(self)
        self._dismiss.setObjectName("contextHelpDismiss")
        self._dismiss.setText("×")
        self._dismiss.setToolTip(tr("ctx.hide_help"))
        self._dismiss.clicked.connect(self._hide_help)
        header.addWidget(self._dismiss, 0, Qt.AlignmentFlag.AlignTop)
        content_root.addLayout(header)

        self._body = QLabel(body, self)
        self._body.setObjectName("contextHelpBody")
        self._body.setWordWrap(True)
        self._body.setTextFormat(Qt.TextFormat.RichText)
        self._body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._body.setVisible(expanded)
        content_root.addWidget(self._body)

        self._restore = QToolButton(self)
        self._restore.setObjectName("contextHelpRestore")
        self._restore.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._restore.setText(tr("ctx.show_help"))
        self._restore.setToolTip(tr("ctx.show_help"))
        self._restore.clicked.connect(self._show_help)
        self._restore.setVisible(False)

        root.addWidget(self._content)
        root.addWidget(self._restore, 0, Qt.AlignmentFlag.AlignLeft)

        self._on_toggled(expanded)

    def _on_toggled(self, expanded: bool) -> None:
        """Show or hide the body while keeping the title visible."""
        self._toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self._toggle.setToolTip(
            tr("ctx.collapse_help") if expanded else tr("ctx.expand_help")
        )
        self._body.setVisible(expanded)

    def _hide_help(self) -> None:
        """Replace the help box with a compact restore link."""
        self._dismissed = True
        self._content.setVisible(False)
        self._restore.setVisible(True)

    def _show_help(self) -> None:
        """Restore the help box after it was dismissed."""
        self._dismissed = False
        self._content.setVisible(True)
        self._restore.setVisible(False)
