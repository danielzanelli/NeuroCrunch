# This Python file uses the following encoding: utf-8
"""Shared pytest fixtures / import shims for the NeuroCrunch test suite.

The pure-logic tests must import ``src`` modules (``param_dialog``,
``script_runner``, …) without a real Qt installation or a running
``QApplication``. This conftest installs a single, complete PySide6 stub into
``sys.modules`` at collection time (before any test module imports its target),
so every test file can simply import what it needs.

Keeping one stub here — instead of a copy per test file — means the mock only
has to be kept in step with the modules' Qt imports in one place. When a module
under test starts importing a new Qt symbol, add it below.
"""
import os
import sys
import types


def _make_qt_mock():
    pyside6 = types.ModuleType('PySide6')

    # -- Signals (class-level descriptor + per-instance bound object) --------
    class _BoundSignal:
        def __init__(self):
            self._callbacks = []

        def connect(self, callback):
            self._callbacks.append(callback)

        def emit(self, *args, **kwargs):
            for cb in list(self._callbacks):
                cb(*args, **kwargs)

    class _Signal:
        """Descriptor mimicking PySide6.Signal: one bound signal per instance."""

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

    # -- QtCore -------------------------------------------------------------
    qtcore = types.ModuleType('PySide6.QtCore')
    qtcore.Qt = type('Qt', (), {
        'AlignRight': 0, 'AlignVCenter': 0, 'AlignCenter': 0, 'AlignTop': 0,
        'NoFocus': 0,
    })()
    qtcore.QColor = type('QColor', (), {'__init__': lambda self, *a, **k: None})
    qtcore.QCoreApplication = type('QCoreApplication', (), {
        'translate': staticmethod(lambda context, text, *a, **k: text),
    })
    qtcore.Signal = _Signal

    class _QThread:
        """Minimal QThread stand-in: start() runs run() synchronously."""

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

    class _QTimer:
        """Import-only QTimer stub (no event loop); enough to construct one."""

        def __init__(self, parent=None):
            self.timeout = _BoundSignal()

        def setSingleShot(self, _value):
            pass

        def setInterval(self, _ms):
            pass

        def start(self, *_a):
            pass

        def stop(self):
            pass

    qtcore.QTimer = _QTimer
    pyside6.QtCore = qtcore

    # -- QtGui --------------------------------------------------------------
    qtgui = types.ModuleType('PySide6.QtGui')
    qtgui.QColor = type('QColor', (), {'__init__': lambda self, *a, **k: None})
    pyside6.QtGui = qtgui

    # -- QtWidgets ----------------------------------------------------------
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
# setdefault: install the stub only if a real PySide6 has not already been
# imported by the process. Nothing in the suite needs the real toolkit.
sys.modules.setdefault('PySide6', _pyside6)
sys.modules.setdefault('PySide6.QtCore', _qtcore)
sys.modules.setdefault('PySide6.QtGui', _qtgui)
sys.modules.setdefault('PySide6.QtWidgets', _qtwidgets)

# Make the src/ modules importable by name (script_runner, param_dialog, …).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
