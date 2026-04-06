"""
ui/asset_browser.py - GraphX asset browser widget.

Features:
- Scan a GraphX folder recursively for images.
- Filter by text.
- Drag & drop assets as file URLs to other widgets (sprite list, palette/tab, etc.).
- Quick actions: open in Palette / open in Tilemap / add to scene as Sprite or Tilemap.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal, QFileSystemWatcher, QTimer
from PyQt6.QtGui import QDrag, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QCheckBox,
)

from i18n.lang import tr


_IMG_EXTS = (".png", ".bmp", ".gif")


class _AssetList(QListWidget):
    """List widget specialized for dragging asset file paths as local URLs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAlternatingRowColors(True)
        self.setUniformItemSizes(True)

    def startDrag(self, supportedActions) -> None:  # type: ignore[override]
        mime = self.mimeData(self.selectedItems())
        urls: list[QUrl] = []
        for it in self.selectedItems():
            p = it.data(Qt.ItemDataRole.UserRole)
            if not p:
                continue
            path = Path(str(p))
            if path.exists():
                urls.append(QUrl.fromLocalFile(str(path)))
        if not urls:
            return
        mime.setUrls(urls)
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(supportedActions)


class AssetBrowserWidget(QGroupBox):
    """Browsable, filterable GraphX asset list shared by multiple tabs."""

    open_palette_requested = pyqtSignal(Path)
    open_tilemap_requested = pyqtSignal(Path)
    open_editor_requested = pyqtSignal(Path)
    add_sprites_requested = pyqtSignal(object)   # list[Path]
    add_tilemaps_requested = pyqtSignal(object)  # list[Path]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(tr("asset.group"), parent)
        self._root: Path | None = None
        self._all_paths: list[Path] = []
        self._can_add: bool = False
        self._thumbs_enabled: bool = False
        self._thumb_cache: dict[str, tuple[float, QIcon]] = {}
        self._thumb_queue: list[int] = []
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(False)
        self._thumb_timer.timeout.connect(self._load_thumbs_batch)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_fs_changed)
        self._rescan_timer = QTimer(self)
        self._rescan_timer.setSingleShot(True)
        self._rescan_timer.timeout.connect(self._on_rescan_timer)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(6)

        top = QHBoxLayout()
        top.addWidget(QLabel(tr("asset.filter")))
        self._filter = QLineEdit()
        self._filter.setPlaceholderText(tr("asset.filter_hint"))
        self._filter.textChanged.connect(self._apply_filter)
        top.addWidget(self._filter, 1)
        self._auto_rescan = QCheckBox(tr("asset.auto_rescan"))
        self._auto_rescan.setChecked(True)
        self._auto_rescan.toggled.connect(lambda _checked: self._install_watcher())
        top.addWidget(self._auto_rescan)
        self._thumbs = QCheckBox(tr("asset.thumbs"))
        self._thumbs.setChecked(False)
        self._thumbs.toggled.connect(self._toggle_thumbs)
        top.addWidget(self._thumbs)
        self._btn_scan = QPushButton(tr("asset.rescan"))
        self._btn_scan.clicked.connect(self.scan)
        top.addWidget(self._btn_scan)
        root.addLayout(top)

        self._root_lbl = QLabel(tr("asset.no_root"))
        self._root_lbl.setStyleSheet("color: gray; font-style: italic;")
        root.addWidget(self._root_lbl)

        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet("color: gray;")
        root.addWidget(self._count_lbl)

        self._list = _AssetList()
        self._list.itemDoubleClicked.connect(self._on_double_click)
        self._list.verticalScrollBar().valueChanged.connect(lambda _v: self._schedule_visible_thumbs())
        root.addWidget(self._list, 1)

        btns = QHBoxLayout()
        self._btn_open_pal = QPushButton(tr("asset.open_palette"))
        self._btn_open_pal.clicked.connect(self._open_palette)
        btns.addWidget(self._btn_open_pal)

        self._btn_open_tm = QPushButton(tr("asset.open_tilemap"))
        self._btn_open_tm.clicked.connect(self._open_tilemap)
        btns.addWidget(self._btn_open_tm)

        self._btn_open_ed = QPushButton(tr("asset.open_editor"))
        self._btn_open_ed.clicked.connect(self._open_editor)
        btns.addWidget(self._btn_open_ed)

        self._btn_add_spr = QPushButton(tr("asset.add_sprites"))
        self._btn_add_spr.clicked.connect(self._add_sprites)
        btns.addWidget(self._btn_add_spr)

        self._btn_add_tm = QPushButton(tr("asset.add_tilemaps"))
        self._btn_add_tm.clicked.connect(self._add_tilemaps)
        btns.addWidget(self._btn_add_tm)

        btns.addStretch()
        root.addLayout(btns)

        self._set_enabled(False)

    def _set_enabled(self, on: bool) -> None:
        for w in (
            self._filter,
            self._btn_scan,
            self._list,
            self._btn_open_pal,
            self._btn_open_tm,
            self._btn_open_ed,
        ):
            w.setEnabled(on)
        self._btn_add_spr.setEnabled(on and self._can_add)
        self._btn_add_tm.setEnabled(on and self._can_add)
        self._auto_rescan.setEnabled(on)
        self._thumbs.setEnabled(on)

    def set_can_add(self, can_add: bool) -> None:
        """Enable or disable the scene-add actions exposed by the browser."""
        self._can_add = can_add
        on = bool(self._root and self._root.exists())
        self._btn_add_spr.setEnabled(on and can_add)
        self._btn_add_tm.setEnabled(on and can_add)

    def set_root(self, graphx_dir: Path | None) -> None:
        """Point the browser at a new GraphX root directory and refresh the listing."""
        self._root = graphx_dir
        self._all_paths = []
        self._list.clear()
        self._watcher.removePaths(self._watcher.directories())
        if not graphx_dir or not graphx_dir.exists():
            self._root_lbl.setText(tr("asset.no_root"))
            self._root_lbl.setStyleSheet("color: gray; font-style: italic;")
            self._count_lbl.setText("")
            self._set_enabled(False)
            return
        self._root_lbl.setText(tr("asset.root", path=str(graphx_dir)))
        self._root_lbl.setStyleSheet("")
        self._set_enabled(True)
        self.scan()

    def scan(self) -> None:
        """Rescan the active GraphX root recursively for supported image assets."""
        if not self._root or not self._root.exists():
            return
        paths: list[Path] = []
        for p in self._root.rglob("*"):
            if p.is_file() and p.suffix.lower() in _IMG_EXTS:
                paths.append(p)
        paths.sort(key=lambda x: str(x).lower())
        self._all_paths = paths
        self._apply_filter()
        self._install_watcher()

    def _install_watcher(self) -> None:
        self._watcher.removePaths(self._watcher.directories())
        if not self._root or not self._root.exists() or not self._auto_rescan.isChecked():
            return
        # Watch all subdirs so changes in nested folders also rescan.
        dirs = [self._root] + [p for p in self._root.rglob("*") if p.is_dir()]
        if len(dirs) > 2000:
            # Avoid creating huge watchers; allow manual rescan.
            self._auto_rescan.setChecked(False)
            QMessageBox.information(self, tr("asset.group"), tr("asset.too_many_dirs", n=len(dirs)))
            return
        self._watcher.addPaths([str(d) for d in dirs])

    def _on_fs_changed(self, _path: str) -> None:
        if not self._auto_rescan.isChecked():
            return
        # debounce; also handles burst events from editors
        self._rescan_timer.start(300)

    def _on_rescan_timer(self) -> None:
        self.scan()

    def _apply_filter(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        if not self._root:
            self._list.blockSignals(False)
            return
        q = (self._filter.text() or "").strip().lower()
        shown = 0
        for p in self._all_paths:
            rel = str(p.relative_to(self._root))
            if q and q not in rel.lower():
                continue
            item = QListWidgetItem(rel)
            item.setData(Qt.ItemDataRole.UserRole, str(p))
            self._list.addItem(item)
            shown += 1
            if shown >= 5000:
                break
        self._list.blockSignals(False)
        self._count_lbl.setText(tr("asset.count", shown=shown, total=len(self._all_paths)))
        self._schedule_visible_thumbs(force=True)

    def _toggle_thumbs(self, checked: bool) -> None:
        self._thumbs_enabled = bool(checked)
        if not self._thumbs_enabled:
            self._thumb_timer.stop()
            self._thumb_queue.clear()
            for i in range(self._list.count()):
                it = self._list.item(i)
                if it:
                    it.setIcon(QIcon())
            return
        self._schedule_visible_thumbs(force=True)

    def _schedule_visible_thumbs(self, force: bool = False) -> None:
        if not self._thumbs_enabled:
            return
        if self._list.count() == 0:
            return
        viewport = self._list.viewport()
        top_item = self._list.itemAt(4, 4)
        bot_item = self._list.itemAt(4, max(4, viewport.height() - 4))
        if top_item is None:
            return
        top = self._list.row(top_item)
        bot = self._list.row(bot_item) if bot_item is not None else min(self._list.count() - 1, top + 30)
        top = max(0, top - 12)
        bot = min(self._list.count() - 1, bot + 24)

        wanted = list(range(top, bot + 1))
        if force:
            self._thumb_queue = wanted
        else:
            seen = set(self._thumb_queue)
            for idx in wanted:
                if idx not in seen:
                    self._thumb_queue.append(idx)

        if self._thumb_queue and not self._thumb_timer.isActive():
            self._thumb_timer.start(10)

    def _load_thumbs_batch(self) -> None:
        if not self._thumb_queue:
            self._thumb_timer.stop()
            return
        budget = 10
        while self._thumb_queue and budget > 0:
            idx = self._thumb_queue.pop(0)
            it = self._list.item(idx)
            if it is None:
                budget -= 1
                continue
            p = it.data(Qt.ItemDataRole.UserRole)
            if not p:
                budget -= 1
                continue
            path = Path(str(p))
            if not path.exists():
                budget -= 1
                continue
            try:
                mtime = path.stat().st_mtime
            except Exception:
                budget -= 1
                continue
            cached = self._thumb_cache.get(str(path))
            if cached and cached[0] == mtime:
                it.setIcon(cached[1])
                budget -= 1
                continue
            pm = QPixmap(str(path))
            if pm.isNull():
                budget -= 1
                continue
            pm = pm.scaled(42, 42, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
            icon = QIcon(pm)
            self._thumb_cache[str(path)] = (mtime, icon)
            it.setIcon(icon)
            budget -= 1

    def _current_path(self) -> Path | None:
        item = self._list.currentItem()
        if item is None:
            return None
        p = item.data(Qt.ItemDataRole.UserRole)
        if not p:
            return None
        return Path(str(p))

    def _selected_paths(self) -> list[Path]:
        out: list[Path] = []
        for it in self._list.selectedItems():
            p = it.data(Qt.ItemDataRole.UserRole)
            if not p:
                continue
            path = Path(str(p))
            if path.exists():
                out.append(path)
        return out

    def _on_double_click(self, _item: QListWidgetItem) -> None:
        p = self._current_path()
        if p:
            self.open_palette_requested.emit(p)

    def _open_palette(self) -> None:
        p = self._current_path()
        if p:
            self.open_palette_requested.emit(p)

    def _open_tilemap(self) -> None:
        p = self._current_path()
        if p:
            self.open_tilemap_requested.emit(p)

    def _open_editor(self) -> None:
        p = self._current_path()
        if p:
            self.open_editor_requested.emit(p)

    def _add_sprites(self) -> None:
        paths = self._selected_paths()
        if paths:
            self.add_sprites_requested.emit(paths)

    def _add_tilemaps(self) -> None:
        paths = self._selected_paths()
        if paths:
            self.add_tilemaps_requested.emit(paths)
