# This Python file uses the following encoding: utf-8
"""Tests for src/script_runner.py (Phase 4).

These tests do NOT require PySide6 or a running QApplication. They provide
minimal mocks for ``QThread``/``Signal`` (synchronous ``start()`` that calls
``run()`` directly, and a tiny pub-sub ``Signal`` implementation) plus mocks
for ``param_dialog``'s Qt-dependent imports, so ``script_runner.py`` can be
imported and exercised in isolation. Run with:

    pytest tests/test_script_runner.py
"""
import json
import os
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass, field
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Mock PySide6 so the module (and its param_dialog import) imports without Qt
# ---------------------------------------------------------------------------
def _make_qt_mock():
    pyside6 = types.ModuleType('PySide6')

    # -- QtCore --
    qtcore = types.ModuleType('PySide6.QtCore')
    qtcore.Qt = type('Qt', (), {
        'AlignRight': 0, 'AlignVCenter': 0, 'AlignCenter': 0, 'NoFocus': 0,
    })()
    qtcore.QColor = type('QColor', (), {'__init__': lambda self, *a, **k: None})

    class _Signal:
        """Minimal stand-in for PySide6.QtCore.Signal: a per-instance pub-sub."""

        def __init__(self, *_types):
            self._name = None

        def __set_name__(self, owner, name):
            self._name = name

        def __get__(self, instance, owner):
            if instance is None:
                return self
            attr = f'_signal_{self._name}'
            bound = instance.__dict__.get(attr)
            if bound is None:
                bound = _BoundSignal()
                instance.__dict__[attr] = bound
            return bound

    class _BoundSignal:
        def __init__(self):
            self._callbacks = []

        def connect(self, callback):
            self._callbacks.append(callback)

        def emit(self, *args, **kwargs):
            for cb in list(self._callbacks):
                cb(*args, **kwargs)

    qtcore.Signal = _Signal

    class _QThread:
        """Minimal stand-in for QThread: start() runs synchronously."""

        def __init__(self, parent=None):
            self._parent = parent
            self._running = False

        def start(self):
            self._running = True
            try:
                self.run()
            finally:
                self._running = False

        def isRunning(self):
            return self._running

        def run(self):
            pass

    qtcore.QThread = _QThread
    pyside6.QtCore = qtcore

    # -- QtGui --
    qtgui = types.ModuleType('PySide6.QtGui')
    qtgui.QColor = type('QColor', (), {'__init__': lambda self, *a, **k: None})
    pyside6.QtGui = qtgui

    def _widget_stub(name):
        return type(name, (), {
            '__init__': lambda self, *a, **k: None,
            'Shape': type('Shape', (), {'NoFrame': 0})(),
            'StandardButton': type('StandardButton', (), {'Ok': 1, 'Cancel': 2})(),
            'DialogCode': type('DialogCode', (), {'Accepted': 1, 'Rejected': 0})(),
        })

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

# If another test module already installed a PySide6.QtCore mock (e.g.
# test_param_dialog.py, which doesn't define QThread/Signal), make sure the
# attributes this module needs are present regardless of import order.
_installed_qtcore = sys.modules['PySide6.QtCore']
if not hasattr(_installed_qtcore, 'QThread'):
    _installed_qtcore.QThread = _qtcore.QThread
if not hasattr(_installed_qtcore, 'Signal'):
    _installed_qtcore.Signal = _qtcore.Signal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from script_runner import PipelineContext, ScriptRunner  # noqa: E402


@dataclass
class _FakePluginInfo:
    """Minimal stand-in for plugin_manager.PluginInfo."""
    id: str
    name: str
    entry_point: str
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    outputs: Dict[str, Any] = field(default_factory=dict)


