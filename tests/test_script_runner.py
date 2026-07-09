# This Python file uses the following encoding: utf-8
"""Tests for src/script_runner.py (Phase 5 — threading model).

Scripts are executed in-process via exec() so no external Python interpreter
is needed. These tests do NOT require PySide6 or a running QApplication. Run:

    pytest tests/test_script_runner.py
"""
import os
import sys
import tempfile
import textwrap
import threading
import types
import unittest
from dataclasses import dataclass, field
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Minimal PySide6 mock (no Qt required to run tests)
# ---------------------------------------------------------------------------

def _make_qt_mock():
    pyside6 = types.ModuleType('PySide6')

    qtcore = types.ModuleType('PySide6.QtCore')
    qtcore.Qt = type('Qt', (), {
        'AlignRight': 0, 'AlignVCenter': 0, 'AlignCenter': 0, 'NoFocus': 0,
    })()
    qtcore.QColor = type('QColor', (), {'__init__': lambda self, *a, **k: None})
    qtcore.QCoreApplication = type('QCoreApplication', (), {
        'translate': staticmethod(lambda context, text, *a, **k: text),
    })

    class _Signal:
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
        """Minimal QThread stand-in: start() runs synchronously."""
        def __init__(self, parent=None):
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
    for _w in (
        'QCheckBox', 'QComboBox', 'QDialog', 'QDialogButtonBox',
        'QDoubleSpinBox', 'QFileDialog', 'QFormLayout', 'QHBoxLayout',
        'QLabel', 'QLineEdit', 'QMenu', 'QMessageBox', 'QPushButton',
        'QScrollArea', 'QSpinBox', 'QTextEdit', 'QVBoxLayout', 'QWidget',
    ):
        setattr(qtwidgets, _w, _widget_stub(_w))
    pyside6.QtWidgets = qtwidgets

    return pyside6, qtcore, qtgui, qtwidgets


_pyside6, _qtcore, _qtgui, _qtwidgets = _make_qt_mock()
sys.modules.setdefault('PySide6', _pyside6)
sys.modules.setdefault('PySide6.QtCore', _qtcore)
sys.modules.setdefault('PySide6.QtGui', _qtgui)
sys.modules.setdefault('PySide6.QtWidgets', _qtwidgets)

# Ensure QThread, Signal and QCoreApplication are present even if another
# test file registered a lighter mock first.
_installed_qtcore = sys.modules['PySide6.QtCore']
for _attr, _val in (
    ('QThread', _qtcore.QThread),
    ('Signal', _qtcore.Signal),
    ('QCoreApplication', _qtcore.QCoreApplication),
):
    if not hasattr(_installed_qtcore, _attr):
        setattr(_installed_qtcore, _attr, _val)
