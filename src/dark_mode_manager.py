# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""Dark Mode Manager for NeuroCrunch"""
import os
import pyqtgraph as pg

import icon_loader

# pyqtgraph backgrounds matched to the viewer_frame color in each QSS theme
_PLOT_BG = {'dark': '#1a1e23', 'light': '#ffffff'}
_PLOT_AXIS = {'dark': '#9aa3ad', 'light': '#66707c'}


class DarkModeManager:
    """Manages dark/light theme for the application: stylesheet, icons and plots."""

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
        """Load stylesheet from file, resolving the @ICONS@ path token."""
        stylesheet_path = os.path.join(self.assets_path, 'styles', filename)
        try:
            with open(stylesheet_path, 'r', encoding='utf-8') as f:
                qss = f.read()
        except FileNotFoundError:
            print(f"Warning: Stylesheet not found at {stylesheet_path}")
            return ""
        # QSS url() paths must be absolute with forward slashes on Windows
        icons_dir = os.path.join(self.assets_path, 'icons', 'tinted').replace('\\', '/')
        return qss.replace('@ICONS@', icons_dir)

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
        icon_loader.set_theme(dark=True)
        self._apply_icons()
        self._configure_plot('dark')

    def apply_light_mode(self):
        """Apply light mode stylesheet"""
        self.app.setStyle('Fusion')
        self.app.setStyleSheet(self.light_stylesheet)
        icon_loader.set_theme(dark=False)
        self._apply_icons()
        self._configure_plot('light')

    def _apply_icons(self):
        """Re-tint all main-window button icons for the active theme."""
        glyph = icon_loader.glyph_color()
        ui = self.widget

        # Theme toggle shows the mode you would switch TO
        toggle_name = 'sun' if self.is_dark_mode else 'moon'
        ui.btn_darkmode.setIcon(icon_loader.get_icon(toggle_name, glyph, 18))
        ui.btn_refresh.setIcon(icon_loader.get_icon('refresh-cw', glyph, 16))
        ui.btn_open_folder.setIcon(icon_loader.get_icon('folder-open', glyph, 16))
        ui.btn_load_config.setIcon(icon_loader.get_icon('file-input', glyph, 16))
        ui.btn_save_config.setIcon(icon_loader.get_icon('save', glyph, 16))
        ui.btn_open_scripts_dir.setIcon(icon_loader.get_icon('folder-cog', glyph, 16))

        # Primary button keeps a white glyph on the accent background; show
        # the stop icon when a pipeline is currently running.
        runner = getattr(self.window, '_script_runner', None)
        running = runner is not None and runner.isRunning()
        ui.btn_execute_scripts.setIcon(
            icon_loader.get_icon('square' if running else 'play', '#ffffff', 16))

        # Video play/pause button exists only while a video is loaded
        play_btn = getattr(self.window, 'play_button', None)
        if play_btn is not None:
            try:
                player = getattr(self.window, 'media_player', None)
                playing = player is not None and player.isPlaying()
                play_btn.setIcon(
                    icon_loader.get_icon('pause' if playing else 'play', glyph, 14))
            except RuntimeError:
                pass  # widget already deleted

    def _configure_plot(self, theme):
        """Match the pyqtgraph plot to the active theme."""
        bg = _PLOT_BG[theme]
        axis = _PLOT_AXIS[theme]
        for attr in ('graph_data', 'plot_widget'):
            plot = getattr(self.widget, attr, None)
            if plot is None:
                continue
            try:
                plot.setBackground(bg)
                plot_item = plot.getPlotItem()
                for side in ('bottom', 'left'):
                    plot_item.getAxis(side).setPen(pg.mkPen(color=axis, width=1))
                    plot_item.getAxis(side).setTextPen(pg.mkPen(color=axis))
            except (AttributeError, RuntimeError):
                pass
