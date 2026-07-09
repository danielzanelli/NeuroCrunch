# This Python file uses the following encoding: utf-8
"""Lightweight tests for src/param_dialog.py non-GUI logic.

These tests do NOT require PySide6 or a running QApplication.  They
cover only the helper functions and pure-logic parts of the module by
providing minimal mocks for the Qt imports.  Run with:

    pytest tests/test_param_dialog.py
"""
import sys
import types
import os

# ---------------------------------------------------------------------------
# Mock PySide6 so the module imports without a Qt installation
# ---------------------------------------------------------------------------
def _make_qt_mock():
    """Build a minimal sys.modules mock for the PySide6 namespace."""
    pyside6 = types.ModuleType('PySide6')

    # -- QtCore --
    qtcore = types.ModuleType('PySide6.QtCore')
    qtcore.Qt = type('Qt', (), {
        'AlignRight': 0, 'AlignVCenter': 0, 'AlignCenter': 0, 'NoFocus': 0,
    })()
    qtcore.QColor = type('QColor', (), {'__init__': lambda self, *a, **k: None})
    pyside6.QtCore = qtcore

    # -- QtGui --
    qtgui = types.ModuleType('PySide6.QtGui')
    qtgui.QColor = type('QColor', (), {'__init__': lambda self, *a, **k: None})
    pyside6.QtGui = qtgui

    # Build a generic widget stub factory
    def _widget_stub(name):
        return type(name, (), {
            '__init__': lambda self, *a, **k: None,
            'Shape': type('Shape', (), {'NoFrame': 0})(),
            'StandardButton': type('StandardButton', (), {'Ok': 1, 'Cancel': 2})(),
            'DialogCode': type('DialogCode', (), {'Accepted': 1, 'Rejected': 0})(),
        })

    # -- QtWidgets --
    qtwidgets = types.ModuleType('PySide6.QtWidgets')
    for widget_name in (
        'QCheckBox', 'QComboBox', 'QDialog', 'QDialogButtonBox',
        'QDoubleSpinBox', 'QFileDialog', 'QFormLayout', 'QHBoxLayout',
        'QLabel', 'QLineEdit', 'QMessageBox', 'QPushButton', 'QScrollArea',
        'QSpinBox', 'QTextEdit', 'QVBoxLayout', 'QWidget',
    ):
        setattr(qtwidgets, widget_name, _widget_stub(widget_name))
    pyside6.QtWidgets = qtwidgets

    return pyside6, qtcore, qtgui, qtwidgets


_pyside6, _qtcore, _qtgui, _qtwidgets = _make_qt_mock()
sys.modules.setdefault('PySide6', _pyside6)
sys.modules.setdefault('PySide6.QtCore', _qtcore)
sys.modules.setdefault('PySide6.QtGui', _qtgui)
sys.modules.setdefault('PySide6.QtWidgets', _qtwidgets)

# ---------------------------------------------------------------------------
# Now safe to import the module under test
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from param_dialog import _resolve_label, _resolve_link, is_script_configured  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers: _resolve_label
# ---------------------------------------------------------------------------

class TestResolveLabel:
    def test_plain_string(self):
        assert _resolve_label({'name': 'fps', 'label': 'Frames per second'}) == 'Frames per second'

    def test_locale_map_prefers_english(self):
        param = {'name': 'fps', 'label': {'es': 'Frames por segundo', 'en': 'Frames per second'}}
        assert _resolve_label(param) == 'Frames per second'

    def test_locale_map_english_fallback(self):
        param = {'name': 'fps', 'label': {'en': 'Frames per second'}}
        assert _resolve_label(param) == 'Frames per second'

    def test_missing_label_falls_back_to_name(self):
        param = {'name': 'fps'}
        assert _resolve_label(param) == 'fps'

    def test_empty_label_dict_falls_back_to_name(self):
        param = {'name': 'fps', 'label': {}}
        assert _resolve_label(param) == 'fps'

    def test_description_key(self):
        param = {'name': 'fps', 'description': 'Sampling rate'}
        assert _resolve_label(param, 'description') == 'Sampling rate'

    def test_none_label(self):
        param = {'name': 'x', 'label': None}
        assert _resolve_label(param) == 'x'


