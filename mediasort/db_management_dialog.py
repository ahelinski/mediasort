"""Database management dialog (default key: F10).

Shows a summary of the tags database (number of assignments / entries,
distinct files, distinct tags) and offers three maintenance operations:

  * Compact - scan every file path in the database and delete the linked
    entries when the file no longer exists on disk (orphaned tags left
    without any assignments are dropped as well).
  * Export to CSV - write every assignment as (tag, timestamp, path)
    rows without internal ids; a whole-file tag has an empty timestamp.
  * Import from CSV - append assignments from the same format, skipping
    rows that duplicate an existing assignment (same tag, same file, and
    the same timestamp when one is given).
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox,
    QMessageBox, QFileDialog
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

from .i18n import tr
from . import styles


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
        self.compact_btn.clicked.connect(self._compact)
        self.export_btn.clicked.connect(self._export)
        self.import_btn.clicked.connect(self._import_csv)
        ops_layout.addWidget(self.compact_btn)
        ops_layout.addWidget(self.export_btn)
        ops_layout.addWidget(self.import_btn)
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
    def _compact(self):
        answer = QMessageBox.question(
            self, tr("db_manage.compact_title"), tr("db_manage.compact_ask"),
            defaultButton=QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed_files, removed_entries, removed_tags = self.tags_db.compact()
        self._refresh_stats()
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
        except OSError as e:
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
        except (OSError, UnicodeDecodeError) as e:
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
    # Keyboard handling - Esc closes the dialog.
    # ------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Escape:
            self.accept()
            return
        super().keyPressEvent(event)
