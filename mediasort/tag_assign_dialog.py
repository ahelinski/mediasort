"""Dialog for assigning a tag to the current file or all selected files
(default key: Ctrl+T).

Mirrors the file operation dialog's "keep all existing features" pattern:
a context selector (Zaznaczone/Biezacy plik), invert/select-all actions,
and Zaznaczone/Pozostale preview panels - plus a "Tag" preview panel
showing the first/last file carrying the currently typed/selected tag
and how many instances of it exist.
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLineEdit, QPushButton, QLabel, QGroupBox, QRadioButton, QButtonGroup, QWidget
)
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent, QMouseEvent

from . import styles
from .file_scanner import kind_for_path
from .i18n import tr
from .key_utils import matches_any, shortcut_label
from .selection_preview import SelectionPreviewWidget
from .tags_db import MAX_TAG_LENGTH
from .tag_suggestions import TagSuggestionBox


class TagAssignDialog(QDialog):
    def __init__(self, current_file, settings, tags_db, media_items=None, selected_paths=None, parent=None):
        super().__init__(parent)
        self.current_file = str(current_file)
        self.settings = settings
        self.tags_db = tags_db
        self.media_items = list(media_items) if media_items else [(self.current_file, "image")]
        self.selected_paths = selected_paths if selected_paths is not None else set()
        self.assigned = False  # True once at least one assignment has been made

        self.setWindowTitle(tr("tag_assign.title"))
        self.resize(880, 560)
        self.setStyleSheet(styles.DIALOG)

        # Shortcut labels for the UI texts.  Assign (Enter) and cancel
        # (Esc) are handled directly and are not configurable; invert /
        # select-all follow the configured "file_dialog" bindings.
        fd = self.settings.get("file_dialog", default={})
        self._shortcuts = {
            "enter_key": "Enter",
            "cancel_key": "Esc",
            "invert_key": shortcut_label(fd.get("invert_selection", ["I"])),
            "select_all_key": shortcut_label(fd.get("select_all", ["A"])),
        }

        self._build_ui()
        # Tag autocomplete: existing tags starting with the typed text are
        # suggested after the 2nd character (see tag_suggestions.py).
        self._suggestions = TagSuggestionBox(
            self, self.tag_edit, lambda: self.tags_db.all_tags()
        )
        self._reload_tag_list()
        self._refresh_selection_ui()
        self._refresh_tag_preview()
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = QHBoxLayout(self)
        left = QVBoxLayout()
        outer.addLayout(left, 2)
        self._build_left_panel(left)

        middle = QVBoxLayout()
        outer.addLayout(middle, 2)
        self._build_middle_panel(middle)
        self._reload_tags_count()

        right = QVBoxLayout()
        outer.addLayout(right, 1)
        self._build_selection_panel(right)

    def _build_left_panel(self, layout):
        info = QLabel(tr("tag_assign.current_file", filename=Path(self.current_file).name), self)
        info.setStyleSheet(styles.DIALOG)
        layout.addWidget(info)

        layout.addWidget(QLabel(tr("tag_assign.tag_label"), self))
        self.tag_edit = QLineEdit(self)
        self.tag_edit.setMaxLength(MAX_TAG_LENGTH)
        self.tag_edit.installEventFilter(self)
        self.tag_edit.textChanged.connect(lambda _text: self._refresh_tag_preview())
        layout.addWidget(self.tag_edit)

        layout.addWidget(QLabel(tr("tag_assign.recent_tags_label"), self))
        self.tag_list = QListWidget(self)
        self.tag_list.currentItemChanged.connect(self._on_tag_selected)
        self.tag_list.installEventFilter(self)
        layout.addWidget(self.tag_list)

        btn_row = QHBoxLayout()
        self.assign_btn = QPushButton(tr("tag_assign.assign_btn", **self._shortcuts), self)
        self.assign_btn.setDefault(True)
        self.assign_btn.clicked.connect(self._perform_assign)
        self.cancel_btn = QPushButton(tr("tag_assign.cancel_btn", **self._shortcuts), self)
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.assign_btn)
        btn_row.addWidget(self.cancel_btn)
        layout.addLayout(btn_row)

        hint = QLabel(
            tr("tag_assign.hint", **self._shortcuts),
            self,
        )
        hint.setStyleSheet(styles.HINT)
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def _build_middle_panel(self, layout):
        info = QLabel(tr("tag_assign.selected_count", count=len(self.selected_paths)), self)
        # info.setStyleSheet(styles.DIALOG)
        layout.addWidget(info)

        if len(self.selected_paths) > 0:
            layout.addWidget(QLabel(tr("tag_assign.tags_in_selected"), self))
        else:
            layout.addWidget(QLabel(tr("tag_assign.tags_in_current"), self))
        self.tag_count_list = QListWidget(self)
        # self.tag_count_list.currentItemChanged.connect(self._on_tag_selected)
        self.tag_count_list.installEventFilter(self)
        layout.addWidget(self.tag_count_list)

    def _build_selection_panel(self, layout):
        context_box = QGroupBox(tr("tag_assign.context_group"), self)
        context_layout = QVBoxLayout(context_box)
        self.context_selected_radio = QRadioButton(tr("tag_assign.context_selected"), context_box)
        self.context_current_radio = QRadioButton(tr("tag_assign.context_current"), context_box)
        self.context_selected_radio.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.context_selected_radio)
        group.addButton(self.context_current_radio)
        context_layout.addWidget(self.context_selected_radio)
        context_layout.addWidget(self.context_current_radio)
        layout.addWidget(context_box)

        action_row = QHBoxLayout()
        self.invert_btn = QPushButton(tr("tag_assign.invert_btn", **self._shortcuts), self)
        self.select_all_btn = QPushButton(tr("tag_assign.select_all_btn", **self._shortcuts), self)
        self.invert_btn.clicked.connect(self._invert_selection)
        self.select_all_btn.clicked.connect(self._select_all)
        action_row.addWidget(self.invert_btn)
        action_row.addWidget(self.select_all_btn)
        layout.addLayout(action_row)

        summary_box = QGroupBox(tr("tag_assign.summary_group"), self)
        summary_layout = QVBoxLayout(summary_box)
        self.selected_preview = SelectionPreviewWidget(tr("tag_assign.preview_selected"), summary_box)
        self.remaining_preview = SelectionPreviewWidget(tr("tag_assign.preview_remaining"), summary_box)
        self.tag_preview = SelectionPreviewWidget(tr("tag_assign.preview_tag"), summary_box)
        summary_layout.addWidget(self.selected_preview)
        summary_layout.addWidget(self.remaining_preview)
        summary_layout.addWidget(self.tag_preview)
        layout.addWidget(summary_box)
        layout.addStretch(1)

    def showEvent(self, event):
        super().showEvent(event)
        self.tag_edit.setFocus()

    # ------------------------------------------------------------------
    # Tag list (left)
    # ------------------------------------------------------------------
    def _reload_tag_list(self):
        self.tag_list.blockSignals(True)
        self.tag_list.clear()
        for name in self.tags_db.recent_assigned_tags():
            text = name
            if self.tags_db.file_has_tag(name, self.current_file):
                text = f"{name}   \u2713"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, name)
            self.tag_list.addItem(item)
        self.tag_list.blockSignals(False)

    def _delete_tag(self, key, files):
        self.tags_db.remove_tag_from_files(key, files)
        self._reload_tags_count()

    def _reload_tags_count(self):
        # self.tag_count_list.blockSignals(True)
        self.tag_count_list.clear()
        if len(self.selected_paths) > 0:
            files = self.selected_paths
        else:
            files = [self.current_file]
        tag_counts = self.tags_db.count_tags_for_files(files)

        for key in tag_counts:
            row_widget = QWidget(self.tag_count_list)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(6, 2, 6, 2)

            item = QLabel(f"{key} ({tag_counts[key]})",row_widget)
            # item.setData(Qt.UserRole, name)
            row_layout.addWidget(item)
            row_layout.addStretch(1)

            delete_link = QPushButton(tr("tag_assign.delete_btn"), row_widget)
            delete_link.setFlat(True)
            # delete_link.setCursor(Qt.PointingHandCursor)
            delete_link.setStyleSheet(styles.DEL_LINK)
            delete_link.clicked.connect(lambda _checked=False, n=key: self._delete_tag(key, files))
            row_layout.addWidget(delete_link)
            item = QListWidgetItem()
            item.setSizeHint(row_widget.sizeHint())
            self.tag_count_list.addItem(item)
            self.tag_count_list.setItemWidget(item, row_widget)

        # self.tag_count_list.blockSignals(False)

    def _on_tag_selected(self, current, _previous):
        if current is not None:
            self.tag_edit.setText(current.data(Qt.UserRole))

    def _refresh_tag_preview(self):
        name = self.tags_db.normalize_tag(self.tag_edit.text())
        items = []
        if name:
            image_exts = self.settings.get("image_extensions", default=[])
            video_exts = self.settings.get("video_extensions", default=[])
            for path, _ts in self.tags_db.instances_for_tag(name):
                kind = kind_for_path(path, image_exts, video_exts) or "image"
                items.append((path, kind))
        self.tag_preview.set_items(items)

    # ------------------------------------------------------------------
    # Selection panel (right) - same semantics as the file operation dialog
    # ------------------------------------------------------------------
    def _selected_items(self):
        return [item for item in self.media_items if item[0] in self.selected_paths]

    def _remaining_items(self):
        return [item for item in self.media_items if item[0] not in self.selected_paths]

    def _refresh_selection_ui(self):
        selected_items = self._selected_items()
        remaining_items = self._remaining_items()
        self.selected_preview.set_items(selected_items)
        self.remaining_preview.set_items(remaining_items)
        self.context_selected_radio.setText(tr("tag_assign.context_selected_count", count=len(selected_items)))

    def _invert_selection(self):
        all_paths = {p for p, _k in self.media_items}
        self.selected_paths.symmetric_difference_update(all_paths)
        self._refresh_selection_ui()

    def _select_all(self):
        for p, _k in self.media_items:
            self.selected_paths.add(p)
        self._refresh_selection_ui()

    def _operation_context(self):
        return "selected" if self.context_selected_radio.isChecked() else "current"

    # ------------------------------------------------------------------
    # Assign action
    # ------------------------------------------------------------------
    def _perform_assign(self):
        name = self.tags_db.normalize_tag(self.tag_edit.text())
        if not name:
            return

        context = self._operation_context()
        if context == "selected":
            targets = [p for p, _k in self._selected_items()]
            if not targets:
                targets = [self.current_file]  # nothing selected -> fall back to current file
        else:
            targets = [self.current_file]

        for path in targets:
            self.tags_db.assign_tag(name, path)  # already-tagged files are silently skipped

        self.assigned = True
        self.accept()

    # ------------------------------------------------------------------
    # Keyboard handling
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent):
            if self._handle_key(event, obj):
                return True
        elif event.type() == QEvent.MouseButtonPress and isinstance(event, QMouseEvent):
            if self._handle_key(event, obj):
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent):
        if self._handle_key(event, self.focusWidget()):
            return
        super().keyPressEvent(event)

    def _handle_key(self, event, focused_obj) -> bool:
        if isinstance(event, QKeyEvent) and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._perform_assign()
            return True
        if isinstance(event, QKeyEvent) and event.key() == Qt.Key_Escape:
            self.reject()
            return True

        if focused_obj is not self.tag_edit:
            file_dialog_keys = self.settings.get("file_dialog", default={})
            if matches_any(event, file_dialog_keys.get("invert_selection", ["I"])):
                self._invert_selection()
                return True
            if matches_any(event, file_dialog_keys.get("select_all", ["A"])):
                self._select_all()
                return True

        return False
