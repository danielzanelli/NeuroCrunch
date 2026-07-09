# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""NeuroCrunch - Main Application"""
import datetime
import os
import sys
import subprocess
import json
import warnings
import io

import pandas as pd
import numpy as np
import read_roi

# Keep startup simple: do not attempt to silence FFmpeg/Libav messages here.
# Warnings from underlying libraries will appear on the terminal.
warnings.filterwarnings('ignore')

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTreeWidgetItem, QTableWidgetItem, QMenu, QVBoxLayout, QLineEdit,
    QHBoxLayout, QPushButton, QSlider, QLabel, QWidget, QDialog, QSpinBox, QMessageBox,
    QComboBox, QCheckBox
)
from PySide6.QtCore import QCoreApplication, QUrl, Qt, QTimer, QThread, Signal, QRect, QPoint
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut, QTextCursor, QPainter, QPen, QColor, QPolygon, QBrush, QDesktopServices
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
try:
    # Optional: QtWebEngine is a ~290 MB dependency used only as a PDF-viewer
    # fallback. The primary PDF path is QPdfView (QtPdf). If WebEngine is not
    # bundled, the app still runs; the fallback is simply unavailable.
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    QWebEngineView = None

from tkinter.filedialog import askopenfilename, askdirectory, asksaveasfilename

import pyqtgraph as pg

from mainwindow import Ui_MainWindow
import icon_loader
from dark_mode_manager import DarkModeManager
from plugin_manager import PluginManager
from param_dialog import ParamDialog
from script_runner import PipelineContext, ScriptRunner
from updater import read_current_version, UpdateChecker, UpdateDownloader, apply_update


MAX_PLOT_COLUMNS = 100  # Maximum number of columns allowed to plot at once

# Source language of the codebase; selected when no translator is needed.
DEFAULT_LANGUAGE = 'en'
# (code, display name) pairs offered in the preferences dialog. Display names
# are shown in their own language, so they are intentionally not translated.
AVAILABLE_LANGUAGES = [
    ('en', 'English'),
    ('es', 'Español'),
]
SETTINGS_FILENAME = 'settings.json'