# ---------------------------------------------------------------------------
# Helpers: _resolve_link
# ---------------------------------------------------------------------------

class TestResolveLink:
    def _ctx(self):
        return {
            'process_video': {'output_csv': '/data/signals.csv'},
        }

    def test_valid_link(self):
        result = _resolve_link('process_video.output_csv', self._ctx())
        assert result == '/data/signals.csv'

    def test_missing_script(self):
        assert _resolve_link('nonexistent.output_csv', self._ctx()) is None

    def test_missing_output_key(self):
        assert _resolve_link('process_video.nonexistent', self._ctx()) is None

    def test_malformed_no_dot(self):
        assert _resolve_link('process_video_output_csv', self._ctx()) is None

    def test_empty_string(self):
        assert _resolve_link('', self._ctx()) is None

    def test_empty_context(self):
        assert _resolve_link('process_video.output_csv', {}) is None

    def test_non_string_link(self):
        assert _resolve_link(None, self._ctx()) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Helpers: is_script_configured
# ---------------------------------------------------------------------------

class _FakePluginInfo:
    """Minimal stand-in for PluginInfo, sufficient for is_script_configured."""
    def __init__(self, parameters):
        self.parameters = parameters


class TestIsScriptConfigured:
    def test_no_parameters_always_configured(self):
        info = _FakePluginInfo([])
        assert is_script_configured(info, {}) is True

    def test_no_required_params_always_configured(self):
        info = _FakePluginInfo([
            {'name': 'fps', 'type': 'int', 'required': False}
        ])
        assert is_script_configured(info, {}) is True

    def test_required_string_missing(self):
        info = _FakePluginInfo([
            {'name': 'input_video', 'type': 'file', 'required': True}
        ])
        assert is_script_configured(info, {}) is False

    def test_required_string_present(self):
        info = _FakePluginInfo([
            {'name': 'input_video', 'type': 'file', 'required': True}
        ])
        assert is_script_configured(info, {'input_video': '/path/to/video.tif'}) is True

    def test_required_string_empty(self):
        info = _FakePluginInfo([
            {'name': 'input_video', 'type': 'file', 'required': True}
        ])
        assert is_script_configured(info, {'input_video': ''}) is False

    def test_required_string_whitespace_only(self):
        info = _FakePluginInfo([
            {'name': 'input_video', 'type': 'file', 'required': True}
        ])
        assert is_script_configured(info, {'input_video': '   '}) is False

    def test_required_int_zero_is_configured(self):
        # Zero is a valid integer value — should not be treated as "empty"
        info = _FakePluginInfo([
            {'name': 'count', 'type': 'int', 'required': True}
        ])
        assert is_script_configured(info, {'count': 0}) is True

    def test_required_bool_false_is_configured(self):
        info = _FakePluginInfo([
            {'name': 'normalize', 'type': 'bool', 'required': True}
        ])
        assert is_script_configured(info, {'normalize': False}) is True

    def test_required_int_missing(self):
        info = _FakePluginInfo([
            {'name': 'fps', 'type': 'int', 'required': True}
        ])
        assert is_script_configured(info, {}) is False

    def test_mixed_required_and_optional(self):
        info = _FakePluginInfo([
            {'name': 'input_video', 'type': 'file', 'required': True},
            {'name': 'fps', 'type': 'int', 'required': False},
            {'name': 'output_dir', 'type': 'directory', 'required': True},
        ])
        # Both required params present
        assert is_script_configured(info, {'input_video': '/v.tif', 'output_dir': '/out'}) is True
        # One required param missing
        assert is_script_configured(info, {'input_video': '/v.tif'}) is False



# ---------------------------------------------------------------------------
# Helpers: _resolve_label
# ---------------------------------------------------------------------------

