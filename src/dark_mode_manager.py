# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""Dark Mode Manager for NeuroCrunch"""
import os
import pyqtgraph as pg


class DarkModeManager:
    """Manages dark mode theme for the application"""
    
    def __init__(self, app, window, assets_path):
        """
        Initialize DarkModeManager
        
        Args:
            app: QApplication instance
            window: QMainWindow instance
            assets_path: Path to the assets folder
        """
        self.app = app
        self.window = window
        self.widget = window.ui
        self.assets_path = assets_path
        self.is_dark_mode = False
        
        # Load stylesheets from files
        self.dark_stylesheet = self._load_stylesheet('dark.qss')
        self.light_stylesheet = self._load_stylesheet('light.qss')
    
    def _load_stylesheet(self, filename):
        """Load stylesheet from file"""
        stylesheet_path = os.path.join(self.assets_path, 'styles', filename)
        try:
            with open(stylesheet_path, 'r') as f:
                return f.read()
        except FileNotFoundError:
            print(f"Warning: Stylesheet not found at {stylesheet_path}")
            return ""
    
    def toggle_dark_mode(self):
        """Toggle between dark and light mode"""
        self.is_dark_mode = not self.is_dark_mode
        
        if self.is_dark_mode:
            self.apply_dark_mode()
        else:
            self.apply_light_mode()
    
    def apply_dark_mode(self):
        """Apply dark mode stylesheet"""
        self.app.setStyle('Fusion')
        self.app.setStyleSheet(self.dark_stylesheet)
        self.widget.btn_darkmode.setText("☀️")
        # Configure pyqtgraph for dark mode
        self._configure_plot_dark()
    
    def apply_light_mode(self):
        """Apply light mode stylesheet"""
        self.app.setStyle('Fusion')
        self.app.setStyleSheet(self.light_stylesheet)
        self.widget.btn_darkmode.setText("🌙")
        # Configure pyqtgraph for light mode
        self._configure_plot_light()
    
    def _configure_plot_dark(self):
        """Configure plot widget for dark mode"""
        try:
            # primary plot widget used in older UI
            self.widget.graph_data.setBackground('#2d2d2d')
            self.widget.graph_data.getPlotItem().getAxis('bottom').setPen(pg.mkPen(color='#ffffff', width=1))
            self.widget.graph_data.getPlotItem().getAxis('left').setPen(pg.mkPen(color='#ffffff', width=1))
            self.widget.graph_data.getPlotItem().getAxis('bottom').setTextPen(pg.mkPen(color='#ffffff'))
            self.widget.graph_data.getPlotItem().getAxis('left').setTextPen(pg.mkPen(color='#ffffff'))
        except AttributeError:
            # Handle case where graph_data might not exist yet
            pass

        # Also configure the plot widget used in NeuroCrunch (`plot_widget`)
        try:
            self.widget.plot_widget.setBackground('#2d2d2d')
            self.widget.plot_widget.getPlotItem().getAxis('bottom').setPen(pg.mkPen(color='#ffffff', width=1))
            self.widget.plot_widget.getPlotItem().getAxis('left').setPen(pg.mkPen(color='#ffffff', width=1))
            self.widget.plot_widget.getPlotItem().getAxis('bottom').setTextPen(pg.mkPen(color='#ffffff'))
            self.widget.plot_widget.getPlotItem().getAxis('left').setTextPen(pg.mkPen(color='#ffffff'))
        except AttributeError:
            pass
        except AttributeError:
            # Handle case where graph_data might not exist yet
            pass
    
    def _configure_plot_light(self):
        """Configure plot widget for light mode"""
        try:
            # primary plot widget used in older UI
            self.widget.graph_data.setBackground('#ffffff')
            self.widget.graph_data.getPlotItem().getAxis('bottom').setPen(pg.mkPen(color='#000000', width=1))
            self.widget.graph_data.getPlotItem().getAxis('left').setPen(pg.mkPen(color='#000000', width=1))
            self.widget.graph_data.getPlotItem().getAxis('bottom').setTextPen(pg.mkPen(color='#000000'))
            self.widget.graph_data.getPlotItem().getAxis('left').setTextPen(pg.mkPen(color='#000000'))
        except AttributeError:
            # Handle case where graph_data might not exist yet
            pass

        # Also configure the plot widget used in NeuroCrunch (`plot_widget`)
        try:
            self.widget.plot_widget.setBackground('#ffffff')
            self.widget.plot_widget.getPlotItem().getAxis('bottom').setPen(pg.mkPen(color='#000000', width=1))
            self.widget.plot_widget.getPlotItem().getAxis('left').setPen(pg.mkPen(color='#000000', width=1))
            self.widget.plot_widget.getPlotItem().getAxis('bottom').setTextPen(pg.mkPen(color='#000000'))
            self.widget.plot_widget.getPlotItem().getAxis('left').setTextPen(pg.mkPen(color='#000000'))
        except AttributeError:
            pass
        except AttributeError:
            # Handle case where graph_data might not exist yet
            pass
