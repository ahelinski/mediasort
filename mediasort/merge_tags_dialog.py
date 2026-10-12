"""Merge / Rename tags dialog, opened from the database management window.

The user builds the set of "source" tags explicitly: the list of available
tags (each shown together with its number of entries) is on the left, the
chosen source tags are on the right - a tag is added with the "Add" button
or a double-click, and removed again with the "×" button next to it. The
target tag is typed in: an existing tag picked from the autocomplete, or
a brand-new name.

After a confirmation (worded differently for a rename of one tag and a
merge of several) every entry of the source tags is moved to the target
tag and the source tags are deleted; see ``TagsDatabase.merge_tags`` for
the exact rules (duplicates on the target are dropped, timestamps are
preserved).
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLineEdit, QPushButton, QLabel, QGroupBox, QMessageBox, QWidget
)
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent

from .i18n import tr, tr_plural
from . import styles
from .tags_db import MAX_TAG_LENGTH
from .tag_suggestions import TagSuggestionBox


class MergeTagsDialog(QDialog):
    def __init__(self, tags_db, parent=None):
        super().__init__(parent)
        self.tags_db = tags_db
        self.merged = False   # True once at least one merge was performed
        self.stats = None     # stats of the last merge (see merge_tags)

        # Source tags chosen by the user (in the order they were added) and
        # the entry count of every tag, refreshed on each reload.
        self._selected = []
        self._counts = {}

        self.setWindowTitle(tr("db_manage.merge_title"))
        self.resize(720, 520)
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
    def _build_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel(tr("db_manage.merge_info"), self)
        info.setWordWrap(True)
        layout.addWidget(info)

        sources_box = QGroupBox(tr("db_manage.merge_sources_group"), self)
        sources_layout = QVBoxLayout(sources_box)

        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText(tr("db_manage.merge_filter_placeholder"))
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.filter_edit.installEventFilter(self)
        sources_layout.addWidget(self.filter_edit)

        lists_row = QHBoxLayout()

        available_col = QVBoxLayout()
        available_col.addWidget(QLabel(tr("db_manage.merge_available_label"), self))
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
        self.add_btn = QPushButton(tr("db_manage.merge_add_btn"), self)
        self.add_btn.clicked.connect(self._add_current)
        add_col.addWidget(self.add_btn)
        add_col.addStretch(1)
        lists_row.addLayout(add_col)

        selected_col = QVBoxLayout()
        selected_col.addWidget(QLabel(tr("db_manage.merge_selected_label"), self))
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

        target_box = QGroupBox(tr("db_manage.merge_target_group"), self)
        target_layout = QVBoxLayout(target_box)
        self.target_edit = QLineEdit(self)
        self.target_edit.setMaxLength(MAX_TAG_LENGTH)
        self.target_edit.setPlaceholderText(tr("db_manage.merge_target_placeholder"))
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
        self.merge_btn = QPushButton(tr("db_manage.merge_apply_btn", **self._shortcuts), self)
        self.merge_btn.setDefault(True)
        self.merge_btn.clicked.connect(self._confirm_merge)
        btn_row.addWidget(self.merge_btn)
        self.cancel_btn = QPushButton(tr("db_manage.merge_cancel_btn", **self._shortcuts), self)
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)
        layout.addLayout(btn_row)

        hint = QLabel(tr("db_manage.merge_hint", **self._shortcuts), self)
        hint.setStyleSheet(styles.HINT)
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def showEvent(self, event):
        super().showEvent(event)
        self.filter_edit.setFocus()

    # ------------------------------------------------------------------
    # Tag list / selection
    # ------------------------------------------------------------------
    def _entry_text(self, count):
        return tr_plural("db_manage.tag_entry_count", count)

    def _reload_tags(self):
        self._counts = self.tags_db.tag_entry_counts()
        # A reload follows a merge, which deletes the source tags - so the
        # previous selection is not meaningful any more.
        self._selected = []
        self.available_list.blockSignals(True)
        self.available_list.clear()
        for name, count in self._counts.items():
            item = QListWidgetItem(f"{name}  ({self._entry_text(count)})")
            item.setData(Qt.UserRole, name)
            self.available_list.addItem(item)
        self.available_list.blockSignals(False)
        self._apply_filter(self.filter_edit.text())
        self._refresh_selected()

    def _apply_filter(self, text):
        """Hide the tags not matching the filter; the current selection is
        not affected by filtering."""
        needle = text.strip().casefold()
        for i in range(self.available_list.count()):
            item = self.available_list.item(i)
            hidden = bool(needle) and needle not in item.data(Qt.UserRole).casefold()
            item.setHidden(hidden)
        self._update_add_btn()

    def _sync_available_marks(self):
        """Mark the tags that are already in the selection with a "✓" (the
        same convention as the assign-tag dialog), so it is clear which
        ones were added; clicking such a tag again is a harmless no-op."""
        for i in range(self.available_list.count()):
            item = self.available_list.item(i)
            name = item.data(Qt.UserRole)
            mark = "\u2713 " if name in self._selected else ""
            item.setText(f"{mark}{name}  ({self._entry_text(self._counts.get(name, 0))})")

    def _update_add_btn(self):
        item = self.available_list.currentItem()
        self.add_btn.setEnabled(
            item is not None
            and not item.isHidden()
            and item.data(Qt.UserRole) not in self._selected
        )

    def _add_item(self, item):
        """Double-click on an available tag adds it to the selection."""
        if item is not None and not item.isHidden():
            self._add_source(item.data(Qt.UserRole))

    def _add_current(self):
        """The "Add" button (or Enter on the available list)."""
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

            label = QLabel(
                f"{name}  ({self._entry_text(self._counts.get(name, 0))})", row
            )
            label.setStyleSheet(styles.DIALOG)
            row_layout.addWidget(label)
            row_layout.addStretch(1)

            remove_btn = QPushButton("\u00d7", row)   # ×
            remove_btn.setFlat(True)
            remove_btn.setCursor(Qt.PointingHandCursor)
            remove_btn.setStyleSheet(styles.REMOVE_ICON)
            remove_btn.setToolTip(tr("db_manage.merge_remove_tooltip"))
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
                "db_manage.merge_selected",
                tags=tr_plural("db_manage.tag_count", len(sources)),
                entries=self._entry_text(entries),
            ))
        else:
            self.selected_label.setText(tr("db_manage.merge_selected_none"))

        if not target:
            self.target_label.setText(tr("db_manage.merge_target_empty"))
        elif target in self._counts:
            self.target_label.setText(tr(
                "db_manage.merge_target_existing",
                entries=self._entry_text(self._counts[target]),
            ))
        else:
            self.target_label.setText(tr("db_manage.merge_target_new"))

        # Nothing to do when the target is the only selected source tag.
        if self._selected and target and not sources:
            self.target_label.setText(tr("db_manage.merge_target_same"))
        self.merge_btn.setEnabled(bool(sources) and bool(target))

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
                "db_manage.merge_confirm_single",
                source_tag=sources[0],
                source_entries=self._entry_text(source_entries),
                target_tag=target,
                target_entries=self._entry_text(target_entries),
            )
        else:
            question = tr(
                "db_manage.merge_confirm_multi",
                source_count=tr_plural("db_manage.tag_count", len(sources)),
                entries=self._entry_text(source_entries),
                target_tag=target,
            )

        answer = QMessageBox.question(
            self, tr("db_manage.merge_confirm_title"), question,
            defaultButton=QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            stats = self.tags_db.merge_tags(sources, target)
        except Exception as e:
            # Details were already written to log.txt by the database layer.
            QMessageBox.critical(
                self, tr("common.error_title"), tr("db_manage.merge_error", error=e)
            )
            return
        if stats is None:
            return

        self.merged = True
        self.stats = stats
        self._reload_tags()
        QMessageBox.information(
            self, tr("db_manage.merge_title"),
            tr(
                "db_manage.merge_done",
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
            # Enter in the available list adds the highlighted tag instead
            # of immediately running the merge.
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
