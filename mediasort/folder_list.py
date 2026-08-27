"""Shared folder-list browsing (Relative / History / Favourites modes)
used by both the file operation dialog and the browse dialog.

Relative mode lists the subfolders of the PARENT of the dialog's current
folder - i.e. all folders at the same level as the current folder - and
auto-selects the current folder itself.  The "..." entry represents the
folder the user is currently "inside" (selecting it targets that folder);
Enter on "..." moves one level up, Enter on a folder moves into it.

The controller owns a QListWidget and its mode label.  The host dialog
creates those widgets, hands them over together with the Settings
instance, and sets ``on_select`` to a callable that receives the selected
path (used to fill the dialog's location edit).
"""
from pathlib import Path

from PySide6.QtWidgets import QListWidgetItem
from PySide6.QtCore import Qt

from .file_scanner import list_subfolders
from .i18n import tr

PARENT_MARK = "..."

_MODE_DISPLAY_KEYS = {
    "relative": "file_dialog.mode.relative",
    "history": "file_dialog.mode.history",
    "favourites": "file_dialog.mode.favourites",
}


class FolderListController:
    """Owns a folder QListWidget + its mode label and implements the
    three folder modes.  The host dialog supplies:

      * list_widget - the QListWidget to populate
      * mode_label  - the QLabel showing the active mode name
      * settings    - Settings instance (history/favourites/mode)
      * mode_label_key - i18n key used for the "Tryb: ..." label
      * on_select   - callable(path_str) invoked when the user selects a
        row (used to push the path into the dialog's location edit)

    Relative mode state: ``_relative_dir`` is the folder whose subfolders
    are listed; ``_current_dir`` is the folder that should be
    auto-selected (the dialog's current folder, or the folder the user
    last navigated into/out of).
    """

    def __init__(self, list_widget, mode_label, settings,
                 mode_label_key="file_dialog.mode_label"):
        self.list_widget = list_widget
        self.mode_label = mode_label
        self.settings = settings
        self.mode_label_key = mode_label_key
        self.on_select = None

        self.mode = self.settings.get_last_dialog_mode() or "relative"
        self._relative_dir = None
        self._current_dir = None

        self.list_widget.currentItemChanged.connect(self._on_item_changed)
        self.list_widget.itemActivated.connect(lambda _: self.navigate())

    # -- context ---------------------------------------------------------
    def set_context(self, current_folder):
        """Point relative mode at ``current_folder``: the list shows the
        folders inside its parent (i.e. the folders at the same level)
        and auto-selects ``current_folder`` itself."""
        self._current_dir = str(Path(current_folder).resolve())
        self._relative_dir = str(Path(self._current_dir).resolve().parent)

    # -- list population --------------------------------------------------
    def current_folder_list(self):
        """Return list of (display_text, actual_path) tuples for the
        active mode."""
        if self.mode == "relative":
            root = Path(self._relative_dir).resolve()
            items = []
            if root.parent != root:  # not filesystem root
                # '...' represents the folder the user is currently
                # "inside" (the view root) - selecting it targets that
                # folder, Enter on it moves one level up.
                items.append((PARENT_MARK, str(root)))
            for p in list_subfolders(root):
                items.append((Path(p).name, p))
            return items
        elif self.mode == "history":
            hist = self.settings.get_history()
            if not hist:
                hist = [self._current_dir]
            return [(p, p) for p in hist]
        elif self.mode == "favourites":
            return [(p, p) for p in self.settings.get_favourites()]
        return []

    def reload(self, select_path=None, auto_select=True):
        """Repopulate the list.  With ``select_path`` the matching row is
        selected (falling back to the default selection when not found);
        otherwise the row matching the context folder is selected, or the
        first row when the context folder isn't in the list."""
        self.mode_label.setText(tr(self.mode_label_key, mode=self.mode_display_name()))
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for text, path in self.current_folder_list():
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, path)
            if text != PARENT_MARK and self.settings.is_favourite(path):
                item.setText(f"\u2605 {text}")
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)

        selected = False
        if select_path:
            for row in range(self.list_widget.count()):
                if self.list_widget.item(row).data(Qt.UserRole) == select_path:
                    self.list_widget.setCurrentRow(row)
                    selected = True
                    break
        if not selected and auto_select and self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(self._auto_select_row())

    def _auto_select_row(self):
        """Row to select when the list is (re)loaded without an explicit
        selection.  Only in RELATIVE mode is the current folder itself
        preferred (right after descending, that row is the '...' entry,
        which carries the view root's own path).  In History and
        Favourites the current folder is deliberately NOT auto-selected -
        the first row is used instead."""
        if self.mode == "relative":
            for row in range(self.list_widget.count()):
                if self.list_widget.item(row).data(Qt.UserRole) == self._current_dir:
                    return row
        return 0

    def mode_display_name(self):
        return tr(_MODE_DISPLAY_KEYS.get(self.mode, self.mode))

    # -- selection ---------------------------------------------------------
    def _on_item_changed(self, current, _previous):
        # Picking a list row overwrites whatever the location edit holds
        # (the list is authoritative while a row is being selected).  The
        # reverse never happens: manual edits leave the list untouched.
        if current is not None and self.on_select is not None:
            self.on_select(current.data(Qt.UserRole))

    # -- interaction -------------------------------------------------------
    def navigate(self):
        """Enter in relative mode: descend into the selected subfolder or
        ascend one level via '...'.  Returns True when it navigated."""
        item = self.list_widget.currentItem()
        if not item or self.mode != "relative":
            return False
        path = item.data(Qt.UserRole)
        root = Path(self._relative_dir).resolve()
        if path == str(root):  # '...' - one level up
            self._current_dir = self._relative_dir
            self._relative_dir = str(root.parent)
        else:                  # subfolder - move into it
            self._current_dir = path
            self._relative_dir = path
        self.reload()
        return True

    def set_mode(self, mode):
        if mode == self.mode:
            return False
        self.mode = mode
        self.settings.set_last_dialog_mode(mode)
        self.reload()
        return True
