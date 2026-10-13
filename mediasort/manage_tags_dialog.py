"""Manage tags window, opened from the database management window (F10).

Lists every tag of the database with its number of entries and gives each
one three actions:

  * the magnifier (🔍-like icon drawn in icons.py) shows the next
    occurrence of that tag - it starts from the currently displayed file
    and continues with the current folder before moving to other folders
    (see MainWindow.goto_tag_instance). The window stays open while the
    file behind it changes;
  * the trash deletes the tag and all of its entries from the database,
    after a confirmation;
  * clicking the tag name adds it to the "source tags" selection used by
    the merge / rename action below (removed again with the "×" of the
    selected-tags list).

The window also offers a Play/Pause button for the video shown behind it,
and keeps the merge/rename functionality of the earlier merge window.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLineEdit, QPushButton, QLabel, QGroupBox, QMessageBox, QWidget
)
from PySide6.QtCore import Qt, QEvent, QSize, Signal
from PySide6.QtGui import QKeyEvent

from .i18n import tr, tr_plural
from . import icons, styles
from .tags_db import MAX_TAG_LENGTH
from .tag_suggestions import TagSuggestionBox


class _ClickableLabel(QLabel):
    """A tag-name label that reports plain left clicks - clicking a tag in
    the list adds it to the merge/rename selection."""

    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ManageTagsDialog(QDialog):
    def __init__(self, tags_db, main_window=None, parent=None):
        super().__init__(parent)
        self.tags_db = tags_db
        self.main_window = main_window
        self.merged = False        # True once a merge/rename was performed
        self.deleted_any = False   # True once a tag was deleted
        self.playback_touched = False  # True once Play/Pause was pressed
        self.stats = None          # stats of the last merge (see merge_tags)

        # Source tags chosen for merging (in the order they were added),
        # the entry count of every tag, and the list rows/labels by name.
        self._selected = []
        self._counts = {}
        self._available_items = {}
        self._available_labels = {}

        self.setWindowTitle(tr("manage_tags.title"))
        self.resize(760, 560)
        self.setStyleSheet(styles.DIALOG)

        # Shortcut labels for the UI texts - both actions here (Enter /
        # Esc) are handled directly and are not configurable.
        self._shortcuts = {
            "enter_key": "Enter",
            "cancel_key": "Esc",
        }

        self._build_ui()
        self._reload_tags()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel(tr("manage_tags.info"), self)
        info.setWordWrap(True)
        layout.addWidget(info)

        sources_box = QGroupBox(tr("manage_tags.sources_group"), self)
        sources_layout = QVBoxLayout(sources_box)

        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText(tr("manage_tags.filter_placeholder"))
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.filter_edit.installEventFilter(self)
        sources_layout.addWidget(self.filter_edit)

        lists_row = QHBoxLayout()

        available_col = QVBoxLayout()
        available_col.addWidget(QLabel(tr("manage_tags.available_label"), self))
        self.available_list = QListWidget(self)
        self.available_list.setSelectionMode(QListWidget.SingleSelection)
        self.available_list.itemDoubleClicked.connect(self._add_item)
        self.available_list.itemSelectionChanged.connect(self._update_add_btn)
        # The list would otherwise swallow Enter (activating the item) -
        # see eventFilter.
        self.available_list.installEventFilter(self)
        available_col.addWidget(self.available_list)
        lists_row.addLayout(available_col, 1)

        add_col = QVBoxLayout()
        add_col.addStretch(1)
        self.add_btn = QPushButton(tr("manage_tags.add_btn"), self)
        self.add_btn.clicked.connect(self._add_current)
        add_col.addWidget(self.add_btn)
        add_col.addStretch(1)
        lists_row.addLayout(add_col)

        selected_col = QVBoxLayout()
        selected_col.addWidget(QLabel(tr("manage_tags.selected_label"), self))
        self.selected_list = QListWidget(self)
        # Rows are widgets with their own "×" button, so no row selection.
        self.selected_list.setSelectionMode(QListWidget.NoSelection)
        selected_col.addWidget(self.selected_list)

        self.selected_label = QLabel(self)
        self.selected_label.setStyleSheet(styles.INFO)
        selected_col.addWidget(self.selected_label)
        lists_row.addLayout(selected_col, 1)

        sources_layout.addLayout(lists_row)
        layout.addWidget(sources_box, 1)

        target_box = QGroupBox(tr("manage_tags.target_group"), self)
        target_layout = QVBoxLayout(target_box)
        self.target_edit = QLineEdit(self)
        self.target_edit.setMaxLength(MAX_TAG_LENGTH)
        self.target_edit.setPlaceholderText(tr("manage_tags.target_placeholder"))
        self.target_edit.textChanged.connect(lambda _text: self._update_summary())
        # Installed before the suggestion popup below, so the popup still
        # gets Escape/Enter first (it hides itself on Escape).
        self.target_edit.installEventFilter(self)
        target_layout.addWidget(self.target_edit)

        self.target_label = QLabel(self)
        self.target_label.setStyleSheet(styles.INFO)
        self.target_label.setWordWrap(True)
        target_layout.addWidget(self.target_label)
        layout.addWidget(target_box)

        # Tag autocomplete for the target field (same popup as the tagging
        # dialogs) - typing is what creates a renamed/new tag name.
        self._suggestions = TagSuggestionBox(
            self, self.target_edit, self.tags_db.all_tags
        )

        btn_row = QHBoxLayout()
        self.merge_btn = QPushButton(tr("manage_tags.apply_btn", **self._shortcuts), self)
        self.merge_btn.setStyleSheet(styles.PRIMARY_BUTTON)
        self.merge_btn.setDefault(True)
        self.merge_btn.clicked.connect(self._confirm_merge)
        btn_row.addWidget(self.merge_btn)

        self.play_btn = QPushButton(tr("manage_tags.play_btn"), self)
        self.play_btn.setStyleSheet(styles.SECONDARY_BUTTON)
        self.play_btn.setToolTip(tr("manage_tags.play_tooltip"))
        self.play_btn.clicked.connect(self._toggle_playback)
        btn_row.addWidget(self.play_btn)

        self.close_btn = QPushButton(tr("manage_tags.close_btn", **self._shortcuts), self)
        self.close_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.close_btn)
        layout.addLayout(btn_row)

        hint = QLabel(tr("manage_tags.hint", **self._shortcuts), self)
        hint.setStyleSheet(styles.HINT)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        if self.main_window is not None:
            self.main_window.video_viewer.player.playbackStateChanged.connect(
                self._refresh_play_btn
            )

    def showEvent(self, event):
        super().showEvent(event)
        self.filter_edit.setFocus()
        self._refresh_play_btn()

    def _row_button(self, icon, tooltip, parent):
        button = QPushButton(parent)
        button.setIcon(icon)
        button.setIconSize(QSize(16, 16))
        button.setFlat(True)
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedSize(24, 24)
        button.setToolTip(tooltip)
        button.setStyleSheet(styles.ICON_BUTTON)
        return button

    # ------------------------------------------------------------------
    # Tag list / selection
    # ------------------------------------------------------------------
    def _entry_text(self, count):
        return tr_plural("manage_tags.entry_count", count)

    def _entry_label(self, name, count):
        return f"{name}  ({self._entry_text(count)})"

    def _reload_tags(self):
        self._counts = self.tags_db.tag_entry_counts()
        # A reload follows a merge or a deletion: keep the source tags that
        # still exist, drop the ones that disappeared.
        self._selected = [name for name in self._selected if name in self._counts]
        self._available_items = {}
        self._available_labels = {}

        self.available_list.blockSignals(True)
        self.available_list.clear()
        for name, count in self._counts.items():
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, name)
            self.available_list.addItem(item)

            row = QWidget(self.available_list)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(6, 1, 2, 1)

            label = _ClickableLabel(self._entry_label(name, count), row)
            label.setStyleSheet(styles.DIALOG)
            label.setCursor(Qt.PointingHandCursor)
            label.setToolTip(tr("manage_tags.add_tooltip"))
            label.clicked.connect(lambda n=name: self._select_and_add(n))
            row_layout.addWidget(label)
            row_layout.addStretch(1)

            search_btn = self._row_button(
                icons.magnifier_icon(), tr("manage_tags.search_tooltip"), row
            )
            search_btn.clicked.connect(lambda _checked=False, n=name: self._goto_tag(n))
            row_layout.addWidget(search_btn)

            delete_btn = self._row_button(
                icons.trash_icon(), tr("manage_tags.delete_tooltip"), row
            )
            delete_btn.clicked.connect(lambda _checked=False, n=name: self._delete_tag(n))
            row_layout.addWidget(delete_btn)

            item.setSizeHint(row.sizeHint())
            self.available_list.setItemWidget(item, row)

            self._available_items[name] = item
            self._available_labels[name] = label
        self.available_list.blockSignals(False)
        self._apply_filter(self.filter_edit.text())
        self._refresh_selected()

    def _apply_filter(self, text):
        """Hide the tags not matching the filter; the current selection is
        not affected by filtering."""
        needle = text.strip().casefold()
        for name, item in self._available_items.items():
            item.setHidden(bool(needle) and needle not in name.casefold())
        self._update_add_btn()

    def _sync_available_marks(self):
        """Mark the tags already in the merge selection with a "✓" (the
        same convention as the assign-tag dialog); clicking such a tag
        again is a harmless no-op."""
        for name, label in self._available_labels.items():
            mark = "\u2713 " if name in self._selected else ""
            label.setText(mark + self._entry_label(name, self._counts.get(name, 0)))

    def _update_add_btn(self):
        item = self.available_list.currentItem()
        self.add_btn.setEnabled(
            item is not None
            and not item.isHidden()
            and item.data(Qt.UserRole) not in self._selected
        )

    def _select_and_add(self, name):
        """Clicking a tag's name in the list selects and adds it."""
        item = self._available_items.get(name)
        if item is not None:
            self.available_list.setCurrentItem(item)
        self._add_source(name)

    def _add_item(self, item):
        """Double-clicking a tag row adds it to the selection."""
        if item is not None and not item.isHidden():
            self._add_source(item.data(Qt.UserRole))

    def _add_current(self):
        """The "Add" button (or Enter on the tag list)."""
        item = self.available_list.currentItem()
        if item is not None and not item.isHidden():
            self._add_source(item.data(Qt.UserRole))

    def _add_source(self, name):
        if name and name not in self._selected:
            self._selected.append(name)
            self._refresh_selected()

    def _remove_source(self, name):
        if name in self._selected:
            self._selected.remove(name)
            self._refresh_selected()

    def _refresh_selected(self):
        """Rebuild the "selected source tags" list (one row per tag, with
        its entry count and a "×" remove button)."""
        self._sync_available_marks()
        self.selected_list.clear()
        for name in self._selected:
            row = QWidget(self.selected_list)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(6, 2, 6, 2)

            label = QLabel(self._entry_label(name, self._counts.get(name, 0)), row)
            label.setStyleSheet(styles.DIALOG)
            row_layout.addWidget(label)
            row_layout.addStretch(1)

            remove_btn = QPushButton("\u00d7", row)   # ×
            remove_btn.setFlat(True)
            remove_btn.setCursor(Qt.PointingHandCursor)
            remove_btn.setStyleSheet(styles.REMOVE_ICON)
            remove_btn.setToolTip(tr("manage_tags.remove_tooltip"))
            remove_btn.clicked.connect(
                lambda _checked=False, n=name: self._remove_source(n)
            )
            row_layout.addWidget(remove_btn)

            item = QListWidgetItem()
            item.setSizeHint(row.sizeHint())
            self.selected_list.addItem(item)
            self.selected_list.setItemWidget(item, row)
        self._update_summary()
        self._update_add_btn()

    def _update_summary(self):
        target = self.tags_db.normalize_tag(self.target_edit.text())
        # The target itself is never a source (merging it into itself would
        # be a no-op), so it is left out of the counts below - and out of
        # the merge itself, see _confirm_merge.
        sources = [name for name in self._selected if name != target]
        if sources:
            entries = sum(self._counts.get(name, 0) for name in sources)
            self.selected_label.setText(tr(
                "manage_tags.selected",
                tags=tr_plural("manage_tags.tag_count", len(sources)),
                entries=self._entry_text(entries),
            ))
        else:
            self.selected_label.setText(tr("manage_tags.selected_none"))

        if not target:
            self.target_label.setText(tr("manage_tags.target_empty"))
        elif target in self._counts:
            self.target_label.setText(tr(
                "manage_tags.target_existing",
                entries=self._entry_text(self._counts[target]),
            ))
        else:
            self.target_label.setText(tr("manage_tags.target_new"))

        # Nothing to do when the target is the only selected source tag.
        if self._selected and target and not sources:
            self.target_label.setText(tr("manage_tags.target_same"))
        self.merge_btn.setEnabled(bool(sources) and bool(target))

    # ------------------------------------------------------------------
    # Magnifier / trash / playback
    # ------------------------------------------------------------------
    def _goto_tag(self, name):
        """Show the next occurrence of `name` behind the window (the window
        itself stays open)."""
        if self.main_window is not None:
            self.main_window.goto_tag_instance(name)
        self._refresh_play_btn()

    def _delete_tag(self, name):
        """Delete the tag (and every entry of it) after confirming."""
        answer = QMessageBox.question(
            self, tr("manage_tags.delete_title"),
            tr(
                "manage_tags.delete_confirm",
                tag=name,
                entries=self._entry_text(self._counts.get(name, 0)),
            ),
            defaultButton=QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            removed = self.tags_db.delete_tag(name)
        except Exception as e:
            # Details were already written to log.txt by the database layer.
            QMessageBox.critical(
                self, tr("common.error_title"),
                tr("manage_tags.delete_error", error=e),
            )
            return

        self.deleted_any = True
        self._selected = [n for n in self._selected if n != name]
        if self.tags_db.normalize_tag(self.target_edit.text()) == name:
            self.target_edit.clear()
        if self.main_window is not None:
            self.main_window.on_tag_deleted(name)
        self._reload_tags()
        QMessageBox.information(
            self, tr("manage_tags.delete_title"),
            tr(
                "manage_tags.delete_done",
                tag=name,
                entries=self._entry_text(removed),
            ),
        )

    def _toggle_playback(self):
        if self.main_window is None:
            return
        self.playback_touched = True
        self.main_window.video_viewer.toggle_pause()
        self._refresh_play_btn()

    def _refresh_play_btn(self, *_args):
        """Enable the Play/Pause button only while a video is shown and
        keep its label in sync with the real playback state."""
        if self.main_window is None:
            self.play_btn.setEnabled(False)
            return
        is_video = self.main_window.current_kind() == "video"
        self.play_btn.setEnabled(is_video)
        if not is_video:
            return
        paused = self.main_window.video_viewer.is_paused()
        self.play_btn.setText(
            tr("manage_tags.play_btn") if paused else tr("manage_tags.pause_btn")
        )

    # ------------------------------------------------------------------
    # Performing the merge
    # ------------------------------------------------------------------
    def _confirm_merge(self):
        target = self.tags_db.normalize_tag(self.target_edit.text())
        sources = [name for name in self._selected if name != target]
        if not sources or not target:
            return

        source_entries = sum(self._counts.get(name, 0) for name in sources)
        target_entries = self._counts.get(target, 0)
        if len(sources) == 1:
            question = tr(
                "manage_tags.confirm_single",
                source_tag=sources[0],
                source_entries=self._entry_text(source_entries),
                target_tag=target,
                target_entries=self._entry_text(target_entries),
            )
        else:
            question = tr(
                "manage_tags.confirm_multi",
                source_count=tr_plural("manage_tags.tag_count", len(sources)),
                entries=self._entry_text(source_entries),
                target_tag=target,
            )

        answer = QMessageBox.question(
            self, tr("manage_tags.confirm_title"), question,
            defaultButton=QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            stats = self.tags_db.merge_tags(sources, target)
        except Exception as e:
            # Details were already written to log.txt by the database layer.
            QMessageBox.critical(
                self, tr("common.error_title"), tr("manage_tags.merge_error", error=e)
            )
            return
        if stats is None:
            return

        self.merged = True
        self.stats = stats
        self._reload_tags()
        QMessageBox.information(
            self, tr("manage_tags.title"),
            tr(
                "manage_tags.merge_done",
                target=stats["target"],
                moved=stats["moved"],
                dropped=stats["dropped"],
                target_entries=self._entry_text(stats["target_entries"]),
            ),
        )

    # ------------------------------------------------------------------
    # Keyboard handling
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent):
            # Enter in the tag list adds the highlighted tag instead of
            # immediately running the merge.
            if obj is self.available_list and event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._add_current()
                return True
            if self._handle_key(event):
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent):
        if self._handle_key(event):
            return
        super().keyPressEvent(event)

    def _handle_key(self, event: QKeyEvent) -> bool:
        if event.key() == Qt.Key_Escape:
            self.reject()
            return True
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._confirm_merge()
            return True
        return False