class CSVReaderWorker(QThread):
    """Worker thread to read CSV files with progress reporting."""
    progress_updated = Signal(str)  # Signal to update progress
    data_loaded = Signal(object)  # Signal when data is loaded
    error_occurred = Signal(str)  # Signal when error occurs

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path

    def run(self):
        """Run in background thread."""
        try:
            filename = os.path.basename(self.file_path)
            self.progress_updated.emit(QCoreApplication.translate('CSVReaderWorker', f'Opening CSV {filename}: 0%'))

            if self.file_path.lower().endswith('.csv'):
                # Count total lines upfront so progress can be calculated correctly
                with open(self.file_path, 'rb') as f:
                    total_lines = sum(1 for _ in f) - 1  # subtract header row

                chunk_size = max(total_lines // 100, 200)
                chunk_size = min(chunk_size, 10000)

                chunks = []
                loaded_rows = 0
                for chunk in pd.read_csv(self.file_path, chunksize=chunk_size):
                    chunks.append(chunk)
                    loaded_rows += len(chunk)
                    progress = min(int((loaded_rows / max(total_lines, 1)) * 100), 100)
                    self.progress_updated.emit(f'Opening CSV {filename}: {progress}%')

                if chunks:
                    data = pd.concat(chunks, ignore_index=True)
                else:
                    data = pd.read_csv(self.file_path)

            elif self.file_path.lower().endswith(('.xls', '.xlsx')):
                self.progress_updated.emit(f'Opening file {filename}: 0%')
                data = pd.read_excel(self.file_path)
                self.progress_updated.emit(f'Opening file {filename}: 100%')
            else:
                raise ValueError('File format not supported for charts.')

            self.data_loaded.emit(data)
        except Exception as e:
            self.error_occurred.emit(str(e))


class NeuroCrunch(QMainWindow):
    def __init__(self):
        super(NeuroCrunch, self).__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        # Icon loader needs the assets path before the file tree is populated
        icon_loader.init_icons(get_asset_path())

        # Initial pane proportions: explorer | viewer | scripts+log
        self.ui.main_splitter.setStretchFactor(0, 0)
        self.ui.main_splitter.setStretchFactor(1, 1)
        self.ui.main_splitter.setStretchFactor(2, 0)
        self.ui.main_splitter.setSizes([250, 550, 480])
        self.ui.right_splitter.setSizes([440, 260])

        # Set up translation. The language is read from the persisted user
        # settings, defaulting to English (the source language).
        self.translator = None
        self.settings = load_settings()
        self.current_language = self.settings.get('language', DEFAULT_LANGUAGE)
        self._setup_translator()
        # setupUi() ran before the translator was installed, so re-apply the
        # translations to the already-built UI for a non-English startup.
        if self.translator is not None:
            self.ui.retranslateUi(self)


        # Set all viewers to hidden initially; the image label doubles as the
        # empty-state hint until a file is previewed for the first time.
        self.ui.text_viewer.hide()
        self.ui.plot_frame.hide()
        self.ui.pdf_viewer.hide()
        self.ui.video_player.hide()
        self.ui.image_viewer.setText(self.tr('Double-click a file to preview it'))
        self.ui.image_viewer.setAlignment(Qt.AlignCenter)
        self.ui.image_viewer.show()

        # Default to the application directory as the local folder
        self.local_folder = os.path.dirname(os.path.abspath(__file__))
        # Bundled official scripts. Resolved via the frozen-aware resource base so
        # discovery works both in development (project_root/scripts) and inside the
        # PyInstaller bundle (sys._MEIPASS/scripts).
        self.scripts_folder = os.path.join(get_resource_base(), 'scripts')
        # Writable, per-user directory where community/user-installed scripts are dropped
        self.user_plugins_folder = self.get_user_plugins_dir()
        # Discover and validate script plugins (bundled + user); user plugins
        # with the same id override the bundled ones with the same id.
        self.plugin_manager = PluginManager()
        self.plugins = self.plugin_manager.discover_scripts(self.scripts_folder, self.user_plugins_folder)
        self.scripts = sorted(self.plugins.keys())
        self.config = {}
        self._refreshing_table = False
        # Pipeline context shared between the parameter dialog (Phase 3, for
        # pre-filling linked parameters) and the script runner (Phase 4,
        # which populates it after each script finishes). Uses a temporary
        # directory that is cleaned up after each pipeline execution.
        self.pipeline_context_store = PipelineContext()
        self._script_runner = None

        # Refresh the file viewer and scripts table with the initial local folder and scripts
        self.refresh_local_folder()
        self.refresh_scripts_table()

        # Surface any manifest/plugin issues found during discovery in the log
        for warning in self.plugin_manager.warnings:
            self.print(warning)

        # Categorical palette validated for >=3:1 contrast on both the dark
        # (#1a1e23) and light (#ffffff) plot surfaces; fixed slot order.
        self.plot_color_palette = [
            '#3987e5', '#199e70', '#c98500', '#008300',
            '#9085e9', '#e66767', '#d55181', '#d95926',
        ]


        # ...


        # Button connections
        self.ui.btn_open_folder.clicked.connect(self.select_local_folder)
        self.ui.btn_refresh.clicked.connect(self.on_refresh_clicked)
        self.ui.btn_save_config.clicked.connect(self.save_config)
        self.ui.btn_load_config.clicked.connect(self.load_config)
        self.ui.btn_execute_scripts.clicked.connect(self.toggle_pipeline)
        # "Open Scripts Folder" — opens the writable user-plugins directory where
        # users drop their own script folders; Refresh afterwards picks them up.
        self.ui.btn_open_scripts_dir.clicked.connect(self.open_scripts_folder)
        # Gear button — opens the preferences dialog (language selection).
        self.ui.btn_preferences.clicked.connect(self.open_preferences)

        # File viewer context menu
        self.ui.file_viewer.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ui.file_viewer.customContextMenuRequested.connect(self.show_file_context_menu)
        self.ui.file_viewer.itemDoubleClicked.connect(self.on_file_viewer_double_clicked)

        # Scripts table — double-click a row to open the parameter configuration dialog
        self.ui.table_data_columns.cellDoubleClicked.connect(self.open_param_dialog)
        # Note: checkbox changes are now handled by individual QCheckBox widgets


        self.print(self.tr('Program initialized') + ' - ' + datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S'))

        # Silently check GitHub Releases for a newer version once the UI is up.
        self._update_checker = None
        self._update_downloader = None
        QTimer.singleShot(0, self.check_for_updates)

    def _setup_translator(self):
        """Install the translator for the current language.

        English is the source language, so it needs no translator. For any other
        language a compiled Qt ``.qm`` catalog is preferred when present, falling
        back to the human-editable JSON catalog via :class:`JsonTranslator` (so
        translations work even without Qt's ``lrelease`` compiler).
        """
        from PySide6.QtCore import QTranslator
        from json_translator import JsonTranslator, load_json_catalog

        app = QApplication.instance()

        # Remove any translator installed for a previous language.
        if self.translator is not None:
            app.removeTranslator(self.translator)
            self.translator = None

        if self.current_language == DEFAULT_LANGUAGE:
            return  # source language — nothing to translate

        translations_dir = os.path.join(get_asset_path(), 'translations')
        if not os.path.isdir(translations_dir):
            return

        qm_translator = QTranslator()
        qm_file = os.path.join(translations_dir, f'neurocruncher_{self.current_language}.qm')
        if os.path.isfile(qm_file) and qm_translator.load(qm_file):
            self.translator = qm_translator
        else:
            catalog = load_json_catalog(translations_dir, self.current_language)
            if catalog:
                self.translator = JsonTranslator(catalog)

        if self.translator is not None:
            app.installTranslator(self.translator)

    def tr(self, text: str, context: str = 'NeuroCrunch') -> str:
        """Translate *text* via the installed translator (source text if none)."""
        return QCoreApplication.translate(context, text)

    def open_preferences(self) -> None:
        """Open the preferences dialog and apply any language change."""
        from preferences_dialog import PreferencesDialog

        dialog = PreferencesDialog(self.current_language, AVAILABLE_LANGUAGES, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_language(dialog.selected_language())

    def set_language(self, language: str) -> None:
        """Switch the UI language at runtime and persist the choice."""
        if not language or language == self.current_language:
            return
        self.current_language = language
        self._setup_translator()
        self._retranslate_ui()
        self.settings['language'] = language
        save_settings(self.settings)

    def _retranslate_ui(self) -> None:
        """Re-apply translations to widgets after a language change."""
        # Static UI: button texts, tooltips, table headers, panel titles.
        self.ui.retranslateUi(self)

        # Strings set from code are not covered by retranslateUi:
        if getattr(self, '_current_image_pixmap', None) is None:
            self.ui.image_viewer.setText(self.tr('Double-click a file to preview it'))
            self.ui.image_viewer.setAlignment(Qt.AlignCenter)

        # Keep the Run/Stop toggle label consistent with the runner state
        # (retranslateUi always resets it to the "Run" caption).
        runner = self._script_runner
        if runner is not None and runner.isRunning():
            self.ui.btn_execute_scripts.setText(self.tr('Stop'))
        else:
            self.ui.btn_execute_scripts.setText(self.tr('Run'))



    def print(self, text):
        self.ui.log.append( datetime.datetime.now().strftime('%H:%M:%S - ') + str(text))
        self.ui.log.moveCursor(QTextCursor.End)
        self.ui.log.ensureCursorVisible()

    def print_progress(self, text):
        """Update the last line in the log (for progress reporting)."""
        cursor = self.ui.log.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.select(QTextCursor.LineUnderCursor)
        cursor.removeSelectedText()
        cursor.insertText(datetime.datetime.now().strftime('%H:%M:%S - ') + str(text))
        self.ui.log.setTextCursor(cursor)
        self.ui.log.ensureCursorVisible()

    def select_local_folder(self):
        selected_folder = askdirectory(title=self.tr('Select local folder'))
        if selected_folder:
            self.local_folder = selected_folder
            self.ui.file_viewer.setHeaderLabel(self.local_folder)
            # Create a new pipeline context with temporary directory
            self.pipeline_context_store.cleanup()
            self.pipeline_context_store = PipelineContext()
            self.refresh_local_folder()

    def refresh_local_folder(self):
        self.ui.file_viewer.clear()
        if not self.local_folder:
            self.print(self.tr('No local folder selected.'))
            return
        if not os.path.exists(self.local_folder):
            self.print(self.tr(f'Local folder "{self.local_folder}" does not exist.'))
            return

        content = self.get_dir_content(self.local_folder)
        self.populate_file_viewer(content, self.ui.file_viewer.invisibleRootItem(), self.local_folder)

    def get_user_plugins_dir(self):
        """Resolve the writable, per-user directory where community/user-installed scripts live.

        This directory is outside the PyInstaller bundle so users can drop community
        plugin folders (each containing main.py + manifest.json) into it without
        touching the installed application. Created on first use if missing.
        """
        if sys.platform == 'win32':
            base = os.environ.get('APPDATA') or os.path.expanduser('~')
            path = os.path.join(base, 'NeuroCrunch', 'plugins')
        elif sys.platform == 'darwin':
            path = os.path.expanduser('~/Library/Application Support/NeuroCrunch/plugins')
        else:
            path = os.path.expanduser('~/.config/NeuroCrunch/plugins')

        try:
            os.makedirs(path, exist_ok=True)
        except OSError as e:
            self.print(self.tr(f'Could not create user plugins folder "{path}": {str(e)}'))

        return path

    def open_scripts_folder(self):
        """Open the writable user scripts directory in the OS file manager.

        Official scripts are bundled read-only inside the application; users add
        their own by dropping a folder (with config.json + <name>.py) into this
        directory, which survives app updates. After adding scripts, pressing
        Refresh re-scans and shows them.
        """
        path = self.user_plugins_folder
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as e:
            self.print(self.tr(f'Could not open scripts folder "{path}": {str(e)}'))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        self.print(self.tr(f'User scripts folder: {path}'))

    def rescan_scripts(self):
        """Re-discover bundled + user scripts and refresh the scripts table.

        Lets newly added user scripts appear without restarting the app. Config
        for scripts that no longer exist is dropped.
        """
        self.plugins = self.plugin_manager.discover_scripts(self.scripts_folder, self.user_plugins_folder)
        self.scripts = sorted(self.plugins.keys())
        self.config = {k: v for k, v in self.config.items() if k in self.plugins}
        self.refresh_scripts_table()
        for warning in self.plugin_manager.warnings:
            self.print(warning)

    def on_refresh_clicked(self):
        """Refresh button: refresh the file browser and re-scan for scripts."""
        self.refresh_local_folder()
        self.rescan_scripts()

    # ------------------------------------------------------------------
    # In-app updater (Phase 6)
    # ------------------------------------------------------------------

    def check_for_updates(self):
        """Start a background check of GitHub Releases for a newer version."""
        info = read_current_version(os.path.join(get_resource_base(), 'version.json'))
        repo = info.get('repo')
        current = info.get('version', '0.0.0')
        if not repo:
            return
        self._update_checker = UpdateChecker(repo, current)
        self._update_checker.update_available.connect(self._on_update_available)
        # Keep the check silent on failure (offline, rate limit): log, don't nag.
        self._update_checker.error.connect(self.print)
        self._update_checker.start()

    def _on_update_available(self, release):
        version = release.get('version', '')
        self.statusBar().showMessage(self.tr(f'NeuroCrunch {version} available'))
        asset = release.get('asset')
        if not asset:
            QMessageBox.information(
                self, self.tr('Update available'),
                self.tr(f'There is a new version ({version}), but there is no installer for this ')
                + self.tr('platform.\nDownload it manually from:\n') + release.get("html_url", ""))
            return
        reply = QMessageBox.question(
            self, self.tr('Update available'),
            self.tr(f'A new version is available ({version}).\nDownload it now?'))
        if reply == QMessageBox.Yes:
            self._start_update_download(asset)

    def _start_update_download(self, asset):
        url = asset.get('browser_download_url')
        name = asset.get('name')
        if not url or not name:
            self.print(self.tr('The update asset does not have a valid URL or name.'))
            return
        self.print(self.tr(f'Downloading update: {name}...'))
        self._update_downloader = UpdateDownloader(url, name)
        self._update_downloader.progress.connect(
            lambda pct: self.statusBar().showMessage(self.tr(f'Downloading update: {pct}%')))
        self._update_downloader.finished_ok.connect(self._on_update_downloaded)
        self._update_downloader.error.connect(self.print)
        self._update_downloader.start()

    def _on_update_downloaded(self, path):
        self.statusBar().showMessage(self.tr('Download complete'))
        reply = QMessageBox.question(
            self, self.tr('Apply update'),
            self.tr('The update was downloaded successfully.\nRestart NeuroCrunch to apply it?'))
        if reply == QMessageBox.Yes:
            apply_update(path)
            QApplication.quit()

    def get_dir_content(self, path):
        """Get the content of a directory recursively, returning a tree structure.
        Returns a list where items are either:
        - Tuples: (folder_name, folder_contents) for directories
        - Strings: filename for files
        """
        content = []

        if os.path.isfile(path):
            raise ValueError(f'The path "{path}" is a file, a folder was expected.')
        if not os.path.exists(path):
            raise ValueError(f'The folder "{path}" does not exist.')

        try:
            items = os.listdir(path)
        except PermissionError:
            return content

        # Sort items: folders first, then files
        folders = sorted([item for item in items if os.path.isdir(os.path.join(path, item))])
        files = sorted([item for item in items if os.path.isfile(os.path.join(path, item))])

        for folder in folders:
            folder_path = os.path.join(path, folder)
            try:
                # Store tuple: (folder_name, folder_contents)
                content.append((folder, self.get_dir_content(folder_path)))
            except PermissionError:
                pass

        for file in files:
            content.append(file)

        return content

    def populate_file_viewer(self, content, parent_item, parent_path=''):
        """Populate the file viewer tree widget with the given content.
        Expects items to be either tuples (folder_name, contents) or strings (filenames).
        Stores full paths in item data for context menu operations.
        """
        for item in content:
            if isinstance(item, tuple):
                # This is a directory: (folder_name, folder_contents)
                folder_name, folder_contents = item
                dir_item = QTreeWidgetItem(parent_item)
                dir_item.setText(0, folder_name)
                dir_item.setIcon(0, icon_loader.icon_for_file(folder_name, is_dir=True))

                # Store full path
                full_path = os.path.join(parent_path, folder_name)
                dir_item.setData(0, Qt.UserRole, full_path)

                # Show expand arrow even if folder is empty
                dir_item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)

                self.populate_file_viewer(folder_contents, dir_item, full_path)
            else:
                # This is a file
                file_item = QTreeWidgetItem(parent_item)
                file_item.setText(0, item)
                file_item.setIcon(0, icon_loader.icon_for_file(item))

                # Store full path
                full_path = os.path.join(parent_path, item)
                file_item.setData(0, Qt.UserRole, full_path)

    def show_file_context_menu(self, position):
        """Show context menu for file viewer items on right-click"""
        item = self.ui.file_viewer.itemAt(position)
        if not item:
            return

        file_path = item.data(0, Qt.UserRole)
        if not file_path:
            return

        menu = QMenu()

        # Open file action
        open_action = menu.addAction(self.tr("Open"))
        open_action.triggered.connect(lambda: self.on_file_viewer_double_clicked(item, 0))

        menu.addSeparator()

        # Open in location action
        open_location_action = menu.addAction(self.tr("Show in folder"))
        open_location_action.triggered.connect(lambda: self.open_in_file_explorer(file_path))

        menu.exec(self.ui.file_viewer.mapToGlobal(position))

    def open_in_file_explorer(self, file_path):
        """Open file or folder in system file explorer"""
        if not os.path.exists(file_path):
            self.print(self.tr(f'The file/folder "{file_path}" does not exist.'))
            return

        try:
            if sys.platform == 'win32':
                # Windows: open with /select to highlight the item
                subprocess.Popen(['explorer', '/select,', os.path.normpath(file_path)])
            elif sys.platform == 'darwin':
                # macOS: open with Finder
                subprocess.Popen(['open', '-R', file_path])
            else:
                # Linux: open with file manager
                subprocess.Popen(['xdg-open', os.path.dirname(file_path)])

            self.print(self.tr(f'Opening in file explorer: {file_path}'))
        except Exception as e:
            self.print(f'Error opening file explorer: {str(e)}')



    def on_file_viewer_double_clicked(self, item, column):
        """Handle double-click on file viewer items"""
        file_path = item.data(0, Qt.UserRole)
        # Only open files on double-click. Directory expansion is handled by the tree arrow.
        if not file_path:
            return

        if os.path.isdir(file_path):
            # Ignore double-clicks on folder names (arrow will expand)
            return

        if os.path.isfile(file_path):
            # We can open images, text files, videos, CSVs (pyqtgraph) and PDFs directly in the app by showing them in the right panel and hiding the other display widgets.
            #  We try for different file types, last case being trying to open as text file, if it fails we print an error message in the log.

            try:
                # Images
                if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif')):
                    self.show_image(file_path)
                # Data files
                elif file_path.lower().endswith(('.csv', '.xls', '.xlsx')):
                    self.show_plot(file_path)
                # PDFs
                elif file_path.lower().endswith('.pdf'):
                    self.show_pdf(file_path)
                # Videos
                elif file_path.lower().endswith(('.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.mpeg', '.mpg', '.webm', '.tif', '.tiff')):
                    self.show_video(file_path)
                # ROI zip files (only if a video is currently showing)
                elif file_path.lower().endswith('.zip') and self.ui.video_player.isVisible():
                    self.load_and_display_roi(file_path)
                # Text files
                else:
                    self.show_text_file(file_path)
            except Exception as e:
                self.print(self.tr(f"Error opening the file:\n{str(e)}"))

    def show_column_range_dialog(self, total_columns):
        """Show a dialog to let user select column range. Returns (start_col, end_col) or None if cancelled."""
        max_selectable = min(MAX_PLOT_COLUMNS, total_columns)
        dialog = QDialog(self)
        dialog.setWindowTitle('Select column range')
        dialog.setModal(True)

        layout = QVBoxLayout()

        # Add description
        desc_label = QLabel(f'Total columns: {total_columns}\nMaximum allowed: {max_selectable}\n')
        layout.addWidget(desc_label)

        # Start column spinbox
        start_label = QLabel('Start column (0-indexed):')
        self.start_spin = QSpinBox()
        self.start_spin.setMinimum(0)
        self.start_spin.setMaximum(total_columns - 1)
        self.start_spin.setValue(0)
        layout.addWidget(start_label)
        layout.addWidget(self.start_spin)

        # End column spinbox
        end_label = QLabel(f'End column (0-indexed, max +{max_selectable} from start):')
        self.end_spin = QSpinBox()
        self.end_spin.setMinimum(0)
        self.end_spin.setMaximum(total_columns - 1)
        self.end_spin.setValue(min(max_selectable - 1, total_columns - 1))
        layout.addWidget(end_label)
        layout.addWidget(self.end_spin)

        # Buttons
        button_layout = QHBoxLayout()
        ok_button = QPushButton('OK')
        cancel_button = QPushButton('Cancel')
        ok_button.clicked.connect(dialog.accept)
        cancel_button.clicked.connect(dialog.reject)
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

        dialog.setLayout(layout)

        if dialog.exec() == QDialog.Accepted:
            start = self.start_spin.value()
            end = self.end_spin.value()

            # Validate range
            if end < start:
                QMessageBox.warning(self, 'Error', 'The end column must be >= start column')
                return None

            if (end - start + 1) > MAX_PLOT_COLUMNS:
                QMessageBox.warning(self, 'Error', f'Cannot plot more than {MAX_PLOT_COLUMNS} columns')
                return None

            return (start, end)
        return None

    def refresh_scripts_table(self):
        """
            Refreshes the table_data_columns table with the current list of scripts and their config.

            Columns are:
                0 - Script name
                1 - Last modification timestamp
                2 - Checkbox to enable/disable script execution
                3 - Execution order
                4 - Configured status (green = all required params set; double-click to open dialog)

            self.config: Dictionary where keys are script ids and values are dictionaries with script configuration, including:
                - 'enabled': bool indicating if the script is enabled
                - 'parameters': dict of parameter names and their current values
                - 'last_modified': timestamp of last modification of the config for this script
                - 'execution_order': Optional[int] execution order in the pipeline

            If the script id is not in self.config, it will be added with default values (enabled=False, empty parameters, current timestamp).

            Script metadata (display name, description, version, author, category, official/community)
            comes from the PluginInfo objects in self.plugins, populated by PluginManager.discover_scripts.
        """
        table = self.ui.table_data_columns

        self._refreshing_table = True
        table.blockSignals(True)
        table.setRowCount(0)
        table.setColumnWidth(0, 140)
        table.setColumnWidth(1, 140)
        table.setColumnWidth(2, 80)
        table.setColumnWidth(3, 60)

        # Ensure every script has a config entry before computing selection counts
        for script in self.scripts:
            if script not in self.config:
                self.config[script] = {
                    'enabled': False,
                    'parameters': {},
                    'last_modified': None,
                    'execution_order': None
                }

        # Scripts can only run if they have been configured; clear stale enabled flags
        for s in self.scripts:
            if self.config[s]['last_modified'] is None:
                self.config[s]['enabled'] = False
                self.config[s]['execution_order'] = None

        # Number of scripts marked for execution; clear any orders that exceed that count
        n_selected = sum(1 for s in self.scripts if self.config[s]['enabled'])
        for s in self.scripts:
            if (self.config[s]['execution_order'] or 0) > n_selected:
                self.config[s]['execution_order'] = None

        for script in self.scripts:
            plugin_info = self.plugins[script]

            row_position = table.rowCount()
            table.insertRow(row_position)

            # Script name (display name from the manifest, with rich metadata as a tooltip)
            script_item = QTableWidgetItem()
            script_item.setText(plugin_info.name)
            origin = 'Official' if plugin_info.is_official else 'Community'
            script_item.setToolTip(
                f'{plugin_info.name} (v{plugin_info.version})\n'
                f'{plugin_info.description}\n'
                f'Category: {plugin_info.category} · Author: {plugin_info.author} · {origin}\n'
                f'Double-click to configure parameters'
            )
            table.setItem(row_position, 0, script_item)

            # Configuration timestamp — "-" until the user saves parameters
            timestamp_item = QTableWidgetItem()
            ts = self.config[script]['last_modified']
            timestamp_item.setText(ts if ts is not None else '-')
            timestamp_item.setTextAlignment(Qt.AlignCenter)
            table.setItem(row_position, 1, timestamp_item)

            # Checkbox for execution (Selection) — only interactive when the script has been configured
            is_configured = self.config[script]['last_modified'] is not None

            # Create a centered checkbox widget
            checkbox_widget = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_widget)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            checkbox_layout.setAlignment(Qt.AlignCenter)

            checkbox = QCheckBox()
            checkbox.setChecked(self.config[script]['enabled'] if is_configured else False)
            checkbox.setEnabled(is_configured)
            # Store the script_id in the checkbox for easy access
            checkbox.script_id = script
            checkbox.stateChanged.connect(self._on_checkbox_state_changed)

            checkbox_layout.addWidget(checkbox)
            table.setCellWidget(row_position, 2, checkbox_widget)

            # Order dropdown — positions 1..n_selected; disabled when script is not selected
            order_combo = QComboBox()
            order_combo.addItem('—')
            if self.config[script]['enabled']:
                for i in range(1, n_selected + 1):
                    order_combo.addItem(str(i))
                order_val = self.config[script]['execution_order']
                if order_val is not None and 1 <= order_val <= n_selected:
                    order_combo.setCurrentIndex(order_val)
                else:
                    order_combo.setCurrentIndex(0)
            else:
                order_combo.setEnabled(False)

            # Center the combobox items
            for i in range(order_combo.count()):
                order_combo.model().item(i).setTextAlignment(Qt.AlignCenter)

            order_combo.currentIndexChanged.connect(
                lambda idx, sid=script: self._on_combobox_order_changed(sid, idx)
            )

            # Create a centered widget for the combobox
            order_widget = QWidget()
            order_layout = QHBoxLayout(order_widget)
            order_layout.setContentsMargins(0, 0, 0, 0)
            order_layout.setAlignment(Qt.AlignCenter)
            order_layout.addWidget(order_combo)

            table.setCellWidget(row_position, 3, order_widget)




        table.blockSignals(False)
        self._refreshing_table = False

    def _on_checkbox_state_changed(self) -> None:
        """Handle checkbox state changes from the checkbox widgets."""
        sender = self.sender()
        if not isinstance(sender, QCheckBox) or not hasattr(sender, 'script_id'):
            return

        script_id = sender.script_id
        checked = sender.isChecked()

        self.config[script_id]['enabled'] = checked
        if checked:
            # Auto-assign the next free execution order (smallest positive
            # integer not already used by another enabled script)
            used_orders = {
                self.config[s]['execution_order']
                for s in self.scripts
                if s != script_id and self.config[s]['enabled']
                and self.config[s]['execution_order'] is not None
            }
            next_order = 1
            while next_order in used_orders:
                next_order += 1
            self.config[script_id]['execution_order'] = next_order
        else:
            removed_order = self.config[script_id]['execution_order']
            self.config[script_id]['execution_order'] = None
            # Compact remaining orders so they stay contiguous (1..n_selected)
            if removed_order is not None:
                for s in self.scripts:
                    order_val = self.config[s]['execution_order']
                    if order_val is not None and order_val > removed_order:
                        self.config[s]['execution_order'] = order_val - 1

        self.refresh_scripts_table()

    def _on_combobox_order_changed(self, script_id: str, index: int) -> None:
        """Handle order dropdown selection changes."""
        if self._refreshing_table:
            return

        new_order = None if index == 0 else index

        # Conflict resolution: clear and uncheck the script that currently holds this order
        if new_order is not None:
            for other_id in self.scripts:
                if other_id != script_id and self.config[other_id]['execution_order'] == new_order:
                    self.config[other_id]['execution_order'] = None
                    self.config[other_id]['enabled'] = False
                    self.print(
                        f'Order {new_order} reassigned from "{self.plugins[other_id].name}": disabled.'
                    )
                    break

        self.config[script_id]['execution_order'] = new_order
        self.refresh_scripts_table()

    def save_config(self) -> None:
        """Save the current script configuration to a JSON .config file."""
        file_path = asksaveasfilename(
            title=self.tr('Save configuration'),
            defaultextension='.config',
            filetypes=[(self.tr('Configuration file'), '*.config'), (self.tr('All files'), '*.*')],
        )
        if not file_path:
            return
        try:
            # Persist the script config plus the current working directory under a
            # reserved key (ignored by the per-script load loop for back-compat).
            data = dict(self.config)
            data['__working_directory__'] = self.local_folder
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.print(f'Configuration saved to: {os.path.basename(file_path)}')
        except Exception as e:
            self.print(f'Error saving configuration: {str(e)}')

    def load_config(self) -> None:
        """Load a previously saved .config file into self.config and refresh the table."""
        file_path = askopenfilename(
            title=self.tr('Load configuration'),
            filetypes=[(self.tr('Configuration file'), '*.config'), (self.tr('All files'), '*.*')],
        )
        if not file_path:
            return
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                self.print('Error: the configuration file does not have the expected format.')
                return
            # Restore the working directory if it was saved and still exists.
            saved_cwd = loaded.pop('__working_directory__', None)
            # Merge: only update entries for known scripts; ignore stale keys
            for script_id, cfg in loaded.items():
                if script_id in self.scripts:
                    self.config[script_id] = cfg
            self.refresh_scripts_table()
            if saved_cwd and os.path.isdir(saved_cwd):
                self.local_folder = saved_cwd
                self.ui.file_viewer.setHeaderLabel(self.local_folder)
                self.refresh_local_folder()
                self.print(f'Working folder restored: {saved_cwd}')
            self.print(f'Configuration loaded from: {os.path.basename(file_path)}')
        except (OSError, json.JSONDecodeError) as e:
            self.print(f'Error loading configuration: {str(e)}')

    def open_param_dialog(self, row: int, column: int) -> None:
        """Open the parameter configuration dialog for the script in *row*.

        Connected to ``table_data_columns.cellDoubleClicked``.  Saves the
        accepted values back into ``self.config`` and refreshes the table so
        the "Configured" column updates immediately.
        """
        if column == 2:  # checkbox column — ignore double-clicks
            return
        if row < 0 or row >= len(self.scripts):
            return

        script_id = self.scripts[row]
        plugin_info = self.plugins.get(script_id)
        if plugin_info is None:
            return

        current_values = self.config.get(script_id, {}).get('parameters', {})

        dialog = ParamDialog(plugin_info, current_values, self.pipeline_context_store.as_dict(), self)
        if dialog.exec() == ParamDialog.DialogCode.Accepted:
            values = dialog.get_values()
            self.config[script_id]['parameters'] = values
            self.config[script_id]['last_modified'] = datetime.datetime.now().strftime('%Y/%m/%d - %H:%M')
            self.print(f'Parameters saved for "{plugin_info.name}"')
            self.refresh_scripts_table()

    def _build_pipeline(self):
        """Build the ordered ``(script_id, plugin_info, params)`` list of
        scripts marked for execution, sorted by their ``execution_order``.

        Returns ``None`` (after logging an explanatory message) if the
        pipeline cannot be built (nothing selected or missing order).
        """
        selected = [
            script_id for script_id in self.scripts
            if self.config.get(script_id, {}).get('enabled')
        ]
        if not selected:
            self.print(self.tr('No scripts selected to run.'))
            return None

        missing_order = [
            self.plugins[s].name for s in selected
            if self.config[s].get('execution_order') is None
        ]
        if missing_order:
            self.print(
                self.tr('The following selected scripts do not have an execution order assigned: ')
                + ', '.join(missing_order)
            )
            return None

        selected.sort(key=lambda s: self.config[s]['execution_order'])

        pipeline = [
            (script_id, self.plugins[script_id], self.config[script_id].get('parameters', {}))
            for script_id in selected
        ]
        return pipeline

    def toggle_pipeline(self) -> None:
        """Toggle between running and stopping the pipeline.

        Connected to ``btn_execute_scripts``. If a pipeline is currently running,
        shows a confirmation dialog before stopping. Otherwise, starts a new pipeline.
        """
        if self._script_runner is not None and self._script_runner.isRunning():
            # Pipeline is running — ask for confirmation before stopping
            reply = QMessageBox.warning(
                self,
                self.tr('Confirm stop'),
                self.tr('Are you sure you want to stop the pipeline?\nThis will interrupt the current process.'),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.print(self.tr('Stopping pipeline...'))
                self._script_runner.stop()
            return

        # No pipeline running — start a new one
        pipeline = self._build_pipeline()
        if not pipeline:
            return

        self.ui.btn_execute_scripts.setEnabled(True)
        self.ui.btn_execute_scripts.setText(self.tr('Stop'))
        self.ui.btn_execute_scripts.setIcon(icon_loader.get_icon('square', '#ffffff', 16))

        self._script_runner = ScriptRunner(pipeline, self.pipeline_context_store, self)
        self._script_runner.log_message.connect(self._on_log_message)
        self._script_runner.progress_changed.connect(self._on_progress_changed)
        self._script_runner.script_started.connect(
            lambda script_id: self.print(f'Starting script: {self.plugins[script_id].name}')
        )
        self._script_runner.script_finished.connect(self._on_script_finished)
        self._script_runner.pipeline_done.connect(self._on_pipeline_done)
        self._script_runner.start()

    def _on_log_message(self, text: str) -> None:
        """Route log lines from the script runner to the correct display method.

        Lines prefixed with '\\r' are in-place progress updates (e.g. from
        ``print(..., end='', flush=True)`` with a carriage return); they update
        the last log entry. All other lines append a new timestamped entry.
        """
        if text.startswith('\r'):
            self.print_progress(text[1:])
        else:
            self.print(text)

    def _on_progress_changed(self, percent: int) -> None:
        """Handle a PROGRESS:N line from a running script.

        Shown in the status bar so it updates in place, without clobbering log
        lines the script prints between progress updates.
        """
        self.statusBar().showMessage(f'Progress: {percent}%')

    def _on_script_finished(self, script_id: str, success: bool) -> None:
        status = 'completed' if success else 'with error'
        self.print(f'Script "{self.plugins[script_id].name}" {status}.')

    def _on_pipeline_done(self, success: bool) -> None:
        self.ui.btn_execute_scripts.setEnabled(True)
        self.ui.btn_execute_scripts.setText(self.tr('Run'))
        self.ui.btn_execute_scripts.setIcon(icon_loader.get_icon('play', '#ffffff', 16))
        self.statusBar().clearMessage()
        self.print(self.tr('Pipeline completed successfully.') if success else self.tr('Pipeline completed with errors.'))
        # Clean up the temporary pipeline context and create a new one for the next run
        self.pipeline_context_store.cleanup()
        self.pipeline_context_store = PipelineContext()

    def show_image(self, file_path):
        """Shows an image on the ui.image_viewer QLabel, hiding the other display widgets."""
        if hasattr(self, 'frame_timer') and self.frame_timer is not None:
            self.frame_timer.stop()
        if hasattr(self, 'media_player'):
            self.media_player.stop()
            self.media_player.setSource(QUrl())

        # Keep the original pixmap so we can rescale it on every resize (and on
        # first show, once the label has been laid out to its real size).
        self._current_image_pixmap = QPixmap(file_path)
        self.ui.image_viewer.setAlignment(Qt.AlignCenter)
        self.ui.image_viewer.show()
        self.ui.text_viewer.hide()
        self.ui.plot_frame.hide()
        self.ui.pdf_viewer.hide()
        self.ui.video_player.hide()

        self._rescale_current_image()
        # The label may not have its final size until the layout settles after
        # show(); rescale again on the next event-loop tick so the first image
        # fills the viewer instead of appearing tiny.
        QTimer.singleShot(0, self._rescale_current_image)

    def _rescale_current_image(self):
        """Rescale the stored image pixmap to the current viewer size."""
        if not hasattr(self, 'ui'):
            return
        pixmap = getattr(self, '_current_image_pixmap', None)
        if pixmap is None or pixmap.isNull() or not self.ui.image_viewer.isVisible():
            return
        self.ui.image_viewer.setPixmap(pixmap.scaled(
            self.ui.image_viewer.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        """Keep the displayed image scaled to the viewer as the window resizes."""
        super().resizeEvent(event)
        self._rescale_current_image()


    def show_plot(self, file_path):
        """Shows a plot on the ui.plot_viewer pyqtgraph widget, hiding the other display widgets."""
        if hasattr(self, 'frame_timer') and self.frame_timer is not None:
            self.frame_timer.stop()
        if hasattr(self, 'media_player'):
            self.media_player.stop()
            self.media_player.setSource(QUrl())

        self.ui.image_viewer.hide()
        self.ui.text_viewer.hide()
        self.ui.plot_frame.show()
        self.ui.pdf_viewer.hide()
        self.ui.video_player.hide()

        # Load data in background thread with progress reporting
        self.csv_reader = CSVReaderWorker(file_path)
        self.csv_reader.progress_updated.connect(self._on_csv_progress, Qt.BlockingQueuedConnection)
        self.csv_reader.data_loaded.connect(self._on_csv_loaded)
        self.csv_reader.error_occurred.connect(self._on_csv_error)
        self.csv_reader.start()

    def _on_csv_progress(self, message):
        """Update progress in log."""
        self.print_progress(message)
        self.ui.log.repaint()

    def _on_csv_error(self, error_msg):
        """Handle CSV loading error."""
        self.print(f"Error loading data for chart:\n{error_msg}")

    def _on_csv_loaded(self, data):
        """Handle CSV loaded from background thread."""

        self.print(self.tr(f'Loaded: {len(data)} rows, {len(data.columns)} columns'))
        self.data = data

        # Create two spinboxes and a button at the bottom of the self.ui.plot_frame

        total_columns = len(self.data.columns)
        max_selectable = min(MAX_PLOT_COLUMNS, total_columns)



        # Clear previous widgets
        for child in self.ui.plot_frame.findChildren(QSpinBox):
            child.deleteLater()
        for child in self.ui.plot_frame.findChildren(QPushButton):
            child.deleteLater()
        for child in self.ui.plot_frame.findChildren(QLabel):
            child.deleteLater()
        for child in self.ui.plot_frame.findChildren(QLineEdit):
            child.deleteLater()

        # Create main layout
        layout = self.ui.plot_frame.layout()
        if layout is None:
            layout = QVBoxLayout()
            self.ui.plot_frame.setLayout(layout)

        columns_widget = QWidget(self.ui.plot_frame)
        columns_layout = QHBoxLayout()

        # Add description
        desc_label = QLabel(f'Total columns: {total_columns}\nMaximum allowed: {max_selectable}\n')
        columns_layout.addWidget(desc_label)

        # Regex finder for column names
        regex_label = QLabel('Columns that include:')
        self.regex_input = QLineEdit()
        columns_layout.addWidget(regex_label)
        columns_layout.addWidget(self.regex_input)

        # Start column spinbox
        start_label = QLabel('Start column:')
        self.start_spin = QSpinBox()
        self.start_spin.setMinimum(0)
        self.start_spin.setMaximum(total_columns - 1)
        self.start_spin.setValue(0)
        columns_layout.addWidget(start_label)
        columns_layout.addWidget(self.start_spin)

        # End column spinbox
        end_label = QLabel(f'End column:')
        self.end_spin = QSpinBox()
        self.end_spin.setMinimum(0)
        self.end_spin.setMaximum(total_columns - 1)
        self.end_spin.setValue(1)
        columns_layout.addWidget(end_label)
        columns_layout.addWidget(self.end_spin)

        # Button
        ok_button = QPushButton('Plot')
        ok_button.clicked.connect(self.plot_data)
        columns_layout.addWidget(ok_button)
        columns_widget.setLayout(columns_layout)

        # Add the columns selection widget below the plot
        layout.addWidget(columns_widget)

        self.plot_data()



    def plot_data(self):
        try:

            # Get column range from spinboxes
            start_col = self.start_spin.value()
            end_col = self.end_spin.value()

            columns_to_plot = list(self.data.columns[start_col:end_col+1])

            # Filter columns by "regex" input (simple substring match)
            regex_filter = self.regex_input.text().strip()
            if regex_filter:
                columns_to_plot = [col for col in columns_to_plot if regex_filter in str(col)]

            columns_to_plot = columns_to_plot[:MAX_PLOT_COLUMNS]

            # Clear previous plot and legend
            self.ui.plot_widget.clear()
            self._plot_items = {}

            # Create a legend (ensure a single legend is used for this plot)
            try:
                legend = self.ui.plot_widget.addLegend()
            except Exception as e:
                self.print(f"Warning: Could not create the interactive legend:\n{str(e)}")
                legend = None

            # Plot selected columns and save references
            for i, column in enumerate(columns_to_plot):
                pen = pg.mkPen(self.plot_color_palette[i % len(self.plot_color_palette)], width=2)
                plot_item = self.ui.plot_widget.plot(self.data[column], pen=pen, name=str(column))
                # store by column name for toggling
                self._plot_items[str(column)] = plot_item

            # Make legend entries clickable to toggle visibility
            if legend is not None:
                try:
                    # legend.items is a list of (sample, label) pairs
                    for sample, label in list(legend.items):
                        # label may be a QGraphicsTextItem or similar; get the text
                        try:
                            label_text = str(label.text)
                        except Exception:
                            try:
                                label_text = str(label.toPlainText())
                            except Exception:
                                # fallback: read from the label's bounding rect or skip
                                label_text = None

                        # If label_text not available, try reading from the associated plot item name
                        if not label_text:
                            continue

                        # Define toggle function bound to this label_text
                        def make_toggle(name, lab, samp):
                            def _toggle(event):
                                item = self._plot_items.get(name)
                                if item is None:
                                    return
                                visible = not item.isVisible()
                                item.setVisible(visible)
                                # visually dim the legend entry when hidden
                                try:
                                    lab.setOpacity(1.0 if visible else 0.4)
                                except Exception:
                                    pass
                                try:
                                    samp.setOpacity(1.0 if visible else 0.25)
                                except Exception:
                                    pass
                            return _toggle

                        # Attach click handler to both sample and label if possible
                        try:
                            handler = make_toggle(label_text, label, sample)
                            sample.mousePressEvent = handler
                            label.mousePressEvent = handler
                        except Exception:
                            # best-effort; ignore if API differs
                            pass
                except Exception:
                    # Non-fatal: continue without clickable legend
                    pass
        except Exception as e:
            self.print(f"Error loading data for chart:\n{str(e)}")
            self.ui.plot_widget.clear()

    def load_and_display_roi(self, roi_zip_path):
        """Load ROI zip and store data; ROIs are painted onto each subsequent video frame."""
        try:
            rois = read_roi.read_roi_zip(roi_zip_path)
            if not rois:
                self.print(self.tr(f'No ROIs found in {os.path.basename(roi_zip_path)}'))
                return
            self.roi_data = rois
            self.print(self.tr(f'ROIs loaded: {len(rois)} regions from {os.path.basename(roi_zip_path)}'))
        except Exception as e:
            self.print(f'Error loading ROI:\n{str(e)}')

    def show_video(self, file_path):
        """Shows a video using QVideoSink so ROIs can be painted onto each decoded frame."""
        self.ui.image_viewer.hide()
        self.ui.text_viewer.hide()
        self.ui.plot_frame.hide()
        self.ui.pdf_viewer.hide()
        self.ui.video_player.show()

        try:
            if hasattr(self, 'media_player'):
                self.media_player.stop()
                self.media_player.setSource(QUrl())

            # Clear previous layout contents
            layout = self.ui.video_player.layout()
            if layout is None:
                layout = QVBoxLayout()
                self.ui.video_player.setLayout(layout)
            else:
                while layout.count():
                    item = layout.takeAt(0)
                    w = item.widget()
                    if w:
                        w.deleteLater()

            # QLabel displays decoded frames; black background for letterboxing
            self.video_display_label = QLabel()
            self.video_display_label.setAlignment(Qt.AlignCenter)
            self.video_display_label.setStyleSheet("background: black;")

            # QVideoSink receives raw frames — lets us draw ROIs before display
            self.media_player = QMediaPlayer(self)
            self.video_sink = QVideoSink(self)
            self.media_player.setVideoSink(self.video_sink)
            self.video_sink.videoFrameChanged.connect(self._on_video_frame_received)
            self._pending_frame = None

            # Render timer: pull the latest stored frame at a fixed ~30 fps so the
            # main thread is not flooded by every decoded frame from the video sink.
            if hasattr(self, 'frame_timer') and self.frame_timer is not None:
                self.frame_timer.stop()
            self.frame_timer = QTimer(self)
            self.frame_timer.setInterval(33)  # ~30 fps
            self.frame_timer.timeout.connect(self._render_pending_frame)
            self.frame_timer.start()

            # Reset ROI data for the new video
            self.roi_data = {}

            # Control bar
            control_widget = QWidget()
            control_layout = QHBoxLayout(control_widget)
            control_layout.setContentsMargins(0, 2, 0, 2)
            control_layout.setSpacing(3)

            self.play_button = QPushButton()
            self.play_button.setIcon(icon_loader.get_icon('play', icon_loader.glyph_color(), 14))
            self.play_button.setFixedSize(30, 24)
            self.play_button.clicked.connect(self.toggle_play_pause)
            control_layout.addWidget(self.play_button)

            self.progress_slider = QSlider(Qt.Horizontal)
            self.progress_slider.setMinimum(0)
            self.progress_slider.sliderMoved.connect(self.set_position)
            self.media_player.durationChanged.connect(self.update_duration)
            self.media_player.positionChanged.connect(self.update_position)
            control_layout.addWidget(self.progress_slider, 1)

            self.time_label = QLabel("00:00 / 00:00")
            self.time_label.setMinimumWidth(85)
            self.time_label.setMaximumHeight(22)
            self.time_label.setStyleSheet("font-size: 10px;")
            control_layout.addWidget(self.time_label)

            layout.addWidget(self.video_display_label, 1)
            layout.addWidget(control_widget, 0)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            # Load and play, suppressing FFmpeg stderr noise
            try:
                old_stderr_fd = os.dup(2)
                null_fd = os.open(os.devnull, os.O_WRONLY)
                os.dup2(null_fd, 2)
                try:
                    self.media_player.setSource(QUrl.fromLocalFile(file_path))
                    self.media_player.play()
                finally:
                    os.dup2(old_stderr_fd, 2)
                    os.close(old_stderr_fd)
                    os.close(null_fd)
            except Exception:
                self.media_player.setSource(QUrl.fromLocalFile(file_path))
                self.media_player.play()

            self.play_button.setIcon(icon_loader.get_icon('pause', icon_loader.glyph_color(), 14))
            self.print(self.tr(f'Playing video: {os.path.basename(file_path)}'))

        except Exception as e:
            self.print(f"Error loading video:\n{str(e)}")
            self.ui.video_player.hide()

    def _on_video_frame_received(self, frame):
        """Store the latest decoded frame; rendering is done by the timer at ~30 fps."""
        self._pending_frame = frame

    def _render_pending_frame(self):
        """Render the latest stored video frame (called by QTimer at ~30 fps)."""
        frame = getattr(self, '_pending_frame', None)
        if frame is None or not frame.isValid():
            return
        self._pending_frame = None

        image = frame.toImage()
        if image.isNull():
            return

        roi_data = getattr(self, 'roi_data', {})
        if roi_data:
            painter = QPainter(image)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(QPen(QColor(0, 255, 0, 230), 2))
            painter.setBrush(QBrush(QColor(0, 255, 0, 50)))
            for roi_d in roi_data.values():
                try:
                    if isinstance(roi_d, dict):
                        if 'x' in roi_d and 'y' in roi_d:
                            points = [QPoint(int(x), int(y)) for x, y in zip(roi_d['x'], roi_d['y'])]
                            if len(points) > 2:
                                painter.drawPolygon(QPolygon(points))
                        elif all(k in roi_d for k in ['left', 'top', 'width', 'height']):
                            painter.drawRect(
                                int(roi_d['left']), int(roi_d['top']),
                                int(roi_d['width']), int(roi_d['height'])
                            )
                except Exception:
                    pass
            painter.end()

        pixmap = QPixmap.fromImage(image)
        if not pixmap.isNull() and self.video_display_label.width() > 0:
            self.video_display_label.setPixmap(
                pixmap.scaled(self.video_display_label.size(),
                              Qt.KeepAspectRatio, Qt.FastTransformation)
            )

    def show_pdf(self, file_path):
        """Shows a PDF on the ui.pdf_viewer QWebEngineView, hiding the other display widgets."""
        self.ui.image_viewer.hide()
        self.ui.text_viewer.hide()
        self.ui.plot_frame.hide()
        self.ui.pdf_viewer.show()
        self.ui.video_player.hide()

        # Stop any existing video playback
        if hasattr(self, 'media_player'):
            try:
                self.media_player.stop()
                self.media_player.setSource(QUrl())
            except Exception:
                pass

        # Clear previous children from the container
        layout = self.ui.pdf_viewer.layout()
        if layout is None:
            layout = QVBoxLayout()
            self.ui.pdf_viewer.setLayout(layout)
        else:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        # Prefer QtPdf (QPdfView) when available for smooth scrolling and stable behavior
        try:
            from PySide6.QtPdf import QPdfDocument
            from PySide6.QtPdfWidgets import QPdfView

            self._pdf_document = QPdfDocument(self)
            load_status = self._pdf_document.load(file_path)
            # load() returns an enum or int; if it fails an Exception will typically be raised later
            self._pdf_view = QPdfView(self.ui.pdf_viewer)
            self._pdf_view.setDocument(self._pdf_document)
            # Prefer multi-page / continuous scrolling if available; fall back silently if not.
            try:
                # Try common page mode enums — use MultiPage if present, otherwise try Continuous.
                try:
                    self._pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
                except Exception:
                    try:
                        self._pdf_view.setPageMode(QPdfView.PageMode.Continuous)
                    except Exception:
                        pass

                # Keep FitInView zoom when available
                try:
                    self._pdf_view.setZoomMode(self._pdf_view.ZoomMode.FitInView)
                except Exception:
                    pass
            except Exception:
                # Any unexpected API differences are ignored; default view will be used.
                pass
            layout.addWidget(self._pdf_view)
            layout.setContentsMargins(0, 0, 0, 0)
            self._pdf_view.show()
            self.print(self.tr(f'Loading PDF (QPdfView): {os.path.basename(file_path)}'))
            return
        except Exception:
            # QtPdf not available or failed — fall back to QWebEngineView below
            pass

        # Fallback: use QWebEngineView but ensure a safe widget name and focus
        if QWebEngineView is None:
            self.print(
                f'Could not display the PDF with QtPdf and QtWebEngine is not available: '
                f'{os.path.basename(file_path)}')
            self.ui.pdf_viewer.hide()
            return
        try:
            web_view = QWebEngineView(self.ui.pdf_viewer)
            # Enable plugins if available to help with embedded PDF viewers
            try:
                from PySide6.QtWebEngineCore import QWebEngineSettings
                web_view.settings().setAttribute(QWebEngineSettings.PluginsEnabled, True)
            except Exception:
                pass

            web_view.setUrl(QUrl.fromLocalFile(file_path))
            layout.addWidget(web_view)
            layout.setContentsMargins(0, 0, 0, 0)
            web_view.show()
            web_view.setFocus()
            self._web_pdf_view = web_view
            self.print(self.tr(f'Loading PDF (QWebEngineView): {os.path.basename(file_path)}'))
        except Exception as e:
            self.print(f"Error loading PDF:\n{str(e)}")
            self.ui.pdf_viewer.hide()

    def show_text_file(self, file_path):
        """Shows a text file on the ui.text_viewer QTextBrowser, hiding the other display widgets."""
        self.ui.image_viewer.hide()
        self.ui.text_viewer.show()
        self.ui.plot_frame.hide()
        self.ui.pdf_viewer.hide()
        self.ui.video_player.hide()

        try:
            if hasattr(self, 'frame_timer') and self.frame_timer is not None:
                self.frame_timer.stop()
            if hasattr(self, 'media_player'):
                self.media_player.stop()
                self.media_player.setSource(QUrl())

            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                self.ui.text_viewer.setPlainText(content)
        except Exception as e:
            self.print(f"Error loading text file:\n{str(e)}")
            self.ui.text_viewer.hide()

    def toggle_play_pause(self):
        """Toggle between play and pause"""
        if self.media_player.isPlaying():
            self.media_player.pause()
            self.play_button.setIcon(icon_loader.get_icon('play', icon_loader.glyph_color(), 14))
        else:
            self.media_player.play()
            self.play_button.setIcon(icon_loader.get_icon('pause', icon_loader.glyph_color(), 14))

    def set_position(self, position):
        """Set media player position when slider is moved"""
        self.media_player.setPosition(position)

    def update_duration(self, duration):
        """Update slider max when duration changes"""
        self.progress_slider.setMaximum(duration)

    def update_position(self, position):
        """Update slider and time label"""
        if not self.progress_slider.isSliderDown():
            self.progress_slider.setValue(position)

        # Update time label
        current = position // 1000
        duration = self.media_player.duration() // 1000
        current_time = f"{current // 60:02d}:{current % 60:02d}"
        total_time = f"{duration // 60:02d}:{duration % 60:02d}"
        self.time_label.setText(f"{current_time} / {total_time}")






############################################################################################################

def get_resource_base():
    """Root under which bundled resources (assets/, scripts/, schemas/) live.

    When frozen by PyInstaller these are unpacked under sys._MEIPASS (the
    _internal/ folder next to the executable for a onedir build); in development
    they sit at the project root, one level above src/.
    """
    if getattr(sys, 'frozen', False):
        # Running as bundled executable
        return sys._MEIPASS
    # Running as script
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_asset_path():
    """Get the path to the assets folder, handling both development and PyInstaller bundled versions"""
    return os.path.join(get_resource_base(), 'assets')


def get_user_config_dir():
    """Writable, per-user directory for app settings (created on first use)."""
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
        path = os.path.join(base, 'NeuroCrunch')
    elif sys.platform == 'darwin':
        path = os.path.expanduser('~/Library/Application Support/NeuroCrunch')
    else:
        path = os.path.expanduser('~/.config/NeuroCrunch')
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def load_settings():
    """Load persisted user settings ({} on any failure)."""
    path = os.path.join(get_user_config_dir(), SETTINGS_FILENAME)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(settings):
    """Persist *settings* to the user config directory (best effort)."""
    path = os.path.join(get_user_config_dir(), SETTINGS_FILENAME)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def toggle_fullscreen(window):
    """Toggle fullscreen mode"""
    if window.isFullScreen():
        window.showMaximized()
    else:
        window.showFullScreen()


if __name__ == "__main__":
    # Enable shared OpenGL contexts for better performance
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)

    # Create the application instance
    app = QApplication(sys.argv)

    # Get asset path
    asset_path = get_asset_path()

    # Application/window icon.
    icon_path = os.path.join(asset_path, 'icons', 'app_icon.ico')
    app_icon = QIcon(icon_path) if os.path.exists(icon_path) else None
    if app_icon is not None:
        app.setWindowIcon(app_icon)

    # Create main window
    window = NeuroCrunch()
    window.setWindowTitle("NeuroCrunch")
    if app_icon is not None:
        window.setWindowIcon(app_icon)


    # Initialize dark mode manager
    dark_mode_manager = DarkModeManager(app, window, asset_path)

    # Connect dark mode button
    window.ui.btn_darkmode.clicked.connect(dark_mode_manager.toggle_dark_mode)

    # Setup fullscreen toggle with F11
    fullscreen_shortcut = QShortcut(QKeySequence(Qt.Key_F11), window)
    fullscreen_shortcut.activated.connect(lambda: toggle_fullscreen(window))

    # Set the window size to full screen
    # window.showMaximized()
    window.show()

    # Start with dark mode enabled
    dark_mode_manager.toggle_dark_mode()

    # Start the application event loop
    sys.exit(app.exec())
