"""File operation (copy/move) dialog.

Left side: shows a list of candidate destination folders in one of three
modes - Relative (subfolders of the current file's folder), History
(recently used destinations) or Favourites (user-pinned folders). The
user can navigate the list with arrow keys, edit the destination path
directly, and confirm with Copy / Move (or the Enter key, which triggers
whichever action the dialog was opened for).

Right side: a multi-file selection panel. The user picks whether the
operation should apply to the "Zaznaczone" (selected) files or just the
"Biezacy plik" (current file), can invert the selection or select all
files in the folder, and sees a small thumbnail summary of both the
selected and the remaining files.
"""
import shutil
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLineEdit, QPushButton, QLabel, QMessageBox, QGroupBox, QRadioButton,
    QButtonGroup
)
from PySide6.QtCore import Qt, QEvent, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent

from .key_utils import matches_any
from .file_scanner import list_subfolders, scan_media
from .selection_preview import SelectionPreviewWidget
from .style import STYLE

PARENT_MARK = "..."


class ClickableLabel(QLabel):
    """A QLabel that emits `clicked` on a left mouse click."""
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class FileOperationDialog(QDialog):
    def __init__(
        self, current_file, settings, default_action="copy",
        media_items=None, selected_paths=None, tags_db=None, parent=None,
    ):
        super().__init__(parent)
        self.current_file = str(current_file)
        self.settings = settings
        self.tags_db = tags_db  # optional - if given, tags follow moved files
        self.default_action = default_action  # "copy" or "move"
        self.performed_action = None   # set to "copy"/"move" once an operation succeeds
        self.affected_paths = []       # paths actually copied/moved

        # media_items: list of (path, kind) tuples for the whole current folder.
        # selected_paths: a *mutable set* shared with MainWindow - mutations
        # here (invert/select-all) are immediately visible to the caller.
        self.media_items = list(media_items) if media_items else [(self.current_file, "image")]
        self.selected_paths = selected_paths if selected_paths is not None else set()

        titles = {"copy": "Kopiuj plik", "move": "Przenies plik"}
        self.setWindowTitle(titles.get(default_action, "Operacja na pliku"))
        self.resize(880, 560)
        # Setting a stylesheet on any single label (even just font-weight)
        # can make Qt stop inheriting the system palette for that widget
        # and fall back to black text, which becomes invisible on a dark
        # OS theme. Give the whole dialog an explicit, theme-independent
        # dark style so every label stays readable regardless of the
        # system palette.
        self.setStyleSheet(STYLE)

        self.mode = self.settings.get_last_dialog_mode() or "relative"
        # Directory currently being browsed in "relative" mode.
        self._relative_dir = str(Path(self.current_file).resolve().parent)

        self._build_ui()
        self._reload_list()
        self._refresh_selection_ui()
        if self.list_widget.currentItem() is None:
            # _reload_list() already triggers _refresh_folder_preview() via
            # the selection-changed signal when the list is non-empty; this
            # covers the edge case where the list has no items at all.
            self._refresh_folder_preview()

    def create(self, /, arg__1: int | None = ..., initializeWindow: bool = ..., destroyOldWindow: bool = ...) -> None:
        super().create(arg__1, initializeWindow, destroyOldWindow)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QHBoxLayout(self)

        left = QVBoxLayout()
        outer.addLayout(left, 2)
        self._build_left_panel(left)

        right = QVBoxLayout()
        outer.addLayout(right, 1)
        self._build_selection_panel(right)

    def _build_left_panel(self, layout):
        info = QLabel(f"Plik: {Path(self.current_file).name}", self)
        info.setStyleSheet(STYLE)
        layout.addWidget(info)

        self.mode_label = QLabel(self)
        layout.addWidget(self.mode_label)

        # Destination display: normally mirrors the selected list item; a
        # click or F2 turns it into an editable field for a custom path.
        self.location_label = ClickableLabel(self)
        self.location_label.setStyleSheet(
            STYLE
        )
        self.location_label.setToolTip("Kliknij lub nacisnij F2, aby recznie edytowac lokalizacje")
        self.location_label.clicked.connect(self._begin_edit_location)
        layout.addWidget(self.location_label)

        self.location_edit = QLineEdit(self)
        self.location_edit.installEventFilter(self)
        # Let QLineEdit handle Return itself and react to its dedicated
        # signal.  This is more reliable than relying on the dialog-level
        # event filter: Return can otherwise be consumed by the focused
        # line edit before it reaches the dialog.
        self.location_edit.returnPressed.connect(self._perform_edited_location)
        self.location_edit.hide()
        layout.addWidget(self.location_edit)

        self.list_widget = QListWidget(self)
        self.list_widget.currentItemChanged.connect(self._on_selection_changed)
        self.list_widget.itemActivated.connect(lambda _: self._navigate_or_select())
        self.list_widget.installEventFilter(self)
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        self.copy_btn = QPushButton("Kopiuj (C)", self)
        self.move_btn = QPushButton("Przenies (M)", self)
        self.fav_btn = QPushButton("Ulubione +/-", self)
        self.copy_btn.clicked.connect(lambda: self._perform("copy"))
        self.move_btn.clicked.connect(lambda: self._perform("move"))
        self.fav_btn.clicked.connect(self._toggle_favourite_current)
        default_buttons = {"copy": self.copy_btn, "move": self.move_btn}
        default_buttons.get(self.default_action, self.copy_btn).setDefault(True)
        btn_row.addWidget(self.copy_btn)
        btn_row.addWidget(self.move_btn)
        btn_row.addWidget(self.fav_btn)
        layout.addLayout(btn_row)

        hint = QLabel(
            "R: widok wzgledny  H: historia  F: ulubione  |  "
            "F2 / klik na lokalizacji: recznie edytuj sciezke  |  "
            "Enter: nawiguj folder (w trybie wzglednym) / akcja domyslna  |  "
            "Ctrl+Enter: wykonaj akcje domyslna  |  "
            "Alt+C: kopiuj  Alt+M: przenies  |  "
            "Ctrl+D: ulubione  Esc: anuluj",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(hint)

    def _build_selection_panel(self, layout):
        context_box = QGroupBox("Kontekst operacji", self)
        context_layout = QVBoxLayout(context_box)
        self.context_selected_radio = QRadioButton("Zaznaczone", context_box)
        self.context_current_radio = QRadioButton("Biezacy plik", context_box)
        self.context_selected_radio.setChecked(True)  # default per spec
        group = QButtonGroup(self)
        group.addButton(self.context_selected_radio)
        group.addButton(self.context_current_radio)
        context_layout.addWidget(self.context_selected_radio)
        context_layout.addWidget(self.context_current_radio)
        layout.addWidget(context_box)

        action_row = QHBoxLayout()
        self.invert_btn = QPushButton("Odwroc zaznaczenie (i)", self)
        self.select_all_btn = QPushButton("Zaznacz wszystkie (a)", self)
        self.invert_btn.clicked.connect(self._invert_selection)
        self.select_all_btn.clicked.connect(self._select_all)
        action_row.addWidget(self.invert_btn)
        action_row.addWidget(self.select_all_btn)
        layout.addLayout(action_row)

        summary_box = QGroupBox("Podsumowanie zaznaczenia", self)
        summary_layout = QVBoxLayout(summary_box)
        self.selected_preview = SelectionPreviewWidget("Zaznaczone", summary_box)
        self.remaining_preview = SelectionPreviewWidget("Pozostale", summary_box)
        self.folder_preview = SelectionPreviewWidget("Folder", summary_box)
        summary_layout.addWidget(self.selected_preview)
        summary_layout.addWidget(self.remaining_preview)
        summary_layout.addWidget(self.folder_preview)
        layout.addWidget(summary_box)

        layout.addStretch(1)

    def showEvent(self, event):
        super().showEvent(event)
        self.list_widget.setFocus()

    # ------------------------------------------------------------------
    # Destination folder list population (Relative / History / Favourites)
    # ------------------------------------------------------------------
    def _current_folder_list(self):
        """Return list of (display_text, actual_path) tuples for the active mode."""
        if self.mode == "relative":
            root = Path(self._relative_dir).resolve()
            items = []
            if root.parent != root:  # not filesystem root
                items.append((PARENT_MARK, str(root.parent)))
            for p in list_subfolders(root):
                items.append((Path(p).name, p))
            return items
        elif self.mode == "history":
            hist = self.settings.get_history()
            if not hist:
                hist = [str(Path(self.current_file).resolve().parent)]
            return [(p, p) for p in hist]
        elif self.mode == "favourites":
            return [(p, p) for p in self.settings.get_favourites()]
        return []

    def _reload_list(self, select_path=None):
        self.mode_label.setText(f"Tryb: {self._mode_display_name()}")
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        entries = self._current_folder_list()
        for text, path in entries:
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, path)
            if text != PARENT_MARK and self.settings.is_favourite(path):
                item.setText(f"\u2605 {text}")
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)

        target_row = 0
        if select_path:
            for row in range(self.list_widget.count()):
                if self.list_widget.item(row).data(Qt.UserRole) == select_path:
                    target_row = row
                    break
        elif self.mode == "favourites":
            last_used = self.settings.get_last_used_location()
            if last_used:
                for row in range(self.list_widget.count()):
                    if self.list_widget.item(row).data(Qt.UserRole) == last_used:
                        target_row = row
                        break

        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(target_row)
        else:
            self.location_label.clear()

    def _mode_display_name(self):
        return {
            "relative": "Wzgledny",
            "history": "Historia",
            "favourites": "Ulubione",
        }.get(self.mode, self.mode)

    # ------------------------------------------------------------------
    # Destination list selection / navigation
    # ------------------------------------------------------------------
    def _on_selection_changed(self, current, _previous):
        if current is not None:
            self.location_label.setText(current.data(Qt.UserRole))
        self._refresh_folder_preview()

    def _navigate_or_select(self):
        """In relative mode, descend into (or ascend out of, via '...')
        the currently selected folder. This is what lets the user go back
        into a subfolder after having gone up with '...' - previously
        Enter only handled the '...' case and otherwise performed the
        copy/move action, making it impossible to descend again."""
        item = self.list_widget.currentItem()
        if not item or self.mode != "relative":
            return
        path = item.data(Qt.UserRole)
        self._relative_dir = path
        self._reload_list()

    def _set_mode(self, mode):
        if mode == self.mode:
            return
        self.mode = mode
        self.settings.set_last_dialog_mode(mode)
        self._reload_list()

    def _selected_path(self):
        return self.location_label.text().strip()

    def _destination_path(self):
        """Return the path the operation must use right now.

        A default dialog button may be activated by Return before Qt has
        finished committing the active QLineEdit.  In that case the typed
        value is authoritative; the selected row is only a browsing aid.
        """
        if not self.location_edit.isHidden():
            return self.location_edit.text().strip()
        return self._selected_path()

    # -- custom location editing (F2 / click on the label) ---------------
    def _begin_edit_location(self):
        self.location_edit.setText(self.location_label.text().strip())
        self.location_label.hide()
        self.location_edit.show()
        self.location_edit.setFocus()

    def _confirm_edit_location(self):
        self.location_label.setText(self.location_edit.text().strip())
        self._end_edit_location()
        self._refresh_folder_preview()

    def _perform_edited_location(self):
        """Use the typed path as the destination and run the default action."""
        if self.location_edit.isHidden():
            return
        self._confirm_edit_location()
        self._perform_default_action()

    def _cancel_edit_location(self):
        self._end_edit_location()

    def _end_edit_location(self):
        # self.location_edit.hide()
        # self.location_label.show()
        self.list_widget.setFocus()

    # -- "Folder" preview: contents of the currently selected/edited
    # destination location --------------------------------------------
    def _refresh_folder_preview(self):
        path_str = self._selected_path()
        items = []
        if path_str:
            folder = Path(path_str)
            if folder.exists() and folder.is_dir():
                image_exts = self.settings.get("image_extensions", default=[])
                video_exts = self.settings.get("video_extensions", default=[])
                items = scan_media(str(folder), image_exts, video_exts)
        self.folder_preview.set_items(items)

    def _toggle_favourite_current(self):
        path = self._selected_path()
        if not path:
            return
        if self.settings.is_favourite(path):
            self.settings.remove_favourite(path)
        else:
            self.settings.add_favourite(path)
        self._reload_list(select_path=path)

    # ------------------------------------------------------------------
    # Multi-file selection panel
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
        self.context_selected_radio.setText(f"Zaznaczone ({len(selected_items)})")
        self.context_current_radio.setText("Biezacy plik")

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
    # Copy / Move
    # ------------------------------------------------------------------
    def _perform(self, action):
        context = self._operation_context()
        if context == "selected":
            paths_to_process = [p for p, _k in self._selected_items()]
            if not paths_to_process:
                # Nothing is selected - fall back to the current file
                # instead of blocking the user with an error.
                paths_to_process = [self.current_file]
        else:
            paths_to_process = [self.current_file]

        destination_folder = self._destination_path()
        if not destination_folder:
            QMessageBox.warning(self, "Blad", "Nie wybrano lokalizacji docelowej.")
            return

        try:
            dest_path = Path(destination_folder)
        except (OSError, ValueError) as e:
            QMessageBox.critical(self, "Nieprawidlowa sciezka", f"Podana sciezka jest nieprawidlowa: {e}")
            return

        if dest_path.exists() and not dest_path.is_dir():
            QMessageBox.critical(
                self, "Nieprawidlowa sciezka",
                "Wybrana lokalizacja istnieje, ale nie jest folderem.",
            )
            return

        if not dest_path.exists():
            self.blockSignals(True)
            answer = QMessageBox.question(
                self, "Utworzyc folder?",
                f"Folder '{destination_folder}' nie istnieje. Czy utworzyc?",
                defaultButton=QMessageBox.StandardButton.Yes
            )

            if answer != QMessageBox.Yes:
                return
            try:
                dest_path.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                QMessageBox.critical(self, "Nieprawidlowa sciezka", f"Nie mozna utworzyc folderu: {e}")
                return
            self.blockSignals(False)

        succeeded = []
        succeeded_targets = {}  # src_str -> target_str, only for action == "move"
        errors = []
        for src_str in paths_to_process:
            src = Path(src_str)
            try:
                target = dest_path / src.name
                if action == "copy":
                    shutil.copy2(str(src), str(target))
                else:
                    shutil.move(str(src), str(target))
                    succeeded_targets[src_str] = str(target)
                succeeded.append(src_str)
            except OSError as e:
                errors.append((src_str, str(e)))

        if errors:
            details = "\n".join(f"{Path(p).name}: {err}" for p, err in errors)
            QMessageBox.warning(self, "Niektore operacje nie powiodly sie", details)

        if not succeeded:
            return  # nothing worked, keep the dialog open

        self.settings.add_history(destination_folder)
        self.settings.set_last_used_location(destination_folder)
        self.performed_action = action
        self.affected_paths = succeeded

        if action == "move" and self.tags_db is not None:
            # Tags follow the file to its new location instead of being
            # orphaned (left pointing at a path that no longer exists).
            for src_str, target_str in succeeded_targets.items():
                self.tags_db.retarget_file(src_str, target_str)

        if action == "move":
            # Moved files no longer exist in this folder - drop them from
            # the (shared) selection set as well.
            for p in succeeded:
                self.selected_paths.discard(p)

        self.accept()

    def _perform_default_action(self):
        """Run whichever action (copy/move) this dialog was opened for."""
        self._perform(self.default_action)

    # ------------------------------------------------------------------
    # Configurable keyboard / mouse handling
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent):
            if self._handle_dialog_key(event, obj):
                return True
        elif event.type() == QEvent.MouseButtonPress and isinstance(event, QMouseEvent):
            if self._handle_dialog_key(event, obj):
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent):
        if self._handle_dialog_key(event, self.focusWidget()):
            return
        super().keyPressEvent(event)

    def _handle_dialog_key(self, event, focused_obj) -> bool:
        file_dialog_keys = self.settings.get("file_dialog", default={})

        # While actively editing a custom location, let QLineEdit process
        # Enter and emit returnPressed. Escape remains dialog-specific;
        # every other key is regular text input.
        if not self.location_edit.isHidden() and focused_obj is self.location_edit:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._confirm_edit_location()
                return True
            if matches_any(event, file_dialog_keys.get("cancel", ["Escape"])):
                self._cancel_edit_location()
                return True
            return False

        # Ctrl+Enter always performs the dialog's configured action
        # (copy/move/open), regardless of mode - this is the escape hatch
        # for relative mode, where plain Enter now navigates instead.
        if matches_any(event, file_dialog_keys.get("confirm_action", ["Ctrl+Return"])):
            self._perform_default_action()
            return True

        if matches_any(event, file_dialog_keys.get("edit_location", ["F2"])):
            self._begin_edit_location()
            return True
        if matches_any(event, file_dialog_keys.get("copy", ["Alt+C"])):
            self._perform("copy")
            return True
        if matches_any(event, file_dialog_keys.get("move", ["Alt+M"])):
            self._perform("move")
            return True
        if matches_any(event, file_dialog_keys.get("toggle_favourite", ["Ctrl+D"])):
            self._toggle_favourite_current()
            return True
        if matches_any(event, file_dialog_keys.get("cancel", ["Escape"])):
            self.reject()
            return True
        if matches_any(event, file_dialog_keys.get("mode_relative", ["R"])):
            self._set_mode("relative")
            return True
        if matches_any(event, file_dialog_keys.get("mode_history", ["H"])):
            self._set_mode("history")
            return True
        if matches_any(event, file_dialog_keys.get("mode_favourites", ["F"])):
            self._set_mode("favourites")
            return True
        if matches_any(event, file_dialog_keys.get("invert_selection", ["I"])):
            self._invert_selection()
            return True
        if matches_any(event, file_dialog_keys.get("select_all", ["A"])):
            self._select_all()
            return True

        if isinstance(event, QKeyEvent) and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self.mode == "relative":
                # Descend into (or ascend out of, via '...') the selected
                # folder instead of performing the copy/move/open action -
                # this is what lets the user go back down after using
                # '...' to go up.
                self._navigate_or_select()
            else:
                self._perform_default_action()
            return True

        return False
