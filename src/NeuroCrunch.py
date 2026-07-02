# This Python file uses the following encoding: utf-8
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

# Keep startup simple: do not attempt to silence FFmpeg/Libav messages here.
# Warnings from underlying libraries will appear on the terminal.
warnings.filterwarnings('ignore')

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTreeWidgetItem, QTableWidgetItem, QMenu, QVBoxLayout, QLineEdit,
    QHBoxLayout, QPushButton, QSlider, QLabel, QWidget, QDialog, QSpinBox, QMessageBox, QCheckBox
)
from PySide6.QtCore import QCoreApplication, QUrl, Qt, QTimer, QThread, Signal
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut, QTextCursor
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWebEngineWidgets import QWebEngineView

from tkinter.filedialog import askopenfilename, askdirectory, asksaveasfilename

from mainwindow import Ui_MainWindow
from dark_mode_manager import DarkModeManager


MAX_PLOT_COLUMNS = 100  # Maximum number of columns allowed to plot at once


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
            self.progress_updated.emit(f'Abriendo CSV {filename}: 0%')
            
            if self.file_path.lower().endswith('.csv'):
                chunks = []
                total_rows = 0
                for i, chunk in enumerate(pd.read_csv(self.file_path, chunksize=10000)):
                    chunks.append(chunk)
                    total_rows += len(chunk)
                    progress = int((total_rows / max(total_rows, 1)) * 100)
                    self.progress_updated.emit(f'Abriendo CSV {filename}: {progress}%')
                
                if chunks:
                    data = pd.concat(chunks, ignore_index=True)
                else:
                    data = pd.read_csv(self.file_path)
                    
            elif self.file_path.lower().endswith(('.xls', '.xlsx')):
                self.progress_updated.emit(f'Abriendo archivo {filename}: 0%')
                data = pd.read_excel(self.file_path)
                self.progress_updated.emit(f'Abriendo archivo {filename}: 100%')
            else:
                raise ValueError('Formato de archivo no soportado para gráficos.')
            
            self.data_loaded.emit(data)
        except Exception as e:
            self.error_occurred.emit(str(e))


