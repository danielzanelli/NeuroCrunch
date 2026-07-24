# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""NeuroCrunch - Main Application"""
import datetime
import os
import sys
import subprocess
import json
import warnings

# Keep startup simple: do not attempt to silence FFmpeg/Libav messages here.
# Warnings from underlying libraries will appear on the terminal.
warnings.filterwarnings('ignore')

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTreeWidgetItem, QTableWidgetItem, QMenu,
    QHBoxLayout, QWidget, QDialog, QMessageBox, QComboBox, QCheckBox, QLabel
)
from PySide6.QtCore import QCoreApplication, QUrl, Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QShortcut, QTextCursor, QDesktopServices

from tkinter.filedialog import askopenfilename, askdirectory, asksaveasfilename

from mainwindow import Ui_MainWindow
import icon_loader
from dark_mode_manager import DarkModeManager
from plugin_manager import PluginManager
from param_dialog import ParamDialog
from graph_viewer import GraphViewer
from viewers import viewer_for, VideoViewer, TextViewer
from script_runner import PipelineContext, ScriptRunner
from updater import read_current_version, UpdateChecker, UpdateDownloader, apply_update


# Source language of the codebase; selected when no translator is needed.
DEFAULT_LANGUAGE = 'en'
# (code, display name) pairs offered in the preferences dialog. Display names
# are shown in their own language, so they are intentionally not translated.
AVAILABLE_LANGUAGES = [
    ('en', 'English'),
    ('es', 'Español'),
]
SETTINGS_FILENAME = 'settings.json'


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


        # Central pane: one tab per open file. The stack shows the empty-state
        # hint instead whenever no file is open.
        self._viewers = {}  # normalised path -> viewer widget
        self.ui.viewer_placeholder.setText(self.tr('Double-click a file to preview it'))
        self.ui.viewer_tabs.tabCloseRequested.connect(self.close_tab)
        self.ui.viewer_tabs.currentChanged.connect(self._on_tab_changed)
        self._active_viewer = None
        close_tab_shortcut = QShortcut(QKeySequence.Close, self)  # Ctrl+W
        close_tab_shortcut.activated.connect(
            lambda: self.close_tab(self.ui.viewer_tabs.currentIndex()))

        # Default to the last folder the user browsed, falling back to the
        # user's home directory on first launch.
        self.local_folder = self.settings.get('local_folder') or os.path.expanduser('~')
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
        # directory that is cleaned up after each pipeline execution; outputs
        # survive across runs via self.config['__outputs__'].
        self.pipeline_context_store = self._new_pipeline_context()
        self._script_runner = None

        # Refresh the file viewer and scripts table with the initial local folder and scripts
        self.refresh_local_folder()
        self.refresh_scripts_table()

        # Surface any manifest/plugin issues found during discovery in the log
        for warning in self.plugin_manager.warnings:
            self.print(warning)

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
        # Folders load their children lazily, the first time they are expanded.
        self.ui.file_viewer.itemExpanded.connect(self.on_item_expanded)

        # Scripts table — double-click a row to open the parameter configuration dialog
        self.ui.table_data_columns.cellDoubleClicked.connect(self.open_param_dialog)
        # Note: checkbox changes are now handled by individual QCheckBox widgets


        self.print(self.tr('Program initialized') + ' - ' + datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S'))

        # Permanent version label in the status-bar corner (same version.json the
        # updater reads). Sits alongside the transient update/progress messages.
        version = read_current_version(
            os.path.join(get_resource_base(), 'version.json')).get('version', '')
        if version:
            self.statusBar().addPermanentWidget(QLabel(f'v{version}'))

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
        self.ui.viewer_placeholder.setText(self.tr('Double-click a file to preview it'))
        for viewer in self.open_viewers():
            viewer.retranslate()

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

    def _set_local_folder(self, folder):
        """Point the file viewer at *folder* and remember it across sessions."""
        self.local_folder = folder
        self.ui.file_viewer.setHeaderLabel(folder)
        self.settings['local_folder'] = folder
        save_settings(self.settings)

    def select_local_folder(self):
        selected_folder = askdirectory(title=self.tr('Select local folder'))
        if selected_folder:
            self._set_local_folder(selected_folder)
            # Create a new pipeline context with temporary directory
            self.pipeline_context_store.cleanup()
            self.pipeline_context_store = self._new_pipeline_context()
            self.refresh_local_folder()

    def refresh_local_folder(self):
        self.ui.file_viewer.clear()
        if not self.local_folder:
            self.print(self.tr('No local folder selected.'))
            return
        if not os.path.exists(self.local_folder):
            self.print(self.tr('Local folder "{0}" does not exist.').format(self.local_folder))
            return

        self._populate_dir(self.ui.file_viewer.invisibleRootItem(), self.local_folder)

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
            self.print(self.tr('Could not create user plugins folder "{0}": {1}').format(path, str(e)))

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
            self.print(self.tr('Could not open scripts folder "{0}": {1}').format(path, str(e)))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        self.print(self.tr('User scripts folder: {0}').format(path))

    def rescan_scripts(self):
        """Re-discover bundled + user scripts and refresh the scripts table.

        Lets newly added user scripts appear without restarting the app. Config
        for scripts that no longer exist is dropped.
        """
        self.plugins = self.plugin_manager.discover_scripts(self.scripts_folder, self.user_plugins_folder)
        self.scripts = sorted(self.plugins.keys())
        # Keep '__'-prefixed entries (e.g. '__outputs__') — they are app
        # state, not per-script config.
        self.config = {
            k: v for k, v in self.config.items()
            if k in self.plugins or k.startswith('__')
        }
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
        self.statusBar().showMessage(self.tr('NeuroCrunch {0} available').format(version))
        asset = release.get('asset')
        if not asset:
            QMessageBox.information(
                self, self.tr('Update available'),
                self.tr('There is a new version ({0}), but there is no installer for this platform.\nDownload it manually from:\n').format(version)
                + release.get("html_url", ""))
            return
        reply = QMessageBox.question(
            self, self.tr('Update available'),
            self.tr('A new version is available ({0}).\nDownload it now?').format(version))
        if reply == QMessageBox.Yes:
            self._start_update_download(asset)

    def _start_update_download(self, asset):
        url = asset.get('browser_download_url')
        name = asset.get('name')
        if not url or not name:
            self.print(self.tr('The update asset does not have a valid URL or name.'))
            return
        self.print(self.tr('Downloading update: {0}...').format(name))
        self._update_downloader = UpdateDownloader(url, name)
        self._update_downloader.progress.connect(
            lambda pct: self.statusBar().showMessage(self.tr('Downloading update: {0}%').format(pct)))
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
            # The updater script is now waiting on this process: the installer
            # cannot replace the exe until every NeuroCrunch process is gone.
            # QApplication.quit() only asks the event loop to unwind, and a slow
            # or stuck teardown (background QThreads, Qt/OpenGL cleanup) leaves
            # the exe locked long enough for the installer to raise its blocking
            # "files in use" dialog. Hide the window for immediate feedback, then
            # end the process outright — there is no unsaved state at this point
            # and a guaranteed exit is what keeps the update unattended.
            self.hide()
            QApplication.processEvents()
            os._exit(0)

    def _populate_dir(self, parent_item, path):
        """List a single level of *path* into *parent_item*.

        Only the immediate children are read; sub-folders are filled in
        lazily the first time they are expanded (see on_item_expanded).
        This keeps startup fast regardless of how large the tree is.
        """
        try:
            items = os.listdir(path)
        except (PermissionError, OSError):
            return

        # Sort items: folders first, then files
        folders = sorted([i for i in items if os.path.isdir(os.path.join(path, i))])
        files = sorted([i for i in items if os.path.isfile(os.path.join(path, i))])

        for folder in folders:
            full_path = os.path.join(path, folder)
            dir_item = QTreeWidgetItem(parent_item)
            dir_item.setText(0, folder)
            dir_item.setIcon(0, icon_loader.icon_for_file(folder, is_dir=True))
            dir_item.setData(0, Qt.UserRole, full_path)
            # False marks a folder whose children are not loaded yet.
            dir_item.setData(0, Qt.UserRole + 1, False)
            # Show expand arrow without having read the folder's contents.
            dir_item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)

        for file in files:
            file_item = QTreeWidgetItem(parent_item)
            file_item.setText(0, file)
            file_item.setIcon(0, icon_loader.icon_for_file(file))
            file_item.setData(0, Qt.UserRole, os.path.join(path, file))

    def on_item_expanded(self, item):
        """Populate a folder's children the first time it is expanded."""
        # Only unloaded folders carry a False flag; files/loaded folders skip.
        if item.data(0, Qt.UserRole + 1) is not False:
            return
        item.setData(0, Qt.UserRole + 1, True)
        self._populate_dir(item, item.data(0, Qt.UserRole))

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
            self.print(self.tr('The file/folder "{0}" does not exist.').format(file_path))
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

            self.print(self.tr('Opening in file explorer: {0}').format(file_path))
        except Exception as e:
            self.print(self.tr('Error opening file explorer: {0}').format(str(e)))



    def on_file_viewer_double_clicked(self, item, column):
        """Open the double-clicked file in a tab (folders expand via the arrow)."""
        file_path = item.data(0, Qt.UserRole)
        if file_path and os.path.isfile(file_path):
            self.open_file(file_path)

    def open_file(self, file_path):
        """Show *file_path* in the central tab area, focusing it if already open.

        ROI zips are not files with a viewer of their own: they are an overlay
        for the video in the current tab.
        """
        try:
            current = self.current_viewer()
            if file_path.lower().endswith('.zip') and isinstance(current, VideoViewer):
                current.load_roi(file_path)
                return

            existing = self._viewers.get(_viewer_key(file_path))
            if existing is not None:
                self.ui.viewer_tabs.setCurrentWidget(existing)
                return

            self._add_tab(file_path, viewer_for(file_path))
        except Exception as e:
            self.print(self.tr('Error opening the file:\n{0}').format(str(e)))

    def _add_tab(self, file_path, viewer, index=None):
        """Add *viewer* as a tab for *file_path*, make it current and load it."""
        viewer.progress_changed.connect(self._on_viewer_progress)
        viewer.log_message.connect(self.print)
        viewer.load_done.connect(
            lambda ok, message, v=viewer: self._on_viewer_load_done(v, ok, message))

        name = os.path.basename(file_path)
        icon = icon_loader.icon_for_file(name)
        if index is None:
            index = self.ui.viewer_tabs.addTab(viewer, icon, name)
        else:
            self.ui.viewer_tabs.insertTab(index, viewer, icon, name)
        self.ui.viewer_tabs.setTabToolTip(index, file_path)
        self._viewers[_viewer_key(file_path)] = viewer

        self.ui.viewer_stack.setCurrentWidget(self.ui.viewer_tabs)
        self.ui.viewer_tabs.setCurrentWidget(viewer)
        viewer.apply_theme(self._is_dark_mode())
        viewer.load(file_path)

    def close_tab(self, index):
        """Close the tab at *index*, releasing the resources it holds."""
        viewer = self.ui.viewer_tabs.widget(index)
        if viewer is None:
            return
        viewer.release()
        for key, open_viewer in list(self._viewers.items()):
            if open_viewer is viewer:
                del self._viewers[key]
        if viewer is self._active_viewer:
            self._active_viewer = None
        self.ui.viewer_tabs.removeTab(index)
        viewer.deleteLater()
        if self.ui.viewer_tabs.count() == 0:
            self.ui.viewer_stack.setCurrentWidget(self.ui.placeholder_page)

    def current_viewer(self):
        """The viewer of the current tab, or None when no file is open."""
        return self.ui.viewer_tabs.currentWidget()

    def open_viewers(self):
        """Every open viewer, in tab order."""
        return [self.ui.viewer_tabs.widget(i) for i in range(self.ui.viewer_tabs.count())]

    def _on_tab_changed(self, index):
        """Let the viewers know which one is on screen (videos pause when left)."""
        previous, self._active_viewer = self._active_viewer, self.ui.viewer_tabs.widget(index)
        if previous is not None and previous is not self._active_viewer:
            previous.on_deactivated()
        if self._active_viewer is not None:
            self._active_viewer.on_activated()

    def _on_viewer_progress(self, message):
        """Live progress line from a viewer (replaces the last log line)."""
        self.print_progress(message)
        self.ui.log.repaint()

    def _on_viewer_load_done(self, viewer, ok, message):
        if message:
            self.print(message)
        if not ok and isinstance(viewer, GraphViewer):
            # The graph could not be parsed — fall back to the raw text in the
            # same tab so the file is still inspectable.
            self._replace_with_text_viewer(viewer)

    def _replace_with_text_viewer(self, viewer):
        index = self.ui.viewer_tabs.indexOf(viewer)
        if index < 0:
            return
        file_path = self.ui.viewer_tabs.tabToolTip(index)
        self.close_tab(index)
        self._add_tab(file_path, TextViewer(), index=index)

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
                        self.tr('Order {0} reassigned from "{1}": disabled.').format(
                            new_order, self.plugins[other_id].name
                        )
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
            self.print(self.tr('Configuration saved to: {0}').format(os.path.basename(file_path)))
        except Exception as e:
            self.print(self.tr('Error saving configuration: {0}').format(str(e)))

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
                self.print(self.tr('Error: the configuration file does not have the expected format.'))
                return
            # Restore the working directory if it was saved and still exists.
            saved_cwd = loaded.pop('__working_directory__', None)
            # Restore outputs from previous runs so linked parameters resolve.
            saved_outputs = loaded.pop('__outputs__', None)
            if isinstance(saved_outputs, dict):
                self.config['__outputs__'] = saved_outputs
                self.pipeline_context_store.seed(saved_outputs)
            # Merge: only update entries for known scripts; ignore stale keys
            for script_id, cfg in loaded.items():
                if script_id in self.scripts:
                    self.config[script_id] = cfg
            self.refresh_scripts_table()
            if saved_cwd and os.path.isdir(saved_cwd):
                self._set_local_folder(saved_cwd)
                self.refresh_local_folder()
                self.print(self.tr('Working folder restored: {0}').format(saved_cwd))
            self.print(self.tr('Configuration loaded from: {0}').format(os.path.basename(file_path)))
        except (OSError, json.JSONDecodeError) as e:
            self.print(self.tr('Error loading configuration: {0}').format(str(e)))

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
        current_links = self.config.get(script_id, {}).get('links', {})

        dialog = ParamDialog(
            plugin_info, current_values, self.pipeline_context_store.as_dict(), self,
            all_plugins=self.plugins, current_links=current_links, language=self.current_language,
        )
        if dialog.exec() == ParamDialog.DialogCode.Accepted:
            values = dialog.get_values()
            self.config[script_id]['parameters'] = values
            self.config[script_id]['links'] = dialog.get_links()
            self.config[script_id]['last_modified'] = datetime.datetime.now().strftime('%Y/%m/%d - %H:%M')
            self.print(self.tr('Parameters saved for "{0}"').format(plugin_info.name))
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

        links_by_script = {
            script_id: self.config.get(script_id, {}).get('links', {})
            for script_id, _info, _params in pipeline
            if self.config.get(script_id, {}).get('links')
        }
        self._script_runner = ScriptRunner(
            pipeline, self.pipeline_context_store, self, links_by_script=links_by_script
        )
        self._script_runner.log_message.connect(self._on_log_message)
        self._script_runner.progress_changed.connect(self._on_progress_changed)
        self._script_runner.script_started.connect(
            lambda script_id: self.print(self.tr('Starting script: {0}').format(self.plugins[script_id].name))
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
        self.statusBar().showMessage(self.tr('Progress: {0}%').format(percent))

    def _on_script_finished(self, script_id: str, success: bool) -> None:
        name = self.plugins[script_id].name
        if success:
            self.print(self.tr('Script "{0}" completed.').format(name))
        else:
            self.print(self.tr('Script "{0}" finished with an error.').format(name))

    def _on_pipeline_done(self, success: bool) -> None:
        self.ui.btn_execute_scripts.setEnabled(True)
        self.ui.btn_execute_scripts.setText(self.tr('Run'))
        self.ui.btn_execute_scripts.setIcon(icon_loader.get_icon('play', '#ffffff', 16))
        self.statusBar().clearMessage()
        self.print(self.tr('Pipeline completed successfully.') if success else self.tr('Pipeline completed with errors.'))
        # Persist the produced outputs so linked parameters resolve in later
        # runs and sessions, then recycle the temporary context directory.
        outputs = {k: dict(v) for k, v in self.pipeline_context_store.as_dict().items()}
        if outputs:
            self.config['__outputs__'] = outputs
        self.pipeline_context_store.cleanup()
        self.pipeline_context_store = self._new_pipeline_context()

    def _new_pipeline_context(self) -> PipelineContext:
        """Fresh temp-dir pipeline context, seeded with outputs from earlier runs."""
        context = PipelineContext()
        context.seed(self.config.get('__outputs__'))
        return context

    def _is_dark_mode(self):
        """Whether the app is currently in dark mode (defaults to dark)."""
        mgr = getattr(self, 'dark_mode_manager', None)
        return mgr.is_dark_mode if mgr is not None else True


############################################################################################################

def _viewer_key(file_path):
    """Identity of an open file: same file, same tab, however it was spelled."""
    return os.path.normcase(os.path.abspath(file_path))


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
    # Expose it so newly opened viewers can query the current theme.
    window.dark_mode_manager = dark_mode_manager

    # Connect dark mode button
    window.ui.btn_darkmode.clicked.connect(dark_mode_manager.toggle_dark_mode)

    # Setup fullscreen toggle with F11
    fullscreen_shortcut = QShortcut(QKeySequence(Qt.Key_F11), window)
    fullscreen_shortcut.activated.connect(lambda: toggle_fullscreen(window))

    
    # Set the window to  maximized state on startup
    window.showMaximized()


    window.show()

    # Start with dark mode enabled
    dark_mode_manager.toggle_dark_mode()

    # Start the application event loop
    sys.exit(app.exec())