class PipelineContextTests(unittest.TestCase):
    def test_get_outputs_empty_by_default(self):
        ctx = PipelineContext()
        self.assertEqual(ctx.get_outputs('unknown'), {})

    def test_set_and_get_outputs(self):
        ctx = PipelineContext()
        ctx.set_outputs('script_a', {'out': '/tmp/a.csv'})
        self.assertEqual(ctx.get_outputs('script_a'), {'out': '/tmp/a.csv'})

    def test_set_outputs_merges_without_clobbering(self):
        ctx = PipelineContext()
        ctx.set_outputs('script_a', {'out1': 'x'})
        ctx.set_outputs('script_a', {'out2': 'y'})
        self.assertEqual(ctx.get_outputs('script_a'), {'out1': 'x', 'out2': 'y'})

    def test_persists_to_session_dir_and_reloads(self):
        with tempfile.TemporaryDirectory() as session_dir:
            ctx = PipelineContext(session_dir=session_dir)
            ctx.set_outputs('script_a', {'out': '/tmp/a.csv'})

            path = os.path.join(session_dir, 'pipeline_context.json')
            self.assertTrue(os.path.isfile(path))

            ctx2 = PipelineContext(session_dir=session_dir)
            self.assertEqual(ctx2.get_outputs('script_a'), {'out': '/tmp/a.csv'})

    def test_set_outputs_with_empty_dict_does_not_persist(self):
        with tempfile.TemporaryDirectory() as session_dir:
            ctx = PipelineContext(session_dir=session_dir)
            ctx.set_outputs('script_a', {})
            path = os.path.join(session_dir, 'pipeline_context.json')
            self.assertFalse(os.path.isfile(path))


class _EchoScript:
    """Writes a small helper script that echoes params and writes output.json."""

    TEMPLATE = '''
import argparse, json, sys
parser = argparse.ArgumentParser()
parser.add_argument("--nc_params")
parser.add_argument("--nc_output")
args = parser.parse_args()
with open(args.nc_params) as f:
    params = json.load(f)
print("hello from script:" + params.get("name", "?"))
if params.get("fail"):
    sys.exit(3)
with open(args.nc_output, "w") as f:
    json.dump({"result": params.get("value", "default")}, f)
'''

    @classmethod
    def write(cls, path):
        with open(path, 'w', encoding='utf-8') as f:
            f.write(cls.TEMPLATE)


class ScriptRunnerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.script_path = os.path.join(self._tmp.name, 'main.py')
        _EchoScript.write(self.script_path)

    def _make_plugin(self, script_id='script_a', parameters=None):
        return _FakePluginInfo(
            id=script_id,
            name=script_id.title(),
            entry_point=self.script_path,
            parameters=parameters or [],
        )

    def test_successful_pipeline_run_collects_outputs_and_logs(self):
        plugin = self._make_plugin()
        ctx = PipelineContext()
        pipeline = [('script_a', plugin, {'name': 'A', 'value': 'ok'})]
        runner = ScriptRunner(pipeline, ctx)

        logs = []
        started = []
        finished = []
        done = []
        runner.log_message.connect(logs.append)
        runner.script_started.connect(started.append)
        runner.script_finished.connect(lambda sid, ok: finished.append((sid, ok)))
        runner.pipeline_done.connect(done.append)

        runner.start()

        self.assertEqual(started, ['script_a'])
        self.assertEqual(finished, [('script_a', True)])
        self.assertEqual(done, [True])
        self.assertTrue(any('hello from script:A' in line for line in logs))
        self.assertEqual(ctx.get_outputs('script_a'), {'result': 'ok'})

    def test_failing_script_halts_pipeline(self):
        plugin_a = self._make_plugin('script_a')
        plugin_b = self._make_plugin('script_b')
        ctx = PipelineContext()
        pipeline = [
            ('script_a', plugin_a, {'name': 'A', 'fail': True}),
            ('script_b', plugin_b, {'name': 'B'}),
        ]
        runner = ScriptRunner(pipeline, ctx)

        finished = []
        done = []
        runner.script_finished.connect(lambda sid, ok: finished.append((sid, ok)))
        runner.pipeline_done.connect(done.append)

        runner.start()

        self.assertEqual(finished, [('script_a', False)])
        self.assertEqual(done, [False])

    def test_linked_param_resolved_from_context(self):
        plugin_b = self._make_plugin(
            'script_b',
            parameters=[{'name': 'value', 'link': 'script_a.result'}],
        )
        ctx = PipelineContext()
        ctx.set_outputs('script_a', {'result': 'from_a'})
        pipeline = [('script_b', plugin_b, {'name': 'B'})]
        runner = ScriptRunner(pipeline, ctx)

        runner.start()

        self.assertEqual(ctx.get_outputs('script_b'), {'result': 'from_a'})


if __name__ == '__main__':
    unittest.main()