class NeuroCrunch(QMainWindow):
    def __init__(self):
        super(NeuroCrunch, self).__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)


        # Set all viewers to hidden initially
        self.ui.image_viewer.hide()
        self.ui.text_viewer.hide()
        self.ui.plot_frame.hide()
        self.ui.pdf_viewer.hide()
        self.ui.video_player.hide()

        # Default to the application directory as the local folder
        self.local_folder = os.path.dirname(os.path.abspath(__file__))
        # Relative to the application directory, the "scripts" folder is expected to be at "../scripts"
        self.scripts_folder = os.path.join(self.local_folder, '..', 'scripts')
        self.scripts = self.get_dir_content(self.scripts_folder) if os.path.exists(self.scripts_folder) else []
        self.config = {}

        # Refresh the file viewer and scripts table with the initial local folder and scripts
        self.refresh_local_folder()
        self.refresh_scripts_table()

        self.plot_color_palette = ['b', 'g', 'r', 'c', 'm', 'y', 'k']
        

        # ...


        # Button connections
        self.ui.btn_open_folder.clicked.connect(self.select_local_folder)
        self.ui.btn_refresh.clicked.connect(self.refresh_local_folder)

        # File viewer context menu
        self.ui.file_viewer.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ui.file_viewer.customContextMenuRequested.connect(self.show_file_context_menu)        
        self.ui.file_viewer.itemDoubleClicked.connect(self.on_file_viewer_double_clicked)

        
        self.print('Programa inicializado - ' + datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S'))



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
        selected_folder = askdirectory(title='Seleccionar carpeta local')
        if selected_folder:
            self.local_folder = selected_folder
            self.ui.file_viewer.setHeaderLabel(self.local_folder)
            self.refresh_local_folder()
        
    def refresh_local_folder(self):
        self.ui.file_viewer.clear()
        if not self.local_folder:
            self.print('No se seleccionó ninguna carpeta local.')
            return
        if not os.path.exists(self.local_folder):
            self.print(f'La carpeta local "{self.local_folder}" no existe.')
            return
        
        content = self.get_dir_content(self.local_folder)
        self.populate_file_viewer(content, self.ui.file_viewer.invisibleRootItem(), self.local_folder)
                
    def get_dir_content(self, path):
        """Get the content of a directory recursively, returning a tree structure.
        Returns a list where items are either:
        - Tuples: (folder_name, folder_contents) for directories
        - Strings: filename for files
        """
        content = []

        if os.path.isfile(path):
            raise ValueError(f'El path "{path}" es un archivo, se esperaba una carpeta.')
        if not os.path.exists(path):
            raise ValueError(f'La carpeta "{path}" no existe.')
        
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
        open_action = menu.addAction("Abrir")
        open_action.triggered.connect(lambda: self.on_file_viewer_double_clicked(item, 0))
        
        menu.addSeparator()
        
        # Open in location action
        open_location_action = menu.addAction("Mostrar en carpeta")
        open_location_action.triggered.connect(lambda: self.open_in_file_explorer(file_path))
        
        menu.exec(self.ui.file_viewer.mapToGlobal(position))

    def open_in_file_explorer(self, file_path):
        """Open file or folder in system file explorer"""
        if not os.path.exists(file_path):
            self.print(f'El archivo/carpeta "{file_path}" no existe.')
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
            
            self.print(f'Abriendo en explorador de archivos: {file_path}')
        except Exception as e:
            self.print(f'Error al abrir explorador: {str(e)}')



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

                # Text files
                else:
                    self.show_text_file(file_path)
            except Exception as e:
                self.print(f"Error al abrir el archivo:\n{str(e)}")

    def show_column_range_dialog(self, total_columns):
        """Show a dialog to let user select column range. Returns (start_col, end_col) or None if cancelled."""
        max_selectable = min(MAX_PLOT_COLUMNS, total_columns)
        dialog = QDialog(self)
        dialog.setWindowTitle('Seleccionar rango de columnas')
        dialog.setModal(True)
        
        layout = QVBoxLayout()
        
        # Add description
        desc_label = QLabel(f'Total de columnas: {total_columns}\nMáximo permitido: {max_selectable}\n')
        layout.addWidget(desc_label)
        
        # Start column spinbox
        start_label = QLabel('Columna inicial (0-indexed):')
        self.start_spin = QSpinBox()
        self.start_spin.setMinimum(0)
        self.start_spin.setMaximum(total_columns - 1)
        self.start_spin.setValue(0)
        layout.addWidget(start_label)
        layout.addWidget(self.start_spin)
        
        # End column spinbox
        end_label = QLabel(f'Columna final (0-indexed, max +{max_selectable} desde inicio):')
        self.end_spin = QSpinBox()
        self.end_spin.setMinimum(0)
        self.end_spin.setMaximum(total_columns - 1)
        self.end_spin.setValue(min(max_selectable - 1, total_columns - 1))
        layout.addWidget(end_label)
        layout.addWidget(self.end_spin)
        
        # Buttons
        button_layout = QHBoxLayout()
        ok_button = QPushButton('OK')
        cancel_button = QPushButton('Cancelar')
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
                QMessageBox.warning(self, 'Error', 'La columna final debe ser >= columna inicial')
                return None
            
            if (end - start + 1) > MAX_PLOT_COLUMNS:
                QMessageBox.warning(self, 'Error', f'No se pueden plotear más de {MAX_PLOT_COLUMNS} columnas')
                return None
            
            return (start, end)
        return None

    def refresh_scripts_table(self):
        """
            Refreshes the table_data_columns table with the current list of scripts and their config. 
            
            Columns are:
                - Script name
                - Last modification timestamp
                - Checkbox to enable/disable script execution

            self.config: Dictionary where keys are script names and values are dictionaries with script configuration, including:
                - 'ejecutar': bool indicating if the script is enabled
                - 'parametros': dict of parameter names and their current values
                - 'ultima_modificacion': timestamp of last modification of the config for this script

            If the script name is not in self.config, it will be added with default values (ejecutar=False, empty parametros, current timestamp).
        
        """
        self.ui.table_data_columns.setRowCount(0)
        self.ui.table_data_columns.setColumnWidth(0, 140)
        self.ui.table_data_columns.setColumnWidth(1, 140)
        self.ui.table_data_columns.setColumnWidth(2, 60)
        self.ui.table_data_columns.setColumnWidth(3, 60)

        for script in self.scripts:
            if script not in self.config:
                self.config[script] = {
                    'ejecutar': False,
                    'parametros': {},
                    'ultima_modificacion': datetime.datetime.now().strftime('%Y/%m/%d - %H:%M'),
                    'orden_ejecucion': None
                }
            
            row_position = self.ui.table_data_columns.rowCount()
            self.ui.table_data_columns.insertRow(row_position)

            # Script name
            script_item = QTableWidgetItem()
            script_item.setText(script)
            self.ui.table_data_columns.setItem(row_position, 0, script_item)

            # Last modification timestamp
            timestamp_item = QTableWidgetItem()
            timestamp_item.setText(self.config[script]['ultima_modificacion'])
            timestamp_item.setTextAlignment(Qt.AlignCenter)
            self.ui.table_data_columns.setItem(row_position, 1, timestamp_item)

            # Checkbox for execution
            checkbox = QCheckBox()
            checkbox.setCheckState(Qt.Checked if self.config[script]['ejecutar'] else Qt.Unchecked)
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(checkbox)
            self.ui.table_data_columns.setCellWidget(row_position, 2, container)

            # Order of execution
            order_item = QTableWidgetItem()
            order_item.setTextAlignment(Qt.AlignCenter)
            order_text = str(self.config[script]['orden_ejecucion']) if self.config[script]['orden_ejecucion'] is not None else '-'
            order_item.setText(order_text)
            self.ui.table_data_columns.setItem(row_position, 3, order_item)







    def show_image(self, file_path):
        """Shows an image on the ui.image_viewer QLabel, hiding the other display widgets."""
        # Stop any existing video playback
        if hasattr(self, 'media_player'):
            self.media_player.stop()
            self.media_player.setSource(QUrl())
        
        self.ui.image_viewer.setPixmap(QPixmap(file_path).scaled(self.ui.image_viewer.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.ui.image_viewer.show()
        self.ui.text_viewer.hide()
        self.ui.plot_frame.hide()
        self.ui.pdf_viewer.hide()
        self.ui.video_player.hide()
       

    def show_plot(self, file_path):
        """Shows a plot on the ui.plot_viewer pyqtgraph widget, hiding the other display widgets."""
        # Stop any existing video playback
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
        self.csv_reader.progress_updated.connect(self._on_csv_progress)
        self.csv_reader.data_loaded.connect(self._on_csv_loaded)
        self.csv_reader.error_occurred.connect(self._on_csv_error)
        self.csv_reader.start()
    
    def _on_csv_progress(self, message):
        """Update progress in log."""
        self.print_progress(message)
    
    def _on_csv_error(self, error_msg):
        """Handle CSV loading error."""
        self.print(f"Error al cargar datos para gráfico:\n{error_msg}")
    
    def _on_csv_loaded(self, data):
        """Handle CSV loaded from background thread."""
        
        self.print(f'Cargado: {len(data)} filas, {len(data.columns)} columnas')     
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
        desc_label = QLabel(f'Total de columnas: {total_columns}\nMáximo permitido: {max_selectable}\n')
        columns_layout.addWidget(desc_label)

        # Regex finder for column names
        regex_label = QLabel('Columnas que incluyan:')
        self.regex_input = QLineEdit()
        columns_layout.addWidget(regex_label)
        columns_layout.addWidget(self.regex_input)

        # Start column spinbox
        start_label = QLabel('Columna inicial:')
        self.start_spin = QSpinBox()
        self.start_spin.setMinimum(0)
        self.start_spin.setMaximum(total_columns - 1)
        self.start_spin.setValue(0)
        columns_layout.addWidget(start_label)
        columns_layout.addWidget(self.start_spin)
        
        # End column spinbox
        end_label = QLabel(f'Columna final:')
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
                self.print(f"Advertencia: No se pudo crear la leyenda interactiva:\n{str(e)}")
                legend = None

            # Plot selected columns and save references
            for i, column in enumerate(columns_to_plot):
                pen = self.plot_color_palette[i % len(self.plot_color_palette)]
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
            self.print(f"Error al cargar datos para gráfico:\n{str(e)}")
            self.ui.plot_widget.clear()
       
    def show_video(self, file_path):
        """Shows a video on the ui.video_player QMediaPlayer/QVideoWidget with controls."""
        self.ui.image_viewer.hide()
        self.ui.text_viewer.hide()
        self.ui.plot_frame.hide()
        self.ui.pdf_viewer.hide()
        self.ui.video_player.show()

        try:
            # Stop any existing video playback
            if hasattr(self, 'media_player'):
                self.media_player.stop()
                self.media_player.setSource(QUrl())
            
            # Clear previous widgets
            for child in self.ui.video_player.findChildren(QVideoWidget):
                child.deleteLater()
            for child in self.ui.video_player.findChildren(QPushButton):
                child.deleteLater()
            for child in self.ui.video_player.findChildren(QSlider):
                child.deleteLater()
            for child in self.ui.video_player.findChildren(QLabel):
                child.deleteLater()

            # Create main layout
            layout = self.ui.video_player.layout()
            if layout is None:
                layout = QVBoxLayout()
                self.ui.video_player.setLayout(layout)
            else:
                while layout.count():
                    layout.takeAt(0)

            # Create video widget and media player
            self.video_widget = QVideoWidget()
            self.media_player = QMediaPlayer(self)
            self.media_player.setVideoOutput(self.video_widget)

            # Create control bar
            control_widget = QWidget()
            control_layout = QHBoxLayout(control_widget)
            control_layout.setContentsMargins(0, 2, 0, 2)
            control_layout.setSpacing(3)

            # Play/Pause button
            self.play_button = QPushButton("▶")
            self.play_button.setMaximumWidth(30)
            self.play_button.setMaximumHeight(22)
            self.play_button.clicked.connect(self.toggle_play_pause)
            control_layout.addWidget(self.play_button)

            # Progress slider
            self.progress_slider = QSlider(Qt.Horizontal)
            self.progress_slider.setMinimum(0)
            self.progress_slider.sliderMoved.connect(self.set_position)
            self.media_player.durationChanged.connect(self.update_duration)
            self.media_player.positionChanged.connect(self.update_position)
            control_layout.addWidget(self.progress_slider, 1)

            # Time label
            self.time_label = QLabel("00:00 / 00:00")
            self.time_label.setMinimumWidth(85)
            self.time_label.setMaximumHeight(22)
            self.time_label.setStyleSheet("font-size: 10px;")
            control_layout.addWidget(self.time_label)

            # Add widgets to main layout - video takes most space
            layout.addWidget(self.video_widget, 1)
            layout.addWidget(control_widget, 0)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            # Load and play video - suppress FFmpeg C library warnings by redirecting stderr at OS level
            try:
                # Save original stderr file descriptor
                old_stderr_fd = os.dup(2)
                # Open null device
                null_fd = os.open(os.devnull, os.O_WRONLY)
                # Redirect stderr (fd 2) to null device
                os.dup2(null_fd, 2)
                
                try:
                    self.media_player.setSource(QUrl.fromLocalFile(file_path))
                    self.media_player.play()
                finally:
                    # Restore original stderr
                    os.dup2(old_stderr_fd, 2)
                    os.close(old_stderr_fd)
                    os.close(null_fd)
            except:
                # Fallback: just load normally if fd redirection fails
                self.media_player.setSource(QUrl.fromLocalFile(file_path))
                self.media_player.play()
            
            self.play_button.setText("||")
            self.print(f'Reproduciendo video: {os.path.basename(file_path)}')

        except Exception as e:
            self.print(f"Error al cargar video:\n{str(e)}")
            self.ui.video_player.hide()

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
            self.print(f'Cargando PDF (QPdfView): {os.path.basename(file_path)}')
            return
        except Exception:
            # QtPdf not available or failed — fall back to QWebEngineView below
            pass

        # Fallback: use QWebEngineView but ensure a safe widget name and focus
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
            self.print(f'Cargando PDF (QWebEngineView): {os.path.basename(file_path)}')
        except Exception as e:
            self.print(f"Error al cargar PDF:\n{str(e)}")
            self.ui.pdf_viewer.hide()

    def show_text_file(self, file_path):
        """Shows a text file on the ui.text_viewer QTextBrowser, hiding the other display widgets."""
        self.ui.image_viewer.hide()
        self.ui.text_viewer.show()
        self.ui.plot_frame.hide()
        self.ui.pdf_viewer.hide()
        self.ui.video_player.hide()

        try:
            # Stop any existing video playback
            if hasattr(self, 'media_player'):
                self.media_player.stop()
                self.media_player.setSource(QUrl())
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                self.ui.text_viewer.setPlainText(content)
        except Exception as e:
            self.print(f"Error al cargar archivo de texto:\n{str(e)}")
            self.ui.text_viewer.hide()

    def toggle_play_pause(self):
        """Toggle between play and pause"""
        if self.media_player.isPlaying():
            self.media_player.pause()
            self.play_button.setText("▶")
        else:
            self.media_player.play()
            self.play_button.setText("||")

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

def get_asset_path():
    """Get the path to the assets folder, handling both development and PyInstaller bundled versions"""
    if getattr(sys, 'frozen', False):
        # Running as bundled executable
        applicationPath = sys._MEIPASS
    else:
        # Running as script
        applicationPath = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    return os.path.join(applicationPath, 'assets')


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
    
    # Set icon with fixed aspect ratio
    icon_path = os.path.join(asset_path, 'icons', 'icon.ico')
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    # Create main window
    window = NeuroCrunch()
    window.setWindowTitle("NeuroCrunch")

    
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