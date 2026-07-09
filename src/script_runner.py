# This Python file uses the following encoding: utf-8
# SPDX-License-Identifier: Apache-2.0
"""NeuroCrunch - Script Runner (Phase 5)

Executes a configured pipeline of script plugins in the bundled Python
environment. Each script's ``run(params)`` function is called directly inside
a worker thread — no external interpreter required.

See README.md > "<script_name>.py — execution contract".
"""
from __future__ import annotations

import ctypes
import inspect
import io
import json
import os
import sys
import tempfile
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QThread, Signal

from param_dialog import _resolve_link


class _PipelineCancelled(BaseException):
    """Raised inside the worker thread to interrupt a running script on Stop.

    Subclasses ``BaseException`` (not ``Exception``) so a script's own
    ``except Exception`` cannot swallow the cancellation; the runner catches it
    explicitly.
    """

# Type alias matching param_dialog.PipelineContext's shape:
# { script_id: { output_key: value } }
PipelineContextData = Dict[str, Dict[str, Any]]

PIPELINE_CONTEXT_FILENAME = 'pipeline_context.json'


# ---------------------------------------------------------------------------
# PipelineContext
# ---------------------------------------------------------------------------

class PipelineContext:
    """Stores ``{script_id: {output_key: value}}`` for the current session.

    Uses a temporary directory by default. This is created per-session and
    should be cleaned up after the pipeline finishes via cleanup().
    """

    def __init__(self, session_dir: Optional[str] = None) -> None:
        if session_dir:
            self.session_dir = session_dir
            self._temp_dir = None
        else:
            self._temp_dir = tempfile.TemporaryDirectory(prefix='neurocrunch_pipeline_')
            self.session_dir = self._temp_dir.name

        self.data: PipelineContextData = {}
        if session_dir:
            self.load()

    @property
    def path(self) -> Optional[str]:
        if not self.session_dir:
            return None
        return os.path.join(self.session_dir, PIPELINE_CONTEXT_FILENAME)

    def get_outputs(self, script_id: str) -> Dict[str, Any]:
        """Return the outputs recorded for *script_id* (empty dict if none)."""
        return self.data.get(script_id, {})

    def set_outputs(self, script_id: str, outputs: Dict[str, Any]) -> None:
        """Merge *outputs* into the entry for *script_id* and persist to disk."""
        if not outputs:
            return
        self.data.setdefault(script_id, {}).update(outputs)
        self.save()

    def as_dict(self) -> PipelineContextData:
        """Return the underlying ``{script_id: {output_key: value}}`` mapping."""
        return self.data

    def load(self) -> None:
        """Load previously persisted context from ``session_dir``, if present."""
        path = self.path
        if not path or not os.path.isfile(path):
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self.data = loaded
        except (OSError, json.JSONDecodeError):
            pass

    def save(self) -> None:
        """Persist the current context to ``session_dir``, if configured."""
        path = self.path
        if not path:
            return
        try:
            os.makedirs(self.session_dir, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def cleanup(self) -> None:
        """Delete the temporary directory if this context owns one."""
        if self._temp_dir is not None:
            try:
                self._temp_dir.cleanup()
                self._temp_dir = None
                self.session_dir = None
            except OSError:
                pass


# ---------------------------------------------------------------------------
# StdoutCapture
# ---------------------------------------------------------------------------

class StdoutCapture(io.TextIOBase):
    """Redirects ``sys.stdout``/``sys.stderr`` to a Qt signal during a script run.

    Buffers text and emits one call per logical line:

    * Lines ending with ``\\n`` are emitted stripped of the newline.
    * Text preceded by ``\\r`` is emitted with a leading ``\\r`` so the UI log
      can update the last entry in-place (matching the existing log panel
      behaviour for carriage-return progress updates).
    * ``PROGRESS:<number>`` lines are forwarded as-is; ``ScriptRunner``
      inspects them to drive the progress bar.
    """

    def __init__(self, emit_fn: Callable[[str], None]) -> None:
        super().__init__()
        self._emit = emit_fn
        self._buffer = ''

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._buffer += text
        # Process all complete lines in the buffer.
        while True:
            cr_pos = self._buffer.find('\r')
            nl_pos = self._buffer.find('\n')

            if cr_pos == -1 and nl_pos == -1:
                break  # No line ending yet; keep buffering.

            if cr_pos != -1 and (nl_pos == -1 or cr_pos < nl_pos):
                # \r comes first: emit buffered text as an in-place update.
                line = self._buffer[:cr_pos]
                self._buffer = self._buffer[cr_pos + 1:]
                if line:
                    self._emit('\r' + line)
            else:
                # \n comes first: emit as a normal new line.
                line = self._buffer[:nl_pos]
                self._buffer = self._buffer[nl_pos + 1:]
                if line.strip():
                    self._emit(line)
        return len(text)

    def flush(self) -> None:
        """Emit any remaining buffered text that has no trailing line ending."""
        remaining = self._buffer.strip()
        if remaining:
            self._emit(remaining)
        self._buffer = ''

    def readable(self) -> bool:
        return False

    def writable(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# ScriptContext
# ---------------------------------------------------------------------------

class ScriptContext:
    """Optional second argument for scripts that declare ``run(params, ctx)``.

    Provides cooperative cancellation and progress reporting::

        def run(params, ctx):
            for i, item in enumerate(items):
                if ctx.is_cancelled():
                    return {}
                ctx.progress(i / len(items) * 100)
                # ... process item ...

    Scripts that only declare ``run(params)`` do not receive a context object;
    the runner detects the signature via ``inspect`` and omits it automatically.
    """

    def __init__(
        self,
        cancel_event: threading.Event,
        emit_fn: Callable[[str], None],
    ) -> None:
        self._cancel = cancel_event
        self._emit = emit_fn

    def is_cancelled(self) -> bool:
        """Return ``True`` if the user has pressed Stop."""
        return self._cancel.is_set()

    def progress(self, percent: float) -> None:
        """Report progress (0–100). Equivalent to ``print(f'PROGRESS:{percent:.0f}')``."""
        self._emit(f'PROGRESS:{percent:.0f}')

    def log(self, message: str) -> None:
        """Emit *message* to the app log."""
        self._emit(str(message))


# ---------------------------------------------------------------------------
# ScriptRunner
# ---------------------------------------------------------------------------

class ScriptRunner(QThread):
    """Runs an ordered pipeline of scripts in-process, one at a time.

    Parameters
    ----------
    pipeline:
        Ordered list of ``(script_id, plugin_info, params)`` tuples to run in
        sequence. ``params`` is the dict of saved parameter values for that
        script (before linked-parameter resolution, which happens right before
        each script runs).
    pipeline_context:
        Shared ``PipelineContext`` instance, updated after each script
        finishes with its declared outputs.
    """

    log_message = Signal(str)
    progress_changed = Signal(int)   # 0–100
    script_started = Signal(str)
    script_finished = Signal(str, bool)
    pipeline_done = Signal(bool)

    def __init__(
        self,
        pipeline: List[Tuple[str, Any, Dict[str, Any]]],
        pipeline_context: PipelineContext,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._pipeline = pipeline
        self._context = pipeline_context
        self._stop_requested = False
        self._cancel_event = threading.Event()
        self._worker_tid: Optional[int] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Request cancellation of the pipeline.

        Two mechanisms, so Stop works whether or not the running script
        cooperates:

        * sets the cancel event, which scripts declaring ``run(params, ctx)``
          can poll via ``ctx.is_cancelled()`` for a clean early return;
        * injects a ``_PipelineCancelled`` exception into the worker thread so
          even a non-cooperative ``run(params)`` script is interrupted. Since
          scripts run in-process (``exec``) rather than as a subprocess, this
          is the only way to stop a busy pure-Python loop. It fires at a Python
          bytecode boundary, so it cannot corrupt an in-flight C call — a script
          blocked in native code stops when control returns to Python.
        """
        self._stop_requested = True
        self._cancel_event.set()
        tid = self._worker_tid
        if tid is not None:
            self._async_raise(tid, _PipelineCancelled)

    @staticmethod
    def _async_raise(tid: int, exctype: type) -> None:
        """Best-effort: raise *exctype* in the thread identified by *tid*."""
        try:
            res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
                ctypes.c_long(tid), ctypes.py_object(exctype)
            )
            if res > 1:  # oops — undo, we hit the wrong/too-many state(s)
                ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(tid), None)
        except Exception:  # noqa: BLE001 — interruption is best-effort
            pass

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._worker_tid = threading.get_ident()
        overall_success = True

        try:
            for script_id, plugin_info, params in self._pipeline:
                if self._stop_requested:
                    self.log_message.emit(
                        f'Pipeline stopped before running "{plugin_info.name}".'
                    )
                    overall_success = False
                    break

                resolved_params = self._resolve_linked_params(plugin_info, params)

                self.script_started.emit(script_id)
                self.log_message.emit(f'--- Running "{plugin_info.name}" ---')

                success, outputs = self._run_script(script_id, plugin_info, resolved_params)

                if outputs:
                    self._context.set_outputs(script_id, outputs)

                self.script_finished.emit(script_id, success)

                if not success:
                    overall_success = False
                    if not self._stop_requested:
                        self.log_message.emit(
                            f'"{plugin_info.name}" finished with an error. Pipeline stopped.'
                        )
                    break
        except _PipelineCancelled:
            # A cancellation injected by stop() fired between scripts.
            overall_success = False
        finally:
            # No script is running now, so no more async exceptions should be
            # aimed at this thread.
            self._worker_tid = None

        self.pipeline_done.emit(overall_success and not self._stop_requested)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_linked_params(
        self, plugin_info: Any, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Return a copy of *params* with any ``link``-ed values refreshed
        from the current pipeline context."""
        resolved = dict(params)
        for param in plugin_info.parameters or []:
            link = param.get('link')
            name = param.get('name')
            if not link or not name:
                continue
            linked_val = _resolve_link(link, self._context.as_dict())
            if linked_val is not None:
                resolved[name] = linked_val
        return resolved

    def _run_script(
        self, script_id: str, plugin_info: Any, params: Dict[str, Any]
    ) -> Tuple[bool, Dict[str, Any]]:
        """Execute a single script in-process and return ``(success, outputs)``.

        The script's source is compiled and ``exec()``'d in a fresh ``{}``
        namespace so module-level state does not persist across runs. The
        ``run()`` (or ``main()``) function found in that namespace is called
        with the resolved *params* dict. ``sys.stdout`` and ``sys.stderr`` are
        temporarily redirected to ``StdoutCapture`` so ``print()`` output flows
        to the UI log.
        """
        entry_point = plugin_info.entry_point
        script_dir = os.path.dirname(entry_point)

        # Read and compile the script source.
        try:
            with open(entry_point, 'r', encoding='utf-8') as f:
                source = f.read()
        except OSError as e:
            self.log_message.emit(
                f'Could not read the script "{entry_point}": {e}'
            )
            return False, {}

        try:
            code = compile(source, entry_point, 'exec')
        except SyntaxError as e:
            self.log_message.emit(
                f'Syntax error in "{plugin_info.name}": {e}'
            )
            return False, {}

        # Set up stdout/stderr capture and working directory.
        capture = StdoutCapture(self._handle_output_line)
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        old_cwd = os.getcwd()

        outputs: Dict[str, Any] = {}
        success = True

        try:
            sys.stdout = capture  # type: ignore[assignment]
            sys.stderr = capture  # type: ignore[assignment]
            os.chdir(script_dir)

            # Execute in a fresh namespace so module-level variables do not
            # persist between runs. __name__ is intentionally NOT '__main__'
            # so that ``if __name__ == '__main__':`` blocks are skipped.
            namespace: Dict[str, Any] = {
                '__name__': '',
                '__file__': entry_point,
            }
            exec(code, namespace)  # noqa: S102

            # Find the entry-point function: run() takes priority over main().
            run_fn = namespace.get('run') or namespace.get('main')
            if run_fn is None or not callable(run_fn):
                self.log_message.emit(
                    f'"{plugin_info.name}" does not define a run(params) or main(params) function.'
                )
                return False, {}

            # Detect whether the function accepts a ctx argument.
            try:
                sig = inspect.signature(run_fn)
                wants_ctx = len(sig.parameters) >= 2
            except (ValueError, TypeError):
                wants_ctx = False

            if wants_ctx:
                ctx = ScriptContext(self._cancel_event, self._handle_output_line)
                result = run_fn(params, ctx)
            else:
                result = run_fn(params)

            outputs = result if isinstance(result, dict) else {}

        except _PipelineCancelled:
            # Injected by stop(): interrupt the running script cleanly.
            success = False
        except SystemExit as e:
            exit_code = e.code
            if exit_code not in (None, 0):
                self.log_message.emit(
                    f'"{plugin_info.name}" finished with an error (sys.exit({exit_code})).'
                )
                success = False
        except Exception as e:  # noqa: BLE001
            self.log_message.emit(
                f'Error in "{plugin_info.name}": {type(e).__name__}: {e}'
            )
            success = False
        finally:
            capture.flush()
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            try:
                os.chdir(old_cwd)
            except OSError:
                pass

        if self._stop_requested and success:
            self.log_message.emit(f'"{plugin_info.name}" cancelled by the user.')
            success = False

        return success, outputs

    def _handle_output_line(self, line: str) -> None:
        """Route a line emitted by a running script to the appropriate signal.

        ``PROGRESS:<number>`` lines only drive the progress indicator — they are
        NOT forwarded to the log, so the progress status updates in place instead
        of piling up raw ``PROGRESS:N`` lines. All other lines go to the log.
        """
        if line.startswith('PROGRESS:'):
            try:
                pct = float(line[9:])
                self.progress_changed.emit(max(0, min(100, int(pct))))
            except ValueError:
                pass
            return
        self.log_message.emit(line)
