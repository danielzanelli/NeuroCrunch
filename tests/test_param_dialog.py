# This Python file uses the following encoding: utf-8
"""Lightweight tests for src/param_dialog.py non-GUI logic.

These tests do NOT require PySide6 or a running QApplication.  They cover only
the helper functions and pure-logic parts of the module; the PySide6 stub and
the ``src`` import path are installed by ``tests/conftest.py``.  Run with:

    pytest tests/test_param_dialog.py
"""
from param_dialog import (  # noqa: E402
    _localize,
    _resolve_label,
    _resolve_link,
    compute_effective_links,
    is_script_configured,
)


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

    def test_locale_map_prefers_active_language(self):
        param = {'name': 'fps', 'label': {'en': 'Frames per second', 'es': 'Frames por segundo'}}
        assert _resolve_label(param, 'label', language='es') == 'Frames por segundo'

    def test_locale_map_falls_back_to_english_when_language_missing(self):
        param = {'name': 'fps', 'label': {'en': 'Frames per second'}}
        assert _resolve_label(param, 'label', language='es') == 'Frames per second'

    def test_locale_map_falls_back_to_any_value_when_no_match(self):
        param = {'name': 'fps', 'label': {'fr': 'Images par seconde'}}
        assert _resolve_label(param, 'label', language='es') == 'Images par seconde'


class TestLocalize:
    def test_plain_string_ignores_language(self):
        assert _localize('Select ROIs', language='es') == 'Select ROIs'

    def test_prefers_active_language(self):
        value = {'en': 'Select ROIs', 'es': 'Seleccionar ROIs'}
        assert _localize(value, language='es') == 'Seleccionar ROIs'

    def test_falls_back_to_english(self):
        value = {'en': 'Select ROIs'}
        assert _localize(value, language='es') == 'Select ROIs'

    def test_falls_back_to_fallback_when_none(self):
        assert _localize(None, fallback='select_rois', language='es') == 'select_rois'


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

    def test_required_file_with_manifest_link_is_configured(self):
        info = _FakePluginInfo([
            {'name': 'input_csv', 'type': 'file', 'required': True, 'link': 'upstream.out_csv'}
        ])
        assert is_script_configured(info, {}) is True

    def test_required_file_with_user_link_is_configured(self):
        info = _FakePluginInfo([
            {'name': 'input_csv', 'type': 'file', 'required': True}
        ])
        assert is_script_configured(info, {}, user_links={'input_csv': 'upstream.out_csv'}) is True

    def test_required_file_with_cleared_link_is_not_configured(self):
        info = _FakePluginInfo([
            {'name': 'input_csv', 'type': 'file', 'required': True, 'link': 'upstream.out_csv'}
        ])
        assert is_script_configured(info, {}, user_links={'input_csv': ''}) is False


# ---------------------------------------------------------------------------
# Helpers: compute_effective_links
# ---------------------------------------------------------------------------

class TestComputeEffectiveLinks:
    def _info(self):
        return _FakePluginInfo([
            {'name': 'input_csv', 'type': 'file', 'link': 'upstream.out_csv'},
            {'name': 'input_video', 'type': 'file'},
            {'name': 'fps', 'type': 'int'},
        ])

    def test_manifest_links_inherited_without_user_links(self):
        assert compute_effective_links(self._info()) == {'input_csv': 'upstream.out_csv'}

    def test_user_link_overrides_manifest(self):
        links = compute_effective_links(self._info(), {'input_csv': 'other.result'})
        assert links == {'input_csv': 'other.result'}

    def test_user_link_adds_new_link(self):
        links = compute_effective_links(self._info(), {'input_video': 'upstream.video'})
        assert links == {'input_csv': 'upstream.out_csv', 'input_video': 'upstream.video'}

    def test_empty_string_clears_manifest_link(self):
        assert compute_effective_links(self._info(), {'input_csv': ''}) == {}

    def test_no_parameters(self):
        assert compute_effective_links(_FakePluginInfo([])) == {}
