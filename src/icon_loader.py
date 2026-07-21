# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""Icon loader for NeuroCrunch.

Loads Lucide SVG icons (assets/icons/lucide, ISC license) and tints them at
runtime by replacing ``currentColor`` with a theme color, so a single set of
SVGs serves both dark and light modes. Rendered QIcons are cached per
(name, color, size).
"""
import os

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# Populated once by init_icons(); avoids passing the asset path everywhere.
_ICONS_DIR = None
_CACHE = {}

# Neutral glyph color per theme, kept in sync by DarkModeManager so widgets
# created later (video controls, dialogs) pick the right tint.
_GLYPH_COLORS = {'dark': '#b6bdc6', 'light': '#5b6572'}
_current_theme = 'dark'


def set_theme(dark):
    """Record the active theme ('dark' when *dark* is truthy)."""
    global _current_theme
    _current_theme = 'dark' if dark else 'light'


def glyph_color():
    """Neutral icon color for the active theme."""
    return _GLYPH_COLORS[_current_theme]

# Fixed hues for file-type icons in the tree — chosen to read well on both
# dark and light backgrounds (mid-lightness, saturated).
FILE_TYPE_COLORS = {
    'folder': '#e8b339',
    'image': '#b18cf2',
    'film': '#e06c75',
    'table': '#4cb782',
    'file-text': '#5ea1ef',
    'file-code': '#4cc2d9',
    'file-archive': '#c99a66',
    'braces': '#d19a66',
    'chart-line': '#4cb782',
    'waypoints': '#33b1a3',
    'file': '#8a919e',
}

# Extension → lucide icon name used by the file explorer tree.
_EXT_ICONS = {
    ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.svg'): 'image',
    ('.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.mpeg', '.mpg', '.webm', '.tif', '.tiff'): 'film',
    ('.csv', '.xls', '.xlsx'): 'table',
    ('.pdf', '.txt', '.md', '.log'): 'file-text',
    ('.py', '.m', '.r', '.jl'): 'file-code',
    ('.zip', '.gz', '.tar', '.7z', '.rar'): 'file-archive',
    ('.json', '.config', '.yaml', '.yml', '.toml'): 'braces',
    ('.jgf',): 'waypoints',
}


def init_icons(assets_path):
    """Point the loader at the assets folder. Call once at startup."""
    global _ICONS_DIR
    _ICONS_DIR = os.path.join(assets_path, 'icons', 'lucide')


def get_icon(name, color='#8a919e', size=20):
    """Return a tinted QIcon for the Lucide icon *name*.

    Falls back to an empty QIcon when the SVG is missing so callers never
    have to guard against packaging problems.
    """
    key = (name, color, size)
    if key in _CACHE:
        return _CACHE[key]

    pixmap = _render(name, color, size)
    icon = QIcon()
    if pixmap is not None:
        icon.addPixmap(pixmap, QIcon.Normal)
        # Dimmed variant so disabled buttons don't show full-strength glyphs
        disabled = _render(name, color, size, opacity=0.35)
        if disabled is not None:
            icon.addPixmap(disabled, QIcon.Disabled)
    _CACHE[key] = icon
    return icon


def icon_for_file(filename, is_dir=False):
    """Return the QIcon used in the file explorer for *filename*."""
    if is_dir:
        return get_icon('folder', FILE_TYPE_COLORS['folder'], 18)
    ext = os.path.splitext(filename)[1].lower()
    name = 'file'
    for exts, icon_name in _EXT_ICONS.items():
        if ext in exts:
            name = icon_name
            break
    return get_icon(name, FILE_TYPE_COLORS.get(name, FILE_TYPE_COLORS['file']), 18)


def _render(name, color, size, opacity=1.0):
    """Render the named SVG tinted with *color* into a pixmap (2x for HiDPI)."""
    if _ICONS_DIR is None:
        return None
    path = os.path.join(_ICONS_DIR, f'{name}.svg')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            svg = f.read()
    except OSError:
        return None

    svg = svg.replace('currentColor', color)
    renderer = QSvgRenderer(QByteArray(svg.encode('utf-8')))
    if not renderer.isValid():
        return None

    scale = 2  # render at 2x and mark the pixmap so HiDPI screens stay crisp
    image = QImage(size * scale, size * scale, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setOpacity(opacity)
    renderer.render(painter)
    painter.end()

    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(scale)
    return pixmap