_installed_qtwidgets = sys.modules['PySide6.QtWidgets']
if not hasattr(_installed_qtwidgets, 'QMenu'):
    _installed_qtwidgets.QMenu = _qtwidgets.QMenu

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from script_runner import (  # noqa: E402
    PipelineContext,
    ScriptContext,
    ScriptRunner,
    StdoutCapture,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _FakePluginInfo:
    """Minimal stand-in for plugin_manager.PluginInfo."""
    id: str
    name: str
    entry_point: str
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    outputs: Dict[str, Any] = field(default_factory=dict)


def _write_script(path: str, source: str) -> None:
    """Write *source* (dedented) to *path*."""
    with open(path, 'w', encoding='utf-8') as f:
        f.write(textwrap.dedent(source))


# ---------------------------------------------------------------------------
# PipelineContext
# ---------------------------------------------------------------------------

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
            ctx2 = PipelineContext(session_dir=session_dir)
            self.assertEqual(ctx2.get_outputs('script_a'), {'out': '/tmp/a.csv'})

    def test_set_outputs_empty_dict_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as session_dir:
            ctx = PipelineContext(session_dir=session_dir)
            ctx.set_outputs('script_a', {})
            path = os.path.join(session_dir, 'pipeline_context.json')
            self.assertFalse(os.path.isfile(path))


# ---------------------------------------------------------------------------
# StdoutCapture
# ---------------------------------------------------------------------------

class StdoutCaptureTests(unittest.TestCase):
    def _collect(self, texts):
        """Feed *texts* into a capture, return list of emitted lines."""
        lines = []
        cap = StdoutCapture(lines.append)
        for t in texts:
            cap.write(t)
        cap.flush()
        return lines

    def test_emits_complete_newline_terminated_line(self):
        lines = self._collect(['hello world\n'])
        self.assertIn('hello world', lines)

    def test_buffers_partial_line_until_newline(self):
        lines = []
        cap = StdoutCapture(lines.append)
        cap.write('part')
        self.assertEqual(lines, [])  # not emitted yet
        cap.write('ial\n')
        self.assertIn('partial', lines)

    def test_flush_emits_remaining_buffer(self):
        lines = []
        cap = StdoutCapture(lines.append)
        cap.write('no newline here')
        cap.flush()
        self.assertTrue(any('no newline here' in l for l in lines))

    def test_carriage_return_emits_with_prefix(self):
        lines = self._collect(['progress\r'])
        self.assertTrue(any(l.startswith('\r') for l in lines))

    def test_progress_line_format_preserved(self):
        lines = self._collect(['PROGRESS:75\n'])
        self.assertIn('PROGRESS:75', lines)

    def test_blank_lines_not_emitted(self):
        lines = self._collect(['\n', '   \n'])
        self.assertEqual(lines, [])

    def test_multiple_lines_in_one_write(self):
        lines = self._collect(['line1\nline2\nline3\n'])
        self.assertEqual(lines, ['line1', 'line2', 'line3'])


# ---------------------------------------------------------------------------
# ScriptContext
# ---------------------------------------------------------------------------

class ScriptContextTests(unittest.TestCase):
    def test_is_cancelled_false_by_default(self):
        event = threading.Event()
        ctx = ScriptContext(event, lambda s: None)
        self.assertFalse(ctx.is_cancelled())

    def test_is_cancelled_true_after_set(self):
        event = threading.Event()
        ctx = ScriptContext(event, lambda s: None)
        event.set()
        self.assertTrue(ctx.is_cancelled())

    def test_progress_emits_progress_line(self):
        emitted = []
        ctx = ScriptContext(threading.Event(), emitted.append)
        ctx.progress(42)
        self.assertEqual(emitted, ['PROGRESS:42'])

    def test_log_emits_message(self):
        emitted = []
        ctx = ScriptContext(threading.Event(), emitted.append)
        ctx.log('hello')
        self.assertEqual(emitted, ['hello'])


# ---------------------------------------------------------------------------
# ScriptRunner
# ---------------------------------------------------------------------------

class ScriptRunnerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _script_path(self, name='script.py'):
        return os.path.join(self._tmp.name, name)

    def _make_plugin(self, script_id='script_a', path=None, parameters=None):
        return _FakePluginInfo(
            id=script_id,
            name=script_id.title(),
            entry_point=path or self._script_path(),
            parameters=parameters or [],
        )

    def _run(self, pipeline, ctx=None):
        """Run pipeline synchronously; return (logs, started, finished, done)."""
        if ctx is None:
            ctx = PipelineContext()
        runner = ScriptRunner(pipeline, ctx)
        logs, started, finished, done, progress = [], [], [], [], []
        runner.log_message.connect(logs.append)
        runner.script_started.connect(started.append)
        runner.script_finished.connect(lambda sid, ok: finished.append((sid, ok)))
        runner.pipeline_done.connect(done.append)
        runner.progress_changed.connect(progress.append)
        runner.start()
        return logs, started, finished, done, progress

    # --- Basic execution --------------------------------------------------

    def test_run_function_called_and_outputs_collected(self):
        _write_script(self._script_path(), '''
            def run(params):
                return {"result": params["value"]}
        ''')
        ctx = PipelineContext()
        plugin = self._make_plugin()
        _, _, finished, done, _ = self._run([('script_a', plugin, {'value': 'ok'})], ctx)
        self.assertEqual(finished, [('script_a', True)])
        self.assertEqual(done, [True])
        self.assertEqual(ctx.get_outputs('script_a'), {'result': 'ok'})

    def test_main_function_accepted_as_fallback(self):
        _write_script(self._script_path(), '''
            def main(params):
                return {"x": 1}
        ''')
        _, _, finished, done, _ = self._run([('script_a', self._make_plugin(), {})])
        self.assertEqual(finished, [('script_a', True)])
        self.assertEqual(done, [True])

    def test_print_output_appears_in_log(self):
        _write_script(self._script_path(), '''
            def run(params):
                print("hello from script")
                return {}
        ''')
        logs, _, _, _, _ = self._run([('script_a', self._make_plugin(), {})])
        self.assertTrue(any('hello from script' in l for l in logs))

    # --- Error handling ---------------------------------------------------

    def test_exception_marks_script_failed(self):
        _write_script(self._script_path(), '''
            def run(params):
                raise ValueError("something went wrong")
        ''')
        _, _, finished, done, _ = self._run([('script_a', self._make_plugin(), {})])
        self.assertEqual(finished, [('script_a', False)])
        self.assertEqual(done, [False])

    def test_exception_message_appears_in_log(self):
        _write_script(self._script_path(), '''
            def run(params):
                raise ValueError("specific error message")
        ''')
        logs, _, _, _, _ = self._run([('script_a', self._make_plugin(), {})])
        self.assertTrue(any('specific error message' in l for l in logs))

    def test_sys_exit_nonzero_marks_script_failed(self):
        _write_script(self._script_path(), '''
            import sys
            def run(params):
                sys.exit(1)
        ''')
        _, _, finished, done, _ = self._run([('script_a', self._make_plugin(), {})])
        self.assertEqual(finished, [('script_a', False)])
        self.assertEqual(done, [False])

    def test_sys_exit_zero_is_success(self):
        _write_script(self._script_path(), '''
            import sys
            def run(params):
                sys.exit(0)
        ''')
        _, _, finished, done, _ = self._run([('script_a', self._make_plugin(), {})])
        self.assertEqual(finished, [('script_a', True)])

    def test_syntax_error_marks_script_failed(self):
        _write_script(self._script_path(), 'def run(params\n    return {}\n')
        _, _, finished, done, _ = self._run([('script_a', self._make_plugin(), {})])
        self.assertEqual(finished, [('script_a', False)])
        self.assertEqual(done, [False])

    def test_missing_run_and_main_marks_script_failed(self):
        _write_script(self._script_path(), 'x = 1\n')
        logs, _, finished, _, _ = self._run([('script_a', self._make_plugin(), {})])
        self.assertEqual(finished, [('script_a', False)])
        self.assertTrue(any('run' in l or 'main' in l for l in logs))

    # --- Pipeline halting -------------------------------------------------

    def test_pipeline_halts_after_first_failure(self):
        path_a = self._script_path('a.py')
        path_b = self._script_path('b.py')
        _write_script(path_a, 'def run(p): raise RuntimeError("fail")')
        _write_script(path_b, 'def run(p): return {"ran": True}')
        plugin_a = self._make_plugin('a', path_a)
        plugin_b = self._make_plugin('b', path_b)
        ctx = PipelineContext()
        _, _, finished, done, _ = self._run([('a', plugin_a, {}), ('b', plugin_b, {})], ctx)
        self.assertEqual([s for s, _ in finished], ['a'])   # b never ran
        self.assertEqual(done, [False])
        self.assertEqual(ctx.get_outputs('b'), {})

    # --- Progress ---------------------------------------------------------

    def test_progress_line_drives_progress_changed_signal(self):
        _write_script(self._script_path(), '''
            def run(params):
                print("PROGRESS:50")
                return {}
        ''')
        _, _, _, _, progress = self._run([('script_a', self._make_plugin(), {})])
        self.assertIn(50, progress)

    def test_progress_clamped_to_0_100(self):
        _write_script(self._script_path(), '''
            def run(params):
                print("PROGRESS:150")
                print("PROGRESS:-10")
                return {}
        ''')
        _, _, _, _, progress = self._run([('script_a', self._make_plugin(), {})])
        self.assertTrue(all(0 <= p <= 100 for p in progress))

    # --- ctx parameter ---------------------------------------------------

    def test_ctx_passed_when_run_accepts_two_params(self):
        _write_script(self._script_path(), '''
            def run(params, ctx):
                ctx.log("ctx received")
                return {}
        ''')
        logs, _, _, _, _ = self._run([('script_a', self._make_plugin(), {})])
        self.assertIn('ctx received', logs)

    def test_ctx_progress_emits_signal(self):
        _write_script(self._script_path(), '''
            def run(params, ctx):
                ctx.progress(75)
                return {}
        ''')
        _, _, _, _, progress = self._run([('script_a', self._make_plugin(), {})])
        self.assertIn(75, progress)

    # --- Stop / cancellation ---------------------------------------------

    def test_stop_before_start_skips_all_scripts(self):
        path = self._script_path()
        _write_script(path, 'def run(p): return {}')
        plugin = self._make_plugin(path=path)
        ctx = PipelineContext()
        runner = ScriptRunner([('script_a', plugin, {})], ctx)
        runner.stop()
        done = []
        runner.pipeline_done.connect(done.append)
        runner.start()
        self.assertEqual(done, [False])

    def test_cancelled_ctx_stops_cooperative_script(self):
        _write_script(self._script_path(), '''
            def run(params, ctx):
                for i in range(1000):
                    if ctx.is_cancelled():
                        return {"stopped": True}
                return {"stopped": False}
        ''')
        ctx = PipelineContext()
        runner = ScriptRunner([('script_a', self._make_plugin(), {})], ctx)
        runner.stop()   # cancel before start
        runner.start()
        # Script returns early due to cancellation — pipeline_done is False
        # (stop_requested is True), but the script itself ran without error.

    # --- Fresh namespace per run -----------------------------------------

    def test_module_level_state_not_shared_between_runs(self):
        """Each exec() must get a fresh namespace — counters reset to 0."""
        path = self._script_path()
        _write_script(path, '''
            _counter = 0
            def run(params):
                global _counter
                _counter += 1
                return {"count": _counter}
        ''')
        plugin = self._make_plugin(path=path)
        ctx = PipelineContext()
        for _ in range(3):
            ctx2 = PipelineContext()
            runner = ScriptRunner([('script_a', plugin, {})], ctx2)
            runner.start()
            # Each run should return count=1, not an incrementing value.
            self.assertEqual(ctx2.get_outputs('script_a').get('count'), 1)

    # --- Linked parameters -----------------------------------------------

    def test_linked_param_resolved_from_context(self):
        path = self._script_path()
        _write_script(path, '''
            def run(params):
                return {"echoed": params["value"]}
        ''')
        plugin = self._make_plugin(
            parameters=[{'name': 'value', 'link': 'upstream.result'}]
        )
        ctx = PipelineContext()
        ctx.set_outputs('upstream', {'result': 'linked_value'})
        runner = ScriptRunner([('script_a', plugin, {})], ctx)
        runner.start()
        self.assertEqual(ctx.get_outputs('script_a'), {'echoed': 'linked_value'})

    def test_user_link_overrides_manifest_link(self):
        path = self._script_path()
        _write_script(path, '''
            def run(params):
                return {"echoed": params["value"]}
        ''')
        plugin = self._make_plugin(
            parameters=[{'name': 'value', 'link': 'upstream.result'}]
        )
        ctx = PipelineContext()
        ctx.set_outputs('upstream', {'result': 'manifest_value'})
        ctx.set_outputs('other', {'result': 'user_value'})
        runner = ScriptRunner(
            [('script_a', plugin, {})], ctx,
            links_by_script={'script_a': {'value': 'other.result'}},
        )
        runner.start()
        self.assertEqual(ctx.get_outputs('script_a'), {'echoed': 'user_value'})

    def test_stale_file_link_falls_back_to_saved_value(self):
        path = self._script_path()
        _write_script(path, '''
            def run(params):
                return {"echoed": params["input_csv"]}
        ''')
        plugin = self._make_plugin(
            parameters=[{'name': 'input_csv', 'type': 'file', 'link': 'upstream.out_csv'}]
        )
        existing = self._script_path('saved.csv')
        _write_script(existing, 'a,b\n')
        ctx = PipelineContext()
        ctx.set_outputs('upstream', {'out_csv': os.path.join(self._tmp.name, 'deleted.csv')})
        logs, _, _, _, _ = self._run([('script_a', plugin, {'input_csv': existing})], ctx)
        self.assertEqual(ctx.get_outputs('script_a'), {'echoed': existing})
        self.assertTrue(any('missing file' in l for l in logs))

    def test_required_file_param_empty_fails_before_exec(self):
        path = self._script_path()
        _write_script(path, '''
            def run(params):
                return {"ran": True}
        ''')
        plugin = self._make_plugin(
            parameters=[{'name': 'input_csv', 'type': 'file', 'required': True}]
        )
        ctx = PipelineContext()
        logs, _, finished, done, _ = self._run([('script_a', plugin, {})], ctx)
        self.assertEqual(finished, [('script_a', False)])
        self.assertEqual(done, [False])
        self.assertEqual(ctx.get_outputs('script_a'), {})
        self.assertTrue(any('input_csv' in l for l in logs))

    # --- Context seeding (persistence across runs) -------------------------

    def test_seed_prepopulates_outputs(self):
        ctx = PipelineContext()
        ctx.seed({'upstream': {'out': '/data/a.csv'}})
        self.assertEqual(ctx.get_outputs('upstream'), {'out': '/data/a.csv'})

    def test_seed_ignores_malformed_data(self):
        ctx = PipelineContext()
        ctx.seed(None)
        ctx.seed({'bad': 'not-a-dict'})
        self.assertEqual(ctx.get_outputs('bad'), {})

    def test_outputs_carry_across_runner_instances_via_seed(self):
        """Run A, persist its outputs, seed a fresh context, run B linked to A."""
        path_a = self._script_path('a.py')
        path_b = self._script_path('b.py')
        produced = os.path.join(self._tmp.name, 'produced.csv')
        _write_script(path_a, f'''
            def run(params):
                path = {produced!r}
                with open(path, 'w') as f:
                    f.write('data')
                return {{"out_csv": path}}
        ''')
        _write_script(path_b, '''
            def run(params):
                return {"echoed": params["input_csv"]}
        ''')
        plugin_a = self._make_plugin('a', path_a)
        plugin_b = self._make_plugin(
            'b', path_b,
            parameters=[{'name': 'input_csv', 'type': 'file', 'link': 'a.out_csv'}],
        )

        ctx1 = PipelineContext()
        ScriptRunner([('a', plugin_a, {})], ctx1).start()
        persisted = {k: dict(v) for k, v in ctx1.as_dict().items()}

        ctx2 = PipelineContext()
        ctx2.seed(persisted)
        ScriptRunner([('b', plugin_b, {})], ctx2).start()
        self.assertEqual(ctx2.get_outputs('b'), {'echoed': produced})


if __name__ == '__main__':
    unittest.main()