class TestResolveLabel:
    def test_plain_string(self):
        assert _resolve_label({'name': 'fps', 'label': 'Frames per second'}) == 'Frames per second'

    def test_locale_map_prefers_english(self):
        param = {'name': 'fps', 'label': {'es': 'Frames por segundo', 'en': 'Frames per second'}}
        assert _resolve_label(param) == 'Frames per second'

    def test_locale_map_english_fallback(self):
        param = {'name': 'fps', 'label': {'en': 'Frames per second'}}
        assert _resolve_label(param) == 'Frames per second'

    def test_missing_label_falls_back_to_name(self):
        param = {'name': 'fps'}
        assert _resolve_label(param) == 'fps'

    def test_empty_label_dict_falls_back_to_name(self):
        param = {'name': 'fps', 'label': {}}
        assert _resolve_label(param) == 'fps'

    def test_description_key(self):
        param = {'name': 'fps', 'description': 'Sampling rate'}
        assert _resolve_label(param, 'description') == 'Sampling rate'

    def test_none_label(self):
        param = {'name': 'x', 'label': None}
        assert _resolve_label(param) == 'x'


# ---------------------------------------------------------------------------
# Helpers: _resolve_link
# ---------------------------------------------------------------------------

class TestResolveLink:
    def _ctx(self):
        return {
            'process_video': {'output_csv': '/data/signals.csv'},
        }

    def test_valid_link(self):
        result = _resolve_link('process_video.output_csv', self._ctx())
        assert result == '/data/signals.csv'

    def test_missing_script(self):
        assert _resolve_link('nonexistent.output_csv', self._ctx()) is None

    def test_missing_output_key(self):
        assert _resolve_link('process_video.nonexistent', self._ctx()) is None

    def test_malformed_no_dot(self):
        assert _resolve_link('process_video_output_csv', self._ctx()) is None

    def test_empty_string(self):
        assert _resolve_link('', self._ctx()) is None

    def test_empty_context(self):
        assert _resolve_link('process_video.output_csv', {}) is None

    def test_non_string_link(self):
        assert _resolve_link(None, self._ctx()) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Helpers: is_script_configured
# ---------------------------------------------------------------------------

class _FakePluginInfo:
    """Minimal stand-in for PluginInfo, sufficient for is_script_configured."""
    def __init__(self, parameters):
        self.parameters = parameters


class TestIsScriptConfigured:
    def test_no_parameters_always_configured(self):
        info = _FakePluginInfo([])
        assert is_script_configured(info, {}) is True

    def test_no_required_params_always_configured(self):
        info = _FakePluginInfo([
            {'name': 'fps', 'type': 'int', 'required': False}
        ])
        assert is_script_configured(info, {}) is True

    def test_required_string_missing(self):
        info = _FakePluginInfo([
            {'name': 'input_video', 'type': 'file', 'required': True}
        ])
        assert is_script_configured(info, {}) is False

    def test_required_string_present(self):
        info = _FakePluginInfo([
            {'name': 'input_video', 'type': 'file', 'required': True}
        ])
        assert is_script_configured(info, {'input_video': '/path/to/video.tif'}) is True

    def test_required_string_empty(self):
        info = _FakePluginInfo([
            {'name': 'input_video', 'type': 'file', 'required': True}
        ])
        assert is_script_configured(info, {'input_video': ''}) is False

    def test_required_string_whitespace_only(self):
        info = _FakePluginInfo([
            {'name': 'input_video', 'type': 'file', 'required': True}
        ])
        assert is_script_configured(info, {'input_video': '   '}) is False

    def test_required_int_zero_is_configured(self):
        # Zero is a valid integer value — should not be treated as "empty"
        info = _FakePluginInfo([
            {'name': 'count', 'type': 'int', 'required': True}
        ])
        assert is_script_configured(info, {'count': 0}) is True

    def test_required_bool_false_is_configured(self):
        info = _FakePluginInfo([
            {'name': 'normalize', 'type': 'bool', 'required': True}
        ])
        assert is_script_configured(info, {'normalize': False}) is True

    def test_required_int_missing(self):
        info = _FakePluginInfo([
            {'name': 'fps', 'type': 'int', 'required': True}
        ])
        assert is_script_configured(info, {}) is False

    def test_mixed_required_and_optional(self):
        info = _FakePluginInfo([
            {'name': 'input_video', 'type': 'file', 'required': True},
            {'name': 'fps', 'type': 'int', 'required': False},
            {'name': 'output_dir', 'type': 'directory', 'required': True},
        ])
        # Both required params present
        assert is_script_configured(info, {'input_video': '/v.tif', 'output_dir': '/out'}) is True
        # One required param missing
        assert is_script_configured(info, {'input_video': '/v.tif'}) is False
