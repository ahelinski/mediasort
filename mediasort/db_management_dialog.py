"""Database management dialog (default key: F10).

Shows a summary of the tags database (number of assignments / entries,
distinct files, distinct tags) and offers four maintenance operations:

  * Compact - scan every file path in the database and delete the linked
    entries when the file no longer exists on disk (orphaned tags left
    without any assignments are dropped as well).  Paths that cannot be
    checked because access is denied are presented to the user, who may
    keep, delete, delete all remaining inaccessible entries, or abort.
  * Export to CSV - write every assignment as (tag, timestamp, path)
    rows without internal ids; a whole-file tag has an empty timestamp.
  * Import from CSV - append assignments from the same format, skipping
    rows that duplicate an existing assignment (same tag, same file, and
    the same timestamp when one is given).
  * Export folder - write every tag entry of the files inside a chosen
    folder (and its subfolders) to a JSON file *inside* that folder, with
    relative paths, so the whole folder can be moved elsewhere.
  * Import folder - read that file back after the move and recreate the
    entries for the new absolute paths (both Windows and Linux path
    separators are accepted).

Tag maintenance lives in its own windows: "Manage All Tags" (F9, see
manage_tags_dialog.py) and "Manage File Tags" (T).

Errors from any of the operations are shown in a message box and their
details (with the full stack trace) are appended to log.txt in the
application folder.
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox,
    QMessageBox, QFileDialog
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

from .i18n import tr
from . import styles
from .app_log import log_exception
from .folder_export import (
    EXPORT_FILE_NAME, export_folder, import_folder,
)


class DbManagementDialog(QDialog):
    def __init__(self, tags_db, parent=None):
        super().__init__(parent)
        self.tags_db = tags_db

        self.setWindowTitle(tr("db_manage.title"))
        self.resize(520, 360)
        self.setStyleSheet(styles.DIALOG)

        self._build_ui()
        self._refresh_stats()

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)

        stats_box = QGroupBox(tr("db_manage.statistics_group"), self)
        stats_layout = QVBoxLayout(stats_box)
        self.entries_label = QLabel(self)
        self.files_label = QLabel(self)
        self.tags_label = QLabel(self)
        stats_layout.addWidget(self.entries_label)
        stats_layout.addWidget(self.files_label)
        stats_layout.addWidget(self.tags_label)
        layout.addWidget(stats_box)

        ops_box = QGroupBox(tr("db_manage.operations_group"), self)
        ops_layout = QVBoxLayout(ops_box)
        self.compact_btn = QPushButton(tr("db_manage.compact_btn"), self)
        self.export_btn = QPushButton(tr("db_manage.export_btn"), self)
        self.import_btn = QPushButton(tr("db_manage.import_btn"), self)
        self.folder_export_btn = QPushButton(tr("db_manage.folder_export_btn"), self)
        self.folder_import_btn = QPushButton(tr("db_manage.folder_import_btn"), self)
        self.folder_export_btn.setToolTip(tr("db_manage.folder_export_tooltip"))
        self.folder_import_btn.setToolTip(tr("db_manage.folder_import_tooltip"))
        self.compact_btn.clicked.connect(self._compact)
        self.export_btn.clicked.connect(self._export)
        self.import_btn.clicked.connect(self._import_csv)
        self.folder_export_btn.clicked.connect(self._export_folder)
        self.folder_import_btn.clicked.connect(self._import_folder)
        ops_layout.addWidget(self.compact_btn)
        ops_layout.addWidget(self.export_btn)
        ops_layout.addWidget(self.import_btn)
        ops_layout.addWidget(self.folder_export_btn)
        ops_layout.addWidget(self.folder_import_btn)
        layout.addWidget(ops_box)

        btn_row = QHBoxLayout()
        self.close_btn = QPushButton(tr("db_manage.close_btn", cancel_key="Esc"), self)
        self.close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.close_btn)
        layout.addLayout(btn_row)

        layout.addStretch(1)

    # ------------------------------------------------------------------
    def _refresh_stats(self):
        stats = self.tags_db.db_stats()
        self.entries_label.setText(tr("db_manage.stats_entries", count=stats["entries"]))
        self.files_label.setText(tr("db_manage.stats_files", count=stats["files"]))
        self.tags_label.setText(tr("db_manage.stats_tags", count=stats["tags"]))

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------
    def _resolve_inaccessible(self, path):
        """Ask the user what to do with a stored path that cannot be
        checked (no access to the file or folder).  Returns one of
        "keep", "delete", "delete_all" or "abort" for TagsDatabase.compact."""
        box = QMessageBox(self)
        box.setWindowTitle(tr("db_manage.inaccessible_title"))
        box.setText(tr("db_manage.inaccessible_ask", path=path))
        no_btn = box.addButton(tr("db_manage.inaccessible_no"), QMessageBox.ButtonRole.RejectRole)
        yes_btn = box.addButton(tr("db_manage.inaccessible_yes"), QMessageBox.ButtonRole.AcceptRole)
        all_btn = box.addButton(tr("db_manage.inaccessible_all"), QMessageBox.ButtonRole.AcceptRole)
        abort_btn = box.addButton(tr("db_manage.inaccessible_abort"), QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(no_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is yes_btn:
            return "delete"
        if clicked is all_btn:
            return "delete_all"
        if clicked is abort_btn:
            return "abort"
        return "keep"  # "Nie" or the dialog was closed without a choice

    def _compact(self):
        answer = QMessageBox.question(
            self, tr("db_manage.compact_title"), tr("db_manage.compact_ask"),
            defaultButton=QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            removed_files, removed_entries, removed_tags, aborted = self.tags_db.compact(
                resolve_inaccessible=self._resolve_inaccessible
            )
        except Exception as e:
            # Details were already written to log.txt by the database layer.
            QMessageBox.critical(
                self, tr("common.error_title"), tr("db_manage.compact_error", error=e)
            )
            return
        self._refresh_stats()
        if aborted:
            QMessageBox.information(self, tr("db_manage.compact_title"), tr("db_manage.compact_aborted"))
            return
        QMessageBox.information(
            self, tr("db_manage.compact_title"),
            tr(
                "db_manage.compact_done",
                files=removed_files, entries=removed_entries, tags=removed_tags,
            ),
        )

    def _export(self):
        path, _selected_filter = QFileDialog.getSaveFileName(
            self, tr("db_manage.export_title"), "", tr("db_manage.csv_filter")
        )
        if not path:
            return
        try:
            count = self.tags_db.export_csv(path)
        except Exception as e:
            # Details were already written to log.txt by the database layer.
            QMessageBox.critical(
                self, tr("common.error_title"), tr("db_manage.export_error", error=e)
            )
            return
        QMessageBox.information(
            self, tr("db_manage.export_title"),
            tr("db_manage.export_done", count=count, path=path),
        )

    def _import_csv(self):
        path, _selected_filter = QFileDialog.getOpenFileName(
            self, tr("db_manage.import_title"), "", tr("db_manage.csv_filter")
        )
        if not path:
            return
        try:
            added, skipped = self.tags_db.import_csv(path)
        except Exception as e:
            # Details were already written to log.txt by the database layer.
            QMessageBox.critical(
                self, tr("common.error_title"), tr("db_manage.import_error", error=e)
            )
            return
        self._refresh_stats()
        QMessageBox.information(
            self, tr("db_manage.import_title"),
            tr("db_manage.import_done", added=added, skipped=skipped),
        )

    # ------------------------------------------------------------------
    # Folder export / import (moving a whole folder without losing tags)
    # ------------------------------------------------------------------
    def _initial_folder(self):
        """Starting folder for the folder pickers: the main window's current
        folder, so exporting the folder being browsed is a single click."""
        parent = self.parent()
        folder = getattr(parent, "folder", "") if parent is not None else ""
        return folder or str(Path.home())

    def _export_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, tr("db_manage.folder_export_title"), self._initial_folder()
        )
        if not folder:
            return
        try:
            stats = export_folder(self.tags_db, folder)
        except Exception as e:                      # noqa: BLE001
            log_exception("export_folder", e)
            QMessageBox.critical(
                self, tr("common.error_title"),
                tr("db_manage.folder_export_error", error=e),
            )
            return
        QMessageBox.information(
            self, tr("db_manage.folder_export_title"),
            tr("db_manage.folder_export_done", files=stats["files"],
               entries=stats["entries"], path=stats["path"]),
        )

    def _import_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, tr("db_manage.folder_import_title"), self._initial_folder()
        )
        if not folder:
            return
        try:
            stats = import_folder(self.tags_db, folder)
        except FileNotFoundError:
            QMessageBox.warning(
                self, tr("db_manage.folder_import_title"),
                tr("db_manage.folder_import_no_file", name=EXPORT_FILE_NAME),
            )
            return
        except ValueError as e:
            QMessageBox.warning(
                self, tr("db_manage.folder_import_title"),
                tr("db_manage.folder_import_bad_file", error=e),
            )
            return
        except Exception as e:                      # noqa: BLE001
            log_exception("import_folder", e)
            QMessageBox.critical(
                self, tr("common.error_title"),
                tr("db_manage.folder_import_error", error=e),
            )
            return
        self._refresh_stats()
        message = tr("db_manage.folder_import_done", files=stats["files"],
                     added=stats["added"], skipped=stats["skipped"],
                     source=stats["source"])
        if stats["missing"]:
            examples = ", ".join(Path(p).name for p in stats["missing_paths"][:5])
            message += "\n\n" + tr("db_manage.folder_import_missing",
                                    count=stats["missing"], examples=examples)
        QMessageBox.information(self, tr("db_manage.folder_import_title"), message)

    # ------------------------------------------------------------------
    # Keyboard handling - Esc closes the dialog.
    # ------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Escape:
            self.accept()
            return
        super().keyPressEvent(event)
